#!/usr/bin/env python3
"""Self-test — WARP over MASQUE, the panel's half (docs/WARP-MASQUE-PLAN.md §6 P3; 1.8.12 item 17b).

  [1] the record — `warp-masque` saved with `transport` h3 (default) / h2, no dial source; `cfg_sig` signs `transport` for
      this kind only (a WireGuard WARP exit keeps its signature); WARP ↔ MASQUE is a switch that keeps the escrow, while
      SOCKS ↔ tunnel and profile ↔ WARP stay refused (F12)
  [2] T27 — a node, or its failover node, that does not list `warp-masque` is refused it on a create AND on a switch, and is
      never sent one; the sync carries `transport` on a MASQUE entry only
  [3] T22 — the escrow: a new key of the SAME account (`acct`) replaces the blob and parks nothing; another account parks the
      displaced one as before; a blob without `acct` is asked for once more of a node that seals it, never of an older one
  [4] T29 / F10 — the restore relay: a MASQUE public key (124 characters) is kept at the door; the relay ends on the row's
      `restore_ref` — the relay it acted on, one per press (a cross-kind restore reports a new key, and `restored` outlives
      the press); one the node refused rides on, saying why — in `restore_error`, or in `error` on a node with no key; a
      switch ends a relay still riding; the parked account coming back ends its offer
  [6] the fix round — a stale whole-list save never switches a kind back (only the sheet's `kind_switch` does); a failover
      node that has not reported is asked too (and refuses)
  [5] the usque mirror — the pinned bytes or nothing; a twin of swg-noded's USQ_*; the node's turn-binary door never takes a
      usque tag down the turn-fork path

Run: python3 tests/warp_masque_panel_selftest.py           (0 = pass)
     --perturb-<name>   plants one regression in a copy of the panel (see PLANTS) and expects RED
"""
import ast, hashlib, importlib.machinery, importlib.util, json, os, re, shutil, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PLANTS = {
    "--perturb-sig": ('        mat["transport"] = str(rec.get("transport") or "h3")\n', '        pass\n'),                                   # [1]
    "--perturb-f12": ('            if _was_pv and _was_pv != _pv and not (_was_pv in WARP_PROVIDERS and _pv in WARP_PROVIDERS):',
                      '            if _was_pv and "socks5" in (_was_pv, _pv) and _was_pv != _pv:'),                          # [1]
    "--perturb-carry": ('        if out.get("provider") in WARP_PROVIDERS and _old.get("producer") == "imported" \\',
                        '        if out.get("provider") == "warp" and _old.get("producer") == "imported" \\'),                  # [1]
    "--perturb-createonly": ('            if gen_snap is not None and _pv != _was_pv:', '            if gen_snap is not None and not _was_pv:'),  # [2]
    "--perturb-fo": ('                for _i, (_s, _nm) in enumerate([(gen_snap, c.get("name") or "this node")] + list(fo_snaps or ())):',
                     '                for _i, (_s, _nm) in enumerate([(gen_snap, c.get("name") or "this node")]):'),                              # [2]
    "--perturb-wire": ('                                           **({"transport": x.get("transport") or "h3"}\n'
                       '                                              if x.get("provider") == "warp-masque" else {}),\n', ''),     # [2]
    "--perturb-park": ('_same = lambda a, b: bool(a.get("acct")) and a.get("acct") == b.get("acct")', '_same = lambda a, b: False'),  # [3]
    "--perturb-acctwant": ('                               and ((x.get("key_blob") or {}).get("acct") or not _acct_ok)\n', ''),  # [3]
    "--perturb-acctold": ('                               and ((x.get("key_blob") or {}).get("acct") or not _acct_ok)\n',
                          '                               and (x.get("key_blob") or {}).get("acct")\n'),                     # [3]
    "--perturb-pub64": ('        if _pub and len(_pub) <= 200:', '        if _pub and len(_pub) <= 64:'),                        # [4]
    "--perturb-restored": (' or (_acted and bool(_have) and not _rwhy)', ''),                                                # [4]
    "--perturb-refused": (' or (_acted and bool(_have) and not _rwhy)', ' or _acted'),                                       # [4]
    # the fix round (runs/item17b-p3)
    "--perturb-ref": ('                _acted = str(_lv.get("restore_ref") or "") == \\\n',
                      '                _acted = str(_lv.get("restored") or "") == _want or "" == \\\n'),                 # [4] F1
    "--perturb-keyless": (' or (_acted and bool(_have) and not _rwhy)', ' or (_acted and not _lv.get("restore_error"))'),     # [4] F7
    "--perturb-prevpop": ('or _same(_bp, _blob) or _bp.get("landed"):', 'or _same(_bp, _blob):'),                                   # F8
    # round 2 (the operator's permit, runs/item17b-p3/round2-stop-rule.md)
    "--perturb-landedpop": ('                    _xrec["key_blob_prev"] = dict(_xrec["key_blob_prev"], landed=True)',
                            '                    _xrec.pop("key_blob_prev", None)'),                                          # verify F23
    "--perturb-staleds": ('                e = dict(e, dial_src=(known.get(eid) or {}).get("dial_src") or "")    # stale too (verify F24)\n', ''),  # F24
    "--perturb-fosay": ('                    if _no and _i and not _s:', '                    if False:'),                               # F25
    "--perturb-switchrelay": (' and not (_k.startswith("key_restore") and out["provider"] != str(_old.get("provider") or "warp"))', ''),  # F2
    "--perturb-stale": ('and _pv != _was_pv and e.get("kind_switch") is not True:', 'and False:'),                         # [6] F6
    "--perturb-foabsent": ('if _fb else [])', 'if _fbs else [])'),                                                          # [6] F14
    "--perturb-usqarm": ('        elif owner == USQ_OWNER and tag.startswith("usque-"):', '        elif False:'),               # [5]
    "--perturb-usqpin": ('        if r.returncode == 0 and os.path.isfile(tmp) and _turn_sha256_file(tmp) == want:',
                         '        if r.returncode == 0 and os.path.isfile(tmp):'),                                            # [5]
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)
FAILS = []


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


TMP = tempfile.mkdtemp(prefix="mqx-panel-")
server = SERVER
SRC = open(SERVER, encoding="utf-8").read()
if MODE:
    _a, _b = PLANTS[MODE]
    assert SRC.count(_a) == 1, "perturbation anchor for %s is missing or not unique — would FALSE-PASS" % MODE
    SRC = SRC.replace(_a, _b, 1)
    server = os.path.join(TMP, "panel-perturbed.py")
    open(server, "w", encoding="utf-8").write(SRC)
_l = importlib.machinery.SourceFileLoader("swgpanel", server)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass

NEW = {"producer": "imported", "label": "", "enabled": True, "killswitch": False}
CAN, OLD = {"exit_kinds": ["warp", "profile", "socks5", "warp-masque"]}, {"exit_kinds": ["warp", "profile", "socks5"]}
V = lambda xs, snap=CAN, prev=(), fo=(): P._validate_exits(xs, {"name": "na"}, prev=list(prev), gen_snap=snap, fo_snaps=list(fo))

# ── [1] the record ──────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] the record")
ex, err = V([dict(NEW, id="aaaa0001", provider="warp-masque", dial_src="198.51.100.4")])
check("a MASQUE exit is saved on a node that lists the kind: device wgx-<id>, HTTP/3 by default, no dial source",
      not err and ex[0]["device"] == "wgx-aaaa0001" and ex[0].get("transport") == "h3" and ex[0]["dial_src"] == "", (ex, err))
ex2, _ = V([dict(NEW, id="aaaa0001", provider="warp-masque", transport="h2")])
check("…HTTP/2 when asked, and only the two words (anything else is HTTP/3)", ex2[0]["transport"] == "h2"
      and V([dict(NEW, id="aaaa0001", provider="warp-masque", transport="quic9")])[0][0]["transport"] == "h3")
check("the transport is signed: HTTP/3 → HTTP/2 makes the node re-apply", ex[0]["cfg_sig"] != ex2[0]["cfg_sig"])
_w, _ = V([dict(NEW, id="aaaa0002", provider="warp", transport="h2")])
_old_sig = hashlib.sha256(json.dumps({"device": "wgx-aaaa0002", "provider": "warp", "licence": "", "dial_src": "", "down": False,
                                      "profile": {}}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]
check("…for this kind only: a WireGuard WARP exit carries no transport and keeps the signature it had",
      "transport" not in _w[0] and _w[0]["cfg_sig"] == _old_sig, (_w, _old_sig))
ESC = {"key_blob": {"ct": "c", "eph": "e", "mac": "m", "pub": "P1", "acct": "A1"}, "key_blob_prev": {"ct": "c0", "pub": "P0"}}
WG = dict(NEW, id="aaaa0003", provider="warp", device="wgx-aaaa0003", **ESC)
ex, err = V([dict(NEW, id="aaaa0003", provider="warp-masque", kind_switch=True)], prev=[WG])
check("WireGuard → MASQUE on one id is a switch: saved, the same device, the account's escrow kept (§4.10)",
      not err and ex[0]["provider"] == "warp-masque" and ex[0]["device"] == "wgx-aaaa0003"
      and all(ex[0].get(k) == v for k, v in ESC.items()), (ex, err))
ex, err = V([dict(NEW, id="aaaa0003", provider="warp", kind_switch=True)], prev=[dict(WG, provider="warp-masque", transport="h2")])
check("…and back: WireGuard again, the transport dropped, the escrow kept", not err and ex[0]["provider"] == "warp"
      and "transport" not in ex[0] and ex[0].get("key_blob") == ESC["key_blob"], (ex, err))
PROF = dict(NEW, id="aaaa0004", provider="profile", device="wgx-aaaa0004", profile={"private_key": "k", "address": "10.9.0.2/32"})
for frm, to in (("profile", "warp-masque"), ("profile", "warp"), ("warp-masque", "profile"), ("warp", "profile")):
    _r, _e = V([dict(NEW, id="aaaa0004", provider=to, profile_text="")], prev=[dict(PROF, provider=frm)])
    check("⚠️ %s → %s on one id is refused — the node never turns a profile into an account or back (F12)" % (frm, to),
          _r is None and "add a new exit" in str(_e), (_r, _e))
for frm, to in (("socks5", "warp-masque"), ("warp-masque", "socks5")):
    _r, _e = V([dict(NEW, id="aaaa0005", provider=to, socks_text="h.example:1080")],
               prev=[dict(NEW, id="aaaa0005", provider=frm, device="wgx-aaaa0005", socks={"host": "h", "port": 1, "pass": ""})])
    check("SOCKS ↔ WARP still refused: %s → %s" % (frm, to), _r is None and "SOCKS5" in str(_e), (_r, _e))

_RL = {"key_restore": {"eph": "e", "ct": "c", "mac": "m"}, "key_restore_pub": "P9", "key_restore_at": 1}
ex, err = V([dict(NEW, id="aaaa0003", provider="warp-masque", kind_switch=True)], prev=[dict(WG, **_RL)])
check("⚠️ a switch ends a restore relay still riding — the node takes the relay first, so it would hold the switch (review F2)",
      not err and not any(k in ex[0] for k in _RL) and ex[0].get("key_blob") == ESC["key_blob"], (ex, err))
ex, err = V([dict(NEW, id="aaaa0003", provider="warp")], prev=[dict(WG, **_RL)])
check("…while any other save keeps it", not err and all(ex[0].get(k) == v for k, v in _RL.items()), (ex, err))
print("\n[6] a stale whole-list save (review F6)")
ex, err = V([dict(NEW, id="aaaa0003", provider="warp")], prev=[dict(WG, provider="warp-masque", transport="h2")])
check("⚠️ a list saved from a view opened before the switch re-posts the old kind: the stored MASQUE exit stays MASQUE, on its HTTP/2",
      not err and ex[0]["provider"] == "warp-masque" and ex[0].get("transport") == "h2", (ex, err))
ex, err = V([dict(NEW, id="aaaa0003", provider="warp-masque")], prev=[WG])
check("…and a stored WireGuard one stays WireGuard", not err and ex[0]["provider"] == "warp" and "transport" not in ex[0], (ex, err))
ex, err = V([dict(NEW, id="aaaa0003", provider="warp-masque", dial_src="")], prev=[dict(WG, dial_src="203.0.113.10")])
check("…keeping its \"Connect from\" too — the stale view of a MASQUE exit had none (verify F24)",
      not err and ex[0]["dial_src"] == "203.0.113.10", (ex, err))

# ── [2] T27 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] an older node, or an older failover node (T27)")
_r, _e = V([dict(NEW, id="bbbb0001", provider="warp-masque")], snap=OLD)
check("a new MASQUE exit on a node that does not list the kind is refused, naming the update",
      _r is None and "1.8.12" in json.dumps(_e), _e)
_r, _e = V([dict(NEW, id="bbbb0002", provider="warp-masque", kind_switch=True)], prev=[dict(WG, id="bbbb0002", device="wgx-bbbb0002")], snap=OLD)
check("⚠️ …and so is a SWITCH of an existing WARP exit (the sync would withhold it, the node would reap the account)",
      _r is None and "1.8.12" in json.dumps(_e), _e)
_r, _e = V([dict(NEW, id="bbbb0003", provider="warp-masque")], fo=[(OLD, "nb")])
check("⚠️ a failover node that does not list it refuses the save too, by its name (its copy follows the kind)",
      _r is None and "nb" in json.dumps(_e), _e)
_r, _e = V([dict(NEW, id="bbbb0004", provider="warp-masque", kind_switch=True)], prev=[dict(WG, id="bbbb0004", device="wgx-bbbb0004")], fo=[(OLD, "nb")])
check("…on a switch as well", _r is None and "nb" in json.dumps(_e), _e)
_r, _e = V([dict(NEW, id="bbbb0005", provider="warp-masque")], prev=[dict(WG, id="bbbb0005", device="wgx-bbbb0005", provider="warp-masque")],
           snap=OLD, fo=[(OLD, "nb")])
check("…while an exit already stored as MASQUE stays savable (a rename never asks again)", not _e, _e)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


state = os.path.join(TMP, "state"); os.makedirs(os.path.join(state, "subs")); stats = os.path.join(TMP, "stats"); os.makedirs(stats)
NODES = os.path.join(state, "nodes.json")
NIDS = ("na", "nb", "nold", "nd", "nc")
_recs = {n: {"id": n, "name": n, "links": {}, "ifaces": {}} for n in NIDS}
_recs["nb"]["failover_of"] = "na"
_recs["nc"]["failover_of"] = "nd"
json.dump(_recs, open(NODES, "w"))
open(os.path.join(state, "users.json"), "w").write("{}\n")
VAULT = "dmF1bHQtcHViLWZvci10aGUtc2VsZnRlc3QtMDAwMDA="
json.dump({"ivk_enabled": True, "ivk_pub": VAULT}, open(os.path.join(state, "subs", "vault.json"), "w"))
fleet = os.path.join(TMP, "fleet.json")
json.dump({"nodes_path": NODES, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet, "w"))
PORT = free_port()
log = open(os.path.join(TMP, "panel.log"), "w+")
proc = subprocess.Popen([sys.executable, server], stdout=log, stderr=subprocess.STDOUT,
                        env={**{k: v for k, v in os.environ.items() if "proxy" not in k.lower()},
                             "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                             "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                             "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})


def req(path, data=None, token=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                               data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json",
                                        **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read(); code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read(); code = e.code
    try:
        return code, json.loads(raw or b"{}")
    except Exception:
        return code, {"raw": raw[:200]}


try:
    for _ in range(150):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
        except Exception:
            if proc.poll() is not None:
                sys.exit("panel exited: " + open(log.name).read()[-2000:])
            time.sleep(0.1)
    TOK = {n: req("/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in NIDS}
    KINDS = {"na": CAN["exit_kinds"], "nb": OLD["exit_kinds"], "nold": OLD["exit_kinds"], "nd": CAN["exit_kinds"], "nc": None}
    ROWS = {n: [] for n in NIDS}
    SEALED = {n: {} for n in NIDS}

    def sync(nid):
        s = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": {}, "exits": ROWS[nid],
             "exit_kinds": KINDS[nid], **({"exit_key_sealed": SEALED[nid]} if SEALED[nid] else {})}
        code, r = req("/api/node/sync", {"snapshot": s}, TOK[nid])
        assert code == 200, (code, r)
        return r

    def stored(nid, xid):
        return next((x for x in json.load(open(NODES))[nid].get("exits") or [] if x.get("id") == xid), {})

    def plant(nid, exits):
        n = json.load(open(NODES)); n[nid]["exits"] = exits
        with open(NODES + ".tmp", "w") as f:
            json.dump(n, f)
        os.replace(NODES + ".tmp", NODES)

    for n in ("na", "nb", "nold"):
        sync(n)
    code, r = req("/api/nodes/update", {"id": "na", "exits": [dict(NEW, id="cccc0001", provider="warp-masque")]})
    check("⚠️ through the door: na lists the kind, its failover node nb does not — refused, naming nb",
          code == 400 and "nb" in json.dumps(r), (code, r))
    KINDS["nb"] = CAN["exit_kinds"]; sync("nb")
    code, r = req("/api/nodes/update", {"id": "na", "exits": [dict(NEW, id="cccc0001", provider="warp-masque", transport="h2"),
                                                              dict(NEW, id="cccc0002", provider="warp")]})
    check("…saved once nb lists it too", code == 200 and stored("na", "cccc0001").get("transport") == "h2", (code, r))
    rep = sync("na")
    _m = next((e for e in rep.get("exits") or [] if e.get("id") == "cccc0001"), {})
    _g = next((e for e in rep.get("exits") or [] if e.get("id") == "cccc0002"), {})
    check("the sync carries a MASQUE entry's transport…", _m.get("provider") == "warp-masque" and _m.get("transport") == "h2", _m)
    check("…and none on a WireGuard WARP entry (its wire is what it was)", _g.get("provider") == "warp" and "transport" not in _g, _g)
    plant("nold", [dict(NEW, id="cccc0003", provider="warp-masque", device="wgx-cccc0003", transport="h3", cfg_sig="x")])
    rep = sync("nold")
    check("⚠️ a node that does not list the kind is never sent one", not any(e.get("id") == "cccc0003" for e in rep.get("exits") or []),
          rep.get("exits"))

    # ── [3] T22 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
    print("\n[3] the escrow keeps one account across its keys (T22)")
    B = lambda pub, acct=None, ct="ct": dict({"eph": "e", "ct": ct + pub, "mac": "m", "pub": pub, "vault": VAULT}, **({"acct": acct} if acct else {}))
    ROWS["na"] = [{"id": "cccc0001", "device": "wgx-cccc0001", "provider": "warp-masque", "public_key": "P1", "up": True}]
    plant("na", [dict(stored("na", "cccc0001"), key_blob=B("P1", "A1")), stored("na", "cccc0002")])
    ROWS["na"][0]["public_key"] = "P2"; SEALED["na"] = {"cccc0001": B("P2", "A1")}
    sync("na")
    x = stored("na", "cccc0001")
    check("a new key of the SAME account (a switch, a re-enrolment) replaces the blob and parks nothing",
          (x.get("key_blob") or {}).get("pub") == "P2" and not x.get("key_blob_prev"), x)
    ROWS["na"][0]["public_key"] = "P3"; SEALED["na"] = {"cccc0001": B("P3", "A2")}
    sync("na")
    x = stored("na", "cccc0001")
    check("another account still parks the displaced one (today's rule)", (x.get("key_blob_prev") or {}).get("pub") == "P2"
          and (x.get("key_blob") or {}).get("pub") == "P3", x)
    ROWS["na"][0]["public_key"] = "P4"; SEALED["na"] = {"cccc0001": B("P4", "A1")}
    sync("na")
    x = stored("na", "cccc0001")
    check("the parked account coming back under ANOTHER key (a restore enrolled for the other kind) ends the offer",
          (x.get("key_blob") or {}).get("pub") == "P4" and not x.get("key_blob_prev"), x)
    SEALED["na"] = {}
    plant("na", [dict(x, key_blob=B("P4")), stored("na", "cccc0002")])
    rep = sync("na")
    check("a blob sealed before `acct` existed is asked for again, of a node that seals it",
          "cccc0001" in (rep.get("exit_vault_want") or []), rep.get("exit_vault_want"))
    SEALED["na"] = {"cccc0001": B("P4", "A1", ct="re")}
    sync("na"); SEALED["na"] = {}
    rep = sync("na")
    check("…once: re-sealed with `acct`, it is not asked again", "cccc0001" not in (rep.get("exit_vault_want") or [])
          and (stored("na", "cccc0001").get("key_blob") or {}).get("acct") == "A1", (rep.get("exit_vault_want"), stored("na", "cccc0001")))
    ROWS["nold"] = [{"id": "cccc0004", "device": "wgx-cccc0004", "provider": "warp", "public_key": "Q1", "up": True}]
    plant("nold", [dict(NEW, id="cccc0004", provider="warp", device="wgx-cccc0004", cfg_sig="x", key_blob=B("Q1"))])
    rep = sync("nold")
    check("⚠️ …and never of an older node (it would be asked on every sync for ever)", "cccc0004" not in (rep.get("exit_vault_want") or []),
          rep.get("exit_vault_want"))

    # ── [4] T29 / F10 ───────────────────────────────────────────────────────────────────────────────────────────────────────
    print("\n[4] the restore relay (T29, F10)")
    MQPUB = "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE" + "A" * 88
    check("(a MASQUE public key is 124 characters)", len(MQPUB) == 124)
    code, r = req("/api/exit/restore", {"node": "na", "id": "cccc0001", "key_blob": {"eph": "e", "ct": "c", "mac": "m"}, "pub": MQPUB})
    check("⚠️ the door keeps a MASQUE key to recognise the restore by — F10", code == 200
          and stored("na", "cccc0001").get("key_restore_pub") == MQPUB, stored("na", "cccc0001"))
    REF = lambda ct: hashlib.sha256(ct.encode()).hexdigest()[:16]
    ROWS["na"][0].update(public_key="W" * 43 + "=", provider="warp", restore_error="the escrowed account could not be enrolled: x",
                         restored=MQPUB, restore_ref=REF("c"))
    rep = sync("na")
    check("a restore the node REFUSED rides on — the node says why while it rides, and acts on it only once",
          stored("na", "cccc0001").get("key_restore") and any(e.get("key_blob") for e in rep.get("exits") or []), stored("na", "cccc0001"))
    ROWS["na"][0].pop("restore_error")
    sync("na")
    check("⚠️ a cross-kind restore ends on the row's `restore_ref` though the key reported is a new one (T29)",
          not stored("na", "cccc0001").get("key_restore") and not stored("na", "cccc0001").get("key_restore_pub"), stored("na", "cccc0001"))
    req("/api/exit/restore", {"node": "na", "id": "cccc0001", "key_blob": {"eph": "e", "ct": "c2", "mac": "m"}, "pub": MQPUB})
    rep = sync("na")
    check("⚠️ pressed again, the same blob is carried to the node: `restored` from the earlier press is no ack of this one (review F1)",
          stored("na", "cccc0001").get("key_restore") and any((e.get("key_blob") or {}).get("ct") == "c2" for e in rep.get("exits") or []),
          stored("na", "cccc0001"))
    ROWS["na"][0].update(public_key="", up=False, error="the escrowed account could not be enrolled: 1006", restore_ref=REF("c2"))
    sync("na")
    check("⚠️ refused on a node with no key (the reason in `error`, no `restore_error`): it rides on, never read as applied (review F7)",
          stored("na", "cccc0001").get("key_restore"), stored("na", "cccc0001"))
    x = stored("na", "cccc0001")
    plant("na", [dict(x, key_blob=B("Y1", "A9"), key_blob_prev={"ct": "old", "pub": MQPUB}), stored("na", "cccc0002")])
    ROWS["na"][0].update(public_key="Z" * 43 + "=", up=True, error="")
    sync("na")
    x = stored("na", "cccc0001")
    check("the parked account restored under a new key: the relay ends, its offer is marked landed", not x.get("key_restore")
          and (x.get("key_blob_prev") or {}).get("landed") is True, x)
    SEALED["na"] = {"cccc0001": B("Z" * 43 + "=", "A0")}
    sync("na"); SEALED["na"] = {}
    x = stored("na", "cccc0001")
    check("⚠️ …and its re-seal ends the offer WITHOUT parking the account it replaced (review F8, verify F23)",
          not x.get("key_blob_prev") and (x.get("key_blob") or {}).get("pub") == "Z" * 43 + "=", x)

    print("\n[6] …and a failover node that has not reported (review F14)")
    sync("nd")
    code, r = req("/api/nodes/update", {"id": "nd", "exits": [dict(NEW, id="dddd0001", provider="warp-masque")]})
    check("⚠️ a failover node that has not reported cannot be shown to run the kind: refused, by its name",
          code == 400 and "nc" in json.dumps(r), (code, r))
    check("…saying it has not reported, never \"update the node\" (verify F25)", "has not reported yet" in json.dumps(r)
          and "update" not in json.dumps(r), r)
finally:
    proc.terminate()
    with __import__("contextlib").suppress(Exception):
        proc.wait(5)

# ── [5] the mirror ──────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] the usque mirror serves the pin or nothing")
NSRC = open(NODED, encoding="utf-8").read()
for k in ("USQ_TAG", "USQ_OWNER", "USQ_SHA256", "USQ_ASSET"):
    m = re.search(r"^%s = (.*(?:\n +.*)*)$" % k, NSRC, re.M)
    check("the twin of swg-noded's %s" % k, m and ast.literal_eval(m.group(1).strip()) == getattr(P, k), (m and m.group(1), getattr(P, k)))
check("the node names the relay it acted on (`restore_ref`) on both of its rows that carry `restored` — review F1",
      NSRC.count('**({"restore_ref": rec["restore_ref"]} if rec.get("restore_ref") else {})') == 2)
_door = SRC[SRC.index("    def _node_turn_binary(self, u):"):]
_door = _door[:_door.index("        if not sha or not os.path.isfile(dest):")]
check("the node's door takes any usque tag to the usque arm — the pin, or nothing — before the turn-fork path",
      'elif owner == USQ_OWNER and tag.startswith("usque-"):' in _door
      and "dest = usq_mirror_file(arch) if tag == USQ_TAG else \"\"" in _door
      and _door.index("usq_mirror_file") < _door.index("turn_sum("), _door[-600:])
P.TURN_BINS_DIR = os.path.join(TMP, "bins")
GOOD, BAD = b"\x7fELF-usque", b"\x7fELF-other"
P.USQ_SHA256 = dict(P.USQ_SHA256, amd64=hashlib.sha256(GOOD).hexdigest())
_CURL = {"v": BAD}
def _curl(argv, **k):
    open(argv[argv.index("-o") + 1], "wb").write(_CURL["v"])
    return subprocess.CompletedProcess(argv, 0, "", "")
P.subprocess.run = _curl
check("a download that is not the pin is never kept", P.usq_mirror_file("amd64") == "")
_CURL["v"] = GOOD; P._USQ_MIRROR_FAIL.clear()
d = P.usq_mirror_file("amd64")
check("the pinned one is, under its own owner/tag", d and open(d, "rb").read() == GOOD and P.USQ_TAG in d, d)
check("an arch with no build has nothing", P.usq_mirror_file("riscv64") == "")
shutil.rmtree(TMP, ignore_errors=True)

print()
if MODE:
    print(("perturbed (%s): CAUGHT (%d red)" % (MODE, len(FAILS))) if FAILS
          else "perturbed (%s): NOTHING FAILED — this gate does not test what it claims" % MODE)
    sys.exit(0 if FAILS else 1)
print(("FAILED: " + "; ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
