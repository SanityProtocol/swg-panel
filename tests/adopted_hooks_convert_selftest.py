#!/usr/bin/env python3
"""Self-test — AN ADOPTED INTERFACE KEEPS ITS OWN HOOKS ACROSS A CONVERT, BOTH WAYS, AND ITS ORIGINAL IS KEPT BYTE FOR BYTE.

1.8.8 qualification, round 8 (pre-existing, in 1.8.7): a bare → Docker convert stripped every PostUp/PostDown — an adopted
(#swg:onboarded) conf's own too — and the bare original went with the switch, so its hooks were gone for good; the way back
(convert.sh import_bare_conf) wrote swg's NAT hooks INTO the adopted conf. Both contradict "an adopted interface keeps its
hooks". Now its hooks stay where they can run — on the host: the container does not run them (a hook that fails there takes
the interface down), so install-docker.sh keeps the original, byte for byte, in /etc/swg-panel-confs.converted-<ts> and the
convert back puts them back from it (or from the host's own conf of it: a Docker node that adopted a host interface left
that in place) — and nothing of ours is written into an adopted conf.

  [1] install-docker.sh migrate_baremetal_ifaces (bare → Docker), lifted as shipped: the Docker copies carry no PostUp/
      PostDown; the ADOPTED conf's original is kept byte for byte (dir 0700, file 0600) and one line says so; a managed
      conf gets no such copy
  [2] convert.sh import_bare_conf: an adopted conf with an original → exactly its own hook lines, in order, and none of
      ours; without one → the conf as it came; a managed conf → swg's NAT hooks, as before
  [3] the node's Docker → bare import loop, lifted as shipped, after [1]: the adopted interface comes back with its own
      hooks byte for byte, its Docker original is kept in the backup, and one line says both; the managed one gets ours
  [4] …a Docker node that adopted a HOST interface (its original still on the host): the hooks come from that original,
      which is still kept beside the import (.pre-convert) as before
  [5] after the switch back (round 9), the node container's own rule for an ADOPTED interface goes — quoted or not, and
      only that interface's (not a managed one's, not wg88's, not the operator's own) — and one line names it; when the
      interface's own hooks carry our tag (swg-nat:%i), the rule is theirs and stays; both Docker → bare paths call it
      after install-node.sh (the switch)

Run: python3 tests/adopted_hooks_convert_selftest.py     (0 = pass)
     --perturb             import_bare_conf writes our NAT hooks into an adopted conf again (the shipped behaviour) → RED
     --perturb-nobackup    bare → Docker keeps no copy of the adopted original (the shipped behaviour) → RED on [1] and [3]
     --perturb-norestore   the way back does not look for the original → RED on [3] and [4]
     --perturb-noreap      the container's rule is left for an adopted interface (the first round-9 fix) → RED on [5]
"""
import os, re, stat, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
V = open(os.path.join(ROOT, "convert.sh"), encoding="utf-8").read()
D = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
C = open(os.path.join(ROOT, "lib", "common.sh"), encoding="utf-8").read()
MODE = next((a for a in sys.argv[1:] if a in ("--perturb", "--perturb-nobackup", "--perturb-norestore", "--perturb-noreap")), None)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:700]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

if MODE == "--perturb":
    V = plant(V, '  if conf_is_adopted "$src"; then                         # its own hooks or none — never ours (see above)\n',
              '  if false; then\n')
if MODE == "--perturb-nobackup":
    D = plant(D, '      cp -p "$src" "$_cbak/$n.conf" && chmod 600 "$_cbak/$n.conf"\n', '      :\n')
if MODE == "--perturb-noreap":
    V = plant(V, '  [ -n "$ad" ] || return 0\n  gone="$(reap_container_nat $ad', '  return 0\n  gone="$(reap_container_nat $ad')
if MODE == "--perturb-norestore":
    V = plant(V, '    [ -f "$c" ] && same_iface_conf "$c" "$src" && [ -n "$(conf_hooks "$c")" ] && { printf \'%s\\n\' "$c"; return 0; }\n',
              '    :\n')

def fn(src, name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot lift " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

T = tempfile.mkdtemp(prefix="adopthooks-")
AWG, WG, BAK = os.path.join(T, "amnezia"), os.path.join(T, "wireguard"), os.path.join(T, "etc")
for d in (AWG, WG, BAK):
    os.makedirs(d)
def remap(text):
    return (text.replace("/etc/amnezia/amneziawg", AWG).replace("/etc/wireguard", WG)
                .replace("/etc/swg-panel-confs.converted-", BAK + "/swg-panel-confs.converted-"))

KEY_A = "cHJpdmF0ZS1rZXktYWRvcHRlZC1hZG9wdGVkLWFkb3A="
KEY_M = "cHJpdmF0ZS1rZXktbWFuYWdlZC1tYW5hZ2VkLW1hbmE="
HOOKS = ("PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o ens3 -j MASQUERADE\n"
         "PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o ens3 -j MASQUERADE\n")
ADOPTED = ("#swg:onboarded\n#swg:cmd wg\n[Interface]\nPrivateKey = %s\nAddress = 10.66.8.1/24\nListenPort = 51888\n%s"
           "\n# name: laptop\n[Peer]\nPublicKey = 5dYQ79ynisVEC8XyQgXamgfpZe38PN6KihtEV6kpGjk=\nAllowedIPs = 10.66.8.2/32\n" % (KEY_A, HOOKS))
MANAGED = ("#swg:cmd awg\n[Interface]\nPrivateKey = %s\nAddress = 10.66.9.1/24\nListenPort = 51889\nJc = 4\n"
           "PostUp = sysctl -q -w net.ipv4.ip_forward=1 || true\nPostDown = true\n" % KEY_M)

def bash(script):
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr

PRE = ('set -uo pipefail\nDRYRUN=false; RESET=""; C_GREEN=""\nb(){ printf %s "$*"; }; info(){ echo "INFO $*"; }; sub(){ echo "SUB $*"; }\n'
       'warn(){ echo "WARN $*"; }\n')

print("[1] bare → Docker: install-docker.sh migrate_baremetal_ifaces")
open(os.path.join(WG, "wg8.conf"), "w").write(ADOPTED)
open(os.path.join(AWG, "awg0.conf"), "w").write(MANAGED)
INST = os.path.join(T, "docker")
mig = remap(fn(D, "migrate_baremetal_ifaces"))
rc, out = bash(PRE + 'SWG_CONVERT_DIR=convert-docker; INSTALL_DIR="%s"; NODE_ENDPOINT=192.0.2.9\n' % INST
               + 'migrate_wdtt(){ :; }; migrate_csqtt(){ :; }; migrate_node_state(){ :; }; detect_public_ip(){ echo 192.0.2.9; }\n'
               + mig + "migrate_baremetal_ifaces\n")
dw8 = os.path.join(INST, "data", "node-confs", "wg8.conf")
d8 = open(dw8).read() if os.path.exists(dw8) else ""
check("[1] the Docker copies carry no PostUp/PostDown (the container does not run a host's hooks)",
      d8 and not re.search(r"(?im)^\s*Post(Up|Down)\s*=", d8), (rc, out[-400:], d8))
baks = [os.path.join(dp, f) for dp, _, fs in os.walk(BAK) for f in fs]
bak8 = [b for b in baks if b.endswith("/wg8.conf")]
check("[1] the ADOPTED original is kept, byte for byte", len(bak8) == 1 and open(bak8[0]).read() == ADOPTED, (baks, out[-300:]))
check("[1] …in a 0700 directory, as a 0600 file", bak8 and stat.S_IMODE(os.stat(os.path.dirname(bak8[0])).st_mode) == 0o700
      and stat.S_IMODE(os.stat(bak8[0]).st_mode) == 0o600, bak8)
check("[1] …and one line says its hooks do not run in the container and where the original is",
      "wg8" in out and "(adopted)" in out and "do not run in the container" in out and "kept byte for byte" in out, out[-500:])
check("[1] a managed conf gets no such copy", not [b for b in baks if b.endswith("/awg0.conf")], baks)

print("\n[2] convert.sh import_bare_conf")
IMP = (fn(C, "_ipt_reap_sh") + fn(C, "_ipt_set_sh") + fn(C, "nat_hook_up") + fn(C, "nat_hook_down") + 'detect_wan(){ echo ens3; }\n'
       + "".join(fn(V, n) for n in ("conf_privkey", "same_iface_conf", "conf_is_adopted", "conf_hooks", "import_bare_conf")))
src_d = os.path.join(T, "docker-wg8.conf"); open(src_d, "w").write(d8)
orig = os.path.join(T, "orig-wg8.conf"); open(orig, "w").write(ADOPTED)
got = os.path.join(T, "imp1.conf")
rc, out = bash(PRE + IMP + 'import_bare_conf "%s" "%s" "%s"\n' % (src_d, got, orig))
g1 = open(got).read() if os.path.exists(got) else ""
hooks_of = lambda t: [l for l in t.splitlines() if re.match(r"(?i)^\s*(pre|post)(up|down)\s*=", l)]
check("[2] an adopted conf with its original → exactly its own hook lines, in order",
      hooks_of(g1) == hooks_of(ADOPTED), (hooks_of(g1), out))
check("[2] …none of ours (no swg-nat, no reap-then-add loop)", "swg-nat:" not in g1 and "for _n in" not in g1, g1)
check("[2] …and the rest is the Docker conf's (its key, its peer)", KEY_A in g1 and "10.66.8.2/32" in g1, g1)
got2 = os.path.join(T, "imp2.conf")
rc, out = bash(PRE + IMP + 'import_bare_conf "%s" "%s"\n' % (src_d, got2))
check("[2] an adopted conf with no original → the conf as it came, nothing of ours added",
      os.path.exists(got2) and open(got2).read() == d8, (out, open(got2).read() if os.path.exists(got2) else None))
srcm = os.path.join(T, "docker-awg0.conf"); open(srcm, "w").write(MANAGED.replace("PostUp = sysctl -q -w net.ipv4.ip_forward=1 || true\nPostDown = true\n", ""))
got3 = os.path.join(T, "imp3.conf")
rc, out = bash(PRE + IMP + 'import_bare_conf "%s" "%s"\n' % (srcm, got3))
g3 = open(got3).read() if os.path.exists(got3) else ""
check("[2] a managed conf → swg's NAT hooks, as before", "swg-nat:%i" in g3 and g3.count("PostUp = ") == 1, g3)

print("\n[3] Docker → bare: the node's import loop, after [1]")
# the Docker side as a node convert finds it: data/node-confs from [1], the bare dirs emptied by the switch
for f in os.listdir(WG) + os.listdir(AWG):
    p = os.path.join(WG, f) if os.path.exists(os.path.join(WG, f)) else os.path.join(AWG, f)
    os.remove(p)
a = V.index('  names=""\n  for s in $specs; do nm="${s%:*}"; pr="${s#*:}"')
b = V.index("\n  done\n", a) + len("\n  done\n")
loop = remap(V[a:b])
helpers = "".join(fn(V, n) for n in ("adopted_hooks_from", "keep_docker_original", "adopted_import_line"))
rc, out = bash(PRE + IMP + remap(helpers) + 'confd="%s"; specs="wg8:wg awg0:awg"\n' % os.path.join(INST, "data", "node-confs") + loop)
b8 = os.path.join(WG, "wg8.conf")
g = open(b8).read() if os.path.exists(b8) else ""
check("[3] the adopted interface comes back to bare metal with its OWN hooks, byte for byte, none of ours",
      hooks_of(g) == hooks_of(ADOPTED) and "swg-nat:" not in g, (hooks_of(g), out[-500:]))
kept = [os.path.join(dp, f) for dp, _, fs in os.walk(BAK) for f in fs if f == "wg8.conf"]
check("[3] …its Docker original is kept byte for byte in a backup too", any(open(k).read() == d8 for k in kept), kept)
check("[3] …and one line says where the hooks came from and where the original is (a path, not a blank)",
      re.search(r"adopted: its own hooks put back from \S+wg8\.conf.*kept byte for byte in \S+wg8\.conf\)", out) is not None, out[-500:])
ga = open(os.path.join(AWG, "awg0.conf")).read() if os.path.exists(os.path.join(AWG, "awg0.conf")) else ""
check("[3] the managed one gets ours (host NAT added), as before", "swg-nat:%i" in ga and "host NAT added" in out, (ga[:200], out[-300:]))

print("\n[4] a Docker node that adopted a HOST interface (its original still on the host)")
for dp, _, fs in os.walk(BAK):
    for f in fs:
        os.remove(os.path.join(dp, f))                   # no convert backup this time: the host's own conf is the original
for f in os.listdir(WG):
    os.remove(os.path.join(WG, f))
for f in os.listdir(AWG):
    os.remove(os.path.join(AWG, f))
open(os.path.join(WG, "wg8.conf"), "w").write(ADOPTED)   # the host's own, as the operator wrote it
rc, out = bash(PRE + IMP + remap(helpers) + 'confd="%s"; specs="wg8:wg"\n' % os.path.join(INST, "data", "node-confs") + loop)
g = open(b8).read() if os.path.exists(b8) else ""
check("[4] the hooks come back from the host's own conf of it", hooks_of(g) == hooks_of(ADOPTED) and "swg-nat:" not in g, (g, out[-400:]))
pre = os.path.join(WG, "wg8.conf.pre-convert")
check("[4] …which is still kept beside the import when it differs (.pre-convert), or already is the import",
      (os.path.exists(pre) and open(pre).read() == ADOPTED) or g == ADOPTED, (os.listdir(WG), out[-300:]))

print("\n[5] Docker → bare, after the switch: the node container's rule for an ADOPTED interface")
FAKE = os.path.join(T, "bin"); os.makedirs(FAKE)
RULES = os.path.join(T, "nat-rules")
open(os.path.join(FAKE, "iptables"), "w").write("""#!/usr/bin/env python3
import shlex, sys
f = %r
rules = [l for l in open(f).read().splitlines() if l.strip()]
a = sys.argv[1:]
if a[:3] == ["-t", "nat", "-S"]:
    print("-P POSTROUTING ACCEPT"); print("\\n".join(rules)); sys.exit(0)
if a[:3] == ["-t", "nat", "-D"]:
    want = ["-A"] + a[3:]
    for i, r in enumerate(rules):
        if shlex.split(r) == want:
            del rules[i]; open(f, "w").write("\\n".join(rules) + "\\n"); sys.exit(0)
    sys.exit(1)
sys.exit(2)
""" % RULES)
os.chmod(os.path.join(FAKE, "iptables"), 0o755)
R_C = '-A POSTROUTING -s 10.66.8.0/24 -o ens3 -m comment --comment "swg-nat:wg8" -j MASQUERADE'
R_C2 = '-A POSTROUTING -s 10.66.8.0/24 -o ens3 -m comment --comment swg-nat:wg8 -j MASQUERADE'
R_M = '-A POSTROUTING -s 10.66.9.0/24 -o ens3 -m comment --comment "swg-nat:awg0" -j MASQUERADE'
R_OP = '-A POSTROUTING -s 10.66.8.0/24 -o ens3 -m comment --comment r22-own -j MASQUERADE'
R_88 = '-A POSTROUTING -s 10.66.7.0/24 -o ens3 -m comment --comment "swg-nat:wg88" -j MASQUERADE'
REAP = remap(fn(V, "reap_container_nat") + fn(V, "reap_adopted_container_nat"))
def reap_case(wg8_conf):
    open(RULES, "w").write("\n".join([R_C, R_C2, R_M, R_OP, R_88]) + "\n")
    for f in os.listdir(WG) + os.listdir(AWG):
        for d in (WG, AWG):
            if os.path.exists(os.path.join(d, f)): os.remove(os.path.join(d, f))
    open(os.path.join(WG, "wg8.conf"), "w").write(wg8_conf)
    open(os.path.join(AWG, "awg0.conf"), "w").write(MANAGED)
    rc, out = bash('export PATH="%s:$PATH"\n' % FAKE + PRE + "".join(fn(V, n) for n in ("conf_is_adopted",)) + REAP
                   + "reap_adopted_container_nat wg8 awg0\n")
    return [l for l in open(RULES).read().splitlines() if l.strip()], out
left, out = reap_case(ADOPTED)
check("[5] the container's rule for the adopted wg8 goes — quoted and unquoted", R_C not in left and R_C2 not in left, (left, out))
check("[5] …a managed interface's, wg88's and the operator's own rule stay", all(r in left for r in (R_M, R_88, R_OP)), left)
check("[5] …and one line names it", "removed the Docker node's NAT rule for wg8" in out and "awg0" not in out.split("rule for", 1)[-1], out)
left, out = reap_case(ADOPTED.replace("iptables -t nat -A POSTROUTING -o ens3 -j MASQUERADE",
                                      "iptables -t nat -A POSTROUTING -o ens3 -m comment --comment swg-nat:%i -j MASQUERADE"))
check("[5] its own hooks carry our tag (swg-nat:%i) → the rule is theirs and stays", R_C in left and R_C2 in left and "removed" not in out, (left, out))
cm = V.index('    reap_adopted_container_nat $mnames')
cn = V.index('  reap_adopted_container_nat $names')
check("[5] the master's Docker → bare path reaps right after install-node.sh (the switch)",
      V.rfind('bash "$SRC/install-node.sh"', 0, cm) > V.rfind("\nfi\n", 0, cm) and cm - V.rfind('bash "$SRC/install-node.sh"', 0, cm) < 300)
check("[5] the node's Docker → bare path reaps right after install-node.sh (the switch)",
      cn - V.rfind('bash "$SRC/install-node.sh"', 0, cn) < 300)

print()
if MODE:
    print("PERTURBED (%s): %s" % (MODE, "RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate is blind"))
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "FAILED: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
