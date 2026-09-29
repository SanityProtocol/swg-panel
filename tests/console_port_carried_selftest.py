#!/usr/bin/env python3
"""Self-test — A DOCKER → BARE CONVERT CARRIES THE CONSOLE'S PORT AND ADDRESS BACK (F95).

A bare → Docker convert carries an operator's console drop-in (SWG_PANEL_CONSOLE_PORT / _HOST on swg-panel-server) into
the .env as CONSOLE_PORT / CONSOLE_BIND (carry_dropins_to_env). The convert back wrote only SWG_LATEST_URL into its
drop-in, so the console came back on nothing the operator had set — and the comment above it said every other .env key
had its bare home already (1.8.8 qualification, round 10).

  [1] carry_env_to_dropin (convert.sh), driven: CONSOLE_PORT / CONSOLE_BIND that are not Docker's defaults come back as
      SWG_PANEL_CONSOLE_PORT / _HOST, the names the bare panel reads; Docker's own defaults (8445, 127.0.0.1) are not an
      operator's setting and stay out; a value that is not a plain port / address is named, not carried; a same-named
      key (SWG_LATEST_URL) is carried as before, with its % escaped for systemd
  [2] the Docker → bare panel step passes both console keys, beside SWG_LATEST_URL
  [3] …the mirror still maps them the other way (bare → Docker), so a round trip ends where it began

Run: python3 tests/console_port_carried_selftest.py        (0 = pass)
     --perturb   three plants, each on its own — each must turn its own check red
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PATH = os.environ.get("SWG_CP_CONVERT") or os.path.join(ROOT, "convert.sh")
CV = open(PATH, encoding="utf-8").read()

PLANTS = [
    ("call", " \\\n      'SWG_PANEL_CONSOLE_PORT=CONSOLE_PORT/8445/[0-9]{1,5}' 'SWG_PANEL_CONSOLE_HOST=CONSOLE_BIND/127.0.0.1/[0-9A-Fa-f.:]{2,45}'", "",
     "[2] the Docker → bare panel step passes both console keys"),
    ("default", '    [ -n "$dflt" ] && [ "$v" = "$dflt" ] && continue\n', "",
     "[1] Docker's own defaults stay out"),
    ("check", '    if [ -n "$chk" ] && ! printf \'%s\' "$v" | grep -cxE "$chk" >/dev/null; then\n', '    if false; then\n',
     "[1] a value that is not a plain port is named, not carried"),
]
if "--perturb" in sys.argv:
    bad = 0
    for name, old, new, must in PLANTS:
        if CV.count(old) != 1:
            print("  %-8s STALE ANCHOR (%d) — this plant would plant nothing" % (name, CV.count(old))); bad += 1; continue
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix="-" + name); f.write(CV.replace(old, new)); f.close()
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, SWG_CP_CONVERT=f.name), capture_output=True, text=True, timeout=120)
        os.unlink(f.name)
        red = ("FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-8s %s" % (name, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")))
        bad += not red
    print("%d plants, %d caught" % (len(PLANTS), len(PLANTS) - bad))
    sys.exit(1 if bad else 0)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:700]) if detail and not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)

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

call = re.search(r"  carry_env_to_dropin \"\$envf\" swg-panel-server ((?:[^\n]*\\\n)*[^\n]*)", CV)   # its continuation lines too
assert call, "the Docker → bare panel step's carry_env_to_dropin call is gone — this run would FALSE-PASS"
ARGS = re.sub(r"\s*#.*$", "", call.group(1).replace("\\\n", " "))

print("[1] carry_env_to_dropin, driven")
def carry(env_text):
    t = tempfile.mkdtemp(prefix="cp-"); envf = os.path.join(t, ".env"); open(envf, "w").write(env_text)
    body = fn(CV, "carry_env_to_dropin").replace("/etc/systemd/system/", t + "/")
    script = ('set -euo pipefail\nDOTENV_DROPIN=50-swg-from-docker.conf\nsystemctl(){ :; }; sub(){ echo "SUB $*"; }; warn(){ echo "WARN $*"; }; b(){ printf %%s "$*"; }\n'
              '%s%scarry_env_to_dropin "%s" swg-panel-server %s\n') % (fn(CV, "_dotenv_val"), body, envf, ARGS)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    f = os.path.join(t, "swg-panel-server.service.d", "50-swg-from-docker.conf")
    return r.returncode, r.stdout + r.stderr, (open(f).read() if os.path.exists(f) else "")
rc, out, dropin = carry("CONSOLE_PORT=8447\nCONSOLE_BIND=0.0.0.0\nSWG_LATEST_URL=https://m.example/p%20x\n")
check("[1] CONSOLE_PORT / CONSOLE_BIND that are not Docker's defaults come back as SWG_PANEL_CONSOLE_PORT / _HOST",
      rc == 0 and 'Environment="SWG_PANEL_CONSOLE_PORT=8447"' in dropin and 'Environment="SWG_PANEL_CONSOLE_HOST=0.0.0.0"' in dropin, (rc, out, dropin))
check("[1] …and SWG_LATEST_URL as before, its % escaped for systemd", 'Environment="SWG_LATEST_URL=https://m.example/p%%20x"' in dropin, dropin)
rc, out, dropin = carry("CONSOLE_PORT=8445\nCONSOLE_BIND=127.0.0.1\n")
check("[1] Docker's own defaults stay out", rc == 0 and dropin == "" and "SUB" not in out, (rc, out, dropin))
rc, out, dropin = carry('CONSOLE_PORT="84;47"\nCONSOLE_BIND=127.0.0.1\n')
check("[1] a value that is not a plain port is named, not carried", rc == 0 and "SWG_PANEL_CONSOLE_PORT" not in dropin
      and "WARN the Docker .env's CONSOLE_PORT" in out, (rc, out, dropin))

print("\n[2] the Docker → bare panel step")
check("[2] the Docker → bare panel step passes both console keys", "SWG_PANEL_CONSOLE_PORT=CONSOLE_PORT/8445/" in ARGS
      and "SWG_PANEL_CONSOLE_HOST=CONSOLE_BIND/127.0.0.1/" in ARGS and "SWG_LATEST_URL" in ARGS, ARGS)

print("\n[3] the other way")
check("[3] bare → Docker still maps SWG_PANEL_CONSOLE_PORT → CONSOLE_PORT and _HOST → CONSOLE_BIND",
      '"SWG_PANEL_CONSOLE_PORT": ("CONSOLE_PORT", "G")' in CV and '"SWG_PANEL_CONSOLE_HOST": ("CONSOLE_BIND", "G")' in CV)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS")
