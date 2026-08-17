/* grids.js — the shared peer table.
 *
 * LAYER 8 (see docs/APP-JS-SPLIT-PLAN.md). Above sheets-crud, because a row opens one.
 *
 * PeerGrid is one row per (peer, target) DEPLOYMENT, not per peer, and it is deliberately the same
 * component everywhere it appears — the Peers screen, the Live monitor, a user's expanded grid and the
 * interface detail page — so a deployment reads identically wherever you meet it. `live` swaps the pill
 * badge for an animated dot and drops the row actions; `agg` adds the Server/IF column.
 *
 * It sits here rather than in views.js because it OPENS things: the peer view, the edit sheet, the QR
 * modal. views.js is layer 3 and derives rows; this renders them and acts on them.
 */

import { esc, tkey, seen, dur, fmtBytes } from "./util.js";
import { T } from "./i18n.js";
import { Store, api, useStore } from "./store.js";
import { targetType, nodeStale, ghostIface, ifaceIsAll, ifaceMatch, tgtXfer, tgtSeenAge } from "./model.js";
import {
  Ic, Tag, Badge, Dropdown, SearchBox, secTitle, footRow, Popover, toast, openModal, openConfirm,
  rowSingle, rowDouble, rowNoSelect, RowError, connDot, endpointCell, rateCell, xferCell, DepBadge,
  gridIfaceTag, gridStatusBadge, badgeWithReason, lifecycleIcon, statusLabel, dlul, rowError, statusReason,
  Portal,
} from "./ui.js";
import {
  peersView, sortPeerRows, peerSortBy, pageScroll, searchMatch, peerMatchesQ, ifaceOptGroups,
  nodeFilterOptions, ifaceFilterOptions, orphCount, OnlinePeersTag, revealUser,
  dashNodes, dashNodeOn, dashToggleNode,
} from "./views.js";
import {
  UserCombo, assignPeer, confirmUnassign, confirmDeletePeer, confirmRestoreDeployment,
  confirmCorrectDeployment, openRecreateRekey, peerBlockBtn,
} from "./peer-actions.js";
import { openPeerConfigs } from "./peer-ui.js";
import { openEditPeer, openPeerView } from "./sheets-crud.js";
import { h, Fragment } from "preact";
import { useState, useEffect, useRef } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// `live` (the Live monitor): status is the animated connDot (not the pill badge), an Endpoint column is added
// (turn peers show "Local turn-proxy"), the row actions + assign-to-user dropdown are dropped (read-only).
// `sort`/`dir`/`onSort` make every column header a clickable order-by.
export function PeerGrid({ rows, agg, node, iface, shownByPeer, q, blocked, hideUser, loc, live, sort, dir, onSort }) {
  const arrow = c => sort === c ? (dir < 0 ? "↓ " : "↑ ") : "";
  const th = (c, label, cls) => onSort ? html`<th class=${(cls ? cls + " " : "") + "clk"} onClick=${() => onSort(c)}>${arrow(c)}${label}</th>` : html`<th class=${cls || ""}>${label}</th>`;
  return html`<div class="tablewrap"><table class=${"peergrid" + (live ? " live" : "") + (loc ? " loc" : "")}>
    <thead><tr>${th("status", live ? "" : T("col|Status"), "h-status")}${loc
      ? html`${hideUser ? null : th("user", T("col|User"), "h-user")}${th("title", T("col|Title"), "h-title")}${live ? th("endpoint", T("col|Endpoint"), "h-ep") : null}${th("address", T("col|Address"), "h-addr")}${th("server", T("col|Node"), "h-node")}`
      : html`${hideUser ? null : th("user", T("col|User"), "h-user")}${th("title", T("col|Title"), "h-title")}${agg ? th("server", node === "*" ? T("col|Node") : T("col|IF"), "h-node") : null}${th("address", T("col|Address"), "h-addr")}${live ? th("endpoint", T("col|Endpoint"), "h-ep") : null}`
    }${th("online", T("col|Online"), "h-online")}${th("rate", T("col|Rate") + " ↓↑", "h-rate")}${th("total", T("col|Total") + " ↓↑", "h-total")}${live ? null : html`<th class="h-acts"></th>`}</tr></thead>
    <tbody>
      ${rows.length ? rows.map(({ p, t }) => {
        const obs = t.observed;
        const u = p.user_id ? Store.user(p.user_id) : null;
        const hidden = p.targets.filter(d => !(shownByPeer[p.id] || new Set()).has(tkey(d.node, d.iface)));   // this peer's deployments not shown in the grid
        const fresh = Store.recentlyCreated[p.id] && (Date.now() - Store.recentlyCreated[p.id] < 2500);   // just-created → one-shot glow
        const re = rowError("peer:" + p.id);   // pinned action failure → shown on the status hover bubble, not inline
        return html`<tr key=${p.id + "|" + tkey(t.node, t.iface)} data-peer=${p.id} class=${"clk" + (fresh ? " pcreate" : "")} title=${T("Double-click for QR / configs")} onMouseDown=${rowNoSelect} onClick=${e => rowSingle(e, () => openPeerView(p.id, t.node, t.iface))} onDblClick=${e => rowDouble(e, () => openPeerConfigs(p))}>
          <td data-label=${T("col|Status")} class="c-status">${(() => {
            const ifaceB = loc ? gridIfaceTag(t) : null;
            if (!live) return html`${gridStatusBadge(t, p, re)}${ifaceB}`;
            const dot = html`<span class=${"condot " + (t.status === "faulty" ? "faulty" : t.status === "blocked" ? "blocked" : t.online ? "on" : "off")}></span>`;
            if (re) {
              return html`<span class="turnwrap">${dot}${ifaceB}
                <span class="turnbub statusbub err"><span class="statusbub-h" style="color:var(--dangling)"><${Ic} i="err"/>${T("Error")}</span>${re.msg}</span></span>`;
            }
            // faulty / blocked → the "why" bubble on hovering the dot OR the interface badge (same as the peer-grid badge)
            if (t.status === "faulty" || t.status === "blocked") {
              return html`<span class="turnwrap">${dot}${ifaceB}
                <span class="turnbub statusbub"><span class="statusbub-h" style="color:var(--fault)"><${Ic} i="warn"/>${t.status === "blocked" ? T("status|Restricted") : T("status|Faulty")}</span>${statusReason(t.status)}</span></span>`;
            }
            return html`<span class=${"condot " + (t.online ? "on" : "off")} title=${t.online ? "online" : "offline"}></span>${ifaceB}`;
          })()}</td>
          ${(() => {
            const titleCell = html`<td data-label=${T("col|Title")} class="c-name">${lifecycleIcon(p, t.status)}${p.title ? html`<b>${p.title}</b>` : html`<span class="faint">${T("Untitled")}</span>`}</td>`;
            const addrCell = html`<td data-label=${T("col|Address")}><span class="addr">${t.ip || "—"}</span>${hidden.length ? html`<${DepBadge} others=${hidden}/>` : null}</td>`;
            const epCell = html`<td data-label=${T("col|Endpoint")}>${endpointCell(t)}</td>`;
            const nodeCell = html`<td data-label=${T("col|Node")}><div class="srvcell"><span class="srv-name" style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span></div></td>`;
            // The row's tooltip advertises "Double-click for QR / configs", but this cell is a SINGLE-click link to
            // the user — so it carries its own title, overriding the row's. A cell whose tooltip describes a
            // different action than the one it performs is worse than no tooltip.
            const userCell = hideUser ? null : html`<td data-label=${T("col|User")} class=${"usercell" + (u ? " linked" : "")}
              title=${u ? T("Click to open this user's details") : (live ? "" : T("Assign this peer to a user"))}
              onClick=${u ? (e => { e.stopPropagation(); revealUser(u.id); }) : (e => e.stopPropagation())}>
              ${u ? html`<a class="namecell" href="#/users" onClick=${e => { e.preventDefault(); e.stopPropagation(); revealUser(u.id); }}><span>${u.name}</span><${Ic} i="user"/></a>`
                  : (live ? html`<span class="faint">${T("status|Unassigned")}</span>` : html`<div class="assigncell"><${UserCombo} onPick=${uid => assignPeer(p, uid)}/></div>`)}</td>`;
            // embedded / live-peers: Status · [User] · Title · [Endpoint (live)] · Address · Node — iface badge sits by the status
            if (loc) return html`${userCell}${titleCell}${live ? epCell : null}${addrCell}${nodeCell}`;
            const srvAgg = agg ? html`<td data-label=${node === "*" ? T("col|Node") : T("col|IF")}><div class="srvcell">
              ${node === "*" ? html`<span class="srv-name" style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span>` : null}
              ${ifaceIsAll(iface) ? gridIfaceTag(t) : null}
            </div></td>` : null;
            return html`${userCell}${titleCell}${srvAgg}${addrCell}${live ? epCell : null}`;
          })()}
          <td data-label=${T("col|Online")} class="c-online"><span class="when">${seen(tgtSeenAge(t))}</span></td>
          ${(() => { const xf = tgtXfer(t); return html`
          <td data-label=${T("col|Rate")} class="c-rate">${rateCell(xf ? xf.rx_speed : 0, xf ? xf.tx_speed : 0)}</td>
          <td data-label=${T("col|Total")} class="c-total">${xferCell(...dlul(xf ? xf.rx_bytes : 0, xf ? xf.tx_bytes : 0))}</td>`; })()}
          ${live ? null : html`<td data-label="" class="rowacts" onClick=${e => e.stopPropagation()}>
            ${(() => { const gh = ghostIface(t.node, t.iface); return (gh && gh.ripe)
              ? html`<button class="iconbtn ghost" title=${T("Recreate & rekey — {iface} is gone with no recoverable key; recreate it fresh and reissue every client's config", { iface: t.iface })} onClick=${() => openRecreateRekey(t.node, t.iface)}><${Ic} i="refresh"/></button>`
              : t.restorable
                ? html`<button class="iconbtn restore" title=${T("Restore interface {iface} (recreate the missing interface with its original identity — recovers every peer on it)", { iface: t.iface })} onClick=${() => confirmRestoreDeployment(p, t)}><${Ic} i="refresh"/></button>`
                : t.correctable
                  ? html`<button class="iconbtn correct" title=${T("Fix address — {ip} is outside {iface}'s subnet", { ip: t.ip || "?", iface: t.iface })} onClick=${() => confirmCorrectDeployment(p, t)}><${Ic} i="check"/></button>`
                  : html`<button class="iconbtn qr" title=${T("Show QR / configs")} onClick=${() => openPeerConfigs(p)}><${Ic} i="qr"/></button>`; })()}
            <button class="iconbtn" disabled=${blocked} title=${blocked ? T("Unavailable while the node is down / converting") : T("Edit peer")} onClick=${() => openEditPeer(p, { node: t.node, iface: t.iface })}><${Ic} i="pencil"/></button>
            ${p.unassigned
              ? html`<button class="iconbtn danger" disabled=${blocked} title=${blocked ? T("Unavailable while the node is down / converting") : T("Delete peer")} onClick=${() => confirmDeletePeer(p)}><${Ic} i="trash"/></button>`
              : html`<button class="iconbtn danger" disabled=${blocked} title=${blocked ? T("Unavailable while the node is down / converting") : T("Unassign peer")} onClick=${() => confirmUnassign(p)}><${Ic} i="link"/></button>`}
          </td>`}</tr>`;
      }) : html`<tr><td colspan=${((agg || loc) ? 9 : 8) - (hideUser ? 1 : 0)} class="empty"><b>${q ? T("No matches") : T("No peers here")}</b>${q ? T("Try a different search.") : (!agg ? T("Create one, or copy an existing peer onto this interface.") : T("No peers deployed yet."))}</td></tr>`}
    </tbody></table></div>`;
}

// The sortable header line above a users list — same grid columns as .urow-head so the titles (which the rows no
// longer repeat inline) sit over their columns.
export function UsersHeader({ sort, dir, onSort, live }) {
  const arrow = c => sort === c ? (dir < 0 ? "↓ " : "↑ ") : "";
  const th = (c, label, cls) => html`<span class=${"clk" + (cls ? " " + cls : "")} onClick=${() => onSort(c)}>${arrow(c)}${label}</span>`;
  return html`<div class="uhead">
    <span></span>${th("status", T("col|Status"))}${th("name", T("col|User"))}
    <span class=${"u-right" + (live ? " live" : "")}>${th("peers", T("col|Peers"), "uh-pc")}${th("nodes", T("col|Nodes"), "uh-srv")}${th("last", T("col|Online"))}${th("rate", T("col|Rate") + " ↓↑", "uh-r")}${th("total", T("col|Total") + " ↓↑", "uh-r")}${live ? null : html`<span></span>`}</span>
  </div>`;
}

// A self-contained peers panel (toolbar + shared PeerGrid + pager) over a GIVEN peer set. Reused for the
// unassigned grid and each user's expanded grid, so they look/behave exactly like the Peers screen. The
// server / interface dropdown options are derived from the set itself (only servers/ifaces that have rows).
export function EmbeddedPeers({ peers, view, onNew, newLabel, hideUser, hideToolbar, collapse, live, onlineOnly, freezeKey }) {
  const [, force] = useState(0);
  const bump = () => force(x => x + 1);
  const nodeSet = new Set(), ifByNode = {};
  for (const p of peers) for (const t of p.targets) { nodeSet.add(t.node); (ifByNode[t.node] = ifByNode[t.node] || new Set()).add(t.iface); }
  const nodes = [...nodeSet].sort((a, b) => Store.nodeName(a).localeCompare(Store.nodeName(b)));
  const multiServer = nodes.length > 1;
  if (view.node && view.node !== "*" && !nodeSet.has(view.node)) view.node = "";
  if (!view.node) view.node = multiServer ? "*" : (nodes[0] || "*");
  // with no toolbar (a user's expanded grid) there's no way to change the filter, so always show ALL the
  // set's peers — never let a stale single-server view hide peers on another node.
  const node = hideToolbar ? "*" : view.node;
  const ifaceOpts = node === "*"
    ? [...new Set(Object.values(ifByNode).flatMap(s => [...s]))].sort()
    : [...(ifByNode[node] || [])].sort();
  const ifaceDefault = () => (node === "*" || ifaceOpts.length > 1) ? "*" : (ifaceOpts[0] || "*");
  if (!view.iface) view.iface = ifaceDefault();
  if (!ifaceIsAll(view.iface) && !ifaceOpts.includes(view.iface)) view.iface = ifaceDefault();
  const iface = hideToolbar ? "*" : view.iface;
  const agg = node === "*" || ifaceIsAll(iface);
  const q = (view.q || "").toLowerCase();

  let rows = [];
  const shownByPeer = {};
  if (collapse) {
    // one row PER PEER (a representative deployment); the peer's other interfaces surface as a +N badge
    for (const p of peers) {
      let ts = p.targets.filter(t => (node === "*" || t.node === node) && ifaceMatch(t.iface, iface));
      if (onlineOnly) ts = ts.filter(t => t.online);   // Online filter → only the peer's online deployments
      if (!ts.length) continue;
      if (!searchMatch((p.title || "") + " " + (p.name || "") + " " + p.targets.map(t => (t.ip || "") + " " + Store.nodeName(t.node) + " " + t.iface).join(" "), q)) continue;
      const rep = ts.slice().sort((a, b) => (b.online ? 1 : 0) - (a.online ? 1 : 0))[0];   // prefer an online deployment
      rows.push({ p, t: rep });
      shownByPeer[p.id] = new Set([tkey(rep.node, rep.iface)]);   // only the rep is "shown" → the rest become +N
    }
  } else {
    for (const p of peers) for (const t of p.targets) {
      if (node !== "*" && t.node !== node) continue;
      if (!ifaceMatch(t.iface, iface)) continue;
      if (onlineOnly && !t.online) continue;
      rows.push({ p, t });
    }
    if (q) rows = rows.filter(({ p, t }) => searchMatch((p.title || "") + " " + (p.name || "") + " " + (t.ip || "") + " " + Store.nodeName(t.node) + " " + t.iface, q));
    for (const { p, t } of rows) (shownByPeer[p.id] = shownByPeer[p.id] || new Set()).add(tkey(t.node, t.iface));
  }
  if (!view.sort) { view.sort = "status"; view.dir = -1; }
  // freeze the order so an edit/rotate (a status change) doesn't make the row jump out of view
  rows = sortPeerRows(rows, view.sort, view.dir, freezeKey ? freezeKey + "|" + node + "|" + iface : null);

  const pageSize = view.pageSize || 20;
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const page = Math.min(Math.max(1, view.page || 1), totalPages);
  const pageRows = rows.slice((page - 1) * pageSize, page * pageSize);
  const setPage = p => { view.page = p; bump(); };

  return html`<div class="peerspanel">
    ${hideToolbar ? null : html`<div class="toolbar sub">
      <${SearchBox} placeholder=${T("Search title, address…")} value=${view.q || ""} onInput=${e => { view.q = e.target.value; view.page = 1; bump(); }}/>
      ${multiServer ? html`<select class="selwrap" value=${node} onChange=${e => { view.node = e.target.value; view.iface = ""; view.page = 1; bump(); }}>
        <option value="*">${T("All nodes")}</option>${nodes.map(n => html`<option value=${n}>${Store.nodeName(n)}</option>`)}
      </select>` : null}
      ${ifaceOpts.length > 1 ? html`<select class="selwrap" value=${iface} onChange=${e => { view.iface = e.target.value; view.page = 1; bump(); }}>
        <option value="*">${T("All interfaces")}</option>${ifaceOptGroups(ifaceOpts)}
      </select>` : null}
      ${onNew ? html`<span class="grow"></span><button class="btn btn-primary btn-mini" onClick=${onNew}><${Ic} i="plus"/> ${newLabel || T("New peer")}</button>` : null}
    </div>`}
    <${PeerGrid} rows=${pageRows} agg=${agg} node=${node} iface=${iface} shownByPeer=${shownByPeer} q=${view.q} hideUser=${hideUser} loc=${collapse} live=${live} sort=${view.sort} dir=${view.dir} onSort=${c => { peerSortBy(view, c); view.page = 1; bump(); }}/>
    ${rows.length > pageSize ? html`<div class="pager">
      <label class="pager-size">${T("Rows per page")}
        <select class="selwrap" value=${pageSize} onChange=${e => { view.pageSize = +e.target.value; view.page = 1; bump(); }}>
          ${[20, 30, 50, 100].map(n => html`<option value=${n}>${n}</option>`)}
        </select></label>
      <span class="pager-info">${T("{from}–{to} of {total}", { from: (page - 1) * pageSize + 1, to: Math.min(page * pageSize, rows.length), total: rows.length })}</span>
      <button class="btn btn-ghost" disabled=${page <= 1} onClick=${e => { setPage(page - 1); pageScroll(e, -1); }}>${T("‹ Prev")}</button>
      <span class="pager-pg">${page} / ${totalPages}</span>
      <button class="btn btn-ghost" disabled=${page >= totalPages} onClick=${e => { setPage(page + 1); pageScroll(e, 1); }}>${T("Next ›")}</button>
    </div>` : null}
  </div>`;
}

// Quick node→node nav as a pinned SIDE RAIL — the exact Overview node rail (reused via NodesRailPanel), in nav
// mode: the current node highlighted, click navigates. Same markup/CSS as the dashboard's node selector.
// Once you scroll the dashbar out of view, the SAME node selector + range dock as a compact vertical rail pinned to the
// right edge, vertically centred and travelling with the scroll. It shrinks further when the pointer leaves it (a "peek")
// and grows back on hover; scrolling back to the top slides it away and the inline dashbar takes over again. Self-contained
// scroll state (rAF-throttled, no-op when the boolean doesn't flip) so it never taxes the poll path.
// The node rail panel — shared by the Overview rail (nav=false: toggle a node in/out of the dashboard) and the
// node/interface-detail rail (nav=true: jump to a node). Identical markup/CSS; only the per-row behaviour differs.
export function NodesRailPanel({ nav, active }) {
  const ns = Store.nodes || [];
  return html`<div class="railpanel railmenu railmenu-nodes">
    ${ns.map(n => {
      const down = Store.recon.nodeStatus[n.id] !== "live";
      const on = nav ? (n.id === active) : dashNodeOn(n.id);
      const cls = "railmenu-b node" + (on ? " on" : (nav ? "" : " off")) + (down ? " down" : "");
      const styl = "--c:" + Store.nodeColor(n.id);   // on the button so BOTH the dot glow and the selected name can use the node colour
      const inner = html`<span class="railmenu-ic"><span class="railnode-dot"></span></span><span class="railmenu-t">${n.name}</span>`;
      if (!nav)
        return html`<button key=${n.id} class=${cls} style=${styl} onClick=${() => dashToggleNode(n.id)} title=${(on ? "Hide " : "Show ") + n.name + (down ? " · not reporting" : "")}>${inner}</button>`;
      return on
        ? html`<span key=${n.id} class=${cls} style=${styl} title=${n.name + (down ? " · not reporting" : "")}>${inner}</span>`
        : html`<a key=${n.id} class=${cls} style=${styl} href=${"#/node/" + encodeURIComponent(n.id)} title=${(down ? "Down — " : "Go to ") + n.name}>${inner}</a>`;
    })}
  </div>`;
}

export function NodeRail({ active }) {
  if ((Store.nodes || []).length < 2) return null;
  // Render at <body> (Portal) so the fixed rail escapes the .screen "rise" transform — otherwise a fixed child of a
  // transformed ancestor is positioned relative to THAT ancestor and rides the 0.32s enter animation into place.
  return html`<${Portal}><div class="dashrail noderail"><div class="dashrail-stack">
    <${NodesRailPanel} nav=${true} active=${active}/>
  </div></div><//>`;
}
