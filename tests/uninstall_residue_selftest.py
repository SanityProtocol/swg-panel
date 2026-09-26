#!/usr/bin/env python3
"""Self-test — a completed uninstall takes back what WE put on the box, exactly that, and nothing of anyone else's.

Found by listing what a finished uninstall actually left (1.8.8 qualification, q1 bare master + a converted box):
  [1] `6890: from all fwmark 0x1aea lookup 7000` — swg-noded's UPSTREAM-MARK band (6890-6989) was never swept; only the
      table band 7000-7099 and the relay's 6990 were. Its priorities are not table ids: only the rule goes.
  [2] /usr/local/bin/swg-passwd — the panel's login-reset helper, never removed.
  [3] `ufw allow 2087/tcp` (v4+v6) — opened by install-host.sh's serve_internal, never closed. It is now RECORDED when
      the installer actually adds it (never when ufw already had it: somebody else's), and exactly that is closed.
  [4] after a bare→docker convert whose docker data was KEPT: swg-sub's drop-in + tls dir, /var/www/wgstats, users
      swgpanel/swgsub — "Leftover swg files" was never offered while $DOCKER_DIR existed. Now offered; the identities are
      decided at run time (after the docker components): kept while a container remains, removed once none does.
  [5] a LIVE docker panel's own swg-netctl-docker units were listed as "swg-netctl (leftover helper)".
  [6] empty /etc/amnezia/amneziawg and /etc/wireguard — removed only when empty AND no package owns them.
  [7] keeping the wg/awg PACKAGES (the usual answer) skipped the whole datapath sweep — "some components were kept" —
      though a package runs no swg datapath: every swg ip rule / nft table stayed. Only a kept component that does
      (an interface, a node, a turn/WDTT/csqtt server — or anything new) still holds the sweep back.

Every piece is lifted out of uninstall.sh / install-host.sh AS SHIPPED and run against stubs (ip, ufw, dpkg, docker,
systemctl, rmrf) — nothing on this machine is touched.

Run: python3 tests/uninstall_residue_selftest.py      (0 = pass)
     --perturb   re-plants all seven shipped behaviours at once → RED (at least one FAIL per item)
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
U = open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()
H = open(os.path.join(ROOT, "install-host.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:80]
    return src.replace(a, b)

if PERTURB:
    U = plant(U, "awk '$1>=6890 && $1<=6989'", "awk '$1>=1 && $1<=0'")                                  # [1]
    U = plant(U, " /var/www/acme /usr/local/bin/swg-passwd   #", " /var/www/acme   #")                     # [2]
    H = plant(H, '      grep -qsx "${PORT}/tcp" "$ETC_DIR/ufw-added" || echo "${PORT}/tcp" >> "$ETC_DIR/ufw-added"\n',
              '      :\n')                                                                                # [3]
    U = plant(U, "if [ ! -d /opt/swg-panel ] && [ ! -f $SD/swg-panel-server.service ] \\\n   && [ ! -d /opt/swg-noded ]",
              "if [ ! -d \"$DOCKER_DIR\" ] && [ ! -d /opt/swg-panel ] && [ ! -f $SD/swg-panel-server.service ] \\\n   && [ ! -d /opt/swg-noded ]")  # [4]
    U = plant(U, "|| { ! $DPANEL && _has_docker_netctl; }", "|| { [ ! -d /opt/swg-panel ] && _has_docker_netctl; }")  # [5]
    U = plant(U, "  for _d in /etc/amnezia/amneziawg /etc/amnezia /etc/wireguard; do\n", "  for _d in; do\n")  # [6]
    U = plant(U, '  if [ "${KEPT_DATAPATH:-false}" = true ]; then\n', '  if [ "${#DID_KEEP[@]}" -gt 0 ]; then\n')  # [7]

def fn(src, name):
    """The function `name(){ … }` exactly as shipped: from its header to the FIRST closing line at which the text
    parses (`bash -n`) — so a `…; }` inside the body (an inline `{ …; }` group) is never mistaken for the end, and
    the top-level code after a function that closes with `; }` is never swallowed with it."""
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot extract " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if not l.split("  #")[0].rstrip().endswith("}"):
            continue
        text = "\n".join(lines[:k + 1]) + "\n"
        if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
            return text
    raise AssertionError("unterminated " + name)

def between(src, a, b):
    i = src.index(a); j = src.index(b, i)
    return src[i:j]

def bash(script, stubs, env=None):
    d = tempfile.mkdtemp(prefix="unres-"); log = os.path.join(d, "calls")
    for name, body in stubs.items():
        p = os.path.join(d, name)
        open(p, "w").write('#!/bin/bash\necho "%s $*" >> %s\n%s\n' % (name, log, body)); os.chmod(p, 0o755)
    e = dict(os.environ, PATH=d + ":/usr/bin:/bin", T=d); e.update(env or {})
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=e)
    return p.stdout + p.stderr, (open(log).read() if os.path.exists(log) else ""), d

PRE = ('DRYRUN=false\ninfo(){ echo "INFO $*"; }; ok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }; sub(){ :; }\n'
       'b(){ printf %s "$*"; }\nrun(){ "$@"; }\n')

print("[1] the datapath sweep takes the upstream-mark band too — rules only, never a table of that number")
rules = ("0:\tfrom all lookup local\n5000:\tfrom all lookup main\n6890:\tfrom all fwmark 0x1aea lookup 7000\n"
         "6891:\tfrom 10.18.0.1 fwmark 0x1aeb lookup 7001\n6990:\tfrom all fwmark 0x9c40 lookup 6990\n"
         "7000:\tfrom 10.8.0.0/24 lookup 7000\n32766:\tfrom all lookup main")
out, calls, _ = bash(PRE + "rmrf(){ :; }\n" + fn(U, "rm_node_netobjects") + "rm_node_netobjects\n",
                     {"ip": 'case "$1 $2" in "rule show") printf "%s\\n" "' + rules.replace("\t", "\\t") + '";; esac; exit 0',
                      "iptables": "exit 0", "nft": "exit 0", "ipset": "exit 0"})
dels = re.findall(r"^ip rule del pref (\d+)$", calls, re.M)
flush = re.findall(r"^ip route flush table (\d+)$", calls, re.M)
check("6890 and 6891 (the upstream band) are deleted", "6890" in dels and "6891" in dels, calls)
check("…and no `table 6890`/`6891` is flushed — those priorities name no table of ours", "6890" not in flush and "6891" not in flush, flush)
check("the table band is still swept as before (7000: rule + table)", "7000" in dels and "7000" in flush, calls)
check("nobody else's rule is touched (0, 5000, 32766), nor the relay's 6990 (rm_node owns it)",
      not ({"0", "5000", "32766", "6990"} & set(dels)), dels)

print("\n[2] rm_panel removes the login-reset helper it installed")
out, calls, _ = bash(PRE + 'SD=/nonexistent; DOMAIN=""; PANEL_DATA_DEL=no; REMOVED_PANEL=false\n'
                     'rmrf(){ echo "RMRF $*"; }\nask_yn(){ :; }\nufw_forget(){ echo "UFWFORGET $*"; }\nid(){ return 1; }\n'
                     + fn(U, "rm_panel") + "rm_panel\n", {"systemctl": "exit 0", "nginx": "exit 1"})
rmrf = " ".join(l for l in out.splitlines() if l.startswith("RMRF"))
check("/usr/local/bin/swg-passwd is in rm_panel's removal", "/usr/local/bin/swg-passwd" in rmrf.split(), rmrf)
check("…and the docker address helper's binary a docker era left (seen on a bare master)", "/usr/local/bin/swg-netctl-docker" in rmrf.split(), rmrf)
# the ufw record lives in /etc/swg-panel, which goes only with the data (a kept panel keeps it — kept_panel_identity_selftest)
out, calls, _ = bash(PRE + 'SD=/nonexistent; DOMAIN=""; PANEL_DATA_DEL=yes; REMOVED_PANEL=false\n'
                     'rmrf(){ echo "RMRF $*"; }\nask_yn(){ :; }\nufw_forget(){ echo "UFWFORGET $*"; }\nid(){ return 1; }\n'
                     + fn(U, "rm_panel") + "rm_panel\n", {"systemctl": "exit 0", "nginx": "exit 1"})
lines = out.splitlines()
fi = next((k for k, l in enumerate(lines) if l.startswith("UFWFORGET /etc/swg-panel/ufw-added")), None)
ri = next((k for k, l in enumerate(lines) if l.startswith("RMRF") and " /etc/swg-panel " in l + " "), None)
check("the ufw record is read BEFORE /etc/swg-panel (where it lives) is removed", fi is not None and ri is not None and fi < ri, out)

print("\n[3] ufw: the installer records a rule it ADDED; the uninstaller closes exactly that")
ublock = between(H, '  if command -v ufw >/dev/null 2>&1; then\n    _ufw_out=', '  local sch="https"')
def inst(ufw_says, dry=False):
    d = tempfile.mkdtemp(prefix="ufwi-")
    out, calls, t = bash('DRYRUN=%s\nrun(){ if $DRYRUN; then echo "    [skip] $*"; else "$@"; fi; }\nETC_DIR=%s\nPORT=2087\n%s'
                         % ("true" if dry else "false", d, ublock), {"ufw": 'printf "%s\\n" "' + ufw_says + '"'})
    rec = os.path.join(d, "ufw-added")
    return open(rec).read() if os.path.exists(rec) else None
check("ufw answers 'Rule added' (v4+v6) → recorded as 2087/tcp", inst("Rule added\\nRule added (v6)") == "2087/tcp\n")
check("ufw is inactive ('Rules updated') → still ours, recorded", inst("Rules updated\\nRules updated (v6)") == "2087/tcp\n")
check("ufw already had it ('Skipping adding existing rule') → somebody else's, NOT recorded",
      inst("Skipping adding existing rule\\nSkipping adding existing rule (v6)") is None)
check("a dry run records nothing", inst("Rule added", dry=True) is None)
uf = fn(U, "ufw_forget")
d = tempfile.mkdtemp(prefix="ufwu-"); open(os.path.join(d, "ufw-added"), "w").write("2087/tcp\n")
out, calls, _ = bash(PRE + uf + "ufw_forget %s/ufw-added\n" % d, {"ufw": "exit 0"})
check("a recorded rule is deleted: `ufw delete allow 2087/tcp`", "ufw delete allow 2087/tcp" in calls, calls)
d2 = tempfile.mkdtemp(prefix="ufwu-"); open(os.path.join(d2, "install.conf"), "w").write("PORT=2087\nSERVE_MODE=internal\n")
out, calls, _ = bash(PRE + uf + "ufw_forget %s/ufw-added\n" % d2,
                     {"ufw": '[ "$1 $2" = "show added" ] && echo "ufw allow 2087/tcp"; exit 0'})
check("NO record (an older install) → the rule is named, never deleted", "delete" not in calls and "ufw still allows 2087/tcp" in out, (out, calls))

print("\n[4] 'Leftover swg files' is offered beside a KEPT docker dir, and decides the identities at run time")
_ga = "(`swgpanel` owns data a convert copied in).\n"
gate = between(U, _ga,
               'if ! $DPANEL && ! $DNODE && { [ -f "$DOCKER_DIR/docker-compose.yml" ]')
gate = gate[len(_ga):]
kd = tempfile.mkdtemp(prefix="kept-"); os.makedirs(os.path.join(kd, "data", "lib"))
out, calls, _ = bash('SD=/nonexistent; DOCKER_DIR=%s; DPANEL=false; DNODE=false\n_has_leftovers(){ return 0; }\n'
                     'add(){ echo "ADD $1"; }\n%s' % (kd, gate), {})
check("no bare install left, docker dir KEPT → 'Leftover swg files' is offered", "ADD Leftover swg files" in out, out)
rl = fn(U, "rm_leftovers")
def leftovers(docker_live):
    return bash(PRE + 'SD=/nonexistent; DOCKER_DIR=%s\nrmrf(){ echo "RMRF $*"; }\nufw_forget(){ echo "UFWFORGET $*"; }\n'
                'docker_running(){ %s; }\nid(){ return 0; }\n%s rm_leftovers\necho "REMOVED_LEFTOVERS=${REMOVED_LEFTOVERS:-}"\n'
                % (kd, "return 0" if docker_live else "return 1", rl), {"systemctl": "exit 0", "userdel": "exit 0", "chown": "exit 0"})
out, calls, _ = leftovers(False)
check("docker gone → bare-era files go: sub drop-in + tls dir, /var/www/wgstats, swg-passwd",
      all(x in out for x in ("/etc/swg-sub", "swg-sub.service.d", "/var/www/wgstats", "/usr/local/bin/swg-passwd")), out)
check("docker gone → the kept data is handed to root FIRST, then swgpanel/swgsub go",
      "chown -R root:root %s/data" % kd in calls and "userdel swgpanel" in calls and "userdel swgsub" in calls
      and calls.index("chown") < calls.index("userdel"), calls)
out, calls, _ = leftovers(True)
check("a docker container still here → its identities are KEPT (not ours to orphan)", "userdel" not in calls
      and "REMOVED_LEFTOVERS=\n" in out + "\n", (out, calls))

print("\n[5] a LIVE docker panel's own address helper is not a 'leftover helper'")
reg = between(U, "{ { [ ! -d /opt/swg-panel ] && [ ! -f $SD/swg-panel-server.service ] && _has_bare_netctl; }",
              "\n# swg-sub's dirs/units")
for dp, want in (("true", False), ("false", True)):
    out, calls, _ = bash('SD=/nonexistent; DPANEL=%s\n_has_bare_netctl(){ return 1; }\n_has_docker_netctl(){ return 0; }\n'
                         'add(){ echo "ADD $1"; }\n%s' % (dp, reg), {})
    check("docker panel %s + swg-netctl-docker.* present → %s" % ("LIVE" if dp == "true" else "gone",
          "NOT listed as a leftover" if not want else "listed as a leftover"),
          ("ADD swg-netctl (leftover helper)" in out) == want, out)

print("\n[6] empty interface-config dirs go — only empty, and only when no package owns them")
emp = between(U, 'if [ "${#DID_REMOVE[@]}" -gt 0 ] && command -v dpkg >/dev/null 2>&1; then', "\n\necho;")
t = tempfile.mkdtemp(prefix="wgd-")
for sub in ("amnezia/amneziawg", "wireguard", "wgfull"):
    os.makedirs(os.path.join(t, sub))
open(os.path.join(t, "wgfull", "wg9.conf"), "w").write("x")
emp2 = emp.replace("/etc/amnezia/amneziawg /etc/amnezia /etc/wireguard", "%s/amnezia/amneziawg %s/amnezia %s/wireguard %s/wgfull" % (t, t, t, t))
assert emp2 != emp or PERTURB
out, calls, _ = bash(PRE + "DID_REMOVE=(x)\n" + emp2, {"dpkg": '[ "$2" = "%s/wireguard" ] && exit 0; exit 1' % t})
check("empty + unowned → /etc/amnezia/amneziawg (and then /etc/amnezia) removed",
      not os.path.exists(os.path.join(t, "amnezia", "amneziawg")) and not os.path.exists(os.path.join(t, "amnezia")), os.listdir(t))
check("empty but a package owns it (dpkg -S answers) → /etc/wireguard KEPT", os.path.isdir(os.path.join(t, "wireguard")))
check("a dir still holding a file → KEPT", os.path.isdir(os.path.join(t, "wgfull")))

print("\n[7] keeping a PACKAGE (or anything that runs no swg datapath) does not skip the datapath sweep")
loop = between(U, "DID_REMOVE=(); DID_KEEP=(); NOT_DONE=()", "\n# Containers we TOOK")
def sweep(kept):
    comps = ["rm_node", "rm_awg_peers", "rm_awg_pkg", "rm_wg_pkg"]
    script = PRE + ('N=%d\nCLABEL=(%s)\nCFN=(%s)\nCARG=(); CHINT=(); CVERB=(); CNOAUTO=(); CPROMPT=(%s)\n'
              'for k in $(seq 0 $((N-1))); do CARG+=(""); CHINT+=(""); CVERB+=(""); CNOAUTO+=(""); done\n'
              'KEEP=" %s "\nask_comp(){ case "$KEEP" in *" $1 "*) return 1;; *) return 0;; esac; }\n'
              'rm_node(){ NEED_NETOBJ_SWEEP=true; }; rm_awg_peers(){ :; }; rm_awg_pkg(){ :; }; rm_wg_pkg(){ :; }\n'
              'rm_node_netobjects(){ echo SWEPT; }\n%s') % (len(comps), " ".join(comps), " ".join(comps), " ".join(comps),
                                                           " ".join(kept), loop)
    out, _, _ = bash(script, {})
    return "SWEPT" in out
check("node + interfaces removed, the wg/awg PACKAGES kept → the sweep RUNS (nothing kept uses swg's rules)",
      sweep(["rm_awg_pkg", "rm_wg_pkg"]))
check("an interface KEPT → the sweep is skipped (its egress rules are its datapath)", not sweep(["rm_awg_peers"]))

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
