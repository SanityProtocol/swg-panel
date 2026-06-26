#!/usr/bin/env bash
# install-host.sh — set up the swg-panel host (server + UI + collector + receiver).
#
# Two roles, chosen in Step 1 (or via ROLE): master or host.
#   master  panel + this box also runs wg/awg interfaces (an entry server)
#   host    panel only; wg/awg nodes are deployed separately
#
# Fill the CONFIG block to run unattended, or leave blanks to be prompted.
# Run as root. Use --dry-run to render every file under ./dryrun and execute nothing.
set -euo pipefail

# ───────────────────────── CONFIG (blank = ask) ─────────────────────────
METHOD="${METHOD:-baremetal}"          # baremetal (systemd). For Docker, use docker-compose instead.
ROLE="${ROLE:-}"                       # master (panel + this box is an entry server) | host (panel only)
HOST_NODE_NAME="${HOST_NODE_NAME:-}"   # node name for THIS box (master only)
HOST_ENDPOINT_IP="${HOST_ENDPOINT_IP:-}" # public IP clients dial for this box's wg (master only)
MANAGE_IFACES="${MANAGE_IFACES:-}"     # e.g. "awg0"  (blank = manage all detected; master only)
WG_MTU="${WG_MTU:-1280}"               # interface MTU — 1280 leaves headroom for turn-proxy obfuscation

PANEL_DOMAIN="${PANEL_DOMAIN:-}"       # panel URL: IP, host, or host/subpath (e.g. vpn.example.com/swg). Blank = this host's IP.
STORE_CONFIGS="${STORE_CONFIGS:-true}"   # keep client configs on the panel so QR/download stay available (set false for no secrets at rest)

SERVE_MODE="${SERVE_MODE:-}"           # internal (self-contained) | nginx | caddy | skip  (blank = ask)
# TLS — how to obtain the certificate:
TLS_MODE="${TLS_MODE:-}"               # cloudflare | letsencrypt | selfsigned | skip  (blank = ask)
ACME_EMAIL="${ACME_EMAIL:-}"           # account email for letsencrypt/cloudflare
CF_TOKEN="${CF_TOKEN:-}"               # cloudflare: API token with Zone:DNS:Edit
CF_ACCOUNT_ID="${CF_ACCOUNT_ID:-}"     # cloudflare: optional account id
CF_ORIGIN_TOKEN="${CF_ORIGIN_TOKEN:-${CF_ORIGIN_KEY:-}}"  # cf15: API token with Zone:SSL and Certificates:Edit (the Origin CA Key is deprecated)
CERT_FULLCHAIN="${CERT_FULLCHAIN:-}"   # skip-with-own-cert: path to fullchain.pem
CERT_KEY="${CERT_KEY:-}"               # skip-with-own-cert: path to private key.pem
BASIC_USER="${BASIC_USER:-admin}"
BASIC_PASS="${BASIC_PASS:-}"           # blank -> random, printed at the end

# Remote nodes are NOT listed here — add them in the panel's Nodes screen, which
# issues a one-time token + an install-node.sh command to run on each server.

# paths / identities (defaults are sane)
PANEL_DIR="${PANEL_DIR:-/opt/swg-panel}"
AGENT_DIR="${AGENT_DIR:-/opt/swg-agent}"
NODED_DIR="${NODED_DIR:-/opt/swg-noded}"
ETC_DIR="${ETC_DIR:-/etc/swg-panel}"
STATE_DIR="${STATE_DIR:-/var/lib/swg-panel}"
STATS_DIR="${STATS_DIR:-/var/www/wgstats}"
PANEL_USER="${PANEL_USER:-swgpanel}"
PORT="${PORT:-}"
PANEL_BASE="${PANEL_BASE:-}"           # derived from PANEL_DOMAIN's path (e.g. /swg); blank = served at root
TLS_DIR="${TLS_DIR:-/etc/swg-panel/tls}"
ACME_WEBROOT="${ACME_WEBROOT:-/var/www/acme}"
# ────────────────────────────────────────────────────────────────────────

DRYRUN=false; [ "${1:-}" = "--dry-run" ] && DRYRUN=true
PREFIX=""; $DRYRUN && PREFIX="$(pwd)/dryrun"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SRC/lib/common.sh"   # shared helpers: v_iface/v_subnet/v_hostport, next_free_port, turn_repo_owner, dl_turn_bin
PALETTE=("#34d399" "#22d3ee" "#c084e8" "#f0913c" "#e8c04b" "#60a5fa" "#f0596b")

# ── colours / styling (honour NO_COLOR + non-tty) ──
if { [ -t 1 ] || [ -n "${SWG_FORCE_COLOR:-}" ]; } && [ -z "${NO_COLOR:-}" ]; then
  BOLD=$'\033[1m'; RESET=$'\033[0m'
  C_BLUE=$'\033[38;5;39m'; C_GREEN=$'\033[32m'; C_GREY=$'\033[90m'; C_CYAN=$'\033[36m'; C_RED=$'\033[31m'; C_YEL=$'\033[33m'; C_BL=$'\033[38;5;33m'; C_BROWN=$'\033[38;5;130m'
else BOLD=""; RESET=""; C_BLUE=""; C_GREEN=""; C_GREY=""; C_CYAN=""; C_RED=""; C_YEL=""; C_BL=""; C_BROWN=""; fi
b(){   printf '%s%s%s' "$BOLD" "$*" "$RESET"; }
bb(){  printf '%s%s%s%s' "$BOLD" "$C_BLUE" "$*" "$RESET"; }   # bold + blue (handoff URL / login)
col(){ local _c="$1"; shift; printf '%s%s%s' "$_c" "$*" "$RESET"; }
conf_get(){ grep -iE "^[[:space:]]*$2[[:space:]]*=" "$1" 2>/dev/null | head -1 | sed 's/.*=[[:space:]]*//; s/[[:space:]]*$//'; }
# one styled interface row (green name + proto + endpoint:port + address) for the manage-loop lists, matching the SUMMARY.
iface_row(){ local n="$1" conf proto ep lp addr   # set -e safe; prefer a just-queued spec (no conf yet), else the conf
  if [ -n "${SPEC_CMD[$n]:-}" ]; then proto="${SPEC_CMD[$n]}"; lp="${SPEC_PORT[$n]:-}"; addr="${SPEC_ADDR[$n]:-}"; ep="${SPEC_EP[$n]:-}"
  else conf="${IF_CONF[$n]:-}"; proto="${IF_CMD[$n]:-?}"; ep="${IF_ENDPOINT[$n]:-${HOST_ENDPOINT_IP:-}}"
    lp="$(conf_get "$conf" ListenPort || true)"; addr="$(conf_get "$conf" Address || true)"; fi
  [ -n "$ep" ] || ep="$(detect_public_ip 2>/dev/null || true)"
  printf '    %s%s%s  %s%-10s%s  %s:%s  %s\n' "$C_GREEN" "$(printf '%-10s' "$n")" "$RESET" "$BOLD" "$(proto_label "${proto:-?}")" "$RESET" "${ep:-?}" "${lp:-?}" "${addr:-?}"; }
fwd_ifaces(){ local cp="${1##*:}" n lp out=""; for n in "${!IF_CONF[@]}"; do lp="$(conf_get "${IF_CONF[$n]}" ListenPort)"; [ -n "$lp" ] && [ "$lp" = "$cp" ] && out="${out:+$out }$n"; done; printf '%s' "$out"; }   # interface(s) a turn-proxy's ip:port forwards to (matched by ListenPort)
# add-only marker: an interface ADOPTED from outside (existing peers) carries '#swg:onboarded' in its
# conf so swg-noded never wipes its peers. The marker rides along through re-installs and conversions.
iface_onboarded(){ local c="${IF_CONF[$1]:-}"; [ -n "$c" ] && grep -q '^#swg:onboarded' "$c" 2>/dev/null; }
onboard_mark(){ local c="${IF_CONF[$1]:-}"; [ -n "$c" ] || return 0; $DRYRUN && return 0; [ -f "$c" ] || return 0
  grep -q '^#swg:onboarded' "$c" 2>/dev/null || sed -i '1i #swg:onboarded' "$c" 2>/dev/null || true; }
info(){ _nlguard; echo "${C_BLUE}▸${RESET} ${BOLD}$*${RESET}"; }   # ▸ light-blue, bold (universal action flag)
sub(){  _nlguard; echo "${C_BL}::${RESET} $*"; }                    # :: blue sub-item / progress detail
ok(){   _nlguard; echo "${C_GREEN}✓${RESET} $*"; }
warn(){ _nlguard; echo "${C_BROWN}!${RESET} $*" >&2; }
die(){  echo "${C_RED}✗ $*${RESET}" >&2; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }
run(){ if $DRYRUN; then echo "    [skip] $*"; else "$@"; fi; }
# bring an interface up QUIETLY — wg/awg-quick spew a "[#] ip link add…" trace; swallow it on success and
# surface the captured output (indented) only on failure, so a real error still shows. bringup <tool> <iface>
bringup(){ local tool="$1" ifn="$2" out
  if $DRYRUN; then echo "    [skip] $tool up $ifn"; return 0; fi
  if out="$("$tool" up "$ifn" 2>&1)"; then return 0
  else [ -n "$out" ] && printf '%s\n' "$out" | sed 's/^/      /' >&2; return 1; fi; }
writef(){ # writef <abs_path> <mode>   (content on stdin)
  local p="$1" m="${2:-644}" full="$PREFIX$1"; mkdir -p "$(dirname "$full")"; cat > "$full"
  chmod "$m" "$full" 2>/dev/null || true; ok "wrote $p ($m)"; }
menu(){ printf '  %s\n      %s\n\n' "$1" "$2"; }   # menu <styled-label> <description>
key(){  printf '%s[%s]%s%s'   "$C_BLUE"        "$1" "$2" "$RESET"; }   # whole label blue:        key  a 'mneziawg'           → [a]mneziawg
keyd(){ printf '%s%s[%s]%s%s' "$BOLD" "$C_BLUE" "$1" "$2" "$RESET"; }   # default label bold+blue: keyd a 'mneziawg (default)'  → [a]mneziawg (default)
keyg(){ printf '%s[%s]%s%s'   "$C_GREY"        "$1" "$2" "$RESET"; }   # de-emphasised label grey:  keyg n 'one'                → [n]one
STEP="${STEP_BASE:-1}"; step(){ [ -n "${_SWG_NL:-}" ] || echo; _SWG_NL=""; echo "$(b "Step $STEP. $1")${2:+   $2}"; STEP=$((STEP+1)); }   # sequential; skip the leading blank when a prompt already printed one

ask(){ local v p="$1" d="${2:-}"; if [ -n "${!3:-}" ]; then return; fi
  echo; read -rp "  $p${d:+ [$(col "$C_BLUE" "$d")]}: " v </dev/tty || true; printf -v "$3" '%s' "${v:-$d}"; }
ask_yn(){ local v p="$1" d="${2:-y}"; if [ -n "${!3:-}" ]; then return; fi
  [ -n "${_SWG_NL:-}" ] || echo; _SWG_NL=""; read -rp "  $p ($([ "$d" = y ] && echo 'Y/n' || echo 'y/N')): " v </dev/tty || true
  v="${v:-$d}"; case "$v" in [Yy]*) printf -v "$3" yes;; *) printf -v "$3" no;; esac; _pnl; }

# ── input validators (0 = ok) ──
v_role(){    case "$1" in master|host) return 0;; *) return 1;; esac; }
v_tls(){     case "$1" in cloudflare|letsencrypt|selfsigned|skip) return 0;; *) return 1;; esac; }
v_serve(){   case "$1" in internal|nginx|caddy|skip) return 0;; *) return 1;; esac; }
v_proto(){   case "$1" in a|awg|amneziawg|w|wg|wireguard) return 0;; *) return 1;; esac; }
v_ip(){      printf '%s' "$1" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$' || return 1
             local o; for o in ${1//./ }; do [ "$o" -le 255 ] 2>/dev/null || return 1; done; return 0; }
v_host(){    v_ip "$1" && return 0; case "$1" in ""|*" "*|*[!a-zA-Z0-9.-]*) return 1;; *) return 0;; esac; }
v_url(){     case "$1" in ""|*" "*) return 1;; esac
             local h="${1#http://}"; h="${h#https://}"; h="${h%%/*}"; h="${h%%:*}"; v_host "$h"; }
v_port(){    case "$1" in ""|*[!0-9]*) return 1;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
port_free(){ local p="$1" n   # UDP port not already bound AND not already taken by an interface queued this session
  for n in ${SPEC_ORDER[@]+"${SPEC_ORDER[@]}"}; do [ "${SPEC_PORT[$n]:-}" = "$p" ] && return 1; done
  have ss || return 0; [ -z "$(ss -lnuH "sport = :$p" 2>/dev/null)" ]; }
v_freeport(){ v_port "$1" && port_free "$1"; }
# host TCP port $1 is held by OUR panel's systemd service (a re-install) → not a real conflict. Identify it by
# the listener PID's cgroup so it holds on any port, not just :443 (mirrors docker's panel_owns_port).
panel_owns_port(){ have ss || return 1; local pid
  pid="$(ss -lntpH "sport = :$1" 2>/dev/null | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2 || true)"
  [ -n "$pid" ] && grep -qs swg-panel-server "/proc/$pid/cgroup"; }
# smart default ports: first install offers the base; later ones offer (highest used OF THAT KIND)+1, then the
# next host-free port. turn = TP_LISTEN units; wg/awg = highest ListenPort across confs, never below 51820+queued.
turn_default_port(){ detect_turn; local hi=0 lis p; if [ "${#TP_LISTEN[@]}" -gt 0 ]; then for lis in "${TP_LISTEN[@]}"; do p="${lis##*:}"; case "$p" in ''|*[!0-9]*) :;; *) [ "$p" -gt "$hi" ] && hi="$p";; esac; done; fi; [ "$hi" -gt 0 ] && next_free_port $((hi+1)) || next_free_port 56000; }
iface_default_port(){ local cnt="${1:-0}" hi=0 p f n base; for f in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf; do [ -f "$f" ] || continue; p="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]\{1,\}\).*/\1/p' "$f" | head -1)"; case "$p" in ''|*[!0-9]*) :;; *) [ "$p" -gt "$hi" ] && hi="$p";; esac; done; for n in ${SPEC_ORDER[@]+"${SPEC_ORDER[@]}"}; do p="${SPEC_PORT[$n]:-}"; case "$p" in ''|*[!0-9]*) :;; *) [ "$p" -gt "$hi" ] && hi="$p";; esac; done; base=$((51820 + cnt)); { [ "$hi" -ge 51820 ] && [ $((hi+1)) -gt "$base" ]; } && base=$((hi+1)); next_free_port "$base"; }
v_name(){    case "$1" in ""|*[!a-zA-Z0-9_-]*) return 1;; esac; [ "${#1}" -le 40 ]; }
v_user(){    case "$1" in ""|*:*|*" "*) return 1;; esac; [ "${#1}" -le 40 ]; }
v_email(){   case "$1" in ?*@?*.?*) return 0;; *) return 1;; esac; }
v_cftoken(){ [ -n "$1" ] && [ "${#1}" -ge 10 ]; }
v_cforigin(){ [ -n "$1" ] && [ "${#1}" -ge 20 ]; }
v_cfport(){  case "$1" in 443|2053|2083|2087|2096|8443) return 0;; *) return 1;; esac; }  # ports Cloudflare's proxy forwards (HTTPS)
# 0 iff $1 is a public, routable IPv4 literal — excludes RFC1918 / loopback / link-local / CGNAT.
# Let's Encrypt only issues IP certs for public IPs, so this gates the letsencrypt-ip TLS option.
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
# 0 iff the cert file $1 is valid for host $2 — i.e. $2 appears as a SAN (DNS/IP) or the CN. Used to decide
# whether a re-install can REUSE the existing cert: a cert issued for a different host/IP can't be reused here.
cert_covers_host(){ local cert="$1" host="$2" txt
  [ -s "$cert" ] && command -v openssl >/dev/null 2>&1 || return 1
  txt="$( { openssl x509 -in "$cert" -noout -ext subjectAltName; openssl x509 -in "$cert" -noout -subject; } 2>/dev/null || true)"
  if printf '%s' "$txt" | grep -qE "(DNS:|IP Address:|CN ?= ?)${host//./\\.}(\$|[^0-9A-Za-z.-])"; then return 0; fi
  return 1; }
# v_iface/v_subnet/v_hostport now in lib/common.sh

# ask_choice <prompt> <default> <var> "<opt…>"  — re-prompts on bad input; ' --force' overrides
ask_choice(){ local p="$1" d="$2" var="$3" opts="$4" v o forced rc i
  if [ -n "${!var:-}" ]; then for o in $opts; do [ "${!var}" = "$o" ] && return; done
    warn "ignoring invalid $var='${!var}' (expected: $opts)"; fi
  while :; do
    if read -rp "  $p [$(col "$C_BLUE" "$d")]: " v </dev/tty; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"; forced=no
    case "$v" in *' --force') v="${v% --force}"; v="${v%"${v##*[![:space:]]}"}"; forced=yes;; esac
    case "$v" in ""|*[!0-9]*) :;; *) i=1; for o in $opts; do [ "$i" = "$v" ] && { v="$o"; break; }; i=$((i+1)); done;; esac   # [N] -> the Nth option
    for o in $opts; do [ "$v" = "$o" ] && { printf -v "$var" '%s' "$v"; _pnl; return; }; done
    [ "$forced" = yes ] && { warn "forcing unrecognised value: $v"; printf -v "$var" '%s' "$v"; _pnl; return; }
    [ $rc -ne 0 ] && die "‘$v’ is not one of: $opts (and no interactive input to re-prompt)"
    warn "‘$v’ isn't one of: $(col "$C_BLUE" "$opts")"
    echo "  re-enter, or append $(b ' --force') to use your value anyway"
  done; }

# ask_valid <prompt> <default> <var> <validator> <hint>  — re-prompts on bad input; ' --force' overrides
ask_valid(){ local p="$1" d="$2" var="$3" fn="$4" hint="$5" v forced rc
  if [ -n "${!var:-}" ]; then "$fn" "${!var}" && return
    warn "ignoring invalid $var='${!var}' ($hint)"; fi
  [ -n "${_SWG_NL:-}" ] || echo; _SWG_NL=""
  while :; do
    if read -rp "  $p${d:+ [$(col "$C_BLUE" "$d")]}: " v </dev/tty; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"; forced=no
    case "$v" in *' --force') v="${v% --force}"; v="${v%"${v##*[![:space:]]}"}"; forced=yes;; esac
    if "$fn" "$v"; then printf -v "$var" '%s' "$v"; _pnl; return; fi
    [ "$forced" = yes ] && { warn "forcing: $v"; printf -v "$var" '%s' "$v"; _pnl; return; }
    [ $rc -ne 0 ] && die "no valid value for ‘$p’ (got '${v:-empty}') and no interactive input to re-prompt"
    warn "$hint"
    echo "  re-enter, or append $(b ' --force') to use it anyway"
  done; }

detect_public_ip(){ # best public IPv4: default-route source, then first hostname -I (never the loopback)
  local ip; ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1 || true)"
  case "$ip" in 127.*) ip="";; esac                                                   # never the loopback — clients can't reach it
  [ -z "$ip" ] && ip="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -vE '^127\.' | head -n1 || true)"
  printf '%s' "$ip"; }
detect_wan(){ ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n1; }

parse_panel_url(){ # parse_panel_url <input> -> sets PANEL_HOST_NOPORT, PANEL_BASE, URL_PORT
  local u="$1" hostport rest
  u="${u#http://}"; u="${u#https://}"; u="${u%/}"
  hostport="${u%%/*}"                       # host[:port]
  rest="${u#"$hostport"}"                    # remaining /path (may be empty)
  PANEL_BASE="$rest"; [ "$PANEL_BASE" = "/" ] && PANEL_BASE=""
  PANEL_BASE="${PANEL_BASE%/}"               # no trailing slash
  case "$hostport" in
    *:*) PANEL_HOST_NOPORT="${hostport%%:*}"; URL_PORT="${hostport##*:}";;
    *)   PANEL_HOST_NOPORT="$hostport"; URL_PORT="";;
  esac
}

# ───────────────────────── wg/awg detection ─────────────────────────
declare -A IF_CMD IF_CONF IF_ENDPOINT; declare -a CREATED   # IF_ENDPOINT: per-interface public IP clients dial; CREATED: ifaces made this run
declare -A SPEC_CMD SPEC_PROTO SPEC_PORT SPEC_SUBNET SPEC_ADDR SPEC_WAN SPEC_EP SPEC_DIR; declare -a SPEC_ORDER=()   # queued interfaces (prompted now, installed at the end by apply_specs)
detect_wg(){ # scan everything under /etc/amnezia (any subdir) for awg, and /etc/wireguard for wg
  IF_CMD=(); IF_CONF=(); local f n
  if [ -d /etc/amnezia ]; then
    while IFS= read -r f; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=awg; IF_CONF[$n]="$f"
    done < <(find /etc/amnezia -maxdepth 3 -type f -name '*.conf' 2>/dev/null)
  fi
  for f in /etc/wireguard/*.conf; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=wg; IF_CONF[$n]="$f"; done
}
# ── interface picker helpers (bare-metal master) ──
node_ifaces(){ # interfaces this node already manages — config.json keys WHOSE CONF STILL EXISTS. A dangling entry
  # (conf file gone, no live device — e.g. a docker host-net interface orphaned by teardown) is a GHOST: skip it
  # so it's never shown as "already on this node" and re-adopted with blank fields (which then re-writes the ghost).
  { [ -f /etc/swg-agent/config.json ] && have python3; } || return 0
  python3 -c 'import json, os
for n, ic in (json.load(open("/etc/swg-agent/config.json")).get("interfaces") or {}).items():
    if isinstance(ic, dict) and os.path.exists(ic.get("conf", "")): print(n)' 2>/dev/null || true
}
_in(){ case " $2 " in *" $1 "*) return 0;; *) return 1;; esac; }
docker_node_ifaces(){   # interfaces managed by a co-located DOCKER node (its ./data/node-confs)
  local d c; for d in "${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"; do
    [ -d "$d/data/node-confs" ] || continue
    for c in "$d"/data/node-confs/*.conf; do [ -f "$c" ] && basename "$c" .conf; done
  done
}
transfer_from_docker(){ # import a docker node-conf to bare-metal: copy out, ADD host NAT, drop the source
  local n="$1" d="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}" src dest addr subnet wan up down
  src="$d/data/node-confs/$n.conf"; [ -f "$src" ] || return 0
  if grep -qiE '^[[:space:]]*(Jc|Jmin|Jmax|S1|S2|H1|H2|H3|H4|I1)[[:space:]]*=' "$src"; then dest="/etc/amnezia/amneziawg/$n.conf"; else dest="/etc/wireguard/$n.conf"; fi
  run mkdir -p "$(dirname "$dest")"
  # docker confs carry NO PostUp (the container does its own NAT) — inject host NAT so the bare iface routes
  addr="$(sed -n 's/^[[:space:]]*[Aa]ddress[[:space:]]*=//p' "$src" | head -1 | sed 's/,.*//; s/[[:space:]]//g')"
  subnet="$(python3 -c 'import ipaddress,sys;print(ipaddress.ip_network(sys.argv[1],strict=False))' "$addr" 2>/dev/null || echo "$addr")"
  wan="$(detect_wan)"; [ -n "$wan" ] || wan=eth0
  up="sysctl -q -w net.ipv4.ip_forward=1; iptables -t nat -A POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -A FORWARD -i %i -o ${wan} -j ACCEPT; iptables -A FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
  down="iptables -t nat -D POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -D FORWARD -i %i -o ${wan} -j ACCEPT; iptables -D FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
  if $DRYRUN; then echo "    [skip] import $src → $dest (+ host NAT)"
  else awk -v up="$up" -v down="$down" '
    /^[[:space:]]*[Pp]ost(Up|Down)[[:space:]]*=/ {next}
    {print}
    /^\[Interface\][[:space:]]*$/ && !d {print "PostUp = " up; print "PostDown = " down; d=1}
  ' "$src" > "$dest"; chmod 600 "$dest"; fi
  run rm -f "$src"
  ok "imported $(col "$C_GREEN" "$n") from the docker node-confs (host NAT added)"
}
choose_ifaces(){ # let the user pick which detected interfaces to manage; 'new' creates more
  detect_wg
  if [ -n "$MANAGE_IFACES" ]; then
    IFS=',' read -ra SELECTED <<< "$MANAGE_IFACES"
  else
    info "Checking for wg / awg on this host…"
    # only nothing-to-do if there are NEITHER /etc confs NOR leftover docker node-confs (a removed
    # docker node whose peers were kept) — the latter are offered for import in the loop below.
    if [ "${#IF_CMD[@]}" -eq 0 ] && [ -z "$(docker_node_ifaces)" ]; then
      warn "No wg / awg interfaces found in /etc/wireguard or /etc/amnezia."
      local doit; ask_yn "Create one now? (installs WireGuard / AmneziaWG only if missing)" y doit
      [ "$doit" = yes ] && spec_iface
      detect_wg
      [ "${#IF_CMD[@]}" -eq 0 ] && [ "${#SPEC_ORDER[@]}" -eq 0 ] && die "No interface. Create one, then re-run (or set MANAGE_IFACES)."
    elif [ "${#IF_CMD[@]}" -eq 0 ]; then
      info "Found leftover docker node-confs to import: $(col "$C_GREEN" "$(echo $(docker_node_ifaces))")"
    fi
    local names pick n dk avail mine xfer bad yn; local -a sel=()
    while :; do
      detect_wg; names="${!IF_CMD[*]}"; dk="$(docker_node_ifaces)" || true
      mine=""; for n in $(node_ifaces) ${CREATED[@]+"${CREATED[@]}"}; do _in "$n" "$mine" || mine="$mine $n"; done; mine="$(echo $mine)"
      avail=""; for n in $names; do _in "$n" "$mine" && continue; _in "$n" "$dk" && continue; avail="$avail $n"; done; avail="$(echo $avail)"
      echo
      [ -n "$mine" ] && { echo "  Interfaces already on this node:"; echo; for n in $mine; do iface_row "$n"; done; echo; }
      if [ -n "$avail" ]; then echo "  Available orphan interfaces:"; echo; for n in $avail; do iface_row "$n"; done; echo
      else echo "  Available orphan interfaces: (none)"; fi
      [ -n "$dk" ] && { printf "  Interfaces from a docker node on this server (import to this node):"; for n in $dk; do printf ' %s' "$(col "$C_RED" "$n")"; done; echo; }
      echo
      if [ -z "$avail" ] && [ -z "$mine" ] && [ -n "$dk" ]; then   # only docker-node interfaces → transfer or create
        printf "  Enter a name to %s it from the docker node, or %s to create one: " "$(col "$C_BLUE" transfer)" "$(col "$C_BLUE" new)"
      elif [ -n "$avail" ]; then                                   # orphans present → manage all / some / none
        echo "  Press $(b Enter) to manage $(col "$C_BLUE" 'all orphans above') and continue"
        echo "  Enter interface $(b names) (space-separated) to manage or migrate specific ones"
        [ -n "$mine" ] && echo "  Enter $(col "$C_BLUE" done) to keep only this node's interfaces (leave the orphans)"
        printf "  Enter %s to create another interface: " "$(col "$C_BLUE" '[n]ew')"
      else                                                        # no orphans → finish or add more
        echo "  Press $(b Enter) to finish with this node's interfaces"
        [ -n "$dk" ] && echo "  Enter interface $(b names) to migrate one from the docker node"
        printf "  Enter %s to create another interface: " "$(col "$C_BLUE" '[n]ew')"
      fi
      if ! read -r pick 2>/dev/null </dev/tty; then echo; warn "no interactive input — keeping this node's interfaces"; sel=($mine $avail); break; fi
      pick="$(echo $pick)"
      if [ -z "$pick" ]; then                                     # Enter → keep mine + onboard all orphans
        sel=($mine $avail)
        [ ${#sel[@]} -gt 0 ] || { warn "nothing to manage — type 'new' to create an interface"; continue; }
        break
      fi
      if [ "$pick" = done ]; then                                 # keep only this node's interfaces (leave orphans)
        [ -n "$mine" ] || { warn "this node has no interfaces yet — manage one or type 'new'"; continue; }
        sel=($mine); break
      fi
      { [ "$pick" = new ] || [ "$pick" = n ]; } && { spec_iface; continue; }
      xfer=""; bad=""
      for n in $pick; do _in "$n" "$mine" && continue; _in "$n" "$avail" && continue; _in "$n" "$dk" && { xfer="$xfer $n"; continue; }; bad="$bad $n"; done
      [ -n "$bad" ] && { warn "not found:$bad — pick from the lists, or 'new'"; continue; }
      if [ -n "$xfer" ]; then
        printf "  Are you sure you want to transfer %s to this node? (y/N): " "$(col "$C_RED" "$(echo $xfer)")"
        read -r yn 2>/dev/null </dev/tty || yn=n
        case "$yn" in [Yy]*) for n in $xfer; do transfer_from_docker "$n" || true; done; detect_wg;; *) continue;; esac
      fi
      sel=($mine); for n in $pick; do _in "$n" "$mine" || sel+=("$n"); done; break   # keep mine + the chosen ones
    done
    # a freshly ADOPTED orphan (not created here, not a conversion import) is add-only — tag its conf
    _nodeifs="$(node_ifaces | tr '\n' ' ')"
    for n in ${sel[@]+"${sel[@]}"}; do n="${n// /}"; [ -z "$n" ] && continue
      _in "$n" "$_nodeifs" && continue
      _in "$n" "${CREATED[*]:-}" && continue
      _in "$n" "${ADOPTED_IFACES:-}" && continue
      onboard_mark "$n"
    done
    SELECTED=("${sel[@]}")
  fi
  apply_specs   # install tools + write confs + bring up every queued interface now (after all prompts)
  detect_wg
  local _ep
  for n in "${SELECTED[@]}"; do n="${n// /}"; [ -n "${IF_CMD[$n]:-}" ] || { [ -e "/etc/amnezia/amneziawg/$n.conf" ] && { IF_CMD[$n]=awg; IF_CONF[$n]="/etc/amnezia/amneziawg/$n.conf"; } || { IF_CMD[$n]=wg; IF_CONF[$n]="/etc/wireguard/$n.conf"; }; }
    [ -n "${IF_ENDPOINT[$n]:-}" ] && continue   # interfaces just created already have an endpoint
    _ep="$(detect_public_ip)"; IF_ENDPOINT[$n]="$_ep"   # auto endpoint clients dial (change it later in the panel)
    echo "    Used $(bb "$_ep") endpoint IP for $(col "$C_GREEN" "$n")"; done
  [ "${#SELECTED[@]}" -gt 0 ] || die "no interfaces selected"
  ok "Managing: $(b "$(col "$C_GREEN" "${SELECTED[*]}")")"
}

# ───────────────────────── turn-proxy (vk-turn-proxy) ─────────────────────────
# Tunnels WireGuard/AmneziaWG through VK/Yandex TURN servers. Config is the systemd
# unit's CLI args: -listen <pub-ip:port>  -connect <wg-ip:port>. We detect any such
# unit, can install the binary from a fork's GitHub releases, and record listen→connect
# so the panel can later tell a turn-proxied client (peer endpoint IP == a turn listen IP)
# from a direct wg/awg one. https://github.com/cacggghp/vk-turn-proxy
TURN_DIR="${TURN_DIR:-/opt/vk-turn-proxy}"
TURN_RECORD="${TURN_RECORD:-/etc/swg-agent/turn-proxy.json}"
declare -A TP_LISTEN TP_CONNECT TP_WRAP
gen_wrap_key(){ $DRYRUN && { echo "GENERATED-ON-REAL-RUN"; return 0; }   # 32-byte key as 64 hex chars
  openssl rand -hex 32 2>/dev/null || head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
# Per-fork obfuscation flags (verified from each binary's -h). Echoes the flags WITH a
# freshly generated -wrap-key baked in (kiper292 has no wrap support → empty).
turn_wrap_flags(){ local k; case "$1" in
  anton48)      k="$(gen_wrap_key)"; printf -- '-wrap-srtp -wrap-key %s' "$k";;
  samosvalishe) k="$(gen_wrap_key)"; printf -- '-wrap -wrap-key %s' "$k";;
  WINGS-N)      k="$(gen_wrap_key)"; printf -- '-wrap-mode on -wrap-key %s' "$k";;
  Moroka8)      k="$(gen_wrap_key)"; printf -- '-wrap -wrap-key %s' "$k";;   # verified from its README: -wrap -wrap-key
  *) printf '';; esac; }
turn_wg_ports(){   # echo "<iface>:<ListenPort>" for every interface managed in the wg/awg step
  local n p
  for n in ${SELECTED[@]+"${SELECTED[@]}"}; do
    [ -n "${IF_CONF[$n]:-}" ] || continue
    p="$(grep -iE '^[[:space:]]*ListenPort[[:space:]]*=' "${IF_CONF[$n]}" 2>/dev/null | head -1 | sed 's/.*=[[:space:]]*//; s/[^0-9].*//')"
    [ -n "$p" ] && printf '%s:%s\n' "$n" "$p"
  done
  return 0   # a final iface with no ListenPort would otherwise leave the loop non-zero → trips set -e at ports="$(turn_wg_ports)"
}
detect_turn(){   # any systemd unit whose ExecStart carries both -listen and -connect is a turn-proxy
  TP_LISTEN=(); TP_CONNECT=(); TP_WRAP=(); local u name exe lis con wk envf params
  for u in /etc/systemd/system/*.service; do
    [ -e "$u" ] || continue
    exe="$(sed -n 's/^ExecStart=//p' "$u" 2>/dev/null | head -1)"
    case "$exe" in *-listen*-connect*|*-connect*-listen*) ;; *) continue;; esac
    name="$(basename "$u" .service)"
    case "$exe" in
      *'${SWG_'*)   # EnvironmentFile form — read listen/connect/params out of turn.env
        envf="$(sed -n 's/^EnvironmentFile=-\{0,1\}//p' "$u" 2>/dev/null | head -1)"
        lis="$(sed -n 's/^SWG_LISTEN=//p' "$envf" 2>/dev/null | head -1)"
        con="$(sed -n 's/^SWG_CONNECT=//p' "$envf" 2>/dev/null | head -1)"
        params="$(sed -n 's/^SWG_PARAMS=//p' "$envf" 2>/dev/null | head -1)"
        wk="$(printf '%s\n' "$params" | sed -n 's/.*-wrap-key[ =]\{1,\}\([^ ]*\).*/\1/p')" ;;
      *)            # legacy baked-ExecStart form
        lis="$(printf '%s\n' "$exe" | sed -n 's/.*-listen[ =]\{1,\}\([^ ]*\).*/\1/p')"
        con="$(printf '%s\n' "$exe" | sed -n 's/.*-connect[ =]\{1,\}\([^ ]*\).*/\1/p')"
        wk="$(printf '%s\n' "$exe" | sed -n 's/.*-wrap-key[ =]\{1,\}\([^ ]*\).*/\1/p')" ;;
    esac
    TP_LISTEN[$name]="$lis"; TP_CONNECT[$name]="$con"; TP_WRAP[$name]="$wk"
  done
}
turn_latest_tag(){ $DRYRUN && { echo "v0.0.0"; return 0; }   # turn_latest_tag <owner/repo>
  curl -fsSL --connect-timeout 10 --max-time 20 "https://api.github.com/repos/$1/releases/latest" 2>/dev/null \
    | python3 -c 'import sys,json;print(json.load(sys.stdin).get("tag_name",""))' 2>/dev/null || true; }
install_turn_binary(){ # <fork> <owner/repo> <listen ip:port> <connect ip:port> <extra-flags>
  local fork="$1" owner="$2" listen="$3" connect="$4" extra="$5" arch dir bin svc url ver port inst fdir sbin
  case "$(uname -m)" in x86_64|amd64) arch=amd64;; aarch64|arm64) arch=arm64;; *) arch=amd64;; esac
  # key each instance by <fork>-<port> so one fork can run many times (different ports + wrap keys)
  port="${listen##*:}"; inst="$fork-$port"; svc="vk-turn-proxy-$inst"
  fdir="$TURN_DIR/.bin/$fork"; sbin="$fdir/server"   # ONE binary per fork — shared by every instance
  dir="$TURN_DIR/$inst"; bin="$dir/server"            # this instance: turn.env + a 'server' symlink → the shared binary
  if [ -e "/etc/systemd/system/$svc.service" ]; then warn "turn-proxy $svc already exists — pick another port"; return 0; fi
  url="https://github.com/$owner/releases/latest/download/server-linux-$arch"
  mkdir -p "$PREFIX$fdir" "$PREFIX$dir"
  if $DRYRUN; then echo "    [skip] reuse-or-download the $fork binary → $sbin"
  elif [ -x "$PREFIX$sbin" ]; then info "reusing the $fork binary already downloaded ($sbin)"
  else
    info "Installing $owner ($listen → $connect) — downloading the binary from GitHub (up to ~2 min)…"
    if ! { dl_turn_bin "$owner" "$arch" "$PREFIX$sbin" && chmod +x "$PREFIX$sbin"; }; then
      warn "download failed for $owner — skipping this turn-proxy (retry later, or set SWG_TURN_MIRROR=<proxy> and re-run)"; return 0
    fi
  fi
  $DRYRUN || ln -sfn "../.bin/$fork/server" "$PREFIX$bin"   # ExecStart points here; resolves to the shared binary
  ver="$(turn_latest_tag "$owner")"
  printf '%s\n' "$owner"        | writef "$fdir/repo.txt" 644
  printf '%s\n' "${ver:-unknown}" | writef "$fdir/version.txt" 644
  # listen/connect/params live in turn.env so a panel edit only rewrites it + restarts (no daemon-reload)
  writef "$dir/turn.env" 600 <<EOF
SWG_LISTEN=${listen}
SWG_CONNECT=${connect}
SWG_PARAMS=${extra}
EOF
  writef "/etc/systemd/system/$svc.service" 600 <<EOF
[Unit]
Description=vk-turn-proxy ($owner) — ${listen} → ${connect}
After=network-online.target
Wants=network-online.target

[Service]
EnvironmentFile=-${dir}/turn.env
ExecStart=${bin} -listen \${SWG_LISTEN} -connect \${SWG_CONNECT} \$SWG_PARAMS
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  run systemctl daemon-reload; run systemctl enable --quiet --now "$svc" || warn "couldn't start $svc"
  ok "installed turn-proxy $(col "$C_GREEN" "$inst") ($owner ${ver:-?}) — $listen → $connect"
}
# turn-proxy forward-to value: accept an interface NAME (resolved to 127.0.0.1:<its listen port>) or a custom ip:port.
v_fwd(){ local names; names=" $(turn_wg_ports | cut -d: -f1 | tr '\n' ' ')"; case "$names" in *" $1 "*) return 0;; esac; v_hostport "$1"; }
fwd_resolve(){ local n p; while IFS=: read -r n p; do [ -n "$n" ] && [ "$n" = "$1" ] && { echo "127.0.0.1:$p"; return; }; done <<< "$(turn_wg_ports)"; echo "$1"; }
install_turn_proxy(){   # <fork> — params, then install (the fork is chosen in choose_turn_proxy)
  local sel="$1" owner pub port connect; owner="$(turn_repo_owner "$sel")" || { warn "unknown turn-proxy branch: $sel"; return 0; }
  ask_valid "Public IP this turn-proxy is reached at" "$(detect_public_ip)" pub v_host "an IP or hostname"
  ask_valid "Turn-proxy listen port" "$(turn_default_port)" port v_freeport "port 1–65535 and free (not already in use)"
  detect_turn; local _n; for _n in "${!TP_LISTEN[@]}"; do [ "${TP_LISTEN[$_n]##*:}" = "$port" ] && { warn "port $port is already used by turn-proxy '$_n' — pick another port (enter 'new' again)"; return 0; }; done
  local ports defport=51820 defname="127.0.0.1:51820" n p proto label clabel pad; ports="$(turn_wg_ports)"
  echo
  if [ -n "$ports" ]; then
    defname="$(printf '%s\n' "$ports" | head -1 | cut -d: -f1)"   # first interface NAME
    echo "  Available wg/awg interfaces:"
    while IFS=: read -r n p; do proto="${IF_CMD[$n]:-wg}"
      label="[$n] on $proto"; clabel="$(col "$C_GREEN" "[$n]") on $(b "$proto")"
      pad=$((15 - ${#label})); [ "$pad" -lt 1 ] && pad=1
      printf '    %s%*s%s\n' "$clabel" "$pad" "" "$(col "$C_BLUE" "127.0.0.1:$p")"
    done <<< "$ports"
  fi
  ask_valid "WireGuard/AmneziaWG address it forwards to - interface name or custom ip:port" "$defname" connect v_fwd "an interface name (e.g. awg0) or ip:port"
  connect="$(fwd_resolve "$connect")"
  echo
  local wrap; wrap="$(turn_wrap_flags "$sel")"
  [ -n "$wrap" ] && info "Obfuscation: a 64-hex wrap key is generated, baked into the unit, and recorded for the panel / client configs." \
                 || warn "$sel has no wrap/srtp obfuscation flags — installing plain (-listen/-connect only)."
  install_turn_binary "$sel" "$owner" "$pub:$port" "$connect" "$wrap"
}
write_turn_record(){   # record detected turn-proxies for the panel (Phase 2: direct-vs-turn + wrap key for client configs)
  detect_turn; local json="" sep="" n
  for n in "${!TP_LISTEN[@]}"; do
    json+="$sep    { \"service\": \"$n\", \"listen\": \"${TP_LISTEN[$n]}\", \"connect\": \"${TP_CONNECT[$n]}\", \"wrap_key\": \"${TP_WRAP[$n]}\" }"; sep=$',\n'
  done
  writef "$TURN_RECORD" 640 <<EOF
{
  "turn_proxies": [
$json
  ]
}
EOF
}
choose_turn_proxy(){   # one looped step: list installed (if any) + available branches; a branch installs, Enter proceeds
  info "Checking for turn-proxy servers on this host…"
  local sel names n
  while :; do
    detect_turn; names=("${!TP_LISTEN[@]}")
    echo
    if [ "${#names[@]}" -gt 0 ]; then
      echo "  Installed turn-proxy servers:"; echo
      for n in "${names[@]}"; do _fw="$(fwd_ifaces "${TP_CONNECT[$n]}")"; printf '    %s%s%s %s → %s%s\n' "$C_GREEN" "$n" "$RESET" "${TP_LISTEN[$n]}" "${TP_CONNECT[$n]}" "${_fw:+ $(col "$C_GREEN" "($_fw)")}"; done
      echo
    else
      warn "No turn-proxy servers found on this box."
    fi
    echo
    echo "  Here is a list of turn-proxy branches available for installation:"
    echo
    menu "$(col "$C_BLUE" '[0] [c]acggghp')"     "The original project - https://github.com/cacggghp/vk-turn-proxy"
    menu "$(col "$C_BLUE" '[1] [W]INGS-N')"      "Fork by WINGS-N - https://github.com/WINGS-N/vk-turn-proxy"
    menu "$(col "$C_BLUE" '[2] [s]amosvalishe')" "Fork by samosvalishe - https://github.com/samosvalishe/vk-turn-proxy"
    menu "$(col "$C_BLUE" '[3] [k]iper292')"     "Fork by kiper292 - https://github.com/kiper292/vk-turn-proxy"
    menu "$(col "$C_BLUE" '[4] [M]oroka8')"      "Fork by Moroka8 - https://github.com/Moroka8/vk-turn-proxy"
    menu "$(col "$C_BLUE" '[5] [a]nton48')"      "Fork by anton48 - https://github.com/anton48/vk-turn-proxy"
    printf '  Enter a number, letter or name to install, or just press %s to skip and proceed with the setup: ' "$(b Enter)"
    if ! read -r sel 2>/dev/null </dev/tty; then echo; warn "no interactive input — skipping turn-proxy step"; break; fi
    sel="${sel//[[:space:]]/}"
    [ -z "$sel" ] && break
    sel="$(printf '%s' "$sel" | tr '[:upper:]' '[:lower:]')"   # case-insensitive (W/w, M/m, …)
    case "$sel" in
      0|c|cacggghp|original|main)  install_turn_proxy cacggghp; continue;;
      1|w|wings|wings-n)           install_turn_proxy WINGS-N; continue;;
      2|s|samosvalishe)            install_turn_proxy samosvalishe; continue;;
      3|k|kiper|kiper292)          install_turn_proxy kiper292; continue;;
      4|m|moroka|moroka8)          install_turn_proxy Moroka8; continue;;
      5|a|anton|anton48)           install_turn_proxy anton48; continue;;
      *) warn "enter 0–5, a letter (c/w/s/k/m/a) or a name (or press Enter to skip)";;
    esac
  done
  write_turn_record
}

ensure_wg_tools(){ # ensure_wg_tools <awg|wg> — install tools + kernel module if missing (idempotent, non-fatal -> 0/1)
  local cmd="$1"
  have "$cmd" && return 0
  info "installing $([ "$cmd" = wg ] && echo 'WireGuard' || echo 'AmneziaWG') tools via apt — this can take a minute…"
  if [ "$cmd" = wg ]; then
    run apt-get update -qq || true; run apt-get install -y wireguard || true
  else
    run apt-get update -qq || true; run apt-get install -y software-properties-common || true
    run add-apt-repository -y ppa:amnezia/ppa || true; run apt-get update -qq || true; run apt-get install -y amneziawg || true
  fi
  $DRYRUN && return 0
  have "$cmd"               # success only if the tool is actually present now
}
awg_obfuscation(){ # emit AmneziaWG v2 obfuscation — H1–H4 ranges, S1–S4, and a conservative QUIC-Initial I1
  local s1 s2 s3 s4 b1 b2 b3 b4 w=15
  s1=$(( 15 + RANDOM % 136 )); s2=$(( 15 + RANDOM % 136 ))
  while [ "$s1" -eq "$s2" ] || [ $((s1+56)) -eq "$s2" ]; do s2=$(( 15 + RANDOM % 136 )); done
  s3=$(( 15 + RANDOM % 86 )); s4=$(( 15 + RANDOM % 86 ))   # v2 init/response junk sizes
  b1=$(( 5          + (RANDOM*RANDOM) % 900000000 ))       # four disjoint bands keep H1–H4
  b2=$(( 1000000000 + (RANDOM*RANDOM) % 900000000 ))       # distinct and non-overlapping, all > 4
  b3=$(( 2000000000 + (RANDOM*RANDOM) % 900000000 ))
  b4=$(( 3000000000 + (RANDOM*RANDOM) % 900000000 ))
  printf 'Jc = 4\nJmin = 40\nJmax = 70\nS1 = %s\nS2 = %s\nS3 = %s\nS4 = %s\nH1 = %s-%s\nH2 = %s-%s\nH3 = %s-%s\nH4 = %s-%s\n' \
    "$s1" "$s2" "$s3" "$s4" "$b1" $((b1+w)) "$b2" $((b2+w)) "$b3" $((b3+w)) "$b4" $((b4+w))
  # Conservative QUIC-Initial mimicry on I1 only (no <c> counters, no <t> — keeps amneziawg-go/Android working).
  # 0xc3 = long-header Initial first byte; 0x00000001 = QUIC v1; then random payload.
  printf 'I1 = <b 0xc300000001><r 1200>\n'
}
server_addr(){ # server_addr <cidr> -> "<first-host>/<prefix>"
  have python3 || die "python3 is required to compute the tunnel address (it's also needed by the daemon)"
  python3 - "$1" <<'PY'
import ipaddress, sys
n = ipaddress.ip_network(sys.argv[1], strict=False)
print(f"{next(n.hosts())}/{n.prefixlen}")
PY
}
# pick a default tunnel subnet that isn't already taken — by a queued spec OR a persisted interface — so a
# 2nd interface doesn't collide with a non-default subnet the user chose for the 1st (and v_subnet_free rejects a typed dup).
_net24(){ local ip="${1%%/*}" m="${1##*/}"; [ "$1" = "$m" ] && m=24; printf '%s.0/%s' "${ip%.*}" "$m"; }   # 10.9.0.1/24 → 10.9.0.0/24
subnet_used(){ local s n a; s="$(_net24 "$1")"
  for n in ${SPEC_ORDER[@]+"${SPEC_ORDER[@]}"}; do [ -n "${SPEC_SUBNET[$n]:-}" ] && [ "$(_net24 "${SPEC_SUBNET[$n]}")" = "$s" ] && return 0; done
  for n in "${!IF_CONF[@]}"; do a="$(sed -n 's/^[[:space:]]*Address[[:space:]]*=[[:space:]]*\([0-9./]*\).*/\1/p' "${IF_CONF[$n]}" 2>/dev/null | head -1)"; [ -n "$a" ] && [ "$(_net24 "$a")" = "$s" ] && return 0; done
  return 1; }
# default subnet = (highest used 10.X.0.0/24 second-octet)+1, then the next free above it (10.8 if none).
next_free_subnet(){ local hi=7 n a o
  for n in ${SPEC_ORDER[@]+"${SPEC_ORDER[@]}"}; do a="${SPEC_SUBNET[$n]:-}"; [ -n "$a" ] || continue; o="$(_net24 "$a" | cut -d. -f2)"; case "$o" in ''|*[!0-9]*) :;; *) [ "$o" -gt "$hi" ] && hi="$o";; esac; done
  for n in "${!IF_CONF[@]}"; do a="$(conf_get "${IF_CONF[$n]}" Address)"; [ -n "$a" ] || continue; o="$(_net24 "$a" | cut -d. -f2)"; case "$o" in ''|*[!0-9]*) :;; *) [ "$o" -gt "$hi" ] && hi="$o";; esac; done
  o=$((hi+1)); while [ "$o" -lt 255 ] && subnet_used "10.$o.0.0/24"; do o=$((o+1)); done; echo "10.$o.0.0/24"; }
# default interface index = (highest numeric suffix across existing + queued names)+1 (awg3,wg4 → 5).
iface_next_index(){ local hi=-1 n s; for n in "${!IF_CMD[@]}" ${SPEC_ORDER[@]+"${SPEC_ORDER[@]}"}; do s="${n##*[!0-9]}"; case "$s" in ''|*[!0-9]*) :;; *) [ "$s" -gt "$hi" ] && hi="$s";; esac; done; echo $((hi+1)); }
v_subnet_free(){ v_subnet "$1" || return 1; subnet_used "$1" && return 1; return 0; }
# Two-phase interface creation: spec_iface() only PROMPTS and queues a spec, so the user can add
# every interface up front; apply_specs() then installs tools + writes confs + brings them all up
# once, at the end. Queued names show in 'mine' (via CREATED) and block name collisions immediately.
spec_iface(){ # prompt for one interface and queue it (no install yet)
  local _proto proto name port subnet addr cmd dir wan ep idx defname defport defsub
  idx=$(( ${#IF_CMD[@]} + ${#SPEC_ORDER[@]} ))   # offset defaults past existing + already-queued ifaces
  menu "$(col "$C_BLUE" '[1]') $(keyd a 'mneziawg (default)')" "WireGuard with AmneziaWG obfuscation. Runs on the host's AmneziaWG kernel module."
  menu "$(col "$C_BLUE" '[2]') $(key w 'ireguard')"            "Plain WireGuard — no obfuscation, lowest overhead. Runs on the host's WireGuard kernel module."
  ask_choice "Select the protocol you want to create (number, letter or name)" "a" _proto "a w awg wg amneziawg wireguard"
  case "$_proto" in w|wg|wireguard) proto=wg; cmd=wg;  dir=/etc/wireguard;;
                                 *) proto=awg; cmd=awg; dir=/etc/amnezia/amneziawg;; esac
  local nidx; nidx=$(iface_next_index)   # name = highest-suffix+1, bumped past any exact collision
  defname="$([ "$cmd" = awg ] && echo "awg$nidx" || echo "wg$nidx")"
  while [ -n "${IF_CMD[$defname]:-}" ] || [ -n "${SPEC_CMD[$defname]:-}" ] || [ -e "/etc/amnezia/amneziawg/$defname.conf" ] || [ -e "/etc/wireguard/$defname.conf" ]; do
    nidx=$((nidx+1)); defname="$([ "$cmd" = awg ] && echo "awg$nidx" || echo "wg$nidx")"; done
  while :; do
    ask_valid "Interface name" "$defname" name v_iface "1–15 chars: letters, digits, - or _"
    if [ -n "${IF_CMD[$name]:-}" ] || [ -n "${SPEC_CMD[$name]:-}" ] || [ -e "/etc/amnezia/amneziawg/$name.conf" ] || [ -e "/etc/wireguard/$name.conf" ]; then
      warn "interface '$name' already exists — pick another name"; name=""; continue
    fi
    break
  done
  defport=$(iface_default_port "$idx"); defsub="$(next_free_subnet)"
  ask_valid "Listen port" "$defport" port v_freeport "port 1–65535 and free (not already in use)"
  ask_valid "Tunnel subnet (CIDR; server takes the first host)" "$defsub" subnet v_subnet_free "a CIDR not already used, e.g. 10.8.0.0/24"
  addr="$(server_addr "$subnet")"
  echo "    server address $(col "$C_GREEN" "$addr") — peers get the rest of $subnet"
  wan="$(detect_wan)"; [ -n "$wan" ] || wan=eth0             # auto WAN egress NIC — clients NAT out this (change it later in the panel)
  echo "    Used $(bb "$wan") egress interface for $(col "$C_GREEN" "$name")"
  ep="$(detect_public_ip)"                                   # auto endpoint clients dial — public IP/host (change it later in the panel)
  echo "    Used $(bb "$ep") endpoint IP for $(col "$C_GREEN" "$name")"
  SPEC_CMD[$name]="$cmd"; SPEC_PROTO[$name]="$proto"; SPEC_PORT[$name]="$port"; SPEC_SUBNET[$name]="$subnet"
  SPEC_ADDR[$name]="$addr"; SPEC_WAN[$name]="$wan"; SPEC_EP[$name]="$ep"; SPEC_DIR[$name]="$dir"
  SPEC_ORDER+=("$name"); CREATED+=("$name")                  # CREATED makes it show in 'mine' on the next pass
  ok "queued interface $(col "$C_GREEN" "$name") ($proto, :$port) — installed once you finish adding interfaces"
}
apply_specs(){ # install tools + write confs + bring up every queued interface, then prune failures
  [ "${#SPEC_ORDER[@]}" -gt 0 ] || return 0
  local name proto port subnet addr conf cmd priv dir wan up down upok ep failed=""
  echo; info "Setting up ${#SPEC_ORDER[@]} interface(s)…"
  for name in "${SPEC_ORDER[@]}"; do
    cmd="${SPEC_CMD[$name]}"; proto="${SPEC_PROTO[$name]}"; port="${SPEC_PORT[$name]}"; subnet="${SPEC_SUBNET[$name]}"
    addr="${SPEC_ADDR[$name]}"; wan="${SPEC_WAN[$name]}"; ep="${SPEC_EP[$name]}"; dir="${SPEC_DIR[$name]}"; conf="$dir/$name.conf"
    if ! ensure_wg_tools "$cmd"; then warn "couldn't install $cmd tools — skipping interface '$name'"; failed="$failed $name"; continue; fi
    # gateway plumbing: forward + masquerade the tunnel subnet out the WAN (bound to iface lifecycle)
    up="sysctl -q -w net.ipv4.ip_forward=1; iptables -t nat -A POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -A FORWARD -i %i -o ${wan} -j ACCEPT; iptables -A FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
    down="iptables -t nat -D POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -D FORWARD -i %i -o ${wan} -j ACCEPT; iptables -D FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
    printf 'net.ipv4.ip_forward = 1\n' | writef /etc/sysctl.d/99-swg-forward.conf 644
    run sysctl -q -w net.ipv4.ip_forward=1
    if $DRYRUN; then priv="<generated-on-real-run>"
    elif ! priv="$("$cmd" genkey 2>/dev/null)" || [ -z "$priv" ]; then warn "'$cmd genkey' failed — skipping interface '$name'"; failed="$failed $name"; continue; fi
    { printf '[Interface]\nPrivateKey = %s\nAddress = %s\nListenPort = %s\nMTU = %s\n' "$priv" "$addr" "$port" "$WG_MTU"
      printf 'PostUp = %s\nPostDown = %s\n' "$up" "$down"
      if [ "$cmd" = awg ]; then awg_obfuscation; fi; } | writef "$conf" 600
    # bring up — NON-FATAL: a port/subnet clash must not abort the whole install (set -e)
    upok=yes
    if [ "$cmd" = awg ]; then bringup awg-quick "$name" || upok=no; [ "$upok" = yes ] && { run systemctl enable --quiet "awg-quick@$name" || true; }
    else                     bringup wg-quick  "$name" || upok=no; [ "$upok" = yes ] && { run systemctl enable --quiet "wg-quick@$name"  || true; }; fi
    if [ "$upok" = no ]; then
      warn "couldn't bring up '$name' (a port or subnet may already be in use) — removing its conf; try again with different values"
      run rm -f "$conf"; failed="$failed $name"; continue
    fi
    IF_CMD[$name]="$cmd"; IF_CONF[$name]="$conf"; IF_ENDPOINT[$name]="$ep"; LAST_IFACE="$name"
    ok "created $proto interface $(col "$C_GREEN" "$name") on :$port (server $addr, NAT out $wan)"
  done
  if [ -n "$failed" ]; then   # drop interfaces that failed to come up from the selected set
    local keep=() n; for n in ${SELECTED[@]+"${SELECTED[@]}"}; do _in "$n" "$failed" || keep+=("$n"); done; SELECTED=(${keep[@]+"${keep[@]}"})
  fi
}

# ───────────────────────── prompts ─────────────────────────
[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && { info "DRY RUN — files render under ./dryrun, nothing executes."; rm -rf "$PREFIX"; }

# ═══════════════ I. PANEL SETUP ═══════════════
echo; info "BARE-METAL SWG PANEL SETUP"

# Idempotent re-install: detect an existing panel UP FRONT and offer its saved answers as the
# defaults for every step (mirrors the docker installer's .env reuse). To start fresh, uninstall first.
EXISTING_HOST=no; KEEP_AUTH=no
DOM_SAVED=""; BASE_SAVED=""; PORT_SAVED=""; TLS_SAVED=""; SERVE_SAVED=""; ROLE_SAVED=""; EMAIL_SAVED=""; NODENAME_SAVED=""; ENDPOINT_SAVED=""
_unit=/etc/systemd/system/swg-panel-server.service
if [ -f "$ETC_DIR/auth" ] || [ -f "$_unit" ]; then
  EXISTING_HOST=yes; KEEP_AUTH=yes
  [ "${BASIC_USER:-admin}" = admin ] && [ -f "$ETC_DIR/auth" ] && BASIC_USER="$(cut -d: -f1 "$ETC_DIR/auth" 2>/dev/null || echo admin)"
  if [ -f "$ETC_DIR/install.conf" ]; then                 # snapshot of the previous install's answers
    DOM_SAVED="$(sed -n 's/^PANEL_DOMAIN=//p'        "$ETC_DIR/install.conf" | head -1)"
    BASE_SAVED="$(sed -n 's/^PANEL_BASE=//p'         "$ETC_DIR/install.conf" | head -1)"
    PORT_SAVED="$(sed -n 's/^PORT=//p'               "$ETC_DIR/install.conf" | head -1)"
    TLS_SAVED="$(sed -n 's/^TLS_MODE=//p'            "$ETC_DIR/install.conf" | head -1)"
    SERVE_SAVED="$(sed -n 's/^SERVE_MODE=//p'        "$ETC_DIR/install.conf" | head -1)"
    ROLE_SAVED="$(sed -n 's/^ROLE_SEL=//p'           "$ETC_DIR/install.conf" | head -1)"
    EMAIL_SAVED="$(sed -n 's/^ACME_EMAIL=//p'        "$ETC_DIR/install.conf" | head -1)"
    NODENAME_SAVED="$(sed -n 's/^HOST_NODE_NAME=//p' "$ETC_DIR/install.conf" | head -1)"
    ENDPOINT_SAVED="$(sed -n 's/^HOST_ENDPOINT_IP=//p' "$ETC_DIR/install.conf" | head -1)"
    # CF tokens load straight into the live vars so the prompt self-skips and re-issue (if any) just works
    [ -z "$CF_TOKEN" ]        && CF_TOKEN="$(sed -n 's/^CF_TOKEN=//p'               "$ETC_DIR/install.conf" | head -1)"
    [ -z "$CF_ORIGIN_TOKEN" ] && CF_ORIGIN_TOKEN="$(sed -n 's/^CF_ORIGIN_TOKEN=//p' "$ETC_DIR/install.conf" | head -1)"
  fi
  # fallback for installs predating install.conf: recover PORT + subpath from the running unit
  [ -z "$PORT_SAVED" ] && [ -f "$_unit" ] && PORT_SAVED="$(sed -n 's/^Environment=SWG_PANEL_PORT=//p' "$_unit" | head -1)"
  [ -z "$BASE_SAVED" ] && [ -f "$_unit" ] && BASE_SAVED="$(sed -n 's/^Environment=SWG_PANEL_BASE=//p' "$_unit" | head -1)"
  info "Existing panel install detected — keeping your login, users, nodes + certs; your previous settings are the defaults below. To start fresh, run the uninstaller first."
fi

# RE-INSTALL: signal "re-installing" the MOMENT the script starts (before any prompt) and ARM the lifecycle
# traps now, so an abort/failure at ANY point is reported. Emits to BOTH the panel header (host_proc file)
# and — if this box has a local node (master) — that node's tile. A re-install always installs the latest, so
# the terminal is "re-installed and updated".
if [ "$EXISTING_HOST" = yes ] && ! $DRYRUN; then
  mkdir -p "$STATE_DIR" 2>/dev/null || true
  LC_FILE="$STATE_DIR/host_proc"
  if [ -f /etc/swg-agent/config.json ]; then   # a local node exists (master) → also drive its tile
    LC_URL="$(python3 -c 'import json;print((json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("url",""))' 2>/dev/null || true)"
    LC_TOKEN="$(python3 -c 'import json;print((json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("token",""))' 2>/dev/null || true)"
    LC_VERIFY="$(python3 -c 'import json;print("yes" if (json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("verify",True) else "no")' 2>/dev/null || echo no)"
  fi
  lc_emit_host(){ lc_emit_file "$1" "${2:-}"; lc_emit_post "$1" "${2:-}"; }   # host_proc + (master) the local node
  # SWG_LC_PARENT=1 ⇒ convert.sh (a docker→bare host/master convert) owns the lifecycle terminal, so it can emit
  # "converted" WITH its final summary instead of us firing it mid-flow before the node phase. Skip our own lc_init.
  [ "${SWG_LC_PARENT:-}" = 1 ] || lc_init "${SWG_CONVERT_DIR:-reinstall}" lc_emit_host   # convert.sh passes convert-bare → "converting/converted to bare-metal"
  [ -z "${SWG_CONVERT_DIR:-}" ] && LC_SUCCESS="reinstalled-updated"   # plain re-install installs the latest; a convert keeps its converted-bare success
fi
# deferred-start convert (SWG_DEFER_START=1): install + enable the panel but DON'T start it here — the docker panel
# still holds :443 and keeps serving the UI; convert.sh stops docker + starts it at the switch. _NOW = "--now"
# normally, empty when deferred, applied to every `systemctl enable … swg-panel-server`.
_NOW="--now"; [ "${SWG_DEFER_START:-}" = 1 ] && _NOW=""

# Server role — skipped when already chosen (e.g. by bootstrap.sh)
ROLE_SEL=""
case "$ROLE" in master|host+node) ROLE_SEL=master;; host) ROLE_SEL=host;; node) die "for a node-only box run install-node.sh, not this script";; esac
if [ -z "$ROLE_SEL" ]; then
  step "Server role"
  menu "$(b "$(col "$C_BLUE" '[1] master (default)')")" "Masternode — this server will host the panel and run WG/AWG interfaces"
  menu "$(col "$C_BLUE" '[2] host')"                     "This server will host only the panel. WG/AWG nodes will be deployed separately"
  ask_choice "Select role (number, letter or name)" "${ROLE_SAVED:-master}" ROLE_SEL "master host"
fi
case "$ROLE_SEL" in master) ROLE="host+node";; host) ROLE="host";; esac
HOST_HAS_WG=no; [ "$ROLE" = "host+node" ] && HOST_HAS_WG=yes

# panel URL (may include a subpath, e.g. vpn.example.com/swg)
step "Panel URL"
echo
echo "      Where the panel is reached — an IP, a host, or a host with a subpath to"
echo "      live under an existing site (e.g. $(b 'vpn.example.com/swg'))."
echo
DEF_URL="$(detect_public_ip)"; [ -z "$DEF_URL" ] && DEF_URL=localhost
if [ -n "$DOM_SAVED" ]; then DEF_URL="$DOM_SAVED"          # re-install: rebuild the saved host[:port][/subpath]
  { [ -n "$PORT_SAVED" ] && [ "$PORT_SAVED" != 443 ]; } && DEF_URL="$DEF_URL:$PORT_SAVED"
  [ -n "$BASE_SAVED" ] && DEF_URL="$DEF_URL$BASE_SAVED"
fi
PANEL_DOMAIN=""; ask_valid "Enter panel URL (https://…)" "$DEF_URL" PANEL_DOMAIN v_url "enter a host or IP, optionally with a /subpath (e.g. vpn.example.com/swg)"
while :; do
  parse_panel_url "$PANEL_DOMAIN"
  # is the port the panel will use free on this host? (catches nginx/apache or a prior panel)
  _pp="${URL_PORT:-443}"
  # block only on a REAL conflict — skip when our own panel already holds the port (a re-install; install
  # stops/restarts it on the same port), and skip during a deferred-start convert (the docker panel is holding the
  # port and is torn down at the switch, just before we start the bare panel — see convert.sh).
  if [ "${_forced:-}" != "$_pp" ] && [ "${SWG_DEFER_START:-}" != 1 ] && ! $DRYRUN && have ss && [ -n "$(ss -lntH "sport = :$_pp" 2>/dev/null)" ] && ! panel_owns_port "$_pp"; then
    _who="$(ss -lntpH "sport = :$_pp" 2>/dev/null | grep -oE '"[^"]+"' | head -1 | tr -d '"' || true)"
    echo; warn "port $(col "$C_YEL" ":$_pp") is already in use${_who:+ (by $(col "$C_YEL" "$_who"))}"
    echo "    Running the panel $(b standalone)? Give it a free port, e.g. $(b "${PANEL_HOST_NOPORT}:8443")."
    echo "    Serving it $(b behind) that web server (the next step offers nginx/caddy)? Then $(bb force) is fine."
    printf '  Enter a different URL, or type %s to keep :%s anyway: ' "$(bb force)" "$_pp"
    read -r _url_ans 2>/dev/null </dev/tty || _url_ans=force
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
  read -r _url_ans 2>/dev/null </dev/tty || _url_ans=proceed
  case "$(printf '%s' "$_url_ans" | tr -d '[:space:]')" in
    proceed|"") break;;                                           # keep the current port
    *) if v_url "$_url_ans"; then PANEL_DOMAIN="$_url_ans"        # adopt the new URL; loop re-parses + re-checks
       else warn "‘$_url_ans’ isn't a valid host/URL — try again."; fi ;;
  esac
done
PANEL_DOMAIN="$PANEL_HOST_NOPORT"
[ -z "$PANEL_DOMAIN" ] && PANEL_DOMAIN=localhost
[ -n "$PANEL_BASE" ] && ok "panel will be served under subpath ${PANEL_BASE}/"

# TLS certificate
step "TLS certificate"
echo
# re-install with a cert already in $TLS_DIR → offer to KEEP it (default), no re-issue.
# canonicals first (so [N] maps to the displayed order), letter aliases after; _tn numbers the shown items
# Panel URL shape decides which certs are offered:
#   domain (FQDN)   → letsencrypt / cloudflare / cf15  (the CA validates a domain)
#   public IP       → letsencrypt-ip                   (LE short-lived IP cert, ~6d, auto-renews)
#   private / bare  → none of the above                (no CA will issue → selfsigned/skip only)
_url_is_domain=no; case "$PANEL_DOMAIN" in *[a-zA-Z]*) case "$PANEL_DOMAIN" in *.*) _url_is_domain=yes;; esac;; esac
_ip_public=no; [ "$_url_is_domain" = yes ] || { ip_public "$PANEL_DOMAIN" && _ip_public=yes; }
# default = each branch's recommended primary (NOT the saved mode — a saved letsencrypt-ip is meaningless on a
# domain URL, etc.; 'reuse' below is the real "keep what you had" and wins as default when the cert still fits).
if   [ "$_url_is_domain" = yes ]; then _tls_opts="letsencrypt cloudflare cf15 selfsigned none l c cf 15 15years 15cf s self n skip sk"; _tls_def=l
elif [ "$_ip_public" = yes ];     then _tls_opts="letsencrypt-ip selfsigned none lip ip letsencrypt l s n skip sk"; _tls_def=letsencrypt-ip
else                                   _tls_opts="selfsigned none s n skip sk";                                    _tls_def=s; fi
# Offer 'reuse' ONLY if the existing cert actually covers this URL (host in its SAN/CN). A cert issued for a
# different host/IP (e.g. a letsencrypt-ip cert when you now type a private IP) would be wrong here, so hide
# reuse and let the working default win — that also avoids showing two "(default)" options.
_reuse_avail=no
# ...offer it for a re-install (existing host) AND for a convert (SWG_CONVERT_DIR): the convert STAGES the panel's
# real cert into $TLS_DIR before running us, so it's just as reusable — without this a docker→bare convert would
# never reuse a Let's Encrypt cert and would silently re-issue (→ selfsigned on a localhost/IP).
if { [ "$EXISTING_HOST" = yes ] || [ -n "${SWG_CONVERT_DIR:-}" ]; } && [ -f "$PREFIX$TLS_DIR/fullchain.pem" ] && [ -f "$PREFIX$TLS_DIR/key.pem" ] \
   && cert_covers_host "$PREFIX$TLS_DIR/fullchain.pem" "$PANEL_DOMAIN"; then
  _reuse_avail=yes; _tls_opts="reuse $_tls_opts r"; _tls_def=r
fi
# exactly ONE "(default)" marker: reuse when offered, otherwise each branch's primary option carries it
if [ "$_reuse_avail" = yes ]; then _le_lbl="$(key l 'etsencrypt')";            _lip_lbl="$(key l 'etsencrypt-ip')";            _ss_lbl="$(key s 'elfsigned')"
else                               _le_lbl="$(keyd l 'etsencrypt (default)')"; _lip_lbl="$(keyd l 'etsencrypt-ip (default)')"; _ss_lbl="$(keyd s 'elfsigned (default)')"; fi
[ -z "$TLS_MODE" ] && [ -n "$CERT_FULLCHAIN" ] && [ -n "$CERT_KEY" ] && TLS_MODE=skip
case "$TLS_MODE" in manual|none) TLS_MODE=skip;; esac
# the loop re-asks (warn) instead of aborting if a cert is chosen that doesn't match the URL (e.g. env preset)
while :; do
  _tn=0
  [ "$_reuse_avail" = yes ] && { _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $(keyd r 'euse (default)')"       "Keep the existing $(b "${TLS_SAVED:-cert}") certificate — it already covers $(b "$PANEL_DOMAIN"), no re-issue (recommended for a re-install)"; }
  if [ "$_url_is_domain" = yes ]; then
    _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $_le_lbl"                           "Let's Encrypt cert via acme.sh HTTP-01 (needs port 80 reachable)"
    _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $(key c 'loudflare') + letsencrypt" "Let's Encrypt cert, validated via Cloudflare DNS-01 (no port 80) — needs a Zone:DNS:Edit+Read token + email"
    _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $(key 15 'years cloudflare')"       "Cloudflare Origin certificate, 15 years — ONLY valid behind Cloudflare's proxy (orange cloud); needs an API token (Zone → SSL and Certificates → Edit)"
    _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $(key s 'elfsigned')"               "OK for testing"
  elif [ "$_ip_public" = yes ]; then
    _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $_lip_lbl"                          "Trusted Let's Encrypt cert for this IP — short-lived (~6 days), auto-renews daily via acme.sh (needs :80 reachable + a direct/grey-cloud IP)"
    _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $(key s 'elfsigned')"               "Self-signed — the browser warns once (zero-maintenance, no port 80)"
  else
    _tn=$((_tn+1)); menu "$(col "$C_BLUE" "[$_tn]") $_ss_lbl"                           "Self-signed cert — the browser warns once (the realistic choice for an IP)"
  fi
  _tn=$((_tn+1)); menu "$(col "$C_GREY" "[$_tn]") $(keyg n 'one')"                     "No certificate issued — bring your own / terminate TLS elsewhere (plain HTTP otherwise)"
  [ "$_url_is_domain" = yes ] || [ "$_ip_public" = yes ] || sub "Let's Encrypt needs a public domain or public IP — hidden because $(b "$PANEL_DOMAIN") is private / not routable."
  ask_choice "Select TLS certificate (number, letter or name)" "$_tls_def" TLS_MODE "$_tls_opts"
  # map the choice to a canonical TLS_MODE. On an IP menu every 'letsencrypt' alias (l / ip / letsencrypt)
  # means the IP cert; 'none'/'n' is the display name for the no-cert mode (kept internally as 'skip').
  if [ "$_ip_public" = yes ]; then
    case "$TLS_MODE" in r) TLS_MODE=reuse;; l|ip|lip|letsencrypt|letsencrypt-ip) TLS_MODE=letsencrypt-ip;; s|selfsigned) TLS_MODE=selfsigned;; n|none|sk|skip) TLS_MODE=skip;; esac
  else
    case "$TLS_MODE" in r) TLS_MODE=reuse;; l) TLS_MODE=letsencrypt;; c|cf) TLS_MODE=cloudflare;; 15|15years|15cf) TLS_MODE=cf15;; s|self) TLS_MODE=selfsigned;; n|none|sk|skip) TLS_MODE=skip;; esac
  fi
  case "$TLS_MODE" in
    letsencrypt|cloudflare|cf15)   # domain-only — warn + re-ask if the URL isn't a domain
      if [ "$_url_is_domain" != yes ]; then
        echo; warn "$(b "$TLS_MODE") needs a domain (FQDN), but the panel URL ($(b "$PANEL_DOMAIN")) is an IP. Pick $([ "$_ip_public" = yes ] && printf 'letsencrypt-ip, ')selfsigned or none, or re-run with a domain URL."
        echo; TLS_MODE=""; continue; fi ;;
    letsencrypt-ip)                # public-IP-only — warn + re-ask otherwise
      if [ "$_ip_public" != yes ]; then
        echo; warn "$(b letsencrypt-ip) needs a public IP, but the panel URL is $(b "$PANEL_DOMAIN"). Pick $([ "$_url_is_domain" = yes ] && printf 'letsencrypt, ')selfsigned or none."
        echo; TLS_MODE=""; continue; fi ;;
  esac
  break
done
case "$TLS_MODE" in
  letsencrypt) ask_valid "ACME account email"                                     "${ACME_EMAIL:-$EMAIL_SAVED}" ACME_EMAIL v_email "enter a valid email, e.g. you@example.com";;
  letsencrypt-ip) warn "letsencrypt-ip issues a $(b 'short-lived (~6 day)') cert for $(b "$PANEL_DOMAIN") — acme.sh renews it daily; if renewal is down for ~6 days the cert expires."
               warn "Needs host port $(col "$C_YEL" ':80') reachable for HTTP-01 and the IP hit directly (grey-cloud / no proxy)."
               ask_valid "ACME account email"                                     "${ACME_EMAIL:-$EMAIL_SAVED}" ACME_EMAIL v_email "enter a valid email, e.g. you@example.com";;
  cloudflare)  ask_valid "Cloudflare API token (needs Zone:DNS:Edit + Zone:Read)" "" CF_TOKEN  v_cftoken "the API token can't be empty"   # pre-filled from the saved snapshot on re-install
               ask_valid "ACME account email"                                     "${ACME_EMAIL:-$EMAIL_SAVED}" ACME_EMAIL v_email "enter a valid email, e.g. you@example.com";;
  cf15)        warn "cf15 issues a Cloudflare Origin cert — it is ONLY trusted behind Cloudflare's proxy."
               warn "$PANEL_DOMAIN must be on Cloudflare with the orange cloud ON; a direct hit to the origin shows an untrusted cert."
               if [ -n "$URL_PORT" ] && ! v_cfport "$URL_PORT"; then
                 warn "port $(col "$C_YEL" "$URL_PORT") is NOT one Cloudflare's proxy forwards (only 443, 2053, 2083, 2087, 2096, 8443) —"
                 warn "the panel would be unreachable through the orange cloud. Use one of those ports (or Cloudflare Spectrum), or grey-cloud the record and accept an untrusted direct cert."
               fi
               ask_valid "Cloudflare API token (Zone → SSL and Certificates → Edit)" "" CF_ORIGIN_TOKEN v_cforigin "paste an API token — the legacy Origin CA Key is deprecated (sunset 2026-09-30)";;   # pre-filled from the saved snapshot on re-install
esac
# reuse → keep the existing cert; carry the previous real mode forward (serve logic + install.conf) and flag
# REUSE_TLS so the cert step skips re-issue. (reuse matched no case above, so no FQDN check / cred prompt ran.)
REUSE_TLS=no
if [ "$TLS_MODE" = reuse ]; then REUSE_TLS=yes; TLS_MODE="${TLS_SAVED:-selfsigned}"; ok "reusing the existing certificate in $TLS_DIR — no re-issue (TLS mode: $(b "$TLS_MODE"))"; fi

# web server
step "Web server"
echo
# re-install → offer to KEEP the current web-server mode (default), same as the TLS step. Accept the first
# letter OR the full word (both are listed as options).
_srv_opts="internal nginx caddy skip i n c s"; _srv_def=i; _int_lbl="$(keyd i 'nternal (default)')"; _sn=0
if [ "$EXISTING_HOST" = yes ] && [ -n "$SERVE_SAVED" ]; then
  _sn=$((_sn+1)); menu "$(col "$C_BLUE" "[$_sn]") $(keyd r 'euse (default)')"  "Keep the current web-server mode from this install ($(b "$SERVE_SAVED")) — recommended for a re-install"
  _srv_opts="reuse $_srv_opts r"; _srv_def=r; _int_lbl="$(key i 'nternal')"
fi
_sn=$((_sn+1)); menu "$(col "$C_BLUE" "[$_sn]") $_int_lbl"        "Self-contained, no separate web-server is required"
_sn=$((_sn+1)); menu "$(col "$C_BLUE" "[$_sn]") $(key n 'ginx')"  "Web content will be served via an Nginx reverse proxy"
_sn=$((_sn+1)); menu "$(col "$C_BLUE" "[$_sn]") $(key c 'addy')"  "Web content will be served via a Caddy reverse proxy"
_sn=$((_sn+1)); menu "$(col "$C_BLUE" "[$_sn]") $(key s 'kip')"   "If you are planning to configure the web server manually"
case "$SERVE_MODE" in standalone) SERVE_MODE=internal;; esac
ask_choice "Select web server (number, letter or name)" "$_srv_def" SERVE_MODE "$_srv_opts"
case "$SERVE_MODE" in r) SERVE_MODE=reuse;; i) SERVE_MODE=internal;; n) SERVE_MODE=nginx;; c) SERVE_MODE=caddy;; s) SERVE_MODE=skip;; esac
[ "$SERVE_MODE" = reuse ] && SERVE_MODE="${SERVE_SAVED:-internal}"

# port: internal serves the public port itself; proxy/manual modes keep the panel on a loopback port
if [ "$SERVE_MODE" = internal ]; then
  [ -z "$PORT" ] && PORT="${URL_PORT:-${PORT_SAVED:-443}}"
  ask_valid "Public HTTPS port for the panel" "$PORT" PORT v_port "port must be 1–65535"
else
  [ -z "$PORT" ] && PORT="${URL_PORT:-${PORT_SAVED:-8088}}"
fi

# (existing-install detection + saved-settings load happen up-front, at the top of PANEL SETUP)
# Admin login — auto-generated (username admin + 3 random digits, password random); both are
# printed at the end and can be changed later in the panel (Account). Override via BASIC_USER=/BASIC_PASS= env.
[ "$KEEP_AUTH" != yes ] && [ -z "$BASIC_PASS" ] && BASIC_PASS="$(head -c12 /dev/urandom | base64 | tr -d '/+=' | head -c16)"
if [ "$KEEP_AUTH" != yes ] && [ "${BASIC_USER}" = admin ]; then BASIC_USER="admin$(( RANDOM % 900 + 100 ))"; fi

# ═══════════════ II. NODE SETUP (master only) ═══════════════
declare -a SELECTED
if [ "$HOST_HAS_WG" = yes ]; then
  echo; info "BARE-METAL SWG NODE SETUP"
  step "Node name for THIS box"
  # default to the name the PANEL currently has for this box's local node (it may have been renamed in the
  # UI) — matched by verifying the agent token against each nodes.json token_hash; else saved name, else host.
  _pn="$(panel_node_name "$STATE_DIR/nodes.json" /etc/swg-agent/config.json)"
  ask_valid "Node name for THIS box" "${_pn:-${NODENAME_SAVED:-$(hostname -s 2>/dev/null || hostname)}}" HOST_NODE_NAME v_name "1–40 chars: letters, digits, - or _"
  step "WireGuard / AmneziaWG setup" "(each interface has its own endpoint IP)"
  echo
  choose_ifaces
  step "TURN-PROXY setup"
  echo
  choose_turn_proxy
fi

echo; info "Plan: method=$METHOD role=$ROLE serve=$SERVE_MODE tls=$TLS_MODE base=${PANEL_BASE:-/} store_configs=$STORE_CONFIGS"

# master: push a box-name change to the local node (the name was entered above). The lc signal + traps were
# armed right after the role step (LC_URL/LC_TOKEN point at the local node's loopback panel); here we only
# push the rename, if it changed — the OLD panel is still running at this point and the restart loads it.
if [ "$EXISTING_HOST" = yes ] && ! $DRYRUN && [ "$HOST_HAS_WG" = yes ] && [ -n "${LC_URL:-}" ] && [ -n "${LC_TOKEN:-}" ]; then
  _lk=""; [ "${LC_VERIFY:-no}" = yes ] || _lk="-k"
  _cur="$(curl -fsS $_lk --max-time 8 -H "Authorization: Bearer $LC_TOKEN" "${LC_URL%/}/api/node/whoami" 2>/dev/null | python3 -c 'import json,sys;print((json.load(sys.stdin).get("data") or {}).get("name") or "")' 2>/dev/null || true)"
  [ -n "$HOST_NODE_NAME" ] && [ "$HOST_NODE_NAME" != "$_cur" ] && curl -fsS $_lk --max-time 8 -X POST -H "Authorization: Bearer $LC_TOKEN" -H "Content-Type: application/json" --data "$(python3 -c 'import json,sys;print(json.dumps({"name":sys.argv[1]}))' "$HOST_NODE_NAME")" "${LC_URL%/}/api/node/rename" >/dev/null 2>&1 || true
fi

# ───────────────────────── users / dirs ─────────────────────────
info "Users, groups, directories"
run groupadd -f swg
id "$PANEL_USER" >/dev/null 2>&1 || run useradd -r -g swg -d "$STATE_DIR" -s /usr/sbin/nologin "$PANEL_USER"
run usermod -d "$STATE_DIR" -g swg "$PANEL_USER"
for d in "$PANEL_DIR" "$ETC_DIR" "$STATE_DIR" "$STATS_DIR"; do mkdir -p "$PREFIX$d"; done
run chown "$PANEL_USER:swg" "$STATE_DIR"; run chmod 750 "$STATE_DIR"
run chown "$PANEL_USER:swg" "$STATS_DIR"; run chmod 2775 "$STATS_DIR"   # panel writes node snapshots here for the dashboard
# the panel user must rewrite the auth file (Account tab) — that's an atomic temp+rename in
# ETC_DIR, so the dir needs group(swg) write; setgid keeps new files in group swg.
run chown root:swg "$ETC_DIR"; run chmod 2775 "$ETC_DIR"
[ "$STORE_CONFIGS" = true ] && { mkdir -p "$PREFIX$STATE_DIR/configs"; run chown "$PANEL_USER:swg" "$STATE_DIR/configs"; run chmod 750 "$STATE_DIR/configs"; }

# ───────────────────────── panel files ─────────────────────────
info "Panel application"
for f in swg-panel-server index.html app.css app.js reconcile.js; do
  [ -f "$SRC/$f" ] || die "missing $f beside this script (unzip the bundle here)"
done
mkdir -p "$PREFIX$PANEL_DIR"; cp "$SRC/swg-panel-server" "$PREFIX$PANEL_DIR/"; chmod 755 "$PREFIX$PANEL_DIR/swg-panel-server"
for f in index.html app.css app.js reconcile.js; do mkdir -p "$PREFIX$PANEL_DIR"; cp "$SRC/$f" "$PREFIX$PANEL_DIR/"; done
mkdir -p "$PREFIX$PANEL_DIR/vendor"; cp -a "$SRC/vendor/." "$PREFIX$PANEL_DIR/vendor/"   # qrcode + vendored Preact/htm ESM (buildless SPA)
[ -f "$SRC/VERSION" ] && cp "$SRC/VERSION" "$PREFIX$PANEL_DIR/" || true   # version stamp (update.sh reports it)
ok "installed panel + SPA to $PANEL_DIR"
mkdir -p "$PREFIX$STATE_DIR"; [ -f "$PREFIX$STATE_DIR/users.json" ] || { echo '{}' > "$PREFIX$STATE_DIR/users.json"; run chown "$PANEL_USER:swg" "$STATE_DIR/users.json"; ok "seeded empty users.json"; }

# ───────────────────────── host-as-node (this box is also an entry server) ─────────────────────────
LOCAL_TOKHASH=""
if [ "$HOST_HAS_WG" = yes ]; then
  info "This box as a node: agent + swg-noded (syncs to the local panel over HTTPS)"
  mkdir -p "$PREFIX$AGENT_DIR"; cp "$SRC/swg-agent" "$PREFIX$AGENT_DIR/"; chmod 755 "$PREFIX$AGENT_DIR/swg-agent"
  mkdir -p "$PREFIX$NODED_DIR"; cp "$SRC/swg-noded" "$PREFIX$NODED_DIR/"; chmod 755 "$PREFIX$NODED_DIR/swg-noded"
  [ -f "$SRC/VERSION" ] && cp "$SRC/VERSION" "$PREFIX$NODED_DIR/" || true
  mkdir -p "$PREFIX/var/lib/swg-noded" "$PREFIX/var/log/swg-agent"

  # the local node always reaches the local panel on loopback (works for every serve mode);
  # scheme is https only when the panel terminates TLS itself (internal mode with a cert).
  LOCAL_SCHEME=http
  [ "$SERVE_MODE" = internal ] && [ "$TLS_MODE" != skip ] && LOCAL_SCHEME=https
  LOCAL_PANEL_URL="${LOCAL_SCHEME}://127.0.0.1:${PORT}${PANEL_BASE}"

  if [ -f "$PREFIX/etc/swg-agent/config.json" ]; then
    ok "keeping existing /etc/swg-agent/config.json (local node already enrolled)"
  else
    # auto-enroll: mint a token for the local node; its hash goes into nodes.json below
    LOCAL_TOKEN="$(head -c18 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=')"
    LOCAL_TOKHASH="$(python3 -c 'import hashlib,os,base64,sys;t=sys.argv[1].encode();s=os.urandom(16);h=hashlib.pbkdf2_hmac("sha256",t,s,200000);print("pbkdf2_sha256$200000$"+base64.b64encode(s).decode()+"$"+base64.b64encode(h).decode())' "$LOCAL_TOKEN")"
    IFJSON=""; sep=""
    for n in "${SELECTED[@]}"; do n="${n// /}"; [ -z "$n" ] && continue
      _onb=""; iface_onboarded "$n" && _onb=', "onboarded": true'   # add-only (adopted interface — keep its peers)
      IFJSON+="$sep    \"$n\": { \"cmd\": [\"${IF_CMD[$n]}\"], \"conf\": \"${IF_CONF[$n]}\", \"endpoint_host\": \"${IF_ENDPOINT[$n]:-}\"${_onb} }"; sep=$',\n'; done
    # node-level endpoint_host is now a fallback (panel uses each interface's own); default it to the first interface's
    if [ -z "$HOST_ENDPOINT_IP" ]; then for n in "${SELECTED[@]}"; do [ -n "${IF_ENDPOINT[$n]:-}" ] && { HOST_ENDPOINT_IP="${IF_ENDPOINT[$n]}"; break; }; done; fi
    [ -z "$HOST_ENDPOINT_IP" ] && HOST_ENDPOINT_IP="$(detect_public_ip)"
    writef /etc/swg-agent/config.json 640 <<EOF
{
  "interfaces": {
$IFJSON
  },
  "endpoint_host": "${HOST_ENDPOINT_IP}",
  "dns": ["1.1.1.1"],
  "panel": {
    "url": "${LOCAL_PANEL_URL}",
    "token": "${LOCAL_TOKEN}",
    "verify": false
  },
  "node": {
    "interval": 5,
    "agent": "${AGENT_DIR}/swg-agent",
    "sudo": false
  }
}
EOF
  fi
  # swg-noded runs as ROOT (samples kernel wg + runs the agent which writes /etc). ProtectSystem=true keeps /etc writable.
  writef /etc/systemd/system/swg-noded.service 644 <<EOF
[Unit]
Description=swg-noded (HTTPS sync to local panel) — ${HOST_NODE_NAME}
After=network-online.target swg-panel-server.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=${NODED_DIR}/swg-noded
Environment=SWG_AGENT_CONFIG=/etc/swg-agent/config.json
Environment=SWG_NODED_STATE=/var/lib/swg-noded
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
ProtectSystem=true
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
fi

# ───────────────────────── nodes.json + fleet.json ─────────────────────────
info "nodes.json + fleet.json"
if [ "$HOST_HAS_WG" = yes ] && [ -n "$LOCAL_TOKHASH" ]; then
  writef "$STATE_DIR/nodes.json" 600 <<EOF
{
  "${HOST_NODE_NAME}": { "name": "${HOST_NODE_NAME}", "color": "${PALETTE[0]}", "endpoint_host": "", "stats_file": "stats-${HOST_NODE_NAME}.json", "token_hash": "${LOCAL_TOKHASH}", "created": $(date +%s 2>/dev/null || echo 0) }
}
EOF
elif [ ! -f "$PREFIX$STATE_DIR/nodes.json" ]; then
  writef "$STATE_DIR/nodes.json" 600 <<EOF
{}
EOF
fi
run chown "$PANEL_USER:swg" "$STATE_DIR/nodes.json" 2>/dev/null || true
writef /etc/swg-panel/fleet.json 640 <<EOF
{
  "roster_path":   "${STATE_DIR}/users.json",
  "nodes_path":    "${STATE_DIR}/nodes.json",
  "stats_dir":     "${STATS_DIR}",
  "store_configs": ${STORE_CONFIGS},
  "config_dir":    "${STATE_DIR}/configs",
  "node_interval": 5
}
EOF
run chown "$PANEL_USER:swg" "$ETC_DIR/fleet.json" 2>/dev/null || true

# Install snapshot — the next run of this installer reads it back to default every prompt (root-only).
writef "$ETC_DIR/install.conf" 600 <<EOF
# swg-panel install settings — re-running the installer offers these as defaults. Safe to edit/delete.
ROLE_SEL=${ROLE_SEL}
PANEL_DOMAIN=${PANEL_DOMAIN}
PANEL_BASE=${PANEL_BASE}
PORT=${PORT}
TLS_MODE=${TLS_MODE}
SERVE_MODE=${SERVE_MODE}
ACME_EMAIL=${ACME_EMAIL}
CF_TOKEN=${CF_TOKEN:-}
CF_ORIGIN_TOKEN=${CF_ORIGIN_TOKEN:-}
HOST_NODE_NAME=${HOST_NODE_NAME:-}
HOST_ENDPOINT_IP=${HOST_ENDPOINT_IP:-}
EOF

# ───────────────────────── panel-server service ─────────────────────────
write_panel_unit(){   # bind/TLS/base depend on SERVE_MODE; called from the serve section
  local bind="127.0.0.1" extra=""
  extra="Environment=SWG_PANEL_AUTH=${ETC_DIR}/auth"            # panel does its own login in every serve mode
  [ -n "$PANEL_BASE" ] && extra="$extra
Environment=SWG_PANEL_BASE=${PANEL_BASE}"
  if [ "$SERVE_MODE" = internal ]; then
    bind="0.0.0.0"                                              # internal mode faces the network directly
    [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ] && extra="$extra
Environment=SWG_PANEL_TLS_CERT=${CERT_FULLCHAIN}
Environment=SWG_PANEL_TLS_KEY=${CERT_KEY}"
    [ "${PORT}" -lt 1024 ] 2>/dev/null && extra="$extra
AmbientCapabilities=CAP_NET_BIND_SERVICE"
  fi
  writef /etc/systemd/system/swg-panel-server.service 644 <<EOF
[Unit]
Description=swg-panel broker
After=network.target

[Service]
Type=simple
User=${PANEL_USER}
ExecStart=${PANEL_DIR}/swg-panel-server
Environment=SWG_PANEL_FLEET=${ETC_DIR}/fleet.json
Environment=SWG_PANEL_WEB=${PANEL_DIR}
Environment=SWG_PANEL_HOST=${bind}
Environment=SWG_PANEL_PORT=${PORT}
Environment=SWG_UPDATE_TRIGGER=${STATE_DIR}/.update-request
${extra}
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${ETC_DIR} ${STATE_DIR} ${STATS_DIR}
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
  mk_update_unit                                   # wire one-click host self-update (root, own cgroup)
}

# One-click self-update: a root systemd updater the (unprivileged) panel triggers by touching a
# file. swg-update.path watches the trigger and starts swg-update.service, which runs in its OWN
# cgroup so 'systemctl restart swg-panel-server' mid-update can't kill it. swg programs only.
mk_update_unit(){
  [ -n "${_UPDATE_UNIT_DONE:-}" ] && return 0; _UPDATE_UNIT_DONE=1   # write_panel_unit runs twice (placeholder→real cert); the TLS-independent self-update units only need writing once
  writef /usr/local/bin/swg-update 755 <<'WRAP'
#!/usr/bin/env bash
# swg-update — fixed root entrypoint for one-click in-place update (panel + co-located node).
# swg programs only (panel/noded/agent); never wg/awg/turn-proxies. Logs to the journal.
set -euo pipefail
URL="${SWG_BOOTSTRAP_URL:-https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh}"
curl -fsSL "$URL" | bash -s update -y --no-components
WRAP
  writef /etc/systemd/system/swg-update.service 644 <<EOF
[Unit]
Description=swg-panel one-click self-update (swg programs only)

[Service]
Type=oneshot
ExecStart=/usr/local/bin/swg-update
EOF
  writef /etc/systemd/system/swg-update.path 644 <<EOF
[Unit]
Description=watch for a swg-panel update request

[Path]
PathModified=${STATE_DIR}/.update-request
Unit=swg-update.service

[Install]
WantedBy=multi-user.target
EOF
  if [ ! -e "$PREFIX$STATE_DIR/.update-request" ]; then          # pre-create ONLY when missing — on a re-install
    printf '' | writef "$STATE_DIR/.update-request" 660          # the swg-update.path unit is already watching,
    run chown "$PANEL_USER:swg" "$STATE_DIR/.update-request" 2>/dev/null || true   # so re-touching it would fire a spurious self-update ("updated")
  fi
  run systemctl daemon-reload
  run systemctl enable --quiet --now swg-update.path || warn "couldn't enable swg-update.path (one-click host update)"
}

# (no push receiver — nodes connect outbound over HTTPS; enroll them in the Nodes screen)

# ───────────────────────── login + TLS + serve mode ─────────────────────────
mk_auth_file(){   # panel login file (pbkdf2) — used by every serve mode so the Account tab works
  mkdir -p "$PREFIX$ETC_DIR"
  if $DRYRUN; then echo "    [skip] write ${ETC_DIR}/auth (pbkdf2 login for $BASIC_USER)"
    printf '%s:pbkdf2_sha256$200000$DRYRUN$DRYRUN\n' "$BASIC_USER" > "$PREFIX$ETC_DIR/auth"
  else
    python3 - "$BASIC_USER" "$BASIC_PASS" > "$PREFIX$ETC_DIR/auth" <<'PYAUTH'
import sys, os, hashlib, base64
u, pw = sys.argv[1], sys.argv[2]
salt = os.urandom(16); it = 200000
h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, it)
print("%s:pbkdf2_sha256$%d$%s$%s" % (u, it, base64.b64encode(salt).decode(), base64.b64encode(h).decode()))
PYAUTH
  fi
  chmod 640 "$PREFIX$ETC_DIR/auth" 2>/dev/null || true; run chown root:swg "$ETC_DIR/auth"
  ok "login: $BASIC_USER  (stored hashed in ${ETC_DIR}/auth)"
}
cert_perms(){ run chown root:swg "$TLS_DIR/fullchain.pem" "$TLS_DIR/key.pem" 2>/dev/null || true
  chmod 644 "$PREFIX$TLS_DIR/fullchain.pem" 2>/dev/null || true; chmod 640 "$PREFIX$TLS_DIR/key.pem" 2>/dev/null || true; }
san_for(){ case "$1" in *[a-zA-Z]*) echo "DNS:$1";; *) echo "IP:$1";; esac; }
find_acme(){ ACME=""; local a; for a in /root/.acme.sh/acme.sh "${HOME:-/root}/.acme.sh/acme.sh" "$(command -v acme.sh 2>/dev/null || true)"; do [ -n "$a" ] && [ -x "$a" ] && { ACME="$a"; return 0; }; done; return 1; }
# does acme.sh actually hold an ISSUED cert for <domain>?  (`--info` returns 0 even with no cert,
# e.g. on a clean box right after --register-account — so check the cert file on disk instead)
acme_has_cert(){ local h; h="$(dirname "${ACME:-/root/.acme.sh/acme.sh}")"; [ -s "$h/${1}_ecc/${1}.cer" ] || [ -s "$h/${1}/${1}.cer" ]; }
ensure_acme(){ find_acme && return 0
  info "Installing acme.sh"; run sh -c "curl -fsSL https://get.acme.sh | sh -s email=${ACME_EMAIL:-admin@$PANEL_DOMAIN}"
  find_acme && return 0; $DRYRUN && { ACME=/root/.acme.sh/acme.sh; return 0; }
  die "acme.sh not found after install — install it manually or use TLS=selfsigned/skip"; }
mk_selfsigned(){ CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"; mkdir -p "$PREFIX$TLS_DIR"
  if $DRYRUN; then echo "    [skip] openssl self-signed -> $TLS_DIR (CN=$PANEL_DOMAIN)"; : > "$PREFIX$CERT_FULLCHAIN"; : > "$PREFIX$CERT_KEY"
  else run openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout "$CERT_KEY" -out "$CERT_FULLCHAIN" -subj "/CN=${PANEL_DOMAIN}" -addext "subjectAltName=$(san_for "$PANEL_DOMAIN")"; fi
  cert_perms; ok "self-signed certificate for ${PANEL_DOMAIN} (10y)"; }
reuse_cert(){   # re-install with REUSE_TLS=yes: keep the cert already in $TLS_DIR, no re-issue
  if [ -f "$PREFIX$TLS_DIR/fullchain.pem" ] && [ -f "$PREFIX$TLS_DIR/key.pem" ]; then
    CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"; cert_perms; ok "keeping the existing certificate in $TLS_DIR"
  else warn "no existing certificate in $TLS_DIR — generating a self-signed one"; mk_selfsigned; fi; }
use_provided_certs(){   # skip-with-own-cert: copy caller-supplied cert into $TLS_DIR; 0 if used, 1 if none
  [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ] || return 1
  mkdir -p "$PREFIX$TLS_DIR"
  $DRYRUN || { cp "$CERT_FULLCHAIN" "$PREFIX$TLS_DIR/fullchain.pem"; cp "$CERT_KEY" "$PREFIX$TLS_DIR/key.pem"; }
  CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"; cert_perms
  ok "using provided certificate (copied into $TLS_DIR)"; return 0; }
mk_cf_origin(){   # cf15: request a 15-year Cloudflare Origin certificate via the CF API
  # Auth is a Bearer API token (Zone:SSL and Certificates:Edit). The old Origin CA Key /
  # X-Auth-User-Service-Key header is deprecated by Cloudflare (sunset 2026-09-30).
  CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"; mkdir -p "$PREFIX$TLS_DIR"
  [ -n "${CF_ORIGIN_TOKEN:-}" ] || die "cf15 needs CF_ORIGIN_TOKEN (API token with Zone:SSL and Certificates:Edit)"
  if $DRYRUN; then echo "    [skip] request Cloudflare Origin certificate (15y, origin-ecc) for $PANEL_DOMAIN"
    : > "$PREFIX$CERT_FULLCHAIN"; : > "$PREFIX$CERT_KEY"; cert_perms; ok "cf15 origin certificate (dry-run placeholder)"; return 0; fi
  local key csr cert
  key="$(openssl ecparam -name prime256v1 -genkey -noout 2>/dev/null)" || die "openssl: EC key generation failed"
  csr="$(printf '%s\n' "$key" | openssl req -new -key /dev/stdin -subj "/CN=${PANEL_DOMAIN}" 2>/dev/null)" || die "openssl: CSR generation failed"
  info "Requesting a 15-year Cloudflare Origin certificate for $PANEL_DOMAIN…"
  cert="$(CF_ORIGIN_TOKEN="$CF_ORIGIN_TOKEN" python3 - "$PANEL_DOMAIN" "$csr" <<'PY'
import sys, os, json, urllib.request, urllib.error
domain, csr = sys.argv[1], sys.argv[2]
body = json.dumps({"hostnames": [domain], "requested_validity": 5475,
                   "request_type": "origin-ecc", "csr": csr}).encode()
req = urllib.request.Request("https://api.cloudflare.com/client/v4/certificates", data=body, method="POST",
      headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["CF_ORIGIN_TOKEN"]})
try:
    with urllib.request.urlopen(req, timeout=30) as r: d = json.load(r)
except urllib.error.HTTPError as e:
    d = json.load(e)
except Exception as e:
    sys.stderr.write(str(e)); sys.exit(1)
if d.get("success"): sys.stdout.write(d["result"]["certificate"])
else: sys.stderr.write(json.dumps(d.get("errors", d))[:300]); sys.exit(1)
PY
)" || die "Cloudflare Origin CA request failed — check the API token (Zone:SSL and Certificates:Edit) and that $PANEL_DOMAIN is on this Cloudflare account"
  printf '%s\n' "$cert" > "$PREFIX$CERT_FULLCHAIN"
  printf '%s\n' "$key"  > "$PREFIX$CERT_KEY"
  cert_perms; ok "issued Cloudflare Origin certificate (15y) for ${PANEL_DOMAIN} — valid only behind Cloudflare's proxy"; }

# ---- internal: the panel serves its own TLS; cert lands in $TLS_DIR ----
obtain_cert_internal(){
  mkdir -p "$PREFIX$TLS_DIR"
  [ "${REUSE_TLS:-no}" = yes ] && { reuse_cert; return 0; }
  case "$TLS_MODE" in
    skip) use_provided_certs || { CERT_FULLCHAIN=""; CERT_KEY=""; ok "TLS skipped — panel will serve plain HTTP"; }; return 0;;
    selfsigned) mk_selfsigned;;
    cf15) mk_cf_origin;;
    letsencrypt|letsencrypt-ip|cloudflare)
      ensure_acme
      local args=(--issue -d "$PANEL_DOMAIN" --server letsencrypt --keylength ec-256)
      # IP certs MUST be short-lived (~6 days); --days 3 makes acme.sh's daily cron renew ~2 days in (≈4-day buffer)
      [ "$TLS_MODE" = letsencrypt-ip ] && args+=(--certificate-profile shortlived --days 3)
      if [ "$TLS_MODE" = cloudflare ]; then [ -n "$CF_TOKEN" ] || die "cloudflare needs a CF token (re-run Step 3, or set CF_TOKEN)"
        export CF_Token="$CF_TOKEN"; [ -n "$CF_ACCOUNT_ID" ] && export CF_Account_ID="$CF_ACCOUNT_ID"; args+=(--dns dns_cf)
        info "Issuing $PANEL_DOMAIN via Let's Encrypt — DNS-01 challenge through Cloudflare (can take ~30–60s while DNS propagates)…"
      else args+=(--standalone)
        if ! $DRYRUN && have ss && [ -n "$(ss -lntH "sport = :80" 2>/dev/null)" ]; then
          local _w80 _g80=""; _w80="$(ss -lntpH "sport = :80" 2>/dev/null | grep -oE '"[^"]+"' | head -1 | tr -d '"' || true)"
          echo; warn "letsencrypt HTTP-01 needs host port $(col "$C_YEL" ":80"), but it's in use${_w80:+ (by $(col "$C_YEL" "$_w80"))} — issuance will fail"
          echo "    :80 is fixed by ACME (independent of the panel's port). Free it, or re-run and pick $(b cloudflare) (DNS-01), $(b cf15), or $(b selfsigned)."
          ask_yn "Try acme standalone on :80 anyway?" n _g80
          [ "$_g80" = yes ] || die "aborted — free :80 or pick a TLS method that doesn't need it, then re-run"
        fi
        info "Issuing $PANEL_DOMAIN via Let's Encrypt — HTTP-01 (acme standalone needs :80 free)…"
      fi
      [ -n "$ACME_EMAIL" ] && { run "$ACME" --register-account -m "$ACME_EMAIL" --server letsencrypt || true; }
      # Re-run? acme.sh already holds a cert for this domain → install it instead of re-issuing.
      # Renewals run from acme's cron. (First install on a clean box has no cert → issue below.)
      if ! $DRYRUN && acme_has_cert "$PANEL_DOMAIN"; then
        ok "acme.sh already has a cert for $PANEL_DOMAIN — installing it (auto-renews via acme's cron)"
      else
        local rc=0; run "$ACME" "${args[@]}" || rc=$?
        # acme.sh exit 2 = RENEW_SKIP (a valid cert already exists, not due for renewal) — that's fine.
        if [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ]; then
          if $DRYRUN || acme_has_cert "$PANEL_DOMAIN"; then
            warn "acme.sh exit $rc, but a cert for $PANEL_DOMAIN already exists — installing it."
          else
            warn "issuance failed (acme.sh exit $rc) — falling back to a self-signed cert."; mk_selfsigned; return
          fi
        fi
      fi
      CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"
      run "$ACME" --install-cert -d "$PANEL_DOMAIN" --ecc --key-file "$CERT_KEY" --fullchain-file "$CERT_FULLCHAIN" \
          --reloadcmd "chown root:swg $TLS_DIR/fullchain.pem $TLS_DIR/key.pem; chmod 640 $TLS_DIR/key.pem; systemctl restart swg-panel-server"
      cert_perms; ok "issued + installed certificate via $TLS_MODE (auto-renews)";;
    *) die "TLS must be cloudflare|letsencrypt|letsencrypt-ip|selfsigned|skip";;
  esac
}
serve_internal(){
  # acme's --install-cert reloadcmd runs `systemctl restart swg-panel-server` immediately,
  # so the unit must exist (and be loaded) BEFORE issuance — write+enable a TLS-less
  # placeholder first, then rewrite with the real cert paths and restart for real.
  write_panel_unit
  run systemctl daemon-reload
  run systemctl enable --quiet $_NOW swg-panel-server
  obtain_cert_internal
  write_panel_unit
  run systemctl daemon-reload
  if [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ]; then run systemctl restart swg-panel-server; fi
  if command -v ufw >/dev/null 2>&1; then run ufw allow "${PORT}/tcp" 2>/dev/null || true; fi
  local sch="https"; [ -n "${CERT_FULLCHAIN:-}" ] || sch="http"
  [ "$sch" = http ] && warn "TLS skipped — login travels in the clear. Use selfsigned/letsencrypt/cloudflare for real use."
  ok "Internal: panel serves ${sch}://${PANEL_DOMAIN}:${PORT}${PANEL_BASE}/ directly (no extra web server)"
}

# ---- reverse-proxy (nginx / caddy): panel on loopback, proxy terminates TLS ----
setup_tls_proxy(){   # issue/locate a cert into $TLS_DIR for a reverse proxy to use
  [ "${REUSE_TLS:-no}" = yes ] && { reuse_cert; return 0; }
  case "$TLS_MODE" in
    selfsigned) mk_selfsigned;;
    cf15) mk_cf_origin;;
    skip) use_provided_certs || { CERT_FULLCHAIN=""; CERT_KEY=""; ok "TLS skipped — proxy will serve plain HTTP (or add your own cert)"; }; return 0;;
    letsencrypt|letsencrypt-ip|cloudflare)
      mkdir -p "$PREFIX$TLS_DIR"; ensure_acme
      local args=(--issue -d "$PANEL_DOMAIN" --server letsencrypt --keylength ec-256)
      [ "$TLS_MODE" = letsencrypt-ip ] && args+=(--certificate-profile shortlived --days 3)   # short-lived IP cert
      if [ "$TLS_MODE" = cloudflare ]; then [ -n "$CF_TOKEN" ] || die "cloudflare needs a CF token (re-run Step 3, or set CF_TOKEN)"
        export CF_Token="$CF_TOKEN"; [ -n "$CF_ACCOUNT_ID" ] && export CF_Account_ID="$CF_ACCOUNT_ID"; args+=(--dns dns_cf)
        info "Issuing $PANEL_DOMAIN via Let's Encrypt — DNS-01 challenge through Cloudflare (can take ~30–60s while DNS propagates)…"
      elif [ "$SERVE_MODE" = nginx ]; then args+=(--webroot "$ACME_WEBROOT")    # nginx already serves :80 for the challenge
      else args+=(--standalone); fi                                            # caddy not up yet → acme can hold :80
      [ -n "$ACME_EMAIL" ] && { run "$ACME" --register-account -m "$ACME_EMAIL" --server letsencrypt || true; }
      local reload="systemctl reload nginx"; [ "$SERVE_MODE" = caddy ] && reload="systemctl reload caddy"
      # Re-run? install the existing cert instead of re-issuing. First install → no cert → issue.
      if ! $DRYRUN && acme_has_cert "$PANEL_DOMAIN"; then
        ok "acme.sh already has a cert for $PANEL_DOMAIN — installing it (auto-renews via acme's cron)"
      else
        local rc=0; run "$ACME" "${args[@]}" || rc=$?
        if [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ] && ! { $DRYRUN || acme_has_cert "$PANEL_DOMAIN"; }; then
          warn "issuance failed (acme.sh exit $rc) — proxy will serve plain HTTP."; CERT_FULLCHAIN=""; CERT_KEY=""; return 0
        fi
      fi
      CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"
      run "$ACME" --install-cert -d "$PANEL_DOMAIN" --ecc --key-file "$CERT_KEY" --fullchain-file "$CERT_FULLCHAIN" --reloadcmd "$reload"
      cert_perms; ok "issued + installed certificate via $TLS_MODE";;
    *) die "TLS must be cloudflare|letsencrypt|letsencrypt-ip|selfsigned|skip";;
  esac
}
proxy_loc(){ [ -n "$PANEL_BASE" ] && printf '%s/' "$PANEL_BASE" || printf '/'; }   # nginx location path

write_vhost(){   # write_vhost bootstrap|tls    (nginx)
  local loc; loc="$(proxy_loc)"
  if [ "$1" = tls ]; then
    writef /etc/nginx/sites-available/swg-panel.conf 644 <<EOF
server {
    listen 80;
    server_name ${PANEL_DOMAIN};
    location ^~ /.well-known/acme-challenge/ { root ${ACME_WEBROOT}; }
    location / { return 301 https://\$host\$request_uri; }
}
server {
    listen 443 ssl http2;
    server_name ${PANEL_DOMAIN};
    ssl_certificate ${CERT_FULLCHAIN};
    ssl_certificate_key ${CERT_KEY};

    location ${loc} {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  else
    writef /etc/nginx/sites-available/swg-panel.conf 644 <<EOF
server {
    listen 80;
    server_name ${PANEL_DOMAIN};
    location ^~ /.well-known/acme-challenge/ { root ${ACME_WEBROOT}; }
    location ${loc} {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  fi
  if [ -d /etc/nginx/sites-enabled ]; then run ln -sf /etc/nginx/sites-available/swg-panel.conf /etc/nginx/sites-enabled/swg-panel.conf
  elif [ -d /etc/nginx/conf.d ]; then cp "$PREFIX/etc/nginx/sites-available/swg-panel.conf" "$PREFIX/etc/nginx/conf.d/swg-panel.conf"; fi
}
serve_nginx(){
  mkdir -p "$PREFIX$ACME_WEBROOT"
  write_panel_unit
  run systemctl daemon-reload; run systemctl enable --quiet $_NOW swg-panel-server
  write_vhost bootstrap
  run nginx -t && run systemctl reload nginx || warn "nginx -t failed (is nginx installed?) — fix, then: systemctl reload nginx"
  setup_tls_proxy
  if [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ]; then
    write_vhost tls
    run nginx -t && run systemctl reload nginx || warn "nginx -t failed after enabling TLS — check $CERT_FULLCHAIN"
    ok "nginx: TLS enabled for https://${PANEL_DOMAIN}${PANEL_BASE}/"
  else warn "nginx: serving on :80 without TLS — front with TLS before exposing."; fi
}

ensure_caddy_import(){   # make the main Caddyfile import our drop-in
  local main=/etc/caddy/Caddyfile
  if $DRYRUN; then echo "    [skip] ensure 'import conf.d/*.caddy' in $main"; return 0; fi
  mkdir -p /etc/caddy/conf.d; touch "$main"
  grep -qF 'conf.d/*.caddy' "$main" 2>/dev/null || printf '\nimport conf.d/*.caddy\n' >> "$main"
}
write_caddy_site(){
  local site="$PANEL_DOMAIN" tls="" handle="handle"
  [ -n "$PANEL_BASE" ] && handle="handle ${PANEL_BASE}/*"
  if [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ]; then tls="    tls ${CERT_FULLCHAIN} ${CERT_KEY}"
  elif [ "$TLS_MODE" = selfsigned ]; then tls="    tls internal"
  elif [ "$TLS_MODE" = skip ]; then site="http://${PANEL_DOMAIN}"; fi
  writef /etc/caddy/conf.d/swg-panel.caddy 644 <<EOF
${site} {
${tls}
    ${handle} {
        reverse_proxy 127.0.0.1:${PORT}
    }
}
EOF
  ensure_caddy_import
}
serve_caddy(){
  have caddy || warn "caddy not found — install it (https://caddyserver.com), then re-run or 'systemctl reload caddy'"
  write_panel_unit
  run systemctl daemon-reload; run systemctl enable --quiet $_NOW swg-panel-server
  setup_tls_proxy            # caddy isn't up yet, so acme standalone (:80) is free for letsencrypt
  write_caddy_site
  run systemctl reload caddy 2>/dev/null || run systemctl restart caddy 2>/dev/null || warn "couldn't (re)load caddy — start it after checking /etc/caddy/conf.d/swg-panel.caddy"
  local sch="https"; { [ "$TLS_MODE" = skip ] && [ -z "${CERT_FULLCHAIN:-}" ]; } && sch="http"
  ok "caddy: serving ${sch}://${PANEL_DOMAIN}${PANEL_BASE}/"
}

serve_skip(){
  write_panel_unit
  run systemctl daemon-reload; run systemctl enable --quiet $_NOW swg-panel-server
  ok "Panel running on 127.0.0.1:${PORT}${PANEL_BASE} — configure your web server to proxy to it."
  echo "    nginx example:"
  echo "      location $(proxy_loc) { proxy_pass http://127.0.0.1:${PORT}; proxy_set_header Host \$host; }"
}

info "Login + TLS ($SERVE_MODE)"
if [ "$KEEP_AUTH" = yes ]; then ok "keeping existing login ($BASIC_USER) — ${ETC_DIR}/auth untouched"; else mk_auth_file; fi
case "$SERVE_MODE" in
  internal) serve_internal;;
  nginx)    serve_nginx;;
  caddy)    serve_caddy;;
  skip)     serve_skip;;
esac

# ───────────────────────── enable ─────────────────────────
info "Enable services"
run systemctl daemon-reload
[ "$HOST_HAS_WG" = yes ] && { run systemctl enable --quiet swg-noded; run systemctl restart swg-noded || warn "couldn't start swg-noded"; }   # restart so a re-run picks up newly-added interfaces (config.json is read only at startup)
run systemctl enable --quiet $_NOW swg-panel-server
[ "$SERVE_MODE" = nginx ] && { run nginx -t && run systemctl reload nginx || warn "nginx -t failed; fix the vhost then: systemctl reload nginx"; }

# ───────────────────────── SUMMARY ─────────────────────────
# A convert (SWG_CONVERT_DIR set) prints ONE unified summary at the very end in convert.sh — suppress this
# mid-flow panel summary so the converted box doesn't show two (matches bare→docker's single end summary).
if [ -z "${SWG_CONVERT_DIR:-}" ]; then
echo; ok "Host install complete."
case "$SERVE_MODE" in
  internal) SCH=https; [ -n "${CERT_FULLCHAIN:-}" ] || SCH=http
            PORTSUF=""; [ "$PORT" != 443 ] && PORTSUF=":${PORT}"; UI="${SCH}://${PANEL_DOMAIN}${PORTSUF}${PANEL_BASE}/";;
  nginx|caddy) SCH=https; { [ "$TLS_MODE" = skip ] && [ -z "${CERT_FULLCHAIN:-}" ]; } && SCH=http; UI="${SCH}://${PANEL_DOMAIN}${PANEL_BASE}/";;
  skip) UI="http://127.0.0.1:${PORT}${PANEL_BASE}/";;
esac
echo; echo "$(b '──────────────── SUMMARY ────────────────')"; echo
echo "  Panel     $(bb "$UI")"
if [ "$KEEP_AUTH" = yes ]; then echo "  Login     $(bb "$BASIC_USER") / $(bb "(unchanged — your existing password)")"
else echo "  Login     $(bb "$BASIC_USER") / $(bb "$BASIC_PASS")   (change later in the panel → Account)"; fi
echo "  TLS       $(b "$TLS_MODE")  ·  Web server $(b "$SERVE_MODE") (port $(b "$PORT"))"
LOCAL_SCHEME=http; [ "$SERVE_MODE" = internal ] && [ "$TLS_MODE" != skip ] && LOCAL_SCHEME=https
echo "  Local     $(bb "${LOCAL_SCHEME}://127.0.0.1:${PORT}${PANEL_BASE}/")   (on this box — reverse proxy / local checks)"
if [ "$HOST_HAS_WG" = yes ] && [ "${#SELECTED[@]}" -gt 0 ]; then echo; echo "  $(b 'Interfaces') (this box, node '$(b "$HOST_NODE_NAME")'):"
  for n in "${SELECTED[@]}"; do c="${IF_CONF[$n]:-}"
    printf '    %s %-9s %s  %s  mtu %s\n' "$(col "$C_GREEN" "$(printf '%-10s' "$n")")" "${IF_CMD[$n]:-?}" \
      "$(bb "${IF_ENDPOINT[$n]:-$HOST_ENDPOINT_IP}:$(conf_get "$c" ListenPort)")" "$(b "$(conf_get "$c" Address)")" "$(conf_get "$c" MTU)"
  done
fi
# turn-proxy + interface info only matter when this box is also a node (master); a panel-only host has none
if [ "$HOST_HAS_WG" = yes ]; then
  detect_turn 2>/dev/null || true
  if [ "${#TP_LISTEN[@]}" -gt 0 ]; then echo; echo "  $(b 'Turn-proxy') instances:"
    for n in "${!TP_LISTEN[@]}"; do _fw="$(fwd_ifaces "${TP_CONNECT[$n]}")"
      printf '    %s %s → %s%s\n' "$(col "$C_GREEN" "$(printf '%-22s' "$n")")" "$(bb "${TP_LISTEN[$n]}")" "$(b "${TP_CONNECT[$n]}")" "${_fw:+ $(col "$C_GREEN" "($_fw)")}"
    done
  fi
fi
echo
echo "  Next      add entry servers in the panel: $(b 'Nodes → Add node')  (gives a one-time key + one-liner)"
if [ "$HOST_HAS_WG" = yes ]; then
  echo "  Firewall  open TCP $(b "$PORT")$([ "${#TP_LISTEN[@]}" -gt 0 ] && echo ' + the turn-proxy UDP ports') if not already"
  echo "  Manage    each interface's ingress/egress IPs + egress NIC anytime in the panel → $(b Interfaces)"
  echo "  Edit      panel $(b /etc/swg-panel/)  ·  interfaces $(b /etc/amnezia/amneziawg/) / $(b /etc/wireguard/)  ·  turn-proxies $(b /etc/systemd/system/)"
else
  echo "  Firewall  open TCP $(b "$PORT") if not already"
  echo "  Edit      panel $(b /etc/swg-panel/)"
fi
[ "$TLS_MODE" = selfsigned ] && echo "  Note      self-signed cert — the browser warns once, that's expected"
echo     # one blank line after the summary block (consistency)
else ok "panel installed on bare-metal — continuing…"; fi   # convert: brief line; convert.sh prints the unified summary
if $DRYRUN; then echo; ok "DRY RUN done — inspect ./dryrun"; fi   # `if` (not `&&`) so a real run doesn't exit the script non-zero on its last command
