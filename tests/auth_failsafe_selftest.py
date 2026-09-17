#!/usr/bin/env python3
"""Self-test: "the password file is unreadable" must never mean "this panel has no password".

Found in the field 2026-09-16 on a customer's panel, published to the internet. `/etc/swg-panel/auth` was
root:root 0600 while the panel runs as swgpanel, so `load_auth()` hit `except OSError: pass` and returned
None — and None is the DOCUMENTED "no login configured" value (a blank SWG_PANEL_AUTH is a real mode; the
docker entrypoint deliberately unsets it). Every request was therefore allowed: `GET /api/state` with no
cookie answered 200 with the whole roster — names, tags, notes, VK links.

Three things were wrong and each is independently gated here:
  • load_auth() could not tell "unset" from "unusable"                       → [1]
  • the request gate opened on BOTH                                           → [2]
  • the login endpoint answered `ok: true`, so the SPA "logged in" and looped → [3]
…plus the two repairs that make it visible and self-healing:
  • the startup banner carrying the warning was the one print() without flush=True, and under systemd
    stdout is a block-buffered pipe — the warning was confirmed ABSENT from the live box's journal  → [4]
  • update.sh's ensure_cert_perms heals exactly this class for tls/key.pem but never listed the auth
    file, so an update would not have repaired the box it was running on                            → [5]

⚠️ WHAT MUST STILL WORK. Failing closed is only correct if it closes the right things. The GET dispatcher
serves SPA assets, /api/node/*, /healthz, /metrics and /api/v1/* BEFORE `_require_auth`, so the login page
still loads, nodes keep syncing and the datapath is untouched — [6] holds that ordering in place, because a
future reshuffle of that function is what would silently turn this fix into an outage.

Run: python3 tests/auth_failsafe_selftest.py       (0 = pass)
     --perturb         restores `return True` in _authed_user (the hole) — expects RED in [2]
     --perturb-unset   makes an UNSET SWG_PANEL_AUTH read as unusable — expects RED in [1]/[2], proving the
                       documented no-login dev mode was not closed by accident
"""
import io, os, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

PLANTS = {
    "--perturb": ("return None if AUTH_UNUSABLE else True", "return True"),
    "--perturb-unset": ('AUTH_UNUSABLE = ""                       # the documented no-login mode: nothing was named',
                        'AUTH_UNUSABLE = "unset"'),
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:220]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(PANEL, encoding="utf-8").read()
if MODE:
    cut, new = PLANTS[MODE]
    # ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind and teaches the
    # reader that this gate is watching something it is not.
    assert src.count(cut) == 1, "perturbation anchor for %s missing or not unique — this run would FALSE-PASS" % MODE
    src = src.replace(cut, new, 1)

m = types.ModuleType("p")
m.__dict__.update({"__name__": "p", "__file__": PANEL})
exec(compile(src.split("\nif __name__ ==")[0], "swg-panel-server", "exec"), m.__dict__)

TMP = tempfile.mkdtemp(prefix="authfailsafe-")
GOOD = os.path.join(TMP, "auth-good")
open(GOOD, "w").write("admin:pbkdf2_sha256$1$abc$def\n")
NOCOLON = os.path.join(TMP, "auth-nocolon")
open(NOCOLON, "w").write("garbage-with-no-separator\n")
EMPTY = os.path.join(TMP, "auth-empty")
open(EMPTY, "w").write("")
GONE = os.path.join(TMP, "auth-does-not-exist")

def load_with(path):
    m.AUTH_FILE = path
    creds = m.load_auth()
    return creds, m.AUTH_UNUSABLE

# ── [1] load_auth tells the three states apart ────────────────────────────────────────────────────
print("[1] load_auth distinguishes unset / usable / unusable")
creds, why = load_with("")
check("[1] UNSET is the documented no-login mode: no creds, and nothing is wrong",
      creds is None and why == "", (creds, why))
creds, why = load_with(GOOD)
check("[1] a usable file returns the credential and clears the reason",
      creds == ("admin", "pbkdf2_sha256$1$abc$def") and why == "", (creds, why))
for label, path in (("missing", GONE), ("no 'user:hash' line", NOCOLON), ("empty", EMPTY)):
    creds, why = load_with(path)
    check("[1] a NAMED file that is %s yields no creds AND a reason" % label,
          creds is None and bool(why), (creds, why))

# ── [2] the gate: open only when nothing was configured ───────────────────────────────────────────
print("\n[2] the request gate refuses when a file was named and is unusable")
class Req:
    """The smallest thing _authed_user/_login touch. Both return before reading anything else in the
    no-credential branch, which is the only branch this gate is about."""
    def __init__(self, body=b"{}"):
        self._buf = body
        self.rfile = io.BytesIO(body)
        self.headers = {}
        self.out = None
    def _body_len(self): return len(self._buf)
    def _send(self, code, obj): self.out = (code, obj)
    def _cookie(self, _n): return ""

# The fake carries the REAL methods, so this drives the shipped implementations through a fake transport
# rather than restating their logic here. It also matters mechanically: _require_auth() calls
# self._authed_user(), so a fake without it would raise AttributeError and prove nothing.
Req._authed_user = m.Handler._authed_user
Req._require_auth = m.Handler._require_auth
Req._login = m.Handler._login

m.Handler.deps = {"auth": None, "session_secret": b"x"}
m.AUTH_UNUSABLE = ""
check("[2] nothing configured → the panel stays open (the documented dev/docker mode)",
      Req()._authed_user() is True, Req()._authed_user())
m.AUTH_UNUSABLE = "Permission denied"
check("[2] configured but unusable → UNAUTHENTICATED, not 'no auth'",
      Req()._authed_user() is None, Req()._authed_user())
check("[2] …so _require_auth refuses the request",
      Req()._require_auth() is False, "the gate let it through")
# The same line closes /metrics and /api/v1/* — _ext_authed ends in `self._authed_user() is not None`.
check("[2] …and the external API is closed by the SAME line, not a second copy of the rule",
      "self._authed_user() is not None" in src, "the _ext_authed fall-through is gone — /metrics may be open")

# ── [3] the login endpoint states the problem instead of lying ────────────────────────────────────
print("\n[3] the login endpoint answers precisely in each state")
m.AUTH_UNUSABLE = ""
r = Req(); r._login()
check("[3] no auth configured → the existing 200 {auth:false} answer is unchanged",
      r.out and r.out[0] == 200 and r.out[1].get("data", {}).get("auth") is False, r.out)
m.AUTH_UNUSABLE = "Permission denied"
m.AUTH_FILE = "/etc/swg-panel/auth"
r = Req(); r._login()
code, obj = r.out if r.out else (None, {})
check("[3] unusable → 503 (not 401: no credential can ever work here)", code == 503, r.out)
check("[3] …with a machine-readable code the SPA can branch on", obj.get("code") == "auth_unusable", obj)
check("[3] …and NOT ok:true, which made the SPA 'log in' and reload into a 401 for ever",
      obj.get("ok") is False, obj)
msg = str(obj.get("error") or "")
check("[3] …the sentence names the file, the process user and the fix",
      "/etc/swg-panel/auth" in msg and "chown" in msg and "systemctl restart" in msg, msg[:200])
# ⚠️ AND THE DELIBERATE ESCAPE. A named-but-empty file reads the same whether it broke or was emptied on
# purpose by someone running an open panel behind an SSH tunnel. The panel cannot tell, so it refuses — but
# an operator who MEANT it must be told how to say so, or this fix simply strands them with no way back.
check("[3] …and how to ask for no login on purpose, for a panel that wants none",
      "SWG_PANEL_AUTH" in msg, msg[:260])

# ── [4] the warning can actually reach the journal ────────────────────────────────────────────────
print("\n[4] the startup warning is flushed")
banner = [l for l in src.splitlines() if "swg-panel-server on {scheme}" in l]
check("[4] the banner line is still where this expects it", len(banner) == 1, banner)
check("[4] …and it flushes — under systemd stdout is a block-buffered pipe",
      bool(banner) and "flush=True" in banner[0], banner[0] if banner else "")
check("[4] an unusable auth file also prints its own dedicated line",
      "LOGIN IS CLOSED" in src, "no dedicated operator line for the unusable state")

# ── [5] an update heals the cause ─────────────────────────────────────────────────────────────────
print("\n[5] update.sh repairs the permissions that caused this")
up = open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read()
loop = [l for l in up.splitlines() if l.strip().startswith("for f in") and "key.pem" in l]
check("[5] ensure_cert_perms' file list is still where this expects it", len(loop) == 1, loop)
check("[5] …and it now includes the auth file",
      bool(loop) and "/etc/swg-panel/auth" in loop[0], loop[0] if loop else "")
check("[5] …reusing the group-read-bit test rather than -r (root can read the very file the service cannot)",
      "swg:*[4567]?" in up, "the group-read test changed shape")

# ── [6] what must STILL work — the dispatch order this fix depends on ─────────────────────────────
print("\n[6] failing closed still leaves the login page, the nodes and the probes reachable")
get = src.split("def do_GET", 1)[1].split("def do_POST", 1)[0]
i_static = get.find("static_rel(path) is not None")
i_node = get.find('path == "/api/node/whoami"')
i_ext = get.find('path == "/healthz" or path == "/metrics"')
i_gate = get.find("if not self._require_auth()")
check("[6] SPA assets are served before the gate, so the login page can load",
      0 <= i_static < i_gate, (i_static, i_gate))
check("[6] node-token paths are served before the gate, so the fleet keeps syncing",
      0 <= i_node < i_gate, (i_node, i_gate))
check("[6] /healthz, /metrics and /api/v1/* keep their own token auth ahead of it",
      0 <= i_ext < i_gate, (i_ext, i_gate))

# ── [7] a panel repaired through the UI reopens without a restart ─────────────────────────────────
print("\n[7] fixing the password from /api/account clears the closed state")
check("[7] the hot-reload re-READS the file, so AUTH_UNUSABLE is recomputed",
      'deps["auth"] = load_auth() or (new_user, new_hash)' in src,
      "assigning the tuple directly would leave the gate shut until a restart")

if MODE:
    if FAILS:
        print("\nperturbed (%s): CAUGHT (%d red)" % (MODE, len(FAILS)))
        sys.exit(0)
    print("\nperturbed (%s): NOTHING FAILED — this gate does not test what it claims" % MODE)
    sys.exit(1)
print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
