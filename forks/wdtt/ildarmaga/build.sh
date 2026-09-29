#!/usr/bin/env bash
# Reproducibly build the swg-panel-patched ildarmaga WDTT SERVER binary (server-only, headless).
#
# ildarmaga/wdtt is a separate Go codebase from amurcanov but a BYTE-IDENTICAL wire (WRAP/GETCONF/
# wdtt://) — clients are interchangeable. This builds ONLY the datapath server (server/cmd), NOT the
# bundled web panel / Xray / subscription server.
#
# BUILD LABEL: 1.5.0-4 (-3 + the -dns flag). ildarmaga publishes no source past PIN (ef69799 = the v1.5.0 tree); its
# 1.5.40/1.5.55/1.5.61 tags all point at that one commit and the shipped 1.5.x binaries were built from
# unpublished commits. So we build v1.5.0 + our patch and label it honestly (NOT a borrowed 1.5.40/1.5.61).
# -3 adds the K5 revocation/source fixes (see README) on top of the -no-nat/flags patch. Nothing published.
#
# Our patch (wdtt-ildarmaga.patch) adds:
#   -iface / -wg-addr / -mtu   parameterize the interface + subnet (multi-instance per node)
#   -max-users                 raise the stock per-instance cap
#   -no-nat                    node owns NAT/sysctls → skip setupFullConeNAT + syncVPNLocalServices +
#                              enableBBR (ALL host mutation; verified zero WDTT_MANAGED/BBR change on a
#                              live box). Clean stop = TUN close self-removes the iface, nothing to clean.
# Defaults preserve stock behavior when a flag is absent.
#
# Pure-Go SQLite (modernc) → CGO_ENABLED=0 static build, so the binary runs on any glibc/musl node.
set -euo pipefail

PIN="${WDTT_ILDARMAGA_PIN:-ef697994bc7ac650b81623484933d930c5cd766b}"   # pinned upstream commit
REPO="https://github.com/ildarmaga/wdtt.git"
HERE="$(cd "$(dirname "$0")" && pwd)"
PATCH="$HERE/wdtt-ildarmaga.patch"
WORK="${WDTT_BUILD_DIR:-$(mktemp -d)}"
ARCH="${GOARCH:-amd64}"
OUT="${1:-$HERE/wdtt-ildarmaga-server-$ARCH}"

echo "[build] clone $REPO @ $PIN"
git clone --quiet "$REPO" "$WORK/src"
git -C "$WORK/src" checkout --quiet "$PIN"

echo "[build] apply $PATCH"
git -C "$WORK/src" apply "$PATCH"

echo "[build] compile server-only, static (GOARCH=$ARCH, CGO off)"
( cd "$WORK/src/server" && GOWORK=off CGO_ENABLED=0 GOARCH="$ARCH" go build -trimpath -o "$OUT" ./cmd )

echo "[build] done -> $OUT"
sha256sum "$OUT"
