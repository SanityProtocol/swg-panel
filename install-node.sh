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
ADOPTED_IFACES="${ADOPTED_IFACES:-}"   # interfaces migrated in by convert.sh — shown as "already on this node", not orphan/docker
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
. "$SRC/lib/common.sh"   # shared helpers: v_iface/v_subnet/v_hostport, next_free_port, turn_repo_owner, dl_turn_bin
# Refuse on a declaratively managed host BEFORE anything is written — a node laid down here would
# be invisible to the host's own tooling. Defined in lib/common.sh, above; a `--dry-run` still runs.
refuse_on_declarative_host 'services.swg-node = { enable = true; ... };'

# ── colours / styling (honour NO_COLOR + non-tty) ──
if { [ -t 1 ] || [ -n "${SWG_FORCE_COLOR:-}" ]; } && [ -z "${NO_COLOR:-}" ]; then
  BOLD=$'\033[1m'; RESET=$'\033[0m'
  C_BLUE=$'\033[38;5;39m'; C_GREEN=$'\033[32m'; C_GREY=$'\033[90m'; C_CYAN=$'\033[36m'; C_RED=$'\033[31m'; C_YEL=$'\033[33m'; C_BL=$'\033[38;5;33m'; C_BROWN=$'\033[38;5;130m'
else BOLD=""; RESET=""; C_BLUE=""; C_GREEN=""; C_GREY=""; C_CYAN=""; C_RED=""; C_YEL=""; C_BL=""; C_BROWN=""; fi
b(){   printf '%s%s%s' "$BOLD" "$*" "$RESET"; }
bb(){  printf '%s%s%s%s' "$BOLD" "$C_BLUE" "$*" "$RESET"; }   # bold + blue (summary highlights)
col(){ local _c="$1"; shift; printf '%s%s%s' "$_c" "$*" "$RESET"; }
conf_get(){ grep -iE "^[[:space:]]*$2[[:space:]]*=" "$1" 2>/dev/null | head -1 | sed 's/.*=[[:space:]]*//; s/[[:space:]]*$//'; }
# one styled interface row (green name + proto + endpoint:port + address) for the manage-loop lists, matching the SUMMARY.
iface_row(){ local n="$1" conf proto ep lp addr _c   # set -e safe; prefer a just-queued spec (no conf yet), else the conf
  is_sys_iface "$n" && return 0   # panel-managed mesh links are never shown in a user-facing interface list
  if [ -n "${SPEC_CMD[$n]:-}" ]; then proto="${SPEC_CMD[$n]}"; lp="${SPEC_PORT[$n]:-}"; addr="${SPEC_ADDR[$n]:-}"; ep="${SPEC_EP[$n]:-}"
  else conf="${IF_CONF[$n]:-}"; proto="${IF_CMD[$n]:-?}"; ep="${IF_ENDPOINT[$n]:-${ENDPOINT_IP:-}}"
    { [ -n "$conf" ] && [ -f "$conf" ]; } || for _c in "/etc/amnezia/amneziawg/$n.conf" "/etc/wireguard/$n.conf"; do [ -f "$_c" ] && { conf="$_c"; break; }; done   # IF_CONF missed it (e.g. an adopted iface) → find the on-disk conf by name so port/addr aren't '?'
    lp="$(conf_get "$conf" ListenPort || true)"; addr="$(conf_get "$conf" Address || true)"; fi
  [ -n "$ep" ] || ep="$(detect_public_ip 2>/dev/null || true)"
  case "${proto:-?}" in ''|'?') case "$n" in awg*) proto=awg;; wg*) proto=wg;; esac;; esac   # unknown proto → infer from the name (awg0 ⇒ AmneziaWG)
  printf '    %s%s%s  %s%-10s%s  %s:%s  %s\n' "$C_GREEN" "$(printf '%-10s' "$n")" "$RESET" "$BOLD" "$(proto_label "${proto:-?}")" "$RESET" "${ep:-?}" "${lp:-?}" "${addr:-?}"; }
# WDTT instances this node runs, from its own record. Their interfaces are brought up by the WDTT server itself and
# have NO .conf, so detect_wg (a conf-dir scan) can never see them — list them explicitly or they look absent.
# Emits "<iface>\t<listen>\t<subnet>" per line.
# Every interface this node ALREADY manages (wg/awg from config.json + its WDTT instances) — the "local" set, as
# opposed to anything else on the box, which is an adoption candidate for the panel.
local_ifaces(){ { node_ifaces; wdtt_local | cut -f1; } 2>/dev/null | awk 'NF' | sort -u; }
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
writef(){ local p="$1" m="${2:-644}" full="$PREFIX$1"; mkdir -p "$(dirname "$full")"; cat > "$full"; chmod "$m" "$full" 2>/dev/null || true; ok "wrote $p ($m)"; }
menu(){ printf '  %s\n      %s\n\n' "$1" "$2"; }
key(){  printf '%s[%s]%s%s'   "$C_BLUE"        "$1" "$2" "$RESET"; }   # whole label blue:        key  a 'mneziawg'           → [a]mneziawg
keyd(){ printf '%s%s[%s]%s%s' "$BOLD" "$C_BLUE" "$1" "$2" "$RESET"; }   # default label bold+blue: keyd a 'mneziawg (default)'  → [a]mneziawg (default)
STEP="${STEP_BASE:-1}"; step(){ [ -n "${_SWG_NL:-}" ] || echo; _SWG_NL=""; echo "$(b "Step $STEP. $1")${2:+   $2}"; STEP=$((STEP+1)); }   # skip the leading blank when a prompt already printed one

ask(){ local v p="$1" d="${2:-}"; if [ -n "${!3:-}" ]; then return; fi
  [ -n "${_SWG_NL:-}" ] || echo; _SWG_NL=""; read -rp "  $p${d:+ [$(col "$C_BLUE" "$d")]}: " v </dev/tty || true; printf -v "$3" '%s' "${v:-$d}"; _pnl; }
ask_yn(){ local v p="$1" d="${2:-y}"; if [ -n "${!3:-}" ]; then return; fi
  [ -n "${_SWG_NL:-}" ] || echo; _SWG_NL=""; read -rp "  $p ($([ "$d" = y ] && echo 'Y/n' || echo 'y/N')): " v </dev/tty || true
  v="${v:-$d}"; case "$v" in [Yy]*) printf -v "$3" yes;; *) printf -v "$3" no;; esac; _pnl; }

# ── input validators (0 = ok) ──
v_proto(){   case "$1" in a|awg|amneziawg|w|wg|wireguard) return 0;; *) return 1;; esac; }
v_ip(){      printf '%s' "$1" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$' || return 1
             local o; for o in ${1//./ }; do [ "$o" -le 255 ] 2>/dev/null || return 1; done; return 0; }
v_host(){    v_ip "$1" && return 0; case "$1" in ""|*" "*|*[!a-zA-Z0-9.-]*) return 1;; *) return 0;; esac; }
v_httpsurl(){ case "$1" in https://*|http://*) v_host "$(x="${1#http://}"; x="${x#https://}"; x="${x%%/*}"; printf '%s' "${x%%:*}")";; *) v_host "$(x="${1%%/*}"; printf '%s' "${x%%:*}")";; esac; }   # no scheme ok → https:// is prepended after the prompt
v_port(){    case "$1" in ""|*[!0-9]*) return 1;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
port_free(){ local p="$1" n   # UDP port not already bound AND not already taken by an interface queued this session
  for n in ${SPEC_ORDER[@]+"${SPEC_ORDER[@]}"}; do [ "${SPEC_PORT[$n]:-}" = "$p" ] && return 1; done
  have ss || return 0; [ -z "$(ss -lnuH "sport = :$p" 2>/dev/null)" ]; }
v_freeport(){ v_port "$1" && port_free "$1"; }
# smart default ports: first install offers the base; later ones offer (highest used OF THAT KIND)+1, then the
# next host-free port. turn = TP_LISTEN units; wg/awg = highest ListenPort across confs, never below 51820+queued.
turn_default_port(){ detect_turn; local hi=0 lis p; if [ "${#TP_LISTEN[@]}" -gt 0 ]; then for lis in "${TP_LISTEN[@]}"; do p="${lis##*:}"; case "$p" in ''|*[!0-9]*) :;; *) [ "$p" -gt "$hi" ] && hi="$p";; esac; done; fi; [ "$hi" -gt 0 ] && next_free_port $((hi+1)) || next_free_port 56000; }
v_name(){    case "$1" in ""|*[!a-zA-Z0-9_-]*) return 1;; esac; [ "${#1}" -le 40 ]; }
v_token(){   [ -n "$1" ] && [ "${#1}" -ge 8 ]; }   # v_iface/v_subnet/v_hostport now in lib/common.sh

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

detect_public_ip(){ # best public IPv4: default-route source, then first hostname -I
  local ip; ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1 || true)"
  case "$ip" in 127.*) ip="";; esac                                                   # never the loopback — clients can't reach it
  [ -z "$ip" ] && ip="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -vE '^127\.' | head -n1 || true)"
  printf '%s' "$ip"; }

# ── idempotent re-install: read the current install's panel URL/token + per-interface endpoints, to
#    offer as defaults (so re-running keeps everything). Fresh install = run the uninstaller first.
EXIST_URL=""; EXIST_TOKEN=""; EXISTING=no
read_existing(){
  { [ -f /etc/swg-agent/config.json ] && have python3; } || return 0
  EXISTING=yes
  EXIST_URL="$(python3 -c 'import json;print(json.load(open("/etc/swg-agent/config.json")).get("panel",{}).get("url",""))' 2>/dev/null || true)"
  EXIST_TOKEN="$(python3 -c 'import json;print(json.load(open("/etc/swg-agent/config.json")).get("panel",{}).get("token",""))' 2>/dev/null || true)"
  while IFS='|' read -r n ep; do [ -n "$n" ] && [ -z "${IF_ENDPOINT[$n]:-}" ] && IF_ENDPOINT[$n]="$ep"; done < <(python3 -c '
import json
for n,ic in (json.load(open("/etc/swg-agent/config.json")).get("interfaces") or {}).items():
    e=ic.get("endpoint_host","")
    if e: print("%s|%s"%(n,e))' 2>/dev/null || true)
  return 0   # the while-loop falls through non-zero if the last iface's endpoint was already set; bare-called at NODE SETUP start
}
detect_wan(){ ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n1; }

declare -A IF_CMD IF_CONF IF_ENDPOINT; declare -a SELECTED CREATED   # IF_ENDPOINT: per-interface public IP clients dial; CREATED: ifaces made this run
declare -A SPEC_CMD SPEC_PROTO SPEC_PORT SPEC_SUBNET SPEC_ADDR SPEC_WAN SPEC_EP SPEC_DIR; declare -a SPEC_ORDER=()   # queued interfaces (prompted now, installed at the end by apply_specs)
detect_wg(){ # every CONVENTIONAL wg/awg location, not just the ones we install into — a box configured by a
  # distro package, an upstream installer or by hand is exactly what adoption exists for, and it used to be invisible.
  IF_CMD=(); IF_CONF=(); local f n d
  for d in /etc/amnezia /etc/amneziawg /usr/local/etc/amneziawg; do
    [ -d "$d" ] || continue
    while IFS= read -r f; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=awg; IF_CONF[$n]="$f"
    done < <(find "$d" -maxdepth 3 -type f -name '*.conf' 2>/dev/null)
  done
  for d in /etc/wireguard /usr/local/etc/wireguard; do
    [ -d "$d" ] || continue
    for f in "$d"/*.conf; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=wg; IF_CONF[$n]="$f"; done
  done
}
ensure_wg_tools(){ # ensure_wg_tools <awg|wg> — install tools + kernel module if missing (idempotent, non-fatal -> 0/1).
  # Success = the CLI is present AND its kernel module LOADS. `apt install amneziawg` installs the `awg` tool but the
  # datapath is a DKMS module that must COMPILE against the running kernel (needs dkms + linux-headers-$(uname -r));
  # without them `awg` exists yet `ip link add type amneziawg` dies with "Unknown device type". So install the build
  # deps and verify `modprobe` before declaring success.
  local cmd="$1"
  if [ "$cmd" = wg ]; then
    have wg || { if $DRYRUN || have apt-get; then info "installing WireGuard tools via apt — this can take a minute…"; run apt-get update -qq || true; run apt-get install -y wireguard || true; else warn "WireGuard tools not found and no apt-get on this system — install 'wireguard' with your package manager, then re-run"; fi; }
    $DRYRUN && return 0
    have wg && { modprobe wireguard 2>/dev/null || true; return 0; }
    return 1
  fi
  if have awg && modprobe amneziawg 2>/dev/null; then return 0; fi
  # graceful degrade on a non-apt distro (Fedora/RHEL/Arch/Alpine): don't silently limp — tell the operator exactly
  # what to install with their own package manager. apt paths below stay for Debian/Ubuntu.
  $DRYRUN || have apt-get || { warn "AmneziaWG not installed — no apt-get on this system; install dkms, linux-headers-$(uname -r) and amneziawg-dkms with your package manager, then re-run"; return 1; }
  info "installing AmneziaWG (tools + DKMS kernel module) via apt — this can take a minute…"
  run apt-get update -qq || true
  run apt-get install -y software-properties-common || true
  run add-apt-repository -y ppa:amnezia/ppa || true
  run apt-get update -qq || true
  run apt-get install -y dkms "linux-headers-$(uname -r)" || run apt-get install -y dkms linux-headers-generic || true
  run apt-get install -y amneziawg amneziawg-dkms amneziawg-tools || run apt-get install -y amneziawg || true
  build_awg_module
  $DRYRUN && return 0
  have awg && modprobe amneziawg 2>/dev/null && return 0
  # The apt path did not get us there — Debian (the PPA is Ubuntu-only), a non-apt distro, or a kernel with
  # no matching headers. Do NOT stop at a warning: build from source, which is the only route to the KERNEL
  # datapath off Ubuntu and is what we want wherever it is possible.
  awg_build_from_source && { info "AmneziaWG: kernel datapath (built from source)"; return 0; }
  # Still no module: no headers for this kernel, or an LXC/OpenVZ guest that cannot load one at all. Fall
  # back to userspace so the node can still serve AmneziaWG — awg-quick picks it up by itself.
  if ensure_awg_userspace; then
    warn "AmneziaWG will run on the SLOWER userspace datapath — no loadable kernel module on $(uname -r).$(
      have apt-get && printf ' %s' 'Installing matching linux-headers and re-running the installer switches it to the kernel module.')"
    return 0
  fi
  return 1
}
build_awg_module(){ # FORCE the amneziawg DKMS module to COMPILE for the RUNNING kernel — `apt install amneziawg` is
  # a NO-OP when the package is already present (tool on disk) yet its module never built (headers missing then).
  # `-k $(uname -r)` targets the running kernel: a box on an OLD kernel with newer headers would otherwise build
  # for the wrong one and modprobe would still fail.
  run dkms autoinstall -k "$(uname -r)" 2>/dev/null || run dkms autoinstall 2>/dev/null || true
  modprobe amneziawg 2>/dev/null && return 0
  run apt-get install --reinstall -y amneziawg-dkms 2>/dev/null || true
  run dkms autoinstall -k "$(uname -r)" 2>/dev/null || true
  run modprobe amneziawg 2>/dev/null || true
}
ensure_smart_tools(){ # nftables (smart-routing marking) + dnsmasq (domain-tier set filling) — idempotent, non-fatal
  have nft     || { run apt-get update -qq || true; run apt-get install -y nftables || true; }
  have dnsmasq || { run apt-get update -qq || true; run apt-get install -y dnsmasq  || true; }
  have ipset   || { run apt-get update -qq || true; run apt-get install -y ipset    || true; }   # kernel-SNI mode (xt_string learn → ipset); degrades to userspace SNI if absent
  # the node runs its OWN dnsmasq on loopback:5354 via swg-noded; keep the distro service from ever grabbing :53.
  # mask (not just disable) so an apt postinst can't restart it, and reset-failed so a prior boot's :53 conflict
  # (systemd-resolved already holds :53) doesn't linger in `systemctl --failed` after a reinstall.
  run systemctl disable --now dnsmasq 2>/dev/null || true
  run systemctl mask dnsmasq 2>/dev/null || true
  run systemctl reset-failed dnsmasq 2>/dev/null || true
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
  printf 'I1 = <b 0xc000000001><r 64><t>\nI2 = <r 24><t>\nI3 = <r 32>\nI4 = <b 0xc000000001><r 32><t>\nI5 = <t><r 48>\n'   # I1-I5: QUIC-Initial-shaped junk (0xc0 long header, QUIC v1) + random bytes + timestamp
}
server_addr(){ have python3 || die "python3 required for the tunnel address (also needed by the daemon)"
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
v_subnet_free(){ v_subnet "$1" || return 1; subnet_used "$1" && return 1; return 0; }
# default interface index = (highest numeric suffix across existing + queued names)+1 (awg3,wg4 → 5).
# warn if any two managed interfaces share a tunnel subnet — only ONE can be up at a time (the rest fail to
# start), so the node will report some interfaces down until the operator edits one to a free subnet.
# Two-phase interface creation: spec_iface() only PROMPTS and queues a spec, so the user can add
# every interface up front; apply_specs() then installs tools + writes confs + brings them all up
# once, at the end. Queued names show in 'mine' (via CREATED) and block name collisions immediately.
apply_specs(){ # install tools + write confs + bring up every queued interface, then prune failures
  [ "${#SPEC_ORDER[@]}" -gt 0 ] || return 0
  local name proto port subnet addr conf cmd priv dir wan up down upok ep failed=""
  echo; info "Setting up ${#SPEC_ORDER[@]} interface(s)…"
  for name in "${SPEC_ORDER[@]}"; do
    cmd="${SPEC_CMD[$name]}"; proto="${SPEC_PROTO[$name]}"; port="${SPEC_PORT[$name]}"; subnet="${SPEC_SUBNET[$name]}"
    addr="${SPEC_ADDR[$name]}"; wan="${SPEC_WAN[$name]}"; ep="${SPEC_EP[$name]}"; dir="${SPEC_DIR[$name]}"; conf="$dir/$name.conf"
    if ! ensure_wg_tools "$cmd"; then warn "couldn't install $cmd tools — skipping interface '$name'"; failed="$failed $name"; continue; fi
    up="sysctl -q -w net.ipv4.ip_forward=1; iptables -t nat -A POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -A FORWARD -i %i -o ${wan} -j ACCEPT; iptables -A FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
    down="iptables -t nat -D POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -D FORWARD -i %i -o ${wan} -j ACCEPT; iptables -D FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
    printf 'net.ipv4.ip_forward = 1\nnet.ipv4.conf.all.route_localnet = 1\n' | writef /etc/sysctl.d/99-swg-forward.conf 644
    run sysctl -q -w net.ipv4.ip_forward=1
    run sysctl -q -w net.ipv4.conf.all.route_localnet=1   # lets Force-DNS DNAT client :53 to loopback dnsmasq (else silent DNS blackhole)
    if $DRYRUN; then priv="<generated-on-real-run>"
    elif ! priv="$("$cmd" genkey 2>/dev/null)" || [ -z "$priv" ]; then warn "'$cmd genkey' failed — skipping interface '$name'"; failed="$failed $name"; continue; fi
    { printf '[Interface]\nPrivateKey = %s\nAddress = %s\nListenPort = %s\nMTU = %s\n' "$priv" "$addr" "$port" "$WG_MTU"
      printf 'PostUp = %s\nPostDown = %s\n' "$up" "$down"
      if [ "$cmd" = awg ]; then awg_obfuscation; fi; } | writef "$conf" 600
    # drop a STALE live interface of the same name first — a removed docker node that ran on the host netns
    # leaves its awg/wg interfaces on the host ('docker rm' can't take them down), which would block this
    # fresh bring-up with "already exists". We hold a brand-new conf, so replacing it is safe.
    if ! $DRYRUN && ip link show "$name" >/dev/null 2>&1; then
      warn "interface '$name' already exists as a leftover (e.g. a removed docker node left its host-netns iface) — replacing it with the new one"
      awg-quick down "$name" >/dev/null 2>&1 || wg-quick down "$name" >/dev/null 2>&1 || true   # clean teardown if it can
      ip link delete dev "$name" >/dev/null 2>&1 || true                                        # ALWAYS force-delete the netdev (down may exit 0 without removing it)
    fi
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
# ── interface picker helpers (bare-metal) ──
node_ifaces(){ # interfaces this node already manages — config.json keys WHOSE CONF STILL EXISTS. A dangling entry
  # (conf file gone, no live device — e.g. a docker host-net interface orphaned by teardown) is a GHOST: skip it
  # so it's never shown as "already on this node" and re-adopted with blank fields (which then re-writes the ghost).
  { [ -f /etc/swg-agent/config.json ] && have python3; } || return 0
  python3 -c 'import json, os
for n, ic in (json.load(open("/etc/swg-agent/config.json")).get("interfaces") or {}).items():
    if isinstance(ic, dict) and os.path.exists(ic.get("conf", "")): print(n)' 2>/dev/null | drop_sys_ifaces || true
}
_in(){ case " $2 " in *" $1 "*) return 0;; *) return 1;; esac; }
# A LIVE wg/awg interface with NO conf on disk is invisible to the conf-based scan below (e.g. a removed docker
# node ran on the host netns and left its interface behind). Rebuild its conf from the live state — key, port,
# Amnezia params, peers (awg/wg showconf) + Address (ip addr) + host NAT — so it's DETECTED and adopted (peers
# kept), not silently colliding with a freshly-created same-named interface. Marked #swg:onboarded (add-only).
reconstruct_live_orphans(){
  $DRYRUN && return 0
  command -v ip >/dev/null 2>&1 || return 0
  local tool dir n sc addr sub wan up down _allow=""
  # SCOPE IT. During a CONVERT we know exactly which interfaces are ours — convert.sh passes them in
  # ADOPTED_IFACES — so reconstruct only those. Anything else running on this box is the operator's, and
  # Approach B is explicit that an unmanaged interface is REPORTED as an adoption candidate, never taken over.
  # Unscoped, a plain `ip link add wg0 type wireguard` on the host was rebuilt into /etc/wireguard/wg0.conf,
  # marked #swg:onboarded, listed in the summary as "managed", and would then be deleted by a later uninstall
  # (which removes /etc/wireguard/*.conf). The bare->docker direction had ALREADY reported that same interface
  # correctly as an adoption candidate, so only this path was claiming it.
  # …and OUTSIDE a convert there is no such list, because there is nothing to build one FROM: a fresh install
  # is meeting this box for the first time. Rebuilding then claims whatever happens to be up — the operator's
  # own wg server, a WARP/wgcf tunnel, WDTT-Plus's `wg-wdtt-exit`, a corporate VPN — writes it a conf marked
  # #swg:onboarded, and hands the panel a Delete button for the box's own egress. Measured: a node installed
  # on a box carrying four CLIENT tunnels adopted all four, pinning each one's EPHEMERAL source port into the
  # conf as if it were a server ListenPort. The scope test below was already written for this; it was simply
  # never armed on the path that needs it most, because the bug it was written for was found during a convert.
  # The case this function exists for is covered better elsewhere now: swg-noded's self-heal re-adopts a live
  # interface THE PANEL OWNS whose conf is gone (`owned_ifaces`) — the same repair, made with the panel's
  # authority instead of a guess. So a convert reconstructs exactly what it is migrating, and nothing else
  # reconstructs anything.
  [ "${SWG_CONVERT:-}" = 1 ] || return 0
  _allow=" $(printf '%s' "${ADOPTED_IFACES:-}" | tr ', ' '  ') "
  wan="$(ip route show default 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}' || true)"; [ -n "$wan" ] || wan=eth0
  for tool in awg wg; do
    command -v "$tool" >/dev/null 2>&1 || continue
    dir=/etc/amnezia/amneziawg; [ "$tool" = wg ] && dir=/etc/wireguard
    for n in $("$tool" show interfaces 2>/dev/null || true); do
      [ -n "$n" ] || continue
      if [ -f "/etc/amnezia/amneziawg/$n.conf" ] || [ -f "/etc/wireguard/$n.conf" ]; then continue; fi   # already managed
      _in "$n" "$_allow" || continue   # not one of the interfaces THIS convert is migrating → leave it for the panel to offer as a candidate
      sc="$("$tool" showconf "$n" 2>/dev/null || true)"; [ -n "$sc" ] || continue
      addr="$(ip -o -4 addr show "$n" 2>/dev/null | awk '{print $4; exit}' || true)"; [ -n "$addr" ] || continue
      sub="$(printf '%s' "${addr%/*}" | awk -F. '{print $1"."$2"."$3".0"}' || true)/${addr#*/}"
      up="sysctl -q -w net.ipv4.ip_forward=1; iptables -t nat -A POSTROUTING -s ${sub} -o ${wan} -j MASQUERADE; iptables -A FORWARD -i %i -o ${wan} -j ACCEPT; iptables -A FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
      down="iptables -t nat -D POSTROUTING -s ${sub} -o ${wan} -j MASQUERADE; iptables -D FORWARD -i %i -o ${wan} -j ACCEPT; iptables -D FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
      mkdir -p "$dir" 2>/dev/null || true
      # `showconf` reports each peer's CURRENT endpoint — the source address of its last packet, not
      # configuration. Persisting it would pin a client's IP into a file that backups and the bare<->docker
      # conversion copy around, and wg re-learns it on the first authenticated packet anyway. A peer that
      # also sets PersistentKeepalive is a dial-OUT (mesh) peer: there the Endpoint IS config, so it stays.
      { echo '#swg:onboarded'; printf '%s\n' "$sc" | awk -v a="$addr" -v u="$up" -v d="$down" '
        function flush(  i) { if (np == 0) return
          for (i = 1; i <= np; i++) if (ka || peer[i] !~ /^[ \t]*[Ee]ndpoint[ \t]*=/) print peer[i]
          np = 0; ka = 0 }
        /^[ \t]*\[Interface\]/ { flush(); print; print "Address = " a; print "MTU = 1420"; print "PostUp = " u; print "PostDown = " d; next }
        /^[ \t]*\[Peer\]/      { flush(); peer[++np] = $0; next }
        np > 0                  { peer[++np] = $0; if ($0 ~ /^[ \t]*[Pp]ersistentKeepalive[ \t]*=/) ka = 1; next }
                                { print }
        END                     { flush() }'; } > "$dir/$n.conf" 2>/dev/null && chmod 600 "$dir/$n.conf" 2>/dev/null || true
      info "  detected running interface $(b "$n") with no config on disk — rebuilt its conf so it's managed (peers kept)"
    done
  done
  return 0
}
choose_ifaces(){ # let the user pick which detected interfaces to manage; 'new' creates more
  reconstruct_live_orphans   # rebuild confs for running wg/awg ifaces that have none on disk → detected below
  migrate_docker_ifaces      # docker→bare convert: list the migrated interfaces + "Transfer? (Y/n)"; declined ⇒ drop them (must run AFTER reconstruct, before detect_wg, so a drop sticks)
  detect_wg
  if [ -n "$MANAGE_IFACES" ]; then
    IFS=',' read -ra SELECTED <<< "$MANAGE_IFACES"
  elif [ -n "${ADOPTED_IFACES:-}" ]; then
    # convert: carry the interfaces the convert migrated (the already-MANAGED set) — no re-decision.
    IFS=', ' read -ra SELECTED <<< "$ADOPTED_IFACES"
    # add-only mark for any that arrived without a marker (keep their peers)
    local n _nodeifs; _nodeifs="$(node_ifaces | tr '\n' ' ')"
    for n in ${SELECTED[@]+"${SELECTED[@]}"}; do n="${n// /}"; [ -z "$n" ] && continue
      _in "$n" "$_nodeifs" && continue
      _in "$n" "${CREATED[*]:-}" && continue
      onboard_mark "$n"
    done
  else
    # Approach B (record-only): no picker, no auto-adopt. Detect the wg/awg interfaces already on this box and just
    # DISPLAY them — the node reports them to the panel, where they appear as adoption candidates for the operator to
    # classify (WG / AWG / WDTT) or ignore. Nothing is touched here; new interfaces are created from the panel.
    local n _mine; local -a cand=()
    _mine=" $(local_ifaces | tr '\n' ' ') "
    for n in "${!IF_CMD[@]}"; do
      is_sys_iface "$n" && continue
      case "$_mine" in *" $n "*) continue;; esac   # already managed by this node → local, not a candidate
      cand+=("$n")
    done
    if [ "${#cand[@]}" -gt 0 ]; then
      echo; info "Found ${#cand[@]} wg/awg/wdtt interface(s) NOT managed by the panel — adopt them from the panel (Node → Interfaces → adoption candidates):"; echo
      for n in "${cand[@]}"; do iface_row "$n"; done; echo
    else
      info "No unmanaged wg/awg/wdtt interfaces found on this box — nothing to adopt."
    fi
    # Record-only means DON'T ADOPT STRANGERS — not "forget what this node already manages". Emptying SELECTED
    # here made config.json's "interfaces" {} on every re-install: the interfaces stayed up on the kernel but
    # unmanaged, so every peer on the node went dangling until each one was re-adopted from the panel by hand.
    SELECTED=(); while IFS= read -r n; do [ -n "$n" ] && SELECTED+=("$n"); done < <(node_ifaces)
  fi
  # the CUTOVER + bringing every interface up is DEFERRED for a docker→bare convert: the turn-proxy step
  # (Step 2) still has to run while the docker node serves, so the convert path calls apply_node_switch
  # itself AFTER Step 2. A fresh install has nothing to tear down, so it switches right here.
  [ "${SWG_CONVERT:-}" = 1 ] || apply_node_switch
}
# the ATOMIC SWITCH: stop the docker datapath (convert only — a no-op on a fresh install) + clear leftover host
# netdevs so wg-quick can bind, then bring every selected interface up. The conf/key COPY already happened
# (convert.sh), so this is the only destructive step — run as the very last thing before the daemon starts.
apply_node_switch(){
  local _n _ep n _c
  if [ "${SWG_CONVERT:-}" = 1 ] && ! $DRYRUN && command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-node; then
    info "Switching over — stopping the docker node, then bringing the interfaces up bare-metal…"
    lc_teardown_docker "${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"
    for _n in ${SELECTED[@]+"${SELECTED[@]}"}; do _n="${_n// /}"; [ -n "$_n" ] && command -v ip >/dev/null 2>&1 && ip link show "$_n" >/dev/null 2>&1 && ip link delete dev "$_n" 2>/dev/null || true; done
  fi
  apply_specs   # install tools + write confs + bring up every queued interface now (after all prompts)
  detect_wg
  for n in "${SELECTED[@]}"; do n="${n// /}"; [ -n "${IF_CMD[$n]:-}" ] || { [ -e "/etc/amnezia/amneziawg/$n.conf" ] && { IF_CMD[$n]=awg; IF_CONF[$n]="/etc/amnezia/amneziawg/$n.conf"; } || { IF_CMD[$n]=wg; IF_CONF[$n]="/etc/wireguard/$n.conf"; }; }
    [ -n "${IF_ENDPOINT[$n]:-}" ] && continue   # interfaces just created already have an endpoint
    _ep="$(detect_public_ip)"; IF_ENDPOINT[$n]="$_ep"   # auto endpoint clients dial (change it later in the panel)
    echo "    Used $(bb "$_ep") endpoint IP for $(col "$C_GREEN" "$n")"; done
  [ "${#SELECTED[@]}" -gt 0 ] && echo
  # bring up any adopted interface whose conf is here but isn't running yet (transfer-from-docker / conversion)
  info "Bringing up the node's interfaces (starting each one — this can take a moment for many)…"
  for n in "${SELECTED[@]}"; do n="${n// /}"; [ -z "$n" ] && continue
    ip link show "$n" >/dev/null 2>&1 && continue          # already up → leave it
    _c="${IF_CMD[$n]:-awg}"; ensure_wg_tools "$_c" || continue
    if [ "$_c" = awg ]; then bringup awg-quick "$n" && { run systemctl enable --quiet "awg-quick@$n" || true; } || warn "couldn't bring up adopted '$n' — check $(b "${IF_CONF[$n]:-}")"
    else                     bringup wg-quick  "$n" && { run systemctl enable --quiet "wg-quick@$n"  || true; } || warn "couldn't bring up adopted '$n' — check $(b "${IF_CONF[$n]:-}")"; fi
  done
  # The LOCAL set — what this node manages after this run: wg/awg from config.json + its WDTT instances (whose
  # interfaces have no .conf, so they'd otherwise look absent). Listed, not re-asked: a re-install keeps them.
  local _l _li _lls _lsub; local -a _loc=()
  while IFS= read -r _l; do [ -n "$_l" ] && _loc+=("$_l"); done < <(local_ifaces)
  if [ "${#_loc[@]}" -gt 0 ]; then
    echo; info "Found ${#_loc[@]} wg/awg/wdtt local interface(s) on this box:"; echo
    detect_wg
    for _l in "${_loc[@]}"; do
      if [ -n "${IF_CMD[$_l]:-}" ]; then iface_row "$_l"; else
        IFS="$(printf '\t')" read -r _li _lls _lsub < <(wdtt_local | awk -F'\t' -v i="$_l" '$1==i') || true   # EOF => rc 1; set -e would abort the whole install
        [ -n "$_li" ] && wdtt_row "$_li" "$_lls" "$_lsub"
      fi
    done; echo
  else info "No local interfaces yet — this node is managed from the panel (Interfaces → Load new interface)."; fi
  [ "${#SELECTED[@]}" -gt 0 ] && ok "Managing: $(b "$(col "$C_GREEN" "${SELECTED[*]}")")" || true
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
gen_wrap_key(){ $DRYRUN && { echo "GENERATED-ON-REAL-RUN"; return 0; }   # 32-byte key as 64 hex chars
  openssl rand -hex 32 2>/dev/null || head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
# Per-fork obfuscation flags (verified from each binary's -h). Echoes the flags WITH a freshly generated
# 64-hex key baked in (kiper292 has no obfuscation → empty). samosvalishe is now the free-turn-proxy server
# (the standalone vk-turn-proxy is archived): it uses -obf-profile rtpopus + -obf-key, and its clients
# (turn-proxy-android / free-turn-proxy CLI) import a freeturn:// link carrying the same rtpopus key.
turn_wrap_flags(){ local k; case "$1" in
  anton48)      k="$(gen_wrap_key)"; printf -- '-wrap-srtp -wrap-key %s' "$k";;
  samosvalishe) k="$(gen_wrap_key)"; printf -- '-obf-profile rtpopus -obf-key %s' "$k";;
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
        wk="$(printf '%s\n' "$params" | sed -n 's/.*-wrap-key[ =]\{1,\}\([^ ]*\).*/\1/p')"
        [ -n "$wk" ] || wk="$(printf '%s\n' "$params" | sed -n 's/.*-obf-key[ =]\{1,\}\([^ ]*\).*/\1/p')" ;;   # free-turn-proxy uses -obf-key
      *)            # legacy baked-ExecStart form
        lis="$(printf '%s\n' "$exe" | sed -n 's/.*-listen[ =]\{1,\}\([^ ]*\).*/\1/p')"
        con="$(printf '%s\n' "$exe" | sed -n 's/.*-connect[ =]\{1,\}\([^ ]*\).*/\1/p')"
        wk="$(printf '%s\n' "$exe" | sed -n 's/.*-wrap-key[ =]\{1,\}\([^ ]*\).*/\1/p')"
        [ -n "$wk" ] || wk="$(printf '%s\n' "$exe" | sed -n 's/.*-obf-key[ =]\{1,\}\([^ ]*\).*/\1/p')" ;;
    esac
    TP_LISTEN[$name]="$lis"; TP_CONNECT[$name]="$con"; TP_WRAP[$name]="$wk"
  done
}
turn_latest_tag(){ $DRYRUN && { echo "v0.0.0"; return 0; }   # turn_latest_tag <owner/repo>
  curl -fsSL --connect-timeout 10 --max-time 20 "https://api.github.com/repos/$1/releases/latest" 2>/dev/null \
    | python3 -c 'import sys,json;print(json.load(sys.stdin).get("tag_name",""))' 2>/dev/null || true; }
install_turn_binary(){ # <fork> <owner/repo> <listen ip:port> <connect ip:port> <extra-flags>
  local fork="$1" owner="$2" listen="$3" connect="$4" extra="$5" arch dir bin svc url ver port inst fdir sbin
  case "$(uname -m)" in x86_64|amd64) arch=amd64;; aarch64|arm64) arch=arm64;; *) arch="";; esac
  # detect-and-REFUSE: the forks publish server-linux-amd64/arm64 only. Never fall back to amd64 on an unknown arch —
  # that fetched a wrong x86-64 binary → 404 / "Exec format error". Skip the turn-proxy with a clear message instead.
  [ -n "$arch" ] || { warn "no turn-proxy build for $(uname -m) — forks publish amd64/arm64 only; skipping this turn-proxy"; return 0; }
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
  printf '%s\n' "$owner"          | writef "$fdir/repo.txt" 644
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
$TURN_HARDENING

[Install]
WantedBy=multi-user.target
EOF
  run systemctl daemon-reload
  if [ -n "${TURN_DEFER_START:-}" ]; then   # docker→bare convert: the docker turn-proxy still holds the port → enable now, start at the switch
    run systemctl enable --quiet "$svc" || true
    ok "prepared turn-proxy $(col "$C_GREEN" "$inst") ($owner ${ver:-?}) — $listen → $connect (starts at the switch)"
  else
    run systemctl enable --quiet --now "$svc" || warn "couldn't start $svc"
    ok "installed turn-proxy $(col "$C_GREEN" "$inst") ($owner ${ver:-?}) — $listen → $connect"
  fi
}
# docker→bare convert: recreate the docker node's turn-proxies as bare systemd units (deferred — started at the
# switch), as the FIRST thing in Step 2 (so it reads interfaces-then-turns); the fork menu below then adds more.
migrate_docker_turns(){
  [ "${SWG_CONVERT:-}" = 1 ] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  local rec="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}/data/node/turn-proxy.json" list svc owner lis con params fork _yn
  if [ ! -f "$rec" ] && command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx swg-node; then
    mkdir -p "$(dirname "$rec")"; docker cp swg-node:/var/lib/swg-noded/turn-proxy.json "$rec" 2>/dev/null || true   # robust vs an empty ./data bind mount
  fi
  [ -f "$rec" ] || return 0
  list="$(python3 - "$rec" <<'PY' 2>/dev/null
import json, sys
try: d=json.load(open(sys.argv[1])); tps=d.get("turn_proxies") or []
except Exception: tps=[]
for t in (tps if isinstance(tps,list) else []):
    if t.get("service"): print("\t".join([t.get("service",""), t.get("owner",""), t.get("listen",""), t.get("connect",""), (t.get("params") or "")]))
PY
)"
  [ -n "$list" ] || return 0
  echo; info "Turn-proxies to migrate from the docker node:"; echo
  while IFS="$(printf '\t')" read -r svc owner lis con params; do [ -n "$svc" ] && printf '    %s%s%s  %s → %s\n' "$C_GREEN" "$svc" "$RESET" "${lis:-?}" "${con:-?}"; done <<EOF
$list
EOF
  echo
  # Approach B: auto-carry — always migrate the existing turn-proxies (no prompt). New ones are created from the panel.
  while IFS="$(printf '\t')" read -r svc owner lis con params; do
    [ -n "$svc" ] && [ -n "$owner" ] || continue
    fork="${svc#vk-turn-proxy-}"; fork="${fork%-*}"
    TURN_DEFER_START=1 install_turn_binary "$fork" "$owner" "$lis" "$con" "$params"
  done <<EOF
$list
EOF
}
# docker→bare convert: the docker node's interfaces were imported to the bare conf dirs (host NAT added) by
# convert.sh's node phase. The mirror of migrate_docker_turns + bare→docker's migrate_baremetal_ifaces: list them,
# ask "Transfer? (Y/n)"; declined ⇒ drop the confs so detect_wg finds none (node starts empty / add fresh in loop).
migrate_docker_ifaces(){
  [ "${SWG_CONVERT:-}" = 1 ] || return 0
  local ifs n c pr lp addr _yn _mep
  ifs="$(for c in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf; do [ -f "$c" ] && basename "$c" .conf; done 2>/dev/null | sort -u || true)" || true; ifs="$(echo $ifs)"
  [ -n "$ifs" ] || return 0
  echo; info "Interfaces to migrate from the docker node:"; echo
  _mep="${ENDPOINT_IP:-}"; case "$_mep" in 127.*|"") _mep="$(detect_public_ip 2>/dev/null || true)";; esac   # public endpoint clients dial (this box) — show it like the node's own interface list
  for n in $ifs; do c="/etc/amnezia/amneziawg/$n.conf"; pr=AmneziaWG; [ -f "$c" ] || { c="/etc/wireguard/$n.conf"; pr=WireGuard; }
    lp="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$c" | head -1)"
    addr="$(sed -n 's/^[[:space:]]*Address[[:space:]]*=[[:space:]]*\([0-9./]*\).*/\1/p' "$c" | head -1)"
    printf '    %s%-10s%s %-9s  %s:%-6s %s\n' "$C_GREEN" "$n" "$RESET" "$pr" "${_mep:-?}" "${lp:-?}" "${addr:-?}"; done
  echo
  # Approach B: auto-carry — always keep the migrated interface confs (no prompt). They're adopted below and
  # surface in the panel; new interfaces are created there.
  echo
}
# turn-proxy forward-to value: accept an interface NAME (resolved to 127.0.0.1:<its listen port>) or a custom ip:port.
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

[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
# Fail early on a too-old interpreter: swg-noded/swg-agent use 3.7 syntax, so a too-old python3 would otherwise
# surface as an opaque SyntaxError only when the daemon starts. (Bash guard — an in-file check can't catch a
# parse-time failure.) Node floor is 3.7 (the panel needs 3.8; a pure node doesn't).
$DRYRUN || { have python3 || die "python3 (>= 3.7) is required — install it with your package manager, then re-run"; \
  python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 7) else 1)' \
    || die "this box's python3 ($(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo '?')) is too old — swg-noded needs Python >= 3.7; install a newer python3 and re-run"; }
$DRYRUN && { info "DRY RUN — files render under ./dryrun, nothing executes."; rm -rf "$PREFIX"; }

# ⚠️ THIS BOX ALREADY RUNS THE DOCKER NODE. Every docker-aware branch in this script is gated on
# SWG_CONVERT=1, which only convert.sh sets — so run bare-metal by hand on a box whose `swg-node`
# container is up and nothing here notices. The result is two daemons holding the SAME token and node
# id, both reconciling the same desired state through different run models: one inside the container's
# netns against its volume, one on the host. They fight over the interfaces, and the panel's `kind`
# flips with whichever snapshot arrived last, because it adopts the run model the node reports.
#
# bootstrap.sh ALREADY guards this: reaching it through the panel's own command finds the other method
# installed and offers convert / keep / abort. This is the same guard one layer down, for the path that
# skips it — anything invoking install-node.sh directly, which includes every hand-rolled installer built
# from this repo. A refusal rather than a warning: there is no reading of "install the other run model
# beside the one already running" that is what the operator meant. FORCE_ALONGSIDE exists for the one
# case a rule cannot judge: a container that is somebody else's, or is on its way out.
if [ "${SWG_CONVERT:-}" != 1 ] && [ "${FORCE_ALONGSIDE:-}" != 1 ] && ! $DRYRUN \
     && command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx swg-node; then
  die "this box already runs the swg-node CONTAINER, and a bare-metal install beside it would leave two
     daemons syncing the same node id and fighting over the same interfaces.

     Run the panel's command through bootstrap.sh instead of calling this script directly: it detects the
     docker install and offers to CONVERT it (settings, users and peers preserved) or to re-install it as
     docker — which is the choice this script, on its own, cannot offer.

     To install a NODE here anyway (the container is somebody else's, or is on its way out), re-run with
     FORCE_ALONGSIDE=1."
fi

# convert.sh (docker→bare) re-enters here AFTER migrating the existing turn-proxies, to offer the same
# "add more?" step interfaces get — reusing this script's turn menu instead of duplicating the fork list
# in convert.sh. choose_turn_proxy lists what's already installed (incl. the just-migrated units), lets
# you add more, and (re)writes the turn record; restart swg-noded so any additions reach the panel.
if [ "${SWG_TURN_ADD:-}" = 1 ]; then
  # Approach B: turn-proxies are managed from the PANEL — no "add more" menu here. convert.sh has already carried the
  # existing turn-proxies; just (re)write the record and restart the daemon so the panel sees the carried set.
  write_turn_record
  run systemctl restart swg-noded || warn "couldn't restart swg-noded — carried turn-proxies reach the panel on its next start"
  exit 0
fi

# ═══════════════ NODE SETUP ═══════════════
echo; info "BARE-METAL SWG NODE SETUP"
read_existing
if [ "$EXISTING" = yes ]; then
  info "Existing node install detected — keeping your interfaces + data. Press $(b Enter) to keep each value (to start fresh, run the uninstaller first)."
fi

# RE-INSTALL: signal "re-installing" the MOMENT the script starts (before any prompt), using the stored panel
# URL/token, and drop the keypair backups so swg-noded re-harvests. lc_init's traps emit the terminal on exit;
# a re-install always installs the latest → "re-installed and updated". (convert.sh owns the signal mid-convert.)
if [ "$EXISTING" = yes ] && ! $DRYRUN && [ "${SWG_CONVERT:-}" != 1 ] && [ -n "$EXIST_URL" ] && [ -n "$EXIST_TOKEN" ]; then
  rm -rf /var/lib/swg-noded/iface-keys 2>/dev/null || true
  LC_URL="$EXIST_URL"; LC_TOKEN="$EXIST_TOKEN"
  LC_VERIFY="$(python3 -c 'import json;print("yes" if (json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("verify",True) else "no")' 2>/dev/null || echo no)"
  lc_init reinstall lc_emit_post
  LC_SUCCESS="reinstalled-updated"
fi

# Panel connection — normally supplied by the install command's -host / -key flags; on a re-install
# the current values are offered as defaults so you can just press Enter.
if $DRYRUN; then ask "Panel URL (https://host[/subpath])" "$EXIST_URL" PANEL_URL
else ask_valid "Panel URL (https://host[/subpath])" "$EXIST_URL" PANEL_URL v_httpsurl "enter the panel's https:// URL (pass -host to skip this)"; fi
# token: a re-install reuses the existing one SILENTLY (no prompt — re-typing it is useless/error-prone);
# a fresh install (or no stored token) still asks. -key always wins.
if [ -n "$NODE_TOKEN" ]; then :                                                # provided via -key
elif [ "$EXISTING" = yes ] && [ -n "$EXIST_TOKEN" ]; then NODE_TOKEN="$EXIST_TOKEN"
elif $DRYRUN; then ask "Node enrollment key (from the Nodes screen)" "$EXIST_TOKEN" NODE_TOKEN
else ask_secret "Node enrollment key (from the Nodes screen)" "$EXIST_TOKEN" NODE_TOKEN v_token "paste the key from Nodes → Add node (pass -key to skip this)"; fi
case "$PANEL_URL" in https://*) ;; http://*) _url_is_loopback "$PANEL_URL" || warn "panel URL is http:// — the key would travel in clear. Continue only if you know why.";; *) PANEL_URL="https://$PANEL_URL";; esac   # no scheme → default https://
# if the operator re-pointed the node at a different panel, the lc terminal should reach the NEW one
[ "$EXISTING" = yes ] && [ -n "${LC_TOKEN:-}" ] && [ -n "$PANEL_URL" ] && LC_URL="$PANEL_URL"

# print the sha256 hex of the panel's TLS cert (unverified fetch), or nothing on failure. Matches the node's
# `fingerprint` format: hashlib.sha256(DER).hexdigest(), lowercase, no colons.
_panel_fp(){ python3 - "$1" <<'PY' 2>/dev/null || true
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

if [ -z "$TLS_VERIFY" ] && [ -z "$TLS_FINGERPRINT" ]; then
  # Verify the panel's TLS certificate by DEFAULT (secure). To avoid a fresh install failing its first sync
  # against a self-signed panel, auto-detect the cert: probe once with strict TLS; only if that fails while
  # skipping verification works is the panel self-signed. The operator can still override.
  _tls_def=y
  if [ -n "$PANEL_URL" ] && ! $DRYRUN; then
    _rc=0; curl -sS --max-time 6 -o /dev/null "${PANEL_URL%/}/healthz" 2>/dev/null || _rc=$?   # capture rc WITHOUT letting set -e abort — a self-signed/unreachable panel (the case this block exists for) makes curl exit non-zero
    # Only a genuine cert-verification failure (curl 60/51) — where skipping verify then works — means the
    # panel is self-signed. A transient error (timeout/refused/other) keeps the SECURE default (CA verify), so
    # a network hiccup never silently downgrades a real-CA panel.
    if { [ "$_rc" = 60 ] || [ "$_rc" = 51 ]; } && curl -sSk --max-time 6 -o /dev/null "${PANEL_URL%/}/healthz" 2>/dev/null; then
      _tls_def=n
    fi
  fi
  # SELF-SIGNED panel → PIN its certificate (trust-on-first-use) so the sync is MITM-protected by default,
  # instead of running unverified. Real-CA panels keep CA verification (pinning them would break on renewal).
  if [ "$_tls_def" = n ] && [ -n "$PANEL_URL" ] && ! $DRYRUN; then
    _fp="$(_panel_fp "$PANEL_URL")"
    if [ -n "$_fp" ]; then
      TLS_FINGERPRINT="$_fp"; TLS_VERIFY=no
      info "Panel cert is self-signed — pinning it (sha256 ${_fp:0:16}…) so a man-in-the-middle can't impersonate the panel."
    fi
  fi
  # real-CA (or the fingerprint fetch failed) → ask, defaulting to the secure choice
  if [ -z "$TLS_FINGERPRINT" ]; then
    ask_yn "Verify the panel's TLS certificate? (auto-detected default: $([ "$_tls_def" = y ] && echo yes || echo 'no — self-signed'))" "$_tls_def" TLS_VERIFY
  fi
fi

NODE_NAME="${NODE_NAME:-$(hostname -s 2>/dev/null || hostname)}"   # local label (systemd unit + final message)
# Box name on the panel: on a re-install, offer to change it (default = the name the panel currently has for
# this token). A fresh install's name comes from Nodes → Add node. PUSH_NAME != "" means push the change.
PUSH_NAME=""
if { [ "$EXISTING" = yes ] || [ "${SWG_CONVERT:-}" = 1 ]; } && [ -n "$NODE_TOKEN" ] && [ -n "$PANEL_URL" ] && ! $DRYRUN; then
  _ins=""; [ "${TLS_VERIFY:-no}" = yes ] || _ins="-k"
  _cur="$(auth_curl "$NODE_TOKEN" -fsS $_ins --max-time 8 "${PANEL_URL%/}/api/node/whoami" 2>/dev/null | python3 -c 'import json,sys;print((json.load(sys.stdin).get("data") or {}).get("name") or "")' 2>/dev/null || true)"
  step "Node name for THIS box"
  ask_valid "Node name for THIS box" "${_cur:-$NODE_NAME}" PUSH_NAME v_name "1–40 chars: letters, digits, - or _"
  [ -n "$_cur" ] && [ "$PUSH_NAME" = "$_cur" ] && PUSH_NAME=""    # unchanged → nothing to push
fi

# push a box-name change (if the operator entered a new one above)
if { [ "$EXISTING" = yes ] || [ "${SWG_CONVERT:-}" = 1 ]; } && ! $DRYRUN && [ -n "$PUSH_NAME" ]; then
  auth_curl "$NODE_TOKEN" -fsS ${_ins:-} --max-time 8 -X POST -H "Content-Type: application/json" \
    --data "$(python3 -c 'import json,sys;print(json.dumps({"name":sys.argv[1]}))' "$PUSH_NAME")" "${PANEL_URL%/}/api/node/rename" >/dev/null 2>&1 || true
fi

step "Datapath tooling"
echo
# Approach B: no create prompts. Interfaces / turn-proxies / WDTT are created FROM THE PANEL. Install the datapath
# tooling, then auto-adopt any interfaces already on this box (choose_ifaces, add-only) + carry any turn-proxies a
# convert migrated (auto). The panel's Orphans screen classifies each interface (WG / AWG / WDTT) or leaves it
# unmanaged; new ones are created there.
ensure_smart_tools || true            # nftables (smart routing) + dnsmasq (Force-DNS host tier)
ensure_wg_tools awg || true           # AmneziaWG tools + DKMS kernel module (default interface type)
ensure_wg_tools wg  || true           # plain WireGuard tools too — either type works when created later
choose_ifaces                         # detect + display + auto-adopt everything found (convert: incl. migrated confs)
migrate_docker_turns                  # docker→bare convert: carry existing turn-proxies (auto, no prompt)
write_turn_record                     # record carried turns for the panel (fresh install: writes an empty set)

# CONVERT: the turn-proxy step is done → NOW do the deferred cutover as the very last step (mirror bare→docker):
# stop the docker datapath (+ its turn containers) → bring the bare interfaces up → start the migrated turn
# units (their ports are free now). The node goes down + comes back ONCE, fully converted; the daemon (below)
# is its first report, already carrying interfaces + turn-proxies.
if [ "${SWG_CONVERT:-}" = 1 ]; then
  apply_node_switch
  for _u in /etc/systemd/system/vk-turn-proxy-*.service; do [ -e "$_u" ] || continue; run systemctl enable --now "$(basename "$_u")" || true; done
fi

# ───────────────────────── install binaries ─────────────────────────
info "Agent + daemon"
for f in swg-agent swg-noded; do [ -f "$SRC/$f" ] || die "missing $f beside this script (unzip the bundle here)"; done
mkdir -p "$PREFIX$AGENT_DIR" "$PREFIX$NODED_DIR"; cp "$SRC/swg-agent" "$PREFIX$AGENT_DIR/"; cp "$SRC/swg-noded" "$PREFIX$NODED_DIR/"
[ -f "$SRC/swg-sni" ] && { cp "$SRC/swg-sni" "$PREFIX$NODED_DIR/"; chmod 755 "$PREFIX$NODED_DIR/swg-sni"; }   # SNI-router classifier (routing_mode=sni)
chmod 755 "$PREFIX$AGENT_DIR/swg-agent" "$PREFIX$NODED_DIR/swg-noded"; ok "installed agent + daemon"
[ -f "$SRC/VERSION" ] && cp "$SRC/VERSION" "$PREFIX$NODED_DIR/" || true   # version stamp (update.sh reports it)
mkdir -p "$PREFIX/var/lib/swg-noded" "$PREFIX/var/log/swg-agent" "$PREFIX/etc/swg-agent"

# Pre-install wg + awg tools regardless of what interfaces (if any) are configured now — so creating
# an interface later from the panel "just works" (the sandboxed agent can't apt-install at runtime).
info "Installing WireGuard + AmneziaWG tools (for future interface creation)"
ensure_wg_tools wg  || warn "wireguard tools not installed — wg interface creation will need them"
ensure_wg_tools awg || warn "amneziawg tools not installed (the amnezia ppa is Ubuntu-only) — awg interface creation will need them"
ensure_smart_tools  # nftables + dnsmasq for Phase-3 smart routing (domain tier); harmless if already present

# ───────────────────────── config.json (pull-only HTTPS) ─────────────────────────
IFJSON=""; sep=""
for n in "${SELECTED[@]}"; do n="${n// /}"; [ -z "$n" ] && continue
  _onb=""; iface_onboarded "$n" && _onb=', "onboarded": true'   # add-only (adopted interface — keep its peers)
  IFJSON+="$sep    \"$n\": { \"cmd\": [\"${IF_CMD[$n]}\"], \"conf\": \"${IF_CONF[$n]}\", \"endpoint_host\": \"${IF_ENDPOINT[$n]:-}\"${_onb} }"; sep=$',\n'; done
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
run systemctl enable --quiet swg-noded
# restart (not just enable --now): on a RE-RUN that added interfaces, swg-noded is already running and
# reads config.json only at startup — so without a restart the new interfaces never reach the panel.
run systemctl restart swg-noded || warn "couldn't start swg-noded"   # turn-proxies already up (convert) → first report carries them
# Clear a stale convert-recovery marker now that the node is wired — but NOT when we're a STEP inside a
# docker→bare convert (SWG_CONVERT / SWG_TURN_ADD). convert.sh still has to migrate the turn-proxies and move
# the old docker dir aside after we return; it owns the marker and clears it (clear_recovery) only when the
# WHOLE convert is done. Clearing here would strand an interrupt after this point with no resume offer.
$DRYRUN || [ -n "${SWG_CONVERT:-}${SWG_TURN_ADD:-}" ] || rm -f /var/lib/swg-recovery 2>/dev/null || true

# during a convert, skip this summary entirely — convert.sh prints ONE final combined summary (interfaces +
# turn-proxies) after. The switch is done here (interfaces + turn-proxies + daemon all up).
if [ "${SWG_CONVERT:-}" = 1 ]; then
  echo; ok "Node '$(bb "$NODE_NAME")' is up — fully converted to bare-metal (interfaces + turn-proxies)."
  exit 0
fi
echo; ok "Node '$(bb "$NODE_NAME")' install complete."
print_summary "$([ "$EXISTING" = yes ] && echo RE-INSTALL || echo INSTALL)"
[ -n "$TLS_FINGERPRINT" ] && echo "  TLS       panel cert pinned (sha256 ${TLS_FINGERPRINT:0:16}…) — MITM-protected"
[ "$VERIFY_JSON" = false ] && [ -z "$TLS_FINGERPRINT" ] && echo "  TLS       ${C_BROWN}not verifying the panel cert${RESET} — set TLS_FINGERPRINT to pin it (MITM protection)"
if $DRYRUN; then echo; ok "DRY RUN done — inspect ./dryrun"; fi   # NB: an `if` (not `$DRYRUN && {…}`) so a non-dry-run doesn't make the script's LAST command exit non-zero (convert.sh read that as "install-node.sh reported an error")
echo     # one blank line after the summary block (consistency)
exit 0   # reaching here = success (every fatal error die'd with exit 1 earlier; a single interface that couldn't come up is a non-fatal warning)
