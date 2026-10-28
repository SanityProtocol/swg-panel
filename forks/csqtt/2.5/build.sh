#!/usr/bin/env bash
# Build the swg-panel csqtt 2.5.3 server (line 2.5): forks/csqtt/build.sh with the 2.5 repository, pin and patch. 2.5.3 is
# built on the community repository Afteroid/csqttr (its `main` carries the swg-panel integration); the patch is our
# version label on top. If that repository is gone, it builds the same source from our csqtt-2.5.3 release's archive
# (sha256-checked).
#
# Usage:  bash forks/csqtt/2.5/build.sh <out-dir> [amd64|arm64]     (default arch: amd64)
# Needs:  what forks/csqtt/build.sh needs (rustup 1.97.1 + zig + cargo-zigbuild) and curl for the fallback.
# csqtt is PolyForm-Noncommercial-1.0.0 — build only for non-commercial use.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CSQTT_REPO="https://github.com/Afteroid/csqttr.git" \
CSQTT_PIN="001caa48e342caac8758db8ed4d12305faea6954" \
CSQTT_PATCH="$HERE/csqtt-swgpanel-2.5.3.patch" \
CSQTT_SRC_FALLBACK="https://github.com/SanityProtocol/swg-panel/releases/download/csqtt-2.5.3/csqtt-2.5.3-swgpanel-src.tar.gz 6b2ee135f7fb6b4cdd0c30b0f44fc8643eb1f459806b37e75cd630523735c5ad 7860f56b81de843c8943c271c3e1e8212666f1afce5d3b2a9098650a6b08a2ad" \
  exec bash "$HERE/../build.sh" "$@"
