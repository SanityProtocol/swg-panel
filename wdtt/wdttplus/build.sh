#!/usr/bin/env bash
# Build our patched wdttplus WDTT server (Ivan4537/WDTT-Plus — admin/bot/WARP fork; server at repo root) for swg-panel.
# Same model as wdtt/build.sh: pinned upstream SHA + our patch, hosted in our mirror. Usage: ./build.sh [out]  Env: GOARCH
set -euo pipefail
UPSTREAM_REPO="https://github.com/Ivan4537/WDTT-Plus"
UPSTREAM_SHA="10c6939b2ace8a56e203e163d4eea586127c8646"   # v14; re-ported 2026-08-16 (v14 added its own wgIface/Addr/CIDR consts → dropped our dup)
HERE="$(cd "$(dirname "$0")" && pwd)"; OUT="${1:-$HERE/wdtt-server}"; PATCH="$HERE/wdtt-wdttplus.patch"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
git clone --quiet "$UPSTREAM_REPO" "$WORK/src"; git -C "$WORK/src" checkout --quiet "$UPSTREAM_SHA"
cd "$WORK/src"; git apply "$PATCH"
export CGO_ENABLED=0 GOOS=linux; [ -n "${GOARCH:-}" ] && export GOARCH
go build -trimpath -ldflags="-s -w" -o "$OUT" .
echo "[wdttplus] built: $OUT"; "$OUT" -h 2>&1 | grep -E '^\s+-(iface|wg-addr|desired|no-nat|no-panel)' || true
