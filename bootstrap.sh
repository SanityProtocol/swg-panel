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
# Survive being launched from a directory that no longer exists — common right after an uninstall
# removed it (the shell stays "in" the deleted dir, getcwd() fails, and git/curl refuse to run).
# Step into a guaranteed-present directory before doing anything.
cd / 2>/dev/null || cd "${TMPDIR:-/tmp}" 2>/dev/null || true
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
    printf '%s' "$pr" >/dev/tty 2>/dev/null   # read -p writes the prompt to stderr (lost if redirected) — print it to the tty ourselves
    if read -r v </dev/tty 2>/dev/null; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"
    for o in $opts; do [ "$v" = "$o" ] || { [ -n "$v" ] && [ "$v" = "${o:0:1}" ]; } && { printf -v "$var" '%s' "$o"; return; }; done
    [ "$rc" -ne 0 ] && die "no interactive input for '$p' — pass it as a flag (one of: $opts)"
    if [ -n "$v" ]; then
      pr="  Can't understand \"$v\". $p${d:+ or press Enter to use the default [$(col "$C_BLUE" "$sc")]}: "
    else
      pr="  $p${d:+ [$(col "$C_BLUE" "$sc")]}: "
    fi
  done; }
ask_yn(){ local p="$1" d="$2" var="$3" v   # ask_yn <prompt> <y|n default> <var>  → sets var to yes/no
  printf '%s' "  $p ($([ "$d" = y ] && echo 'Y/n' || echo 'y/N')): " >/dev/tty 2>/dev/null
  read -r v </dev/tty 2>/dev/null || v="$d"; v="${v:-$d}"
  case "$v" in [Yy]*) printf -v "$var" yes;; *) printf -v "$var" no;; esac; }

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

# ───────────────── existing-install detection (drives the routing below) ─────────────────
SD=/etc/systemd/system; DOCKER_DIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"
dkr(){ command -v docker >/dev/null 2>&1; }
dkr_has(){ dkr && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$1"; }
BARE_PANEL=no; BARE_NODE=no; DOCK_PANEL=no; DOCK_NODE=no
if [ -d /opt/swg-panel ] || [ -f "$SD/swg-panel-server.service" ]; then BARE_PANEL=yes; fi
if [ -d /opt/swg-noded ] || [ -d /opt/swg-agent ] || [ -f "$SD/swg-noded.service" ]; then BARE_NODE=yes; fi
if dkr_has swg-panel; then DOCK_PANEL=yes; fi
if dkr_has swg-node;  then DOCK_NODE=yes; fi
has_comp(){ case "$1-$2" in   # has_comp <baremetal|docker> <panel|node>  → 0 if that component is installed
  baremetal-panel) [ "$BARE_PANEL" = yes ];; baremetal-node) [ "$BARE_NODE" = yes ];;
  docker-panel)    [ "$DOCK_PANEL" = yes ];; docker-node)    [ "$DOCK_NODE" = yes ];; *) return 1;; esac; }
mlabel(){ [ "$1" = baremetal ] && echo bare-metal || echo "$1"; }

# Bare `install` (no method, no role): re-install exactly what's already here, skipping the prompts.
if [ -z "$METHOD" ] && [ -z "$ROLE" ]; then
  _bare=no; _dock=no
  { [ "$BARE_PANEL" = yes ] || [ "$BARE_NODE" = yes ]; } && _bare=yes
  { [ "$DOCK_PANEL" = yes ] || [ "$DOCK_NODE" = yes ]; } && _dock=yes
  if [ "$_bare" = yes ] && [ "$_dock" = yes ]; then
    echo ":: both a bare-metal and a docker install are present — choose which to re-install:"   # mixed → fall through to the prompts
  elif [ "$_bare" = yes ]; then METHOD=baremetal
    if   [ "$BARE_PANEL" = yes ] && [ "$BARE_NODE" = yes ]; then ROLE=master
    elif [ "$BARE_PANEL" = yes ]; then ROLE=host; else ROLE=node; fi
  elif [ "$_dock" = yes ]; then METHOD=docker
    if   [ "$DOCK_PANEL" = yes ] && [ "$DOCK_NODE" = yes ]; then ROLE=master
    elif [ "$DOCK_PANEL" = yes ]; then ROLE=host; else ROLE=node; fi
  fi
  { [ -n "$METHOD" ] && [ -n "$ROLE" ]; } && echo ":: existing $(mlabel "$METHOD") install detected — re-installing $(b "$ROLE") (your settings are the defaults)."
fi

# ── method + role (sequential step numbering — only steps actually shown here count) ──
STEP=1
step(){ echo; echo "$(b "Step $STEP. $1")"; echo; STEP=$((STEP+1)); }

# ── resume an interrupted conversion ─────────────────────────────────────────
# convert.sh persists the node's identity to /var/lib/swg-recovery before any teardown. If the session
# dropped mid-convert, finish it with the SAME token instead of starting over (which would orphan the node).
if [ -f /var/lib/swg-recovery ]; then
  . /var/lib/swg-recovery 2>/dev/null || true
  if [ -n "${SWG_RV_FROM:-}" ] && [ -n "${SWG_RV_TO:-}" ] && [ -n "${SWG_RV_ROLE:-}" ]; then
    echo
    warn "An interrupted conversion ($(mlabel "$SWG_RV_FROM") → $(mlabel "$SWG_RV_TO")) was found — its node would be LOST if you start over."
    _ans=yes; ask_yn "Resume it now and finish the conversion (keeps the same node)" y _ans
    if [ "$_ans" = yes ]; then
      echo ":: resuming the $(mlabel "$SWG_RV_FROM") → $(mlabel "$SWG_RV_TO") conversion…"; echo
      exec bash "$SRC/convert.sh" "$SWG_RV_FROM" "$SWG_RV_TO" "$SWG_RV_ROLE" ${PASS[@]+"${PASS[@]}"}
    fi
    warn "not resuming — removing the recovery marker; the half-converted node may be orphaned on the panel until you re-add it."
    rm -f /var/lib/swg-recovery 2>/dev/null || true
  fi
fi

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
  menu "$(b "$(col "$C_BLUE" '[m]aster (default)')")" "Panel + a local WireGuard/AmneziaWG node on this box (all-in-one)."
  menu "$(col "$C_BLUE" '[h]ost')"                    "Panel only; entry-server nodes are deployed separately (run their command from the panel)."
  menu "$(col "$C_BLUE" '[n]ode')"                    "An entry server that joins an existing panel."
  ask_choice "Select the server role" "master" ROLE "master host node"
fi
# ───────────────── cross-method conflict (requested method ≠ what's already installed) ─────────────────
# For each component the requested role needs, if the OTHER method has it but THIS method doesn't,
# offer to convert it, keep+re-install it as-is, or abort. (Same-method present ⇒ a normal re-install,
# handled inside the installer; neither present ⇒ a fresh install — your promotion cases.)
ROLE_COMPS=""; case "$ROLE" in host) ROLE_COMPS=panel;; node) ROLE_COMPS=node;; master) ROLE_COMPS="panel node";; esac
OTHER=baremetal; [ "$METHOD" = baremetal ] && OTHER=docker
CONFLICT=""
for _c in $ROLE_COMPS; do
  if ! has_comp "$METHOD" "$_c" && has_comp "$OTHER" "$_c"; then CONFLICT="${CONFLICT:+$CONFLICT }$_c"; fi
done
if [ -n "$CONFLICT" ]; then
  while :; do
    echo
    echo "$(b "! A $(mlabel "$OTHER") $ROLE is already installed on this box.")"
    echo "  Convert it to a $(mlabel "$METHOD") $ROLE, or re-install it as it is?"
    echo
    menu "$(b "$(col "$C_BLUE" '[c]onvert')")"      "Migrate it to $(mlabel "$METHOD") — all settings / users / peers are preserved. A port/interface pre-flight runs first."
    menu "$(col "$C_BLUE" '[k]eep and re-install')" "Leave it on $(mlabel "$OTHER") and just re-install it (you didn't mean to switch methods)."
    menu "$(col "$C_BLUE" '[a]bort')"               "Exit without changing anything."
    CHOICE=""; ask_choice "Convert, keep, or abort" "convert" CHOICE "convert keep abort"
    case "$CHOICE" in
      abort) echo ":: aborted — nothing changed."; exit 0;;
      keep)  METHOD="$OTHER"; echo ":: keeping the existing $(mlabel "$OTHER") install — re-installing it as-is."; break;;
      convert)
        # pre-flight (port/interface check) lives in convert.sh --check: exit 0 = clear, non-0 = printed conflicts
        if bash "./convert.sh" --check "$OTHER" "$METHOD" "$ROLE"; then
          _ans=no; ask_yn "No conflicts found, do you want to proceed with the conversion" y _ans
          [ "$_ans" = yes ] && exec bash "./convert.sh" "$OTHER" "$METHOD" "$ROLE" ${PASS[@]+"${PASS[@]}"}
        fi
        ;;   # conflicts (or 'no' at the confirm) → loop the menu again
    esac
  done
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
