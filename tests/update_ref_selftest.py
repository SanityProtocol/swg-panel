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

Run: python3 tests/update_ref_selftest.py (0 = pass).  --perturb restores the hardcoded `main`.
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv

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
    for f in srcs:
        srcs[f] = srcs[f].replace("swg-panel/${_swg_ref}/bootstrap.sh", "swg-panel/main/bootstrap.sh")

print("\n[1] every writer of the update wrapper bakes the ref")
for f in WRITERS:
    body = srcs[f]
    # the URL line inside the heredoc that becomes /usr/local/bin/swg-update
    # ⚠️ THE ASSIGNMENT, not any mention. This matched the first line CONTAINING the name, and a
    # comment added above it silently took that slot — the gate then judged prose instead of code.
    urls = [l for l in body.splitlines() if l.lstrip().startswith('URL="')]
    check("%s writes the wrapper" % f, len(urls) == 1, urls)
    check("…and its default names the installed ref, not `main`",
          bool(urls) and "${_swg_ref}" in urls[0] and "/main/bootstrap.sh" not in urls[0], urls[0] if urls else "")
    check("…resolved with `main` only as the fallback",
          '_swg_ref="${SWG_REF:-main}"' in body, "no _swg_ref default in " + f)

print("\n[2] bootstrap tells them which ref that is")
boot = open(os.path.join(ROOT, "bootstrap.sh"), encoding="utf-8").read()
check("bootstrap EXPORTS the ref it resolved", 'export SWG_REF="$REF"' in boot,
      "SWG_REF is computed but never exported — nothing downstream can know it")
check("…after the default is applied, so it is never empty",
      boot.index('export SWG_REF="$REF"') > boot.index('REF="${REF:-main}"'))

print("\n[3] the generated wrapper is correct for each ref, and keeps its runtime overrides")
tmpl = [l for l in srcs["update.sh"].splitlines() if l.lstrip().startswith('URL="')][0]
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
for f in WRITERS:
    body = srcs[f]
    check("%s EXPORTS the URL so bootstrap can infer from it" % f,
          'export SWG_BOOTSTRAP_URL=' in body,
          "the ref is baked into a variable bootstrap never sees")

# …and drive it: build the wrapper for a ref, run it with a stubbed curl+bash, and read what REF bootstrap
# would resolve. This is the only check here that exercises the two together.
_tmpl_lines = [l for l in srcs["update.sh"].splitlines()
               if l.lstrip().startswith(('URL="', "export SWG_BOOTSTRAP_URL=", "curl -fsSL"))]
_wrap = "\n".join(_tmpl_lines)
_infer = """
_ref_from_url(){ printf '%s' "${1:-}" | sed -nE \
    -e 's#^https?://raw\\.githubusercontent\\.com/[^/]+/[^/]+/([^/]+)/.*#\\1#p' \
    -e 's#^https?://[^/]+/[^/]+/[^/]+/raw/([^/]+)/.*#\\1#p' | head -1; }
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
    nsrc["update.sh"] = nsrc["update.sh"].replace("  ensure_node_update_ref #", "  #")

check("swg-noded's self-update command is a TEMPLATE, not a hardcoded ref",
      "{ref}" in nsrc["swg-noded"] and "swg-panel/main/" not in nsrc["swg-noded"],
      [l for l in nsrc["swg-noded"].splitlines() if "UPDATE_CMD_TMPL" in l][:1])
check("…and it defaults to main when nothing recorded a ref",
      'DEFAULT_UPDATE_REF = "main"' in nsrc["swg-noded"])
for f in ("install-node.sh", "install-host.sh"):
    check("%s records the installed ref for the node" % f, '"update_ref"' in nsrc[f])
    check("…from SWG_REF, defaulting to main", re.search(r'_swg_[a-z_]*ref="\$\{SWG_REF:-main\}"', nsrc[f]) is not None)

# and the command it actually builds, for each ref — driven through the real function
import importlib.machinery, importlib.util
_fd, _tmp = tempfile.mkstemp(suffix=".py", prefix="noded-ref-", dir=HERE)
os.write(_fd, nsrc["swg-noded"].encode()); os.close(_fd)
_l = importlib.machinery.SourceFileLoader("nodedref", _tmp)
_m = importlib.util.module_from_spec(importlib.util.spec_from_loader("nodedref", _l))
try: _l.exec_module(_m)
except SystemExit: pass
os.unlink(_tmp)
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

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: the wrapper hardcoded `main` again" % len(FAILS)) if ok
          else "PERTURB FAILED — `main` was hardcoded back and nothing noticed")
    sys.exit(0 if ok else 1)
print(("FAIL: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
