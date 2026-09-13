#!/usr/bin/env bash
# verify-release.sh — fail if this tree is not a release a box could verify.
#
# Signing is a MANUAL step (see sign-release.yml: main carries one squashed commit per release, so a bot
# commit per push is not available to us). A manual step can be forgotten, and forgetting this one ships a
# release that every future fail-closed install would refuse. So `main` is checked instead: you can still
# forget to sign, and you find out loudly and immediately rather than from an operator months later.
#
# ⚠️ IT RUNS THE SHIPPED VERIFIER, NOT A COPY OF IT. The check that guards releases and the check a box
# performs have to be the same check — two readers of one grammar, where a second implementation is free to
# drift into agreeing with nothing. So verify_fetched_tree() is lifted out of bootstrap.sh and run here
# against this checkout, exactly as it runs against a freshly fetched tree on a node.
#
# ⚠️ IT IS ALSO WHAT CATCHES A STALE MANIFEST, which is worse than a missing one: a signature made at an
# earlier commit is still a VALID signature, over the wrong tree. `sha256sum -c` inside the shipped verifier
# is what notices, and it notices here rather than on every install.
#
# Self-activating: while bootstrap.sh carries no release key, nothing can be signed and this exits clean.
# The first signed release turns it on permanently, with no second switch to remember to flip.
set -euo pipefail

BOOT="${1:-bootstrap.sh}"

if ! grep -q 'BEGIN PUBLIC KEY' "$BOOT"; then
  echo "::notice::release signing is not live yet — $BOOT carries no release key, so there is nothing to require"
  exit 0
fi

for f in MANIFEST.sha256 MANIFEST.sha256.sig; do
  [ -f "$f" ] || {
    echo "::error::$f is missing, but $BOOT carries a release key — run the sign-release workflow on dev, then squash to main"
    exit 1
  }
done

TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT

# Lift the real functions out of the real bootstrap.sh. An extraction that silently found nothing would
# make this whole check pass while verifying nothing at all, so a miss is fatal, not empty.
python3 - "$BOOT" "$TMPD/verify.sh" <<'PY'
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
parts = ['die(){  echo "::error::$*" >&2; exit 1; }',
         'warn(){ echo "::warning::$*" >&2; }',
         'info(){ echo "$*"; }',
         'need(){ command -v "$1" >/dev/null 2>&1; }',
         'REF="${GITHUB_REF_NAME:-this tree}"',
         'TMP="$(mktemp -d)"']
m = re.search(r'^RELEASE_KEYS_D=.*$', src, re.M)
if not m:
    sys.exit("::error::RELEASE_KEYS_D not found in bootstrap.sh — it has drifted")
parts.append(m.group(0))
for name in ("emit_release_keys", "verify_fetched_tree"):
    f = re.search(r"^%s\(\)\{.*?^\}" % name, src, re.S | re.M)
    if not f:
        sys.exit("::error::%s() not found in bootstrap.sh — it has drifted" % name)
    parts.append(f.group(0))
parts.append("verify_fetched_tree")
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(parts) + "\n")
PY

# SWG_SKIP_VERIFY would make the shipped verifier return success without checking anything. It exists for
# operators stuck on a box, never for the gate that decides whether a release is publishable.
#
# The verifier's own words are written for someone watching an install ("re-run to fetch it again"), which
# is the right message there and the wrong one here. Reusing it is still correct — one implementation, not
# two that can drift — so the CI-shaped explanation is added AFTER it rather than by forking its text.
if ! env -u SWG_SKIP_VERIFY bash "$TMPD/verify.sh"; then
  echo "::error::On main this almost always means the manifest is STALE — the tree was signed, then more commits landed on top. A signature made at an earlier commit is still a VALID signature over the WRONG tree, which is why it has to be caught here. Re-run the sign-release workflow on dev, then squash to main again."
  exit 1
fi
echo "this tree is a verifiable release"
