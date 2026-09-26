#!/usr/bin/env python3
"""Self-test: a docker MASTER's auto-enroll hands the endpoint the operator gave to the panel (nodes.json endpoint_host).

Measured in the 1.8.8-beta qualification: a fresh docker master with NODE_ENDPOINT=192.168.77.6 came up with
nodes.json endpoint_host '' for its own node. The installer writes that entry itself (it mints the token and
pre-writes nodes.json before `compose up`) and always wrote "". The panel fills a blank endpoint_host only from a
PUBLIC IP the node reports (node_public_ip skips private ranges), so a node whose clients dial a LAN / NAT'd address
had no dial host at all — the mesh and the address the panel hands out had nothing to use.

  [1] a new entry takes the given endpoint
  [2] an existing entry with a BLANK endpoint_host is filled
  [3] an existing entry with an endpoint the operator set in the panel is left alone
  [4] no endpoint given (auto-detected) → blank, as before: the panel's own auto-fill stays in charge
  [5] the shell call passes the GIVEN endpoint (not the auto-detected NODE_ENDPOINT) to the writer

The writer is the python heredoc lifted verbatim out of install-docker.sh's auto-enroll block.

Run: python3 tests/docker_master_endpoint_host_selftest.py      (0 = pass)
     --perturb   re-plants the shipped writer (endpoint_host always "") → RED
"""
import json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERTURB = "--perturb" in sys.argv
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


src = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
m = re.search(r'  if python3 - "\$ndir/nodes\.json" (.*?) <<\'PY\'\n(.*?)\nPY\n', src, re.S)
assert m, "auto-enroll writer missing — this run would FALSE-PASS"
call_args, WRITER = m.group(1), m.group(2)
if PERTURB:
    for a, b in [('"endpoint_host": given_ep.strip(),', '"endpoint_host": "",'),
                 ("    if given_ep.strip() and not", "    if False and not")]:
        assert WRITER.count(a) == 1, "perturbation anchor missing — this run would FALSE-PASS: %r" % a
        WRITER = WRITER.replace(a, b, 1)

T = tempfile.mkdtemp(prefix="mastereph-")
W = os.path.join(T, "writer.py"); open(W, "w").write(WRITER)


def run(nodes, given, name="q6-dmaster", token="tok-0123456789abcdef"):
    p = os.path.join(T, "nodes.json")
    if nodes is None:
        if os.path.exists(p):
            os.remove(p)
    else:
        json.dump(nodes, open(p, "w"))
    r = subprocess.run([sys.executable, W, p, name, token, "#34d399", given], capture_output=True, text=True)
    return r.returncode, json.load(open(p))


def entry(d, name="q6-dmaster"):
    return next((v for v in d.values() if v.get("name") == name), {})


print("[1] a new entry takes the given endpoint")
rc, d = run(None, "192.168.77.6")
check("endpoint_host = 192.168.77.6", rc == 0 and entry(d).get("endpoint_host") == "192.168.77.6", (rc, entry(d)))

print("\n[2] an existing entry with a blank endpoint_host is filled")
rc, d = run({"n1": {"name": "q6-dmaster", "endpoint_host": "", "token_hash": "x"}}, "192.168.77.6")
check("filled with 192.168.77.6", entry(d).get("endpoint_host") == "192.168.77.6", entry(d))

print("\n[3] an endpoint the operator set in the panel is left alone")
rc, d = run({"n1": {"name": "q6-dmaster", "endpoint_host": "vpn.example.net", "token_hash": "x"}}, "192.168.77.6")
check("still vpn.example.net", entry(d).get("endpoint_host") == "vpn.example.net", entry(d))

print("\n[4] nothing given → blank, as before")
rc, d = run(None, "")
check("endpoint_host ''", rc == 0 and entry(d).get("endpoint_host") == "", entry(d))

print("\n[5] the shell call passes the GIVEN endpoint")
check('the 5th argument is "${_GIVEN_NODE_ENDPOINT:-}"', call_args.strip().endswith('"${_GIVEN_NODE_ENDPOINT:-}"'), call_args)

print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PERTURB:
    print("(--perturb expects RED above)")
sys.exit(1 if FAILS else 0)
