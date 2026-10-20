#!/usr/bin/env python3
"""Self-test — A RE-INSTALL KEEPS THE NODE'S CLIENT DNS.

The node's "dns" (/etc/swg-agent/config.json; the Docker node's .env DNS) is the DNS line the panel puts in every client
config it makes for that node's interfaces, unless a peer or interface overrides it in the panel — it is not the node's
own resolver. install-node.sh wrote `"dns": ["$DNS"]` with DNS defaulted to 1.1.1.1, so a plain re-install (the
unattended `bash bootstrap.sh node`, or update's heal) put 1.1.1.1 over a node set to its own resolver, and every
client config made after it silently changed its DNS (1.8.8 qualification, round 7). install-host.sh wrote 1.1.1.1 for
a master's local node whatever DNS it was given.

  [1] install-node.sh node_dns_json: given on this run (DNS=…, a convert handing over the box's) → that; else the
      node's own, kept whole (a list); else (a fresh install) 1.1.1.1
  [2] …read_existing reads the node's own as a list of non-empty strings, anything else as nothing
  [3] install-node.sh --dry-run over an existing node config with DNS 9.9.9.9 + 8.8.8.8 and no DNS given (a plain
      re-install): the config it writes keeps both — and with DNS=… given, that one
  [4] install-host.sh, a master's local node written fresh: DNS=… when given, else the box's node config's (a node of
      another panel becoming a master), else 1.1.1.1
  [5] install-docker.sh re-install (checked, it was right): the .env's DNS is imported, an explicit DNS=… wins
  [6] (round 8) install-host.sh, a master RE-install that keeps the enrolled node config: a DNS=… given on this run is
      applied to it and said in the "keeping" line; not given → the node's own is untouched; the same one → no change

Run: python3 tests/node_dns_kept_selftest.py      (0 = pass)
     --perturb          install-node.sh's shipped `"dns": ["$DNS"]` → RED on [1] and [3]
     --perturb-host     install-host.sh's shipped `["1.1.1.1"]` → RED on [4]
     --perturb-docker   DNS left out of install-docker.sh's .env import → RED on [5]
     --perturb-master-keep   the master's kept config ignores DNS= again (the shipped behaviour) → RED on [6]
"""
import json, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from _tree_copy import copy_tree  # noqa: E402 — the live tree, minus what other gates remove while it is copied
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


N = open(os.path.join(ROOT, "install-node.sh"), encoding="utf-8").read()
H = open(os.path.join(ROOT, "install-host.sh"), encoding="utf-8").read()
D = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
MODE = next((a for a in sys.argv[1:] if a in ("--perturb", "--perturb-host", "--perturb-docker", "--perturb-master-keep")), None)


def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing or not unique — this run would FALSE-PASS: %r" % a[:70]
    return src.replace(a, b, 1)


if MODE == "--perturb":
    a = N.index("node_dns_json(){"); b = N.index("; fi; }\n", a) + len("; fi; }\n")
    N = N[:a] + "node_dns_json(){ printf '[\"%s\"]\\n' \"${DNS}\"; }\n" + N[b:]
if MODE == "--perturb-host":
    a = H.index('    _dns_json="$(python3 - "${DNS:-}" <<\'PY\''); b = H.index("\nPY\n)\"\n", a) + len("\nPY\n)\"\n")
    H = H[:a] + "    _dns_json='[\"1.1.1.1\"]'\n" + H[b:]
if MODE == "--perturb-master-keep":
    a = H.index('    if [ -n "${DNS:-}" ] && ! $DRYRUN; then\n      _dns_set="$(python3 - "$PREFIX/etc/swg-agent/config.json" "$DNS"')
    b = H.index("\n    fi\n", a) + len("\n    fi\n")
    H = H[:a] + H[b:]
if MODE == "--perturb-docker":
    D = plant(D, "NODE_NET TURN_MANAGE DNS TLS_VERIFY \\\n            TLS_FINGERPRINT ACME_EMAIL CF_TOKEN CF_ORIGIN_TOKEN; do\n    _g=",
              "NODE_NET TURN_MANAGE TLS_VERIFY \\\n            TLS_FINGERPRINT ACME_EMAIL CF_TOKEN CF_ORIGIN_TOKEN; do\n    _g=")

T = tempfile.mkdtemp(prefix="nodedns-")


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


def bash(script, env=None):
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, env=dict(os.environ, **(env or {})))
    return r.returncode, r.stdout.strip(), r.stderr.strip()


print("[1] install-node.sh node_dns_json")
NDJ = fn(N, "node_dns_json")
for label, given, exist, want in (("given (DNS=9.9.9.9)", "9.9.9.9", "", ["9.9.9.9"]),
                                  ("a re-install: the node's own, kept whole", "", '["9.9.9.9", "8.8.8.8"]', ["9.9.9.9", "8.8.8.8"]),
                                  ("given wins over the node's own", "1.0.0.1", '["9.9.9.9"]', ["1.0.0.1"]),
                                  ("a fresh install: 1.1.1.1", "", "", ["1.1.1.1"])):
    rc, out, err = bash('_GIVEN_DNS=%s; EXIST_DNS_JSON=%s; DNS="${_GIVEN_DNS:-1.1.1.1}"\n%snode_dns_json'
                        % (json.dumps(given), json.dumps(exist), NDJ))
    try:
        got = json.loads(out)
    except Exception:
        got = out
    check("[1] %s → %s" % (label, want), got == want, (got, err))

print("\n[2] read_existing reads the node's own DNS")
line = next(l for l in N.splitlines() if l.strip().startswith('EXIST_DNS_JSON="$(python3 -c'))
for label, dns, want in (("a list", ["9.9.9.9", "8.8.8.8"], ["9.9.9.9", "8.8.8.8"]), ("an empty list", [], ""),
                         ("a string", "9.9.9.9", ""), ("a number in it", [9], ""), ("an empty name in it", ["9.9.9.9", " "], ""),
                         ("no dns at all", None, "")):
    cfg = os.path.join(T, "cfg-%d.json" % abs(hash(label)))
    json.dump({"panel": {"url": "https://p:1"}} if dns is None else {"dns": dns}, open(cfg, "w"))
    rc, out, err = bash(line.replace("/etc/swg-agent/config.json", cfg) + '\nprintf "%s" "$EXIST_DNS_JSON"')
    got = json.loads(out) if out else ""
    check("[2] %s → %s" % (label, json.dumps(want)), got == want, (out, err))

print("\n[3] install-node.sh --dry-run over an existing node config (a plain re-install)")
S = os.path.join(T, "src")
copy_tree(ROOT, S, ignore=shutil.ignore_patterns(".git", "dryrun", "node_modules", "*.png", "scratchpad", "docs",
                                                ".campaign", "__pycache__", "forks", "screenshots", ".claude"))
OLDCFG = os.path.join(T, "old-config.json")
json.dump({"interfaces": {}, "endpoint_host": "192.168.77.2", "dns": ["9.9.9.9", "8.8.8.8"],
           "panel": {"url": "https://192.168.77.1:2087", "token": "R20dryDummyToken00000000", "verify": False},
           "node": {"interval": 5, "agent": "/opt/swg-agent/swg-agent", "sudo": False, "update_ref": "dev"}}, open(OLDCFG, "w"))
a = N.index("read_existing(){"); b = N.index("\n}\n", a) + 3
NN = N[:a] + N[a:b].replace("/etc/swg-agent/config.json", OLDCFG) + N[b:]
assert N[a:b].count("/etc/swg-agent/config.json") >= 2, "read_existing does not read the config — this run would FALSE-PASS"
open(os.path.join(S, "install-node.sh"), "w", encoding="utf-8").write(NN)
env = dict(os.environ, PANEL_URL="https://192.168.77.1:2087", NODE_TOKEN="R20dryDummyToken00000000", TLS_VERIFY="no",
           ENDPOINT_IP="192.168.77.2")
env.pop("DNS", None)
for label, extra, want in (("no DNS given: the node's own, both entries", {}, ["9.9.9.9", "8.8.8.8"]),
                           ("DNS=1.0.0.1 given: that one", {"DNS": "1.0.0.1"}, ["1.0.0.1"])):
    shutil.rmtree(os.path.join(S, "dryrun"), ignore_errors=True)
    r = subprocess.run(["bash", "install-node.sh", "--dry-run"], cwd=S, env=dict(env, **extra), stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=300, start_new_session=True)
    cfgp = os.path.join(S, "dryrun", "etc", "swg-agent", "config.json")
    try:
        got = json.load(open(cfgp)).get("dns")
    except Exception as e:
        got = repr(e)
    check("[3] %s" % label, got == want, (got, r.returncode, (r.stdout + r.stderr)[-500:]))

print("\n[4] install-host.sh, a master's local node written fresh")
a = H.index('    _dns_json="$(python3 - "${DNS:-}" <<\'PY\'') if MODE != "--perturb-host" else -1
if a >= 0:
    code = H[H.index("\n", a) + 1:H.index("\nPY\n)\"\n", a)]
    assert "/etc/swg-agent/config.json" in code, "the snippet reads no config — this run would FALSE-PASS"
    def host_dns(given, cfg):
        r = subprocess.run(["python3", "-", given], input=code.replace("/etc/swg-agent/config.json", cfg),
                           capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else ("rc=%d %s" % (r.returncode, r.stderr[-200:]))
else:
    def host_dns(given, cfg):
        m = re.search(r"_dns_json='(\[.*?\])'", H)
        return json.loads(m.group(1)) if m else None
nodecfg = os.path.join(T, "was-a-node.json"); json.dump({"dns": ["9.9.9.9"]}, open(nodecfg, "w"))
check("[4] DNS=1.0.0.1 given → [\"1.0.0.1\"]", host_dns("1.0.0.1", nodecfg) == ["1.0.0.1"], host_dns("1.0.0.1", nodecfg))
check("[4] not given, the box's node config says 9.9.9.9 → kept", host_dns("", nodecfg) == ["9.9.9.9"], host_dns("", nodecfg))
check("[4] not given, no node config → [\"1.1.1.1\"]", host_dns("", os.path.join(T, "none.json")) == ["1.1.1.1"],
      host_dns("", os.path.join(T, "none.json")))
check("[4] …and that is what the local node's config.json is written with",
      '"dns": ${_dns_json},' in H and H.find("_dns_json=") < H.find('"dns": ${_dns_json},'))

print("\n[6] install-host.sh, a master re-install that keeps the enrolled node config")
a = H.index('  if [ "$_keep_agent" = yes ]; then')
k = H.index('    ok "keeping existing /etc/swg-agent/config.json', a)
keep = H[H.index("    # …and a DNS= GIVEN on this run", a) if "    # …and a DNS= GIVEN on this run" in H[a:k] else k:k]
okline = H[k:H.index("\n", k)]
check("[6] the keep branch has a DNS step before its \"keeping\" line", "DNS" in keep and "_dns_set" in okline, keep[:200] or okline)
kcfg = os.path.join(T, "kept.json")
def keep_run(dns, start):
    json.dump({"panel": {"url": "http://127.0.0.1:8088", "token": "t" * 20}, "dns": start, "interfaces": {}}, open(kcfg, "w"))
    rc, out, err = bash('PREFIX=""; DRYRUN=false; DNS=%s\nok(){ echo "OK $*"; }; b(){ printf %%s "$*"; }; col(){ shift; printf %%s "$*"; }; _merged=""\n%s%s\n'
                        % (json.dumps(dns), keep.replace("$PREFIX/etc/swg-agent/config.json", kcfg), okline))
    return json.load(open(kcfg)).get("dns"), out, err
got, out, err = keep_run("9.9.9.9", ["1.1.1.1"])
check("[6] DNS=9.9.9.9 given → the kept config's dns is [\"9.9.9.9\"]", got == ["9.9.9.9"], (got, out, err))
check("[6] …and the \"keeping\" line says the client DNS was set to it", "client DNS set to 9.9.9.9" in out, out)
got, out, err = keep_run("", ["9.9.9.9", "8.8.8.8"])
check("[6] no DNS given → the node's own, both entries, untouched and unmentioned", got == ["9.9.9.9", "8.8.8.8"] and "client DNS" not in out, (got, out))
got, out, err = keep_run("1.1.1.1", ["1.1.1.1"])
check("[6] the same one given → nothing changed, nothing said", got == ["1.1.1.1"] and "client DNS" not in out, (got, out))

print("\n[5] install-docker.sh re-install: the .env's DNS")
a = D.index('if [ -f "$INSTALL_DIR/.env" ]; then\n  EXISTING_DOCKER=yes\n'); b = D.index('  EXIST_TLS="$(_env_val TLS', a)
blk = D[a:b] + "fi\n"
ENV_DIR = os.path.join(T, "docker"); os.makedirs(ENV_DIR)
open(os.path.join(ENV_DIR, ".env"), "w").write("PANEL_URL=https://p:1\nDNS=9.9.9.9   # the node's resolver\n")
for label, given, want in (("nothing given → the .env's", "", "9.9.9.9"), ("DNS=1.0.0.1 given → that one", "1.0.0.1", "1.0.0.1")):
    rc, out, err = bash('INSTALL_DIR=%s; _GIVEN_DNS=%s; DNS="${_GIVEN_DNS:-1.1.1.1}"\n%s%secho "DNS=$DNS"'
                        % (ENV_DIR, json.dumps(given), fn(D, "_env_val"), blk))
    check("[5] %s" % label, ("DNS=%s" % want) in out, (out, err[-300:]))
check("[5] …DNS is in the pre-default snapshot too (an explicit DNS=… is known as given)",
      re.search(r"for _k in [^;]*\bDNS\b[^;]*; do\n  eval \"_GIVEN_\$_k=", D) is not None)

print()
shutil.rmtree(T, ignore_errors=True)
if MODE:
    print("PERTURBED (%s): %s" % (MODE, "RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate is blind"))
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "FAILED: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
