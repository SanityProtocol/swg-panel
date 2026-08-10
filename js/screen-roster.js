/* screen-roster.js — Peers, Users, Live and the activity history.
 *
 * LAYER 11 (see docs/APP-JS-SPLIT-PLAN.md). Four screens in one module because they are four views of
 * ONE thing: the same peers, through different lenses. They render the same PeerGrid, filter through the
 * same views.js state and sort with the same comparators — which is exactly the coupling the graph showed
 * (63 and 41 references between them) before views.js and grids.js gave that shared half a home.
 */

import {
  ago, seen, tkey,
} from "./util.js";
import { T, Tsplit, Trich, plural, srvVerb, srvDetail } from "./i18n.js";
import {
  Store, api, useStore,
} from "./store.js";
import {
  ifaceIsAll, ifaceMatch, targetType,
} from "./model.js";
import {
  Ic, RowError, SearchBox, StoreOffBanner, Tag, dlul, lifecycleIcon, openConfirm, rateCell, rowDouble,
  rowNoSelect, rowSingle, secTitle, xferCell,
} from "./ui.js";
import {
  EV_ACTIONS, EV_ITEMS, evItemLabel, evActionLabel, peerStatusFilters, USER_DEFDIR, activityView, connView, evDecorate,
  ifaceFilterOptions, ifaceOptGroups, nodeFilterOptions, pageScroll, peerMatchesQ, peerSortBy, peersView,
  searchMatch, sortColToggle, sortPeerRows, sortUsers, unassignedView, userIdentityMatchesQ, userMatchesQ,
  userOnNodeIface, userPeerViews, userStatTag, userStats, usersView,
} from "./views.js";
import {
  confirmCorrectAll, confirmRestoreAll,
} from "./peer-actions.js";
import {
  openUserConfigs, openUserEdit,
} from "./peer-ui.js";
import {
  openAddPeers, openCreatePeer, openCreateUser,
} from "./sheets-crud.js";
import {
  EmbeddedPeers, PeerGrid, UsersHeader,
} from "./grids.js";
import {
  OrphanRow,
} from "./iface.js";
import { h, Fragment } from "preact";
import { useState, useEffect } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// One fleet entry: main block (identity/traffic/sync) on the left, health block on the right.
export function PeersScreen() {
  useStore();
  const [, force] = useState(0);
  const fleet = Store.fleet;
  const multiServer = fleet.length > 1;
  // "*" = aggregate (all). With more than one server, default to fleet-wide so search spans it.
  if (!peersView.node) peersView.node = multiServer ? "*" : (fleet[0] ? fleet[0].id : "");
  if (peersView.node !== "*" && !fleet.some(n => n.id === peersView.node)) peersView.node = multiServer ? "*" : (fleet[0] ? fleet[0].id : "");
  const node = peersView.node;   // node = id, or "*" for all servers

  const allIfaces = Array.from(new Set(Object.keys(Store.describe).flatMap(n => Store.userIfacesOf(n)))).sort();   // user ifaces only — mesh links (swg_*) are not peer-bearing
  const ifaceOpts = node === "*" ? allIfaces : Store.userIfacesOf(node);
  // default interface: aggregate when several exist (or all-servers); else the only one.
  const ifaceDefault = () => (node === "*" || ifaceOpts.length > 1) ? "*" : (ifaceOpts[0] || "");
  if (!peersView.iface) peersView.iface = ifaceDefault();
  if (!ifaceIsAll(peersView.iface) && !ifaceOpts.includes(peersView.iface)) peersView.iface = ifaceDefault();
  const iface = peersView.iface;
  const agg = node === "*" || ifaceIsAll(iface);
  const itype = (!agg && Store.ifaceMeta(node, iface) && Object.keys(Store.ifaceMeta(node, iface).awg_params || {}).length) ? "awg" : "wg";

  const q = peersView.q.toLowerCase();
  // one row per matching (peer, target) deployment, so a fleet-wide view shows where each peer lives.
  let rows = [];
  for (const p of Store.recon.peers) for (const t of p.targets) {
    if (node !== "*" && t.node !== node) continue;
    if (!ifaceMatch(t.iface, iface)) continue;
    rows.push({ p, t });
  }
  // freeze the order over this view's full row set (per node/iface), THEN apply search/status filters — so
  // filtering or editing never reshuffles the frozen rows
  rows = sortPeerRows(rows, peersView.sort, peersView.dir, "peers|" + node + "|" + iface);
  if (q) rows = rows.filter(({ p, t }) => searchMatch((p.title || "") + " " + (p.name || "") + " " + (t.ip || "") + " " + Store.nodeName(t.node) + " " + t.iface, q));
  if (peersView.status) {
    // Filter on the DEPLOYMENT status (t.status) — the same value the row badge shows — so the filter never
    // returns rows whose badge reads something else (the "select Partial, see Ready rows" confusion). Two
    // peer-level exceptions that aren't a single deployment's state: `unassigned` (no owner), and `partial`
    // (a redundancy gap) → surface the MISSING side (the dangling/broken deployments) of partial peers.
    const f = peersView.status;
    rows = rows.filter(({ p, t }) =>
      f === "unassigned" ? p.unassigned
      : f === "partial" ? (p.status === "partial" && (t.status === "dangling" || t.status === "broken"))
      : t.status === f);
  }
  // batch Restore/Correct affordance: how many of the currently-shown rows are actionable. Restore is
  // per-interface (dedupe node|iface — one recreate fixes every dangling peer on it); Correct is per-peer.
  const restorableCount = peersView.status === "dangling" ? new Set(rows.filter(({ t }) => t.restorable).map(({ t }) => t.node + "|" + t.iface)).size : 0;
  const correctableCount = peersView.status === "broken" ? rows.filter(({ t }) => t.correctable).length : 0;
  // which of each peer's deployments are actually visible as rows here — so a row can flag the rest
  // (filtered out by server/interface or search) with a "+N" the operator can hover/tap.
  const shownByPeer = {};
  for (const { p, t } of rows) (shownByPeer[p.id] = shownByPeer[p.id] || new Set()).add(tkey(t.node, t.iface));
  const orphans = !agg ? Store.recon.orphans.filter(o => o.node === node && o.iface === iface) : [];

  // pagination — default 20/page; the +N badge still reflects ALL rows (shownByPeer above), not the page.
  const pageSize = peersView.pageSize || 20;
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const page = Math.min(Math.max(1, peersView.page || 1), totalPages);
  const pageRows = rows.slice((page - 1) * pageSize, page * pageSize);
  const setPage = p => { peersView.page = p; force(x => x + 1); };

  return html`<div class="screen">
    <${StoreOffBanner}/>
    <div class="toolbar">
      <${SearchBox} placeholder=${T("Search title, user, address…")} value=${peersView.q} onInput=${e => { peersView.q = e.target.value; peersView.page = 1; force(x => x + 1); }}/>
      <select class="selwrap" value=${node} onChange=${e => { peersView.node = e.target.value; peersView.iface = ""; peersView.page = 1; force(x => x + 1); }}>
        ${multiServer ? html`<option value="*">${T("All nodes")}</option>` : (!fleet.length ? html`<option value="*">${T("No nodes")}</option>` : null)}
        ${fleet.map(n => html`<option value=${n.id}>${n.name}</option>`)}
      </select>
      <select class="selwrap" value=${iface} onChange=${e => { peersView.iface = e.target.value; peersView.page = 1; force(x => x + 1); }}>
        ${ifaceOpts.length && (node === "*" || ifaceOpts.length > 1) ? html`<option value="*">${T("All interfaces")}</option>` : null}
        ${ifaceOpts.length ? ifaceOptGroups(ifaceOpts) : html`<option value="">${T("No interfaces")}</option>`}
      </select>
      <select class="selwrap" value=${peersView.status || ""} onChange=${e => { peersView.status = e.target.value || null; peersView.page = 1; force(x => x + 1); }}>
        ${peerStatusFilters().map(([v, l]) => html`<option value=${v}>${l}</option>`)}
      </select>
      ${restorableCount ? html`<button class="btn btn-restore" title=${T("Recreate every missing interface shown here with its original identity")} onClick=${() => confirmRestoreAll(rows)}><${Ic} i="refresh"/> ${T("Restore all dangling")}${restorableCount > 1 ? " · " + restorableCount : ""}</button>` : null}
      ${correctableCount ? html`<button class="btn btn-correct" title=${T("Assign each broken peer shown here the next free in-subnet address")} onClick=${() => confirmCorrectAll(rows)}><${Ic} i="check"/> ${T("Fix all broken")}${correctableCount > 1 ? " · " + correctableCount : ""}</button>` : null}
      <button class="btn btn-primary" onClick=${() => openCreatePeer(agg ? {} : { node, iface })}><span class="plus"><${Ic} i="plus"/></span> ${T("New peer")}</button>
    </div>

    <div class="section-title"><h2>${agg ? T("Peers") : T("Peers on")}</h2><span class="tags">
      ${node !== "*" ? html`<${Tag} kind="iface" label=${Store.nodeName(node) || "—"} color=${Store.nodeColor(node)}/>` : null}
      ${iface !== "*" && iface ? html`<${Tag} kind=${itype} label=${iface}/>` : null}
    </span><span class="count">${rows.length}</span></div>
    <${PeerGrid} rows=${pageRows} agg=${agg} node=${node} iface=${iface} shownByPeer=${shownByPeer} q=${peersView.q} sort=${peersView.sort} dir=${peersView.dir} onSort=${c => { peerSortBy(peersView, c); peersView.page = 1; force(x => x + 1); }}/>
    ${rows.length > 20 ? html`<div class="pager">
      <label class="pager-size">Rows per page
        <select class="selwrap" value=${pageSize} onChange=${e => { peersView.pageSize = +e.target.value; peersView.page = 1; force(x => x + 1); }}>
          ${[20, 30, 50, 100].map(n => html`<option value=${n}>${n}</option>`)}
        </select>
      </label>
      <span class="pager-info">${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, rows.length)} of ${rows.length}</span>
      <button class="btn btn-ghost" disabled=${page <= 1} onClick=${e => { setPage(page - 1); pageScroll(e, -1); }}>${T("‹ Prev")}</button>
      <span class="pager-pg">${page} / ${totalPages}</span>
      <button class="btn btn-ghost" disabled=${page >= totalPages} onClick=${e => { setPage(page + 1); pageScroll(e, 1); }}>${T("Next ›")}</button>
    </div>` : null}

    ${orphans.length ? html`<${Fragment}>
      <div class="section-title"><h2 style="color:var(--orphan)">${T("Unmanaged here")}</h2></div>
      <div class="tablewrap"><table><tbody>${orphans.map(o => html`<${OrphanRow} key=${o.node + "|" + o.iface + "|" + o.pubkey} o=${o}/>`)}</tbody></table></div>
    <//>` : null}
  </div>`;
}

// "No peers yet — add one." The call to action is a BUTTON mid-sentence, so the sentence is translated whole
// and split on its marker (see Tsplit) rather than glued together around it.
function noPeersYet(onAdd) {
  const [before, after] = Tsplit("No peers yet — {add}.", "add");
  return html`<${Fragment}>${before}<button class="linkbtn" onClick=${onAdd}>${T("add one")}</button>${after}<//>`;
}

export function ActivityHistoryScreen() {
  const [rows, setRows] = useState(null);   // null = still loading
  const [, force] = useState(0);
  const bump = () => force(x => x + 1);
  const load = () => api.events(1000).then(r => setRows(Array.isArray(r.data) ? r.data : [])).catch(() => setRows([]));
  useEffect(() => { load(); }, []);
  const all = (rows || []).map(evDecorate);
  const q = activityView.q.toLowerCase();
  let list = all;
  if (activityView.item) list = list.filter(e => e.item === activityView.item);
  if (activityView.action) list = list.filter(e => e.action === activityView.action);
  // search the TRANSLATED text as well as the stored English: the operator types what they can see,
  // and a row written before the sweep still matches its English verb.
  if (q) list = list.filter(e => (e.verb + " " + srvVerb(e.verb) + " " + e.name + " " + (e.detail || "") + " " + srvDetail(e))
    .toLowerCase().includes(q));
  const pageSize = 25;
  const totalPages = Math.max(1, Math.ceil(list.length / pageSize));
  const page = Math.min(Math.max(1, activityView.page), totalPages);
  const pageRows = list.slice((page - 1) * pageSize, page * pageSize);
  const setPage = p => { activityView.page = p; bump(); };
  const delOne = e => openConfirm({ title: T("Delete this entry?"), confirmLabel: T("Delete"), danger: true,
    body: Trich("Remove this record — *{v1}{v2}*? This can't be undone.", { v1: srvVerb(e.verb), v2: e.name ? " · " + e.name : "" }),
    onConfirm: async () => { await api.eventDelete(e.eid); await load(); } });
  const clearAll = () => openConfirm({ title: T("Clear all activity?"), confirmLabel: T("Clear history"), danger: true,
    body: Trich("Delete *all {v1}* from the activity log? This can't be undone.", { v1: plural(all.length, "record") }),
    onConfirm: async () => { await api.eventsClear(); activityView.page = 1; await load(); } });
  return html`<div class="screen">
    <div class="crumb"><a href="#/">${T("Overview")}</a><span class="sep">/</span><b>${T("Activity history")}</b></div>
    <div class="toolbar">
      <${SearchBox} placeholder=${T("Search action, name, detail…")} value=${activityView.q} onInput=${e => { activityView.q = e.target.value; activityView.page = 1; bump(); }}/>
      <select class="selwrap" value=${activityView.item} onChange=${e => { activityView.item = e.target.value; activityView.page = 1; bump(); }}>
        <option value="">${T("All items")}</option>${EV_ITEMS.map(i => html`<option value=${i}>${evItemLabel(i)}</option>`)}
      </select>
      <select class="selwrap" value=${activityView.action} onChange=${e => { activityView.action = e.target.value; activityView.page = 1; bump(); }}>
        <option value="">${T("All actions")}</option>${EV_ACTIONS.map(a => html`<option value=${a}>${evActionLabel(a)}</option>`)}
      </select>
      <button class="btn btn-danger" disabled=${!all.length} onClick=${clearAll}><${Ic} i="trash"/> ${T("Clear history")}</button>
    </div>
    ${secTitle(T("Activity history"), html`${list.length}${list.length !== all.length ? " / " + all.length : ""}`, false)}
    ${rows === null ? html`<div class="loading"><${Ic} i="refresh"/> ${T("Loading…")}</div>`
      : !all.length ? html`<div class="empty"><b>${T("No activity yet")}</b>${T("Operator actions across the panel will show up here.")}</div>`
      : !list.length ? html`<div class="empty"><b>${T("No matches")}</b>${T("Try a different search or filter.")}</div>`
      : html`<div class="acthist">${pageRows.map(e => html`<div class=${"act-row" + (e.click ? "" : " noclk")} key=${e.key}>
          <span class=${"act-ic t-" + e.slug}><${Ic} i=${e.icon}/></span>
          ${e.click
            ? html`<a class="act-link" href=${e.click.href} onClick=${e.click.on ? (ev => { ev.preventDefault(); e.click.on(); }) : null}><span class="act-what">${srvVerb(e.verb)}</span>${e.name ? html`<span class="act-name">${e.name}</span>` : null}</a>`
            : html`<span class="act-what">${srvVerb(e.verb)}</span>${e.name ? html`<span class="act-name">${e.name}</span>` : null}`}
          ${e.detail || e.detail_key ? html`<span class="act-detail">${srvDetail(e)}</span>` : null}
          <span class="grow"></span>
          <span class="act-cat">${e.itemLabel || e.item}</span>
          <span class="when">${ago(e.ts)}</span>
          <button class="iconbtn danger" title=${T("Delete entry")} onClick=${() => delOne(e)}><${Ic} i="x"/></button>
        </div>`)}</div>`}
    ${list.length > pageSize ? html`<div class="pager">
      <span class="pager-info">${T("{from}–{to} of {total}", { from: (page - 1) * pageSize + 1, to: Math.min(page * pageSize, list.length), total: list.length })}</span>
      <button class="btn btn-ghost" disabled=${page <= 1} onClick=${() => setPage(page - 1)}>${T("‹ Prev")}</button>
      <span class="pager-pg">${page} / ${totalPages}</span>
      <button class="btn btn-ghost" disabled=${page >= totalPages} onClick=${() => setPage(page + 1)}>${T("Next ›")}</button>
    </div>` : null}
  </div>`;
}

// ═════════════════════════ SCREEN: LIVE (Peers / Users monitor) ═════════════════════════
// Read-only over the enriched snapshot. A Peers↔Users toggle switches between the shared PeerGrid (in `live`
// mode — dot status, endpoint column, no controls) and the shared UserRow list (also `live`). Node/interface
// dropdowns + a global search + an Online filter narrow both. State lives in module scope so the 5s poll
// never loses it; Preact keeps scroll + updates cells in place.

export function ConnectionsScreen() {
  useStore();
  const [, force] = useState(0);
  const bump = () => force(x => x + 1);
  const reset = () => { connView.page = 1; bump(); };   // any filter/mode change → back to page 1
  const mode = connView.mode, q = connView.q.toLowerCase();
  const allIfaces = Array.from(new Set(Object.keys(Store.describe).flatMap(n => Store.userIfacesOf(n)))).sort();
  const ifaceOpts = connView.node ? Store.userIfacesOf(connView.node) : allIfaces;
  if (!ifaceIsAll(connView.iface) && !ifaceOpts.includes(connView.iface)) connView.iface = "";
  const setMode = m => { connView.mode = m; reset(); };
  const setPage = p => { connView.page = p; bump(); };
  // shared pager (both modes) — mirrors the Peers/Users screens
  const pager = (total) => {
    const pageSize = connView.pageSize || 20, totalPages = Math.max(1, Math.ceil(total / pageSize));
    const page = Math.min(Math.max(1, connView.page || 1), totalPages);
    return total > pageSize ? html`<div class="pager">
      <label class="pager-size">Rows per page
        <select class="selwrap" value=${pageSize} onChange=${e => { connView.pageSize = +e.target.value; reset(); }}>
          ${[20, 30, 50, 100].map(n => html`<option value=${n}>${n}</option>`)}
        </select></label>
      <span class="pager-info">${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total}</span>
      <button class="btn btn-ghost" disabled=${page <= 1} onClick=${() => setPage(page - 1)}>${T("‹ Prev")}</button>
      <span class="pager-pg">${page} / ${totalPages}</span>
      <button class="btn btn-ghost" disabled=${page >= totalPages} onClick=${() => setPage(page + 1)}>${T("Next ›")}</button>
    </div>` : null;
  };
  const paginate = (list) => { const pageSize = connView.pageSize || 20, totalPages = Math.max(1, Math.ceil(list.length / pageSize));
    const page = Math.min(Math.max(1, connView.page || 1), totalPages); return list.slice((page - 1) * pageSize, page * pageSize); };

  const toolbar = html`<div class="toolbar">
    <div class="pmode">
      <button class=${"pm-opt pm-peers" + (mode === "peers" ? " on" : "")} onClick=${() => setMode("peers")}>${T("Peers")}</button>
      <button class=${"pm-opt pm-users" + (mode === "users" ? " on" : "")} onClick=${() => setMode("users")}>${T("Users")}</button>
    </div>
    <${SearchBox} placeholder=${mode === "users" ? T("Search users, tags, peers…") : T("Search peer, user, endpoint, IP…")} value=${connView.q} onInput=${e => { connView.q = e.target.value; reset(); }}/>
    <select class="selwrap" value=${connView.node} onChange=${e => { connView.node = e.target.value; connView.iface = ""; reset(); }}>
      ${nodeFilterOptions("")}
    </select>
    <select class="selwrap" value=${connView.iface} onChange=${e => { connView.iface = e.target.value; reset(); }}>
      ${ifaceFilterOptions(ifaceOpts, "")}
    </select>
    <button class=${"onlbtn" + (connView.online ? " on" : "")} title=${T("Show only online connections")} onClick=${() => { connView.online = !connView.online; reset(); }}>${T("status|Online")}</button>
  </div>`;

  if (mode === "users") {
    // filter the user LIST by node/iface (has a peer there) + search + Online; the expanded grid still shows ALL peers
    const users = sortUsers(Store.recon.users, connView.usort, connView.udir, "live").filter(u => userMatchesQ(u, q) && userOnNodeIface(u, connView.node, connView.iface) && (!connView.online || u.onlineCount > 0));
    return html`<div class="screen">
      ${toolbar}
      <div class="section-title"><h2 class="live-users">${T("Users")}</h2><span class="count">${users.length}</span></div>
      ${users.length ? html`<${Fragment}>
        <${UsersHeader} live=${true} sort=${connView.usort} dir=${connView.udir} onSort=${c => { sortColToggle(connView, "usort", "udir", c, USER_DEFDIR); connView.page = 1; bump(); }}/>
        <div class="urows">${paginate(users).map(u => html`<${UserRow} key=${u.id} user=${u} live=${true} onlineOnly=${connView.online} q=${q}/>`)}</div>
      <//>`
        : html`<div class="empty"><b>${connView.online ? T("No users online") : T("Nothing matches")}</b>${connView.online ? T("No user has an online peer right now.") : T("Clear the filters.")}</div>`}
      ${pager(users.length)}
    </div>`;
  }

  // peers mode — one row per deployment, rendered via the shared PeerGrid in live mode. Lists ALL deployments with a
  // live online/offline badge (matching Users mode, which lists every user); the Online filter narrows to live ones.
  let rows = [];
  for (const p of Store.recon.peers) for (const t of p.targets) {
    if (connView.node && t.node !== connView.node) continue;
    if (!ifaceMatch(t.iface, connView.iface)) continue;
    if (connView.online && !t.online) continue;                        // Online filter → only live connections
    rows.push({ p, t });
  }
  if (q) rows = rows.filter(({ p, t }) => { const u = p.user_id ? Store.user(p.user_id) : null; const o = t.observed || {};
    return searchMatch((p.title || "") + " " + (p.name || "") + " " + (u ? u.name : "") + " " + (t.ip || "") + " " + Store.nodeName(t.node) + " " + t.iface + " " + (o.endpoint || ""), q); });
  rows = sortPeerRows(rows, connView.sort, connView.dir, "livepeers");
  const shownByPeer = {};
  for (const { p, t } of rows) (shownByPeer[p.id] = shownByPeer[p.id] || new Set()).add(tkey(t.node, t.iface));
  const onlineCount = rows.filter(r => r.t.online).length;

  return html`<div class="screen">
    ${toolbar}
    <div class="section-title"><h2 class="live-peers">${T("Peers")}</h2><span class="count">${T("{n} shown · {online} online", { n: rows.length, online: onlineCount })}</span></div>
    ${rows.length
      ? html`<${PeerGrid} rows=${paginate(rows)} agg=${true} node="*" iface="*" shownByPeer=${shownByPeer} q=${connView.q} live=${true} loc=${true} hideUser=${false} sort=${connView.sort} dir=${connView.dir} onSort=${c => { peerSortBy(connView, c); connView.page = 1; bump(); }}/>`
      : html`<div class="empty"><b>${connView.online ? T("No connections online") : T("Nothing matches")}</b>${connView.online ? T("No peer is online with these filters.") : T("Clear the filters.")}</div>`}
    ${pager(rows.length)}
  </div>`;
}

// ═════════════════════════ SCREEN: USERS ═════════════════════════



// A peer's configs as a modal: one QR/download card per target (reuses TargetCard).
// One peer's QR cards on a SINGLE line — up to 3 per view, paged with ‹ › when the peer has more
// (never wraps to a second row). The card cards are passed in already built.
export function UserRow({ user, live, onlineOnly, q }) {
  const [, force] = useState(0);
  // While searching, matching users auto-expand (unless the operator explicitly collapsed one). If the user
  // matched only via some of their PEERS (not their own name/tag/note), the expanded grid shows just those
  // matching peers — a matching child pulls in its parent, siblings stay hidden. An identity match shows all peers.
  const searching = !!q;
  const idMatch = userIdentityMatchesQ(user, q);
  const expanded = searching ? (usersView.expanded[user.id] !== false) : !!usersView.expanded[user.id];
  const toggle = () => { usersView.expanded[user.id] = !expanded; force(x => x + 1); };
  const allPeers = Store.peersOfUser(user.id);
  const shownPeers = (searching && !idMatch) ? allPeers.filter(p => peerMatchesQ(p, q)) : allPeers;
  // nodes the user has peers on → for the hover bubble: each node's interfaces listed ONCE with a peer count, by node.
  const _nm = {};
  for (const p of allPeers) for (const t of p.targets) {
    const nn = _nm[t.node] = _nm[t.node] || {};
    if (!nn[t.iface]) nn[t.iface] = { iface: t.iface, type: targetType(t), count: 0 };
    nn[t.iface].count++;
  }
  const srvNodes = Object.keys(_nm).map(nid => ({ node: nid, ifaces: Object.values(_nm[nid]).sort((a, b) => a.iface.localeCompare(b.iface)) }))
    .sort((a, b) => Store.nodeName(a.node).localeCompare(Store.nodeName(b.node)));
  const st = userStats(user.id);
  const [db, ub] = dlul(st.rxb, st.txb);
  const view = userPeerViews[user.id] || (userPeerViews[user.id] = { node: "", iface: "", q: "", page: 1, pageSize: 20, sort: "status", dir: -1 });
  return html`<div class=${"urow" + (expanded ? " open" : "")} id=${"urow-" + user.id}>
    <div class="urow-head" title=${T("Double-click for QR / configs")} onMouseDown=${rowNoSelect} onClick=${e => rowSingle(e, toggle)} onDblClick=${e => rowDouble(e, () => openUserConfigs(user))}>
      <span class="u-exp"><${Ic} i="arrow"/></span>
      ${userStatTag(user, live)}
      <span class="u-name">${lifecycleIcon(user, user.peerCount ? user.status : "empty")}<span class="un">${user.name}</span>${user.tag ? html`<span class="tagchip">${user.tag}</span>` : null}${user.note ? html`<span class="u-note" title=${user.note}>${user.note}</span>` : null}</span>
      <span class=${"u-right" + (live ? " live" : "")}>
        <span class="u-counts">${(() => {
          const onc = html`<span class=${"u-onc" + (user.onlineCount ? " on" : "")}>${T("{n} Online", { n: user.onlineCount })}</span>`;
          const pc = html`<span class="u-pc">${plural(user.peerCount, "cap|Peer")}</span>`;
          const sep = html`<span class="u-dot"> · </span>`;
          return live ? html`${onc}${sep}${pc}` : html`${pc}${user.peerCount ? html`${sep}${onc}` : null}`;
        })()}</span>
        <span class="u-servers">${srvNodes.length ? html`<span class="turnwrap srvwrap" onClick=${e => e.stopPropagation()}>
          <span class="srvchips">
            ${srvNodes.length === 1 ? html`<span class="nsrv" style=${"--c:" + Store.nodeColor(srvNodes[0].node)}>${Store.nodeName(srvNodes[0].node)}</span>`
              : html`<span class="nsrv-agg"><${Ic} i="server"/>${plural(srvNodes.length, "cap|Node")}</span>`}
          </span>
          <span class="turnbub servbub">${srvNodes.flatMap(n => n.ifaces.map(f => html`<span class="servbub-row">
            <span class="nsrv" style=${"--c:" + Store.nodeColor(n.node)}>${Store.nodeName(n.node)}</span>
            <${Tag} kind=${f.type} label=${f.iface}/>
            <span class="servbub-pc">${plural(f.count, "cap|Peer")}</span>
          </span>`))}</span>
        </span>` : html`<span class="faint">—</span>`}</span>
        <span class="u-last">${st.last == null ? html`<span class="u-never">${T("Never")}</span>` : html`<span class="when">${seen(st.last)}</span>`}</span>
        <span class="u-thru">${rateCell(st.rx, st.tx)}</span>
        <span class="u-total">${xferCell(db, ub)}</span>
        ${live ? null : html`<span class="u-acts" onClick=${e => e.stopPropagation()}>
          <button class="iconbtn qr" title=${T("Show QR / configs")} onClick=${() => openUserConfigs(user)}><${Ic} i="qr"/></button>
          <button class="iconbtn" title=${T("Edit user")} onClick=${() => openUserEdit(user)}><${Ic} i="pencil"/></button>
          <button class="iconbtn iconbtn-add" title=${T("Add peer")} onClick=${() => openAddPeers(user.id, user.name)}><${Ic} i="plus"/></button>
        </span>`}
      </span>
    </div>
    ${expanded ? html`<div class="urow-body">
      ${shownPeers.length ? html`<${EmbeddedPeers} peers=${shownPeers} view=${view} hideUser=${true} hideToolbar=${true} collapse=${true} live=${live} onlineOnly=${onlineOnly} freezeKey=${"uembed|" + user.id}/>`
        : html`<div class="ug-empty">${user.peerCount ? T("No peers match.") : noPeersYet(() => openAddPeers(user.id, user.name))}</div>`}
    </div>` : null}
    <${RowError} k=${"user:" + user.id}/>
  </div>`;
}

export function UsersScreen() {
  useStore();
  const [, force] = useState(0);
  const q = usersView.q.toLowerCase();
  const allUsers = Store.recon.users;
  const allIfaces = Array.from(new Set(Object.keys(Store.describe).flatMap(n => Store.userIfacesOf(n)))).sort();
  const ifaceOpts = usersView.node ? Store.userIfacesOf(usersView.node) : allIfaces;
  if (!ifaceIsAll(usersView.iface) && !ifaceOpts.includes(usersView.iface)) usersView.iface = "";
  // node/iface filter the user LIST (has a peer there); each expanded row still shows ALL of that user's peers
  // freeze the order over the FULL list, then filter — so searching/clearing never reshuffles the frozen rows
  const users = sortUsers(allUsers, usersView.sort, usersView.dir, "users").filter(u => userMatchesQ(u, q) && userOnNodeIface(u, usersView.node, usersView.iface));
  // The toolbar search filters the USER list only. The unassigned grid is deliberately NOT filtered by it:
  // the whole point of searching for a user here is to then assign an unassigned peer to them, and filtering
  // both by the same term hid every peer whose title didn't happen to match the user's name. The grid has its
  // own search box (unassignedView.q, applied inside EmbeddedPeers) for filtering the peers themselves.
  const unassigned = Store.unassignedPeers();

  const pageSize = usersView.pageSize || 20;
  const totalPages = Math.max(1, Math.ceil(users.length / pageSize));
  const page = Math.min(Math.max(1, usersView.page || 1), totalPages);
  const pageUsers = users.slice((page - 1) * pageSize, page * pageSize);
  const setPage = p => { usersView.page = p; force(x => x + 1); };

  return html`<div class="screen">
    <${StoreOffBanner}/>
    <div class="toolbar">
      <${SearchBox} placeholder=${T("Search users, tags, notes, peers…")} value=${usersView.q} onInput=${e => { usersView.q = e.target.value; usersView.page = 1; force(x => x + 1); }}/>
      <select class="selwrap" value=${usersView.node} onChange=${e => { usersView.node = e.target.value; usersView.iface = ""; usersView.page = 1; force(x => x + 1); }}>
        ${nodeFilterOptions("")}
      </select>
      <select class="selwrap" value=${usersView.iface} onChange=${e => { usersView.iface = e.target.value; usersView.page = 1; force(x => x + 1); }}>
        ${ifaceFilterOptions(ifaceOpts, "")}
      </select>
      <button class="btn btn-ghost" onClick=${() => openCreatePeer({})}><span class="plus"><${Ic} i="plus"/></span> ${T("New peer")}</button>
      <button class="btn btn-primary" onClick=${openCreateUser}><span class="plus"><${Ic} i="plus"/></span> ${T("New user")}</button>
    </div>

    ${secTitle(T("Users"), users.length, false)}
    ${!allUsers.length ? html`<div class="empty"><b>${T("No users yet")}</b>${T("Create a user, then mint peers for them — or create a peer and assign it later.")}</div>`
      : !users.length ? html`<div class="empty"><b>${T("Nothing matches")}</b>${T("Clear the search.")}</div>`
      : html`<${Fragment}>
        <${UsersHeader} sort=${usersView.sort} dir=${usersView.dir} onSort=${c => { sortColToggle(usersView, "sort", "dir", c, USER_DEFDIR); usersView.page = 1; force(x => x + 1); }}/>
        <div class="urows">${pageUsers.map(u => html`<${UserRow} key=${u.id} user=${u} q=${q}/>`)}</div>
      <//>`}
    ${users.length > pageSize ? html`<div class="pager">
      <label class="pager-size">Rows per page
        <select class="selwrap" value=${pageSize} onChange=${e => { usersView.pageSize = +e.target.value; usersView.page = 1; force(x => x + 1); }}>
          ${[20, 30, 50, 100].map(n => html`<option value=${n}>${n}</option>`)}
        </select></label>
      <span class="pager-info">${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, users.length)} of ${users.length}</span>
      <button class="btn btn-ghost" disabled=${page <= 1} onClick=${e => { setPage(page - 1); pageScroll(e, -1); }}>${T("‹ Prev")}</button>
      <span class="pager-pg">${page} / ${totalPages}</span>
      <button class="btn btn-ghost" disabled=${page >= totalPages} onClick=${e => { setPage(page + 1); pageScroll(e, 1); }}>${T("Next ›")}</button>
    </div>` : null}

    ${unassigned.length ? html`<${Fragment}>
      <div class="section-title"><h2 style="color:var(--faint)">${T("Unassigned peers")}</h2><span class="count">${unassigned.length}</span></div>
      <${EmbeddedPeers} peers=${unassigned} view=${unassignedView} collapse=${true} freezeKey=${"unassigned-embed"}/>
    <//>` : null}
  </div>`;
}

// ═════════════════════════ SCREEN: USER DETAIL ═════════════════════════


// ═════════════════════════ SCREEN: NODES ═════════════════════════
// ═════════════════════════ SCREEN: ACCOUNT ═════════════════════════
