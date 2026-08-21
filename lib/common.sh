# swg-panel — shared installer helpers (sourced by install-host/node/docker.sh + convert.sh).
# Pure, stateless helpers that were byte-identical across the installers. Functions that depend on
# per-script state (port_free, v_host/v_port, have) are CALLED here but defined by the sourcing script,
# so behaviour is unchanged. Keep only provably-identical helpers here; don't add drifted ones.
#
# NB: this file is sourced, not executed — no shebang, no `set`, no side effects at load time.

# Web assets swg-sub serves (its STATIC allow-list, minus vendor/qrcode.js which every site copies separately).
# ONE list, shared by every installer/updater copy site — the four images were allow-listed by the server but
# absent from all four copy loops, so `_a/import-hint.png` (and the client logos) 404'd on every install since
# they were added. Keep this in sync with STATIC in swg-sub; nothing else needs touching when an asset is added.
SUB_WEB="sub.html sub.js sub.css turn-artifacts.js import-hint.png amneziavpn.svg amneziawg.png wireguard.svg"

# pretty protocol name for interface listings: awg → AmneziaWG, wg → Wireguard (anything else passes through)
proto_label(){ case "$1" in wg) printf 'Wireguard';; awg) printf 'AmneziaWG';; *) printf '%s' "$1";; esac; }

# System (panel-managed inter-node mesh-link) interfaces use a reserved name prefix (default `swg_`); user
# interfaces can never use it (the panel rejects it). These are NOT user interfaces and must never be
# presented/offered in any installer / re-installer / docker / convert / uninstall listing.
# is_sys_iface <name> → 0 if it's a system iface; drop_sys_ifaces filters them from stdin (one name/line).
SWG_SYS_PREFIX="${SWG_SYS_PREFIX:-swg_}"
is_sys_iface(){ case "$1" in "$SWG_SYS_PREFIX"*) return 0;; *) return 1;; esac; }
drop_sys_ifaces(){ grep -v "^[[:space:]]*${SWG_SYS_PREFIX}" || true; }

# bold (b) + bold-blue link (bb) text — print_summary uses both, but convert.sh / update.sh don't define bb
# themselves, so provide them here. The guard only FILLS A GAP: a script that defines its own (identical) b/bb
# keeps it, in any source order. Colours are read at call time, so they need not be set when this file is sourced.
command -v b  >/dev/null 2>&1 || b(){  printf '%s%s%s'   "${BOLD:-}" "$*" "${RESET:-}"; }
command -v bb >/dev/null 2>&1 || bb(){ printf '%s%s%s%s' "${BOLD:-}" "${C_BLUE:-}" "$*" "${RESET:-}"; }
# `have` is used by print_summary's detection (and v_subnet) but is normally a per-script helper — convert.sh
# doesn't define it, so _sum_detect printed "have: command not found" and returned no methods → an empty summary.
command -v have >/dev/null 2>&1 || have(){ command -v "$1" >/dev/null 2>&1; }

# Run curl with a node bearer token kept OFF the argv — so it can't leak through `ps` / /proc/<pid>/cmdline
# (world-readable by default) to another local user or a co-resident process during an install. The token is fed
# to curl through a --config file on stdin (the `header` config option is exactly `-H`); URL, method, --data, -k
# and everything non-secret stay on the argv as usual. Usage:  auth_curl <token> <curl-args...>
# NB: the wrapped curl must NOT itself read stdin (no `-d @-` / `--config -`) — stdin carries the auth header here.
auth_curl(){ local _tok="$1"; shift
  curl "$@" --config /dev/stdin <<CURLCFG
header = "Authorization: Bearer ${_tok}"
CURLCFG
}

# Prompt for a SECRET (the node enrollment key) with terminal echo OFF, so it never lands in scrollback / a
# screen recording / a shared session — and an EXISTING value (re-install default) is offered as "[keep current]"
# rather than printed. Same contract + non-interactive short-circuit as the installers' ask_valid: a value already
# in the var (from -key / env) is validated and returned with NO prompt. col()/C_BLUE/die/_pnl come from the
# sourcing script (resolved at call time). Usage: ask_secret <prompt> <default> <var> <validator_fn> <hint>
ask_secret(){ local p="$1" d="$2" var="$3" fn="$4" hint="$5" v rc
  if [ -n "${!var:-}" ]; then "$fn" "${!var}" && return
    warn "ignoring invalid $var (${hint})"; fi
  [ -n "${_SWG_NL:-}" ] || echo; _SWG_NL=""
  while :; do
    printf '  %s%s: ' "$p" "${d:+ [$(col "${C_BLUE:-}" 'keep current')]}" >/dev/tty 2>/dev/null || printf '  %s: ' "$p"
    if read -rs v </dev/tty; then rc=0; else rc=1; v=""; fi
    printf '\n' >/dev/tty 2>/dev/null || echo               # read -s swallows the newline the operator pressed
    v="${v:-$d}"
    if "$fn" "$v"; then printf -v "$var" '%s' "$v"; _pnl; return; fi
    [ "$rc" -ne 0 ] && die "no value for ‘$p’ and no interactive input to re-prompt"
    warn "$hint"
  done; }

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
  echo "  Interfaces, turn-proxies, WDTT and csqtt servers can be re-configured in the web panel, or directly on the server:"; echo
  if [ "$method" = docker ]; then
    printf '    %-13s %s\n' "Interfaces"   "$(b "ls $dir/data/node-confs/*.conf")"
    printf '    %-13s %s\n' "Turn-proxies" "$(b 'docker ps --filter name=swg-turn')"
    printf '    %-13s %s\n' "WDTT"         "$(b "cat $dir/data/node/wdtt.json")   (servers + their interfaces)"
    printf '    %-13s %s\n' "csqtt"        "$(b "cat $dir/data/node/csqtt.json")  (servers + their interfaces)"
    echo
    printf '    %-13s %s\n' "Directory"    "$(b "cd $dir")"
    printf '    %-13s %s\n' "Restart"      "$(b "cd $dir && $C restart swg-node")"
    printf '    %-13s %s\n' "Logs"         "$(b "cd $dir && $C logs -f swg-node")"
    printf '    %-13s %s\n' "Config"       "$(b "nano $dir/.env") (after edit run $(b "$C --profile $prof up -d"))"
  else
    printf '    %-13s %s\n' "AmneziaWG"    "$(b 'ls /etc/amnezia/amneziawg/*.conf')"
    printf '    %-13s %s\n' "WireGuard"    "$(b 'ls /etc/wireguard/*.conf')"
    printf '    %-13s %s\n' "Turn-proxies" "$(b 'ls /etc/systemd/system/vk-turn-proxy*.service')"
    printf '    %-13s %s\n' "WDTT"         "$(b 'ls /etc/systemd/system/swg-wdtt-*.service')   (servers + their interfaces)"
    printf '    %-13s %s\n' "csqtt"        "$(b 'ls /etc/systemd/system/swg-csqtt-*.service')  (servers + their interfaces)"
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

# Subscription surface for the summary — the per-user QR page (swg-sub). Emits three TAB-separated fields:
#   <enabled|disabled|unset>  <auto|manual>  <public url>
# Read straight from panel-settings.json (the panel owns it) rather than from install.conf/.env, which only
# carry the BIND — the public URL and the on/off switch are panel state and can be changed after install.
_sum_sub_state(){   # <baremetal|docker>
  local ps; if [ "$1" = docker ]; then ps="$_SUM_DDIR/data/lib/panel-settings.json"; else ps=/var/lib/swg-panel/panel-settings.json; fi
  [ -f "$ps" ] || { printf 'unset\t\t'; return 0; }
  have python3 || { printf 'unset\t\t'; return 0; }
  python3 - "$ps" <<'PYSUB' 2>/dev/null || printf 'unset\t\t'
import json, sys
try: d = json.load(open(sys.argv[1]))
except Exception: print("unset\t\t"); raise SystemExit
sub = d.get("subscriptions") or {}
url = (((d.get("access") or {}).get("sub") or {}).get("url") or "").rstrip("/")
state = "enabled" if sub.get("enabled") else ("disabled" if "enabled" in sub else "unset")
print("%s\t%s\t%s" % (state, "auto" if sub.get("auto_generate") else "manual", url))
PYSUB
}
summary_sub_block(){   # <method>
  local st auto url
  IFS="$(printf '\t')" read -r st auto url <<EOS
$(_sum_sub_state "$1")
EOS
  echo
  case "$st" in
    enabled)
      local _how="manually"; [ "$auto" = auto ] && _how="automatically"
      echo "  $(b 'Subscriptions') (per-user links created $(b "$_how")):"
      echo
      if [ -n "$url" ]; then printf '    %-9s%s\n' "URL" "$(bb "$url/")$(b '<user-link>')"
      else                   printf '    %-9s%s\n' "URL" "not set yet — set the subscription address in the panel"; fi
      echo
      if [ "$auto" = auto ]; then echo "    A link is minted for every new user automatically."
      else                        echo "    Links are minted per user, on demand — open a user and create theirs."; fi
      ;;
    disabled) echo "  $(b 'Subscriptions') (off):"; echo
              echo "    Every subscription URL returns 404. Nobody can load a config from a link." ;;
    *)        echo "  $(b 'Subscriptions') (not configured yet):"; echo
              echo "    Off until you turn them on — the per-user QR page is not being served." ;;
  esac
  echo
  echo "    Configure in the panel: $(b 'Settings → Subscriptions')"
}
summary_host_block(){   # <method> <converted?yes|no>
  local m="$1" conv="$2" url login tls ver mlabel note="" e dom port base sch ps reset
  if [ "$m" = docker ]; then e="$_SUM_DDIR/.env"; mlabel=Docker
    dom="$(_sum_get "$e" PANEL_DOMAIN)"; port="$(_sum_get "$e" PANEL_PORT)"; base="$(_sum_get "$e" PANEL_BASE)"; tls="$(_sum_get "$e" TLS)"
    login="$(_sum_get "$e" PANEL_USER)"; ver="$(docker exec swg-panel cat /opt/swg-panel/VERSION 2>/dev/null | head -1 || true)"
  else mlabel=Bare-metal
    dom="$(_sum_get /etc/swg-panel/install.conf PANEL_DOMAIN)"; port="$(_sum_get /etc/swg-panel/install.conf PORT)"; base="$(_sum_get /etc/swg-panel/install.conf PANEL_BASE)"; tls="$(_sum_get /etc/swg-panel/install.conf TLS_MODE)"
    login="$(sed -n 's/^\([^:]*\):.*/\1/p' /etc/swg-panel/auth 2>/dev/null | head -1 || true)"; ver="$(cat /opt/swg-panel/VERSION 2>/dev/null | head -1 || true)"
  fi
  sch=https; [ "$tls" = none ] && sch=http; ps=":$port"; case "$port" in 443|80|"") ps="";; esac; url="${sch}://${dom}${ps}${base}/"
  [ "$conv" = yes ] && note="  ·  $(_sum_note "$m")"
  echo "${C_BLUE:-}▸${RESET:-} $(b "$mlabel SWG Host")${ver:+ $(b "v$ver")}$note"
  echo
  # A fresh install MINTS the login, and the auth file only ever holds the pbkdf2 hash — so this summary is the one
  # and only place the plaintext password is ever shown. The installer hands it over in SWG_SUMMARY_PASS; without it
  # (re-install / convert) the existing login is untouched and there's no password to show.
  if [ -n "${SWG_SUMMARY_PASS:-}" ]; then echo "  $(b 'Panel') (new login — $(b 'save the password now'), it is not shown again):"
  else                                    echo "  $(b 'Panel') (login + the $(b "${tls:-?}") cert preserved):"; fi
  echo
  printf '    %-9s%s\n' "URL"     "$(bb "$url")"
  if [ "$m" = docker ]; then reset="docker exec -it swg-panel swg-passwd"
  else reset="sudo swg-passwd"; fi
  if [ -n "${SWG_SUMMARY_PASS:-}" ]; then
    printf '    %-9s%s\n' "Login"    "$(b "${login:-admin}")"
    printf '    %-9s%s\n' "Password" "$(b "$SWG_SUMMARY_PASS")  (change it in the panel: Account · or reset with $(b "$reset"))"
  else
    printf '    %-9s%s\n' "Login"   "$(b "${login:-admin}")  (to reset the password run: $(b "$reset"))"
  fi
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
  summary_sub_block "$m"    # the subscription surface is part of what a panel install delivers — say where it stands
}
# WDTT servers on this node, from the record swg-noded keeps (bare-metal /etc/swg-agent, docker the mounted
# data dir). They own their interface (created by the server, so it has no .conf the interface scan could find)
# AND act as a turn-family proxy — so the summary gives them their own section instead of splitting them.
_sum_wdtt_rows(){   # <baremetal|docker>
  local rec; if [ "$1" = docker ]; then rec="$_SUM_DDIR/data/node/wdtt.json"; else rec=/etc/swg-agent/wdtt.json; fi
  [ -f "$rec" ] || return 0
  have python3 || return 0
  python3 -c 'import json,sys
try: w=(json.load(open(sys.argv[1])).get("wdtt") or [])
except Exception: w=[]
for i in w:
    if isinstance(i,dict) and i.get("iface"):
        print("\t".join([i["iface"], i.get("fork") or "?", i.get("listen") or ("127.0.0.1:%s" % (i.get("wg_port") or "?")), i.get("wg_addr") or "?"]))' "$rec" 2>/dev/null
}
_sum_wdtt_row(){ printf '    %s%-10s%s  %s%-10s%s  %s  %s\n' "${C_GREEN:-}" "$1" "${RESET:-}" "${BOLD:-}" "$2" "${RESET:-}" "${3:-?}" "${4:-?}"; }

_sum_wdtt_block(){   # <baremetal|docker> — the "WDTT interfaces & proxies" section, printed only when any exist
  local rows _i _f _l _a
  rows="$(_sum_wdtt_rows "$1")"; [ -n "$rows" ] || return 0
  echo; echo "  $(b 'WDTT interfaces & proxies') (own their interface — managed from the panel):"; echo
  while IFS="$(printf '\t')" read -r _i _f _l _a; do [ -n "$_i" ] && _sum_wdtt_row "$_i" "$_f" "$_l" "$_a"; done <<EOS
$rows
EOS
}
# csqtt servers, same section shape. Its record is a flat {iface: inst} map (WDTT's is a list under "wdtt"), and the
# fork column is always csqtt — one implementation, no fork variance — so it reports the subnet's tun_addr instead.
_sum_csqtt_rows(){   # <baremetal|docker>
  local rec; if [ "$1" = docker ]; then rec="$_SUM_DDIR/data/node/csqtt.json"; else rec=/etc/swg-agent/csqtt.json; fi
  [ -f "$rec" ] || return 0
  have python3 || return 0
  python3 -c 'import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
if isinstance(d,dict):
    for k,i in d.items():
        if isinstance(i,dict):
            print("\t".join([k, "csqtt", i.get("listen") or "?", i.get("tun_addr") or "?"]))' "$rec" 2>/dev/null
}
_sum_csqtt_block(){   # <baremetal|docker> — printed only when any exist
  local rows _i _f _l _a
  rows="$(_sum_csqtt_rows "$1")"; [ -n "$rows" ] || return 0
  echo; echo "  $(b 'csqtt interfaces & proxies') (own their interface — managed from the panel):"; echo
  while IFS="$(printf '\t')" read -r _i _f _l _a; do [ -n "$_i" ] && _sum_wdtt_row "$_i" "$_f" "$_l" "$_a"; done <<EOS
$rows
EOS
}
summary_node_block(){   # <method> <converted?yes|no>
  local m="$1" conv="$2" ver mlabel note="" nep purl conf n proto units svc inst lis con u _trec _meshif
  nep="$(_sum_node_ep)"; purl="$(_sum_node_purl)"
  if [ "$m" = docker ]; then mlabel=Docker; ver="$(docker exec swg-node cat /opt/swg-noded/VERSION 2>/dev/null | head -1 || true)"
  else mlabel=Bare-metal; ver="$(cat /opt/swg-noded/VERSION 2>/dev/null | head -1 || true)"; fi
  [ "$conv" = yes ] && note="  ·  $(_sum_note "$m")"
  echo "${C_BLUE:-}▸${RESET:-} $(b "$mlabel SWG Node")${ver:+ $(b "v$ver")}${purl:+  ·  syncs to $(bb "$purl")}$note"
  if [ "$m" = docker ]; then
    # Header only when there is something under it. Installers no longer create interfaces — the panel does —
    # so a fresh install used to print the heading over an empty list, announcing a section that had no content.
    _ifn=0; for conf in "$_SUM_DDIR"/data/node-confs/*.conf; do [ -f "$conf" ] && _ifn=$((_ifn+1)); done
    echo
    if [ "$_ifn" -eq 0 ]; then echo "  $(b 'Interfaces'):  none yet — add them in the web panel"
    else echo "  $(b 'Interfaces') (in the swg-node container):"; fi
    echo
    _meshif=""
    for conf in "$_SUM_DDIR"/data/node-confs/*.conf; do [ -f "$conf" ] || continue; n="$(basename "$conf" .conf)"
      is_sys_iface "$n" && { _meshif="$_meshif $n"; continue; }   # panel-managed mesh link — never listed as a user interface
      grep -qiE '^[[:space:]]*(Jc|Jmin|S1|H1)[[:space:]]*=' "$conf" && proto=awg || proto=wg; _sum_iface_row "$n" "$proto" "$conf" "$nep"; done
    for n in $_meshif; do printf '    %s Mesh interface %s\n' "${C_BLUE:-}→${RESET:-}" "${C_BLUE:-}$n${RESET:-}"; done
    units="$(docker ps --format '{{.Names}}' 2>/dev/null | grep '^swg-turn-' || true)"; _trec="$_SUM_DDIR/data/node/turn-proxy.json"
    if [ -n "$units" ]; then echo; echo "  $(b 'Turn-proxies') (sibling containers — swg-turn-*, managed from the panel):"; echo
      if [ -f "$_trec" ] && have python3; then   # docker turns are containers — listen/connect live in the node turn record, not a unit file
        python3 -c 'import json,sys
try: tps=(json.load(open(sys.argv[1])).get("turn_proxies") or [])
except Exception: tps=[]
for t in tps:
    if t.get("service"): print(t["service"]+"\t"+t.get("listen","")+"\t"+t.get("connect",""))' "$_trec" 2>/dev/null \
          | while IFS="$(printf '\t')" read -r svc lis con; do [ -n "$svc" ] && _sum_turn_row "$svc" "$lis" "$con"; done
      else for svc in $units; do _sum_turn_row "$svc" "" ""; done; fi
    fi
    _sum_wdtt_block docker
    _sum_csqtt_block docker
  else
    _ifn=0; for conf in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf; do [ -f "$conf" ] && _ifn=$((_ifn+1)); done
    echo
    if [ "$_ifn" -eq 0 ]; then echo "  $(b 'Interfaces'):  none yet — add them in the web panel"
    else echo "  $(b 'Interfaces') (managed bare-metal — peers stay in the panel):"; fi
    echo
    _meshif=""
    for conf in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf; do [ -f "$conf" ] || continue; n="$(basename "$conf" .conf)"
      is_sys_iface "$n" && { _meshif="$_meshif $n"; continue; }   # panel-managed mesh link — never listed as a user interface
      case "$conf" in */wireguard/*) proto=wg;; *) proto=awg;; esac; _sum_iface_row "$n" "$proto" "$conf" "$nep"; done
    for n in $_meshif; do printf '    %s Mesh interface %s\n' "${C_BLUE:-}→${RESET:-}" "${C_BLUE:-}$n${RESET:-}"; done
    units="$(ls /etc/systemd/system/vk-turn-proxy-*.service 2>/dev/null || true)"
    if [ -n "$units" ]; then echo; echo "  $(b 'Turn-proxies') (host systemd, managed from the panel):"; echo
      for u in $units; do svc="$(basename "$u" .service)"; inst="${svc#vk-turn-proxy-}"
        lis="$(sed -n 's/^SWG_LISTEN=//p' "/opt/vk-turn-proxy/$inst/turn.env" 2>/dev/null | head -1 || true)"
        con="$(sed -n 's/^SWG_CONNECT=//p' "/opt/vk-turn-proxy/$inst/turn.env" 2>/dev/null | head -1 || true)"
        _sum_turn_row "$svc" "$lis" "$con"; done; fi
    _sum_wdtt_block baremetal
    _sum_csqtt_block baremetal
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

# A co-located node dials the panel over LOOPBACK (http://127.0.0.1:<local-port>) — plain HTTP there is the
# design, not a mistake: the request never leaves the box, so there is no wire to intercept. Warning about it
# on every master install/convert taught operators to ignore a message that is real for a REMOTE node.
_url_is_loopback(){ case "${1#*://}" in 127.0.0.1|127.0.0.1:*|localhost|localhost:*|\[::1\]|\[::1\]:*|::1|::1:*) return 0;; *) return 1;; esac; }

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
  #   • IN-PROGRESS states stay short: the panel is about to restart from THIS op — don't block the update on it.
  #   • TERMINAL states (updated / converted / reinstalled / *-failed / *-aborted) are emitted right when the
  #     panel may be restarting from this very op (a master host-update restarts the panel, THEN posts the node's
  #     "updated"), so wait ~30s for it to come back — otherwise the tag hangs until PROC_GRACE flips it to a
  #     FALSE "<op> failed". (The panel also self-heals "updating" once the node reports the target version, so
  #     this is belt-and-suspenders.)
  local _tries; case "$1" in updating|reinstalling|converting-bare|converting-docker|uninstalling) _tries=4;; *) _tries=25;; esac
  # SAY SO while waiting. This runs from the EXIT trap, i.e. AFTER the completion summary has printed, so a
  # silent 25-retry loop looks exactly like a hang at the very moment the operator has been told it's done —
  # and the run then exits fine, which is more baffling still. One line on the first failure, one on give-up.
  _i=0
  while [ "$_i" -lt "$_tries" ]; do
    auth_curl "$LC_TOKEN" -fsS $ins --max-time 6 -X POST -H "Content-Type: application/json" \
      --data "$data" "${LC_URL%/}/api/node/proc-status" >/dev/null 2>&1 && {
        [ "$_i" -gt 0 ] && echo "    panel reached — status recorded." || true; return 0; }
    [ "$_i" -eq 0 ] && echo "    telling the panel this finished (it may still be restarting) — up to ${_tries}s…"
    _i=$((_i + 1)); sleep 1
  done
  echo "    couldn't reach the panel to record the status — the conversion itself is done; the panel corrects the tag on the node's next sync."
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
  # The capture holds the WHOLE run transcript, and print_summary prints the minted panel login in
  # plaintext — the one place it is ever shown. Leaving that in /tmp until the next reboot is a real
  # credential leak on a shared box. The only consumer is the failure tail just above, so drop it here.
  [ -n "${LC_LOG:-}" ] && rm -f "$LC_LOG" 2>/dev/null || true
  return $rc; }
lc_init(){ LC_OP="$1"; LC_EMIT="$2"; LC_ABORT=""; LC_HANDOFF=""; LC_DONE=""; LC_SUCCESS=""
  LC_LOG="$(mktemp 2>/dev/null || echo "/tmp/swg-lc.$$")"; : > "$LC_LOG" 2>/dev/null || true
  chmod 600 "$LC_LOG" 2>/dev/null || true                      # the fallback path (no mktemp) isn't 0600 by itself
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
# Remove the DOCKER address helper (swg-netctl-docker.*) — the mirror of what teardown_bare_panel does to the
# bare units. Used by the docker→bare convert: the bare panel installs its own swg-netctl, and leaving the docker
# pair behind arms a SECOND drainer on the same request queue. Its .timer then wakes every couple of seconds on a
# box with no compose install, hits systemd's start-limit, and races the real helper for the panel's address
# changes. Existence-guarded, so calling it on a box that never had docker is a no-op.
remove_docker_netctl(){
  # .path BELONGS IN THIS LIST. update.sh writes swg-netctl-docker.path (it superseded the 1s .timer), but this
  # helper was written before that existed and never caught up — so a docker→bare-metal convert left the .path
  # ENABLED and ACTIVE, triggering a .service the same call had just deleted. Reproduced converting a master
  # back: `swg-netctl-docker.service not-found failed`, a permanently broken unit that also masks real failures
  # in `systemctl --failed`. uninstall.sh already listed all three; this is that fix, applied to the convert.
  for _u in swg-netctl-docker.path swg-netctl-docker.timer swg-netctl-docker.service; do
    systemctl disable --now "$_u" >/dev/null 2>&1 || systemctl stop "$_u" >/dev/null 2>&1 || true
  done
  rm -f /etc/systemd/system/swg-netctl-docker.service /etc/systemd/system/swg-netctl-docker.timer \
        /etc/systemd/system/swg-netctl-docker.path /usr/local/bin/swg-netctl-docker
  systemctl daemon-reload >/dev/null 2>&1 || true; }

# restages cleanly. Used by the bare→docker host/master convert (install-docker.sh, at the atomic switch).
teardown_bare_panel(){
  systemctl disable --now swg-panel-server >/dev/null 2>&1 || true
  systemctl disable --now swg-update.path  >/dev/null 2>&1 || true
  # swg-sub + swg-netctl are PANEL components — stop them too, or the bare swg-sub keeps port 8444 (the docker
  # swg-sub then can't bind it) and swg-netctl.path lingers. (The node datapath is handled separately.)
  # ONE AT A TIME. `systemctl disable --now a b c` ABORTS THE WHOLE OPERATION if any unit is missing — and
  # swg-netctl-docker.* never exist on a bare-metal box, so the single call below used to fail before stopping
  # anything, leaving the bare swg-sub running and holding its port (exactly what the comment above says it is
  # here to prevent). `|| true` then hid it. Proven: `disable --now probe missing.service` leaves probe ACTIVE
  # and returns 1; the same call without the missing unit stops it and returns 0.
  # The `stop` fallback covers a unit whose FILE is already gone while the process is still alive — `disable`
  # refuses that outright, and it is how the orphan survived a second teardown.
  for _u in swg-sub swg-netctl.path swg-netctl.service swg-netctl.timer swg-netctl-docker.path swg-netctl-docker.timer swg-netctl-docker.service; do
    systemctl disable --now "$_u" >/dev/null 2>&1 || systemctl stop "$_u" >/dev/null 2>&1 || true
  done
  rm -f /etc/systemd/system/swg-sub.service /etc/systemd/system/swg-netctl.service /etc/systemd/system/swg-netctl.path /etc/systemd/system/swg-netctl.timer /usr/local/bin/swg-netctl \
        /etc/systemd/system/swg-netctl-docker.service /etc/systemd/system/swg-netctl-docker.timer /usr/local/bin/swg-netctl-docker
  rm -rf /opt/swg-sub
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

# migrate_wdtt <to-docker|to-baremetal> [docker_dir] — carry the WDTT server state between the two path conventions
# during a convert. SINGLE SOURCE OF TRUTH for both directions (this logic used to be duplicated in install-docker.sh
# + convert.sh ×2, where the copy/strip stayed in sync but the GATING drifted → a WDTT-only master silently re-minted).
# Paths:
#     bare-metal : /opt/swg-wdtt/<iface>/…               record /etc/swg-agent/wdtt.json
#     docker     : <docker_dir>/data/node/wdtt/<iface>/…  record …/data/node/wdtt.json  (→ container /var/lib/swg-noded)
# Each instance's wg-keys.dat is the server IDENTITY; carrying it (+ the record's node-owned owner passwords, and
# passwords.json / panel.db) is what keeps every GETCONF'd client working — a re-mint changes the server pubkey and
# forces every client to reconnect. Copy-first (the source's units are stopped / the container torn down separately,
# at the atomic switch) so a mid-convert abort never drops WDTT; the destination's reconcile then converges.
#
# STRIP (to-baremetal only): a full copy also carries the source run-model's runtime files — the `server` symlink +
# server.pid / server.log / wdtt.env / desired.json, all pointing at the source's paths. The systemd (bare) unit would
# crash-loop on that stale, container-pathed symlink before the reconcile rewrites it, so strip them here (KEEP
# wg-keys.dat / passwords.json / panel.db + the .bin binary cache). to-docker does NOT strip: the docker subprocess
# run-model reads the carried symlink as dangling (paths differ) and rewrites all of it on install — a full copy is
# both safe and simpler. Caller stops/tears down the source datapath separately (see lc_teardown_*).
migrate_wdtt(){
  local dir="$1" dd="${2:-/opt/swg-panel-docker}" src dst srec drec strip=no
  case "$dir" in
    to-docker)    src=/opt/swg-wdtt;        dst="$dd/data/node/wdtt"; srec=/etc/swg-agent/wdtt.json;  drec="$dd/data/node/wdtt.json";;
    to-baremetal) src="$dd/data/node/wdtt"; dst=/opt/swg-wdtt;        srec="$dd/data/node/wdtt.json"; drec=/etc/swg-agent/wdtt.json; strip=yes;;
    *) return 0;;
  esac
  [ -d "$src" ] || return 0
  # A silent `|| true` here was the worst possible failure mode: what is being carried is the server IDENTITY, and
  # a copy that quietly did nothing looks EXACTLY like a successful convert until the operator's clients stop
  # connecting to a re-minted server. Still non-fatal (a half-converted box is worse than a warned one), but loud.
  local _bad=""
  mkdir -p "$dst" || _bad="couldn't create $dst"
  [ -n "$_bad" ] || cp -a "$src/." "$dst/" || _bad="couldn't copy $src → $dst"
  if [ "$strip" = yes ] && [ -z "$_bad" ]; then
    find "$dst/." -mindepth 2 -maxdepth 2 \( -type l -name server -o -type f \( -name server.pid -o -name server.log -o -name wdtt.env -o -name desired.json \) \) -delete 2>/dev/null || true
  fi
  if [ -z "$_bad" ] && [ -f "$srec" ]; then
    mkdir -p "$(dirname "$drec")" && cp -a "$srec" "$drec" || _bad="couldn't copy the WDTT record $srec → $drec"
  fi
  if [ -n "$_bad" ]; then
    warn "WDTT state was NOT carried over: $_bad"
    warn "  the WDTT servers will come up with FRESH identities and existing clients will stop connecting."
    warn "  the originals are untouched in $src — copy them to $dst by hand and restart the node to recover."
    return 0
  fi
  echo "    WDTT server state (identity + config) → $dst"
  return 0; }

# migrate_csqtt <to-docker|to-baremetal> [docker_dir] — the same carry for csqtt servers. Sibling of migrate_wdtt
# rather than a shared core: the paths differ, and so does the honest failure story, which is the part that has to
# be right when it goes wrong.
# Paths:
#     bare-metal : /opt/swg-csqtt/<iface>/…                record /etc/swg-agent/csqtt.json
#     docker     : <docker_dir>/data/node/csqtt/<iface>/…   record …/data/node/csqtt.json  (→ container /var/lib/swg-noded)
# csqtt has NO server keypair — a password IS the credential — so nothing here can re-mint a server identity the way
# WDTT can. What must survive is each instance's passwords.json (the store its clients authenticate against) and the
# record's NODE-OWNED owner password + pw_seen. Lose the record and the node re-mints the owner password over a store
# that still holds the old one; lose the store and every client on that server stops connecting.
# STRIP (to-baremetal only): identical reasoning to WDTT — drop the source run-model's runtime files (the `server`
# symlink + server.pid / server.log / .server.lock / csqtt.env / desired.json, all pointing at container paths) so
# the systemd unit doesn't crash-loop on them before the reconcile rewrites them. KEEP passwords.json and .bin
# (depth 3, so the depth-2 sweep can't reach the binary cache).
migrate_csqtt(){
  local dir="$1" dd="${2:-/opt/swg-panel-docker}" src dst srec drec strip=no
  local bare="${CSQTT_DIR:-/opt/swg-csqtt}" brec="${CSQTT_RECORD:-/etc/swg-agent/csqtt.json}"   # overridable, as in uninstall.sh
  case "$dir" in
    to-docker)    src="$bare";               dst="$dd/data/node/csqtt"; srec="$brec";                   drec="$dd/data/node/csqtt.json";;
    to-baremetal) src="$dd/data/node/csqtt"; dst="$bare";               srec="$dd/data/node/csqtt.json"; drec="$brec"; strip=yes;;
    *) return 0;;
  esac
  [ -d "$src" ] || return 0
  local _bad=""
  mkdir -p "$dst" || _bad="couldn't create $dst"
  [ -n "$_bad" ] || cp -a "$src/." "$dst/" || _bad="couldn't copy $src → $dst"
  if [ "$strip" = yes ] && [ -z "$_bad" ]; then
    find "$dst/." -mindepth 2 -maxdepth 2 \( -type l -name server -o -type f \( -name server.pid -o -name server.log -o -name .server.lock -o -name csqtt.env -o -name desired.json \) \) -delete 2>/dev/null || true
  fi
  if [ -z "$_bad" ] && [ -f "$srec" ]; then
    mkdir -p "$(dirname "$drec")" && cp -a "$srec" "$drec" || _bad="couldn't copy the csqtt record $srec → $drec"
  fi
  if [ -n "$_bad" ]; then
    warn "csqtt state was NOT carried over: $_bad"
    warn "  the csqtt servers will come up with a FRESH owner password and existing clients will stop connecting."
    warn "  the originals are untouched in $src — copy them to $dst by hand and restart the node to recover."
    return 0
  fi
  echo "    csqtt server state (passwords + config) → $dst"
  return 0; }

# stop_bare_csqtt — bring down every bare-metal csqtt server so it stops holding its port, TUN device and store.
# A convert to docker hands those instances to a supervised child inside the container; leave the host units running
# and the two fight over the same listen port and iface name, with the panel reporting whichever answered last.
# Units only — the config-dir is carried by migrate_csqtt and removed by nothing here.
stop_bare_csqtt(){
  local unit name n=0 sd="${SYSTEMD_DIR:-/etc/systemd/system}"
  for unit in $(ls "$sd"/swg-csqtt-*.service 2>/dev/null || true); do
    name="$(basename "$unit" .service)"
    systemctl disable --now "$name" >/dev/null 2>&1 || true
    ip link delete dev "${name#swg-csqtt-}" >/dev/null 2>&1 || true   # the raw TUN outlives the process
    rm -f "$unit"; n=$((n+1))
  done
  [ "$n" -gt 0 ] && { systemctl daemon-reload >/dev/null 2>&1 || true; echo "    stopped $n bare-metal csqtt server(s) — the container owns them now"; }
  return 0; }

# ── turn-proxy: the curated forks + their owner/repo, and the binary download (GitHub direct, then opt-in mirrors) ──
turn_repo_owner(){ case "$1" in
  WINGS-N) echo "WINGS-N/vk-turn-proxy";; samosvalishe) echo "samosvalishe/free-turn-proxy";;
  kiper292) echo "kiper292/vk-turn-proxy";; anton48) echo "anton48/vk-turn-proxy";;
  Moroka8) echo "Moroka8/vk-turn-proxy";; MYSOREZ) echo "MYSOREZ/vk-turn-proxy";;
  cacggghp) echo "cacggghp/vk-turn-proxy";; *) return 1;; esac; }

# Axis-2 P3: systemd sandbox for turn-proxy units — shared by install-host/node + convert (mirrors swg-noded's
# TURN_UNIT_HARDENING). A forwarder only shuffles bytes between two sockets, so confine it hard: a compromised
# fork binary is contained to its sockets, not root. Injected into the unit's [Service] via $TURN_HARDENING.
# ⚠️ SystemCallFilter=@system-service is the one that could refuse an odd Go syscall — first suspect if a proxy
# won't start after install (check `journalctl -u <svc>` for a seccomp kill).
TURN_HARDENING='NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK
RestrictNamespaces=yes
RestrictSUIDSGID=yes
LockPersonality=yes
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM'
dl_turn_bin(){ local owner="$1" arch="$2" out="$3" base url m; base="https://github.com/$owner/releases/latest/download/server-linux-$arch"
  for url in "$base" $(for m in ${SWG_TURN_MIRROR:-}; do printf '%s ' "${m%/}/$base"; done); do
    curl -fsSL --connect-timeout 20 --max-time 240 --retry 3 --retry-delay 3 --retry-all-errors "$url" -o "$out" && return 0
  done; return 1; }

# ── reverse-proxy config generation (shared by install-host "skip" mode + install-docker TLS=none) ──
# The operator runs their own nginx/Caddy; we bind the panel + swg-sub to loopback and PRINT ready configs
# (installing nothing). gen_proxy_conf writes ONE config to stdout; print_proxy_configs saves both + echoes.
#   gen_proxy_conf nginx|caddy <panel_domain> <panel_target> <panel_base> <sub_domain> <sub_target>
#   <panel_target>/<sub_target> = host:port the proxy forwards to (e.g. 127.0.0.1:8088). <sub_domain> "" → no sub block.
gen_proxy_conf(){
  local kind="$1" pd="$2" pt="$3" pbase="$4" sd="$5" st="$6" loc="/"
  [ -n "$pbase" ] && loc="${pbase}/"
  if [ "$kind" = nginx ]; then
    cat <<EOF
# swg-panel reverse proxy for nginx. Get certificates first, e.g.:
#   certbot --nginx -d ${pd}${sd:+ -d $sd}
server {                                     # redirect HTTP -> HTTPS
    listen 80;
    server_name ${pd}${sd:+ $sd};
    location / { return 301 https://\$host\$request_uri; }
}
server {                                     # admin panel
    listen 443 ssl http2;
    server_name ${pd};
    ssl_certificate     /etc/letsencrypt/live/${pd}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${pd}/privkey.pem;
    client_max_body_size 4m;
    location ${loc} {
        proxy_pass http://${pt};
        proxy_set_header Host \$http_host;   # \$http_host keeps the PORT; \$host strips it, and the address-change confirm compares Host against host:port
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    [ -n "$sd" ] && cat <<EOF
server {                                     # subscription page (public, read-only)
    listen 443 ssl http2;
    server_name ${sd};
    ssl_certificate     /etc/letsencrypt/live/${sd}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${sd}/privkey.pem;
    client_max_body_size 2m;
    location / {
        proxy_pass http://${st};
        proxy_set_header Host \$http_host;   # \$http_host keeps the PORT; \$host strips it, and the address-change confirm compares Host against host:port
        proxy_set_header X-Forwarded-For \$remote_addr;   # swg-sub trusts this only with SWG_SUB_TRUST_XFF=1 (set in reverse-proxy installs)
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  else   # caddy — auto-HTTPS
    cat <<EOF
# swg-panel reverse proxy for Caddy (auto-HTTPS). Point DNS at this host first.
${pd} {
$( [ -n "$pbase" ] && printf '    handle %s/* {\n        reverse_proxy %s\n    }' "$pbase" "$pt" || printf '    reverse_proxy %s' "$pt" )
}
EOF
    [ -n "$sd" ] && cat <<EOF
${sd} {
    reverse_proxy ${st}
}
EOF
  fi
}

# print_proxy_configs <out_dir> <panel_domain> <panel_target> <panel_base> <sub_domain> <sub_target>
print_proxy_configs(){
  local dir="$1" pd="$2" pt="$3" pbase="$4" sd="$5" st="$6"
  mkdir -p "$PREFIX$dir"
  gen_proxy_conf nginx "$pd" "$pt" "$pbase" "$sd" "$st" > "$PREFIX$dir/swg-nginx.conf"
  gen_proxy_conf caddy "$pd" "$pt" "$pbase" "$sd" "$st" > "$PREFIX$dir/swg-Caddyfile"
  chmod 644 "$PREFIX$dir/swg-nginx.conf" "$PREFIX$dir/swg-Caddyfile" 2>/dev/null || true
  echo; ok "Reverse-proxy configs saved to ${dir}/ — nothing was installed or reloaded."
  sub "Panel  → ${pt}${pbase}"
  [ -n "$sd" ] && sub "Sub    → ${st}   (${sd})"
  echo; echo "  $(b "── nginx ──  ${dir}/swg-nginx.conf")"; gen_proxy_conf nginx "$pd" "$pt" "$pbase" "$sd" "$st" | sed 's/^/    /'
  echo; echo "  $(b "── Caddy ──  ${dir}/swg-Caddyfile")"; gen_proxy_conf caddy "$pd" "$pt" "$pbase" "$sd" "$st" | sed 's/^/    /'
  echo
}

# ── docker one-click self-update wiring (STATIC templates — no per-install config) ──────────────────────────────
# The swg-update + swg-update-check wrappers and the poll service/timer. Shared by install-docker.sh's
# wire_host_updater (fresh install) AND update.sh's ensure_update_unit_docker (heal) so both write byte-identical
# pieces. Writes the files, retires the legacy .path watch, stamps NOW (so the first poll can't fire a spurious
# update), reloads systemd, and enables the 30s timer. Caller owns $DRYRUN gating + container trigger pre-creation.
# systemctl calls are best-effort so this never trips set -e. Returns 0.
write_docker_updater(){
  cat > /usr/local/bin/swg-update <<'WRAP'
#!/usr/bin/env bash
# swg-update — root entrypoint for the panel/node one-click update. swg programs + images only (--no-components
# skips docker engine / wg-awg / turn-proxies); on a docker box this is `compose pull && up`. A container can't
# recreate itself, so the panel/node touches its trigger and THIS (host, root) unit does the recreate.
set -euo pipefail
URL="${SWG_BOOTSTRAP_URL:-https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh}"
curl -fsSL "$URL" | bash -s update -y --no-components
WRAP
  chmod 755 /usr/local/bin/swg-update
  # The trigger files are written by the panel/node CONTAINER through a bind mount, and inotify does NOT cross that
  # bind mount — a host `.path` unit (PathModified) NEVER sees the container's write. So we POLL the trigger mtimes
  # from the host instead (stat across the bind mount works — it's a shared inode). A timer runs this every 30s.
  cat > /usr/local/bin/swg-update-check <<'WRAP2'
#!/usr/bin/env bash
set -euo pipefail
STAMP=/var/lib/swg-update.stamp
_run=no
for _t in /var/lib/swg-panel/.update-request /var/lib/swg-noded/.update-request /opt/swg-panel-docker/data/lib/.update-request /opt/swg-panel-docker/data/node/.update-request; do
  [ -f "$_t" ] || continue
  { [ ! -e "$STAMP" ] || [ "$_t" -nt "$STAMP" ]; } && _run=yes
done
[ "$_run" = yes ] || exit 0
touch "$STAMP"            # mark this batch handled BEFORE updating, so we never loop
exec /usr/local/bin/swg-update
WRAP2
  chmod 755 /usr/local/bin/swg-update-check
  cat > /etc/systemd/system/swg-update.service <<EOF
[Unit]
Description=swg-panel one-click self-update (swg programs only)

[Service]
Type=oneshot
ExecStart=/usr/local/bin/swg-update-check
EOF
  cat > /etc/systemd/system/swg-update.timer <<EOF
[Unit]
Description=poll for a swg-panel one-click update request (docker)

[Timer]
OnActiveSec=30s
OnUnitActiveSec=30s

[Install]
WantedBy=timers.target
EOF
  systemctl disable --now swg-update.path >/dev/null 2>&1 || true   # retire the old inotify watch from a pre-poll install
  rm -f /etc/systemd/system/swg-update.path
  touch /var/lib/swg-update.stamp   # stamp NOW (newer than any just-created triggers) so the first poll doesn't fire a spurious update
  systemctl daemon-reload 2>/dev/null || true
  systemctl enable --now swg-update.timer >/dev/null 2>&1 || true
  return 0
}

# ── docker: pre-create the secret files swg-sub masks with /dev/null (docker-compose.yml) ───────────────────────
# swg-sub bind-mounts /dev/null over the panel's auth/panel-settings/vault/escrow so the public surface can never
# read them. Docker needs the mount TARGET to already exist, and swg-sub mounts /etc/swg-panel + /var/lib/swg-panel
# READ-ONLY — so on a FRESH install (files not yet written by the panel) docker can't create the mountpoint and
# swg-sub dies with "read-only file system". Pre-create empty placeholders before `compose up`: the panel's load_json
# treats an empty file as its default, and the entrypoint overwrites auth from PANEL_PASSWORD. Idempotent — an
# existing install already has these files, so this is a no-op (backwards compatible). $1 = install dir.
ensure_docker_mask_files(){
  local d="${1:-}" f; [ -n "$d" ] || return 0
  mkdir -p "$d/data/etc" "$d/data/lib/subs" 2>/dev/null || true
  for f in data/etc/auth data/lib/panel-settings.json data/lib/subs/vault.json data/lib/subs/escrow.json; do
    [ -e "$d/$f" ] || : > "$d/$f" 2>/dev/null || true
  done
  return 0
}

ensure_swap(){ # PANEL-HOST: a low-RAM box with NO active swap OOM-kills the panel on a transient list-resolve spike (a
  # big domain feed peaks a few hundred MB). Add a right-sized swapfile so spikes go to disk, not the OOM-killer.
  # Idempotent, best-effort (never aborts — set-e safe via if-guards), dry-run aware. Self-contained (plain echo +
  # the $DRYRUN global) so install-host and update can both call it. Nodes pull lists (never resolve) → they don't.
  local active memmb freemb sizemb
  active=$(awk 'NR>1{s+=$3} END{print s+0}' /proc/swaps 2>/dev/null || echo 0)
  if [ "${active:-0}" -gt 0 ] 2>/dev/null; then echo "  ✓ swap already active — skipping"; return 0; fi
  memmb=$(( $(awk '/^MemTotal:/{print $2}' /proc/meminfo 2>/dev/null || echo 0) / 1024 ))
  if [ "$memmb" -ge 2048 ]; then echo "  · RAM ${memmb}MB — swap not needed"; return 0; fi
  if [ -e /swapfile ]; then echo "  ! /swapfile exists but no active swap — leaving it alone"; return 0; fi
  freemb=$(( $(df -Pk / 2>/dev/null | awk 'NR==2{print $4}' || echo 0) / 1024 ))
  if   [ "$freemb" -gt 4096 ]; then sizemb=2048
  elif [ "$freemb" -gt 2560 ]; then sizemb=1024
  else echo "  ! only ${freemb}MB free on / — not adding swap (this ${memmb}MB box stays OOM-prone; add swap manually)"; return 0; fi
  if [ "${DRYRUN:-false}" = true ]; then echo "    [skip] create ${sizemb}MB /swapfile + swapon + fstab + vm.swappiness=10"; return 0; fi
  echo "  ✓ adding ${sizemb}MB swap (${memmb}MB RAM, none active) — bounds panel list-resolve spikes"
  if { fallocate -l "${sizemb}M" /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count="$sizemb" status=none; } \
       && chmod 600 /swapfile && mkswap /swapfile >/dev/null 2>&1 && swapon /swapfile 2>/dev/null; then
    grep -qs '/swapfile' /etc/fstab || printf '%s\n' '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl -qw vm.swappiness=10 >/dev/null 2>&1 || true
    grep -qs 'vm.swappiness' /etc/sysctl.conf || printf '%s\n' 'vm.swappiness=10' >> /etc/sysctl.conf
    echo "  ✓ swap active ($(free -m 2>/dev/null | awk '/Swap/{print $2}')MB, swappiness 10)"
  else
    echo "  ! swap setup failed — continuing (box remains OOM-prone until swap is added)"; rm -f /swapfile 2>/dev/null || true
  fi
  return 0
}

# seed_access_settings <panel-settings.json path> — merge this run's Access & TLS answers into the panel's own
# settings file. panel-settings.json lives in the STATE dir, which an uninstall KEEPS by default, so a fresh
# install onto a kept state dir would otherwise show the PREVIOUS install's address/TLS in Settings → Access (or
# blanks on a first install), contradicting what is actually running. The panel is the source of truth once the
# operator edits it there (it writes install.conf / .env back via swg-netctl); this just makes the two agree from
# the start. MERGE, never rewrite. Caller exports PANEL_DOMAIN / PANEL_BASE / PORT / TLS_MODE / ACME_EMAIL /
# CF_TOKEN / CF_ORIGIN_TOKEN. Was copy-pasted into install-host.sh and install-docker.sh, identical but for the path.
seed_access_settings(){
  have python3 || { warn "couldn't seed Access settings (no python3) — set them in Settings → Access & TLS"; return 0; }
  mkdir -p "$(dirname "$1")" 2>/dev/null || true
  python3 - "$1" <<'PYACC' || warn "couldn't seed Access settings — set them in Settings → Access & TLS"
import json, os, sys
p = sys.argv[1]
try:
    with open(p) as f: d = json.load(f)
except Exception:
    d = {}
if not isinstance(d, dict): d = {}
dom  = (os.environ.get("PANEL_DOMAIN") or "").strip()
base = (os.environ.get("PANEL_BASE") or "").strip().rstrip("/")
port = (os.environ.get("PORT") or "").strip()
acc  = d.setdefault("access", {})
pan  = acc.setdefault("panel", {}); tls = acc.setdefault("tls", {})
if dom:
    host = dom if "://" in dom else "https://" + dom            # the operator may have typed a scheme
    if port and port not in ("443", "80") and ":" not in host.split("://", 1)[1]:
        host += ":" + port
    pan["url"] = host + (base or "")
if port.isdigit(): pan["port"] = int(port)
pan["base"] = (base or "/")
tls["mode"]  = (os.environ.get("TLS_MODE") or tls.get("mode") or "").strip()
tls["email"] = (os.environ.get("ACME_EMAIL") or tls.get("email") or "").strip()
for k, e in (("cf_token", "CF_TOKEN"), ("cf_origin_token", "CF_ORIGIN_TOKEN")):
    v = (os.environ.get(e) or "").strip()
    if v: tls[k] = v                                            # keep an existing token when this run didn't supply one
tmp = p + ".tmp"
with open(tmp, "w") as f: json.dump(d, f, indent=2)
os.replace(tmp, p)
PYACC
  return 0; }

# migrate_node_state <to-docker|to-baremetal> [docker_dir] — carry the node's HOST-LOCAL derived state between the
# two path conventions during a convert: the per-interface keypair backups (the server-key revert baseline) and the
# routing lists pulled from the panel (geo/<cat>.doms + the geoip sets).
#
# The lists are why this exists. The panel ships almost no inline domains — the real per-category list is PULLED into
# the node's geo dir and read back from there. Kernel-SNI builds its xt_string chain ONLY from categories that have
# a non-empty domain list, so a converted node started with an empty geo dir, found nothing to hook, tore the SWGK
# chain down, and reported "SNI scanner down — host routing degraded" until the background pull happened to land —
# indefinitely if the panel's manifest didn't re-offer the category. Carrying the files makes the converted node
# come up already routing, exactly as it was before the move.
migrate_node_state(){
  local dir="$1" dd="${2:-/opt/swg-panel-docker}" src dst d
  case "$dir" in
    to-docker)    src=/var/lib/swg-noded;      dst="$dd/data/node";;
    to-baremetal) src="$dd/data/node";         dst=/var/lib/swg-noded;;
    *) return 0;;
  esac
  for d in iface-keys geo; do
    [ -d "$src/$d" ] || continue
    mkdir -p "$dst/$d" && cp -a "$src/$d/." "$dst/$d/" \
      || { warn "couldn't carry the node's $d over — $([ "$d" = geo ] && echo "host routing re-fills itself from the panel within a minute" || echo "server-key revert loses its baseline")"; continue; }
    case "$d" in
      iface-keys) sub "carried interface keypair backups → $dst/iface-keys";;
      geo)        sub "carried the pulled routing lists → $dst/geo";;
    esac
  done
  return 0; }

# wdtt_local [record…] — one TAB-separated row per WDTT instance this node manages: iface, listen, wg_addr.
# Reads the FIRST record path that exists (docker installs pass their own before the bare-metal default).
# Was three near-copies across install-host / install-node / install-docker, differing only in that lookup.
wdtt_local(){
  local r="" p
  for p in "$@" /etc/swg-agent/wdtt.json; do [ -f "$p" ] && { r="$p"; break; }; done
  [ -n "$r" ] || return 0
  python3 - "$r" <<'PYWL' 2>/dev/null || true
import json, sys
try: d = json.load(open(sys.argv[1]))
except Exception: raise SystemExit
for i in (d.get("wdtt") or []):
    if isinstance(i, dict) and i.get("iface"):
        print("%s\t%s\t%s" % (i["iface"], i.get("listen") or ("127.0.0.1:%s" % (i.get("wg_port") or "?")), i.get("wg_addr") or "?"))
PYWL
}
wdtt_row(){ printf '    %s%-10s%s  %s%-10s%s  %s  %s\n' "${C_GREEN:-}" "$1" "${RESET:-}" "${BOLD:-}" "WDTT" "${RESET:-}" "${2:-?}" "${3:-?}"; }

# ── nginx after a convert ────────────────────────────────────────────────────────────────────────
# A convert MOVES the panel's cert dir (/etc/swg-panel → /etc/swg-panel.converted-<ts>, or the other
# way into <docker>/data/etc) and CHANGES the upstream ports. A reverse-proxied install therefore comes
# out the far side with a vhost pointing at a path that no longer exists and a port nothing listens on.
# nginx keeps serving its stale in-memory config, so nothing looks wrong until someone reloads — at which
# point `nginx -t` fails and the site is down. Observed live: subscriptions 502'd after a bare→docker
# convert because the vhost still proxied to the bare :8888 while the container published :8444.
#
# Ownership rule: we only REWRITE the vhost swg itself wrote (sites-available/swg-panel.conf). Everything
# else on the box is the operator's, so for those we DETECT and report the exact old→new values and let
# them make the edit. Silently rewriting a config we didn't author is how you lose someone's tuning.
#
#   nginx_convert_fixup <new_tls_dir> <new_panel_upstream> [<new_sub_upstream>]
#     new_tls_dir       dir now holding fullchain.pem/key.pem, e.g. /opt/swg-panel-docker/data/etc/tls
#     new_panel_upstream  e.g. http://127.0.0.1:8088
#     new_sub_upstream    e.g. https://127.0.0.1:8444   (optional; blank = don't mention the sub)
NGINX_DIR="${NGINX_DIR:-/etc/nginx}"   # overridable so this is testable and dry-runnable against a fake tree
_ngx_enabled_files(){        # list every config file nginx will read (can't use `nginx -T`: it fails when broken)
  local d; for d in "$NGINX_DIR/sites-enabled" "$NGINX_DIR/conf.d"; do
    [ -d "$d" ] || continue
    find "$d" -maxdepth 1 -type f -o -maxdepth 1 -type l 2>/dev/null
  done | sort -u; }
_ngx_port_dead(){ have ss || return 1; [ -z "$(ss -lntH "sport = :$1" 2>/dev/null)" ]; }
# ngx_upstream <port> — "https://127.0.0.1:<port>" or "http://…", decided by ASKING the listener rather than
# assuming. Whether swg-sub terminates its own TLS depends on subscriptions.serve.tls_mode, and the panel's
# loopback listener is plain HTTP while its public one is not — guessing here writes a vhost that 502s.
ngx_upstream(){
  local p="$1"
  curl -sk -o /dev/null --max-time 3 "https://127.0.0.1:$p/" 2>/dev/null && { printf 'https://127.0.0.1:%s' "$p"; return 0; }
  printf 'http://127.0.0.1:%s' "$p"; }
nginx_convert_fixup(){
  local tlsdir="$1" up_panel="$2" up_sub="${3:-}"
  have nginx || return 0
  _ngx_enabled_files | grep -q . || return 0
  local swgvh="" f
  for f in "$NGINX_DIR/sites-enabled/swg-panel.conf" "$NGINX_DIR/conf.d/swg-panel.conf"; do [ -e "$f" ] && swgvh="$f" && break; done
  [ -n "$swgvh" ] && [ -L "$swgvh" ] && swgvh="$(readlink -f "$swgvh" 2>/dev/null || echo "$swgvh")"

  # 1) repair OUR vhost in place — only the two things a convert invalidates, so operator edits survive
  local swgbak=""
  if [ -n "$swgvh" ] && [ -f "$swgvh" ] && [ -f "$tlsdir/fullchain.pem" ]; then
    # NOT beside the vhost: nginx `include sites-enabled/*` would load the backup as a duplicate server
    # block, and it would also show up in the operator-config scan below as a file we don't own.
    swgbak="$(mktemp 2>/dev/null || echo "/tmp/swg-vhost.$$")"; cp -a "$swgvh" "$swgbak" 2>/dev/null || true
    local live_ports; live_ports="$(ss -lntH 2>/dev/null | grep -oE ':[0-9]+ ' | tr -d ': ' | sort -u | tr '\n' ',')"
    python3 - "$swgvh" "$tlsdir" "$up_panel" "$live_ports" <<'PYNGX' 2>/dev/null && sub "repointed the panel vhost ($swgvh) at $tlsdir and $up_panel"
import os, re, sys
p, tls, up = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3]
live = {x for x in (sys.argv[4] if len(sys.argv) > 4 else "").split(",") if x}
s = open(p).read()
# only rewrite a cert path that is actually GONE — never touch one the operator repointed themselves
def cert(m):
    key, path = m.group(1), m.group(2)
    return m.group(0) if os.path.exists(path) else "%s %s/%s;" % (key, tls, os.path.basename(path))
s = re.sub(r"(ssl_certificate|ssl_certificate_key)\s+(\S+);", cert, s)
# We wrote this file, and what we write is the PANEL vhost only — one upstream. If it now names more than one
# distinct loopback port, it has been extended beyond what we generate (a sub vhost bolted into the same file,
# say), and "point every upstream at the panel" would silently redirect the other one. Leave ports alone then;
# the reporting pass below still tells the operator exactly what moved. Also never touch a port that is LIVE:
# a listening upstream is by definition not what this convert broke.
ports = set(re.findall(r"proxy_pass\s+https?://127\.0\.0\.1:(\d+);", s))
if len(ports) <= 1:
    s = re.sub(r"proxy_pass\s+https?://127\.0\.0\.1:(\d+);",
               lambda m: m.group(0) if m.group(1) in live else "proxy_pass %s;" % up, s)
open(p, "w").write(s)
PYNGX
  fi

  # 2) report what we must NOT touch: dangling certs / dead upstreams in the operator's own vhosts
  local bad=0 pf
  while IFS= read -r pf; do
    [ -f "$pf" ] || continue
    [ "$pf" = "$swgvh" ] && continue
    local c
    while IFS= read -r c; do
      [ -n "$c" ] && [ ! -e "$c" ] && { [ "$bad" = 0 ] && warn "nginx configs you maintain still point at things this convert moved:"; bad=1
        warn "  $(basename "$pf"): certificate $c is gone → use $tlsdir/$(basename "$c")"; }
    done <<EOC
$(grep -hoE '^[[:space:]]*ssl_certificate(_key)?[[:space:]]+[^;]+;' "$pf" 2>/dev/null | sed -E 's/^[[:space:]]*ssl_certificate(_key)?[[:space:]]+//; s/;$//')
EOC
    local prt
    while IFS= read -r prt; do
      [ -n "$prt" ] && _ngx_port_dead "$prt" && { [ "$bad" = 0 ] && warn "nginx configs you maintain still point at things this convert moved:"; bad=1
        warn "  $(basename "$pf"): nothing listens on 127.0.0.1:$prt → panel is now $up_panel${up_sub:+, subscriptions $up_sub}"; }
    done <<EOP
$(grep -hoE 'proxy_pass[[:space:]]+https?://127\.0\.0\.1:[0-9]+' "$pf" 2>/dev/null | grep -oE '[0-9]+$' | sort -u)
EOP
  done <<EOF
$(_ngx_enabled_files)
EOF

  # 3) validate + reload. A convert must never leave nginx un-reloadable: if our own edit is what broke
  #    it, put the original back so the operator is no worse off than before.
  if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx >/dev/null 2>&1 || true
    [ "$bad" = 0 ] && sub "nginx config validates and was reloaded"
  else
    [ -n "$swgbak" ] && [ -f "$swgbak" ] && { cp -a "$swgbak" "$swgvh"; warn "our vhost edit didn't validate — restored the original"; }
    warn "nginx -t FAILS, so nginx cannot reload (it is still serving its old in-memory config until something restarts it):"
    nginx -t 2>&1 | sed 's/^/    /' | head -4
  fi
  [ -n "$swgbak" ] && rm -f "$swgbak" 2>/dev/null || true
  return 0; }

# ── Cloudflare credential validation ─────────────────────────────────────────────────────────────
# Both prompts (DNS-01 for `cloudflare`, Origin CA for `cf15`) want a SCOPED API TOKEN: 40 characters of
# [A-Za-z0-9_-]. That is the only form the code wires — acme.sh gets CF_Token, mk_cf_origin sends a Bearer
# header; nothing ever sets CF_Key/CF_Email, so a Global API Key would fail later at issue time. Reject it
# HERE, where the message can say why, instead of after the install has moved on.
#
# The old checks were "non-empty" (docker) and "at least 10 chars" (host), so an email address sailed through
# both and the install proceeded to a certificate that could never issue.
# Deliberately SHAPE-only, not a length equality. The classic scoped token is 40 chars, but Cloudflare also
# issues prefixed ones (cfut_… , ~52 chars), and pinning to 40 would reject a perfectly good credential — a
# worse failure than the one this is fixing, because the operator would have no way past it but --force.
# So: reject what CANNOT be a token (an email, whitespace, quotes, anything far too short) and let the rest
# through to fail loudly at issue time if the scope is wrong.
v_cftoken(){
  case "$1" in *[!A-Za-z0-9_-]*) return 1;; esac      # '@' and '.' land here → an email can never pass
  # 37 lowercase hex is the Global API Key. It is a real Cloudflare credential, which is exactly why it needs
  # rejecting HERE: acme.sh would want CF_Key + CF_Email for it and we only ever set CF_Token, so it would fail
  # at issue time with a generic auth error instead of "you pasted the wrong one of your two credentials".
  case "${#1}" in 37) case "$1" in *[!0-9a-f]*) ;; *) return 1;; esac;; esac
  [ "${#1}" -ge 30 ]
}
v_cforigin(){ v_cftoken "$1"; }                        # same credential type, different scope
# Why a value was rejected — ask_valid shows this instead of a generic hint, so the operator is told what they
# actually pasted rather than being re-prompted with the same sentence.
v_cftoken_why(){
  case "$1" in
    "")        echo "the API token can't be empty";                                                       return;;
    *@*.*)     echo "that looks like an EMAIL address, not an API token";                                 return;;
  esac
  case "${#1}" in
    37) case "$1" in *[!0-9a-f]*) ;; *) echo "that looks like your Global API Key — this needs a scoped API Token (My Profile → API Tokens → Create Token)"; return;; esac;;
  esac
  case "$1" in *[!A-Za-z0-9_-]*) echo "an API token is only letters, digits, '_' and '-' — that value has other characters"; return;; esac
  echo "that is only ${#1} characters — a Cloudflare API token is 40 or more"
}
v_cforigin_why(){ v_cftoken_why "$1"; }

# ── host addresses for a DOCKER panel ────────────────────────────────────────────────────────────
# host_bindable_ips — the HOST's bindable, public-servable addresses as "ip|iface" (comma-separated).
# The panel's own _bindable_ips() cannot produce these in docker: the container is BRIDGED, so it sees
# only the compose network's 172.x — and `ip` isn't even in the panel image. The installer runs on the
# host, so it captures them here and passes them in via .env (SWG_HOST_IPS). Without it the Access & TLS
# ── the SPA module tree ─────────────────────────────────────────────────────────────────────────────
# Verify a DEPLOYED js/ against the SOURCE it was copied from.
#   verify_js_tree <src-dir> <dest-dir>     -> prints nothing and returns 0 when the copy is complete
#
# The SPA is 22 ES modules plus a locale catalog. If a copy drops or truncates one, nothing anywhere says
# so: the panel serves the rest happily and the operator gets a blank page whose only clue is a 404 in a
# console they will never open. So check the copy — right here, while the operator is still watching.
#
# Compares the two DIRECTORIES rather than a manifest of stored hashes. A manifest has to be regenerated
# every time any module changes, and a stale one cries wolf: it once reported six modules "corrupt" that
# had merely been edited, which is exactly how a check trains people to ignore it. The source tree is the
# authority we already have on disk, it is never out of date with itself, and comparing to it catches a
# TRUNCATED file as well as a missing one.
#
# Never fatal on its own: the caller decides, because a half-copied SPA is worth shouting about but not
# worth aborting an update that has already replaced the server binary.
verify_js_tree(){
  local src="$1" dst="$2"
  [ -d "$src" ] && [ -d "$dst" ] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  python3 - "$src" "$dst" <<'PYJS'
import filecmp, os, sys
src, dst = sys.argv[1], sys.argv[2]
bad = []
for root, _dirs, files in os.walk(src):
    for fn in sorted(files):
        if not fn.endswith(".js"):
            continue
        rel = os.path.relpath(os.path.join(root, fn), src)
        a, b = os.path.join(src, rel), os.path.join(dst, rel)
        if not os.path.exists(b):
            bad.append("missing " + rel)
        elif not filecmp.cmp(a, b, shallow=False):   # shallow=False: compare CONTENT, not size+mtime
            bad.append("differs " + rel)
for b in bad:
    print(b)
sys.exit(1 if bad else 0)
PYJS
}

# "Listen IP" picker offers nothing but 0.0.0.0 / 127.0.0.1 on every docker install.
# The interface filter MIRRORS swg-panel-server's _IFACE_SKIP_RE — keep the two in step.
# Excludes by DEVICE TYPE as well as name: the name filter only catches wgN/awgN, so any tunnel the operator
# named otherwise (an adopted `foreign0`, a WDTT server's `wdtt0`) was offered as a bindable public address —
# binding the panel to a VPN tunnel's own IP is never right. Type is read once from `ip -d link`, where the kind
# (wireguard / amneziawg / tun) is the first token of a detail line. Bridges/veth stay NAME-filtered on purpose:
# a host `br0` carrying real traffic is perfectly bindable, while docker's br-*/veth* are not.
host_bindable_ips(){
  command -v ip >/dev/null 2>&1 || return 0
  local tun; tun="$(ip -d link show 2>/dev/null | awk '
      /^[0-9]+: / { name=$2; sub(/:$/,"",name); sub(/@.*/,"",name); next }
      { if (name != "" && ($1=="wireguard" || $1=="amneziawg" || $1=="tun" || $1=="tap")) { print name; name="" } }')"
  ip -o addr show scope global 2>/dev/null | awk -v skip="$tun" '
    BEGIN { n=split(skip, s, "\n"); for (i=1; i<=n; i++) if (s[i] != "") X[s[i]]=1 }
    ($3=="inet" || $3=="inet6") && !($2 in X) &&
    $2 !~ /^(wg[0-9]|awg[0-9]|swg_|docker|br-|veth|virbr|tun[0-9]|tap[0-9]|cni|flannel|kube|cali|nerdctl)/ {
      split($4, a, "/"); printf "%s%s|%s", (m++ ? "," : ""), a[1], $2 }'
}

# ─────────────────────── AmneziaWG: get the BEST datapath this box can run ───────────────────────
# The amnezia PPA is a LAUNCHPAD ppa — Ubuntu only. On Debian (very common on VPS), on any non-apt
# distro, and on a kernel with no matching headers, `add-apt-repository ppa:amnezia/ppa` cannot work,
# and until now that left the node with NO AmneziaWG at all: the installer only warned, then reported a
# successful install. These two rungs close that. Order matters — the kernel module is materially
# faster, so it is always tried first and userspace is only a fallback.

awg_build_from_source(){ # build awg tools (+ the DKMS kernel module) from upstream. 0 = tools AND module.
  # Tools first and unconditionally: `awg` + `awg-quick` are what the panel needs to write and bring up a
  # conf, and they build anywhere with a compiler — no distro repo involved. WITH_WGQUICK=yes is what
  # produces awg-quick; without it you get the confusing half-installed state (`awg` present, awg-quick
  # missing) that reads from the panel as "not installed at all". Same recipe as Dockerfile.node.
  local w; w="$(mktemp -d)"
  if ! have awg || ! have awg-quick; then
    info "building AmneziaWG tools from source (the amnezia PPA is Ubuntu-only)…"
    # ca-certificates is NOT optional here: without it every https git clone below fails cert verification.
    # Dockerfile.node never hit this because its golang base image ships them; a minimal Debian does not.
    have apt-get && run apt-get install -y --no-install-recommends git make build-essential ca-certificates >/dev/null 2>&1
    if ! have git || ! have make; then
      warn "cannot build AmneziaWG tools — git/make/compiler missing and no apt-get to add them"
      rm -rf "$w"; return 1
    fi
    { run git clone --depth=1 https://github.com/amnezia-vpn/amneziawg-tools "$w/tools" \
        && run make -C "$w/tools/src" \
        && run make -C "$w/tools/src" install PREFIX=/usr WITH_BASHCOMPLETION=no WITH_SYSTEMDUNITS=no \
                WITH_WGQUICK=yes; } >"$w/build.log" 2>&1 || true
  fi
  $DRYRUN && { rm -rf "$w"; return 0; }
  have awg && have awg-quick || {
    warn "AmneziaWG tools did not build: $(tail -n 2 "$w/build.log" 2>/dev/null | tr '\n' ' ' | cut -c1-200)"
    rm -rf "$w"; return 1; }
  # Kernel module. Wanted wherever it is possible: it is the fast datapath, and on Debian this source
  # build is the ONLY way to it. Needs headers for the RUNNING kernel — a provider kernel often has none,
  # and an LXC/OpenVZ guest cannot load a module at all, which is what the userspace rung is for.
  # No modprobe at all (a stripped image, some containers) means no kernel module is possible here — say so
  # by falling through to userspace rather than returning modprobe's 127 to the caller.
  have modprobe || { rm -rf "$w"; return 1; }
  if modprobe amneziawg 2>/dev/null; then rm -rf "$w"; return 0; fi
  info "building the AmneziaWG kernel module for $(uname -r)…"
  have apt-get && run apt-get install -y --no-install-recommends dkms "linux-headers-$(uname -r)" >/dev/null 2>&1
  { run git clone --depth=1 https://github.com/amnezia-vpn/amneziawg-linux-kernel-module "$w/mod" \
      && run make -C "$w/mod/src" \
      && run make -C "$w/mod/src" install; } >"$w/mod.log" 2>&1 || true
  run depmod -a >/dev/null 2>&1 || true
  rm -rf "$w"
  modprobe amneziawg 2>/dev/null || return 1
}

ensure_awg_userspace(){ # last rung: the userspace datapath, so AWG works even with no loadable module. 0/1
  # awg-quick falls back to this ON ITS OWN — its add_if() exits unless the module is missing AND
  # `amneziawg-go` is on PATH, so simply having the binary is the whole wiring. No env var, no config.
  # Slower than the kernel module (which is why it is last), but it is the same datapath our Docker nodes
  # have always run, and it works on boxes where nothing else can: no matching headers, LXC/OpenVZ guests.
  have amneziawg-go && return 0
  $DRYRUN && return 0
  have go || { have apt-get && run apt-get install -y --no-install-recommends golang-go git ca-certificates >/dev/null 2>&1; }
  have go || { warn "no Go toolchain — install amneziawg-go by hand for a userspace AmneziaWG datapath"; return 1; }
  info "building the userspace AmneziaWG datapath (amneziawg-go)…"
  local w; w="$(mktemp -d)"
  { run git clone --depth=1 https://github.com/amnezia-vpn/amneziawg-go "$w/go" \
      && ( cd "$w/go" && run go build -o /usr/local/bin/amneziawg-go . ); } >"$w/go.log" 2>&1 || true
  # Debian STABLE ships a Go far older than amneziawg-go asks for (bookworm: 1.19 vs a go.mod wanting 1.25),
  # and 1.19 predates Go fetching its own toolchain, so it cannot bootstrap out of it either. backports is
  # Debian's own answer to exactly this and carries a current Go — reach for it once before giving up.
  if ! have amneziawg-go && have apt-get && [ -r /etc/os-release ]; then
    local _cn; _cn="$(sed -n 's/^VERSION_CODENAME=//p' /etc/os-release | tr -d '"')"
    if [ -n "$_cn" ] && [ ! -f /etc/apt/sources.list.d/swg-backports.list ]; then
      info "this distro's Go is too old for amneziawg-go — trying ${_cn}-backports…"
      echo "deb http://deb.debian.org/debian ${_cn}-backports main" > /etc/apt/sources.list.d/swg-backports.list
      run apt-get update -qq >/dev/null 2>&1 || true
      run apt-get install -y -t "${_cn}-backports" --no-install-recommends golang-go >/dev/null 2>&1 || true
      { ( cd "$w/go" && run go build -o /usr/local/bin/amneziawg-go . ); } >>"$w/go.log" 2>&1 || true
      have amneziawg-go || rm -f /etc/apt/sources.list.d/swg-backports.list   # leave no source behind if it did not help
    fi
  fi
  if ! have amneziawg-go; then
    # The usual reason is a distro Go older than amneziawg-go's go.mod (Debian 12 ships 1.19 against a
    # go.mod asking 1.25), and Go only learned to fetch its own toolchain in 1.21 — so the old one cannot
    # bootstrap out of it either. Say exactly that: "no userspace datapath" with no reason is unactionable.
    warn "amneziawg-go did not build (this node's Go is $(go version 2>/dev/null | awk '{print $3}' || echo unknown)): $(
      tail -n 2 "$w/go.log" 2>/dev/null | tr '\n' ' ' | cut -c1-160)"
    rm -rf "$w"; return 1
  fi
  rm -rf "$w"
  return 0
}
