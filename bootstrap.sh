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

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then BOLD=$'\033[1m'; RESET=$'\033[0m'; C_BLUE=$'\033[38;5;39m'; C_BL=$'\033[38;5;33m'; C_BROWN=$'\033[38;5;130m'; C_RED=$'\033[31m'; else BOLD=""; RESET=""; C_BLUE=""; C_BL=""; C_BROWN=""; C_RED=""; fi
b(){ printf '%s%s%s' "$BOLD" "$*" "$RESET"; }
col(){ local c="$1"; shift; printf '%s%s%s' "$c" "$*" "$RESET"; }
menu(){ printf '  %s\n      %s\n\n' "$1" "$2"; }
die(){  echo "${C_RED}✗ $*${RESET}" >&2; exit 1; }            # universal flags: :: blue, ! brown, ✗ red
warn(){ echo "${C_BROWN}!${RESET} $*" >&2; }
info(){ echo "${C_BL}::${RESET} $*"; }
# ask_choice <prompt> <default> <var> "<opt…>" — accepts a full option OR its first-letter shortcut;
# shows the default's letter as [x]; friendly re-prompt on bad input.
ask_choice(){ local p="$1" d="$2" var="$3" opts="$4" v o rc sc pr i
  sc="${d:0:1}"
  if [ -n "${!var:-}" ]; then for o in $opts; do [ "${!var}" = "$o" ] && return; done; fi
  pr="  $p${d:+ [$(col "$C_BLUE" "$sc")]}: "
  while :; do
    printf '%s' "$pr" >/dev/tty 2>/dev/null   # read -p writes the prompt to stderr (lost if redirected) — print it to the tty ourselves
    if read -r v </dev/tty 2>/dev/null; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"
    case "$v" in ''|*[!0-9]*) :;; *) i=1; for o in $opts; do [ "$i" = "$v" ] && { v="$o"; break; }; i=$((i+1)); done;; esac   # [N] → the Nth option
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
info "fetching $REPO @ $REF"
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
  info "running $SCRIPT"; exec bash "./$SCRIPT" ${PASS[@]+"${PASS[@]}"}
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
    info "both a bare-metal and a docker install are present — choose which to re-install:"   # mixed → fall through to the prompts
  elif [ "$_bare" = yes ]; then METHOD=baremetal
    if   [ "$BARE_PANEL" = yes ] && [ "$BARE_NODE" = yes ]; then ROLE=master
    elif [ "$BARE_PANEL" = yes ]; then ROLE=host; else ROLE=node; fi
  elif [ "$_dock" = yes ]; then METHOD=docker
    if   [ "$DOCK_PANEL" = yes ] && [ "$DOCK_NODE" = yes ]; then ROLE=master
    elif [ "$DOCK_PANEL" = yes ]; then ROLE=host; else ROLE=node; fi
  fi
  { [ -n "$METHOD" ] && [ -n "$ROLE" ]; } && info "existing $(mlabel "$METHOD") install detected — re-installing $(b "$ROLE") (your settings are the defaults)."
fi

# ── method + role (sequential step numbering — only steps actually shown here count) ──
STEP=1
step(){ echo; echo "$(b "Step $STEP. $1")"; echo; STEP=$((STEP+1)); }

# ── resume an interrupted conversion ─────────────────────────────────────────
# convert.sh persists the node's identity to /var/lib/swg-recovery before the final switch-over. Conversions
# are copy-first: the source node keeps running until everything is staged, so a dropped session usually left
# the node fully up on its CURRENT method. Offer to finish the move (same token); declining just keeps it.
if [ -f /var/lib/swg-recovery ]; then
  . /var/lib/swg-recovery 2>/dev/null || true
  if [ -n "${SWG_RV_FROM:-}" ] && [ -n "${SWG_RV_TO:-}" ] && [ -n "${SWG_RV_ROLE:-}" ]; then
    echo
    warn "An unfinished $(mlabel "$SWG_RV_FROM") → $(mlabel "$SWG_RV_TO") conversion was found."
    info "  Resume → finish it on $(mlabel "$SWG_RV_TO"), keeping the same node, token and peers (safe even if the switch-over had already begun)."
    info "  Skip   → leave the node on $(mlabel "$SWG_RV_FROM"); the unfinished $(mlabel "$SWG_RV_TO") copy is inert and gets auto-removed."
    _ans=yes; ask_yn "Resume the conversion now" y _ans
    if [ "$_ans" = yes ]; then
      info "resuming the $(mlabel "$SWG_RV_FROM") → $(mlabel "$SWG_RV_TO") conversion…"; echo
      exec bash "./convert.sh" "$SWG_RV_FROM" "$SWG_RV_TO" "$SWG_RV_ROLE" ${PASS[@]+"${PASS[@]}"}
    fi
    info "keeping the node on $(mlabel "$SWG_RV_FROM") — the unfinished $(mlabel "$SWG_RV_TO") copy is inert and gets auto-removed on any re-install, conversion or update."
    rm -f /var/lib/swg-recovery 2>/dev/null || true
  fi
fi

if [ -z "$METHOD" ]; then
  if [ "$ROLE_EXPLICIT" = yes ]; then METHOD=baremetal     # a bare role word (host/master/node) ⇒ bare-metal
  else
    step "Installation method"
    menu "$(b "$(col "$C_BLUE" '[1] [b]are-metal (default)')")" "Runs directly on this host (kernel datapath, best throughput). Recommended for a dedicated box."
    menu "$(col "$C_BLUE" '[2] [d]ocker')"                      "Runs in containers (userspace datapath, isolated). No kernel module needed."
    ask_choice "Select the installation method (number, letter or name)" "bare-metal" METHOD "bare-metal docker baremetal"
    [ "$METHOD" = bare-metal ] && METHOD=baremetal
  fi
fi
if [ -z "$ROLE" ]; then
  step "Server role"
  menu "$(b "$(col "$C_BLUE" '[1] [m]aster (default)')")" "Panel + a local WireGuard/AmneziaWG node on this box (all-in-one)."
  menu "$(col "$C_BLUE" '[2] [h]ost')"                    "Panel only; entry-server nodes are deployed separately (run their command from the panel)."
  menu "$(col "$C_BLUE" '[3] [n]ode')"                    "An entry server that joins an existing panel."
  ask_choice "Select the server role (number, letter or name)" "master" ROLE "master host node"
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
    menu "$(b "$(col "$C_BLUE" '[1] [c]onvert')")"      "Migrate it to $(mlabel "$METHOD") — all settings / users / peers are preserved. A port/interface pre-flight runs first."
    menu "$(col "$C_BLUE" '[2] [k]eep and re-install')" "Leave it on $(mlabel "$OTHER") and just re-install it (you didn't mean to switch methods)."
    menu "$(col "$C_BLUE" '[3] [a]bort')"               "Exit without changing anything."
    CHOICE=""; ask_choice "Convert, keep, or abort (number, letter or name)" "convert" CHOICE "convert keep abort"
    case "$CHOICE" in
      abort) info "aborted — nothing changed."; exit 0;;
      keep)  METHOD="$OTHER"; info "keeping the existing $(mlabel "$OTHER") install — re-installing it as-is."; break;;
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

# A plain (re-)install clears a stale leftover from an ABORTED conversion — it's just an outdated copy, so no
# prompt. The live node (still on its original method) is untouched: an ACTIVE other-method install would have
# offered 'convert' above, so reaching here as a plain install means there's nothing live of the other method.
if [ "${CHOICE:-}" != convert ]; then
  if [ "$METHOD" = baremetal ] && [ -d "$DOCKER_DIR" ] && command -v docker >/dev/null 2>&1 \
       && ! docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qxE 'swg-(node|panel)'; then
    info "removing a stale docker leftover at $(b "$DOCKER_DIR") — no container present (likely a cancelled bare→docker convert); your live install is untouched"
    rm -rf "$DOCKER_DIR" 2>/dev/null || true
  fi
  # docker (re-)install: drop ONLY the bare confs that match this docker node's confs (i.e. copies a docker→bare
  # convert left behind) and only when no swg-noded is installed — never an unrelated WireGuard config.
  if [ "$METHOD" = docker ] && [ -d "$DOCKER_DIR/data/node-confs" ] && command -v systemctl >/dev/null 2>&1 \
       && ! systemctl list-unit-files swg-noded.service >/dev/null 2>&1; then
    _cleared=
    for _c in "$DOCKER_DIR/data/node-confs/"*.conf; do [ -f "$_c" ] || continue; _n="$(basename "$_c" .conf)"
      for _d in "/etc/amnezia/amneziawg/$_n.conf" "/etc/wireguard/$_n.conf"; do [ -f "$_d" ] && { rm -f "$_d"; _cleared=1; }; done
    done
    [ -n "$_cleared" ] && info "removed stale bare-metal conf leftovers — no swg-noded service present (likely a cancelled docker→bare convert); your live install is untouched"
  fi
fi

export STEP_BASE="$STEP"          # the installer numbers its steps from here

# ── salvage a leftover node identity (NO recovery marker — e.g. an install/convert interrupted on an
#    older version). A half-finished node may still hold its token in a docker .env, a moved docker
#    backup (…​.converted-*), the swg-node container's env, or the bare agent config. Re-using it
#    re-enrolls this box as the SAME node so it isn't orphaned on the panel (its peers re-sync). ──
# A NORMAL re-install reuses the token from the LIVE deployment itself — install-docker.sh from its .env,
# install-node.sh from the agent config — so the installer handles it and we must NOT hijack into recovery.
# The salvage is only for a node that's actually GONE (live source missing; token only in old backups).
_have_live_token=no
if [ "$ROLE" = node ] && [ -z "${NODE_TOKEN:-}" ]; then
  if [ "$METHOD" = docker ]; then
    if [ -f "$DOCKER_DIR/.env" ]; then _lt="$(sed -n 's/^NODE_TOKEN=//p' "$DOCKER_DIR/.env" | head -1 | tr -d '"')"
      [ -n "$_lt" ] && [ "$_lt" != "set-in-nodes-screen" ] && _have_live_token=yes; fi
  else
    if [ -f /etc/swg-agent/config.json ] && command -v python3 >/dev/null 2>&1; then
      _lt="$(python3 -c 'import json;print((json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("token",""))' 2>/dev/null || true)"
      [ -n "$_lt" ] && _have_live_token=yes; fi
  fi
  [ "$_have_live_token" = yes ] && info "re-installing the existing $(mlabel "$METHOD") node (its token is reused — to recover/rotate instead, use the panel's Recover button or pass -key)."
fi
# Render a leftover identity as a readable block: method, panel URL, token, where its configs live, the
# interfaces + turn-proxies it had, when it was created, and (best-effort, via the panel) its name + last-online.
_fmt_epoch(){ [ -n "${1:-}" ] && date -d "@$1" '+%d.%m.%Y %H:%M:%S' 2>/dev/null || echo "unknown"; }
_salv_created(){ local s="$1" ts
  case "$s" in *.converted-*) ts="$(printf '%s' "$s" | sed -n 's/.*\.converted-\([0-9]\{8\}\)-\([0-9]\{6\}\).*/\1\2/p')"
    [ -n "$ts" ] && { printf '%s.%s.%s %s:%s:%s\n' "${ts:6:2}" "${ts:4:2}" "${ts:0:4}" "${ts:8:2}" "${ts:10:2}" "${ts:12:2}"; return; };; esac
  [ -f "$s" ] && _fmt_epoch "$(stat -c %Y "$s" 2>/dev/null)" || echo "unknown"; }
_salv_block(){ local idx="$1" tok="$2" url="$3" src="$4" method dir ifaces turns name last wj ls
  case "$src" in
    *config.json) method="Bare-metal"; dir="/etc/swg-agent";;
    "the swg-node container") method="Docker"; dir="/opt/swg-panel-docker";;
    *) method="Docker"; dir="$(dirname "$src" 2>/dev/null)";; esac
  if [ "$method" = Docker ]; then
    ifaces="$(ls "$dir/data/node-confs"/*.conf 2>/dev/null | while read -r c; do basename "$c" .conf; done | tr '\n' ' ')"
    turns="$(python3 -c 'import json,sys;print(len((json.load(open(sys.argv[1])).get("turn_proxies") or [])))' "$dir/data/node/turn-proxy.json" 2>/dev/null || echo '?')"
  else
    ifaces="$(python3 -c 'import json;print(" ".join((json.load(open("/etc/swg-agent/config.json")).get("interfaces") or {}).keys()))' 2>/dev/null || true)"; turns="?"
  fi
  name=""; last=""
  if [ -n "$url" ] && command -v curl >/dev/null 2>&1; then
    wj="$(curl -fsS -k --max-time 6 -H "Authorization: Bearer $tok" "${url%/}/api/node/whoami" 2>/dev/null || true)"
    name="$(printf '%s' "$wj" | sed -n 's/.*"name": *"\([^"]*\)".*/\1/p')"
    ls="$(printf '%s' "$wj" | sed -n 's/.*"last_seen": *\([0-9][0-9]*\).*/\1/p')"; [ -n "$ls" ] && last="$(_fmt_epoch "$ls")"
  fi
  echo "  [$idx]  $(b "$method node${name:+ $name}")"
  echo "           Panel URL:     ${url:-unknown}"
  echo "           Token:         $tok"
  echo "           Configs path:  $dir/"
  echo "           Interfaces:    ${ifaces:-none}"
  echo "           Turn-proxies:  ${turns:-0}"
  echo "           Created:       $(_salv_created "$src")"
  echo "           Last online:   ${last:-unknown (no answer from panel)}"
  echo
}
if [ "$ROLE" = node ] && [ -z "${NODE_TOKEN:-}" ] && [ "$_have_live_token" = no ]; then
  _salvf="$(mktemp 2>/dev/null || echo "/tmp/swg-salv.$$")"; : > "$_salvf"
  # collect every candidate identity as "<token>\t<url>\t<source>" — most authoritative first: a leftover
  # swg-node container, then docker .env (live + moved backups, NEWEST first), then the bare agent config.
  if command -v docker >/dev/null 2>&1; then
    _env="$(docker inspect swg-node --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null || true)"
    _t="$(printf '%s\n' "$_env" | sed -n 's/^NODE_TOKEN=//p' | head -1)"
    [ -n "$_t" ] && printf '%s\t%s\t%s\n' "$_t" "$(printf '%s\n' "$_env" | sed -n 's/^PANEL_URL=//p' | head -1)" "the swg-node container" >> "$_salvf"
  fi
  for _f in /opt/swg-panel-docker/.env $(ls -dt /opt/swg-panel-docker.converted-*/.env 2>/dev/null || true); do
    [ -f "$_f" ] || continue
    _t="$(sed -n 's/^NODE_TOKEN=//p' "$_f" | head -1 | tr -d '"')"
    [ -n "$_t" ] && [ "$_t" != "set-in-nodes-screen" ] && printf '%s\t%s\t%s\n' "$_t" "$(sed -n 's/^PANEL_URL=//p' "$_f" | head -1 | tr -d '"')" "$_f" >> "$_salvf"
  done
  if [ -f /etc/swg-agent/config.json ] && command -v python3 >/dev/null 2>&1; then
    python3 - >> "$_salvf" 2>/dev/null <<'PY' || true
import json
try:
    d=(json.load(open("/etc/swg-agent/config.json")).get("panel") or {})
    if d.get("token"): print(d["token"]+"\t"+(d.get("url") or "")+"\t/etc/swg-agent/config.json")
except Exception: pass
PY
  fi
  # dedup by token (a node keeps its token across converts, so repeated backups collapse to ONE identity)
  _uniq="$(awk -F'\t' '$1 && !seen[$1]++' "$_salvf" 2>/dev/null || true)"; rm -f "$_salvf"
  _ntok="$(printf '%s\n' "$_uniq" | grep -c . 2>/dev/null || true)"; _ntok="${_ntok:-0}"
  salv_tok=""; salv_url=""
  if [ "$_ntok" = 1 ]; then
    salv_tok="$(printf '%s' "$_uniq" | cut -f1)"; salv_url="$(printf '%s' "$_uniq" | cut -f2)"
    echo
    warn "Found a leftover identity for a node that used to live on this box — its live config is gone, but the token survives in a backup (an install or conversion that didn't finish)."
    echo
    _salv_block 1 "$salv_tok" "$salv_url" "$(printf '%s' "$_uniq" | cut -f3-)"
    info "  Re-enroll → this box rejoins the panel as the SAME node: same token, and its existing peers re-sync onto it."
    info "  Skip      → set this box up as a NEW node instead; you'll supply a token yourself (panel → Nodes, or pass -key)."
    _sa=yes; ask_yn "Re-enroll as this node" y _sa
    [ "$_sa" = yes ] || salv_tok=""
  elif [ "$_ntok" != 0 ]; then
    echo
    warn "Found $_ntok leftover node identities on this box (from past converts / re-installs) — their live configs are gone but the tokens survive in backups. Pick which to re-enroll as (or skip for a new node):"
    echo
    _i=0
    while IFS="$(printf '\t')" read -r _t _u _s; do [ -n "$_t" ] || continue; _i=$((_i+1)); _salv_block "$_i" "$_t" "$_u" "$_s"; done <<EOF2
$_uniq
EOF2
    printf '  Number to re-enroll with (or Enter to skip and set up a new node — you supply a token, panel → Nodes or -key): '; _pick=""; read -r _pick </dev/tty 2>/dev/null || _pick=""
    if printf '%s' "$_pick" | grep -qE '^[0-9]+$'; then
      _line="$(printf '%s\n' "$_uniq" | sed -n "${_pick}p" 2>/dev/null || true)"
      salv_tok="$(printf '%s' "$_line" | cut -f1)"; salv_url="$(printf '%s' "$_line" | cut -f2)"
    fi
  fi
  if [ -n "$salv_tok" ]; then
    NODE_TOKEN="$salv_tok"; export NODE_TOKEN; [ -n "$salv_url" ] && { PANEL_URL="$salv_url"; export PANEL_URL; }
    info "re-enrolling this box as the recovered node (token reused — its peers re-sync onto it)."
  fi
fi

case "$METHOD-$ROLE" in
  baremetal-master|baremetal-host) export ROLE; SCRIPT="install-host.sh" ;;
  baremetal-node)                  unset ROLE; SCRIPT="install-node.sh" ;;
  docker-master)  export ROLE=master; SCRIPT="install-docker.sh"; PASS=(master ${PASS[@]+"${PASS[@]}"}) ;;
  docker-host)    export ROLE=host;   SCRIPT="install-docker.sh"; PASS=(host   ${PASS[@]+"${PASS[@]}"}) ;;
  docker-node)    unset ROLE;         SCRIPT="install-docker.sh"; PASS=(node   ${PASS[@]+"${PASS[@]}"}) ;;
  *) die "unknown method/role: '$METHOD' / '$ROLE'" ;;
esac
info "running $SCRIPT"
exec bash "./$SCRIPT" ${PASS[@]+"${PASS[@]}"}
