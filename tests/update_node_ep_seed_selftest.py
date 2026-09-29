#!/usr/bin/env python3
"""Self-test — an UPGRADED master's own node record gets the endpoint its node already has, when that changes nothing
a client dials, and never while the panel is running.

Only a first enrolment ever wrote the endpoint into a master's own node record (install-host.sh), so a master
installed before that — or by 1.8.7 — kept endpoint_host '' through every update (1.8.8 qualification, q1: '' before
and after the 1.8.7 → 1.8.8 update). The panel fills a blank from the node's first PUBLIC address; a box with none (a
LAN, a NAT'd lab) never got one: no mesh dial host, and WDTT/csqtt on a wildcard bind advertised nothing.

update.sh now seeds it — from the agent config's node-level endpoint — only when ALL hold:
  · the agent dials THIS box's panel (loopback URL) and its token matches the record (token_sha, else pbkdf2);
  · the record is blank (a set one is the operator's, or the panel's own fill);
  · every interface in the agent config reports that same endpoint — the record OVERRIDES what the node reports per
    interface (apply_iface_meta), so seeding anything else would change client configs on an update;
  · it is an address of this box (the record is also the listen address pre-filled for turn-proxies);
and the write happens while the panel is STOPPED (nodes.json is the panel's own read-modify-write store), keeping the
file's owner and mode.

seed_local_node_ep + restart_panel_seeding_node_ep are lifted out of update.sh AS SHIPPED; systemctl is a stub that
records the order of stop / start / restart.

Run: python3 tests/update_node_ep_seed_selftest.py     (0 = pass)
     --perturb   the per-interface guard, the locality guard and the stop-before-write taken out → RED
"""
import base64, hashlib, json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
UP = open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(a, b):
    global UP
    assert UP.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    UP = UP.replace(a, b)

if PERTURB:
    plant("        sys.exit(0)                               # this interface reports its OWN endpoint — the record would override it\n",
          "        pass\n")
    plant("    sys.exit(0)                                   # not an address of this box (NAT, or a name pointing elsewhere)\n",
          "    pass\n")
    plant("  systemctl stop swg-panel-server || { run systemctl restart swg-panel-server; return; }\n  ep=\"$(seed_local_node_ep write)\"\n",
          "  ep=\"$(seed_local_node_ep write)\"\n  systemctl stop swg-panel-server || true\n")

def fn(name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), UP, re.M)
    assert m, "cannot extract " + name
    lines = UP[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)
FNS = fn("seed_local_node_ep") + fn("restart_panel_seeding_node_ep")

TOK = "tok-abc"
def pbkdf2(t):
    salt = b"0123456789abcdef"
    return "pbkdf2_sha256$1000$%s$%s" % (base64.b64encode(salt).decode(),
                                          base64.b64encode(hashlib.pbkdf2_hmac("sha256", t.encode(), salt, 1000)).decode())

def world(rec_ep="", agent_ep="192.168.77.1", ifaces=None, url="http://127.0.0.1:8088", legacy=False, tok=TOK):
    d = tempfile.mkdtemp(prefix="seed-"); st = os.path.join(d, "state"); os.makedirs(st)
    rec = {"id": "abc", "name": "q1m", "endpoint_host": rec_ep}
    if legacy:
        rec["token_hash"] = pbkdf2(tok)
    else:
        rec["token_sha"] = hashlib.sha256(tok.encode()).hexdigest()
    nodes = {"abc": rec, "zzz": {"id": "zzz", "name": "remote", "endpoint_host": "", "token_sha": "00"}}
    np = os.path.join(st, "nodes.json"); json.dump(nodes, open(np, "w"), indent=2); os.chmod(np, 0o640)
    cfg = os.path.join(d, "config.json")
    json.dump({"endpoint_host": agent_ep, "panel": {"url": url, "token": TOK},
               "interfaces": ifaces if ifaces is not None else {"awg0": {}, "wg0": {"endpoint_host": agent_ep}}}, open(cfg, "w"))
    log = os.path.join(d, "calls")
    # systemctl records each call and whether nodes.json had been seeded at that moment
    p = os.path.join(d, "systemctl"); open(p, "w").write(
        '#!/bin/bash\necho "$* EP=$(python3 -c \'import json,sys;print(json.load(open(sys.argv[1]))["abc"]["endpoint_host"])\' %s)" >> %s\nexit 0\n' % (np, log))
    os.chmod(p, 0o755)
    return d, st, np, cfg, log

def run(d, st, cfg, addrs="127.0.0.1 10.0.2.15 192.168.77.1", dry=False):
    script = ('set -euo pipefail\nDRYRUN=%s; STATE_DIR=%s\nRESULTS=(); note(){ RESULTS+=("$*"); }\nrun(){ if $DRYRUN; then echo "[skip] $*"; else "$@"; fi; }\n'
              'ok(){ echo "OK $*"; }\ncol_v(){ printf %%s "$*"; }\nhave(){ command -v "$1" >/dev/null 2>&1; }\n'
              'local_addrs(){ printf "%%s\\n" %s; }\n%s\nrestart_panel_seeding_node_ep\n') % (
        "true" if dry else "false", st, addrs, FNS.replace("/etc/swg-agent/config.json", cfg))
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=dict(os.environ, PATH=d + ":" + os.environ["PATH"]))
    return r.stdout + r.stderr

def ep_of(np):
    return json.load(open(np))["abc"]["endpoint_host"]

print("[1] the upgraded master's blank record gets its node's endpoint — with the panel stopped")
d, st, np, cfg, log = world()
out = run(d, st, cfg); calls = open(log).read().splitlines()
check("blank record, agent endpoint 192.168.77.1 (on this box), interfaces report the same → seeded", ep_of(np) == "192.168.77.1", out)
check("…written while the panel was STOPPED: stop (blank) → start (seeded), no restart",
      [c.split(" EP=")[0] for c in calls] == ["stop swg-panel-server", "start swg-panel-server"]
      and calls[0].endswith("EP=") and calls[1].endswith("EP=192.168.77.1"), calls)
check("…the file keeps its mode (the panel runs as its own user)", oct(os.stat(np).st_mode & 0o777) == "0o640", oct(os.stat(np).st_mode))
check("…the other nodes' records are untouched", json.load(open(np))["zzz"]["endpoint_host"] == "", json.load(open(np))["zzz"])
check("…and it is said", "now carries its endpoint 192.168.77.1" in out, out)
d, st, np, cfg, log = world(legacy=True)
out = run(d, st, cfg)
check("a legacy record (pbkdf2 token_hash, no token_sha) is found the same way", ep_of(np) == "192.168.77.1", out)

print("\n[2] anything that would change what a client dials, or be wrong, is left alone (plain restart)")
for why, kw, addrs in (
        ("the record already has an endpoint (the operator's, or the panel's fill)", {"rec_ep": "vpn.example.com"}, None),
        ("an interface reports its OWN endpoint — the record would override it", {"ifaces": {"awg0": {"endpoint_host": "awg.example.com"}}}, None),
        ("the endpoint is not an address of this box (NAT'd public IP)", {"agent_ep": "203.0.113.7", "ifaces": {}}, None),
        ("the agent syncs to ANOTHER panel", {"url": "https://192.168.77.5:2087"}, None),
        ("the token matches no record here", {"tok": "someone-else"}, None)):
    d, st, np, cfg, log = world(**kw)
    before = ep_of(np)
    out = run(d, st, cfg, **({"addrs": addrs} if addrs else {}))
    calls = [c.split(" EP=")[0] for c in open(log).read().splitlines()]
    check(why, ep_of(np) == before and calls == ["restart swg-panel-server"], (calls, out))
d, st, np, cfg, log = world()
out = run(d, st, cfg, dry=True)
check("a dry run seeds nothing and stops nothing", ep_of(np) == "" and not os.path.exists(log) and "[skip]" in out, out)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
