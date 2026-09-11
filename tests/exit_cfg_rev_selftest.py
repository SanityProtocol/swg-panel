"""Self-test — TWO STATES THAT WERE LYING ON THE EXITS SCREEN.

**1. "This peer has never answered" for a peer that had just answered.**
The node reports a handshake as an AGE in seconds and reserves 0 for NEVER — but it computed that age as
`now - timestamp`, which IS 0 for the whole second after every rekey. WireGuard rehandshakes about every two
minutes, so on a fleet of five exits one of them wore an amber fault triangle roughly every 24 seconds. It
was reported as "saving anything makes all the WARP exits go to error for a few seconds", because a save is
when an operator is looking at the screen; the save had nothing to do with it.

MEASURED on msk-main before the fix. Polling `/api/state` every 300 ms across a save: exit f2d8ae24 went
95 -> **0** -> 5, e52aab6d 96 -> **0** -> 6, f6397fdc 119 -> **0**, 736a24bf 115 -> **0** -> 25 — each
exactly once, at its own rekey. Polling the box's own `wg show <dev> latest-handshakes` every 200 ms for
200 s in the same period found **zero** zero-timestamps: the kernel never said never, the arithmetic did.
f2d8ae24's handshake landed at epoch 1789041083 and the node sampled it inside that second.

**2. A verdict about the config you had just replaced.**
`error`, `up` and `handshake` all describe whatever the node last converged on, so for the seconds between
a save and the node's next pass the row stated the OLD verdict with full confidence — green for a profile
that no longer existed, or the previous paste's failure against the paste that fixes it. The panel now
stamps each imported exit with a digest of the material the node is sent, the node echoes back the one it
is working to, and the row circles ("Applying your changes on the node…") until they agree.

Run: python3 tests/exit_cfg_rev_selftest.py      (0 = pass)
     --perturb   restores the 0-floor and stamps only the ordinary report path, and expects RED.
"""
import importlib.machinery, importlib.util, json, os, re, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

NSRC = open(NODED, encoding="utf-8").read()
PSRC = open(PANEL, encoding="utf-8").read()

# ⚠️ ASSERT EVERY ANCHOR EXISTS BEFORE TOUCHING IT. A perturbation that silently matches nothing leaves the
# code intact and the run reads as a clean PASS while measuring the unperturbed tree.
_FLOOR = "return 0 if ts == 0 else max(1, int(time.time()) - ts)"
_STAMP = '''    _sigs = {xid: str((d or {}).get("cfg_sig") or "") for xid, d in want.items()}
    for _o in out:
        _o["cfg_sig"] = _sigs.get(str(_o.get("id") or ""), "")'''
assert NSRC.count(_FLOOR) == 1, "handshake-floor anchor missing — this run would FALSE-PASS"
assert NSRC.count(_STAMP) == 1, "cfg_sig stamp anchor missing — this run would FALSE-PASS"
if PERTURB:
    NSRC = NSRC.replace(_FLOOR, "return 0 if ts == 0 else max(0, int(time.time()) - ts)")
    NSRC = NSRC.replace(_STAMP, "    pass")

npath = NODED
if PERTURB:
    _fd, npath = tempfile.mkstemp(suffix=".py", prefix="cfgrev-", dir=HERE)
    os.write(_fd, NSRC.encode()); os.close(_fd)

def _load(p, n):
    l = importlib.machinery.SourceFileLoader(n, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(n, l))
    try: l.exec_module(m)
    except SystemExit: pass
    return m

P = _load(PANEL, "swgpanel")
N = _load(npath, "swgnoded")
if PERTURB:
    os.unlink(npath)


class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


print("[1] the handshake age can never be mistaken for the NEVER sentinel")
KEY = "ZtVPNeJM8Gsneelu4sijDrDz3AVt7uZb9IbtK71Q6xc="
N._link_kind = lambda dev: "wg"
def _hs(ts):
    N.run = lambda cmd, **kw: R(0, "%s\t%s\n" % (KEY, ts))
    return N._exit_handshake({}, "wgx-test")

now = int(time.time())
check("a handshake THIS SECOND is not 'never'", _hs(now) != 0, _hs(now))
check("…it reads as one second", _hs(now) == 1, _hs(now))
check("an older handshake still reads its real age", 40 <= _hs(now - 42) <= 44, _hs(now - 42))
# The same collapse, reached from the other side: NTP steps a node's clock back over the timestamp and
# `max(0, …)` turned that into "this peer has never answered" too.
check("a clock that stepped backwards is not 'never' either", _hs(now + 30) == 1, _hs(now + 30))
check("0 STILL MEANS NEVER — the sentinel is not what was wrong", _hs(0) == 0, _hs(0))
N.run = lambda cmd, **kw: R(1, "", "Unable to access interface: Operation not supported")
check("a device neither tool can read reports 'cannot say', not 'never'",
      N._exit_handshake({}, "wgx-test") is None, N._exit_handshake({}, "wgx-test"))

print("\n[2] the panel stamps what the NODE is given, and nothing else")
NODE = {"id": "n1", "name": "n1", "exits": []}
PROF = """[Interface]
PrivateKey = QFm3Jt5Rrn6f0aX1sVYQK0lZ2p8vJcU7dHwEbNqTsGk=
Address = 10.77.0.2/32
MTU = 1280

[Peer]
PublicKey = %s
AllowedIPs = 0.0.0.0/0
Endpoint = %s
"""
def clean(exits, prev=()):
    c, e = P._validate_exits(exits, NODE, prev=prev)
    assert e is None, e
    return c

def one(**kw):
    # ⚠️ A REAL ID. `_validate_exits` MINTS one for anything that is not 8 hex, and the device is derived
    # from it — so a made-up id gives every call a different device and a different digest, and the two
    # stability checks below would fail against perfectly good code. (They did.)
    base = {"id": "aabbccdd", "producer": "imported", "provider": "profile", "label": "first",
            "enabled": True, "profile_text": PROF % (KEY, "203.0.113.9:51820")}
    return clean([dict(base, **kw)])[0]

base = one()
check("an imported exit carries a revision", bool(base.get("cfg_sig")), base.get("cfg_sig"))
check("…the same input twice gives the same one (or every save spins)",
      one()["cfg_sig"] == base["cfg_sig"])
check("renaming it does NOT — the node has no work to do",
      one(label="renamed")["cfg_sig"] == base["cfg_sig"])
check("changing the endpoint DOES",
      one(profile_text=PROF % (KEY, "203.0.113.10:51820"))["cfg_sig"] != base["cfg_sig"])
check("disabling it DOES — the node takes the tunnel down",
      one(enabled=False)["cfg_sig"] != base["cfg_sig"])
check("a WARP+ licence DOES", one(provider="warp", licence="A-B-C")["cfg_sig"]
      != one(provider="warp")["cfg_sig"])
check("the dial source DOES", one(dial_src="10.0.0.7")["cfg_sig"] != base["cfg_sig"])
ad = clean([{"id": "bbccddee", "producer": "adopted", "device": "tun-lab0", "enabled": True}])[0]
check("an adopted exit gets none — nothing is sent to the node for it", "cfg_sig" not in ad, ad)
# Re-pasting the SAME profile must land on the same digest, or a label edit (which re-submits the textarea)
# would spin the row. The sentinel path is the one the editor actually uses.
_sent = (PROF % (KEY, "203.0.113.9:51820")).replace(
    "QFm3Jt5Rrn6f0aX1sVYQK0lZ2p8vJcU7dHwEbNqTsGk=", P.EXIT_KEY_KEEP)
kept = clean([dict(base, profile_text=_sent)], prev=[base])[0]
check("re-submitting the editor's own text (key sentinel and all) is not a change",
      kept["cfg_sig"] == base["cfg_sig"], (kept["cfg_sig"], base["cfg_sig"]))

print("\n[3] the seam — it has to survive the trip to the node and back")
# ⚠️ A WHITELIST IS WHERE A NEW FIELD DIES QUIETLY, and both ends can be green while the wire carries
# nothing. The panel builds the node's `exits` payload key by key.
check("the sync payload ships it", '"cfg_sig": x.get("cfg_sig") or "",' in PSRC)
check("/api/state ships the stored record whole (so the browser sees it)",
      '"exits": [dict({k: v for k, v in e.items() if k != "profile"},' in PSRC)

# ⚠️ THE COVERAGE INVARIANT, SAID ONCE, INSTEAD OF TWO LISTS THAT AGREE TODAY. The digest's whole claim is
# "if this is unchanged, the node has nothing new to apply". That claim is only true while EVERY field the
# node is handed is either in the signed material or deliberately exempt — and the two live 10,000 lines
# apart, one a dict literal in `exit_cfg_sig`, the other a whitelist in the sync payload. Add a field to the
# payload alone and the panel reports "in step" about a config the node has never been given; the row goes
# green on the strength of a digest that does not describe it. Derived from the source both times, so the
# next field cannot be added to one without this going red.
_mat = re.search(r"def exit_cfg_sig\(rec\):(?:.|\n)*?\n    mat = \{((?:.|\n)*?)\}\n", PSRC)
assert _mat, "exit_cfg_sig's material literal was not found — this section would measure nothing"
SIGNED = set(re.findall(r'"([a-z_]+)":', _mat.group(1)))
_pay = re.search(r'"exits": \[\{"id": x\.get\("id"\)((?:.|\n)*?)\n\s*for x in \(node\.get\("exits"\)', PSRC)
assert _pay, "the sync payload's exit literal was not found — this section would measure nothing"
SENT = {"id"} | set(re.findall(r'"([a-z_]+)":', _pay.group(1)))
# `id` is identity, not config (it never changes for an exit, and the device is derived from it). `cfg_sig`
# is the stamp itself. `key_blob` is a ONE-SHOT escrow restore that the panel clears the moment the node
# reports a public key for it — it is a request, not a config, and signing it would make every restore
# rewrite the digest of a config that did not change.
EXEMPT = {"id", "cfg_sig", "key_blob"}
check("every field the node is SENT is either signed or deliberately exempt",
      not (SENT - SIGNED - EXEMPT), "sent but unsigned: " + str(sorted(SENT - SIGNED - EXEMPT)))
check("…and the digest signs nothing the node is never told", not (SIGNED - SENT),
      "signed but never sent: " + str(sorted(SIGNED - SENT)))
check("…and it is measuring real lists, not two empty sets", len(SIGNED) >= 5 and len(SENT) >= 6,
      (sorted(SIGNED), sorted(SENT)))

tmp = tempfile.mkdtemp(prefix="exitcfg-")
N.EXIT_DIR = tmp
N._dev_link_state = lambda d: "absent"
N._link_kind = lambda d: ""

def report(desired):
    # reconcile_exits publishes into `_EXITS`, it does not return the list.
    res = {"errors": [], "changed": 0}
    N._EXITS["list"] = []
    N.reconcile_exits(desired, res)
    return {r["id"]: r for r in (N._EXITS.get("list") or [])}

# (a) the PAUSED path — returns long before the ordinary report is built
out = report([{"id": "aa11aa11", "device": "wgx-aa11aa11", "provider": "warp", "down": True, "cfg_sig": "deadbeef01"}])
check("a paused exit echoes the revision", (out.get("aa11aa11") or {}).get("cfg_sig") == "deadbeef01", out)
# (b) the REGISTRATION-BACKOFF path — a different early return again
with open(os.path.join(tmp, "bb22bb22.json"), "w") as f:
    json.dump({"reg_fails": 3, "reg_next": time.time() + 900, "reg_error": "nope"}, f)
out = report([{"id": "bb22bb22", "device": "wgx-bb22bb22", "provider": "warp", "cfg_sig": "deadbeef02"}])
check("an exit backing off from a failed registration echoes it too",
      (out.get("bb22bb22") or {}).get("cfg_sig") == "deadbeef02", out)
check("…and it is stamped in ONE place, after every append", _STAMP in open(NODED, encoding="utf-8").read())
# (c) and (d) — the two paths that REFUSED an exit and then said nothing at all. No live record reads to the
# panel as "the node has not got to it yet", so `exitHealth` sat on `creating` — "Waiting for the node to set
# this up…" — for ever, about an exit the node had already looked at and rejected. The reason existed, but
# only in the node's error list, attached to the NODE rather than to the row the operator is staring at.
out = report([{"id": "cc33cc33", "device": "wgx has a space", "provider": "warp", "cfg_sig": "deadbeef03"}])
check("an exit refused for its device name is REPORTED, not silently skipped",
      "cc33cc33" in out, sorted(out))
check("…with the reason on the row", "device name" in (out.get("cc33cc33") or {}).get("error", ""), out)
check("…and stamped like every other report", (out.get("cc33cc33") or {}).get("cfg_sig") == "deadbeef03", out)
out = report([{"id": "dd44dd44", "device": "wgx-dd44dd44", "provider": "profile", "cfg_sig": "deadbeef04",
               "profile": {"private_key": "k", "address": "10.0.0.2/32", "peer_key": "p"}}])   # no endpoint
check("an exit whose profile is incomplete is REPORTED too", "dd44dd44" in out, sorted(out))
check("…naming the part that is missing, which is the whole diagnosis",
      "endpoint" in (out.get("dd44dd44") or {}).get("error", ""), out)
check("…and stamped", (out.get("dd44dd44") or {}).get("cfg_sig") == "deadbeef04", out)
# ⚠️ SAID AS A RULE, so a SEVENTH exit path cannot be added silently. Every `continue` in that loop must be
# preceded by a report; the one exception is an entry with no usable id, which has nothing to attach to.
_loop = NSRC[NSRC.index("for xid, d in sorted(want.items()):"):NSRC.index("    # …and stamp EVERY report")]
_ls = _loop.splitlines()
_silent = [_ls[max(0, i - 2)].strip()[:70] for i, l in enumerate(_ls)
           if l.strip() == "continue" and "out.append(" not in "\n".join(_ls[max(0, i - 8):i])]
check("every way out of the reconcile loop leaves a report behind", not _silent, _silent)

print("\n[4] the browser has somewhere to put it")
rj = open(os.path.join(ROOT, "js", "routing.js"), encoding="utf-8").read()
ss = open(os.path.join(ROOT, "js", "screen-settings.js"), encoding="utf-8").read()
ru = open(os.path.join(ROOT, "js", "lang", "ru.js"), encoding="utf-8").read()
check("the health model has a `configuring` state",
      'return { state: "configuring", tone: "busy", icon: "refresh"' in rj)
check("…it needs a stamp from BOTH sides, so an older node is not spun for ever",
      "if (ex.cfg_sig && l.cfg_sig && l.cfg_sig !== ex.cfg_sig" in rj)
check("…and it needs the node to still be REPORTING, or the spinner outlives the node",
      "&& !nodeStale((node || {}).id))" in rj)
check("…and it outranks every reading of the config it replaced",
      rj.index('state: "configuring"') < rj.index('if (l.error) return { state: "failed"'))
# ⚠️ THE SENTENCE HAS EXACTLY ONE RENDERER, and it is `exitHealth`. There used to be a second: `ExitLive` in
# screen-settings.js held a copy of the same verdict ordering, and `d3a29ad` removed the only place that
# mounted it without removing the function. It therefore rendered nothing — while still reading like the
# exits screen's detail line, which is how the `cfg_sig` guard came to be added to it, and gated, as if it
# were live. A check that merely found the string there passed on dead code. It is now deleted, and this
# asserts the deletion rather than the wiring: a SECOND implementation of the ordering is the hazard,
# whether or not anything mounts it today.
check("the exits grid reads its verdict from the one health model", "exitHealth(stored(ex.id), node)" in ss)
check("…and no second copy of that ordering exists to drift from it",
      "function ExitLive" not in ss and "${ExitLive}" not in ss,
      "ExitLive is back. It takes no `node`, so its `configuring` branch would spin for ever on a node "
      "that has gone dark — render exitHealth's `why` instead of re-deriving it.")
check("the sentence is translated", '"Applying your changes on the node…":' in ru)
# The false amber had a second reader: an older node still conflates the two meanings of 0, and the trace
# is the fact that settles it — traffic cannot have crossed a peer that never answered.
check("a handshake of 0 is cross-checked against the trace",
      "l.handshake === 0 && !(l.trace || {}).ip" in rj)

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
