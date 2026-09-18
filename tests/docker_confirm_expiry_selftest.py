#!/usr/bin/env python3
"""Self-test: a docker restart-safe address change that EXPIRES while its dry-run runs is not recreated afterwards.

THE BUG (loose end D1, found by reading 2026-09-18, a deterministic path): /api/access/docker-confirm snapshots the
pending change, releases _APPLY["lock"] and waits up to 220 s for the dry-run. A change left unconfirmed expires after
DOCKER_STEP1_TTL in its own thread (_docker_step1_expire), which takes only _APPLY["lock"]: it clears the pending
change and rolls the settings back. The confirm then carried on — it parked the flip marker and asked the root helper to
recreate the container onto the NEW address, against settings that name the old one; on a failed dry-run it brought
back a Confirm card for a change that no longer existed.

  • control: a dry-run that passes, nothing expired → the container is recreated (flip queued, marker parked)
  • expired during a PASSING dry-run → refused, no flip, no marker, and the status the expiry set is left alone
  • expired during a FAILING dry-run → refused, and no card comes back for the change that expired
  • control: a dry-run that fails, nothing expired → "dry-run failed", the card stays so the operator can retry
  • expired AND saved again meanwhile (a new change, a new nonce) → the old request does not confirm the new change
    (defensive: today a Save waits for the _api_lock the confirm holds, so only the expiry thread can move meanwhile)

Hermetic: no root helper, no docker, no network. Run: python3 tests/docker_confirm_expiry_selftest.py   (0 = pass)
                                                     python3 tests/docker_confirm_expiry_selftest.py --perturb
                                                     (each guard planted out, one per run: every run must go red)
"""
import importlib.machinery, importlib.util, os, sys, tempfile, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

PERTURB = [   # one plant per run — each must turn a check red
    ("the re-check after the dry-run planted out",
     "        if not _ours:\n            return 409,", "        if False:\n            return 409,"),
    ("the re-check trusts any pending docker change (no nonce)",
     ' and hmac.compare_digest(_now_pend.get("nonce", ""), nonce)\n', "\n"),
]
if "--perturb" in sys.argv:
    src = open(SERVER, encoding="utf-8").read(); caught = 0
    for name, old, new in PERTURB:
        if src.count(old) != 1:
            print("  ??   %s: ANCHOR MISSING — the guard moved or went" % name); continue
        alt = os.path.join(tempfile.mkdtemp(prefix="dcexp-pert."), "swg-panel-server")
        open(alt, "w", encoding="utf-8").write(src.replace(old, new, 1))
        r = subprocess.run([sys.executable, os.path.abspath(__file__)], env={**os.environ, "SWG_PANEL_SERVER": alt},
                           capture_output=True, text=True, timeout=120)
        red = [l.strip()[5:] for l in r.stdout.splitlines() if l.startswith("  FAIL ")]
        print("  %-4s %-58s %s" % ("RED" if red else "GREEN", name, (red[0][:60] if red else "")))
        caught += bool(red)
    print("\n%d of %d planted regressions caught" % (caught, len(PERTURB)))
    sys.exit(0 if caught == len(PERTURB) else 1)

loader = importlib.machinery.SourceFileLoader("swgpanel", SERVER)
spec = importlib.util.spec_from_loader("swgpanel", loader)
P = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(P)
except SystemExit:
    pass

TMP = tempfile.mkdtemp(prefix="dcexp.")
DEPS = {"fleet": {}, "nodes_path": os.path.join(TMP, "nodes.json"), "roster_path": os.path.join(TMP, "users.json"),
        "panel_settings": {}}
NONCE = "n0nce-test"
PEND = {"kind": "docker-restart", "nonce": NONCE, "arm_at": 0, "deadline": 1 << 40, "url_changed": True,
        "old_url": "https://old.example:8443", "new_url": "https://new.example:8443", "tls": "letsencrypt",
        "domain": "new.example", "port": 8443, "host": "new.example", "localport": "", "old": {"url": "https://old.example:8443"}}
queued = []
P._netctl_enqueue = lambda deps, verb, args: (queued.append(verb) or "rid-%d" % len(queued))

def expire():                                            # exactly what _docker_step1_expire does to the pending change
    with P._APPLY["lock"]:
        P._APPLY["pending"] = None
    P._apply_status("idle", "the pending change expired — nothing was changed")

def confirm(dry_ok, expires, resaved=False):
    queued.clear()
    with P._APPLY["lock"]:
        P._APPLY["pending"] = dict(PEND)
    P._apply_status("docker-restart", "waiting for confirm", nonce=NONCE)
    def wait(deps, rid, timeout=180):
        if expires:
            expire()                                     # the TTL ran out while the dry-run was in flight
        if resaved:                                      # …and the operator saved the change again: a NEW nonce
            with P._APPLY["lock"]:
                P._APPLY["pending"] = dict(PEND, nonce="n0nce-second")
            P._apply_status("docker-restart", "waiting for confirm", nonce="n0nce-second")
        return (True, "") if dry_ok else (False, "the certificate could not be issued")
    P._netctl_wait = wait
    marker = P._flip_marker_path(DEPS)
    if os.path.exists(marker):
        os.unlink(marker)
    code, obj = P.api("POST", "/api/access/docker-confirm", {}, {"nonce": NONCE}, DEPS)
    return code, obj, list(queued), os.path.exists(marker), dict(P._APPLY.get("status") or {})

print("[docker-confirm] a change that expires during its dry-run")
code, obj, q, mk, st = confirm(dry_ok=True, expires=False)
check("control: dry-run passes, nothing expired → recreated (flip queued, marker parked)",
      code == 200 and obj.get("docker_recreate") and "flip" in q and mk, (code, obj, q, mk))
code, obj, q, mk, st = confirm(dry_ok=True, expires=True)
check("expired during a PASSING dry-run → refused, saying it expired", code == 409 and not obj.get("ok") and obj.get("code") == "expired", (code, obj))
check("…and nothing is recreated: no flip queued, no marker parked", "flip" not in q and not mk, (q, mk))
check("…and the status the expiry set is left alone", st.get("state") == "idle", st)
code, obj, q, mk, st = confirm(dry_ok=False, expires=True)
check("expired during a FAILING dry-run → refused, and no Confirm card comes back for it",
      code == 409 and st.get("state") == "idle" and not st.get("dryrun_failed"), (code, obj, st))
code, obj, q, mk, st = confirm(dry_ok=False, expires=False)
check("control: dry-run fails, nothing expired → 'dry-run failed' and the card stays to retry",
      code == 200 and obj.get("code") == "dryrun_failed" and st.get("state") == "docker-restart" and st.get("dryrun_failed")
      and "flip" not in q, (code, obj, st, q))

code, obj, q, mk, st = confirm(dry_ok=True, expires=True, resaved=True)
check("expired and SAVED AGAIN meanwhile → the old request does not confirm the new change (nonce)",
      code == 409 and "flip" not in q and not mk and (P._APPLY.get("pending") or {}).get("nonce") == "n0nce-second", (code, q, mk))

print("\nALL PASS" if not FAILS else "\n%d FAILED" % len(FAILS))
sys.exit(1 if FAILS else 0)
