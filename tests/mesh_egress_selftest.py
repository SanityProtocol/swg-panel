#!/usr/bin/env python3
"""Self-test for the mesh EGRESS source rule — which of a node's addresses it dials its mesh peers from.

Two controls, one default. `nodes[nid]["mesh_egress_ip"]` is the node-level default and the per-connection
`links[peer]["dial_src"]` overrides it, and the ordering matters in a way that is easy to get backwards: the
default has to be the DURABLE one, because a per-link value is not. `mesh_reprovision_node` clears `links`
wholesale and `_mesh_make_link` rebuilds the records without dial_src, so a source set on a single connection
card is dropped by the next re-provision or migration — which is exactly why the node-level setting exists.

Hermetic: no network, no state dir, no panel process. Run: python3 tests/mesh_egress_selftest.py (0 = pass)
"""
import importlib.machinery, importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

loader = importlib.machinery.SourceFileLoader("swgpanel", SERVER)
spec = importlib.util.spec_from_loader("swgpanel", loader)
P = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(P)
except SystemExit:
    pass


def nodes(dial_src=None, mesh_egress=None):
    """Two linked nodes, the remote end ready (blessed pubkey + listen port + endpoint), so a peer is emitted."""
    link = {"iface": "swg_aa", "peer_address": "10.255.0.1", "psk": "none"}
    if dial_src is not None:
        link["dial_src"] = dial_src
    a = {"name": "a", "links": {"b": link}, "ifaces": {"swg_aa": {}}}
    if mesh_egress is not None:
        a["mesh_egress_ip"] = mesh_egress
    b = {"name": "b", "endpoint_host": "198.51.100.9",
         "links": {"a": {"iface": "swg_bb", "peer_address": "10.255.0.0", "listen_port": 9999}},
         "ifaces": {"swg_bb": {"public_key": "REMOTEPUB="}}}
    return {"a": a, "b": b}


def dial_src_of(**kw):
    out = P.desired_mesh_for_node(nodes(**kw), "a", 25)
    peers = (out or {}).get("swg_aa") or []
    return peers[0].get("dial_src") if peers else "<no peer emitted>"


print("[mesh egress] the source a node dials its mesh peers from")
check("a node with neither set dials from wherever the route says (blank)",
      dial_src_of() == "", dial_src_of())
check("the node-level mesh egress becomes every link's source",
      dial_src_of(mesh_egress="203.0.113.7") == "203.0.113.7", dial_src_of(mesh_egress="203.0.113.7"))
check("a per-connection dial_src OVERRIDES the node default",
      dial_src_of(dial_src="203.0.113.8", mesh_egress="203.0.113.7") == "203.0.113.8",
      dial_src_of(dial_src="203.0.113.8", mesh_egress="203.0.113.7"))
check("...and a BLANK per-connection value falls back to the default, not to nothing",
      dial_src_of(dial_src="", mesh_egress="203.0.113.7") == "203.0.113.7",
      dial_src_of(dial_src="", mesh_egress="203.0.113.7"))
check("a per-connection source still works with no node default",
      dial_src_of(dial_src="203.0.113.8") == "203.0.113.8", dial_src_of(dial_src="203.0.113.8"))

print("\n" + ("ALL PASS" if not FAILS else "FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
