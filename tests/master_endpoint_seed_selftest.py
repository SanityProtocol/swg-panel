#!/usr/bin/env python3
"""Self-test — a master's OWN node record carries the endpoint the operator gave the installer.

A bare master installed with HOST_ENDPOINT_IP=192.168.77.1 wrote that value into the agent config only; the panel's
node store (nodes.json) got endpoint_host ''. The panel fills an empty one from the node's first PUBLIC address, so a
box with none (a LAN, a NAT'd lab — the 1.8.8 qualification guests) never got one: mesh peers had no host to dial, and
recreating a ghost interface (js/peer-actions.js) fell back to the node's first IP, 10.0.2.15.

Now the merge seeds endpoint_host from an EXPLICIT HOST_ENDPOINT_IP, only when the record holds none. A detected
default is never written (the panel's own fill does that better), and an endpoint already set is the operator's.

The PYNODES merge is lifted out of install-host.sh AS SHIPPED and run over temp node stores.

…and ONLY an address this box has (a LAN address, a public one on its NIC, a name resolving to one): the record is also
the listen address the panel pre-fills for turn-proxies, and a NAT'd public IP there cannot be bound (section [2]).

Run: python3 tests/master_endpoint_seed_selftest.py     (0 = pass)
     --perturb           the seed taken back out → RED
     --perturb-locality  the locality check taken out (any given value seeds, as c5cb1df did) → RED
"""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
PERTURB_LOC = "--perturb-locality" in sys.argv
C = open(os.path.join(ROOT, "lib/common.sh"), encoding="utf-8").read()
src = open(os.path.join(ROOT, "install-host.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

i = src.index("<<'PYNODES'\n") + len("<<'PYNODES'\n"); j = src.index("\nPYNODES\n", i)
py = src[i:j]
# the shell hands python the value as the operator GAVE it — captured before any default fills HOST_ENDPOINT_IP
assert '_EP_GIVEN="$HOST_ENDPOINT_IP"' in src and '"$LOCAL_TOKHASH" "$_EP_SEED"' in src, "call-site anchor missing"
assert src.index('_EP_GIVEN="$HOST_ENDPOINT_IP"') < src.index('[ -z "$HOST_ENDPOINT_IP" ] && HOST_ENDPOINT_IP="$(detect_public_ip)"'), \
    "_EP_GIVEN must be captured BEFORE the detected default fills HOST_ENDPOINT_IP"
if PERTURB:
    a = '    cur["endpoint_host"] = ep_given.strip()\n'
    assert py.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    py = py.replace(a, "    pass\n")

def merge(store, ep):
    d = tempfile.mkdtemp(prefix="nodes-"); p = os.path.join(d, "nodes.json")
    if store is not None:
        json.dump(store, open(p, "w"))
    r = subprocess.run([sys.executable, "-", p, "abc123", "q1m", "#fff", "pbkdf2_sha256$x", ep], input=py,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)

out = merge(None, "192.168.77.1")
check("fresh store + HOST_ENDPOINT_IP=192.168.77.1 → the local node's endpoint_host is 192.168.77.1",
      out["abc123"]["endpoint_host"] == "192.168.77.1", out)
out = merge(None, "")
check("no explicit endpoint → '' as before (the panel fills it from a public address)", out["abc123"]["endpoint_host"] == "", out)
out = merge({"abc123": {"id": "abc123", "name": "q1m", "endpoint_host": "vpn.example.com"}}, "192.168.77.1")
check("an endpoint already on the record (the operator's, or the panel's fill) is never overwritten",
      out["abc123"]["endpoint_host"] == "vpn.example.com", out)
out = merge({"abc123": {"id": "abc123", "name": "q1m", "endpoint_host": ""}}, "192.168.77.1")
check("a re-enroll over an EMPTY record seeds it", out["abc123"]["endpoint_host"] == "192.168.77.1", out)
out = merge({"zzz": {"id": "zzz", "name": "remote", "endpoint_host": ""}}, "192.168.77.1")
check("every OTHER node's record is left exactly as it was", out["zzz"] == {"id": "zzz", "name": "remote", "endpoint_host": ""}, out)

print("\n[2] only an address this box HAS is seeded (install-host.sh's guard, lib/common.sh host_is_local)")
g = src[src.index('  _EP_SEED=""\n'):src.index('  _NODES_MERGED="$(python3')]
if PERTURB_LOC:
    a = '    if host_is_local "$_EP_GIVEN"; then _EP_SEED="$_EP_GIVEN"\n'
    assert g.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    g = g.replace(a, '    if true; then _EP_SEED="$_EP_GIVEN"\n')
def fn(text, name):
    import re as _re
    m = _re.search(r"^%s\(\)\{" % _re.escape(name), text, _re.M)
    lines = text[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            t = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=t, capture_output=True, text=True).returncode == 0:
                return t
helpers = fn(C, "local_addrs") + fn(C, "host_is_local")
def seed(given, resolves=""):
    d = tempfile.mkdtemp(prefix="loc-")
    for n, body in (("ip", "printf '1: lo    inet 127.0.0.1/8 scope host lo\\n3: ens4    inet 192.168.77.1/24 scope global ens4\\n'"),
                    ("hostname", "echo 10.0.2.15 192.168.77.1"),
                    ("getent", '[ -n "%s" ] && echo "%s STREAM $2" || exit 2' % (resolves, resolves))):
        p = os.path.join(d, n); open(p, "w").write("#!/bin/bash\n" + body + "\n"); os.chmod(p, 0o755)
    r = subprocess.run(["bash", "-c", 'set -euo pipefail\nsub(){ echo "SUB $*"; }\n_EP_GIVEN="%s"\n%s%s\necho "SEED=$_EP_SEED"\n' % (given, helpers, g)],
                       capture_output=True, text=True, env=dict(os.environ, PATH=d + ":" + os.environ["PATH"]))
    return r.stdout + r.stderr
out = seed("192.168.77.1", resolves="192.168.77.1")
check("192.168.77.1, assigned to ens4 → seeded", "SEED=192.168.77.1" in out, out)
out = seed("panel.lan", resolves="192.168.77.1")
check("a name that resolves to an address of this box → seeded", "SEED=panel.lan" in out, out)
out = seed("203.0.113.7", resolves="203.0.113.7")
check("a NAT'd public IP (not on any interface) → NOT seeded, and said", "SEED=\n" in out + "\n" and "not an address of this box" in out, out)
out = seed("nowhere.invalid")
check("a name that does not resolve → NOT seeded (fail safe)", "SEED=\n" in out + "\n", out)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if (PERTURB or PERTURB_LOC) else ""))
sys.exit(2 if (PERTURB or PERTURB_LOC) else 0)
