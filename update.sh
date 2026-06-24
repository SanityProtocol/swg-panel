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
#         --no-components  swg only (panel/noded/agent) — skip third-party turn-proxy servers
set -euo pipefail

DRYRUN=false; ASSUME_YES=false; FORCE=false; NO_COMPONENTS=false; NODE_ONLY=false
for a in "$@"; do case "$a" in
  --dry-run) DRYRUN=true;; -y|--yes) ASSUME_YES=true;; -f|--force) FORCE=true;;
  --no-components) NO_COMPONENTS=true;;
  --node-only) NODE_ONLY=true;;     # update ONLY the bare-metal node/agent — never the co-located panel/docker
esac; done
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PANEL_DIR="${PANEL_DIR:-/opt/swg-panel}"
AGENT_DIR="${AGENT_DIR:-/opt/swg-agent}"
NODED_DIR="${NODED_DIR:-/opt/swg-noded}"
DOCKER_DIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"

. "$SRC/lib/common.sh"   # lc_* lifecycle helpers (shared with the installers)
# signal "updating" → updated / aborted / failed for whichever this box is: a node (POST via its agent
# config) and/or a panel host (host_proc file). Best-effort; armed only when there's something to tell.
lc_emit_upd(){ [ -n "${LC_FILE:-}" ] && lc_emit_file "$1" "${2:-}"; [ -n "${LC_TOKEN:-}" ] && [ -n "${LC_URL:-}" ] && lc_emit_post "$1" "${2:-}"; return 0; }
if ! $DRYRUN; then
  [ -f "$PANEL_DIR/swg-panel-server" ] && [ -d /var/lib/swg-panel ] && LC_FILE=/var/lib/swg-panel/host_proc
  if [ -f /etc/swg-agent/config.json ]; then
    LC_URL="$(python3 -c 'import json;print((json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("url",""))' 2>/dev/null || true)"
    LC_TOKEN="$(python3 -c 'import json;print((json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("token",""))' 2>/dev/null || true)"
    LC_VERIFY="$(python3 -c 'import json;print("yes" if (json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("verify",True) else "no")' 2>/dev/null || echo no)"
  fi
  { [ -n "${LC_FILE:-}" ] || [ -n "${LC_TOKEN:-}" ]; } && lc_init update lc_emit_upd
fi

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then BOLD=$'\033[1m'; RESET=$'\033[0m'; C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YEL=$'\033[33m'; C_RED=$'\033[31m'; C_BLUE=$'\033[38;5;39m'; C_BL=$'\033[38;5;33m'; C_BROWN=$'\033[38;5;130m'
else BOLD=""; RESET=""; C_CYAN=""; C_GREEN=""; C_YEL=""; C_RED=""; C_BLUE=""; C_BL=""; C_BROWN=""; fi
info(){ echo "${C_BLUE}▸${RESET} ${BOLD}$*${RESET}"; }   # ▸ light-blue, bold (universal action flag)
sub(){  echo "${C_BL}::${RESET} $*"; }                    # :: blue sub-item / progress detail
ok(){   echo "${C_GREEN}✓${RESET} $*"; }
warn(){ echo "${C_BROWN}!${RESET} $*" >&2; }
die(){  echo "${C_RED}✗ $*${RESET}" >&2; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }
run(){ if $DRYRUN; then echo "    [skip] $*"; else "$@"; fi; }
stamp(){ $DRYRUN || printf '%s\n' "$NEW_VER" > "$1/VERSION" 2>/dev/null || true; }
oldver(){ cat "$1/VERSION" 2>/dev/null || echo '?'; }
confirm(){ # confirm <prompt> -> 0 yes / 1 no.  --yes or no terminal => yes (you ran update on purpose)
  $ASSUME_YES && return 0
  local v
  if printf '%s %s: ' "$1" "[Y/n]" 2>/dev/null >/dev/tty && IFS= read -r v 2>/dev/null </dev/tty; then
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
  apt_refresh; cand="$(pkg_candidate "$pkg")"
  if [ -z "$cand" ] || [ "$cand" = "$cur" ] || [ "$cand" = "(none)" ]; then ok "$(col_l "$label") ($pkg): already up to date ($cur)"; return 0; fi
  echo
  if confirm "Upgrade $(col_l "$label") ($pkg) $(col_v "$cur → $cand")?"; then
    info "updating $label ($pkg)"
    if run apt-get install -y --only-upgrade "$pkg"; then DID_UPDATE=yes; ok "$label updated ($cand)"; note "$label: ${cur} → ${cand}"
    else warn "$label: upgrade failed"; note "$label: upgrade FAILED"; fi
  else warn "$label: skipped (still $cur)"; note "$label: unchanged ($cur)"; fi; }

NEW_VER="$(cat "$SRC/VERSION" 2>/dev/null || echo unknown)"
[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
found=0; DID_UPDATE=no
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
[ "$_haspanel" = yes ] && info "swg-panel — latest is version $(col_v "$NEW_VER")"
[ "$_hasnode" = yes ]  && info "swg-node — latest is version $(col_v "$NEW_VER")"
true   # don't let the above &&-tests leave a non-zero status for `set -e`

install_update_unit(){   # idempotent: wire one-click host self-update for an existing bare-metal panel
  local st="${STATE_DIR:-/var/lib/swg-panel}" usr="${PANEL_USER:-swgpanel}" trig
  trig="${st}/.update-request"
  if $DRYRUN; then echo "    [skip] install /usr/local/bin/swg-update + swg-update.{service,path} + trigger drop-in"; return 0; fi
  cat > /usr/local/bin/swg-update <<'WRAP'
#!/usr/bin/env bash
# swg-update — fixed root entrypoint for one-click in-place update (swg programs only).
set -euo pipefail
URL="${SWG_BOOTSTRAP_URL:-https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh}"
curl -fsSL "$URL" | bash -s update -y --no-components
WRAP
  chmod 755 /usr/local/bin/swg-update
  cat > /etc/systemd/system/swg-update.service <<EOF
[Unit]
Description=swg-panel one-click self-update (swg programs only)

[Service]
Type=oneshot
ExecStart=/usr/local/bin/swg-update
EOF
  cat > /etc/systemd/system/swg-update.path <<EOF
[Unit]
Description=watch for a swg-panel update request

[Path]
PathModified=${trig}
Unit=swg-update.service

[Install]
WantedBy=multi-user.target
EOF
  [ -e "$trig" ] || { : > "$trig"; chown "$usr:swg" "$trig" 2>/dev/null || true; chmod 660 "$trig"; }
  # point the (already-installed) panel at the trigger via a drop-in — don't edit the main unit
  install -d /etc/systemd/system/swg-panel-server.service.d
  printf '[Service]\nEnvironment=SWG_UPDATE_TRIGGER=%s\n' "$trig" \
    > /etc/systemd/system/swg-panel-server.service.d/zz-swg-update.conf
  systemctl daemon-reload
  systemctl enable --now swg-update.path >/dev/null 2>&1 || warn "couldn't enable swg-update.path"
}

# ───────────────────────── bare-metal panel (host or master) ─────────────────────────
if ! $NODE_ONLY && [ -f "$PANEL_DIR/swg-panel-server" ]; then
  found=1; pan_seen=yes; pold="$(oldver "$PANEL_DIR")"
  if should_update "bare-metal swg-panel" "$PANEL_DIR"; then
    info "updating bare-metal swg-panel ($PANEL_DIR)"
    for f in swg-panel-server index.html app.css app.js reconcile.js; do
      [ -f "$SRC/$f" ] && run cp "$SRC/$f" "$PANEL_DIR/"
    done
    # whole vendor/ dir — the buildless SPA needs the vendored Preact + htm ESM, not just qrcode
    [ -d "$SRC/vendor" ] && { run mkdir -p "$PANEL_DIR/vendor"; run cp -a "$SRC/vendor/." "$PANEL_DIR/vendor/"; }
    run chmod 755 "$PANEL_DIR/swg-panel-server"; stamp "$PANEL_DIR"
    install_update_unit                              # ensure one-click host self-update is wired
    if run systemctl restart swg-panel-server; then ok "swg-panel updated + restarted"; note "bare-metal swg-panel: ${pold} → ${NEW_VER}"
    else warn "couldn't restart swg-panel-server"; note "bare-metal swg-panel: updated but RESTART FAILED"; fi
  else note "bare-metal swg-panel: unchanged (${pold})"; fi
fi

# ───────────────────────── bare-metal node daemon (node or master) ─────────────────────────
if [ -f "$NODED_DIR/swg-noded" ] || [ -f "$AGENT_DIR/swg-agent" ]; then
  found=1; nod_seen=yes; nold="$(oldver "$NODED_DIR")"
  if should_update "bare-metal swg-node" "$NODED_DIR"; then
    info "updating bare-metal swg-node ($AGENT_DIR + $NODED_DIR)"
    [ -d "$AGENT_DIR" ] && [ -f "$SRC/swg-agent" ] && { run cp "$SRC/swg-agent" "$AGENT_DIR/"; run chmod 755 "$AGENT_DIR/swg-agent"; }
    [ -d "$NODED_DIR" ] && [ -f "$SRC/swg-noded" ] && { run cp "$SRC/swg-noded" "$NODED_DIR/"; run chmod 755 "$NODED_DIR/swg-noded"; }
    stamp "$NODED_DIR"
    if run systemctl restart swg-noded; then ok "swg-node updated + restarted"; note "bare-metal swg-node: ${nold} → ${NEW_VER}"
    else warn "couldn't restart swg-noded — run: systemctl restart swg-noded"; note "bare-metal swg-node: updated but RESTART FAILED"; fi
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
      else ( cd "$DOCKER_DIR" && $COMPOSE --profile "$prof" up -d --build ) >&"${LC_OUT:-1}" 2>&"${LC_OUT:-1}" && { ok "docker ($prof) rebuilt + restarted"; note "docker ($prof): rebuilt"; } || { warn "compose rebuild failed — check $DOCKER_DIR"; note "docker ($prof): rebuild FAILED"; }; fi
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
      else ( cd "$DOCKER_DIR" && $COMPOSE --profile "$prof" pull && $COMPOSE --profile "$prof" up -d --force-recreate ) >&"${LC_OUT:-1}" 2>&"${LC_OUT:-1}" && { ok "docker ($prof) image pulled + recreated"; note "docker ($prof): image pulled + recreated"; } || { warn "compose pull/up failed — check $DOCKER_DIR"; note "docker ($prof): pull/up FAILED"; }; fi
    else warn "docker ($prof): skipped"; note "docker ($prof): skipped"; fi
  fi
fi

# ───────────────────────── WireGuard / AmneziaWG datapath ─────────────────────────
# bare-metal node → the system package (amneziawg via the amnezia PPA, or wireguard). docker node → the
# datapath (amneziawg-go) lives in the swg-node image and refreshes with the image pull above.
if [ "$HAVE_BNODE" = yes ]; then
  pkg_update "WireGuard / AmneziaWG" amneziawg amneziawg-tools amneziawg-dkms wireguard wireguard-tools
elif [ "$HAVE_DOCK" = yes ] && [ "$DOCK_PROF" != host ]; then
  ok "$(col_l "WireGuard / AmneziaWG"): bundled in the swg-node image (refreshed with the image above)"
fi

# ───────────────────────── Docker engine (docker scenario only) ─────────────────────────
if [ "$HAVE_DOCK" = yes ]; then
  pkg_update "Docker engine" docker-ce docker.io
fi

# ───────────────────────── turn-proxy servers (vk-turn-proxy, ones we installed) ─────────────────────────
TURN_DIR="${TURN_DIR:-/opt/vk-turn-proxy}"
if $NO_COMPONENTS && [ -d "$TURN_DIR" ]; then
  info "skipping third-party components (turn-proxy servers) — --no-components"
elif [ -d "$TURN_DIR" ]; then
  for d in "$TURN_DIR"/*/; do
    [ -f "${d}server" ] && [ -f "${d}version.txt" ] || continue
    found=1
    key="$(basename "$d")"; owner="$(cat "${d}repo.txt" 2>/dev/null || echo '?')"; cur="$(cat "${d}version.txt" 2>/dev/null || echo '?')"
    if $DRYRUN; then latest="v0.0.0-latest"
    else sub "checking turn-proxy $(col_l "$key") ($owner) for a newer release on GitHub…"   # network call — say so (and cap it) so it never looks hung
      latest="$(curl -fsSL --connect-timeout 10 --max-time 20 "https://api.github.com/repos/$owner/releases/latest" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("tag_name",""))' 2>/dev/null || true)"; fi
    [ -n "$latest" ] || { warn "turn-proxy $key ($owner): couldn't reach GitHub for the latest release — skipping"; continue; }
    if [ "$cur" = "$latest" ] && ! $FORCE; then ok "$(col_l "turn-proxy $key") ($owner): already up to date ($cur)"; continue; fi
    echo
    if confirm "Upgrade $(col_l "turn-proxy $key") ($owner) $(col_v "$cur → $latest")?"; then
      DID_UPDATE=yes
      case "$(uname -m)" in x86_64|amd64) arch=amd64;; aarch64|arm64) arch=arm64;; *) arch=amd64;; esac
      url="https://github.com/$owner/releases/latest/download/server-linux-$arch"
      info "updating turn-proxy $key ($owner)"
      if run curl -fsSL "$url" -o "${d}server.new" && run chmod +x "${d}server.new" && run mv "${d}server.new" "${d}server"; then
        $DRYRUN || printf '%s\n' "$latest" > "${d}version.txt"
        run systemctl restart "vk-turn-proxy-$key" && ok "turn-proxy $key updated + restarted" || warn "couldn't restart vk-turn-proxy-$key"
      else warn "turn-proxy $key: download failed ($url)"; fi
    else warn "turn-proxy $key: skipped (still $cur)"; fi
  done
fi

[ "$found" = 1 ] || die "no swg-panel install found (looked in $PANEL_DIR, $NODED_DIR, $DOCKER_DIR, $TURN_DIR)"
# call out swg components that weren't present, so a partial-looking run is never a mystery
[ "$pan_seen" = yes ] || note "bare-metal swg-panel: not installed ($PANEL_DIR)"
[ "$nod_seen" = yes ] || note "bare-metal swg-node: not installed ($NODED_DIR)"
[ "$doc_seen" = yes ] || note "docker: not installed ($DOCKER_DIR)"
# lifecycle terminal: nothing changed → green "up to date" (5 s); else the lc EXIT trap emits "updated".
if [ "$DID_UPDATE" = no ]; then lc_emit uptodate; lc_handoff; fi
echo; ok "Update complete."
if [ "${#RESULTS[@]}" -gt 0 ]; then echo; info "Summary (every component on this host):"; for r in "${RESULTS[@]}"; do echo "    • $r"; done; fi
if $DRYRUN; then ok "DRY RUN done — nothing changed."; fi
exit 0   # success — keep the last status 0 so the lc EXIT trap reports "updated", not a false failure
