#!/usr/bin/env python3
"""Self-test for per-person rows on KERNEL SNI (docs/ROUTING-PEERS-MESH-PLAN.md §6.3, §8 P1b; traps T33, T34).

A smart entry carrying `src: <wid>` routes only the devices the panel resolved for that selection. On Kernel SNI the host
tier is iptables mangle `SWGK`, so the row's hostnames route through a `hash:net,iface` ipset per selection, `swgs_<wid>`,
holding the same (address, device) pairs as the nft row. What that has to keep, each checked on the chain
`_ensure_smart_xtstring` actually renders, through a model of iptables + ipset and a walk of each connection's packets:

  · the row routes its chosen devices and nobody else — by (address, device), not by address (`src,src`);
  · both marks, the packet's and the connection's, on every packet of the routed flow (the recorded split flow);
  · a device the row does not choose is reset at most once per address — Phase 1 is closed by one unmarked RETURN per
    (subnet, category) a row uses; without it, every connection of theirs to a learned host is reset, for ever (T34);
  · learning once per (subnet, category) — a per-person row scans exactly what a rule for everyone with its list scans;
  · each category's operands → MARK → `--save-mark` stay together, and the learn rule stays keyed by operand, so two
    categories on one subnet learn into their own sets only (the two failures the code's comments record);
  · members are swapped in whole and never rebuild the chain; a set no row names is destroyed only once SWGK no longer
    references it; a scratch set an interrupted swap left behind goes on the next pass;
  · the one-time `hash:net,iface` probe: where it fails, no rule names a `swgs_` set and the node reports `src: 1` (T33);
  · a plan without `src` renders and signs exactly as P1 (fa8f8bf) did, so a node naming nobody rebuilds nothing.

The model follows the kernel where it decides: `ipset destroy` of a set a rule references fails; a rule naming a set that
does not exist is refused; `--match-set` with fewer directions than the set has dimensions never matches (ip_set_test);
`ipset restore` stops at its first error.

Hermetic: no iptables, no ipset, no root. Run: python3 tests/ksni_src_selftest.py   (0 = pass)
  --plant X   plant one defect and expect RED (exit 0 when caught; the FAIL count is printed):
     a   the learning block emitted per entry — the scan multiplies with the rows
     b   the `--save-mark` hoisted to once per subnet (a later category's operands come after it)
     c   the learn rule keyed by the reset mark instead of the operand (cross-category learning)
     d   a row's routing rule matches `-s <subnet>` (the widening)
     e   members replaced by destroy + create while SWGK references the set (the kernel refuses; old members stay)
     e2  a set no row names is reaped before SWGK is unhooked (the destroy is refused; the set outlives its row)
     f   the chain signature signs the members (a member change rebuilds the chain)
     g   the probe's answer is ignored at the hand-off (every per-person rule reaches a kernel that refuses them)
     g2  the node reports `src: 2` whatever the probe said
     g3  the probe reads a refused `hash:net,iface` as a pass
     h   the closing RETURN left out (T34)
     i   the row's set binds the address alone, not (address, device)
     s1  a scratch `swgs_<wid>t` left by an interrupted swap is never destroyed
     s2  a set whose member count drifted is not replaced (a flushed set stays empty)
     d6  an IP-learning change destroys the learned sets again (refused while SWG_CATK counts with them — D6)
     d6b a failed `ipset list` is read as "no sets" (nothing checked, nothing reported)
     d6c every learned set is swapped whatever its lifetime already is (one refused swap re-empties the others every pass)
     d6d the lifetime pass walks every `swgk_*` set, not the ones this node routes (a set about to be reaped holds it up)
     d6e the lifetime is taken from a note on disk again (a node 1.8.7 left believing it is never healed)
     r1  Reset routing destroys the learned sets without emptying them (the destroy is refused; every IP survives)
     t1  leaving Kernel SNI tears SWGK down before the counters (the learned sets outlive the pass)

Also, not tied to rows (a 1.8.7 bug found by P1b, D6): an IP-learning change reaches the learned sets while SWG_CATK counts
with them, Reset routing empties them, and a node leaving Kernel SNI drops them in the same pass.
"""
import importlib.machinery, importlib.util, ipaddress, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
P1_REV = os.environ.get("SWG_NODED_P1_REV", "fa8f8bf")          # the P1 build a plan without `src` must render exactly as
sys.path.insert(0, HERE)
from nft_guarded_model import SmartKernel  # noqa: E402

PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "a": ('''    learn = list(dict.fromkeys((e["subnet"], e["category"]) for e in entries))''',
          '''    learn = [(e["subnet"], e["category"]) for e in entries]'''),
    "b": ('''            rules.append(["-A", CHAIN, "-s", S, "-m", "mark", "--mark", hex(reset_mark),
                          "-j", "CONNMARK", "--save-mark"])''',
          '''            if (S, c) == next(p for p in learn if p[0] == S):
                rules.append(["-A", CHAIN, "-s", S, "-m", "mark", "--mark", hex(reset_mark), "-j", "CONNMARK", "--save-mark"])'''),
    "c": [('''            rules.append(["-A", CHAIN, *_xts_scan(S), "--string", d, "-j", "SET", "--add-set", setn, "dst"])''',
           '''            pass'''),
          ('''            rules.append(["-A", CHAIN, "-s", S, "-m", "mark", "--mark", hex(reset_mark),
                          "-j", "CONNMARK", "--save-mark"])''',
           '''            rules.append(["-A", CHAIN, "-s", S, "-m", "mark", "--mark", hex(reset_mark), "-j", "SET", "--add-set", setn, "dst"])
            rules.append(["-A", CHAIN, "-s", S, "-m", "mark", "--mark", hex(reset_mark),
                          "-j", "CONNMARK", "--save-mark"])''')],
    "d": ('''        who = ["-m", "set", "--match-set", _xts_srcsetname(e["src"]), "src,src"] if "src" in e else []''',
          '''        who = []'''),
    "e": [('''        body = ["create %s hash:net,iface family inet" % sn, "create %s hash:net,iface family inet" % tmp, "flush " + tmp]
        body += ["add %s %s,%s" % (tmp, a, d) for d, a in sorted(mem)]
        body += ["swap %s %s" % (tmp, sn), "destroy " + tmp]''',
           '''        body = ["create %s hash:net,iface family inet" % sn, "destroy " + sn, "create %s hash:net,iface family inet" % sn]
        body += ["add %s %s,%s" % (sn, a, d) for d, a in sorted(mem)]''')],
    "e2": [('''    _xts_src_sets(want_srcs, res, hdrs)
''', '''    _xts_src_sets(want_srcs, res, hdrs)
    _xts_reap(want_cats, want_srcs)
'''),
           ('''    _xts_reap(want_cats, want_srcs)
    _ok = [True]''', '''    _ok = [True]''')],
    "f": ('''    sig = hashlib.sha1((json.dumps(rules) + "|ttl:" + str(ttl)).encode()).hexdigest()[:16]''',
          '''    sig = hashlib.sha1((json.dumps(rules) + json.dumps(sorted((k, sorted(v)) for k, v in want_srcs.items())) + "|ttl:" + str(ttl)).encode()).hexdigest()[:16]'''),
    "g": ('''[e for e in smart_exit if _ks or "src" not in e]''', '''[e for e in smart_exit]'''),
    "g2": ('''            "src": 2 if _KSNI_SRC["ok"] else 1}''', '''            "src": 2}'''),
    "g3": ('''            ok = run(["ipset", "create", "swgs_probe", "hash:net,iface", "family", "inet"]).returncode == 0''',
           '''            ok = run(["ipset", "create", "swgs_probe", "hash:net,iface", "family", "inet"]) is not None'''),
    "h": ('''        rules.append(["-A", CHAIN, "-s", S, "-m", "set", "--match-set", _xts_setname(c), "dst", "-j", "RETURN"])''',
          '''        pass'''),
    "i": [('''        body = ["create %s hash:net,iface family inet" % sn, "create %s hash:net,iface family inet" % tmp, "flush " + tmp]
        body += ["add %s %s,%s" % (tmp, a, d) for d, a in sorted(mem)]''',
           '''        body = ["create %s hash:net family inet" % sn, "create %s hash:net family inet" % tmp, "flush " + tmp]
        body += ["add %s %s" % (tmp, a) for d, a in sorted(mem)]'''),
          ('''_xts_srcsetname(e["src"]), "src,src"]''', '''_xts_srcsetname(e["src"]), "src"]''')],
    "s1": ('''        if setn.startswith("swgs_") and not (_XTS_SRC_RE.fullmatch(setn) or _XTS_SRC_RE.fullmatch(setn[:-1])):''',
           '''        if setn.startswith("swgs_") and not _XTS_SRC_RE.fullmatch(setn):'''),
    "d6": ('''        r = run(["ipset", "restore"], input_text="create swgk_TTL hash:ip family inet timeout %s\\nswap swgk_TTL %s\\n"
                                                     "destroy swgk_TTL\\n" % (ttl, setn))''',
           '''        r = run(["ipset", "destroy", setn]); r = run(["ipset", "create", setn, "hash:ip", "family", "inet", "timeout", str(ttl), "-exist"])'''),
    "d6b": ('''    r = run(["ipset", "list", "-t"])
    if r.returncode != 0:
        return None
    out = {}''', '''    r = run(["ipset", "list", "-t"])
    out = {}'''),
    "d6c": ('''        if setn not in hdrs or hdrs[setn]["timeout"] == str(ttl):''', '''        if setn not in hdrs:'''),
    "d6d": ('''    for c in (want_cats if hdrs else ()):
        setn = _xts_setname(c)''', '''    for setn in (sorted(k for k in hdrs if k.startswith("swgk_") and k != "swgk_TTL") if hdrs else ()):'''),
    "d6e": ('''        if setn not in hdrs or hdrs[setn]["timeout"] == str(ttl):''',
            '''        if setn not in hdrs or hdrs[setn]["timeout"] == str(ttl) or (lambda f: os.path.exists(f) and open(f).read().strip() == str(ttl))(os.path.join(GEO_DIR, ".xtstring-ttl")):'''),
    "r1": ('''        run(["ipset", "flush", setn])      # the learned IPs go even where the destroy is refused: SWG_CATK still counts with''',
           '''        pass'''),
    "t1": ('''        _ensure_sni_router(None, [], res)                     # not SNI → stop the classifier + drop its map
        reconcile_catk_chain([])                              # not kernel-SNI → drop the per-category counting chain FIRST:
        _ensure_smart_xtstring([], {}, 0, res, active=False)  # it names the learned sets, whose destroy is refused while it does''',
           '''        _ensure_sni_router(None, [], res)                     # not SNI → stop the classifier + drop its map
        _ensure_smart_xtstring([], {}, 0, res, active=False)
        reconcile_catk_chain([])'''),
    "s2": ('''        if sn in have and _XTS_SRC.get(sn) == msig and have[sn] == len(mem):''',
           '''        if sn in have and _XTS_SRC.get(sn) == msig:'''),
}

STATE = tempfile.mkdtemp(prefix="ksni-src-")
os.environ["SWG_NODED_STATE"] = STATE


def load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m


path = NODED
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    src = open(NODED, encoding="utf-8").read()
    for old, new in (PLANTS[PLANT] if isinstance(PLANTS[PLANT], list) else [PLANTS[PLANT]]):
        assert src.count(old) == 1, "plant anchor missing — this run would FALSE-PASS: %r" % old[:80]
        src = src.replace(old, new, 1)
    path = os.path.join(STATE, "planted-noded.py")
    open(path, "w", encoding="utf-8").write(src)
N = load(path, "swgnoded_ksni")
REAL_CATK = N.reconcile_catk_chain


# ── the model: iptables mangle + ipset, as the kernel decides ───────────────────────────────────────────────────────────
class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


DIMS = {"hash:ip": 1, "hash:net": 1, "hash:net,iface": 2}


class Box:
    def __init__(self, netiface=True, nft=None):
        self.sets, self.chains, self.hooked, self.fail_swap, self.fail_list, self.swaps = {}, {}, False, False, False, []
        self.netiface, self.nft = netiface, nft
        self.builds = self.restores = 0
        self.refused = []

    # ipset
    def _member(self, typ, tok):
        if typ == "hash:net,iface":
            a, sep, dev = tok.partition(",")
            if not sep or not dev:
                raise ValueError("needs address,iface")
            return (ipaddress.ip_network(a, strict=False), dev)
        if "," in tok:
            raise ValueError("one dimension")
        return (ipaddress.ip_network(tok, strict=False), None)

    def referenced(self, name):                                 # EVERY set a rule names, not the first (a row names two)
        return any(t in ("--match-set", "--add-set") and r[i + 1] == name
                   for rs in self.chains.values() for r in rs for i, t in enumerate(r[:-1]))

    def ipset(self, a, exist=False):
        op = a[0]
        if op == "list" and a[1:] == ["-name"]:
            return R(0, "".join(n + "\n" for n in self.sets))
        if op == "list" and a[1:] == ["-t"]:
            if self.fail_list:
                return R(124, "", "")
            return R(0, "".join("Name: %s\nType: %s\nRevision: 1\nHeader: family inet hashsize 1024 maxelem 65536%s\n"
                                "Size in memory: 1\nReferences: %d\nNumber of entries: %d\n"
                                % (n, s["type"], " timeout %s bucketsize 12" % s["timeout"] if s.get("timeout") else "",
                                   int(self.referenced(n)), len(s["m"])) for n, s in self.sets.items()))
        if op == "create":
            n, typ = a[1], a[2]
            if typ == "hash:net,iface" and not self.netiface:
                return R(1, "", "ipset v7: Kernel error received: set type not supported")
            tmo = a[a.index("timeout") + 1] if "timeout" in a else None
            if n in self.sets:                                 # -exist forgives only the SAME set (type and parameters)
                same = self.sets[n]["type"] == typ and self.sets[n].get("timeout") == tmo
                return R(0) if ("-exist" in a or exist) and same else R(1, "", "set with the same name already exists")
            self.sets[n] = {"type": typ, "m": set(), "timeout": tmo}
            return R(0)
        if op == "destroy":
            if a[1] not in self.sets:
                return R(1, "", "set does not exist")
            if self.referenced(a[1]):
                return R(1, "", "Set cannot be destroyed: it is in use by a kernel component")
            del self.sets[a[1]]
            return R(0)
        if op == "flush":
            if a[1] not in self.sets:
                return R(1, "", "set does not exist")
            self.sets[a[1]]["m"].clear()
            return R(0)
        if op == "add":
            s = self.sets.get(a[1])
            if not s:
                return R(1, "", "set does not exist")
            try:
                s["m"].add(self._member(s["type"], a[2]))
            except ValueError as e:
                return R(1, "", "Syntax error: %s" % e)
            return R(0)
        if op == "swap":
            x, y = self.sets.get(a[1]), self.sets.get(a[2])
            if not x or not y or x["type"] != y["type"] or self.fail_swap is True or a[2] in (self.fail_swap or ()):
                return R(1, "", "cannot swap")
            self.swaps.append(a[2])
            self.sets[a[1]], self.sets[a[2]] = y, x            # the kernel swaps the SETS (timeout included); names stay put
            return R(0)
        if op == "restore":
            self.restores += 1
            for ln in (a[-1] or "").splitlines():
                if ln.strip():
                    r = self.ipset(ln.split(), exist=exist)
                    if r.returncode:
                        return r                               # ipset restore stops at its first error
            return R(0)
        return R(1, "", "unknown ipset op %r" % a)

    # iptables -t mangle
    def ipt(self, a):
        while a and a[0] in ("-w",):
            a = a[2:]
        if a[:2] != ["-t", "mangle"]:
            return R(0)                                        # nat / filter: not this test's business
        op, ch, rest = a[2], a[3] if len(a) > 3 else "", a[4:]
        if ch == "PREROUTING":
            if op == "-C":
                return R(0 if self.hooked else 1)
            if op == "-D":
                was, self.hooked = self.hooked, False
                return R(0 if was else 1)
            if op == "-A":
                assert rest[-2:] == ["-j", "SWGK"], rest
                if "SWGK" not in self.chains:
                    return R(1, "", "no chain")
                self.hooked = True
                return R(0)
        if ch in ("FORWARD", "OUTPUT", "POSTROUTING", "INPUT"):   # built-in chains: only their jumps matter here
            fw = self.chains.setdefault("@" + ch, [])
            if op == "-S":
                return R(0, "".join("-A %s %s\n" % (ch, " ".join(r)) for r in fw))
            if op in ("-A", "-I"):
                r = rest[1:] if op == "-I" and rest and rest[0].isdigit() else rest
                fw.insert(0, r) if op == "-I" else fw.append(r)
                return R(0)
            if op == "-D":
                if rest in fw:
                    fw.remove(rest); return R(0)
                return R(1)
            return R(0)
        if op == "-nL":
            return R(0 if ch in self.chains else 1)
        if op == "-S":
            if ch not in self.chains:
                return R(1)
            return R(0, "-N %s\n" % ch + "".join("-A %s %s\n" % (ch, " ".join(r)) for r in self.chains[ch]))
        if op == "-N":
            if ch in self.chains:
                return R(1, "", "Chain already exists")
            self.chains[ch] = []
            self.builds += ch == "SWGK"
            return R(0)
        if op == "-F":
            if ch not in self.chains:
                return R(1)
            self.chains[ch] = []
            return R(0)
        if op == "-X":
            if ch not in self.chains or (ch == "SWGK" and self.hooked) or \
                    any(r[-2:] == ["-j", ch] for k, rs in self.chains.items() for r in rs):
                return R(1)
            del self.chains[ch]
            return R(0)
        if op == "-A":
            for i, t in enumerate(rest):
                if t in ("--match-set", "--add-set") and rest[i + 1] not in self.sets:
                    self.refused.append(rest)
                    return R(1, "", "Set %s doesn't exist" % rest[i + 1])
            self.chains[ch].append(rest)
            return R(0)
        return R(1, "", "unknown iptables op %r" % a)

    def __call__(self, args, input_text=None, timeout=20, **kw):
        if args[0] == "nft":
            return self.nft(args, input_text, timeout) if self.nft else R(0)
        if args[0] == "ipset":
            a, exist = list(args[1:]), False
            if a and a[0] == "-exist":
                a, exist = a[1:], True
            if a == ["restore"]:
                return self.ipset(["restore", input_text], exist=exist)
            return self.ipset(a, exist=exist)
        if args[0] == "iptables":
            return self.ipt(list(args[1:]))
        return R(0)

    # a packet through SWGK
    def _in(self, name, flags, pkt):
        s = self.sets[name]
        fl = flags.split(",")
        if len(fl) < DIMS[s["type"]]:
            return False                                       # ip_set_test: fewer directions than dimensions never match
        addr = ipaddress.ip_address(pkt["src"] if fl[0] == "src" else pkt["dst"])
        dev = (pkt["iif"] if fl[1] == "src" else None) if DIMS[s["type"]] == 2 else None
        return any(addr in net and (DIMS[s["type"]] == 1 or d == dev) for net, d in s["m"])

    def walk(self, pkt, ct):
        for r in self.chains.get("SWGK", []) if self.hooked else []:
            i, ok, tgt = 0, True, None
            while i < len(r) and ok:
                t = r[i]
                if t == "-s":
                    ok = ipaddress.ip_address(pkt["src"]) in ipaddress.ip_network(r[i + 1]); i += 2
                elif t == "-p":
                    i += 2
                elif t == "--dport":
                    ok = r[i + 1] == "443"; i += 2
                elif t == "-m" and r[i + 1] == "connbytes":
                    lo, hi = r[i + 3].split(":")
                    ok = int(lo) <= pkt["n"] <= int(hi); i += 8
                elif t == "-m" and r[i + 1] == "string":
                    ok = r[i + 5] in pkt["payload"]; i += 6
                elif t == "-m" and r[i + 1] == "set":
                    ok = self._in(r[i + 3], r[i + 4], pkt); i += 5
                elif t == "-m" and r[i + 1] == "mark":
                    ok = pkt["mark"] == int(r[i + 3], 0); i += 4
                elif t == "-j":
                    tgt = r[i + 1:]; break
                else:
                    raise AssertionError("model cannot read %r in %r" % (t, r))
            if not ok:
                continue
            if tgt[0] == "MARK":
                pkt["mark"] = int(tgt[2], 0)
            elif tgt[0] == "CONNMARK":
                ct["mark"] = pkt["mark"] if tgt[1] == "--save-mark" else int(tgt[2], 0)
            elif tgt[0] == "SET":
                s = self.sets[tgt[2]]
                if s["type"] == "hash:ip":
                    s["m"].add((ipaddress.ip_network(pkt["dst"]), None))
            elif tgt[0] == "RETURN":
                return
            else:
                raise AssertionError("model cannot run target %r" % tgt)

    def conn(self, src, iif, dst, sni):
        """One TLS connection: the SYN, then the ClientHello. Each packet starts with the connection's mark (the nft restore
        at the same priority, before SWGK). A packet leaving with the reset mark is rejected (the nft FORWARD reset)."""
        ct, out = {"mark": 0}, {}
        for k, n, payload in (("syn", 1, ""), ("ch", 3, "\x16\x03\x01..." + sni + "...")):
            pkt = {"src": src, "iif": iif, "dst": dst, "n": n, "payload": payload, "mark": ct["mark"]}
            self.walk(pkt, ct)
            out[k] = pkt["mark"]
        out["ct"] = ct["mark"]
        out["reset"] = RESET in (out["syn"], out["ch"])
        return out

    def members(self, name):
        return {(str(n.network_address), d) for n, d in (self.sets.get(name) or {}).get("m", set())}

    def learned(self, cat):
        return {str(n.network_address) for n, _ in (self.sets.get(N._xts_setname(cat)) or {}).get("m", set())}

    def strings(self):
        return sum(1 for r in self.chains.get("SWGK", []) if "string" in r)


# ── the fixture ──────────────────────────────────────────────────────────────────────────────────────────────────────────
RESET = N.SNI_RESET_MARK
S = "10.8.0.0/24"
W1, W2 = "1f2e3d4c5b6a", "a0b1c2d3e4f5"
ALICE, BOB, CAROL = "10.8.0.5", "10.8.0.6", "10.8.0.7"
YT1, YT2, YT3, TG1 = "198.51.100.1", "198.51.100.2", "198.51.100.3", "203.0.113.1"
DOMS = {"custom_yt": ["yt.example"], "custom_tg": ["tg.example"]}
ROW_YT = {"subnet": S, "category": "custom_yt", "action": "exit", "via_iface": "swg_q", "table": 7001, "src": W1}
EV_TG = {"subnet": S, "category": "custom_tg", "action": "exit", "via_iface": "swg_r", "table": 7002}
EV_YT = {"subnet": S, "category": "custom_yt", "action": "exit", "via_iface": "swg_p", "table": 7003}
SRCS = {W1: [["wg0", ALICE + "/32"]], W2: [["wg0", CAROL + "/32"]]}
SN1 = N._xts_srcsetname(W1)


def fresh(**kw):
    N.GEO_DIR = tempfile.mkdtemp(prefix="geo-", dir=STATE)
    N._XTS_SRC.clear()
    N._kernel_sni_ok = lambda: True
    B = Box(**kw)
    N.run = B
    return B


def xpass(B, entries, srcs=SRCS, active=True):
    res = {"changed": 0, "errors": []}
    try:
        N._ensure_smart_xtstring([dict(e) for e in entries], DOMS, RESET, res, active=active, ttl=3600, srcs=srcs)
    except Exception as e:                                     # a crash is its check failing, never a pass
        res["errors"].append("raised %s: %s" % (type(e).__name__, e))
    return res


def tally(B, src, dst, sni, n=10, iif="wg0"):
    rs = [B.conn(src, iif, dst, sni) for _ in range(n)]
    return sum(r["reset"] for r in rs), rs


# ── 1. a per-person row routes its chosen device, and only by (address, device) ─────────────────────────────────────────
print("\n[a row for Alice, a rule for everyone below it]")
B = fresh()
r = xpass(B, [ROW_YT, EV_TG])
check("the chain builds without an error", not r["errors"] and not B.refused, (r["errors"], B.refused[:2]))
check("SWGK is hooked", B.hooked)
check("the selection's set holds exactly Alice's (address, device) pair", B.members(SN1) == {(ALICE, "wg0")}, B.members(SN1))
check("it is a hash:net,iface set", (B.sets.get(SN1) or {}).get("type") == "hash:net,iface", B.sets.get(SN1))
c1 = B.conn(ALICE, "wg0", YT1, "yt.example")
check("Alice's first connection to a new host is reset once, and the host is learned", c1["reset"] and YT1 in B.learned("custom_yt"),
      (c1, B.learned("custom_yt")))
c2 = B.conn(ALICE, "wg0", YT1, "yt.example")
check("her retry leaves by the row's exit — the SYN, the ClientHello and the connection all carry 7001",
      (c2["syn"], c2["ch"], c2["ct"], c2["reset"]) == (7001, 7001, 7001, False), c2)
n, rs = tally(B, BOB, YT1, "yt.example")
check("Bob (not chosen), to the same learned host, ten times: never reset (T34)", n == 0, [x["reset"] for x in rs])
check("…and never marked by SWGK — he takes the interface's other rules", all(x["ch"] == 0 and x["ct"] == 0 for x in rs), rs[:2])
n, rs = tally(B, BOB, YT2, "yt.example")
check("Bob to a host nobody taught yet, ten times: reset once (he teaches it), then never", n == 1, [x["reset"] for x in rs])
c3 = B.conn(ALICE, "wg0", YT2, "yt.example")
check("…and Alice's first connection to the host Bob taught leaves by her exit without a reset", (c3["ch"], c3["reset"]) == (7001, False), c3)
c4 = B.conn(ALICE, "wg1", YT1, "yt.example")
check("Alice's ADDRESS sent from another device is not taken for her (the set binds the device)", c4["ch"] != 7001 and c4["ct"] != 7001, c4)
check("…and it is not reset either (the closing RETURN meets every source on the subnet)", not c4["reset"], c4)
c5 = B.conn(BOB, "wg0", TG1, "tg.example")
check("the rule for everyone still teaches and resets on first contact", c5["reset"] and TG1 in B.learned("custom_tg"), c5)
check("the second category's ClientHello leaves its connection marked for the reset too (its own `--save-mark`)", c5["ct"] == RESET, c5)
c6 = B.conn(BOB, "wg0", TG1, "tg.example")
check("…and its retry leaves by the everyone exit", (c6["syn"], c6["ch"], c6["ct"]) == (7002, 7002, 7002), c6)
check("each category learned into its own set only (no cross-category learning)",
      B.learned("custom_tg") == {TG1} and TG1 not in B.learned("custom_yt") and not (B.learned("custom_tg") & {YT1, YT2}),
      (B.learned("custom_yt"), B.learned("custom_tg")))

# ── 2. first match across a row and a rule for everyone ─────────────────────────────────────────────────────────────────
print("\n[a row for Alice above a rule for everyone with the same list]")
B = fresh()
xpass(B, [ROW_YT, EV_YT])
B.conn(BOB, "wg0", YT1, "yt.example")
check("Alice leaves by her row", B.conn(ALICE, "wg0", YT1, "yt.example")["ch"] == 7001)
check("Bob leaves by the rule for everyone", B.conn(BOB, "wg0", YT1, "yt.example")["ch"] == 7003)

# ── 3. learning is once per (subnet, category) — the scan never multiplies with the rows ────────────────────────────────
print("\n[the scan's cost]")
cnt = {}
for label, plan in (("everyone", [EV_YT]), ("row", [ROW_YT]), ("row+everyone", [ROW_YT, EV_YT]),
                    ("two rows", [ROW_YT, dict(ROW_YT, src=W2, table=7004)])):
    B = fresh()
    xpass(B, plan)
    cnt[label] = B.strings()
check("a row, a row above a rule for everyone, and two rows each scan exactly what one rule for everyone scans",
      cnt["everyone"] > 0 and len(set(cnt.values())) == 1, cnt)

# ── 4. membership: swapped in whole, never a rebuild; drift healed; scratch and unused sets reaped ───────────────────────
print("\n[membership]")
B = fresh()
xpass(B, [ROW_YT, EV_TG])
b0, s0 = B.builds, B.restores
r = xpass(B, [ROW_YT, EV_TG])
check("an unchanged plan: no rebuild and no set replaced", (B.builds, B.restores) == (b0, s0) and not r["errors"], (B.builds, B.restores, r))
B.conn(BOB, "wg0", YT1, "yt.example")
live = B.conn(ALICE, "wg0", YT1, "yt.example")
r = xpass(B, [ROW_YT, EV_TG], srcs={W1: [["wg0", BOB + "/32"]]})
check("a member change rebuilds nothing", B.builds == b0 and B.hooked, (B.builds, b0))
check("…and replaces the set whole: Bob in, Alice out", B.members(SN1) == {(BOB, "wg0")} and not r["errors"], (B.members(SN1), r))
check("Bob now leaves by the row", B.conn(BOB, "wg0", YT1, "yt.example")["ch"] == 7001)
check("Alice no longer does, and is not reset", (lambda c: c["ch"] != 7001 and not c["reset"])(B.conn(ALICE, "wg0", YT1, "yt.example")))
_ct = {"mark": live["ct"]}                                      # a later packet of her connection opened before the swap
_pk = {"src": ALICE, "iif": "wg0", "dst": YT1, "n": 40, "payload": "", "mark": _ct["mark"]}
B.walk(_pk, _ct)
check("her established connection keeps its exit across the swap (the connection mark it already carries)",
      live["ct"] == 7001 and (_pk["mark"], _ct["mark"]) == (7001, 7001), (live, _pk, _ct))
B.sets.get(SN1, {"m": set()})["m"].clear()                      # someone flushed it by hand
xpass(B, [ROW_YT, EV_TG], srcs={W1: [["wg0", BOB + "/32"]]})
check("a set whose count drifted is replaced on the next pass", B.members(SN1) == {(BOB, "wg0")}, B.members(SN1))
B.sets[SN1 + "t"] = {"type": "hash:net,iface", "m": set()}      # an interrupted swap's scratch set
xpass(B, [ROW_YT, EV_TG], srcs={W1: [["wg0", BOB + "/32"]]})
check("a scratch set left by an interrupted swap is destroyed on the next pass", SN1 + "t" not in B.sets, sorted(B.sets))
r = xpass(B, [EV_TG])
check("the row removed: its set is destroyed in the same pass, once SWGK no longer names it",
      SN1 not in B.sets and not any(SN1 in x for x in B.chains.get("SWGK", [])), (sorted(B.sets), r))
check("…and nothing was refused on the way", not r["errors"] and not B.refused, (r, B.refused[:2]))
xpass(B, [ROW_YT, EV_TG]); xpass(B, [], active=False)
check("Kernel SNI torn down: no swgk_ or swgs_ set left", not [n for n in B.sets if n.startswith(("swgk_", "swgs_"))], sorted(B.sets))

# ── 5. a malformed selection is never widened ───────────────────────────────────────────────────────────────────────────
print("\n[narrower, never wider]")
B = fresh()
xpass(B, [dict(ROW_YT, src=""), dict(ROW_YT, src="not-a-wid"), EV_TG])
B.conn(ALICE, "wg0", YT1, "yt.example")
check("an entry whose `src` is not a selection id routes nobody (not the subnet)",
      all(B.conn(x, "wg0", YT1, "yt.example")["ch"] == 0 for x in (ALICE, BOB)) and not any(n.startswith("swgs_") for n in B.sets),
      sorted(B.sets))

# ── 6. the probe (T33): the hand-off, the report ────────────────────────────────────────────────────────────────────────
print("\n[the hash:net,iface probe, through reconcile_cascade]")
N._ensure_sni_router = lambda *a, **k: None
N.reconcile_catk_chain = lambda *a, **k: None
for ok in (False, True):
    B = fresh(netiface=ok, nft=SmartKernel())
    N._KSNI_SRC["ok"] = None
    smart = {"entries": [dict(ROW_YT), dict(EV_TG)], "categories": ["custom_tg", "custom_yt"], "mode": "sni_kernel",
             "srcs": SRCS, "domains": DOMS}
    try:
        N.reconcile_cascade({"interfaces": {}}, {}, smart, "")
        err = ""
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, e)
    tag = "probe %s: " % ("passes" if ok else "fails")
    rules = B.chains.get("SWGK", [])
    check(tag + "the pass runs", not err, err)
    check(tag + "the rule for everyone is built either way", any("custom_tg" in " ".join(x) for x in rules), rules[:2])
    check(tag + "no probe set is left behind", "swgs_probe" not in B.sets, sorted(B.sets))
    check(tag + "not one rule refused (T33)", not B.refused, B.refused[:2])
    if ok:
        check(tag + "the row reaches SWGK through its selection's set", any(SN1 in x for x in rules), rules[:3])
    else:
        check(tag + "not one rule references a swgs_ set", not any("swgs_" in " ".join(x) for x in rules), rules[:3])
    check(tag + "the node reports `src: %d`" % (2 if ok else 1), N.smart_status().get("src") == (2 if ok else 1), N.smart_status())
N._KSNI_SRC["ok"] = None

# ── 7b. D6 — the learned sets while SWG_CATK counts with them (a 1.8.7 bug, not the rows') ─────────────────────────────
print("\n[D6: an IP-learning change, Reset routing, leaving Kernel SNI — with the byte counters naming the sets]")
N.reconcile_catk_chain = REAL_CATK
CY = N._xts_setname("custom_yt")
def kpass(B, ttl, entries=(EV_YT,)):
    res = {"changed": 0, "errors": []}
    cats = N._ensure_smart_xtstring([dict(e) for e in entries], DOMS, RESET, res, ttl=ttl, srcs=SRCS)
    N.reconcile_catk_chain(cats)
    return res
CT = N._xts_setname("custom_tg")
lrn = lambda B, sn, ip: B.sets[sn]["m"].add((ipaddress.ip_network(ip + "/32"), None))
B = fresh()
kpass(B, 3600, (EV_YT, EV_TG))
check("the counters name the learned sets (the condition D6 needs)", B.referenced(CY) and B.referenced(CT), sorted(B.chains))
lrn(B, CY, "198.51.100.1"); lrn(B, CT, "203.0.113.1")
r = kpass(B, 120, (EV_YT, EV_TG))
check("IP learning turned off: both learned sets now live 120 s", [B.sets[x]["timeout"] for x in (CY, CT)] == ["120", "120"],
      [B.sets.get(x) for x in (CY, CT)])
check("…their learned IPs are gone, as the recreate always meant", not B.sets[CY]["m"] and not B.sets[CT]["m"])
check("…the counters still name them, no error, and no scratch set is left",
      B.referenced(CY) and not r["errors"] and "swgk_TTL" not in B.sets, (r["errors"], sorted(B.sets)))
check("…and nothing is kept on disk to believe instead of the kernel", not os.path.exists(os.path.join(N.GEO_DIR, ".xtstring-ttl")))
lrn(B, CY, "198.51.100.5"); b1, w1 = B.builds, len(B.swaps)
r = kpass(B, 120, (EV_YT, EV_TG))
check("…the next pass is quiet: no rebuild, no swap, what was learned since stays",
      B.builds == b1 and len(B.swaps) == w1 and B.sets[CY]["m"] and not r["errors"], (B.builds - b1, B.swaps[w1:], r["errors"]))
# one set's swap refused, the other's lands
B.fail_swap = {CT}
lrn(B, CY, "198.51.100.6")
r = kpass(B, 3600, (EV_YT, EV_TG))
check("one set refuses the new lifetime: that set is named in the error", any(CT in e for e in r["errors"]) and
      not any(CY in e for e in r["errors"]), r["errors"])
check("…and the other took it", B.sets[CY]["timeout"] == "3600" and B.sets[CT]["timeout"] == "120", [B.sets[x]["timeout"] for x in (CY, CT)])
lrn(B, CY, "198.51.100.7"); b2, w2 = B.builds, len(B.swaps)
r = kpass(B, 3600, (EV_YT, EV_TG))
check("…while it keeps refusing, the set that took it is never swapped again — its learned IPs stay",
      B.sets[CY]["m"] and CY not in B.swaps[w2:], (B.swaps[w2:], B.sets[CY]["m"]))
check("…and the chain is not rebuilt for it (a retry that rebuilt SWGK every pass would be T33's churn)", B.builds == b2, B.builds - b2)
B.fail_swap = False
lrn(B, CT, "203.0.113.9")
r = kpass(B, 3600, (EV_YT, EV_TG))
check("…once the kernel takes it: applied, emptied, no error that pass",
      B.sets[CT]["timeout"] == "3600" and not B.sets[CT]["m"] and not r["errors"], (B.sets[CT], r["errors"]))
# a failed listing
B.fail_list = True
r = kpass(B, 120, (EV_YT, EV_TG))
check("the listing fails: nothing is swapped, and it is said", B.sets[CY]["timeout"] == "3600" and any("list" in e for e in r["errors"]),
      (B.sets[CY]["timeout"], r["errors"]))
B.fail_list = False
r = kpass(B, 120, (EV_YT, EV_TG))
check("…the next pass applies it", [B.sets[x]["timeout"] for x in (CY, CT)] == ["120", "120"] and not r["errors"], r["errors"])
# a set this node no longer routes: the reaper's, never held up by a swap
B.fail_swap = {CT}
w3 = len(B.swaps)
r = kpass(B, 3600, (EV_YT,))
check("a category no longer routed: its set is never swapped (the reaper takes it), and no refusal of it is reported",
      CT not in B.swaps[w3:] and CY in B.swaps[w3:] and not any(CT in e for e in r["errors"]), (B.swaps[w3:], r["errors"]))
B.fail_swap = False
# a node 1.8.7 left hit: the marker said 120, the set still lives 3600
B = fresh()
kpass(B, 3600)
open(os.path.join(N.GEO_DIR, ".xtstring-ttl"), "w").write("120")
lrn(B, CY, "198.51.100.1")
kpass(B, 120)
check("a node 1.8.7 left believing its lifetime was applied (marker 120, set 3600) heals on its first pass",
      B.sets[CY]["timeout"] == "120", B.sets[CY])
B.sets[CY]["m"].add((ipaddress.ip_network("198.51.100.2/32"), None))
N._apply_full_reset(9, {"changed": 0, "errors": []})
check("Reset routing empties the learned sets even while the counters still name them",
      all(not v["m"] for k, v in B.sets.items() if k.startswith("swgk_")), {k: len(v["m"]) for k, v in B.sets.items()})
# leaving Kernel SNI, through the real reconcile_cascade: one pass must take the learned sets with it
B = fresh(nft=SmartKernel())
N._KSNI_SRC["ok"] = True
base = {"entries": [dict(EV_YT)], "categories": ["custom_yt"], "srcs": {}, "domains": DOMS}
N.reconcile_cascade({"interfaces": {}}, {}, dict(base, mode="sni_kernel"), "")
had = sorted(k for k in B.sets if k.startswith("swgk_"))
N.reconcile_cascade({"interfaces": {}}, {}, dict(base, mode="kernel", domains={}), "")
check("leaving Kernel SNI: the learned sets go in the same pass (the counters are dropped first)",
      had and not [k for k in B.sets if k.startswith("swgk_")] and "SWG_CATK" not in B.chains and "SWGK" not in B.chains,
      (had, sorted(B.sets), sorted(B.chains)))
N._KSNI_SRC["ok"] = None

# ── 7. a plan without `src` renders and signs exactly as P1 did ────────────────────────────────────────────────────────
print("\n[byte-identical where nobody is chosen]")
p1src = subprocess.run(["git", "-C", ROOT, "show", P1_REV + ":swg-noded"], capture_output=True, text=True)
check("the P1 build (%s) is readable" % P1_REV, p1src.returncode == 0, p1src.stderr[:120])
if p1src.returncode == 0:
    p1path = os.path.join(STATE, "p1-noded.py")
    open(p1path, "w").write(p1src.stdout)
    P1 = load(p1path, "swgnoded_p1")
    got = {}
    for label, mod in (("P1", P1), ("this", N)):
        mod.GEO_DIR = tempfile.mkdtemp(prefix="geo-", dir=STATE)
        mod._kernel_sni_ok = lambda: True
        B = Box()
        mod.run = B
        mod._ensure_smart_xtstring([dict(EV_YT), dict(EV_TG)], DOMS, RESET, {"changed": 0, "errors": []}, ttl=3600)
        got[label] = (B.chains.get("SWGK"), open(os.path.join(mod.GEO_DIR, ".xtstring-sig")).read())
    check("the same rules, in the same order", got["P1"][0] == got["this"][0], (len(got["P1"][0] or []), len(got["this"][0] or [])))
    check("the same signature — an upgrading node naming nobody rebuilds nothing", got["P1"][1] == got["this"][1], got)

shutil.rmtree(STATE, ignore_errors=True)
print("\n%s" % ("ALL PASS" if not FAILS else "FAILED (%d): %s" % (len(FAILS), ", ".join(FAILS))))
if PLANT:
    print("PLANT %s — %d check(s) red: %s" % (PLANT, len(FAILS), FAILS[:4]))
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
