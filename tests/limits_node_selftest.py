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
       force after the rebuild (R16), a pool's new limit is in force on a device that was not rebuilt, a cap moves, a
       one-hook device rebuilds, an index at the top of the u32 range loads and the next wraps.
  [12] Review round (limits-l1 F1–F23): the index range stays under tc's u32; only the hooks a device holds are deleted;
       one prefix once per device; a combined pool beside a per-direction one; host bits refused; a trailing newline on a
       pool refused; a `limits` that is not a list changes nothing; a WDTT password on two paths counts once, csqtt by
       its `ip`; a member that moved within LIMITS_HOLD_S stays counted; a cap never under LIMITS_MIN_CAP; a failed cap
       change keeps the caps in force; tc's cause reaches limit_err; a sweep that never ran is tried again; a WDTT device
       left out of the client list for a pass keeps its limits; a node without a limit stats the marker once.
  [14] Review round 2 (F59, F61, F62, F68, F69): the marker names the devices loaded and a restart sweeps them listed or
       not; a sweep that never ran waits a minute; a part-applied cap change is sent again; a `limits` that is not a list
       keeps the other errors; uninstall deletes on the marker's devices only.
  [13] The main loop's wiring (the critical invariant): the wire is None each pass, set only from a valid 200 carrying
       `desired`, the call sits outside the sync's try, and the snapshot carries limit_err.

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
     onehook      a rebuild deletes both hooks whatever the device holds
     idxwrap      the index counter runs past tc's u32
     dupnet       a prefix repeated on one device renders two filters
     mixkind      a pool with a combined and a per-direction member keeps both
     strict       host bits are masked into the subnet
     notlist      a `limits` that is not a list reads as none
     rawtwice     a WDTT password's speed counts on both its paths
     nohold       a member counts only on the pass it moved
     mincap       no floor under a cap
     capfailkeep  a failed cap change is recorded as in force
     errcause     limit_err keeps tc's last line only
     sweepfail    a sweep that never ran is not tried again
     snatdrop     a device left out of the client list for a pass loses its limits
     clientsweep  the start sweep runs over every tunnel (mesh links, exits)
     markstat     the marker is stat'ed on every pass
     wireall      the main loop starts a pass with an empty wire (a panel outage lifts every limit)
     noerr        the snapshot leaves out limit_err
     capunknown   a failed cap change keeps the old caps as known (a part-applied change is never re-sent)
     marknames    the start sweep ignores the devices the marker names
     sweepspin    a sweep that never ran is retried every pass
     errwipe      a `limits` that is not a list wipes the other errors from limit_err
     unwide       uninstall deletes pref 4097 on every device
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
    "sweepalways": ('''    if not st["started"] and (st["mark"] or plan):''', '''    if not st["started"]:'''),
    "stale": ('''        dels = _lim_dels(dev, have["hooks"]) if have and have["ifindex"] == ifx else []''', '''        dels = []'''),
    "lostclsact": ("        sig = (esig.get(dev), ifx)", "        sig = (esig.get(dev), 0)"),
    "failretry": ("        if f and f[0] == sig and now - f[1] < LIMITS_RETRY_S:", "        if False:"),
    "failquiet": ('''            err[dev] = msg
            res["errors"].append("limits %s: %s" % (dev, msg))''', '''            pass'''),
    "meshdev": ('''    cdevs = sorted(set(str(d) for d in (_CLIENT_DEVS.get("list") or ())) | set(st["dev"]))''',
                '''    cdevs = sorted(_own_tunnel_devs(node_cfg))'''),
    "sameidx": ('''st["pidx"], _lim_alloc)''',
                '''st["pidx"], (lambda _s=iter(range(LIMITS_IDX0 + 1000, LIMITS_IDX0 + 100000)): lambda: next(_s))())'''),
    "nopoolset": ('''    for pool, dirn in sorted(bound):
        lines.append(''', '''    for pool, dirn in []:
        lines.append('''),
    "nomemo": ('''    if wire != st.get("wire") or cdevs != st.get("cdevs"):''', "    if True:"),
    "capquiet": ("            t = now if bps * 8 / 1e6 >= lim * 0.01 else seen.get(k)", "            t = now"),
    "onehook": ('''        dels = _lim_dels(dev, have["hooks"]) if''', '''        dels = _lim_dels(dev) if'''),
    "idxwrap": ('''    _LIMITS["next"] = i + 1 if i + 1 < LIMITS_IDX_END else LIMITS_IDX0''', '''    _LIMITS["next"] = i + 1'''),
    "dupnet": ('''        out = [n for n in dict.fromkeys(out) if (dev, n) not in seen]''', '''        out = out'''),
    "mixkind": ('''        if p.get("c"):                                # both would''', '''        if False:                                # both would'''),
    "strict": ('''net = ipaddress.IPv4Network(str(n))''', '''net = ipaddress.IPv4Network(str(n), strict=False)'''),
    "notlist": ('''    if not isinstance(wire, list):                    # a malformed set''', '''    if False:                    # a malformed set'''),
    "rawtwice": ('''                        sp[(dev, a)] = (pe.get("rx_speed") or 0, pe.get("tx_speed") or 0)
                        break''', '''                        sp[(dev, a)] = (pe.get("rx_speed") or 0, pe.get("tx_speed") or 0)'''),
    "nohold": ('''            if t is not None and now - t < LIMITS_HOLD_S:''', '''            if t == now:'''),
    "mincap": ('''max(LIMITS_MIN_CAP, pools[k[0]][k[1]] / max(1, n))''', '''pools[k[0]][k[1]] / max(1, n)'''),
    "capfailkeep": ('''    st["caps"] = {k: (v if k not in old or (ok and k in moved) else (v[0], -1.0) if k in moved else old[k])''',
                    '''    st["caps"] = {k: (v if True else (v[0], -1.0) if k in moved else old[k])'''),
    "capunknown": ('''else (v[0], -1.0) if k in moved else old[k])''', '''else old[k])'''),
    "marknames": ('''        devs = [d for d in sorted(set(cdevs) | st["markdevs"]) if''', '''        devs = [d for d in sorted(set(cdevs)) if'''),
    "sweepspin": ('''        if st["sweepfail"] and now - st["sweepfail"][0] < LIMITS_RETRY_S:''', '''        if False:'''),
    "errwipe": ('''        st["err"] = dict(st["err"], limits="not a list''', '''        st["err"] = dict(limits="not a list'''),
    "unwide": ('''done < /var/lib/swg-noded/limits; true''', '''done < /dev/null; for d in $(ls /sys/class/net); do for h in egress ingress; do tc filter del dev "$d" $h pref 4097 >/dev/null 2>&1; done; done; true'''),
    "errcause": ('''    cause = [x for x in ls if not x.startswith("Command failed")]''', '''    cause = []'''),
    "sweepfail": ('''        if r.returncode in (124, 127):                # not run at all''', '''        if False:                # not run at all'''),
    "snatdrop": ('''(_CLIENT_DEVS.get("list") or ())) | set(st["dev"]))''', '''(_CLIENT_DEVS.get("list") or ())))'''),
    "clientsweep": ('''        devs = [d for d in sorted(set(cdevs) | st["markdevs"]) if''',
                    '''        devs = [d for d in sorted(set(_own_tunnel_devs(node_cfg)) | st["markdevs"]) if'''),
    "markstat": ('''    if st["mark"] is None:\n''', '''    if True:\n'''),
    "wireall": ('''        _lim_wire = None                            # …and the limits''', '''        _lim_wire = []                            # …and the limits'''),
    "noerr": ('''        snap["limit_err"] = dict(_LIMITS["err"])''', '''        pass'''),
}


def load(src, name):
    d = tempfile.mkdtemp(prefix="swg-limits-mod-")         # private per run: parallel plant runs never share a module
    tmp = os.path.join(d, "%s.py" % name)
    open(tmp, "w", encoding="utf-8").write(src)
    sys.dont_write_bytecode = True
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
        os.rmdir(d)


src = open(NODED, encoding="utf-8").read()
UNPLANTS = {"unwide"}                       # planted in uninstall.sh, which [14] reads
if PLANT and PLANT not in UNPLANTS:
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

    def monotonic(self):
        return NOW[0]


RC = {}                                      # a forced return code for the next batches (124: timed out)


def fake_run(args, input_text=None, timeout=20, env=None, read=False):
    lines = (input_text or "").splitlines()
    CALLS.append((list(args), lines))
    if RC.get("rc"):
        return subprocess.CompletedProcess(args, RC["rc"], "", "timed out\n")
    bad = any(("dev %s " % d) in ln for d in FAILDEV for ln in lines) or ("caps" in FAILDEV and lines and
                                                                          lines[0].startswith("actions change"))
    return subprocess.CompletedProcess(args, 1 if bad else 0, "",   # as tc says it: the cause, then the line
                                       "Error: Exclusivity flag on, cannot modify.\nCommand failed -:2\n" if bad else "")


N.run = fake_run
N.time = _Clock()
N._dev_ifindex = lambda d: IFX.get(d, 0)
N._own_tunnel_devs = lambda cfg=None: {"awg2", "wg1", "mesh1", "wgx-exit", "wdtt1", "wdttr1", "csqtt2"}
CLIENT = ["awg2", "csqtt2", "wdttr1", "wg1", "wdtt1"]
N._CLIENT_DEVS["list"] = list(CLIENT)
IDX0 = N.LIMITS_IDX0


def reset(mark=False):
    N._LIMITS.update(started=False, mark=None, markdevs=set(), sweepfail=None, next=IDX0, dev={}, pidx={}, caps={}, capfail=None, seen={}, fail={}, err={},
                     wire=None, cdevs=None, plan=None)
    N._CLIENT_DEVS["list"] = list(CLIENT)
    RC.clear()
    if os.path.exists(N.LIMITS_MARK):
        os.unlink(N.LIMITS_MARK)
    if mark:
        open(N.LIMITS_MARK, "w").close()
    CALLS.clear()
    FAILDEV.clear()
    IFX.clear()
    IFX.update({"awg2": 7, "wg1": 8, "wdtt1": 9, "mesh1": 10, "eth0": 2, "wgx-exit": 11, "wdttr1": 12, "csqtt2": 13})


def ens(wire, snap=None):
    res = {"changed": 0, "errors": []}                     # a fresh object, as every reply's json gives
    N._ensure_limits({}, [list(e) if isinstance(e, list) else e for e in wire] if isinstance(wire, list) else wire,
                     snap or {}, res)
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
check("the sweep covers the client tunnels only (never a mesh link or an exit), pref 4097 only",
      swept == ["awg2", "csqtt2", "wdtt1", "wdttr1", "wg1"]
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
check("a first load sweeps first (a wiped marker's leftovers), then one strict batch per device",
      [c[0] for c in CALLS] == [["tc", "-force", "-batch", "-"]] + [["tc", "-batch", "-"]] * 2, [c[0] for c in CALLS])
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
check("limit_err names tc's cause, not only its line", "Exclusivity" in N._LIMITS["err"].get("wg1", "")
      and "-:2" in N._LIMITS["err"].get("wg1", ""), N._LIMITS["err"])
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
       ["awg2", ["fd00::2/128"], 5, 0, 0, ""], ["awg2", ["10.9.0.9/32"], True, 0, 0, ""], "junk",
       ["awg2", ["10.9.0.5/24"], 5, 0, 0, ""], ["awg2", ["10.9.0.9/32"], 5, 0, 0, "u:a\n"]]
ens(BAD)
check("no spawn at all", CALLS == [], tc_lines())
check("each reported", {"mesh1", "eth0", "wgx-exit", "awg2", "?", "awg2\nqdisc del dev eth0 root"} <= set(N._LIMITS["err"]),
      N._LIMITS["err"])
ens(BAD + [W[0]])
check("a good entry beside them loads, and only it",
      len(CALLS) == 2 and not any(("mesh1" in ln or "eth0" in ln or "exit" in ln or "fd00" in ln or "0.0.0.0" in ln)
                                  for ln in CALLS[1][1]) and sum("filter add" in ln for ln in CALLS[1][1]) == 2, tc_lines())

print("[8] an absent device")
reset()
del IFX["wdtt1"]
ens([["wdtt1", ["10.66.0.2/32"], 10, 0, 0, ""]])
check("skipped without a word", not any("wdtt1" in ln for ln in tc_lines() if not ln.startswith("filter del"))
      and N._LIMITS["err"] == {}, (CALLS, N._LIMITS["err"]))
CALLS.clear()
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

print("[12] review round")
import re as _re
_m = _re.search(r"secrets\.randbelow\(1 << (\d+)\) << (\d+)", src)
check("the start index leaves room under tc's u32", _m and N.LIMITS_IDX0 + ((1 << int(_m.group(1))) << int(_m.group(2)))
      + 10 ** 9 < N.LIMITS_IDX_END <= 0xFFFFFFFF, _m and _m.group(0))
N._LIMITS["next"] = N.LIMITS_IDX_END - 1
check("the counter wraps before the end", (N._lim_alloc(), N._lim_alloc()) == (N.LIMITS_IDX_END - 1, N.LIMITS_IDX0))
reset()
OH = [["wdtt1", ["10.66.0.2/32"], 10, 0, 0, ""], ["awg2", ["10.9.0.2/32"], 0, 5, 0, ""]]
ens(OH)
CALLS.clear()
OH[0][2], OH[1][3] = 12, 6
r = ens(OH)
check("a one-hook device deletes only the hook it holds", sorted(ln for ln in tc_lines() if ln.startswith("filter del"))
      == ["filter del dev awg2 ingress pref 4097", "filter del dev wdtt1 egress pref 4097"], tc_lines())
CALLS.clear()
ens([])
check("…and so does its removal", sorted(tc_lines()) == ["filter del dev awg2 ingress pref 4097",
                                                          "filter del dev wdtt1 egress pref 4097"], tc_lines())
reset()
ens([["awg2", ["10.9.0.2/32", "10.9.0.2/32"], 10, 0, 0, ""], ["awg2", ["10.9.0.7/32", "10.9.0.2/32"], 5, 0, 0, ""]])
adds = [ln.split()[11] for ln in tc_lines() if ln.startswith("filter add")]
check("a prefix is loaded once per device", sorted(adds) == ["10.9.0.2/32", "10.9.0.7/32"], adds)
reset()
ens([["awg2", ["10.9.0.4/32"], 0, 0, 40, "g:x"], ["wg1", ["10.8.0.5/32"], 30, 0, 0, "g:x"]])
egress = [ln for ln in tc_lines() if " egress " in ln and ln.startswith("filter add")]
check("a pool with a combined and a per-direction member: the combined, one filter a prefix and hook",
      len(egress) == 2 and all("rate 40000kbit" in ln for ln in egress) and N._LIMITS["err"] == {}, tc_lines())
reset()
ens(W)
CALLS.clear()
ens({})
check("a `limits` that is not a list changes nothing and is reported", CALLS == [] and "limits" in N._LIMITS["err"]
      and set(N._LIMITS["dev"]) == {"awg2", "wg1"}, (CALLS, N._LIMITS["err"]))
# speeds: a RAW-capable WDTT password is two entries, one device
reset()
R = [["awg2", ["10.9.0.4/32"], 40, 0, 0, "u:a"], ["wdtt1", ["10.66.0.7/32"], 40, 0, 0, "u:a"],
     ["wdttr1", ["10.67.0.7/32"], 40, 0, 0, "u:a"], ["csqtt2", ["10.68.0.3/32"], 40, 0, 0, "u:a"]]


def snapr(a, w, c):
    return {"interfaces": {"awg2": {"peers": [{"allowed_ips": "10.9.0.4/32", "rx_speed": 0, "tx_speed": mb(a)}]}},
            "wdtt": [{"iface": "wdtt1", "raw_iface": "wdttr1", "passwords": {
                "pw": {"ip": "10.66.0.7", "raw_ip": "10.67.0.7", "rx_speed": 0, "tx_speed": mb(w)}}}],
            "csqtt": [{"iface": "csqtt2", "passwords": {"q": {"ip": "10.68.0.3", "rx_speed": 0, "tx_speed": mb(c)}}}]}


ens(R, snapr(30, 0, 0))
ens(R, snapr(30, 20, 0))
check("a WDTT password on two paths counts once", N._LIMITS["caps"].get(("u:a", "d")) == (40, 20.0), N._LIMITS["caps"])
ens(R, snapr(30, 20, 10))
check("a csqtt member by its `ip`", N._LIMITS["caps"].get(("u:a", "d"))[1] == 40 / 3, N._LIMITS["caps"])
NOW[0] += 10
ens(R, snapr(30, 20, 0))                     # csqtt's bytes arrive every 30 s: quiet between, still a member
check("a member that moved within LIMITS_HOLD_S stays counted", N._LIMITS["caps"].get(("u:a", "d"))[1] == 40 / 3,
      N._LIMITS["caps"])
NOW[0] += N.LIMITS_HOLD_S
ens(R, snapr(30, 20, 0))
check("…and after it, not", N._LIMITS["caps"].get(("u:a", "d")) == (40, 20.0), N._LIMITS["caps"])
pl = [("awg2", "10.9.%d.%d/32" % (i // 200, i % 200), "10.9.%d.%d" % (i // 200, i % 200), 0, 1.0, 0, "p") for i in range(30)]
sn = {"interfaces": {"awg2": {"peers": [{"allowed_ips": "10.9.%d.%d/32" % (i // 200, i % 200), "rx_speed": mb(0.5),
                                         "tx_speed": 0} for i in range(30)]}}}
cp = N._limits_caps(pl, {"p": {"n": 30, "u": 1.0}}, sn, frozenset(["awg2"]), {}, 0.0)
check("a cap never under LIMITS_MIN_CAP (tc refuses ~4 kbit with a 128 KB burst)", cp == {("p", "u"): (1.0, N.LIMITS_MIN_CAP)}, cp)
# a failed cap change
reset()
ens(G, snap(30, 0, 0))
FAILDEV.add("caps")
CALLS.clear()
r = ens(G, snap(30, 20, 0))
check("a failed cap change records the cap as unknown (some members may be set), and says so",
      N._LIMITS["caps"][("g:x", "d")] == (40, -1.0)
      and "Exclusivity" in N._LIMITS["err"].get("caps", "") and len(CALLS) == 1, (N._LIMITS["caps"], N._LIMITS["err"]))
CALLS.clear()
NOW[0] += 5
ens(G, snap(30, 20, 0))
check("not tried again within a minute", CALLS == [] and "caps" in N._LIMITS["err"], CALLS)
FAILDEV.clear()
NOW[0] += N.LIMITS_RETRY_S
ens(G, snap(30, 20, 0))
check("then tried, and in force", len(CALLS) == 1 and N._LIMITS["caps"][("g:x", "d")] == (40, 20.0)
      and "caps" not in N._LIMITS["err"], (CALLS, N._LIMITS["err"]))
# a sweep that never ran
reset(mark=True)
RC["rc"] = 124
ens(W)
check("a sweep that timed out loads nothing and is reported", len(CALLS) == 1 and "sweep" in N._LIMITS["err"]
      and os.path.exists(N.LIMITS_MARK), (CALLS, N._LIMITS["err"]))
RC.clear()
CALLS.clear()
NOW[0] += 5
ens(W)
check("…not again within a minute (a hung tc must not block every pass, F61)", CALLS == [] and "sweep" in N._LIMITS["err"],
      [c[0] for c in CALLS])
NOW[0] += N.LIMITS_RETRY_S
ens(W)
check("…and then tried again", len(CALLS) == 3 and "-force" in CALLS[0][0], [c[0] for c in CALLS])
# a WDTT device left out of the client list for one pass (its SNAT write failed)
reset()
WD = [["wdtt1", ["10.66.0.2/32"], 10, 0, 0, ""]]
ens(WD)
CALLS.clear()
N._CLIENT_DEVS["list"] = [d for d in CLIENT if d != "wdtt1"]
ens(WD)
check("a loaded device out of the client list for a pass keeps its limits", CALLS == [] and N._LIMITS["err"] == {},
      (CALLS, N._LIMITS["err"]))
N._CLIENT_DEVS["list"] = list(CLIENT)
# a node without a limit: the marker is stat'ed once
reset()
_rd, _stats = N._lim_mark_read, [0]


def _counting(st):
    _stats[0] += 1
    return _rd(st)


N._lim_mark_read = _counting
try:
    for _ in range(4):
        ens([])
finally:
    N._lim_mark_read = _rd
check("a node without a limit stats the marker once a process", _stats[0] <= 1 and CALLS == [], (_stats, CALLS))

print("[14] review round 2")
reset()
ens([["wdtt1", ["10.66.0.2/32"], 10, 0, 0, ""], ["awg2", ["10.9.0.2/32"], 10, 0, 0, ""]])
names = open(N.LIMITS_MARK).read().split()
check("the marker names every device loaded", names == ["awg2", "wdtt1"], names)
N._LIMITS.update(started=False, mark=None, markdevs=set(), dev={}, wire=None, cdevs=None, plan=None)   # a new process
N._CLIENT_DEVS["list"] = [d for d in CLIENT if d != "wdtt1"]           # wdtt1's SNAT write failed on its first pass
CALLS.clear()
ens([])
swept = sorted({ln.split()[3] for ln in tc_lines()})
check("a restart sweeps a device the marker names though it is not listed this pass (F59)", "wdtt1" in swept and
      not os.path.exists(N.LIMITS_MARK), (swept, os.path.exists(N.LIMITS_MARK)))
N._CLIENT_DEVS["list"] = list(CLIENT)
# a part-applied cap change is sent again when the wanted cap returns (F62)
reset()
ens(G, snap(30, 0, 0))
FAILDEV.add("caps")
ens(G, snap(30, 20, 0))
FAILDEV.clear()
NOW[0] += N.LIMITS_HOLD_S + 1
CALLS.clear()
ens(G, snap(30, 0, 0))                       # the wanted cap is back to the old one
NOW[0] += N.LIMITS_RETRY_S
ens(G, snap(30, 0, 0))
check("a part-applied cap change is sent again, whatever is wanted then", any(ln.startswith("actions change")
      and "rate 40000kbit" in ln for ln in tc_lines()) and N._LIMITS["caps"][("g:x", "d")] == (40, 40.0),
      (tc_lines(), N._LIMITS["caps"]))
# a `limits` that is not a list keeps the other errors (F69)
reset()
ens(W)
FAILDEV.add("wg1")
W6 = [list(e) for e in W]
W6[4][2] = 7
ens(W6)
FAILDEV.clear()
r = ens({})
check("a `limits` that is not a list keeps the other errors, and says so once", "wg1" in N._LIMITS["err"]
      and "limits" in N._LIMITS["err"] and len(r["errors"]) == 1 and ens({})["errors"] == [], (N._LIMITS["err"], r))
# uninstall clears exactly the devices the marker names (F68)
_un = open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()
if PLANT in UNPLANTS:
    assert _un.count(PLANTS[PLANT][0]) == 1, "plant anchor for %s missing or not unique — would FALSE-PASS" % PLANT
    _un = _un.replace(PLANTS[PLANT][0], PLANTS[PLANT][1], 1)
_m = _re.search(r"\[ -e /var/lib/swg-noded/limits \] && run sh -c '([^']*)'", _un)
check("uninstall has the marker-gated delete", _m is not None)
if _m:
    _d = tempfile.mkdtemp(prefix="swg-limits-un-")
    open(os.path.join(_d, "limits"), "w").write("awg2\nwdtt1\nbad name\n")
    open(os.path.join(_d, "tc"), "w").write("#!/bin/sh\necho \"$*\" >> %s/tc.log\n" % _d)
    os.chmod(os.path.join(_d, "tc"), 0o755)
    subprocess.run(["sh", "-c", _m.group(1).replace("/var/lib/swg-noded/limits", os.path.join(_d, "limits"))],
                   env={**os.environ, "PATH": _d + ":" + os.environ.get("PATH", "")})
    _log = open(os.path.join(_d, "tc.log")).read().split("\n") if os.path.exists(os.path.join(_d, "tc.log")) else []
    check("uninstall deletes pref 4097 on the devices the marker names, and only there",
          sorted(x for x in _log if x) == ["filter del dev awg2 egress pref 4097", "filter del dev awg2 ingress pref 4097",
                                           "filter del dev wdtt1 egress pref 4097", "filter del dev wdtt1 ingress pref 4097"],
          _log)
    for _f in os.listdir(_d):
        os.unlink(os.path.join(_d, _f))
    os.rmdir(_d)

print("[13] the main loop's wiring")
_pass = src[src.index("_relay_plan, _relay_sync_ok = None, False"):]
_pass = _pass[:_pass.index("_iv = 1.0 if _busy else interval")]
_i_none = _pass.find("\n        _lim_wire = None ")
_i_set = _pass.find('_lim_wire = reply.get("limits", [])')
_valid = _pass.rfind('if status == 200 and isinstance(reply.get("desired"), dict):', 0, _i_set)
check("each pass starts with no wire", _i_none >= 0, _i_none)
check("the wire is set only from a valid 200 carrying `desired`", _i_set > 0 and _pass.count("_lim_wire = ") == 2
      and 0 < _valid and _pass[_valid:_i_set].count("\n") <= 3, _pass[_valid:_i_set + 40] if _valid > 0 else "no guard")
_call = _pass.find("\n        if _lim_wire is not None:")
check("the call sits outside the sync's try, at the loop's level", _call > _i_set
      and "_ensure_limits(node_cfg, _lim_wire, snap, _lres)" in _pass[_call:_call + 800], _call)
check("the snapshot carries limit_err", 'snap["limit_err"] = dict(_LIMITS["err"])' in src)


print("[11] a real kernel")
NS = "swglimtest%d" % os.getpid()
try:
    ok = subprocess.run(["sudo", "-n", "ip", "netns", "add", NS], capture_output=True).returncode == 0
except OSError:                              # no sudo binary at all
    ok = False
if not ok:
    print("  SKIP — no `sudo -n ip netns` here")
else:
    try:
        def nsx(args, inp=None):
            return subprocess.run(["sudo", "-n", "ip", "netns", "exec", NS] + args, input=inp, capture_output=True, text=True)
        for d in ("awg2", "wg1", "wdtt1"):
            nsx(["ip", "link", "add", d, "type", "dummy"])
            nsx(["ip", "link", "set", d, "up"])
        N.run = lambda args, input_text=None, timeout=20, env=None, read=False: nsx(list(args), input_text)
        N._dev_ifindex = lambda d: (lambda r: int(r.stdout) if r.returncode == 0 and r.stdout.strip().isdigit() else 0)(
            nsx(["cat", "/sys/class/net/%s/ifindex" % d]))
        N._LIMITS["dev"].clear()

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
        W5 = W4 + [["wdtt1", ["10.66.0.2/32"], 10, 0, 0, ""]]
        r = ens(W5)
        W5[-1][2] = 12
        r = ens(W5)
        flt = nsx(["tc", "filter", "show", "dev", "wdtt1", "egress"]).stdout
        check("a download-only device rebuilds (only its egress deleted)", r["errors"] == [] and "rate 12Mbit" in flt,
              (r, flt[:300]))
        N._LIMITS["next"] = N.LIMITS_IDX_END - 1
        W5[-1][2] = 14
        r = ens(W5)
        flt = nsx(["tc", "filter", "show", "dev", "wdtt1", "egress"]).stdout
        check("an index at the top of the range loads, the next wraps", r["errors"] == [] and "rate 14Mbit" in flt
              and N._LIMITS["next"] == N.LIMITS_IDX0, (r, N._LIMITS["next"]))
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
