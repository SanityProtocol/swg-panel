#!/usr/bin/env bash
# Build the userspace AmneziaWG datapath (amnezia-vpn/amneziawg-go) that every bare-metal node keeps as awg-quick's
# fallback when the kernel module is missing (docs/AWG-DATAPATH-RESILIENCE-PLAN.md D1). UNPATCHED upstream at a pinned
# commit. Usage: ./build.sh [out]   Env: GOARCH (amd64 | arm64)
# Reproducible: this commit + this exact Go toolchain + these flags give the sha256s pinned in lib/common.sh
# (AWG_GO_SHA256_amd64 / _arm64), so the published release asset can be rebuilt and compared byte for byte.
set -euo pipefail
UPSTREAM_REPO="https://github.com/amnezia-vpn/amneziawg-go"
UPSTREAM_SHA="b5928efb6ca19f0153958460c3d141f04abc5c2e"   # tag v3.1.20260828 → release amneziawg-go-3.1.20260828
GO_VERSION="go1.27.1"                                       # the pinned sha256s reproduce ONLY with this toolchain
HERE="$(cd "$(dirname "$0")" && pwd)"; OUT="${1:-$HERE/amneziawg-go}"
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac   # before the cd below: a relative path would land in the temp tree and go with it
have_go="$(go env GOVERSION 2>/dev/null || echo none)"
[ "$have_go" = "$GO_VERSION" ] || { echo "[amneziawg-go] needs $GO_VERSION, found $have_go — any other toolchain builds a binary whose sha256 will not match the pin" >&2; exit 1; }
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
git clone --quiet "$UPSTREAM_REPO" "$WORK/src"; git -C "$WORK/src" checkout --quiet "$UPSTREAM_SHA"
cd "$WORK/src"
export CGO_ENABLED=0 GOOS=linux GOFLAGS=-buildvcs=false; [ -n "${GOARCH:-}" ] && export GOARCH
go build -trimpath -ldflags="-s -w" -o "$OUT" .
echo "[amneziawg-go] built: $OUT  sha256 $(sha256sum "$OUT" | cut -d' ' -f1)"
