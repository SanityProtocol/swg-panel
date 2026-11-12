#!/usr/bin/env python3
"""Self-test — a big pulled hostname list is read from its FILE, not held (docs/SCALE-PLAN.md K9, M1 + M2; 1.8.12 Scale).

A pulled block list of 1.2 M names cost swg-sni ~330 MB as a dict and swg-noded ~260 MB as a list (msk-forge, 2026-11-11). Under
Hybrid SNI swg-noded now names a list of SNI_FILE_MIN or more in the map by its path (`~files`) and swg-sni answers rung 1 by a
binary search over the mapped file. Nothing a connection meets may change: every verdict must be what the names inline gave.

  [1] the differential — the real reconcile_cascade under Hybrid SNI, once with every list inline (the floor raised past the
      files: today's path) and once by file; swg-sni built from each map answers `_match` the same on every host of a sample
      (a name, a suffix of one, a miss, a name in two big lists and inline beside one, a name only the panel ships inline
      for a pulled category, a bare-label line, names under a Never-block cut, a line that is not a name). With and without
      the Never-block list; the shadow categories (a rule for other devices names a parent of union names) equal too. The
      by-file map names the big lists by path, holds none of their names, keeps the small list inline; an engine switch
      re-reads (Force-DNS gets lists again); a pass with the Never-block list emptied writes no `cut`.
  [2] swg-sni's memory — a 2,000,000-name list by file: anon growth under 20 MB (a dict was ~280 MB), lookups right
  [3] a list replaced while mapped keeps answering by the content swg-noded checked until the map names the new file's stamp,
      then by the new; a list removed keeps its mapping until the map drops it; a failed map keeps the old one and retries;
      a mapped line that is not a name never answers
  [4] swg-noded's check — a by-file read keeps no names and returns the zones; each break of the contract (unsorted, `\\r\\n`,
      a trailing space, a junk line, an uppercase name, an empty line) reads the list as before; a file under the floor and
      `files=False` read lists; a file replaced after the check is still read right; swg-sni's name expression and map key
      are swg-noded's

Run: python3 tests/sni_pulled_file_selftest.py      (0 = pass)
     --perturb   plant each defect in turn → every one must go RED (exit 0 when all are caught)
"""
import ast, importlib.machinery, importlib.util, json, os, random, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from nft_guarded_model import SmartKernel  # noqa: E402

_RUN = subprocess.run          # swg-sni's run is stubbed on the shared module below; the RSS child needs the real one

NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
SNI = os.environ.get("SWG_SNI") or os.path.join(ROOT, "swg-sni")

PLANTS = {   # name: (file, old text, planted text)
    "s-read":     ("sni", "                            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)",
                   "                            mm = f.read()"),
    "s-onecat":   ("sni", "                got.add(cat)\n        return got", "                return {cat}\n        return got"),
    "s-noremap":  ("sni", "            if not (e and e[4] == want):", "            if not e:"),
    "s-anyfile":  ("sni", "                        if (st.st_ino, st.st_mtime_ns, st.st_size) == want:",
                   "                        if st.st_size:"),
    "s-dropold":  ("sni", "            elif e:\n                out.append((cat, path, cut, e[3], e[4]))", "            elif False:\n                pass"),
    "s-noregex":  ("sni", "        if not _DOM_RE.match(s):\n            return got\n", ""),
    "s-nocut":    ("sni", "            if not (cut and _nb_under(s, cut)) and _in_sorted", "            if _in_sorted"),
    "n-noorder":  ("noded", "        if ln < prev or not ln.isascii()", "        if not ln.isascii()"),
    "n-nomode":   ("noded", "            if byfile:\n                sig += (\"file\",)\n", ""),
    "n-cached":   ("noded", "                    out[cat], fh = _Pulled(path, stamp, fh), None",
                   "                    out[cat], fh = globals().setdefault(\"_PC\", {}).setdefault(path, _Pulled(path, stamp, fh)), None"),
    "n-names":    ("noded", "                if isinstance(d, _Pulled):                     # swg-sni reads it", "                if False:   # swg-sni reads it"),
    "n-nostamp":  ("noded", "{\"path\": d.path, \"stamp\": list(d.stamp)}", "{\"path\": d.path}"),
    "n-noinline": ("noded", "                fl.inline = sorted(set(domains.get(cat) or []))", "                fl.inline = []"),
    "n-itercut":  ("noded", "                    if not (self.cut and _nb_under(d, self.cut)):\n                        yield d",
                   "                    if True:\n                        yield d"),
    "n-unpinned": ("noded", "        return mmap.mmap(self.fh.fileno(), 0, access=mmap.ACCESS_READ)",
                   "        with open(self.path, \"rb\") as f:\n            return mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)"),
    "n-searchdrift": ("noded", "            hi = ls\n    return False\n\n\ndef _doms_file_ok",
                      "            hi = ls\n    return key == b\"\"\n\n\ndef _doms_file_ok"),
    "n-inlcut":   ("noded", "                lst.inline = [d for d in lst.inline if not _nb_under(d, allow)]", "                pass"),
    "n-holdscut": ("noded", "_DOM_RE.match(d) and not (self.cut and _nb_under(d, self.cut)) and _in_sorted(mm, d.encode())",
                   "_DOM_RE.match(d) and _in_sorted(mm, d.encode())"),
    "n-addmat":   ("noded", "        if isinstance(domains.get(c), _Pulled):\n            domains[c].inline", "        if False:\n            domains[c].inline"),
    "n-noadd":    ("noded", "            domains[c].inline = domains[c].inline + names      #", "            pass                                               #"),
    "n-norecheck": ("noded", "            sig = (st.st_ino, st.st_mtime_ns, st.st_size)", "            sig = (int(st.st_mtime), st.st_size)"),
}

UNION, BIG2, SMALL = "blku:host:0123456789ab", "mc:big2", "mc:small"
SA, SB = "10.188.1.0/24", "10.188.2.0/24"
ALLOW = ["allowed.org", "keep.tracker.com", "x.shared.io"]   # the last: a key of its own, added onto a by-file list


def load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m


def lists(rnd):
    """The two big lists (≥ 1 MiB each, sorted, with the names the checks ask for) and a small one."""
    al = "abcdefghijklmnopqrstuvwxyz0123456789"
    def bulk(n, tld):
        s = set()
        while len(s) < n:
            s.add("".join(rnd.choice(al) for _ in range(rnd.randint(6, 14))) + "." +
                  "".join(rnd.choice(al) for _ in range(rnd.randint(3, 9))) + "." + tld)
        return s
    u = bulk(60000, "com") | {"ads.tracker.com", "tracker.com", "x.y.tracker.com", "allowed.org", "cdn.allowed.org",
                               "keep.tracker.com", "both.example.com", "shared.io"}
    u_lines = sorted(u) + ["zz"]                                   # a bare label: a zone, never a rung-1 answer
    b2 = bulk(60000, "net") | {"both.example.com", "shared.io", "deep.shared.io"}
    return sorted(u_lines), sorted(b2), ["small-one.org", "small-two.org"], sorted(u)


def run_checks(nsrc, ssrc, which=""):
    fails = []

    def ok(cond, name, detail=""):
        if not cond:
            fails.append(name)
            if not which:
                print("  FAIL " + name + (("  — " + str(detail)[:300]) if detail else ""))
        elif not which:
            print("  PASS " + name)

    tmp = tempfile.mkdtemp(prefix="snipulled-")
    try:
        np_, sp_ = os.path.join(tmp, "noded.py"), os.path.join(tmp, "sni.py")
        open(np_, "w").write(nsrc); open(sp_, "w").write(ssrc)
        os.environ["SWG_NODED_STATE"] = tmp
        N = load(np_, "swgnoded_k9_" + (which or "x").replace("-", "_"))
        S = load(sp_, "swgsni_k9_" + (which or "x").replace("-", "_"))
        S.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")
        N.GEO_DIR = os.path.join(tmp, "geo"); os.makedirs(N.GEO_DIR)
        open(os.path.join(N.GEO_DIR, ".automerge-migrated"), "w").write("1")
        N.SNI_MAP_PATH = os.path.join(tmp, "sni-map.json")
        N.SNI_PATTERNS_PATH = os.path.join(tmp, "sni-patterns.json")
        N.SNI_BLOCKS_PATH = os.path.join(tmp, "sni-blocks.json")
        N.SNI_SETS_PATH = os.path.join(tmp, "sni-sets.json")
        N._SNI_PROC.update(p=type("P", (), {"poll": lambda self: None, "terminate": lambda self: None})(), ttl=3600)
        K = SmartKernel()
        N.run = lambda args, input_text=None, timeout=20, **kw: K(args, input_text, timeout) if args and args[0] == "nft" else \
            subprocess.CompletedProcess(args, 0, "", "")
        rnd = random.Random(11)
        ul, b2, sm, unames = lists(rnd)
        for cat, lines in ((UNION, ul), (BIG2, b2), (SMALL, sm)):
            open(os.path.join(N.GEO_DIR, cat + ".doms"), "w").write("\n".join(lines) + "\n")
        ok(min(os.path.getsize(os.path.join(N.GEO_DIR, c + ".doms")) for c in (UNION, BIG2)) >= N.SNI_FILE_MIN
           and os.path.getsize(os.path.join(N.GEO_DIR, SMALL + ".doms")) < N.SNI_FILE_MIN, "[0] the fixture: two lists past the floor, one under")
        entries = [{"subnet": SA, "category": UNION, "action": "block"},
                   {"subnet": SA, "category": BIG2, "action": "exit", "via_iface": "swg_p", "table": 7000},
                   {"subnet": SA, "category": SMALL, "action": "exit", "via_iface": "swg_p", "table": 7000},
                   {"subnet": SA, "category": "custom_c", "action": "exit", "via_iface": "swg_p", "table": 7000},
                   {"subnet": SB, "category": "custom_x", "action": "exit", "via_iface": "swg_p", "table": 7000},
                   {"subnet": SA, "category": "all", "action": "direct"}, {"subnet": SB, "category": "all", "action": "direct"}]
        cats = sorted({e["category"] for e in entries})
        smart_doms = {BIG2: ["inline-only.example"], UNION: ["panel-inline.example", "y.allowed.org"],   # the union's own,
                      "custom_c": ["both.example.com", "c-only.example"],                         # one under the cut
                      "custom_x": ["tracker.com"]}               # a rule for OTHER devices names a parent of union names: shadows

        def rc(allow, floor):
            N.SNI_FILE_MIN = floor
            smart = {"entries": [dict(e) for e in entries], "categories": cats, "mode": "sni", "domains": json.loads(json.dumps(smart_doms)),
                     "cat_caps": {UNION: {"host": True}, BIG2: {"host": True}, SMALL: {"host": True}}}
            if allow:
                smart["allow"] = list(allow)
            try:
                N.reconcile_cascade({"interfaces": {}}, {}, smart, "")
            except Exception as e:
                return "%s: %s" % (type(e).__name__, e), None
            try:
                return "", open(N.SNI_MAP_PATH).read()
            except OSError as e:
                return str(e), None

        def classifier(mapbytes):
            d = tempfile.mkdtemp(dir=tmp)
            open(os.path.join(d, "sni-map.json"), "w").write(mapbytes)
            if os.path.exists(N.SNI_PATTERNS_PATH):
                shutil.copy(N.SNI_PATTERNS_PATH, d)
            return S.Classifier(os.path.join(d, "sni-map.json"), N.SMART_NFT_TABLE, learn_ttl=3600)

        sample = rnd.sample(unames, 300) + rnd.sample(b2, 300)
        hosts = ["both.example.com", "a.both.example.com", "shared.io", "deep.shared.io", "x.deep.shared.io", "inline-only.example",
                 "w.inline-only.example", "c-only.example", "small-one.org", "q.small-two.org", "allowed.org", "cdn.allowed.org",
                 "x.cdn.allowed.org", "keep.tracker.com", "a.keep.tracker.com", "ads.tracker.com", "tracker.com", "x.y.tracker.com",
                 "zz", "a.zz", "nothing.example", "a_b.tracker.com", "TRACKER.com", "tracker.com.", "deep.shared.io.", "x.shared.io",
                 "a.x.shared.io", "panel-inline.example", "y.allowed.org", "z.y.allowed.org"]
        hosts += sample + ["www." + h for h in sample] + [h[1:] for h in sample] + [h + "x" for h in sample[:100]]
        for allow in ([], ALLOW):
            tag = "Never-block on" if allow else "Never-block off"
            for c in (N._DOM_CACHE, N._DOMTIER_CACHE):
                c.clear()
            N._SHADOW.update(k=None, v={})
            ea, ma = rc(allow, 1 << 40)                     # every list inline: the names as before
            N._SHADOW.update(k=None, v={})
            eb, mb = rc(allow, 1 << 20)                     # the big ones by file
            ok(not ea and not eb and ma and mb, "[1] %s: both passes ran and wrote a map" % tag, (ea, eb))
            if not (ma and mb):
                continue
            ja, jb = json.loads(ma), json.loads(mb)
            fl = jb.get(N.SNI_FILES_KEY) or {}
            def stamp(c):
                st = os.stat(os.path.join(N.GEO_DIR, c + ".doms"))
                return [st.st_ino, st.st_mtime_ns, st.st_size]
            ok(sorted(fl) == sorted([UNION, BIG2]) and all(os.path.samefile(v["path"], os.path.join(N.GEO_DIR, c + ".doms"))
                                                           and v.get("stamp") == stamp(c) for c, v in fl.items()),
               "[1] %s: the map names the two big lists by path, at the stamp of the file checked" % tag, fl)
            ok(N.SNI_FILES_KEY not in ja, "[1] %s: with the floor raised, the map is today's (no file named)" % tag)
            ok(jb.get(UNION) == ["panel-inline.example"] + ([] if allow else ["y.allowed.org"])
               and jb.get(BIG2) == ["inline-only.example"] + (["x.shared.io"] if allow else []) and jb.get(SMALL) == sm,
               "[1] %s: no name of a big list is written; the panel's own names stay inline (cut by Never-block), a Never-block "
               "key onto a big list too; the small list inline" % tag,
               {k: (v if len(str(v)) < 200 else len(v)) for k, v in jb.items()})
            ok(len(mb) < 20000 < len(ma), "[1] %s: the map %d → %d bytes" % (tag, len(ma), len(mb)), (len(ma), len(mb)))
            ok(sorted((fl.get(UNION) or {}).get("cut") or []) == sorted(ALLOW if allow else []) and "cut" not in (fl.get(BIG2) or {}),
               "[1] %s: the union's file carries the Never-block cut, the other none" % tag, fl)
            sha = {k: v for k, v in ja.items() if k.startswith("sw_")}
            shb = {k: v for k, v in jb.items() if k.startswith("sw_")}
            ok(sha and sha == shb, "[1] %s: the shadow categories are the same (a union name under the other devices' rule)" % tag,
               (sorted(sha)[:3], sorted(shb)[:3]))
            ca, cb = classifier(ma), classifier(mb)
            diff = [(h, ca._match(h), cb._match(h)) for h in hosts if list(ca._match(h)) != list(cb._match(h))]
            ok(not diff, "[1] %s: swg-sni answers all %d hosts the same from the files" % (tag, len(hosts)), diff[:5])
            ok(cb._match("both.example.com") == tuple(sorted([UNION, BIG2, "custom_c"])) and UNION in cb._match("x.y.tracker.com")
               and BIG2 in cb._match("x.deep.shared.io"),
               "[1] %s: a name in two files and inline answers all three; suffixes answer" % tag,
               (cb._match("both.example.com"), cb._match("x.y.tracker.com")))
            if allow:
                ok(UNION not in cb._match("cdn.allowed.org") and UNION not in cb._match("keep.tracker.com")
                   and UNION in cb._match("ads.tracker.com") and list(cb._match("x.shared.io")) == [BIG2],
                   "[1] %s: names under the cut are not the union's; the key added onto a big list answers it alone" % tag,
                   (cb._match("cdn.allowed.org"), cb._match("keep.tracker.com"), cb._match("x.shared.io")))
        # the Never-block list emptied after a pass with it: the fresh object carries no cut (the cache must not hand it on)
        N._SHADOW.update(k=None, v={})
        e1, m1 = rc(ALLOW, 1 << 20)
        e2, m2 = rc([], 1 << 20)
        ok(not e1 and not e2 and m2 and "cut" not in (json.loads(m2).get(N.SNI_FILES_KEY) or {}).get(UNION, {"cut": 1}),
           "[1] the Never-block list emptied: the next map carries no cut", (e1, e2, (m2 or "")[:300]))
        # an engine switch re-reads: Force-DNS gets lists
        r = {"errors": [], "changed": 0}
        d1, _z = N._smart_domain_refresh([UNION, BIG2], r, files=True)
        d2, _z = N._smart_domain_refresh([UNION, BIG2], r, files=False)
        ok(all(isinstance(v, N._Pulled) for v in d1.values()) and all(isinstance(v, list) for v in d2.values())
           and sorted(d2[UNION]) == unames, "[1] Hybrid then Force-DNS on the same files: by file, then the lists again",
           ({k: type(v).__name__ for k, v in d1.items()}, {k: type(v).__name__ for k, v in d2.items()}))
        d3, _z = N._smart_domain_refresh([UNION], r, files=True)
        ok(isinstance(d3.get(UNION), N._Pulled) and list(d3[UNION]) == unames,
           "[1] back to Hybrid: by file again, iterating it gives the list's names", type(d3.get(UNION)).__name__)
        def body(src, fn):                                         # a function's code without its docstring
            f = next(x for x in ast.parse(src).body if isinstance(x, ast.FunctionDef) and x.name == fn)
            b = f.body[1:] if f.body and isinstance(f.body[0], ast.Expr) and isinstance(getattr(f.body[0], "value", None), ast.Constant) else f.body
            return [ast.dump(x) for x in b]
        ok(S._DOM_RE.pattern == N._DOM_RE.pattern and S.FILES_KEY == N.SNI_FILES_KEY
           and all(body(nsrc, fn) == body(ssrc, fn) for fn in ("_in_sorted", "_nb_under")),
           "[4] swg-sni's name expression, map key, search and cut are swg-noded's", (S._DOM_RE.pattern, N._DOM_RE.pattern))
        # a file renamed in after the check: the object still reads the CHECKED file (the one swg-sni maps), the next pass the new
        up = os.path.join(N.GEO_DIR, UNION + ".doms")
        open(up + ".tmp", "w").write("".join(x + "\n" for x in sorted(set(ul) | {"late.example"})))
        os.replace(up + ".tmp", up)
        pl = d3[UNION]
        ok(pl.holds(["late.example", "tracker.com", "nope.example"]) == {"tracker.com"} and list(pl) == unames,
           "[4] a file replaced after the check: the list still reads the file it checked", sorted(pl.holds(["late.example", "tracker.com"])))
        d4, _z = N._smart_domain_refresh([UNION], r, files=True)
        ok(isinstance(d4.get(UNION), N._Pulled) and d4[UNION].stamp != pl.stamp
           and d4[UNION].holds(["late.example"]) == {"late.example"}, "[4] …and the next refresh checks it and takes its stamp",
           (getattr(d4.get(UNION), "stamp", None), pl.stamp))
        t0 = os.stat(up).st_mtime_ns                               # the same size and mtime, another file: re-checked all the same
        open(up + ".tmp", "w").write("".join(x + "\n" for x in sorted(set(ul) | {"latf.example"})))
        os.utime(up + ".tmp", ns=(t0, t0))
        os.replace(up + ".tmp", up)
        d5, _z = N._smart_domain_refresh([UNION], r, files=True)
        ok(isinstance(d5.get(UNION), N._Pulled) and d5[UNION].stamp == (os.stat(up).st_ino, t0, os.stat(up).st_size)
           and d5[UNION].holds(["late.example", "latf.example"]) == {"latf.example"},
           "[4] a file renamed in at the same size and mtime is checked again", getattr(d5.get(UNION), "stamp", None))

        # ── [3] a list replaced while mapped ──
        d = tempfile.mkdtemp(dir=tmp)
        lp = os.path.join(d, "L.doms")
        mp = os.path.join(d, "sni-map.json")

        def name_it(present=True):                                 # what swg-noded writes once it has checked the file there
            if present:
                st = os.stat(lp)
                fl = {"L": {"path": lp, "stamp": [st.st_ino, st.st_mtime_ns, st.st_size]}}
            json.dump({N.SNI_FILES_KEY: fl} if present else {}, open(mp + ".tmp", "w"))
            os.replace(mp + ".tmp", mp)
            os.utime(mp, ns=(os.stat(mp).st_mtime_ns + 10 ** 9,) * 2)   # a new mtime whatever the clock's grain

        def put(body):
            open(lp + ".tmp", "w").write(body)
            os.replace(lp + ".tmp", lp)

        def m(*hs):
            return tuple(c._match(h) for h in hs)

        put("one.example\ntwo.example\n"); name_it()
        c = S.Classifier(mp, N.SMART_NFT_TABLE, learn_ttl=3600)
        before = m("one.example", "three.example")
        put("three.example\ntwo.example\n")
        c._reload()
        mid = m("one.example", "three.example")
        name_it(); c._reload()
        after = m("one.example", "three.example")
        ok(before == (("L",), ()) and mid == before and after == ((), ("L",)),
           "[3] a list replaced while mapped: the checked content until the map names the new file, then the new", (before, mid, after))
        os.remove(lp); c._reload()
        gone = m("three.example")
        name_it(False); c._reload()
        ok(gone == (("L",),) and m("three.example") == ((),),
           "[3] a list removed keeps its mapping until the map drops it, then answers nothing", (gone, m("three.example")))
        put("a_b.example\nok.example\n"); name_it()
        real = S.mmap
        S.mmap = type("M", (), {"ACCESS_READ": real.ACCESS_READ, "mmap": staticmethod(lambda *a, **k: (_ for _ in ()).throw(OSError(24, "EMFILE")))})
        try:
            c._reload()
            failed = m("ok.example")
        finally:
            S.mmap = real
        c._reload()
        ok(failed == ((),) and m("a_b.example", "ok.example") == ((), ("L",)),
           "[3] a failed map answers nothing and is tried again; a mapped line that is not a name never answers",
           (failed, m("a_b.example", "ok.example")))
        put("four.example\n"); name_it(); c._reload()
        put("five.example\n"); real = S.mmap
        S.mmap = type("M", (), {"ACCESS_READ": real.ACCESS_READ, "mmap": staticmethod(lambda *a, **k: (_ for _ in ()).throw(OSError(24, "EMFILE")))})
        try:
            name_it(); c._reload()
            held = m("four.example", "five.example")
        finally:
            S.mmap = real
        c._reload()
        ok(held == (("L",), ()) and m("four.example", "five.example") == ((), ("L",)),
           "[3] a failed re-map keeps the mapping held, and the next tick maps the new file", (held, m("four.example", "five.example")))
        put("six.example\n"); name_it(); put("seven.example\n")   # the map names a file the pull has already replaced
        c._reload()
        race = m("five.example", "six.example", "seven.example")
        name_it(); c._reload()
        ok(race == (("L",), (), ()) and m("five.example", "seven.example") == ((), ("L",)),
           "[3] a map naming a file no longer there: the file now there is not mapped until the map names it",
           (race, m("five.example", "seven.example")))

        # ── [4] swg-noded's check ──
        def one(lines, raw=None):
            p = os.path.join(N.GEO_DIR, "mc:chk.doms")
            body = raw if raw is not None else "\n".join(lines) + "\n"
            open(p, "w", newline="").write(body)
            N._DOM_CACHE.pop("mc:chk", None)
            N.SNI_FILE_MIN = 1
            return N._smart_domain_refresh(["mc:chk"], {"errors": [], "changed": 0}, files=True)

        good = ["a.example", "b.example", "ru", "su"]
        dd, zz = one(good)
        ok(isinstance(dd.get("mc:chk"), N._Pulled) and N._DOM_CACHE["mc:chk"][1] is None and zz.get("mc:chk") == ["ru", "su"],
           "[4] a clean sorted file: by file, no names kept, the zones returned", (dd, zz))
        for label, lines, raw in (("unsorted", ["b.example", "a.example"], None), ("CRLF", None, "a.example\r\nb.example\r\n"),
                                  ("a trailing space", ["a.example ", "b.example"], None), ("a junk line", ["a.example", "b_c.example"], None),
                                  ("an uppercase name", ["A.example", "b.example"], None), ("an empty line", ["", "a.example"], None)):
            dd, _zz = one(lines, raw)
            ok(isinstance(dd.get("mc:chk"), list), "[4] %s: read as a list, as before" % label, type(dd.get("mc:chk")).__name__)
        N.SNI_FILE_MIN = 1 << 20
        N._DOM_CACHE.pop("mc:chk", None)
        p = os.path.join(N.GEO_DIR, "mc:chk.doms"); open(p, "w").write("a.example\nb.example\n")
        dd, _zz = N._smart_domain_refresh(["mc:chk"], {"errors": [], "changed": 0}, files=True)
        ok(dd.get("mc:chk") == ["a.example", "b.example"], "[4] a file under the floor: a list", dd)
    except Exception as e:
        fails.append("raised %s: %s" % (type(e).__name__, e))
        if not which:
            print("  FAIL raised %s: %s" % (type(e).__name__, e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return fails


RSS_CHILD = r'''
import importlib.machinery, importlib.util, json, os, sys, subprocess
def anon():
    for l in open("/proc/self/status"):
        if l.startswith("RssAnon"):
            return int(l.split()[1]) // 1024
sp, mp, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
l = importlib.machinery.SourceFileLoader("swgsni_rss", sp)
S = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgsni_rss", l)); l.exec_module(S)
S.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")
a0 = anon()
c = S.Classifier(mp, "swg_smart", learn_ttl=3600)
ok = all(c._match("www.n%07d.example.com" % i) == ("big",) for i in range(0, n, 997)) and c._match("n%07dx.example.com" % 5) == ()
print("RESULT " + json.dumps({"growth": anon() - a0, "ok": ok}), flush=True)
'''


def rss_check(ssrc, which=""):
    """[2] a 2,000,000-name list by file: swg-sni's anon memory grows < 20 MB (the dict was ~280 MB)."""
    tmp = tempfile.mkdtemp(prefix="snipulled-rss-")
    try:
        n = 2_000_000
        lp = os.path.join(tmp, "big.doms")
        with open(lp, "w") as f:
            f.write("".join("n%07d.example.com\n" % i for i in range(n)))
        mp = os.path.join(tmp, "sni-map.json")
        st = os.stat(lp)
        json.dump({"~files": {"big": {"path": lp, "stamp": [st.st_ino, st.st_mtime_ns, st.st_size]}}}, open(mp, "w"))
        sp = os.path.join(tmp, "sni.py"); open(sp, "w").write(ssrc)
        r = _RUN([sys.executable, "-c", RSS_CHILD, sp, mp, str(n)], capture_output=True, text=True, timeout=300)
        try:
            out = json.loads([ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")][-1][7:])
        except Exception:
            out = {"growth": None, "ok": False, "rc": r.returncode, "err": (r.stderr or "")[-300:], "out": (r.stdout or "")[-300:]}
        good = out.get("ok") and out.get("growth") is not None and out["growth"] < 20
        if not which:
            print(("  PASS " if good else "  FAIL ") + "[2] 2,000,000 names by file: swg-sni anon +%s MB, lookups %s"
                  % (out.get("growth"), "right" if out.get("ok") else "WRONG"), "" if good else out)
        return [] if good else ["[2] rss"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    nsrc, ssrc = open(NODED, encoding="utf-8").read(), open(SNI, encoding="utf-8").read()
    if "--perturb" in sys.argv:
        missed = []
        only = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--only=")]
        for name, (which, *pairs) in PLANTS.items():
            if only and name not in only:
                continue
            reps = pairs[0] if isinstance(pairs[0], list) else [tuple(pairs)]
            src = nsrc if which == "noded" else ssrc
            if any(src.count(a) != 1 for a, _b in reps):
                print("PLANT %-12s anchor missing — fix the plant" % name); missed.append(name); continue
            for a, b in reps:
                src = src.replace(a, b)
            ns, ss = (src, ssrc) if which == "noded" else (nsrc, src)
            f = run_checks(ns, ss, which=name)
            if which == "sni":
                f += rss_check(ss, which=name)
            print("PLANT %-12s %s" % (name, ("RED  (" + f[0][:90] + ")") if f else "GREEN — NOT CAUGHT"))
            if not f:
                missed.append(name)
        print("perturb:", "all caught" if not missed else "MISSED " + ", ".join(missed))
        return 1 if missed else 0
    f = run_checks(nsrc, ssrc) + rss_check(ssrc)
    print("sni_pulled_file_selftest:", "PASS" if not f else "FAIL (%d)" % len(f))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
