#!/usr/bin/env python3
"""Self-test — installing a node over one that already has an endpoint keeps it, and the interface list says only
true things.

  [1] install-node.sh re-run: each interface's OWN endpoint was read back, but not the NODE's, so every interface
      without one (every interface the panel created — they carry none and fall back to the node's) was re-detected
      from the default route and written back PINNED to that address. A docker → bare-metal convert did the same to
      every migrated interface: the panel's client configs changed 192.168.77.x → 10.0.2.15 (1.8.8 qualification).
      Now: the node's configured endpoint (ENDPOINT_IP / -endpoint, else the one it already had) is kept, and a
      convert's ADOPTED_ENDPOINTS ("name=host,…", convert.sh) keeps each migrated interface's own.
  [2] install-host.sh (master): an explicit HOST_ENDPOINT_IP is what an adopted interface advertises, not the
      default-route address.
  [3] the listing printed "No local interfaces yet" and then, one line below, "✓ Managing: awg0 wg0" — and one list
      spelled the protocol "Wireguard" beside "WireGuard" everywhere else.

read_existing, the NODE SETUP defaults and apply_node_switch are lifted out of install-node.sh (the same loop and
listing out of install-host.sh) AS SHIPPED and run with the box's tools stubbed.

Run: python3 tests/node_endpoint_keep_selftest.py      (0 = pass)
     --perturb   re-plants the shipped behaviour (re-detect, no ADOPTED_ENDPOINTS, the listing, the spelling) → RED
"""
import json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
N = open(os.path.join(ROOT, "install-node.sh"), encoding="utf-8").read()
H = open(os.path.join(ROOT, "install-host.sh"), encoding="utf-8").read()
C = open(os.path.join(ROOT, "lib/common.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b, cnt=1):
    assert src.count(a) == cnt, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

if PERTURB:
    N = plant(N, '    case "${ENDPOINT_IP:-}" in ""|127.*|localhost) ;; *) echo "    Kept $(bb "$ENDPOINT_IP") (this node\'s endpoint) for $(col "$C_GREEN" "$n")"; continue;; esac\n', '')
    N = plant(N, '[ -n "$ENDPOINT_IP" ] || ENDPOINT_IP="$EXIST_EP"\n', '')
    N = plant(N, '  [ -n "$_an" ] && [ "$_an" != "$_ae" ] && [ -n "$_ah" ] && [ -z "${IF_ENDPOINT[$_an]:-}" ] && IF_ENDPOINT[$_an]="$_ah"\n', '  :\n')
    H = plant(H, '    case "${HOST_ENDPOINT_IP:-}" in ""|127.*|localhost) ;; *) echo "    Kept $(bb "$HOST_ENDPOINT_IP") (this node\'s endpoint) for $(col "$C_GREEN" "$n")"; continue;; esac\n', '')
    H = plant(H, '  HOST_ENDPOINT_IP="${_aep:-$ENDPOINT_SAVED}"\n', '  :\n')
    for src in ("N", "H"):
        globals()[src] = plant(globals()[src],
                               "< <({ local_ifaces; printf '%s\\n' ${SELECTED[@]+\"${SELECTED[@]}\"}; } | tr -d ' ' | awk 'NF && !s[$0]++' | drop_sys_ifaces)",
                               "< <(local_ifaces)")
    C = plant(C, "proto_label(){ case \"$1\" in wg) printf 'WireGuard';;", "proto_label(){ case \"$1\" in wg) printf 'Wireguard';;")

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

STUBS = ('BOLD=""; RESET=""; C_BLUE=""; C_GREEN=""\nhave(){ command -v "$1" >/dev/null 2>&1; }\n'
         'b(){ printf %s "$*"; }\nbb(){ printf %s "$*"; }\ncol(){ shift; printf %s "$*"; }\n'
         'info(){ echo "INFO $*"; }\nok(){ echo "OK $*"; }\nwarn(){ :; }\nsub(){ :; }\nrun(){ :; }\n'
         'detect_public_ip(){ echo 10.0.2.15; }\napply_specs(){ :; }\ndetect_wg(){ :; }\nensure_wg_tools(){ return 0; }\n'
         'bringup(){ return 0; }\nlc_teardown_docker(){ :; }\nlocal_ifaces(){ printf "%s" "$LOCAL"; }\nwdtt_local(){ :; }\n'
         'wdtt_row(){ :; }\nconf_get(){ echo "?"; }\n'
         'declare -A IF_CMD IF_CONF IF_ENDPOINT SPEC_CMD SPEC_PORT SPEC_ADDR SPEC_EP; declare -a SELECTED\n'
         'SWG_SYS_PREFIX=swg_\n' + fn(C, "is_sys_iface") + fn(C, "drop_sys_ifaces"))   # lib/common.sh's, as the installers source them

print("[1] install-node.sh: a re-run or a convert keeps the endpoints this node already has")
setup = N[N.index("read_existing\n# ⚠️ THE ENDPOINT THIS NODE ALREADY HAS"):]
setup = setup[:setup.index("\ndone\n") + 6] if not PERTURB else setup[:setup.index("\n# RE-INSTALL: signal")]
_init = re.search(r"^EXIST_URL=.*$", N, re.M).group(0)   # the globals read_existing fills (as shipped)
node_fns = _init + "\n" + fn(N, "read_existing") + fn(N, "iface_row") + fn(N, "apply_node_switch") + fn(C, "proto_label")
def node(existing=None, endpoint_ip="", adopted="", selected=("awg0", "wg0"), local=""):
    d = tempfile.mkdtemp(prefix="nek-"); cfg = os.path.join(d, "config.json")
    if existing is not None:
        json.dump(existing, open(cfg, "w"))
    ip = os.path.join(d, "ip"); open(ip, "w").write("#!/bin/sh\nexit 0\n"); os.chmod(ip, 0o755)   # `ip link show` → already up
    script = ('set -uo pipefail\nENDPOINT_IP="%s"; ADOPTED_ENDPOINTS="%s"; LOCAL="%s"\n%s%s%s\n'
              'SELECTED=(%s); for n in "${SELECTED[@]}"; do IF_CMD[$n]=${n%%%%[0-9]*}; done\napply_node_switch\n'
              'for n in "${SELECTED[@]}"; do echo "EFF $n=${IF_ENDPOINT[$n]:-${ENDPOINT_IP:-}} (own=${IF_ENDPOINT[$n]:-})"; done\n') % (
        endpoint_ip, adopted, local, STUBS, node_fns.replace("/etc/swg-agent/config.json", cfg),
        setup.replace("/etc/swg-agent/config.json", cfg), " ".join(selected))
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=dict(os.environ, PATH=d + ":" + os.environ["PATH"]))
    return r.stdout + r.stderr

out = node(existing={"endpoint_host": "192.168.77.2", "interfaces": {"awg0": {}, "wg0": {}}})
check("re-run, node endpoint 192.168.77.2, interfaces without their own → both still dial 192.168.77.2",
      "EFF awg0=192.168.77.2 (own=)" in out and "EFF wg0=192.168.77.2 (own=)" in out and "10.0.2.15" not in out, out)
out = node(existing={"endpoint_host": "vpn.example.com", "interfaces": {"awg0": {"endpoint_host": "awg.example.com"}, "wg0": {}}})
check("…an interface's OWN endpoint stays its own; the rest keep the node's DNS name",
      "EFF awg0=awg.example.com" in out and "EFF wg0=vpn.example.com" in out, out)
out = node(existing={"endpoint_host": "192.168.77.2", "interfaces": {}}, endpoint_ip="203.0.113.7")
check("-endpoint / ENDPOINT_IP given on the re-run still wins over what the node had", "EFF awg0=203.0.113.7" in out, out)
out = node(endpoint_ip="192.168.77.3", adopted="awg0=192.168.77.3,wg0=wg.example.com")
check("docker → bare convert: each migrated interface keeps what its clients dial (ADOPTED_ENDPOINTS)",
      "EFF awg0=192.168.77.3 (own=192.168.77.3)" in out and "EFF wg0=wg.example.com (own=wg.example.com)" in out, out)
out = node()
check("fresh install, nothing configured → the default-route address, as before", "EFF awg0=10.0.2.15 (own=10.0.2.15)" in out, out)

print("\n[2] install-host.sh (master): an explicit HOST_ENDPOINT_IP is what adopted interfaces advertise")
hloop = H[H.index("  local _ep\n  for n in \"${SELECTED[@]}\"; do n=\"${n// /}\"; [ -n \"${IF_CMD[$n]:-}\" ]"):]
hloop = hloop[:hloop.index('    echo "    Used $(bb "$_ep") endpoint IP for $(col "$C_GREEN" "$n")"; done') + 80]
hloop = hloop[:hloop.index("; done") + 6] + "\n"
def host(given):
    script = ('%sHOST_ENDPOINT_IP="%s"\nSELECTED=(awg0)\nIF_CMD[awg0]=awg\nf(){\n%s}\nf\necho "EFF awg0=${IF_ENDPOINT[awg0]:-${HOST_ENDPOINT_IP:-}}"\n') % (
        STUBS, given, hloop)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return r.stdout + r.stderr
out = host("192.168.77.1")
check("HOST_ENDPOINT_IP=192.168.77.1 → the adopted awg0 advertises 192.168.77.1", "EFF awg0=192.168.77.1" in out and "10.0.2.15" not in out, out)
out = host("")
check("none given → the default-route address, as before", "EFF awg0=10.0.2.15" in out, out)

hre = H[H.index('if [ -z "$HOST_ENDPOINT_IP" ] && [ "$EXISTING_HOST" = yes ]; then'):]
hre = hre[:hre.index("\nfi\n") + 4]
def host_rerun(agent_ep=None, saved="", given=""):
    d = tempfile.mkdtemp(prefix="hre-"); cfg = os.path.join(d, "config.json")
    if agent_ep is not None:
        json.dump({"endpoint_host": agent_ep}, open(cfg, "w"))
    script = 'set -euo pipefail\nEXISTING_HOST=yes; ENDPOINT_SAVED="%s"; HOST_ENDPOINT_IP="%s"\n%s\necho "HOST_ENDPOINT_IP=$HOST_ENDPOINT_IP"\n' % (
        saved, given, hre.replace("/etc/swg-agent/config.json", cfg))
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return r.stdout + r.stderr
out = host_rerun(agent_ep="192.168.77.1", saved="")
check("master RE-install, nothing given: the node's own endpoint (agent config) is the default", "HOST_ENDPOINT_IP=192.168.77.1" in out, out)
out = host_rerun(agent_ep=None, saved="192.168.77.9")
check("…no agent config: install.conf's recorded HOST_ENDPOINT_IP", "HOST_ENDPOINT_IP=192.168.77.9" in out, out)
out = host_rerun(agent_ep="192.168.77.1", given="203.0.113.7")
check("…a value given now still wins", "HOST_ENDPOINT_IP=203.0.113.7" in out, out)

print("\n[3] the interface list: no 'No local interfaces yet' above 'Managing: …', and one spelling of WireGuard")
out = node(endpoint_ip="192.168.77.3", adopted="awg0=192.168.77.3,wg0=192.168.77.3", local="")
check("install-node: nothing in config.json yet, awg0 wg0 being managed → listed, not 'No local interfaces yet'",
      "No local interfaces yet" not in out and "Found 2 wg/awg/wdtt local interface(s)" in out and "OK Managing: awg0 wg0" in out, out)
check("…and the plain-WireGuard row says 'WireGuard'", re.search(r"wg0\s+WireGuard\s", out) is not None and "Wireguard" not in out, out)
out = node(existing={"endpoint_host": "192.168.77.2", "interfaces": {}}, selected=(), local="")
check("…a node with truly nothing still says 'No local interfaces yet'", "No local interfaces yet" in out, out)
hlist = H[H.index("  # + this run's SELECTED: config.json is written only AFTER this listing"):]
hlist = hlist[:hlist.index('  _l="$(printf \'%s\\n\' ${SELECTED[@]+')] if "# + this run's SELECTED" in H else ""
if not hlist:   # perturbed: the comment is still there, the listing is the old one — take it from its first line
    hlist = H[H.index("  while IFS= read -r _l; do [ -n \"$_l\" ] && _loc+=(\"$_l\"); done < <(local_ifaces)"):]
    hlist = hlist[:hlist.index('  _l="$(printf \'%s\\n\' ${SELECTED[@]+')]
script = ('%sLOCAL=""\nSELECTED=(awg0)\nIF_CMD[awg0]=awg\n%sf(){\n  local _l _li _lls _lsub; local -a _loc=()\n%s}\nf\n') % (
    STUBS, fn(H, "iface_row").replace("iface_row", "iface_row", 1) + fn(C, "proto_label"), hlist)
r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
check("install-host: the same listing, the same fix", "No local interfaces yet" not in r.stdout and "local interface(s)" in r.stdout, r.stdout + r.stderr)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
