#!/usr/bin/env python3
"""Self-test — A DOCKER NODE'S nft TABLES STAY READABLE BY THE HOST'S OWN nft, AND GO WITH THE NODE (round 12c, R27).

A host-networking Docker node writes its nft tables into the HOST's kernel with the image's nft (1.1.3). nft ≥ 1.1 records a
set or map declared with a plain single key — `type ipv4_addr`, `type ifname`, `type inet_service` — as a key "value"
expression in the set's userdata, and Debian 12's nft 1.0.6 calls that expression's parse_udata, which 1.0.6 does not have:
a NULL call in set_make_key() (src/netlink.c:893), so `nft list ruleset`, `nft list tables`, `nft delete table` segfaulted on
the host for as long as the node ran, and a full uninstall read nothing, deleted nothing, said "✓ swg datapath objects
removed" and left swg_reach — a prerouting hook guarding the old tunnel subnets — until a reboot. Declared by the expression
it is matched with (`typeof ip daddr`) the same key reads everywhere: measured, written by 1.0.2, 1.0.6, 1.0.9 and 1.1.3 and
read by 1.0.6; a concatenated key already did.

  [1] swg-noded declares every single-key set and map by expression (`typeof ip daddr|ip saddr|iifname|th dport`), never by a
      plain single `type`; concatenations and chain hooks keep `type`
  [2] docker/node-entrypoint.sh's nft_typeof_migrate, lifted and run under `sh -eu` against a stub nft: a swg* table an earlier
      image wrote with plain keys is re-loaded in ONE transaction — `delete table` first, then the table exactly as listed,
      only the keys of the sets swg-noded declared re-spelled, each by the expression it is matched with (a source-keyed set
      `typeof ip saddr`, round 12d) — elements, timeouts, counters, rules, concatenations untouched; a `meter`'s own set
      (swg_mech's psc_*, which every nft reads) is neither counted nor touched, and a table holding only that is not
      re-loaded; a clean table, another program's table, no nft, a ruleset that cannot be read → nothing; a re-load nft
      refuses → said, the table left as it was; it runs before swg-noded starts
  [3] uninstall.sh's _node_nft_sweep (rm_docker_node, before `docker rm`): the container stopped FIRST (a running swg-noded
      re-creates a table within one sync), then its interfaces deleted (round 12e: a kernel wg0 outlives `docker stop` and
      forwards with whatever tables are left), then every swg* table deleted in one batch by the node's own image on the host's
      network, each named in one line; another program's table never; a dry run touches nothing; a failed read is said and
      the host-side sweep still runs
  [4] rm_node_netobjects: a `nft list tables` that fails (139: the crash) is said — the ruleset could not be read, what that
      leaves and the remedy — goes to the summary's "Asked for but NOT removed", and "✓ swg datapath objects removed" is
      never printed after it; a readable ruleset is swept and ✓'d as before
  [4b] the docker → bare convert's switch (lib/common.sh lc_teardown_docker, round 12d, R29): when the host's own nft cannot
      read the ruleset (read in a substitution: its crash prints nothing), the node's own nft sweep runs before the container
      is removed — stopped, ITS INTERFACES DELETED (round 12e, R31-X3: a kernel wg0 left up forwarded ~0.3 s with no table),
      then one batch by its image, said in one line, the same batch uninstall.sh's twin sends; an interface that cannot be
      deleted (or no `ip`) leaves the tables enforcing (fail closed); a ruleset the host reads is left exactly as before (it
      keeps enforcing across the switch); no container → nothing; its own nft failing is said, and the switch goes on
  [5] CHANGELOG.md and CHANGELOG.ru.md say it, the convert included

Run: python3 tests/nft_host_readable_selftest.py        (0 = pass)
     --perturb   seventeen plants, each on its own — each must turn its own check red
"""
import os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
FILES = (("NODED", "swg-noded"), ("ENTRY", "docker/node-entrypoint.sh"), ("UNINST", "uninstall.sh"), ("COMMON", "lib/common.sh"))
PATHS = {k: os.environ.get("SWG_NH_" + k) or os.path.join(ROOT, f) for k, f in FILES}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PATHS.items()}

PLANTS = [
    ("type", "NODED", 'dmap = ("  map dmap_%s { typeof ip daddr : verdict; flags interval;', 'dmap = ("  map dmap_%s { type ipv4_addr : verdict; flags interval;',
     "[1] swg-noded declares every single-key set and map by expression, never by a plain single `type`"),
    ("call", "ENTRY", "\nnft_typeof_migrate\n", "\n: nft_typeof_migrate\n", "[2] …and it runs before swg-noded starts"),
    ("sub", "ENTRY", 'if (k != "") { sub(/type [a-z0-9_]+/, "typeof " k); m++;', 'if (k != "") { m++;',
     "[2] a table with plain keys is re-loaded in ONE transaction, its single keys re-spelled"),
    ("saddr", "ENTRY", 's ~ /^a[0-9]+n[0-9]+_/) return "ip saddr"', 's ~ /^a[0-9]+n[0-9]+_/) return "ip daddr"',
     "[2] a table with plain keys is re-loaded in ONE transaction, its single keys re-spelled"),
    ("decide", "ENTRY", "m++; if (nm !~ /^psc_/) n++", "m++; n++",
     "[2] a meter's own set (psc_*) is neither counted nor touched — a table holding only that is not re-loaded"),
    ("meter", "ENTRY", 's ~ /^pscf?_/ ||', 's ~ /^pscf_/ ||',
     "[2] …but a table re-loaded for another set declares the meter's set again, re-spelled `typeof ip saddr` (plain, the host cannot read it)"),
    ("twin", "NODED", "set doh_seen { typeof ip saddr;", "set doh_seen { typeof ip daddr;",
     "[2] …each re-spelled with the expression swg-noded declares that set with (a meter's set: the key its meter counts by)"),
    ("delete", "ENTRY", "if { printf 'delete table %s %s\\n' \"$_fam\" \"$_t\"; printf", "if { printf",
     "[2] a table with plain keys is re-loaded in ONE transaction, its single keys re-spelled"),
    ("sweep", "UNINST", '  _node_nft_sweep "$_ifn"             # stopped, its interfaces', '  :                                   # stopped, its interfaces',
     "[3] rm_docker_node sweeps the node's tables with its own nft BEFORE `docker rm`"),
    ("uorder", "UNINST", '  for _n in ${1:-}; do _rm_host_iface "$_n"; done\n', "",
     "[3] the container is stopped first, then its interfaces deleted, then every swg* table in one batch by the node's own image"),
    ("stop", "UNINST", "  docker stop -t 10 swg-node >/dev/null 2>&1 || true\n", "",
     "[3] the container is stopped first, then its interfaces deleted, then every swg* table in one batch by the node's own image"),
    ("rc", "UNINST", '      if [ "$_nftrc" -ne 0 ]; then', '      if false; then',
     "[4] a `nft list tables` that crashes is said, goes to NOT removed, and no ✓ follows"),
    ("convert", "COMMON", '  lc_node_nft_sweep "$d"   # its nft tables the host cannot read', '  :                        # its nft tables the host cannot read',
     "[4b] the docker → bare switch: stopped, its interfaces deleted, THEN its tables in one batch by its own image, then the container removed"),
    ("iorder", "COMMON", '  left="$(lc_del_node_ifaces "$d")"\n', '  left=""\n',
     "[4b] the docker → bare switch: stopped, its interfaces deleted, THEN its tables in one batch by its own image, then the container removed"),
    ("open", "COMMON", '  if [ -n "$left" ]; then\n', '  if false; then\n',
     "[4b] an interface that cannot be deleted leaves the tables enforcing (fail closed) — said, naming it — and the switch goes on"),
    ("readable", "COMMON", "  command -v nft >/dev/null 2>&1 && tl=\"$(nft list tables 2>/dev/null)\" && return 0", "  :",
     "[4b] a ruleset the host reads is left exactly as before: nothing stopped, nothing deleted — it keeps enforcing across the switch"),
    ("quiet", "COMMON", "&& tl=\"$(nft list tables 2>/dev/null)\" && return 0", "&& nft list tables >/dev/null 2>&1 && return 0",
     "[4b] …when the host's own nft cannot read the ruleset (it crashes: no \"Segmentation fault\" line reaches the operator), said in one line; another program's table never"),
]
if "--perturb" in sys.argv:
    bad = 0
    for name, key, old, new, must in PLANTS:
        src = SRC[key]
        if src.count(old) != 1:
            print("  %-7s STALE ANCHOR (%d) — this plant would plant nothing" % (name, src.count(old))); bad += 1; continue
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix="-" + name); f.write(src.replace(old, new)); f.close()
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{"SWG_NH_" + key: f.name}), capture_output=True, text=True, timeout=300)
        os.unlink(f.name)
        red = ("FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-7s %s" % (name, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")))
        bad += not red
    print("%d plants, %d caught" % (len(PLANTS), len(PLANTS) - bad))
    sys.exit(1 if bad else 0)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:900]) if detail and not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)

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

TOOLS = ("bash", "sh", "dash", "cat", "grep", "sed", "tr", "awk", "tail", "chmod", "mkdir", "cp", "rm", "env", "printf")
def sandbox():
    t = tempfile.mkdtemp(prefix="nfthr-")
    b = os.path.join(t, "bin"); os.makedirs(b)
    for tool in TOOLS:
        w = shutil.which(tool)
        if w:
            os.symlink(w, os.path.join(b, tool))
    return t, b
def put(path, text):
    open(path, "w").write(text); os.chmod(path, 0o755)

# ── [1] the declarations ─────────────────────────────────────────────────────────────────────────────────────────────
print("[1] swg-noded's set and map declarations")
N = SRC["NODED"]
code = "\n".join(l for l in N.split("\n") if not l.lstrip().startswith("#"))
plain = re.findall(r"(?:set|map) [A-Za-z0-9_%{}]+ \{ type ([a-z0-9_]+)(?: : verdict)?;", code) \
      + re.findall(r'"\{ type ([a-z0-9_]+)(?: : verdict)?;', code) + re.findall(r'\("\{ type ([a-z0-9_]+);', code)
plain = [x for x in plain if x != "filter"]
decls = re.findall(r"(?:set|map) [A-Za-z0-9_%{}]+ \{ (type|typeof) ([^;]+);", code) + re.findall(r'"\{ (type|typeof) ([^;]+);', code)
single_type = [d for k, d in decls if k == "type" and " . " not in d and not d.startswith("filter hook")]
typeofs = sorted({d.split(" : ")[0] for k, d in decls if k == "typeof"})
check("[1] swg-noded declares every single-key set and map by expression, never by a plain single `type`",
      not plain and not single_type and len([1 for k, _ in decls if k == "typeof"]) >= 14, (plain, single_type, len(decls)))
check("[1] …each by an expression measured to read on nft 1.0.2 / 1.0.6 / 1.0.9 / 1.1.3", set(typeofs) <= {"ip daddr", "ip saddr", "iifname", "th dport"}
      and {"ip daddr", "ip saddr", "iifname", "th dport"} <= set(typeofs), typeofs)
concats = [d for k, d in decls if k == "type" and " . " in d]
check("[1] …while a concatenation keeps its `type` (it read everywhere before)", len(concats) >= 4, concats)

# ── [2] the entrypoint's migration ───────────────────────────────────────────────────────────────────────────────────
print("\n[2] docker/node-entrypoint.sh: nft_typeof_migrate, driven under sh -eu")
E = SRC["ENTRY"]
i_awk = E.find("\nNFT_TYPEOF_AWK='")
assert i_awk > 0, "cannot lift NFT_TYPEOF_AWK"
AWKDEF = E[i_awk + 1:E.index("}'\n", i_awk) + 3]
MIG = AWKDEF + fn(E, "nft_typeof_migrate")

# The tables as nft 1.1.3 (the image's) lists them. `@T(<datatype>|<expression>)` is `type <datatype>` as an image older than
# e72529b declared the set, and `typeof <expression>` once re-declared — the expression swg-noded declares that set with now
# (TWINS below holds each one to swg-noded's own declaration). A line without the marker must come back exactly as listed.
def T(text, new):
    return re.sub(r"@T\(([^|)]+)\|([^)]+)\)", (lambda m: "typeof " + m.group(2)) if new else (lambda m: "type " + m.group(1)), text)
REACH = """table inet swg_reach {
\tcounter gc {
\t\tpackets 3 bytes 180
\t}

\tcounter c776730 {
\t\tpackets 7 bytes 420
\t}

\tset guard {
\t\t@T(ipv4_addr|ip daddr)
\t\tflags interval
\t\telements = { 10.50.0.0/24, 10.51.0.0/24 }
\t}

\tset f0_b {
\t\ttype ifname . ipv4_addr
\t\telements = { "wg0" . 10.50.0.2 }
\t}

\tset f0n0_b {
\t\t@T(ipv4_addr|ip saddr)
\t\tflags interval
\t\telements = { 10.50.0.64/26 }
\t}

\tmap dmap_b {
\t\t@T(ipv4_addr|ip daddr) : verdict
\t\tflags interval
\t\telements = { 10.50.0.1 : accept, 10.50.0.3-10.50.0.255 : jump n1_b }
\t}

\tchain z0i0_b {
\t\tiifname . ip saddr @f0_b accept
\t\tiifname "wg0" ip saddr @f0n0_b accept
\t\tcounter name "c776730" drop
\t}

\tchain n1_b {
\t\tcounter name "c776730" drop
\t}

\tchain sel {
\t\tip daddr vmap @dmap_b
\t}

\tchain pre {
\t\ttype filter hook prerouting priority mangle - 4; policy accept;
\t\tct direction reply accept
\t\tip daddr != @guard accept
\t\tjump sel
\t\tip daddr @guard counter name "gc" drop
\t}
}
"""
SHARE = """table inet swg_share {
\tset guard {
\t\t@T(ipv4_addr|ip daddr)
\t\tflags interval
\t\telements = { 10.50.0.9 }
\t}

\tset a0_b {
\t\ttype ifname . ipv4_addr
\t\tflags timeout
\t\telements = { "wg0" . 10.50.0.2 timeout 1d expires 23h59m }
\t}

\tset a0n0_b {
\t\t@T(ipv4_addr|ip saddr)
\t\tflags interval,timeout
\t\telements = { 10.50.0.64/26 timeout 1d expires 23h59m }
\t}

\tmap nets_b {
\t\t@T(ipv4_addr|ip daddr) : verdict
\t\tflags interval
\t\telements = { 192.168.1.0/24 : jump p0_b }
\t}

\tchain p0_b {
\t\tiifname . ip saddr @a0_b accept
\t\tiifname "wg0" ip saddr @a0n0_b accept
\t\tcounter packets 0 bytes 0 drop
\t}

\tchain pre {
\t\ttype filter hook prerouting priority mangle - 3; policy accept;
\t\tip daddr != @guard accept
\t\tip daddr vmap @nets_b
\t}
}
"""
SMART = """table inet swg_smart {
\tset cat_ru {
\t\t@T(ipv4_addr|ip daddr)
\t\tflags interval
\t\tauto-merge
\t\telements = { 5.3.0.0/16, 77.88.0.0/18 }
\t}

\tset catl_ru {
\t\t@T(ipv4_addr|ip daddr)
\t\tflags timeout
\t\ttimeout 1h
\t\telements = { 87.250.250.242 timeout 1h expires 59m1s }
\t}

\tset lg {
\t\t@T(ifname|iifname)
\t\telements = { "wg0" }
\t}

\tset ar {
\t\t@T(ipv4_addr|ip saddr)
\t\tflags interval
\t\tauto-merge
\t\telements = { 10.50.0.0/24 }
\t}

\tset cln {
\t\t@T(ipv4_addr|ip daddr)
\t\tflags interval
\t\tauto-merge
\t\telements = { 10.50.0.0/24 }
\t}

\tchain prerouting {
\t\ttype filter hook prerouting priority mangle; policy accept;
\t\tiifname @lg ip saddr @ar ip daddr != @cln ip daddr { @cat_ru, @catl_ru } meta mark set 0x00000065 counter packets 4 bytes 240
\t}
}
"""
DOH = """table inet swg_doh {
\tset doh4 {
\t\t@T(ipv4_addr|ip daddr)
\t\tflags interval
\t\tauto-merge
\t\telements = { 1.1.1.1, 8.8.8.8 }
\t}

\tset doh_seen {
\t\t@T(ipv4_addr|ip saddr)
\t\tsize 65535
\t\tflags dynamic,timeout
\t\tcounter
\t\ttimeout 10m
\t\telements = { 10.50.0.2 counter packets 1 bytes 60 expires 9m58s }
\t}

\tchain pre {
\t\ttype filter hook prerouting priority mangle - 5; policy accept;
\t\tip daddr @doh4 tcp dport { 443, 853 } add @doh_seen { ip saddr } counter packets 1 bytes 60 reject with tcp reset
\t}
}
"""
TURN = """table inet swg_turn {
\tset ports {
\t\t@T(inet_service|th dport)
\t\telements = { 56001 }
\t}

\tset peers {
\t\ttype ipv4_addr . inet_service
\t\tsize 65535
\t\tflags dynamic,timeout
\t\ttimeout 3m
\t\telements = { 203.0.113.9 . 56001 expires 2m51s }
\t}

\tchain pre {
\t\ttype filter hook prerouting priority mangle; policy accept;
\t\tmeta l4proto { tcp, udp } th dport @ports fib daddr type local ct direction original ct state established update @peers { ip saddr . th dport }
\t}
}
"""
# swg_mech: the port-scan rule's `meter` makes psc_<subnet> itself — listed `type ipv4_addr` by every nft, and read by 1.0.6 as
# the meter wrote it (R29). MECH_TIP is the table as this image's swg-noded builds it; MECH_OLD as an older one did (pscf_ plain).
MECH = """table inet swg_mech {
\tset mps_10_50_0_0_24 {
\t\ttype inet_proto . inet_service
\t\tflags interval
\t\telements = { tcp . 25, udp . 443 }
\t}

\tset pscf_10_50_0_0_24 {
\t\t%s
\t\tsize 65535
\t\tflags dynamic,timeout
\t\telements = { 10.50.0.2 timeout 10m expires 9m58s }
\t}

\tset psc_10_50_0_0_24 {
\t\t%s
\t\tsize 65535
\t\tflags dynamic
\t}

\tchain pre {
\t\ttype filter hook prerouting priority mangle - 10; policy accept;
\t\tip saddr 10.50.0.0/24 fib daddr type != local meta l4proto . th dport @mps_10_50_0_0_24 counter packets 5 bytes 300 drop
\t\tip saddr 10.50.0.0/24 fib daddr type != local ct state new add @psc_10_50_0_0_24 { ip saddr limit rate over 200/second burst 5 packets } add @pscf_10_50_0_0_24 { ip saddr timeout 10m } counter packets 594 bytes 35640 drop
\t}
}
"""
MECH_TIP = MECH % ("typeof ip saddr", "type ipv4_addr")
MECH_OLD = MECH % ("@T(ipv4_addr|ip saddr)", "@T(ipv4_addr|ip saddr)")
OTHER = "table inet other_tool {\n\tset s {\n\t\ttype ipv4_addr\n\t}\n}\n"

# The expression each set is re-spelled with is the one swg-noded declares that set with now — a meter's set, the key its meter
# counts by: the set name in the fixtures → (the expression, where swg-noded says so).
TWINS = {
    "guard":    ("ip daddr", r'set guard \{ typeof ip daddr;'),
    "f0n0_b":   ("ip saddr", r'set f%dn%d_%s \{ typeof ip saddr;'),
    "dmap_b":   ("ip daddr", r'map dmap_%s \{ typeof ip daddr : verdict;'),
    "a0n0_b":   ("ip saddr", r'set a%dn%d_%s \{ typeof ip saddr;'),
    "nets_b":   ("ip daddr", r'map nets_%s \{ typeof ip daddr : verdict;'),
    "cat_ru":   ("ip daddr", r'return "cat_" \+[\s\S]*SMART_NFT_TABLE, _smart_setname\(c\), "\{ typeof ip daddr;'),
    "catl_ru":  ("ip daddr", r'return "catl_" \+[\s\S]*SMART_NFT_TABLE, _smart_learnsetname\(c\),\s*"\{ typeof ip daddr;'),
    "lg":       ("iifname", r'"lg": \("\{ typeof iifname;'),
    "ar":       ("ip saddr", r'"ar": \("\{ typeof ip saddr;'),
    "cln":      ("ip daddr", r'"cln": \("\{ typeof ip daddr;'),
    "doh4":     ("ip daddr", r'set doh4 \{ typeof ip daddr;'),
    "doh_seen": ("ip saddr", r'set doh_seen \{ typeof ip saddr;'),
    "ports":    ("th dport", r'TURN_CAP_TABLE, "ports", "\{ typeof th dport;'),
    "pscf_10_50_0_0_24": ("ip saddr", r'return "pscf_" \+[\s\S]*_mech_flagged\(S\) \+ " \{ typeof ip saddr;'),
    "psc_10_50_0_0_24":  ("ip saddr", r'return "psc_" \+[\s\S]*meter " \+ _mech_meter\(S\) \+[^\n]*\n\s*" \{ ip saddr limit rate'),
}
NFT_STUB = r'''#!/bin/sh
echo "nft $*" >> "$LOG"
case "$*" in
  "list tables") [ -n "${LIST_RC:-}" ] && exit "$LIST_RC"; cat "$FIX/tables"; exit 0;;
  "list table "*) [ -f "$FIX/t.$3.$4" ] && { cat "$FIX/t.$3.$4"; exit 0; }; exit 1;;
  "-f -") n=0; for f in "$FIX"/load*; do [ -e "$f" ] && n=$((n + 1)); done; cat > "$FIX/load$n"; exit "${LOAD_RC:-0}";;
esac
exit 0
'''
DEFAULT = [("ip", "filter", None), ("inet", "swg_reach", T(REACH, False)), ("inet", "swg_share", T(SHARE, True)),
           ("inet", "swg_smart", T(SMART, False)), ("inet", "swg_doh", T(DOH, False)), ("inet", "swg_turn", T(TURN, False)),
           ("inet", "swg_mech", MECH_TIP), ("inet", "other_tool", OTHER)]
def entry_run(tables=DEFAULT, nft=True, **env):
    t, b = sandbox()
    fix = os.path.join(t, "fix"); os.makedirs(fix)
    open(os.path.join(fix, "tables"), "w").write("".join("table %s %s\n" % (f, n) for f, n, _ in tables))
    for f, n, body in tables:
        if body is not None:
            open(os.path.join(fix, "t.%s.%s" % (f, n)), "w").write(body)
    if nft:
        put(os.path.join(b, "nft"), NFT_STUB)
    script = "set -eu\nlog(){ echo \"LOG $*\"; }\n%snft_typeof_migrate\necho END\n" % MIG
    e = {"PATH": b, "LOG": os.path.join(t, "log"), "FIX": fix}
    e.update({k: str(v) for k, v in env.items()})
    sh_ = shutil.which("dash") or shutil.which("sh")
    r = subprocess.run([sh_, "-c", script], capture_output=True, text=True, env=e, timeout=60)
    loads = [open(os.path.join(fix, f)).read() for f in sorted(os.listdir(fix)) if f.startswith("load")]
    log = open(e["LOG"]).read() if os.path.exists(e["LOG"]) else ""
    return r.returncode, r.stdout + r.stderr, loads, log
def keys_of(text):   # {set name: its key line} of a listing
    return dict(re.findall(r"\t(?:set|map) (\S+) \{\n\t\t(type[^\n]*)\n", text))

rc, out, loads, log = entry_run()
want = ["delete table inet %s\n%s" % (n, T(x, True)) for n, x in (("swg_reach", REACH), ("swg_smart", SMART), ("swg_doh", DOH), ("swg_turn", TURN))]
check("[2] a table with plain keys is re-loaded in ONE transaction, its single keys re-spelled",
      rc == 0 and "END" in out and loads == want, (rc, out, [l[:300] for l in loads], log))
got = {k: v for l in loads for k, v in keys_of(l).items()}
src_keyed = {k: got.get(k) for k in ("f0n0_b", "ar", "doh_seen")}
check("[2] …each by the expression swg-noded declares it with — a source-keyed set `typeof ip saddr`, never `ip daddr`",
      src_keyed == dict.fromkeys(src_keyed, "typeof ip saddr") and got.get("guard") == "typeof ip daddr"
      and got.get("dmap_b") == "typeof ip daddr : verdict" and got.get("lg") == "typeof iifname" and got.get("ports") == "typeof th dport", got)
check("[2] …everything else exactly as listed: elements, timeouts, counters, the concatenations, the rules",
      len(loads) == 4 and "\t\ttype ifname . ipv4_addr\n" in loads[0] and "10.50.0.2 counter packets 1 bytes 60 expires 9m58s" in loads[2]
      and "ip daddr vmap @dmap_b" in loads[0] and "packets 3 bytes 180" in loads[0] and "\t\ttype ipv4_addr . inet_service\n" in loads[3]
      and "87.250.250.242 timeout 1h expires 59m1s" in loads[1]
      and [l.count("\n") for l in loads] == [w.count("\n") for w in want], [l[:200] for l in loads])
check("[2] …and it says so, one line a table", [l for l in out.splitlines() if l.startswith("LOG ")] == [
      "LOG nft: inet %s re-declared its %d set key(s) by expression, contents kept — the host's own nft reads it now" % x
      for x in (("swg_reach", 3), ("swg_smart", 5), ("swg_doh", 2), ("swg_turn", 1))], out)
check("[2] a meter's own set (psc_*) is neither counted nor touched — a table holding only that is not re-loaded",
      "nft list table inet swg_mech" in log and not any("swg_mech" in l for l in loads) and "swg_mech" not in out, (out, log))
check("[2] a clean table and another program's table: not loaded, not touched",
      "nft list table inet swg_share" in log and not any("swg_share" in l for l in loads)
      and "list table inet other_tool" not in log and log.count("-f -") == 4, log)
rc, out, loads, log = entry_run(tables=[("inet", "swg_share", T(SHARE, False)), ("inet", "swg_mech", T(MECH_OLD, False))])
check("[2] …but a table re-loaded for another set declares the meter's set again, re-spelled `typeof ip saddr` (plain, the host cannot read it)",
      rc == 0 and loads == ["delete table inet swg_share\n" + T(SHARE, True), "delete table inet swg_mech\n" + T(MECH_OLD, True)]
      and keys_of(loads[1]).get("psc_10_50_0_0_24") == "typeof ip saddr"
      and "LOG nft: inet swg_mech re-declared its 2 set key(s) by expression, contents kept — the host's own nft reads it now" in out,
      (rc, out, [l[:400] for l in loads]))
marks = dict(re.findall(r"\t(?:set|map) (\S+) \{\n\t\t@T\([^|)]+\|([^)]+)\)", REACH + SHARE + SMART + DOH + TURN + MECH_OLD))
miss = [(k, x) for k, x in marks.items() if k not in TWINS or TWINS[k][0] != x]
noanchor = [k for k, (x, rx) in TWINS.items() if not re.search(rx, code)]
check("[2] …each re-spelled with the expression swg-noded declares that set with (a meter's set: the key its meter counts by)",
      not miss and not noanchor and set(marks) == set(TWINS), (miss, noanchor, sorted(set(TWINS) - set(marks))))
rc, out, loads, log = entry_run(LOAD_RC=1)
check("[2] a re-load nft refuses → said, the table left as it was (no second try, nothing deleted apart), sh -eu survives",
      rc == 0 and "END" in out and "LOG nft: inet swg_reach could not be re-declared — left as it was" in out and log.count("-f -") == 4
      and "delete table" not in log, (rc, out, log))
rc, out, loads, log = entry_run(nft=False)
check("[2] no nft → nothing", rc == 0 and out.strip() == "END" and not loads, (rc, out))
rc, out, loads, log = entry_run(LIST_RC=139)
check("[2] a ruleset that cannot be read → nothing (never a guess)", rc == 0 and out.strip() == "END" and not loads and log == "nft list tables\n", (rc, out, log))
i_def, i_call = E.find("nft_typeof_migrate(){"), E.find("\nnft_typeof_migrate\n")
i_exec = E.find('exec "${SWG_NODED_BIN:-/opt/swg-noded/swg-noded}"')
check("[2] …and it runs before swg-noded starts", 0 < i_awk < i_def < i_call < i_exec, (i_awk, i_def, i_call, i_exec))

# ── [3] the uninstall's sweep with the node's own nft ────────────────────────────────────────────────────────────────
print("\n[3] uninstall.sh: _node_nft_sweep")
U = SRC["UNINST"]
DOCKER_STUB = r'''#!/bin/bash
echo "docker $*" >> "$LOG"
case "$1" in
  inspect) [ -n "${NO_CTR:-}" ] && exit 1; echo "ghcr.io/sanityprotocol/swg-node:sha-test"; exit 0;;
  image) [ "$*" = "image inspect ghcr.io/sanityprotocol/swg-node:${ENV_TAG:-none}" ] && exit 0; exit 1;;   # only the one its .env names
  stop) exit 0;;
  run)
    case " $* " in
      *" list tables "*) [ -n "${LIST_RC:-}" ] && exit "$LIST_RC"; printf 'table ip filter\ntable inet swg_reach\ntable inet swg_smart\ntable ip nat\ntable inet other_tool\n'; exit 0;;
      *" -f - "*) cat > "$BATCH"; exit "${BATCH_RC:-0}";;
    esac;;
esac
exit 0
'''
# the host's interfaces: a file per name in $IFDIR, a <name>.gone beside it once `ip link delete` took it — kernel WireGuard (wg0)
# outlives `docker stop`; IP_STUCK names one `ip link delete` cannot remove. Every call goes to the log docker's go to, so the log
# is the order they ran in.
IP_STUB = r'''#!/bin/sh
echo "ip $*" >> "$LOG"
up(){ [ -e "$IFDIR/$1" ] && [ ! -e "$IFDIR/$1.gone" ]; }
case "$1 $2" in
  "link show") up "$3" && exit 0; exit 1;;
  "link delete") up "$4" || exit 1; [ "$4" = "${IP_STUCK:-}" ] && exit 2; : > "${IFDIR:?}/${4:?}.gone"; exit 0;;
esac
exit 0
'''
QUICK_STUB = '#!/bin/sh\necho "$(basename "$0") $*" >> "$LOG"\nexit 1\n'
def host_ifaces(t, b, names, ip=True):
    ifd = os.path.join(t, "ifaces"); os.makedirs(ifd)
    for n in names:
        open(os.path.join(ifd, n), "w").close()
    if ip:
        put(os.path.join(b, "ip"), IP_STUB)
    for q in ("awg-quick", "wg-quick"):
        put(os.path.join(b, q), QUICK_STUB)
    return ifd
def still_up(ifd):
    f = os.listdir(ifd)
    return sorted(n for n in f if not n.endswith(".gone") and n + ".gone" not in f)
def first(calls, pred):
    return next((i for i, c in enumerate(calls) if pred(c)), -1)
def sweep_run(dry=False, **env):
    t, b = sandbox()
    put(os.path.join(b, "docker"), DOCKER_STUB)
    ifd = host_ifaces(t, b, ("wg0",))   # awg0 was userspace: it went with the container
    dd = os.path.join(t, "dd"); os.makedirs(dd)
    if env.get("ENV_TAG"):
        put(os.path.join(dd, ".env"), "NODE_TOKEN=x\nSWG_IMAGE_TAG=%s   # a comment\n" % env["ENV_TAG"])
    script = ("set -uo pipefail\nDRYRUN=%s\nDOCKER_DIR=%s\ninfo(){ echo \"INFO $*\"; }\nwarn(){ echo \"WARN $*\"; }\nb(){ printf '%%s' \"$*\"; }\n"
              "%s%s_node_nft_sweep \"wg0 awg0\"\necho END\n" % ("true" if dry else "false", dd, fn(U, "_rm_host_iface"), fn(U, "_node_nft_sweep")))
    e = {"PATH": b, "LOG": os.path.join(t, "log"), "BATCH": os.path.join(t, "batch"), "IFDIR": ifd}
    e.update({k: str(v) for k, v in env.items()})
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=e, timeout=60)
    log = open(e["LOG"]).read() if os.path.exists(e["LOG"]) else ""
    batch = open(e["BATCH"]).read() if os.path.exists(e["BATCH"]) else ""
    return r.returncode, r.stdout + r.stderr, log, batch, still_up(ifd)

rc, out, log, batch, left = sweep_run()
calls = log.splitlines()
i_stop = first(calls, lambda c: c.startswith("docker stop"))
i_if = first(calls, lambda c: c == "ip link delete dev wg0")
i_list = first(calls, lambda c: c.startswith("docker run") and "list tables" in c)
i_batch = first(calls, lambda c: c.startswith("docker run") and " -f -" in c)
check("[3] the container is stopped first, then its interfaces deleted, then every swg* table in one batch by the node's own image",
      rc == 0 and 0 <= i_stop < i_if < i_list < i_batch and not left and batch == "delete table inet swg_reach\ndelete table inet swg_smart\n"
      and all("--net host" in c and "--cap-add NET_ADMIN" in c and "--entrypoint nft ghcr.io/sanityprotocol/swg-node:sha-test" in c
              for c in calls if c.startswith("docker run")), (rc, out, log, batch, left))
check("[3] …each named in one line; another program's table never", [l for l in out.splitlines() if l.startswith(("INFO", "WARN"))]
      == ["INFO   removed leftover host interface wg0", "INFO   removed the node's nft tables with its own nft: swg_reach swg_smart"]
      and "other_tool" not in batch, out)
rc, out, log, batch, left = sweep_run(dry=True)
check("[3] a dry run touches nothing", rc == 0 and "[dry] stop swg-node, then delete its swg* nft tables with its own nft" in out
      and [c for c in log.splitlines() if not c.startswith("docker inspect")] == [] and not batch and left == ["wg0"], (out, log))
rc, out, log, batch, left = sweep_run(LIST_RC=1)
check("[3] a failed read is said, and the host-side sweep still runs (it returns 0)",
      rc == 0 and "END" in out and "WARN could not read the node's nft tables with its own nft" in out and not batch, (out, log))
rc, out, log, batch, left = sweep_run(NO_CTR=1)
check("[3] no swg-node container and no image of it → nothing at all", rc == 0 and out.strip() == "END" and log ==
      "docker inspect -f {{.Config.Image}} swg-node\ndocker image inspect ghcr.io/sanityprotocol/swg-node:latest\n" and left == ["wg0"], (out, log))
rc, out, log, batch, left = sweep_run(NO_CTR=1, ENV_TAG="sha-env")
check("[3] its container gone, the image its .env names on the box (1.8.8 deferred #15) → the same sweep, with that image",
      rc == 0 and not left and batch == "delete table inet swg_reach\ndelete table inet swg_smart\n"
      and all("--entrypoint nft ghcr.io/sanityprotocol/swg-node:sha-env" in c for c in log.splitlines() if c.startswith("docker run")), (out, log))
i_cap = U.find('  capture_adopted "$_acfg" "$DOCKER_DIR/data/node/adopted-containers.json"\n  rm -f "$_acfg"\n')
i_sw = U.find('  _node_nft_sweep "$_ifn"             # stopped, its interfaces, then its nft tables')
i_rm = U.find("  run sh -c 'docker rm -f swg-node >/dev/null 2>&1 || true'")
check("[3] rm_docker_node sweeps the node's tables with its own nft BEFORE `docker rm`", 0 < i_cap < i_sw < i_rm, (i_cap, i_sw, i_rm))

# ── [4] the host-side sweep's read ───────────────────────────────────────────────────────────────────────────────────
print("\n[4] uninstall.sh: rm_node_netobjects when the ruleset cannot be read")
HNFT = r'''#!/bin/bash
echo "nft $*" >> "$LOG"
case "$*" in
  "list tables") [ -n "${LIST_RC:-}" ] && kill -"${LIST_SIG:-SEGV}" $$; printf 'table inet swg_reach\ntable inet other_tool\n'; exit 0;;
esac
exit 0
'''
def netobj_run(**env):
    t, b = sandbox()
    put(os.path.join(b, "nft"), HNFT)
    script = ("set -uo pipefail\nDRYRUN=false\ninfo(){ echo \"INFO $*\"; }\nwarn(){ echo \"WARN $*\"; }\nok(){ echo \"OK $*\"; }\n"
              "run(){ \"$@\"; }\nrmrf(){ :; }\nNOT_DONE=()\n%srm_node_netobjects\necho \"NOT_DONE=${NOT_DONE[*]-}\"\necho END\n"
              % fn(U, "rm_node_netobjects"))
    e = {"PATH": b, "LOG": os.path.join(t, "log")}
    e.update({k: str(v) for k, v in env.items()})
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=e, timeout=60)
    log = open(e["LOG"]).read() if os.path.exists(e["LOG"]) else ""
    return r.returncode, r.stdout + r.stderr, log

rc, out, log = netobj_run(LIST_RC=1)
check("[4] a `nft list tables` that crashes is said, goes to NOT removed, and no ✓ follows",
      rc == 0 and "END" in out and "WARN could not read the nft ruleset: nft list tables exited 139 (killed by signal 11 — a crash)" in out
      and "a reboot clears it" in out and "delete table" not in log and "OK swg datapath objects removed" not in out
      and "WARN swg datapath objects: the rest removed — NOT the nft tables" in out
      and "NOT_DONE=swg nft tables — the host's nft could not read the ruleset" in out and "Segmentation fault" not in out, (rc, out, log))
rc, out, log = netobj_run()
check("[4] a readable ruleset is swept and ✓'d as before (another program's table left)",
      rc == 0 and "nft delete table inet swg_reach" in log and "other_tool" not in log.replace("nft list tables\n", "")
      and "OK swg datapath objects removed" in out and "NOT_DONE=\n" in out + "\n", (out, log))

# ── [4b] the docker → bare convert's switch ──────────────────────────────────────────────────────────────────────────
print("\n[4b] lib/common.sh: lc_teardown_docker (a docker → bare convert's switch), driven under set -euo pipefail")
C = SRC["COMMON"]
HOSTNFT = r'''#!/bin/sh
echo "hostnft $*" >> "$LOG"
[ -n "${HOST_CRASH:-}" ] && kill -SEGV $$
exit 0
'''
def conv_run(nft=True, ip=True, **env):
    t, b = sandbox()
    put(os.path.join(b, "docker"), DOCKER_STUB)
    if nft:
        put(os.path.join(b, "nft"), HOSTNFT)
    ifd = host_ifaces(t, b, ("wg0",), ip=ip)   # wg0 is kernel WireGuard — it outlives `docker stop`; awg0 was userspace
    d = os.path.join(t, "dock"); os.makedirs(os.path.join(d, "data", "node-confs"))
    for n in ("awg0", "wg0"):
        open(os.path.join(d, "data", "node-confs", n + ".conf"), "w").write("[Interface]\n")
    script = ("set -euo pipefail\ninfo(){ echo \"INFO $*\"; }\nwarn(){ echo \"WARN $*\"; }\n%s%s%slc_teardown_docker \"%s\"\necho END\n"
              % (fn(C, "lc_node_nft_sweep"), fn(C, "lc_del_node_ifaces"), fn(C, "lc_teardown_docker"), d))
    e = {"PATH": b, "LOG": os.path.join(t, "log"), "BATCH": os.path.join(t, "batch"), "IFDIR": ifd}
    e.update({k: str(v) for k, v in env.items()})
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=e, timeout=60)
    log = open(e["LOG"]).read() if os.path.exists(e["LOG"]) else ""
    batch = open(e["BATCH"]).read() if os.path.exists(e["BATCH"]) else ""
    return r.returncode, r.stdout + r.stderr, log, batch, still_up(ifd)

rc, out, log, batch, left = conv_run(HOST_CRASH=1)
calls = [c for c in log.splitlines() if c.startswith(("docker ", "ip link delete"))]
i_stop = first(calls, lambda c: c.startswith("docker stop"))
i_if = first(calls, lambda c: c == "ip link delete dev wg0")
i_if2 = first(calls, lambda c: c == "ip link delete dev awg0")
i_batch = first(calls, lambda c: c.startswith("docker run") and " -f -" in c)
i_rm = first(calls, lambda c: c == "docker rm -f swg-node")
check("[4b] the docker → bare switch: stopped, its interfaces deleted, THEN its tables in one batch by its own image, then the container removed",
      rc == 0 and "END" in out and 0 <= i_stop < min(i_if, i_if2) and max(i_if, i_if2) < i_batch < i_rm and not left
      and batch == "delete table inet swg_reach\ndelete table inet swg_smart\n"
      and all("--net host" in c and "--cap-add NET_ADMIN" in c and "--entrypoint nft ghcr.io/sanityprotocol/swg-node:sha-test" in c
              for c in calls if c.startswith("docker run")), (rc, out, calls, batch, left))
check("[4b] …when the host's own nft cannot read the ruleset (it crashes: no \"Segmentation fault\" line reaches the operator), said in one line; another program's table never",
      [l for l in out.splitlines() if l.startswith(("INFO", "WARN"))] == ["INFO this host's nft cannot read the Docker node's nft tables — "
      "took its interfaces down, then removed the tables with the node's own nft: swg_reach swg_smart; the bare node declares them afresh"]
      and "other_tool" not in batch and "Segmentation fault" not in out and "hostnft list tables" in log, out)
_, _, _, twin, _ = sweep_run()
check("[4b] …the same batch uninstall.sh's _node_nft_sweep sends", batch == twin != "", (batch, twin))
rc, out, log, batch, left = conv_run(HOST_CRASH=1, IP_STUCK="wg0")
check("[4b] an interface that cannot be deleted leaves the tables enforcing (fail closed) — said, naming it — and the switch goes on",
      rc == 0 and "END" in out and not batch and left == ["wg0"] and "docker rm -f swg-node" in log
      and "WARN this host's nft cannot read the Docker node's nft tables, and its interface(s) wg0 could not be deleted — the tables are "
          "left enforcing; the bare node cannot change them until a reboot" in out, (out, log))
rc, out, log, batch, left = conv_run(HOST_CRASH=1, ip=False)
check("[4b] …and so does a host without `ip` (nothing can be deleted, nothing proven gone)",
      rc == 0 and "END" in out and not batch and "its interface(s) awg0 wg0 could not be deleted" in out, (out, log))
rc, out, log, batch, left = conv_run()
calls = [c for c in log.splitlines() if c.startswith(("docker ", "ip link delete"))]
check("[4b] a ruleset the host reads is left exactly as before: nothing stopped, nothing deleted — it keeps enforcing across the switch",
      rc == 0 and "END" in out and "hostnft list tables" in log and not batch and calls[:1] == ["docker rm -f swg-node"]
      and first(calls, lambda c: c == "ip link delete dev wg0") > 0 and not left
      and not [l for l in out.splitlines() if l.startswith(("INFO", "WARN"))], (out, log))
rc, out, log, batch, left = conv_run(nft=False)
check("[4b] no nft on the host (not installed yet) → swept, as for one that cannot read",
      rc == 0 and batch == "delete table inet swg_reach\ndelete table inet swg_smart\n", (out, log))
rc, out, log, batch, left = conv_run(HOST_CRASH=1, NO_CTR=1)
check("[4b] no swg-node container → nothing but the teardown", rc == 0 and "END" in out and not batch
      and [c for c in log.splitlines() if c.startswith("docker ")][:2] == ["docker inspect -f {{.Config.Image}} swg-node", "docker rm -f swg-node"], (out, log))
rc, out, log, batch, left = conv_run(HOST_CRASH=1, LIST_RC=1)
rc2, out2, log2, batch2, left2 = conv_run(HOST_CRASH=1, BATCH_RC=1)
check("[4b] its own nft failing to read or delete is said (edits cannot apply until a reboot), and the switch goes on",
      rc == 0 == rc2 and "END" in out and "END" in out2 and "docker rm -f swg-node" in log and "docker rm -f swg-node" in log2
      and "WARN this host's nft cannot read the Docker node's nft tables, and its own nft could not either — the bare node cannot "
          "change them until a reboot" in out
      and "WARN this host's nft cannot read the Docker node's nft tables, and its own nft could not delete them — the bare node "
          "cannot change them until a reboot" in out2, (out, out2))

# ── [5] CHANGELOG ────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] the CHANGELOG")
en = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read().split("\n## ")[1]
ru = open(os.path.join(ROOT, "CHANGELOG.ru.md"), encoding="utf-8").read().split("\n## ")[1]
check("[5] CHANGELOG.md's current release says it (Debian 12, a Docker node, the host's nft)",
      re.search(r"Debian 12[^\n]*Docker node|Docker node[^\n]*Debian 12", en) is not None and "nft" in en)
check("[5] …and CHANGELOG.ru.md's", re.search(r"Debian 12", ru) is not None and re.search(r"Docker", ru) is not None and "nft" in ru)
en12 = " ".join(next((b for b in en.split("\n- ") if b.startswith("**On Debian 12, a Docker node")), "").split())
ru12 = " ".join(next((b for b in ru.split("\n- ") if b.startswith("**На Debian 12 нода в Docker")), "").split())
check("[5] …the convert included (a Docker node converted to bare-metal could not change routing or blocking), in both",
      "converted to bare-metal" in en12 and "a convert, when the host cannot read them" in en12
      and "перенесённая на голое железо" in ru12 and "перенос, если хост не может их прочитать" in ru12, (en12[:120], ru12[:120]))

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS")
