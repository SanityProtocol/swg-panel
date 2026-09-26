#!/usr/bin/env python3
"""Self-test — an interface's NAT/forward rules converge to ONE copy, and a Docker node's uninstall takes them with it.

Two leaks, one class (1.8.8 qualification, round 4):
  · the installers wrote an interface's hooks as a plain `-A` up and one `-D` down — convert.sh's import_bare_conf (every
    Docker → bare-metal convert), install-node.sh's reconstruct_live_orphans and both installers' apply_specs. e937f8d
    made the AGENT's hooks reap-then-add; these kept the old form, so after a Docker → bare convert every interface
    carried two MASQUERADE and two FORWARD copies, and an uninstall later left one of each behind. They now write
    lib/common.sh's nat_hook_up / nat_hook_down — the agent's text, byte for byte.
  · a Docker node runs with host networking, so its hooks and node-entrypoint's NAT write the HOST's tables, and removing
    the container ran no PostDown: every uninstall left them (one box: 8 MASQUERADE and 6 FORWARD accepts for interfaces
    long gone). rm_docker_node now reaps each of its interfaces' rules (reap_iface_rules, uninstall.sh).

  [1] the shell hooks ARE the agent's hooks: nat_hook_up / nat_hook_down == swg-agent's _ipt_set / _ipt_reap text
  [2] run through a model of iptables: two bring-ups with no tear-down between them leave ONE copy of each rule
      (the old form left two), and the down removes them all, however many a pile held
  [3] import_bare_conf (the convert) writes exactly those hooks into the conf it imports
  [4] reap_iface_rules: every FORWARD rule naming the interface (hook pair, tagged ACL, jump) and its subnet's
      MASQUERADE go, in any number of copies; another interface's rules, another subnet's and Docker's own stay
  [5] rm_docker_node reads each interface's subnet out of the node's confs and reaps each one's rules, network form

Run: python3 tests/nat_hooks_selftest.py        (0 = pass)
     --plant <hooks|reap|call>   plant one old behaviour → RED (exit 0 when caught);  --perturb plants all three
"""
import importlib.machinery, importlib.util, os, re, shlex, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
C = open(os.path.join(ROOT, "lib", "common.sh"), encoding="utf-8").read()
V = open(os.path.join(ROOT, "convert.sh"), encoding="utf-8").read()
U = open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()
ALL = ("hooks", "reap", "call")
PLANTS = set(ALL) if "--perturb" in sys.argv else ({sys.argv[sys.argv.index("--plant") + 1]} if "--plant" in sys.argv else set())

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

if "hooks" in PLANTS:   # the installers' shipped hooks: a plain -A up, one -D down
    a = C.index("nat_hook_up(){"); b = C.index("\n# installed_sum <path…>", a)
    C = C[:a] + ("nat_hook_up(){ printf 'sysctl -q -w net.ipv4.ip_forward=1; iptables -t nat -A POSTROUTING -s %s -o %s -j MASQUERADE; "
                 "iptables -A FORWARD -i %%i -o %s -j ACCEPT; iptables -A FORWARD -i %s -o %%i -m state --state RELATED,ESTABLISHED -j ACCEPT' "
                 "\"$1\" \"$2\" \"$2\" \"$2\"; }\n"
                 "nat_hook_down(){ printf 'iptables -t nat -D POSTROUTING -s %s -o %s -j MASQUERADE; iptables -D FORWARD -i %%i -o %s -j ACCEPT; "
                 "iptables -D FORWARD -i %s -o %%i -m state --state RELATED,ESTABLISHED -j ACCEPT' \"$1\" \"$2\" \"$2\" \"$2\"; }\n") + C[b:]
if "reap" in PLANTS:
    U = plant(U, 'reap_iface_rules(){ local n="$1" s="${2:-}" l _s\n', 'reap_iface_rules(){ return 0\n')
if "call" in PLANTS:
    a = U.index("  # …and their rules (see reap_iface_rules)"); b = U.index("  done\n", a) + len("  done\n")
    U = U[:a] + U[b:]

def fn(src, name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot extract " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

HOOKS = "".join(fn(C, n) for n in ("_ipt_reap_sh", "_ipt_set_sh", "nat_hook_up", "nat_hook_down"))
T = tempfile.mkdtemp(prefix="nathooks-")
STUB = os.path.join(T, "bin"); os.makedirs(STUB)
STATE = os.path.join(T, "rules")
# a model of iptables: -t, -A/-D/-S/-N; rules kept per table as argument lists; -D removes ONE copy or fails
open(os.path.join(STUB, "iptables"), "w").write('''#!/usr/bin/env python3
import json, os, shlex, sys
p = os.environ["IPT_STATE"]; st = json.load(open(p)) if os.path.exists(p) else {}
a = sys.argv[1:]; t = "filter"
if a[:1] == ["-t"]:
    t, a = a[1], a[2:]
rules = st.setdefault(t, [])
op = a[0] if a else ""
def show(r):
    out = []; i = 0
    while i < len(r):
        out.append(r[i])
        if r[i] == "--comment" and i + 1 < len(r):
            out.append('"%s"' % r[i + 1]); i += 1
        i += 1
    return " ".join(out)
if op == "-A":
    rules.append(a[1:])
elif op == "-D":
    if a[1:] in rules:
        rules.remove(a[1:])
    else:
        sys.exit(1)
elif op == "-S":
    ch = a[1] if len(a) > 1 else None
    for r in rules:
        if ch is None or r[0] == ch:
            print("-A " + show(r))
    sys.exit(0)
json.dump(st, open(p, "w"))
''')
os.chmod(os.path.join(STUB, "iptables"), 0o755)
open(os.path.join(STUB, "sysctl"), "w").write("#!/bin/bash\nexit 0\n"); os.chmod(os.path.join(STUB, "sysctl"), 0o755)
ENV = dict(os.environ, PATH=STUB + ":" + os.environ["PATH"], IPT_STATE=STATE)

def sh(script):
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=ENV)
    return r.stdout + r.stderr
def rules():
    return sh("iptables -S; iptables -t nat -S").splitlines()
def reset(lines=()):
    if os.path.exists(STATE):
        os.remove(STATE)
    for l in lines:
        sh("iptables " + l)

print("[1] the installers' hooks are the agent's")
ld = importlib.machinery.SourceFileLoader("ag_nat", os.path.join(ROOT, "swg-agent"))
AG = importlib.util.module_from_spec(importlib.util.spec_from_loader("ag_nat", ld))
try:
    ld.exec_module(AG)
except SystemExit:
    pass
same = True
for net, wan in (("10.8.0.0/24", "ens3"), ("10.255.0.4/31", "eth0"), ("192.168.50.0/23", "enp1s0")):
    up = (f"sysctl -q -w net.ipv4.ip_forward=1 || true; "
          f"{AG._ipt_set('-t nat', f'POSTROUTING -s {net} -o {wan} -j MASQUERADE')}; "
          f"{AG._ipt_set('', f'FORWARD -i %i -o {wan} -j ACCEPT')}; "
          f"{AG._ipt_set('', f'FORWARD -i {wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT')}")
    down = (f"{AG._ipt_reap('-t nat', f'POSTROUTING -s {net} -o {wan} -j MASQUERADE')}; "
            f"{AG._ipt_reap('', f'FORWARD -i %i -o {wan} -j ACCEPT')}; "
            f"{AG._ipt_reap('', f'FORWARD -i {wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT')}; true")
    su = sh(HOOKS + 'nat_hook_up "%s" "%s"' % (net, wan)); sd = sh(HOOKS + 'nat_hook_down "%s" "%s"' % (net, wan))
    same = same and su == up and sd == down
check("[1] nat_hook_up / nat_hook_down print exactly swg-agent's PostUp / PostDown", same)

print("\n[2] through a model of iptables")
up = sh(HOOKS + "nat_hook_up 10.64.1.0/24 ens3").replace("%i", "wg0")
down = sh(HOOKS + "nat_hook_down 10.64.1.0/24 ens3").replace("%i", "wg0")
reset(); sh(up); sh(up)
rs = rules()
check("[2] two bring-ups with no tear-down between them: ONE copy of each of the three rules",
      len(rs) == 3 and len(set(rs)) == 3, rs)
reset(["-t nat -A POSTROUTING -s 10.64.1.0/24 -o ens3 -j MASQUERADE"] * 3 + ["-A FORWARD -i wg0 -o ens3 -j ACCEPT"] * 2)
sh(up)
check("[2] a bring-up over a pile an older install left converges it to one copy each", len(rules()) == 3, rules())
sh(down)
check("[2] the tear-down removes every copy", rules() == [], rules())

print("\n[3] the convert's import writes those hooks")
src = os.path.join(T, "wg0.conf"); dst = os.path.join(T, "wg0.out.conf")
open(src, "w").write("#swg:cmd wg\n[Interface]\nAddress = 10.64.1.1/24\nListenPort = 51820\nPrivateKey = K=\nPostUp = old\nPostDown = old\n")
out = sh(HOOKS + "detect_wan(){ echo ens3; }\n" + fn(V, "import_bare_conf") + 'import_bare_conf "%s" "%s"' % (src, dst))
conf = open(dst).read() if os.path.exists(dst) else ""
exp_up = sh(HOOKS + "nat_hook_up 10.64.1.0/24 ens3"); exp_down = sh(HOOKS + "nat_hook_down 10.64.1.0/24 ens3")
check("[3] PostUp / PostDown in the imported conf are the reap-then-add hooks (the old ones dropped)",
      ("PostUp = " + exp_up + "\n") in conf and ("PostDown = " + exp_down + "\n") in conf and "PostUp = old" not in conf, conf or out)

print("\n[4] reap_iface_rules")
REAP = fn(U, "reap_iface_rules")
seed = (["-A FORWARD -i wg0 -o ens3 -j ACCEPT"] * 2 + ["-A FORWARD -i ens3 -o wg0 -m state --state RELATED,ESTABLISHED -j ACCEPT"] * 2
        + ['-A FORWARD -o wg0 -m comment --comment swg-egress-acl:wg0 -j ACCEPT', "-A FORWARD -i wg0 -m comment --comment swg-egress-acl:wg0 -j SWG_FWD_IN"]
        + ["-t nat -A POSTROUTING -s 10.64.1.0/24 -o ens3 -j MASQUERADE"] * 2
        + ["-A FORWARD -i awg9 -o ens3 -j ACCEPT", "-t nat -A POSTROUTING -s 10.99.0.0/24 -o ens3 -j MASQUERADE",
           "-t nat -A POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE", "-A FORWARD -i wg01 -o ens3 -j ACCEPT"])
reset(seed)
sh("DRYRUN=false\nrun(){ \"$@\"; }\n" + REAP + "reap_iface_rules wg0 10.64.1.0/24")
rs = rules()
check("[4] every FORWARD rule naming wg0 is gone — hook pair, tagged ACL and jump, every copy",
      not [r for r in rs if re.search(r"-[io] wg0( |$)", r)], rs)
check("[4] …and its subnet's MASQUERADE, every copy", not [r for r in rs if "10.64.1.0/24" in r], rs)
check("[4] another interface's rules (awg9, and wg01 whose name only starts the same), another subnet's and Docker's stay",
      sorted(rs) == sorted(["-A FORWARD -i awg9 -o ens3 -j ACCEPT", "-A FORWARD -i wg01 -o ens3 -j ACCEPT",
                            "-A POSTROUTING -s 10.99.0.0/24 -o ens3 -j MASQUERADE",
                            "-A POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE"]), rs)

print("\n[5] rm_docker_node reaps its interfaces' rules")
a = U.index("  # …and each one's subnet, for the MASQUERADE its bring-up added")
b = U.index("\n", U.index('  [ -n "$_nets" ] || _nets=', a)) + 1
CAP = U[a:b]
LOOP = ""
if "call" not in PLANTS:
    a2 = U.index("  # …and their rules (see reap_iface_rules)"); LOOP = U[a2:U.index("  done\n", a2) + len("  done\n")]
open(os.path.join(STUB, "docker"), "w").write("#!/bin/bash\nprintf 'wg0 10.64.1.1/24\\nawg0 10.64.2.1/24\\n'\n")
os.chmod(os.path.join(STUB, "docker"), 0o755)
reset(["-A FORWARD -i wg0 -o ens3 -j ACCEPT", "-A FORWARD -i ens3 -o awg0 -m state --state RELATED,ESTABLISHED -j ACCEPT",
       "-t nat -A POSTROUTING -s 10.64.1.0/24 -o ens3 -j MASQUERADE", "-t nat -A POSTROUTING -s 10.64.2.0/24 -o ens3 -j MASQUERADE",
       "-t nat -A POSTROUTING -s 10.99.0.0/24 -o ens3 -j MASQUERADE"])
out = sh("DRYRUN=false; DOCKER_DIR=%s\nrun(){ \"$@\"; }\n%sf(){ local _ifn='wg0 awg0' _n\n%s%s}\nf\n" % (T, REAP, CAP, LOOP))
rs = rules()
check("[5] both interfaces' rules and both subnets' MASQUERADE are gone (10.64.1.1/24 read as 10.64.1.0/24)",
      rs == ["-A POSTROUTING -s 10.99.0.0/24 -o ens3 -j MASQUERADE"], (rs, out))

print()
if PLANTS:
    print("PERTURBED (%s): %s" % (",".join(sorted(PLANTS)), "RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate does not see the defect"))
    sys.exit(0 if FAILS else 2)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
