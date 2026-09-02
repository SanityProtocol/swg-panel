#!/usr/bin/env bash
# Build our patched qWDTT server (SpaceNeuroX/proxy-turn-vk-android) for swg-panel.
#
# qWDTT is a WDTT fork whose server was rewritten into ONE flat `server.go` at the
# repo root (upstream WDTT keeps db/net/types/main under app/src/main/assets/linux-server),
# so it needs its own patch — the amurcanov one does not apply. Same model though:
# upstream ships no server binary, we build from a PINNED COMMIT and host the result.
#
# ⚠️ PIN A COMMIT, NEVER A TAG: qWDTT's v1.3.8 / v1.3.9 / v1.4.0 / v1.4.0-beta tags all
# still point at the July commit 2dd5d37f, long behind master.
#
# Usage:  ./build.sh [output-path]           (default: ./qwdtt-server)
# Env:    GOARCH=amd64|arm64  (default: host)   — same arch gate as turn.
set -euo pipefail

UPSTREAM_REPO="https://github.com/SpaceNeuroX/proxy-turn-vk-android"
UPSTREAM_SHA="fae121efc3ef57b633516601d3c0d6b1be1fde7c"   # v1.4.3, 2026-08-31; bump deliberately + re-test the patch
# ⚠️ v1.4.3 MOVED the server out of the repo root into server/ and split it across a dozen files
# (buffers/connections/core/nat/obfs/optimization/...). Our 9 hunks were untouched by that split and
# apply unchanged from inside server/ — the only edit this bump needed was this path. The flag surface
# only GAINED flags (admin-cert/-key/-listen/-token-file, bot-token-file, password-file), so a unit
# written by an older node still parses.
SRC_SUBDIR="server"       # was "." — server.go + admin_api.go moved here in v1.4.3

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HERE/qwdtt-server}"
PATCH="$HERE/qwdtt-swgpanel.patch"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "[qwdtt] cloning $UPSTREAM_REPO @ $UPSTREAM_SHA"
git clone --quiet "$UPSTREAM_REPO" "$WORK/src"
git -C "$WORK/src" checkout --quiet "$UPSTREAM_SHA"

cd "$WORK/src/$SRC_SUBDIR"
echo "[qwdtt] applying qwdtt-swgpanel.patch"
patch -p1 < "$PATCH"

echo "[qwdtt] building static binary (GOARCH=${GOARCH:-host})"
export CGO_ENABLED=0 GOOS=linux
[ -n "${GOARCH:-}" ] && export GOARCH
go build -trimpath -ldflags="-s -w" -o "$OUT" .

echo "[qwdtt] built: $OUT"
"$OUT" -h 2>&1 | grep -E '^\s+-(iface|wg-addr|desired|no-nat|max-passwords|fixed-config|api-addr|raw-iface|raw-addr)' || true
