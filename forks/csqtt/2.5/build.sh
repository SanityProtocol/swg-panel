#!/usr/bin/env bash
# Build the swg-panel csqtt 2.5.1-2 server (line 2.5): forks/csqtt/build.sh with the 2.5 pin and patch. If amurcanov's
# repository is gone, it builds the same source from our csqtt-2.5.1-2 release's archive (sha256-checked).
#
# Usage:  bash forks/csqtt/2.5/build.sh <out-dir> [amd64|arm64]     (default arch: amd64)
# Needs:  what forks/csqtt/build.sh needs (rustup 1.97.1 + zig + cargo-zigbuild) and curl for the fallback.
# csqtt is PolyForm-Noncommercial-1.0.0 — build only for non-commercial use.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CSQTT_PIN="d02da9bd9d8926969b766e197c434d830a83dbd8" \
CSQTT_PATCH="$HERE/csqtt-swgpanel-2.5.1-2.patch" \
CSQTT_SRC_FALLBACK="https://github.com/SanityProtocol/swg-panel/releases/download/csqtt-2.5.1-2/csqtt-2.5.1-2-swgpanel-src.tar.gz 3d34359fde5354521e70297e6c3fa19c6019de0088399c3d0dbcbacd32840403 7fbedb3a56a2cb10b1fb9147f7c28fd16d8889a8e1f4247a0395ef38e5ba03d1" \
  exec bash "$HERE/../build.sh" "$@"
