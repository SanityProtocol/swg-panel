#!/usr/bin/env python3
"""Self-test — AN INSTALL NEVER PRINTS A PASSWORD THE OPERATOR GAVE; A GENERATED ONE IS SHOWN ONCE, AS BEFORE.

1.8.8 qualification, round 8 (the security class of F54; 1.8.7 did the same): a fresh bare-metal install run with
BASIC_PASS=… printed that password in its summary — the unattended install's log then held it in plaintext. The Docker
installer printed a -pass / PANEL_PASSWORD= one the same way. Only a password the install GENERATED is shown (once — the
auth file keeps only its pbkdf2 hash); a given one is said to be given. The salvage menu (bootstrap.sh) printed every
leftover node token whole — on unattended runs too — and now shows only enough to tell two apart.

  [1] lib/common.sh summary_host_block: SWG_SUMMARY_PASS → the password once; SWG_SUMMARY_PASS_GIVEN → "the one you gave",
      never the value (which is in the environment of the run, to prove it is not read)
  [2] install-host.sh: BASIC_PASS given → _PASS_GIVEN=yes before anything generates one, and the summary is handed
      SWG_SUMMARY_PASS_GIVEN, not the password; not given → a generated one is handed over; a kept login → neither
  [3] install-docker.sh: -pass / PANEL_PASSWORD= given (_GIVEN_PANEL_PASSWORD) → GIVEN; generated → the password; no new
      login → neither
  [4] bootstrap.sh _salv_block: the token is shown as its first six and last four characters, never whole

Run: python3 tests/given_password_hidden_selftest.py     (0 = pass)
     --perturb          install-host.sh hands a given password to the summary again (the shipped behaviour) → RED on [2]
     --perturb-docker   install-docker.sh does → RED on [3]
     --perturb-token    the salvage menu prints the token whole → RED on [4]
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
C = open(os.path.join(ROOT, "lib", "common.sh"), encoding="utf-8").read()
H = open(os.path.join(ROOT, "install-host.sh"), encoding="utf-8").read()
D = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
B = open(os.path.join(ROOT, "bootstrap.sh"), encoding="utf-8").read()
MODE = next((a for a in sys.argv[1:] if a in ("--perturb", "--perturb-docker", "--perturb-token")), None)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

if MODE == "--perturb":
    H = plant(H, '  if [ "$_PASS_GIVEN" = yes ]; then export SWG_SUMMARY_PASS_GIVEN=1; else export SWG_SUMMARY_PASS="$BASIC_PASS"; fi\n',
              '  export SWG_SUMMARY_PASS="$BASIC_PASS"\n')
if MODE == "--perturb-docker":
    D = plant(D, '  if [ -n "${_GIVEN_PANEL_PASSWORD:-}" ]; then export SWG_SUMMARY_PASS_GIVEN=1; else export SWG_SUMMARY_PASS="$PANEL_PASSWORD"; fi\n',
              '  export SWG_SUMMARY_PASS="$PANEL_PASSWORD"\n')
if MODE == "--perturb-token":
    B = plant(B, '''  echo "           Token:         $([ "${#tok}" -gt 12 ] && printf '%s…%s' "${tok:0:6}" "${tok: -4}" || printf '%s' '(hidden)')"''',
              '''  echo "           Token:         $tok"''')

def fn(src, name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot lift " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

def between(src, a, b):
    assert src.count(a) == 1, "anchor missing — would FALSE-PASS: " + a[:80]
    i = src.index(a); return src[i:src.index(b, i) + len(b)]

def bash(script, env=None):
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, env=dict(os.environ, **(env or {})))
    return r.stdout + r.stderr

SECRET = "Given-Secret-7f3a9"
PRE = 'b(){ printf %s "$*"; }; bb(){ printf %s "$*"; }; C_BLUE=""; RESET=""; summary_sub_block(){ :; }\n'
SUM = PRE + fn(C, "_sum_get") + fn(C, "_sum_note") + fn(C, "summary_host_block")

print("[1] the summary block")
out = bash(SUM + "summary_host_block bare no", {"SWG_SUMMARY_PASS": "Gen-Pass-1234"})
check("[1] a GENERATED password → shown, once", out.count("Gen-Pass-1234") == 1 and "save the password now" in out, out)
out = bash(SUM + "summary_host_block bare no", {"SWG_SUMMARY_PASS_GIVEN": "1", "BASIC_PASS": SECRET, "PANEL_PASSWORD": SECRET})
check("[1] a GIVEN password → never printed (it is in the run's environment), and it says so",
      SECRET not in out and "the one you gave" in out, out)
out = bash(SUM + "summary_host_block bare no", {"BASIC_PASS": SECRET})
check("[1] a kept login → no password line at all", SECRET not in out and "Password" not in out, out)

print("\n[2] install-host.sh")
top = between(H, 'BASIC_PASS="${BASIC_PASS:-}"', "\n_PASS_GIVEN=no; [ -n \"$BASIC_PASS\" ] && _PASS_GIVEN=yes\n")
gen = between(H, '[ "$KEEP_AUTH" != yes ] && [ -z "$BASIC_PASS" ] && BASIC_PASS=', "\n")
hand = between(H, "# ⚠️ …AND A PASSWORD THE OPERATOR GAVE (BASIC_PASS=) IS NEVER PRINTED", "unset SWG_SUMMARY_PASS SWG_SUMMARY_PASS_GIVEN")
check("[2] _PASS_GIVEN is decided before anything generates a password", H.index(top) < H.index(gen), (H.index(top), H.index(gen)))
SHOW = 'print_summary(){ echo "PASS=[${SWG_SUMMARY_PASS:-}] GIVEN=[${SWG_SUMMARY_PASS_GIVEN:-}]"; }\n'
def host(env, keep="no"):
    return bash(SHOW + top + "\nKEEP_AUTH=%s; EXISTING_HOST=no\n" % keep + gen + "\n" + hand + "\n", env)
out = host({"BASIC_PASS": SECRET})
check("[2] BASIC_PASS given → the summary gets GIVEN, not the password", "GIVEN=[1]" in out and SECRET not in out, out)
out = host({})
m = re.search(r"PASS=\[([^\]]*)\] GIVEN=\[\]", out)
check("[2] not given → a generated password is handed over", bool(m) and len(m.group(1)) >= 12, out)
out = host({"BASIC_PASS": SECRET}, keep="yes")
check("[2] a kept login → neither", "PASS=[] GIVEN=[]" in out, out)

print("\n[3] install-docker.sh")
dhand = between(D, "# ⚠️ …but never one the operator GAVE (-pass / PANEL_PASSWORD=)", "unset SWG_SUMMARY_PASS SWG_SUMMARY_PASS_GIVEN")
dhand = dhand.replace(dhand[dhand.index("print_summary"):dhand.index("\n", dhand.index("print_summary"))], "print_summary")
def dock(env):
    return bash(SHOW + dhand + "\n", env)
out = dock({"NEW_LOGIN": "yes", "_GIVEN_PANEL_PASSWORD": SECRET, "PANEL_PASSWORD": SECRET})
check("[3] -pass given → GIVEN, not the password", "GIVEN=[1]" in out and SECRET not in out, out)
out = dock({"NEW_LOGIN": "yes", "PANEL_PASSWORD": "Gen-Docker-99"})
check("[3] generated → the password is handed over", "PASS=[Gen-Docker-99] GIVEN=[]" in out, out)
out = dock({"NEW_LOGIN": "no", "PANEL_PASSWORD": SECRET})
check("[3] no new login → neither", "PASS=[] GIVEN=[]" in out, out)

print("\n[4] the salvage menu")
TOK = "abcdefGHIJKLmnopqrstUVWX"
blk = (PRE + 'panel_req(){ return 1; }\n' + fn(B, "_fmt_epoch") + fn(B, "_salv_created") + fn(B, "_salv_trust") + fn(B, "_salv_block")
       + '_salv_block 1 "%s" "" /nonexistent/config.json\n' % TOK)
out = bash(blk)
check("[4] the token is shown as its first six and last four characters", "abcdef…UVWX" in out and TOK not in out, out)

print()
if MODE:
    print("PERTURBED (%s): %s" % (MODE, "RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate is blind"))
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "FAILED: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
