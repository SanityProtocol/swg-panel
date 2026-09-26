/* screen-roster.js — Peers, Users, Live and the activity history.
 *
 * LAYER 11 (see docs/APP-JS-SPLIT-PLAN.md). Four screens in one module because they are four views of
 * ONE thing: the same peers, through different lenses. They render the same PeerGrid, filter through the
 * same views.js state and sort with the same comparators — which is exactly the coupling the graph showed
 * (63 and 41 references between them) before views.js and grids.js gave that shared half a home.
 */

import {
  ago, seen, tkey, isPrimaryTarget,
} from "./util.js";
import { T, Tsplit, Trich, plural, srvVerb, srvDetail, srvName } from "./i18n.js";
import {
  Store, api, bus, useStore,
} from "./store.js";
import {
  ifaceIsAll, ifaceMatch, targetType, awgGen,
} from "./model.js";
import {
  CapList, Dropdown, Ic, Popover, RowError, SearchBox, StoreOffBanner, Tag, dlul, lifecycleIcon, openConfirm, rateCell, rowDouble,
  rowNoSelect, rowSingle, secTitle, xferCell, tgt3,
} from "./ui.js";
import {
  EV_ACTIONS, EV_ITEMS, evItemLabel, evActionLabel, peerStatusFilters, USER_DEFDIR, activityView, connView, evDecorate,
  ifaceFilterOptions, ifaceOptGroups, nodeFilterOptions, pageScroll, pageSizeOpts, peerMatchesQ, peerSortBy, peersView,
  searchMatch, sortColToggle, sortPeerRows, sortUsers, unassignedView, userIdentityMatchesQ, userMatchesQ,
  userOnNodeIface, userPeerViews, userStatTag, userStats, usersView, groupShares, shareDeviceName,
  groupMemberViews, groupStats, sortGroups, GROUP_DEFDIR, trafficRangeLabel,
} from "./views.js";
import {
  confirmCorrectAll, confirmRestoreAll,
} from "./peer-actions.js";
import {
  openUserConfigs, openUserEdit, openGroup, openCreateGroup, confirmDeleteGroup, UserCounts,
} from "./peer-ui.js";
import {
  openAddPeers, openCreatePeer, openCreateUser, openUserView, openGroupView,
} from "./sheets-crud.js";
import { TrafficRail, TrafficCell, UserTrafficCell } from "./traffic-ui.js";
import { trafficTotals } from "./traffic.js";
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

// The roster lists' pager — Peers, Users, Groups: rows per page, where you are, Prev / Next with the scroll back to the list.
// ONE copy, so a fix to paging lands on every list. Shown once a list is longer than the smallest page (20), so "Rows per page"
// stays reachable after choosing a larger size.
function RowsPager({ total, page, pageSize, onPage, onSize }) {
  if (total <= 20) return null;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return html`<div class="pager">
    <label class="pager-size">${T("Rows per page")}
      <${Dropdown} className="selwrap" ariaLabel=${T("Rows per page")} value=${pageSize} options=${pageSizeOpts()} onChange=${onSize}/>
    </label>
    <span class="pager-info">${T("{from}–{to} of {total}", { from: (page - 1) * pageSize + 1, to: Math.min(page * pageSize, total), total })}</span>
    <button class="btn btn-ghost" disabled=${page <= 1} onClick=${e => { onPage(page - 1); pageScroll(e, -1); }}>${T("‹ Prev")}</button>
    <span class="pager-pg">${page} / ${pages}</span>
    <button class="btn btn-ghost" disabled=${page >= pages} onClick=${e => { onPage(page + 1); pageScroll(e, 1); }}>${T("Next ›")}</button>
  </div>`;
}

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
  const grouped = !!peersView.group;
  // one row per matching (peer, target) DEPLOYMENT, so a fleet-wide view shows where each peer lives —
  // unless Group is on, which collapses to one row per PEER (its primary deployment, the rest as +N).
  let rows = [];
  for (const p of Store.recon.peers) {
    const ts = p.targets.filter(t => (node === "*" || t.node === node) && ifaceMatch(t.iface, iface, t));
    if (!ts.length) continue;
    if (!grouped) { for (const t of ts) rows.push({ p, t }); continue; }
    // The peer's PRIMARY deployment represents it — that is the one its subscription leads with, so the
    // grouped row says the same thing the user's own page does. Falling back to an online one keeps the
    // row informative when the primary happens to be down.
    const rep = ts.find(t => isPrimaryTarget(p.targets, t)) || ts.find(t => t.online) || ts[0];
    rows.push({ p, t: rep });
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
    <${TrafficRail}/>
    <div class="toolbar">
      <button class=${"onlbtn" + (grouped ? " on" : "")}
        title=${grouped ? T("One row per peer — its other deployments are behind the +N") : T("Collapse each peer's deployments into one row")}
        onClick=${() => { peersView.group = !peersView.group; peersView.page = 1; force(x => x + 1); }}>${grouped ? T("btn|Grouped") : T("btn|Group")}</button>
      <${SearchBox} placeholder=${T("Search title, user, address…")} value=${peersView.q} onInput=${e => { peersView.q = e.target.value; peersView.page = 1; force(x => x + 1); }}/>
      <${Dropdown} className="selwrap" ariaLabel=${T("All nodes")} value=${node}
        onChange=${v => { peersView.node = v; peersView.iface = ""; peersView.page = 1; force(x => x + 1); }}
        options=${[...(multiServer ? [{ value: "*", label: T("All nodes") }]
                     : !fleet.length ? [{ value: "*", label: T("No nodes") }] : []),
                   ...fleet.map(n => ({ value: n.id, label: n.name }))]}/>
      <${Dropdown} className="selwrap" ariaLabel=${T("All interfaces")} value=${iface}
        onChange=${v => { peersView.iface = v; peersView.page = 1; force(x => x + 1); }}
        options=${[...(ifaceOpts.length && (node === "*" || ifaceOpts.length > 1) ? [{ value: "*", label: T("All interfaces") }] : []),
                   ...(ifaceOpts.length ? ifaceOptGroups(ifaceOpts) : [{ value: "", label: T("No interfaces") }])]}/>
      <${Dropdown} className="selwrap" ariaLabel=${T("All statuses")} value=${peersView.status || ""}
        onChange=${v => { peersView.status = v || null; peersView.page = 1; force(x => x + 1); }}
        options=${peerStatusFilters()}/>
      ${restorableCount ? html`<button class="btn btn-restore" title=${T("Recreate every missing interface shown here with its original identity")} onClick=${() => confirmRestoreAll(rows)}><${Ic} i="refresh"/> ${T("Restore all dangling")}${restorableCount > 1 ? " · " + restorableCount : ""}</button>` : null}
      ${correctableCount ? html`<button class="btn btn-correct" title=${T("Assign each broken peer shown here the next free in-subnet address")} onClick=${() => confirmCorrectAll(rows)}><${Ic} i="check"/> ${T("Fix all broken")}${correctableCount > 1 ? " · " + correctableCount : ""}</button>` : null}
      <button class="btn btn-primary" onClick=${() => openCreatePeer(agg ? {} : { node, iface })}><span class="plus"><${Ic} i="plus"/></span> ${T("New peer")}</button>
    </div>

    <div class="section-title"><h2>${agg ? T("Peers") : T("Peers on")}</h2><span class="tags">
      ${node !== "*" ? html`<${Tag} kind="iface" label=${Store.nodeName(node) || "—"} color=${Store.nodeColor(node)}/>` : null}
      ${iface !== "*" && iface ? html`<${Tag} kind=${itype} label=${iface} gen3=${itype === "awg" && awgGen(node, iface) === "3.1"}/>` : null}
    </span><span class="count">${rows.length}</span></div>
    <${PeerGrid} rows=${pageRows} agg=${agg} node=${node} iface=${iface} shownByPeer=${shownByPeer} q=${peersView.q} grouped=${grouped} ranged=${true} sort=${peersView.sort} dir=${peersView.dir} onSort=${c => { peerSortBy(peersView, c); peersView.page = 1; force(x => x + 1); }}/>
    <${RowsPager} total=${rows.length} page=${page} pageSize=${pageSize} onPage=${setPage}
      onSize=${v => { peersView.pageSize = v; peersView.page = 1; force(x => x + 1); }}/>

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
      <${Dropdown} className="selwrap" ariaLabel=${T("All items")} value=${activityView.item}
        onChange=${v => { activityView.item = v; activityView.page = 1; bump(); }}
        options=${[{ value: "", label: T("All items") }, ...EV_ITEMS.map(i => ({ value: i, label: evItemLabel(i) }))]}/>
      <${Dropdown} className="selwrap" ariaLabel=${T("All actions")} value=${activityView.action}
        onChange=${v => { activityView.action = v; activityView.page = 1; bump(); }}
        options=${[{ value: "", label: T("All actions") }, ...EV_ACTIONS.map(a => ({ value: a, label: evActionLabel(a) }))]}/>
      <button class="btn btn-danger" disabled=${!all.length} onClick=${clearAll}><${Ic} i="trash"/> ${T("Clear history")}</button>
    </div>
    ${secTitle(T("Activity history"), html`${list.length}${list.length !== all.length ? " / " + all.length : ""}`, false)}
    ${rows === null ? html`<div class="loading"><${Ic} i="refresh"/> ${T("Loading…")}</div>`
      : !all.length ? html`<div class="empty"><b>${T("No activity yet")}</b>${T("Operator actions across the panel will show up here.")}</div>`
      : !list.length ? html`<div class="empty"><b>${T("No matches")}</b>${T("Try a different search or filter.")}</div>`
      : html`<div class="acthist">${pageRows.map(e => html`<div class=${"act-row" + (e.click ? "" : " noclk")} key=${e.key}>
          <span class=${"act-ic t-" + e.slug}><${Ic} i=${e.icon}/></span>
          ${e.click
            ? html`<a class="act-link" href=${e.click.href} onClick=${e.click.on ? (ev => { ev.preventDefault(); e.click.on(); }) : null}><span class="act-what">${srvVerb(e.verb)}</span>${e.name ? html`<span class="act-name">${srvName(e)}</span>` : null}</a>`
            : html`<span class="act-what">${srvVerb(e.verb)}</span>${e.name ? html`<span class="act-name">${srvName(e)}</span>` : null}`}
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
      <label class="pager-size">${T("Rows per page")}
        <${Dropdown} className="selwrap" ariaLabel=${T("Rows per page")} value=${pageSize} options=${pageSizeOpts()}
          onChange=${v => { connView.pageSize = v; reset(); }}/></label>
      <span class="pager-info">${T("{from}–{to} of {total}", { from: (page - 1) * pageSize + 1, to: Math.min(page * pageSize, total), total })}</span>
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
    <${Dropdown} className="selwrap" ariaLabel=${T("All nodes")} value=${connView.node}
      onChange=${v => { connView.node = v; connView.iface = ""; reset(); }} options=${nodeFilterOptions("")}/>
    <${Dropdown} className="selwrap" ariaLabel=${T("All interfaces")} value=${connView.iface}
      onChange=${v => { connView.iface = v; reset(); }} options=${ifaceFilterOptions(ifaceOpts, "")}/>
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
    if (!ifaceMatch(t.iface, connView.iface, t)) continue;
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



// The nodes a set of peers lives on, each node's interfaces listed ONCE with a peer count — the Nodes column's hover bubble.
function nodesOfPeers(peers) {
  const nm = {};
  for (const p of peers) for (const t of p.targets) {
    const nn = nm[t.node] = nm[t.node] || {};
    if (!nn[t.iface]) nn[t.iface] = { iface: t.iface, type: targetType(t), gen3: tgt3(t), count: 0 };
    nn[t.iface].count++;
  }
  return Object.keys(nm).map(nid => ({ node: nid, ifaces: Object.values(nm[nid]).sort((a, b) => a.iface.localeCompare(b.iface)) }))
    .sort((a, b) => Store.byNode(a.node, b.node));
}
// The Nodes cell (users and groups): one node's badge, or "N Nodes"; hover lists each node's interfaces and peer counts.
function nodesChip(srvNodes) {
  if (!srvNodes.length) return html`<span class="faint">—</span>`;
  return html`<span class="turnwrap srvwrap" title="" onClick=${e => e.stopPropagation()}>
    <span class="srvchips">
      ${srvNodes.length === 1 ? html`<span class="nsrv" style=${"--c:" + Store.nodeColor(srvNodes[0].node)}>${Store.nodeName(srvNodes[0].node)}</span>`
        : html`<span class="nsrv-agg"><${Ic} i="server"/>${plural(srvNodes.length, "cap|Node")}</span>`}
    </span>
    <span class="turnbub servbub">${srvNodes.flatMap(n => n.ifaces.map(f => html`<span class="servbub-row">
      <span class="nsrv" style=${"--c:" + Store.nodeColor(n.node)}>${Store.nodeName(n.node)}</span>
      <${Tag} kind=${f.type} label=${f.iface} gen3=${f.gen3}/>
      <span class="servbub-pc">${plural(f.count, "cap|Peer")}</span>
    </span>`))}</span>
  </span>`;
}

// A peer's configs as a modal: one QR/download card per target (reuses TargetCard).
// One peer's QR cards on a SINGLE line — up to 3 per view, paged with ‹ › when the peer has more
// (never wraps to a second row). The card cards are passed in already built.
export function UserRow({ user, live, onlineOnly, q, nested }) {
  const [, force] = useState(0);
  // While searching, matching users auto-expand (unless the operator explicitly collapsed one). If the user
  // matched only via some of their PEERS (not their own name/tag/note), the expanded grid shows just those
  // matching peers — a matching child pulls in its parent, siblings stay hidden. An identity match shows all peers.
  const searching = !!q;
  const idMatch = userIdentityMatchesQ(user, q);
  const expanded = searching ? (usersView.expanded[user.id] !== false) : !!usersView.expanded[user.id];
  const toggle = () => { usersView.expanded[user.id] = !expanded; force(x => x + 1); };
  const allPeers = Store.peersByUser(user.id);
  const shownPeers = (searching && !idMatch) ? allPeers.filter(p => peerMatchesQ(p, q)) : allPeers;
  const srvNodes = nodesOfPeers(allPeers);
  const st = userStats(user.id);
  const [db, ub] = dlul(st.rxb, st.txb);
  const view = userPeerViews[user.id] || (userPeerViews[user.id] = { node: "", iface: "", q: "", page: 1, pageSize: 20, sort: "status", dir: -1 });
  // a member row inside an open group carries no id: the users list's own row is the one revealUser() scrolls to
  return html`<div class=${"urow" + (expanded ? " open" : "")} id=${nested ? null : "urow-" + user.id}>
    <div class="urow-head" title=${T("Double-click for QR / configs")} onMouseDown=${rowNoSelect} onClick=${e => rowSingle(e, toggle)} onDblClick=${e => rowDouble(e, () => openUserConfigs(user))}>
      <span class="u-exp"><${Ic} i="arrow"/></span>
      ${userStatTag(user, live)}
      <span class="u-name">${lifecycleIcon(user, user.peerCount ? user.status : "empty")}<span class="un">${user.name}</span>${user.tag ? html`<span class="tagchip">${user.tag}</span>` : null}${user.note ? html`<span class="u-note" title=${user.note}>${user.note}</span>` : null}<${UserCounts} user=${user}/></span>
      <span class=${"u-right" + (live ? " live" : "")}>
        <span class="u-counts">${(() => {
          const onc = html`<span class=${"u-onc" + (user.onlineCount ? " on" : "")}>${T("{n} Online", { n: user.onlineCount })}</span>`;
          const pc = html`<span class="u-pc">${plural(user.peerCount, "cap|Peer")}</span>`;
          const sep = html`<span class="u-dot"> · </span>`;
          return live ? html`${onc}${sep}${pc}` : html`${pc}${user.peerCount ? html`${sep}${onc}` : null}`;
        })()}</span>
        <span class="u-servers">${nodesChip(srvNodes)}</span>
        <span class="u-last">${st.last == null ? html`<span class="u-never">${T("Never")}</span>` : html`<span class="when">${seen(st.last)}</span>`}</span>
        <span class="u-thru">${rateCell(st.rx, st.tx)}</span>
        ${live ? html`<span class="u-total">${xferCell(db, ub)}</span>`
          // the user's figure opens the user's view — their graph and every device they had (O12)
          : html`<span class="u-total clk" role="button" tabindex="0" title=${T("Open this user's traffic — graph and devices")}
              onClick=${e => { e.stopPropagation(); openUserView(user.id); }} onDblClick=${e => e.stopPropagation()}
              onKeyDown=${e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); openUserView(user.id); } }}><${UserTrafficCell} uid=${user.id}/></span>`}
        ${live ? null : html`<span class="u-acts" onClick=${e => e.stopPropagation()}>
          <button class="iconbtn qr" title=${T("Show QR / configs")} onClick=${() => openUserConfigs(user)}><${Ic} i="qr"/></button>
          <button class="iconbtn" title=${T("Traffic — graph and devices")} aria-label=${T("Traffic — graph and devices")} onClick=${() => openUserView(user.id)}><${Ic} i="bars"/></button>
          <button class="iconbtn" title=${T("Edit user")} onClick=${() => openUserEdit(user)}><${Ic} i="pencil"/></button>
          <button class="iconbtn iconbtn-add" title=${T("Add peer")} onClick=${() => openAddPeers(user.id, user.name)}><${Ic} i="plus"/></button>
        </span>`}
      </span>
    </div>
    ${expanded ? html`<div class="urow-body">
      ${shownPeers.length ? html`<${EmbeddedPeers} peers=${shownPeers} view=${view} hideUser=${true} hideToolbar=${true} collapse=${true} live=${live} onlineOnly=${onlineOnly} owner=${user.id} freezeKey=${"uembed|" + user.id}/>`
        : html`<div class="ug-empty">${user.peerCount ? T("No peers match.") : noPeersYet(() => openAddPeers(user.id, user.name))}</div>`}
    </div>` : null}
    <${RowError} k=${"user:" + user.id}/>
  </div>`;
}

// ═════════════════════════ USERS → GROUPS (docs/GROUPS-PLAN.md G11) ═════════════════════════
// The Users screen's two views sit behind a pair of icons (Users · Groups). On the users list the Users icon gives way to a
// Groups filter — the list narrowed to one group's members — so the pair reads [filter][Groups] there and [Users][Groups] on
// the groups grid.
function ModeIcons({ users, force }) {
  const set = m => { usersView.mode = m; force(x => x + 1); };
  const groupsMode = usersView.mode === "groups";
  // Two icons are a pair of tabs; the lone Groups icon beside the filter is a plain button that opens the groups grid.
  const tab = users ? { role: "tab", "aria-selected": groupsMode } : {};
  return html`<div class="pmode pm-icons" role=${users ? "tablist" : null} aria-label=${users ? T("Users or groups") : null}>
    ${users ? html`<button type="button" role="tab" aria-selected=${!groupsMode} class=${"pm-opt pm-ico pm-users" + (groupsMode ? "" : " on")}
      title=${T("Users")} aria-label=${T("Users")} onClick=${() => set("users")}><${Ic} i="user"/></button>` : null}
    <button type="button" ...${tab} class=${"pm-opt pm-ico pm-groups" + (groupsMode ? " on" : "")}
      title=${T("Groups")} aria-label=${T("Groups")} onClick=${() => set("groups")}><${Ic} i="users"/></button>
  </div>`;
}

// The groups grid's column line — the users list's widths, so a group's figures sit above its members' once it is open.
function GroupsHeader({ sort, dir, onSort }) {
  const arrow = c => sort === c ? (dir < 0 ? "↓ " : "↑ ") : "";
  const th = (c, label, cls) => html`<span class=${"clk" + (cls ? " " + cls : "")} onClick=${() => onSort(c)}>${arrow(c)}${label}</span>`;
  return html`<div class="uhead ghead">
    <span></span>${th("name", T("col|Group"))}
    <span class="u-right">${th("members", T("col|Members"), "uh-pc")}${th("peers", T("col|Peers"), "uh-gpeers")}${th("nodes", T("col|Nodes"), "uh-srv")}${th("nets", T("col|Networks"))}${th("rate", T("col|Rate") + " ↓↑", "uh-r uh-rate")}${th("rtotal", trafficRangeLabel() + " ↓↑", "uh-r")}<span></span></span>
  </div>`;
}

// One group: a users-list row of its own (members and how many are online · the nodes their devices are on · networks shared
// with it · its members' rate and ranged traffic added together) that opens onto its members as full user rows, paged like a user's devices.
// While searching, a group found through a MEMBER opens on its own and lists only the members that matched.
function GroupRow({ g, st, q }) {
  const [, force] = useState(0);
  const searching = !!q;
  const nameHit = searching && searchMatch(g.name, q);
  const expanded = searching && !nameHit ? usersView.gexpanded[g.id] !== false : !!usersView.gexpanded[g.id];
  const toggle = () => { usersView.gexpanded[g.id] = !expanded; force(x => x + 1); };
  const shares = groupShares(g.id);   // cached per poll (Store.sharesByGroup) — the count in `st` came from the same list
  const lit = st.online > 0;
  const view = groupMemberViews[g.id] || (groupMemberViews[g.id] = { page: 1, pageSize: 20, sort: "status", dir: -1 });
  let body = null;
  if (expanded) {
    const inGroup = new Set(g.users);
    const all = Store.recon.users.filter(u => inGroup.has(u.id) && (!filtersOn() || memberPasses(u)));
    const members = sortUsers(searching && !nameHit ? all.filter(u => userMatchesQ(u, q)) : all, view.sort, view.dir, "group|" + g.id);
    const totalPages = Math.max(1, Math.ceil(members.length / view.pageSize));
    const page = Math.min(Math.max(1, view.page), totalPages);
    body = html`<div class="urow-body gcard-body">
      ${!g.users.length ? html`<div class="ug-empty">${T("No members yet.")} <button type="button" class="btn btn-ghost btn-mini" onClick=${() => openGroup(g.id)}><${Ic} i="plus"/> ${T("Add members")}</button></div>`
        : html`<${Fragment}>
          <${UsersHeader} sort=${view.sort} dir=${view.dir} onSort=${c => { sortColToggle(view, "sort", "dir", c, USER_DEFDIR); view.page = 1; force(x => x + 1); }}/>
          <div class="urows">${members.slice((page - 1) * view.pageSize, page * view.pageSize).map(u => html`<${UserRow} key=${u.id} user=${u} q=${nameHit ? "" : q} nested=${true} onlineOnly=${usersView.online}/>`)}</div>
          <${RowsPager} total=${members.length} page=${page} pageSize=${view.pageSize} onPage=${p => { view.page = p; force(x => x + 1); }}
            onSize=${v => { view.pageSize = v; view.page = 1; force(x => x + 1); }}/>
        <//>`}
    </div>`;
  }
  return html`<div class=${"urow gcard" + (expanded ? " open" : "")}>
    <div class="urow-head" title=${T("Double-click to edit the group")} onMouseDown=${rowNoSelect} onClick=${e => rowSingle(e, toggle)} onDblClick=${e => rowDouble(e, () => openGroup(g.id))}>
      <span class="u-exp"><${Ic} i="arrow"/></span>
      <span class="u-name"><span class="g-ico"><${Ic} i="users"/></span><span class="un">${g.name}</span></span>
      <span class="u-right">
        <span class="u-counts"><span class="u-pc">${plural(st.members, "cap|Member")}</span>${st.members ? html`<span class="u-dot"> · </span><span class=${"u-onc" + (lit ? " on" : "")}>${T("{n} Online", { n: st.online })}</span>` : null}</span>
        <span class="u-counts g-peers"><span class="u-pc">${plural(st.peers, "cap|Peer")}</span>${st.peers ? html`<span class="u-dot"> · </span><span class=${"u-onc" + (st.peersOn ? " on" : "")}>${T("{n} Online", { n: st.peersOn })}</span>` : null}</span>
        <span class="u-servers">${nodesChip(nodesOfPeers(g.users.flatMap(u => Store.peersByUser(u))))}</span>
        <span class="g-nets" onClick=${e => e.stopPropagation()}>
          <${Popover} hoverOnly cls="grp-pop" popCls="netroute-bub" trigger=${html`<span class=${"grp-n" + (shares.length ? " lit-net" : " zero")}
              aria-label=${T("Devices whose networks are shared with {name}: {n}", { name: g.name, n: shares.length })}><${Ic} i="network"/>${shares.length}</span>`}>
            <span class="netroute-h">${T("Networks shared with this group")}</span>
            ${shares.length ? html`<${CapList} items=${shares} cap=${10} row=${p => html`<div class="netbub-row" key=${p.id}><b>${shareDeviceName(p)}</b> <span class="faint">${(p.routes || []).join(", ")}</span></div>`}/>`
              : html`<div class="netbub-row sub">${T("None yet — share a network from a device's Networks window.")}</div>`}
          <//>
        </span>
        <span class="u-thru">${rateCell(st.rx, st.tx)}</span>
        <span class="u-total"><${TrafficCell} a=${st.traffic} e=${trafficTotals()} ctx=${{ group: true }}/></span>
        <span class="u-acts" onClick=${e => e.stopPropagation()} onDblClick=${e => e.stopPropagation()}>
          <button type="button" class="iconbtn" title=${T("Traffic — graph and members")} aria-label=${T("Traffic — graph and members")} onClick=${() => openGroupView(g.id)}><${Ic} i="bars"/></button>
          <button type="button" class="iconbtn" title=${T("Show this group on the users list")} aria-label=${T("Show this group on the users list")}
            onClick=${() => { usersView.mode = "users"; usersView.group = g.id; usersView.q = ""; usersView.page = 1; bus.emit(); }}><${Ic} i="user"/></button>
          <button type="button" class="iconbtn" title=${T("Edit group")} aria-label=${T("Edit group")} onClick=${() => openGroup(g.id)}><${Ic} i="pencil"/></button>
          <button type="button" class="iconbtn danger" title=${T("Delete group")} aria-label=${T("Delete group")} onClick=${() => confirmDeleteGroup(g, false)}><${Ic} i="trash"/></button>
        </span>
      </span>
    </div>
    ${body}
  </div>`;
}

// Node · interface · Online — the filters the users list and the groups grid share (usersView), so switching views keeps them.
// A user passes when they have a device on that node/interface and, with Online on, one online now; a group passes when any
// member does, and opens on just those members. `reset` is the caller's: its own page goes back to 1.
const memberPasses = u => userOnNodeIface(u, usersView.node, usersView.iface) && (!usersView.online || u.onlineCount > 0);
const filtersOn = () => !!(usersView.node || usersView.iface || usersView.online);
function RosterFilters({ reset }) {
  const allIfaces = Array.from(new Set(Object.keys(Store.describe).flatMap(n => Store.userIfacesOf(n)))).sort();
  const ifaceOpts = usersView.node ? Store.userIfacesOf(usersView.node) : allIfaces;
  if (!ifaceIsAll(usersView.iface) && !ifaceOpts.includes(usersView.iface)) usersView.iface = "";
  return html`<${Fragment}>
    <${Dropdown} className="selwrap" ariaLabel=${T("All nodes")} value=${usersView.node}
      onChange=${v => { usersView.node = v; usersView.iface = ""; reset(); }}
      options=${nodeFilterOptions("")}/>
    <${Dropdown} className="selwrap" ariaLabel=${T("All interfaces")} value=${usersView.iface}
      onChange=${v => { usersView.iface = v; reset(); }}
      options=${ifaceFilterOptions(ifaceOpts, "")}/>
    <button class=${"onlbtn" + (usersView.online ? " on" : "")} aria-pressed=${!!usersView.online} title=${T("Show only users with a device online")}
      onClick=${() => { usersView.online = !usersView.online; reset(); }}>${T("status|Online")}</button>
  <//>`;
}

function GroupsView({ force }) {
  const all = Store.groups();
  const q = usersView.gq.trim().toLowerCase();
  const byId = new Map(Store.recon.users.map(u => [u.id, u]));      // one pass per render, not a search per member
  const hit = g => searchMatch(g.name, q) || g.users.some(u => byId.has(u) && userMatchesQ(byId.get(u), q));
  const filt = filtersOn();
  const passes = g => (!q || hit(g)) && (!filt || g.users.some(u => byId.has(u) && memberPasses(byId.get(u))));
  // A group's figures walk every member's devices: work out only the groups the sort compares (every group for a sort by a
  // figure, none for the name sort) and the page shows — each once per render.
  const stc = new Map();
  const st = g => stc.get(g.id) || (stc.set(g.id, groupStats(g)), stc.get(g.id));
  const list = sortGroups(all, st, usersView.gsort, usersView.gdir).filter(passes);   // freeze over all, then filter
  const pageSize = usersView.gpageSize || 20;
  const totalPages = Math.max(1, Math.ceil(list.length / pageSize));
  const page = Math.min(Math.max(1, usersView.gpage || 1), totalPages);
  const setPage = p => { usersView.gpage = p; force(x => x + 1); };
  return html`<div class="screen">
    <${StoreOffBanner}/>
    <${TrafficRail}/>
    <div class="toolbar">
      <${ModeIcons} users=${true} force=${force}/>
      <${SearchBox} placeholder=${T("Search groups or members…")} value=${usersView.gq} onInput=${e => { usersView.gq = e.target.value; usersView.gpage = 1; force(x => x + 1); }}/>
      <${RosterFilters} reset=${() => { usersView.gpage = 1; force(x => x + 1); }}/>
      <button class="btn btn-primary" onClick=${() => openCreateGroup()}><span class="plus"><${Ic} i="plus"/></span> ${T("New group")}</button>
    </div>
    ${secTitle(T("Groups"), list.length, false)}
    ${!all.length ? html`<div class="empty"><b>${T("No groups yet")}</b>${T("Put people in a group to share a network with all of them at once, from a device's Networks window.")}</div>`
      : !list.length ? html`<div class="empty"><b>${T("Nothing matches")}</b>${filt ? T("Clear the filters.") : T("Clear the search.")}</div>`
      : html`<${Fragment}>
        <${GroupsHeader} sort=${usersView.gsort} dir=${usersView.gdir} onSort=${c => { sortColToggle(usersView, "gsort", "gdir", c, GROUP_DEFDIR); usersView.gpage = 1; force(x => x + 1); }}/>
        <div class="urows">${list.slice((page - 1) * pageSize, page * pageSize).map(g => html`<${GroupRow} key=${g.id} g=${g} st=${st(g)} q=${q}/>`)}</div>
      <//>`}
    <${RowsPager} total=${list.length} page=${page} pageSize=${pageSize} onPage=${setPage}
      onSize=${v => { usersView.gpageSize = v; usersView.gpage = 1; force(x => x + 1); }}/>
  </div>`;
}

export function UsersScreen() {
  useStore();
  const [, force] = useState(0);
  if (usersView.mode === "groups") return html`<${GroupsView} force=${force}/>`;
  const groups = Store.groups();
  if (usersView.group && !Store.group(usersView.group)) usersView.group = "";   // the group was deleted (here or elsewhere)
  const inGroup = usersView.group ? new Set(Store.group(usersView.group).users) : null;
  const q = usersView.q.toLowerCase();
  const allUsers = Store.recon.users;
  // node/iface filter the user LIST (has a peer there); each expanded row still shows ALL of that user's peers
  // freeze the order over the FULL list, then filter — so searching/clearing never reshuffles the frozen rows
  const users = sortUsers(allUsers, usersView.sort, usersView.dir, "users").filter(u => (!inGroup || inGroup.has(u.id)) && userMatchesQ(u, q) && memberPasses(u));
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
    <${TrafficRail}/>
    <div class="toolbar">
      <${Dropdown} className="selwrap grpsel" ariaLabel=${T("Groups")} value=${usersView.group}
        onChange=${v => { usersView.group = v; usersView.page = 1; force(x => x + 1); }}
        options=${[{ value: "", label: T("All groups") }, ...groups.map(g => ({ value: g.id, label: g.name }))]}/>
      <${ModeIcons} users=${false} force=${force}/>
      <${SearchBox} placeholder=${T("Search users, tags, notes, peers…")} value=${usersView.q} onInput=${e => { usersView.q = e.target.value; usersView.page = 1; force(x => x + 1); }}/>
      <${RosterFilters} reset=${() => { usersView.page = 1; force(x => x + 1); }}/>
      <button class="btn btn-primary" onClick=${openCreateUser}><span class="plus"><${Ic} i="plus"/></span> ${T("New user")}</button>
    </div>

    ${secTitle(inGroup ? T("{name} users", { name: Store.group(usersView.group).name }) : T("Total users"), users.length, false)}
    ${!allUsers.length ? html`<div class="empty"><b>${T("No users yet")}</b>${T("Create a user, then add devices for them — or create a peer on the Peers screen and assign it later.")}</div>`
      : !users.length ? html`<div class="empty"><b>${T("Nothing matches")}</b>${inGroup || filtersOn() ? T("Clear the filters.") : T("Clear the search.")}</div>`
      : html`<${Fragment}>
        <${UsersHeader} sort=${usersView.sort} dir=${usersView.dir} onSort=${c => { sortColToggle(usersView, "sort", "dir", c, USER_DEFDIR); usersView.page = 1; force(x => x + 1); }}/>
        <div class="urows">${pageUsers.map(u => html`<${UserRow} key=${u.id} user=${u} q=${q} onlineOnly=${usersView.online}/>`)}</div>
      <//>`}
    <${RowsPager} total=${users.length} page=${page} pageSize=${pageSize} onPage=${setPage}
      onSize=${v => { usersView.pageSize = v; usersView.page = 1; force(x => x + 1); }}/>

    ${unassigned.length ? html`<${Fragment}>
      <div class="section-title"><h2 style="color:var(--faint)">${T("Unassigned peers")}</h2><span class="count">${unassigned.length}</span></div>
      <${EmbeddedPeers} peers=${unassigned} view=${unassignedView} collapse=${true} freezeKey=${"unassigned-embed"}/>
    <//>` : null}
  </div>`;
}

// ═════════════════════════ SCREEN: USER DETAIL ═════════════════════════


// ═════════════════════════ SCREEN: NODES ═════════════════════════
// ═════════════════════════ SCREEN: ACCOUNT ═════════════════════════
