# swg-panel — shared installer helpers (sourced by install-host/node/docker.sh + convert.sh).
# Pure, stateless helpers that were byte-identical across the installers. Functions that depend on
# per-script state (port_free, v_host/v_port, have) are CALLED here but defined by the sourcing script,
# so behaviour is unchanged. Keep only provably-identical helpers here; don't add drifted ones.
#
# NB: this file is sourced, not executed — no shebang, no `set`, no side effects at load time.

# pretty protocol name for interface listings: awg → AmneziaWG, wg → Wireguard (anything else passes through)
proto_label(){ case "$1" in wg) printf 'Wireguard';; awg) printf 'AmneziaWG';; *) printf '%s' "$1";; esac; }

# the bordered, bold title every summary opens with — keeps one style across install / re-install / convert /
# update for node / host / master. Pass the operation phrase, e.g. "CONVERSION COMPLETE", "INSTALL COMPLETE".
# Leading blank above, blank below — callers add their final trailing blank with summary_end.
summary_title(){ echo; echo "$(b "──────────────── $1 ────────────────")"; echo; }
# the single trailing blank line every summary must end with (consistency across all scripts).
summary_end(){ echo; }

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

# ── unified per-server summary ────────────────────────────────────────────────
# print_summary <OP> [converted-parts] — ONE summary for ANY operation. Builds up to two blocks from what's
# actually on this box: a HOST block (iff a panel is installed) and a NODE block (iff a local node is installed),
# each tagged with its OWN method + version + an optional "newly converted" note. Only the title (+ that note)
# differ between install / re-install / update / convert; absent blocks are omitted; a blank line separates the
# two when both exist. Self-contained — DETECTS the methods and reads the live config, so every caller is just
# `print_summary <OP> [host|node|both]`.   <OP> ∈ INSTALL | RE-INSTALL | UPDATE | CONVERSION.
_SUM_DDIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"
_sum_get(){ sed -n "s/^$2=//p" "$1" 2>/dev/null | head -1 | sed 's/^"//; s/"$//' || true; }   # || true: pipefail+set -e safe when the file is missing
_sum_proto_label(){ case "$1" in wg|wireguard|WireGuard) echo WireGuard;; *) echo AmneziaWG;; esac; }
_sum_fwd_iface(){ local cp="${1##*:}" f lp; for f in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf "$_SUM_DDIR"/data/node-confs/*.conf; do [ -f "$f" ] || continue; lp="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$f" 2>/dev/null | head -1)"; [ -n "$lp" ] && [ "$lp" = "$cp" ] && { basename "$f" .conf; return 0; }; done; return 0; }
_sum_iface_row(){ local n="$1" proto="$2" conf="$3" ep="$4" lp addr
  lp="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$conf" 2>/dev/null | head -1 || true)"
  addr="$(sed -n 's/^[[:space:]]*Address[[:space:]]*=[[:space:]]*\([0-9./]*\).*/\1/p' "$conf" 2>/dev/null | head -1 || true)"
  printf '    %s%s%s  %s%-10s%s  %s:%s  %s\n' "${C_GREEN:-}" "$(printf '%-10s' "$n")" "${RESET:-}" "${BOLD:-}" "$(_sum_proto_label "$proto")" "${RESET:-}" "${ep:-?}" "${lp:-?}" "${addr:-?}"; }
_sum_turn_row(){ local fw; fw="$(_sum_fwd_iface "${3:-}")"; printf '    %s%s%s %s → %s%s\n' "${C_GREEN:-}" "$1" "${RESET:-}" "${2:-?}" "${3:-?}" "${fw:+ ($fw)}"; }
_sum_node_ep(){ local ep; ep="$(python3 -c 'import json;print((json.load(open("/etc/swg-agent/config.json")).get("endpoint_host") or ""))' 2>/dev/null || true)"; [ -n "$ep" ] || ep="$(_sum_get "$_SUM_DDIR/.env" NODE_ENDPOINT)"; [ -n "$ep" ] || ep="$(detect_public_ip 2>/dev/null || true)"; printf '%s' "$ep"; }
# the host:port the NODE actually dials for the panel — its agent's panel.url (127.0.0.1:443 for a local node,
# the public URL for a remote one). Distinct from the panel's own public URL.
_sum_node_purl(){ local u; u="$(python3 -c 'import json;print((json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("url") or "")' 2>/dev/null || true)"; [ -n "$u" ] || u="$(_sum_get "$_SUM_DDIR/.env" PANEL_URL)"; printf '%s' "$u"; }
_sum_detect(){ local hm="" nm=""   # echoes "<host_method> <node_method>", each ∈ baremetal|docker|"" (none)
  if have docker && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-panel; then hm=docker
  elif [ -f /etc/systemd/system/swg-panel-server.service ] || [ -x /opt/swg-panel/swg-panel-server ]; then hm=baremetal; fi
  if have docker && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-node; then nm=docker
  elif [ -f /etc/systemd/system/swg-noded.service ] || [ -f /etc/swg-agent/config.json ]; then nm=baremetal; fi
  printf '%s %s' "$hm" "$nm"; }
_sum_note(){ case "$1" in docker) echo "$(b 'newly converted') (was bare-metal)";; *) echo "$(b 'newly converted') (was docker)";; esac; }

summary_host_block(){   # <method> <converted?yes|no>
  local m="$1" conv="$2" url login tls ver mlabel note="" e dom port base sch ps
  if [ "$m" = docker ]; then e="$_SUM_DDIR/.env"; mlabel=Docker
    dom="$(_sum_get "$e" PANEL_DOMAIN)"; port="$(_sum_get "$e" PANEL_PORT)"; base="$(_sum_get "$e" PANEL_BASE)"; tls="$(_sum_get "$e" TLS)"
    login="$(_sum_get "$e" PANEL_USER)"; ver="$(docker exec swg-panel cat /opt/swg-panel/VERSION 2>/dev/null | head -1 || true)"
  else mlabel=Bare-metal
    dom="$(_sum_get /etc/swg-panel/install.conf PANEL_DOMAIN)"; port="$(_sum_get /etc/swg-panel/install.conf PORT)"; base="$(_sum_get /etc/swg-panel/install.conf PANEL_BASE)"; tls="$(_sum_get /etc/swg-panel/install.conf TLS_MODE)"
    login="$(sed -n 's/^\([^:]*\):.*/\1/p' /etc/swg-panel/auth 2>/dev/null | head -1 || true)"; ver="$(cat /opt/swg-panel/VERSION 2>/dev/null | head -1 || true)"
  fi
  sch=https; [ "$tls" = none ] && sch=http; ps=":$port"; case "$port" in 443|80|"") ps="";; esac; url="${sch}://${dom}${ps}${base}/"
  [ "$conv" = yes ] && note="  ·  $(_sum_note "$m")"
  echo "  $(b "$mlabel SWG Host")${ver:+ $(b "v$ver")}$note"
  echo; echo "  $(b 'Panel') (login + the $(b "${tls:-?}") cert preserved):"; echo
  printf '    %-9s%s\n' "URL"     "$(bb "$url")"
  printf '    %-9s%s\n' "Login"   "$(b "${login:-admin}")  (unchanged)"
  printf '    %-9s%s\n' "TLS"     "$(b "${tls:-?}")"
  if [ "$m" = docker ]; then
    printf '    %-9s%s\n' "Config"  "$(b "nano $_SUM_DDIR/.env")"
    printf '    %-9s%s\n' "Restart" "$(b "cd $_SUM_DDIR && docker compose restart swg-panel")"
    printf '    %-9s%s\n' "Logs"    "$(b "cd $_SUM_DDIR && docker compose logs -f swg-panel")"
  else
    printf '    %-9s%s\n' "Config"  "$(b /etc/swg-panel/)  (change URL/TLS by re-running the installer)"
    printf '    %-9s%s\n' "Restart" "$(b 'systemctl restart swg-panel-server')"
    printf '    %-9s%s\n' "Logs"    "$(b 'journalctl -u swg-panel-server -f')"
  fi
}
summary_node_block(){   # <method> <converted?yes|no>
  local m="$1" conv="$2" ver mlabel note="" nep purl conf n proto units svc inst lis con u
  nep="$(_sum_node_ep)"; purl="$(_sum_node_purl)"
  if [ "$m" = docker ]; then mlabel=Docker; ver="$(docker exec swg-node cat /opt/swg-noded/VERSION 2>/dev/null | head -1 || true)"
  else mlabel=Bare-metal; ver="$(cat /opt/swg-noded/VERSION 2>/dev/null | head -1 || true)"; fi
  [ "$conv" = yes ] && note="  ·  $(_sum_note "$m")"
  echo "  $(b "$mlabel SWG Node")${ver:+ $(b "v$ver")}${purl:+  ·  syncs to $(bb "$purl")}$note"
  if [ "$m" = docker ]; then
    echo; echo "  $(b 'Interfaces') (in the swg-node container):"; echo
    for conf in "$_SUM_DDIR"/data/node-confs/*.conf; do [ -f "$conf" ] || continue; n="$(basename "$conf" .conf)"
      grep -qiE '^[[:space:]]*(Jc|Jmin|S1|H1)[[:space:]]*=' "$conf" && proto=awg || proto=wg; _sum_iface_row "$n" "$proto" "$conf" "$nep"; done
    units="$(docker ps --format '{{.Names}}' 2>/dev/null | grep '^swg-turn-' || true)"
    if [ -n "$units" ]; then echo; echo "  $(b 'Turn-proxies') (sibling containers — swg-turn-*, managed from the panel):"; echo
      for svc in $units; do _sum_turn_row "$svc" "" ""; done; fi
  else
    echo; echo "  $(b 'Interfaces') (managed bare-metal — peers stay in the panel):"; echo
    for conf in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf; do [ -f "$conf" ] || continue; n="$(basename "$conf" .conf)"
      case "$conf" in */wireguard/*) proto=wg;; *) proto=awg;; esac; _sum_iface_row "$n" "$proto" "$conf" "$nep"; done
    units="$(ls /etc/systemd/system/vk-turn-proxy-*.service 2>/dev/null || true)"
    if [ -n "$units" ]; then echo; echo "  $(b 'Turn-proxies') (host systemd, managed from the panel):"; echo
      for u in $units; do svc="$(basename "$u" .service)"; inst="${svc#vk-turn-proxy-}"
        lis="$(sed -n 's/^SWG_LISTEN=//p' "/opt/vk-turn-proxy/$inst/turn.env" 2>/dev/null | head -1 || true)"
        con="$(sed -n 's/^SWG_CONNECT=//p' "/opt/vk-turn-proxy/$inst/turn.env" 2>/dev/null | head -1 || true)"
        _sum_turn_row "$svc" "$lis" "$con"; done; fi
  fi
  echo; node_reconfig_block "$([ "$m" = docker ] && echo docker || echo baremetal)" "$_SUM_DDIR"
}
print_summary(){   # <OP> [converted-parts: host|node|both]
  local op="$1" conv="${2:-}" det hm nm title hc=no nc=no printed=""
  det="$(_sum_detect)"; hm="${det%% *}"; nm="${det##* }"
  case "$op" in INSTALL) title="INSTALL COMPLETE";; RE-INSTALL) title="RE-INSTALL COMPLETE";; UPDATE) title="UPDATE COMPLETE";; CONVERSION) title="CONVERSION COMPLETE";; *) title="$op COMPLETE";; esac
  case " $conv " in *" host "*|*" both "*) hc=yes;; esac
  case " $conv " in *" node "*|*" both "*) nc=yes;; esac
  summary_title "$title"
  [ -n "$hm" ] && { summary_host_block "$hm" "$hc"; printed=1; }
  [ -n "$nm" ] && { [ -n "$printed" ] && echo; summary_node_block "$nm" "$nc"; }
  summary_end
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
# Data-entry spacing: a prompt helper ends with _pnl — ONE trailing blank line + a mark. The next step() skips its
# own leading blank while that mark is up (so prompt→step shows ONE blank, not two); any real output (info/ok/warn/
# sub, or another step) lowers the mark so content→step still gets its separating blank. Net: exactly one blank line
# after every data-entry prompt, everywhere, without doubling.
_SWG_NL=""
_pnl(){ echo; _SWG_NL=1; }                     # call at the end of a prompt helper (interactive path only)
_nlguard(){ _SWG_NL=""; }                      # call from real-output helpers so they don't get swallowed
LC_OP=""; LC_EMIT=""; LC_LOG=""; LC_ABORT=""; LC_HANDOFF=""; LC_DONE=""; LC_SUCCESS=""
_lc_inprogress(){ case "$1" in reinstall) echo reinstalling;; convert-bare) echo converting-bare;; convert-docker) echo converting-docker;; update) echo updating;; uninstall) echo uninstalling;; esac; }
_lc_success(){    case "$1" in reinstall) echo reinstalled;; convert-bare) echo converted-bare;; convert-docker) echo converted-docker;; update) echo updated;; uninstall) echo "";; esac; }
_lc_prefix(){     case "$1" in convert-*) echo convert;; *) echo "$1";; esac; }   # aborted/failed are op-generic
lc_emit(){ [ -n "${LC_EMIT:-}" ] && [ -n "${1:-}" ] && "$LC_EMIT" "$1" "${2:-}" || true; }
lc_handoff(){ LC_HANDOFF=1; }                                  # another script now owns the terminal (convert→installer)
lc_emit_post(){ [ -n "${LC_URL:-}" ] && [ -n "${LC_TOKEN:-}" ] || return 0
  local ins=""; [ "${LC_VERIFY:-no}" = yes ] || ins="-k"; local data="" _i
  if [ -n "${2:-}" ]; then data="$(python3 -c 'import json,sys;print(json.dumps({"state":sys.argv[1],"err":sys.argv[2]}))' "$1" "$2" 2>/dev/null)"; fi
  [ -n "$data" ] || data="{\"state\":\"$1\"}"
  # RETRY: a single best-effort POST silently drops the status when the panel is briefly unreachable mid-convert
  # (just restarted / settling, or an opposite convert fired the instant the new panel came up) — exactly why
  # "converting" sometimes never showed and a stale "converted" wouldn't flip to "converting". A few quick retries
  # make converting/converted reliably land. Still best-effort overall (never trips set -e).
  for _i in 1 2 3 4; do
    curl -fsS $ins --max-time 6 -X POST -H "Authorization: Bearer $LC_TOKEN" -H "Content-Type: application/json" \
      --data "$data" "${LC_URL%/}/api/node/proc-status" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 0; }
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
# teardown_bare_panel — stop + remove the bare-metal panel (units + proxy vhost + binary), then move its STATE
# dirs aside (already staged into data/) so the box no longer reads as a bare panel and a later convert-back
# restages cleanly. Used by the bare→docker host/master convert (install-docker.sh, at the atomic switch).
teardown_bare_panel(){
  systemctl disable --now swg-panel-server >/dev/null 2>&1 || true
  systemctl disable --now swg-update.path  >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/swg-panel-server.service /etc/systemd/system/swg-update.service /etc/systemd/system/swg-update.path /usr/local/bin/swg-update
  rm -rf /etc/systemd/system/swg-panel-server.service.d
  rm -f /etc/nginx/sites-enabled/swg-panel.conf /etc/nginx/sites-available/swg-panel.conf /etc/nginx/conf.d/swg-panel.conf
  command -v nginx >/dev/null 2>&1 && { nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1; } || true
  rm -rf /opt/swg-panel /usr/local/bin/swg-panel-server   # remove the bare binary too, else the box still reads as a bare panel (bootstrap won't offer convert-back)
  for _d in /var/lib/swg-panel /etc/swg-panel; do [ -d "$_d" ] && mv "$_d" "$_d.converted-$(date +%Y%m%d-%H%M%S 2>/dev/null || echo bak)" 2>/dev/null || true; done
  systemctl daemon-reload >/dev/null 2>&1 || true; }
lc_teardown_docker(){   # stop+remove the docker datapath (container + stack), freeing wg ports + host netdevs
  local d="${1:-/opt/swg-panel-docker}"
  command -v docker >/dev/null 2>&1 || return 0
  docker rm -f swg-node >/dev/null 2>&1 || true
  for _c in $(docker ps -aq --filter name=swg-turn- 2>/dev/null || true); do docker rm -f "$_c" >/dev/null 2>&1 || true; done   # turn-proxy containers hold the listen ports the migrated bare units need
  # docker host networking leaves the node's wg/awg interfaces in the HOST netns — `docker rm` can't remove them.
  # Delete the ones it managed (names from data/node-confs) so they don't linger as confless orphans (a later
  # install would adopt one as a ghost) or collide with a fresh bring-up; whatever's still wanted is recreated after.
  if command -v ip >/dev/null 2>&1; then for _c in "$d/data/node-confs/"*.conf; do [ -f "$_c" ] || continue
    ip link delete dev "$(basename "$_c" .conf)" >/dev/null 2>&1 || true; done; fi
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
