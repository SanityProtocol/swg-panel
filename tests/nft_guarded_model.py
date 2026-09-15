"""A model of the guarded tables swg-noded loads — `swg_reach` and `swg_share` (docs/DEVICE-ACCESS-PLAN.md §13, §15, §16).

It reads exactly the file grammar those loads use (anything else is refused, so a new construct turns a gate red until the model
learns it), applies a load as ONE transaction the way the kernel does — a refused file changes nothing — and walks a packet
through `pre`. A gate then checks what a table DOES: who reaches what, which counter a drop lands in, what a swap leaves behind.

Refused, as measured: a name nft reserves (`ct`, `dst`, `fwd`, §10.1 M1); a prefix member in a hash concat set (§13.3); any
overlapping or duplicate element in a plain interval set (§16 C2 — 1.0.9 accepts a duplicate, 1.0.2 does not, the model takes the
stricter); a reference to a set, map, chain or counter that is not there; deleting what is not there, or what a rule or map element
still references (§13.3). With `nft102=True`, also a guard element added over one deleted in the same transaction (§13.3 M).
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
        m = re.fullmatch(r"delete (map|chain|set) inet (%s) (%s)" % (NAME, NAME), line)
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
            return CP(args, 0, "", "") if args[4] in T and args[5] in T[args[4]]["chains"] else missing
        if args[:3] == ["nft", "delete", "table"]:
            return CP(args, 0, "", "") if T.pop(args[4], None) is not None else missing
        if args[:4] == ["nft", "-j", "list", "counters"]:
            if args[6] not in T:
                return missing
            return CP(args, 0, json.dumps({"nftables": [{"metainfo": {}}] + [{"counter": {"family": "inet", "table": args[6], "name": k,
                                                                                         "packets": v, "bytes": v * 60}}
                                                                             for k, v in sorted(T[args[6]]["counters"].items())]}), "")
        return CP(args, 0, "", "")

    def flush(self, table):
        """A ruleset flush (Debian's `systemctl restart nftables`, a firewalld reload) took the table."""
        self.m.tables.pop(table, None)

    def leftover(self, table):
        """A table an earlier process left, of a shape this one never loaded."""
        self.m.load("table inet %s {\n  counter old { }\n}\n" % table)

    def names(self, table, kind):
        return set((self.m.tables.get(table) or _empty())[kind])
