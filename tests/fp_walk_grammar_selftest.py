#!/usr/bin/env python3
"""Self-test: every fingerprint walker names a path the same way.

The rebuild/transfer machinery walks a node record SEVEN times over — prune, mask, the reset, both diff
passes, the path inventory and the single-path lookup. They do genuinely different jobs (one pairs TWO
trees, one resolves ONE path), so they are not one function pretending to be seven. What they must share is
the GRAMMAR: which containers are subtrees, and what an element is called inside one.

That is the thing that actually broke. Six of them answered "is this a subtree?" with their own
`isinstance(o, dict)` and stopped at a list, while the inventory indexed one as `[i]` — so a rule written
for a field inside `exits` matched on the checking side and reset, masked and pruned nothing, silently. The
fix was one predicate (`_fp_record_list`) and one namer (`_fp_list_path`); this is what keeps them shared.

⚠️ IT ALREADY CAUGHT A SECOND DIVERGENCE. After the list fix the two ENUMERATORS still disagreed: the
inventory kept its own list rule and descended a list of NAMES into `[0]`, `[1]`… which nothing can judge —
`_fp_swap_verdict_list` takes such a list whole — while pass 2 dropped empty containers the inventory
reported. A path promised by a capture that the diff can never judge is a promise it does not keep.

Hermetic: no state, no network. Run: python3 tests/fp_walk_grammar_selftest.py (0 = pass).
--perturb makes every list look like a plain value again and expects the walkers to disagree.
"""
import importlib.machinery, importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

_l = importlib.machinery.SourceFileLoader("swgpanel", PANEL)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass
if PERTURB:
    # One predicate answers "is this list a subtree?" for every walker, so saying "never" puts all of them
    # back to stopping at a list. It cannot raise, so a red run is a caught disagreement and not a crash.
    P._fp_record_list = lambda o: False

# Every shape the record actually contains: scalars, nested dicts, a list of NAMES (judged whole), a list of
# RECORDS (walked into), a mixed list (a name list with something odd in it) and empty containers.
TREE = {"scalar": 1, "empty_dict": {}, "empty_list": [],
        "names": ["a.example", "b.example"],
        "records": [{"k": 1, "deep": {"x": 2}}, {"k": 3}],
        "mixed": ["a.example", {"k": 1}],
        "nested": {"inner": {"leaf": "v"}}}

print("\n[1] the two enumerators name exactly the same leaves")
leaves = set(P._fp_leaves(TREE))
values = set(p.split(".", 1)[1] for p, _ in P._fp_leaf_values(TREE, "sec"))
check("the inventory and pass 2 agree", leaves == values,
      "only inventory: %s · only judged: %s" % (sorted(leaves - values), sorted(values - leaves)))
check("a list of RECORDS is walked into", "records.[0].deep.x" in leaves, sorted(leaves))
check("a list of NAMES is one value, not indexed", "names" in leaves and "names.[0]" not in leaves, sorted(leaves))
check("…and so is a name list with an odd element in it", "mixed" in leaves and "mixed.[0]" not in leaves)
check("an empty container is a leaf — \"exists and is empty\" is a fact",
      "empty_dict" in leaves and "empty_list" in leaves, sorted(leaves))

print("\n[2] every leaf the diff judges can be resolved and reported")
missing = [p for p, _ in P._fp_leaf_values(TREE, "sec")
           if P._fp_leaf_at(TREE, p, "sec") is None and not str(p).endswith(("empty_dict", "empty_list"))]
check("_fp_leaf_at resolves every path pass 2 produces", not missing, missing[:4])
b = {"records": [{"k": 1}]}
a = {"records": [{"k": 2}]}
d = [p for p, _bv, _av in P._fp_tree_diff(b, a, "sec")]
check("_fp_tree_diff reports a change INSIDE a record list", d == ["sec.records.[0].k"], d)

print("\n[3] prune, mask and the reset reach the same places")
pruned, dropped = P._fp_prune(TREE, ("records.*.deep",))
check("_fp_prune drops a subtree inside a record list", dropped == ["records.[0].deep"], dropped)
_saved = P._FP_SECRET_PATHS
P._FP_SECRET_PATHS = (("records.*.secret", "probe"),)
m = P._fp_mask({"records": [{"secret": "PLAINTEXT"}]})
P._FP_SECRET_PATHS = _saved
check("_fp_mask masks a value inside a record list",
      str(m["records"][0]["secret"]).startswith("secret:"), m)
check("…and the plaintext is gone", "PLAINTEXT" not in str(m), m)

print("\n[4] the one predicate every walker asks")
check("all-dicts is a subtree", P._fp_record_list([{"a": 1}, {"b": 2}]) is True or P._fp_record_list([{"a": 1}]))
check("scalars are a value", not P._fp_record_list(["a", "b"]))
check("mixed is a value — one odd element must not turn a name list into a tree", not P._fp_record_list(["a", {"b": 1}]))
check("empty is a value", not P._fp_record_list([]))
check("a dict is not a list", not P._fp_record_list({"a": 1}))

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: the walkers stopped agreeing about lists" % len(FAILS)) if ok
          else "PERTURB FAILED — every walker was told to ignore lists and nothing noticed")
    sys.exit(0 if ok else 1)
print(("FAIL: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
