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
import ast, importlib.machinery, importlib.util, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []


def check(label, got, want):
    if got != want:
        FAIL.append(f"{label}: got {got!r}, want {want!r}")


spec = importlib.util.spec_from_loader(
    "swgagent", importlib.machinery.SourceFileLoader("swgagent", os.path.join(ROOT, "swg-agent")))
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

# and the same host WITHOUT the declaration still gets the container answer, or the reorder would
# simply have swapped one wrong message for another
os.environ.pop("SWG_DECLARATIVE", None)
check("undeclared container: no tools", ensure_tool(lambda t: None), "PULL-IMAGE")
check("undeclared container: refused",  advice(agent._denied_error(EXEC_DENIED).msg), "PULL-IMAGE")

# ── the deliberate asymmetry ─────────────────────────────────────────────────────────────────────
src = open(os.path.join(ROOT, "swg-agent")).read()
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
