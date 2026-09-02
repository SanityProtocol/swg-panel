#!/usr/bin/env bash
# Build the swg-panel csqtt server: clone upstream at the pinned commit, apply csqtt-swgpanel.patch, and
# produce a static musl binary via cargo-zigbuild. Mirrors wdtt/<fork>/build.sh.
#
# Usage:  bash forks/csqtt/build.sh <out-dir> [amd64|arm64]     (default arch: amd64)
# Needs:  cargo + rustup (toolchain 1.97.1) + zig + cargo-zigbuild on PATH.
# csqtt is PolyForm-Noncommercial-1.0.0 — build only for non-commercial use.
set -euo pipefail

PIN="446293aa2e873ac5323ef6fd2316d9b81d966c11"   # amurcanov/csqtt v2.1.9 (2026-09-02)
REPO="https://github.com/amurcanov/csqtt.git"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:?usage: build.sh <out-dir> [amd64|arm64]}"
ARCH="${2:-amd64}"
case "$ARCH" in
  amd64) TARGET="x86_64-unknown-linux-musl";  ZIGTGT="x86_64-linux-musl";  ENVA="X86_64_UNKNOWN_LINUX_MUSL";  CENV="x86_64_unknown_linux_musl" ;;
  arm64) TARGET="aarch64-unknown-linux-musl"; ZIGTGT="aarch64-linux-musl"; ENVA="AARCH64_UNKNOWN_LINUX_MUSL"; CENV="aarch64_unknown_linux_musl" ;;
  *) echo "arch must be amd64|arm64" >&2; exit 2 ;;
esac

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
git clone -q "$REPO" "$WORK/csqtt"
git -C "$WORK/csqtt" checkout -q "$PIN"
git -C "$WORK/csqtt" apply "$HERE/csqtt-swgpanel.patch"

rustup toolchain install 1.97.1 --profile minimal >/dev/null 2>&1 || true
rustup target add "$TARGET" --toolchain 1.97.1 >/dev/null 2>&1 || true

# 2.1.5 pulled in C/C++ dependencies — rusqlite (bundled SQLite, C) and snmalloc-rs (build_cc, C++) — beside
# the aws-lc-sys that was already there. cargo-zigbuild alone does NOT wire those up: the `cc` crate needs an
# explicit cross compiler, which is what upstream's own rust-server/build_linux.sh does with zig wrappers.
# The wrapper drops the `--target=<rust triple>` rustc passes through, which `zig cc` does not understand.
WRAP="$WORK/zig-wrappers"; mkdir -p "$WRAP"
cat > "$WRAP/zigcc" <<SH
#!/usr/bin/env bash
args=(); for a in "\$@"; do [[ "\$a" == "--target=$TARGET" ]] || args+=("\$a"); done
exec zig cc -target $ZIGTGT "\${args[@]}"
SH
cat > "$WRAP/zigcxx" <<SH
#!/usr/bin/env bash
args=(); for a in "\$@"; do [[ "\$a" == "--target=$TARGET" ]] || args+=("\$a"); done
exec zig c++ -target $ZIGTGT "\${args[@]}"
SH
printf '#!/usr/bin/env bash\nexec zig ar "$@"\n' > "$WRAP/zigar"
chmod +x "$WRAP"/zig*
export CC_$CENV="$WRAP/zigcc" CXX_$CENV="$WRAP/zigcxx" AR_$CENV="$WRAP/zigar"
export CARGO_TARGET_${ENVA}_LINKER="$WRAP/zigcc"
# Upstream's .cargo/config.toml sets link-self-contained=no for x86_64 ONLY. Without it here, rustc adds its own
# crt1.o beside zig's and ld.lld fails with `duplicate symbol: _start`. Setting it for both arches keeps the two
# builds identical instead of one carrying a silent exception.
# ⚠️ As of 2.1.9 upstream DOES build arm64 (rust-server/build_linux.sh: `build_variant aarch64-unknown-linux-musl
# ... csqtt-linux-arm64`) — an earlier version of this comment said they never did, which is no longer true. We
# still do not use their script: it sets no aarch64 rustflags and .cargo/config.toml still covers x86_64 only, so
# their own arm64 path would hit the duplicate-_start failure this line exists to avoid.
export CARGO_TARGET_${ENVA}_RUSTFLAGS="-C link-self-contained=no"

( cd "$WORK/csqtt/rust-server" && cargo +1.97.1 zigbuild --release --target "$TARGET" )

mkdir -p "$OUT"
cp "$WORK/csqtt/rust-server/target/$TARGET/release/csqtt" "$OUT/csqtt-server-linux-$ARCH"
echo "built: $OUT/csqtt-server-linux-$ARCH"
file "$OUT/csqtt-server-linux-$ARCH"
