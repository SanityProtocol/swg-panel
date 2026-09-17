#!/usr/bin/env python3
"""Self-test: a node whose stored dial address is no longer on the box must SAY SO.

`endpoint_host` is "auto" while it is empty — and the sync fills it from the node's reported public IP and
SAVES it (swg-panel-server, the node-sync handler). From that moment it is a pinned literal, and nothing
ever revisits it: `mesh_endpoint_host()` reads `stored or reported`, so once stored the reported value can
never win again.

What that cost, measured 2026-09-16 on a customer's box whose provider changed its IP: the panel kept
handing out the dead address. It prefilled the listen-IP picker, so every turn-proxy installed or edited
afterwards was born with `-listen <dead ip>`, panicked on bind and crash-looped — 262 panics against 272
starts in 90 minutes. The operator's symptom was "clients connect but get no traffic", and the address was
the last thing suspected, because the panel's own interface screens showed the NEW one (apply_iface_meta
overlays the node record on top of the snapshot).

What this drives, through the REAL `_node_issues`:
  [1] a stored IP the node no longer reports is called out, naming the address and the consequence
  [2] the address the node DOES report raises nothing
  [3] a DNS name is never flagged — endpoint_host is legitimately a hostname (hel.sanitygate.net), which
      can never appear in node_ips, so an unguarded test would fire on every domain-based install
  [4] "the node did not report any addresses" is not evidence of staleness
  [5] auto (empty) raises nothing — that is the healthy state this whole field starts in
  [6] the panel does NOT silently rewrite it: an operator may have pinned an address deliberately

Hermetic: no network, no state; `_node_issues` is called directly.

Run: python3 tests/stale_endpoint_host_selftest.py     (0 = pass)
     --perturb       drops the check entirely (how it shipped) — expects RED in [1]
     --perturb-name  drops the _is_ip guard — expects RED in [3], the false alarm that would fire on
                     every install whose endpoint_host is a domain
"""
import os, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

PLANTS = {
    "--perturb": ('    if _eh and nips and _is_ip(_eh) and _eh not in nips:', '    if False:'),
    "--perturb-name": ('if _eh and nips and _is_ip(_eh) and _eh not in nips:', 'if _eh and nips and _eh not in nips:'),
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:200]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(PANEL, encoding="utf-8").read()
if MODE:
    cut, new = PLANTS[MODE]
    assert src.count(cut) == 1, "perturbation anchor for %s missing or not unique — would FALSE-PASS" % MODE
    src = src.replace(cut, new, 1)

P = types.ModuleType("p")
P.__dict__.update({"__name__": "p", "__file__": PANEL})
exec(compile(src.split("\nif __name__ ==")[0], "swg-panel-server", "exec"), P.__dict__)

LIVE, DEAD = "82.24.110.35", "46.17.99.41"

def issues(endpoint_host, node_ips):
    c = {"endpoint_host": endpoint_host}
    snap = {"node_ips": list(node_ips), "node_ifaces": []}
    return [str(i.get("error") or "") for i in P._node_issues(c, snap)]

def said(msgs):
    return [mm for mm in msgs if "no longer on this node" in mm]

# ── [1] the stale pin is called out ───────────────────────────────────────────────────────────────
print("[1] an address the node no longer has is reported")
msgs = issues(DEAD, [LIVE])
check("[1] the stale address is flagged", len(said(msgs)) == 1, msgs)
check("[1] …naming the address itself", any(DEAD in mm for mm in said(msgs)), msgs)
check("[1] …and the consequence an operator would otherwise chase for hours",
      any("fail to start" in mm for mm in said(msgs)), msgs)

# ── [2] the current address is fine ───────────────────────────────────────────────────────────────
print("\n[2] the address the node actually reports raises nothing")
check("[2] a matching pin is silent", said(issues(LIVE, [LIVE])) == [], issues(LIVE, [LIVE]))
check("[2] …including when the node has several addresses",
      said(issues(LIVE, ["10.0.0.5", LIVE])) == [], issues(LIVE, ["10.0.0.5", LIVE]))

# ── [3] a hostname is not an address ──────────────────────────────────────────────────────────────
print("\n[3] a DNS name is never flagged")
for name in ("teabata.swgpanel.com", "hel.sanitygate.net"):
    check("[3] %s is left alone — it cannot appear in node_ips by definition" % name,
          said(issues(name, [LIVE])) == [], issues(name, [LIVE]))

# ── [4] no reported addresses is not evidence ─────────────────────────────────────────────────────
print("\n[4] 'the node did not say' is not 'the address is stale'")
check("[4] an empty node_ips yields no verdict", said(issues(DEAD, [])) == [], issues(DEAD, []))

# ── [5] auto is the healthy default ───────────────────────────────────────────────────────────────
print("\n[5] auto (empty) is silent")
check("[5] an unset endpoint_host raises nothing", said(issues("", [LIVE])) == [], issues("", [LIVE]))

# ── [6] the panel says it, it does not silently 'fix' it ──────────────────────────────────────────
print("\n[6] a health check reports; it does not rewrite what configs dial")
c = {"endpoint_host": DEAD}
P._node_issues(c, {"node_ips": [LIVE], "node_ifaces": []})
check("[6] the node record is left exactly as the operator has it", c["endpoint_host"] == DEAD, c)

if MODE:
    if FAILS:
        print("\nperturbed (%s): CAUGHT (%d red)" % (MODE, len(FAILS)))
        sys.exit(0)
    print("\nperturbed (%s): NOTHING FAILED — this gate does not test what it claims" % MODE)
    sys.exit(1)
print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
