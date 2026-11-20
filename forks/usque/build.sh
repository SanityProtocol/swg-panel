#!/usr/bin/env bash
# Build usque (Diniboy1123/usque), the MASQUE client a `warp-masque` exit runs as `usque nativetun`
# (1.8.12 item 17b, docs/WARP-MASQUE-PLAN.md §1.4). UNPATCHED upstream at a pinned commit; upstream has no tags.
# Usage: ./build.sh [out]   Env: GOARCH (amd64 | arm64)
# Reproducible: this commit + this exact Go toolchain + these flags give the sha256s pinned in swg-noded
# (USQ_SHA256), so the published release asset can be rebuilt and compared byte for byte.
set -euo pipefail
UPSTREAM_REPO="https://github.com/Diniboy1123/usque"
UPSTREAM_SHA="6aa03fc97d12848dce34eedbd187fb1077b5d1ea"   # 2026-07-20 → release usque-20260720-6aa03fc
GO_VERSION="go1.27.1"                                       # the pinned sha256s reproduce ONLY with this toolchain
HERE="$(cd "$(dirname "$0")" && pwd)"; OUT="${1:-$HERE/usque}"
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac   # before the cd below: a relative path would land in the temp tree and go with it
have_go="$(go env GOVERSION 2>/dev/null || echo none)"
[ "$have_go" = "$GO_VERSION" ] || { echo "[usque] needs $GO_VERSION, found $have_go — any other toolchain builds a binary whose sha256 will not match the pin" >&2; exit 1; }
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
git clone --quiet "$UPSTREAM_REPO" "$WORK/src"; git -C "$WORK/src" checkout --quiet "$UPSTREAM_SHA"
cd "$WORK/src"
export CGO_ENABLED=0 GOOS=linux GOFLAGS=-buildvcs=false; [ -n "${GOARCH:-}" ] && export GOARCH
go build -trimpath -ldflags="-s -w" -o "$OUT" .
echo "[usque] built: $OUT  sha256 $(sha256sum "$OUT" | cut -d' ' -f1)"
