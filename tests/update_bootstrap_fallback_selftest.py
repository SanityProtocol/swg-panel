#!/usr/bin/env python3
"""Self-test for UPDATE-RESILIENCE — an update reads bootstrap.sh through a second door, and never runs half of it.

Every update on every box starts the same way: fetch bootstrap.sh from raw.githubusercontent.com and run it.
That one file is the ONLY thing an update reads from raw — bootstrap.sh fetches the tree from github.com itself
— and raw is the host filtered in the networks this product is most used in, while api.github.com is not
(docs/UPDATE-RESILIENCE-PLAN.md, 0a). So the fetch falls back to the API's contents endpoint: same repo, same
ref, same TLS, nothing new to trust.

The same change retires `curl | bash`, which executes whatever arrived before the connection died. A reset
halfway through bootstrap.sh ran half of it; a downloaded file is run only once curl says all of it arrived.

Four places carry the fetch, and all four are exercised as SHIPPED — none is restated here:
  · the root `swg-update` wrapper, written by install-host.sh, update.sh and lib/common.sh. Each heredoc is
    lifted out of its file and rendered by bash exactly as it is at install time, then run.
  · swg-noded's `default_update_cmd()`, loaded from the real module and run — once bare, and once through the
    real `_self_update_wrapper()` (0b), because that seam is where a node's verdict is written.

What has to hold, each a place a plausible version goes wrong:
  1. raw works → the API is NOT dialled. Its quota is 60/h per address, shared with the version check.
  2. ⚠️ raw fails → the API is dialled with the raw-accept header, and the update still runs.
  3. ⚠️ a PARTIAL download is never executed, even though curl wrote bytes to the file.
  4. both fail → non-zero, nothing runs, and the RAW cause is what an operator reads.
  5. an operator's own SWG_BOOTSTRAP_URL mirror gets no second door invented for it; a fork's raw URL gets
     ITS OWN API door, translated rather than hardcoded to this repo.
  6. SWG_BOOTSTRAP_URL still names the raw URL after an API fetch — bootstrap.sh infers the ref from it, and
     losing that is the silent main-downgrade 51a4b10 fixed.
  7. the wrapper survives rewriting itself mid-run (the braces + `exit` fix), the temp file is removed, and
     bootstrap's exit code is the wrapper's.
  8. the three wrapper copies are byte-identical from `URL=` to `exit` — they have drifted before.

Hermetic: `curl` is a stub on PATH that records every URL dialled and plays ok / fail / partial per host;
bootstrap is a stub that records its args and environment. No network, no root, no systemd.

Run: python3 tests/update_bootstrap_fallback_selftest.py            (0 = pass)
     --perturb   three perturbations of the shipped source — the wrappers lose the API door; the wrappers run
                 what arrived; the node loses the API door — and exits 0 only if EVERY one goes red.
"""
import importlib.machinery, importlib.util, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.path.join(ROOT, "swg-noded")
WRAPPERS = ("install-host.sh", "update.sh", "lib/common.sh")
PERTURB = "--perturb" in sys.argv

RAW_DEV = "https://raw.githubusercontent.com/SanityProtocol/swg-panel/dev/bootstrap.sh"
API_DEV = "https://api.github.com/repos/SanityProtocol/swg-panel/contents/bootstrap.sh?ref=dev"
ACCEPT = "Accept: application/vnd.github.raw"
BOOT_ARGS = "update -y --no-components --node-only"

TMP = tempfile.mkdtemp(prefix="swg-bootfetch-")
BIN = os.path.join(TMP, "bin")
os.makedirs(BIN)

# The curl stub. Mode per host comes from $STUB_RAW / $STUB_API / $STUB_OTHER. `partial` writes a script that would print
# PARTIAL-RAN and then break off mid-construct — exactly what a reset leaves — and exits 18 as curl does.
_CURL = r'''#!/usr/bin/env bash
out=""; url=""; hdr=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2;;
    -H) hdr="$hdr|$2"; shift 2;;
    --connect-timeout|--max-time) shift 2;;
    -*) shift;;
    *) url="$1"; shift;;
  esac
done
printf '%s\t%s\n' "$url" "$hdr" >> "$CURL_LOG"
case "$url" in
  https://raw.githubusercontent.com/*) mode="$STUB_RAW";;
  https://api.github.com/*) mode="$STUB_API";;
  *) mode="$STUB_OTHER";;
esac
case "$mode" in
  ok) cp "$BOOT_STUB" "$out"; exit 0;;
  partial) printf 'echo PARTIAL-RAN >> "$BOOT_LOG"\nif true; then\n  echo' > "$out"
           echo "curl: (18) transfer closed with outstanding read data remaining" >&2; exit 18;;
  *) h="${url#https://}"; echo "curl: (7) Failed to connect to ${h%%/*} port 443" >&2; exit 7;;
esac
'''
_BOOT = r'''#!/usr/bin/env bash
printf 'ran args=[%s] url=[%s] ref=[%s]\n' "$*" "${SWG_BOOTSTRAP_URL:-}" "${SWG_REF:-}" >> "$BOOT_LOG"
if [ -n "${REWRITE_WRAPPER:-}" ]; then
  # Refill the wrapper IN PLACE (same inode, as `cat >` does) with something longer, whose lines are commands.
  # An unguarded wrapper reads on past its old end into this and runs `pass through`.
  for i in $(seq 1 300); do echo "pass through"; done > "$REWRITE_WRAPPER"
fi
exit "${BOOT_RC:-0}"
'''
open(os.path.join(BIN, "curl"), "w").write(_CURL)
os.chmod(os.path.join(BIN, "curl"), 0o755)
BOOT_STUB = os.path.join(TMP, "bootstrap-stub.sh")
open(BOOT_STUB, "w").write(_BOOT)


def _read(p):
    try:
        return open(p, encoding="utf-8").read()
    except OSError:
        return ""


def _run(argv, extra, cwd):
    """Run argv with the stubs on PATH. → (proc, curl calls as [url, headers], boot log, leftover temp files)."""
    env = {"PATH": BIN + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
           "HOME": cwd, "TMPDIR": cwd, "LANG": "C.UTF-8",
           "CURL_LOG": os.path.join(cwd, "curl.log"), "BOOT_LOG": os.path.join(cwd, "boot.log"),
           "BOOT_STUB": BOOT_STUB, "STUB_RAW": "ok", "STUB_API": "ok", "STUB_OTHER": "fail"}
    # ⚠️ THE STUB'S MODES LIVE UNDER STUB_*. The wrapper assigns its own `API` variable, and assigning to a name
    # the environment already exports rewrites the EXPORTED copy — so a mode named API reached the curl stub as
    # a URL, and every fallback check went red over code that was correct.
    env.update({("STUB_" + k if k in ("RAW", "API", "OTHER") else k): v for k, v in extra.items()})
    p = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, timeout=60)
    calls = [l.split("\t") for l in _read(env["CURL_LOG"]).splitlines() if l]
    leftovers = sorted(f for f in os.listdir(cwd) if f.startswith("tmp."))
    return p, calls, _read(env["BOOT_LOG"]), leftovers


def _load_noded(path):
    os.environ["SWG_NODED_STATE"] = tempfile.mkdtemp(prefix="state-", dir=TMP)
    spec = importlib.util.spec_from_loader("nd_bootfetch", importlib.machinery.SourceFileLoader("nd_bootfetch", path))
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    return m


def suite(wrapper_srcs, noded_path):
    fails = []

    def check(name, cond, detail=""):
        print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
        if not cond:
            fails.append(name)

    # ── the root swg-update wrapper, three copies ────────────────────────────────────────────────────────────
    rendered = {}
    for f in WRAPPERS:
        hits = re.findall(r"<<WRAP\n(.*?)\nWRAP\n", wrapper_srcs[f], re.S)
        # An extraction that found nothing would make every check below vacuous — fatal, not skipped.
        check("[0] %s carries exactly one swg-update heredoc" % f, len(hits) == 1, len(hits))
        if len(hits) != 1:
            continue
        r = subprocess.run(["bash", "-c", "_swg_ref=dev\ncat <<WRAP\n%s\nWRAP\n" % hits[0]],
                           capture_output=True, text=True)
        check("[0b] %s's heredoc renders" % f, r.returncode == 0 and "curl" in r.stdout, r.stderr.strip())
        rendered[f] = r.stdout

    for f, script in rendered.items():
        syn = subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True)
        check("[1] %s: the rendered wrapper is valid shell" % f, syn.returncode == 0, syn.stderr.strip())

        def go(extra=None, rewrite=False):
            d = tempfile.mkdtemp(dir=TMP)
            w = os.path.join(d, "swg-update")
            open(w, "w").write(script)
            os.chmod(w, 0o755)
            e = dict(extra or {})
            if rewrite:
                e["REWRITE_WRAPPER"] = w
            return _run(["bash", w, "--node-only"], e, d)

        p, calls, boot, left = go()
        check("[2] %s: raw works → bootstrap runs with the passed-through flags" % f,
              p.returncode == 0 and boot.count("ran ") == 1 and "args=[%s]" % BOOT_ARGS in boot, (p.returncode, boot, p.stderr))
        check("[2b] %s: ⚠️ raw works → the API is NOT dialled" % f, calls == [[RAW_DEV, ""]], calls)
        check("[2c] %s: the temp file is removed" % f, left == [], left)

        p, calls, boot, left = go({"RAW": "fail"})
        check("[3] %s: ⚠️ raw fails → the update still runs" % f,
              p.returncode == 0 and boot.count("ran ") == 1, (p.returncode, boot, p.stderr))
        check("[3b] %s: …through the API contents endpoint, raw-accept header" % f,
              [API_DEV, "|" + ACCEPT] in calls, calls)
        check("[3c] %s: ⚠️ SWG_BOOTSTRAP_URL still names raw, so bootstrap infers the ref" % f,
              "url=[%s]" % RAW_DEV in boot, boot)
        check("[3d] %s: it says it fell back" % f, "api.github.com" in p.stderr, p.stderr)

        p, calls, boot, left = go({"RAW": "partial"})
        check("[4] %s: ⚠️ a partial download is NEVER executed" % f, "PARTIAL-RAN" not in boot, boot)
        check("[4b] %s: …and the API copy runs instead" % f,
              p.returncode == 0 and boot.count("ran ") == 1, (p.returncode, boot, p.stderr))

        p, calls, boot, left = go({"RAW": "fail", "API": "fail"})
        check("[5] %s: both doors fail → non-zero, nothing runs" % f, p.returncode != 0 and boot == "", (p.returncode, boot))
        check("[5b] %s: the raw cause is on stderr" % f, "raw.githubusercontent.com port 443" in p.stderr, p.stderr)
        check("[5c] %s: the temp file is removed on failure too" % f, left == [], left)

        p, calls, boot, left = go({"SWG_BOOTSTRAP_URL": "https://mirror.example/swg/bootstrap.sh"})
        check("[6] %s: an operator's own mirror gets no invented second door" % f,
              p.returncode != 0 and boot == "" and not any("api.github.com" in c[0] for c in calls), calls)

        fork_raw = "https://raw.githubusercontent.com/someone/fork/feat/bootstrap.sh"
        p, calls, boot, left = go({"SWG_BOOTSTRAP_URL": fork_raw, "RAW": "fail"})
        check("[6b] %s: a fork's raw URL gets ITS OWN API door" % f,
              ["https://api.github.com/repos/someone/fork/contents/bootstrap.sh?ref=feat", "|" + ACCEPT] in calls
              and "url=[%s]" % fork_raw in boot, (calls, boot))

        p, calls, boot, left = go({"BOOT_RC": "5"})
        check("[7] %s: bootstrap's exit code is the wrapper's" % f, p.returncode == 5, p.returncode)

        p, calls, boot, left = go(rewrite=True)
        check("[7b] %s: ⚠️ survives rewriting itself mid-run" % f,
              p.returncode == 0 and "command not found" not in p.stderr, (p.returncode, p.stderr[-200:]))

    def _fetch_block(s):
        m = re.search(r'^URL=.*?^exit$', s, re.S | re.M)
        return m.group(0) if m else None
    blocks = {f: _fetch_block(s) for f, s in rendered.items()}
    check("[8] ⚠️ the three wrapper copies are byte-identical from URL= to exit",
          len(rendered) == 3 and None not in blocks.values() and len(set(blocks.values())) == 1,
          {f: (len(b) if b else None) for f, b in blocks.items()})

    # ── swg-noded's own update command ───────────────────────────────────────────────────────────────────────
    m = _load_noded(noded_path)
    cmd = m.default_update_cmd({"node": {"update_ref": "dev"}})
    check("[N1] the node's command formats with no stray braces", "{ref}" not in cmd and "{{" not in cmd, cmd)
    syn = subprocess.run(["bash", "-n"], input=cmd, text=True, capture_output=True)
    check("[N1b] …and is valid shell", syn.returncode == 0, syn.stderr.strip())

    def ngo(extra=None, c=cmd):
        d = tempfile.mkdtemp(dir=TMP)
        return _run(["bash", "-c", c], extra or {}, d)

    p, calls, boot, left = ngo()
    check("[N2] node: raw works → bootstrap runs node-only, on its ref, API not dialled",
          p.returncode == 0 and "args=[%s]" % BOOT_ARGS in boot and "ref=[dev]" in boot and calls == [[RAW_DEV, ""]],
          (p.returncode, calls, boot, p.stderr))
    check("[N2b] node: the temp file is removed", left == [], left)
    p, calls, boot, left = ngo({"RAW": "fail"})
    check("[N3] node: ⚠️ raw fails → through the API, and the update runs",
          [API_DEV, "|" + ACCEPT] in calls and p.returncode == 0 and boot.count("ran ") == 1, (calls, boot, p.stderr))
    p, calls, boot, left = ngo({"RAW": "partial"})
    check("[N4] node: ⚠️ a partial download is NEVER executed",
          "PARTIAL-RAN" not in boot and boot.count("ran ") == 1, (boot, p.stderr))
    p, calls, boot, left = ngo({"RAW": "fail", "API": "fail"})
    check("[N5] node: both fail → non-zero, nothing runs", p.returncode != 0 and boot == "", (p.returncode, boot))
    check("[N5b] node: the temp file is removed on failure too", left == [], left)
    bad = m.default_update_cmd({"node": {"update_ref": "main; rm -rf /"}})
    check("[N6] node: an unsafe ref still falls back to main", "/main/bootstrap.sh" in bad and "rm -rf" not in bad, bad)

    # The seam with 0b: the command runs INSIDE the verdict wrapper, and the verdict is what the panel sees.
    ver = os.path.join(TMP, "VERSION")
    open(ver, "w").write("1.9.0-beta\n")
    m._noded_version_path = lambda: ver
    _geteuid = os.geteuid
    os.geteuid = lambda: 0          # the wrapper would otherwise prefix `sudo -n`, which a test box cannot answer
    try:
        wrapped = m._self_update_wrapper(cmd)
    finally:
        os.geteuid = _geteuid
    for label, extra, want in (("raw filtered, API reachable", {"RAW": "fail"}, "uptodate"),
                               ("both filtered", {"RAW": "fail", "API": "fail"}, "update-failed")):
        with __import__("contextlib").suppress(OSError):
            os.remove(m.UPDATE_RESULT_FILE)
        p, calls, boot, left = ngo(extra, c=wrapped)
        res = _read(m.UPDATE_RESULT_FILE)
        check("[N7] node through the 0b wrapper, %s → verdict '%s'" % (label, want),
              res.splitlines()[:1] == [want], res[:200])
    check("[N7b] ⚠️ a double failure's verdict carries the cause", "could not fetch bootstrap.sh" in res, res[-300:])

    return fails


# ── perturbations of the SHIPPED source ──────────────────────────────────────────────────────────────────────
API_LINE = "  curl -fsSL --connect-timeout 20 --max-time 120 -H 'Accept: application/vnd.github.raw' \"\\$API\" -o \"\\$B\"\n"
IF_LINE = "if ! curl -fsSL --connect-timeout 20 --max-time 120 \"\\$URL\" -o \"\\$B\"; then\n"
IF_PIPE = ("if ! { curl -fsSL --connect-timeout 20 --max-time 120 \"\\$URL\" -o \"\\$B\"; "
           "bash \"\\$B\" update -y --no-components \"\\$@\"; }; then\n")
NODE_API = "    'curl -fsSL --connect-timeout 20 --max-time 120 -o \"$B\" -H \"Accept: application/vnd.github.raw\" '\n"

srcs = {f: open(os.path.join(ROOT, f), encoding="utf-8").read() for f in WRAPPERS}
noded_src = open(NODED, encoding="utf-8").read()

try:
    if not PERTURB:
        fails = suite(srcs, NODED)
        print()
        if fails:
            print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
            sys.exit(1)
        print("all checks passed")
        sys.exit(0)

    def _swap(text, old, new, where):
        # A drifted anchor would perturb NOTHING and read as "not caught" — or worse, as caught by accident.
        assert text.count(old) == 1, "perturbation anchor drifted in %s (%d hits) — fix the gate" % (where, text.count(old))
        return text.replace(old, new, 1)

    perts = []
    perts.append(("the wrappers lose the API door",
                  {f: _swap(s, API_LINE, "  false\n", f) for f, s in srcs.items()}, noded_src, ("[3", "[4b", "[6b")))
    perts.append(("the wrappers run what arrived",
                  {f: _swap(s, IF_LINE, IF_PIPE, f) for f, s in srcs.items()}, noded_src, ("[4] ",)))
    perts.append(("the node loses the API door",
                  srcs, _swap(noded_src, NODE_API, "    'false '\n", "swg-noded"), ("[N3", "[N4", "[N7")))

    missed = []
    for label, wsrcs, nsrc, expect in perts:
        print("\n── perturbation: %s" % label)
        npath = os.path.join(TMP, "swg-noded-perturbed")
        open(npath, "w", encoding="utf-8").write(nsrc)
        fails = suite(wsrcs, npath)
        hit = [x for x in fails if x.startswith(expect)]
        print("  → %s (%d red, %d of them the expected checks)" % ("CAUGHT" if hit else "NOT CAUGHT", len(fails), len(hit)))
        if not hit:
            missed.append(label)
    print()
    if missed:
        print("PERTURBATIONS NOT CAUGHT: %s" % "; ".join(missed))
        sys.exit(1)
    print("every perturbation went red")
    sys.exit(0)
finally:
    shutil.rmtree(TMP, ignore_errors=True)
