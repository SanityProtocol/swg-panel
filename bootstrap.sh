#!/usr/bin/env bash
# bootstrap.sh — fetch swg-panel from GitHub and run the host or node installer.
#
#   curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s host
#   curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s node -key SECURE_NODE_KEY -host https://HOST_URL
#   curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s docker host
#   curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s update   # update an install in place
#
# The node one-liner takes the enrollment key + panel URL straight from the Nodes
# screen; the installer prompts for the rest (name, endpoint, interfaces) on /dev/tty.
#
#   -key  | -token  <tok>   node enrollment token   (-> NODE_TOKEN)
#   -host | -url    <url>   panel URL (https://…)    (-> PANEL_URL)
#   -name           <name>  node name               (-> NODE_NAME)
#   -endpoint       <ip>    public endpoint IP       (-> ENDPOINT_IP)
#
# For a fully unattended/config-driven run, pass CONFIG vars through sudo with -E, e.g.:
#   curl -fsSL .../bootstrap.sh | sudo -E ROLE=host TLS_MODE=cloudflare CF_TOKEN=… bash -s host
# Override the source with SWG_REPO / SWG_REF (branch or tag).
set -euo pipefail
REPO="${SWG_REPO:-https://github.com/SanityProtocol/swg-panel}"
REF="${SWG_REF:-main}"
ROLE="${1:-}"; case "$ROLE" in host|node|docker|update|uninstall) ;; *) echo "usage: bootstrap.sh host|node|docker|update|uninstall [flags]" >&2; exit 1;; esac
shift || true; [ "${1:-}" = "--" ] && shift || true

# Map convenience flags (for the node one-liner) into the env the installers read;
# anything else (e.g. --dry-run) is passed straight through to the installer.
PASS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -key|--key|-token|--token)     export NODE_TOKEN="${2:-}"; shift 2 || shift;;
    -host|--host|-url|--url)       export PANEL_URL="${2:-}";  shift 2 || shift;;
    -name|--name)                  export NODE_NAME="${2:-}";  shift 2 || shift;;
    -endpoint|--endpoint)          export ENDPOINT_IP="${2:-}"; shift 2 || shift;;
    *)                             PASS+=("$1"); shift;;
  esac
done

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
SCRIPT="install-$ROLE.sh"; [ "$ROLE" = uninstall ] && SCRIPT="uninstall.sh"; [ "$ROLE" = update ] && SCRIPT="update.sh"
echo ":: running $SCRIPT"
bash "./$SCRIPT" ${PASS[@]+"${PASS[@]}"}      # bash …  => exec bit not required
