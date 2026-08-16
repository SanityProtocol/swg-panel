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

import { isWdttIface, isCsqttIface, isSelfContainedIface, tkey } from "./util.js";
import { Store, bus } from "./store.js";
import { ifaceIsAwg, ifaceMatch, ifaceIsAll, nodeStale } from "./model.js";
import { go } from "./router.js";
import { statusLabel, Popover, Ic, Tag, inProc, setPendingSection } from "./ui.js";
import { subFeatureOn } from "./crypto.js";
import { T, plural, pluralWord } from "./i18n.js";
import { h } from "preact";
import { useState } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

export const peersView = { node: "", iface: "", q: "", sort: "status", dir: -1, status: null };
// Peers-screen status filter options (also the deep-link targets from grouped Needs-attention rows).
// The value is the internal status KEY (matched against p.status) and it never moves — persisted filters and
// deep-links point at it. The LABEL comes from statusLabel(), the panel's one status vocabulary, so the
// dropdown can never drift from the badges it filters (that includes the two display remaps: the access-revoke
// key `disabled` shows as Blocked, the DPI fault key `blocked` as Restricted).
export const PEER_STATUS_KEYS = ["", "online", "ready", "unassigned", "disabled", "expired", "expiring", "blocking",
  "restoring", "dangling", "broken", "partial", "blocked", "faulty", "pending", "unknown"];   // i18n-keys
export const peerStatusFilters = () => PEER_STATUS_KEYS.map(k => [k, k ? statusLabel(k) : T("All statuses")]);
// Prominent warning when the panel keeps no client configs at rest — QRs/downloads then only work
// in the session a peer is created, and existing peers can't be re-shared. Shown on Overview + Peers.

// <option>s for an interface dropdown: "All AmneziaWG" / "All WireGuard" shortcuts, then AmneziaWG / WireGuard
// optgroups of the individual interfaces (used everywhere we list ifaces; the caller renders "All interfaces").
// Type groups only matter when BOTH kinds are present — with one kind we list the interfaces flat (a group header
// or "All <type>" would just duplicate "All interfaces"). "All AmneziaWG" / "All WireGuard" appear only when both
// kinds exist AND there's more than one of that kind (otherwise they'd equal "All interfaces" or the lone iface).
export function ifaceOptGroups(names) {
  const wdtt = names.filter(isWdttIface);
  const csqtt = names.filter(isCsqttIface);
  const awg = names.filter(n => !isSelfContainedIface(n) && ifaceIsAwg(n));
  const wg = names.filter(n => !isSelfContainedIface(n) && !ifaceIsAwg(n));
  const groups = [["*awg", "AmneziaWG", awg], ["*wg", "WireGuard", wg], ["*wdtt", "WDTT", wdtt], ["*csqtt", "csqtt", csqtt]].filter(g => g[2].length);
  if (groups.length < 2) return html`${names.map(i => html`<option value=${i}>${i}</option>`)}`;   // one kind → flat list (an "All <type>" would just duplicate "All interfaces")
  // "All <type>" shortcut per kind (only when that kind has >1 — else it equals the lone iface), then a group per kind.
  return html`${groups.map(([val, label, arr]) => arr.length > 1 ? html`<option value=${val}>${T("All {v1}", { v1: label })}</option>` : null)}${groups.map(([, label, arr]) => html`<optgroup label=${label}>${arr.map(i => html`<option value=${i}>${i}</option>`)}</optgroup>`)}`;
}
// Shared node / interface FILTER <option> lists so the Peers / Users / Live toolbars behave identically:
//   0 available → a single "No nodes/interfaces" item · exactly 1 → that one (labelled, value=allVal so the list
//   stays unfiltered and it reads pre-selected) · ≥2 → "All nodes/interfaces" + each. `allVal` is the caller's
//   "all" sentinel ("" or "*").
export function nodeFilterOptions(allVal) {
  const ns = Store.nodes || [];
  if (!ns.length) return html`<option value=${allVal}>${T("No nodes")}</option>`;
  if (ns.length === 1) return html`<option value=${allVal}>${ns[0].name}</option>`;
  return html`<option value=${allVal}>${T("All nodes")}</option>${ns.map(n => html`<option value=${n.id}>${n.name}</option>`)}`;
}
export function ifaceFilterOptions(names, allVal) {
  if (!names.length) return html`<option value=${allVal}>${T("No interfaces")}</option>`;
  if (names.length === 1) return html`<option value=${allVal}>${names[0]}</option>`;
  return html`<option value=${allVal}>${T("All interfaces")}</option>${ifaceOptGroups(names)}`;
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
  online: ({ t }) => (t.observed && t.observed.handshake_age != null) ? t.observed.handshake_age : Infinity,
  rate: ({ t }) => t.observed ? (t.observed.rx_speed || 0) + (t.observed.tx_speed || 0) : 0,
  total: ({ t }) => t.observed ? (t.observed.rx_bytes || 0) + (t.observed.tx_bytes || 0) : 0,
};
export const PEER_DEFDIR = { status: -1, rate: -1, total: -1, online: 1, title: 1, user: 1, server: 1, address: 1, endpoint: 1 };   // first-click direction per column
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
  const s = freeze ? stableOrder(freeze + "|" + sort + "|" + dir, rows, r => r.p.id + "|" + tkey(r.t.node, r.t.iface), cmp)
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
export const usersView = { q: "", node: "", iface: "", page: 1, pageSize: 20, sort: "status", dir: -1, expanded: {} };   // node/iface filter the LIST (expand shows all peers)
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
    const o = t.observed; if (!o) continue;
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
  return Store.peersOfUser(u.id).some(p => p.targets.some(t => (!node || node === "*" || t.node === node) && ifaceMatch(t.iface, iface)));
}
// User-list sorting (clickable header). Callers hold sort/dir in their view-state under caller-chosen keys.
export const USER_SORT = {
  status: u => PEER_STATUS_RANK[u.status] || 0, name: u => (u.name || "").toLowerCase(),
  peers: u => u.peerCount || 0, online: u => u.onlineCount || 0,
  last: u => { const s = userStats(u.id); return s.last == null ? Infinity : s.last; },
  rate: u => { const s = userStats(u.id); return s.rx + s.tx; },
  total: u => { const s = userStats(u.id); return s.rxb + s.txb; },
  // by node count first, then the total distinct interfaces across those nodes (encoded: nodes×10000 + ifaces)
  nodes: u => { const nm = {}; let ifs = 0; for (const p of Store.peersOfUser(u.id)) for (const t of p.targets) { const s = nm[t.node] = nm[t.node] || new Set(); if (!s.has(t.iface)) { s.add(t.iface); ifs++; } } return Object.keys(nm).length * 10000 + ifs; },
};
export const USER_DEFDIR = { status: -1, peers: -1, online: -1, last: 1, rate: -1, total: -1, name: 1, nodes: -1 };
export function sortUsers(users, sort, dir, freeze) {
  const key = USER_SORT[sort] || USER_SORT.status;
  const cmp = (a, b) => ((x, y) => x < y ? -1 : x > y ? 1 : 0)(key(a), key(b)) * (dir || -1) || String(a.name).localeCompare(String(b.name));
  const s = freeze ? stableOrder(freeze + "|" + sort + "|" + dir, users, u => u.id, cmp) : users.slice().sort(cmp);
  return pinRecentlyCreated(s, u => u.id);   // a just-created user stays on TOP regardless of sort/freeze
}
export function sortColToggle(view, sk, dk, col, defdir) { if (view[sk] === col) view[dk] = -view[dk]; else { view[sk] = col; view[dk] = defdir[col] || 1; } }

// which Users page a user lands on (mirrors UsersScreen's sort; search is cleared before we navigate)
export function userPageOf(uid) {
  const users = sortUsers(Store.recon.users, usersView.sort, usersView.dir);
  const idx = users.findIndex(u => u.id === uid);
  return idx < 0 ? 1 : Math.floor(idx / (usersView.pageSize || 20)) + 1;
}
// Land on the Users screen at the PAGE where `userId` sits, expand that user's row and scroll it into view.
// Optionally glow a just-assigned peer's row (peerId). Shared by "click a username anywhere" and the assign
// flow (when it started on the Users screen).
export function revealUser(userId, peerId) {
  if (!userId) return;
  usersView.q = ""; usersView.expanded[userId] = true;
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
  if (!peer) return go("#/users");
  if (peer.user_id != null) { revealUser(peer.user_id, peer.id); return; }
  Store.recentlyCreated[peer.id] = Date.now(); go("#/users");
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
    if (!m[id]) m[id] = { name: p.unassigned ? "Unassigned" : (p.name || "(unnamed)"), count: 0, unassigned: !!p.unassigned, lastAge: null };
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
      return { title: p.title || p.name || "(peer)", user: p.unassigned ? "Unassigned" : (p.name || "(unnamed)"),
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
      return { title: p.title || p.name || "(peer)", user: p.unassigned ? "Unassigned" : (p.name || "(unnamed)"), ip: t.ip || "", unassigned: !!p.unassigned, lastAge: p.lastHandshakeAge }; })
    .sort(_byHandshake);
}

// Online users of a WDTT instance — the WDTT analogue of turnConnRows. A WDTT server owns its interface, so its
// peers attach by (node, iface) with no viaTurn hop; reconcile.js sets `online` on the wdtt target directly.
export function wdttConnRows(nodeId, iface) {
  const onT = (t) => t.node === nodeId && t.iface === iface && t.online;
  return (Store.recon.peers || []).filter(p => p.targets.some(onT))
    .map(p => { const t = p.targets.find(onT) || {};
      return { title: p.title || p.name || "(peer)", user: p.unassigned ? "Unassigned" : (p.name || "(unnamed)"), ip: t.ip || "", unassigned: !!p.unassigned, lastAge: p.lastHandshakeAge }; })
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
    return { peer,
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
  const row = n => {   // node name FIRST, then the glowing arrow(s)
    const p = h.peers.find(x => x.peer === n.id);
    const nameCls = p.in === "up" ? "mh-bold" : p.in === "down" ? "mh-dim" : "";
    return html`<div class="mh-row"><span class=${"mh-rn " + nameCls} style=${"color:" + Store.nodeColor(n.id)}>${n.name}</span><span class="mh-rar">${mhArrow("down", p.in)}${mode === "both" ? mhArrow("up", p.out) : null}</span></div>`;
  };
  const trigger = mode === "in"
    ? html`<span class="mh-tag mh-tag-hdr"><span class="mh-lbl-hdr">${T("This node's mesh status:")}</span> ${num(h.okIn, "mhn-down")}</span>`
    : html`<span class="mh-tag"><span class="nm-l">${T("Mesh")}</span><span class="mh-grp"><span class="mh-ar mh-down s-up">↓</span>${num(h.okIn, "mhn-down")}</span><span class="mh-grp"><span class="mh-ar mh-up s-up">↑</span>${num(h.okOut, "mhn-up")}</span></span>`;
  return html`<${Popover} cls="mh-pop" popCls="mh-bubble" alignRight=${true} trigger=${trigger}>
    <div class="onpop-h">${mode === "in" ? T("Inbound links") : T("Mesh connections")}</div>
    ${ordered.map(row)}
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
  const dflt = (c, w) => html`<span class="dot"></span><b class=${"oncount" + (c ? " on" : "")}>${c}</b> ${w || "user"}${c === 1 ? "" : "s"}`;
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
export const rangeLabel = k => ({ live: T("range|Live"), hour: T("range|Hour"), day: T("range|Day"), week: T("range|Week"), month: T("range|Month") }[k] || k);   // i18n-keys
export const rangeWord = k => (({ live: T("range|live"), hour: T("range|hour"), day: T("range|day"), week: T("range|week"), month: T("range|month") })[k] || T("range|live"));   // i18n-keys
export const dashState = { nodes: null, range: "live", peers: true, mesh: true, ov: {} };
(function () {
  try {
    const raw = JSON.parse(localStorage.getItem("swg-dash") || "{}");
    if (Array.isArray(raw.nodes) && raw.nodes.length) dashState.nodes = new Set(raw.nodes);   // ignore a stale empty selection → default to the whole fleet
    if (DASH_RANGES.some(r => r[0] === raw.range)) dashState.range = raw.range;
    if (typeof raw.peers === "boolean") dashState.peers = raw.peers;
    if (typeof raw.mesh === "boolean") dashState.mesh = raw.mesh;
    if (raw.ov && typeof raw.ov === "object") dashState.ov = raw.ov;
  } catch (_) {}
})();
export function dashSave() {
  try { localStorage.setItem("swg-dash", JSON.stringify({ nodes: dashState.nodes ? [...dashState.nodes] : null, range: dashState.range, peers: dashState.peers, mesh: dashState.mesh, ov: dashState.ov })); } catch (_) {}
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
  "Settings": T("event|Settings"), "Update": T("event|Update"),
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
export const SVC_KINDWORD = new Proxy({}, { get: (_, k) => (_svcKind || (_svcKind = { missing: T("not installed"), down: T("not running"), disabled: T("won’t survive a reboot") }))[k] });
export function serviceIssues() {
  const ps = Store.panelServices || {};
  if (!ps || !Object.keys(ps).length) return [];
  // Not while the host is mid-convert / re-install / update: services legitimately stop and restart during
  // those, so the probe catches a real-but-transient gap and raises a CRITICAL modal for it — observed on a
  // docker→bare-metal convert, where swg-sub was down for seconds and the alert then outlived the cause by
  // hours. An operation in flight already has its own status surface; this one only adds noise to it.
  if (inProc(Store.hostProc)) return [];
  const out = [], add = (id, sev, kind, msg) => out.push({ id, sev, kind, msg, label: SVC_LABEL[id], unit: SVC_UNIT[id] });
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
  const sc = Store.subCert || {};
  if (sc.needs_issue && subFeatureOn()) {
    out.push({ id: "subcert", sev: "critical", kind: sc.present ? "wrong" : "missing",
               label: T("Subscription certificate"), unit: SVC_UNIT.sub,
               msg: sc.present
                 ? T("the subscription server's certificate doesn't match {v1}", { v1: T("{v1} — subscribers get a TLS error", { v1: sc.domain }) })
                 : "the subscription server has no certificate for " + T("{v1} — subscribers get a TLS error", { v1: sc.domain }) });
  }
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
  if (dp && dp.needed && !dp.ok) add("awg", "critical", "module", T("the AmneziaWG kernel module isn’t built or loaded — awg interfaces can’t come up; running Update rebuilds it"));
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
