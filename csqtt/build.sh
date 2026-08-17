#!/usr/bin/env bash
# Build the swg-panel csqtt server: clone upstream at the pinned commit, apply csqtt-swgpanel.patch, and
# produce a static musl binary via cargo-zigbuild. Mirrors wdtt/<fork>/build.sh.
#
# Usage:  bash csqtt/build.sh <out-dir> [amd64|arm64]     (default arch: amd64)
# Needs:  cargo + rustup (toolchain 1.97.1) + zig + cargo-zigbuild on PATH (see the A0 scratchpad setup.sh).
# csqtt is PolyForm-Noncommercial-1.0.0 — build only for non-commercial use.
set -euo pipefail

PIN="31114cb70af67ed9a86adb063e2427ea4802c5c7"   # amurcanov/csqtt v2.0.1 (2026-08-17); v2.0.0 (2ff8a1a) differs by README only
REPO="https://github.com/amurcanov/csqtt.git"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:?usage: build.sh <out-dir> [amd64|arm64]}"
ARCH="${2:-amd64}"
case "$ARCH" in
  amd64) TARGET="x86_64-unknown-linux-musl" ;;
  arm64) TARGET="aarch64-unknown-linux-musl" ;;
  *) echo "arch must be amd64|arm64" >&2; exit 2 ;;
esac

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
git clone -q "$REPO" "$WORK/csqtt"
git -C "$WORK/csqtt" checkout -q "$PIN"
git -C "$WORK/csqtt" apply "$HERE/csqtt-swgpanel.patch"

rustup toolchain install 1.97.1 --profile minimal >/dev/null 2>&1 || true
rustup target add "$TARGET" --toolchain 1.97.1 >/dev/null 2>&1 || true

( cd "$WORK/csqtt/csqtt-uring" && cargo +1.97.1 zigbuild --release --target "$TARGET" )

mkdir -p "$OUT"
cp "$WORK/csqtt/csqtt-uring/target/$TARGET/release/csqtt" "$OUT/csqtt-server-linux-$ARCH"
echo "built: $OUT/csqtt-server-linux-$ARCH"
file "$OUT/csqtt-server-linux-$ARCH"
