#!/usr/bin/env python3
"""Self-test: a bring-up the SYSTEM refused must never be reported as a port or subnet clash.

A node reported that no wg interface would create. `wg-quick up wg2` printed

    /usr/bin/wg-quick: line 32: /usr/bin/ip: Operation not permitted

and the panel rendered that as "port/subnet may be in use", which sent the operator hunting a conflict
that did not exist. The line is bash reporting a FAILED execve — `ip` never ran, so nothing it would have
said about a port could be true. The kernel audit log had the real cause: a distribution `wg-quick`
profile trying to switch `ip` into its `wg-quick//ip` child profile, which AppArmor must refuse while the
caller carries no_new_privs — and that was swg-noded's own `NoNewPrivileges=true`.

⚠️ THE SECOND REFUSAL IS THE ONE THIS PROJECT'S OWN FIX MAKES LIKELIER. Retiring NoNewPrivileges means the
tools now genuinely RUN under whatever profile confines them, so `RTNETLINK answers: Operation not
permitted` — the tool running and the kernel turning it down — becomes the realistic outcome. It must not
fall back to the same lie, so it gets its own arm and is asserted here.

⚠️ BOTH REFUSAL SPELLINGS COUNT. EPERM is the no_new_privs transition denial; EACCES is a policy with
no exec rule for the binary at all, or a noexec mount. Both mean the tool never ran, so both must reach
a real message — matching only EPERM made the arm that names SELinux and fapolicyd unreachable for the
hosts that actually produce them. Widening is safe here because `<tool>-quick` redirects only to file
descriptors and /dev/null, so a failed redirect cannot wear this same shape inside it.

⚠️ A PROFILE IS NAMED EITHER WAY. Newer policy names it for the tool (`wg`), older for the path
(`/usr/bin/wg`). Matching one spelling only would read a confined box as unconfined and hand the operator
advice for the wrong cause — silently, which is why both are pinned below.

Run: python3 tests/apparmor_denial_selftest.py      (0 = pass)
"""
import ast, importlib.machinery, importlib.util, json, os, re, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []


def load(name, path):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check(label, got, want):
    if got != want:
        FAIL.append(f"{label}: got {got!r}, want {want!r}")


# ── perturbations ──────────────────────────────────────────────────────────────────────────────
# ⚠️ A GREEN GATE PROVES NOTHING UNTIL YOU BREAK IT. This gate had no perturbation mode at all, and
# release qualification 1.8.7 found a guard it was blind to (the `//` child-profile exclusion) by
# breaking the code BY HAND in a scratch copy of the tree — which proves it once and leaves nothing
# behind. These run the same experiments from inside the gate, so the proof is repeatable:
#
#     for f in child decl order eacces marker netlink; do
#       python3 tests/apparmor_denial_selftest.py --perturb-$f >/dev/null 2>&1; echo "$f rc=$?"
#     done      # every one MUST print rc=1
#
# The edit is applied to the SOURCE TEXT before anything reads it, so the module checks and the
# source-scanning checks below both see the perturbed tree. ⚠️ An anchor that no longer matches is a
# FALSE PASS, not a no-op, so a missing anchor is a hard error rather than a skipped edit.
_EDITS = {
    # the guard this gate was blind to: a `//` child profile counted as its parent's tool
    "--perturb-child":   ("swg-agent", 'if mode != "(enforce)" or "//" in name:',
                                       'if mode != "(enforce)":'),
    # a declared host stops being recognised — every declarative arm goes silent
    "--perturb-decl":    ("swg-agent", 'def _declarative():', 'def _declarative():\n    return False'),
    # the exec arm's container test back above the declarative one
    "--perturb-order":   ("swg-agent", '        if _declarative():\n            if aa:',
                                       '        if _declarative() and not _IN_CONTAINER:\n            if aa:'),
    # the refusal spelling a policy with no exec rule returns
    "--perturb-eacces":  ("swg-agent", 'Operation not permitted|Permission denied',
                                       'Operation not permitted'),
    # the reap marker drifts from the one uninstall.sh cuts on
    "--perturb-marker":  ("lib/common.sh", 'swgPanel: userspace WireGuard datapaths (begin)',
                                           'swgPanel: userspace WG datapaths (begin)'),
    # the RTNETLINK arm loses its declarative branch — qualification 1.8.7 finding 1, put back
    "--perturb-netlink": ("swg-agent", '        if _declarative():\n            return AgentError("no_priv"',
                                       '        if False:\n            return AgentError("no_priv"'),
}
PERTURB = [a for a in sys.argv[1:] if a.startswith("--perturb")]
for _f in PERTURB:
    if _f not in _EDITS:
        sys.exit("unknown perturbation %s (have: %s)" % (_f, " ".join(sorted(_EDITS))))


def read(rel):
    """Source of `rel`, with any perturbation for it applied."""
    text = open(os.path.join(ROOT, rel)).read()
    for flag in PERTURB:
        target, old, new = _EDITS[flag]
        if target != rel:
            continue
        if old not in text:
            sys.exit("PERTURBATION %s FOUND NO ANCHOR in %s — it would have passed for the wrong reason"
                     % (flag, rel))
        text = text.replace(old, new, 1)
    return text


def load_src(name, rel):
    """Load `rel` as a module from its (possibly perturbed) source, never from the path directly."""
    body = read(rel)
    if not PERTURB:
        return load(name, os.path.join(ROOT, rel))
    tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
    tmp.write(body); tmp.close()
    return load(name, tmp.name)


agent = load_src("swgagent", "swg-agent")

EXEC_DENIED = ("wg-quick up wg2 failed: [#] ip link add dev wg2 type wireguard\n"
               "/usr/bin/wg-quick: line 32: /usr/bin/ip: Operation not permitted\n"
               "/usr/bin/wg-quick: line 183: /usr/bin/wg: Operation not permitted")
NETLINK_DENIED = ("wg-quick up wg2 failed: [#] ip link add dev wg2 type wireguard\n"
                  "RTNETLINK answers: Operation not permitted")


def with_profiles(text):
    if text is None:
        agent._AA_PROFILES = os.path.join(tempfile.gettempdir(), "swg-no-such-apparmor")
        return
    fd, path = tempfile.mkstemp(prefix="swg-aa-")
    os.write(fd, text.encode())
    os.close(fd)
    agent._AA_PROFILES = path


def arm(err):
    if err is None:
        return "NONE"
    if "AppArmor refused" in err.msg:
        # the declarative twin prescribes a configuration change, not a command — see _denied_error
        return "DECLARATIVE" if "managed declaratively" in err.msg else "APPARMOR"
    if err.msg.startswith("this node's container"):
        return "CONTAINER"
    if err.msg.startswith("the interface tools ran"):
        return "NETLINK"
    return "GENERAL"


# ── which profile spellings count as "this box confines the tools" ──────────────────────────────
for label, profiles, want in [
    ("short name",            "wg (enforce)\nwg-quick (enforce)\n",  ["wg", "wg-quick"]),
    ("path name",             "/usr/bin/wg (enforce)\n",             ["wg"]),
    ("/bin path",             "/bin/awg-quick (enforce)\n",          ["awg-quick"]),
    ("child profile alone",   "wg-quick//ip (enforce)\n",            []),
    # ⚠️ THE ROW ABOVE PASSES WITHOUT THE GUARD, which is why it was not enough: `wg-quick//ip` has the
    # basename `ip`, and `ip` is not in _AA_TOOLS, so the name test rejects it whether or not `//` is
    # excluded. The exclusion only does work when the CHILD is named after a tool — and then it is
    # load-bearing, because a `wg-quick//wg` child is reached through its parent and is out of reach of
    # /etc/apparmor.d/local/ altogether, so naming `wg` sends the operator to a file that cannot fix it.
    # Both gates were blind to this until release qualification 1.8.7 (finding 2).
    ("child named for a tool", "wg-quick//wg (enforce)\n",            []),
    ("child beside its parent","wg-quick//wg (enforce)\nwg-quick (enforce)\n", ["wg-quick"]),
    ("complain is permissive","wg (complain)\n",                     []),
    ("lookalike name",        "wgx (enforce)\n",                     []),
    ("no apparmor at all",    None,                                  []),
]:
    with_profiles(profiles)
    check(f"profiles/{label}", agent._aa_enforced_tools(), want)

# ── which sentence each refusal gets ────────────────────────────────────────────────────────────
# a host that cannot keep a unit it writes cannot keep an `aa-complain` either
agent._units_persist = lambda: True

for label, msg, profiles, in_container, want in [
    ("exec denied, AppArmor enforcing",   EXEC_DENIED,    "wg (enforce)\n",        False, "APPARMOR"),
    ("exec denied, path-named profile",   EXEC_DENIED,    "/usr/bin/wg (enforce)\n", False, "APPARMOR"),
    ("exec denied, no AppArmor",          EXEC_DENIED,    None,                     False, "GENERAL"),
    # host policy advice must never be given where host policy cannot be reached
    ("exec denied inside a container",    EXEC_DENIED,    "wg (enforce)\n",        True,  "CONTAINER"),
    ("kernel refused the operation",      NETLINK_DENIED, None,                     False, "NETLINK"),
    # the faults that are NOT a refusal keep their own, already-correct messages
    ("datapath module missing",  "[#] ip link add\nError: Unknown device type.",          None, False, "NONE"),
    ("name already taken",       "wg-quick: `wg2' already exists",                          None, False, "NONE"),
    ("a real port clash",        "[#] wg setconf wg2\nAddress already in use",              None, False, "NONE"),
    # EACCES means the tool never ran either — a policy with no exec rule for the binary, or a noexec
    # mount. The general arm names SELinux and fapolicyd, which produce exactly this; matching only
    # EPERM left that advice unreachable and dropped those hosts back onto "port/subnet may be in use".
    ("EACCES: no exec rule at all", "/usr/bin/wg-quick: line 32: /usr/bin/ip: Permission denied", None, False, "GENERAL"),
]:
    with_profiles(profiles)
    agent._IN_CONTAINER = in_container
    check(f"arm/{label}", arm(agent._denied_error(msg)), want)

# ── a declaratively managed host gets configuration, never a command that cannot stick ──────────
# NixOS also sets restartIfChanged=false by default, so a rebuild leaves the OLD unit running —
# the sentence has to say so or the operator changes the module and sees no difference.
agent._units_persist = lambda: False
with_profiles("wg (enforce)\n")
agent._IN_CONTAINER = False
declarative = agent._denied_error(EXEC_DENIED)
check("arm/declarative host", arm(declarative), "DECLARATIVE")
check("declarative arm names the restart", "does not restart it" in (declarative.msg if declarative else ""), True)
check("declarative arm prescribes no command", "aa-complain" in (declarative.msg if declarative else ""), False)
agent._units_persist = lambda: True

# ── every bring-up site must consult it, or the fix reaches one screen and not the next ─────────
src = read("swg-agent")
wired = len(re.findall(r"_denied = _denied_error\(.*?\)\n\s+if _denied:\n\s+raise _denied", src))
check("all four bring-up sites classify", wired, src.count("_denied = _denied_error("))
check("bring-up sites found", wired, 4)

# ── the catalogue: an untranslated sentence reads as English inside a translated page ───────────
ru = read("js/lang/ru.js")
tree = ast.parse(src)
consts = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
          if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
          and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)}
fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_denied_error")
msgs = []
for a in ast.walk(fn):
    if isinstance(a, ast.Call) and getattr(a.func, "id", "") == "AgentError":
        arg = a.args[1]
        # an arm reached from two places is a module constant, not a literal — resolve it, or the
        # count below silently stops seeing it the moment one is hoisted
        msgs.append(arg.value if isinstance(arg, ast.Constant) else consts[arg.id])
check("eight arms", len(msgs), 8)   # exec:    declarative/apparmor · declarative · container · apparmor · general
#                                     netlink: declarative · container · host

# ⚠️ THE COUNT ABOVE IS NOT THE PROPERTY — it only notices that an arm appeared. The property is that
# BOTH refusal kinds ask what the host can act on before they answer, and the netlink one did not: it
# shipped as a single sentence naming a docker-compose.yml a declaratively managed node does not have,
# and the count was 6 and green the whole time. So assert the SHAPE: every `if <…>_DENIED_RE.search(…)`
# block must guard at least one AgentError behind `_declarative()`. Release qualification 1.8.7 finding 1.
def _kind_blocks(f):
    for node in f.body:
        if isinstance(node, ast.If):
            names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            hit = {n for n in names if n.endswith("_DENIED_RE")}
            if hit:
                yield sorted(hit)[0], node


def _declarative_arms(node):
    n = 0
    for sub in ast.walk(node):
        if (isinstance(sub, ast.If) and isinstance(sub.test, ast.Call)
                and getattr(sub.test.func, "id", "") == "_declarative"):
            n += sum(1 for c in ast.walk(sub) if isinstance(c, ast.Call)
                     and getattr(c.func, "id", "") == "AgentError")
    return n


_kinds = dict(_kind_blocks(fn))
check("both refusal kinds are handled", sorted(_kinds), ["_EXEC_DENIED_RE", "_NETLINK_DENIED_RE"])
for _k, _blk in sorted(_kinds.items()):
    check(f"{_k}: has a declarative arm", _declarative_arms(_blk) >= 1, True)
    # …and it must come FIRST, above the container test: a declared node that happens to run in a
    # container is both, and only one of those two answers can be acted on there.
    _order = [i for i, sub in enumerate(ast.walk(_blk))
              if isinstance(sub, ast.If) and isinstance(sub.test, ast.Call)
              and getattr(sub.test.func, "id", "") == "_declarative"]
    _ctr = [i for i, sub in enumerate(ast.walk(_blk))
            if isinstance(sub, ast.If) and isinstance(sub.test, ast.Name)
            and sub.test.id == "_IN_CONTAINER"]
    check(f"{_k}: declarative before container", (not _ctr) or (_order and _order[0] < _ctr[0]), True)
for m in msgs:
    # The sentence IS the key (js/i18n.js srvText), so it must stay interpolation-free — a value baked
    # into it can never be looked up, and the message then arrives as English inside a translated page.
    check(f"interpolation-free: {m[:30]}…", "{" in m, False)
    # ru.js holds it JSON-encoded; compare the same encoding rather than the raw sentence, or a message
    # containing a quote reads as missing when it is there.
    check(f"catalogued: {m[:30]}…", json.dumps(m, ensure_ascii=False) in ru, True)

# ── uninstall.sh reaps the AppArmor grant by literal text; the markers live in lib/common.sh ────
lib = read("lib/common.sh")
uninstall = read("uninstall.sh")
for var in ("APPARMOR_LOCAL_BEGIN", "APPARMOR_LOCAL_END"):
    marker = re.search(rf"^{var}='([^']*)'", lib, re.M).group(1).strip()
    check(f"uninstall.sh knows {var}", marker in uninstall, True)
    # a marker that reads as shell syntax breaks any parser that walks these files (the repo's own
    # heredoc audit rejected `>>>`/`<<<` here once already)
    check(f"{var} is not shell syntax", any(c in marker for c in "<>|&$`"), False)

# ── the unit templates: the directive that caused this must not come back ───────────────────────
for path, why in [("install-node.sh", "a node"), ("install-host.sh", "a master's local node"),
                  ("update.sh", "the heal template")]:
    body = read(path)
    for unit in re.findall(r"swg-noded\.service[^\n]*\n(.*?)\nEOF", body, re.S):
        check(f"{path}: no NoNewPrivileges in {why}", "\nNoNewPrivileges=" in "\n" + unit, False)

if FAIL:
    print("RED — %d check(s) failed:" % len(FAIL))
    for f in FAIL:
        print("  ·", f)
    sys.exit(1)
print("GREEN — refusals are named, not blamed on the port; markers and unit templates hold")
