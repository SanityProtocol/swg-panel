#!/usr/bin/env python3
"""Self-test — a turn server binds what clients dial when it lands on the box, and every address when it does not.

A home box behind a MikroTik (client report, 2026-10-06): its public name is the router's DDNS host, which resolves to the
router's WAN address. Plain WireGuard worked with that name as Endpoint; a turn server could not be brought up at all,
because the node passed the operator's `listen` straight to the server binary as the address to BIND — and an address
that is not on the box cannot be bound (`bind: cannot assign requested address`, a crash loop). The upstream servers
never had that problem: they listen on 0.0.0.0 by default and the client is told the host separately.

swg-noded turn_bind now decides: a host that lands on this box is bound (on a box with several addresses that is what
keeps replies leaving from the address the client dialled); anything else listens on every address. The `listen` the
panel gave stays what clients dial — in the node's record, and for a vk-turn-proxy in its env file beside the bind.

  [1] turn_bind: a literal of the box / a name resolving to it bind that address; a foreign literal, a name resolving
      elsewhere, a name that does not resolve → 0.0.0.0 on the same port; IPv6, wildcards, unreadable addresses → as given
  [2] vk-turn-proxy env: a host on the box writes the file byte-identical to before; a foreign one binds 0.0.0.0 and
      keeps the dialled host as SWG_DIAL — and the read-back reports that host as `listen`, the bind as `bind`
  [3] WDTT / csqtt: the env file and the docker argv carry the bind; the record (what the panel reads back) keeps the host
  [4] the WDTT RAW listener: an IP the box does not carry binds every address, not a crash
  [5] docker vk-turn-proxy (host networking): the container is run on the bind, the record keeps the host
  [6] a WDTT/csqtt server whose env an older build wrote with an unbindable host is rewritten once per run (the update
      brings it up) and by an operator's Restart — never a working server, never from a partial record
  [7] Listen on (`bind_ip`): a pin the box carries is bound whatever the host; one it does not carry is ignored; it is
      kept in the vk-turn-proxy env, read back, a parameter change for WDTT/csqtt, and binds the RAW listener too
  [8] a name that does not resolve right now (DNS not up at boot) keeps what the server binds today; the heal waits
  [9] heal_turn_binds: a vk-turn-proxy env with an unbindable host (an older build, an installer, convert.sh) is
      re-rendered and restarted once per run; a carried Listen on is applied; a working or stopped one is left alone
  [10] every bash reader of turn.env takes SWG_DIAL before SWG_LISTEN (the bind), or a re-install / convert loses the host
  [11] (1.8.9 qualification IN-3) the LIVE bare → Docker convert — install-docker.sh's migrate_baremetal_turns +
       install_turn_binary, driven on fake units and turn.env files: the docker record keeps the host clients dial (a DDNS
       name not on the box) and the Listen on as bind_ip; an older env and a legacy unit as before
  [12] (1.8.9 qualification DN-1) a Docker vk-turn-proxy container an older build ran on an unbindable host — crash-looping,
       which docker reports as Running, its image NAME unchanged by the release-day `latest` update — is recreated through
       turn_bind by the background reconcile, once per run, and the record (what the node reports) keeps the new bind; a
       container that binds fine (a name or address on the box, every address), a stopped one, one docker cannot describe
       and one whose name does not resolve right now are left alone; a carried Listen on is applied; the record's two
       writers share a lock and the background one never undoes a change written meanwhile

Run: python3 tests/turn_bind_selftest.py         (0 = pass)
     --perturb   turn_bind hands the host on unchanged again — expects RED in [1]–[9].
     --perturb-docker   install-docker.sh reads SWG_LISTEN alone and drops SWG_PIN again — expects RED in [10] and [11].
     --perturb-dn1    the background reconcile never compares a running container's bind (52aa9c4) — expects RED in [12].
     --perturb-keep   …compares it, but the record does not keep the new bind — expects RED in [12].
     --perturb-lock   apply_turn writes the record without the lock — expects RED in [12].
"""
import os, socket, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv[1:]
PERTURB_DOCKER = "--perturb-docker" in sys.argv[1:]
PERTURB_DN1 = "--perturb-dn1" in sys.argv[1:]
PERTURB_KEEP = "--perturb-keep" in sys.argv[1:]
PERTURB_LOCK = "--perturb-lock" in sys.argv[1:]
ANCHOR = '    mine = _local_v4()\n    if mine is None:\n        return s\n'
SRCS = {f: open(os.path.join(ROOT, f), encoding="utf-8").read() for f in ("install-node.sh", "install-host.sh", "convert.sh", "install-docker.sh")}
if PERTURB_DOCKER:   # the convert as it shipped: the bind read as the address clients dial, the pin never read
    _dial = """lis="$(sed -n 's/^SWG_DIAL=//p' "$envf" | sed -n 1p)"; [ -n "$lis" ] || lis="$(sed -n 's/^SWG_LISTEN=//p' "$envf" | sed -n 1p)\""""
    _pin = """pin="$(sed -n 's/^SWG_PIN=//p' "$envf" | sed -n 1p)\""""
    assert SRCS["install-docker.sh"].count(_dial) == 2 and SRCS["install-docker.sh"].count(_pin) == 1, \
        "perturbation anchors missing — would FALSE-PASS"
    SRCS["install-docker.sh"] = SRCS["install-docker.sh"].replace(_dial, """lis="$(sed -n 's/^SWG_LISTEN=//p' "$envf" | sed -n 1p)\"""").replace(_pin, 'pin=""')

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:240]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(NODED, encoding="utf-8").read()
# ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
assert src.count(ANCHOR) == 1, "perturbation anchor missing or not unique — would FALSE-PASS"
if PERTURB:
    src = src.replace(ANCHOR, '    return s\n', 1)
for _flag, _old, _new in ((PERTURB_DN1, '        _bind_why = _dturn_bind_stale(svc, tp) if _ns_ok and _img_ok else ""', '        _bind_why = ""'),
                          (PERTURB_KEEP, '        _dturn_keep_bind(svc, tp.get("bind", ""))', '        pass'),
                          (PERTURB_LOCK, '            with _TURN_REC_LOCK:                       # the background', '            if True:                       # the background')):
    assert src.count(_old) == 1, "perturbation anchor missing or not unique — would FALSE-PASS: " + _old.strip()[:60]
    if _flag:
        src = src.replace(_old, _new, 1)
N = types.ModuleType("n")
N.__dict__.update({"__name__": "n", "__file__": NODED})
exec(compile(src.split("\nif __name__ ==")[0], "swg-noded", "exec"), N.__dict__)

BOX = {"192.168.88.10", "10.66.66.1"}                  # a home box behind NAT: its LAN address + a tunnel
N._local_addrs = lambda: [("eth0", ip, ip + "/24") for ip in sorted(BOX)]
DNS = {"abcd1234.sn.mynetname.net": ["203.0.113.50"],   # the MikroTik DDNS name → the router's WAN address
       "nettop.lan": ["192.168.88.10"],                 # a name that lands on the box
       "both.example": ["203.0.113.50", "192.168.88.10"]}
_real_gai = socket.getaddrinfo
def fake_gai(host, *a, **k):
    if host in DNS:
        return [(socket.AF_INET, socket.SOCK_DGRAM, 17, "", (ip, 0)) for ip in DNS[host]]
    if host.startswith("gone."):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")      # NXDOMAIN: definite
    raise socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")   # DNS not up: temporary
N.socket.getaddrinfo = fake_gai
DDNS = "abcd1234.sn.mynetname.net"

print("[1] turn_bind")
for listen, want in (("192.168.88.10:56000", "192.168.88.10:56000"),     # a literal of the box: bound as it is
                     ("203.0.113.7:56000", "0.0.0.0:56000"),             # an IP the box does not carry (cloud 1:1 NAT)
                     (DDNS + ":56000", "0.0.0.0:56000"),                 # the DDNS name → the router → every address
                     ("nettop.lan:56000", "192.168.88.10:56000"),        # a name that lands on the box → as that IP
                     ("both.example:56000", "192.168.88.10:56000"),      # one of its addresses is the box's
                     ("nowhere.invalid:56000", "0.0.0.0:56000"),         # does not resolve → every address
                     ("0.0.0.0:56000", "0.0.0.0:56000"),
                     ("[2a02:6b8::10]:56000", "[2a02:6b8::10]:56000"),   # IPv6: as given (only IPv4 is judged)
                     ("", "")):
    got = N.turn_bind(listen)
    check("%r → %r" % (listen, want), got == want, got)
check("resolve=False: a name binds every address without a lookup", N.turn_bind("nettop.lan:56000", resolve=False) == "0.0.0.0:56000",
      N.turn_bind("nettop.lan:56000", resolve=False))
_save = N._local_addrs; N._local_addrs = lambda: None; N._LOCAL_V4["at"] = -1e9
check("addresses unreadable → as given (what every node did before)", N.turn_bind(DDNS + ":56000") == DDNS + ":56000", N.turn_bind(DDNS + ":56000"))
N._local_addrs = _save; N._LOCAL_V4["at"] = -1e9

print("\n[2] vk-turn-proxy env file and read-back")
OLD = "SWG_LISTEN=%s\nSWG_CONNECT=127.0.0.1:51820\nSWG_PARAMS=-wrap-key ab\n"
t = N._turn_env_text("192.168.88.10:56000", "127.0.0.1:51820", "-wrap-key ab")
check("a host on the box: byte-identical to the old file", t == OLD % "192.168.88.10:56000", t)
t = N._turn_env_text(DDNS + ":56000", "127.0.0.1:51820", "-wrap-key ab")
check("a foreign host: binds 0.0.0.0, keeps the host as SWG_DIAL",
      t == "SWG_LISTEN=0.0.0.0:56000\nSWG_DIAL=%s:56000\nSWG_CONNECT=127.0.0.1:51820\nSWG_PARAMS=-wrap-key ab\n" % DDNS, t)
N.host_sh = lambda cmd, **k: types.SimpleNamespace(returncode=0, stdout=t, stderr="")
UNIT = "[Service]\nEnvironmentFile=-/opt/vk-turn-proxy/x/turn.env\nExecStart=/opt/vk-turn-proxy/x/server -listen ${SWG_LISTEN} -connect ${SWG_CONNECT} $SWG_PARAMS\n"
rb = N._tp_from_unit("vk-turn-proxy-samosvalishe-56000", UNIT)
check("read-back: `listen` is what clients dial", rb.get("listen") == DDNS + ":56000", rb)
check("read-back: `bind` is what the server binds", rb.get("bind") == "0.0.0.0:56000", rb)
N.host_sh = lambda cmd, **k: types.SimpleNamespace(returncode=0, stdout=OLD % "192.168.88.10:56000", stderr="")
rb = N._tp_from_unit("vk-turn-proxy-samosvalishe-56000", UNIT)
check("an old file (no SWG_DIAL): listen = bind = SWG_LISTEN", rb.get("listen") == rb.get("bind") == "192.168.88.10:56000", rb)

print("\n[3] WDTT / csqtt: env and docker argv bind, the record keeps the host")
W = {"iface": "wdtt0", "wg_addr": "10.66.66.1/24", "listen": DDNS + ":56000", "wg_port": 56001, "password": "p", "fork": "amurcanov"}
we = N._wdtt_env_text(W)
check("WDTT env: SWG_LISTEN=0.0.0.0:56000", "SWG_LISTEN=0.0.0.0:56000\n" in we, we.splitlines()[:4])
wa = N._wdtt_argv(W, "/x/server")
check("WDTT argv: -listen 0.0.0.0:56000", wa[wa.index("-listen") + 1] == "0.0.0.0:56000", wa)
check("…and the record still says what clients dial", W["listen"] == DDNS + ":56000", W)
we2 = N._wdtt_env_text(dict(W, listen="192.168.88.10:56000"))
check("WDTT env, host on the box: bound as it is", "SWG_LISTEN=192.168.88.10:56000\n" in we2, we2.splitlines()[:4])
C = {"iface": "csqtt0", "tun_addr": "10.66.67.1/24", "listen": "nettop.lan:46000", "password": "p"}
ce = N._csqtt_env_text(C)
check("csqtt env: a name on the box binds as its IP (csqtt parses a socket address)", "SWG_LISTEN=192.168.88.10:46000\n" in ce, ce.splitlines()[:2])
ca = N._csqtt_argv(dict(C, listen=DDNS + ":46000"), "/x/server")
check("csqtt argv: a foreign host → --listen 0.0.0.0:46000", ca[ca.index("--listen") + 1] == "0.0.0.0:46000", ca)

print("\n[4] the WDTT RAW listener")
R = dict(W, raw_port="56003", raw_iface="wdttraw0", raw_addr="10.77.0.1/24")
check("an IP the box does not carry → 0.0.0.0:56003", (N._wdtt_raw(dict(R, listen="203.0.113.7:56000")) or ("",))[0] == "0.0.0.0:56003",
      N._wdtt_raw(dict(R, listen="203.0.113.7:56000")))
check("an IP of the box → that IP", (N._wdtt_raw(dict(R, listen="192.168.88.10:56000")) or ("",))[0] == "192.168.88.10:56003",
      N._wdtt_raw(dict(R, listen="192.168.88.10:56000")))

print("\n[5] docker vk-turn-proxy (host networking)")
N.NODE_NET = "host"
tp = {"service": "vk-turn-proxy-samosvalishe-56000", "listen": DDNS + ":56000", "connect": "127.0.0.1:51820", "params": ""}
a = N._dturn_args(tp)
check("the container is run on 0.0.0.0:56000", a[a.index("-listen") + 1] == "0.0.0.0:56000", a)
check("the record keeps the host and reports the bind", tp["listen"] == DDNS + ":56000" and tp.get("bind") == "0.0.0.0:56000", tp)

print("\n[6] a server set up before this build: healed once by the update, and by Restart")
import tempfile
d = tempfile.mkdtemp(prefix="turnbind-")
envp = os.path.join(d, "wdtt.env")
open(envp, "w").write("SWG_IFACE=wdtt0\nSWG_LISTEN=%s:56000\nSWG_WGPORT=56001\n" % DDNS)   # the old file: the host as typed
check("an old env binding the DDNS name → heal due", N.bind_heal_due("wdtt:wdtt0", envp, DDNS + ":56000") is True)
check("…once per run, not per sync", N.bind_heal_due("wdtt:wdtt0", envp, DDNS + ":56000") is False)
open(envp, "w").write("SWG_LISTEN=192.168.88.10:56000\n")
check("a working server (its host is on the box) is never restarted for it", N.bind_heal_due("wdtt:w1", envp, "192.168.88.10:56000") is False)
open(envp, "w").write("SWG_LISTEN=0.0.0.0:56000\n")
check("a file this build wrote (already the bind) → nothing to heal", N.bind_heal_due("wdtt:w2", envp, DDNS + ":56000") is False)
open(envp, "w").write("SWG_IFACE=wdtt0\nSWG_LISTEN=%s:56000\n" % DDNS)
N.rebind_env(envp, W, N._wdtt_env_text)
check("Restart rewrites an env that binds an unbindable host", N._env_listen(envp) == "0.0.0.0:56000", open(envp).read()[:120])
before = open(envp).read()
N.rebind_env(envp, W, N._wdtt_env_text)
check("…and leaves one that is already right byte-identical", open(envp).read() == before)
open(envp, "w").write("SWG_LISTEN=%s:56000\n" % DDNS)
N.rebind_env(envp, dict(W, password=""), N._wdtt_env_text)
check("…never from a partial record (no password)", N._env_listen(envp) == DDNS + ":56000", open(envp).read())

print("\n[7] Listen on (bind_ip): the one address of the box to bind, whatever the host")
check("a pin the box carries wins over the host", N.turn_bind(DDNS + ":56000", pin="10.66.66.1") == "10.66.66.1:56000",
      N.turn_bind(DDNS + ":56000", pin="10.66.66.1"))
check("…even over a host that is on the box", N.turn_bind("192.168.88.10:56000", pin="10.66.66.1") == "10.66.66.1:56000",
      N.turn_bind("192.168.88.10:56000", pin="10.66.66.1"))
check("a pin the box no longer carries is ignored → the rule decides", N.turn_bind(DDNS + ":56000", pin="10.9.9.9") == "0.0.0.0:56000",
      N.turn_bind(DDNS + ":56000", pin="10.9.9.9"))
t = N._turn_env_text(DDNS + ":56000", "127.0.0.1:51820", "", "10.66.66.1")
check("vk-turn-proxy env keeps the pin (SWG_PIN) for a Restart/rotation to re-render from",
      "SWG_LISTEN=10.66.66.1:56000\n" in t and "SWG_DIAL=%s:56000\n" % DDNS in t and "SWG_PIN=10.66.66.1\n" in t, t)
check("…and only an address goes into it", "SWG_PIN" not in N._turn_env_text(DDNS + ":56000", "c:1", "", "x\nSWG_X=1"))
N.host_sh = lambda cmd, **k: types.SimpleNamespace(returncode=0, stdout=t, stderr="")
rb = N._tp_from_unit("vk-turn-proxy-samosvalishe-56000", UNIT)
check("read-back reports it as bind_ip", rb.get("bind_ip") == "10.66.66.1" and rb.get("listen") == DDNS + ":56000", rb)
we = N._wdtt_env_text(dict(W, bind_ip="10.66.66.1"))
check("WDTT env binds the pin", "SWG_LISTEN=10.66.66.1:56000\n" in we, we.splitlines()[:4])
check("a changed pin is a parameter change (rewrite + restart)", N._wdtt_params_changed(dict(W), dict(W, bind_ip="10.66.66.1")) is True)
check("csqtt too", N._csqtt_params_changed(dict(C), dict(C, bind_ip="10.66.66.1")) is True)
check("the WDTT RAW listener binds the pin", (N._wdtt_raw(dict(R, bind_ip="10.66.66.1")) or ("",))[0] == "10.66.66.1:56003",
      N._wdtt_raw(dict(R, bind_ip="10.66.66.1")))
tp2 = {"service": "vk-turn-proxy-samosvalishe-56000", "listen": DDNS + ":56000", "connect": "127.0.0.1:51820", "params": "", "bind_ip": "10.66.66.1"}
a = N._dturn_args(tp2)
check("docker: the container is run on the pin", a[a.index("-listen") + 1] == "10.66.66.1:56000", a)

print("\n[8] a name that does not resolve RIGHT NOW is not one that resolves elsewhere")
check("it keeps what the server binds today (DNS not up at boot)", N.turn_bind("nowhere.invalid:56000", prev="192.168.88.10:56000") == "192.168.88.10:56000",
      N.turn_bind("nowhere.invalid:56000", prev="192.168.88.10:56000"))
check("a new server (nothing to keep) binds every address", N.turn_bind("nowhere.invalid:56000", prev="") == "0.0.0.0:56000")
check("a kept bind on another port is not reused", N.turn_bind("nowhere.invalid:56000", prev="192.168.88.10:57000") == "0.0.0.0:56000")
check("a name that DOES resolve elsewhere is not kept", N.turn_bind(DDNS + ":56000", prev="192.168.88.10:56000") == "0.0.0.0:56000")
check("a kept bind the box no longer carries is not reused (DHCP change, cleared pin)",
      N.turn_bind("nowhere.invalid:56000", prev="10.9.9.9:56000") == "0.0.0.0:56000", N.turn_bind("nowhere.invalid:56000", prev="10.9.9.9:56000"))
check("a name that does not exist (NXDOMAIN) is a definite answer: every address, nothing kept",
      N.turn_bind("gone.example:56000", prev="192.168.88.10:56000") == "0.0.0.0:56000", N.turn_bind("gone.example:56000", prev="192.168.88.10:56000"))
open(envp, "w").write("SWG_LISTEN=nowhere.invalid:56000\n")
check("heal: not judged while the name does not resolve…", N.bind_heal_due("wdtt:dns", envp, "nowhere.invalid:56000") is False)
DNS["nowhere.invalid"] = ["203.0.113.99"]
check("…not asked again on the next sync (5-minute backoff, not a lookup per pass)", N.bind_heal_due("wdtt:dns", envp, "nowhere.invalid:56000") is False)
N._BIND_RETRY.clear()                                   # five minutes later
check("…and judged once it does (not marked in between)", N.bind_heal_due("wdtt:dns", envp, "nowhere.invalid:56000") is True)
del DNS["nowhere.invalid"]; N._RESOLVED.clear()        # the outage begins (and the 60 s answer cache has aged out)
open(envp, "w").write("SWG_LISTEN=192.168.88.10:56000\n")
N.rebind_env(envp, dict(W, listen="nowhere.invalid:56000"), N._wdtt_env_text)
check("Restart during a DNS outage leaves a working env alone", N._env_listen(envp) == "192.168.88.10:56000", open(envp).read())

print("\n[9] vk-turn-proxy heal (installers, convert.sh, an older build wrote the dialled host)")
import json as _json
rec = os.path.join(d, "turn-proxy.json")
N.TURN_RECORD = rec; N.TURN_DOCKER = False; N.TURN_MANAGE_ON = True
ENVS = {"vk-turn-proxy-samosvalishe-56000": "SWG_LISTEN=%s:56000\nSWG_CONNECT=127.0.0.1:51820\nSWG_PARAMS=\n" % DDNS,
        "vk-turn-proxy-samosvalishe-57000": "SWG_LISTEN=192.168.88.10:57000\nSWG_CONNECT=127.0.0.1:51820\nSWG_PARAMS=\n",
        "vk-turn-proxy-samosvalishe-58000": "SWG_LISTEN=192.168.88.10:58000\nSWG_PIN=10.66.66.1\nSWG_CONNECT=127.0.0.1:51820\nSWG_PARAMS=\n",
        "vk-turn-proxy-samosvalishe-60000": "SWG_LISTEN=%s:60000\nSWG_CONNECT=127.0.0.1:51820\nSWG_PARAMS=\n" % DDNS,
        "vk-turn-proxy-samosvalishe-61000": "SWG_LISTEN=10.66.66.1:61000\nSWG_PIN=10.66.66.1\nSWG_CONNECT=127.0.0.1:51820\nSWG_PARAMS=\n"}
CMDS = []
INACTIVE = {"vk-turn-proxy-samosvalishe-60000"}
def fake_host_sh(cmd, **k):
    CMDS.append(cmd)
    if cmd.startswith("systemctl is-active"):
        return types.SimpleNamespace(returncode=0, stdout="inactive\n" if any(x in cmd for x in INACTIVE) else "activating\n", stderr="")
    for svc, env in ENVS.items():
        if "cat " in cmd and svc in cmd and ".service" in cmd:
            return types.SimpleNamespace(returncode=0, stdout=UNIT, stderr="")
        if "cat " in cmd and svc in cmd and "turn.env" in cmd and "<<" not in cmd:
            return types.SimpleNamespace(returncode=0, stdout=env, stderr="")
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")
N.host_sh = fake_host_sh
N._turn_env_path = lambda svc: "/opt/vk-turn-proxy/%s/turn.env" % svc
_orig_tp = N._tp_from_unit
def tp_for(svc, unit):
    vals = dict(l.split("=", 1) for l in ENVS[svc].strip().splitlines())
    return {"service": svc, "listen": vals.get("SWG_DIAL") or vals["SWG_LISTEN"], "connect": vals["SWG_CONNECT"],
            "params": "", "bind": vals["SWG_LISTEN"], "bind_ip": vals.get("SWG_PIN", "")}
N._tp_from_unit = tp_for
_json.dump({"turn_proxies": [
    {"service": "vk-turn-proxy-samosvalishe-56000", "listen": DDNS + ":56000", "bind": DDNS + ":56000"},
    {"service": "vk-turn-proxy-samosvalishe-57000", "listen": "192.168.88.10:57000", "bind": "192.168.88.10:57000"},
    {"service": "vk-turn-proxy-samosvalishe-58000", "listen": "192.168.88.10:58000", "bind": "192.168.88.10:58000", "bind_ip": "10.66.66.1"},
    {"service": "vk-turn-proxy-samosvalishe-59000", "listen": DDNS + ":59000", "bind": DDNS + ":59000", "stopped": True},
    {"service": "vk-turn-proxy-samosvalishe-60000", "listen": DDNS + ":60000", "bind": DDNS + ":60000"},       # stopped by hand: no flag
    {"service": "vk-turn-proxy-samosvalishe-61000", "listen": "192.168.88.10:61000", "bind_ip": "10.66.66.1"}]}, open(rec, "w"))   # stale record
N.heal_turn_binds()
w = [c for c in CMDS if "<<'SWGENV'" in c]
check("the DDNS-bound proxy is re-rendered onto 0.0.0.0 and restarted",
      any("samosvalishe-56000" in c and "SWG_LISTEN=0.0.0.0:56000" in c and "SWG_DIAL=%s:56000" % DDNS in c and "systemctl restart" in c for c in w), w)
check("one whose host is on the box is left alone", not any("samosvalishe-57000" in c for c in w), w)
check("a carried Listen on is applied", any("samosvalishe-58000" in c and "SWG_LISTEN=10.66.66.1:58000" in c and "SWG_PIN=10.66.66.1" in c for c in w), w)
check("a stopped one is left alone", not any("59000" in c for c in CMDS), CMDS)
check("one stopped by hand (inactive, no flag in the record) is not started by a restart", not any("samosvalishe-60000" in c for c in w), w)
check("a render that would not change the bind does not restart (stale record, env already right)", not any("samosvalishe-61000" in c for c in w), w)
n = len(CMDS); N.heal_turn_binds()
check("once per run: a second sync does nothing", len(CMDS) == n, CMDS[n:])
N._tp_from_unit = _orig_tp

print("\n[10] every bash reader of turn.env takes the dialled host (SWG_DIAL) before the bind")
for f in ("install-node.sh", "install-host.sh", "convert.sh", "install-docker.sh"):
    lines = SRCS[f].splitlines()
    bad = [i + 1 for i, l in enumerate(lines) if "s/^SWG_LISTEN=//p" in l
           and not any("s/^SWG_DIAL=//p" in x for x in lines[max(0, i - 2):i + 1])]
    check("%s: no reader takes SWG_LISTEN alone" % f, not bad, bad)

print("\n[11] the LIVE bare → Docker convert (install-docker.sh migrate_baremetal_turns, driven) keeps what clients dial and "
      "the Listen on (1.8.9 qualification IN-3)")
import json as _json, shutil as _sh, subprocess as _sp, tempfile as _tf
_D = SRCS["install-docker.sh"]
_end = '(starts as a container on first run)"; }\n'
_a = _D.index("\ninstall_turn_binary(){") + 1; _b = _D.index(_end, _a) + len(_end)
_c = _D.index("\nmigrate_baremetal_turns(){") + 1; _d = _D.index("\n}\n", _c) + 3
_T = _tf.mkdtemp(prefix="turn-convert-")
_fn = (_D[_a:_b] + _D[_c:_d]).replace("/etc/systemd/system/", _T + "/sys/").replace("/opt/vk-turn-proxy/", _T + "/opt/vk-turn-proxy/")
_UNIT = ("[Unit]\nDescription=vk-turn-proxy (cacggghp/vk-turn-proxy) — x → 127.0.0.1:51820\n\n[Service]\n"
         "EnvironmentFile=-/opt/vk-turn-proxy/%s/turn.env\nExecStart=/opt/vk-turn-proxy/%s/server -listen ${SWG_LISTEN} -connect ${SWG_CONNECT} $SWG_PARAMS\n")
_ENVS = {   # as swg-noded's _turn_env_text writes them ([2], [7])
    "anton48-56000": "SWG_LISTEN=0.0.0.0:56000\nSWG_DIAL=%s:56000\nSWG_CONNECT=127.0.0.1:51820\nSWG_PARAMS=-wrap-srtp -wrap-key aa11\n" % DDNS,
    "anton48-56001": "SWG_LISTEN=192.168.1.50:56001\nSWG_DIAL=203.0.113.7:56001\nSWG_PIN=192.168.1.50\nSWG_CONNECT=127.0.0.1:51820\nSWG_PARAMS=-wrap-srtp -wrap-key bb22\n",
    "anton48-56002": "SWG_LISTEN=198.51.100.9:56002\nSWG_CONNECT=127.0.0.1:51820\nSWG_PARAMS=\n",          # an older file: no DIAL, no PIN
}
os.makedirs(_T + "/sys")
for _i, _e in _ENVS.items():
    os.makedirs(_T + "/opt/vk-turn-proxy/" + _i)
    open(_T + "/opt/vk-turn-proxy/%s/turn.env" % _i, "w").write(_e)
    open(_T + "/sys/vk-turn-proxy-%s.service" % _i, "w").write(_UNIT % (_i, _i))
open(_T + "/sys/vk-turn-proxy-anton48-56003.service", "w").write(   # a legacy unit: everything baked into ExecStart
    "[Unit]\nDescription=vk-turn-proxy (cacggghp/vk-turn-proxy) — x\n\n[Service]\n"
    "ExecStart=/opt/vk-turn-proxy/anton48-56003/server -listen 198.51.100.9:56003 -connect 127.0.0.1:51820 -wrap-srtp -wrap-key cc33\n")
_r = _sp.run(["bash", "-c", 'set -euo pipefail\ninfo(){ :; }; ok(){ :; }; warn(){ echo "WARN $*"; }; col(){ printf "%s" "$2"; }\n'
              'C_GREEN=""; RESET=""; MIGRATED_TURNS=""\n' + _fn + '\nmigrate_baremetal_turns >/dev/null\necho "MIGRATED=$MIGRATED_TURNS"\n'],
             capture_output=True, text=True, env=dict(os.environ, SWG_CONVERT_DIR="convert-docker", DRYRUN="false", TURN_RECORD=_T + "/rec.json"))
_rec = {}
if os.path.exists(_T + "/rec.json"):
    _rec = {t["service"]: t for t in _json.load(open(_T + "/rec.json"))["turn_proxies"]}
_g = lambda i: _rec.get("vk-turn-proxy-" + i) or {}
check("a DDNS name not on the box: the record keeps the NAME clients dial, not the 0.0.0.0 bind (no pin → no bind_ip)",
      _g("anton48-56000").get("listen") == DDNS + ":56000" and "bind_ip" not in _g("anton48-56000"),
      (_r.stdout + _r.stderr)[-300:] + str(_g("anton48-56000")))
check("a Listen on: the record keeps the dialled public address AND the pin as bind_ip (not the LAN bind as listen)",
      _g("anton48-56001").get("listen") == "203.0.113.7:56001" and _g("anton48-56001").get("bind_ip") == "192.168.1.50", _g("anton48-56001"))
check("CONTROL: an older env (no SWG_DIAL, no SWG_PIN) → listen = SWG_LISTEN, no bind_ip",
      _g("anton48-56002").get("listen") == "198.51.100.9:56002" and "bind_ip" not in _g("anton48-56002"), _g("anton48-56002"))
check("CONTROL: a legacy unit (ExecStart only) → listen from -listen, its wrap key kept, no bind_ip",
      _g("anton48-56003").get("listen") == "198.51.100.9:56003" and _g("anton48-56003").get("wrap_key") == "cc33"
      and "bind_ip" not in _g("anton48-56003"), _g("anton48-56003"))
check("…every one carried, wrap key and connect kept, and each marked for the switch's teardown",
      len(_rec) == 4 and _g("anton48-56001").get("wrap_key") == "bb22" and _g("anton48-56000").get("connect") == "127.0.0.1:51820"
      and _r.stdout.count("vk-turn-proxy-anton48-") == 4, (sorted(_rec), _r.stdout[-200:]))
_sh.rmtree(_T, ignore_errors=True)

print("\n[12] a Docker container an older build ran on an unbindable host is recreated by the update (1.8.9 qualification DN-1)")
import threading as _th
_F12 = len(FAILS)
_T = _tf.mkdtemp(prefix="turn-dn1-")
N.TURN_DOCKER = True; N.TURN_MANAGE_ON = True; N.NODE_NET = "host"; N.SWG_TURN_IMAGE = "ghcr.io/x/swg-node:latest"; N.SWG_HOST_NODE_DIR = "/x"
N.TURN_RECORD = _T + "/turn-proxy.json"; open(_T + "/server", "w").write("bin")
N._turn_bin_local = lambda svc: _T + "/server"; N._dturn_verify = lambda svc: ""
N._LOCAL_V4["at"] = -1e9; N._RESOLVED.clear(); N._BIND_RETRY.clear(); N._TURN_BIND_HEALED.clear()
_S = lambda port: "vk-turn-proxy-WINGS-N-%d" % port
_RECS = [   # (record entry, the -listen an older build gave its container — None: no container)
    ({"listen": "203.0.113.7:56200"}, "203.0.113.7:56200"),                        # 1.8.8: a public IP behind 1:1 NAT → crash loop
    ({"listen": DDNS + ":56201"}, DDNS + ":56201"),                                # 1.8.8: the router's DDNS name → crash loop
    ({"listen": "nettop.lan:56202"}, "nettop.lan:56202"),                          # 1.8.8: a name that lands on the box — works
    ({"listen": "192.168.88.10:56203"}, "192.168.88.10:56203"),                    # an address of the box — works
    ({"listen": "nettop.lan:56204"}, "0.0.0.0:56204"),                             # every address — works
    ({"listen": DDNS + ":56205"}, "10.9.9.9:56205"),                               # an address the box no longer carries (DHCP)
    ({"listen": "192.168.88.10:56206", "bind_ip": "10.66.66.1"}, "0.0.0.0:56206"),  # a Listen on carried, not applied
    ({"listen": "flaky.example:56207"}, "flaky.example:56207"),                    # its name does not resolve right now
    ({"listen": "203.0.113.7:56208", "stopped": True}, None),                      # stopped from the panel
    ({"listen": "203.0.113.7:56209"}, "?"),                                        # docker cannot describe its args
]
_json.dump({"turn_proxies": [dict(e, service=_S(56200 + i), connect="127.0.0.1:51820", params="-wrap-key ab")
                             for i, (e, _a) in enumerate(_RECS)]}, open(N.TURN_RECORD, "w"))
_BOXC = {N._turn_cname(_S(56200 + i)): {"listen": a, "made": 0} for i, (_e, a) in enumerate(_RECS) if a}
_CMDS = []
def _drun(cmd, **k):
    _CMDS.append(cmd)
    ok = lambda out="", rc=0: types.SimpleNamespace(returncode=rc, stdout=out, stderr="")
    if cmd[:2] == ["docker", "inspect"]:
        c = _BOXC.get(cmd[-1])
        if not c: return ok("", 1)
        f = cmd[3]
        if f == "{{.State.Running}}": return ok("true\n")                     # moby: Running, even in its restart back-off
        if f == "{{.Config.Image}}": return ok(N.SWG_TURN_IMAGE + "\n")       # `latest` moved: the same NAME
        if f == "{{json .Args}}":
            return ok("", 1) if c["listen"] == "?" else ok(_json.dumps(["-listen", c["listen"], "-connect", "127.0.0.1:51820"]) + "\n")
        return ok("\n")
    if cmd[:2] == ["docker", "run"]:
        a = cmd[cmd.index(N.SWG_TURN_IMAGE) + 1:]; c = _BOXC.setdefault(cmd[cmd.index("--name") + 1], {"made": 0})
        c["listen"] = a[a.index("-listen") + 1]; c["made"] += 1
        return ok("cid\n")
    if cmd[:2] == ["docker", "ps"]: return ok("\n".join(_BOXC) + "\n")
    return ok()
_save_run = N.run; N.run = _drun
for _i in range(3):
    N._dturn_reconcile()                                # three background passes (30 s apart in life)
_c = lambda port: _BOXC.get(N._turn_cname(_S(port))) or {}
_rec = lambda: {t["service"]: t for t in _json.load(open(N.TURN_RECORD))["turn_proxies"]}
check("1.8.8's container on an IP the box does not carry is recreated on every address — once in three passes",
      _c(56200).get("listen") == "0.0.0.0:56200" and _c(56200).get("made") == 1, _c(56200))
check("…one on the router's DDNS name likewise", _c(56201).get("listen") == "0.0.0.0:56201" and _c(56201).get("made") == 1, _c(56201))
check("…and the record keeps the new bind (the listen clients dial unchanged)",
      _rec()[_S(56200)].get("bind") == "0.0.0.0:56200" and _rec()[_S(56200)].get("listen") == "203.0.113.7:56200", _rec()[_S(56200)])
_rep = {t["service"]: t for t in N.load_turn_proxies()}
check("…so the node reports it (`bind`), not a running proxy with no bind",
      _rep[_S(56200)].get("bind") == "0.0.0.0:56200" and _rep[_S(56201)].get("bind") == "0.0.0.0:56201", {k: _rep[_S(56200)].get(k) for k in ("listen", "bind")})
check("a container that binds fine is left alone: a name on the box, an address of the box, every address",
      all(_c(p).get("made") == 0 for p in (56202, 56203, 56204)) and _c(56202).get("listen") == "nettop.lan:56202",
      {p: _c(p) for p in (56202, 56203, 56204)})
check("…and its record is not touched", all("bind" not in _rec()[_S(p)] for p in (56202, 56203, 56204)), [_rec()[_S(p)] for p in (56202, 56203, 56204)])
check("a bind decided earlier on an address the box no longer carries (DHCP) is recreated", _c(56205).get("listen") == "0.0.0.0:56205", _c(56205))
check("a carried Listen on the box carries is applied", _c(56206).get("listen") == "10.66.66.1:56206" and _rec()[_S(56206)].get("bind") == "10.66.66.1:56206",
      (_c(56206), _rec()[_S(56206)]))
check("a stopped proxy is not started, one docker cannot describe is left alone",
      _S(56208) not in str(_CMDS) and _c(56209).get("made") == 0, (_c(56209), [c for c in _CMDS if "56208" in str(c)][:2]))
check("a name that does not resolve right now is not judged…", _c(56207).get("made") == 0 and _S(56207) not in N._TURN_BIND_HEALED, _c(56207))
_n = sum(1 for c in _CMDS if c[3:4] == ["{{json .Args}}"] and c[-1].endswith("56207"))
N._dturn_reconcile()
check("…nor asked again on the next pass (5 minutes)", sum(1 for c in _CMDS if c[3:4] == ["{{json .Args}}"] and c[-1].endswith("56207")) == _n, _n)
DNS["flaky.example"] = ["203.0.113.60"]; N._BIND_RETRY.clear()      # five minutes on, it resolves — to the router
N._dturn_reconcile()
check("…and recreated once it resolves elsewhere", _c(56207).get("listen") == "0.0.0.0:56207" and _c(56207).get("made") == 1, _c(56207))
del DNS["flaky.example"]
_m = {k: v.get("made") for k, v in _BOXC.items()}; N._dturn_reconcile(); N._dturn_reconcile()
check("once per run: further passes recreate nothing", {k: v.get("made") for k, v in _BOXC.items()} == _m)
N._TURN_BIND_HEALED.clear(); _m = {k: v.get("made") for k, v in _BOXC.items()}; N._dturn_reconcile()
check("a restarted noded recreates nothing more (what it now binds works)", {k: v.get("made") for k, v in _BOXC.items()} == _m,
      {k: v for k, v in _BOXC.items() if v.get("made") != _m.get(k)})
N.NODE_NET = "bridge"; N._TURN_BIND_HEALED.clear(); _n = len(_CMDS)
check("bridge networking: never judged (it binds every address in our netns)",
      N._dturn_bind_stale(_S(56200), {"listen": "203.0.113.7:56200"}) == "" and len(_CMDS) == _n, _CMDS[_n:])
N.NODE_NET = "host"
_d = _rec(); _d[_S(56203)]["stopped"] = True; _d["vk-turn-proxy-WINGS-N-56299"] = {"service": "vk-turn-proxy-WINGS-N-56299", "listen": "x:1"}
_json.dump({"turn_proxies": list(_d.values())}, open(N.TURN_RECORD, "w")); open(N.TURN_RECORD + ".tmp", "w").write("apply_turn's")
N._dturn_keep_bind(_S(56203), "192.168.88.10:56203")
check("the background writer re-reads the record: a Stop and a new proxy written meanwhile are kept, one field set",
      _rec()[_S(56203)].get("stopped") is True and "vk-turn-proxy-WINGS-N-56299" in _rec() and _rec()[_S(56203)].get("bind") == "192.168.88.10:56203",
      _rec()[_S(56203)])
check("…through its own tmp file, never apply_turn's", open(N.TURN_RECORD + ".tmp").read() == "apply_turn's")
os.remove(N.TURN_RECORD + ".tmp")
class _SpyLock:   # the record lock, counting the writes made while it is held (no timing: a write outside it is not counted)
    def __init__(self): self.l, self.writes = _th.Lock(), 0
    def __enter__(self):
        self.l.acquire(); self.before = open(N.TURN_RECORD).read(); return self
    def __exit__(self, *a):
        self.writes += open(N.TURN_RECORD).read() != self.before; self.l.release()
_lk = N._TURN_REC_LOCK; N._TURN_REC_LOCK = _SpyLock()
N.apply_turn({_S(56202): {"action": "title", "title": "home"}}, None)
N._dturn_keep_bind(_S(56202), "192.168.88.10:56202")
check("both writers of the record write it under the one lock (apply_turn, the background reconcile)",
      N._TURN_REC_LOCK.writes == 2 and _rec()[_S(56202)].get("title") == "home" and _rec()[_S(56202)].get("bind") == "192.168.88.10:56202",
      (N._TURN_REC_LOCK.writes, _rec()[_S(56202)]))
N._TURN_REC_LOCK = _lk
N.run = _save_run; N.TURN_DOCKER = False
_sh.rmtree(_T, ignore_errors=True)

socket.getaddrinfo = _real_gai
print("")
if PERTURB_DN1 or PERTURB_KEEP or PERTURB_LOCK:
    _ok = len(FAILS) > _F12 and _F12 == 0
    print("PERTURB OK — %d checks went red, all in [12]" % len(FAILS) if _ok else
          "PERTURB FAILED — " + ("also red before [12]: %s" % FAILS[:_F12] if _F12 else "nothing went red in [12]"))
    sys.exit(0 if _ok else 1)
if PERTURB or PERTURB_DOCKER:
    print("PERTURB OK — %d checks went red" % len(FAILS) if FAILS else "PERTURB FAILED — nothing went red; this gate cannot see the regression")
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
