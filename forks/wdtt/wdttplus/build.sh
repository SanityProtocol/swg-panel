#!/usr/bin/env bash
# Build our patched wdttplus WDTT server (Ivan4537/WDTT-Plus — admin/bot/WARP fork; server at repo root) for swg-panel.
# Same model as forks/wdtt/build.sh: pinned upstream SHA + our patch, hosted in our mirror. Usage: ./build.sh [out]  Env: GOARCH
set -euo pipefail
UPSTREAM_REPO="https://github.com/Ivan4537/WDTT-Plus"
UPSTREAM_SHA="3038b8ddc0306feb21d3c3624e2bc1c3c14639ad"   # v15, 2026-08-31; only re-anchor needed was the wdttServerVersion context line (14→15). Flag surface identical
HERE="$(cd "$(dirname "$0")" && pwd)"; OUT="${1:-$HERE/wdtt-server}"; PATCH="$HERE/wdtt-wdttplus.patch"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
git clone --quiet "$UPSTREAM_REPO" "$WORK/src"; git -C "$WORK/src" checkout --quiet "$UPSTREAM_SHA"
cd "$WORK/src"; git apply "$PATCH"
export CGO_ENABLED=0 GOOS=linux; [ -n "${GOARCH:-}" ] && export GOARCH
go build -trimpath -ldflags="-s -w" -o "$OUT" .
echo "[wdttplus] built: $OUT"; "$OUT" -h 2>&1 | grep -E '^\s+-(iface|wg-addr|desired|no-nat|no-panel)' || true
