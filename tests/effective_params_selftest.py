#!/usr/bin/env python3
"""Parity self-test for effective_client_params — the rule that decides what a client config is RENDERED with.

Three programs must answer "what DNS / MTU / AllowedIPs / keepalive does THIS deployment of THIS peer get?"
identically, because a peer sees all three: swg-panel-server owns the rule, `swg-sub` resolves it into the
subscription payload, and `js/crypto.js` rebuilds the panel's own QR from the encrypted blob. They cannot
share code — swg-sub is a separate, deliberately isolated process and crypto.js is browser ESM — so each
keeps a copy, the way swg-sub's node_public_host copies node_public_ip. This locks the copies together.

It is worth a file because the copies HAD drifted, invisibly: js/crypto.js took no target at all, so it
could not perform the per-target merge swg-sub does, and a peer with a per-target MTU rendered one config in
the panel's QR and a different one on its own subscription page.

The JS copy is executed for real (extracted from js/crypto.js and run under node), not re-implemented here —
a test that re-states the rule proves only that the test agrees with itself.

Hermetic: no network, no state dir, no panel. Run:  python3 tests/effective_params_selftest.py   (exit 0 = pass)
Needs `node` on PATH for the JS third of it; without it that third is reported SKIP, not PASS.
"""
import importlib.machinery, importlib.util, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
# default to the repo copies next to this file; the env vars let you point it at DEPLOYED binaries
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
SUB    = os.environ.get("SWG_SUB")          or os.path.join(ROOT, "swg-sub")
CRYPTO = os.environ.get("SWG_CRYPTO_JS")    or os.path.join(ROOT, "js", "crypto.js")

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + detail) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def load(path, name):
    """Import a single-file program as a module. Both guard main() behind __name__, so nothing starts."""
    loader = importlib.machinery.SourceFileLoader(name, os.path.abspath(path))
    spec = importlib.util.spec_from_loader(name, loader)
    m = importlib.util.module_from_spec(spec)
    try:
        loader.exec_module(m)
    except SystemExit:
        pass
    return m


def js_impl():
    """The REAL effectiveClientParams out of js/crypto.js, as a standalone ES module body.

    Brace-matched from the `export function` header rather than regexed as a whole, so a nested object
    literal can't end the capture early. If the function ever grows an import-dependent line this stops
    evaluating and the test says so — which is the correct failure, not a false pass."""
    src = open(CRYPTO, encoding="utf-8").read()
    head = "export function effectiveClientParams("
    i = src.index(head)
    j = src.index("{", i)
    depth, k = 0, j
    while k < len(src):
        if src[k] == "{": depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                break
        k += 1
    return src[i:k + 1].replace("export function", "function", 1)


def js_eval(cases):
    """Run every case through the extracted JS and return its answers, or None when node is unavailable."""
    if not shutil.which("node"):
        return None
    script = (js_impl() + "\nconst CASES = " + json.dumps(cases) + ";\n"
              + "console.log(JSON.stringify(CASES.map(c => effectiveClientParams(c[0], c[1], c[2]))));\n")
    out = subprocess.run([shutil.which("node"), "--input-type=module", "-e", script],
                         capture_output=True, text=True)
    if out.returncode != 0:
        print("  node failed: " + (out.stderr or "").strip()[:400])
        return []
    return json.loads(out.stdout)


# ── the table. Each case is (peer, target, iface_meta, expected) ────────────────────────────────────────
# `expected` is written out by hand: the point is to pin the RULE, not to record whatever the code does.
IFACE = {"dns": ["1.1.1.1"], "mtu": 1420}
IFACE_KA = {"dns": ["1.1.1.1"], "mtu": 1420, "keepalive": 40}   # an interface with its own keepalive
CASES = [
    ("bare peer takes the interface's defaults",
     {}, {}, IFACE,
     {"dns": ["1.1.1.1"], "mtu": 1420, "allowed": "0.0.0.0/0, ::/0", "keepalive": 25}),

    ("no interface defaults either -> the fixed floor",
     {}, {}, {},
     {"dns": [], "mtu": 1280, "allowed": "0.0.0.0/0, ::/0", "keepalive": 25}),

    ("peer-wide overrides beat the interface",
     {"overrides": {"dns": ["9.9.9.9"], "mtu": 1300, "allowed": "10.0.0.0/8", "keepalive": 0}}, {}, IFACE,
     {"dns": ["9.9.9.9"], "mtu": 1300, "allowed": "10.0.0.0/8", "keepalive": 0}),

    # THE ONE THIS FILE EXISTS FOR: crypto.js took no target, so it answered 1420 here while swg-sub said 1200.
    ("this deployment's own mtu beats the peer-wide one",
     {"overrides": {"mtu": 1300}}, {"overrides": {"mtu": 1200}}, IFACE,
     {"dns": ["1.1.1.1"], "mtu": 1200, "allowed": "0.0.0.0/0, ::/0", "keepalive": 25}),

    ("the merge is per FIELD, not all-or-nothing",
     {"overrides": {"dns": ["9.9.9.9"], "keepalive": 15}}, {"overrides": {"mtu": 1200}}, IFACE,
     {"dns": ["9.9.9.9"], "mtu": 1200, "allowed": "0.0.0.0/0, ::/0", "keepalive": 15}),

    ("a target override of every field wins outright",
     {"overrides": {"dns": ["9.9.9.9"], "mtu": 1300, "allowed": "10.0.0.0/8", "keepalive": 15}},
     {"overrides": {"dns": ["8.8.8.8"], "mtu": 1200, "allowed": "192.168.0.0/16", "keepalive": 30}}, IFACE,
     {"dns": ["8.8.8.8"], "mtu": 1200, "allowed": "192.168.0.0/16", "keepalive": 30}),

    # dns=[] is the operator saying "no DNS line", which is NOT the same as "not customised"
    ("an empty dns list is an explicit choice, not an absent one",
     {"overrides": {"dns": []}}, {}, IFACE,
     {"dns": [], "mtu": 1420, "allowed": "0.0.0.0/0, ::/0", "keepalive": 25}),

    ("a target's empty dns list overrides a peer-wide dns",
     {"overrides": {"dns": ["9.9.9.9"]}}, {"overrides": {"dns": []}}, IFACE,
     {"dns": [], "mtu": 1420, "allowed": "0.0.0.0/0, ::/0", "keepalive": 25}),

    # keepalive 0 means "disable it" — a truthiness test would silently turn it back on at 25
    ("keepalive 0 disables it rather than falling back to 25",
     {}, {"overrides": {"keepalive": 0}}, IFACE,
     {"dns": ["1.1.1.1"], "mtu": 1420, "allowed": "0.0.0.0/0, ::/0", "keepalive": 0}),

    ("a peer with no overrides key at all",
     {"pubkey": "x"}, {"node": "n1", "iface": "awg0", "ip": "10.8.0.2"}, IFACE,
     {"dns": ["1.1.1.1"], "mtu": 1420, "allowed": "0.0.0.0/0, ::/0", "keepalive": 25}),

    # the roster is JSON on disk and hand-edits happen; a junk type must not become a config line
    ("junk override types fall back instead of rendering",
     {"overrides": {"dns": "8.8.8.8", "keepalive": "30"}}, {}, IFACE,
     {"dns": ["1.1.1.1"], "mtu": 1420, "allowed": "0.0.0.0/0, ::/0", "keepalive": 25}),

    # ── the interface level of the chain (T-0b). keepalive had no interface level at all until then:
    #    the value was writable, never published, and every config rendered the fixed 25 instead.
    ("the interface's own keepalive reaches a peer that set none",
     {}, {}, IFACE_KA,
     {"dns": ["1.1.1.1"], "mtu": 1420, "allowed": "0.0.0.0/0, ::/0", "keepalive": 40}),

    ("a peer-wide keepalive still beats the interface's",
     {"overrides": {"keepalive": 10}}, {}, IFACE_KA,
     {"dns": ["1.1.1.1"], "mtu": 1420, "allowed": "0.0.0.0/0, ::/0", "keepalive": 10}),

    ("and this deployment's beats both",
     {"overrides": {"keepalive": 10}}, {"overrides": {"keepalive": 5}}, IFACE_KA,
     {"dns": ["1.1.1.1"], "mtu": 1420, "allowed": "0.0.0.0/0, ::/0", "keepalive": 5}),

    ("keepalive 0 on the interface disables it, rather than reading as 'unset'",
     {}, {}, {"dns": [], "mtu": 1420, "keepalive": 0},
     {"dns": [], "mtu": 1420, "allowed": "0.0.0.0/0, ::/0", "keepalive": 0}),

    ("a deployment can re-enable keepalive over an interface that disabled it",
     {}, {"overrides": {"keepalive": 25}}, {"dns": [], "mtu": 1420, "keepalive": 0},
     {"dns": [], "mtu": 1420, "allowed": "0.0.0.0/0, ::/0", "keepalive": 25}),

    # `allowed` is the one field with no interface level, and that is deliberate: routing is a property of
    # the client, not of the server it dials. An interface carrying one must NOT be honoured by accident.
    ("an interface cannot supply AllowedIPs",
     {}, {}, {"dns": [], "mtu": 1420, "allowed": "10.0.0.0/8"},
     {"dns": [], "mtu": 1420, "allowed": "0.0.0.0/0, ::/0", "keepalive": 25}),
]


def main():
    print("effective_client_params parity — swg-panel-server / swg-sub / js/crypto.js\n")
    srv = load(SERVER, "swgpanel")
    sub = load(SUB, "swgsub")
    impls = [("swg-panel-server", srv.effective_client_params), ("swg-sub", sub.effective_client_params)]

    print("[1] each implementation against the table")
    for name, fn in impls:
        for label, peer, target, meta, want in CASES:
            got = fn(peer, target, meta)
            check("%-16s %s" % (name, label), got == want, "got %r want %r" % (got, want))

    print("\n[2] js/crypto.js (executed, not re-implemented)")
    jsout = js_eval([[c[1], c[2], c[3]] for c in CASES])
    if jsout is None:
        print("  SKIP  node not on PATH — the JS third of the rule was NOT checked")
    else:
        for (label, _p, _t, _m, want), got in zip(CASES, jsout):
            check("%-16s %s" % ("js/crypto.js", label), got == want, "got %r want %r" % (got, want))
        check("js/crypto.js covered every case", len(jsout) == len(CASES),
              "%d of %d" % (len(jsout), len(CASES)))

    print("\n[3] the roster's stored form round-trips (clean_overrides is the inverse)")
    # What the panel STORES is only what differs from the interface default; putting the defaults back must
    # return what the operator typed. If these two ever disagree a peer silently renders unlike its twin.
    for meta in (IFACE, IFACE_KA):
        for raw in ({"dns": ["9.9.9.9"], "mtu": 1300, "allowed": "10.0.0.0/8", "keepalive": 15},
                    {"dns": []}, {"keepalive": 0}, {"mtu": 1200}):
            stored = srv.clean_overrides(raw)
            eff = srv.effective_client_params({}, {"overrides": stored}, meta)
            ok = all(eff[k] == raw[k] for k in raw)
            check("round-trip %r (iface ka=%r)" % (raw, meta.get("keepalive")), ok,
                  "stored %r -> %r" % (stored, eff))

    print("\n[4] apply_iface_meta agrees across the twins, for every field that reaches a config")
    # effective_client_params is only half the answer: `meta` comes from apply_iface_meta, which is ALSO
    # duplicated (panel + swg-sub). Publishing the interface keepalive in one and not the other put the two
    # surfaces back out of step even with one shared render rule, so the pair is pinned here too.
    NODE_CFG = {"endpoint_host": "vpn.example.org",
                "ifaces": {"awg0": {"dns": ["9.9.9.9"], "mtu": 1420, "keepalive": 40,
                                    "awg_params": {"Jc": "5"}, "listen_port": 51821},
                           "awg1": {},                                   # nothing overridden: pure fall-through
                           "awg2": {"keepalive": 0}}}                    # 0 = "no PersistentKeepalive line"
    SNAP = {"interfaces": {ifn: {"meta": {"public_key": "PUB" + ifn, "listen_port": 51820,
                                          "endpoint": "203.0.113.10:51820", "address": "10.20.0.1/24",
                                          "subnet": "10.20.0.0/24", "dns": ["1.1.1.1"], "mtu": 1380,
                                          "awg_params": {"Jc": "4", "Jmin": "40"}}, "peers": []}
                           for ifn in ("awg0", "awg1", "awg2")}}
    # only the fields that end up in a client config — the panel's describe also carries counters and rates
    WIRE = ("public_key", "endpoint", "subnet", "dns", "mtu", "keepalive", "awg_params")
    a = srv.apply_iface_meta(NODE_CFG, srv.node_describe(SNAP)["data"]["interfaces"])
    b = sub.apply_iface_meta(NODE_CFG, sub.node_describe(SNAP))
    for ifn in sorted(SNAP["interfaces"]):
        pa = {k: a[ifn].get(k) for k in WIRE}
        pb = {k: b[ifn].get(k) for k in WIRE}
        check("apply_iface_meta %s: panel == swg-sub" % ifn, pa == pb, "panel %r vs sub %r" % (pa, pb))
    check("the override MTU wins over the node's reported one", a["awg0"]["mtu"] == 1420, str(a["awg0"]["mtu"]))
    check("no override -> the node's REPORTED mtu, not a hardcoded 1280", a["awg1"]["mtu"] == 1380, str(a["awg1"]["mtu"]))
    check("an interface keepalive of 0 survives as 0", a["awg2"].get("keepalive") == 0, repr(a["awg2"].get("keepalive")))
    check("an interface with no keepalive publishes none", "keepalive" not in a["awg1"], repr(a["awg1"].get("keepalive")))

    print("\n[5] the copies are not accidentally the same object")
    # A refactor that made swg-sub import the panel would make [1] pass vacuously.
    check("three distinct implementations", srv.effective_client_params is not sub.effective_client_params)
    check("apply_iface_meta likewise", srv.apply_iface_meta is not sub.apply_iface_meta)

    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS)); sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
