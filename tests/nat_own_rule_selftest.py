#!/usr/bin/env python3
"""Self-test — ONE INTERFACE'S TEAR-DOWN NEVER TAKES ANOTHER INTERFACE'S NAT RULE.

1.8.8 qualification, round 7 (a node's transfer home, bare q1/q2): the mesh link between the two came back under a new
name on the SAME /31 (only mesh_gen renames it), and afterwards neither end had the link's MASQUERADE — for good; a
restart of the link put it back. The rule was `-s <net> -o <wan> -j MASQUERADE` and nothing else, written by every
interface's PostUp (swg-agent create-iface, lib/common.sh nat_hook_up for the installers and the convert) and by the
Docker node's entrypoint once per SUBNET. Two interfaces on one subnet therefore wrote ONE text; swg-noded's sync
creates before it deletes (create_ifaces, then delete_ifaces), so the new link's PostUp added the rule and the old
link's PostDown — which reaps every copy of that text — took it. Every rule is now named after its interface
(`-m comment --comment swg-nat:<iface>`, %i in the hooks), so a down takes its own and nothing else, in any order.
1.8.7 carries the same untagged hooks, the same create-then-delete sync and the same first-free /31 allocator.

  [1] two interfaces on one subnet, through a model of iptables, with the text swg-agent writes AND the text the
      installers write: the new one up then the old one down (the homecoming), the other order, a restart of either
      while the other is up, a rename — each keeps exactly its own MASQUERADE and FORWARD pair
  [2] the migration (swg-agent tag-nat-hooks): a .conf with the 1.8.7 hooks gets exactly create-iface's text, one with
      the plain pre-reap `-A`/`-D` hooks is tagged in place, every other line byte for byte; an adopted .conf
      (#swg:onboarded) and one without a MASQUERADE are not touched; a second run changes nothing. Live: the untagged
      copies go and ONE tagged copy stays — also where the homecoming already took the rule (the update heals it);
      a device that is down is left alone
  [3] swg-noded runs it once per start, right after backfill_cmd_markers, for every managed interface whose hooks still
      carry the UNTAGGED MASQUERADE — never for a tagged one (a start costs nothing once all have moved), never for an
      adopted one — and says so, one line per interface moved
  [4] the Docker entrypoint: one tagged rule per INTERFACE (was one untagged per subnet), an older start's untagged
      copy removed, a second start adds nothing, two interfaces on one subnet each keep theirs through the other's down
  [5] the agent's delete (_reap_egress_rules): a tagged .conf reaps its own rule only — a twin's stays; a legacy .conf
      still reaps its untagged copies, as before
  [6] swg-noded's baseline still reads the tagged rule as the interface's own NAT (not "swg-egress:") and defers to it:
      no second MASQUERADE appears for any interface
  [7] (round 8) the agent's delete takes the rule NAMED after the interface even when its .conf has no hooks — a Docker
      node's (install-docker.sh strips them; the entrypoint adds the rule): every copy, quoted or not, and only its own
      (swg-nat:wg0 is not swg-nat:wg01, a twin's stays)
  [8] swg-noded's first start removes a rule whose interface is GONE (not managed, no device, no .conf) — q4 kept
      `swg-nat:swg_51bc7bc8` after its link was deleted — and never one whose interface exists in any form: managed and
      down, a device that is up, a .conf on disk; nor an untagged rule or anybody else's; nor when `ip` cannot say

Run: python3 tests/nat_own_rule_selftest.py      (0 = pass)
     --plant <untag|noop|nocall|entry|delreap|every|tagreap|orphan|greedy>   one shipped behaviour back → RED (exit 0 when
             caught); every: noded asks about every interface at every start (the first version); tagreap: the delete
             reaps only what the hooks name (round 8's leftover); orphan: no start-time sweep; greedy: the sweep does not
             ask whether the interface still exists
     --perturb                                         all of them at once
"""
import importlib.machinery, importlib.util, inspect, io, json, os, re, contextlib, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
ALL = ("untag", "noop", "nocall", "entry", "delreap", "every", "tagreap", "orphan", "greedy")
PLANTS = set(ALL) if "--perturb" in sys.argv else ({sys.argv[sys.argv.index("--plant") + 1]} if "--plant" in sys.argv else set())
assert PLANTS <= set(ALL), "unknown plant: %s" % (PLANTS - set(ALL))

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:700]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b, count=1):
    assert src.count(a) == count, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

AGENT_SRC = open(os.path.join(ROOT, "swg-agent"), encoding="utf-8").read()
NODED_SRC = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
C = open(os.path.join(ROOT, "lib", "common.sh"), encoding="utf-8").read()
E = open(os.path.join(ROOT, "docker", "node-entrypoint.sh"), encoding="utf-8").read()

if "untag" in PLANTS:     # the 1.8.7 text: one rule per subnet, whoever wrote it
    AGENT_SRC = plant(AGENT_SRC, 'return f"POSTROUTING -s {net} -o {wan} -m comment --comment {NAT_TAG}{who} -j MASQUERADE"',
                      'return f"POSTROUTING -s {net} -o {wan} -j MASQUERADE"')
    C = plant(C, "-m comment --comment swg-nat:%i ", "", 2)
if "noop" in PLANTS:      # no migration: an existing interface keeps its 1.8.7 hooks
    AGENT_SRC = plant(AGENT_SRC, 'this once per start for each managed interface, which is how boxes installed before the tag move over."""\n',
                      'this once per start for each managed interface, which is how boxes installed before the tag move over."""\n'
                      '    return {"iface": req["iface"], "changed": False, "live": False}\n')
if "nocall" in PLANTS:    # the op exists, nobody runs it
    NODED_SRC = plant(NODED_SRC, "        tag_nat_hooks(node_cfg, agent, sudo)   # each interface's OWN MASQUERADE — see tag_nat_hooks\n",
                      "        pass\n")
if "every" in PLANTS:     # the first version: a tagged .conf asked about again at every start (a cost per interface)
    NODED_SRC = plant(NODED_SRC, 'if not re.search(r"(?im)^\\s*Post(?:Up|Down)\\s*=.*\\bPOSTROUTING -s \\S+ -o \\S+ -j MASQUERADE", text):',
                      'if not re.search(r"(?im)^\\s*Post(?:Up|Down)\\s*=.*\\bPOSTROUTING -s \\S+ -o \\S+ .*-j MASQUERADE", text):')
if "tagreap" in PLANTS:   # the delete reaps only what the hook text names
    AGENT_SRC = plant(AGENT_SRC, "    _reap_own_nat(iface)                           # …and the rule named after it, which a hookless .conf does not name\n", "")
if "orphan" in PLANTS:    # no start-time sweep
    NODED_SRC = plant(NODED_SRC, "        reap_orphan_nat(node_cfg)              # …and none for an interface that is gone — see reap_orphan_nat\n",
                      "        pass\n")
if "greedy" in PLANTS:    # the sweep takes every swg-nat rule of a name it does not manage
    NODED_SRC = plant(NODED_SRC, '        if any(os.path.exists(os.path.join(d, name + ".conf")) for d in _NAT_CONF_DIRS):\n            continue\n', "")
    NODED_SRC = plant(NODED_SRC, '        if r.returncode == 0 or "does not exist" not in (r.stderr or ""):\n', "        if False:\n")
if "entry" in PLANTS:     # the entrypoint's shipped block: one untagged rule per subnet
    a = E.index("  # ITS OWN MASQUERADE, named after it"); b = E.index("\ndone\n", a)
    E = E[:a] + '''  case " $NATTED " in *" $SUBNET "*) : ;; *)
    if iptables -t nat -C POSTROUTING -s "$SUBNET" -o "$WAN" -j MASQUERADE 2>/dev/null; then :; else
      iptables -t nat -A POSTROUTING -s "$SUBNET" -o "$WAN" -j MASQUERADE \\
        && log "NAT: masquerading $SUBNET out $WAN ($IFACE)" \\
        || log "WARNING: could not add MASQUERADE for $SUBNET (need NET_ADMIN) — clients may have no internet"
    fi
    NATTED="$NATTED $SUBNET" ;;
  esac''' + E[b:]
if "delreap" in PLANTS:   # the delete's shipped reap: the untagged text only, whatever the conf says
    AGENT_SRC = plant(AGENT_SRC, '_EGRESS_MASQ_RE = re.compile(r"-s (\\S+) -o (\\S+) (-m comment --comment \\S+ )?-j MASQUERADE")',
                      '_EGRESS_MASQ_RE = re.compile(r"-s (\\S+) -o (\\S+) -j MASQUERADE")')
    AGENT_SRC = plant(AGENT_SRC, '    masq = (["-m", "comment", "--comment", NAT_TAG + iface] if m.group(3) else [])\n', "    masq = []\n")


def load(src, name):
    tmp = os.path.join(tempfile.mkdtemp(prefix="natown-"), name + ".py")
    open(tmp, "w", encoding="utf-8").write(src)
    ld = importlib.machinery.SourceFileLoader(name, tmp)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    try:
        ld.exec_module(mod)
    except SystemExit:
        pass
    return mod


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


AG = load(AGENT_SRC, "ag_natown")
ND = load(NODED_SRC, "nd_natown")
HOOKS = "".join(fn(C, n) for n in ("_ipt_reap_sh", "_ipt_set_sh", "nat_hook_up", "nat_hook_down"))

T = tempfile.mkdtemp(prefix="natown-")
STUB = os.path.join(T, "bin"); os.makedirs(STUB)
STATE = os.path.join(T, "rules")
# a model of iptables: -t, -A/-I/-D/-C/-S; rules kept per table as argument lists; -D removes ONE copy or fails
open(os.path.join(STUB, "iptables"), "w").write('''#!/usr/bin/env python3
import json, os, sys
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
elif op == "-I":
    rules.insert(0, a[1:])
elif op == "-D":
    if a[1:] in rules:
        rules.remove(a[1:])
    else:
        sys.exit(1)
elif op == "-C":
    sys.exit(0 if a[1:] in rules else 1)
elif op == "-S":
    ch = a[1] if len(a) > 1 else None
    for r in rules:
        if ch is None or r[0] == ch:
            print("-A " + show(r))
    sys.exit(0)
json.dump(st, open(p, "w"))
''')
# `ip link show <dev>`: a device is up when LIVE_IFACES names it
open(os.path.join(STUB, "ip"), "w").write('#!/bin/bash\n[ "$1 $2" = "link show" ] || exit 0\n'
                                          '[ -n "${IP_BROKEN:-}" ] && { echo "ip: cannot open netlink socket" >&2; exit 2; }\n'
                                          'case " ${LIVE_IFACES:-} " in *" $3 "*) exit 0;; esac\n'
                                          'echo "Device \\"$3\\" does not exist." >&2; exit 1\n')
open(os.path.join(STUB, "sysctl"), "w").write("#!/bin/bash\nexit 0\n")
for f in ("iptables", "ip", "sysctl"):
    os.chmod(os.path.join(STUB, f), 0o755)
os.environ["PATH"] = STUB + ":" + os.environ["PATH"]      # the agent's own subprocess calls land in the model too
os.environ["IPT_STATE"] = STATE


def sh(script):
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return r.stdout + r.stderr
def rules(tbl=None):
    return sh("iptables -S; iptables -t nat -S").splitlines() if tbl is None else sh("iptables -t %s -S" % tbl).splitlines()
def nat():
    return [r for r in rules("nat") if "MASQUERADE" in r]
def reset(lines=()):
    if os.path.exists(STATE):
        os.remove(STATE)
    for l in lines:
        sh("iptables " + l)
def masq_of(ifc, net="10.255.0.0/31", wan="ens3"):
    return '-A POSTROUTING -s %s -o %s -m comment --comment "swg-nat:%s" -j MASQUERADE' % (net, wan, ifc)
UNTAGGED = "-A POSTROUTING -s 10.255.0.0/31 -o ens3 -j MASQUERADE"


def legacy_hooks(net, wan):
    """What 1.8.7 (and dev up to e5c02bd) wrote into a .conf: the untagged reap-then-add hooks."""
    up = (f"sysctl -q -w net.ipv4.ip_forward=1 || true; "
          f"{AG._ipt_set('-t nat', f'POSTROUTING -s {net} -o {wan} -j MASQUERADE')}; "
          f"{AG._ipt_set('', f'FORWARD -i %i -o {wan} -j ACCEPT')}; "
          f"{AG._ipt_set('', f'FORWARD -i {wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT')}")
    down = (f"{AG._ipt_reap('-t nat', f'POSTROUTING -s {net} -o {wan} -j MASQUERADE')}; "
            f"{AG._ipt_reap('', f'FORWARD -i %i -o {wan} -j ACCEPT')}; "
            f"{AG._ipt_reap('', f'FORWARD -i {wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT')}; true")
    return up, down


print("[1] two interfaces on one subnet — each keeps its own rule, whatever the order")
WRITERS = (("swg-agent (create-iface)", lambda net, wan: AG._nat_hooks(net, wan)),
           ("lib/common.sh (installers, convert)", lambda net, wan: (sh(HOOKS + 'nat_hook_up "%s" "%s"' % (net, wan)),
                                                                     sh(HOOKS + 'nat_hook_down "%s" "%s"' % (net, wan)))))
for label, writer in WRITERS:
    up, down = writer("10.255.0.0/31", "ens3")
    def U(i): sh(up.replace("%i", i))
    def D(i): sh(down.replace("%i", i))
    def fwd(i): return [r for r in rules("filter") if re.search(r"-[io] %s( |$)" % re.escape(i), r)]
    reset(); U("swg_old"); U("swg_new"); D("swg_old")
    check("[1] %s: the homecoming — new link up, THEN the old one down: the new link keeps its MASQUERADE" % label,
          nat() == [masq_of("swg_new")], nat())
    check("[1] %s: …and its FORWARD pair" % label, len(fwd("swg_new")) == 2 and not fwd("swg_old"), rules("filter"))
    D("swg_new")
    check("[1] %s: …and its own down leaves nothing behind" % label, nat() == [] and rules("filter") == [], rules())
    reset(); U("swg_old"); D("swg_old"); U("swg_new")
    check("[1] %s: the other order (old down first) — the new link has its rule" % label, nat() == [masq_of("swg_new")], nat())
    reset(); U("swg_a"); U("swg_b"); D("swg_b"); U("swg_b")
    check("[1] %s: a restart of one while the other is up: one rule each" % label,
          sorted(nat()) == sorted([masq_of("swg_a"), masq_of("swg_b")]), nat())
    D("swg_a"); U("swg_a")
    check("[1] %s: …the other's restart too" % label, sorted(nat()) == sorted([masq_of("swg_a"), masq_of("swg_b")]), nat())
    reset(); U("wg0"); U("wg1"); D("wg0")
    check("[1] %s: a rename done up-then-down (wg0 → wg1, one subnet): wg1 keeps it" % label, nat() == [masq_of("wg1")], nat())

print("\n[2] the migration: swg-agent tag-nat-hooks")
NET, WAN = "10.64.7.0/24", "ens3"
lup, ldown = legacy_hooks(NET, WAN)
nup, ndown = AG._nat_hooks(NET, WAN)
REST = ("[Interface]\nPrivateKey = cHJpdmF0ZS1rZXktc2VydmVyLXNlcnZlci1zZXJ2ZXI=\nAddress = 10.64.7.1/24\nListenPort = 51820\n"
        "%s\nJc = 4\n\n# name: phone\n[Peer]\nPublicKey = 5dYQ79ynisVEC8XyQgXamgfpZe38PN6KihtEV6kpGjk=\nAllowedIPs = 10.64.7.2/32\n")
def conf(name, text):
    p = os.path.join(T, name + ".conf"); open(p, "w").write(text); os.chmod(p, 0o600); return p
def op(ifc, path, live=False):
    os.environ["LIVE_IFACES"] = ifc if live else ""
    return AG.op_tag_nat_hooks({"interfaces": {ifc: {"conf": path, "cmd": ["awg"]}}}, {"iface": ifc})
p187 = conf("awg0", REST % ("PostUp = %s\nPostDown = %s" % (lup, ldown)))
reset()
r = op("awg0", p187)
got = open(p187).read()
check("[2] a .conf with the 1.8.7 hooks: PostUp / PostDown become exactly what create-iface writes",
      ("PostUp = %s\n" % nup) in got and ("PostDown = %s\n" % ndown) in got and r.get("changed") is True, (r, got))
check("[2] …every other line byte for byte, the mode kept (0600)",
      got.replace("PostUp = %s\nPostDown = %s" % (nup, ndown), "@") == (REST % "@")
      and oct(os.stat(p187).st_mode & 0o777) == "0o600", got)
r2 = op("awg0", p187)
check("[2] a second run changes nothing", r2.get("changed") is False and open(p187).read() == got, r2)
plain_up = "iptables -t nat -A POSTROUTING -s %s -o %s -j MASQUERADE; iptables -A FORWARD -i %%i -j ACCEPT" % (NET, WAN)
plain_down = "iptables -t nat -D POSTROUTING -s %s -o %s -j MASQUERADE; iptables -D FORWARD -i %%i -j ACCEPT" % (NET, WAN)
pplain = conf("wg3", REST % ("PostUp = %s\nPostDown = %s" % (plain_up, plain_down)))
op("wg3", pplain)
tag = "-m comment --comment swg-nat:%i -j MASQUERADE"
check("[2] the plain pre-reap hooks (-A up, one -D down): the MASQUERADE is tagged in place, the rest as it was",
      open(pplain).read() == REST % ("PostUp = %s\nPostDown = %s" % (plain_up.replace("-j MASQUERADE", tag),
                                                                       plain_down.replace("-j MASQUERADE", tag))), open(pplain).read())
onb_text = "#swg:onboarded\n" + REST % ("PostUp = %s\nPostDown = %s" % (lup, ldown))
ponb = conf("wg9", onb_text)
reset(["-t nat -A POSTROUTING -s %s -o %s -j MASQUERADE" % (NET, WAN)])
r = op("wg9", ponb, live=True)
check("[2] an ADOPTED .conf (#swg:onboarded) keeps its hooks and its live rule: its text is somebody else's",
      open(ponb).read() == onb_text and r.get("changed") is False and nat() == ["-A POSTROUTING -s %s -o %s -j MASQUERADE" % (NET, WAN)],
      (r, nat()))
pnone = conf("wg4", REST % "PostUp = sysctl -q -w net.ipv4.ip_forward=1\nPostDown = true")
before = open(pnone).read(); r = op("wg4", pnone)
check("[2] a .conf with no MASQUERADE is not touched", open(pnone).read() == before and r.get("changed") is False, r)
# live
LEG = "-t nat -A POSTROUTING -s %s -o %s -j MASQUERADE" % (NET, WAN)
TAGD = '-A POSTROUTING -s %s -o %s -m comment --comment "swg-nat:awg0" -j MASQUERADE' % (NET, WAN)
p187b = conf("awg0", REST % ("PostUp = %s\nPostDown = %s" % (lup, ldown)))
reset([LEG] * 3 + ["-A FORWARD -i awg0 -o ens3 -j ACCEPT"])
r = op("awg0", p187b, live=True)
check("[2] LIVE: the untagged copies go and exactly one tagged copy stays", nat() == [TAGD] and r.get("live") is True, (r, nat()))
check("[2] …the FORWARD pair is left as it was", rules("filter") == ["-A FORWARD -i awg0 -o ens3 -j ACCEPT"], rules("filter"))
op("awg0", p187b, live=True)
check("[2] …and a second run (the next start) leaves exactly that", nat() == [TAGD], nat())
p187c = conf("awg0", REST % ("PostUp = %s\nPostDown = %s" % (lup, ldown)))
reset()
op("awg0", p187c, live=True)
check("[2] LIVE, where the homecoming already took the rule: the migration puts it back, tagged", nat() == [TAGD], nat())
p187d = conf("awg0", REST % ("PostUp = %s\nPostDown = %s" % (lup, ldown)))
reset([LEG])
op("awg0", p187d, live=False)
check("[2] a device that is down: the .conf moves, the kernel is left alone (its next bring-up writes its own rule)",
      nat() == ["-A POSTROUTING -s %s -o %s -j MASQUERADE" % (NET, WAN)] and ("PostUp = %s\n" % nup) in open(p187d).read(), nat())

print("\n[3] swg-noded runs it once per start")
calls = []
def fake_agent(agent, sudo, payload):
    calls.append(payload)
    return {"ok": True, "op": payload.get("op"), "data": {"iface": payload.get("iface"), "changed": True, "live": True}}
ND.run_agent = fake_agent
cfg = {"interfaces": {"awg0": {"conf": conf("n-awg0", REST % ("PostUp = %s\nPostDown = %s" % (lup, ldown)))},
                      "swg_ab": {"conf": conf("n-swg_ab", REST % ("PostUp = %s\nPostDown = %s" % (nup, ndown)))},
                      "wg9": {"conf": conf("n-wg9", onb_text)},
                      "wg4": {"conf": conf("n-wg4", REST % "PostUp = true\nPostDown = true")},
                      "gone": {"conf": os.path.join(T, "missing.conf")}}}
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    ND.tag_nat_hooks(cfg, "/opt/swg-agent/swg-agent", True)
asked = sorted(c.get("iface") for c in calls)
check("[3] tag-nat-hooks is asked for the interface whose hooks carry the untagged MASQUERADE, and no other (not the "
      "tagged swg_ab, the adopted wg9, wg4 with none, the missing .conf)",
      asked == ["awg0"] and all(c.get("op") == "tag-nat-hooks" for c in calls), (asked, calls))
check("[3] …and one line per interface it moved", buf.getvalue().count("has its own MASQUERADE now (swg-nat:") == 1, buf.getvalue())
msrc = inspect.getsource(ND.main)
i_bf = msrc.find("backfill_cmd_markers(node_cfg)"); i_tn = msrc.find("tag_nat_hooks(node_cfg, agent, sudo)")
check("[3] main() runs it at start, right after backfill_cmd_markers (before the first sync)", 0 < i_bf < i_tn, (i_bf, i_tn))

print("\n[4] the Docker entrypoint")
a = E.index('  [ -n "$SUBNET" ] || { log "WARNING: could not read subnet for $IFACE')
blk = E[E.index("\n", a) + 1:E.index("\ndone\n", a)]
def entry(ifc, subnet="10.255.0.0/31"):
    return sh('log(){ echo "LOG $*"; }\nNATTED=""; IFACE=%s; SUBNET=%s; WAN=ens3\n%s\n' % (ifc, subnet, blk))
reset(["-t nat -A POSTROUTING -s 10.255.0.0/31 -o ens3 -j MASQUERADE"])
entry("awg0")
check("[4] a start over an older start's untagged rule: the interface's own tagged rule, the untagged one gone",
      nat() == [masq_of("awg0")], nat())
entry("awg0")
check("[4] a second start adds nothing", nat() == [masq_of("awg0")], nat())
entry("swg_x")
hup, hdown = AG._nat_hooks("10.255.0.0/31", "ens3")
sh(hdown.replace("%i", "swg_x"))
check("[4] two interfaces on one subnet: one's down (its hooks) leaves the other's rule", nat() == [masq_of("awg0")], nat())

print("\n[5] the agent's delete — its own rule only")
tconf = "[Interface]\nPostUp = %s\nPostDown = %s\n" % AG._nat_hooks("10.255.0.0/31", "ens3")
reset(["-t nat -A POSTROUTING -s 10.255.0.0/31 -o ens3 -m comment --comment swg-nat:swg_b -j MASQUERADE"] * 2
      + ["-t nat -A POSTROUTING -s 10.255.0.0/31 -o ens3 -m comment --comment swg-nat:swg_a -j MASQUERADE"])
AG._reap_egress_rules(tconf, "swg_b")
check("[5] a tagged .conf: every copy of its own rule goes, a twin's (same /31) stays", nat() == [masq_of("swg_a")], nat())
lconf = "[Interface]\nPostUp = %s\nPostDown = %s\n" % legacy_hooks("10.255.0.0/31", "ens3")
reset(["-t nat -A POSTROUTING -s 10.255.0.0/31 -o ens3 -j MASQUERADE"] * 2)
AG._reap_egress_rules(lconf, "swg_old")
check("[5] a legacy .conf: its untagged copies go, as before", nat() == [], nat())

print("\n[7] the agent's delete takes the rule named after the interface — a hookless (Docker) .conf too")
os.environ["LIVE_IFACES"] = ""
dconf = conf("docker-swg_51bc7bc8", "#swg:cmd awg\n[Interface]\nPrivateKey = cHJpdmF0ZS1rZXk=\nAddress = 10.255.0.0/31\nListenPort = 10000\n")
reset(['-t nat -A POSTROUTING -s 10.255.0.0/31 -o ens3 -m comment --comment swg-nat:swg_51bc7bc8 -j MASQUERADE'] * 2
      + ['-t nat -A POSTROUTING -s 10.255.0.0/31 -o ens3 -m comment --comment swg-nat:swg_eff49cad -j MASQUERADE',
         '-t nat -A POSTROUTING -s 10.81.1.0/24 -o ens3 -m comment --comment swg-nat:swg_51bc7bc80 -j MASQUERADE',
         '-t nat -A POSTROUTING -s 10.81.2.0/24 -o ens3 -j MASQUERADE'])
AG.run = lambda *a, **k: ""                               # the device and its unit are not this model's business
AG._iface_unit = lambda *a, **k: None
AG.op_delete_iface({"interfaces": {"swg_51bc7bc8": {"conf": dconf, "cmd": ["awg"]}}}, {"iface": "swg_51bc7bc8"})
check("[7] a hookless .conf: every copy of the rule named swg-nat:swg_51bc7bc8 is gone",
      not [r for r in nat() if '"swg-nat:swg_51bc7bc8"' in r], nat())
check("[7] …the twin link's (same /31), a longer name that only starts the same, and an untagged rule stay",
      sorted(nat()) == sorted([masq_of("swg_eff49cad"), '-A POSTROUTING -s 10.81.1.0/24 -o ens3 -m comment --comment "swg-nat:swg_51bc7bc80" -j MASQUERADE',
                               "-A POSTROUTING -s 10.81.2.0/24 -o ens3 -j MASQUERADE"]), nat())

print("\n[8] swg-noded's first start: a rule whose interface is gone goes, and nothing else")
CD = os.path.join(T, "confdirs"); os.makedirs(os.path.join(CD, "awg")); os.makedirs(os.path.join(CD, "wg"))
ND._NAT_CONF_DIRS = (os.path.join(CD, "awg"), os.path.join(CD, "wg"))
open(os.path.join(CD, "wg", "wg9.conf"), "w").write("[Interface]\n")          # a conf on disk, not managed, no device
KEEP = ['-t nat -A POSTROUTING -s 10.81.2.0/24 -o ens3 -m comment --comment swg-nat:awg0 -j MASQUERADE',   # managed + up
        '-t nat -A POSTROUTING -s 10.81.3.0/24 -o ens3 -m comment --comment swg-nat:wg3 -j MASQUERADE',    # managed, DOWN
        '-t nat -A POSTROUTING -s 10.81.4.0/24 -o ens3 -m comment --comment swg-nat:foo0 -j MASQUERADE',   # a device, unmanaged
        '-t nat -A POSTROUTING -s 10.81.5.0/24 -o ens3 -m comment --comment swg-nat:wg9 -j MASQUERADE',    # a .conf on disk
        '-t nat -A POSTROUTING -s 10.81.6.0/24 -o ens3 -j MASQUERADE',                                     # untagged
        '-t nat -A POSTROUTING -s 10.81.7.0/24 -o ens3 -m comment --comment swg-egress:gone1 -j MASQUERADE',
        '-t nat -A POSTROUTING -s 10.81.8.0/24 -o ens3 -m comment --comment ops-keep -j MASQUERADE']
GONE = ['-t nat -A POSTROUTING -s 10.255.0.0/31 -o ens3 -m comment --comment swg-nat:swg_51bc7bc8 -j MASQUERADE']
reset(KEEP + GONE)
before = [r for r in nat() if "swg_51bc7bc8" not in r]
os.environ["LIVE_IFACES"] = "awg0 foo0"
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    ND.tag_nat_hooks = lambda *a, **k: 0
    msrc_ok = "reap_orphan_nat(node_cfg)" in inspect.getsource(ND.main)
    ND.reap_orphan_nat({"interfaces": {"awg0": {"conf": "x"}, "wg3": {"conf": "y"}}}) if msrc_ok else None
check("[8] main() sweeps at start (after tag_nat_hooks)", msrc_ok and 0 < inspect.getsource(ND.main).find("tag_nat_hooks(node_cfg, agent, sudo)")
      < inspect.getsource(ND.main).find("reap_orphan_nat(node_cfg)"))
check("[8] the gone interface's rule (swg_51bc7bc8: not managed, no device, no .conf) is removed, and it says so",
      not [r for r in nat() if "swg_51bc7bc8" in r] and "swg_51bc7bc8" in buf.getvalue(), (nat(), buf.getvalue()))
check("[8] …every other rule stays: managed up and down, a device, a .conf on disk, untagged, swg-egress:, an operator's",
      sorted(nat()) == sorted(before), sorted(set(before) ^ set(nat())))
reset(GONE)
os.environ["IP_BROKEN"] = "1"
with contextlib.redirect_stdout(io.StringIO()):
    ND.reap_orphan_nat({"interfaces": {}})
os.environ.pop("IP_BROKEN", None)
check("[8] `ip` cannot say whether the device exists → the rule is left (fail safe)", len(nat()) == 1, nat())
os.environ["LIVE_IFACES"] = ""

print("\n[6] swg-noded's baseline still defers to the interface's own rule")
line = masq_of("awg0", NET)
check("[6] _has_foreign_egress reads swg-nat:<iface> as an existing NAT for the subnet (no second MASQUERADE)",
      ND._has_foreign_egress(NET, [line]) is True and ND._has_foreign_egress(NET, []) is False)

print()
if PLANTS:
    print("PERTURBED (%s): %s" % (",".join(sorted(PLANTS)), "RED as expected (%d failing)" % len(FAILS) if FAILS
                                   else "STILL GREEN — the gate does not see the defect"))
    sys.exit(0 if FAILS else 2)
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS))); sys.exit(1)
print("ALL PASS"); sys.exit(0)
