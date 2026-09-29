#!/usr/bin/env python3
"""Self-test — Force-DNS's redirect leaves with the node whose dnsmasq it points at, and the sweep sees every swg- rule.

1.8.8 qualification, round 6: (a) uninstalling a node while KEEPING its interfaces kept swg-noded's `swg-smartdns` DNATs
(every client's :53 → the node's dnsmasq on 127.0.0.1:5354) "so they keep working" — but that dnsmasq is the node's and
was gone: every client on a kept Force-DNS interface lost DNS while traffic by address still worked (q1). (b) The full
sweep matched `--comment "swg-` — and iptables prints a comment with nothing but letters, digits, `-` and `_` UNQUOTED
(`--comment swg-smartdns`), so the sweep never saw these rules: a Docker box kept six through a full purge (q3).

The rules below are iptables 1.8.10's own `-S` lines, as the guests print them; a stateful stub serves them and applies
each `-D`. The uninstaller's definitions are lifted AS SHIPPED (paths rooted in a temp dir, host tools stubbed), and
rm_node / rm_docker_node / rm_node_netobjects / _rm_egress_rules run for real.

  [1] the bare node removed, its interfaces KEPT (no sweep) → no swg-smartdns / swg-smartdns-net rule left; the kept
      interfaces' own NAT and an operator's own rule untouched
  [2] the Docker node removed → the same
  [3] …but not while the OTHER method's node is still on the box (its dnsmasq still answers those clients)
  [4] the full sweep takes the unquoted swg-smartdns rules as well as the quoted swg-egress ones; an operator's rule stays
  [5] _rm_egress_rules for wdtt1 takes wdtt1's rules (quoted, and unquoted if iptables printed them so) — never wdtt11's

Run: python3 tests/uninstall_forcedns_selftest.py     (0 = pass)
     --perturb-quote   the quote-only matches put back (sweep + _rm_egress_rules) → RED on [4][5]
     --perturb-kept    the redirect left for the sweep again (the round-6 shape) → RED on [1][2]
     --perturb-other   removed even while the other method's node is still here → RED on [3]
"""
import json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
ARGS = set(sys.argv[1:])
PERTURBED = any(a.startswith("--perturb") for a in ARGS)
U = open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[-900:]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(a, b, n=1):
    global U
    assert U.count(a) == n, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    U = U.replace(a, b)

if "--perturb-quote" in ARGS:
    plant("""grep -E -- '--comment "?swg-' | while""", """grep -F -- '--comment "swg-' | while""")
    plant('''$(iptables -t "$1" -S "$2" 2>/dev/null | grep -E -- "$(_ipt_comment_re "$3")")''',
          '''$(iptables -t "$1" -S "$2" 2>/dev/null | grep -F -- "--comment \\"$3\\"")''')
if "--perturb-kept" in ARGS:
    plant("  docker_running swg-node || rm_smartdns_redirect   # its dnsmasq just went with it — see rm_smartdns_redirect\n", "")
    plant('  [ -f "$SD/swg-noded.service" ] || rm_smartdns_redirect   # its dnsmasq was in the container (host networking: the DNATs are the host\'s)\n', "")
if "--perturb-other" in ARGS:
    plant("  docker_running swg-node || rm_smartdns_redirect", "  rm_smartdns_redirect")
    plant('  [ -f "$SD/swg-noded.service" ] || rm_smartdns_redirect   # its dnsmasq was in the container', "  rm_smartdns_redirect   # its dnsmasq was in the container")

DNAT = "-A PREROUTING -s %s -p %s -m %s --dport 53 -m comment --comment swg-smartdns -j DNAT --to-destination 127.0.0.1:5354"
RULES = {
    "nat": ["-A PREROUTING -m addrtype --dst-type LOCAL -j DOCKER",
            "-A PREROUTING -s 10.71.1.0/24 -d 192.168.10.0/24 -p udp -m udp --dport 53 -m comment --comment swg-smartdns-net -j RETURN",
            DNAT % ("10.71.1.0/24", "tcp", "tcp"), DNAT % ("10.71.1.0/24", "udp", "udp"),
            DNAT % ("10.76.0.0/24", "tcp", "tcp"), DNAT % ("10.76.0.0/24", "udp", "udp"),
            "-A PREROUTING -p tcp -m tcp --dport 8080 -m comment --comment ops-redirect -j REDIRECT --to-ports 80",
            "-A POSTROUTING -s 10.71.1.0/24 -o ens3 -j MASQUERADE",
            "-A POSTROUTING -s 10.76.0.0/24 -o ens3 -j MASQUERADE",
            '-A POSTROUTING -s 10.66.1.0/24 -m comment --comment "swg-egress:wdtt1" -j MASQUERADE',
            '-A POSTROUTING -s 10.66.2.0/24 -m comment --comment "swg-egress:wdtt11" -j MASQUERADE',
            "-A POSTROUTING -s 10.66.3.0/24 -m comment --comment swg-egress-unquoted-probe -j MASQUERADE"],
    "filter": ['-A FORWARD -o wdtt1 -m comment --comment "swg-egress-acl:wdtt1" -j ACCEPT',
               '-A FORWARD -o wdtt11 -m comment --comment "swg-egress-acl:wdtt11" -j ACCEPT',
               "-A FORWARD -i awg0 -j ACCEPT"],
    "mangle": []}

IPT = r'''#!/usr/bin/env python3
import json, os, shlex, sys
box = os.environ["BOX"]; st = os.path.join(box, "ipt.json")
open(os.path.join(box, "calls.log"), "a").write("iptables\t" + " ".join(sys.argv[1:]) + "\n")
rules = json.load(open(st)); a = sys.argv[1:]; t = "filter"
if a[:1] == ["-t"]:
    t, a = a[1], a[2:]
if a[:1] == ["-S"]:
    for r in rules.get(t, []):
        if len(a) < 2 or r.split()[1] == a[1]:
            print(r)
    sys.exit(0)
if a[:1] == ["-D"]:
    want = ["-A"] + a[1:]
    for i, r in enumerate(rules.get(t, [])):
        if shlex.split(r) == want:
            del rules[t][i]; json.dump(rules, open(st, "w")); sys.exit(0)
    sys.exit(1)
sys.exit(0)
'''
STUB = r'''#!/bin/bash
printf '%s\t%s\n' "$(basename "$0")" "$*" >> "$BOX/calls.log"
case "$(basename "$0")" in
  docker) case "$1" in ps) cat "$BOX/fx.docker" 2>/dev/null;; inspect) exit 1;; esac ;;
  systemctl) case "$1" in is-enabled|is-active) exit 1;; esac ;;
  ip) case "$*" in "link show "*) exit 1;; esac ;;
esac
exit 0
'''
T = tempfile.mkdtemp(prefix="fdns-")
CUT = U.index('N=${#CLABEL[@]}')

def rooted(text, box):
    for p in ("/opt/", "/etc/", "/var/", "/usr/local/bin/", "/srv/", "/root/"):
        text = text.replace(p, box + p)
    return text

def world(name, bare=False, docker=False):
    box = os.path.join(T, name); os.makedirs(os.path.join(box, "stub")); os.makedirs(os.path.join(box, "home"))
    json.dump(RULES, open(os.path.join(box, "ipt.json"), "w"))
    open(os.path.join(box, "stub/iptables"), "w").write(IPT); os.chmod(os.path.join(box, "stub/iptables"), 0o755)
    for t in ("docker", "ip", "nft", "ipset", "systemctl", "awg-quick", "wg-quick", "userdel", "groupdel", "dpkg", "ufw", "nginx"):
        open(os.path.join(box, "stub", t), "w").write(STUB); os.chmod(os.path.join(box, "stub", t), 0o755)
    def w(rel, text):
        p = os.path.join(box, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(text)
    if bare:
        w("etc/systemd/system/swg-noded.service", "[Unit]\n"); w("opt/swg-noded/swg-noded", "x")
        w("etc/swg-agent/config.json", '{"panel": {"url": "http://127.0.0.1:8088", "token": "t0123456789", "verify": false},'
                                       ' "interfaces": {"awg0": {"conf": "/etc/amnezia/amneziawg/awg0.conf"}}}')
        w("etc/amnezia/amneziawg/awg0.conf", "[Interface]\nAddress = 10.71.1.1/24\n")
    if docker:
        w("opt/swg-panel-docker/.env", "PANEL_URL=http://127.0.0.1:8088\nNODE_TOKEN=t0123456789\nTLS_VERIFY=no\n")
        w("opt/swg-panel-docker/data/node-confs/awg0.conf", "[Interface]\nAddress = 10.76.0.1/24\n")
    open(os.path.join(box, "fx.docker"), "w").write("swg-node\n" if docker else "")
    return box

def run(box, body, docker_after=None):
    defs = rooted(U[:CUT], box).replace('[ "$(id -u)" = 0 ] || $DRYRUN || die', 'true || $DRYRUN || die')
    if docker_after is not None:   # what `docker ps` answers once the body has run (a container removed in it)
        body = body.replace("@@DOCKER_GONE@@", "printf '%s' '%s' > \"$BOX/fx.docker\"" % ("%s", docker_after))
    open(os.path.join(box, "run.sh"), "w").write(defs + "\n" + body + "\n")
    env = dict(os.environ, BOX=box, HOME=os.path.join(box, "home"), PATH=os.path.join(box, "stub") + ":" + os.environ["PATH"])
    r = subprocess.run(["bash", os.path.join(box, "run.sh")], env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       timeout=300, start_new_session=True)
    return r.stdout + r.stderr, json.load(open(os.path.join(box, "ipt.json")))

def smartdns(rules):
    return [r for r in rules["nat"] if re.search(r"--comment \"?swg-smartdns(-net)?\"?( |$)", r)]
OPS = "-A PREROUTING -p tcp -m tcp --dport 8080 -m comment --comment ops-redirect -j REDIRECT --to-ports 80"

print("[1] the bare node removed, its interfaces kept (the sweep never runs)")
box = world("bare-kept", bare=True)
out, rules = run(box, "rm_node\necho SWEEP_ARMED=$NEED_NETOBJ_SWEEP")
check("[1] no swg-smartdns / swg-smartdns-net rule left — the kept interface's clients resolve through their own DNS again",
      smartdns(rules) == [], smartdns(rules) or out[-600:])
check("[1] …the kept interfaces' own NAT and an operator's rule untouched, and the sweep still only armed (not run)",
      OPS in rules["nat"] and "-A POSTROUTING -s 10.71.1.0/24 -o ens3 -j MASQUERADE" in rules["nat"]
      and "SWEEP_ARMED=true" in out and any("swg-egress" in r for r in rules["nat"]), out[-600:])
check("[1] …and it says so", "removed Force-DNS's redirect" in out, out[-600:])

print("\n[2] the Docker node removed")
box = world("docker-kept", docker=True)
out, rules = run(box, "@@DOCKER_GONE@@\nrm_docker_node", docker_after="")
check("[2] no swg-smartdns / swg-smartdns-net rule left (the container took its dnsmasq with it)", smartdns(rules) == [],
      smartdns(rules) or out[-600:])
check("[2] …an operator's rule untouched", OPS in rules["nat"], rules["nat"])

print("\n[3] not while the other method's node is still on the box")
box = world("bare-beside-docker", bare=True, docker=True)
out, rules = run(box, "rm_node")
check("[3] the bare node removed beside a running Docker node → its redirect stays (that node's dnsmasq answers it)",
      len(smartdns(rules)) == 5, smartdns(rules))
box = world("docker-beside-bare", bare=True, docker=True)
out, rules = run(box, "@@DOCKER_GONE@@\nrm_docker_node", docker_after="")
check("[3] the Docker node removed beside a bare node → the same", len(smartdns(rules)) == 5, smartdns(rules))

print("\n[4] the full sweep")
box = world("sweep")
out, rules = run(box, "rm_node_netobjects")
check("[4] the unquoted swg-smartdns / swg-smartdns-net rules go", smartdns(rules) == [], smartdns(rules))
check("[4] …the quoted swg-egress ones and an unquoted swg- one go too",
      not any("swg-" in r for r in rules["nat"] + rules["filter"]), rules)
check("[4] …an operator's rule and the untagged NAT stay", OPS in rules["nat"] and "-A FORWARD -i awg0 -j ACCEPT" in rules["filter"], rules)

print("\n[5] _rm_egress_rules")
box = world("egress")
r5 = json.load(open(os.path.join(box, "ipt.json")))
r5["nat"].append("-A POSTROUTING -s 10.66.9.0/24 -m comment --comment swg-egress:wdtt1 -j MASQUERADE")   # printed unquoted
json.dump(r5, open(os.path.join(box, "ipt.json"), "w"))
out, rules = run(box, "_rm_egress_rules wdtt1")
left = [r for r in rules["nat"] + rules["filter"] if "wdtt1" in r]
check("[5] wdtt1's rules go, quoted and unquoted; wdtt11's stay",
      not any(re.search(r"swg-egress(-acl)?:wdtt1\"?( |$)", r) for r in left)
      and any("wdtt11" in r for r in rules["nat"]) and any("wdtt11" in r for r in rules["filter"]), left)

shutil.rmtree(T, ignore_errors=True)
print()
if PERTURBED:
    print("PERTURBED: %s" % ("RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate does not see it"))
    sys.exit(0 if FAILS else 2)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
