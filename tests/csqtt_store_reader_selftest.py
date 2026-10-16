#!/usr/bin/env python3
"""Self-test: swg-noded reads a csqtt.db of either line — 2.1 (passwords bound to devices, the address on the
device row) and 2.5 (no devices: the address is the password's own `passwords.ip`).

  1  a 2.1 store: traffic + flags per password, the address through `devices`, never a private key
  2  a 2.5 store (no device_id column, no devices table): every password read, its address from passwords.ip —
     the old SELECT named device_id and failed the whole read, so a 2.5 server reported an empty store
  3  a store that ran both lines (2.1 → 2.5 adds `ip`, 2.5 never drops `device_id`/`devices`): the LINE decides —
     2.5 reads passwords.ip, 2.1 reads the device rows, never the other line's stale column
  4  a store without device_id is device-less whatever the line says
  5  csqtt_snapshot reports each password's address on both lines

Schemas are upstream's own (rust-server/model.rs DATABASE_SCHEMA of v2.1.9 and 2.5.0).

Run: python3 tests/csqtt_store_reader_selftest.py   (0 = pass)
     --perturb-line   the reader ignores the line (columns decide)      → RED 3
     --perturb-ip     the snapshot takes the address from devices only → RED 5
"""
import os, sys, sqlite3, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")

PLANTS = {
    "--perturb-line": ('            if (line or "2.1") == "2.1" and "device_id" in cols:\n',
                       '            if "device_id" in cols:\n'),
    "--perturb-ip": ('                        "ip": e.get("ip") or _dev.get("ip", ""), "online": online,',
                     '                        "ip": _dev.get("ip", ""), "online": online,'),
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def load(path, name):
    src = open(path, encoding="utf-8").read()
    if MODE:
        cut, new = PLANTS[MODE]
        # ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
        assert src.count(cut) == 1, "perturbation anchor for %s missing or not unique — would FALSE-PASS" % MODE
        src = src.replace(cut, new, 1)
    m = types.ModuleType(name)
    m.__dict__.update({"__name__": name, "__file__": path})
    exec(compile(src.split("\nif __name__ ==")[0], os.path.basename(path), "exec"), m.__dict__)
    return m

N = load(NODED, "n")

PW21 = """CREATE TABLE passwords (
    password TEXT PRIMARY KEY, device_id TEXT NOT NULL DEFAULT '', expires_at INTEGER NOT NULL DEFAULT 0,
    down_bytes INTEGER NOT NULL DEFAULT 0, up_bytes INTEGER NOT NULL DEFAULT 0, vk_hash TEXT NOT NULL DEFAULT '',
    ports TEXT NOT NULL DEFAULT '', is_deactivated INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL DEFAULT '',
    vk_hashes TEXT NOT NULL DEFAULT '', dtls_port INTEGER NOT NULL DEFAULT 0, wg_port INTEGER NOT NULL DEFAULT 0,
    local_port INTEGER NOT NULL DEFAULT 0);
CREATE TABLE devices (device_id TEXT PRIMARY KEY, ip TEXT NOT NULL, priv_key TEXT NOT NULL, pub_key TEXT NOT NULL,
    up_bytes INTEGER NOT NULL DEFAULT 0, down_bytes INTEGER NOT NULL DEFAULT 0);"""
PW25 = """CREATE TABLE passwords (
    password TEXT PRIMARY KEY, ip TEXT NOT NULL DEFAULT '', expires_at INTEGER NOT NULL DEFAULT 0,
    down_bytes INTEGER NOT NULL DEFAULT 0, up_bytes INTEGER NOT NULL DEFAULT 0, vk_hash TEXT NOT NULL DEFAULT '',
    ports TEXT NOT NULL DEFAULT '', is_deactivated INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL DEFAULT '',
    vk_hashes TEXT NOT NULL DEFAULT '', vk_token_enabled INTEGER NOT NULL DEFAULT 0, dtls_port INTEGER NOT NULL DEFAULT 0,
    wg_port INTEGER NOT NULL DEFAULT 0, local_port INTEGER NOT NULL DEFAULT 0, group_id TEXT NOT NULL DEFAULT '',
    routing_rule_id TEXT NOT NULL DEFAULT '', sub_uuid TEXT NOT NULL DEFAULT '', workers INTEGER);"""

TMP = tempfile.mkdtemp(prefix="csqtt-store-")
def store(name, schema, rows):
    d = os.path.join(TMP, name); os.makedirs(d)
    c = sqlite3.connect(os.path.join(d, "csqtt.db")); c.executescript(schema)
    for sql, args in rows:
        c.execute(sql, args)
    c.commit(); c.close()
    return d

print("1  a 2.1 store")
d21 = store("s21", PW21, [
    ("INSERT INTO passwords (password, device_id, up_bytes, down_bytes, name, vk_hash) VALUES (?,?,?,?,?,?)",
     ("pwA", "devA", 10, 20, "alice", "h1")),
    ("INSERT INTO passwords (password, is_deactivated) VALUES (?,?)", ("pwB", 1)),
    ("INSERT INTO devices VALUES (?,?,?,?,0,0)", ("devA", "10.66.68.2", "PRIVATE", "PUB")),
])
s = N._csqtt_read_store(d21, "2.1")
pa = s["passwords"].get("pwA") or {}
check("both passwords read", set(s["passwords"]) == {"pwA", "pwB"}, s)
check("traffic, flags, name", (pa.get("up_bytes"), pa.get("down_bytes"), pa.get("name"), pa.get("vk_hash"),
                               s["passwords"]["pwB"]["is_deactivated"]) == (10, 20, "alice", "h1", True), pa)
check("the address through the device row", s["devices"].get("devA", {}).get("ip") == "10.66.68.2", s["devices"])
check("never a private key", "PRIVATE" not in repr(s), s)
check("an absent line reads as 2.1", N._csqtt_read_store(d21)["devices"].get("devA", {}).get("ip") == "10.66.68.2")

print("2  a 2.5 store")
d25 = store("s25", PW25, [
    ("INSERT INTO passwords (password, ip, up_bytes, down_bytes, name) VALUES (?,?,?,?,?)",
     ("pwA", "10.66.68.3", 5, 6, "alice")),
    ("INSERT INTO passwords (password, ip) VALUES (?,?)", ("pwC", "")),
])
s = N._csqtt_read_store(d25, "2.5")
check("every password read", set(s["passwords"]) == {"pwA", "pwC"}, s)
check("the address is the password's own", s["passwords"]["pwA"].get("ip") == "10.66.68.3", s)
check("traffic + name", (s["passwords"]["pwA"]["up_bytes"], s["passwords"]["pwA"]["down_bytes"],
                         s["passwords"]["pwA"]["name"]) == (5, 6, "alice"), s)
check("no devices", s["devices"] == {}, s)

print("3  a store that ran both lines")
dboth = store("sboth", PW21 + "\nALTER TABLE passwords ADD COLUMN ip TEXT NOT NULL DEFAULT '';", [
    ("INSERT INTO passwords (password, device_id, ip) VALUES (?,?,?)", ("pwA", "devA", "10.66.68.9")),
    ("INSERT INTO devices VALUES (?,?,?,?,0,0)", ("devA", "10.66.68.2", "PRIVATE", "PUB")),
])
s5 = N._csqtt_read_store(dboth, "2.5"); s1 = N._csqtt_read_store(dboth, "2.1")
check("2.5 reads passwords.ip", s5["passwords"]["pwA"].get("ip") == "10.66.68.9" and s5["devices"] == {}, s5)
check("2.1 reads the device row, not 2.5's stale column",
      not s1["passwords"]["pwA"].get("ip") and s1["devices"].get("devA", {}).get("ip") == "10.66.68.2", s1)

print("4  no device_id column")
check("device-less whatever the line", N._csqtt_read_store(d25, "2.1")["passwords"].get("pwA", {}).get("ip") == "10.66.68.3")

print("5  the snapshot")
dirs = {"csqtt1": d21, "csqtt2": d25}
lines = {"csqtt1": "2.1", "csqtt2": "2.5"}
N._csqtt_load = lambda: {i: {"iface": i, "listen": "0.0.0.0:5600%s" % i[-1], "tun_addr": "10.66.6%s.1/24" % i[-1]} for i in dirs}
N._csqtt_dir = lambda i: dirs[i]
N._csqtt_running_line = lambda i: lines[i]
N._csqtt_cut_line = lambda i: ""
N._unit_active = lambda svc: "active"
N._csqtt_installed_ver = lambda line: ""
N._wdtt_iface_traffic = lambda i: (0, 0, 0, 0)
N._turn_own_dns = lambda d: N.OWN_DNS_UNKNOWN
N._csqtt_applied_dns = lambda i, inst: ""
N._env_listen = lambda p: ""
N.NODE_KIND = "baremetal"
try:
    snap = {e["iface"]: e for e in N.csqtt_snapshot()}
except Exception as ex:
    snap = {}
    check("csqtt_snapshot runs", False, repr(ex))
check("2.1: the device's address", snap.get("csqtt1", {}).get("passwords", {}).get("pwA", {}).get("ip") == "10.66.68.2",
      snap.get("csqtt1"))
check("2.5: the password's address", snap.get("csqtt2", {}).get("passwords", {}).get("pwA", {}).get("ip") == "10.66.68.3",
      snap.get("csqtt2"))
check("2.5: traffic reported", snap.get("csqtt2", {}).get("passwords", {}).get("pwA", {}).get("up_bytes") == 5)

print("\n" + ("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), ", ".join(FAILS))))
sys.exit(1 if FAILS else 0)
