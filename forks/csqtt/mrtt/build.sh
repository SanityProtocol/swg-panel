#!/usr/bin/env bash
# Build the swg-panel MRTT server (csqtt line `mrtt`): forks/csqtt/build.sh with MRTT's repository, pin and patch. MRTT is
# ttrroyy's fork of amurcanov's csqtt 2.5.0 (fd936ef) with every crypto label renamed, so it speaks to MRTT's apps only.
# The patch is our csqtt 2.5.3 integration (--iface --tun-addr --instance --no-nat --no-web --desired --max-passwords,
# App routing riding in --desired) ported onto MRTT 1.0, its store renamed csqtt.db so the node reads it as a csqtt
# server's, and MRTT's own exit-route loop left off under --desired (the node owns routing).
#
# Usage:  bash forks/csqtt/mrtt/build.sh <out-dir> [amd64|arm64]     (default arch: amd64)
# Needs:  what forks/csqtt/build.sh needs (rustup 1.97.1 + zig + cargo-zigbuild).
# MRTT is PolyForm-Noncommercial-1.0.0 — build only for non-commercial use.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CSQTT_REPO="https://github.com/ttrroyy/MRTT.git" \
CSQTT_PIN="17259c200887262fd531b8c2790920f49e1178d2" \
CSQTT_PATCH="$HERE/mrtt-swgpanel-1.0.patch" \
CSQTT_BIN="mrtt" \
  exec bash "$HERE/../build.sh" "$@"
