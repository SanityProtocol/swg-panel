/* iface.js — the interface page: one screen per (node, interface), and the sheets that manage it.
 *
 * LAYER 9 (see docs/APP-JS-SPLIT-PLAN.md). Near the top: it renders turn cards, peer grids, routing and
 * blocking policy, and opens the CRUD sheets.
 *
 * IfaceDetail is a DISPATCH, and that is the part worth preserving. It routes on what the interface
 * actually is — a WDTT server, an adoption candidate, a dormant one, or a plain wg/awg interface — and
 * each kind gets its own detail component. It keys off CONFIG PRESENCE rather than the interface name,
 * which is why it will survive the TUN-only WDTT: a fourth kind is a fourth branch here plus a kind in
 * model.js, not a rename hunt. See docs/APP-JS-SPLIT-PLAN.md §5.
 */

import { T, Trich, Tsplit, plural, srvText } from "./i18n.js";
import { esc, tkey, seen, dur, ago, fmtBytes, ipOf, portOf, ipPickerVal, isWdttIface, isCsqttIface, V } from "./util.js";
import { Store, api, bus, useStore } from "./store.js";
import { go } from "./router.js";
import { pickThemed, toThemed, IFACE_COLOR_DEFAULTS } from "./theme.js";
import {
  kindOf, iTypeOf, targetType, nodeStale, ifaceNotUp, wdttOn, ghostIface, ghostPeers, turnProxiesFor,
  suggestIface, suggestSubnet, suggestPort, portHolder, portErrMsg, subnetFleetConflict, subnetServerAddr,
  cidrNet, nextWdttName, nextCsqttName, ifaceIsAwg,
} from "./model.js";
import { turnFork, turnColor, turnForkList, forkSupportsAwg } from "./turn-catalog.js";
import {
  Ic, ICON, Tag, Panel, Badge, StatusTag, CmdErr, Sheet, footRow, secTitle, SearchBox, Switch, Dropdown,
  Disclosure, autoGrow, IpPicker, NodeIpPick, Popover, Portal, toast, copy, mutate, openModal, pushModal,
  closeModal, closeAllModals, openConfirm, ConfirmSheet, opTag, procTag, inProc, statusLabel, LogBody,
  useReorder, GRIP_SVG, orderById, trackIfaceOps, startOrRestartWdtt, ifaceReady, ifaceWasBusy, RowError,
  goSettings, rowSingle, rowDouble, rowNoSelect, ifopBusy, ifopDone, ifopFail, STATUS_RANK,
  adoptOrphanPatch, dlul, rateCell, xferCell,
} from "./ui.js";
import { RangedHistory, IfaceThroughput } from "./charts.js";
import { AWG_ORDER, SubAutoNote, ensureVaultUnlocked, subSKCached } from "./crypto.js";
import { EgressPicker, egressInit, egressError, egressBody, ifTrafficBadge, BlockTraffic, RoutingRules,
         SMART_CAT_LABEL, defaultBlockFor, loadBlockCatalog } from "./routing.js";
import { orphCount, OnlinePeersTag, peersView, searchMatch } from "./views.js";
import { confirmRestoreInterface, confirmRestoreAllInterfaces, openRecreateRekey, fmtDate } from "./peer-actions.js";
import { TurnProxiesBlock, turnEnabled, WDTT_COLOR, wdttRestoreIdentity, wdttRecreateFresh,
         WdttDeleteSheet, openEditWdtt, ForkTag, shownTitle, enabledTurnForks } from "./turn.js";
import { PeerGrid, NodeRail } from "./grids.js";
import { openCreatePeer } from "./sheets-crud.js";
import { h, Fragment } from "preact";
import { useState, useEffect, useRef, useMemo } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// ═════════════════════════ SCREEN: ADOPTION CANDIDATE ═════════════════════════
// A wg/awg interface the node reported but the panel doesn't manage (Approach B). Stripped detail: facts +
// Adopt / Ignore only. wdtt_hint ones steer to WDTT (coming soon) / Ignore — never wg/awg-adopt (would break the server).
// Every interface the operator has dismissed, fleet-wide. Ignoring one is a deliberate "the panel doesn't manage
// this" decision, so it does NOT belong on the node's interface grid dimmed at the bottom — that put a permanent
// piece of clutter on the screen the operator looks at most, for interfaces they had already dealt with. This is
// the single place they exist: a plain list, one action, and it disappears again the moment the node stops
// reporting the interface. Adopting is the only way back — that IS the un-ignore.
/* Adopt-sheet intro. The node NAME is a value the code supplies, so it rides in as a marker; the rest of
   the emphasis is the translator's, so it travels as *…* (see Trich in js/i18n.js). */
/* The docker step names a compose KEY (swg-node → ports:) that must stay verbatim and monospace. */
/* "This interface is *down* … The node reported: <code>reason</code>. Use *Start interface* — …" The reason
   is a code-supplied value in a <code>, and the rest of the emphasis is the translator's. Both, so both. */
function ifaceDownNote(reason) {
  const [a, b] = Tsplit("This interface is *down* on the node — its config below is read from the *.conf* (not live). The node reported: {reason}. Use *Start interface* — if the bring-up fails, the exact reason (port clash, a left-over kernel interface of the same name, an unsupported AmneziaWG parameter, …) shows here.", "reason");
  const rich = t => t.split("*").map((p, i) => (i % 2 ? html`<b>${p}</b>` : p));
  return html`<${Fragment}>${rich(a)}<code>${reason}</code>${rich(b)}<//>`;
}
/* The middle clause differs with whether the key survives, so it arrives as a translated VALUE. */
function ifaceGoneNote(iface, nodeName, verdict) {
  const [a, b] = Tsplit("Interface *{iface}* is gone from {node} — the panel no longer sees it, so this view is *read-only* and shows the panel's saved config. {verdict} The only action here is *Restore interface*.", "verdict", { iface, node: nodeName });
  const rich = t => t.split("*").map((p, i) => (i % 2 ? html`<b>${p}</b>` : p));
  return html`<${Fragment}>${rich(a)}${verdict}${rich(b)}<//>`;
}

function restoreFailed(err) {
  const [a, b] = Tsplit("*Restore failed.* The node couldn't revert to its backed-up key: {err} — try again, or adopt the new key instead.", "err");
  const rich = t => t.split("*").map((p, i) => (i % 2 ? html`<b style="color:var(--dangling)">${p}</b>` : p));
  return html`<${Fragment}>${rich(a)}<span class="mono" style="color:var(--dangling)">${err}</span>${rich(b)}<//>`;
}

function subnetTaken(iface, node) {
  const one = T("Subnet already used by {iface} on {node} — interface subnets must be unique across the fleet.");
  const [a, r1] = [one.split("{iface}")[0], one.split("{iface}").slice(1).join("{iface}")];
  const [b, c] = [r1.split("{node}")[0], r1.split("{node}").slice(1).join("{node}")];
  return html`<${Fragment}>${a}<b>${iface}</b>${b}<b>${node}</b>${c}<//>`;
}

function dockerPortsStep() {
  const [a, b] = Tsplit("1. Add under {key} in the node's docker-compose.yml", "key");
  return html`<${Fragment}>${a}<span class="mono">swg-node → ports:</span>${b}<//>`;
}

function adoptIntro(nodeName) {
  const [a, b] = Tsplit("Start managing this interface on {node}. The panel doesn't know its type — {choose}", "node");
  const [c, d] = [b.split("{choose}")[0], b.split("{choose}").slice(1).join("{choose}")];
  return html`<${Fragment}>${a}<b>${nodeName}</b>${c}<b>${T("choose it below")}</b>${d}<//>`;
}
function adoptPreselect(type, why) {
  const [a, b] = Tsplit(". Preselected {type} because {why}", "type", { why });
  return html`<${Fragment}>${a}<b>${type}</b>${b}<//>`;
}

export function IgnoredIfacesCard() {
  useStore();
  const rows = [];
  for (const n of (Store.nodes || [])) {
    for (const cd of (n.ignored_candidates || []))
      // Store.ifaceIsSystem, NOT isSysName: that one is a local of the node screen, and calling it from here
      // threw a ReferenceError on every render of this section — which is exactly why this card appeared to do
      // nothing no matter what was ignored. (Same trap the turn-button comment above warns about.)
      if (cd && cd.name && !Store.ifaceIsSystem(n.id, cd.name) && !Store.ifaceMeta(n.id, cd.name))
        rows.push({ n, id: cd.name, name: cd.name,
                    info: (cd.wdtt_hint ? "WDTT" : (cd.address || "—")) + (cd.listen_port ? " · :" + cd.listen_port : ""),
                    adopt: () => openModal(html`<${AdoptIfaceSheet} node=${n.id} iface=${cd.name} cand=${cd} nrec=${n}/>`) });
    // A dismissed DORMANT WDTT install belongs here too — it is the same decision about the same kind of thing,
    // and it is addressed by its config dir because a stopped server has no interface name to be listed under.
    for (const d of (n.ignored_dormant || []))
      if (d && d.config_dir)
        rows.push({ n, id: d.config_dir, name: (d.config_dir.split("/").filter(Boolean).pop() || "wdtt"),
                    info: T("WDTT · not running") + (d.listen_port ? " · :" + d.listen_port : ""),
                    adopt: () => openModal(html`<${AdoptDormantWdttSheet} node=${n.id} d=${d} nrec=${n}/>`) });
  }
  if (!rows.length) return null;
  return html`<div class="card">
    <div class="seclabel" style="margin-top:0">${T("Ignored interfaces")}</div>
    <p class="hint" style="margin:0 0 12px">${Trich("Interfaces found on your nodes that you told the panel to leave alone. They keep running exactly as they are — nothing here is managed, and nothing is shown on the node's page. *Adopt* one to start managing it.")}</p>
    <div class="ignlist">${rows.map(r => html`<div class="ignrow" key=${r.n.id + "/" + r.id}>
      <a class="ignrow-n" href=${"#/node/" + encodeURIComponent(r.n.id) + "/" + encodeURIComponent(r.id)} title=${r.id}>${r.name}</a>
      <span class="ignrow-node">on ${r.n.name || r.n.id}</span>
      <span class="grow"></span>
      <span class="ignrow-f">${r.info}</span>
      <button class="iconbtn" title=${T("Adopt {v1}", { v1: T("{v1} — start managing it from the panel", { v1: r.name }) })}
        onClick=${r.adopt}><${Ic} i="plus"/></button>
    </div>`)}</div>
  </div>`;
}
export function CandidateIfaceDetail({ node, iface, cand, nrec, ignored, dorm }) {
  useStore();
  const dname = nrec.name || node;
  const wd = !!cand.wdtt_hint;
  const title = dorm ? cand.name : iface;   // a dormant install is addressed by its config dir; show its folder
  const ip0 = (cand.address || "").split("/")[0];
  // Optimistic: the tag flips to "ignoring" on the click and we leave for the node page immediately, so the
  // decision is visible where its result lands (the card) instead of the page sitting still through a round-trip
  // and then vanishing. The request runs underneath; a failure puts the reason back on the card.
  const panelOp = (verb, call, okMsg, leave) => {
    const key = node + "|" + iface;
    Store.ifaceOp[key] = { verb, phase: "busy", started: Date.now() }; Store.apply();
    if (leave) location.hash = "#/node/" + encodeURIComponent(node);
    (async () => {
      let r; try { r = await call(); } catch (e) { r = { ok: false, error: String((e && e.message) || e) }; }
      if (!r || !r.ok) {
        Store.ifaceOp[key] = { verb, phase: "fail", until: Date.now() + 10000, err: srvText(r) || T("request failed") };
        Store.apply(); return toast(srvText(r) || T("Failed"), "err");
      }
      await Store.poll();
      delete Store.ifaceOp[key]; Store.apply();   // the card has moved on its own — no "done" flash to leave behind
      toast(okMsg, "ok");
    })();
  };
  const doIgnore   = () => panelOp("ignore",   () => api.ifaceIgnore({ node, iface }),   T("Interface ignored — listed in Settings → Interfaces."), true);
  const doUnignore = () => panelOp("unignore", () => api.ifaceUnignore({ node, iface }), T("Interface un-ignored — back as an adoption candidate."), false);
  // Never disable Adopt: the sheet lets the operator pick a different type, and for WDTT it explains exactly why
  // an identity-less server can't be taken over. A blocked action that says why beats a dead control.
  // Same shape as a managed interface's page — head, "Interface details", "Peers on this interface" — so a
  // candidate reads as the same kind of object, just not managed yet. Only those two sections: throughput,
  // turn-proxies and peer management all describe things the panel doesn't run for it.
  return html`<div class="screen">
    <${NodeRail} active=${node}/>
    <div class="crumb"><a href="#/nodes">${T("col|Nodes")}</a><span class="sep">/</span><a href=${"#/node/" + encodeURIComponent(node)}>${dname}</a><span class="sep">/</span><b>${iface}</b></div>
    <div class="detail-head">
      <div class="title"><h1>${title}</h1><span class=${"iftype " + (wd ? "wdtt" : (cand.type_hint === "awg" ? "awg" : "orph"))}>${wd ? "wdtt" : cand.type_hint === "awg" ? "awg?" : "wg?"}</span>
        ${dorm ? html`<${ForkTag} fork=${dorm.fork || "amurcanov"}/><span class="nstat stopped" title=${T("Installed on disk, nothing running")}><${Ic} i="stop"/> ${T("not running")}</span>` : null}
        <span class=${"tg " + (ignored ? "tg-ign" : "tg-cand")} title=${ignored ? T("Dismissed — the panel isn't managing it") : T("On the node, not managed by the panel")}><${Ic} i="warn"/>${ignored ? "ignored" : "orphan"}</span></div>
      <div class="grow"></div>
    </div>
    <div class="notice warn"><${Ic} i="warn"/><span>${Store.ifaceGone[node + "|" + iface]
      ? Trich("This interface is being *deleted* — the node tears it down on its next sync. It still reports the device, which is the only reason this page is showing.")
      : ignored
      ? Trich("This interface is *ignored* — the panel isn't managing it and it's hidden from the node's page. It's listed in *Settings → Interfaces*. *Un-ignore* to bring it back as a candidate, or *Adopt* to start managing it now.")
      : dorm
      ? html`${Trich("A WDTT server is *installed here but not running*. It owns its own tunnel device, so while it is stopped there is no interface, no socket and no process — this directory is its only trace. *Adopt* takes it over and starts it, keeping its server key and users, so existing clients keep working; *Ignore* leaves it alone.")}
          ${!dorm.listen_port ? html`<div style="margin-top:8px">${Trich("*Its ports couldn't be identified*, so adoption will offer defaults — replace them with the ports this server was actually listening on. Clients dial the port written into the config they already hold, so adopting on the wrong one leaves every existing user unable to connect until you re-issue and re-distribute their links.")}</div>` : null}`
      : wd
      ? Trich("This is a *WDTT* interface — a userspace tunnel owned by its own server. *Adopt* takes it over keeping its identity and passwords, so existing clients keep working; *Ignore* leaves it alone.")
      : Trich("This interface is on the node but the panel doesn't manage it, so its type isn't established yet — *you choose it while adopting*. *Adopt* to start managing it (its existing peers are kept), or *Ignore* to dismiss it.")}</span></div>

    <${Panel} icon="key" title=${T("Interface details")} tone="orphan"
          actions=${Store.ifaceGone[node + "|" + iface]
            // A teardown in flight lands HERE for a WDTT server: the panel drops its record at once, so this
            // page (the candidate/orphan view) is what the router picks while the node still reports the
            // device. Offering Adopt on the server being deleted is the detail-page half of the orphan flicker.
            ? html`<${StatusTag} cls="tg-del" icon="clock" label="deleting" title=${T("The node tears it down on its next sync")}/>`
            : Store.ifaceNew[node + "|" + iface]
            // Adopt already submitted, node has not reported it yet. Offering the buttons again invites a
            // SECOND onboard for the same interface; show what is happening instead.
            ? html`<${StatusTag} cls="tg-busy" icon="clock" label="onboarding" title=${T("The node takes it over on its next sync")}/>`
            : html`<${Fragment}>
          ${ignored
            ? html`<button class="btn btn-mini" onClick=${doUnignore}>${T("Un-ignore")}</button>`
            : html`<button class="btn btn-mini" onClick=${doIgnore}>${T("Ignore")}</button>`}
          <button class="btn btn-mini btn-primary"
            title=${T("Start managing this interface from the panel")}
            onClick=${() => openModal(dorm
              ? html`<${AdoptDormantWdttSheet} node=${node} d=${dorm} nrec=${nrec}/>`
              : html`<${AdoptIfaceSheet} node=${node} iface=${iface} cand=${cand} nrec=${nrec}/>`)}>${T("Adopt")}</button>
        <//>`}>
      <div class="iface-grid">
        <div class="ig-item"><span class="ig-l">${T("Type")}</span><span class="ig-v">${wd
          ? html`WDTT${(cand.wdtt && cand.wdtt.fork) ? " · " + cand.wdtt.fork : ""}`
          : cand.type_why
          ? html`looks like ${(cand.type_hint || "wg").toUpperCase()}`
          : html`<span class="faint">${T("chosen when you adopt")}</span>`}</span></div>
        ${dorm
          // A stopped install has no endpoint, address or datapath to report — those are properties of a RUNNING
          // server. What it does have is on disk, and that is what decides whether it can be taken over.
          ? html`<${Fragment}>
              <div class="ig-item"><span class="ig-l">${T("Found at")}</span><span class="ig-v">${dorm.config_dir}</span></div>
              <div class="ig-item"><span class="ig-l">${T("Ports")}</span><span class="ig-v">${dorm.listen_port
                ? html`${dorm.listen_port}${dorm.wg_port ? " · " + dorm.wg_port : ""}`
                : html`<span class="faint">${T("set on adopt")}</span>`}</span></div>
              <div class="ig-item"><span class="ig-l">${T("Server identity")}</span><span class="ig-v"><span class="mi-ok">${T("tag|present")}</span></span></div>
            <//>`
          : html`<${Fragment}>
              <div class="ig-item"><span class="ig-l">${T("col|Endpoint")}</span><span class="ig-v">${ip0}${cand.listen_port ? ":" + cand.listen_port : ""}</span></div>
              <div class="ig-item"><span class="ig-l">${T("Server address")}</span><span class="ig-v">${cand.address || "—"}</span></div>
              <div class="ig-item"><span class="ig-l">${T("Found at")}</span><span class="ig-v">${cand.conf || ((cand.wdtt || {}).config_dir) || html`<span class="faint">—</span>`}</span></div>
            <//>`}
      </div>
    <//>

    ${wd && ((cand.wdtt || {}).users || []).length ? html`<${Panel} icon="users" title=${T("Users on this server")} count=${((cand.wdtt || {}).users || []).length} pad=${false}>
      <table><thead><tr><th>${T("col|User")}</th><th>${T("col|Address")}</th><th>${T("LAST SEEN")}</th><th>${T("EXPIRES")}</th><th>VK</th><th class="num">${T("TRANSFER")}</th></tr></thead>
        <tbody>${((cand.wdtt || {}).users || []).map((u, i) => html`<tr key=${"wu" + i}>
          <td>${u.label || html`<span class="faint">${T("Peer {n}", { n: i + 1 })}</span>`}${u.disabled ? html` <span class="tg tg-ign">${T("tag|disabled")}</span>` : null}</td>
          <td class="addr">${u.ip || html`<span class="faint">—</span>`}</td>
          <td>${u.last_seen ? ago(u.last_seen) : u.bound ? html`<span class="faint">${T("connected before")}</span>` : html`<span class="faint">${T("never connected")}</span>`}</td>
          <td>${u.expires_at ? html`<span class=${u.expires_at * 1000 < Date.now() ? "mi-bad" : ""}>${fmtDate(u.expires_at)}</span>` : html`<span class="faint">${T("never")}</span>`}</td>
          <td>${u.vk ? html`<${Ic} i="check"/>` : html`<span class="faint">—</span>`}</td>
          <td class="num">${(u.down_bytes || u.up_bytes) ? html`↓${fmtBytes(u.down_bytes || 0)} ↑${fmtBytes(u.up_bytes || 0)}` : html`<span class="faint">—</span>`}</td>
        </tr>`)}</tbody></table>
    <//>` : null}

    ${wd && ((cand.wdtt || {}).users || []).length ? null : html`<${Panel} icon="users" title=${T("Peers on this interface")} count=${cand.peers || 0} pad=${false}>
      ${(cand.peer_list || []).length
        ? html`<table><thead><tr><th>${T("col|Address")}</th><th>${T("PUBLIC KEY")}</th><th>${T("col|Endpoint")}</th><th>${T("LAST HANDSHAKE")}</th><th class="num">${T("TRANSFER")}</th></tr></thead>
            <tbody>${cand.peer_list.map(p => html`<tr key=${p.public_key}>
              <td class="addr">${p.allowed_ips || "—"}</td>
              <td class="mono faint" title=${p.public_key}>${String(p.public_key || "").slice(0, 16)}…</td>
              <td class="addr">${p.endpoint || html`<span class="faint">${T("never connected")}</span>`}</td>
              <td>${p.last_handshake ? ago(p.last_handshake) : html`<span class="faint">${T("never")}</span>`}</td>
              <td class="num">${(p.rx_bytes || p.tx_bytes) ? html`↓${fmtBytes(p.rx_bytes || 0)} ↑${fmtBytes(p.tx_bytes || 0)}` : html`<span class="faint">—</span>`}</td>
            </tr>`)}</tbody></table>
            ${cand.peers > cand.peer_list.length ? html`<div class="hint" style="padding:8px 14px">${T("Showing {n} of {total} — the rest come across on adopt.", { n: cand.peer_list.length, total: cand.peers })}</div>` : null}`
        : html`<div class="empty">${cand.peers
            ? Trich("*{v1} peer{v2} on this interface*The node couldn't read their details — they still come across when you adopt.", { v1: cand.peers, v2: cand.peers === 1 ? "" : "s" })
            : Trich("*{v1}*Nothing is configured on this interface yet. Adopt it to add peers from the panel.", { v1: T("No peers here") })}</div>`}
    <//>`}
  </div>`;
}
// The adopt modal: confirm/override the type (wg/awg → shows/hides AWG params), optionally tweak endpoint/port, then
// adopt. Subnet is fixed (like Edit). Onboard adds it to the managed set (peers kept); edits go via the normal update
// path afterwards. Existing-peer warning when the port/endpoint would change.
// Adopting a DORMANT install: the identity and password store are on disk, but the runtime parameters only ever
// existed in the process that isn't running — so the operator supplies them and the panel STARTS the server with
// its original key. (Telling them to start it by hand would be odd advice from the one thing that can do it.)
export function AdoptDormantWdttSheet({ node, d, nrec }) {
  useStore();
  const forks = enabledTurnForks().filter(f => f.kind === "wdtt");
  const [fork, setFork] = useState(d.fork || (forks[0] || {}).id || "amurcanov");
  const [iface, setIface] = useState(nextWdttName(node));
  // Ports the node managed to recover (the unit's ExecStart, the fork's own store) are used as-is, so an
  // adopted server comes back on the SAME ports its existing clients already dial.
  // When NOTHING could be recovered, offer the WDTT DEFAULTS rather than the next free pair: this server was
  // almost certainly on them, since every unpatched build compiles 56000/56001 in. That is the opposite of the
  // CREATE form, which deliberately avoids the defaults — there a collision with an unmanaged server is the
  // risk; here matching what its clients already dial is the whole point. If they are genuinely taken, the
  // usual port validation says so and the operator picks.
  const [host, setHost] = useState("");
  const [dtls, setDtls] = useState(String(d.listen_port || WDTT_DEFAULT_DTLS));
  const [wgPort, setWgPort] = useState(String(d.wg_port || WDTT_DEFAULT_WG));
  const [subnet, setSubnet] = useState(suggestSubnet(node));
  const [busy, setBusy] = useState(false);
  // One error for two fields put the internal-WG conflict under the DTLS box, so changing the port it named
  // could never clear it. Validate each field on its own and show each message where it belongs.
  // portErrMsg's second argument is a SKIP list, so passing dtls there exempts the very collision we care about
  // — every other WDTT form checks the two against each other explicitly first. And a blank port is deliberately
  // not portErrMsg's business, so without a required-check Adopt stayed enabled and posted "host:".
  const dtlsErr = !dtls.trim() ? T("The DTLS port is required.") : portErrMsg(node, dtls, []);
  const wgErr = !wgPort.trim() ? T("The internal WG port is required.")
    : (Number(wgPort) === Number(dtls)) ? T("The DTLS port and internal WG port must differ.")
    : portErrMsg(node, wgPort, [Number(dtls) || 0]);
  const iperr = dtlsErr || wgErr;
  const nameErr = /^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$/.test(iface.trim()) ? "" : "Letters, digits, _ and -, up to 15 characters.";
  const doAdopt = async () => {
    setBusy(true);
    const r = await api.wdttAdopt({ node, iface: iface.trim(), fork, adopt_config_dir: d.config_dir,
                                    // .0/24 is the NETWORK — the server wants .1/24, same as the create path
                                    wg_addr: subnetServerAddr(subnet.trim()),
                                    listen: (host.trim() || "") + ":" + dtls.trim(),
                                    wg_port: wgPort.trim() });
    if (!r || !r.ok) { setBusy(false); return toast(srvText(r) || T("Adopt failed"), "err"); }
    closeAllModals(); await Store.poll();
    toast(T("Adopting — the node starts this server with its existing key on the next sync."), "ok");
    location.hash = "#/node/" + encodeURIComponent(node);
  };
  return html`<${Sheet} title=${T("Adopt WDTT install · {v1}", { v1: d.config_dir })} width=${640}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>${T("Cancel")}</button><button class="btn btn-primary" disabled=${busy || !!iperr || !!nameErr || !forks.length} title=${nameErr || iperr || (forks.length ? "" : T("No WDTT forks are enabled in Settings → Turn proxies"))} onClick=${doAdopt}>${T("Adopt")}</button></>`}>
    <div class="notice ok"><${Ic} i="check"/><span>${Trich("Its *server key and passwords are kept* — the panel installs our build over this config directory and starts it, so any client that already has a config keeps working.")}</span></div>
    <div class="iface-grid" style="margin:0 0 16px">
      <div class="ig-item"><span class="ig-l">${T("Found at")}</span><span class="ig-v">${d.config_dir}</span></div>
      <div class="ig-item"><span class="ig-l">${T("Password store")}</span><span class="ig-v">${d.store || "—"}</span></div>
      <div class="ig-item"><span class="ig-l">${T("Server identity")}</span><span class="ig-v"><span class="mi-ok">${T("tag|present")}</span></span></div>
      <div class="ig-item"><span class="ig-l">${T("Users")}</span><span class="ig-v">${(d.users || []).length || html`<span class="faint">${T("none found")}</span>`}</span></div>
    </div>
    ${(d.users || []).length ? html`<div class="hint" style="margin:-6px 0 14px">${Trich("Its *{count}* come across on adopt — open the install from its card to see them.", { count: plural((d.users || []).length, "user") })}</div>` : null}
    <div class="hint" style="margin:-6px 0 14px">${d.listen_port
      ? Trich("Ports recovered from its password store — its clients already dial these. The *subnet* is never written to disk, so set that below.")
      : T("Not running, so its ports and subnet can't be read from the server — set them here.")}</div>
    <div class="row2">
      <div class="field"><label>${T("Server fork")}</label><select value=${fork} onChange=${e => setFork(e.target.value)}>${forks.map(f => html`<option value=${f.id}>${f.label}</option>`)}</select><div class="hint">${d.fork ? html`Detected <b>${d.fork}</b> from its files` : T("Pick the fork this install is")}</div></div>
      <div class="field"><label>${T("Interface name")}</label><input class=${nameErr ? "bad" : ""} value=${iface} onInput=${e => setIface(e.target.value)} placeholder="wdtt1"/>${nameErr ? html`<div class="hint err">${nameErr}</div>` : null}</div>
    </div>
    <div class="row2">
      <div class="field"><label>${T("Endpoint host / IP")}</label><${NodeIpPick} ips=${nrec.ips || []} value=${host} onChange=${setHost} auto=${T("Auto (node's detected address)")} customPlaceholder="IP or hostname"/><div class="hint">${T("What clients dial")}</div></div>
      <div class="field"><label>${T("Tunnel subnet (CIDR)")}</label><input value=${subnet} onInput=${e => setSubnet(e.target.value)} placeholder="10.66.0.1/24"/></div>
    </div>
    <div class="row2">
      <div class="field"><label>${T("Listen port (DTLS)")}</label><input class=${dtlsErr ? "bad" : ""} value=${dtls} onInput=${e => setDtls(e.target.value)}/>${dtlsErr ? html`<div class="hint err">${dtlsErr}</div>` : html`<div class="hint">${T("What clients dial")}</div>`}</div>
      <div class="field"><label>${T("Internal WG port")}</label><input class=${wgErr ? "bad" : ""} value=${wgPort} onInput=${e => setWgPort(e.target.value)}/>${wgErr ? html`<div class="hint err">${wgErr}</div>` : html`<div class="hint">${T("The server's own tunnel port")}</div>`}</div>
    </div>
  <//>`;
}
// First free wdtt<N> name on this node — a dormant install has no interface, so we pick the name.
// Upstream WDTT compiles these in and registers no flag to change them (verified against ildarmaga and
// amurcanov builds), so they are what a foreign server is listening on unless something says otherwise.
export const WDTT_DEFAULT_DTLS = 56000, WDTT_DEFAULT_WG = 56001;
// ONE adopt flow for every interface type. The backends differ — wg/awg is "start managing this conf"
// (ifaceOnboard, add-only, keys untouched), WDTT is a seeded create that reuses the foreign server's identity —
// but to the operator it is a single act: adopt this interface, as this type. So the type pills stay put and
// only the type-specific fields swap underneath; dispatch happens at Adopt, not by swapping the whole sheet.
export function AdoptIfaceSheet({ node, iface, cand, nrec }) {
  useStore();
  const w = cand.wdtt || {};
  const wd = !!cand.wdtt_hint;                                  // the node positively identified a WDTT server here
  const forks = enabledTurnForks().filter(f => f.kind === "wdtt");
  // Preselect from the node's EVIDENCE (live obfuscation params / a WDTT server process), never from which tool
  // happened to answer a dump — that lies on a box where the amneziawg module backs plain WireGuard too.
  const [type, setType] = useState(cand.type_hint === "wdtt" ? "wdtt" : cand.type_hint === "awg" ? "awg" : "wg");
  const [fork, setFork] = useState(w.fork || (forks[0] || {}).id || "amurcanov");
  const [host, setHost] = useState("");
  // Prefilled from what the node found — the DTLS port for WDTT (what clients dial), the wg listen port otherwise.
  const wdttDtls = String((w.listen || "").split(":").pop() || "");
  const [port, setPort] = useState(String(cand.listen_port || ""));
  const [dtls, setDtls] = useState(wdttDtls);
  const [wgPort, setWgPort] = useState(String(w.wg_port || ""));
  const iperr = portErrMsg(node, type === "wdtt" ? dtls : port, [cand.listen_port, Number(wdttDtls) || 0]);
  // the internal WG port was never validated here — a clash was accepted and surfaced only when the node failed
  const wgErr = type !== "wdtt" ? ""
    : (Number(wgPort) === Number(dtls)) ? T("The DTLS port and internal WG port must differ.")
    : portErrMsg(node, wgPort, [cand.listen_port, Number(wdttDtls) || 0, Number(dtls) || 0]);
  const [awg, setAwg] = useState({});
  const setAwgK = (k, v) => setAwg(a => ({ ...a, [k]: v }));
  // Collapsed by default: adoption KEEPS the interface's existing parameters, so these 16 fields are an override
  // nobody needs in the common case — and a wall of empty boxes reads as "fill me in" when blank is correct.
  const [awgOpen, setAwgOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [idPath, setIdPath] = useState("");                     // operator-supplied wg-keys.dat, when we couldn't find it
  // Two different questions: does this server need us to be TOLD where its identity is (drives the notice, which
  // holds the input — so it must not vanish the moment they start typing), and is Adopt blocked right now.
  const needsIdentity = !(w && w.adoptable);
  const doAdopt = async () => {
    setBusy(true);
    if (type === "wdtt") {
      const r = await api.wdttAdopt({ node, iface, fork, wg_addr: w.wg_addr || cand.address || "",
                                      listen: (host.trim() || (w.listen || "").split(":")[0] || "") + ":" + dtls.trim(),
                                      wg_port: wgPort.trim(), max_passwords: w.max_passwords || "",
                                      identity_path: idPath.trim() });
      if (!r || !r.ok) { setBusy(false); return toast(srvText(r) || T("Adopt failed"), "err"); }
      closeAllModals(); await Store.poll();
      toast(T("Adopting the WDTT server — the node takes it over on its next sync."), "ok");
      location.hash = "#/node/" + encodeURIComponent(node); return;
    }
    const r = await api.ifaceOnboard({ node, iface, protocol: type, conf: cand.conf, endpoint_host: host.trim() });
    if (!r || !r.ok) { setBusy(false); return toast(srvText(r) || T("Adopt failed"), "err"); }
    const awgClean = AWG_ORDER.reduce((o, k) => { const v = String(awg[k] == null ? "" : awg[k]).trim(); if (v) o[k] = v; return o; }, {});
    const portChanged = port.trim() && port.trim() !== String(cand.listen_port || "");
    if (portChanged || host.trim() || (type === "awg" && Object.keys(awgClean).length)) {   // apply edits via the normal reconfigure path
      const ub = { node, iface, endpoint_host: host.trim(), listen_port: port.trim() };
      if (type === "awg") ub.awg_params = awgClean;
      await api.ifaceUpdate(ub);
    }
    Store.ifaceNew[node + "|" + iface] = { at: Date.now() };   // flash "ready" once it appears as managed
    closeAllModals(); await Store.poll();
    toast(T("Adopting interface — the node will start managing it."), "ok");
      // Stay on the NODE page: the optimistic "onboarding" card (Store.ifaceNew, set just above) lives there, and
      // this interface's own page is still the ORPHAN view until the node reports it — landing on a screen that
      // still offers Adopt/Ignore reads as though the click did nothing. The WDTT branch already stayed put.
      location.hash = "#/node/" + encodeURIComponent(node);
  };
  const blockMsg = (type === "wdtt" && needsIdentity)
    ? (w.has_identity === false || w.fork
        ? T("The node found this server but not its identity (wg-keys.dat), so adopting would mint a new key and break every client. Ignore it instead, or restore its config directory first.")
        : T("No WDTT server was found running on this interface, so there is no identity to take over. Start it and re-check, or adopt it as WireGuard/AmneziaWG."))
    : "";
  const adoptBlocked = type === "wdtt" && needsIdentity && !idPath.trim();
  return html`<${Sheet} title=${T("Adopt interface · {v1}", { v1: iface })} width=${640}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>${T("Cancel")}</button><button class="btn btn-primary" disabled=${busy || !!iperr || !!wgErr || adoptBlocked || (type === "wdtt" && !forks.length)} title=${(adoptBlocked ? blockMsg : "") || iperr || wgErr || ((type === "wdtt" && !forks.length) ? T("No WDTT forks are enabled in Settings → Turn proxies") : "")} onClick=${doAdopt}>${T("Adopt")}</button></>`}>
    <div class="iface-intro"><div>${adoptIntro(nrec.name || node)}${cand.type_why ? adoptPreselect((cand.type_hint || "wg").toUpperCase(), cand.type_why) : null}.</div></div>
    <div class="notice ok"><${Ic} i="check"/><span>${type === "wdtt"
      ? Trich("Its *server key and passwords are kept* — a panel-managed instance is built that reuses them, then the old process is stopped. Every client that already has a config keeps working.")
      : Trich("Its *server key and existing peers are kept* (add-only — the panel never removes peers it didn't create), so nothing needs re-distributing.")}</span></div>
    ${cand.peers ? html`<div class="notice warn"><${Ic} i="warn"/><span>${Trich("This interface has {count} existing. Changing the *listen port* or *endpoint* will break their current configs — you'd re-distribute the QR codes.", { count: plural(cand.peers, "peer") })}</span></div>` : null}
    <div class="field"><label>${T("Interface type")}</label>
      <div class="typepick">${[["wg", "WireGuard", "var(--online)"], ["awg", "AmneziaWG", "var(--brand)"], ["wdtt", "WDTT", WDTT_COLOR]]
        // WDTT is offered ONLY where the node positively identified one — a server process on this interface, or
        // an install on disk. Both signals are unambiguous, so there is nothing to "maybe" adopt as WDTT: without
        // either the node refuses it anyway, and the option only invites a wrong answer.
        .filter(([id]) => id !== "wdtt" || wd).map(([id, label, col]) => html`
        <button type="button" key=${id} class=${"tp-opt" + (type === id ? " on" : "")} style=${"--tpc:" + col} onClick=${() => setType(id)}>${label}</button>`)}</div>
      ${(wd && type !== "wdtt") ? html`<div class="notice warn" style="margin:8px 0 0"><${Ic} i="warn"/><span>${Trich("A *WDTT server owns this interface* and manages its own peers. Adopting it as {type} leaves both the panel and that server writing the same peer list — it appears to work until they disagree. Adopt it as *WDTT* unless you know why you want this.", { type: type.toUpperCase() })}</span></div>` : null}
      <div class="hint">${type === "wdtt" ? T("Managed as a WDTT server — the panel rebuilds it with our patched fork over its existing identity.")
        : type === "awg" ? T("Managed as AmneziaWG (obfuscated) — set its parameters below, or leave blank to keep the interface's existing ones.")
        : T("Managed as plain WireGuard.")}</div>
    </div>
    <div class="iface-grid" style="margin:0 0 16px">
      <div class="ig-item"><span class="ig-l">${T("Datapath")}</span><span class="ig-v">${cand.datapath}${cand.up ? "" : " · down"}</span></div>
      <div class="ig-item"><span class="ig-l">${T("Tunnel subnet")}</span><span class="ig-v">${cand.address || w.wg_addr || "—"}</span></div>
      <div class="ig-item"><span class="ig-l">${T("Existing peers")}</span><span class="ig-v">${cand.peers || 0}</span></div>
      ${cand.conf ? html`<div class="ig-item"><span class="ig-l">${T("Config file")}</span><span class="ig-v">${cand.conf}</span></div>` : null}
      ${type === "wdtt" ? html`<${Fragment}>
        <div class="ig-item"><span class="ig-l">${T("Config directory")}</span><span class="ig-v">${w.config_dir || "—"}</span></div>
        <div class="ig-item"><span class="ig-l">${T("Password store")}</span><span class="ig-v">${w.store || "—"}</span></div>
        <div class="ig-item"><span class="ig-l">${T("Server identity")}</span><span class="ig-v">${w.has_identity ? html`<span class="mi-ok">${T("recoverable")}</span>` : html`<span class="mi-bad">${T("not found")}</span>`}</span></div>
      <//>` : null}
    </div>
    ${blockMsg ? html`<div class="notice warn"><div style="min-width:0">${blockMsg}
      <div class="field" style="margin:10px 0 0"><label>${T("Path to the server's key file")}</label>
        <input value=${idPath} onInput=${e => setIdPath(e.target.value)} placeholder="/etc/wdtt/wg-keys.dat"/>
        <div class="hint">${T("If you know where it lives, point at it — the node checks the file first and adopts only if it can read it. Nothing is stopped or overwritten until that check passes, so a wrong path costs nothing.")}</div>
      </div></div></div>` : null}
    <div class="row2">
      ${type === "wdtt" ? html`<div class="field"><label>${T("Server fork")}</label>
        <select value=${fork} onChange=${e => setFork(e.target.value)}>${forks.map(f => html`<option value=${f.id}>${f.label}</option>`)}</select>
        <div class="hint">${w.fork ? Trich("Detected *{v1}*{v2} — change only if wrong", { v1: w.fork, v2: w.store ? " (" + w.store + ")" : "" }) : T("Pick the fork this server runs")}</div>
      </div>` : null}
      <div class="field"><label>${T("Endpoint host / IP")}</label><${NodeIpPick} ips=${nrec.ips || []} value=${host} onChange=${setHost} auto=${T("Auto (node's detected address)")} customPlaceholder="IP or hostname"/><div class="hint">${T("What clients dial")}</div></div>
      ${type === "wdtt" ? null
        : html`<div class="field"><label>${T("Listen port")}</label><input class=${iperr ? "bad" : ""} value=${port} onInput=${e => setPort(e.target.value)} placeholder=${String(cand.listen_port || "")}/>${iperr ? html`<div class="hint err">${iperr}</div>` : html`<div class="hint">${T("Currently {v1}", { v1: cand.listen_port || "—" })}</div>`}</div>`}
    </div>
    ${type === "wdtt" ? html`<div class="row2">
      <div class="field"><label>${T("Listen port (DTLS)")}</label><input class=${iperr ? "bad" : ""} value=${dtls} onInput=${e => setDtls(e.target.value)} placeholder=${wdttDtls}/>${iperr ? html`<div class="hint err">${iperr}</div>` : html`<div class="hint">${T("What clients dial · currently {v1}", { v1: wdttDtls || "—" })}</div>`}</div>
      <div class="field"><label>${T("Internal WG port")}</label><input class=${wgErr ? "bad" : ""} value=${wgPort} onInput=${e => setWgPort(e.target.value)} placeholder=${String(w.wg_port || "")}/>${wgErr ? html`<div class="hint err">${wgErr}</div>` : html`<div class="hint">${T("The server's own tunnel port — not dialled by clients")}</div>`}</div>
    </div>` : null}
    ${type === "awg" ? html`<div class="field" style="margin-top:4px">
      <${Disclosure} title=${T("AmneziaWG parameters")} open=${awgOpen} onToggle=${() => setAwgOpen(o => !o)}
          summary=${Object.values(awg).some(v => String(v || "").trim()) ? "overridden" : T("keeping the interface's own")}>
        <div class="hint" style="margin:0 0 8px">${T("Rendered into configs/QRs. Leave blank to keep the interface's existing values.")}</div>
        <div class="awg-cols">${[["Jc", "Jmin", "Jmax"], ["S1", "S2", "S3", "S4"], ["H1", "H2", "H3", "H4"], ["I1", "I2", "I3", "I4", "I5"]].map(grp => html`<div class="awg-col">${grp.map(k => html`<label class="awg-f"><span>${k}</span><input value=${awg[k] == null ? "" : awg[k]} onInput=${e => setAwgK(k, e.target.value)}/></label>`)}</div>`)}</div>
      <//></div>` : null}
  <//>`;
}
// ═════════════════════════ SCREEN: INTERFACE DETAIL ═════════════════════════
export function IfaceDetail({ node: rawNode, iface: rawIface }) {
  useStore();
  const [q, setQ] = useState("");
  const node = decodeURIComponent(rawNode);
  const iface = decodeURIComponent(rawIface);
  const nrec = (Store.nodes || []).find(n => n.id === node);   // FULL record (turn_manage/restarting/cmd_errors/ip_ifaces)
  if (!nrec) return html`<div class="screen"><div class="crumb"><a href="#/nodes">${T("col|Nodes")}</a><span class="sep">/</span><b>${T("val|server")}</b></div>
    <div class="empty"><b>${T("Unknown server")}</b>${T("this server isn't in the fleet.")}</div></div>`;
  // WDTT owns its interface (reported in snap.wdtt, not describe) → a dedicated detail (server info + users),
  // not the wg/awg config view. Keyed off the read-back so it's never mistaken for a missing/ghost wg iface.
  const _wInst = ((Store.stats[node] || {}).wdtt || []).find(w => w && w.iface === iface);
  // A WDTT server the panel still WANTS but the node no longer reports (rebuilt box, or a node running a build
  // without WDTT support) has no snapshot entry at all — without this it fell through to the wg/awg views and
  // showed up as a ghost interface, or as nothing. Route it here on the desired config alone; WdttIfaceDetail
  // already falls back to cfg for every field, and `missing` puts it in the restore-or-recreate state.
  const _wCfg = !_wInst && ((nrec.wdtt_cfg || {})[iface] || null);
  if (_wInst || _wCfg) return html`<${WdttIfaceDetail} node=${node} iface=${iface} w=${_wInst || { iface }} nrec=${nrec} missing=${!_wInst}/>`;
  // A DORMANT WDTT install has no interface at all — no device, no socket, no process — so it has no interface
  // NAME to be routed by. It is identified by its config dir, which url-encodes into this same slot (a path has
  // no bare "/" once encoded). Its users can run to dozens, which is why they get a screen and not a modal.
  if (iface.startsWith("/")) {
    const _dorm = (nrec.wdtt_dormant || []).find(x => x && x.config_dir === iface)
              || (nrec.ignored_dormant || []).find(x => x && x.config_dir === iface);
    // Shaped as a CANDIDATE so it lands on the SAME screen: the head, the details panel, Ignore/Adopt and the
    // user grid are already there and behave identically — a stopped install is the same decision as a running
    // orphan, minus a running interface.
    if (_dorm) return html`<${CandidateIfaceDetail} node=${node} iface=${iface} nrec=${nrec} dorm=${_dorm}
      ignored=${(nrec.ignored_dormant || []).some(x => x && x.config_dir === iface)}
      cand=${{ name: (_dorm.config_dir || "").split("/").filter(Boolean).pop() || "wdtt", wdtt_hint: true,
               type_hint: "wdtt", datapath: "userspace", address: "", listen_port: _dorm.listen_port || 0,
               peers: 0, peer_list: [], conf: _dorm.config_dir,
               wdtt: { fork: _dorm.fork, config_dir: _dorm.config_dir, store: _dorm.store,
                       has_identity: true, adoptable: true, users: _dorm.users || [] } }}/>`;
    return html`<div class="screen"><div class="crumb"><a href="#/nodes">${T("col|Nodes")}</a><span class="sep">/</span><a href=${"#/node/" + encodeURIComponent(node)}>${nrec.name || node}</a><span class="sep">/</span><b>${iface}</b></div>
      <div class="empty"><b>${T("Not found")}</b>${T("the node no longer reports a WDTT install at this path — it may have been started (look for it as an interface) or removed.")}</div></div>`;
  }
  const dname = nrec.name || node;
  const meta = Store.ifaceMeta(node, iface);
  // Approach-B adoption candidate: found on the node, not managed by the panel → the stripped Adopt/Ignore view.
  // (ignored candidates land here too — the detail then offers Un-ignore instead of Ignore.)
  const _cand = !meta && ((nrec.iface_candidates || []).find(c => c && c.name === iface) || (nrec.ignored_candidates || []).find(c => c && c.name === iface));
  if (_cand) return html`<${CandidateIfaceDetail} node=${node} iface=${iface} cand=${_cand} nrec=${nrec} ignored=${(nrec.ignored_candidates || []).some(c => c && c.name === iface)}/>`;
  const _rawMiss = (!meta && nrec.missing_ifaces && nrec.missing_ifaces[iface]) || null;
  const missIf = (_rawMiss && _rawMiss.key_source) ? _rawMiss : null;   // RECOVERABLE (key backup/vault) → read-only, only action Restore interface
  const ghostIf = (!meta && !missIf && ghostIface(node, iface)) || null;   // lost + KEYLESS → read-only, only action Recreate and rekey interface
  const live = Store.recon.nodeStatus[node] === "live";
  const blocked = !live || inProc(nrec.proc_status) || !!missIf;   // missing → fully read-only (every edit/lifecycle button off; only Restore acts)
  // a pending listen-port change: desired (panel) != reported (node) until the node converges
  const updating = !!(meta && meta.desired_port && meta.listen_port && Number(meta.desired_port) !== Number(meta.listen_port));
  const type = ghostIf   // a ghost has no meta/awg_params → infer the badge from the peers that reference it (else it always reads "wg")
    ? (Store.recon.peers.some(p => (p.targets || []).some(t => t.node === node && t.iface === iface && t.type === "awg")) ? "awg" : "wg")
    : ((((meta && meta.awg_params) || (missIf && missIf.awg_params)) && Object.keys((meta && meta.awg_params) || (missIf && missIf.awg_params) || {}).length) ? "awg" : "wg");
  const peers = Store.recon.peers.filter(p => p.targets.some(t => t.node === node && t.iface === iface));
  const onl = peers.filter(p => p.targets.some(t => t.node === node && t.iface === iface && t.online)).length;
  const orphans = Store.recon.orphans.filter(o => o.node === node && o.iface === iface);
  const restarting = (nrec.restarting || []).includes(iface);
  const istate = (((Store.stats[node] || {}).interfaces || {})[iface] || {});
  const istopped = !!istate.stopped;   // operator stopped it → a choice, not a failure (no error notice)
  const idown = !istopped && istate.down;   // genuinely down (failed to come up)
  const notup = !!idown || istopped;        // either way: offer Start + Edit
  const op = Store.ifaceOp[node + "|" + iface];   // start/stop/restart lifecycle (busy/ok/fail flash)
  // AmneziaWG params split into the four header columns: J* under Endpoint, S* under Server
  // address, H* under DNS, and I* (+ anything else) under MTU.
  const ap = (meta && meta.awg_params) || (missIf && missIf.awg_params) || {};
  const awgGrp = pred => Object.entries(ap).filter(([k]) => pred(k)).map(([k, v]) => k + "=" + v);
  const awgCols = [awgGrp(k => k[0] === "J"), awgGrp(k => k[0] === "S"), awgGrp(k => k[0] === "H"), awgGrp(k => !"JSH".includes(k[0]))];
  const rows = peers.slice().sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status] || String(a.name).localeCompare(String(b.name)));
  // one {peer,target} row per peer on this interface, fed to the shared PeerGrid
  const ifaceRows = rows.map(p => ({ p, t: p.targets.find(d => d.node === node && d.iface === iface) || {} }));
  const ifaceShown = {};
  for (const { p, t } of ifaceRows) (ifaceShown[p.id] = ifaceShown[p.id] || new Set()).add(tkey(t.node, t.iface));
  const ql = q.trim().toLowerCase();
  const ifaceFiltered = !ql ? ifaceRows : ifaceRows.filter(({ p, t }) => {
    const u = p.user_id ? Store.user(p.user_id) : null;
    return searchMatch((p.title || "") + " " + (p.name || "") + " " + (t.ip || "") + " " + (u ? u.name : ""), ql);
  });

  return html`<div class="screen">
    <${NodeRail} active=${node}/>
    <div class="crumb"><a href="#/nodes">${T("col|Nodes")}</a><span class="sep">/</span><a href=${"#/node/" + encodeURIComponent(node)}>${dname}</a><span class="sep">/</span><b>${iface}</b></div>
    <div class="detail-head">
      <div class="title"><h1>${iface}</h1><span class=${"iftype " + type}>${type}</span>${missIf ? html`<span class="nstat down"><${Ic} i="warn"/> ${T("tag|missing")}</span>` : ghostIf ? html`<span class="nstat down"><${Ic} i="warn"/> ${T("tag|ghost")}</span>` : istopped ? html`<span class="nstat stopped" title=${T("Stopped by you — Start it whenever you're ready")}><${Ic} i="stop"/> ${T("tag|stopped")}</span>` : idown ? html`<span class="nstat down" style="cursor:pointer" title=${(nrec.cmd_errors || {})[iface] || (T("down on the node — {v1}", { v1: idown }))} onClick=${() => openConfirm({ title: T("Interface down on the node"), log: (nrec.cmd_errors || {})[iface] || (T("down on the node — {v1}", { v1: idown })), confirmLabel: T("Close") })}><${Ic} i="warn"/> ${T("tag|down")}</span>` : live ? html`<span class="reporting">${T("reporting")}</span>` : html`<span class="nstat stale"><${Ic} i="info"/> ${T("stale")}</span>`}<span class="when"><${OnlinePeersTag} nodeId=${node} iface=${iface} total=${peers.length} orphans=${orphCount(node, iface)}/></span></div>
      <div class="grow"></div>
    </div>
    ${idown ? html`<div class="notice warn"><${Ic} i="warn"/><span>${ifaceDownNote((nrec.cmd_errors || {})[iface] || idown)}</span></div>` : null}

    ${missIf ? html`<${Fragment}>
        <div class="notice warn"><${Ic} i="warn"/><span>${ifaceGoneNote(iface, dname, missIf.key_source
      ? T("Its original server key is recoverable, so Restore recreates it cleanly and every peer below reconnects with no changes.")
      : T("Its original server key can't be recovered, so Restore recreates it with a NEW key and the peers below must re-import a fresh config."))}</span></div>
        <${Panel} icon="key" title=${T("Interface details (saved)")} tone=""
          actions=${html`<button class="btn btn-mini restore" disabled=${!missIf.ripe} title=${missIf.ripe ? T("Recreate this interface with its original identity — recovers every peer on it") : T("Confirming it's really gone (a couple of minutes) before Restore is offered")} onClick=${() => confirmRestoreInterface(node, iface, missIf)}><${Ic} i="refresh"/> ${T("Restore interface")}</button>`}>
          <div class="iface-grid">
            <div class="ig-item"><span class="ig-l">${T("col|Endpoint")}</span><span class="ig-v">${((missIf.address ? missIf.address.split("/")[0] : "") + (missIf.listen_port ? ":" + missIf.listen_port : "")) || "—"}</span></div>
            <div class="ig-item"><span class="ig-l">${T("Server address")}</span><span class="ig-v">${missIf.address || "—"}</span></div>
            <div class="ig-item"><span class="ig-l">${T("Subnet")}</span><span class="ig-v">${missIf.subnet || "—"}</span></div>
            <div class="ig-item"><span class="ig-l">${T("Listen port")}</span><span class="ig-v">${missIf.listen_port || "—"}</span></div>
          </div>
          ${type === "awg" ? html`<div class="iface-amnezia"><span class="ig-l">AmneziaWG</span><div class="iface-grid" style="margin-top:8px">${awgCols.map(g => html`<div class="ig-item"><span class="ig-v">${g.length ? g.map(l => html`<span>${l}</span>`) : "—"}</span></div>`)}</div></div>` : null}
        <//></>`
      : ghostIf ? html`<${Fragment}>
          <div class="notice danger"><${Ic} i="warn"/><span>${Trich("Interface *{iface}* is gone from {node} with *no recoverable key*, so it can't be restored — this view is *read-only*. Recreating it means a *new server key*, and every peer below must *re-import* a fresh QR / config. The only action here is *Recreate and rekey interface*.", { iface, node: dname })}</span></div>
        <${Panel} icon="key" title=${T("Interface (lost — no recoverable key)")} tone=""
          actions=${html`<button class="btn btn-mini ghost" disabled=${!ghostIf.ripe} title=${ghostIf.ripe ? T("Recreate this interface with a NEW key and rekey every peer on it (clients re-import)") : T("Confirming it's really gone (a couple of minutes) before Recreate is offered")} onClick=${() => openRecreateRekey(node, iface)}><${Ic} i="refresh"/> ${T("Recreate and rekey interface")}</button>`}>
          <div class="iface-grid">
            <div class="ig-item"><span class="ig-l">${T("Subnet")}</span><span class="ig-v">${ghostIf.subnet || "—"}</span></div>
            <div class="ig-item"><span class="ig-l">${T("Peers affected")}</span><span class="ig-v">${ghostPeers(node, iface).length}</span></div>
          </div>
        <//></>`
      : !meta ? html`<div class="notice warn"><${Ic} i="warn"/><span>${T("This interface hasn't been reported in a snapshot yet.")}</span></div>`
      : html`<${Panel} icon="key" title=${T("Interface details")} tone=${type === "awg" ? "" : "online"}
          actions=${Store.ifaceGone[node + "|" + iface]
            // Delete already submitted, the node has not torn it down yet. Leaving Stop/Restart/Edit live
            // invites commands against an interface that is going away; show what is happening instead.
            ? html`<${StatusTag} cls="tg-del" icon="clock" label="deleting" title=${T("The node tears it down on its next sync")}/>`
            : html`<${Fragment}>${op && op.phase === "busy" ? html`<span class="tg-busy"><${Ic} i="clock"/>${ifopBusy(op.verb)}…</span>` : op && op.phase === "ok" ? html`<span class="tg-ok"><${Ic} i="check"/>${ifopDone(op.verb)}</span>` : op && op.phase === "fail" ? html`<${StatusTag} cls="tg-del" icon="warn" label=${ifopFail(op.verb)} msg=${op.err || T("the action failed on the node")} title=${T("Action failed on the node")}/>` : null}${(op && op.phase === "busy") ? null : notup
              ? html`<button class="btn btn-mini" disabled=${blocked} title=${blocked ? T("Unavailable while the node is down / converting") : T("Bring this interface up on the node")} onClick=${() => startOrRestartIface(node, iface, "start")}><${Ic} i="play"/> ${T("Start service")}</button>`
              : html`<${Fragment}><button class="btn btn-mini" disabled=${blocked} title=${blocked ? T("Unavailable while the node is down / converting") : T("Take this interface down on the node (stays down until started)")} onClick=${() => startOrRestartIface(node, iface, "stop")}><${Ic} i="stop"/> ${T("Stop service")}</button><button class="btn btn-mini" disabled=${blocked} title=${blocked ? T("Unavailable while the node is down / converting") : T("Bounce this interface's service on the node")} onClick=${() => startOrRestartIface(node, iface, "restart")}><${Ic} i="refresh"/> ${T("Restart service")}</button><//>`}<button class="btn btn-mini" disabled=${blocked || (op && op.phase === "busy")} title=${blocked ? T("Unavailable while the node is down / converting") : ""} onClick=${() => openEditIface(node, iface)}><${Ic} i="pencil"/>${T("Edit interface")}</button><//>`}>
        <div class="iface-grid">
          <div class="ig-item"><span class="ig-l">${T("col|Endpoint")}</span><span class="ig-v">${meta.endpoint || "—"}</span></div>
          <div class="ig-item"><span class="ig-l">${T("Server address")}</span><span class="ig-v">${meta.address || "—"}</span></div>
          <div class="ig-item"><span class="ig-l">${T("Throughput")}</span><span class="ig-v">${ifTrafficBadge(meta.egress_mode, meta.egress_node)}</span></div>
          <div class="ig-item"><span class="ig-l">MTU</span><span class="ig-v">${meta.mtu || 1280}</span></div>
        </div>
        ${type === "awg" ? html`<div class="iface-amnezia">
          <span class="ig-l">AmneziaWG</span>
          <div class="iface-grid" style="margin-top:8px">
            ${awgCols.map(g => html`<div class="ig-item"><span class="ig-v">${g.length ? g.map(l => html`<span>${l}</span>`) : "—"}</span></div>`)}
          </div>
        </div>` : null}
      <//>`}

    ${meta ? html`<${IfaceThroughput} node=${node} iface=${iface}/>` : null}

    ${turnEnabled() ? html`<${TurnProxiesBlock} node=${node} nrec=${nrec} metas=${Store.describe[node] || {}} title=${T("Reachable via turn-proxy")} iface=${iface}/>` : null}

    <${Panel} icon="users" title=${T("Peers on this interface")} count=${peers.length} pad=${false}
        lead=${html`<div class="search hdr"><${Ic} i="search"/><input placeholder=${T("Search title, user, address…")} value=${q} onInput=${e => setQ(e.target.value)}/></div>`}
        actions=${Store.ifaceGone[node + "|" + iface] ? null   // teardown in flight → adding a peer to it is a dead end
          : html`<button class="btn btn-mini" disabled=${blocked} title=${blocked ? T("Unavailable while the node is down / converting") : ""} onClick=${() => openCreatePeer({ node, iface, lock: true })}><${Ic} i="plus"/> ${T("Add peer")}</button>`}>
      <${PeerGrid} rows=${ifaceFiltered} agg=${false} node=${node} iface=${iface} shownByPeer=${ifaceShown} q=${q} blocked=${blocked}/>
    <//>

    ${orphans.length ? html`<div id="iface-orphans"><${Panel} icon="warn" title=${T("Unmanaged on this interface")} tone="warn" pad=${false}
        actions=${html`<button class="btn btn-mini" onClick=${() => orphans.forEach(o => mutate({
          key: "orphan:" + o.node + "|" + o.iface + "|" + o.pubkey,
          patch: adoptOrphanPatch(o),
          call: () => api.peerAdopt({ pubkey: o.pubkey, psk: o.preshared_key || "", target: { node: o.node, iface: o.iface, ip: (o.allowed_ips || "").split("/")[0] } }),
        }))}><${Ic} i="link"/> ${T("Adopt all")}</button>`}>
      <table><tbody>
        ${orphans.map(o => html`<${OrphanRow} key=${o.node + "|" + o.iface + "|" + o.pubkey} o=${o}/>`)}
      </tbody></table>
    <//></div>` : null}
  </div>`;
}

// A WDTT interface's detail page: the self-contained server (info + lifecycle) + its users (the shared PeerGrid).
// One record — the server's turn-half is edited from its Turn-proxies card; here we manage the interface + peers.
export function WdttIfaceDetail({ node, iface, w, nrec, missing }) {
  useStore();
  const [q, setQ] = useState("");
  const dname = nrec.name || node;
  const live = Store.recon.nodeStatus[node] === "live";
  const blocked = !live || inProc(nrec.proc_status);
  const cfg = (nrec.wdtt_cfg || {})[iface] || {};
  const fork = w.fork || cfg.fork || "amurcanov";
  const active = w.active === "active";
  // `missing` = the node doesn't report this server at all. Treat it exactly like await_restore: the identity is
  // escrowed, so offer Restore (or Recreate fresh) and keep every other control off — there is nothing running
  // to start, stop or edit.
  // A take-over in flight writes the instance into wdtt_cfg at once, while the node has not reported it yet —
  // which reads exactly like "gone from the box". So this page offered Restore / Recreate fresh for a server
  // being ADOPTED, and "Recreate fresh" there would mint a new key and break the very clients the adoption
  // exists to keep. `adopting` therefore wins over `missing`, and stands down every lifecycle control until
  // the node reports the result.
  const adopting = (nrec.wdtt_adopting || []).includes(iface);
  const awaiting = !adopting && (!!w.await_restore || !!missing);
  const stopped = !!cfg.stopped;
  const notup = !active && !awaiting;   // stopped / starting → offer Start; else Stop + Restart
  const restoring = (nrec.wdtt_restoring || []).includes(iface);
  const restorable = !!((nrec.wdtt_vault || {})[iface]);
  const op = Store.ifaceOp[node + "|" + iface];   // start/stop/restart/apply lifecycle (busy/ok/fail flash)
  const peers = Store.recon.peers.filter(p => p.targets.some(t => t.node === node && t.iface === iface));
  const rows = peers.slice().sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status] || String(a.name).localeCompare(String(b.name)));
  const ifaceRows = rows.map(p => ({ p, t: p.targets.find(d => d.node === node && d.iface === iface) || {} }));
  const ifaceShown = {}; for (const { p, t } of ifaceRows) (ifaceShown[p.id] = ifaceShown[p.id] || new Set()).add(tkey(t.node, t.iface));
  const ql = q.trim().toLowerCase();
  const ifaceFiltered = !ql ? ifaceRows : ifaceRows.filter(({ p, t }) => { const u = p.user_id ? Store.user(p.user_id) : null; return searchMatch((p.title || "") + " " + (p.name || "") + " " + (t.ip || "") + " " + (u ? u.name : ""), ql); });
  const opFlash = op && op.phase === "busy" ? html`<span class="tg-busy"><${Ic} i="clock"/>${ifopBusy(op.verb)}…</span>`
    : op && op.phase === "ok" ? html`<span class="tg-ok"><${Ic} i="check"/>${ifopDone(op.verb)}</span>`
    : op && op.phase === "fail" ? html`<${StatusTag} cls="tg-del" icon="warn" label=${ifopFail(op.verb)} msg=${op.err || T("the action failed on the node")} title=${T("Action failed on the node")}/>` : null;
  return html`<div class="screen">
    <${NodeRail} active=${node}/>
    <div class="crumb"><a href="#/nodes">${T("col|Nodes")}</a><span class="sep">/</span><a href=${"#/node/" + encodeURIComponent(node)}>${dname}</a><span class="sep">/</span><b>${iface}</b></div>
    <div class="detail-head">
      <div class="title"><h1>${iface}</h1><span class="iftype wdtt">WDTT</span><${ForkTag} fork=${fork}/>${adopting ? html`<span class="tg-busy"><${Ic} i="clock"/>${T("tag|adopting")}</span>` : awaiting ? html`<span class="nstat down"><${Ic} i="shield"/> ${missing ? "missing" : T("awaiting restore")}</span>` : (op && op.phase === "busy") ? html`<span class="tg-busy"><${Ic} i="clock"/>${ifopBusy(op.verb)}</span>` : stopped ? html`<span class="nstat stopped" title=${T("Stopped by you — Start it whenever you're ready")}><${Ic} i="stop"/> ${T("tag|stopped")}</span>` : active ? html`<span class="reporting">${T("tag|running")}</span>` : html`<span class="nstat stale"><${Ic} i="clock"/> ${T("tag|starting")}</span>`}<span class="when"><${OnlinePeersTag} nodeId=${node} iface=${iface} total=${peers.length} orphans=${0}/></span></div>
      <div class="grow"></div>
    </div>
    ${adopting ? html`<div class="notice"><${Ic} i="clock"/><span>${Trich("This server is being *taken over* — the node stops the existing one and brings it back up under the panel with its original identity and users. Its controls stay disabled until that finishes.")}</span></div>` : null}
    ${awaiting ? html`<div class="notice warn"><${Ic} i="shield"/><span>${missing ? T("This node isn't reporting this server — it's gone from the box (a rebuild, or a node running a build without WDTT support).") : T("This server was wiped.")} ${Trich("Its identity is escrowed in your Encryption Vault, so it's held offline rather than coming back with a fresh key that would break every user. *Restore* to bring it back with its original identity, or *Recreate fresh* (every user re-imports).")}
      <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap"><button class="btn btn-primary" disabled=${restoring} onClick=${() => wdttRestoreIdentity(node, iface)}><${Ic} i="shield"/> ${restoring ? T("Restoring…") : T("Restore server identity")}</button><button class="btn btn-ghost" disabled=${restoring} onClick=${() => wdttRecreateFresh(node, iface)}>${T("Recreate fresh")}</button></div></span></div>` : null}
    <${Panel} icon="key" title=${T("Interface details")} tone="online"
        actions=${Store.ifaceGone[node + "|" + iface]
          // Delete already submitted, the node has not torn it down yet — same guard as the wg/awg page.
          ? html`<${StatusTag} cls="tg-del" icon="clock" label="deleting" title=${T("The node tears it down on its next sync")}/>`
          : adopting
          // Take-over in flight: Stop/Restart/Edit/Delete would all act on a server that is being replaced.
          ? html`<${StatusTag} cls="tg-busy" icon="clock" label="adopting" title=${T("The node applies the take-over on its next sync")}/>`
          : html`<${Fragment}>${opFlash}${(op && op.phase === "busy") ? null : notup
          ? html`<button class="btn btn-mini" disabled=${blocked || awaiting} title=${blocked ? T("Unavailable while the node is down") : T("Bring this WDTT server up on the node")} onClick=${() => startOrRestartWdtt(node, iface, "start")}><${Ic} i="play"/> ${T("Start service")}</button>`
          : html`<${Fragment}><button class="btn btn-mini" disabled=${blocked} title=${T("Take this WDTT server down (stays down until started)")} onClick=${() => startOrRestartWdtt(node, iface, "stop")}><${Ic} i="stop"/> ${T("Stop service")}</button><button class="btn btn-mini" disabled=${blocked} title=${T("Bounce this WDTT server on the node")} onClick=${() => startOrRestartWdtt(node, iface, "restart")}><${Ic} i="refresh"/> ${T("Restart service")}</button><//>`}<button class="btn btn-mini" disabled=${blocked || awaiting || (op && op.phase === "busy")} title=${blocked ? T("Unavailable while the node is down") : ""} onClick=${() => openEditWdtt(node, iface)}><${Ic} i="pencil"/>${T("Edit interface")}</button><button class="btn btn-mini danger" disabled=${blocked || (op && op.phase === "busy")} title=${T("Stop + remove this WDTT server and disconnect its users")} onClick=${() => openModal(html`<${WdttDeleteSheet} node=${node} iface=${iface}/>`)}><${Ic} i="trash"/>${T("Delete")}</button><//>`}>
      <div class="iface-grid">
        <div class="ig-item"><span class="ig-l">${T("col|Endpoint")}</span><span class="ig-v">${w.listen || cfg.listen || "—"}</span></div>
        <div class="ig-item"><span class="ig-l">${T("Server address")}</span><span class="ig-v">${w.wg_addr || "—"}</span></div>
        <div class="ig-item"><span class="ig-l">${T("Throughput")}</span><span class="ig-v">${ifTrafficBadge(cfg.egress_mode, cfg.egress_node)}</span></div>
        <div class="ig-item"><span class="ig-l">${T("Fork")}</span><span class="ig-v"><${ForkTag} fork=${fork}/></span></div>
      </div>
    <//>

    <${IfaceThroughput} node=${node} iface=${iface}/>

    ${/* A WDTT fork IS a turn-family server, so this page shows its card in the same section the node screen
          uses — read-only here: no add-proxy button, because a WDTT server owns its own transport
          and nothing can be pointed at this interface. */""}
    ${turnEnabled() ? html`<${TurnProxiesBlock} node=${node} nrec=${nrec} metas=${Store.describe[node] || {}} title=${T("WDTT proxy")} iface=${iface}/>` : null}

    <${Panel} icon="users" title=${T("Peers on this interface")} count=${peers.length} pad=${false}
        lead=${html`<div class="search hdr"><${Ic} i="search"/><input placeholder=${T("Search title, user, address…")} value=${q} onInput=${e => setQ(e.target.value)}/></div>`}
        actions=${Store.ifaceGone[node + "|" + iface] ? null   // teardown in flight → adding a peer to it is a dead end
          : html`<button class="btn btn-mini" disabled=${blocked} title=${blocked ? T("Unavailable while the node is down") : ""} onClick=${() => openCreatePeer({ node, iface, lock: true })}><${Ic} i="plus"/> ${T("Add peer")}</button>`}>
      <${PeerGrid} rows=${ifaceFiltered} agg=${false} node=${node} iface=${iface} shownByPeer=${ifaceShown} q=${q} blocked=${blocked}/>
    <//>
  </div>`;
}

export function OrphanRow({ o }) {
  return html`<tr>
    <td data-label=${T("col|Status")}><${Badge} s="orphan"/></td>
    <td data-label=${T("Key")} class="addr">${o.pubkey.slice(0, 22)}…</td>
    <td data-label=${T("col|Address")}><span class="addr">${o.iface} · ${o.allowed_ips || "—"}</span></td>
    <td data-label="" style="text-align:right" class="rowacts">
      <button class="btn btn-mini" onClick=${() => mutate({   // server assigns the real id; this is the overlay
        key: "orphan:" + o.node + "|" + o.iface + "|" + o.pubkey,
        patch: adoptOrphanPatch(o),
        call: () => api.peerAdopt({ pubkey: o.pubkey, psk: o.preshared_key || "", target: { node: o.node, iface: o.iface, ip: (o.allowed_ips || "").split("/")[0] } }),
      })}>${T("Adopt")}</button>
      <${RowError} k=${"orphan:" + o.node + "|" + o.iface + "|" + o.pubkey}/>
    </td></tr>`;
}

// Edit an interface: the Endpoint IP (what clients dial — config-facing only) and the Listen
// port (pushed to the node's wgXX.conf — the interface rebinds to it; peers are untouched and
// reconnect via the new port). Default DNS / MTU seed new peers. Interface key shown read-only.
// Ask the node to manage an existing wg/awg interface the panel didn't auto-detect. The node only
// needs the tool (wg/awg) + the .conf path; the public endpoint is a panel-side render override.
export function openOnboardIface(node) { openModal(html`<${LoadIfaceSheet} node=${node}/>`); }
export function BridgePortSheet({ iface, port }) {   // shown after creating an iface on a bridge docker node
  const p = port || "PORT";
  const portsLine = `- "${p}:${p}/udp"`;
  return html`<${Sheet} title=${T("Publish port · {v1}", { v1: iface })}>
    <div class="iface-intro big"><div>${Trich("Creation requested — it applies on the node's next sync. This node runs on `bridge` networking, so this interface's UDP port isn't reachable from outside until you publish it on the host (otherwise peers won't handshake — rx stays 0).")}</div></div>
    <div class="field"><label>${dockerPortsStep()}</label><div class="ipk-field"><span class="ipk-val" style="text-align:left">${portsLine}</span><button class="copybtn" onClick=${() => copy(portsLine, T("Copied"))}><${Ic} i="copy"/></button></div></div>
    <div class="field"><label>${T("2. Apply (in the node's compose dir)")}</label><div class="ipk-field"><span class="ipk-val" style="text-align:left">docker compose up -d</span><button class="copybtn" onClick=${() => copy("docker compose up -d", T("Copied"))}><${Ic} i="copy"/></button></div><div class="hint">${T("Re-installing the node with host networking avoids per-port publishing entirely.")}</div></div>
  <//>`;
}

// Two-dropdown egress: where an interface's traffic exits — Auto, Direct out a NIC, or Forward (cascade)
// to another node — plus the source IP (this node's, or the TARGET node's for forward). value =
// {mode:"auto"|"direct"|"forward", nic, node, ip}; the routing for "forward" is wired in Phase 2.



export function LoadIfaceSheet({ node, pre, ghost, back }) {
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const isBridge = nrec.kind === "docker" && (nrec.net_mode || "host") === "bridge";   // only bridge needs port publishing
  const _defProto = (pre && pre.proto) || "wg";   // WireGuard is the default base for a new interface
  const [proto, setProto] = useState(_defProto);   // wg | awg | wdtt | existing
  const sugAwg = suggestIface(node, "awg"), sugWg = suggestIface(node, "wg");   // auto-suggested names (per base)
  // WDTT name + subnet suggestions (next free wdttN + a free 10.66.N.1/24, avoiding other WDTT instances).
  // Ports use the SHARED suggestPort() — WDTT instances are now counted in usedPortsOn(), so a 2nd wdtt on the
  // node never clashes on its DTLS listen or its internal wg-port (nor with any interface / turn-proxy).
  // nextWdttName(), NOT a local scan of snap.wdtt: the readback only lists servers the node is already RUNNING,
  // so while one is still being created this handed out its name a second time — and /api/wdtt/set is an upsert,
  // so creating a second WDTT back-to-back silently overwrote the first ("the second one never appears"). The
  // ports and subnet below never had the bug because they use the shared suggestPort/suggestSubnet, which
  // already count the desired set and the in-flight ones; the name had a bespoke copy that did not.
  const sugWdtt = nextWdttName(node);
  const sugWdttNet = suggestSubnet(node);   // WDTT takes the SAME subnet form as wg/awg (10.X.0.0/24, fleet-unique); the server .1 is derived on save
  const sugWdttListen = suggestPort(node, "turn");                        // external DTLS (turn-proxy family)
  const sugWdttWg = suggestPort(node, "turn", [sugWdttListen]);           // internal userspace-WG port (≠ the listen)
  const [iface, setIface] = useState((pre && pre.iface) || (_defProto === "wdtt" ? sugWdtt : _defProto === "awg" ? sugAwg : sugWg)); const [subnet, setSubnet] = useState((pre && pre.subnet) || ((pre && pre.proto) === "wdtt" ? sugWdttNet : suggestSubnet(node)));
  const [host, setHost] = useState(""); const [port, setPort] = useState(String((pre && pre.proto) === "wdtt" ? sugWdttListen : suggestPort(node, "iface")));
  const _wdttForks = enabledTurnForks().filter(f => f.kind === "wdtt");   // WDTT server forks the operator has enabled
  const [wgPort, setWgPort] = useState(String(sugWdttWg)); const [fork, setFork] = useState((_wdttForks[0] || {}).id || "amurcanov");   // WDTT: internal userspace-WG port + which server fork (default = first enabled)
  // WDTT is a turn-family fork → needs turn management on this node AND at least one WDTT fork enabled (else there's
  // nothing to create) — if every WDTT fork is disabled in Settings, don't offer the WDTT protocol at all.
  const wdttOk = turnEnabled() && nrec.turn_manage && nrec.turn_arch_ok !== false && enabledTurnForks().some(f => f.kind === "wdtt");
  const isWdtt = proto === "wdtt";
  // csqtt — a SELF-CONTAINED raw-IP TUN server, created as its own interface exactly like WDTT (peers target it).
  // Same gate (turn-managed node + csqtt enabled). It takes a subnet like wg/awg (server .1 derived), a UDP DTLS
  // listen, and a password cap — but NO fork (single binary) and NO internal WG port (raw TUN, no WireGuard).
  const sugCsqtt = nextCsqttName(node);
  const sugCsqttNet = suggestSubnet(node);
  const sugCsqttListen = suggestPort(node, "turn");
  const [maxPw, setMaxPw] = useState("500");
  const csqttOk = turnEnabled() && nrec.turn_manage && nrec.turn_arch_ok !== false && enabledTurnForks().some(f => f.kind === "csqtt");
  const isCsqtt = proto === "csqtt";
  const _idf = (Store.panelSettings || {}).interface_defaults || {};   // panel-wide new-interface defaults
  const [dns, setDns] = useState((_idf.dns || ["1.1.1.1"]).join(", ")); const [mtu, setMtu] = useState(String(_idf.mtu || 1280)); const [ka, setKa] = useState(String(_idf.keepalive || 25));
  const [conf, setConf] = useState("");
  const ips = nrec.ips || []; const [eg, setEg] = useState(() => egressInit({}));
  const [blk, setBlk] = useState(() => defaultBlockFor(node));   // Filters & abuse — seeded from each category's default_on once the catalog loads
  const blkSeeded = useRef(false);
  useEffect(() => { loadBlockCatalog().then(() => { if (blkSeeded.current) return; blkSeeded.current = true; setBlk(defaultBlockFor(node)); }); }, []);
  const [disc, setDisc] = useState({ routing: true, filters: false, advanced: false });   // collapsible sections; Routing opens by default (only shown in Smart mode)
  const tog = k => setDisc(d => ({ ...d, [k]: !d[k] }));
  // endpoint host: dropdown of the node's known IPs (default the first), last entry = a free-text "Custom IP / Host…"
  const _preEp = pre && pre.endpoint;
  const [hostSel, setHostSel] = useState(_preEp ? (ips.includes(_preEp) ? _preEp : "__custom__") : (ips[0] || "__custom__"));
  const [hostCustom, setHostCustom] = useState(_preEp && !ips.includes(_preEp) ? _preEp : "");
  const pickProto = p => {   // switching base re-suggests the name only if the field is still an untouched suggestion
    const untouched = iface === sugAwg || iface === sugWg || iface === sugWdtt || iface === sugCsqtt || !iface.trim();
    if (p !== "existing" && untouched) setIface(p === "wg" ? sugWg : p === "wdtt" ? sugWdtt : p === "csqtt" ? sugCsqtt : sugAwg);
    if (p === "wdtt") {   // WDTT: seed the subnet + collision-free DTLS listen + internal-WG ports
      if (!subnet.trim() || subnet === suggestSubnet(node)) setSubnet(sugWdttNet);
      if (!port.trim() || port === String(suggestPort(node, "iface"))) setPort(String(sugWdttListen));
      setWgPort(String(sugWdttWg));
    } else if (p === "csqtt") {   // csqtt: seed the subnet + collision-free UDP DTLS listen (no internal WG port)
      if (!subnet.trim() || subnet === suggestSubnet(node)) setSubnet(sugCsqttNet);
      if (!port.trim() || port === String(suggestPort(node, "iface"))) setPort(String(sugCsqttListen));
    } else if (port === String(sugWdttListen) || port === String(sugCsqttListen)) {   // switching away from a turn kind → restore the interface listen port
      setPort(String(suggestPort(node, "iface")));
    }
    setProto(p);
  };
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  // "Adopt existing" is a MODE, not a protocol: the same wg/awg/wdtt row above chooses the type either way.
  // As a fourth chip it forced a second identical type row underneath — the same three names twice, in two
  // different styles, one of them meaning something else.
  const [adoptMode, setAdoptMode] = useState(false);
  const existing = adoptMode;
  // Adopting BY PATH — the same choice the adopt sheet offers, because it is the same decision: what is this
  // interface? "auto" used to be inferred from the conf, which is fine for wg/awg but says nothing about WDTT.
  const exWdtt = existing && proto === "wdtt";
  const fail = t => { setBusy(false); setMsg({ k: "err", t }); };
  const save = async () => {
    setBusy(true); setMsg({ k: "work", t: "requesting…" });
    // Recreating a ghost rekeys its peers in the background once the fresh interface returns — the ONE moment the
    // browser holds each new private key. Unlock the vault UP FRONT so those fresh configs are captured as they're
    // rekeyed (re-viewable in the panel + served on subscription pages) instead of being lost on the next reload.
    // Proceed either way: if the operator skips, the prompt has already spelled out that the peers will be stranded.
    if (ghost && !existing && Store.storeMode === "encrypted" && (ghost.peers || []).length && !subSKCached()) {
      const n = ghost.peers.length;
      await ensureVaultUnlocked({
        title: T("Unlock to capture the rekeyed configs"),
        reason: T("Recreating {v1} gives its {v2} brand-new keys once it's back. Unlock your encryption key now so each fresh config is captured the moment it's rekeyed — then it stays re-viewable in the panel and is served on the users' subscription pages.", { v1: ghost.iface, v2: plural(n, "peer") }),
        consequence: T("the interface is recreated and its peers are rekeyed, but their new configs are NOT captured — they can't be re-viewed or served on subscription pages, and you'd have to hand every client a fresh QR by other means. (Unlock later in this same tab before reloading and they're still saved; after a reload the new keys are gone for good.)"),
      });
      setMsg({ k: "work", t: "requesting…" });   // the prompt may have taken a while → restore the working state
    }
    let r;
    if (existing) {
      if (proto === "wdtt") {
        // Hand the typed directory to the SAME sheet a discovered dormant install opens: it owns the fork,
        // name, ports and subnet this adoption needs, and posts /api/wdtt/adopt (adopt_config_dir), which is
        // the path that actually seeds a WDTT take-over. The old form posted ifaceOnboard — the wg/awg
        // endpoint — so typing a WDTT directory here never completed an adoption in the first place.
        const c = conf.trim();
        if (!c.startsWith("/")) return fail(T("Enter the absolute path to the server's config directory (the one holding wg-keys.dat)."));
        setBusy(false); closeModal();
        openModal(html`<${AdoptDormantWdttSheet} node=${node} nrec=${nrec}
          d=${{ config_dir: c.replace(/\/+$/, ""), fork: "", store: "", users: [], listen_port: 0, wg_port: 0 }}/>`);
        return;
      }
      if (proto === "csqtt") return fail(T("Adopting an existing csqtt server isn't supported yet — create a new one instead."));
      const c = conf.trim();
      if (!c.startsWith("/")) return fail(T("Enter the absolute path to the interface's .conf."));
      const base = (c.split("/").pop() || "").replace(/\.conf$/i, "");   // seed the name from the filename
      r = await api.ifaceOnboard({ node, iface: base, protocol: proto, conf: c, endpoint_host: host.trim() });
    } else if (isWdtt) {
      // WDTT interface: ONE record — this writes the same /api/wdtt/set the Turn-proxies card edits.
      const nm = iface.trim();
      if (!/^wdtt\d{1,3}$/.test(nm)) return fail(T("WDTT interface name must be wdtt0–wdtt999."));
      if (!/^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/.test(subnet.trim())) return fail(T("Enter the tunnel subnet as CIDR, e.g. 10.8.0.0/24."));
      if (wgPort.trim() && !/^\d+$/.test(wgPort.trim())) return fail(T("Internal WG port must be a number."));
      // Endpoint host/IP + Listen port = the turn-proxy (DTLS) side → compose the WDTT server's -listen from them
      // (blank host → 0.0.0.0, all interfaces). The interface side binds 127.0.0.1:<internal wg port>, not shown.
      // The form takes the SUBNET (10.8.0.0/24) like wg/awg; the server lives on the first host (.1) — derive it here.
      const _dtlsHost = ipPickerVal(hostSel, hostCustom).trim() || "0.0.0.0";
      r = await api.wdttSet({ node, iface: nm, wg_addr: subnetServerAddr(subnet.trim()), listen: _dtlsHost + ":" + (port.trim() || "56000"),
        wg_port: wgPort.trim() || "56001", fork, block: blk, ...egressBody(eg) });   // carry the routing mode + filters chosen at create time (same as edit)
    } else if (isCsqtt) {
      // csqtt interface: ONE record — writes the same /api/csqtt/set the Turn-proxies card edits. Raw-TUN, so no
      // internal WG port and no fork; takes the SUBNET like wg/awg (server .1 derived), a UDP DTLS listen, a pw cap.
      const nm = iface.trim();
      if (!/^csqtt\d{1,4}$/.test(nm)) return fail(T("csqtt interface name must be csqtt0–csqtt9999."));
      if (!/\/24$/.test(subnet.trim())) return fail(T("csqtt needs a /24 tunnel subnet, e.g. 10.66.67.0/24."));
      if (maxPw.trim() && !/^\d+$/.test(maxPw.trim())) return fail(T("Max passwords must be a number."));
      const _lHost = ipPickerVal(hostSel, hostCustom).trim() || "0.0.0.0";
      r = await api.csqttSet({ node, iface: nm, tun_addr: subnetServerAddr(subnet.trim()), listen: _lHost + ":" + (port.trim() || "46000"),
        max_passwords: maxPw.trim() || "500", block: blk, ...egressBody(eg) });
    } else {
      const nm = iface.trim();
      if (!nm || /[\s/]/.test(nm)) return fail(T("Interface name is required (no spaces or /)."));
      if (!/^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/.test(subnet.trim())) return fail(T("Enter the tunnel subnet as CIDR, e.g. 10.8.0.0/24."));
      if (port.trim() && !/^\d+$/.test(port.trim())) return fail(T("Listen port must be a number."));
      const ee = egressError(eg, nrec.routing_mode || "kernel"); if (ee) return fail(ee);
      const hostVal = ipPickerVal(hostSel, hostCustom);
      r = await api.ifaceCreate({ node, iface: nm, protocol: proto, subnet: subnet.trim(), endpoint_host: hostVal,
        listen_port: port.trim(), dns: dns.trim(), mtu: mtu.trim(), keepalive: ka.trim(), block: blk, ...egressBody(eg) });
    }
    if (!r.ok) return fail(srvText(r) || T("Request failed."));
    // optimistic: show the card — WITH the details just entered — the instant Create is clicked (use the
    // component-scoped state vars, not the else-block locals). Onboarding doesn't know subnet/port yet.
    const _newName = existing ? (conf.trim().split("/").pop() || "").replace(/\.conf$/i, "") : iface.trim();
    if (_newName) Store.ifaceNew[node + "|" + _newName] = existing
      ? { type: null, at: Date.now() }
      : { type: proto, subnet: subnet.trim(), port: port.trim(), endpoint: ipPickerVal(hostSel, hostCustom), at: Date.now() };
    if (ghost && !existing) Store.ghostRekey[node + "|" + _newName] = { peers: ghost.peers || [], at: Date.now() };   // phase 2: rekey these once the fresh iface is live
    closeModal(); Store.apply(); await Store.poll();
    if (!existing && !isWdtt && !isCsqtt && isBridge) { openModal(html`<${BridgePortSheet} iface=${_newName} port=${port.trim()}/>`); return; }
    toast(ghost ? ((ghost.peers || []).length === 1
        ? T("Recreating {v1} — keep this tab open and its 1 peer is rekeyed automatically once it's back; otherwise rekey it from its peer view. Then hand out the fresh config.", { v1: _newName })
        : T("Recreating {v1} — keep this tab open and its {v2} are rekeyed automatically once it's back; otherwise rekey each from its peer view. Then hand out the fresh configs.", { v1: _newName, v2: plural((ghost.peers || []).length, "peer") }))
                : (existing ? T("Onboarding requested — applies on the node's next sync.") : T("Interface creation requested — applies on the node's next sync.")), "ok", ghost ? 6000 : 3600);
  };
  // subnets must be UNIQUE across the fleet (the mesh routes by subnet) → warn + block Save on a duplicate. Skip
  // for onboarding (the node reports its own subnet) and for a ghost recreate (same iface, its subnet is expected).
  const _subConflict = (!existing && !ghost && subnet.trim()) ? subnetFleetConflict(subnet.trim(), null, null) : null;
  // The NAME had no collision check at all — only the suggestion avoided taken names, so anything typed (or a
  // name reused deliberately) went straight through. The costly case is an UNMANAGED server already holding it:
  // upstream WDTT compiles in "wdtt0", so creating our own wdtt0 beside one leaves two servers fighting over the
  // interface — ours bound to its port while the device carries the foreign subnet, and neither serving.
  // Skipped for adopt (`existing`, keyed by conf path) and for a ghost recreate, which reuses its name by design.
  const _nameTaken = (!existing && !ghost && iface.trim()) ? (() => { const nm = iface.trim();
    if ((Store.describe[node] || {})[nm] || (nrec.wdtt_cfg || {})[nm] || (nrec.csqtt_cfg || {})[nm]
        || ((Store.stats[node] || {}).wdtt || []).some(w => w && w.iface === nm)
        || ((Store.stats[node] || {}).csqtt || []).some(c => c && c.iface === nm)) return "managed";
    if ((nrec.iface_candidates || []).some(c => c && c.name === nm)) return "unmanaged";
    return null; })() : null;
  const nameErr = _nameTaken === "managed" ? T("An interface named {v1} already exists on this node.", { v1: iface.trim() })
    : _nameTaken === "unmanaged" ? T("{v1} is already on this node but isn't managed by the panel — Adopt it instead (its keys and users are kept).", { v1: iface.trim() })
    : null;
  // live port-collision checks (new interface → no own ports). WDTT also needs its DTLS ≠ internal WG port.
  const pperr = portErrMsg(node, port, []);
  const wgperr = isWdtt ? ((port.trim() && wgPort.trim() && Number(port) === Number(wgPort)) ? T("The DTLS port and internal WG port must differ.") : portErrMsg(node, wgPort, [])) : null;
  return html`<${Sheet} title=${ghost ? T("Recreate & rekey · {iface}", { iface: ghost.iface }) : T("Create new interface")} onBack=${back || null}
    foot=${footRow({ onCancel: back || closeModal, disabled: busy || !!nameErr || !!_subConflict || !!pperr || !!wgperr || (!existing && !!egressError(eg, nrec.routing_mode || "kernel")), title: (nameErr || pperr || wgperr || (_subConflict ? T("This subnet is already in use in the fleet") : (!existing && egressError(eg, nrec.routing_mode || "kernel")))) || "", onAction: save, action: ghost ? T("Recreate & rekey") : (existing ? T("Adopt") : T("Create")) })}>
    ${ghost ? html`<div class="notice danger" style="margin-bottom:16px"><${Ic} i="warn"/><span>${Trich("Interface *{iface}* is gone from {node} with *no recoverable key*, so it can't be restored — only recreated with a *new server key*. Its *{count}* will be rekeyed once it's back, so *every client must re-import* a fresh QR / config. Review the settings below (inferred from the peers) and recreate.", { iface: ghost.iface, node: Store.nodeName(node), count: plural(ghost.total, "peer") })}</span></div>` : null}
    <div class="field"><label>${T("Protocol")}</label>
      <div class=${"chiprow" + (ghost ? "" : " proto3")}>
        <button class=${"chip c-wg" + (proto === "wg" ? " on" : "")} onClick=${() => pickProto("wg")}>WireGuard</button>
        <button class=${"chip c-awg" + (proto === "awg" ? " on" : "")} onClick=${() => pickProto("awg")}>AmneziaWG</button>
        ${ghost || !wdttOk ? null : html`<button class=${"chip c-wdtt" + (proto === "wdtt" ? " on" : "")} onClick=${() => pickProto("wdtt")}>WDTT</button>`}
        ${ghost || !csqttOk ? null : html`<button class=${"chip c-csqtt" + (proto === "csqtt" ? " on" : "")} onClick=${() => pickProto("csqtt")}>CSQTT</button>`}
        ${ghost ? null : html`<button type="button" class=${"adoptsw" + (adoptMode ? " on" : "")} aria-pressed=${adoptMode}
          title=${adoptMode ? T("Taking over an interface already on the node") : T("Create a new interface — switch on to take over one already on the node")}
          onClick=${() => setAdoptMode(v => !v)}>${T("Adopt existing")}</button>`}
      </div>
      ${adoptMode ? html`<div class="hint" style="margin-top:8px">${T("Taking over an interface already on the node — its keys and peers are kept.")}</div>` : null}
    </div>
    ${existing ? html`<${Fragment}>
      ${exWdtt ? html`<div class="notice"><${Ic} i="info"/><span>${Trich("If the node has discovered this server it is quicker to adopt it from its *orphan card* on the node screen — the node has already read its fork, ports and identity. Point at the directory here when it hasn't: an install that was moved, renamed, or is stopped.")}</span></div>` : html`
      <div class="row2">
        <div class="field"><label>${T("Public endpoint host / IP")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— optional")}</span></label><input value=${host} onInput=${e => setHost(e.target.value)} placeholder=${T("vpn.xyz.com or 203.0.113.7")}/><div class="hint">${T("What clients dial. Leave blank to use the node's detected address.")}</div></div>
      </div>`}
      <div class="field"><label>${exWdtt ? T("Config directory") : T("Config path")}</label><input autofocus value=${conf} onInput=${e => setConf(e.target.value)} placeholder=${exWdtt ? "/etc/wdtt" : (proto === "awg" ? "/etc/amnezia/amneziawg/awg0.conf" : "/etc/wireguard/wg0.conf")} autocomplete="off"/>${exWdtt ? html`<div class="hint">${T("The directory holding its")} <span class="mono">wg-keys.dat</span> ${T("— for an install the node hasn't discovered (moved, renamed, or stopped).")}</div>` : null}</div>
      ${(!exWdtt && nrec.kind === "docker") ? html`<div class="notice"><${Ic} i="info"/><span>${Trich("This node runs in a container, so it can only read paths inside it — a config elsewhere on the host is invisible from here. *The interface must be running*: the node then adopts it from the live device (keys, peers, ports and AmneziaWG parameters, all fresher than any file). A stopped interface whose config the node can't read cannot be adopted.")}</span></div>` : null}
    <//>` : html`<${Fragment}>
      <div class="row2">
        <div class="field"><label>${T("Interface name")}</label><input autofocus=${!ghost} class=${nameErr ? "bad" : ""} value=${iface} onInput=${e => { if (!ghost) setIface(e.target.value); }} readOnly=${!!ghost} placeholder=${proto === "wg" ? "wg1" : proto === "wdtt" ? "wdtt1" : proto === "csqtt" ? "csqtt1" : "awg1"} autocomplete="off"/>${ghost ? html`<div class="hint">${T("Fixed — must match the peers that reference it.")}</div>` : nameErr ? html`<div class="hint err">${nameErr}</div>` : null}</div>
        <div class="field"><label>${T("Tunnel subnet (CIDR)")}</label><input class=${_subConflict ? "bad" : ""} value=${subnet} onInput=${e => setSubnet(e.target.value)} placeholder="10.8.0.0/24" autocomplete="off"/>${_subConflict ? html`<div class="hint err">${subnetTaken(_subConflict.iface, Store.nodeName(_subConflict.node))}</div>` : null}</div>
      </div>
      ${(!isWdtt && !isCsqtt) ? html`<div class="row2">
        <div class="field"><label>${T("Endpoint host / IP")}</label>
          <${IpPicker} ips=${ips} sel=${hostSel} setSel=${setHostSel} custom=${hostCustom} setCustom=${setHostCustom} placeholder=${T("vpn.xyz.com or 203.0.113.7")}/>
          <div class="hint">${T("What clients dial")}</div></div>
        <div class="field"><label>${T("Listen port")}</label><input class=${pperr ? "bad" : ""} value=${port} onInput=${e => setPort(e.target.value)} placeholder="51820"/>${pperr ? html`<div class="hint err">${pperr}</div>` : null}</div>
      </div>` : null}
      ${isCsqtt ? html`<div class="row2">
        <div class="field"><label>${T("Endpoint host / IP")}</label>
          <${IpPicker} ips=${ips} sel=${hostSel} setSel=${setHostSel} custom=${hostCustom} setCustom=${setHostCustom} placeholder=${T("vpn.xyz.com or 203.0.113.7")}/>
          <div class="hint">${T("What clients dial (over the VK relay)")}</div></div>
        <div class="field"><label>${T("Listen port")}</label><input class=${pperr ? "bad" : ""} value=${port} onInput=${e => setPort(e.target.value)} placeholder="46000"/>${pperr ? html`<div class="hint err">${pperr}</div>` : html`<div class="hint">${T("UDP DTLS listen (outside)")}</div>`}</div>
      </div>
      <div class="row2">
        <div class="field"><label>${T("Max users")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— optional")}</span></label><input value=${maxPw} onInput=${e => setMaxPw(e.target.value)} placeholder="500"/><div class="hint">${T("Cap on simultaneous access passwords · blank = 500")}</div></div>
        <div class="field"></div>
      </div>` : null}
      ${isBridge ? html`<div class="notice warn" style="margin:-6px 0 16px"><${Ic} i="warn"/><span>${Trich("This docker node uses `bridge` networking — after creating you must publish this port in the node's `docker-compose.yml` ({ports}) and `up -d`, or clients can't reach it. (A host-networking node needs none of this.)", { ports: 'ports: "' + (port || "PORT") + ":" + (port || "PORT") + '/udp"' })}</span></div>` : null}
      ${isWdtt ? html`<div class="row2">
        <div class="field"><label>${T("Server fork")}</label><select value=${fork} onChange=${e => setFork(e.target.value)}>${_wdttForks.map(f => html`<option value=${f.id}>${f.label}</option>`)}</select><div class="hint">${T("Which WDTT server implements this instance")}</div></div>
        <div class="field"><label>${T("Endpoint host / IP")}</label>
          <${IpPicker} ips=${ips} sel=${hostSel} setSel=${setHostSel} custom=${hostCustom} setCustom=${setHostCustom} placeholder=${T("vpn.xyz.com or 203.0.113.7")}/>
          <div class="hint">${T("What clients dial")}</div></div>
      </div>
      <div class="row2">
        <div class="field"><label>${T("Listen port")}</label><input class=${pperr ? "bad" : ""} value=${port} onInput=${e => setPort(e.target.value)} placeholder="51820"/>${pperr ? html`<div class="hint err">${pperr}</div>` : html`<div class="hint">${T("DTLS listen (outside)")}</div>`}</div>
        <div class="field"><label>${T("Internal WG port")}</label><input class=${wgperr ? "bad" : ""} value=${wgPort} onInput=${e => setWgPort(e.target.value)} placeholder="56001"/>${wgperr ? html`<div class="hint err">${wgperr}</div>` : html`<div class="hint">${T("Loopback userspace-WG port (server-internal)")}</div>`}</div>
      </div>` : null}
      <${Fragment}><${EgressPicker} node=${node} value=${eg} onChange=${setEg} noRules=${true}/>
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
      ${(!isWdtt && !isCsqtt) ? html`<${Disclosure} title=${T("Advanced settings")} summary=${T("MTU · keepalive · DNS")}
        open=${disc.advanced} onToggle=${() => tog("advanced")}>
        <div class="row2">
          <div class="field"><label>MTU</label><input value=${mtu} onInput=${e => setMtu(e.target.value)} placeholder="1280"/><div class="hint">${T("Blank = 1280")}</div></div>
          <div class="field"><label>${T("Persistent keepalive (s)")}</label><input value=${ka} onInput=${e => setKa(e.target.value)} placeholder="25"/><div class="hint">${T("0 disables · blank = 25")}</div></div>
        </div>
        <div class="field"><label>DNS</label><input value=${dns} onInput=${e => setDns(e.target.value)} placeholder="1.1.1.1"/><div class="hint">${T("Comma-separated")}</div></div>
      <//>` : null}<//>
    <//>`}
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}
// Delete an interface — destructive, so gated behind typing "DELETE <iface>" (case-sensitive).
export function DeleteIfaceSheet({ node, iface }) {
  const [txt, setTxt] = useState(""); const [busy, setBusy] = useState(false);
  const phrase = T("DELETE {v1}", { v1: iface });
  const ok = txt === phrase;
  const del = async () => {
    if (!ok || busy) return;
    setBusy(true);
    const r = await api.ifaceDelete({ node, iface });
    if (!r.ok) { setBusy(false); return toast(srvText(r) || T("Failed to delete interface."), "err"); }
    const _m = Store.ifaceMeta(node, iface) || {};   // capture type/rows now — see the WDTT delete above
    Store.ifaceGone[node + "|" + iface] = { at: Date.now(),
      type: (_m.awg_params && Object.keys(_m.awg_params).length) ? "awg" : "wg",
      listen: _m.endpoint || ((_m.address || "").split("/")[0] + (_m.listen_port ? ":" + _m.listen_port : "")), subnet: _m.subnet || "" };
    closeAllModals(); await Store.poll();   // iface is gone → close this + the editor behind it
    toast(T("Interface deletion requested — the node tears it down on its next sync."), "ok");
    go("#/node/" + encodeURIComponent(node));   // this interface's page is going away
  };
  return html`<${Sheet} title=${T("Delete interface · {v1}", { v1: iface })}
    foot=${footRow({ onCancel: closeModal, danger: true, disabled: !ok || busy, onAction: del, action: T("Delete interface") })}>
    <div class="notice warn"><${Ic} i="warn"/><span>${Trich("This permanently tears down *{iface}* on the node: the interface goes *down*, its *.conf and server key are removed*, and *every peer on this interface is destroyed*. Peers deployed only here are deleted from the panel and their configs/QRs stop working. This can't be undone.", { iface })}</span></div>
    <div class="field"><label>${typeToConfirm(phrase)}</label><input autofocus value=${txt} onInput=${e => setTxt(e.target.value)} placeholder=${phrase} autocomplete="off" spellcheck="false"/></div>
  <//>`;
}
// start/restart with an inline progress lifecycle on the interface card: busy tag (button hidden)
// → green "started/restarted" 5s or red "failed" 10s (button back). verb = "start" (down) | "restart".
export async function startOrRestartIface(node, iface, verb) {
  const key = node + "|" + iface;
  Store.ifaceOp[key] = { verb, phase: "busy", started: Date.now() }; Store.apply();
  const m = verb === "stop" ? "ifaceStop" : verb === "start" ? "ifaceStart" : "ifaceRestart";
  const r = await api[m]({ node, iface });
  if (!r.ok) {
    Store.ifaceOp[key] = { verb, phase: "fail", until: Date.now() + 10000, err: srvText(r) || T("request failed") };
    Store.apply(); setTimeout(() => Store.apply(), 10100); return;
  }
  await Store.poll();   // queued on the node; trackIfaceOps() watches for completion each poll
}
export function openEditIface(node, iface) { openModal(html`<${EditIfaceSheet} node=${node} iface=${iface}/>`); }
export function openConnectionEdit(node, iface) { openModal(html`<${ConnectionEditSheet} node=${node} iface=${iface}/>`); }
// A node↔node mesh link (system interface). Mesh-managed (no create/delete/egress here) — mostly status;
// the only operator knob is whether this link can carry forwarded user traffic (reserved for Phase 2).
export function ConnectionEditSheet({ node, iface }) {
  useStore();
  const meta = Store.ifaceMeta(node, iface) || {};
  const peer = meta.link_node;
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const prec = (Store.nodes || []).find(n => n.id === peer) || {};
  const [dialSrc, setDialSrc] = useState(meta.dial_src || "");
  const [dialEp, setDialEp] = useState(meta.dial_endpoint || "");
  const nodeDown = nodeStale(node) || inProc(nrec.proc_status);   // node not reporting / mid re-install → can't apply a dial change
  const lk = nodeStale(node) ? "down" : (meta.handshake_age == null ? "connecting" : (meta.handshake_age < 180 ? "up" : "down"));
  const lkLabel = { up: "connected", connecting: "connecting", down: "down" }[lk];
  const proto = (meta.awg_params && Object.keys(meta.awg_params).length) ? "awg" : "wg";
    const Cell = (l, v) => html`<div class="conn-cell"><span class="cl">${l}</span><span class="cv">${v}</span></div>`;
  const saveDial = () => {
    closeModal();
    mutate({
      key: "conn:" + node + "|" + peer,
      patch: () => {},
      call: () => api.connectionUpdate({ node, peer, dial_src: dialSrc, dial_endpoint: dialEp }),
    });
  };
  const connDirty = dialSrc !== (meta.dial_src || "") || dialEp !== (meta.dial_endpoint || "");   // enable Save only when the dial fields changed
  // user interfaces on THIS node whose traffic is forwarded out through this link (egress → peer)
  const allMeta = Store.describe[node] || {};
  const carried = Object.keys(allMeta).filter(k => !allMeta[k].system
    && allMeta[k].egress_mode === "forward" && allMeta[k].egress_node === peer)
    .map(k => ({ iface: k, subnet: allMeta[k].subnet, ip: allMeta[k].egress_ip }));
  // interfaces that SMART-route some destination categories out through this link (not the whole iface)
  const _listTitle = Object.fromEntries((Store.panelSettings?.custom_lists || []).map(l => [l.id, l.title]));
  const smartCarried = Object.keys(allMeta).filter(k => !allMeta[k].system && allMeta[k].egress_mode === "smart")
    .map(k => ({ iface: k, cats: (allMeta[k].routing || []).filter(r => r.action === "exit" && r.node === peer)
      .map(r => r.category === "custom" ? [...(r.domains || []), ...(r.cidrs || [])].join(", ") || "custom" : (SMART_CAT_LABEL[r.category] || _listTitle[r.category] || r.category)) }))
    .filter(x => x.cats.length);
  const ifBadge = k => html`<span class=${"tg tg-" + ((allMeta[k].awg_params && Object.keys(allMeta[k].awg_params).length) ? "awg" : "wg")}>${k}</span>`;
  const peerNm = html`<b style=${"color:" + Store.nodeColor(peer)}>${Store.nodeName(peer)}</b>`;
  return html`<${Sheet} title=${T("Connection to {v1}", { v1: Store.nodeName(peer) })} width=${680} onClose=${closeModal}
      foot=${footRow({ onCancel: closeModal, disabled: nodeDown || !connDirty, title: nodeDown ? T("{v1} isn't reporting — reconnect it before changing this link", { v1: Store.nodeName(node) }) : (!connDirty ? T("No changes to save") : ""), onAction: saveDial, action: T("Save") })}>
    <div class="conncard">
      <div class="conncard-top">
        <span class=${"iftype " + proto}>${T("System {v1}", { v1: proto.toUpperCase() })}</span>
        <span class=${"lkpill " + lk}><span class=${"lkdot " + lk}></span>${lkLabel}</span>
      </div>
      <div class="conn-grid">
        ${Cell(T("Node"), html`<a href=${"#/node/" + encodeURIComponent(peer)} onClick=${closeModal}>${Store.nodeName(peer)}</a>`)}
        ${Cell(T("This end"), meta.address || "—")}
        ${Cell("Endpoint", meta.peer_endpoint || T("— (not dialed yet)"))}
        ${Cell("Rate", rateCell(meta.rx_speed, meta.tx_speed))}
        ${meta.rx_bytes != null || meta.tx_bytes != null ? Cell("Total", xferCell(...dlul(meta.rx_bytes, meta.tx_bytes))) : null}
        ${Cell(T("Last handshake"), meta.handshake_age != null ? T("{v1} ago", { v1: seen(meta.handshake_age) }) : "—")}
      </div>
    </div>
    <div style="margin-top:12px"><${RangedHistory} node=${node} kind="throughput" h=${60} fetch=${r => api.meshSeries(node, peer, r).then(x => x && x.ok ? x.data : {})}/></div>
    <div class="row2" style="margin-top:14px">
      <div class="field"><label>${T("Dial source IP")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— {node}'s IP", { node: Store.nodeName(node) })}</span></label>
        <${NodeIpPick} ips=${nrec.ips || []} value=${dialSrc} onChange=${setDialSrc} auto=${T("Auto (default route)")}/></div>
      <div class="field"><label>${T("Dial endpoint IP")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— {node}'s IP", { node: Store.nodeName(peer) })}</span></label>
        <${NodeIpPick} ips=${prec.ips || []} value=${dialEp} onChange=${setDialEp} auto=${T("Auto ({v1}'s ingress)", { v1: Store.nodeName(peer) })}/></div>
    </div>
    <div class="hint" style="margin-top:-4px">${Trich("Per-connection overrides: which of *{a}*'s IPs dials out, and which of *{b}*'s IPs it dials to (overriding {b}'s default ingress). Changing the endpoint re-connects this link automatically. Neither changes how routed traffic appears externally — that's the exit node's egress IP", { a: Store.nodeName(node), b: Store.nodeName(peer) })}.</div>
    ${(carried.length || smartCarried.length) ? html`<div style="margin-top:16px">
      ${carried.length ? html`<div class="fwd-head"><span class="egb egb-cascade"><${Ic} i="cascade"/>${T("tag|cascade")}</span><span class="fwd-to">to</span>${peerNm}</div>
        <div class="fwd-ifaces">${carried.map(c => ifBadge(c.iface))}</div>` : null}
      ${smartCarried.length ? html`<div class="fwd-head" style=${carried.length ? "margin-top:14px" : ""}><span class="egb egb-smart"><${Ic} i="cascade"/>${T("smart cascade")}</span><span class="fwd-to">to</span>${peerNm}</div>
        <div class="fwd-list">${smartCarried.map(s => html`<div class="fwd-row">${ifBadge(s.iface)} <span class="faint">(${s.cats.map(c => SMART_CAT_LABEL[c] || c).join(", ")})</span></div>`)}</div>` : null}
      <div class="hint" style="margin-top:16px">${Trich("These interfaces' client traffic exits the fleet through *{node}*{smart}.", { node: Store.nodeName(peer), smart: smartCarried.length ? T(" — smart-routed by destination") : "" })}</div>
    </div>` : null}
    <div class="hint" style="margin-top:14px">${Trich("This is a panel-managed mesh link to *{node}*. It's created and torn down automatically as nodes are added or removed. To route a user interface's traffic out through this node, set that interface's egress to *Forward to {node}*.", { node: Store.nodeName(peer) })}</div>
  <//>`;
}
export function EditIfaceSheet({ node, iface }) {
  useStore();   // re-render on each poll so live meta (drift appearing/clearing, cmd_errors) stays current while the sheet is open
  const meta = Store.ifaceMeta(node, iface) || {};
  const emode = ((Store.nodes || []).find(n => n.id === node) || {}).routing_mode || "kernel";   // for smart-rule validation (kernel = IP-only)
  const ep = meta.endpoint || "";
  const epHost = ep.includes(":") ? ep.slice(0, ep.lastIndexOf(":")) : ep;
  const [host, setHost] = useState(epHost);
  const [port, setPort] = useState(String(meta.desired_port || meta.listen_port || ""));
  const iperr = portErrMsg(node, port, [meta.listen_port, meta.desired_port]);   // live port-collision check (this iface's own port doesn't count)
  const [dns, setDns] = useState((meta.dns || []).join(", "));
  const [mtu, setMtu] = useState(String(meta.mtu || 1280));
  const [ka, setKa] = useState(String(meta.keepalive || 25));
  const [disc, setDisc] = useState({ routing: true, filters: false, advanced: false });   // collapsible sections; Routing opens by default (only shown in Smart mode)
  const tog = k => setDisc(d => ({ ...d, [k]: !d[k] }));
  const [driftDone, setDriftDone] = useState(null);   // after resolving a server-key drift: "adopted" | "restoring" — the warning becomes a terminal confirmation (no buttons) until the drift clears on a later sync
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const [eg, setEg] = useState(() => egressInit(meta));
  const [blk, setBlk] = useState(() => [...(meta.block || [])]);   // active block-category ids (Block-traffic section)
  const isAwg = !!(meta.awg_params && Object.keys(meta.awg_params).length);
  const [awg, setAwg] = useState(() => Object.assign({}, meta.awg_params || {}));
  const setAwgK = (k, v) => setAwg(a => ({ ...a, [k]: v }));
  const ist = (((Store.stats[node] || {}).interfaces || {})[iface] || {});
  const istopped = !!ist.stopped;            // operator stopped it (not a failure)
  const idown = !istopped && ist.down;       // genuinely down
  const notup = !!idown || istopped;         // either way: Save brings it up; footer offers Start
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const doSave = async () => {
    const body = { node, iface, endpoint_host: host.trim(), listen_port: port.trim(), dns: dns.trim(), mtu: mtu.trim(), keepalive: ka.trim(), block: blk, ...egressBody(eg) };
    if (isAwg) body.awg_params = AWG_ORDER.reduce((o, k) => { const v = String(awg[k] == null ? "" : awg[k]).trim(); if (v) o[k] = v; return o; }, {});
    // down → "start" (real bring-up); up → "apply" live (no restart). Optimistic: flip the lifecycle +
    // close the modal(s) NOW so the detail page shows starting/applying the instant Save is pressed.
    const key = node + "|" + iface, verb = notup ? "start" : "apply";
    Store.ifaceOp[key] = { verb, phase: "busy", started: Date.now() };
    Store.apply(); closeAllModals();
    const fail = (m) => { Store.ifaceOp[key] = { verb, phase: "fail", until: Date.now() + 5000, err: m }; Store.apply(); setTimeout(() => Store.apply(), 5100); };
    const r = await api.ifaceUpdate(body);
    if (!r.ok) return fail(srvText(r) || T("save failed"));
    if (notup) { const r2 = await api.ifaceStart({ node, iface }); if (!r2.ok) return fail(srvText(r2) || T("start failed")); }
    await Store.poll();   // trackIfaceOps drives busy → done
    toast(notup ? T("Interface saved — starting…") : T("Interface saved."), "ok");
  };
  const save = () => {
    const ee = egressError(eg, emode); if (ee) return toast(ee, "err");
    const portChanged = port.trim() !== String(meta.desired_port || meta.listen_port || "");
    const epChanged = host.trim() !== epHost;
    if (portChanged || epChanged) {           // client-breaking → confirm first (the editor stays open behind it)
      const what = portChanged && epChanged ? T("endpoint and listen port") : portChanged ? T("listen port") : "endpoint";
      pushModal(html`<${ConfirmSheet} title=${T("Change {what}?", { what })} confirmLabel=${T("Apply change")} warn=${true}
        body=${T("This reconfigures the interface on the node. Existing peers will NOT be able to connect using their old configs — you'll need to re-issue and re-distribute the QR codes. The interface's keys and peers are kept.")}
        note=${html`<${SubAutoNote}/>`}
        onConfirm=${() => { doSave(); }}/>`);
      return;
    }
    doSave();
  };
  // enable Save only when something would change — mirror doSave()'s body; a down/stopped iface always allows Save (= bring-up)
  const _ifBody = { endpoint_host: host.trim(), listen_port: port.trim(), dns: dns.trim(), mtu: mtu.trim(), keepalive: ka.trim(), ...egressBody(eg) };
  const _ifOrig = { endpoint_host: epHost, listen_port: String(meta.desired_port || meta.listen_port || ""), dns: (meta.dns || []).join(", "), mtu: String(meta.mtu || 1280), keepalive: String(meta.keepalive || 25), ...egressBody(egressInit(meta)) };
  const _awgTrim = src => AWG_ORDER.reduce((o, k) => { const v = String((src || {})[k] == null ? "" : (src || {})[k]).trim(); if (v) o[k] = v; return o; }, {});
  const ifaceDirty = notup
    || JSON.stringify(_ifBody) !== JSON.stringify(_ifOrig)
    || JSON.stringify([...blk].sort()) !== JSON.stringify([...(meta.block || [])].sort())
    || (isAwg && JSON.stringify(_awgTrim(awg)) !== JSON.stringify(_awgTrim(meta.awg_params)));
  return html`<${Sheet} title=${T("Edit {v1} interface · {v2}", { v1: kindOf(node, iface).toUpperCase(), v2: iface })} width=${720}
    foot=${html`<${Fragment}><button class="btn btn-ghost danger" onClick=${() => pushModal(html`<${DeleteIfaceSheet} node=${node} iface=${iface}/>`)}><${Ic} i="trash"/>${T("Delete")}</button>
      ${notup
        ? html`<button class="btn btn-ghost" style="margin-left:8px" disabled=${busy} title=${T("Bring this interface up on the node")} onClick=${() => { closeModal(); startOrRestartIface(node, iface, "start"); }}><${Ic} i="play"/> ${T("Start service")}</button>`
        : html`<${Fragment}><button class="btn btn-ghost" style="margin-left:8px" disabled=${busy} title=${T("Take this interface down on the node (stays down until started)")} onClick=${() => { closeModal(); startOrRestartIface(node, iface, "stop"); }}><${Ic} i="stop"/> ${T("Stop service")}</button><button class="btn btn-ghost" style="margin-left:8px" disabled=${busy} title=${T("Bounce this interface's service on the node (down then up)")} onClick=${() => { closeModal(); startOrRestartIface(node, iface, "restart"); }}><${Ic} i="refresh"/> ${T("Restart service")}</button><//>`}
      <span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>${T("Cancel")}</button><button class="btn btn-primary" disabled=${busy || !!egressError(eg, emode) || !!iperr || !ifaceDirty} title=${iperr || egressError(eg, emode) || (!ifaceDirty ? T("No changes to save") : "")} onClick=${save}>${T("Save")}</button></>`}>
    <div class="iface-intro"><div>${Trich("Changing the *endpoint* or *port* will break the existing clients' connections; you will need to re-distribute the configs / QR codes.")}</div></div>
    ${idown ? html`<div class="notice warn"><${Ic} i="warn"/><span>${Trich("This interface is *down* on the node. Change the *Listen port* to a free one and *Save* — the panel will write the new port and restart the interface to bring it up.")}</span></div>` : null}
    ${((meta.drift && meta.drift.public_key) || driftDone) ? (() => {
      // Once the operator acts, this area becomes a terminal confirmation (no buttons), kept for the life of the
      // sheet via driftDone so the stale Adopt/Restore buttons never linger. ADOPT is instant (panel-side) → one
      // terminal "adopted". RESTORE is two-phase (request → node reverts on its next sync) → restoring →
      // restored (drift cleared) OR restore-failed (the node reported an error via cmd_errors — retry below).
      const rerr = driftDone === "restoring" ? (nrec.cmd_errors || {})[iface] : null;
      if (driftDone === "adopted") return html`<div class="notice ok"><${Ic} i="check"/><span>${Trich("*New server key adopted.* Re-issue and re-distribute the QR codes / configs — *subscribed users update automatically*.")}</span></div>`;
      if (driftDone === "restoring" && !rerr) {
        return (meta.drift && meta.drift.public_key)
          ? html`<div class="notice ok"><${Ic} i="check"/><span>${Trich("*Restoring the original key…* The node reverts to its backed-up key on its next sync — existing clients keep working, no re-distribution.")}</span></div>`
          : html`<div class="notice ok"><${Ic} i="check"/><span>${Trich("*Original key restored.* The node reverted to its backed-up key — existing clients keep working, no re-distribution needed.")}</span></div>`;
      }
      // else: the drift warning + buttons — also the RESTORE-FAILED retry surface (driftDone==="restoring" && rerr).
      // Restore only helps if the node's key BACKUP is the blessed key. `drift_restorable === false` means the
      // node reported a backup that can't restore it (a re-created node whose backup IS the new key) → hide
      // Restore, steer to Adopt. Unknown (old node not reporting a backup pubkey) → keep offering Restore.
      const canRestore = meta.drift_restorable !== false;
      const restoreAct = html`<div class="kd-act">
        <button type="button" class="kd-btn kd-restore" onClick=${async () => { const r = await api.ifaceRestore({ node, iface, key: "public_key" }); if (!r.ok) return toast(srvText(r) || T("Failed"), "err"); setDriftDone("restoring"); await Store.poll(); openConfirm({ title: T("Restoring the original key"), confirmLabel: T("Got it"), body: T("The node is reverting this interface to its backed-up original server key on its next sync. Existing clients keep working — no re-distribution needed.") }); }}>${T("Restore original key")}</button>
        <span class="faint kd-hint">${T("Reverts to the backed-up key — existing clients keep working, no re-distribution.")}</span>
      </div>`;
      const adoptAct = html`<div class="kd-act">
        <button type="button" class="kd-btn kd-adopt" onClick=${() => pushModal(html`<${ConfirmSheet} title=${T("Adopt the new server key?")} confirmLabel=${T("Adopt new key")} warn=${true} body=${T("Every client on this interface will stop connecting with their current config. You must re-issue and re-distribute every QR code / config. The original key is discarded.")} onConfirm=${async () => { const r = await api.ifaceAdopt({ node, iface, key: "public_key" }); if (!r.ok) return toast(srvText(r) || T("Failed"), "err"); setDriftDone("adopted"); await Store.poll(); openModal(html`<${ConfirmSheet} title=${T("New server key adopted")} confirmLabel=${T("Got it")} note=${html`<${SubAutoNote}/>`} body=${T("The node's new server key is now the panel's key for this interface. Every client's existing config / QR for this interface has stopped working — re-issue and re-distribute the new QR codes / configs to them.")}/>`); }}/>`)}>${T("Adopt new key")}</button>
        <span class="faint kd-hint">${canRestore ? T("Accept the node's new key — you'll re-distribute every QR.") : T("The node was re-created and no longer holds the original key, so Restore can't recover it — Adopt is the only option. You'll re-distribute every QR.")}</span>
      </div>`;
      return html`<div class="notice warn">
        <${Ic} i="warn"/><span>${rerr
          ? restoreFailed(rerr)
          : html`${Trich("*Server key changed on the node.* This interface's server keypair was rotated directly on the server, so *every client's existing config / QR for this interface no longer connects*.")} ${canRestore ? T("The node kept a backup of the original key.") : Trich("*The node no longer holds the original key* (it was re-created), so it can't be restored — only adopted.")}`}
          <div class=${"keydrift-acts" + (canRestore ? "" : " one")}>
            ${canRestore ? restoreAct : null}
            ${adoptAct}
          </div>
        </span></div>`;
    })() : null}
    ${Object.entries(meta.drift || {}).filter(([k]) => k !== "public_key").length ? html`<div class="notice warn">
      <${Ic} i="warn"/><span>${Trich("*Edited directly on the server.* The panel paused pushing these so your change survives — Adopt to keep the server value, or Restore to re-apply the panel's:")}
      ${Object.entries(meta.drift).filter(([k]) => k !== "public_key").map(([k, v]) => html`<div style="margin-top:7px"><span class="mono">${k === "awg_params" ? T("AWG params") : k}</span> ${T("on node =")} <span class="mono">${k === "awg_params" ? Object.entries(v).map(([a, b]) => a + "=" + b).join(" ") : v}</span>
        <button type="button" class="linkbtn" style="margin-left:8px" onClick=${async () => { const r = await api.ifaceAdopt({ node, iface, key: k }); if (!r.ok) return toast(srvText(r) || T("Failed"), "err"); closeModal(); await Store.poll(); toast(T("Adopted the server value."), "ok"); }}>${T("Adopt")}</button>
        · <button type="button" class="linkbtn" onClick=${async () => { const r = await api.ifaceRestore({ node, iface, key: k }); if (!r.ok) return toast(srvText(r) || T("Failed"), "err"); closeModal(); await Store.poll(); toast(T("Restoring the panel value on the next sync."), "ok"); }}>${T("Restore panel value")}</button></div>`)}
      </span></div>` : null}
    <div class="field ipk-field subnet-row"><label>${T("Host tunnel IP")}</label><span class="ipk-val"><b>${(meta.address || "").split("/")[0] || meta.subnet || "—"}</b> <span class="faint">${T("(set at creation — delete & recreate to change)")}</span></span></div>
    <div class="row2">
      <div class="field"><label>${T("Endpoint host / IP")}</label>
        <${NodeIpPick} ips=${nrec.ips || []} value=${host} onChange=${setHost} auto=${T("Auto (node's detected address)")} customPlaceholder="IP or hostname — e.g. vpn.example.com"/>
        <div class="hint">${T("What clients dial — config-facing only")}</div></div>
      <div class="field"><label>${T("Listen port")}</label><input class=${iperr ? "bad" : ""} value=${port} onInput=${e => setPort(e.target.value)} placeholder=${String(meta.listen_port || "")}/>${iperr ? html`<div class="hint err">${iperr}</div>` : html`<div class="hint">${T("Applied to the node (currently {v1})", { v1: meta.listen_port || "—" })}</div>`}</div>
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
    <${Disclosure} title=${T("Advanced settings")} summary=${T("MTU · keepalive · DNS") + (isAwg ? " · AWG" : "")}
      open=${disc.advanced} onToggle=${() => tog("advanced")}>
      <div class="row2">
        <div class="field"><label>MTU</label><input value=${mtu} onInput=${e => setMtu(e.target.value)} placeholder="1280"/><div class="hint">${T("Default for new peers")}</div></div>
        <div class="field"><label>${T("Persistent keepalive (s)")}</label><input value=${ka} onInput=${e => setKa(e.target.value)} placeholder="25"/><div class="hint">${T("0 disables · blank = 25")}</div></div>
      </div>
      <div class="field"><label>DNS</label><input value=${dns} onInput=${e => setDns(e.target.value)} placeholder=${T("https://8.8.8.8/dns-query, 1.1.1.1")}/><div class="hint">${T("Comma-separated")}</div></div>
      ${isAwg ? html`<div class="field"><label>${T("AmneziaWG parameters")}</label>
        <div class="hint" style="margin:0 0 8px">${T("Pushed to the node's interface and rendered into configs/QRs. Existing clients must re-import after a change.")}</div>
        <div class="awg-cols">${[["Jc", "Jmin", "Jmax"], ["S1", "S2", "S3", "S4"], ["H1", "H2", "H3", "H4"], ["I1", "I2", "I3", "I4", "I5"]].map(grp => html`<div class="awg-col">${grp.map(k => html`<label class="awg-f"><span>${k}</span><input value=${awg[k] == null ? "" : awg[k]} onInput=${e => setAwgK(k, e.target.value)}/></label>`)}</div>`)}</div></div>` : null}
    <//>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}
