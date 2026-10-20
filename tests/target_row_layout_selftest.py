#!/usr/bin/env python3
"""Self-test: the deployment rows fit their content (operator, 2026-10-20: in the Edit peer sheet a "TURN ×4" badge
pushed the address and gear off the row, the list grew a sideways scrollbar, and one proxy's name was cropped to its
middle, "INGS-" of WINGS-N). Renders the REAL app.css in headless Chrome with the markup the two lists carry and
measures the boxes. The markup is a copy of js/sheets-crud.js — the Edit peer sheet's Deployments list (~line 1064:
RoleToggle ★, PubTag, TargetFrontBadge, the address or "auto IP", the gear only once its config has loaded) and
TargetPicker (~line 289: no ★, a "missing" tag on a deployment whose interface is gone) — and of TargetFrontBadge
(~line 182: one proxy, several behind the hover wrapper, a hidden one with its "off" icon, the name in .tgt-ttl).

Widths are the lists' real ones: a sheet's width less its border (2) and body padding (40); the list's own
padding-right is part of the list — Edit peer 880 → 838, New peer / Peer targets 620 → 578, and on a 390px phone the
overlay's 18px side padding leaves a 354px sheet → 312.

  [1] at Edit peer's width (both lists) and the create sheets' (the picker — the ★ list is Edit peer's alone) nothing
      leaves its row and the list does not scroll sideways
  [2] "TURN ×4" and "WINGS-N" show whole; a long proxy name is cut at its END with an ellipsis (never at both ends), and
      a hidden badge keeps its "off" icon whole
  [3] at every width each list's address column lines up — rows with and without a gear, "auto IP" rows, ★ or not —
      and on a phone every usual row of a list keeps the same width (the list scrolls as one)
  [4] the ★-less picker keeps the narrower column (the ★'s room is not taken from its names)
  [5] at every width every interface and "missing" tag shows whole on one line, clear of the badges, and every node
      name keeps a readable width (whole, or ≥ 7ch with an ellipsis); a long node name is cut instead of widening its
      row; a row whose name area needs more than 220px (a 15-character interface beside "missing" — the #edge list)
      grows instead of overlapping; on a phone every control stays inside its row's border

Hermetic. Run: python3 tests/target_row_layout_selftest.py   (0 = pass)
     --perturb-width   the ★ list's column back at 296px (sized before the ★ joined it) → RED in [1]/[2]
     --perturb-ellip   no ellipsis span rule (the badge's name runs on; the icon is cut) → RED in [2]
     --perturb-align   the address is not anchored right → RED in [3]
     --perturb-gear    a gearless row does not keep the gear's place → RED in [3]
     --perturb-nostar  the ★-less picker takes the ★'s width too → RED in [4]
     --perturb-rowmin  a row may go below its content (a phone squeezes the names under the badges) → RED in [5]
     --perturb-floor   no name-area floor (usual rows take their own widths on a phone) → RED in [3]
     --perturb-nmfloor every node name carries the 7ch floor (a short name gets a gap after it) → RED in [5]
     --perturb-nmcut   a node name cannot be cut (a long one runs under the badges) → RED in [5]
     --perturb-tpwrap  an interface may wrap onto two lines → RED in [5]
Needs google-chrome (or $CHROME). A missing browser is a FAIL, never a skip.
"""
import functools, http.server, json, os, shutil, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
FAILS = []
DETAIL = int(os.environ["DETAIL"]) if os.environ.get("DETAIL", "").isdigit() else 500   # how much of a FAIL's detail to print
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + json.dumps(detail, default=str)[:DETAIL]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

# plant → (anchor, replacement, the sections that must go red)
PLANTS = {
    "--perturb-width": (".targetpick:has(.primtog){--topt-col:340px}", ".targetpick:has(.primtog){--topt-col:296px}", ("[1]", "[2]")),
    "--perturb-ellip": (".tgt-front > .tgt-ttl{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
                        ".tgt-front > .tgt-ttl{}", ("[2]",)),
    "--perturb-align": (".targetopt .topt-right > .topt-ip{margin-left:auto}", ".targetopt .topt-right > .topt-ip{}", ("[3]",)),
    "--perturb-gear": (".targetopt .topt-right > .topt-ip:last-child{margin-right:38px}",
                       ".targetopt .topt-right > .topt-ip:last-child{}", ("[3]",)),
    "--perturb-nostar": (".targetpick{--topt-col:300px}", ".targetpick{--topt-col:340px}", ("[4]",)),
    "--perturb-rowmin": (".targetpick > .targetopt{min-width:min-content}", ".targetpick > .targetopt{}", ("[5]",)),
    "--perturb-floor": ("gap:9px;flex:1;cursor:pointer;min-width:calc(7ch + 164px)}", "gap:9px;flex:1;cursor:pointer;min-width:0}", ("[3]",)),
    "--perturb-nmfloor": (".targetopt.missing .nm{min-width:7ch}", ".targetopt .nm{min-width:7ch}", ("[5]",)),
    "--perturb-nmcut": (".targetopt .nm{font-weight:600;flex:0 1 max-content;width:0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
                        ".targetopt .nm{font-weight:600;white-space:nowrap}", ("[5]",)),
    "--perturb-tpwrap": (".targetopt .tp{font-size:13.5px;color:var(--faint);font-family:var(--mono);white-space:nowrap}",
                         ".targetopt .tp{font-size:13.5px;color:var(--faint);font-family:var(--mono)}", ("[5]",)),
}
plant = [a for a in sys.argv[1:] if a in PLANTS]
css = open(os.path.join(ROOT, "app.css"), encoding="utf-8").read()
for p in plant:
    a, b, _ = PLANTS[p]
    if css.count(a) != 1:
        print("PERTURB FAILED — %s: the anchor is not there exactly once" % p); sys.exit(1)
    css = css.replace(a, b)
    print("(perturbed: %s — this run must FAIL)" % p)

OFF = '<span class="ic"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/></svg></span>'
def front(name, col, off=False, many=0):
    """TargetFrontBadge as a publish switch (the edit sheet) — its name in .tgt-ttl, the off icon after it."""
    body = ('turn<b class="turnx">×%d</b>' % many) if many else name
    b = '<button type="button" class="tg tgt-front pubtg%s%s"%s><span class="tgt-ttl">%s</span>%s</button>' % (
        " tgt-front-many" if many else "", " off" if off else "", "" if many else ' style="--tgc:%s"' % col, body, OFF if off else "")
    return '<span class="tgt-frontpop">%s</span>' % b if many else b
def front_plain(name, col):
    """TargetFrontBadge without a peer (TargetPicker on create): a plain span."""
    return '<span class="tg tgt-front" style="--tgc:%s">%s</span>' % (col, name)
ADDR = '<input class="topt-ip" value="%s">'
AUTO = '<span class="topt-ip faint">auto IP</span>'
GEAR = '<button type="button" class="btn btn-mini ico topt-gear">⚙</button>'
LONG = "Helsinki relay backup Frankfurt am Main secondary uplink node 2"     # a 64-character node title (the server's limit)
def row(node, iface, star, chip, fr, addr, gear, missing=False):
    s = '<button type="button" class="primtog%s"><span class="primstar">%s</span></button>' % ((" on", "★") if star == "on" else ("", "☆")) if star else ""
    return ('<div class="targetopt sel locked%s"><div class="topt-main"><span class="box">✓</span><span class="nm">%s</span><span class="tp">%s</span>%s</div>'
            '<div class="topt-right hasprim">%s<button type="button" class="tg tg-%s pubtg">%s</button>%s%s%s</div></div>') % (
                " missing" if missing else "", node, iface, '<span class="topt-missing">missing</span>' if missing else "",
                s, chip, chip, fr, addr, GEAR if gear else "")
EDIT = ('<div class="targetpick" id="edit">'
        + row("msk-shadow", "wg11001", "off", "wg", front("", "", many=4), ADDR % "10.8.0.16", True)
        + row("msk-shadow", "wg11002", "off", "wg", front("WINGS-N", "#C98BE0"), ADDR % "10.9.0.16", True)
        + row("nixos", "awg2", "on", "awg", front("a very long proxy title", "#E0A85F", off=True), ADDR % "10.9.0.161", True)
        + row("svo-im", "wg1", "off", "wg", "", ADDR % "10.8.0.16", False)            # keyed, config not loaded yet: no gear
        + row("msk-main", "csqtt2", "off", "csqtt", "", AUTO, False)                   # self-contained: "auto IP", no gear
        + row(LONG, "wg-home-office", "off", "wg", "", ADDR % "10.21.0.7", True)
        + '</div>')
PICK = ('<div class="targetpick" id="pick">'
        + row("msk-shadow", "wg11001", None, "wg", front_plain("WINGS-N", "#C98BE0"), ADDR % "10.8.0.17", True)
        + row("nixos", "awg2", None, "awg", "", ADDR % "10.9.0.162", True)
        + row("msk-main", "wdtt1", None, "wdtt", front_plain("WDTT", "#5FA8E0"), AUTO, False)
        + row("msk-shadow", "wg11003", None, "wg", "", ADDR % "10.8.0.18", False, missing=True)   # its interface is gone: no badge, no gear
        + row(LONG, "wg-home-office", None, "wg", "", ADDR % "10.21.0.8", True)
        + '</div>')
EDGE = ('<div class="targetpick" id="edge">'                                  # a name area that needs more than 220px
        + row("msk-shadow", "wg-home-office1", None, "wg", "", ADDR % "10.8.0.19", False, missing=True)
        + row("nixos", "awg2", None, "awg", "", ADDR % "10.9.0.163", True)
        + '</div>')
PAGE = ('<!doctype html><html data-theme="light"><head><meta charset="utf-8"><link rel="stylesheet" href="app.css"></head>'
        '<body style="background:var(--surface);padding:0;margin:0"><div class="frame" style="width:838px"><div class="field">'
        + EDIT + '<div style="height:24px"></div>' + PICK + '<div style="height:24px"></div>' + EDGE + '</div></div></body></html>')

D = tempfile.mkdtemp(prefix="rowlayout-")
open(os.path.join(D, "app.css"), "w", encoding="utf-8").write(css)
open(os.path.join(D, "row.html"), "w", encoding="utf-8").write(PAGE)
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=D))
threading.Thread(target=srv.serve_forever, daemon=True).start()

br = tab = None
def done(code):
    for x in (tab, br):
        try:
            x and x.close()
        except Exception:
            pass
    srv.shutdown(); shutil.rmtree(D, True); sys.exit(code)

try:
    from cdp_pipe import Browser, Tab
    br = Browser()
except Exception as e:                                    # no browser: a FAIL, never a skip
    print("FAIL: no headless Chrome (%r)" % e); done(1)

MEASURE = r"""((id) => {
  const r = el => el.getBoundingClientRect();
  const whole = el => el.scrollWidth <= el.clientWidth + 1 && r(el).width > 0;
  const textW = el => { const g = document.createRange(); g.selectNodeContents(el); return g.getBoundingClientRect().width; };
  const oneLine = el => { const g = document.createRange(); g.selectNodeContents(el);     // its text's line boxes: one top
    return new Set([...g.getClientRects()].map(x => Math.round(x.top))).size === 1; };
  const p = document.getElementById(id);
  const rows = [...p.querySelectorAll('.targetopt')].map(o => {
    const col = o.querySelector('.topt-right'), last = col.lastElementChild, ip = o.querySelector('.topt-ip');
    const nm = o.querySelector('.nm'), tp = o.querySelector('.tp'), mi = o.querySelector('.topt-missing');
    const f = o.querySelector('.tgt-front'), t = f && (f.querySelector('.tgt-ttl') || f), ic = f && f.querySelector('.ic');
    return {row: r(o).right, w: Math.round(r(o).width), main: Math.round(r(o.querySelector('.topt-main')).width), last: r(last).right, ipLeft: Math.round(r(ip).left), col: Math.round(r(col).width),
            colStart: Math.round(r(col).left),
            nm: {text: nm.textContent, whole: whole(nm), ellip: getComputedStyle(nm).textOverflow, end: Math.round(r(nm).right), wd: Math.round(r(nm).width),
                 tight: r(nm).width <= textW(nm) + 1},   // the box no wider than its text: no gap before the interface
            tp: {whole: whole(tp) && oneLine(tp), end: Math.round(r(tp).right)},
            mi: mi ? {whole: whole(mi) && oneLine(mi), end: Math.round(r(mi).right)} : null,
            front: f ? {text: f.textContent, clipped: t.scrollWidth > t.clientWidth + 1, ellip: getComputedStyle(t).textOverflow,
                        icon: ic ? {r: r(ic).right, fr: r(f).right, w: r(ic).width} : null} : null};
  });
  return {rows, scroll: p.scrollWidth - p.clientWidth};
})"""

tab = Tab(br)
tab.goto("http://127.0.0.1:%d/row.html" % srv.server_address[1])
for _ in range(100):
    if tab.ev("document.readyState") == "complete" and tab.ev("!!document.querySelector('#pick .targetopt') && document.styleSheets.length > 0"):
        break
    time.sleep(0.1)
else:
    print("FAIL: the page did not load"); done(1)
def at(w):
    tab.ev("document.querySelector('.frame').style.width = '%dpx'; true" % w)
    return tab.ev(MEASURE + "('edit')"), tab.ev(MEASURE + "('pick')"), tab.ev(MEASURE + "('edge')")
fits = lambda x: all(r["last"] <= r["row"] + 0.5 for r in x["rows"]) and x["scroll"] <= 0
inrow = lambda x: all(r["last"] <= r["row"] + 0.5 for r in x["rows"])
# on a list that scrolls, the rows sitting at the name-area floor; a row whose content outgrows it is wider by design
usual = lambda x: [r for r in x["rows"] if r["main"] <= min(q["main"] for q in x["rows"]) + 1]
aligned = lambda x: len({r["ipLeft"] for r in (x["rows"] if x["scroll"] <= 0 else usual(x))}) == 1   # all rows when nothing scrolls
# every interface and "missing" tag whole on one line; a node name whole or ellipsised; nothing in the name area reaching the column
CH7 = 7 * 7      # 7ch of the name's 600-weight face is ≥ 49px
names = lambda x: all(r["tp"]["whole"] and (r["mi"] is None or r["mi"]["whole"]) and (r["nm"]["whole"] or r["nm"]["wd"] >= CH7)
                      and max(r["nm"]["end"], r["tp"]["end"], (r["mi"] or {}).get("end", 0)) <= r["colStart"] for r in x["rows"])
SHEETS = ((838, "Edit peer (880px)"), (578, "New peer / Peer targets (620px)"), (312, "a 390px phone"))
M = {w: at(w) for w, _ in SHEETS}
E, P, _ = M[838]

print("[1] at the sheets' widths")   # the ★ list is Edit peer's alone; the picker opens in New peer / Peer targets too
check("[1] Edit peer (880px): every row's last control ends inside its row, neither list scrolls sideways",
      fits(M[838][0]) and fits(M[838][1]), M[838][:2])
check("[1] New peer / Peer targets (620px): every row of the picker ends inside its row, the list does not scroll sideways",
      fits(M[578][1]), M[578][1])
check("[1] a picker with a long interface beside \"missing\" fits Edit peer's width", fits(M[838][2]), M[838][2])
print("[2] the front badges")
many, one, long_ = (E["rows"][i]["front"] for i in range(3))
check("[2] \"TURN ×4\" shows whole", bool(many) and not many["clipped"], many)
check("[2] \"WINGS-N\" shows whole", bool(one) and not one["clipped"], one)
check("[2] a long proxy name is cut at its end with an ellipsis", bool(long_) and long_["clipped"] and long_["ellip"] == "ellipsis", long_)
check("[2] …and the hidden badge's \"off\" icon stays whole inside it",
      bool(long_) and bool(long_["icon"]) and long_["icon"]["w"] >= 9 and long_["icon"]["r"] <= long_["icon"]["fr"] + 0.5, long_)
print("[3] the address column")
for w, what in SHEETS:
    e, p, g = M[w]
    check("[3] %s: each list's addresses line up (gear or not, \"auto IP\" too)" % what, aligned(e) and aligned(p) and aligned(g),
          [[r["ipLeft"] for r in x["rows"]] for x in (e, p, g)])
e, p, g = M[312]
check("[3] a 390px phone: every list's usual rows keep one width — the ordinary \"missing\" row too — the pickers' the same",
      len({r["w"] for r in usual(e)}) == 1 and len({r["w"] for r in usual(p) + usual(g)}) == 1 and len(usual(p)) == len(p["rows"]),
      [[(r["w"], r["main"]) for r in x["rows"]] for x in (e, p, g)])
check("[3] …and only the row whose name area outgrows the floor (a long interface beside \"missing\") is wider",
      [r["w"] > usual(g)[0]["w"] for r in g["rows"]] == [True, False], [(r["w"], r["main"]) for r in g["rows"]])
print("[4] the ★-less picker")
check("[4] its column is the ★'s 40px narrower than the edit sheet's", E["rows"][0]["col"] - P["rows"][0]["col"] == 40,
      [E["rows"][0]["col"], P["rows"][0]["col"]])
print("[5] names")
for w, what in SHEETS:
    e, p, g = M[w]
    check("[5] %s: every interface and \"missing\" tag whole on one line, every node name whole or ≥ 7ch, all clear of the badges" % what,
          names(e) and names(p) and names(g), [e, p, g])
    check("[5] %s: every control stays inside its row's border (a row too wide for the sheet grows, it never overlaps)" % what,
          inrow(e) and inrow(p) and inrow(g), [e, p, g])
    check("[5] %s: a node name shown whole is no wider than its text (the interface follows it at the row's gap)" % what,
          all(r["nm"]["tight"] for x in (e, p, g) for r in x["rows"] if r["nm"]["whole"]),
          [[(r["nm"]["text"][:12], r["nm"]["wd"]) for r in x["rows"] if r["nm"]["whole"] and not r["nm"]["tight"]] for x in (e, p, g)])
check("[5] the 64-character node name ends in an ellipsis on the create sheet (it does not widen its row)",
      not M[578][1]["rows"][-1]["nm"]["whole"] and M[578][1]["rows"][-1]["nm"]["ellip"] == "ellipsis" and M[578][1]["scroll"] <= 0, M[578][1])
# a short name shows whole; on a "missing" row the tag shares its room, so at 620px it may end in an ellipsis — but stays readable
check("[5] a short node name shows whole on every desktop sheet (a \"missing\" row's: at least 60px of it)",
      all((r["nm"]["whole"] if r["mi"] is None else r["nm"]["wd"] >= 60) for w in (838, 578) for x in M[w] for r in x["rows"][:-1]),
      [[r["nm"] for r in x["rows"][:-1]] for w in (838, 578) for x in M[w]])

if FAILS:
    print("\n%d FAIL" % len(FAILS))
    if plant:
        want = {s for p in plant for s in PLANTS[p][2]}
        hit = {s for s in want if any(f.startswith(s) for f in FAILS)}
        if hit == want:
            print("PERTURB OK — %s went red" % ", ".join(sorted(hit))); done(0)
        print("PERTURB NOT CAUGHT — %s should have gone red" % ", ".join(sorted(want - hit))); done(1)
    done(1)
print("\nALL PASS")
if plant:
    print("PERTURB NOT CAUGHT — nothing went red"); done(1)
done(0)
