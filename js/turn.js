/* turn.js — the turn-proxy family: the proxies themselves, their client apps, and WDTT.
 *
 * LAYER 5 (see docs/APP-JS-SPLIT-PLAN.md). The largest domain in the SPA.
 *
 * WDTT lives here rather than in its own module because it IS a member of this family — a self-contained,
 * key-owning server that an operator reaches through the same cards, the same fork tags and the same
 * lifecycle badges as any other fork. Splitting it out would organise the code by implementation rather
 * than by what the operator is looking at.
 *
 * What is NOT here: the interface PAGE that renders these (iface.js, next), the fork catalog itself
 * (turn-catalog.js), and the shared lifecycle/egress primitives that both this and iface.js need — those
 * were distributed to ui.js and routing.js first, which is what let this come out with a one-way edge.
 */

import { T, Trich, Tsplit, plural, srvText } from "./i18n.js";
import { esc, portOf, ipOf, ipPickerVal, seen, ago, dur, fmtBytes, rate, isWdttIface, isCsqttIface, isSelfContainedKind } from "./util.js";
import { Store, api, bus, useStore } from "./store.js";
import { pickThemed, toThemed } from "./theme.js";
import {
  TURN_FORKS_FALLBACK, turnLabel, turnFork, turnOwner, turnForkList, turnForksVisible, forkLabel,
  forkSupportsAwg, turnColor, turnClientColor, turnClientAuthor,
} from "./turn-catalog.js";
import { kindOf, iTypeOf, targetType, nodeStale, ifaceNotUp, turnDown, turnProxiesFor, wdttOn,
         suggestPort, portHolder, portErrMsg, nextWdttName, cidrNet, subnetsOverlap, subnetFleetConflict,
         subnetServerAddr, suggestSubnet, ghostIface } from "./model.js";
import {
  Ic, ICON, Tag, Panel, Badge, StatusTag, CmdErr, Sheet, footRow, secTitle, SearchBox, Switch, Dropdown,
  Disclosure, autoGrow, IpPicker, NodeIpPick, Popover, Portal, toast, copy, mutate, rowError, openModal,
  pushModal, closeModal, closeAllModals, openConfirm, openChildOrRoot, useReorder, GRIP_SVG, opTag, procTag,
  inProc, statusLabel, goSettings, goSettingsTurnIps, takePendingTurnIps, trackIfaceOps, startOrRestartWdtt, startOrRestartCsqtt,
  ifaceReady, ifaceWasBusy, RowError, LogBody, logRaw, logRendered, rowSingle, rowDouble, rowNoSelect,
  ConfirmSheet, orderById, procLabel,
} from "./ui.js";
import { EgressPicker, egressInit, egressError, egressBody, ifTrafficBadge, BlockTraffic, RoutingRules } from "./routing.js";
import { turnConnRows, wdttConnRows, OnlPop, OnlinePeersTag, orphCount } from "./views.js";
import { IfaceThroughput, RangedHistory } from "./charts.js";
import { buildConf, downloadConf, QR, qrDataURL, turnArtifact, turnClientsFor, subFeatureOn,
         wdttResealForNode } from "./crypto.js";
import { h, Fragment } from "preact";
import { useState, useEffect, useRef, useMemo } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// turn create/edit sheet heading: "Turn-proxy · <title> · <fork>" (title omitted when blank)
export function turnSheetTitle(fork, title) { return T("Turn-proxy · {v1}", { v1: ((title || "").trim() ? (title.trim() + " · ") : "") + fork }); }
// a fresh 64-hex wrap key (browser crypto) — used to pre-fill the create form's params for obfuscation forks
export function randWrapKey() { const a = new Uint8Array(32); crypto.getRandomValues(a); return Array.from(a, b => b.toString(16).padStart(2, "0")).join(""); }








// turn badges for an interface card: one fork-coloured "turn" chip per distinct forwarding fork
// (collapses to one in the common single-fork case), greyed when that fork's proxies are all down / node stale.
// When MORE THAN 3 turn-proxies forward here the per-fork list gets noisy, so collapse to ONE badge in the
// general turn colour + a "×N" count; hovering opens a small portaled bubble listing each proxy as a
// fork-coloured badge + its title.
// hover bubble body for a set of forwarding proxies: one line each — fork badge (own colour) + title.
export function turnListRows(list) {
  return list.map(tp => { const f = turnFork(tp.service); return html`<div class=${"turnlist-row" + (turnDown(tp) ? " muted" : "")}>
    <span class="tg tg-turn" style=${"--tfc:" + turnColor(f)}>${f}</span>${tp.title ? html`<span class="turnlist-ttl">${tp.title}</span>` : null}</div>`; });
}
// each turn badge on an interface card gets a hover-only bubble listing its proxies; clicks fall through to
// the card link (hoverOnly). ≤3 forwarding proxies → one fork-coloured chip per fork; >3 → collapse to one
// general-colour "turn ×N" badge (the per-fork list gets noisy), same bubble listing all of them.
export function ifaceTurnBadges(node, fwdTurns, compact) {
  if (!fwdTurns || !fwdTurns.length) return null;
  const stale = nodeStale(node);
  const bubble = (trigger, list) => html`<${Popover} hoverOnly cls="turncollwrap" popCls="turnlist" trigger=${trigger}>${turnListRows(list)}<//>`;
  if (fwdTurns.length > 3) {
    const allDown = fwdTurns.every(turnDown);
    const trigger = html`<span class=${"tg tg-turn tf-gen turncoll" + ((stale || allDown) ? " muted" : "") + (compact ? " mini" : "")}>${compact ? "t" : "turn"}<b class="turnx">×${fwdTurns.length}</b></span>`;
    return bubble(trigger, fwdTurns);
  }
  const groups = {};
  fwdTurns.forEach(tp => { const f = turnFork(tp.service); (groups[f] = groups[f] || []).push(tp); });
  return Object.entries(groups).map(([f, list]) => {
    const allDown = list.every(turnDown);
    const trigger = html`<span class=${"tg tg-turn tf-" + f + ((stale || allDown) ? " muted" : "") + (compact ? " mini" : "")}>${compact ? "t" : "turn"}</span>`;
    return bubble(trigger, list);
  });
}

// Optimistic title: a title is a cosmetic panel-side label with no node round-trip, so show the new value on the
// card the instant Save is clicked (pushOptTitle) instead of waiting for the next poll. Cleared once the server
// reports it, or after 20s as a safety net.
const _optTitle = {};   // "kind|node|id" -> { title, at }
export function pushOptTitle(key, title) { _optTitle[key] = { title: (title || "").trim(), at: Date.now() }; Store.apply(); }
export function shownTitle(key, real) {
  const o = _optTitle[key];
  if (!o) return real || "";
  if ((real || "") === o.title || Date.now() - o.at > 20000) { delete _optTitle[key]; return real || ""; }
  return o.title;
}
// One turn-proxy card — shared by the node detail (Forwards-to shown) and the interface detail
// (showForwards=false, that view is already scoped to the fronted iface). Same data, status tags,
// online/down dimming, click-to-manage. `metas` = the node's all-interface metas (Store.describe[node]).
export function TurnCard({ node, tp, nrec, metas, showForwards = true, reorder }) {
  metas = metas || {};
  const it = reorder ? reorder.item(tp.service) : null;
  const lp = portOf(tp.connect);
  const fronted = Object.keys(metas).find(i => String((metas[i] || {}).listen_port) === lp);
  const ftype = (fronted && metas[fronted].awg_params && Object.keys(metas[fronted].awg_params).length) ? "awg" : "wg";
  const _pendRaw = (nrec.turn_pending || {})[tp.service];
  const pend = _pendRaw === "title" ? undefined : _pendRaw;   // a cosmetic title rename is not a disruptive pending — never dim / "creating" / busy the card for it
  const err = (nrec.cmd_errors || {})[tp.service];
  const prog = (nrec.cmd_progress || {})[tp.service];   // node "what's happening now" (slow GitHub download / retry) → yellow note
  const installing = !!tp.installing;   // actively being downloaded / (re)created right now
  const queued = !!tp.pending;          // not up yet, waiting its turn in the sequential reconcile
  const failed = !!tp.failed;
  const stopped = !!tp.stopped;   // intentionally stopped from the panel (kept down)
  const down = tp.running === false && !installing && !queued && !failed && !stopped;   // not-running, not in any in-flight state
  const converting = (nrec.proc_status || "").startsWith("converting");   // node is mid bare↔docker convert → every card "converting"
  const k = node + "|" + tp.service;
  const justRestarted = !pend && turnRestarted[k] && Date.now() < turnRestarted[k];
  const updating = pend && turnUpdating[k] && Date.now() < turnUpdating[k];   // a pending reinstall triggered by an "Update" click
  // in-flight label: a fresh install/reinstall reads "creating"; any other queued action (manage/rotate/…) reads its
  // action word. An Update-click reinstall walks pending (queued, node hasn't picked it up) → updating (node is
  // actively downloading/recreating — signalled by the install marker or a live progress note).
  const pendLabel = updating ? ((installing || prog) ? T("updating") : T("turn|pending"))
    : (pend && pend !== "install" && pend !== "reinstall") ? (turnPendLabel(pend) || T("turn|creating")) : T("turn|creating");
  // Two dims (see app.css): `dim` = THIS proxy needs attention or is in flight — dim through the whole
  // 'creating' phase (installing/queued/assigned) plus failed/down/stopped/deleting; only a settled card is
  // full-bright. `nblocked` = the NODE forbids editing (offline / converting / re-installing / updating), which
  // is exactly what disables the buttons — so every card on the page dims together, not just the mesh ones.
  const dim = !justRestarted && (installing || queued || pend || failed || down || stopped || err);
  const nblocked = nodeStale(node) || inProc(nrec.proc_status);
  const _busy = !!(queued || installing || (pend && pend !== "delete"));   // any in-flight create / install / op
  const _bad = !!(failed || down || converting || stopped);
  const _settled = !!fronted && !_bad && !_busy;                           // up + healthy
  if (turnWasInstalling[k] && !installing && !_bad) turnReady[k] = Date.now() + 5000;   // OPTIMISTIC: install just ended without failing → "ready" NOW
  if (turnWasBusy[k] && _settled) {                    // settled after any in-flight state
    turnReady[k] = Date.now() + 5000;
    if (turnWasUpd[k]) { turnUpdatedFlash[k] = Date.now() + 5000; delete turnUpdating[k]; }   // it was mid-Update → green "updated" (bare-metal reinstalls set no install marker, so key off the update flag itself)
  }
  turnWasUpd[k] = updating;   // remember for the next render's settle check
  turnWasInstalling[k] = !!installing;
  turnWasBusy[k] = _busy;
  const turnReadyNow = !_bad && !!fronted && !!turnReady[k] && Date.now() < turnReady[k];
  const conn = fronted ? turnConnRows(node, fronted, tp.service) : [];   // online peers via THIS specific proxy → header count
  const canOpen = nrec.turn_manage && !nblocked && !_busy && pend !== "delete";   // clickable only once it settles — NOT while creating/queued/deleting, and never while the node blocks edits (don't open a half-created proxy)
  return html`<div class=${"ifcard tp" + (canOpen ? " clickable" : "") + (dim ? " down" : "") + (nblocked ? " locked" : "") + (it ? it.cls : "")} onClick=${canOpen ? () => openTurnManage(node, tp) : null} data-rid=${it ? it.rid : null}>
    <div class="ifcard-top">${reorder ? html`<span class="drag-grip" title=${T("Drag to reorder")} onClick=${e => e.stopPropagation()} ...${reorder.grip(tp.service)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span>` : null}<span class=${"iftype turn tf-" + turnFork(tp.service)}>${T("val|turn")}</span><span class="ifname">${shownTitle("t|" + node + "|" + tp.service, tp.title) || turnFork(tp.service)}</span><span class="grow"></span>${conn.length ? html`<${OnlPop} peer title=${T("Via this turn-proxy")} cls="ifc-conn" rows=${conn} trigger=${c => html`<b class="oncount on">${c}</b>`}/>` : null}${converting
      ? html`<${StatusTag} cls="tg-convert" icon="clock" label="converting" title=${T("The node is converting between bare-metal and docker")}/>`
      : pend === "delete"
      ? html`<${StatusTag} cls="tg-busy del" label=${T("deleting…")} msg=${err || prog} title=${err ? T("Command failed on the node") : T("Working on the node")}/><button class="xbtn" title=${T("Cancel this request")} onClick=${e => { e.stopPropagation(); cancelTurn(node, { service: tp.service }); }}><${Ic} i="x"/></button>`
      : installing ? html`<${StatusTag} cls=${"tg-busy" + (prog ? " warn" : "")} icon="clock" label=${pendLabel} msg=${prog} title=${T("The node is setting it up right now")}/>`
      : turnReadyNow ? html`<span class=${"tg " + ((turnUpdatedFlash[k] && Date.now() < turnUpdatedFlash[k]) ? "tg-ok" : "tg-ready")}><${Ic} i="check"/>${(turnUpdatedFlash[k] && Date.now() < turnUpdatedFlash[k]) ? T("updated") : T("turn|ready")}</span>`
      : (pend || queued) ? html`<${StatusTag} cls="tg-busy" icon="clock" label=${pend ? pendLabel : "creating"} msg=${err} title=${pend ? T("The node is setting it up") : T("Queued — the node creates these one at a time")}/>${pend ? html`<button class="xbtn" title=${T("Cancel this request")} onClick=${e => { e.stopPropagation(); cancelTurn(node, { service: tp.service }); }}><${Ic} i="x"/></button>` : null}`
      : failed ? html`<${StatusTag} cls="tg-busy del" icon="warn" label=${T("install failed")} msg=${err || T("the install failed on the node")} title=${T("Command failed on the node")}/>`
      : justRestarted ? html`<span class="tg tg-ok"><${Ic} i="check"/>${T("tag|restarted")}</span>`
      : stopped ? html`<span class="tg-off" title=${T("Stopped from the panel — open to Start it")}><${Ic} i="stop"/>${T("tag|stopped")}</span>`
      : down ? html`<${StatusTag} cls="tg-busy del" label="down" msg=${err || T("service is not running on the node")} title=${T("Service down on the node")}/>`
      : (!fronted ? html`<span class="tg tg-warn" title=${T("Forwards to a port with no managed interface behind it — likely a misconfiguration.")}>${T("tag|unbound")}</span>` : null)}</div>
    <div class="ifcard-rows">
      <div class="ifrow"><span class="l">${T("Turn-proxy fork")}</span><span class="r">${turnFork(tp.service)}</span></div>
      <div class="ifrow"><span class="l">${T("Listen")}</span><span class="r addr">${tp.listen || "—"}</span></div>
      ${showForwards ? html`<div class="ifrow"><span class="l">${T("Forwards to")}</span><span class="r">${fronted ? html`<a class=${"tg tg-" + ftype + ((nodeStale(node) || ifaceNotUp(node, fronted)) ? " muted" : "")} href=${"#/node/" + encodeURIComponent(node) + "/" + encodeURIComponent(fronted)} onClick=${e => e.stopPropagation()}>${fronted}</a>` : (tp.connect || "—")}</span></div>` : null}
    </div></div>`;
}

// The turn-proxies block — ONE component for both the node screen and the interface screen, so the cards
// never drift. Pass `iface` to scope it to one interface: it then (1) uses a different title, (2) shows only
// the proxies that forward to that interface, and (3) drops the "Forwards to" row. Everything else (the
// cards, the Setup button, pending/onboarding chips) is the node view and is omitted when scoped.
export function TurnProxiesBlock({ node, nrec, snap, metas, title, iface }) {
  snap = snap || Store.stats[node] || {}; metas = metas || Store.describe[node] || {}; nrec = nrec || {};
  const all = snap.turn_proxies || [];
  // A turn-proxy fronts a USER wg/awg interface (exactly what SetupTurnSheet offers — never a mesh link, never a
  // WDTT iface, which owns its own transport). With none on the node there is nothing to forward to, so hide the
  // button rather than open a sheet with an empty target list. Inline, not isSysName(): that is a local of the
  // node screen, and calling it here throws at render and takes the whole panel down.
  const _canFrontTurn = Object.entries(metas).some(([n, b]) => (b || {}).listen_port && !((b || {}).system || String(n).startsWith("swg_") || isWdttIface(n)));
  const cards = iface ? turnProxiesFor(node, iface) : orderById(all, nrec.turn_order, tp => tp.service);
  // WDTT forks are self-contained turn-family servers (own their interface) — rendered as cards in THIS section
  // (node view only; a WDTT instance doesn't "forward to" an iface, so it never appears in the per-iface subset).
  // On a WDTT interface page the section shows the server that OWNS that interface: a WDTT fork IS a
  // turn-family server, so its card belongs here — it just isn't something a proxy "forwards to", which is
  // why the per-iface list of `cards` is empty for it and the block used to disappear entirely.
  const wdttInsts = !iface ? (snap.wdtt || []).filter(w => w && w.iface)
                           : (snap.wdtt || []).filter(w => w && w.iface === iface);
  const csqttInsts = !iface ? (snap.csqtt || []).filter(c => c && c.iface)
                            : (snap.csqtt || []).filter(c => c && c.iface === iface);
  // drag-to-reorder turn-proxies + WDTT + csqtt instances together (node view only; per-interface view is a
  // filtered subset). Self-contained-kind ids are namespaced ('wdtt:'/'csqtt:'<iface>) so they never clash.
  const _turnOrder = orderById([...cards.map(tp => tp.service), ...wdttInsts.map(w => "wdtt:" + w.iface), ...csqttInsts.map(c => "csqtt:" + c.iface)], nrec.turn_order, x => x);
  const tReorder = useReorder(iface ? [] : _turnOrder, ids => mutate({
    patch: s => { const nn = (s.nodes || []).find(x => x.id === node); if (nn) nn.turn_order = ids; },
    call: () => api.saveOrder({ kind: "turn", node, order: ids }),
  }));
  if (iface && !cards.length && !wdttInsts.length) return null;   // interface view with nothing to show → no block
  const blocked = (Store.recon.nodeStatus[node] !== "live") || inProc(nrec.proc_status);
  // arch gate: grey out "Setup proxy" ONLY when the node explicitly reports no build for its CPU arch (turn_arch_ok===false).
  // Unknown/absent never blocks — the node's own download is the real gate, so a valid box is never wrongly refused.
  const archNo = nrec.turn_arch_ok === false;
  const archTip = T("No turn-proxy build for this node's architecture{v1} — only amd64 and arm64 are supported.", { v1: nrec.arch ? " (" + nrec.arch + ")" : "" });
  // client-optimistic installs: a FULL card with the entered data, dimmed + "installing", shown the instant
  // Install is clicked — until the node reports the real proxy (in `all`) or it goes stale. Keyed by service.
  const _tpfx = node + "|";
  for (const k of Object.keys(Store.turnNew)) { if (!k.startsWith(_tpfx)) continue; const s = k.slice(_tpfx.length); if (all.some(t => t.service === s) || (Date.now() - (Store.turnNew[k].at || 0) > 900000)) delete Store.turnNew[k]; }
  const optTurns = iface ? [] : Object.keys(Store.turnNew).filter(k => k.startsWith(_tpfx)).map(k => ({ svc: k.slice(_tpfx.length), d: Store.turnNew[k] })).filter(o => !all.some(t => t.service === o.svc));
  const optSvcs = new Set(optTurns.map(o => o.svc));
  const optCard = (svc, d) => { const lp = portOf(d.connect); const fronted = Object.keys(metas).find(i => String((metas[i] || {}).listen_port) === lp); const ftype = (fronted && metas[fronted].awg_params && Object.keys(metas[fronted].awg_params).length) ? "awg" : "wg";
    return html`<div class="ifcard tp down" key=${"new:" + svc}>
      <div class="ifcard-top"><span class=${"iftype turn tf-" + turnFork(svc)}>${T("val|turn")}</span><span class="ifname">${d.title || turnFork(svc)}</span><span class="grow"></span><${CmdErr} err=${(nrec.cmd_errors || {})[svc]}/><${StatusTag} cls="tg-pending" icon="clock" label="pending" title=${T("Assigned — waiting for the node to pick it up and install it")}/><button class="xbtn" title=${T("Cancel this request")} onClick=${() => { delete Store.turnNew[node + "|" + svc]; cancelTurn(node, { service: svc }); }}><${Ic} i="x"/></button></div>
      <div class="ifcard-rows">
        <div class="ifrow"><span class="l">${T("Turn-proxy fork")}</span><span class="r">${turnFork(svc)}</span></div>
        <div class="ifrow"><span class="l">${T("Listen")}</span><span class="r addr">${d.listen || "—"}</span></div>
        <div class="ifrow"><span class="l">${T("Forwards to")}</span><span class="r">${fronted ? html`<a class=${"tg tg-" + ftype} href=${"#/node/" + encodeURIComponent(node) + "/" + encodeURIComponent(fronted)} onClick=${e => e.stopPropagation()}>${fronted}</a>` : (d.connect || "—")}</span></div>
      </div></div>`; };
  return html`<${Panel} icon="relay" title=${title} tone="turn" count=${cards.length + optTurns.length + wdttInsts.length + csqttInsts.length}
      actions=${nrec.turn_manage ? html`<${Fragment}><button class="btn btn-mini ico" title=${T("Turn-proxy settings in Settings → Turn proxies")} onClick=${() => goSettings("turn")}><${Ic} i="gear"/></button>${_canFrontTurn && !(iface && isWdttIface(iface)) ? html`<button class="btn btn-mini" disabled=${blocked || archNo} title=${blocked ? T("Unavailable while the node is down / converting") : archNo ? archTip : ""} onClick=${() => openSetupTurn(node, iface)}><${Ic} i="plus"/> ${T("Setup new proxy")}</button>` : null}<//>` : null}>
    ${(!iface && !nrec.turn_manage) ? html`<div class="notice"><${Ic} i="info"/><span>${Trich("Turn-proxy management is *off* on this node — no Docker socket was mounted at install (*TURN_MANAGE=manual*), so these are read-only here. Add, edit or restart them on the box directly.")}</span></div>` : null}
    <div class="ifgrid" ...${iface ? {} : tReorder.container()}>${iface
      ? html`<${Fragment}>
          ${wdttInsts.map(w => html`<${WdttCard} key=${"wdtt:" + w.iface} node=${node} w=${w} reorder=${null}/>`)}
          ${csqttInsts.map(c => html`<${CsqttCard} key=${"csqtt:" + c.iface} node=${node} c=${c} reorder=${null}/>`)}
          ${cards.map(tp => html`<${TurnCard} key=${tp.service} node=${node} tp=${tp} nrec=${nrec} metas=${metas} showForwards=${false} reorder=${null}/>`)}
        <//>`
      : _turnOrder.map(id => {
          const w = id.indexOf("wdtt:") === 0 ? wdttInsts.find(x => "wdtt:" + x.iface === id) : null;
          if (w) return html`<${WdttCard} key=${id} node=${node} w=${w} reorder=${tReorder}/>`;
          const c = id.indexOf("csqtt:") === 0 ? csqttInsts.find(x => "csqtt:" + x.iface === id) : null;
          if (c) return html`<${CsqttCard} key=${id} node=${node} c=${c} reorder=${tReorder}/>`;
          const tp = cards.find(t => t.service === id);
          return tp ? html`<${TurnCard} key=${tp.service} node=${node} tp=${tp} nrec=${nrec} metas=${metas} showForwards=${true} reorder=${tReorder}/>` : null;
        })}
    ${optTurns.map(o => optCard(o.svc, o.d))}
    ${!iface ? Object.entries(nrec.turn_pending || {}).filter(([s]) => !all.some(t => t.service === s) && !optSvcs.has(s)).map(([s, act]) => html`<div class="ifcard tp pending"><div class="ifcard-top"><span class="iftype turn">${T("val|turn")}</span><span class="ifname">${turnLabel(s, "")}</span><span class="grow"></span><${CmdErr} err=${(nrec.cmd_errors || {})[s]}/>${act === "delete" ? html`<span class="tg-busy del">${T("deleting…")}</span>` : html`<span class="tg tg-pending"><${Ic} i="clock"/>${T("tag|pending")}</span>`}<button class="xbtn" title=${T("Cancel this request")} onClick=${() => cancelTurn(node, { service: s })}><${Ic} i="x"/></button></div></div>`) : null}
    ${!iface ? (nrec.turn_onboarding || []).map(p => html`<div class="ifcard tp pending"><div class="ifcard-top"><span class="iftype turn">${T("val|turn")}</span><span class="ifname">${T("adopting…")}</span><span class="grow"></span><${CmdErr} err=${(nrec.cmd_errors || {})[p]}/><span class="tg-busy">${T("adopting…")}</span><button class="xbtn" title=${T("Cancel this request")} onClick=${() => cancelTurn(node, { path: p })}><${Ic} i="x"/></button></div><div class="ifcard-rows"><div class="ifrow"><span class="l faint" style="word-break:break-all">${p}</span></div></div></div>`) : null}
    </div>
  <//>`;
}

// master switch: turn-proxy UI is shown unless explicitly disabled in Panel settings → Turn proxies.


const _forkTag = svc => {
  // A self-contained VK-turn server (WDTT/csqtt) collects relay IPs too; its service is `swg-<kind>-<iface>`, which
  // turnFork can't parse. Resolve the running instance to its actual fork (WDTT has several; csqtt is single) so it
  // renders a proper fork tag at parity with the turn-proxies, falling back to the kind's default fork.
  const scm = /^swg-(wdtt|csqtt)-/.exec(String(svc || ""));
  if (scm) {
    const kind = scm[1];
    let fork = "";
    for (const nid of Object.keys(Store.stats || {})) {
      const inst = ((Store.stats[nid] || {})[kind] || []).find(x => x && x.service === svc);
      if (inst) { fork = inst.fork || ""; break; }
    }
    if (!fork) fork = kind === "csqtt" ? "csqtt" : "amurcanov";
    const label = forkLabel(fork);
    return html`<span class="tg tg-turn" style=${"--tfc:" + (turnColor(fork) || WDTT_COLOR)}>${label}</span>`;
  }
  return html`<span class="tg tg-turn" style=${"--tfc:" + turnColor(turnFork(svc))}>${turnFork(svc)}</span>`;
};
const _lastSeen = last => last ? T("{v1} ago", { v1: seen(Math.max(0, Math.floor(Date.now() / 1000) - last)) }) : "—";

// The "Turn IPs" header control on the turn-edit modal: the unique remote peers reaching THIS proxy. A client
// never dials a proxy directly — it goes through a VK TURN server which relays to us — so these are VK relays.
// The active count comes from the live snapshot (no fetch); the hover bubble lists them (green dot = online) with
// a Flush that drops the offline ones. `src_ips` is node-collected (nft); history persists on the panel.
export function TurnIpsHeader({ node, svc }) {
  const [data, setData] = useState(null);
  const load = () => api.turnIps().then(r => setData(r && r.ok ? ((r.data.nodes || {})[node] || {}) : {})).catch(() => setData({}));
  useEffect(() => { load(); }, [node]);
  const _snap = Store.stats[node] || {};
  // a turn-proxy OR a self-contained VK-turn server (WDTT/csqtt) — all key their captured relay IPs off `service`
  const _ent = (_snap.turn_proxies || []).find(t => t.service === svc)
            || (_snap.wdtt || []).find(w => w && w.service === svc)
            || (_snap.csqtt || []).find(c => c && c.service === svc);
  const active = new Set(_ent ? (_ent.src_ips || []) : []);
  const recs = data || {};
  const ips = new Set([...Object.keys(recs).filter(ip => (recs[ip].by || []).includes(svc)), ...active]);
  const all = [...ips].map(ip => ({ ip, last: (recs[ip] || {}).last, on: active.has(ip) }))
    .sort((a, b) => (a.on === b.on ? (b.last || 0) - (a.last || 0) : a.on ? -1 : 1));
  const rows = all.slice(0, 10);   // show at most 10 here — the full list lives in Settings
  const offlineN = all.filter(r => !r.on).length;   // only OFFLINE recorded IPs are flushable (online are kept)
  const flush = () => openConfirm({ title: T("Flush offline recorded IPs"), confirmLabel: T("Flush"), danger: true,
    body: Trich(T("Remove {count} offline recorded for *this turn-proxy only*. Currently-online relays are kept, and other proxies are untouched.", { count: plural(offlineN, "IP") })),
    onConfirm: async () => { await api.turnIpsFlush({ node, service: svc }); load(); } });   // service-scoped on the backend → this proxy's offline IPs only
  const openSettings = () => goSettingsTurnIps();
  const trigger = html`<span class="turnips-hd" onClick=${openSettings}>${T("Turn IPs")}${active.size ? html` · <b>${active.size}</b>` : ""}</span>`;
  return html`<${Popover} hoverOnly cls="turnips-wrap" popCls="turnips-pop" trigger=${trigger}>
    <div class="onpop-h">${T("Collected VK IPs")}</div>
    ${rows.length ? html`<${Fragment}>
      ${rows.map(r => html`<div class="tipbub-row" key=${r.ip}><span class=${"tipdot" + (r.on ? " on" : "")}></span><span class="tipbub-ip">${r.ip}</span><span class="grow"></span><span class="tipbub-when">${r.on ? "online" : _lastSeen(r.last)}</span></div>`)}
      ${all.length > rows.length ? html`<div class="tipbub-more">${T("+{n} more in Settings", { n: all.length - rows.length })}</div>` : null}
      ${offlineN ? html`<button class="tipbub-flush" onClick=${flush}><${Ic} i="trash"/> ${T("Flush offline recorded IPs")}</button>` : null}
    <//>`
      : html`<div class="tipbub-empty">${T("No connections seen yet.")}</div>`}
  <//>`;
}

// The "Collected IPs" grid in Settings → Turn proxies: every unique VK relay IP across the fleet's proxies,
// sorted by Last (online first), with per-row delete and a fleet-wide "Flush …" that keeps the online ones.
export function TurnCollectedIps() {
  const [show, setShow] = useState(false);   // collapsed by default (advtoggle concept) — fetch on first expand
  const [data, setData] = useState(null);
  const secRef = useRef(null);
  const load = () => api.turnIps().then(r => setData(r && r.ok ? (r.data.nodes || {}) : {})).catch(() => setData({}));
  useEffect(() => { if (show && data === null) load(); }, [show]);
  useEffect(() => {   // deep-linked from a "Turn IPs" header → expand + scroll into view
    if (takePendingTurnIps()) { setShow(true); setTimeout(() => secRef.current && secRef.current.scrollIntoView({ behavior: "smooth", block: "center" }), 150); }
  }, []);
  const rows = [];
  for (const [nid, ips] of Object.entries(data || {}))
    for (const [ip, rec] of Object.entries(ips))
      rows.push({ nid, ip, last: rec.last, by: rec.by || [], on: (rec.active_by || []).length > 0 });
  rows.sort((a, b) => (a.on === b.on ? (b.last || 0) - (a.last || 0) : a.on ? -1 : 1));   // default: Last (online first)
  const del = async (nid, ip) => { await api.turnIpsFlush({ node: nid, ip }); load(); };
  const flushAll = () => openConfirm({ title: T("Flush recorded IP history"), confirmLabel: T("Flush"), danger: true,
    body: T("Flush the collected turn-proxy IP history across the fleet? The currently-online IPs are kept."),
    onConfirm: async () => { await api.turnIpsFlush({}); load(); } });
  return html`<${Fragment}>
    <button type="button" ref=${secRef} class="advtoggle" style="margin-top:18px" onClick=${() => setShow(a => !a)}><span class="advcaret">${show ? "▾" : "▸"}</span> ${T("Collected IPs")}${show && rows.length ? html` <span class="count">${rows.length}</span>` : ""}</button>
    ${show ? html`<${Fragment}>
    <p class="hint" style="margin:8px 0 10px">${T("Unique VK server IPs the nodes collected via turn-proxies.")}</p>
    ${data === null ? html`<div class="hint">${T("Loading…")}</div>`
      : rows.length ? html`<${Fragment}>
        <div class="tipgrid">
          <div class="tipgrid-h"><span>${T("Turn IP")}</span><span>${T("Last")}</span><span>${T("Collected by")}</span><span></span></div>
          ${rows.map(r => html`<div class="tiprow" key=${r.nid + "|" + r.ip}>
            <span class="tip-ip"><span class=${"tipdot" + (r.on ? " on" : "")}></span>${r.ip}</span>
            <span class="tip-last">${r.on ? "online" : _lastSeen(r.last)}</span>
            <span class="tip-by">${r.by.map(_forkTag)}</span>
            <button class="xbtn" title=${T("Delete this IP record")} onClick=${() => del(r.nid, r.ip)}><${Ic} i="x"/></button>
          </div>`)}
        </div>
        <div class="tipfoot"><button class="btn btn-mini warn" onClick=${flushAll}><${Ic} i="trash"/> ${T("Flush turn-proxies history")}</button></div>
      <//>`
      : html`<div class="hint">${T("No turn-proxy connections collected yet.")}</div>`}
    <//>` : null}
  <//>`;
}

// ── turn-proxy management (manage modal + onboard) — only on nodes reporting turn_manage ──
// ── turn-proxy management (manage modal + onboard) — only on nodes reporting turn_manage ──
export function openTurnManage(node, tp) { openModal(html`<${TurnManageSheet} node=${node} tp=${tp}/>`); }
export function TurnManageSheet({ node, tp }) {
  const svc = tp.service;
  const lis = tp.listen || "";
  const lh = lis.includes(":") ? lis.slice(0, lis.lastIndexOf(":")) : lis;
  const lp = lis.includes(":") ? lis.slice(lis.lastIndexOf(":") + 1) : "";
  const con = tp.connect || "";
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const snap = Store.stats[node] || {};
  const isBridge = nrec.kind === "docker" && (nrec.net_mode || "host") === "bridge";
  // node's PUBLIC endpoint (what clients dial): on a bridge node the reported nrec.ips are container-private (and
  // filtered out), so surface the public endpoint so the LISTEN-IP dropdown offers it — noded rebinds it to
  // 0.0.0.0 inside the netns, so binding "the public IP" works there despite it not being a local container address.
  const epIp = (() => { for (const b of Object.values(snap.interfaces || {})) { const ep = (b.meta || {}).endpoint || ""; if (ep) return ep.includes(":") ? ep.slice(0, ep.lastIndexOf(":")) : ep; } return ""; })();
  const ips = [...new Set([epIp, (nrec.endpoint_host || "").trim(), ...(nrec.ips || [])].filter(Boolean))];
  const lInit = ips.includes(lh) ? lh : "__custom__";
  const [lsel, setLsel] = useState(lInit);
  const [lcustom, setLcustom] = useState(lInit === "__custom__" ? lh : "");
  const [lport, setLport] = useState(lp);
  const tperr = portErrMsg(node, lport, [lp]);   // live listen-port collision check (this proxy's own port doesn't count)
  const allIfaces = Object.entries(snap.interfaces || {})
    .map(([n, b]) => ({ name: n, port: String((b.meta || {}).listen_port || ""), sys: !!(b.meta || {}).system || n.startsWith("swg_") || isWdttIface(n), awg: !!Object.keys((b.meta || {}).awg_params || {}).length }))
    .filter(i => i.port && !i.sys);   // turn proxies forward to USER interfaces only — never the system/mesh link (swg_*)
  // this proxy's fork is fixed here; a WireGuard-only fork can't front an AmneziaWG interface → hide awg ones
  const fork = turnFork(svc);
  const ifaces = forkSupportsAwg(fork) ? allIfaces : allIfaces.filter(i => !i.awg);
  const hideAwg = !forkSupportsAwg(fork) && allIfaces.some(i => i.awg);
  const conPort = con.includes(":") ? con.slice(con.lastIndexOf(":") + 1) : con;
  const match = ifaces.find(i => i.port === conPort);
  const [fwd, setFwd] = useState(match ? match.name : "__custom__");
  const [custom, setCustom] = useState(con || "127.0.0.1:");
  const [params, setParams] = useState(tp.params != null ? tp.params : (tp.wrap_key ? "-wrap-key " + tp.wrap_key : ""));   // i18n-keys: CLI flags — the operator types these
  const [openSec, setOpenSec] = useState(null);   // the strip's open section — null | "server" | "version"
  const origParams = tp.params != null ? tp.params : (tp.wrap_key ? "-wrap-key " + tp.wrap_key : "");   // i18n-keys: CLI flags — the operator types these
  const [title, setTitle] = useState(shownTitle("t|" + node + "|" + svc, tp.title));   // honour a just-saved optimistic title
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const blocked = (Store.recon.nodeStatus[node] !== "live") || inProc(nrec.proc_status);   // node down / mid re-install / convert / update → disable every action here, same as the node-detail buttons
  const dis = busy || blocked;
  const fail = t => { setBusy(false); setMsg({ k: "err", t }); };
  const isCustom = fwd === "__custom__";
  const lhost = ipPickerVal(lsel, lcustom);
  const installed = tp.version || "";
  const installing = !!tp.installing;
  const failed = !!tp.failed;
  const stopped = !!tp.stopped;
  const down = tp.running === false;
  const owner = turnOwner(svc);
  const doReinstall = async (verb, tag) => {
    setBusy(true); setMsg({ k: "work", t: verb.toLowerCase() + "…" });
    if (verb === "Update") turnUpdating[node + "|" + svc] = Date.now() + 120000;   // card shows "updating" (not "installing") while it applies
    const r = await api.turnReinstall({ node, service: svc, owner, ...(tag ? { tag } : {}) });
    if (!r.ok) { delete turnUpdating[node + "|" + svc]; return fail(srvText(r) || T("Request failed.")); }
    closeModal(); await Store.poll();
    toast(T("Turn-proxy {verb} requested — applies on the node's next sync.", { verb: verb.toLowerCase() }), "ok");
  };
  const save = async () => {
    if (!lhost) return fail(T("Listen IP is required."));
    if (!/^\d+$/.test(lport.trim())) return fail(T("Listen port must be a number."));
    let connect;
    if (isCustom) { connect = custom.trim(); if (!/:\d+$/.test(connect)) return fail(T("Forward-to must be host:port.")); }
    else { connect = "127.0.0.1:" + ifaces.find(i => i.name === fwd).port; }
    const newListen = lhost + ":" + lport.trim();
    // title-only change → OPTIMISTIC: a cosmetic panel-side label, so close immediately + save in the background
    // (no status, no node round-trip, the proxy keeps running). Other field changes go the proper pending route.
    const titleOnly = newListen === (tp.listen || "") && connect === (tp.connect || "") && params.trim() === origParams.trim();
    if (titleOnly) {
      const titleChanged = title.trim() !== (tp.title || "");
      closeModal();
      if (!titleChanged) return toast(T("No changes."), "ok");
      pushOptTitle("t|" + node + "|" + svc, title.trim());   // show the new title on the card immediately
      const r = await api.turnTitle({ node, service: svc, title: title.trim() });
      if (r.ok) { await Store.poll(); toast(T("Title saved — the proxy keeps running."), "ok"); }
      else toast(srvText(r) || T("Failed to save the title."), "err");
      return;
    }
    setBusy(true); setMsg({ k: "work", t: T("saving…") });
    const body = { node, service: svc, listen: newListen, connect, params: params.trim(), title: title.trim() };
    const r = await api.turnManage(body);
    if (!r.ok) return fail(srvText(r) || T("Request failed."));
    closeModal(); await Store.poll();
    toast(T("Turn-proxy update requested — applies on the node's next sync."), "ok");
  };
  const randKey = () => {
    const a = new Uint8Array(32); crypto.getRandomValues(a);
    copy(Array.from(a, b => b.toString(16).padStart(2, "0")).join(""), T("Random 64-hex key copied — paste it into the parameters"));
  };
  // enable Save only when something would actually change (any field, or the inline client picker) — mirrors save()'s own diff
  const _mConnect = isCustom ? custom.trim() : (((ifaces.find(i => i.name === fwd)) || {}).port ? "127.0.0.1:" + ifaces.find(i => i.name === fwd).port : (tp.connect || ""));
  const turnDirty = (lhost + ":" + lport.trim()) !== (tp.listen || "")
    || _mConnect !== (tp.connect || "")
    || params.trim() !== origParams.trim()
    || title.trim() !== (tp.title || "");
  return html`<${Sheet} title=${html`${turnSheetTitle(turnFork(svc), title)}${installed ? html` <span class="sheet-ver">${installed}</span>` : ""}<button class="iconbtn sheet-verset" title=${T("Version, rollback & server defaults for {v1}", { v1: turnFork(svc) })} onClick=${() => openServerDefaults(turnFork(svc))}><${Ic} i="gear"/></button>`} width=${664} headExtra=${html`<${TurnIpsHeader} node=${node} svc=${svc}/>`}
    foot=${html`<${Fragment}>
      <button class="btn btn-ghost danger" disabled=${dis} onClick=${() => openModal(html`<${DeleteTurnSheet} node=${node} service=${svc} label=${turnLabel(svc, lp)}/>`)}><${Ic} i="trash"/>${T("Delete")}</button>
      ${stopped
        ? html`<button class="btn btn-ghost" style="margin-left:8px" disabled=${dis} title=${T("Start the service on the node")} onClick=${() => { startTurn(node, svc); closeModal(); }}><${Ic} i="play"/> ${T("Start service")}</button>`
        : installing
        ? html`<button class="btn btn-ghost" style="margin-left:8px" disabled=${true} title=${T("Installing…")}><${Ic} i="refresh"/> ${T("Reinstall service")}</button>`
        : (tp.running !== false && !failed)
        ? html`<${Fragment}>
            <button class="btn btn-ghost" style="margin-left:8px" disabled=${dis} title=${T("Stop the service on the node (stays down until started)")} onClick=${() => { stopTurn(node, svc); closeModal(); }}><${Ic} i="stop"/> ${T("Stop service")}</button>
            <button class="btn btn-ghost" style="margin-left:8px" disabled=${dis} title=${T("Restart the service on the node")} onClick=${() => { restartTurn(node, svc); closeModal(); }}><${Ic} i="refresh"/> ${T("Restart service")}</button>
          <//>`
        : html`<button class="btn btn-ghost" style="margin-left:8px" disabled=${dis} title=${T("Re-download the binary and start the service on the node")} onClick=${() => doReinstall("Reinstall")}><${Ic} i="refresh"/> ${T("Reinstall service")}</button>`}
      <span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>${T("Cancel")}</button>
      <button class="btn btn-primary" disabled=${dis || !!tperr || !turnDirty} title=${tperr || (!turnDirty ? T("No changes to save") : "")} onClick=${save}>${T("Save")}</button></>`}>
    ${blocked ? html`<div class="notice warn" style="margin-bottom:16px"><${Ic} i="warn"/><span>${T("This node is busy or offline")}${nrec.proc_status ? html` (${procLabel(nrec.proc_status)})` : ""}${T(" — turn-proxy actions are disabled until it's reporting again.")}</span></div>` : null}
    <${RangedHistory} node=${node} kind="throughput" h=${60} fetch=${r => api.turnSeries(node, turnFork(svc), r).then(x => x && x.ok ? x.data : {})}/>
    <div class="iface-intro" style="margin-top:8px">
      <div>${T("Changing any field rewrites the unit's ExecStart on the node and restarts it.")}</div>
      <div>${Trich("The parameters below are placed verbatim after `-connect` — wrap key, wrap mode, any flags the fork supports.")}</div>
    </div>
    <div class="field"><label>${T("col|Title")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— optional")}</span></label><input value=${title} onInput=${e => setTitle(e.target.value)} placeholder=${turnFork(svc)} autocomplete="off"/></div>
    <div class="row2">
      <div class="field"><label>${T("Listen IP")}</label>
        <${IpPicker} ips=${ips} sel=${lsel} setSel=${setLsel} custom=${lcustom} setCustom=${setLcustom} placeholder="203.0.113.7"/></div>
      <div class="field"><label>${T("Listen port")}</label><input class=${tperr ? "bad" : ""} value=${lport} onInput=${e => setLport(e.target.value)} placeholder="57000"/>${tperr ? html`<div class="hint err">${tperr}</div>` : null}</div>
    </div>
    ${lsel === "__custom__" && lhost && !ips.includes(lhost) ? (isBridge
      ? html`<div class="notice" style="margin:-6px 0 16px"><${Ic} i="info"/><span>${Trich("Bridge node: the proxy binds `0.0.0.0` inside the container and this port is published, so enter the node's *public* IP/host (what clients dial) here.")}</span></div>`
      : html`<div class="notice warn" style="margin:-6px 0 16px"><${Ic} i="warn"/><span>${Trich("This isn't a detected address on the node. The proxy *binds* to this address — it must be a real IP on the server, or it dies with `bind: cannot assign requested address`.")}</span></div>`) : null}
    <div class="field"><label>${T("Forwards to")}</label>
      <select class="selwrap" value=${fwd} onChange=${e => setFwd(e.target.value)}>
        ${ifaces.map(i => html`<option value=${i.name}>${i.name} · 127.0.0.1:${i.port}</option>`)}
        <option value="__custom__">${T("Custom IP:Port…")}</option>
      </select>
      ${hideAwg ? html`<div class="hint">${T("{v1} is WireGuard-only — AmneziaWG interfaces are hidden.", { v1: fork })}</div>` : null}
    </div>
    ${isCustom ? html`<${Fragment}>
      <div class="field"><input value=${custom} onInput=${e => setCustom(e.target.value)} placeholder="127.0.0.1:51820" autocomplete="off"/></div>
      <div class="notice warn" style="margin:-6px 0 16px"><${Ic} i="warn"/><span>${T("This forwards to a port with no managed interface behind it. Make sure a wg/awg interface is really listening there, or clients reach the proxy but get no tunnel.")}</span></div>
    <//>` : null}
    <${Disclosure} title=${T("Server parameters")} open=${openSec === "server"} onToggle=${() => setOpenSec(s => s === "server" ? null : "server")}>
      <${TurnParamsEditor} fork=${fork} node=${node} value=${params} onChange=${setParams} listen=${(lhost || "server_ip") + ":" + (lport || "port")} connect=${isCustom ? (custom || "interface_ip:port") : ("127.0.0.1:" + (((ifaces.find(i => i.name === fwd)) || {}).port || "port"))}/>
    <//>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}
export function DeleteTurnSheet({ node, service, label }) {
  const [txt, setTxt] = useState(""); const [busy, setBusy] = useState(false);
  const phrase = T("DELETE {v1}", { v1: label });
  const ok = txt === phrase;
  const del = async () => {
    if (!ok || busy) return; setBusy(true);
    const r = await api.turnDelete({ node, service });
    if (!r.ok) { setBusy(false); return toast(srvText(r) || "Failed.", "err"); }
    closeModal(); await Store.poll();
    toast(T("Turn-proxy removal requested — the node stops + removes it on its next sync."), "ok");
  };
  return html`<${Sheet} title=${T("Delete turn-proxy · {v1}", { v1: label })}
    foot=${footRow({ onCancel: closeModal, danger: true, disabled: !ok || busy, onAction: del, action: T("Delete turn-proxy") })}>
    <div class="notice warn"><${Ic} i="warn"/><span>${Trich("This *stops, disables and removes* the turn-proxy service *{label}* on the node. Clients pointed at it stop connecting. This can't be undone. (To keep the service running and only unlink it from the panel, use *Disconnect*.)", { label })}</span></div>
    <div class="field"><label>${typeToConfirm(phrase)}</label><input autofocus value=${txt} onInput=${e => setTxt(e.target.value)} placeholder=${phrase} autocomplete="off" spellcheck="false"/></div>
  <//>`;
}

// RAW-IP's ONE port, and who holds it. The qWDTT app resolves the raw port from a single app-wide
// preference (default 56003) and REPLACES the link's port with it, so the port is never per-server — but the
// HOST comes from the link untouched. RAW is therefore one listener per ADDRESS: instances on a node's other
// IPs keep theirs. `rawOwnerOn` returns the instance already holding it on `iface`'s address, or "".
export const RAW_PORT = 56003;
const _listenIp = s => { const v = String(s || ""); const i = v.lastIndexOf(":"); const ip = i > 0 ? v.slice(0, i).trim() : ""; return (ip === "0.0.0.0" || ip === "::" || ip === "[::]") ? "" : ip; };
export function rawOwnerOn(node, iface) {
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const cfgs = nrec.wdtt_cfg || {};
  const snap = ((Store.stats[node] || {}).wdtt || []).filter(Boolean);
  const listenOf = ifn => (cfgs[ifn] || {}).listen || (snap.find(w => w.iface === ifn) || {}).listen || "";
  const mine = _listenIp(listenOf(iface));
  const names = new Set([...Object.keys(cfgs), ...snap.map(w => w.iface)]);
  for (const ifn of names) {
    if (ifn === iface) continue;
    const w = cfgs[ifn] || snap.find(x => x.iface === ifn) || {};
    if (!w.raw_port) continue;
    const theirs = _listenIp(listenOf(ifn));
    if (theirs === mine || !theirs || !mine) return ifn;   // same address, or either is a wildcard bind
  }
  return "";
}
export function turnEnabled() { return !(Store.panelSettings && Store.panelSettings.turn_enabled === false); }
// the forks offered in the "install a fork" picker — toggled in Panel settings → Turn proxies. Disabling a fork
// only hides it here; deployed proxies are untouched. Default (setting unset) = WINGS-N + anton48.
// The forks offered in the install picker before settings load / on a panel with no stored list. MUST mirror
// PANEL_SETTINGS_DEFAULTS["enabled_turn_forks"] server-side; it lived as three separate literals and two of them
// had fallen behind, hiding wdttplus and xxcipherx — two of the four WDTT servers we build and publish.
export const TURN_FORKS_DEFAULT = ["WINGS-N", "MYSOREZ", "samosvalishe", "anton48", "Moroka8",
                            "amurcanov", "ildarmaga", "wdttplus", "xxcipherx", "csqtt", "qwdtt"];
export function enabledTurnForks() {
  const en = Store.panelSettings && Store.panelSettings.enabled_turn_forks;
  // Mirror of PANEL_SETTINGS_DEFAULTS["enabled_turn_forks"] server-side — used before settings load, and on a
  // panel with no stored list. It was missing wdttplus and xxcipherx, so two of the four WDTT server forks we
  // build and publish were hidden from every picker until the operator ticked them by hand.
  const set = new Set(en || TURN_FORKS_DEFAULT);
  return turnForkList().filter(f => set.has(f.id) && !f.hidden);   // hidden (dead) forks never appear in operator pickers
}

// ═══════════ Typed turn-proxy settings (Axis 1) ═══════════
// A fork's `settings` schema (served in the catalog) describes its obfuscation knobs as typed fields; the editor
// renders a form from it and SERIALISES back to the ExecStart params tail (the wire truth the node applies
// verbatim). A raw textarea stays as the escape hatch, so a flag we don't model is never lost. Descriptor:
//   {key, flag, type, default, label, help?, secret?, rotatable?, values?, showIf?}
//   type: bool (bare flag when true) · enum (-flag <value>) · flagenum (mutually-exclusive; value carries its own
//   flag) · hexkey (-flag <64hex> + generate/copy) · string/int (-flag <value>). See TURN-PROXY-OVERHAUL-PLAN.md.
export function forkSettings(forkId) {
  const f = turnForkList().find(x => x.id === forkId);
  return (f && Array.isArray(f.settings)) ? f.settings : [];
}
// opts.key = a fixed hex for hexkey fields (stable across fork switches) · opts.fresh = generate one. Neither (the
// PARSE baseline) → everything empty/false, so the params string is the sole truth.
export function defaultSettingValues(schema, opts) {
  opts = opts || {}; const dflt = !!(opts.fresh || opts.key); const v = {};   // dflt: apply schema defaults (a new install); else the empty PARSE baseline
  for (const d of schema) {
    if (d.type === "hexkey") v[d.key] = opts.key || (opts.fresh ? randWrapKey() : "");
    else if (d.type === "bool") v[d.key] = dflt ? !!d.default : false;
    else v[d.key] = dflt ? (d.default != null ? d.default : "") : "";
  }
  return v;
}
export function settingShown(d, values) {
  return !d.showIf || Object.keys(d.showIf).every(k => values[k] === d.showIf[k]);
}
// options normalised to [{value,label}] for enum (string values) + flagenum (object values).
export function turnOptions(d) {
  return (d.values || []).map(o => d.type === "flagenum" ? { value: o.value, label: o.label || o.value } : { value: o, label: String(o) });
}
// ANY parameter with exactly two states renders as a switch: a bool, or an enum/flagenum with exactly 2 values.
// 3+ values → dropdown. The switch shows the selected value's LABEL so a 2-mode enum (e.g. WRAP/SRTP) is unambiguous.
export function serializeTurnSettings(schema, values) {   // typed values → ExecStart params tail (schema order; skips hidden + empty)
  const parts = [];
  for (const d of schema) {
    if (!settingShown(d, values)) continue;
    const v = values[d.key];
    if (d.type === "bool") { if (v) parts.push(d.flag); }
    else if (d.type === "flagenum") { const o = (d.values || []).find(x => x.value === v); if (o && o.flag) parts.push(o.flag); }
    else if (v !== "" && v != null) { parts.push(d.flag + " " + v); }
  }
  return parts.join(" ");
}
// Does the current obfuscation mode use a key? (false for the keyless values: wrap-mode off / obf none / SRTP plain / -wrap off)
export const TURN_KEYLESS = new Set(["off", "none", "plain", "false"]);
export function turnKeyUsed(schema, vals) {
  const keyField = schema.find(d => d.type === "hexkey"); if (!keyField) return false;
  return schema.filter(d => d.type !== "hexkey").every(d => d.type === "bool" ? (vals[d.key] === true || vals[d.key] === "true") : !TURN_KEYLESS.has(String(vals[d.key])));
}
export function parseTurnSettings(schema, params) {   // params tail → {values, ok, leftover}; ok=false (unknown tokens) → the extra box holds them
  const toks = String(params || "").trim().split(/\s+/).filter(Boolean);
  const values = defaultSettingValues(schema, {});
  const boolFlag = {}, valFlag = {}, feFlag = {};
  for (const d of schema) {
    if (d.type === "bool") boolFlag[d.flag] = d.key;
    else if (d.type === "flagenum") (d.values || []).forEach(o => { if (o.flag) feFlag[o.flag] = { key: d.key, value: o.value }; });
    else valFlag[d.flag] = d.key;
  }
  const leftover = [];
  for (let i = 0; i < toks.length; i++) {
    const t = toks[i];
    if (boolFlag[t] != null) values[boolFlag[t]] = true;
    else if (feFlag[t]) values[feFlag[t].key] = feFlag[t].value;
    else if (valFlag[t] != null && i + 1 < toks.length) values[valFlag[t]] = toks[++i];
    else leftover.push(t);
  }
  return { values, ok: leftover.length === 0, leftover };
}
// Shared server-config form — used by the panel-settings DEFAULTS sheet AND the per-proxy create/edit editor.
// An obfuscation control (+ Generate key, shown only for keyed modes with a live "Not generated yet"), a read-only
// "-listen … -connect … <obf>" line, and a free-entry extra-flags textarea. `template`=true → the placeholder
// (defaults) copy; false → a real proxy's actual listen/connect.
export function TurnServerFields({ schema, vals, setV, extra, setExtra, listen, connect, template, wdtt, noHint }) {
  const keyField = schema.find(d => d.type === "hexkey");
  const obfFields = schema.filter(d => d.type !== "hexkey");
  const keyUsed = turnKeyUsed(schema, vals);
  const obfTail = serializeTurnSettings(schema, (keyUsed || !keyField) ? vals : { ...vals, [keyField.key]: "" });
  // WDTT is SELF-CONTAINED: it owns its WireGuard interface, so its command is nothing like a -connect fork's.
  // Show the real WDTT ExecStart shape (read-only, per-instance values are placeholders) instead of -listen/-connect.
  const autoLine = wdtt
    ? "-iface wdttN -wg-addr 10.66.N.1/24 -listen server_ip:dtls_port -wg-port internal_port -no-nat -fixed-config -password <node-minted>" + (obfTail ? " " + obfTail : "")
    : "-listen " + (listen || "server_ip:port") + " -connect " + (connect || "interface_ip:port") + (obfTail ? " " + obfTail : "");   // i18n-keys: CLI flags — the operator types these
  return html`<${Fragment}>
    ${obfFields.length ? html`<div class="field"><label>${T("Obfuscation")}</label>
      <div class="obfrow">
        ${obfFields.map(d => d.type === "bool"
          ? html`<label class="obfctl" key=${d.key}><${Switch} on=${!!vals[d.key]} onChange=${v => setV(d.key, v)}/> <span class="obfctl-lbl">${d.label}</span></label>`
          : html`<label class="obfctl" key=${d.key}><select class="selwrap" value=${vals[d.key]} onChange=${e => setV(d.key, e.target.value)}>${turnOptions(d).map(o => html`<option value=${o.value}>${o.label}</option>`)}</select></label>`)}
        ${keyField && keyUsed ? html`<button type="button" class="btn btn-mini" onClick=${() => setV(keyField.key, randWrapKey())}><${Ic} i="refresh"/> ${T("Generate key")}</button>${!vals[keyField.key] ? html`<span class="notgen">${T("Not generated yet")}</span>` : null}` : null}
      </div></div>` : null}
    <div class="field"><label>${T("ExecStart parameters")}</label>
      <div class="execbox">
        <div class="execbox-auto" title=${template ? T("Auto-filled for each real proxy — read-only") : T("This proxy's command — read-only")}>${autoLine}</div>
        <textarea class="execbox-extra" value=${extra} onInput=${e => setExtra(e.target.value)} placeholder=${T("extra flags — appended verbatim, e.g. -debug")} spellcheck="false"></textarea>
      </div>
      ${noHint ? null : html`<div class="hint">${wdtt
        ? Trich("WDTT servers are *self-contained* — each owns its own WireGuard interface. The interface name, subnet, endpoint / DTLS port, internal WG port, egress, routing and filters are set *per interface* (in the interface's create / edit modal), and the WRAP password is minted on the node — everything on the top line is a placeholder. Only the extra flags below pre-fill a new WDTT instance.")
        : template
        ? Trich("You're setting the *default* parameters for the actual turn-proxies you'll create on nodes later — nothing is deployed now. The top line is filled in per real proxy: the node's *listen* address (`server_ip:port`), the *interface* it forwards to (`interface_ip:port`), and the obfuscation you set above — those are placeholders here. Whatever you type below is appended to the command as-is.")
        : Trich("The top line is this proxy's actual command — the *listen* address and *interface* you set above, plus the obfuscation here. Whatever you type below is appended verbatim.")}</div>`}
    </div>
  <//>`;
}
// Controlled per-proxy editor: `value` is the ExecStart params tail (after -connect), `onChange` gets the new one.
// Splits it into typed obfuscation (curated schema) + free extra flags; anything the schema doesn't model rides in
// the extra box (the raw escape hatch). `listen`/`connect` feed the read-only preview line.
export function TurnParamsEditor({ fork, node, value, onChange, listen, connect }) {
  const schema = forkSettings(fork);
  const [obfVals, setObfVals] = useState(() => parseTurnSettings(schema, value).values);
  const [extra, setExtra] = useState(() => (parseTurnSettings(schema, value).leftover || []).join(" "));
  const serialize = (ov, ex) => { const t = serializeTurnSettings(schema, ov); const e = (ex || "").trim(); return t + (e ? (t ? " " : "") + e : ""); };
  useEffect(() => { if (value !== serialize(obfVals, extra)) { const p = parseTurnSettings(schema, value); setObfVals(p.values); setExtra((p.leftover || []).join(" ")); } }, [value, fork]);   // re-sync on an external change (fork switch)
  const setV = (k, v) => { const nv = { ...obfVals, [k]: v }; setObfVals(nv); onChange(serialize(nv, extra)); };
  const onEx = s => { setExtra(s); onChange(serialize(obfVals, s)); };
  return html`<${TurnServerFields} schema=${schema} vals=${obfVals} setV=${setV} extra=${extra} setExtra=${onEx} listen=${listen} connect=${connect} template=${false}/>`;
}
// A typed schema → plain {key:value} form (bool/enum/flagenum/hexkey/int/text), used by the Servers-tab and
// Clients-tab DEFAULTS editors. onSet(key, value) persists one field; `values` are the saved overrides (else schema default).
export function TurnDefaultsForm({ schema, values, onSet, busy }) {
  const cur = d => { const v = (values || {})[d.key]; return (v === undefined || v === null) ? d.default : v; };
  // two fields per row; textarea (raw flags) spans the full width.
  return html`<div class="fld2">${(schema || []).filter(d => settingShown(d, values || {})).map(d => html`<div class=${"field" + (d.type === "textarea" ? " span2" : "")} key=${d.key}>
    <label>${d.label || d.key}</label>
    ${d.type === "bool"
      ? html`<div style="display:flex;align-items:center;gap:10px"><${Switch} on=${!!cur(d)} disabled=${busy} onChange=${v => onSet(d.key, v)}/> <span class="faint">${cur(d) ? "on" : "off"}</span></div>`
      : (d.type === "enum" || d.type === "flagenum")
      ? html`<select class="selwrap" value=${cur(d)} disabled=${busy} onInput=${e => onSet(d.key, e.target.value)}>${turnOptions(d).map(o => html`<option value=${o.value}>${o.label}</option>`)}</select>`
      : d.type === "hexkey"
      ? html`<div style="display:flex;gap:8px;align-items:center">
          <input class="mono" style="flex:1" value=${cur(d)} spellcheck="false" autocomplete="off" placeholder=${T("64 hex chars — blank = a fresh key per proxy")} disabled=${busy} onInput=${e => onSet(d.key, e.target.value.trim())}/>
          <button type="button" class="linkbtn" disabled=${busy} onClick=${() => onSet(d.key, randWrapKey())}>${T("Generate")}</button></div>`
      : d.type === "int"
      ? html`<input type="number" value=${cur(d)} min=${d.min != null ? d.min : undefined} max=${d.max != null ? d.max : undefined} disabled=${busy} placeholder=${d.default === "" ? T("app default") : String(d.default)} onInput=${e => onSet(d.key, e.target.value)}/>`
      : d.type === "textarea"
      ? html`<textarea class="ta" rows="3" value=${cur(d) || ""} disabled=${busy} spellcheck="false" placeholder=${d.placeholder || ""} onInput=${e => onSet(d.key, e.target.value)}></textarea>`
      : html`<input value=${cur(d)} disabled=${busy} onInput=${e => onSet(d.key, e.target.value)}/>`}
    ${d.help ? html`<div class="hint">${d.help}</div>` : null}
  </div>`)}</div>`;
}
// Servers-tab "Clients" icon → the end-user apps that can connect to this fork's proxies, grouped by device/OS.
// Four OS tabs; a tab with no app for the fork is disabled. Native app sorts first in the per-OS picker; under it,
// how that app takes its config (import scheme, where to get the app, its in-app knobs).
export const _OS_TABS = [["android", "Android"], ["ios", "iOS"], ["linux", "Linux"], ["windows", "Windows"], ["macos", "macOS"]];
const _OS_ICON = { android: "android", ios: "apple", linux: "os_linux", windows: "windows", macos: "finder" };
// A compact styled OS dropdown (glyph + name), matching the Clients-sheet OS tabs. `value` is an os key, `options`
// the os keys to offer (in _OS_TABS order), `onChange(os)`. Closes on outside-click or pick.
export function OsDropdown({ value, options, onChange }) {
  const [open, setOpen] = useState(false);
  const opts = _OS_TABS.filter(([o]) => (options || []).includes(o));
  const cur = _OS_TABS.find(([o]) => o === value) || opts[0] || _OS_TABS[0];
  useEffect(() => { if (!open) return; const h = () => setOpen(false); document.addEventListener("click", h); return () => document.removeEventListener("click", h); }, [open]);
  return html`<div class="osdd" onClick=${e => e.stopPropagation()}>
    <button type="button" class=${"osdd-btn" + (open ? " open" : "")} onClick=${() => setOpen(o => !o)}>
      <span class="osdd-ic"><${Ic} i=${_OS_ICON[cur[0]]}/></span><span class="osdd-lbl">${cur[1]}</span><span class="osdd-car">${open ? "▴" : "▾"}</span></button>
    ${open ? html`<div class="osdd-menu">${opts.map(([o, label]) => html`<button key=${o} type="button"
      class=${"osdd-opt" + (o === cur[0] ? " on" : "")} onClick=${() => { onChange(o); setOpen(false); }}>
      <span class="osdd-ic"><${Ic} i=${_OS_ICON[o]}/></span><span class="osdd-lbl">${label}</span>${o === cur[0] ? html`<${Ic} i="check"/>` : null}</button>`)}</div>` : null}
  </div>`;
}
// Name colour by the client's relation to the fork: native (green), friendly (blue), plain (red), CLI (gold).
const _APP_REL_COLOR = { native: "var(--online)", friendly: "#5FA8E0", friendly_core: "#5FA8E0", plain: "var(--dangling)" };
export function appNameColor(rel, isCli) { return isCli ? "#D9B84A" : (_APP_REL_COLOR[rel] || "#5FA8E0"); }
// A client-app picker styled like OsDropdown. options: [{id, name, author, color, nameColor?, plain?}]. The label
// reads "<app name> by <author>" — the name in its relation colour, the author in its own — with a red PLAIN badge
// on an unobfuscated client (the exp note lives under the config, so it's not repeated here).
export function AppDropdown({ value, options, onChange }) {
  const [open, setOpen] = useState(false);
  const opts = options || [];
  const cur = opts.find(o => o.id === value) || opts[0];
  useEffect(() => { if (!open) return; const h = () => setOpen(false); document.addEventListener("click", h); return () => document.removeEventListener("click", h); }, [open]);
  if (!cur) return null;
  const lbl = o => html`<span class="osdd-lbl"><b style=${o.nameColor ? "color:" + o.nameColor : ""}>${o.name}</b><span class="app-by"> by </span><span style=${"color:" + o.color}>${o.author || "—"}</span>${o.plain ? html`<span class="app-plain">PLAIN</span>` : null}${autostartIcon(o.autostart)}</span>`;
  return html`<div class="osdd appdd" onClick=${e => e.stopPropagation()}>
    <button type="button" class=${"osdd-btn" + (open ? " open" : "")} onClick=${() => setOpen(o => !o)}>
      ${lbl(cur)}<span class="osdd-car">${open ? "▴" : "▾"}</span></button>
    ${open ? html`<div class="osdd-menu">${opts.map(o => html`<button key=${o.id} type="button"
      class=${"osdd-opt" + (o.id === cur.id ? " on" : "")} onClick=${() => { onChange(o.id); setOpen(false); }}>
      ${lbl(o)}${o.id === cur.id ? html`<${Ic} i="check"/>` : null}</button>`)}</div>` : null}
  </div>`;
}
export function openServerClients(fork, os) { pushModal(html`<${ServerClientsSheet} fork=${fork} initialOs=${os}/>`); }
export function ServerClientsSheet({ fork, initialOs }) {
  const f = turnForkList().find(x => x.id === fork) || {};
  return html`<${Sheet} title=${html`Default client apps <span class="faint" style="text-transform:none;letter-spacing:0">— <b style=${"color:" + (turnColor(fork) || "var(--fg)") + ";font-weight:700"}>${f.label}</b></span>`} width=${880} noGuard=${true} onClose=${closeModal} onBack=${closeModal}>
    <${ServerClientsBody} fork=${fork} initialOs=${initialOs}/>
  <//>`;
}
// ── Client-picker entry model ── the apps/CLIs that can drive THIS fork's server, each a rich row for the styled
// dropdown. GUI apps come from the compat map; the CLI is expanded into one entry PER author (native build first) so
// the admin picks which binary end-users get. Three independent badge axes: relation (native vs cross), obfuscation
// (the fork's wire, or plain), and kind (app vs CLI). `key` = the client id, or "sidecar@<author>" for a CLI build.
export const TURN_OBF_LABEL = { "Moroka8": "WRAP", "samosvalishe": "rtpopus", "anton48": "SRTP", "MYSOREZ": "WRAP", "WINGS-N": "WRAP",
                         // WDTT family: every client speaks WRAP-A (DTLS + RTP-AEAD). Never "plain".
                         "amurcanov": "WRAP-A", "ildarmaga": "WRAP-A", "wdttplus": "WRAP-A", "xxcipherx": "WRAP-A", "qwdtt": "WRAP-A",
                         "csqtt": "RTP-AEAD" };   // csqtt masks its transport as encrypted VK-call/RTP media — always on
const _FORK_GUI_OBF = { "Moroka8": 1, "samosvalishe": 1, "anton48": 1, "MYSOREZ": 1, "WINGS-N": 1,       // a native/friendly GUI app rides the fork's obfuscation
                        "amurcanov": 1, "ildarmaga": 1, "wdttplus": 1, "xxcipherx": 1, "qwdtt": 1, "csqtt": 1 };   // WDTT apps always obfuscate (WRAP-A); csqtt always obfuscates (RTP-AEAD)
const _FORK_CLI_OBF = { "Moroka8": 1, "samosvalishe": 1, "anton48": 1, "MYSOREZ": 1 };                 // a listed CLI author obfuscates (NOT WINGS — its wrap needs the app's SessionHello)
// "Don't offer on this OS" — a stored choice in turn_client_default[fork][os], alongside a client id or
// "sidecar@<author>". The sub page's turnGetApp() returns nothing for it, and every caller there already hides a
// deployment with no app, so the card simply isn't rendered. NOT a pickerEntries member: it isn't an app, and
// letting it into that list would put it into ranking, system-default and "has any app" logic.
export const NONE_KEY = "none";
export function pickerEntries(f, os) {
  const cmap = (Store.turnCatalog && Store.turnCatalog.clients) || {};
  const fork = f.id, compat = f.compat || {}, obfLabel = TURN_OBF_LABEL[fork] || "";
  const out = [];
  Object.keys(cmap).forEach(cid => {
    const cl = cmap[cid] || {};
    if (cid === "sidecar" || cl.encoder === "sidecar") return;                    // the CLI is expanded per-author below
    const rel = compat[cid];
    if (!rel || !(cl.platforms && cl.platforms[os])) return;
    const isCore = rel === "friendly_core", native = rel === "native";
    const obf = ((native || rel === "friendly" || isCore) && _FORK_GUI_OBF[fork]) ? obfLabel : "";
    out.push({ key: cid, cid, isCli: false, native, obf,
      autostart: !!(((cl.platforms || {})[os] || {}).autostart),   // per-app-per-OS: Start opens the app via its URL scheme
      coreFork: cid === "mysorez" ? fork : null,          // the VK TURN Proxy app is a core-launcher — always name the core it loads (this fork's)
      author: (turnClientAuthor(cid) || {}).fork || fork,
      name: ((cl.platforms || {})[os] || {}).name || cl.name || cid,
      color: turnClientColor(cid) || turnColor(fork) });
  });
  // The generic UDP-relay sidecar CLI is a VK-TURN-PROXY-family client — offer it ONLY to forks whose compat
  // declares it (per _TURN_CLIENT_COMPAT). Self-contained kinds (WDTT/csqtt) own their datapath and the sidecar
  // can't front them, so they must NOT get it (they'd else show a bogus "Sidecar by samosvalishe" desktop client).
  const sc = cmap.sidecar;
  if (sc && sc.platforms && sc.platforms[os] && compat.sidecar) (f.cli_authors || ["samosvalishe"]).forEach(author => {
    out.push({ key: "sidecar@" + author, cid: "sidecar", isCli: true, native: author === fork, autostart: false,   // a CLI is a copy-and-run command, never a one-tap open
      obf: _FORK_CLI_OBF[fork] ? obfLabel : "", coreFork: null, author, name: sc.name || "Sidecar", color: turnColor(author) });
  });
  // order: native app · friendly app · native sidecar · friendly sidecar · plain app · plain sidecar (apps before sidecars in every band; obf before plain)
  const rank = e => e.obf ? (e.native ? (e.isCli ? 3 : 1) : (e.isCli ? 4 : 2)) : (e.isCli ? 6 : 5);
  // within a compat band, prefer the apps that OPEN one-tap (register a URL scheme = autostart) over paste/QR-only
  // ones — so the sub hands out a clickable app by default wherever the band offers one. No per-app hardcoding.
  return out.sort((a, b) => rank(a) - rank(b) || ((b.autostart ? 1 : 0) - (a.autostart ? 1 : 0)) || ((b.native ? 1 : 0) - (a.native ? 1 : 0)) || String(a.name).localeCompare(String(b.name)));
}
// The system default (before any operator choice) for a fork/OS: the WDTT family standardises on a ONE-TAP app.
// Keep the top compat/autostart pick when it already opens one-tap (a fork's own clickable app — Ivan4537's WDTT-Plus,
// XXcipherX's own), else substitute xxcipher (the fleet-standard clickable WDTT client) where it's offered (Android).
// Returns an entry KEY, or null to fall back to the top-ranked entry. Only the WDTT family is standardised.
export function sysDefaultKey(f, entries) {
  const es = entries || [];
  if (!(f && f.kind === "wdtt") || !es.length) return null;
  // A fork may name its own preferred app in the catalog (default_client). That wins over the one-tap rule
  // below: qWDTT's app can't be deep-linked (its manifest registers no BROWSABLE scheme — only .qwdtt/.conf
  // file opens), yet it is the app that fork's users want, and Start already falls back to copy + steps.
  if (f.default_client) { const own = es.find(e => e.cid === f.default_client); if (own) return own.key; }
  if (es[0].autostart) return es[0].key;                    // already one-tap (e.g. the fork's own app) → keep it
  const xc = es.find(e => e.cid === "xxcipher");            // top pick can't one-tap (e.g. amurcanov's wdttapp) → xxcipher
  return xc ? xc.key : null;
}
// The OS-picker order (matches the sub page). Each fork row shows one platform button per OS that has a client.
const _TURN_OS = [["android", "Android"], ["ios", "iOS"], ["windows", "Windows"], ["macos", "macOS"], ["linux", "Linux"]];
// For a fork, the BEST client per OS (native app > friendly app > native sidecar > … , from pickerEntries' rank) →
// the flags that colour its platform button: fill = native/crossplatform · border = plain (unobfuscated) · icon =
// sidecar (CLI). OSes with no connectable client are dropped.
export function turnForkPlatforms(f) {
  const defs = ((Store.panelSettings || {}).turn_client_default || {})[f.id] || {};   // the admin's saved per-OS default clients
  return _TURN_OS.map(([os, label]) => {
    const es = pickerEntries(f, os);
    if (!es.length) return { os, label, disabled: true };   // no connectable client for this OS → greyed, unclickable (not hidden)
    const sd = defs[os], sk = sysDefaultKey(f, es);
    // Deliberately withheld on this OS → ghost the chip like "no app", but keep it CLICKABLE: unlike a platform
    // with nothing to offer, this one has apps and the operator may want to start offering it again.
    if (sd === NONE_KEY) return { os, label, notOffered: true };
    const e = (sd && es.find(x => x.key === sd)) || (sk && es.find(x => x.key === sk)) || es[0];   // SAVED default (matches the settings picker) · else the WDTT system default · else the top-ranked. e.obf = obf label or "" for plain
    return { os, label, native: !!e.native, obf: !!e.obf, isCli: !!e.isCli, name: e.name, author: e.author, color: e.color, coreFork: e.coreFork || null, obfLabel: e.obf || "" };
  });
}
// One styled dropdown row's label parts (used in the button + the open menu). Left: name · by author · [with <core> core].
export function ClientEntryLabel({ e }) {
  /* "<name> by <author> with <core> core" is ONE sentence, not five spans: Russian puts the author in
     the instrumental and the core clause elsewhere, and neither is expressible once it arrives in pieces. */
  const _auth = html`<span class="ce-auth" style=${"color:" + e.color}>${e.author}</span>`;
  const _core = html`<span class="ce-auth" style=${"color:" + turnColor(e.coreFork)}>${e.coreFork}</span>`;
  return html`<span class="ce-name"><b>${e.name}</b> ${e.coreFork
    ? Trich("by {v1} with {v2} core", { v1: _auth, v2: _core })
    : Trich("by {v1}", { v1: _auth })}</span>`;
}
export function ClientEntryBadges({ e }) {
  return html`<span class="ce-badges">
    <span class=${"ce-tag " + (e.obf ? "ce-obf" : "ce-plain")}>${e.obf || "plain"}</span>
    <span class=${"ce-tag " + (e.native ? "ce-native" : "ce-cross")}>${e.native ? "Native" : "crossplatform"}</span>
    <span class=${"ce-tag " + (e.isCli ? "ce-cli" : "ce-app")}>${e.isCli ? "CLI" : "app"}</span>
    ${autostartIcon(e.autostart)}
  </span>`;
}
// One trailing icon on every app row/option telling the operator how the end-user's Start button behaves:
// ⚡ = opens the app automatically (registers a URL scheme) · ⧉ = manual import (copy the link, then paste/scan).
export function autostartIcon(on) {
  return html`<span class=${"ce-auto " + (on ? "on" : "off")} title=${on ? T("Opens the app automatically") : T("Manual import — copy the link, then paste or scan it in the app")}><${Ic} i=${on ? "bolt" : "copy"}/></span>`;
}
// Reusable Clients body — OS segmented tabs + native-first app dropdown + per-(server,client,OS) config reference &
// default-settings form. Used by the settings modal above AND inline (collapsible) in the create/edit-proxy sheets.
// ── Shared client-picker state: OS tab + selected app + staged in-app settings — one hook so a proxy sheet can show
// the app picker inline (under "Forwards to") and its settings in the "Client parameters" section, both driven off the
// same selection. `commitRef` (embedded) lets the parent sheet's Save commit the staged default+settings (true iff changed). ──
export function useTurnClients(fork, commitRef, initialOs) {
  useStore();
  const f = turnForkList().find(x => x.id === fork) || {};
  const cmap = (Store.turnCatalog && Store.turnCatalog.clients) || {};
  const byOs = {};
  _OS_TABS.forEach(([o]) => { byOs[o] = pickerEntries(f, o); });               // rich entries (GUI apps + per-author CLIs), native-first
  const first = (_OS_TABS.find(([o]) => byOs[o].length) || [])[0] || "android";
  const [os, setOs] = useState((initialOs && (byOs[initialOs] || []).length) ? initialOs : first);   // opened from a specific OS button → land on that tab
  const [sel, setSel] = useState({});                                          // {os: entry key}
  const [drafts, setDrafts] = useState({});                                    // staged in-app settings, keyed "os|cid"; committed on Save
  const [flash, setFlash] = useState(null); const [busy, setBusy] = useState(false);
  const entries = byOs[os] || [];
  // the admin's saved end-user default (an entry key) for this (fork, OS); falls back to the top-priority entry if unset / stale
  const savedDefault = (o) => (((Store.panelSettings || {}).turn_client_default || {})[fork] || {})[o];
  // NONE_KEY = "don't offer this server on this OS": a real, storable choice, not the absence of one — so it is
  // valid wherever a client id is, and it round-trips through settings. It has no `cid`, so anything keyed by
  // client id must skip it (see save()).
  const noneEntry = (o) => ({ key: NONE_KEY, cid: null, none: true, isCli: false, native: false, obf: "",
                              autostart: false, coreFork: null, author: "", color: "",
                              name: T("Not offered on {v1}", { v1: (_OS_TABS.find(([x]) => x === o) || [])[1] || o }) });
  const validDefault = (o) => { const sd = savedDefault(o), es = byOs[o] || []; if (sd === NONE_KEY) return NONE_KEY; if (sd && es.some(e => e.key === sd)) return sd; return sysDefaultKey(f, es) || ((es[0] || {}).key || null); };
  const selEntry = (o) => { const es = byOs[o] || []; if (!es.length) return null; const k = sel[o] !== undefined ? sel[o] : validDefault(o); if (k === NONE_KEY) return noneEntry(o); return es.find(x => x.key === k) || es[0]; };   // the chosen entry for ANY os (each OS button shows its own)
  const selKey = sel[os] !== undefined ? sel[os] : validDefault(os);
  const e = selKey === NONE_KEY ? noneEntry(os) : (entries.find(x => x.key === selKey) || entries[0] || null);
  const cid = e ? e.cid : null; const c = cid ? cmap[cid] : null;
  const cSchema = (cid && f.client_schemas && f.client_schemas[cid]) || (c && c.settings) || [];   // per-(fork,client) knobs — the mysorez app's core differs per fork
  const osLabel = (_OS_TABS.find(([o]) => o === os) || [])[1];
  const cName = e ? e.name : "";
  const appColor = e ? e.color : null;
  // saved DEFAULT VALUES for THIS (server, client, OS) — per-author CLIs share the sidecar schema/value-set
  const savedVals = ((((Store.panelSettings || {}).turn_client_settings || {})[fork] || {})[cid] || {})[os] || {};
  const draftKey = os + "|" + cid;
  const effVals = drafts[draftKey] !== undefined ? drafts[draftKey] : savedVals;                          // staged if edited, else saved
  const stageSetting = (key, value) => setDrafts(m => ({ ...m, [draftKey]: { ...(m[draftKey] !== undefined ? m[draftKey] : savedVals), [key]: value } }));
  const norm = v => JSON.stringify(v || {});
  const isDefault = e && e.key === validDefault(os);                          // is the shown entry the current end-user default?
  const settingsDirty = drafts[draftKey] !== undefined && norm(drafts[draftKey]) !== norm(savedVals);
  const dirty = !!(e && (!isDefault || settingsDirty));                       // changed the default entry, or edited its settings
  const save = async (close) => {
    setBusy(true);
    const def = { ...((Store.panelSettings || {}).turn_client_default || {}) };
    const dfo = { ...(def[fork] || {}) }; dfo[os] = e.key; def[fork] = dfo;    // record this ENTRY (app or CLI-author, or NONE_KEY) as the (fork, OS) default
    const all = { ...((Store.panelSettings || {}).turn_client_settings || {}) };
    if (!e.none) {                                                            // T("not offered") has no client id — writing settings under it would key the map on null
      const fo = { ...(all[fork] || {}) }; const co = { ...(fo[cid] || {}) };
      co[os] = effVals; fo[cid] = co; all[fork] = fo;
    }
    const r = await api.panelSettings({ turn_client_default: def, turn_client_settings: all });
    if (r && r.ok) {
      setDrafts(m => { const n = { ...m }; delete n[draftKey]; return n; }); await Store.poll();
      if (close) { closeModal(); return true; }   // standalone modal: close while STILL "Saving…" so the button never flashes back to "Save"
      setBusy(false); setFlash(T("Saved · {v1} · {v2}", { v1: cName, v2: osLabel })); setTimeout(() => setFlash(null), 2400);
      return true;
    }
    setBusy(false); setFlash(srvText(r) || T("Save failed"));
    return false;
  };
  if (commitRef) commitRef.current = () => (dirty && !busy ? save().then(() => true) : Promise.resolve(false));   // the parent proxy-sheet's Save commits the staged client default/settings; resolves true iff it actually changed something
  return { f, byOs, os, setOs, setSel, selEntry, entries, e, cSchema, osLabel, cName, appColor, effVals, stageSetting, dirty, isDefault, settingsDirty, save, busy, flash };
}
// The app picker — OS tabs + the styled client dropdown (the app the fork's sub page hands out). Shown inline, right
// under "Forwards to", so the choice is visible without opening a section.
// "<app> by <author> [with <core> core]" — same colouring as the dropdown row (name plain, author + core tinted)
export function clientAppLabel(e) {
  if (!e) return "";
  const _a = html`<span style=${"color:" + e.color}>${e.author}</span>`;
  const _c = html`<span style=${"color:" + turnColor(e.coreFork)}>${e.coreFork}</span>`;
  return html`<b>${e.name}</b> ${e.coreFork
    ? Trich("by {v1} with {v2} core", { v1: _a, v2: _c })
    : Trich("by {v1}", { v1: _a })}`;
}
// Per-OS app matrix — one button per OS showing its chosen app (icon · name · author in the author's colour). Hover
// reveals the tags + "offered to <OS> users"; clicking a button makes that OS active (drives the Client-parameters
// body) and expands its app list to pick from. `offered` → phrase the bubble as an end-user offer (proxy sheets).
export function TurnAppsPicker({ ctl, offered }) {
  const { f, byOs, os, setOs, setSel, selEntry } = ctl;
  const [openOs, setOpenOs] = useState(null);
  useEffect(() => { if (!openOs) return; const h = () => setOpenOs(null); document.addEventListener("click", h); return () => document.removeEventListener("click", h); }, [openOs]);
  const anyApp = _OS_TABS.some(([o]) => byOs[o].length);
  const openEntries = openOs ? (byOs[openOs] || []) : [];
  const openLabel = openOs ? (_OS_TABS.find(([o]) => o === openOs) || [])[1] : "";
  const openCur = openOs ? selEntry(openOs) : null;
  const pick = (o, key) => { setSel(m => ({ ...m, [o]: key })); setOs(o); setOpenOs(null); };
  return html`<${Fragment}>
    <div class="osapp-hd">${T("Select an app for each OS")}</div>
    <div class=${"osapp" + (openOs ? " menuopen" : "")} onClick=${ev => ev.stopPropagation()}>
      ${_OS_TABS.map(([o, label]) => {
        const has = byOs[o].length, oe = selEntry(o), many = has > 1;
        return html`<button key=${o} type="button" disabled=${!has}
          class=${"osapp-cell" + (o === os ? " on" : "") + (has ? "" : " off") + (o === openOs ? " open" : "")}
          title=${has ? "" : T("No {v1} app for {v2} yet", { v1: f.label, v2: label })}
          onClick=${() => { if (!has) return; setOs(o); setOpenOs(c => c === o ? null : o); }}>
          <span class="osapp-ic"><${Ic} i=${_OS_ICON[o]}/></span>
          <span class="osapp-col">
            ${oe && oe.none ? html`<span class="osapp-name osapp-dim">${label}</span><span class="osapp-auth osapp-dim">${T("not offered")}</span>`
                 : oe ? html`<span class="osapp-name">${oe.name}</span><span class="osapp-auth"><span style=${"color:" + oe.color}>${oe.author}</span>${oe.coreFork && oe.coreFork !== oe.author ? html`<span class="ce-by"> · </span><span style=${"color:" + turnColor(oe.coreFork)}>${oe.coreFork}</span>` : null}</span>`
                 : html`<span class="osapp-name osapp-dim">${label}</span><span class="osapp-auth osapp-dim">${T("no client")}</span>`}
          </span>
          ${many ? html`<span class="osapp-car">▾</span>` : null}
          ${oe && oe.none ? html`<span class="osapp-bub"><span class="osapp-bub-txt"><b>${T("Not offered")}</b><span class="ce-by">${T(" — {os} users get no card for this server", { os: label })}</span></span></span>`
            : oe ? html`<span class="osapp-bub"><span class="osapp-bub-txt"><b>${oe.name}</b>${oe.coreFork ? html`<span class="ce-by"> ${T("val|with")} </span><span style=${"color:" + turnColor(oe.coreFork)}>${oe.coreFork}</span><span class="ce-by"> ${T("val|core")}</span>` : html`<span class="ce-by"> by </span><span style=${"color:" + oe.color}>${oe.author}</span>`}${offered ? html`<span class="ce-by">${T(" offered to {v1} users", { v1: label })}</span>` : null}</span><${ClientEntryBadges} e=${oe}/></span>` : null}
        </button>`;
      })}
    </div>
    ${openOs && openEntries.length ? html`<div class="osapp-menu" onClick=${ev => ev.stopPropagation()}>
      <div class="osapp-menu-hd">${T("Choose the {v1} app", { v1: openLabel })}</div>
      ${openEntries.map(en => html`<button key=${en.key} type="button"
        class=${"cpick-opt" + (openCur && en.key === openCur.key ? " on" : "")} onClick=${() => pick(openOs, en.key)}>
        <${ClientEntryLabel} e=${en}/><${ClientEntryBadges} e=${en}/></button>`)}
      ${""/* LAST, and set apart: offering nothing is a deliberate choice, not one more app. Picking it drops this
            server from that OS's subscription pages entirely — no card, rather than a client that can't connect. */}
      <button type="button" class=${"cpick-opt cpick-none" + (openCur && openCur.none ? " on" : "")}
        onClick=${() => pick(openOs, NONE_KEY)}>
        <span><b>${T("Don't offer")}</b><span class="ce-by">${T(" for {os}", { os: openLabel })}</span></span>
        <span class="cpick-none-hint">${T("no card on their page")}</span></button>
    </div>` : null}
    ${!anyApp ? html`<div class="notice" style="margin-top:12px"><${Ic} i="info"/><span>${T("No {v1} client app yet.", { v1: f.label })}</span></div>` : null}
  <//>`;
}
// The "Client parameters" body — the selected app's Default settings for this (server, OS). embedded → the parent
// proxy sheet's Save commits; standalone (fork modal) → its own Save button.
export function TurnClientParams({ ctl, embedded }) {
  const { cSchema, cName, osLabel, effVals, stageSetting, dirty, save, busy, flash, e } = ctl;
  if (!e) return html`<div class="hint">${T("Pick a client app above first.")}</div>`;
  return html`<${Fragment}>
    ${""/* "Not offered" has no settings — but it still has to be SAVEABLE, so this replaces the form only, never
          the footer the Save button lives in (returning early here left the choice unable to be committed). */}
    ${e.none
      ? html`<div class="hint">${T("This server isn't offered on {v1} — those users won't see a card for it, so there's nothing to configure. Pick an app above to start offering it again.", { v1: osLabel })}</div>`
      : (cSchema && cSchema.length)
      ? html`<${TurnDefaultsForm} schema=${cSchema} values=${effVals} onSet=${stageSetting} busy=${busy}/>`
      : html`<div class="hint">${T("{v1} has no in-app settings to configure.", { v1: cName })}</div>`}
    ${embedded ? null : html`<div style="display:flex;align-items:center;gap:12px;margin-top:16px">
        <span class="faint" style="font-size:12px">${e.none ? html`${osLabel} users will be offered nothing for this server` : html`${osLabel} users will be offered ${clientAppLabel(e)}`}</span>
        <span class="grow"></span>
        ${flash ? html`<span class="vk-status ok">${flash}</span>` : null}
        <button class="btn btn-primary" disabled=${busy || !dirty} onClick=${() => save(true)}>${busy ? T("Saving…") : T("Save")}</button>
      </div>`}
  <//>`;
}
// Standalone client picker (opened from a fork-row platform button): app picker + its Default settings + a Save.
export function ServerClientsBody({ fork, initialOs }) {
  const ctl = useTurnClients(fork, null, initialOs);
  return html`<${Fragment}>
    <${TurnAppsPicker} ctl=${ctl}/>
    <div style="margin-top:16px"><${TurnClientParams} ctl=${ctl} embedded=${false}/></div>
  <//>`;
}
// "Check client rosters" → fetch each client app's curated schema SOURCE from GitHub and flag drift vs the last-
// acknowledged commit. Detection only (heterogeneous sources → the schema edit is a code change); "Mark reviewed"
// records that we've caught up to the current upstream.
export function openRosterCheck() { pushModal(html`<${RosterCheckSheet}/>`); }
// Always-on client grid: parseable forks (p4/report) get per-field counters + adopt + Set-version rollback; the
// ack-only forks (Markdown/Kotlin-pending, roster-check) show commit drift + whole-client acknowledge.
export function RosterCheckSheet() {
  const [data, setData] = useState(null); const [err, setErr] = useState(null);
  const [checking, setChecking] = useState(false); const [busy, setBusy] = useState({});
  const load = async (refresh) => {
    setChecking(true); setErr(null);
    try {
      const [p4, p1] = await Promise.all([api.p4Report(refresh), api.rosterCheck()]);
      if (p4 && p4.ok && p1 && p1.ok) setData({ p4: p4.data.clients || {}, p1: p1.data.clients || {} });
      else setErr(srvText(p4) || srvText(p1) || T("check failed"));
    } catch (e) { setErr((e && e.message) || T("check failed")); }
    finally { setChecking(false); }
  };
  useEffect(() => { load(false); }, []);
  const reload = () => load(false);
  const withBusy = async (cid, fn) => { setBusy(m => ({ ...m, [cid]: true })); try { await fn(); } catch (_) {} setBusy(m => { const n = { ...m }; delete n[cid]; return n; }); };
  const ack = (cid) => withBusy(cid, async () => { const r = await api.rosterAck(cid); if (r && r.ok) await load(false); });
  const setVersion = (cid, index) => withBusy(cid, async () => { await api.p4SetVersion(cid, index); await load(false); });
  const p1c = (data && data.p1) || {}, p4c = (data && data.p4) || {};
  const cids = Object.keys(p1c).length ? Object.keys(p1c) : Object.keys(p4c);
  const TAG = { up_to_date: ["tg-ready", "check", T("up to date")], changed: ["tg-pending", "warn", "changed"], unknown: ["tg-off", "info", "couldn't check"] };
  return html`<${Sheet} title=${T("Client rosters")} width=${740} noGuard=${true} onClose=${closeModal} onBack=${closeModal}
      foot=${footRow({ left: html`<button class="btn btn-mini" disabled=${checking} onClick=${() => load(true)}><span class=${checking ? "ic-spin" : ""}><${Ic} i="refresh"/></span> ${checking ? T("Checking…") : T("Re-check")}</button>`, cancelLabel: T("Close"), onCancel: closeModal })}>
    <p class="hint" style="margin:2px 0 14px">${T("Each client app's config schema vs upstream on GitHub.")} <b style="color:var(--online)">+n</b> ${T("new adoptable fields ·")} <b style="color:var(--ready)">+y</b> ${T("new values ·")} <b style="color:var(--dangling)">−</b> ${T("removed ·")} <b style="color:var(--fault)">+x</b> ${T("new items that need a panel update (encoder wiring) before they work.")} <b>${T("Set version")}</b> ${T("rolls a client back to a previous app version.")}</p>
    ${!data && !err ? html`<div class="loading"><span class="spin"></span>${T("loading…")}</div>`
      : err ? html`<div class="notice warn"><${Ic} i="warn"/><span>${err}</span></div>`
      : html`<div class="rosterlist">
          ${cids.map(cid => {
            const p4 = p4c[cid], p1 = p1c[cid], t = p1 ? (TAG[p1.status] || TAG.unknown) : null;
            const color = turnClientColor(cid), author = (turnClientAuthor(cid) || {}).fork;
            const name = (p4 && p4.name) || (p1 && p1.name) || cid;
            const p4has = p4 && rcTotal(p4.counts) > 0;
            return html`<div class="roster-row" key=${cid}>
              <div class="roster-hd">
                <span class="roster-nm" style=${color ? "color:" + color : ""}>${name}</span>${author ? html`<span class="roster-by">by ${author}</span>` : null}
                ${p4 ? RosterCounts(p4.counts) : (t ? html`<span class=${"tg " + t[0]}><${Ic} i=${t[1]}/>${t[2]}</span>` : null)}
                <span class="grow"></span>
                ${p4 && (p4.versions || []).length ? SetVersionPicker(p4, i => setVersion(cid, i), busy[cid]) : null}
                ${p4has ? html`<button class="btn btn-mini" disabled=${busy[cid]} onClick=${() => openRosterP4Review(cid, p4, reload)}>${T("Review")}</button>` : null}
                ${!p4 && p1 && p1.status === "changed" ? html`<button class="btn btn-mini" disabled=${busy[cid]} onClick=${() => openRosterReview(cid, p1, ack)}>${busy[cid] ? T("saving…") : T("Review")}</button>` : null}
              </div>
              ${p4 ? null : (p1 ? RosterP1Files(p1) : null)}
            </div>`;
          })}
          <div class="hint faint" style="margin-top:10px">${Trich("Rate-limited by GitHub (60/hour unauthenticated); set `SWG_GH_TOKEN` to lift it. A field tagged \"needs wiring\" becomes usable after a panel update.")}</div>
        </div>`}
  <//>`;
}
export function rcTotal(c) { return c ? (c.n + c.x + c.m + (c.y || 0) + (c.z || 0)) : 0; }
export function RosterCounts(c) {
  if (rcTotal(c) === 0) return html`<span class="tg tg-ready"><${Ic} i="check"/>${T("up to date")}</span>`;
  return html`<span class="rc-counts">${c.n ? html`<span class="rc-cnt add" title=${T("new adoptable fields")}>+${c.n}</span>` : null}${c.y ? html`<span class="rc-cnt val" title=${T("new values for existing settings")}>+${c.y}</span>` : null}${c.m ? html`<span class="rc-cnt rem" title=${T("fields removed upstream")}>−${c.m}</span>` : null}${c.z ? html`<span class="rc-cnt rem" title=${T("values removed upstream")}>−${c.z}</span>` : null}${c.x ? html`<span class="rc-cnt wire" title=${T("new fields/values — need a panel update to use")}>+${c.x}</span>` : null}</span>`;
}
export function SetVersionPicker(p4, onPick, busy) {
  const vs = p4.versions || [], pin = p4.pinned_snapshot;
  return html`<select class="rc-ver" disabled=${busy} value=${pin === null || pin === undefined ? "" : String(pin)}
      onChange=${e => onPick(e.target.value === "" ? null : parseInt(e.target.value, 10))} title=${T("Roll this client's schema to a previous app version")}>
    <option value="">${T("↻ Track latest")}</option>
    ${vs.map((v, i) => html`<option value=${i}>${v.app_version || ("v" + (i + 1))}${i === vs.length - 1 ? " (latest)" : ""}</option>`)}
  </select>`;
}
export function RosterP1Files(p1) {
  return html`${(p1.files || []).map(f => html`<div class="roster-file"><span class="mono">${f.path.split("/").pop()}</span>
    ${f.status === "changed" ? html`<a href=${f.compare_url || f.url} target="_blank" rel="noopener">${T("view change → {v1}", { v1: f.latest_commit })}</a>`
      : f.status === "unknown" ? html`<a class="faint" href=${f.url} target="_blank" rel="noopener">${T("couldn't fetch")}</a>`
      : html`<span class="faint">${f.latest_commit || "current"}</span>`}</div>`)}`;
}
// P4 review: adopt green (Add) / red (Remove) via p4/adopt; orange needs-wiring rows are disabled + labelled.
export function openRosterP4Review(cid, rep, onDone) { pushModal(html`<${RosterP4ReviewSheet} cid=${cid} rep=${rep} onDone=${onDone}/>`); }
export function turnClientFieldLabel(cid, key) {
  const cs = ((((Store.turnCatalog || {}).clients || {})[cid] || {}).settings) || [];
  const s = cs.find(x => x.key === key);
  return (s && s.label) || key;
}
export function RosterP4ReviewSheet({ cid, rep, onDone }) {
  const lbl = f => turnClientFieldLabel(cid, f);
  const items = [];
  (rep.added || []).forEach(f => items.push({ key: "a:" + f, kind: "add", field: f, adoptable: true }));
  (rep.removed || []).forEach(f => items.push({ key: "r:" + f, kind: "rem", field: f, adoptable: true }));
  (rep.value_diff || []).forEach(v => {
    (v.added || []).forEach(val => items.push({ key: "va:" + v.field + ":" + val, kind: v.adoptable_add ? "vadd" : "vwire", field: v.field, value: val, adoptable: !!v.adoptable_add }));
    (v.removed || []).forEach(val => items.push({ key: "vr:" + v.field + ":" + val, kind: "vrem", field: v.field, value: val, adoptable: true }));
  });
  (rep.needs_wiring || []).forEach(f => items.push({ key: "w:" + f, kind: "wire", field: f, adoptable: false }));
  const adoptable = items.filter(i => i.adoptable);
  const [checked, setChecked] = useState(() => { const m = {}; adoptable.forEach(i => m[i.key] = true); return m; });
  const [busy, setBusy] = useState(false);
  const allOn = adoptable.length > 0 && adoptable.every(i => checked[i.key]);
  const someOn = adoptable.some(i => checked[i.key]);
  const toggleAll = () => { const v = !allOn; setChecked(() => { const m = {}; adoptable.forEach(i => m[i.key] = v); return m; }); };
  const toggle = k => setChecked(m => ({ ...m, [k]: !m[k] }));
  const adopt = async () => {
    setBusy(true);
    const add = items.filter(i => i.kind === "add" && checked[i.key]).map(i => i.field);
    const remove = items.filter(i => i.kind === "rem" && checked[i.key]).map(i => i.field);
    const vadd = {}, vrem = {};
    items.filter(i => i.kind === "vadd" && checked[i.key]).forEach(i => (vadd[i.field] = vadd[i.field] || []).push(i.value));
    items.filter(i => i.kind === "vrem" && checked[i.key]).forEach(i => (vrem[i.field] = vrem[i.field] || []).push(i.value));
    try { await api.p4Adopt(cid, { add, remove, vadd, vrem }); } finally { closeModal(); onDone && onDone(); }
  };
  const color = turnClientColor(cid);
  return html`<${Sheet} title=${T("Review changes")} width=${580} noGuard=${true} onClose=${closeModal} onBack=${closeModal}
      foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" disabled=${busy} onClick=${closeModal}>${T("Preserve current")}</button><button class="btn btn-primary" disabled=${busy || !adoptable.length} onClick=${adopt}>${busy ? T("adopting…") : T("Adopt changes")}</button><//>`}>
    <p class="hint" style="margin:2px 0 12px">${T("Schema changes for")} <b style=${color ? "color:" + color : ""}>${rep.name || cid}</b>${rep.app_version ? T(" (upstream {ver})", { ver: rep.app_version }) : ""}. <b style="color:var(--fault)">${T("Needs-wiring")}</b> ${T("items can't be adopted until a panel update teaches the encoder to emit them.")}</p>
    <div class="revlist">
      ${adoptable.length ? html`<label class="rev-all"><input type="checkbox" checked=${allOn} ref=${el => el && (el.indeterminate = !allOn && someOn)} onChange=${toggleAll}/><span>${T("Check all")}</span></label>` : null}
      ${items.map(i => html`<label class=${"rev-item " + i.kind + (i.adoptable ? "" : " disabled")} key=${i.key}>
        <input type="checkbox" disabled=${!i.adoptable} checked=${i.adoptable ? !!checked[i.key] : false} onChange=${() => i.adoptable && toggle(i.key)}/>
        ${i.kind === "add" ? html`<span class="fd-sum add">${T("Add {v1}", { v1: i.field })}</span>`
          : i.kind === "rem" ? html`<span class="fd-sum rem">${T("Remove {v1}", { v1: i.field })}</span>`
          : i.kind === "vadd" || i.kind === "vwire" ? html`<span class="fd-sum val">${T("Add {value} to {field}", { value: i.value, field: lbl(i.field) })}</span>`
          : i.kind === "vrem" ? html`<span class="fd-sum rem">${T("Remove {value} from {field}", { value: i.value, field: lbl(i.field) })}</span>`
          : html`<span class="rev-file mono">${i.field}</span>`}
        <span class="grow"></span>
        ${i.kind === "wire" || i.kind === "vwire" ? html`<span class="rc-wtag">${T("Needs wiring")}</span>` : null}
      </label>`)}
    </div>
  <//>`;
}
// Flatten a client's changed files into individual, reviewable changes: one item per added/removed field, or a single
// T("source changed") item for commit-only sources we can't field-parse (Kotlin / Markdown).
export function rosterChanges(client) {
  const items = [];
  for (const f of (client.files || [])) {
    if (f.status !== "changed") continue;
    const fname = f.path.split("/").pop(), fd = f.field_diff;
    const na = fd ? (fd.added || []) : [], nr = fd ? (fd.removed || []) : [];
    if (na.length || nr.length) {
      na.forEach(x => items.push({ key: fname + ":+" + x, file: fname, kind: "add", field: x, assisted: !!fd.assisted }));
      nr.forEach(x => items.push({ key: fname + ":-" + x, file: fname, kind: "rem", field: x, assisted: !!fd.assisted }));
    } else {
      items.push({ key: fname + ":src", file: fname, kind: "src", field: null });
    }
  }
  return items;
}
// "Review" → child modal listing each upstream change with a checkbox. "Adopt changes" records we've caught up
// (rosterAck); "Preserve current" backs out untouched. Field selection is a review aid — ack is whole-client (the
// schema edit itself, when one's needed, stays a code change), so this confirms the operator has seen the drift.
export function openRosterReview(cid, client, onAdopt) { pushModal(html`<${RosterReviewSheet} cid=${cid} client=${client} onAdopt=${onAdopt}/>`); }
export function RosterReviewSheet({ cid, client, onAdopt }) {
  const items = rosterChanges(client);
  const [checked, setChecked] = useState(() => { const m = {}; items.forEach(i => m[i.key] = true); return m; });
  const [busy, setBusy] = useState(false);
  const allOn = items.length > 0 && items.every(i => checked[i.key]);
  const someOn = items.some(i => checked[i.key]);
  const toggleAll = () => { const v = !allOn; setChecked(() => { const m = {}; items.forEach(i => m[i.key] = v); return m; }); };
  const toggle = k => setChecked(m => ({ ...m, [k]: !m[k] }));
  const adopt = async () => { setBusy(true); try { await onAdopt(cid); } finally { closeModal(); } };
  const color = turnClientColor(cid);
  return html`<${Sheet} title=${T("Review changes")} width=${520} noGuard=${true} onClose=${closeModal} onBack=${closeModal}
      foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" disabled=${busy} onClick=${closeModal}>${T("Preserve current")}</button><button class="btn btn-primary" disabled=${busy} onClick=${adopt}>${busy ? T("adopting…") : T("Adopt changes")}</button><//>`}>
    <p class="hint" style="margin:2px 0 12px">${T("Upstream changes to")} <b style=${color ? "color:" + color : ""}>${client.name}</b>${T("'s config schema since you last reviewed it. Adopting records you've caught up — the schema edit itself, if one's needed, is a code change.")}</p>
    ${!items.length
      ? html`<div class="notice"><${Ic} i="info"/><span>${T("The source moved but nothing field-level was parsed — adopt to acknowledge the new commit.")}</span></div>`
      : html`<div class="revlist">
          <label class="rev-all"><input type="checkbox" checked=${allOn} ref=${el => el && (el.indeterminate = !allOn && someOn)} onChange=${toggleAll}/><span>${T("Check all")}</span></label>
          ${items.map(i => html`<label class=${"rev-item " + i.kind} key=${i.key}><input type="checkbox" checked=${!!checked[i.key]} onChange=${() => toggle(i.key)}/>
            <span class="rev-file mono">${i.file}</span>
            ${i.kind === "add" ? html`<span class="fd-sum add">+ ${i.field}</span>` : i.kind === "rem" ? html`<span class="fd-sum rem">− ${i.field}</span>` : html`<span class="faint">${T("source changed")}</span>`}
            ${i.assisted ? html`<span class="fd-approx" title=${T("Best-effort parse (Python/Go source)")}>≈</span>` : null}</label>`)}
        </div>`}
  <//>`;
}
// Servers-tab gear → set a fork's SERVER-flag defaults (turn_server_defaults[fork]) — pre-fills new proxies of that fork.
// Version & rollback for a whole fork, PER NODE. A fork shares ONE binary per node (both -connect and WDTT), so the
// version + rollback hold live per (node, fork) — every instance of the fork on a node moves together. Lives in the
// fork settings modal (not the per-instance sheet) because that's the granularity. -connect rolls back by reinstalling
// each of the fork's services to the pinned tag; WDTT sets the per-fork hold (its reconcile swaps the shared binary).
// Compare version-ish tags numerically (v2.0.1 > v1.8.0 > v11-vs-v2 by segment) → >0 when `a` is newer.
export function verCmp(a, b) {
  const seg = s => String(s).replace(/^v/i, "").split(/[^0-9]+/).filter(x => x !== "").map(Number);
  const pa = seg(a), pb = seg(b);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) { const d = (pa[i] || 0) - (pb[i] || 0); if (d) return d; }
  return 0;
}
export function ForkVersionPanel({ f, commitRef, onDirty }) {
  useStore();
  const fork = f.id, kind = f.kind, owner = f.owner;
  const wdtt = kind === "wdtt";
  const csqtt = kind === "csqtt";   // panel-hosted single binary (like WDTT), reported under snap.csqtt — its own iface, no fork variance
  // nodes running this fork + the installed version (shared per fork on a node) + the service/iface list to act on
  const running = {};
  for (const [nid, snap] of Object.entries(Store.stats || {})) {
    if (csqtt) { for (const c of (snap.csqtt || [])) if (c && c.iface) { const m = running[nid] = running[nid] || { version: "", ids: [] }; if (c.version) m.version = c.version; m.ids.push(c.iface); } }
    else if (wdtt) { for (const w of (snap.wdtt || [])) if (w && w.fork === fork && w.iface) { const m = running[nid] = running[nid] || { version: "", ids: [] }; if (w.version) m.version = w.version; m.ids.push(w.iface); } }
    else { for (const tp of (snap.turn_proxies || [])) if (tp.service && turnFork(tp.service) === fork) { const m = running[nid] = running[nid] || { version: "", ids: [] }; if (tp.version) m.version = tp.version; m.ids.push(tp.service); } }
  }
  const nids = Object.keys(running).sort((a, b) => Store.nodeName(a).localeCompare(Store.nodeName(b)));
  const [vmap, setVmap] = useState({});   // nid -> versions[] (newest-first). ONLY the version list loads async.
  const [sel, setSel] = useState({});     // nid -> user override; absent = the actual hold (heldOf) — so the dropdown shows the right value on open, no "latest" flash
  const heldOf = nid => (Store.turnHolds[nid] || {})[fork] || "";   // sync, from /api/state → correct current selection immediately
  const curSel = nid => (nid in sel ? sel[nid] : heldOf(nid));
  const key = nids.join(",");
  useEffect(() => { let live = true; (async () => {
    const out = {};
    for (const nid of nids) {
      if (csqtt) { out[nid] = []; }   // csqtt: version board wires with the published-build catalog; latest-only until then
      else if (wdtt) { const r = await api.wdttVersions({ node: nid, iface: running[nid].ids[0] || "", fork }); if (r && r.ok) out[nid] = r.data.versions || []; }
      else { const r = await api.turnVersions({ owner, node: nid, fork }); if (r && r.ok) out[nid] = (r.data.tags || []).map(t => t.tag); }
    }
    if (live) setVmap(out);
  })(); return () => { live = false; }; }, [key, fork]);
  const dirty = nids.some(nid => curSel(nid) !== heldOf(nid));
  useEffect(() => { if (onDirty) onDirty(dirty); }, [dirty]);
  // The sheet's Save calls this: apply each changed node — pin a version (hold) or "" = release the hold + take latest.
  // Returns a list of human-readable errors (empty = ok) so Save can surface a failure instead of silently "succeeding".
  if (commitRef) commitRef.current = async () => {
    const errs = [];
    for (const nid of nids) {
      const want = curSel(nid), cur = heldOf(nid);
      if (want === cur) continue;
      if (csqtt) { continue; }   // csqtt: no pinnable builds yet — the dropdown is latest-only, nothing to apply
      if (wdtt) { const r = await api.wdttVersion({ node: nid, iface: running[nid].ids[0], ver: want }); if (r && !r.ok) errs.push(Store.nodeName(nid) + ": " + (srvText(r) || "failed")); }
      else { for (const svc of running[nid].ids) { const r = await api.turnReinstall({ node: nid, service: svc, owner, ...(want ? { tag: want } : {}) }); if (r && !r.ok) { errs.push(Store.nodeName(nid) + ": " + (srvText(r) || "failed")); break; } } }
    }
    return errs;
  };
  if (!nids.length) return html`<div class="hint">${T("Not deployed on any node yet — version & rollback appear once a {v1} server is running.", { v1: f.label || fork })}</div>`;
  // A node whose running version doesn't match a pin it was told to install → the reinstall FAILED on the node
  // (e.g. a checksum mismatch); surface it rather than pretend the pin took.
  return html`<div class="fvp">${nids.map(nid => { const versions = vmap[nid] || []; const inst = running[nid].version || "—"; const held = heldOf(nid);
    const sorted = versions.slice().sort((a, b) => verCmp(b, a));   // newest first
    const latest = sorted[0] || "";
    let opts = sorted.filter(x => x !== latest);   // the newest IS "Use latest" — don't list it as a pin too
    if (held && !opts.includes(held)) opts = [held, ...opts].sort((a, b) => verCmp(b, a));   // but keep a held-at-latest pin selectable
    const mismatch = held && inst !== "—" && inst !== held;   // held at X but running Y → the node rejected/failed the swap
    return html`<div class="fvp-node" key=${nid}>
      <div class="fvp-head">
        <span class="fvp-dot" style=${"background:" + (Store.nodeColor(nid) || "var(--ink)")}></span>
        <b class="fvp-nm">${Store.nodeName(nid)}</b>
        <span class="fvp-ver">${T("Installed")} <span class="mono">${inst}</span>${running[nid].ids.length > 1 ? html` · <span class="faint">${plural(running[nid].ids.length, "server")}</span>` : ""}</span>
        ${held ? html`<span class="tg" style=${"color:var(--" + (mismatch ? "dangling" : "warn") + ");background:color-mix(in srgb,var(--" + (mismatch ? "dangling" : "warn") + ") 16%,transparent)"}>${T("held · {v1}", { v1: held })}</span>` : null}
      </div>
      <div class="fvp-act">
        <select class="selwrap fvp-sel" value=${curSel(nid)} onChange=${e => setSel(m => ({ ...m, [nid]: e.target.value }))}>
          <option value="">${T("Use latest version")}</option>
          ${opts.map(x => html`<option value=${x}>${x}</option>`)}
        </select>
        ${curSel(nid) !== heldOf(nid) ? html`<span class="fvp-pend"><${Ic} i="pencil"/> ${T("tag|unsaved")}</span>` : null}
      </div>
      ${mismatch ? html`<div class="notice warn" style="margin:2px 0 0"><${Ic} i="warn"/><span>${Trich("Pinned to *{held}* but the node is still running *{inst}* — the version swap failed on the node (often a checksum mismatch). Check the proxy's status, then re-try or pick a different version.", { held, inst })}</span></div>` : null}
    </div>`; })}
  </div>`;
}
export function openServerDefaults(fork) { pushModal(html`<${ServerDefaultsSheet} fork=${fork}/>`); }
export function ServerDefaultsSheet({ fork }) {
  useStore();
  const f = turnForkList().find(x => x.id === fork) || {};
  const schema = f.settings || [];
  const stored = ((Store.panelSettings || {}).turn_server_defaults || {})[fork] || {};
  const keyField = schema.find(d => d.type === "hexkey");
  const baseTyped = () => { const v = {}; schema.forEach(d => { const s = stored[d.key]; v[d.key] = (s === undefined || s === null) ? (d.default === undefined ? "" : d.default) : s; }); return v; };
  const [vals, setVals] = useState(baseTyped);
  const [extra, setExtra] = useState(stored._extra || "");
  const [busy, setBusy] = useState(false); const [flash, setFlash] = useState(null); const [savedOnce, setSavedOnce] = useState(false);
  const [verOpen, setVerOpen] = useState(true);   // open the Version & rollback section by default (both WDTT and turn-proxies)
  const verCommitRef = useRef(null); const [verDirty, setVerDirty] = useState(false);   // version dropdowns → applied on Save
  const setV = (k, v) => setVals(o => ({ ...o, [k]: v }));
  const defaultsDirty = JSON.stringify({ ...vals, _extra: extra }) !== JSON.stringify({ ...baseTyped(), _extra: (stored._extra || "") });
  const dirty = defaultsDirty || verDirty;
  const save = async () => {
    setBusy(true); setFlash(null);
    if (defaultsDirty) {
      const keyUsed = turnKeyUsed(schema, vals);
      const all = { ...((Store.panelSettings || {}).turn_server_defaults || {}) };
      const clean = {}; schema.forEach(d => { if (d === keyField && !keyUsed) return; const vv = vals[d.key]; if (vv !== undefined && vv !== null && vv !== "") clean[d.key] = vv; });
      if (extra.trim()) clean._extra = extra.trim();
      all[fork] = clean;
      const r = await api.panelSettings({ turn_server_defaults: all });
      if (!r.ok) { setBusy(false); setFlash(srvText(r) || T("Save failed")); return false; }
    }
    if (verDirty && verCommitRef.current) {   // apply version pins/rollbacks; surface any per-node error instead of a silent success
      const errs = await verCommitRef.current();
      if (errs && errs.length) { setBusy(false); setFlash(errs.join(" · ")); return false; }
    }
    await Store.poll(); closeModal();
    toast(verDirty ? T("Version change requested — applies on each node's next sync.") : T("Server defaults saved — used when creating new {v1} proxies.", { v1: f.label || fork }), "ok");
    return true;
  };
  return html`<${Sheet} title=${html`Server defaults <span class="faint" style="text-transform:none;letter-spacing:0">— ${fork}</span>`} width=${680} noGuard=${true} onClose=${closeModal} onBack=${closeModal}
      foot=${footRow({ left: flash ? html`<span class="vk-status ok savedmsg"><${Ic} i="check"/> ${flash}</span>` : null, cancelLabel: (savedOnce && !dirty) ? T("Close") : T("Cancel"), onCancel: closeModal, disabled: busy || !dirty, onAction: save, action: busy ? T("Saving…") : T("Save") })}>
    <p class="hint" style="margin:2px 0 14px">${isSelfContainedKind(f.kind)
      ? Trich("Extra command-line flags that *pre-fill* a new {v1} server. It's self-contained — its real config lives per interface — so there's little to default here beyond advanced flags.", { v1: f.label || fork })
      : Trich("The ExecStart flags that *pre-fill* a new {v1} proxy. Nothing here changes proxies you've already deployed.", { v1: fork })}</p>
    <${TurnServerFields} schema=${schema} vals=${vals} setV=${setV} extra=${extra} setExtra=${setExtra} listen="server_ip:port" connect="interface_ip:port" template=${true} wdtt=${isSelfContainedKind(f.kind)}/>
    <${Disclosure} title=${T("Version & rollback")} sumCls="route" open=${verOpen} onToggle=${() => setVerOpen(o => !o)}>
      <p class="hint" style="margin:0 0 10px">${Trich("A {fork} server shares one binary per node, so the version is per node — every {fork} instance on a node moves together. Pinning an older version *holds* it (no auto-update); *Use latest* follows new releases.", { fork: f.label || fork })}</p>
      <${ForkVersionPanel} f=${f} commitRef=${verCommitRef} onDirty=${setVerDirty}/>
    <//>
  <//>`;
}
// What a queued turn-proxy request reads as while the node works on it. Built on first use, not at module
// load, so the words come from the loaded catalog (same rule as ui.js's label tables).
let _turnPend = null;
export function turnPendLabel(act) {
  if (!_turnPend) _turnPend = { install: T("ifop|installing"), manage: T("ifop|applying"), rotate: T("ifop|rotating"), delete: T("ifop|deleting"),
    onboard: T("ifop|adopting"), restart: T("ifop|restarting"), reinstall: T("ifop|installing"), start: T("ifop|starting"), stop: T("ifop|stopping") };
  return _turnPend[act] || "";
}
// turn-proxy restart completion flash: when a queued 'restart' clears, show a green "restarted" tag 5s
const _turnRestartPend = {};   // "node|service" currently mid-restart (last poll)
export const turnRestarted = {};      // "node|service" -> expiry ts for the green flash
export const turnUpdating = {};        // "node|service" -> expiry ts; set on an "Update" click so the pending tag reads "updating" (not "installing")
export const turnUpdateTarget = {};    // forkId -> {ver, until}: the version a fleet-wide Update is driving to, so the version bubble can flag converged nodes "updated" (independent of the transient turnCheck state)
export const turnReady = {};          // "node|service" -> expiry ts for the blue "ready" flash (5s after it settles → then no tag)
export const turnUpdatedFlash = {};   // "node|service" -> expiry ts: settle that FOLLOWED an Update click → green "updated" (not "ready")
export const turnWasUpd = {};         // "node|service" -> was this card update-in-flight last render (→ flash "updated" when it settles)
export const turnWasBusy = {};        // "node|service" -> was it pending/installing/op last render (settle → ready)
export const turnWasInstalling = {};  // "node|service" -> was it INSTALLING last render (install end → "ready" optimistically, never bounce to pending)
export function trackTurnRestarts() {
  const seen = {};
  for (const n of (Store.nodes || [])) {
    for (const [svc, act] of Object.entries(n.turn_pending || {})) if (act === "restart") seen[n.id + "|" + svc] = true;
  }
  for (const k of Object.keys(_turnRestartPend)) if (!seen[k]) {   // was restarting, now cleared → done
    turnRestarted[k] = Date.now() + 5000; delete _turnRestartPend[k];
    setTimeout(() => Store.apply(), 0);      // re-render NOW so the "restarted" flash shows on the current screen
    setTimeout(() => Store.apply(), 5100);   // and again to clear it when the 5s window ends
  }
  for (const k of Object.keys(seen)) _turnRestartPend[k] = true;
}

export async function cancelTurn(node, body) {
  const r = await api.turnCancel({ node, ...body });
  if (!r.ok) return toast(srvText(r) || T("Failed to cancel."), "err");
  await Store.poll(); toast(T("Pending turn-proxy request cancelled."), "ok");
}
export async function restartTurn(node, service) {
  const r = await api.turnRestart({ node, service });
  if (!r.ok) return toast(srvText(r) || T("Failed to restart."), "err");
  await Store.poll(); toast(T("Restart requested — applies on the node's next sync."), "ok");
}
export async function stopTurn(node, service) {
  const r = await api.turnStop({ node, service });
  if (!r.ok) return toast(srvText(r) || T("Failed to stop."), "err");
  await Store.poll(); toast(T("Stop requested — applies on the node's next sync."), "ok");
}
export async function startTurn(node, service) {
  const r = await api.turnStart({ node, service });
  if (!r.ok) return toast(srvText(r) || T("Failed to start."), "err");
  await Store.poll(); toast(T("Start requested — applies on the node's next sync."), "ok");
}
export function openSetupTurn(node, forwardIface) { openModal(html`<${SetupTurnSheet} node=${node} forwardIface=${forwardIface}/>`); }
export function SetupTurnSheet({ node, forwardIface }) {
  const FORKS = enabledTurnForks().filter(f => !isSelfContainedKind(f.kind));   // forks that FRONT an interface; WDTT + csqtt are self-contained (created as their own interface), never added to one
  const [mode, setMode] = useState("new");   // new (install) | existing (adopt)
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const snap = Store.stats[node] || {};
  const isBridge = nrec.kind === "docker" && (nrec.net_mode || "host") === "bridge";
  const allIfaces = Object.entries(snap.interfaces || {})
    .map(([n, b]) => ({ name: n, port: String((b.meta || {}).listen_port || ""), sys: !!(b.meta || {}).system || n.startsWith("swg_") || isWdttIface(n), awg: !!Object.keys((b.meta || {}).awg_params || {}).length }))
    .filter(i => i.port && !i.sys);   // turn proxies forward to USER interfaces only — never the system/mesh link (swg_*)
  // launched from an interface's page → pre-select it as the forwards-to (and, if it's AmneziaWG, start on a fork that can front it)
  const fwdPre = forwardIface ? allIfaces.find(i => i.name === forwardIface) : null;
  const [fork, setFork] = useState(((fwdPre && fwdPre.awg ? FORKS.find(x => forkSupportsAwg(x.id)) : null) || FORKS[0] || turnForkList()[0]).id);
  const epIp = (() => {   // the node's PUBLIC endpoint (what clients dial); on bridge the proxy rebinds it to 0.0.0.0
    for (const b of Object.values(snap.interfaces || {})) {
      const ep = (b.meta || {}).endpoint || "";
      if (ep) return ep.includes(":") ? ep.slice(0, ep.lastIndexOf(":")) : ep;
    }
    return "";
  })();
  // include the public endpoint so bridge nodes (whose reported ips are container-private + filtered) still offer it
  const ips = [...new Set([epIp, (nrec.endpoint_host || "").trim(), ...(nrec.ips || [])].filter(Boolean))];
  // a WireGuard-only fork can't front an AmneziaWG interface → hide awg interfaces from its picker
  const ifaces = forkSupportsAwg(fork) ? allIfaces : allIfaces.filter(i => !i.awg);
  const hideAwg = !forkSupportsAwg(fork) && allIfaces.some(i => i.awg);
  const lInit = epIp ? (ips.includes(epIp) ? epIp : "__custom__") : (ips[0] || "__custom__");
  const [lsel, setLsel] = useState(lInit);
  const [lcustom, setLcustom] = useState(lInit === "__custom__" ? epIp : "");
  const [lport, setLport] = useState(String(suggestPort(node, "turn")));
  const tsperr = portErrMsg(node, lport, []);   // live listen-port collision check (new proxy → no own port)
  const [fwd, setFwd] = useState(fwdPre ? fwdPre.name : (ifaces[0] ? ifaces[0].name : "__custom__"));
  const [custom, setCustom] = useState("127.0.0.1:51820");
  const [title, setTitle] = useState("");
  const [wrapKey] = useState(randWrapKey);            // one fresh key, reused so a fork switch is deterministic
  // default params = the fork's typed schema serialised with the fixed key (byte-identical to the old wrap+keyflag
  // default, but now stable across renders so the pickFork "untouched default" check still fires).
  const dflParams = fk => { const sch = forkSettings(fk.id); const sd = ((Store.panelSettings || {}).turn_server_defaults || {})[fk.id] || {};   // schema defaults (+ a fresh key), the fork's saved obfuscation DEFAULTS on top, then its free-entry extra flags appended
    const base = serializeTurnSettings(sch, { ...defaultSettingValues(sch, { key: wrapKey }), ...sd });   // sd._extra isn't a schema key → serialize ignores it
    return base + (sd._extra ? (base ? " " : "") + sd._extra : ""); };
  const [params, setParams] = useState(dflParams(FORKS[0] || turnForkList()[0]));
  const [openSec, setOpenSec] = useState(null);   // the strip's open section — null | "server"
  const [path, setPath] = useState("");
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const fail = t => { setBusy(false); setMsg({ k: "err", t }); };
  const isCustom = fwd === "__custom__";
  const f = turnForkList().find(x => x.id === fork) || FORKS[0] || turnForkList()[0];
  const lhost = ipPickerVal(lsel, lcustom);
  // WDTT (kind:"wdtt") owns its OWN built-in userspace-WG interface, so there's no Forwards-to. The internals
  // (iface / subnet / internal WG port) are auto-assigned to avoid collisions with this node's existing wdtt
  // instances + interfaces, and stay advanced-editable. Listen IP/port above are the PUBLIC DTLS endpoint.
  // WDTT (kind:"wdtt") is a SELF-CONTAINED server — it owns its built-in userspace-WG interface, so its Setup body
  // (interface/subnet/ports) + submit are entirely different from a -connect fork. Rather than branch turn-shaped
  // code, its fields live in <WdttInstanceBody/> (dispatched in the body below); it registers its save() in
  // wdttSaveRef, which this sheet's shared save() delegates to. Keeps this component turn-only.
  const isWdtt = f.kind === "wdtt";
  const isCsqtt = f.kind === "csqtt";
  const isSelfContained = isWdtt || isCsqtt;   // both create their own interface (no Forwards-to picker)
  const wdttSaveRef = useRef(null);
  const csqttSaveRef = useRef(null);
  const pickFork = id => {   // re-default params for the new fork only if the field is still an untouched default
    const cf = turnForkList().find(x => x.id === fork) || turnForkList()[0];
    const nf = turnForkList().find(x => x.id === id) || turnForkList()[0];
    if (params === dflParams(cf)) setParams(dflParams(nf));
    // switching to a WG-only fork while an awg interface is selected → move to the first WG interface (or custom)
    if (!forkSupportsAwg(id) && fwd !== "__custom__" && !allIfaces.some(i => i.name === fwd && !i.awg)) {
      const firstWg = allIfaces.find(i => !i.awg); setFwd(firstWg ? firstWg.name : "__custom__");
    }
    setFork(id);
  };
  const randKey = () => copy(randWrapKey(), T("Random 64-hex key copied — paste it into the parameters"));
  const save = async () => {
    if (mode === "existing") {
      const p = path.trim();
      if (!p.startsWith("/") || !p.endsWith(".service")) return fail(T("Enter the absolute path to the .service unit."));
      setBusy(true); setMsg({ k: "work", t: "requesting…" });
      const r = await api.turnOnboard({ node, path: p });
      if (!r.ok) return fail(srvText(r) || T("Request failed."));
      closeModal(); await Store.poll();
      return toast(T("Turn-proxy adopt requested — the node reads it on its next sync."), "ok");
    }
    if (!lhost) return fail(T("Listen IP is required."));
    if (!/^\d+$/.test(lport.trim())) return fail(T("Listen port must be a number."));
    if (isCsqtt) return csqttSaveRef.current ? csqttSaveRef.current(lhost, lport.trim()) : fail(T("csqtt fields aren't ready yet."));
    if (isWdtt) return wdttSaveRef.current ? wdttSaveRef.current(lhost, lport.trim()) : fail(T("WDTT fields aren't ready yet."));
    let connect;
    if (isCustom) { connect = custom.trim(); if (!/:\d+$/.test(connect)) return fail(T("Forwards-to must be host:port.")); }
    else { connect = "127.0.0.1:" + ifaces.find(i => i.name === fwd).port; }
    // OPTIMISTIC: seed the card and close NOW — the install takes as long as it takes on the node (binary
    // download), and its progress belongs on the card, not behind a blocked modal. The service id is predictable
    // (vk-turn-proxy-<fork>-<port>); if the panel returns a different one we re-key the placeholder, and if the
    // request is rejected we drop it again and say so.
    const svc = "vk-turn-proxy-" + f.id + "-" + lport.trim();
    const _tkey = node + "|" + svc;
    Store.turnNew[_tkey] = { listen: lhost + ":" + lport.trim(), connect, title: title.trim(), at: Date.now() };
    closeModal(); Store.apply();
    const r = await api.turnInstall({ node, fork: f.id, owner: f.owner, wrap_flags: f.wrap,
      listen: lhost + ":" + lport.trim(), connect, title: title.trim(), params: params.trim() });
    if (!r || !r.ok) { delete Store.turnNew[_tkey]; Store.apply(); return toast(srvText(r) || T("Turn-proxy install failed."), "err"); }
    const _real = (r.data && r.data.service) || svc;
    if (_real !== svc) { Store.turnNew[node + "|" + _real] = Store.turnNew[_tkey]; delete Store.turnNew[_tkey]; }
    await Store.poll();
    toast(T("Turn-proxy install requested — the node downloads + starts it on its next sync."), "ok");
  };
  return html`<${Sheet} title=${mode === "new" ? turnSheetTitle(f.label, title) : T("Adopt turn-proxy")} width=${880}
    foot=${footRow({ onCancel: closeModal, disabled: busy || !!tsperr || (mode === "new" && !FORKS.length), title: tsperr || "", onAction: save, action: mode === "existing" ? T("Adopt") : (isSelfContained ? T("Create") : T("Install")) })}>
    <div class="field"><label>${T("Source")}</label>
      <div class="chiprow proto3">
        <button class=${"chip c-awg" + (mode === "new" ? " on" : "")} onClick=${() => setMode("new")}>${T("Install a fork")}</button>
        <button class=${"chip c-ex" + (mode === "existing" ? " on" : "")} onClick=${() => setMode("existing")}>${T("Adopt existing service")}</button>
      </div></div>
    ${mode === "existing" ? html`<${Fragment}>
      <div class="iface-intro big">
        <div>${T("Adopt a turn-proxy already running as a systemd service on this node.")}</div>
        <div>${T("The node reads the unit's ExecStart (listen, forwards-to, wrap key) on its next sync and it shows up here.")}</div>
      </div>
      <div class="field"><label>${T("Service unit path")}</label><input autofocus value=${path} onInput=${e => setPath(e.target.value)} placeholder="/etc/systemd/system/vk-turn-proxy-...service" autocomplete="off"/></div>
    <//>` : html`<${Fragment}>
      <div class="row2">
        <div class="field"><label>${T("col|Title")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— optional")}</span></label><input value=${title} onInput=${e => setTitle(e.target.value)} placeholder=${f.label} autocomplete="off"/></div>
        <div class="field"><label>${T("Fork")}</label>
          <select class="selwrap" value=${fork} disabled=${!FORKS.length} onChange=${e => pickFork(e.target.value)}>
            ${FORKS.map(x => html`<option value=${x.id}>${x.label}${(x.wrap || x.keyflag) ? "" : " · no obfuscation"}</option>`)}
          </select>
          <div class="hint">${FORKS.length ? f.owner : T("No forks enabled — turn them on in Panel settings → Turn proxies.")}</div></div>
      </div>
      <div class="row2">
        <div class="field"><label>${T("Listen IP")}</label>
          <${IpPicker} ips=${ips} sel=${lsel} setSel=${setLsel} custom=${lcustom} setCustom=${setLcustom} placeholder="203.0.113.7"/>
          <div class="hint">${T("An address on this server — the proxy binds to it")}</div></div>
        <div class="field"><label>${T("Listen port")}</label><input class=${tsperr ? "bad" : ""} value=${lport} onInput=${e => setLport(e.target.value)} placeholder="56000"/>${tsperr ? html`<div class="hint err">${tsperr}</div>` : null}</div>
      </div>
      ${lsel === "__custom__" && lhost && !ips.includes(lhost) ? (isBridge
        ? html`<div class="notice" style="margin:-6px 0 16px"><${Ic} i="info"/><span>${Trich("Bridge node: the proxy binds `0.0.0.0` inside the container and this port is published, so enter the node's *public* IP/host (what clients dial) here.")}</span></div>`
        : html`<div class="notice warn" style="margin:-6px 0 16px"><${Ic} i="warn"/><span>${Trich("This isn't a detected address on the node. The proxy *binds* to it, so it must be a real IP on the server — otherwise it dies with `bind: cannot assign requested address`.")}</span></div>`) : null}
      ${isCsqtt ? html`<${CsqttInstanceBody} node=${node} snap=${snap} saveRef=${csqttSaveRef} setBusy=${setBusy} setMsg=${setMsg} fail=${fail}/>`
       : isWdtt ? html`<${WdttInstanceBody} node=${node} snap=${snap} saveRef=${wdttSaveRef} setBusy=${setBusy} setMsg=${setMsg} fail=${fail}/>` : html`<${Fragment}>
      <div class="field"><label>${T("Forwards to")}</label>
        <select class="selwrap" value=${fwd} onChange=${e => setFwd(e.target.value)}>
          ${ifaces.map(i => html`<option value=${i.name}>${i.name} · 127.0.0.1:${i.port}</option>`)}
          <option value="__custom__">${T("Custom IP:Port…")}</option>
        </select>
        ${hideAwg ? html`<div class="hint">${T("{v1} is WireGuard-only — AmneziaWG interfaces are hidden.", { v1: fork })}</div>` : null}
      </div>
      ${isCustom ? html`<div class="field"><input value=${custom} onInput=${e => setCustom(e.target.value)} placeholder="127.0.0.1:51820" autocomplete="off"/></div>` : null}
      <${Disclosure} title=${T("Server parameters")} summary=${forkSettings(fork).length ? null : html`<span class="faint">${T("val|none")}</span>`} open=${openSec === "server"} onToggle=${() => setOpenSec(s => s === "server" ? null : "server")}>
        <${TurnParamsEditor} fork=${fork} node=${node} value=${params} onChange=${setParams} listen=${(lhost || "server_ip") + ":" + (lport || "port")} connect=${isCustom ? (custom || "interface_ip:port") : ("127.0.0.1:" + (((ifaces.find(i => i.name === fwd)) || {}).port || "port"))}/>
      <//>
    <//>`}
    <//>`}
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// WDTT (self-contained server) Setup body — the built-in interface/subnet/ports a -connect fork has no concept of.
// Kept OUT of SetupTurnSheet so that sheet stays turn-shaped; it registers its save() in saveRef, which the sheet's
// shared footer triggers. Auto-assigns a free iface + /24 subnet + internal WG port for this node, scanning its
// interfaces, turn-proxies and existing WDTT instances so nothing collides.
export function WdttInstanceBody({ node, snap, saveRef, setBusy, setMsg, fail }) {
  const used = (() => {
    const ifaces = new Set(), subs = new Set(), ports = new Set();
    Object.entries(snap.interfaces || {}).forEach(([n, b]) => {
      if (isWdttIface(n)) ifaces.add(n);
      const p = parseInt((b.meta || {}).listen_port, 10); if (p) ports.add(p);
    });
    (snap.turn_proxies || []).forEach(tp => { const p = parseInt(String(tp.listen || "").split(":").pop(), 10); if (p) ports.add(p); });
    (snap.wdtt || []).forEach(w => { if (!w) return;
      if (w.iface) ifaces.add(w.iface);
      if (w.wg_addr) subs.add(String(w.wg_addr).split("/")[0].split(".").slice(0, 3).join("."));
      const wp = parseInt(w.wg_port, 10); if (wp) ports.add(wp);
      const lp = parseInt(String(w.listen || "").split(":").pop(), 10); if (lp) ports.add(lp);
    });
    return { ifaces, subs, ports };
  })();
  const nextIface = (() => { for (let i = 0; i < 100; i++) if (!used.ifaces.has("wdtt" + i)) return "wdtt" + i; return "wdtt0"; })();
  const nextSubnet = (() => { for (let i = 66; i < 230; i++) { const b = "10.66." + i; if (!used.subs.has(b)) return b + ".1/24"; } return "10.66.66.1/24"; })();
  const nextWgPort = (() => { for (let p = 56001; p < 56999; p++) if (!used.ports.has(p)) return String(p); return "56001"; })();
  const [iface, setIface] = useState(nextIface);
  const [subnet, setSubnet] = useState(nextSubnet);
  const [wgPort, setWgPort] = useState(nextWgPort);
  const [adv, setAdv] = useState(false);
  const wgperr = portErrMsg(node, wgPort, []);   // live internal-WG-port collision check (new interface → no own port)
  saveRef.current = async (lhost, lport) => {
    if (!isWdttIface(iface.trim())) return fail(T("Interface must be wdtt0–wdtt999."));
    if (!/^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/.test(subnet.trim())) return fail(T("Subnet must be an IPv4 CIDR (e.g. 10.66.66.1/24)."));
    if (!/^\d+$/.test(String(wgPort).trim())) return fail(T("Internal WG port must be a number."));
    if (wgperr) return fail(wgperr);   // caught in the browser (never a node-side "FAILED TO APPLY")
    if (lport && String(lport).trim() === String(wgPort).trim()) return fail(T("The DTLS listen port and internal WG port must differ."));
    setBusy(true); setMsg({ k: "work", t: T("creating WDTT server… (the node installs it on its next sync)") });
    const r = await api.wdttSet({ node, iface: iface.trim(), wg_addr: subnet.trim(),
      listen: lhost + ":" + lport, wg_port: parseInt(String(wgPort).trim(), 10), max_passwords: 200, stopped: false });
    if (!r.ok) return fail(srvText(r) || T("Request failed."));
    closeModal(); Store.apply(); await Store.poll();
    toast(T("WDTT server requested — the node installs it on its next sync. Add users from Peers."), "ok");
  };
  return html`<${Fragment}>
    <div class="field"><label>${T("Serves")}</label>
      <div class="selwrap" style="display:flex;align-items:center;justify-content:space-between;opacity:.9">
        <span>${T("Built-in userspace WireGuard")}</span>
        <span class="mono faint">${iface} · ${subnet}</span>
      </div>
      <div class="hint">${T("WDTT owns its own WireGuard interface — users attach to it directly (no forwards-to). WDTT mints each user's key + IP on connect; you add + manage users from Peers.")}</div>
    </div>
    <${Disclosure} title=${T("Advanced — built-in interface")} open=${adv} onToggle=${() => setAdv(a => !a)}>
      <div class="row2">
        <div class="field"><label>${T("col|Interface")}</label><input value=${iface} onInput=${e => setIface(e.target.value)} placeholder="wdtt1" autocomplete="off"/></div>
        <div class="field"><label>${T("Internal WG port")}</label><input class=${wgperr ? "bad" : ""} value=${wgPort} onInput=${e => setWgPort(e.target.value)} placeholder="56001" autocomplete="off"/>${wgperr ? html`<div class="hint err">${wgperr}</div>` : null}</div>
      </div>
      <div class="field"><label>${T("Internal subnet")}</label><input value=${subnet} onInput=${e => setSubnet(e.target.value)} placeholder="10.66.66.1/24" autocomplete="off"/>
        <div class="hint">${T("Auto-assigned to avoid collisions with this node's other WDTT servers, interfaces, and ports.")}</div></div>
    <//>
  <//>`;
}

// ── WDTT is a self-contained, key-owning member of the TURN-PROXY fork family: its server card renders inside
//    TurnProxiesBlock (folded there), its interface shows in the interfaces section, and its clients reuse the
//    turn app flow. WDTT-specific bits (keyless peers, built-in interface, vault restore) are kind-dispatched. ──
export const WDTT_COLOR = "#A78BFA";
export function WdttCard({ node, w, reorder }) {
  const active = w.active === "active";
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  // This card had NO node-state handling: while the node was converting (or offline, or re-installing) every
  // other card on the page dimmed and said so, and the WDTT ones sat there bright and clickable, offering to
  // open a manage sheet whose actions are all disabled. Mirror TurnCard exactly.
  const converting = (nrec.proc_status || "").startsWith("converting");
  const nblocked = nodeStale(node) || inProc(nrec.proc_status);
  const restoring = (nrec.wdtt_restoring || []).includes(w.iface);
  const awaiting = !!w.await_restore;
  const rid = "wdtt:" + w.iface;   // reorder id, namespaced so it never clashes with a turn service
  const it = reorder ? reorder.item(rid) : null;
  const _wop = Store.ifaceOp[node + "|" + w.iface];   // optimistic save lifecycle (applying/applied/failed), like every card
  const _wopTag = opTag(node + "|" + w.iface);
  const deleting = !!Store.ifaceGone[node + "|" + w.iface];   // the SAME server is shown twice (interface card + here) — both must say it is going
  const adopting = (nrec.wdtt_adopting || []).includes(w.iface);   // take-over in flight — same reason as the interface card
  const tag = deleting ? html`<${StatusTag} cls="tg-del" icon="clock" label="deleting" title=${T("The node tears it down on its next sync")}/>`
    : adopting ? html`<${StatusTag} cls="tg-busy" icon="clock" label="adopting" title=${T("The node applies the take-over on its next sync")}/>`
    : converting ? html`<${StatusTag} cls="tg-convert" icon="clock" label="converting" title=${T("The node is converting between bare-metal and docker")}/>`
    : _wopTag ? _wopTag
    : restoring ? html`<${StatusTag} cls="tg tg-pending" icon="clock" label="restoring…" title=${T("Restoring the vaulted server identity")}/>`
    : awaiting ? html`<${StatusTag} cls="tg-busy del" icon="shield" label=${T("Restore")} title=${T("A vaulted identity exists — restore it to bring this server back with its original key")}/>`
    : active ? null   // healthy → no persistent tag (matches normal turn/interface cards; reuse the standard status vocabulary)
    : html`<${StatusTag} cls="tg tg-pending" icon="clock" label="starting" title=${T("Installing / starting on the node")}/>`;
  const _wopBusy = _wop && _wop.phase === "busy";   // mid-save → don't let the card re-open the edit modal
  // awaiting restore → the SAME treatment as the interface card for the same server: dimmed with the danger
  // border (.ifcard.down), not a quiet amber pill on a full-brightness card. One server in one state should not
  // look like two different severities depending on which section you happen to be reading.
  // Same reason this covers `starting` (and converting/restoring): the SAME server shows as a dimmed interface
  // card above and, until this, a full-brightness proxy card below — the two sections disagreed about whether
  // anything was happening. This is the interface card's `idim`, term for term.
  const wdim = deleting || adopting || converting || awaiting || restoring || !active || _wopBusy;
  const wCanOpen = !_wopBusy && !nblocked && !deleting && !adopting;   // don't open a sheet whose every action is disabled
  return html`<div class=${"ifcard tp" + (wCanOpen ? " clickable" : "") + (wdim ? " down" : "") + (nblocked ? " locked" : "") + (it ? it.cls : "")} data-rid=${it ? it.rid : null} onClick=${() => { if (!wCanOpen) return; openModal(html`<${WdttManageSheet} node=${node} w=${w}/>`); }}>
    <div class="ifcard-top">${reorder ? html`<span class="drag-grip" title=${T("Drag to reorder")} onClick=${e => e.stopPropagation()} ...${reorder.grip(rid)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span>` : null}
      <span class="iftype wdtt">WDTT</span>
      <span class="ifname">${shownTitle("w|" + node + "|" + w.iface, (((nrec.wdtt_cfg || {})[w.iface] || {}).title || "").trim()) || w.iface}</span><span class="grow"></span>
      ${(() => { const conn = wdttConnRows(node, w.iface); return conn.length ? html`<${OnlPop} peer title=${T("Connected to this WDTT server")} cls="ifc-conn" rows=${conn} trigger=${c => html`<b class="oncount on">${c}</b>`}/>` : null; })()}
      ${tag}
    </div>
    <div class="ifcard-rows">
      <div class="ifrow"><span class="l">${T("WDTT fork")}</span><span class="r">${forkLabel(w.fork || "amurcanov")}</span></div>
      ${/* One address, one row: the RAW listener shares the host and differs only in port, so it reads as
            "…:56012 (56032)" with the raw port in the RAW colour — a second full row said the same thing twice. */ null}
      <div class="ifrow"><span class="l">${T("Listen")}</span><span class="r addr">${w.listen || "—"}${w.raw_port
        ? html` <b class="rawport" title=${T("RAW-IP port — no WireGuard, no forward secrecy")}>(${w.raw_port})</b>` : null}</span></div>
      <div class="ifrow"><span class="l">${T("Forwards to")}</span><span class="r"><a class="tg tg-wdtt" href=${"#/node/" + encodeURIComponent(node) + "/" + encodeURIComponent(w.iface)} onClick=${e => e.stopPropagation()}>${w.iface}</a></span></div>
    </div></div>`;
}
// The turn-half management surface, reached from the WDTT turn-proxy card (the interface card goes to the
// full interface detail instead). TODO Phase 2 (fork dimension): reshape this into the real turn modal —
// fork switch + client-apps picker + server params — and let the interface detail own lifecycle/peers, so
// the two views stop overlapping (see docs/WDTT-FORK-FAMILY-PLAN.md §"UI corrections").
export function WdttManageSheet({ node, w: w0 }) {
  useStore();   // live status / config while open
  const iface = w0.iface;
  // openModal captures the vnode — and therefore this prop — at CLICK time, so `w` is a frozen snapshot of the
  // server as it was when the modal opened. nrec below was already re-read live, but every status came from that
  // stale object: after "Recreate fresh" the node reported a healthy new server and the sheet still showed
  // "This server was wiped… Restore", because await_restore was true in a copy nothing ever updates.
  // Re-read from the live snapshot each render; fall back to the prop until the node reports it.
  const w = ((Store.stats[node] || {}).wdtt || []).find(x => x && x.iface === iface) || w0;
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const cfg = (nrec.wdtt_cfg || {})[iface] || {};
  const fork = w.fork || cfg.fork || "amurcanov";
  const forkLabel = (turnForkList().find(x => x.id === fork) || {}).label || fork;
  const [title, setTitle] = useState(shownTitle("w|" + node + "|" + iface, (cfg.title || "").trim()));   // optional cosmetic label; honour a just-saved optimistic title
  const [params, setParams] = useState((cfg.params || "").trim());   // extra ExecStart flags (advanced)
  const [srvOpen, setSrvOpen] = useState(false);
  const awaiting = !!w.await_restore;
  const restoring = (nrec.wdtt_restoring || []).includes(iface);
  const recreating = (nrec.wdtt_recreating || []).includes(iface);
  const blocked = (Store.recon.nodeStatus[node] !== "live") || inProc(nrec.proc_status);
  const notup = w.active !== "active" && !awaiting;   // stopped / starting → Start; else Stop + Restart
  // Endpoint + DTLS listen port, EDITABLE — writes to the same place as the interface edit (api.wdttSet).
  const ips = nrec.ips || [];
  const oldListen = cfg.listen || w.listen || "";
  const lhost = oldListen.includes(":") ? oldListen.slice(0, oldListen.lastIndexOf(":")) : oldListen;
  const lport = oldListen.includes(":") ? oldListen.slice(oldListen.lastIndexOf(":") + 1) : "";
  const initHost = (lhost && lhost !== "0.0.0.0") ? lhost : "";
  const [hostSel, setHostSel] = useState(initHost ? (ips.includes(initHost) ? initHost : "__custom__") : (ips[0] || "__custom__"));
  const [hostCustom, setHostCustom] = useState(initHost && !ips.includes(initHost) ? initHost : "");
  const [port, setPort] = useState(lport || "");
  const [msg, setMsg] = useState(null);
  // RAW-IP mode — a SECOND listener on the same server, qWDTT-only and off unless the operator asks for it.
  // On/off only: the port is fixed at RAW_PORT because the app dials that one number and nothing else
  // (TunnelService resolves it from a single app-wide preference and REPLACES the link's port with it), so a
  // custom port would only ever reach users who hand-edit app settings. Same reason it is one per node.
  const rawCapable = !!(turnForkList().find(x => x.id === fork) || {}).raw;
  const rawCur = String(cfg.raw_port || w.raw_port || "");
  const [rawOn, setRawOn] = useState(!!rawCur);
  const rawHolder = rawOwnerOn(node, iface);          // instance already offering RAW on THIS listen address
  // The server-internal WireGuard port: the DTLS half forwards to 127.0.0.1:<this>, no client ever dials it
  // and no link carries it. Editable because it is the one thing that can squat RAW's fixed port — which is
  // exactly how 56003 was lost on the first fleet — and there was no way to move it without hand-editing state.
  const wgCur = String(cfg.wg_port || w.wg_port || "56001");
  const [wgIn, setWgIn] = useState(wgCur);
  const wgPort = (wgIn.trim() && /^\d+$/.test(wgIn.trim())) ? wgIn.trim() : wgCur;
  const wgDirty = wgPort !== wgCur;
  const wgErr = !wgIn.trim() ? T("The internal WG port is required.")
    : !/^\d+$/.test(wgIn.trim()) ? T("The internal WG port must be a number.")
    : wgIn.trim() === port.trim() ? T("The DTLS port and the internal WG port must differ.")
    : portErrMsg(node, wgIn, [wgCur, lport]);
  const newListen = (ipPickerVal(hostSel, hostCustom).trim() || "0.0.0.0") + ":" + (port.trim() || "56000");
  const endpointDirty = !!oldListen && newListen !== oldListen;
  const titleDirty = title.trim() !== (cfg.title || "").trim();
  const paramsDirty = params.trim() !== (cfg.params || "").trim();
  const rawWant = !!(rawOn && rawCapable);
  // A server saved before the port was fixed is still listening on its old one — which the app never dials.
  // Treat that as dirty so Save migrates it to RAW_PORT in one click.
  const rawStale = !!rawCur && String(rawCur) !== String(RAW_PORT);
  const rawDirty = (rawWant !== !!rawCur) || (rawWant && rawStale);
  const anyDirty = endpointDirty || titleDirty || paramsDirty || rawDirty || wgDirty;
  // live DTLS-port check: must differ from this instance's own internal WG port, and not collide with any other
  // port on the node (its own DTLS/WG ports don't count). Blocks Save so a clash never becomes a node "FAILED TO APPLY".
  const wperr = (port.trim() && Number(port) === Number(wgPort)) ? T("The DTLS port and the internal WG port must differ.")
    : portErrMsg(node, port, [lport, wgCur]);
  // The only way RAW can be refused now: this very server is already sitting on the one port RAW needs.
  const rawErr = (!rawOn || !rawCapable) ? ""
    : (port.trim() === String(RAW_PORT) || String(wgPort) === String(RAW_PORT))
      ? T("This server is using port {v1} itself — move its listen or internal WG port before turning RAW on.", { v1: RAW_PORT })
      : "";
  const doSave = () => {
    const key = node + "|" + iface, verb = "apply";
    Store.ifaceOp[key] = { verb, phase: "busy", started: Date.now() }; Store.apply(); closeAllModals();
    const fail = m => { Store.ifaceOp[key] = { verb, phase: "fail", until: Date.now() + 6000, err: m }; Store.apply(); setTimeout(() => Store.apply(), 6100); };
    api.wdttSet({ node, iface, listen: newListen, wg_port: wgPort, fork, title: title.trim(), params: params.trim(), raw: rawWant, block: cfg.block || [], ...egressBody(egressInit(cfg)) })
      .then(r => { if (!r.ok) return fail(srvText(r) || T("save failed"));
        const mv = ((r.data || {}).raw_moved || "");
        if (mv) toast(T("RAW-IP moved from {v1} to {v2} — one raw listener per address.", { v1: mv, v2: iface }), "ok", 5000);
        Store.poll(); })
      .catch(e => fail((e && e.message) || T("save failed")));
  };
  const save = () => {
    if (port.trim() && !/^\d+$/.test(port.trim())) return setMsg({ k: "err", t: T("Listen port must be a number.") });
    if (endpointDirty) {   // endpoint / DTLS port is baked into every user's link → confirm the re-issue
      pushModal(html`<${ConfirmSheet} title=${T("Change the endpoint or port?")} confirmLabel=${T("Apply change")} warn=${true}
        body=${T("This rewrites every user's link — the endpoint and DTLS port are part of it. Existing users must re-import from their subscription page. The server key and users are kept; the server briefly reconnects.")} onConfirm=${doSave}/>`);
      return;
    }
    if (rawErr) return setMsg({ k: "err", t: rawErr });
    if (wgErr) return setMsg({ k: "err", t: wgErr });
    if (rawWant && rawHolder) {   // one RAW listener per ADDRESS — turning it on here takes it from that one
      pushModal(html`<${ConfirmSheet} title=${T("Move RAW-IP to this server?")} confirmLabel=${T("Move RAW here")} warn=${true}
        body=${Trich("*{holder}* offers RAW-IP on this address today. The app dials one fixed port for every server, so an address can only run one raw listener — turning it on here turns it off on *{holder}*. Its users keep their links and fall back to WireGuard mode. Servers on this node's other IPs are untouched.", { holder: rawHolder })} onConfirm=${doSave}/>`);
      return;
    }
    if (paramsDirty || rawDirty || wgDirty) { doSave(); return; }   // extra ExecStart flags / RAW listener → the node rewrites the unit + restarts
    // title-only → a cosmetic panel-side label (no node restart, like a turn-proxy title): store + close immediately
    closeModal();
    pushOptTitle("w|" + node + "|" + iface, title.trim());   // reflect on the card instantly
    api.wdttSet({ node, iface, listen: oldListen, wg_port: wgPort, fork, title: title.trim(), params: params.trim(), raw: rawWant, block: cfg.block || [], ...egressBody(egressInit(cfg)) })
      .then(r => { if (r && r.ok) { Store.poll(); toast(T("Title saved."), "ok"); } else toast(srvText(r) || T("Save failed."), "err"); });
  };
  const control = (verb, icon, label, title) => html`<button class="btn btn-ghost" style="margin-left:8px" disabled=${blocked || awaiting} title=${title} onClick=${() => { startOrRestartWdtt(node, iface, verb); closeModal(); }}><${Ic} i=${icon}/> ${label}</button>`;
  return html`<${Sheet}
    title=${html`WDTT-proxy · ${(title.trim() || iface)} · ${forkLabel}${w.version ? html` <span class="sheet-ver">${w.version}</span>` : ""}<button class="iconbtn sheet-verset" title=${T("Version, rollback & server defaults for {v1}", { v1: fork })} onClick=${() => openServerDefaults(fork)}><${Ic} i="gear"/></button>`}
    width=${664}
    headExtra=${w.service ? html`<${TurnIpsHeader} node=${node} svc=${w.service}/>` : null}
    foot=${footRow({ left: html`<${Fragment}>
        <button class="btn btn-ghost danger" onClick=${() => openModal(html`<${WdttDeleteSheet} node=${node} iface=${iface}/>`)}><${Ic} i="trash"/>${T("Delete")}</button>
        ${notup ? control("start", "play", T("Start service"), T("Bring this WDTT server up on the node"))
          : html`<${Fragment}>${control("stop", "stop", T("Stop service"), T("Take this WDTT server down (stays down until started)"))}${control("restart", "refresh", T("Restart service"), T("Bounce this WDTT server on the node"))}<//>`}
      <//>`, onCancel: closeModal, disabled: !anyDirty || !!wperr, onAction: save, action: "Save" })}>
    ${awaiting ? html`<div class="notice warn"><${Ic} i="shield"/><span>${Trich("This server was wiped. Its identity (server keypair + owner password) is *escrowed in your Encryption Vault*. *Restore* to bring it back with its original identity — no user re-imports.")}
      <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn btn-primary" disabled=${restoring || recreating} onClick=${() => wdttRestoreIdentity(node, iface)}><${Ic} i="shield"/> ${restoring ? T("Restoring…") : T("Restore server identity")}</button>
        <button class="btn btn-ghost" disabled=${restoring || recreating} onClick=${() => wdttRecreateFresh(node, iface)}>${recreating ? T("Recreating…") : T("Recreate fresh")}</button>
      </div></span></div>`
    : html`<${Fragment}>
      <${IfaceThroughput} node=${node} iface=${iface}/>
      <div class="iface-intro" style="margin-top:10px"><div>${T("Changing the endpoint or port rewrites the unit's ExecStart on the node and restarts it — every user's link is re-issued.")}</div></div>
      <div class="field"><label>${T("col|Title")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— optional")}</span></label><input value=${title} onInput=${e => setTitle(e.target.value)} placeholder=${iface} autocomplete="off"/></div>
      <div class="row2">
        <div class="field"><label>${T("Endpoint host / IP")}</label><${IpPicker} ips=${ips} sel=${hostSel} setSel=${setHostSel} custom=${hostCustom} setCustom=${setHostCustom} placeholder=${T("vpn.xyz.com or 203.0.113.7")}/><div class="hint">${T("What clients dial")}</div></div>
        <div class="field"><label>${T("Listen port")}</label><input class=${wperr ? "bad" : ""} value=${port} onInput=${e => setPort(e.target.value)} placeholder="56000"/>${wperr ? html`<div class="hint err">${wperr}</div>` : html`<div class="hint">${T("DTLS listen (outside)")}</div>`}</div>
      </div>
      <div class="field"><label>${T("Forwards to")}</label><div class="ro-field" style="display:flex;align-items:center;gap:8px"><span class="mono">${iface} · 127.0.0.1:${wgPort}</span> <span class="faint">${T("— self-contained (its own userspace-WireGuard)")}</span><span class="grow"></span><button class="btn btn-mini" disabled=${blocked || awaiting} title=${T("Egress, routing & filters")} onClick=${() => pushModal(html`<${EditWdttSheet} node=${node} iface=${iface}/>`)}><${Ic} i="pencil"/> ${T("Edit interface")}</button></div></div>
      ${/* RAW-IP lives INSIDE Server parameters — it is an advanced server capability, not a first-class control.
            When it's on the accordion says so in its header, because the setting is otherwise invisible until opened. */ null}
      <${Disclosure} title=${T("Server parameters")}
        summary=${rawCur
          ? html`<span class="tg tg-raw">${T("RAW mode on")}</span><span class=${rawStale ? "tg tg-pending" : "faint"} style="margin-left:6px"
              title=${rawStale ? T("Listening on {v1}, but the app only ever dials {v2} — save to move it.", { v1: rawCur, v2: RAW_PORT }) : ""}>${rawCur}${rawStale ? " → " + RAW_PORT : ""}</span>`
          : html`<span class="faint">${T("tag|advanced")}</span>`}
        open=${srvOpen} onToggle=${() => setSrvOpen(o => !o)}>
        ${rawCapable ? html`<${Fragment}>
          <div class="lbl" style="margin:0 0 6px">${T("RAW-IP mode")}</div>
          <p class="hint" style="margin:0 0 10px">${T("Carries a peer's traffic without WireGuard — roughly 6× the throughput through the same VK relay. The server keeps its normal WireGuard listener, so peers choose per device.")}</p>
          <div class="notice warn" style="margin:0 0 12px"><${Ic} i="warn"/><span>${Trich("RAW drops WireGuard's handshake: *no forward secrecy and no replay protection*. Anyone who later learns a peer's password can read traffic they recorded earlier. Turn it on for people who need the speed and accept that.")}</span></div>
          <label class="obfctl" style="margin-bottom:10px"><${Switch} on=${rawOn} onChange=${v => setRawOn(v)}/> <span class="obfctl-lbl">${T("Accept RAW connections")}</span> <span class="tg tg-raw" style="margin-left:8px">${T("port {v1}", { v1: RAW_PORT })}</span></label>
          ${rawErr ? html`<div class="hint err" style="margin-bottom:10px">${rawErr}</div>` : null}
          ${rawOn ? html`<div class="notice" style="margin-bottom:10px"><${Ic} i="info"/><span>${Trich("The user switches connection mode to *raw* in the app — nothing else. The port isn't theirs to set: the app dials *{v1}* for every server and no link or subscription can carry another one, which is why the panel fixes it. Their link keeps working for WireGuard mode.", { v1: RAW_PORT })}</span></div>` : null}
          ${rawStale ? html`<div class="notice warn" style="margin-bottom:10px"><${Ic} i="warn"/><span>${Trich("This server still listens for RAW on *{v1}*, from before the port was fixed. The app only ever dials *{v2}*, so nobody can reach it — *Save* moves the listener.", { v1: rawCur, v2: RAW_PORT })}</span></div>` : null}
          ${(rawOn && rawHolder) ? html`<div class="notice warn" style="margin-bottom:10px"><${Ic} i="warn"/><span>${Trich("*{v1}* offers RAW on this address today. One address can only run one raw listener, so saving moves it here and turns it off there.", { v1: rawHolder })}</span></div>` : null}
        <//>` : null}
        <div class="lbl" style="margin:${rawCapable ? "18px" : "0"} 0 6px">${T("Internal WireGuard port")}</div>
        <div class="field"><input class=${wgErr ? "bad" : ""} value=${wgIn} onInput=${e => setWgIn(e.target.value)} placeholder="56001" autocomplete="off"/>
          ${wgErr ? html`<div class="hint err">${wgErr}</div>` : html`<div class="hint">${T("Where the DTLS half forwards, on loopback. No client dials it and no link carries it, so changing it only restarts the server — but it must not sit on the RAW port.")}</div>`}</div>
        <div class="lbl" style="margin:18px 0 6px">${T("Extra flags")}</div>
        <p class="hint" style="margin:0 0 12px">${T("Extra command-line flags for this {v1} server. It's self-contained — its real config lives per interface — so there's little here beyond advanced flags.", { v1: forkLabel })}</p>
        <${TurnServerFields} schema=${[]} vals=${{}} setV=${() => {}} extra=${params} setExtra=${setParams} template=${false} wdtt=${true} noHint=${true}/>
      <//>
      ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
    <//>`}
  <//>`;
}
export async function wdttRestoreIdentity(node, iface) {
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const kb = (nrec.wdtt_vault || {})[iface];
  if (!kb) return toast(T("No escrowed identity is stored for this server."), "err");
  try {
    const sealed = await wdttResealForNode(node, kb);
    const r = await api.wdttRestore({ node, iface, sealed_identity: sealed });
    if (!r.ok) return toast(srvText(r) || T("Restore failed."), "err");
    toast(T("Restoring the original server identity — the node applies it on its next sync."), "ok");
    Store.poll();
  } catch (e) { toast(e.message || T("Restore failed."), "err"); }
}
// Escape hatch when the vault can't be unlocked: abandon the escrowed identity, mint a fresh key. Type-to-confirm
// because every existing user has to re-import (their cached server key changes).
export function wdttRecreateFresh(node, iface) {
  openConfirm({ title: T("Recreate with a fresh identity?"), danger: true, requireType: iface, confirmLabel: T("Recreate fresh"),
    body: Trich("This *abandons the vaulted server identity* and generates a NEW server key for *{iface}*. Every existing user must *re-import* their link. Use this only if the Encryption Vault can't be unlocked. Type *{iface}* to confirm.", { iface }),
    onConfirm: async () => { const r = await api.wdttRecreateFresh({ node, iface });
      toast(r && r.ok ? T("Recreating with a fresh identity — users must re-import.") : (srvText(r) || "Failed."), r && r.ok ? "ok" : "err");
      await Store.poll(); } });
}
export function WdttDeleteSheet({ node, iface }) {
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false); const [msg, setMsg] = useState(null);
  const del = async () => {
    setBusy(true); setMsg({ k: "work", t: "removing…" });
    const r = await api.wdttDelete({ node, iface });
    if (!r.ok) { setBusy(false); return setMsg({ k: "err", t: srvText(r) || T("Request failed.") }); }
    // Card goes inert + "deleting" NOW. Capture the identity WITH it: the server process dies first, so by the
    // next render it is gone from snap.wdtt and the card had nothing left to render itself from — it flipped to
    // a green "wg" badge with empty rows. Same reason the optimistic CREATE card carries the entered values.
    const _w = ((Store.stats[node] || {}).wdtt || []).find(x => x && x.iface === iface) || {};
    const _c = (((Store.nodes || []).find(n => n.id === node) || {}).wdtt_cfg || {})[iface] || {};
    const _port = String(_w.listen || _c.listen || "").split(":").pop();
    Store.ifaceGone[node + "|" + iface] = { at: Date.now(), type: "wdtt",
      listen: (_w.fork || _c.fork || "wdtt") + (_port ? ":" + _port : ""), subnet: _w.wg_addr || _c.wg_addr || "" };
    closeModal(); Store.apply(); await Store.poll();
    toast(T("WDTT server removed — the node tears it down on its next sync."), "ok");
  };
  return html`<${Sheet} title=${T("Delete WDTT server")} width=${480}
    foot=${footRow({ onCancel: closeModal, disabled: busy || confirm.trim() !== iface, onAction: del, action: T("Delete"), danger: true })}>
    <div class="notice warn"><${Ic} i="warn"/><span>${Trich("This stops and removes the WDTT server *{iface}* on this node and disconnects its users. Each user's credential is a password on *this* server, so its peers go with it (a peer also deployed elsewhere keeps those deployments). Type *{iface}* to confirm.", { iface })}</span></div>
    <div class="field"><input value=${confirm} onInput=${e => setConfirm(e.target.value)} placeholder=${iface} autocomplete="off"/></div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}
export function openEditWdtt(node, iface) { openModal(html`<${EditWdttSheet} node=${node} iface=${iface}/>`); }
// WDTT interface EDIT modal — the interface modal for a WDTT server: endpoint / fork / ports (the 2 extra WDTT
// fields) PLUS the same egress picker + routing rules + Filters & abuse an ordinary interface has. Saves the
// whole instance via /api/wdtt/set (an upsert); the routing/filters ride the SAME subnet-based node datapath.
export function EditWdttSheet({ node, iface }) {
  useStore();   // re-render on each poll so live status / desired config stays current while open
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const cfg = (nrec.wdtt_cfg || {})[iface] || {};                                    // DESIRED config (node store)
  const w = ((Store.stats[node] || {}).wdtt || []).filter(Boolean).find(x => x.iface === iface) || {};   // live readback
  const wgAddr = cfg.wg_addr || w.wg_addr || "";
  const oldListen = cfg.listen || w.listen || "";
  const ips = nrec.ips || [];
  const emode = nrec.routing_mode || "kernel";   // for smart-rule validation (kernel = IP-only)
  // Take-over in flight: saving here would push a config at a server the node is still replacing.
  const adopting = (nrec.wdtt_adopting || []).includes(iface);
  const fork = cfg.fork || w.fork || "amurcanov";   // create-time choice — read-only here (no live binary/store swap)
  const forkLabel = (turnForkList().find(x => x.id === fork) || {}).label || fork;
  const [wgPort, setWgPort] = useState(String(cfg.wg_port || "56001"));   // endpoint + listen port are edited from the WDTT-proxy modal now
  const _dtls = oldListen.includes(":") ? oldListen.slice(oldListen.lastIndexOf(":") + 1) : "";
  const wgperr = portErrMsg(node, wgPort, [cfg.wg_port, w.wg_port, _dtls]);   // live collision check (this instance's own WG + DTLS ports don't count)
  const [eg, setEg] = useState(() => egressInit(cfg));
  const [blk, setBlk] = useState(() => [...(cfg.block || [])]);
  const [disc, setDisc] = useState({ routing: true, filters: false });   // Routing opens by default (only shown in Smart mode)
  const tog = k => setDisc(d => ({ ...d, [k]: !d[k] }));
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const doSave = () => {
    // Optimistic, like the interface edit sheet: flip the card to an "applying" badge + close the modal(s) NOW;
    // the save + the node's reconcile run in the background. trackIfaceOps drives applying → applied / failed.
    const key = node + "|" + iface, verb = "apply";
    Store.ifaceOp[key] = { verb, phase: "busy", started: Date.now() };
    Store.apply(); closeAllModals();
    const fail = m => { Store.ifaceOp[key] = { verb, phase: "fail", until: Date.now() + 6000, err: m }; Store.apply(); setTimeout(() => Store.apply(), 6100); };
    api.wdttSet({ node, iface, listen: oldListen, wg_port: wgPort.trim() || "56001", fork, block: blk, ...egressBody(eg) })
      .then(r => { if (!r.ok) return fail(srvText(r) || T("save failed")); Store.poll(); })   // busy → applied via trackIfaceOps
      .catch(e => fail((e && e.message) || T("save failed")));
  };
  const save = () => {
    const ee = egressError(eg, emode); if (ee) return setMsg({ k: "err", t: ee });
    if (wgPort.trim() && !/^\d+$/.test(wgPort.trim())) return setMsg({ k: "err", t: T("Internal WG port must be a number.") });
    // the internal WG port is baked into each wdtt:// link → a change re-issues it
    if (!!oldListen && (wgPort.trim() || "56001") !== String(cfg.wg_port || "56001")) {
      pushModal(html`<${ConfirmSheet} title=${T("Change the internal WG port?")} confirmLabel=${T("Apply change")} warn=${true}
        body=${T("This rewrites every user's link — the internal WG port is part of it. Existing users must re-import from their subscription page. The server key and users are kept; the server briefly reconnects.")}
        onConfirm=${doSave}/>`);
      return;
    }
    doSave();
  };
  return html`<${Sheet} title=${T("Edit WDTT interface · {v1}", { v1: iface })} width=${720}
    foot=${footRow({ onCancel: closeModal, disabled: busy || adopting || !!wgperr || !!egressError(eg, emode), title: (adopting ? T("This server is being adopted — wait for the node to finish") : wgperr || egressError(eg, emode)) || "", onAction: save, action: T("Save") })}>
    ${adopting ? html`<div class="notice"><${Ic} i="clock"/><span>${Trich("This server is being *taken over* right now — its settings are read-only until the node reports the result.")}</span></div>` : null}
    <div class="iface-intro"><div>${Trich("*WDTT* owns its own *WireGuard* interface *({iface} · {addr})* and mints each user's key on connect.", { iface, addr: wgAddr || "—" })}</div></div>
    <div class="row2">
      <div class="field"><label>${T("WDTT server instance")}</label>
        <div class="ro-field" style="display:flex;align-items:center;gap:10px"><span class="mono">${forkLabel}</span><span class="grow"></span><span class="mono">${oldListen || "—"}</span></div>
        <div class="hint">${T("Fork is set at create. Endpoint & listen port are edited from the WDTT-proxy modal.")}</div></div>
      <div class="field"><label>${T("Internal WG port")}</label><input class=${wgperr ? "bad" : ""} value=${wgPort} onInput=${e => setWgPort(e.target.value)} placeholder="56001"/>${wgperr ? html`<div class="hint err">${wgperr}</div>` : html`<div class="hint">${T("Loopback userspace-WG port (server-internal)")}</div>`}</div>
    </div>
    <${EgressPicker} node=${node} value=${eg} onChange=${setEg} noRules=${true}/>
    ${eg.mode === "smart" ? html`<${Disclosure} title=${T("Routing rules")} sumCls="route"
      summary=${(eg.rules || []).length ? Trich("*{v1}* {v2} · first match wins", { v1: (eg.rules || []).length, v2: (eg.rules || []).length === 1 ? "rule" : "rules" }) : T("no rules yet")}
      open=${disc.routing} onToggle=${() => tog("routing")}>
      <${RoutingRules} node=${node} rules=${eg.rules || []} onChange=${rs => setEg({ ...eg, rules: rs })}/>
    <//>` : null}
    <${Disclosure} title=${T("Filters & abuse")} sumCls="on"
      summary=${blk.length ? T("{v1} active", { v1: blk.length }) : html`<span class="faint">${T("val|none")}</span>`}
      open=${disc.filters} onToggle=${() => tog("filters")}>
      <${BlockTraffic} node=${node} value=${blk} onChange=${setBlk}/>
    <//>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// ── csqtt (amurcanov/csqtt) — a SELF-CONTAINED, key-owning member of the fork family like WDTT, but a raw-IP TUN
//    datapath (no WireGuard). Its setup/card/manage/edit mirror the WDTT ones (dedicated, kind-dispatched); it is
//    simpler — no fork/wg-port/vault. Users attach directly (keyless, panel-owned csqtt_password) and get a
//    csqtt:// link (turn-artifacts.js csqttArtifact). ────────────────────────────────────────────────────────────
export const CSQTT_COLOR = "#F97316";
export function CsqttInstanceBody({ node, snap, saveRef, setBusy, setMsg, fail }) {
  const used = (() => {
    const ifaces = new Set(), subs = new Set(), ports = new Set();
    Object.entries(snap.interfaces || {}).forEach(([n, b]) => { const p = parseInt((b.meta || {}).listen_port, 10); if (p) ports.add(p); });
    (snap.turn_proxies || []).forEach(tp => { const p = parseInt(String(tp.listen || "").split(":").pop(), 10); if (p) ports.add(p); });
    (snap.wdtt || []).forEach(w => { if (!w) return; if (w.wg_addr) subs.add(String(w.wg_addr).split("/")[0].split(".").slice(0, 3).join(".")); const lp = parseInt(String(w.listen || "").split(":").pop(), 10); if (lp) ports.add(lp); });
    (snap.csqtt || []).forEach(c => { if (!c) return; if (c.iface) ifaces.add(c.iface); if (c.tun_addr) subs.add(String(c.tun_addr).split("/")[0].split(".").slice(0, 3).join(".")); const lp = parseInt(String(c.listen || "").split(":").pop(), 10); if (lp) ports.add(lp); });
    return { ifaces, subs, ports };
  })();
  const nextIface = (() => { for (let i = 0; i < 1000; i++) if (!used.ifaces.has("csqtt" + i)) return "csqtt" + i; return "csqtt0"; })();
  const nextSubnet = (() => { for (let i = 66; i < 230; i++) { const b = "10.66." + i; if (!used.subs.has(b)) return b + ".1/24"; } return "10.66.67.1/24"; })();
  const [iface, setIface] = useState(nextIface);
  const [subnet, setSubnet] = useState(nextSubnet);
  const [adv, setAdv] = useState(false);
  saveRef.current = async (lhost, lport) => {
    if (!isCsqttIface(iface.trim())) return fail(T("Interface must be csqtt0–csqtt9999."));
    if (!/^\d{1,3}(\.\d{1,3}){3}\/24$/.test(subnet.trim())) return fail(T("Subnet must be an IPv4 /24 CIDR (e.g. 10.66.67.1/24)."));
    setBusy(true); setMsg({ k: "work", t: T("creating csqtt server… (the node installs it on its next sync)") });
    const r = await api.csqttSet({ node, iface: iface.trim(), tun_addr: subnet.trim(), listen: lhost + ":" + lport, max_passwords: 500, stopped: false });
    if (!r.ok) return fail(srvText(r) || T("Request failed."));
    closeModal(); Store.apply(); await Store.poll();
    toast(T("csqtt server requested — the node installs it on its next sync. Add users from Peers."), "ok");
  };
  return html`<${Fragment}>
    <div class="field"><label>${T("Serves")}</label>
      <div class="selwrap" style="display:flex;align-items:center;justify-content:space-between;opacity:.9">
        <span>${T("Built-in raw-IP tunnel")}</span>
        <span class="mono faint">${iface} · ${subnet}</span>
      </div>
      <div class="hint">${T("csqtt owns its own raw-IP TUN interface — users attach to it directly (no forwards-to). It mints each user's address on connect; add + manage users from Peers.")}</div>
    </div>
    <${Disclosure} title=${T("Advanced — built-in interface")} open=${adv} onToggle=${() => setAdv(a => !a)}>
      <div class="field"><label>${T("col|Interface")}</label><input value=${iface} onInput=${e => setIface(e.target.value)} placeholder="csqtt1" autocomplete="off"/></div>
      <div class="field"><label>${T("Tunnel subnet")}</label><input value=${subnet} onInput=${e => setSubnet(e.target.value)} placeholder="10.66.67.1/24" autocomplete="off"/>
        <div class="hint">${T("Auto-assigned to avoid collisions with this node's other servers, interfaces, and ports. /24 only.")}</div></div>
    <//>
  <//>`;
}

export function CsqttCard({ node, c, reorder }) {
  const active = c.active === "active";
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const converting = (nrec.proc_status || "").startsWith("converting");
  const nblocked = nodeStale(node) || inProc(nrec.proc_status);
  const rid = "csqtt:" + c.iface;
  const it = reorder ? reorder.item(rid) : null;
  const _op = Store.ifaceOp[node + "|" + c.iface];
  const _opTag = opTag(node + "|" + c.iface);
  const deleting = !!Store.ifaceGone[node + "|" + c.iface];
  const tag = deleting ? html`<${StatusTag} cls="tg-del" icon="clock" label="deleting" title=${T("The node tears it down on its next sync")}/>`
    : converting ? html`<${StatusTag} cls="tg-convert" icon="clock" label="converting" title=${T("The node is converting between bare-metal and docker")}/>`
    : _opTag ? _opTag
    : active ? null
    : html`<${StatusTag} cls="tg tg-pending" icon="clock" label="starting" title=${T("Installing / starting on the node")}/>`;
  const _opBusy = _op && _op.phase === "busy";
  const cdim = deleting || converting || !active || _opBusy;
  const canOpen = !_opBusy && !nblocked && !deleting;
  return html`<div class=${"ifcard tp" + (canOpen ? " clickable" : "") + (cdim ? " down" : "") + (nblocked ? " locked" : "") + (it ? it.cls : "")} data-rid=${it ? it.rid : null} onClick=${() => { if (!canOpen) return; openModal(html`<${CsqttManageSheet} node=${node} c=${c}/>`); }}>
    <div class="ifcard-top">${reorder ? html`<span class="drag-grip" title=${T("Drag to reorder")} onClick=${e => e.stopPropagation()} ...${reorder.grip(rid)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span>` : null}
      <span class="iftype csqtt">CSQTT</span>
      <span class="ifname">${shownTitle("c|" + node + "|" + c.iface, (((nrec.csqtt_cfg || {})[c.iface] || {}).title || "").trim()) || c.iface}</span><span class="grow"></span>
      ${(() => { const conn = wdttConnRows(node, c.iface); return conn.length ? html`<${OnlPop} peer title=${T("Connected to this csqtt server")} cls="ifc-conn" rows=${conn} trigger=${cnt => html`<b class="oncount on">${cnt}</b>`}/>` : null; })()}
      ${tag}
    </div>
    <div class="ifcard-rows">
      <div class="ifrow"><span class="l">${T("CSQTT fork")}</span><span class="r">amurcanov</span></div>
      <div class="ifrow"><span class="l">${T("Listen")}</span><span class="r addr">${c.listen || "—"}</span></div>
      <div class="ifrow"><span class="l">${T("Forwards to")}</span><span class="r"><a class="tg tg-csqtt" href=${"#/node/" + encodeURIComponent(node) + "/" + encodeURIComponent(c.iface)} onClick=${e => e.stopPropagation()}>${c.iface}</a></span></div>
    </div></div>`;
}

export function CsqttManageSheet({ node, c: c0 }) {
  useStore();
  const iface = c0.iface;
  const c = ((Store.stats[node] || {}).csqtt || []).filter(Boolean).find(x => x.iface === iface) || c0;
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const cfg = (nrec.csqtt_cfg || {})[iface] || {};
  const [title, setTitle] = useState(shownTitle("c|" + node + "|" + iface, (cfg.title || "").trim()));
  const [params, setParams] = useState((cfg.params || "").trim());
  const [srvOpen, setSrvOpen] = useState(false);
  const blocked = (Store.recon.nodeStatus[node] !== "live") || inProc(nrec.proc_status);
  const notup = c.active !== "active";
  const ips = nrec.ips || [];
  const oldListen = cfg.listen || c.listen || "";
  const lhost = oldListen.includes(":") ? oldListen.slice(0, oldListen.lastIndexOf(":")) : oldListen;
  const lport = oldListen.includes(":") ? oldListen.slice(oldListen.lastIndexOf(":") + 1) : "";
  const initHost = (lhost && lhost !== "0.0.0.0") ? lhost : "";
  const [hostSel, setHostSel] = useState(initHost ? (ips.includes(initHost) ? initHost : "__custom__") : (ips[0] || "__custom__"));
  const [hostCustom, setHostCustom] = useState(initHost && !ips.includes(initHost) ? initHost : "");
  const [port, setPort] = useState(lport || "");
  const [msg, setMsg] = useState(null);
  const newListen = (ipPickerVal(hostSel, hostCustom).trim() || "0.0.0.0") + ":" + (port.trim() || "46000");
  const endpointDirty = !!oldListen && newListen !== oldListen;
  const titleDirty = title.trim() !== (cfg.title || "").trim();
  const paramsDirty = params.trim() !== (cfg.params || "").trim();
  const anyDirty = endpointDirty || titleDirty || paramsDirty;   // csqtt IS a raw-IP tunnel — no RAW toggle here
  const wperr = portErrMsg(node, port, [lport]);
  const doSave = () => {
    const key = node + "|" + iface, verb = "apply";
    Store.ifaceOp[key] = { verb, phase: "busy", started: Date.now() }; Store.apply(); closeAllModals();
    const fail = m => { Store.ifaceOp[key] = { verb, phase: "fail", until: Date.now() + 6000, err: m }; Store.apply(); setTimeout(() => Store.apply(), 6100); };
    api.csqttSet({ node, iface, listen: newListen, title: title.trim(), params: params.trim(), block: cfg.block || [], ...egressBody(egressInit(cfg)) })
      .then(r => { if (!r.ok) return fail(srvText(r) || T("save failed")); Store.poll(); })
      .catch(e => fail((e && e.message) || T("save failed")));
  };
  const save = () => {
    if (port.trim() && !/^\d+$/.test(port.trim())) return setMsg({ k: "err", t: T("Listen port must be a number.") });
    if (endpointDirty) {
      pushModal(html`<${ConfirmSheet} title=${T("Change the endpoint or port?")} confirmLabel=${T("Apply change")} warn=${true}
        body=${T("This rewrites every user's link — the endpoint and DTLS port are part of it. Existing users must re-import from their subscription page. The server key and users are kept; the server briefly reconnects.")} onConfirm=${doSave}/>`);
      return;
    }
    if (paramsDirty) { doSave(); return; }
    closeModal(); pushOptTitle("c|" + node + "|" + iface, title.trim());
    api.csqttSet({ node, iface, listen: oldListen, title: title.trim(), params: params.trim(), block: cfg.block || [], ...egressBody(egressInit(cfg)) })
      .then(r => { if (r && r.ok) { Store.poll(); toast(T("Title saved."), "ok"); } else toast(srvText(r) || T("Save failed."), "err"); });
  };
  const control = (verb, icon, label, title) => html`<button class="btn btn-ghost" style="margin-left:8px" disabled=${blocked} title=${title} onClick=${() => { startOrRestartCsqtt(node, iface, verb); closeModal(); }}><${Ic} i=${icon}/> ${label}</button>`;
  return html`<${Sheet}
    title=${html`csqtt-proxy · ${(title.trim() || iface)}${c.version ? html` <span class="sheet-ver">${c.version}</span>` : ""}`}
    width=${664}
    headExtra=${c.service ? html`<${TurnIpsHeader} node=${node} svc=${c.service}/>` : null}
    foot=${footRow({ left: html`<${Fragment}>
        <button class="btn btn-ghost danger" onClick=${() => openModal(html`<${CsqttDeleteSheet} node=${node} iface=${iface}/>`)}><${Ic} i="trash"/>${T("Delete")}</button>
        ${notup ? control("start", "play", T("Start service"), T("Bring this csqtt server up on the node"))
          : html`<${Fragment}>${control("stop", "stop", T("Stop service"), T("Take this csqtt server down (stays down until started)"))}${control("restart", "refresh", T("Restart service"), T("Bounce this csqtt server on the node"))}<//>`}
      <//>`, onCancel: closeModal, disabled: !anyDirty || !!wperr, onAction: save, action: "Save" })}>
    <${IfaceThroughput} node=${node} iface=${iface}/>
    <div class="iface-intro" style="margin-top:10px"><div>${T("Changing the endpoint or port rewrites the unit's ExecStart on the node and restarts it — every user's link is re-issued.")}</div></div>
    <div class="field"><label>${T("col|Title")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— optional")}</span></label><input value=${title} onInput=${e => setTitle(e.target.value)} placeholder=${iface} autocomplete="off"/></div>
    <div class="row2">
      <div class="field"><label>${T("Endpoint host / IP")}</label><${IpPicker} ips=${ips} sel=${hostSel} setSel=${setHostSel} custom=${hostCustom} setCustom=${setHostCustom} placeholder=${T("vpn.xyz.com or 203.0.113.7")}/><div class="hint">${T("What clients dial")}</div></div>
      <div class="field"><label>${T("Listen port")}</label><input class=${wperr ? "bad" : ""} value=${port} onInput=${e => setPort(e.target.value)} placeholder="46000"/>${wperr ? html`<div class="hint err">${wperr}</div>` : html`<div class="hint">${T("DTLS listen (outside)")}</div>`}</div>
    </div>
    <div class="field"><label>${T("Forwards to")}</label><div class="ro-field" style="display:flex;align-items:center;gap:8px"><span class="mono">${iface} · ${c.tun_addr || "raw TUN"}</span> <span class="faint">${T("— self-contained (its own raw-IP tunnel)")}</span><span class="grow"></span><button class="btn btn-mini" disabled=${blocked} title=${T("Egress, routing & filters")} onClick=${() => pushModal(html`<${EditCsqttSheet} node=${node} iface=${iface}/>`)}><${Ic} i="pencil"/> ${T("Edit interface")}</button></div></div>
    <${Disclosure} title=${T("Server parameters")} summary=${html`<span class="faint">${T("tag|advanced")}</span>`} open=${srvOpen} onToggle=${() => setSrvOpen(o => !o)}>
      <p class="hint" style="margin:0 0 12px">${T("Extra command-line flags for this csqtt server. It's self-contained — its real config lives per interface — so there's little here beyond advanced flags.")}</p>
      <${TurnServerFields} schema=${[]} vals=${{}} setV=${() => {}} extra=${params} setExtra=${setParams} template=${false} wdtt=${true} noHint=${true}/>
    <//>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

export function CsqttDeleteSheet({ node, iface }) {
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false); const [msg, setMsg] = useState(null);
  const del = async () => {
    setBusy(true); setMsg({ k: "work", t: "removing…" });
    const r = await api.csqttDelete({ node, iface });
    if (!r.ok) { setBusy(false); return setMsg({ k: "err", t: srvText(r) || T("Request failed.") }); }
    Store.ifaceGone[node + "|" + iface] = { at: Date.now(), type: "csqtt" };
    closeAllModals(); Store.apply(); await Store.poll();
    toast(T("csqtt server removed — the node tears it down on its next sync."), "ok");
  };
  return html`<${Sheet} title=${T("Delete csqtt server · {v1}", { v1: iface })} width=${520}
    foot=${footRow({ onCancel: closeModal, danger: true, disabled: busy || confirm.trim() !== iface, onAction: del, action: T("Delete server") })}>
    <div class="notice warn"><${Ic} i="shield"/><span>${Trich("This removes the *{iface}* csqtt server and *unassigns + deletes* every user on it — their credential is a password on this server, so it means nothing once the server is gone. Type *{iface}* to confirm.", { iface })}</span></div>
    <div class="field"><label>${T("Type the interface name to confirm")}</label><input value=${confirm} onInput=${e => setConfirm(e.target.value)} placeholder=${iface} autocomplete="off"/></div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

export function openEditCsqtt(node, iface) { openModal(html`<${EditCsqttSheet} node=${node} iface=${iface}/>`); }
export function EditCsqttSheet({ node, iface }) {
  useStore();
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const cfg = (nrec.csqtt_cfg || {})[iface] || {};
  const c = ((Store.stats[node] || {}).csqtt || []).filter(Boolean).find(x => x.iface === iface) || {};
  const tunAddr = cfg.tun_addr || c.tun_addr || "";
  const oldListen = cfg.listen || c.listen || "";
  const emode = nrec.routing_mode || "kernel";
  const [eg, setEg] = useState(() => egressInit(cfg));
  const [blk, setBlk] = useState(() => [...(cfg.block || [])]);
  const [disc, setDisc] = useState({ routing: true, filters: false });
  const tog = k => setDisc(d => ({ ...d, [k]: !d[k] }));
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const doSave = () => {
    const key = node + "|" + iface, verb = "apply";
    Store.ifaceOp[key] = { verb, phase: "busy", started: Date.now() }; Store.apply(); closeAllModals();
    const fail = m => { Store.ifaceOp[key] = { verb, phase: "fail", until: Date.now() + 6000, err: m }; Store.apply(); setTimeout(() => Store.apply(), 6100); };
    api.csqttSet({ node, iface, listen: oldListen, block: blk, ...egressBody(eg) })
      .then(r => { if (!r.ok) return fail(srvText(r) || T("save failed")); Store.poll(); })
      .catch(e => fail((e && e.message) || T("save failed")));
  };
  const save = () => { const ee = egressError(eg, emode); if (ee) return setMsg({ k: "err", t: ee }); doSave(); };
  return html`<${Sheet} title=${T("Edit csqtt interface · {v1}", { v1: iface })} width=${720}
    foot=${footRow({ onCancel: closeModal, disabled: busy || !!egressError(eg, emode), title: egressError(eg, emode) || "", onAction: save, action: T("Save") })}>
    <div class="iface-intro"><div>${Trich("*csqtt* owns its own raw-IP tunnel *({iface} · {addr})* and mints each user's address on connect.", { iface, addr: tunAddr || "—" })}</div></div>
    <${EgressPicker} node=${node} value=${eg} onChange=${setEg} noRules=${true}/>
    ${eg.mode === "smart" ? html`<${Disclosure} title=${T("Routing rules")} sumCls="route"
      summary=${(eg.rules || []).length ? Trich("*{v1}* {v2} · first match wins", { v1: (eg.rules || []).length, v2: (eg.rules || []).length === 1 ? "rule" : "rules" }) : T("no rules yet")}
      open=${disc.routing} onToggle=${() => tog("routing")}>
      <${RoutingRules} node=${node} rules=${eg.rules || []} onChange=${rs => setEg({ ...eg, rules: rs })}/>
    <//>` : null}
    <${Disclosure} title=${T("Filters & abuse")} sumCls="on"
      summary=${blk.length ? T("{v1} active", { v1: blk.length }) : html`<span class="faint">${T("val|none")}</span>`}
      open=${disc.filters} onToggle=${() => tog("filters")}>
      <${BlockTraffic} node=${node} value=${blk} onChange=${setBlk}/>
    <//>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// A WDTT fork chip: the fork's own colour, with the WDTT colour as the fallback until applyThemeColors has
// injected the tunable one. The style string, the `turnColor(fork) || WDTT_COLOR` fallback and the label lookup
// were written out at four separate sites, which is how they drifted (some showed the raw id, some the label).
export function ForkTag({ fork, suffix, title }) {
  if (!fork) return null;
  const col = turnColor(fork) || WDTT_COLOR;
  const fk = turnForkList().find(x => x.id === fork) || {};
  const label = forkLabel(fork);
  // Both amurcanov forks now read "amurcanov"; the kind-specific title (and the fork colour) tell them apart.
  const defTitle = fk.kind === "csqtt" ? T("CSQTT fork: {v1}", { v1: label }) : T("WDTT fork: {v1}", { v1: label });
  return html`<span class="tg" style=${"color:" + col + ";background:color-mix(in srgb," + col + " 16%,transparent)"}
    title=${title || defTitle}>${label}${suffix || ""}</span>`;
}