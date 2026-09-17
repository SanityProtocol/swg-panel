#!/usr/bin/env python3
"""Self-test: advice a node prints must be something THAT host can act on.

Every "no_tool" / "no_module" / "no_exec" message ends in an instruction, and there are three kinds of
host that need three different ones: run a package manager (bare metal), pull the image (a container),
or put it in the configuration that declares this node and rebuild (NixOS and any other immutable-OS
layout). Getting it wrong is not cosmetic — the operator does the thing, nothing changes, and nothing
says why.

⚠️ THE DECLARATIVE TEST MUST COME FIRST, above the container one. A NixOS node running our image is
BOTH, and only one of the two answers is actionable there. Every chain here had it the other way round,
so a NixOS container node was told to edit a docker-compose.yml its host does not have.

⚠️ AND THE PROBE HAD TO CHANGE TO SEE THAT. `_units_persist()` is a write probe on the unit directory —
right on the native arm, blind inside our image, where /etc/systemd/system is an ordinary writable
directory on a Debian filesystem. `_declarative()` reads SWG_DECLARATIVE, which nix/modules/node.nix
already sets and swg-noded already parses, and falls back to the probe where there is no env of ours.

⚠️ ONE CALLER DELIBERATELY KEEPS THE NARROW PROBE. `_iface_unit` asks whether a unit written HERE would
survive, which is a different question — in a container the honest answer is no, whoever declared it.

Run: python3 tests/declarative_advice_selftest.py      (0 = pass)
"""
import ast, tempfile, importlib.machinery, importlib.util, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []


def check(label, got, want):
    if got != want:
        FAIL.append(f"{label}: got {got!r}, want {want!r}")


# ── perturbations ──────────────────────────────────────────────────────────────────────────────
# ⚠️ This gate was green while a whole arm of `_denied_error` had no declarative branch (release
# qualification 1.8.7, finding 1) — it drove the EXEC refusal twice and the RTNETLINK one never. A gate
# nobody has broken is a gate nobody has checked, so the experiments live here now:
#
#     for f in netlink env order decl; do
#       python3 tests/declarative_advice_selftest.py --perturb-$f >/dev/null 2>&1; echo "$f rc=$?"
#     done      # every one MUST print rc=1
#
# ⚠️ An anchor that no longer matches is a FALSE PASS, not a skipped edit, so it is a hard error.
_EDITS = {
    "--perturb-netlink": ('        if _declarative():\n            return AgentError("no_priv"',
                          '        if False:\n            return AgentError("no_priv"'),
    "--perturb-env":     ('    if (os.environ.get("SWG_DECLARATIVE")',
                          '    if False and (os.environ.get("SWG_DECLARATIVE")'),
    "--perturb-order":   ('        if _declarative():\n            if aa:',
                          '        if _declarative() and not _IN_CONTAINER:\n            if aa:'),
    "--perturb-decl":    ('def _declarative():', 'def _declarative():\n    return False'),
}
PERTURB = [a for a in sys.argv[1:] if a.startswith("--perturb")]
for _f in PERTURB:
    if _f not in _EDITS:
        sys.exit("unknown perturbation %s (have: %s)" % (_f, " ".join(sorted(_EDITS))))


def read(rel):
    text = open(os.path.join(ROOT, rel)).read()
    if rel != "swg-agent":
        return text
    for flag in PERTURB:
        old, new = _EDITS[flag]
        if old not in text:
            sys.exit("PERTURBATION %s FOUND NO ANCHOR — it would have passed for the wrong reason" % flag)
        text = text.replace(old, new, 1)
    return text


_agent_path = os.path.join(ROOT, "swg-agent")
if PERTURB:
    _tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
    _tmp.write(read("swg-agent")); _tmp.close()
    _agent_path = _tmp.name
spec = importlib.util.spec_from_loader(
    "swgagent", importlib.machinery.SourceFileLoader("swgagent", _agent_path))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

# ── the predicate: two signals, because neither alone covers both arms ───────────────────────────
for label, env, persist, want in [
    ("native arm: unit dir not writable", None,    False, True),
    ("ordinary bare metal",               None,    True,  False),
    ("declared container (env only)",     "1",     True,  True),
    ("env spellings honoured",            "true",  True,  True),
    ("env spellings honoured",            "yes",   True,  True),
    ("env off is not declarative",        "0",     True,  False),
    ("env empty is not declarative",       "",     True,  False),
]:
    agent._units_persist = lambda p=persist: p
    os.environ.pop("SWG_DECLARATIVE", None)
    if env is not None:
        os.environ["SWG_DECLARATIVE"] = env
    check(f"declarative/{label}={env!r}", agent._declarative(), want)
os.environ.pop("SWG_DECLARATIVE", None)


# ── every chain prefers configuration over a command, on a host that is BOTH ─────────────────────
def advice(msg):
    if "managed declaratively" in msg:
        return "CONFIGURE"
    if "docker compose" in msg or "docker-compose" in msg:
        return "PULL-IMAGE"
    return "RUN-A-COMMAND"


agent._IN_CONTAINER = True          # a container …
agent._units_persist = lambda: True  # … whose own filesystem cannot reveal that it is declared
os.environ["SWG_DECLARATIVE"] = "1"

def ensure_tool(which):
    agent.shutil.which = which
    try:
        agent._ensure_tool("awg")
    except agent.AgentError as e:
        return advice(e.msg)
    return "NO-ERROR"

check("no tools at all",     ensure_tool(lambda t: None), "CONFIGURE")
check("awg without awg-quick", ensure_tool(lambda t: "/usr/bin/awg" if t == "awg" else None), "CONFIGURE")

agent.shutil.which = lambda t: None
try:
    agent._ensure_tool("wg")
except agent.AgentError as e:
    check("WireGuard tools absent", advice(e.msg), "CONFIGURE")

EXEC_DENIED = "/usr/bin/wg-quick: line 32: /usr/bin/ip: Operation not permitted"
agent._AA_PROFILES = os.path.join(ROOT, "no-such-apparmor-profiles")
check("bring-up refused at exec", advice(agent._denied_error(EXEC_DENIED).msg), "CONFIGURE")

# ⚠️ AND THE OTHER REFUSAL, which this gate drove NOT ONCE. `_denied_error` classifies two faults: the
# tool that could not be EXEC'd, and the tool that ran and had its operation refused — and only the
# first was ever asked what a declared host should be told. The second shipped as one sentence naming
# a docker-compose.yml a declaratively managed node does not have. It is also the arm the module's own
# docstring calls the LIKELIER of the two now that NoNewPrivileges is retired, because the tools
# genuinely execute under whatever policy confines them. Release qualification 1.8.7, finding 1.
NETLINK_DENIED = "RTNETLINK answers: Operation not permitted"
check("kernel refused the operation", advice(agent._denied_error(NETLINK_DENIED).msg), "CONFIGURE")

# and the same host WITHOUT the declaration still gets the container answer, or the reorder would
# simply have swapped one wrong message for another
os.environ.pop("SWG_DECLARATIVE", None)
check("undeclared container: no tools", ensure_tool(lambda t: None), "PULL-IMAGE")
check("undeclared container: refused",  advice(agent._denied_error(EXEC_DENIED).msg), "PULL-IMAGE")
check("undeclared container: kernel refused", advice(agent._denied_error(NETLINK_DENIED).msg), "PULL-IMAGE")

# ── the deliberate asymmetry ─────────────────────────────────────────────────────────────────────
src = read("swg-agent")
fn = next(n for n in ast.walk(ast.parse(src))
          if isinstance(n, ast.FunctionDef) and n.name == "_iface_unit")
names = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
check("_iface_unit keeps the write probe", "_units_persist" in names, True)
check("_iface_unit does not ask _declarative", "_declarative" in names, False)

# ── nothing may ship a fixed sentence the catalogue has never seen ───────────────────────────────
# The sentence IS the key (js/i18n.js srvText), so an uncatalogued one renders as English inside a
# translated page — and three did, the moment these arms were added.
ru = open(os.path.join(ROOT, "js/lang/ru.js")).read()
uncatalogued = []
for node in ast.walk(ast.parse(src)):
    if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "AgentError"
            and len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)):
        m = node.args[1].value
        if len(m) > 90 and "{" not in m and json.dumps(m, ensure_ascii=False) not in ru:
            uncatalogued.append(m[:60])
check("every fixed sentence is catalogued", uncatalogued, [])

if FAIL:
    print("RED — %d check(s) failed:" % len(FAIL))
    for f in FAIL:
        print("  ·", f)
    sys.exit(1)
print("GREEN — declared hosts get configuration, containers get the image, everyone else a command")
