#!/usr/bin/env python3
"""Self-test for §1.5's address reset over a LIST — `node_record.endpoint_hosts`.

The bug this locks down: both halves of the migration reset descended dicts only. `fp_transform`'s walk
returns on anything that is not a dict, and `fp_diff`'s `judge` coerced a non-string to "" before handing
it to the verdict. So a field whose value is a LIST was invisible to the reset AND to the check that
exists to catch a reset that did not happen. `endpoint_hosts` is exactly that field — the node's other
names, offered in every picker that asks for a host — so a rebuilt node kept the OLD box's IP among the
addresses it invites the operator to choose, and the diff read clean.

Proved on a constructed record 2026-09-08: every scalar address reset, `endpoint_hosts` came through
untouched.

Hermetic: builds records in memory and calls fp_transform / fp_diff directly. No state dir, no network.

Run: python3 tests/fp_list_reset_selftest.py (0 = pass).
  --perturb            back out both halves and expect red
  --perturb=<name>     one of: transform | verdict | rule
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

PERTURBATIONS = {
    # the transform stops seeing a list — the shipped behaviour before the fix
    "transform": ('elif verb in ("host_swap", "bind_swap") and isinstance(v, (str, list)):',
                  'elif verb in ("host_swap", "bind_swap") and isinstance(v, str):'),
    # the verdict stops seeing a list, so a stale entry produces no row
    "verdict":   ('            if isinstance(av, list) or isinstance(bv, list):',
                  '            if False:'),
    # the NIC-name reset goes away — the second field the cross-check found
    "wan":       ('        ("residue.ifaces.*.wan_iface", "cleared",   "the NIC this interface egresses out of — a device name is the OLD box\'s"),\n',
                  ''),
    # the verdict goes back to skipping an element it cannot read, while the transform still KEEPS it
    "nonstr":    ('            worst = "review" if RANK[worst] < 1 else worst\n'
                  '            notes.append("%.120r — not a name; kept as it was, so check it by hand" % (x,))\n'
                  '            continue',
                  '            continue'),
    # the table forgets the field entirely
    "rule":      ('        ("residue.endpoint_hosts",     "host_swap", "the node\'s other names, offered wherever a host is asked for"),\n',
                  ''),
}
ASKED = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--perturb=")]
ALL = any(a == "--perturb" for a in sys.argv)
WANT = list(PERTURBATIONS) if ALL else ASKED
PERTURB = bool(WANT)

src = open(SERVER, encoding="utf-8").read()
path = SERVER
if PERTURB:
    for name in WANT:
        frm, to = PERTURBATIONS[name]
        if src.count(frm) != 1:
            print("HARNESS BROKEN: perturbation %r matched %d times, not 1" % (name, src.count(frm)))
            sys.exit(2)
        src = src.replace(frm, to, 1)
    path = os.path.join(tempfile.mkdtemp(), "swg-panel-server")
    open(path, "w", encoding="utf-8").write(src)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:220]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

loader = importlib.machinery.SourceFileLoader("srv", path)
spec = importlib.util.spec_from_loader("srv", loader)
S = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(S)
except SystemExit:
    pass

OLD, NEW, FRONT = "201.24.126.212", "5.42.109.16", "198.51.100.7"
CTX = {"before_ips": [OLD], "after_ips": [NEW]}

def rec(hosts):
    return {"id": "n1", "name": "probe", "endpoint_host": OLD, "endpoint_hosts": list(hosts)}

print("── the reset (fp_transform) ──")
out, actions = S.fp_transform(rec([OLD, "node.example.org", NEW]), "rebuild", CTX)
got = out.get("endpoint_hosts")
check("the OLD box's IP is dropped from the list", OLD not in got, got)
check("a hostname is kept — it re-resolves to the new box", "node.example.org" in got, got)
check("an IP the NEW box has is kept", NEW in got, got)
check("the scalar endpoint_host still resets too", out.get("endpoint_host") == "", out.get("endpoint_host"))
check("the reset is reported as an action",
      any(a[0] == "endpoint_hosts" for a in actions), [a[0] for a in actions])

out2, _ = S.fp_transform(rec([FRONT, "a.example.org"]), "rebuild", CTX)
check("an IP the box NEVER reported is kept — a deliberate front door is not ours to delete",
      out2.get("endpoint_hosts") == [FRONT, "a.example.org"], out2.get("endpoint_hosts"))

out3, _ = S.fp_transform(rec([]), "rebuild", CTX)
check("an empty list survives as an empty list", out3.get("endpoint_hosts") == [], out3.get("endpoint_hosts"))

# ⚠️ MY FIRST VERSION OF THIS CHECK ASSERTED THE OPPOSITE, and the code was right. With
# `after_ips=None` — the normal rebuild, where the new box has not reported yet — the TRANSFORM still
# resets, while the VERDICT returns "unknown". That asymmetry is deliberate and the scalar beside this
# field has always behaved the same way: a reset to blank means "derive at install" and costs nothing,
# whereas BLOCKING a dry-run teaches the operator to force past the screen the severities exist for.
# The list must match the scalar it sits beside, so it resets too. Verified against `endpoint_host`.
out4, _ = S.fp_transform(rec([OLD]), "rebuild", {"before_ips": [OLD], "after_ips": None})
scal, _ = S.fp_transform({"endpoint_host": OLD}, "rebuild", {"before_ips": [OLD], "after_ips": None})
check("a prospective run resets, exactly as the scalar endpoint_host does",
      out4.get("endpoint_hosts") == [] and scal.get("endpoint_host") == "",
      (out4.get("endpoint_hosts"), scal.get("endpoint_host")))

print("── the check (fp_diff), which is the half that protects anything ──")
def fp(tree):
    return {"trees": {"residue": tree}, "cannot_predict": []}

# the failure this exists for: the record came back with the stale entry still in it
before = fp({"endpoint_hosts": [OLD, "node.example.org"], "endpoint_host": OLD})
after_bad = fp({"endpoint_hosts": [OLD, "node.example.org"], "endpoint_host": ""})
d = S.fp_diff(before, after_bad, "rebuild", CTX)
blocked = [b for b in d["blocks"] if b["path"].endswith("endpoint_hosts")]
check("a stale entry that did NOT move is BLOCKED (the affirmative pass)", bool(blocked),
      {k: d[k] for k in ("blocks", "review")})

after_ok = fp({"endpoint_hosts": ["node.example.org", NEW], "endpoint_host": ""})
d2 = S.fp_diff(before, after_ok, "rebuild", CTX)
check("a correctly reset list does not block",
      not [b for b in d2["blocks"] if b["path"].endswith("endpoint_hosts")], d2["blocks"])

# ⚠️ AN ELEMENT THAT IS NOT A NAME. The transform KEEPS it (a value we cannot read is not a value we may
# throw away) — so the verdict has to say something about it, or the two halves answer differently about
# one element and the diff reads "every name is the new box's" over a retained OLD-box value. That is the
# drift the shared helpers exist to make impossible, and the verdict used to `continue` straight past it.
kept, _ = S.fp_transform(rec([OLD, {"was": OLD}, 7]), "rebuild", CTX)
check("the transform keeps an element it cannot read", kept.get("endpoint_hosts") == [{"was": OLD}, 7],
      kept.get("endpoint_hosts"))
before_w = fp({"endpoint_hosts": [OLD, {"was": OLD}], "endpoint_host": OLD})
after_w  = fp({"endpoint_hosts": [{"was": OLD}], "endpoint_host": ""})
d3 = S.fp_diff(before_w, after_w, "rebuild", CTX)
flagged = [r for r in (d3["review"] + d3["blocks"]) if r["path"].endswith("endpoint_hosts")]
check("…and the verdict does NOT call that list clean", bool(flagged),
      {k: d3[k] for k in ("blocks", "review")})

# …and it must not be reported as "never looked at"
missed = [c for c in d2["cannot_predict"] if "endpoint_hosts" in c]
check("the rule is recorded as having RUN, not as unlooked-at", not missed, d2["cannot_predict"])

print("── the neighbours it must not have disturbed ──")
out5, _ = S.fp_transform(
    {"id": "n1", "default_egress_ip": OLD, "panel_ip": OLD, "mesh_egress_ip": OLD,
     "ifaces": {"awg0": {"endpoint_host": OLD, "egress_ip": OLD, "keepalive": 25}}},
    "rebuild", CTX)
check("the four scalar source-IP fields still reset",
      out5.get("default_egress_ip") == "" and out5.get("panel_ip") == ""
      and out5.get("mesh_egress_ip") == "" and out5["ifaces"]["awg0"]["egress_ip"] == "", out5)
check("keepalive is untouched — it is not box-specific",
      out5["ifaces"]["awg0"].get("keepalive") == 25, out5["ifaces"]["awg0"])

print("── the OTHER field the reset cross-check found: a NIC NAME ──")
# `wan_iface` pins which interface an interface's egress MASQUERADEs out of. A device name does not
# travel: this project's own fleet is `eth0` on three boxes and `ens3` on the fourth, so a node rebuilt
# across that boundary wrote `-o eth0` into a POSTROUTING rule the new box cannot install and its
# clients lost egress with nothing saying why. Blank already means auto-detect.
out6, acts6 = S.fp_transform({"ifaces": {"awg0": {"wan_iface": "eth0", "mtu": 1280}}}, "rebuild", CTX)
check("wan_iface is cleared outright", "wan_iface" not in out6["ifaces"]["awg0"], out6["ifaces"]["awg0"])
check("…and nothing else on that interface moved", out6["ifaces"]["awg0"].get("mtu") == 1280, out6["ifaces"]["awg0"])
check("…and it is reported as an action",
      any(a[0] == "ifaces.awg0.wan_iface" for a in acts6), [a[0] for a in acts6])
d3 = S.fp_diff(fp({"ifaces": {"awg0": {"wan_iface": "eth0"}}}),
               fp({"ifaces": {"awg0": {"wan_iface": "eth0"}}}), "rebuild", CTX)
check("a wan_iface that survived a rebuild is BLOCKED",
      any(b["path"].endswith("wan_iface") for b in d3["blocks"]), d3["blocks"])

print()
if PERTURB:
    if FAILS:
        print("PERTURB(%s) OK — %d check(s) red: %s" % (",".join(WANT), len(FAILS), FAILS[:4]))
        sys.exit(0)
    print("PERTURB(%s) FAILED — everything still passed with that part removed" % ",".join(WANT))
    sys.exit(1)
if FAILS:
    print("FAIL: %d — %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("PASS")
