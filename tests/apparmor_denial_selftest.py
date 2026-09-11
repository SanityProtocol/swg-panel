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


agent = load("swgagent", os.path.join(ROOT, "swg-agent"))

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
    ("EACCES is not EPERM",      "/usr/bin/wg-quick: line 32: /usr/bin/ip: Permission denied", None, False, "NONE"),
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
src = open(os.path.join(ROOT, "swg-agent")).read()
wired = len(re.findall(r"_denied = _denied_error\(.*?\)\n\s+if _denied:\n\s+raise _denied", src))
check("all four bring-up sites classify", wired, src.count("_denied = _denied_error("))
check("bring-up sites found", wired, 4)

# ── the catalogue: an untranslated sentence reads as English inside a translated page ───────────
ru = open(os.path.join(ROOT, "js/lang/ru.js")).read()
fn = next(n for n in ast.walk(ast.parse(src))
          if isinstance(n, ast.FunctionDef) and n.name == "_denied_error")
msgs = [a.args[1].value for a in ast.walk(fn)
        if isinstance(a, ast.Call) and getattr(a.func, "id", "") == "AgentError"]
check("five arms", len(msgs), 5)   # container · apparmor · apparmor/declarative · general · netlink
for m in msgs:
    # The sentence IS the key (js/i18n.js srvText), so it must stay interpolation-free — a value baked
    # into it can never be looked up, and the message then arrives as English inside a translated page.
    check(f"interpolation-free: {m[:30]}…", "{" in m, False)
    # ru.js holds it JSON-encoded; compare the same encoding rather than the raw sentence, or a message
    # containing a quote reads as missing when it is there.
    check(f"catalogued: {m[:30]}…", json.dumps(m, ensure_ascii=False) in ru, True)

# ── uninstall.sh reaps the AppArmor grant by literal text; the markers live in lib/common.sh ────
lib = open(os.path.join(ROOT, "lib/common.sh")).read()
uninstall = open(os.path.join(ROOT, "uninstall.sh")).read()
for var in ("APPARMOR_LOCAL_BEGIN", "APPARMOR_LOCAL_END"):
    marker = re.search(rf"^{var}='([^']*)'", lib, re.M).group(1).strip()
    check(f"uninstall.sh knows {var}", marker in uninstall, True)
    # a marker that reads as shell syntax breaks any parser that walks these files (the repo's own
    # heredoc audit rejected `>>>`/`<<<` here once already)
    check(f"{var} is not shell syntax", any(c in marker for c in "<>|&$`"), False)

# ── the unit templates: the directive that caused this must not come back ───────────────────────
for path, why in [("install-node.sh", "a node"), ("install-host.sh", "a master's local node"),
                  ("update.sh", "the heal template")]:
    body = open(os.path.join(ROOT, path)).read()
    for unit in re.findall(r"swg-noded\.service[^\n]*\n(.*?)\nEOF", body, re.S):
        check(f"{path}: no NoNewPrivileges in {why}", "\nNoNewPrivileges=" in "\n" + unit, False)

if FAIL:
    print("RED — %d check(s) failed:" % len(FAIL))
    for f in FAIL:
        print("  ·", f)
    sys.exit(1)
print("GREEN — refusals are named, not blamed on the port; markers and unit templates hold")
