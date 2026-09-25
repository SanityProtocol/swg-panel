/* views.js — the derived row sets the roster screens read: filters, sorts, pagination and reveal.
 *
 * LAYER 3 (see docs/APP-JS-SPLIT-PLAN.md). Imports util / store / model / router / ui.
 *
 * The measured reason this module exists: Peers, Users and Live were reaching into each other for
 * usersView / peersView / connView / searchMatch / sortPeerRows — 63 and 41 references that looked like
 * screen-to-screen coupling and were really a missing layer. They share this, not each other.
 *
 * The view objects are deliberately MODULE-LEVEL mutable state, not component state: search, server and
 * interface filters, the page and the sort must survive a screen unmounting and remounting, and a live
 * poll re-render must not reset them under the operator.
 *
 * stableOrder is the other subtlety. Rows are frozen in their first-seen order per freeze key, so a peer
 * whose status changes mid-poll does not jump the list under the cursor; new rows append. Sorting
 * re-derives the freeze, pagination happens after.
 */

import { tkey, seen, fmtBytes } from "./util.js";
import { lossColor, lossColorMesh } from "./charts.js";
import { Store, api, bus, isCustomKey, customKeyWindow } from "./store.js";
import { ifaceIsAwg, ifaceMatch, ifaceIsAll, nodeStale, tgtXfer, tgtSeenAge,
         isWdttName, isCsqttName, isSelfContainedName } from "./model.js";
import { go } from "./router.js";
import { statusLabel, Popover, Ic, Tag, toast, inProc, setPendingSection } from "./ui.js";
import { subFeatureOn } from "./crypto.js";
import { T, plural, pluralWord, fmtNum, srvText, locale } from "./i18n.js";
import { trafficData, trafficFreezeTag, trafficView, chartsFirstDay } from "./traffic.js";
import { h } from "preact";
import { useState } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// ── DEVICE ACCESS (docs/DEVICE-ACCESS-PLAN.md §10.6) ────────────────────────────────────────────────────────────────────
// Who may OPEN a connection to a device on an interface — judged at the destination, never the source. Absent is "Same
// user and their groups": every interface that predates this was isolated on upgrade (A3). The line under the control is
// the node's own word (snapshot `dev_reach`), never the panel's guess. Lives here because the interface sheets (iface.js)
// and the WDTT/csqtt sheets (turn.js) both render it, and iface.js already imports turn.js.
export const reachOpts = () => [["everyone", T("Everyone on this node")], ["user", T("Same user and their groups")], ["none", T("Nobody")]];
// Why the node left a listed interface out of its table (snapshot `dev_reach.skipped`, §11.2 F2) — the node's own word, so
// "not enforced" is never the panel's guess. Shared with the interface card's chip (screen-nodes.js `reachChip`).
export const reachSkipText = (nname, why) => why === "overlap"
  ? T("Not enforced on {node} — this interface's subnet overlaps another interface's.", { node: nname })
  : why === "no_address" ? T("Not enforced on {node} — the node can't read this interface's address.", { node: nname })
  : why === "not_here" ? T("Not enforced on {node} — the node doesn't run this interface.", { node: nname })
  : T("Not enforced on {node}.", { node: nname });
// A reload the node's nft refused leaves its PREVIOUS table in force (one transaction, §11.2 F3): not open, but not this setting.
export const reachStaleText = (nname, st) => T("Couldn't apply the latest change on {node}: {detail}. The previous rules stay in force.",
  { node: nname, detail: st.detail || st.why || "" });
/** A moment, in the PANEL's language — "17 Sept, 09:20" / "17 сент., 09:20". `undefined` as the locale meant the BROWSER's, so a
 *  Russian panel on an English browser read "Sep 17, 09:20 AM" inside a Russian sentence (1.8.7 qualification PART 3, P3-3). */
export const fmtWhen = s => { try { return new Date(s * 1000).toLocaleString(locale(), { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); } catch (_) { return ""; } };

export function ReachField({ node, iface, value, onChange, create, unvouched, unvouchedRaw }) {
  const label = T("Who can open connections to devices here");
  const snap = node ? (Store.stats[node] || {}) : {};
  const st = snap.dev_reach;
  const nname = node ? Store.nodeName(node) : "";
  const mine = !!(st && (st.ifaces || []).includes(iface));
  const skipped = st && st.skipped ? st.skipped[iface] : null;
  const when = fmtWhen;
  let status = null;
  // Only a node reporting now is believed: a stale snapshot says nothing about what is in force.
  // ⚠️ A promoted interface is ENFORCED though it is set to Everyone, so it gets the same status line as any guarded one —
  // without this it showed none at all: no "packets stopped since", and no way to report a refused or skipped reload.
  const _promoted = value === "everyone" && !create && node && promotedAt(node, iface);
  if (!create && node && (value !== "everyone" || _promoted) && Store.recon.nodeStatus[node] === "live") {
    if (!((snap.net_deps || {}).reach >= 2)) status = html`<div class="notice warn"><${Ic} i="warn"/><span>${T("Not enforced on {node} — it runs an older version. Update it.", { node: nname })}</span></div>`;
    else if (st && st.ok === false && st.stale) status = html`<div class="formmsg err">${reachStaleText(nname, st)}</div>`;
    else if (st && st.ok === false && mine) status = html`<div class="formmsg err">${T("Couldn't apply on {node}: {detail}", { node: nname, detail: st.detail || st.why || "" })}</div>`;
    else if (skipped) status = html`<div class="notice warn"><${Ic} i="warn"/><span>${reachSkipText(nname, skipped)}</span></div>`;
    else if (st && st.ok && mine) status = html`<div class="hint">${T("Packets to devices here stopped since {when}: {n}", { when: when(st.since), n: (st.blocked || {})[iface] || 0 })}</div>`;
    else status = html`<div class="hint">${T("Applies on {node}'s next sync.", { node: nname })}</div>`;
  }
  return html`<div class="field reachfield">
    <label>${label}</label>
    <div class="dpsw netsw-share" role="radiogroup" aria-label=${label}>${reachOpts().map(([m, l]) => html`<button type="button" role="radio"
      aria-checked=${value === m} class=${value === m ? "on" : ""} onClick=${() => onChange(m)}>${l}</button>`)}</div>
    <div class="hint">${value === "everyone" && _promoted
      ? T("Any device on this node can open connections to devices here, except the ones marked Private — only their user's own devices reach those.")
      : value === "everyone"
      ? T("Any device on this node can open connections to devices here. Internet access and networks behind devices are not affected.")
      : value === "none"
      ? T("No other device can open connections to devices here; their own connections still work. Internet access and networks behind devices are not affected.")
      : T("A device here can be reached by its user's other devices on this node and by users who share a group with them. Internet access and networks behind devices are not affected.")}</div>
    ${unvouched && value === "user" ? html`<div class="notice warn"><${Ic} i="warn"/><span>${T("This server build can't prove which user a device belongs to, so no other device can reach any device here.")}</span></div>` : null}
    ${unvouchedRaw && !unvouched && value === "user" ? html`<div class="notice warn"><${Ic} i="warn"/><span>${T("This server build can't prove which user a device connected over RAW belongs to, so no other device can reach those devices.")}</span></div>` : null}
    ${status}
  </div>`;
}

// `group` collapses the grid to ONE row per peer (its primary deployment) with the rest behind a +N —
// the same +N the node/interface filters already produce, but chosen rather than a side effect of
// filtering. A peer on five interfaces is five rows here by design (this is the DEPLOYMENT view); the
// toggle is for when you want the peer list instead.
export const peersView = { node: "", iface: "", q: "", sort: "status", dir: -1, status: null, group: false };
// Peers-screen status filter options (also the deep-link targets from grouped Needs-attention rows).
// The value is the internal status KEY (matched against p.status) and it never moves — persisted filters and
// deep-links point at it. The LABEL comes from statusLabel(), the panel's one status vocabulary, so the
// dropdown can never drift from the badges it filters (that includes the two display remaps: the access-revoke
// key `disabled` shows as Blocked, the DPI fault key `blocked` as Restricted).
export const PEER_STATUS_KEYS = ["", "online", "ready", "unassigned", "disabled", "expired", "expiring", "blocking",
  "restoring", "dangling", "broken", "partial", "blocked", "pending", "unknown"];   // i18n-keys
// ("faulty" is gone from this list: the flat-rx rule that produced it could only fire on a false positive,
//  and the churn detector that replaced it raises "blocked"/Restricted. A filter that can never match is
//  worse than no filter — it reads as "no faulty peers" rather than "this is not measured any more".)
// The one page-size list, and its Dropdown options. Written out four times across three pagers before —
// three in the roster screens and one in the shared grid — which is three chances for them to drift apart.
export const pageSizeOpts = () => [20, 30, 50, 100].map(n => ({ value: n, label: String(n) }));
export const peerStatusFilters = () => PEER_STATUS_KEYS.map(k => ({ value: k, label: k ? statusLabel(k) : T("All statuses") }));
// Prominent warning when the panel keeps no client configs at rest — QRs/downloads then only work
// in the session a peer is created, and existing peers can't be re-shared. Shown on Overview + Peers.

// OPTIONS for an interface dropdown: "All AmneziaWG" / "All WireGuard" shortcuts, then AmneziaWG / WireGuard
// groups of the individual interfaces (used everywhere we list ifaces; the caller renders "All interfaces").
//
// ⚠️ DATA, NOT MARKUP. These three built `<option>`/`<optgroup>` elements while every consumer was a native
// `<select>`. They are the shared `Dropdown` now, which takes `[{value,label}]` with `{group,items}` for a
// heading — so the helpers return that and there is ONE shape, rather than a markup twin per data twin.
// Type groups only matter when BOTH kinds are present — with one kind we list the interfaces flat (a group header
// or "All <type>" would just duplicate "All interfaces"). "All AmneziaWG" / "All WireGuard" appear only when both
// kinds exist AND there's more than one of that kind (otherwise they'd equal "All interfaces" or the lone iface).
export function ifaceOptGroups(names) {
  // Grouped by what each interface IS (scKindByName asks the fleet), not by what it is called — an adopted or
  // operator-named turn instance used to match no pattern and land in the WireGuard group.
  const wdtt = names.filter(isWdttName);
  const csqtt = names.filter(isCsqttName);
  const awg = names.filter(n => !isSelfContainedName(n) && ifaceIsAwg(n));
  const wg = names.filter(n => !isSelfContainedName(n) && !ifaceIsAwg(n));
  const groups = [["*awg", "AmneziaWG", awg], ["*wg", "WireGuard", wg], ["*wdtt", "WDTT", wdtt], ["*csqtt", "CSQTT", csqtt]].filter(g => g[2].length);
  if (groups.length < 2) return names.map(i => ({ value: i, label: i }));   // one kind → flat list (an "All <type>" would just duplicate "All interfaces")
  // "All <type>" shortcut per kind (only when that kind has >1 — else it equals the lone iface), then a group per kind.
  return [...groups.filter(([, , arr]) => arr.length > 1).map(([val, label]) => ({ value: val, label: T("All {v1}", { v1: label }) })),
          ...groups.map(([, label, arr]) => ({ group: label, items: arr.map(i => ({ value: i, label: i })) }))];
}
// Shared node / interface FILTER <option> lists so the Peers / Users / Live toolbars behave identically:
//   0 available → a single "No nodes/interfaces" item · exactly 1 → that one (labelled, value=allVal so the list
//   stays unfiltered and it reads pre-selected) · ≥2 → "All nodes/interfaces" + each. `allVal` is the caller's
//   "all" sentinel ("" or "*").
export function nodeFilterOptions(allVal) {
  const ns = Store.nodes || [];
  if (!ns.length) return [{ value: allVal, label: T("No nodes") }];
  if (ns.length === 1) return [{ value: allVal, label: ns[0].name }];
  return [{ value: allVal, label: T("All nodes") }, ...ns.map(n => ({ value: n.id, label: n.name }))];
}
export function ifaceFilterOptions(names, allVal) {
  if (!names.length) return [{ value: allVal, label: T("No interfaces") }];
  if (names.length === 1) return [{ value: allVal, label: names[0] }];
  return [{ value: allVal, label: T("All interfaces") }, ...ifaceOptGroups(names)];
}

// column sort keys for the shared peer grid — every header is clickable (order-by). Callers hold sort/dir in
// their view-state and sort BEFORE pagination via sortPeerRows(); PeerGrid renders the clickable headers.
const _ipKey = ip => String(ip || "").split(/[./]/).map(n => String((+n) || 0).padStart(3, "0")).join(".");
// status order for the clickable "Status" column — online FIRST (STATUS_RANK ranks ready above online, which is
// right for the Peers-screen default grouping but backwards for an order-by; here online is the top of the sort).
export const PEER_STATUS_RANK = { online: 10, faulty: 9, ready: 8, expiring: 8, blocked: 7, partial: 6, pending: 5, creating: 5, rotating: 5, restoring: 4, unassigned: 3, unknown: 2, dangling: 1, broken: 1, blocking: 0, disabled: 0, expired: 0 };
export const PEER_SORT = {
  status: ({ p, t }) => PEER_STATUS_RANK[t.status || p.status] || 0,
  server: ({ t }) => Store.nodeName(t.node).toLowerCase() + "|" + t.iface,
  user: ({ p }) => { const u = p.user_id ? Store.user(p.user_id) : null; return u ? u.name.toLowerCase() : "￿"; },
  title: ({ p }) => String(p.title || p.name || "").toLowerCase(),
  address: ({ t }) => _ipKey(t.ip),
  endpoint: ({ t }) => ((t.observed && t.observed.endpoint) || "￿").toLowerCase(),
  online: ({ t }) => { const a = tgtSeenAge(t); return a != null ? a : Infinity; },
  rate: ({ t }) => { const x = tgtXfer(t); return x ? (x.rx_speed || 0) + (x.tx_speed || 0) : 0; },
  total: ({ t }) => { const x = tgtXfer(t); return x ? (x.rx_bytes || 0) + (x.tx_bytes || 0) : 0; },
  // The ranged total (traffic.js): the whole device, or — in a user's own list (`o`, its owner) — what it carried while it
  // was that user's. A Map lookup per comparison, never a walk.
  rtotal: ({ p, o }) => { const a = peerTraffic(p.id, o); return a ? a.rx + a.tx : 0; },
};
export const PEER_DEFDIR = { status: -1, rate: -1, total: -1, rtotal: -1, online: 1, title: 1, user: 1, server: 1, address: 1, endpoint: 1 };   // first-click direction per column
// ── ranged totals (traffic.js) ──────────────────────────────────────────────────────────────────────────────
// A peer's total in the window: the whole device, or with `owner` what it carried while it was that user's.
export function peerTraffic(pid, owner) {
  const d = trafficData();
  return d ? (owner ? d.slot.get(owner + "|" + pid) : d.peer.get(pid)) || null : null;
}
export function userTraffic(uid) { const d = trafficData(); return d ? d.user.get(uid) || null : null; }
// ⚠️ stableOrder freezes a known row's slot, so a sort by ranged total that rendered before the totals landed would keep
// its all-zero order for good. The freeze key carries the window and whether its totals are in — and nothing that moves
// every minute, or the rows would reshuffle each time "until now" refreshes.
const rtotalTag = sort => sort === "rtotal" ? "|" + trafficFreezeTag() : "";
// The column's name is the window's: "This month", "Last 30 days", or the custom dates (month names through Intl).
export function trafficRangeLabel(v) {
  v = v || trafficView;
  if (v.range === "30d") return T("Last 30 days");
  if (v.range === "custom" && v.from && v.to) {
    const f = d => { try { return new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(d + "T00:00:00Z")); } catch (_) { return d; } };
    return v.from === v.to ? f(v.from) : f(v.from) + " – " + f(v.to);
  }
  return T("This month");
}
// ── order freeze ─────────────────────────────────────────────────────────────────────────────────
// Keep rows where they are WHILE you look at them: editing a record (rename, status flip) must not make its
// row jump or leave the page. The sorted order is snapshotted per (list, sort, dir); a known row holds its
// slot even if its sort key changes. The order is recomputed only when you change the sort (a new key) or
// reload the page (this module var resets). New/removed rows fold into the snapshot so they stay put too.
const _orderFreeze = {};   // freezeKey -> [ids] in frozen order
export function stableOrder(freezeKey, items, idOf, cmp) {
  const frozen = _orderFreeze[freezeKey];
  if (!frozen) { const s = items.slice().sort(cmp); _orderFreeze[freezeKey] = s.map(idOf); return s; }
  const pos = new Map(frozen.map((id, i) => [id, i]));
  const s = items.slice().sort((a, b) => {
    const ai = pos.has(idOf(a)) ? pos.get(idOf(a)) : Infinity;   // known rows keep their frozen slot
    const bi = pos.has(idOf(b)) ? pos.get(idOf(b)) : Infinity;   // new rows sort live, after the known ones
    return ai !== bi ? ai - bi : cmp(a, b);
  });
  if (items.length !== frozen.length || items.some(it => !pos.has(idOf(it)))) _orderFreeze[freezeKey] = s.map(idOf);
  return s;
}
export function sortPeerRows(rows, sort, dir, freeze) {
  const key = PEER_SORT[sort] || PEER_SORT.status;
  const cmp = (a, b) => ((x, y) => x < y ? -1 : x > y ? 1 : 0)(key(a), key(b)) * (dir || -1)
    || String(a.p.title || a.p.name || "").localeCompare(String(b.p.title || b.p.name || ""));
  const s = freeze ? stableOrder(freeze + "|" + sort + "|" + dir + rtotalTag(sort), rows, r => r.p.id + "|" + tkey(r.t.node, r.t.iface), cmp)
    : rows.slice().sort(cmp);
  return pinRecentlyCreated(s, r => r.p.id);   // a just-created peer stays on TOP regardless of sort/freeze
}
// Keep just-created rows at the TOP of a grid, newest first, regardless of the active sort — so a peer/user you
// just made isn't buried. Session-scoped (Store.recentlyCreated resets on reload). Stable: existing rows keep order.
export function pinRecentlyCreated(sorted, idOf) {
  const rc = Store.recentlyCreated;
  if (!rc || !sorted.some(x => rc[idOf(x)])) return sorted;
  const pin = [], rest = [];
  for (const x of sorted) (rc[idOf(x)] ? pin : rest).push(x);
  pin.sort((a, b) => (rc[idOf(b)] || 0) - (rc[idOf(a)] || 0));   // newest-created first
  return pin.concat(rest);
}
export function peerSortBy(view, col) { if (view.sort === col) view.dir = -view.dir; else { view.sort = col; view.dir = PEER_DEFDIR[col] || 1; } }
// Pager scroll: turning to the NEXT page brings the grid's TOP just under the sticky header; PREV brings its BOTTOM
// into view — so a page turn always lands you at the fresh edge of the list. `e` targets the clicked pager button;
// the grid is the element right before the .pager. Deferred two frames so the new page has rendered/re-sized.
export function pageScroll(e, dir) {
  const pager = e.currentTarget && e.currentTarget.closest(".pager");
  const grid = pager && pager.previousElementSibling;
  if (!grid) return;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const r = grid.getBoundingClientRect();
    // Next → land the grid top well below the toolbar (scroll a bit further up); Prev → keep the grid bottom
    // clear of the pager/viewport edge (scroll a bit further down). Extra margin = more context on either side.
    const y = dir > 0 ? window.scrollY + r.top - 120 : window.scrollY + r.bottom - window.innerHeight + 64;
    window.scrollTo({ top: Math.max(0, y), behavior: "smooth" });
  }));
}

export const connView = { mode: "peers", node: "", iface: "", q: "", online: true, page: 1, pageSize: 20, sort: "status", dir: -1, usort: "status", udir: -1 };   // Online filter ON by default → the Live view leads with what's connected now

// Independent view-state per grid so search / server / interface / page never bleed across them.
export const usersView = { q: "", node: "", iface: "", page: 1, pageSize: 20, sort: "status", dir: -1, expanded: {},   // node/iface filter the LIST (expand shows all peers)
  mode: "users", gq: "", gpage: 1, gpageSize: 20 };   // the Users | Groups switch, and the groups list's own search and page
export const unassignedView = { node: "", iface: "", q: "", page: 1, pageSize: 20, sort: "status", dir: -1 };
export const userPeerViews = {};   // uid -> its own { node, iface, q, page, pageSize, sort, dir } for the expanded grid

// User-row status: a BARE tag (dot + uppercase mono label), same style as the node "reporting/offline"
// status, just smaller — not the pill Badge used inside the grids.
export function userStatTag(user, live) {
  // Live monitor: a user is simply online (has an online peer, green) or offline (grey) — no ready/partial/etc.
  if (live) { const on = user.onlineCount > 0; return html`<span class=${"ustat s-" + (on ? "online" : "off")}>${on ? T("status|Online") : T("Offline")}</span>`; }
  const s = user.peerCount ? user.status : "empty";
  return html`<span class=${"ustat s-" + s}>${s === "empty" ? T("No peers") : statusLabel(s)}</span>`;
}
// Combined live stats across ALL of a user's peers/targets — for the user row's rate/total/last columns.
export function userStats(uid) {
  let rx = 0, tx = 0, rxb = 0, txb = 0, last = null;
  for (const p of Store.peersOfUser(uid)) for (const t of p.targets) {
    const o = tgtXfer(t); if (!o) continue;
    rx += o.rx_speed || 0; tx += o.tx_speed || 0; rxb += o.rx_bytes || 0; txb += o.tx_bytes || 0;
    if (o.handshake_age != null) last = (last == null) ? o.handshake_age : Math.min(last, o.handshake_age);
  }
  return { rx, tx, rxb, txb, last };
}
// Multi-term search: split the query on whitespace and require EVERY term to appear somewhere in the (single,
// combined) haystack — AND across terms, so "ada awg1" matches a peer whose USER is Ada and whose INTERFACE is
// awg1 even though the two terms live in different fields. Empty query matches everything. Callers pass ONE
// haystack that concatenates all searchable fields, so terms are free to match across them.
export function searchMatch(hay, q) {
  if (!q) return true;
  hay = String(hay).toLowerCase();
  return String(q).toLowerCase().split(/\s+/).filter(Boolean).every(t => hay.includes(t));
}
// Global Users-search match: a peer's title/name/key/address/server/interface (one combined haystack).
export function peerMatchesQ(p, q) {
  if (!q) return true;
  const hay = (p.title || "") + " " + (p.name || "") + " " + (p.pubkey || "") + " "
    + p.targets.map(t => (t.ip || "") + " " + Store.nodeName(t.node) + " " + t.iface).join(" ");
  return searchMatch(hay, q);
}
// does the user's OWN identity (name/tag/note) match? — distinct from a match via one of their peers.
export function userIdentityMatchesQ(u, q) { return searchMatch((u.name || "") + " " + (u.tag || "") + " " + (u.note || ""), q); }
// A user matches if their identity OR any of their peers match — so you can find a user by a peer's IP.
export function userMatchesQ(u, q) {
  if (!q) return true;
  if (userIdentityMatchesQ(u, q)) return true;
  return Store.peersOfUser(u.id).some(p => peerMatchesQ(p, q));
}
// does the user have a peer deployed on this node (and interface, if given)? — for the Users node/iface filter.
// The user LIST is filtered by this; the expanded grid still shows ALL of the user's peers.
export function userOnNodeIface(u, node, iface) {
  const anyIface = !iface || iface === "*";   // *awg / *wg still filter (by type) — only ""/"*" mean "all interfaces"
  if (!node && anyIface) return true;
  return Store.peersOfUser(u.id).some(p => p.targets.some(t => (!node || node === "*" || t.node === node) && ifaceMatch(t.iface, iface, t)));
}
// User-list sorting (clickable header). Callers hold sort/dir in their view-state under caller-chosen keys.
export const USER_SORT = {
  status: u => PEER_STATUS_RANK[u.status] || 0, name: u => (u.name || "").toLowerCase(),
  peers: u => u.peerCount || 0, online: u => u.onlineCount || 0,
  last: u => { const s = userStats(u.id); return s.last == null ? Infinity : s.last; },
  rate: u => { const s = userStats(u.id); return s.rx + s.tx; },
  total: u => { const s = userStats(u.id); return s.rxb + s.txb; },
  rtotal: u => { const a = userTraffic(u.id); return a ? a.rx + a.tx : 0; },   // every slot the user held, in the window
  // by node count first, then the total distinct interfaces across those nodes (encoded: nodes×10000 + ifaces)
  nodes: u => { const nm = {}; let ifs = 0; for (const p of Store.peersOfUser(u.id)) for (const t of p.targets) { const s = nm[t.node] = nm[t.node] || new Set(); if (!s.has(t.iface)) { s.add(t.iface); ifs++; } } return Object.keys(nm).length * 10000 + ifs; },
};
export const USER_DEFDIR = { status: -1, peers: -1, online: -1, last: 1, rate: -1, total: -1, rtotal: -1, name: 1, nodes: -1 };
export function sortUsers(users, sort, dir, freeze) {
  const key = USER_SORT[sort] || USER_SORT.status;
  const cmp = (a, b) => ((x, y) => x < y ? -1 : x > y ? 1 : 0)(key(a), key(b)) * (dir || -1) || String(a.name).localeCompare(String(b.name));
  const s = freeze ? stableOrder(freeze + "|" + sort + "|" + dir + rtotalTag(sort), users, u => u.id, cmp) : users.slice().sort(cmp);
  return pinRecentlyCreated(s, u => u.id);   // a just-created user stays on TOP regardless of sort/freeze
}
export function sortColToggle(view, sk, dk, col, defdir) { if (view[sk] === col) view[dk] = -view[dk]; else { view[sk] = col; view[dk] = defdir[col] || 1; } }

// which Users page a user lands on (mirrors UsersScreen's sort; search is cleared before we navigate)
export function userPageOf(uid) {
  const users = sortUsers(Store.recon.users, usersView.sort, usersView.dir);
  const idx = users.findIndex(u => u.id === uid);
  return idx < 0 ? 1 : Math.floor(idx / (usersView.pageSize || 20)) + 1;
}
// USER GROUPS (docs/GROUPS-PLAN.md G11). The devices whose networks are shared with a group — what adding someone grants, and what
// removing someone or deleting the group takes away — from the roster the poll already holds, never a request.
// ⚠️ A PRIVATE device grants a group NOTHING, whatever its stored share still says. Marking a device private does not clear
// the share (and should not — turning the flag off has to give it back), so the grant sits in the roster while share_grants
// hands the group nobody. Without this test the Groups screen counted it, its bubble named the device and its prefixes, and
// two DESTRUCTIVE confirms — removing a member, deleting the group — warned about losing networks nobody ever reached.
export function groupShares(gid) {
  return Store.recon.peers.filter(p => !p.private && (p.routes || []).length && p.share && p.share.groups && typeof p.share.groups === "object"
    && Object.prototype.hasOwnProperty.call(p.share.groups, gid));
}
// A device as a sentence names it: its title, else its owner's name.
export const shareDeviceName = p => p.title || (p.user_id && Store.user(p.user_id) ? Store.user(p.user_id).name : T("Untitled"));
// A device as a LIST names it: its title, else where it is — its address, else the interface it sits on. `shareDeviceName` falls
// back to the OWNER's name, which reads as the person rather than the device the moment a device is untitled.
export function deviceLabel(peer) {
  if (!peer) return T("Untitled");
  if (peer.title) return peer.title;
  const t = (peer.targets || []).find(x => x && (x.ip || x.iface));
  const where = t ? (t.ip ? String(t.ip).split("/")[0] : t.iface) : "";
  return where || T("Untitled");
}
export const peerOnline = p => !!(p && (p.targets || []).some(t => t && t.online));
// "Title (address)" — or just the address when the device has no title, because `deviceLabel` already falls back to it and
// "10.8.0.3 (10.8.0.3)" is what that produced. `node` picks the address it answers on there, since a device may be deployed
// to several and the row is about one of them.
export function deviceNameAt(peer, node) {
  const nm = deviceLabel(peer);
  const t = (peer && (peer.targets || []).find(x => x && (!node || x.node === node) && x.ip)) || null;
  const ip = t && t.ip ? String(t.ip).split("/")[0] : "";
  return ip && nm !== ip ? nm + " (" + ip + ")" : nm;
}
// SOMEBODY ELSE'S device is named by its OWNER, not by its title: "whose is it" is the actionable fact when the network is
// theirs and you want it changed — the title belongs to a device you cannot see or edit. Falls back to the device's own name
// for an unassigned peer, which has no owner to name.
export function ownerNameAt(peer, node) {
  const u = peer && peer.user_id ? Store.user(peer.user_id) : null;
  if (!u) return deviceNameAt(peer, node);
  const t = (peer.targets || []).find(x => x && (!node || x.node === node) && x.ip) || null;
  const ip = t && t.ip ? String(t.ip).split("/")[0] : "";
  return ip ? u.name + " (" + ip + ")" : u.name;
}

// ── DEVICE ACCESS on a user's line (docs/DEVICE-ACCESS-PLAN.md §10) ──────────────────────────────────────────────────────────
// The level in force on ONE deployment's interface, as the panel publishes it (absent = "user", A3).
// Where a private device is NOT protected, and why — [{node, why: "old"}] once per node too old or not reporting now, and
// [{node, iface, why}] for an interface at Everyone where the node has no address to guard it by. The switch promises "not
// everyone on the node, whatever the interface allows"; where that is not kept, saying so is the rule this file already
// states for sharing: claiming isolation a box does not have is the one answer worse than no answer.
// ⚠️ On an interface at Everyone the node guards a private device BY ITS ADDRESS and passes the rest of the subnet (that is
// what keeps everyone else's reach), so a device the panel cannot place has nothing guarding it: no user (dev_reach_promotes
// skips it) or a keyless build that can't prove which address a device has (A7). At "user" the same two are Nobody instead,
// which keeps the promise.
export function privateUnenforced(peer) {
  if (!peer || peer.disabled || peer.expired) return [];
  const out = [], seen = new Set();
  for (const t of (peer.targets || [])) {
    if (!t || !t.node) continue;
    if (!nodeEnforces(t.node)) {
      if (!seen.has(t.node)) { seen.add(t.node); out.push({ node: t.node, why: "old" }); }
    } else if (ifaceLevelOf(t) === "everyone" && (!Store.user(peer.user_id) || unvouchedTarget(t))) {
      out.push({ node: t.node, iface: t.iface, why: Store.user(peer.user_id) ? "unvouched" : "no_user" });
    }
  }
  return out;
}
// What turning Private OFF opens — in the TWO halves the node enforces separately. The device's own address follows its
// interface's level; the networks behind it follow its share. ⚠️ The sheet used to read the share alone: measured on msk-main
// (1.8.7 qualification D5), a private gateway on an Everyone interface, shared with one user, said "opens again to n-erin" —
// and on save carol's device reached the gateway itself too, as everyone on the node did. With no share on a "user"
// interface it said "everyone on the node reaches it", which the device's own address was not.
export function privateOffOpens(peer) {
  const p = { ...(peer || {}), private: false };
  const everyoneAt = [...new Set((p.targets || []).filter(t => t && t.node && targetOpen(t) === "everyone").map(t => t.node))];
  return { everyoneAt, nets: (p.routes || []).length ? peerAudience(p) : null };
}
const ifaceLevelOf = t => {
  const nr = (Store.nodes || []).find(x => x.id === t.node) || {};
  const c = (nr.wdtt_cfg || {})[t.iface] || (nr.csqtt_cfg || {})[t.iface];
  return (c ? c.reach : (Store.ifaceMeta(t.node, t.iface) || {}).reach) || "user";
};
// ⚠️ A node below `reach: 2`, or one not reporting now, ENFORCES NOTHING — so everything on it reaches everything, and that is
// what this says. Claiming isolation a box does not have is the one answer worse than no answer.
const nodeEnforces = nid => ((Store.stats[nid] || {}).net_deps || {}).reach >= 2 && Store.recon.nodeStatus[nid] === "live";
// A7: an instance whose REPORTED build cannot prove who owns a device acts as Nobody; one that proves only its WireGuard path
// does so for the devices on its RAW TUN — the node names the INSTANCE, so its RAW tun is found through the node's wdtt_cfg.
const unvouchedTarget = t => {
  const nr = (Store.nodes || []).find(x => x.id === t.node) || {};
  if ((nr.reach_unvouched || []).includes(t.iface)) return true;
  return (nr.reach_unvouched_raw || []).some(ifn => ((nr.wdtt_cfg || {})[ifn] || {}).raw_iface === t.iface);
};
// PROMOTED: an interface set to Everyone with a private device on it, so the node has a table for it — it guards the private
// devices by address and passes everything else. The PANEL decides which (it builds the table) and publishes it per node;
// this reads that verdict rather than deriving a second one. It changes nobody's reach but the private devices' — it is what
// lets the interface's status line report a refused or skipped reload there.
export const promotedAt = (node, iface) =>
  (((Store.nodes || []).find(x => x.id === node) || {}).reach_promoted || []).includes(iface);
// Which devices caused it — display only. The verdict above is the panel's; this only names the devices that match it.
export const promotedBy = (node, iface) => (Store.recon.peers || []).filter(p => p.private && !p.disabled && !p.expired
  && Store.user(p.user_id) && (p.targets || []).some(t => t && t.node === node && t.iface === iface));
// The level IN FORCE on a deployment for everyone but a private device (userReach excludes those per device). A promoted
// interface stays Everyone: the node passes everything there but the private devices.
// ⚠️ An unvouched build is Nobody only at "user" (A7) — at Everyone nothing guards it, and reading it as Nobody there told a
// viewer that devices everybody on the node reaches could not be reached.
const targetOpen = t => {
  if (!nodeEnforces(t.node)) return "everyone";
  const lv = ifaceLevelOf(t);
  return lv === "user" && unvouchedTarget(t) ? "none" : lv;
};

// Who every user's devices can open connections to — ONE pass per poll, because a list asks it per row. Judged AT THE
// DESTINATION and per node (§10.2): a device is reachable when it sits on a node this user also has a device on, and that
// interface allows it — Everyone to anyone there, Nobody to nobody, "user" to the same person and whoever shares a group with
// them. Cross-node reach is never claimed: it does not exist (§12). Blocked and expired are off the node, so neither reaches
// nor is reached.
let _reachOf = null, _reachIdx = null;
function reachIndex() {
  if (_reachOf === Store.recon && _reachIdx) return _reachIdx;
  const open = new Map(), lvl = new Map(), here = new Map();
  const put = (m, k, v) => (m.get(k) || m.set(k, new Set()).get(k)).add(v);
  for (const p of Store.recon.peers) {
    const u = p.user_id ? Store.user(p.user_id) : null;
    if (!u || p.unassigned || p.disabled || p.expired || u.disabled) continue;
    for (const t of p.targets || []) {
      if (!t || !t.node) continue;
      put(here, t.node, p.user_id);
      const lv = targetOpen(t);
      if (lv === "everyone") put(open, t.node, p.user_id);
      else if (lv === "user") put(lvl, t.node, p.user_id);
    }
  }
  const out = new Map();
  const add = (uid, other) => { if (other !== uid) put(out, uid, other); };
  for (const [nid, users] of here) {
    for (const uid of users) for (const o of open.get(nid) || []) add(uid, o);
    // "user": every member of a group reaches every other member's devices there — walked per GROUP, never per pair of people
    const atUser = lvl.get(nid) || new Set();
    for (const g of Store.groups()) {
      const mates = g.users.filter(x => users.has(x));
      if (mates.length < 2) continue;
      for (const a of mates) for (const b of mates) if (atUser.has(b)) add(a, b);
    }
  }
  _reachOf = Store.recon; _reachIdx = out;
  return out;
}
export const reachOwners = uid => reachIndex().get(uid) || new Set();

// The devices of ONE person that the other members of a group can open connections to — the group sheet's per-member number
// and its bubble. Same test the reach index applies at the destination: a live device (not blocked, expired, unassigned, of a
// blocked user), not Private where its node enforces Private, on a deployment at Everyone or at "Same user and their groups".
// A device at Nobody, or Private, is not reachable by the group whatever the membership — counting every device ("tester · 8
// devices") promised access the membership does not give (operator, 2026-09-17). Online first, then by name.
export function reachableByGroup(uid) {
  const u = Store.user(uid);
  if (!u || u.disabled) return [];
  const out = [];
  for (const p of Store.peersByUser(uid)) {
    if (p.disabled || p.expired || p.unassigned) continue;
    const t = (p.targets || []).find(x => x && x.node && !(p.private && nodeEnforces(x.node))
      && (targetOpen(x) === "everyone" || targetOpen(x) === "user"));
    if (t) out.push({ peer: p, node: t.node, online: (p.targets || []).some(x => x && x.online) });
  }
  return out.sort((a, b) => (b.online ? 1 : 0) - (a.online ? 1 : 0) || deviceLabel(a.peer).localeCompare(deviceLabel(b.peer)));
}

// The same answer in detail, for the bubble: each person they reach and which of that person's devices, online first. Computed
// when the bubble opens, not per row.
// ⚠️ MEMOISED PER POLL, because the chip beside every name now asks for it too — it counts devices, and a device count
// cannot come from `reachIndex` (which knows who, not how many). Without this the list would walk every reachable owner's
// peers per row per poll. Only the uids actually asked about are computed: the rows on screen, and whichever bubble is open.
let _urOf = null, _urCache = new Map();
export function userReach(uid) {
  if (_urOf !== Store.recon) { _urOf = Store.recon; _urCache = new Map(); }
  const hit = _urCache.get(uid);
  if (hit) return hit;
  const mates = new Set(Store.groupsByUser(uid).flatMap(g => g.users));
  const myNodes = new Set();
  // ⚠️ THE SAME FILTER reachIndex applies (a blocked, expired or unassigned device is off the node and is not presence).
  // Without it a blocked device of this user's made its node count as somewhere they are, and every destination there was
  // listed as reachable — a standing wrong answer for as long as that device existed.
  for (const p of Store.peersByUser(uid)) {
    if (p.disabled || p.expired || p.unassigned) continue;
    for (const t of p.targets || []) if (t && t.node) myNodes.add(t.node);
  }
  const allows = (t, owner) => {
    if (!t || !t.node || !myNodes.has(t.node)) return false;
    const lv = targetOpen(t);
    return lv === "everyone" || (lv === "user" && mates.has(owner));
  };
  const rows = [];
  for (const other of reachOwners(uid)) {
    const u = Store.user(other);
    if (!u) continue;
    const devices = [];
    for (const p of Store.peersByUser(other)) {
      if (p.disabled || p.expired) continue;
      // The deployment that ALLOWS it names the row: its address and its node. A device reachable on two shared nodes is
      // still one device — it is listed once, at the first deployment that lets this user in.
      // ⚠️ Every device in this loop belongs to SOMEBODY ELSE (reachOwners never returns the viewer), so a private one is
      // not reachable — but only WHERE THE NODE ENFORCES IT. Private was applied before targetOpen() was consulted, so on a
      // node too old to restrict, or one not reporting, the bubble reported a device as reached by nobody while everything
      // on that subnet still reached it: claiming an isolation the box does not have, which is the one answer this file
      // says is worse than none. The panel plans the node's table the same way, so the two cannot disagree.
      const t = (p.targets || []).find(x => allows(x, other) && !(p.private && nodeEnforces(x.node)));
      if (!t) continue;
      devices.push({ peer: p, online: !!t.online, node: t.node, ip: t.ip ? String(t.ip).split("/")[0] : "" });
    }
    devices.sort((a, b) => (b.online ? 1 : 0) - (a.online ? 1 : 0) || deviceLabel(a.peer).localeCompare(deviceLabel(b.peer)));
    if (devices.length) rows.push({ user: u, devices, online: devices.filter(d => d.online).length });
  }
  const out = rows.sort((a, b) => (b.online ? 1 : 0) - (a.online ? 1 : 0)
    || String(a.user.name).localeCompare(String(b.user.name)));
  _urCache.set(uid, out);
  return out;
}
// ── ONE RULE FOR EVERYTHING THIS FILE ASKS THE PANEL ─────────────────────────────────────────────────────────────────────────
// The reach bubble, the networks bubble and the chip's count all ask `/api/users|peers/networks`, which §4.10 forbids running
// for every user on every poll. They used to cache their answers three different ways — two on a 60 s clock, one on an input
// signature — so a bubble could show minute-old rows beside a chip that was current. One rule now:
//
//   SIGNATURE   what the answer actually depends on — which devices carry which networks, who they are shared with, group
//               membership, where each device is deployed, whether a node can restrict, and whether node LANs count at all.
//               A clock was always the wrong question: traffic counters tick constantly and change none of this.
//   BACKSTOP    ⚠️ and yet not signature alone. The browser cannot see a node PICKING UP a route (`net_carried` lands in a
//               snapshot, not the roster), so a pure signature would hold a stale answer for as long as nothing else moved.
//               Five minutes, which is far too long to flicker and far too short to be wrong for a shift.
const ASK_TTL = 300000;
let SIG = "", SIG_KEY = null;
export function askSig() {
  if (SIG_KEY === Store.recon) return SIG;
  const parts = [];
  for (const p of (Store.recon && Store.recon.peers) || []) {
    const tg = (p.targets || []).map(t => t.node + "/" + t.iface).join(",");
    // ⚠️ `dead` on BOTH branches. node_networks drops a blocked or expired provider outright, so blocking the device that
    // fronts a network changes every grantee's answer — and the signature has to see it, or the old count stands until the
    // backstop expires. It was on the non-carrying branch only, which is the branch that matters least.
    // ⚠️ `private` IS IN HERE, on both branches, for the same reason `dead` is. It is the FIRST thing share_grants reads,
    // so flipping it changes every grantee's answer — and without it in the signature the networks chip and both bubbles
    // served the pre-Private answer until the 5-minute backstop expired. Turning it OFF withheld the network just as long.
    const dead = (p.disabled ? 1 : 0) + (p.expired ? 2 : 0) + (p.userDisabled ? 4 : 0) + (p.private ? 8 : 0);
    if ((p.routes || []).length) parts.push("R" + p.id + ":" + (p.routes || []).join("|") + ":" + JSON.stringify(p.share || null) + ":" + tg + ":" + dead);
    else parts.push("P" + p.id + ":" + (p.user_id || "") + ":" + tg + ":" + dead);
  }
  for (const g of (Store.groups ? Store.groups() : [])) parts.push("G" + g.id + ":" + (g.users || []).join("|"));
  // `net_capable` is in here because it is what decides whether a node can restrict a network at all — the audience bubble
  // reads that verdict, so a node being updated has to invalidate the answer.
  for (const n of (Store.nodes || [])) parts.push("N" + n.id + ":" + (n.lan_share === false ? 0 : 1) + ":" + ((n.lans || []).length) + ":" + (n.net_capable ? 1 : 0));
  parts.push("S" + ((Store.panelSettings || {}).show_node_lans === false ? 0 : 1));
  SIG_KEY = Store.recon; SIG = parts.join(";");
  return SIG;
}
export const askFresh = e => !!(e && e.sig === askSig() && Date.now() - e.at < ASK_TTL);

// ── WHO REACHES THE NETWORKS BEHIND ONE DEVICE (docs/NETWORKS-PLAN.md §18) ───────────────────────────────────────────────────
// ⚠️ SHARING IS PER DEVICE, NOT PER NETWORK — `share_grants` takes the peer — so one audience covers every network behind it.
// The names, dates and device counts are roster facts and are read here; whether a NODE can enforce the restriction is not, and
// is fetched (`peerAudFetch`) rather than guessed: a node too old to restrict carries a restricted network for NOBODY, so a
// bubble that named its grantees without saying so would be confidently wrong.
export function peerAudience(peer) {
  const sh = peer && peer.share && typeof peer.share === "object" ? peer.share : null;
  const owner = peer && peer.user_id ? Store.user(peer.user_id) : null;
  const nodes = [...new Set((peer.targets || []).map(t => t && t.node).filter(Boolean))];
  // ⚠️ PRIVATE OUTRANKS EVERY SHARE, exactly as `share_grants` decides it on the panel: the owner alone, no grantee and
  // no group, and not "everyone on the node" either — which is what an absent share would otherwise mean.
  if (peer && peer.private) return { mode: "owner", nodes, owner, users: [], groups: [], private: true };
  const now = Math.floor(Date.now() / 1000);
  const live = u => typeof u === "number" && u >= 0 && (!u || u > now);
  // "Devices here" means on a node this device is deployed to — a grantee whose devices are all elsewhere reaches nothing,
  // because reach is judged per node (§12). A global device count would overstate what the grant actually gives them.
  const here = uid => Store.peersByUser(uid).filter(q => !q.disabled && !q.expired
    && (q.targets || []).some(t => t && nodes.includes(t.node))).length;
  if (!sh) return { mode: "everyone", nodes, owner, users: [], groups: [] };
  const users = [], groups = [];
  for (const [uid, until] of Object.entries(sh.users || {})) {
    const u = live(until) ? Store.user(uid) : null;
    if (!u || u.disabled || uid === (peer.user_id || "")) continue;   // the owner is always in; it is not a "share"
    users.push({ id: uid, name: u.name, devices: here(uid), until: until || 0 });
  }
  for (const [gid, until] of Object.entries(sh.groups || {})) {
    const g = live(until) ? Store.group(gid) : null;
    if (!g) continue;
    groups.push({ id: gid, name: g.name, members: (g.users || []).length, until: until || 0 });
  }
  // Grantees who actually reach it first: a grant to somebody with no device on the right node is worth nothing, and with
  // a long list those are exactly the rows that should fall past the cap rather than crowd out the ones that work.
  users.sort((a, b) => b.devices - a.devices || String(a.name).localeCompare(String(b.name)));
  groups.sort((a, b) => String(a.name).localeCompare(String(b.name)));
  return { mode: users.length || groups.length ? "shared" : "owner", nodes, owner, users, groups };
}
// The node's own verdict, asked once when the bubble opens and cached by the SAME rule as everything else asked of the panel.
const AUD = new Map();
export const peerAudCached = pid => { const e = AUD.get(pid); return e && e.rep && askFresh(e) ? e.rep : null; };
export async function peerAudFetch(pid) {
  const e = AUD.get(pid);
  if (e && (e.busy || (e.rep && askFresh(e)))) return;
  // ⚠️ KEEP THE OLD STAMP while the new answer is in flight. Carrying the previous payload forward is right;
  // carrying it under the NEW signature is what made a revoked share read as current for a whole round trip.
  AUD.set(pid, { ...(e || {}), busy: true });
  let rep = { targets: [] };
  try {
    const r = await api.peerNetworks({ peer_id: pid });
    rep = (r && r.data) || { targets: [] };
  } catch (_) { rep = { targets: [] }; }
  AUD.set(pid, { at: Date.now(), sig: askSig(), rep });
  bus.emit();
}

// What the chip says: online devices while any are online, otherwise all of them — so the number is the one worth acting on.
export function reachTally(uid) {
  let total = 0, online = 0;
  for (const r of userReach(uid)) { total += r.devices.length; online += r.online; }
  return { total, online, shown: online || total };
}

// ── NETWORKS on a user's line (docs/NETWORKS-PLAN.md §18) ────────────────────────────────────────────────────────────────────
// ⚠️ THE PANEL'S ANSWER, NOT A GUESS. Which networks a node actually carries — an overlapping prefix resolved to ONE device, one
// a node refuses, a restricted one on a node that cannot enforce it, a blocked provider, a keyless device whose build cannot
// vouch for it, the node's own local network — is decided by `node_networks` / `user_networks` and nothing in the roster says
// it. A list that derived its own version disagreed with the very sheet it sits next to (seen 2026-09-16: one row here, four
// there). So the bubble asks `/api/users/networks`, the same call the sheet makes — once, when it is opened, cached a minute.
const NETS = new Map();
export function netsCached(uid) { const e = NETS.get(uid); return e && e.rows && askFresh(e) ? e : null; }
export async function netsFetch(uid) {
  const e = NETS.get(uid);
  if (e && (e.busy || (e.rows && askFresh(e)))) return;
  // ⚠️ KEEP THE OLD STAMP while the new answer is in flight. Carrying the previous payload forward is right;
  // carrying it under the NEW signature is what made a revoked share read as current for a whole round trip.
  NETS.set(uid, { ...(e || {}), busy: true });
  let rows = [];
  try {
    const r = await api.userNetworks({ user_id: uid });
    // ONE row per (node, network) — the same shape the sheet lists, not one per deployment that reaches it.
    // `covered` follows the sheet's rule: the user reaches it if ANY of their devices there routes it, and an
    // unknown (keyless) deployment never outranks a device that does.
    const rank = c => (c === true ? 2 : c == null ? 1 : 0);
    const seen = new Map();
    for (const p of ((r && r.data && r.data.peers) || []).filter(x => !x.blocked)) for (const t of p.targets || []) {
      for (const n of t.networks || []) {
        const k = t.node + "|" + n.prefix, cur = seen.get(k);
        if (!cur) seen.set(k, { node: t.node, prefix: n.prefix, via: n.via || "", restricted: !!n.restricted, until: n.until || 0, covered: n.covered });
        else if (rank(n.covered) > rank(cur.covered)) cur.covered = n.covered;
      }
      if (t.lan && (t.lan.addrs || []).length) {
        const k = t.node + "|lan", cur = seen.get(k);
        if (!cur) seen.set(k, { node: t.node, prefix: t.lan.addrs.join(", "), lan: t.lan, covered: t.lan.covered });
        else if (rank(t.lan.covered) > rank(cur.covered)) cur.covered = t.lan.covered;
      }
    }
    rows = [...seen.values()].sort((a, b) => String(Store.nodeName(a.node)).localeCompare(String(Store.nodeName(b.node)))
      || (a.lan ? 1 : 0) - (b.lan ? 1 : 0) || String(a.prefix).localeCompare(String(b.prefix)));
  } catch (_) { rows = []; }
  NETS.set(uid, { at: Date.now(), sig: askSig(), rows });
  COUNTS.set(uid, { sig: askSig(), at: Date.now(), n: rows.length,       // ⚠️ THE SAME SHAPE flushNetsCounts writes:
    rows: rows.map(r => ({ node: r.node, via: r.via || "", lan: !!r.lan, covered: r.covered })) });
  // a bare number here read back as `undefined` through netsCount and as stale through askFresh, so opening a bubble both
  // blanked the chip and re-queued that uid on every render — the flicker this cache exists to remove.
  bus.emit();     // the chip's count was the roster's guess until now — it says the panel's number from here on
}

// ── the CHIP'S number ────────────────────────────────────────────────────────────────────────────────────────────────────────
// ⚠️ ONE-WAY. A count here is only ever replaced by another answer from the panel, never reverted to the roster's guess. The
// chip used to read 1, correct itself to 4 when hovered, and fall back to 1 a minute later: a number that changes when you
// look at it is worse than no number.
const COUNTS = new Map();
export const netsCount = uid => { const e = COUNTS.get(uid); return e ? e.n : null; };
// The rows behind that number, in brief ({node, via, lan, covered}) — what a chip needs to count the ONLINE ones. Null from a
// panel that answers counts alone.
export const netsBrief = uid => { const e = COUNTS.get(uid); return e && Array.isArray(e.rows) ? e.rows : null; };

// ⚠️ ONE ANSWER TO "IS THIS NETWORK LIVE", for the chip's number, the bubble's Online list and every dot in it — the reach chip's
// rule, and the reason its number and its bubble never disagree. Live means reachable NOW: this user's routing covers it (a row
// it does not route, or cannot tell, is never counted), and what carries it is up where it is carried — the device behind the
// network online ON THAT NODE (a row's node is where its device sits: the carry plan is per node), or, for a node's own LAN,
// the node itself.
let _pbOf = null, _pb = null;             // peers by id, rebuilt once per roster snapshot — every chip on a page asks per row
const peerById = id => {
  if (_pbOf !== Store.recon) { _pbOf = Store.recon; _pb = new Map(Store.recon.peers.map(p => [p.id, p])); }
  return _pb.get(id);
};
export function netRowOnline(r) {
  if (!r || r.covered === false || r.covered == null) return false;
  if (r.lan) return (Store.recon.nodeStatus || {})[r.node] === "live";
  const dev = r.via ? peerById(r.via) : null;
  return !!(dev && (dev.targets || []).some(t => t && t.node === r.node && t.online));
}
// The chip's number, as reachTally says it for devices: the online count while any are, otherwise all of them. `known` false
// = only the roster's guess so far, which cannot say what is live.
export function netTally(uid) {
  const hit = netsCached(uid);
  const rows = hit ? hit.rows : netsBrief(uid);
  const n = netsCount(uid);
  if (!rows) {
    const total = n != null ? n : new Set(userNets(uid).map(x => x.prefix)).size;
    return { total, online: 0, shown: total, known: n != null };
  }
  const online = rows.filter(netRowOnline).length;
  return { total: rows.length, online, shown: online || rows.length, known: true };
}
let PEND = new Set(), PEND_T = null;
// A chip asks for its own number; the asks are collected and go out as ONE request for the rows actually on screen.
export function wantNetsCount(uid) {
  if (!uid) return;
  if (askFresh(COUNTS.get(uid))) return;
  PEND.add(uid);
  if (!PEND_T) PEND_T = setTimeout(flushNetsCounts, 60);
}
async function flushNetsCounts() {
  PEND_T = null;
  const ids = [...PEND];
  PEND.clear();
  if (!ids.length) return;
  const sig = askSig(), at = Date.now();
  try {
    const r = await api.userNetworks({ user_ids: ids });
    const c = ((r && r.data) || {}).counts, rw = ((r && r.data) || {}).rows || {};
    if (!c) return;                       // an older panel without the batch: keep whatever is on screen
    for (const k of Object.keys(c)) COUNTS.set(k, { sig, at, n: c[k], rows: Array.isArray(rw[k]) ? rw[k] : null });
    bus.emit();
  } catch (_) { /* leave the numbers alone rather than flicker back to a guess */ }
}

// What the roster alone knows, which is what the chip counts UNTIL the panel has answered once: the networks their own devices
// carry, and the ones shared with them by name or through a group.
export function userNets(uid) {
  const gids = new Set(Store.groupsByUser(uid).map(g => g.id));
  const out = [];
  for (const p of Store.recon.peers) {
    if (!(p.routes || []).length) continue;
    const sh = p.share && typeof p.share === "object" ? p.share : null;
    const own = p.user_id === uid;
    // ⚠️ Private outranks the stored share here too — this is the count the chip shows BEFORE the panel answers, so
    // without it a grantee's chip briefly included a private device's networks and then corrected itself downward,
    // which is the flicker the one-way COUNTS rule exists to prevent. The owner still sees their own.
    if (p.private && !own) continue;
    const named = !!(sh && sh.users && Object.prototype.hasOwnProperty.call(sh.users, uid));
    const via = sh && sh.groups && !own && !named ? Object.keys(sh.groups).find(g => gids.has(g)) : null;
    if (!own && !named && !via) continue;
    const vname = via ? (Store.group(via) || {}).name || "" : "";
    for (const prefix of p.routes) out.push({ prefix, peer: p, own, via: vname });
  }
  return out.sort((a, b) => (a.own === b.own ? 0 : a.own ? -1 : 1) || a.prefix.localeCompare(b.prefix));
}
// "Office router, Home NAS, Dacha and 4 more" — three named, the rest counted, as one translatable phrase.
export function namedFew(names) {
  if (names.length <= 3) return names.join(", ");
  return T("{names} and {n} more", { names: names.slice(0, 3).join(", "), n: names.length - 3 });
}

// Land on the Users screen at the PAGE where `userId` sits, expand that user's row and scroll it into view.
// Optionally glow a just-assigned peer's row (peerId). Shared by "click a username anywhere" and the assign
// flow (when it started on the Users screen). It opens the USERS list even if the operator last left the screen on Groups.
export function revealUser(userId, peerId) {
  if (!userId) return;
  usersView.mode = "users"; usersView.q = ""; usersView.expanded[userId] = true;
  go("#/users");
  setTimeout(() => {                          // after the poll + re-render settles
    usersView.page = userPageOf(userId);      // the page this user actually lands on (not always page 1)
    if (peerId) Store.recentlyCreated[peerId] = Date.now();   // 1.5s glow on the peer's row
    Store.apply();                            // re-render Users with the right page + expansion
    requestAnimationFrame(() => { const el = document.getElementById("urow-" + userId); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" }); });   // land the row near the top with breathing room (scroll-margin-top on .urow), not centered under its expanded peers
  }, 240);
}
// Clicking a PEER anywhere reveals its OWNER on the Users screen (row expanded, that peer's row glowing) — there
// is no standalone peer page. An unassigned peer (no owner) just lands on the Users screen with its row glowing.
export function revealPeer(peer) {
  if (!peer) { usersView.mode = "users"; return go("#/users"); }
  if (peer.user_id != null) { revealUser(peer.user_id, peer.id); return; }
  usersView.mode = "users"; Store.recentlyCreated[peer.id] = Date.now(); go("#/users");
}
// Land on the PEERS screen with a specific peer visible + its row flashing (activity-feed clicks). Filters
// the grid to that peer (unique IP) so it's guaranteed on-page, then scrolls to + glows it for ~2.5s.
export function revealPeerInPeers(peer) {
  if (!peer) return go("#/peers");
  const ip = (peer.targets && peer.targets[0] && peer.targets[0].ip) || "";
  peersView.node = "*"; peersView.iface = "*"; peersView.status = null;
  peersView.q = ip || peer.title || peer.name || ""; peersView.page = 1;
  Store.recentlyCreated[peer.id] = Date.now();
  go("#/peers");
  setTimeout(() => {
    Store.apply();
    requestAnimationFrame(() => { const el = document.querySelector('[data-peer="' + peer.id + '"]'); if (el) el.scrollIntoView({ behavior: "smooth", block: "center" }); });
  }, 240);
}
export function revealPeerInPeersById(id) { revealPeerInPeers((Store.recon.peers || []).find(p => p.id === id)); }
// Land on the PEERS screen filtered to a status (a grouped Needs-attention click) — optionally scoped to
// one node. status "unassigned" is a synthetic filter (peers with no owner); the rest match a peer status.
export function revealPeersFiltered({ node, status }) {
  peersView.node = node || "*"; peersView.iface = "*";
  peersView.status = status || null; peersView.q = ""; peersView.page = 1;
  go("#/peers");
}
// Land on an interface detail and scroll to its unmanaged/orphan panel (a grouped-orphans click).
export function revealOrphans(node, iface) {
  go("#/node/" + encodeURIComponent(node) + "/" + encodeURIComponent(iface));
  setTimeout(() => requestAnimationFrame(() => { const el = document.getElementById("iface-orphans"); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" }); }), 320);
}
// after assigning a peer TO a user: glow the just-assigned peer's row wherever it is. If we're already on the
// Users screen, ALSO reveal the user (their page + expand + scroll). But when the assignment came from the
// Peers screen, a peer-view modal, or a node's interface, STAY on that screen (just the glow) — no jump to Users.
export function revealAssignedPeer(userId, peerId) {
  if (!userId) return;
  if (peerId) Store.recentlyCreated[peerId] = Date.now();   // glow the row on whatever screen shows it
  if ((location.hash || "").startsWith("#/user")) revealUser(userId, peerId);   // already on Users → reveal
  else Store.apply();                                       // assigned from Peers / a node interface → stay put
}

// ── who is online, and the mesh link health, with the popovers that show them ────────────────────
// online USERS + their online-peer counts — global (nodeId null) or scoped to a node
const _byHandshake = (a, b) => {   // most-recent handshake first; never-seen last
  const av = a.lastAge == null ? Infinity : a.lastAge, bv = b.lastAge == null ? Infinity : b.lastAge;
  return av - bv;
};

export function orphCount(nodeId, iface) {
  return (Store.recon.orphans || []).filter(o => o.node === nodeId && (iface == null || o.iface === iface)).length;
}

export function onlineUserRows(nodeId) {
  const m = {};
  (Store.recon.peers || []).forEach(p => {
    const isOn = nodeId ? p.targets.some(t => t.node === nodeId && t.online) : p.online;
    if (!isOn) return;
    const id = p.unassigned ? "_un" : ("u" + p.user_id);
    if (!m[id]) m[id] = { name: p.unassigned ? T("val|Unassigned") : (p.name || T("(unnamed)")), count: 0, unassigned: !!p.unassigned, lastAge: null };
    m[id].count++;
    if (p.lastHandshakeAge != null) m[id].lastAge = (m[id].lastAge == null) ? p.lastHandshakeAge : Math.min(m[id].lastAge, p.lastHandshakeAge);
  });
  return Object.values(m).sort(_byHandshake);
}

// The headline "online" number for the users tag: each assigned user counts ONCE (however many peers they have),
// each unassigned peer counts individually — so 5 users + 3 loose peers reads as 8, not 6. Works on both the live
// rows (onlineUserRows) and the ranged rows (presence.userRows), which share the same {unassigned,count} shape.
export function onlineUserCount(rows) { return (rows || []).reduce((a, r) => a + (r.unassigned ? (r.count || 0) : 1), 0); }

// online PEERS on an interface (or the whole node when iface == null, or the whole fleet when nodeId == null)
export function onlinePeerRows(nodeId, iface) {
  const onT = (t) => (nodeId == null || t.node === nodeId) && (iface == null || t.iface === iface) && t.online;
  return (Store.recon.peers || []).filter(p => p.targets.some(onT))
    .map(p => { const t = p.targets.find(onT) || {};
      return { title: p.title || p.name || T("(peer)"), user: p.unassigned ? T("val|Unassigned") : (p.name || T("(unnamed)")),
               ip: t.ip || "", iface: t.iface, unassigned: !!p.unassigned, lastAge: p.lastHandshakeAge }; })
    .sort(_byHandshake);
}

// peers reaching `iface` THROUGH a turn-proxy: online, and the wg-observed endpoint IP == the proxy's
// connect IP (so they came via the relay, not directly). connectIp = ipOf(turn.connect).
// online peers attributed to THIS specific turn-proxy. Reconcile maps a peer's observed endpoint IP to one
// service (turnIp), so a peer counts for exactly one proxy — several proxies sharing 127.0.0.1 no longer all
// claim the same connection (was matched by connect IP, which is identical across proxies on one wg port).
export function turnConnRows(nodeId, iface, service) {
  const onT = (t) => t.node === nodeId && t.iface === iface && t.online && t.viaTurn === service;
  return (Store.recon.peers || []).filter(p => p.targets.some(onT))
    .map(p => { const t = p.targets.find(onT) || {};
      return { title: p.title || p.name || T("(peer)"), user: p.unassigned ? T("val|Unassigned") : (p.name || T("(unnamed)")), ip: t.ip || "", unassigned: !!p.unassigned, lastAge: p.lastHandshakeAge }; })
    .sort(_byHandshake);
}

// Online users of a WDTT instance — the WDTT analogue of turnConnRows. A WDTT server owns its interface, so its
// peers attach by (node, iface) with no viaTurn hop; reconcile.js sets `online` on the wdtt target directly.
export function wdttConnRows(nodeId, iface) {
  const onT = (t) => t.node === nodeId && t.iface === iface && t.online;
  return (Store.recon.peers || []).filter(p => p.targets.some(onT))
    .map(p => { const t = p.targets.find(onT) || {};
      return { title: p.title || p.name || T("(peer)"), user: p.unassigned ? T("val|Unassigned") : (p.name || T("(unnamed)")), ip: t.ip || "", unassigned: !!p.unassigned, lastAge: p.lastHandshakeAge }; })
    .sort(_byHandshake);
}

export function OnlPop({ title, rows, peer, orphans, orphHref, trigger, cls, count, hoverOnly }) {
  const tab = peer ? "peers" : "users";                  // this bubble lists peers, or users
  const n = count != null ? count : rows.length;         // the headline number (users tag overrides it: users + loose peers, not row count)
  const renderRow = peer
    ? r => html`<div class=${"onrow" + (r.unassigned ? " un" : "")}><span class="on-name">${r.title}</span><span class="on-user faint">${r.user}${r.iface ? " · " + r.iface : ""}${r.ip ? " · " + r.ip : ""}</span></div>`
    : r => html`<div class=${"onrow" + (r.unassigned ? " un" : "")}><span class="on-name">${r.name}</span><span class="on-ct">${r.count} <span class="faint">${pluralWord(r.count, "peer")}</span></span></div>`;
  return html`<${Popover} cls=${"onlinetag " + (cls || "")} hoverOnly=${hoverOnly} trigger=${trigger(n)}>
    <a class="onpop-h onpop-link" href="#/connections" onClick=${openLiveTab(tab)}>${title} · ${n} →</a>
    ${rows.length ? rows.slice(0, 10).map(renderRow) : html`<div class="onrow faint">${peer ? T("no peers online") : T("no one online")}</div>`}
    ${orphans ? html`<a class="onpop-orph" href=${orphHref || "#/connections"} onClick=${openLiveTab("peers")}>${T("{v1} unmanaged orphan", { v1: plural(orphans, "peer") })}</a>` : null}
    ${rows.length > 10 ? html`<a class="onpop-viewall" href="#/connections" onClick=${openLiveTab(tab)}>${T("view all {n} connections →", { n: rows.length })}</a>` : null}
  </${Popover}>`;
}

// ───── mesh health: per-node, per-direction link status (down = other→this · up = this→other) ─────
// OUT (this node → peer) = this node's reported handshake on its link iface. IN (peer → this node) = the
// PEER's reported handshake on its iface back to this node. Both come from snapshots the panel already has.
export function meshHealth(nodeId) {
  const byId = id => (Store.nodes || []).find(n => n.id === id);
  const mp = (byId(nodeId) || {}).mesh_peers || [];
  const hs = (nid, iface) => iface ? (((Store.describe || {})[nid] || {})[iface] || {}).handshake_age : undefined;
  const stat = (nid, iface, reprov) => reprov ? "connecting"
    : (nodeStale(nid) || !iface) ? "down"
    : (hs(nid, iface) == null ? "connecting" : (hs(nid, iface) < 180 ? "up" : "down"));
  const peers = mp.map(({ peer, iface, reprovisioning }) => {
    const pmp = ((byId(peer) || {}).mesh_peers || []).find(x => x.peer === nodeId) || {};
    // A mesh link is live only when BOTH ends are reporting. If either endpoint is stale/offline, neither direction
    // can be asserted up: the surviving end's handshake age lags up to 180s behind the peer actually going away —
    // which showed an offline node ↓1/1 AND its still-online peer ↑1/1 to a node that's already gone. Zero both.
    const linkDown = nodeStale(nodeId) || nodeStale(peer);
    // Leg quality as measured FROM THIS NODE (the node probes its own links). A handshake says the link is
    // up; this says whether it carries traffic well — 0.4% loss caps a single cascaded TCP flow at a few
    // Mbit/s while the same link moves hundreds in the other direction.
    const link = (((Store.describe || {})[nodeId] || {})[iface] || {}).link || null;
    // …and the PEER's measurement of the same leg. Each node probes its OWN links, so "how is the traffic
    // coming IN to this node" is a question only the other end can answer. The inbound bubble asks exactly
    // that, and showing our own outbound figure there would answer a different question with a straight face.
    const plink = (((Store.describe || {})[peer] || {})[pmp.iface] || {}).link || null;
    return { peer, link, plink,
      out: linkDown ? "down" : stat(nodeId, iface, reprovisioning),
      in:  linkDown ? "down" : stat(peer, pmp.iface, pmp.reprovisioning) };
  });
  return { peers, total: peers.length,
    okIn: peers.filter(p => p.in === "up").length, okOut: peers.filter(p => p.out === "up").length };
}

export const mhArrow = (dir, status) => html`<span class=${"mh-ar mh-" + dir + " s-" + status}>${dir === "down" ? "↓" : "↑"}</span>`;

// mode "in" → node-detail header (inbound only) · mode "both" → nodes-list (down = inbound, up = outbound)
export function MeshStat({ nodeId, mode }) {
  const h = meshHealth(nodeId);
  if (!h.total) return null;
  // all-up → the arrow's colour (inbound green · outbound blue) · none up → red · partial → orange
  const num = (ok, dir) => html`<b class=${"mh-num " + (mode === "in" ? "mh-num-hdr " : "") + (ok >= h.total ? dir : ok === 0 ? "mhn-bad" : "mhn-warn")}>${ok}/${h.total}</b>`;
  const ordered = (Store.nodes || []).filter(n => h.peers.some(p => p.peer === n.id));
  // The loss COLUMN exists only when some leg actually has loss — otherwise a healthy fleet pays for an
  // empty gutter on every row. Layout stays stable while it is there, so a value appearing does not shift
  // the columns beside it.
  // DIRECTION MATTERS, AND IT MATTERS PER QUANTITY.
  //
  // RTT is a ROUND trip: measured from either end it crosses the same point-to-point tunnel out and back,
  // so our own reading is a legitimate answer in an inbound view. LOSS IS NOT — it is per-direction, and
  // only the far end can measure what arrives here. So the inbound bubble takes latency from whichever end
  // has it and takes loss ONLY from the peer.
  //
  // The fallback used to cover both, which put this node's OUTBOUND loss under an "inbound" heading — the
  // same figure the link cards already show for the other direction, wearing the opposite label. A number
  // in the wrong direction is worse than a blank cell: the blank says "not measured", the number lies.
  const legOf = p => (mode === "in" ? (p.plink || p.link) : p.link);
  const legIsPeer = p => mode !== "in" || !!p.plink;
  const lossOf = p => (mode === "in" ? p.plink : p.link);   // directional: never borrowed from the near end
  const anyLoss = h.peers.some(p => { const l = lossOf(p); return l && typeof l.loss === "number" && l.loss > 0; });
  const row = n => {   // node name FIRST, then the glowing arrow(s)
    const p = h.peers.find(x => x.peer === n.id);
    const nameCls = p.in === "up" ? "mh-bold" : p.in === "down" ? "mh-dim" : "";
    // Leg quality in FIXED columns so they line up down the bubble, loss first because it is the alarm and
    // sits closest to the name that owns it. Loss renders ONLY when it is enough to matter: a "0.0%" on
    // every healthy row is noise that teaches the eye to skip the column, and then the one row that matters
    // gets skipped with it. The column itself only exists when some leg has loss (see anyLoss), so a healthy
    // fleet does not carry an empty gutter.
    const lk = legOf(p), ll = lossOf(p);
    const loss = ll && typeof ll.loss === "number" ? ll.loss : null;
    const warn = loss != null && loss > 0;   // ⚠️ MESH IS THE EXCEPTION: a DC-to-DC leg is not a client link: ANY loss on it is worth seeing, so this one shows from the
              // first lost packet rather than at the 0.05% the client-facing counters use.
    const legBase = !ll ? (lk ? T("Round-trip latency to {v3}. Loss this way is measured by {v3}, which has not reported it.", { v3: n.name }) : "")
      : legIsPeer(p) ? T("Leg measured from {v3}: {v1} of {v2} probe packets lost.",
                         { v1: ll.window_lost, v2: ll.window_sent, v3: n.name })
      : T("Leg measured from this node: {v1} of {v2} probe packets lost.",
          { v1: ll.window_lost, v2: ll.window_sent });
    // A row inside this bubble cannot carry a bubble of its own — the outer one closes the moment the
    // pointer leaves it for a portalled child — so the extra facts ride the native tooltip here. The mesh
    // CARDS, which are not inside a popover, get the full LossPop instead.
    const legTitle = [legBase,
      ll && typeof ll.peak_loss === "number" && ll.peak_loss > (ll.loss || 0) ? T("Worst probe {v1}%.", { v1: ll.peak_loss }) : "",
      ll && ll.last_loss_s != null ? T("Last loss {v1} ago.", { v1: seen(ll.last_loss_s) }) : "",
      lk && lk.mdev_ms != null ? T("Jitter {v1}ms.", { v1: lk.mdev_ms.toFixed(1) }) : "",
    ].filter(Boolean).join(" ");
    return html`<div class="mh-row" title=${legTitle}>
      <span class=${"mh-rn " + nameCls} style=${"color:" + Store.nodeColor(n.id)}>${n.name}</span>
      ${anyLoss ? html`<span class="mh-loss" style=${warn ? "color:" + lossColorMesh(loss) : ""}>${warn ? loss + "%" : ""}</span>` : null}
      <span class="mh-rtt">${lk && lk.rtt_ms != null ? Math.round(lk.rtt_ms) + T("unit|ms") : ""}</span>
      <span class="mh-rar">${mhArrow("down", p.in)}${mode === "both" ? mhArrow("up", p.out) : null}</span>
    </div>`;
  };
  const trigger = mode === "in"
    ? html`<span class="mh-tag mh-tag-hdr"><span class="mh-lbl-hdr">${T("This node's mesh status:")}</span> ${num(h.okIn, "mhn-down")}</span>`
    : html`<span class="mh-tag"><span class="nm-l">${T("Mesh")}</span><span class="mh-grp"><span class="mh-ar mh-down s-up">↓</span>${num(h.okIn, "mhn-down")}</span><span class="mh-grp"><span class="mh-ar mh-up s-up">↑</span>${num(h.okOut, "mhn-up")}</span></span>`;
  return html`<${Popover} cls="mh-pop" popCls=${"mh-bubble" + (anyLoss ? " has-loss" : "")} alignRight=${true} trigger=${trigger}>
    <div class="onpop-h">${mode === "in" ? T("Inbound links") : T("Mesh connections")}</div>
    ${ordered.map(row)}
  </${Popover}>`;
}

// ───── interface drops: what the kernel counters can actually tell an operator ─────
// The card shows one percentage. One percentage cannot be acted on: a receive backlog overflowing, a link
// whose far end had no session, and a send that failed outright are different faults wearing the same
// number. This bubble splits it the way the kernel already counts it, and adds the two things a rolling
// mean hides — the worst single sample (bursts are what users feel; a 0.02% mean can be one 5% sample)
// and whether it is happening NOW or is a scar from hours ago.
//
// Everything here is free: the node reads sysfs counters it was already reading. Fields are all optional,
// because a node on an older build reports only pct/window_* and this must degrade to that quietly.
//
// ⚠️ THE HEADLINE COUNTS ONLY THE NODE'S `fault_kinds`. On a client-facing kernel wg/awg interface that is rx_drop alone:
// the kernel's tx_dropped there is packets held for a client that had no session (asleep, out of coverage, just removed),
// tx_errors is traffic to an address no client owns, rx_errors is one client sending from outside its range — none of it
// something a connected client lost, and together they read 40-50% on quiet interfaces. The node says which kinds count
// (see _FAULT_ALL in swg-noded); the rest are summed into one "Not counted" row, with a line saying what they are.
// The old labels had rx_drop as "refused" — that is rx_errors.
const DROP_KINDS = [
  // On a kernel device a counted tx_drop can only be a mesh link (a client interface leaves it out), and there it is
  // no queue at all: packets held for a far end with no session. "queue full" is true of a TUN only.
  { k: "tx_drop", dir: "out", lbl: d => d.dp === "wg" ? T("no session") : T("queue full"),
    hint: d => d.dp === "wg" ? T("Packets held for the other server were discarded because the link had no working session — it was down.")
      : d.dp === "tun" ? T("The program serving this interface didn't read its queue in time — local load, or it was restarting.")
      : T("Packets waiting to go out were discarded before they could be sent.") },
  { k: "tx_err",  dir: "out", lbl: () => T("failed"),
    hint: () => T("Sends failed outright — no route out, or a peer whose endpoint this node doesn't know yet.") },
  { k: "rx_drop", dir: "in",  lbl: () => T("overflow"),
    hint: () => T("Packets arrived faster than this node could take them in — local load, not the path.") },
  { k: "rx_err",  dir: "in",  lbl: () => T("refused"),
    hint: () => T("Packets came from a source outside the sender's allowed range, or were malformed — usually one misconfigured sender.") },
];

// Below this many packets in the window a percentage is arithmetic, not a measurement — 3 drops among 4 packets is 43% —
// so the count shows instead, and the node card stays quiet. The same number as the node's per-sample floor
// (IFACE_PEAK_MIN in swg-noded) but NOT the same floor: that one is per 5 s sample, this one is the whole window. Kept in
// the browser on purpose: `pct` stays a number, so a panel older than this still renders what a newer node sends.
const DROP_PCT_MIN = 200;
export const dropsEnough = d => (d.window_pkts || 0) + (d.window_bad || 0) >= DROP_PCT_MIN;
// Below the floor the COUNT shows even when it is 0: "0%" over a window that moved no packets looks like a clean measurement.
export function DropsFigure({ d }) {
  return !dropsEnough(d)
    ? html`<span class="dp-num">${fmtCount(d.window_bad)} ${T("dropped")}</span>`
    : html`<span class="dp-num" style=${"color:" + lossColor(d.pct)}>${d.pct}%</span>`;
}

// ───── mesh loss: the same treatment, for the number that comes off the probe ─────
// ⚠️ THE HEADLINE PERCENTAGE OVERSTATES ITS OWN PRECISION. 20 packets a minute over a 30-probe window is
// 600 packets, so the smallest non-zero loss the probe can express is 1/600 = 0.167% — and that is exactly
// the figure an operator sees when ONE packet went missing, once, up to half an hour ago. The bubble's job
// is to put that packet count in front of them, and to say when it happened, before they go rebuild a leg
// that is fine. Everything here is measured already; none of it costs another probe.
//
// `l` = this end's reading, `pl` = the far end's reading of the same leg. Loss is directional — only the
// receiving end can see what failed to arrive — so both are shown side by side rather than averaged.
export function LossPop({ l, pl, peerName, node, iface, trigger, alignRight }) {
  const [reset, setReset] = useState("");
  if (!l && !pl) return trigger;
  // ⚠️ RESETS THE LEG, NOT THIS END. `Out` is this node's probe, `In` is the far node's probe of us — two
  // independent measurements — so the panel stamps the nonce on BOTH ends (mesh_leg_ends). Clearing only
  // the near end would leave half the bubble reading the old outage, which looks like a bug, not a reset.
  const doReset = async e => {
    e.preventDefault(); e.stopPropagation();
    setReset("busy");
    const r = await api.ifaceUpdate({ node: node, iface: iface, mesh_reset: 1 });
    if (r && r.ok) { setReset("ok"); setTimeout(() => setReset(""), 2500); }
    else { setReset(""); toast(srvText(r) || T("Couldn't reset the probe window."), "err"); }
  };
  // ⚠️ EVERY QUALIFIER MUST FOLLOW THE DIRECTION IT BELONGS TO. The first cut anchored "worst probe",
  // "last loss" and the RTT spread to whichever end reported first — in practice always the near one — so
  // a leg losing 2.4% INBOUND, with 412ms of far-end bufferbloat, rendered "last loss: none in this
  // window", "jitter 0.3ms", no worst-probe row at all. Every figure was true of the clean direction and
  // read as a verdict on the leg. Same class of bug as the inbound bubble showing outbound loss: a number
  // under the wrong label is worse than a blank cell, because a blank says "not measured".
  // ⚠️ THESE ROWS ARE NOT DIRECTIONS, AND CALLING THEM "Out"/"In" CLAIMED MORE THAN THE PROBE MEASURES.
  // Both are `ping` — a ROUND TRIP. The near node's probe goes near→far and the reply comes far→near; the
  // far node's probe does the same in the opposite order. Each one therefore crosses BOTH directions, so a
  // packet lost anywhere shows up in whichever probe was unlucky, and neither number can say which way the
  // loss happened. Two rows that disagree are two samples of one bidirectional path, not two directions.
  // Label them by WHO MEASURED, which is exactly what distinguishes them, and say what a row is.
  const nearName = node ? Store.nodeName(node) : T("this node");
  const ends = [];
  if (l && typeof l.loss === "number") ends.push({ dir: nearName, x: l });
  if (pl && typeof pl.loss === "number") ends.push({ dir: peerName, x: pl });
  if (!ends.length) return trigger;
  const both = ends.length > 1;
  const tag = e => both ? html`<span class="dp-kind">${e.dir}</span>` : null;
  const pick = (has, better) => { const c = ends.filter(has); return c.length ? c.reduce(better) : null; };
  const worst = pick(e => typeof e.x.peak_loss === "number", (a, b) => b.x.peak_loss > a.x.peak_loss ? b : a);
  const last  = pick(e => e.x.last_loss_s != null, (a, b) => b.x.last_loss_s < a.x.last_loss_s ? b : a);
  const reportsLast = ends.some(e => "last_loss_s" in e.x);
  // Round trip is symmetric, but each end SAMPLES it separately: one-way queueing shows up as a far-end
  // max the near end never sees. Show both rows only when they actually disagree — otherwise it is one
  // measurement printed twice.
  const rtts = ends.filter(e => e.x.rtt_ms != null);
  const spread = rtts.map(e => e.x.rtt_max != null ? e.x.rtt_max : e.x.rtt_ms);
  const splitRtt = rtts.length > 1 && Math.max(...spread) > Math.min(...spread) * 1.25;
  const rttRows = splitRtt ? rtts : rtts.slice(0, 1);
  const one = ends.find(e => e.x.window_lost === 1);   // 1/600 = 0.167%: the probe's own resolution floor
  return html`<${Popover} cls="drops-pop" popCls="dp-bubble" flipFit=${true} alignRight=${alignRight !== false} trigger=${trigger}>
    <div class="onpop-h dp-h">${T("Leg quality · {v1}", { v1: peerName })}
      ${node && iface ? html`<button class=${"dp-reset" + (reset === "ok" ? " ok" : "")} disabled=${reset === "busy"}
        title=${T("Clear this leg's probe window at both ends and start measuring again from now")}
        onClick=${doReset}>${reset === "ok" ? T("Reset ✓") : reset === "busy" ? T("Resetting…") : T("Reset")}</button>` : null}</div>
    ${ends.map(e => html`<div class="dp-row"><span class="dp-l">${e.dir}</span><span class="dp-v">
      <b style=${"color:" + lossColorMesh(e.x.loss)}>${e.x.loss}%</b>
      <span class="dp-kind">${T("{v1} of {v2}", { v1: e.x.window_lost, v2: e.x.window_sent })}</span></span></div>`)}
    ${rttRows.map(e => html`<div class="dp-row"><span class="dp-l">${T("Round trip")}</span><span class="dp-v">
      <b>${Math.round(e.x.rtt_ms)}${T("unit|ms")}</b>${e.x.rtt_min != null && e.x.rtt_max != null
        ? html`<span class="dp-kind">${T("min {v1} · max {v2}", { v1: Math.round(e.x.rtt_min), v2: Math.round(e.x.rtt_max) })}</span>` : null}${splitRtt ? tag(e) : null}</span></div>`)}
    ${rttRows.filter(e => e.x.mdev_ms != null).map(e => html`<div class="dp-row"><span class="dp-l">${T("Jitter")}</span>
      <span class="dp-v"><b>${e.x.mdev_ms.toFixed(1)}${T("unit|ms")}</b>${splitRtt ? tag(e) : null}</span></div>`)}
    ${worst && worst.x.peak_loss > (worst.x.loss || 0) ? html`<div class="dp-row"><span class="dp-l">${T("Worst probe")}</span>
      <span class="dp-v"><b style=${"color:" + lossColorMesh(worst.x.peak_loss)}>${worst.x.peak_loss}%</b>${tag(worst)}</span></div>` : null}
    ${last ? html`<div class="dp-row"><span class="dp-l">${T("Last loss")}</span><span class="dp-v">${
        last.x.last_loss_s < 90 ? T("just now") : T("{v1} ago", { v1: seen(last.x.last_loss_s) })}${tag(last)}</span></div>`
      : reportsLast ? html`<div class="dp-row"><span class="dp-l">${T("Last loss")}</span><span class="dp-v">${"—"}</span></div>` : null}
    ${one ? html`<div class="dp-hint">${T("That is a single lost packet — the smallest amount this probe can measure. One is normal; watch whether it keeps happening.")}</div>` : null}
    ${both ? html`<div class="dp-hint">${T("Each row is a round trip measured from that node, so both cross the link in both directions — a difference between them is two samples of the same link, not a direction.")}</div>` : null}
    ${/* ⚠️ THIS BUBBLE MIXES TWO TIME SPANS AND USED TO NAME NEITHER. Loss is accumulated over the whole
          30-probe window (half an hour) because one probe of 20 packets cannot express 0.4%; latency,
          min/max and jitter are the NEWEST probe alone — 20 packets over about four seconds. So "0.167%
          (1 of 600)" sat directly above "18ms" with thirty minutes between what they describe, and an
          operator reading the two together had no way to know. Say it. */""}
    <div class="dp-foot">${ends[0].x.probes
      ? T("Loss over the last {v1} ({v2} probes of {v3} packets, {v4}-byte). Latency and jitter are from the newest probe.",
          { v1: seen((ends[0].x.probes || 0) * (ends[0].x.probe_every_s || 60)), v2: ends[0].x.probes,
            v3: 20, v4: ends[0].x.probe_size })
      : T("measured by pinging the far end of this link")}</div>
  </${Popover}>`;
}

// Counts in these bubbles span six orders of magnitude — "75,773 of 756,880,952" is a line nobody reads,
// they just see two long numbers. Compact the big ones and leave the small ones ALONE: "1 of 600" is the
// entire point of the loss bubble (one lost packet, the probe's own resolution floor) and "0.6k of 600"
// would destroy it. So exactness below 10k, where every digit still carries meaning, and a short form
// above it, where they no longer do.
export const fmtCount = n => {
  n = Number(n) || 0;
  if (n < 10000) return fmtNum(n);
  const [d, u] = n < 1e6 ? [n / 1e3, "K"] : n < 1e9 ? [n / 1e6, "M"] : [n / 1e9, "G"];
  return d.toFixed(1).replace(/\.0$/, "") + u;
};

// Two decimals is right for 4.44/min and ridiculous for 80561.65/min. Scale the precision to the number.
export const dropRate = v => (v >= 100 ? fmtCount(Math.round(v)) : v >= 10 ? v.toFixed(1) : String(v));

// ───── turn-proxy socket drops ─────
// A proxy owns no interface, so this is not the same measurement as DropsPop and must not pretend to be:
// there is no received-packet count on a UDP socket, so there is NO PERCENTAGE — only the count and the
// rate, which are facts. Leading with a rate the data cannot support is the mistake `peak` already made.
export function ProxyDropsPop({ d, service, trigger, alignRight }) {
  if (!d) return trigger;
  const n = v => typeof v === "number";
  return html`<${Popover} cls="drops-pop" popCls="dp-bubble" flipFit=${true} alignRight=${alignRight !== false} trigger=${trigger}>
    <div class="onpop-h">${T("Dropped at the socket · {v1}", { v1: service })}</div>
    <div class="dp-head">
      <span class="dp-sub">${T("in the last {v1}", { v1: d.span_s ? seen(d.span_s) : "—" })}</span>
      <b class="dp-pct" style=${"color:" + lossColor(d.per_min > 0 ? Math.min(5, d.per_min / 20) : 0)}>${fmtCount(d.win_drops || 0)}</b>
    </div>
    ${n(d.per_min) ? html`<div class="dp-row"><span class="dp-l">${T("Rate")}</span><span class="dp-v"><b>${dropRate(d.per_min)}</b><span class="dp-kind">${T("per minute")}</span></span></div>` : null}
    ${n(d.rxq) ? html`<div class="dp-row"><span class="dp-l">${T("Backlog")}</span><span class="dp-v"><b>${fmtBytes(d.rxq)}</b><span class="dp-kind">${T("waiting")}</span></span></div>` : null}
    ${d.last_bad_s !== undefined ? html`<div class="dp-row"><span class="dp-l">${T("Last drop")}</span><span class="dp-v">${
      d.last_bad_s == null ? "—" : d.last_bad_s < 90 ? T("just now") : T("{v1} ago", { v1: seen(d.last_bad_s) })}</span></div>` : null}
    ${n(d.life_drops) ? html`<div class="dp-row"><span class="dp-l">${T("Since it started")}</span><span class="dp-v">${fmtCount(d.life_drops)}</span></div>` : null}
    <div class="dp-foot">${T("Packets that reached this server and were discarded because the proxy wasn't reading its socket fast enough. They never reach an interface, so no interface counter can show them.")}</div>
  </${Popover}>`;
}

export function DropsPop({ d, iface, node, trigger, alignRight }) {
  const [reset, setReset] = useState("");
  if (!d) return trigger;
  // Re-baseline on the NODE, not in the browser: the counters are the node's, and a page reload must not
  // undo it. The panel writes a nonce the node acts on once, so a slow sync only means it lands late.
  const doReset = async e => {
    e.preventDefault(); e.stopPropagation();
    setReset("busy");
    const r = await api.ifaceUpdate({ node: node, iface: iface, drops_reset: 1 });
    if (r && r.ok) { setReset("ok"); setTimeout(() => setReset(""), 2500); }
    else { setReset(""); toast(srvText(r) || T("Couldn't reset the counters."), "err"); }
  };
  const has = k => typeof d[k] === "number";
  // A node older than fault_kinds counts every kind — which is exactly what it put in its pct.
  const counts = k => !Array.isArray(d.fault_kinds) || d.fault_kinds.includes(k);
  const split = DROP_KINDS.filter(x => has(x.k) && counts(x.k));
  const offN = DROP_KINDS.filter(x => has(x.k) && !counts(x.k)).reduce((a, x) => a + d[x.k], 0);
  // The dominant kind names the fault. Only when it is genuinely dominant (over half) — a 50/50 mix has no
  // single explanation and inventing one would send the operator down the wrong path.
  const top = split.slice().sort((a, b) => d[b.k] - d[a.k])[0];
  const hint = top && d[top.k] > 0 && d[top.k] * 2 > d.window_bad ? top.hint(d) : null;
  const rowsFor = dir => split.filter(x => x.dir === dir);
  const pair = (dir, label) => {
    const rs = rowsFor(dir);
    if (!rs.length) return null;
    return html`<div class="dp-row"><span class="dp-l">${label}</span><span class="dp-v">${rs.map(x => html`
      <span class=${"dp-kind" + (d[x.k] ? "" : " zero")}>${x.lbl(d)} <b>${fmtCount(d[x.k])}</b></span>`)}</span></div>`;
  };
  return html`<${Popover} cls="drops-pop" popCls="dp-bubble" flipFit=${true} alignRight=${alignRight !== false} trigger=${trigger}>
    <div class="onpop-h dp-h">${T("Drops · {v1}", { v1: iface })}
      ${node ? html`<button class=${"dp-reset" + (reset === "ok" ? " ok" : "")} disabled=${reset === "busy"}
        title=${T("Zero the counters and start measuring again from now")}
        onClick=${doReset}>${reset === "ok" ? T("Reset ✓") : reset === "busy" ? T("Resetting…") : T("Reset")}</button>` : null}</div>
    ${/* The percentage is a VALUE, so it sits on the right where every other value in this bubble is,
          instead of on the left among the labels. */""}
    <div class="dp-head">
      <span class="dp-sub">${T("{v1} of {v2} packets", { v1: fmtCount(d.window_bad), v2: fmtCount(d.window_pkts) })}</span>
      ${dropsEnough(d) ? html`<b class="dp-pct" style=${"color:" + lossColor(d.pct)}>${d.pct}%</b>` : null}
    </div>
    ${pair("out", T("Sending"))}
    ${pair("in", T("Receiving"))}
    ${offN ? html`<div class="dp-row"><span class="dp-l">${T("Not counted")}</span><span class="dp-v">${fmtCount(offN)}</span></div>` : null}
    ${(() => {
      // ⚠️ THE RATE AND THE COUNT ANSWER DIFFERENT QUESTIONS, AND THE RATE CAN LIE. A 5s sample that pushed
      // 2 packets while dropping 70 is 97.22%, which the panel duly showed an operator as "Worst sample
      // 97.22%" on an interface whose 5-min window moved 23,416 packets cleanly. The node now withholds a
      // rate it cannot support (peak = null below IFACE_PEAK_MIN) and always reports the raw count, which
      // is a fact at any traffic level. So: lead with the rate when it means something, and let the count
      // carry the row when it doesn't — a burst must never go unreported just because the leg was quiet.
      const wp = has("peak") && d.peak > (d.pct || 0) ? d.peak : null;
      const wb = typeof d.peak_bad === "number" && d.peak_bad > 0 ? d.peak_bad : null;
      if (wp == null && wb == null) return null;
      return html`<div class="dp-row"><span class="dp-l">${T("Worst sample")}</span><span class="dp-v">${wp != null
        ? html`<b style=${"color:" + lossColor(wp)}>${wp}%</b>${wb ? html`<span class="dp-kind">${fmtCount(wb)} ${T("dropped")}</span>` : null}`
        : html`<b>${fmtCount(wb)}</b><span class="dp-kind">${T("dropped")}</span>`}</span></div>`;
    })()}
    ${has("last_bad_s") || d.last_bad_s === null ? html`<div class="dp-row"><span class="dp-l">${T("Last drop")}</span><span class="dp-v">${
      d.last_bad_s == null ? "—" : d.last_bad_s < 5 ? T("just now") : T("{v1} ago", { v1: seen(d.last_bad_s) })}</span></div>` : null}
    ${/* the ratio alone made the reader do the division — give them the rate too, at the row's own size */""}
    ${has("life_bad") ? html`<div class="dp-row"><span class="dp-l">${
      d.life_since ? T("Since reset") : T("Since boot")}</span><span class="dp-v">${
      T("{v1} of {v2}", { v1: fmtCount(d.life_bad), v2: fmtCount(d.life_pkts) })}${d.life_pkts
        ? html`<span class="dp-life" style=${"color:" + lossColor(100 * d.life_bad / d.life_pkts)}>${
            (100 * d.life_bad / d.life_pkts).toFixed(4)}%</span>` : null}</span></div>` : null}
    ${hint ? html`<div class="dp-hint">${hint}</div>` : null}
    ${offN ? html`<div class="dp-hint">${T("Not counted: packets for clients that weren't connected, traffic to addresses no client owns, and traffic one client sent from outside its range. None of it is something a connected client lost.")}</div>` : null}
    <div class="dp-foot">${d.span_s ? T("measured over the last {v1}", { v1: seen(d.span_s) }) : T("this node's own queues and datapath, not the path to the client")}</div>
  </${Popover}>`;
}

// "N online" tag → users bubble. nodeId null = whole fleet. trigger: optional (count)=>vnode.
// `presence` (from /api/presence, per node) switches this from "online right now" to "distinct users seen
// online during the selected range" — the question the range picker is actually asking. Without it the card
// answered "nobody is connected this instant" while the Day doughnut reported peers online that day.
export function OnlineUsersTag({ nodeId, cls, trigger, presence, rangeLabel }) {
  const [mode, setMode] = useState("users");             // click the tag to flip the whole tag+bubble users ↔ peers
  const isPeers = mode === "peers";
  const userRows = presence ? (presence.userRows || []).map(r => ({ ...r, lastAge: null })) : onlineUserRows(nodeId);
  const peerRows = onlinePeerRows(nodeId, null);          // live online peers on this node (or the fleet when nodeId==null)
  const rows = isPeers ? peerRows : userRows;
  const count = isPeers ? peerRows.length : onlineUserCount(userRows);
  const title = isPeers ? T("Online peers") : (presence ? T("Users online · {v1}", { v1: rangeLabel || T("val|range") }) : T("Online users"));
  const word = isPeers ? "peer" : "user";
  const dflt = (c, w) => html`<span class="dot"></span><b class=${"oncount" + (c ? " on" : "")}>${c}</b> ${pluralWord(c, w || "user")}`;
  // hoverOnly on the popover frees the click to TOGGLE the mode (rather than pin the bubble); the bubble updates live.
  const trig = c => html`<span class="onl-toggle" title=${T("Click to switch users / peers")} onClick=${e => { e.stopPropagation(); e.preventDefault(); setMode(m => m === "users" ? "peers" : "users"); }}>${(trigger || dflt)(c, word)}</span>`;
  return html`<${OnlPop} peer=${isPeers} title=${title} rows=${rows} count=${count} cls=${cls} hoverOnly=${true} trigger=${trig}/>`;
}

// "N online" peers bubble (device · user · ip). orphans: count to append. Used on interface cards/screens.
export function OnlinePeersTag({ nodeId, iface, total, cls, trigger, orphans, orphHref }) {
  return html`<${OnlPop} peer title=${T("Online peers")} rows=${onlinePeerRows(nodeId, iface)} orphans=${orphans} orphHref=${orphHref} cls=${cls}
    trigger=${trigger || (c => html`<b class=${"oncount" + (c ? " on" : "")}>${c}</b>${total != null ? " / " + total : ""} online`)}/>`;
}

// Jump to the Live screen already switched to the peers/users tab the caller means.
// shared online-breakdown bubble: a Live-linked header, top-10 rows (already handshake-sorted), an
// optional "n orphan peers" line, and a "view all" link past 10. trigger: (count)=>vnode.
// Open Live on the tab that matches the bubble that was clicked. `connView.mode` is module state that
// remembers the last toggle, so without this a Users bubble could land on the Peers table (or vice versa).
// The appbar bubble is visible ON the Live screen too, where the hash does not change — so nudge the bus.
export const openLiveTab = mode => e => {
  e.stopPropagation();
  connView.mode = mode; connView.page = 1;
  if (location.hash === "#/connections") bus.emit();     // already there: no hashchange to re-render us
};

// nodes: null = whole fleet, else a Set of node ids. peers/mesh = which traffic COMPONENTS the figures count
// (the toolbar badges): peers = client traffic (total−mesh), mesh = node↔node relay traffic. `ov` = per-widget
// overrides keyed by widget id, each {peers?,mesh?} where a set field pins that pill and null inherits the global.
// ─────────── Dashboard controls: node selector + time range ───────────
// Two module-level controls drive every Overview widget. The NODE selector filters the fleet the
// dashboard aggregates over (default = ALL, stored as null); unselecting nodes re-renders every widget
// for the remaining set (all-but-one = a single-node view). The RANGE selector chooses the history
// window for the range-driven visuals (doughnuts + flow map); live derives from the /api/state bundle,
// the rest read the per-node RRD on demand. Both live in module state + localStorage so a re-render or
// the 5s poll never clobbers the operator's selection (it's not derived from server data).
export const DASH_RANGES = [["live", "Live"], ["hour", "Hour"], ["day", "Day"], ["week", "Week"], ["month", "Month"]];   // i18n-keys: canonical (persisted range key + English label)
/* The range word, translated. Two forms because the dashboard uses both: capitalised on the rail buttons,
   lowercase inside a section subtitle ("distribution · за сутки"). Literal T() calls, as always. */
export const rangeLabel = k => isCustomKey(k) ? customKeyLabel(k) : ({ live: T("range|Live"), hour: T("range|Hour"), day: T("range|Day"), week: T("range|Week"), month: T("range|Month") }[k] || k);   // i18n-keys
export const rangeWord = k => isCustomKey(k) ? customKeyLabel(k) : (({ live: T("range|live"), hour: T("range|hour"), day: T("range|day"), week: T("range|week"), month: T("range|month") })[k] || T("range|live"));   // i18n-keys
// A custom Overview window (P3) travels as a KEY — "custom:YYYYMMDD-YYYYMMDD", the server's own `rangeKey` — never as the
// bare word "custom": two custom windows are both "custom", so a guard comparing that would render the last window's
// numbers under the new title. Everything ranged (fetch, stale guard, label, step) reads the key it LOADED.
export { isCustomKey, customKeyWindow };   // the grammar is store.js's (rangeQ reads it too)
export const customKeyLabel = k => trafficRangeLabel(customKeyWindow(k));
export const dashState = { nodes: null, range: "live", from: "", to: "", peers: true, mesh: true, ov: {} };
// The Overview's range key: a named range, or the custom window's key.
// A custom window kept from an earlier visit may have aged past what the charts keep (33 days): it is read from the first
// day they still hold — the rail and every title show the days actually read — instead of a page of refusals.
export function dashKey() {
  if (dashState.range !== "custom" || !dashState.from || !dashState.to) return dashState.range === "custom" ? "live" : dashState.range;
  const first = chartsFirstDay(), from = dashState.from < first ? first : dashState.from, to = dashState.to < from ? from : dashState.to;
  return "custom:" + from.replace(/-/g, "") + "-" + to.replace(/-/g, "");
}
(function () {
  try {
    const raw = JSON.parse(localStorage.getItem("swg-dash") || "{}");
    if (Array.isArray(raw.nodes) && raw.nodes.length) dashState.nodes = new Set(raw.nodes);   // ignore a stale empty selection → default to the whole fleet
    if (DASH_RANGES.some(r => r[0] === raw.range)) dashState.range = raw.range;
    else if (raw.range === "custom" && /^\d{4}-\d{2}-\d{2}$/.test(raw.from || "") && /^\d{4}-\d{2}-\d{2}$/.test(raw.to || "")) Object.assign(dashState, { range: "custom", from: raw.from, to: raw.to });
    if (typeof raw.peers === "boolean") dashState.peers = raw.peers;
    if (typeof raw.mesh === "boolean") dashState.mesh = raw.mesh;
    if (raw.ov && typeof raw.ov === "object") dashState.ov = raw.ov;
  } catch (_) {}
})();
export function dashSave() {
  try { localStorage.setItem("swg-dash", JSON.stringify({ nodes: dashState.nodes ? [...dashState.nodes] : null, range: dashState.range, ...(dashState.range === "custom" ? { from: dashState.from, to: dashState.to } : {}), peers: dashState.peers, mesh: dashState.mesh, ov: dashState.ov })); } catch (_) {}
}

// ── which nodes the Overview charts include (persisted per browser) ──
// Effective selected node ids, reconciled against the CURRENT fleet (ids for departed nodes drop out).
// An empty selection collapses back to the whole fleet — the dashboard is never blank.
// null OR an empty set both mean "the whole fleet" — the selection can never be empty (nothing to show).
export function dashNodes() {
  const fleet = (Store.fleet || []).map(n => n.id);
  if (!dashState.nodes || !dashState.nodes.size) return fleet;
  const sel = fleet.filter(id => dashState.nodes.has(id));
  return sel.length ? sel : fleet;
}

export function dashNodeOn(id) { const s = dashState.nodes; return !s || !s.size || s.has(id); }

export function dashToggleNode(id) {
  const fleet = (Store.fleet || []).map(n => n.id);
  const sel = new Set(dashState.nodes && dashState.nodes.size ? [...dashState.nodes].filter(x => fleet.includes(x)) : fleet);
  if (sel.has(id)) {
    if (sel.size <= 1) return;   // the last selected node can NOT be deselected — the dashboard always shows ≥1 node
    sel.delete(id);
  } else sel.add(id);
  dashState.nodes = (sel.size >= fleet.length) ? null : sel;   // all selected → canonical null (never an empty set)
  dashSave(); bus.emit();
}

// ── activity taxonomy + panel-service issues: derived from Store, read by more than one screen ──
// ─────────── Activity taxonomy ───────────
// The panel's server-side event log (/api/events) records every operator action. One place decides
// each record's ITEM category (icon + the history "Item" filter), an ACTION bucket (Added / Changed /
// Removed, the history "Action" filter), and where a click lands. Shared by the Overview feed and the
// full Activity-history grid so both stay consistent.
/* Display labels for EV_ITEMS. Written as eight LITERAL T() calls rather than T("event|" + item),
   because a composed key cannot be verified statically — the audit would see the key "event|" and
   report all eight translations as orphaned. Rule: T() always takes a literal. */
export const evItemLabel = item => ({
  "Peer": T("event|Peer"), "User": T("event|User"), "Node": T("event|Node"),   // i18n-keys
  "Interface": T("event|Interface"), "Turn-proxy": T("event|Turn-proxy"), "Mesh": T("event|Mesh"),   // i18n-keys
  "Settings": T("event|Settings"), "Update": T("event|Update"),   // i18n-keys
}[item] || item);
export const EV_ITEMS = ["Peer", "User", "Node", "Interface", "Turn-proxy", "Mesh", "Settings", "Update"];   // i18n-keys: canonical (filter value + routing key) — evDecorate adds itemLabel for display
export const EV_ACTIONS = ["Added", "Changed", "Removed"];   // i18n-keys: canonical (filter value + evAction result)
// ...and their display forms, literal for the same reason evItemLabel is.
export const evActionLabel = a => ({ "Added": T("event|Added"), "Changed": T("event|Changed"), "Removed": T("event|Removed") }[a] || a);   // i18n-keys
export const EV_ITEM_IC = { Peer: "device", User: "user", Node: "server", Interface: "network", "Turn-proxy": "relay", Mesh: "cascade", Settings: "gear", Update: "download" };
export const evSlug = s => s.toLowerCase().replace(/[^a-z]/g, "");   // "Turn-proxy" → "turnproxy" (CSS tint class)
export function evItem(e) {
  const v = e.verb || "";
  if (e.kind === "peer") return "Peer";   // i18n-keys: canonical EV_ITEMS value
  if (e.kind === "user") return "User";
  if (e.kind === "group") return "User";   // a group lives on the Users screen (docs/GROUPS-PLAN.md G11)
  if (e.kind === "panel") return v === "Panel updated" ? "Update" : "Settings";   // i18n-keys: e.verb is the SERVER's English — never compare it to a translation
  if (/interface/i.test(v)) return "Interface";       // kind === node from here
  if (/turn-proxy/i.test(v)) return "Turn-proxy";
  if (/mesh/i.test(v)) return "Mesh";   // i18n-keys: canonical EV_ITEMS value
  if (/^update |host update/i.test(v)) return "Update";   // update LIFECYCLE ("Update requested", "Host update started") — NOT "Updated node/interface"
  return "Node";   // i18n-keys: canonical EV_ITEMS value — evItemLabel() translates it for display
}
export function evAction(e) {
  const v = (e.verb || "").toLowerCase();
  if (/\b(deleted|removed|deleting|uninstalled|flagged)\b/.test(v)) return "Removed";
  if (/\b(created|enrolled|installing|creating|onboarding|added|linked|adopted)\b/.test(v)) return "Added";
  return "Changed";
}
// Where a feed/grid row navigates. Returns {href} for a plain link, {href,on} for a scripted reveal
// (flash + scroll), or null for non-actionable rows (a version bump, an update-lifecycle note).
export function evClick(e) {
  const item = evItem(e), v = e.verb || "", gone = /\bdeleted\b/i.test(v);
  if (item === "Peer") return gone ? { href: "#/peers" } : { href: "#/peers", on: () => revealPeerInPeersById(e.id) };   // i18n-keys: canonical EV_ITEMS value
  // a group's id is not a user's: it opens Users → Groups, never revealUser
  if (e.kind === "group") return { href: "#/users", on: () => { usersView.mode = "groups"; usersView.gq = ""; go("#/users"); Store.apply(); } };
  if (item === "User") return gone ? { href: "#/users" } : { href: "#/users", on: () => revealUser(e.id) };
  if (item === "Settings") return { href: "#/panel/settings", on: () => { setPendingSection((e.id && e.id !== "settings") ? e.id : null); go("#/panel/settings"); } };
  if (item === "Update") return null;                 // panel version bump / update lifecycle — nothing to open
  if (/\b(removed node|uninstalled)\b/i.test(v)) return { href: "#/nodes" };   // the node is gone
  return e.id ? { href: "#/node/" + encodeURIComponent(e.id) } : { href: "#/nodes" };
}
export function evDecorate(e, i) {
  const item = evItem(e);
  const action = evAction(e);
  return { ...e, item, itemLabel: evItemLabel(item), action, actionLabel: evActionLabel(action), icon: EV_ITEM_IC[item] || "info", slug: evSlug(item),
           click: evClick(e), key: "e" + (e.eid || e.ts) + "_" + i };
}
// Fallback feed when the server log is still empty: synthesise created/updated rows from the roster's
// created_at vs modified_at, so a fresh panel's Overview is never blank.
export function synthEvents() {
  const ev = [];
  for (const u of Store.recon.users) {
    const c = u.created_at || 0, m = u.modified_at || c;
    ev.push({ ts: m, kind: "user", id: u.id, verb: m > c + 5 ? T("Updated user") : T("Created user"), name: u.name, detail: "" });
  }
  for (const p of Store.recon.peers) {
    const c = p.created_at || 0, m = p.modified_at || c;
    ev.push({ ts: m, kind: "peer", id: p.id, verb: m > c + 5 ? T("Updated peer") : T("Created peer"), name: p.title || p.name || T("unassigned peer"), detail: "" });
  }
  return ev.filter(e => e.ts).sort((a, b) => b.ts - a.ts);
}
export function recentActivity(n) {
  const src = (Store.events && Store.events.length) ? Store.events : synthEvents();
  return src.slice(0, n || 15).map(evDecorate);
}

// ═════════════════════════ panel-host service health ═════════════════════════
// Reads THIS host's own swg units from Store.panelServices (a server self-probe, cached ~20s server-side →
// essentially free) and turns them into "needs attention" records. Config-aware severity: a service that's
// intentionally inert (swg-sub while subscriptions are OFF) is NOT a fault. Only swg-sub down/missing WHILE
// subscriptions are ON is "critical" (the only thing that raises the on-load modal) — netctl/update matter
// only when you change settings or press Update, so they stay warnings. That keeps the modal meaningful
// instead of training people to Silence it. The panel host is one box, so these show regardless of the
// node filter. Purely additive: an older/docker panel reports {} → serviceIssues() returns [].
// Built on first use, like SVC_KINDWORD below — a module-level T() answers before loadLang() has run,
// which is how "Network & TLS helper" stayed English inside an otherwise Russian warning.
let _svcLabel = null;
export const SVC_LABEL = new Proxy({}, { get: (_, k) => (_svcLabel || (_svcLabel = { sub: T("Subscription server"), netctl: T("Network & TLS helper"), update: T("One-click self-update"), panel: T("Panel server"), awg: T("AmneziaWG datapath") }))[k] });
export const SVC_UNIT  = { sub: "swg-sub", netctl: "swg-netctl", update: "swg-update", panel: "swg-panel-server", awg: "" };
// Built on first use — T() only answers after loadLang() (same rule as ui.js's label tables).
let _svcKind = null;
export const SVC_KINDWORD = new Proxy({}, { get: (_, k) => (_svcKind || (_svcKind = { missing: T("not installed"), down: T("not running"), disabled: T("won’t survive a reboot"), unwritable: T("can’t be saved") }))[k] });
// The subscription server's CERTIFICATE, direct-TLS only. swg-sub keeps serving on its port without one, so
// the panel reports it healthy while every subscriber gets a TLS handshake failure (Cloudflare 525) — the
// failure is invisible from here unless we say it. The server sends {} under a reverse proxy: there the proxy
// terminates TLS and the cert is the admin's to manage, so there is nothing for us to assert. Independent of
// the systemd unit probe, which is why it lives in its own function — see serviceIssues.
function subCertIssue(out) {
  const sc = Store.subCert || {};
  if (!sc.needs_issue || !subFeatureOn()) return;
  out.push({ id: "subcert", sev: "critical", kind: sc.present ? "wrong" : "missing",
             label: T("Subscription certificate"), unit: SVC_UNIT.sub,
             msg: sc.present
               ? T("the subscription server's certificate doesn't match {v1}", { v1: T("{v1} — subscribers get a TLS error", { v1: sc.domain }) })
               : T("the subscription server has no certificate for {v1}", { v1: T("{v1} — subscribers get a TLS error", { v1: sc.domain }) }) });
}

// The panel could not persist its session-signing secret. Like subCertIssue this has its OWN source rather
// than the systemd probe, so it is just as true in a container — and it sits ABOVE the bare-metal early
// return for the same reason. Warn, not critical: sessions are lost, nothing else is.
function sessionKeyIssue(out) {
  const why = Store.sessionEphemeral;
  if (!why) return;
  out.push({ id: "sessionkey", sev: "warn", kind: "unwritable",
             label: T("Session key"), unit: SVC_UNIT.panel,
             msg: T("the panel can't save the key it signs sign-ins with ({v1}), so everyone is signed out whenever it restarts — its state directory is owned by another user", { v1: why }) });
}

export function serviceIssues() {
  const ps = Store.panelServices || {};
  // Not while the host is mid-convert / re-install / update: services legitimately stop and restart during
  // those, so the probe catches a real-but-transient gap and raises a CRITICAL modal for it — observed on a
  // docker→bare-metal convert, where swg-sub was down for seconds and the alert then outlived the cause by
  // hours. An operation in flight already has its own status surface; this one only adds noise to it.
  if (inProc(Store.hostProc)) return [];
  const out = [], add = (id, sev, kind, msg) => out.push({ id, sev, kind, msg, label: SVC_LABEL[id], unit: SVC_UNIT[id] });
  // EVERY check below this point reads Store.panelServices, which is a bare-metal systemd probe — a docker
  // panel reports {} and none of them can say anything. The CERTIFICATE check is the exception: it has its own
  // source (Store.subCert, from the panel's own view of the cert file) and is just as true in a container. It
  // used to sit below the early return, so enabling the server-side check for docker changed nothing visible —
  // the panel reported needs_issue and the SPA dropped it here, one line before it could be read.
  subCertIssue(out);
  sessionKeyIssue(out);
  if (!Object.keys(ps).length) return out;
  const gone = u => u && !u.present;
  const down = u => u && u.present && u.active !== "active";
  const unen = u => u && u.present && u.enabled && u.enabled !== "enabled" && u.enabled !== "static";
  const sub = ps.sub;
  if (sub && subFeatureOn()) {                         // only meaningful while subscriptions are enabled
    if (gone(sub))      add("sub", "critical", "missing", T("the subscription server isn’t installed — subscribers can’t load their configs"));
    else if (down(sub)) add("sub", "critical", "down", T("the subscription server isn’t running — subscribers can’t load their configs"));
    else if (unen(sub)) add("sub", "warn", "disabled", T("the subscription server won’t start again after a reboot"));
  }
  // The subscription server's CERTIFICATE, direct-TLS only. swg-sub keeps serving on its port without one, so
  // the panel reports it healthy while every subscriber gets a TLS handshake failure (Cloudflare 525) — the
  // failure is invisible from here unless we say it. The server sends {} under a reverse proxy: there the proxy
  // terminates TLS and the cert is the admin's to manage, so there is nothing for us to assert.
  const np = ps.netctl_path, nt = ps.netctl_timer;    // path OR timer covers the helper; collapse to one record
  if (gone(np) || gone(nt))       add("netctl", "warn", "missing", T("Panel URL and address changes can’t be applied until it’s restored"));
  else if (down(np) && down(nt))  add("netctl", "warn", "down", T("Panel URL and address changes can’t be applied right now"));
  else if (unen(np) || unen(nt))  add("netctl", "warn", "disabled", T("the network helper won’t start again after a reboot"));
  const up = ps.update;
  if (gone(up))      add("update", "warn", "missing", T("the one-click Update button won’t work (a manual update still will)"));
  else if (down(up)) add("update", "warn", "down", T("the one-click Update button won’t work right now"));
  else if (unen(up)) add("update", "warn", "disabled", T("one-click self-update won’t arm again after a reboot"));
  if (unen(ps.panel)) add("panel", "warn", "disabled", T("the panel won’t start again after a reboot"));   // it's answering → it's up; only reboot-survival matters
  const dp = (Store.datapath || {}).awg;               // local node's AmneziaWG kernel module — a broken DKMS build is what Update rebuilds
  // …but NOT while an update is running: the module legitimately isn't loaded while it is being rebuilt, and
  // raising CRITICAL then invites a SECOND update on top of the first — which is exactly what one operator did.
  // With the userspace fallback on the box the interfaces are UP, just slower — a warning, not a critical "can't come up".
  if (dp && dp.needed && !dp.ok && !dp.updating) {
    if (dp.fallback) add("awg", "warn", "fallback", T("AmneziaWG runs on the slower fallback datapath — its kernel module isn’t built or loaded; running Update rebuilds it"));
    else add("awg", "critical", "module", T("the AmneziaWG kernel module isn’t built or loaded — awg interfaces can’t come up; running Update rebuilds it"));
  }
  out.sort((a, b) => (b.sev === "critical") - (a.sev === "critical"));
  return out;
}
// Per-incident "Silence" — a localStorage set of "<id>:<kind>" keys the operator has hushed. Only the
// on-load MODAL respects it; the needs-attention ROW always shows. Auto-pruned to currently-live incidents,
// so a service that recovers then breaks again re-alerts.
export function svcKey(is) { return is.id + ":" + is.kind; }
export function svcSilencedSet() { try { return new Set(JSON.parse(localStorage.getItem("swg-svc-silence") || "[]")); } catch (_) { return new Set(); } }
export function svcSaveSilence(s) { try { localStorage.setItem("swg-svc-silence", JSON.stringify([...s])); } catch (_) {} }
export function svcSilence(is) { const s = svcSilencedSet(); s.add(svcKey(is)); svcSaveSilence(s); bus.emit(); }

// ═════════════════════════ SCREEN: ACTIVITY HISTORY ═════════════════════════
// The full operator-action log ("Show history" from the Overview feed): search + Item/Action filters,
// pagination, per-row delete, and Clear all. Pulls the whole capped log once and filters client-side with
// the same taxonomy (evDecorate) as the feed, so a row's icon / click target / category stay identical.
export const activityView = { q: "", item: "", action: "", page: 1 };
