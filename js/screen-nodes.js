/* screen-nodes.js — the fleet: the node list, one node's page, its health and its updates.
 *
 * LAYER 10 (see docs/APP-JS-SPLIT-PLAN.md). A screen: nothing imports it except the router table.
 *
 * The host/node update lifecycle lives here rather than in app.js because the pill that reports it IS a
 * node card. hostUpdating/pendingUpdateDone/seenPanelVer are module-level on purpose: an update outlives
 * the component that started it — the panel restarts mid-update on a master — so the state has to sit
 * above any mount.
 */

import { $, esc, seen, dur, ago, rate, fmtBytes, niceScaleCeil, tkey, ipOf, portOf, isWdttIface, isCsqttIface } from "./util.js";
import { Store, api, bus, useStore } from "./store.js";
import { go } from "./router.js";
import { pickThemed, NODE_COLOR_DEFAULT, toThemed, themeMode } from "./theme.js";
import { kindOf, iTypeOf, targetType, nodeStale, ifaceNotUp, wdttOn, ghostIface, ghostPeers, turnDown,
         turnProxiesFor, ifaceIsAwg } from "./model.js";
import { turnFork, turnLabel, turnColor, turnForkList, forkProduct } from "./turn-catalog.js";
import {
  Ic, ICON, Tag, Panel, Badge, StatusTag, CmdErr, Sheet, footRow, secTitle, SearchBox, Switch, Dropdown,
  Popover, Portal, toast, copy, mutate, openModal, pushModal, closeModal, openConfirm, ConfirmSheet,
  opTag, procTag, inProc, procFailed, procSuccess, procAborted, isUpdateState, procInClass,
  dismissNodeProc, dismissHostProc, statusLabel, LogBody, logRaw, useReorder, GRIP_SVG,
  orderById, rowSingle, rowDouble, rowNoSelect, RowError, goSettings, ifaceReady, ifaceWasBusy,
  trackIfaceOps, StoreOffBanner, ifaceColor, dlul, ifopBusy, applyThemeMode, paintThemeBtn,
} from "./ui.js";
import { T, Tsplit, plural, srvText } from "./i18n.js";
import { Sparkline, MiniArea, MultiRing, RingLegend, TrendArea, TrendSpark, RankBars, RangeTabs,
         RangedHistory, ThroughputChart, OnlineBlocks, cpuColor, histTime, ChartHover, IfaceThroughput,
         RANGE_CAP } from "./charts.js";
import { orphCount, OnlinePeersTag, OnlineUsersTag, MeshStat, meshHealth, onlineUserRows, onlinePeerRows,
         serviceIssues, recentActivity, evItem, evAction, evClick, evDecorate, dashState, DASH_RANGES } from "./views.js";
import { TurnProxiesBlock, turnEnabled, WdttCard, WDTT_COLOR, ForkTag, ifaceTurnBadges, openEditWdtt, openEditCsqtt,
         openSetupTurn, wdttRecreateFresh, wdttRestoreIdentity } from "./turn.js";
import { PeerGrid, NodeRail, NodesRailPanel } from "./grids.js";
import { IgnoredIfacesCard, openOnboardIface, openEditIface, openConnectionEdit, OrphanRow,
         AdoptIfaceSheet, AdoptDormantWdttSheet } from "./iface.js";
import { openNodeCreate, openNodeEdit, openNodeRemove, openNodeRecover, openNodeRotate, unflagNode } from "./sheets-crud.js";
import { confirmRestoreInterface, confirmRestoreAllInterfaces, openRecreateRekey } from "./peer-actions.js";
import { h, Fragment } from "preact";
import { useState, useEffect, useRef, useMemo } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

/* Update-dialog prose. Each is ONE sentence with bold runs inside it; {side} is "node's" / "panel's", which
   is itself translated, so the whole thing has to be one key rather than a phrase built around a variable. */
function fullUpdateIntro(side) {
  const [a, b] = Tsplit("For a {what} — including third-party components (docker / wg-awg / turn-proxies) — run this on the {side} box:", "what", { side });
  return html`<${Fragment}>${a}<b>${T("full, controlled update")}</b>${b}<//>`;
}
function autoUpdateIntro(side) {
  const one = T("For an {what}, press {press} below. This also {repairs} the {side} box — reinstalls anything missing, re-enables services, and rebuilds the datapath (e.g. the AmneziaWG kernel module) — so it's worth running even when you're already up to date.", { side });
  const [a, r1] = [one.split("{what}")[0], one.split("{what}").slice(1).join("{what}")];
  const [b, r2] = [r1.split("{press}")[0], r1.split("{press}").slice(1).join("{press}")];
  const [c, d] = [r2.split("{repairs}")[0], r2.split("{repairs}").slice(1).join("{repairs}")];
  return html`<${Fragment}>${a}<b>${T("automatic update of SWG components only")}</b>${b}<b>${T("Update now")}</b>${c}<b>${T("repairs")}</b>${d}<//>`;
}
function updatedFromTo(from, to) {
  const one = T("The panel was updated from {from} to {to}.");
  const [a, r1] = [one.split("{from}")[0], one.split("{from}").slice(1).join("{from}")];
  const [b, c] = [r1.split("{to}")[0], r1.split("{to}").slice(1).join("{to}")];
  return html`<${Fragment}>${a}<b>v${from}</b>${b}<b>v${to}</b>${c}<//>`;
}
function entryServersRun() {
  const [a, b] = Tsplit("All servers run {daemon}, which syncs to this panel over HTTPS — the node needs no inbound access.", "daemon");
  return html`<${Fragment}>${a}<span class="mono">swg-noded</span>${b}<//>`;
}

/* "The node no longer reports X. <verdict>, so …" — the verdict is COLOURED (green if the key survives, red
   if it doesn't), so it cannot be one text node. One key with a {verdict} marker, split around the span. */
function goneSentence(text, ok, verdict) {
  const [before, after] = [text.split("{verdict}")[0], text.split("{verdict}").slice(1).join("{verdict}")];
  return html`<${Fragment}>${before}<span class=${ok ? "mi-ok" : "mi-bad"}>${verdict}</span>${after}<//>`;
}

export function HealthDot({ issues }) {
  if (!issues || !issues.length) return null;
  const n = issues.length;
  const trigger = html`<span class="badge b-issue ic"><${Ic} i="warn"/>${n} issue${n > 1 ? "s" : ""}</span>`;
  return html`<${Popover} cls="onlinetag bare healthpop" trigger=${trigger}>
    <div class="onpop-h">${T("{v1} on this node", { v1: plural(n, "issue") })}</div>
    ${issues.map(it => html`<div class="onrow hrow"><span class="on-name">${it}</span></div>`)}
  </${Popover}>`;
}
export function NodeDetail({ node: rawName }) {
  const name = decodeURIComponent(rawName);   // `name` is the node id (the connector); display uses dname
  const node = Store.node(name);
  const nrec = Store.nodes.find(x => x.id === name) || {};   // full record carries health
  const meta = Store.describe[name] || null;       // interface meta from the consolidated state
  const metaErr = node && !meta;

  // if a node we were viewing gets removed (force-remove, or a flagged node that signed off), bounce
  // to the Nodes list instead of stranding the operator on a dead detail page. A node that was never
  // here (stale link) just shows the message below.
  const seenRef = useRef(false);
  useEffect(() => { if (node) seenRef.current = true; else if (seenRef.current) go("#/nodes"); }, [node]);

  // split the node's interfaces: USER interfaces (operator-created) vs SYSTEM mesh links (node↔node connections).
  // System ifaces are EXCLUDED from the user list by BOTH the reported `system` flag AND the reserved name
  // prefix — a mesh iface mid-delete loses its override flag but keeps its swg_ name, so it must never leak
  // onto the User-interfaces screen as a card.
  const meshPfx = (nrec.mesh_prefix || (Store.panelSettings || {}).reserved?.iface_prefix || "swg_");
  const isSysName = k => k.startsWith(meshPfx) || k.startsWith("swg_");
  const isSysIface = k => (meta[k] && meta[k].system) || isSysName(k);
  const userKeys = meta ? Object.keys(meta).filter(k => !isSysIface(k)) : [];
  // drag-to-reorder the (user) interface cards — the saved order overlays the node's reported set, and
  // WDTT-owned interfaces reorder alongside the wg/awg ones (same "User interfaces" grid, so one order).
  // `gone` keeps an interface being deleted in the list until the node stops reporting it, so its
  // "deleting" card holds the SLOT the live card had: without it the name left ifaceIds the moment its
  // server died and the card re-rendered outside the ordered grid — jumping to the top mid-teardown.
  const ifaceIds = nodeIfaces(name, { gone: true }).map(x => x.ifn);
  const ifReorder = useReorder(ifaceIds, ids => mutate({
    patch: s => { const nn = (s.nodes || []).find(x => x.id === name); if (nn) nn.iface_order = ids; },
    call: () => api.saveOrder({ kind: "iface", node: name, order: ids }),
  }));

  if (!node) return html`<div class="screen"><div class="crumb"><a href="#/nodes">${T("col|Nodes")}</a><span class="sep">/</span><b>${name}</b></div>
    <div class="empty"><b>${T("Unknown server")}</b>${T("this server isn't in the fleet.")}</div></div>`;
  const dname = node.name || name;

  const live = Store.recon.nodeStatus[name] === "live";
  const blocked = !live || inProc(nrec.proc_status);   // node down or mid convert/re-install → only recovery actions (rotate key, delete) stay enabled (a timed-out/failed tag doesn't block)
  const down = !live && !inProc(nrec.proc_status);      // genuinely not reporting (not just mid-convert) → offer one-click Recover in place of rotate-token
  const dhUpdating = nrec.updating || (nrec.local && (hostUpdating || inProc(Store.hostProc) || inProc(nrec.proc_status)));  // the dh-ver pill already shows "updating…" — so suppress a duplicate "updating" proc-tag next to the title
  const snap = Store.stats[name];
  // turn-proxies present (installed, a pending install, or onboarding) → show the Turn-proxies block;
  // none → hide that block and surface a "Setup turn-proxy" button in the Interfaces header instead.
  const hasTurns = !!((snap && (snap.turn_proxies || []).length) || Object.keys(nrec.turn_pending || {}).length || (nrec.turn_onboarding || []).length);
  const wdttIfaces = (snap && snap.wdtt || []).filter(w => w && w.iface);   // WDTT-owned userspace-WG interfaces → shown (flagged) in the interfaces section too
  const hasWdtt = wdttIfaces.length > 0;   // WDTT forks are self-contained turn-family servers → also shown in the Turn-proxies section
  const csqttIfaces = (snap && snap.csqtt || []).filter(c => c && c.iface);   // csqtt-owned raw-TUN interfaces → shown (flagged) in the interfaces section too, like WDTT
  const hasCsqtt = csqttIfaces.length > 0;   // csqtt: self-contained raw-TUN turn server → also shown in the Turn-proxies section
  // nothing for a turn-proxy to forward to → do not offer to create one (see TurnProxiesBlock)
  const canFrontTurn = userKeys.some(k => (meta[k] || {}).listen_port);
  const here = Store.recon.peers.filter(p => p.targets.some(t => t.node === name));
  const onl = here.filter(p => p.targets.some(t => t.node === name && t.online)).length;
  let nrx = 0, ntx = 0; if (snap) for (const blk of Object.values(snap.interfaces || {})) for (const pp of blk.peers || []) { nrx += pp.rx_speed || 0; ntx += pp.tx_speed || 0; }
  if (snap) for (const w of (snap.wdtt || [])) { nrx += w.rx_speed || 0; ntx += w.tx_speed || 0; }   // include WDTT interface throughput in the node-card total
  if (snap) for (const c of (snap.csqtt || [])) { nrx += c.rx_speed || 0; ntx += c.tx_speed || 0; }   // include csqtt interface throughput too
  let syncTxt = T("no snapshot yet");
  if (snap && snap.generated_at) { const a = Math.floor(Date.now() / 1000 - snap.generated_at); syncTxt = live ? T("{ago} ago", { ago: seen(a) }) : T("stale for {ago}", { ago: seen(a) }); }

  return html`<div class="screen">
    <${NodeRail} active=${name}/>
    <div class="crumb"><a href="#/nodes">${T("col|Nodes")}</a><span class="sep">/</span><b>${dname}</b></div>
    <div class="detail-head">
      <div class="title">${(nrec.outdated || (nrec.local && Store.panelOutdated)) && !nrec.updating ? html`<span class="upd-dot" title=${T("Update available")}><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 4v4h-4"/></svg></span>` : null}<h1>${dname}</h1>${nrec.kind ? html`<span class=${"tport " + nrec.kind}>${nrec.kind === "docker" ? T("kind|docker") : T("kind|bare-metal")}</span>` : null}${nrec.uninstalled ? html`<span class="nstat uninst"><${Ic} i="info"/> ${T("tag|uninstalled")}</span>` : live ? html`<span class="reporting">${T("reporting")}</span>` : nrec.status === "dangling" ? html`<span class="nstat enroll"><${Ic} i="clock"/> ${T("awaiting enroll")}</span>` : html`<span class="nstat stale"><${Ic} i="info"/> ${T("stale")}</span>`}${nrec.proc_status && !isUpdateState(nrec.proc_status) ? procTag(nrec.proc_status, () => dismissNodeProc(nrec.id), nrec.proc_err, !live && nrec.status === "dangling") : null}<${HealthDot} issues=${nrec.issues}/></div>
      <div class="grow"></div>
      <div class="dh-ver">
        ${nrec.version && !nrec.uninstalled ? html`<span class=${"nm-ver" + (nrec.ahead ? " out" : "")} title=${nrec.ahead ? T("Node is running a newer version than the panel — update the panel to catch up") : ""}>v${nrec.version}</span>` : null}
        ${nrec.uninstalled ? null : dhUpdating ? html`<span class="livepill upd-busy">${T("updating…")} <svg class="updspin" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 4v4h-4"/></svg></span>`
          : (nrec.proc_status && isUpdateState(nrec.proc_status)) ? procTag(nrec.proc_status, () => dismissNodeProc(nrec.id), nrec.proc_err)
          : (nrec.local && Store.panelOutdated) ? html`<button class="livepill updpill" disabled=${blocked} onClick=${() => updateHost()} title=${T("Update this master (panel + co-located node) to the latest release")}>${T("update to")} <b>${Store.latestRemote || "?"}</b></button>`
          : nrec.outdated ? html`<button class="livepill updpill" disabled=${blocked} onClick=${() => updateNode(nrec)} title=${blocked ? T("Unavailable while the node is down / converting") : T("Update this node")}>${T("update node to")} <b>${nrec.latest || "?"}</b></button>`
          : nrec.repairable ? html`<button class="livepill updpill fixpill" disabled=${blocked} onClick=${() => nrec.local ? updateHost() : updateNode(nrec)} title=${(nrec.kind === "docker" ? T("A container or the datapath isn't running on this node — recreating it should fix it. ") : T("The AmneziaWG kernel module isn't built or loaded on this node — awg interfaces can't come up. ")) + (nrec.local ? T("Re-run the updater to repair.") : T("Update this node to repair."))}><${Ic} i="warn"/> ${T("repair node")}</button>`
          : (nrec.local ? (Store.updFlash && Date.now() < Store.updFlash) : (Store.nodeUpdFlash && Store.nodeUpdFlash.id === nrec.id && Date.now() < Store.nodeUpdFlash.until))
          ? html`<span class="livepill upd-uptodate" title=${nrec.local ? T("This master is on the latest version") : T("This node is on the latest version")}><${Ic} i="check"/> ${T("up to date")}</span>`
          : html`<button class="iconbtn" disabled=${blocked} title=${blocked ? T("Unavailable while the node is down / converting") : T("Check status")} onClick=${e => checkForUpdate(e, nrec.local ? undefined : nrec.id)}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 4v4h-4"/></svg></button>`}
        <span class="dh-sep"></span>
        <button class="iconbtn" disabled=${blocked} title=${blocked ? T("Unavailable while the node is down / converting") : T("Node settings")} onClick=${() => openNodeEdit(nrec)}><${Ic} i="gear"/></button>
        ${down ? null : html`<button class="iconbtn" title=${T("Rotate token (re-enroll / re-install)")} onClick=${() => openNodeRotate(nrec)}><${Ic} i="key"/></button>`}
        <button class="iconbtn danger" title=${nrec.removing ? T("Force remove node") : T("Remove node")} onClick=${() => openNodeRemove(nrec)}><${Ic} i="trash"/></button>
        ${down ? html`<button class="iconbtn recover" title=${T("Recover this node — rotate its token and get a fresh paste-on-the-server install command (the node keeps its peers)")} onClick=${() => openNodeRecover(nrec)}><${Ic} i="key"/> ${T("tag|recover")}</button>` : null}
      </div>
    </div>

    ${!snap ? html`<div class="node-nodata"><${Ic} i="activity"/><p>${T("This node isn't sending any data right now")}</p></div>` : html`<div class="noderibbon">
      <div class="nr-tags">
        ${nodeIfaces(name).map(x => IfaceTag(name, x))}
        ${turnEnabled() ? nodeTurns(name).map(tp => TurnTag(name, tp)) : null}
      </div>
      <span class="grow"></span>
      <div class="nr-sync"><span class="when">${syncTxt}</span>${nrec.health && nrec.health.uptime != null ? html`<span class="when">up ${dur(nrec.health.uptime)}</span>` : null}</div>
    </div>

    ${nrec.health ? html`<${NodeHealthPanel} name=${name} nrec=${nrec}/>` : null}

    ${nrec.health_history ? html`<${NodeThroughput} name=${name} nrec=${nrec}/>` : null}

    ${(nrec.mesh_peers || []).length ? html`<${Panel} icon="network" title=${T("Node connections")} tone="pending" count=${(nrec.mesh_peers || []).length}
        actions=${html`<${MeshStat} nodeId=${name} mode="in"/>`}>
      <div class="ifgrid">${[...(nrec.mesh_peers || [])].sort((a, b) => Store.nodeName(a.peer).localeCompare(Store.nodeName(b.peer))).map(mp => {
        const peer = mp.peer;
        const ifn = mp.iface;
        const m = (ifn && meta) ? meta[ifn] : null;   // reported stats for the link's CURRENT iface (absent mid-rebuild)
        const col = Store.nodeColor(peer);
        const reprov = !!mp.reprovisioning || (!!ifn && !m);   // staged create, or iface not reported yet → re-provisioning
        // link health → one glowing dot: green up (recent handshake) · amber connecting (never handshook)
        // · red down (handshook then went stale, or the node itself is dark). reprov takes over the card.
        const lk = reprov ? "reprov" : nodeStale(name) ? "down" : (!m || m.handshake_age == null ? "connecting" : (m.handshake_age < 180 ? "up" : "down"));
        const lkTitle = { up: T("Link up"), connecting: T("Connecting…"), down: T("Link down") }[lk];
        const muted = lk === "down" || reprov;
        const carried = reprov ? [] : userKeys.filter(k => meta[k].egress_mode === "forward" && meta[k].egress_node === peer);   // user iface NAMES forwarded whole (cascade) out through THIS link
        const smartCarried = reprov ? [] : userKeys.filter(k => meta[k].egress_mode === "smart" && (meta[k].routing || []).some(r => r.action === "exit" && r.node === peer));   // ifaces SMART-routing some destinations out via THIS link
        const canOpen = !reprov && !!ifn && !blocked;   // node unavailable (converting / down / mid-proc) → dim + not editable, matching the interface/turn cards
        return html`<div key=${peer} class=${"ifcard tp" + (canOpen ? " clickable" : "") + (muted ? " down" : "") + (blocked ? " locked" : "")} onClick=${canOpen ? () => openConnectionEdit(name, ifn) : null}>
          <div class="ifcard-top"><span class="iftype turn" style=${"--tfc:" + col}><${Ic} i="server"/></span><span class="ifname">${Store.nodeName(peer)}</span><span class="grow"></span>${smartCarried.length ? html`<span class="egb egb-smart" title=${T("Smart cascade: routes selected destinations out via {node}", { node: Store.nodeName(peer) })}><${Ic} i="cascade"/>${T("smart cascade")}</span>` : carried.length ? html`<span class="egb egb-cascade" title=${T("Cascade: relays {v1} out via {v2}", { v1: plural(carried.length, "interface"), v2: Store.nodeName(peer) })}><${Ic} i="cascade"/>${T("tag|cascade")}</span>` : null}${reprov ? html`<span class="tg tg-busy" title=${T("Rebuilding this node's mesh link — it reconnects in a few seconds")}><${Ic} i="clock"/>${T("tag|re-provisioning")}</span>` : html`<span class=${"lkdot " + lk} title=${lkTitle}></span>`}</div>
          <div class="ifcard-rows">
            <div class="ifrow"><span class="l">${T("col|Endpoint")}</span><span class="r addr">${(m && m.peer_endpoint) || "—"}</span></div>
            <div class="ifrow"><span class="l">${T("Tunnel")}</span><span class="r addr">${(m && m.subnet) || "—"}</span></div>
            ${carried.length ? html`<div class="ifrow"><span class="l">${T("Carrying")}</span><span class="r"><span class="carry-tags">${carried.map(k => html`<span class=${"tg tg-" + ((meta[k].awg_params && Object.keys(meta[k].awg_params).length) ? "awg" : "wg")}>${k}</span>`)}</span></span></div>` : null}
          </div></div>`;
      })}</div>
    <//>` : null}

    <${Panel} icon="globe" title=${T("User interfaces")} tone="ready" count=${userKeys.length + wdttIfaces.length + Object.keys(nrec.wdtt_cfg || {}).filter(ifn => !wdttIfaces.some(w => w.iface === ifn)).length + csqttIfaces.length + Object.keys(nrec.csqtt_cfg || {}).filter(ifn => !csqttIfaces.some(c => c.iface === ifn)).length}
        actions=${html`<${Fragment}>${(() => { const mr = Object.values(nrec.missing_ifaces || {}).filter(mi => mi && mi.ripe).length; return mr ? html`<button class="btn btn-mini restore" title=${T("Recreate this node's missing interfaces with their original identities — node-rebuild recovery")} onClick=${() => confirmRestoreAllInterfaces(name)}><${Ic} i="refresh"/> Restore ${mr > 1 ? T("{v1} interfaces", { v1: mr }) : "interface"}</button>` : null; })()}${turnEnabled() && nrec.turn_manage && !hasTurns && !hasWdtt && !hasCsqtt && canFrontTurn ? html`<button class="btn btn-mini" disabled=${blocked || nrec.turn_arch_ok === false} title=${blocked ? T("Unavailable while the node is down / converting") : nrec.turn_arch_ok === false ? T("No turn-proxy build for this node's architecture{arch} — only amd64 and arm64 are supported.", { arch: nrec.arch ? " (" + nrec.arch + ")" : "" }) : T("Set up the node's first turn-proxy")} onClick=${() => openSetupTurn(name)}><${Ic} i="plus"/> ${T("Setup turn-proxy")}</button>` : null}<button class="btn btn-mini ico" title=${T("Interface defaults in Settings → Interfaces")} onClick=${() => goSettings("defaults")}><${Ic} i="gear"/></button><button class="btn btn-mini" disabled=${blocked} title=${blocked ? T("Unavailable while the node is down / converting") : ""} onClick=${() => openOnboardIface(name)}><${Ic} i="plus"/> ${T("Create new interface")}</button><//>`}>
      ${(() => {
        // server-side pending (no data yet): the simple "waiting…" chip. creating → wg/awg tag; onboarding → "load".
        const pcard = (ifn, label, type) => html`<div class="ifcard pending" key=${label + ":" + ifn}>
          <div class="ifcard-top"><span class=${"iftype " + (type || "turn")}>${type || "load"}</span><span class="ifname">${ifn}</span><span class="grow"></span><${CmdErr} err=${(nrec.cmd_errors || {})[ifn]}/><${StatusTag} cls="tg-busy" icon="clock" label=${label} title=${T("Setting it up on the node")}/></div>
          <div class="ifcard-rows"><div class="ifrow"><span class="l faint">${label === "creating" ? T("the node is creating it…") : T("the node is adding it…")}</span><button class="btn btn-mini warn" title=${T("Drop this pending request")} onClick=${() => mutate({ key: "ifcancel:" + name + "|" + ifn, call: () => api.ifaceCancel({ node: name, iface: ifn }) })}>${T("Cancel")}</button></div><${RowError} k=${"ifcancel:" + name + "|" + ifn}/></div></div>`;
        // client-optimistic create: the FULL card with the values just entered, dimmed + "creating" + × in the
        // header — identical layout to the turn-proxy optimistic card. Shown until the node reports the iface.
        const optIfCard = (ifn, e) => html`<div class="ifcard down" key=${"new:" + ifn}>
          <div class="ifcard-top"><span class=${"iftype " + (e.type || "turn")}>${e.type || "load"}</span><span class="ifname">${ifn}</span><span class="grow"></span><${CmdErr} err=${(nrec.cmd_errors || {})[ifn]}/><${StatusTag} cls="tg-busy" icon="clock" label=${e.type ? "creating" : "onboarding"} title=${T("Setting it up on the node")}/><button class="xbtn" title=${T("Cancel this request")} onClick=${() => { delete Store.ifaceNew[name + "|" + ifn]; mutate({ key: "ifcancel:" + name + "|" + ifn, call: () => api.ifaceCancel({ node: name, iface: ifn }) }); }}><${Ic} i="x"/></button></div>
          <div class="ifcard-rows">
            ${(e.endpoint || e.port) ? html`<div class="ifrow"><span class="l">${T("Listen")}</span><span class="r addr">${(e.endpoint || "") + (e.port ? ":" + e.port : "") || "—"}</span></div>` : null}
            ${e.subnet ? html`<div class="ifrow"><span class="l">${T("Subnet")}</span><span class="r addr">${e.subnet}</span></div>` : null}
            <${RowError} k=${"ifcancel:" + name + "|" + ifn}/></div></div>`;
        // DELETING card — the optimistic card for a teardown in flight. Same chrome as the live card it
        // replaces (so the grid doesn't jump), but inert: no pencil, no drag grip, not a link, and no × —
        // unlike a create, a delete already executing on the node isn't cancellable.
        // Rows come from the marker captured at Delete, NOT from the live maps: a WDTT server leaves snap.wdtt
        // the instant its process dies, so reading them here rendered the card as a green "wg" with empty rows
        // for the rest of the teardown. Live data is only the fallback (e.g. a marker from an older tab).
        const delCard = (ifn, g) => { const _m = (meta && meta[ifn]) || {};
          const _w = wdttIfaces.find(w => w.iface === ifn);
          const _t = g.type || (_w ? "wdtt" : (_m.awg_params && Object.keys(_m.awg_params).length) ? "awg" : "wg");
          const _port = _w ? String(_w.listen || "").split(":").pop() : "";
          return html`<div class=${"ifcard pending down"} key=${"del:" + ifn}>
            <div class="ifcard-top"><span class=${"iftype " + _t}>${_t === "wdtt" ? "WDTT" : _t}</span><span class="ifname">${ifn}</span><span class="grow"></span><${CmdErr} err=${(nrec.cmd_errors || {})[ifn]}/><${StatusTag} cls="tg-del" icon="clock" label="deleting" title=${T("The node tears it down on its next sync")}/></div>
            <div class="ifcard-rows">
              <div class="ifrow"><span class="l">${T("Listen")}</span><span class="r addr">${g.listen || (_w
                ? (_w.fork || "wdtt") + (_port ? ":" + _port : "")
                : (_m.endpoint || ((_m.address || "").split("/")[0] + (_m.listen_port ? ":" + _m.listen_port : "")))) || "—"}</span></div>
              <div class="ifrow"><span class="l">${T("Subnet")}</span><span class="r addr">${g.subnet || (_w ? _w.wg_addr : _m.subnet) || "—"}</span></div>
              <div class="ifrow"><span class="l faint">${T("the node is tearing it down…")}</span></div>
            </div></div>`; };
        const _pfx = name + "|";
        // drop a client-optimistic entry only once the node REPORTS the iface (meta), or it's gone stale —
        // keep it through the whole "creating" phase so its details stay on the card AND the next form's
        // suggestions (name / subnet / port) account for it.
        // A WDTT interface is REPORTED via stats.wdtt (it owns its own interface), not the wg/awg `meta` map — so
        // its optimistic "creating" card must dedupe against the live WDTT set too, else it lingers as a ghost.
        const _wLive = new Set([...((Store.stats[name] || {}).wdtt || []), ...((Store.stats[name] || {}).csqtt || [])].filter(w => w && w.iface).map(w => w.iface));   // self-contained (WDTT + csqtt) live ifaces — for optimistic create/delete dedup
        const _reported = i => (meta && meta[i]) || _wLive.has(i);
        for (const k of Object.keys(Store.ifaceNew)) {
          if (!k.startsWith(_pfx)) continue;
          const i = k.slice(_pfx.length);
          if (_reported(i)) { ifaceReady[name + "|" + i] = Date.now() + 5000; delete Store.ifaceNew[k]; }   // just created/onboarded → flash green→blue "ready" for 5s
          else if (Date.now() - (Store.ifaceNew[k].at || 0) > 900000) delete Store.ifaceNew[k];
        }
        const optNames = Object.keys(Store.ifaceNew).filter(k => k.startsWith(_pfx)).map(k => k.slice(_pfx.length));
        // client-optimistic DELETE — ifaceNew inverted: it is set the instant Delete is confirmed and cleared
        // once the node STOPS reporting the interface. Without it the card kept every action live on a doomed
        // interface, and a WDTT one then flickered into an adoption CANDIDATE — the panel drops its record at
        // once while the node still reports the device, and a WDTT iface isn't in `meta`, so `_known` said
        // "not ours, adopt it?" about the very server being torn down.
        // Cleared once OUR instance is gone — the live set plus the panel's own record. Deliberately NOT
        // "until the node stops mentioning the name at all": a name can stay on the node under a DIFFERENT
        // owner, and an unmanaged WDTT server is pinned to wdtt0 (upstream compiles the name in), so that
        // reading left the card on "deleting" for ever after deleting the managed instance beside it. The
        // orphan card this used to suppress is now prevented at the source, on the node (_wdtt_remove drops
        // the cached proc walk it was being resurrected from).
        const _stillOnNode = i => _reported(i) || !!(nrec.wdtt_cfg || {})[i] || !!(nrec.csqtt_cfg || {})[i];
        for (const k of Object.keys(Store.ifaceGone)) {
          if (!k.startsWith(_pfx)) continue;
          const i = k.slice(_pfx.length);
          if (!_stillOnNode(i)) delete Store.ifaceGone[k];                                     // really gone → the card goes with it
          else if (Date.now() - (Store.ifaceGone[k].at || 0) > 900000) delete Store.ifaceGone[k];   // stale sweep, same window as ifaceNew
        }
        const goneNames = Object.keys(Store.ifaceGone).filter(k => k.startsWith(_pfx)).map(k => k.slice(_pfx.length));
        // system mesh-link ifaces (swg_*) are created/torn down by the panel during re-provision — they belong
        // to the Node-connections cards, NEVER the User-interfaces list, so exclude them from every pending lane.
        const pendOn = (nrec.onboarding || []).filter(ifn => !_reported(ifn) && !optNames.includes(ifn) && !isSysName(ifn));
        const cr = nrec.creating || {};   // { iface: "wg" | "awg" } — server-side, deduped against the client cards
        const pendCr = Object.keys(cr).filter(ifn => !_reported(ifn) && !optNames.includes(ifn) && !isSysName(ifn));
        const optCards = optNames.filter(ifn => !_reported(ifn)).map(ifn => optIfCard(ifn, Store.ifaceNew[_pfx + ifn]));
        const pending = pendOn.concat(pendCr, optNames);
        pending.forEach(ifn => { ifaceWasBusy[name + "|" + ifn] = true; });   // any in-flight iface (create / onboard / server) → flash "ready" once it appears in meta
        // a delete in flight suppresses the candidate / missing / ghost grids for that name too (that flicker
        // IS the orphan card) — but after the ready-flash arming above: it is not coming back.
        pending.push(...goneNames);
        const pcards = pendOn.map(ifn => pcard(ifn, "onboarding", null))
          .concat(pendCr.map(ifn => pcard(ifn, "creating", cr[ifn])))
          .concat(optCards);
        // MISSING user interfaces: expected (the panel holds a saved config) but the node no longer reports them
        // — a warning card that recreates the interface with its original identity, recovering every peer on it.
        const mcard = (ifn, mi) => { const mtype = (mi.awg_params && Object.keys(mi.awg_params).length) ? "awg" : "wg";
          const sentence = mi.key_source
            ? goneSentence(T("The node no longer reports interface {iface} (subnet {subnet}). {verdict}, so Restore recreates it cleanly — no client changes.",
                { iface: ifn, subnet: mi.subnet || "?" }), true, T("Its original server key is recoverable"))
            : goneSentence(T("The node no longer reports interface {iface} (subnet {subnet}). {verdict}, so Restore recreates it with a new key — clients re-import.",
                { iface: ifn, subnet: mi.subnet || "?" }), false, T("Its original server key can't be recovered"));
          return html`<a class="ifcard missing" key=${"missing:" + ifn} href=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(ifn)} title=${T("Open the interface (read-only) — peers, saved config, and Restore")}>
            <div class="ifcard-top"><span class=${"iftype " + mtype}>${mtype}</span><span class="ifname">${ifn}</span><span class="grow"></span>
              <button class="mi-restore" disabled=${blocked || !mi.ripe} title=${mi.ripe ? T("Recreate this interface with its original identity — recovers every peer on it") : T("Confirming it's really gone (a couple of minutes) before Restore is offered")} onClick=${e => { e.preventDefault(); e.stopPropagation(); confirmRestoreInterface(name, ifn, mi); }}><${Ic} i="refresh"/> ${T("Restore")}</button>
              <${StatusTag} cls="tg-del" icon="warn" label="missing" title=${T("This interface is gone from the node")}/></div>
            <div class="ifcard-rows"><div class="mi-text">${sentence}</div></div></a>`; };
        // GHOST card — a lost interface with NO recoverable key (cold: no saved config; or a keyless missing
        // interface). Restore can't help, so it offers "Recreate" (fresh key + rekey every peer). Semi-
        // transparent until hover (it's a phantom), mirroring the .ifcard.down treatment.
        const gcard = (ifn, g) => { const gp = ghostPeers(name, ifn);
          return html`<a class="ifcard ghost" key=${"ghost:" + ifn} href=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(ifn)} title=${T("Open the interface (read-only) — recreate & rekey")}>
            <div class="ifcard-top"><span class="iftype gh">${T("tag|gone")}</span><span class="ifname">${ifn}</span><span class="grow"></span>
              <button class="mi-restore ghost" disabled=${blocked || !g.ripe} title=${g.ripe ? T("Recreate this interface with a NEW key and rekey every peer on it (clients re-import)") : T("Confirming it's really gone (a couple of minutes) before Recreate is offered")} onClick=${e => { e.preventDefault(); e.stopPropagation(); openRecreateRekey(name, ifn); }}><${Ic} i="refresh"/> ${T("Recreate")}</button>
              <${StatusTag} cls="tg-del" icon="warn" label="ghost" title=${T("Gone with no recoverable key — recreate fresh + rekey")}/></div>
            <div class="ifcard-rows"><div class="mi-text">${goneSentence(T("The node no longer reports {iface}, and {verdict} — there's nothing to restore. Recreate it with a new key; {count} get fresh configs to re-import.", { iface: ifn, count: plural(gp.length, "peer") }), false, T("its server key can't be recovered"))}</div></div></a>`; };
        // MISSING WDTT server: the panel still wants it (wdtt_cfg) but the node reports nothing for it in
        // snap.wdtt — a rebuilt box, or a node running a build without WDTT support. The whole WDTT UI keys off
        // the snapshot, so without this the server simply VANISHED: no card, no hint that its identity is safely
        // escrowed, no way to restore it. Same orange treatment and inline action as a missing wg/awg interface.
        const wmcard = (ifn, wc) => { const vaulted = !!((nrec.wdtt_vault || {})[ifn]);
          const restoring = (nrec.wdtt_restoring || []).includes(ifn);
          const fork = wc.fork || "amurcanov";
          const dtls = String(wc.listen || "").split(":").pop() || "";
          const sentence = vaulted
            ? goneSentence(T("The node no longer reports WDTT server {iface} (subnet {subnet}). {verdict}, so Restore brings it back unchanged — no user re-imports.",
                { iface: ifn, subnet: wc.wg_addr || "?" }), true, T("Its identity is escrowed in your Encryption Vault"))
            : goneSentence(T("The node no longer reports WDTT server {iface} (subnet {subnet}). {verdict}, so it can only come back with a new key — every user re-imports.",
                { iface: ifn, subnet: wc.wg_addr || "?" }), false, T("No escrowed identity is stored"));
          return html`<a class="ifcard missing" key=${"wdtt-missing:" + ifn} href=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(ifn)} title=${T("Open the WDTT server (read-only) — details and Restore")}>
            <div class="ifcard-top"><span class="iftype wdtt">WDTT</span><span class="ifname">${ifn}</span><span class="grow"></span>
              <button class="mi-restore" disabled=${blocked || restoring} title=${vaulted ? T("Bring this WDTT server back with its original identity — no user re-imports") : T("Recreate this WDTT server with a NEW identity — every user re-imports")}
                onClick=${e => { e.preventDefault(); e.stopPropagation(); vaulted ? wdttRestoreIdentity(name, ifn) : wdttRecreateFresh(name, ifn); }}><${Ic} i=${vaulted ? "shield" : "refresh"}/> ${restoring ? T("Restoring…") : vaulted ? T("Restore") : T("Recreate")}</button>
              <${StatusTag} cls="tg-del" icon="warn" label="missing" title=${T("This WDTT server is gone from the node")}/></div>
            <div class="ifcard-rows"><div class="mi-text">${sentence}</div></div></a>`; };
        // ADOPTING card — a take-over in flight, before the node has started the server. Same chrome as the
        // card it becomes, inert: nothing to start, stop or restore yet.
        const wacard = (ifn, wc) => { const fork = wc.fork || "amurcanov";
          const dtls = String(wc.listen || "").split(":").pop() || "";
          return html`<div class="ifcard down" key=${"wdtt-adopting:" + ifn}>
            <div class="ifcard-top"><span class="iftype wdtt">WDTT</span><span class="ifname">${ifn}</span><span class="grow"></span>
              <${ForkTag} fork=${fork}/><${StatusTag} cls="tg-busy" icon="clock" label="adopting" title=${T("The node takes it over on its next sync")}/></div>
            <div class="ifcard-rows">
              <div class="ifrow"><span class="l">${T("Listen")}</span><span class="r addr">${forkProduct(fork)}${dtls ? ":" + dtls : ""}</span></div>
              <div class="ifrow"><span class="l">${T("Subnet")}</span><span class="r addr">${wc.wg_addr || "—"}</span></div>
              <div class="ifrow"><span class="l faint">${T("taking it over…")}</span></div>
            </div></div>`; };
        // An adoption in flight writes the instance into wdtt_cfg immediately, while the node may still report
        // the ORPHAN it is taking over — that orphan card carries the state, so showing this one too would put
        // two cards on screen for one server. But a DORMANT install has no orphan card: the panel drops it from
        // wdtt_dormant the moment it is claimed, and the node hasn't started the server yet — so skipping it
        // here left NO card at all and the server simply vanished until the take-over finished. Skip only when
        // something else is already showing it; otherwise show the take-over itself.
        const _wAdopting = new Set(nrec.wdtt_adopting || []);
        const _wHasOrphanCard = ifn => (nrec.iface_candidates || []).some(c => c && c.name === ifn);
        const wmcards = Object.entries(nrec.wdtt_cfg || {})
          .filter(([ifn]) => !wdttIfaces.some(w => w.iface === ifn) && !pending.includes(ifn)
                             && !(_wAdopting.has(ifn) && _wHasOrphanCard(ifn)))
          .map(([ifn, wc]) => _wAdopting.has(ifn) ? wacard(ifn, wc || {}) : wmcard(ifn, wc || {}));
        const mcards = Object.entries(nrec.missing_ifaces || {})
          .filter(([ifn, mi]) => mi.key_source && !(meta && meta[ifn]) && !pending.includes(ifn) && !isSysName(ifn))   // RECOVERABLE only — keyless ones fall to gcard below; a recreate/restore in flight shows the "creating" card instead
          .map(([ifn, mi]) => mcard(ifn, mi));
        // Approach-B adoption candidates: wg/awg interfaces the node found but the panel doesn't manage. Orange
        // "found" cards in the same grid → open to Adopt or Ignore. (wdtt_hint → WDTT, not wg/awg-adoptable yet.)
        const ccard = (cd, ig) => { const wd = !!cd.wdtt_hint; const ip0 = (cd.address || "").split("/")[0];
          // wdtt_adopting is the SERVER's word for a WDTT take-over; Store.ifaceNew is the client's optimistic
          // marker for a wg/awg adopt, set the instant Adopt is submitted. Either means "in flight".
          const adopting = _wAdopting.has(cd.name) || !!Store.ifaceNew[name + "|" + cd.name];
          // Ignore is decided on the DETAIL page but lands here — the operator is bounced to this grid the
          // instant they click, so without this the card would sit unchanged until the next poll quietly
          // removed it, and the click would read as having done nothing.
          const _cop = opTag(name + "|" + cd.name);
          // `blocked` = the node is converting / re-installing / down. Every managed card dims and disables for
          // it; the candidate cards were the exception, still offering an Adopt that the node cannot act on.
          return html`<a class=${"ifcard candidate" + (ig ? " ignored" : "") + ((adopting || blocked || _cop) ? " down" : "") + (blocked ? " locked" : "")} key=${(ig ? "ign:" : "cand:") + cd.name}
            onClick=${blocked ? (e => e.preventDefault()) : null} href=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(cd.name)} title=${ig ? T("Ignored — the panel isn't managing it. Open to Un-ignore or Adopt.") : T("Found on the node — not managed by the panel. Open to Adopt or Ignore.")}>
            <div class="ifcard-top"><span class=${"iftype " + (wd ? "wdtt" : (cd.type_hint === "awg" ? "awg" : "orph"))}
                title=${wd ? T("A WDTT server is running on it") : cd.type_why ? T("Looks like {v1} — {v2}", { v1: String(cd.type_hint || "wg").toUpperCase(), v2: cd.type_why }) : T("Type not established — you choose it when adopting")}>${wd ? "wdtt" : cd.type_hint === "awg" ? "awg?" : "wg?"}</span><span class="ifname">${cd.name}</span>
              <span class="grow"></span>
              ${(ig || adopting || blocked || _cop) ? null : html`<button class="mi-restore" title=${T("Adopt this interface — choose its type, keys and peers are kept")}
                onClick=${e => { e.preventDefault(); e.stopPropagation(); openModal(html`<${AdoptIfaceSheet} node=${name} iface=${cd.name} cand=${cd} nrec=${nrec}/>`); }}><${Ic} i="plus"/> ${T("Adopt")}</button>`}
              ${_cop
                ? _cop
                : adopting
                ? html`<${StatusTag} cls="tg-busy" icon="clock" label="adopting" title=${T("Taking it over — the node applies this on its next sync")}/>`
                : html`<span class=${"tg " + (ig ? "tg-ign" : "tg-cand")} title=${ig ? T("Ignored candidate — Settings-style dismissed; open to Un-ignore") : T("Found on the node — the panel doesn't manage it. Adopt to manage, or Ignore.")}><${Ic} i="warn"/>${ig ? "ignored" : "orphan"}</span>`}</div>
            <div class="ifcard-rows">
              <div class="ifrow"><span class="l">${T("Found at")}</span><span class="r addr">${(cd.conf ? cd.conf.replace(/\/[^/]*$/, "") : ((cd.wdtt || {}).config_dir || "")) || html`<span class="faint">—</span>`}</span></div>
              <div class="ifrow"><span class="l">${T("Listen")}</span><span class="r addr">${ip0}${cd.listen_port ? ":" + cd.listen_port : ""}</span></div>
              <div class="ifrow"><span class="l">${T("Subnet")}</span><span class="r addr">${cd.address || "—"}</span></div>
              <div class="ifrow"><span class="l">${T("Peers")}</span><span class="r">${cd.peers ? html`<b>${cd.peers}</b>` : html`<span class="faint">${T("None")}</span>`}</span></div>
            </div></a>`; };
        // A name the panel already has for THIS node is not an orphan — it is one of ours the node stopped
        // reporting, which is the missing/ghost card right above. Showing both said "we manage it, it's gone"
        // and "we don't manage it, adopt it?" about the same interface, in the same grid.
        // …but NOT while it is being taken over: adopting writes the instance into wdtt_cfg immediately, so
        // treating that as "known" hid the orphan card at the very moment it is meant to show "adopting" — and
        // wmcards skips it too, leaving the interface with no card at all until the node finished.
        const _known = ifn => !_wAdopting.has(ifn) && !!((meta && meta[ifn]) || (nrec.missing_ifaces || {})[ifn] || (nrec.ghost_ifaces || {})[ifn] || (nrec.wdtt_cfg || {})[ifn]);
        // DORMANT WDTT: an install on disk with nothing running. It owns its TUN, so while stopped there is no
        // interface, no socket and no process — it can't be an interface candidate, and staying silent about it
        // is how a real server goes unnoticed. Adoption STARTS it: we have the binary, its identity and its
        // password store, so "go start it yourself" would be pointless advice from the one thing that can.
        const _claimed = new Set(nrec.wdtt_claimed_dirs || []);
        const dcard = d => { const taking = _claimed.has(d.config_dir);   // an instance already points at this dir
          return html`<div class=${"ifcard candidate" + ((taking || blocked) ? " down" : " clickable") + (blocked ? " locked" : "")} key=${"dormant:" + d.config_dir}
            title=${taking ? T("Being taken over — the node applies this on its next sync") : T("Adopt this WDTT server — its key and passwords are kept")}
            onClick=${() => { if (!taking && !blocked) go("#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(d.config_dir || "")); }}>
          <div class="ifcard-top"><span class="iftype wdtt">wdtt</span><span class="ifname">${(d.config_dir || "").split("/").filter(Boolean).pop() || "wdtt"}</span><span class="grow"></span>
            ${(taking || blocked) ? null : html`<button class="mi-restore" title=${T("Adopt this WDTT server — its key and passwords are kept")}
              onClick=${e => { e.preventDefault(); e.stopPropagation(); openModal(html`<${AdoptDormantWdttSheet} node=${name} d=${d} nrec=${nrec}/>`); }}><${Ic} i="plus"/> ${T("Adopt")}</button>`}
            ${taking
              ? html`<${StatusTag} cls="tg-busy" icon="clock" label="adopting" title=${T("Taking it over — the node applies this on its next sync")}/>`
              : html`<span class="tg tg-cand" title=${T("On the node, not managed by the panel")}><${Ic} i="warn"/>${T("tag|orphan")}</span>`}</div>
          <div class="ifcard-rows">
            <div class="ifrow"><span class="l">${T("Found at")}</span><span class="r addr">${d.config_dir}</span></div>
            <div class="ifrow"><span class="l">${T("Fork")}</span><span class="r">${d.fork || html`<span class="faint">${T("value|unknown")}</span>`}</span></div>
            <div class="ifrow"><span class="l">${T("Ports")}</span><span class="r addr">${d.listen_port
              ? html`${d.listen_port}${d.wg_port ? " · " + d.wg_port : ""}`
              : html`<span class="faint">${T("set on adopt")}</span>`}</span></div>
            <div class="ifrow"><span class="l">${T("Peers")}</span><span class="r">${(d.users || []).length
              ? html`<b>${(d.users || []).length}</b>`
              : html`<span class="faint">${T("None")}</span>`}</span></div>
          </div></div>`; };
        const dcards = (nrec.wdtt_dormant || []).map(dcard);
        const ccards = (nrec.iface_candidates || []).filter(cd => cd && cd.name && !_known(cd.name) && !pending.includes(cd.name) && !isSysName(cd.name)).map(cd => ccard(cd, false));
        const _gset = {};   // dedupe cold (ghost_ifaces) + keyless-missing into one gcard per iface; a recreate in flight (pending) drops the ghost card in favour of its "creating" card
        for (const ifn of Object.keys(nrec.ghost_ifaces || {})) if (!(meta && meta[ifn]) && !pending.includes(ifn) && !isSysName(ifn)) _gset[ifn] = 1;
        for (const [ifn, mi] of Object.entries(nrec.missing_ifaces || {})) if (!mi.key_source && !(meta && meta[ifn]) && !pending.includes(ifn) && !isSysName(ifn)) _gset[ifn] = 1;
        const gcards = Object.keys(_gset).map(ifn => [ifn, ghostIface(name, ifn)]).filter(([, g]) => g).map(([ifn, g]) => gcard(ifn, g));
        // WDTT-owned interfaces: a self-contained WDTT fork brings up its OWN userspace-WireGuard interface. Show it
        // here (flagged) so the operator sees the datapath, but it's READ-ONLY for peer/key management — WDTT owns
        // its keys + peers, so it's managed from the Turn-proxies card (click opens that). Routing/blocking applies.
        // WDTT interface card — SAME chrome/behavior as the normal interface card (hover, edit-flash, dimming,
        // status, click→detail), rows identical EXCEPT Listen shows the fork:port instead of the interface IP.
        // The pencil opens the WDTT edit modal (endpoint/fork/ports + routing/filters/egress), like a normal iface.
        const wcard = w => {
          const active = w.active === "active"; const awaiting = !!w.await_restore;
          const restoring = (nrec.wdtt_restoring || []).includes(w.iface);
          const fork = w.fork || "amurcanov";
          const wcfg = (nrec.wdtt_cfg || {})[w.iface] || {};   // desired egress/routing/filters (for the Traffic badge)
          const dtls = String(w.listen || "").split(":").pop() || "";
          const ps = here.filter(p => p.targets.some(t => t.node === name && t.iface === w.iface));
          const onlc = ps.filter(p => p.targets.some(t => t.node === name && t.iface === w.iface && t.online)).length;
          const _wop = Store.ifaceOp[name + "|" + w.iface];   // optimistic save lifecycle (applying/applied/failed), like a normal card
          const _wopTag = opTag(name + "|" + w.iface);
          const wconverting = (nrec.proc_status || "").startsWith("converting");   // node mid bare↔docker convert — same as the wg/awg + turn cards
          const idim = wconverting || awaiting || restoring || !active || (_wop && _wop.phase === "busy");   // needs attention / in flight → dim
          const href = "#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(w.iface);
          const it = ifReorder.item(w.iface);
          const badge = html`<span class="iftype wdtt">WDTT</span><span class="ifname">${w.iface}</span>`;
          return html`<a key=${"wdtt-if:" + w.iface} class=${"ifcard" + (idim ? " down" : "") + (blocked ? " locked" : "") + it.cls} href=${href} draggable=${false} data-rid=${it.rid}>
            <div class="ifcard-top"><span class="drag-grip" title=${T("Drag to reorder")} onClick=${e => e.preventDefault()} ...${ifReorder.grip(w.iface)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span>${(blocked || (_wop && _wop.phase === "busy")) ? badge
              : html`<button class="ifc-edit" title=${T("Edit WDTT server · {v1}", { v1: w.iface })} onClick=${e => { e.preventDefault(); e.stopPropagation(); openEditWdtt(name, w.iface); }}>${badge}<span class="ifc-pic"><${Ic} i="pencil"/></span></button>`}<span class="grow"></span><${ForkTag} fork=${fork}/>${wconverting
                ? html`<${StatusTag} cls="tg-convert" icon="clock" label="converting" title=${T("The node is converting between bare-metal and docker")}/>`
                : _wopTag
                ? _wopTag
                : awaiting
                ? html`<${StatusTag} cls="tg-busy del" icon="shield" label=${T("Restore")} title=${T("Server wiped — its identity is escrowed; open to Restore or Recreate fresh")}/>`
                : restoring ? html`<span class="tg tg-busy"><${Ic} i="clock"/>${T("tag|restoring")}</span>`
                : active ? null
                : html`<span class="tg tg-busy"><${Ic} i="clock"/>${T("tag|starting")}</span>`}</div>
            <div class="ifcard-rows">
              <div class="ifrow"><span class="l">${T("Listen")}</span><span class="r addr">${forkProduct(fork)}${dtls ? ":" + dtls : ""}</span></div>
              <div class="ifrow"><span class="l">${T("Subnet")}</span><span class="r addr">${w.wg_addr || "—"}</span></div>
              <div class="ifrow"><span class="l">${T("Throughput")}</span><span class="r">${wcfg.egress_mode === "forward" && wcfg.egress_node
                ? html`<span class="egb egb-fwd" style=${"color:" + Store.nodeColor(wcfg.egress_node)} title=${T("Exits via {v1}", { v1: Store.nodeName(wcfg.egress_node) + (wcfg.egress_ip ? " (" + wcfg.egress_ip + ")" : "") })}><${Ic} i="server"/>→ ${Store.nodeName(wcfg.egress_node)}</span>`
                : wcfg.egress_mode === "smart"
                ? html`<span class="egb egb-smart" title=${T("{v1} destination rule(s)", { v1: (wcfg.routing || []).filter(r => r.action === "exit").length })}><${Ic} i="cascade"/>${T("tag|smart")}</span>`
                : html`<span class="egb egb-direct" title=${T("Exits directly from this node")}><${Ic} i="globe"/>${T("tag|direct")}</span>`}</span></div>
              <div class="ifrow"><span class="l">${T("Peers")}</span><span class="r">${ps.length
                ? html`<${OnlinePeersTag} nodeId=${name} iface=${w.iface} orphans=${0} orphHref=${href}
                    trigger=${() => html`<b class=${"oncount" + (onlc ? " on" : "")}>${onlc}</b><span class="faint">/${ps.length}</span>`}/>`
                : html`<span class="faint">${T("None")}</span>`}</span></div>
            </div></a>`; };
        // csqtt in the node store (csqtt_cfg) but NOT yet reported in snap.csqtt — a just-created instance the node
        // hasn't brought up yet, or a wiped one it will re-establish (csqtt self-heals from panel state, no vault).
        // Shows a syncing card so it doesn't vanish in that window. Same orange treatment as a WDTT missing card.
        const cmcard = (ifn, cc) => html`<a class="ifcard down" key=${"csqtt-cfg:" + ifn} href=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(ifn)} title=${T("Open the csqtt server — details and settings")}>
          <div class="ifcard-top"><span class="iftype csqtt">CSQTT</span><span class="ifname">${(cc.title || "").trim() || ifn}</span><span class="grow"></span>
            <${StatusTag} cls="tg tg-pending" icon="clock" label="starting" title=${T("The node brings it up on its next sync")}/></div>
          <div class="ifcard-rows">
            <div class="ifrow"><span class="l">${T("Listen")}</span><span class="r addr">${cc.listen || "—"}</span></div>
            <div class="ifrow"><span class="l">${T("Subnet")}</span><span class="r addr">${cc.tun_addr || "—"}</span></div>
            <div class="ifrow"><span class="l faint">${T("waiting for the node to bring it up…")}</span></div>
          </div></a>`;
        const cmcards = Object.entries(nrec.csqtt_cfg || {})
          .filter(([ifn]) => !csqttIfaces.some(c => c.iface === ifn) && !pending.includes(ifn))
          .map(([ifn, cc]) => cmcard(ifn, cc || {}));
        // csqtt-owned interface card — same chrome as the WDTT card (self-contained kind), but raw-TUN: Listen shows
        // the host:port, Subnet shows the tun_addr, no fork tag, and the pencil opens the csqtt edit modal.
        const csqCard = c => {
          const active = c.active === "active";
          const ccfg = (nrec.csqtt_cfg || {})[c.iface] || {};
          const ps = here.filter(p => p.targets.some(t => t.node === name && t.iface === c.iface));
          const onlc = ps.filter(p => p.targets.some(t => t.node === name && t.iface === c.iface && t.online)).length;
          const _cop = Store.ifaceOp[name + "|" + c.iface];
          const _copTag = opTag(name + "|" + c.iface);
          const cconverting = (nrec.proc_status || "").startsWith("converting");
          const idim = cconverting || !active || (_cop && _cop.phase === "busy");
          const href = "#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(c.iface);
          const it = ifReorder.item(c.iface);
          const badge = html`<span class="iftype csqtt">CSQTT</span><span class="ifname">${c.iface}</span>`;
          return html`<a key=${"csqtt-if:" + c.iface} class=${"ifcard" + (idim ? " down" : "") + (blocked ? " locked" : "") + it.cls} href=${href} draggable=${false} data-rid=${it.rid}>
            <div class="ifcard-top"><span class="drag-grip" title=${T("Drag to reorder")} onClick=${e => e.preventDefault()} ...${ifReorder.grip(c.iface)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span>${(blocked || (_cop && _cop.phase === "busy")) ? badge
              : html`<button class="ifc-edit" title=${T("Edit csqtt server · {v1}", { v1: c.iface })} onClick=${e => { e.preventDefault(); e.stopPropagation(); openEditCsqtt(name, c.iface); }}>${badge}<span class="ifc-pic"><${Ic} i="pencil"/></span></button>`}<span class="grow"></span><${ForkTag} fork=${c.fork || "csqtt"}/>${cconverting
                ? html`<${StatusTag} cls="tg-convert" icon="clock" label="converting" title=${T("The node is converting between bare-metal and docker")}/>`
                : _copTag ? _copTag
                : active ? null
                : html`<span class="tg tg-busy"><${Ic} i="clock"/>${T("tag|starting")}</span>`}</div>
            <div class="ifcard-rows">
              <div class="ifrow"><span class="l">${T("Listen")}</span><span class="r addr">${c.listen || "—"}</span></div>
              <div class="ifrow"><span class="l">${T("Subnet")}</span><span class="r addr">${c.tun_addr || "—"}</span></div>
              <div class="ifrow"><span class="l">${T("Throughput")}</span><span class="r">${ccfg.egress_mode === "forward" && ccfg.egress_node
                ? html`<span class="egb egb-fwd" style=${"color:" + Store.nodeColor(ccfg.egress_node)} title=${T("Exits via {v1}", { v1: Store.nodeName(ccfg.egress_node) + (ccfg.egress_ip ? " (" + ccfg.egress_ip + ")" : "") })}><${Ic} i="server"/>→ ${Store.nodeName(ccfg.egress_node)}</span>`
                : ccfg.egress_mode === "smart"
                ? html`<span class="egb egb-smart" title=${T("{v1} destination rule(s)", { v1: (ccfg.routing || []).filter(r => r.action === "exit").length })}><${Ic} i="cascade"/>${T("tag|smart")}</span>`
                : html`<span class="egb egb-direct" title=${T("Exits directly from this node")}><${Ic} i="globe"/>${T("tag|direct")}</span>`}</span></div>
              <div class="ifrow"><span class="l">${T("Peers")}</span><span class="r">${ps.length
                ? html`<${OnlinePeersTag} nodeId=${name} iface=${c.iface} orphans=${0} orphHref=${href}
                    trigger=${() => html`<b class=${"oncount" + (onlc ? " on" : "")}>${onlc}</b><span class="faint">/${ps.length}</span>`}/>`
                : html`<span class="faint">${T("None")}</span>`}</span></div>
            </div></a>`; };
        return metaErr ? html`<div class="notice warn"><${Ic} i="warn"/><span>${T("This node hasn't reported in yet — its interfaces will show up here once it runs the installer and syncs.")}<br/><br/>${T("Lost the enrollment token or the install command? Rotate the node's token to generate a fresh install command.")}</span></div>`
          : !meta ? html`<div class="loading"><span class="spin"></span>${T("reading server…")}</div>`
          : (!userKeys.length && !pending.length && !mcards.length && !gcards.length && !wdttIfaces.length && !csqttIfaces.length && !wmcards.length && !cmcards.length && !ccards.length && !dcards.length) ? html`<div class="notice warn"><${Ic} i="warn"/><span>${T("No managed interfaces reported.")}</span></div>`
          : html`<div class="ifgrid" ...${ifReorder.container()}>${mcards}${wmcards}${cmcards}${gcards}${ifaceIds.map(ifn => {
              if (Store.ifaceGone[_pfx + ifn]) return delCard(ifn, Store.ifaceGone[_pfx + ifn]);   // teardown in flight → the inert "deleting" card, in place
              const _w = wdttIfaces.find(w => w.iface === ifn);   // WDTT interface → its card (reorders in the same grid); else a normal wg/awg card
              if (_w) return wcard(_w);
              const _c = csqttIfaces.find(c => c.iface === ifn);   // csqtt interface → its card (self-contained raw-TUN, like WDTT)
              if (_c) return csqCard(_c);
              const m = meta[ifn];
              if (!m) return null;   // ifaceIds is built before the ifaceGone sweep below, so a marker cleared THIS render can leave a name with nothing behind it — rendering it would read meta of undefined and blank the page
              const it = ifReorder.item(ifn);
              if (ifaceWasBusy[name + "|" + ifn]) { ifaceReady[name + "|" + ifn] = Date.now() + 5000; ifaceWasBusy[name + "|" + ifn] = false; }   // just came up after being pending/creating → "ready" 5s
              const type = (m.awg_params && Object.keys(m.awg_params).length) ? "awg" : "wg";
              const ps = here.filter(p => p.targets.some(t => t.node === name && t.iface === ifn));
              const onlc = ps.filter(p => p.targets.some(t => t.node === name && t.iface === ifn && t.online)).length;
              const orph = Store.recon.orphans.filter(o => o.node === name && o.iface === ifn).length;
              const deleting = (nrec.deleting || []).includes(ifn);
              const istate = (((Store.stats[name] || {}).interfaces || {})[ifn] || {});
              const istopped = !!istate.stopped;   // operator stopped it (a choice, not a failure)
              const idown = !istopped && istate.down;   // genuinely down
              const irestarting = (nrec.restarting || []).includes(ifn);
              const iconverting = (nrec.proc_status || "").startsWith("converting");   // node is mid bare↔docker convert
              const fwdTurns = turnProxiesFor(name, ifn);   // turn-proxies forwarding to this interface (by connect-port == listen_port)
              const iprog = (nrec.cmd_progress || {})[ifn];   // node "what's happening now" (yellow note) for this interface
              const iop = Store.ifaceOp[name + "|" + ifn];   // optimistic start/stop/restart lifecycle (set on click, before the node reflects it)
              const iopBusy = iop && iop.phase === "busy";
              // a wide status badge is showing → keep it on one line by compacting the turn badges (turn→t) and
              // letting the name ellipsize; reverts to full once no such status is shown
              const tight = iopBusy || iconverting || deleting || idown || irestarting || !!(nrec.cmd_errors || {})[ifn];
              // `.down` = THIS interface needs attention or is in flight. Node-wide states (offline, converting,
              // re-installing, updating) are `.locked` instead — nothing is wrong with the interface, it just
              // can't be edited, and every card on the page gets it at once. `iconverting`/`nodeStale` moved out
              // of here into `blocked` for exactly that reason.
              const idim = deleting || idown || istopped || irestarting || iopBusy || !!iprog || !!(nrec.cmd_errors || {})[ifn];
              return html`<a key=${ifn} class=${"ifcard" + (deleting ? " pending" : "") + (idim ? " down" : "") + (blocked ? " locked" : "") + it.cls} href=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(ifn)} draggable=${false} data-rid=${it.rid}>
                <div class="ifcard-top"><span class="drag-grip" title=${T("Drag to reorder")} onClick=${e => e.preventDefault()} ...${ifReorder.grip(ifn)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span>${(blocked || iopBusy || deleting || irestarting) ? html`<span class=${"iftype " + type}>${type}</span><span class="ifname">${ifn}</span>` : html`<button class="ifc-edit" title=${T("Edit interface · {v1}", { v1: type.toUpperCase() })} onClick=${e => { e.preventDefault(); e.stopPropagation(); openEditIface(name, ifn); }}><span class=${"iftype " + type}>${type}</span><span class="ifname">${ifn}</span><span class="ifc-pic"><${Ic} i="pencil"/></span></button>`}<span class="grow"></span>${ifaceTurnBadges(name, fwdTurns, tight)}${iprog ? html`<${CmdErr} err=${iprog} cls="warn" title=${T("Working on the node")}/>` : null}${iopBusy ? html`<span class="tg tg-busy"><${Ic} i="clock"/>${ifopBusy(iop.verb)}</span>` : iconverting ? html`<span class="tg tg-convert" title=${T("The node is converting between bare-metal and docker")}><${Ic} i="clock"/>${T("tag|converting")}</span>` : deleting ? html`<${StatusTag} cls="tg-del" icon="clock" label="deleting" msg=${(nrec.cmd_errors || {})[ifn]} title=${T("Command failed on the node")}/>` : istopped ? html`<span class="tg-off" title=${T("Stopped by you — open to Start it")}><${Ic} i="stop"/>${T("tag|stopped")}</span>` : idown ? html`<${StatusTag} cls="tg-busy del" icon="warn" label="down" msg=${(nrec.cmd_errors || {})[ifn] || (T("interface is down on the node — awg-quick couldn't bring it up: {v1}", { v1: idown }))} title=${T("Interface down on the node")}/>` : irestarting ? html`<span class="tg tg-busy"><${Ic} i="clock"/>${T("tag|restarting")}</span>` : ((nrec.cmd_errors || {})[ifn] ? html`<${StatusTag} cls="tg-busy del" icon="warn" label="error" msg=${(nrec.cmd_errors || {})[ifn]} title=${T("Command failed on the node")}/>` : (m.drift && Object.keys(m.drift).length) ? html`<span class="tg tg-pending" title=${T("A setting was edited directly on the server — open to Adopt or Restore")}><${Ic} i="warn"/>${T("tag|modified")}</span>` : (ifaceReady[name + "|" + ifn] && Date.now() < ifaceReady[name + "|" + ifn]) ? html`<span class="tg tg-ready"><${Ic} i="check"/>${T("tag|ready")}</span>` : null)}</div>
                <div class="ifcard-rows">
                  <div class="ifrow"><span class="l">${T("Listen")}</span><span class="r addr">${m.endpoint || ((m.address || "").split("/")[0] + (m.listen_port ? ":" + m.listen_port : "")) || "—"}</span></div>
                  <div class="ifrow"><span class="l">${T("Subnet")}</span><span class="r addr">${m.subnet || "—"}</span></div>
                  <div class="ifrow"><span class="l">${T("Throughput")}</span><span class="r">${m.egress_mode === "forward" && m.egress_node
                    ? html`<span class="egb egb-fwd" style=${"color:" + Store.nodeColor(m.egress_node)} title=${T("Exits via {v1}", { v1: Store.nodeName(m.egress_node) + (m.egress_ip ? " (" + m.egress_ip + ")" : "") })}><${Ic} i="server"/>→ ${Store.nodeName(m.egress_node)}</span>`
                    : m.egress_mode === "smart"
                    ? html`<span class="egb egb-smart" title=${T("{v1} destination rule(s)", { v1: (m.routing || []).filter(r => r.action === "exit").length })}><${Ic} i="cascade"/>${T("tag|smart")}</span>`
                    : html`<span class="egb egb-direct" title=${T("Exits directly from this node")}><${Ic} i="globe"/>${T("tag|direct")}</span>`}</span></div>
                  <div class="ifrow"><span class="l">${T("Peers")}</span><span class="r">${ps.length
                    ? html`<${OnlinePeersTag} nodeId=${name} iface=${ifn} orphans=${orph} orphHref=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(ifn)}
                        trigger=${() => html`<b class=${"oncount" + (onlc ? " on" : "")}>${onlc}</b><span class="faint">/${ps.length}</span>${orph ? html` <span class="ifc-orph" title=${T("{v1} unmanaged (orphan)", { v1: plural(orph, "peer") })}>(${orph})</span>` : null}`}/>`
                    : (orph ? html`<span class="ifc-orph" title=${T("{v1} unmanaged (orphan)", { v1: plural(orph, "peer") })}>${orph}</span>` : html`<span class="faint">${T("None")}</span>`)}</span></div>
                </div></a>`;
            })}${pcards}${ccards}${dcards}</div>`; })()}
    <//>

    ${(hasTurns || hasWdtt || hasCsqtt) && turnEnabled() ? html`<${TurnProxiesBlock} node=${name} nrec=${nrec} snap=${snap} metas=${meta} title=${T("Turn proxies")}/>` : null}
    `}
  </div>`;
}



// re-resolve on OS scheme change while in Auto
try { matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => { if (themeMode() === "auto") { applyThemeMode(); const b = document.getElementById("theme-btn"); if (b) paintThemeBtn(b); } }); } catch (_) {}


// ═════════════════════════ SCREEN: PEERS (by node) ═════════════════════════




// The shared peers grid — one row per (peer, target) deployment. Reused by the Peers screen and
// the interface-detail screen so they're identical. `agg` adds the Server/IF column; `shownByPeer`
// drives the "+N other deployments" badge; row click opens the peer-view popup.




export function NodesScreen() {
  useStore();
  const ns = Store.nodes || [];
  // drag-to-reorder the whole fleet (persisted as per-node `pos`)
  const nReorder = useReorder(ns.map(n => n.id), ids => mutate({
    patch: s => { s.nodes = orderById(s.nodes, ids, n => n.id); },
    call: () => api.saveOrder({ kind: "node", order: ids }),
  }), "y");   // nodes stack vertically → top/bottom drop edges
  return html`<div class="screen">
    <div class="section-title" style="margin:6px 2px 16px"><h2>${T("col|Nodes")}</h2><span class="count">${plural(ns.length, "server")}</span>
      <span class="nodehint">${entryServersRun()}</span><span class="grow"></span>
      <button class="btn btn-primary" onClick=${openNodeCreate}><span class="plus"><${Ic} i="plus"/></span> ${T("Add node")}</button></div>
    ${!ns.length ? html`<div class="empty"><b>${T("No nodes yet")}</b>${T("Add your first entry server — you'll get a one-time command to run on it.")}</div>`
      : html`<div class="nodegrid" ...${nReorder.container()}>${ns.map(n => html`<${NodeCard} key=${n.id} n=${n} reorder=${nReorder}/>`)}</div>`}
  </div>`;
}
// load/util tone: green under 70%, amber to 90%, red above.
export function htone(pct) { return pct >= 90 ? "hot" : (pct >= 70 ? "warn" : "ok"); }
   // green→amber→red util ramp (matches hm-fill + the CPU cpuColor ramp)
// Threshold alerts for a node: disk/memory > 90%, CPU saturated, one core pinned, load > 1.5/core.
// CPU and load are separate signals: load counts D-state tasks, so heavy disk I/O raises load while
// the CPU sits idle. Reporting both keeps each honest.
export function healthAlerts(health) {
  const out = [];
  for (const d of (health && health.disk || [])) if (d.total && d.used / d.total > 0.9) out.push({ sev: "hot", msg: "disk " + d.mount + " " + Math.round(d.used / d.total * 100) + "%" });
  const m = health && health.mem;
  if (m && m.total && m.used / m.total > 0.9) out.push({ sev: "hot", msg: "memory " + Math.round(m.used / m.total * 100) + "%" });
  const ncpu = (health && health.ncpu) || 1;
  if (health && typeof health.cpu_pct === "number") {
    // Saturation is described per-CPU, counted from the node's per-vCPU list — never inferred from
    // (max − mean), which can't tell 1 pinned CPU from 5 and goes silent at 6-of-8. The all-saturated case
    // MUST be tested before any mean-based alert: when every CPU is hot the mean is necessarily ≥ SAT_PCT,
    // so a mean-first branch would swallow it and "All … saturated" could never appear.
    const cores = cpuCores(health), hot = hotCores(health), tot = cores.length;
    const pk = tot ? T(" (peak {v1}%)", { v1: Math.max(...cores) }) : "";
    if (!tot) {                                                    // older swg-noded: mean only, no per-CPU list
      if (health.cpu_pct >= SAT_PCT) out.push({ sev: "hot", msg: T("CPU {v1}%", { v1: Math.round(health.cpu_pct) }) });
    } else if (hot && tot === 1) {
      out.push({ sev: "hot", msg: T("1 {v1} saturated{v2}", { v1: cpuName(health), v2: pk }) });
    } else if (hot && hot === tot) {
      out.push({ sev: "hot", msg: T("All {v1} saturated{v2}", { v1: cpuNamePl(health, tot), v2: pk }) });
    } else if (hot) {                                              // plural keyed off the TOTAL: "1 of 2 vCPUs"
      out.push({ sev: health.cpu_pct >= SAT_PCT ? "hot" : "warn",
                 msg: T("{v1} of {v2} {v3} saturated{v4}", { v1: hot, v2: tot, v3: cpuNamePl(health, tot), v4: pk }) });
    }
  }
  if (health && Array.isArray(health.load) && (health.load[0] || 0) / ncpu > 1.5) out.push({ sev: "warn", msg: "load " + health.load[0].toFixed(1) + " / " + ncpu + " " + cpuNamePl(health, ncpu) });
  return out;
}
export const SAT_PCT = 90;                                     // a logical CPU at/above this is "saturated" (matches CPU_SAT_PCT in swg-panel-server)
export const cpuCores = h => (h && Array.isArray(h.cpu_cores)) ? h.cpu_cores : [];
export const hotCores = h => cpuCores(h).reduce((n, c) => n + (c >= SAT_PCT ? 1 : 0), 0);
// /proc/stat's cpuN are LOGICAL cpus: vCPUs under a hypervisor, hardware threads on bare metal. Never
// "cores" — an 8-core box with hyperthreading lists 16. The node reports `virt`; unknown ⇒ plain "CPU".
export const cpuName = h => (h && h.virt) ? T("vCPU") : T("CPU");
export const cpuNamePl = (h, n) => cpuName(h) + (n === 1 ? "" : "s");

// The CPU bar+number is ALWAYS the hover target — per-vCPU detail is useful on a healthy node too.
// The triangle is only an attention marker, added when at least one vCPU is saturated.
// `idle` is 100 - usage (i.e. it folds in that vCPU's iowait share). Per-CPU iowait is not reported:
// the kernel credits it to whichever CPU was idle when the I/O completed, so only the node-level
// figure in the header is meaningful — and it's the share that used to masquerade as CPU.
export function CpuPop({ health, trigger, alignRight }) {
  const cores = cpuCores(health);
  if (!cores.length) return trigger;                    // older swg-noded: no per-vCPU data, no bubble
  const hot = hotCores(health), iow = health.cpu_iowait_pct;
  const l1 = Array.isArray(health.load) ? (health.load[0] || 0) : null;   // system-wide; the kernel keeps no per-CPU load
  return html`<${Popover} cls="cpupop" popCls="cpu-bubble" alignRight=${alignRight} trigger=${trigger}>
    <div class="onpop-h">${cores.length} ${cpuNamePl(health, cores.length)}${T(" · mean {v1}%", { v1: Math.round(health.cpu_pct) })}${l1 !== null ? T(" · load {v1}", { v1: l1.toFixed(2) }) : ""}${typeof iow === "number" && iow >= 1 ? T(" · iowait {v1}%", { v1: Math.round(iow) }) : ""}${hot ? html` · <b class="cpu-hot-n">${T("{n} saturated", { n: hot })}</b>` : ""}</div>
    ${cores.map((c, i) => html`<div class=${"onrow cpu-row" + (c >= SAT_PCT ? " hot" : "")} key=${i}>
      <span class="on-name">${cpuName(health)} ${i}</span>
      <span class="hm-bar cpu-corebar"><i class="hm-fill" style=${"width:" + Math.min(100, c) + "%;background:" + cpuColor(c)}></i></span>
      <span class="cpu-use" style=${"color:" + cpuColor(c)}>${c}%</span>
      <span class="cpu-idle">${T("idle {n}%", { n: Math.max(0, 100 - c) })}</span>
      <span class="cpu-sat">${c >= SAT_PCT ? html`<${Ic} i="warn"/>` : null}</span>
    </div>`)}
  </${Popover}>`;
}
// The attention triangle itself — rendered inside the trigger, so it hovers with the bar.
export const CpuWarnIc = ({ health }) => hotCores(health) ? html`<span class="cpu-warn" aria-label=${T("{v1} saturated", { v1: cpuNamePl(health, hotCores(health)) })}><${Ic} i="warn"/></span>` : null;


// Inline "x of y" usage bar for table rows — a compact track + count.

// ── one node's interfaces, derived once ──────────────────────────────────────────────────────────
// The ordered, typed, muted-flagged interface list for a node — the single source of truth for every
// place that shows them: the fleet card's badge row, the detail ribbon's badge row, and the order of
// the detail grid's cards. It used to be derived three times, and the copies drifted: a WDTT
// interface lives in snap.wdtt, NOT in `describe`, so a filter over describe alone silently drops it
// however it filters — which is how the ribbon lost its WDTT badges while the card kept them.
//
// Two things the callers must not have to know:
//  · a WDTT interface is reported separately (it owns its own TUN device), but on every one of these
//    surfaces it is simply another interface of this node, so it is merged in — WDTT-coloured — and
//    ordered with the rest. iface_order already carries WDTT names (the grid reorders them together).
//  · `gone: true` also yields interfaces mid-teardown, which the node has stopped reporting: their
//    card must hold its slot until it does. Those have NO `describe` entry, so `type` can never be
//    read off meta[ifn] blind — a member access on a missing entry is the shape of bug that took the
//    node page down in 1.7.0. Anything meta can't answer is classified by NAME instead.
export function nodeIfaces(node, { gone = false } = {}) {
  const meta = Store.describe[node] || {};
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  // the node's own mesh prefix wins over the fleet default (a mid-delete mesh iface loses its system
  // flag but keeps its swg_ name, so both spellings stay excluded)
  const pfx = nrec.mesh_prefix || (Store.panelSettings || {}).reserved?.iface_prefix || "swg_";
  const isSys = k => (meta[k] && meta[k].system) || k.startsWith(pfx) || k.startsWith("swg_");
  const wdtt = new Map(((Store.stats[node] || {}).wdtt || []).filter(w => w && w.iface).map(w => [w.iface, w]));
  const csqtt = new Map(((Store.stats[node] || {}).csqtt || []).filter(c => c && c.iface).map(c => [c.iface, c]));   // csqtt owns its own raw-TUN iface too
  const gonePfx = node + "|";
  const goneOn = gone ? Object.keys(Store.ifaceGone).filter(k => k.startsWith(gonePfx)).map(k => k.slice(gonePfx.length)) : [];
  const names = [...new Set([...Object.keys(meta).filter(k => !isSys(k)), ...wdtt.keys(), ...csqtt.keys(), ...goneOn.filter(k => !isSys(k))])];
  return orderById(names, nrec.iface_order, x => x).map(ifn => {
    const w = wdtt.get(ifn), cc = csqtt.get(ifn), m = meta[ifn];
    return {
      ifn, wdtt: !!w, csqtt: !!cc,
      type: (w || isWdttIface(ifn)) ? "wdtt" : (cc || isCsqttIface(ifn)) ? "csqtt" : (m && m.awg_params && Object.keys(m.awg_params).length) ? "awg" : "wg",
      muted: nodeStale(node) || (w ? (w.active !== "active" && !w.await_restore) : cc ? (cc.active !== "active") : ifaceNotUp(node, ifn)),
    };
  });
}
// One interface badge: protocol-coloured, links to the interface, and shows a start/stop/restart in
// flight in place of the plain name. Every badge row renders through this — two renderers is how the
// rows diverged in the first place.
export const IfaceTag = (node, { ifn, type, muted }) => {
  const op = Store.ifaceOp[node + "|" + ifn];   // op in flight → say so here too (optimistic, set on click)
  const href = "#/node/" + encodeURIComponent(node) + "/" + encodeURIComponent(ifn);
  const stop = e => e.stopPropagation();        // the fleet card is itself a link; the ribbon has nothing to bubble to
  return (op && op.phase === "busy")
    ? html`<a class="tg tg-busy" href=${href} onClick=${stop}><${Ic} i="clock"/>${ifn} ${ifopBusy(op.verb)}</a>`
    : html`<a class=${"tg tg-" + type + (muted ? " muted" : "")} href=${href} onClick=${stop}>${ifn}</a>`;
};
// interface tags for a node: each iface coloured by protocol, linking to its detail.
export const ifaceTags = node => nodeIfaces(node).map(x => IfaceTag(node, x));

// The other half of the same badge rows: the node's turn-proxies, in the operator's saved order.
// `turn_order` also holds "wdtt:<iface>" entries, because the Turn-proxies grid it comes from lists
// WDTT servers next to the proxies — those never match a tp.service, so they simply don't place a
// badge here, which is right: a WDTT server is already in the interface half of the row.
export const nodeTurns = node => {
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  return orderById(((Store.stats[node] || {}).turn_proxies) || [], nrec.turn_order, tp => tp.service);
};
// One turn-proxy badge: fork-coloured, labelled with the fork + the port it answers on.
export const TurnTag = (node, tp) =>
  html`<span class=${"tg tg-turn tf-" + turnFork(tp.service) + ((nodeStale(node) || turnDown(tp)) ? " muted" : "")}>${turnLabel(tp.service, portOf(tp.listen) || portOf(tp.connect))}</span>`;


// Node throughput panel: a Peers/Mesh toggle in the header (right-aligned) splits the graph into client (rx−mrx),
// mesh (mrx), or both. Never both off — turning off the only-selected one switches to the other (like the doughnuts).
// Node health panel: CPU/Mem/Disk meters + the CPU-load history, with the range picker hoisted into the header.
export function NodeHealthPanel({ name, nrec }) {
  const [range, setRange] = useState("live");
  const removing = nrec.removing ? html`<span class="nstat removing"><${Ic} i="trash"/> ${T("tag|flagged for removal")}</span><button class="btn btn-mini" style="margin-left:9px" title=${T("Cancel removal — keep this node")} onClick=${() => unflagNode(nrec)}>${T("Cancel")}</button>` : null;
  const actions = html`<div class="panel-tools">${removing}${nrec.health_history ? html`<${RangeTabs} range=${range} setRange=${setRange}/>` : null}</div>`;
  return html`<${Panel} icon="activity" title=${T("Health")} tone="online" actions=${actions}>
    <${HealthAlerts} health=${nrec.health}/>
    ${nrec.health_history
      ? html`<${RangedHistory} node=${name} kind="cpu" live=${nrec.health_history} liveFine=${nrec.health_live} h=${52} head=${html`<${HealthMeters} health=${nrec.health}/>`} range=${range} setRange=${setRange}/>`
      : html`<${HealthMeters} health=${nrec.health}/>`}
  <//>`;
}
export function NodeThroughput({ name, nrec }) {
  const [peers, setPeers] = useState(true);
  const [mesh, setMesh] = useState(true);
  const [range, setRange] = useState("live");
  const togP = () => { if (peers && !mesh) { setPeers(false); setMesh(true); } else setPeers(!peers); };
  const togM = () => { if (mesh && !peers) { setMesh(false); setPeers(true); } else setMesh(!mesh); };
  // Peers/Mesh sits on the LEFT (as the header's `lead`, right after the title); the range picker stays on the right.
  const lead = html`<div class="dcard-traf hdr-lead">
    <button class=${"tbadge peers" + (peers ? " on" : "")} onClick=${togP} title=${peers ? T("Hide client (peer) traffic") : T("Show client (peer) traffic")}>${T("Peers")}</button>
    <button class=${"tbadge mesh" + (mesh ? " on" : "")} onClick=${togM} title=${mesh ? T("Hide mesh (node-to-node relay) traffic") : T("Show mesh (node-to-node relay) traffic")}>${T("Mesh")}</button>
  </div>`;
  return html`<${Panel} icon="gauge" title=${T("Throughput")} lead=${lead} actions=${html`<${RangeTabs} range=${range} setRange=${setRange}/>`}>
    <${RangedHistory} node=${name} kind="throughput" live=${nrec.health_history} liveFine=${nrec.health_live} h=${72} traf=${{ peers, mesh }} range=${range} setRange=${setRange}/>
  <//>`;
}

// Per-node health: CPU / Memory / Disk on one row (each a third), with the CPU-load history
// charted below. `history=false` omits the inline chart (node detail uses RangedHistory instead).
// The CPU/Memory/Disk meter row — reused standalone (as the head of the node-detail Health
// chart row) and inside NodeHealth (overview cards).
export function healthCols(health) {
  const cols = [];
  const ncpu = health.ncpu || 1;
  const l1 = Array.isArray(health.load) ? (health.load[0] || 0) : null;
  const loadTxt = () => l1.toFixed(2) + " / " + ncpu + " " + cpuNamePl(health, ncpu);
  if (typeof health.cpu_pct === "number") {
    // Only bounded percentages get a bar. Load is unbounded and system-wide, so a bar clamped at 100%
    // would erase the one thing load adds over utilization: how DEEP the run queue is (util reads 100%
    // at load 1.0 and at load 8.0 alike). It lives as a plain number in the CPU hover bubble instead.
    cols.push({ label: T("CPU"), heat: true, cpu: true, pct: health.cpu_pct, text: Math.round(health.cpu_pct) + "%" });
  } else if (l1 !== null) {
    cols.push({ label: T("CPU load"), heat: true, pct: l1 / ncpu * 100, text: loadTxt() });   // older swg-noded: no cpu_pct, load-per-core as before
  }
  const m = health.mem;
  if (m && m.total) cols.push({ label: T("Memory"), pct: m.used / m.total * 100, text: fmtBytes(m.used) + " / " + fmtBytes(m.total) });
  const d0 = (health.disk || [])[0];
  if (d0 && d0.total) cols.push({ label: T("Disk"), pct: d0.used / d0.total * 100, text: fmtBytes(d0.used) + " / " + fmtBytes(d0.total) });
  return cols;
}
export function HealthMeters({ health }) {
  return html`<div class="health-cols">${healthCols(health).map(c => {
    const p = Math.min(100, Math.max(0, c.pct || 0));
    const heat = !!c.heat;                               // CPU bar+number: continuous green→red, like the graph
    const col = heat ? cpuColor(c.pct) : null;          // uncapped pct → an old node's overloaded load-per-core reads full red
    const body = html`<div class="hcol">
      <div class="hcol-top"><span class="hcol-l">${c.label}</span><span class="hcol-v" style=${col ? "color:" + col : ""}>${c.text}${c.cpu ? html`<${CpuWarnIc} health=${health}/>` : null}</span></div>
      <div class="hm-bar"><i class=${"hm-fill" + (heat ? "" : " " + htone(p))} style=${"width:" + p + "%" + (col ? ";background:" + col : "")}></i></div>
    </div>`;
    // the whole CPU meter (number + bar) is the hover target, saturated or not
    return c.cpu ? html`<${CpuPop} health=${health} trigger=${body}/>` : body;
  })}</div>`;
}
export function HealthAlerts({ health }) {
  const alerts = healthAlerts(health);
  return alerts.length ? html`<div class="halerts">${alerts.map(a => html`<span class=${"halert " + a.sev}><${Ic} i="warn"/> ${a.msg}</span>`)}</div>` : null;
}
export function NodeHealth({ health, node, compact, history, range, nodeHist }) {
  if (!health) return compact ? null : html`<div class="hint" style="margin:2px">${T("No health data reported yet.")}</div>`;
  const hh = (node && (Store.nodes || []).find(n => n.id === node) || {}).health_history || null;  // server-side RRD (node = id)
  // CPU history follows the dashboard range. `range` here is the range the passed nodeHist is FOR (the Overview passes
  // rangeHist.range) — it LAGS the just-clicked range while a fetch is in flight, so the chart keeps showing the last
  // loaded range's data until the new one lands (no flick to empty or to live).
  const useRanged = range && range !== "live" && nodeHist && Array.isArray(nodeHist.cpu) && nodeHist.cpu.some(x => x != null);
  const liveCpu = (hh && Array.isArray(hh.cpu) && hh.cpu.length > 1) ? hh.cpu : null;
  const cpuHist = useRanged ? nodeHist.cpu : liveCpu;
  const cpuTimes = useRanged ? nodeHist.t : (hh ? hh.t : null);
  const cpuRange = useRanged ? range : "live", cpuCap = useRanged ? (RANGE_CAP[range] || 0) : 0;
  const showHist = history !== false && !!cpuHist;
  return html`<div class="health">
    <${HealthAlerts} health=${health}/>
    <${HealthMeters} health=${health}/>
    ${showHist ? html`<div class="health-hist">
      <span class="hist-cap">${T("CPU history")}</span>
      <${MiniArea} points=${cpuHist} h=${compact ? 36 : 52} times=${cpuTimes} range=${cpuRange} cap=${cpuCap}/>
    </div>` : null}
  </div>`;
}

export let hostUpdating = false;                 // once Update is clicked, lock the header pill into "updating"
export let hostUpdRepairing = false;             // that update was a REPAIR (triggered while up to date) → pill says "repairing…"
export let pendingUpdateDone = null;             // [from,to] of a panel version bump, held until the WHOLE host update finishes (a master's panel restarts mid-update, before the node phase — don't pop the "updated" dialog yet)
// the circular-arrow glyph (same as the check icon), spun in yellow while an update runs
export const UPD_SPIN_SVG = `<svg class="updspin" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 4v4h-4"/></svg>`;
export const WARN_SVG = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>`;
export const X_SVG = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>`;
export const CHECK_SVG = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>`;
export const INFO_SVG = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>`;
// The App header drives this from the poll: an imported binding is read-only, so the version-bump
// bookkeeping goes through setters rather than assignment at a distance.
export function noteHostUpdateDone(from, to) { hostUpdating = false; pendingUpdateDone = [from, to]; }
export function setSeenPanelVer(v) { seenPanelVer = v; }
export function takePendingUpdateDone() { const u = pendingUpdateDone; pendingUpdateDone = null; return u; }

export function setHostUpdating() {
  hostUpdating = true;
  hostUpdRepairing = !Store.panelOutdated;   // up to date when triggered ⇒ it's a repair (Fix / re-run), not a version update
  const slot = $("#updslot");
  if (slot) slot.innerHTML = `<span class="livepill upd-busy">${esc(hostUpdRepairing ? T("repairing…") : T("updating…"))} ${UPD_SPIN_SVG}</span>`;
  Store.apply();   // re-render the whole SPA so a co-located (local) node tile flips at the SAME instant, not on the next poll
}
export let seenPanelVer = null;   // detect the panel coming back on a new version (after an update), to prompt a hard reload
export function openUpdateDone(from, to) {
  openModal(html`<${Sheet} title=${T("Panel updated")}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-primary" onClick=${() => location.reload()}>${T("Reload now")}</button></>`}>
    <div class="updone">
      <p>${updatedFromTo(from, to)}</p>
      <p>${T("To be sure every change takes effect, give the panel a hard reload — it drops the cached app so the new version loads cleanly.")}</p>
      <p class="updone-hint">${T("Press")} <kbd>Ctrl</kbd><kbd>Shift</kbd><kbd>R</kbd></p>
    </div>
  <//>`);
}
// One consistent update modal for both a node and the panel header: the full (third-party-included) command to
// run by hand, plus an "Update now" button that kicks off the automatic swg-only update.
export function openUpdateModal({ title, side, onConfirm }) {
  const full = "curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s update";
  const go = async () => { closeModal(); await onConfirm(); };
  openModal(html`<${Sheet} title=${title}
    foot=${footRow({ onCancel: closeModal, onAction: go, action: T("Update now") })}>
    <div class="iface-intro" style="font-size:14px;line-height:1.55"><div>${fullUpdateIntro(side)}</div></div>
    <div class="field"><div class="ipk-field"><span class="ipk-val" style="text-align:left">${full}</span><button class="copybtn" onClick=${() => copy(full, T("Command copied"))}><${Ic} i="copy"/></button></div></div>
    <div class="iface-intro" style="font-size:14px;line-height:1.55;margin-top:26px;margin-bottom:2px"><div>${autoUpdateIntro(side)}</div></div>
  <//>`);
}
export function updateNode(n) {
  openUpdateModal({
    title: T("Update {name}", { name: n.name }), side: T("node's"),
    onConfirm: async () => { const r = await api.nodeSelfUpdate({ node: n.id }); if (r.ok) { await Store.poll(); toast(T("Update requested — applies on the node's next sync."), "ok"); } else toast(srvText(r) || T("Failed to request update."), "err"); },
  });
}
export function updateHost() {
  openUpdateModal({
    title: T("Update this server"), side: T("panel's"),
    onConfirm: async () => {
      const r = await api.hostUpdate();
      if (!r.ok) return toast(srvText(r) || T("Failed to start update."), "err");
      if (r.data && r.data.manual) return toast(T("Automatic update isn't wired on this install — run the command shown in the dialog on the host."), "err");
      setHostUpdating(); toast(T("Update started — the panel will restart shortly."), "ok");
    },
  });
}
export async function checkForUpdate(e, nodeId) {
  const btn = e && e.currentTarget;                  // spin + cyan it while we poll, so it reads as "searching"
  if (btn) btn.classList.add("checking");
  if (!nodeId) { Store.hostChecking = true; Store.apply(); }   // panel-header check → show a "checking…" pill
  try {
    const r = await api.checkUpdate();
    await Store.poll();
    if (!r.ok) toast(srvText(r) || T("Couldn't check for updates."), "err");
    else if (r.data && !r.data.checked) toast(T("Couldn't reach the repo to check for updates."), "err");
    else if (nodeId) {                               // invoked from a NODE header → show the result THERE, not on the panel header
      const n = (Store.nodes || []).find(x => x.id === nodeId);   // outdated → its "update node" button appears; up-to-date → flash on the node row
      if (!(n && n.outdated)) { Store.nodeUpdFlash = { id: nodeId, until: Date.now() + 5000 }; Store.apply(); setTimeout(() => Store.apply(), 5100); }
    }
    else if (r.data && r.data.panel_outdated) toast(T("Update available — v{ver}", { ver: r.data.latest_remote }), "ok");
    else if (serviceIssues().length) toast(T("{v1} can be repaired — click “Fix”", { v1: plural(serviceIssues().length, "issue") }), "ok");   // up to date, but self-heals are pending
    else { Store.updFlash = Date.now() + 15000; Store.apply(); setTimeout(() => Store.apply(), 15100); }   // panel up to date + healthy → T("up to date") pill (clickable to re-run/repair) for 15s
  } finally { if (btn) btn.classList.remove("checking"); if (!nodeId) { Store.hostChecking = false; Store.apply(); } }
}
// Rich hover bubble for the innerHTML header update widget (no Preact there) — right-aligned under the anchor;
// contentFn() returns HTML (empty string → no bubble). Replaces the plain title= tooltip.
export function hostHoverBubble(anchor, contentFn) {
  // SINGLETON, self-hiding bubble. The header is innerHTML-driven and re-renders every poll, replacing `anchor` —
  // so the anchor's own mouseleave can't be trusted to clean up. Guard against orphans (remove any stray bubble
  // before showing) and hide when the pointer leaves the BUBBLE too, so it never gets stuck or stacks a glow.
  let bub = null, t = null;
  const hide = () => {                                   // a poll re-render removes the anchor → its mouseleave fires; if the
    if (bub && bub.matches(":hover")) { later(); return; }   // pointer is actually over the BUBBLE, keep it (don't vanish mid-read)
    clearTimeout(t); if (bub) { bub.remove(); bub = null; }
  };
  const later = () => { clearTimeout(t); t = setTimeout(hide, 140); };   // grace to travel between anchor and bubble
  const show = () => {
    clearTimeout(t);
    if (bub && bub.isConnected) return;                                   // already showing → don't stack
    document.querySelectorAll(".hostupd-bub").forEach(x => x.remove());   // kill any orphan left by a re-render
    const inner = contentFn(); if (!inner) return;
    bub = document.createElement("div");
    bub.className = "deppop hostupd-bub";
    bub.innerHTML = inner;
    document.body.appendChild(bub);
    const r = anchor.getBoundingClientRect();
    bub.style.top = Math.round(r.bottom + 8) + "px";
    bub.style.left = Math.round(r.right) + "px";
    bub.style.transform = "translateX(-100%)";   // right edge aligns under the button
    bub.addEventListener("mouseenter", () => clearTimeout(t));
    bub.addEventListener("mouseleave", later);
  };
  anchor.addEventListener("mouseenter", show);
  anchor.addEventListener("mouseleave", later);
}
// Panel-version changelog bubble — an EXACT copy of the update-to-version hover bubble (same .hub-* markup + the same
// self-hiding, hover-safe singleton mechanism, so it stays open while the pointer is over it), plus ‹ older / › newer
// buttons to browse releases. Changelog fetched once and cached.
let _changelogCache = null;   // {entries:[{version,date,notes[]}], current}
let _changelogIdx = 0;
export function versionHoverBubble(anchor) {
  let bub = null, t = null;
  const hide = () => { if (bub && bub.matches(":hover")) { later(); return; } clearTimeout(t); if (bub) { bub.remove(); bub = null; } };
  const later = () => { clearTimeout(t); t = setTimeout(hide, 140); };
  const paint = () => {
    if (!bub) return;
    if (!_changelogCache) { bub.innerHTML = `<div class="hub-list"><div class="hub-row faint"><span class="hub-txt">${esc(T("Loading changelog…"))}</span></div></div>`; return; }
    const es = _changelogCache.entries || [];
    if (!es.length) { bub.innerHTML = `<div class="hub-h"><span class="hub-title">${esc(T("Changelog"))}</span></div><div class="hub-list"><div class="hub-row faint"><span class="hub-txt">${esc(T("No changelog available."))}</span></div></div>`; return; }
    _changelogIdx = Math.max(0, Math.min(_changelogIdx, es.length - 1));
    const e = es[_changelogIdx], cur = _changelogCache.current || "";
    bub.innerHTML = hubEntryHtml({
      titleHtml: `<b>${esc(e.version)}</b>${e.version === cur ? ` <span class="hub-cur">${esc(T("installed"))}</span>` : ""}`,
      date: e.date, notes: e.notes, nav: { older: _changelogIdx < es.length - 1, newer: _changelogIdx > 0 } });
    bub.querySelectorAll(".hub-nav").forEach(b => b.addEventListener("click", ev => { ev.stopPropagation(); if (b.disabled) return; _changelogIdx += (+b.dataset.nav); paint(); }));
  };
  const show = () => {
    clearTimeout(t);
    if (bub && bub.isConnected) return;
    document.querySelectorAll(".hostupd-bub.verbub").forEach(x => x.remove());   // kill any orphan from a header re-render
    bub = document.createElement("div"); bub.className = "deppop hostupd-bub verbub";
    document.body.appendChild(bub);
    const r = anchor.getBoundingClientRect();
    bub.style.top = Math.round(r.bottom + 8) + "px";
    bub.style.left = Math.round(r.left) + "px";
    bub.addEventListener("mouseenter", () => clearTimeout(t));
    bub.addEventListener("mouseleave", later);
    paint();
    if (!_changelogCache) api.changelog().then(res => {
      _changelogCache = (res && res.ok) ? res.data : { entries: [] };
      const i = (_changelogCache.entries || []).findIndex(x => x.version === (_changelogCache.current || ""));
      _changelogIdx = i >= 0 ? i : 0;
      if (bub) paint();
    });
  };
  anchor.addEventListener("mouseenter", show);
  anchor.addEventListener("mouseleave", later);
}
// Bold the "lead" of a changelog line — the phrase up to its first sentence period, colon, or em-dash (capped so a
// long clause can't bold half the row); otherwise the first few words. Returns [lead, rest].
export function noteLead(n) {
  n = String(n).trim();
  const dot = n.indexOf(". "), dash = n.search(/\s[—–-]\s/);
  let cut = -1, keep = 0;
  if (dot >= 0 && dot <= 54 && (dash < 0 || dot < dash)) { cut = dot; keep = 1; }        // include the '.'
  else if (dash >= 0 && dash <= 54) { cut = dash; keep = 0; }
  if (cut < 0) { const w = n.split(" "); return [w.slice(0, 3).join(" "), w.slice(3).join(" ")]; }
  return [n.slice(0, cut + keep).trim(), n.slice(cut + keep).replace(/^\s*[—–-]\s*/, "").trim()];
}
// ONE renderer for the changelog hover bubbles — the update-to-version pill AND the panel-version bubble show the
// SAME changelog, so they share this. opts.nav={older,newer} adds ‹ older / › newer; opts.footer adds a CTA row.
export function hubEntryHtml({ titleHtml, date, notes, emptyNote, footer, nav }) {
  const rows = (notes && notes.length) ? notes.map(n => { const [lead, rest] = noteLead(n);
      return `<div class="hub-row"><span class="hub-bul"></span><span class="hub-txt"><b>${esc(lead)}</b>${rest ? " " + esc(rest) : ""}</span></div>`; }).join("")
    : `<div class="hub-row faint"><span class="hub-txt">${esc(emptyNote || T("No notes for this release."))}</span></div>`;
  const navGroup = nav ? `<span class="hub-nav-group"><button class="hub-nav" data-nav="1"${nav.older ? "" : " disabled"} title="${esc(T("Older release"))}">${esc(T("‹ Prev"))}</button><button class="hub-nav" data-nav="-1"${nav.newer ? "" : " disabled"} title="${esc(T("Newer release"))}">${esc(T("Next ›"))}</button></span>` : "";
  return `<div class="hub-h"><span class="hub-title">${titleHtml}</span>${navGroup}${date ? `<span class="hub-date">${esc(date)}</span>` : ""}</div>`
    + `<div class="hub-list">${rows}</div>`
    + (footer ? `<div class="hub-foot">${esc(footer)}</div>` : "");
}
export function updBubbleHtml() {
  return hubEntryHtml({ titleHtml: `What's new in <b>${esc(Store.latestRemote || "?")}</b>`, date: Store.latestRemoteDate,
    notes: Store.latestRemoteNotes || [], emptyNote: T("See the changelog for what's new."), footer: T("Click to update this server.") });
}
export function fixBubbleHtml() {
  const iss = serviceIssues(); if (!iss.length) return "";
  const head = `<div class="hub-h">${T("{v1} to fix", { v1: plural(iss.length, "issue") })}</div>`;
  const body = iss.map(i => `<div class="hub-row"><span class="hub-dot ${i.sev}"></span><span><b>${esc(i.label)}</b> — ${esc(i.msg)}</span></div>`).join("");
  return head + body + `<div class="hub-foot">${esc(T("Click to review & run the repair."))}</div>`;
}
export function NodeCard({ n, reorder }) {
  const it = reorder ? reorder.item(n.id) : null;
  const st = n.status || "dangling";
  const here = Store.recon.peers.filter(p => p.targets.some(t => t.node === n.id));
  const onl = here.filter(p => p.targets.some(t => t.node === n.id && t.online)).length;
  const snap = Store.stats[n.id];
  const tps = nodeTurns(n.id);      // turn-proxies in the operator's order (same list the ribbon shows)
  const ifTags = ifaceTags(n.id);   // every interface tag, one wrapping line
  const h = n.health, cpuUtil = h && typeof h.cpu_pct === "number";
  const hasCpu = cpuUtil || (h && Array.isArray(h.load));
  const l1 = (h && Array.isArray(h.load)) ? (h.load[0] || 0) : 0;
  // Utilization when the node reports it; load-per-core for an older swg-noded (which can exceed 100).
  const cpctRaw = cpuUtil ? h.cpu_pct : l1 / ((h && h.ncpu) || 1) * 100, cpct = Math.min(100, cpctRaw);   // cpctRaw (uncapped) colours the bar+number green→red like the graph; cpct caps the bar width
  const cpuLabel = cpuUtil ? T("CPU") : T("CPU load"), cpuText = cpuUtil ? Math.round(cpctRaw) + "%" : l1.toFixed(2);
  const removing = n.removing;
  const nblocked = st !== "online" || inProc(n.proc_status);  // down OR mid convert/re-install
  // list-card update tag: a co-located node updates WITH the panel (its "updating" comes from hostUpdating, not
  // its own proc_status) — mirror the detail's dh-ver so the LIST shows "updating" too, while a terminal wins.
  const nUpdating = n.updating || (n.local && (hostUpdating || inProc(Store.hostProc)));
  const procEff = (n.proc_status && !inProc(n.proc_status)) ? n.proc_status : (nUpdating ? "updating" : n.proc_status);   // i18n-keys
  const nav = () => go("#/node/" + encodeURIComponent(n.id));
  return html`<div class=${"ncard clk" + (removing ? " removing" : "") + (it ? it.cls : "")} onClick=${nav} data-rid=${it ? it.rid : null}>
    <div class="nc-gutter">${reorder ? html`<span class="drag-grip" title=${T("Drag to reorder")} onClick=${e => e.stopPropagation()} ...${reorder.grip(n.id)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span>` : null}</div>
    <div class="nc-name">
      ${!n.uninstalled && (n.outdated || (n.local && Store.panelOutdated)) && !n.updating ? html`<span class="upd-dot" title=${T("Update available — open the node to update")}><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 4v4h-4"/></svg></span>` : null}
      <span class="nname">${n.name}</span>
      ${n.kind ? html`<span class=${"tport " + n.kind}>${n.kind === "docker" ? T("kind|docker") : T("kind|bare-metal")}</span>` : null}
      ${n.uninstalled ? html`<span class="nstat uninst"><${Ic} i="info"/> ${T("tag|uninstalled")}</span>`
        : st === "online" ? html`<span class="reporting">${T("reporting")}</span>`
        : st === "offline" ? html`<span class="nstat offline"><${Ic} i="info"/> ${T("tag|offline")}</span>`
        : html`<span class="nstat enroll"><${Ic} i="clock"/> ${T("awaiting enroll")}</span>`}${procEff ? procTag(procEff, e => { e.stopPropagation(); e.preventDefault(); dismissNodeProc(n.id); }, n.proc_err, st !== "online" && st !== "offline") : null}
      <span style="margin-left:8px"><${HealthDot} issues=${n.issues}/></span>
      ${removing ? html`<span class="nstat removing" style="margin-left:14px"><${Ic} i="trash"/> ${T("tag|flagged for removal")}</span>` : null}
    </div>
    <div class="nc-mesh nm-item">${(n.mesh_peers || []).length ? html`<${MeshStat} nodeId=${n.id} mode="both"/>` : null}</div>
    <div class="nc-cpu nm-item"><span class="nm-l">${cpuLabel}</span>${hasCpu ? html`<${CpuPop} health=${h} alignRight=${true} trigger=${html`<span class="nm-cpu"><span class="hm-bar"><i class="hm-fill" style=${"width:" + cpct + "%;background:" + cpuColor(cpctRaw)}></i></span><span class="nm-v" style=${"color:" + cpuColor(cpctRaw)}>${cpuText}</span><${CpuWarnIc} health=${h}/></span>`}/>` : html`<span class="nm-v faint">—</span>`}</span>
    <button class="iconbtn nc-ctl" disabled=${nblocked} title=${nblocked ? T("Unavailable while the node is down / converting") : T("Node settings")} onClick=${e => { e.stopPropagation(); openNodeEdit(n); }}><${Ic} i="gear"/></button>

    <span class="nc-peers nm-item">${here.length
      ? html`<${OnlinePeersTag} nodeId=${n.id} orphans=${orphCount(n.id, null)} cls="nm-peerpop"
          trigger=${() => html`<span class="nm-l">${T("Peers")}</span><span class="nm-v nm-peers"><b class=${"oncount" + (onl ? " on" : "")}>${onl}</b><small>/${here.length}</small></span>`}/>`
      : html`<span class="nm-l">${T("Peers")}</span><span class="nm-v nm-peers faint">${T("val|none")}</span>`}</span>
    <div class="nc-ifaces nm-item"><span class="nm-l">${T("Interfaces")}</span><span class="tags">${ifTags.length ? ifTags : html`<span class="nm-v faint">—</span>`}</span></div>
    <span class="nc-thru nm-thru"><span class="nm-l">${T("Throughput")}</span>${st === "online"
      ? html`<span class=${"nm-v thru" + ((n.rx_speed || 0) + (n.tx_speed || 0) > 0 ? "" : " idle")}><span class="down">↓ ${rate(dlul(n.rx_speed, n.tx_speed)[0])}</span><span class="up">↑ ${rate(dlul(n.rx_speed, n.tx_speed)[1])}</span></span>`
      : html`<span class="nm-v faint">—</span>`}</span>
    <button class="iconbtn nc-ctl danger" title=${removing ? T("Force remove") : T("Remove node")} onClick=${e => { e.stopPropagation(); openNodeRemove(n); }}><${Ic} i="trash"/></button>

    ${turnEnabled() && tps.length ? html`<div class="nc-turn nm-item"><span class="nm-l">${T("Turn-proxies")}</span><span class="tags">${tps.map(tp => TurnTag(n.id, tp))}</span></div>` : null}
  </div>`;
}

