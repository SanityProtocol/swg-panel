#!/usr/bin/env python3
"""Self-test — a secret asked by an installer never reaches the screen or the install log.

The installers' ask_valid SHOWS its default: in [brackets] on the prompt, and — with no terminal — in the line
"<prompt>: <default>  (no terminal — default taken)" that install-docker.sh prints and the bare installers now print
too (installer_lines_selftest.py [c]). The Cloudflare token prompts (letsencrypt over DNS-01, and cf15) went through
ask_valid with the SAVED token as their default, so an unattended re-install printed the token into its log, and an
interactive one onto the screen. Found while adding that line to install-host.sh (1.8.8 qualification fix round);
install-docker.sh had carried the log leak since its own line was added.

  [1] no installer asks for a secret — a Cloudflare token, a node key, a password — through ask / ask_valid /
      ask_choice: every such prompt is ask_secret (echo off, a saved value offered as [keep current])
  [2] ask_secret with no terminal takes the saved value and prints NOTHING of it; ask_valid, by design, prints its
      default — which is why [1] must hold
  [3] ask_secret still explains a rejected value with the validator's own _why, as ask_valid does

Run: python3 tests/installer_secret_prompts_selftest.py     (0 = pass)
     --perturb   the Cloudflare prompts planted back on ask_valid → RED
"""
import os, re, shlex, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
SRC = {f: open(os.path.join(ROOT, f), encoding="utf-8").read() for f in ("install-host.sh", "install-docker.sh", "install-node.sh")}
C = open(os.path.join(ROOT, "lib/common.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

if PERTURB:
    for f in ("install-host.sh", "install-docker.sh"):
        a = 'ask_secret "Cloudflare API token'
        assert SRC[f].count(a) == 2, "perturbation anchor missing — would FALSE-PASS: " + f
        SRC[f] = SRC[f].replace(a, 'ask_valid "Cloudflare API token')

SECRET = re.compile(r"^(CF_TOKEN|CF_ORIGIN_TOKEN|NODE_TOKEN|[A-Z_]*PASS(WORD)?|[A-Z_]*SECRET[A-Z_]*)$")

def fn(src, name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot extract " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

print("[1] every secret prompt goes through ask_secret")
seen = 0
for f, s in SRC.items():
    for n, line in enumerate(s.splitlines(), 1):
        for m in re.finditer(r"(?<![\w-])(ask|ask_valid|ask_choice|ask_secret)\s+(\"[^\"]*\"\s+(?:\"[^\"]*\"|\S+)\s+[A-Za-z_]+)", line):
            try:
                args = shlex.split(m.group(2))
            except ValueError:
                continue
            if len(args) < 3 or not SECRET.match(args[2]):
                continue
            seen += 1
            check("%s:%d %s → %s" % (f, n, args[2], m.group(1)), m.group(1) == "ask_secret", line.strip()[:160])
check("…and the scan found the prompts it is about (Cloudflare ×2 in two installers, the node key ×2)", seen >= 6, seen)

print("\n[2] with no terminal, a saved secret is taken and not printed")
TOKEN = "cf-sekret-0123456789abcdefghijklmnopqrstuv"
PRE = ('set -euo pipefail\nC_BLUE=""; RESET=""; BOLD=""; _SWG_NL=""\ncol(){ shift; printf %s "$*"; }\nb(){ printf %s "$*"; }\n'
       '_pnl(){ echo; }\nwarn(){ echo "WARN $*"; }\ndie(){ echo "DIE $*"; exit 9; }\n_tty(){ { : </dev/tty; } 2>/dev/null; }\n'
       'v_tok(){ [ "${#1}" -ge 40 ]; }\n')
def run(script):
    r = subprocess.run(["setsid", "-w", "bash", "-c", PRE + script], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return r.stdout + r.stderr
out = run(fn(C, "ask_secret") + 'ask_secret "Cloudflare API token" "%s" CF_TOKEN v_tok "paste a token"\necho "GOT=${#CF_TOKEN}"\n' % TOKEN)
check("ask_secret takes the saved token (GOT=%d)" % len(TOKEN), "GOT=%d" % len(TOKEN) in out, out)
check("…and prints none of it", TOKEN not in out, out)
H = SRC["install-host.sh"]
out = run(fn(H, "_notty") + fn(H, "ask_valid") + 'ask_valid "Cloudflare API token" "%s" CF_TOKEN v_tok "paste a token"\n' % TOKEN)
check("ask_valid, by design, prints its default — so it must never carry a secret", TOKEN in out, out)

print("\n[3] a rejected value is explained by the validator's own _why")
# a terminal is needed to be re-prompted at all: `script` gives the shell a pty, fed a wrong value and then a right one
body = PRE + fn(C, "ask_secret") + ('v_tok_why(){ echo "that is a Global API Key — make a scoped token"; }\n'
                                    'ask_secret "Cloudflare API token" "" CF_TOKEN v_tok "paste a token"\necho "GOT=${#CF_TOKEN}"\n')
r = subprocess.run(["script", "-qec", "bash -c " + shlex.quote(body), "/dev/null"], input="short\n" + TOKEN + "\n",
                   capture_output=True, text=True, timeout=30)
out = r.stdout + r.stderr
check("ask_secret's re-prompt names why (the validator's _why, not only the hint)",
      "a Global API Key — make a scoped token" in out and "GOT=%d" % len(TOKEN) in out, out)
# (whether the pty ECHOES typed input is not testable here: `script` feeds its input before `read -s` turns echo off)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
