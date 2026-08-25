#!/usr/bin/env bash
# adopt.sh — move an EXISTING swg install onto NixOS, keeping the server's identity.
#
#   sudo ./nix/adopt.sh --to native|container [--carry] [--release] [flags]
#
# Run it ON THE BOX THAT HAS THE INSTALL, while it is still imperative — i.e. while systemctl can still
# write units and docker can still stop containers. It does three things, each opt-in past the first:
#
#   (report)    what is installed here, the identity that must survive, the token to re-use, and the
#               configuration.nix that matches. Reads only; this is the default.
#   --carry     the CROSS-CONVENTION state carry, and only when the two conventions actually differ.
#               Calls lib/common.sh's migrate_* helpers — the same ones the docker↔bare-metal convert
#               uses — rather than a second copy of the path map. Copies; never moves.
#   --release   stop and remove the imperative UNITS, keeping every byte of state. Not the uninstaller:
#               uninstall.sh signs the node off the panel (/api/node/goodbye) and deletes
#               /var/lib/swg-noded, /etc/swg-agent and /opt/swg-{wdtt,csqtt} — which is exactly the
#               identity an adoption exists to keep. Running it here would look like a clean move right
#               up until every client stopped connecting.
#
# ORDER MATTERS. uninstall.sh and this script both refuse once the box is declarative (a read-only
# /etc/systemd/system), because a `systemctl disable` there fails and a script that walks past that
# failure leaves services running with their files deleted. So: --carry and --release FIRST, then
# declare services.swg-* and rebuild.
#
# WHAT IS AT STAKE is server identity: each interface's private key (its .conf), each WDTT instance's
# wg-keys.dat, each csqtt password store, and the node's enrolment token. Re-minting any of them looks
# exactly like a successful move until the clients stop connecting.
set -uo pipefail   # not -e: a report must finish even when one probe of a half-installed box fails
SRC="$(cd "$(dirname "$0")/.." && pwd)"
[ -r "$SRC/lib/common.sh" ] || { echo "adopt.sh: run me from a clone — lib/common.sh is not beside me ($SRC)" >&2; exit 1; }

if { [ -t 1 ] || [ -n "${SWG_FORCE_COLOR:-}" ]; } && [ -z "${NO_COLOR:-}" ]; then C_BLUE=$'\033[38;5;39m'; C_BL=$'\033[38;5;33m'; C_BROWN=$'\033[38;5;130m'; C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; RESET=$'\033[0m'; BOLD=$'\033[1m'
else C_BLUE=""; C_BL=""; C_BROWN=""; C_RED=""; C_GREEN=""; RESET=""; BOLD=""; fi
b(){ printf '%s%s%s' "$BOLD" "$*" "$RESET"; }
info(){ echo "${C_BLUE}▸${RESET} ${BOLD}$*${RESET}"; }
sub(){  echo "${C_BL}::${RESET} $*"; }
ok(){   echo "${C_GREEN}✓${RESET} $*"; }
warn(){ echo "${C_BROWN}!${RESET} $*" >&2; }
die(){  echo "${C_RED}✗ $*${RESET}" >&2; exit 1; }
. "$SRC/lib/common.sh"   # migrate_wdtt / migrate_csqtt / migrate_node_state / migrate_turn_record
# ⚠️ sourced AFTER info/warn/sub are defined, deliberately: lib/common.sh does not define them (it fills in
# b/bb/have and nothing else), and the migrate_* helpers report their FAILURE through warn. Sourced into a
# shell without one, the loudest line in the file is a "warn: command not found" on stderr.

TO=""; DO_CARRY=no; DO_RELEASE=no; DRYRUN=false; SHOW_TOKEN=no; TOKEN_OUT=""
DOCKER_DIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"
STATE_DIR="/var/lib/swg-noded"          # services.swg-node.stateDir — the module's default, which IS bare-metal's
CONF_DIR="/etc/amnezia/amneziawg"       # services.swg-node.confDir  — likewise
SD="${SYSTEMD_DIR:-/etc/systemd/system}"

usage(){ cat <<USAGE
adopt.sh — move an existing swg install onto NixOS, keeping the server's identity.

  sudo ./nix/adopt.sh --to native|container [--carry] [--release] [flags]

  --to native|container   the delivery arm you are moving to                 (required)
  --carry                 run the cross-convention state carry (copies, never moves)
  --release               stop + remove the imperative units, keeping ALL state
  --state-dir DIR         services.swg-node.stateDir   (default $STATE_DIR)
  --conf-dir DIR          services.swg-node.confDir    (default $CONF_DIR)
  --docker-dir DIR        an existing docker install    (default $DOCKER_DIR)
  --token-out FILE        write the node's existing enrolment token to FILE (0600)
  --show-token            print the token in full instead of masked
  --dry-run               say what --carry / --release would do, and do nothing
  -h, --help              this

With neither --carry nor --release it only reports. Run it in that order: report, carry, release,
THEN declare services.swg-* and rebuild. See nix/README.md — "Moving an existing install onto NixOS".
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --to)          TO="${2:-}"; shift 2 || shift;;
    --carry)       DO_CARRY=yes; shift;;
    --release)     DO_RELEASE=yes; shift;;
    --state-dir)   STATE_DIR="${2:-}"; shift 2 || shift;;
    --conf-dir)    CONF_DIR="${2:-}"; shift 2 || shift;;
    --docker-dir)  DOCKER_DIR="${2:-}"; shift 2 || shift;;
    --token-out)   TOKEN_OUT="${2:-}"; shift 2 || shift;;
    --show-token)  SHOW_TOKEN=yes; shift;;
    --dry-run)     DRYRUN=true; shift;;
    -h|--help)     usage; exit 0;;
    *)             die "unknown argument: $1 (try --help)";;
  esac
done
case "$TO" in
  native|container) ;;
  "")  usage; exit 1;;
  *)   die "--to must be native or container (got '$TO')";;
esac
[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
run(){ if $DRYRUN; then echo "    [dry] $*"; else "$@"; fi; }

# ───────────────────────── what is installed here ─────────────────────────
# Kept deliberately literal — each of these is one identity-bearing artifact, and "nothing found" must be
# distinguishable from "did not look".
NODE_CFG=/etc/swg-agent/config.json
BARE_NODE=no;  if [ -f "$NODE_CFG" ] || [ -e "$SD/swg-noded.service" ] || [ -x /opt/swg-noded/swg-noded ]; then BARE_NODE=yes; fi
BARE_PANEL=no; if [ -e "$SD/swg-panel-server.service" ] || [ -x /opt/swg-panel/swg-panel-server ]; then BARE_PANEL=yes; fi
DOCKER_NODE=no; DOCKER_PANEL=no
if command -v docker >/dev/null 2>&1; then
  docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-node  && DOCKER_NODE=yes
  docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-panel && DOCKER_PANEL=yes
fi
# A docker install whose containers are already gone is still a docker install: its data dir holds the state.
[ "$DOCKER_NODE" = no ]  && [ -d "$DOCKER_DIR/data/node" ] && DOCKER_NODE=stale
[ "$DOCKER_PANEL" = no ] && [ -d "$DOCKER_DIR/data/lib" ]  && DOCKER_PANEL=stale

FROM=""
{ [ "$BARE_NODE" = yes ] || [ "$BARE_PANEL" = yes ]; } && FROM=baremetal
{ [ "$DOCKER_NODE" != no ] || [ "$DOCKER_PANEL" != no ]; } && FROM="${FROM:+$FROM+}docker"
[ -n "$FROM" ] || die "no swg install found on this box (looked for $NODE_CFG, $SD/swg-*.service and $DOCKER_DIR/data).
    Nothing to adopt — a fresh NixOS host just declares services.swg-node / services.swg-panel."
[ "$FROM" = "baremetal+docker" ] && warn "BOTH a bare-metal and a docker install are present. Adopt one at a time:
    pass --docker-dir/--state-dir so each run names the one you mean, and check the report below carefully."

py(){ python3 "$@"; }
command -v python3 >/dev/null 2>&1 || warn "python3 is missing — the token/name lookups below will be skipped"

read_bare_node(){   # token, panel url, endpoint, verify, fingerprint — TAB separated
  [ -f "$NODE_CFG" ] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  py - "$NODE_CFG" <<'PY' 2>/dev/null
import json, sys
try: c = json.load(open(sys.argv[1]))
except Exception: raise SystemExit
p = c.get("panel") or {}
print("\t".join([p.get("token") or "", p.get("url") or "", c.get("endpoint_host") or "",
                 "yes" if p.get("verify", True) else "no", p.get("fingerprint") or ""]))
PY
}
read_docker_env(){  # same five, out of the compose .env
  local e="$DOCKER_DIR/.env" g
  [ -f "$e" ] || return 0
  g(){ sed -n "s/^$1=//p" "$e" 2>/dev/null | head -1 | sed 's/^"//; s/"$//'; }
  printf '%s\t%s\t%s\t%s\t%s\n' "$(g NODE_TOKEN)" "$(g PANEL_URL)" "$(g NODE_ENDPOINT)" "$(g TLS_VERIFY)" "$(g TLS_FINGERPRINT)"
}
mask(){ local t="${1:-}"; [ -n "$t" ] || { printf '(none)'; return; }
  if [ "$SHOW_TOKEN" = yes ]; then printf '%s' "$t"; else printf '%s…%s (%d chars — --show-token to print it)' "${t:0:4}" "${t: -2}" "${#t}"; fi; }

NTOK=""; NURL=""; NEP=""; NVERIFY=""; NFP=""; TOKSRC=""
if [ "$BARE_NODE" = yes ]; then
  IFS="$(printf '\t')" read -r NTOK NURL NEP NVERIFY NFP <<<"$(read_bare_node)" || true
  [ -n "$NTOK" ] && TOKSRC="$NODE_CFG (panel.token)"
fi
if [ -z "$NTOK" ] && [ "$DOCKER_NODE" != no ]; then
  IFS="$(printf '\t')" read -r NTOK NURL NEP NVERIFY NFP <<<"$(read_docker_env)" || true
  [ -n "$NTOK" ] && TOKSRC="$DOCKER_DIR/.env (NODE_TOKEN)"
fi

# The panel's own name for this node, when the panel is on this box (a master). Matched the way the panel
# matches — by verifying the token against each entry's hash — because that is the identity that decides
# whether an adopted master re-attaches to its node or enrols a SECOND one beside it.
LOCAL_NODE_NAME=""
node_name_for_token(){
  local nodes="$1" tok="$2"
  [ -f "$nodes" ] && [ -n "$tok" ] && command -v python3 >/dev/null 2>&1 || return 0
  py - "$nodes" "$tok" <<'PY' 2>/dev/null
import base64, hashlib, json, sys
try: nodes = json.load(open(sys.argv[1]))
except Exception: raise SystemExit
tok = sys.argv[2]
def validates(th):
    try:
        algo, it, salt, h = th.split("$")
        return algo == "pbkdf2_sha256" and base64.b64encode(
            hashlib.pbkdf2_hmac("sha256", tok.encode(), base64.b64decode(salt), int(it))).decode() == h
    except Exception:
        return False
sha = hashlib.sha256(tok.encode()).hexdigest()
for k, v in (nodes.items() if isinstance(nodes, dict) else []):
    if not isinstance(v, dict): continue
    if v.get("token_sha") == sha or validates(v.get("token_hash", "")):
        print(v.get("name") or k); break
PY
}
PANEL_STATE=/var/lib/swg-panel
[ "$DOCKER_PANEL" != no ] && [ ! -d "$PANEL_STATE" ] && PANEL_STATE="$DOCKER_DIR/data/lib"
LOCAL_NODE_NAME="$(node_name_for_token "$PANEL_STATE/nodes.json" "$NTOK")"

# ───────────────────────── report ─────────────────────────
echo
info "This box: $(b "$FROM") → $(b "nix-$TO")"
[ "$BARE_NODE" = yes ]    && sub "bare-metal node     $NODE_CFG"
[ "$BARE_PANEL" = yes ]   && sub "bare-metal panel    $PANEL_STATE"
[ "$DOCKER_NODE" != no ]  && sub "docker node         $DOCKER_DIR/data/node$([ "$DOCKER_NODE" = stale ] && echo '   (no container — data only)')"
[ "$DOCKER_PANEL" != no ] && sub "docker panel        $DOCKER_DIR/data/lib$([ "$DOCKER_PANEL" = stale ] && echo '   (no container — data only)')"
echo

info "Identity that must survive this move"
_n=0
for c in "$CONF_DIR"/*.conf /etc/wireguard/*.conf "$DOCKER_DIR/data/node-confs/"*.conf; do
  [ -f "$c" ] || continue; _n=$((_n+1))
  sub "interface $(b "$(basename "$c" .conf)")  server key in $c"
done
[ "$_n" = 0 ] && sub "no interface confs found — this node has none yet, or they are somewhere else"
for r in /opt/swg-wdtt "$DOCKER_DIR/data/node/wdtt"; do
  [ -d "$r" ] || continue
  for d in "$r"/*/; do [ -f "$d/wg-keys.dat" ] || continue
    sub "WDTT $(b "$(basename "$d")")  identity ${d%/}/wg-keys.dat  $(sha256sum "$d/wg-keys.dat" 2>/dev/null | cut -c1-16)…"; done
done
for r in /opt/swg-csqtt "$DOCKER_DIR/data/node/csqtt"; do
  [ -d "$r" ] || continue
  for d in "$r"/*/; do [ -f "$d/passwords.json" ] || continue
    sub "csqtt $(b "$(basename "$d")")  password store $d/passwords.json"; done
done
if [ -n "$NTOK" ]; then
  sub "node token        $(mask "$NTOK")   from $TOKSRC"
  sub "  panel           ${NURL:-?}${NEP:+   endpoint $NEP}"
  [ -n "$LOCAL_NODE_NAME" ] && sub "  this node is $(b "$LOCAL_NODE_NAME") in the panel on this box"
else
  warn "no enrolment token found — a node that re-enrols with a NEW token becomes a SECOND node on the panel,"
  warn "  and its peers stay on the old entry. Recover the token before you rebuild (Nodes → the node → Rotate"
  warn "  token gives you a fresh one for the SAME entry, which is the safe way to replace a lost one)."
fi
if [ -n "$TOKEN_OUT" ] && [ -n "$NTOK" ]; then
  if $DRYRUN; then echo "    [dry] write the token to $TOKEN_OUT (0600)"
  else ( umask 077; printf '%s\n' "$NTOK" > "$TOKEN_OUT" ) && ok "wrote the token to $(b "$TOKEN_OUT") (0600)" || warn "couldn't write $TOKEN_OUT"; fi
fi
echo

# ───────────────────────── what this pair needs ─────────────────────────
# The whole point of the table below: three of the four routes move NO data, because the native arm keeps
# bare-metal's paths and the container arm mounts whatever host dirs you point it at.
CARRY_NEEDED=no
if [ "$TO" = native ] && [ "$DOCKER_NODE" != no ]; then CARRY_NEEDED=yes; fi
if [ "$TO" = container ] && [ "$BARE_NODE" = yes ]; then
  # …unless the container arm is being pointed at the bare-metal paths it already uses, which is the default.
  { [ "$STATE_DIR" = /var/lib/swg-noded ] && [ -d /opt/swg-wdtt -o -d /opt/swg-csqtt -o -f /etc/swg-agent/turn-proxy.json ]; } && CARRY_NEEDED=yes
  [ "$STATE_DIR" != /var/lib/swg-noded ] && CARRY_NEEDED=yes
fi

info "What this route needs"
case "$TO:$FROM" in
  native:baremetal)
    sub "state: $(b "nothing moves"). The native arm keeps bare-metal's paths on purpose —"
    sub "  $CONF_DIR, /etc/wireguard, /etc/swg-agent, /var/lib/swg-noded, /opt/{vk-turn-proxy,swg-wdtt,swg-csqtt}"
    sub "  are already where the module expects them. (The module ASSERTS those two paths for that reason.)"
    ;;
  container:*docker*)
    sub "state: $(b "nothing moves"). Point the module at the dirs the compose stack already mounts:"
    sub "  services.swg-node.stateDir  = \"$DOCKER_DIR/data/node\";"
    sub "  services.swg-node.confDir   = \"$DOCKER_DIR/data/node-confs\";"
    sub "  services.swg-panel.stateDir = \"$DOCKER_DIR/data/lib\";  configDir = \"$DOCKER_DIR/data/etc\";"
    sub "  services.swg-panel.statsDir = \"$DOCKER_DIR/data/stats\"; subTlsDir = \"$DOCKER_DIR/data/sub-tls\";"
    ;;
  native:*docker*)
    sub "state: the $(b "cross-convention carry") — a native node is bare-metal's convention and its stateDir"
    sub "  cannot be moved (the module asserts /var/lib/swg-noded and $CONF_DIR)."
    sub "  --carry copies: node state (interface-key backups + routing lists), WDTT, csqtt, the turn record."
    sub "  Interface confs: $DOCKER_DIR/data/node-confs/*.conf → $CONF_DIR  (also --carry)."
    ;;
  container:baremetal)
    sub "state: the $(b "cross-convention carry") for the run-model-specific paths only."
    sub "  --carry copies: WDTT /opt/swg-wdtt → $STATE_DIR/wdtt, csqtt likewise, and the two records"
    sub "  (/etc/swg-agent/{wdtt,csqtt}.json → $STATE_DIR/) — a container node reads them from its state dir."
    [ "$STATE_DIR" = /var/lib/swg-noded ] && sub "  Everything else already IS $STATE_DIR — the container mounts the dir you already have."
    ;;
esac
if [ "$TO" = native ] && [ "$BARE_PANEL" = yes ]; then
  sub "panel: the native panel runs as $(b "swgpanel:swg") — accounts NixOS allocates its own ids for. Chown"
  sub "  the adopted state to them after the rebuild, or the panel refuses to start (it will not serve an"
  sub "  empty roster): chown -R swgpanel:swg $PANEL_STATE && chown -R root:swg /etc/swg-panel"
fi
echo

# ───────────────────────── the carry ─────────────────────────
if [ "$DO_CARRY" = yes ]; then
  info "Carrying state (copies — the originals are left exactly where they are)"
  if $DRYRUN; then
    echo "    [dry] to=$TO from=$FROM state-dir=$STATE_DIR conf-dir=$CONF_DIR docker-dir=$DOCKER_DIR"
  elif [ "$TO" = native ] && [ "$DOCKER_NODE" != no ]; then
    for c in "$DOCKER_DIR/data/node-confs/"*.conf; do
      [ -f "$c" ] || continue
      n="$(basename "$c")"
      if [ -f "$CONF_DIR/$n" ]; then sub "kept $(b "${n%.conf}") — $CONF_DIR/$n already exists (not overwritten)"; continue; fi
      mkdir -p "$CONF_DIR" && cp -a "$c" "$CONF_DIR/$n" && chmod 600 "$CONF_DIR/$n" \
        && echo "    interface $(b "${n%.conf}") (server key preserved) → $CONF_DIR/$n" \
        || warn "couldn't copy $c → $CONF_DIR/$n — that interface's SERVER KEY has not moved"
    done
    migrate_node_state  to-baremetal "$DOCKER_DIR"
    migrate_wdtt        to-baremetal "$DOCKER_DIR"
    migrate_csqtt       to-baremetal "$DOCKER_DIR"
    migrate_turn_record to-baremetal "$DOCKER_DIR"
    warn "turn-proxies: the record carried, but a bare-metal-convention node reads its turn set from the UNITS"
    warn "  on disk, and this script writes none. Re-create each proxy from the panel after the rebuild; the"
    warn "  carried record keeps its listen/connect/fork so you are re-entering nothing."
  elif [ "$TO" = container ] && [ "$BARE_NODE" = yes ]; then
    migrate_node_state  to-docker "" "$STATE_DIR"
    migrate_wdtt        to-docker "" "$STATE_DIR"
    migrate_csqtt       to-docker "" "$STATE_DIR"
    migrate_turn_record to-docker "" "$STATE_DIR"
    if [ "$CONF_DIR" != /etc/amnezia/amneziawg ]; then
      for c in /etc/amnezia/amneziawg/*.conf; do [ -f "$c" ] || continue
        mkdir -p "$CONF_DIR" && cp -a "$c" "$CONF_DIR/" && echo "    interface $(b "$(basename "$c" .conf)") → $CONF_DIR" \
          || warn "couldn't copy $c → $CONF_DIR — that interface's SERVER KEY has not moved"; done
    fi
    # Plain-WireGuard confs live in /etc/wireguard, which a container node never mounts — they have to join
    # the rest in confDir or those interfaces silently drop out of the managed set. (Same flattening the
    # bare→docker convert does; the entrypoint drives a conf without obfuscation keys perfectly well.)
    for c in /etc/wireguard/*.conf; do [ -f "$c" ] || continue
      n="$(basename "$c")"
      [ -f "$CONF_DIR/$n" ] && { sub "kept ${n%.conf} — $CONF_DIR/$n already exists"; continue; }
      mkdir -p "$CONF_DIR" && cp -a "$c" "$CONF_DIR/$n" && chmod 600 "$CONF_DIR/$n" \
        && echo "    plain-WireGuard interface $(b "${n%.conf}") → $CONF_DIR/$n" \
        || warn "couldn't copy $c → $CONF_DIR/$n — that interface's SERVER KEY has not moved"; done
  else
    sub "nothing to carry — both sides use the same paths. That is the design, not a skipped step."
  fi
  echo
elif [ "$CARRY_NEEDED" = yes ]; then
  warn "this route DOES need --carry (see above) — you have not run it yet"
  echo
fi

# ───────────────────────── the release ─────────────────────────
unit_dir_writable(){ local p="$SD/.swg-adopt-probe.$$"; ( : > "$p" ) 2>/dev/null || return 1; rm -f "$p"; return 0; }
if [ "$DO_RELEASE" = yes ]; then
  # Same probe, and the same reason, as uninstall.sh's guard: for root `[ -w ]` reports the mode bits and
  # ignores a read-only mount, so a declarative host would sail past it and every disable below would fail
  # while the script kept going.
  if ! $DRYRUN && [ -d "$SD" ] && ! unit_dir_writable; then
    die "$SD is read-only — this host is ALREADY declarative, so there are no imperative units to remove here.
    If a rebuild has already happened, the old units went with the old system. If swg is still running from
    /opt on this box, remove it before the rebuild, not after: that is the order this script exists to keep."
  fi
  info "Stopping and removing the imperative units — state is NOT touched"
  units=""
  for u in swg-noded swg-panel-server swg-sub; do [ -e "$SD/$u.service" ] && units="$units $u.service"; done
  for u in swg-netctl swg-update swg-netctl-docker; do
    for x in path timer service; do [ -e "$SD/$u.$x" ] && units="$units $u.$x"; done; done
  for f in "$SD"/swg-wdtt-*.service "$SD"/swg-csqtt-*.service "$SD"/vk-turn-proxy-*.service; do
    [ -e "$f" ] && units="$units $(basename "$f")"; done
  if [ -n "$units" ]; then
    stuck=""
    for u in $units; do
      if $DRYRUN; then echo "    [dry] systemctl disable --now $u; rm -f $SD/$u"; continue; fi
      systemctl disable --now "$u" >/dev/null 2>&1 || systemctl stop "$u" >/dev/null 2>&1 || true
      # ⚠️ Deleting a unit file whose service is still RUNNING is the exact shape of the bug that made
      # uninstall.sh refuse on a declarative host: `disable --now` fails, `--now` never reaches the stop,
      # and the script walks on and removes the file underneath a live process. So ask systemd what
      # actually happened rather than trusting the return code, and keep the file when the answer is
      # "still active" — a unit left in place is recoverable; one deleted out from under its process is not.
      if systemctl is-active --quiet "$u" 2>/dev/null; then
        stuck="$stuck $u"; warn "$u is STILL ACTIVE after disable --now — leaving its unit file in place"
        continue
      fi
      rm -f "$SD/$u"; sub "removed $(b "$u")"
    done
    $DRYRUN || rm -rf "$SD/swg-panel-server.service.d"
    $DRYRUN || systemctl daemon-reload >/dev/null 2>&1 || true
    [ -n "$stuck" ] && die "these units would not stop:$stuck
    Their files were kept, so nothing is running with its unit deleted. Stop them by hand and re-run
    --release; do NOT rebuild into the declarative arm while they hold their ports."
  else
    sub "no imperative swg units on this box"
  fi
  if [ "$DOCKER_NODE" = yes ] || [ "$DOCKER_PANEL" = yes ]; then
    # compose down, not `docker rm`: it takes the network and the swg-sub container with it. The swg-turn-*
    # containers are deliberately NOT touched — they are not compose-managed, they hold no compose state, and
    # a container node's own reconcile picks them straight back up from the carried record.
    if [ -f "$DOCKER_DIR/docker-compose.yml" ]; then
      if $DRYRUN; then echo "    [dry] (cd $DOCKER_DIR && docker compose down)"
      else ( cd "$DOCKER_DIR" && { docker compose down >/dev/null 2>&1 || docker-compose down >/dev/null 2>&1; } ) \
             && sub "stopped the compose stack ($DOCKER_DIR)" || warn "couldn't bring the compose stack down — do it by hand before the rebuild"; fi
    else
      for c in swg-node swg-panel swg-sub; do docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$c" && { run docker rm -f "$c" >/dev/null 2>&1 || true; sub "removed the $c container"; }; done
    fi
    # host netdevs outlive `compose down` (host networking), and they hold the ports the new arm needs.
    for c in "$DOCKER_DIR/data/node-confs/"*.conf; do [ -f "$c" ] || continue
      run ip link delete dev "$(basename "$c" .conf)" >/dev/null 2>&1 || true; done
  fi
  echo
  ok "units released. NOT touched, on purpose: $(b "every byte of state") — interface confs, /var/lib/swg-noded,"
  echo "   /etc/swg-agent, /opt/swg-{wdtt,csqtt}, /opt/vk-turn-proxy, the panel's roster, and the docker data dir."
  echo "   The panel was NOT told this node is going away (no /api/node/goodbye): it must keep this node's entry,"
  echo "   its peers and its token hash, or the box comes back as a stranger."
  echo
fi

# ───────────────────────── what to declare ─────────────────────────
# Built line by line rather than as one heredoc with conditionals inside it: a `$( … <<EOF )` nested in a
# heredoc is exactly the construct that renders half a config when one branch is empty, and a config block
# that is quietly missing a line is the worst thing this script could hand someone.
p_(){ printf '%s\n' "$*"; }
info "Next: declare it, then rebuild"
echo
_tokfile="${TOKEN_OUT:-/run/secrets/swg-node-token}"
if [ "$BARE_NODE" = yes ] || [ "$DOCKER_NODE" != no ]; then
  p_ "  services.swg-node = {"
  p_ "    enable = true;"
  p_ "    delivery = \"$TO\";"
  p_ "    panelUrl = \"${NURL:-https://panel.example.org:8443}\";"
  p_ "    endpoint = \"${NEP:-203.0.113.10}\";            # what CLIENTS dial — unchanged, or every client moves"
  [ "$NVERIFY" = no ] && p_ "    verifyPanelTls = false;"
  [ -n "$NFP" ]       && p_ "    panelTlsFingerprint = \"$NFP\";"
  if [ "$TO" = container ]; then
    [ "$STATE_DIR" != /var/lib/swg-noded ]    && p_ "    stateDir = \"$STATE_DIR\";"
    [ "$CONF_DIR"  != /etc/amnezia/amneziawg ] && p_ "    confDir = \"$CONF_DIR\";"
  fi
  p_ "    # THE token this node already holds — never a newly minted one. \"Add a node\" mints a token for a"
  p_ "    # NEW entry: this box would come up as a second node and its peers would stay on the old one."
  if [ "$TO" = native ]; then p_ "    tokenFile = \"$_tokfile\";"
  else                        p_ "    environmentFile = \"/run/secrets/swg-node.env\";   # must define NODE_TOKEN=<that token>"; fi
  p_ "    # interfaces: leave UNSET. The confs already on disk are the interface set."
  p_ "  };"
fi
if [ "$BARE_PANEL" = yes ] || [ "$DOCKER_PANEL" != no ]; then
  echo
  p_ "  services.swg-panel = {"
  p_ "    enable = true;"
  p_ "    delivery = \"$TO\";"
  p_ "    domain = \"panel.example.org\";                 # the address this panel already advertises"
  p_ "    environmentFile = \"/run/secrets/swg-panel.env\";   # PANEL_PASSWORD=… — unused here: your existing login is kept"
  if [ "$TO" = container ] && [ "$DOCKER_PANEL" != no ]; then
    p_ "    stateDir = \"$DOCKER_DIR/data/lib\";"
    p_ "    configDir = \"$DOCKER_DIR/data/etc\";"
    p_ "    statsDir = \"$DOCKER_DIR/data/stats\";"
    p_ "    subTlsDir = \"$DOCKER_DIR/data/sub-tls\";"
  fi
  if [ "$TO" = native ] && [ "$DOCKER_PANEL" != no ]; then
    p_ "    stateDir = \"$DOCKER_DIR/data/lib\";      # or move these to the defaults; the module reads them where you say"
    p_ "    configDir = \"$DOCKER_DIR/data/etc\";"
    p_ "    statsDir = \"$DOCKER_DIR/data/stats\";"
  fi
  if [ -n "$LOCAL_NODE_NAME" ]; then
    p_ "    # master: the node co-located here. The NAME must be the one the panel already uses, or the"
    p_ "    # seeder enrols a second entry beside it instead of refreshing this one's token."
    p_ "    localNode = { enable = true; name = \"$LOCAL_NODE_NAME\"; tokenFile = \"$_tokfile\"; };"
  fi
  p_ "  };"
fi
echo
sub "then: $(b "nixos-rebuild switch") — and read nix/README.md § Moving an existing install onto NixOS for the two"
sub "checks that say it worked: the panel still shows ONE entry for this node, and each interface's public"
sub "key is the one it had before."
echo
