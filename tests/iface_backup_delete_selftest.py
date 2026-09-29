#!/usr/bin/env python3
"""Self-test — A DELETED INTERFACE'S KEY BACKUP GOES WITH IT; EVERY OTHER BACKUP STAYS.

swg-noded keeps a backup of each interface's identity (/var/lib/swg-noded/iface-keys/<name>.json — the PRIVATE key), so a
LOST interface can be recreated with its original key (the panel still holds its record: _missing_ifaces). A delete the
panel asks for is different: the panel has already dropped the record, its escrow and its last config, and the Delete
dialog says the server key is removed — but the backup stayed until the next re-harvest (1.8.8 qualification, round 9b:
q4's wg6, q5's wg9). An interface created later under the same name then kept the OLD backup (create keeps one that
exists), so a key restore would have put the deleted interface's key back.

Real swg-noded, loaded as a module; the agent and config persistence stubbed; a temporary backup directory.
  [1] a delete the panel asked for → that interface's backup is removed (and its .tmp), and one line says so
  [2] …a managed interface that stays, and a LOST one (not managed, backup on disk: a recreate's key source) — untouched
  [3] the agent refused the delete → the backup stays (the interface may still be there)
  [4] a delete for a name that is not managed here (already gone) → nothing touched
  [5] the same name created again → its NEW key is the backup (the old one no longer shadows it)
  [6] create_ifaces MINTS a key under a name whose older backup stayed (a delete before this fix) → the backup is
      replaced by the new interface's own, and one line says so
  [7] a RESTORE create (the key comes back from the backup) → the backup is left as it is

Run: python3 tests/iface_backup_delete_selftest.py            (0 = pass)
     --perturb   the removal taken back out → [1] and [5] red
     --perturb-create   the create's replacement taken back out → [6] red
"""
import contextlib, importlib.machinery, importlib.util, io, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SRC = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
if "--perturb" in sys.argv:
    old = '''        if drop_iface_backup(iface):
            print("keys: %s's key backup removed with it" % iface, flush=True)
'''
    assert SRC.count(old) == 1, "perturbation anchor missing — would FALSE-PASS"
    SRC = SRC.replace(old, "")
if "--perturb-create" in sys.argv:
    old = "            if not priv:\n                _new = harvest_iface_backup(_ctext, cmd)"
    assert SRC.count(old) == 1, "perturbation anchor missing — would FALSE-PASS"
    SRC = SRC.replace(old, "            if False:\n                _new = harvest_iface_backup(_ctext, cmd)")

fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "\n     " + str(detail)[:600]))
    if not ok:
        fails.append(name)


p = os.path.join(tempfile.mkdtemp(prefix="ifbak-nd-"), "swg-noded")
open(p, "w", encoding="utf-8").write(SRC)
ld = importlib.machinery.SourceFileLoader("swgnoded_ifbak", p)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_ifbak", ld))
with contextlib.suppress(SystemExit):
    ld.exec_module(N)

KD = tempfile.mkdtemp(prefix="ifbak-keys-")
N.IFACE_KEYS_DIR = KD
N._persist_config = lambda cfg: None
N._adopted_ctr_forget = lambda iface: None
AGENT = {"ok": True}
N.run_agent = lambda agent, sudo, payload: ({"ok": True} if AGENT["ok"] else {"ok": False, "error": "refused"})
N.derive_pubkey = lambda cmd, priv: "PUB-" + priv


def put(name, priv):
    N.write_iface_backup(name, {"private_key": priv, "public_key": "PUB-" + priv, "listen_port": 51820, "address": "10.1.0.1/24"})


def have(name):
    return os.path.exists(os.path.join(KD, name + ".json"))


put("wg6", "OLDKEY6"); open(os.path.join(KD, "wg6.json.tmp"), "w").write("{}")
put("wg0", "KEY0"); put("wg7", "KEY7")
cfg = {"interfaces": {"wg0": {"cmd": ["wg"], "conf": "/etc/wireguard/wg0.conf"}, "wg6": {"cmd": ["wg"], "conf": "/etc/wireguard/wg6.conf"}}}
out = io.StringIO()
with contextlib.redirect_stdout(out):
    res = N.delete_ifaces(cfg, ["wg6"], "/opt/swg-agent/swg-agent", False)
check("[1] a delete the panel asked for → its key backup is removed (and its .tmp)",
      res.get("deleted") == ["wg6"] and not have("wg6") and not os.path.exists(os.path.join(KD, "wg6.json.tmp")), (res, os.listdir(KD)))
check("[1] …and one line says so", "keys: wg6's key backup removed with it" in out.getvalue(), out.getvalue())
check("[2] a managed interface that stays, and a LOST one's backup (a recreate's key source) — untouched",
      have("wg0") and have("wg7") and (N.read_iface_backup("wg7") or {}).get("private_key") == "KEY7", os.listdir(KD))

put("wg8", "KEY8"); cfg["interfaces"]["wg8"] = {"cmd": ["wg"], "conf": "/etc/wireguard/wg8.conf"}
AGENT["ok"] = False
res = N.delete_ifaces(cfg, ["wg8"], "/opt/swg-agent/swg-agent", False)
check("[3] the agent refused the delete → the backup stays", have("wg8") and res.get("errors"), (res, os.listdir(KD)))
AGENT["ok"] = True

put("wg9", "KEY9")
res = N.delete_ifaces(cfg, ["wg9"], "/opt/swg-agent/swg-agent", False)
check("[4] a delete for a name not managed here (already gone) → nothing touched", have("wg9") and not res.get("deleted"), (res, os.listdir(KD)))

# [5] the same name created again: the create path's backup call keeps one that exists
put("wg5", "OLDKEY5"); cfg["interfaces"]["wg5"] = {"cmd": ["wg"], "conf": "/etc/wireguard/wg5.conf"}
N.delete_ifaces(cfg, ["wg5"], "/opt/swg-agent/swg-agent", False)
N.ensure_iface_backup("wg5", "[Interface]\nPrivateKey = NEWKEY5\nListenPort = 51825\nAddress = 10.5.0.1/24\n", ["wg"])
check("[5] the same name created again → its NEW key is the backup", (N.read_iface_backup("wg5") or {}).get("private_key") == "NEWKEY5",
      N.read_iface_backup("wg5"))

# [6] [7] the create path: a stubbed agent writes the conf with the key it is handed, else a minted one
CD = tempfile.mkdtemp(prefix="ifbak-conf-")
def fake_agent(agent, sudo, payload):
    if payload.get("op") != "create-iface":
        return {"ok": True}
    key = payload.get("private_key") or "MINTED-" + payload["iface"]
    c = os.path.join(CD, payload["iface"] + ".conf")
    open(c, "w").write("[Interface]\nPrivateKey = %s\nListenPort = %s\nAddress = 10.9.0.1/24\n" % (key, payload.get("listen_port") or 51900))
    return {"ok": True, "data": {"conf": c, "cmd": ["wg"]}}
N.run_agent = fake_agent
N.awg_gen_refusal = lambda iface, params: None
put("wg9", "OLDKEY9")                                         # a deleted interface's backup, left before the fix
cfg2 = {"interfaces": {}}
out = io.StringIO()
with contextlib.redirect_stdout(out):
    r = N.create_ifaces(cfg2, {"wg9": {"cmd": ["wg"], "subnet": "10.9.0.0/24", "listen_port": 51909}}, "/opt/swg-agent/swg-agent", False)
check("[6] a key MINTED under a name whose older backup stayed → the backup is the new interface's own",
      r.get("created") == ["wg9"] and (N.read_iface_backup("wg9") or {}).get("private_key") == "MINTED-wg9", (r, N.read_iface_backup("wg9")))
check("[6] …and one line says so", "keys: wg9 is a new interface — the older key backup under its name" in out.getvalue(), out.getvalue())
put("wg4", "KEY4")                                           # a lost interface's backup: the restore reads it
cfg3 = {"interfaces": {}}
r = N.create_ifaces(cfg3, {"wg4": {"cmd": ["wg"], "subnet": "10.9.0.0/24", "listen_port": 51904, "restore": True}}, "/opt/swg-agent/swg-agent", False)
check("[7] a RESTORE create (the key back from the backup) → the backup is left as it is",
      r.get("created") == ["wg4"] and (N.read_iface_backup("wg4") or {}).get("private_key") == "KEY4"
      and "PrivateKey = KEY4" in open(os.path.join(CD, "wg4.conf")).read(), (r, N.read_iface_backup("wg4")))

print("\n%s" % ("PASS — all checks" if not fails else "FAIL — %d check(s) failed" % len(fails)))
sys.exit(1 if fails else 0)
