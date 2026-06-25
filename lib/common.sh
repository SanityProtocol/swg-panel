# swg-panel — shared installer helpers (sourced by install-host/node/docker.sh + convert.sh).
# Pure, stateless helpers that were byte-identical across the installers. Functions that depend on
# per-script state (port_free, v_host/v_port, have) are CALLED here but defined by the sourcing script,
# so behaviour is unchanged. Keep only provably-identical helpers here; don't add drifted ones.
#
# NB: this file is sourced, not executed — no shebang, no `set`, no side effects at load time.

# pretty protocol name for interface listings: awg → AmneziaWG, wg → Wireguard (anything else passes through)
proto_label(){ case "$1" in wg) printf 'Wireguard';; awg) printf 'AmneziaWG';; *) printf '%s' "$1";; esac; }

# node summary footer: "reconfigure in the panel, or directly on the server", with the method's real paths +
# commands. <baremetal|docker> [docker_install_dir]. b()/COMPOSE come from the sourcing script (installers/convert).
node_reconfig_block(){
  local method="$1" dir="${2:-/opt/swg-panel-docker}" prof="${3:-node}" C="${COMPOSE:-docker compose}"
  echo "  Interfaces and turn-proxies can be re-configured in the web panel, or directly on the server:"; echo
  if [ "$method" = docker ]; then
    printf '    %-13s %s\n' "Interfaces"   "$(b "ls $dir/data/node-confs/*.conf")"
    printf '    %-13s %s\n' "Turn-proxies" "$(b 'docker ps --filter name=swg-turn')"
    echo
    printf '    %-13s %s\n' "Directory"    "$(b "cd $dir")"
    printf '    %-13s %s\n' "Restart"      "$(b "cd $dir && $C restart swg-node")"
    printf '    %-13s %s\n' "Logs"         "$(b "cd $dir && $C logs -f swg-node")"
    printf '    %-13s %s\n' "Config"       "$(b "nano $dir/.env") (after edit run $(b "$C --profile $prof up -d"))"
  else
    printf '    %-13s %s\n' "AmneziaWG"    "$(b 'ls /etc/amnezia/amneziawg/*.conf')"
    printf '    %-13s %s\n' "WireGuard"    "$(b 'ls /etc/wireguard/*.conf')"
    printf '    %-13s %s\n' "Turn-proxies" "$(b 'ls /etc/systemd/system/vk-turn-proxy*.service')"
    echo
    printf '    %-13s %s\n' "SWG Agent"    "$(b 'nano /etc/swg-agent/config.json')"
    printf '    %-13s %s\n' "Restart"      "$(b 'systemctl restart swg-noded')"
    printf '    %-13s %s\n' "Logs"         "$(b 'journalctl -u swg-noded -f')"
  fi
}

# ── validators ──
v_iface(){   case "$1" in ""|*[!a-zA-Z0-9_-]*) return 1;; esac; [ "${#1}" -le 15 ]; }
v_subnet(){  have python3 || return 0; python3 -c "import ipaddress,sys;ipaddress.ip_network(sys.argv[1],strict=False)" "$1" >/dev/null 2>&1; }
v_hostport(){ case "$1" in *:*) v_host "${1%%:*}" && v_port "${1##*:}";; *) return 1;; esac; }

# ── ports ──
next_free_port(){ local p="${1:-51820}"; while [ "$p" -le 65535 ] && ! port_free "$p"; do p=$((p+1)); done; echo "$p"; }

# The name the PANEL currently has for the local node, matched by verifying the node's token against each
# nodes.json token_hash (same pbkdf2 the panel uses). Prints the name (empty if not found). Lets a re-install
# default to the UI-renamed name instead of the hostname.
#   panel_node_name_tok <nodes.json> <raw-token>        (docker: NODE_TOKEN from .env)
#   panel_node_name     <nodes.json> <agent-config.json> (bare-metal: token read from the agent config)
panel_node_name_tok(){ [ -f "$1" ] && [ -n "${2:-}" ] || return 0
  python3 - "$1" "$2" <<'PY' 2>/dev/null || true
import json,sys,hashlib,base64
try: nodes=json.load(open(sys.argv[1]))
except Exception: sys.exit(0)
tb=sys.argv[2].encode()
for _id,n in (nodes.items() if isinstance(nodes,dict) else []):
    h=n.get("token_hash") or ""
    try:
        _algo,it,salt,want=h.split("$")
        got=base64.b64encode(hashlib.pbkdf2_hmac("sha256",tb,base64.b64decode(salt),int(it))).decode()
    except Exception: continue
    if got==want: print(n.get("name") or ""); break
PY
}
panel_node_name(){ [ -f "$2" ] || return 0
  local _t; _t="$(python3 -c 'import json,sys;print((json.load(open(sys.argv[1])).get("panel") or {}).get("token") or "")' "$2" 2>/dev/null || true)"
  panel_node_name_tok "$1" "$_t"; }

# ── lifecycle status signalling (re-install / convert / update / uninstall) ──────────────────────────────
# A script calls `lc_init <op> <emit_fn>` right after step 1, where:
#   op ∈ reinstall | convert-bare | convert-docker | update | uninstall
#   emit_fn ∈ lc_emit_post (node/docker/convert → panel) | lc_emit_file (host → host_proc)
# lc_init signals the in-progress state, captures output for the failed-state log tail, and installs traps so
# the EXIT decides the terminal: Ctrl-C/SIGTERM → "<op> aborted"; any non-zero exit → "<op> failed" + log
# tail; clean exit → the success state (uninstall has none — the goodbye removes the node). Backends read the
# conventional vars the caller sets first: LC_URL/LC_TOKEN/LC_VERIFY (post) or LC_FILE (host_proc path).
LC_OP=""; LC_EMIT=""; LC_LOG=""; LC_ABORT=""; LC_HANDOFF=""; LC_DONE=""; LC_SUCCESS=""
_lc_inprogress(){ case "$1" in reinstall) echo reinstalling;; convert-bare) echo converting-bare;; convert-docker) echo converting-docker;; update) echo updating;; uninstall) echo uninstalling;; esac; }
_lc_success(){    case "$1" in reinstall) echo reinstalled;; convert-bare) echo converted-bare;; convert-docker) echo converted-docker;; update) echo updated;; uninstall) echo "";; esac; }
_lc_prefix(){     case "$1" in convert-*) echo convert;; *) echo "$1";; esac; }   # aborted/failed are op-generic
lc_emit(){ [ -n "${LC_EMIT:-}" ] && [ -n "${1:-}" ] && "$LC_EMIT" "$1" "${2:-}" || true; }
lc_handoff(){ LC_HANDOFF=1; }                                  # another script now owns the terminal (convert→installer)
lc_emit_post(){ [ -n "${LC_URL:-}" ] && [ -n "${LC_TOKEN:-}" ] || return 0
  local ins=""; [ "${LC_VERIFY:-no}" = yes ] || ins="-k"; local data=""
  if [ -n "${2:-}" ]; then data="$(python3 -c 'import json,sys;print(json.dumps({"state":sys.argv[1],"err":sys.argv[2]}))' "$1" "$2" 2>/dev/null)"; fi
  [ -n "$data" ] || data="{\"state\":\"$1\"}"
  curl -fsS $ins --max-time 8 -X POST -H "Authorization: Bearer $LC_TOKEN" -H "Content-Type: application/json" \
    --data "$data" "${LC_URL%/}/api/node/proc-status" >/dev/null 2>&1 || true; }
lc_emit_file(){ local f="${LC_FILE:-}"; [ -n "$f" ] || return 0; mkdir -p "$(dirname "$f")" 2>/dev/null || true
  if [ -n "${2:-}" ]; then printf '%s\n%s\n' "$1" "$2" > "$f" 2>/dev/null || true
  else printf '%s' "$1" > "$f" 2>/dev/null || true; fi; }
_lc_exit(){ local rc=$?                                        # MUST preserve rc (EXIT trap's last cmd = exit code)
  [ -n "$LC_DONE" ] && return $rc; LC_DONE=1
  # detach from the tee (restore real stdout/err, close the pipe) and WAIT for it to flush, so the log tail
  # we read below is complete (tee block-buffers — without this the failed-state err would be empty).
  if [ -n "${LC_OUT:-}" ]; then exec 1>&${LC_OUT} 2>&${LC_OUT}; { exec {LC_TEEFD}>&-; } 2>/dev/null
    [ -n "${LC_TEE:-}" ] && wait "$LC_TEE" 2>/dev/null || true; fi
  if   [ -n "$LC_HANDOFF" ]; then :
  elif [ -n "$LC_ABORT" ];   then lc_emit "$(_lc_prefix "$LC_OP")-aborted"
  elif [ "$rc" -ne 0 ];      then lc_emit "$(_lc_prefix "$LC_OP")-failed" "$(tail -n 20 "$LC_LOG" 2>/dev/null)"
  else local s; s="${LC_SUCCESS:-$(_lc_success "$LC_OP")}"; [ -n "$s" ] && lc_emit "$s"; fi   # LC_SUCCESS lets a script override (e.g. "reinstalled-updated")
  return $rc; }
lc_init(){ LC_OP="$1"; LC_EMIT="$2"; LC_ABORT=""; LC_HANDOFF=""; LC_DONE=""; LC_SUCCESS=""
  LC_LOG="$(mktemp 2>/dev/null || echo "/tmp/swg-lc.$$")"; : > "$LC_LOG" 2>/dev/null || true
  # mirror output to the log AND the terminal; remember the tee pid so _lc_exit can flush it. Prompts read
  # /dev/tty, so interactivity is unaffected. If the fd plumbing isn't supported, fall back to no capture.
  if exec {LC_OUT}>&1 && exec {LC_TEEFD}> >(tee -a "$LC_LOG" >&${LC_OUT}) 2>/dev/null; then
    LC_TEE=$!; exec 1>&${LC_TEEFD} 2>&${LC_TEEFD}
  else LC_OUT=""; fi
  trap 'LC_ABORT=1; exit 130' INT TERM HUP                     # user abort → flag + exit → EXIT trap emits "aborted"
  trap '_lc_exit' EXIT
  lc_emit "$(_lc_inprogress "$LC_OP")"; }                      # step 1 done → signal in-progress now

# Run "$@" with stdout+stderr on the CONTROLLING TERMINAL (/dev/tty) so `docker compose` renders its live
# progress BAR. lc_init's capture pipe — and any `| tee` / `exec bash` chain that leaves fd 1 a non-tty —
# makes compose fall back to plain line-by-line text; /dev/tty is the real terminal regardless of fd 1.
# Falls back to the inherited fds when there's no tty (headless/cron). Returns the wrapped command's status.
on_tty(){ if { true >/dev/tty; } 2>/dev/null; then "$@" >/dev/tty 2>/dev/tty; else "$@"; fi; }

# ── convert switch helpers: tear the OLD method down ONLY at the final switch (after the new one is fully
#    staged), so the node stays up the whole time. Generic (scan disk) → no per-name args needed. ───────────
# lc_teardown_baremetal [migrated-turn-svcs…] — stop+remove a bare-metal node: daemon, every wg/awg iface,
# files, and ONLY the host turn-proxies passed in (the ones being recreated on docker; ones the operator chose
# to keep stay running). Generic for the wg/awg side (scan disk) → no per-iface args needed.
lc_teardown_baremetal(){
  systemctl disable --now swg-noded 2>/dev/null || true
  local f n s
  for f in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf; do [ -f "$f" ] || continue; n="$(basename "$f" .conf)"
    awg-quick down "$n" 2>/dev/null || wg-quick down "$n" 2>/dev/null || true
    systemctl disable "awg-quick@$n" 2>/dev/null || true; systemctl disable "wg-quick@$n" 2>/dev/null || true
    rm -f "$f"; done
  for s in "$@"; do [ -n "$s" ] || continue; systemctl disable --now "$s" 2>/dev/null || true; rm -f "/etc/systemd/system/$s.service"; done   # migrated host turn-proxies only
  rm -f /etc/systemd/system/swg-noded.service; systemctl daemon-reload 2>/dev/null || true
  rm -rf /opt/swg-noded /opt/swg-agent /etc/swg-agent /var/lib/swg-noded /etc/sudoers.d/swg-agent; }
lc_teardown_docker(){   # stop+remove the docker datapath (container + stack), freeing wg ports + host netdevs
  local d="${1:-/opt/swg-panel-docker}"
  command -v docker >/dev/null 2>&1 || return 0
  docker rm -f swg-node >/dev/null 2>&1 || true
  for _c in $(docker ps -aq --filter name=swg-turn- 2>/dev/null || true); do docker rm -f "$_c" >/dev/null 2>&1 || true; done   # turn-proxy containers hold the listen ports the migrated bare units need
  if ! docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-panel; then   # node-only → take the stack down
    [ -f "$d/docker-compose.yml" ] && ( cd "$d" && { docker compose down >/dev/null 2>&1 || docker-compose down >/dev/null 2>&1 || true; } )
  fi
  return 0; }   # always succeed — a missing compose file (node-only box) must not return non-zero mid-switch and trip set -e

# lc_clear_convert_leftover <baremetal|docker> [docker_dir] — on a plain (re-)install/update of one method,
# delete the inert copy an ABORTED conversion to the OTHER method left behind (no prompt — just an old copy).
# Guards keep it safe: a docker leftover is removed only when NO swg-node/swg-panel container exists; a
# bare-metal leftover only the /etc confs that MATCH this docker node's confs and only when no swg-noded is
# installed — never a live install or an unrelated WireGuard config. Needs the caller's info() for messaging.
lc_clear_convert_leftover(){
  local method="$1" dd="${2:-/opt/swg-panel-docker}" c n d cleared=
  if [ "$method" = baremetal ] && [ -d "$dd" ] && command -v docker >/dev/null 2>&1 \
       && ! docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qxE 'swg-(node|panel)'; then
    info "removing a stale docker leftover at $dd — no container present (likely a cancelled bare→docker convert); your live install is untouched"
    rm -rf "$dd" 2>/dev/null || true
  elif [ "$method" = docker ] && [ -d "$dd/data/node-confs" ] && command -v systemctl >/dev/null 2>&1 \
       && ! systemctl list-unit-files swg-noded.service >/dev/null 2>&1; then
    for c in "$dd/data/node-confs/"*.conf; do [ -f "$c" ] || continue; n="$(basename "$c" .conf)"
      for d in "/etc/amnezia/amneziawg/$n.conf" "/etc/wireguard/$n.conf"; do [ -f "$d" ] && { rm -f "$d"; cleared=1; }; done
    done
    [ -n "$cleared" ] && info "removed stale bare-metal conf leftovers — no swg-noded service present (likely a cancelled docker→bare convert); your live install is untouched"
  fi
  return 0; }   # always succeed — best-effort cleanup; "nothing to clear" must not return non-zero and trip set -e in callers

# ── turn-proxy: the 6 forks + their owner/repo, and the binary download (GitHub direct, then opt-in mirrors) ──
turn_repo_owner(){ case "$1" in
  WINGS-N) echo "WINGS-N/vk-turn-proxy";; samosvalishe) echo "samosvalishe/vk-turn-proxy";;
  kiper292) echo "kiper292/vk-turn-proxy";; anton48) echo "anton48/vk-turn-proxy";;
  Moroka8) echo "Moroka8/vk-turn-proxy";;
  cacggghp) echo "cacggghp/vk-turn-proxy";; *) return 1;; esac; }
dl_turn_bin(){ local owner="$1" arch="$2" out="$3" base url m; base="https://github.com/$owner/releases/latest/download/server-linux-$arch"
  for url in "$base" $(for m in ${SWG_TURN_MIRROR:-}; do printf '%s ' "${m%/}/$base"; done); do
    curl -fsSL --connect-timeout 20 --max-time 240 --retry 3 --retry-delay 3 --retry-all-errors "$url" -o "$out" && return 0
  done; return 1; }
