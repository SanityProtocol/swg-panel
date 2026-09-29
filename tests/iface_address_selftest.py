#!/usr/bin/env python3
"""Self-test — which of an interface's addresses is ITS address (the v6-first misread).

`Address = fd42::1/64, 10.8.0.1/24` is a legal wg-quick line, and every reader took its first entry. So a client
interface read as `fd42::/64`: `_iface_is_mesh` took the /64 for a point-to-point link — no egress MASQUERADE, no FORWARD
accept, no MSS clamp — a network behind a peer on it entered the ACL unjudged, the agent refused every peer add, the
panel was shown the IPv6 address, and a key restore wrote the first entry back as the whole Address line, erasing the
IPv4 address every client uses.

  [1] one grammar, twice: the `Address` a conf parses to, and `conf_v4_address`, agree between swg-noded and swg-agent
      over every shape — v4 only, v4 first, v6 first, several lines, v6 only, a trailing comment, none, a [Peer].
  [2] nothing moves where the old readers were right: a v4-only and a single-line v4-first conf give the same subnet,
      mesh verdict, snapshot address/subnet and agent network as frozen copies of the pre-fix readers.
  [3] v6 first: an IPv4 subnet, NOT mesh, a baseline MASQUERADE, IPv4 in the snapshot meta, the agent's network (and its
      next free address) IPv4, the probe source IPv4, the networks members read — on one line and on two.
  [4] the mesh test is per family: /31 and /32 in v4, /127 and /128 in v6; a v6 /64 is not a link.
  [5] a key restore puts back EVERY address: the backup keeps them all, and the agent writes a replaced key once — a
      two-line Address becomes one line holding both, never two lines holding both.
  [6] v6-only reads as before where it matters: no IPv4 subnet for the IPv4 readers (they skipped it as "mesh" before,
      so the egress outcome is unchanged), and the snapshot and the agent still see its address.

Hermetic. Run: python3 tests/iface_address_selftest.py     (0 = pass)
     --perturb   has swg-noded take the first entry again and expects RED on [1] and [3].
"""
import importlib.machinery, importlib.util, ipaddress, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
AGENT = os.environ.get("SWG_AGENT") or os.path.join(ROOT, "swg-agent")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def load(name, path):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m
N = load("swgnoded", NODED)
A = load("swgagent", AGENT)
if PERTURB:
    N.conf_v4_address = lambda address: str(address or "").split(",")[0].strip()
N.derive_pubkey = lambda cmd, priv: "PUB"          # no `wg` binary in a hermetic test

TMP = tempfile.mkdtemp(prefix="ifaddr-")
def conf(text, name="wg0"):
    p = os.path.join(TMP, "%s-%d.conf" % (name, len(os.listdir(TMP))))
    with open(p, "w") as f:
        f.write(text)
    return {"interfaces": {name: {"conf": p}}}, p

# ── frozen: the readers exactly as they were before the fix ──────────────────────────────────────────────────────────
def OLD_parse(conf_text):
    info, in_iface = {}, False
    for line in conf_text.splitlines():
        s = line.strip()
        if s.startswith("["):
            in_iface = (s.lower() == "[interface]")
            continue
        if in_iface and "=" in s and not s.startswith("#"):
            k, v = s.split("=", 1)
            info[k.strip()] = v.strip()
    return info
def OLD_iface_subnet(text):
    m = re.search(r"(?im)^\s*Address\s*=\s*([^\s,]+)", text)
    if not m:
        return ""
    try:
        return str(ipaddress.ip_network(m.group(1), strict=False))
    except Exception:
        return ""
def OLD_mesh(subnet):
    try:
        return int(str(subnet).rsplit("/", 1)[1]) >= 31
    except Exception:
        return False
def OLD_first(text):
    return OLD_parse(text).get("Address", "").split(",")[0].strip()

IF = "[Interface]\nListenPort = 51820\n%s\n\n[Peer]\nPublicKey = k\nAllowedIPs = 10.8.0.2/32\n"
SHAPES = [   # (name, conf, its IPv4 address, every address in order)
    ("v4 only", IF % "Address = 10.8.0.1/24", "10.8.0.1/24", ["10.8.0.1/24"]),
    ("v4 first", IF % "Address = 10.8.0.1/24, fd42::1/64", "10.8.0.1/24", ["10.8.0.1/24", "fd42::1/64"]),
    ("v6 first", IF % "Address = fd42::1/64, 10.8.0.1/24", "10.8.0.1/24", ["fd42::1/64", "10.8.0.1/24"]),
    ("v6 first, no spaces", IF % "Address=fd42::1/64,10.8.0.1/24", "10.8.0.1/24", ["fd42::1/64", "10.8.0.1/24"]),
    ("two lines, v6 first", IF % "Address = fd42::1/64\nAddress = 10.8.0.1/24", "10.8.0.1/24", ["fd42::1/64", "10.8.0.1/24"]),
    ("two lines, v4 first", IF % "Address = 10.8.0.1/24\nAddress = fd42::1/64", "10.8.0.1/24", ["10.8.0.1/24", "fd42::1/64"]),
    ("v6 only", IF % "Address = fd42::1/64", "", ["fd42::1/64"]),
    ("a trailing comment", IF % "Address = fd42::1/64, 10.8.0.1/24 # office", "10.8.0.1/24", None),
    ("no Address", IF % "MTU = 1280", "", []),
    ("an Address under [Peer] never counts", "[Interface]\nAddress = fd42::1/64\n[Peer]\nPublicKey = k\nAddress = 10.9.9.9/24\n", "", ["fd42::1/64"]),
]
entries = lambda v: [a.strip() for a in str(v or "").split(",") if a.strip()]

# ── [1] ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[1] one grammar, in both programs")
for name, text, v4, addrs in SHAPES:
    nv, av = N.parse_interface_section(text).get("Address", ""), A.parse_interface_section(text).get("Address", "")
    check("%s: the parsed Address is the same in swg-noded and swg-agent%s" % (name, "" if addrs is None else ", every entry in order"),
          nv == av and (addrs is None or entries(nv) == addrs), (nv, av))
    check("%s: conf_v4_address → %r in both" % (name, v4), N.conf_v4_address(nv) == A.conf_v4_address(av) == v4,
          (N.conf_v4_address(nv), A.conf_v4_address(av)))

# ── [2] ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] where the old readers were right, nothing moves")
for name, text in (("v4 only", IF % "Address = 10.8.0.1/24"), ("v4 first", IF % "Address = 10.8.0.1/24, fd42::1/64"),
                   ("a mesh link /31", "[Interface]\nAddress = 10.200.0.0/31\nTable = off\n"),
                   ("a bare /32 address", IF % "Address = 10.8.0.9")):
    cfg, _p = conf(text)
    sub = N._iface_subnet(cfg, "wg0")
    meta = N.build_meta([], text, "", [])
    check("%s: _iface_subnet unchanged (%r)" % (name, OLD_iface_subnet(text)), sub == OLD_iface_subnet(text), sub)
    check("%s: the mesh verdict unchanged" % name, N._iface_is_mesh(cfg, "wg0", sub) == (OLD_mesh(sub) or "Table = off" in text))
    old_addr = OLD_first(text)
    try:
        old_sub = str(ipaddress.ip_network(old_addr, strict=False)) if "/" in old_addr else None
    except ValueError:
        old_sub = None
    check("%s: the snapshot's address/subnet unchanged" % name, (meta["address"], meta["subnet"]) == (old_addr or None, old_sub),
          (meta["address"], meta["subnet"]))
    check("%s: the agent's network unchanged" % name, A.iface_net(A.parse_interface_section(text)) == ipaddress.ip_interface(old_addr))

# ── [3] ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] v6 first — the interface is its IPv4 half")
for name, line in (("one line", "Address = fd42::1/64, 10.8.0.1/24"), ("two lines", "Address = fd42::1/64\nAddress = 10.8.0.1/24")):
    text = IF % line
    cfg, _p = conf(text)
    sub = N._iface_subnet(cfg, "wg0")
    check("%s: _iface_subnet is 10.8.0.0/24 (was %r)" % (name, OLD_iface_subnet(text)), sub == "10.8.0.0/24", sub)
    mesh = N._iface_is_mesh(cfg, "wg0", sub)
    check("%s: NOT a mesh link" % name, not mesh)
    check("%s: so it gets the baseline MASQUERADE" % name,
          N._egress_des("", "", "", "eth0", sub, [], mesh) == ("MASQUERADE", "eth0", ""))
    meta = N.build_meta([], text, "", [])
    check("%s: the panel is shown 10.8.0.1/24 · 10.8.0.0/24" % name, (meta["address"], meta["subnet"]) == ("10.8.0.1/24", "10.8.0.0/24"),
          (meta["address"], meta["subnet"]))
    ainfo = A.parse_interface_section(text)
    check("%s: the agent's network is 10.8.0.1/24, and its next free address 10.8.0.3" % name,
          A.iface_net(ainfo) == ipaddress.ip_interface("10.8.0.1/24")
          and A.next_free_ip(ainfo, [{"allowed_ips": "10.8.0.2/32"}]) == "10.8.0.3")
    check("%s: the reachability test sends from 10.8.0.1" % name, N._iface_own_addr(cfg, "wg0") == "10.8.0.1")
    try:
        mem = N._net_members(cfg, {"wg0": [{"public_key": "k", "allowed_ips": "10.8.0.2/32,192.168.50.0/24"}]})
    except Exception as e:          # the first-entry reader compares a v4 member with the v6 /64 and raises: a FAIL, not the end
        mem = "raised %r" % e
    check("%s: a network behind a peer on it is read, so it is judged" % name, mem == {"wg0": {"192.168.50.0/24": ["k"]}}, mem)

# ── [4] ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] point-to-point, per family")
cfg, _p = conf(IF % "Address = 10.8.0.1/24")
for sub, want in (("10.200.0.0/31", True), ("10.200.0.1/32", True), ("10.200.0.0/30", False), ("10.8.0.0/24", False),
                  ("fd00::/127", True), ("fd00::1/128", True), ("fd00::/126", False), ("fd42::/64", False),
                  ("", False), ("junk", False), ("10.8.0.9", False)):
    check("%-14r → %s" % (sub, "mesh" if want else "not mesh"), N._iface_is_mesh(cfg, "wg0", sub) == want)
check("the swg_ prefix is mesh whatever the subnet", N._iface_is_mesh(cfg, "swg_ab12", "10.8.0.0/24"))
cto, _p = conf("[Interface]\nAddress = 10.8.0.1/24\nTable = off\n")
check("…and so is Table = off", N._iface_is_mesh(cto, "wg0", "10.8.0.0/24"))

# ── [5] ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] a key restore puts back every address")
for name, line in (("one line, v6 first", "Address = fd42::1/64, 10.8.0.1/24"),
                   ("two lines, v6 first", "Address = fd42::1/64\nAddress = 10.8.0.1/24")):
    text = "[Interface]\nPrivateKey = OLD\n%s\nListenPort = 51820\n\n[Peer]\n# office\nPublicKey = k\nAllowedIPs = 10.8.0.2/32\n" % line
    bak = N.harvest_iface_backup(text)
    check("%s: the backup keeps both addresses (it kept %r)" % (name, OLD_first(text)),
          entries(bak["address"]) == ["fd42::1/64", "10.8.0.1/24"], bak)
    _cfg, path = conf(text)
    A.set_iface_fields_in_conf(path, {"PrivateKey": "NEW", "Address": bak["address"], "ListenPort": "51820"})
    out = open(path).read()
    iface_part = out.split("[Peer]")[0]
    check("%s: restored — ONE Address line holding both, in order" % name,
          len(re.findall(r"(?im)^\s*Address\s*=", iface_part)) == 1
          and entries(A.parse_interface_section(out).get("Address")) == ["fd42::1/64", "10.8.0.1/24"], out)
    check("%s: …the new key written once, the port kept, the peer untouched" % name,
          iface_part.count("PrivateKey") == 1 and "PrivateKey = NEW" in out and "ListenPort = 51820" in out
          and out.split("[Peer]")[1] == "\n# office\nPublicKey = k\nAllowedIPs = 10.8.0.2/32\n", out)
    check("%s: …and the node reads it back as 10.8.0.0/24" % name, N._iface_subnet({"interfaces": {"wg0": {"conf": path}}}, "wg0") == "10.8.0.0/24")

# ── [6] ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[6] v6 only — nothing for the IPv4 readers, the address still shown")
text = IF % "Address = fd42::1/64"
cfg, _p = conf(text)
check("_iface_subnet is empty (it was fd42::/64, which read as mesh — skipped by egress either way)", N._iface_subnet(cfg, "wg0") == "")
meta = N.build_meta([], text, "", [])
check("the snapshot still shows fd42::1/64 · fd42::/64", (meta["address"], meta["subnet"]) == ("fd42::1/64", "fd42::/64"), meta)
check("the agent's network is still fd42::1/64", A.iface_net(A.parse_interface_section(text)) == ipaddress.ip_interface("fd42::1/64"))
check("the probe has no source on it", N._iface_own_addr(cfg, "wg0") == "")

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
