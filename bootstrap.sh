#!/usr/bin/env bash
# bootstrap.sh — fetch swg-panel from GitHub and run the host or node installer.
#
#   curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s host
#   curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s node
#
# The installers prompt interactively (they read /dev/tty, so the pipe is fine).
# For an unattended/config-driven run, pass CONFIG vars through sudo with -E, e.g.:
#   curl -fsSL .../bootstrap.sh | sudo -E ROLE=host TLS_MODE=cloudflare CF_TOKEN=… bash -s host
# Override the source with SWG_REPO / SWG_REF (branch or tag).
set -euo pipefail
REPO="${SWG_REPO:-https://github.com/SanityProtocol/swg-panel}"
REF="${SWG_REF:-main}"
ROLE="${1:-}"; case "$ROLE" in host|node|uninstall) ;; *) echo "usage: bootstrap.sh host|node|uninstall [-- args]" >&2; exit 1;; esac
shift || true; [ "${1:-}" = "--" ] && shift || true
[ "$(id -u)" = 0 ] || { echo "run with sudo (it installs users, units and certs)" >&2; exit 1; }
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
  echo "need git, or curl+tar, to fetch the repo" >&2; exit 1
fi
cd "$TMP/swg-panel"
SCRIPT="install-$ROLE.sh"; [ "$ROLE" = uninstall ] && SCRIPT="uninstall.sh"
echo ":: running $SCRIPT"
bash "./$SCRIPT" "$@"                 # bash …  => exec bit not required
