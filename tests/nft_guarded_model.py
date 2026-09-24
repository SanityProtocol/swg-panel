"""A model of the guarded tables swg-noded loads — `swg_reach` and `swg_share` (docs/DEVICE-ACCESS-PLAN.md §13, §15, §16).

It reads exactly the file grammar those loads use (anything else is refused, so a new construct turns a gate red until the model
learns it), applies a load as ONE transaction the way the kernel does — a refused file changes nothing — and walks a packet
through `pre`. A gate then checks what a table DOES: who reaches what, which counter a drop lands in, what a swap leaves behind.

Refused, as measured: a name nft reserves (`ct`, `dst`, `fwd`, §10.1 M1); a prefix member in a hash concat set (§13.3); any
overlapping or duplicate element in a plain interval set (§16 C2 — 1.0.9 accepts a duplicate, 1.0.2 does not, the model takes the
stricter); a reference to a set, map, chain or counter that is not there; deleting what is not there, or what a rule or map element
still references (§13.3) — a named counter included (measured on 1.0.2–1.1.5, docs/SWG-REACH-COUNTER-PLAN.md §1). With `nft102=True`, also a guard element added over one deleted in the same transaction (§13.3 M).
"""
import copy, ipaddress, json, re, subprocess

RESERVED = {"ct", "dst", "fwd"}
NAME = r"[A-Za-z][A-Za-z0-9_]*"


class NftError(Exception):
    pass


def _ip(s):
    return int(ipaddress.IPv4Address(s))


def _span(a, b=None):
    """(lo, hi) of `a.b.c.d`, `a.b.c.d/len` or `a.b.c.d`-`e.f.g.h`."""
    if b:
        return _ip(a), _ip(b)
    n = ipaddress.IPv4Network(a, strict=True)
    return int(n.network_address), int(n.broadcast_address)


def _empty():
    return {"sets": {}, "maps": {}, "chains": {}, "counters": {}}


def _render(r):
    """A stored rule back in nft's own words."""
    kind, *g = r
    return {"reply": lambda: "ct direction reply accept", "dnot": lambda: "ip daddr != @%s accept" % g[0],
            "jump": lambda: "jump %s" % g[0], "dguard": lambda: 'ip daddr @%s counter name "%s" drop' % (g[0], g[1]),
            "vmap": lambda: "ip daddr vmap @%s" % g[0], "concat": lambda: "iifname . ip saddr @%s accept" % g[0],
            "ifsrc": lambda: 'iifname "%s" ip saddr @%s accept' % (g[0], g[1]), "src": lambda: "ip saddr @%s accept" % g[0],
            "cdrop": lambda: 'counter name "%s" drop' % g[0], "adrop": lambda: "counter drop"}[kind]()


class Model:
    def __init__(self, nft102=False):
        self.tables, self.nft102 = {}, nft102

    # ── loading ──────────────────────────────────────────────────────────────────────────────────────────────────────────
    def load(self, text):
        work, cur, gone = copy.deepcopy(self.tables), None, {}
        for raw in text.split("\n"):
            line = raw.strip()
            if not line:
                continue
            if cur is not None:
                if line == "}":
                    self._check_refs(work[cur])
                    cur = None
                else:
                    self._declare(work[cur], line)
                continue
            m = re.fullmatch(r"(delete )?table inet (%s)( \{)?" % NAME, line)
            if m:
                if m.group(1):
                    if m.group(2) not in work:
                        raise NftError("No such file or directory: table %s" % m.group(2))
                    del work[m.group(2)]
                else:
                    work.setdefault(m.group(2), _empty())
                    cur = m.group(2) if m.group(3) else None
                continue
            self._command(work, line, gone)
        if cur is not None:
            raise NftError("syntax error, unexpected end of file")
        self.tables = work

    def _name(self, n):
        if n in RESERVED:
            raise NftError("syntax error, unexpected %s" % n)
        return n

    def _declare(self, t, line):
        m = re.fullmatch(r"counter (%s) \{ \}" % NAME, line)
        if m:
            t["counters"].setdefault(self._name(m.group(1)), 0)       # re-declared: its value kept (measured, 1.0.9 and 1.0.2)
            return
        m = re.fullmatch(r"set (%s) \{ type ([^;]+);(?: flags ([^;]+);)?(?: elements = \{ (.*) \})? \}" % NAME, line)
        if m:
            name, typ, flags = self._name(m.group(1)), m.group(2), {f.strip() for f in (m.group(3) or "").split(",") if f.strip()}
            if typ not in ("ipv4_addr", "ifname . ipv4_addr"):
                raise NftError("unsupported set type %s" % typ)
            s = t["sets"].setdefault(name, {"type": typ, "flags": flags, "els": []})
            if (s["type"], s["flags"]) != (typ, flags):
                raise NftError("set %s redeclared with another type" % name)
            self._add(s, m.group(4) or "", name)
            return
        m = re.fullmatch(r"map (%s) \{ type ipv4_addr : verdict; flags interval; elements = \{ (.*) \} \}" % NAME, line)
        if m:
            name = self._name(m.group(1))
            els = t["maps"].setdefault(name, [])
            for e in m.group(2).split(", "):
                me = re.fullmatch(r"([\d.]+(?:/\d+)?)(?:-([\d.]+))? : (accept|drop|jump (%s))" % NAME, e)
                if not me:
                    raise NftError("syntax error in map element %r" % e)
                lo, hi = _span(me.group(1), me.group(2))
                if any(lo <= x_hi and x_lo <= hi for x_lo, x_hi, _v in els):
                    raise NftError("conflicting intervals specified (%s)" % e)          # measured for maps too, 1.0.9 and 1.0.2
                els.append((lo, hi, me.group(4) and ("jump", me.group(4)) or (me.group(3), None)))
            return
        m = re.fullmatch(r"chain (%s) \{ (.*) \}" % NAME, line)
        if m:
            name, body = self._name(m.group(1)), [s.strip() for s in m.group(2).split(";") if s.strip()]
            c = t["chains"].setdefault(name, {"base": None, "rules": []})
            if body and body[0].startswith("type filter hook prerouting priority "):
                if len(body) < 2 or body[1] != "policy accept":
                    raise NftError("base chain without policy accept")
                c["base"] = body[0][len("type filter hook prerouting priority "):]
                body = body[2:]
            c["rules"] += [self._rule(r) for r in body]
            return
        raise NftError("syntax error: %r" % line)

    def _add(self, s, text, name, gone=()):
        for e in [x for x in text.split(", ") if x]:
            if s["type"] == "ifname . ipv4_addr":
                me = re.fullmatch(r'"([A-Za-z0-9_.@-]{1,15})" \. ([\d.]+)(/\d+)?(?: timeout (\d+)s)?', e)
                if not me:
                    raise NftError("syntax error in element %r" % e)
                if "interval" not in s["flags"] and me.group(3):
                    raise NftError("Error: a hash concat set takes no prefix length (%s)" % e)      # §13.3, measured
                lo, hi = _span(me.group(2) + (me.group(3) or ""))
                s["els"].append({"if": me.group(1), "lo": lo, "hi": hi, "timeout": me.group(4) and int(me.group(4))})
            else:
                me = re.fullmatch(r"([\d.]+(?:/\d+)?)(?:-([\d.]+))?(?: timeout (\d+)s)?", e)
                if not me:
                    raise NftError("syntax error in element %r" % e)
                lo, hi = _span(me.group(1), me.group(2))
                if "interval" in s["flags"]:
                    for x in s["els"]:
                        if lo <= x["hi"] and x["lo"] <= hi:
                            raise NftError("conflicting intervals specified (%s)" % e)        # §16 C2, measured
                    if self.nft102 and any(lo <= g_hi and g_lo <= hi for g_lo, g_hi in gone):
                        raise NftError("interval overlaps with an existing one (%s)" % e)    # §13.3 M, nft 1.0.2
                s["els"].append({"if": None, "lo": lo, "hi": hi, "timeout": me.group(3) and int(me.group(3))})

    def _rule(self, r):
        for pat, kind in ((r"ct direction reply accept", "reply"),
                          (r"ip daddr != @(%s) accept" % NAME, "dnot"),
                          (r"jump (%s)" % NAME, "jump"),
                          (r'ip daddr @(%s) counter name "(%s)" drop' % (NAME, NAME), "dguard"),
                          (r"ip daddr vmap @(%s)" % NAME, "vmap"),
                          (r"iifname \. ip saddr @(%s) accept" % NAME, "concat"),
                          (r'iifname "([A-Za-z0-9_.@-]{1,15})" ip saddr @(%s) accept' % NAME, "ifsrc"),
                          (r"ip saddr @(%s) accept" % NAME, "src"),
                          (r'counter name "(%s)" drop' % NAME, "cdrop"),
                          (r"counter drop", "adrop")):
            m = re.fullmatch(pat, r)
            if m:
                return (kind,) + m.groups()
        raise NftError("syntax error in rule %r" % r)

    def _refs(self, t):
        """Every (kind, name) the table's rules and map elements reference."""
        out = set()
        for c in t["chains"].values():
            for r in c["rules"]:
                k = r[0]
                if k in ("dnot", "concat", "src"):
                    out.add(("sets", r[1]))
                elif k == "ifsrc":
                    out.add(("sets", r[2]))
                elif k == "dguard":
                    out |= {("sets", r[1]), ("counters", r[2])}
                elif k == "cdrop":
                    out.add(("counters", r[1]))
                elif k == "jump":
                    out.add(("chains", r[1]))
                elif k == "vmap":
                    out.add(("maps", r[1]))
        for els in t["maps"].values():
            out |= {("chains", v[1]) for _lo, _hi, v in els if v[0] == "jump"}
        return out

    def _check_refs(self, t):
        for kind, name in self._refs(t):
            if name not in t[kind]:
                raise NftError("Could not process rule: No such file or directory (%s %s)" % (kind[:-1], name))

    def _command(self, work, line, gone):
        m = re.fullmatch(r"(delete|add) element inet (%s) (%s) \{ (.*) \}" % (NAME, NAME), line)
        if m:
            t = self._table(work, m.group(2))
            s = t["sets"].get(m.group(3))
            if s is None:
                raise NftError("No such file or directory: set %s" % m.group(3))
            if m.group(1) == "add":
                self._add(s, m.group(4), m.group(3), gone.get(m.group(3), ()))
            else:
                for e in m.group(4).split(", "):
                    lo, hi = _span(e)
                    hit = [x for x in s["els"] if (x["lo"], x["hi"]) == (lo, hi)]
                    if not hit:
                        raise NftError("No such file or directory: element %s" % e)
                    s["els"].remove(hit[0])
                    gone.setdefault(m.group(3), []).append((lo, hi))
            return
        m = re.fullmatch(r"flush chain inet (%s) (%s)" % (NAME, NAME), line)
        if m:
            c = self._table(work, m.group(1))["chains"].get(m.group(2))
            if c is None:
                raise NftError("No such file or directory: chain %s" % m.group(2))
            c["rules"] = []
            return
        m = re.fullmatch(r"add rule inet (%s) (%s) (.*)" % (NAME, NAME), line)
        if m:
            t = self._table(work, m.group(1))
            if m.group(2) not in t["chains"]:
                raise NftError("No such file or directory: chain %s" % m.group(2))
            t["chains"][m.group(2)]["rules"].append(self._rule(m.group(3)))
            self._check_refs(t)
            return
        m = re.fullmatch(r"delete (map|chain|set|counter) inet (%s) (%s)" % (NAME, NAME), line)
        if m:
            t, kind, name = self._table(work, m.group(2)), m.group(1) + "s", m.group(3)
            if name not in t[kind]:
                raise NftError("No such file or directory: %s %s" % (m.group(1), name))
            saved = t[kind].pop(name)
            if (kind, name) in self._refs(t):
                t[kind][name] = saved
                raise NftError("Could not process rule: Device or resource busy (%s %s)" % (m.group(1), name))
            return
        raise NftError("syntax error: %r" % line)

    def _table(self, work, name):
        if name not in work:
            raise NftError("No such file or directory: table %s" % name)
        return work[name]

    # ── packets ──────────────────────────────────────────────────────────────────────────────────────────────────────────
    def packet(self, table, iif, saddr, daddr, reply=False, v6=False, at=0):
        """→ (verdict, counter) for one packet through `pre`: "accept" or "drop", and the named counter a drop counted into ("" for
        an anonymous one). The counter is incremented. `at` is seconds since the load, for elements with a timeout."""
        t = self.tables.get(table)
        if t is None:
            return "accept", None
        base = [n for n, c in t["chains"].items() if c["base"] is not None]
        if len(base) != 1:
            raise NftError("expected one base chain, found %s" % base)
        pkt = {"iif": iif, "s": None if v6 else _ip(saddr), "d": None if v6 else _ip(daddr), "reply": reply, "at": at}
        return self._walk(t, base[0], pkt, 0) or ("accept", None)

    def _in(self, t, set_name, pkt, key, iif=None):
        for x in t["sets"][set_name]["els"]:
            if x["timeout"] is not None and pkt["at"] >= x["timeout"]:
                continue
            if x["lo"] <= key <= x["hi"] and (x["if"] is None or x["if"] == iif):
                return True
        return False

    def _walk(self, t, chain, pkt, depth):
        if depth > 16:
            raise NftError("jump loop")
        v4 = pkt["d"] is not None
        for r in t["chains"][chain]["rules"]:
            k = r[0]
            if k == "reply" and pkt["reply"]:
                return "accept", None
            if k == "dnot" and v4 and not self._in(t, r[1], pkt, pkt["d"]):
                return "accept", None
            if k == "jump":
                out = self._walk(t, r[1], pkt, depth + 1)
                if out:
                    return out
            if k == "dguard" and v4 and self._in(t, r[1], pkt, pkt["d"]):
                t["counters"][r[2]] += 1
                return "drop", r[2]
            if k == "vmap" and v4:
                hit = next((v for lo, hi, v in t["maps"][r[1]] if lo <= pkt["d"] <= hi), None)
                if hit and hit[0] == "jump":
                    out = self._walk(t, hit[1], pkt, depth + 1)
                    if out:
                        return out
                elif hit:
                    return hit[0], None
            if k == "concat" and v4 and self._in(t, r[1], pkt, pkt["s"], pkt["iif"]):
                return "accept", None
            if k == "ifsrc" and v4 and pkt["iif"] == r[1] and self._in(t, r[2], pkt, pkt["s"]):
                return "accept", None
            if k == "src" and v4 and self._in(t, r[1], pkt, pkt["s"]):
                return "accept", None
            if k == "cdrop":
                t["counters"][r[1]] += 1
                return "drop", r[1]
            if k == "adrop":
                return "drop", ""
        return None


class Kernel:
    """`run` as swg-noded calls it for these tables, answered from a Model: loads, list table/chain, delete table, the JSON counter
    listing. `refuse` makes every load fail as a refused file; `calls` and `loads` record what was asked."""
    def __init__(self, nft102=False):
        self.m, self.calls, self.loads, self.refuse, self.last_refused = Model(nft102), [], [], False, False

    def __call__(self, args, input_text=None, timeout=20):
        CP = subprocess.CompletedProcess
        self.calls.append(list(args))
        T = self.m.tables
        if args[:2] == ["nft", "-f"]:
            try:
                if self.refuse:
                    raise NftError("Could not process rule: No such file or directory")
                self.m.load(input_text or "")
            except NftError as e:
                self.last_refused = True
                return CP(args, 1, "", "Error: %s" % e)
            self.last_refused = False
            self.loads.append(input_text)
            return CP(args, 0, "", "")
        missing = CP(args, 1, "", "Error: No such file or directory")
        if args[:3] == ["nft", "list", "table"]:
            return CP(args, 0, "", "") if args[4] in T else missing
        if args[:3] == ["nft", "list", "chain"]:
            if not (args[4] in T and args[5] in T[args[4]]["chains"]):
                return missing
            # rendered the way nft lists it, enough for a reader that asks whether a rule is still THERE (`_gtable_intact`)
            c = T[args[4]]["chains"][args[5]]
            return CP(args, 0, "table inet %s {\n\tchain %s {\n%s\t}\n}\n" % (args[4], args[5], "".join(
                "\t\t%s\n" % _render(r) for r in c["rules"])), "")
        if args[:3] == ["nft", "delete", "table"]:
            return CP(args, 0, "", "") if T.pop(args[4], None) is not None else missing
        if args[:4] == ["nft", "-j", "list", "counters"]:
            if args[6] not in T:
                return missing
            return CP(args, 0, json.dumps({"nftables": [{"metainfo": {}}] + [{"counter": {"family": "inet", "table": args[6], "name": k,
                                                                                         "packets": v, "bytes": v * 60}}
                                                                             for k, v in sorted(T[args[6]]["counters"].items())]}), "")
        return CP(args, 0, "", "")

    def flush_rules(self, table):
        """`nft flush table`: the table, its sets, maps and counters stay — every chain is emptied."""
        for c in self.m.tables.get(table, {}).get("chains", {}).values():
            c["rules"] = []

    def flush(self, table):
        """A ruleset flush (Debian's `systemctl restart nftables`, a firewalld reload) took the table."""
        self.m.tables.pop(table, None)

    def leftover(self, table):
        """A table an earlier process left, of a shape this one never loaded."""
        self.m.load("table inet %s {\n  counter old { }\n}\n" % table)

    def names(self, table, kind):
        return set((self.m.tables.get(table) or _empty())[kind])


# ═══ swg_smart — the smart-routing table, as `_ensure_smart_nft` drives it (docs/ROUTING-PEERS-MESH-PLAN.md §6.2) ═══════════
# A second model, not an extension of the one above: swg_smart is built by per-object `nft add …` calls plus ONE `_NftBatch`
# script of `flush` / `add rule` / `add element` / `delete` lines, and the node reads it back by REGEX over `nft list table`.
# So this model takes exactly those command shapes, applies a script as one transaction (a refused script, `-c` included,
# changes nothing), renders the table the way nft 1.0.9 prints it closely enough for the node's own readers, and walks a
# packet through `prerouting` — jumps, marks and the connection mark included. Refused, as measured: a prefix member in a
# hash concat set; a reference to a set / chain / counter that is not there; deleting a chain a jump still names or a set a
# rule still matches ("Device or resource busy", smart-nft-ttl-swap-ordering). Anything it does not know is a syntax error.
class SmartModel:
    def __init__(self):
        self.tables, self.handle = {}, 0

    # ── state helpers ────────────────────────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _table():
        return {"sets": {}, "chains": {}, "counters": {}}

    def _t(self, work, name):
        if name not in work:
            raise NftError("No such file or directory: table %s" % name)
        return work[name]

    def _new_set(self, spec):
        m = re.fullmatch(r"\{ type (ipv4_addr|ifname \. ipv4_addr|ifname);(?: flags ([a-z, ]+);)?(?: auto-merge;)?(?: timeout (\d+)s;)? \}",
                         spec.strip())
        if not m:
            raise NftError("syntax error in set declaration %r" % spec)
        flags = {f.strip() for f in (m.group(2) or "").split(",") if f.strip()}
        return {"type": m.group(1), "flags": flags, "automerge": "auto-merge" in spec,
                "timeout": int(m.group(3)) if m.group(3) else None, "els": set()}

    def _add_elements(self, s, text):
        for e in [x.strip() for x in text.split(",") if x.strip()]:
            if s["type"] == "ifname":                      # the arrivals' mesh legs (ROUTING-PEERS-MESH-PLAN §6.1): a device name, quoted
                me = re.fullmatch(r'"([A-Za-z0-9_.@:+-]{1,15})"', e)
                if not me:
                    raise NftError("syntax error in element %r" % e)
                s["els"].add((me.group(1), -1, -1))
                continue
            if s["type"] == "ifname . ipv4_addr":
                me = re.fullmatch(r'"([A-Za-z0-9_.@:+-]{1,15})" \. (\d+\.\d+\.\d+\.\d+)(/\d+)?', e)
                if not me:
                    raise NftError("syntax error in element %r" % e)
                if me.group(3):
                    raise NftError("Error: You must add 'flags interval' to your set declaration (%s)" % e)   # measured, T25
                s["els"].add((me.group(1),) + _span(me.group(2)))
            else:
                if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+(/\d+)?", e):
                    raise NftError("syntax error in element %r" % e)
                s["els"].add((None,) + _span(e))

    # ── rules ────────────────────────────────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _num(v):
        return int(v, 16) if v.lower().startswith("0x") else int(v)

    def _rule(self, text):
        """`add rule` text → a list of ops, read left to right as nft does. Strict: a construct the node does not emit is refused."""
        tk, ops, i = text.split(), [], 0
        def at(*w):
            return tk[i:i + len(w)] == list(w)
        while i < len(tk):
            if at("iifname", ".", "ip", "saddr", "!=") and tk[i + 5].startswith("@"):   # a shadow rule's "not these devices"
                ops.append(("concat_src", tk[i + 5][1:], True)); i += 6
            elif at("iifname", ".", "ip", "saddr") and tk[i + 4].startswith("@"):
                ops.append(("concat_src", tk[i + 4][1:])); i += 5
            elif tk[i] == "iifname" and i + 1 < len(tk) and (tk[i + 1].startswith("@") or (tk[i + 1] == "!=" and tk[i + 2].startswith("@"))):
                neg = tk[i + 1] == "!="                                  # the device in an `ifname` set (`iifname @lg`)
                ops.append(("iifset", (tk[i + 2] if neg else tk[i + 1])[1:], neg)); i += 3 if neg else 2
            elif tk[i] in ("iifname", "oifname") and i + 1 < len(tk):
                neg = tk[i + 1] == "!="
                ops.append(("iif" if tk[i] == "iifname" else "oif", (tk[i + 2] if neg else tk[i + 1]).strip('"'), neg))
                i += 3 if neg else 2
            elif at("ip", "saddr") or at("ip", "daddr"):
                fld = tk[i + 1][0]
                neg = tk[i + 2] == "!="
                v = tk[i + 3] if neg else tk[i + 2]
                if v.startswith("@"):
                    ops.append(("set", fld, v[1:], neg))
                else:
                    ops.append(("net", fld) + _span(v) + (neg,))
                i += 4 if neg else 3
            elif at("ct", "state"):
                ops.append(("ctstate", tk[i + 2])); i += 3
            elif at("ct", "direction"):
                ops.append(("ctdir", tk[i + 2])); i += 3
            elif at("ct", "packets", "lt"):
                ops.append(("ctpk_lt", int(tk[i + 3]))); i += 4
            elif at("ct", "original", "packets", "lt"):                 # the client's packets so far (swg-sni's queue gate)
                ops.append(("ctopk_lt", int(tk[i + 4]))); i += 5
            elif at("ct", "reply", "bytes", "lt"):                      # what the server has sent so far
                ops.append(("ctrb_lt", int(tk[i + 4]))); i += 5
            elif at("ct", "reply", "avgpkt", "lt"):                     # …and in packets how long, on average
                ops.append(("ctra_lt", int(tk[i + 4]))); i += 5
            elif at("meta", "length", "gt"):                            # the packet's length (a bare ACK is 40–64 bytes)
                ops.append(("len_gt", int(tk[i + 3]))); i += 4
            elif at("meta", "mark", "set", "ct", "mark"):
                ops.append(("mark_from_ct",)); i += 5
            elif at("meta", "mark", "set"):
                ops.append(("set_mark", self._num(tk[i + 3]))); i += 4
            elif at("ct", "mark", "set"):
                ops.append(("set_ctmark", self._num(tk[i + 3]))); i += 4
            elif at("ct", "mark", "!="):
                ops.append(("ctmark_ne", self._num(tk[i + 3]))); i += 4
            elif at("meta", "mark"):
                ops.append(("mark_eq", self._num(tk[i + 2]))); i += 3
            elif at("meta", "nfproto"):
                ops.append(("nfproto", tk[i + 2])); i += 3
            elif tk[i] in ("udp", "tcp") and at(tk[i], "dport"):
                ops.append(("l4", tk[i], int(tk[i + 2]))); i += 3
            elif at("counter", "name"):
                ops.append(("counter", tk[i + 2].strip('"'))); i += 3
            elif at("counter"):
                ops.append(("counter", None)); i += 1
            elif tk[i] in ("return", "accept", "drop"):
                ops.append(("verdict", tk[i])); i += 1
            elif at("jump"):
                ops.append(("jump", tk[i + 1])); i += 2
            elif at("queue", "num") and tk[i + 3:i + 4] == ["bypass"]:
                ops.append(("verdict", "queue")); i += 4
            elif at("reject", "with", "tcp", "reset"):
                ops.append(("verdict", "reject")); i += 4
            else:
                raise NftError("syntax error in rule %r at %r" % (text, " ".join(tk[i:i + 3])))
        if any(o[0] in ("verdict", "jump") for o in ops[:-1]):
            raise NftError("syntax error: a verdict must end the rule %r" % text)
        return ops

    @staticmethod
    def _refs(t):
        out = set()
        for c in t["chains"].values():
            for r in c["rules"]:
                for o in r["ops"]:
                    if o[0] in ("concat_src", "iifset"):
                        out.add(("sets", o[1]))
                    elif o[0] == "set":
                        out.add(("sets", o[2]))
                    elif o[0] == "jump":
                        out.add(("chains", o[1]))
                    elif o[0] == "counter" and o[1]:
                        out.add(("counters", o[1]))
        return out

    def _check_refs(self, t):
        for kind, name in self._refs(t):
            if name not in t[kind]:
                raise NftError("Could not process rule: No such file or directory (%s %s)" % (kind[:-1], name))

    # ── commands ─────────────────────────────────────────────────────────────────────────────────────────────────────────
    def command(self, work, line):
        """One command line — as a script line (`flush chain inet swg_smart prerouting`) or an argv joined with spaces."""
        m = re.fullmatch(r"(add|delete) table inet (%s)" % NAME, line)
        if m:
            if m.group(1) == "add":
                work.setdefault(m.group(2), self._table())
            elif work.pop(m.group(2), None) is None:
                raise NftError("No such file or directory: table %s" % m.group(2))
            return
        m = re.fullmatch(r"add set inet (%s) (%s) (\{.*\})" % (NAME, NAME), line)
        if m:
            t = self._t(work, m.group(1))
            if m.group(2) not in t["sets"]:
                t["sets"][m.group(2)] = self._new_set(m.group(3))
            return
        m = re.fullmatch(r"add chain inet (%s) (%s)(?: \{ type filter hook (prerouting|forward) priority ([a-z0-9+ -]+); policy accept; \})?"
                         % (NAME, NAME), line)
        if m:
            t = self._t(work, m.group(1))
            c = t["chains"].setdefault(m.group(2), {"hook": None, "rules": []})
            if m.group(3):
                c["hook"] = (m.group(3), m.group(4))
            return
        m = re.fullmatch(r"add counter inet (%s) (%s)" % (NAME, NAME), line)
        if m:
            self._t(work, m.group(1))["counters"].setdefault(m.group(2), 0)
            return
        m = re.fullmatch(r"flush (chain|set) inet (%s) (%s)" % (NAME, NAME), line)
        if m:
            t = self._t(work, m.group(2))
            obj = t[m.group(1) + "s"].get(m.group(3))
            if obj is None:
                raise NftError("No such file or directory: %s %s" % (m.group(1), m.group(3)))
            if m.group(1) == "chain":
                obj["rules"] = []
            else:
                obj["els"] = set()
            return
        m = re.fullmatch(r"add element inet (%s) (%s) \{ (.*) \}" % (NAME, NAME), line)
        if m:
            s = self._t(work, m.group(1))["sets"].get(m.group(2))
            if s is None:
                raise NftError("No such file or directory: set %s" % m.group(2))
            self._add_elements(s, m.group(3))
            return
        m = re.fullmatch(r"add rule inet (%s) (%s) (.*)" % (NAME, NAME), line)
        if m:
            t = self._t(work, m.group(1))
            if m.group(2) not in t["chains"]:
                raise NftError("No such file or directory: chain %s" % m.group(2))
            self.handle += 1
            t["chains"][m.group(2)]["rules"].append({"text": m.group(3), "ops": self._rule(m.group(3)), "handle": self.handle})
            self._check_refs(t)
            return
        m = re.fullmatch(r"delete (chain|set|counter) inet (%s) (%s)" % (NAME, NAME), line)
        if m:
            t, kind, name = self._t(work, m.group(2)), m.group(1) + "s", m.group(3)
            if name not in t[kind]:
                raise NftError("No such file or directory: %s %s" % (m.group(1), name))
            if (kind, name) in self._refs(t):
                raise NftError("Could not process rule: Device or resource busy (%s %s)" % (m.group(1), name))
            del t[kind][name]
            return
        raise NftError("syntax error: %r" % line)

    def script(self, text, check_only=False):
        work, hsave = copy.deepcopy(self.tables), self.handle
        try:
            for line in [l.strip() for l in text.split("\n") if l.strip()]:
                self.command(work, line)
            for t in work.values():
                self._check_refs(t)
        except NftError:
            self.handle = hsave
            raise
        if check_only:
            self.handle = hsave
        else:
            self.tables = work

    # ── the listing the node parses ──────────────────────────────────────────────────────────────────────────────────────
    def render(self, name):
        t = self.tables[name]
        out = ["table inet %s {" % name]
        for cn, v in sorted(t["counters"].items()):
            out += ["\tcounter %s {" % cn, "\t\tpackets %d bytes %d" % (v, v * 60), "\t}"]
        for sn, s in t["sets"].items():
            out += ["\tset %s {" % sn, "\t\ttype %s" % s["type"]]
            if s["flags"]:
                out.append("\t\tflags %s" % ",".join(sorted(s["flags"])))
            if s["automerge"]:
                out.append("\t\tauto-merge")
            if s["timeout"]:
                out.append("\t\ttimeout %ds" % s["timeout"])
            if s["els"]:
                els = sorted(s["els"], key=lambda x: (x[0] or "", x[1]))
                txt = ", ".join(('"%s"' % e[0]) if e[1] == -1 else ('"%s" . %s' % (e[0], ipaddress.IPv4Address(e[1]))) if e[0] else
                                (str(ipaddress.IPv4Address(e[1])) if e[1] == e[2] else
                                 str(next(ipaddress.summarize_address_range(ipaddress.IPv4Address(e[1]), ipaddress.IPv4Address(e[2])))))
                                for e in els)
                out.append("\t\telements = { %s }" % txt)
            out.append("\t}")
        for cn, c in t["chains"].items():
            out.append("\tchain %s {" % cn)
            if c["hook"]:
                out.append("\t\ttype filter hook %s priority %s; policy accept;" % c["hook"])
            out += ["\t\t%s # handle %d" % (re.sub(r"\bcounter\b(?! name)", "counter packets %d bytes %d" % (r.get("pk", 0), r.get("pk", 0) * 60),
                                                     r["text"]), r["handle"]) for r in c["rules"]]
            out.append("\t}")
        return "\n".join(out + ["}"]) + "\n"

    # ── packets ──────────────────────────────────────────────────────────────────────────────────────────────────────────
    def packet(self, table, iif, saddr, daddr, proto="tcp", dport=443, ct="new", ctmark=0, reply=False, ctpackets=1,
               ctorig=None, length=517, replybytes=60, replypkts=1):
        """→ {verdict, mark, ctmark, via}: one IPv4 packet through `prerouting`. `via` lists the chains it walked.
        `ctpackets` counts both directions, `ctorig` the client's alone (default: `ctpackets`, an upper bound, so a test
        written for the old gate keeps its meaning — an early packet is early); `length` defaults to a ClientHello's, and
        `replybytes` over `replypkts` to a SYN-ACK: the server has not answered yet. `ct reply avgpkt` is their quotient,
        rounded down, as the kernel's is."""
        t = self.tables.get(table)
        st = {"mark": 0, "ctmark": ctmark, "via": []}
        if t is None:
            return dict(st, verdict="accept")
        pkt = {"iif": iif, "s": _ip(saddr), "d": _ip(daddr), "proto": proto, "dport": dport, "ct": ct,
               "dir": "reply" if reply else "original", "ctpk": ctpackets,
               "ctopk": ctpackets if ctorig is None else ctorig, "len": length, "ctrb": replybytes,
               "ctra": replybytes // replypkts if replypkts else 0}
        base = [n for n, c in t["chains"].items() if c["hook"] and c["hook"][0] == "prerouting"]
        v = self._walk(t, base[0], pkt, st, 0) if base else None
        return dict(st, verdict=v or "accept")

    def _in(self, t, name, key, iif=None):
        for e in t["sets"][name]["els"]:
            if e[1] <= key <= e[2] and (e[0] is None or e[0] == iif):
                return True
        return False

    def _walk(self, t, chain, pkt, st, depth):
        if depth > 16:
            raise NftError("jump loop")
        st["via"].append(chain)
        for r in t["chains"][chain]["rules"]:
            ok, verdict = True, None
            for o in r["ops"]:
                k = o[0]
                if k == "concat_src":
                    ok = self._in(t, o[1], pkt["s"], pkt["iif"]) != (len(o) > 2 and o[2])
                elif k == "iif":
                    ok = (pkt["iif"] == o[1]) != o[2]
                elif k == "iifset":
                    ok = any(e[0] == pkt["iif"] for e in t["sets"][o[1]]["els"]) != o[2]
                elif k == "oif":
                    ok = False                              # prerouting has no output interface
                elif k == "set":
                    ok = self._in(t, o[2], pkt[o[1]]) != o[3]
                elif k == "net":
                    ok = (o[2] <= pkt[o[1]] <= o[3]) != o[4]
                elif k == "ctstate":
                    ok = pkt["ct"] == o[1]
                elif k == "ctdir":
                    ok = pkt["dir"] == o[1]
                elif k == "ctpk_lt":
                    ok = pkt["ctpk"] < o[1]
                elif k == "ctopk_lt":
                    ok = pkt["ctopk"] < o[1]
                elif k == "len_gt":
                    ok = pkt["len"] > o[1]
                elif k == "ctrb_lt":
                    ok = pkt["ctrb"] < o[1]
                elif k == "ctra_lt":
                    ok = pkt["ctra"] < o[1]
                elif k == "mark_eq":
                    ok = st["mark"] == o[1]
                elif k == "ctmark_ne":
                    ok = st["ctmark"] != o[1]
                elif k == "nfproto":
                    ok = o[1] == "ipv4"
                elif k == "l4":
                    ok = pkt["proto"] == o[1] and pkt["dport"] == o[2]
                elif k == "mark_from_ct":
                    st["mark"] = st["ctmark"]
                elif k == "set_mark":
                    st["mark"] = o[1]
                elif k == "set_ctmark":
                    st["ctmark"] = o[1]
                elif k == "counter":
                    if o[1]:
                        t["counters"][o[1]] = t["counters"].get(o[1], 0) + 1
                    else:
                        r["pk"] = r.get("pk", 0) + 1                  # an anonymous counter, listed as `counter packets N bytes M`
                elif k == "verdict":
                    verdict = o[1]
                elif k == "jump":
                    verdict = ("jump", o[1])
                if not ok:
                    break
            if not ok:
                continue
            if verdict == "return":
                return None
            if isinstance(verdict, tuple):
                sub = self._walk(t, verdict[1], pkt, st, depth + 1)
                if sub:
                    return sub
                continue
            if verdict:
                return verdict
        return None


class SmartKernel:
    """`run` as `_ensure_smart_nft` calls it, answered from a SmartModel. `scripts` records every script that LANDED, `refused`
    every one that did not (with the reason)."""
    def __init__(self):
        self.m, self.calls, self.scripts, self.refused = SmartModel(), [], [], []

    def __call__(self, args, input_text=None, timeout=20):
        CP = subprocess.CompletedProcess
        args = [str(a) for a in args]
        self.calls.append(list(args))
        if args[:1] != ["nft"]:
            return CP(args, 0, "", "")
        try:
            if args[1:] in (["-c", "-f", "-"], ["-f", "-"]):
                self.m.script(input_text or "", check_only=args[1] == "-c")
                if args[1] != "-c":
                    self.scripts.append(input_text or "")
                return CP(args, 0, "", "")
            if args[1:3] == ["list", "table"]:
                if args[4] not in self.m.tables:
                    return CP(args, 1, "", "Error: No such file or directory")
                return CP(args, 0, self.m.render(args[4]), "")
            if args[1:3] == ["list", "chain"]:                   # one chain, as `nft list chain inet <t> <c>` prints it
                if args[4] not in self.m.tables or args[5] not in self.m.tables[args[4]]["chains"]:
                    return CP(args, 1, "", "Error: No such file or directory")
                txt = self.m.render(args[4])
                m = re.search(r"\tchain " + re.escape(args[5]) + r" \{.*?\n\t\}", txt, re.S)
                return CP(args, 0, "table inet %s {\n%s\n}\n" % (args[4], m.group(0)), "")
            self.m.script(" ".join(args[1:]))
            return CP(args, 0, "", "")
        except NftError as e:
            self.refused.append((" ".join(args[1:3]), str(e)))
            return CP(args, 1, "", "Error: %s" % e)

    def load_set(self, table, name, cidrs):
        """What `_smart_geo_refresh` / `_smart_load_cidrs` do between passes: fill a category set."""
        s = self.m.tables[table]["sets"][name]
        s["els"] = set()
        self.m._add_elements(s, ", ".join(cidrs))

    def handles(self, table, chain):
        return [r["handle"] for r in self.m.tables[table]["chains"][chain]["rules"]]
