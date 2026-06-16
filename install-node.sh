#!/usr/bin/env bash
# install-node.sh — set up a swg-panel NODE (entry server).
#
# Installs the agent + the swg-noded daemon and points it at your panel. The node
# makes ONLY outbound HTTPS to the panel: every few seconds it posts its snapshot
# and receives its desired peer set, then reconciles locally. No inbound access,
# no SSH keys, no rsync, no queue.
#
# First add the node in the panel's "Nodes" screen — it hands you a one-time key
# and the exact command to run here, e.g.:
#   curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh \
#     | sudo bash -s node -key SECURE_NODE_KEY -host https://panel.example.net
#
# Fill CONFIG to run unattended, or be prompted. Run as root. --dry-run renders
# files under ./dryrun and executes nothing.
set -euo pipefail

# ───────────────────────── CONFIG (blank = ask) ─────────────────────────
PANEL_URL="${PANEL_URL:-}"             # https://host[:port][/subpath] of the panel   (bootstrap: -host)
NODE_TOKEN="${NODE_TOKEN:-}"           # one-time enrollment key from the Nodes screen (bootstrap: -key)
NODE_NAME="${NODE_NAME:-}"             # local label for this box's systemd unit + final message only (NOT the panel name; blank = hostname)
ENDPOINT_IP="${ENDPOINT_IP:-}"         # public IP/host clients dial for THIS node's wg
MANAGE_IFACES="${MANAGE_IFACES:-}"     # e.g. "awg0"  (blank = manage all detected)
WG_MTU="${WG_MTU:-1280}"               # interface MTU — 1280 leaves headroom for turn-proxy obfuscation
DNS="${DNS:-1.1.1.1}"
TLS_VERIFY="${TLS_VERIFY:-}"           # yes = verify panel's cert (real CA); no = self-signed
TLS_FINGERPRINT="${TLS_FINGERPRINT:-}" # optional: pin panel cert sha256 (hex) instead of verify
INTERVAL="${INTERVAL:-5}"              # sync period, seconds
AGENT_DIR="${AGENT_DIR:-/opt/swg-agent}"
NODED_DIR="${NODED_DIR:-/opt/swg-noded}"
# ────────────────────────────────────────────────────────────────────────

DRYRUN=false; [ "${1:-}" = "--dry-run" ] && DRYRUN=true
PREFIX=""; $DRYRUN && PREFIX="$(pwd)/dryrun"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── colours / styling (honour NO_COLOR + non-tty) ──
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  BOLD=$'\033[1m'; RESET=$'\033[0m'
  C_BLUE=$'\033[38;5;39m'; C_GREEN=$'\033[32m'; C_GREY=$'\033[90m'; C_CYAN=$'\033[36m'; C_RED=$'\033[31m'; C_YEL=$'\033[33m'
else BOLD=""; RESET=""; C_BLUE=""; C_GREEN=""; C_GREY=""; C_CYAN=""; C_RED=""; C_YEL=""; fi
b(){   printf '%s%s%s' "$BOLD" "$*" "$RESET"; }
bb(){  printf '%s%s%s%s' "$BOLD" "$C_BLUE" "$*" "$RESET"; }   # bold + blue (summary highlights)
col(){ local _c="$1"; shift; printf '%s%s%s' "$_c" "$*" "$RESET"; }
conf_get(){ grep -iE "^[[:space:]]*$2[[:space:]]*=" "$1" 2>/dev/null | head -1 | sed 's/.*=[[:space:]]*//; s/[[:space:]]*$//'; }
info(){ echo "${C_CYAN}▸${RESET} ${BOLD}$*${RESET}"; }   # every ▸ line is bold
ok(){   echo "${C_GREEN}✓${RESET} $*"; }
warn(){ echo "${C_YEL}!${RESET} $*" >&2; }
die(){  echo "${C_RED}✗ $*${RESET}" >&2; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }
run(){ if $DRYRUN; then echo "    [skip] $*"; else "$@"; fi; }
writef(){ local p="$1" m="${2:-644}" full="$PREFIX$1"; mkdir -p "$(dirname "$full")"; cat > "$full"; chmod "$m" "$full" 2>/dev/null || true; ok "wrote $p ($m)"; }
menu(){ printf '  %s\n      %s\n\n' "$1" "$2"; }

ask(){ local v p="$1" d="${2:-}"; if [ -n "${!3:-}" ]; then return; fi
  read -rp "$p${d:+ [$(col "$C_BLUE" "$d")]}: " v </dev/tty || true; printf -v "$3" '%s' "${v:-$d}"; }
ask_yn(){ local v p="$1" d="${2:-y}"; if [ -n "${!3:-}" ]; then return; fi
  read -rp "$p ($([ "$d" = y ] && echo 'Y/n' || echo 'y/N')): " v </dev/tty || true
  v="${v:-$d}"; case "$v" in [Yy]*) printf -v "$3" yes;; *) printf -v "$3" no;; esac; }

# ── input validators (0 = ok) ──
v_proto(){   case "$1" in a|awg|amneziawg|w|wg|wireguard) return 0;; *) return 1;; esac; }
v_ip(){      printf '%s' "$1" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$' || return 1
             local o; for o in ${1//./ }; do [ "$o" -le 255 ] 2>/dev/null || return 1; done; return 0; }
v_host(){    v_ip "$1" && return 0; case "$1" in ""|*" "*|*[!a-zA-Z0-9.-]*) return 1;; *) return 0;; esac; }
v_httpsurl(){ case "$1" in https://*|http://*) v_host "$(x="${1#http://}"; x="${x#https://}"; x="${x%%/*}"; printf '%s' "${x%%:*}")";; *) return 1;; esac; }
v_port(){    case "$1" in ""|*[!0-9]*) return 1;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
port_free(){ have ss || return 0; [ -z "$(ss -lnuH "sport = :$1" 2>/dev/null)" ]; }   # UDP port not already bound
v_freeport(){ v_port "$1" && port_free "$1"; }
v_name(){    case "$1" in ""|*[!a-zA-Z0-9_-]*) return 1;; esac; [ "${#1}" -le 40 ]; }
v_iface(){   case "$1" in ""|*[!a-zA-Z0-9_-]*) return 1;; esac; [ "${#1}" -le 15 ]; }
v_token(){   [ -n "$1" ] && [ "${#1}" -ge 8 ]; }
v_subnet(){  have python3 || return 0; python3 -c "import ipaddress,sys;ipaddress.ip_network(sys.argv[1],strict=False)" "$1" >/dev/null 2>&1; }
v_hostport(){ case "$1" in *:*) v_host "${1%%:*}" && v_port "${1##*:}";; *) return 1;; esac; }

# ask_choice <prompt> <default> <var> "<opt…>"  — re-prompts on bad input; ' --force' overrides
ask_choice(){ local p="$1" d="$2" var="$3" opts="$4" v o forced rc
  if [ -n "${!var:-}" ]; then for o in $opts; do [ "${!var}" = "$o" ] && return; done
    warn "ignoring invalid $var='${!var}' (expected: $opts)"; fi
  while :; do
    if read -rp "$p [$(col "$C_BLUE" "$d")]: " v </dev/tty; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"; forced=no
    case "$v" in *' --force') v="${v% --force}"; v="${v%"${v##*[![:space:]]}"}"; forced=yes;; esac
    for o in $opts; do [ "$v" = "$o" ] && { printf -v "$var" '%s' "$v"; return; }; done
    [ "$forced" = yes ] && { warn "forcing unrecognised value: $v"; printf -v "$var" '%s' "$v"; return; }
    [ $rc -ne 0 ] && die "‘$v’ is not one of: $opts (and no interactive input to re-prompt)"
    warn "‘$v’ isn't one of: $(col "$C_BLUE" "$opts")"
    echo "  re-enter, or append $(b ' --force') to use your value anyway"
  done; }

# ask_valid <prompt> <default> <var> <validator> <hint>  — re-prompts on bad input; ' --force' overrides
ask_valid(){ local p="$1" d="$2" var="$3" fn="$4" hint="$5" v forced rc
  if [ -n "${!var:-}" ]; then "$fn" "${!var}" && return
    warn "ignoring invalid $var='${!var}' ($hint)"; fi
  while :; do
    if read -rp "$p${d:+ [$(col "$C_BLUE" "$d")]}: " v </dev/tty; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"; forced=no
    case "$v" in *' --force') v="${v% --force}"; v="${v%"${v##*[![:space:]]}"}"; forced=yes;; esac
    if "$fn" "$v"; then printf -v "$var" '%s' "$v"; return; fi
    [ "$forced" = yes ] && { warn "forcing: $v"; printf -v "$var" '%s' "$v"; return; }
    [ $rc -ne 0 ] && die "no valid value for ‘$p’ (got '${v:-empty}') and no interactive input to re-prompt"
    warn "$hint"
    echo "  re-enter, or append $(b ' --force') to use it anyway"
  done; }

detect_public_ip(){ # best public IPv4: default-route source, then first hostname -I
  local ip; ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1 || true)"
  [ -z "$ip" ] && ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  printf '%s' "$ip"; }
detect_wan(){ ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n1; }

declare -A IF_CMD IF_CONF IF_ENDPOINT; declare -a SELECTED   # IF_ENDPOINT: per-interface public IP clients dial
detect_wg(){ # scan everything under /etc/amnezia (any subdir) for awg, and /etc/wireguard for wg
  IF_CMD=(); IF_CONF=(); local f n
  if [ -d /etc/amnezia ]; then
    while IFS= read -r f; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=awg; IF_CONF[$n]="$f"
    done < <(find /etc/amnezia -maxdepth 3 -type f -name '*.conf' 2>/dev/null)
  fi
  for f in /etc/wireguard/*.conf; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=wg; IF_CONF[$n]="$f"; done
}
ensure_wg_tools(){ # ensure_wg_tools <awg|wg> — install tools if missing (idempotent, non-fatal -> 0/1)
  local cmd="$1"
  have "$cmd" && return 0
  if [ "$cmd" = wg ]; then run apt-get update -qq || true; run apt-get install -y wireguard || true
  else run apt-get update -qq || true; run apt-get install -y software-properties-common || true
       run add-apt-repository -y ppa:amnezia/ppa || true; run apt-get update -qq || true; run apt-get install -y amneziawg || true; fi
  $DRYRUN && return 0
  have "$cmd"
}
awg_obfuscation(){ # AmneziaWG v2 obfuscation — H1–H4 ranges, S1–S4, conservative QUIC-Initial I1
  local s1 s2 s3 s4 b1 b2 b3 b4 w=15
  s1=$(( 15 + RANDOM % 136 )); s2=$(( 15 + RANDOM % 136 ))
  while [ "$s1" -eq "$s2" ] || [ $((s1+56)) -eq "$s2" ]; do s2=$(( 15 + RANDOM % 136 )); done
  s3=$(( 15 + RANDOM % 86 )); s4=$(( 15 + RANDOM % 86 ))
  b1=$(( 5 + (RANDOM*RANDOM) % 900000000 ));          b2=$(( 1000000000 + (RANDOM*RANDOM) % 900000000 ))
  b3=$(( 2000000000 + (RANDOM*RANDOM) % 900000000 )); b4=$(( 3000000000 + (RANDOM*RANDOM) % 900000000 ))
  printf 'Jc = 4\nJmin = 40\nJmax = 70\nS1 = %s\nS2 = %s\nS3 = %s\nS4 = %s\nH1 = %s-%s\nH2 = %s-%s\nH3 = %s-%s\nH4 = %s-%s\n' \
    "$s1" "$s2" "$s3" "$s4" "$b1" $((b1+w)) "$b2" $((b2+w)) "$b3" $((b3+w)) "$b4" $((b4+w))
  printf 'I1 = <b 0xc300000001><r 1200>\n'   # QUIC v1 Initial prefix + random; no <c>/<t> (Android-safe)
}
server_addr(){ have python3 || die "python3 required for the tunnel address (also needed by the daemon)"
  python3 - "$1" <<'PY'
import ipaddress, sys
n = ipaddress.ip_network(sys.argv[1], strict=False)
print(f"{next(n.hosts())}/{n.prefixlen}")
PY
}
create_iface(){ # prompt, gen server key, write conf (AWG v2 + QUIC I1, or plain WG), NAT it to the WAN, bring up, register
  local _proto proto name port subnet addr conf cmd priv dir wan up down idx defname defport defsub upok ep
  idx=${#IF_CMD[@]}                              # offset defaults so a 2nd/3rd iface doesn't collide
  ask_choice "Protocol — (a)mneziawg or (w)ireguard?" "a" _proto "a w awg wg amneziawg wireguard"
  case "$_proto" in w|wg|wireguard) proto=wg; cmd=wg;  dir=/etc/wireguard;;
                                 *) proto=awg; cmd=awg; dir=/etc/amnezia/amneziawg;; esac
  defname="$([ "$cmd" = awg ] && echo "awg$idx" || echo "wg$idx")"
  while [ -n "${IF_CMD[$defname]:-}" ] || [ -e "/etc/amnezia/amneziawg/$defname.conf" ] || [ -e "/etc/wireguard/$defname.conf" ]; do
    idx=$((idx+1)); defname="$([ "$cmd" = awg ] && echo "awg$idx" || echo "wg$idx")"; done
  while :; do
    ask_valid "Interface name" "$defname" name v_iface "1–15 chars: letters, digits, - or _"
    if [ -n "${IF_CMD[$name]:-}" ] || [ -e "/etc/amnezia/amneziawg/$name.conf" ] || [ -e "/etc/wireguard/$name.conf" ]; then
      warn "interface '$name' already exists — pick another name"; name=""; continue
    fi
    break
  done
  defport=$((51820 + idx)); defsub="10.$(( (8 + idx) % 255 )).0.0/24"
  ask_valid "Listen port" "$defport" port v_freeport "port 1–65535 and free (not already in use)"
  ask_valid "Tunnel subnet (CIDR; server takes the first host)" "$defsub" subnet v_subnet "enter a CIDR, e.g. 10.8.0.0/24"
  ask_valid "WAN egress interface (clients are NAT'd out using this)" "$(detect_wan || echo eth0)" wan v_iface "enter a network interface name"
  ask_valid "Endpoint clients dial for $(col "$C_GREEN" "$name") (this interface's public IP/host)" "$(detect_public_ip)" ep v_host "enter an IP address or hostname"
  addr="$(server_addr "$subnet")"; conf="$dir/$name.conf"
  if ! ensure_wg_tools "$cmd"; then warn "couldn't install $cmd tools — skipping interface '$name'"; return 0; fi
  up="sysctl -q -w net.ipv4.ip_forward=1; iptables -t nat -A POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -A FORWARD -i %i -o ${wan} -j ACCEPT; iptables -A FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
  down="iptables -t nat -D POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -D FORWARD -i %i -o ${wan} -j ACCEPT; iptables -D FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
  printf 'net.ipv4.ip_forward = 1\n' | writef /etc/sysctl.d/99-swg-forward.conf 644
  run sysctl -q -w net.ipv4.ip_forward=1
  if $DRYRUN; then priv="<generated-on-real-run>"
  elif ! priv="$("$cmd" genkey 2>/dev/null)" || [ -z "$priv" ]; then warn "'$cmd genkey' failed — skipping interface '$name'"; return 0; fi
  { printf '[Interface]\nPrivateKey = %s\nAddress = %s\nListenPort = %s\nMTU = %s\n' "$priv" "$addr" "$port" "$WG_MTU"
    printf 'PostUp = %s\nPostDown = %s\n' "$up" "$down"
    if [ "$cmd" = awg ]; then awg_obfuscation; fi; } | writef "$conf" 600
  # bring up — NON-FATAL: a port/subnet clash must not abort the whole install (set -e)
  upok=yes
  if [ "$cmd" = awg ]; then run awg-quick up "$name" || upok=no; [ "$upok" = yes ] && { run systemctl enable "awg-quick@$name" || true; }
  else                     run wg-quick  up "$name" || upok=no; [ "$upok" = yes ] && { run systemctl enable "wg-quick@$name"  || true; }; fi
  if [ "$upok" = no ]; then
    warn "couldn't bring up '$name' (a port or subnet may already be in use) — removing its conf; try again with different values"
    run rm -f "$conf"; return 0
  fi
  IF_CMD[$name]="$cmd"; IF_CONF[$name]="$conf"; IF_ENDPOINT[$name]="$ep"; LAST_IFACE="$name"
  ok "created $proto interface $(col "$C_GREEN" "$name") on :$port (server $addr, NAT out $wan)"
}
choose_ifaces(){ # populate SELECTED[] — all detected interfaces are managed; 'new' creates more
  detect_wg
  if [ -n "$MANAGE_IFACES" ]; then
    IFS=',' read -ra SELECTED <<< "$MANAGE_IFACES"
  else
    info "Checking for wg / awg on this host…"
    if [ "${#IF_CMD[@]}" -eq 0 ]; then
      warn "No wg / awg interfaces found in /etc/wireguard or /etc/amnezia."
      local doit; ask_yn "Create one now? (installs WireGuard / AmneziaWG only if missing)" y doit
      [ "$doit" = yes ] && create_iface
      detect_wg
      [ "${#IF_CMD[@]}" -eq 0 ] && { $DRYRUN || die "create an interface, then re-run"; IF_CMD[awg0]=awg; IF_CONF[awg0]=/etc/amnezia/amneziawg/awg0.conf; }
    fi
    local names=() pick n
    while :; do
      detect_wg; names=("${!IF_CMD[@]}")
      echo
      printf "  Available interfaces:"
      for n in "${names[@]}"; do printf ' %s %s' "$(col "$C_GREEN" "$n")" "$(b "(${IF_CMD[$n]})")"; done
      echo; echo
      # print the prompt with printf (NOT read -p) so it always shows; never hide it via 2>/dev/null
      printf '  Press %s to proceed with the setup or enter "%s" to create an additional interface: ' "$(b Enter)" "$(col "$C_BLUE" new)"
      if ! read -r pick </dev/tty; then
        echo; warn "no interactive input — managing all detected interfaces"; break
      fi
      pick="${pick//[[:space:]]/}"
      [ "$pick" = new ] && { create_iface; continue; }
      [ -z "$pick" ] && break
      warn "type nothing to proceed, or \"new\" to add another interface"
    done
    SELECTED=("${names[@]}")          # every detected interface ends up in the web panel
  fi
  detect_wg
  local _ep
  for n in "${SELECTED[@]}"; do n="${n// /}"; [ -n "${IF_CMD[$n]:-}" ] || { [ -e "/etc/amnezia/amneziawg/$n.conf" ] && { IF_CMD[$n]=awg; IF_CONF[$n]="/etc/amnezia/amneziawg/$n.conf"; } || { IF_CMD[$n]=wg; IF_CONF[$n]="/etc/wireguard/$n.conf"; }; }
    [ -n "${IF_ENDPOINT[$n]:-}" ] && continue   # interfaces just created already have an endpoint
    _ep=""; ask_valid "Endpoint clients dial for $(col "$C_GREEN" "$n") (this interface's public IP/host)" "$(detect_public_ip)" _ep v_host "enter an IP address or hostname"
    IF_ENDPOINT[$n]="$_ep"; done
  [ "${#SELECTED[@]}" -gt 0 ] || die "no interfaces selected"
  ok "Managing: $(b "$(col "$C_GREEN" "${SELECTED[*]}")")"
}

# ───────────────────────── turn-proxy (vk-turn-proxy) ─────────────────────────
# Tunnels WireGuard/AmneziaWG through VK/Yandex TURN servers. Config is the systemd
# unit's CLI args: -listen <pub-ip:port>  -connect <wg-ip:port>. We detect any such
# unit, can install the binary from a fork's GitHub releases, and record listen→connect
# so the panel can later tell a turn-proxied client from a direct one.
# https://github.com/cacggghp/vk-turn-proxy
TURN_DIR="${TURN_DIR:-/opt/vk-turn-proxy}"
TURN_RECORD="${TURN_RECORD:-/etc/swg-agent/turn-proxy.json}"
declare -A TP_LISTEN TP_CONNECT TP_WRAP
turn_repo_owner(){ case "$1" in
  wings) echo "WINGS-N/vk-turn-proxy";; samosvalishe) echo "samosvalishe/vk-turn-proxy";;
  kiper292) echo "kiper292/vk-turn-proxy";; anton48) echo "anton48/vk-turn-proxy";;
  main) echo "cacggghp/vk-turn-proxy";; *) return 1;; esac; }
gen_wrap_key(){ $DRYRUN && { echo "GENERATED-ON-REAL-RUN"; return 0; }   # 32-byte key as 64 hex chars
  openssl rand -hex 32 2>/dev/null || head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
# Per-fork obfuscation flags (verified from each binary's -h). Echoes the flags WITH a
# freshly generated -wrap-key baked in (kiper292 has no wrap support → empty).
turn_wrap_flags(){ local k; case "$1" in
  anton48)      k="$(gen_wrap_key)"; printf -- '-wrap-srtp -wrap-key %s' "$k";;
  samosvalishe) k="$(gen_wrap_key)"; printf -- '-wrap -wrap-key %s' "$k";;
  wings)        k="$(gen_wrap_key)"; printf -- '-wrap-mode on -wrap-key %s' "$k";;
  *) printf '';; esac; }
turn_wg_ports(){   # echo "<iface>:<ListenPort>" for every interface managed in the wg/awg step
  local n p
  for n in ${SELECTED[@]+"${SELECTED[@]}"}; do
    [ -n "${IF_CONF[$n]:-}" ] || continue
    p="$(grep -iE '^[[:space:]]*ListenPort[[:space:]]*=' "${IF_CONF[$n]}" 2>/dev/null | head -1 | sed 's/.*=[[:space:]]*//; s/[^0-9].*//')"
    [ -n "$p" ] && printf '%s:%s\n' "$n" "$p"
  done
}
detect_turn(){   # any systemd unit whose ExecStart carries both -listen and -connect is a turn-proxy
  TP_LISTEN=(); TP_CONNECT=(); TP_WRAP=(); local u name exe lis con wk
  for u in /etc/systemd/system/*.service; do
    [ -e "$u" ] || continue
    exe="$(sed -n 's/^ExecStart=//p' "$u" 2>/dev/null | head -1)"
    case "$exe" in *-listen*-connect*|*-connect*-listen*) ;; *) continue;; esac
    name="$(basename "$u" .service)"
    lis="$(printf '%s\n' "$exe" | sed -n 's/.*-listen[ =]\{1,\}\([^ ]*\).*/\1/p')"
    con="$(printf '%s\n' "$exe" | sed -n 's/.*-connect[ =]\{1,\}\([^ ]*\).*/\1/p')"
    wk="$(printf '%s\n' "$exe" | sed -n 's/.*-wrap-key[ =]\{1,\}\([^ ]*\).*/\1/p')"
    TP_LISTEN[$name]="$lis"; TP_CONNECT[$name]="$con"; TP_WRAP[$name]="$wk"
  done
}
turn_latest_tag(){ $DRYRUN && { echo "v0.0.0"; return 0; }   # turn_latest_tag <owner/repo>
  curl -fsSL --connect-timeout 10 --max-time 20 "https://api.github.com/repos/$1/releases/latest" 2>/dev/null \
    | python3 -c 'import sys,json;print(json.load(sys.stdin).get("tag_name",""))' 2>/dev/null || true; }
install_turn_binary(){ # <fork> <owner/repo> <listen ip:port> <connect ip:port> <extra-flags>
  local fork="$1" owner="$2" listen="$3" connect="$4" extra="$5" arch dir bin svc url ver port inst
  case "$(uname -m)" in x86_64|amd64) arch=amd64;; aarch64|arm64) arch=arm64;; *) arch=amd64;; esac
  # key each instance by <fork>-<port> so one fork can run many times (different ports + wrap keys)
  port="${listen##*:}"; inst="$fork-$port"; dir="$TURN_DIR/$inst"; bin="$dir/server"; svc="vk-turn-proxy-$inst"
  if [ -e "/etc/systemd/system/$svc.service" ]; then warn "turn-proxy $svc already exists — pick another port"; return 0; fi
  url="https://github.com/$owner/releases/latest/download/server-linux-$arch"
  mkdir -p "$PREFIX$dir"
  info "Installing $owner ($listen → $connect) — downloading the binary from GitHub (up to ~2 min)…"
  if $DRYRUN; then echo "    [skip] curl -fsSL $url -o $bin"
  elif ! { curl -fsSL --connect-timeout 10 --max-time 120 --retry 2 --retry-delay 2 --retry-all-errors "$url" -o "$PREFIX$bin" && chmod +x "$PREFIX$bin"; }; then
    warn "download failed ($url) — skipping this turn-proxy"; return 0
  fi
  ver="$(turn_latest_tag "$owner")"
  printf '%s\n' "$owner"          | writef "$dir/repo.txt" 644
  printf '%s\n' "${ver:-unknown}" | writef "$dir/version.txt" 644
  writef "/etc/systemd/system/$svc.service" 600 <<EOF
[Unit]
Description=vk-turn-proxy ($owner) — ${listen} → ${connect}
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=${bin} -listen ${listen} -connect ${connect} ${extra}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  run systemctl daemon-reload; run systemctl enable --now "$svc" || warn "couldn't start $svc"
  ok "installed turn-proxy $(col "$C_GREEN" "$inst") ($owner ${ver:-?}) — $listen → $connect"
}
install_turn_proxy(){   # <fork> — params, then install (the fork is chosen in choose_turn_proxy)
  local sel="$1" owner pub port connect extra; owner="$(turn_repo_owner "$sel")" || { warn "unknown turn-proxy branch: $sel"; return 0; }
  ask_valid "Public IP this turn-proxy is reached at" "$(detect_public_ip)" pub v_host "an IP or hostname"
  ask_valid "Turn-proxy listen port" "56000" port v_freeport "port 1–65535 and free (not already in use)"
  detect_turn; local _n; for _n in "${!TP_LISTEN[@]}"; do [ "${TP_LISTEN[$_n]##*:}" = "$port" ] && { warn "port $port is already used by turn-proxy '$_n' — pick another port (enter 'new' again)"; return 0; }; done
  local ports defport=51820 disp n p proto first; ports="$(turn_wg_ports)"
  if [ -n "$ports" ]; then
    defport="$(printf '%s\n' "$ports" | head -1 | cut -d: -f2)"; disp=""; first=1
    while IFS=: read -r n p; do proto="${IF_CMD[$n]:-wg}"
      [ "$first" = 1 ] && first=0 || disp+=", "
      disp+="$(col "$C_BLUE" "$p") ($(col "$C_GREEN" "$n") on $(b "$proto"))"
    done <<< "$ports"
    echo "  Available wg/awg ports: ${disp}"
  fi
  ask_valid "WireGuard/AmneziaWG address it forwards to (ip:port)" "127.0.0.1:${defport}" connect v_hostport "ip:port, e.g. 127.0.0.1:51820"
  local wrap extra; wrap="$(turn_wrap_flags "$sel")"
  [ -n "$wrap" ] && info "Obfuscation: a 64-hex wrap key is generated, baked into the unit, and recorded for the panel / client configs." \
                 || warn "$sel has no wrap/srtp obfuscation flags — installing plain (-listen/-connect only)."
  ask "Extra server flags (optional)" "" extra
  install_turn_binary "$sel" "$owner" "$pub:$port" "$connect" "$wrap${extra:+ $extra}"
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
      echo "  Installed turn-proxy servers:"
      for n in "${names[@]}"; do printf '    %s %s\n' "$(col "$C_GREEN" "$n")" "$(b "(${TP_LISTEN[$n]} → ${TP_CONNECT[$n]})")"; done
    else
      warn "No turn-proxy servers found on this box."
    fi
    echo
    echo "  Here is a list of turn-proxy branches available for installation:"
    echo
    menu "$(col "$C_BLUE" wings)"        "For Android — https://github.com/WINGS-N/vk-turn-proxy"
    menu "$(col "$C_BLUE" samosvalishe)" "For Android — https://github.com/samosvalishe/vk-turn-proxy"
    menu "$(col "$C_BLUE" kiper292)"     "For Android — https://github.com/kiper292/vk-turn-proxy"
    menu "$(col "$C_BLUE" anton48)"      "For iOS — https://github.com/anton48/vk-turn-proxy"
    printf '  Select a turn-proxy repository to install or just press %s to skip and proceed with the setup: ' "$(b Enter)"
    if ! read -r sel 2>/dev/null </dev/tty; then echo; warn "no interactive input — skipping turn-proxy step"; break; fi
    sel="${sel//[[:space:]]/}"
    [ -z "$sel" ] && break
    case "$sel" in
      wings|samosvalishe|kiper292|anton48) install_turn_proxy "$sel"; continue;;
      *) warn "‘$sel’ isn't one of: wings samosvalishe kiper292 anton48 (or press Enter to skip)";;
    esac
  done
  write_turn_record
}

[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && { info "DRY RUN — files render under ./dryrun, nothing executes."; rm -rf "$PREFIX"; }

# ═══════════════ NODE SETUP ═══════════════
echo; info "NODE SETUP"

# Panel connection — normally supplied by the install command's -host / -key flags.
if $DRYRUN; then ask "Panel URL (https://host[/subpath])" "" PANEL_URL
else ask_valid "Panel URL (https://host[/subpath])" "" PANEL_URL v_httpsurl "enter the panel's https:// URL (pass -host to skip this)"; fi
if $DRYRUN; then ask "Node enrollment key (from the Nodes screen)" "" NODE_TOKEN
else ask_valid "Node enrollment key (from the Nodes screen)" "" NODE_TOKEN v_token "paste the key from Nodes → Add node (pass -key to skip this)"; fi
case "$PANEL_URL" in https://*) ;; *) warn "panel URL is not https:// — the key would travel in clear. Continue only if you know why.";; esac
if [ -z "$TLS_VERIFY" ] && [ -z "$TLS_FINGERPRINT" ]; then
  ask_yn "Verify the panel's TLS certificate? (answer no if the panel uses a self-signed cert)" n TLS_VERIFY
fi

# The node's panel name comes from Nodes → Add node (matched by the enrollment token),
# NOT from here. NODE_NAME is only a local label for this box's systemd unit + final
# message, so default it to the hostname and don't prompt for it.
NODE_NAME="${NODE_NAME:-$(hostname -s 2>/dev/null || hostname)}"

echo
echo "$(b 'Step 1. WireGuard / AmneziaWG setup')   (each interface has its own endpoint IP)"
echo
choose_ifaces

echo
echo "$(b 'Step 2. TURN-PROXY setup') (https://github.com/cacggghp/vk-turn-proxy)"
echo
choose_turn_proxy

# ───────────────────────── install binaries ─────────────────────────
info "Agent + daemon"
for f in swg-agent swg-noded; do [ -f "$SRC/$f" ] || die "missing $f beside this script (unzip the bundle here)"; done
mkdir -p "$PREFIX$AGENT_DIR" "$PREFIX$NODED_DIR"; cp "$SRC/swg-agent" "$PREFIX$AGENT_DIR/"; cp "$SRC/swg-noded" "$PREFIX$NODED_DIR/"
chmod 755 "$PREFIX$AGENT_DIR/swg-agent" "$PREFIX$NODED_DIR/swg-noded"; ok "installed agent + daemon"
[ -f "$SRC/VERSION" ] && cp "$SRC/VERSION" "$PREFIX$NODED_DIR/" || true   # version stamp (update.sh reports it)
mkdir -p "$PREFIX/var/lib/swg-noded" "$PREFIX/var/log/swg-agent" "$PREFIX/etc/swg-agent"

# ───────────────────────── config.json (pull-only HTTPS) ─────────────────────────
IFJSON=""; sep=""
for n in "${SELECTED[@]}"; do n="${n// /}"; [ -z "$n" ] && continue
  IFJSON+="$sep    \"$n\": { \"cmd\": [\"${IF_CMD[$n]}\"], \"conf\": \"${IF_CONF[$n]}\", \"endpoint_host\": \"${IF_ENDPOINT[$n]:-}\" }"; sep=$',\n'; done
# node-level endpoint_host is now a fallback (the panel uses each interface's own when blank); default it to the first interface's
if [ -z "$ENDPOINT_IP" ]; then for n in "${SELECTED[@]}"; do [ -n "${IF_ENDPOINT[$n]:-}" ] && { ENDPOINT_IP="${IF_ENDPOINT[$n]}"; break; }; done; fi
[ -z "$ENDPOINT_IP" ] && ENDPOINT_IP="$(detect_public_ip)"
VERIFY_JSON=$([ "$TLS_VERIFY" = yes ] && echo true || echo false)
FP=""; [ -n "$TLS_FINGERPRINT" ] && FP=$',\n    "fingerprint": "'"$TLS_FINGERPRINT"'"'
writef /etc/swg-agent/config.json 640 <<EOF
{
  "interfaces": {
$IFJSON
  },
  "endpoint_host": "${ENDPOINT_IP}",
  "dns": ["${DNS}"],
  "panel": {
    "url": "${PANEL_URL}",
    "token": "${NODE_TOKEN}",
    "verify": ${VERIFY_JSON}${FP}
  },
  "node": {
    "interval": ${INTERVAL},
    "agent": "${AGENT_DIR}/swg-agent",
    "sudo": false
  }
}
EOF
warn "config.json holds the node key (mode 640, root:root). Treat it as a secret."

# ───────────────────────── daemon service (root) ─────────────────────────
writef /etc/systemd/system/swg-noded.service 644 <<EOF
[Unit]
Description=swg-noded (HTTPS sync to panel) — ${NODE_NAME}
After=network-online.target
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

# ───────────────────────── enable ─────────────────────────
info "Enable daemon"
run systemctl daemon-reload
run systemctl enable --now swg-noded

echo; ok "Node '$(bb "$NODE_NAME")' install complete."
# ───────────────────────── SUMMARY ─────────────────────────
echo; echo "$(b '──────────────── SUMMARY ────────────────')"; echo
echo "  Node      $(bb "$NODE_NAME")  →  syncs to $(bb "$PANEL_URL") every ${INTERVAL}s"
if [ "${#SELECTED[@]}" -gt 0 ]; then echo; echo "  $(b 'Interfaces') (manage peers in the panel):"
  for n in "${SELECTED[@]}"; do c="${IF_CONF[$n]:-}"
    printf '    %s %-9s endpoint %s  subnet %s  mtu %s\n' "$(col "$C_GREEN" "$(printf '%-10s' "$n")")" "${IF_CMD[$n]:-?}" \
      "$(bb "${IF_ENDPOINT[$n]:-$ENDPOINT_IP}:$(conf_get "$c" ListenPort)")" "$(b "$(conf_get "$c" Address)")" "$(conf_get "$c" MTU)"
  done
fi
detect_turn
if [ "${#TP_LISTEN[@]}" -gt 0 ]; then echo; echo "  $(b 'Turn-proxy') instances:"
  for n in "${!TP_LISTEN[@]}"; do wk="${TP_WRAP[$n]}"
    printf '    %s %s → %s   %s\n' "$(col "$C_GREEN" "$(printf '%-22s' "$n")")" "$(bb "${TP_LISTEN[$n]}")" "$(b "${TP_CONNECT[$n]}")" "${wk:+wrap-key $(b "$wk")}"
  done
fi
echo
echo "  Edit      interfaces in $(b /etc/amnezia/amneziawg/) / $(b /etc/wireguard/)  ·  daemon $(b /etc/swg-agent/config.json)"
echo "  Logs      $(b 'journalctl -u swg-noded -f')  ·  turns green in the panel's Nodes screen in ~${INTERVAL}s"
[ "$VERIFY_JSON" = false ] && [ -z "$TLS_FINGERPRINT" ] && echo "  TLS       not verifying the panel cert (self-signed) — set TLS_FINGERPRINT to pin it"
$DRYRUN && { echo; ok "DRY RUN done — inspect ./dryrun"; }
