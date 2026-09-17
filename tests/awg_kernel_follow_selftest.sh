#!/bin/bash
# Self-test — the AmneziaWG kernel module follows kernel upgrades (docs/AWG-DATAPATH-RESILIENCE-PLAN.md D4). Stubbed
# apt-cache / dpkg-query / dpkg / dkms / apt-get; /boot, /lib/modules and /usr/src pointed at a temp tree.
#   [1] the headers metapackages are the twins of the INSTALLED image metapackages — including the incident (running an
#       older kernel than the metapackage now points at); removed (rc), versioned and `unsigned` images yield nothing
#   [2] ensure_awg_headers_follow: 0 when installed (held too), 10 after installing it (also after ONE refresh of stale lists),
#       1 when there is none, 2 when an install failed
#   [3] awg_dkms_build_all_kernels installs amneziawg (never `dkms autoinstall`, which builds every module on the box) for
#       kernels with both an image and headers
#   [4] awg_dkms_drop_unowned removes only an amneziawg DKMS tree no package owns, and only once the package downloads
#   [5] the source route registers with DKMS (dkms-install → add → build → install) before any `make install`
# Run: bash tests/awg_kernel_follow_selftest.sh     --perturb lets versioned image packages match and drops the refresh-and-retry, expects RED on [1], [2].
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
FAILS=0; check(){ if [ "$2" = 0 ]; then echo "  PASS $1"; else echo "  FAIL $1 ${3:-}"; FAILS=$((FAILS+1)); fi; }
grab(){ awk -v f="$1" '$0 ~ "^"f"\\(\\)\\{" {p=1} p {print} p && /^}$/ {exit}' "$ROOT/lib/common.sh"; }
src="$(grab awg_headers_meta; grab ensure_awg_headers_follow; grab awg_dkms_build_all_kernels; grab awg_dkms_drop_unowned)"
src="${src//\/boot\//$T/boot/}"; src="${src//\/lib\/modules/$T/modules}"; src="${src//\/usr\/src\//$T/src/}"; src="${src//\/var\/lib\/dkms/$T/dkms}"
[ "${1:-}" = "--perturb" ] && src="${src//\$2 ~ \/^ii\/ && /}"   # perturbation: drop the "installed" filter
[ "${1:-}" = "--perturb" ] && src="$(printf '%s\n' "$src" | sed 's/|| { run apt-get update.*; }; then/; then/')"   # …and the refresh-and-retry
mkdir -p "$T/bin" "$T/boot" "$T/modules" "$T/src"
cat > "$T/bin/apt-cache" <<'EOF'
#!/bin/sh
case "$1" in
  rdepends) cat "$SBX/rdepends" ;;
  show) grep -qx "$2" "$SBX/available" ;;
esac
EOF
cat > "$T/bin/dpkg-query" <<'EOF'
#!/bin/sh
p="$3"
case "$p" in 'linux-image-*') cat "$SBX/images" 2>/dev/null; exit 0 ;; esac
grep -qx "$p" "$SBX/installed" 2>/dev/null || exit 0
case "$2" in *Status-Status*) printf 'installed' ;; *) if grep -qx "$p" "$SBX/held" 2>/dev/null; then printf 'hold ok installed'; else printf 'install ok installed'; fi ;; esac
EOF
cat > "$T/bin/apt-get" <<'EOF'
#!/bin/sh
echo "apt-get $*" >> "$SBX/calls"
[ "$1" = update ] && { [ -e "$SBX/refresh-fixes" ] && rm -f "$SBX/stale"; exit 0; }
case " $* " in *" --download-only "*) [ -e "$SBX/nodownload" ] && exit 100; exit 0 ;; esac
[ -e "$SBX/stale" ] && exit 100
for a; do case "$a" in -*|install) ;; *) echo "$a" >> "$SBX/installed" ;; esac; done
EOF
cat > "$T/bin/dkms" <<'EOF'
#!/bin/sh
echo "dkms $*" >> "$SBX/calls"
EOF
cat > "$T/bin/dpkg" <<'EOF'
#!/bin/sh
[ "$1" = -S ] && grep -qx "$2" "$SBX/owned"
EOF
chmod +x "$T/bin/"*
run(){ "$@"; }; have(){ command -v "$1" >/dev/null 2>&1; }
export SBX="$T" PATH="$T/bin:$PATH"; DRYRUN=false
eval "$src"
uname(){ [ "${1:-}" = -r ] && echo 6.8.0-139-generic || command uname "$@"; }
reset(){ : > "$T/calls"; : > "$T/installed"; : > "$T/owned"; : > "$T/available"; : > "$T/images"; rm -rf "$T/boot"/* "$T/modules"/* "$T/src"/*; rm -f "$T/stale" "$T/refresh-fixes" "$T/held" "$T/nodownload"; rm -rf "$T/dkms"; }
# [1] — the metapackages come from what is INSTALLED, not from what depends on the running kernel
reset; printf 'linux-image-6.8.0-138-generic ii \nlinux-image-6.8.0-139-generic ii \nlinux-image-virtual ii \n' > "$T/images"; printf 'linux-headers-virtual\n' > "$T/available"
check "[1] the incident: running 138, virtual already on 139 → linux-headers-virtual" "$([ "$(awg_headers_meta)" = linux-headers-virtual ]; echo $?)" "got '$(awg_headers_meta)'"
reset; printf 'linux-image-6.1.0-53-cloud-amd64 ii \nlinux-image-cloud-amd64 ii \nlinux-image-amd64 ii \n' > "$T/images"; printf 'linux-headers-cloud-amd64\nlinux-headers-amd64\n' > "$T/available"
check "[1] Debian, two image metapackages → both twins" "$([ "$(awg_headers_meta | sort | tr '\n' ' ')" = "linux-headers-amd64 linux-headers-cloud-amd64 " ]; echo $?)" "got '$(awg_headers_meta | tr '\n' ' ')'"
reset; printf 'linux-image-virtual rc \nlinux-image-unsigned-6.8.0-139-generic ii \nlinux-image-6.8.0-139-generic ii \n' > "$T/images"; printf 'linux-headers-virtual\n' > "$T/available"
check "[1] removed (rc) metapackage, unsigned and versioned images → nothing" "$([ -z "$(awg_headers_meta)" ]; echo $?)" "got '$(awg_headers_meta)'"
# [2]
reset; printf 'linux-image-virtual ii \n' > "$T/images"; echo linux-headers-virtual > "$T/available"
ensure_awg_headers_follow; r=$?; check "[2] missing → installed, rc 10" "$([ $r = 10 ] && grep -q 'install .*linux-headers-virtual' "$T/calls"; echo $?)" "rc=$r $(cat "$T/calls")"
: > "$T/calls"; ensure_awg_headers_follow; r=$?; check "[2] present → rc 0, no apt" "$([ $r = 0 ] && [ ! -s "$T/calls" ]; echo $?)" "rc=$r"
echo linux-headers-virtual > "$T/held"; : > "$T/calls"; ensure_awg_headers_follow; r=$?
check "[2] present and HELD (dpkg: 'hold ok installed') → rc 0, no apt" "$([ $r = 0 ] && [ ! -s "$T/calls" ]; echo $?)" "rc=$r $(cat "$T/calls")"
reset; : > "$T/images"; ensure_awg_headers_follow; r=$?; check "[2] none → rc 1" "$([ $r = 1 ]; echo $?)" "rc=$r"
# [2] the lists this box last fetched name a headers version the mirror dropped: ONE refresh, one retry
reset; printf 'linux-image-virtual ii \n' > "$T/images"; echo linux-headers-virtual > "$T/available"; : > "$T/stale"; : > "$T/refresh-fixes"
ensure_awg_headers_follow; r=$?; check "[2] stale lists → one apt-get update, the retry installs it, rc 10" "$([ $r = 10 ] && [ "$(grep -c 'apt-get update' "$T/calls")" = 1 ] && grep -qx linux-headers-virtual "$T/installed"; echo $?)" "rc=$r $(cat "$T/calls")"
reset; printf 'linux-image-virtual ii \n' > "$T/images"; echo linux-headers-virtual > "$T/available"; : > "$T/stale"
ensure_awg_headers_follow; r=$?; check "[2] a refresh that does not help → rc 2 (failed) after exactly one update" "$([ $r = 2 ] && [ "$(grep -c 'apt-get update' "$T/calls")" = 1 ]; echo $?)" "rc=$r $(cat "$T/calls")"
# [3]
reset; for k in 6.8.0-138-generic 6.8.0-139-generic 6.8.0-140-generic; do mkdir -p "$T/modules/$k"; done
: > "$T/boot/vmlinuz-6.8.0-138-generic"; : > "$T/boot/vmlinuz-6.8.0-139-generic"; ln -s /nonexistent "$T/modules/6.8.0-139-generic/build"; mkdir "$T/modules/6.8.0-138-generic/build"; mkdir "$T/modules/6.8.0-140-generic/build"
mkdir -p "$T/dkms/amneziawg/1.0.0/source" "$T/dkms/amneziawg/kernel-6.8.0-138-generic-x86_64"
awg_dkms_build_all_kernels
check "[3] installs amneziawg for 138 (image + headers) — never autoinstall" "$(grep -qx 'dkms install -m amneziawg -v 1.0.0 -k 6.8.0-138-generic' "$T/calls" && ! grep -q autoinstall "$T/calls"; echo $?)" "$(cat "$T/calls")"
check "[3] skips 139 (headers link dangles) and 140 (no image)" "$(! grep -qE '139|140' "$T/calls"; echo $?)" "$(cat "$T/calls")"
# [4]
plant(){ mkdir -p "$T/src/amneziawg-1.0.0" "$T/src/amneziawg-0.9.9" "$T/src/amneziawg-linux-kernel-module"
  printf 'PACKAGE_NAME="amneziawg"\nPACKAGE_VERSION="1.0.0"\n' > "$T/src/amneziawg-1.0.0/dkms.conf"
  printf 'PACKAGE_NAME="amneziawg"\nPACKAGE_VERSION="0.9.9"\n' > "$T/src/amneziawg-0.9.9/dkms.conf"; echo "$T/src/amneziawg-0.9.9" > "$T/owned"; }
reset; plant; awg_dkms_drop_unowned
check "[4] unowned amneziawg tree removed; package-owned and a non-DKMS checkout kept" "$([ ! -d "$T/src/amneziawg-1.0.0" ] && [ -d "$T/src/amneziawg-0.9.9" ] && [ -d "$T/src/amneziawg-linux-kernel-module" ] && grep -q 'dkms remove amneziawg/1.0.0 --all' "$T/calls" && ! grep -q 'linux-kernel-module' "$T/calls"; echo $?)" "$(cat "$T/calls")"
reset; plant; : > "$T/nodownload"; awg_dkms_drop_unowned
check "[4] the package cannot be downloaded → nothing removed" "$([ -d "$T/src/amneziawg-1.0.0" ] && ! grep -q 'dkms remove' "$T/calls"; echo $?)" "$(cat "$T/calls")"
# [5]
f="$(grab awg_build_from_source)"
check "[5] source route registers through awg_dkms_register_dir, make install only as the other branch" "$(printf '%s' "$f" | grep -q 'awg_dkms_register_dir "$w/mod/src"' && [ "$(printf '%s' "$f" | grep -n 'awg_dkms_register_dir' | head -1 | cut -d: -f1)" -lt "$(printf '%s' "$f" | grep -n 'make -C "$w/mod/src" install' | head -1 | cut -d: -f1)" ]; echo $?)"
r="$(grab awg_dkms_register_dir)"
i1=$(printf '%s' "$r" | grep -n 'dkms-install' | cut -d: -f1 | head -1); i2=$(printf '%s' "$r" | grep -n 'dkms add' | cut -d: -f1 | head -1); i3=$(printf '%s' "$r" | grep -n 'dkms install -m' | cut -d: -f1 | head -1)
check "[5] register_dir: dkms-install → add → install, then every kernel" "$([ -n "$i1" ] && [ "$i1" -le "$i2" ] && [ "$i2" -le "$i3" ] && printf '%s' "$r" | grep -q awg_dkms_build_all_kernels; echo $?)" "$i1 $i2 $i3"
# [6] register_source never clones when a tree is registered; the heal only migrates when no package can own the module
eval "$(grab awg_dkms_register_source)"; git_clone_depth1(){ echo "clone $*" >> "$T/calls"; return 1; }
reset; printf '#!/bin/sh\necho "dkms $*" >> "$SBX/calls"; [ "$1" = status ] && echo "amneziawg/1.0.0, 6.8.0-139-generic, x86_64: installed"\n' > "$T/bin/dkms"; chmod +x "$T/bin/dkms"
have(){ case "$1" in git|make) return 0;; *) command -v "$1" >/dev/null 2>&1;; esac; }
awg_dkms_register_source; r=$?
check "[6] a registered tree → no clone, rc 1" "$([ $r = 1 ] && ! grep -q clone "$T/calls"; echo $?)" "rc=$r $(cat "$T/calls")"
u="$(awk '/^ensure_awg_datapath\(\)\{/,/^}$/' "$ROOT/update.sh")"
check "[6] heal migrates only with no registered tree and no installable package, before the early return" "$(printf '%s' "$u" | grep -q '\[ -z "$(dkms status amneziawg 2>/dev/null)" \] && ! apt-cache show amneziawg-dkms' && [ "$(printf '%s' "$u" | grep -n awg_dkms_register_source | head -1 | cut -d: -f1)" -lt "$(printf '%s' "$u" | grep -n '"$_mod" = yes \] && return 0' | cut -d: -f1 | tail -1)" ]; echo $?)"
# [7] every caller survives `set -e`: these functions return non-zero on NORMAL paths, so a bare call aborts the script that
#     runs it (update.sh and both installers are `set -euo pipefail`). A regex over the code with its comments stripped —
#     the failure is the CALL SITE, and a `#` inside `${v#x}` or `$#` is not a comment.
bare=""
for fnn in ensure_awg_headers_follow awg_go_needs_install awg_go_pinned awg_kernel_takes awg_dkms_register_source; do
  for f in update.sh install-host.sh install-node.sh lib/common.sh; do
    t="$ROOT/$f"; [ "${1:-}" = "--perturb" ] && [ "$f" = update.sh ] && { sed 's/_hf=0; ensure_awg_headers_follow || _hf=\$?; case \$_hf in/ensure_awg_headers_follow; case $? in/' "$ROOT/$f" > "$T/perturbed-update.sh"; t="$T/perturbed-update.sh"; }
    while IFS= read -r ln; do
      code="$(printf '%s' "$ln" | sed -E 's/(^|[[:space:]])#.*$//')"
      printf '%s' "$code" | grep -qE "(^|[^_a-z])$fnn([^(_a-z]|\$)" || continue
      printf '%s' "$code" | grep -qE "$fnn.*(\|\||&&)|(if|elif|while|until)[[:space:]]+(! )?$fnn|(\|\||&&)[[:space:]]*(! )?$fnn" || bare="$bare $f:$fnn"
    done < <(grep -E "(^|[^_a-z])$fnn([^(_a-z]|\$)" "$t")
  done
done
check "[7] no bare call, under set -e, of a function that returns non-zero on normal paths" "$([ -z "$bare" ]; echo $?)" "bare:$bare"
echo; [ "$FAILS" = 0 ] && echo "GREEN — 0 failed" || echo "RED — $FAILS failed"; [ "$FAILS" = 0 ]
