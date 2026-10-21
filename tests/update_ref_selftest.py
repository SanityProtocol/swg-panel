#!/usr/bin/env python3
"""Self-test: a box keeps tracking the ref it was INSTALLED from when it updates itself.

`bootstrap.sh` deliberately supports installing a branch or a tag — `SWG_REF`, or inferred from the URL it
was fetched from — and its own comment says why that inference exists:

    "a panel tracking a pre-release branch SILENTLY DOWNGRADED itself on every one-click update, and the
     version it landed on was the one it had just been told not to use."

That fix covered the bootstrap. It did NOT cover `/usr/local/bin/swg-update` — the fixed root entrypoint the
Update button actually runs — which hardcoded `main` in THREE separate writers. Nothing on the box records
the branch, so there was no way back: measured on the live fleet with `dev` 281 commits ahead of `main`, the
panel and one node had that wrapper installed and `swg-update.timer` enabled and active. One press of Update
and the box would have been rolled back 281 commits, onto code predating the entire feature it was running.

The wrapper is rewritten by every update, so baking the ref into it at write time is enough to keep a box on
its branch — no new state to keep in step, and the next update re-bakes it.

⚠️ AND THERE WAS A FOURTH PATH THIS GATE DID NOT WATCH: a bare-metal NODE has no `swg-update` wrapper at all
(`ensure_update_unit` returns early unless the box carries a panel). Its self-update is `swg-noded`'s own
`DEFAULT_UPDATE_CMD`, which hardcoded `main`, and NO installer wrote the `update_cmd` override that would
have corrected it. So every node installed from a branch or tag would roll itself back on the panel's Update
button — the identical downgrade, in the one place the fix did not reach, and invisible here because this
gate only ever read the three writers that HAVE a wrapper. Found during 1.8.5 qualification, while trying to
run the "install from main, update from dev" cell: the node would have fetched main's bootstrap and the cell
would have passed while measuring nothing.

[5] (1.8.9 qualification IN-8) update.sh's "re-run the host installer" hint (the panel unit is missing) names the ref the
    box follows — `SWG_REF=dev; ` inside the string and dev's bootstrap — not main: followed on a dev box, it re-installed main

[6] (1.8.10) the branch a node's Update button installs from is SHOWN when it is not main: one hand-update from dev
    records dev for good, and hel-flux (production) followed dev unseen — it stayed on 1.8.8 when the operator updated
    the fleet in the minute dev lagged main (2026-10-20). noded reports `update_ref` only where its own updater runs
    (not a container, a declarative host, a trigger or an operator's update_cmd) and only when it is not main; the
    panel passes it on in the node record; the node page says "from <ref>" beside the version.

Run: python3 tests/update_ref_selftest.py (0 = pass).  --perturb restores the hardcoded `main`.
     --perturb-hint   the hint pinned to main again (e66018f) → RED on [5] only
     --perturb-shown  a container reports its ref too → RED on [6] only
     --perturb-custom a node running an operator's own update_cmd does not say so (the first cut) → RED on [6] only
     --perturb-viahost a master's own node never says so, even when its header offers "update node to" (1.8.10, r1810b
                      F16) → RED on [6] only
[7] (1.8.10) the PANEL HOST's updater (/usr/local/bin/swg-update) follows the ref baked into it at install/update; the
    panel reads that one machine-written line (cached by mtime) and reports panel_update_ref when it is not main; the
    header and a master's own node page say "from <ref>" (swgt: dev, unseen, 2026-10-20).
     --perturb-panelmain   main is reported too → RED on [7] only
     --perturb-panelcache  the cache never notices a rewritten wrapper → RED on [7] only
     --perturb-panelfail   a failed read is cached (the label gone until the next update) → RED on [7] only
     --perturb-panelino    the cache key ignores the inode (a same-size rename in the same second) → RED on [7] only
     --perturb-paneldecl   a NixOS panel reports a bare-metal wrapper left behind → RED on [7] only
     --perturb-panelslash  the panel's reader takes a ref with a `/` that update.sh's read-back refuses → RED on [7] only
"""
import contextlib, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
PERTURB_HINT = "--perturb-hint" in sys.argv
PERTURB_SHOWN = "--perturb-shown" in sys.argv
PERTURB_CUSTOM = "--perturb-custom" in sys.argv
PERTURB_PANELMAIN = "--perturb-panelmain" in sys.argv
PERTURB_PANELCACHE = "--perturb-panelcache" in sys.argv
PERTURB_PANELFAIL = "--perturb-panelfail" in sys.argv
PERTURB_PANELINO = "--perturb-panelino" in sys.argv
PERTURB_PANELDECL = "--perturb-paneldecl" in sys.argv
PERTURB_PANELSLASH = "--perturb-panelslash" in sys.argv
PERTURB_VIAHOST = "--perturb-viahost" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

WRITERS = ("update.sh", "lib/common.sh", "install-host.sh")
# the NODE side: the daemon that owns the command, and the two installers that record the ref for it
NODE_SRC = ("swg-noded", "install-node.sh", "install-host.sh", "update.sh")
srcs = {f: open(os.path.join(ROOT, f), encoding="utf-8").read() for f in WRITERS}
if PERTURB:
    # ⚠️ ASSERT THE ANCHOR: the one text lives in lib/common.sh now; a replace that finds it nowhere plants nothing (round 10)
    assert sum(srcs[f].count("swg-panel/${_swg_ref}/bootstrap.sh") for f in srcs) >= 1, \
        "perturbation anchor missing (swg-panel/${_swg_ref}/bootstrap.sh) — this run would FALSE-PASS"
    for f in srcs:
        srcs[f] = srcs[f].replace("swg-panel/${_swg_ref}/bootstrap.sh", "swg-panel/main/bootstrap.sh")

print("\n[1] every writer of the update wrapper bakes the ref")
# ONE TEXT (round 8): swg_update_wrapper_text in lib/common.sh; the three writers render it with the ref they resolved.
m = re.search(r"^swg_update_wrapper_text\(\)\{.*?\nWRAP\n\}\n", srcs["lib/common.sh"], re.S | re.M)
text = m.group(0) if m else ""
# ⚠️ THE ASSIGNMENT, not any mention. This matched the first line CONTAINING the name, and a
# comment added above it silently took that slot — the gate then judged prose instead of code.
urls = [l for l in text.splitlines() if l.lstrip().startswith('URL="')]
check("the wrapper text (lib/common.sh swg_update_wrapper_text) sets URL once", len(urls) == 1, urls)
check("…and its default names the ref it is handed, not `main`",
      bool(urls) and "${_swg_ref}" in urls[0] and "/main/bootstrap.sh" not in urls[0], urls[0] if urls else "")
for f in WRITERS:
    body = srcs[f]
    check("%s writes the wrapper from that text, with the ref it resolved" % f, 'swg_update_wrapper_text "$_swg_ref"' in body)
    check("…resolved with `main` only as the fallback",
          '_swg_ref="${SWG_REF:-main}"' in body, "no _swg_ref default in " + f)

print("\n[2] bootstrap tells them which ref that is")
boot = open(os.path.join(ROOT, "bootstrap.sh"), encoding="utf-8").read()
check("bootstrap EXPORTS the ref it resolved", 'export SWG_REF="$REF"' in boot,
      "SWG_REF is computed but never exported — nothing downstream can know it")
check("…after the default is applied, so it is never empty",
      boot.index('export SWG_REF="$REF"') > boot.index('REF="${REF:-main}"'))

print("\n[3] the generated wrapper is correct for each ref, and keeps its runtime overrides")
tmpl = urls[0] if urls else 'URL=""'
for ref, want in (("", "main"), ("dev", "dev"), ("v1.9.0", "v1.9.0")):
    out = subprocess.run(["bash", "-c", '_swg_ref="${SWG_REF:-main}"; cat <<WRAP\n%s\nWRAP' % tmpl],
                         capture_output=True, text=True, env={**os.environ, "SWG_REF": ref}).stdout
    check("SWG_REF=%-7r bakes %s" % (ref or "(unset)", want),
          ("swg-panel/%s/bootstrap.sh" % want) in out, out.strip()[:110])
    # ⚠️ the heredoc is UNQUOTED so the ref expands — every OTHER $ must still reach the file intact, or the
    # wrapper loses the override the operator uses to point one box somewhere else.
    check("…and `${SWG_BOOTSTRAP_URL}` survives to the file", "${SWG_BOOTSTRAP_URL:-" in out, out.strip()[:110])

print("\n[3b] ⚠️ THE SEAM — the baked ref must REACH bootstrap, not merely sit in the wrapper")
# [3] proved the URL carries the ref. It does not prove bootstrap can SEE it. The wrapper used the baked
# URL only as a shell DEFAULT for $SWG_BOOTSTRAP_URL and never exported it, so the piped bash inherited an
# UNSET variable, `_ref_from_url ""` returned nothing, and REF fell back to `main` — the wrapper fetched
# dev's bootstrap and installed main from it. Both ends were green and the wire between them carried
# nothing. Measured on swgt: panel 1.8.6-beta -> 1.8.5-beta and the wrapper dev -> main, on one press.
# ⚠️ ALL THREE WRITERS, and the omission here is why this shipped. Twenty lines above, section [1] loops
# `WRITERS` — update.sh, lib/common.sh AND install-host.sh — to check each BAKES the ref. This loop then
# checked only two of the same three for the EXPORT, so `install-host.sh` was verified for half the fix and
# not the other half, in one file, by two loops over the same subject. A FRESH install from a branch
# therefore wrote a wrapper that would fetch dev's bootstrap and install main from it — found by installing
# dev onto a wiped box and reading the wrapper (`exports=0`, where the update path writes 1), not by
# reading the source. [[two-readers-one-grammar]]
# (round 8: ONE text — every writer renders swg_update_wrapper_text, which [1] proved each of them calls)
check("the one wrapper text EXPORTS the URL so bootstrap can infer from it", 'export SWG_BOOTSTRAP_URL=' in text,
      "the ref is baked into a variable bootstrap never sees")

# …and drive it: build the wrapper for a ref, run it with a stubbed curl+bash, and read what REF bootstrap
# would resolve. This is the only check here that exercises the two together.
_tmpl_lines = [l for l in text.splitlines()
               if l.lstrip().startswith(('URL="', "export SWG_BOOTSTRAP_URL=", "curl -fsSL"))]
_wrap = "\n".join(_tmpl_lines)
_infer = """
_ref_from_url(){ printf '%s' "${1:-}" | sed -nE \
    -e 's#^https?://raw\\.githubusercontent\\.com/[^/]+/[^/]+/([^/]+)/.*#\\1#p' \
    -e 's#^https?://[^/]+/[^/]+/[^/]+/raw/([^/]+)/.*#\\1#p' | sed -n 1p; }
REF="${SWG_REF:-}"; [ -z "$REF" ] && REF="$(_ref_from_url "${SWG_BOOTSTRAP_URL:-}")"; echo "REF=${REF:-main}"
"""
for ref, want in (("dev", "dev"), ("v1.9.0", "v1.9.0"), ("", "main")):
    script = ('_swg_ref="${SWG_REF:-main}"\n'
              'cat <<WRAP > /tmp/_swgwrap.$$\n' + _wrap.replace("curl -fsSL", "# curl") + '\nWRAP\n'
              'curl(){ :; }\n'
              '. /tmp/_swgwrap.$$\n'
              'unset SWG_REF\n'          # bootstrap is a FRESH process: only what the wrapper exported survives
              + _infer + '\nrm -f /tmp/_swgwrap.$$\n')
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                         env={**os.environ, "SWG_REF": ref}).stdout
    check("wrapper baked with %-8r -> bootstrap resolves REF=%s" % (ref or "(unset)", want),
          ("REF=%s" % want) in out, out.strip()[:160])

print("\n[4] THE NODE — it has no wrapper, so the ref has to reach it another way")
nsrc = {f: open(os.path.join(ROOT, f), encoding="utf-8").read() for f in NODE_SRC}
if PERTURB:
    # ⚠️ PLANT ACROSS THE WHOLE ASSIGNMENT, AND ASSERT IT WAS FOUND. This used to replace one exact first line;
    # when the template grew an API door (86b46f6) that line no longer existed, `.replace` changed nothing, and
    # the node checks below stayed GREEN under --perturb. The template now carries {ref} three times (raw URL,
    # API door, SWG_REF), so the hardcoded-main shape is every one of them.
    _tm = re.search(r"^UPDATE_CMD_TMPL = \(.*?\)\n", nsrc["swg-noded"], re.S | re.M)
    assert _tm and "{ref}" in _tm.group(0), "UPDATE_CMD_TMPL not found — this perturbation would plant nothing"
    nsrc["swg-noded"] = nsrc["swg-noded"].replace(_tm.group(0), _tm.group(0).replace("{ref}", "main"), 1)
    for f in ("install-node.sh", "install-host.sh"):
        nsrc[f] = re.sub(r'\n\s*"update_ref": "\$\{_swg_[a-z_]*ref\}"', "", nsrc[f])
    assert nsrc["update.sh"].count("  ensure_node_update_ref #") == 1, "perturbation anchor missing in update.sh — this run would FALSE-PASS"
    nsrc["update.sh"] = nsrc["update.sh"].replace("  ensure_node_update_ref #", "  #")

check("swg-noded's self-update command is a TEMPLATE, not a hardcoded ref",
      "{ref}" in nsrc["swg-noded"] and "swg-panel/main/" not in nsrc["swg-noded"],
      [l for l in nsrc["swg-noded"].splitlines() if "UPDATE_CMD_TMPL" in l][:1])
check("…and it defaults to main when nothing recorded a ref",
      'DEFAULT_UPDATE_REF = "main"' in nsrc["swg-noded"])
for f in ("install-node.sh", "install-host.sh"):
    check("%s records the installed ref for the node" % f, '"update_ref"' in nsrc[f])
    # install-node.sh defaults a hand-run re-install to the branch the node ALREADY follows (EXIST_REF), then main —
    # still SWG_REF first and main last; tests/node_track_ref_selftest.py [3] exercises it.
    check("…from SWG_REF, defaulting to main",
          re.search(r'_swg_[a-z_]*ref="\$\{SWG_REF:-(main|\$\{EXIST_REF:-main\})\}"', nsrc[f]) is not None)

# and the command it actually builds, for each ref — driven through the real function
import importlib.machinery, importlib.util, shutil
_dir = tempfile.mkdtemp(prefix="noded-ref-")     # not tests/: each run left a ~1.5 MB pyc in tests/__pycache__ for good, and
_fd, _tmp = tempfile.mkstemp(suffix=".py", prefix="noded-ref-", dir=_dir)   # a gate copying the tree could lose the copy
_nsrc = nsrc["swg-noded"]
if PERTURB_SHOWN:
    _a = '    return update_auto() and not os.environ.get("SWG_UPDATE_TRIGGER")\n'
    assert _nsrc.count(_a) == 1, "perturbation anchor missing — would FALSE-PASS"
    _nsrc = _nsrc.replace(_a, '    return not os.environ.get("SWG_UPDATE_TRIGGER")\n')
if PERTURB_CUSTOM:
    _a = '    return bool(_own_updater_runs() and own_update_cmd(node_cfg))\n'
    assert _nsrc.count(_a) == 1, "perturbation anchor missing — would FALSE-PASS"
    _nsrc = _nsrc.replace(_a, '    return False\n')
os.write(_fd, _nsrc.encode()); os.close(_fd)
_l = importlib.machinery.SourceFileLoader("nodedref", _tmp)
_m = importlib.util.module_from_spec(importlib.util.spec_from_loader("nodedref", _l))
try: _l.exec_module(_m)
except SystemExit: pass
shutil.rmtree(_dir, ignore_errors=True)
for ref, want in ((None, "main"), ("dev", "dev"), ("v1.9.0", "v1.9.0"), ("", "main"),
                  ("evil;rm -rf /", "main")):
    cfg = {"node": ({} if ref is None else {"update_ref": ref})}
    got = _m.default_update_cmd(cfg)
    check("update_ref=%-14r -> %s" % (ref, want), ("swg-panel/%s/" % want) in got, got[:120])
check("an explicit update_cmd still wins outright",
      "MINE" in (({"node": {"update_cmd": "MINE", "update_ref": "dev"}}.get("node") or {}).get("update_cmd")))

# ⚠️ AN UPDATE MUST RE-RECORD IT TOO. The installers write `update_ref` at install time and an update does
# NOT rewrite config.json — so a node installed from main and then updated to dev kept no ref at all and
# fell back to main, i.e. the downgrade survived the very update meant to fix it. Caught on hel-flux by
# checking the config AFTER a real main->dev update, not by reading the installer.
check("update.sh HEALS the node's update_ref on every update",
      "ensure_node_update_ref" in nsrc["update.sh"]
      and re.search(r"^\s*ensure_node_update_ref\b", nsrc["update.sh"], re.M) is not None,
      "the heal is defined but never called" if "ensure_node_update_ref()" in nsrc["update.sh"] else "absent")
check("…from SWG_REF, defaulting to main",
      're.search' and 'want="${SWG_REF:-main}"' in nsrc["update.sh"])

print("\n[5] update.sh's hint for a missing panel unit names the box's ref (IN-8)")
U = open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read()
m = re.search(r"^ensure_panel_unit_warn\(\)\{.*?^\}\n", U, re.S | re.M)
HINT = m.group(0) if m else ""
if PERTURB_HINT:
    _a = re.search(r'\n  local _r=[^\n]*\n  warn "    sudo bash -c[^\n]*\n', HINT)
    assert _a, "perturbation anchor missing — would FALSE-PASS"
    HINT = HINT.replace(_a.group(0), "\n  warn '    sudo bash -c \"$(curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh)\" -- host'\n")
_pd = tempfile.mkdtemp(prefix="unitwarn-"); open(os.path.join(_pd, "swg-panel-server"), "w").close()
assert HINT.count("/etc/systemd/system/swg-panel-server.service") == 1, "the unit check is not where [5] reads it"
HINT = HINT.replace("/etc/systemd/system/swg-panel-server.service", _pd + "/no-such.service")   # the unit is missing, on any box
for ref, want in (("dev", 'sudo bash -c "SWG_REF=dev; $(curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/dev/bootstrap.sh)" -- host'),
                  ("main", 'sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh)" -- host'),
                  (None, 'sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh)" -- host')):
    env = {k: v for k, v in os.environ.items() if k != "SWG_REF"}
    if ref is not None:
        env["SWG_REF"] = ref
    r = subprocess.run(["bash", "-c", 'set -euo pipefail\nwarn(){ echo "WARN $*"; }; PANEL_DIR=%s; DID_FAIL=no\n%s\nensure_panel_unit_warn\necho "FAIL=$DID_FAIL"'
                        % (_pd, HINT)], capture_output=True, text=True, env=env)
    line = next((l for l in r.stdout.splitlines() if "bootstrap.sh" in l), "")
    check("SWG_REF=%-7s → the hint names %s" % (ref if ref is not None else "(unset)", "dev, inside the string" if ref == "dev" else "main"),
          line.strip().endswith(want) and "FAIL=yes" in r.stdout, (line, r.stderr[-200:]))

print("\n[6] a node's non-main update branch is shown (1.8.10)")
def shown(ref, kind="bare-metal", declarative=False, trigger="", cmd="", fn="update_ref_shown"):
    _m.NODE_KIND, _m.NODE_DECLARATIVE = kind, declarative
    old = os.environ.pop("SWG_UPDATE_TRIGGER", None)
    if trigger:
        os.environ["SWG_UPDATE_TRIGGER"] = trigger
    try:
        n = {} if ref is None else {"update_ref": ref}
        if cmd:
            n["update_cmd"] = cmd
        return getattr(_m, fn)({"node": n})
    finally:
        os.environ.pop("SWG_UPDATE_TRIGGER", None)
        if old is not None:
            os.environ["SWG_UPDATE_TRIGGER"] = old
_s6 = []
for args, want, what in (((("dev",), {}), "dev", "a bare node on dev reports dev"),
                         (((None,), {}), "", "…one with no ref recorded (main) reports nothing"),
                         ((("main",), {}), "", "…one on main reports nothing"),
                         ((("v1.9.0",), {}), "v1.9.0", "…a tag is reported as it is"),
                         ((("evil;rm -rf /",), {}), "", "…an unsafe ref reads as main and reports nothing"),
                         ((("dev",), {"kind": "docker"}), "", "a container on dev reports nothing (its image updates it)"),
                         ((("dev",), {"declarative": True}), "", "a declarative host reports nothing (its configuration updates it)"),
                         ((("dev",), {"trigger": "/run/swg/update"}), "", "a node with an update trigger reports nothing"),
                         ((("dev",), {"cmd": "MINE"}), "", "a node running an operator's own update_cmd reports no ref (update_custom says it)")):
    got = shown(*args[0], **args[1])
    check("[6] %s" % what, got == want, repr(got)); _s6.append(what)
SWGT = ("curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/dev/bootstrap.sh"
        " | SWG_REF=dev bash -s update -y --no-components --node-only")
for (a, kw), want, what in ((((None,), {"cmd": SWGT}), True, "an own update_cmd is reported as update_custom (swgt's dev-pinned one)"),
                            (((None,), {"cmd": ["bash", "/root/up.sh", 1]}), True, "…a list one too, never parsed (a hand-edited int cannot break the snapshot)"),
                            ((("dev",), {}), False, "…no update_cmd: no update_custom"),
                            ((("dev",), {"cmd": SWGT, "kind": "docker"}), False, "…a container: none (its image updates it)"),
                            ((("dev",), {"cmd": SWGT, "trigger": "/run/swg/update"}), False, "…a trigger: none")):
    got = shown(*a, fn="update_custom_shown", **kw)
    check("[6] %s" % what, got is want, repr(got))
check("[6] build_snapshot carries it, only when there is one (computed once per snapshot)",
      '_uref = update_ref_shown(node_cfg)' in nsrc["swg-noded"] and '**({"update_ref": _uref} if _uref else {}),' in nsrc["swg-noded"]
      and '_ucustom = update_custom_shown(node_cfg)' in nsrc["swg-noded"] and '**({"update_custom": True} if _ucustom else {}),' in nsrc["swg-noded"])
_fn = lambda name: (re.search(r"^def %s\(.*?(?=^def )" % name, nsrc["swg-noded"], re.S | re.M) or re.search("$", "")).group(0)
check("[6] the report and the command share one rule for an operator's own update_cmd (own_update_cmd)",
      "cmd = own_update_cmd(node_cfg) or default_update_cmd(node_cfg)" in nsrc["swg-noded"]
      and "own_update_cmd(node_cfg)" in _fn("update_ref_shown") and "own_update_cmd(node_cfg)" in _fn("update_custom_shown"))
_P = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
check("[6] the panel passes update_custom on as a strict boolean", '"update_custom": snap.get("update_custom") is True,' in _P)
check("[6] the panel's node record passes it on, kept to a ref's characters",
      '"update_ref": _uref if re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", _uref := str(snap.get("update_ref") or "")) else "",' in _P)
_SN = open(os.path.join(ROOT, "js", "screen-nodes.js"), encoding="utf-8").read()
if PERTURB_VIAHOST:
    _a = "          if (nrec.update_custom && !viaHost) return"
    assert _SN.count(_a) == 1, "perturbation anchor missing — would FALSE-PASS"
    _SN = _SN.replace(_a, "          if (nrec.update_custom && !nrec.local) return")
_RU = open(os.path.join(ROOT, "js", "lang", "ru.js"), encoding="utf-8").read()
check("[6] the node page says \"from <ref>\" beside the version, and why in its title",
      'const ref = viaHost ? Store.panelUpdateRef : nrec.update_ref;' in _SN
      and ': T("Update installs {ref}, not the latest release — this node was installed' in _SN
      and 'T("from {ref}", { ref })' in _SN)
check("[6] a node running its own update command says so beside the version, and how to undo it in the title — a master's "
      "own node too when its header offers \"update node to\" (that button runs the node's own updater; r1810b F16)",
      'const viaHost = nrec.local && !(nrec.outdated && !Store.panelOutdated);' in _SN
      and 'if (nrec.update_custom && !viaHost) return html`<span class="nm-ver out" title=${T("Update runs this node\'s own update command' in _SN
      and "Remove it there and restart swg-noded to follow releases again." in _SN
      and '${T("own update command")}' in _SN)
check("[6] …in Russian too", '"from {ref}": "из {ref}"' in _RU and '"Update installs {ref}, not the latest release' in _RU
      and '"own update command": "своя команда обновления"' in _RU and "\"Update runs this node's own update command" in _RU)

print("\n[7] the panel host's updater ref (1.8.10)")
_psrc = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
if PERTURB_PANELMAIN:
    _a = '        _WRAPPER_REF.update(key=key, ref="" if ref == "main" else ref)\n'
    assert _psrc.count(_a) == 1, "perturbation anchor missing — would FALSE-PASS"
    _psrc = _psrc.replace(_a, '        _WRAPPER_REF.update(key=key, ref=ref)\n')
if PERTURB_PANELCACHE:
    _a = '    if _WRAPPER_REF["key"] != key:\n'
    assert _psrc.count(_a) == 1, "perturbation anchor missing — would FALSE-PASS"
    _psrc = _psrc.replace(_a, '    if _WRAPPER_REF["key"] is None:\n')
if PERTURB_PANELFAIL:
    _a = '            return ""                           # not cached: the next poll reads it again\n'
    assert _psrc.count(_a) == 1, "perturbation anchor missing — would FALSE-PASS"
    _psrc = _psrc.replace(_a, '            _WRAPPER_REF.update(key=key, ref=""); return ""\n')
if PERTURB_PANELINO:
    _a = '    key = (st.st_ino, st.st_mtime_ns, st.st_size)\n'
    assert _psrc.count(_a) == 1, "perturbation anchor missing — would FALSE-PASS"
    _psrc = _psrc.replace(_a, '    key = (st.st_mtime_ns, st.st_size)\n')
if PERTURB_PANELSLASH:
    _a = "r'([^/\"]{1,100})/bootstrap\\.sh\\}\"$', re.M)"
    assert _psrc.count(_a) == 1, "perturbation anchor missing — would FALSE-PASS"
    _psrc = _psrc.replace(_a, "r'([^\"]{1,100})/bootstrap\\.sh\\}\"$', re.M)")
if PERTURB_PANELDECL:
    _a = '    if not UPDATE_TRIGGER or PANEL_DECLARATIVE:\n'
    assert _psrc.count(_a) == 1, "perturbation anchor missing — would FALSE-PASS"
    _psrc = _psrc.replace(_a, '    if not UPDATE_TRIGGER:\n')
_pd = tempfile.mkdtemp(prefix="panel-ref-")
_pf = os.path.join(_pd, "panelref.py"); open(_pf, "w").write(_psrc)
os.environ["SWG_NO_REEXEC"] = "1"
_pl = importlib.machinery.SourceFileLoader("panelref", _pf)
_P7 = importlib.util.module_from_spec(importlib.util.spec_from_loader("panelref", _pl))
try: _pl.exec_module(_P7)
except SystemExit: pass
def wrapper(ref):   # the real text every writer installs (lib/common.sh swg_update_wrapper_text)
    return subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; swg_update_wrapper_text "$2"', "_",
                           os.path.join(ROOT, "lib", "common.sh"), ref], capture_output=True, text=True).stdout
_W = os.path.join(_pd, "swg-update"); _P7.UPDATE_WRAPPER = _W; _P7.UPDATE_TRIGGER = os.path.join(_pd, "trigger")
def ref_after(text):
    if text is None:
        with contextlib.suppress(OSError): os.unlink(_W)
    else:
        open(_W, "w").write(text); st = os.stat(_W); os.utime(_W, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    return _P7.panel_update_ref()
check("[7] a host updater baked with dev reports dev", ref_after(wrapper("dev")) == "dev")
check("[7] …rewritten to main (a later update from main) reports nothing — the cache follows the file", ref_after(wrapper("main")) == "")
check("[7] …a tag is reported as it is", ref_after(wrapper("v1.9.0")) == "v1.9.0")
check("[7] …no updater (a Docker panel) reports nothing", ref_after(None) == "")
check("[7] …a file that is not our text reports nothing", ref_after('#!/bin/sh\nURL="https://example.org/swg-panel/dev/bootstrap.sh"\n') == "")
_P7.UPDATE_TRIGGER = None
check("[7] …a panel without the update trigger reports nothing (its Update hands out a main-pinned command)",
      ref_after(wrapper("dev")) == "")
_P7.UPDATE_TRIGGER = os.path.join(_pd, "trigger")
_P7.PANEL_DECLARATIVE = True
check("[7] …a NixOS panel reports nothing: its trigger runs the module's own service, not a wrapper left behind",
      ref_after(wrapper("dev")) == "")
_P7.PANEL_DECLARATIVE = False
if os.geteuid() != 0:                     # root reads a 000 file, so the unreadable case needs an ordinary user
    ref_after(wrapper("v1.9.0")); open(_W, "w").write(wrapper("dev"))
    _st = os.stat(_W); os.utime(_W, ns=(_st.st_atime_ns, _st.st_mtime_ns + 2_000_000_000)); os.chmod(_W, 0)
    _r1 = _P7.panel_update_ref(); os.chmod(_W, 0o644); _r2 = _P7.panel_update_ref()
    check("[7] …a read that fails is not cached: the next poll reads the file again", _r1 == "" and _r2 == "dev", (_r1, _r2))
ref_after(wrapper("dev")); _t = os.stat(_W).st_mtime_ns; _new = _W + ".new"
open(_new, "w").write(wrapper("tst")); os.utime(_new, ns=(_t, _t)); os.replace(_new, _W)   # same size, same mtime, new inode
check("[7] …a rename to a same-size ref in the same second is noticed (the key holds the inode)", _P7.panel_update_ref() == "tst")
# update.sh reads the same line back with its own sed (the ref it re-bakes on the next update): both readers, run on the
# same generated wrappers, must agree — the panel says nothing for main, which update.sh reads as main.
_m = re.search(r"sed -n '(s#\^URL=[^']*)' /usr/local/bin/swg-update", open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read())
check("[7] update.sh still reads its updater's ref back with one sed (the comparison below runs it)", bool(_m))
if _m:
    _bad = []
    for _ref in ("dev", "main", "v1.9.0", "1.8.11-rc.1", "my_branch", "feature/x"):
        _txt = wrapper(_ref); open(_W, "w").write(_txt)
        _sed = subprocess.run(["sed", "-n", _m.group(1), _W], capture_output=True, text=True).stdout.split("\n")[0]
        ref_after(_txt)
        if (_sed if _sed != "main" else "") != _P7.panel_update_ref():
            _bad.append((_ref, _sed, _P7.panel_update_ref()))
    check("[7] the panel's reader and update.sh's read-back agree on the same wrappers (a branch, main, tags, a `/`)",
          not _bad, _bad)
shutil.rmtree(_pd, ignore_errors=True)
check("[7] /api/state carries panel_update_ref only when there is one",
      '**({"panel_update_ref": _pref} if (_pref := panel_update_ref()) else {}),' in _psrc)
_ST = open(os.path.join(ROOT, "js", "store.js"), encoding="utf-8").read()
_AP = open(os.path.join(ROOT, "app.js"), encoding="utf-8").read()
_IX = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
check("[7] the store keeps it", 'this.panelUpdateRef = d.panel_update_ref || "";' in _ST)
check("[7] the header shows it beside the version, hidden without one",
      '<span class="appver appref" id="appref" hidden></span>' in _IX and 'ar.hidden = !ref;' in _AP
      and 'ar.textContent = T("from {ref}", { ref });' in _AP)
check("[7] a master's own node shows the host updater's ref, not its own",
      '${viaHost ? T("Update installs {ref}, not the latest release — this host\'s updater' in _SN
      and (_SN + _AP).count('Run `sudo bash -c \\"SWG_REF=main swg-update\\"` once to follow releases again.') == 2)
check("[7] …in Russian too", "this host's updater (/usr/local/bin/swg-update) was installed or last updated from it" in _RU
      and "программу обновления этого хоста (/usr/local/bin/swg-update)" in _RU and '`sudo bash -c \\"SWG_REF=main swg-update\\"`.' in _RU)

print()
if PERTURB_PANELMAIN or PERTURB_PANELCACHE or PERTURB_PANELFAIL or PERTURB_PANELINO or PERTURB_PANELDECL or PERTURB_PANELSLASH:
    _red = [f for f in FAILS if f.startswith("[7]")]
    print("perturb-panel: %s" % ("RED as it must be (%d), all [7]" % len(_red) if _red and len(_red) == len(FAILS) else "WRONG: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if PERTURB_CUSTOM or PERTURB_VIAHOST:
    _red = [f for f in FAILS if f.startswith("[6]")]
    print("perturb-custom: %s" % ("RED as it must be (%d), all [6]" % len(_red) if _red and len(_red) == len(FAILS) else "WRONG: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if PERTURB_SHOWN:
    _red = [f for f in FAILS if f.startswith("[6]")]
    print("perturb-shown: %s" % ("RED as it must be (%d), all [6]" % len(_red) if _red and len(_red) == len(FAILS) else "WRONG: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if PERTURB_HINT:
    _red = [f for f in FAILS if f.startswith("SWG_REF=")]
    print("perturb-hint: %s" % ("RED as it must be (%d), all [5]" % len(_red) if _red and len(_red) == len(FAILS) else "WRONG: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: the wrapper hardcoded `main` again" % len(FAILS)) if ok
          else "PERTURB FAILED — `main` was hardcoded back and nothing noticed")
    sys.exit(0 if ok else 1)
print(("FAIL: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
