#!/usr/bin/env python3
"""Self-test — swg-sni confirms its NFQUEUE bind, and swg-noded believes it (docs/SCALE-PLAN.md K8 D1).

swg-sni sent its BIND and never read the answer: with the queue held by another process (an IPS, a stray reader) the kernel
answered EPERM into a stream the packet loop skips, swg-sni logged "bound", saw no packet, and swg-noded reported the
classifier alive (1.8.9 CPU re-qualification, register N1). Now the BIND asks for an ack and reads it; a refusal exits.

The laptop has no nfnetlink_queue module and no unprivileged user namespace, so the socket here is a fake that answers as
the kernel does (`nfqnl_recv_config` + `netlink_rcv_skb`): an error is always answered, a success only when NLM_F_ACK asks,
and a queue exists from the BIND on, so a packet can arrive before the answer. The kernel half is the live check on a node.

  [1] the kernel accepts: the BIND carries NLM_F_ACK (seq 1), the answer is read, PARAMS follow; no warning.
  [2] the kernel refuses (EPERM): QueueRefused, no PARAMS, the socket closed; main() logs the refusal at err and exits non-zero.
  [3] a packet queued before the answer is ACCEPTed (its verdict sent) and the bind is still confirmed.
  [4] no answer at all: a warning, and on as before (fail-open).
  [5] swg-noded: a swg-sni that died within 60 s of its launch is not relaunched until that minute is over — `sni_alive`
      reads false meanwhile; one that ran longer is relaunched in the same pass; a stop noded made itself is not delayed.
  [6] swg-noded: the TTL relaunch waits for the old process before it starts the new one.

Run: python3 tests/sni_queue_bind_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED (exit 0 when caught):
     noack       the answer is never read (the BIND sent blind, as before)          [1][2]
     noackflag   the BIND does not ask for an ack (a success is never confirmed)     [1]
     ignoreerr   a refusal is read and ignored                                       [2]
     droppkt     a packet that arrives before the answer is dropped, not accepted    [3]
     everypass   swg-noded relaunches a dead swg-sni every pass                      [5]
     nowait      the TTL relaunch does not wait for the old process                  [6]
"""
import importlib.machinery, importlib.util, os, socket, struct, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
SNI = os.environ.get("SWG_SNI") or os.path.join(ROOT, "swg-sni")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)


PLANTS = {
    "noack": (SNI, "        err = self._answer(1)\n", "        err = 0\n"),
    "noackflag": (SNI, "flags=NLM_F_REQUEST | NLM_F_ACK, seq=1)", "flags=NLM_F_REQUEST, seq=1)"),
    "ignoreerr": (SNI, "        if err:\n            self.s.close()\n            raise QueueRefused(err)\n", "        if False:\n            pass\n"),
    "droppkt": (SNI, "                        if pid is not None:\n                            self._accept(pid)\n",
                "                        if pid is not None:\n                            pass\n"),
    "everypass": (NODED, '        if p and time.monotonic() - _SNI_PROC.get("at", 0.0) < 60:\n            return\n', ""),
    "nowait": (NODED, "            p.terminate(); p.wait(2)", "            p.terminate()"),
}
TMP = tempfile.mkdtemp(prefix="sni-bind-")
paths = {SNI: SNI, NODED: NODED}
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    f, old, new = PLANTS[PLANT]
    src = open(f, encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    paths[f] = os.path.join(TMP, "planted-" + os.path.basename(f) + ".py")
    open(paths[f], "w", encoding="utf-8").write(src.replace(old, new, 1))


def load(p, name):
    l = importlib.machinery.SourceFileLoader(name, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m


os.environ["SWG_NODED_STATE"] = TMP
S = load(paths[SNI], "swgsni_bind")
LOG = []
S.say = lambda prio, fmt, *a: LOG.append((prio, fmt % a if a else fmt))

# ── the fake kernel ───────────────────────────────────────────────────────────────────────────────────────────────────
EPERM = 1
SCN = {"err": 0, "before": [], "silent": False}


def _hdr(b):
    return struct.unpack("=IHHII", b[:16])


def _is_bind(b):
    return S.struct.pack("=BB", S.NFQNL_CFG_CMD_BIND, 0) in b[20:] and _hdr(b)[1] == S.NFQNL_MSG_CONFIG and \
        struct.pack("=HH", 8, S.NFQA_CFG_CMD) in b[20:]


def _error(orig, err):
    """struct nlmsghdr + struct nlmsgerr {int error; struct nlmsghdr msg} — as netlink_ack writes it (no payload copy)."""
    ln, _t, _f, seq, pid = _hdr(orig)
    return struct.pack("=IHHII", 36, S.NLMSG_ERROR, 0, seq, pid) + struct.pack("=i", -err) + orig[:16]


def _packet(pid):
    body = struct.pack("=BB", 2, 0) + struct.pack(">H", 0) + S._nla(S.NFQA_PACKET_HDR, struct.pack(">IHB", pid, 0x0800, 1))
    return struct.pack("=IHHII", 16 + len(body), S.NFQNL_MSG_PACKET, 0, 0, 0) + body


class FakeNL:
    def __init__(self, *a):
        self.sent, self.inbox, self.closed = [], [], False

    def setsockopt(self, *a):
        pass

    def bind(self, a):
        pass

    def settimeout(self, t):
        pass

    def close(self):
        self.closed = True

    def send(self, b):
        self.sent.append(b)
        ln, typ, flags, seq, pid = _hdr(b)
        if typ != S.NFQNL_MSG_CONFIG or SCN["silent"]:
            return len(b)
        if _is_bind(b):
            self.inbox += [_packet(p) for p in SCN["before"]]
        if SCN["err"] or flags & S.NLM_F_ACK:            # netlink_rcv_skb: an error always, a success only on NLM_F_ACK
            self.inbox.append(_error(b, SCN["err"]))
        return len(b)

    def recv(self, n):
        if not self.inbox:
            raise socket.timeout("timed out")
        return self.inbox.pop(0)


REAL_SOCKET = socket.socket
LAST = {}


def mk(*a):
    LAST["s"] = FakeNL(*a)
    return LAST["s"]


def run_bind(err=0, before=(), silent=False):
    SCN.update(err=err, before=list(before), silent=silent)
    del LOG[:]
    S.socket.socket = mk
    try:
        try:
            S.NFQueue(0)
            return None
        except S.QueueRefused as e:
            return e
    finally:
        S.socket.socket = REAL_SOCKET


def configs(s):
    return [b for b in s.sent if _hdr(b)[1] == S.NFQNL_MSG_CONFIG]


def verdicts(s):
    return [struct.unpack(">II", b[24:32])[1] for b in s.sent if _hdr(b)[1] == S.NFQNL_MSG_VERDICT]


print("[1] the kernel accepts")
e = run_bind(0)
s = LAST["s"]
cf = configs(s)
check("[1] bound: no refusal", e is None, e)
check("[1] the BIND asks for an ack, seq 1", bool(cf) and _is_bind(cf[0]) and _hdr(cf[0])[2] & S.NLM_F_ACK and _hdr(cf[0])[3] == 1,
      [_hdr(b) for b in cf])
check("[1] PARAMS follow the confirmed bind", len(cf) == 2 and not _is_bind(cf[1]), [_hdr(b) for b in cf])
check("[1] no warning: the answer was read", not [l for l in LOG if l[0] == S.LOG_WARNING], LOG)

print("\n[2] the kernel refuses (EPERM: another socket holds the queue)")
e = run_bind(EPERM)
s = LAST["s"]
check("[2] QueueRefused, carrying EPERM", e is not None and e.args[0] == EPERM, e)
check("[2] no PARAMS after a refusal, the socket closed", len(configs(s)) == 1 and s.closed, (len(configs(s)), s.closed))
SCN.update(err=EPERM, before=[], silent=False)
del LOG[:]
S.Classifier = lambda *a, **k: None
S.socket.socket = mk
argv, code = sys.argv, None
sys.argv = ["swg-sni", "--queue", "0", "--map", os.path.join(TMP, "none.json")]
try:
    S.main()
except SystemExit as x:
    code = x.code
except Exception as x:                                          # it went on into the packet loop: the fake has nothing more
    code = None
finally:
    S.socket.socket = REAL_SOCKET
    sys.argv = argv
check("[2] main() exits non-zero", code not in (None, 0), code)
check("[2] …with one err line naming the refusal, and never 'bound'",
      [l for l in LOG if l[0] == S.LOG_ERR and "refused (EPERM)" in l[1]] and not [l for l in LOG if "bound queue" in l[1]], LOG)

print("\n[3] a packet before the answer")
e = run_bind(0, before=[77, 78])
s = LAST["s"]
check("[3] both are accepted at once (their verdicts sent)", verdicts(s) == [77, 78], verdicts(s))
check("[3] …and the bind is still confirmed (PARAMS follow, no warning)",
      e is None and len(configs(s)) == 2 and not [l for l in LOG if l[0] == S.LOG_WARNING], (e, LOG))

print("\n[4] no answer at all")
e = run_bind(0, silent=True)
s = LAST["s"]
check("[4] a warning, and on as before (PARAMS sent)", e is None and len(configs(s)) == 2
      and [l for l in LOG if l[0] == S.LOG_WARNING and "no answer" in l[1]], (e, LOG))

# ── swg-noded ─────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] swg-noded relaunches a swg-sni that died")
N = load(paths[NODED], "swgnoded_bind")
N.SNI_MAP_PATH, N.SNI_BLOCKS_PATH = os.path.join(TMP, "map.json"), os.path.join(TMP, "blocks.json")
N.SNI_PATTERNS_PATH, N.SNI_SETS_PATH = os.path.join(TMP, "pat.json"), os.path.join(TMP, "sets.json")
N.NODE_KIND = "baremetal"
EV = []


class Proc:
    def __init__(self, rc):
        self.rc = rc

    def poll(self):
        return self.rc

    def terminate(self):
        EV.append("terminate")
        self.rc = -15

    def wait(self, t=None):
        EV.append("wait")
        return self.rc


def popen(*a, **k):
    EV.append("launch")
    return Proc(None)


N.subprocess.Popen = popen
sys.argv[0] = os.path.join(ROOT, "swg-noded")                  # swg-sni is found beside it


def router(ttl=3600):
    del EV[:]
    r = {"changed": 0, "errors": []}
    N._ensure_sni_router({"google": ["google.com"]}, ["10.188.1.0/24"], r, learn_ttl=ttl)
    return r


alive = lambda: bool(N._SNI_PROC.get("p") and N._SNI_PROC["p"].poll() is None)   # smart_status's sni_alive
dead = Proc(3)
N._SNI_PROC.update(p=dead, ttl=3600, at=time.monotonic() - 10)
r = router()
check("[5] died 10 s after its launch: not relaunched this pass", "launch" not in EV and N._SNI_PROC["p"] is dead, (EV, r))
check("[5] …and sni_alive reads false meanwhile", alive() is False)
N._SNI_PROC["at"] = time.monotonic() - 61
r = router()
check("[5] once the minute is over: relaunched, its launch time taken",
      EV == ["launch"] and alive() and time.monotonic() - N._SNI_PROC["at"] < 5, (EV, r))
N._SNI_PROC.update(p=Proc(1), at=time.monotonic() - 3600)
router()
check("[5] one that ran an hour and died is relaunched in the same pass, as before", EV == ["launch"], EV)
N._SNI_PROC.update(p=None, at=time.monotonic())
router()
check("[5] a stop noded made itself (no process) launches at once", EV == ["launch"], EV)

print("\n[6] the TTL relaunch")
N._SNI_PROC.update(p=Proc(None), ttl=3600, at=time.monotonic() - 5)
router(ttl=120)
check("[6] the old process is stopped AND waited for before the new one starts", EV == ["terminate", "wait", "launch"], EV)

import shutil
shutil.rmtree(TMP, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
