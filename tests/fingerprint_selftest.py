#!/usr/bin/env python3
"""Self-test for the node fingerprint — the digest a rebuild / transfer is proved against.

The fingerprint's whole value is that an unchanged fleet produces an unchanged digest, so the operator can
trust a clean diff. That makes its failure mode quiet: a digest that wobbles on its own trains people to
ignore it, and a digest that folds two different states together says "clean" about a broken node. Both are
worse than not having it. So the properties are pinned here rather than assumed.

Covers T-1 (canonicalisation) today; T-2's sections and stability land in the same file.

Hermetic: no network, no state dir, no panel. Run:  python3 tests/fingerprint_selftest.py   (exit 0 = pass)
"""
import importlib.machinery, importlib.util, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + detail) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def raises(fn, frag=""):
    """True when fn() raises FingerprintError whose message mentions `frag` (the offending path)."""
    try:
        fn()
    except Exception as e:
        return type(e).__name__ == "FingerprintError" and (frag in str(e))
    return False


def load():
    loader = importlib.machinery.SourceFileLoader("swgpanel", os.path.abspath(SERVER))
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", loader))
    try:
        loader.exec_module(m)
    except SystemExit:
        pass
    return m


def main():
    print("node fingerprint — canonicalisation (T-1)\n")
    m = load()
    canon, fph, fps = m._fp_canon, m._fp_hash, m._fp_secret

    print("[1] the same state always produces the same bytes")
    # THE control: a dict built in a different order is the same state and must hash the same, or every
    # diff is noise. Nothing in the panel guarantees key order — nodes.json round-trips through json.load.
    a = {"name": "edge", "ifaces": {"awg0": {"mtu": 1420, "dns": ["1.1.1.1"], "keepalive": 25}}, "pos": 1}
    b = {"pos": 1, "ifaces": {"awg0": {"keepalive": 25, "dns": ["1.1.1.1"], "mtu": 1420}}, "name": "edge"}
    check("two key orders canonicalise byte-identically", canon(a) == canon(b),
          "%r != %r" % (canon(a), canon(b)))
    check("...and therefore hash identically", fph(a) == fph(b))
    check("the bytes are stable across calls", canon(a) == canon(a))
    check("a digest is 16 hex chars", len(fph(a)) == 16 and all(c in "0123456789abcdef" for c in fph(a)))

    print("\n[2] list order is SEMANTIC and must survive")
    # targets / dns / routing are ordered. Sorting them here would hide a reordering that changes which
    # deployment a client tries first, and which DNS server it asks.
    check("reordering a list changes the digest",
          fph({"dns": ["1.1.1.1", "9.9.9.9"]}) != fph({"dns": ["9.9.9.9", "1.1.1.1"]}))
    check("an unchanged list keeps its digest",
          fph({"dns": ["1.1.1.1", "9.9.9.9"]}) == fph({"dns": ["1.1.1.1", "9.9.9.9"]}))

    print("\n[3] a float raises, and the message names it")
    # The other control. Floats are what telemetry looks like on this panel — measured in a live snapshot:
    # peers[].rx_speed / tx_speed, health.cpu_pct, health.load[], health.uptime, inet.up / inet.down.
    check("a bare float raises", raises(lambda: canon(1.0)))
    check("a nested float raises and names its path",
          raises(lambda: canon({"interfaces": {"awg0": {"peers": [{"rx_speed": 12.5}]}}}),
                 "$.interfaces.awg0.peers[0].rx_speed"))
    check("the exception is a ValueError (a caller can catch it narrowly)",
          issubclass(m.FingerprintError, ValueError))
    check("an int is NOT a float and passes", canon(12) == b"12")
    check("a bool stays a bool, not the int it subclasses",
          canon(True) == b"true" and canon(1) == b"1" and canon(True) != canon(1))

    print("\n[4] everything else that must never reach a digest")
    check("a set raises", raises(lambda: canon({"x"}), "$"))
    check("bytes raise", raises(lambda: canon(b"x")))
    check("a non-str dict key raises", raises(lambda: canon({1: "a"}), "not str"))
    check("a cycle is bounded rather than hanging",
          raises(lambda: canon(_deep(60)), "nested deeper"))
    check("a legal depth still works", isinstance(canon(_deep(10)), bytes))

    print("\n[5] _FP_NUM: one number, however it was written")
    # mtu is int in ifaces[<if>] and str in the node's create request (`req["mtu"] = str(_mtu)`);
    # raw_port is str in a snapshot while its sibling wg_port is int. Same fact, two spellings.
    check("mtu '1420' == 1420", fph({"mtu": "1420"}) == fph({"mtu": 1420}))
    check("listen_port '51820' == 51820", fph({"listen_port": "51820"}) == fph({"listen_port": 51820}))
    check("raw_port '56003' == 56003", fph({"raw_port": "56003"}) == fph({"raw_port": 56003}))
    check("keepalive '0' == 0 (0 is a real setting, not absence)",
          fph({"keepalive": "0"}) == fph({"keepalive": 0}))
    check("a NON-numeric field is left alone ('80' != 80)", fph({"title": "80"}) != fph({"title": 80}))
    check("a non-integer _FP_NUM value survives verbatim, it does not vanish",
          fph({"mtu": "auto"}) == fph({"mtu": "auto"}) and fph({"mtu": "auto"}) != fph({"mtu": 0}))
    check("different numbers still differ", fph({"mtu": 1420}) != fph({"mtu": 1280}))

    print("\n[6] secrets are carried by identity, never by content")
    psk = "rcwZkhhiTgY6GmIUcTw8YLp4Swdbvc/jP8+da9RfBJY="
    h = fps("psk", psk)
    check("a secret hashes to 16 hex chars", len(h) == 16)
    check("the plaintext is not in the digest", psk not in h and psk[:8] not in h)
    check("the same secret hashes the same (Transfer compares across panels)", h == fps("psk", psk))
    check("a changed secret changes the hash", h != fps("psk", psk[:-2] + "AA="))
    check("kind domain-separates: same string, different field, different hash",
          fps("psk", "hunter2") != fps("turn_password", "hunter2"))
    check("absent and empty both read as '' (no secret, not an unreadable one)",
          fps("psk", None) == "" and fps("psk", "") == "")
    check("'' is distinguishable from a real secret", fps("psk", "") != fps("psk", "x"))

    print("\n[7] _ip_literal — a hostname survives a rebuild, an IP gets re-checked (§1.5)")
    for v, want in (("1.2.3.4", True), ("203.0.113.10", True), ("2001:db8::1", True),
                    ("[2001:db8::1]", True), ("vpn.example.org", False), ("localhost", False),
                    ("", False), ("  1.2.3.4  ", True), ("1.2.3.4.5", False), ("999.1.1.1", False),
                    ("10", False)):
        check("_ip_literal(%r) is %s" % (v, want), m._ip_literal(v) is want)
    # ipaddress.ip_address(10) returns 0.0.0.10 — a port reaching this must not read as an address
    check("_ip_literal(51820) is False (an int is not an address here)", m._ip_literal(51820) is False)
    check("_ip_literal(None) is False", m._ip_literal(None) is False)

    print("\n[8] _hostport_split — including the one a plain rsplit(':') corrupts")
    for v, want in (("1.2.3.4:51820", ("1.2.3.4", 51820)),
                    ("vpn.example.org:51820", ("vpn.example.org", 51820)),
                    ("1.2.3.4", ("1.2.3.4", None)),
                    ("vpn.example.org", ("vpn.example.org", None)),
                    ("[2001:db8::1]:51820", ("2001:db8::1", 51820)),
                    ("[2001:db8::1]", ("2001:db8::1", None)),
                    ("2001:db8::1", ("2001:db8::1", None)),      # rsplit would say ('2001:db8:', None)
                    ("::1", ("::1", None)),
                    ("host:notaport", ("host:notaport", None)),  # not a port -> not a split
                    ("", ("", None)),
                    (None, ("", None))):
        got = m._hostport_split(v)
        check("_hostport_split(%r) == %r" % (v, want), got == want, "got %r" % (got,))
    # the pairing that matters: whatever comes out of the split must classify correctly
    for ep in ("1.2.3.4:51820", "[2001:db8::1]:51820", "2001:db8::1"):
        check("host of %r is an IP literal" % ep, m._ip_literal(m._hostport_split(ep)[0]))
    check("host of a hostname endpoint is NOT an IP literal",
          not m._ip_literal(m._hostport_split("vpn.example.org:51820")[0]))

    print("\n[9] the tripwire is LOAD-DEPENDENT — T-2 must project, not rely on it")
    # node_describe sums the peers' speeds with `sum(p.get("rx_speed", 0) or 0 ...)`. A zero float is
    # FALSY, so `0.0 or 0` yields the int 0: on an idle fleet rx_speed is an int and canon accepts it, and
    # the moment traffic flows it becomes a float and canon raises. Testing a fingerprint on a quiet fleet
    # would therefore prove nothing and the first raise would land in production on a busy node.
    # The conclusion is not "loosen canon" — it is that a section must PROJECT these fields away, and this
    # case is here so that stays true when someone edits the projection.
    def speed_of(peers):
        d = m.node_describe({"interfaces": {"awg0": {"meta": {}, "peers": peers}}})["data"]["interfaces"]
        return d["awg0"]["rx_speed"]
    check("idle node: rx_speed is an int, so canon accepts it",
          isinstance(speed_of([{"rx_speed": 0.0}]), int) and canon({"rx_speed": speed_of([{"rx_speed": 0.0}])}))
    check("busy node: rx_speed is a float, and canon raises",
          isinstance(speed_of([{"rx_speed": 12.5}]), float)
          and raises(lambda: canon({"rx_speed": speed_of([{"rx_speed": 12.5}])})))
    # every describe key that is telemetry rather than configuration — T-2's projection has to drop these
    VOLATILE = ("rx_speed", "tx_speed", "rx_bytes", "tx_bytes", "handshake_age", "peer_endpoint",
                "used_ips", "peer_count")
    d = m.node_describe({"interfaces": {"awg0": {"meta": {}, "peers": [{"rx_speed": 1.5, "allowed_ips": "10.0.0.2/32"}]}}})
    present = [k for k in VOLATILE if k in d["data"]["interfaces"]["awg0"]]
    check("all %d known-volatile describe keys still exist (the projection list is current)" % len(VOLATILE),
          len(present) == len(VOLATILE), "missing %s" % [k for k in VOLATILE if k not in present])

    # ── T-2: the sections ────────────────────────────────────────────────────────────────────────
    print("\n[10] node_fingerprint: a moving fleet does not move the root")
    fp = lambda nodes=None, roster=None, snap=None, **kw: m.node_fingerprint(
        DEPS, nodes or NODES(), "n1", roster or ROSTER(), {"n1": snap or SNAP()}, **kw)
    base = fp()
    check("both sections build", base["sections"] == ["residue", "render"], str(base["sections"]))
    check("nothing is unpredictable on a reporting node", base["cannot_predict"] == [],
          str(base["cannot_predict"]))
    # THE control. Counters, speeds and handshake age all move on a live node every few seconds; a root
    # that follows them is a root nobody can diff. Floats are the shape a real node reports speeds in.
    busy = SNAP(rx_bytes=99 << 20, rx_speed=1024.75, tx_speed=512.5, handshake_age=27)
    check("counters/speeds/handshake moving leaves the root identical",
          fp(snap=busy)["root"] == base["root"],
          "%s -> %s" % (base["root"], fp(snap=busy)["root"]))
    check("...and it did not merely raise instead", isinstance(fp(snap=busy)["root"], str))
    check("capturing twice from the same state is identical", fp()["root"] == base["root"])
    # The checks above run in the same instant, so a field derived from the clock would pass them and then
    # drift in production. Move the clock rather than waiting for it: 100 days apart, same state.
    _real_time = m.time.time
    roots, ats = [], []
    try:
        # several offsets, none a round number: a single round jump can land back on the same value for
        # anything modular (the first attempt used +100 days against a `% 3` and sailed through).
        for off in (1234567, 98765431, 314159265):
            m.time.time = lambda o=off: _real_time() + o
            f = fp(); roots.append(f["root"]); ats.append(f["meta"]["at"])
    finally:
        m.time.time = _real_time
    check("the root does not depend on the clock (3 far-apart offsets, same state)",
          set(roots) == {base["root"]}, "%s vs base %s" % (sorted(set(roots)), base["root"]))
    check("...though `meta.at` does move, which is why it is outside the root",
          len(set(ats)) == 3)

    print("\n[11] a real change moves exactly one digest path")
    # §7.1: bump one MTU => exactly one diff line. More than one and the operator is reading noise;
    # none and the digest is not watching what it claims to.
    n2 = NODES(); n2["n1"]["ifaces"]["awg0"]["mtu"] = 1380
    d = _diff(base, fp(nodes=n2))
    check("an MTU change is seen at all", bool(d), "nothing changed")
    check("it moves the peer's render path, and only it",
          d == ["render", "render.u1.p1.n1|awg0", "root"], str(d))
    # a change the node record carries but no client sees must still be caught -- by residue, not render
    n3 = NODES(); n3["n1"]["ifaces"]["awg0"]["egress_ip"] = "203.0.113.99"
    d3 = _diff(base, fp(nodes=n3))
    check("an egress change lands in residue, not render",
          "residue.ifaces" in d3 and not any(x.startswith("render") for x in d3), str(d3))

    print("\n[12] residue: what nobody classified shows up BY NAME")
    n4 = NODES(); n4["n1"]["some_new_field_nobody_classified"] = {"a": 1}
    f4 = fp(nodes=n4)
    check("an unknown field moves the root", f4["root"] != base["root"])
    check("...and the digest names it",
          "residue.some_new_field_nobody_classified" in f4["digest"], str(sorted(f4["digest"])))
    check("...and it is listed as a residue path",
          "some_new_field_nobody_classified.a" in f4["meta"]["residue_paths"],
          str(f4["meta"]["residue_paths"]))
    check("an empty container is still a named path (a field appearing as {} is a fact)",
          "csqtt" in "".join(fp(nodes=_with(NODES(), "csqtt", {}))["meta"]["residue_paths"]))

    print("\n[13] EXCLUDE and CONSUMED do what their names say")
    n5 = NODES(); n5["n1"]["token_hash"] = "pbkdf2_sha256$totally$different"; n5["n1"]["token_sha"] = "ff" * 32
    check("rotating the token does NOT move the root (it is the lockout, §1.2)",
          fp(nodes=n5)["root"] == base["root"])
    n6 = NODES(); n6["n1"]["ifaces"]["awg0"]["_synced"] = {"listen_port": 51820}
    check("convergence bookkeeping does not move the root", fp(nodes=n6)["root"] == base["root"])
    check("both are reported as dropped, with which list dropped them",
          "token_hash" in base["meta"]["residue_dropped"]["excluded"]
          and any(x.endswith(".dns") for x in base["meta"]["residue_dropped"]["consumed"]),
          str(base["meta"]["residue_dropped"]))
    # a field must live in exactly one section, or one change reads as two
    rp = " ".join(base["meta"]["residue_paths"])
    for k in ("awg_params", "endpoint_host", "public_key"):
        check("%s is claimed by render, so residue does not repeat it" % k, k not in rp)

    print("\n[13b] a stored tree never carries a secret")
    # node_fingerprint(with_trees=True) returns the material the digests were taken over, and that is what
    # gets written to disk as a baseline. `links.*.psk` is a mesh pre-shared key in cleartext; a baseline
    # holding it would be a second copy of it in the same directory as nodes.json.
    nsec = NODES()
    nsec["n1"]["links"] = {"n2": {"iface": "swg_a", "psk": "SUPERSECRETPSK=", "listen_port": 9999}}
    nsec["n1"]["ifaces"]["awg0"]["key_blob"] = {"pub": "P", "ct": "CIPHERTEXT", "eph": "E", "mac": "M"}
    ft = m.node_fingerprint(DEPS, nsec, "n1", ROSTER(), {"n1": SNAP()}, with_trees=True)
    blob = json.dumps(ft["trees"]["residue"])
    check("the plaintext PSK is not in the stored tree", "SUPERSECRETPSK=" not in blob, blob[:120])
    check("the sealed key ciphertext is not either", "CIPHERTEXT" not in blob)
    check("what remains is a labelled identity",
          ft["trees"]["residue"]["links"]["n2"]["psk"].startswith("secret:"),
          str(ft["trees"]["residue"]["links"]["n2"]["psk"]))
    check("the surrounding record survives masking",
          ft["trees"]["residue"]["links"]["n2"]["listen_port"] == 9999)
    # a mask that collapsed everything to one value would hide a change; a mask that varied would invent one
    nsec2 = json.loads(json.dumps(nsec)); nsec2["n1"]["links"]["n2"]["psk"] = "A DIFFERENT PSK="
    f2 = m.node_fingerprint(DEPS, nsec2, "n1", ROSTER(), {"n1": SNAP()})
    check("a changed secret still moves the root", f2["root"] != ft["root"])
    f3 = m.node_fingerprint(DEPS, json.loads(json.dumps(nsec)), "n1", ROSTER(), {"n1": SNAP()})
    check("an unchanged secret does not", f3["root"] == ft["root"])

    print("\n[14] render is keyed by user, so a peer changing owner is a PATH change")
    r2 = ROSTER(); r2["peers"]["p1"]["user_id"] = "u2"
    f2 = fp(roster=r2)
    check("the old path is gone", "render.u1.p1.n1|awg0" not in f2["digest"])
    check("the new path exists", "render.u2.p1.n1|awg0" in f2["digest"])
    check("the deployment's own hash is unchanged — only where it hangs moved",
          f2["digest"]["render.u2.p1.n1|awg0"] == base["digest"]["render.u1.p1.n1|awg0"])
    r3 = ROSTER(); r3["peers"]["p1"]["user_id"] = None
    check("an unassigned peer gets a real bucket, not a missing one",
          "render.-.p1.n1|awg0" in fp(roster=r3)["digest"])

    print("\n[15] the VK fallback trap — the source is fingerprinted, not just the value")
    # §Context: on a transfer, a peer with no hash of its own and no personal link falls back to the
    # PANEL-WIDE vk_link, which is the operator's own and resolves differently on the far panel.
    rw = ROSTER(); rw["peers"]["p1"] = _wdtt_peer()
    nw = NODES(); nw["n1"]["wdtt"] = {"wd0": {"listen": "0.0.0.0:56000", "wg_port": 56001, "fork": "amurcanov"}}
    deps_fb = dict(DEPS); deps_fb["panel_settings"] = {"vk_link": "https://vk.me/call/PANELWIDE"}
    a1 = m.node_fingerprint(DEPS, nw, "n1", rw, {"n1": SNAP()}, with_trees=True)
    a2 = m.node_fingerprint(deps_fb, nw, "n1", rw, {"n1": SNAP()}, with_trees=True)
    check("a peer with no link of its own reads vk_source=none without a fallback",
          _render(a1).get("vk_source") == "none", str(_render(a1)))
    check("...and vk_source=panel_fallback once the panel has one",
          _render(a2).get("vk_source") == "panel_fallback", str(_render(a2)))
    check("which moves the root — the trap is visible, not silent", a1["root"] != a2["root"])
    rw2 = ROSTER(); rw2["peers"]["p1"] = _wdtt_peer(); rw2["users"]["u1"]["vk_link"] = "https://vk.me/call/USEROWN"
    a3 = m.node_fingerprint(deps_fb, nw, "n1", rw2, {"n1": SNAP()}, with_trees=True)
    check("a peer with its OWN user's link reads vk_source=user", _render(a3).get("vk_source") == "user")

    print("\n[16] the empty-render gate (§2.2: 'not a nicety')")
    # describe_view skips a node with no snapshot, so an early capture compares empty to empty and reads
    # clean having verified nothing. That must be impossible to miss.
    ns = m.node_fingerprint(DEPS, NODES(), "n1", ROSTER(), {})
    check("a node that never reported yields a cannot_predict entry", len(ns["cannot_predict"]) == 1,
          str(ns["cannot_predict"]))
    check("...naming `render` as the unverified section", "render" in ns["cannot_predict"][0])
    check("two such captures DO compare equal — which is why the gate exists",
          ns["root"] == m.node_fingerprint(DEPS, NODES(), "n1", ROSTER(), {})["root"])
    check("an unknown node raises rather than fingerprinting nothing",
          raises(lambda: m.node_fingerprint(DEPS, NODES(), "nope", ROSTER(), {"n1": SNAP()}), "unknown node"))

    # ── T-4: the delta table ─────────────────────────────────────────────────────────────────────
    print("\n[17] §1.5 in full — the transform, all four rows")
    # "the reset IS this call". Note what is NOT here: "clear every IP", which would destroy a deliberate
    # front-door address on every rebuild. That is why the rule needs the box's addresses on BOTH sides.
    for v, bi, ai, want, label in (
        ("vpn.example.org", ["1.2.3.4"], ["9.9.9.9"], "vpn.example.org", "a hostname is kept, always"),
        ("203.0.113.9", ["1.2.3.4"], ["9.9.9.9"], "203.0.113.9", "an IP the box NEVER reported is kept (anycast/LB)"),
        ("1.2.3.4", ["1.2.3.4"], ["1.2.3.4"], "1.2.3.4", "an IP still on the box is kept (re-image/floating)"),
        ("1.2.3.4", ["1.2.3.4"], ["9.9.9.9"], "", "an IP the box no longer has is RESET"),
    ):
        out, _acts = m.fp_transform({"endpoint_host": v}, "rebuild",
                                    {"before_ips": bi, "after_ips": ai})
        check(label, out["endpoint_host"] == want, "got %r want %r" % (out["endpoint_host"], want))
    src = {"endpoint_host": "1.2.3.4", "ifaces": {"awg0": {"endpoint_host": "1.2.3.4"}}}
    out, acts = m.fp_transform(src, "rebuild", {"before_ips": ["1.2.3.4"], "after_ips": ["9.9.9.9"]})
    check("the transform never mutates its input", src["endpoint_host"] == "1.2.3.4")
    check("it reaches a nested per-interface override too",
          out["ifaces"]["awg0"]["endpoint_host"] == "", str(out))
    check("and it reports what it did", len(acts) == 2, str(acts))
    outb, _ = m.fp_transform({"listen": "1.2.3.4:56000"}, "rebuild",
                             {"before_ips": ["1.2.3.4"], "after_ips": ["9.9.9.9"]})
    check("a bind keeps its port when the host is reset",
          m.fp_transform({"endpoint_host": "1.2.3.4:56000"}, "rebuild",
                         {"before_ips": ["1.2.3.4"], "after_ips": ["9.9.9.9"]})[0]["endpoint_host"]
          == "0.0.0.0:56000")

    print("\n[18] …and the same rule as the CHECK, on the AFTER value (both ways)")
    # "cleared only if it was ours" licenses clearing but lets UNCHANGED pass trivially. THE control.
    for b, a, bi, ai, want, label in (
        ("1.2.3.4", "", ["1.2.3.4"], ["9.9.9.9"], "ok", "reset to blank passes"),
        ("1.2.3.4", "1.2.3.4", ["1.2.3.4"], ["9.9.9.9"], "block", "UNCHANGED and now wrong is BLOCKED"),
        ("1.2.3.4", "9.9.9.9", ["1.2.3.4"], ["9.9.9.9"], "ok", "swapped to an address the box has"),
        ("1.2.3.4", "5.5.5.5", ["1.2.3.4"], ["9.9.9.9"], "block", "swapped to one it does not"),
        ("vpn.example.org", "vpn.example.org", ["1.2.3.4"], ["9.9.9.9"], "ok", "a hostname survives"),
        ("vpn.example.org", "other.example.org", ["1.2.3.4"], ["9.9.9.9"], "review", "a CHANGED hostname is surfaced"),
        ("203.0.113.9", "203.0.113.9", ["1.2.3.4"], ["9.9.9.9"], "review", "a never-reported IP is unprovable, not silent"),
    ):
        sev, _note = m._host_swap_verdict(b, a, {"before_ips": bi, "after_ips": ai})
        check("%-46s %-16r -> %-16r" % (label, b, a), sev == want, "got %s want %s" % (sev, want))

    print("\n[19] one pair per verb, and the default is BLOCK")
    def diff_for(bt, at, op="rebuild", ctx=None):
        B = {"trees": {"residue": bt, "render": {}}, "cannot_predict": []}
        A = {"trees": {"residue": at, "render": {}}, "cannot_predict": []}
        return m.fp_diff(B, A, op, ctx or {})
    d = diff_for({"links": {"n2": {"psk": "secret:a"}}}, {"links": {"n2": {"psk": "secret:b"}}})
    check("any      — a re-provisioned mesh link passes without a tick", len(d["ok"]) == 1 and not d["blocks"])
    d = diff_for({"platform_info": {"kernel": "6.1"}}, {"platform_info": {"kernel": "6.99"}})
    check("review   — a new kernel is allowed but SURFACED",
          len(d["review"]) == 1 and not d["blocks"] and not d["ok"], str(d))
    d = diff_for({"ifaces": {"awg0": {"public_key": "A"}}}, {"ifaces": {"awg0": {"public_key": "B"}}})
    check("(default) — an unclassified field that changed BLOCKS", len(d["blocks"]) == 1, str(d))
    check("...and says why", "no rule" in d["blocks"][0]["why"], str(d["blocks"][0]))
    d = diff_for({"ifaces": {"awg0": {"public_key": "A"}}}, {"ifaces": {"awg0": {"public_key": "A"}}})
    check("an unchanged unclassified field is silent", not (d["blocks"] or d["review"] or d["ok"]))
    # cleared / to: exercised through the table rather than special-cased
    m._FP_DELTA["_t4test"] = (("residue.gone", "cleared", "test"), ("residue.fixed", "to:X", "test"))
    try:
        d = diff_for({"gone": "v"}, {"gone": "v"}, op="_t4test")
        check("cleared  — still present afterwards BLOCKS", len(d["blocks"]) == 1, str(d))
        d = diff_for({"gone": "v"}, {}, op="_t4test")
        check("cleared  — actually gone is accepted", not d["blocks"], str(d))
        d = diff_for({"fixed": "A"}, {"fixed": "Y"}, op="_t4test")
        check("to:      — the wrong value BLOCKS", len(d["blocks"]) == 1, str(d))
        d = diff_for({"fixed": "A"}, {"fixed": "X"}, op="_t4test")
        check("to:      — the right value is accepted", not d["blocks"], str(d))
        out, _ = m.fp_transform({"gone": "v", "fixed": "A"}, "_t4test", {})
        check("...and the transform performs both", out == {"fixed": "X"}, str(out))
    finally:
        m._FP_DELTA.pop("_t4test", None)

    print("\n[19b] the unchanged-and-now-wrong case, END TO END through a real fingerprint")
    # The one that matters, and the one this code got wrong twice. A rebuild that restores
    # /etc/swg-agent/config.json verbatim leaves endpoint_host naming the OLD box: NOTHING CHANGED, so a
    # diff-driven check sees nothing and reads clean while every dashboard stays green. Built from a real
    # node record and snapshot rather than a hand-made tree, because the first version of this test used
    # the path the rule was keyed to instead of the path the value actually appears at, and passed while
    # the rule matched nothing on three live nodes.
    def cap(eh, ips):
        n = NODES(); n["n1"]["endpoint_host"] = eh
        sp = SNAP(); sp["node_ips"] = list(ips)
        # a real node builds meta.endpoint from its OWN address, so a fixture whose reported endpoint
        # contradicts its node_ips is not a rebuilt box, it is an impossible one — and host_swap rightly
        # blocked it, which is how this was noticed.
        sp["interfaces"]["awg0"]["meta"]["endpoint"] = "%s:51820" % ips[0]
        return m.node_fingerprint(DEPS, n, "n1", ROSTER(), {"n1": sp}, with_trees=True)
    EP = "render.u1.p1.n1|awg0.endpoint"
    before = cap("1.2.3.4", ["1.2.3.4"])
    check("the endpoint really is at the path the rule is keyed to",
          any(p == EP for p, _v in m._fp_leaf_values(before["trees"]["render"], "render")),
          str([p for p, _ in m._fp_leaf_values(before["trees"]["render"], "render")][:6]))
    moved = {"before_ips": ["1.2.3.4"], "after_ips": ["9.9.9.9"]}
    stale = m.fp_diff(before, cap("1.2.3.4", ["9.9.9.9"]), "rebuild", moved)
    check("a stale endpoint that did not move is BLOCKED, not passed in silence",
          len(stale["blocks"]) == 1, str(stale["blocks"]))
    check("...and the row says it did not change",
          stale["blocks"] and stale["blocks"][0]["changed"] is False)
    check("...and names the reason", stale["blocks"] and "does not have" in stale["blocks"][0]["why"])
    healed = m.fp_diff(before, cap("", ["9.9.9.9"]), "rebuild", moved)
    check("after the reset the endpoint derives from the new box and passes",
          not healed["blocks"], str(healed["blocks"]))
    stayed = {"before_ips": ["1.2.3.4"], "after_ips": ["1.2.3.4"]}
    check("a same-box rebuild leaves a still-valid address alone",
          not m.fp_diff(before, cap("1.2.3.4", ["1.2.3.4"]), "rebuild", stayed)["blocks"])
    hn = cap("vpn.example.org", ["1.2.3.4"])
    check("a hostname survives a move untouched",
          not m.fp_diff(hn, cap("vpn.example.org", ["9.9.9.9"]), "rebuild", moved)["blocks"])
    # the two columns of the row must agree: reset the record, then check the render
    rec, acts = m.fp_transform(NODES()["n1"] | {"endpoint_host": "1.2.3.4"}, "rebuild", moved)
    check("the transform resets the record the check complained about",
          rec["endpoint_host"] == "" and acts, str(acts))
    check("...and the reset value then passes the check",
          not m.fp_diff(before, cap(rec["endpoint_host"], ["9.9.9.9"]), "rebuild", moved)["blocks"])

    print("\n[19c] a rule that never ran is not a rule that passed")
    # Measured on the live fleet: a node with NO peers deployed on it has no rendered endpoint, so the
    # §1.5 address rule never fires and its endpoint_host could go stale with the diff reading clean.
    # That is §1.5's own failure one level up, so it lands where it belongs — cannot_predict.
    def cap2(eh, ips, roster):
        n = NODES(); n["n1"]["endpoint_host"] = eh
        sp = SNAP(); sp["node_ips"] = list(ips)
        sp["interfaces"]["awg0"]["meta"]["endpoint"] = "%s:51820" % ips[0]
        return m.node_fingerprint(DEPS, n, "n1", roster, {"n1": sp}, with_trees=True)
    empty = {"version": 1, "users": {"u1": {"id": "u1"}}, "peers": {}}
    b0, a0 = cap2("1.2.3.4", ["1.2.3.4"], empty), cap2("1.2.3.4", ["9.9.9.9"], empty)
    d0 = m.fp_diff(b0, a0, "rebuild", {"before_ips": ["1.2.3.4"], "after_ips": ["9.9.9.9"]})
    check("a node with no deployments cannot be address-checked, and says so",
          any("matched nothing" in c for c in d0["cannot_predict"]), str(d0["cannot_predict"]))
    check("...and it is NOT reported as a pass", not d0["ok"] and not d0["blocks"], str(d0))
    # …while the same pair WITH a deployment does run the rule and does block
    dR = m.fp_diff(cap2("1.2.3.4", ["1.2.3.4"], ROSTER()), cap2("1.2.3.4", ["9.9.9.9"], ROSTER()),
                   "rebuild", {"before_ips": ["1.2.3.4"], "after_ips": ["9.9.9.9"]})
    check("with a deployment present the rule fires and blocks", len(dR["blocks"]) == 1, str(dR["blocks"]))
    check("...and that run has no 'matched nothing' for the wg rule",
          not any("render.*.*.*.endpoint`" in c for c in dR["cannot_predict"]), str(dR["cannot_predict"]))

    print("\n[20] the three severities stay in three places")
    ns = m.node_fingerprint(DEPS, NODES(), "n1", ROSTER(), {}, with_trees=True)
    d = m.fp_diff(ns, ns, "rebuild", {})
    check("cannot_predict rides through the diff, it is not folded away",
          d["cannot_predict"] and "render" in d["cannot_predict"][0], str(d["cannot_predict"]))
    check("an identical pair produces no rows at all",
          not (d["blocks"] or d["review"] or d["ok"]))
    # the longest matching pattern wins, so a precise rule is not shadowed by a wildcard above it
    m._FP_DELTA["_t4prec"] = (("residue.ifaces.*", "any", "wide"),
                              ("residue.ifaces.*.public_key", "review", "narrow"))
    try:
        d = diff_for({"ifaces": {"a": {"public_key": "A", "other": 1}}},
                     {"ifaces": {"a": {"public_key": "B", "other": 2}}}, op="_t4prec")
        check("the more specific rule wins over the wildcard",
              len(d["review"]) == 1 and len(d["ok"]) == 1, str(d))
    finally:
        m._FP_DELTA.pop("_t4prec", None)

    print("\n[21] the prospective run derives predictability, it does not list it")
    # The question asked of every value is "does the panel HOLD this?", answered against the precedence
    # apply_iface_meta and /api/iface/recreate already implement. Measured on the live fleet, which is why
    # it is not a table: msk-main's awg0 carries all sixteen AWG params in `_lastcfg` and IS predictable,
    # while nixos's awg0 has no record entry at all and none of it is.
    def prosp(nodes, snap=None, mode="unknown", assume=None, roster=None):
        sp = {"n1": snap if snap is not None else SNAP()}
        d = dict(DEPS, node_snaps=sp)
        return m.fp_prospective(d, nodes, "n1", "rebuild", mode=mode, assume=assume,
                                roster=roster if roster is not None else ROSTER(), snaps=sp)
    # ⚠️ The fixture has to be shaped like the live fleet or it proves the wrong thing: msk-main's awg0
    # carries all sixteen params in `_lastcfg` and NO awg_params override at all. A fixture whose override
    # happens to cover every reported key would report "predictable" from the override while the _lastcfg
    # path — the one being claimed — never ran. (It did exactly that until a perturbation said so.)
    AWG16 = {"Jc": 4, "Jmin": 40, "Jmax": 70, "S1": 72, "S2": 108, "S3": 32, "S4": 100,
             "H1": "116459550-116459565", "H2": "1066232342-1066232357",
             "H3": "2262031190-2262031205", "H4": "3149500973-3149500988",
             "I1": "<b 0xc000000001><r 64><t>", "I2": "<r 24><t>", "I3": "<r 32>",
             "I4": "<b 0xc000000001><r 32><t>", "I5": "<t><r 48>"}
    def SNAP16():
        s = SNAP(); s["interfaces"]["awg0"]["meta"]["awg_params"] = dict(AWG16); return s
    held = NODES()
    held["n1"]["ifaces"]["awg0"].pop("awg_params")          # no override — exactly like the live fleet
    held["n1"]["ifaces"]["awg0"]["_lastcfg"] = {"subnet": "10.20.0.0/24", "listen_port": 51820,
                                                "address": "10.20.0.1/24",
                                                "awg_params": dict(AWG16), "mtu": 1420}
    r = _render(prosp(held, SNAP16()))
    check("AWG the panel holds in _lastcfg is PREDICTABLE, not unknown",
          not m._fp_is_unknown(r["awg"]), str(r["awg"]))
    check("...and so are the subnet and the endpoint port",
          not m._fp_is_unknown(r["subnet"]) and "<fp-unknown>" not in r["endpoint"], str(r))
    check("...and all sixteen of them, not just the ones an override happens to cover",
          len(r["awg"]) == 16 and not any(m._fp_is_unknown(v) for v in r["awg"].values()), str(r["awg"]))
    bare = NODES()
    bare["n1"]["ifaces"]["awg0"].pop("awg_params")          # no override AND no _lastcfg
    r2 = _render(prosp(bare, SNAP16()))
    check("AWG the panel holds NOWHERE is unknown", m._fp_is_unknown(r2["awg"]), str(r2["awg"]))
    check("...every one of the sixteen, and the reason counts them",
          all(m._fp_is_unknown(v) for v in r2["awg"].values()) and
          any("16 of 16 obfuscation params" in c for c in prosp(bare, SNAP16())["cannot_predict"]),
          str(prosp(bare, SNAP16())["cannot_predict"]))
    # …and the two sources are independent: an override alone is enough, _lastcfg alone is enough
    ovonly = NODES(); ovonly["n1"]["ifaces"]["awg0"]["awg_params"] = dict(AWG16)
    check("an override alone also makes it predictable",
          not m._fp_is_unknown(_render(prosp(ovonly, SNAP16()))["awg"]))
    check("the server key is ALWAYS unknown — it returns from the box or the vault, neither visible here",
          m._fp_is_unknown(r["server_pubkey"]))
    check("a hostname endpoint stays predictable across a rebuild (§7.8's payoff)",
          "vpn.example.org" in r["endpoint"] and not m._fp_is_unknown(r["endpoint"]), str(r["endpoint"]))

    print("\n[21b] DNS: the row T-7 has to close")
    # `_lastcfg` carries subnet / listen_port / address / awg_params / mtu and NOT dns, so with no panel
    # override the client's resolver comes from the NEW box's config.json. T-7's adapter must capture the
    # observed DNS into ifaces[<if>].dns; until it does, this is the honest answer.
    check("with a panel override, DNS is predictable", not m._fp_is_unknown(r["dns"]), str(r["dns"]))
    check("...and no fall-through is reported for it — a spurious note is a false alarm to chase",
          not any("DNS falls through" in c for c in prosp(held, SNAP16())["cannot_predict"]),
          str(prosp(held, SNAP16())["cannot_predict"]))
    nod = NODES(); nod["n1"]["ifaces"]["awg0"].pop("dns")
    check("with NO override, DNS is unknown — it falls through to the new box",
          m._fp_is_unknown(_render(prosp(nod))["dns"]))
    check("...and the reason names the fall-through, not just the field",
          any("falls through to the new box" in c for c in prosp(nod)["cannot_predict"]),
          str(prosp(nod)["cannot_predict"]))

    print("\n[22] `assume` is what makes §1.5 checkable at all")
    # In `unknown` mode the box's future addresses are unknown BY DEFINITION, so an address rule cannot be
    # evaluated — it must report as unpredictable, never as a pass. Supplying the address is what turns it
    # back into a real check, and the label stays conditional because the assumption is the operator's.
    stale_ip = NODES(); stale_ip["n1"]["endpoint_host"] = "1.2.3.4"
    sp = SNAP(); sp["node_ips"] = ["1.2.3.4"]
    sp["interfaces"]["awg0"]["meta"]["endpoint"] = "1.2.3.4:51820"
    base = m.node_fingerprint(dict(DEPS, node_snaps={"n1": sp}), stale_ip, "n1", ROSTER(),
                              {"n1": sp}, with_trees=True)
    unk = prosp(stale_ip, sp)
    d_unk = m.fp_diff(base, unk, "rebuild", unk["meta"]["prospective"]["ctx"])
    def _unpred(d, frag):
        """A path reported as UNPREDICTABLE — not merely a line that mentions it. The 'matched nothing'
        rows live in the same list and say something quite different."""
        return any(frag in c and "not knowable" in c for c in d["cannot_predict"])
    check("unknown mode cannot judge an IP endpoint, and does not pretend to",
          not d_unk["blocks"] and _unpred(d_unk, "render.*.*.*.endpoint`"),
          str(d_unk["blocks"]) + str(d_unk["cannot_predict"]))
    # the endpoint reaches render COMPOSED ("<fp-unknown>:51820" — apply_iface_meta built it), which is
    # why the sentinel is detected by containment. Equality here reads the value as an ordinary hostname.
    check("a sentinel COMPOSED into a larger value is still detected",
          m._fp_is_unknown("<fp-unknown>:51820") and not m._fp_is_unknown("vpn.example.org:51820"))
    check("...and that is the form the endpoint actually arrives in",
          "<fp-unknown>:51820" == _render(unk)["endpoint"], _render(unk)["endpoint"])
    asm = prosp(stale_ip, sp, mode="assume", assume="9.9.9.9")
    d_asm = m.fp_diff(base, asm, "rebuild", asm["meta"]["prospective"]["ctx"])
    check("assume mode resets the stale address and the check then PASSES",
          not d_asm["blocks"], str(d_asm["blocks"]))
    check("...and the assumption is labelled, not silently folded in",
          any("ASSUMED" in c for c in asm["cannot_predict"]), str(asm["cannot_predict"]))
    check("assume without an address is refused", raises(lambda: prosp(stale_ip, sp, mode="assume"), "assume"))
    check("an unknown mode name is refused", raises(lambda: prosp(stale_ip, sp, mode="wishful"), "wishful"))
    # PERTURBATION: break the reset and assume mode must go RED. This is the control that proves assume
    # mode is doing work rather than agreeing with itself.
    _real = m._host_swap_transform
    try:
        m._host_swap_transform = lambda value, ctx: value      # "reset" that resets nothing
        bad = prosp(stale_ip, sp, mode="assume", assume="9.9.9.9")
        d_bad = m.fp_diff(base, bad, "rebuild", bad["meta"]["prospective"]["ctx"])
        check("a reset that resets nothing BLOCKS under assume", len(d_bad["blocks"]) >= 1, str(d_bad))
    finally:
        m._host_swap_transform = _real

    print("\n[22b] a deliberate front-door address: kept, and therefore actually checked")
    # §1.5 keeps an IP the box never reported (anycast / LB / DNAT front). It survives the transform, so it
    # reaches the verdict as a REAL IP literal — the one shape where "the box has not reported yet" is
    # distinguishable from "the box reports no addresses". Folding those two together (after_ips = [] in a
    # prospective run) turns an unanswerable question into a confident review row.
    front = NODES(); front["n1"]["endpoint_host"] = "198.51.100.9"       # never in node_ips
    spf = SNAP(); spf["node_ips"] = ["1.2.3.4"]
    spf["interfaces"]["awg0"]["meta"]["endpoint"] = "1.2.3.4:51820"
    bf = m.node_fingerprint(dict(DEPS, node_snaps={"n1": spf}), front, "n1", ROSTER(),
                            {"n1": spf}, with_trees=True)
    af = prosp(front, spf)
    check("the front-door IP is KEPT by the reset (§1.5), not cleared",
          _render(af)["endpoint"] == "198.51.100.9:51820", _render(af)["endpoint"])
    df = m.fp_diff(bf, af, "rebuild", af["meta"]["prospective"]["ctx"])
    check("...and with the box's future addresses unknown, it is UNPREDICTABLE, not a verdict",
          not df["blocks"] and not df["review"] and
          any("not known yet" in c for c in df["cannot_predict"]), str(df))
    aa = prosp(front, spf, mode="assume", assume="198.51.100.9")
    da = m.fp_diff(bf, aa, "rebuild", aa["meta"]["prospective"]["ctx"])
    check("...while assuming the box will carry it makes it a real pass",
          not da["blocks"] and not any("not known yet" in c for c in da["cannot_predict"]), str(da))
    ab = prosp(front, spf, mode="assume", assume="203.0.113.77")
    db = m.fp_diff(bf, ab, "rebuild", ab["meta"]["prospective"]["ctx"])
    # NOT a block, deliberately: an address the box never reported is unprovable in BOTH directions — a
    # front door that still points somewhere, or one that went stale years ago. T-4 made that `review`
    # rather than `block` on purpose, and assuming a different address does not make it knowable. What it
    # must never be is silence.
    check("...and assuming a DIFFERENT address leaves it surfaced for a human, not passed",
          not db["blocks"] and len(db["review"]) == 1 and
          "never reported" in db["review"][0]["why"], str(db))

    print("\n[23] a projected value is never a block, never an ok, and collapses with a count")
    two = ROSTER()
    two["peers"]["p2"] = {"id": "p2", "user_id": "u2", "pubkey": "PEERPUB2", "psk": "PSK2",
                          "targets": [{"node": "n1", "iface": "awg0", "ip": "10.20.0.3", "type": "awg"}]}
    sp2 = SNAP()
    sp2["interfaces"]["awg0"]["peers"].append({"public_key": "PEERPUB2", "online": True,
                                               "handshake_age": 5, "allowed_ips": "10.20.0.3/32",
                                               "rx_bytes": 1, "tx_bytes": 1, "rx_speed": 0, "tx_speed": 0})
    b2 = m.node_fingerprint(dict(DEPS, node_snaps={"n1": sp2}), NODES(), "n1", two, {"n1": sp2},
                            with_trees=True)
    a2 = prosp(NODES(), sp2, roster=two)
    d2 = m.fp_diff(b2, a2, "rebuild", a2["meta"]["prospective"]["ctx"])
    check("the sentinel produces no blocks and no oks", not d2["blocks"] and not d2["ok"], str(d2))
    key = [c for c in d2["cannot_predict"] if "server_pubkey" in c]
    check("two deployments collapse to ONE line carrying the count",
          len(key) == 1 and "(2 paths)" in key[0], str(key))
    check("the collapsed path names the shape, not an instance",
          key and key[0].startswith("`render.*.*.*.server_pubkey`"), str(key))
    check("collapsing keeps residue container keys distinguishable",
          m._fp_collapse_path("residue.ifaces.awg0.public_key") == "residue.ifaces.*.public_key" and
          m._fp_collapse_path("render.u1.p1.n1|awg0.turn.0.wrap_key") == "render.*.*.*.turn.*.wrap_key")

    print("\n[24] the `stale` mode — §2.2's fixture, and the only thing it proves")
    # "A third mode that reuses the old snapshot produces a reassuring FALSE empty diff; it exists only as
    # the test fixture proving `unknown` works." So it is asserted to be empty AND to say that it is false.
    st = prosp(NODES(), sp2, mode="stale", roster=two)
    d_st = m.fp_diff(b2, st, "rebuild", st["meta"]["prospective"]["ctx"])
    check("stale mode reports a completely clean diff",
          not (d_st["blocks"] or d_st["review"] or d_st["ok"]), str(d_st))
    check("...and the ONLY thing separating it from a real pass is that it says so",
          any("FALSE empty" in c for c in d_st["cannot_predict"]), str(d_st["cannot_predict"]))
    check("...while `unknown` over the same input is not clean at all",
          len(d2["cannot_predict"]) > len(d_st["cannot_predict"]),
          "%d vs %d" % (len(d2["cannot_predict"]), len(d_st["cannot_predict"])))

    print("\n[25] the convergence predicate — never a diff while the node is still coming back")
    def conv(nodes, snap, **kw):
        d = dict(DEPS, node_snaps=({"n1": snap} if snap is not None else {}))
        return d, m.fp_converged(d, nodes, "n1", ROSTER(), **kw)
    _d, c0 = conv(NODES(), None)
    check("a node that has never reported is NOT ready", not c0["ready"])
    check("...and the reason is the empty-to-empty trap, by name",
          any("empty to empty" in w for w in c0["waiting"]), str(c0["waiting"]))
    pend = NODES(); pend["n1"]["create"] = {"awg1": {"cmd": ["awg"]}}
    _d, c1 = conv(pend, SNAP())
    check("a queued instruction the node has not consumed blocks the capture", not c1["ready"])
    check("...and it is named", any(w.startswith("create:") for w in c1["waiting"]), str(c1["waiting"]))
    check("the pending list is DERIVED from _FP_EXCLUDE, not retyped beside it",
          "create" in m._FP_PENDING_KEYS and "turn" in m._FP_PENDING_KEYS
          and "proc_status" not in m._FP_PENDING_KEYS and
          all("." not in k for k in m._FP_PENDING_KEYS), str(m._FP_PENDING_KEYS))
    gone = NODES()
    gone["n1"]["ifaces"]["awg1"] = {"_lastcfg": {"subnet": "10.30.0.0/24"}, "public_key": "K2"}
    _d, c2 = conv(gone, SNAP())
    check("an interface that has not come back blocks the capture",
          not c2["ready"] and any("not back" in w for w in c2["waiting"]), str(c2["waiting"]))
    _d, c2a = conv(gone, SNAP(), ack_missing=True)
    check("...unless the operator has acknowledged it",
          not any("not back" in w for w in c2a["waiting"]), str(c2a["waiting"]))
    check("N of M back is counted", (c2["back"], c2["of"]) == (1, 2), str((c2["back"], c2["of"])))

    print("\n[25b] stability cannot be manufactured by polling")
    d, s1 = conv(NODES(), SNAP())
    check("one observation is not two — the first capture is never ready",
          not s1["ready"] and s1["stable"] == 1 and
          any("two that agree" in w for w in s1["waiting"]), str(s1["waiting"]))
    same = m.fp_converged(d, NODES(), "n1", ROSTER())          # SAME snapshot, polled again
    check("re-polling the same snapshot does not advance stability", same["stable"] == 1, str(same))
    sp_next = SNAP(rx_bytes=99 << 20); sp_next["generated_at"] = 1787000005   # a NEW snapshot, same config
    d["node_snaps"]["n1"] = sp_next
    s2 = m.fp_converged(d, NODES(), "n1", ROSTER())
    check("a second snapshot agreeing with the first IS ready", s2["ready"] and s2["stable"] == 2, str(s2))
    moved_cfg = NODES(); moved_cfg["n1"]["ifaces"]["awg0"]["mtu"] = 1380
    sp3 = SNAP(); sp3["generated_at"] = 1787000010
    d["node_snaps"]["n1"] = sp3
    s3 = m.fp_converged(d, moved_cfg, "n1", ROSTER())
    check("a fingerprint that moved resets the count to one", not s3["ready"] and s3["stable"] == 1, str(s3))

    print("\n[26] baselines — a rebuild is a ONE-SHOT DESTRUCTIVE measurement")
    # `render` is computed from the record, the roster and the snapshot, and a rebuild overwrites all three
    # the moment the node reports. The "before" exists only if it was captured first, which is this whole
    # section. (The previous session's comparison copies lived in a scratch directory and are gone; that is
    # the failure being designed out, not a hypothetical.)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        st = os.path.join(td, "state"); os.makedirs(st)
        npath = os.path.join(st, "nodes.json")
        nodes = NODES()
        m.nodes_save(npath, nodes)
        d = dict(DEPS, nodes_path=npath, roster_path=os.path.join(st, "users.json"),
                 node_snaps={"n1": SNAP()})
        e1 = m.fp_baseline_save(d, nodes, "n1", ROSTER(), label="before the rebuild")
        check("a capture writes a tree and records a digest",
              os.path.exists(os.path.join(m._fp_dir(d, "n1"), e1["file"])) and e1["root"], str(e1))

        # THE SELF-REFERENCE TRAP: the baseline is stored IN the record, so if it were part of `residue`
        # every capture would move the root and each baseline would invalidate the next one.
        r_before = m.node_fingerprint(d, nodes, "n1", ROSTER(), d["node_snaps"])["root"]
        m.fp_baseline_save(d, nodes, "n1", ROSTER(), label="second")
        r_after = m.node_fingerprint(d, nodes, "n1", ROSTER(), d["node_snaps"])["root"]
        check("storing a baseline does NOT move the root it just recorded",
              r_before == r_after == e1["root"], "%s vs %s vs %s" % (r_before, r_after, e1["root"]))
        check("...because `fp` is classified, by name and with a reason",
              any(p == "fp" and w for p, w in m._FP_EXCLUDE))

        # A same-second pair: two entries, and they must NOT share a file. Measured on the first live run
        # as nine record entries over eight files — one entry silently naming the other's tree.
        a = m.fp_baseline_save(d, nodes, "n1", ROSTER())
        b = m.fp_baseline_save(d, nodes, "n1", ROSTER())
        check("two captures in the same second get distinct identities and distinct files",
              a["id"] != b["id"] and a["file"] != b["file"], "%s / %s" % (a, b))
        check("...and the record entry count matches the files on disk",
              len(m.fp_baseline_list(nodes, "n1")) == len(os.listdir(m._fp_dir(d, "n1"))),
              "%d entries vs %d files" % (len(m.fp_baseline_list(nodes, "n1")),
                                          len(os.listdir(m._fp_dir(d, "n1")))))
        check("a baseline loads back in the shape fp_diff consumes",
              (m.fp_baseline_load(d, nodes, "n1", a["id"]) or {}).get("trees", {}).get("render") is not None)
        check("...addressed by id, and a wrong id is None rather than the newest one",
              m.fp_baseline_load(d, nodes, "n1", "1-deadbe") is None)

        # ROUTINE MUST NOT DESTROY DELIBERATE. A flat "keep the last N" lets unlabelled captures evict the
        # one taken on purpose before a rebuild — measured, ten of them did exactly that.
        for i in range(m.FP_BASELINE_KEEP + 4):
            m.fp_baseline_save(d, nodes, "n1", ROSTER())
        lst = m.fp_baseline_list(nodes, "n1")
        labelled = [x for x in lst if x.get("label")]
        check("the deliberate capture survives a flood of routine ones",
              any(x["label"] == "before the rebuild" for x in labelled), str([x.get("label") for x in lst]))
        check("...while the routine ones stay capped", len([x for x in lst if not x.get("label")])
              <= m.FP_BASELINE_KEEP, str(len(lst)))
        check("...and every remaining entry still has its file",
              all(os.path.exists(os.path.join(m._fp_dir(d, "n1"), x["file"])) for x in lst))

        # A capture is NOT gated on convergence: it is taken before the thing that disturbs the node, and
        # a damaged box would never satisfy the gate at all.
        d2 = dict(d, node_snaps={})
        check("a node with no snapshot can still be baselined — that is when it matters most",
              m.fp_baseline_save(d2, nodes, "n1", ROSTER(), label="damaged")["root"] != "")
        latest = m.fp_baseline_load(d2, nodes, "n1") or {}
        check("...and the capture carries the warning that its render section is empty",
              latest.get("cannot_predict"), str(latest.get("label")))
        # "the newest" must survive the pruner regrouping the list — it is a stored sequence, not a position
        check("...and `latest` really is the newest capture, not merely the last in the list",
              latest.get("label") == "damaged", str(latest.get("label")))
        check("every entry carries an explicit sequence",
              all(int(x.get("seq") or 0) > 0 for x in m.fp_baseline_list(nodes, "n1")))

    print("\n[26b] a missing baseline is not a clean bill")
    with tempfile.TemporaryDirectory() as td:
        st = os.path.join(td, "state"); os.makedirs(st)
        npath = os.path.join(st, "nodes.json")
        nodes = NODES(); m.nodes_save(npath, nodes)
        d = dict(DEPS, nodes_path=npath, node_snaps={"n1": SNAP()})
        check("no baseline at all loads as None", m.fp_baseline_load(d, nodes, "n1") is None)
        e = m.fp_baseline_save(d, nodes, "n1", ROSTER(), label="x")
        os.unlink(os.path.join(m._fp_dir(d, "n1"), e["file"]))       # the tree goes missing under the record
        check("a record entry whose tree is gone loads as None, not as an empty tree",
              m.fp_baseline_load(d, nodes, "n1") is None)
        # …and the reason a missing tree must not silently become an empty one is EMPTY-VS-EMPTY, not
        # empty-vs-full. A half-empty pair is loud (every leaf reads as a change); it is two empty renders
        # that compare equal and report a clean bill having verified nothing — §2.2's stated trap, and the
        # only defence against it is the cannot_predict node_fingerprint raises for a node with no snapshot.
        cur = m.node_fingerprint(d, nodes, "n1", ROSTER(), d["node_snaps"], with_trees=True)
        empty = {"trees": {"residue": {}, "render": {}}, "cannot_predict": []}
        loud = m.fp_diff(empty, cur, "rebuild", {"before_ips": [], "after_ips": []})
        check("an empty tree against a full one is LOUD, not clean", bool(loud["blocks"]))
        blind = m.node_fingerprint(dict(d, node_snaps={}), nodes, "n1", ROSTER(), {}, with_trees=True)
        pair = m.fp_diff(blind, blind, "rebuild", {"before_ips": [], "after_ips": []})
        check("...while two EMPTY renders compare perfectly clean — the trap itself",
              not (pair["blocks"] or pair["review"]), str(pair))
        check("...and the only thing that stops that reading as a pass is the cannot_predict",
              any("never reported" in c for c in pair["cannot_predict"]), str(pair["cannot_predict"]))

    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS)); sys.exit(1)
    print("ALL PASS")


DEPS = {"roster_path": "/nonexistent", "panel_settings": {}}

def NODES():
    """One node, one awg interface, shaped like the live fleet's records."""
    return {"n1": {
        "id": "n1", "name": "edge-01", "kind": "baremetal", "created": 1787000000,
        "endpoint_host": "vpn.example.org", "stats_file": "stats-n1.json",
        "token_hash": "pbkdf2_sha256$1$abc", "token_sha": "aa" * 32,
        "color": {"dark": "#123456", "light": "#abcdef"},
        "ifaces": {"awg0": {"dns": ["1.1.1.1"], "mtu": 1420, "keepalive": 25,
                            "listen_port": 51820, "public_key": "SRVPUB",
                            "awg_params": {"Jc": "4", "Jmin": "40"},
                            "egress_ip": "", "egress_mode": "direct"}}}}

def ROSTER():
    return {"version": 1,
            "users": {"u1": {"id": "u1", "name": "Anna"}, "u2": {"id": "u2", "name": "Boris"}},
            # the peer carries an EXPIRY, and the clock offsets below straddle it on purpose: a section
            # that stored a computed "is expired" instead of the stored date would be stable right up to
            # that date and then flip, which a fixture without one can never catch.
            "peers": {"p1": {"id": "p1", "user_id": "u1", "pubkey": "PEERPUB", "psk": "PEERPSK",
                             "expiry": 1800000000,
                             "targets": [{"node": "n1", "iface": "awg0", "ip": "10.20.0.2", "type": "awg"}]}}}

def _wdtt_peer():
    return {"id": "p1", "user_id": "u1", "pubkey": "", "wdtt_password": "pw",
            "targets": [{"node": "n1", "iface": "wd0", "type": "wdtt"}]}

def SNAP(rx_bytes=10 << 20, rx_speed=0.0, tx_speed=0.0, handshake_age=5):
    return {"generated_at": 1787000000, "node_ips": ["203.0.113.10"],
            "interfaces": {"awg0": {"meta": {"public_key": "SRVPUB", "listen_port": 51820,
                                             "endpoint": "203.0.113.10:51820", "address": "10.20.0.1/24",
                                             "subnet": "10.20.0.0/24", "dns": ["1.1.1.1"], "mtu": 1420,
                                             "awg_params": {"Jc": "4", "Jmin": "40"}},
                                    "peers": [{"public_key": "PEERPUB", "online": True,
                                               "handshake_age": handshake_age, "allowed_ips": "10.20.0.2/32",
                                               "rx_bytes": rx_bytes, "tx_bytes": rx_bytes // 2,
                                               "rx_speed": rx_speed, "tx_speed": tx_speed}]}},
            "turn_proxies": []}

def _with(nodes, k, v):
    nodes["n1"][k] = v
    return nodes

def _diff(a, b):
    """Digest paths (plus 'root') whose hash differs — what an operator would be shown."""
    out = [k for k in sorted(set(a["digest"]) | set(b["digest"]))
           if a["digest"].get(k) != b["digest"].get(k)]
    if a["root"] != b["root"]:
        out.append("root")
    return out

def _render(fpr):
    """The one deployment in a single-peer fixture, out of the returned render tree."""
    r = fpr["trees"]["render"]
    u = r[sorted(r)[0]]
    pr = u[sorted(u)[0]]
    return pr[sorted(pr)[0]]

def _deep(n):
    o = "leaf"
    for _ in range(n):
        o = {"k": o}
    return o


if __name__ == "__main__":
    # ⚠️ A CRASH MUST READ AS A FAILURE, not as silence. Any harness that scans for "FAIL" lines — the
    # perturbation sweep that keeps these checks honest is exactly that — sees a traceback as no failures
    # at all, so a guard whose perturbation happens to raise reports GREEN. That has now happened twice in
    # this file's history: once as a KeyError in a T-2 check (fixed there with .get()), and once when
    # gating fp_baseline_save on convergence turned a check into an exception. Fixing it at the call site
    # only fixes the call site; this fixes the class.
    try:
        main()
    except SystemExit:
        raise
    except BaseException as e:
        import traceback
        traceback.print_exc()
        print("  FAIL the suite CRASHED before finishing — %s: %s" % (type(e).__name__, e))
        print("\nFAILED: the suite did not finish, which is not the same as passing")
        sys.exit(1)
