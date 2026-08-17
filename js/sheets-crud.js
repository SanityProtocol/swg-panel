/* sheets-crud.js — the create/edit dialogs for users, peers, targets and nodes.
 *
 * LAYER 7 (see docs/APP-JS-SPLIT-PLAN.md). Imported by the roster screens and by iface.js.
 *
 * These are where a peer is BORN: CreatePeerSheet mints the keypair in the browser (crypto.js), hands the
 * private key to the config and the QR, and sends the panel only a public key, an IP and a PSK. The same
 * TargetPicker drives create, add-target and edit, so one peer's several deployments stay one credential.
 */

import { T, Tsplit, plural, srvText } from "./i18n.js";
import { esc, tkey, V, BASE, seen, configErrors, orderedTargets, isPrimaryTarget, useStableOrder,
         isSelfContainedKind, ipOf, portOf, ipPickerVal } from "./util.js";
import { Store, api, bus, useStore } from "./store.js";
import { NODE_COLOR_DEFAULT, NODE_CREATE_DEFAULT, toThemed } from "./theme.js";
import { go } from "./router.js";
import { targetType, iTypeOf, kindOf, nodeStale, wdttOn, suggestIface, suggestSubnet, suggestPort,
         portHolder, portErrMsg, subnetFleetConflict, subnetServerAddr, cidrNet, ghostIface,
         turnProxiesFor, tgtXfer, tgtSeenAge } from "./model.js";
import { turnFork, turnColor, turnForkList } from "./turn-catalog.js";
import {
  Ic, ICON, Tag, Panel, Badge, Sheet, footRow, secTitle, SearchBox, Switch, Dropdown, Disclosure, autoGrow,
  IpPicker, NodeIpPick, Popover, Portal, toast, copy, mutate, openModal, pushModal, closeModal,
  closeAllModals, openConfirm, openChildOrRoot, ConfirmSheet, subjectBlocked, statusLabel, LogBody, RowError,
  useAnchoredList, goSettings, ThemedSwatch, modalDepth, rowSingle, rowDouble, rowNoSelect, rateCell,
  xferCell, gridStatusBadge, badgeWithReason, blockedReason, statusReason, dlul,
} from "./ui.js";
import {
  genKeys, genPSK, buildConf, parseFullConf, downloadConf, getConfig, configOverrides, QR, qrDataURL,
  subFeatureOn, subPublishOrPrompt, ensureVaultUnlocked, subSKCached, VaultPromptSheet, ensurePeerBlob,
  SubAutoNote, anySessionConf, subAutoGenIfEnabled, subReconcileUser,
} from "./crypto.js";
import {
  confirmDeletePeer, confirmUnassign, peerBlockBtn, userBlockBtn, PeerStatusLine, SubStatusLine,
  fmtDate, expiryInputVal, expiryFromInput, UserCombo, UserPicker, PrimaryToggle, assignPeer,
  confirmReassign, confirmCorrectDeployment, confirmRestoreDeployment, openRecreateRekey, rotatePeerKeys, PubTag,
} from "./peer-actions.js";
import { searchMatch, usersView, revealUser } from "./views.js";
import { turnEnabled, WDTT_COLOR, shownTitle } from "./turn.js";
import { openPeerConfigs } from "./peer-ui.js";
import { h, Fragment } from "preact";
import { useState, useEffect, useRef, useMemo } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// New user — identity, then optionally straight into adding peers (one per interface).
export function openCreateUser() { openModal(html`<${CreateUserSheet}/>`); }
export function CreateUserSheet() {
  const [name, setName] = useState(""); const [tag, setTag] = useState(""); const [note, setNote] = useState(""); const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const createUser = async () => {
    if (!name.trim()) { setMsg({ k: "err", t: T("Give the user a name.") }); return null; }
    setBusy(true); setMsg({ k: "work", t: "creating…" });
    const r = await api.userCreate({ name: name.trim(), tag: tag.trim(), note });
    setBusy(false);
    if (!r.ok) { setMsg({ k: "err", t: srvText(r) || T("couldn't create user") }); return null; }
    Store.recentlyCreated[r.data.id] = Date.now(); subAutoGenIfEnabled(r.data.id); await Store.poll();
    return r.data;
  };
  const stayExpanded = uid => { usersView.expanded[uid] = true; usersView.q = ""; usersView.page = 1; closeModal(); go("#/users"); };
  const createOnly = async () => { const u = await createUser(); if (u) stayExpanded(u.id); };
  const createAndAdd = async () => { const u = await createUser(); if (u) openModal(html`<${AddPeersSheet} userId=${u.id} userName=${u.name}/>`); };
  return html`<${Sheet} title=${T("New user")}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>${T("Cancel")}</button><button class="btn btn-ghost" disabled=${busy} onClick=${createOnly}>${T("Create only")}</button><button class="btn btn-primary" disabled=${busy} onClick=${createAndAdd}>${T("Add peers ▸")}</button></>`}>
    <div class="field"><label>${T("Name")}</label><input autofocus value=${name} onInput=${e => setName(e.target.value)} placeholder=${T("Alex")}/></div>
    <div class="field"><label>${T("Tag")}</label><input value=${tag} onInput=${e => setTag(e.target.value)} placeholder=${T("Friend")}/></div>
    <div class="field"><label>${T("Note")}</label><input value=${note} onInput=${e => setNote(e.target.value)} placeholder=${T("Uses iPhone and router")}/></div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

export function openAddPeers(userId, userName) { openModal(html`<${AddPeersSheet} userId=${userId} userName=${userName}/>`); }
// One peer as a bordered block: a deployment row per (node, iface) — status · title (once) · node · iface+address ·
// action. Multi-deployment peers stack their targets under one border with the PRIMARY tagged and backups beneath, so
// the set reads as one identity. `mode` picks the row action: "mine" unassigns (rotates the key), "free" assigns.
export function PeerBlockGrid({ peers, mode, act }) {
  useStore();
  const gridRef = useRef(null);
  const ids = peers.map(p => p.id).join(",");
  useEffect(() => {                                     // cap the grid at 7 peer blocks (styled scrollbar past that) + centre a just-added/moved peer
    const el = gridRef.current; if (!el) return;
    const kids = el.children;
    el.style.maxHeight = kids.length > 7 ? Math.ceil(kids[6].getBoundingClientRect().bottom - el.getBoundingClientRect().top) + "px" : "";
    const hot = peers.find(p => Store.recentlyCreated[p.id] && Date.now() - Store.recentlyCreated[p.id] < 2500);
    if (hot) requestAnimationFrame(() => { const n = el.querySelector('[data-pid="' + hot.id + '"]'); if (!n) return;
      const gr = el.getBoundingClientRect(), pr = n.getBoundingClientRect();
      el.scrollTo({ top: Math.max(0, el.scrollTop + (pr.top - gr.top) - (el.clientHeight - pr.height) / 2), behavior: "smooth" }); });
  }, [ids]);
  if (!peers.length) return html`<div class="pg2-empty">${mode === "mine" ? T("No peers assigned to this user yet.") : T("No unassigned peers to add.")}</div>`;
  return html`<div class="pg2" ref=${gridRef}>${peers.map(p => {
    const ts = orderedTargets(p.targets || []); const multi = ts.length > 1;
    const fresh = Store.recentlyCreated[p.id] && (Date.now() - Store.recentlyCreated[p.id] < 2500);   // reuse the users/peers-grid glow (recentlyCreated + pcreate)
    return html`<div key=${p.id} data-pid=${p.id} class=${"pg2-peer" + (fresh ? " pcreate" : "")}>${(ts.length ? ts : [{}]).map((t, i) => html`
      <div key=${tkey(t.node, t.iface)} class=${"pg2-dep clk" + (multi && i === 0 ? " primary" : "")} title=${T("Double-click for QR / configs")}
        onMouseDown=${rowNoSelect} onClick=${e => rowSingle(e, () => openPeerView(p.id, t.node, t.iface, true))} onDblClick=${e => rowDouble(e, () => openPeerConfigs(p, { child: true }))}>
        <span class="pg2-c pg2-st">${t.node ? gridStatusBadge(t, p) : null}</span>
        <span class="pg2-c pg2-title">${i === 0
          ? html`<${Fragment}><span class="pg2-nm">${(p.title || "").trim() || html`<span class="faint">${T("tag|untitled")}</span>`}</span>${multi ? html`<span class="pg2-rel primary">${T("Primary")}</span>` : null}<//>`
          : html`<span class="pg2-bk">${T("Backup")}</span>`}</span>
        <span class="pg2-c pg2-if">${t.node ? html`<${TargetFrontBadge} node=${t.node} iface=${t.iface}/><${Tag} kind=${targetType(t)} label=${targetType(t)}/><span class="pg2-ifn">${t.iface}</span><span class="pg2-ip">${String(t.ip || "").split("/")[0] || "—"}</span>` : null}</span>
        <span class="pg2-c pg2-ctl">${i === 0 ? html`<${Fragment}>${mode === "mine" ? html`<button type="button" class="pg2-act add" title=${T("Add or edit interface deployments")} onClick=${() => openAddTarget(p)}><${Ic} i="plus"/></button>` : null}<button type="button" class=${"pg2-act " + mode} title=${mode === "mine" ? T("Unassign from this user") : T("Assign to this user (keeps its key)")} onClick=${() => act(p)}><${Ic} i=${mode === "mine" ? "link" : "plus"}/></button><//>` : null}</span>
      </div>`)}</div>`;
  })}</div>`;
}
// Add peers to a user — two grids: the user's own peers (unassign) and the unassigned pool (assign, key kept). Both
// actions persist immediately (assign is non-destructive; unassign rotates the key, so it confirms). "Create fresh
// peer" opens the normal new-peer flow with this user locked in. No carousel, no staging, no Save.
export function AddPeersSheet({ userId, userName }) {
  useStore();
  const rep = p => orderedTargets(p.targets || [])[0] || {};
  const orderPeers = list => [...list].sort((a, b) =>
    (b.title ? 1 : 0) - (a.title ? 1 : 0) ||                              // named peers first (untitled sink to the bottom)
    String(a.title || "").localeCompare(String(b.title || "")) ||        // then alphabetical by title
    (Store.nodeName(rep(a).node) || "").localeCompare(Store.nodeName(rep(b).node) || "") ||
    String(rep(a).ip || "").localeCompare(String(rep(b).ip || ""), undefined, { numeric: true }));
  const mine = orderPeers(userId ? Store.peersOfUser(userId) : []);
  const free = orderPeers(Store.unassignedPeers());

  const doAssign = p => { Store.recentlyCreated[p.id] = Date.now(); return mutate({ key: "peer:" + p.id,   // keep the key, just link — publish the blob (prompts to unlock if locked)
    patch: s => { const pp = s.roster.peers[p.id]; if (pp) pp.user_id = userId; },
    call: () => api.peerUpdate({ peer_id: p.id, user_id: userId }),
    onOk: () => subReconcileUser(userId) }); };
  const doUnassign = p => pushModal(html`<${ConfirmSheet} title=${T("Unassign peer") + (userName ? " · " + userName : "")} confirmLabel=${T("Unassign")} danger=${true}
    body=${html`Revoke <b>${(p.title || "").trim() || T("this peer")}</b> from ${userName || T("the user")}? Access is cut immediately and the key changes — re-adding later needs a fresh QR / config.`}
    onConfirm=${() => { Store.recentlyCreated[p.id] = Date.now(); mutate({ key: "peer:" + p.id,
      patch: s => { const pp = s.roster.peers[p.id]; if (pp) pp.user_id = null; },
      call: () => api.peerUnassign({ peer_id: p.id }),
      onOk: () => { delete Store.sessionConfigs[p.pubkey]; Store.configEpoch++; } }); }}/>`);
  const createFresh = () => openCreatePeer({ user_id: userId, userName, lockUser: true }, true);

  return html`<${Sheet} title=${userName ? T("Add peers · {v1}", { v1: userName }) : T("Add peers")} width=${720}>
    <div class="pg2-sec">
      <div class="pg2-hdr"><label>${T("This user’s peers")}</label><span class="grow"></span>
        <button class="btn btn-mini pg2-fresh" onClick=${createFresh}><${Ic} i="plus"/> ${T("Create fresh peer")}</button></div>
      <${PeerBlockGrid} peers=${mine} mode="mine" act=${doUnassign}/>
    </div>
    <div class="pg2-sec">
      <div class="pg2-hdr"><label>${T("Unassigned peers")}</label></div>
      <${PeerBlockGrid} peers=${free} mode="free" act=${doAssign}/>
    </div>
  <//>`;
}

// All deployable (node, iface) targets known from the consolidated state.
export function allTargets() {
  const out = [];
  for (const node of Object.keys(Store.describe)) for (const iface of Object.keys(Store.describe[node] || {}))
    if (!Store.ifaceIsSystem(node, iface)) out.push({ node, iface });   // never offer a mesh link (swg_*) as a peer target
  // WDTT servers own their interface, which isn't a panel-managed WG iface (so it's absent from `describe`) — add
  // each from the node's WDTT readback so it's selectable as a (keyless) peer target.
  for (const node of Object.keys(Store.stats || {})) for (const w of ((Store.stats[node] || {}).wdtt || []))
    if (w && w.iface && !out.some(t => t.node === node && t.iface === w.iface)) out.push({ node, iface: w.iface });
  for (const node of Object.keys(Store.stats || {})) for (const c of ((Store.stats[node] || {}).csqtt || []))
    if (c && c.iface && !out.some(t => t.node === node && t.iface === c.iface)) out.push({ node, iface: c.iface });
  return out;
}

// What sits IN FRONT of a target interface, as one badge — so a targets grid says what a peer will actually
// connect through, not just which interface it lands on. Two cases, never both:
//   WDTT  — the server owns the interface: its operator title, else the fork name, in that fork's colour.
//   turn  — one proxy: its title, else the fork name, in that fork's colour. SEVERAL: a neutral "turn" badge
//           (naming one of several would be a lie), with the full list on hover.
// Nothing in front → nothing rendered; a plain wg/awg interface keeps the grid quiet.
export function TargetFrontBadge({ node, iface }) {
  if (!node || !iface) return null;
  if (kindOf(node, iface, null) === "wdtt") {
    const nrec = (Store.nodes || []).find(x => x.id === node) || {};
    const cfg = (nrec.wdtt_cfg || {})[iface] || {};
    const live = ((Store.stats[node] || {}).wdtt || []).find(w => w && w.iface === iface) || {};
    const fork = cfg.fork || live.fork || "";
    const label = shownTitle("w|" + node + "|" + iface, String(cfg.title || live.title || "").trim()) || fork;
    if (!label) return null;
    const col = turnColor(fork) || WDTT_COLOR;
    return html`<span class="tg tgt-front" style=${"--tgc:" + col} title=${T("WDTT server") + (fork ? " · " + fork : "")}>${label}</span>`;
  }
  const tps = turnProxiesFor(node, iface);
  if (!tps.length) return null;
  const one = t => shownTitle("t|" + node + "|" + t.service, t.title) || turnFork(t.service);
  if (tps.length === 1) {
    const f = turnFork(tps[0].service);
    return html`<span class="tg tgt-front" style=${"--tgc:" + (turnColor(f) || "var(--turn)")} title=${"Turn-proxy" + (f ? " · " + f : "")}>${one(tps[0])}</span>`;
  }
  return html`<${Popover} hoverOnly cls="tgt-frontpop" popCls="tgt-frontbub"
    trigger=${html`<span class="tg tgt-front tgt-front-many" title=${T("{v1} turn-proxies forward to this interface", { v1: tps.length })}>${T("val|turn")} <b>${tps.length}</b></span>`}>
    <div class="tgt-frontlist"><span class="tgt-frontlbl">${T("Turn-proxies on this interface")}</span>
      ${tps.map(t => { const f = turnFork(t.service);
        return html`<span class="tg tgt-front" key=${t.service} style=${"--tgc:" + (turnColor(f) || "var(--turn)")}>${one(t)}</span>`; })}</div>
  <//>`;
}

// Reusable (node,iface) picker with per-target IP allocation. `exclude` is a Set of tkeys
// to hide (interfaces a user is already on); `onChange` receives the chosen target list
// [{node,iface,ip,ipHint}]. Used by the create-peer, create-user and add-peers flows.
export function TargetPicker({ prefill, exclude, onChange, initial, pubPeer }) {
  // `pubPeer` (Targets sheet only): rows that are ALREADY deployments of that peer get their protocol tag as a
  // publish switch. A row you haven't ticked yet is a candidate — there is nothing of it to publish, so it stays
  // a plain tag.
  const pubHave = useMemo(() => new Set(((pubPeer && pubPeer.targets) || []).map(t => tkey(t.node, t.iface))),
                          [pubPeer && pubPeer.targets]);
  const all = useMemo(allTargets, [Store.describe, Store.stats]);
  // locked: launched from one interface — show only that target, no toggling, just the IP.
  const locked = !!(prefill && prefill.lock && prefill.node && prefill.iface);
  const baseAll = locked ? all.filter(t => t.node === prefill.node && t.iface === prefill.iface)
    : (exclude ? all.filter(t => !exclude.has(tkey(t.node, t.iface))) : all);
  // existing deployments whose interface the node no longer reports (dangling/missing) — still list them so the
  // operator can UNCHECK to drop them; otherwise a dangling deployment is stuck on the peer with no way to remove it.
  const missingExisting = (!locked && initial) ? initial.filter(t => !baseAll.some(a => a.node === t.node && a.iface === t.iface))
    .map(t => ({ node: t.node, iface: t.iface, type: t.type, missing: true })) : [];
  const targets = baseAll.concat(missingExisting);
  const [sel, setSel] = useState({});
  const allocIp = async (node, iface) => {
    const k = tkey(node, iface);
    setSel(s => ({ ...s, [k]: { node, iface, ip: "", ipHint: T("finding a free address…") } }));
    const r = await api.nextIp([node], iface);
    setSel(s => s[k] ? { ...s, [k]: { node, iface, ip: r.ok ? String(r.data.next_ip).split("/")[0] : "", ipHint: r.ok ? "" : (srvText(r) || T("no free address")) } } : s);
  };
  const toggle = (node, iface) => {
    const k = tkey(node, iface);
    if (sel[k]) setSel(s => { const n = { ...s }; delete n[k]; return n; });
    else if (iTypeOf(node, iface) === "wdtt") setSel(s => ({ ...s, [k]: { node, iface, ip: "", wdtt: true } }));   // WDTT mints the client IP on connect — no address to pick
    else if (iTypeOf(node, iface) === "csqtt") setSel(s => ({ ...s, [k]: { node, iface, ip: "", csqtt: true } }));   // csqtt mints the address on connect too
    else allocIp(node, iface);
  };
  const setIp = (k, v) => setSel(s => s[k] ? { ...s, [k]: { ...s[k], ip: v } } : s);
  const seeded = useRef(false);
  useEffect(() => {                                  // seed already-deployed targets (their assigned IP, read-only)
    if (seeded.current || !initial || !initial.length || !all.length) return;
    seeded.current = true;
    const seed = {};
    initial.forEach(t => { seed[tkey(t.node, t.iface)] = { node: t.node, iface: t.iface, ip: String(t.ip || "").split("/")[0], existing: true }; });
    setSel(seed);
  }, [all, initial]);
  useEffect(() => {                                  // preselect from prefill once targets are known
    if (!targets.length || Object.keys(sel).length || (initial && initial.length)) return;
    if (prefill && prefill.node && prefill.iface) {
      if (iTypeOf(prefill.node, prefill.iface) === "wdtt") setSel({ [tkey(prefill.node, prefill.iface)]: { node: prefill.node, iface: prefill.iface, ip: "", wdtt: true } });   // WDTT: select without allocating an address
      else if (iTypeOf(prefill.node, prefill.iface) === "csqtt") setSel({ [tkey(prefill.node, prefill.iface)]: { node: prefill.node, iface: prefill.iface, ip: "", csqtt: true } });
      else allocIp(prefill.node, prefill.iface);
    } else if (prefill && prefill.node) targets.filter(t => t.node === prefill.node).slice(0, 1).forEach(t => allocIp(t.node, t.iface));
  }, [all]);
  useEffect(() => { onChange(Object.values(sel)); }, [sel]);

  if (!targets.length) return html`<div class="hint">${T("No interfaces available — is a node online?")}</div>`;
  // Steady order — by node, then interface. Ticking a target does NOT move its row (an on-the-fly "checked rows jump
  // to the top" reshuffle read as confusing); the arrangement stays put while you pick, and re-sorts only on re-open.
  const _sv = Object.values(sel);
  const lockType = _sv.length ? iTypeOf(_sv[0].node, _sv[0].iface) : null;   // a peer is one protocol — hide the other kind once one is ticked
  const ordered = [...targets].filter(t => t.missing || !lockType || iTypeOf(t.node, t.iface) === lockType).sort((a, b) =>
    (Store.nodeName(a.node) || "").localeCompare(Store.nodeName(b.node) || "")
    || (a.iface || "").localeCompare(b.iface || ""));
  return html`<div class="targetpick">${ordered.map(t => {
    const k = tkey(t.node, t.iface); const s = sel[k];
    const ity = t.missing ? (t.type || "wg") : iTypeOf(t.node, t.iface);   // wg | awg | wdtt (a WDTT iface isn't in `describe`, so key off the name via iTypeOf)
    return html`<div class=${"targetopt " + (s ? "sel " : "") + (locked ? "locked" : "") + (t.missing ? " missing" : "")}>
      <label class="topt-main" onClick=${locked ? null : () => toggle(t.node, t.iface)}>
        <span class="box">${s ? html`<${Ic} i="check"/>` : ""}</span>
        <span class="nm" style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span>
        <span class="tp">${t.iface}</span>
        ${t.missing ? html`<span class="topt-missing" title=${T("This interface is gone from the node — uncheck to remove this deployment from the peer")}>${T("tag|missing")}</span>` : null}</label>
      ${(pubPeer && pubHave.has(k)) ? html`<${PubTag} peer=${pubPeer} src=${ity} label=${ity}/>` : html`<${Tag} kind=${ity} label=${ity}/>`}
      ${t.missing ? null : html`<${TargetFrontBadge} node=${t.node} iface=${t.iface}/>`}
      ${(s && (s.wdtt || s.csqtt || isSelfContainedKind(ity)))
        // `ity` (the interface's real type), not just the flag set when a row is TOGGLED: an already-deployed
        // target is seeded straight from the peer, so it never went through toggle and rendered an editable
        // address box for a self-contained server — which mints the client IP itself on connect and can't be told one.
        ? html`<span class="topt-ip faint" title=${T("The server assigns the address on connect")}>${T("val|auto")}</span>`
        : (s ? html`<input class=${"topt-ip " + (s.ip && !V.ipv4(s.ip) ? "bad" : "")} value=${s.ip} placeholder=${s.ipHint || "address"} title=${s.ip && !V.ipv4(s.ip) ? T("not a valid IPv4 address") : ""} onInput=${e => setIp(k, e.target.value)}/>` : null)}
    </div>`;
  })}</div>`;
}

// CONTROLLED interfaces grid for the Add-peers carousel: `value` = {tkey:{node,iface,ip,existing?}}; `onChange`
// takes a functional updater so an async IP allocation merges against the LATEST selection. `lockExisting` keeps
// already-deployed rows checked + read-only (removing a live deployment isn't done here). Scrolls past 5 rows.

// Advanced client-config fields (DNS / MTU / keepalive / AllowedIPs) — shared by the
// peer-minting sheets. `v` is a {dns,mtu,keepalive,allowed,dnsTouched} ref-ish object.
export function AdvancedFields({ st, startOpen }) {
  const [open, setOpen] = useState(!!startOpen);
  const errs = configErrors(st);
  const fld = (k, fallback) => (errs[k] ? html`<div class="hint err">${errs[k]}</div>` : html`<div class="hint">${fallback}</div>`);
  return html`<${Fragment}>
    <button class="advtoggle" onClick=${() => setOpen(o => !o)}><span>${open ? "▾" : "▸"}</span> ${T("Advanced")}${Object.keys(errs).length ? html` <span class="advbad">${plural(Object.keys(errs).length, "issue")}</span>` : ""}</button>
    ${open ? html`<div class="adv open">
      <div class="field" style="margin-top:8px"><label>${T("Client allowed IPs (routing)")}</label>
        <input class=${errs.allowed ? "bad" : ""} value=${st.allowed} onInput=${e => st.set("allowed", e.target.value)}/>${fld("allowed", T("Full tunnel by default. Narrow for split tunnel."))}</div>
      <div class="field"><label>DNS</label>
        <input class=${errs.dns ? "bad" : ""} value=${st.dns} onInput=${e => { st.dnsTouched.current = true; st.set("dns", e.target.value); }} placeholder=${T("from server, or e.g. 1.1.1.1")}/>${fld("dns", T("Comma-separated IPs. Blank = no DNS line."))}</div>
      <div class="row2">
        <div class="field"><label>MTU</label><input class=${errs.mtu ? "bad" : ""} value=${st.mtu} onInput=${e => { if (st.mtuTouched) st.mtuTouched.current = true; st.set("mtu", e.target.value); }} placeholder="1280"/>${fld("mtu", "Blank = 1280.")}</div>
        <div class="field"><label>${T("Persistent keepalive (s)")}</label><input class=${errs.keepalive ? "bad" : ""} value=${st.keepalive} onInput=${e => st.set("keepalive", e.target.value)} placeholder="25"/>${fld("keepalive", T("0 disables · blank = 25."))}</div>
      </div></div>` : null}
  <//>`;
}

// Mint ONE peer per chosen target (own keypair + PSK each), assigned to userId. Builds each
// config in-browser, stashes it in sessionConfigs (so the QR shows), and creates the peer via
// the Phase-2 endpoint. Returns { ok, made, fails:[...] }.

// Shared client-config field state (DNS / MTU / keepalive / AllowedIPs) for the peer sheets.
export function useConfigFields() {
  const [dns, setDns] = useState(""); const [mtu, setMtu] = useState("1280");
  const [keepalive, setKeepalive] = useState("25"); const [allowed, setAllowed] = useState("0.0.0.0/0, ::/0");
  const dnsTouched = useRef(false); const mtuTouched = useRef(false);
  const setters = { dns: setDns, mtu: setMtu, keepalive: setKeepalive, allowed: setAllowed };
  return { dns, mtu, keepalive, allowed, dnsTouched, mtuTouched, setDns, setMtu, set: (k, v) => setters[k](v),
           opts: () => ({ dns, mtu, keepalive, allowed }) };
}

// New peer (mint a fresh keypair) deployed to one OR MORE (node,iface) targets as ONE
// credential (redundancy / failover). For per-interface devices, use a user's "Add peers".
export function openCreatePeer(prefill, child) { (child ? pushModal : openModal)(html`<${CreatePeerSheet} prefill=${prefill || {}}/>`); }
export function CreatePeerSheet({ prefill }) {
  const [chosen, setChosen] = useState([]);
  const [title, setTitle] = useState("");
  const cf = useConfigFields();
  const [userId, setUserId] = useState(prefill.user_id || "");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {   // default DNS + MTU from the first chosen interface until the operator edits them
    if (!chosen.length) return;
    const m = Store.ifaceMeta(chosen[0].node, chosen[0].iface); if (!m) return;
    if (!cf.dnsTouched.current) cf.setDns((m.dns || []).join(", "));
    if (!cf.mtuTouched.current && m.mtu) cf.setMtu(String(m.mtu));
  }, [chosen]);

  const wdttMode = chosen.some(t => t.wdtt);   // the TargetPicker locks a peer to one kind, so any wdtt target ⇒ all wdtt
  const csqttMode = chosen.some(t => t.csqtt);   // …likewise csqtt
  const keylessMode = wdttMode || csqttMode;   // self-contained kinds: no address, no client-config fields

  const validate = () => {
    if (!chosen.length) return T("Pick at least one target.");
    if (keylessMode) return null;   // self-contained targets carry no address (minted on connect) + no client-config fields
    const badIp = chosen.find(t => !V.ipv4(String(t.ip).trim()));
    if (badIp) return T("Invalid address for {v1}.", { v1: Store.nodeName(badIp.node) + "/" + badIp.iface });
    const ce = configErrors(cf); const k = Object.keys(ce)[0];
    if (k) return ce[k];
    return null;
  };

  const create = async () => {
    const err = validate(); if (err) return setMsg({ k: "err", t: err });
    if (keylessMode) {   // keyless self-contained peer — the panel mints the access password; the server mints the client address on connect. One roster peer, one link per targeted server.
      setBusy(true); setMsg({ k: "work", t: csqttMode ? T("adding csqtt user…") : T("adding WDTT user…") });
      const body = { user_id: userId || null, title: title.trim(), targets: chosen.map(t => ({ node: t.node, iface: t.iface })) };
      const r = await (csqttMode ? api.csqttPeerCreate(body) : api.wdttPeerCreate(body));
      if (!r.ok) { setBusy(false); return setMsg({ k: "err", t: srvText(r) || T("Request failed.") }); }
      closeModal();
      if (prefill.lock && prefill.node && prefill.iface) go("#/node/" + encodeURIComponent(prefill.node) + "/" + encodeURIComponent(prefill.iface));
      else if (userId) revealUser(userId, (r.data && r.data.id) || "");
      Store.apply(); await Store.poll();
      return toast(csqttMode ? T("csqtt user added — their connect link is on the assigned subscription.") : T("WDTT user added — their connect link is on the assigned subscription."), "ok");
    }
    setBusy(true); setMsg({ k: "work", t: T("generating key…") });
    let keys, pskV, tgts, configs, body;
    try {                                            // browser-side crypto/config build is the only awaited part
      keys = await genKeys();
      pskV = genPSK();   // PSK is panel-owned & auto-minted; change it via a peer's Rotate keys
      const dnsArr = cf.dns.split(",").map(s => s.trim()).filter(Boolean);
      tgts = []; configs = {};
      for (const t of chosen) {
        const m = Store.ifaceMeta(t.node, t.iface); if (!m) continue;
        const ipClean = String(t.ip).trim().split("/")[0];
        tgts.push({ node: t.node, iface: t.iface, ip: ipClean, type: (m.awg_params && Object.keys(m.awg_params).length) ? "awg" : "wg" });
        configs[tkey(t.node, t.iface)] = buildConf({ privkey: keys.priv, address: ipClean + "/32", dns: dnsArr, mtu: cf.mtu.trim() || 1280, awg_params: m.awg_params, server_pubkey: m.public_key, psk: pskV, endpoint: m.endpoint, allowed: cf.allowed.trim() || "0.0.0.0/0, ::/0", keepalive: cf.keepalive.trim() });
      }
      body = { user_id: userId || null, title: title.trim(), pubkey: keys.pub, psk: pskV, targets: tgts };
      const _ov = configOverrides(cf.opts(), Store.ifaceMeta(chosen[0].node, chosen[0].iface));
      if (Object.keys(_ov).length) body.overrides = _ov;
      // No plaintext to the server: the key stays in the browser (session config for the immediate QR) and is
      // encrypted into the blob by subMaybePublish (below, after the create POST succeeds).
    } catch (e) { setBusy(false); return setMsg({ k: "err", t: T("Error: {v1}", { v1: e.message })}); }
    // Optimistic: stash the config, drop a "creating" peer onto the grid, close the modal NOW, and let
    // the create POST run in the background (mutate reverts + toasts on failure; the next poll supersedes).
    Store.sessionConfigs[keys.pub] = Object.assign(Store.sessionConfigs[keys.pub] || {}, configs);
    const tempId = "tmp_" + keys.pub.slice(0, 14);
    const optimistic = { id: tempId, pubkey: keys.pub, user_id: userId || null, title: title.trim(), psk: pskV,
      targets: tgts.map(t => ({ node: t.node, iface: t.iface, ip: t.ip, type: t.type })),
      created_at: Math.floor(Date.now() / 1000), _creating: true };
    closeModal();
    if (prefill.lock && prefill.node && prefill.iface) go("#/node/" + encodeURIComponent(prefill.node) + "/" + encodeURIComponent(prefill.iface));
    else if (userId) revealUser(userId, tempId);
    mutate({
      patch: s => { s.roster.peers[tempId] = optimistic; },        // shows instantly with status "creating"
      call: () => api.peerCreate(body),
      onOk: r => { if (r && r.data && r.data.id) { Store.recentlyCreated[r.data.id] = Date.now();
        subPublishOrPrompt(userId || null, r.data.id, keys.priv, pskV); } },   // encrypt {k,p} → blob (prompt to unlock if locked)
    });
  };

  return html`<${Sheet} title=${T("New peer")} width=${620}
    foot=${footRow({ onCancel: closeModal, disabled: busy, onAction: create, action: T("Create peer") })}>
    ${prefill.lockUser
      ? html`<div class="field"><label>${T("col|User")}</label><div class="lockeduser">${prefill.userName || (Store.recon.users.find(u => u.id === userId) || {}).name || "—"}</div></div>`
      : html`<div class="field"><label>${T("col|User")}</label>
      <${UserPicker} value=${userId} allowUnassigned=${true} onChange=${setUserId}/></div>`}
    <div class="field"><label>${T("col|Title")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— optional, to tell devices apart")}</span></label>
      <input value=${title} onInput=${e => setTitle(e.target.value)} maxlength="64" placeholder=${T("iPhone, Router, Laptop…")}/></div>
    <div class="field"><label>${T("Targets")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— one, or several for redundancy (same key)")}</span></label>
      <${TargetPicker} prefill=${prefill} onChange=${setChosen}/></div>
    ${csqttMode
      ? html`<div class="hint">${T("csqtt server — the panel mints this user's access password and csqtt mints their address on connect, so there's no key or client config to set here. The user's VK link (from their subscription) is the TURN credential.")}</div>`
      : wdttMode
      ? html`<div class="hint">${T("WDTT server — the panel mints this user's access password and WDTT mints their WireGuard key + IP on connect, so there's no key or client config to set here. The user's VK link (from their subscription) is the TURN credential.")}</div>`
      : html`<${AdvancedFields} st=${cf}/>`}
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// Copy peer interface→interface (same key + PSK, new target). Needs the client's
// private key (session config, or stored) to build the new client config / QR.
// `back` = where Cancel / Deploy / Esc returns to (e.g. reopen the peer view); default just closes.
export function openAddTarget(peer, back) {
  const child = modalDepth() > 0;   // opened from another modal (peer view / edit) → child; Cancel pops back to it
  (child ? pushModal : openModal)(html`<${AddTargetSheet} peer=${peer} back=${back || closeModal} child=${child}/>`);
}
export function AddTargetSheet({ peer, back, child }) {
  back = back || closeModal;
  const [chosen, setChosen] = useState([]);
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  // source config (holds the client's private key) so NEW targets can rebuild a QR: session first,
  // then the panel's stored copy when store_configs is on. Any target's config carries the same key.
  const [srcConf, setSrcConf] = useState(() => anySessionConf(peer.pubkey));
  const [confLoaded, setConfLoaded] = useState(() => !!anySessionConf(peer.pubkey) || !Store.storeConfigs);
  useEffect(() => {
    if (srcConf || !Store.storeConfigs) { setConfLoaded(true); return; }
    let ok = true;
    (async () => {
      for (const t of peer.targets) { const c = await getConfig(peer.pubkey, t.node, t.iface); if (c) { if (ok) setSrcConf(c); break; } }
      if (ok) setConfLoaded(true);
    })();
    return () => { ok = false; };
  }, [peer.id]);

  const initial = useMemo(() => peer.targets.map(t => ({ node: t.node, iface: t.iface, ip: t.ip, type: t.type })), [peer.id]);
  const haveKeys = new Set(peer.targets.map(t => tkey(t.node, t.iface)));
  const origIp = {}; peer.targets.forEach(t => origIp[tkey(t.node, t.iface)] = String(t.ip || "").split("/")[0]);
  const chosenKeys = new Set(chosen.map(c => tkey(c.node, c.iface)));
  const added = chosen.filter(c => !haveKeys.has(tkey(c.node, c.iface)));         // newly checked
  const removed = peer.targets.filter(t => !chosenKeys.has(tkey(t.node, t.iface))); // unchecked existing
  const ipChanged = chosen.filter(c => haveKeys.has(tkey(c.node, c.iface)) && c.ip && String(c.ip).split("/")[0] !== origIp[tkey(c.node, c.iface)]);  // existing whose address was edited
  const badIp = added.concat(ipChanged).some(c => !c.ip || !V.ipv4(String(c.ip).split("/")[0]));
  const nochange = !added.length && !removed.length && !ipChanged.length;

  const doSave = async () => {
    setBusy(true); setMsg({ k: "work", t: "applying…" });
    const fails = [];
    for (const t of added) {
      const info = Store.ifaceMeta(t.node, t.iface);
      const ipClean = String(t.ip || "").split("/")[0];
      let conf = null;
      if (srcConf) { const s = parseFullConf(srcConf); conf = buildConf({ privkey: s.privkey, address: ipClean + "/32", dns: s.dns, mtu: s.mtu, awg_params: info.awg_params, server_pubkey: info.public_key, psk: s.psk || peer.psk, endpoint: info.endpoint, allowed: s.allowed, keepalive: s.keepalive }); }
      const body = { peer_id: peer.id, target: { node: t.node, iface: t.iface, ip: ipClean, type: info.awg_params && Object.keys(info.awg_params).length ? "awg" : "wg" } };
      // Same key as the existing deployments → the peer's blob already covers it; no plaintext to the server.
      const r = await api.peerAddTarget(body);
      if (r.ok) { if (conf) (Store.sessionConfigs[peer.pubkey] = Store.sessionConfigs[peer.pubkey] || {})[tkey(t.node, t.iface)] = conf; }
      else fails.push(Store.nodeName(t.node) + "/" + T("{v1} (add)", { v1: t.iface }));
    }
    for (const t of ipChanged) {
      const info = Store.ifaceMeta(t.node, t.iface);
      const ipClean = String(t.ip || "").split("/")[0];
      const body = { peer_id: peer.id, node: t.node, iface: t.iface, ip: ipClean };
      // address lives in the roster (rendered live); rebuild the session config for the QR, but send no plaintext.
      if (srcConf) { const s = parseFullConf(srcConf); const conf = buildConf({ privkey: s.privkey, address: ipClean + "/32", dns: s.dns, mtu: s.mtu, awg_params: info.awg_params, server_pubkey: info.public_key, psk: s.psk || peer.psk, endpoint: info.endpoint, allowed: s.allowed, keepalive: s.keepalive }); (Store.sessionConfigs[peer.pubkey] = Store.sessionConfigs[peer.pubkey] || {})[tkey(t.node, t.iface)] = conf; }
      const r = await api.peerUpdateTarget(body);
      if (!r.ok) fails.push(Store.nodeName(t.node) + "/" + T("{v1} (address)", { v1: t.iface }));
    }
    for (const t of removed) {
      const r = await api.peerRemoveTarget({ peer_id: peer.id, node: t.node, iface: t.iface });
      if (!r.ok) fails.push(Store.nodeName(t.node) + "/" + T("{v1} (remove)", { v1: t.iface }));
    }
    setBusy(false);
    if (fails.length) { setMsg({ k: "err", t: T("Some changes failed: {v1}", { v1: fails.join(", ") })}); return false; }
    toast(T("Peer targets updated."), "ok"); await Store.poll(); return true;
  };
  const save = () => {
    if (nochange) { back(); return; }
    if (badIp) return setMsg({ k: "err", t: T("A target has an invalid address.") });
    if (chosen.length === 0) {                       // a peer must live on at least one interface — none left = delete it
      pushModal(html`<${ConfirmSheet} title=${T("Delete this peer?")} confirmLabel=${T("Yes, delete")} danger=${true}
        body=${T("You've unchecked every interface, so there's nothing left to deploy this peer to — saving will completely delete it. Its access is revoked everywhere and its config / QR stops working. This action is irreversible. Are you sure you want to continue?")}
        onConfirm=${async () => {
          if (peer.user_id != null) { const u = await api.peerUnassign({ peer_id: peer.id }); if (!u.ok) return setMsg({ k: "err", t: T("Delete failed: {v1}", { v1: srvText(u) || u.code || "" }) }); }
          const r = await api.peerDelete({ peer_id: peer.id });
          if (!r.ok) return setMsg({ k: "err", t: T("Delete failed: {v1}", { v1: srvText(r) || r.code || "" }) });
          closeModal(); back(); toast(T("Peer deleted."), "ok"); await Store.poll();
        }}/>`);
      return;
    }
    if (removed.length || ipChanged.length) {
      const parts = [];
      if (removed.length) {
      const where = removed.map(t => Store.nodeName(t.node) + "/" + t.iface).join(", ");
      parts.push(removed.length > 1
        ? T("Remove the peer from {v1} — those tunnels drop immediately and the client can no longer connect through them.", { v1: where })
        : T("Remove the peer from {v1} — that tunnel drops immediately and the client can no longer connect through it.", { v1: where }));
    }
      if (ipChanged.length) {
      const where = ipChanged.map(c => Store.nodeName(c.node) + "/" + c.iface).join(", ");
      parts.push(ipChanged.length > 1
        ? T("Change the peer's address on {v1} — the config / QR already handed out for those interfaces stops connecting, so you'll need to re-issue and re-distribute them.", { v1: where })
        : T("Change the peer's address on {v1} — the config / QR already handed out for that interface stops connecting, so you'll need to re-issue and re-distribute it.", { v1: where }));
    }
      const title = removed.length && ipChanged.length ? T("Apply these changes?")
        : removed.length ? T("Remove from {v1}?", { v1: plural(removed.length, "interface") })
        : T("Change {v1}?", { v1: plural(ipChanged.length, "address") });
      pushModal(html`<${ConfirmSheet} title=${title} confirmLabel=${T("Save changes")} danger=${true} body=${parts.join(" ") + " " + T("This can't be undone.")}
        note=${ipChanged.length ? html`<${SubAutoNote}/>` : null}
        onConfirm=${async () => { if (await doSave()) { closeModal(); back(); } }}/>`);
    } else doSave().then(ok => { if (ok) back(); });
  };

  return html`<${Sheet} title=${T("Peer targets")} width=${620} onClose=${back} onBack=${child ? back : null} subject=${{ kind: "peer", id: peer.id }}
    foot=${footRow({ onCancel: back, actionCls: "btn " + (chosen.length === 0 ? "btn-danger" : "btn-primary"), disabled: busy || !confLoaded || nochange, onAction: save, action: chosen.length === 0 ? T("Delete peer") : ((removed.length || ipChanged.length) ? T("Save changes") : T("Deploy")) })}>
    ${!confLoaded ? html`<div class="loading"><span class="spin"></span>${T("loading config…")}</div>`
      : html`<${Fragment}>
        ${added.length && !srcConf ? html`<div class="notice warn"><${Ic} i="warn"/><span>${Store.storeConfigs
            ? T("This peer's private key isn't available here, so newly-added targets get the same key + PSK but a fresh QR / config can't be generated. Re-issue (rotate keys) for a downloadable config.")
            : T("store_configs is off, so the client's private key isn't kept — new targets get the same key + PSK, but a fresh QR can't be shown.")}</span></div>` : null}
        <div class="field"><label>${T("Targets")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— check to deploy, uncheck to remove")}</span></label>
          <${TargetPicker} initial=${initial} pubPeer=${peer} onChange=${setChosen}/></div>
        ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
      </>`}
  <//>`;
}

// Edit a peer's client-config settings (DNS / MTU / keepalive / AllowedIPs) and re-issue
// the config for every target. The private key only lives in the existing config, so this
// rebuilds from it — available right after creation, or whenever store_configs is on.
// (Address / interface / server are deployment moves — use copy + remove for those.)
// Read-only peer view: all the peer's info + actions (edit / unassign|delete / close).
export function openPeerView(pid, node, iface, child) { (child ? pushModal : openModal)(html`<${PeerViewSheet} pid=${pid} node=${node} iface=${iface}/>`); }
export function PeerViewSheet({ pid, node, iface }) {
  useStore();
  const p = Store.peer(pid);
  const depsOrdered = useStableOrder(p ? p.targets : []);   // frozen at open — toggling ★ won't re-shuffle the cards
  if (!p) return html`<${Sheet} title=${T("sheet|Peer")} foot=${html`<button class="btn btn-ghost" onClick=${closeModal}>${T("Close")}</button>`}><div class="empty"><b>${T("Peer not found")}</b>${T("It may have been removed.")}</div><//>`;
  const u = p.user_id ? Store.user(p.user_id) : null;
  // Editing is peer-WIDE (keys, AmneziaWG params, DNS, address apply to every deployment), so it's locked while any
  // deployment is on a missing (dangling) or misconfigured (broken) interface — a change there can't reach that
  // deployment and would leave the peer inconsistent. The operator must Restore/Fix the interface, or drop it from Targets.
  const editLocked = p.targets.some(t => t.status === "dangling" || t.status === "broken");
  // Same status treatment as the peer QR modal: in a subscription → subscription status in the header (right) + the
  // peer's own status on a line under it; not in a subscription → the peer's own status takes the header slot.
  const headExtra = u ? html`<${SubStatusLine} user=${u} pos="hr"/>` : html`<${PeerStatusLine} peer=${p} pos="hr"/>`;
  return html`<${Sheet} title=${p.title || (u ? u.name : T("Unassigned peer"))} width=${640} headExtra=${headExtra} subject=${{ kind: "peer", id: pid }}
    foot=${html`<${Fragment}>
      <button class="btn btn-ghost" onClick=${closeModal}>${T("Close")}</button><span class="grow"></span>
      <button class="btn btn-ghost" onClick=${() => openPeerConfigs(p, { child: true })}><${Ic} i="qr"/>QR</button>
      <button class="btn btn-ghost" onClick=${() => openAddTarget(p)}><${Ic} i="copy"/> ${T("Targets")}</button>
      ${editLocked
        ? html`<button class="btn btn-ghost" disabled title=${T("Fix or remove the problem interface first — see the note above")}><${Ic} i="pencil"/> ${T("Edit")}</button>`
        : html`<button class="btn btn-ghost" onClick=${() => openEditPeer(p, node && iface ? { node, iface } : null)}><${Ic} i="pencil"/> ${T("Edit")}</button>`}
      ${peerBlockBtn(p)}
      ${p.unassigned ? html`<button class="btn btn-danger" onClick=${() => confirmDeletePeer(p)}>${T("Delete")}</button>`
        : html`<button class="btn btn-danger" onClick=${() => confirmUnassign(p)}>${T("Unassign")}</button>`}<//>`}>
    ${u ? html`<${PeerStatusLine} peer=${p} pos="bar"/>` : null}
    <div class="pv-head">
      <div class="pv-id"><div class="pv-sub">${u ? html`<a class="pv-user" href="#/users" onClick=${e => { e.preventDefault(); closeModal(); revealUser(u.id); }}>${u.name}</a>`
          : html`<${UserCombo} onPick=${uid => assignPeer(p, uid)} placeholder=${T("Assign to a user…")}/>`}</div></div>
      ${badgeWithReason(p.unassigned ? "unassigned" : p.status, p.reason)}</div>
    <div class="lbl" style="margin:16px 2px 4px">${T("Deployments · {n}", { n: p.targets.length })}</div>
    <div class="pv-deps">${depsOrdered.map(t => {
      const obs = t.observed;
      const xfer = tgtXfer(t);            // wire counters for wg/awg, per-password byte deltas for a keyless server
      const proto = targetType(t);
      return html`<div class=${"pv-dep" + (node === t.node && iface === t.iface ? " hl" : "")} key=${tkey(t.node, t.iface)}>
        <div class="pv-dep-top">${badgeWithReason(t.status, t.status === "blocked" ? blockedReason(t.type) : statusReason(t.status))}
          <span class="tags">
            <${PubTag} peer=${p} src=${proto} label=${proto} muted=${!t.online}/>
            ${turnEnabled() && turnProxiesFor(t.node, t.iface).length ? html`<${PubTag} peer=${p} src="turn" label=${T("val|turn")}/>` : null}
          </span>
          <span class="grow"></span>
          <${PrimaryToggle} peer=${p} t=${t}/>
          ${(() => { const gh = ghostIface(t.node, t.iface); return (gh && gh.ripe)
            ? html`<button class="btn btn-ghost gh" title=${T("Recreate this interface with a NEW key and rekey every peer on it — clients re-import")} onClick=${() => openRecreateRekey(t.node, t.iface)}><${Ic} i="refresh"/> ${T("Recreate & rekey interface")}</button>`
            : t.restorable ? html`<button class="btn btn-ghost restore" title=${T("Recreate this missing interface with its original identity — recovers every peer on it")} onClick=${() => confirmRestoreDeployment(p, t)}><${Ic} i="refresh"/> ${T("Restore interface")}</button>`
            : t.correctable ? html`<button class="btn btn-ghost correct" title=${T("Assign the next free in-subnet address ({ip} is out of range)", { ip: t.ip || "?" })} onClick=${() => confirmCorrectDeployment(p, t)}><${Ic} i="check"/> ${T("Fix address")}</button>` : null; })()}</div>
        <div class="pv-dep-grid">
          <span><span class="k">${T("col|Node")}</span> <span style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span></span>
          <span><span class="k">${T("col|Interface")}</span> ${t.iface}</span>
          <span><span class="k">${T("col|Address")}</span> <span class="addr">${t.ip || "—"}</span></span>
          <span><span class="k">${T("col|Rate")}</span> ${rateCell(xfer ? xfer.rx_speed : 0, xfer ? xfer.tx_speed : 0)}</span>
          <span><span class="k">${T("col|Total")}</span> ${xferCell(...dlul(xfer ? xfer.rx_bytes : 0, xfer ? xfer.tx_bytes : 0))}</span>
          <span><span class="k">${T("col|Online")}</span> ${seen(tgtSeenAge(t))}</span>
        </div></div>`;
    })}</div>
    ${editLocked ? html`<div class="notice warn" style="margin-top:14px"><${Ic} i="warn"/><span>${T("Editing is off while a deployment sits on a missing or misconfigured interface. A peer edit (keys, AmneziaWG params, DNS, address) applies to every deployment, so it would leave this peer inconsistent. To edit it, either Restore / Fix the interface above, or open Targets and remove that interface from this peer.")}</span></div>` : null}
  <//>`;
}

// Edit a peer: title (peer-wide), the focused target's address, and the client-config settings
// (DNS/MTU/keepalive/AllowedIPs, applied to every target with a known config). Also offers copy
// → another interface and key rotation (keeps the PSK). `focus` = the {node,iface} to edit IP for.
// `done` = where Cancel / Save returns to (reopen the peer view when edit came from it, else close).
export function openEditPeer(peer, focus, done, flash) {
  const child = modalDepth() > 0;   // opened from another modal (peer view) → child; closing pops back to it
  (child ? pushModal : openModal)(html`<${EditPeerSheet} peer=${peer} focus=${focus} done=${done || closeModal} flash=${flash} child=${child}/>`);
}
export function EditPeerSheet({ peer, focus, done, flash, child }) {
  done = done || closeModal;
  useStore();                                        // re-render on poll so a target added via the Targets sheet shows up live
  const live = Store.peer(peer.id) || peer;          // LIVE peer (the `peer` prop is a snapshot from open) — used for the target list
  const targetsOrdered = useStableOrder(live.targets);   // frozen at open — the primary ★ won't re-shuffle rows mid-edit
  const [title, setTitle] = useState(peer.title || "");
  const [ips, setIps] = useState(() => Object.fromEntries(live.targets.map(t => [tkey(t.node, t.iface), (t.ip || "").split("/")[0]])));
  useEffect(() => {                                  // a newly-added target appears live → give it an IP field
    setIps(prev => { const next = { ...prev }; let ch = false;
      live.targets.forEach(t => { const k = tkey(t.node, t.iface); if (!(k in next)) { next[k] = (t.ip || "").split("/")[0]; ch = true; } });
      return ch ? next : prev; });
  }, [live.targets.map(t => tkey(t.node, t.iface)).join(",")]);
  const setIpFor = (k, v) => setIps(m => ({ ...m, [k]: v }));
  const [loaded, setLoaded] = useState(false);
  const [confs, setConfs] = useState({});            // "node|iface" -> conf text (those we can rebuild)
  const [dns, setDns] = useState(""); const [mtu, setMtu] = useState("1280");
  const [keepalive, setKeepalive] = useState("25"); const [allowed, setAllowed] = useState("0.0.0.0/0, ::/0");
  const [userId, setUserId] = useState(peer.user_id || "");   // staged owner (applied on Save for an unassigned peer)
  const [expDate, setExpDate] = useState(expiryInputVal(peer.ownExpiry || 0));   // this peer's OWN expiry (blank = inherit the subscription's)
  const [msg, setMsg] = useState(flash || null); const [busy, setBusy] = useState(false);
  const [orig, setOrig] = useState(null);          // the loaded config values — Save stays off until one differs
  const [rotating, setRotating] = useState(false); // Rotate in flight → the button disables + says so
  // reopening THIS sheet with a new flash (e.g. rotate: orange "Rotating…" → green "Keys rotated")
  // reuses the instance, so the useState initial above is ignored — sync the prop into state.
  useEffect(() => { if (flash) setMsg(flash); }, [flash]);

  useEffect(() => {
    let ok = true;
    (async () => {
      const found = {};
      // LIVE pubkey, not the `peer` prop's: a Rotate mints a new keypair and stores the config under the NEW
      // pubkey while the prop stays the snapshot from when the sheet opened. Looking it up by the stale key found
      // nothing, so the sheet kept saying "the client's private key isn't available" even after a good rotate.
      const _pk = (live && live.pubkey) || peer.pubkey;
      for (const t of (live.targets || peer.targets)) { const c = await getConfig(_pk, t.node, t.iface); if (c) found[tkey(t.node, t.iface)] = c; }
      if (!ok) return;
      setConfs(found); setLoaded(true);
      const first = found[tkey(focus && focus.node, focus && focus.iface)] || Object.values(found)[0];
      if (first) { const s = parseFullConf(first); const _d = (s.dns || []).join(", "), _m = String(s.mtu), _k = String(s.keepalive);
        setDns(_d); setMtu(_m); setKeepalive(_k); setAllowed(s.allowed);
        setOrig({ dns: _d, mtu: _m, keepalive: _k, allowed: s.allowed }); }   // baseline for the "anything changed?" Save gate
    })();
    return () => { ok = false; };
  }, [peer.id, live && live.pubkey, Store.configEpoch]);   // LIVE pubkey / epoch change (e.g. after Rotate) re-reads the now-available config

  const editable = Object.keys(confs).length;
  const ipChangedFor = t => { const v = (ips[tkey(t.node, t.iface)] || "").trim(); return !!v && v !== (t.ip || "").split("/")[0]; };
  const ipBadFor = t => { const v = (ips[tkey(t.node, t.iface)] || "").trim(); return !!v && !V.ipv4(v.split("/")[0]); };
  const anyIpBad = peer.targets.some(ipBadFor);
  const errs = editable ? configErrors({ dns, mtu, keepalive, allowed }) : {};
  // Save is only offered when something would actually change — otherwise it rewrites the peer with identical
  // values (and, for a user change, walks the operator into a confirm for a no-op).
  const _dirty = (title.trim() !== (peer.title || "").trim())
    || ((userId || "") !== (peer.user_id || ""))
    || (expDate !== expiryInputVal(peer.ownExpiry || 0))
    || (live.targets || []).some(ipChangedFor)
    || (editable && !!orig && (dns !== orig.dns || mtu !== orig.mtu || keepalive !== orig.keepalive || allowed !== orig.allowed));
  const ownerExp = userId ? +(((Store.recon.users || []).find(u => u.id === userId) || {}).expiry || 0) : 0;
  const save = async () => {
    if (anyIpBad) return setMsg({ k: "err", t: T("Each address must be a valid IPv4.") });
    const ek = Object.keys(errs)[0]; if (ek) return setMsg({ k: "err", t: errs[ek] });
    const expSec = expiryFromInput(expDate);
    // A peer can't outlive its subscription (the server enforces it too — check here for a clean message).
    if (expSec && ownerExp && expSec > ownerExp) return setMsg({ k: "err", t: T("Expiry can't be later than the subscription's (") + fmtDate(ownerExp) + ")." });
    setBusy(true); setMsg({ k: "work", t: T("saving…") });
    const dnsArr = dns.split(",").map(s => s.trim()).filter(Boolean);
    let fails = 0;
    try {
      if (title.trim() !== (peer.title || "")) {
        const r = await api.peerUpdate({ peer_id: peer.id, title: title.trim() }); if (!r.ok) fails++;
      }
      if (expSec !== (peer.ownExpiry || 0)) {   // this peer's own expiry date (independent of the subscription's)
        const r = await api.peerUpdate({ peer_id: peer.id, expiry: expSec }); if (!r.ok) { fails++; if (r.error) setMsg({ k: "err", t: srvText(r) }); }
      }
      // persist the roster copy of the non-secret overrides (custom DNS/MTU/AllowedIPs/keepalive), so a
      // blob-only render (encrypted store / the sub page) reproduces this peer's config faithfully.
      if (editable) {
        const _meta0 = Store.ifaceMeta(peer.targets[0].node, peer.targets[0].iface);
        const ovNew = configOverrides({ dns, mtu, allowed, keepalive }, _meta0);
        if (JSON.stringify(ovNew) !== JSON.stringify(peer.overrides || {})) {
          const r = await api.peerUpdate({ peer_id: peer.id, overrides: ovNew }); if (!r.ok) fails++;
        }
      }
      // staged assignment of a previously-unassigned peer — keep the key, just set the owner
      if (peer.unassigned && userId && userId !== (peer.user_id || "")) {
        const r = await api.peerUpdate({ peer_id: peer.id, user_id: userId }); if (!r.ok) fails++;
      }
      // rebuild + persist each target's config; any target whose address changed moves on its iface
      for (const t of peer.targets) {
        const k = tkey(t.node, t.iface); const cur = confs[k];
        const changed = ipChangedFor(t);
        const newIP = (ips[k] || "").trim().split("/")[0];
        if (!cur) {                                  // no config to rebuild — IP can still move
          if (changed) { const r = await api.peerUpdateTarget({ peer_id: peer.id, node: t.node, iface: t.iface, ip: newIP }); if (!r.ok) fails++; }
          continue;
        }
        const s = parseFullConf(cur);
        const addr = (changed ? newIP : (s.address || "").split("/")[0]) + "/32";
        const conf = buildConf({ privkey: s.privkey, address: addr, dns: editable ? dnsArr : s.dns, mtu: (mtu.trim() || 1280), awg_params: s.awg_params, server_pubkey: s.server_pubkey, psk: s.psk, endpoint: s.endpoint, allowed: (allowed.trim() || "0.0.0.0/0, ::/0"), keepalive: keepalive.trim() });
        (Store.sessionConfigs[peer.pubkey] = Store.sessionConfigs[peer.pubkey] || {})[k] = conf;
        // No plaintext to the server: the address moves via the roster, and the DNS/MTU/AllowedIPs edits are
        // persisted as roster overrides (the peerUpdate above); the key is unchanged, so the blob still holds it.
        if (changed) { const r = await api.peerUpdateTarget({ peer_id: peer.id, node: t.node, iface: t.iface, ip: newIP }); if (!r.ok) fails++; }
      }
    } catch (e) { setBusy(false); return setMsg({ k: "err", t: String(e.message || e) }); }
    setBusy(false); Store.configEpoch++;
    // an already-assigned peer changing owner is destructive (keys rotate) — confirm it now, on
    // Save (so cancelling keeps the previous owner). Title/config above are already persisted.
    const oldUid = peer.user_id || "", newUid = userId || "";
    if (oldUid && newUid !== oldUid) {
      await Store.poll();
      const fresh = (Store.recon.peers.find(x => x.id === peer.id)) || peer;
      return newUid ? confirmReassign(fresh, newUid) : confirmUnassign(fresh);   // stacks over this sheet; Cancel pops back
    }
    toast(fails ? T("Saved (some changes couldn't be persisted).") : T("Peer updated."), fails ? "info" : "ok");
    done(); await Store.poll();
  };

  const isWdttPeer = !!peer.wdtt_password || (peer.targets || []).some(t => t.type === "wdtt");
  const isCsqttPeer = !!peer.csqtt_password || (peer.targets || []).some(t => t.type === "csqtt");
  const isKeyless = isWdttPeer || isCsqttPeer;   // self-contained turn peers: panel-owned password, no browser keypair
  const rotate = () => {
    if (isKeyless) {   // keyless turn peer: no browser keypair — rotate the panel-owned access password (revokes the old link)
      const rotateApi = isCsqttPeer ? api.csqttPeerRotate : api.wdttPeerRotate;
      openConfirm({ title: T("Rotate link"), confirmLabel: T("Rotate link"), warn: true,
        body: isCsqttPeer
          ? T("A fresh access password is generated. The current csqtt link stops working — send the user their new link (from the subscription page) to re-import.")
          : T("A fresh access password is generated. The current WDTT link stops working — send the user their new link (from the subscription page) to re-import."),
        onConfirm: () => { setRotating(true); rotateApi({ peer_id: peer.id }).then(async r => { await Store.poll(); setRotating(false); toast(r && r.ok ? T("Link rotated — the old one no longer works.") : (srvText(r) || T("Rotate failed.")), r && r.ok ? "ok" : "err"); }).catch(() => setRotating(false)); } });
      return;
    }
    openConfirm({ title: T("Rotate keys"), confirmLabel: T("Rotate keys"), warn: true,
      body: T("A fresh keypair and preshared key are generated. The current config stops working — you'll need to send out the fresh QR / config to re-import. Useful if a config may have leaked."),
      onConfirm: () => {
        // confirm pops back to the edit sheet (its parent); the rotate runs and reports via a toast. The button
        // reads "Rotating keys…" meanwhile, and the poll refreshes the LIVE pubkey — which re-runs the config
        // load, clearing the "private key isn't available" notice and filling in the real form fields.
        setRotating(true);
        rotatePeerKeys(peer).then(async () => {
          await Store.poll();
          setRotating(false);
          const re = Store.rowErrors["peer:" + peer.id];
          toast(re ? (re.msg || T("Rotate failed.")) : T("Keys rotated — send the user the new QR / config; the old one no longer works."), re ? "err" : "ok");
        }).catch(() => setRotating(false));
      } });
  };

  // A dangling / broken deployment replaces "Rotate keys" with its fix (Restore recreates the missing
  // interface; Correct reassigns an in-subnet IP) — targeting the deployment the edit is focused on, or the
  // first problem deployment when it's not target-scoped. Otherwise the normal Rotate-keys button shows.
  const _rp = Store.peer(peer.id) || peer;
  const _isGhostT = t => { const g = t && ghostIface(t.node, t.iface); return !!(g && g.ripe); };
  const _fixT = (focus && (_rp.targets || []).find(t => t.node === focus.node && t.iface === focus.iface))
             || (_rp.targets || []).find(t => t.restorable || t.correctable || _isGhostT(t)) || null;
  const fixBtn = _isGhostT(_fixT)
    ? html`<button class="btn btn-ghost gh" onClick=${() => openRecreateRekey(_fixT.node, _fixT.iface)}><${Ic} i="refresh"/> ${T("Recreate & rekey interface")}</button>`
    : (_fixT && _fixT.restorable)
      ? html`<button class="btn btn-ghost restore" onClick=${() => confirmRestoreDeployment(_rp, _fixT)}><${Ic} i="refresh"/> ${T("Restore interface")}</button>`
      : (_fixT && _fixT.correctable)
        ? html`<button class="btn btn-ghost correct" onClick=${() => confirmCorrectDeployment(_rp, _fixT)}><${Ic} i="check"/> ${T("Fix address")}</button>`
        : html`<button class="btn btn-ghost" disabled=${rotating} onClick=${rotate}><${Ic} i="key"/> ${rotating ? (isKeyless ? T("Rotating link…") : T("Rotating keys…")) : (isKeyless ? T("Rotate link") : T("Rotate keys"))}</button>`;
  return html`<${Sheet} title=${T("Edit peer")} width=${700} onClose=${done} onBack=${child ? done : null} subject=${{ kind: "peer", id: peer.id }}
    foot=${footRow({ left: html`${editable && !isKeyless ? html`<button class="btn btn-ghost" onClick=${() => openPeerConfigs(peer, { child: true })}><${Ic} i="qr"/>QR</button>` : null}${isKeyless ? null : html`<button class="btn btn-ghost" onClick=${() => openAddTarget(peer)}><${Ic} i="copy"/> ${T("Targets")}</button>`}${fixBtn}${peerBlockBtn(peer)}`, onCancel: done, disabled: busy || !_dirty, title: _dirty ? "" : T("No changes to save"), onAction: save, action: T("Save") })}>
    <${PeerStatusLine} peer=${peer} pos="bar"/>
    <div class="field"><label>${T("col|Title")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— optional")}</span></label><input autofocus value=${title} maxlength="64" onInput=${e => setTitle(e.target.value)} placeholder=${T("e.g. iPhone, Work laptop")}/></div>
    <div class="field"><label>${T("col|User")}</label>
      <${UserPicker} value=${userId} allowUnassigned=${!peer.unassigned} onChange=${setUserId}/>
      <div class=${"hint"}>${
        peer.unassigned ? T("Pick a user to assign this peer to — the existing key and config are kept, applied when you Save.")
        : (userId || "") === (peer.user_id || "") ? T("Reassigning rotates the keys; you'll confirm on Save and the new user needs a fresh config.")
        : !userId ? T("On Save you'll confirm unassigning — access is revoked and the keys rotate.")
        : T("On Save you'll confirm reassigning — the current user loses access for good and the new user needs a fresh config.")
      }</div></div>
    <div class="field"><label>${T("Access expires")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— this peer only; blank = {fallback}", { fallback: ownerExp ? T("follows the subscription") : T("never") })}</span></label>
      <div class="daterow"><input type="date" class="datein" max=${ownerExp ? expiryInputVal(ownerExp) : ""} value=${expDate} onInput=${e => setExpDate(e.target.value)}/>${expDate ? html`<button class="btn btn-ghost btn-mini" onClick=${() => setExpDate("")}>${T("Clear")}</button>` : null}</div>
      <div class=${"hint"}>${T("On this date the peer stops working (it reappears if you extend it).")}${ownerExp ? T(" Can't be later than the subscription's expiry ({v1}).", { v1: fmtDate(ownerExp) }) : ""}</div></div>
    ${isKeyless ? html`<div class="field"><label>${T("Servers")}</label>
      <div class="targetpick">${targetsOrdered.map(t => html`<div class="targetopt sel locked" key=${tkey(t.node, t.iface)}>
        <div class="topt-main"><span class="box"><${Ic} i="check"/></span><span class="nm" style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span><span class="tp">${t.iface}</span></div>
        <${TargetFrontBadge} node=${t.node} iface=${t.iface}/>
        <span class="topt-ip faint" title=${isCsqttPeer ? T("csqtt assigns the address on connect") : T("WDTT assigns the address on connect")}>${T("val|auto")}</span>
      </div>`)}</div>
      <div class="hint">${isCsqttPeer
        ? T("csqtt servers this user reaches. csqtt assigns each server's address on connect; the user's link per server is on their subscription. No client config (key/DNS/MTU) — csqtt owns the datapath.")
        : T("WDTT servers this user reaches. WDTT assigns each server's address on connect; the user's link per server is on their subscription. No client config (key/DNS/MTU) — WDTT owns the datapath.")}</div>
    </div>` : html`<${Fragment}>
    <div class="field"><label>${T("Addresses")}</label>
      <div class="targetpick">${targetsOrdered.map(t => {
        const k = tkey(t.node, t.iface);
        const im = (Store.describe[t.node] || {})[t.iface] || {};
        const ity = (im.awg_params && Object.keys(im.awg_params).length) ? "awg" : "wg";
        return html`<div class="targetopt sel locked" key=${k}>
          <div class="topt-main"><span class="box"><${Ic} i="check"/></span><span class="nm" style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span><span class="tp">${t.iface}</span></div>
          <${PrimaryToggle} peer=${peer} t=${t} compact=${true}/>
          <${PubTag} peer=${live} src=${targetType(t)} label=${ity}/>
          ${turnEnabled() && turnProxiesFor(t.node, t.iface).length ? html`<${PubTag} peer=${live} src="turn" label=${T("val|turn")}/>` : null}
          <${TargetFrontBadge} node=${t.node} iface=${t.iface}/>
          <input class=${"topt-ip " + (ipBadFor(t) ? "bad" : "")} value=${ips[k] || ""} onInput=${e => setIpFor(k, e.target.value)}/>
        </div>`;
      })}</div>
      <div class="hint">${T("Changing an address moves the peer on that interface.")}</div>
    </div>
    ${!loaded ? html`<div class="loading"><span class="spin"></span>${T("loading config…")}</div>`
      : !editable ? html`<div class="notice warn"><${Ic} i="warn"/><span>${T("The client's private key isn't available, so DNS / MTU / routing can't be rebuilt")}${Store.storeConfigs ? "" : T(" (enable store_configs, or edit right after creating)")}${T(". Title and address can still change.")}</span></div>`
      : html`<${Fragment}>
        <div class="field"><label>${T("Client allowed IPs (routing)")}</label><input class=${errs.allowed ? "bad" : ""} value=${allowed} onInput=${e => setAllowed(e.target.value)}/><div class=${"hint" + (errs.allowed ? " err" : "")}>${errs.allowed || T("Full tunnel by default. Narrow for split tunnel.")}</div></div>
        <div class="field"><label>DNS</label><input class=${errs.dns ? "bad" : ""} value=${dns} onInput=${e => setDns(e.target.value)} placeholder=${T("e.g. 1.1.1.1, 1.0.0.1")}/><div class=${"hint" + (errs.dns ? " err" : "")}>${errs.dns || T("Comma-separated IPs. Blank = no DNS line.")}</div></div>
        <div class="row2">
          <div class="field"><label>MTU</label><input class=${errs.mtu ? "bad" : ""} value=${mtu} onInput=${e => setMtu(e.target.value)} placeholder="1280"/><div class=${"hint" + (errs.mtu ? " err" : "")}>${errs.mtu || "Blank = 1280."}</div></div>
          <div class="field"><label>${T("Persistent keepalive (s)")}</label><input class=${errs.keepalive ? "bad" : ""} value=${keepalive} onInput=${e => setKeepalive(e.target.value)} placeholder="25"/><div class=${"hint" + (errs.keepalive ? " err" : "")}>${errs.keepalive || T("0 disables · blank = 25.")}</div></div>
        </div>
      <//>`}
    <//>`}
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// ── node sheets ──
export function openNodeCreate() { openModal(html`<${NodeCreateSheet}/>`); }
/* Sentences with a styled run (a bold name, a bold warning, a link) inside them. Each is ONE key with a
   marker, split around the styled element — see Tsplit in js/i18n.js. */
function recoversAs(name, method) {
  const [a, r1] = Tsplit("This recovers {name} as {method} — the method it was already running, so its turn-proxies and interfaces are kept. To switch methods, convert the node instead.", "name");
  const [b, c] = [r1.split("{method}")[0], r1.split("{method}").slice(1).join("{method}")];
  return html`<${Fragment}>${a}<b>${name}</b>${b}<b>${method}</b>${c}<//>`;
}
function meshElsewhere() {
  const [a, b] = Tsplit("Mesh settings (ingress IP, subnet, port, prefix, AWG) for this node are configured in {where} — select this node there.", "where");
  return html`<${Fragment}>${a}<a href="#/panel/settings">${T("Panel settings → Mesh & egress")}</a>${b}<//>`;
}
function recoverSameNode(name) {
  const [a, r1] = Tsplit("This node isn't reporting. Generating a recovery command rotates its token and gives you a one-line command to paste on the server — it re-installs/recovers {name} as the {same}, so its interfaces and peers come straight back (no need to find the old token).", "name");
  const [b, c] = [r1.split("{same}")[0], r1.split("{same}").slice(1).join("{same}")];
  return html`<${Fragment}>${a}<b>${name}</b>${b}<b>${T("same node")}</b>${c}<//>`;
}
/* The count is bold and its clause changes with the number, so English needs two whole sentences (a plural
   table cannot fix "1 peers is dropped"); Russian gets its three forms from plural() inside one of them. */
function forceRemoveWarn(name, onlyHere) {
  const dropped = onlyHere
    ? T("{n} that live only here are dropped", { n: plural(onlyHere, "peer") })
    : T("peers that live only here are dropped");
  const [a, r1] = Tsplit("This cuts {name} off {now} without waiting for it to confirm — {dropped}. Use this only when the server is unreachable. This can't be undone.", "name", { dropped });
  const [b, c] = [r1.split("{now}")[0], r1.split("{now}").slice(1).join("{now}")];
  return html`<${Fragment}>${a}<b>${name}</b>${b}<b>${T("immediately")}</b>${c}<//>`;
}
function typeToConfirm(phrase) {
  const [a, b] = Tsplit("Type {phrase} to confirm", "phrase");
  return html`<${Fragment}>${a}<span class="mono" style="text-transform:none">${phrase}</span>${b}<//>`;
}
function flaggedForRemoval() {
  const [a, r1] = Tsplit("{flagged} Run the command below on the node — it'll sign off and disappear here automatically. If you've lost access to the server, use {force} to cut it off.", "flagged");
  const [b, c] = [r1.split("{force}")[0], r1.split("{force}").slice(1).join("{force}")];
  return html`<${Fragment}>${a}<b>${T("Flagged for removal.")}</b>${b}<b>${T("Force remove now")}</b>${c}<//>`;
}

export function NodeCreateSheet() {
  const [name, setName] = useState(""); const [color, setColor] = useState({ ...NODE_CREATE_DEFAULT }); const [msg, setMsg] = useState(null);
  const nameBad = name.trim() && !V.nodeName(name);
  const create = async () => {
    if (!name.trim()) return setMsg({ k: "err", t: T("Give the node a name.") });
    if (!V.nodeName(name)) return setMsg({ k: "err", t: "Name: 1–40 chars, letters/digits/-/_ only." });
    setMsg({ k: "work", t: "creating…" });
    const r = await api.nodeCreate({ name: name.trim(), endpoint_host: "", color });
    if (!r.ok) return setMsg({ k: "err", t: srvText(r) || T("couldn't create node") });
    await Store.poll(); openModal(html`<${NodeTokenSheet} name=${r.data.name} token=${r.data.token} isNew=${true}/>`);
  };
  return html`<${Sheet} title=${T("Add node")}
    foot=${footRow({ onCancel: closeModal, onAction: create, action: T("Create node") })}>
    <div class="field"><label>${T("Name")}</label>
      <div class="namerow"><input autofocus class=${nameBad ? "bad" : ""} value=${name} onInput=${e => setName(e.target.value)} placeholder="msk-edge1" autocomplete="off"/>
        <${ThemedSwatch} val=${color} title=${T("Node colour")} onChange=${setColor} sample=${(c) => html`<span class="tg" style=${"background:color-mix(in srgb," + c + " 16%,transparent);color:" + c}>${name.trim() || "node"}</span>`}/></div>
      <div class=${"hint" + (nameBad ? " err" : "")}>${nameBad ? "1–40 chars: letters, digits, - or _ only." : T("A label for this node — you can rename it anytime. The swatches set its colour per theme.")}</div></div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}
export const BOOTSTRAP_URL = "https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh";
export function NodeTokenSheet({ name, token, isNew, kind }) {
  const host = `${location.origin}${BASE}`;
  const bare = `curl -fsSL ${BOOTSTRAP_URL} | sudo bash -s node -key ${token} -host ${host}`;
  const docker = `curl -fsSL ${BOOTSTRAP_URL} | sudo bash -s docker node -key ${token} -host ${host}`;
  // recover/rotate of an existing node → show ONLY its method's command (a docker box re-installed as
  // bare, or vice-versa, would NOT carry its turn-proxies over — that's a deliberate convert, not this).
  const cmds = kind === "docker" ? [[T("kind|docker"), docker, "#c084e8"]]
    : kind === "baremetal" ? [[T("kind|bare-metal"), bare, "#60a5fa"]]
    : [[T("kind|bare-metal"), bare, "#60a5fa"], [T("kind|docker"), docker, "#c084e8"]];
  return html`<${Sheet} title=${(isNew ? T("Node created") : T("New token")) + " · " + name}
    foot=${html`<button class="btn btn-primary" onClick=${closeModal}>${T("Done")}</button>`}>
    <div class="notice warn"><${Ic} i="warn"/><span><b>${T("Shown once.")}</b> ${T("This token authenticates the node to the panel — copy it now. You can rotate it later if it leaks.")}</span></div>
    ${kind ? html`<div class="hint" style="margin-top:9px">${recoversAs(name, kind === "docker" ? T("kind|docker") : T("kind|bare-metal"))}</div>` : null}
    <div class="field" style="margin-top:15px"><label>${T("Enrollment token")}</label><div class="cmdrow"><div class="tokenbox">${token}</div><button class="copyaction" onClick=${() => copy(token, T("Copied"))}><${Ic} i="copy"/> ${T("Copy")}</button></div></div>
    ${cmds.map(([label, cmd, color]) => html`<div class="field"><label>${T("Run on the node —")} <span style=${"color:" + color + ";font-weight:700"}>${label}</span></label><div class="cmdrow"><div class="tokenbox">${cmd}</div><button class="copyaction" onClick=${() => copy(cmd, T("Copied"))}><${Ic} i="copy"/> ${T("Copy")}</button></div></div>`)}
    ${kind ? null : html`<div class="hint">${T("Pick one. Both fetch the installer and prompt for the node's endpoint.")}</div>`}
  <//>`;
}
export function openNodeEdit(node) { openModal(html`<${NodeEditSheet} node=${node}/>`); }

export function NodeEditSheet({ node }) {
  const rsv = (Store.panelSettings || {}).reserved || {};   // panel-wide defaults (used when the node has no override)
  const dSub = rsv.mesh_subnet || "10.255.0.0/16", dPort = String(rsv.mesh_port_base || 9999), dPfx = rsv.iface_prefix || "swg_";
  const [name, setName] = useState(node.name || ""); const [color, setColor] = useState(() => toThemed(node.color, NODE_COLOR_DEFAULT)); const [msg, setMsg] = useState(null);
  const [ingress, setIngress] = useState(node.endpoint_host || "");
  // mesh fields show the EFFECTIVE value in use (the node's override, else the panel default). Leaving it at
  // the default normalizes to "inherit" on save (no spurious override / re-provision).
  const [meshPort, setMeshPort] = useState(node.mesh_port ? String(node.mesh_port) : dPort);
  const [meshSubnet, setMeshSubnet] = useState(node.mesh_subnet || dSub);
  const [meshPrefix, setMeshPrefix] = useState(node.mesh_prefix || dPfx);
  const [defEgress, setDefEgress] = useState(node.default_egress_ip || "");
  const [panelIp, setPanelIp] = useState(node.panel_ip || "");
  const ips = node.ips || [];
  const ovSub = meshSubnet.trim() === dSub ? "" : meshSubnet.trim();   // normalized overrides (default → inherit)
  const ovPort = meshPort.trim() === dPort ? "" : meshPort.trim();
  const ovPfx = meshPrefix.trim() === dPfx ? "" : meshPrefix.trim();
  const nameBad = name.trim() && !V.nodeName(name);
  // Only a subnet or PREFIX change re-provisions (re-addresses / renames the iface → rebuild). A port-only
  // change is applied LIVE (the node re-ports in place + peers re-dial), so it needs no re-provision confirm.
  const reprovChanged = ovSub !== (node.mesh_subnet || "") || ovPfx !== (node.mesh_prefix || "");
  const doSave = () => {
    closeAllModals();   // close the sheet AND any re-provision confirm stacked on top; optimistic — the card reflects the change immediately
    mutate({
      key: "node:" + node.id,
      patch: s => { const n = s.nodes.find(x => x.id === node.id); if (n) { n.name = name.trim(); n.color = color; n.endpoint_host = ingress; n.mesh_port = ovPort; n.mesh_subnet = ovSub; n.mesh_prefix = ovPfx; n.default_egress_ip = defEgress; n.panel_ip = panelIp; } },
      call: () => api.nodeUpdate({ id: node.id, name: name.trim(), color, endpoint_host: ingress, mesh_port: ovPort, mesh_subnet: ovSub, mesh_prefix: ovPfx, default_egress_ip: defEgress, panel_ip: panelIp }),
    });
  };
  const save = async () => {
    if (!name.trim() || !V.nodeName(name)) return setMsg({ k: "err", t: "Name: 1–40 chars, letters/digits/-/_ only." });
    if (reprovChanged) {   // re-provisioning bounces this node's mesh links → confirm first
      return pushModal(html`<${ConfirmSheet} title=${T("Re-provision this node's mesh links?")} confirmLabel=${T("Re-provision")} warn=${true}
        body=${T("Changing the mesh subnet / port / prefix of {v1} rebuilds all of its node-to-node links with the new settings.", { v1: node.name }) + " " + T("{v1} will briefly drop off the mesh (and any cascade/smart traffic routed through it pauses) until every peer pulls the new config and reconnects — usually a few seconds. Other nodes' links to each other are unaffected.", { v1: node.name })}
        onConfirm=${doSave}/>`);
    }
    doSave();
  };
  const [showAwg, setShowAwg] = useState(false);
  return html`<${Sheet} title=${T("Node settings · {v1}", { v1: node.name })}
    foot=${footRow({ left: html`<button class="btn btn-ghost" title=${T("Rotate this node's enrollment token (re-enroll / re-install)")} onClick=${() => openNodeRotate(node)}><${Ic} i="key"/> ${T("Rotate key")}</button>`, onCancel: closeModal, onAction: save, action: T("Save") })}>
    <div class="field"><label>${T("Name")}</label>
      <div class="namerow"><input autofocus class=${nameBad ? "bad" : ""} value=${name} onInput=${e => setName(e.target.value)} autocomplete="off"/>
        <${ThemedSwatch} val=${color} title=${T("Node colour")} onChange=${setColor} sample=${(c) => html`<span class="tg" style=${"background:color-mix(in srgb," + c + " 16%,transparent);color:" + c}>${name.trim() || node.name || "node"}</span>`}/></div>
      <div class=${"hint" + (nameBad ? " err" : "")}>${nameBad ? "1–40 chars: letters, digits, - or _ only." : T("A label for this node — rename anytime, nothing else changes. The swatches set its colour per theme.")}</div></div>
    <div class="seclabel">${T("Egress")}</div>
    <div class="field"><label>${T("Default egress IP")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— direct internet exit")}</span></label>
      <${NodeIpPick} ips=${ips} value=${defEgress} onChange=${setDefEgress} auto=${T("Auto (MASQUERADE)")}/>
      <div class="hint">${T("The fallback source IP this node SNATs to when traffic exits to the internet here — applied to any interface (and traffic received from other nodes) that doesn't set its own egress IP. Interfaces with their own egress IP, and cascading traffic that exits elsewhere, are unaffected.")}</div></div>
    <div class="field"><label>${T("Panel egress connection IP")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— source to reach the panel")}</span></label>
      <${NodeIpPick} ips=${ips} value=${panelIp} onChange=${setPanelIp} auto=${T("Auto (default route)")}/>
      <div class="hint">${T("Source IP this node uses to reach the panel. Ignored on same-server installs; falls back to auto if it can't connect.")}</div></div>
    <div class="hint" style="margin-top:14px">${meshElsewhere()}</div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}
export function openNodeRecover(node) { openModal(html`<${NodeRecoverSheet} node=${node}/>`); }
export function NodeRecoverSheet({ node }) {
  const go = async () => { const r = await api.nodeRotate({ id: node.id }); if (!r.ok) { toast(srvText(r) || T("couldn't generate a recovery command"), "err"); return; } openModal(html`<${NodeTokenSheet} name=${node.name} token=${r.data.token} isNew=${false} kind=${node.kind}/>`); };
  return html`<${Sheet} title=${T("Recover node · {v1}", { v1: node.name })}
    foot=${footRow({ onCancel: closeModal, onAction: go, action: T("Generate recovery command") })}>
    <div class="notice"><${Ic} i="info"/><span>${recoverSameNode(node.name)}</span></div>
    <div class="notice warn" style="margin-top:10px"><${Ic} i="warn"/><span>${T("The node's current token stops working immediately — use this only when the node is genuinely down or you've lost its install command.")}</span></div>
  <//>`;
}
export function openNodeRotate(node) { openModal(html`<${NodeRotateSheet} node=${node}/>`); }
export function NodeRotateSheet({ node }) {
  const go2 = async () => { const r = await api.nodeRotate({ id: node.id }); if (!r.ok) { toast(srvText(r) || T("rotate failed"), "err"); return; } openModal(html`<${NodeTokenSheet} name=${node.name} token=${r.data.token} isNew=${false} kind=${node.kind}/>`); };
  return html`<${Sheet} title=${T("Rotate token · {v1}", { v1: node.name })}
    foot=${footRow({ onCancel: closeModal, onAction: go2, action: T("Rotate") })}>
    <div class="notice warn"><${Ic} i="warn"/><span>${T("The current token stops working immediately. Re-enroll the node with the new token or it will go offline.")}</span></div>
  <//>`;
}
export function openNodeRemove(node) { openModal(html`<${NodeRemoveSheet} node=${node}/>`); }
export function unflagNode(n) {   // cancel a pending soft removal — keep the node
  mutate({
    key: "node:" + n.id,
    patch: s => { const x = s.nodes.find(y => y.id === n.id); if (x) { delete x.removing; delete x.removing_at; } },
    call: () => api.nodeUnflagRemove({ id: n.id }),
  });
}
// Force-remove a node — destructive (cuts it off immediately + drops peers that live only here), so gated behind typing "DELETE <name>" (case-sensitive), like deleting an interface/turn-proxy.
export function ForceRemoveNodeSheet({ node }) {
  const [txt, setTxt] = useState(""); const [busy, setBusy] = useState(false);
  const phrase = T("DELETE {v1}", { v1: node.name });
  const ok = txt === phrase;
  const here = Store.recon.peers.filter(p => p.targets.some(t => t.node === node.id));
  const onlyHere = here.filter(p => new Set(p.targets.map(t => t.node)).size === 1).length;
  const del = () => {
    if (!ok || busy) return;
    setBusy(true); closeAllModals();
    mutate({
      key: "node:" + node.id,
      patch: s => {                                  // optimistic: drop the node + purge its targets (mirrors the cascade)
        s.nodes = s.nodes.filter(x => x.id !== node.id);
        for (const id of Object.keys(s.roster.peers)) {
          const p = s.roster.peers[id]; p.targets = p.targets.filter(t => t.node !== node.id);
          if (!p.targets.length) delete s.roster.peers[id];
        }
      },
      call: () => api.nodeDelete({ id: node.id }),
    });
    toast(T("Node force-removed."), "ok");
  };
  return html`<${Sheet} title=${T("Force remove · {v1}", { v1: node.name })}
    foot=${footRow({ onCancel: closeModal, danger: true, disabled: !ok || busy, onAction: del, action: T("Force remove") })}>
    <div class="notice warn"><${Ic} i="warn"/><span>${forceRemoveWarn(node.name, onlyHere)}</span></div>
    <div class="field"><label>${typeToConfirm(phrase)}</label><input autofocus value=${txt} onInput=${e => setTxt(e.target.value)} placeholder=${phrase} autocomplete="off" spellcheck="false"/></div>
  <//>`;
}
export function NodeRemoveSheet({ node }) {
  const [flagged, setFlagged] = useState(!!node.removing);
  const here = Store.recon.peers.filter(p => p.targets.some(t => t.node === node.id));
  const onlyHere = here.filter(p => new Set(p.targets.map(t => t.node)).size === 1).length;
  const note = !here.length ? T("No peers reference it.")
    : onlyHere ? T("{v1} reference it; {n} live only here and will be dropped.", { v1: plural(here.length, "peer"), n: onlyHere })
    : T("{v1} reference it.", { v1: plural(here.length, "peer") });
  const uninstall = `curl -fsSL ${BOOTSTRAP_URL} | sudo bash -s uninstall`;
  const flag = () => { setFlagged(true); mutate({
    key: "node:" + node.id,
    patch: s => { const n = s.nodes.find(x => x.id === node.id); if (n) n.removing = true; },
    call: () => api.nodeFlagRemove({ id: node.id }),
  }); };
  const force = () => pushModal(html`<${ForceRemoveNodeSheet} node=${node}/>`);   // typed "DELETE <name>" confirmation (matches interface/turn-proxy deletes)
  return html`<${Sheet} title=${T("Remove {v1}", { v1: node.name })}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>${T("Close")}</button>
      ${flagged ? null : html`<button class="btn btn-primary" onClick=${flag}>${T("Flag for removal")}</button>`}
      <button class="btn btn-danger" onClick=${force}>${T("Force remove now")}</button></>`}>
    ${flagged
      ? html`<div class="notice"><${Ic} i="info"/><span>${flaggedForRemoval()}</span></div>`
      : html`<div class="notice"><${Ic} i="info"/><span>${T("Clean removal: flag the node, then run the uninstall command on the server. The node keeps serving its {v1} until it confirms, then drops itself from the panel.", { v1: plural(here.length, "peer") })} ${note}</span></div>`}
    <div class="field" style="margin-top:14px"><label>${T("Run on the node to uninstall + sign off")}</label>
      <div class="cmdrow"><div class="tokenbox">${uninstall}</div><button class="copyaction" onClick=${() => copy(uninstall, T("Copied"))}><${Ic} i="copy"/> ${T("Copy")}</button></div>
      <div class="hint">${T("Removes swg-noded / swg-agent and tells the panel it's gone. Force remove is for when the server is unreachable.")}</div></div>
  <//>`;
}
