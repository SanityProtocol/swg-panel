#!/bin/bash
# awg_compat_build_matrix.sh — NOT a selftest (it needs Docker and the network): builds upstream's AmneziaWG kernel module
# against real distro kernel headers, unpatched and with lib/common.sh awg_compat_patch (upstream PR #218), and asserts AT
# COMPILE TIME that its signature detection picks the form each kernel's header declares. A successful build alone proves
# nothing here: both branches compile (they cast), so a wrong choice would build and then crash the kernel at runtime.
# Run it when upstream's compat.h moves, or before trusting the fix on a new distro kernel:
#     bash tests/awg_compat_build_matrix.sh
# One line per kernel: header form (setup / release) · unpatched build · patch applied · patched build · detection check.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INNER="$(mktemp)"; trap 'rm -f "$INNER"' EXIT
cat > "$INNER" <<'INNEREOF'
# inside a container (or on the host): build upstream's module for every kernel with headers, unpatched and patched,
# and assert at compile time that PR #218's detection picks the form each kernel's header DECLARES.
set -u
SRC=/tmp/awgsrc; [ -d $SRC ] || git clone -q --depth 1 https://github.com/amnezia-vpn/amneziawg-linux-kernel-module $SRC
fn="$(sed -n '/^AWG_COMPAT_MARK=/,/^}/p' /repo/lib/common.sh)"
for B in /lib/modules/*/build; do
  KV="$(basename "$(dirname "$B")")"; H="$B/include/net/udp_tunnel.h"
  [ -f "$H" ] || H="$(dirname "$B")/source/include/net/udp_tunnel.h"   # Debian: arch headers in build/, the rest in source/
  [ -f "$H" ] || { echo "$KV: no udp_tunnel.h"; continue; }
  es=0; grep -Eq 'void setup_udp_tunnel_sock\(struct net \*net, struct sock \*' "$H" && es=1
  er=0; grep -Eq 'void udp_tunnel_sock_release\(struct sock \*' "$H" && er=1
  rm -rf /tmp/b1 /tmp/b2 /tmp/b3; cp -r $SRC /tmp/b1; cp -r $SRC /tmp/b2
  make -s -j4 -C "$B" M=/tmp/b1/src modules >/tmp/b1.log 2>&1 && u=OK || u=FAIL
  bash -c 'have(){ command -v "$1" >/dev/null 2>&1; }; DRYRUN=false; '"$fn"'; awg_compat_patch /tmp/b2/src' && pa=applied || pa=NOT-APPLIED
  make -s -j4 -C "$B" M=/tmp/b2/src modules >/tmp/b2.log 2>&1 && p=OK || p=FAIL
  mkdir -p /tmp/b3; cat > /tmp/b3/chk.c <<C
#include <linux/module.h>
#include <net/udp_tunnel.h>
#define SETUP_SOCK __builtin_types_compatible_p(typeof(&setup_udp_tunnel_sock), void (*)(struct net *, struct sock *, struct udp_tunnel_sock_cfg *))
#define SETUP_SOCKET __builtin_types_compatible_p(typeof(&setup_udp_tunnel_sock), void (*)(struct net *, struct socket *, struct udp_tunnel_sock_cfg *))
#define REL_SOCK __builtin_types_compatible_p(typeof(&udp_tunnel_sock_release), void (*)(struct sock *))
#define REL_SOCKET __builtin_types_compatible_p(typeof(&udp_tunnel_sock_release), void (*)(struct socket *))
_Static_assert(SETUP_SOCK != SETUP_SOCKET, "setup: exactly one form must match");
_Static_assert(REL_SOCK != REL_SOCKET, "release: exactly one form must match");
_Static_assert(SETUP_SOCK == $es, "setup: detection disagrees with the header");
_Static_assert(REL_SOCK == $er, "release: detection disagrees with the header");
MODULE_LICENSE("GPL");
C
  echo 'obj-m := chk.o' > /tmp/b3/Makefile
  make -s -C "$B" M=/tmp/b3 modules >/tmp/b3.log 2>&1 && c=OK || c="FAIL($(grep -o 'error: static assertion failed: "[^"]*"' /tmp/b3.log | head -1))"
  why=""; [ "$p" = FAIL ] && why=" :: $(grep -m1 -E 'error' /tmp/b2.log | cut -c1-140)"
  echo "$KV | header: setup=$( [ $es = 1 ] && echo sock || echo socket ) release=$( [ $er = 1 ] && echo sock || echo socket ) | unpatched=$u | patch=$pa | patched=$p | detection-check=$c$why"
done
INNEREOF
run(){ local img="$1"; shift; echo "===== $img $*"
  docker run --rm -v "$ROOT":/repo:ro -v "$INNER":/inner.sh:ro "$img" bash -c "export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq >/dev/null 2>&1; apt-get install -y -qq gcc make git ca-certificates python3 $* >/tmp/apt.log 2>&1 || tail -3 /tmp/apt.log
    bash /inner.sh" 2>&1 | grep -v '^\(Unable to find\|.*Pull\|Digest\|Status\)'; }
OLD26="$(docker run --rm ubuntu:26.04 bash -c "apt-get update -qq >/dev/null 2>&1; apt-cache search --names-only '^linux-headers-7\.0\.0-[0-9]+-generic\$' | awk '{print \$1}' | sort -V | head -1")"
run ubuntu:26.04 linux-headers-generic $OLD26
run ubuntu:24.04 linux-headers-generic linux-headers-generic-hwe-24.04
run debian:trixie linux-headers-amd64
run debian:bookworm linux-headers-amd64
