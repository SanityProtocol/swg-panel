#!/usr/bin/env bash
# uninstall.sh — interactive, component-by-component remover for swg-panel.
#
# Detects every installed entity on this box — the bare-metal panel, a bare-metal node,
# a Docker deployment, AmneziaWG, WireGuard, and EACH installed turn-proxy server — lists
# them, then loops through and asks "uninstall or keep?" for each one. Nothing is removed
# without a yes. Run as root. --dry-run prints the plan and changes nothing; --yes assumes
# yes to every component (still asks the destructive sub-questions unless those are preset).
set -uo pipefail   # not -e: an uninstaller should keep going even if a piece is gone

DRYRUN=false; ASSUME_YES=false
for a in "$@"; do case "$a" in --dry-run) DRYRUN=true;; -y|--yes) ASSUME_YES=true;; esac; done

c(){ printf '\033[%sm' "$1"; }
info(){ echo "$(c '38;5;39')▸$(c 0) $*"; }   # universal flags: ▸ light-blue, :: blue, ✓ green, ! brown, ✗ red
sub(){  echo "$(c '38;5;33')::$(c 0) $*"; }
ok(){   echo "$(c '0;32')✓$(c 0) $*"; }
warn(){ echo "$(c '38;5;130')!$(c 0) $*" >&2; }
die(){  echo "$(c '0;31')✗ $*$(c 0)" >&2; exit 1; }
b(){ printf '\033[1m%s\033[0m' "$*"; }
run(){ if $DRYRUN; then echo "    [dry] $*"; else "$@"; fi; }
rmrf(){ local p; for p in "$@"; do if [ -e "$p" ] || [ -L "$p" ]; then run rm -rf "$p"; fi; done; }
# ask_yn <prompt> <default> <outvar>  — preset outvar (env) or --yes skips the prompt
ask_yn(){ local v p="$1" d="${2:-n}"; if [ -n "${!3:-}" ]; then return; fi
  if ! { true </dev/tty; } 2>/dev/null; then printf -v "$3" '%s' "$d"; return; fi   # /dev/tty not openable (no controlling terminal) → default, no leaked error
  read -rp "$p ($([ "$d" = y ] && echo 'Y/n' || echo 'y/N')): " v </dev/tty || true
  v="${v:-$d}"; case "$v" in [Yy]*) printf -v "$3" yes;; *) printf -v "$3" no;; esac; }
# ask_comp <label> — the per-component yes/no (honours --yes); returns 0 = uninstall
ask_comp(){ local v verb="${3:-Uninstall}"; $ASSUME_YES && return 0
  if ! { true </dev/tty; } 2>/dev/null; then return 1; fi   # no usable tty, not --yes => keep
  read -rp "  $verb $(b "$1")${2:+  ($(c '0;90')$2$(c 0))}? (y/N): " v </dev/tty || true
  case "$v" in [Yy]*) return 0;; *) return 1;; esac; }

[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && info "DRY RUN — nothing will be changed."

DOCKER_DIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"
TURN_DIR="${TURN_DIR:-/opt/vk-turn-proxy}"
SD="${SYSTEMD_DIR:-/etc/systemd/system}"   # overridable for testing
DOCKER_DATA_DEL=""; DOCKER_KEEP_CONFS=""   # docker data-dir fate — decided up front, applied after teardown
DOMAIN=""
[ -f /etc/nginx/sites-available/swg-panel.conf ] && \
  DOMAIN="$(sed -n 's/[[:space:]]*server_name[[:space:]]\+\([^;]*\);.*/\1/p' /etc/nginx/sites-available/swg-panel.conf | head -n1 | tr -d ' ')"

# ───────────────────────── removal actions ─────────────────────────
REMOVED_PANEL=false; REMOVED_NODE=false

rm_panel(){
  info "Removing swg-panel (control panel)"
  if [ -e $SD/swg-panel-server.service ]; then run systemctl disable --now swg-panel-server; fi
  # one-click self-update bits the panel installed (mk_update_unit): units, wrapper, and the env drop-in
  if [ -e $SD/swg-update.path ]; then run systemctl disable --now swg-update.path 2>/dev/null || true; fi
  rmrf $SD/swg-panel-server.service $SD/swg-panel-server.service.d \
       $SD/swg-update.service $SD/swg-update.path /usr/local/bin/swg-update
  run systemctl daemon-reload
  rmrf /etc/nginx/sites-enabled/swg-panel.conf /etc/nginx/sites-available/swg-panel.conf \
       /etc/nginx/conf.d/swg-panel.conf /etc/nginx/.htpasswd-swg
  command -v nginx >/dev/null 2>&1 && { run nginx -t && run systemctl reload nginx || warn "reload nginx manually if it's running"; }
  if [ -n "$DOMAIN" ] && [ "$DOMAIN" != "_" ]; then
    for a in /root/.acme.sh/acme.sh "${HOME:-/root}/.acme.sh/acme.sh" "$(command -v acme.sh 2>/dev/null || true)"; do
      [ -n "$a" ] && [ -x "$a" ] && { info "Removing acme.sh renewal for $DOMAIN"; run "$a" --remove -d "$DOMAIN" --ecc; break; }
    done
  fi
  rmrf /opt/swg-panel /etc/swg-panel /var/www/wgstats /var/www/acme
  # default NO = keep the roster for a future re-install (matches the docker data-dir prompt); yes = wipe it
  local PANEL_DATA_DEL="${PANEL_DATA_DEL:-}"
  ask_yn "  Delete the data dir /var/lib/swg-panel (users, peers, nodes)?" n PANEL_DATA_DEL
  if [ "$PANEL_DATA_DEL" = yes ]; then rmrf /var/lib/swg-panel
  elif [ -d /var/lib/swg-panel ]; then
    rmrf /var/lib/swg-panel/.ssh /var/lib/swg-panel/configs            # keep the roster; never leave secrets at rest
    ok "Kept /var/lib/swg-panel (users, peers, nodes) for a future re-install"
  fi
  if id swgpanel >/dev/null 2>&1; then run userdel swgpanel; fi
  REMOVED_PANEL=true; ok "swg-panel removed"
}

# Tell the panel this node is going away (the "goodbye" signal) so it removes itself cleanly —
# using the node's own bearer token + panel URL from its config. Best-effort: if the panel is
# unreachable, the operator can Force-remove it from the Nodes screen instead.
# _goodbye_post <panel-url> <token> <verify:yes|no> — POST the node's bearer token to /api/node/goodbye
_goodbye_post(){
  local url="$1" tok="$2" verify="$3"
  [ -n "$url" ] && [ -n "$tok" ] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  info "Signing off from the panel…"
  python3 - "$url" "$tok" "$verify" <<'PY'
import ssl, sys, http.client, urllib.request
url = sys.argv[1].rstrip("/") + "/api/node/goodbye"; tok = sys.argv[2]; verify = sys.argv[3] == "yes"
ctx = ssl.create_default_context()
if not verify:                                 # self-signed / pinned panel: don't verify for the goodbye
    ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request(url, data=b"{}", method="POST",
                             headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json",
                                      "User-Agent": "swg-noded"})   # urllib's default Python-urllib UA gets 403'd by some WAFs
# The panel removes the node when it RECEIVES the request (node_remove runs before the reply), so a
# truncated/5xx response from a proxy in front still means it landed. exit 0 = clean, 2 = uncertain
# (got an error response, node probably dropped), 1 = never reached the panel.
try:
    r = urllib.request.urlopen(req, timeout=10, context=ctx)
    try: r.read()
    except http.client.IncompleteRead: pass
    sys.exit(0)
except urllib.error.HTTPError as e:
    if e.code in (200, 404): sys.exit(0)        # removed / already gone
    if 500 <= e.code <= 599: sys.exit(2)        # proxy/gateway error — request reached the panel, node likely dropped
    sys.stderr.write("HTTP %s\n" % e.code); sys.exit(1)   # 401 etc — rejected, not removed
except Exception as e:
    sys.stderr.write(str(e) + "\n"); sys.exit(1)
PY
  case $? in
    0) ok "Panel notified — the node will drop itself.";;
    2) warn "Panel returned a gateway error but the node was likely dropped — check the Nodes screen (Force-remove if it's still listed).";;
    *) warn "Couldn't reach the panel; Force-remove the node from the Nodes screen instead.";;
  esac
}
# bare-metal node — read the panel URL + token from its config.json
node_goodbye(){
  local cfg=/etc/swg-agent/config.json
  [ -f "$cfg" ] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  local url tok verify
  url="$(python3 -c 'import json,sys;print((json.load(open(sys.argv[1])).get("panel") or {}).get("url",""))' "$cfg" 2>/dev/null)"
  tok="$(python3 -c 'import json,sys;print((json.load(open(sys.argv[1])).get("panel") or {}).get("token",""))' "$cfg" 2>/dev/null)"
  verify="$(python3 -c 'import json,sys;print("yes" if (json.load(open(sys.argv[1])).get("panel") or {}).get("verify",True) else "no")' "$cfg" 2>/dev/null)"
  _goodbye_post "$url" "$tok" "$verify"
}
# docker node — the token + panel URL live in the deployment .env (config.json is inside the container)
docker_node_goodbye(){
  local env="$DOCKER_DIR/.env"; [ -f "$env" ] || return 0
  local url tok verify
  url="$(sed -n 's/^PANEL_URL=//p' "$env" | head -1)"; url="${url%\"}"; url="${url#\"}"
  tok="$(sed -n 's/^NODE_TOKEN=//p' "$env" | head -1)"; tok="${tok%\"}"; tok="${tok#\"}"
  verify="$(sed -n 's/^TLS_VERIFY=//p' "$env" | head -1)"; verify="${verify%\"}"; verify="${verify#\"}"
  [ "$verify" = yes ] || verify=no
  # A co-located master's node signs off to its OWN panel. If that panel was already removed
  # earlier in this same run (master teardown removes swg-panel before swg-node), the goodbye
  # would just hit a dead local port — skip it instead of printing a scary connection error.
  local host="${url#*://}"; host="${host%%/*}"; host="${host%%:*}"
  case "$host" in swg-panel|127.0.0.1|localhost|::1)
    if ! docker_running swg-panel; then
      info "Local panel already removed — skipping node sign-off (Force-remove the node in the panel later if it persists)."
      return 0
    fi ;;
  esac
  _goodbye_post "$url" "$tok" "$verify"
}

rm_node(){
  info "Removing swg-node (bare-metal entry server)"
  node_goodbye   # signal the panel before we tear down the config it needs
  if [ -e $SD/swg-noded.service ]; then run systemctl disable --now swg-noded; fi
  rmrf $SD/swg-noded.service; run systemctl daemon-reload
  rmrf /opt/swg-agent /opt/swg-noded /srv/swg-queue /var/log/swg-agent /var/lib/swg-noded /var/lib/swg-recovery /etc/sudoers.d/swg-agent
  rmrf /etc/swg-agent   # turn-proxy.json here is just a panel-facing record; a kept turn-proxy keeps running
  for u in swgpush swgagent; do if id "$u" >/dev/null 2>&1; then run userdel -r "$u"; fi; done
  REMOVED_NODE=true; ok "swg-node removed"
}

# swg-panel and swg-node are SEPARATE containers — remove each on its own. The shared
# deployment dir / network / images / data are only torn down once BOTH are gone.
docker_running(){ command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$1"; }
_rm_node_data(){  rmrf "$DOCKER_DIR/data/node" "$DOCKER_DIR/data/node-confs"; }      # node-only state + iface confs
_rm_panel_data(){ rmrf "$DOCKER_DIR/data/etc" "$DOCKER_DIR/data/lib" "$DOCKER_DIR/data/stats"; }  # login/roster/certs
ask_full_data_fate(){   # the LAST swg container is going → decide the WHOLE data dir up front (before teardown)
  local desc=""
  [ -d "$DOCKER_DIR/data/lib" ] && desc="login, roster (users+peers), "
  [ -d "$DOCKER_DIR/data/etc" ] && desc="${desc}nodes, certs, "
  [ -d "$DOCKER_DIR/data/node-confs" ] && desc="${desc}interface configs / peers, "
  desc="${desc%, }"; [ -n "$desc" ] || desc="state"
  ask_yn "  Delete the data dir $DOCKER_DIR/data ($desc)?" n DOCKER_DATA_DEL
  DOCKER_KEEP_CONFS=""
  if [ "$DOCKER_DATA_DEL" = yes ] && [ -d "$DOCKER_DIR/data/node-confs" ]; then
    ask_yn "  Keep at least the peers? Leaves data/node-confs (keys + peers) so a future install can re-onboard them." y DOCKER_KEEP_CONFS
  fi
}
apply_full_data_fate(){   # run AFTER teardown, using the decision captured by ask_full_data_fate
  if [ "$DOCKER_DATA_DEL" != yes ]; then
    rmrf "$DOCKER_DIR/.env" "$DOCKER_DIR/docker-compose.yml" "$DOCKER_DIR/Dockerfile" "$DOCKER_DIR/Dockerfile.node" \
         "$DOCKER_DIR/.dockerignore" "$DOCKER_DIR/VERSION" "$DOCKER_DIR/docker" "$DOCKER_DIR/vendor" \
         "$DOCKER_DIR/swg-panel-server" "$DOCKER_DIR/swg-agent" "$DOCKER_DIR/swg-noded" \
         "$DOCKER_DIR/index.html" "$DOCKER_DIR/app.css" "$DOCKER_DIR/app.js" "$DOCKER_DIR/reconcile.js"
    ok "Kept $DOCKER_DIR/data for a future reinstall"
  elif [ "$DOCKER_KEEP_CONFS" = yes ]; then
    # keep ONLY the interface confs (the peers) — drop everything else
    run sh -c "find '$DOCKER_DIR' -mindepth 1 -maxdepth 1 ! -name data -exec rm -rf {} + 2>/dev/null; find '$DOCKER_DIR/data' -mindepth 1 -maxdepth 1 ! -name node-confs -exec rm -rf {} + 2>/dev/null"
    ok "Kept $DOCKER_DIR/data/node-confs — peers re-onboardable; everything else removed"
  else rmrf "$DOCKER_DIR"; fi
}
docker_cleanup_if_last(){   # shared bits (network/images/data dir) — only once NO swg container remains
  if docker_running swg-panel || docker_running swg-node; then return 0; fi
  if command -v docker >/dev/null 2>&1; then
    local DC=""; if docker compose version >/dev/null 2>&1; then DC="docker compose"; elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"; fi
    [ -n "$DC" ] && [ -f "$DOCKER_DIR/docker-compose.yml" ] && run sh -c "cd '$DOCKER_DIR' && $DC down --remove-orphans >/dev/null 2>&1 || true"   # drop the network
    local RMI="${REMOVE_DOCKER_IMAGES:-}"; ask_yn "  Remove the pulled swg-panel / swg-node images too?" n RMI
    [ "$RMI" = yes ] && run sh -c 'docker rmi ghcr.io/sanityprotocol/swg-panel:latest ghcr.io/sanityprotocol/swg-node:latest swg-panel-docker-swg-panel swg-panel-docker-swg-node >/dev/null 2>&1 || true'
  fi
  apply_full_data_fate
}
rm_docker_panel(){ info "Removing Docker panel container (swg-panel)"
  local DELP=""
  if docker_running swg-node; then    # node stays → only the panel's OWN data is in play (decide now)
    ask_yn "  Delete the panel data (login, roster (users+peers), nodes, certs)? The node's interface configs are kept." n DELP
  else ask_full_data_fate; fi         # panel is the last container → the whole data dir
  run sh -c 'docker rm -f swg-panel >/dev/null 2>&1 || true'
  if docker_running swg-node; then
    [ "$DELP" = yes ] && { _rm_panel_data; info "  Removed the panel data; node interface configs untouched."; } \
                      || info "  Kept the panel data; node interface configs untouched."
  else docker_cleanup_if_last; fi     # applies the data-dir decision captured above
  ok "swg-panel container removed"; }
rm_docker_node(){  info "Removing Docker node container (swg-node)"
  local KNODE=""
  if docker_running swg-panel; then   # master/panel stays → only the NODE's own data is in play (decide now)
    ask_yn "  Keep the node's interface configs (peers)? Leaves data/node-confs so a future install can re-onboard them." y KNODE
  else ask_full_data_fate; fi         # node is the last container → the whole data dir
  docker_node_goodbye                 # sign off to the panel (token + URL from .env) before teardown
  run sh -c 'docker rm -f swg-node >/dev/null 2>&1 || true'
  run sh -c 'ids=$(docker ps -aq --filter name=swg-turn- 2>/dev/null); [ -n "$ids" ] && docker rm -f $ids >/dev/null 2>&1 || true'   # this node's turn-proxy containers
  # a HOST-networking node creates its wg/awg netdevs in the HOST namespace; they survive `docker rm` → delete them
  for _c in "$DOCKER_DIR/data/node-confs/"*.conf; do [ -f "$_c" ] || continue; _n="$(basename "$_c" .conf)"
    command -v ip >/dev/null 2>&1 && ip link show "$_n" >/dev/null 2>&1 && { run ip link delete dev "$_n"; info "  removed leftover host interface $(b "$_n")"; }; done
  if docker_running swg-panel; then
    [ "$KNODE" = yes ] && info "  Kept $DOCKER_DIR/data/node-confs (peers re-onboardable); panel data untouched." \
                       || { _rm_node_data; info "  Removed the node's interface configs; panel data untouched."; }
  else docker_cleanup_if_last; fi     # applies the data-dir decision captured above
  ok "swg-node container removed"; }
rm_docker_files(){ info "Removing the Docker deployment files ($DOCKER_DIR)"; ask_full_data_fate; apply_full_data_fate; rmrf /var/lib/swg-recovery; ok "Docker deployment files removed"; }

down_ifaces(){ local dir="$1" tool="$2" f n              # quietly bring each interface down (wg/awg-quick is noisy)
  for f in "$dir"/*.conf; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"
    $DRYRUN && { echo "    [dry] $tool down $n"; continue; }
    { command -v "$tool" >/dev/null 2>&1 && "$tool" down "$n"; ip link delete "$n"; } >/dev/null 2>&1 || true; done; }
# Down each interface + delete its .conf, printing ONE green ✓ line (name · address · port) — used by the
# peer-removal components (down_ifaces above is the quiet, no-display version used before purging a package).
remove_ifaces(){ local dir="$1" tool="$2" f n addr port
  for f in "$dir"/*.conf; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"
    addr="$(awk -F= 'tolower($1)~/address/{gsub(/[ \t]/,"",$2);split($2,a,",");print a[1];exit}' "$f" 2>/dev/null)"
    port="$(awk -F= 'tolower($1)~/listenport/{gsub(/[ \t]/,"",$2);print $2;exit}' "$f" 2>/dev/null)"
    if $DRYRUN; then echo "    [dry] down + remove $n"
    else { command -v "$tool" >/dev/null 2>&1 && "$tool" down "$n"; ip link delete "$n"; } >/dev/null 2>&1 || true; rm -f "$f"; fi
    printf '    %s✓ %s%s%s%s\n' "$(c '0;32')" "$n" "$(c 0)" "${addr:+ · $addr}" "${port:+ · :$port}"
  done; }

# Peers (the interface .conf files) and the wg/awg PACKAGE are removed INDEPENDENTLY — so you can wipe the
# panel + peers but KEEP the wg/awg service installed (or remove the package but keep the configs). Each is
# its own component in the list, so the peer question is always asked regardless of the package answer.
rm_awg_peers(){
  info "Removing AmneziaWG interface configs (peers)"
  remove_ifaces /etc/amnezia/amneziawg awg-quick
  rmrf /etc/amnezia/amneziawg
}
rm_awg_pkg(){
  info "Uninstalling the AmneziaWG package (kernel module + tools)"
  down_ifaces /etc/amnezia/amneziawg awg-quick      # if the configs were kept, bring the ifaces down before pulling the module
  if command -v apt-get >/dev/null 2>&1; then
    run apt-get purge -y amneziawg amneziawg-tools amneziawg-dkms
    run add-apt-repository -y --remove ppa:amnezia/ppa; run apt-get autoremove -y
  else warn "Non-apt system — remove the amneziawg packages with your package manager."; fi
  ok "AmneziaWG package removed"
}
rm_wg_peers(){
  info "Removing WireGuard interface configs (peers)"
  remove_ifaces /etc/wireguard wg-quick
  rmrf /etc/wireguard
}
rm_wg_pkg(){
  info "Uninstalling the WireGuard package"
  down_ifaces /etc/wireguard wg-quick
  if command -v apt-get >/dev/null 2>&1; then run apt-get purge -y wireguard wireguard-tools; run apt-get autoremove -y
  else warn "Non-apt system — remove the wireguard packages with your package manager."; fi
  ok "WireGuard package removed"
}

rm_turn(){ local unit="$1" name fork
  name="$(basename "$unit" .service)"; fork="${name#vk-turn-proxy-}"
  info "Removing turn-proxy ($fork)"
  [ -e "$unit" ] && run systemctl disable --now "$name"
  rmrf "$unit" "$TURN_DIR/$fork"; run systemctl daemon-reload
  ls $SD/vk-turn-proxy-"${fork%-*}"-*.service >/dev/null 2>&1 || rmrf "$TURN_DIR/.bin/${fork%-*}"   # fork's last instance → drop its shared binary
  # last one out removes the shared dir + the panel-facing record
  ls $SD/vk-turn-proxy-*.service >/dev/null 2>&1 || rmrf "$TURN_DIR" /etc/swg-agent/turn-proxy.json
  ok "turn-proxy ($fork) removed"
}

# ───────────────────────── detect installed components ─────────────────────────
declare -a CLABEL=() CDETAIL=() CFN=() CARG=() CHINT=() CVERB=()   # init empty (not just `declare -a`) — bash 5.2 + set -u treats a never-assigned array as unbound for ${#arr[@]}
# ── richer component details: interface names+ports, node endpoints, turn-proxy ports ──
iface_list(){  # <dir> -> "awg0:51820, awg505:51234" (interface name + ListenPort from each .conf)
  local dir="$1" out="" f n p
  for f in "$dir"/*.conf; do [ -f "$f" ] || continue
    n="$(basename "$f" .conf)"
    p="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$f" 2>/dev/null | head -1)"
    out="${out:+$out, }${n}${p:+:$p}"
  done
  printf '%s' "${out:-$dir}"
}
bm_node_detail(){  # bare-metal node: endpoint + interfaces from config.json
  local cfg=/etc/swg-agent/config.json ep ifs
  if [ -f "$cfg" ] && command -v python3 >/dev/null 2>&1; then
    ep="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("endpoint_host",""))' "$cfg" 2>/dev/null)"
    ifs="$(python3 -c 'import json,sys;print(", ".join((json.load(open(sys.argv[1])).get("interfaces") or {}).keys()))' "$cfg" 2>/dev/null)"
  fi
  printf 'swg-noded%s%s' "${ep:+ · endpoint $ep}" "${ifs:+ · ifaces: $ifs}"
}
docker_node_detail(){  # docker node: name/endpoint + interfaces (name:port) from the deployment .env
  local env="$DOCKER_DIR/.env" ep nm ni ifs
  if [ -f "$env" ]; then
    ep="$(sed -n 's/^NODE_ENDPOINT=//p' "$env" | head -1 | tr -d '"')"
    nm="$(sed -n 's/^NODE_NAME=//p' "$env" | head -1 | tr -d '"')"
    ni="$(sed -n 's/^NODE_IFACES=//p' "$env" | head -1 | tr -d '"')"
    if [ -n "$ni" ]; then ifs="$(printf '%s' "$ni" | tr ',' '\n' | cut -d: -f1,2 | tr '\n' ',' | sed 's/,$//; s/,/, /g')"
    else ifs="$(sed -n 's/^NODE_IFACE=//p' "$env" | head -1 | tr -d '"')"; fi
  fi
  printf 'container swg-node%s%s%s' "${nm:+ · $nm}" "${ep:+ · endpoint $ep}" "${ifs:+ · ifaces: $ifs}"
}
turn_exec_env(){  # <unit> -> "<listen>\t<connect>", resolving the EnvironmentFile (turn.env) form
  local unit="$1" exe envf
  exe="$(sed -n 's/^ExecStart=//p' "$unit" 2>/dev/null | head -1)"
  case "$exe" in
    *'${SWG_'*)   # env-file form — values live in turn.env, not the ExecStart
      envf="$(sed -n 's/^EnvironmentFile=-\{0,1\}//p' "$unit" 2>/dev/null | head -1)"
      printf '%s\t%s' "$(sed -n 's/^SWG_LISTEN=//p' "$envf" 2>/dev/null | head -1)" "$(sed -n 's/^SWG_CONNECT=//p' "$envf" 2>/dev/null | head -1)" ;;
    *)            # legacy baked-ExecStart form
      printf '%s\t%s' "$(printf '%s' "$exe" | sed -n 's/.*-listen[ =]\{1,\}\([^ ]*\).*/\1/p')" "$(printf '%s' "$exe" | sed -n 's/.*-connect[ =]\{1,\}\([^ ]*\).*/\1/p')" ;;
  esac
}
turn_fwd_iface(){  # connect "ip:port" -> the wg/awg interface whose ListenPort matches the port (else empty)
  local cp="${1##*:}" f lp
  for f in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf; do [ -f "$f" ] || continue
    lp="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$f" 2>/dev/null | head -1)"
    [ -n "$lp" ] && [ "$lp" = "$cp" ] && { basename "$f" .conf; return; }
  done
}
turn_detail(){  # <unit> -> "1.2.3.4:57000 → 127.0.0.1:51820 (wg7)" — the listen → connect (iface) style used elsewhere
  local lis con fw; IFS="$(printf '\t')" read -r lis con < <(turn_exec_env "$1")
  fw="$(turn_fwd_iface "$con")"
  printf '%s%s%s' "${lis:-?}" "${con:+ → $con}" "${fw:+ ($fw)}"
}
add(){ CLABEL+=("$1"); CDETAIL+=("$2"); CFN+=("$3"); CARG+=("${4:-}"); CHINT+=("${5:-}"); CVERB+=("${6:-Uninstall}"); }   # $6 = question verb (default Uninstall)
turn_listen(){ local lis con; IFS="$(printf '\t')" read -r lis con < <(turn_exec_env "$1"); printf '%s' "$lis"; }

[ -d /opt/swg-panel ] || [ -f $SD/swg-panel-server.service ] && \
  add "Bare-metal swg-panel" "control panel (/opt/swg-panel)" rm_panel
[ -d /opt/swg-noded ] || [ -d /opt/swg-agent ] || [ -f $SD/swg-noded.service ] && \
  add "Bare-metal node (swg-node)" "$(bm_node_detail)" rm_node

# Docker: the panel and node are separate containers — offer each independently. If the
# deployment dir exists but neither container does, offer a files-only cleanup.
DPANEL=false; DNODE=false
if command -v docker >/dev/null 2>&1; then
  docker_running swg-panel && DPANEL=true
  docker_running swg-node  && DNODE=true
fi
$DPANEL && add "Docker panel (swg-panel)" "container swg-panel" rm_docker_panel
$DNODE  && add "Docker node (swg-node)"   "$(docker_node_detail)"   rm_docker_node
if ! $DPANEL && ! $DNODE && { [ -f "$DOCKER_DIR/docker-compose.yml" ] || [ -f "$DOCKER_DIR/.env" ]; }; then
  add "Docker deployment (files)" "$DOCKER_DIR" rm_docker_files
fi

# NB: grep on a here-string, NOT 'dpkg -l | grep -q' — under pipefail, grep -q exits on first match and the
# still-writing dpkg gets SIGPIPE (141), so the pipe reports failure even on a match (amneziawg sorts early in
# dpkg -l, so it always tripped this; wireguard sorts late and usually slipped through).
pkg_ii(){ grep -qE "$1" <<< "$(dpkg -l 2>/dev/null)"; }
# interface configs (the PEERS) vs the system PACKAGE — detected + offered SEPARATELY
awg_ifaces(){ ls /etc/amnezia/amneziawg/*.conf >/dev/null 2>&1 || ls $SD/awg*.service >/dev/null 2>&1; }
wg_ifaces(){  ls /etc/wireguard/*.conf >/dev/null 2>&1 || ls $SD/wg-quick@*.service >/dev/null 2>&1; }
awg_pkg(){ command -v dpkg >/dev/null 2>&1 && pkg_ii '^ii +amneziawg(-tools| |$)'; }
wg_pkg(){  command -v dpkg >/dev/null 2>&1 && pkg_ii '^ii +wireguard '; }
awg_ifaces && { _d="$(iface_list /etc/amnezia/amneziawg)"; add "AmneziaWG interface peers" "$_d" rm_awg_peers "" "$_d" Remove; }
awg_pkg    &&   add "AmneziaWG package (kernel module + tools)" "amneziawg · amneziawg-tools · amneziawg-dkms" rm_awg_pkg
wg_ifaces  && { _d="$(iface_list /etc/wireguard)";        add "WireGuard interface peers" "$_d" rm_wg_peers "" "$_d" Remove; }
wg_pkg     &&   add "WireGuard package (kernel module + tools)" "wireguard · wireguard-tools" rm_wg_pkg
true   # don't let the last &&-test leave a non-zero status

for unit in $(ls $SD/vk-turn-proxy-*.service 2>/dev/null || true); do
  add "$(basename "$unit" .service)" "$(turn_detail "$unit")" rm_turn "$unit" "$(turn_listen "$unit")"   # green service name + listen → connect (iface)
done

N=${#CLABEL[@]}
[ "$N" -gt 0 ] || die "swg-panel does not appear to be installed here (nothing to do)"

# ───────────────────────── list, then prompt per component ─────────────────────────
echo; info "Found these installed components:"; echo
for i in $(seq 0 $((N-1))); do printf '    %s%s%s  %s\n' "$(c '0;32')" "${CLABEL[$i]}" "$(c 0)" "$(c '0;90')${CDETAIL[$i]}$(c 0)"; done
echo
$ASSUME_YES && info "--yes: every component will be uninstalled (you'll still be asked the destructive sub-questions)." \
            || echo "  You'll be asked about each component one by one — nothing is removed without your yes."
echo

# Per component: ask "Uninstall X?"; if yes, the removal fn asks its own destructive sub-questions
# (keep peers / delete data dir) so the peers' fate is decided in context, not up front.
DID_REMOVE=(); DID_KEEP=()
for i in $(seq 0 $((N-1))); do
  if ask_comp "${CLABEL[$i]}" "${CHINT[$i]}" "${CVERB[$i]}"; then "${CFN[$i]}" "${CARG[$i]}"; DID_REMOVE+=("${CLABEL[$i]}")
  else info "Kept ${CLABEL[$i]}."; DID_KEEP+=("${CLABEL[$i]}"); fi
  echo
done

# group cleanup (shared by panel + agent) — only if we removed a bare-metal piece
if { $REMOVED_PANEL || $REMOVED_NODE; } && getent group swg >/dev/null 2>&1; then
  run groupdel swg 2>/dev/null || info "group 'swg' still in use — left in place."
fi
rmdir /etc/swg-agent 2>/dev/null || true

echo; echo "$(b '──────────────── SUMMARY ────────────────')"; echo
if [ "${#DID_REMOVE[@]}" -gt 0 ]; then echo "  $(b Removed):"
  for x in "${DID_REMOVE[@]}"; do echo "    $(c '0;31')✗$(c 0) $x"; done; fi
[ "${#DID_REMOVE[@]}" -gt 0 ] && [ "${#DID_KEEP[@]}" -gt 0 ] && echo
if [ "${#DID_KEEP[@]}" -gt 0 ]; then echo "  $(b Kept):"
  for x in "${DID_KEEP[@]}"; do echo "    $(c '0;32')•$(c 0) $x"; done; fi
echo
$DRYRUN && ok "DRY RUN — nothing was actually removed; re-run without --dry-run to apply." \
        || ok "Uninstall complete."
