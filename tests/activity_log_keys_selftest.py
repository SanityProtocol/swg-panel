#!/usr/bin/env python3
"""Self-test — every activity row the panel writes can be translated.

The browser translates an activity row by LOOKING UP its English: the verb as a catalog key, and a prose detail
through detail_key + detail_vars (ev_append's docstring). Two shapes defeat that and shipped anyway, found in the
1.8.8 qualification's Russian pass ("1 target" under a Russian "Deleted peer"):
  · a verb with a value formatted INTO it — "VK pool changed — reassigned %d user(s)" % n. The catalog held the
    template, the disk held "… reassigned 3 user(s)", and the lookup never matched. The i18n audit counted the
    template as translated, so it was green on a string no Russian operator ever saw translated.
  · a detail that is English prose with no detail_key — "fresh key issued", "was <user>", "%d target%s",
    "(automatic, attempt %d of %d)", the key-restore explanation, a node's adoption note.

The real source is parsed (Python's own `ast`), so this reads every ev_append call however it is wrapped:
  [1] the verb is a string literal, a conditional of literals, or a name — never %-formatted, an f-string, or
      concatenated;
  [2] a detail that holds English prose (two words, or a formatted count) comes with a detail_key;
  [3] every literal verb and detail_key — and every phrase nested in detail_vars through perr() — is a key in
      js/lang/ru.js (a key with no three-letter word is exempt: it has nothing to translate).

Run: python3 tests/activity_log_keys_selftest.py      (0 = pass)
     --perturb   plants the two shipped shapes into a copy of the source → RED
"""
import ast, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
src = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
if PERTURB:
    src += ('\n\ndef _planted(roster_path, pid, n):\n'
            '    ev_append(roster_path, "settings", "", "VK pool changed — reassigned %d user(s)" % n, "")\n'
            '    ev_append(roster_path, "peer", pid, "Assigned peer", "x", "fresh key issued")\n'
            '    ev_append(roster_path, "settings", "", "VK pool changed", "reassigned %d user(s)" % n, detail_key="reassigned {count}")\n')
ru = open(os.path.join(ROOT, "js", "lang", "ru.js"), encoding="utf-8").read()
KEYS = {m.group(1).replace('\\"', '"') for m in re.finditer(r'^\s*"((?:[^"\\]|\\.)*)"\s*:', ru, re.M)}

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:900]) if not ok else ""))
    if not ok:
        FAILS.append(name)

PROSE = re.compile(r"[A-Za-z]{2,}\s+[A-Za-z]{2,}|%d\s*[A-Za-z]|\(\s*[A-Za-z]{3,}")
def strs(node):
    """Every string literal inside an expression (f-string parts included)."""
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
def verb_ok(node):
    if isinstance(node, (ast.Constant, ast.Name)):
        return True
    if isinstance(node, ast.IfExp):
        return verb_ok(node.body) and verb_ok(node.orelse)
    return False
def literals(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return literals(node.body) + literals(node.orelse)
    return []
def need_key(k):
    return bool(k) and bool(re.search(r"[A-Za-z]{3}", k))

tree = ast.parse(src)
calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "ev_append"]
calls = [c for c in calls if len(c.args) >= 4]                      # the definition's own recursion aside
bad_verb, bad_detail, missing = [], [], []
for c in calls:
    kw = {k.arg: k.value for k in c.keywords}
    verb = c.args[3]
    if not verb_ok(verb):
        bad_verb.append("line %d: %s" % (c.lineno, ast.unparse(verb)[:90]))
    for v in literals(verb):
        if need_key(v) and v not in KEYS:
            missing.append("line %d verb %r" % (c.lineno, v))
    name = c.args[4] if len(c.args) > 4 else kw.get("name")
    if name is not None:                       # the NAME is a value (a label, node, iface) — prose there is never looked up
        prose = [x for x in strs(name) if PROSE.search(x)]
        if prose:
            bad_detail.append("line %d NAME: %s" % (c.lineno, prose[:2]))
    detail = c.args[5] if len(c.args) > 5 else kw.get("detail")
    if detail is not None and "detail_key" not in kw:
        prose = [x for x in strs(detail) if PROSE.search(x)]
        if prose:
            bad_detail.append("line %d: %s" % (c.lineno, prose[:2]))
    if "detail_key" in kw:
        for k in literals(kw["detail_key"]):
            if need_key(k) and k not in KEYS:
                missing.append("line %d detail_key %r" % (c.lineno, k))
    dv = kw.get("detail_vars")
    if dv is not None:
        for n in ast.walk(dv):
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "perr" and n.args:
                a0 = n.args[0]           # perr("phrase") — or perr({field: "phrase", …}[f]): the phrases, not the field ids
                phrases = ([x for v in a0.value.values for x in strs(v)] if isinstance(a0, ast.Subscript)
                           and isinstance(a0.value, ast.Dict) else strs(a0))
                for k in phrases:
                    if need_key(k) and k not in KEYS:
                        missing.append("line %d perr %r" % (c.lineno, k))

print("[the calls this reads]")
check("found the panel's activity calls (a parser that finds none proves nothing)", len(calls) >= 100, len(calls))

print("\n[1] a verb is a key, never a sentence with a value in it")
check("no ev_append verb is formatted, an f-string or concatenated", not bad_verb, bad_verb)

print("\n[2] prose in a detail travels with its key, and a name is a value")
check("every detail that is English prose has a detail_key, and no name is prose", not bad_detail, bad_detail)

print("\n[3] and the keys are in the Russian catalog")
check("every literal verb, detail_key and nested perr() phrase has a Russian entry", not missing, missing)

print("\nFAIL (%d)" % len(FAILS) if FAILS else "\nALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(1 if FAILS else (2 if PERTURB else 0))
