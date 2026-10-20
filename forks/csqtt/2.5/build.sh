#!/usr/bin/env bash
# Build the swg-panel csqtt 2.5.1 server (line 2.5): forks/csqtt/build.sh with the 2.5 pin and patch. If amurcanov's
# repository is gone, it builds the same source from our csqtt-2.5.1 release's archive (sha256-checked).
#
# Usage:  bash forks/csqtt/2.5/build.sh <out-dir> [amd64|arm64]     (default arch: amd64)
# Needs:  what forks/csqtt/build.sh needs (rustup 1.97.1 + zig + cargo-zigbuild) and curl for the fallback.
# csqtt is PolyForm-Noncommercial-1.0.0 — build only for non-commercial use.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CSQTT_PIN="d02da9bd9d8926969b766e197c434d830a83dbd8" \
CSQTT_PATCH="$HERE/csqtt-swgpanel-2.5.1.patch" \
CSQTT_SRC_FALLBACK="https://github.com/SanityProtocol/swg-panel/releases/download/csqtt-2.5.1/csqtt-2.5.1-swgpanel-src.tar.gz dcf06a1c98781e21f3c9c477d5c56bcb23566c3c2b0ab2f361c286079c0e3ea6 a8a24e5348541c569ed98d8efcbff3ca160ddf1ba38ad62976c4910775b798c8" \
  exec bash "$HERE/../build.sh" "$@"
