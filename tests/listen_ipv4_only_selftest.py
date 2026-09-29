#!/usr/bin/env python3
"""Self-test — THE LISTEN IP FIELDS TAKE IPv4 ONLY, AND SAY WHY THEY REFUSE AN IPv6 ONE (N3).

Neither server binds IPv6: the panel and swg-sub listen AF_INET (ThreadingHTTPServer's default), and a Docker install
publishes the address as `${PANEL_BIND}:${PANEL_PORT}:8443`, where an IPv6 one is not even valid compose. Yet the Listen
IP field took "::" or one of the box's inet6 addresses — the address list offered them — and the apply then rolled
back with nothing saying why (1.8.8 qualification, round 10, N3). Now a Save refuses one, with a sentence that says
what to use instead, and the list offers IPv4 only.

  [1] validate_access, driven: "::", "::1", a global and a link-local IPv6 address → refused for the panel AND for
      the subscription server, each with the sentence naming the address, the reason (IPv4 only) and what to use;
      0.0.0.0, 127.0.0.1, a box address and an untouched field → accepted as before
  [2] _bindable_ips, driven: `ip -o addr` output with inet and inet6 lines → IPv4 only (a bare box); SWG_HOST_IPS with
      both families → IPv4 only (a Docker panel, whose installer hands the host's addresses in)
  [3] the premise: neither server's listener is IPv6 (no AF_INET6 anywhere in either), and compose publishes the
      address as `<bind>:<port>:<container port>`
  [4] the sentence has its Russian (js/lang/ru.js)

Run: python3 tests/listen_ipv4_only_selftest.py        (0 = pass)
     --perturb   two plants, each on its own — each must turn its own check red
"""
import os, subprocess, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_L4_PANEL") or os.path.join(ROOT, "swg-panel-server")
SRC = open(PANEL, encoding="utf-8").read()

PLANTS = [
    ("validate", '        if ":" in str(ep["host"]):\n', '        if False:\n', "[1] an IPv6 listen address is refused"),
    ("list", '            if len(p) >= 4 and p[2] == "inet" and not _IFACE_SKIP_RE.match(p[1]):',
     '            if len(p) >= 4 and p[2] in ("inet", "inet6") and not _IFACE_SKIP_RE.match(p[1]):', "[2] a bare box lists IPv4 only"),
]
if "--perturb" in sys.argv:
    bad = 0
    for name, old, new, must in PLANTS:
        if SRC.count(old) != 1:
            print("  %-9s STALE ANCHOR (%d) — this plant would plant nothing" % (name, SRC.count(old))); bad += 1; continue
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix="-" + name); f.write(SRC.replace(old, new)); f.close()
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, SWG_L4_PANEL=f.name), capture_output=True, text=True, timeout=180)
        os.unlink(f.name)
        red = ("FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-9s %s" % (name, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")))
        bad += not red
    print("%d plants, %d caught" % (len(PLANTS), len(PLANTS) - bad))
    sys.exit(1 if bad else 0)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)

m = types.ModuleType("p")
m.__dict__.update({"__name__": "p", "__file__": PANEL})
exec(compile(SRC.split("\nif __name__ ==")[0], "swg-panel-server", "exec"), m.__dict__)
m._dns_resolves = lambda host: True     # never a DNS query from a gate

print("[1] validate_access: an IPv6 listen address is refused, with the reason")
def errs(side, host):
    inc = {side: {"host": host, "port": 8444 if side == "sub" else 8443}}
    _clean, e, _w = m.validate_access(inc, {})
    return e
for host in ("::", "::1", "2001:db8::10", "fe80::1"):
    for side, label in (("panel", "Panel"), ("sub", "Subscription")):
        e = [x for x in errs(side, host) if "IPv6" in x]
        check("[1] an IPv6 listen address is refused — %s, %s" % (label, host),
              len(e) == 1 and e[0].startswith(label + ": the listen IP " + host + " is an IPv6 address")
              and "listens on IPv4 only" in e[0] and "0.0.0.0" in e[0] and "127.0.0.1" in e[0], errs(side, host))
for host in ("0.0.0.0", "127.0.0.1", "203.0.113.7", ""):
    for side, label in (("panel", "Panel"), ("sub", "Subscription")):
        e = errs(side, host)
        check("[1] an IPv4 one (or none) is taken as before — %s, %r" % (label, host), not [x for x in e if "IPv6" in x], e)

print("\n[2] the address list offers IPv4 only")
stub = tempfile.mkdtemp(prefix="l4-")
open(os.path.join(stub, "ip"), "w").write(
    "#!/bin/sh\ncat <<'EOF'\n"
    "2: eth0    inet 203.0.113.7/24 brd 203.0.113.255 scope global eth0\\       valid_lft forever preferred_lft forever\n"
    "2: eth0    inet6 2001:db8::7/64 scope global \\       valid_lft forever preferred_lft forever\n"
    "3: ens4    inet 198.51.100.9/24 scope global ens4\\       valid_lft forever preferred_lft forever\n"
    "3: ens4    inet6 2001:db8:1::9/64 scope global dynamic \\       valid_lft 86000sec preferred_lft 14000sec\n"
    "EOF\n")
os.chmod(os.path.join(stub, "ip"), 0o755)
_path = os.environ["PATH"]
os.environ["PATH"] = stub + ":" + _path
try:
    m.IN_DOCKER = False
    got = m._bindable_ips()
finally:
    os.environ["PATH"] = _path
check("[2] a bare box lists IPv4 only", [x["ip"] for x in got] == ["203.0.113.7", "198.51.100.9"] and all(x["family"] == 4 for x in got), got)
os.environ["SWG_HOST_IPS"] = "203.0.113.7|eth0 2001:db8::7|eth0 198.51.100.9|ens4 fe80::1|eth0"
try:
    m.IN_DOCKER = True
    got = m._bindable_ips()
finally:
    m.IN_DOCKER = False; os.environ.pop("SWG_HOST_IPS", None)
check("[2] a Docker panel lists IPv4 only from the host's addresses", [x["ip"] for x in got] == ["203.0.113.7", "198.51.100.9"], got)

print("\n[3] the premise: neither listener is IPv6")
SUB = open(os.path.join(ROOT, "swg-sub"), encoding="utf-8").read()
COMPOSE = open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8").read()
check("[3] no AF_INET6 in the panel or in swg-sub (both serve on ThreadingHTTPServer's AF_INET)",
      "AF_INET6" not in SRC.split("\nif __name__ ==")[0] and "AF_INET6" not in SUB and "address_family" not in SUB)
check("[3] compose publishes the panel and swg-sub as <bind>:<port>:<container port> (an IPv6 bind is not valid there)",
      '"${PANEL_BIND:-0.0.0.0}:${PANEL_PORT:-443}:8443"' in COMPOSE and '"${SUB_BIND:-0.0.0.0}:${SUB_PORT:-8444}:8444"' in COMPOSE)

print("\n[4] the sentence has its Russian")
RU = open(os.path.join(ROOT, "js/lang/ru.js"), encoding="utf-8").read()
key = ("%s: the listen IP %s is an IPv6 address, and this server listens on IPv4 only. Use 0.0.0.0 (every IPv4 address), "
       "127.0.0.1 or one of this box's IPv4 addresses.")
check("[4] js/lang/ru.js carries the refusal, word for word", ('"%s":' % key) in RU and key in SRC.replace('"\n                          "', ""))

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS")
