#!/usr/bin/env bash
# Build our patched xxcipherx WDTT server (XXcipherX/proxy-turn-vk-android — video-masquerade fork) for swg-panel.
# Same model as forks/wdtt/build.sh (amurcanov): pinned upstream SHA + our patch, hosted in our mirror.
# Usage: ./build.sh [out]   Env: GOARCH=amd64|arm64
set -euo pipefail
UPSTREAM_REPO="https://github.com/XXcipherX/proxy-turn-vk-android"
UPSTREAM_SHA="a9c0ff7ae7a16a42244b1a1cae08282708e1d001"   # v2.0.0.70, 2026-08-31; patch applied UNCHANGED (no re-port) and the flag surface is identical to v2.0.0.68
SRC_SUBDIR="app/src/main/assets/linux-server"
HERE="$(cd "$(dirname "$0")" && pwd)"; OUT="${1:-$HERE/wdtt-server}"; PATCH="$HERE/wdtt-xxcipherx.patch"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
git clone --quiet "$UPSTREAM_REPO" "$WORK/src"; git -C "$WORK/src" checkout --quiet "$UPSTREAM_SHA"
cd "$WORK/src/$SRC_SUBDIR"; git apply "$PATCH"
export CGO_ENABLED=0 GOOS=linux; [ -n "${GOARCH:-}" ] && export GOARCH
go build -trimpath -ldflags="-s -w" -o "$OUT" .
echo "[xxcipherx] built: $OUT"; "$OUT" -h 2>&1 | grep -E '^\s+-(iface|wg-addr|desired|no-nat)' || true
