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
ask_yn(){ local v p="$1" d="${2:-n}"
  # A PRESET answer (unattended run) is normalised exactly like a typed one. It used to be returned verbatim, so
  # the obvious FOO=y — the same letter the prompt offers as "Y/n" — was compared against "yes", didn't match, and
  # silently meant NO: an unattended uninstall with PANEL_DATA_DEL=y kept the data it was told to delete.
  if [ -n "${!3:-}" ]; then case "${!3}" in [Yy]*) printf -v "$3" yes;; *) printf -v "$3" no;; esac; return; fi
  if ! { true </dev/tty; } 2>/dev/null; then printf -v "$3" '%s' "$d"; return; fi   # /dev/tty not openable (no controlling terminal) → default, no leaked error
  read -rp "$p ($([ "$d" = y ] && echo 'Y/n' || echo 'y/N')): " v </dev/tty || true
  v="${v:-$d}"; case "$v" in [Yy]*) printf -v "$3" yes;; *) printf -v "$3" no;; esac; echo; }   # one trailing blank after the prompt
# ask_comp <label> — the per-component yes/no (honours --yes); returns 0 = uninstall
ask_comp(){ local v verb="${3:-Uninstall}"; $ASSUME_YES && return 0
  if ! { true </dev/tty; } 2>/dev/null; then return 1; fi   # no usable tty, not --yes => keep
  read -rp "  $verb $(b "$1")${2:+  ($(c '0;90')$2$(c 0))}? (y/N): " v </dev/tty || true
  case "$v" in [Yy]*) return 0;; *) return 1;; esac; }

[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && info "DRY RUN — nothing will be changed."

DOCKER_DIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"
TURN_DIR="${TURN_DIR:-/opt/vk-turn-proxy}"
WDTT_DIR="${WDTT_DIR:-/opt/swg-wdtt}"     # WDTT servers: per-instance config-dir (identity + passwords) + .bin/<fork> shared binaries
CSQTT_DIR="${CSQTT_DIR:-/opt/swg-csqtt}"  # csqtt servers: per-instance config-dir (password store) + .bin/<arch> shared binary
SD="${SYSTEMD_DIR:-/etc/systemd/system}"   # overridable for testing
# docker data-dir fate — decided up front, applied after teardown. `:-` so an UNATTENDED run's preset survives:
# a bare ="" clobbered the caller's DOCKER_DATA_DEL=y before ask_yn ever read it, so the data dir it was told to
# delete was kept — the same silent-preset class as the [Yy] normalisation in ask_yn, one layer further out.
DOCKER_DATA_DEL="${DOCKER_DATA_DEL:-}"; DOCKER_KEEP_CONFS="${DOCKER_KEEP_CONFS:-}"
DOMAIN=""
[ -f /etc/nginx/sites-available/swg-panel.conf ] && \
  DOMAIN="$(sed -n 's/[[:space:]]*server_name[[:space:]]\+\([^;]*\);.*/\1/p' /etc/nginx/sites-available/swg-panel.conf | head -n1 | tr -d ' ')"

# ───────────────────────── removal actions ─────────────────────────
REMOVED_PANEL=false; REMOVED_NODE=false

rm_panel(){
  info "Removing swg-panel (control panel)"
  if [ -e $SD/swg-panel-server.service ]; then run systemctl disable --now swg-panel-server; fi
  # swg-sub (the subscription surface) is a companion of the panel — remove it alongside
  if [ -e $SD/swg-sub.service ]; then run systemctl disable --now swg-sub; fi
  # swg-netctl (the panel's privileged network/TLS helper: .service + .path + .timer) — a companion of the panel
  for _nc in swg-netctl.path swg-netctl.timer swg-netctl.service; do [ -e "$SD/$_nc" ] && run systemctl disable --now "$_nc" 2>/dev/null || true; done
  # one-click self-update bits the panel installed (mk_update_unit): units, wrapper, and the env drop-in
  for _su in swg-update.timer swg-update.path; do [ -e "$SD/$_su" ] && run systemctl disable --now "$_su" 2>/dev/null || true; done
  rmrf $SD/swg-panel-server.service $SD/swg-panel-server.service.d $SD/swg-sub.service $SD/swg-sub.service.d \
       $SD/swg-netctl.service $SD/swg-netctl.path $SD/swg-netctl.timer /usr/local/bin/swg-netctl \
       $SD/swg-update.service $SD/swg-update.path $SD/swg-update.timer /usr/local/bin/swg-update /usr/local/bin/swg-update-check /var/lib/swg-update.stamp
  run systemctl daemon-reload
  rmrf /etc/nginx/sites-enabled/swg-panel.conf /etc/nginx/sites-available/swg-panel.conf \
       /etc/nginx/conf.d/swg-panel.conf /etc/nginx/.htpasswd-swg
  command -v nginx >/dev/null 2>&1 && { run nginx -t && run systemctl reload nginx || warn "reload nginx manually if it's running"; }
  if [ -n "$DOMAIN" ] && [ "$DOMAIN" != "_" ]; then
    for a in /root/.acme.sh/acme.sh "${HOME:-/root}/.acme.sh/acme.sh" "$(command -v acme.sh 2>/dev/null || true)"; do
      [ -n "$a" ] && [ -x "$a" ] && { info "Removing acme.sh renewal for $DOMAIN"; run "$a" --remove -d "$DOMAIN" --ecc; break; }
    done
  fi
  rmrf /opt/swg-panel /opt/swg-sub /etc/swg-panel /etc/swg-sub /var/www/wgstats /var/www/acme   # /etc/swg-sub = swg-sub's OWN tls dir; it was never referenced, so it survived every uninstall
  # default NO = keep the roster for a future re-install (matches the docker data-dir prompt); yes = wipe it
  local PANEL_DATA_DEL="${PANEL_DATA_DEL:-}"
  ask_yn "  Delete the data dir /var/lib/swg-panel (users, peers, nodes)?" n PANEL_DATA_DEL
  if [ "$PANEL_DATA_DEL" = yes ]; then rmrf /var/lib/swg-panel
  elif [ -d /var/lib/swg-panel ]; then
    rmrf /var/lib/swg-panel/.ssh /var/lib/swg-panel/configs            # keep the roster; never leave secrets at rest
    ok "Kept /var/lib/swg-panel (users, peers, nodes) for a future re-install"
    # The vault lives in the dir we just kept; the login it is wrapped under lives in /etc/swg-panel, which we
    # removed a few lines up. Say so HERE — this is the last moment the operator still has the old password.
    if [ -f /var/lib/swg-panel/subs/vault.json ]; then
      sub "  Your Encryption Vault is in there too — but the login it is sealed under is not (that lived in /etc/swg-panel)."
      sub "  A re-install mints a NEW password, so the panel will ask you to reconnect the vault with the OLD"
      sub "  password or your encryption key. Keep one of them, or your subscription links and escrowed"
      sub "  interface keys stay sealed."
    fi
  fi
  if id swgpanel >/dev/null 2>&1; then run userdel swgpanel; fi
  if id swgsub >/dev/null 2>&1; then run userdel swgsub; fi   # swg-sub's dedicated read-only user
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
except ConnectionResetError:
    # Covers http.client.RemoteDisconnected, which subclasses it. The panel removes the node BEFORE it
    # replies (see the note above), so a connection closed with no status line is the same "it landed"
    # case as the IncompleteRead handled just above, one step earlier. It was falling through to the
    # generic handler and reporting "never reached the panel" — while the panel's own event log recorded
    # 'Node uninstalled — kept for re-install'. Sending the operator to remove a node that is already
    # gone is worse than saying nothing.
    sys.exit(2)
except urllib.error.HTTPError as e:
    if e.code in (200, 404): sys.exit(0)        # removed / already gone
    if 500 <= e.code <= 599: sys.exit(2)        # proxy/gateway error — request reached the panel, node likely dropped
    sys.stderr.write("HTTP %s\n" % e.code); sys.exit(1)   # 401 etc — rejected, not removed
except Exception as e:
    sys.stderr.write(str(e) + "\n"); sys.exit(1)
PY
  case $? in
    0) ok "Panel notified — your peers are KEPT for a re-install (re-enroll with the same token to restore them). To purge for good, use Nodes → remove in the panel.";;
    2) warn "The panel closed the connection without a reply — it almost certainly ACTIONED the sign-off (it removes the node before responding). Check the Nodes screen to confirm.";;
    *) warn "Couldn't reach the panel; the node will just go offline there (your peers are kept). Remove it from the Nodes screen if you want it gone.";;
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
# POST proc-status (best-effort) — flashes a red "uninstalling" tag on the panel the moment teardown starts.
_proc_post(){  # <url> <token> <verify> <state>
  local url="$1" tok="$2" verify="$3" state="$4"
  { [ -n "$url" ] && [ -n "$tok" ] && command -v python3 >/dev/null 2>&1; } || return 0
  python3 - "$url" "$tok" "$verify" "$state" <<'PY' 2>/dev/null || true
import ssl, sys, json, urllib.request
url = sys.argv[1].rstrip("/") + "/api/node/proc-status"; tok = sys.argv[2]; verify = sys.argv[3] == "yes"; state = sys.argv[4]
ctx = ssl.create_default_context()
if not verify: ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request(url, data=json.dumps({"state": state}).encode(), method="POST",
                             headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json", "User-Agent": "swg-noded"})
try: urllib.request.urlopen(req, timeout=6, context=ctx).read()
except Exception: pass
PY
}
docker_node_uninstalling(){   # red "uninstalling" tag while a docker node tears down (token/URL from the .env)
  local env="$DOCKER_DIR/.env"; [ -f "$env" ] || return 0
  local url tok verify
  url="$(sed -n 's/^PANEL_URL=//p' "$env" | head -1)"; url="${url%\"}"; url="${url#\"}"
  tok="$(sed -n 's/^NODE_TOKEN=//p' "$env" | head -1)"; tok="${tok%\"}"; tok="${tok#\"}"
  verify="$(sed -n 's/^TLS_VERIFY=//p' "$env" | head -1)"; verify="${verify%\"}"; verify="${verify#\"}"; [ "$verify" = yes ] || verify=no
  _proc_post "$url" "$tok" "$verify" uninstalling
}

# Containers we took an interface over from — see the restore at the end of the run. config.json is the
# authoritative record, but on a DOCKER node it lives inside the node container and is gone after a recreate,
# so swg-noded also mirrors the map into its state dir, which is a bind mount the host can always read. Read
# both and dedupe: whichever exists wins, and a container named twice is started once.
adopted_ctrs(){ # adopted_ctrs <config.json> <adopted-containers.json>
  python3 - "$1" "$2" 2>/dev/null <<'PYADOPT' || true
import json, sys
out = []
try:
    with open(sys.argv[1]) as f:
        for _i, v in (json.load(f).get("interfaces") or {}).items():
            if isinstance(v, dict) and v.get("adopted_from"):
                out.append(v["adopted_from"])
except Exception:
    pass
try:
    with open(sys.argv[2]) as f:
        d = json.load(f)
    if isinstance(d, dict):
        out += [v for v in d.values() if isinstance(v, str) and v]
except Exception:
    pass
seen = set()
for c in out:
    if c and c not in seen:
        seen.add(c)
        print(c)
PYADOPT
}
# Append to the run-wide list (a box can carry a bare-metal AND a docker node), keeping it unique.
capture_adopted(){ local _n
  _n="$(adopted_ctrs "$1" "$2")"
  [ -n "$_n" ] && ADOPTED_CTRS="$(printf '%s\n%s\n' "${ADOPTED_CTRS:-}" "$_n" | awk 'NF && !seen[$0]++')"
  return 0; }

rm_node(){
  info "Removing swg-node (bare-metal entry server)"
  node_goodbye   # signal the panel before we tear down the config it needs
  if [ -e $SD/swg-noded.service ]; then run systemctl disable --now swg-noded; fi
  run systemctl unmask dnsmasq 2>/dev/null || true   # install masked the distro dnsmasq (node ran its own); restore it
  rmrf $SD/swg-noded.service; run systemctl daemon-reload
  # An interface TAKEN OVER from somebody else's container came with a promise: their server keeps serving, just
  # from here instead. Uninstalling ends that — we delete the interface further down — and the container it came
  # from is still stopped with restart=no, exactly as the take-over left it. Removing swgPanel then leaves the
  # operator with NO server at all: ours gone, theirs disabled and never told to come back. Capture the pairs now,
  # while the record still exists; the restore itself is deferred to the end of the run, past the interface
  # removal, or their container would come back to a port ours is still holding.
  capture_adopted /etc/swg-agent/config.json /var/lib/swg-noded/adopted-containers.json
  rmrf /opt/swg-agent /opt/swg-noded /srv/swg-queue /var/log/swg-agent /var/lib/swg-noded /var/lib/swg-recovery /etc/sudoers.d/swg-agent
  rmrf /etc/swg-agent   # turn-proxy.json here is just a panel-facing record; a kept turn-proxy keeps running
  for u in swgpush swgagent; do if id "$u" >/dev/null 2>&1; then run userdel -r "$u"; fi; done
  # NOT rm_node_netobjects here. This runs FIRST in the component list, while "keep my interfaces / turn-proxies /
  # WDTT servers" are offered later and default to keep — and those objects are their datapath. A kept WDTT server
  # runs with -no-nat, so its SNAT is precisely the swg-egress:<iface> rule this would delete: the server survives
  # the uninstall with no internet for any of its clients. Deferred to the end of the run, past every prompt.
  NEED_NETOBJ_SWEEP=true
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
  [ -d "$DOCKER_DIR/data/node/wdtt" ] && desc="${desc}WDTT identities + passwords, "   # same irrecoverable weight as the bare-metal /opt/swg-wdtt question
  [ -d "$DOCKER_DIR/data/node/csqtt" ] && desc="${desc}csqtt password stores, "        # csqtt has no keypair — the store IS what its clients authenticate against
  desc="${desc%, }"; [ -n "$desc" ] || desc="state"
  ask_yn "  Delete the data dir $DOCKER_DIR/data ($desc)?" n DOCKER_DATA_DEL
  DOCKER_KEEP_CONFS="${DOCKER_KEEP_CONFS:-}"      # keep a preset; only defined-ness is needed under set -u
  if [ "$DOCKER_DATA_DEL" = yes ] && [ -d "$DOCKER_DIR/data/node-confs" ]; then
    ask_yn "  Keep at least the peers? Leaves data/node-confs (keys + peers) so a future install can re-onboard them." y DOCKER_KEEP_CONFS
  fi
}
apply_full_data_fate(){   # run AFTER teardown, using the decision captured by ask_full_data_fate
  if [ "$DOCKER_DATA_DEL" != yes ]; then
    # KEEP .env so a plain `docker node` re-install recovers NODE_TOKEN / PANEL_URL on its own (peers re-sync
    # and the re-install lifecycle shows) — without it the box has no key and stays stuck "Uninstalled". Strip
    # panel secrets so no plain password is left at rest; compose + binaries are re-staged by the installer anyway.
    [ -f "$DOCKER_DIR/.env" ] && run sed -i -E '/^(PANEL_PASSWORD|CF_TOKEN|CF_ORIGIN_TOKEN|ACME_EMAIL)=/d' "$DOCKER_DIR/.env"
    rmrf "$DOCKER_DIR/docker-compose.yml" "$DOCKER_DIR/Dockerfile" "$DOCKER_DIR/Dockerfile.node" \
         "$DOCKER_DIR/.dockerignore" "$DOCKER_DIR/VERSION" "$DOCKER_DIR/docker" "$DOCKER_DIR/vendor" \
         "$DOCKER_DIR/swg-panel-server" "$DOCKER_DIR/swg-agent" "$DOCKER_DIR/swg-noded" \
         "$DOCKER_DIR/index.html" "$DOCKER_DIR/app.css" "$DOCKER_DIR/app.js" "$DOCKER_DIR/reconcile.js" \
         "$DOCKER_DIR/js"
    ok "Kept $DOCKER_DIR/data + .env (node token) for a future reinstall"
    return
  fi
  # CASES 2 & 3 — wiping the live data dir: first stash a recovery copy (node token + interface keys) under
  # $DOCKER_DIR.uninstalled-<ts> so a future re-install can recover this node from the leftover-identity list
  # (its peers re-sync from the panel). Panel / TLS secrets are stripped from the copy.
  if [ -f "$DOCKER_DIR/.env" ]; then
    _bak="$DOCKER_DIR.uninstalled-$(date +%Y%m%d-%H%M%S 2>/dev/null || echo bak)"
    run mkdir -p "$_bak/data"
    run cp -a "$DOCKER_DIR/.env" "$_bak/.env"
    [ -d "$DOCKER_DIR/data/node-confs" ] && run cp -a "$DOCKER_DIR/data/node-confs" "$_bak/data/node-confs"
    [ -d "$DOCKER_DIR/data/node" ] && run cp -a "$DOCKER_DIR/data/node" "$_bak/data/node"   # swg-noded state incl. turn-proxy.json → turn-proxies re-create on recovery
    run sed -i -E '/^(PANEL_PASSWORD|CF_TOKEN|CF_ORIGIN_TOKEN|ACME_EMAIL)=/d' "$_bak/.env"
    info "  saved a recovery copy (node token + interface keys + turn-proxies) to $(b "$_bak") — re-install and pick it from the recovery list"
  fi
  if [ "$DOCKER_KEEP_CONFS" = yes ]; then
    # CASE 2 — keep the peers (interface server keys) LIVE so existing client configs keep working
    run sh -c "find '$DOCKER_DIR' -mindepth 1 -maxdepth 1 ! -name data -exec rm -rf {} + 2>/dev/null; find '$DOCKER_DIR/data' -mindepth 1 -maxdepth 1 ! -name node-confs ! -name node -exec rm -rf {} + 2>/dev/null"
    ok "Kept $DOCKER_DIR/data/node-confs (peers) + node (turn-proxies) live; token recoverable from the backup"
  else
    # CASE 3 — wipe everything live; full recovery (token + interface keys) is in the backup
    rmrf "$DOCKER_DIR"
    ok "Removed $DOCKER_DIR — a recovery copy (token + interface keys) is kept for re-install"
  fi
}
docker_cleanup_if_last(){   # shared bits (network/images/data dir) — only once NO swg container remains
  if docker_running swg-panel || docker_running swg-node; then return 0; fi
  # host one-click updater units (install-docker's wire_host_updater) — remove now that no swg container remains
  for _su in swg-update.timer swg-update.path; do [ -e "/etc/systemd/system/$_su" ] && run systemctl disable --now "$_su" 2>/dev/null || true; done
  rmrf /etc/systemd/system/swg-update.service /etc/systemd/system/swg-update.path /etc/systemd/system/swg-update.timer /usr/local/bin/swg-update /usr/local/bin/swg-update-check /var/lib/swg-update.stamp
  run systemctl daemon-reload 2>/dev/null || true
  if command -v docker >/dev/null 2>&1; then
    local DC=""; if docker compose version >/dev/null 2>&1; then DC="docker compose"; elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"; fi
    # activate every profile so `down` stops profile-gated services too (swg-sub); plain `down` skips them and --remove-orphans won't (it's in the compose file, not an orphan)
    [ -n "$DC" ] && [ -f "$DOCKER_DIR/docker-compose.yml" ] && run sh -c "cd '$DOCKER_DIR' && COMPOSE_PROFILES=host,master,node,host-node $DC down --remove-orphans >/dev/null 2>&1 || true"   # drop the network + any straggler
    local RMI="${REMOVE_DOCKER_IMAGES:-}"; echo; ask_yn "  Remove the pulled swg-panel / swg-node images too?" n RMI
    [ "$RMI" = yes ] && run sh -c 'docker rmi ghcr.io/sanityprotocol/swg-panel:latest ghcr.io/sanityprotocol/swg-node:latest swg-panel-docker-swg-panel swg-panel-docker-swg-node >/dev/null 2>&1 || true'
  fi
  apply_full_data_fate
}
rm_docker_panel(){ info "Removing Docker panel container (swg-panel)"
  local DELP=""
  if docker_running swg-node; then    # node stays → only the panel's OWN data is in play (decide now)
    ask_yn "  Delete the panel data (login, roster (users+peers), nodes, certs)? The node's interface configs are kept." n DELP
  else ask_full_data_fate; fi         # panel is the last container → the whole data dir
  run sh -c 'docker rm -f swg-panel swg-sub >/dev/null 2>&1 || true'   # swg-sub is the panel's companion surface (a profile-gated service `down` won't stop) — remove it alongside
  if docker_running swg-node; then
    [ "$DELP" = yes ] && { _rm_panel_data; info "  Removed the panel data; node interface configs untouched."; } \
                      || info "  Kept the panel data; node interface configs untouched."
  else docker_cleanup_if_last; fi     # applies the data-dir decision captured above
  ok "swg-panel container removed"; }
rm_docker_node(){  info "Removing Docker node container (swg-node)"
  docker_node_uninstalling   # flash a red "uninstalling" tag on the panel before we tear down
  local KNODE=""
  if docker_running swg-panel; then   # master/panel stays → only the NODE's own data is in play (decide now)
    ask_yn "  Keep the node's interface configs (peers)? Leaves data/node-confs so a future install can re-onboard them." y KNODE
  else ask_full_data_fate; fi         # node is the last container → the whole data dir
  # capture the node's interface names FROM THE CONTAINER first — the ./data/node-confs bind mount can be empty,
  # and a host-networking node creates its wg/awg netdevs in the HOST namespace (they survive `docker rm`), so we
  # need the names to delete the leftover host interfaces below (else the next install hits "awg0 already exists").
  local _ifn _n _c
  _ifn="$(docker exec swg-node sh -c 'for d in /etc/amnezia/amneziawg /etc/wireguard; do ls "$d"/*.conf 2>/dev/null; done' 2>/dev/null | sed 's#.*/##; s#\.conf$##' | tr '\n' ' ')"
  [ -n "$_ifn" ] || _ifn="$(for _c in "$DOCKER_DIR/data/node-confs/"*.conf; do [ -f "$_c" ] && basename "$_c" .conf; done | tr '\n' ' ')"
  # Same debt the bare-metal node owes (see rm_node): an interface taken over from somebody else's container
  # left that container stopped with restart=no. Read the mirror off the bind-mounted state dir, and — for a
  # take-over that predates the mirror — the container's own config.json while it is still up to be asked.
  _acfg="$(mktemp 2>/dev/null || echo /tmp/swg-adopted.$$)"
  docker exec swg-node cat /etc/swg-agent/config.json >"$_acfg" 2>/dev/null || : >"$_acfg"
  capture_adopted "$_acfg" "$DOCKER_DIR/data/node/adopted-containers.json"
  rm -f "$_acfg"
  run sh -c 'docker rm -f swg-node >/dev/null 2>&1 || true'
  run sh -c 'ids=$(docker ps -aq --filter name=swg-turn- 2>/dev/null); [ -n "$ids" ] && docker rm -f $ids >/dev/null 2>&1 || true'   # this node's turn-proxy containers
  docker_node_goodbye                 # sign off AFTER the container is stopped — else its next 5s sync re-reports and clears the panel's "Uninstalled" tag (leaving it merely "offline")
  # delete the leftover HOST-namespace wg/awg netdevs the (host-networking) node created
  for _n in $_ifn; do [ -n "$_n" ] || continue
    command -v ip >/dev/null 2>&1 && ip link show "$_n" >/dev/null 2>&1 || continue
    awg-quick down "$_n" >/dev/null 2>&1 || wg-quick down "$_n" >/dev/null 2>&1 || true   # clean teardown if it can
    ip link delete dev "$_n" >/dev/null 2>&1 || true                                      # ALWAYS force-delete (down may exit 0 without removing it)
    info "  removed leftover host interface $(b "$_n")"; done
  if docker_running swg-panel; then
    [ "$KNODE" = yes ] && info "  Kept $DOCKER_DIR/data/node-confs (peers re-onboardable); panel data untouched." \
                       || { _rm_node_data; info "  Removed the node's interface configs; panel data untouched."; }
  else docker_cleanup_if_last; fi     # applies the data-dir decision captured above
  # Same deferred sweep the bare-metal rm_node arms. A docker node given host networking (or one that force-removed
  # an interface, so wg-quick PostDown never ran) leaves its iptables/nft/ipset objects in the HOST namespace, where
  # nothing else reclaims them; without this the docker path swept nothing at all.
  NEED_NETOBJ_SWEEP=true
  ok "swg-node container removed"; }
rm_docker_files(){ info "Removing the Docker deployment files ($DOCKER_DIR)"
  # This component can run without rm_docker_node ever firing, so it owes the same debt: a container we took
  # an interface over from is still stopped with restart=no. Capture before anything is torn down.
  capture_adopted /dev/null "$DOCKER_DIR/data/node/adopted-containers.json"
  # The dir-based component doesn't go through rm_docker_node/panel, so tear down ANY swg container here too
  # (incl. compose's "<id>_swg-node" recreate-backups, which is why the node sometimes isn't detected by name).
  ( cd "$DOCKER_DIR" 2>/dev/null && { docker compose down --remove-orphans >/dev/null 2>&1 || docker-compose down --remove-orphans >/dev/null 2>&1; } ) || true
  for _p in swg-node swg-panel swg-turn-; do docker ps -aq -f "name=$_p" 2>/dev/null | xargs -r docker rm -f >/dev/null 2>&1 || true; done
  docker_node_goodbye   # sign off AFTER the container is gone (no further sync clears the panel's "Uninstalled")
  ask_full_data_fate; apply_full_data_fate; rmrf /var/lib/swg-recovery; ok "Docker deployment files removed"; }

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
    if $DRYRUN; then echo "    [dry] down + disable ${tool}@$n + remove $n"
    else { command -v "$tool" >/dev/null 2>&1 && "$tool" down "$n"; ip link delete "$n"; } >/dev/null 2>&1 || true
      # DISABLE the unit instance, not just `down` it. Without this the enable symlink in
      # multi-user.target.wants survives the conf it points at, and once the wg/awg package is removed too
      # there is no unit file behind it either — systemd then reports `wg-quick@<n>.service not-found failed`
      # for ever and tries again on every boot. A full uninstall left 36 of these on a test box. swg-agent
      # already disables the instance on its own delete/stop paths; this is the same call, in the uninstaller.
      run systemctl disable "${tool}@$n" >/dev/null 2>&1 || true
      rm -f "$f"; fi
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
rm_netctl(){   # a leftover swg-netctl (e.g. after a docker convert) with no bare panel around to sweep it up
  info "Removing swg-netctl (leftover helper)"
  # BOTH families: the bare-metal swg-netctl.* and the docker helper swg-netctl-docker.*. The docker pair was
  # invisible to every uninstall — the detection globbed swg-netctl.* , which needs a literal dot and so never
  # matched swg-netctl-docker.service — leaving an ACTIVE .timer polling a queue for a panel that was gone.
  for _nc in swg-netctl.path swg-netctl.timer swg-netctl.service \
             swg-netctl-docker.path swg-netctl-docker.timer swg-netctl-docker.service; do
    [ -e "$SD/$_nc" ] && run systemctl disable --now "$_nc" 2>/dev/null || true   # one at a time: a multi-unit disable aborts wholesale on the first missing unit
  done
  rmrf $SD/swg-netctl.service $SD/swg-netctl.path $SD/swg-netctl.timer \
       $SD/swg-netctl-docker.service $SD/swg-netctl-docker.path $SD/swg-netctl-docker.timer /usr/local/bin/swg-netctl
  run systemctl daemon-reload; ok "swg-netctl removed"
}
# Host-side remnants of a DOCKER or converted install that no container remover owns: swg-sub's own tls dir and its
# systemd drop-in (written by the bare-metal install, survived the convert), and the node sysctl drop-in. Removing
# these also arms the datapath sweep — this is the "re-run this uninstaller" the sweep message promises.
rm_leftovers(){
  info "Removing leftover swg files (docker/converted install)"
  for _u in swg-sub.service; do [ -e "$SD/$_u" ] && run systemctl disable --now "$_u" 2>/dev/null || true; done
  rmrf /etc/swg-sub /opt/swg-sub "$SD/swg-sub.service" "$SD/swg-sub.service.d" /usr/local/bin/swg-sub
  run systemctl daemon-reload
  # Service identities the pre-convert BARE install created. rm_panel/rm_node own these, and neither runs on a
  # docker-only box, so they outlived the uninstall — leaving swgpanel + group swg on a box with no swg on it.
  # Safe here by construction: this component only exists when no panel/node install remains. Same -r split as
  # the owners use (swgpush/swgagent carry a home dir; swgpanel/swgsub do not).
  for _su in swgpanel swgsub; do id "$_su" >/dev/null 2>&1 && run userdel "$_su" 2>/dev/null || true; done
  for _su in swgpush swgagent; do id "$_su" >/dev/null 2>&1 && run userdel -r "$_su" 2>/dev/null || true; done
  REMOVED_LEFTOVERS=true      # lets the shared group cleanup at the end run for a docker/converted box too
  NEED_NETOBJ_SWEEP=true
  ok "leftover swg files removed"
}
_has_netctl(){ ls $SD/swg-netctl.* >/dev/null 2>&1 || ls $SD/swg-netctl-docker.* >/dev/null 2>&1; }
_has_leftovers(){ [ -d /etc/swg-sub ] || [ -d /opt/swg-sub ] || [ -e "$SD/swg-sub.service" ] || [ -d "$SD/swg-sub.service.d" ] \
  || id swgpanel >/dev/null 2>&1 || id swgsub >/dev/null 2>&1 || id swgpush >/dev/null 2>&1 || id swgagent >/dev/null 2>&1 \
  || getent group swg >/dev/null 2>&1; }

# Delete the node-owned egress rules tagged for ONE interface (nat/POSTROUTING SNAT + filter/FORWARD accept +
# mangle/FORWARD MSS), matching swg-noded's own tags. The trailing quote in --comment "tag" keeps swg-egress:wdtt1
# from matching swg-egress:wdtt11.
_rm_egress_rules(){ local ifn="$1" t c l
  command -v iptables >/dev/null 2>&1 || return 0
  for t in "nat POSTROUTING swg-egress:$ifn" "filter FORWARD swg-egress-acl:$ifn" "mangle FORWARD swg-egress-mss:$ifn"; do
    set -- $t
    while IFS= read -r l; do
      [ -n "$l" ] || continue
      run sh -c "iptables -t $1 $(printf '%s' "$l" | sed "s/^-A /-D /")"
    done <<EOS
$(iptables -t "$1" -S "$2" 2>/dev/null | grep -F -- "--comment \"$3\"")
EOS
  done; }

# Remove the node's DATAPATH objects — the filtering / routing / NAT state swg-noded creates at runtime and that
# nothing else cleans up (it lives in the kernel, not on disk, so removing files leaves it behind). Every match is
# by an swg-OWNED name so a co-resident firewall/VPN is never touched:
#   • iptables rules whose --comment starts with "swg-"  (nat/filter/mangle: egress, fwd, inet, catk tags)
#   • the "swg_smart" nftables table (smart-routing / blocking)
#   • "swgk_*" ipsets (Kernel-SNI categories)
#   • policy-routing rules + tables in swg's OWN band 7000-7099 (SWG_RT_BASE..SWG_RT_MAX; priority == table id)
#   • the forwarding sysctl drop-in the installer wrote
rm_node_netobjects(){
  info "Removing swg datapath objects (iptables/nft/ipset/policy-routing tagged swg-*)"
  local t chain l n
  if command -v iptables >/dev/null 2>&1; then
    for t in nat filter mangle; do
      for chain in $(iptables -t "$t" -S 2>/dev/null | sed -n 's/^-N \([A-Za-z0-9_-]*\).*/\1/p'; echo PREROUTING INPUT FORWARD OUTPUT POSTROUTING); do
        iptables -t "$t" -S "$chain" 2>/dev/null | grep -F -- '--comment "swg-' | while IFS= read -r l; do
          [ -n "$l" ] && run sh -c "iptables -t $t $(printf '%s' "$l" | sed 's/^-A /-D /')"
        done
      done
    done
  fi
    # The loop above only deletes rules that CARRY a swg- comment. Our own chains (SWG_INET, SWGK, SWG_CATK) and
    # the jumps INTO them have no comment, so they survived every uninstall — leaving an empty SWG_INET plus a live
    # "-A FORWARD -j SWG_INET" behind. Drop the jumps first (iptables refuses to delete a referenced chain), then
    # flush + delete the chains. Matched on our SWG prefix, so nothing else is touched.
    if command -v iptables >/dev/null 2>&1; then
      for t in nat filter mangle; do
        for chain in $(iptables -t "$t" -S 2>/dev/null | sed -n 's/^-N \(SWG[A-Za-z0-9_]*\).*/\1/p'); do
          iptables -t "$t" -S 2>/dev/null | grep -E -- "-j ${chain}$" | while IFS= read -r l; do
            [ -n "$l" ] && run sh -c "iptables -t $t $(printf '%s' "$l" | sed 's/^-A /-D /')"
          done
          run sh -c "iptables -t $t -F $chain"; run sh -c "iptables -t $t -X $chain"
        done
      done
    fi
    # nft: swg_smart is not the only table we create (swg_turn is the other) — sweep every swg* table we own.
    if command -v nft >/dev/null 2>&1; then
      nft list tables 2>/dev/null | sed -n 's/^table \([a-z0-9]*\) \(swg[A-Za-z0-9_]*\).*/\1 \2/p' | while read -r fam tbl; do
        [ -n "$tbl" ] && run nft delete table "$fam" "$tbl"
      done
    fi
    # ipsets: swgk_* are the kernel-SNI sets, but swgp_src (turn client-IP capture) is ours too.
    if command -v ipset >/dev/null 2>&1; then
      for n in $(ipset list -name 2>/dev/null | grep '^swg'); do run ipset destroy "$n"; done
    fi
  if command -v ip >/dev/null 2>&1; then
    for n in $(ip rule show 2>/dev/null | sed -n 's/^\([0-9]\+\):.*/\1/p' | awk '$1>=7000 && $1<=7099'); do
      run ip rule del pref "$n"; run ip route flush table "$n"
    done
  fi
  # Orphaned wg-quick PostUp rules for a node<->node MESH link (swg-agent writes the FORWARD accept pair; `swg_` is
  # noded's reserved mesh link-name prefix). They carry no swg- comment and sit in no SWG* chain, so neither loop
  # above sees them, and PostDown never runs when the container/interface is force-removed. Only ever deleted when
  # the named link is GONE — a rule for a link that still exists belongs to something the operator kept.
  if command -v iptables >/dev/null 2>&1; then
    for n in $(iptables -S 2>/dev/null | grep -oE '[-]{1,2}[io] swg_[A-Za-z0-9_]+' | awk '{print $2}' | sort -u); do
      ip link show "$n" >/dev/null 2>&1 && continue          # link still up → not an orphan, leave it alone
      iptables -S 2>/dev/null | grep -E -- "-[io] ${n}( |$)" | while IFS= read -r l; do
        [ -n "$l" ] && run sh -c "iptables $(printf '%s' "$l" | sed 's/^-A /-D /')"
      done
    done
  fi
  # 99-swg-forward.conf is the BARE installer's name; install-docker.sh writes 99-swg-node.conf instead, so the
  # docker drop-in was never removed. Both are ours and both are unconditionally rewritten by a re-install.
  rmrf /etc/sysctl.d/99-swg-forward.conf /etc/sysctl.d/99-swg-node.conf
  ok "swg datapath objects removed"
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

# A WDTT server owns BOTH its service and its userspace interface (it brings the tunnel up itself), so removing one
# is the turn-proxy flow plus an `ip link delete`. Its config-dir holds the SERVER IDENTITY (wg-keys.dat) and the
# password store: deleting those can never be undone and no client on this instance could ever connect again — so
# that part is a separate question, default NO, mirroring how the panel keeps its roster for a re-install.
# (ask_yn returns immediately once the var is set, so the question is asked ONCE however many instances there are.)
rm_wdtt(){ local unit="$1" name iface fork
  name="$(basename "$unit" .service)"; iface="${name#swg-wdtt-}"
  fork="$(sed -n 's/^Description=swg-wdtt (\([^)]*\)).*/\1/p' "$unit" 2>/dev/null | head -1)"; fork="${fork%%/*}"
  info "Removing WDTT server ($iface${fork:+ · $fork})"
  [ -e "$unit" ] && run systemctl disable --now "$name"
  rmrf "$unit"; run systemctl daemon-reload
  command -v ip >/dev/null 2>&1 && run ip link delete dev "$iface" 2>/dev/null || true   # its userspace tunnel outlives the process
  rmrf "/var/run/wireguard/$iface.sock"   # the wireguard-go UAPI socket outlives it too — and a stale one makes the node report a PHANTOM adoption candidate
  # The node owns this instance's egress rules (WDTT runs with -no-nat). Nothing else removes them, so they'd
  # linger after an uninstall and a LATER install could reuse the iface name with a different subnet — leaving a
  # MASQUERADE for the old one and clients with no internet. Delete by our own comment tag only.
  _rm_egress_rules "$iface"
  # ask_yn returns immediately once its variable is set, so a single answer used to apply to EVERY instance —
  # while the prompt named one specific path. This is the one irrecoverable action in the script, so ask per
  # instance (a name-scoped variable), and let an unattended run still answer once via WDTT_DATA_DEL.
  local _delvar="WDTT_DATA_DEL_${iface//[^A-Za-z0-9_]/_}"
  [ -n "${WDTT_DATA_DEL:-}" ] && printf -v "$_delvar" '%s' "$WDTT_DATA_DEL"
  ask_yn "  Delete this WDTT interface identity + passwords ($WDTT_DIR/$iface)? Clients on it could never be restored." n "$_delvar"
  if [ "${!_delvar}" = yes ]; then
    rmrf "$WDTT_DIR/$iface"
  else
    ok "Kept $WDTT_DIR/$iface (server identity + passwords) for a future re-install"
  fi
  ls $SD/swg-wdtt-*.service >/dev/null 2>&1 || {          # last one out: shared per-fork binaries + the panel-facing record
    rmrf "$WDTT_DIR/.bin" /etc/swg-agent/wdtt.json
    [ "${WDTT_DATA_DEL:-}" = yes ] && rmrf "$WDTT_DIR"   # :- — the per-instance answers live in WDTT_DATA_DEL_<iface>; this global is only ever set by an unattended run, so under `set -u` an interactive uninstall died right here
  }
  ok "WDTT server ($iface) removed"
}

# csqtt: the same shape as rm_wdtt, with one difference that changes what the irrecoverable question means. csqtt has
# NO server keypair — a password IS the credential — so its config-dir holds the password STORE and nothing else can
# stand in for it: delete it and every client on this instance is locked out with no way back, exactly as if a WDTT
# identity had been destroyed. Same per-instance question, same default NO.
rm_csqtt(){ local unit="$1" name iface
  name="$(basename "$unit" .service)"; iface="${name#swg-csqtt-}"
  info "Removing csqtt server ($iface)"
  [ -e "$unit" ] && run systemctl disable --now "$name"
  rmrf "$unit"; run systemctl daemon-reload
  command -v ip >/dev/null 2>&1 && run ip link delete dev "$iface" 2>/dev/null || true   # its raw TUN outlives the process
  # The node owns this instance's egress rules (csqtt runs with --no-nat), same as WDTT — remove by our comment tag.
  _rm_egress_rules "$iface"
  local _delvar="CSQTT_DATA_DEL_${iface//[^A-Za-z0-9_]/_}"
  [ -n "${CSQTT_DATA_DEL:-}" ] && printf -v "$_delvar" '%s' "$CSQTT_DATA_DEL"
  ask_yn "  Delete this csqtt server's password store ($CSQTT_DIR/$iface)? Clients on it could never be restored." n "$_delvar"
  if [ "${!_delvar}" = yes ]; then
    rmrf "$CSQTT_DIR/$iface"
  else
    ok "Kept $CSQTT_DIR/$iface (password store) for a future re-install"
  fi
  ls $SD/swg-csqtt-*.service >/dev/null 2>&1 || {          # last one out: shared binary + the panel-facing record
    rmrf "$CSQTT_DIR/.bin" /etc/swg-agent/csqtt.json
    [ "${CSQTT_DATA_DEL:-}" = yes ] && rmrf "$CSQTT_DIR"
  }
  ok "csqtt server ($iface) removed"
}

# ───────────────────────── detect installed components ─────────────────────────
declare -a CLABEL=() CDETAIL=() CFN=() CARG=() CHINT=() CVERB=() CPROMPT=()   # init empty (not just `declare -a`) — bash 5.2 + set -u treats a never-assigned array as unbound for ${#arr[@]}
# ── richer component details: interface names+ports, node endpoints, turn-proxy ports ──
iface_list(){  # <dir> -> "awg0:51820, awg505:51234" (interface name + ListenPort from each .conf)
  local dir="$1" out="" f n p
  for f in "$dir"/*.conf; do [ -f "$f" ] || continue
    n="$(basename "$f" .conf)"
    case "$n" in "${SWG_SYS_PREFIX:-swg_}"*) continue;; esac   # don't list panel-managed mesh links
    p="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$f" 2>/dev/null | head -1)"
    out="${out:+$out, }${n}${p:+:$p}"
  done
  printf '%s' "${out:-$dir}"
}
bm_node_detail(){  # bare-metal node: endpoint + interfaces from config.json
  local cfg=/etc/swg-agent/config.json ep ifs
  if [ -f "$cfg" ] && command -v python3 >/dev/null 2>&1; then
    ep="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("endpoint_host",""))' "$cfg" 2>/dev/null)"
    ifs="$(python3 -c 'import json,sys;print(", ".join(k for k in (json.load(open(sys.argv[1])).get("interfaces") or {}) if not k.startswith("swg_")))' "$cfg" 2>/dev/null)"
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
  # Turn-proxies and WDTT servers, DOCKER form. Both are detected elsewhere by their host systemd units
  # (vk-turn-proxy-*.service / swg-wdtt-*.service), which a docker install simply does not have: turn-proxies
  # run as SIBLING CONTAINERS and WDTT as a supervised subprocess inside swg-node. They were therefore removed
  # with the node container while never appearing in the component list — the operator was never told a WDTT
  # server and its identity were about to go. They cannot be offered as separate components (nothing can keep
  # them once the node container is gone), so they are DISCLOSED here, on the node they belong to.
  local tn wl wn
  tn="$(docker ps -a --filter 'name=swg-turn-' --format '{{.Names}}' 2>/dev/null | sed 's/^swg-turn-//' | tr '\n' ',' | sed 's/,$//; s/,/, /g')"
  # uninstall.sh is standalone (it must run on a box where lib/ may be gone), so the record is parsed here rather
  # than via common.sh's wdtt_local. Heredoc body at column 0: indenting a python program is an IndentationError,
  # and 2>/dev/null would swallow it and silently report "no WDTT" on a box that has one.
  wl="$(python3 - "$DOCKER_DIR/data/node/wdtt.json" <<'PYWD' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    raise SystemExit
out = []
for i in (d.get("wdtt") or []):
    if isinstance(i, dict) and i.get("iface"):
        out.append("%s%s" % (i["iface"], ("/" + i["fork"]) if i.get("fork") else ""))
print(", ".join(out))
PYWD
)"
  wn="$(printf '%s' "$wl" | tr ',' '\n' | grep -c . 2>/dev/null)"
  # csqtt, same disclosure and for the same reason — a supervised subprocess inside swg-node, so no host unit names
  # it and it would leave with the container unannounced. Its record is a flat {iface: inst} map, not WDTT's list.
  local cl cn
  cl="$(python3 - "$DOCKER_DIR/data/node/csqtt.json" <<'PYCQ' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    raise SystemExit
if not isinstance(d, dict):
    raise SystemExit
out = []
for k, i in d.items():
    if isinstance(i, dict):
        n = len(i.get("passwords") or {})
        out.append("%s%s" % (k, (" (%d pw)" % n) if n else ""))
print(", ".join(out))
PYCQ
)"
  cn="$(printf '%s' "$cl" | tr ',' '\n' | grep -c . 2>/dev/null)"
  printf 'container swg-node%s%s%s%s%s%s' "${nm:+ · $nm}" "${ep:+ · endpoint $ep}" "${ifs:+ · ifaces: $ifs}" \
         "${tn:+ · turn-proxies: $tn}" "${wl:+ · WDTT ($wn): $wl}" "${cl:+ · csqtt ($cn): $cl}"
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
add(){ CLABEL+=("$1"); CDETAIL+=("$2"); CFN+=("$3"); CARG+=("${4:-}"); CHINT+=("${5:-}"); CVERB+=("${6:-Uninstall}"); CPROMPT+=("${7:-$1}"); }   # $6 = question verb (default Uninstall); $7 = shorter label for the question (defaults to the list label)
turn_listen(){ local lis con; IFS="$(printf '\t')" read -r lis con < <(turn_exec_env "$1"); printf '%s' "$lis"; }
# WDTT: params live in the instance's wdtt.env (the unit's ExecStart only references them), so read that.
wdtt_env(){ local iface="$1" k="$2"; sed -n "s/^$k=//p" "$WDTT_DIR/$iface/wdtt.env" 2>/dev/null | head -1; }
wdtt_listen(){ local n; n="$(basename "$1" .service)"; wdtt_env "${n#swg-wdtt-}" SWG_LISTEN; }
wdtt_detail(){  # <unit> -> "amurcanov · DTLS 1.2.3.4:56000 · wg :56001 · 10.66.66.1/24 · identity kept"
  local unit="$1" n iface fork lis wgp addr id
  n="$(basename "$unit" .service)"; iface="${n#swg-wdtt-}"
  fork="$(sed -n 's/^Description=swg-wdtt (\([^)]*\)).*/\1/p' "$unit" 2>/dev/null | head -1)"; fork="${fork%%/*}"
  lis="$(wdtt_env "$iface" SWG_LISTEN)"; wgp="$(wdtt_env "$iface" SWG_WGPORT)"; addr="$(wdtt_env "$iface" SWG_WGADDR)"
  [ -f "$WDTT_DIR/$iface/wg-keys.dat" ] && id="server identity on disk" || id="no identity file"
  printf '%s%s%s%s · %s' "${fork:-wdtt}" "${lis:+ · DTLS $lis}" "${wgp:+ · $iface:$wgp}" "${addr:+ · $addr}" "$id"
}
# csqtt: same idea, its own env file. There is no identity file to report — the store IS the identity, so say how
# many passwords would go with it, which is the number that decides the keep/delete answer.
csqtt_env(){ local iface="$1" k="$2"; sed -n "s/^$k=//p" "$CSQTT_DIR/$iface/csqtt.env" 2>/dev/null | head -1; }
csqtt_listen(){ local n; n="$(basename "$1" .service)"; csqtt_env "${n#swg-csqtt-}" SWG_LISTEN; }
csqtt_detail(){  # <unit> -> "csqtt · 1.2.3.4:56006 · 10.12.0.1/24 · 4 passwords on disk"
  local unit="$1" n iface lis addr pw
  n="$(basename "$unit" .service)"; iface="${n#swg-csqtt-}"
  lis="$(csqtt_env "$iface" SWG_LISTEN)"; addr="$(csqtt_env "$iface" SWG_TUNADDR)"
  pw="$(python3 -c 'import json,sys
try: print(len(json.load(open(sys.argv[1])).get("passwords") or {}))
except Exception: print("")' "$CSQTT_DIR/$iface/passwords.json" 2>/dev/null)"
  if [ -n "$pw" ]; then pw="$pw password(s) on disk"; else pw="no password store"; fi
  printf 'csqtt%s%s · %s' "${lis:+ · $lis}" "${addr:+ · $addr}" "$pw"
}

[ -d /opt/swg-panel ] || [ -f $SD/swg-panel-server.service ] && \
  add "Bare-metal swg-panel" "control panel (/opt/swg-panel)" rm_panel
[ -d /opt/swg-noded ] || [ -d /opt/swg-agent ] || [ -f $SD/swg-noded.service ] && \
  add "Bare-metal node (swg-node)" "$(bm_node_detail)" rm_node
# swg-netctl units lingering WITHOUT a bare panel (rm_panel would otherwise sweep them) → offer on their own
{ [ ! -d /opt/swg-panel ] && [ ! -f $SD/swg-panel-server.service ]; } && _has_netctl && \
  add "swg-netctl (leftover helper)" "privileged network/TLS helper units" rm_netctl
# (the "Leftover swg files" component is added AFTER the docker detection below — it must know whether a docker
#  install is present, since the identities it removes own that install's data-dir files.)

# Docker: the panel and node are separate containers — offer each independently. If the
# deployment dir exists but neither container does, offer a files-only cleanup.
DPANEL=false; DNODE=false
if command -v docker >/dev/null 2>&1; then
  docker_running swg-panel && DPANEL=true
  docker_running swg-node  && DNODE=true
fi
$DPANEL && add "Docker panel (swg-panel)" "container swg-panel" rm_docker_panel
$DNODE  && add "Docker node (swg-node)"   "$(docker_node_detail)"   rm_docker_node

# swg-sub's dirs/units and the bare-metal service identities are removed by rm_panel/rm_node, which a docker-only
# or post-convert box never runs — so they outlived every uninstall on exactly the boxes that have them. Offered
# only when NO swg install of any kind is left: `swgpanel` owns the docker data-dir files, so removing it while a
# docker install is live (or being kept) would orphan their ownership.
if ! $DPANEL && ! $DNODE && [ ! -d "$DOCKER_DIR" ] \
   && [ ! -d /opt/swg-panel ] && [ ! -f $SD/swg-panel-server.service ] \
   && [ ! -d /opt/swg-noded ] && [ ! -f $SD/swg-noded.service ] && _has_leftovers; then
  add "Leftover swg files" "swg-sub dirs/units + service identities from a docker or converted install" rm_leftovers
fi
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
# The host WG/AWG PACKAGES are swg's to purge only when a BARE-METAL swg node installed them. A docker node runs
# its datapath in-container (userspace amneziawg-go), so on a docker-only box these host packages belong to
# something else (e.g. wg-easy, or another VPN) — purging them would break it. Peers (interface .conf files) are
# still offered separately since those files ARE swg's own.
_bare_swg=false; { [ -d /opt/swg-noded ] || [ -d /opt/swg-agent ] || [ -f "$SD/swg-noded.service" ] || [ -d /opt/swg-panel ] || [ -f "$SD/swg-panel-server.service" ]; } && _bare_swg=true
awg_ifaces && { _d="$(iface_list /etc/amnezia/amneziawg)"; add "AmneziaWG interfaces" "$_d" rm_awg_peers "" "$_d" Remove; }
awg_pkg    && $_bare_swg && add "AmneziaWG package (kernel module + tools)" "amneziawg · amneziawg-tools · amneziawg-dkms" rm_awg_pkg
wg_ifaces  && { _d="$(iface_list /etc/wireguard)";        add "WireGuard interfaces" "$_d" rm_wg_peers "" "$_d" Remove; }
wg_pkg     && $_bare_swg && add "WireGuard package (kernel module + tools)" "wireguard · wireguard-tools" rm_wg_pkg
true   # don't let the last &&-test leave a non-zero status

for unit in $(ls $SD/vk-turn-proxy-*.service 2>/dev/null || true); do
  add "Turn-proxy (service) $(basename "$unit" .service)" "$(turn_detail "$unit")" rm_turn "$unit" "$(turn_listen "$unit")" "" "Turn-proxy $(basename "$unit" .service)"   # type + green service name, then listen → connect (iface)
done
for unit in $(ls $SD/swg-wdtt-*.service 2>/dev/null || true); do   # WDTT servers — listed per instance, like turn-proxies
  add "WDTT (service + interface) $(basename "$unit" .service)" "$(wdtt_detail "$unit")" rm_wdtt "$unit" "$(wdtt_listen "$unit")" "" "WDTT-proxy $(basename "$unit" .service)"
done
for unit in $(ls $SD/swg-csqtt-*.service 2>/dev/null || true); do   # csqtt servers — same, one entry per instance
  add "csqtt (service + interface) $(basename "$unit" .service)" "$(csqtt_detail "$unit")" rm_csqtt "$unit" "$(csqtt_listen "$unit")" "" "csqtt server $(basename "$unit" .service)"
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
  if ask_comp "${CPROMPT[$i]}" "${CHINT[$i]}" "${CVERB[$i]}"; then "${CFN[$i]}" "${CARG[$i]}"; DID_REMOVE+=("${CLABEL[$i]}")
  else info "Kept ${CLABEL[$i]}."; DID_KEEP+=("${CLABEL[$i]}"); fi
  echo
done

# Datapath sweep, LAST — after every keep/remove decision. rm_node_netobjects deletes swg-tagged iptables rules,
# the swg_smart nft table, swgk_* ipsets and our ip rules/tables; those are the datapath of the very interfaces,
# turn-proxies and WDTT servers the operator may have chosen to KEEP, so it cannot run before they are asked.
# Anything kept has already had its own rules removed by its own remover (rm_wdtt → _rm_egress_rules).
if [ "${NEED_NETOBJ_SWEEP:-false}" = true ]; then
  if [ "${#DID_KEEP[@]}" -gt 0 ]; then
    # The sweep is all-or-nothing by tag — it cannot tell a kept interface's swg-egress rule from a removed one's.
    # Keeping something means keeping it WORKING, so leave the objects: stale rules on a box that still runs our
    # datapath are harmless, whereas deleting a kept WDTT server's SNAT silently kills internet for its clients.
    info "Some components were kept — leaving the routing/filter objects in place so they keep working."
    info "  To clear them later, once nothing swg-related remains: re-run this uninstaller."
  else
    rm_node_netobjects
  fi
fi

# Containers we TOOK an interface over from (see rm_node). Their server was somebody else's before it was ours,
# and the take-over stopped it with restart=no on the promise that we would serve it instead. That promise ends
# here, so put them back the way we found them — after the interfaces above are gone, so the port they bind is
# free. Default YES: leaving a box with neither our interface nor their container is the one outcome nobody wants.
if [ -n "${ADOPTED_CTRS:-}" ] && command -v docker >/dev/null 2>&1; then
  _nc="$(printf '%s\n' "$ADOPTED_CTRS" | grep -c .)"
  info "$_nc container(s) had an interface taken over by this node — still stopped, as the take-over left them."
  ask_yn "  Start them again? Without this the box is left with no server at all — ours removed, theirs off." y RESTORE_CTRS
  if [ "${RESTORE_CTRS:-}" = yes ]; then
    printf '%s\n' "$ADOPTED_CTRS" | while IFS= read -r _c; do [ -n "$_c" ] || continue
      docker inspect "$_c" >/dev/null 2>&1 || { info "  $(b "$_c") is gone — nothing to restore"; continue; }
      run sh -c "docker update --restart=always '$_c' >/dev/null 2>&1 || true"
      if $DRYRUN; then echo "    [dry] docker start $_c"; continue; fi
      if docker start "$_c" >/dev/null 2>&1; then ok "restarted $(b "$_c") — its own server is serving again"
      else warn "  could not start $(b "$_c") — start it by hand: docker start $_c"; fi
    done
  else info "  Left stopped — start one by hand with: docker start <name>"; fi
fi

# Recovery archives from earlier converts/uninstalls (.converted-* / .uninstalled-*). They are OURS, but they are
# deliberately-kept state — a node token plus interface private keys — and the installer offers them as a recovery
# list, so they are never deleted without being asked. Default NO; a preset ARCHIVES_DEL=y covers unattended wipes.
_archives(){ ls -d /opt/swg-panel*.converted-* /opt/swg-panel*.uninstalled-* /etc/swg-panel*.converted-* \
                   /etc/swg-panel*.uninstalled-* /var/lib/swg-panel*.converted-* /var/lib/swg-panel*.uninstalled-* 2>/dev/null; }
if [ -n "$(_archives)" ]; then
  _na="$(_archives | wc -l)"
  info "$_na recovery archive(s) from earlier converts/uninstalls remain (node token + interface keys)."
  ask_yn "  Delete them too? A future install can no longer offer them for recovery." n ARCHIVES_DEL
  if [ "${ARCHIVES_DEL:-}" = yes ]; then _archives | while IFS= read -r _a; do [ -n "$_a" ] && rmrf "$_a"; done
    ok "removed $_na recovery archive(s)"
  else info "  Kept — delete by hand once you no longer need them."; fi
fi

# group cleanup (shared by panel + agent) — only if we removed a bare-metal piece, or swept the bare-metal
# identities off a docker/converted box (where REMOVED_PANEL/REMOVED_NODE are never set but the group is ours).
if { $REMOVED_PANEL || $REMOVED_NODE || [ "${REMOVED_LEFTOVERS:-false}" = true ]; } && getent group swg >/dev/null 2>&1; then
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
echo     # one blank line after the summary block (consistency)
