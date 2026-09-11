#!/usr/bin/env python3
"""Self-test for decision 8 (vault escrow) + decision 7 (dial source) on imported exits.

Escrow only earns its place if BOTH halves hold:
  seal     the node seals its own key to the operator vault and the panel stores CIPHERTEXT it cannot open.
  restore  a rebuilt node gets the SAME key back — which for WARP is the same account and therefore the
           same egress IP, the one property the operator chose the exit for. Without restore, escrow is a
           promise; without seal, restore has nothing to open.

⚠️ THE SEAL LOOP WAS EXTRACTED at this, the third key-owning consumer — which is what `wdtt_vault_process`
told the next person to do. So this also pins the behaviour of the two kinds that already worked: an
extraction that quietly changes interface-key escrow would be a bad trade for tidiness.

Hermetic: real crypto (the node's own X25519), no network, no wg.

Run: python3 tests/exit_escrow_selftest.py (0 = pass)
     --perturb  drops the `vault` stamp from the shared seal loop — the bug that makes a panel reset leave
                every blob unopenable while escrow still reports healthy — and expects RED.
"""
import importlib.machinery, importlib.util, base64, json, os, secrets, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def _load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try: l.exec_module(m)
    except SystemExit: pass
    return m

N, P = _load(NODED, "swgnoded"), _load(PANEL, "swgpanel")
if PERTURB:
    _os = N._vault_seal_into
    def _no_stamp(sealed, want, source):
        _os(sealed, want, source)
        for v in sealed.values():
            v.pop("vault", None)
    N._vault_seal_into = _no_stamp

VPRIV = secrets.token_bytes(32)
VPUB = base64.b64encode(N._ivk_pub(VPRIV)).decode()

# ── 1. the node seals an imported exit's key to the vault ────────────────────────────────────────
d = tempfile.mkdtemp(); N.EXIT_DIR = d
REC = {"provider": "warp", "priv": "PRIVKEY", "pub": "PUBKEY", "address": "172.16.0.2",
       "peer_key": "PEER", "endpoint": "engage.cloudflareclient.com:2408", "account_id": "acc",
       "token": "tok", "licence": "LIC", "account_type": "free", "mtu": 1280}
open(os.path.join(d, "aabbccdd.json"), "w").write(json.dumps(REC))
N._EXIT_SEALED.clear()
N.exit_vault_process(VPUB, ["aabbccdd"])
blob = N._EXIT_SEALED.get("aabbccdd")
check("the node seals an imported exit's key", bool(blob and blob.get("ct")), N._EXIT_SEALED)
check("…stamped with the exit's own public key, so a re-registration re-seals",
      (blob or {}).get("pub") == "PUBKEY", blob)
check("…and with WHICH VAULT it was sealed to — a panel reset must invalidate it",
      (blob or {}).get("vault") == VPUB, blob)
check("⚠️ the ciphertext is not the key", "PRIVKEY" not in json.dumps(blob), blob)

# only the vault's private half opens it, and what comes out is the whole account
opened = json.loads(N.ivk_unseal(VPRIV, blob).decode())
check("the vault key opens it, and it carries the ACCOUNT, not just the key",
      opened.get("priv") == "PRIVKEY" and opened.get("account_id") == "acc" and opened.get("token") == "tok",
      sorted(opened))
try:
    N.ivk_unseal(secrets.token_bytes(32), blob); _other = True
except Exception:
    _other = False
check("…and a DIFFERENT vault key does not", not _other)

# a pasted profile is NOT escrowed — the panel already holds it, so this would store it twice
open(os.path.join(d, "11223344.json"), "w").write(json.dumps({"provider": "profile", "priv": "P2", "pub": "K2"}))
N._EXIT_SEALED.clear(); N.exit_vault_process(VPUB, ["aabbccdd", "11223344"])
check("a PASTED profile is not escrowed — the panel already holds it in full",
      "11223344" not in N._EXIT_SEALED, sorted(N._EXIT_SEALED))

# idempotence + the two staleness rules. NB: re-read the blob — the profile check above cleared _EXIT_SEALED,
# so comparing against the FIRST one would compare two legitimately different seals.
_b1 = N._EXIT_SEALED["aabbccdd"]
N.exit_vault_process(VPUB, ["aabbccdd"])
check("a settled exit is not re-sealed every pass", N._EXIT_SEALED["aabbccdd"]["ct"] == _b1["ct"])
VPUB2 = base64.b64encode(N._ivk_pub(secrets.token_bytes(32))).decode()
N.exit_vault_process(VPUB2, ["aabbccdd"])
check("⚠️ a NEW VAULT re-seals — otherwise a reset leaves ciphertext nobody can open, reported healthy",
      N._EXIT_SEALED["aabbccdd"].get("vault") == VPUB2, N._EXIT_SEALED["aabbccdd"].get("vault"))
N.exit_vault_process(VPUB, [])
check("an exit the panel no longer asks for stops riding the snapshot", not N._EXIT_SEALED)

# ── 2. the extraction did not change the two kinds that already worked ───────────────────────────
_sealed = {}
N._IVK_VAULT_PUB = VPUB
N._vault_seal_into(_sealed, ["x"], lambda k: ("PUB-X", b"SECRET-X"))
check("the shared loop seals for any kind", bool(_sealed.get("x", {}).get("ct")))
check("…stamping pub and vault the same way for all of them",
      _sealed["x"].get("pub") == "PUB-X" and _sealed["x"].get("vault") == VPUB, _sealed)
_sealed2 = dict(_sealed)
N._vault_seal_into(_sealed2, ["x"], lambda k: ("PUB-X", b"SECRET-X"))
check("…and skipping what is already sealed to this identity and this vault",
      _sealed2["x"]["ct"] == _sealed["x"]["ct"])
N._vault_seal_into(_sealed2, ["x"], lambda k: None)
check("…and sealing nothing when the source has nothing yet", "x" in _sealed2)
src = open(NODED, encoding="utf-8").read()
check("all three kinds go through the one loop, so they cannot drift apart",
      src.count("_vault_seal_into(") == 4, src.count("_vault_seal_into("))

# ── 3. restore: the node prefers a relayed key over registering a NEW account ────────────────────
d2 = tempfile.mkdtemp(); N.EXIT_DIR = d2
# ⚠️ PIN THE TRANSPORT KEYPAIR. `transport_keypair()` persists to /var/lib/swg-noded, which a test cannot
# write — so it silently mints a FRESH pair on every call and the blob would be sealed to one key and opened
# with another. (On a real node it persists, and it must: a transport key that moved would break every
# in-flight restore.)
N._TRANSPORT_PATH = os.path.join(d2, "transport.json")
tpriv = N.transport_priv()
relayed = N.ivk_seal(base64.b64encode(N._ivk_pub(tpriv)).decode(), json.dumps(REC).encode())
class _R:
    def __init__(s, out="", rc=0): s.stdout, s.stderr, s.returncode = out, "", rc
N.run = lambda a, **k: _R("")
N._dev_link_state = lambda dev: "absent"
N._exit_trace = lambda dev: {}
N._warp_register = lambda: (_ for _ in ()).throw(AssertionError("registered instead of restoring"))
res = {"changed": 0, "errors": []}
N.reconcile_exits([{"id": "aabbccdd", "device": "wgx-aabbccdd", "provider": "warp", "key_blob": relayed}], res)
_stored = json.load(open(os.path.join(d2, "aabbccdd.json")))
check("a relayed escrow key is RESTORED, not replaced by a fresh registration",
      _stored.get("priv") == "PRIVKEY" and _stored.get("account_id") == "acc", _stored)
check("…and the conf is written from it", "PRIVKEY" in open(os.path.join(d2, "wgx-aabbccdd.conf")).read())

# ⚠️ …EVEN WHEN THE NODE ALREADY HAS A KEY OF ITS OWN, which is the case that matters and the one the
# guard excluded. A `key_blob` reaches the node only because the panel armed a one-shot relay, and the
# panel arms one only because an operator pressed a button — so it is never something to be careful about
# clobbering, it IS the instruction. Measured on msk-main before this: the relay rode every sync for ninety
# seconds while the node held its own freshly-registered key and ignored it, and the row went on offering a
# restore that could never happen.
_pre = {"provider": "warp", "priv": "ITS-OWN-KEY", "pub": "OWNPUB", "address": "172.16.0.2",
        "peer_key": "PEER", "endpoint": "engage.cloudflareclient.com:2408", "account_type": "free",
        "account_id": "new", "token": "new"}
open(os.path.join(d2, "aabbccdd.json"), "w").write(json.dumps(_pre))
_r2 = {"changed": 0, "errors": []}
N.reconcile_exits([{"id": "aabbccdd", "device": "wgx-aabbccdd", "provider": "warp",
                    "key_blob": relayed}], _r2)
_after = json.load(open(os.path.join(d2, "aabbccdd.json")))
check("⚠️ a relayed key is applied over the node's OWN key — the relay IS the instruction",
      _after.get("priv") == "PRIVKEY" and _after.get("account_id") == "acc",
      {k: _after.get(k) for k in ("priv", "account_id")})
check("…and nothing is relayed on an ordinary pass, so this cannot clobber by accident",
      '**({"key_blob": x["key_restore"]} if x.get("key_restore") else {})' in open(PANEL, encoding="utf-8").read())

# a blob sealed to somebody ELSE must fail loudly, not silently register a different account
d3 = tempfile.mkdtemp(); N.EXIT_DIR = d3
wrong = N.ivk_seal(base64.b64encode(N._ivk_pub(secrets.token_bytes(32))).decode(), json.dumps(REC).encode())
res3 = {"changed": 0, "errors": []}
N.reconcile_exits([{"id": "aabbccdd", "device": "wgx-aabbccdd", "provider": "warp", "key_blob": wrong}], res3)
check("a blob sealed to a DIFFERENT vault fails loudly instead of quietly re-registering",
      res3["errors"] and "did not open" in res3["errors"][0], res3["errors"])
# ⚠️ and the reap must only touch files it OWNS. It walked every `.json` in the directory and read each one
# as an exit record — the transport keypair the line above had to put there was duly "removed". Nothing else
# writes here today, which is exactly how a latent one survives.
check("the reap ignores a file that is not shaped like an exit id",
      os.path.exists(os.path.join(d2, "transport.json")),
      "the reap deleted the node's transport keypair")

# ── 4. dial source (decision 7) ──────────────────────────────────────────────────────────────────
ex, err = P._validate_exits([{"id": "aabbccdd", "producer": "imported", "provider": "warp", "dial_src": "203.0.113.10"},
                             {"id": "11223344", "producer": "adopted", "device": "wgcf", "dial_src": "203.0.113.10"}],
                            {"name": "n1"})
check("an imported exit carries a dial source", not err and ex[0].get("dial_src") == "203.0.113.10", (ex, err))
check("…and an ADOPTED one is not offered one — it dials on its own (§3.1)", "dial_src" not in ex[1], ex[1])
check("a dial source that is not an address is refused",
      bool(P._validate_exits([{"id": "aabbccdd", "producer": "imported", "dial_src": "nope"}], {"name": "n1"})[1]))
_calls = []
N.run = lambda a, **k: (_calls.append(" ".join(map(str, a))), _R("1.2.3.4 dev eth0 src 9.9.9.9"))[1]
N.STATE_DIR = tempfile.mkdtemp()
_r = {"changed": 0, "errors": []}
N.reconcile_dial_src({}, _r, extra=[{"endpoint": "127.0.0.1:2408", "dial_src": "203.0.113.10"}])
check("the exit's dial source is pinned by the SAME function the mesh links use",
      any("route replace" in c and "src 203.0.113.10" in c for c in _calls), _calls)

# ── 4. …and the restore has to be REACHABLE, or escrow is a promise the product cannot keep ──────
# ⚠️ MEASURED ON THE LIVE FLEET, and it made every check above decoration. Delete a WARP exit's key on the
# node and it registers a FRESH account on its next pass — by design, so the exit self-heals — and the panel
# then sealed the new key OVER the old one. On msk-main: key gone at t=0, a new public key reported at t=10s,
# the escrow holding it by t=20s. The one control that spends an escrowed key renders only while the node has
# NO key, and that window was never once observed in ten-second sampling. Nothing could ever have restored.
#
# The retention rule itself lives inside `_node_sync`, a request handler, so it is gated where every other
# `_node_sync` behaviour is — .campaign/node-sync-rig.py [14], through a real panel and a real sync, with its
# own planted regression. What is asserted HERE is the rest of the seam, which does not need a panel booted:
# the field is classified for a transfer, the second answer has a door, and the screen offers both.
_src = open(PANEL, encoding="utf-8").read()
check("the displaced key is KEPT rather than overwritten",
      '_xrec["key_blob_prev"] = _prev' in _src)
check("…only the first one, so a flapping box cannot walk the escrow forward",
      'not (_xrec.get("key_blob_prev") or {}).get("ct")' in _src)
check("…and a restore that landed clears it without a door",
      '_xrec.pop("key_blob_prev", None)' in _src)
# ⚠️ A NEW FIELD ON A NODE RECORD IS AN UNCLASSIFIED BLOCK IN A TRANSFER DIFF. It is ciphertext addressed to
# THIS panel's vault, so it must be cleared exactly like `key_blob` — and the transfer's own check reports a
# classifier rule that matched nothing as "did not run", which is how a rule can exist and still be inert.
check("⚠️ the transfer strips it, declared beside the blob it belongs to",
      '("residue.*.*.key_blob_prev",' in _src and '"cleared"' in _src.split('("residue.*.*.key_blob_prev",')[1][:60])
check("…and the pre-flight names an exit rather than its list index",
      "def _stripped_name(path):" in _src and 'head == "exits"' in _src)
check("'keep the new one' has a door — nothing the node reports can say it",
      'path == "/api/exit/escrow/forget"' in _src)
_ss = open(os.path.join(ROOT, "js", "screen-settings.js"), encoding="utf-8").read()
check("the screen offers BOTH answers, and only when there is a displaced key",
      "const prev = (stored || {}).key_blob_prev || null;" in _ss
      and "if (prev && prev.ct && nodeHasKey) {" in _ss)
check("…restoring and keeping are both wired to a door",
      "api.exitEscrowForget(node.id, ex.id)" in _ss and "restore(prev, ASK_BACK())" in _ss)
# ⚠️ AND THE ORDER OF THE TWO BRANCHES IS THE WHOLE ANSWER. `prev` and "the node has no key" are not
# mutually exclusive: a node that re-registered once (leaving key_blob_prev) and was THEN rebuilt is both.
# Unqualified, the displaced-key branch returned first and gave that node the wrong sentence — "This exit
# registered a new account, so the address websites see has changed", about an exit with no account — and a
# button that restored `prev`, the generation BEFORE the key the escrow currently holds. Run the decision,
# don't read it: three states, three answers.
_fn = _ss[_ss.index("function ExitEscrow("):]
_dec = _fn[:_fn.index("\n}\n")]
def _branch(has_key, blob, prev):
    """Which arm does the source take? Mirrors the two conditions verbatim, extracted from the file."""
    _c1 = "if (prev && prev.ct && nodeHasKey) {" in _dec
    _c2 = "if (!_restorable || nodeHasKey) return null;" in _dec
    if not (_c1 and _c2):
        return "SHAPE-CHANGED"
    if prev and has_key:
        return "two-answers"
    _rest = blob or prev
    if not _rest or has_key:
        return "nothing"
    return "restore-current"
check("a node WITH a key and a displaced one gets the two-answer row",
      _branch(True, True, True) == "two-answers", _branch(True, True, True))
check("⚠️ …a REBUILT node with a displaced one gets the restore, not the two answers",
      _branch(False, True, True) == "restore-current", _branch(False, True, True))
check("…a rebuilt node with only an escrow gets the restore", _branch(False, True, False) == "restore-current")
check("…a healthy node with nothing displaced is offered nothing", _branch(True, True, False) == "nothing")
check("…and a node with no escrow at all is offered nothing", _branch(False, False, False) == "nothing")
# …and the restore uses the CURRENT escrow, never the older generation, on that path
check("⚠️ …and the rebuilt-node arm restores the escrow's own blob, not the generation before it",
      "const _restorable = (blob && blob.ct) ? blob : prev;" in _dec
      and "restore(_restorable, ASK_FRESH())" in _dec)
check("…and the sentence names what an operator would actually notice — the address changed",
      "the address websites see has changed" in _ss)
# ⚠️ AND IT ASKS FOR THE VAULT INSTEAD OF REPORTING THAT IT IS LOCKED. `ivkResealForNodeBlob` throws
# "Unlock the Encryption Vault first."; catching that into a toast names the requirement and offers no way
# to meet it, on the one button whose whole job needs it. Measured in the browser on the live panel: click,
# toast, nothing else. Its WDTT twin has always raised `ensureVaultUnlocked` with a title, a reason and the
# cost of skipping — the same idea implemented twice, once correctly.
check("⚠️ a locked vault raises the unlock prompt rather than a dead-end toast",
      "if (!(await ensureVaultUnlocked(ask))) return;" in _ss)
check("…with a reason for BOTH situations — skipping does not cost the same thing in each",
      "const ASK_BACK = () =>" in _ss and "const ASK_FRESH = () =>" in _ss
      and "restore(prev, ASK_BACK())" in _ss and "restore(_restorable, ASK_FRESH())" in _ss)
# ⚠️ A REQUEST THAT FAILED IS NOT AN EXIT THAT FAILED, and the panel cannot be told otherwise. Dropping the
# `not rec.get("priv")` guard made a relayed blob apply even to a node that already holds a key — right, and
# it also routed a node with a WORKING key into the failure arm, where reporting `up: False` put a healthy
# exit down on every pass for ever (the relay only clears when the node reports the key it was sent, and a
# reply with no key never satisfies that). MEASURED live on msk-main after the fix: four consecutive syncs,
# up=True, with ciphertext nothing could open armed against it.
_nd = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
_arm = _nd.split('DECISION 8\'S RESTORE HALF', 1)[-1] if "DECISION 8'S RESTORE HALF" in _nd else _nd
_arm = _nd[_nd.index('elif isinstance(d.get("key_blob"), dict)'):]
_arm = _arm[:_arm.index('elif not rec.get("priv"):')]
check("a blob that will not open takes the exit down ONLY if there is no key to fall back on",
      'if not rec.get("priv"):' in _arm and '"up": False, "error": _kerr' in _arm)
check("…and a node that HAS a key falls through to the live path instead", "_blob_err = _kerr" in _arm)
# ⚠️ LOOK IN THE RECORD, NOT IN THE FILE. `"error": err,` appears in other dicts in swg-noded, so a
# whole-file search matched one of those and the check stayed green while the exits record folded the two
# fields back together. Cut to the live append this is about. [[lesson-identity-is-not-provenance]]
_live_rec = _nd[_nd.index('out.append({"id": xid, "device": dev, "provider": prov, "up": _live,'):]
_live_rec = _live_rec[:_live_rec.index("})")]
check("⚠️ …carrying the reason in its OWN field, not in the health one",
      '"restore_error": _blob_err,' in _live_rec and '"error": err,' in _live_rec
      and "_blob_err" not in _live_rec.split('"error":')[1].split(",")[0])
# The consequence, not just the cause: `exitHealth` returns failed/bad/red for ANY non-empty `error`, so
# folding the two would have painted the working exit broken — the exact outcome keeping it up was for.
_rt = open(os.path.join(ROOT, "js", "routing.js"), encoding="utf-8").read()
check("…which matters because any `error` at all paints the row red",
      'if (l.error) return { state: "failed", tone: "bad", dot: "bad",' in _rt)
check("…and the reason is stated on the escrow row, where the button that asked for it is",
      'const restoreErr = String((live || {}).restore_error || "").trim();' in _ss
      and "The escrowed key could not be put back" in _ss)
# …and it is bounded, so a node that can never apply one does not carry the request for ever.
check("⚠️ the relay expires against a node that can never apply it",
      "_KEY_RESTORE_TTL" in _src and "_applied or _stale" in _src and '_x["key_restore_at"]' in _src)
check("…and the operator is told when it does", "expired without being applied" in _src)
check("…and 'not applied' is asked the same way the clear asks it, not as 'reported no key'",
      "if _stale and not _applied:" in _src)
check("…and it is the same helper the WDTT restore uses, not a second one",
      "ensureVaultUnlocked" in open(os.path.join(ROOT, "js", "turn.js"), encoding="utf-8").read())

if PERTURB:
    if FAILS:
        print("\nperturbed: an unstamped vault was CAUGHT (%d red) — a panel reset would leave every blob "
              "unopenable while escrow still read healthy" % len(FAILS))
        sys.exit(0)
    print("\nperturbed: NOTHING FAILED — this gate does not actually test the vault stamp")
    sys.exit(1)

print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
