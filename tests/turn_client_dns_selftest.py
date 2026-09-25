#!/usr/bin/env python3
"""Self-test: a WDTT / csqtt server's CLIENT DNS reaches the server, and nothing else moves (docs/DNS-SETTINGS-PLAN.md §3).

  1  node `_turn_dns`: 1–2 IPv4 → "a,b"; anything else reads as NOT SET (it is written into an env file)
  2  WDTT: `-dns` rides SWG_PARAMS FIRST, the operator's params LAST (Go's flag keeps the last value, so a `-dns`
     typed into params still wins) — in the env file AND the docker argv; a build whose -h lists no -dns
     (ildarmaga, an old rollback target) never gets it
  3  csqtt: CSQTT_DNS in csqtt.env, never `--dns` on the command line (clap refuses a repeat → crash loop);
     unset → the env file is byte-identical to before
  4  the UNITS are untouched — a new ExecStart var would read as drift and restart every instance on upgrade
  5  a DNS change IS a params change (rewrite + restart); an unchanged one is not, nor one the build can't take
  6  the report echoes it (T-18: a mirror without it restarts the server) + says when the fork can't take it
  7  panel `turn_client_dns`: validation, and CLEARING a set value stores the fork default, not nothing
  8  every WDTT / csqtt fork in the catalog carries `client_dns`, and the SPA publishers carry `dns`
  9  panel, node and SPA agree on which addresses are usable (three readers, one grammar)
 10  adopting a foreign WDTT carries its `-dns` (three forks hold it only in the flag), `-flag=value` included
 11  the -h probe: yes / no / unknown — cached only when the binary ANSWERED; a timeout or an exec error is unknown,
     backed off, and never read as "no"
 13  the snapshot reports the DNS IN EFFECT (read from the env file), and a binary swap writes safely
 15  P3 — the Force-DNS upstream: parser (node + panel agree), default when unset/unusable, never empty; the
     signature moves with it; an untouched node gets exactly the reply it got before
 14  a server that remembers its own DNS (csqtt DB, wdttplus passwords.json) reports it; the panel keeps it as
     dns_orig at the first set, and clearing restores it — clearing never changes what clients get
 12  env drift: a dns stored by an old node is applied after the update; nothing else moves — not a fork mismatch,
     not an unknown probe; a binary swap re-renders the env before restarting

Run: python3 tests/turn_client_dns_selftest.py         (0 = pass)
     --perturb-order   puts `-dns` AFTER params            → RED 2
     --perturb-probe   the probe says yes to every build   → RED 11
     --perturb-unknown a failed probe is cached as "no"    → RED 11
     --perturb-upsig   the upstream is not in the signature → RED 15
     --perturb-change  drops dns from _wdtt_params_changed → RED 5
     --perturb-clear   clearing stores nothing             → RED 7
"""
import os, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

N_PLANTS = {
    "--perturb-order": ('        return params\n    return ("-dns " + dns + " " + params).strip()\n',
                        '        return params\n    return (params + " -dns " + dns).strip()\n'),
    "--perturb-probe": ('    _WDTT_TAKES_DNS[key] = any(f["name"] == "dns" for f in flags)\n',
                        '    _WDTT_TAKES_DNS[key] = True\n'),
    "--perturb-change": ('            or _wdtt_params_eff(prev, _wdtt_fork(prev or inst)) != _wdtt_params_eff(inst, _wdtt_fork(prev or inst))\n', ''),
    "--perturb-upsig": ('            tuple(upstream))   # an upstream change rewrites the conf NOW, not on the 12th-pass forced rebuild\n',
                        '            ())\n'),
    "--perturb-unknown": ('    if not flags:\n        _WDTT_DNS_RETRY[key] = time.time() + _WDTT_DNS_BACKOFF\n        return None\n',
                          '    if not flags:\n        _WDTT_TAKES_DNS[key] = False\n        return False\n'),
}
P_PLANTS = {
    "--perturb-clear": ('        return ([p for p in dflt.split(",") if p] or None), None\n', '        return None, None\n'),
}
MODE = next((a for a in sys.argv[1:] if a in N_PLANTS or a in P_PLANTS), None)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:200]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def load(path, name, plants):
    src = open(path, encoding="utf-8").read()
    if MODE in plants:
        cut, new = plants[MODE]
        # ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
        assert src.count(cut) == 1, "perturbation anchor for %s missing or not unique — would FALSE-PASS" % MODE
        src = src.replace(cut, new, 1)
    m = types.ModuleType(name)
    m.__dict__.update({"__name__": name, "__file__": path})
    exec(compile(src.split("\nif __name__ ==")[0], os.path.basename(path), "exec"), m.__dict__)
    return m

N = load(NODED, "n", N_PLANTS)
P = load(PANEL, "p", P_PLANTS)
_REAL_TAKES = N._wdtt_takes_dns
N._wdtt_takes_dns = lambda fork: fork != "ildarmaga"   # sections 2–6; the probe itself is section 11

# ── 1 ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("1  _turn_dns")
for v, want in ((["9.9.9.9"], "9.9.9.9"), (["9.9.9.9", "149.112.112.112"], "9.9.9.9,149.112.112.112"),
                ("1.1.1.1, 1.0.0.1", "1.1.1.1,1.0.0.1"), (None, ""), ([], ""),
                (["1.1.1.1", "1.0.0.1", "8.8.8.8"], ""), (["dns.google"], ""), (["300.1.1.1"], ""),
                (["1.1.1.1\nSWG_X=1"], ""), (["https://1.1.1.1/dns-query"], "")):
    check("%r → %r" % (v, want), N._turn_dns({"dns": v}) == want, N._turn_dns({"dns": v}))

# ── 2 ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("2  WDTT: -dns first, params last, never to ildarmaga")
base = {"iface": "wdtt1", "wg_addr": "10.66.66.1/24", "listen": "0.0.0.0:56000", "wg_port": 56001,
        "password": "p", "fork": "amurcanov", "params": "-dns 8.8.8.8 -foo", "dns": ["9.9.9.9"]}
env = N._wdtt_env_text(base)
check("env SWG_PARAMS = -dns <field> then the operator's params",
      "SWG_PARAMS=-dns 9.9.9.9 -dns 8.8.8.8 -foo\n" in env, env)
argv = N._wdtt_argv(base, "/bin/server")
check("argv carries the same tail, field first", argv[-5:] == ["-dns", "9.9.9.9", "-dns", "8.8.8.8", "-foo"], argv[-6:])
check("no field → SWG_PARAMS exactly as before",
      "SWG_PARAMS=-foo\n" in N._wdtt_env_text(dict(base, params="-foo", dns=None)))
ild = dict(base, fork="ildarmaga", params="")
check("a build without -dns (ildarmaga) gets none — Go exits on an unknown flag", "-dns" not in N._wdtt_env_text(ild)
      and "-dns" not in N._wdtt_argv(ild, "/bin/server"), N._wdtt_env_text(ild))

# ── 3 ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("3  csqtt: CSQTT_DNS in the env, never --dns")
cs = {"iface": "csqtt1", "listen": "0.0.0.0:46000", "tun_addr": "10.66.67.1/24", "password": "p", "params": ""}
e0 = N._csqtt_env_text(cs)
e1 = N._csqtt_env_text(dict(cs, dns=["77.88.8.8", "77.88.8.1"]))
check("set → CSQTT_DNS line", "CSQTT_DNS=77.88.8.8,77.88.8.1\n" in e1, e1)
check("set → only that line added", e1 == e0 + "CSQTT_DNS=77.88.8.8,77.88.8.1\n")
check("unset → no CSQTT_DNS at all", "CSQTT_DNS" not in e0)
check("never --dns in the argv", "--dns" not in N._csqtt_argv(dict(cs, dns=["9.9.9.9"]), "/bin/csqtt"))

# ── 4 ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("4  units untouched")
for fk in ("amurcanov", "wdttplus", "ildarmaga", "qwdtt", "xxcipherx"):
    u = N._wdtt_unit_text("wdtt1", "/bin/server", "/opt/swg-wdtt/wdtt1", fk)
    check("wdtt unit (%s) names no dns" % fk, "dns" not in u.lower(), u)
check("csqtt unit names no dns", "dns" not in N._csqtt_unit_text("csqtt1", "/bin/csqtt", "/opt/swg-csqtt/csqtt1").lower())

# ── 5 ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("5  a DNS change restarts, an unchanged one does not")
check("wdtt: set → changed", N._wdtt_params_changed(dict(base, dns=None), base))
check("wdtt: same value, other spelling → unchanged", not N._wdtt_params_changed(base, dict(base, dns="9.9.9.9")))
check("csqtt: set → changed", N._csqtt_params_changed(cs, dict(cs, dns=["9.9.9.9"])))
check("csqtt: none → none unchanged", not N._csqtt_params_changed(cs, dict(cs)))
check("wdtt: a dns the build can't take is no change (no restart for nothing)",
      not N._wdtt_params_changed(dict(ild, dns=None), ild))
check("wdtt: a panel-side fork change alone is no change (no hot fork swap)",
      not N._wdtt_params_changed(dict(ild, dns=["9.9.9.9"]), dict(base, params="", dns=["9.9.9.9"])))

# ── 6 ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("6  the report echoes it")
src = open(NODED, encoding="utf-8").read()
check("WDTT report: dns in effect + dns_unsupported (from the probe)",
      '"dns": _wdtt_applied_dns(iface, inst), "dns_unsupported": _wdtt_takes_dns(_wdtt_fork(inst)) is False,' in src)
check("WDTT await-restore report carries dns too (else it reads as an old node)",
      '"dns": _wdtt_applied_dns(iface, inst),   # a current node always says' in src)
check("csqtt report: dns in effect", '"dns": _csqtt_applied_dns(iface, inst),' in src)

# ── 7 ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("7  panel turn_client_dns")
f = P.turn_client_dns
check("two IPv4 kept", f(["9.9.9.9", "149.112.112.112"], "amurcanov", False) == (["9.9.9.9", "149.112.112.112"], None))
check("comma/space string accepted", f("9.9.9.9 1.1.1.1", "csqtt", False)[0] == ["9.9.9.9", "1.1.1.1"])
check("three refused", f(["1.1.1.1", "1.0.0.1", "8.8.8.8"], "csqtt", False)[1])
check("a repeat counts once", f(["9.9.9.9", "9.9.9.9"], "csqtt", False) == (["9.9.9.9"], None))
for bad in ("dns.google", "https://1.1.1.1/dns-query", "2606:4700::1111", "127.0.0.1", "0.0.0.0", "1.1.1",
            "224.0.0.1", "255.255.255.255", "240.0.0.1", "169.254.1.1", "01.1.1.1"):
    check("refused: %s" % bad, f([bad], "amurcanov", False)[1], f([bad], "amurcanov", False))
check("empty, never set → stays unset", f([], "csqtt", False) == (None, None))
check("empty after a value → the fork default (csqtt keeps its last value on no flag)",
      f([], "csqtt", True) == (["77.88.8.8", "77.88.8.1"], None), f([], "csqtt", True))
check("empty after a value → the fork default (wdttplus)", f("", "wdttplus", True) == (["1.1.1.1"], None))

# ── 8 ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("8  catalog + publishers")
for sid, e in P.TURN_SERVERS.items():
    if e.get("kind") in ("wdtt", "csqtt"):
        check("%s has client_dns" % sid, bool(N._turn_dns({"dns": e.get("client_dns")})), e.get("client_dns"))
psrc = open(PANEL, encoding="utf-8").read()
check("wdtt_cfg publishes dns + dns_orig", '"raw_port", "raw_iface", "raw_addr", "exit_id", "reach", "dns", "dns_orig") if k in ov}' in psrc)
check("csqtt_cfg publishes dns + dns_orig", '"title", "params", "exit_id", "reach", "dns", "dns_orig") if k in ov}' in psrc)

# ── 9 ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("9  panel / node / SPA agree")
import json, re, subprocess
VEC = ["1.1.1.1", "9.9.9.9", "10.0.0.53", "192.168.1.10", "77.88.8.8", "0.0.0.0", "0.1.2.3", "127.0.0.1",
       "169.254.1.1", "224.0.0.1", "239.1.1.1", "240.0.0.1", "255.255.255.255", "256.1.1.1", "01.1.1.1",
       "1.1.1", "1.1.1.1.1", "dns.google", "::1", ""]
tsrc = open(os.path.join(ROOT, "js", "turn.js"), encoding="utf-8").read()
m = re.search(r"^const _dnsUsable = .*?;\n", tsrc, re.S | re.M)
check("SPA twin found", bool(m))
if m:
    js = m.group(0) + "console.log(JSON.stringify(%s.map(_dnsUsable)))" % json.dumps(VEC)
    spa = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True).stdout)
    for v, js_ok in zip(VEC, spa):
        pan, nod = P.turn_dns_usable(v), N._turn_dns_usable(v)
        check("%-16r panel=%s node=%s spa=%s" % (v, pan, nod, js_ok), pan == nod == js_ok)

# ── 10 ────────────────────────────────────────────────────────────────────────────────────────────────────
print("10 adoption carries -dns")
fl = N._wdtt_flags_from_argv(["/usr/bin/server", "-listen", "0.0.0.0:56000", "-dns", "9.9.9.9,149.112.112.112"])
check("argv parse reads -dns", fl.get("dns") == "9.9.9.9,149.112.112.112", fl)
fl = N._wdtt_flags_from_argv(["/usr/bin/server", "-dns=1.1.1.1", "-listen", "0.0.0.0:56000"])
check("argv parse reads -dns=value", fl.get("dns") == "1.1.1.1" and fl.get("listen") == "0.0.0.0:56000", fl)
check("candidate reports it", '"dns": f.get("dns") or "",' in src)
check("panel adopt seeds the first two usable", 'inst["dns"] = list(dict.fromkeys(_fd))[:2]' in psrc)
check("panel splits on any whitespace, like the SPA", P.turn_client_dns("1.1.1.1\n8.8.8.8\t", "amurcanov", False)[0] == ["1.1.1.1", "8.8.8.8"])

# ── 11 ────────────────────────────────────────────────────────────────────────────────────────────────────
print("11 the -h probe")
import tempfile, stat
TMP = tempfile.mkdtemp()
def fake(name, text, rc=2):
    path = os.path.join(TMP, name)
    with open(path, "w") as fh:
        fh.write("#!/bin/sh\ncat >&2 <<'EOF'\n%s\nEOF\nexit %d\n" % (text, rc))
    os.chmod(path, 0o755)
    return path
WITH = "Usage of server:\n  -dns string\n    \tDNS для клиента (default \"1.1.1.1\")\n  -listen string\n    \tlisten"
WITHOUT = "Usage of server:\n  -admin-addr string\n    \tadmin\n  -listen string\n    \tlisten"
bins = {"amurcanov": fake("a", WITH), "ildarmaga": fake("i", WITHOUT), "gone": os.path.join(TMP, "missing"),
        "mute": fake("m", "", 0), "boom": fake("b", "exec format error", 126)}
FORKS = dict(N.WDTT_FORK_OWNER, **{k: "t/t" for k in bins})
N.WDTT_FORK_OWNER = FORKS                                 # the probe sanitises the fork id against this
N._wdtt_takes_dns = _REAL_TAKES
N._wdtt_bin_shared = lambda fork: bins[fork]
N._wdtt_installed_ver = lambda fork: "v1"
N._WDTT_TAKES_DNS.clear(); N._WDTT_DNS_RETRY.clear()
check("a build listing -dns takes it", N._wdtt_takes_dns("amurcanov") is True)
check("a build without it does not (ildarmaga)", N._wdtt_takes_dns("ildarmaga") is False)
check("no binary → unknown, not cached", N._wdtt_takes_dns("gone") is None and ("gone", "v1") not in N._WDTT_TAKES_DNS)
check("a probe that printed nothing → unknown, not cached", N._wdtt_takes_dns("mute") is None and ("mute", "v1") not in N._WDTT_TAKES_DNS)
check("an exec error → unknown, not cached", N._wdtt_takes_dns("boom") is None and ("boom", "v1") not in N._WDTT_TAKES_DNS)
_orig_run = N.run
N.run = lambda *a, **k: N.subprocess.CompletedProcess(a[0], 124, "", "timeout")
N._WDTT_DNS_RETRY.clear()
check("a timeout ('timeout' text) → unknown, never 'no'", N._wdtt_takes_dns("ildarmaga") is False   # cached answer stands
      and N._wdtt_takes_dns("mute") is None and ("mute", "v1") not in N._WDTT_TAKES_DNS)
calls = []
N.run = lambda *a, **k: (calls.append(1), N.subprocess.CompletedProcess(a[0], 124, "", "timeout"))[1]
N._wdtt_takes_dns("mute")
check("an unknown is backed off, not re-asked every pass", calls == [], calls)
N.run = _orig_run
check("cached per fork+version", N._WDTT_TAKES_DNS.get(("amurcanov", "v1")) is True)
N._wdtt_installed_ver = lambda fork: "v2"
bins["amurcanov"] = fake("a2", WITHOUT)
check("a new version is asked again", N._wdtt_takes_dns("amurcanov") is False)
N.WDTT_FORK_OWNER = {k: v for k, v in FORKS.items() if k not in bins or k in ("amurcanov", "ildarmaga")}

# ── 12 ────────────────────────────────────────────────────────────────────────────────────────────────────
print("12 env drift")
N._wdtt_takes_dns = lambda fork: fork != "ildarmaga"
N._wdtt_dir = lambda iface: os.path.join(TMP, "w-" + iface)
N._csqtt_dir = lambda iface: os.path.join(TMP, "c-" + iface)
for d in ("w-wdtt1", "c-csqtt1"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
wi = dict(base, params="-foo", dns=None)
with open(os.path.join(TMP, "w-wdtt1", "wdtt.env"), "w") as fh: fh.write(N._wdtt_env_text(wi))
wd = dict(wi, dns=["9.9.9.9"])
check("wdtt: env as rendered → no drift", not N._wdtt_env_drifted("wdtt1", wi, wi))
check("wdtt: a dns the old node stored but never rendered → drift", N._wdtt_env_drifted("wdtt1", wd, wd))
check("wdtt: ildarmaga's dns (build can't take it) → no drift",
      not N._wdtt_env_drifted("wdtt1", dict(wd, fork="ildarmaga"), dict(wd, fork="ildarmaga")))
check("wdtt: fork mismatch → no drift (never a hot fork swap)", not N._wdtt_env_drifted("wdtt1", wd, dict(wd, fork="ildarmaga")))
check("wdtt: no previous record → no drift", not N._wdtt_env_drifted("wdtt1", wd, {}))
check("wdtt: no env file (not installed) → no drift", not N._wdtt_env_drifted("nope", wd, wd))
_t = N._wdtt_takes_dns; N._wdtt_takes_dns = lambda fork: None
check("wdtt: probe unknown → no drift (never restart on a guess)", not N._wdtt_env_drifted("wdtt1", wd, wd))
N._wdtt_takes_dns = _t
ci = dict(cs)
with open(os.path.join(TMP, "c-csqtt1", "csqtt.env"), "w") as fh: fh.write(N._csqtt_env_text(dict(ci, iface="csqtt1")))
check("csqtt: env as rendered → no drift", not N._csqtt_env_drifted("csqtt1", ci))
check("csqtt: stored but not rendered → drift", N._csqtt_env_drifted("csqtt1", dict(ci, dns=["9.9.9.9"])))
check("reconcile consults both (running instances only)",
      'or (not inst.get("stopped") and _wdtt_env_drifted(iface, inst, prev))' in src
      and 'or (not inst.get("stopped") and _csqtt_env_drifted(iface, inst))' in src)

# ── 13 ────────────────────────────────────────────────────────────────────────────────────────────────────
print("13 dns in effect + binary swap")
with open(os.path.join(TMP, "w-wdtt1", "wdtt.env"), "w") as fh: fh.write(N._wdtt_env_text(dict(wi, dns=["9.9.9.9"])))
check("applied: -dns at the front of SWG_PARAMS", N._wdtt_applied_dns("wdtt1", wi) == "9.9.9.9")
with open(os.path.join(TMP, "w-wdtt1", "wdtt.env"), "w") as fh: fh.write(N._wdtt_env_text(dict(wi, dns=None)))
check("applied: stored but not rendered → '' (the sheet shows it pending)", N._wdtt_applied_dns("wdtt1", dict(wi, dns=["9.9.9.9"])) == "")
check("applied: the operator's own -dns later in params is not ours", N._wdtt_applied_dns("wdtt1", dict(wi, params="-dns 8.8.8.8")) == "")
check("applied: no env file → the record", N._wdtt_applied_dns("nope", dict(wi, dns=["9.9.9.9"])) == "9.9.9.9")
with open(os.path.join(TMP, "c-csqtt1", "csqtt.env"), "w") as fh: fh.write(N._csqtt_env_text(dict(ci, iface="csqtt1")))
check("csqtt applied: no line → ''", N._csqtt_applied_dns("csqtt1", dict(ci, dns=["9.9.9.9"])) == "")
ub = src[src.index("def _wdtt_update_binary"):src.index("def _wdtt_verify")]
check("swap: renders before opening (never truncates first)",
      "text = _wdtt_env_text(it)" in ub and ub.index("text = _wdtt_env_text(it)") < ub.index('open(envp + ".tmp", "w")')
      and "os.replace(envp + \".tmp\", envp)" in ub)
check("swap: forced probe, and no answer leaves the file as it was", "if _wdtt_takes_dns(fork, force=True) is not None:" in ub)
check("swap: chmod before the probe", ub.index('host_sh("chmod 755 "') < ub.index("_wdtt_takes_dns(fork, force=True)"))
check("swap: a stopped instance is not restarted (bare metal, like docker)",
      'if (insts.get(i) or {}).get("stopped"):\n            continue' in ub)

# ── 14 ────────────────────────────────────────────────────────────────────────────────────────────────────
print("14 the server's own DNS")
import sqlite3, time as _time
cd = os.path.join(TMP, "own-c"); os.makedirs(cd, exist_ok=True)
con = sqlite3.connect(os.path.join(cd, "csqtt.db")); con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
con.execute("INSERT INTO meta VALUES ('dns', '1.1.1.1')"); con.commit(); con.close()
check("csqtt: reads meta.dns", N._turn_own_dns(cd) == "1.1.1.1", N._turn_own_dns(cd))
con = sqlite3.connect(os.path.join(cd, "csqtt.db")); con.execute("UPDATE meta SET value='9.9.9.9' WHERE key='dns'"); con.commit(); con.close()
os.utime(os.path.join(cd, "csqtt.db"), (_time.time() + 5, _time.time() + 5))
check("csqtt: re-read when the store changed", N._turn_own_dns(cd) == "9.9.9.9", N._turn_own_dns(cd))
wd2 = os.path.join(TMP, "own-w"); os.makedirs(wd2, exist_ok=True)
with open(os.path.join(wd2, "passwords.json"), "w") as fh: json.dump({"dns": "1.1.1.1,1.0.0.1", "passwords": {}}, fh)
check("wdttplus: reads passwords.json dns", N._turn_own_dns(wd2) == "1.1.1.1,1.0.0.1")
wd3 = os.path.join(TMP, "own-a"); os.makedirs(wd3, exist_ok=True)
with open(os.path.join(wd3, "passwords.json"), "w") as fh: json.dump({"passwords": {}}, fh)
check("a store without dns (amurcanov) → None", N._turn_own_dns(wd3) is None)
check("no store → None", N._turn_own_dns(os.path.join(TMP, "nothing")) is None)
check("reports carry dns_server (wdttplus + csqtt)",
      '**({"dns_server": _turn_own_dns(_wdtt_dir(iface))} if _wdtt_fork(inst) == "wdttplus" else {}),' in src
      and '"dns_server": _turn_own_dns(_csqtt_dir(iface)),' in src)
inst = {}
check("first set keeps the server's own as dns_orig",
      P.apply_turn_client_dns(inst, {"dns": ["9.9.9.9"]}, "csqtt", {"dns_server": "1.1.1.1"}) is None
      and inst == {"dns": ["9.9.9.9"], "dns_orig": ["1.1.1.1"]}, inst)
P.apply_turn_client_dns(inst, {"dns": ["8.8.8.8"]}, "csqtt", {"dns_server": "9.9.9.9"})
check("a later set does not overwrite dns_orig", inst.get("dns_orig") == ["1.1.1.1"], inst)
P.apply_turn_client_dns(inst, {"dns": []}, "csqtt", {"dns_server": "8.8.8.8"})
check("clearing restores dns_orig, not the catalog default", inst.get("dns") == ["1.1.1.1"], inst)
inst = {}
P.apply_turn_client_dns(inst, {"dns": ["9.9.9.9"]}, "qwdtt", {"dns": ""})
P.apply_turn_client_dns(inst, {"dns": []}, "qwdtt", {})
check("a flag-only fork (no dns_server) clears to the catalog default", inst == {"dns": ["8.8.8.8"]}, inst)
check("a body without dns touches nothing", P.apply_turn_client_dns(inst, {"title": "x"}, "qwdtt", {}) is None and inst == {"dns": ["8.8.8.8"]})

# ── 15 ────────────────────────────────────────────────────────────────────────────────────────────────────
print("15 Force-DNS upstream (P3)")
D = N.SMART_DNS_UPSTREAM_DEFAULT
check("default is what dnsmasq always had", D == ("1.1.1.1", "8.8.8.8"))
check("absent → default", N._dns_upstream(None) == D and N._dns_upstream([]) == D)
check("nothing usable → default, never empty", N._dns_upstream(["0.0.0.0", "224.0.0.1", "127.0.0.1#5354", "x"]) == D)
check("v4, v6, #port", N._dns_upstream(["9.9.9.9", "2620:fe::fe", "127.0.0.1#5335"]) == ("9.9.9.9", "2620:fe::fe", "127.0.0.1#5335"))
check("a local resolver on loopback (not our port) is allowed", N._dns_upstream(["127.0.0.1#5335"]) == ("127.0.0.1#5335",))
check("capped at four", len(N._dns_upstream(["1.1.1.%d" % i for i in range(1, 8)])) == 4)
VEC_UP = ["9.9.9.9", "2620:fe::fe", "127.0.0.1#5335", "192.168.1.10", "127.0.0.1#5354", "0.0.0.0", "224.0.0.1",
          "1.1.1.1#0", "1.1.1.1#70000", "dns.google", "https://1.1.1.1/dns-query", "::1#53"]
for v in VEC_UP:
    pl, pe = P.node_dns_upstream([v])
    nd = N._dns_upstream([v])
    check("panel/node agree on %r (panel %s, node %s)" % (v, "ok" if not pe else "refuses", "keeps" if nd != D else "default"),
          (not pe and pl and tuple(pl) == nd) or (pe and nd == D))
check("panel: empty clears to the default", P.node_dns_upstream("") == ([], None) and P.node_dns_upstream([]) == ([], None))
check("panel: five refused", bool(P.node_dns_upstream(["1.1.1.%d" % i for i in range(1, 6)])[1]))
e, d, f = [{"subnet": "10.8.0.0/24"}], {"c": ["x.com"]}, {}
check("signature moves with the upstream", N._dom_signature(e, d, {}, f, ("9.9.9.9",)) != N._dom_signature(e, d, {}, f))
check("signature: the default equals leaving it out", N._dom_signature(e, d, {}, f, D) == N._dom_signature(e, d, {}, f))
check("dnsmasq renders server= from the upstream",
      'conf += ["server=" + u for u in (upstream or SMART_DNS_UPSTREAM_DEFAULT)]' in src and "server=1.1.1.1" not in src)
check("reconcile threads it through", "_dns_up = _dns_upstream((smart or {}).get(\"dns_upstream\"))" in src
      and "dom_sig = _dom_signature(_dns_e, domains, _zones, _fetched, _dns_up)" in src and "upstream=_dns_up)" in src)
check("panel pushes it only when set (untouched node: same reply)",
      '**({"dns_upstream": node["dns_upstream"]} if node.get("dns_upstream") else {}),' in psrc)
check("panel publishes it", '"dns_upstream": c.get("dns_upstream") or [],' in psrc)
check("node reports the upstream IN EFFECT while dnsmasq runs (not what was saved)",
      '_SMART_MODE["dns_upstream"] = list(upstream or SMART_DNS_UPSTREAM_DEFAULT)' in src
      and 'base["dns_upstream"] = _SMART_MODE["dns_upstream"]' in src)
ssrc = open(os.path.join(ROOT, "js", "screen-settings.js"), encoding="utf-8").read()
check("SPA: draft field, save body, section dirty-tracking",
      'dns_upstream: (n.dns_upstream || []).join(", ")' in ssrc and 'dns_upstream: String(e.dns_upstream || "").split(' in ssrc
      and 'routing: ["routing_mode", "ip_learning", "dns_upstream", "catalog_cats"]' in ssrc)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("PASS" + (" — but %s was planted and should have gone RED" % MODE if MODE else ""))
sys.exit(2 if MODE else 0)
