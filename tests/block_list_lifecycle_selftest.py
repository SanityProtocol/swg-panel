#!/usr/bin/env python3
"""Block-list lifecycle on the panel — the rules that decide WHEN a list is fetched, not how it is parsed
(list_selftest.py owns the parsing).

  1. a list that has never resolved and fails backs off — a second ask inside the cooldown fetches nothing,
     and consecutive failures lengthen the cooldown
  2. the reason is kept (an HTTP code verbatim) for the Blocking tab
  3. a scheduled refresh that fails backs off too, while last-good keeps being served
  4. a union built while a member was missing is PARTIAL, and says so: its meta records the members it was made
     of, so the moment the missing member lands the union reads stale and is rebuilt to include it
  5. a union's members are refreshed on the cadence by the manifest builder (they reach no other refresh path)

Hermetic: file:// fixtures, no network. Run:  python3 tests/block_list_lifecycle_selftest.py   (exit 0 = all pass)
"""
import importlib.machinery, importlib.util, os, sys, tempfile, time, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")


def load():
    loader = importlib.machinery.SourceFileLoader("swgpanel", os.path.abspath(SERVER))
    spec = importlib.util.spec_from_loader("swgpanel", loader)
    m = importlib.util.module_from_spec(spec)
    try:
        loader.exec_module(m)
    except SystemExit:
        pass
    return m


FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def settle(m, t=10):
    end = time.time() + t
    while time.time() < end:
        with m._LIST_LOCK:
            if not m._LIST_INFLIGHT:
                return True
        time.sleep(0.02)
    return False


def main():
    m = load()
    d = tempfile.mkdtemp()
    m.LIST_DIR = os.path.join(d, "lists")
    feeds = os.path.join(d, "feeds"); os.makedirs(feeds)
    m._http_retry = lambda fn, **k: fn()                       # one try — the retry policy is not under test
    m.BLOCK_PROVIDERS["tp"] = {"label": "T", "tier": "host", "raw": "file://" + feeds + "/{id}.txt", "fmt": "plain"}
    calls = []
    real_store = m.list_store
    def counting_store(cat, tier):
        calls.append(cat)
        return real_store(cat, tier)
    m.list_store = counting_store

    print("1-2. a never-resolved failing list backs off, and keeps its reason")
    m.list_ensure("blk:tp:gone", "host"); settle(m)
    check("first ask fetches", calls.count("blk:tp:gone") == 1, calls)
    m.list_ensure("blk:tp:gone", "host"); settle(m)
    check("second ask inside the cooldown fetches nothing", calls.count("blk:tp:gone") == 1, calls)
    check("the failure is reported as failed", m.list_failed("blk:tp:gone", "host"))
    check("the reason is kept", bool(m._LIST_ERR.get("blk:tp:gone|host")), m._LIST_ERR)
    k = "blk:tp:gone|host"
    m._LIST_FAILED[k] -= m._LIST_FAIL_TTL + 1                  # the first cooldown has run out
    m.list_ensure("blk:tp:gone", "host"); settle(m)
    check("after the cooldown it tries again", calls.count("blk:tp:gone") == 2, calls)
    for _ in range(3):                                         # the node-sync manifest forces a list that has no copy yet
        m.list_ensure("blk:tp:gone", "host", force=True); settle(m)
    check("a FORCED ask inside the back-off fetches nothing either", calls.count("blk:tp:gone") == 2, calls)
    m._LIST_FAILED[k] -= m._LIST_FAIL_TTL + 1                  # one base-cooldown later is no longer enough …
    check("a second consecutive failure doubles the cooldown", m.list_failed("blk:tp:gone", "host"))
    e = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
    m._list_note_err("blk:tp:x", "host", e)
    check("an HTTP refusal is named by its code", m._LIST_ERR.get("blk:tp:x|host") == "HTTP 429", m._LIST_ERR.get("blk:tp:x|host"))

    print("3. a failed scheduled refresh backs off; last-good is served")
    open(os.path.join(feeds, "a.txt"), "w").write("a1.example.com\na2.example.com\n")
    m.list_ensure("blk:tp:a", "host"); settle(m)
    ma = m.list_meta("blk:tp:a", "host")
    check("list a resolves", ma and ma.get("n") == 2, ma)
    os.remove(os.path.join(feeds, "a.txt"))                    # upstream goes away
    n0 = calls.count("blk:tp:a")
    m.list_ensure("blk:tp:a", "host", force=True); settle(m)
    check("the due refresh is attempted", calls.count("blk:tp:a") == n0 + 1)
    check("last-good kept", m.list_meta("blk:tp:a", "host").get("v") == ma.get("v"))
    for _ in range(3):
        m.list_ensure("blk:tp:a", "host", force=True); settle(m)
    check("…and not re-attempted on every sync after it failed", calls.count("blk:tp:a") == n0 + 1, calls.count("blk:tp:a") - n0)
    open(os.path.join(feeds, "a.txt"), "w").write("a1.example.com\na2.example.com\na3.example.com\n")
    m._LIST_FAILED["blk:tp:a|host"] -= m._LIST_FAIL_MAX + 1     # the back-off has run out
    m.list_ensure("blk:tp:a", "host", force=True); settle(m)
    check("after the back-off the refresh lands", m.list_meta("blk:tp:a", "host").get("n") == 3)
    check("…and clears the failure state", all("blk:tp:a|host" not in d for d in (m._LIST_FAILED, m._LIST_FAILN, m._LIST_ERR)))

    print("4. a union is named after the lists it HOLDS — a list that lands late makes a new union a node pulls at once")
    # A node applies a CHANGED list only in its update window (04:00) and a NEW one at once, so a late list must rename.
    PS = {"block_catalog": {"categories": {"cl_t": {"label": "T", "kind": "content", "enabled_nodes": ["n1"],
          "sources": [{"provider": "tp", "list": "a"}, {"provider": "tp", "list": "b"}]}}}}
    NODE = {"ifaces": {"wg0": {"block": ["cl_t"]}}}
    SNAP = {"interfaces": {"wg0": {"meta": {"subnet": "10.0.0.0/24"}}}}
    def plan():
        ents, srcs, _ = m._resolve_iface_blocks(NODE, SNAP, PS, "sni", "n1"); settle(m)
        return [e["category"] for e in ents]
    k1 = plan()                                                # b has no list yet
    check("with b still downloading, the union is named after a alone", k1 == [m._blku_key("host", ["blk:tp:a"])], k1)
    check("…and b is being fetched meanwhile", "blk:tp:b|host" in m._LIST_FAILED or "blk:tp:b|host" in m._LIST_INFLIGHT or m.list_meta("blk:tp:b", "host"))
    meta, st = m._blku_store(k1[0], "host")
    check("that union builds from a", st == "ok" and meta.get("n") == 3, (st, meta))
    open(os.path.join(feeds, "b.txt"), "w").write("b1.example.com\na1.example.com\n")
    m._LIST_FAILED.pop("blk:tp:b|host", None); m._LIST_FAILN.pop("blk:tp:b|host", None)
    m.list_ensure("blk:tp:b", "host"); settle(m)
    check("b lands", (m.list_meta("blk:tp:b", "host") or {}).get("n") == 2)
    k2 = plan()
    check("b landing RENAMES the union (a node sees a new list and pulls it at once)", k2 and k2 != k1 and k2[0] == m._blku_key("host", ["blk:tp:a", "blk:tp:b"]), (k1, k2))
    check("the new union has no copy yet — a node cannot hold a stale one under this name", m.list_meta(k2[0], "host") is None)
    held = 0                                                   # every download slot busy (a one-core panel mid-download)
    while m._RESOLVE_SEM.acquire(blocking=False):
        held += 1
    m.list_ensure(k2[0], "host", force=True)
    built = settle(m, 5)
    for _ in range(held):
        m._RESOLVE_SEM.release()
    check("a union builds while every download slot is taken (it never queues behind downloads)", built and held > 0)
    um = m.list_meta(k2[0], "host")
    check("it holds both lists, deduped", um and um.get("n") == 4, um)
    check("…and records the versions it was made of", um.get("mv") == m._blku_member_vers(k2[0], "host"))
    body = open(m._list_path(k2[0], "host")).read().split()
    check("union body is sorted + unique", body == sorted(set(body)), body)
    open(os.path.join(feeds, "a.txt"), "w").write("a1.example.com\na2.example.com\na3.example.com\na4.example.com\n")
    m._LIST_FAILED.pop("blk:tp:a|host", None)
    m.list_ensure("blk:tp:a", "host", force=True); settle(m)
    check("a routine refresh of a keeps the name (it waits for the node's window, like every list)", plan() == k2)
    check("…and reads as stale for the hourly rebuild", m.list_meta(k2[0], "host").get("mv") != m._blku_member_vers(k2[0], "host"))

    print("5. the manifest builder refreshes union members on the cadence")
    src = open(SERVER).read()
    i = src.find("A UNION IS ONLY AS FRESH AS ITS MEMBERS")
    blk = src[i:i + 1800]
    check("members are ensured with force when due", "for _sid in (_BLKU_REG.get(_c)" in blk and "force=bool(_mm)" in blk)
    check("a union whose members refreshed is rebuilt, at most hourly", "_blku_member_vers(_c, _tier)" in blk and "> 3600" in blk)

    print("\n%s" % ("ALL PASS" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
