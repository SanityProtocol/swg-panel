#!/usr/bin/env bash
# release-manifest.sh — build (and sign) the manifest a box verifies before it installs anything.
#
# WHAT IT COVERS: every file git tracks. Not a curated list of "shipped" files, and that is deliberate.
#
#   The plan (docs/UPDATE-RESILIENCE-PLAN.md, Phase A) first said to generate this from the canonical
#   shipped-file set in nix/package.nix. That would have made this the SIXTH place naming shipped files —
#   .campaign/shipped-assets-audit.mjs already exists because the five that came before drifted, and a
#   sixth reader of the same fact is a sixth chance to disagree with it.
#
#   The tracked tree avoids the question entirely, and it is also what actually arrives: `bootstrap.sh`
#   fetches via `git clone` or via `$REPO/archive/refs/…tar.gz`, and both produce exactly the tracked set
#   (measured 2026-09-13: 243 files, identical). So the manifest describes the thing being verified rather
#   than a description of it.
#
#   It is also STRICTLY MORE than the shipped list: bootstrap.sh, update.sh and the install-*.sh scripts
#   are covered too. Those are how a release is applied, so a manifest that left them out would sign the
#   cargo and not the crane — which is Phase A open question 1, answered.
#
# THE SIGNATURE: ECDSA P-256 over SHA-256, verified with `openssl dgst`. Ed25519 was the first choice and
# is the better primitive, but it cannot be verified by the openssl these boxes actually have: `openssl
# dgst -sign` refuses an Ed25519 key outright ("Key type not supported for this operation") and the form
# that does work, `pkeyutl -rawin`, arrived in OpenSSL 3.0 — which would leave every Debian 11 and Ubuntu
# 20.04 node unable to verify, and therefore, under a fail-closed rule, unable to update. `dgst -sha256`
# works from OpenSSL 1.0.2 onward. Measured, not assumed.
#
#   ⚠️ The algorithm is fixed HERE and in the verifier. It is never read from the signature file — a
#   signature that chooses how it will be checked is not a signature.
#
# Usage:
#   lib/release-manifest.sh generate            → writes MANIFEST.sha256 (run from the repo root)
#   lib/release-manifest.sh sign <private.pem>  → writes MANIFEST.sha256.sig
#   lib/release-manifest.sh check <public.pem>  → verifies both, the way a box will
#
# The private key never lives in this repo and is never handled by this script beyond being read once.
set -euo pipefail

MANIFEST="MANIFEST.sha256"
SIGFILE="MANIFEST.sha256.sig"

die(){ echo "release-manifest: $*" >&2; exit 1; }

generate(){
  command -v git >/dev/null 2>&1 || die "needs git (this runs at release time, from a checkout)"
  [ -d .git ] || die "run from the repository root"
  # sha256sum's own format, so a box verifies with `sha256sum -c` and needs nothing else installed.
  # Sorted by path with LC_ALL=C so the manifest is byte-reproducible: two people on two machines building
  # the same commit get the same file, which is what makes "the manifest changed" mean something.
  #
  # The manifest and its signature are excluded — a file cannot state its own hash, and the signature is
  # made over the manifest after it exists.
  # ⚠️ THIS HASHES THE WORKING TREE, NOT HEAD. That is correct — the working tree is what gets installed,
  # and CI deliberately modifies bootstrap.sh (embedding the public key) immediately before generating. But
  # it means an unrelated uncommitted edit is baked into the signature, and the manifest then goes stale the
  # moment someone commits or reverts it. A warning rather than a refusal, because the CI case above is
  # legitimate; loud, because a silently stale manifest is a valid signature over the wrong tree.
  if [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    echo "release-manifest: ⚠ tracked files are modified — this manifest describes the WORKING TREE:" >&2
    git status --porcelain --untracked-files=no 2>/dev/null | sed 's/^/    /' >&2
    echo "release-manifest:   sign a clean tree for a real release, or the signature covers these edits" >&2
  fi
  git ls-files -z \
    | LC_ALL=C sort -z \
    | while IFS= read -r -d '' f; do
        [ "$f" = "$MANIFEST" ] && continue
        [ "$f" = "$SIGFILE" ] && continue
        sha256sum "$f"
      done > "$MANIFEST.tmp"
  mv -f "$MANIFEST.tmp" "$MANIFEST"
  echo "wrote $MANIFEST ($(wc -l < "$MANIFEST") files)"
}

sign(){
  local key="${1:-}"
  [ -n "$key" ] && [ -f "$key" ] || die "usage: $0 sign <private-key.pem>"
  [ -f "$MANIFEST" ] || die "no $MANIFEST — run 'generate' first"
  command -v openssl >/dev/null 2>&1 || die "needs openssl"
  openssl dgst -sha256 -sign "$key" -out "$SIGFILE.tmp" "$MANIFEST" || die "signing failed"
  mv -f "$SIGFILE.tmp" "$SIGFILE"
  echo "wrote $SIGFILE"
}

check(){
  local pub="${1:-}"
  [ -n "$pub" ] && [ -f "$pub" ] || die "usage: $0 check <public-key.pem>"
  [ -f "$MANIFEST" ] && [ -f "$SIGFILE" ] || die "need both $MANIFEST and $SIGFILE"
  openssl dgst -sha256 -verify "$pub" -signature "$SIGFILE" "$MANIFEST" >/dev/null \
    || die "SIGNATURE DOES NOT VERIFY against $pub"
  sha256sum -c --quiet "$MANIFEST" || die "a tracked file does not match the manifest"
  echo "manifest verified against $pub, and every file matches"
}

case "${1:-}" in
  generate) generate ;;
  sign)     shift; sign "$@" ;;
  check)    shift; check "$@" ;;
  *)        die "usage: $0 {generate|sign <key.pem>|check <pub.pem>}" ;;
esac
