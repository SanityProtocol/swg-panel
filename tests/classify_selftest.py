#!/usr/bin/env python3
"""Self-test for the routing-target grammar — the one thing keeping its TWO implementations from drifting.

One grammar, two implementations, because they run in two places and neither can call the other:

  js/classify.js        — decides the badge the operator sees while typing, in the browser
  classify_target()     — swg-panel-server, the authority: decides what is STORED, and buckets patterns
                          for the node in cascade_plan

swg-noded has no third copy on purpose (it is handed pre-bucketed lists), so these two are the whole surface.
When they disagree nothing crashes, which is the problem: the field draws a confident badge for a rule the
panel then reads as something else, or quietly declines to keep — and the save's `dropped` report says an
entry "couldn't be read" for a token the operator watched the field accept.

BOTH ARE CHECKED AGAINST THE SAME TABLE, not against each other. A table is stronger: two implementations
that each match it necessarily match each other, and neither can drag the contract along with it. The table
was written BEFORE either implementation, deliberately — one derived from an implementation only proves that
implementation is self-consistent.

Checked per case: the KIND, and the canonical VALUE where one is expected. For an invalid token the `why`
CODE is compared, never the message — the prose belongs to each UI and is allowed to differ.

`idn` cases are reported separately: the two runtimes reach punycode by different roads (the browser's URL
parser is UTS-46, Python's codec is IDNA2003), so a divergence there is a real finding about which names are
reachable, not a typo in a regex.

Run:  python3 tests/classify_selftest.py          (exit 0 = all pass)
      SWG_CLASSIFY_PY_ONLY=1 python3 …            accept a run with no node, checking only the panel half

The JS half needs `node`. Without it this exits NON-ZERO by default rather than passing quietly: a grammar
gate that silently checked one of two implementations is worse than none, because it reads green.
"""
import importlib.machinery, importlib.util, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
JS = os.path.join(HERE, "..", "js", "classify.js")
VEC = os.path.join(HERE, "classify_vectors.json")
NO_NODE = object()          # distinct from None: "no node to run" is not "node ran and failed"
FAILS = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("   " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def load_panel():
    loader = importlib.machinery.SourceFileLoader("swgpanel", os.path.abspath(SERVER))
    spec = importlib.util.spec_from_loader("swgpanel", loader)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def js_results(cases):
    """Run js/classify.js over the cases in one node process.

    Returns the list, or NO_NODE when there is no node to run, or None when node ran and failed. Those two are
    not the same thing and must never print the same sentence: "node not found" for a broken script sends the
    reader to install something they already have."""
    script = (
        "import { classify } from %s;\n"
        "const cases = JSON.parse(process.argv[2]);\n"
        "console.log(JSON.stringify(cases.map(c => classify(c))));\n" % json.dumps(os.path.abspath(JS))
    )
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as f:
        f.write(script); path = f.name
    try:
        r = subprocess.run(["node", path, json.dumps([c["in"] for c in cases])],
                           capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return NO_NODE
    except subprocess.TimeoutExpired:
        print("  node timed out"); return None
    finally:
        os.unlink(path)
    if r.returncode != 0:
        print("  node failed: " + (r.stderr or "").strip()[:300])
        return None
    return json.loads(r.stdout)


def one(name, got, want):
    """Compare one implementation's answer to the table. `why` is a code; a message is never compared."""
    if (got or {}).get("kind") != want.get("kind"):
        return "%s: kind %r, table says %r" % (name, (got or {}).get("kind"), want.get("kind"))
    if want.get("value") is not None and (got or {}).get("value") != want["value"]:
        return "%s: value %r, table says %r" % (name, (got or {}).get("value"), want["value"])
    if want.get("why") is not None and (got or {}).get("why") != want["why"]:
        return "%s: why %r, table says %r" % (name, (got or {}).get("why"), want["why"])
    return None


def main():
    vectors = json.load(open(VEC))
    cases, idn = vectors.get("cases") or [], vectors.get("idn") or []
    if not cases:
        print("FAILED: the vector table has no cases — a gate with nothing in it reads green"); sys.exit(1)

    m = load_panel()
    if not hasattr(m, "classify_target"):
        print("FAILED: swg-panel-server has no classify_target()"); sys.exit(1)

    print("grammar vectors: %d cases + %d IDN\n" % (len(cases), len(idn)))

    py_bad = [e for e in (one("py " + c["in"], m.classify_target(c["in"]), c) for c in cases) if e]
    check("panel classify_target() matches the table (%d cases)" % len(cases), not py_bad,
          "; ".join(py_bad[:4]))

    js = js_results(cases)
    if js is NO_NODE and os.environ.get("SWG_CLASSIFY_PY_ONLY"):
        print("  SKIP js/classify.js — no node, and SWG_CLASSIFY_PY_ONLY is set")
    elif js is NO_NODE:
        check("js/classify.js matches the table", False,
              "node not found — the BROWSER half of the grammar was not checked. Install node, or set "
              "SWG_CLASSIFY_PY_ONLY=1 to accept a half-run knowingly.")
    elif js is None:
        check("js/classify.js matches the table", False,
              "node ran and failed (see above) — the browser half was not checked. This is NOT a missing tool.")
    else:
        js_bad = [e for e in (one("js " + c["in"], g, c) for c, g in zip(cases, js)) if e]
        check("js/classify.js matches the table (%d cases)" % len(cases), not js_bad, "; ".join(js_bad[:4]))

    # IDN is reported separately and NEVER fails the run: the two runtimes reach punycode by different roads,
    # so a divergence is a finding about which names are reachable, not a broken regex. Printed so it is seen.
    if idn:
        py_idn = [e for e in (one("py " + c["in"], m.classify_target(c["in"]), c) for c in idn) if e]
        j = js_results(idn) if isinstance(js, list) else None
        js_idn = [] if not isinstance(j, list) else [e for e in (one("js " + c["in"], g, c)
                                                                 for c, g in zip(idn, j)) if e]
        print("  note IDN (%d): panel %s, browser %s"
              % (len(idn), "agrees" if not py_idn else "; ".join(py_idn[:2]),
                 "not run" if not isinstance(j, list) else ("agrees" if not js_idn else "; ".join(js_idn[:2]))))

    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS)); sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
