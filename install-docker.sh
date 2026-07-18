#!/usr/bin/env bash
# install-docker.sh — one-line Docker installer for swg-panel.
#
#   Panel (host):      … | sudo bash -s docker host   -pass SECRET -domain panel.example.net
#   Node only:         … | sudo bash -s docker node   -key KEY -host https://panel.example.net -endpoint 203.0.113.7
#
# `docker host` is the panel entry point: Step 1 asks the role — master or host — exactly
# like bare-metal (install-host.sh):
#   master  panel + this box also runs WG/AWG (a co-located node container), auto-enrolled
#           in ONE pass — no "add the node in the panel first". (compose profile: master)
#   host    panel only; WG/AWG nodes are deployed separately with `docker node` (the panel's
#           Nodes → Add node screen prints the command). (compose profile: host)
# `docker node` is the entry point for a separate node box. Pass -role master|host to skip
# the Step 1 prompt; the bare word `master` also forces the master role.
#
# Ensures Docker is present, stages the project under /opt/swg-panel-docker, writes a
# .env, and brings up the chosen compose profile. Run as root. --dry-run renders the
# .env under ./dryrun and runs no Docker commands.
#
#   -role master|host               role for the `host` entry (skips the Step 1 prompt)
#   --profile host|node|master      pick the compose profile directly (host-node = master alias)
#   -pass <pw>      panel admin password     (-> PANEL_PASSWORD)
#   -domain <host>  panel domain/IP for cert (-> PANEL_DOMAIN)
#   -port <n>       host port for the panel  (-> PANEL_PORT, default 8443)
#   -key <tok>      node enrollment key      (-> NODE_TOKEN)
#   -host <url>     panel URL the node dials (-> PANEL_URL)
#   -endpoint <ip>  public IP clients dial   (-> NODE_ENDPOINT)
#   -iface <name>   node interface name      (-> NODE_IFACE, default awg0)
set -euo pipefail

# ───────────────────────── config (env or flags) ─────────────────────────
PROFILE="${PROFILE:-host}"
ROLE="${ROLE:-}"                        # master | host — asked in Step 1 when the entry is `host`.
                                        # master ⇒ master compose profile (panel + a co-located,
                                        # auto-enrolled node container); mirrors bare-metal master.
BUILD="${BUILD:-false}"                 # true = build images from source (stages full context); default pulls from GHCR
INSTALL_DIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"
# Panel
PANEL_PASSWORD="${PANEL_PASSWORD:-}"
PANEL_USER="${PANEL_USER:-admin}"
PANEL_DOMAIN="${PANEL_DOMAIN:-}"        # host/IP only; a full URL (host[:port][/subpath]) is parsed in Step 1
PANEL_BASE="${PANEL_BASE:-}"            # optional subpath mount, e.g. /swg (also derivable from the URL)
PANEL_HOST_NOPORT=""; URL_PORT=""       # filled by parse_panel_url
TLS="${TLS:-}"                         # letsencrypt|cloudflare|cf15|selfsigned|none (blank = ask)
ACME_EMAIL="${ACME_EMAIL:-}"           # account email for letsencrypt/cloudflare
CF_TOKEN="${CF_TOKEN:-}"               # cloudflare DNS-01: API token with Zone:DNS:Edit + Zone:Read
CF_ORIGIN_TOKEN="${CF_ORIGIN_TOKEN:-${CF_ORIGIN_KEY:-}}"  # cf15: API token with Zone:SSL and Certificates:Edit
PANEL_PORT="${PANEL_PORT:-}"           # host-published port; blank = derive from URL, else 443 (Step 1)
PANEL_LOCAL_PORT="${PANEL_LOCAL_PORT:-8088}"   # dedicated STABLE plain-HTTP loopback port a co-located node dials (a public flip never moves it)
SUB_PORT="${SUB_PORT:-8444}"           # swg-sub host port (bound to loopback in reverse-proxy/TLS=none mode)
SUB_DOMAIN="${SUB_DOMAIN:-}"           # subscription page hostname, for the printed reverse-proxy config (TLS=none)
PANEL_BIND="${PANEL_BIND:-0.0.0.0}"    # host bind for the panel publish; 127.0.0.1 in reverse-proxy mode
SUB_BIND="${SUB_BIND:-0.0.0.0}"        # host bind for the swg-sub publish; 127.0.0.1 in reverse-proxy mode
SUB_TRUST_XFF="${SUB_TRUST_XFF:-0}"    # swg-sub trusts X-Forwarded-For (set to 1 behind a reverse proxy)
# Node
PANEL_URL="${PANEL_URL:-}"
NODE_TOKEN="${NODE_TOKEN:-}"
NODE_NAME="${NODE_NAME:-}"             # local node's name in the panel (master); blank = this host's hostname
PUSH_NAME=""                           # node-profile re-install: a changed box name to push via /api/node/rename
NODE_COLOR="${NODE_COLOR:-#34d399}"   # local node's swatch in the panel (master); bare-metal's first palette colour
NODE_ENDPOINT="${NODE_ENDPOINT:-${ENDPOINT_IP:-}}"
NODE_IFACE="${NODE_IFACE:-}"           # bootstrap interface name; blank = no bootstrap interface (manage from the panel)
NODE_IFACES="${NODE_IFACES:-}"         # several interfaces: "name:port:addr[:proto],…"
NODE_LISTEN_PORT="${NODE_LISTEN_PORT:-51820}"
NODE_ADDRESS="${NODE_ADDRESS:-10.8.0.1/24}"
NODE_MTU="${NODE_MTU:-1280}"           # interface MTU; 1280 leaves headroom for turn-proxy obfuscation
NODE_PLAIN_WG="${NODE_PLAIN_WG:-}"     # yes = plain WireGuard; blank/no = AmneziaWG v2 (Step 2 sets it)
NODE_NET="${NODE_NET:-}"               # host (default) | bridge — docker networking for the node (-net)
TURN_MANAGE="${TURN_MANAGE:-}"         # panel (default) | manual — manage turn-proxies from the panel (mounts docker.sock) (-turn-manage)
TLS_VERIFY="${TLS_VERIFY:-}"           # yes/no; blank = ask (node profile) / default no
TLS_FINGERPRINT="${TLS_FINGERPRINT:-}" # optional: pin panel cert sha256 (auto-set for self-signed panels)
DNS="${DNS:-1.1.1.1}"

DRYRUN=false
ARGS=("$@"); for a in "${ARGS[@]+"${ARGS[@]}"}"; do [ "$a" = "--dry-run" ] && DRYRUN=true; done
PREFIX=""; $DRYRUN && PREFIX="$(pwd)/dryrun"

c(){ printf '\033[%sm' "$1"; }
# data-entry spacing primitives (lib/common.sh is sourced later in this script, but info/warn above use these) —
# redefined identically when common.sh loads. See common.sh for the model.
_SWG_NL=""; _pnl(){ echo; _SWG_NL=1; }; _nlguard(){ _SWG_NL=""; }
info(){ _nlguard; echo "${C_BLUE}▸${RESET} ${BOLD}$*${RESET}"; }   # ▸ light-blue, bold (universal action flag)
# print the sha256 hex of the panel's TLS cert (unverified fetch), or nothing — matches the node's `fingerprint`
_docker_panel_fp(){ python3 - "$1" <<'PY' 2>/dev/null || true
import ssl,socket,hashlib,sys,urllib.parse
r=sys.argv[1]; u=urllib.parse.urlparse(r if '://' in r else 'https://'+r)
host=u.hostname; port=u.port or 443
ctx=ssl._create_unverified_context()
with socket.create_connection((host,port),timeout=6) as s:
    with ctx.wrap_socket(s,server_hostname=host) as ss:
        der=ss.getpeercert(True)
if der: print(hashlib.sha256(der).hexdigest())
PY
}
sub(){  _nlguard; echo "${C_BL}::${RESET} $*"; }                    # :: blue sub-item / progress detail
ok(){   _nlguard; echo "${C_GREEN}✓${RESET} $*"; }
warn(){ _nlguard; echo "${C_BROWN}!${RESET} $*" >&2; }
die(){  echo "${C_RED}✗ $*${RESET}" >&2; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }
run(){ if $DRYRUN; then echo "    [skip] $*"; else "$@"; fi; }
detect_public_ip(){ local ip; ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1 || true)"
  case "$ip" in 127.*) ip="";; esac                                                   # never the loopback — it's not reachable by clients
  [ -z "$ip" ] && ip="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -vE '^127\.' | head -n1 || true)"
  printf '%s' "$ip"; }
ask_tty(){ local v p="$1" d="${2:-}"   # prompt on the terminal (curl|bash keeps a tty); else use default
  # NB: this runs in a $() subshell (ask_yn_tty captures it), so it can only READ _SWG_NL, not set it — hence just
  # a flag-aware LEADING blank; the following step/helper supplies the trailing blank (its own leading, flag clear).
  [ -n "${_SWG_NL:-}" ] || printf '\n' >/dev/tty 2>/dev/null || true
  if printf '  %s%s: ' "$p" "${d:+ [$d]}" 2>/dev/null >/dev/tty && IFS= read -r v 2>/dev/null </dev/tty; then printf '%s' "${v:-$d}"
  else printf '%s' "$d"; fi; }
ask_yn_tty(){ local v p="$1" d="${2:-n}"   # y/n on the tty -> echoes yes|no (default when blank / no tty)
  v="$(ask_tty "$p ($([ "$d" = y ] && echo 'Y/n' || echo 'y/N'))" "")"
  case "${v:-$d}" in [Yy]*) printf yes;; *) printf no;; esac; }
rand_pw(){ head -c12 /dev/urandom | base64 | tr -d '/+=' | head -c16; }

# ── styling shared with the bare-metal installers (same palette + bold ▸ headers) ──
if { [ -t 1 ] || [ -n "${SWG_FORCE_COLOR:-}" ]; } && [ -z "${NO_COLOR:-}" ]; then BOLD=$'\033[1m'; RESET=$'\033[0m'; C_BLUE=$'\033[38;5;39m'; C_GREEN=$'\033[32m'; C_GREY=$'\033[90m'; C_CYAN=$'\033[36m'; C_RED=$'\033[31m'; C_YEL=$'\033[33m'; C_BL=$'\033[38;5;33m'; C_BROWN=$'\033[38;5;130m'
else BOLD=""; RESET=""; C_BLUE=""; C_GREEN=""; C_GREY=""; C_CYAN=""; C_RED=""; C_YEL=""; C_BL=""; C_BROWN=""; fi
b(){ printf '%s%s%s' "$BOLD" "$*" "$RESET"; }
bb(){ printf '%s%s%s%s' "$BOLD" "$C_BLUE" "$*" "$RESET"; }   # bold + blue (handoff URL / login)
col(){ local _c="$1"; shift; printf '%s%s%s' "$_c" "$*" "$RESET"; }
menu(){ printf '  %s\n      %s\n\n' "$1" "$2"; }
key(){  printf '%s[%s]%s%s'   "$C_BLUE"        "$1" "$2" "$RESET"; }   # whole label blue:        key  l 'etsencrypt'           → [l]etsencrypt
keyd(){ printf '%s%s[%s]%s%s' "$BOLD" "$C_BLUE" "$1" "$2" "$RESET"; }   # default label bold+blue: keyd l 'etsencrypt (default)'  → [l]etsencrypt (default)
keyg(){ printf '%s[%s]%s%s'   "$C_GREY"        "$1" "$2" "$RESET"; }   # de-emphasised label grey:  keyg n 'one'                → [n]one
STEP="${STEP_BASE:-1}"; step(){ [ -n "${_SWG_NL:-}" ] || echo; _SWG_NL=""; echo "$(b "Step $STEP. $1")${2:+   $2}"; STEP=$((STEP+1)); }   # skip the leading blank when a prompt already printed one
writef(){ local p="$1" m="${2:-644}" full="$PREFIX$1"; mkdir -p "$(dirname "$full")"; cat > "$full"; chmod "$m" "$full" 2>/dev/null || true; ok "wrote $p ($m)"; }
ask(){ local v p="$1" d="${2:-}"; echo; read -rp "  $p${d:+ [$(col "$C_BLUE" "$d")]}: " v </dev/tty || v=""; printf -v "$3" '%s' "${v:-$d}"; }
v_ip(){ printf '%s' "$1" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$' || return 1; local o; for o in ${1//./ }; do [ "$o" -le 255 ] 2>/dev/null || return 1; done; }
v_host(){ v_ip "$1" && return 0; case "$1" in ""|*" "*|*[!a-zA-Z0-9.-]*) return 1;; *) return 0;; esac; }
v_port(){ case "$1" in ""|*[!0-9]*) return 1;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
port_free(){ have ss || return 0; [ -z "$(ss -lnuH "sport = :$1" 2>/dev/null)" ]; }   # UDP port not already bound
panel_owns_port(){ have docker || return 1; docker port swg-panel 2>/dev/null | sed 's/.*-> //' | grep -qE ":$1\$"; }   # host port $1 is published by OUR swg-panel container (re-install) → not a real conflict
v_freeport(){ v_port "$1" && port_free "$1"; }
# smart default ports: first install offers the base; later ones offer (highest used OF THAT KIND)+1, then
# the next host-free port. turn = TP_LISTEN record; wg/awg = ListenPort across persisted confs + this session's spec.
turn_default_port(){ detect_turn; local hi=0 lis p; if [ "${#TP_LISTEN[@]}" -gt 0 ]; then for lis in "${TP_LISTEN[@]}"; do p="${lis##*:}"; case "$p" in ''|*[!0-9]*) :;; *) [ "$p" -gt "$hi" ] && hi="$p";; esac; done; fi; [ "$hi" -gt 0 ] && next_free_port $((hi+1)) || next_free_port 56000; }
iface_default_port(){ local hi=0 p f e _ifs; for f in "$INSTALL_DIR"/data/node-confs/*.conf; do [ -f "$f" ] || continue; p="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]\{1,\}\).*/\1/p' "$f" | head -1)"; case "$p" in ''|*[!0-9]*) :;; *) [ "$p" -gt "$hi" ] && hi="$p";; esac; done; if [ -n "${NODE_IFACES:-}" ]; then IFS=',' read -ra _ifs <<< "$NODE_IFACES"; for e in "${_ifs[@]}"; do p="$(printf '%s' "$e" | cut -d: -f2)"; case "$p" in ''|*[!0-9]*) :;; *) [ "$p" -gt "$hi" ] && hi="$p";; esac; done; fi; [ "$hi" -gt 0 ] && next_free_port $((hi+1)) || next_free_port 51820; }
v_email(){   case "$1" in ?*@?*.?*) return 0;; *) return 1;; esac; }
v_cftoken(){ [ -n "$1" ]; }
v_cforigin(){ [ -n "$1" ]; }
v_cfport(){  case "$1" in 443|2053|2083|2087|2096|8443) return 0;; *) return 1;; esac; }  # ports Cloudflare's proxy forwards (HTTPS)
# 0 iff $1 is a public, routable IPv4 literal (excludes RFC1918 / loopback / link-local / CGNAT) — gates letsencrypt-ip
ip_public(){ case "$1" in *[!0-9.]*|*.*.*.*.*|*..*) return 1;; *.*.*.*) ;; *) return 1;; esac
  local a b; a="${1%%.*}"; b="${1#*.}"; b="${b%%.*}"
  case "$a" in
    0|10|127) return 1;;
    172) case "$b" in 1[6-9]|2[0-9]|3[01]) return 1;; esac;;
    192) case "$b" in 168) return 1;; esac;;
    169) case "$b" in 254) return 1;; esac;;
    100) case "$b" in 6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7]) return 1;; esac;;
  esac
  return 0; }
# 0 iff cert file $1 is valid for host $2 (host appears as a SAN DNS/IP or the CN) — gates 'reuse' of a cert.
cert_covers_host(){ local cert="$1" host="$2" txt
  [ -s "$cert" ] && command -v openssl >/dev/null 2>&1 || return 1
  txt="$( { openssl x509 -in "$cert" -noout -ext subjectAltName; openssl x509 -in "$cert" -noout -subject; } 2>/dev/null || true)"
  if printf '%s' "$txt" | grep -qE "(DNS:|IP Address:|CN ?= ?)${host//./\\.}(\$|[^0-9A-Za-z.-])"; then return 0; fi
  return 1; }
v_name(){    case "$1" in ""|*[!a-zA-Z0-9_-]*) return 1;; esac; [ "${#1}" -le 40 ]; }   # panel node name for this box (mirrors bare-metal)
# v_iface/v_subnet/v_hostport + next_free_port now in lib/common.sh
v_url(){     case "$1" in ""|*" "*) return 1;; esac
             local h="${1#http://}"; h="${h#https://}"; h="${h%%/*}"; h="${h%%:*}"; v_host "$h"; }
v_httpsurl(){ case "$1" in https://*|http://*) v_host "$(x="${1#http://}"; x="${x#https://}"; x="${x%%/*}"; printf '%s' "${x%%:*}")";; *) v_host "$(x="${1%%/*}"; printf '%s' "${x%%:*}")";; esac; }   # no scheme ok → https:// is prepended after the prompt
v_token(){   [ -n "$1" ] && [ "${#1}" -ge 8 ]; }
# parse_panel_url <input> -> PANEL_HOST_NOPORT, PANEL_BASE (subpath), URL_PORT  (same logic as bare-metal)
parse_panel_url(){ local u="$1" hostport rest
  u="${u#http://}"; u="${u#https://}"; u="${u%/}"
  hostport="${u%%/*}"; rest="${u#"$hostport"}"
  PANEL_BASE="$rest"; [ "$PANEL_BASE" = "/" ] && PANEL_BASE=""; PANEL_BASE="${PANEL_BASE%/}"
  case "$hostport" in
    *:*) PANEL_HOST_NOPORT="${hostport%%:*}"; URL_PORT="${hostport##*:}";;
    *)   PANEL_HOST_NOPORT="$hostport"; URL_PORT="";;
  esac; }
ask_choice(){ local p="$1" d="$2" var="$3" opts="$4" v o forced rc i
  if [ -n "${!var:-}" ]; then for o in $opts; do [ "${!var}" = "$o" ] && return; done; fi
  while :; do
    if read -rp "  $p [$(bb "$d")]: " v </dev/tty; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"; forced=no; case "$v" in *' --force') v="${v% --force}"; v="${v%"${v##*[![:space:]]}"}"; forced=yes;; esac
    case "$v" in ""|*[!0-9]*) :;; *) i=1; for o in $opts; do [ "$i" = "$v" ] && { v="$o"; break; }; i=$((i+1)); done;; esac   # [N] -> the Nth option (1-indexed menus)
    for o in $opts; do [ "$v" = "$o" ] && { printf -v "$var" '%s' "$v"; _pnl; return; }; done
    [ "$forced" = yes ] && { warn "forcing: $v"; printf -v "$var" '%s' "$v"; _pnl; return; }
    [ $rc -ne 0 ] && die "‘$v’ is not one of: $opts"
    warn "‘$v’ isn't one of: $opts"; echo "  re-enter, or append ' --force' to use it anyway"
  done; }
ask_valid(){ local p="$1" d="$2" var="$3" fn="$4" hint="$5" v forced rc
  if [ -n "${!var:-}" ]; then "$fn" "${!var}" && return; fi
  [ -n "${_SWG_NL:-}" ] || echo; _SWG_NL=""
  while :; do
    if read -rp "  $p${d:+ [$(col "$C_BLUE" "$d")]}: " v </dev/tty; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"; forced=no; case "$v" in *' --force') v="${v% --force}"; v="${v%"${v##*[![:space:]]}"}"; forced=yes;; esac
    if "$fn" "$v"; then printf -v "$var" '%s' "$v"; _pnl; return; fi
    [ "$forced" = yes ] && { warn "forcing: $v"; printf -v "$var" '%s' "$v"; _pnl; return; }
    [ $rc -ne 0 ] && die "no valid value for ‘$p’"
    warn "$hint"; echo "  re-enter, or append ' --force' to use it anyway"
  done; }

# ── turn-proxy (vk-turn-proxy) — host systemd service forwarding to the published wg port ──
# Each turn-proxy runs as a sibling CONTAINER (swg-turn-*); the installer only writes the record into
# ./data/node, which is bind-mounted into swg-node at /var/lib/swg-noded. swg-noded (SWG_TURN_RECORD)
# materialises it into containers on its first run and reports them to the panel.
TURN_RECORD="${TURN_RECORD:-$INSTALL_DIR/data/node/turn-proxy.json}"
MIGRATED_TURNS=""   # bare turn-proxy units migrate_baremetal_turns brought into the docker record → torn down at the switch
declare -A TP_LISTEN TP_CONNECT TP_WRAP
gen_wrap_key(){ $DRYRUN && { echo "GENERATED-ON-REAL-RUN"; return 0; }
  openssl rand -hex 32 2>/dev/null || head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
turn_wrap_flags(){ local k; case "$1" in   # per-fork obfuscation flags (verified from each binary's -h)
  anton48)      k="$(gen_wrap_key)"; printf -- '-wrap-srtp -wrap-key %s' "$k";;
  samosvalishe) k="$(gen_wrap_key)"; printf -- '-wrap -wrap-key %s' "$k";;
  WINGS-N)      k="$(gen_wrap_key)"; printf -- '-wrap-mode on -wrap-key %s' "$k";;
  Moroka8)      k="$(gen_wrap_key)"; printf -- '-wrap -wrap-key %s' "$k";;   # verified from its README: -wrap -wrap-key
  *) printf '';; esac; }
detect_turn(){ TP_LISTEN=(); TP_CONNECT=(); TP_WRAP=(); local name lis con wk   # container model: read the RECORD
  [ -f "$TURN_RECORD" ] || return 0
  while IFS=$'\t' read -r name lis con wk; do
    [ -n "$name" ] && { TP_LISTEN[$name]="$lis"; TP_CONNECT[$name]="$con"; TP_WRAP[$name]="$wk"; }
  done < <(python3 - "$TURN_RECORD" 2>/dev/null <<'PY'
import json, sys
try: d = json.load(open(sys.argv[1])); tps = d.get("turn_proxies") or []
except Exception: tps = []
for t in (tps if isinstance(tps, list) else []):
    print("\t".join([str(t.get("service", "")), str(t.get("listen", "")), str(t.get("connect", "")), str(t.get("wrap_key", ""))]))
PY
) ; return 0; }   # a record line with an empty service would leave the loop non-zero → trips set -e at the bare callers
# One instance == one container (swg-turn-<fork>-<port>) so the SAME fork can run many times
# (2× wings, 3× samosvalishe, …) — each on its own port with its own wrap key.
install_turn_binary(){ local fork="$1" owner="$2" listen="$3" connect="$4" extra="$5" port inst svc
  # CONTAINER model: don't install a host systemd unit or download here — just write the turn RECORD.
  # swg-noded materialises it into a sibling container (swg-turn-*) on its next start (it fetches the binary).
  port="${listen##*:}"; inst="$fork-$port"; svc="vk-turn-proxy-$inst"
  if $DRYRUN; then echo "    [skip] record turn-proxy $svc ($owner: $listen → $connect) in $TURN_RECORD"
  else
    mkdir -p "$(dirname "$TURN_RECORD")"
    python3 - "$TURN_RECORD" "$svc" "$owner" "$listen" "$connect" "$extra" <<'PY' || { warn "couldn't write turn record"; return 0; }
import json, sys, re
p, svc, owner, listen, connect, extra = sys.argv[1:7]
try:
    d = json.load(open(p)); tps = d.get("turn_proxies") if isinstance(d, dict) else None
    tps = tps if isinstance(tps, list) else []
except Exception:
    tps = []
tps = [t for t in tps if t.get("service") != svc]
m = re.search(r"-wrap-key[ =]+(\S+)", extra or "")
tps.append({"service": svc, "listen": listen, "connect": connect,
            "params": (extra or "").strip(), "wrap_key": (m.group(1) if m else ""), "owner": owner})
json.dump({"turn_proxies": tps}, open(p, "w"))
PY
  fi
  ok "configured turn-proxy $(col "$C_GREEN" "$inst") ($owner) — $listen → $connect (starts as a container on first run)"; }
# every wg/awg interface on this node as "<name> <listen-port> <proto>": persisted node-confs (AUTHORITATIVE
# ListenPort) first, then this session's NODE_IFACES additions not already on disk. Drives the turn-proxy
# forward-to picker so it lists ALL interfaces with their REAL ports — not just the bootstrap NODE_IFACE on a
# stale .env port (which is why a re-install showed only awg0:51820 + the new iface, missing wg2/wg4).
# the interface a turn-proxy forwards to: the node iface whose listen port matches the connect port (else empty)
fwd_iface_for(){ local cp="${1##*:}" nm pt; while read -r nm pt _; do [ -n "$nm" ] && [ "$pt" = "$cp" ] && { printf '%s' "$nm"; return 0; }; done <<< "$(node_iface_rows)"; return 0; }   # no match → empty + success (non-zero would trip set -e)
node_iface_rows(){
  local seen=" " c n pt pr e _ifs
  if [ -d "$INSTALL_DIR/data/node-confs" ]; then
    for c in "$INSTALL_DIR/data/node-confs/"*.conf; do [ -f "$c" ] || continue
      n="$(basename "$c" .conf)"
      pt="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]\{1,\}\).*/\1/p' "$c" | head -1)"
      if grep -qiE '^[[:space:]]*(Jc|Jmin|Jmax|S1|S2|H1|H2|H3|H4|I[1-5]|Itime)[[:space:]]*=' "$c"; then pr=awg; else pr=wg; fi
      case "$seen" in *" $n "*) :;; *) printf '%s %s %s\n' "$n" "${pt:-?}" "$pr"; seen="$seen$n ";; esac
    done
  fi
  if [ -n "${NODE_IFACES:-}" ]; then IFS=',' read -ra _ifs <<< "$NODE_IFACES"
    for e in "${_ifs[@]}"; do
      n="$(printf '%s' "$e"|cut -d: -f1)"; pt="$(printf '%s' "$e"|cut -d: -f2)"; pr="$(printf '%s' "$e"|cut -d: -f4)"
      [ "$pr" = wg ] || pr=awg; [ -n "$n" ] || continue
      case "$seen" in *" $n "*) :;; *) printf '%s %s %s\n' "$n" "${pt:-?}" "$pr"; seen="$seen$n ";; esac
    done
  fi
}
# one styled interface row (green name + proto + endpoint:port + address) for the manage-loop lists, matching the SUMMARY.
# queued spec for an interface from NODE_IFACES (name:port:addr:proto:ep), if any — so a just-queued iface
# (no conf written yet) still shows its real proto/port/address instead of guessing.
node_iface_spec(){ local n="$1" e _ifs; [ -n "${NODE_IFACES:-}" ] || return 1; IFS=',' read -ra _ifs <<< "$NODE_IFACES"
  for e in "${_ifs[@]}"; do [ "$(printf '%s' "$e" | cut -d: -f1)" = "$n" ] && { printf '%s' "$e"; return 0; }; done; return 1; }
iface_row(){ local n="$1" conf spec proto="" ep="" lp="" addr=""   # set -e safe; prefer a queued NODE_IFACES spec, else the conf
  is_sys_iface "$n" && return 0   # panel-managed mesh links are never shown in a user-facing interface list
  spec="$(node_iface_spec "$n" || true)"
  if [ -n "$spec" ]; then
    lp="$(printf '%s' "$spec" | cut -d: -f2)"; addr="$(printf '%s' "$spec" | cut -d: -f3)"
    proto="$(printf '%s' "$spec" | cut -d: -f4)"; [ "$proto" = wg ] || proto=awg   # empty field4 = awg (plain=="")
    ep="$(printf '%s' "$spec" | cut -d: -f5-)"
  else
    conf="$(find_iface_conf "$n" 2>/dev/null || true)"
    if [ -n "$conf" ]; then
      grep -qiE '^[[:space:]]*(Jc|Jmin|Jmax|S1|S2|H1|H2|H3|H4|I[1-5]|Itime)[[:space:]]*=' "$conf" 2>/dev/null && proto=awg || proto=wg
      lp="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$conf" 2>/dev/null | head -1 || true)"
      addr="$(sed -n 's/^[[:space:]]*Address[[:space:]]*=[[:space:]]*\([0-9./]*\).*/\1/p' "$conf" 2>/dev/null | head -1 || true)"
    fi
  fi
  [ -n "$proto" ] || case "$n" in awg*) proto=awg;; *) proto=wg;; esac   # no conf/spec → infer from the name (awg0 ⇒ AmneziaWG), not a blind wg
  [ -n "$ep" ] || ep="${NODE_ENDPOINT:-}"; case "$ep" in 127.*|"") ep="$(detect_public_ip 2>/dev/null || true)";; esac   # never show loopback as the public endpoint
  printf '    %s%s%s  %s%-10s%s  %s:%s  %s\n' "$C_GREEN" "$(printf '%-10s' "$n")" "$RESET" "$BOLD" "$(proto_label "$proto")" "$RESET" "${ep:-?}" "${lp:-?}" "${addr:-?}"; }
# turn-proxy forward-to value: accept an interface NAME (resolved to 127.0.0.1:<its listen port>) or a custom ip:port.
v_fwd(){ local names; names=" $(node_iface_rows | cut -d' ' -f1 | tr '\n' ' ')${NODE_IFACE:+$NODE_IFACE }"; case "$names" in *" $1 "*) return 0;; esac; v_hostport "$1"; }
fwd_resolve(){ local n p x; while read -r n p x; do [ -n "$n" ] && [ "$n" = "$1" ] && { echo "127.0.0.1:$p"; return; }; done <<< "$(node_iface_rows)"
  [ -n "${NODE_IFACE:-}" ] && [ "$1" = "$NODE_IFACE" ] && { echo "127.0.0.1:${NODE_LISTEN_PORT:-51820}"; return; }; echo "$1"; }
install_turn_proxy(){   # <fork> — params, then install (the fork is chosen in choose_turn_proxy)
  local sel="$1" owner pub port connect; owner="$(turn_repo_owner "$sel")" || { warn "unknown turn-proxy branch: $sel"; return 0; }
  ask_valid "Public IP this turn-proxy is reached at" "${NODE_ENDPOINT:-$(detect_public_ip)}" pub v_host "an IP or hostname"
  ask_valid "Turn-proxy listen port" "$(turn_default_port)" port v_freeport "port 1–65535 and free (not already in use)"
  detect_turn; local n; for n in "${!TP_LISTEN[@]}"; do [ "${TP_LISTEN[$n]##*:}" = "$port" ] && { warn "port $port is already used by turn-proxy '$n' — pick another port (enter 'new' again)"; return 0; }; done
  local defport="${NODE_LISTEN_PORT:-51820}" defname _nm _pt _pr label clabel pad rows
  rows="$(node_iface_rows)"
  echo
  echo "  Available wg/awg interfaces:"
  if [ -n "$rows" ]; then
    defname="$(printf '%s\n' "$rows" | head -1)"; defname="${defname%% *}"   # first interface NAME
    while read -r _nm _pt _pr; do [ -n "$_nm" ] || continue
      [ "$_pr" = wg ] && _pr=wg || _pr=awg
      label="[$_nm] on $_pr"; clabel="$(col "$C_GREEN" "[$_nm]") on $(b "$_pr")"
      pad=$((15 - ${#label})); [ "$pad" -lt 1 ] && pad=1
      printf '    %s%*s%s\n' "$clabel" "$pad" "" "$(col "$C_BLUE" "127.0.0.1:$_pt")"
    done <<< "$rows"
  elif [ -n "$NODE_IFACE" ]; then                        # a bootstrap interface is configured but not on disk yet (fresh install)
    _pr=awg; [ "${NODE_PLAIN_WG:-}" = yes ] && _pr=wg
    label="[$NODE_IFACE] on $_pr"; clabel="$(col "$C_GREEN" "[$NODE_IFACE]") on $(b "$_pr")"
    pad=$((15 - ${#label})); [ "$pad" -lt 1 ] && pad=1
    printf '    %s%*s%s\n' "$clabel" "$pad" "" "$(col "$C_BLUE" "127.0.0.1:$defport")"
    defname="$NODE_IFACE"
  else                                                   # zero interfaces (panel-managed) — no default; make the operator type a real target
    echo "    (none yet — enter a custom $(b ip:port) to forward to, or add an interface from the panel first)"
    defname=""
  fi
  ask_valid "WireGuard/AmneziaWG address it forwards to - interface name or custom ip:port" "$defname" connect v_fwd "an interface name (e.g. awg0) or ip:port"
  connect="$(fwd_resolve "$connect")"
  echo
  local wrap; wrap="$(turn_wrap_flags "$sel")"
  [ -n "$wrap" ] && info "Obfuscation: a 64-hex wrap key is generated, baked into the unit, and recorded for the panel / client configs." \
                 || warn "$sel has no wrap/srtp obfuscation flags — installing plain (-listen/-connect only)."
  install_turn_binary "$sel" "$owner" "$pub:$port" "$connect" "$wrap"; }
choose_turn_proxy(){ info "Checking for turn-proxy servers on this host…"; local sel names n
  while :; do
    detect_turn; names=("${!TP_LISTEN[@]}")
    echo
    if [ "${#names[@]}" -gt 0 ]; then echo "  Installed turn-proxy servers:"; echo
      for n in "${names[@]}"; do _fw="$(fwd_iface_for "${TP_CONNECT[$n]}")"; printf '    %s%s%s %s → %s%s\n' "$C_GREEN" "$n" "$RESET" "${TP_LISTEN[$n]}" "${TP_CONNECT[$n]}" "${_fw:+ $(col "$C_GREEN" "($_fw)")}"; done
    else warn "No turn-proxy servers found on this box."; fi
    echo
    echo "  Here is a list of turn-proxy branches available for installation:"; echo
    menu "$(col "$C_BLUE" '[0] [c]acggghp')"     "The original project - https://github.com/cacggghp/vk-turn-proxy"
    menu "$(col "$C_BLUE" '[1] [W]INGS-N')"      "Fork by WINGS-N - https://github.com/WINGS-N/vk-turn-proxy"
    menu "$(col "$C_BLUE" '[2] [s]amosvalishe')" "Fork by samosvalishe - https://github.com/samosvalishe/vk-turn-proxy"
    menu "$(col "$C_BLUE" '[3] [k]iper292')"     "Fork by kiper292 - https://github.com/kiper292/vk-turn-proxy"
    menu "$(col "$C_BLUE" '[4] [M]oroka8')"      "Fork by Moroka8 - https://github.com/Moroka8/vk-turn-proxy"
    menu "$(col "$C_BLUE" '[5] [a]nton48')"      "Fork by anton48 - https://github.com/anton48/vk-turn-proxy"
    printf '  Enter a number, letter or name to install, or just press %s to skip and proceed with the setup: ' "$(b Enter)"
    if ! read -r sel 2>/dev/null </dev/tty; then echo; warn "no interactive input — skipping turn-proxy step"; break; fi
    sel="${sel//[[:space:]]/}"; [ -z "$sel" ] && break
    sel="$(printf '%s' "$sel" | tr '[:upper:]' '[:lower:]')"   # case-insensitive (W/w, M/m, …)
    case "$sel" in
      0|c|cacggghp|original|main)  install_turn_proxy cacggghp; continue;;
      1|w|wings|wings-n)           install_turn_proxy WINGS-N; continue;;
      2|s|samosvalishe)            install_turn_proxy samosvalishe; continue;;
      3|k|kiper|kiper292)          install_turn_proxy kiper292; continue;;
      4|m|moroka|moroka8)          install_turn_proxy Moroka8; continue;;
      5|a|anton|anton48)           install_turn_proxy anton48; continue;;
      *) warn "enter 0–5, a letter (c/w/s/k/m/a) or a name (or press Enter to skip)";; esac
  done; }
# bare→docker convert: migrate THIS box's host turn-proxy systemd units → the docker turn RECORD (swg-noded
# materialises them as sibling containers). The exact mirror of install-node's migrate_docker_turns: runs in the
# turn step (node stage), lists them, asks "Transfer? (Y/n)", and copy-firsts — the bare units keep serving until
# the atomic switch tears them down (recorded in MIGRATED_TURNS). Decline ⇒ left on bare-metal (stopped at switch).
migrate_baremetal_turns(){
  [ "${SWG_CONVERT_DIR:-}" = convert-docker ] || return 0
  local units u svc owner lis con params envf exe inst
  units="$(ls /etc/systemd/system/vk-turn-proxy-*.service 2>/dev/null)" || true
  [ -n "$units" ] || return 0
  echo; info "Turn-proxies to migrate from the bare-metal node:"; echo
  for u in $units; do svc="$(basename "$u" .service)"; inst="${svc#vk-turn-proxy-}"; envf="/opt/vk-turn-proxy/$inst/turn.env"
    lis=""; con=""; [ -f "$envf" ] && { lis="$(sed -n 's/^SWG_LISTEN=//p' "$envf" | head -1)"; con="$(sed -n 's/^SWG_CONNECT=//p' "$envf" | head -1)"; }
    printf '    %s%s%s  %s → %s\n' "$C_GREEN" "$svc" "$RESET" "${lis:-?}" "${con:-?}"; done
  echo
  [ "$(ask_yn_tty "Transfer these turn-proxies into the docker node?" y)" = yes ] || { info "  left on bare-metal — they stop at the switch; add fresh ones below if you want"; return 0; }
  for u in $units; do
    svc="$(basename "$u" .service)"; inst="${svc#vk-turn-proxy-}"; envf="/opt/vk-turn-proxy/$inst/turn.env"
    if [ -f "$envf" ]; then
      lis="$(sed -n 's/^SWG_LISTEN=//p' "$envf" | head -1)"; con="$(sed -n 's/^SWG_CONNECT=//p' "$envf" | head -1)"; params="$(sed -n 's/^SWG_PARAMS=//p' "$envf" | head -1)"
    else
      exe="$(sed -n 's/^ExecStart=//p' "$u" | head -1)"
      lis="$(printf '%s' "$exe" | sed -n 's/.*-listen[ =]\{1,\}\([^ ]*\).*/\1/p')"; con="$(printf '%s' "$exe" | sed -n 's/.*-connect[ =]\{1,\}\([^ ]*\).*/\1/p')"
      params="$(printf '%s' "$exe" | sed -n 's/.*-connect[ =]\{1,\}[^ ]*[[:space:]]*\(.*\)$/\1/p')"
    fi
    owner="$(sed -n 's/.*vk-turn-proxy (\([^)]*\)).*/\1/p' "$u" | head -1)"
    fork="${svc#vk-turn-proxy-}"; fork="${fork%-*}"
    install_turn_binary "$fork" "$owner" "$lis" "$con" "$params"     # writes the docker turn RECORD (no host unit)
    MIGRATED_TURNS="${MIGRATED_TURNS:+$MIGRATED_TURNS }$svc"          # tear the bare unit down at the atomic switch
  done
}

# ───────────────────────── flags ─────────────────────────
while [ $# -gt 0 ]; do
  case "$1" in
    --profile)              PROFILE="${2:-host}"; shift 2 || shift;;
    master)                 PROFILE=master; ROLE=master; shift;; # bare-metal-style role word → master profile
    host|node|host-node)    PROFILE="$1"; shift;;          # bare positional profile (e.g. "docker node")
    -role|--role)           ROLE="${2:-}"; shift 2 || shift;;    # master|host — skips the Step 1 role prompt
    -pass|--pass|-password) PANEL_PASSWORD="${2:-}"; shift 2 || shift;;
    -user|--user|-username) PANEL_USER="${2:-}"; shift 2 || shift;;
    -domain|--domain)       PANEL_DOMAIN="${2:-}"; shift 2 || shift;;
    -base|--base)           PANEL_BASE="${2:-}"; shift 2 || shift;;
    -port|--port)           PANEL_PORT="${2:-}"; PANEL_PORT_EXPLICIT=yes; shift 2 || shift;;
    -tls|--tls)             TLS="${2:-}"; shift 2 || shift;;
    -email|--email)         ACME_EMAIL="${2:-}"; shift 2 || shift;;
    -cf-token|--cf-token)   CF_TOKEN="${2:-}"; shift 2 || shift;;
    -cf-origin|--cf-origin) CF_ORIGIN_TOKEN="${2:-}"; shift 2 || shift;;
    -key|--key|-token)      NODE_TOKEN="${2:-}"; shift 2 || shift;;
    -host|--host|-url)      PANEL_URL="${2:-}"; shift 2 || shift;;
    -endpoint|--endpoint)   NODE_ENDPOINT="${2:-}"; shift 2 || shift;;
    -net|--net|--network)   NODE_NET="${2:-}"; shift 2 || shift;;
    -turn-manage|--turn-manage) TURN_MANAGE="${2:-}"; shift 2 || shift;;
    -verify|--verify)       TLS_VERIFY="${2:-}"; shift 2 || shift;;
    -iface|--iface)         NODE_IFACE="${2:-}"; shift 2 || shift;;
    -ifaces|--ifaces)       NODE_IFACES="${2:-}"; shift 2 || shift;;
    --build)                BUILD=true; shift;;
    --dry-run)              shift;;
    *)                      shift;;
  esac
done
case "$PROFILE" in host|node|host-node|master) ;; *) die "profile must be host|node|master";; esac
[ "$PROFILE" = host-node ] && PROFILE=master                    # normalize the legacy alias
[ "$PROFILE" = master ] && ROLE=master                          # explicit master profile ⇒ master role
case "$ROLE" in ""|master|host) ;; *) die "role must be master|host";; esac
[ -n "$PANEL_BASE" ] && PANEL_BASE="/$(printf '%s' "$PANEL_BASE" | sed 's#^/*##; s#/*$##')"

[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && { info "DRY RUN — .env renders under ./dryrun, no Docker commands run."; rm -rf "$PREFIX"; }
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SRC/lib/common.sh"   # shared helpers: v_iface/v_subnet/v_hostport, next_free_port, turn_repo_owner, dl_turn_bin
# docker re-install can be a node (POST to its panel), a host (host_proc file), or a master (BOTH) → one
# emit backend that fans out to whichever LC_* vars are set.
lc_emit_docker(){
  [ -n "${LC_TOKEN:-}" ] && [ -n "${LC_URL:-}" ] && lc_emit_post "$1" "${2:-}"
  [ -n "${LC_FILE:-}" ] && lc_emit_file "$1" "${2:-}"
  return 0; }

# Idempotent re-install: re-use the current .env's values (token, URL, login, interface defaults) so
# re-running keeps everything and the ./data state is untouched. To start fresh, run the uninstaller.
EXISTING_DOCKER=no; EXIST_TLS=""
if [ -f "$INSTALL_DIR/.env" ]; then
  EXISTING_DOCKER=yes
  for _k in PANEL_URL NODE_TOKEN NODE_ENDPOINT PANEL_USER PANEL_PASSWORD PANEL_DOMAIN PANEL_PORT PANEL_BASE \
            SUB_PORT SUB_DOMAIN PANEL_BIND SUB_BIND SUB_TRUST_XFF \
            NODE_IFACE NODE_IFACES NODE_LISTEN_PORT NODE_ADDRESS NODE_MTU NODE_PLAIN_WG NODE_NET TURN_MANAGE DNS TLS_VERIFY \
            ACME_EMAIL CF_TOKEN CF_ORIGIN_TOKEN; do
    [ -n "${!_k:-}" ] && continue                       # an explicit flag/env wins over the stored value
    _v="$(sed -n "s/^${_k}=//p" "$INSTALL_DIR/.env" 2>/dev/null | head -1)"
    _v="${_v%\"}"; _v="${_v#\"}"                        # strip surrounding quotes
    [ -n "$_v" ] && printf -v "$_k" '%s' "$_v"
  done
  EXIST_TLS="$(sed -n 's/^TLS=//p' "$INSTALL_DIR/.env" 2>/dev/null | head -1)"   # for the 'reuse' TLS option (not auto-applied)
  if [ "$PROFILE" = node ]; then
    info "Existing node install detected — keeping your interfaces + data. Press $(b Enter) to keep each value (to start fresh, run the uninstaller first)."
  else
    info "Existing docker install detected in $INSTALL_DIR — keeping your .env + ./data (token, login, interfaces). To start fresh, uninstall first."
  fi
fi

# RE-INSTALL: signal "re-installing" the MOMENT the script starts (before any prompt) + arm the traps. Node →
# POST to the panel (+ re-baseline the server key); panel → flag the still-running container's host_proc. A
# re-install installs the latest → terminal is "re-installed and updated" (a convert keeps its own op via
# SWG_CONVERT_DIR). The box-name rename is pushed later, once ask_node_conn has it.
if { [ "$EXISTING_DOCKER" = yes ] || [ -n "${SWG_CONVERT_DIR:-}" ] || ls "$INSTALL_DIR/data/node-confs/"*.conf >/dev/null 2>&1; } && ! $DRYRUN; then
  if [ -n "${NODE_TOKEN:-}" ] && [ -n "${PANEL_URL:-}" ]; then   # token from kept .env, -key recovery, or convert — any re-enroll posts the lifecycle
    LC_URL="$PANEL_URL"; LC_TOKEN="$NODE_TOKEN"; LC_VERIFY="${TLS_VERIFY:-no}"
    case "$PANEL_URL" in *//swg-panel|*//swg-panel/*|*//swg-panel:*)
      LC_URL="$(printf '%s' "$PANEL_URL" | sed -E "s#^(https?://)[^/]+#\1127.0.0.1:${PANEL_PORT:-443}#")"; LC_VERIFY=no ;; esac
    rm -rf "$INSTALL_DIR/data/node/iface-keys" 2>/dev/null || true
  fi
  # set the panel header file when a swg-panel container exists (re-install) OR will be created by THIS run
  # (a bare→docker host/master convert — the container reads data/lib/host_proc once compose brings it up, so the
  # 'converted-docker' terminal lands on the new panel's header). A node convert has no panel → no host_proc.
  # ...but NEVER for a node-profile op — a node's status belongs on its node tile (the POST above), not the panel
  # header. On a master box a swg-panel container exists, so guard the WHOLE condition with PROFILE != node (else a
  # plain `docker node` re-install would write "reinstalling" onto the panel header).
  if [ "$PROFILE" != node ] \
     && { docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-panel || [ "${SWG_CONVERT_DIR:-}" = convert-docker ]; }; then
    mkdir -p "$INSTALL_DIR/data/lib" 2>/dev/null; LC_FILE="$INSTALL_DIR/data/lib/host_proc"
  fi
  _lcop="${SWG_CONVERT_DIR:-reinstall}"
  # SWG_LC_PARENT=1 ⇒ a parent convert (master = host+node) owns the lifecycle terminal, so don't lc_init here
  # (we'd emit a premature 'converted' when THIS sub-step exits, before the other half + the final summary).
  { [ "${SWG_LC_PARENT:-}" != 1 ] && { [ -n "${LC_TOKEN:-}" ] || [ -n "${LC_FILE:-}" ]; }; } && lc_init "$_lcop" lc_emit_docker
  [ -z "${SWG_CONVERT_DIR:-}" ] && LC_SUCCESS="reinstalled-updated"   # plain re-install → "re-installed and updated"
fi

# bare→docker CONVERT: the panel login (pbkdf2) is already staged in data/etc/auth — never regenerate or
# overwrite it; show it as "unchanged" in the summary. (A fresh/re-install has no SWG_CONVERT_DIR.)
KEEP_AUTH=no
if [ -n "${SWG_CONVERT_DIR:-}" ] && [ -f "$PREFIX$INSTALL_DIR/data/etc/auth" ]; then
  KEEP_AUTH=yes
  _au="$(cut -d: -f1 "$PREFIX$INSTALL_DIR/data/etc/auth" 2>/dev/null | head -1)"; [ -n "$_au" ] && PANEL_USER="$_au"
  PANEL_PASSWORD="(preserved)"
fi

# ───────────────────────── per-profile requirements ─────────────────────────
# Compose interpolates the whole file (both services), so every referenced var must be
# non-empty even when its service isn't in the active profile — fill sane placeholders.
ask_panel_login(){   # Panel URL (identical look + parsing to bare-metal); login auto-generated
  step "Panel URL"
  echo
  echo "      Where the panel is reached — an IP, a host, or a host with a subpath to"
  echo "      live under an existing site (e.g. $(b 'vpn.example.com/swg'))."
  echo
  local def="${PANEL_DOMAIN:-$(detect_public_ip)}"; [ -z "$def" ] && def=localhost; local _url_ans _forced="" _pp _who
  # re-install (or -host): show the saved port/subpath in the default URL, e.g. host:8443/swg — not just the host
  if [ -n "${PANEL_DOMAIN:-}" ]; then
    { [ -n "${PANEL_PORT:-}" ] && [ "$PANEL_PORT" != 443 ]; } && def="$def:$PANEL_PORT"
    [ -n "${PANEL_BASE:-}" ] && def="$def$PANEL_BASE"
  fi
  PANEL_DOMAIN=""   # ask_valid skips if non-empty; force the prompt and parse the result
  ask_valid "Enter panel URL (https://…)" "$def" PANEL_DOMAIN v_url "enter a host or IP, optionally with a /subpath (e.g. vpn.example.com/swg)"
  while :; do
    parse_panel_url "$PANEL_DOMAIN"
    # is the port the panel will publish actually free on this host? (catches nginx/apache or a prior panel)
    _pp="${URL_PORT:-443}"
    if [ "${SWG_CONVERT_KILL_PANEL:-}" != 1 ] && [ "$_forced" != "$_pp" ] && ! $DRYRUN && have ss && [ -n "$(ss -lntH "sport = :$_pp" 2>/dev/null)" ] && ! panel_owns_port "$_pp"; then
      _who="$(ss -lntpH "sport = :$_pp" 2>/dev/null | grep -oE '"[^"]+"' | head -1 | tr -d '"' || true)"
      echo; warn "port $(col "$C_YEL" ":$_pp") is already in use${_who:+ (by $(col "$C_YEL" "$_who"))} — the panel can't bind it"
      echo "    Give the panel its own port (e.g. $(b "${PANEL_HOST_NOPORT}:8443")), or stop whatever holds it."
      printf '  Enter a different URL, or type %s to publish on :%s anyway: ' "$(bb force)" "$_pp"
      read -r _url_ans </dev/tty || _url_ans=force
      case "$(printf '%s' "$_url_ans" | tr -d '[:space:]')" in
        force|FORCE) _forced="$_pp";;
        "") :;;
        *) if v_url "$_url_ans"; then PANEL_DOMAIN="$_url_ans"; else warn "‘$_url_ans’ isn't a valid host/URL — try again."; fi;;
      esac
      continue
    fi
    { [ -z "$URL_PORT" ] || v_cfport "$URL_PORT"; } && break   # no port or a Cloudflare-proxyable one → fine
    echo
    warn "Port $(col "$C_YEL" "$URL_PORT") is NOT a standard HTTPS port Cloudflare's proxy (orange cloud) forwards."
    echo "         Cloudflare proxies HTTPS only on: $(b '443, 2053, 2083, 2087, 2096, 8443')."
    echo "         Behind the orange cloud the panel on $URL_PORT is unreachable, so $(b cloudflare)/$(b cf15)"
    echo "         certificates won't work. ($(b letsencrypt)/$(b selfsigned) on a directly-reachable port is fine.)"
    echo
    printf '  To keep the port %s type %s, or enter a new URL to change: ' "$URL_PORT" "$(bb proceed)"
    read -r _url_ans </dev/tty || _url_ans=proceed
    case "$(printf '%s' "$_url_ans" | tr -d '[:space:]')" in
      proceed|"") break;;                                           # keep the current port
      *) if v_url "$_url_ans"; then PANEL_DOMAIN="$_url_ans"        # adopt the new URL; loop re-parses + re-checks
         else warn "‘$_url_ans’ isn't a valid host/URL — try again."; fi ;;
    esac
  done
  PANEL_DOMAIN="$PANEL_HOST_NOPORT"; [ -z "$PANEL_DOMAIN" ] && PANEL_DOMAIN=localhost
  [ -n "$PANEL_BASE" ] && ok "panel will be served under subpath ${PANEL_BASE}/"
  # an explicit -port flag wins; otherwise the URL's :port wins (even over a stale value loaded from a
  # re-install's .env, so changing the URL to host:8443 actually moves the published port); else 443.
  if   [ "${PANEL_PORT_EXPLICIT:-no}" = yes ]; then :
  elif [ -n "$URL_PORT" ];                     then PANEL_PORT="$URL_PORT"
  else PANEL_PORT="${PANEL_PORT:-443}"; fi
  [ "${PANEL_USER:-admin}" = admin ] && PANEL_USER="admin$(( RANDOM % 900 + 100 ))"   # admin+3 digits, like bare-metal (-user overrides)
  [ -z "$PANEL_PASSWORD" ] && PANEL_PASSWORD="$(rand_pw)"   # auto-generated; pass -pass to set your own
  return 0   # never let a short-circuited && above make the function (and set -e) fail
}
ask_panel_tls(){     # TLS certificate (same look as bare-metal); issued INSIDE the container by acme.sh
  step "TLS certificate"
  echo
  # Panel URL shape decides the certs offered: domain → letsencrypt/cloudflare/cf15; public IP → letsencrypt-ip
  # (LE short-lived IP cert); private/bare → selfsigned/none only.
  local _url_is_domain=no _ip_public=no _opts _def _le _reuse_avail=no _w80 _ans80 _tn
  case "$PANEL_DOMAIN" in *[a-zA-Z]*) case "$PANEL_DOMAIN" in *.*) _url_is_domain=yes;; esac;; esac
  [ "$_url_is_domain" = yes ] || { ip_public "$PANEL_DOMAIN" && _ip_public=yes; }
  local _lip _ss
  if   [ "$_url_is_domain" = yes ]; then _opts="letsencrypt cloudflare cf15 selfsigned none l c cf 15 15years 15cf s self n"; _def=l
  elif [ "$_ip_public" = yes ];     then _opts="letsencrypt-ip selfsigned none lip ip letsencrypt l s n"; _def=letsencrypt-ip
  else                                   _opts="selfsigned none s n";                                    _def=s; fi
  # offer 'reuse' ONLY if the existing cert actually covers this URL (host in its SAN/CN); a cert for a
  # different host/IP can't be reused here, so hide reuse and let the working default win (never two defaults).
  if [ "$EXISTING_DOCKER" = yes ] && [ -f "$INSTALL_DIR/data/etc/tls/fullchain.pem" ] \
     && cert_covers_host "$INSTALL_DIR/data/etc/tls/fullchain.pem" "$PANEL_DOMAIN"; then
    _reuse_avail=yes; _opts="reuse $_opts r"; _def=r
  fi
  # exactly ONE "(default)": reuse when offered, otherwise each branch's primary option carries it
  if [ "$_reuse_avail" = yes ]; then _le="$(key l 'etsencrypt')";            _lip="$(key l 'etsencrypt-ip')";            _ss="$(key s 'elfsigned')"
  else                               _le="$(keyd l 'etsencrypt (default)')"; _lip="$(keyd l 'etsencrypt-ip (default)')"; _ss="$(keyd s 'elfsigned (default)')"; fi
  while :; do
    _tn=0
    [ "$_reuse_avail" = yes ] && { _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $(keyd r 'euse (default)')"    "Keep the existing $(b "${EXIST_TLS:-cert}") certificate — it already covers $(b "$PANEL_DOMAIN"), no re-issue (recommended for a re-install)"; }
    if [ "$_url_is_domain" = yes ]; then
      _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $_le"                                "Let's Encrypt cert via acme.sh HTTP-01 (publish port 80: -p 80:80)"
      _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $(key c 'loudflare') + letsencrypt"  "Let's Encrypt cert, validated via Cloudflare DNS-01 (no port 80) — needs a Zone:DNS:Edit+Read token + email"
      _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $(key 15 'years cloudflare')"        "Cloudflare Origin certificate, 15 years — ONLY valid behind Cloudflare's proxy (orange cloud); needs an API token (Zone → SSL and Certificates → Edit)"
      _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $(key s 'elfsigned')"                "OK for testing"
    elif [ "$_ip_public" = yes ]; then
      _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $_lip"                              "Trusted Let's Encrypt cert for this IP — short-lived (~6 days), auto-renews every 12h (publish :80 -p 80:80, direct/grey-cloud IP)"
      _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $(key s 'elfsigned')"                "Self-signed — the browser warns once (zero-maintenance, no port 80)"
    else
      _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $_ss"                                "Self-signed cert — the browser warns once (the realistic choice for an IP)"
    fi
    _tn=$((_tn+1)); menu "$(col "$C_GREY" "[$_tn]") $(keyg n 'one')"                     "plain HTTP — only behind a tunnel/reverse-proxy that terminates TLS"
    [ "$_url_is_domain" = yes ] || [ "$_ip_public" = yes ] || sub "Let's Encrypt needs a public domain or public IP — hidden because $(b "$PANEL_DOMAIN") is private / not routable."
    ask_choice "Select TLS certificate (number, letter or name)" "$_def" TLS "$_opts"
    if [ "$_ip_public" = yes ]; then   # on an IP menu every letsencrypt alias means the IP cert
      case "$TLS" in r) TLS=reuse;; l|ip|lip|letsencrypt|letsencrypt-ip) TLS=letsencrypt-ip;; s|selfsigned) TLS=selfsigned;; n|none) TLS=none;; esac
    else
      case "$TLS" in r) TLS=reuse;; l) TLS=letsencrypt;; c|cf) TLS=cloudflare;; 15|15years|15cf) TLS=cf15;; s|self) TLS=selfsigned;; n|none) TLS=none;; esac
    fi
    # letsencrypt('-ip') HTTP-01 needs host :80 — if it's taken (nginx/apache), make the user switch or force
    if { [ "$TLS" = letsencrypt ] || [ "$TLS" = letsencrypt-ip ]; } && ! $DRYRUN && have ss && [ -n "$(ss -lntH 'sport = :80' 2>/dev/null)" ]; then
      _w80="$(ss -lntpH 'sport = :80' 2>/dev/null | grep -oE '"[^"]+"' | head -1 | tr -d '"' || true)"
      echo; warn "letsencrypt needs host port $(col "$C_YEL" ':80') for HTTP-01, but it's in use${_w80:+ (by $(col "$C_YEL" "$_w80"))} — issuance will fail"
      echo "    :80 is fixed by ACME (independent of the panel's port). Pick $(key c 'loudflare') (DNS-01), $(key 15 'years cloudflare'), $(key s 'elfsigned'), or $(key n 'one') — or $(bb force) to keep letsencrypt."
      printf '  Select another certificate, or type %s: ' "$(bb force)"
      read -r _ans80 2>/dev/null </dev/tty || _ans80=force
      _ans80="$(printf '%s' "$_ans80" | tr -d '[:space:]')"
      [ "$_ans80" = force ] && break
      case " $_opts " in *" $_ans80 "*) TLS="$_ans80";; *) TLS=""; warn "enter one of: $_opts — or 'force'";; esac
      continue
    fi
    case "$TLS" in
      letsencrypt|cloudflare|cf15)   # domain-only — warn + re-ask if the URL isn't a domain
        if [ "$_url_is_domain" != yes ]; then echo; warn "$(b "$TLS") needs a domain (FQDN), but the panel URL ($(b "$PANEL_DOMAIN")) is an IP. Pick $([ "$_ip_public" = yes ] && printf 'letsencrypt-ip, ')selfsigned or none, or re-run with a domain URL."; echo; TLS=""; continue; fi ;;
      letsencrypt-ip)                # public-IP-only — warn + re-ask otherwise
        if [ "$_ip_public" != yes ]; then echo; warn "$(b letsencrypt-ip) needs a public IP, but the panel URL is $(b "$PANEL_DOMAIN"). Pick $([ "$_url_is_domain" = yes ] && printf 'letsencrypt, ')selfsigned or none."; echo; TLS=""; continue; fi ;;
    esac
    break
  done
  if [ "$TLS" = reuse ]; then REUSE_TLS=yes; TLS="${EXIST_TLS:-selfsigned}"; ok "reusing the existing certificate (TLS mode: $(b "$TLS"))"; return 0; fi
  case "$TLS" in
    letsencrypt) ask_valid "ACME account email" "$ACME_EMAIL" ACME_EMAIL v_email "enter a valid email, e.g. you@example.com"
                 warn "letsencrypt validates over HTTP-01 — publish port 80 to the panel container (compose maps 80:80)";;
    letsencrypt-ip) warn "letsencrypt-ip issues a $(b 'short-lived (~6 day)') cert for the IP $(b "$PANEL_DOMAIN") — the container renews it every 12h; if renewal is down ~6 days the cert expires."
                 warn "Needs host port 80 published (the installer maps 80:80) and the IP reachable directly (grey-cloud / no proxy)."
                 ask_valid "ACME account email" "$ACME_EMAIL" ACME_EMAIL v_email "enter a valid email, e.g. you@example.com";;
    cloudflare)  ask_valid "Cloudflare API token (needs Zone:DNS:Edit + Zone:Read)" "$CF_TOKEN" CF_TOKEN v_cftoken "the API token can't be empty"
                 ask_valid "ACME account email" "$ACME_EMAIL" ACME_EMAIL v_email "enter a valid email, e.g. you@example.com";;
    cf15)        warn "cf15 issues a Cloudflare Origin cert — it is ONLY trusted behind Cloudflare's proxy (orange cloud)."
                 if ! v_cfport "$PANEL_PORT"; then
                   warn "port $(col "$C_YEL" "$PANEL_PORT") is NOT one Cloudflare's proxy forwards (only 443, 2053, 2083, 2087, 2096, 8443) —"
                   warn "the panel would be unreachable through the orange cloud. Use one of those ports (or Cloudflare Spectrum), or grey-cloud the record and accept an untrusted direct cert."
                 fi
                 ask_valid "Cloudflare API token (Zone → SSL and Certificates → Edit)" "$CF_ORIGIN_TOKEN" CF_ORIGIN_TOKEN v_cforigin "paste an API token — the legacy Origin CA Key is deprecated (sunset 2026-09-30)";;
    none)        # reverse proxy: keep the containers on loopback so ONLY the operator's own nginx/Caddy reaches them
                 PANEL_BIND=127.0.0.1; SUB_BIND=127.0.0.1; SUB_TRUST_XFF=1
                 { [ "${PANEL_PORT_EXPLICIT:-no}" != yes ] && [ "${PANEL_PORT:-443}" = 443 ]; } && PANEL_PORT=8088   # don't grab host :443 — your proxy needs it
                 sub "TLS=none → panel :$PANEL_PORT + swg-sub :$SUB_PORT bind 127.0.0.1; run your own reverse proxy (configs printed at the end)."
                 [ -z "$SUB_DOMAIN" ] && ask "Subscription page hostname for the reverse-proxy config (blank to fill in later)" "" SUB_DOMAIN;;
  esac
  return 0
}
ask_node_conn(){     # NODE SETUP — panel connection (endpoint moved into the per-interface wg/awg step)
  # Panel connection — normally supplied by the install command's -host / -key flags.
  # On a re-install, ALWAYS re-prompt the URL + TLS (the panel may have moved / changed cert) with the
  # current value as the default; the TOKEN is reused silently (re-typing it is useless). Mirrors bare-metal.
  # CONVERT (the master's node step, or a standalone node convert): convert.sh passes the panel URL/token/verify
  # already — use them as-is, no prompts (a convert isn't a re-install; the operator confirmed at the convert's
  # proceed step). Keeps the master's node step identical to a standalone node convert (no extra re-install prompts).
  if [ -n "${SWG_CONVERT_DIR:-}" ] && [ -n "${PANEL_URL:-}" ]; then
    case "$PANEL_URL" in https://*|http://*) ;; *) PANEL_URL="https://$PANEL_URL";; esac
    [ -z "${TLS_VERIFY:-}" ] && TLS_VERIFY=no
    # a convert should STILL let you set this box's name in the panel (mirrors bare-metal install-host/master) —
    # fetch its current name + offer to change it; the rename is pushed via /api/node/rename below if changed.
    local _ins=""; [ "$TLS_VERIFY" = yes ] || _ins="-k"; local _cur
    _cur="$(auth_curl "${NODE_TOKEN:-}" -fsS $_ins --max-time 8 "${PANEL_URL%/}/api/node/whoami" 2>/dev/null | python3 -c 'import json,sys;print((json.load(sys.stdin).get("data") or {}).get("name") or "")' 2>/dev/null || true)"
    step "Node name for THIS box"
    ask_valid "Node name for THIS box" "${_cur:-$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo node)}" PUSH_NAME v_name "1–40 chars: letters, digits, - or _"
    [ "$PUSH_NAME" = "$_cur" ] && PUSH_NAME=""
    return 0
  fi
  if [ "$EXISTING_DOCKER" = yes ]; then
    local _exurl="$PANEL_URL" _extls="$TLS_VERIFY"; PANEL_URL=""; TLS_VERIFY=""
    ask_valid "Panel URL (https://host[/subpath])" "$_exurl" PANEL_URL v_httpsurl "enter the panel's https:// URL (pass -host to skip this)"
    case "$PANEL_URL" in https://*) ;; http://*) warn "panel URL is http:// — the key would travel in clear. Continue only if you know why.";; *) PANEL_URL="https://$PANEL_URL";; esac   # no scheme → default https://
    TLS_VERIFY="$(ask_yn_tty "Verify the panel's TLS certificate? (answer no if the panel uses a self-signed cert)" "$([ "$_extls" = yes ] && echo y || echo n)")"
    # offer to change the box name shown in the panel (default = its current name); push via /api/node/rename
    local _ins=""; [ "$TLS_VERIFY" = yes ] || _ins="-k"; local _cur
    _cur="$(auth_curl "${NODE_TOKEN:-}" -fsS $_ins --max-time 8 "${PANEL_URL%/}/api/node/whoami" 2>/dev/null | python3 -c 'import json,sys;print((json.load(sys.stdin).get("data") or {}).get("name") or "")' 2>/dev/null || true)"
    if [ -n "$_cur" ]; then step "Box name on the panel"; ask_valid "Node name (shown in the panel)" "$_cur" PUSH_NAME v_name "1–40 chars: letters, digits, - or _"; [ "$PUSH_NAME" = "$_cur" ] && PUSH_NAME=""; fi
    return 0
  fi
  ask_valid "Panel URL (https://host[/subpath])" "$PANEL_URL" PANEL_URL v_httpsurl "enter the panel's https:// URL (pass -host to skip this)"
  ask_secret "Node enrollment key (from the Nodes screen)" "$NODE_TOKEN" NODE_TOKEN v_token "paste the key from Nodes → Add node (pass -key to skip this)"
  case "$PANEL_URL" in https://*) ;; *) warn "panel URL is not https:// — the key would travel in clear. Continue only if you know why.";; esac
  if [ -z "$TLS_VERIFY" ] && [ -z "${TLS_FINGERPRINT:-}" ]; then
    # Verify by DEFAULT (secure); auto-detect a self-signed panel so a fresh node never fails its first sync.
    local _tls_def=y _rc
    if [ -n "$PANEL_URL" ]; then
      _rc=0; curl -sS --max-time 6 -o /dev/null "${PANEL_URL%/}/healthz" 2>/dev/null || _rc=$?   # capture rc WITHOUT letting set -e abort — a self-signed/unreachable panel (the case this block exists for) makes curl exit non-zero
      # only a genuine cert-verification failure (60/51) with -k then working means self-signed; a transient
      # error keeps the secure default (verify) rather than silently downgrading a real-CA panel.
      if { [ "$_rc" = 60 ] || [ "$_rc" = 51 ]; } && curl -sSk --max-time 6 -o /dev/null "${PANEL_URL%/}/healthz" 2>/dev/null; then
        _tls_def=n
      fi
    fi
    # SELF-SIGNED → PIN the panel cert (TOFU) so the sync is MITM-protected by default, instead of unverified.
    # Real-CA panels keep CA verification (a pin would break on cert renewal).
    if [ "$_tls_def" = n ] && [ -n "$PANEL_URL" ] && ! $DRYRUN; then
      local _fp; _fp="$(_docker_panel_fp "$PANEL_URL")"
      if [ -n "$_fp" ]; then
        TLS_FINGERPRINT="$_fp"; TLS_VERIFY=no
        info "Panel cert is self-signed — pinning it (sha256 ${_fp:0:16}…) so a man-in-the-middle can't impersonate the panel."
      fi
    fi
    [ -z "${TLS_FINGERPRINT:-}" ] && TLS_VERIFY="$(ask_yn_tty "Verify the panel's TLS certificate? (auto-detected default: $([ "$_tls_def" = y ] && echo yes || echo 'no — self-signed'))" "$_tls_def")"
  fi
  return 0
}
# subnet (10.x.y.0/24) -> the server's interface address (10.x.y.1/24). Accepts either form as input.
server_addr(){ python3 -c "import ipaddress,sys;n=ipaddress.ip_network(sys.argv[1],strict=False);print('%s/%d'%(next(n.hosts()),n.prefixlen))" "$1" 2>/dev/null || echo "$1"; }
net_of(){      python3 -c "import ipaddress,sys;print(ipaddress.ip_network(sys.argv[1],strict=False))" "$1" 2>/dev/null || echo "$1"; }
# tunnel subnets already used on this node (persisted node-confs + queued NODE_IFACES) → so a new interface's
# default + validator never collide with an existing one (e.g. offering 10.13 when wg4 already has it).
node_used_subnets(){ local c a e _ifs
  if [ -d "$INSTALL_DIR/data/node-confs" ]; then
    for c in "$INSTALL_DIR/data/node-confs/"*.conf; do [ -f "$c" ] || continue
      a="$(sed -n 's/^[[:space:]]*Address[[:space:]]*=[[:space:]]*\([0-9./]*\).*/\1/p' "$c" 2>/dev/null | head -1)"; [ -n "$a" ] && net_of "$a"; done
  fi
  if [ -n "${NODE_IFACES:-}" ]; then IFS=',' read -ra _ifs <<< "$NODE_IFACES"
    for e in "${_ifs[@]}"; do a="$(printf '%s' "$e" | cut -d: -f3)"; [ -n "$a" ] && net_of "$a"; done
  fi; }
subnet_used(){ local s; s="$(net_of "$1")"; node_used_subnets | grep -qx "$s"; }
# default subnet = (highest used 10.X.0.0/24 second-octet)+1, then the next free above it (10.8 if none).
next_free_subnet(){ local hi=7 s o; while read -r s; do [ -n "$s" ] || continue; o="$(printf '%s' "$s" | cut -d. -f2)"; case "$o" in ''|*[!0-9]*) :;; *) [ "$o" -gt "$hi" ] && hi="$o";; esac; done <<< "$(node_used_subnets)"
  o=$((hi+1)); while [ "$o" -lt 255 ] && subnet_used "10.$o.0.0/24"; do o=$((o+1)); done; echo "10.$o.0.0/24"; }
v_subnet_free(){ v_subnet "$1" || return 1; subnet_used "$1" && return 1; return 0; }
# default interface index = (highest numeric suffix across existing names)+1 — so a new iface increments past the highest (awg3,wg4 → 5).
iface_next_index(){ local hi=-1 n s; while read -r n; do [ -n "$n" ] || continue; s="${n##*[!0-9]}"; case "$s" in ''|*[!0-9]*) :;; *) [ "$s" -gt "$hi" ] && hi="$s";; esac; done <<< "$(taken_iface_names)"; echo $((hi+1)); }
fwd_ifaces(){ local cp="${1##*:}" nm pt pr out=""; while read -r nm pt pr; do [ -n "$nm" ] && [ "$pt" = "$cp" ] && out="${out:+$out }$nm"; done <<< "$(node_iface_rows)"; printf '%s' "$out"; }   # interface(s) a turn-proxy's ip:port forwards to (matched by REAL listen port across node-confs + this session)
ask_node_iface(){    # WG/AWG interface (container-managed) + its endpoint; mirrors bare-metal
  step "WireGuard / AmneziaWG setup" "(this interface has its own endpoint IP)"
  echo
  echo "      The interface is brought up INSIDE the swg-node container from these values."
  echo "      Need several interfaces (each with its own endpoint) or custom AmneziaWG obfuscation?"
  echo "      set $(b NODE_IFACES) in $INSTALL_DIR/.env, or mount $(b /etc/swg-node/*.conf) (see $INSTALL_DIR/docker-compose.yml)."
  echo
  local _proto def_if d_if d_port d_addr d_ep
  d_if="$NODE_IFACE"; d_port="$NODE_LISTEN_PORT"; d_addr="$NODE_ADDRESS"; d_ep="${NODE_ENDPOINT:-$(detect_public_ip)}"
  menu "$(col "$C_BLUE" '[1]') $(keyd a 'mneziawg (default)')" "WireGuard with AmneziaWG obfuscation. Runs on the userspace amneziawg-go datapath built into the swg-node container."
  menu "$(col "$C_BLUE" '[2]') $(key w 'ireguard')"            "Plain WireGuard — no obfuscation, lowest overhead. Also runs via the container's amneziawg-go datapath (Amnezia params off)."
  ask_choice "Select the protocol you want to create (number, letter or name)" "a" _proto "a w awg wg amneziawg wireguard"
  case "$_proto" in w|wg|wireguard) NODE_PLAIN_WG=yes; def_if=wg0;; *) NODE_PLAIN_WG=no; def_if=awg0;; esac
  case "$d_if" in ""|awg0|wg0) d_if="$def_if";; esac        # default name follows the protocol
  NODE_IFACE="";       ask_valid "Interface name" "$d_if" NODE_IFACE v_iface "1–15 chars: letters, digits, - or _"
  NODE_LISTEN_PORT=""; ask_valid "Listen port" "$d_port" NODE_LISTEN_PORT v_freeport "port 1–65535 and free (not already in use)"
  local _sub="";       ask_valid "Tunnel subnet (CIDR; server takes the first host)" "$(net_of "${d_addr:-10.8.0.0/24}")" _sub v_subnet "enter a CIDR, e.g. 10.8.0.0/24"
  NODE_ADDRESS="$(server_addr "$_sub")"              # the server's interface address (.1), derived from the subnet
  NODE_ENDPOINT="$d_ep"                              # auto endpoint clients dial — public IP/host (change it later in the panel)
  echo "    Used $(bb "$NODE_ENDPOINT") endpoint IP for $(col "$C_GREEN" "$NODE_IFACE")"
  return 0
}
# current interface names for this docker node — persisted confs (./data/node-confs) ∪ the .env spec
current_node_ifaces(){
  local seen=" " n e OIFS c
  { if [ -d "$INSTALL_DIR/data/node-confs" ]; then
    for c in "$INSTALL_DIR/data/node-confs/"*.conf; do [ -f "$c" ] || continue
      n="$(basename "$c" .conf)"; case "$seen" in *" $n "*) : ;; *) echo "$n"; seen="$seen$n ";; esac; done
  fi
  if [ -n "$NODE_IFACES" ]; then OIFS="$IFS"; IFS=','      # a real .env spec, or interfaces added this run
    for e in $NODE_IFACES; do IFS="$OIFS"; n="${e%%:*}"
      case "$seen" in *" $n "*) : ;; *) [ -n "$n" ] && { echo "$n"; seen="$seen$n "; };; esac; IFS=','; done; IFS="$OIFS"
  elif [ "$EXISTING_DOCKER" = yes ] && [ -n "$NODE_IFACE" ] && [ "$seen" = " " ]; then   # only when NO real conf is on disk — else NODE_IFACE is just the install default (a convert/master with migrated confs would otherwise list a ghost awg0)
    case "$seen" in *" $NODE_IFACE "*) : ;; *) echo "$NODE_IFACE";; esac; fi
  } | drop_sys_ifaces   # never present panel-managed mesh-link (swg_*) interfaces
}
# EVERY interface NAME already present or queued on this box: node confs + queued spec (current_node_ifaces),
# live wg/awg ifaces, a co-located bare-metal node, and any /etc/amnezia//etc/wireguard conf. A new
# interface's default (and a typed name) is checked against this so it never collides with one that's
# already there, available to onboard, or queued this run.
taken_iface_names(){
  { current_node_ifaces; host_wg_ifaces; bm_node_ifaces
    { [ -d /etc/amnezia ] && find /etc/amnezia -maxdepth 3 -type f -name '*.conf' 2>/dev/null
      printf '%s\n' /etc/wireguard/*.conf "$INSTALL_DIR"/data/node-confs/*.conf
    } | while read -r c; do [ -f "$c" ] && basename "$c" .conf; done
  } 2>/dev/null | sort -u || true   # must end 0 (set -euo pipefail): a non-file glob makes the inner while exit 1
}
v_iface_free(){ v_iface "$1" || return 1; if taken_iface_names | grep -qx "$1"; then return 1; fi; return 0; }   # valid name AND not already taken
# add one interface to NODE_IFACES (seeding the single bootstrap into the list first, so the entrypoint
# — which ignores NODE_IFACE once NODE_IFACES is set — doesn't drop it).
add_node_iface(){
  local _proto plain base i name port addr ep nx taken
  if [ "$EXISTING_DOCKER" = yes ] && [ -z "$NODE_IFACES" ] && [ -n "$NODE_IFACE" ] && ! ls "$INSTALL_DIR/data/node-confs/"*.conf >/dev/null 2>&1; then   # promote an existing single bootstrap into the list — but only if there are NO migrated confs (else NODE_IFACE is just the default → a ghost)
    local pr=""; [ "${NODE_PLAIN_WG:-}" = yes ] && pr=wg
    NODE_IFACES="${NODE_IFACE}:${NODE_LISTEN_PORT:-51820}:${NODE_ADDRESS:-10.8.0.1/24}:${pr}:${NODE_ENDPOINT}"
  fi
  nx=$(current_node_ifaces | grep -c . || true)                 # offset defaults so a 2nd/3rd iface doesn't collide (grep -c exits 1 on empty → guard set -e)
  menu "$(col "$C_BLUE" '[1]') $(keyd a 'mneziawg (default)')" "WireGuard with AmneziaWG obfuscation. Runs on the userspace amneziawg-go datapath built into the swg-node container."
  menu "$(col "$C_BLUE" '[2]') $(key w 'ireguard')"            "Plain WireGuard — no obfuscation, lowest overhead. Also runs via the container's amneziawg-go datapath (Amnezia params off)."
  ask_choice "Select the protocol you want to create (number, letter or name)" "a" _proto "a w awg wg amneziawg wireguard"
  case "$_proto" in w|wg|wireguard) plain=wg;; *) plain="";; esac
  taken="$(taken_iface_names)"   # all names already on the box (computed once)
  [ "$plain" = wg ] && base=wg || base=awg; i=$(iface_next_index); while printf '%s\n' "$taken" | grep -qx "$base$i"; do i=$((i+1)); done
  ask_valid "Interface name" "$base$i" name v_iface_free "1–15 chars (letters, digits, - or _) and not already used"
  ask_valid "Listen port" "$(iface_default_port)" port v_freeport "port 1–65535 and free (not already in use)"
  local _sub=""; ask_valid "Tunnel subnet (CIDR; server takes the first host)" "$(next_free_subnet)" _sub v_subnet_free "a CIDR not already used, e.g. 10.8.0.0/24"; addr="$(server_addr "$_sub")"
  ep="${NODE_ENDPOINT:-$(detect_public_ip)}"       # auto endpoint clients dial — public IP/host (change it later in the panel)
  echo "    Used $(bb "$ep") endpoint IP for $(col "$C_GREEN" "$name")"
  [ -n "$NODE_ENDPOINT" ] || NODE_ENDPOINT="$ep"   # the node-level endpoint (required by compose) — seed from the first interface
  NODE_IFACES="${NODE_IFACES:+$NODE_IFACES,}${name}:${port}:${addr}:${plain}:${ep}"
  ok "queued interface $(col "$C_GREEN" "$name") — created on the node's next start"
}
# ── interface picker helpers ──────────────────────────────────────────────
host_wg_ifaces(){   # live wg/awg interface NAMES on the host (any owner) — excludes panel-managed mesh links
  ip -o link show 2>/dev/null | sed -n 's/^[0-9]\{1,\}: \([^:@]*\).*/\1/p' | while read -r d; do
    [ "$d" = lo ] && continue
    is_sys_iface "$d" && continue
    ip -d link show "$d" 2>/dev/null | grep -qE 'amneziawg|wireguard' && echo "$d"
  done
}
etc_awg_conf(){     # echo the /etc/amnezia conf for an interface (ANY subdir — users install in odd places); empty if none
  [ -f "/etc/amnezia/amneziawg/$1.conf" ] && { echo "/etc/amnezia/amneziawg/$1.conf"; return 0; }
  [ -d /etc/amnezia ] && find /etc/amnezia -maxdepth 3 -type f -name "$1.conf" 2>/dev/null | head -1
}
etc_wg_conf(){ [ -f "/etc/wireguard/$1.conf" ] && echo "/etc/wireguard/$1.conf"; }
find_iface_conf(){  # echo the .conf path for an interface (docker data dir + the default wg/awg dirs); empty if none
  local n="$1" p
  [ -f "$INSTALL_DIR/data/node-confs/$n.conf" ] && { echo "$INSTALL_DIR/data/node-confs/$n.conf"; return 0; }
  p="$(etc_awg_conf "$n")"; [ -n "$p" ] && { echo "$p"; return 0; }
  p="$(etc_wg_conf "$n")";  [ -n "$p" ] && { echo "$p"; return 0; }
  return 0   # no conf found → empty output + success (the trailing test would otherwise return non-zero)
}
is_kernel_iface(){  # true if backed by a kernel/host unit or an /etc conf (NOT just a docker-data conf) —
  [ -n "$(etc_awg_conf "$1")" ] && return 0   # i.e. it runs on the kernel here, not in a container
  [ -n "$(etc_wg_conf "$1")" ] && return 0
  systemctl is-enabled "awg-quick@$1" >/dev/null 2>&1 && return 0
  systemctl is-enabled "wg-quick@$1"  >/dev/null 2>&1 && return 0
  return 1
}
kern_label(){       # human label of the kernel service an interface currently runs as
  if   [ -n "$(etc_awg_conf "$1")" ]; then echo "kernel AmneziaWG (awg-quick@$1)"
  elif [ -n "$(etc_wg_conf "$1")" ];  then echo "kernel WireGuard (wg-quick@$1)"
  else echo "the kernel datapath"; fi
}
bm_node_ifaces(){   # interfaces a co-located BARE-METAL node manages (from its agent config) — excludes mesh links
  [ -f /etc/swg-agent/config.json ] || return 0
  python3 - <<'PY' 2>/dev/null | drop_sys_ifaces || true
import json
try:
    for n in json.load(open("/etc/swg-agent/config.json")).get("interfaces", {}): print(n)
except Exception: pass
PY
}
_in(){ case " $2 " in *" $1 "*) return 0;; *) return 1;; esac; }
onboard_iface(){    # bring an interface under this docker node: import its .conf into ./data/node-confs
  local n="$1" src kconf="" dest                       # NB: don't reference $n in the same `local` (set -u)
  is_sys_iface "$n" && { warn "'$n' is a panel-managed mesh link — not a user interface; skipping"; return 0; }
  dest="$INSTALL_DIR/data/node-confs/$n.conf"
  # prefer a kernel/host conf as the source — so a migration also tears the kernel side down
  kconf="$(etc_awg_conf "$n")"; [ -n "$kconf" ] || kconf="$(etc_wg_conf "$n")"
  src="${kconf:-$(find_iface_conf "$n")}"
  [ -n "$src" ] || { warn "no .conf found for '$n' (orphan interface — no keys to adopt); skipping"; return 1; }
  run mkdir -p "$INSTALL_DIR/data/node-confs"
  # copy the conf WITHOUT the host PostUp/PostDown NAT hooks — inside the swg-node container those
  # iptables rules (bound to the host's WAN) fail and break `awg-quick up`, leaving the iface DOWN.
  # The container sets up its own NAT (node-entrypoint). Keys + Amnezia params are preserved.
  if [ "$src" != "$dest" ]; then
    if $DRYRUN; then echo "    [skip] import $src → $dest (strip host NAT hooks)"
    else grep -viE '^[[:space:]]*Post(Up|Down)[[:space:]]*=' "$src" > "$dest"; chmod 600 "$dest"; fi
  fi
  $DRYRUN || { grep -q '^#swg:onboarded' "$dest" 2>/dev/null || sed -i '1i #swg:onboarded' "$dest" 2>/dev/null || true; }   # add-only: swg-noded keeps the orphan's existing peers
  if [ -n "$kconf" ]; then          # MIGRATION: take the interface OFF the kernel/host side so its name
    run awg-quick down "$n" 2>/dev/null || true   # doesn't collide with the container (host networking)
    run wg-quick  down "$n" 2>/dev/null || true
    run systemctl disable --now "awg-quick@$n" 2>/dev/null || true
    run systemctl disable --now "wg-quick@$n"  2>/dev/null || true
    if _in "$n" "$(bm_node_ifaces)"; then          # also detach from a co-located bare-metal swg node
      $DRYRUN || python3 - "$n" <<'PY' 2>/dev/null || true
import json,sys
p="/etc/swg-agent/config.json"
try:
    d=json.load(open(p)); d.get("interfaces",{}).pop(sys.argv[1],None); json.dump(d,open(p,"w"),indent=2)
except Exception: pass
PY
    fi
    # move the kernel conf aside (not delete) so the unit can't re-create it on boot — recoverable
    if $DRYRUN; then echo "    [skip] mv $kconf $kconf.bak (off the kernel)"
    else mv -f "$kconf" "$kconf.bak" 2>/dev/null || true; fi
  fi
  ok "onboarded $(col "$C_GREEN" "$n")"
}
# bare→docker CONVERT: migrate THIS box's bare interfaces (kernel awg/wg) into the docker node's conf dir, in the
# NODE STAGE — the mirror of migrate_baremetal_turns. Lists them, asks "Transfer? (Y/n)", copy-firsts (strips host
# NAT — the container does its own; keys preserved). The bare interfaces keep serving until the atomic switch
# (lc_teardown_baremetal) brings them down. Decline ⇒ left on bare-metal (start empty / add fresh in the loop).
migrate_baremetal_ifaces(){
  [ "${SWG_CONVERT_DIR:-}" = convert-docker ] || return 0
  # a CONVERT's docker conf dir must hold ONLY this run's migrated set — wipe stale confs a previous convert
  # left in a reused dir, else current_node_ifaces resurrects them as a ghost "already on this node" entry.
  [ -d "$INSTALL_DIR/data/node-confs" ] && rm -f "$INSTALL_DIR/data/node-confs/"*.conf 2>/dev/null || true
  local ifs n c pr lp addr src dest
  ifs="$(for c in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf; do [ -f "$c" ] && basename "$c" .conf; done 2>/dev/null | sort -u || true)" || true; ifs="$(echo $ifs)"
  [ -n "$ifs" ] || return 0
  echo; info "Interfaces to migrate from the bare-metal node:"; echo
  _mep="${NODE_ENDPOINT:-}"; case "$_mep" in 127.*|"") _mep="$(detect_public_ip 2>/dev/null || true)";; esac   # public endpoint clients dial (this box) — show it like the "already on this node" list below
  for n in $ifs; do
    c="/etc/amnezia/amneziawg/$n.conf"; pr=AmneziaWG; [ -f "$c" ] || { c="/etc/wireguard/$n.conf"; pr=WireGuard; }
    lp="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$c" | head -1)"
    addr="$(sed -n 's/^[[:space:]]*Address[[:space:]]*=[[:space:]]*\([0-9./]*\).*/\1/p' "$c" | head -1)"
    printf '    %s%-10s%s %-9s  %s:%-6s %s\n' "$C_GREEN" "$n" "$RESET" "$pr" "${_mep:-?}" "${lp:-?}" "${addr:-?}"
  done
  echo
  [ "$(ask_yn_tty "Transfer these interfaces into the docker node?" y)" = yes ] || { info "  left on bare-metal — they come down at the switch; create fresh ones below if you want"; echo; return 0; }
  mkdir -p "$INSTALL_DIR/data/node-confs"
  for n in $ifs; do
    src="/etc/amnezia/amneziawg/$n.conf"; [ -f "$src" ] || src="/etc/wireguard/$n.conf"; [ -f "$src" ] || continue
    dest="$INSTALL_DIR/data/node-confs/$n.conf"
    grep -viE '^[[:space:]]*Post(Up|Down)[[:space:]]*=' "$src" > "$dest" 2>/dev/null && chmod 600 "$dest"   # strip host NAT (container NATs); keys preserved
    echo "    $(b "$n") → data/node-confs (key preserved; bare interface comes down at the switch)"
  done
  if [ -d /var/lib/swg-noded/iface-keys ]; then mkdir -p "$INSTALL_DIR/data/node/iface-keys"; cp -a /var/lib/swg-noded/iface-keys/. "$INSTALL_DIR/data/node/iface-keys/" 2>/dev/null || true; fi
  echo
}
# wg/awg step: pick from the host's interfaces (available / used-by-another-node) or create new
manage_node_ifaces(){
  step "WireGuard / AmneziaWG setup"
  echo
  echo "      Interfaces run inside the swg-node container; add as many as you need now, or add more"
  echo "      later from the panel (Interfaces → Load new interface). Existing ones are KEPT."
  echo
  migrate_baremetal_ifaces   # convert: Transfer? + copy-first the bare interfaces, then the loop shows them + adds more
  local mine bm cand dock kern n pick xfer kpick dpick bad yn doit
  while :; do
    mine="$(current_node_ifaces | tr '\n' ' ')" || true   # under set -euo pipefail these subs can exit non-zero
    # interfaces a co-located bare node still lists, MINUS any already on this docker node (those aren't
    # migration candidates — showing them in both "already on this node" and "bare-metal node" is confusing)
    bm="$(for n in $(bm_node_ifaces); do _in "$n" "$mine" || printf '%s ' "$n"; done)" || true
    # candidates from EVERY source: live ifaces, our docker source-of-truth dir, AND the default
    # wg/awg dirs (any /etc/amnezia subdir + /etc/wireguard) so a pre-existing user install is found.
    cand="$( { host_wg_ifaces        # live iface NAMES (already bare)
      { [ -d /etc/amnezia ] && find /etc/amnezia -maxdepth 3 -type f -name '*.conf' 2>/dev/null
        printf '%s\n' /etc/wireguard/*.conf "$INSTALL_DIR"/data/node-confs/*.conf
      } | while read -r c; do [ -f "$c" ] && basename "$c" .conf; done    # conf PATHS -> bare names
      } | sort -u | drop_sys_ifaces )" || true   # never surface the panel-managed mesh links (swg_*)
    # split the free interfaces: docker ORPHANS (left by a previous container) vs KERNEL interfaces
    # (running on the host's kernel datapath — onboarding one MOVES it off the kernel).
    dock=""; kern=""
    for n in $cand; do
      _in "$n" "$mine" && continue
      _in "$n" "$bm" && continue
      is_sys_iface "$n" && continue            # belt-and-suspenders: mesh links are never orphans/candidates
      if is_kernel_iface "$n"; then kern="$kern $n"; else dock="$dock $n"; fi
    done
    dock="$(echo $dock)"; kern="$(echo $kern)"
    [ -n "$mine" ] && { echo "  Interfaces already on this node:"; echo; for n in $mine; do iface_row "$n"; done; echo; }
    [ -n "$dock" ] && { echo "  Available orphan interfaces:"; echo; for n in $dock; do iface_row "$n"; done; echo; }
    [ -n "$kern" ] && { printf "  Existing %s interfaces:" "$(col "$C_RED" kernel)"; for n in $kern; do printf ' %s' "$(col "$C_RED" "$n")"; done; printf " %s\n" "$(col "$C_RED" '— picking one MOVES it off the kernel into this node')"; }
    [ -n "$bm" ] && { printf "  Interfaces used by the bare-metal node on this server:"; for n in $bm; do printf ' %s' "$(col "$C_RED" "$n")"; done; echo; }
    echo
    if [ -z "$dock$kern$mine$bm" ]; then            # truly nothing on this box → skip by default (panel-managed) or create one
      info "No wg / awg interfaces yet — this node can be managed entirely from the panel (Interfaces → Load new interface)."; echo
      doit="$(ask_yn_tty "Create a bootstrap interface now instead? (default: skip — add them from the panel later)" n)"
      if [ "$doit" = yes ]; then echo; add_node_iface; echo; continue; fi
      info "No bootstrap interface — this node will be managed from the panel."; break
    elif [ -n "$dock" ]; then                       # docker orphans present → onboard all / some / none
      echo "  Press $(b Enter) to onboard $(col "$C_BLUE" 'all available orphans above') and continue"
      echo "  Enter interface $(b names) (space-separated) to onboard or migrate specific ones"
      [ -n "$mine" ] && echo "  Enter $(col "$C_BLUE" done) to keep only this node's interfaces (leave the orphans)"
      printf "  Enter %s to create another interface: " "$(col "$C_BLUE" '[n]ew')"
    else                                            # no orphans (maybe kernel/bm/own) → finish or migrate
      echo "  Press $(b Enter) to finish with this node's interfaces"
      { [ -n "$kern" ] || [ -n "$bm" ]; } && echo "  Enter interface $(b names) to migrate one onto this node"
      printf "  Enter %s to create another interface: " "$(col "$C_BLUE" '[n]ew')"
    fi
    if ! read -r pick </dev/tty; then echo; warn "no interactive input — keeping current interfaces"; break; fi
    if [ -z "$(echo $pick)" ]; then                # Enter → onboard all docker orphans + proceed (kernel needs explicit confirm)
      for n in $dock; do onboard_iface "$n" || true; done
      [ -n "$(current_node_ifaces)" ] || { warn "no interfaces yet — type 'new' or name a kernel interface to migrate"; echo; continue; }
      break
    fi
    if [ "$pick" = done ]; then                     # keep only what's on the node → leave the rest alone
      [ -n "$(current_node_ifaces)" ] || { warn "this node has no interfaces yet — onboard one or type 'new'"; echo; continue; }
      break
    fi
    if [ "$pick" = new ] || [ "$pick" = n ]; then echo; add_node_iface; echo; continue; fi
    xfer=""; kpick=""; dpick=""; bad=""
    for n in $pick; do
      _in "$n" "$mine" && continue
      _in "$n" "$dock" && { dpick="$dpick $n"; continue; }
      _in "$n" "$kern" && { kpick="$kpick $n"; continue; }
      _in "$n" "$bm" && { xfer="$xfer $n"; continue; }
      bad="$bad $n"
    done
    [ -n "$bad" ] && { warn "not found:$bad — pick from the lists above, or 'new'"; echo; continue; }
    for n in $dpick; do onboard_iface "$n" || true; done           # docker orphans → straight onboard
    for n in $kpick; do                                            # kernel → per-interface migration confirm
      echo
      echo "  You are about to move $(col "$C_RED" "$n") from $(kern_label "$n") to this docker-managed node."
      echo "  It will no longer run on the kernel here ($(b 'its peers are preserved'); the conf is kept as a .bak)."
      if [ "$(ask_yn_tty "Move $n into docker?" y)" = yes ]; then onboard_iface "$n" || true; else warn "kept $n on the kernel"; fi
    done
    if [ -n "$xfer" ]; then                                        # bare-metal swg node → transfer confirm
      printf "  Are you sure you want to transfer %s to this node? (y/N): " "$(col "$C_RED" "$(echo $xfer)")"
      read -r yn </dev/tty || yn=n
      case "$yn" in [Yy]*) for n in $xfer; do onboard_iface "$n" || true; done;; *) echo; continue;; esac
    fi
    break
  done
}
ask_role(){          # role (panel entry) — master (panel + local node) or host (panel only); mirrors bare-metal
  step "Server role"
  menu "$(col "$C_BLUE" '[1]') $(keyd m 'aster (default)')" "Panel + this box also runs WG/AWG interfaces — a co-located, auto-enrolled node container"
  menu "$(col "$C_BLUE" '[2]') $(key h 'ost')"              "Panel only; WG/AWG nodes are deployed separately (run their command from the panel)"
  ask_choice "Select role (number, letter or name)" "m" ROLE "master host m h"
  case "$ROLE" in m) ROLE=master;; h) ROLE=host;; esac
}
case "$PROFILE" in
  host|master)
    [ -n "$ROLE" ] || ask_role
    [ "$ROLE" = master ] && PROFILE=master || PROFILE=host
    echo; info "DOCKER SWG PANEL SETUP"
    ask_panel_login; ask_panel_tls
    if [ "$PROFILE" = master ]; then
      PANEL_URL="https://swg-panel:8443"   # the local node reaches the panel on the compose network
      TLS_VERIFY="${TLS_VERIFY:-no}"        # local node → local panel is self-signed on the compose net
      echo; info "DOCKER SWG NODE SETUP"
      step "Node name for THIS box"
      # default to the name the PANEL currently has for this box's local node (may have been renamed in the
      # UI) — matched by verifying NODE_TOKEN against each nodes.json token_hash; else the hostname.
      _pn="$(panel_node_name_tok "$INSTALL_DIR/data/lib/nodes.json" "${NODE_TOKEN:-}")"
      ask_valid "Node name for THIS box" "${_pn:-$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo node)}" NODE_NAME v_name "1–40 chars: letters, digits, - or _"
      manage_node_ifaces
      # the node-level endpoint is required by compose; ensure it's set (kept existing interfaces only)
      [ -n "$NODE_ENDPOINT" ] || { NODE_ENDPOINT="$(detect_public_ip)"; echo "    Used $(bb "$NODE_ENDPOINT") as this node's endpoint (change it later in the panel)"; }
      # single-pass auto-enroll (mirrors bare-metal master): mint the local node's token NOW so it
      # flows into .env below; its pbkdf2 hash + nodes.json entry are written just before compose up.
      [ -n "$NODE_NAME" ]  || NODE_NAME="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo node)"
      [ -n "$NODE_TOKEN" ] || NODE_TOKEN="$(head -c18 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=')"
      AUTOENROLL=yes
    else
      NODE_TOKEN="${NODE_TOKEN:-set-in-nodes-screen}"; PANEL_URL="${PANEL_URL:-https://swg-panel:8443}"; NODE_ENDPOINT="${NODE_ENDPOINT:-$(detect_public_ip)}"   # host (panel-only) placeholder — the real public IP, not loopback, in case a node ever inherits this .env
    fi
    ;;
  node)
    echo; info "DOCKER SWG NODE SETUP"
    ask_node_conn
    manage_node_ifaces
    # the node-level endpoint is required by compose; ensure it's set (kept existing interfaces only)
    [ -n "$NODE_ENDPOINT" ] || { NODE_ENDPOINT="$(detect_public_ip)"; echo "    Used $(bb "$NODE_ENDPOINT") as this node's endpoint (change it later in the panel)"; }
    PANEL_PASSWORD="${PANEL_PASSWORD:-unused-on-node-only}"; PANEL_DOMAIN="${PANEL_DOMAIN:-localhost}"
    ;;
esac
TLS="${TLS:-selfsigned}"         # concrete value for .env (node profile never prompts for it)
TLS_VERIFY="${TLS_VERIFY:-no}"   # concrete value for .env (host profile leaves it unset)

# push a box-name change once ask_node_conn has it (the signal + traps were armed at startup, above)
if [ -n "$PUSH_NAME" ] && [ -n "${NODE_TOKEN:-}" ] && [ -n "${PANEL_URL:-}" ] && ! $DRYRUN; then
  _rin=""; [ "${TLS_VERIFY:-no}" = yes ] || _rin="-k"
  auth_curl "$NODE_TOKEN" -fsS $_rin --max-time 8 -X POST -H "Content-Type: application/json" \
    --data "$(python3 -c 'import json,sys;print(json.dumps({"name":sys.argv[1]}))' "$PUSH_NAME")" "${PANEL_URL%/}/api/node/rename" >/dev/null 2>&1 || true
fi

# ───────────────────────── ensure Docker ─────────────────────────
info "Docker"
if ! have docker; then
  info "installing Docker (get.docker.com)"; run sh -c "curl -fsSL https://get.docker.com | sh"
fi
if have docker && docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
elif have docker-compose; then COMPOSE="docker-compose"
else COMPOSE="docker compose"; $DRYRUN || warn "docker compose plugin not detected — install it if 'up' fails"; fi

# ───────────────────────── stage project ─────────────────────────
# Default pulls prebuilt images from GHCR, so only the compose file is needed on the host
# (.env is written below, data/ is created by compose). --build also stages the full build
# context and flips the compose file to build-from-source.
info "Staging project in $INSTALL_DIR"
mkdir -p "$PREFIX$INSTALL_DIR"
cp -a "$SRC/docker-compose.yml" "$PREFIX$INSTALL_DIR/" 2>/dev/null || true
if $BUILD; then
  for f in Dockerfile Dockerfile.node Dockerfile.turn .dockerignore VERSION \
           swg-panel-server swg-agent swg-noded swg-sni swg-sub swg-passwd sub.html sub.js sub.css \
           index.html app.css app.js reconcile.js turn-artifacts.js; do
    [ -e "$SRC/$f" ] && cp -a "$SRC/$f" "$PREFIX$INSTALL_DIR/" 2>/dev/null || true
  done
  [ -d "$SRC/vendor" ] && cp -a "$SRC/vendor" "$PREFIX$INSTALL_DIR/" 2>/dev/null || true
  [ -d "$SRC/docker" ] && cp -a "$SRC/docker" "$PREFIX$INSTALL_DIR/" 2>/dev/null || true
  # flip compose: comment the GHCR image: lines, uncomment the build: blocks
  sed -i -E 's@^( *)image: (ghcr.io/[^:]*/swg-(panel|node):latest)@\1# image: \2@; s@^( *)# build: \.@\1build: .@; s@^( *)# (build:)$@\1\2@; s@^( *)#   (context: \.)@\1  \2@; s@^( *)#   (dockerfile: Dockerfile.node)@\1  \2@' "$PREFIX$INSTALL_DIR/docker-compose.yml"
  ok "staged full build context (--build: images built from source)"
else
  ok "staged compose file (images pulled prebuilt from GHCR — no build context needed)"
fi

# Node datapath networking (profiles: node, master). HOST (default) = every interface port, incl.
# panel-created ones, binds directly on the host: no publishing, best UDP throughput. BRIDGE = isolated,
# but each created interface's UDP port must be published in docker-compose.yml. host net disallows
# per-container ports/sysctls (disabled below + ip_forward set on the host); the master's node also
# leaves the compose network, so it reaches the panel over loopback instead of the swg-panel name.
if [ "$PROFILE" = node ] || [ "$PROFILE" = master ]; then
  if [ -z "$NODE_NET" ]; then
    step "Networking mode"; echo
    menu "$(col "$C_BLUE" '[1]') $(keyd h 'ost (default)')" "Every interface port (incl. ones created from the panel) is reachable automatically, no publishing, best throughput. Recommended for a dedicated VPN box."
    menu "$(col "$C_BLUE" '[2]') $(key b 'ridge')"          "Isolated; you must publish each created interface's UDP port in $INSTALL_DIR/docker-compose.yml. Use only if host networking isn't an option."
    ask_choice "Select networking (number, letter or name)" "h" NODE_NET "host bridge h b"
    case "$NODE_NET" in h) NODE_NET=host;; b) NODE_NET=bridge;; esac
  fi
  case "$NODE_NET" in host|bridge) ;; *) NODE_NET=host;; esac
  if [ "$PROFILE" = master ]; then       # the master's node reaches the local panel over the STABLE plain-HTTP loopback
    # The panel always publishes a dedicated internal plain-HTTP port (PANEL_LOCAL_PORT) at ROOT that a public
    # TLS/port/domain/path change NEVER moves — so the co-located node can't strand across an address change.
    if [ "$NODE_NET" = host ]; then PANEL_URL="http://127.0.0.1:${PANEL_LOCAL_PORT:-8088}"   # host-published stable loopback (root, plain HTTP)
    else PANEL_URL="http://swg-panel:${PANEL_LOCAL_PORT:-8088}"; fi                            # compose-network stable internal port (root, plain HTTP)
    TLS_VERIFY="${TLS_VERIFY:-no}"     # loopback plain HTTP → nothing to verify
  fi
  if [ "$NODE_NET" = host ]; then
    if $DRYRUN; then echo "    [skip] enable host networking for the node service + host ip_forward"
    else
      python3 - "$PREFIX$INSTALL_DIR/docker-compose.yml" <<'PYHOST'
import sys, re
p = sys.argv[1]; lines = open(p).read().splitlines(); out = []; in_node = False
for ln in lines:
    if re.match(r'^  swg-node:\s*$', ln): in_node = True
    elif in_node and re.match(r'^  \S', ln): in_node = False
    if in_node:
        if re.match(r'^    container_name: swg-node\s*$', ln):
            out += [ln, '    network_mode: host        # node datapath: every interface port is on the host']; continue
        if re.match(r'^    (ports|sysctls):\s*$', ln):
            out.append('    # ' + ln.strip() + '   (disabled — host networking)'); continue
        if re.match(r'^      - ("?\$\{NODE_LISTEN_PORT|net\.ipv4\.)', ln):   # any net.ipv4.* sysctl (ip_forward, route_localnet, …)
            out.append('    #   ' + ln.strip()); continue
    out.append(ln)
open(p, 'w').write('\n'.join(out) + '\n')
PYHOST
      printf 'net.ipv4.ip_forward = 1\nnet.ipv4.conf.all.route_localnet = 1\n' > /etc/sysctl.d/99-swg-node.conf 2>/dev/null || true
      sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
      sysctl -w net.ipv4.conf.all.route_localnet=1 >/dev/null 2>&1 || true   # host-net node: Force-DNS needs loopback DNAT (container can't set this itself)
      [ "$PROFILE" = master ] && ok "host networking — every port reachable; node → panel via 127.0.0.1:${PANEL_PORT:-443}" \
                             || ok "host networking — every interface port reachable, no per-port publishing"
    fi
  else
    ok "bridge networking — publish each created interface's UDP port in $INSTALL_DIR/docker-compose.yml, then '$COMPOSE --profile $PROFILE up -d'"
  fi

  # ── turn-proxy management — how this node's host turn-proxy services are managed ──
  if [ -z "$TURN_MANAGE" ]; then
    step "Turn proxies management"; echo
    menu "$(col "$C_BLUE" '[1]') $(keyd p 'anel (default)')" "Manage turn-proxies (edit listen/connect/keys, restart) from the panel — they run as
      sibling CONTAINERS (swg-turn-*), not host services. Mounts the Docker socket into the node container, which gives it
      ROOT-EQUIVALENT host access (it manages sibling containers). Only enable if you trust the panel and this box."
    menu "$(col "$C_BLUE" '[2]') $(key m 'anual')"           "Turn-proxies are managed on this server by hand — no socket is mounted."
    ask_choice "Select turn-proxy management (number, letter or name)" "p" TURN_MANAGE "panel manual p m"
    case "$TURN_MANAGE" in p) TURN_MANAGE=panel;; m) TURN_MANAGE=manual;; esac
  fi
  case "$TURN_MANAGE" in panel|manual) ;; *) TURN_MANAGE=panel;; esac
  if [ "$TURN_MANAGE" = panel ] && ! $DRYRUN; then     # mount the Docker socket so swg-noded can drive host turn-proxy units (B1)
    python3 - "$PREFIX$INSTALL_DIR/docker-compose.yml" <<'PYSOCK'
import sys, re
p = sys.argv[1]; lines = open(p).read().splitlines(); out = []; in_node = False
for ln in lines:
    if re.match(r'^  swg-node:\s*$', ln): in_node = True
    elif in_node and re.match(r'^  \S', ln): in_node = False
    out.append(ln)
    if in_node and re.match(r'^      - \./data/node-confs:', ln):   # add the socket right after the conf volume
        out.append('      - /var/run/docker.sock:/var/run/docker.sock   # turn-proxy management (root-on-host)')
open(p, 'w').write('\n'.join(out) + '\n')
PYSOCK
    ok "turn-proxy management: panel (Docker socket mounted — root-equivalent host access)"
  else
    [ "$TURN_MANAGE" = manual ] && ok "turn-proxy management: manual (managed on this server)"
  fi
  migrate_baremetal_turns   # convert: bring the bare-metal turn-proxies into the record FIRST, then the fork menu adds more
  choose_turn_proxy   # install/onboard host turn-proxy servers as part of this step (unit retries until compose publishes the wg port)
fi
NODE_NET="${NODE_NET:-host}"; TURN_MANAGE="${TURN_MANAGE:-manual}"   # concrete values for .env

# ───────────────────────── write .env ─────────────────────────
mkdir -p "$PREFIX$INSTALL_DIR"
_UPD_TRIG=""; _NODE_UPD_TRIG=""   # the panel / node containers write these on a one-click update; the host swg-update.path (wired after compose up) watches them and runs `compose pull && up`
case "$PROFILE" in
  host)   _UPD_TRIG=/var/lib/swg-panel/.update-request;;
  master) _UPD_TRIG=/var/lib/swg-panel/.update-request; _NODE_UPD_TRIG=/var/lib/swg-noded/.update-request;;
  node)   _NODE_UPD_TRIG=/var/lib/swg-noded/.update-request;;
esac
cat > "$PREFIX$INSTALL_DIR/.env" <<EOF
# generated by install-docker.sh — profile: $PROFILE
# ───────── Panel (profiles: host, master) ─────────
PANEL_PASSWORD=$PANEL_PASSWORD
PANEL_USER=$PANEL_USER
PANEL_DOMAIN=$PANEL_DOMAIN
PANEL_BASE=$PANEL_BASE
TLS=$TLS
ACME_EMAIL=$ACME_EMAIL
CF_TOKEN=$CF_TOKEN
CF_ORIGIN_TOKEN=$CF_ORIGIN_TOKEN
PANEL_PORT=$PANEL_PORT
PANEL_BIND=${PANEL_BIND:-0.0.0.0}
PANEL_LOCAL_PORT=${PANEL_LOCAL_PORT:-8088}   # dedicated STABLE plain-HTTP loopback port for a co-located node (published on 127.0.0.1; a public flip never moves it)
SUB_PORT=${SUB_PORT:-8444}
SUB_BIND=${SUB_BIND:-0.0.0.0}
SUB_TRUST_XFF=${SUB_TRUST_XFF:-0}
SUB_DOMAIN=${SUB_DOMAIN:-}
SWG_UPDATE_TRIGGER=$_UPD_TRIG
NODE_UPDATE_TRIGGER=$_NODE_UPD_TRIG
SWG_HOST_HOSTNAME=$(hostname 2>/dev/null)   # host hostname → lets the panel recognise a master's co-located node (which reports the host hostname via host-networking)

# ───────── Node (profiles: node, master) ─────────
PANEL_URL=$PANEL_URL
NODE_TOKEN=$NODE_TOKEN
NODE_ENDPOINT=$NODE_ENDPOINT
NODE_IFACE=$NODE_IFACE
NODE_IFACES=$NODE_IFACES
NODE_LISTEN_PORT=$NODE_LISTEN_PORT
NODE_ADDRESS=$NODE_ADDRESS
NODE_MTU=$NODE_MTU
NODE_PLAIN_WG=$NODE_PLAIN_WG
NODE_NET=$NODE_NET
TURN_MANAGE=$TURN_MANAGE
SWG_HOST_NODE_DIR=$INSTALL_DIR/data/node
TLS_VERIFY=$TLS_VERIFY
TLS_FINGERPRINT=$TLS_FINGERPRINT
DNS=$DNS
EOF
chmod 600 "$PREFIX$INSTALL_DIR/.env" 2>/dev/null || true
ok "wrote $INSTALL_DIR/.env (profile $PROFILE)"

# Let's Encrypt HTTP-01 needs host port 80 — publish it via an override ONLY for letsencrypt(-ip), so the
# other TLS methods (cloudflare/cf15/selfsigned/none) leave :80 free for an existing nginx/apache.
OVERRIDE="$PREFIX$INSTALL_DIR/docker-compose.override.yml"
if [ "$TLS" = letsencrypt ] || [ "$TLS" = letsencrypt-ip ]; then
  if $DRYRUN; then echo "    [skip] write $INSTALL_DIR/docker-compose.override.yml (publish :80 for HTTP-01)"
  else
    cat > "$OVERRIDE" <<'YAML'
# Auto-generated by install-docker.sh — Let's Encrypt HTTP-01 needs host port 80.
# Re-running the installer with a different TLS method removes this file.
services:
  swg-panel:
    ports:
      - "80:80"
YAML
    ok "$TLS: publishing host port 80 for HTTP-01 (docker-compose.override.yml)"
  fi
elif [ -f "$OVERRIDE" ]; then
  $DRYRUN || rm -f "$OVERRIDE"
  ok "removed docker-compose.override.yml (TLS=$TLS doesn't need host port 80)"
fi

# ── reset login + cert on every install (matches bare-metal) ───────────────────
# The entrypoint only writes data/etc/auth and data/etc/tls/* when they're MISSING, so a reused
# data dir keeps the OLD login AND an OLD cert (e.g. a self-signed left by a previously-failed
# letsencrypt run, which then gets served instead of the TLS mode you just picked → Cloudflare 526).
# Drop both and --force-recreate so the entrypoint re-applies the freshly-chosen login + TLS mode.
# (acme state in data/etc/acme is kept, so letsencrypt/cloudflare reuse their cached cert.)
RECREATE=""
if [ "$PROFILE" != node ]; then
  if [ "${REUSE_TLS:-no}" = yes ]; then
    : # reuse: keep the existing login + certificate (entrypoint serves them as-is)
  elif [ "${KEEP_AUTH:-no}" = yes ]; then
    $DRYRUN || rm -f "$PREFIX$INSTALL_DIR/data/etc/tls/fullchain.pem" "$PREFIX$INSTALL_DIR/data/etc/tls/key.pem"   # convert: keep the staged login, but re-apply the chosen TLS
  else
    $DRYRUN || rm -f "$PREFIX$INSTALL_DIR/data/etc/auth" \
                     "$PREFIX$INSTALL_DIR/data/etc/tls/fullchain.pem" "$PREFIX$INSTALL_DIR/data/etc/tls/key.pem"
  fi
fi
# always recreate (incl. node): a plain `up -d` just (re)starts the EXISTING container on its OLD .env,
# so changes from a re-install (e.g. an added interface in NODE_IFACES) never reach the running node.
RECREATE="--force-recreate"

# ── master: auto-enroll the local node in ONE pass (mirrors bare-metal master) ──
# Write the node into ./data/lib/nodes.json BEFORE compose up. The panel entrypoint only seeds
# an empty {} when nodes.json is MISSING, so this pre-written file wins; the node container gets
# the matching raw token via NODE_TOKEN (.env). No "add the node in the panel first" round-trip.
# Merge into any existing nodes.json so a reinstall keeps other (remote) nodes intact.
if [ "${AUTOENROLL:-}" = yes ] && ! $DRYRUN; then
  ndir="$PREFIX$INSTALL_DIR/data/lib"; mkdir -p "$ndir"
  if python3 - "$ndir/nodes.json" "$NODE_NAME" "$NODE_TOKEN" "$NODE_COLOR" <<'PY'
import sys, os, json, hashlib, base64
path, name, token, color = sys.argv[1:5]
try:
    nodes = json.load(open(path)); assert isinstance(nodes, dict)
except Exception:
    nodes = {}

def tok_hash(t):
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", t.encode(), salt, 200000)
    return "pbkdf2_sha256$200000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()
def validates(th, t):
    try:
        algo, it, salt, h = th.split("$")
        return algo == "pbkdf2_sha256" and base64.b64encode(
            hashlib.pbkdf2_hmac("sha256", t.encode(), base64.b64decode(salt), int(it))).decode() == h
    except Exception:
        return False

# A re-install must UPDATE this node, not duplicate it: after the panel's stable-id migration the
# entry is keyed by an opaque id (not the name), so a blind nodes[name]=… would add a second,
# name-keyed copy. Find the existing entry by its (.env-preserved) token first, then by name.
key = next((k for k, v in nodes.items() if isinstance(v, dict) and validates(v.get("token_hash", ""), token)), None)
if key is None:
    key = next((k for k, v in nodes.items() if isinstance(v, dict) and v.get("name") == name), None)
if key is None:
    nodes[name] = {"name": name, "color": color, "endpoint_host": "",
                   "stats_file": "stats-%s.json" % name, "token_hash": tok_hash(token), "created": 0}
else:
    e = nodes[key]; e["name"] = name
    e.setdefault("color", color); e.setdefault("endpoint_host", "")
    e.setdefault("stats_file", "stats-%s.json" % name); e.setdefault("created", 0)
    if not validates(e.get("token_hash", ""), token):   # token changed (e.g. a new -key) → refresh in place
        e["token_hash"] = tok_hash(token)
json.dump(nodes, open(path, "w"), indent=2)
PY
  then chmod 600 "$ndir/nodes.json" 2>/dev/null || true
       ok "auto-enrolled local node $(col "$C_GREEN" "$NODE_NAME") (single-pass master — no key to paste)"
  else warn "couldn't pre-write nodes.json — add the node in the panel (Nodes → Add node) and set NODE_TOKEN in .env"; fi
fi

# ───────────────────────── bring it up ─────────────────────────
# (port checks happen earlier: the panel port at the URL step, :80 at the TLS step for letsencrypt)
info "Starting compose profile '$PROFILE'$($BUILD && echo ' (building from source)')"
BUILDFLAG=""; $BUILD && BUILDFLAG=--build   # default pulls prebuilt images from GHCR
# A re-install MUST refresh the prebuilt image first: compose's pull_policy is "missing", so a plain
# `up --force-recreate` rebuilds the container from the STALE local :latest — entrypoint/datapath fixes
# shipped in a newer image never reach a re-installed node (this is exactly how a stale entrypoint kept
# silently dropping an interface added on re-install). Pull the profile's image(s) up front, like update.sh.
# Skipped when --build (we're compiling locally) and non-fatal (offline → fall back to the local image).
# on_tty runs compose on the controlling terminal (/dev/tty) so it shows its live progress BAR — lc_init's
# log-capture pipe, a `| tee`, or the `exec bash` chain otherwise leave a non-tty and it drops to plain text.
if ! $BUILD; then
  if $DRYRUN; then echo "    [skip] (cd $INSTALL_DIR && $COMPOSE --profile $PROFILE pull)"
  else ( cd "$INSTALL_DIR" && on_tty $COMPOSE --profile "$PROFILE" pull ) \
         && ok "pulled current image(s) for profile $(b "$PROFILE")" \
         || warn "image pull failed — recreating from the local image (run $(b 'bootstrap update') for the newest)"
  fi
fi
# CONVERT bare→docker: the bare node stayed UP through every prompt + the image pull above. NOW — the last
# moment before the container binds its ports — stop+remove it. This is the atomic switch (old down → new up).
if [ "${SWG_CONVERT_DIR:-}" = convert-docker ] && ! $DRYRUN; then
  info "Switching over — stopping the bare-metal services, then starting the container(s)…"
  [ "${SWG_CONVERT_KILL_PANEL:-}" = 1 ] && teardown_bare_panel   # host/master convert: stop+remove the bare panel (and move its state aside)
  # ONLY tear the bare NODE down when its datapath is actually being converted (master/node). A HOST-only
  # convert moves just the panel → docker; the co-located bare node must stay UP + keep serving its peers.
  [ "$PROFILE" != host ] && lc_teardown_baremetal ${MIGRATED_TURNS:-${SWG_CONVERT_TURNS:-}}
fi
# swg-sub masks the panel's secret state with /dev/null (files) + tmpfs (dirs). A bind/tmpfs mount can only CREATE
# its mountpoint if the target already exists on the (read-only) ./data volumes — otherwise the container dies with
# "read-only file system". vault.json/escrow.json don't exist until a subscription vault is set up, panel-settings
# not until the panel first boots, and the tls/ + configs/ dirs may not exist yet on a fresh install or a convert
# that carried no vault. Pre-create them so swg-sub starts. (The node profile doesn't run swg-sub.)
if [ "$PROFILE" != node ] && ! $DRYRUN; then
  mkdir -p "$INSTALL_DIR/data/lib/subs" "$INSTALL_DIR/data/lib/configs" "$INSTALL_DIR/data/etc/tls" 2>/dev/null || true
  for _mf in panel-settings.json subs/vault.json subs/escrow.json; do
    [ -e "$INSTALL_DIR/data/lib/$_mf" ] || : > "$INSTALL_DIR/data/lib/$_mf" 2>/dev/null || true
  done
fi
if $DRYRUN; then echo "    [skip] (cd $INSTALL_DIR && $COMPOSE --profile $PROFILE up -d $RECREATE $BUILDFLAG)"
else
  for _c in $(case "$PROFILE" in node) echo swg-node;; host) echo swg-panel;; *) echo swg-panel swg-node;; esac); do docker ps -aq -f "name=$_c" 2>/dev/null | xargs -r docker rm -f >/dev/null 2>&1 || true; done   # drop any half-recreated/leftover container so `up` can't hit "container name already in use"
  ( cd "$INSTALL_DIR" && on_tty $COMPOSE --profile "$PROFILE" up -d $RECREATE $BUILDFLAG ); fi
$DRYRUN || rm -f /var/lib/swg-recovery 2>/dev/null || true   # stack is up → clear any convert-recovery marker

# After compose's "✔ Container … Started" lines the container(s) initialise silently (panel: start the server +
# issue TLS; node: bring up the datapath + first sync) — say what's happening so the wait below doesn't look hung.
if ! $DRYRUN; then
  case "$PROFILE" in host|master) info "Panel container started — waiting for the server to come up$([ "$TLS" != none ] && echo " + issue its $(b "$TLS") certificate")…";; esac
  case "$PROFILE" in node|master) info "Node container started — bringing up its datapath; it reports to the panel within a couple of syncs.";; esac
fi

# ── surface the cert outcome (don't let a silent self-signed fallback hide as a Cloudflare 526) ──
if [ "$PROFILE" != node ] && [ "$TLS" != none ] && ! $DRYRUN && have openssl; then
  iss=""; for _i in 1 2 3 4 5 6; do
    # NB: '|| true' — a failed openssl pipeline must NOT abort the script under set -o pipefail
    iss="$(echo | openssl s_client -connect "127.0.0.1:$PANEL_PORT" -servername "$PANEL_DOMAIN" 2>/dev/null | openssl x509 -noout -issuer 2>/dev/null || true)"
    [ -n "$iss" ] && break; sleep 2 || true
  done
  case "$iss" in
    *"CN=$PANEL_DOMAIN"|*"CN = $PANEL_DOMAIN")   # issuer == the domain ⇒ self-signed
      [ "$TLS" = selfsigned ] || {
        warn "TLS=$(b "$TLS") was selected, but the panel is serving a $(b 'SELF-SIGNED') cert — issuance failed and fell back."
        echo "         See why: $(b "$COMPOSE -f $INSTALL_DIR/docker-compose.yml logs swg-panel | grep -i cert")"
        echo "         letsencrypt needs :80 reachable (breaks behind Cloudflare); behind the orange cloud use"
        echo "         $(b cloudflare) (DNS-01) or $(b cf15), and set Cloudflare SSL/TLS to $(b 'Full (strict)')."
      } ;;
    "") : ;;   # couldn't read it (port not up yet) — skip
    *) ok "panel is serving a real certificate (issuer:${iss#*=})" ;;
  esac
fi

# ───────────────────────── one-click update wiring (host/master) ─────────────────────────
# A container can't recreate itself, so a docker panel gets the SAME mechanism as bare-metal: a root host
# path-unit watches the panel's data/lib/.update-request and runs a swg-ONLY update. The Update button just
# touches the trigger (the panel writes it via its SWG_UPDATE_TRIGGER env, set in .env above).
wire_host_updater(){
  local paths="" line="" _p
  case "$PROFILE" in
    host)   paths="$INSTALL_DIR/data/lib/.update-request";;
    master) paths="$INSTALL_DIR/data/lib/.update-request $INSTALL_DIR/data/node/.update-request";;
    node)   paths="$INSTALL_DIR/data/node/.update-request";;
    *) return 0;;
  esac
  if $DRYRUN; then echo "    [skip] wire host one-click updater (swg-update.path → ${paths// /, })"; return 0; fi
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
  # from the host instead (stat across the bind mount works — it's a shared inode). A timer runs this every 20s.
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
  # pre-create each trigger INSIDE its container (right owner — a root-created host file would be unwritable by the
  # unprivileged container user). Only when missing (re-touch a live one = a spurious update run).
  case "$PROFILE" in host|master) [ -e "$INSTALL_DIR/data/lib/.update-request" ]  || docker exec swg-panel sh -c ': > /var/lib/swg-panel/.update-request'  2>/dev/null || true;; esac
  case "$PROFILE" in node|master) [ -e "$INSTALL_DIR/data/node/.update-request" ] || docker exec swg-node  sh -c ': > /var/lib/swg-noded/.update-request' 2>/dev/null || true;; esac
  touch /var/lib/swg-update.stamp   # stamp NOW (newer than the just-created triggers) so the first poll doesn't fire a spurious update
  systemctl daemon-reload 2>/dev/null || true
  systemctl enable --now swg-update.timer >/dev/null 2>&1 || warn "couldn't enable swg-update.timer"
  ok "one-click update wired — the $(b Update) button runs a swg-only update on the host"
}
wire_host_updater

# The Docker root helper for ADDRESS changes (mirrors the updater above). A bare-metal panel runs unprivileged and
# delegates host jobs (rebind a listener, restart swg-sub) to swg-netctl; Docker has no swg-netctl, and a container
# can't `docker compose` the host. So the panel container writes the SAME netctl request to data/lib/netctl/queue,
# and THIS host unit drains that queue into `docker compose` actions (restart / recreate a service). Polled, not a
# .path unit — inotify never sees the container's write across a bind mount. Panel-bearing profiles only.
wire_docker_netctl(){
  case "$PROFILE" in host|master|host-node) ;; *) return 0;; esac
  local drainer="$INSTALL_DIR/docker/swg-netctl-docker"
  if $DRYRUN; then echo "    [skip] wire the docker address helper (swg-netctl-docker.timer → docker compose restart/up)"; return 0; fi
  [ -f "$drainer" ] || { warn "docker/swg-netctl-docker missing — one-click address changes will fall back to a manual restart"; return 0; }
  mkdir -p "$INSTALL_DIR/data/lib/netctl/queue" "$INSTALL_DIR/data/lib/netctl/status"   # the panel writes requests here (via the data/lib bind mount)
  install -m755 "$drainer" /usr/local/bin/swg-netctl-docker
  cat > /etc/systemd/system/swg-netctl-docker.service <<EOF
[Unit]
Description=swg-panel docker address helper (drains the netctl queue into docker compose actions)

[Service]
Type=oneshot
Environment=SWG_DOCKER_DIR=$INSTALL_DIR
ExecStart=/usr/local/bin/swg-netctl-docker
EOF
  cat > /etc/systemd/system/swg-netctl-docker.timer <<EOF
[Unit]
Description=poll the swg-panel docker netctl queue (address changes)

[Timer]
OnActiveSec=5s
OnUnitActiveSec=1s
AccuracySec=1s

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload 2>/dev/null || true
  systemctl enable --now swg-netctl-docker.timer >/dev/null 2>&1 || warn "couldn't enable swg-netctl-docker.timer"
  ok "one-click address changes wired — the panel restarts swg-sub / rebinds via the host on Save"
}
wire_docker_netctl

# ───────────────────────── SUMMARY ─────────────────────────
# TLS=none → the operator fronts the panel + swg-sub with their OWN reverse proxy: print ready nginx/Caddy
# configs (both on :443, different subdomains → the two containers on loopback). Installs nothing.
if [ "$TLS" = none ] && { [ "$PROFILE" = host ] || [ "$PROFILE" = master ]; }; then
  print_proxy_configs "$INSTALL_DIR/reverse-proxy" "$PANEL_DOMAIN" "127.0.0.1:${PANEL_PORT}" "$PANEL_BASE" \
    "${SUB_DOMAIN:-sub.example.com}" "127.0.0.1:${SUB_PORT}"
fi

# A master sub-step (SWG_LC_PARENT=1) prints just a one-liner — convert.sh emits ONE unified summary at the very
# end of the master convert. An individual host/node convert (not a sub-step) prints its full summary here.
if [ "${SWG_LC_PARENT:-}" = 1 ]; then echo; ok "$PROFILE → docker done — continuing the master convert…"
else
echo; ok "Docker install complete (profile: $PROFILE)."
print_summary "$([ -n "${SWG_CONVERT_DIR:-}" ] && echo CONVERSION || { [ "$EXISTING_DOCKER" = yes ] && echo RE-INSTALL || echo INSTALL; })" "$([ -n "${SWG_CONVERT_DIR:-}" ] && { [ "$PROFILE" = node ] && echo node || echo host; } || true)"
fi   # end of the full summary (suppressed for a master sub-step)
if $DRYRUN; then echo; ok "DRY RUN done — inspect ./dryrun$INSTALL_DIR/.env"; fi   # `if` (not `&&`) so a real run doesn't exit the script non-zero on its last command
