#!/usr/bin/env bash
# bootstrap.sh — fetch swg-panel from GitHub and run the right installer.
#
#   curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash
#       → interactive: pick installation method (bare-metal/docker) + role (master/host/node).
#   …| sudo bash -s -key NODE_KEY -host https://PANEL    → add a node (a key implies node; asks method).
#   …| sudo bash -s docker host                          → explicit method + role (skips the prompts).
#   …| sudo bash -s update                               → update an install in place.
#   …| sudo bash -s uninstall                            → guided removal.
#
# Method (bare-metal | docker) × Role (master | host | node) — each is asked only if not already
# given. A bare role word (host/master/node) means bare-metal; prefix `docker` for the docker path.
#
#   -key|-token <tok>   node enrollment token   (-> NODE_TOKEN; implies role=node)
#   -host|-url  <url>   panel URL (https://…)    (-> PANEL_URL)
#   -name       <name>  node name               (-> NODE_NAME)
#   -endpoint   <ip>    public endpoint IP       (-> ENDPOINT_IP)
#   -method <bare-metal|docker>   -role <master|host|node>
#
# Override the source with SWG_REPO / SWG_REF (branch or tag). Anything else is passed through.
set -euo pipefail
REPO="${SWG_REPO:-https://github.com/SanityProtocol/swg-panel}"
REF="${SWG_REF:-main}"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then BOLD=$'\033[1m'; RESET=$'\033[0m'; C_BLUE=$'\033[38;5;39m'; else BOLD=""; RESET=""; C_BLUE=""; fi
b(){ printf '%s%s%s' "$BOLD" "$*" "$RESET"; }
col(){ local c="$1"; shift; printf '%s%s%s' "$c" "$*" "$RESET"; }
menu(){ printf '  %s\n      %s\n\n' "$1" "$2"; }
die(){ echo "error: $*" >&2; exit 1; }
# ask_choice <prompt> <default> <var> "<opt…>" — accepts a full option OR its first-letter shortcut;
# shows the default's letter as [x]; friendly re-prompt on bad input.
ask_choice(){ local p="$1" d="$2" var="$3" opts="$4" v o rc sc pr
  sc="${d:0:1}"
  if [ -n "${!var:-}" ]; then for o in $opts; do [ "${!var}" = "$o" ] && return; done; fi
  pr="  $p${d:+ [$(col "$C_BLUE" "$sc")]}: "
  while :; do
    if read -rp "$pr" v </dev/tty 2>/dev/null; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"
    for o in $opts; do [ "$v" = "$o" ] || { [ -n "$v" ] && [ "$v" = "${o:0:1}" ]; } && { printf -v "$var" '%s' "$o"; return; }; done
    [ "$rc" -ne 0 ] && die "no interactive input for '$p' — pass it as a flag (one of: $opts)"
    if [ -n "$v" ]; then
      pr="  Can't understand \"$v\". $p${d:+ or press Enter to use the default [$(col "$C_BLUE" "$sc")]}: "
    else
      pr="  $p${d:+ [$(col "$C_BLUE" "$sc")]}: "
    fi
  done; }

ACTION=""; METHOD="${METHOD:-}"; ROLE="${ROLE:-}"; ROLE_EXPLICIT=no; HAVE_KEY=no
PASS=()
while [ $# -gt 0 ]; do
  case "$1" in
    update|uninstall)            ACTION="$1"; shift;;
    docker)                      METHOD=docker; shift;;
    bare-metal|baremetal)        METHOD=baremetal; shift;;
    master|host|node)            ROLE="$1"; ROLE_EXPLICIT=yes; shift;;
    -key|--key|-token|--token)   export NODE_TOKEN="${2:-}"; HAVE_KEY=yes; shift 2 || shift;;
    -host|--host|-url|--url)     export PANEL_URL="${2:-}";  shift 2 || shift;;
    -name|--name)                export NODE_NAME="${2:-}";  shift 2 || shift;;
    -endpoint|--endpoint)        export ENDPOINT_IP="${2:-}"; shift 2 || shift;;
    -method|--method)            METHOD="${2:-}"; shift 2 || shift;;
    -role|--role)                ROLE="${2:-}"; ROLE_EXPLICIT=yes; shift 2 || shift;;
    --)                          shift;;
    *)                           PASS+=("$1"); shift;;
  esac
done
[ "$METHOD" = bare-metal ] && METHOD=baremetal

[ "$(id -u)" = 0 ] || die "run with sudo (it installs users, units and certs)"

# ── fetch the repo ──
need(){ command -v "$1" >/dev/null 2>&1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
echo ":: fetching $REPO @ $REF"
if need git; then
  git clone --depth 1 --branch "$REF" "$REPO" "$TMP/swg-panel"
elif need curl && need tar; then
  curl -fsSL "$REPO/archive/refs/heads/$REF.tar.gz" | tar -xz -C "$TMP" \
    || curl -fsSL "$REPO/archive/refs/tags/$REF.tar.gz" | tar -xz -C "$TMP"
  mv "$TMP"/swg-panel-* "$TMP/swg-panel"
else
  die "need git, or curl+tar, to fetch the repo"
fi
cd "$TMP/swg-panel"

# ── update / uninstall: no method/role ──
if [ -n "$ACTION" ]; then
  SCRIPT="update.sh"; [ "$ACTION" = uninstall ] && SCRIPT="uninstall.sh"
  echo ":: running $SCRIPT"; exec bash "./$SCRIPT" ${PASS[@]+"${PASS[@]}"}
fi

# only a node carries an enrollment key — infer the role from -key
[ "$HAVE_KEY" = yes ] && [ -z "$ROLE" ] && ROLE=node

# ── method + role (sequential step numbering — only steps actually shown here count) ──
STEP=1
step(){ echo; echo "$(b "Step $STEP. $1")"; echo; STEP=$((STEP+1)); }
if [ -z "$METHOD" ]; then
  if [ "$ROLE_EXPLICIT" = yes ]; then METHOD=baremetal     # a bare role word (host/master/node) ⇒ bare-metal
  else
    step "Installation method"
    menu "$(b "$(col "$C_BLUE" '[b]are-metal (default)')")" "Runs directly on this host (kernel datapath, best throughput). Recommended for a dedicated box."
    menu "$(col "$C_BLUE" '[d]ocker')"                      "Runs in containers (userspace datapath, isolated). No kernel module needed."
    ask_choice "Select the installation method" "bare-metal" METHOD "bare-metal baremetal docker"
    [ "$METHOD" = bare-metal ] && METHOD=baremetal
  fi
fi
if [ -z "$ROLE" ]; then
  step "Server role"
  menu "$(b "$(col "$C_BLUE" '[m]aster')")" "Panel + a local WireGuard/AmneziaWG node on this box (all-in-one)."
  menu "$(col "$C_BLUE" '[h]ost')"          "Panel only; entry-server nodes are deployed separately (run their command from the panel)."
  menu "$(col "$C_BLUE" '[n]ode')"          "An entry server that joins an existing panel."
  ask_choice "Select the server role" "" ROLE "master host node"
fi
export STEP_BASE="$STEP"          # the installer numbers its steps from here

case "$METHOD-$ROLE" in
  baremetal-master|baremetal-host) export ROLE; SCRIPT="install-host.sh" ;;
  baremetal-node)                  unset ROLE; SCRIPT="install-node.sh" ;;
  docker-master)  export ROLE=master; SCRIPT="install-docker.sh"; PASS=(master ${PASS[@]+"${PASS[@]}"}) ;;
  docker-host)    export ROLE=host;   SCRIPT="install-docker.sh"; PASS=(host   ${PASS[@]+"${PASS[@]}"}) ;;
  docker-node)    unset ROLE;         SCRIPT="install-docker.sh"; PASS=(node   ${PASS[@]+"${PASS[@]}"}) ;;
  *) die "unknown method/role: '$METHOD' / '$ROLE'" ;;
esac
echo ":: running $SCRIPT"
exec bash "./$SCRIPT" ${PASS[@]+"${PASS[@]}"}
