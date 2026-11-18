#!/usr/bin/env python3
"""Self-test — failover nodes, the panel core and awareness (docs/FAILOVER-PLAN.md §4, §8; refresh 2026-11-14; card failover-p1p2).

  [1] Census: every setting /api/nodes/update and /api/iface/update accept is classified followed, cloned or local, so a new
      field cannot silently miss; `p2p_portok_none` followed, `fast_lane` and `endpoint_host` local (refresh R5, §4.2).
  [2] The mirror pass: identity cloned once and never followed (an Adopt on A never reaches B); settings followed, `egress_ip`
      only in forward mode; a restore staged only with a vault key source; steady state writes nothing; a key mismatch, a
      stale A, a box's own interface delete nothing; a record A dropped with A reporting is dropped on B. No clone of a blob
      the vault cannot open, and the same key re-sealed on A follows (F7); a device B reports down is restored (F51); a
      3.1 interface is not restored on a box that cannot run it (F54).
  [3] `rid`: B's roster-derived reply equals A's field by field, `limits` included; the two `p2p_*` memos keep separate slots;
      a router peer's arrival from B is named A; a block category enabled on A and a list switched off on A hold on B; a
      memo slot answers only for the id it was computed for (F18); a CENSUS of B's sync: every roster-keyed read takes `_rid`,
      and a call passing `roster` with the node's own id is one of the few that are B's own (F29, F72).
  [4] The planner: the idle member walked last — no clash card, its local block rule kept, the serving member forwards and the
      exit at C keeps A's `egress_ip`; flips with A stale and clients on B, not with none; an even split is stable; the serving
      member ranks where A stood against another node's overlapping subnet (F4); the idle member names no dead torrent route
      (F13); a fleet with no pair plans exactly as the reference build.
  [5] Mesh: in full mode B is linked only where its rules ask, and a link it no longer needs is retired (F61); `auto` does
      not count mirrors (a B whose primary is gone counts); `_fleet_user_networks` skips B's copies, not B's own (F19).
  [6] The ledger: B's bytes land in the device's slot (volume included); a roster save keeps B's baseline; a pair set or
      cleared rebuilds the map; with no pair the mark is today's.
  [7] Read-only: a POST naming B is refused (an iface edit, /api/peers/targets' lists, a node edit of a followed field, an
      egress_node naming B, a padded id, a fresh recreate); the allow-list passes (rotate, update, detach, the node sheet's own
      fields, a connection card's reset, deleting B's own interface, routing/who); a list-valued id raises nothing.
  [8] Take-over and removal: targets move, `p2p_yield` follows (each port keeps its holder), A's interface dropped, B takes
      A's host (never an IP literal; the host the node reports when none is set); an interface B has no copy of stays on A
      with its peers; a take-over deletes nothing on B and refuses while any copy is in doubt (B not reporting, a device
      down, stopped, keyless, waiting for its key); node_remove(A) moves the peers of every copy B has, carries A's
      node-keyed settings to B, archives A whole and logs the take-over; keeping the peers on A waits while an interface
      runs on B alone (not one A stopped); the preview refuses a node in transfer.
  [11] The take-over table (absent / stale / held / unsure), written again here, against _fo_holds in all 4608 cases, and
      four invariants on the take-over in each: on B only an old copy is ever deleted; peers move onto what B holds and only
      that; B never ends an ordinary node keeping a copy with the peers left on A; peers land on A's current identity.
  [9] reconcile.js: A stale, B online → online, no orphans; A live too → still no orphan on A; A stale, B without the
      interface or reporting it down → unknown, no Restore; no mirrors → unchanged. R3: a WDTT device is read on the member
      its password is online on, else the one running the server, else the primary (`served`).
  [10] Real panels: with no failover node the sync reply is byte-identical to the reference build's (7c7987e8); with one,
      B's whole reply equals A's but for the node's own keys (dev_reach, p2p, limits included) and the doors work end to
      end: detach-keep with clients on B needs the typed name, a string take_over is not a take-over.

  [12] The detach door against an old copy on real panels: refused while the vault can rebuild (the Re-sync then runs),
      going on without it where it cannot (Re-sync names the vault).
  [13] A Re-sync that repairs one interface names the one whose key the vault cannot rebuild.

Run: python3 tests/failover_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED (exit 0 when caught):
     follow-key   the pass follows `public_key` (an Adopt on A reaches B)
     endpoint     the pass follows `endpoint_host`
     nokeysrc     a restore is staged without a vault key source
     stale-del    a stale A's missing record deletes B's
     rid          B's sync reads its own id, not its primary's
     limits-rid   limits_for_node is asked with B's id
     memo         the p2p memos share one slot
     arrivals     an arrival from B is not mapped to A
     idle-first   the idle member is walked first
     clash        the idle member's clash is noted
     mesh-all     a failover node is linked to every node in full mode
     auto-count   `auto` counts failover nodes
     ledger-dep   the ledger claims B's counters but not B's deployments
     ledger-mark  the ledger's mark ignores the pairs
     guard-lists  the read-only guard does not read /api/peers/targets' lists
     yield        a take-over leaves `p2p_yield` naming A
     remove       node_remove purges a primary's peers without a take-over
     served       reconcile.js reads the target's own node only
     portok       `p2p_portok_none` is not followed
     blob-follow  the same key re-sealed on A is not followed
     walk-pos     the serving member walks at its own position (not A's)
     remove-assume  removing A with no snapshot of B purges the peers instead of moving them onto B's copies
     restore-race a device B reports down is recreated while the autostart is still starting it (F77)
     stale-live   a snapshot of a B that is not reporting is trusted as certain (F87, F88)
     door-unsure  the detach door moves peers while B reports one of the interfaces down (F89)
     unsure-guard a take-over acts while an interface is in doubt (B ordinary, holding A's key, F93)
     keep-guard   keeping the peers on A deletes B's copy of an interface only B is running
     keep-stopped an interface the operator stopped on A blocks keeping the peers there (F104)
     keep-keyless a device reported up without a key counts as not running (F117 on B; on A it blocks keep, F105)
     stale-keep   a take-over keeps B's old copies and copies of interfaces A no longer has (F119, F120)
     leftover-late "A no longer has it" taken after A's held interfaces are dropped (deletes the copy the peers moved onto)
     report-condemns a key A merely reported makes B's other-key copy stale (a seeded old snapshot deletes it, F147)
     resync-partial-silent a Re-sync that repairs some rows does not name the key rows the vault cannot rebuild (F149)
     stale-deadend the take-over refuses an old copy the vault cannot rebuild (no way out, F136)
     unknown-stale A with no key makes B's copy stale (a removal deletes the copy serving the clients, F128)
     resync-unbuildable the status offers a Re-sync the vault cannot rebuild (it would delete B's copy for good, F128)
     keep-unknown A's key unknown: keeping the peers on A deletes B's running copy while A is down
     view-link    the status offers a Re-sync for a mesh link of B's named like A's interface (F124)
     log-dropped  a take-over that removes copies on B does not say so in the event (F125)
     system-copy  a mesh link of B's own named like one of A's interfaces is taken as A's copy (F116)
     absent-any   an interface in doubt is taken as absent (its peers left on A, or purged with it)
     held-loose   held without checking the key B reports
     held-down    a device B reports down is held
     carry        a take-over leaves the node-keyed settings naming A only
     strip        the read-only guard reads ids unstripped
     orphan       reconcile.js does not mark the primary's copy managed
     down-has     reconcile.js counts an interface reported down as present
     keep-confirm detach-keep cuts B's clients without the typed name
     mesh-retire  a full mesh never retires a failover node's link
     srv-ledger   the ledger leaves B's WDTT / csqtt counters unclaimed (no volume limit there)
     srv-hold-carry  a take-over leaves A's build holds behind (B swaps the binary under the moved clients)
     srv-take-host   a moved server keeps A's own IP as its listen (its links dial A)
     srv-rows-type   a server row with a list for its name raises in every sync
     srv-firewall    a server port B's declared firewall shuts reads Ready
     srv-import      B imports a leftover store's users (the roster names B)
     srv-dial-wild   a wildcard listen is taken as the host clients dial
     srv-unmanaged   B's own unrecorded servers are reported nowhere
     srv-own         an interface door naming B's server copy passes the read-only guard
     srv-absent      a csqtt copy not made yet says "waiting for the vault"
     srv-reply-rid   the sync handler builds B's WDTT reply without its primary's passwords
     upd-b        the updates sheet lists B's WDTT / csqtt, whose Update is refused there
     r2-del       a server copy whose delete is staged reads as unmanaged
     r2-domain    a take-over leaves a server listening on every address without A's domain
     r3-v6wild    a take-over carries A's domain into an IPv6 wildcard (B then binds IPv4 only)
     r2-nolisten  a take-over of a server with no listen raises half-way
     sc-served    reconcile.js reads a WDTT / csqtt device on the primary only
     sc-online    …on the first member running the server, not the one it is online on
     pf-kind      the preview's ports carry no kind (the sheet cannot word a server or a proxy)
     upd-door     the updates sheet's reinstall of B's proxy is refused
     upd-wide     B's carve-out widened to edit or stop a copy
     upd-wide2    …or to start, restart or re-key one
     fo-order     B keeps its own interface and proxy order, not A's
     ip-dial      a copy whose clients dial A's IP reads ready
     ip-dial-noreport  …or with no report of A's, every copy is condemned as having no host
     ip-dial-literal   …or with no report of A's, an IP the record proves reads ready
     ip-dial-via       a wildcard proxy's IP row does not name the interface it is dialled at
     upd-manage   the reinstall is let through on a B that cannot manage proxies
     sc-has       a WDTT device online nowhere is read on the primary, not the live member running the server
     srv-title    B's WDTT / csqtt copy does not follow A's title
     pf-dns-kind  the preview's dns warning carries no kind
     rbl-clash    the partner's subnet is still a clash at a far node that returns by link (B withheld, §4.4)
     rbl-to       both records keep `to S` (two routes for one subnet — the first installed wins)
     rbl-label-table  the label is the table's (a pair's two records share it: one label for both links)
     rbl-cap      both members are planned at a far node that never said it returns by link
     rbl-unique   two of the far node's links with one label still both-planned
     rbl-aware    both members are planned while one runs a noded that never said it knows return by link (its relay
                  would pick over the whole range)
     rbl-arr      the arrivals pass counts the pair's two links as two origins (a T15 duplicate: the far node's default
                  list stops applying to the pair's subnet)
     rbl-half     every node's relay legs carry a port half, not only a pair member's
     ex-p2p-report  the detach door's shared tail reports no pruned torrent route (F14, F17)
"""
import contextlib, importlib.machinery, importlib.util, json, os, re, shutil, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error, gzip

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
RECON = os.path.join(ROOT, "reconcile.js")
REF = "7c7987e8"                                  # origin/dev before failover: the byte-identical reference
REF_F2 = "a3104bff"                               # origin/dev before F2 (return by link, §14.7): [17]'s reference
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
FAILS = []
for _v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_v, None)


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {   # (file, anchor, replacement)
    "ex-blob": ("panel", 'FO_EXIT_FOLLOW = ("label", ', 'FO_EXIT_FOLLOW = ("key_blob", "dial_src", "label", '),
    "ex-none": ("panel", "    _fo_mirror_exits(a, w)  ", "    pass                    "),
    "ex-keep": ("panel", '            nx["profile"] = bx["profile"]', '            pass'),
    "ex-p2p": ("panel", '    out |= {str(p.get("exit_id") or "") for p in _ps', '    out |= {"" for p in _ps'),
    "ex-row": ("panel", '            st, why, more = "problem", "exit_unfilled",', '            continue; st, why, more = "problem", "exit_unfilled",'),
    "ex-door": ("panel", "    if set(old) != set(newm) or len(newm) != len(new):\n        return False", "    return True"),
    "ex-tolerate": ("panel", '                elif c.get("failover_of"):\n                    # a failover node', '                elif False:\n                    # a failover node'),
    "ex-wire": ("panel", "and not fo_exit_unfilled(x)    # a failover node's exit to fill", "and True    # a failover node's exit to fill"),
    "ex-escrow": ("panel", "        nx.update({k: bx[k] for k in _EXIT_ESCROW_KEYS if k in bx})", "        pass"),
    "ex-park": ("panel", '            px = {**bx, "enabled": False}', '            px = dict(bx)'),
    "ex-orphan": ("panel", 'and bx.get("profile") and xid in a_ids:', 'and bx.get("profile"):'),
    "ex-release": ("panel", "    xs = [x for x in (b.get(\"exits\") or []) if not fo_exit_unfilled(x)]", "    xs = list(b.get(\"exits\") or [])"),
    "ex-resolve": ("panel", 'or _x.get("enabled") is False or fo_exit_unfilled(_x):', 'or _x.get("enabled") is False:'),
    "ex-preflight": ("panel", "    _fo_mirror_exits(a, _s)\n", ""),
    "ex-escrow-kind": ("panel", 'if nx.get("provider", "warp") == "warp" and bx.get("provider", "warp") == "warp":', 'if True:'),
    "ex-fill-warn": ("panel", '    warn["exit_fill"] = [str(x.get("id"))', '    warn["exit_fill"] = [] and [str(x.get("id"))'),
    "rbl-clash": ("panel", "                    and not _rbl_both(nid, e[1], s, e[0], P)), None)", "), None)"),
    "rbl-to": ("panel", "                if o == _quiet:\n                    e[\"to\"] = False", "                if False:\n                    e[\"to\"] = False"),
    "rbl-label-table": ("panel", '                e["ret"] = _rbl_lab(P, o)', '                e["ret"] = e["table"] - 6999'),
    "rbl-cap": ("panel", '            _rbl_memo[(P, nid, o)] = bool(isinstance(_sr, dict) and _sr.get("rbl") and _rbl_lab(P, nid) and _rbl_lab(P, o)',
                '            _rbl_memo[(P, nid, o)] = bool(isinstance(_sr, dict) and _rbl_lab(P, nid) and _rbl_lab(P, o)'),
    "rbl-aware": ("panel", "                                          and _rbl_aware(nid) and _rbl_aware(o))", ")"),
    "rbl-arr": ("panel", '''            _via.setdefault(e["subnet"], set()).add(("n", failover_rid(nodes, _o)) if _o else ("i", e["via_iface"]))''',
                '''            _via.setdefault(e["subnet"], set()).add(("i", e["via_iface"]))'''),
    "rbl-unique": ("panel", "    return {n: L for n, L in raw.items() if L and seen[L] == 1}", "    return {n: L for n, L in raw.items() if L}"),
    "rbl-half": ("panel", '    _half = ({"half": 2 if failover_rid(nodes, nid) != nid else 1} if nid in failover_partners(nodes) else {})',
                 '    _half = {"half": 2 if failover_rid(nodes, nid) != nid else 1}'),
    "ex-p2p-report": ("panel", "        _report_p2p_pruned(deps, _p2p_pr)\n        if not take:\n", "        if not take:\n"),
    "ex-rowid": ("panel", '        rows.append({"iface": xid, "kind": "exit",', '        rows.append({"iface": str(ax.get("label") or xid), "kind": "exit",'),
    "follow-key": ("panel", '''FO_IF_FOLLOW = ("listen_port", ''', '''FO_IF_FOLLOW = ("public_key", "listen_port", '''),
    "endpoint": ("panel", '''FO_IF_FOLLOW = ("listen_port", ''', '''FO_IF_FOLLOW = ("endpoint_host", "listen_port", '''),
    "nokeysrc": ("panel", '                or _iface_key_source(bov, None, ivk) != "vault"):\n            return\n        # A device B reports DOWN',
                      '                or False):\n            return\n        # A device B reports DOWN'),
    "stale-del": ("panel", '        if alive:\n            arep = kd.a_reports(asnap)',
                      '        if True:\n            arep = kd.a_reports(asnap)'),
    "rid": ("panel", '''        _rid = failover_rid(nodes, nid)
        # The shared parsed roster (P2): READ-ONLY.''', '''        _rid = nid
        # The shared parsed roster (P2): READ-ONLY.'''),
    "limits-rid": ("panel", '''(_lims := limits_for_node(roster, _rid, desired, snap))''', '''(_lims := limits_for_node(roster, nid, desired, snap))'''),
    "memo": ("panel", '''    slot = node_id if slot is None else slot
    hit = _P2P_FWD.get(slot)''', '''    slot = node_id
    hit = _P2P_FWD.get(slot)'''),
    "arrivals": ("panel", "            os_ = {failover_rid(nodes, by_dev[v]) if nodes else by_dev[v] for v in vs}",
                 "            os_ = {by_dev[v] for v in vs}"),
    "idle-first": ("panel", '''key=lambda kv: (kv[0] in idle, _pos[failover_rid(nodes, kv[0])])''',
                   '''key=lambda kv: (kv[0] not in idle, _pos[failover_rid(nodes, kv[0])])'''),
    "clash": ("panel", '''        if nid in idle:
            return
        slot(nid).setdefault("_clash", {})''', '''        slot(nid).setdefault("_clash", {})'''),
    "mesh-all": ("panel", '''        if _fo:
            _fneed = mesh_need(nodes, deps)''', '''        if False:
            _fneed = mesh_need(nodes, deps)'''),
    "auto-count": ("panel", '''    n = len(nodes) - len(failover_members(nodes))''', '''    n = len(nodes)'''),
    "ledger-dep": ("panel", '''                    deploys.add((fo[t["node"]], t["iface"], pid))''', '''                    pass'''),
    "ledger-mark": ("panel", '''        if pairs:                                              # …or a failover pair''', '''        if False:                                              # …or a failover pair'''),
    "guard-lists": ("panel", '''    for k in ("targets", "base", "add", "address", "remove"):''', '''    for k in ("targets",):'''),
    "yield": ("panel", '''        if aid in ys:
            ys = (ys | {bid})''', '''        if False:
            ys = (ys | {bid})'''),
    "remove": ("panel", '''    _fo_b = failover_pairs(nodes).get(nid)
    _fo_snaps''', '''    _fo_b = None
    _fo_snaps'''),
    "served": ("recon", '''      const mb = cfg.mirrors ? cfg.mirrors[t.node] : null;''', '''      const mb = null;'''),
    "portok": ("panel", '''"p2p_portok", "p2p_portok_none", "catalog_cats",''', '''"p2p_portok", "catalog_cats",'''),
    "blob-follow": ("panel", '        if src.get("key_blob") and bov.get("public_key") == src.get("public_key") and bov.get("key_blob") != src["key_blob"]:',
                      '        if False:'),
    "walk-pos": ("panel", '''key=lambda kv: (kv[0] in idle, _pos[failover_rid(nodes, kv[0])])''', '''key=lambda kv: (kv[0] in idle, _pos[kv[0]])'''),
    "remove-assume": ("panel", '''_fo_live(deps.get("node_seen"), _fo_b), assume=True), _fo_snaps)''', '''_fo_live(deps.get("node_seen"), _fo_b), assume=False), _fo_snaps)'''),
    "unsure-guard": ("panel", '''    if cls[2]:
        raise ValueError''', '''    if False:
        raise ValueError'''),
    "keep-guard": ("panel", '''        if _only_b:''', '''        if False:'''),
    "keep-stopped": ("panel", '''    if rep.get("stopped"):
        return own''', '''    if rep.get("stopped"):
        return False'''),
    "keep-keyless": ("panel", '''((rep.get("meta") or {}).get("public_key") or "") in ("", key)''',
                     '''((rep.get("meta") or {}).get("public_key") or "") == key'''),
    "stale-keep": ("panel", "    for n in old:                                     # never A's current identity: an old copy, or one A no longer has\n",
                      '    for n in ():\n'),
    "leftover-late": ("panel", "    for n in old:                                     # never A's current identity: an old copy, or one A no longer has\n",
                      "    old = sorted(set(cls[3]) | set(_fo_leftovers(nodes, aid, bid)))   # PLANT: taken AFTER A's held copies are dropped\n    for n in old:\n"),
    "stale-deadend": ("panel", ''' if n in _srcs and _srcs[n][0].rebuildable(_srcs[n][1], _ivk)]''', ''']'''),
    "report-condemns": ("panel", '''    return "current" if reported and bk == reported else "unknown"''',
                        '''    return "current" if reported and bk == reported else ("stale" if reported else "unknown")'''),
    "resync-partial-silent": ("panel", '''        return 200, {"ok": True, "data": {"id": bid, "ifaces": bad, "vault_needed": _nv}}''',
                              '''        return 200, {"ok": True, "data": {"id": bid, "ifaces": bad}}'''),
    "unknown-stale": ("panel", '''    if blessed:
        return "current" if bk == blessed else "stale"''', '''    if True:
        return "current" if bk == blessed else "stale"'''),
    "resync-unbuildable": ("panel", '            more = {"resync": True} if r["kind"].rebuildable(r["src"], ivk) else {}',
                      '            more = {"resync": True}'),
    "fo-order": ("panel", ''',\n                  "iface_order", "turn_order")''', ''')'''),
    "ip-dial": ("panel", '''if _fo_dials_ip(_h) and (_h or isinstance(snaps[aid], dict)):''', '''if False:'''),
    "ip-dial-noreport": ("panel", '''if _fo_dials_ip(_h) and (_h or isinstance(snaps[aid], dict)):''', '''if _fo_dials_ip(_h):'''),
    "ip-dial-literal": ("panel", '''if _fo_dials_ip(_h) and (_h or isinstance(snaps[aid], dict)):''', '''if _fo_dials_ip(_h) and isinstance(snaps[aid], dict):'''),
    "ip-dial-via": ("panel", '''                if _via:                                         # the host is that interface's: its endpoint is the fix (F8)''',
                    '''                if False:'''),
    "keep-unknown": ("panel", '        if r["cc"] not in ("current", "unknown"):', '        if r["cc"] != "current":'),
    "view-link": ("panel", '''        elif cc == "link":''', '''        elif False:'''),
    "log-dropped": ("panel", '    if left and dropped:\n        _dk = "took over {v1}; left on {v2}: {v3}; old copies removed: {v4}"\n    elif left:\n        _dk = "took over {v1}; left on {v2}: {v3}"\n    elif dropped:\n        _dk = "took over {v1}; old copies removed: {v4}"\n    else:\n        _dk = "took over {v1}"',
                    '    if left:\n        _dk = "took over {v1}; left on {v2}: {v3}"\n    else:\n        _dk = "took over {v1}"'),
    "system-copy": ("panel", '''    if bov.get("system"):
        return "link"''', '''    if False:
        return "link"'''),
    "absent-any": ("panel", '''            (held if assume else unsure).append(n)''', '''            absent.append(n)'''),
    "held-loose": ("panel", '                and ((rep.get("meta") or {}).get("public_key") or "") == key)',
                      '                )'),
    "held-down": ("panel", 'rep is not None and not rep.get("down") and not rep.get("stopped")',
                      'rep is not None and not rep.get("stopped")'),
    "plan-gone": ("panel", '    held = [n for n in held if n in srcs]              # a name A', '    held = list(held)              # a name A'),
    "stale-live": ("panel", '''    bsnap = (snaps or {}).get(bid) if live else None''', '''    bsnap = (snaps or {}).get(bid)'''),
    "door-unsure": ("panel", '''        if take and cls[2]:''', '''        if False:'''),
    "restore-race": ("panel", '''and int(((w.get("iface_autostart") or {}).get(n) or {}).get("n") or 0) >= len(IFACE_AUTOSTART_GAPS)):''',
                     '''):'''),
    "carry": ("panel", '''        if isinstance(v, list) and aid in v and bid not in v:''', '''        if False:'''),
    "strip": ("panel", '''    hit = sorted({_fo_str(n) for n in named} & set(fo))''', '''    hit = sorted({n for n in named if isinstance(n, str)} & set(fo))'''),
    "orphan": ("recon", '''managed[t.node + "|" + t.iface + "|" + pubkey] = managed[mb + "|" + t.iface + "|" + pubkey] = true;''',
               '''managed[mb + "|" + t.iface + "|" + pubkey] = true;'''),
    "down-has": ("recon", '''[t.iface]) && !ifDown[n + "|" + t.iface];''', '''[t.iface]);'''),
    # R3: a WDTT / csqtt device is read on the member serving it; the preview names kinds; the updates sheet and its door
    "sc-served": ("recon", '''          ssn = pair.find(onl) || pair.find(has) || t.node;''', '''          ssn = t.node;'''),
    "sc-online": ("recon", '''          ssn = pair.find(onl) || pair.find(has) || t.node;''', '''          ssn = pair.find(has) || t.node;'''),
    "pf-kind": ("panel", '''        warn["ports"] += [{"iface": n, "kind": k.kind, "port": _p} for _p in k.ports(src)]''',
                '''        warn["ports"] += [{"iface": n, "port": _p} for _p in k.ports(src)]'''),
    "upd-door": ("panel", '''in _FoTurn().b(None, (snaps or {}).get(b)))):''', '''in ())):'''),
    "upd-wide": ("panel", '''            or (path == "/api/turn/reinstall" and _fo_str(body.get("service")) in _FoTurn().b(''',
                 '''            or (path in ("/api/turn/reinstall", "/api/turn/manage", "/api/turn/stop") and _fo_str(body.get("service")) in _FoTurn().b('''),
    "upd-wide2": ("panel", '''            or (path == "/api/turn/reinstall" and _fo_str(body.get("service")) in _FoTurn().b(''',
                  '''            or (path in ("/api/turn/reinstall", "/api/turn/start", "/api/turn/restart", "/api/turn/rotate") and _fo_str(body.get("service")) in _FoTurn().b('''),
    "upd-manage": ("panel", '''_FoTurn().b(None, (snaps or {}).get(b)))):''', '''_FoTurn._rows((snaps or {}).get(b)))):'''),
    "sc-has": ("recon", '''          ssn = pair.find(onl) || pair.find(has) || t.node;''', '''          ssn = pair.find(onl) || t.node;'''),
    "srv-title": ("panel", '''"web_port",\n                  "title")''', '''"web_port")'''),
    "pf-dns-kind": ("panel", '''warn["dns"].append({"iface": n, "kind": k.kind, "host": host})''', '''warn["dns"].append({"iface": n, "host": host})'''),
    "keep-confirm": ("panel", '''        cut = bid if not take else aid                 # the member whose clients this cuts off''',
                     '''        cut = aid'''),
    "mesh-retire": ("panel", '''            need = {frozenset(ab) for ab in pairs}''', '''            pass'''),
    # copies by kind, R1: the turn family's servers (§12)
    'srv-never': ("panel", 'FO_TURN_FOLLOW = ("fork", "listen", ',
                      'FO_TURN_FOLLOW = ("password", "fork", "listen", '),
    'srv-rid-wdtt': ("panel", '    for _k, p in _peers_on(roster, rid):\n        if not isinstance(p, dict) or not p.get("wdtt_password"):',
                      '    for _k, p in _peers_on(roster, node_id):\n        if not isinstance(p, dict) or not p.get("wdtt_password"):'),
    'srv-rid-csqtt': ("panel", '    for pid, p in _peers_on(roster, rid):\n        if not isinstance(p, dict) or not p.get("csqtt_password"):',
                      '    for pid, p in _peers_on(roster, node_id):\n        if not isinstance(p, dict) or not p.get("csqtt_password"):'),
    'srv-online': ("panel", '        return sum(1 for d in pws if isinstance(d, dict)',
                      '        return 0 and sum(1 for d in pws if isinstance(d, dict)'),
    'srv-held-await': ("panel", '                and not rep.get("await_restore") and (not self.identity or',
                      '                and (not self.identity or'),
    'srv-delete-wait': ("panel", '        return n not in (w.get(self.fam + "_delete") or {}) and self.rebuildable(src, ivk)',
                      '        return self.rebuildable(src, ivk)'),
    'srv-door': ("panel", '                          "/api/wdtt/restore"))',
                      '                          ))'),
    'srv-target': ("panel", '        return (_is_wdtt_target if self.fam == "wdtt" else _is_csqtt_target)(t)',
                      '        return False'),
    'srv-want': ("panel", '            for _w in ((snap.get("wdtt") or []) if _rid == nid else ()):',
                      '            for _w in (snap.get("wdtt") or []):'),
    'srv-rebuild': ("panel", '        if not self.identity:\n            return True\n        blessed = self.bkey(src)',
                      '        if True:\n            return True\n        blessed = self.bkey(src)'),
    'srv-ports': ("panel", '            if 0 < p <= 65535:\n                out.append(p)\n        return out',
                      '            if False:\n                out.append(p)\n        return out'),
    # copies by kind, R2: the turn proxies (§12)
    'tp-bind': ("panel", 'for k in FO_TP_FOLLOW}, "at": now_}', 'for k in FO_TP_FOLLOW}, "bind_ip": src.get("bind_ip") or "", "at": now_}'),
    'tp-pending': ("panel", 'bool(bs) and _turn_can_manage(bs) and n not in (w.get("turn") or {})', 'bool(bs) and _turn_can_manage(bs)'),
    'tp-capable': ("panel", '    return snap.get("turn_manage") is not False and snap.get("turn_capable") is not False', '    return True'),
    'tp-retry': ("panel", '_FO_TP_TRIED.get((w.get("id"), n), 0) >= FO_TP_RETRY', '_FO_TP_TRIED.get((w.get("id"), n), 0) >= 0'),
    'tp-installing': ("panel", 'if _TURN_SVC_RE.match(n) and not (x.get("installing") and "params" not in x)', 'if _TURN_SVC_RE.match(n)'),
    'tp-updating': ("panel", 'if _TURN_SVC_RE.match(n) and not (x.get("installing") and "params" not in x)',
                    'if _TURN_SVC_RE.match(n) and not x.get("installing")'),
    'tp-own-manage': ("panel", '    if not isinstance(bsnap, dict) or not _turn_can_manage(bsnap):\n        return set()', ''),
    'tp-flap': ("panel", ' or rep.get("running") is False or rep.get("flapping"):', ' or rep.get("running") is False:'),
    'tp-firewall': ("panel", 'for lp in self.ports(r["src"]):               # as an interface\'s: B\'s declared firewall shuts what clients dial (F7)',
                    'for lp in ():'),
    'tp-own-live': ("panel", '    if not _fo_live(seen, aid, now) or not isinstance(asnap, dict)', '    if not isinstance(asnap, dict)'),
    'tp-own-pending': ("panel", ' - set((nodes.get(aid) or {}).get("turn") or {})\n', '\n'),
    'tp-own-del': ("panel", '                if (_bt.get(n) or {}).get("action") != "delete")', '                )'),
    'hostport-ascii': ("panel", 'not (port.isascii() and port.isdigit() and len(port) <= 5)', 'not port.isdigit()'),
    'pf-proxies-only': ("panel", '    if not ifs and not [x for x in _servers if x[0].moves]:', '    if not ifs and not _servers:'),
    'tp-norm': ("panel", '        diff = [k for k in FO_TP_FOLLOW if _fo_norm(src.get(k)) != _fo_norm(bov.get(k))]',
                '        diff = [k for k in FO_TP_FOLLOW if (src.get(k) or "") != (bov.get(k) or "")]'),
    'tp-title': ("panel", '        if diff == ["title"]:', '        if False:'),
    'tp-wait': ("panel", '        if bov.get("installing") or n in (w.get("turn") or {}):', '        if bov.get("installing"):'),
    'tp-moves': ("panel", '    kind, identity, moves = "turn", False, False', '    kind, identity, moves = "turn", False, True'),
    'tp-door': ("panel", '(path == "/api/turn/delete" and _fo_str(body.get("service")) in _fo_turn_b_own(nodes, snaps, seen, fo[b], b))',
                '(path == "/api/turn/delete")'),
    'tp-unmanaged': ("panel", ' or not isinstance(asnap, dict) or not isinstance(asnap.get("turn_proxies"), list):\n        return set()',
                     ' or not isinstance(asnap, dict):\n        return set()'),
    'tp-dial': ("panel", '        if host:\n            return host\n        i = self.dial_via(', '        if True:\n            return host\n        i = self.dial_via('),
    'tp-absent': ("panel", '            return "problem", "no_turn", {}', '            return "syncing", "creating", {}'),
    'tp-hold': ("panel", '            if _turn_hold_get(nid, "fork:" + fork):      # operator rolled',
                '            if _turn_hold_get(failover_rid(nodes, nid), "fork:" + fork):      # operator rolled'),
    'tp-ports': ("panel", '        return [p] if isinstance(p, int) and 0 < p <= 65535 else []', '        return []'),
    'srv-subnet': ("panel", ' or nm.split(" (raw)")[0] in _copies:', ':'),
    'srv-stale-door': ("panel", '        _rebuild = [n for n in (cls[3] if take else ()) if n in _srcs and _srcs[n][0].rebuildable(_srcs[n][1], _ivk)]',
                      '        _rebuild = [n for n in (cls[3] if take else ()) if _fo_rebuildable((nodes[aid].get("ifaces") or {}).get(n), _ivk)]'),
    # R1 card round 1 (review F1–F35)
    'srv-ledger': ("panel", '                if fo and t["node"] in fo:', '                if fo and t["node"] in fo and not _is_self_contained_target(t):'),
    'srv-hold-carry': ("panel", '        if add:\n            d.update(add)', '        if False:\n            d.update(add)'),
    'srv-take-host': ("panel", '                bov["listen"] = "0.0.0.0:%d" % p          # of B', '                pass  # of B'),
    'srv-rows-type': ("panel", 'if isinstance(x, dict) and isinstance(x.get("iface"), str) and x["iface"]}', 'if isinstance(x, dict) and x.get("iface")}'),
    'srv-firewall': ("panel", '            if ctx["ranges"] and not any(x <= lp <= y for x, y in ctx["ranges"]):\n                return "problem", "firewall", {"port": lp}\n        return "ready", "", {}\n\n    def absent',
                     '            if False:\n                return "problem", "firewall", {"port": lp}\n        return "ready", "", {}\n\n    def absent'),
    'srv-import': ("panel", 'for _wifn, _wsn in (_wsnap.items() if _rid == nid else ()):', 'for _wifn, _wsn in (_wsnap.items()):'),
    'srv-dial-wild': ("panel", '        return (_fp_bind_host(src.get("listen") or "") or', '        return (_hostport_split(src.get("listen") or "")[0] or'),
    'srv-unmanaged': ("panel", '            um |= {n for n in k.a_reports(bsnap) if n not in k.b(b) and n not in (b.get(k.fam + "_delete") or {})}', '            pass'),
    'srv-own': ("panel", 'not in _fo_srcs(nodes[fo[b]], None)      # B', 'not in _fo_user_ifaces(nodes[fo[b]])      # B'),
    'srv-absent': ("panel", 'return _FoKind.absent(self, ctx) if self.identity else ("syncing", "creating", {})', 'return _FoKind.absent(self, ctx)'),
    'r2-del': ("panel", ' and n not in (b.get(k.fam + "_delete") or {})}', '}'),
    'r2-domain': ("panel", '            bov["listen"] = "%s:%d" % (host, p)', '            pass'),
    'r3-v6wild': ("panel", ' and h in ("", "0.0.0.0", "*"):', ':'),
    'r2-nolisten': ("panel", '        if not p:\n            return\n        if _fp_bind_host(bov["listen"]):', '        if _fp_bind_host(bov["listen"]):'),
    'upd-b': ("panel", '''        if kind != "turn" and nid in _fob:''', '''        if False:'''),
    'srv-reply-rid': ("panel", '_wdtt_des = _wdtt_reply(roster, nodes, nid, _fb_vk, _rid)', '_wdtt_des = _wdtt_reply(roster, nodes, nid, _fb_vk)'),
}

TMP = tempfile.mkdtemp(prefix="swg-failover-")
SRC = open(PANEL, encoding="utf-8").read()
RSRC = open(RECON, encoding="utf-8").read()
if PLANT:
    f, cut, new = PLANTS[PLANT]
    if f == "panel":
        assert SRC.count(cut) == 1, "plant anchor for %s missing or not unique — would FALSE-PASS" % PLANT
        SRC = SRC.replace(cut, new, 1)
    else:
        assert RSRC.count(cut) == 1, "plant anchor for %s missing or not unique — would FALSE-PASS" % PLANT
        RSRC = RSRC.replace(cut, new, 1)
NEW = os.path.join(TMP, "swg-panel-server")
open(NEW, "w", encoding="utf-8").write(SRC)
os.symlink(os.path.join(ROOT, "js"), os.path.join(TMP, "js"))   # reconcile.js imports ./js/i18n.js
NEWR = os.path.join(TMP, "reconcile.mjs")
open(NEWR, "w", encoding="utf-8").write(RSRC)


def load(path, name):
    ld = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m


P = load(NEW, "swgpanel_failover")
IVK = "V" * 43 + "="
P._current_ivk_pub = lambda deps: IVK
KA, KB, KX = "A" * 43 + "=", "B" * 43 + "=", "X" * 43 + "="
PK = ["%s" % (chr(ord("a") + i) * 43 + "=") for i in range(8)]
NOW = 1_800_000_000




_REFS = {}


def _ref(rev, tag):
    """A reference build's panel as a module (loaded once per revision, on first use)."""
    if rev not in _REFS:
        rp = os.path.join(TMP, "ref-%s-swg-panel-server" % tag)
        open(rp, "wb").write(subprocess.run(["git", "-C", ROOT, "show", rev + ":swg-panel-server"], capture_output=True, check=True).stdout)
        _REFS[rev] = load(rp, "swgpanel_failover_ref_" + tag)
    return _REFS[rev]


REFP = lambda: _ref(REF, "p")                       # the reference build
REFF2 = lambda: _ref(REF_F2, "f2")                  # the build before F2


def guarded(name, fn):
    try:
        fn()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check(name + " ran", False, repr(e))


def a_iface(**kw):
    ov = {"public_key": KA, "key_blob": {"pub": KA, "ct": "c", "eph": "e", "mac": "m", "vault": IVK},
          "_lastcfg": {"subnet": "10.8.0.0/24", "listen_port": 443, "address": "10.8.0.1/24"},
          "listen_port": 443, "mtu": 1380, "awg_params": {"Jc": 4, "Jmin": 40, "Jmax": 70},
          "endpoint_host": "vpn.example.com", "block": ["ads"], "egress_mode": "forward", "egress_node": "nc",
          "egress_ip": "7.7.7.7", "_synced": {"listen_port": 443}}
    ov.update(kw)
    return ov


def fleet():
    return {"na": {"id": "na", "name": "hel-1", "endpoint_host": "a.example.com", "routing_mode": "kernel",
                   "p2p_portok_none": True, "fast_lane": 50, "ifaces": {"awg0": a_iface()}, "links": {}},
            "nb": {"id": "nb", "name": "hel-2", "failover_of": "na", "endpoint_host": "", "ifaces": {}, "links": {}},
            "nc": {"id": "nc", "name": "exit", "ifaces": {}, "links": {}}}


def snap_iface(key=KA, subnet="10.8.0.0/24", peers=(), port=443):
    return {"meta": {"public_key": key, "subnet": subnet, "listen_port": port, "address": "10.8.0.1/24"},
            "peers": [{"public_key": k, "online": on, "rx_bytes": rx, "tx_bytes": tx} for k, on, rx, tx in peers]}


DEPS = {"panel_settings": {}, "roster_path": os.path.join(TMP, "users.json")}


# ── [1] census ───────────────────────────────────────────────────────────────────────────────────────────────────────
LOCAL_NODE = {"id", "name", "color", "endpoint_host", "endpoint_hosts", "default_egress_ip", "panel_ip", "mesh_egress_ip",
              "log_mb", "relay", "fast_lane", "mesh_subnet", "mesh_port", "mesh_prefix", "iface_order", "turn_order",
              "ignore_ifaces", "links", "link_keep", "exits", "mesh_type", "mesh_awg", "mesh_mtu"}
LOCAL_IFACE = {"endpoint_host", "drops_reset", "mesh_reset"}
NOT_STORED = {"awg_gen", "routing_v"}            # an intent (a recreate) and a client version: never a record field


def door_keys(path, helpers=()):
    import re
    a = SRC.index('method == "POST" and path == "%s"' % path)
    e = re.compile(r'\n\s*if method == "[A-Z]+" and path').search(SRC, a + 10).start()   # the next door, at any depth
    blk = SRC[a:e]
    for h in helpers:                                # the setters the door hands its body to
        ha = SRC.index("\ndef %s(" % h)
        blk += SRC[ha:SRC.index("\ndef ", ha + 5)]
    return set(re.findall(r'"([a-z_]+)" in body', blk)) | set(re.findall(r'body\.get\("([a-z_]+)"', blk))


def sec1():
    print("[1] census")
    nk = door_keys("/api/nodes/update") - {"id", "routing_reset", "routing_reset_learned"} - NOT_STORED
    ik = door_keys("/api/iface/update", ("_apply_egress_mode", "_apply_iface_p2p", "reach_level_set")) - {"node", "iface", "id"} - NOT_STORED
    nf, ifo = set(P.FO_NODE_FOLLOW), set(P.FO_IF_FOLLOW) | set(P.FO_IF_FWD) | set(P.FO_IF_CLONE)
    check("[1] every node setting is followed or local", not (nk - nf - LOCAL_NODE), sorted(nk - nf - LOCAL_NODE))
    check("[1] every interface setting is followed, cloned or local", not (ik - ifo - LOCAL_IFACE), sorted(ik - ifo - LOCAL_IFACE))
    check("[1] p2p_portok_none followed, fast_lane local", "p2p_portok_none" in nf and "fast_lane" not in nf)
    check("[1] endpoint_host and the identity are never followed",
          not ({"endpoint_host", "public_key", "key_blob", "_lastcfg"} & set(P.FO_IF_FOLLOW)))


# ── [2] the mirror pass ──────────────────────────────────────────────────────────────────────────────────────────────
def sec2():
    print("[2] the mirror pass")
    n = fleet()
    seen = {"na": NOW, "nb": NOW}
    snaps = {"na": {"interfaces": {"awg0": snap_iface()}}, "nb": {"interfaces": {}}}
    ch = P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    b = n["nb"]
    bo = (b.get("ifaces") or {}).get("awg0") or {}
    check("[2] the identity is cloned", ch and bo.get("public_key") == KA and bo.get("key_blob", {}).get("pub") == KA
          and bo.get("_lastcfg", {}).get("subnet") == "10.8.0.0/24", bo)
    check("[2] settings followed", bo.get("listen_port") == 443 and bo.get("awg_params") == {"Jc": 4, "Jmin": 40, "Jmax": 70}
          and bo.get("block") == ["ads"] and bo.get("egress_node") == "nc", bo)
    check("[2] egress_ip followed in forward mode", bo.get("egress_ip") == "7.7.7.7", bo)
    check("[2] endpoint_host not followed (B's own)", "endpoint_host" not in bo and b.get("endpoint_host") == "", (bo, b.get("endpoint_host")))
    check("[2] node settings: p2p_portok_none followed, fast_lane local", b.get("p2p_portok_none") is True and "fast_lane" not in b, b)
    cr = (b.get("create") or {}).get("awg0") or {}
    check("[2] a restore staged, holding for the vault key", cr.get("hold_key") is True and cr.get("subnet") == "10.8.0.0/24"
          and cr.get("listen_port") == 443, cr)
    check("[2] _synced is not cloned", "_synced" not in bo or not bo["_synced"], bo.get("_synced"))
    check("[2] steady state writes nothing", P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW) is False)
    n["na"]["iface_order"], n["na"]["turn_order"] = ["wg1", "awg0"], ["wdtt:wdtt1", "vk-turn-proxy-cacggghp-56100"]
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[2] B's cards follow A's order: interfaces, and proxies with servers (operator, 2026-11-16)",
          b.get("iface_order") == ["wg1", "awg0"] and b.get("turn_order") == ["wdtt:wdtt1", "vk-turn-proxy-cacggghp-56100"],
          (b.get("iface_order"), b.get("turn_order")))
    n["na"].pop("iface_order"); n["na"].pop("turn_order")
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[2] …and back to the reported order when A drops its own", "iface_order" not in b and "turn_order" not in b,
          (b.get("iface_order"), b.get("turn_order")))
    # B now reports the interface
    snaps["nb"] = {"interfaces": {"awg0": snap_iface()}}
    b.pop("create", None)
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[2] a reported interface is not re-staged", "awg0" not in (b.get("create") or {}), b.get("create"))
    # an Adopt on A: A's blessed key moves
    n["na"]["ifaces"]["awg0"]["public_key"] = KX
    n["na"]["ifaces"]["awg0"]["key_blob"] = {"pub": KX, "ct": "z", "vault": IVK}
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[2] an Adopt on A never reaches B", b["ifaces"]["awg0"]["public_key"] == KA and b["ifaces"]["awg0"]["key_blob"]["pub"] == KA,
          b["ifaces"]["awg0"].get("public_key"))
    # follow a change; port change clears _synced
    n["na"]["ifaces"]["awg0"]["public_key"] = KA
    n["na"]["ifaces"]["awg0"]["key_blob"] = {"pub": KA, "ct": "c", "vault": IVK}
    b["ifaces"]["awg0"]["_synced"] = {"listen_port": 443}
    n["na"]["ifaces"]["awg0"]["listen_port"] = 8443
    n["na"]["ifaces"]["awg0"]["egress_mode"] = "direct"
    n["na"]["ifaces"]["awg0"]["egress_ip"] = "1.2.3.4"
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    bo = b["ifaces"]["awg0"]
    check("[2] a port change follows and clears its _synced", bo["listen_port"] == 8443 and "listen_port" not in bo.get("_synced", {}), bo)
    check("[2] direct mode: A's own egress_ip is not B's (Auto there)", "egress_ip" not in bo, bo)
    # a key mismatch on B deletes nothing
    snaps["nb"] = {"interfaces": {"awg0": snap_iface(key=KX)}}
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[2] a key mismatch deletes nothing", "awg0" in b["ifaces"] and "awg0" not in (b.get("delete") or {}), b.get("delete"))
    # A drops awg0 while stale, its last snapshot without it: nothing deleted
    rec = n["na"]["ifaces"].pop("awg0")
    snaps["na"] = {"interfaces": {}}
    P.failover_mirror(DEPS, n, "nb", snaps, {"na": NOW - 3600, "nb": NOW}, now=NOW)
    check("[2] a stale A removes nothing from B", "awg0" in b["ifaces"] and not (b.get("delete") or {}), b.get("delete"))
    # A live, still reporting it: nothing
    snaps["na"] = {"interfaces": {"awg0": snap_iface()}}
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[2] A live but still reporting it: kept", "awg0" in b["ifaces"], b.get("delete"))
    # A live, not reporting it: deleted
    snaps["na"] = {"interfaces": {}}
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[2] record and box agree on A: dropped on B", "awg0" not in b["ifaces"] and "awg0" in (b.get("delete") or {}), b)
    # never a create without a key source: B holds a copy whose blob the vault no longer opens (an encryption reset)
    n2 = fleet()
    P.failover_mirror(DEPS, n2, "nb", {"na": {}, "nb": {"interfaces": {}}}, seen, now=NOW)
    n2["nb"].pop("create", None)
    for x in ("na", "nb"):
        n2[x]["ifaces"]["awg0"]["key_blob"]["vault"] = "other"
    P.failover_mirror(DEPS, n2, "nb", {"na": {}, "nb": {"interfaces": {}}}, seen, now=NOW)
    check("[2] no vault key source: nothing staged", "awg0" in n2["nb"]["ifaces"] and not (n2["nb"].get("create") or {}),
          n2["nb"].get("create"))
    # a box's own interface on B: neither recorded (T-17 off, see [10]) nor deleted
    n3 = fleet()
    n3["nb"]["ifaces"] = {"wg9": {"system": True}}
    P.failover_mirror(DEPS, n3, "nb", {"na": {"interfaces": {"awg0": snap_iface()}}, "nb": {"interfaces": {}}}, seen, now=NOW)
    check("[2] a link record of B's own is untouched", n3["nb"]["ifaces"]["wg9"] == {"system": True} and "wg9" not in (n3["nb"].get("delete") or {}))
    _ = rec
    # F7: a blob the vault cannot open is not cloned; once A's is sealed to the vault, it is
    n4 = fleet()
    n4["na"]["ifaces"]["awg0"]["key_blob"]["vault"] = "old-vault"
    s4 = {"na": {"interfaces": {"awg0": snap_iface()}}, "nb": {"interfaces": {}}}
    P.failover_mirror(DEPS, n4, "nb", s4, seen, now=NOW)
    check("[2] no clone of a blob the vault cannot open", "awg0" not in (n4["nb"].get("ifaces") or {}), n4["nb"].get("ifaces"))
    n4["na"]["ifaces"]["awg0"]["key_blob"]["vault"] = IVK
    P.failover_mirror(DEPS, n4, "nb", s4, seen, now=NOW)
    check("[2] …cloned once A's is sealed to the vault", (n4["nb"]["ifaces"].get("awg0") or {}).get("key_blob", {}).get("vault") == IVK)
    n4["na"]["ifaces"]["awg0"]["key_blob"] = {"pub": KA, "ct": "resealed", "vault": IVK}
    P.failover_mirror(DEPS, n4, "nb", s4, seen, now=NOW)
    check("[2] the same key re-sealed on A follows to B", n4["nb"]["ifaces"]["awg0"]["key_blob"].get("ct") == "resealed",
          n4["nb"]["ifaces"]["awg0"]["key_blob"])
    # F51: a device B reports down is restored like an absent one
    n5 = fleet()
    P.failover_mirror(DEPS, n5, "nb", {"na": {"interfaces": {"awg0": snap_iface()}}, "nb": {"interfaces": {}}}, seen, now=NOW)
    n5["nb"].pop("create", None)
    P.failover_mirror(DEPS, n5, "nb", {"na": {"interfaces": {"awg0": snap_iface()}},
                                      "nb": {"interfaces": {"awg0": {"down": "Cannot find device", "meta": {}, "peers": []}}}}, seen, now=NOW)
    check("[2] a device B reports down: no restore while the autostart is still starting it", not (n5["nb"].get("create") or {}),
          n5["nb"].get("create"))
    n5["nb"]["iface_autostart"] = {"awg0": {"n": len(P.IFACE_AUTOSTART_GAPS)}}
    P.failover_mirror(DEPS, n5, "nb", {"na": {"interfaces": {"awg0": snap_iface()}},
                                      "nb": {"interfaces": {"awg0": {"down": "Cannot find device", "meta": {}, "peers": []}}}}, seen, now=NOW)
    check("[2] …restored once the autostart has given up", (n5["nb"].get("create") or {}).get("awg0", {}).get("hold_key") is True,
          n5["nb"].get("create"))
    # F54: a 3.1 interface is not restored on a box that cannot run it
    n6 = fleet()
    n6["na"]["ifaces"]["awg0"]["awg_params"] = {"Jc": 4, "HeaderProtectionKey": "k"}
    n6["na"]["ifaces"]["awg0"]["_lastcfg"]["awg_params"] = {"Jc": 4, "HeaderProtectionKey": "k"}
    P.failover_mirror(DEPS, n6, "nb", {"na": {"interfaces": {"awg0": snap_iface()}}, "nb": {"interfaces": {}}}, seen, now=NOW)
    check("[2] a 3.1 interface: no restore on a box that does not report it can", not (n6["nb"].get("create") or {}), n6["nb"].get("create"))


# ── [3] rid, memos, arrivals, blocks ─────────────────────────────────────────────────────────────────────────────────
RID_FUNCS = {"desired_for_node", "who_plan_for_node", "_peers_on", "dev_reach_promotes", "node_networks", "net_share_for_node",
             "dev_reach_for_node", "cut_off_for_node", "limits_for_node", "_resolve_iface_blocks", "p2p_routers_cached",
             "p2p_fwd_for_node"}
OWN_ID_ROSTER = {"peer_set", "ev_append", "_wdtt_reply", "_csqtt_reply"}   # the imports (off on B) and B's own turn instances


def sync_calls():
    """(function, argument text) for every call in the sync's apply — the source the plants edited."""
    import re
    a = SRC.index("    def _node_sync_apply(")
    body = SRC[a:re.compile(r"\n    def |\ndef ").search(SRC, a + 10).start()]
    out = []
    for mm in re.finditer(r"\b([A-Za-z_]\w*)\(", body):
        i = j = mm.end(); depth = 1
        while depth and j < len(body):
            depth += {"(": 1, ")": -1}.get(body[j], 0); j += 1
        out.append((mm.group(1), body[i:j - 1]))
    return out


def roster():
    r = {"users": {"u1": {"name": "ann", "limits": {"c": 30}}, "u2": {"name": "bob"}}, "groups": {},
         "peers": {"p1": {"id": "p1", "user_id": "u1", "pubkey": PK[0], "psk": PK[5], "title": "phone", "p2p_port": 20001,
                          "targets": [{"node": "na", "iface": "awg0", "ip": "10.8.0.2"}]},
                   "p2": {"id": "p2", "user_id": "u2", "pubkey": PK[1], "psk": PK[6], "title": "laptop", "router": True,
                          "targets": [{"node": "na", "iface": "awg0", "ip": "10.8.0.3", "limits": {"d": 8}}]},
                   "p3": {"id": "p3", "user_id": "u2", "pubkey": PK[2], "psk": PK[7], "title": "tab", "disabled": True,
                          "targets": [{"node": "na", "iface": "awg0", "ip": "10.8.0.4"}]}}}
    return r


def sec3():
    print("[3] rid")
    n = fleet()
    r = roster()
    check("[3] failover_rid: B → A, A → A, C → C", P.failover_rid(n, "nb") == "na" and P.failover_rid(n, "na") == "na"
          and P.failover_rid(n, "nc") == "nc")
    n2 = fleet(); n2["nb"]["failover_of"] = "gone"
    check("[3] a primary no longer in the store: B is itself", P.failover_rid(n2, "nb") == "nb")
    dA = P.desired_for_node(r, "na")
    check("[3] B's desired through rid is A's", P.desired_for_node(r, P.failover_rid(n, "nb")) == dA and dA.get("awg0"), dA)
    lA = P.limits_for_node(r, "na", dA)
    check("[3] B's limits through rid are A's", lA and P.limits_for_node(r, P.failover_rid(n, "nb"), dA) == lA, lA)
    # memos: A and B keep separate slots
    P._P2P_FWD.clear()
    sc = ("direct", ["10.99.0.0/16"])
    P.p2p_fwd_for_node(1, r, "na", sc)
    P.p2p_fwd_for_node(1, r, "na", sc, slot="nb")
    import re
    calls = sync_calls()
    own = lambda a: re.search(r"(?<![=\w])nid\b", a)
    bad = [(f, " ".join(a.split())[:80]) for f, a in calls
           if own(a) and (f in RID_FUNCS or (re.search(r"\broster\b", a) and f not in OWN_ID_ROSTER))]
    check("[3] census: no roster-keyed read of the sync takes the node's own id", not bad, bad)
    have = {f for f, a in calls if re.search(r"\b_rid\b", a)}
    check("[3] census: every known roster-keyed read is there, with _rid", not (RID_FUNCS - have), sorted(RID_FUNCS - have))
    check("[3] p2p_fwd memo: one slot each", set(P._P2P_FWD) == {"na", "nb"}, set(P._P2P_FWD))
    _alias = P.p2p_fwd_for_node(1, r, "na", sc, slot="nb")
    check("[3] a slot answers only for the id it was computed for (a detach saves no roster)",
          _alias and P.p2p_fwd_for_node(1, r, "nb", sc, slot="nb") == [], _alias)
    P._P2P_ROUTERS.clear()
    P.p2p_routers_cached(1, r, "na", ())
    P.p2p_routers_cached(1, r, "na", (), slot="nb")
    check("[3] p2p_routers memo: one slot each", set(P._P2P_ROUTERS) == {"na", "nb"}, set(P._P2P_ROUTERS))
    # arrivals at C from B are named A
    nc = {"links": {"nb": {"iface": "swg_b"}, "na": {"iface": "swg_a"}}}
    plan = {"exit": [{"subnet": "10.8.0.0/24", "via_iface": "swg_b"}]}
    arr = P.p2p_arrivals(nc, plan, n)
    check("[3] an arrival from B is named A", arr == [("10.8.0.0/24", "na")], arr)
    check("[3] the router peer keeps its never-flag entry at the exit with B serving",
          P.p2p_routers_for_node(r, "nc", arr) == ["10.8.0.3/32"], P.p2p_routers_for_node(r, "nc", arr))
    check("[3] no nodes given: arrivals unchanged", P.p2p_arrivals(nc, plan) == [("10.8.0.0/24", "nb")])
    # a block category enabled on A only → enforces on B through rid
    cat = {"ads": {"id": "ads", "enabled": True, "enabled_nodes": ["na"], "default_on": False, "predefined": False,
                   "sources": [{"id": "x"}]}}
    fa = P._block_feeds(cat, {}, "na", "kernel", ["ads"])
    fb = P._block_feeds(cat, {}, P.failover_rid(n, "nb"), "kernel", ["ads"])
    check("[3] a category enabled on A is read for B as for A", fa == fb, (fa, fb))


# ── [4] the planner ──────────────────────────────────────────────────────────────────────────────────────────────────
def plan_fleet():
    n = fleet()
    n["na"]["ifaces"]["awg0"]["routing"] = []
    n["nb"]["ifaces"]["awg0"] = dict(n["na"]["ifaces"]["awg0"])
    for x, y in (("na", "nc"), ("nb", "nc")):
        n[x]["links"][y] = {"iface": "swg_%s%s" % (x, y), "subnet": "10.255.0.0/31", "address": "10.255.0.0",
                            "peer_address": "10.255.0.1"}
        n[y]["links"][x] = {"iface": "swg_%s%s" % (y, x), "subnet": "10.255.0.0/31", "address": "10.255.0.1",
                            "peer_address": "10.255.0.0"}
    return n


def plan_snaps(on_a=0, on_b=0, a_live=True):
    mk = lambda k: snap_iface(peers=[(PK[i], i < k, 0, 0) for i in range(3)])
    s = {"na": {"interfaces": {"awg0": mk(on_a)}}, "nb": {"interfaces": {"awg0": mk(on_b)}}, "nc": {"interfaces": {}}}
    for x in ("na", "nb", "nc"):
        for y, lk in fleet_links(x).items():
            s[x]["interfaces"][lk] = {"meta": {"subnet": "10.255.0.0/31", "system": True}, "peers": []}
    return s


_PF = None


def fleet_links(x):
    return {y: lk["iface"] for y, lk in _PF[x]["links"].items()}


def sec4():
    global _PF
    print("[4] the planner")
    n = plan_fleet(); _PF = n
    seen = {"na": NOW, "nb": NOW, "nc": NOW}
    s0 = plan_snaps(2, 0)
    idle = P.failover_idle(n, s0, seen, now=NOW)
    check("[4] clients on A: B idle", idle == frozenset({"nb"}), idle)
    pl = P.cascade_plan(n, s0, idle=idle)
    fa, fb = (pl.get("na") or {}).get("forward") or [], (pl.get("nb") or {}).get("forward") or []
    check("[4] the serving member forwards, the idle one does not", fa and not fb, (fa, fb))
    check("[4] the idle member carries no clash card", not (pl.get("nb") or {}).get("_clash"), (pl.get("nb") or {}).get("_clash"))
    ex = (pl.get("nc") or {}).get("exit") or []
    check("[4] one exit record at C, with A's egress_ip", len(ex) == 1 and ex[0].get("egress_ip") == "7.7.7.7", ex)
    s1 = plan_snaps(0, 2)
    idle1 = P.failover_idle(n, s1, {"na": NOW - 3600, "nb": NOW, "nc": NOW}, now=NOW)
    check("[4] A stale and clients on B: A idle", idle1 == frozenset({"na"}), idle1)
    pl1 = P.cascade_plan(n, s1, idle=idle1)
    check("[4] …and B forwards, A does not, no clash on A", (pl1.get("nb") or {}).get("forward") and not (pl1.get("na") or {}).get("forward")
          and not (pl1.get("na") or {}).get("_clash"), (pl1.get("na"), pl1.get("nb")))
    ex1 = (pl1.get("nc") or {}).get("exit") or []
    check("[4] B serving: the exit at C keeps A's egress_ip", len(ex1) == 1 and ex1[0].get("egress_ip") == "7.7.7.7", ex1)
    check("[4] A stale, no clients on B: nothing flips",
          P.failover_idle(n, plan_snaps(0, 0), {"na": NOW - 3600, "nb": NOW, "nc": NOW}, now=NOW) == frozenset({"nb"}))
    check("[4] an even split is stable (A serves)", P.failover_idle(n, plan_snaps(2, 2), seen, now=NOW) == frozenset({"nb"}))
    plain = {k: {kk: vv for kk, vv in v.items() if kk != "failover_of"} for k, v in n.items()}
    plain["nb"]["ifaces"]["awg0"] = dict(plain["nb"]["ifaces"]["awg0"], _lastcfg={"subnet": "10.9.0.0/24"})
    s0p = json.loads(json.dumps(s0)); s0p["nb"]["interfaces"]["awg0"]["meta"]["subnet"] = "10.9.0.0/24"
    cur = json.dumps(P.cascade_plan(plain, s0p), sort_keys=True, default=str)
    check("[4] no pairs: frozenset(), and the plan is the reference build's", P.failover_idle({"nc": {}}, {}, {}) == frozenset()
          and cur == json.dumps(REFP().cascade_plan(plain, s0p), sort_keys=True, default=str))
    # F4: another node's overlapping subnet into the same exit, between A and B in the store: the pair ranks where A stood
    n4 = {k: n[k] for k in ("na",)}
    n4["nd"] = {"id": "nd", "name": "d", "ifaces": {"awg0": dict(n["na"]["ifaces"]["awg0"])}, "links": {}}
    n4.update({k: n[k] for k in ("nc", "nb")})
    n4["nd"]["links"]["nc"] = {"iface": "swg_ndnc", "subnet": "10.255.0.2/31", "address": "10.255.0.2", "peer_address": "10.255.0.3"}
    n4["nc"] = dict(n4["nc"], links=dict(n4["nc"]["links"], nd={"iface": "swg_ncnd", "subnet": "10.255.0.2/31",
                                                                   "address": "10.255.0.3", "peer_address": "10.255.0.2"}))
    s4 = plan_snaps(0, 2)
    s4["nd"] = {"interfaces": {"awg0": snap_iface(), "swg_ndnc": {"meta": {"subnet": "10.255.0.2/31", "system": True}, "peers": []}}}
    s4["nc"]["interfaces"]["swg_ncnd"] = {"meta": {"subnet": "10.255.0.2/31", "system": True}, "peers": []}
    pl4 = P.cascade_plan(n4, s4, idle=frozenset({"na"}))
    check("[4] B serving ranks where A stood: B forwards, the other node's overlap is the clash",
          (pl4.get("nb") or {}).get("forward") and not (pl4.get("nd") or {}).get("forward") and (pl4.get("nd") or {}).get("_clash"),
          {k: ((pl4.get(k) or {}).get("forward"), bool((pl4.get(k) or {}).get("_clash"))) for k in ("na", "nb", "nd")})
    # F13: the idle member names no dead torrent route
    n5 = plan_fleet()
    for x in ("na", "nb"):
        n5[x]["p2p"] = {"action": "iface"}
        n5[x]["ifaces"]["awg0"]["p2p"] = {"action": "exit", "node": "nc"}
    pl5 = P.cascade_plan(n5, s0, idle=frozenset({"nb"}))
    check("[4] the idle member names no dead torrent route", not (pl5.get("nb") or {}).get("_p2p_dead")
          and not (pl5.get("na") or {}).get("_p2p_dead"), {k: (pl5.get(k) or {}).get("_p2p_dead") for k in ("na", "nb")})


# ── [5] mesh ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def sec5():
    print("[5] mesh")
    n = {"na": {"id": "na", "name": "a", "ifaces": {}, "links": {}}, "nc": {"id": "nc", "name": "c", "ifaces": {}, "links": {}},
         "nd": {"id": "nd", "name": "d", "ifaces": {}, "links": {}},
         "nb": {"id": "nb", "name": "b", "failover_of": "na", "ifaces": {}, "links": {}}}
    deps = {"panel_settings": {"mesh_mode": "full"}, "roster_path": os.path.join(TMP, "m-users.json"),
            "nodes_path": os.path.join(TMP, "m-nodes.json")}
    P.reconcile_mesh(n, {}, deps)
    pairs = {frozenset((a, b)) for a, c in n.items() for b in (c.get("links") or {})}
    check("[5] full mode, nothing asks: B linked to nobody", not any("nb" in p for p in pairs) and frozenset(("na", "nc")) in pairs, pairs)
    n["nb"]["ifaces"]["awg0"] = {"egress_mode": "forward", "egress_node": "nc"}
    P.reconcile_mesh(n, {}, deps)
    pairs = {frozenset((a, b)) for a, c in n.items() for b in (c.get("links") or {})}
    check("[5] a mirrored forward to C: B↔C linked, B↔D not", frozenset(("nb", "nc")) in pairs and frozenset(("nb", "nd")) not in pairs, pairs)
    _g = P.MESH_RETIRE_GRACE_S
    try:
        P.MESH_RETIRE_GRACE_S = 0
        n["nb"]["ifaces"]["awg0"]["egress_node"] = "nd"
        P.reconcile_mesh(n, {}, deps); P.reconcile_mesh(n, {}, deps)
        pairs = {frozenset((a, b)) for a, c in n.items() for b in (c.get("links") or {})}
        check("[5] the forward moves to D: B↔D linked, B↔C retired, the rest kept",
              frozenset(("nb", "nd")) in pairs and frozenset(("nb", "nc")) not in pairs and frozenset(("na", "nc")) in pairs, pairs)
    finally:
        P.MESH_RETIRE_GRACE_S = _g
    big = {("n%d" % i): {"id": "n%d" % i} for i in range(P.MESH_AUTO_FULL_MAX)}
    big.update({("f%d" % i): {"id": "f%d" % i, "failover_of": "n%d" % i} for i in range(P.MESH_AUTO_FULL_MAX)})
    check("[5] auto: mirrors do not count", P.mesh_mode_effective({"panel_settings": {}}, big) == "full")
    big["f0"]["failover_of"] = "gone"
    check("[5] …a B whose primary is gone counts", P.mesh_mode_effective({"panel_settings": {}}, big) == "demand")
    nets = P._fleet_user_networks({"node_snaps": {"nb": {"interfaces": {"awg0": snap_iface()}}}},
                                  {"na": {"ifaces": {"awg0": a_iface()}},
                                   "nb": {"failover_of": "na", "wdtt": {"wdtt0": {"wg_addr": "10.66.0.1/24"}}}})
    check("[5] _fleet_user_networks: B's copy of A's interface skipped, B's own counted",
          [(a, b, str(c)) for a, b, c in nets] == [("nb", "wdtt0", "10.66.0.0/24")], nets)


# ── [6] the ledger ───────────────────────────────────────────────────────────────────────────────────────────────────
def sec6():
    print("[6] the ledger")
    d = os.path.join(TMP, "ledger"); os.makedirs(d)
    rp = os.path.join(d, "users.json")
    json.dump(roster(), open(rp, "w"))
    L = P.TrafficLedger()
    L.start({"roster_path": rp, "panel_settings": {}}, now=NOW, writer=False)
    pairs = (("na", "nb"),)
    s = lambda rx: {"interfaces": {"awg0": {"peers": [{"public_key": PK[0], "rx_bytes": rx, "tx_bytes": rx}]}}}
    L.ingest("nb", s(1000), now=NOW, mono=1.0, pairs=pairs)
    L.ingest("nb", s(5000), now=NOW + 5, mono=6.0, pairs=pairs)
    slot = L.open.get("p1")
    got = (L.C_rx[slot], L.C_tx[slot]) if slot is not None else None
    check("[6] B's counter lands in the device's slot", got == (4000, 4000), got)
    check("[6] B's deployment is a deployment", ("nb", "awg0", "p1") in L.deploys, sorted(L.deploys))
    time.sleep(0.01)
    r2 = roster(); r2["users"]["u2"]["name"] = "bobby"
    P.roster_save(rp, r2)
    L.ingest("nb", s(9000), now=NOW + 10, mono=11.0, pairs=pairs)
    got = (L.C_rx[slot], L.C_tx[slot])
    check("[6] a roster save keeps B's baseline (no zero-credit gap)", got == (8000, 8000), got)
    m0 = L.mark
    L.ingest("na", {"interfaces": {}}, now=NOW + 15, mono=16.0, pairs=())
    check("[6] the pair cleared: the map is rebuilt without B", ("nb", "awg0", PK[0]) not in L.map and L.mark != m0, L.mark)
    check("[6] no pair: the mark is the roster's own", L.mark == P.roster_mark(rp), L.mark)
    L.ingest("na", {"interfaces": {}}, now=NOW + 20, mono=21.0, pairs=pairs)
    check("[6] the pair set again: B claimed at once", L.map.get(("nb", "awg0", PK[0])) == "p1", L.map)


# ── [7] read-only ────────────────────────────────────────────────────────────────────────────────────────────────────
def sec7():
    print("[7] read-only")
    n = fleet()
    f = lambda path, body: P.failover_ro_refusal(path, body, n)
    check("[7] an interface edit on B is refused", (f("/api/iface/update", {"node": "nb", "iface": "awg0", "mtu": 1400}) or [0])[0] == 409)
    check("[7] /api/peers/targets adding on B is refused", (f("/api/peers/targets", {"peer_id": "p1", "add": [{"node": "nb", "iface": "awg0"}]}) or [0])[0] == 409)
    check("[7] /api/peers/targets' base naming B is refused", (f("/api/peers/targets", {"peer_id": "p1", "base": [{"node": "nb", "iface": "awg0"}]}) or [0])[0] == 409)
    check("[7] add-target on B is refused", (f("/api/peers/add-target", {"peer_id": "p1", "target": {"node": "nb", "iface": "awg0"}}) or [0])[0] == 409)
    check("[7] a node edit of a followed field is refused", (f("/api/nodes/update", {"id": "nb", "routing_mode": "sni"}) or [0])[0] == 409)
    check("[7] a rename is allowed", f("/api/nodes/update", {"id": "nb", "name": "x", "color": None}) is None)
    check("[7] the node sheet's whole body is allowed", f("/api/nodes/update", {
        "id": "nb", "name": "x", "color": None, "endpoint_host": "b.example.com", "mesh_port": "", "mesh_egress_ip": "",
        "mesh_subnet": "", "mesh_prefix": "", "default_egress_ip": "", "panel_ip": "", "fast_lane": 50}) is None)
    check("[7] a connection card's reset is allowed", f("/api/iface/update", {"node": "nb", "iface": "awg0", "drops_reset": 1}) is None)
    n["nb"]["ifaces"]["wg7"] = {"listen_port": 51000}
    check("[7] deleting B's own interface is allowed", f("/api/iface/delete", {"node": "nb", "iface": "wg7"}) is None)
    check("[7] deleting B's copy of A's is refused", (f("/api/iface/delete", {"node": "nb", "iface": "awg0"}) or [0])[0] == 409)
    check("[7] editing or fresh-recreating B's own interface is allowed", f("/api/iface/update", {"node": "nb", "iface": "wg7", "mtu": 1400}) is None
          and f("/api/iface/recreate", {"node": "nb", "iface": "wg7", "fresh": True}) is None)
    check("[7] routing/who is allowed", f("/api/routing/who", {"node": "nb", "iface": "awg0", "rows": []}) is None)
    check("[7] a fresh recreate (B's own key) is refused", (f("/api/iface/recreate", {"node": "nb", "iface": "awg0", "fresh": True}) or [0])[0] == 409)
    check("[7] an egress_node naming B is refused", (f("/api/iface/update", {"node": "nc", "iface": "awg0", "egress_node": "nb"}) or [0])[0] == 409)
    check("[7] a padded id is refused", (f("/api/container/adopt", {"node": "nb ", "container": "x"}) or [0])[0] == 409)
    check("[7] a list-valued id raises nothing", f("/api/peers/update", {"id": "p1", "node": []}) is None
          and f("/api/access/confirm", {"nonce": "x", "node": [1]}) is None)
    n2 = fleet(); n2["nb"]["failover_of"] = "gone"
    check("[7] a B whose primary is gone is not read-only", P.failover_ro_refusal("/api/iface/update", {"node": "nb", "iface": "x"}, n2) is None)
    for p, b in (("/api/nodes/rotate", {"id": "nb"}), ("/api/node/update", {"node": "nb"}), ("/api/nodes/failover/detach", {"id": "nb"}),
                 ("/api/connection/update", {"node": "nb"}), ("/api/iface/recreate", {"node": "nb", "iface": "awg0"}),
                 ("/api/iface/escrow/verified", {"node": "nb"}), ("/api/iface/restore", {"node": "nb", "iface": "awg0", "key": "mtu"})):
        check("[7] allowed: " + p, f(p, b) is None)
    check("[7] a drift Restore of the key is refused on B — the key is Re-sync's", (f("/api/iface/restore", {"node": "nb", "iface": "awg0", "key": "public_key"}) or [0])[0] == 409)
    check("[7] the primary is not read-only", f("/api/iface/update", {"node": "na", "iface": "awg0"}) is None)
    check("[7] a fleet with none: nothing read", P.failover_ro_refusal("/api/iface/update", {"node": "nb"}, {"nb": {}}) is None)
    check("[7] a peer id on a peer door is not a node", f("/api/peers/update", {"id": "nb"}) is None)
    # the Settings save posts a failover node's own fields only (screen-settings FO_NODE_OWN): the server's own list, as far as
    # that save sends them — a field missing there is silently never saved, one too many fails the whole save (verify F70)
    st = open(os.path.join(ROOT, "js", "screen-settings.js")).read()
    own = set(re.findall(r'"(\w+)"', re.search(r"const FO_NODE_OWN = new Set\(\[(.*?)\]\)", st, re.S).group(1)))
    blk = st[st.index("await api.nodeUpdate({"):]
    sent = set(re.findall(r"\b(\w+):", blk[:blk.index("}, own)")]))
    check("[7] the Settings save's own fields of a failover node are the server's, as far as it sends them",
          own == (set(P._FO_NODE_LOCAL) & sent) - {"id"}, (sorted(own), sorted((set(P._FO_NODE_LOCAL) & sent) - {"id"})))


# ── [8] take-over and removal ────────────────────────────────────────────────────────────────────────────────────────
def to_fleet():
    n = fleet()
    n["na"]["ifaces"]["wg1"] = a_iface(public_key=KX, key_blob={"pub": KX, "ct": "c", "vault": IVK}, endpoint_host="")
    n["nb"]["ifaces"]["awg0"] = {"public_key": KA, "listen_port": 443, "_synced": {"listen_port": 443}}
    n["nb"]["ifaces"]["wg1"] = {"public_key": KX, "listen_port": 443}          # a copy B never brought up
    n["nb"]["create"] = {"wg1": {"hold_key": True}}
    return n


def sec8():
    print("[8] take-over and removal")
    n = to_fleet()
    r = roster()
    r["peers"]["p0"] = {"id": "p0", "user_id": "u2", "pubkey": PK[3], "psk": PK[6], "title": "pc", "p2p_port": 20001,
                        "p2p_yield": ["na"], "targets": [{"node": "na", "iface": "awg0", "ip": "10.8.0.9"}]}
    r["peers"]["p5"] = {"id": "p5", "user_id": "u2", "pubkey": PK[4], "psk": PK[6], "title": "nas",
                        "targets": [{"node": "na", "iface": "wg1", "ip": "10.9.0.2"}]}
    snaps = {"na": {"interfaces": {"awg0": snap_iface(), "wg1": snap_iface(key=KX)}}, "nb": {"interfaces": {"awg0": snap_iface()}}}
    owner_before = {q: o for q, o in [(e[1], e[0]) for e in P.p2p_fwd_for_node(None, r, "na", ("direct", ["10.99.0.0/16"]))]}
    check("[8] with no snapshot of B: nothing held, nothing known lacking", P._fo_holds(n, {"na": snaps["na"]}, "na", "nb", True) == ([], [], ["awg0", "wg1"], []),
          P._fo_holds(n, {"na": snaps["na"]}, "na", "nb", True))
    check("[8] a B not reporting: its last snapshot proves nothing (F87, F88)", P._fo_holds(n, snaps, "na", "nb", False) == ([], [], ["awg0", "wg1"], []),
          P._fo_holds(n, snaps, "na", "nb", False))
    for sx_, live_, what in ((snaps, False, "a B not reporting"), ({"na": snaps["na"]}, True, "no snapshot of B")):
        nz = to_fleet()
        try:
            P.failover_takeover(nz, roster(), "na", "nb", P._fo_holds(nz, sx_, "na", "nb", live_), sx_)
            ok_ = False
        except ValueError:
            ok_ = "failover_of" in nz["nb"] and not nz["nb"].get("delete") and set(nz["nb"]["ifaces"]) == {"awg0", "wg1"}
        check("[8] a take-over from %s is refused: nothing moved, nothing deleted (F75, F87)" % what, ok_, nz["nb"])
    for st in ({"down": "Cannot find device", "meta": {}, "peers": []}, dict(snap_iface(), stopped=True), snap_iface(key="")):
        ny = to_fleet()
        sy = {"na": snaps["na"], "nb": {"interfaces": {"awg0": st}}}
        check("[8] B's awg0 %s: in doubt, not lacking" % ("down" if st.get("down") else "stopped" if st.get("stopped") else "with no key"),
              "awg0" in P._fo_holds(ny, sy, "na", "nb", True)[2], P._fo_holds(ny, sy, "na", "nb", True))
    n["nb"]["ifaces"].pop("wg1"); n["nb"].pop("create")      # B never had a copy of wg1: absent
    moved, left, _dropped = P.failover_takeover(n, r, "na", "nb", P._fo_holds(n, snaps, "na", "nb", True), snaps)
    check("[8] the interface B holds moves; the one it lacks stays", moved == ["awg0"] and left == ["wg1"], (moved, left))
    check("[8] targets moved A→B", all(t["node"] == "nb" for p in ("p1", "p2", "p3", "p0") for t in r["peers"][p]["targets"])
          and r["peers"]["p5"]["targets"][0]["node"] == "na")
    check("[8] p2p_yield follows (A dropped, B added)", r["peers"]["p0"].get("p2p_yield") == ["nb"], r["peers"]["p0"].get("p2p_yield"))
    check("[8] a take-over deletes nothing on B", not n["nb"].get("delete"), n["nb"].get("delete"))
    up_b = {"interfaces": {"awg0": snap_iface()}}
    for st, want, why in (({"down": "x", "meta": {}, "peers": []}, ["awg0"], "down"), (dict(snap_iface(), stopped=True), [], "stopped"),
                          (None, ["awg0"], "not reported"), (snap_iface(key=""), [], "up without a key"),
                          (snap_iface(key=KX), ["awg0"], "up under another key (F118)")):
        ka = {"na": {"interfaces": {"awg0": st} if st else {}}, "nb": up_b}
        got = P._fo_only_on_b(to_fleet(), ka, "na", "nb", True)
        check("[8] keep: awg0 on A %s, B runs it → only on B: %s" % (why, want), got == want, got)
    kb = {"na": {"interfaces": {"awg0": {"down": "x", "meta": {}, "peers": []}}}, "nb": {"interfaces": {"awg0": snap_iface(key="")}}}
    check("[8] keep: B runs awg0 without reporting a key, A has it down → only on B (F117)",
          P._fo_only_on_b(to_fleet(), kb, "na", "nb", True) == ["awg0"], P._fo_only_on_b(to_fleet(), kb, "na", "nb", True))
    check("[8] keep: B not reporting → nothing known to run on B alone", P._fo_only_on_b(to_fleet(), kb, "na", "nb", False) == [])
    check("[8] keep: a malformed snapshot is no report, not a 500 (F121)",
          P._fo_only_on_b(to_fleet(), {"na": {"interfaces": ["x"]}, "nb": {"interfaces": "y"}}, "na", "nb", True) == [])
    nl = to_fleet(); nl["nb"]["ifaces"].pop("wg1"); nl["nb"].pop("create"); nl["nb"]["ifaces"]["wg2"] = {"public_key": "O" * 43 + "="}
    _r = P.failover_takeover(nl, roster(), "na", "nb", P._fo_holds(nl, snaps, "na", "nb", True), snaps)
    check("[8] a take-over drops B's copy of an interface A no longer has, and says so (F120, F125)",
          "wg2" not in nl["nb"]["ifaces"] and "wg2" in (nl["nb"].get("delete") or {}) and _r[2] == ["wg2"], (_r, nl["nb"].get("delete")))
    # the status reads the same copy test (F123, F124, F126)
    nv = to_fleet(); nv["nb"]["ifaces"]["wg1"] = {"system": True, "public_key": "M" * 43 + "="}
    rows = {r["iface"]: r for r in P.failover_view(nv, None, "na", "nb", snaps, {"na": NOW, "nb": NOW}, frozenset(), now=NOW)["rows"]}
    check("[8] status: a mesh link of B's named like A's interface is a problem of its own, never a Re-sync (F124)",
          rows.get("wg1", {}).get("why") == "name_taken" and not rows["wg1"].get("resync"), rows.get("wg1"))
    nk = to_fleet(); nk["na"]["ifaces"]["awg0"].pop("public_key"); nk["nb"]["ifaces"]["awg0"].pop("public_key")
    sk = json.loads(json.dumps(snaps)); sk["na"]["interfaces"]["awg0"]["meta"]["public_key"] = ""
    rk = {r["iface"]: r for r in P.failover_view(nk, None, "na", "nb", sk, {"na": NOW, "nb": NOW}, frozenset(), now=NOW, ivk=IVK)["rows"]}
    check("[8] status: A with no key — a problem of its own, no Re-sync (it could not rebuild), unsure to the door (F128)",
          rk.get("awg0", {}).get("why") == "primary_no_key" and not rk["awg0"].get("resync")
          and "awg0" in P._fo_holds(nk, sk, "na", "nb", True)[2], rk.get("awg0"))
    nr = to_fleet(); nr["na"]["ifaces"]["awg0"].pop("public_key")
    check("[8] A's record not blessed, its box reports the key B's copy carries: held (F135)",
          "awg0" in P._fo_holds(nr, snaps, "na", "nb", True)[0], P._fo_holds(nr, snaps, "na", "nb", True))
    nr["nb"]["ifaces"]["awg0"]["public_key"] = "Q" * 43 + "="
    check("[8] …B's copy under another key: a report never condemns it — unsure, kept on removal (F147)",
          "awg0" in P._fo_holds(nr, snaps, "na", "nb", True)[2] and "awg0" in P._fo_holds(nr, snaps, "na", "nb", True, assume=True)[0],
          P._fo_holds(nr, snaps, "na", "nb", True))
    bad = json.loads(json.dumps(snaps)); bad["na"]["interfaces"]["awg0"]["meta"]["public_key"] = {}
    check("[8] a non-string reported key is no report (F153)", P._fo_akey({}, bad, "na", "awg0") == ("", ""), P._fo_akey({}, bad, "na", "awg0"))
    ns = to_fleet(); ns["nb"]["ifaces"]["awg0"]["public_key"] = "Q" * 43 + "="
    for ivk_, want in ((IVK, True), ("", False)):
        rs = {r["iface"]: r for r in P.failover_view(ns, None, "na", "nb", snaps, {"na": NOW, "nb": NOW}, frozenset(), now=NOW, ivk=ivk_)["rows"]}
        check("[8] status: an old copy offers Re-sync %s" % ("— the vault can rebuild A's key" if want else "only where the vault can rebuild (F128)"),
              rs.get("awg0", {}).get("why") == "key" and bool(rs["awg0"].get("resync")) == want, rs.get("awg0"))
    ku = to_fleet(); ku["na"]["ifaces"]["awg0"].pop("public_key")
    kq = {"na": {"interfaces": {"awg0": {"down": "x", "meta": {}, "peers": []}}}, "nb": {"interfaces": {"awg0": snap_iface(key=KX)}}}
    check("[8] keep: A's key unknown, A down, B runs awg0 under any key → only on B", P._fo_only_on_b(ku, kq, "na", "nb", True) == ["awg0"],
          P._fo_only_on_b(ku, kq, "na", "nb", True))
    owner_after = {q: o for q, o in [(e[1], e[0]) for e in P.p2p_fwd_for_node(None, r, "nb", ("direct", ["10.99.0.0/16"]))]}
    check("[8] each port keeps its holder", owner_before == owner_after and owner_before, (owner_before, owner_after))
    check("[8] A's interface dropped as a delete; B takes A's host", "awg0" not in n["na"]["ifaces"] and "awg0" in n["na"]["delete"]
          and n["nb"]["ifaces"]["awg0"].get("endpoint_host") == "vpn.example.com", (n["na"].get("delete"), n["nb"]["ifaces"]["awg0"]))
    check("[8] the flag goes", "failover_of" not in n["nb"])
    # the host: never an IP literal; the one the node reports when none is set
    for host_a, rep_ep, want in (("1.2.3.4", "", None), ("", "vpn2.example.com:443", "vpn2.example.com"), ("", "localhost:443", None)):
        nx = to_fleet(); nx["nb"]["ifaces"].pop("wg1"); nx["nb"].pop("create")
        nx["na"]["ifaces"]["awg0"]["endpoint_host"] = host_a
        nx["na"]["endpoint_host"] = ""
        sx = json.loads(json.dumps(snaps)); sx["na"]["interfaces"]["awg0"]["meta"]["endpoint"] = rep_ep
        P.failover_takeover(nx, roster(), "na", "nb", P._fo_holds(nx, sx, "na", "nb", True), sx)
        check("[8] B's host from A %r / reported %r: %r" % (host_a, rep_ep, want), nx["nb"]["ifaces"]["awg0"].get("endpoint_host") == want,
              nx["nb"]["ifaces"]["awg0"].get("endpoint_host"))
    pf = P.failover_preflight({"nodes_path": "", "roster_path": ""}, dict(to_fleet(), na=dict(to_fleet()["na"], transfer={"state": "pending"})),
                              "na", snaps, {"na": NOW})
    check("[8] the preview refuses a node in transfer", any("transferred" in x["why"] for x in pf["refused"]), pf["refused"])
    _pf = to_fleet(); _pf["na"]["ifaces"]["awg0"]["listen_port"] = 8443      # changed on A, not applied yet: A reports 443
    _pf["na"]["ifaces"]["wg1"].pop("listen_port", None); _pf["na"]["ifaces"]["wg1"]["_lastcfg"] = {"listen_port": 51820}
    _ps = json.loads(json.dumps(snaps)); _ps["na"]["interfaces"].pop("wg1", None)   # A does not report wg1 (down, restarted)
    pf = P.failover_preflight({"nodes_path": "", "roster_path": ""}, _pf, "na", _ps, {"na": NOW})
    check("[8] the preview names the port the spare is BUILT with — the record's, then the captured config's (review F1, F2)",
          {"iface": "awg0", "port": 8443} in pf["warn"]["ports"] and {"iface": "wg1", "port": 51820} in pf["warn"]["ports"],
          pf["warn"]["ports"])
    check("[8] …and the mesh band its links need (review F3)", pf["warn"].get("mesh_ports") == [9999, 10098], pf["warn"].get("mesh_ports"))
    # node_remove(A) keeps every held peer
    d = os.path.join(TMP, "rm"); os.makedirs(d)
    ps = {"block_catalog": {"categories": {"ads": {"enabled_nodes": ["na"]}}},
          "custom_lists": [{"id": "cl_1", "disabled_nodes": ["na"]}, {"id": "cl_2", "disabled_nodes": []}]}
    deps = {"nodes_path": os.path.join(d, "nodes.json"), "roster_path": os.path.join(d, "users.json"), "stats_dir": d,
            "node_snaps": {"na": snaps["na"], "nb": snaps["nb"]}, "node_seen": {"nb": time.time()}, "panel_settings": ps,
            "panel_settings_path": os.path.join(d, "panel-settings.json")}
    _f = to_fleet(); _f["nb"]["ifaces"].pop("wg1"); _f["nb"].pop("create")     # B has no copy of wg1
    json.dump(_f, open(deps["nodes_path"], "w"))
    rr = roster()
    rr["peers"]["p5"] = {"id": "p5", "user_id": "u2", "pubkey": PK[4], "psk": PK[6], "title": "nas",
                         "targets": [{"node": "na", "iface": "wg1", "ip": "10.9.0.2"}]}
    json.dump(rr, open(deps["roster_path"], "w"))
    P.node_remove(deps, "na")
    after = json.load(open(deps["roster_path"]))
    nn = json.load(open(deps["nodes_path"]))
    check("[8] node_remove(A): the held peers are on B", all(t["node"] == "nb" for p in ("p1", "p2", "p3") for t in after["peers"][p]["targets"]),
          {k: v["targets"] for k, v in after["peers"].items()})
    check("[8] node_remove(A): an interface B has no copy of goes with A", "p5" not in after["peers"])
    check("[8] node_remove(A): B is an ordinary node", "na" not in nn and "failover_of" not in nn["nb"], nn.get("nb"))
    d2 = os.path.join(TMP, "rm2"); os.makedirs(d2)
    deps2 = {"nodes_path": os.path.join(d2, "nodes.json"), "roster_path": os.path.join(d2, "users.json"), "stats_dir": d2,
             "node_snaps": {"na": snaps["na"]}, "node_seen": {}, "panel_settings": {}}
    json.dump(to_fleet(), open(deps2["nodes_path"], "w")); json.dump(roster(), open(deps2["roster_path"], "w"))
    P.node_remove(deps2, "na")
    after2 = json.load(open(deps2["roster_path"]))
    check("[8] node_remove(A) with no snapshot of B: the peers move onto B's copies, never purged",
          all(t["node"] == "nb" for p in ("p1", "p2", "p3") for t in after2["peers"][p]["targets"]), after2["peers"])
    d3 = os.path.join(TMP, "rm3"); os.makedirs(d3)
    deps3 = {"nodes_path": os.path.join(d3, "nodes.json"), "roster_path": os.path.join(d3, "users.json"), "stats_dir": d3,
             "node_snaps": {"na": snaps["na"], "nb": {"interfaces": {"awg0": {"down": "Cannot find device", "meta": {}, "peers": []}}}},
             "node_seen": {"nb": time.time()}, "panel_settings": {}}
    r3 = roster()
    r3["peers"]["p5"] = {"id": "p5", "user_id": "u2", "pubkey": PK[4], "psk": PK[6], "title": "nas",
                         "targets": [{"node": "na", "iface": "wg1", "ip": "10.9.0.2"}]}
    json.dump(to_fleet(), open(deps3["nodes_path"], "w")); json.dump(r3, open(deps3["roster_path"], "w"))
    P.node_remove(deps3, "na")
    after3 = json.load(open(deps3["roster_path"]))
    check("[8] node_remove(A): a copy B still waits the key for takes its peers, never purged (F107)",
          after3["peers"].get("p5", {}).get("targets", [{}])[0].get("node") == "nb", after3["peers"].get("p5"))
    check("[8] node_remove(A) while B's awg0 is down: its peers move onto B's copy, never purged (F89)",
          all(t["node"] == "nb" for p in ("p1", "p2", "p3") for t in after3["peers"][p]["targets"]), after3["peers"])
    psd = json.load(open(deps["panel_settings_path"])) if os.path.exists(deps["panel_settings_path"]) else {}
    check("[8] node_remove(A): A's node-keyed settings name B too",
          (psd.get("block_catalog") or {}).get("categories", {}).get("ads", {}).get("enabled_nodes") == ["na", "nb"]
          and [c["disabled_nodes"] for c in psd.get("custom_lists") or []] == [["na", "nb"], []], psd)
    import glob
    arch = glob.glob(os.path.join(d, "archive", "*", "node.json"))
    check("[8] node_remove(A): the archive holds A whole", arch and set(json.load(open(arch[0])).get("ifaces") or {}) == {"awg0", "wg1"}, arch)
    evs = open(os.path.join(d, "events.jsonl")).read() if os.path.exists(os.path.join(d, "events.jsonl")) else \
        "".join(open(x).read() for x in glob.glob(os.path.join(d, "*event*")))
    check("[8] node_remove(A): the take-over is logged", "took over" in evs, evs[-400:])
    d5 = os.path.join(TMP, "rm5"); os.makedirs(d5)
    deps5 = {"nodes_path": os.path.join(d5, "nodes.json"), "roster_path": os.path.join(d5, "users.json"), "stats_dir": d5,
             "node_snaps": {"na": snaps["na"], "nb": snaps["nb"]}, "node_seen": {"nb": time.time()}, "panel_settings": {}}
    f5 = to_fleet(); f5["nb"]["ifaces"]["wg1"]["public_key"] = "Q" * 43 + "="          # a copy from before A's key changed
    json.dump(f5, open(deps5["nodes_path"], "w")); json.dump(roster(), open(deps5["roster_path"], "w"))
    P.node_remove(deps5, "na")
    n5 = json.load(open(deps5["nodes_path"]))
    ev5 = "".join(open(x).read() for x in glob.glob(os.path.join(d5, "*event*")))
    check("[8] node_remove(A) with a stale copy on B: it is removed there, and the event says so (F125)",
          "wg1" not in n5["nb"]["ifaces"] and "old copies removed" in ev5, (n5["nb"].get("ifaces"), ev5[-300:]))


# ── [11] the take-over table ─────────────────────────────────────────────────────────────────────────────────────────
def table_want(rec, akey, live, snap, waits, rep, down, stopped, key):
    """The table of _fo_holds, written again here from its docstring: the first row that matches decides."""
    if rec in ("none", "sys"):
        return "absent"
    if akey == "none":
        return "unsure"                    # A's key unknown — no blessed key, none reported: cannot be judged (F128)
    if rec != "A":                         # another key: stale only against the BLESSED key — a report never condemns (F147)
        return "stale" if akey == "rec" else "unsure"
    if live and snap and rep and not down and not stopped and key == "A":
        return "held"
    return "unsure"


def sec11():
    print("[11] the take-over table — every case, and four invariants")
    import itertools
    bad, inv = [], []
    for rec, akey, live, snap, waits, rep, down, stopped, key in itertools.product(
            ("none", "sys", "X", "A"), ("rec", "rep", "none"), (0, 1), (0, 1), (0, 1), (0, 1), (0, 1), (0, 1), ("A", "", "X")):
        n = fleet()
        if akey != "rec":                  # "rep": A's record not blessed, its box reports the key (F135); "none": neither
            n["na"]["ifaces"]["awg0"]["public_key"] = ""
        n["nb"]["ifaces"] = ({} if rec == "none" else {"awg0": {"system": True, "public_key": "M" * 43 + "="}} if rec == "sys"
                             else {"awg0": {"public_key": KA if rec == "A" else KX, "listen_port": 443}})
        sn = {"na": {"interfaces": {"awg0": snap_iface(key="" if akey == "none" else KA)}}}
        if snap:
            ent = {"meta": {"public_key": {"A": KA, "": "", "X": KX}[key], "subnet": "10.8.0.0/24", "listen_port": 443}, "peers": []}
            if down:
                ent["down"] = "Cannot find device"
            if stopped:
                ent["stopped"] = True
            sn["nb"] = {"interfaces": {"awg0": ent} if rep else {}, **({"ifaces_awaiting_key": ["awg0"]} if waits else {})}
        want = table_want(rec, akey, live, snap, waits, rep, down, stopped, key)
        case = dict(rec=rec, akey=akey, live=live, snap=snap, waits=waits, rep=rep, down=down, stopped=stopped, key=key)
        for assume in (False, True):
            got = P._fo_holds(n, sn, "na", "nb", bool(live), assume)
            exp = "held" if (assume and want == "unsure") else want
            if got != tuple([["awg0"] if c == exp else [] for c in ("held", "absent", "unsure", "stale")]):
                bad.append((case, assume, got, exp))
                continue
            nn, r = json.loads(json.dumps(n)), roster()
            try:
                moved, left, dropped = P.failover_takeover(nn, r, "na", "nb", got, sn)
            except ValueError:
                if exp != "unsure":
                    inv.append((case, assume, "refused without doubt"))
                continue
            if exp == "unsure":
                inv.append((case, assume, "acted in doubt"))
                continue
            on_b = all(t["node"] == "nb" for t in r["peers"]["p1"]["targets"])
            brec = (nn["nb"].get("ifaces") or {}).get("awg0") or {}
            bkey = None if brec.get("system") else brec.get("public_key")
            gone = set(nn["nb"].get("delete") or {}) | (set(n["nb"].get("ifaces") or {}) - set(nn["nb"].get("ifaces") or {}))
            if gone - ({"awg0"} if exp == "stale" else set()):                # I1: only an old copy is ever deleted on B
                inv.append((case, assume, "I1 a take-over deleted %s on B" % sorted(gone)))
            if set(dropped) != gone:                                          # …and every deletion is said (F125)
                inv.append((case, assume, "a deletion on B not returned: %s vs %s" % (dropped, sorted(gone))))
            if on_b != (exp == "held"):                                       # I2: peers move onto what B holds, and only that
                inv.append((case, assume, "I2 peers moved: %s, class %s" % (on_b, exp)))
            if bkey and not on_b:                                             # I3: an ordinary B never keeps a copy unmoved
                inv.append((case, assume, "I3 B kept a copy, peers left on A"))
            # I4: peers land on A's current identity — judged where A HAS one (a blessed key). Without one, a removal keeps
            # the peer records on B's copy rather than purging them (_fo_holds UNSURE, F139/F147): nothing to judge by.
            if on_b and akey == "rec" and bkey != KA:
                inv.append((case, assume, "I4 peers moved onto a copy without A's key"))
    check("[11] _fo_holds follows its table in all 4608 cases (2304 × assume)", not bad, bad[:3])
    check("[11] the take-over keeps the four invariants in every case, and refuses only in doubt", not inv, inv[:3])


# ── [9] reconcile.js ─────────────────────────────────────────────────────────────────────────────────────────────────
def sec9():
    print("[9] reconcile.js")
    if not shutil.which("node"):
        check("[9] node is installed", False)
        return
    now = NOW * 1000
    roster_ = {"users": {"u1": {"name": "ann"}}, "peers": {"p1": {"user_id": "u1", "pubkey": PK[0], "created_at": NOW - 9999,
                                                            "targets": [{"node": "na", "iface": "awg0", "ip": "10.8.0.2"}]}}}
    # R3: a WDTT device (a password, no key) — its read-back is the server's own row (§12.5)
    roster_w = {"users": {"u1": {"name": "ann"}}, "peers": {"p1": {"user_id": "u1", "wdtt_password": "pw1", "created_at": NOW - 9999,
                                                             "targets": [{"node": "na", "iface": "wdtt1", "type": "wdtt"}]}}}
    wrow = lambda on, act="active": {"iface": "wdtt1", "active": act, "passwords": {"pw1": {"online": on, "ip": "10.9.0.5"}}}
    hs = {"public_key": PK[0], "online": True}
    cases = {
        "stale_b_online": ({"na": {"generated_at": NOW - 3600, "interfaces": {"awg0": snap_iface()}},
                            "nb": {"generated_at": NOW, "interfaces": {"awg0": {"meta": {"subnet": "10.8.0.0/24"}, "peers": [hs]}}}},
                           {"na": NOW - 3600, "nb": NOW}, {"na": "nb"}),
        "stale_b_noif": ({"na": {"generated_at": NOW - 3600, "interfaces": {"awg0": snap_iface()}},
                          "nb": {"generated_at": NOW, "interfaces": {}}}, {"na": NOW - 3600, "nb": NOW}, {"na": "nb"}),
        "nomirror": ({"na": {"generated_at": NOW, "interfaces": {"awg0": {"meta": {"subnet": "10.8.0.0/24"}, "peers": [hs]}}}},
                     {"na": NOW}, None),
        "both_live": ({"na": {"generated_at": NOW, "interfaces": {"awg0": {"meta": {"subnet": "10.8.0.0/24"},
                                                                          "peers": [dict(hs, online=False)]}}},
                       "nb": {"generated_at": NOW, "interfaces": {"awg0": {"meta": {"subnet": "10.8.0.0/24"}, "peers": [hs]}}}},
                      {"na": NOW, "nb": NOW}, {"na": "nb"}),
        "stale_b_down": ({"na": {"generated_at": NOW - 3600, "interfaces": {"awg0": snap_iface()}},
                          "nb": {"generated_at": NOW, "interfaces": {"awg0": {"down": "Cannot find device", "meta": {}, "peers": []}}}},
                         {"na": NOW - 3600, "nb": NOW}, {"na": "nb"}),
        "w_stale_b_online": ({"na": {"generated_at": NOW - 3600, "wdtt": [wrow(False)]}, "nb": {"generated_at": NOW, "wdtt": [wrow(True)]}},
                             {"na": NOW - 3600, "nb": NOW}, {"na": "nb"}, "w"),
        "w_online_on_a": ({"na": {"generated_at": NOW, "wdtt": [wrow(True)]}, "nb": {"generated_at": NOW, "wdtt": [wrow(False)]}},
                          {"na": NOW, "nb": NOW}, {"na": "nb"}, "w"),
        "w_online_on_b": ({"na": {"generated_at": NOW, "wdtt": [wrow(False)]}, "nb": {"generated_at": NOW, "wdtt": [wrow(True)]}},
                          {"na": NOW, "nb": NOW}, {"na": "nb"}, "w"),
        "w_stale_b_idle": ({"na": {"generated_at": NOW - 3600, "wdtt": [wrow(False)]}, "nb": {"generated_at": NOW, "wdtt": [wrow(False)]}},
                           {"na": NOW - 3600, "nb": NOW}, {"na": "nb"}, "w"),
        "w_b_down": ({"na": {"generated_at": NOW - 3600, "wdtt": [wrow(False)]}, "nb": {"generated_at": NOW, "wdtt": [wrow(False, "failed")]}},
                     {"na": NOW - 3600, "nb": NOW}, {"na": "nb"}, "w"),
        "w_nomirror": ({"na": {"generated_at": NOW, "wdtt": [wrow(True)]}}, {"na": NOW}, None, "w"),
    }
    js = """
await import(%s);
const { reconcile } = await import(%s);
const cases = %s, rosters = %s, now = %d;
const out = {};
for (const [k, [stats, seen, mirrors, rk]] of Object.entries(cases)) {
  const roster = rosters[rk || "i"];
  const r = reconcile(roster, stats, now, { nodeSeen: seen, nodeStaleMs: 30000, graceMs: 60000, restoreGraceMs: 0, probSince: {},
                                           ...(mirrors ? { mirrors } : {}) });
  const p = r.peers[0], t = p.targets[0];
  out[k] = { status: p.status, t: t.status, served: t.served || null, node: t.node, restorable: t.restorable, orphans: r.orphans.length,
             keys: Object.keys(t).sort() };
}
console.log(JSON.stringify(out));
""" % (json.dumps("file://" + os.path.join(HERE, "spa_env.mjs")), json.dumps("file://" + NEWR), json.dumps(cases),
       json.dumps({"i": roster_, "w": roster_w}), now)
    f = os.path.join(TMP, "rc.mjs"); open(f, "w").write(js)
    o = subprocess.run(["node", f], capture_output=True, text=True)
    if o.returncode:
        check("[9] reconcile ran", False, o.stderr[-800:])
        return
    out = json.loads(o.stdout)
    a = out["stale_b_online"]
    check("[9] A stale, B online: online, served by B, door names A, no orphans",
          a["status"] == "online" and a["served"] == "nb" and a["node"] == "na" and a["orphans"] == 0, a)
    b = out["stale_b_noif"]
    check("[9] A stale, B without the interface: unknown, no Restore", b["t"] == "unknown" and not b["restorable"], b)
    c = out["nomirror"]
    check("[9] no mirrors: no `served` key", "served" not in c["keys"] and c["status"] == "online", c)
    e = out["both_live"]
    check("[9] A live too, the device online on B: served by B, no orphan on A", e["served"] == "nb" and e["orphans"] == 0, e)
    g = out["stale_b_down"]
    check("[9] A stale, B reports the interface down: unknown, no Restore", g["t"] == "unknown" and not g["restorable"], g)
    w = out["w_stale_b_online"]
    check("[9] WDTT: A stale, the password online on B: online, served by B, door names A",
          w["status"] == "online" and w["served"] == "nb" and w["node"] == "na", w)
    w = out["w_online_on_a"]
    check("[9] WDTT: both live, online on A: served by A", w["served"] == "na" and w["status"] == "online", w)
    w = out["w_online_on_b"]
    check("[9] WDTT: both live, online on B: served by B", w["served"] == "nb" and w["status"] == "online", w)
    w = out["w_stale_b_idle"]
    check("[9] WDTT: A stale, B running it, the password online nowhere: served by B, ready (R3 review F6)",
          w["served"] == "nb" and w["t"] == "ready", w)
    w = out["w_b_down"]
    check("[9] WDTT: A stale, B's server down: read on A — unknown", w["served"] == "na" and w["t"] == "unknown", w)
    w = out["w_nomirror"]
    check("[9] WDTT, no mirrors: no `served` key", "served" not in w["keys"] and w["status"] == "online", w)


# ── [10] real panels ─────────────────────────────────────────────────────────────────────────────────────────────────
def start_panel(src_path, tag, nodes, users, vault=None):
    d = os.path.join(TMP, "panel-" + tag)
    state = os.path.join(d, "state"); os.makedirs(state)
    stats = os.path.join(d, "stats"); os.makedirs(stats)
    npath = os.path.join(state, "nodes.json")
    json.dump(nodes, open(npath, "w"))
    json.dump(users, open(os.path.join(state, "users.json"), "w"))
    if vault:                                      # the vault the escrowed keys are sealed to (the preview requires one)
        os.makedirs(os.path.join(state, "subs"))
        json.dump(vault, open(os.path.join(state, "subs", "vault.json"), "w"))
    fleetp = os.path.join(d, "fleet.json")
    json.dump({"nodes_path": npath, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleetp, "w"))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    lg = open(os.path.join(d, "panel.log"), "w+")
    p = subprocess.Popen([sys.executable, src_path], stdout=lg, stderr=subprocess.STDOUT,
                         env={**os.environ, "SWG_PANEL_FLEET": fleetp, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                              "SWG_PANEL_PORT": str(port), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                              "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0", "SWG_NO_REEXEC": "1"})
    PROCS.append(p)
    for _ in range(300):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=2)
            break
        except Exception:
            if p.poll() is not None:
                raise RuntimeError("panel exited: " + open(lg.name).read()[-2000:])
            time.sleep(0.1)
    return port, d


def req(port, path, data=None, token=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            out, code = resp.read(), resp.status
            if resp.headers.get("Content-Encoding") == "gzip":
                out = gzip.decompress(out)
    except urllib.error.HTTPError as e:
        out, code = e.read(), e.code
    return code, json.loads(out or b"{}")


def sync(port, tok, nid, ifaces=None):
    snap = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": ifaces or {},
            "net_deps": {"limits": True, "reach": 2}}
    code, r = req(port, "/api/node/sync", {"snapshot": snap}, tok)
    assert code == 200, (code, r)
    return r


PROCS = []
VOLATILE = {"panel_url", "panel_url_next", "panel_local_port", "server_time", "now", "t"}
NODE_OWN = {"cascade", "fast_lane"}                # a node's own: the planned member (A serving here), its datapath choice


def unmesh(r):
    """A reply with its mesh-link entries (swg_*) left out: the links are each node's own."""
    out = {}
    for k, v in r.items():
        if isinstance(v, dict):
            v = {kk: vv for kk, vv in v.items() if not str(kk).startswith("swg_")}
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            v = [x for x in v if not x.startswith("swg_")]
        if v or not isinstance(v, (dict, list)):
            out[k] = v
    return out


def sec10():
    print("[10] real panels")
    plain = {k: {kk: vv for kk, vv in v.items() if kk != "failover_of"} for k, v in fleet().items()}
    plain["nb"]["ifaces"] = {}
    ref = os.path.join(TMP, "ref-swg-panel-server")
    open(ref, "wb").write(subprocess.run(["git", "-C", ROOT, "show", REF + ":swg-panel-server"], capture_output=True, check=True).stdout)
    ports = []
    for src, tag in ((ref, "refa"), (ref, "refb"), (NEW, "new")):
        ports.append(start_panel(src, tag, plain, roster())[0])
    toks = {port: {n: req(port, "/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in ("na", "nb", "nc")} for port in ports}
    ifs = {"awg0": snap_iface(peers=[(PK[0], True, 10, 10)])}
    for nid in ("na", "nb", "nc"):
        for port in ports:
            sync(port, toks[port][nid], nid, ifs if nid == "na" else None)
    ra, rb, rn = (sync(port, toks[port]["na"], "na", ifs) for port in ports)
    vol = {k for k in set(ra) | set(rb) if json.dumps(ra.get(k), sort_keys=True) != json.dumps(rb.get(k), sort_keys=True)}
    diff = [k for k in set(ra) | set(rn) if k not in vol and json.dumps(ra.get(k), sort_keys=True) != json.dumps(rn.get(k), sort_keys=True)]
    check("[10] no failover node: the sync reply is byte-identical to %s's (but what its own instances disagree on: %s)" % (REF, sorted(vol)),
          list(rn) == list(ra) and not diff and rn.get("desired"), (diff, set(rn) ^ set(ra)))
    # with a failover node — A's interface protected (reach) so B's reply carries dev_reach too
    fo = fleet(); fo["na"]["ifaces"]["awg0"]["reach"] = "user"
    port, d = start_panel(NEW, "fo", fo, roster(), vault={"ivk_enabled": True, "ivk_pub": IVK})
    tk = {n: req(port, "/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in ("na", "nb", "nc")}
    c, o = req(port, "/api/nodes/failover/preflight?node=na")
    check("[10] preflight answers", c == 200 and "refused" in (o.get("data") or {}), (c, o))
    sync(port, tk["nc"], "nc")
    sync(port, tk["na"], "na", ifs)
    sync(port, tk["nb"], "nb", ifs)
    rA = unmesh(sync(port, tk["na"], "na", ifs))
    rB = unmesh(sync(port, tk["nb"], "nb", ifs))
    diff = sorted(k for k in set(rA) | set(rB) if k not in VOLATILE | NODE_OWN
                  and json.dumps(rA.get(k), sort_keys=True) != json.dumps(rB.get(k), sort_keys=True))
    check("[10] B's whole reply equals A's but for the node's own keys", not diff and rA.get("desired", {}).get("awg0"),
          {k: (rA.get(k), rB.get(k)) for k in diff})
    check("[10] the limits and dev_reach are in B's reply", bool(rB.get("limits")) and bool(rB.get("dev_reach")),
          (rB.get("limits"), rB.get("dev_reach")))
    rC = sync(port, tk["nc"], "nc")
    check("[10] a third node gets none of them", not (rC.get("desired") or {}).get("awg0"), rC.get("desired"))
    c, o = req(port, "/api/nodes/failover/resync", {"id": "nb"})
    check("[10] a Re-sync with nothing to repair is an empty success — a repeated call is no error (F157)",
          c == 200 and o["data"]["ifaces"] == [] and o["data"]["vault_needed"] == [], (c, o))
    c, o = req(port, "/api/iface/update", {"node": "nb", "iface": "awg0", "mtu": 1400})
    check("[10] an edit on B is refused at the door", c == 409 and o.get("code") == "failover_read_only", (c, o))
    sync(port, tk["na"], "na", {"awg0": {"down": "Cannot find device", "meta": {}, "peers": []}})
    c, o = req(port, "/api/nodes/failover/detach", {"id": "nb", "take_over": False, "confirm": "hel-2"})
    check("[10] keeping the peers on A while A's awg0 is down and B runs it is refused", c == 409 and o.get("code") == "primary_not_running", (c, o))
    sync(port, tk["na"], "na", {"awg0": snap_iface(peers=[(PK[0], False, 10, 10)])})   # the client is on B alone now
    sync(port, tk["nb"], "nb", {"awg0": {"down": "Cannot find device", "meta": {}, "peers": []}})
    c, o = req(port, "/api/nodes/failover/detach", {"id": "nb", "take_over": True})
    check("[10] a take-over while B reports awg0 down is refused (F89)", c == 409 and o.get("code") == "failover_unsure", (c, o))
    sync(port, tk["nb"], "nb", ifs)
    c, o = req(port, "/api/nodes/failover/detach", {"id": "nb", "take_over": "false"})
    check("[10] a string take_over is refused (F76)", c == 400, (c, o))
    c, o = req(port, "/api/nodes/failover/detach", {"id": "nb", "take_over": False})
    check("[10] keep with clients on B needs the typed name", c == 409 and o.get("code") == "confirm_required", (c, o))
    c, o = req(port, "/api/nodes/failover/detach", {"id": "nb", "take_over": False, "dry_run": True})
    check("[10] a dry run of keep previews it — the copies it removes and that the name will be asked — and changes nothing",
          c == 200 and o["data"].get("preview") and o["data"]["removed"] == ["awg0"] and o["data"]["confirm"] is True
          and "failover_of" in json.load(open(os.path.join(d, "state", "nodes.json")))["nb"], (c, o))
    c, o = req(port, "/api/nodes/failover/detach", {"id": "nb", "confirm": "hel-2"})
    check("[10] detach-keep with A reporting and the name typed is allowed, and names what it removed (F132)",
          c == 200 and o["data"]["moved"] == [] and o["data"].get("removed") == ["awg0"], (c, o))
    nn = json.load(open(os.path.join(d, "state", "nodes.json")))
    check("[10] …B is an ordinary node", "failover_of" not in nn["nb"], nn["nb"])
    rB2 = sync(port, tk["nb"], "nb", ifs)
    check("[10] …and its reply no longer carries A's peers", not (rB2.get("desired") or {}).get("awg0"), rB2.get("desired"))


def sec12():
    print("[12] the detach door and an old copy on B (F136)")
    for vault, want in (({"ivk_enabled": True, "ivk_pub": IVK}, "refused"), (None, "goes on")):
        f = fleet()
        f["nb"]["ifaces"] = {"awg0": {"public_key": "Q" * 43 + "=", "listen_port": 443}}     # from before A's key changed
        port, d = start_panel(NEW, "stale-" + want.replace(" ", ""), f, roster(), vault=vault)
        tk = {n: req(port, "/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in ("na", "nb", "nc")}
        sync(port, tk["na"], "na", {"awg0": snap_iface()})
        sync(port, tk["nb"], "nb", {"awg0": snap_iface(key="Q" * 43 + "=")})
        if want == "goes on":
            c, o = req(port, "/api/nodes/failover/resync", {"id": "nb"})
            check("[12] no vault: Re-sync names the vault as what is missing (F136, F148)", c == 409 and o.get("code") == "vault_needed", (c, o))
        c, o = req(port, "/api/nodes/failover/detach", {"id": "nb", "take_over": True, "dry_run": True})
        if want == "refused":
            check("[12] a dry run is refused the same way", c == 409 and o.get("code") == "failover_stale", (c, o))
        else:
            check("[12] a dry run says what the take-over does, and does nothing",
                  c == 200 and o["data"]["moved"] == [] and o["data"]["left"] == ["awg0"] and o["data"]["removed"] == ["awg0"]
                  and "failover_of" in json.load(open(os.path.join(d, "state", "nodes.json")))["nb"], (c, o))
        c, o = req(port, "/api/nodes/failover/detach", {"id": "nb", "take_over": True, "confirm": "hel-2"})
        if want == "refused":
            check("[12] the vault can rebuild A's key: the take-over waits for a Re-sync", c == 409 and o.get("code") == "failover_stale", (c, o))
            c, o = req(port, "/api/nodes/failover/resync", {"id": "nb"})
            check("[12] …and the Re-sync is offered and runs", c == 200 and o["data"]["ifaces"] == ["awg0"], (c, o))
        else:
            check("[12] no vault to rebuild it: the take-over goes on, the old copy removed, its peers left on A",
                  c == 200 and o["data"]["moved"] == [] and o["data"]["left"] == ["awg0"] and o["data"]["removed"] == ["awg0"], (c, o))
    mv = P._fo_takeover_plan(fleet(), "na", "nb", (["awg0", "gone0"], [], [], []), {"na": {"interfaces": {"awg0": snap_iface()}}})
    check("[12] a held name A no longer has is neither taken nor reported as moved", mv[0] == ["awg0"] and "gone0" not in mv[3], mv)


def sec13():
    print("[13] a Re-sync that repairs one interface and cannot rebuild another (F149)")
    f = fleet()
    f["na"]["ifaces"]["wg1"] = a_iface(public_key=KX, key_blob={"pub": KX, "ct": "c", "vault": "an-older-vault"}, endpoint_host="")
    f["nb"]["ifaces"] = {"awg0": {"public_key": "Q" * 43 + "=", "listen_port": 443}, "wg1": {"public_key": "R" * 43 + "=", "listen_port": 443}}
    port, d = start_panel(NEW, "partial", f, roster(), vault={"ivk_enabled": True, "ivk_pub": IVK})
    tk = {n: req(port, "/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in ("na", "nb", "nc")}
    sync(port, tk["na"], "na", {"awg0": snap_iface(), "wg1": snap_iface(key=KX)})
    sync(port, tk["nb"], "nb", {"awg0": snap_iface(key="Q" * 43 + "="), "wg1": snap_iface(key="R" * 43 + "=")})
    c, o = req(port, "/api/nodes/failover/resync", {"id": "nb"})
    check("[13] Re-sync repairs awg0 and names wg1, whose key the vault cannot rebuild",
          c == 200 and o["data"]["ifaces"] == ["awg0"] and o["data"].get("vault_needed") == ["wg1"], (c, o))


# ── [14] the turn family's servers: copies by kind (docs/FAILOVER-PLAN.md §12, R1) ─────────────────────────────────────
KW = "W" * 43 + "="


def w_inst(**kw):
    ov = {"iface": "wdtt1", "fork": "amurcanov", "listen": "203.0.113.5:56000", "wg_addr": "10.11.0.1/24", "wg_port": 56001,
          "server_pub": KW, "key_blob": {"pub": KW, "ct": "c", "eph": "e", "mac": "m", "vault": IVK}, "dns": ["1.1.1.1"],
          "max_passwords": 20, "params": "", "block": ["ads"], "egress_mode": "smart", "password": "OWNER",
          "adopt_config_dir": "/etc/wdtt", "restart": 1, "stopped": False, "bind_ip": "203.0.113.5", "raw_port": "56010"}
    ov.update(kw)
    return ov


def c_inst(**kw):
    ov = {"iface": "csqtt1", "fork": "csqtt", "listen": "vpn.example.com:56002", "tun_addr": "10.10.0.1/24", "line": "2.5",
          "dns": ["1.1.1.1"], "max_passwords": 20, "block": ["torrents"], "egress_mode": "smart", "password": "OWNER",
          "web_pass": "WEB", "restart": 2, "stopped": False}
    ov.update(kw)
    return ov


def w_row(iface="wdtt1", pub=KW, active="active", online=(), **kw):
    r = {"iface": iface, "active": active, "server_pub": pub, "stopped": False,
         "passwords": {pw: {"online": True} for pw in online}}
    r.update(kw)
    return r


def t_fleet():
    n = fleet()
    n["na"]["wdtt"] = {"wdtt1": w_inst()}
    n["na"]["csqtt"] = {"csqtt1": c_inst()}
    return n


def sec14():
    print("[14] the turn family's servers")
    n = t_fleet()
    snaps = {"na": {"interfaces": {"awg0": snap_iface()}, "wdtt": [w_row()], "csqtt": [w_row("csqtt1", pub="")]}}
    seen = {"na": NOW, "nb": NOW}
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    bw, bc = (n["nb"].get("wdtt") or {}).get("wdtt1") or {}, (n["nb"].get("csqtt") or {}).get("csqtt1") or {}
    check("[14] a WDTT server is cloned with A's identity — the escrow blob as the HOLD, its server key",
          bw.get("key_blob") == w_inst()["key_blob"] and bw.get("server_pub") == KW, bw)
    check("[14] …its settings follow, `listen` verbatim (noded binds the wildcard for a host not on the box)",
          bw.get("listen") == "203.0.113.5:56000" and bw.get("wg_port") == 56001 and bw.get("max_passwords") == 20
          and bw.get("block") == ["ads"] and bw.get("raw_port") == "56010", bw)
    check("[14] …never its owner password, adopt marker, one-shot requests or box pin",
          not any(k in bw for k in ("password", "adopt_config_dir", "restart", "stopped", "bind_ip")), sorted(bw))
    check("[14] a csqtt server (no identity) is cloned too, never its owner or web password",
          bc.get("listen") == "vpn.example.com:56002" and bc.get("line") == "2.5" and bc.get("tun_addr") == "10.10.0.1/24"
          and not any(k in bc for k in ("password", "web_pass", "restart", "stopped")), bc)
    n["na"]["wdtt"]["wdtt1"]["max_passwords"] = 40
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[14] a change on A follows", n["nb"]["wdtt"]["wdtt1"].get("max_passwords") == 40, n["nb"]["wdtt"]["wdtt1"])
    n["na"]["wdtt"]["wdtt1"]["title"], n["na"]["csqtt"]["csqtt1"]["title"] = "Calls", "Office"
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[14] …the title too: B's card names it as A's does (R3 review F7)",
          n["nb"]["wdtt"]["wdtt1"].get("title") == "Calls" and n["nb"]["csqtt"]["csqtt1"].get("title") == "Office",
          (n["nb"]["wdtt"]["wdtt1"].get("title"), n["nb"]["csqtt"]["csqtt1"].get("title")))

    n2 = t_fleet(); n2["na"]["wdtt"]["wdtt1"]["key_blob"]["vault"] = "an-older-vault"
    P.failover_mirror(DEPS, n2, "nb", snaps, seen, now=NOW)
    check("[14] a WDTT whose key the vault held now cannot rebuild is not cloned",
          "wdtt1" not in (n2["nb"].get("wdtt") or {}), n2["nb"].get("wdtt"))

    # holds: B's report of each server decides, by the kind's own test
    def holds(brows):
        sn = dict(snaps, nb={"interfaces": {"awg0": snap_iface()}, "wdtt": brows[0], "csqtt": brows[1]})
        return P._fo_holds(n, sn, "na", "nb", True)
    h = holds(([w_row()], [w_row("csqtt1", pub="")]))
    check("[14] a server B runs with A's key is held; a csqtt server B runs is held", {"wdtt1", "csqtt1"} <= set(h[0]), h)
    h = holds(([w_row(await_restore=True)], [w_row("csqtt1", pub="", stopped=True)]))
    check("[14] waiting for its key, or stopped: unsure — never moved, never deleted", {"wdtt1", "csqtt1"} <= set(h[2]), h)
    h = holds(([w_row(await_restore=True, active="inactive", pub="")], []))   # the row noded really sends while it waits (F14)
    check("[14] …the waiting row as noded sends it (inactive, no key): unsure", "wdtt1" in h[2] and "wdtt1" not in h[0], h)
    h = holds(([w_row(pub=KX)], []))
    check("[14] B running another WDTT key: not held", "wdtt1" not in h[0] and "wdtt1" in h[2], h)
    nst = t_fleet(); P.failover_mirror(DEPS, nst, "nb", snaps, seen, now=NOW)
    nst["nb"]["wdtt"]["wdtt1"]["server_pub"] = KX; nst["nb"]["wdtt"]["wdtt1"]["key_blob"] = {"pub": KX, "ct": "c"}
    check("[14] B's record of another identity than A's blessed one: stale", "wdtt1" in P._fo_holds(nst, snaps, "na", "nb", True)[3])

    # status rows carry their kind and the server's own codes
    fv = P.failover_view(n, roster(), "na", "nb", dict(snaps, nb={"interfaces": {"awg0": snap_iface()}, "wdtt": [w_row(await_restore=True)]}),
                         seen, frozenset(), now=NOW, ivk=IVK)
    rows = {r["iface"]: r for r in fv["rows"]}
    check("[14] status: WDTT waiting for its key, csqtt not reported yet — each row says its kind",
          rows.get("wdtt1", {}).get("why") == "awaiting_key" and rows["wdtt1"].get("kind") == "wdtt"
          and rows.get("csqtt1", {}).get("why") == "creating" and rows["csqtt1"].get("kind") == "csqtt", fv["rows"])

    # drop: A deleted it — only while A reports, and its own report agrees
    n3 = t_fleet(); P.failover_mirror(DEPS, n3, "nb", snaps, seen, now=NOW)
    del n3["na"]["wdtt"]["wdtt1"]
    sn3 = dict(snaps, na={"interfaces": {"awg0": snap_iface()}, "wdtt": [], "csqtt": [w_row("csqtt1", pub="")]})
    P.failover_mirror(DEPS, n3, "nb", sn3, {"na": NOW - 10_000, "nb": NOW}, now=NOW)
    check("[14] a dead primary removes nothing", "wdtt1" in (n3["nb"].get("wdtt") or {}), n3["nb"].get("wdtt"))
    P.failover_mirror(DEPS, n3, "nb", sn3, seen, now=NOW)
    check("[14] A live and its report agreeing: B's server is dropped as its delete door drops it",
          "wdtt1" not in (n3["nb"].get("wdtt") or {}) and "wdtt1" in (n3["nb"].get("wdtt_delete") or {}), n3["nb"])
    n3["na"]["wdtt"] = {"wdtt1": w_inst()}
    P.failover_mirror(DEPS, n3, "nb", snaps, seen, now=NOW)
    check("[14] …and no re-clone while that delete is in flight", "wdtt1" not in (n3["nb"].get("wdtt") or {}), n3["nb"].get("wdtt"))

    # serving counts the servers' clients
    sv = {"na": {"interfaces": {"awg0": snap_iface()}, "wdtt": [w_row()]},
          "nb": {"interfaces": {"awg0": snap_iface()}, "wdtt": [w_row(online=("p", "q", "r"))]}}
    check("[14] WDTT clients count for who serves: three on B, none on A → B serves",
          P.failover_idle(n, sv, seen, now=NOW) == frozenset({"na"}), P.failover_idle(n, sv, seen, now=NOW))

    # the reply: B's instances, A's passwords
    r = roster()
    r["peers"]["pw"] = {"id": "pw", "user_id": "u1", "pubkey": "", "title": "phone-wdtt", "wdtt_password": "PW1",
                        "targets": [{"node": "na", "iface": "wdtt1", "type": "wdtt"}]}
    r["peers"]["pc"] = {"id": "pc", "user_id": "u1", "pubkey": "", "title": "phone-csq", "csqtt_password": "PC1",
                        "targets": [{"node": "na", "iface": "csqtt1", "type": "csqtt"}]}
    wd = P._wdtt_reply(r, n, "nb", "", "na"); cd = P._csqtt_reply(r, n, "nb", "", None, "na")
    check("[14] B's WDTT reply: its instance, A's passwords, A's escrow blob as the hold",
          "PW1" in ((wd.get("wdtt1") or {}).get("passwords") or {}) and (wd.get("wdtt1") or {}).get("key_blob") == w_inst()["key_blob"]
          and "password" not in (wd.get("wdtt1") or {}), wd)
    check("[14] B's csqtt reply: A's passwords", "PC1" in ((cd.get("csqtt1") or {}).get("passwords") or {}), cd)
    check("[14] without rid, B serves nobody's passwords (the roster never names B)",
          not ((P._wdtt_reply(r, n, "nb", "").get("wdtt1") or {}).get("passwords")), P._wdtt_reply(r, n, "nb", ""))

    # the doors
    f = lambda path, body: P.failover_ro_refusal(path, body, n)
    check("[14] the browser's re-seal of B's WDTT identity is allowed", f("/api/wdtt/restore", {"node": "nb", "iface": "wdtt1"}) is None)
    check("[14] editing, deleting or fresh-recreating a server on B is refused",
          all((f(p_, {"node": "nb", "iface": "wdtt1"}) or [0])[0] == 409
              for p_ in ("/api/wdtt/set", "/api/wdtt/delete", "/api/wdtt/recreate-fresh", "/api/csqtt/set", "/api/csqtt/delete")))

    # take-over: the server's targets move with it, A's record goes
    nt = t_fleet(); P.failover_mirror(DEPS, nt, "nb", snaps, seen, now=NOW)
    sn = dict(snaps, nb={"interfaces": {"awg0": snap_iface()}, "wdtt": [w_row()], "csqtt": [w_row("csqtt1", pub="")]})
    rt = json.loads(json.dumps(r))
    moved, left, removed = P.failover_takeover(nt, rt, "na", "nb", P._fo_holds(nt, sn, "na", "nb", True), sn)
    check("[14] take-over moves the servers and their users to B",
          {"wdtt1", "csqtt1"} <= set(moved) and rt["peers"]["pw"]["targets"][0]["node"] == "nb"
          and rt["peers"]["pc"]["targets"][0]["node"] == "nb", (moved, left, rt["peers"]["pw"]))
    check("[14] …A's records go as their delete doors drop them, B's stay as B's own",
          "wdtt1" not in (nt["na"].get("wdtt") or {}) and "wdtt1" in (nt["na"].get("wdtt_delete") or {})
          and "wdtt1" in nt["nb"]["wdtt"] and "failover_of" not in nt["nb"], (nt["na"].get("wdtt"), nt["nb"].get("wdtt")))
    for fam, n_ in (("wdtt", "wdtt1"), ("csqtt", "csqtt1")):                 # each kind (F48)
        for lst, want in (("0.0.0.0:56000", "a.example.com:56000"), ("[2001:db8::1]:56000", "0.0.0.0:56000"),
                          ("[::]:56000", "[::]:56000"), (None, None)):
            nx = t_fleet()
            if lst is None:
                del nx["na"][fam][n_]["listen"]
            else:
                nx["na"][fam][n_]["listen"] = lst
            P.failover_mirror(DEPS, nx, "nb", snaps, seen, now=NOW)
            try:
                P.failover_takeover(nx, json.loads(json.dumps(r)), "na", "nb", P._fo_holds(nx, sn, "na", "nb", True), sn)
                got = nx["nb"][fam][n_].get("listen")
            except Exception as e:
                got = "raised %r" % e
            check("[14] take-over of a %s server listening on %s: %s (F37, F39, F42, F44)" % (fam, lst, want or "nothing to move, no error"),
                  got == want, got)
    check("[14] …a server A served on its own IP listens on every address of B's now (its links dial B, F3); a domain stays",
          nt["nb"]["wdtt"]["wdtt1"].get("listen") == "0.0.0.0:56000" and nt["nb"]["csqtt"]["csqtt1"].get("listen") == "vpn.example.com:56002",
          (nt["nb"]["wdtt"]["wdtt1"].get("listen"), nt["nb"]["csqtt"]["csqtt1"].get("listen")))

    # the fleet's subnet check: B's copy is A's subnet, not a second use — A's own servers stay editable
    ns = t_fleet(); P.failover_mirror(DEPS, ns, "nb", snaps, seen, now=NOW)
    sd = {"node_snaps": {}}
    check("[14] editing A's WDTT or csqtt server is not refused for B's copy of its subnet",
          not P.subnet_fleet_conflict(sd, ns, "10.11.0.1/24", skip_node="na", skip_iface="wdtt1")
          and not P.subnet_fleet_conflict(sd, ns, "10.10.0.1/24", skip_node="na", skip_iface="csqtt1"), ns["nb"].get("wdtt"))
    check("[14] …while another node taking that subnet is still refused",
          bool(P.subnet_fleet_conflict(sd, ns, "10.11.0.1/24", skip_node="nc", skip_iface="wdtt9")))

    # the preview
    pf = P.failover_preflight({"nodes_path": "", "roster_path": ""}, t_fleet(), "na", snaps, {"na": NOW})
    check("[14] the preview no longer files WDTT/csqtt as not copied",
          not [x for x in pf["warn"]["not_mirrored"] if x["kind"] in ("wdtt", "csqtt")], pf["warn"]["not_mirrored"])
    check("[14] …it names their ports — WDTT's raw port too — and a server clients reach by IP",
          {"iface": "wdtt1", "kind": "wdtt", "port": 56000} in pf["warn"]["ports"] and {"iface": "wdtt1", "kind": "wdtt", "port": 56010} in pf["warn"]["ports"]
          and {"iface": "csqtt1", "kind": "csqtt", "port": 56002} in pf["warn"]["ports"]
          and any(x["iface"] == "wdtt1" for x in pf["warn"]["ip_endpoint"])
          and not any(x["iface"] == "csqtt1" for x in pf["warn"]["ip_endpoint"]), pf["warn"])
    _res = P._fo_resolves_to
    P._fo_resolves_to = lambda h, ips: False         # the domain resolves elsewhere (no DNS in a gate; a public node IP:
    #                                                 a documentation range is private to ipaddress)
    try:
        pf = P.failover_preflight({"nodes_path": "", "roster_path": ""}, t_fleet(), "na",
                                  {"na": dict(snaps["na"], node_ips=["93.184.216.34"])}, {"na": NOW}, resolve=True)
    finally:
        P._fo_resolves_to = _res
    check("[14] …a server whose domain does not point at A: the dns warning names its kind (R3 review F8)",
          {"iface": "csqtt1", "kind": "csqtt", "host": "vpn.example.com"} in pf["warn"]["dns"], pf["warn"]["dns"])
    nv = t_fleet(); nv["na"]["wdtt"]["wdtt1"]["key_blob"]["vault"] = "an-older-vault"
    pf = P.failover_preflight({"nodes_path": "", "roster_path": ""}, nv, "na", snaps, {"na": NOW})
    check("[14] a WDTT whose key the vault cannot rebuild is refused, as an interface is",
          any(x.get("iface") == "wdtt1" and x.get("kind") == "wdtt" for x in pf["refused"]), pf["refused"])

    # card review round 1
    nw = t_fleet(); nw["na"]["wdtt"]["wdtt1"]["listen"] = "0.0.0.0:56000"
    pf = P.failover_preflight({"nodes_path": "", "roster_path": ""}, nw, "na", snaps, {"na": NOW})
    check("[14] a server listening on every address is dialled at the node's domain: no IP warning (F9)",
          not any(x["iface"] == "wdtt1" for x in pf["warn"]["ip_endpoint"])
          and next(k for k in P._FO_KINDS if getattr(k, "fam", "") == "wdtt").dial_host(nw["na"], nw["na"]["wdtt"]["wdtt1"], {}, "wdtt1") == "a.example.com", pf["warn"]["ip_endpoint"])
    try:
        P.failover_idle(n, {"na": {"wdtt": [{"iface": ["x"]}, {"iface": "wdtt1", "passwords": ["a"]}]},
                            "nb": {"csqtt": [{"iface": "csqtt1", "passwords": "s"}]}}, seen, now=NOW)
        ok = True
    except Exception as e:
        ok = e
    check("[14] an odd-shaped server row (a list for a name, a list for passwords) is skipped, never raised on (F4)", ok is True, ok)
    nfw = t_fleet(); P.failover_mirror(DEPS, nfw, "nb", snaps, seen, now=NOW)
    fv = P.failover_view(nfw, roster(), "na", "nb", dict(snaps, nb={"interfaces": {"awg0": snap_iface()}, "udp_ports": "443,51820-51899",
                                                                  "wdtt": [w_row(), w_row("wdtt5")], "csqtt": [w_row("csqtt1", pub="")]}),
                         seen, frozenset(), now=NOW, ivk=IVK)
    rows = {r["iface"]: r for r in fv["rows"]}
    check("[14] a server port outside B's declared firewall range: firewall, as an interface's (F6)",
          rows.get("wdtt1", {}).get("why") == "firewall" and rows.get("csqtt1", {}).get("why") == "firewall", fv["rows"])
    check("[14] a server B runs that the panel holds no record of: listed as unmanaged (F12)",
          any(p.get("kind") == "unmanaged" and "wdtt5" in p.get("ifaces", []) for p in fv["problems"]), fv["problems"])
    fv = P.failover_view(nfw, roster(), "na", "nb", dict(snaps, nb={"interfaces": {"awg0": snap_iface()},
                                                                  "wdtt": [w_row()], "csqtt": [w_row("csqtt1", pub="")]}),
                         seen, frozenset(), now=NOW, ivk=IVK)
    rows = {r["iface"]: r for r in fv["rows"]}
    check("[14] a copy running as A's whose clients dial A's IP: a problem, never ready — a DNS change can't move them "
          "(ip_dial + the host, operator 2026-11-16); one on a name stays ready",
          rows.get("wdtt1", {}).get("why") == "ip_dial" and rows["wdtt1"].get("host") == "203.0.113.5"
          and rows["wdtt1"].get("state") == "problem" and "csqtt1" not in rows, fv["rows"])
    _bs = {"interfaces": {"awg0": snap_iface()}, "wdtt": [w_row()], "csqtt": [w_row("csqtt1", pub="")]}
    fv = P.failover_view(nfw, roster(), "na", "nb", {"nb": _bs}, seen, frozenset(), now=NOW, ivk=IVK)
    rows = {r["iface"]: r for r in fv["rows"]}
    check("[14] …with no report of A's, an IP the record proves is still judged (ip_dial verify F7)",
          rows.get("wdtt1", {}).get("why") == "ip_dial" and rows["wdtt1"].get("host") == "203.0.113.5", fv["rows"])
    _wk = next(k for k in P._FO_KINDS if getattr(k, "fam", "") == "wdtt")
    _dh = _wk.dial_host
    _wk.dial_host = lambda *a, **k: ""              # a host known only from A's report
    try:
        fv0 = P.failover_view(nfw, roster(), "na", "nb", {"nb": _bs}, seen, frozenset(), now=NOW, ivk=IVK)
        fv1 = P.failover_view(nfw, roster(), "na", "nb", dict(snaps, nb=_bs), seen, frozenset(), now=NOW, ivk=IVK)
    finally:
        _wk.dial_host = _dh
    check("[14] …while NO host is judged only on a report of A's — a report confirms, never condemns (ip_dial review F2)",
          not any(r.get("why") == "ip_dial" for r in fv0["rows"])
          and any(r.get("why") == "ip_dial" and r["iface"] == "wdtt1" and r.get("host") == "" for r in fv1["rows"]),
          (fv0["rows"], fv1["rows"]))
    nfd = t_fleet(); P.failover_mirror(DEPS, nfd, "nb", snaps, seen, now=NOW)
    next(k for k in P._FO_KINDS if getattr(k, "fam", "") == "wdtt").drop(nfd["nb"], "wdtt1", NOW)   # a Re-sync's drop (F47: by kind)
    fv = P.failover_view(nfd, roster(), "na", "nb", dict(snaps, nb={"interfaces": {"awg0": snap_iface()}, "wdtt": [w_row()]}),
                         seen, frozenset(), now=NOW, ivk=IVK)
    check("[14] …never one whose delete is staged — a Re-sync or a drop in flight (F36)",
          not any("wdtt1" in p.get("ifaces", []) for p in fv["problems"]), fv["problems"])
    fv = P.failover_view(t_fleet(), roster(), "na", "nb", dict(snaps, nb={"interfaces": {"awg0": snap_iface()}}),
                         seen, frozenset(), now=NOW, ivk=IVK)
    rows = {r["iface"]: r for r in fv["rows"]}
    check("[14] a csqtt copy not made yet is being created, never \"waiting for the vault\"; a WDTT one waits for its key (F32)",
          rows.get("csqtt1", {}).get("why") == "creating" and rows.get("wdtt1", {}).get("why") == "no_copy", fv["rows"])
    check("[14] an interface door naming a server copy on B is refused (F31)",
          (P.failover_ro_refusal("/api/iface/delete", {"node": "nb", "iface": "wdtt1"}, n) or [0])[0] == 409)
    rl = roster()
    rl["peers"]["pw"] = {"id": "pw", "user_id": "u1", "pubkey": "", "title": "phone-wdtt", "wdtt_password": "PW1",
                         "targets": [{"node": "na", "iface": "wdtt1", "type": "wdtt"}]}
    dl = os.path.join(TMP, "ledger14"); os.makedirs(dl)
    json.dump(rl, open(os.path.join(dl, "users.json"), "w"))
    L = P.TrafficLedger()
    L.start({"roster_path": os.path.join(dl, "users.json"), "panel_settings": {}}, now=NOW, writer=False)
    L.ingest("na", {"interfaces": {}}, now=NOW, mono=1.0, pairs=(("na", "nb"),))
    check("[14] the ledger claims a WDTT password's counter on B for the device (volume limits there, F1)",
          L.map.get(("nb", "wdtt1", "PW1")) == "pw", sorted(k for k in L.map if k[0] == "nb"))
    hp = os.path.join(TMP, "holds14.json")
    json.dump({"na|wdtt:amurcanov": {"tag": "1.0", "at": 1}, "nb|csqtt:2.5": {"tag": "keep", "at": 1},
               "na|csqtt:2.5": {"tag": "2.5.1", "at": 1}}, open(hp, "w"))
    _hp, P.TURN_HOLDS_PATH = P.TURN_HOLDS_PATH, hp
    try:
        P.failover_carry_settings({"panel_settings": {}}, "na", "nb")
        hd = json.load(open(hp))
    finally:
        P.TURN_HOLDS_PATH = _hp
    check("[14] a take-over carries the builds A is held on to B, never over one of B's own (F2)",
          hd.get("nb|wdtt:amurcanov", {}).get("tag") == "1.0" and hd.get("nb|csqtt:2.5", {}).get("tag") == "keep", hd)

    _tl, _hg = dict(P.TURN_LATEST), P._turn_hold_get
    try:
        P.TURN_LATEST["forks"] = {"amurcanov": "9.9"}
        P._turn_hold_get = lambda nid_, key_: None
        ur = {(x["node"], x["kind"]) for x in P.turn_updates_view(
            {"node_snaps": {x: {"wdtt": [{"iface": "wdtt1", "fork": "amurcanov", "version": "1.0"}]} for x in ("na", "nb")}}, t_fleet())}
    finally:
        P.TURN_LATEST.clear(); P.TURN_LATEST.update(_tl); P._turn_hold_get = _hg
    check("[14] the updates sheet lists A's WDTT, never B's — B runs A's build, and its Update is refused there (F8)",
          ur == {("na", "wdtt")}, sorted(ur))

    # the sync: B is never asked to seal its own WDTT identity — its seal would overwrite the clone's blob (§12.4)
    port, d = start_panel(NEW, "turn-family", t_fleet(), r, vault={"ivk_enabled": True, "ivk_pub": IVK})
    tk = {x: req(port, "/api/nodes/rotate", {"id": x})[1]["data"]["token"] for x in ("na", "nb", "nc")}

    def tsync(nid, wrows):
        snap = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": {"awg0": snap_iface()},
                "net_deps": {"limits": True, "reach": 2}, "wdtt": wrows, "csqtt": []}
        c_, r_ = req(port, "/api/node/sync", {"snapshot": snap}, tk[nid])
        assert c_ == 200, (c_, r_)
        return r_
    tsync("na", [w_row()])
    tsync("nb", [])
    rb = tsync("nb", [w_row(pub=KX)])                  # B's box runs an identity of its own (a fresh install)
    check("[14] B is never asked to seal its own WDTT identity", "wdtt1" not in (rb.get("wdtt_vault_want") or []),
          rb.get("wdtt_vault_want"))
    check("[14] …and its reply carries A's identity as the hold, with A's users (F15: the handler passes rid)",
          ((rb.get("wdtt") or {}).get("wdtt1") or {}).get("key_blob", {}).get("pub") == KW
          and "PW1" in (((rb.get("wdtt") or {}).get("wdtt1") or {}).get("passwords") or {}), (rb.get("wdtt") or {}).get("wdtt1"))
    tsync("nb", [w_row(adopt_users={"LEFTOVER": {"ip": "10.11.0.9"}})])   # a re-used spare's old store, offered (F7)
    rr = json.load(open(os.path.join(d, "state", "users.json")))
    check("[14] a failover node imports no users: the roster never names it (F7)",
          not any((t or {}).get("node") == "nb" for p in (rr.get("peers") or {}).values() for t in (p.get("targets") or [])),
          [p.get("targets") for p in (rr.get("peers") or {}).values()])

    # the detach door: a WDTT copy of another identity than A's, which the vault can rebuild, waits for a Re-sync —
    # the take-over never drops it on the interfaces' predicate (it found no interface by that name)
    fs = t_fleet()
    fs["nb"]["wdtt"] = {"wdtt1": w_inst(server_pub=KX, key_blob={"pub": KX, "ct": "c", "eph": "e", "mac": "m", "vault": IVK})}
    port, d = start_panel(NEW, "turn-stale", fs, roster(), vault={"ivk_enabled": True, "ivk_pub": IVK})
    tk = {x: req(port, "/api/nodes/rotate", {"id": x})[1]["data"]["token"] for x in ("na", "nb", "nc")}
    tsync("na", [w_row()])
    tsync("nb", [w_row(pub=KX)])
    c, o = req(port, "/api/nodes/failover/detach", {"id": "nb", "take_over": True, "dry_run": True})
    check("[14] a stale WDTT copy the vault can rebuild: the take-over waits for a Re-sync",
          c == 409 and o.get("code") == "failover_stale" and "wdtt1" in (o.get("error") or ""), (c, o))


TPS = "vk-turn-proxy-cacggghp-56100"


def tp_row(svc=TPS, **kw):
    r = {"service": svc, "listen": "0.0.0.0:56100", "connect": "127.0.0.1:443", "params": "-wrap -wrap-key abc",
         "wrap_key": "abc", "title": "main", "version": "v1.2", "running": True, "bind_ip": "203.0.113.5"}
    r.update(kw)
    return r


def sec15():
    print("[15] the turn proxies")
    seen = {"na": NOW, "nb": NOW}
    P._FO_TP_TRIED.clear()
    sa = {"interfaces": {"awg0": snap_iface()}, "turn_proxies": [tp_row()]}
    sb = {"interfaces": {"awg0": snap_iface()}, "turn_proxies": [], "arch": "amd64"}
    n = fleet()
    P.failover_mirror(DEPS, n, "nb", {"na": sa, "nb": sb}, seen, now=NOW)
    rq = (n["nb"].get("turn") or {}).get(TPS) or {}
    check("[15] a proxy A reports and B does not: B gets an install of it — A's listen verbatim, its connect, params (A's "
          "wrap key, which A's clients hold) and title",
          rq.get("action") == "install" and rq.get("listen") == "0.0.0.0:56100" and rq.get("connect") == "127.0.0.1:443"
          and rq.get("params") == "-wrap -wrap-key abc" and rq.get("title") == "main" and rq.get("owner"), rq)
    check("[15] …never A's \"Listen on\" pin (B's addresses are its own), and no pin the panel holds no bytes for",
          "bind_ip" not in rq and "pin" not in rq, rq)
    check("[15] …and a pass with the install pending changes nothing",
          P.failover_mirror(DEPS, n, "nb", {"na": sa, "nb": sb}, seen, now=NOW) is False, n["nb"].get("turn"))
    n["nb"]["turn"][TPS]["at"] = NOW - 100
    P.failover_mirror(DEPS, n, "nb", {"na": sa, "nb": sb}, seen, now=NOW)
    check("[15] …an install already staged is left as it is (its age is what clears a failed one)",
          n["nb"]["turn"][TPS]["at"] == NOW - 100, n["nb"]["turn"][TPS])
    n["nb"]["turn"].pop(TPS)                     # the install cleared without the service (a failed download)
    P.failover_mirror(DEPS, n, "nb", {"na": sa, "nb": sb}, seen, now=NOW)
    check("[15] an install that cleared without the service is not staged again at once (noded runs it inline, R2 F2)",
          not (n["nb"].get("turn") or {}).get(TPS), n["nb"].get("turn"))
    P._FO_TP_TRIED[("nb", TPS)] -= P.FO_TP_RETRY
    P.failover_mirror(DEPS, n, "nb", {"na": sa, "nb": sb}, seen, now=NOW)
    check("[15] …and is, once FO_TP_RETRY has passed", ((n["nb"].get("turn") or {}).get(TPS) or {}).get("action") == "install",
          n["nb"].get("turn"))
    P._FO_TP_TRIED.clear()
    nd = fleet()
    P.failover_mirror(DEPS, nd, "nb", {"na": sa, "nb": sb}, {"na": NOW - 10_000, "nb": NOW}, now=NOW)
    check("[15] A not reporting: installed from its last snapshot all the same (adding is safe)",
          TPS in (nd["nb"].get("turn") or {}), nd["nb"].get("turn"))
    for flag in ("turn_capable", "turn_manage"):
        nx = fleet()
        P.failover_mirror(DEPS, nx, "nb", {"na": sa, "nb": dict(sb, **{flag: False})}, seen, now=NOW)
        check("[15] B says it cannot run turn proxies (%s): nothing staged" % flag, not nx["nb"].get("turn"), nx["nb"].get("turn"))
    nx = fleet()
    P.failover_mirror(DEPS, nx, "nb", {"na": sa}, seen, now=NOW)
    check("[15] B never reported: nothing staged", not nx["nb"].get("turn"), nx["nb"].get("turn"))
    P._FO_TP_TRIED.clear()
    nx = fleet()
    _mark = {k: v for k, v in tp_row(installing=True, running=False, owner="cacggghp/vk-turn-proxy").items()
             if k in ("service", "listen", "connect", "owner", "running", "installing")}   # noded's marker row (swg-noded:2046)
    P.failover_mirror(DEPS, nx, "nb", {"na": dict(sa, turn_proxies=[_mark]), "nb": sb}, seen, now=NOW)
    check("[15] a proxy A is still installing (no params yet): not copied until A runs it (R2 F36)",
          not nx["nb"].get("turn"), nx["nb"].get("turn"))
    for bad in ("0.0.0.0:\u00b2", "0.0.0.0:" + "1" * 5000):
        try:
            ok = P.valid_hostport(bad) is False
        except Exception as e:
            ok = repr(e)
        check("[15] an odd port in A's report is refused, never raised on (R2 F3): %r" % bad[:12], ok is True, ok)
    P._FO_TP_TRIED.clear()
    nx = fleet(); nx["nb"]["turn"] = {TPS: {"action": "delete", "at": NOW}}
    P.failover_mirror(DEPS, nx, "nb", {"na": sa, "nb": sb}, seen, now=NOW)
    check("[15] a request of B's own for that service (a delete): the node finishes it before any install",
          nx["nb"]["turn"][TPS].get("action") == "delete", nx["nb"]["turn"])
    P._FO_TP_TRIED.clear()

    # follow: B reports it — as each box reports it configured, so the comparison settles
    nf = fleet()
    sbr = dict(sb, turn_proxies=[tp_row(bind_ip="")])
    P.failover_mirror(DEPS, nf, "nb", {"na": sa, "nb": sbr}, seen, now=NOW)       # the first pass clones the interface
    check("[15] B reporting the same proxy: steady, nothing written",
          P.failover_mirror(DEPS, nf, "nb", {"na": sa, "nb": sbr}, seen, now=NOW) is False and not nf["nb"].get("turn"),
          nf["nb"].get("turn"))
    sa2 = dict(sa, turn_proxies=[tp_row(listen="a.example.com:56200", params="-wrap  -wrap-key   xyz")])
    P.failover_mirror(DEPS, nf, "nb", {"na": sa2, "nb": sbr}, seen, now=NOW)
    mq = (nf["nb"].get("turn") or {}).get(TPS) or {}
    check("[15] A's listen and params change: one manage carrying A's values",
          mq.get("action") == "manage" and mq.get("listen") == "a.example.com:56200" and mq.get("params") == "-wrap  -wrap-key   xyz"
          and mq.get("connect") == "127.0.0.1:443" and "bind_ip" not in mq, mq)
    nf2 = fleet()
    P.failover_mirror(DEPS, nf2, "nb", {"na": sa, "nb": dict(sb, turn_proxies=[tp_row(params=" -wrap -wrap-key abc ")])}, seen, now=NOW)
    check("[15] the same params spaced otherwise: no manage (a restart of a serving proxy for nothing)",
          not nf2["nb"].get("turn"), nf2["nb"].get("turn"))
    nf3 = fleet()
    P.failover_mirror(DEPS, nf3, "nb", {"na": dict(sa, turn_proxies=[tp_row(title="renamed")]), "nb": sbr}, seen, now=NOW)
    check("[15] a title alone: the title request, which never restarts the proxy",
          ((nf3["nb"].get("turn") or {}).get(TPS) or {}).get("action") == "title"
          and nf3["nb"]["turn"][TPS].get("title") == "renamed", nf3["nb"].get("turn"))
    nfx = fleet()
    P.failover_mirror(DEPS, nfx, "nb", {"na": sa2, "nb": dict(sbr, turn_manage=False)}, seen, now=NOW)
    check("[15] a B that cannot manage proxies gets no manage it must fail, every pass (R2 F13)", not nfx["nb"].get("turn"),
          nfx["nb"].get("turn"))
    nf4 = fleet(); nf4["nb"]["turn"] = {TPS: {"action": "reinstall", "at": NOW, "auto": True}}
    P.failover_mirror(DEPS, nf4, "nb", {"na": sa2, "nb": sbr}, seen, now=NOW)
    check("[15] a request of B's in flight (an auto-update): the follow waits for it",
          nf4["nb"]["turn"][TPS].get("action") == "reinstall", nf4["nb"]["turn"])

    # never deleted: A live and its report agreeing does not drop a proxy
    ng = fleet()
    P.failover_mirror(DEPS, ng, "nb", {"na": dict(sa, turn_proxies=[]), "nb": sbr}, seen, now=NOW)
    check("[15] A no longer reports it: B's proxy is never deleted by the mirror", not ng["nb"].get("turn"), ng["nb"].get("turn"))

    # status
    def view(nn, bs, asn=sa):
        fv = P.failover_view(nn, roster(), "na", "nb", {"na": asn, "nb": bs}, seen, frozenset(), now=NOW, ivk=IVK)
        return {r["iface"]: r for r in fv["rows"]}, fv
    rows, _ = view(n, sb)
    check("[15] status: installing — a row of kind turn", rows.get(TPS, {}).get("why") == "creating"
          and rows[TPS].get("kind") == "turn" and rows[TPS].get("state") == "syncing", rows.get(TPS))
    rows, _ = view(fleet(), sbr)
    check("[15] B runs it as A does: no row", TPS not in rows, rows.get(TPS))
    rows, _ = view(fleet(), dict(sb, turn_proxies=[tp_row(running=False)]))
    check("[15] B's proxy not running: down", rows.get(TPS, {}).get("why") == "down" and rows[TPS]["state"] == "problem", rows.get(TPS))
    rows, _ = view(fleet(), sbr, dict(sa, turn_proxies=[tp_row(installing=True)]))
    check("[15] A updating its proxy (installing, params kept): B's copy is still a copy, still checked (verify F52)",
          TPS not in rows, rows.get(TPS))
    rows, _ = view(fleet(), dict(sbr, turn_proxies=[tp_row(bind_ip="", running=False)]), dict(sa, turn_proxies=[tp_row(installing=True)]))
    check("[15] …and a copy down on B is still said while A updates (verify F52)", rows.get(TPS, {}).get("why") == "down", rows.get(TPS))
    rows, _ = view(fleet(), dict(sbr, turn_proxies=[tp_row(bind_ip="", listen="198.51.100.7:56100")]),
                   dict(sa, turn_proxies=[tp_row(listen="198.51.100.7:56100")]))
    check("[15] a proxy copy whose clients dial A's IP: ip_dial with the host (ip_dial review F5)",
          rows.get(TPS, {}).get("why") == "ip_dial" and rows[TPS].get("host") == "198.51.100.7" and rows[TPS].get("kind") == "turn"
          and "via" not in rows[TPS], rows.get(TPS))
    nv = fleet(); nv["na"]["ifaces"]["awg0"]["endpoint_host"] = "198.51.100.9"; nv["na"].pop("endpoint_host", None)
    fv = P.failover_view(nv, roster(), "na", "nb", {"na": sa, "nb": dict(sbr, turn_proxies=[tp_row(bind_ip="")])},
                         seen, frozenset(), now=NOW, ivk=IVK)
    rv = {r["iface"]: r for r in fv["rows"]}
    check("[15] a proxy on every address, dialled at awg0's IP endpoint: the row names awg0, where the fix is (ip_dial verify F8)",
          rv.get(TPS, {}).get("why") == "ip_dial" and rv[TPS].get("via") == "awg0" and rv[TPS].get("host") == "198.51.100.9", fv["rows"])
    rows, _ = view(fleet(), dict(sb, turn_proxies=[tp_row(flapping=40)]))
    check("[15] B's proxy crash-looping (running between restarts): down (R2 F8)", rows.get(TPS, {}).get("why") == "down", rows.get(TPS))
    rows, _ = view(fleet(), dict(sbr, udp_ports="51820-51899"))
    check("[15] B's declared firewall shuts the proxy's port: firewall, the port named (R2 F7)",
          rows.get(TPS, {}).get("why") == "firewall" and rows[TPS].get("port") == 56100, rows.get(TPS))
    rows, _ = view(fleet(), dict(sb, turn_proxies=[tp_row(connect="127.0.0.1:444")]))
    check("[15] B's differs from A's: drift, the keys named", rows.get(TPS, {}).get("why") == "drift"
          and rows[TPS].get("keys") == ["connect"], rows.get(TPS))
    rows, _ = view(fleet(), dict(sb, turn_capable=False))
    check("[15] B cannot run one: said, not \"creating\" for ever", rows.get(TPS, {}).get("why") == "no_turn", rows.get(TPS))
    _, fv = view(fleet(), dict(sbr, turn_proxies=[tp_row(bind_ip=""), tp_row("vk-turn-proxy-cacggghp-56300")]))
    check("[15] a proxy B runs that A's report does not name is listed as B's own",
          {"kind": "unmanaged_turn", "services": ["vk-turn-proxy-cacggghp-56300"]} in fv["problems"], fv["problems"])
    _, fv = view(fleet(), dict(sbr, turn_proxies=[tp_row("vk-turn-proxy-cacggghp-56300")]), asn={"interfaces": {"awg0": snap_iface()}})
    check("[15] …never on a report of A's that carries no proxy list (a report confirms, never condemns)",
          not any(x["kind"] == "unmanaged_turn" for x in fv["problems"]), fv["problems"])
    _b2 = dict(sbr, turn_proxies=[tp_row(bind_ip=""), tp_row("vk-turn-proxy-cacggghp-56300")])
    fv = P.failover_view(fleet(), roster(), "na", "nb", {"na": sa, "nb": _b2}, {"na": NOW - 10_000, "nb": NOW}, frozenset(), now=NOW, ivk=IVK)
    check("[15] …nor while A is not reporting (its last report may be a rebuilt box's empty one, R2 F4)",
          not any(x["kind"] == "unmanaged_turn" for x in fv["problems"]), fv["problems"])
    nu = fleet(); nu["na"]["turn"] = {"vk-turn-proxy-cacggghp-56300": {"action": "install", "at": NOW}}
    fv = P.failover_view(nu, roster(), "na", "nb", {"na": dict(sa, turn_proxies=[]), "nb": _b2}, seen, frozenset(), now=NOW, ivk=IVK)
    check("[15] …nor one A has a request for (a rebuilt A's re-issued install, R2 F4)",
          {"kind": "unmanaged_turn", "services": [TPS]} in fv["problems"], fv["problems"])
    nu = fleet(); nu["nb"]["turn"] = {"vk-turn-proxy-cacggghp-56300": {"action": "delete", "at": NOW}}
    fv = P.failover_view(nu, roster(), "na", "nb", {"na": sa, "nb": _b2}, seen, frozenset(), now=NOW, ivk=IVK)
    check("[15] …nor one whose delete is already staged (R2 F21)",
          not any(x["kind"] == "unmanaged_turn" for x in fv["problems"]), fv["problems"])
    fv = P.failover_view(fleet(), roster(), "na", "nb", {"na": sa, "nb": dict(_b2, turn_manage=False)}, seen, frozenset(), now=NOW, ivk=IVK)
    check("[15] …nor on a B that cannot manage proxies (every delete would fail there, verify F49)",
          not any(x["kind"] == "unmanaged_turn" for x in fv["problems"]), fv["problems"])

    # the take-over and detach: a proxy has no roster target and no identity — nothing to move, nothing they remove
    snaps_ = {"na": sa, "nb": dict(sb, turn_proxies=[tp_row(running=False)])}
    nh = fleet(); P.failover_mirror(DEPS, nh, "nb", {"na": sa, "nb": dict(sb, interfaces={})}, seen, now=NOW)
    h = P._fo_holds(nh, snaps_, "na", "nb", True)
    check("[15] a proxy down on B never puts the take-over in doubt", not any(TPS in x for x in h), h)
    check("[15] …nor is it listed as moved or left, or removed by a keep",
          TPS not in sum(P._fo_takeover_plan(nh, "na", "nb", h, snaps_)[:3], []) and TPS not in P._fo_b_copies(nh["nb"]), h)

    # the doors: B's own proxy is B's to delete; A's copy, and every other turn door, stays refused
    nr = fleet()
    sn = {"na": sa, "nb": dict(sbr, turn_proxies=[tp_row(bind_ip=""), tp_row("vk-turn-proxy-x-1")])}
    rseen = {"na": time.time(), "nb": time.time()}       # the door reads the wall clock (`now` is the api's)
    f = lambda path, body, snaps=sn, sn_=rseen: P.failover_ro_refusal(path, body, nr, snaps, sn_)
    check("[15] deleting a proxy of B's own is allowed", f("/api/turn/delete", {"node": "nb", "service": "vk-turn-proxy-x-1"}) is None)
    check("[15] deleting A's copy on B is refused (the mirror would put it straight back)",
          (f("/api/turn/delete", {"node": "nb", "service": TPS}) or [0])[0] == 409)
    check("[15] …and with no report of A's to tell them apart, refused",
          (f("/api/turn/delete", {"node": "nb", "service": "vk-turn-proxy-x-1"}, {"nb": sbr}) or [0])[0] == 409)
    check("[15] …nor while A is not reporting (R2 F4)",
          (f("/api/turn/delete", {"node": "nb", "service": "vk-turn-proxy-x-1"}, sn, {"na": time.time() - 10_000, "nb": time.time()}) or [0])[0] == 409)
    nr["na"]["turn"] = {"vk-turn-proxy-x-1": {"action": "install", "at": NOW}}
    check("[15] …nor one A has a request for (R2 F4)", (f("/api/turn/delete", {"node": "nb", "service": "vk-turn-proxy-x-1"}) or [0])[0] == 409)
    nr["na"].pop("turn")
    check("[15] installing, editing or stopping a proxy on B is refused",
          all((f(p_, {"node": "nb", "service": "vk-turn-proxy-x-2", "fork": "x", "listen": "1.2.3.4:1", "connect": "127.0.0.1:2"}) or [0])[0] == 409
              for p_ in ("/api/turn/install", "/api/turn/manage", "/api/turn/stop", "/api/turn/reinstall")))
    # R3: the updates sheet moves B's proxies as it moves A's — a proxy's version is never followed (§12.7 R2)
    check("[15] the updates sheet's reinstall of a proxy B reports is allowed (its version is B's own)",
          f("/api/turn/reinstall", {"node": "nb", "service": TPS, "tag": "v2.0"}) is None)
    check("[15] …and with no report of B's naming it, refused",
          (f("/api/turn/reinstall", {"node": "nb", "service": TPS}, {"na": sa}) or [0])[0] == 409)
    check("[15] …nor on a B that cannot manage proxies (it would fail there for ever, R3 review F28)",
          (f("/api/turn/reinstall", {"node": "nb", "service": TPS}, {"na": sa, "nb": dict(sn["nb"], turn_manage=False)}) or [0])[0] == 409)
    check("[15] editing, stopping or restarting a copy B reports stays refused (only the reinstall is B's, R3 review F5)",
          all((f(p_, {"node": "nb", "service": TPS, "listen": "1.2.3.4:1", "connect": "127.0.0.1:2"}) or [0])[0] == 409
              for p_ in ("/api/turn/manage", "/api/turn/stop", "/api/turn/start", "/api/turn/restart", "/api/turn/rotate")))

    # R3: the updates sheet lists B's proxies, never its WDTT / csqtt — those run the build A is held on (§12.4)
    _tl = dict(P.TURN_LATEST)
    _hg = P._turn_hold_get
    try:
        P.TURN_LATEST["forks"] = {"cacggghp": "v2.0", "amurcanov": "9.9"}
        P._turn_hold_get = lambda nid, key: None
        _ud = {"node_snaps": {x: {"wdtt": [{"iface": "wdtt1", "fork": "amurcanov", "version": "1.0"}],
                                  "turn_proxies": [tp_row(version="v1.2")]} for x in ("na", "nb")}}
        ur = {(r["node"], r["kind"]) for r in P.turn_updates_view(_ud, fleet())}
        check("[15] the updates sheet: A's WDTT and proxy, B's proxy — never B's WDTT",
              ur == {("na", "wdtt"), ("na", "turn"), ("nb", "turn")}, sorted(ur))
        ur0 = {(r["node"], r["kind"]) for r in P.turn_updates_view(_ud)}
        check("[15] …and with no store at hand, every row as before", ("nb", "wdtt") in ur0, sorted(ur0))
    finally:
        P.TURN_LATEST.clear(); P.TURN_LATEST.update(_tl); P._turn_hold_get = _hg

    # the preview
    pa = dict(sa, turn_proxies=[tp_row(), tp_row("vk-turn-proxy-cacggghp-56400", listen="198.51.100.7:56400")])
    pf = P.failover_preflight({"nodes_path": "", "roster_path": ""}, fleet(), "na", {"na": pa}, {"na": NOW})
    check("[15] the preview names a proxy's port, and the one clients reach by IP — each entry with its kind (R3: the sheet "
          "words a proxy as a proxy)",
          {"iface": TPS, "kind": "turn", "port": 56100} in pf["warn"]["ports"]
          and {"iface": "vk-turn-proxy-cacggghp-56400", "kind": "turn", "port": 56400} in pf["warn"]["ports"]
          and any(x["iface"] == "vk-turn-proxy-cacggghp-56400" and x.get("kind") == "turn" for x in pf["warn"]["ip_endpoint"]), pf["warn"])
    check("[15] …a proxy on a wildcard is dialled at the interface it forwards to (a name: no warning)",
          not any(x["iface"] == TPS for x in pf["warn"]["ip_endpoint"]), pf["warn"]["ip_endpoint"])
    check("[15] …and no longer files turn proxies as not copied",
          not [x for x in pf["warn"]["not_mirrored"] if x["kind"] == "turn"], pf["warn"]["not_mirrored"])
    _a0 = fleet(); _a0["na"]["ifaces"] = {}
    pf = P.failover_preflight({"nodes_path": "", "roster_path": ""}, _a0, "na", {"na": pa}, {"na": NOW})
    check("[15] a primary with proxies alone (they forward to its interfaces) is refused (R2 F23)",
          any("no interfaces" in x["why"] for x in pf["refused"]), pf["refused"])

    # the auto-updater: B's copies are B's own binaries — B's own hold holds them (R3 opens B's updates sheet, whose
    # rollback sets it), A's does not (R2 F6/F12/F38: nothing would ever give B A's held build)
    def tick(holds):
        td = tempfile.mkdtemp(dir=TMP)
        json.dump({"turn_update": {"every_days": 1, "at": "04:00"}}, open(os.path.join(td, "ps.json"), "w"))
        json.dump(fleet(), open(os.path.join(td, "nodes.json"), "w"))
        json.dump(holds, open(os.path.join(td, "holds.json"), "w"))
        _saved = (P.TURN_HOLDS_PATH, P._resolve_turn_tag, P.turn_pin, P._turn_update_due, getattr(P.Handler, "deps", None))
        P.TURN_HOLDS_PATH, P._resolve_turn_tag, P.turn_pin = os.path.join(td, "holds.json"), (lambda o: "v2.0"), (lambda *a, **k: {})
        P._turn_update_due = lambda *a, **k: True      # the window, never the wall clock (a run at 23:59 passed vacuously)
        P.Handler.deps = {"panel_settings_path": os.path.join(td, "ps.json"), "nodes_path": os.path.join(td, "nodes.json"),
                          "roster_path": os.path.join(td, "users.json"), "node_snaps": {"nb": dict(sbr, turn_proxies=[tp_row(version="v1.2")])}}
        try:
            P._turn_autoupdate_tick()
        finally:
            P.TURN_HOLDS_PATH, P._resolve_turn_tag, P.turn_pin, P._turn_update_due, P.Handler.deps = _saved
        return json.load(open(os.path.join(td, "nodes.json")))["nb"].get("turn") or {}
    t_ = tick({"na|fork:cacggghp": {"tag": "v1.2"}})
    check("[15] the auto-updater moves B's copy where only A is held", (t_.get(TPS) or {}).get("action") == "reinstall", t_)
    t_ = tick({"nb|fork:cacggghp": {"tag": "v1.2"}})
    check("[15] …and holds it where B is held", not t_, t_)

    # the sync: B's reply carries the install; B reporting the proxy clears it
    port, d = start_panel(NEW, "turn-proxy", fleet(), roster(), vault={"ivk_enabled": True, "ivk_pub": IVK})
    tk = {x: req(port, "/api/nodes/rotate", {"id": x})[1]["data"]["token"] for x in ("na", "nb", "nc")}

    def psync(nid, tps):
        snap = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": {"awg0": snap_iface()},
                "net_deps": {"limits": True, "reach": 2}, "turn_proxies": tps, "arch": "amd64"}
        c_, r_ = req(port, "/api/node/sync", {"snapshot": snap}, tk[nid])
        assert c_ == 200, (c_, r_)
        return r_
    psync("na", [tp_row()])
    rb = psync("nb", [])
    check("[15] B's sync reply carries the install", ((rb.get("turn") or {}).get(TPS) or {}).get("action") == "install", rb.get("turn"))
    rb = psync("nb", [tp_row(bind_ip="")])
    check("[15] …and B reporting the proxy clears it, with nothing new staged", not (rb.get("turn") or {}).get(TPS), rb.get("turn"))



def x_fleet():
    """A primary whose settings use four device exits (and hold a fifth it does not use), and its failover node."""
    n = fleet()
    a = n["na"]
    a["exits"] = [
        {"id": "aaaa0001", "label": "WARP", "producer": "imported", "provider": "warp", "device": "wgx-aaaa0001", "enabled": True,
         "killswitch": False, "licence": "L1", "cfg_sig": "a-sig", "key_blob": {"eph": "E", "ct": "C"}, "dial_src": "198.51.100.7"},
        {"id": "aaaa0002", "label": "Proxy", "producer": "imported", "provider": "socks5", "device": "wgx-aaaa0002", "enabled": True,
         "killswitch": True, "socks": {"host": "px.example.com", "port": 1080, "user": "u", "pass": "p", "salt": "x"}},
        {"id": "aaaa0003", "label": "Provider", "producer": "imported", "provider": "profile", "device": "wgx-aaaa0003", "enabled": True,
         "killswitch": False, "profile": {"private_key": "A-PRIV", "address": "10.9.9.2", "peer_key": "PK", "endpoint": "vpn.example.com:51820"}},
        {"id": "aaaa0004", "label": "Home Router", "producer": "imported", "provider": "profile", "device": "wgx-aaaa0004", "enabled": True,
         "killswitch": False, "profile": {"private_key": "A-DPRIV", "address": "10.254.0.0", "peer_key": "RK", "endpoint": "", "listen_port": 51830}},
        {"id": "aaaa0005", "label": "Unused", "producer": "imported", "provider": "profile", "device": "wgx-aaaa0005", "enabled": True,
         "profile": {"private_key": "A-UPRIV", "address": "10.9.8.2", "peer_key": "UK", "endpoint": "u.example.com:51820"}}]
    a["ifaces"]["awg0"]["egress_mode"] = "smart"
    a["ifaces"]["awg0"]["routing"] = [{"enabled": True, "category": "google", "action": "dev", "exit_id": "aaaa0001"}]
    a["default_routing"] = [{"enabled": True, "category": "discord", "action": "dev", "exit_id": "aaaa0002"},
                            {"enabled": True, "category": "github", "action": "dev", "exit_id": "aaaa0004"}]
    a["p2p"] = {"action": "dev", "exit_id": "aaaa0003"}
    return n


def sec16():
    print("[16] the mirror's exits (FAILOVER-PLAN §14.3)")
    n = x_fleet()
    check("[16] exit_refs: interface rules, the default list and the torrent route — never an exit nothing uses",
          P.exit_refs(n["na"]) == {"aaaa0001", "aaaa0002", "aaaa0003", "aaaa0004"}, sorted(P.exit_refs(n["na"])))
    snaps = {"na": {"interfaces": {"awg0": snap_iface()}}}
    seen = {"na": NOW, "nb": NOW}
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    bx = {x["id"]: x for x in (n["nb"].get("exits") or [])}
    check("[16] B holds every exit A's settings use, by A's id, in A's order — and not the one A does not use",
          [x["id"] for x in n["nb"].get("exits") or []] == ["aaaa0001", "aaaa0002", "aaaa0003", "aaaa0004"], list(bx))
    w = bx.get("aaaa0001") or {}
    check("[16] a WARP copy is the kind and licence — never A's account, signature or source address",
          w.get("provider") == "warp" and w.get("licence") == "L1" and w.get("label") == "WARP"
          and not any(k in w for k in ("key_blob", "key_restore", "dial_src")) and w.get("cfg_sig") == P.exit_cfg_sig(w), w)
    check("[16] a SOCKS copy carries the proxy, its killswitch with it",
          (bx.get("aaaa0002") or {}).get("socks", {}).get("host") == "px.example.com" and (bx.get("aaaa0002") or {}).get("killswitch") is True, bx.get("aaaa0002"))
    check("[16] a provider profile and a dial-in are placeholders: same id and name, no config (A's key never copied)",
          all(P.fo_exit_unfilled(bx.get(k)) and (bx.get(k) or {}).get("label") == lab for k, lab in (("aaaa0003", "Provider"), ("aaaa0004", "Home Router")))
          and "A-PRIV" not in json.dumps(n["nb"]), [bx.get("aaaa0003"), bx.get("aaaa0004")])
    b = n["nb"]
    check("[16] B's copies keep naming the exits — the prune no longer turns them into direct",
          (b.get("ifaces") or {}).get("awg0", {}).get("routing", [{}])[0].get("exit_id") == "aaaa0001"
          and [r.get("exit_id") for r in b.get("default_routing") or []] == ["aaaa0002", "aaaa0004"]
          and (b.get("p2p") or {}).get("exit_id") == "aaaa0003", [b.get("ifaces", {}).get("awg0", {}).get("routing"), b.get("default_routing"), b.get("p2p")])
    v = P.failover_view(n, None, "na", "nb", snaps, seen, frozenset(), now=NOW)
    xr = {r["exit_id"]: r for r in v["rows"] if r.get("kind") == "exit"}
    check("[16] status: the placeholders need attention (the dial-in says so), the others wait for B's report",
          xr.get("aaaa0003", {}).get("why") == "exit_unfilled" and not xr["aaaa0003"].get("dialin")
          and xr.get("aaaa0004", {}).get("why") == "exit_unfilled" and xr["aaaa0004"].get("dialin") is True
          and xr.get("aaaa0001", {}).get("state") == "syncing" and v["state"] == "problem", xr)
    snaps["nb"] = {"interfaces": {}, "exits": [{"id": "aaaa0001", "up": True}, {"id": "aaaa0002", "up": False, "error": "proxy refused"}]}
    v = P.failover_view(n, None, "na", "nb", snaps, seen, frozenset(), now=NOW)
    xr = {r["exit_id"]: r for r in v["rows"] if r.get("kind") == "exit"}
    check("[16] …an exit up on B has no row; one B reports down says why",
          "aaaa0001" not in xr and xr.get("aaaa0002", {}).get("why") == "exit_down" and xr["aaaa0002"].get("err") == "proxy refused", xr)
    for x in n["nb"]["exits"]:
        if x["id"] == "aaaa0003":
            x["profile"] = {"private_key": "B-PRIV", "address": "10.9.9.3", "peer_key": "PK", "endpoint": "vpn.example.com:51820"}
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    aaaa0003 = next((x for x in n["nb"]["exits"] if x["id"] == "aaaa0003"), {})
    check("[16] a config the operator filled on B survives the next pass, and B's signature follows it",
          (aaaa0003.get("profile") or {}).get("private_key") == "B-PRIV" and aaaa0003.get("cfg_sig") == P.exit_cfg_sig(aaaa0003), aaaa0003)
    n["na"]["p2p"] = {"action": "block"}
    n["na"]["default_routing"] = [{"enabled": True, "category": "discord", "action": "dev", "exit_id": "aaaa0002"}]
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    ids = [x["id"] for x in n["nb"].get("exits") or []]
    x3 = next((x for x in n["nb"].get("exits") or [] if x["id"] == "aaaa0003"), {})
    check("[16] no longer used: an unfilled placeholder goes, a filled config A still has is parked — disabled, no tunnel (F4)",
          "aaaa0004" not in ids and x3.get("enabled") is False and (x3.get("profile") or {}).get("private_key") == "B-PRIV"
          and x3.get("cfg_sig") == P.exit_cfg_sig(x3), (ids, x3))
    n["na"]["p2p"] = {"action": "dev", "exit_id": "aaaa0003"}
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    x3 = next((x for x in n["nb"].get("exits") or [] if x["id"] == "aaaa0003"), {})
    check("[16] …A using it again brings it back, the config with it",
          x3.get("enabled") is True and (x3.get("profile") or {}).get("private_key") == "B-PRIV", x3)
    n["na"]["p2p"] = {"action": "block"}
    n["na"]["exits"] = [x for x in n["na"]["exits"] if x["id"] != "aaaa0003"]
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[16] …A deleting the exit takes B's copy, filled or not (F4)",
          "aaaa0003" not in [x["id"] for x in n["nb"].get("exits") or []], [x["id"] for x in n["nb"].get("exits") or []])
    # B's own key escrow on a WARP copy (written by B's sync) survives the pass, which then changes nothing (F1)
    n = x_fleet(); P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    for x in n["nb"]["exits"]:
        if x["id"] == "aaaa0001":
            x["key_blob"] = {"eph": "BE", "ct": "BC", "pub": "BPUB"}
            x["key_restore"] = {"ct": "R"}
    ch = P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    w = next((x for x in n["nb"]["exits"] if x["id"] == "aaaa0001"), {})
    check("[16] B's own WARP key escrow stays on its copy, and the pass is steady (no save every sync) (F1)",
          (w.get("key_blob") or {}).get("pub") == "BPUB" and w.get("key_restore") == {"ct": "R"} and ch is False, (ch, w))
    n["na"]["exits"][0] = dict(n["na"]["exits"][0], provider="socks5", socks={"host": "px2.example.com", "port": 1080})
    n["na"]["exits"][0].pop("key_blob", None)
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    w = next((x for x in n["nb"]["exits"] if x["id"] == "aaaa0001"), {})
    check("[16] …but A switching that exit off WARP ends B's account too: no escrow rides onto the new kind (F12)",
          w.get("provider") == "socks5" and not any(k in w for k in P._EXIT_ESCROW_KEYS), w)
    n = x_fleet(); P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[16] an unfilled copy routes nothing on B — the traffic takes the default, as a deleted exit's does (F5)",
          P.resolve_exit(n, snaps, "nb", "aaaa0003") is None and P.resolve_exit(n, snaps, "nb", "aaaa0001") is not None)
    v = P.failover_view(n, None, "na", "nb", snaps, seen, frozenset(), now=NOW)
    check("[16] an exit row is keyed by the exit's id — the console names it as the exits grid does (F9)",
          all(r["iface"] == r["exit_id"] for r in v["rows"] if r.get("kind") == "exit")
          and any(r.get("kind") == "exit" for r in v["rows"]), v["rows"])
    pf = P.failover_preflight({"nodes_path": "", "roster_path": ""}, x_fleet(), "na", snaps, {"na": NOW})
    check("[16] the setup preview files none of the copied exits as not copied (F3)",
          not [x for x in pf["warn"]["not_mirrored"] if x["kind"] in ("exit", "default_exit", "p2p")], pf["warn"]["not_mirrored"])
    check("[16] …and says which copies leave by B's own address until filled there — the profile and the dial-in (F13)",
          pf["warn"].get("exit_fill") == ["aaaa0003", "aaaa0004"], pf["warn"].get("exit_fill"))
    # the door: B fills its own config of an exit it holds for A, and nothing else
    n = x_fleet(); P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    view = [dict({k: v for k, v in x.items() if k not in ("profile", "socks")}) for x in n["nb"]["exits"]]
    def put(edit):
        xs = [dict(x) for x in view]
        edit(xs)
        return P.failover_ro_refusal("/api/nodes/update", {"id": "nb", "exits": xs}, n, snaps, seen)
    check("[16] the door: a pasted config for a profile B holds for A is allowed",
          put(lambda xs: xs[2].update(profile_text="[Interface]\nPrivateKey = x")) is None)
    check("[16] …a dial-in made in the browser too",
          put(lambda xs: xs[3].update(dialin_gen={"proto": "wg"})) is None)
    check("[16] …a renamed exit, a config on a WARP copy, a dropped or an added exit are refused",
          all((put(f) or (0,))[0] == 409 for f in (lambda xs: xs[2].update(label="mine"),
                                                    lambda xs: xs[0].update(profile_text="x"),
                                                    lambda xs: xs.pop(),
                                                    lambda xs: xs.append({"id": "z9", "producer": "imported", "provider": "warp"}))))
    # the wire: a placeholder never reaches the node
    n = x_fleet()
    n["na"]["p2p"] = {"action": "dev", "exit_id": "aaaa0004"}      # the torrent route through the dial-in B never fills
    n["na"]["default_routing"].append({"enabled": True, "category": "youtube", "action": "dev", "exit_id": "aaaa0003"})
    port, _d = start_panel(NEW, "exits", n, roster())
    tk = {x: req(port, "/api/nodes/rotate", {"id": x})[1]["data"]["token"] for x in ("na", "nb")}
    for nid in ("na", "nb", "nb"):
        snap = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": {"awg0": snap_iface()},
                "net_deps": {"limits": True, "reach": 2}, "exit_kinds": ["warp", "profile", "socks5"]}
        code, r = req(port, "/api/node/sync", {"snapshot": snap}, tk[nid])
    sent = [x.get("id") for x in ((r.get("data") or r).get("exits") or [])]
    check("[16] B's sync sends the WARP and SOCKS copies and never a placeholder",
          code == 200 and sent == ["aaaa0001", "aaaa0002"], (code, sent))
    st = req(port, "/api/state")[1]
    xs = [dict(x) for x in next(x for x in (st.get("data") or st)["nodes"] if x["id"] == "nb")["exits"]]
    conf = ("[Interface]\nPrivateKey = kB3vZ1y7m2oD0w5qX8rT9uYcE4fH6jL1nP3sV5xZ7aA=\nAddress = 10.9.9.3/32\n\n[Peer]\n"
            "PublicKey = gA8AMiyqS34LJSP6skn0yUcmM+PHh0tTlLf3gMnLvV4=\nEndpoint = vpn.example.com:51820\nAllowedIPs = 0.0.0.0/0\n")
    fill = [dict(x, profile_text=conf) if x["id"] == "aaaa0003" else x for x in xs]
    code2, r2 = req(port, "/api/nodes/update", {"id": "nb", "exits": fill})
    code3, _r3 = req(port, "/api/nodes/update", {"id": "nb", "exits": [dict(x, label="mine") if x["id"] == "aaaa0003" else x for x in xs]})
    st = req(port, "/api/state")[1]
    bx = {x["id"]: x for x in next(x for x in (st.get("data") or st)["nodes"] if x["id"] == "nb")["exits"]}
    check("[16] a real save on B fills its copy, the other placeholder still empty (the list is saved whole)",
          code2 == 200 and "profile" in bx.get("aaaa0003", {}) and "profile" not in bx.get("aaaa0004", {}), (code2, r2, sorted(bx)))
    check("[16] …and a rename through the same save is refused (read-only)", code3 == 409, code3)
    c, o = req(port, "/api/nodes/failover/detach", {"id": "nb", "take_over": False, "confirm": "hel-2"})
    st = req(port, "/api/state")[1]
    nb = next(x for x in (st.get("data") or st)["nodes"] if x["id"] == "nb")
    xs = [dict(x) for x in nb.get("exits") or []]
    check("[16] detached, B drops the copy it never filled and keeps the one it did (F2)",
          c == 200 and sorted(x["id"] for x in xs) == ["aaaa0001", "aaaa0002", "aaaa0003"], (c, o, [x["id"] for x in xs]))
    c4, o4 = req(port, "/api/nodes/update", {"id": "nb", "exits": [dict(x, label="mine") if x["id"] == "aaaa0003" else x for x in xs]})
    check("[16] …so its exits list saves again as any node's (F2)", c4 == 200, (c4, o4))
    check("[16] …and its torrent route through the dropped copy turns Block with an event on B, as a deleted exit's does (F14)",
          (nb.get("p2p") or {}).get("action") == "block" and _pruned_ev(_d, "nb"), (nb.get("p2p"), _pruned_ev(_d, "nb")))
    # …and the take-over branch the same (fo-exits-f1b F17): one shared tail reports it (F18)
    n = x_fleet()
    n["na"]["p2p"] = {"action": "dev", "exit_id": "aaaa0004"}
    port, _d = start_panel(NEW, "exits-take", n, roster())
    tk = {x: req(port, "/api/nodes/rotate", {"id": x})[1]["data"]["token"] for x in ("na", "nb")}
    for nid in ("na", "nb"):
        snap = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": {"awg0": snap_iface()},
                "net_deps": {"limits": True, "reach": 2}, "exit_kinds": ["warp", "profile", "socks5"]}
        req(port, "/api/node/sync", {"snapshot": snap}, tk[nid])
    c, o = req(port, "/api/nodes/failover/detach", {"id": "nb", "take_over": True, "confirm": "hel-2"})
    nb = next(x for x in (lambda st: (st.get("data") or st)["nodes"])(req(port, "/api/state")[1]) if x["id"] == "nb")
    check("[16] …taken over, B's torrent route through the copy it never filled turns Block, with its event on B (F17)",
          c == 200 and (nb.get("p2p") or {}).get("action") == "block" and _pruned_ev(_d, "nb"), (c, o, nb.get("p2p")))


def _pruned_ev(d, nid):
    """The "Torrent route removed" event for node `nid` in a panel's event log — the record, matched by its id."""
    import glob
    for f in glob.glob(os.path.join(d, "**", "*event*"), recursive=True):
        for ln in open(f, encoding="utf-8", errors="replace"):
            with contextlib.suppress(ValueError):
                r = json.loads(ln)
                if isinstance(r, dict) and r.get("verb") == "Torrent route removed" and r.get("id") == nid:
                    return True
    return False

# ── [17] both members serve — return by link (FAILOVER-PLAN §14.2, §14.7) ───────────────────────────────────────────────
def sec17():
    global _PF
    print("[17] both members serve — return by link (FAILOVER-PLAN §14.2, §14.7)")
    n = plan_fleet(); _PF = n
    n["nb"]["links"]["nc"].update(subnet="10.255.0.2/31", address="10.255.0.2", peer_address="10.255.0.3")
    n["nc"]["links"]["nb"].update(subnet="10.255.0.2/31", address="10.255.0.3", peer_address="10.255.0.2")
    s0 = plan_snaps(2, 0)
    s0["nb"]["interfaces"]["swg_nbnc"]["meta"]["subnet"] = s0["nc"]["interfaces"]["swg_ncnb"]["meta"]["subnet"] = "10.255.0.2/31"
    for _m in ("na", "nb"):                             # both members run a noded that knows return by link (`rbl` reported)
        s0[_m]["smartroute"] = dict(s0[_m].get("smartroute") or {}, rbl=0)
    s0["nc"]["smartroute"] = {"rbl": 0}                 # a node that reports, and says it cannot (rp_filter, §14.7)
    ref_off = json.dumps(REFF2().cascade_plan(n, s0, idle=frozenset({"nb"})), sort_keys=True, default=str)
    cur_off = json.dumps(P.cascade_plan(n, s0, idle=frozenset({"nb"})), sort_keys=True, default=str)
    check("[17] a far node that does not say `rbl`: the plan is the build before F2's (§4.4 for it)", cur_off == ref_off)
    s0["nc"]["smartroute"] = {"rbl": 1}
    pl = P.cascade_plan(n, s0, idle=frozenset({"nb"}))
    fa, fb = (pl.get("na") or {}).get("forward") or [], (pl.get("nb") or {}).get("forward") or []
    check("[17] both members forward to the far node — the idle one too", fa and fb, (fa, fb))
    check("[17] …and neither carries a clash card", not (pl.get("na") or {}).get("_clash") and not (pl.get("nb") or {}).get("_clash"))
    ex = sorted((pl.get("nc") or {}).get("exit") or [], key=lambda e: e["via_iface"])
    La, Lb = P.rbl_label(n, "nc", "na"), P.rbl_label(n, "nc", "nb")
    check("[17] the far node holds one record per link, each with its link's own label", len(ex) == 2 and La and Lb and La != Lb
          and [(e["via_iface"], e.get("ret")) for e in ex] == [("swg_ncna", La), ("swg_ncnb", Lb)], (La, Lb, ex))
    check("[17] …the idle member's returns by link only, the serving one's keeps `to S`",
          len(ex) == 2 and "to" not in ex[0] and ex[1].get("to") is False, ex)
    check("[17] …the label is the link's, not the table's: both records share the table", len(ex) == 2 and ex[0]["table"] == ex[1]["table"], ex)
    check("[17] …and each link's AllowedIPs carries the subnet", all("10.8.0.0/24" in (pl["nc"]["allowed"].get(d) or "")
                                                                      for d in ("swg_ncna", "swg_ncnb")), pl["nc"]["allowed"])
    pl1 = P.cascade_plan(n, s0, idle=frozenset({"na"}))
    ex1 = sorted((pl1.get("nc") or {}).get("exit") or [], key=lambda e: e["via_iface"])
    check("[17] B serving: A's record is the one without `to S`", len(ex1) == 2 and ex1[0].get("to") is False and "to" not in ex1[1], ex1)
    check("[17] the origin map never reaches the wire", "_xo" not in json.dumps(pl, default=str))
    # a member whose noded never said `rbl` (an older one, mid-rollout): its relay would pick over the whole range (F15)
    s_old = json.loads(json.dumps(s0)); s_old["nb"]["smartroute"].pop("rbl")
    check("[17] a member that never reported `rbl`: the plan is the build before F2's (§4.4 for it)",
          json.dumps(P.cascade_plan(n, s_old, idle=frozenset({"nb"})), sort_keys=True, default=str)
          == json.dumps(REFF2().cascade_plan(n, s_old, idle=frozenset({"nb"})), sort_keys=True, default=str))
    # the far node's default list still applies to the pair's subnet: one origin, not a T15 duplicate (F1)
    nl = json.loads(json.dumps(n)); nl["nc"]["default_routing"] = []
    for _m in ("na", "nb"):                             # unpinned: a pinned arrival is exempt from the list (§3.4)
        nl[_m]["ifaces"]["awg0"].pop("egress_ip", None)
    sl = json.loads(json.dumps(s0)); sl["nc"]["smartroute"]["arr"] = 1
    _rc = (P.cascade_plan(nl, sl, idle=frozenset({"nb"})).get("nc") or {}).get("_reach") or {}
    check("[17] the far node's arrivals keep the pair's subnet — one origin over two links, no duplicate",
          _rc.get("dup") == [] and ["na", "10.8.0.0/24"] in (_rc.get("arr") or []), _rc)
    # …and so do its P2P arrivals: a router peer behind the pair keeps its never-flag entry there (F5)
    _ncn = {"links": {"nb": {"iface": "swg_ncnb"}, "na": {"iface": "swg_ncna"}}}
    _pl2 = {"exit": [{"subnet": "10.8.0.0/24", "via_iface": "swg_ncna"}, {"subnet": "10.8.0.0/24", "via_iface": "swg_ncnb"}]}
    check("[17] P2P arrivals: the pair's two links are one origin, named as the primary",
          P.p2p_arrivals(_ncn, _pl2, n) == [("10.8.0.0/24", "na")], P.p2p_arrivals(_ncn, _pl2, n))
    check("[17] …and two links of two unpaired nodes are still left out (T15)", P.p2p_arrivals(_ncn, _pl2) == [])
    # a third node's overlapping subnet into the same exit is still the clash it was
    n3 = json.loads(json.dumps(n))
    n3["nd"] = {"id": "nd", "name": "d", "ifaces": {"awg0": dict(n["na"]["ifaces"]["awg0"])},
                "links": {"nc": {"iface": "swg_ndnc", "subnet": "10.255.0.4/31", "address": "10.255.0.4", "peer_address": "10.255.0.5"}}}
    n3["nc"]["links"]["nd"] = {"iface": "swg_ncnd", "subnet": "10.255.0.4/31", "address": "10.255.0.5", "peer_address": "10.255.0.4"}
    s3 = json.loads(json.dumps(s0))
    s3["nd"] = {"interfaces": {"awg0": snap_iface(), "swg_ndnc": {"meta": {"subnet": "10.255.0.4/31", "system": True}, "peers": []}}}
    s3["nc"]["interfaces"]["swg_ncnd"] = {"meta": {"subnet": "10.255.0.4/31", "system": True}, "peers": []}
    pl3 = P.cascade_plan(n3, s3, idle=frozenset({"nb"}))
    check("[17] a third node's overlapping subnet is still refused there (T37 holds for anyone but the partner)",
          not (pl3.get("nd") or {}).get("forward") and (pl3.get("nd") or {}).get("_clash")
          and len((pl3.get("nc") or {}).get("exit") or []) == 2, {k: (pl3.get(k) or {}).get("forward") for k in ("na", "nb", "nd")})
    # two of the far node's links with one label: that pair keeps §4.4 there
    nx = json.loads(json.dumps(n))
    nx["nb"]["links"]["nc"]["subnet"] = nx["nc"]["links"]["nb"]["subnet"] = "10.255.1.254/31"   # (0x0aff01fe>>1) ≡ A's mod 255
    check("[17] two links with one label: no label, and the plan is the build before F2's",
          P.rbl_label(nx, "nc", "nb") == 0 and json.dumps(P.cascade_plan(nx, s0, idle=frozenset({"nb"})), sort_keys=True, default=str)
          == json.dumps(REFF2().cascade_plan(nx, s0, idle=frozenset({"nb"})), sort_keys=True, default=str),
          (P._rbl_label_raw(nx["nc"]["links"]["na"]), P._rbl_label_raw(nx["nc"]["links"]["nb"])))
    # no pair at all, a far node that says `rbl`: byte-identical
    plain = {k: {kk: vv for kk, vv in v.items() if kk != "failover_of"} for k, v in n.items()}
    plain["nb"]["ifaces"]["awg0"] = dict(plain["nb"]["ifaces"]["awg0"], _lastcfg={"subnet": "10.9.0.0/24"})
    s0p = json.loads(json.dumps(s0)); s0p["nb"]["interfaces"]["awg0"]["meta"]["subnet"] = "10.9.0.0/24"
    check("[17] no pair, a far node that returns by link: the plan is the build before F2's",
          json.dumps(P.cascade_plan(plain, s0p), sort_keys=True, default=str)
          == json.dumps(REFF2().cascade_plan(plain, s0p), sort_keys=True, default=str))
    # the relay: a pair member's legs carry its port half, nobody else's
    _el = P.relay_eligibility
    try:
        P.relay_eligibility = lambda node, snaps, nid, legs=(): {"awg0": {"iface": "awg0", "peer": "nc", "via": "nc",
                                                                          "subnet": "10.8.0.0/24", "mark": 0, "why": ""}}
        nr = json.loads(json.dumps(n))
        for x in ("na", "nb"):
            nr[x]["links"]["nc"]["relay"] = {"mode": "relay"}
        halves = {x: [l.get("half") for l in P.relay_plan(nr, {}, x, s0).get("legs") or []] for x in ("na", "nb")}
        nr2 = {k: {kk: vv for kk, vv in v.items() if kk != "failover_of"} for k, v in nr.items()}
        lone = P.relay_plan(nr2, {}, "nb", s0).get("legs") or []
    finally:
        P.relay_eligibility = _el
    check("[17] the relay: A's legs take the low half of the source ports, B's the high", halves == {"na": [1], "nb": [2]}, halves)
    check("[17] …and a node in no pair carries no half (its plan unchanged)", lone and all("half" not in l for l in lone), lone)


def main():
    for name, fn in (("[1]", sec1), ("[2]", sec2), ("[3]", sec3), ("[4]", sec4), ("[5]", sec5), ("[6]", sec6), ("[7]", sec7),
                     ("[8]", sec8), ("[9]", sec9), ("[10]", sec10), ("[11]", sec11), ("[12]", sec12), ("[13]", sec13), ("[14]", sec14),
                     ("[15]", sec15), ("[16]", sec16), ("[17]", sec17)):
        guarded(name, fn)
    for p in PROCS:
        p.terminate()
    for p in PROCS:
        try:
            p.wait(timeout=10)
        except Exception:
            p.kill()
    shutil.rmtree(TMP, ignore_errors=True)
    if PLANT:
        print("plant %s: %s" % (PLANT, "RED (caught)" if FAILS else "GREEN — NOT caught"))
        sys.exit(0 if FAILS else 1)
    print("FAIL: %d" % len(FAILS) if FAILS else "PASS")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
