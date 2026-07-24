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
  DOCK_PROF="$(sed -n 's/^# .*profile: *//p' "$DOCKER_DIR/.env" 2>/dev/null | head -1 || true)"   # || true: .env may be absent (compose present) → don't abort before the fallback below
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

ensure_netctl_helper(){   # idempotent: provision the swg-netctl root helper when a bare-metal panel LACKS it.
  # The panel is unprivileged and can't touch the host itself — it drops JSON requests into a queue the root
  # helper drains (systemd .path watch + a 10s .timer fallback). Installs that predate the helper (it shipped
  # with the Access/subscription-address feature) or partial installs have no helper at all, so every Access or
  # subscription-address change fails with "the root helper is not available", and the version-gated refresh
  # below never healed it (it only runs when /usr/local/bin/swg-netctl already exists). Provision the whole thing
  # here, unconditionally, so an update repairs such boxes. MUST mirror install-host.sh's write_netctl.
  [ -f "$SRC/swg-netctl" ] || return 0
  local st="${STATE_DIR:-/var/lib/swg-panel}" etc="${ETC_DIR:-/etc/swg-panel}" usr="${PANEL_USER:-swgpanel}"
  # already complete? (binary + queue dir + both trigger units) → nothing to do; the refresh path keeps it current.
  if [ -f /usr/local/bin/swg-netctl ] && [ -d "$st/netctl/queue" ] \
     && [ -f /etc/systemd/system/swg-netctl.path ] && [ -f /etc/systemd/system/swg-netctl.timer ]; then return 0; fi
  info "provisioning the swg-netctl root helper (missing/incomplete — needed for Access & subscription-address changes)"
  if $DRYRUN; then echo "    [skip] install /usr/local/bin/swg-netctl + ${st}/netctl/{queue,status} + swg-netctl.{service,path,timer}"; return 0; fi
  cp "$SRC/swg-netctl" /usr/local/bin/swg-netctl; chmod 755 /usr/local/bin/swg-netctl
  # queue/ — panel-owned so ONLY the panel can enqueue; status/ — root-written, group-readable by the panel.
  mkdir -p "$st/netctl/queue" "$st/netctl/status"
  chown "$usr:swg" "$st/netctl" "$st/netctl/queue" 2>/dev/null || true; chmod 750 "$st/netctl" "$st/netctl/queue"
  chown root:swg "$st/netctl/status" 2>/dev/null || true; chmod 750 "$st/netctl/status"
  cat > /etc/systemd/system/swg-netctl.service <<EOF
[Unit]
Description=swg-panel privileged network/TLS helper (drains the panel's request queue)
# A single Access apply enqueues several requests in a row; the default 5-starts-per-10s limit trips easily and
# would fail the .path unit permanently. This drainer is MEANT to start frequently, so disable the rate limit.
StartLimitIntervalSec=0

[Service]
Type=oneshot
ExecStart=/usr/local/bin/swg-netctl run
Environment=SWG_PANEL_USER=${usr}
Environment=SWG_PANEL_GROUP=swg
Environment=SWG_STATE_DIR=${st}
Environment=SWG_ETC_DIR=${etc}
EOF
  cat > /etc/systemd/system/swg-netctl.path <<EOF
[Unit]
Description=watch for swg-netctl requests from the panel

[Path]
DirectoryNotEmpty=${st}/netctl/queue
Unit=swg-netctl.service

[Install]
WantedBy=paths.target
EOF
  cat > /etc/systemd/system/swg-netctl.timer <<EOF
[Unit]
Description=poll for swg-netctl requests (fallback for the path watch)

[Timer]
OnActiveSec=10s
OnUnitActiveSec=10s

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --quiet --now swg-netctl.path 2>/dev/null || warn "couldn't enable swg-netctl.path"
  systemctl enable --quiet --now swg-netctl.timer 2>/dev/null || warn "couldn't enable swg-netctl.timer"
  ok "swg-netctl root helper provisioned — Access & subscription-address changes will work now"
}

ensure_sub_server(){   # HEAL (install-if-missing) the swg-sub subscription surface on a bare-metal panel.
  # swg-sub is the public, read-only per-user QR/config page. The panel drives it over swg-netctl
  # (set-listen / restart swg-sub.service), so a panel with NO unit can't bind or rebind it — Settings →
  # Subscriptions then fails with "couldn't bind the subscription server …" and rolls back. Installs that
  # predate swg-sub, or partial ones that dropped the files/user/unit, have no service at all, and the
  # version-gated refresh below only touches an already-present binary.
  #   HEAL CONTRACT (see the heal-section banner): install ONLY the pieces that are MISSING, never rewrite
  #   or re-copy one that exists — writing the base unit when it's already there would clobber the panel's
  #   set-listen drop-in — then enable so it survives a reboot. Piece templates MUST mirror install-host.sh's
  #   swg-sub install + write_sub_unit. Inert until enabled in the panel (the surface 404s until then).
  [ -f "$SRC/swg-sub" ] || return 0
  local st="${STATE_DIR:-/var/lib/swg-panel}" etc="${ETC_DIR:-/etc/swg-panel}" tls="${TLS_DIR:-/etc/swg-panel/tls}"
  local subusr="${SUB_USER:-swgsub}" subport="${SUB_PORT:-8444}" subbind="${SUB_BIND:-0.0.0.0}"
  local unit=/etc/systemd/system/swg-sub.service
  # fully present? leave every file exactly as-is; only make sure it's enabled for reboot, then stop.
  if [ -f "$SUB_DIR/swg-sub" ] && id "$subusr" >/dev/null 2>&1 && [ -f "$unit" ]; then
    $DRYRUN || systemctl is-enabled --quiet swg-sub 2>/dev/null || systemctl enable --quiet swg-sub 2>/dev/null || true
    return 0
  fi
  info "healing the swg-sub subscription surface (installing missing pieces — needed for Settings → Subscriptions)"
  if $DRYRUN; then echo "    [skip] install whichever is MISSING: user ${subusr} · ${SUB_DIR}/swg-sub · /etc/swg-sub/tls · ${unit} (then enable --now)"; return 0; fi
  # swg-sub's OWN unprivileged user (group swg, read-only) — NOT the panel user. useradd sets home+group, so
  # a freshly-made user needs no follow-up; an existing one we leave exactly as the operator has it.
  id "$subusr" >/dev/null 2>&1 || useradd -r -g swg -d "$SUB_DIR" -s /usr/sbin/nologin "$subusr" 2>/dev/null || true
  if [ ! -f "$SUB_DIR/swg-sub" ]; then    # binary missing → lay down the binary + any missing web assets
    mkdir -p "$SUB_DIR/vendor"
    cp "$SRC/swg-sub" "$SUB_DIR/"; chmod 755 "$SUB_DIR/swg-sub"
    for f in sub.html sub.js sub.css turn-artifacts.js; do [ -f "$SUB_DIR/$f" ] || { [ -f "$SRC/$f" ] && cp "$SRC/$f" "$SUB_DIR/"; }; done
    [ -f "$SUB_DIR/vendor/qrcode.js" ] || { [ -f "$SRC/vendor/qrcode.js" ] && cp "$SRC/vendor/qrcode.js" "$SUB_DIR/vendor/"; }
    [ -f "$SUB_DIR/VERSION" ] || stamp "$SUB_DIR"
  fi
  # swg-sub's OWN TLS dir — its cert lives here (never the panel's key). Root writes it, group swg reads.
  [ -d /etc/swg-sub/tls ] || { mkdir -p /etc/swg-sub/tls; chown root:swg /etc/swg-sub/tls 2>/dev/null || true; chmod 750 /etc/swg-sub/tls; }
  if [ ! -f "$unit" ]; then                # unit missing → write it (a separate FILE, so it never disturbs
    local subextra=""                      # the panel's set-listen 10-access drop-in). This is the only
    [ "$subport" -lt 1024 ] 2>/dev/null && subextra="AmbientCapabilities=CAP_NET_BIND_SERVICE
"                                          # thing we CREATE here; host/port below is the pre-reconcile fallback.
  # served as PLAIN HTTP behind the operator's TLS (reverse proxy / Cloudflare) or swg-sub's own cert; it
  # deliberately never reuses the panel's TLS key.
  cat > "$unit" <<EOF
[Unit]
Description=swg-sub subscription surface (public, read-only)
After=network.target

[Service]
Type=simple
User=${subusr}
Group=swg
ExecStart=${SUB_DIR}/swg-sub
Environment=SWG_SUB_FLEET=${etc}/fleet.json
Environment=SWG_SUB_WEB=${SUB_DIR}
Environment=SWG_SUB_HOST=${subbind}
Environment=SWG_SUB_PORT=${subport}
Environment=SWG_SUB_TRUST_XFF=${SUB_TRUST_XFF:-0}
${subextra}Restart=on-failure
RestartSec=2
# hardening — read-only (no ReadWritePaths), and the secrets are masked at the kernel level so even a
# bug in this internet-facing process cannot open the login hash, the TLS key, the subscription-key
# vault, panel-settings (webhook secrets), or any stored configs, regardless of file permissions.
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectControlGroups=true
ProtectKernelModules=true
ProtectKernelTunables=true
RestrictNamespaces=true
RestrictSUIDSGID=true
LockPersonality=true
InaccessiblePaths=-${etc}/auth -${tls} -${st}/subs/vault.json -${st}/subs/escrow.json -${st}/panel-settings.json -${st}/configs

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
  fi
  systemctl enable --quiet --now swg-sub 2>/dev/null || warn "couldn't enable swg-sub"
  ok "swg-sub subscription surface healed — Settings → Subscriptions will work now"
}

ensure_noded_unit(){   # HEAL (install-if-missing) the swg-noded systemd unit on a bare-metal node.
  # swg-noded is the outbound sync daemon. Its unit is STATIC — the real config (panel URL, token, verify,
  # interfaces) lives in the persisted /etc/swg-agent/config.json, so recreating a lost unit restores nothing
  # but the systemd wrapper and is safe. Without it the node isn't managed by systemd and won't sync or
  # survive a reboot. HEAL CONTRACT: only when the binary + config exist but the UNIT is gone; never rewrite
  # an existing unit. Template MUST mirror install-node.sh's swg-noded.service.
  [ -f "$SRC/swg-noded" ] || return 0
  [ -f "$NODED_DIR/swg-noded" ] && [ -f /etc/swg-agent/config.json ] || return 0   # a configured bare-metal node
  local unit=/etc/systemd/system/swg-noded.service
  if [ -f "$unit" ]; then
    $DRYRUN || systemctl is-enabled --quiet swg-noded 2>/dev/null || systemctl enable --quiet swg-noded 2>/dev/null || true
    return 0
  fi
  info "healing the swg-noded unit (missing — the node isn't managed by systemd and won't sync or survive a reboot)"
  if $DRYRUN; then echo "    [skip] install ${unit} (enable --now — config.json is preserved)"; return 0; fi
  local nname; nname="$(hostname 2>/dev/null || echo node)"   # cosmetic Description only (config.json holds no node name)
  cat > "$unit" <<EOF
[Unit]
Description=swg-noded (HTTPS sync to panel) — ${nname}
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
  systemctl daemon-reload
  systemctl enable --quiet --now swg-noded 2>/dev/null || warn "couldn't enable swg-noded"
  ok "swg-noded unit healed — the node will sync + survive a reboot now"
}

ensure_awg_module(){   # HEAL (rebuild-if-missing) the AmneziaWG kernel module on a bare-metal node/master that USES awg.
  # `apt install amneziawg` only lays down the `awg` TOOL; the datapath is a DKMS module that must COMPILE against
  # linux-headers-$(uname -r). Two ways it goes missing: a first install that lacked dkms/headers (tool present,
  # module never built → `ip link add type amneziawg` = "Unknown device type"), or a KERNEL UPGRADE that left the
  # old build stale so awg interfaces silently fail after a reboot. This rebuilds it — a cheap no-op when already
  # loadable. Docker nodes run userspace amneziawg-go (no kernel module) → skipped by the HAVE_BNODE gate.
  [ "$HAVE_BNODE" = yes ] || return 0
  have awg || ls /etc/amnezia/amneziawg/*.conf >/dev/null 2>&1 || return 0    # node doesn't use awg → nothing to heal
  { $DRYRUN || modprobe amneziawg 2>/dev/null; } && return 0                  # already loadable → done (silent)
  have apt-get || { warn "AmneziaWG kernel module not loadable — install amneziawg-dkms + linux-headers for kernel $(uname -r) with your package manager"; return 0; }
  info "healing the AmneziaWG kernel module (not loadable on kernel $(uname -r) — awg interfaces can't come up; rebuilding its DKMS module)"
  apt_refresh
  run apt-get install -y software-properties-common 2>/dev/null || true
  run add-apt-repository -y ppa:amnezia/ppa 2>/dev/null || true
  run apt-get update -qq 2>/dev/null || true
  run apt-get install -y dkms "linux-headers-$(uname -r)" || run apt-get install -y dkms linux-headers-generic || true
  run apt-get install -y amneziawg amneziawg-dkms amneziawg-tools || run apt-get install -y amneziawg || true
  # FORCE the DKMS module to COMPILE for THIS kernel — `apt install amneziawg` is a NO-OP when the package is
  # already installed (tool present) but its module never built (headers were missing then), so nothing rebuilds
  # it. dkms autoinstall builds every registered module for the running kernel; --reinstall re-runs the postinst.
  run dkms autoinstall 2>/dev/null || true
  modprobe amneziawg 2>/dev/null || run apt-get install --reinstall -y amneziawg-dkms 2>/dev/null || true
  run modprobe amneziawg 2>/dev/null || true
  if $DRYRUN || modprobe amneziawg 2>/dev/null; then
    DID_UPDATE=yes; ok "AmneziaWG kernel module healed — awg interfaces can come up now"; note "awg kernel module: rebuilt for $(uname -r)"
  else
    DID_FAIL=yes; warn "AmneziaWG kernel module still won't load on kernel $(uname -r) — this box may lack matching linux-headers (or the PPA has no build for it); awg interfaces can't come up"; note "awg kernel module: heal FAILED"
  fi
}

ensure_update_unit(){   # HEAL (install-if-missing) the one-click self-update wiring on a bare-metal panel.
  # install_update_unit (below) is called during an actual version update to REFRESH this wiring, but on an
  # up-to-date box with the units missing (a partial install / older host) nothing re-wires them, so the
  # panel's one-click "Update" button silently does nothing. Provision them here when absent. All pieces are
  # static templates (no operator config), so a full (re)provision via install_update_unit is safe.
  [ -f "$PANEL_DIR/swg-panel-server" ] || return 0     # bare-metal panel only
  if [ -x /usr/local/bin/swg-update ] && [ -x /usr/local/bin/swg-update-check ] \
     && [ -f /etc/systemd/system/swg-update.service ] && [ -f /etc/systemd/system/swg-update.timer ]; then
    $DRYRUN || systemctl is-enabled --quiet swg-update.timer 2>/dev/null || systemctl enable --quiet --now swg-update.timer 2>/dev/null || true
    return 0
  fi
  info "healing the one-click self-update wiring (missing — the panel's Update button would do nothing)"
  install_update_unit
  $DRYRUN || ok "one-click self-update wiring healed"
}

ensure_panel_unit_warn(){   # DETECT + WARN only — never recreate. The panel unit bakes in the operator's
  # bind host, port, TLS cert/key paths, and login; an update can't safely reconstruct those, and a blind
  # recreate would serve on the wrong port, DROP TLS, or DROP the login — a security downgrade, not a repair.
  # So we surface it loudly and point at the installer, which restores it with the real settings.
  [ -f "$PANEL_DIR/swg-panel-server" ] || return 0
  [ -f /etc/systemd/system/swg-panel-server.service ] && return 0
  DID_FAIL=yes
  warn "swg-panel-server.service is MISSING — the panel is not managed by systemd and won't survive a reboot."
  warn "Its unit carries your TLS cert/key, port, and login, which an update must not guess. Re-run the host"
  warn "installer to restore it with your real settings:"
  warn "    curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s host"
}

ensure_netctl_docker(){   # HEAL (install-if-missing) the docker address helper on a panel-bearing docker host.
  # On docker the panel container can't `docker compose` the host, so it writes netctl requests to the bind-
  # mounted data/lib/netctl/queue and THIS host unit drains them into compose actions (restart / rebind
  # swg-sub on an address change). Missing on older/partial docker installs → one-click address changes fall
  # back to a manual restart. HEAL CONTRACT: install only the missing pieces (binary + .service + .timer),
  # never rewrite existing ones; enable the timer. Templates MUST mirror install-docker.sh's wire_docker_netctl.
  case "${1:-}" in host|master|host-node) ;; *) return 0;; esac    # panel-bearing profiles only
  local drainer="$SRC/docker/swg-netctl-docker"
  [ -f "$drainer" ] || return 0
  if [ -x /usr/local/bin/swg-netctl-docker ] && [ -f /etc/systemd/system/swg-netctl-docker.service ] \
     && [ -f /etc/systemd/system/swg-netctl-docker.timer ]; then
    $DRYRUN || systemctl is-enabled --quiet swg-netctl-docker.timer 2>/dev/null || systemctl enable --quiet --now swg-netctl-docker.timer 2>/dev/null || true
    return 0
  fi
  info "healing the docker address helper (missing — one-click address changes would fall back to a manual restart)"
  if $DRYRUN; then echo "    [skip] install /usr/local/bin/swg-netctl-docker + swg-netctl-docker.{service,timer} (enable --now)"; return 0; fi
  mkdir -p "$DOCKER_DIR/data/lib/netctl/queue" "$DOCKER_DIR/data/lib/netctl/status"   # the panel writes requests here (bind mount)
  [ -x /usr/local/bin/swg-netctl-docker ] || install -m755 "$drainer" /usr/local/bin/swg-netctl-docker
  if [ ! -f /etc/systemd/system/swg-netctl-docker.service ]; then
    cat > /etc/systemd/system/swg-netctl-docker.service <<EOF
[Unit]
Description=swg-panel docker address helper (drains the netctl queue into docker compose actions)

[Service]
Type=oneshot
Environment=SWG_DOCKER_DIR=$DOCKER_DIR
ExecStart=/usr/local/bin/swg-netctl-docker
EOF
  fi
  if [ ! -f /etc/systemd/system/swg-netctl-docker.timer ]; then
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
  fi
  systemctl daemon-reload 2>/dev/null || true
  systemctl enable --quiet --now swg-netctl-docker.timer 2>/dev/null || warn "couldn't enable swg-netctl-docker.timer"
  ok "docker address helper healed — one-click address changes will work now"
}

ensure_update_unit_docker(){   # HEAL (install-if-missing) the docker one-click self-update wiring on a panel-bearing docker host.
  # install-docker.sh's wire_host_updater lays this down at install time; on an older/partial docker host with the
  # wrappers or units missing, the panel's one-click "Update" button silently does nothing. All pieces are STATIC
  # templates (no operator config), shared with the installer via write_docker_updater (lib/common.sh), so a full
  # (re)write is safe. HEAL CONTRACT: only when MISSING; enable the timer when present.
  case "${1:-}" in host|master|host-node) ;; *) return 0;; esac    # panel-bearing profiles only (mirrors ensure_netctl_docker)
  if [ -x /usr/local/bin/swg-update ] && [ -x /usr/local/bin/swg-update-check ] \
     && [ -f /etc/systemd/system/swg-update.service ] && [ -f /etc/systemd/system/swg-update.timer ]; then
    $DRYRUN || systemctl is-enabled --quiet swg-update.timer 2>/dev/null || systemctl enable --quiet --now swg-update.timer 2>/dev/null || true
    return 0
  fi
  info "healing the docker one-click self-update wiring (missing — the panel's Update button would do nothing)"
  if $DRYRUN; then echo "    [skip] install /usr/local/bin/swg-update{,-check} + swg-update.{service,timer} (enable --now)"; return 0; fi
  write_docker_updater   # shared writer (lib/common.sh): same pieces install-docker.sh writes
  ok "docker one-click self-update wiring healed — the Update button will work now"
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
    # swg-sub (the subscription surface) ships with the panel. Refresh it in place when already installed;
    # ensure_sub_server (below, unconditional) provisions it first-time on a panel that lacks the unit/user.
    # Inert unless enabled in the panel.
    if [ -f "$SUB_DIR/swg-sub" ] && [ -f "$SRC/swg-sub" ]; then
      run cp "$SRC/swg-sub" "$SUB_DIR/"; run chmod 755 "$SUB_DIR/swg-sub"
      for f in sub.html sub.js sub.css turn-artifacts.js; do [ -f "$SRC/$f" ] && run cp "$SRC/$f" "$SUB_DIR/"; done
      [ -f "$SRC/vendor/qrcode.js" ] && { run mkdir -p "$SUB_DIR/vendor"; run cp "$SRC/vendor/qrcode.js" "$SUB_DIR/vendor/"; }
      stamp "$SUB_DIR"
      run systemctl restart swg-sub 2>/dev/null && ok "swg-sub updated + restarted" || warn "swg-sub present but not restarted"
    fi
    # swg-passwd (admin login + Encryption-Vault reset helper) ships with the panel — refresh in place when present.
    # It's coupled to the panel's vault, so a stale copy after an update can mismatch; keep it in lockstep with the panel.
    if [ -f /usr/local/bin/swg-passwd ] && [ -f "$SRC/swg-passwd" ]; then
      run cp "$SRC/swg-passwd" /usr/local/bin/swg-passwd; run chmod 755 /usr/local/bin/swg-passwd; ok "swg-passwd refreshed"
    fi
    # swg-netctl (privileged network/TLS helper) — refresh the binary in place when already installed
    # (first-time provisioning of the binary + trigger units is done by install-host.sh).
    if [ -f /usr/local/bin/swg-netctl ] && [ -f "$SRC/swg-netctl" ]; then
      run cp "$SRC/swg-netctl" /usr/local/bin/swg-netctl; run chmod 755 /usr/local/bin/swg-netctl; ok "swg-netctl refreshed"
      # Heal the trigger unit on older installs: without StartLimitIntervalSec=0 the .path watcher trips
      # systemd's 5-starts-per-10s limit under a normal Access apply (issue-cert+set-listen+restart) and fails
      # permanently, degrading applies to the 10s timer (~50s). Add the override + clear any failed state.
      NCS=/etc/systemd/system/swg-netctl.service
      if [ -f "$NCS" ] && ! grep -q "StartLimitIntervalSec=0" "$NCS"; then
        run sed -i '/^\[Unit\]/a StartLimitIntervalSec=0' "$NCS"
        run systemctl daemon-reload
        run systemctl reset-failed swg-netctl.path swg-netctl.service 2>/dev/null || true
        run systemctl restart swg-netctl.path 2>/dev/null || true
        ok "swg-netctl.path rate-limit override applied"
      fi
    fi
  else note "bare-metal swg-panel: unchanged (${pold})"; fi
  # ── HEAL PASS (runs regardless of should_update) ──────────────────────────────────────────────────────
  # Contract: START / ENABLE / INSTALL-IF-MISSING only. Each ensure_* installs the pieces (binary/user/dir/
  # unit) that are ABSENT and enables the service; it must NEVER re-create, rewrite, or re-copy something
  # that already exists (that could clobber the panel's runtime drop-ins or the operator's choices). Config-
  # bearing scaffolding we can't safely template (the panel unit) is WARNED about, not recreated. Detecting
  # present-but-broken services is NOT done here — that's the panel's runtime "needs attention" job.
  # NEW SERVICE? add its ensure_<svc> here (and a matching writer in the installer) so update heals it too.
  ensure_netctl_helper   # swg-netctl privileged helper (+ queue dirs + trigger units)
  ensure_sub_server      # swg-sub subscription surface (user + binary + tls dir + unit)
  ensure_update_unit     # one-click self-update wiring (wrappers + service/timer + trigger drop-in)
  ensure_panel_unit_warn # swg-panel-server.service — detect + warn only (carries TLS/port/login)
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
  ensure_noded_unit      # HEAL: recreate the swg-noded unit if it's gone (config.json is preserved)
  ensure_awg_module      # HEAL: rebuild the AmneziaWG DKMS kernel module if it's missing/stale (e.g. after a kernel upgrade)
fi

# ───────────────────────── Docker (host / node / master) ─────────────────────────
if ! $NODE_ONLY && [ -d "$DOCKER_DIR" ] && [ -f "$DOCKER_DIR/docker-compose.yml" ]; then
  found=1; doc_seen=yes
  # which profile is running? prefer the marker install-docker.sh wrote into .env, else sniff containers
  prof="$(sed -n 's/^# .*profile: *//p' "$DOCKER_DIR/.env" 2>/dev/null | head -1 || true)"   # || true: .env may be absent (compose present) → don't abort before the fallback below
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
  ensure_netctl_docker "$prof"   # HEAL: install the docker address helper if a panel-bearing host lacks it
  ensure_update_unit_docker "$prof"   # HEAL: install the docker one-click self-update wiring if a panel-bearing host lacks it
  $DRYRUN || ensure_docker_mask_files "$DOCKER_DIR"   # HEAL: pre-create the files swg-sub /dev/null-masks (a pre-fix install may lack them → recreate would fail)
  if grep -qE '^[[:space:]]*build:' "$DOCKER_DIR/docker-compose.yml" 2>/dev/null; then
    # build-from-source deployment → restage the source and rebuild (don't touch the user's compose/.env)
    if should_update "docker ($prof, source build)" "$DOCKER_DIR"; then
      info "restaging source + rebuilding ($DOCKER_DIR)"
      for f in Dockerfile Dockerfile.node .dockerignore VERSION \
               swg-panel-server swg-agent swg-noded swg-sni swg-sub swg-passwd \
               index.html app.css app.js reconcile.js turn-artifacts.js sub.html sub.js sub.css; do
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
