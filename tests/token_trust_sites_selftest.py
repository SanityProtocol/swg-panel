#!/usr/bin/env python3
"""Self-test — EVERY CALL THAT CARRIES THE NODE TOKEN GOES OUT WITH THE TRUST THE NODE'S OWN DECISION SET, DRIVEN FOR REAL.

1.8.8 qualification, round 8 (independent re-check, I19): changing the trust arguments of a token-bearing call to
`"no" ""` — the certificate check switched off — left every gate naming the file green at five sites: uninstall.sh's
"uninstalling" status, bootstrap.sh's salvage whoami, install-node.sh's and install-docker.sh's rename, and convert.sh's
D→B status (LC_FP). panel_req_selftest [9] only checked that each site CALLS panel_req; what it passes was never looked at.

This gate drives each site's SHIPPED code — lifted from the script, stubs only for prompts and side effects — against a
panel at 127.0.0.1 whose certificate the test controls, per connection:
  all-C   the node is pinned to certificate B, the panel presents C       → the listener must receive NOTHING
  ca-B    the node CA-verifies (verify=yes, no pin), the panel presents B (self-signed, trusted by no CA) → NOTHING
  last-C  B for every call but the last, C for the last (a whoami, then the rename) → all but the last arrive
  all-B   the pinned certificate throughout → every call arrives (the positive control: the path really was driven)

  [0] every panel_req call in the shipped scripts, and every LC_VERIFY / LC_FP assignment that carries a node's trust,
      is one a driver below lifts — a new one fails here instead of passing unseen (the loopback ones, to this box's own
      panel, are listed as such). Round 10's mutations (I19) closed four ways through it: the census reads EVERY shell
      file of the tree (a new lib file, the Docker entrypoints, nix/adopt.sh); it counts calls per (file, endpoint)
      EXACTLY — a second call to an endpoint a driver already claims is a new, undriven call; every `panel_req` word in
      the code must be a call it can read (unquoted trust arguments, another method, a split line are refused, not
      skipped); a comment is a # that starts a word OUTSIDE quotes (a " #" inside a string hid a call); a trust
      assignment is one at a word's start outside quotes (a message naming LC_FP is not one), a literal "no pin / no
      verify" only where the same line points LC_URL at this box's own 127.0.0.1 panel, and never an `unset`
  [1]–[14] one driver per site family, each under the four panels above
  [15] a Docker node's re-install starts from the trust the node LEARNED (docker_node_panel: a transfer's or a re-point's
       URL, token, verify and pin), lifted and run — the pin it carries is the one ask_node_conn decides with

Run: python3 tests/token_trust_sites_selftest.py     (0 = pass)
     --perturb-site <n>   the n-th token-bearing call (the order of [0]) sends with `"no" ""` — round 8's mutation → RED
     --perturb-lc <n>     the n-th trust assignment loses it: LC_FP="" (or LC_VERIFY=no where it carries no pin) → RED
     --perturb            every site and every assignment in turn, each run on its own — each must go red
"""
import glob, hashlib, http.server, json, os, re, shlex, socket, ssl, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
FILES = ("lib/common.sh", "uninstall.sh", "bootstrap.sh", "install-node.sh", "install-docker.sh", "install-host.sh",
         "update.sh", "convert.sh")
# ⚠️ EVERY SHELL FILE OF THE TREE, not the eight the drivers lift: a call in a new lib file, in the Docker entrypoints or
# in nix/adopt.sh was never looked at (1.8.8 qualification, round 10, I19 class 4).
SCAN = tuple(sorted(set(FILES) | {os.path.relpath(q, ROOT) for g in ("*.sh", "lib/*.sh", "docker/*.sh", "nix/*.sh")
                                   for q in glob.glob(os.path.join(ROOT, g))}))
SRC = {f: open(os.path.join(ROOT, f), encoding="utf-8").read() for f in SCAN}
ARGS = sys.argv[1:]

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:700]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

# ── [0]'s census: the token-bearing calls and the trust assignments, in the shipped text ─────────────────────────────
CALL_RE = re.compile(r'panel_req\s+(GET|POST)\s+"([^"]*)"(\s*\\\n\s*|\s+)("[^"]*")\s+("[^"]*")')
LC_AT = re.compile(r'\bLC_(FP|VERIFY)=')

def _dq(t, j):                       # after an opening " — to just past its closing one ($(…) inside parsed as bash does)
    while j < len(t):
        if t[j] == "\\":
            j += 2; continue
        if t[j] == '"':
            return j + 1
        if t.startswith("$(", j):
            j = _cs(t, j + 2); continue
        j += 1
    raise ValueError("unterminated double quote")
def _cs(t, j):                       # after $( — to just past its closing )
    depth = 1
    while j < len(t):
        ch = t[j]
        if ch == "\\":
            j += 2; continue
        if ch == "'":
            j = t.index("'", j + 1) + 1; continue
        if ch == '"':
            j = _dq(t, j + 1); continue
        if t.startswith("$(", j):
            j = _cs(t, j + 2); continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    raise ValueError("unterminated $(")
def word_end(t, j):                  # the end of the shell word starting at j
    while j < len(t) and t[j] not in " \t;\n":
        if t[j] == "\\":
            j += 2
        elif t[j] == "'":
            j = t.index("'", j + 1) + 1
        elif t[j] == '"':
            j = _dq(t, j + 1)
        elif t.startswith("$(", j):
            j = _cs(t, j + 2)
        else:
            j += 1
    return j
def line_of(t, pos):
    return t[t.rfind("\n", 0, pos) + 1:t.find("\n", pos)]
def _scan_line(line, stop=None):
    """(where the comment starts — a # that begins a word OUTSIDE quotes — , whether `stop` lies inside quotes)"""
    j, n, q, inq = 0, len(line), None, False
    while j < n:
        if stop is not None and j == stop:
            inq = q is not None
        c = line[j]
        if q == "'":
            if c == "'": q = None
        elif q == '"':
            if c == "\\": j += 1
            elif c == '"': q = None
        elif c == "\\": j += 1
        elif c in "'\"": q = c
        elif c == "#" and (j == 0 or line[j - 1] in " \t;|&("):
            return j, inq
        j += 1
    return n, inq
def _line_at(t, pos):
    a = t.rfind("\n", 0, pos) + 1
    b = t.find("\n", pos)
    return t[a:(len(t) if b < 0 else b)], pos - a
def is_comment(t, pos):
    """⚠️ QUOTE-AWARE. `_n=" #2"; panel_req …` read as a comment from the quoted #, and hid the call (round 10, I19 class 5)."""
    line, col = _line_at(t, pos)
    return col >= _scan_line(line)[0]
def in_quotes(t, pos):
    line, col = _line_at(t, pos)
    return _scan_line(line, col)[1]
PR_WORD = re.compile(r"(?<![\w-])panel_req(?![\w(-])")      # the word panel_req — not its definition, not a longer name
LC_URL_LOOP = re.compile(r"\bLC_URL=.*127\.0\.0\.1")      # LC_URL pointed at this box's own panel, on the line's CODE

UNREAD, LITERALS, UNSETS = [], [], []    # [0]'s refusals: a call it cannot read, a literal away from loopback, an unset
def census(src):
    calls, lcs = [], []
    del UNREAD[:], LITERALS[:], UNSETS[:]
    for f in SCAN:
        t = src[f]
        starts = set()
        for m in CALL_RE.finditer(t):
            if not is_comment(t, m.start()):
                calls.append((f, m.start(), m.group(0))); starts.add(m.start())
        # ⚠️ EVERY panel_req WORD IN THE CODE IS A CALL THIS READS. One it could not parse — unquoted trust arguments, a
        # method other than GET/POST, a line split before the URL — was skipped, and so never driven (round 10, I19 class 2).
        for m in PR_WORD.finditer(t):
            if m.start() not in starts and not is_comment(t, m.start()):
                UNREAD.append("%s: %s" % (f, " ".join(line_of(t, m.start()).split())[:120]))
        for m in LC_AT.finditer(t):
            # an ASSIGNMENT: at a word's start, outside quotes — `sub "pin in use: LC_FP=…"` is a message (round 10, 5d)
            if is_comment(t, m.start()) or in_quotes(t, m.start()) or (m.start() and t[m.start() - 1] not in " \t\n;&|({"):
                continue
            a, b = m.end(), word_end(t, m.end())
            if t[a:b] in ('""', "no", '"no"', "", "''"):
                # a literal "no pin / no verify" is the loopback to this box's own panel — and ONLY that: on the line that
                # points LC_URL at 127.0.0.1. Anywhere else it drops the node's trust for every later status (round 10, 3a)
                _ln = line_of(t, m.start())
                if not LC_URL_LOOP.search(_ln[:_scan_line(_ln)[0]]):
                    LITERALS.append("%s: %s" % (f, " ".join(line_of(t, m.start()).split())[:120]))
                continue
            lcs.append((f, m.start(), t[m.start():b], m.group(1), a, b))
        for m in re.finditer(r"\bunset\b[^;\n]*\bLC_(?:FP|VERIFY)\b", t):
            if not is_comment(t, m.start()) and not in_quotes(t, m.start()):
                UNSETS.append("%s: %s" % (f, " ".join(line_of(t, m.start()).split())[:120]))
    return calls, lcs

ORIG = dict(SRC)
CALLS0, LCS0 = census(SRC)

# ── the mutations ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _nth(flag, total):
    """the <n> a --perturb-site / --perturb-lc names — REFUSED when it is missing, not a number or out of range: without one
    nothing was planted, and the run read ALL PASS as if it were a perturbation that had gone green (round 10)"""
    if flag not in ARGS:
        return None
    i = ARGS.index(flag) + 1
    v = ARGS[i] if i < len(ARGS) else ""
    if not re.fullmatch(r"\d+", v) or int(v) >= total:
        print("%s needs the number of a site, 0–%d in the order of [0] (or --perturb for every one): %r is not one — "
              "nothing was planted, and this run would FALSE-PASS" % (flag, total - 1, v))
        sys.exit(3)
    return int(v)
MUT_SITE, MUT_LC = _nth("--perturb-site", len(CALLS0)), _nth("--perturb-lc", len(LCS0))
if "--perturb" in ARGS:
    rows, bad = [], []
    for kind, n, what in ([("--perturb-site", i, "%s: %s" % (c[0], " ".join(c[2].split())[:90])) for i, c in enumerate(CALLS0)]
                          + [("--perturb-lc", i, "%s: %s" % (c[0], c[2][:90])) for i, c in enumerate(LCS0)]):
        r = subprocess.run([sys.executable, os.path.abspath(__file__), kind, str(n)], capture_output=True, text=True, timeout=900)
        red = r.returncode == 0 and "RED as expected" in r.stdout
        state = "RED   " if red else ("BROKEN" if "Traceback" in r.stderr + r.stdout else "GREEN ")
        rows.append("  %s %s %-2d %s" % (state, kind, n, what))
        if not red:
            bad.append("%s %d" % (kind, n))
    print("\n".join(rows))
    print("\nPERTURB OK — every one of the %d mutations went red on its own" % len(rows) if not bad
          else "\nPERTURB FAILED — still green: %s" % ", ".join(bad))
    sys.exit(1 if bad else 0)
MUTATED = None
if MUT_SITE is not None:
    f, pos, text = CALLS0[MUT_SITE]
    m = CALL_RE.match(SRC[f], pos)
    SRC[f] = SRC[f][:m.start(4)] + '"no"' + SRC[f][m.end(4):m.start(5)] + '""' + SRC[f][m.end(5):]
    MUTATED = "call %d (%s)" % (MUT_SITE, f)
if MUT_LC is not None:
    f, pos, text, which, a, b = LCS0[MUT_LC]
    SRC[f] = SRC[f][:a] + ('""' if which == "FP" else "no") + SRC[f][b:]
    MUTATED = "assignment %d (%s)" % (MUT_LC, f)

# ── lifting ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def fn(f, name):
    src = SRC[f]
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot lift %s from %s" % (name, f)
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated %s in %s" % (name, f))

def block(f, start, end, incl_end=True):
    src = SRC[f]
    a = src.index(start)
    b = src.index(end, a) + (len(end) if incl_end else 0)
    assert src.count(start) == 1, "the block anchor is not unique in %s: %r" % (f, start[:70])
    return src[a:b] + "\n"

def line_with(f, needle):
    """The whole line holding `needle` (unique) — for a one-line site whose own arguments a mutation rewrites."""
    src = SRC[f]
    assert src.count(needle) == 1, "the line anchor is not unique in %s: %r" % (f, needle)
    i = src.index(needle)
    return src[src.rfind("\n", 0, i) + 1:src.find("\n", i)] + "\n"

def swap(text, old, new, count=1):
    assert text.count(old) == count, "a lifted text lost its anchor (%r) — this run would FALSE-PASS" % old[:70]
    return text.replace(old, new)

T = tempfile.mkdtemp(prefix="tokentrust-")
def wr(path, text, mode=0o600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text); os.chmod(path, mode); return path

# ── the panel: TLS, its certificate chosen per connection ──────────────────────────────────────────────────────────────
def openssl(*a):
    subprocess.run(["openssl", *a], check=True, capture_output=True)
def mkcert(tag):
    c, k = os.path.join(T, tag + ".pem"), os.path.join(T, tag + ".key")
    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30", "-subj", "/CN=127.0.0.1",
            "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", k, "-out", c)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(c, k)
    return ctx, hashlib.sha256(ssl.PEM_cert_to_DER_cert(open(c).read())).hexdigest()
CTX_B, PIN_B = mkcert("b")
CTX_C, PIN_C = mkcert("c")

LOG, PLAN = [], {"ctxs": [], "i": 0}
class H(http.server.BaseHTTPRequestHandler):
    def _h(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode() if n else ""
        LOG.append((self.command, self.path, self.headers.get("Authorization") or "", body))
        out = (b'{"ok": true, "data": {"name": "panel-name", "last_seen": 1790000000}}' if self.path.endswith("/whoami")
               else b'{"ok": true}')
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    do_GET = do_POST = _h
    def log_message(self, *a):
        pass
class Srv(http.server.ThreadingHTTPServer):
    daemon_threads = True
    def get_request(self):
        conn, addr = self.socket.accept()
        i = PLAN["i"]; PLAN["i"] += 1
        ctxs = PLAN["ctxs"] or [CTX_B]
        ctx = ctxs[i] if i < len(ctxs) else ctxs[-1]
        conn.settimeout(10)
        return ctx.wrap_socket(conn, server_side=True), addr
srv = Srv(("127.0.0.1", 0), H); PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "https://127.0.0.1:%d" % PORT

# ── the drivers ───────────────────────────────────────────────────────────────────────────────────────────────────────
PRE = ('set -u\ninfo(){ echo "INFO $*"; }; ok(){ echo "OK $*"; }; warn(){ echo "WARN $*" >&2; }; sub(){ echo "SUB $*"; }\n'
       'step(){ :; }; b(){ printf %s "$*"; }; bb(){ printf %s "$*"; }; col(){ shift; printf %s "$*"; }\n'
       'die(){ echo "DIE $*" >&2; exit 9; }; DRYRUN=false\n')
LIB = lambda: fn("lib/common.sh", "panel_req") + fn("lib/common.sh", "lc_emit_post") + fn("lib/common.sh", "lc_emit_file")
TYPED = 'ask_valid(){ case "$1" in *URL*) printf -v "$3" %s "$2";; *) printf -v "$3" %s renamed-box;; esac; }\nv_name(){ return 0; }\n'
LCINIT = 'lc_init(){ LC_OP="$1"; "$2" "$(_lc_inprogress "$1")"; }\n'

def posture(p):
    """(verify yes|no, pin) the node's trust carries in this panel: pinned to B, or CA-verifying."""
    return ("yes", "") if p == "ca-B" else ("no", PIN_B)

def d_uninstall_bare(p, tok, d):
    v, fp = posture(p)
    cfg = wr(os.path.join(d, "config.json"), json.dumps({"panel": {"url": URL, "token": tok, "verify": v == "yes", "fingerprint": fp}}))
    return (PRE + fn("uninstall.sh", "panel_req") + fn("uninstall.sh", "_goodbye_post")
            + swap(fn("uninstall.sh", "node_goodbye"), "/etc/swg-agent/config.json", cfg)
            + "_goodbye_nobody(){ return 1; }\n_goodbye_skipped(){ :; }\nnode_goodbye\n")

def _docker_env(d, tok, p, extra=""):
    v, fp = posture(p)
    wr(os.path.join(d, ".env"), "PANEL_URL=%s\nNODE_TOKEN=%s\nTLS_VERIFY=%s\nTLS_FINGERPRINT=%s\n%s" % (URL, tok, v, fp, extra))
    return d

def d_uninstall_docker(p, tok, d):
    _docker_env(d, tok, p)
    return (PRE + 'DOCKER_DIR="%s"\n' % d + fn("uninstall.sh", "panel_req") + fn("uninstall.sh", "_goodbye_post")
            + fn("uninstall.sh", "_docker_node_panel") + fn("uninstall.sh", "docker_node_goodbye")
            + fn("uninstall.sh", "_proc_post") + fn("uninstall.sh", "docker_node_uninstalling")
            + "_goodbye_nobody(){ return 1; }\n_goodbye_skipped(){ :; }\ndocker_node_uninstalling\ndocker_node_goodbye\n")

def d_bootstrap_bare(p, tok, d):
    v, fp = posture(p)
    cfg = wr(os.path.join(d, "config.json"), json.dumps({"panel": {"url": URL, "token": tok, "verify": v == "yes", "fingerprint": fp}}))
    return (PRE + fn("bootstrap.sh", "panel_req") + fn("bootstrap.sh", "_fmt_epoch") + fn("bootstrap.sh", "_salv_created")
            + fn("bootstrap.sh", "_salv_trust") + fn("bootstrap.sh", "_salv_block") + '_salv_block 1 "%s" "%s" "%s"\n' % (tok, URL, cfg))

def d_bootstrap_docker(p, tok, d):
    _docker_env(d, tok, p)
    return (PRE + fn("bootstrap.sh", "panel_req") + fn("bootstrap.sh", "_fmt_epoch") + fn("bootstrap.sh", "_salv_created")
            + fn("bootstrap.sh", "_salv_trust") + fn("bootstrap.sh", "_salv_block") + '_salv_block 1 "%s" "%s" "%s/.env"\n' % (tok, URL, d))

def d_node_rename(p, tok, d):
    v, fp = posture(p)
    blk = block("install-node.sh", 'NODE_NAME="${NODE_NAME:-$(hostname -s 2>/dev/null || hostname)}"', '\nstep "Datapath tooling"\n', False)
    return (PRE + LIB() + TYPED + 'EXISTING=yes; SWG_CONVERT=""; NODE_TOKEN="%s"; PANEL_URL="%s"; TLS_VERIFY="%s"; TLS_FINGERPRINT="%s"\n'
            % (tok, URL, v, fp) + '_tty(){ return 1; }\n' + blk)

def d_node_status(p, tok, d):
    v, fp = posture(p)
    blk = block("install-node.sh", 'if [ "$EXISTING" = yes ] && ! $DRYRUN && [ "${SWG_CONVERT:-}" != 1 ] && [ -n "$EXIST_URL" ] && [ -n "$EXIST_TOKEN" ]; then',
                "\nfi\n")
    blk = swap(blk, "rm -rf /var/lib/swg-noded/iface-keys", ":")
    return (PRE + LIB() + fn("lib/common.sh", "_lc_inprogress") + LCINIT + 'installed_sum(){ :; }\nAGENT_DIR=x; NODED_DIR=y\n'
            + 'EXISTING=yes; EXIST_URL="%s"; EXIST_TOKEN="%s"; NODE_TOKEN="%s"; PANEL_URL="%s"; TLS_VERIFY="%s"; TLS_FINGERPRINT="%s"\n'
            % (URL, tok, tok, URL, v, fp) + blk)

def d_docker_convert_rename(p, tok, d):
    v, fp = posture(p)
    ren = block("install-docker.sh", "# push a box-name change once ask_node_conn has it", "\n# ───────────────────────── ensure Docker", False)
    return (PRE + LIB() + TYPED + 'SWG_CONVERT_DIR=convert-docker; NODE_TOKEN="%s"; PANEL_URL="%s"; TLS_VERIFY="%s"; TLS_FINGERPRINT="%s"; PUSH_NAME=""\n'
            % (tok, URL, v, fp) + fn("install-docker.sh", "ask_node_conn") + "ask_node_conn\n" + ren)

def d_docker_reinstall_rename(p, tok, d):
    v, fp = posture(p)
    _docker_env(d, tok, p)
    given = ('_GIVEN_TLS_VERIFY=yes; _GIVEN_TLS_FINGERPRINT=""' if p == "ca-B" else '_GIVEN_TLS_VERIFY=""; _GIVEN_TLS_FINGERPRINT="%s"' % fp)
    ren = block("install-docker.sh", "# push a box-name change once ask_node_conn has it", "\n# ───────────────────────── ensure Docker", False)
    return (PRE + LIB() + TYPED + fn("install-docker.sh", "_env_val") + fn("lib/common.sh", "_url_is_loopback")
            + 'v_httpsurl(){ return 0; }; node_panel_trust(){ echo "UNEXPECTED node_panel_trust" >&2; }; ask_yn_tty(){ echo no; }\n'
            + 'EXISTING_DOCKER=yes; SWG_CONVERT_DIR=""; INSTALL_DIR="%s"; NODE_TOKEN="%s"; PANEL_URL="%s"; TLS_VERIFY="%s"; PUSH_NAME=""; _EFF_URL=""\n'
            % (d, tok, URL, v) + given + "\n" + fn("install-docker.sh", "ask_node_conn") + "ask_node_conn\n" + ren)

def d_docker_status(p, tok, d):
    v, fp = posture(p)
    return (PRE + LIB() + fn("lib/common.sh", "_lc_inprogress") + LCINIT + fn("install-docker.sh", "lc_emit_docker")
            + 'docker(){ return 1; }\nEXISTING_DOCKER=yes; SWG_CONVERT_DIR=""; PROFILE=node; INSTALL_DIR="%s"; SWG_LC_PARENT=""\n' % d
            + 'NODE_TOKEN="%s"; PANEL_URL="%s"; TLS_VERIFY="%s"; TLS_FINGERPRINT="%s"; PANEL_PORT=2087\n' % (tok, URL, v, fp)
            + fn("install-docker.sh", "_lc_docker_arm") + "_lc_docker_arm\n")

def d_host(p, tok, d):
    v, fp = posture(p)
    cfg = wr(os.path.join(d, "config.json"), json.dumps({"panel": {"url": URL, "token": tok, "verify": v == "yes", "fingerprint": fp}}))
    b1 = block("install-host.sh", 'if [ "$EXISTING_HOST" = yes ] && ! $DRYRUN; then\n  mkdir -p "$STATE_DIR" 2>/dev/null || true', "\nfi\n")
    b1 = swap(b1, "/etc/swg-agent/config.json", cfg, b1.count("/etc/swg-agent/config.json"))
    b2 = block("install-host.sh", 'if [ "$EXISTING_HOST" = yes ] && ! $DRYRUN && [ "$HOST_HAS_WG" = yes ] && [ -n "${LC_URL:-}" ] && [ -n "${LC_TOKEN:-}" ]; then',
               "\nfi\n")
    return (PRE + LIB() + fn("lib/common.sh", "_lc_inprogress") + LCINIT + 'installed_sum(){ :; }\n'
            + 'EXISTING_HOST=yes; STATE_DIR="%s/state"; PANEL_DIR=x; SUB_DIR=x; NODED_DIR=x; AGENT_DIR=x; HOST_HAS_WG=yes\n' % d
            + 'HOST_NODE_NAME=renamed-box; _HOST_NAME_DEFAULT=old-box\n' + b1 + b2)

def d_convert_d2b(p, tok, d):
    _docker_env(d, tok, p, "NODE_ENDPOINT=192.0.2.4\n")
    rd = block("convert.sh", '  envf="$DOCKER_DIR/.env"; confd="$DOCKER_DIR/data/node-confs"',
               'die "couldn\'t read the node token / panel URL (docker .env missing and no recovery state)"\n')
    lc = line_with("convert.sh", "lc_init convert-bare lc_emit_post")
    return (PRE + LIB() + fn("lib/common.sh", "_lc_inprogress") + LCINIT + 'docker(){ return 1; }\nDOCKER_DIR="%s"\n' % d + rd + lc)

def d_convert_b2d(p, tok, d):
    v, fp = posture(p)
    cfg = wr(os.path.join(d, "config.json"), json.dumps({"panel": {"url": URL, "token": tok, "verify": v == "yes", "fingerprint": fp},
                                                        "endpoint_host": "192.0.2.5", "dns": ["1.1.1.1"]}))
    rd = block("convert.sh", "  cfg=/etc/swg-agent/config.json\n  [ -f \"$cfg\" ] || [ -n \"${SWG_RV_TOKEN:-}\" ]",
               'die "couldn\'t read the node token / panel URL (config missing and no recovery state)"\n')
    rd = swap(rd, "cfg=/etc/swg-agent/config.json", 'cfg="%s"' % cfg)
    lc = line_with("convert.sh", "lc_init convert-docker lc_emit_post")
    return (PRE + LIB() + fn("lib/common.sh", "_lc_inprogress") + LCINIT + fn("convert.sh", "_dns_ok") + rd + lc)

def d_update_bare(p, tok, d):
    v, fp = posture(p)
    cfg = wr(os.path.join(d, "config.json"), json.dumps({"panel": {"url": URL, "token": tok, "verify": v == "yes", "fingerprint": fp}}))
    lt = fn("update.sh", "lc_targets")
    lt = swap(lt, "/etc/swg-agent/config.json", cfg, lt.count("/etc/swg-agent/config.json"))
    return (PRE + LIB() + fn("update.sh", "lc_emit_upd") + 'NODE_ONLY=true; DOCKER_DIR="%s/none"\n' % d + lt + "lc_targets\nlc_emit_upd updating\n")

def d_update_docker(p, tok, d):
    _docker_env(d, tok, p, "PANEL_PORT=2087\n")
    lt = fn("update.sh", "lc_targets")
    lt = swap(lt, '[ -f /etc/swg-agent/config.json ]', '[ -f "%s/no-config.json" ]' % d)
    return (PRE + LIB() + fn("lib/common.sh", "docker_node_panel") + fn("update.sh", "lc_emit_upd")
            + 'docker(){ [ "$1" = ps ] && echo swg-node; return 0; }\nNODE_ONLY=true; DOCKER_DIR="%s"\n' % d + lt
            + "lc_targets\nlc_emit_upd updating\n")

#  name, driver, the calls it makes (method path, in order), the census entries it covers: (file, a piece of the text)
DRIVERS = [
    ("[1] uninstall.sh: a bare node's sign-off (node_goodbye → _goodbye_post)", d_uninstall_bare,
     ["POST /api/node/goodbye"], [("uninstall.sh", "/api/node/goodbye")], []),
    ("[2] uninstall.sh: a Docker node's \"uninstalling\" and sign-off (_docker_node_panel → _proc_post, _goodbye_post)",
     d_uninstall_docker, ["POST /api/node/proc-status", "POST /api/node/goodbye"], [("uninstall.sh", "/api/node/proc-status")], []),
    ("[3] bootstrap.sh: the salvage menu's whoami for a bare identity (_salv_trust → _salv_block)", d_bootstrap_bare,
     ["GET /api/node/whoami"], [("bootstrap.sh", "/api/node/whoami")], []),
    ("[4] bootstrap.sh: …and for a Docker .env identity", d_bootstrap_docker, ["GET /api/node/whoami"], [], []),
    ("[5] install-node.sh: a re-install's whoami and rename", d_node_rename, ["GET /api/node/whoami", "POST /api/node/rename"],
     [("install-node.sh", "/api/node/whoami"), ("install-node.sh", "/api/node/rename")], []),
    ("[6] install-node.sh: a re-install's \"reinstalling\" (LC_* → lc_emit_post)", d_node_status, ["POST /api/node/proc-status"],
     [("lib/common.sh", "/api/node/proc-status")], [("install-node.sh", 'LC_FP="${TLS_FINGERPRINT:-}"'), ("install-node.sh", 'LC_VERIFY="${TLS_VERIFY:-no}"')]),
    ("[7] install-docker.sh: a convert's whoami and rename (ask_node_conn, the push)", d_docker_convert_rename,
     ["GET /api/node/whoami", "POST /api/node/rename"],
     [("install-docker.sh", "/api/node/rename"), ("install-docker.sh", "/api/node/whoami#1")], []),
    ("[8] install-docker.sh: a re-install's whoami and rename (the kept .env's node, its pin given)", d_docker_reinstall_rename,
     ["GET /api/node/whoami", "POST /api/node/rename"], [("install-docker.sh", "/api/node/whoami#2")], []),
    ("[9] install-docker.sh: a node re-install's \"reinstalling\" (_lc_docker_arm)", d_docker_status, ["POST /api/node/proc-status"],
     [], [("install-docker.sh", 'LC_FP="${TLS_FINGERPRINT:-}"'), ("install-docker.sh", 'LC_VERIFY="${TLS_VERIFY:-no}"')]),
    ("[10] install-host.sh: a master's \"reinstalling\", whoami and rename (the local node's config)", d_host,
     ["POST /api/node/proc-status", "GET /api/node/whoami", "POST /api/node/rename"],
     [("install-host.sh", "/api/node/whoami"), ("install-host.sh", "/api/node/rename")],
     [("install-host.sh", 'LC_VERIFY="$(python3'), ("install-host.sh", 'LC_FP="$(python3')]),
    ("[11] convert.sh: Docker → bare, the node's \"converting\" (the pin read from the .env)", d_convert_d2b,
     ["POST /api/node/proc-status"], [],
     [("convert.sh", 'LC_FP="${NFP:-}"; lc_init convert-bare'), ("convert.sh", 'LC_VERIFY="${NVERIFY:-no}"; LC_FP="${NFP:-}"; lc_init convert-bare')]),
    ("[12] convert.sh: bare → Docker, the node's \"converting\" (the pin read from the bare config)", d_convert_b2d,
     ["POST /api/node/proc-status"], [],
     [("convert.sh", 'LC_FP="${NFP:-}"; lc_init convert-docker'), ("convert.sh", 'LC_VERIFY="${NVERIFY:-no}"; LC_FP="${NFP:-}"; lc_init convert-docker')]),
    ("[13] update.sh: a bare node's \"updating\" (lc_targets from the agent config)", d_update_bare, ["POST /api/node/proc-status"], [],
     [("update.sh", 'LC_VERIFY="$(python3'), ("update.sh", 'LC_FP="$(python3')]),
    ("[14] update.sh: a Docker node's \"updating\" (lc_targets → docker_node_panel)", d_update_docker, ["POST /api/node/proc-status"], [],
     [("update.sh", 'LC_VERIFY="$DNP_VERIFY"'), ("update.sh", 'LC_FP="$DNP_FP"')]),
]

# ── [0] the census ────────────────────────────────────────────────────────────────────────────────────────────────────
print("[0] every token-bearing call and trust assignment is driven below")
seen = {}
def call_key(c):
    f, pos, text = c
    ep = re.search(r"/api/node/([a-z-]+)", text)
    k = "/api/node/" + (ep.group(1) if ep else "?")
    n = seen.setdefault((f, k), 0) + 1; seen[(f, k)] = n
    return f, k, n
claimed = {(f, a) for _, _, _, cs, _ in DRIVERS for f, a in cs}
# ⚠️ COUNTED, NOT NAMED. A claim of (file, endpoint) covered EVERY call to it in that file, so a second whoami, goodbye or
# proc-status — at top level, in a new function, inside a heredoc'd script — passed as "claimed" and was never driven
# (round 10, I19 class 4). A plain claim is the file's ONE call to that endpoint; a second one needs its own `#2` claim.
want = {}
for f, a in claimed:
    ep, _, n = a.partition("#")
    want[(f, ep)] = max(want.get((f, ep), 0), int(n or 1))
uncovered = []
for c in CALLS0:
    f, k, n = call_key(c)
    if n > want.get((f, k), 0):
        uncovered.append("%s %s (#%d%s)" % (f, k, n, ", a call to an endpoint claimed once" if (f, k) in want else ""))
check("every panel_req call names an endpoint a driver claims", not uncovered, uncovered)
short = ["%s %s: %d claimed, %d found" % (f, k, want[(f, k)], seen.get((f, k), 0)) for f, k in sorted(want) if seen.get((f, k), 0) != want[(f, k)]]
check("…and each (file, endpoint) holds exactly as many calls as the drivers claim — no more, no fewer", not short and not uncovered, short or uncovered)
check("every panel_req word in the code is a call the census can read (quoted trust arguments, GET or POST)", not UNREAD, UNREAD)
check("a literal LC_VERIFY=no / LC_FP=\"\" only where the same line points LC_URL at this box's own 127.0.0.1 panel",
      not LITERALS, LITERALS)
check("…and no LC_FP / LC_VERIFY is ever unset", not UNSETS, UNSETS)
lc_claim = [(f, a) for _, _, _, _, ls in DRIVERS for f, a in ls]
lc_un = []
for f, pos, text, which, _a, _b in LCS0:
    if not any(ff == f and a in line_of(ORIG[f], pos) for ff, a in lc_claim):
        lc_un.append("%s: %s" % (f, text[:60]))
check("every LC_VERIFY / LC_FP assignment that carries a node's trust is one a driver claims", not lc_un, lc_un)
check("…the census is not empty (%d calls, %d assignments — the floor is 11 and 14)" % (len(CALLS0), len(LCS0)),
      len(CALLS0) >= 11 and len(LCS0) >= 14, (len(CALLS0), len(LCS0)))
check("…read from every shell file of the tree (%d), the Docker entrypoints and nix/adopt.sh among them" % len(SCAN),
      {"docker/node-entrypoint.sh", "docker/entrypoint.sh", "nix/adopt.sh"} <= set(SCAN) and set(FILES) <= set(SCAN), SCAN)

# ── the drives ────────────────────────────────────────────────────────────────────────────────────────────────────────
def run(driver, scen, calls, label):
    tok = "tok-%s-%s-%d" % (driver.__name__, scen, int(time.time() * 1000) % 100000)
    d = tempfile.mkdtemp(prefix=scen + "-", dir=T)
    PLAN["i"] = 0
    PLAN["ctxs"] = {"all-C": [CTX_C], "ca-B": [CTX_B], "all-B": [CTX_B],
                    "last-C": [CTX_B] * (len(calls) - 1) + [CTX_C]}[scen]
    script = driver("ca-B" if scen == "ca-B" else "pin", tok, d)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
                       env=dict(os.environ, HOME=d), start_new_session=True)
    got = ["%s %s" % (m, pth) for m, pth, auth, _ in LOG if auth == "Bearer " + tok]
    return got, r

for label, driver, calls, _cs, _ls in DRIVERS:
    print("\n" + label)
    got, r = run(driver, "all-B", calls, label)
    check("all-B: the pinned certificate → every call arrives (%s)" % ", ".join(calls),
          [g.split("?")[0] for g in got] == calls, (got, r.returncode, (r.stdout + r.stderr)[-600:]))
    got, r = run(driver, "all-C", calls, label)
    check("all-C: another certificate → the panel receives NOTHING, no token", got == [], (got, (r.stdout + r.stderr)[-400:]))
    got, r = run(driver, "ca-B", calls, label)
    check("ca-B: CA verification of a self-signed certificate → NOTHING", got == [], (got, (r.stdout + r.stderr)[-400:]))
    if len(calls) > 1:
        got, r = run(driver, "last-C", calls, label)
        check("last-C: the certificate changes before the last call (%s) → it alone is withheld" % calls[-1],
              [g.split("?")[0] for g in got] == calls[:-1], (got, (r.stdout + r.stderr)[-400:]))

# ── [15] a Docker node re-install starts from the trust it LEARNED ─────────────────────────────────────────────────────
print("\n[15] install-docker.sh: a node re-install takes the panel, key and trust the node learned (docker_node_panel)")
_learn = block("install-docker.sh", '  _EFF_URL=""; _LEARNED_MSG=""\n', "\n  fi\n", True)
def learned(given_fp=""):
    d = tempfile.mkdtemp(prefix="learn-", dir=T)
    wr(os.path.join(d, ".env"), "PANEL_URL=https://old.example:8443\nNODE_TOKEN=tok-old\nTLS_VERIFY=no\nTLS_FINGERPRINT=%s\n" % ("a" * 64))
    for k, v in (("panel-url", "https://new.example:2087"), ("panel-token", "tok-new"), ("panel-verify", "no"), ("panel-fp", "b" * 64)):
        wr(os.path.join(d, "data", "node", k), v + "\n")
    script = ('set -euo pipefail\nb(){ printf %%s "$*"; }\n%s%s'
              'PROFILE=node; SWG_CONVERT_DIR=""; INSTALL_DIR="%s"; _GIVEN_PANEL_URL=""; _GIVEN_NODE_TOKEN=""; _GIVEN_TLS_VERIFY=""\n'
              '_GIVEN_TLS_FINGERPRINT="%s"; TLS_FINGERPRINT_SAVED="%s"\n%s'
              'printf "%%s|%%s|%%s|%%s\\n" "$PANEL_URL" "$NODE_TOKEN" "$TLS_VERIFY" "$TLS_FINGERPRINT_SAVED"\n') % (
        fn("lib/common.sh", "docker_node_panel"), fn("install-docker.sh", "_env_val"), d, given_fp, "a" * 64 if not given_fp else "", _learn)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    return r.stdout.strip(), r.stderr
out, err = learned()
check("[15] the learned URL, token, verify and PIN are what the re-install starts from — the pin decided against that panel",
      out == "https://new.example:2087|tok-new|no|" + "b" * 64, (out, err[-300:]))
out, err = learned(given_fp="c" * 64)
check("[15] …a pin given on the command line still wins over the learned one (the carry leaves it alone)",
      out.split("|")[-1] == "", (out, err[-300:]))

srv.shutdown()
print()
if MUTATED:
    print("PERTURBED (%s): %s" % (MUTATED, "RED as expected (%d failing)" % len(FAILS) if FAILS
                                   else "STILL GREEN — the gate does not see the call send without the node's trust"))
    sys.exit(0 if FAILS else 2)
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS))); sys.exit(1)
print("ALL PASS"); sys.exit(0)
