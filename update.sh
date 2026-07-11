#!/usr/bin/env bash
# update.sh — update an existing swg-panel install in place, from the latest GitHub code.
#
#   curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s update
#
# bootstrap.sh fetches the latest repo and runs this from it. It AUTO-DETECTS which
# components are installed — covering every shape (bare-metal host / master / node,
# docker host / master / node) — compares each one's installed version against the
# fetched one, and for any with an upgrade available PROMPTS whether to upgrade or skip.
# Config + state are preserved (fleet.json, users.json, nodes.json, auth, certs, .env).
#
# Flags:  --dry-run       show what it would do, change nothing
#         -y|--yes        upgrade everything available without prompting
#         -f|--force      re-apply even components already on the latest version
#         --no-components  swg only (panel/noded/agent + swg images) — skip ALL third-party: wg/awg datapath,
#                          docker engine AND turn-proxy servers (this is what the one-click panel update uses)
set -euo pipefail

DRYRUN=false; ASSUME_YES=false; FORCE=false; NO_COMPONENTS=false; NODE_ONLY=false
for a in "$@"; do case "$a" in
  --dry-run) DRYRUN=true;; -y|--yes) ASSUME_YES=true;; -f|--force) FORCE=true;;
  --no-components) NO_COMPONENTS=true;;
  --node-only) NODE_ONLY=true;;     # update ONLY the bare-metal node/agent — never the co-located panel/docker
esac; done
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PANEL_DIR="${PANEL_DIR:-/opt/swg-panel}"
SUB_DIR="${SUB_DIR:-/opt/swg-sub}"
AGENT_DIR="${AGENT_DIR:-/opt/swg-agent}"
NODED_DIR="${NODED_DIR:-/opt/swg-noded}"
DOCKER_DIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"

# colours FIRST — must be detected on the real tty BEFORE lc_init's tee redirect makes stdout a pipe (else
# [ -t 1 ] is false and the whole run prints uncoloured). The helper fns below resolve these vars at call time.
if { [ -t 1 ] || [ -n "${SWG_FORCE_COLOR:-}" ]; } && [ -z "${NO_COLOR:-}" ]; then BOLD=$'\033[1m'; RESET=$'\033[0m'; C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YEL=$'\033[33m'; C_RED=$'\033[31m'; C_BLUE=$'\033[38;5;39m'; C_BL=$'\033[38;5;33m'; C_BROWN=$'\033[38;5;130m'
else BOLD=""; RESET=""; C_CYAN=""; C_GREEN=""; C_YEL=""; C_RED=""; C_BLUE=""; C_BL=""; C_BROWN=""; fi

. "$SRC/lib/common.sh"   # lc_* lifecycle helpers (shared with the installers)
# signal "updating" → updated / aborted / failed for whichever this box is: a node (POST via its agent
# config) and/or a panel host (host_proc file). Best-effort; armed only when there's something to tell.
lc_emit_upd(){ [ -n "${LC_FILE:-}" ] && lc_emit_file "$1" "${2:-}"; [ -n "${LC_TOKEN:-}" ] && [ -n "${LC_URL:-}" ] && lc_emit_post "$1" "${2:-}"; return 0; }
if ! $DRYRUN; then
  # host_proc drives the PANEL header's update status. A node-only update (a co-located node self-updating)
  # must NOT touch it — otherwise updating just the node lights up "up to date" on the panel + every tile.
  ! $NODE_ONLY && [ -f "$PANEL_DIR/swg-panel-server" ] && [ -d /var/lib/swg-panel ] && LC_FILE=/var/lib/swg-panel/host_proc
  if [ -f /etc/swg-agent/config.json ]; then
    LC_URL="$(python3 -c 'import json;print((json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("url",""))' 2>/dev/null || true)"
    LC_TOKEN="$(python3 -c 'import json;print((json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("token",""))' 2>/dev/null || true)"
    LC_VERIFY="$(python3 -c 'import json;print("yes" if (json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("verify",True) else "no")' 2>/dev/null || echo no)"
  fi
  # docker deployment: the panel host_proc lives in ./data/lib, the node token/URL in .env (no bare-metal paths)
  if [ -z "${LC_FILE:-}" ] && [ -z "${LC_TOKEN:-}" ] && [ -d "$DOCKER_DIR" ] && [ -f "$DOCKER_DIR/.env" ]; then
    ! $NODE_ONLY && command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-panel && [ -d "$DOCKER_DIR/data/lib" ] && LC_FILE="$DOCKER_DIR/data/lib/host_proc"
    LC_TOKEN="$(sed -n 's/^NODE_TOKEN=//p' "$DOCKER_DIR/.env" 2>/dev/null | head -1 | tr -d '"')"
    LC_URL="$(sed -n 's/^PANEL_URL=//p' "$DOCKER_DIR/.env" 2>/dev/null | head -1 | tr -d '"')"
    LC_VERIFY="$(sed -n 's/^TLS_VERIFY=//p' "$DOCKER_DIR/.env" 2>/dev/null | head -1 | tr -d '"')"; LC_VERIFY="${LC_VERIFY:-no}"
    case "$LC_URL" in *//swg-panel|*//swg-panel/*|*//swg-panel:*)   # master: swg-panel isn't resolvable from the host → loopback
      LC_URL="$(printf '%s' "$LC_URL" | sed -E "s#^(https?://)[^/]+#\1127.0.0.1:$(sed -n 's/^PANEL_PORT=//p' "$DOCKER_DIR/.env" 2>/dev/null | head -1 | tr -d '"')#")"; LC_VERIFY=no ;; esac
  fi
  { [ -n "${LC_FILE:-}" ] || [ -n "${LC_TOKEN:-}" ]; } && lc_init update lc_emit_upd
fi

info(){ echo "${C_BLUE}▸${RESET} ${BOLD}$*${RESET}"; }   # ▸ light-blue, bold (universal action flag)
sub(){  echo "${C_BL}::${RESET} $*"; }                    # :: blue sub-item / progress detail
ok(){   echo "${C_GREEN}✓${RESET} $*"; }
warn(){ echo "${C_BROWN}!${RESET} $*" >&2; }
die(){  echo "${C_RED}✗ $*${RESET}" >&2; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }
run(){ if $DRYRUN; then echo "    [skip] $*"; else "$@"; fi; }
stamp(){ $DRYRUN || printf '%s\n' "$NEW_VER" > "$1/VERSION" 2>/dev/null || true; }
oldver(){ cat "$1/VERSION" 2>/dev/null || echo '?'; }
# current version of a docker component — read from the RUNNING container (the live image actually serving now),
# falling back to the staged $DOCKER_DIR/VERSION, then '?'. $1 = container name, $2 = VERSION path in the image.
docker_ver(){ local c="$1" path="$2" v=""
  have docker && v="$(docker exec "$c" cat "$path" 2>/dev/null | head -1 | tr -d '[:space:]')"
  [ -n "$v" ] || v="$(oldver "$DOCKER_DIR")"
  printf '%s' "${v:-?}"; }
# header line showing the installed version vs the latest, so it's clear whether an update is needed
ver_line(){ local label="$1" cur="$2"
  if [ -z "$cur" ] || [ "$cur" = "?" ]; then info "$label — latest is version $(col_v "$NEW_VER")"
  elif [ "$cur" = "$NEW_VER" ];          then info "$label — version $(col_v "$cur") ${C_GREEN}(up to date)${RESET}"
  else                                        info "$label — $(col_v "$cur") → $(col_v "$NEW_VER") ${C_BROWN}(update available)${RESET}"; fi; }
confirm(){ # confirm <prompt> -> 0 yes / 1 no.  --yes or no terminal => yes (you ran update on purpose)
  $ASSUME_YES && return 0
  local v
  if printf '  %s %s: ' "$1" "${C_BL}(Y/n)${RESET}" 2>/dev/null >/dev/tty && IFS= read -r v 2>/dev/null </dev/tty; then
    case "$v" in [Nn]*) return 1;; *) return 0;; esac
  else return 0; fi
}
# should_update <label> <dir> -> 0 proceed / 1 skip (prints up-to-date or skipped)
should_update(){ local label="$1" dir="$2" old; old="$(oldver "$dir")"
  if [ "$old" = "$NEW_VER" ] && ! $FORCE; then ok "$(col_l "$label"): already up to date ($NEW_VER)"; return 1; fi
  echo   # blank line before the y/n prompt
  if confirm "Upgrade $(col_l "$label") $(col_v "$old → $NEW_VER")?"; then DID_UPDATE=yes; return 0; fi
  warn "$label: skipped (still $old)"; return 1; }
col_l(){ printf '%s%s%s' "$BOLD" "$*" "$RESET"; }
col_v(){ printf '%s%s%s' "$C_BLUE" "$*" "$RESET"; }
# ── OS package check/update (apt — the scripts install wg/amneziawg via apt + the amnezia PPA, docker via
#    get.docker.com's apt repo). Version check is automatic; the upgrade itself asks y/n (empty line first). ──
APT_DONE=no
apt_refresh(){ [ "$APT_DONE" = yes ] && return 0; APT_DONE=yes; have apt-get && run apt-get update -qq 2>/dev/null || true; }
pkg_installed(){ dpkg-query -W -f='${Version}' "$1" 2>/dev/null | head -1; }   # installed version, or empty
pkg_candidate(){ apt-cache policy "$1" 2>/dev/null | sed -n 's/^[[:space:]]*Candidate:[[:space:]]*//p' | head -1; }
first_pkg(){ local p; for p in "$@"; do [ -n "$(pkg_installed "$p")" ] && { echo "$p"; return 0; }; done; return 1; }
# pkg_update <label> <pkg…> : auto-check the first installed pkg; prompt y/n only if a newer candidate exists
pkg_update(){ local label="$1"; shift; local pkg cur cand
  pkg="$(first_pkg "$@")" || return 0                     # none installed → nothing to do
  cur="$(pkg_installed "$pkg")"
  have apt-get || { ok "$(col_l "$label") ($pkg): $cur — manage with your package manager"; return 0; }
  [ "$APT_DONE" = yes ] || sub "refreshing the package index to check $(col_l "$label") ($pkg)…"   # apt-get update is slow + silent — say so
  apt_refresh; cand="$(pkg_candidate "$pkg")"
  if [ -z "$cand" ] || [ "$cand" = "$cur" ] || [ "$cand" = "(none)" ]; then ok "$(col_l "$label") ($pkg): already up to date ($cur)"; return 0; fi
  echo
  if confirm "Upgrade $(col_l "$label") ($pkg) $(col_v "$cur → $cand")?"; then
    info "updating $label ($pkg)"
    if run apt-get install -y --only-upgrade "$pkg"; then DID_UPDATE=yes; ok "$label updated ($cand)"; note "$label: ${cur} → ${cand}"
    else DID_FAIL=yes; warn "$label: upgrade failed"; note "$label: upgrade FAILED"; fi
  else warn "$label: skipped (still $cur)"; note "$label: unchanged ($cur)"; fi; }

NEW_VER="$(cat "$SRC/VERSION" 2>/dev/null || echo unknown)"
[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
found=0; DID_UPDATE=no; DID_FAIL=no   # DID_FAIL flips to yes on ANY component failure → partial-failure status + exit 1
# per-component outcome, printed as a summary at the end — so a multi-component box (e.g. a docker
# master AND a bare-metal node on the same host) clearly shows EVERY component was considered.
RESULTS=(); note(){ RESULTS+=("$*"); }
pan_seen=no; nod_seen=no; doc_seen=no

# ── detect this box's shape (method × role) → title + which checks to run ──
HAVE_BPAN=no; { ! $NODE_ONLY && [ -f "$PANEL_DIR/swg-panel-server" ]; } && HAVE_BPAN=yes
HAVE_BNODE=no; { [ -f "$NODED_DIR/swg-noded" ] || [ -f "$AGENT_DIR/swg-agent" ]; } && HAVE_BNODE=yes
HAVE_DOCK=no; DOCK_PROF=""
if ! $NODE_ONLY && [ -d "$DOCKER_DIR" ] && [ -f "$DOCKER_DIR/docker-compose.yml" ]; then
  HAVE_DOCK=yes
  DOCK_PROF="$(sed -n 's/^# .*profile: *//p' "$DOCKER_DIR/.env" 2>/dev/null | head -1)"
  if [ -z "$DOCK_PROF" ] && have docker; then
    _n="$(docker ps --format '{{.Names}}' 2>/dev/null || true)"
    case "$_n" in *swg-panel*) case "$_n" in *swg-node*) DOCK_PROF=master;; *) DOCK_PROF=host;; esac;; *swg-node*) DOCK_PROF=node;; esac
  fi
  DOCK_PROF="${DOCK_PROF:-host}"
fi
if [ "$HAVE_DOCK" = yes ]; then case "$DOCK_PROF" in master) _role=MASTER;; node) _role=NODE;; *) _role=HOST;; esac; TITLE="SWG DOCKER $_role UPDATE"
elif [ "$HAVE_BPAN" = yes ] && [ "$HAVE_BNODE" = yes ]; then TITLE="SWG BARE-METAL MASTER UPDATE"
elif [ "$HAVE_BPAN" = yes ]; then TITLE="SWG BARE-METAL PANEL UPDATE"
elif [ "$HAVE_BNODE" = yes ]; then TITLE="SWG BARE-METAL NODE UPDATE"
else TITLE="SWG UPDATE"; fi
# roles present (bare OR docker) → the "latest is version" header lines for swg components
_haspanel=no; { [ "$HAVE_BPAN" = yes ] || { [ "$HAVE_DOCK" = yes ] && [ "$DOCK_PROF" != node ]; }; } && _haspanel=yes
_hasnode=no;  { [ "$HAVE_BNODE" = yes ] || { [ "$HAVE_DOCK" = yes ] && [ "$DOCK_PROF" != host ]; }; } && _hasnode=yes
echo; info "$TITLE"
if $DRYRUN; then info "DRY RUN — nothing will change."; fi
echo
# current installed version per component (bare-metal reads its VERSION file; docker falls back to the staged
# $DOCKER_DIR/VERSION, '?' when unknown → just shows the latest)
_pcur="?"; if [ "$HAVE_BPAN" = yes ]; then _pcur="$(oldver "$PANEL_DIR")"; elif [ "$HAVE_DOCK" = yes ]; then _pcur="$(docker_ver swg-panel /opt/swg-panel/VERSION)"; fi
_ncur="?"; if [ "$HAVE_BNODE" = yes ]; then _ncur="$(oldver "$NODED_DIR")"; elif [ "$HAVE_DOCK" = yes ]; then _ncur="$(docker_ver swg-node /opt/swg-noded/VERSION)"; fi
[ "$_haspanel" = yes ] && ver_line "swg-panel" "$_pcur"
[ "$_hasnode" = yes ]  && ver_line "swg-node" "$_ncur"
true   # don't let the above &&-tests leave a non-zero status for `set -e`

# Auto-clear an inert leftover that an aborted conversion to the OTHER method left behind (no prompt — it's
# just an outdated copy). The helper's guards never touch a live install or an unrelated WireGuard config.
if ! $DRYRUN; then
  if   [ "$HAVE_DOCK" = yes ]; then                               lc_clear_convert_leftover docker    "$DOCKER_DIR"
  elif [ "$HAVE_BNODE" = yes ] || [ "$HAVE_BPAN" = yes ]; then    lc_clear_convert_leftover baremetal "$DOCKER_DIR"; fi
fi

install_update_unit(){   # idempotent: wire one-click host self-update for an existing bare-metal panel.
  # MUST stay identical to install-host.sh's mk_update_unit. The design is a STAMP-GUARDED swg-update-check
  # (only updates when a trigger file is NEWER than the last-handled stamp), polled by swg-update.timer.
  # NEVER point swg-update.service straight at /usr/local/bin/swg-update or wire a swg-update.path: that was
  # the old design, and because the timer fires the service every 20s, an unguarded service re-ran the whole
  # installer every 20s forever (an endless update loop). update.sh runs on EVERY update, so a divergence
  # here silently re-introduced the loop on already-fixed hosts.
  local st="${STATE_DIR:-/var/lib/swg-panel}" usr="${PANEL_USER:-swgpanel}" trig
  trig="${st}/.update-request"
  if $DRYRUN; then echo "    [skip] install /usr/local/bin/swg-update{,-check} + swg-update.{service,timer} + trigger drop-in"; return 0; fi
  cat > /usr/local/bin/swg-update <<'WRAP'
#!/usr/bin/env bash
# swg-update — fixed root entrypoint for one-click in-place update (swg programs only).
set -euo pipefail
URL="${SWG_BOOTSTRAP_URL:-https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh}"
curl -fsSL "$URL" | bash -s update -y --no-components "$@"   # extra flags (e.g. --node-only) pass through
WRAP
  chmod 755 /usr/local/bin/swg-update
  cat > /usr/local/bin/swg-update-check <<'WRAP2'
#!/usr/bin/env bash
set -euo pipefail
STAMP=/var/lib/swg-update.stamp
PANEL_TRIGGERS="/var/lib/swg-panel/.update-request /opt/swg-panel-docker/data/lib/.update-request"
NODE_TRIGGERS="/var/lib/swg-noded/.update-request /opt/swg-panel-docker/data/node/.update-request"
_run=no; _panel=no
for _t in $PANEL_TRIGGERS $NODE_TRIGGERS; do
  [ -f "$_t" ] || continue
  if { [ ! -e "$STAMP" ] || [ "$_t" -nt "$STAMP" ]; }; then
    _run=yes
    case " $PANEL_TRIGGERS " in *" $_t "*) _panel=yes;; esac   # a PANEL trigger → this is a host update
  fi
done
[ "$_run" = yes ] || exit 0
touch "$STAMP"            # mark this batch handled BEFORE updating, so we never loop
if [ "$_panel" = yes ]; then exec /usr/local/bin/swg-update
else exec /usr/local/bin/swg-update --node-only; fi
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
Description=poll for a swg one-click update request

[Timer]
OnActiveSec=30s
OnUnitActiveSec=30s

[Install]
WantedBy=timers.target
EOF
  rm -f /etc/systemd/system/swg-update.path   # retire the legacy inotify watch that drove the loop
  [ -e "$trig" ] || : > "$trig"   # create when MISSING — re-writing content would fire a spurious self-update
  chown "$usr:swg" "$trig" 2>/dev/null || true; chmod 660 "$trig" 2>/dev/null || true   # ALWAYS re-assert ownership so the panel can write it even if a convert/older root process left it root-owned
  # point the (already-installed) panel at the trigger via a drop-in — don't edit the main unit
  install -d /etc/systemd/system/swg-panel-server.service.d
  printf '[Service]\nEnvironment=SWG_UPDATE_TRIGGER=%s\n' "$trig" \
    > /etc/systemd/system/swg-panel-server.service.d/zz-swg-update.conf
  touch /var/lib/swg-update.stamp   # stamp AFTER the trigger so THIS update (its trigger is now older) doesn't re-fire
  systemctl daemon-reload
  systemctl disable --now swg-update.path >/dev/null 2>&1 || true
  systemctl enable --quiet --now swg-update.timer >/dev/null 2>&1 || warn "couldn't enable swg-update.timer"
}

# ───────────────────────── bare-metal panel (host or master) ─────────────────────────
if ! $NODE_ONLY && [ -f "$PANEL_DIR/swg-panel-server" ]; then
  found=1; pan_seen=yes; pold="$(oldver "$PANEL_DIR")"
  if should_update "bare-metal swg-panel" "$PANEL_DIR"; then
    info "updating bare-metal swg-panel ($PANEL_DIR)"
    for f in swg-panel-server index.html app.css app.js reconcile.js turn-artifacts.js; do
      [ -f "$SRC/$f" ] && run cp "$SRC/$f" "$PANEL_DIR/"
    done
    # whole vendor/ dir — the buildless SPA needs the vendored Preact + htm ESM, not just qrcode
    [ -d "$SRC/vendor" ] && { run mkdir -p "$PANEL_DIR/vendor"; run cp -a "$SRC/vendor/." "$PANEL_DIR/vendor/"; }
    run chmod 755 "$PANEL_DIR/swg-panel-server"; stamp "$PANEL_DIR"
    install_update_unit                              # ensure one-click host self-update is wired
    if run systemctl restart swg-panel-server; then ok "swg-panel updated + restarted"; note "bare-metal swg-panel: ${pold} → ${NEW_VER}"
    else DID_FAIL=yes; warn "couldn't restart swg-panel-server"; note "bare-metal swg-panel: updated but RESTART FAILED"; fi
    # swg-sub (the subscription surface) ships with the panel. Refresh it in place when already installed —
    # first-time provisioning (binary + unit) is done by install-host.sh. Inert unless enabled in the panel.
    if [ -f "$SUB_DIR/swg-sub" ] && [ -f "$SRC/swg-sub" ]; then
      run cp "$SRC/swg-sub" "$SUB_DIR/"; run chmod 755 "$SUB_DIR/swg-sub"
      for f in sub.html sub.js sub.css turn-artifacts.js; do [ -f "$SRC/$f" ] && run cp "$SRC/$f" "$SUB_DIR/"; done
      [ -f "$SRC/vendor/qrcode.js" ] && { run mkdir -p "$SUB_DIR/vendor"; run cp "$SRC/vendor/qrcode.js" "$SUB_DIR/vendor/"; }
      stamp "$SUB_DIR"
      run systemctl restart swg-sub 2>/dev/null && ok "swg-sub updated + restarted" || warn "swg-sub present but not restarted"
    fi
    # swg-netctl (privileged network/TLS helper) — refresh the binary in place when already installed
    # (first-time provisioning of the binary + trigger units is done by install-host.sh).
    if [ -f /usr/local/bin/swg-netctl ] && [ -f "$SRC/swg-netctl" ]; then
      run cp "$SRC/swg-netctl" /usr/local/bin/swg-netctl; run chmod 755 /usr/local/bin/swg-netctl; ok "swg-netctl refreshed"
    fi
  else note "bare-metal swg-panel: unchanged (${pold})"; fi
fi

# ───────────────────────── bare-metal node daemon (node or master) ─────────────────────────
if [ -f "$NODED_DIR/swg-noded" ] || [ -f "$AGENT_DIR/swg-agent" ]; then
  found=1; nod_seen=yes; nold="$(oldver "$NODED_DIR")"
  if should_update "bare-metal swg-node" "$NODED_DIR"; then
    info "updating bare-metal swg-node ($AGENT_DIR + $NODED_DIR)"
    [ -d "$AGENT_DIR" ] && [ -f "$SRC/swg-agent" ] && { run cp "$SRC/swg-agent" "$AGENT_DIR/"; run chmod 755 "$AGENT_DIR/swg-agent"; }
    [ -d "$NODED_DIR" ] && [ -f "$SRC/swg-noded" ] && { run cp "$SRC/swg-noded" "$NODED_DIR/"; run chmod 755 "$NODED_DIR/swg-noded"; }
    [ -d "$NODED_DIR" ] && [ -f "$SRC/swg-sni" ] && { run cp "$SRC/swg-sni" "$NODED_DIR/"; run chmod 755 "$NODED_DIR/swg-sni"; }   # SNI-router classifier
    stamp "$NODED_DIR"
    if run systemctl restart swg-noded; then ok "swg-node updated + restarted"; note "bare-metal swg-node: ${nold} → ${NEW_VER}"
    else DID_FAIL=yes; warn "couldn't restart swg-noded — run: systemctl restart swg-noded"; note "bare-metal swg-node: updated but RESTART FAILED"; fi
  else note "bare-metal swg-node: unchanged (${nold})"; fi
fi

# ───────────────────────── Docker (host / node / master) ─────────────────────────
if ! $NODE_ONLY && [ -d "$DOCKER_DIR" ] && [ -f "$DOCKER_DIR/docker-compose.yml" ]; then
  found=1; doc_seen=yes
  # which profile is running? prefer the marker install-docker.sh wrote into .env, else sniff containers
  prof="$(sed -n 's/^# .*profile: *//p' "$DOCKER_DIR/.env" 2>/dev/null | head -1)"
  if [ -z "$prof" ] && have docker; then
    names="$(docker ps --format '{{.Names}}' 2>/dev/null || true)"
    case "$names" in *swg-panel*) case "$names" in *swg-node*) prof=master;; *) prof=host;; esac;; *swg-node*) prof=node;; esac
  fi
  prof="${prof:-host}"   # older installs may carry a host-node marker — compose keeps it as a master alias
  if have docker && docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE="docker-compose"; fi
  # Force-DNS DNATs a client's :53 to the node's loopback dnsmasq, which needs net.ipv4.conf.all.route_localnet=1.
  # A host-net container can't set it (read-only /proc/sys) and pre-fix installs never persisted it → repair it on
  # the HOST here so an update un-breaks Force-DNS on existing nodes. Idempotent; node-bearing profiles only.
  case "$prof" in node|master|host-node)
    if ! $DRYRUN; then
      grep -qs route_localnet /etc/sysctl.d/99-swg-node.conf 2>/dev/null || printf 'net.ipv4.conf.all.route_localnet = 1\n' >> /etc/sysctl.d/99-swg-node.conf 2>/dev/null || true
      sysctl -w net.ipv4.conf.all.route_localnet=1 >/dev/null 2>&1 || true
    fi ;;
  esac
  # migrate existing docker panels: the panel matches a master's co-located node by the HOST hostname, which it
  # only learns via SWG_HOST_HOSTNAME — older .env/compose lack it (an update doesn't restage the compose), so add it.
  case "$prof" in host|master|host-node)
    if ! $DRYRUN && ! grep -q '^SWG_HOST_HOSTNAME=' "$DOCKER_DIR/.env" 2>/dev/null; then printf 'SWG_HOST_HOSTNAME=%s\n' "$(hostname 2>/dev/null)" >> "$DOCKER_DIR/.env"; fi
    if ! $DRYRUN && ! grep -q 'SWG_HOST_HOSTNAME' "$DOCKER_DIR/docker-compose.yml" 2>/dev/null; then
      python3 - "$DOCKER_DIR/docker-compose.yml" <<'PYHN' && note "docker-compose.yml: added SWG_HOST_HOSTNAME (co-located node detection)"
import sys
f=sys.argv[1]; o=[]
for l in open(f).read().split("\n"):
    o.append(l)
    if "SWG_UPDATE_TRIGGER:" in l and "${SWG_UPDATE_TRIGGER" in l: o.append('      SWG_HOST_HOSTNAME: "${SWG_HOST_HOSTNAME:-}"')
open(f,"w").write("\n".join(o))
PYHN
    fi ;;
  esac
  if grep -qE '^[[:space:]]*build:' "$DOCKER_DIR/docker-compose.yml" 2>/dev/null; then
    # build-from-source deployment → restage the source and rebuild (don't touch the user's compose/.env)
    if should_update "docker ($prof, source build)" "$DOCKER_DIR"; then
      info "restaging source + rebuilding ($DOCKER_DIR)"
      for f in Dockerfile Dockerfile.node Dockerfile.turn .dockerignore VERSION \
               swg-panel-server swg-agent swg-noded index.html app.css app.js reconcile.js; do
        [ -e "$SRC/$f" ] && run cp -a "$SRC/$f" "$DOCKER_DIR/"
      done
      [ -d "$SRC/vendor" ] && run cp -a "$SRC/vendor" "$DOCKER_DIR/"
      [ -d "$SRC/docker" ] && run cp -a "$SRC/docker" "$DOCKER_DIR/"; stamp "$DOCKER_DIR"
      if $DRYRUN; then echo "    [skip] (cd $DOCKER_DIR && $COMPOSE --profile $prof up -d --build)"; note "docker ($prof): would rebuild"
      else ( cd "$DOCKER_DIR" && on_tty $COMPOSE --profile "$prof" up -d --build ) && { ok "docker ($prof) rebuilt + restarted"; note "docker ($prof): rebuilt"; } || { DID_FAIL=yes; warn "compose rebuild failed — check $DOCKER_DIR"; note "docker ($prof): rebuild FAILED"; }; fi
    else note "docker ($prof): unchanged"; fi
  else
    # prebuilt-image deployment (default) → just pull the newest image + recreate (no restaging)
    echo
    if confirm "Pull the latest image for $(col_l "docker ($prof)")?"; then
      DID_UPDATE=yes; info "pulling latest image + recreating ($DOCKER_DIR)"
      if $DRYRUN; then echo "    [skip] (cd $DOCKER_DIR && $COMPOSE --profile $prof pull && $COMPOSE --profile $prof up -d --force-recreate)"; note "docker ($prof): would pull + recreate"
      # --force-recreate: after `pull` updates :latest, a plain `up -d` may just (re)start the EXISTING
      # container on the OLD image (log shows "Started", not "Recreated") — so the node keeps the old
      # version until a 2nd run. Forcing recreation guarantees it runs the freshly-pulled image.
      else
        for _c in $(case "$prof" in node) echo swg-node;; host) echo swg-panel;; *) echo swg-panel swg-node;; esac); do docker ps -aq -f "name=$_c" 2>/dev/null | xargs -r docker rm -f >/dev/null 2>&1 || true; done   # drop any half-recreated/leftover container so `up` can't hit "container name already in use"
        ( cd "$DOCKER_DIR" && on_tty $COMPOSE --profile "$prof" pull && on_tty $COMPOSE --profile "$prof" up -d --force-recreate ) && { ok "docker ($prof) image pulled + recreated"; note "docker ($prof): image pulled + recreated"; } || { DID_FAIL=yes; warn "compose pull/up failed — check $DOCKER_DIR"; note "docker ($prof): pull/up FAILED"; }; fi
    else warn "docker ($prof): skipped"; note "docker ($prof): skipped"; fi
  fi
fi

# ───────────────────────── WireGuard / AmneziaWG datapath ─────────────────────────
# bare-metal node → the system package (amneziawg via the amnezia PPA, or wireguard). docker node → the
# datapath (amneziawg-go) lives in the swg-node image and refreshes with the image pull above.
if $NO_COMPONENTS && [ "$HAVE_BNODE" = yes ]; then
  ok "$(col_l "WireGuard / AmneziaWG"): skipped — third-party datapath (--no-components: swg programs only)"
elif [ "$HAVE_BNODE" = yes ]; then
  pkg_update "WireGuard / AmneziaWG" amneziawg amneziawg-tools amneziawg-dkms wireguard wireguard-tools
elif [ "$HAVE_DOCK" = yes ] && [ "$DOCK_PROF" != host ]; then
  ok "$(col_l "WireGuard / AmneziaWG"): bundled in the swg-node image — no separate package to update (it tracks the image)"
fi

# ───────────────────────── Docker engine (docker scenario only) ─────────────────────────
if [ "$HAVE_DOCK" = yes ] && $NO_COMPONENTS; then
  ok "$(col_l "Docker engine"): skipped — third-party (--no-components: swg programs only)"
elif [ "$HAVE_DOCK" = yes ]; then
  pkg_update "Docker engine" docker-ce docker.io
fi

# ───────────────────────── turn-proxy servers (vk-turn-proxy, ones we installed) ─────────────────────────
# Current layout: ONE shared binary per fork in .bin/<fork>/ (server + version.txt + repo.txt); each instance
# dir is just turn.env + a 'server' SYMLINK into it. Older installs instead carried a real binary + version.txt
# in the instance dir itself. Check each shared fork once (restarting all its RUNNING instances) plus any legacy
# standalone instance — so every turn-proxy is covered on both layouts (the old loop missed the shared ones).
TURN_DIR="${TURN_DIR:-/opt/vk-turn-proxy}"
turn_check_one(){   # <key> <dir/ holding server+version.txt+repo.txt> <fork|inst>
  local key="$1" d="$2" mode="$3" owner cur latest arch url u svc any=no restart_ok=yes
  owner="$(cat "${d}repo.txt" 2>/dev/null || echo '?')"; cur="$(cat "${d}version.txt" 2>/dev/null || echo '?')"
  if $DRYRUN; then latest="v0.0.0-latest"
  else sub "checking turn-proxy $(col_l "$key") ($owner) for a newer release on GitHub…"   # network call — say so (and cap it) so it never looks hung
    latest="$(curl -fsSL --connect-timeout 10 --max-time 20 "https://api.github.com/repos/$owner/releases/latest" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("tag_name",""))' 2>/dev/null || true)"; fi
  [ -n "$latest" ] || { warn "turn-proxy $key ($owner): couldn't reach GitHub for the latest release — skipping"; return; }
  if [ "$cur" = "$latest" ] && ! $FORCE; then ok "$(col_l "turn-proxy $key") ($owner): already up to date ($cur)"; return; fi
  echo
  if confirm "Upgrade $(col_l "turn-proxy $key") ($owner) $(col_v "$cur → $latest")?"; then
    DID_UPDATE=yes
    case "$(uname -m)" in x86_64|amd64) arch=amd64;; aarch64|arm64) arch=arm64;; *) arch=amd64;; esac
    url="https://github.com/$owner/releases/latest/download/server-linux-$arch"
    info "updating turn-proxy $key ($owner)"
    if run curl -fsSL "$url" -o "${d}server.new" && run chmod +x "${d}server.new" && run mv "${d}server.new" "${d}server"; then
      $DRYRUN || printf '%s\n' "$latest" > "${d}version.txt"
      # restart the RUNNING instance(s) to pick up the new binary — try-restart never STARTS a stopped one
      if [ "$mode" = fork ]; then
        for u in /etc/systemd/system/vk-turn-proxy-"$key"-*.service; do [ -e "$u" ] || continue; any=yes
          svc="$(basename "$u" .service)"; run systemctl try-restart "$svc" || restart_ok=no; done
      else any=yes; run systemctl try-restart "vk-turn-proxy-$key" || restart_ok=no; fi
      if   [ "$any" = no ];          then ok "turn-proxy $key updated (no running instance to restart)"
      elif [ "$restart_ok" = yes ];  then ok "turn-proxy $key updated + restarted"
      else DID_FAIL=yes; warn "couldn't restart vk-turn-proxy-$key"; note "turn-proxy $key: updated but RESTART FAILED"; fi
    else DID_FAIL=yes; warn "turn-proxy $key: download failed ($url)"; note "turn-proxy $key: download FAILED"; fi
  else warn "turn-proxy $key: skipped (still $cur)"; fi
}
if $NO_COMPONENTS && [ -d "$TURN_DIR" ]; then
  info "skipping third-party components (turn-proxy servers) — --no-components"
elif [ -d "$TURN_DIR" ]; then
  for d in "$TURN_DIR"/.bin/*/; do   # shared fork binaries (current layout) — restart all the fork's instances
    [ -f "${d}server" ] && [ -f "${d}version.txt" ] || continue
    found=1; turn_check_one "$(basename "$d")" "$d" fork
  done
  for d in "$TURN_DIR"/*/; do        # legacy standalone instances (own REAL binary, not a symlink into .bin)
    [ -f "${d}server" ] && [ ! -L "${d}server" ] && [ -f "${d}version.txt" ] || continue
    found=1; turn_check_one "$(basename "$d")" "$d" inst
  done
fi

[ "$found" = 1 ] || die "no swg-panel install found (looked in $PANEL_DIR, $NODED_DIR, $DOCKER_DIR, $TURN_DIR)"
# call out swg components that weren't present, so a partial-looking run is never a mystery
[ "$pan_seen" = yes ] || note "bare-metal swg-panel: not installed ($PANEL_DIR)"
[ "$nod_seen" = yes ] || note "bare-metal swg-node: not installed ($NODED_DIR)"
[ "$doc_seen" = yes ] || note "docker: not installed ($DOCKER_DIR)"
# lifecycle terminal:
#  · a component FAILED → don't emit a success state; exit 1 below so the lc EXIT trap reports "update-failed"
#    (with the captured log tail), even if other components updated fine (partial failure still = failure).
#  · nothing changed + no failure → green "up to date" (5 s).
#  · something updated, no failure → the lc EXIT trap emits "updated" on the clean exit 0.
if [ "$DID_FAIL" = no ] && [ "$DID_UPDATE" = no ]; then lc_emit uptodate; lc_handoff; fi
echo
if   [ "$DID_FAIL" = yes ]; then echo "${C_RED}✗${RESET} Update finished with errors — some components FAILED (see the summary below)."
elif [ "$DID_UPDATE" = no ]; then ok "Update finished — nothing changed."
else                              ok "Update complete."; fi
if [ "${#RESULTS[@]}" -gt 0 ]; then   # only ACTUAL changes — drop the inventory notes (absent / unchanged / skipped components aren't "changes")
  _chg=(); for r in "${RESULTS[@]}"; do case "$r" in *"not installed"*|*unchanged*|*skipped*) :;; *) _chg+=("$r");; esac; done
  if [ "${#_chg[@]}" -gt 0 ]; then echo; info "Components changed this run:"; for r in "${_chg[@]}"; do echo "    • $r"; done; fi
fi
[ "$DID_FAIL" = no ] && ! $DRYRUN && print_summary UPDATE   # then the unified per-server summary (same shape as install / convert)
if $DRYRUN; then ok "DRY RUN done — nothing changed."; fi
if [ "$DID_FAIL" = yes ]; then exit 1; fi   # non-zero → the lc EXIT trap reports "update-failed" with the log tail
exit 0   # all good — status 0 so the trap reports "updated" (or the uptodate handoff above stands)
