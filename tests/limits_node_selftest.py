#!/usr/bin/env python3
"""Self-test — the node's speed limits (docs/LIMITS-PLAN.md §3.1–§3.3, design refresh R1–R5, R16; card limits-l1).

`_ensure_limits` turns the panel's `limits` wire key into `tc` policers on the client tunnel devices, after the sync's try.

  [1] No limit, no `tc`, ever (the bar, R3): no key and no marker → no spawn over several passes and no `limit_err`; a
      marker an earlier process left → ONE blind sweep (`-force`) of pref 4097 on the node's tunnels, the marker removed,
      then no spawn again.
  [2] Wire → batch: own download / upload, `c` as one policer on both hooks, several prefixes on one policer, a pool of one
      (one policer at the limit), a pool of two (cap drop/pipe in front of the pool drop/ok), every pool re-set by
      `actions change`; the marker is written before the first load.
  [3] An unchanged wire is a compare: no spawn, and not parsed again (R4: 64 ms a pass at 2,500 entries when it was).
  [4] A changed rate rebuilds THAT device (dels + adds in one batch) under FRESH indices for its own and cap policers (R16:
      a filter re-added under an index whose policer is still being freed binds it and keeps the old rate); the pool keeps
      its index; another device is not touched.
  [5] A new ifindex (lost clsact) rebuilds without the dels (they would fail on a fresh device).
  [6] A failed batch: reported in `limit_err` and the pass's errors, nothing else done (no one is cut), not tried again
      within LIMITS_RETRY_S, then tried with a blind `-force` delete first.
  [7] Refused before any `tc`: a device that is not a client tunnel (a mesh link, eth0, an exit), a name with a newline,
      a bad prefix, a default route, a rate under 1 or `c` beside `d`, a bad pool id — none reaches a batch.
  [8] An absent device is skipped without a word and loaded when it appears.
  [9] Caps from the snapshot (R5): two members both moving → limit ÷ 2; one quiet (< 1 %) → the full limit; a WDTT member
      by its password's `ip`; a move ≤ 10 % changes nothing, a larger one one `actions change` per member.
  [10] The last limit removed: the dels, the marker gone, then no spawn.
  [11] On a real kernel (only when `sudo -n ip netns` works; SKIP otherwise): the batches load, a changed own rate is in
       force after the rebuild (R16), a pool's new limit is in force on a device that was not rebuilt, a cap moves.

Run: python3 tests/limits_node_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED (exit 0 when caught):
     sweepalways  the start sweep runs without the marker
     stale        a rebuild leaves out the dels (the old filters stay beside the new)
     lostclsact   the ifindex is not part of the device's signature
     failretry    a failed device is retried every pass
     failquiet    a failed batch is not reported
     meshdev      the device check reads _own_tunnel_devs (mesh links included) instead of the client tunnels
     sameidx      a rebuild re-uses the device's old policer indices
     nopoolset    the pool's limit is not re-set by `actions change`
     capquiet     a quiet member counts as active
     nomemo       the wire is parsed again on every pass
"""
import importlib.machinery, importlib.util, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.path.join(ROOT, "swg-noded")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "sweepalways": ("        if os.path.exists(LIMITS_MARK):              # a process before us loaded limits",
                    "        if True:              # a process before us loaded limits"),
    "stale": ('''        dels = _lim_dels(dev) if have and have["ifindex"] == ifx else []''', '''        dels = []'''),
    "lostclsact": ("        sig = (esig.get(dev), ifx)", "        sig = (esig.get(dev), 0)"),
    "failretry": ("        if f and f[0] == sig and now - f[1] < LIMITS_RETRY_S:", "        if False:"),
    "failquiet": ('''            err[dev] = msg
            res["errors"].append("limits %s: %s" % (dev, msg))''', '''            pass'''),
    "meshdev": ('''    cdevs = list(_CLIENT_DEVS.get("list") or [])''', '''    cdevs = sorted(_own_tunnel_devs(node_cfg))'''),
    "sameidx": ('''    def alloc():
        st["next"] += 1
        return st["next"] - 1''', '''    _seq = iter(range(LIMITS_IDX0 + 1000, LIMITS_IDX0 + 100000))
    def alloc():
        return next(_seq)'''),
    "nopoolset": ('''    for pool, dirn in sorted(bound):
        lines.append(''', '''    for pool, dirn in []:
        lines.append('''),
    "nomemo": ('''    if wire != st.get("wire") or cdevs != st.get("cdevs"):''', "    if True:"),
    "capquiet": ("                if lim and bps * 8 / 1e6 >= lim * 0.01:", "                if lim:"),
}


def load(src, name):
    tmp = os.path.join(HERE, ".limits-%s.py" % name)
    open(tmp, "w", encoding="utf-8").write(src)
    try:
        spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, tmp))
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pass
        return mod
    finally:
        os.unlink(tmp)


src = open(NODED, encoding="utf-8").read()
if PLANT:
    cut, new = PLANTS[PLANT]
    assert src.count(cut) == 1, "plant anchor for %s missing or not unique — would FALSE-PASS" % PLANT
    src = src.replace(cut, new, 1)
os.environ["SWG_NO_REEXEC"] = "1"
N = load(src, "noded_limits")

TMP = tempfile.mkdtemp(prefix="swg-limits-")
N.LIMITS_MARK = os.path.join(TMP, "limits")
CALLS = []                                   # (argv, stdin lines)
FAILDEV = set()                              # a batch naming one of these fails
IFX = {}                                     # device → ifindex (absent = not there)
NOW = [1000.0]


class _Clock:
    def __getattr__(self, n):
        return getattr(time, n)

    def time(self):
        return NOW[0]


def fake_run(args, input_text=None, timeout=20, env=None, read=False):
    lines = (input_text or "").splitlines()
    CALLS.append((list(args), lines))
    bad = any(("dev %s " % d) in ln for d in FAILDEV for ln in lines)
    return subprocess.CompletedProcess(args, 1 if bad else 0, "", "Error: Exclusivity flag on, cannot modify.\n" if bad else "")


N.run = fake_run
N.time = _Clock()
N._lim_ifindex = lambda d: IFX.get(d)
N._own_tunnel_devs = lambda cfg=None: {"awg2", "wg1", "mesh1", "wgx-exit", "wdtt1"}
CLIENT = ["awg2", "wg1", "wdtt1"]
N._CLIENT_DEVS["list"] = list(CLIENT)
IDX0 = N.LIMITS_IDX0


def reset(mark=False):
    N._LIMITS.update(started=False, next=IDX0, dev={}, pidx={}, caps={}, fail={}, err={}, wire=None, cdevs=None, plan=None)
    if os.path.exists(N.LIMITS_MARK):
        os.unlink(N.LIMITS_MARK)
    if mark:
        open(N.LIMITS_MARK, "w").close()
    CALLS.clear()
    FAILDEV.clear()
    IFX.clear()
    IFX.update({"awg2": 7, "wg1": 8, "wdtt1": 9, "mesh1": 10, "eth0": 2, "wgx-exit": 11})


def ens(wire, snap=None):
    res = {"changed": 0, "errors": []}
    N._ensure_limits({}, wire, snap or {}, res)
    return res


def tc_lines():
    return [ln for _a, ls in CALLS for ln in ls]


def idx_of(line):
    return [int(w) for i, w in enumerate(line.split()) if i and line.split()[i - 1] == "index"] or [-1]


def pol(mbit, idx, verdict):
    return N._lim_police(mbit, idx, verdict)


print("[1] no limit, no tc")
reset()
for _ in range(3):
    ens([])
check("no key, no marker: no spawn in three passes", CALLS == [], CALLS)
check("no limit_err", N._LIMITS["err"] == {})
reset(mark=True)
ens([])
check("a marker: one blind sweep", len(CALLS) == 1 and "-force" in CALLS[0][0], CALLS)
swept = sorted({ln.split()[3] for ln in tc_lines()})
check("the sweep covers the node's tunnels, pref 4097 only", swept == ["awg2", "mesh1", "wdtt1", "wg1", "wgx-exit"]
      and all(ln.endswith("pref 4097") and ln.startswith("filter del") for ln in tc_lines()), tc_lines())
check("the marker is removed", not os.path.exists(N.LIMITS_MARK))
CALLS.clear()
ens([]); ens([])
check("then no spawn", CALLS == [], CALLS)

print("[2] wire → batch")
reset()
W = [["awg2", ["10.9.0.2/32"], 20, 5, 0, ""],
     ["awg2", ["10.9.0.3/32", "192.168.50.0/24"], 0, 0, 10, ""],
     ["awg2", ["10.9.0.4/32"], 0, 0, 40, "u:alice"],
     ["wg1", ["10.8.0.5/32"], 0, 0, 40, "u:alice"],
     ["wg1", ["10.8.0.6/32"], 8, 0, 0, "g:fam"]]
r = ens(W)
check("the marker is written", os.path.exists(N.LIMITS_MARK))
check("one strict batch per device", [c[0] for c in CALLS] == [["tc", "-batch", "-"]] * 2, [c[0] for c in CALLS])
def batch_for(dev):
    return next((ls for _a, ls in CALLS if ("qdisc replace dev %s clsact" % dev) in ls), ["", "", "", "", "", "", "", "", ""])


a2, w1 = batch_for("awg2"), batch_for("wg1")
pa = N._LIMITS["pidx"][("u:alice", "c")]
pf = N._LIMITS["pidx"][("g:fam", "d")]
own_d, own_u = idx_of(a2[1])[0], idx_of(a2[2])[0]
c_idx = idx_of(a2[3])[0]
cap_a = idx_of(a2[7])[0]
exp_a2 = ["qdisc replace dev awg2 clsact",
          "filter add dev awg2 egress pref 4097 protocol ip flower dst_ip 10.9.0.2/32 " + pol(20, own_d, "drop/ok"),
          "filter add dev awg2 ingress pref 4097 protocol ip flower src_ip 10.9.0.2/32 " + pol(5, own_u, "drop/ok"),
          "filter add dev awg2 egress pref 4097 protocol ip flower dst_ip 10.9.0.3/32 " + pol(10, c_idx, "drop/ok"),
          "filter add dev awg2 egress pref 4097 protocol ip flower dst_ip 192.168.50.0/24 " + pol(10, c_idx, "drop/ok"),
          "filter add dev awg2 ingress pref 4097 protocol ip flower src_ip 10.9.0.3/32 " + pol(10, c_idx, "drop/ok"),
          "filter add dev awg2 ingress pref 4097 protocol ip flower src_ip 192.168.50.0/24 " + pol(10, c_idx, "drop/ok"),
          "filter add dev awg2 egress pref 4097 protocol ip flower dst_ip 10.9.0.4/32 " + pol(40, cap_a, "drop/pipe") + " " + pol(40, pa, "drop/ok"),
          "filter add dev awg2 ingress pref 4097 protocol ip flower src_ip 10.9.0.4/32 " + pol(40, cap_a, "drop/pipe") + " " + pol(40, pa, "drop/ok"),
          "actions change " + pol(40, pa, "drop/ok")]
check("awg2's batch, exactly", a2 == exp_a2, "\n" + "\n".join(a2))
check("own d and u are two policers, c one on both hooks", len({own_d, own_u, c_idx}) == 3)
check("burst: 100 ms at the rate, 128 KB at least", "burst 250000 " in a2[1] and "burst 131072 " in a2[2])
cap_w = idx_of(w1[1])[0]
exp_w1 = ["qdisc replace dev wg1 clsact",
          "filter add dev wg1 egress pref 4097 protocol ip flower dst_ip 10.8.0.5/32 " + pol(40, cap_w, "drop/pipe") + " " + pol(40, pa, "drop/ok"),
          "filter add dev wg1 ingress pref 4097 protocol ip flower src_ip 10.8.0.5/32 " + pol(40, cap_w, "drop/pipe") + " " + pol(40, pa, "drop/ok"),
          "filter add dev wg1 egress pref 4097 protocol ip flower dst_ip 10.8.0.6/32 " + pol(8, pf, "drop/ok"),
          "actions change " + pol(8, pf, "drop/ok"),
          "actions change " + pol(40, pa, "drop/ok")]
check("wg1's batch: the pool across devices, a pool of one is one policer", w1 == exp_w1, "\n" + "\n".join(w1))
check("no error", r["errors"] == [] and N._LIMITS["err"] == {}, (r, N._LIMITS["err"]))

print("[3] unchanged → no spawn")
CALLS.clear()
ens(W); ens(W)
check("a compare only", CALLS == [], CALLS)
_parses, _orig_plan = [0], N._limits_plan


def _counted(*a):
    _parses[0] += 1
    return _orig_plan(*a)


N._limits_plan = _counted
ens([list(e) for e in W])                    # the same content in a new object, as every reply's json gives
check("an unchanged wire is not parsed again (R4)", _parses[0] == 0, _parses)
N._limits_plan = _orig_plan

print("[4] a changed rate rebuilds that device under fresh indices")
W2 = [list(e) for e in W]
W2[0][2] = 30
CALLS.clear()
ens(W2)
check("one batch, awg2 only", len(CALLS) == 1 and all("dev awg2 " in ln for ln in CALLS[0][1] if " dev " in ln), CALLS)
b = CALLS[0][1]
check("dels first, in the same batch", b[:2] == ["filter del dev awg2 egress pref 4097", "filter del dev awg2 ingress pref 4097"], b[:3])
new_idx = {i for ln in b for i in idx_of(ln)}
check("own and cap policers take fresh indices", not (new_idx & {own_d, own_u, c_idx, cap_a}), sorted(new_idx))
check("the pool keeps its index", pa in new_idx)
check("the new rate is in the batch", any("rate 30000kbit" in ln for ln in b))

print("[5] lost clsact")
IFX["awg2"] = 70
CALLS.clear()
ens(W2)
check("rebuilt without the dels", len(CALLS) == 1 and not any(ln.startswith("filter del") for ln in CALLS[0][1])
      and CALLS[0][1][0] == "qdisc replace dev awg2 clsact", CALLS)

print("[6] a failed batch")
W3 = [list(e) for e in W2]
W3[4][2] = 9
FAILDEV.add("wg1")
CALLS.clear()
r = ens(W3)
check("reported in limit_err and the pass", "wg1" in N._LIMITS["err"] and any("wg1" in e for e in r["errors"]), (N._LIMITS["err"], r))
check("nothing but the batch ran", len(CALLS) == 1)
CALLS.clear()
NOW[0] += 5
ens(W3)
check("not tried again within a minute", CALLS == [] and "wg1" in N._LIMITS["err"], CALLS)
FAILDEV.clear()
NOW[0] += N.LIMITS_RETRY_S
ens(W3)
check("then a blind -force delete, then the load", len(CALLS) == 2 and "-force" in CALLS[0][0]
      and all(ln.startswith("filter del dev wg1") for ln in CALLS[0][1]) and "-force" not in CALLS[1][0], CALLS)
check("the error clears", N._LIMITS["err"] == {}, N._LIMITS["err"])

print("[7] refused before any tc")
reset()
BAD = [["mesh1", ["10.7.0.2/32"], 10, 0, 0, ""], ["eth0", ["10.9.0.2/32"], 10, 0, 0, ""],
       ["wgx-exit", ["10.9.0.2/32"], 10, 0, 0, ""], ["awg2\nqdisc del dev eth0 root", ["10.9.0.2/32"], 10, 0, 0, ""],
       ["awg2", ["10.9.0.2/32\nqdisc del dev eth0 root"], 10, 0, 0, ""], ["awg2", ["0.0.0.0/0"], 10, 0, 0, ""],
       ["awg2", ["10.9.0.9/32"], 0.5, 0, 0, ""], ["awg2", ["10.9.0.9/32"], 5, 0, 5, ""], ["awg2", ["10.9.0.9/32"], 5, 0, 0, "a b"],
       ["awg2", ["fd00::2/128"], 5, 0, 0, ""], ["awg2", ["10.9.0.9/32"], True, 0, 0, ""], "junk"]
ens(BAD)
check("no spawn at all", CALLS == [], tc_lines())
check("each reported", {"mesh1", "eth0", "wgx-exit", "awg2", "?", "awg2\nqdisc del dev eth0 root"} <= set(N._LIMITS["err"]),
      N._LIMITS["err"])
ens(BAD + [W[0]])
check("a good entry beside them loads, and only it",
      len(CALLS) == 1 and not any(("mesh1" in ln or "eth0" in ln or "exit" in ln or "fd00" in ln or "0.0.0.0" in ln)
                                  for ln in CALLS[0][1]), tc_lines())

print("[8] an absent device")
reset()
del IFX["wdtt1"]
ens([["wdtt1", ["10.66.0.2/32"], 10, 0, 0, ""]])
check("skipped without a word", CALLS == [] and N._LIMITS["err"] == {}, (CALLS, N._LIMITS["err"]))
IFX["wdtt1"] = 9
ens([["wdtt1", ["10.66.0.2/32"], 10, 0, 0, ""]])
check("loaded when it appears", len(CALLS) == 1 and "dev wdtt1 " in CALLS[0][1][1], CALLS)

print("[9] caps from the snapshot")
reset()
G = [["awg2", ["10.9.0.4/32"], 40, 0, 0, "g:x"], ["awg2", ["10.9.0.5/32"], 40, 0, 0, "g:x"],
     ["wdtt1", ["10.66.0.7/32"], 40, 0, 0, "g:x"]]
mb = lambda m: m * 1e6 / 8                    # Mbit/s → B/s


def snap(a, b, w):
    return {"interfaces": {"awg2": {"peers": [{"allowed_ips": "10.9.0.4/32", "rx_speed": 0, "tx_speed": mb(a)},
                                              {"allowed_ips": "10.9.0.5/32, 10.20.0.0/24", "rx_speed": 0, "tx_speed": mb(b)}]}},
            "wdtt": [{"iface": "wdtt1", "raw_iface": "", "passwords": {"pw": {"ip": "10.66.0.7", "rx_speed": 0, "tx_speed": mb(w)}}}]}


ens(G, snap(30, 0, 0))
check("one active member: the cap is the limit", N._LIMITS["caps"].get(("g:x", "d")) == (40, 40.0), N._LIMITS["caps"])
check("the load renders that cap", all("rate 40000kbit" in ln for ln in tc_lines() if "drop/pipe" in ln))
CALLS.clear()
ens(G, snap(30, 20, 0))
check("two moving: limit ÷ 2, one actions change per member, one batch",
      N._LIMITS["caps"][("g:x", "d")] == (40, 20.0) and len(CALLS) == 1
      and len(CALLS[0][1]) == 3 and all(ln.startswith("actions change") and "rate 20000kbit" in ln and "drop/pipe" in ln
                                        for ln in CALLS[0][1]), CALLS)
CALLS.clear()
ens(G, snap(30, 20, 0.3))
check("a member under 1 % of the limit is quiet", CALLS == [], CALLS)
ens(G, snap(30, 20, 5))
check("a WDTT member by its password's address: limit ÷ 3", N._LIMITS["caps"][("g:x", "d")][1] == 40 / 3, N._LIMITS["caps"])
CALLS.clear()
N._LIMITS["caps"][("g:x", "d")] = (40, 12.5)
ens(G, snap(30, 20, 5))
check("a move ≤ 10 % changes nothing", CALLS == [], CALLS)

print("[10] the last limit removed")
reset()
ens(W)
CALLS.clear()
ens([])
check("the dels, nothing else", sorted(ln for ln in tc_lines()) == sorted(N._lim_dels("awg2") + N._lim_dels("wg1"))
      and all("-force" not in c[0] for c in CALLS), tc_lines())
check("the marker is gone", not os.path.exists(N.LIMITS_MARK))
CALLS.clear()
ens([]); ens([])
check("then no spawn", CALLS == [], CALLS)


print("[11] a real kernel")
NS = "swglimtest%d" % os.getpid()
ok = subprocess.run(["sudo", "-n", "ip", "netns", "add", NS], capture_output=True).returncode == 0
if not ok:
    print("  SKIP — no `sudo -n ip netns` here")
else:
    try:
        def nsx(args, inp=None):
            return subprocess.run(["sudo", "-n", "ip", "netns", "exec", NS] + args, input=inp, capture_output=True, text=True)
        for d in ("awg2", "wg1"):
            nsx(["ip", "link", "add", d, "type", "dummy"])
            nsx(["ip", "link", "set", d, "up"])
        N.run = lambda args, input_text=None, timeout=20, env=None, read=False: nsx(list(args), input_text)
        N._lim_ifindex = lambda d: (lambda r: int(r.stdout) if r.returncode == 0 and r.stdout.strip().isdigit() else None)(
            nsx(["cat", "/sys/class/net/%s/ifindex" % d]))

        def rate(i):
            r = nsx(["tc", "actions", "get", "action", "police", "index", str(i)])
            for w in r.stdout.split("rate ")[1:2]:
                return w.split()[0]
            return None
        reset()
        IFX.clear()
        r = ens(W)
        check("the batches load", r["errors"] == [] and N._LIMITS["err"] == {}, (r, N._LIMITS["err"]))
        pa = N._LIMITS["pidx"][("u:alice", "c")]
        check("the pool's policer at its limit", rate(pa) == "40Mbit", rate(pa))
        ens(W2)
        flt = nsx(["tc", "filter", "show", "dev", "awg2", "egress"]).stdout
        check("a changed own rate is in force after the rebuild (R16)", "rate 30Mbit" in flt and "rate 20Mbit" not in flt, flt[:600])
        W4 = [list(e) for e in W2]
        W4[2][4] = W4[3][4] = 60
        ens(W4)
        check("a pool's new limit is in force", rate(pa) == "60Mbit", rate(pa))
        ens(W4, {"interfaces": {"awg2": {"peers": [{"allowed_ips": "10.9.0.4/32", "rx_speed": mb(30), "tx_speed": mb(30)}]},
                                "wg1": {"peers": [{"allowed_ips": "10.8.0.5/32", "rx_speed": mb(30), "tx_speed": mb(30)}]}}})
        caps = [i for d in N._LIMITS["dev"].values() for i in d["caps"].get(("u:alice", "c"), ())]
        check("a cap moves to limit ÷ 2 on both members", len(caps) == 2 and all(rate(i) == "30Mbit" for i in caps),
              [rate(i) for i in caps])
        ens([])
        check("removed: no filter of ours left", "4097" not in nsx(["tc", "filter", "show", "dev", "awg2", "egress"]).stdout
              and "4097" not in nsx(["tc", "filter", "show", "dev", "wg1", "ingress"]).stdout)
    finally:
        subprocess.run(["sudo", "-n", "ip", "netns", "del", NS], capture_output=True)

with __import__("contextlib").suppress(OSError):
    for f in os.listdir(TMP):
        os.unlink(os.path.join(TMP, f))
    os.rmdir(TMP)
print("\n%s — %d failure(s)" % ("FAIL" if FAILS else "PASS", len(FAILS)))
if PLANT:
    print("PLANT %s: %s" % (PLANT, "caught (RED)" if FAILS else "NOT CAUGHT"))
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
