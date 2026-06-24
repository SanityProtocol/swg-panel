# swg-panel — shared installer helpers (sourced by install-host/node/docker.sh + convert.sh).
# Pure, stateless helpers that were byte-identical across the installers. Functions that depend on
# per-script state (port_free, v_host/v_port, have) are CALLED here but defined by the sourcing script,
# so behaviour is unchanged. Keep only provably-identical helpers here; don't add drifted ones.
#
# NB: this file is sourced, not executed — no shebang, no `set`, no side effects at load time.

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
