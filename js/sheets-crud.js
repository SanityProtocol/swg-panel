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
         turnProxiesFor, tgtXfer, tgtSeenAge, kindLabel, platformLabel, peerUncategorised } from "./model.js";
import { turnFork, turnColor, turnForkList } from "./turn-catalog.js";
import { Ic, ICON, Tag, Panel, Badge, Sheet, footRow, secTitle, SearchBox, Switch, Dropdown, Disclosure, autoGrow, IpPicker, NodeIpPick, Popover, Portal, toast, copy, mutate, openModal, pushModal, closeModal, closeAllModals, openConfirm, openChildOrRoot, ConfirmSheet, subjectBlocked, statusLabel, LogBody, RowError, useAnchoredList, goSettings, ThemedSwatch, modalDepth, rowSingle, rowDouble, rowNoSelect, rateCell, xferCell, gridStatusBadge, uncatPop, badgeWithReason, blockedReason, statusReason, dlul, typeToConfirm, closeModals, ListPager, LIST_PAGE, pageSlice } from "./ui.js";
import {
  genKeys, genPSK, buildConf, parseFullConf, downloadConf, getConfig, configOverrides, QR, qrDataURL,
  subFeatureOn, subPublishOrPrompt, ensureVaultUnlocked, subSKCached, VaultPromptSheet, ensurePeerBlob,
  SubAutoNote, anySessionConf, subAutoGenIfEnabled, subReconcileUser,
} from "./crypto.js";
import {
  confirmDeletePeer, confirmUnassign, peerBlockBtn, userBlockBtn, PeerStatusLine, SubStatusLine,
  fmtDate, expiryInputVal, expiryFromInput, UserCombo, UserPicker, RoleToggle, assignPeer,
  confirmReassign, confirmCorrectDeployment, confirmRestoreDeployment, openRecreateRekey, rotatePeerKeys, PubTag,
  pubState, pubCls,
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
    setBusy(true); setMsg({ k: "work", t: T("creating…") });
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
        <span class="pg2-c pg2-tags">${t.node ? (mode === "mine"
          // On the user's OWN peers these tags are the publish switches for that kind of config, exactly as
          // they are on the deployment cards — the operator was already used to clicking them there and had
          // to leave this sheet to do it. Left plain in the unassigned pool: publishing is about what a
          // HOLDER is offered, and an unassigned peer has no holder for the switch to mean anything to.
          ? html`<${TargetFrontBadge} node=${t.node} iface=${t.iface} peer=${p} dim=${!t.online}/><${PubTag} peer=${p} src=${targetType(t)} label=${targetType(t)} dim=${!t.online}/>`
          : html`<${TargetFrontBadge} node=${t.node} iface=${t.iface}/><${Tag} kind=${targetType(t)} label=${targetType(t)}/>`) : null}</span>
        <span class="pg2-c pg2-ifn">${t.node ? t.iface : ""}</span>
        <span class="pg2-c pg2-ip">${t.node ? (String(t.ip || "").split("/")[0] || "—") : ""}</span>
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
    Store.byNode(rep(a).node, rep(b).node) ||
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

  return html`<${Sheet} title=${userName ? T("Add peers · {v1}", { v1: userName }) : T("Add peers")} width=${800}>
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
  // WDTT/csqtt servers own their interface, which isn't a panel-managed WG iface (so it's absent from
  // `describe`) — add each so it is selectable as a (keyless) peer target.
  //
  // ⚠️ From the PANEL'S OWN instance map, not the node's live readback. A node can be running an instance
  // this panel knows nothing about — a box that moved fleets carries its old panel's servers across — and
  // the password set is derived per instance FROM THAT MAP (desired_wdtt_for_node), so a peer deployed to
  // one is inert: no password is ever shipped, while the deployment reports Ready because a keyless target
  // has no wg peer to observe. Offering it was offering a dead end. Such an instance has to be adopted
  // first; the panel's map is also populated the moment one is created, so nothing legitimate is lost.
  for (const n of (Store.nodes || [])) {
    for (const iface of Object.keys(n.wdtt_cfg || {}))
      if (!out.some(t => t.node === n.id && t.iface === iface)) out.push({ node: n.id, iface });
    for (const iface of Object.keys(n.csqtt_cfg || {}))
      if (!out.some(t => t.node === n.id && t.iface === iface)) out.push({ node: n.id, iface });
  }
  return out;
}

// What sits IN FRONT of a target interface, as one badge — so a targets grid says what a peer will actually
// connect through, not just which interface it lands on. Two cases, never both:
//   WDTT  — the server owns the interface: its operator title, else the fork name, in that fork's colour.
//   turn  — one proxy: its title, else the fork name, in that fork's colour. SEVERAL: a neutral "turn" badge
//           (naming one of several would be a lie), with the full list on hover.
// Nothing in front → nothing rendered; a plain wg/awg interface keeps the grid quiet.
// The badge naming what fronts a deployment. For a wg/awg target that is its turn-proxies — and since that IS
// the peer's "turn" config source, passing `peer` makes the badge itself the publish switch for it. One chip:
// a separate TURN toggle beside a "turn ×3" badge said the same thing twice.
export function TargetFrontBadge({ node, iface, peer, dim }) {
  useStore();          // it is a publish switch when `peer` is set — without this it never re-renders after a toggle
  if (!node || !iface) return null;
  if (kindOf(node, iface, null) === "wdtt") {
    const nrec = (Store.nodes || []).find(x => x.id === node) || {};
    const cfg = (nrec.wdtt_cfg || {})[iface] || {};
    const live = ((Store.stats[node] || {}).wdtt || []).find(w => w && w.iface === iface) || {};
    const fork = cfg.fork || live.fork || "";
    const label = shownTitle("w|" + node + "|" + iface, String(cfg.title || live.title || "").trim()) || fork;
    if (!label) return null;
    const col = turnColor(fork) || WDTT_COLOR;
    return html`<span class=${"tg tgt-front" + (dim ? " dim" : "")} style=${"--tgc:" + col} title=${T("WDTT server") + (fork ? " · " + fork : "")}>${label}</span>`;
  }
  const tps = turnProxiesFor(node, iface);
  if (!tps.length) return null;
  const one = t => shownTitle("t|" + node + "|" + t.service, t.title) || turnFork(t.service);
  const st = peer ? pubState(peer, "turn") : null;
  // Offline dims this the same way it dims the interface badge beside it — they describe one deployment, so
  // one of them fading while the other stays lit read as a difference in state that isn't there.
  const tag = (body, cls, style, title) => st
    ? html`<button type="button" class=${"tg tgt-front " + pubCls(st, ((cls || "") + (dim ? " dim" : "")).trim())} style=${style} title=${st.title}
        aria-pressed=${!st.hidden} onClick=${e => { e.preventDefault(); e.stopPropagation(); st.flip(); }}>${body}${st.hidden ? html`<${Ic} i="off"/>` : null}</button>`
    : html`<span class=${"tg tgt-front " + (cls || "") + (dim ? " dim" : "")} style=${style} title=${title}>${body}</span>`;
  if (tps.length === 1) {
    const f = turnFork(tps[0].service);
    return tag(one(tps[0]), "", "--tgc:" + (turnColor(f) || "var(--turn)"), T("Turn-proxy") + (f ? " · " + f : ""));
  }
  return html`<${Popover} hoverOnly cls="tgt-frontpop" popCls="tgt-frontbub"
    trigger=${tag(html`<${Fragment}>${T("val|turn")}<b class="turnx">×${tps.length}</b><//>`, "tgt-front-many", "",
                  T("{v1} turn-proxies forward to this interface", { v1: tps.length }))}>
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
  const setOpts = (k, v) => setSel(s => s[k] ? { ...s, [k]: { ...s[k], opts: v } } : s);
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
  // Every interface stays listed whatever is already ticked. A peer used to be locked to ONE kind here —
  // ticking awg0 hid every wg, wdtt and csqtt row — which was a product rule, not a technical limit: the peer
  // record has always held the three credentials side by side and the node reply builders have always been
  // target-driven. One peer may now span wg + awg + wdtt + csqtt, and each row carries its own settings.
  const ordered = [...targets].sort((a, b) =>
    Store.byNode(a.node, b.node) || (a.iface || "").localeCompare(b.iface || ""));
  return html`<div class="targetpick">${ordered.map(t => {
    const k = tkey(t.node, t.iface); const s = sel[k];
    const ity = t.missing ? (t.type || "wg") : iTypeOf(t.node, t.iface);   // wg | awg | wdtt (a WDTT iface isn't in `describe`, so key off the name via iTypeOf)
    return html`<div class=${"targetopt " + (s ? "sel " : "") + (locked ? "locked" : "") + (t.missing ? " missing" : "")}>
      <label class="topt-main" onClick=${locked ? null : () => toggle(t.node, t.iface)}>
        <span class="box">${s ? html`<${Ic} i="check"/>` : ""}</span>
        <span class="nm" style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span>
        <span class="tp">${t.iface}</span>
        ${t.missing ? html`<span class="topt-missing" title=${T("This interface is gone from the node — uncheck to remove this deployment from the peer")}>${T("tag|missing")}</span>` : null}</label>
      <div class="topt-right hasprim">
        ${(pubPeer && pubHave.has(k)) ? html`<${PubTag} peer=${pubPeer} src=${ity} label=${ity}/>` : html`<${Tag} kind=${ity} label=${ity}/>`}
        ${t.missing ? null : html`<${TargetFrontBadge} node=${t.node} iface=${t.iface} peer=${(pubPeer && pubHave.has(k)) ? pubPeer : null}/>`}
        ${(s && (s.wdtt || s.csqtt || isSelfContainedKind(ity)))
          // `ity` (the interface's real type), not just the flag set when a row is TOGGLED: an already-deployed
          // target is seeded straight from the peer, so it never went through toggle and rendered an editable
          // address box for a self-contained server — which mints the client IP itself on connect and can't be told one.
          ? html`<span class="topt-ip faint" title=${T("The server assigns the address on connect")}>${T("val|auto IP")}</span>`
          : (s ? html`<input class=${"topt-ip " + (s.ip && !V.ipv4(s.ip) ? "bad" : "")} value=${s.ip} placeholder=${s.ipHint || "address"} title=${s.ip && !V.ipv4(s.ip) ? T("not a valid IPv4 address") : ""} onInput=${e => setIp(k, e.target.value)}/>` : null)}
        ${(s && !t.missing) ? html`<${TargetGear} node=${t.node} iface=${t.iface} kind=${ity} opts=${s.opts} onSave=${v => setOpts(k, v)} readOnly=${!!s.existing}/>` : null}
      </div>
    </div>`;
  })}</div>`;
}

// CONTROLLED interfaces grid for the Add-peers carousel: `value` = {tkey:{node,iface,ip,existing?}}; `onChange`
// takes a functional updater so an async IP allocation merges against the LATEST selection. `lockExisting` keeps
// already-deployed rows checked + read-only (removing a live deployment isn't done here). Scrolls past 5 rows.

// ── ONE DEPLOYMENT's client-config settings ─────────────────────────────────────────────────────
// AllowedIPs / DNS / MTU / keepalive used to be ONE block at the bottom of the peer sheet, applying to the
// whole peer. That worked only while a peer was all of one kind. Now that a peer can hold wg + awg + wdtt +
// csqtt at once, a single block would show fields that are meaningless for some of that same peer's
// deployments — WDTT and csqtt mint the client address on connect and have no client config at all — so the
// settings moved to where they were always true: the individual deployment, behind the gear on its row.
// wdtt/csqtt rows have no gear, which is the whole confusion designed out. A side effect worth having: two
// deployments of one peer can now route differently (full tunnel on one interface, split on another).
export const tgtDefaults = (meta) => ({
  dns: ((meta || {}).dns || []).join(", "), mtu: String((meta || {}).mtu || 1280),
  // keepalive reads the interface like dns/mtu do. It used to be a hardcoded "25", so the gear seeded 25
  // over an interface set to something else and configOverrides then stored that 25 as a customisation.
  keepalive: String((meta || {}).keepalive != null ? (meta || {}).keepalive : 25),
  allowed: "0.0.0.0/0, ::/0",   // an interface has no AllowedIPs to inherit — routing belongs to the client
});
// Does this deployment differ from its interface's defaults? Drives the gear's "customised" dot, so an
// operator can see which rows carry settings without opening each one.
export const tgtCustomised = (opts, meta) => !!(opts && Object.keys(configOverrides(opts, meta)).length);

export function openTargetSettings({ node, iface, opts, meta, onSave, readOnly }) {
  pushModal(html`<${TargetSettingsSheet} node=${node} iface=${iface} opts=${opts} meta=${meta} onSave=${onSave} readOnly=${readOnly}/>`);
}
export function TargetSettingsSheet({ node, iface, opts, meta, onSave, readOnly }) {
  const d = tgtDefaults(meta);
  const [dns, setDns] = useState((opts && opts.dns != null) ? opts.dns : d.dns);
  const [mtu, setMtu] = useState((opts && opts.mtu != null) ? opts.mtu : d.mtu);
  const [keepalive, setKa] = useState((opts && opts.keepalive != null) ? opts.keepalive : d.keepalive);
  const [allowed, setAllowed] = useState((opts && opts.allowed != null) ? opts.allowed : d.allowed);
  const cur = { dns, mtu, keepalive, allowed };
  const errs = configErrors(cur);
  const awgOn = !!(meta && meta.awg_params && Object.keys(meta.awg_params).length);
  const fld = (k, fallback) => html`<div class=${"hint" + (errs[k] ? " err" : "")}>${errs[k] || fallback}</div>`;
  const save = () => { if (Object.keys(errs).length) return; onSave(cur); closeModal(); };
  return html`<${Sheet} title=${T("Settings — {v1}", { v1: iface })} width=${560} onBack=${closeModal}
    foot=${readOnly ? footRow({ onCancel: closeModal, cancelLabel: T("Close"), action: null })
      : footRow({ left: html`<button class="btn btn-ghost" onClick=${() => { setDns(d.dns); setMtu(d.mtu); setKa(d.keepalive); setAllowed(d.allowed); }}>${T("Reset to interface defaults")}</button>`,
                  onCancel: closeModal, onAction: save, action: T("Apply"), disabled: !!Object.keys(errs).length })}>
    <div class="hint" style="margin-bottom:10px">${T("These apply to this deployment only — {v1} on {v2}. The peer's other deployments keep their own.", { v1: iface, v2: Store.nodeName(node) })}</div>
    <div class="field"><label>${T("Client allowed IPs (routing)")}</label>
      <input class=${errs.allowed ? "bad" : ""} disabled=${readOnly} value=${allowed} onInput=${e => setAllowed(e.target.value)}/>${fld("allowed", T("Full tunnel by default. Narrow for split tunnel."))}</div>
    <div class="field"><label>DNS</label>
      <input class=${errs.dns ? "bad" : ""} disabled=${readOnly} value=${dns} onInput=${e => setDns(e.target.value)} placeholder=${T("from server, or e.g. 1.1.1.1")}/>${fld("dns", T("Comma-separated IPs. Blank = no DNS line."))}</div>
    <div class="row2">
      <div class="field"><label>MTU</label><input class=${errs.mtu ? "bad" : ""} disabled=${readOnly} value=${mtu} onInput=${e => setMtu(e.target.value)} placeholder="1280"/>${fld("mtu", T("Blank = 1280."))}</div>
      <div class="field"><label>${T("Persistent keepalive (s)")}</label><input class=${errs.keepalive ? "bad" : ""} disabled=${readOnly} value=${keepalive} onInput=${e => setKa(e.target.value)} placeholder="25"/>${fld("keepalive", T("0 disables · blank = 25."))}</div>
    </div>
    <div class="hint">${awgOn
      ? T("AmneziaWG obfuscation parameters come from the interface itself and are the same for every client on it — change them in the interface's settings.")
      : T("This is a plain WireGuard interface, so it carries no AmneziaWG obfuscation parameters.")}</div>
  <//>`;
}
// The gear that opens the sheet above, for ONE wg/awg row. Returns null for a self-contained kind — WDTT and
// csqtt have no client config to open, and that absence IS the affordance.
export function TargetGear({ node, iface, kind, opts, onSave, readOnly }) {
  if (isSelfContainedKind(kind)) return null;
  const meta = Store.ifaceMeta(node, iface);
  const on = tgtCustomised(opts, meta);
  return html`<button type="button" class=${"btn btn-mini ico topt-gear" + (on ? " on" : "")}
    title=${on ? T("Settings for this deployment (customised)") : T("Settings for this deployment (DNS, MTU, routing)")}
    onClick=${e => { e.preventDefault(); e.stopPropagation(); openTargetSettings({ node, iface, opts, meta, onSave, readOnly }); }}><${Ic} i="gear"/></button>`;
}

// Mint ONE peer per chosen target (own keypair + PSK each), assigned to userId. Builds each
// config in-browser, stashes it in sessionConfigs (so the QR shows), and creates the peer via
// the Phase-2 endpoint. Returns { ok, made, fails:[...] }.

// New peer (mint a fresh keypair) deployed to one OR MORE (node,iface) targets as ONE
// credential (redundancy / failover). For per-interface devices, use a user's "Add peers".
export function openCreatePeer(prefill, child) { (child ? pushModal : openModal)(html`<${CreatePeerSheet} prefill=${prefill || {}}/>`); }
export function CreatePeerSheet({ prefill }) {
  const [chosen, setChosen] = useState([]);
  const [title, setTitle] = useState("");
  const [userId, setUserId] = useState(prefill.user_id || "");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  // One peer, ANY mix of kinds. Each chosen target is classified on its own and gets what IT needs: a wg/awg
  // target an address, a client config and the shared keypair; a wdtt/csqtt target neither (its server mints
  // the address on connect, and the panel-owned access password is its whole credential). The client-config
  // fields that used to sit at the bottom of this sheet now live behind each wg/awg row's gear — see
  // TargetSettingsSheet for why a peer that may not be wholly WireGuard can't have one shared block.
  const kindFor = t => (t.wdtt ? "wdtt" : t.csqtt ? "csqtt" : iTypeOf(t.node, t.iface));
  const keyed = chosen.filter(t => !isSelfContainedKind(kindFor(t)));

  const validate = () => {
    if (!chosen.length) return T("Pick at least one target.");
    const badIp = keyed.find(t => !V.ipv4(String(t.ip || "").trim()));
    if (badIp) return T("Invalid address for {v1}.", { v1: Store.nodeName(badIp.node) + "/" + badIp.iface });
    for (const t of keyed) {                      // each deployment's own settings, validated on its own
      const ce = configErrors(t.opts || tgtDefaults(Store.ifaceMeta(t.node, t.iface)));
      const k = Object.keys(ce)[0];
      if (k) return T("{v1}: {v2}", { v1: t.iface, v2: ce[k] });
    }
    return null;
  };

  const create = async () => {
    const err = validate(); if (err) return setMsg({ k: "err", t: err });
    setBusy(true); setMsg({ k: "work", t: keyed.length ? T("generating key…") : T("creating peer…") });
    let keys = null, pskV = "", tgts, configs, body;
    try {                                            // browser-side crypto/config build is the only awaited part
      if (keyed.length) {
        keys = await genKeys();
        pskV = genPSK();   // PSK is panel-owned & auto-minted; change it via a peer's Rotate keys
      }
      tgts = []; configs = {};
      for (const t of chosen) {
        const kind = kindFor(t);
        if (isSelfContainedKind(kind)) {            // no address, no key, no client config — the server owns all three
          tgts.push({ node: t.node, iface: t.iface, ip: "", type: kind });
          continue;
        }
        const m = Store.ifaceMeta(t.node, t.iface); if (!m) continue;
        const ipClean = String(t.ip).trim().split("/")[0];
        const o = t.opts || tgtDefaults(m);
        const tg = { node: t.node, iface: t.iface, ip: ipClean, type: (m.awg_params && Object.keys(m.awg_params).length) ? "awg" : "wg" };
        const ov = configOverrides(o, m);           // only what differs from THIS interface's defaults is stored
        if (Object.keys(ov).length) tg.overrides = ov;
        tgts.push(tg);
        configs[tkey(t.node, t.iface)] = buildConf({ privkey: keys.priv, address: ipClean + "/32", dns: o.dns.split(",").map(x => x.trim()).filter(Boolean), mtu: String(o.mtu).trim() || 1280, awg_params: m.awg_params, server_pubkey: m.public_key, psk: pskV, endpoint: m.endpoint, allowed: String(o.allowed).trim() || "0.0.0.0/0, ::/0", keepalive: String(o.keepalive).trim() });
      }
      body = { user_id: userId || null, title: title.trim(), pubkey: keys ? keys.pub : "", psk: pskV, targets: tgts };
      // No plaintext to the server: the key stays in the browser (session config for the immediate QR) and is
      // encrypted into the blob by subMaybePublish (below, after the create POST succeeds).
    } catch (e) { setBusy(false); return setMsg({ k: "err", t: T("Error: {v1}", { v1: e.message })}); }
    // Optimistic: stash the config, drop a "creating" peer onto the grid, close the modal NOW, and let
    // the create POST run in the background (mutate reverts + toasts on failure; the next poll supersedes).
    if (keys) Store.sessionConfigs[keys.pub] = Object.assign(Store.sessionConfigs[keys.pub] || {}, configs);
    const tempId = "tmp_" + (keys ? keys.pub.slice(0, 14) : String(Math.random()).slice(2, 16));
    const optimistic = { id: tempId, pubkey: keys ? keys.pub : "", user_id: userId || null, title: title.trim(), psk: pskV,
      targets: tgts.map(t => ({ node: t.node, iface: t.iface, ip: t.ip, type: t.type })),
      created_at: Math.floor(Date.now() / 1000), _creating: true };
    closeModal();
    if (prefill.lock && prefill.node && prefill.iface) go("#/node/" + encodeURIComponent(prefill.node) + "/" + encodeURIComponent(prefill.iface));
    else if (userId) revealUser(userId, tempId);
    mutate({
      patch: s => { s.roster.peers[tempId] = optimistic; },        // shows instantly with status "creating"
      call: () => api.peerCreate(body),
      onOk: r => { if (r && r.data && r.data.id) { Store.recentlyCreated[r.data.id] = Date.now();
        if (keys) subPublishOrPrompt(userId || null, r.data.id, keys.priv, pskV); } },   // encrypt {k,p} → blob (prompt to unlock if locked)
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
    <div class="field"><label>${T("Targets")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— one, or several for redundancy (same credential)")}</span></label>
      <${TargetPicker} prefill=${prefill} onChange=${setChosen}/>
      ${keyed.length ? html`<div class="hint">${T("Use the gear on a row for that deployment's DNS, MTU and routing.")}</div>` : null}</div>
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
  // A peer may now hold a mix of kinds, so a newly-ticked row is only asked for an address when its interface
  // HAS one to give — a wdtt/csqtt server mints the client address on connect.
  const kindFor = c => (c.wdtt ? "wdtt" : c.csqtt ? "csqtt" : iTypeOf(c.node, c.iface));
  const needsIp = c => !isSelfContainedKind(kindFor(c));
  const badIp = added.concat(ipChanged).filter(needsIp).some(c => !c.ip || !V.ipv4(String(c.ip).split("/")[0]));
  const nochange = !added.length && !removed.length && !ipChanged.length;
  // A device that carries networks carries them on EVERY node it is deployed to — so a node added here opens them to that
  // node too, and a node removed takes them away from everyone there. Neither was said.
  const nets = peer.routes || [];
  const netDev = peer.title || ((peer.user_id && Store.user(peer.user_id)) || {}).name || T("This device");
  const netsAdded = nets.length > 0 && added.some(needsIp);
  const netsGone = nets.length ? removed.filter(t => !isSelfContainedKind(targetType(t))) : [];

  const doSave = async () => {
    setBusy(true); setMsg({ k: "work", t: T("applying…") });
    const fails = [];
    for (const t of added) {
      const kind = kindFor(t);
      if (isSelfContainedKind(kind)) {
        // A keyless deployment brings no address and no client config; if this is the peer's first of that
        // kind, the panel mints its access password server-side (mint_keyless_secrets).
        const r = await api.peerAddTarget({ peer_id: peer.id, target: { node: t.node, iface: t.iface, ip: "", type: kind } });
        if (!r.ok) fails.push(Store.nodeName(t.node) + "/" + T("{v1} (add)", { v1: t.iface }));
        continue;
      }
      const info = Store.ifaceMeta(t.node, t.iface);
      const ipClean = String(t.ip || "").split("/")[0];
      const o = t.opts || null;                  // settings the operator set behind this row's gear
      let conf = null;
      if (srcConf) { const s = parseFullConf(srcConf);
        conf = buildConf({ privkey: s.privkey, address: ipClean + "/32", dns: o ? String(o.dns).split(",").map(x => x.trim()).filter(Boolean) : s.dns, mtu: o ? (String(o.mtu).trim() || 1280) : s.mtu, awg_params: info.awg_params, server_pubkey: info.public_key, psk: s.psk || peer.psk, endpoint: info.endpoint, allowed: o ? (String(o.allowed).trim() || "0.0.0.0/0, ::/0") : s.allowed, keepalive: o ? String(o.keepalive).trim() : s.keepalive }); }
      const target = { node: t.node, iface: t.iface, ip: ipClean, type: info.awg_params && Object.keys(info.awg_params).length ? "awg" : "wg" };
      const ov = o ? configOverrides(o, info) : {};
      if (Object.keys(ov).length) target.overrides = ov;
      // Same key as the existing deployments → the peer's blob already covers it; no plaintext to the server.
      const r = await api.peerAddTarget({ peer_id: peer.id, target });
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
        body=${T("You've unchecked every interface, so there's nothing left to deploy this peer to — saving will completely delete it. Its access is revoked everywhere and its config / QR stops working. This action is irreversible. Are you sure you want to continue?")
          + (nets.length ? " " + T("{device} carries {nets} — everyone who reaches them through it loses access.", { device: netDev, nets: nets.join(", ") }) : "")}
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
      if (netsGone.length) parts.push(T("{device} stops carrying {nets} on {where} — everyone who reaches them there loses access.",
        { device: netDev, nets: nets.join(", "), where: [...new Set(netsGone.map(t => Store.nodeName(t.node)))].join(", ") }));
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
        ${netsAdded ? html`<div class="notice warn"><${Ic} i="network"/><span>${peer.share
            ? T("{device} carries {nets}. On a node you add, they're carried there too — for the same people as now.", { device: netDev, nets: nets.join(", ") })
            : T("{device} carries {nets}. On a node you add, they're carried there too, and every device on that node can reach them. Open Networks to limit who.", { device: netDev, nets: nets.join(", ") })}</span></div>` : null}
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
      ${p.unassigned ? html`<button class="btn btn-danger" onClick=${() => confirmDeletePeer(p, null, true)}>${T("Delete")}</button>`
        : html`<button class="btn btn-danger" onClick=${() => confirmUnassign(p)}>${T("Unassign")}</button>`}<//>`}>
    ${u ? html`<${PeerStatusLine} peer=${p} pos="bar"/>` : null}
    <div class="pv-head">
      <div class="pv-id"><div class="pv-sub">${u ? html`<a class="pv-user" href="#/users" onClick=${e => { e.preventDefault(); closeModal(); revealUser(u.id); }}>${u.name}</a>`
          : html`<${UserCombo} onPick=${uid => assignPeer(p, uid)} placeholder=${T("Assign to a user…")}/>`}</div></div>
      ${(p.routes || []).length && p.targets.some(t => !isSelfContainedKind(targetType(t))) ? html`<${NetworksBadge} peer=${p}/>` : null}
      ${badgeWithReason(p.unassigned ? "unassigned" : p.status, p.reason)}</div>
    <div class="lbl" style="margin:16px 2px 4px">${T("Deployments · {n}", { n: p.targets.length })}</div>
    <div class="pv-deps">${depsOrdered.map(t => {
      const obs = t.observed;
      const xfer = tgtXfer(t);            // wire counters for wg/awg, per-password byte deltas for a keyless server
      const proto = targetType(t);
      return html`<div class=${"pv-dep" + (node === t.node && iface === t.iface ? " hl" : "")} key=${tkey(t.node, t.iface)}>
        <div class="pv-dep-top">${peerUncategorised(t) && t.status !== "blocked" && t.status !== "faulty"
          // same treatment as the grid and the QR card: the status word goes amber with a warning triangle and
          // the bubble explains, rather than a green pill that says everything is fine about a peer whose
          // traffic is not being category-routed.
          ? uncatPop(html`<span class="badge b-uncat ic"><${Ic} i="warn"/>${statusLabel(t.status)}</span>`)
          : badgeWithReason(t.status, t.status === "blocked" ? blockedReason(t.type) : statusReason(t.status))}
          <span class="tags">
            <${PubTag} peer=${p} src=${proto} label=${proto} dim=${!t.online}/>
            ${turnEnabled() ? html`<${TargetFrontBadge} node=${t.node} iface=${t.iface} peer=${p} dim=${!t.online}/>` : null}
          </span>
          <span class="grow"></span>
          <${RoleToggle} peer=${p} t=${t}/>
          ${(() => { const gh = ghostIface(t.node, t.iface); return (gh && gh.ripe)
            ? html`<button class="btn btn-ghost gh" title=${T("Recreate this interface with a NEW key and rekey every peer on it — clients re-import")} onClick=${() => openRecreateRekey(t.node, t.iface)}><${Ic} i="refresh"/> ${T("Recreate & rekey interface")}</button>`
            : t.restorable ? html`<button class="btn btn-ghost restore" title=${T("Recreate this missing interface with its original identity — recovers every peer on it")} onClick=${() => confirmRestoreDeployment(p, t)}><${Ic} i="refresh"/> ${T("Restore interface")}</button>`
            : t.correctable ? html`<button class="btn btn-ghost correct" title=${T("Assign the next free in-subnet address ({ip} is out of range)", { ip: t.ip || "?" })} onClick=${() => confirmCorrectDeployment(p, t)}><${Ic} i="check"/> ${T("Fix address")}</button>` : null; })()}</div>
        <div class="pv-dep-grid">
          <span><span class="k">${T("col|Node")}</span> <span style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span></span>
          <span><span class="k">${T("col|Interface")}</span> ${t.iface}</span>
          ${/* A qWDTT instance running RAW gives the peer a SECOND address, on its own TUN — it holds both at
                once, so this sits BESIDE the wg address rather than replacing it. Absent for every other kind. */""}
          <span class=${t.raw_ip ? "pv-addr-raw" : ""}><span class="k">${T("col|Address")}</span> <span class="addr">${t.ip || "—"}</span>${t.raw_ip
            ? html` <span class="tg tg-raw" title=${T("This peer's address on the RAW datapath — it holds both at once")}>RAW ${t.raw_ip}</span>`
            : null}</span>
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
  // "node|iface" -> {dns,mtu,keepalive,allowed} for THAT deployment. Was one set for the whole peer, which
  // stopped being expressible once a peer could span kinds — see TargetSettingsSheet.
  const [topts, setTopts] = useState({});
  const setOptsFor = (k, v) => setTopts(m => ({ ...m, [k]: v }));
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
      // Each deployment's own config is the source of its own fields. The old code read ONE config (the focused
      // target's, else whichever came first) and applied its values to every target on Save — so opening the
      // sheet on one interface and saving quietly pushed that interface's DNS/MTU onto all the others.
      const seed = {};
      for (const k of Object.keys(found)) { const c = parseFullConf(found[k]);
        seed[k] = { dns: (c.dns || []).join(", "), mtu: String(c.mtu), keepalive: String(c.keepalive), allowed: c.allowed }; }
      setTopts(seed); setOrig(seed);   // baseline for the "anything changed?" Save gate
    })();
    return () => { ok = false; };
  }, [peer.id, live && live.pubkey, Store.configEpoch]);   // LIVE pubkey / epoch change (e.g. after Rotate) re-reads the now-available config

  const editable = Object.keys(confs).length;
  const ipChangedFor = t => { const v = (ips[tkey(t.node, t.iface)] || "").trim(); return !!v && v !== (t.ip || "").split("/")[0]; };
  const ipBadFor = t => { const v = (ips[tkey(t.node, t.iface)] || "").trim(); return !!v && !V.ipv4(v.split("/")[0]); };
  const anyIpBad = peer.targets.some(ipBadFor);
  const optsErr = Object.keys(topts).map(k => { const e = configErrors(topts[k]); const f = Object.keys(e)[0];
    return f ? { k, msg: T("{v1}: {v2}", { v1: k.split("|")[1], v2: e[f] }) } : null; }).find(Boolean);
  const optsChanged = k => !!orig && !!orig[k] && JSON.stringify(topts[k]) !== JSON.stringify(orig[k]);
  // Save is only offered when something would actually change — otherwise it rewrites the peer with identical
  // values (and, for a user change, walks the operator into a confirm for a no-op).
  const _dirty = (title.trim() !== (peer.title || "").trim())
    || ((userId || "") !== (peer.user_id || ""))
    || (expDate !== expiryInputVal(peer.ownExpiry || 0))
    || (live.targets || []).some(ipChangedFor)
    || Object.keys(topts).some(optsChanged);
  const ownerExp = userId ? +(((Store.recon.users || []).find(u => u.id === userId) || {}).expiry || 0) : 0;
  const save = async () => {
    if (anyIpBad) return setMsg({ k: "err", t: T("Each address must be a valid IPv4.") });
    if (optsErr) return setMsg({ k: "err", t: optsErr.msg });
    const expSec = expiryFromInput(expDate);
    // A peer can't outlive its subscription (the server enforces it too — check here for a clean message).
    if (expSec && ownerExp && expSec > ownerExp) return setMsg({ k: "err", t: T("Expiry can't be later than the subscription's (") + fmtDate(ownerExp) + ")." });
    setBusy(true); setMsg({ k: "work", t: T("saving…") });
    let fails = 0;
    try {
      if (title.trim() !== (peer.title || "")) {
        const r = await api.peerUpdate({ peer_id: peer.id, title: title.trim() }); if (!r.ok) fails++;
      }
      if (expSec !== (peer.ownExpiry || 0)) {   // this peer's own expiry date (independent of the subscription's)
        const r = await api.peerUpdate({ peer_id: peer.id, expiry: expSec }); if (!r.ok) { fails++; if (r.error) setMsg({ k: "err", t: srvText(r) }); }
      }
      // persist the roster copy of the non-secret overrides (custom DNS/MTU/AllowedIPs/keepalive), so a
      // blob-only render (encrypted store / the sub page) reproduces this peer's config faithfully. Written
      // per DEPLOYMENT now: each target carries its own, and the peer-wide block stays only as the fallback
      // for peers written before per-target settings existed.
      for (const t of (live.targets || peer.targets)) {
        const k = tkey(t.node, t.iface);
        if (!topts[k] || !optsChanged(k)) continue;
        const ovNew = configOverrides(topts[k], Store.ifaceMeta(t.node, t.iface));
        const r = await api.peerUpdateTarget({ peer_id: peer.id, node: t.node, iface: t.iface, overrides: ovNew });
        if (!r.ok) fails++;
      }
      // staged assignment of a previously-unassigned peer — keep the key, just set the owner
      if (peer.unassigned && userId && userId !== (peer.user_id || "")) {
        const r = await api.peerUpdate({ peer_id: peer.id, user_id: userId }); if (!r.ok) fails++;
      }
      // rebuild + persist each target's config; any target whose address changed moves on its iface
      for (const t of (live.targets || peer.targets)) {
        const k = tkey(t.node, t.iface); const cur = confs[k];
        const changed = ipChangedFor(t);
        const newIP = (ips[k] || "").trim().split("/")[0];
        if (!cur) {                                  // no config to rebuild (or a keyless deployment) — IP can still move
          if (changed) { const r = await api.peerUpdateTarget({ peer_id: peer.id, node: t.node, iface: t.iface, ip: newIP }); if (!r.ok) fails++; }
          continue;
        }
        const s = parseFullConf(cur);
        const o = topts[k] || { dns: (s.dns || []).join(", "), mtu: String(s.mtu), keepalive: String(s.keepalive), allowed: s.allowed };
        const addr = (changed ? newIP : (s.address || "").split("/")[0]) + "/32";
        const conf = buildConf({ privkey: s.privkey, address: addr, dns: String(o.dns).split(",").map(x => x.trim()).filter(Boolean), mtu: (String(o.mtu).trim() || 1280), awg_params: s.awg_params, server_pubkey: s.server_pubkey, psk: s.psk, endpoint: s.endpoint, allowed: (String(o.allowed).trim() || "0.0.0.0/0, ::/0"), keepalive: String(o.keepalive).trim() });
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

  // A peer can hold a MIX of kinds, so "is this a WDTT peer?" is no longer one question with one answer.
  // What each control actually needs is narrower: does this peer HAVE a wdtt deployment (→ offer Rotate link),
  // a csqtt one, and does it have any KEYED deployment at all (→ offer Rotate keys / QR). The old `isKeyless`
  // read "has any keyless deployment", which on a mixed peer hid its WireGuard addresses and its QR.
  const hasWdtt = !!peer.wdtt_password || (live.targets || []).some(t => targetType(t) === "wdtt");
  const hasCsqtt = !!peer.csqtt_password || (live.targets || []).some(t => targetType(t) === "csqtt");
  const hasKeyed = (live.targets || []).some(t => !isSelfContainedKind(targetType(t)));
  const isKeyless = !hasKeyed;   // EVERY deployment is self-contained: panel-owned password, no browser keypair
  const isWdttPeer = hasWdtt, isCsqttPeer = hasCsqtt;   // (rotate-link wording below)
  const rotate = () => {
    // A MIXED peer holds several independent credentials — a keypair for its wg/awg deployments and one access
    // password per keyless kind — so rotating it means rotating all of them, cumulatively (the same shape the
    // bulk rotate in peer-actions.js uses). The single-kind cases below are what that reduces to.
    if (hasKeyed && (hasWdtt || hasCsqtt)) {
      openConfirm({ title: T("Rotate credentials"), confirmLabel: T("Rotate credentials"), warn: true,
        body: T("This peer holds several credentials — a WireGuard keypair and an access password per turn server. All of them are replaced: every config, QR and link this peer already handed out stops working and must be re-imported."),
        onConfirm: () => {
          setRotating(true);
          (async () => {
            try {
              if (hasCsqtt) await api.csqttPeerRotate({ peer_id: peer.id });
              if (hasWdtt) await api.wdttPeerRotate({ peer_id: peer.id });
              await rotatePeerKeys(peer);   // LAST: this changes the pubkey, and the two above address by id
              await Store.poll();
              const re = Store.rowErrors["peer:" + peer.id];
              toast(re ? (re.msg || T("Rotate failed.")) : T("Credentials rotated — send the user their new QR and links; the old ones no longer work."), re ? "err" : "ok");
            } catch (e) { toast(T("Rotate failed."), "err"); }
            finally { setRotating(false); }
          })();
        } });
      return;
    }
    if (isKeyless) {   // keyless turn peer: no browser keypair — rotate the panel-owned access password (revokes the old link)
      // Called ON the api object, never pulled off it: these are shorthand methods that do `this.post(...)`, so a
      // detached reference loses `this` and the call throws SYNCHRONOUSLY — before .then/.catch are attached, so
      // the catch never runs, the button sits on "Rotating link…" for ever and the request never leaves the
      // browser. The password was never rotated either, so retrying the same button looked equally dead.
      const rotateApi = b => (isCsqttPeer ? api.csqttPeerRotate(b) : api.wdttPeerRotate(b));
      openConfirm({ title: T("Rotate link"), confirmLabel: T("Rotate link"), warn: true,
        body: isCsqttPeer
          ? T("A fresh access password is generated. The current csqtt link stops working — send the user their new link (from the subscription page) to re-import.")
          : T("A fresh access password is generated. The current WDTT link stops working — send the user their new link (from the subscription page) to re-import."),
        // try/finally, not .catch: a .catch only runs on a REJECTED promise, so anything that throws before one
        // exists leaves the button stuck. finally clears it whatever happened — and the operator is told, rather
        // than left watching a disabled button that will never change.
        // Deliberately NOT an async onConfirm: ConfirmSheet awaits it, which would hold the dialog open for the
        // whole request. The design here (and on the keypair path below) is that the confirm closes at once and
        // the BUTTON carries the progress. So: fire-and-forget, but with the clearing guaranteed on all three
        // routes out — a synchronous throw, a rejection, and success. `.catch` alone covered only the middle one.
        onConfirm: () => {
          setRotating(true);
          try {
            rotateApi({ peer_id: peer.id })
              .then(async r => {
                await Store.poll();
                toast(r && r.ok ? T("Link rotated — the old one no longer works.") : (srvText(r) || T("Rotate failed.")),
                      r && r.ok ? "ok" : "err");
              })
              .catch(() => toast(T("Rotate failed."), "err"))
              .finally(() => setRotating(false));
          } catch (e) {
            setRotating(false);
            toast(T("Rotate failed."), "err");
          }
        } });
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
        : html`<button class="btn btn-ghost" disabled=${rotating} onClick=${rotate}><${Ic} i="key"/> ${
            (hasKeyed && (hasWdtt || hasCsqtt)) ? (rotating ? T("Rotating credentials…") : T("Rotate credentials"))
            : isKeyless ? (rotating ? T("Rotating link…") : T("Rotate link"))
            : (rotating ? T("Rotating keys…") : T("Rotate keys"))}</button>`;
  return html`<${Sheet} title=${T("Edit peer")} width=${700} onClose=${done} onBack=${child ? done : null} subject=${{ kind: "peer", id: peer.id }}
    foot=${footRow({ left: html`${editable && hasKeyed ? html`<button class="btn btn-ghost" onClick=${() => openPeerConfigs(peer, { child: true })}><${Ic} i="qr"/>QR</button>` : null}<button class="btn btn-ghost" onClick=${() => openAddTarget(peer)}><${Ic} i="copy"/> ${T("Targets")}</button>${hasKeyed
        ? html`<button class="btn btn-ghost" onClick=${() => openPeerNetworks(live)}><${Ic} i="network"/> ${(live.routes || []).length ? T("Networks · {n}", { n: live.routes.length }) : T("Networks")}</button>` : null}${fixBtn}${peerBlockBtn(peer)}`, onCancel: done, disabled: busy || !_dirty, title: _dirty ? "" : T("No changes to save"), onAction: save, action: T("Save") })}>
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
    <div class="field"><label>${T("label|Deployments")}</label>
      <div class="targetpick">${targetsOrdered.map(t => {
        const k = tkey(t.node, t.iface);
        // ONE list for every kind. It used to be two mutually-exclusive lists chosen by whether the peer was
        // "a WDTT peer", which on a mixed peer showed only one of its halves. Each row now asks its OWN kind
        // what it should offer: an address box and a settings gear for wg/awg, "auto" and no gear for a
        // self-contained server that mints the address on connect.
        const ity = targetType(t);
        const sc = isSelfContainedKind(ity);
        return html`<div class="targetopt sel locked" key=${k}>
          <div class="topt-main"><span class="box"><${Ic} i="check"/></span><span class="nm" style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span><span class="tp">${t.iface}</span></div>
          <div class="topt-right hasprim">
            <${RoleToggle} peer=${peer} t=${t} compact=${true}/>
            <${PubTag} peer=${live} src=${ity} label=${ity} dim=${!t.online}/>
            <${TargetFrontBadge} node=${t.node} iface=${t.iface} peer=${live}/>
            ${sc
              ? html`<span class="topt-ip faint" title=${ity === "csqtt" ? T("csqtt assigns the address on connect") : T("WDTT assigns the address on connect")}>${T("val|auto IP")}</span>`
              : html`<input class=${"topt-ip " + (ipBadFor(t) ? "bad" : "")} value=${ips[k] || ""} onInput=${e => setIpFor(k, e.target.value)}/>`}
            ${(!sc && confs[k]) ? html`<${TargetGear} node=${t.node} iface=${t.iface} kind=${ity} opts=${topts[k]} onSave=${v => setOptsFor(k, v)}/>` : null}
          </div>
        </div>`;
      })}</div>
      <div class="hint">${hasKeyed
        // The gear renders only where a stored config exists (`!sc && confs[k]`), so a keyed peer whose
        // config we cannot rebuild used to be told about a control that was never drawn. `editable` is the
        // same signal the warning below uses.
        ? (editable
            ? T("Changing an address moves the peer on that interface. The gear holds that deployment's DNS, MTU and routing.")
            : T("Changing an address moves the peer on that interface."))
        : T("These servers assign each address on connect; the user's link per server is on their subscription. There's no client config (key/DNS/MTU) — the server owns the datapath.")}</div>
    </div>
    ${(hasKeyed && !loaded) ? html`<div class="loading"><span class="spin"></span>${T("loading config…")}</div>` : null}
    ${(hasKeyed && loaded && !editable) ? html`<div class="notice warn"><${Ic} i="warn"/><span>${T("The client's private key isn't available, so DNS / MTU / routing can't be rebuilt")}${Store.storeConfigs ? "" : T(" (enable store_configs, or edit right after creating)")}${T(". Title and address can still change.")}</span></div>` : null}
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// ── networks behind a peer (docs/NETWORKS-PLAN.md §4.5, §4.6, §5, D8) ──────────────────────────────
// A peer can front networks — the office LAN behind a router, a NAS behind a home box. The field declares
// them; the report under it is what matters. WHO can now reach the network: everyone on the node, because the
// node cannot tell peers apart — an exposure disclosure, not a detail. Which narrowed peers still can't. And
// the far side's setup, which nothing the panel does can make exist. The draft is judged by the server as it
// is typed and nothing is written until "Save networks", so all of that is on screen BEFORE the save.
const netList = s => String(s || "").split(/[\s,]+/).map(x => x.trim()).filter(Boolean);
// The ranges home routers hand out by default (TP-Link/D-Link/Asus, Netgear, Huawei, Xiaomi, MikroTik, ISP boxes). A network
// overlapping one is unreachable from any home that uses it — the home LAN's own route wins on the user's device.
const HOME_RANGES = ["192.168.0.0/24", "192.168.1.0/24", "192.168.2.0/24", "192.168.8.0/24", "192.168.31.0/24",
  "192.168.88.0/24", "192.168.100.0/24", "10.0.0.0/24"];
const v4Range = s => {                                        // "a.b.c.d[/n]" → [first, last] as integers, or null
  const m = /^(\d{1,3}(?:\.\d{1,3}){3})(?:\/(\d{1,2}))?$/.exec(String(s).trim());
  if (!m || !V.ipv4(m[1]) || (m[2] !== undefined && +m[2] > 32)) return null;
  const size = 2 ** (32 - (m[2] === undefined ? 32 : +m[2])), a = m[1].split(".").reduce((n, o) => n * 256 + +o, 0);
  const lo = Math.floor(a / size) * size;
  return [lo, lo + size - 1];
};
const homeClash = list => list.filter(p => { const r = v4Range(p);
  return r && HOME_RANGES.some(h => { const q = v4Range(h); return r[0] <= q[1] && q[0] <= r[1]; }); });
const netPeerName = id => {
  const q = Store.peer(id);
  return q ? ([q.name, q.title].filter(Boolean).join(" / ") || T("an unnamed peer")) : T("another peer");
};
// Every reason a network is not carried, in words. The tokens come from the panel (network_subnet_refusal,
// node_networks) and from the node (network_route_refusal, net_route_install); one missing here falls through
// to the last line rather than printing a token.
function netWhy(r, node) {
  const v = { p: r.prefix, a: r.addr || "", node: node || "", by: r.by ? netPeerName(r.by) : "" };
  switch (r.why) {
    case "invalid": return T("{p} isn't a network address.", v);
    case "not_v4": return T("{p} is IPv6 — only IPv4 networks can be carried.", v);
    case "default_route": return T("{p} would send all of the node's internet traffic into this device.", v);
    case "reserved": return T("{p} is a reserved range — loopback, link-local, multicast or cloud metadata.", v);
    // ⚠️ TRUE ONLY WHILE THE NODE SHARES ITS LAN. With "Clients can reach it" off (NETWORKS P2) its clients reach nothing on
    // that network, and the sentence told the operator the opposite. The refusal still stands — the node is the provider —
    // so the closed case names the switch that lets them in. `node` is a display name here; names are unique per panel.
    case "node_lan": return ((Store.nodes || []).find(n => n.name === node) || {}).lan_share === false
      ? T("{node} is already on {p} ({a}), but it keeps its clients off that network. Turn on “Clients can reach it” under Local network on {node} to let them in.", v)
      : T("{node} is already on {p} ({a}), so its clients reach it without a gateway device.", v);
    case "iface_subnet": return T("{p} overlaps a tunnel subnet on {node} ({a}).", v);
    case "mesh": return T("{p} overlaps a mesh link on {node} ({a}).", v);
    case "node_gateway": return T("{p} contains {a}, the gateway {node} reaches the internet through.", v);
    case "node_panel": return T("{p} contains {a}, the address {node} reaches this panel by.", v);
    case "node_resolver": return T("{p} contains {a}, the DNS server {node} depends on — it could no longer find this panel.", v);
    case "resolver_unknown": return T("{node} can't tell which DNS server it depends on, so it carries no networks.", v);
    case "node_too_old": return T("{node} runs a version that can't check a route is safe — update it to carry networks.", v);
    case "no_snapshot": return T("{node} hasn't reported yet; the network waits until it does.", v);
    case "panel_unknown": return T("{node} hasn't finished a sync yet; the network waits.", v);
    case "self_contained": return T("A turn server deployment has no key, so nothing can be routed through it.", v);
    case "taken": return T("{by} already carries {a} on {node} — a network has one device per node.", v);
    case "overlap": return T("{p} overlaps {a}, which this device already lists.", v);
    case "cap": return T("A device can front at most 8 networks.", v);
    case "blocked": return T("This device is blocked or expired, so it carries nothing.", v);
    case "rolled_back": return T("{node} installed the route and took it straight back out — it moved the path to {a}.", v);
    case "route_exists": return T("{node} already routes {p} through {a}, and leaves that route alone.", v);
    case "share_unsupported": return T("{node} runs a version that can't restrict who reaches a network, so it carries this one for nobody — update it.", v);
    default: return T("{node} couldn't check the route to {p} safely, so it didn't install it.", v);
  }
}

// ── P5: who can reach these networks (docs/NETWORKS-PLAN.md §15) ─────────────────────────────────────────────────────
// `share` null = everyone on the node, as before. An object = the device's owner, always, plus the people named, each
// until a day or for good. The panel refuses with tokens (share_clean); the words are here.
// THREE AUDIENCES, ONE STORED SHAPE: `null` = everyone on the node, `{users: {}}` = the owner only, `{users: {...}}` = the
// owner and the people named. "Only the owner" was always storable — as "people you choose" with nobody chosen, which read
// as a half-finished form — so it is a mode of the draft, not a new field.
const shareOf = s => (s && typeof s === "object" && s.users && typeof s.users === "object")
  ? { mode: Object.keys(s.users).length ? "chosen" : "owner", users: { ...s.users } } : { mode: "everyone", users: {} };
const shareBody = d => d.mode === "everyone" ? null : { users: d.mode === "chosen" ? d.users : {} };
const shareKey = d => d.mode === "everyone" ? "off"
  : "on:" + (d.mode === "chosen" ? Object.keys(d.users).sort().map(k => k + "=" + (d.users[k] || 0)).join(",") : "");
function shareRefused(why) {
  switch (why) {
    case "unknown_user": return T("One of these people no longer exists — remove them and save again.");
    case "date_passed": return T("A date has already passed — pick a later day or leave it empty.");
    case "too_many": return T("A network can be shared with at most 500 people.");
    default: return T("Access wasn't saved.");
  }
}
const shareUser = id => { const u = Store.user(id); return u ? u.name : T("a user who no longer exists"); };
// Why a grantee's turn-server devices do not reach it (swg-panel-server keyless_sources, docs/NETWORKS-PLAN.md §16).
function shareKeyless(why, name, devices) {
  const o = { name, devices };
  switch (why) {
    case "unenforced": return T("{name}: {devices} on a turn server whose build can't prove who is sending — they can't reach it.", o);
    case "not_connected": return T("{name}: {devices} not connected yet — they reach it once connected.", o);
    case "not_running": return T("{name}: {devices} on a turn server that isn't running.", o);
    case "raw_excluded": return T("{name}: {devices} in ildarmaga's raw mode, which can't reach a restricted network.", o);
    default: return T("{name}: {devices} not reported by the node yet.", o);
  }
}

function NetShare({ peer, draft, setDraft, nodes, noShare, routes }) {
  const owner = peer.user_id ? Store.user(peer.user_id) : null;
  // The owner is in regardless and never stored as a grantee; after a reassignment the new owner can still sit in the stored
  // list, and was shown twice — once as the owner, once as someone chosen.
  const ids = Object.keys(draft.users).filter(id => id !== peer.user_id).sort((a, b) => shareUser(a).localeCompare(shareUser(b)));
  const everyone = nodes.length === 1 ? T("Everyone on {node}", { node: nodes[0] }) : T("Everyone on its nodes");
  // ONE control, the panel's pill switch (the link datapath's Forward | Relay): the narrowest, the widest, then the one that
  // needs a list. ⚠️ The list lived here, one row per person, and a network shared with 100 people is not a form field — it
  // opens in its own window (ShareListSheet), searched and paged; here it is a count.
  const modes = [...(owner ? [["owner", T("Only {name}", { name: owner.name })]] : []), ["everyone", everyone], ["chosen", T("People you choose")]];
  const label = T("Who can reach these networks");
  const openList = users => pushModal(html`<${ShareListSheet} peer=${peer} users=${users} routes=${routes}
    onApply=${u => setDraft(d => ({ ...d, mode: "chosen", users: u }))}/>`);
  const pick = m => { setDraft(d => ({ ...d, mode: m })); if (m === "chosen" && !ids.length) openList(draft.users); };
  return html`<div class="netshare">
    <label class="netshare-l">${label}</label>
    <div class="netshare-row">
      <div class="dpsw netsw-share" role="radiogroup" aria-label=${label}>${modes.map(([m, l]) => html`<button type="button" role="radio"
        aria-checked=${draft.mode === m} class=${draft.mode === m ? "on" : ""} onClick=${() => pick(m)}>${l}</button>`)}</div>
      ${draft.mode === "chosen" ? html`<button type="button" class=${"netshare-count" + (!ids.length && !owner ? " bad" : "")} onClick=${() => openList(draft.users)}>
        <${Ic} i="users"/><span>${ids.length ? T("Shared with {users}", { users: plural(ids.length, "user") }) : T("Choose people")}</span></button>` : null}
    </div>
    ${/* NETWORKS P5 S8: a node that can't enforce a restriction carries a restricted network for NOBODY. Said at the choice,
          before the save — further down it was one reason line among many, and "Only Alice" read as simply broken. */""}
    ${draft.mode !== "everyone" && noShare.length ? html`<div class="notice warn"><${Ic} i="warn"/><span>${owner
        ? T("{nodes} runs an older version that can't limit who reaches a network, so with this choice nobody reaches them there — {name} included. Update {nodes}, or choose “{everyone}”.", { nodes: noShare.join(", "), name: owner.name, everyone })
        : T("{nodes} runs an older version that can't limit who reaches a network, so with this choice nobody reaches them there. Update {nodes}, or choose “{everyone}”.", { nodes: noShare.join(", "), everyone })}</span></div>` : null}
    ${draft.mode === "owner" && owner ? html`<div class="hint">${T("Only {name}'s own devices on the same node reach them.", { name: owner.name })}</div>` : null}
    ${draft.mode === "everyone" ? html`<div class="hint">${T("Every device on the same node reaches them — the report below says how many.")}</div>` : null}
    ${draft.mode === "chosen" ? html`<div class=${"hint" + (!ids.length && !owner ? " err" : "")}>${owner
        ? T("{name} always has access, as the owner, and so do the people you choose.", { name: owner.name })
        : ids.length ? T("Only the people you choose have access.")
        : T("Nobody has access yet — choose people, or pick “{everyone}”.", { everyone })}</div>` : null}
  </div>`;
}

// ── a list sized by the fleet, not by the operator ──────────────────────────────────────────────────────────────────────────
// Everything here must read as well with 2 rows as with 200 (operator, 2026-09-14): a long list is paged, 15 rows at a time,
// with the panel's own pager markup (Activity's).
const NET_PAGE = LIST_PAGE, pageOf = pageSlice, NetPager = ListPager;   // the shared pager (js/ui.js), also the user sheet's
// Rows inside a disclosure, paged; `total` is the server's count when it capped the list it sent.
function NetPagedRows({ rows, total, render }) {
  const [page, setPage] = useState(1);
  const pages = Math.max(1, Math.ceil(rows.length / NET_PAGE)), pg = Math.min(page, pages);
  return html`${pageOf(rows, pg).map(render)}
    ${total > rows.length && pg === pages ? html`<div class="hint">${T("…and {v1} more", { v1: total - rows.length })}</div>` : null}
    <${NetPager} page=${pg} setPage=${setPage} total=${rows.length}/>`;
}

// The people a network is shared with, in their own window: add by search, filter, a paged grid. Each person's devices are a
// colour-coded count — green reach it, amber will once connected, red can't — with the per-node detail on hover. The window
// asks the panel what its own draft would mean (the same preview the Networks window uses), so the counts follow edits.
function ShareListSheet({ peer, users: initial, routes, onApply }) {
  const owner = peer.user_id ? Store.user(peer.user_id) : null;
  const [users, setUsers] = useState(() => { const u = { ...(initial || {}) }; delete u[peer.user_id]; return u; });
  const [q, setQ] = useState(""), [page, setPage] = useState(1), [rep, setRep] = useState(null), [err, setErr] = useState("");
  const dirtyRef = useRef(false), closeRef = useRef(null), cleanRef = useRef(null), base = useRef(null);
  const key = Object.keys(users).sort().map(k => k + "=" + (users[k] || 0)).join(",");
  if (base.current === null) base.current = key;
  dirtyRef.current = key !== base.current;
  useEffect(() => {
    let ok = true;
    const h = setTimeout(async () => {
      try {
        const r = await api.peerNetworks({ peer_id: peer.id, routes, share: { users } });
        if (!ok) return;
        if (r && r.ok) { setRep(r.data); setErr(""); } else setErr(r && r.code === "share_refused" ? shareRefused(r.why) : (srvText(r) || T("Couldn't check these networks.")));
      } catch (e) { if (ok) setErr(T("Couldn't check these networks.")); }
    }, 350);
    return () => { ok = false; clearTimeout(h); };
  }, [key]);
  const reach = {};                                      // uid → devices that reach it, summed over the device's nodes
  for (const t of (rep && rep.targets) || []) for (const g of ((t.share || {}).grants || [])) {
    const w = g.keyless_why || {}, soon = w.not_connected || 0;
    const r = reach[g.user_id] = reach[g.user_id] || { ok: 0, soon: 0, no: 0, nodes: [] };
    r.ok += g.devices || 0; r.soon += soon; r.no += Math.max(0, (g.keyless || 0) - soon);
    r.nodes.push({ node: Store.nodeName(t.node), g });
  }
  const byName = (a, b) => shareUser(a).localeCompare(shareUser(b));
  const all = Object.keys(users).sort(byName);
  const ql = q.trim().toLowerCase();
  const rows = ql ? all.filter(id => shareUser(id).toLowerCase().includes(ql)) : all;
  const pages = Math.max(1, Math.ceil(rows.length / NET_PAGE)), pg = Math.min(page, pages);
  const add = id => {
    if (!id || id === peer.user_id || id in users) return;
    setUsers(u => ({ ...u, [id]: 0 })); setQ("");
    setPage(Math.floor([...all, id].sort(byName).indexOf(id) / NET_PAGE) + 1);   // to the page the new person lands on
  };
  const drop = id => setUsers(u => { const n = { ...u }; delete n[id]; return n; });
  const apply = () => { onApply(users); dirtyRef.current = false; if (cleanRef.current) cleanRef.current(); closeModal(); };
  // Sheet marks itself dirty on ANY input event, so typing in the filter or the person search — which change nothing — asked
  // "Discard unsaved changes?" on close. What changed is known exactly (`dirtyRef`, the list's key against the one it
  // opened with), so every input here hands the guard back to that: this handler runs after Sheet's capture listener.
  const typedOnly = () => { if (cleanRef.current) cleanRef.current(); };
  const devices = id => {
    const r = reach[id];
    if (!rep) return html`<span class="faint">…</span>`;
    if (!r) return html`<span class="faint">—</span>`;
    const parts = [[r.ok, "ok"], [r.soon, "soon"], [r.no, "no"]].filter(([n]) => n);
    const trigger = html`<span class=${"netdev" + (parts.length ? "" : " none")}>${parts.length
      ? parts.map(([n, c]) => html`<span class=${"netdev-n " + c}>${n}</span>`) : T("no device")}<${Ic} i="info"/></span>`;
    return html`<${Popover} hoverOnly cls="netdev-pop" popCls="netroute-bub" trigger=${trigger}>
      <span class="netroute-h">${shareUser(id)}</span>
      ${r.nodes.map(({ node, g }) => html`<div class="netbub-row"><b>${node}</b> — ${g.devices
          ? T("{devices} reach it", { devices: plural(g.devices, "device") }) : (g.keyless ? T("no device reaches it yet") : T("no device here"))}</div>
        ${Object.entries(g.keyless_why || {}).map(([w, n]) => html`<div class="netbub-row sub">${shareKeyless(w, shareUser(id), plural(n, "device"))}</div>`)}`)}
    <//>`;
  };
  return html`<${Sheet} title=${T("People with access")} width=${680} dirtyRef=${dirtyRef} closeRef=${closeRef} cleanRef=${cleanRef}
    subject=${{ kind: "peer", id: peer.id }}
    foot=${html`<${Fragment}><span class="faint">${T("{users} chosen", { users: plural(all.length, "user") })}</span><span class="grow"></span>
      <button class="btn btn-ghost" onClick=${() => (closeRef.current ? closeRef.current() : closeModal())}>${T("Cancel")}</button>
      <button class="btn btn-primary" disabled=${!!err} onClick=${apply}>${T("Apply")}</button><//>`}>
    ${owner ? html`<div class="hint sharelead">${T("{name} always has access, as the owner.", { name: owner.name })}</div>` : null}
    <div class="sharebar" onInput=${typedOnly} onChange=${typedOnly}>
      <div class="sharebar-add"><${UserPicker} value=${null} placeholder=${T("Add a person…")} exclude=${[peer.user_id, ...all].filter(Boolean)} onChange=${add}/></div>
      ${all.length > NET_PAGE ? html`<input class="sharebar-filter" value=${q} data-enter="self" placeholder=${T("Filter the list…")}
          aria-label=${T("Filter the list…")} onInput=${e => { setQ(e.target.value); setPage(1); }}/>` : null}
    </div>
    ${err ? html`<div class="formmsg err">${err}</div>` : null}
    ${all.length ? html`<div class="sharegrid" role="table" onInput=${typedOnly} onChange=${typedOnly}>
        <div class="sharegrid-h" role="row"><span>${T("col|User")}</span><span>${T("Devices")}</span><span>${T("Access until")}</span><span></span></div>
        ${pageOf(rows, pg).map(id => html`<div class="sharegrid-r" role="row" key=${id}>
          <span class="nm">${shareUser(id)}</span>
          <span>${devices(id)}</span>
          <span><input type="date" class="datein" value=${expiryInputVal(users[id])} data-enter="self" data-noautofocus
            aria-label=${T("Last day {name} can reach them — leave empty for no end", { name: shareUser(id) })}
            onInput=${e => { const v = expiryFromInput(e.target.value); setUsers(u => ({ ...u, [id]: v })); }}/></span>
          <span><button type="button" class="btn btn-ghost btn-mini" title=${T("Stop sharing with {name}", { name: shareUser(id) })}
            aria-label=${T("Stop sharing with {name}", { name: shareUser(id) })} onClick=${() => drop(id)}><${Ic} i="x"/></button></span></div>`)}
        ${!rows.length ? html`<div class="sharegrid-empty">${T("Nobody on the list matches “{q}”.", { q })}</div>` : null}
      </div>
      <${NetPager} page=${pg} setPage=${setPage} total=${rows.length}/>
      <div class="hint">${T("A date is the last day they can reach these networks; leave it empty for no end.")}</div>`
    : html`<div class="sharegrid-empty">${T("Nobody yet — add people with the search above.")}</div>`}
  <//>`;
}

// Who can reach it on one node, as four numbers on the networks' line — all, green (reach it), amber (will, once they fix their
// routing or connect), red (can't) — and the sentences on hover. ⚠️ These were six lines under every network plus one row per
// person; with 100 people that buried the node's block. Per-person detail lives in the People window.
function NetCounts({ t, node }) {
  const s = t.share, c = (s && s.cut_off) || {}, st = s && s.node;
  let soonKl = 0, noKl = 0;
  for (const g of (s && s.grants) || []) { const w = g.keyless_why || {}; soonKl += w.not_connected || 0; noKl += Math.max(0, (g.keyless || 0) - (w.not_connected || 0)); }
  const widen = t.widen_total || 0;
  const ok = Math.max(0, (t.audience.peers || 0) - widen), soon = widen + soonKl, no = (s ? c.peers || 0 : 0) + noKl;
  const au = { node, peers: plural(t.audience.peers || 0, "peer"), users: plural(t.audience.users || 0, "gen|user") };
  const lines = [["ok", s ? (t.audience.peers ? T("{peers} of {users} can reach it", au) : T("Nobody on {node} can reach it yet", au))
    : (t.audience.peers ? T("Every client on {node} can reach it: {peers} of {users}", au) : T("No other client is on {node} yet — anyone added there will reach it", au))]];
  if (widen) lines.push(["soon", T("{peers} route around it — see “Narrowed routing” below", { peers: plural(widen, "peer") })]);
  if (soonKl) lines.push(["soon", T("{devices} not connected yet — they reach it once connected", { devices: plural(soonKl, "device") })]);
  if (s && c.peers) lines.push(["no", T("{peers} aren't among the people with access", { peers: plural(c.peers, "peer") })]);
  if (noKl) lines.push(["no", T("{devices} on turn servers that can't reach a restricted network", { devices: plural(noKl, "device") })]);
  // Site to site: a device that fronts a network is a source too, so the devices on ITS network reach this one only when its
  // owner has access. Named, with its networks and the reason — the first three; the rest counted.
  const provs = c.providers || [];
  provs.slice(0, 3).forEach(o => { const q = Store.peer(o) || {};
    const v = { device: netPeerName(o), nets: (q.routes || []).join(", "), owner: q.user_id ? shareUser(q.user_id) : "" };
    lines.push(["no", q.user_id
      ? T("Devices on the network behind {device} ({nets}) can't reach it either — {owner} isn't among the people with access.", v)
      : T("Devices on the network behind {device} ({nets}) can't reach it either — that device has no owner, so it can't be given access.", v)]); });
  if (provs.length > 3) lines.push(["no", T("…and {v1} more", { v1: provs.length - 3 })]);
  if (s && (s.lapsed || []).length) lines.push(["off", T("Access has ended for {users}", { users: plural(s.lapsed.length, "user") })]);
  if (s && !st) lines.push(["off", T("{node} hasn't confirmed the restriction yet — it does on its next sync.", { node })]);
  const aria = T("{total} other peers on {node}: {ok} can reach it, {soon} not yet, {no} can't", { total: ok + soon + no, node, ok, soon, no });
  return html`<${Popover} hoverOnly cls="netcount-pop" popCls="netroute-bub" trigger=${html`<span class="netcount" aria-label=${aria}>
      <span class="n all">${ok + soon + no}</span>${ok ? html`<span class="n ok">${ok}</span>` : null}${soon ? html`<span class="n soon">${soon}</span>` : null}${no ? html`<span class="n no">${no}</span>` : null}</span>`}>
    <span class="netroute-h">${T("Who can reach it on {node}", { node })}</span>
    ${lines.map(([cls, txt]) => html`<div class=${"netbub-row nb-dot " + cls}>${txt}</div>`)}
  <//>`;
}

// The device's networks badge on the peer view — the way in to the Networks window, shown only once the device HAS networks:
// an empty "Networks" button on every phone read as something left to set up. New ones are added from Edit. Amber while
// nothing can reach them through it — blocked, expired, or connected on no node — since a lit badge said "working".
function NetworksBadge({ peer }) {
  const n = (peer.routes || []).length, list = (peer.routes || []).join(", ");
  const blocked = !!(peer.selfDisabled || peer.userDisabled) || peer.status === "expired";
  const down = blocked || !peer.targets.some(t => !isSelfContainedKind(targetType(t)) && t.online);
  return html`<button type="button" class=${"badge ic b-nets " + (down ? "warn" : "on")} onClick=${() => openPeerNetworks(peer)}
    title=${blocked ? T("Blocked, so nothing reaches {list} through it", { list })
      : down ? T("Offline, so nothing reaches {list} until it reconnects", { list })
      : T("Networks behind this device: {list}", { list })}>
    <${Ic} i=${down ? "warn" : "network"}/>${T("Networks · {n}", { n })}</button>`;
}

export function openPeerNetworks(peer) { (modalDepth() > 0 ? pushModal : openModal)(html`<${NetworksSheet} pid=${peer.id}/>`); }

// NETWORKS — the networks behind one device, who reaches them, and what that means on each node, in its own window. One
// Save writes the networks and their audience together (one request, one roster write), so a network never lands open
// to everyone for the moment before its restriction does. Removing them is its own, confirmed, action.
function NetworksSheet({ pid }) {
  useStore();
  const found = Store.peer(pid);
  const peer = found || { id: pid, routes: [], targets: [] };
  const owner = peer.user_id ? Store.user(peer.user_id) : null;
  const stored = peer.routes || [];
  const storedKey = stored.join(",");
  const [draft, setDraft] = useState(stored.join(", "));
  const [rep, setRep] = useState(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState({});
  const [rk, setRk] = useState(0);                             // bumped when a deployment's routing is saved from a node's line
  const dirtyRef = useRef(false), closeRef = useRef(null), cleanRef = useRef(null), base = useRef(null);
  const toggle = k => setOpen(o => ({ ...o, [k]: !o[k] }));
  const want = netList(draft);
  const wantKey = want.join(",");
  // A NEW network starts private to its owner: open to everyone on the node the moment it is saved was the old default,
  // and the report explaining the exposure arrived only after the fact. A stored network keeps its stored audience.
  const [share, setShare] = useState(() => {
    const d = stored.length ? shareOf(peer.share) : { mode: owner ? "owner" : "chosen", users: {} };
    return (!owner && d.mode === "owner") ? { ...d, mode: "chosen" } : d;
  });
  const shareDraftKey = shareKey(share);
  const shareStoredKey = stored.length ? shareKey(shareOf(peer.share)) : "";
  const shareDirty = want.length > 0 && shareDraftKey !== shareStoredKey;
  const nodes = [...new Set((peer.targets || []).filter(t => !isSelfContainedKind(targetType(t))).map(t => Store.nodeName(t.node)))];
  const reqKey = wantKey + "|" + shareDraftKey;                // the draft a report answers — anything else on screen is stale
  useEffect(() => {
    if (!want.length && !stored.length) { setRep(null); return; }
    let ok = true;
    const h = setTimeout(async () => {
      try {
        const r = await api.peerNetworks({ peer_id: pid, routes: want, ...(want.length ? { share: shareBody(share) } : {}) });
        if (ok) setRep(r && r.ok ? { ...r.data, _for: wantKey, _key: reqKey } : { targets: [], refusals: [], _key: reqKey,
          error: r && r.code === "share_refused" ? shareRefused(r.why) : (srvText(r) || T("Couldn't check these networks.")) });
      } catch (e) {
        if (ok) setRep({ targets: [], refusals: [], _key: reqKey, error: T("Couldn't check these networks.") });
      }
    }, 350);
    return () => { ok = false; clearTimeout(h); };
  }, [wantKey, pid, storedKey, shareDraftKey, rk]);
  const refusals = (rep && rep.refusals) || [];
  // Compared NORMALISED: the operator types `172.30.9.9`, the roster stores `172.30.9.9/32`.
  const normKey = (rep && rep.routes && rep._for === wantKey) ? rep.routes.join(",") : wantKey;
  const dirty = normKey !== storedKey || shareDirty;
  dirtyRef.current = dirty;
  if (base.current === null) base.current = storedKey + "|" + shareStoredKey;
  // Someone else saved these networks while this window was open (another operator, another tab): saving now would put the
  // old list back over theirs without a word. Caught on the poll that brings their change, before anything is written.
  const stale = storedKey + "|" + shareStoredKey !== base.current;
  // A device with no owner, restricted to nobody: a network no one can reach, saved as if it were a choice.
  const nobody = want.length > 0 && !owner && share.mode === "chosen" && !Object.keys(share.users).length;
  const noShare = ((rep && rep.targets) || []).filter(x => x.can_share === false).map(x => Store.nodeName(x.node));
  const clash = homeClash(want);
  const checking = (want.length > 0 || stored.length > 0) && (!rep || rep._key !== reqKey);
  const name = peer.title || (owner ? owner.name : T("Unassigned peer"));
  const save = async () => {
    setBusy(true);
    try {
      const r = await api.peerUpdate({ peer_id: pid, routes: want, share: shareBody(share) });
      if (r && r.ok) {
        dirtyRef.current = false; if (cleanRef.current) cleanRef.current();
        toast(T("Networks saved."), "ok");
        closeModal(); Store.poll();
      }
      else if (r && r.refusals) setRep(x => ({ ...(x || { targets: [] }), refusals: r.refusals }));
      else toast(r && r.code === "share_refused" ? shareRefused(r.why) : (srvText(r) || T("Networks weren't saved.")), "err");
    } finally { setBusy(false); }
  };
  const remove = () => pushModal(html`<${ConfirmSheet} title=${T("Remove networks?")} confirmLabel=${T("Remove networks")} danger=${true}
    body=${T("{device} stops routing {nets}. Everyone who reaches them through it loses access.", { device: name, nets: stored.join(", ") })}
    onConfirm=${async () => {
      const r = await api.peerUpdate({ peer_id: pid, routes: [], share: null });
      if (r && r.ok) { dirtyRef.current = false; toast(T("Networks removed."), "ok"); closeModals(2); Store.poll(); }
      else toast(srvText(r) || T("Networks weren't saved."), "err");
    }}/>`);
  if (!found) return html`<${Sheet} title=${T("Networks")} foot=${html`<button class="btn btn-ghost" onClick=${closeModal}>${T("Close")}</button>`}><div class="empty"><b>${T("Peer not found")}</b>${T("It may have been removed.")}</div><//>`;
  return html`<${Sheet} title=${T("Networks · {name}", { name })} width=${680} dirtyRef=${dirtyRef} closeRef=${closeRef} cleanRef=${cleanRef}
    subject=${{ kind: "peer", id: pid }}
    foot=${html`<${Fragment}>
      ${stored.length ? html`<button class="btn btn-danger" disabled=${busy} onClick=${remove}>${T("Remove networks")}</button>` : null}
      <span class="grow"></span>
      <button class="btn btn-ghost" onClick=${() => (closeRef.current ? closeRef.current() : closeModal())}>${T("Cancel")}</button>
      ${/* An emptied field saves as a removal, through the same confirm — Save used to just grey out, which read as broken. */""}
      <button class="btn btn-primary" disabled=${busy || !dirty || stale || nobody || (!want.length && !stored.length) || refusals.length > 0}
        onClick=${want.length ? save : remove}>${busy ? T("saving…") : T("Save")}</button><//>`}>
    <div class="field netfield">
      <label>${T("Networks behind this device")}</label>
      <input class=${"mono" + (refusals.length ? " bad" : "")} value=${draft} onInput=${e => setDraft(e.target.value)}
        placeholder="192.168.1.0/24, 10.20.0.0/16" autocomplete="off" spellcheck="false" autofocus/>
      <div class="hint">${T("Networks this device routes for, like the office LAN behind a router. Clients on the same node reach them through it.")}</div>
      ${/* Feature 11: peer-to-peer needs nothing built — two devices on a node already reach each other — and
            operators do not know that. Said here, where someone reaching for "connect devices" will look. */""}
      <div class="hint">${T("Devices on the same node already reach each other at their tunnel addresses — that needs nothing here.")}</div>
      ${!want.length && stored.length ? html`<div class="hint">${T("Saving with no networks removes them — you'll be asked first.")}</div>` : null}
      ${stale ? html`<div class="formmsg err">${T("Someone changed these networks while this window was open. Cancel and open it again to see the latest.")}</div>` : null}
      ${rep && rep.error ? html`<div class="formmsg err">${rep.error}</div>` : null}
      ${refusals.length ? html`<div class="netref">${refusals.map(r => html`<div><${Ic} i="warn"/><span>${netWhy(r, r.node ? Store.nodeName(r.node) : "")}</span></div>`)}</div>` : null}
      ${/* The trap nobody on the panel side can see: a user whose home LAN uses the same range reaches their own printer, not
            the office — "works on mobile data, not at home". Only the common home-router ranges; a hint, never a refusal. */""}
      ${clash.length ? html`<div class="notice warn"><${Ic} i="warn"/><span>${T("Many home routers use {list}. Anyone whose home network uses the same addresses can't reach it from home — their own network wins — though it still works on mobile data. If you can, renumber this network to something rarer, like 10.57.20.0/24.", { list: clash.join(", ") })}</span></div>` : null}
      ${want.length ? html`<${NetShare} peer=${peer} draft=${share} setDraft=${setShare} nodes=${nodes} noShare=${noShare} routes=${want}/>` : null}
      ${checking ? html`<div class="loading"><span class="spin"></span>${T("Checking these networks…")}</div>` : null}
      ${((rep && rep.targets) || []).map(t => html`<${NetNode} key=${t.node} t=${t} open=${open} toggle=${toggle} stored=${stored} onSaved=${() => setRk(x => x + 1)}
          kaOff=${((rep && rep.keepalive_off) || []).includes(t.node)} pid=${pid} testable=${normKey === storedKey && !shareDirty}/>`)}
    </div>
  <//>`;
}

// ── P4: the reachability test (docs/NETWORKS-PLAN.md §8 P4) ────────────────────────────────────────────────────────
// Carried and connected is not the same as working: the device behind may never pass a packet on. So the node sends
// one probe into the network THROUGH this device and says what came back (swg-noded net_probe_run). The panel and the
// node send tokens; every sentence is here. → [dot, sentence, a second line or null].
function netProbeSays(v, node) {
  const r = v.result || {};
  const o = { addr: v.addr, node, port: v.port || "", ms: r.ms, from: r.from || "", dev: r.dev || "", detail: r.detail || "" };
  switch (r.verdict) {
    // Measured on the rig: this device's OWN address on its network answers with forwarding off, so an answer is
    // only proof when it came from something behind it. Said with the answer, the one moment it could mislead.
    case "answered": return ["on", T("{addr} answered through {node} in {ms} ms.", o),
      T("That proves the path only if {addr} is a device on the network — this device's own address there answers even when it passes nothing on.", o)];
    case "refused_port": return ["on", T("{addr} answered through {node} in {ms} ms — port {port} is closed, but the network is reachable.", o), null];
    case "unreachable": return ["blocked", r.from ? T("The device passed it on, and {from} replied that nothing is at {addr}. Check the address.", o)
      : T("The device passed it on, but nothing is at {addr}. Check the address.", o), null];
    case "no_answer": return ["blocked", T("{node} sent it through the device, which is connected, and nothing came back. The device has to pass traffic on to its network and send the answers back — see “Set up the device's side”.", o),
      v.port ? null : T("Some devices ignore pings. If {addr} might, test a port it listens on.", o)];
    case "gateway_offline": return ["off", T("The device isn't connected to {node}, so nothing reaches {addr} through it.", o), null];
    case "no_route": return ["off", T("{node} doesn't carry this network, so nothing was sent.", o),
      netWhy({ prefix: v.prefix, why: r.why, addr: r.raddr }, node)];
    case "route_elsewhere": return ["off", r.dev ? T("{node} would send {addr} out through {dev}, not through this device, so nothing was sent — clients on this interface can't reach it either.", o)
      : T("{node} has no route to {addr} yet, so nothing was sent.", o), null];
    case "no_acl": return ["off", T("{node} doesn't let this device carry {addr} yet, so nothing was sent. It catches up within a sync — test again in a moment.", o), null];
    case "not_carried": return ["off", T("{node} isn't sending {addr} through this device, so it didn't test it.", o), null];
    case "network_address": return ["off", T("{addr} is the network's own address or its broadcast — test a device on it.", o), null];
    case "no_source": return ["off", T("{node} can't read its own address on this interface, so it had nothing to send from.", o), null];
    case "expired": return ["off", r.collected ? T("{node} took the test but never answered — it may run a version that can't test networks. Update it.", o)
      : T("{node} didn't pick up the test in time. Check it's online, then test again.", o), null];
    default: return ["off", r.detail ? T("{node} couldn't run the test: {detail}", o) : T("{node} couldn't run the test.", o), null];
  }
}

// Why the panel would not arm a test (net_probe_refusal), in words. → lines.
function netProbeRefused(b, node, addr) {
  const d = b.detail || {};
  const o = { addr, node, p: d.prefix || "" };
  switch (b.why) {
    case "bad_address": return [T("{addr} isn't an IPv4 address.", o)];
    case "bad_port": return [T("A port is a number from 1 to 65535.", o)];
    case "not_deployed": return [T("This device isn't on {node}.", o)];
    case "node_offline": return [T("{node} isn't syncing, so it can't run a test right now.", o)];
    case "network_address": return [T("{addr} is the network's own address or its broadcast — test a device on it.", o)];
    case "busy": return [T("{node} is already running a test — try again in a few seconds.", o)];
    case "not_carried": return d.because ? [T("{addr} is in {p}, which this device doesn't carry:", o), netWhy({ prefix: d.prefix, ...d.because }, node)]
      : [T("{addr} isn't in a network this device carries on {node}, so it can't be tested from there.", o)];
    default: return [srvText(b) || T("Couldn't start the test.", o)];
  }
}

function NetProbe({ pid, nid, node, nets, restricted }) {
  const [addr, setAddr] = useState("");
  const [port, setPort] = useState("");
  const [test, setTest] = useState(null);       // the panel's view of the latest test on this node
  const [msg, setMsg] = useState(null);          // why a test was not armed, as lines
  const pending = !!test && test.state === "pending";
  useEffect(() => {                              // a test still running, or just answered, when the sheet opens
    let ok = true;
    api.peerNetworkProbe({ peer_id: pid }).then(r => {
      const x = r && r.ok ? (r.data || []).find(q => q.node === nid) : null;
      if (ok && x) setTest(x);
    }).catch(() => {});
    return () => { ok = false; };
  }, [pid, nid]);
  useEffect(() => {                              // the answer arrives within a couple of syncs; the panel expires it at 45 s
    if (!pending) return;
    let ok = true, n = 0;
    const h = setInterval(async () => {
      if (++n > 60) { clearInterval(h); return; }
      try {
        const r = await api.peerNetworkProbe({ peer_id: pid, id: test.id });
        if (!ok) return;
        if (r && r.ok) setTest(r.data);
        else if (r && r.why === "unknown") { setTest(null); setMsg([T("The panel no longer has that test — run it again.")]); }
      } catch (e) { /* the next tick asks again */ }
    }, 1500);
    return () => { ok = false; clearInterval(h); };
  }, [pending, test && test.id]);
  const run = async () => {
    const a = addr.trim();
    setMsg(null);
    try {
      const r = await api.peerNetworkProbe({ peer_id: pid, node: nid, addr: a, ...(port.trim() ? { port: port.trim() } : {}) });
      if (r && r.ok) { setTest(r.data); return; }
      // ⚠️ A refused attempt clears the last answer. Left on screen, "nothing is at 192.168.50.99" sat directly above
      // "192.168.1.1 isn't in a network…" and read as the new address's result — seen in the real sheet, not predicted.
      if (!(r && r.why === "busy")) setTest(null);
      setMsg(r && r.why ? netProbeRefused(r, node, a) : [srvText(r) || T("Couldn't start the test.")]);
    } catch (e) { setTest(null); setMsg([T("Couldn't start the test.")]); }
  };
  // The sheet turns Enter into Save unless an input owns the key (data-enter="self"): here Enter runs the test.
  const key = e => { if (e.key === "Enter") { e.preventDefault(); if (!pending && addr.trim()) run(); } };
  const says = test && !pending ? netProbeSays(test, node) : null;
  return html`<div class="netprobe">
    <div class="netprobe-h">${T("Test that the network answers — {node} sends it through this device:", { node })}</div>
    ${restricted ? html`<div class="hint">${T("It's sent by {node} itself, so it answers the same whoever this is shared with.", { node })}</div>` : null}
    <div class="netrow">
      <input class="mono" value=${addr} onInput=${e => setAddr(e.target.value)} onKeyDown=${key} data-enter="self" data-noautofocus
        placeholder=${T("an address on {p}", { p: nets[0] || "" })} aria-label=${T("Address to test")} autocomplete="off" spellcheck="false"/>
      <input class="mono netprobe-port" value=${port} onInput=${e => setPort(e.target.value)} onKeyDown=${key} data-enter="self" data-noautofocus
        inputmode="numeric" placeholder=${T("port")} aria-label=${T("Port to connect to — leave empty to ping")} autocomplete="off"/>
      <button class="btn" disabled=${pending || !addr.trim()} onClick=${run}>${pending ? T("testing…") : T("Test from the node")}</button>
    </div>
    ${pending ? html`<div class="netgw"><span class="condot"></span><span>${T("Waiting for {node} to send it and report back — a few seconds.", { node })}</span></div>` : null}
    ${says ? html`<div class=${"netgw t-" + says[0]}><span class=${"condot " + says[0]}></span><span>${says[1]}</span></div>` : null}
    ${says && says[2] ? html`<div class="netwhy">${says[2]}</div>` : null}
    ${msg ? msg.map(m => html`<div class="netwhy">${m}</div>`) : null}
  </div>`;
}

// ── the far side, per kind of device (docs/NETWORKS-PLAN.md §18) ────────────────────────────────────────────────────────
// ⚠️ The first version was one `sysctl -w` + one `iptables -A` for every device: gone at the router's first reboot, and no
// `iptables` at all on current OpenWrt (fw4/nftables). Each recipe below is checked against its vendor's own docs and
// survives a reboot: UCI commits to flash; RouterOS saves as you go; Keenetic saves from its web UI; wg-quick re-runs its
// PostUp on every start and starts at boot. Where the tunnel runs ON the network's router, nothing needs translating —
// the LAN already answers through it. Commands and config lines, never prose.
const netSetupSnips = sub => ({
  openwrt: ["uci -q delete network.<peer-section>.allowed_ips",   // i18n-keys: shell commands, not prose
    "uci add_list network.<peer-section>.allowed_ips='" + sub + "'",   // i18n-keys: shell commands, not prose
    "uci set network.<peer-section>.route_allowed_ips='1'", "uci commit network",   // i18n-keys: shell commands, not prose
    "uci set firewall.swg=zone", "uci set firewall.swg.name='swg'",   // i18n-keys: shell commands, not prose
    "uci set firewall.swg.input='REJECT'", "uci set firewall.swg.output='ACCEPT'", "uci set firewall.swg.forward='REJECT'",   // i18n-keys: shell commands, not prose
    "uci add_list firewall.swg.network='<wg-interface>'",   // i18n-keys: shell commands, not prose
    "uci set firewall.swg_lan=forwarding", "uci set firewall.swg_lan.src='swg'", "uci set firewall.swg_lan.dest='lan'",   // i18n-keys: shell commands, not prose
    "uci commit firewall", "service network restart", "service firewall restart"].join("\n"),   // i18n-keys: shell commands, not prose
  mikrotik: ["/interface wireguard peers set [find interface=<wg-interface>] allowed-address=" + sub,   // i18n-keys: RouterOS commands, not prose
    "/ip route add dst-address=" + sub + " gateway=<wg-interface>"].join("\n"),   // i18n-keys: RouterOS commands, not prose
  linuxConf: ["# under [Interface]",   // i18n-keys: config lines, not prose
    "PostUp = iptables -t nat -A POSTROUTING -s " + sub + " -o <lan-device> -j MASQUERADE",   // i18n-keys: config lines, not prose
    "PostUp = iptables -I FORWARD -i %i -o <lan-device> -j ACCEPT",   // i18n-keys: config lines, not prose
    "PostUp = iptables -I FORWARD -i <lan-device> -o %i -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT",   // i18n-keys: config lines, not prose
    "PostDown = iptables -t nat -D POSTROUTING -s " + sub + " -o <lan-device> -j MASQUERADE",   // i18n-keys: config lines, not prose
    "PostDown = iptables -D FORWARD -i %i -o <lan-device> -j ACCEPT",   // i18n-keys: config lines, not prose
    "PostDown = iptables -D FORWARD -i <lan-device> -o %i -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT",   // i18n-keys: config lines, not prose
    "# under [Peer]", "AllowedIPs = " + sub].join("\n"),   // i18n-keys: config lines, not prose
  linuxOnce: ["echo 'net.ipv4.ip_forward = 1' > /etc/sysctl.d/99-swg-forward.conf",   // i18n-keys: shell commands, not prose
    "sysctl -p /etc/sysctl.d/99-swg-forward.conf", "systemctl enable --now wg-quick@<wg-interface>"].join("\n"),   // i18n-keys: shell commands, not prose
  route: sub + " via <device-lan-address>",   // i18n-keys: a route in router syntax, not prose
});

function NetSetup({ sub }) {
  const [kind, setKind] = useState("openwrt");
  const S = netSetupSnips(sub);
  const box = s => html`<div class="netsnip"><pre class="mono nixblock">${s}</pre><button type="button" class="btn btn-ghost btn-mini" onClick=${() => copy(s)}><${Ic} i="copy"/> ${T("Copy")}</button></div>`;
  const kinds = [["openwrt", T("OpenWrt router")], ["mikrotik", "MikroTik"], ["keenetic", "Keenetic"],   // i18n-keys: brand names
    ["linux", T("Linux computer")], ["route", T("Route on the router")]];
  return html`<div class="netsetup">
    <div class="hint">${T("The node sends traffic to this device; the device has to pass it on to its network and send the answers back. Where does the tunnel run?")}</div>
    <div class="dpsw netsw" role="radiogroup" aria-label=${T("Where the tunnel runs")}>${kinds.map(([k, label]) => html`<button type="button" role="radio"
      aria-checked=${kind === k} class=${kind === k ? "on" : ""} onClick=${() => setKind(k)}>${label}</button>`)}</div>
    ${kind === "openwrt" ? html`
      <div class="hint">${T("On the OpenWrt router itself (22.03 or newer). Put the peer section that “uci show network | grep wireguard_” prints in place of <peer-section>, and the tunnel's interface name in place of <wg-interface>. Nothing needs translating — the router is already its network's gateway.")}</div>
      ${box(S.openwrt)}
      <div class="hint">${T("Saved to the router's memory, so it survives a reboot. Don't put the tunnel in the wan zone — that blocks it.")}</div>` : null}
    ${kind === "mikrotik" ? html`
      <div class="hint">${T("On the MikroTik itself (RouterOS 7), with its WireGuard interface in place of <wg-interface>. Nothing needs translating, the default firewall already lets the tunnel reach the network, and RouterOS saves changes as you make them.")}</div>
      ${box(S.mikrotik)}
      <div class="hint">${T("Don't add the tunnel to the WAN interface list — that blocks it.")}</div>` : null}
    ${kind === "keenetic" ? html`
      <div class="hint">${T("In the Keenetic web interface — no commands, nothing to translate:")}</div>
      <ol class="netsteps">
        <li>${T("Open the WireGuard connection. Set the peer's Allowed IPs to {subnet} and turn off “Use for accessing the Internet”. Save.", { subnet: sub })}</li>
        <li>${T("Routing → Add route: “Route to network”, destination {subnet}, interface: this WireGuard connection, “Add automatically” on. Save.", { subnet: sub })}</li>
        <li>${T("Firewall → this WireGuard connection → add a rule that allows the IP protocol. Save. A tunnel starts out blocking incoming traffic; this rule lets clients in.")}</li>
      </ol>` : null}
    ${kind === "linux" ? html`
      <div class="hint">${T("On a Linux computer on that network that runs the tunnel with wg-quick — a Raspberry Pi, a NAS, a server. Add these lines to its tunnel config, with its network card (like eth0) in place of <lan-device>:")}</div>
      ${box(S.linuxConf)}
      <div class="hint">${T("Then run this once, as root, with the tunnel's name in place of <wg-interface>:")}</div>
      ${box(S.linuxOnce)}
      <div class="hint">${T("The rules come back every time the tunnel starts, and the tunnel starts at boot. If iptables isn't installed, the tunnel won't come up — install it first.")}</div>` : null}
    ${kind === "route" ? html`
      <div class="hint">${T("If the tunnel runs on a separate Linux computer and you'd rather not translate addresses: use the Linux setup without its two MASQUERADE lines, and add this route on the network's own router:")}</div>
      ${box(S.route)}
      <div class="hint">${T("Some routers' firewalls drop the answers that come back this way — if connections start and then stall, use the Linux setup as it is.")}</div>` : null}
    ${kind !== "linux" ? html`<div class="hint">${T("Some devices on the network answer only their own network — Windows file sharing and ping, for example — and ignore {subnet}. If one doesn't answer, allow {subnet} in its firewall.", { subnet: sub })}</div>` : null}
    <div class="hint">${T("A Windows or Mac computer can't act as the gateway from here — use a router or a Linux computer.")}</div>
  </div>`;
}

// The device's own routing on this node, as a VALUE on the node's line: the config's AllowedIPs, what it means on hover, and
// the gear that opens the same per-deployment settings as Edit peer's. ⚠️ A full tunnel was a yellow warning box on every
// gateway, and it is the normal setup for a phone — it read as "something needs your attention". Only a config that leaves
// the tunnel subnet out (answers never come back) is still a warning, under the line.
function NetRouting({ t, node, sub, pid, onSaved }) {
  const g = t.gateway, p = Store.peer(pid);
  const tg = p && (p.targets || []).find(x => x.node === t.node && x.iface === t.iface);
  const meta = Store.ifaceMeta(t.node, t.iface);
  const fromOv = o => { const r = {}; if (!o) return r;              // roster overrides → the settings sheet's string fields
    if (Array.isArray(o.dns)) r.dns = o.dns.join(", ");
    if (o.mtu != null) r.mtu = String(o.mtu);
    if (o.keepalive != null) r.keepalive = String(o.keepalive);
    if (o.allowed) r.allowed = o.allowed;
    return r; };
  const opts = { ...tgtDefaults(meta), ...fromOv(p && p.overrides), ...fromOv(tg && tg.overrides) };   // target over peer over interface
  const save = async cur => {
    const r = await api.peerUpdateTarget({ peer_id: pid, node: t.node, iface: t.iface, overrides: configOverrides(cur, meta) });
    if (!(r && r.ok)) { toast(srvText(r) || T("Settings weren't saved."), "err"); return; }
    // The QR this panel shows is rebuilt from the stored config, as Edit peer does, so it carries the new routing.
    try {
      const c = p && await getConfig(p.pubkey, t.node, t.iface);
      if (c) { const s = parseFullConf(c);
        (Store.sessionConfigs[p.pubkey] = Store.sessionConfigs[p.pubkey] || {})[tkey(t.node, t.iface)] = buildConf({ privkey: s.privkey, address: s.address,
          dns: String(cur.dns).split(",").map(x => x.trim()).filter(Boolean), mtu: String(cur.mtu).trim() || 1280, awg_params: s.awg_params,
          server_pubkey: s.server_pubkey, psk: s.psk, endpoint: s.endpoint, allowed: String(cur.allowed).trim() || "0.0.0.0/0, ::/0", keepalive: String(cur.keepalive).trim() }); }
    } catch (_) { /* the roster copy is saved; only this browser's QR stays as it was */ }
    Store.configEpoch++;
    toast(T("Saved. The device uses the new settings once its config is re-imported."), "ok");
    await Store.poll();
    if (onSaved) onSaved();
  };
  const says = g.no_return
    ? T("This device's config doesn't route {subnet}, so its answers to clients leave through its own internet connection and never arrive. Add {subnet} with the gear, then re-import its config.", { subnet: sub })
    : g.full_tunnel
      ? T("This device's config sends all its traffic into the tunnel — the usual setup for a phone or laptop. On a router it means every device behind it browses the internet through {node} too; to carry only its networks, set the routing to {subnet}.", { node, subnet: sub })
      : T("This device's config sends only {allowed} into the tunnel; everything else uses its own internet connection.", { allowed: g.allowed });
  return html`<span class="netroute">
    ${/* left-anchored, not alignRight: only that placement is clamped into the viewport, and on a phone the value sits at the
          right edge — alignRight hung the bubble off the left side. */""}
    <${Popover} hoverOnly cls="netroute-pop" popCls="netroute-bub"
      trigger=${html`<span class=${"netroute-v mono" + (g.no_return ? " bad" : "")}>${g.allowed}</span>`}>
      <span class="netroute-h">${T("Client allowed IPs (routing)")}</span>${says}<//>
    <button type="button" class="btn btn-mini ico topt-gear" title=${T("Settings for this deployment (DNS, MTU, routing)")}
      aria-label=${T("Settings for this deployment (DNS, MTU, routing)")} onClick=${() => openTargetSettings({ node: t.node, iface: t.iface, opts, meta, onSave: save })}><${Ic} i="gear"/></button>
  </span>`;
}

function NetNode({ t, open, toggle, kaOff, pid, testable, stored = [], onSaved }) {
  const node = Store.nodeName(t.node);
  // `pending` = sent to the node and not routed there yet (swg-noded net_carried). It still counts as what saving means —
  // who can reach it, whose routing leaves it out, the far-side setup — just not as "carried".
  const active = t.networks.filter(n => n.state === "active" || n.state === "pending");
  const sub = t.subnet || "<tunnel-subnet>";
  return html`<div class="netnode">
    <div class="netnode-h"><span class="nm" style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${node}</span><span class="tp">${t.iface}</span>${t.address
        ? html`<span class="tp netaddr" title=${T("This device's address on {node}", { node })}>${t.address}</span>` : null}
      ${t.gateway && t.gateway.allowed != null ? html`<span class="grow"></span><${NetRouting} t=${t} node=${node} sub=${sub} pid=${pid} onSaved=${onSaved}/>` : null}</div>
    ${/* P3 evidence: is the gateway there to carry anything? Its traffic is the device's own and its networks'
          together — wg counts per peer — so it is labelled as traffic THROUGH the device. */""}
    ${t.gateway ? html`<div class=${"netgw" + (t.gateway.online ? " on" : "")}>
      <span class=${"condot " + (t.gateway.online ? "on" : "off")}></span>
      <span>${!t.gateway.reported ? T("{node} doesn't list this device yet.", { node })
        : t.gateway.online ? T("The device is connected — traffic through it:")
        : T("The device is offline, so nothing reaches these networks until it reconnects.")}</span>
      ${t.gateway.online ? html`${rateCell(t.gateway.rx_speed, t.gateway.tx_speed)}${xferCell(...dlul(t.gateway.rx_bytes, t.gateway.tx_bytes))}` : null}
    </div>` : null}
    ${kaOff ? html`<div class="notice warn"><${Ic} i="warn"/><span>${T("This device's config for {node} sends no keepalive, so {node} loses its session when the device goes quiet — and these networks with it. Set a keepalive on that deployment.", { node })}</span></div>` : null}
    ${/* Only a config that cannot work stays a warning (network_report gateway.no_return); the routing itself is on the line
          above, with its meaning on hover and the gear to change it. */""}
    ${t.gateway && t.gateway.no_return ? html`<div class="notice warn"><${Ic} i="warn"/><span>${
        T("This device's config for {node} doesn't route {subnet}, so its answers to clients leave through its own internet connection and never arrive. Add {subnet} to its routing with the gear above and re-import its config.", { node, subnet: sub })}</span></div>` : null}
    <div class="netlist">${t.networks.map(n => html`<span class=${"nettag s-" + n.state}><span class="mono">${n.prefix}</span><em>${
      n.state === "active" ? T("carried")
      : n.state === "pending" ? (stored.includes(n.prefix) ? T("waiting for {node}", { node }) : T("carried once saved"))
      : n.state === "refused_by_node" ? T("refused by the node") : T("not carried")}</em></span>`)}
      ${active.length ? html`<span class="grow"></span><${NetCounts} t=${t} node=${node}/>` : null}</div>
    ${/* A restriction the node could not apply is not a number — nobody reaches the networks there, so it stays a line. */""}
    ${t.share && t.share.node && t.share.node.ok === false ? html`<div class="netref"><div><${Ic} i="warn"/><span>${T("{node} couldn't apply the restriction, so nobody reaches these networks there until it can: {detail}",
        { node, detail: t.share.node.detail || t.share.node.why || "" })}</span></div></div>` : null}
    ${t.networks.some(n => n.state === "pending" && stored.includes(n.prefix))
      ? html`<div class="netwhy">${T("{node} hasn't routed it yet — it does on its next sync, usually within a minute.", { node })}</div>` : null}
    ${/* One line per REASON, not per network: two networks refused for the same node-wide reason ("can't restrict") printed
          the identical sentence twice, under a warning that had already said it. */""}
    ${/* `share_unsupported` is left to the warning at "Who can reach these networks", which names the node and the way out;
          repeated here it was the same news twice in one window. */""}
    ${[...new Set(t.networks.filter(n => n.state !== "active" && n.state !== "pending" && n.why !== "share_unsupported")
        .map(n => netWhy(n, node)))].map(s => html`<div class="netwhy">${s}</div>`)}
    ${/* NETWORKS §17 F1: the device is blocked or expired, so its networks go nowhere — and the people who used them are
          not told by anything on their side. Said here, where the block is visible, with the list one click away. */""}
    ${t.lost ? html`<div class="notice warn"><${Ic} i="warn"/><span>${T("Blocked, so {peers} of {users} lose these networks until it is unblocked — their devices keep sending that traffic into the tunnel, where nothing answers.",
        { peers: plural(t.lost.peers, "peer"), users: plural(t.lost.users, "gen|user") })}</span></div>
      <${Disclosure} title=${T("Who loses these networks: {peers}", { peers: plural(t.lost.total, "peer") })}
        open=${!!open[t.node + "|l"]} onToggle=${() => toggle(t.node + "|l")}>
        <${NetPagedRows} rows=${t.lost.list} total=${t.lost.total}
          render=${w => html`<div class="netwiden" key=${w.peer_id}><span class="grow">${netPeerName(w.peer_id)}</span><span class="tp">${w.iface}</span></div>`}/>
      <//>` : null}
    ${/* NETWORKS §17 F5: Force DNS on this node answers every lookup itself; the node lets DNS to this network through, so
          names on it resolve — and a client that uses a resolver there skips Force DNS for everything it looks up. */""}
    ${t.force_dns ? t.force_dns.exempt.map(p => html`<div class="notice warn"><${Ic} i="warn"/><span>${T("Clients of {ifaces} on {node} that use a DNS server on {p} skip Force DNS: those lookups aren't blocked or routed by name.",
        { ifaces: t.force_dns.ifaces.join(", "), node, p })}</span></div>`) : null}
    ${t.widen_total ? html`<${Disclosure} title=${T("Narrowed routing, can't reach it: {peers}", { peers: plural(t.widen_total, "peer") })}
        open=${!!open[t.node + "|w"]} onToggle=${() => toggle(t.node + "|w")}>
      <${NetPagedRows} rows=${t.widen} total=${t.widen_total}
        render=${w => html`<div class="netwiden" key=${w.peer_id + "|" + w.iface}><span class="grow">${netPeerName(w.peer_id)}</span><span class="tp">${w.iface}</span>
          <span class="mono faint">${w.allowed}</span>
          <button class="btn btn-ghost btn-mini" onClick=${() => { const q = Store.peer(w.peer_id); if (q) openEditPeer(q, { node: t.node, iface: w.iface }); }}>${T("Edit routing")}</button></div>`}/>
      <div class="hint">${T("A widened device reaches these networks only after its user re-imports the config or refreshes their subscription.")}</div>
    <//>` : null}
    ${active.length ? html`<${Disclosure} title=${T("Set up the device's side")} open=${!!open[t.node + "|s"]} onToggle=${() => toggle(t.node + "|s")}>
      <${NetSetup} sub=${sub}/>
    <//>` : null}
    ${/* The test is a tool, not a status: it lives last, folded, after the setup it checks. Only for what is SAVED (a draft
          network is carried nowhere, so the panel would refuse the test) and only through a keyed deployment. */""}
    ${testable && t.gateway && t.networks.some(n => n.state !== "inert") ? html`<${Disclosure} title=${T("Connection test")}
        open=${!!open[t.node + "|t"]} onToggle=${() => toggle(t.node + "|t")}>
      <${NetProbe} pid=${pid} nid=${t.node} node=${node} nets=${t.networks.filter(n => n.state !== "inert").map(n => n.prefix)} restricted=${!!t.share}/>
    <//>` : null}
  </div>`;
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
  const [a, b] = Tsplit("Mesh settings (ingress address, subnet, port, prefix, AWG) for this node are configured in {where} — select this node there.", "where");
  return html`<${Fragment}>${a}<a href="#/panel/settings">${T("Panel settings → Network")}</a>${b}<//>`;
}
function migrateIntro(name) {
  const [a, r1] = Tsplit("This gives you a one-line command to run on the {newbox}. It pulls everything the panel holds for {name} — its interfaces with their original keys and settings, its turn-proxies, its place in the mesh — so the node comes back as itself.", "newbox");
  const [b, c] = [r1.split("{name}")[0], r1.split("{name}").slice(1).join("{name}")];
  return html`<${Fragment}>${a}<b>${T("new box")}</b>${b}<b>${name}</b>${c}<//>`;
}
/* T-10's opening line, and it exists to say the one thing that surprises people: NOTHING HAPPENS TO THE
   BOX. Migrate rebuilds the node somewhere else; Transfer leaves it exactly where it is and changes only
   which panel it answers to. */
function transferIntro(name) {
  const [a, r1] = Tsplit("This hands {name} to another panel. The server itself is {untouched} — same box, same interfaces, same addresses — it just starts syncing over there. Its users, their peers and their stored configs go with it.", "name");
  const [b, c] = [r1.split("{untouched}")[0], r1.split("{untouched}").slice(1).join("{untouched}")];
  return html`<${Fragment}>${a}<b>${name}</b>${b}<b>${T("not touched at all")}</b>${c}<//>`;
}
function restoreOrMigrateIntro(name) {
  const [a, r1] = Tsplit("{name} isn't reporting. This gives you a one-line command that rebuilds it from what the panel holds — run it on the {either}. Either way the node comes back as itself, with its interfaces, keys and turn-proxies.", "name");
  const [b, c] = [r1.split("{either}")[0], r1.split("{either}").slice(1).join("{either}")];
  return html`<${Fragment}>${a}<b>${name}</b>${b}<b>${T("same box, a damaged one, or a brand-new one")}</b>${c}<//>`;
}
function oldBoxLive(name, when) {
  // ⚠️ no `vars` here: passing {when} through T would interpolate it, leaving nothing to split on — the
  // whole remainder becomes `b` and the value renders TWICE. A marker is either a variable or a split point.
  const [a, r1] = Tsplit("{name} was migrated {when}. The old box is still running and still serving the peers it had — it simply stopped syncing with this panel. Nothing on it was changed.", "name");
  const [b, c] = [r1.split("{when}")[0], r1.split("{when}").slice(1).join("{when}")];
  return html`<${Fragment}>${a}<b>${name}</b>${b}<b>${when}</b>${c}<//>`;
}

/* What the arming actually did, shown ABOVE the command that must not be run until it has been read.
   There is no dry-run: arming IS how these lists are computed, so this is the only moment they exist —
   after the token is rotated and before the box is wiped, which is exactly when they are useful.
   `no_escrow` is the one that costs a user something, so it is the one that shouts. (T-11 refines the
   presentation; it does not own whether the operator is told.) */
export function RebuildOutcome({ d, preview }) {
  /* TWO BLOCKS, and every line names the thing before its fate.
     The first version wrote each fact as a sentence ending in a list of names — "The panel holds no config
     for these …: awg9, awg1, wg0" — which never said what the names WERE, and folded three different
     reasons into one wording that fitted none of them. So: what will not survive, then what will, each as
     labelled rows in the `ifrow` form this sheet already uses for addresses. The label is the category and
     the value is the thing it happened to, which is the question an operator actually has.

     `preview` = shown by T-11's pre-flight, before anything is armed. Every line reads as a prediction
     either way; only the rollback block below is past tense, and both confirm sheets already say that in
     their own words, so the preview drops it rather than repeating it wrongly. */
  if (!d) return null;
  const armed = d.armed || [], ne = d.no_escrow || [], un = d.unrestorable || [];
  const turn = d.turn || [], addr = (d.address || []).filter(a => a && a.action);
  const fam = d.turn_family || [];
  const orph = d.orphan_escrow || [], incomp = d.incomplete || [], tdead = d.turn_dead || [];
  const row = (label, value) => html`<div class="ifrow"><span class="l">${label}</span><span class="r">${value}</span></div>`;

  /* WHAT COMES BACK — three rows, named the way the node names them. The first cut had six, and they were
     six ANSWERS to questions nobody asked: which keys came out of the vault, that csqtt regenerates its own
     owner password, that a WDTT server takes its config from the panel and its users from the roster. All
     true, all mechanism, and between them they buried the only thing an operator is reading this box for —
     WHICH INTERFACES COME BACK. A turn-family server is an interface here because that is what it is on the
     node page and on the box; splitting it out was the panel explaining its own internals. */
  const kept = [
    (armed.length || fam.length)
      ? [T("Interfaces"), [...armed, ...fam.map(x => x.iface)].join(", ")] : null,
    turn.length ? [T("Turn proxies"), turn.join(", ")] : null,
    /* Names, not "2 links" — a count is the one row that cannot be matched to anything on the box. */
    (d.mesh_ifaces || []).length ? [T("Mesh links"), (d.mesh_ifaces || []).join(", ")] : null,
  ].filter(Boolean);

  /* WHAT DOESN'T — the same three sections, but per ITEM and with the reason, because here the reason is
     the whole message. One name can carry several (unrestorable AND no escrow AND missing its MTU), so
     they are collected by name and joined rather than listed as three separate rows about one interface. */
  const FIELD = { mtu: T("MTU"), listen_port: T("port"), address: T("address"), awg_params: T("obfuscation") };
  const lostBy = new Map();      // name -> { proxy: bool, why: [reason, ...] }
  const note = (name, why, proxy) => {
    if (!name || !why) return;
    const e = lostBy.get(name) || { proxy: !!proxy, why: [] };
    if (proxy) e.proxy = true;
    if (!e.why.includes(why)) e.why.push(why);
    lostBy.set(name, e);
  };
  /* The reason is phrased HERE, from the structured fields, not taken from the server's `why`. Two reasons,
     and the second is the one that decided it: these render beside a name, so they have to be a clause and
     not a paragraph — the server's `why` is a full explanation written for the API; and the server's copy
     is not translatable (the i18n extractor cannot take `"why":` wholesale, because the same key carries
     the fingerprint diff's `%s`-formatted diagnostics, which its own gate rejects). An unknown shape still
     falls back to `why`, so a category added server-side reads as English rather than vanishing. */
  const famNames = new Set(fam.map(x => x && x.iface));
  const REASON = {
    unrecorded_turn: x => (x.users
      ? T("no record here — neither it nor its {v1} come back", { v1: plural(x.users, "user") })
      : T("no record here — it does not come back")),
    unrecorded: () => T("no record here — it comes back only if the box's own configuration recreates it"),
    no_config: () => T("the panel never captured a config for it — it can only be recreated fresh"),
    turn: () => T("unknown fork or unreadable bind — re-add this proxy by hand"),
  };
  for (const x of un) {
    if (!x || !x.iface) continue;
    note(x.iface, (REASON[x.kind] || (() => x.why))(x), x.kind === "turn");
  }
  for (const x of ne) {
    note(x && x.iface, famNames.has(x && x.iface)
      ? T("no usable escrow for its identity — it comes back holding, and recreating it re-keys every user")
      : T("no escrow and no key backup — it comes back with a new key, so its clients re-import"));
  }
  for (const x of orph) note(x && x.iface, T("its escrowed key opens for nobody — re-seal it before the box is wiped"));
  for (const x of incomp) {
    note(x && x.iface, T("comes back without its {v1}", {
      v1: (x.missing || []).map(f => FIELD[f] || f).join(", ") }));
  }
  for (const x of tdead) {
    note(x && x.service, T("forwards to {v1}, which is not coming back", { v1: x && x.iface }), true);
  }
  const lostRows = kind => [...lostBy.entries()].filter(([, e]) => !!e.proxy === kind)
    .map(([name, e]) => html`<div class="ifrow" style="align-items:baseline">
      <span class="l" style="font-weight:600;white-space:nowrap">${name}</span>
      <span class="r" style="text-align:left;opacity:.85">${e.why.join(" · ")}</span></div>`);
  const lostIf = lostRows(false), lostTp = lostRows(true);
  const lost = lostIf.length || lostTp.length;

  /* Two boxes, and the colour is still the summary: DANGER when something comes back re-keyed or a server
     the panel never recorded does not come back at all — the two cases with a guaranteed cost to the people
     using them. */
  const danger = ne.length || un.some(x => x && x.kind === "unrecorded_turn");
  const box = (cls, icon, heading, rows, tail) => html`<div class=${"notice " + cls}>
    <${Ic} i=${icon}/>
    <div style="flex:1;min-width:0">
      <b>${heading}</b>
      <div class="ifcard-rows" style="margin-top:7px">${rows.map(([l, v]) => row(l, v))}</div>
      <div style="margin-top:8px">${tail}</div>
    </div>
  </div>`;
  const sect = (title, rows) => (rows.length ? html`<${Fragment}>
      <div class="seclabel" style="margin:10px 0 4px">${title}</div>
      <div class="ifcard-rows">${rows}</div><//>` : null);
  /* ADDRESSES BELONG IN HERE, not in a bare section of their own below the green box. They are the same
     KIND of thing as the rows above them — something to notice before you go, not a blocker — and putting
     them outside every box left them reading as body text nobody had classified, after two boxes that had
     been. The heading follows the tone: a genuine loss still says so. */
  /* ONE ROW PER THING, but only the things that CHANGE — which is what makes naming them worth the room
     again. Everything derived (a hostname endpoint, a wildcard bind, an auto source) is silent, so a row
     here is always an address somebody typed. Name it, put the port with the name where it never changes,
     and keep the mapping to hosts alone. The earlier version fought a dotted record path against a quoted
     sentence in two columns and both wrapped; the one before this collapsed to the address and lost which
     server it belonged to. */
  const hostOf = v => String(v == null ? "" : v).replace(/:\d+$/, "");
  const portOfAddr = v => { const m = String(v == null ? "" : v).match(/:(\d+)$/); return m ? ":" + m[1] : ""; };
  const addrLabel = a => {
    const p = String(a.path || "").split(".");
    const port = portOfAddr(a.from);
    const svc = n => String(n || "").replace(/^vk-turn-proxy-/, "").replace(/-\d+$/, "");
    if (p[0] === "turn" && p.length >= 3) return svc(p.slice(1, -1).join(".")) + port + " " + T("word|endpoint");
    if ((p[0] === "wdtt" || p[0] === "csqtt") && p.length >= 3) return p[1] + port + " " + T("word|endpoint");
    if (p[0] === "ifaces" && p[2] === "endpoint_host") return p[1] + port + " " + T("word|endpoint");
    if (p[0] === "ifaces" && p[2] === "egress_ip") return p[1] + " " + T("word|egress");
    return { default_egress_ip: T("this node") + " " + T("word|egress"),
             panel_ip: T("word|panel source"),
             mesh_egress_ip: T("word|mesh source"),
             endpoint_host: T("this node") + " " + T("word|endpoint") }[a.path] || a.path;
  };
  const addrRows = (addr || []).map(a => html`<div class="ifrow addrrow">
    <span class="l addr">${addrLabel(a)}</span>
    <span class="r addr">${a.from !== undefined
      ? html`${hostOf(a.from) || T("val|auto")} <span class="faint">→</span> ${hostOf(a.to) || T("val|auto")}`
      : a.action}</span></div>`);
  const lostBody = html`<div style="margin-top:2px">
    ${sect(T("Interfaces"), lostIf)}${sect(T("Turn proxies"), lostTp)}${sect(T("Addresses"), addrRows)}
    ${addr.length ? html`<div style="margin-top:6px">${T("The panel changes these for you when the node comes back. An address of the old box cannot be bound on the new one, and its address is not known yet — so a listener becomes 0.0.0.0, which is every address the new box turns out to have, and a source address becomes auto. Clients are unaffected either way: a wildcard listener is what tells the panel to advertise this node's ingress name, exactly as a wg/awg interface already does. Anything not listed keeps what it has.")}</div>` : null}
  </div>`;
  return html`<${Fragment}>
    ${lost || addr.length ? html`<div class=${"notice " + (danger ? "danger" : "warn")}>
      <${Ic} i="warn"/>
      <div style="flex:1;min-width:0">
        <b>${danger ? T("What the panel can't bring back") : T("Worth knowing before you do this")}</b>
        ${lostBody}
        ${/* No closing sentence. Every row already carries its own reason — that is what made a blanket
              one wrong twice over: it first claimed nothing could be restored while the list above it said
              otherwise, and then, reworded, restated what each line had just said. A description in this
              box belongs to a SECTION, in the box's own colour; there is nothing left to say about all of
              them at once. */''}
      </div>
    </div>` : null}
    ${kept.length ? box("ok", "check", T("What comes back as it is"), kept,
        T("The configs your users already have keep working — nothing has to be re-sent.")) : null}

    ${preview ? null : d.superseded
      ? html`<div class="notice"><${Ic} i="info"/><span>${T("The old box keeps running and keeps serving its peers — it just stops syncing here. One click rolls this panel back to it, from the badge on the node, for as long as you keep it.")}</span></div>`
      : html`<div class="notice warn"><${Ic} i="warn"/><span>${T("No rollback point was kept: this node wasn't reporting, so there was nothing running to roll back to. The command below is the way back.")}</span></div>`}
  <//>`;
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
    if (!V.nodeName(name)) return setMsg({ k: "err", t: T("Name: 1–40 chars, letters/digits/-/_ only.") });
    setMsg({ k: "work", t: T("creating…") });
    const r = await api.nodeCreate({ name: name.trim(), endpoint_host: "", color });
    if (!r.ok) return setMsg({ k: "err", t: srvText(r) || T("couldn't create node") });
    await Store.poll(); openModal(html`<${NodeTokenSheet} name=${r.data.name} token=${r.data.token} isNew=${true}/>`);
  };
  return html`<${Sheet} title=${T("Add node")}
    foot=${footRow({ onCancel: closeModal, onAction: create, action: T("Create node") })}>
    <div class="field"><label>${T("Name")}</label>
      <div class="namerow"><input autofocus class=${nameBad ? "bad" : ""} value=${name} onInput=${e => setName(e.target.value)} placeholder="msk-edge1" autocomplete="off"/>
        <${ThemedSwatch} val=${color} title=${T("Node colour")} onChange=${setColor} sample=${(c) => html`<span class="tg" style=${"background:color-mix(in srgb," + c + " 16%,transparent);color:" + c}>${name.trim() || "node"}</span>`}/></div>
      <div class=${"hint" + (nameBad ? " err" : "")}>${nameBad ? T("1–40 chars: letters, digits, - or _ only.") : T("A label for this node — you can rename it anytime. The swatches set its colour per theme.")}</div></div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}
export const BOOTSTRAP_URL = "https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh";

/* Enrolment for a node whose installation is its configuration's. NOT a command — the installer is
   the wrong shape here twice over: it would write into /opt on a host whose own tooling cannot see
   that, and re-running it is not how such a node is re-enrolled anyway.

   ⚠️ The token is NOT in the snippet, and that is the point rather than an omission. A Nix option's
   value lands in the world-readable store, so the module takes a PATH to a file it reads at runtime
   and asserts against a path literal for exactly this reason. Printing `environmentFile = "…"` beside
   the token, with the token shown separately, is the only shape that stays true to that. */
/* The declarative install as a copy-paste SEQUENCE of commands, not a lone config block with
   comments nobody can act on. Each entry is [label, code]; a fresh node gets all three steps, a
   recovery just re-writes the token file and rebuilds (its flake already exists).

   ⚠️ The token goes into a FILE by command (step 1), so the config only ever names a PATH — a value
   written into a Nix option lands in the world-readable store. That is what the old "# NODE_TOKEN"
   comment was trying, and failing, to convey. The flake names its config `swg` and points
   `selfUpdate.flakeRef` at it, so the panel's Update button works with nothing else to set. */
function nixNodeSteps(host, endpoint, token, recovery, mode) {
  const ep = endpoint || "203.0.113.10";
  const podman = mode === "podman";
  // Native takes the raw token via LoadCredential; the container arm reads NODE_TOKEN= from an env
  // file, because a host credential cannot cross into a container (node.nix's tokenFile assertion).
  const tokenCmd = podman ? [
    "sudo install -d -m 700 /etc/swg-secrets",
    `printf 'NODE_TOKEN=%s\\n' '${token}' | sudo tee /etc/swg-secrets/swg-node.env >/dev/null`,
    "sudo chmod 600 /etc/swg-secrets/swg-node.env",
  ].join("\n") : [
    "sudo install -d -m 700 /etc/swg-secrets",
    `printf %s '${token}' | sudo tee /etc/swg-secrets/swg-node-token >/dev/null`,
    "sudo chmod 600 /etc/swg-secrets/swg-node-token",
  ].join("\n");
  // The one block that differs between the arms — the engine + which token option. The container arm
  // runs the published image via podman (nixpkgs flags the docker package insecure; podman is not),
  // and everything else it needs (the runtime, host sysctls, tmpfiles) the module turns on itself.
  // ⚠️ native REQUIRES delivery = "native": tokenFile is rejected on the container default, so
  // omitting it is a build failure, not a silent fallback.
  const svc = podman ? [
    "        { services.swg-node = {",   // i18n-keys: generated Nix — file text, copied verbatim
    "            enable = true;",   // i18n-keys: generated Nix — file text, copied verbatim
    '            delivery = "container";',
    "            # nixpkgs flags docker insecure on 25.11",   // i18n-keys: generated Nix — file text, copied verbatim
    '            backend = "podman";',
    `            panelUrl = "${host}";`,
    `            endpoint = "${ep}";   # the public IP CLIENTS dial`,
    '            environmentFile = "/etc/swg-secrets/swg-node.env";',
    '            selfUpdate.flakeRef = "/etc/nixos#swg";',
    "        }; }",
  ] : [
    "        { services.swg-node = {",   // i18n-keys: generated Nix — file text, copied verbatim
    "            enable = true;",   // i18n-keys: generated Nix — file text, copied verbatim
    '            delivery = "native";',
    `            panelUrl = "${host}";`,
    `            endpoint = "${ep}";   # the public IP CLIENTS dial`,
    '            tokenFile = "/etc/swg-secrets/swg-node-token";',
    '            selfUpdate.flakeRef = "/etc/nixos#swg";',
    "        }; }",
  ];
  const flake = [
    "{",
    '  inputs.nixpkgs.url   = "github:NixOS/nixpkgs/nixos-25.11";',
    '  inputs.swg-panel.url = "github:SanityProtocol/swg-panel";',
    "  outputs = { self, nixpkgs, swg-panel }: {",   // i18n-keys: generated Nix — file text, copied verbatim
    "    nixosConfigurations.swg = nixpkgs.lib.nixosSystem {",   // i18n-keys: generated Nix — file text, copied verbatim
    '      system = "x86_64-linux";',
    "      modules = [",   // i18n-keys: generated Nix — file text, copied verbatim
    "        ./configuration.nix",
    "        swg-panel.nixosModules.swg-node",
    ...svc,
    "      ];",
    "    };",
    "  };",
    "}",
  ].join("\n");
  const buildCmd = podman ? [
    "cd /etc/nixos && sudo git init -q -b main && sudo git add -A",   // i18n-keys: a shell command the operator runs verbatim
    "sudo nixos-rebuild switch --flake /etc/nixos#swg",
  ].join("\n") : [
    "cd /etc/nixos && sudo git init -q -b main && sudo git add -A",   // i18n-keys: a shell command the operator runs verbatim
    "sudo nixos-rebuild switch --flake /etc/nixos#swg",
    "sudo reboot   # once, so the AmneziaWG kernel module loads",
  ].join("\n");
  if (recovery) return [
    [T("① Replace the token file on the node"), tokenCmd],
    [T("② Rebuild to pick it up"), "sudo nixos-rebuild switch --flake /etc/nixos#swg"],
  ];
  return [
    [T("① Save the enrolment token on the node"), tokenCmd],
    [T("② Create /etc/nixos/flake.nix"), flake],
    [podman ? T("③ Build and switch") : T("③ Build, switch, then reboot for the kernel datapath"), buildCmd],
  ];
}

/* THE TRANSFER TOKEN. One value carrying the two things a transfer needs — this panel's address and a
   token valid here — so the other panel's Transfer window can ask for ONE thing instead of "the whole
   enrolment command". The command was always the wrong artifact to ask for: it is a carrier for these
   two values, and for a declarative (NixOS) node there is no `-key` in it at all, so an operator had
   nothing to copy and no way to tell which of the offered commands was the right kind.

   Minted here, in the browser, from `location.origin` — deliberately the same source the commands use,
   so the address in the token is whatever address the operator actually reached this panel on.

   It does NOT replace the enrolment token, and the commands below are byte-identical to before: every
   bootstrap.sh already published passes `-key` through verbatim, so a compound value there would fail
   authentication on every existing installer. Two fields, two jobs. */
function transferToken(host, token) {
  const json = JSON.stringify({ u: host, t: token, k: "" });
  const b64 = btoa(String.fromCharCode(...new TextEncoder().encode(json)));
  return "swgx1_" + b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function NodeTokenSheet({ name, token, isNew, kind, platform, endpoint, rebuild }) {
  const host = `${location.origin}${BASE}`;
  const bare = `curl -fsSL ${BOOTSTRAP_URL} | sudo bash -s node -key ${token} -host ${host}`;
  const docker = `curl -fsSL ${BOOTSTRAP_URL} | sudo bash -s docker node -key ${token} -host ${host}`;
  const nixos = platform === "nixos";
  const fresh = !kind && !nixos;                       // brand-new node → offer BOTH styles as tabs
  /* …and so does a MIGRATION, which is the one moment changing run model is free. The command used to be
     pinned to the kind the node has now — right for a rotate (same box, same install) and needlessly
     narrow here: a migration installs onto a DIFFERENT box, nothing in what it carries is run-model
     specific (keys, peers, escrow, turn identities all restore either way), and the panel adopts whatever
     the new node reports on its first sync. So offer both, with the current kind preselected. Declarative
     hosts keep their own arm: a bash install there would fight the configuration that owns the box. */
  const bothWays = !nixos && !!rebuild;
  const [tab, setTab] = useState(nixos ? "nix" : "std");
  const [armedOpen, setArmedOpen] = useState(false);   // the pre-flight, folded — see below
  /* THREE SHEETS SHARE THIS ONE, and they do not ask the same question:
       create   — a node that does not exist yet: how do I install it?
       migrate  — a node that exists: how do I stand it up on a NEW box? (rebuild is armed)
       rotate   — a node that exists and is fine: its credential changed, how do I tell it?
     Only the last one has an answer that is not an install command, and it was being shown the install
     commands anyway — under a sentence about "restoring" a node nobody is restoring. */
  const rotate = !isNew && !rebuild;
  const [nmode, setNmode] = useState("native");   // Declarative tab: which arm — kernel (native) or the published image via podman
  const nixSteps = nixNodeSteps(host, endpoint, token, !!kind, nmode);

  const copyBlock = (label, code, block) => html`<div class="field"><label>${label}</label>
    <div class="cmdrow"><div class=${"tokenbox" + (block ? " block" : "")}>${code}</div>
      <button class="copyaction" onClick=${() => copy(code, T("Copied"))}><${Ic} i="copy"/> ${T("Copy")}</button></div></div>`;

  /* T-20 — THE CREDENTIAL ALONE. Every command on this sheet re-installs the node; none of them just fixes
     its token. Measured the hard way twice in one session: a rotate landed on the wrong node and on the
     wrong panel, and both times the only doors were a full re-install or "Restore or migrate", which arms a
     rebuild — a baseline, a create request per interface, a mesh re-provision — for a box that is perfectly
     healthy and merely holding the wrong credential.

     Per run-model, because where the token LIVES differs and nothing detects it reliably from inside a
     one-liner: bare-metal swg-noded reads /etc/swg-agent/config.json directly, while docker and NixOS launch
     through node-entrypoint.sh, which prefers the /var/lib/swg-noded/panel-token mirror — and that mirror is
     on the bind mount (survives a container recreate) and outranks the flake's token file (survives a
     nixos-rebuild), which is exactly why the entrypoint reads it first.

     It changes the TOKEN and nothing else. Not the URL, not `verify`, not the pinned fingerprint: the node
     is already reaching this panel on that posture, and rewriting it is how you turn a locked-out node into
     an unreachable one. A node that must move to a different ADDRESS is a re-point, which has its own verb. */
  const fixBare = `sudo python3 -c 'import json,sys;p="/etc/swg-agent/config.json";c=json.load(open(p));c.setdefault("panel",{})["token"]=sys.argv[1];json.dump(c,open(p,"w"),indent=2)' ${token} && sudo systemctl restart swg-noded`;
  const fixCtr = `sudo docker exec swg-node sh -c 'printf %s "$1" > /var/lib/swg-noded/panel-token; chmod 600 /var/lib/swg-noded/panel-token' sh ${token} && sudo docker restart swg-node`;
  const fixNix = `sudo sh -c 'printf %s "$1" > /var/lib/swg-noded/panel-token; chmod 600 /var/lib/swg-noded/panel-token' sh ${token} && sudo systemctl restart swg-noded`;
  const fixCmd = nixos ? fixNix : kind === "docker" ? fixCtr : fixBare;
  /* …and NOT on a migration. "Fix only the credential" repairs a node whose install is fine and whose
     token is stale — which is not the situation on a box that does not have the node yet. It was the last
     thing on the screen and the longest command on it, answering a question this step never asks. */
  const fixBlock = ((kind || nixos) && !rebuild) ? html`<div class="field"><label>${T("Only fix the credential — no re-install")}</label>
    <div class="cmdrow"><div class="tokenbox">${fixCmd}</div>
      <button class="copyaction" onClick=${() => copy(fixCmd, T("Copied"))}><${Ic} i="copy"/> ${T("Copy")}</button></div>
    <div class="hint">${T("Run this when the node is healthy and only its token is wrong — after a rotate that landed somewhere unexpected, say. It changes the token and restarts the node; it installs nothing, touches no interface, and leaves the panel address and TLS settings exactly as they are.")}</div>
  </div>` : null;

  // The imperative install — bare-metal / Docker, a one-line command each.
  const runLabel = (col, l) => html`${T("Run on the node —")} <span style=${"color:" + col + ";font-weight:700"}>${l}</span>`;
  const standardTab = html`<${Fragment}>
    ${copyBlock(runLabel("#60a5fa", kindLabel("baremetal")), bare, false)}
    ${copyBlock(runLabel("#c084e8", kindLabel("docker")), docker, false)}
    <div class="hint">${T("Pick the one this node runs. Each fetches the installer and prompts for the endpoint.")}</div>
  <//>`;

  // The declarative install — a command sequence for NixOS.
  // The declarative install differs by arm in more than one line — delivery, the token file, and
  // whether a reboot is needed — so it gets its own switch rather than a single flake with a caveat.
  // The two arms ride on the tab row itself, right-aligned — they are a property OF the declarative
  // install, not a second choice of equal weight, and a second full-width tablist under the first read
  // as one. Each side wears the colour its run-model wears everywhere else in the panel (the bare-metal
  // and docker pills), so the switch says which datapath it means before the label is read.
  const armSwitch = html`<div class="armsw" role="tablist" aria-label=${T("Delivery")}>
    <button role="tab" aria-selected=${nmode === "native"} class=${"bare" + (nmode === "native" ? " on" : "")} onClick=${() => setNmode("native")}>${T("Bare-metal (kernel)")}</button>
    <button role="tab" aria-selected=${nmode === "podman"} class=${"ctr" + (nmode === "podman" ? " on" : "")} onClick=${() => setNmode("podman")}>${T("Podman (container)")}</button>
  </div>`;
  const nixTab = html`<${Fragment}>
    ${nixSteps.map(([label, code]) => copyBlock(label, code, true))}
    <div class="hint">${kind
      ? T("This node's configuration already declares it — the two steps above just refresh the token and rebuild.")
      : nmode === "podman"
        ? T("Runs the published image via podman (nixpkgs flags the docker package insecure; podman is not), no reboot. Replace the endpoint with this server's public IP — the panel's Update button then works with nothing else to set.")
        : T("Fresh box shown; if you already use a flake, add the swg-panel input and the services.swg-node block to yours instead. Replace the endpoint with this server's public IP — the panel's Update button then works with nothing else to set.")}</div>
  <//>`;

  return html`<${Sheet} title=${(isNew ? T("Node created")
      : rebuild ? (rebuild.was_reporting ? T("Migrate") : T("Restore or migrate"))
      : T("New token")) + " · " + name}
    foot=${html`<button class="btn btn-primary" onClick=${closeModal}>${T("Done")}</button>`}>
    ${/* THE SUBJECT OF THIS STEP IS THE COMMAND. Everything below used to arrive at once: the whole
          pre-flight again, the enrolment token, the transfer token, both commands and the credential-only
          repair — on a screen whose one job is "run this on the new box". The operator read the outcome on
          the previous step and pressed Prepare; repeating it in full pushed the command off the fold.
          It stays reachable, folded, because it is the record of what was armed. */ null}
    ${rebuild ? html`<${Disclosure} title=${T("What was armed")} open=${armedOpen} onToggle=${() => setArmedOpen(!armedOpen)}>
        <${RebuildOutcome} d=${rebuild}/><//>
      <div class="seclabel">${T("Run this on the box")}</div>` : null}
    ${/* …and the warning says what to copy. With the standalone token field gone from a migration, "copy
          it now" pointed at nothing on screen; the token is inside the command below, so that is what has
          to leave this sheet with the operator. */ null}
    <div class="notice warn"><${Ic} i="warn"/><span><b>${T("Shown once.")}</b> ${rebuild && !nixos
      ? T("The command below carries a token that authenticates the node to this panel — copy the command now. You can rotate the token later if it leaks.")
      : T("This token authenticates the node to the panel — copy it now. You can rotate it later if it leaks.")}</span></div>
    ${/* `recoversAs` said "restores this node as <method> — to change it, convert the node". A ROTATE
          restores nothing, and a MIGRATION now offers both methods a few lines below, so the sentence
          contradicted the screen it was on in both places. The hint under the two commands says the true
          version of it in one line. */ null}
    ${/* …and the token by itself only where something actually needs it typed: the declarative arm writes
          it into a tokenFile. Everywhere else the command below carries it, so the field was a second copy
          of a secret for no one. */ null}
    ${/* Both credentials, and each only where it is the answer to something.
          · the ENROLMENT token by itself: only the declarative arm needs it typed (into a tokenFile).
            Everywhere else the command below already carries it, so the field was a second copy of a
            secret for nobody.
          · the TRANSFER token: for handing this node to ANOTHER PANEL. On a migration — a new box, same
            panel — it answers a question nobody asked, and it is the longest string on the screen. */ null}
    ${nixos || !rebuild ? html`<div class="field" style="margin-top:15px"><label>${T("Enrollment token")}</label><div class="cmdrow"><div class="tokenbox">${token}</div><button class="copyaction" onClick=${() => copy(token, T("Copied"))}><${Ic} i="copy"/> ${T("Copy")}</button></div></div>` : null}
    ${/* …and the transfer token only where a record is WAITING TO RECEIVE one. It says "this panel, and a
          node key valid here", which is an invitation — meaningful for a record nothing is running behind
          yet, and meaningless on a live node, where accepting it would mean pushing somebody else's node
          into a record that already has interfaces and peers. `kind` is the discriminator: the panel only
          learns it from a node that has actually reported. So: Add node, yes; a rotate on a placeholder
          whose token was lost, yes — that is the one rotate where this is the point; a rotate on a running
          node, no; a migration, no (it has reported, by definition). */ null}
    ${(kind || rebuild) ? null : html`<div class="field"><label>${T("Transfer token")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— to move an existing node here")}</span></label>
      <div class="cmdrow"><div class="tokenbox">${transferToken(host, token)}</div>
        <button class="copyaction" onClick=${() => copy(transferToken(host, token), T("Copied"))}><${Ic} i="copy"/> ${T("Copy")}</button></div>
      <div class="hint">${T("Carries this panel's address and this token together. On the panel that has the node now: its Transfer window, and paste this — nothing is installed.")}</div></div>`}
    ${rotate && !nixos ? null
      : nixos ? html`<${Fragment}>
          <div class="rltabs" style="margin:18px 0 14px;gap:0">${armSwitch}</div>
          ${nixTab}
        <//>`
      : bothWays ? html`<${Fragment}>
          ${copyBlock(runLabel(kind === "docker" ? "#c084e8" : "#60a5fa", kindLabel(kind || "baremetal")),
                      kind === "docker" ? docker : bare, false)}
          ${copyBlock(runLabel(kind === "docker" ? "#60a5fa" : "#c084e8", kindLabel(kind === "docker" ? "baremetal" : "docker")),
                      kind === "docker" ? bare : docker, false)}
          <div class="hint">${T("Either works: the first is what this node runs today, and the panel follows whichever the new box reports.")}</div>
        <//>`
      : (kind === "docker" || kind === "baremetal") ? copyBlock(runLabel(kind === "docker" ? "#c084e8" : "#60a5fa", kindLabel(kind)), kind === "docker" ? docker : bare, false)
      : html`<${Fragment}>
          <div class="rltabs" role="tablist" style="margin-top:18px;gap:0">
            <div class="rltab-group" style="margin-left:0">
              <button role="tab" aria-selected=${tab === "std"} class=${"rltab" + (tab === "std" ? " on" : "")} onClick=${() => setTab("std")}>${T("Standard")}</button>
              <button role="tab" aria-selected=${tab === "nix"} class=${"rltab" + (tab === "nix" ? " on" : "")} onClick=${() => setTab("nix")}>${T("Declarative (NixOS)")}</button>
            </div>
            ${tab === "nix" ? armSwitch : null}
          </div>
          ${tab === "std" ? standardTab : nixTab}
        <//>`}
    ${fixBlock}
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
  const [meshEgress, setMeshEgress] = useState(node.mesh_egress_ip || "");
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
      patch: s => { const n = s.nodes.find(x => x.id === node.id); if (n) { n.name = name.trim(); n.color = color; n.endpoint_host = ingress; n.mesh_port = ovPort; n.mesh_subnet = ovSub; n.mesh_prefix = ovPfx; n.default_egress_ip = defEgress; n.panel_ip = panelIp; n.mesh_egress_ip = meshEgress; } },
      call: () => api.nodeUpdate({ id: node.id, name: name.trim(), color, endpoint_host: ingress, mesh_port: ovPort,
        mesh_egress_ip: meshEgress, mesh_subnet: ovSub, mesh_prefix: ovPfx, default_egress_ip: defEgress, panel_ip: panelIp }),
    });
  };
  const save = async () => {
    if (!name.trim() || !V.nodeName(name)) return setMsg({ k: "err", t: T("Name: 1–40 chars, letters/digits/-/_ only.") });
    if (reprovChanged) {   // re-provisioning bounces this node's mesh links → confirm first
      return pushModal(html`<${ConfirmSheet} title=${T("Re-provision this node's mesh links?")} confirmLabel=${T("Re-provision")} warn=${true}
        body=${T("Changing the mesh subnet / port / prefix of {v1} rebuilds all of its node-to-node links with the new settings.", { v1: node.name }) + " " + T("{v1} will briefly drop off the mesh (and any cascade/smart traffic routed through it pauses) until every peer pulls the new config and reconnects — usually a few seconds. Other nodes' links to each other are unaffected.", { v1: node.name })}
        onConfirm=${doSave}/>`);
    }
    doSave();
  };
  const [showAwg, setShowAwg] = useState(false);
  return html`<${Sheet} title=${T("Node settings · {v1}", { v1: node.name })}
    foot=${footRow({ left: html`<${Fragment}>
        <button class="btn btn-ghost" title=${T("Rotate this node's enrollment token (re-enroll / re-install)")} onClick=${() => openNodeRotate(node)}><${Ic} i="key"/> ${T("Rotate key")}</button>
        ${/* §3.1: the door for a node that IS reporting — the old box is alive, so this one supersedes it
              and keeps a rollback point. The other door ("Restore or migrate") lives on the details header
              and only appears when the node is silent. T-10's Transfer lands next to this one. */
          node.status === "online" ? html`<${Fragment}>
          <button class="btn btn-ghost" title=${T("Move this node to another server — the panel gives you a command that rebuilds it there from what it holds")} onClick=${() => openNodeMigrate(node)}><${Ic} i="server"/> ${T("Migrate")}</button>
          <button class="btn btn-ghost" title=${T("Hand this node to another panel — the box keeps running exactly as it is and starts syncing there instead")} onClick=${() => (node.transfer ? openNodeTransferWatch(node) : openNodeTransfer(node))}><${Ic} i="link"/> ${T("Transfer")}</button>
          <//>` : null}
      <//>`, onCancel: closeModal, onAction: save, action: T("Save") })}>
    <div class="field"><label>${T("Name")}</label>
      <div class="namerow"><input autofocus class=${nameBad ? "bad" : ""} value=${name} onInput=${e => setName(e.target.value)} autocomplete="off"/>
        <${ThemedSwatch} val=${color} title=${T("Node colour")} onChange=${setColor} sample=${(c) => html`<span class="tg" style=${"background:color-mix(in srgb," + c + " 16%,transparent);color:" + c}>${name.trim() || node.name || "node"}</span>`}/></div>
      <div class=${"hint" + (nameBad ? " err" : "")}>${nameBad ? T("1–40 chars: letters, digits, - or _ only.") : T("A label for this node — rename anytime, nothing else changes. The swatches set its colour per theme.")}</div></div>
    <div class="seclabel">${T("Egress")}</div>
    <div class="field"><label>${T("Default egress IP")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— direct internet exit")}</span></label>
      <${NodeIpPick} ips=${ips} value=${defEgress} onChange=${setDefEgress} auto=${T("Auto (MASQUERADE)")}/>
      <div class="hint">${T("The fallback source IP this node SNATs to when traffic exits to the internet here — applied to any interface (and traffic received from other nodes) that doesn't set its own egress IP. Interfaces with their own egress IP, and cascading traffic that exits elsewhere, are unaffected.")}</div></div>
    <div class="field"><label>${T("Panel egress connection IP")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— source to reach the panel")}</span></label>
      <${NodeIpPick} ips=${ips} value=${panelIp} onChange=${setPanelIp} auto=${T("Auto (default route)")}/>
      <div class="hint">${T("Source IP this node uses to reach the panel. Ignored on same-server installs; falls back to auto if it can't connect.")}</div></div>
    ${/* The third outbound role, beside the other two rather than under Mesh: an operator asking "which of
          this box's addresses does it go OUT from?" wants all three answers in one place. It is a node-level
          DEFAULT because the per-connection override cannot be one — re-provisioning wipes `links` wholesale
          and rebuilds them without it, so a value set on a single card is dropped by the next migration. */ null}
    <div class="field"><label>${T("Mesh egress IP")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— source to dial other nodes")}</span></label>
      <${NodeIpPick} ips=${ips} value=${meshEgress} onChange=${setMeshEgress} auto=${T("Auto (default route)")}/>
      <div class="hint">${T("Which of this node's addresses it dials the other nodes' mesh links from. A single connection can still override it on its own card.")}</div></div>
    <div class="hint" style="margin-top:14px">${meshElsewhere()}</div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}
/* ── Restore / migrate: one verb, two doors ──────────────────────────────────────────────────────────
   The DOOR is the answer to the one question nobody can answer for the operator — "is the old box still
   alive?" — so neither sheet asks it (plan §3.1):

     reporting      -> "Migrate", from the node's settings. The old box keeps running and is marked
                       superseded, which is what makes the one-click rollback possible.
     not reporting  -> "Restore or migrate", from the details header. No marker: there may be nothing
                       out there to supersede, and the sheet says so rather than implying a way back.

   Both emit the same thing — a rotated token and a paste-on-the-server command that pulls whatever the
   panel holds. "or migrate" is load-bearing: not reporting is not the same as gone for good.

   NOT api.nodeRotate. That rotates a token and nothing else — no baseline, no armed interface restores,
   no turn capture, no rollback point. §3.1 called this "already mostly built" back when rotation was all
   there was; the rebuild adapter is what makes the command mean "be this node again". */
async function armRebuild(node) {
  const r = await api.nodeRebuild({ node: node.id });
  if (!r.ok) { toast(srvText(r) || T("couldn't prepare the command"), "err"); return; }
  await Store.poll();               // the node row picks up its superseded badge before the sheet swaps
  openModal(html`<${NodeTokenSheet} name=${node.name} token=${r.data.token} isNew=${false}
    kind=${node.kind} platform=${node.platform} endpoint=${node.endpoint_host} rebuild=${r.data}/>`);
}
/* T-11 — the PRE-FLIGHT. Both doors ask the panel what this rebuild WOULD do and show it while the
   operator can still walk away. T-9 shipped these lists but could only show them AFTER the token had
   rotated, which is a report about a decision that can no longer be taken: `nixos/wdtt2` is a live example
   — a WDTT server whose identity cannot be unsealed, worth knowing BEFORE the box is wiped, not after.

   The answer comes from `rebuild_plan` on the server, the same call the arming applies, so the preview and
   the act cannot disagree. A pre-flight that FAILS never blocks the rebuild: the box may be broken, which
   is exactly when this is needed most, so it degrades to a note and the button still works. */
function useRebuildPreflight(node) {
  const [pf, setPf] = useState(undefined);          // undefined = still asking · null = unavailable
  useEffect(() => {
    let live = true;
    api.nodeRebuildPreflight(node.id)
      .then(r => { if (live) setPf(r && r.ok ? r.data : null); })
      .catch(() => { if (live) setPf(null); });
    return () => { live = false; };
  }, [node.id]);
  return pf;
}
function PreflightBlock({ pf }) {
  if (pf === undefined) return html`<div class="hint">${T("Checking what this would do…")}</div>`;
  if (!pf) return html`<div class="notice warn"><${Ic} i="warn"/><span>${T("Couldn't check what this would do. The rebuild still works — it reports the same list once it runs.")}</span></div>`;
  return html`<${Fragment}>
    ${/* No heading of its own: RebuildOutcome now brings its own two, and "What this will do" stacked
          straight on top of "What the panel can't bring back" was two headings saying one thing.
          §4's limit — that this predicts the PANEL's half and nothing has been asked of the box — used to
          be a sentence here. It was meta-commentary an operator has to decode, and the block headings now
          carry it concretely: "What the panel can't bring back" IS the limit, said about actual names. */''}
    <${RebuildOutcome} d=${pf} preview=${true}/>
  <//>`;
}
export function openNodeRecover(node) { openModal(html`<${NodeRecoverSheet} node=${node}/>`); }
export function NodeRecoverSheet({ node }) {
  const [busy, setBusy] = useState(false);
  const pf = useRebuildPreflight(node);
  const go = async () => { if (busy) return; setBusy(true); try { await armRebuild(node); } finally { setBusy(false); } };
  return html`<${Sheet} title=${T("Restore or migrate · {v1}", { v1: node.name })}
    foot=${footRow({ onCancel: closeModal, onAction: go, disabled: busy, action: busy ? T("Preparing…") : T("Prepare the command") })}>
    <div class="notice"><${Ic} i="info"/><span>${restoreOrMigrateIntro(node.name)}</span></div>
    <div class="notice warn"><${Ic} i="warn"/><span>${T("The node's current token stops working immediately — so if the box is only briefly unreachable rather than broken, wait for it instead. The command below is then the only way it gets back in.")}</span></div>
    <${PreflightBlock} pf=${pf}/>
  <//>`;
}
export function openNodeMigrate(node) { openModal(html`<${NodeMigrateSheet} node=${node}/>`); }
export function NodeMigrateSheet({ node }) {
  const [busy, setBusy] = useState(false);
  const pf = useRebuildPreflight(node);
  const go = async () => { if (busy) return; setBusy(true); try { await armRebuild(node); } finally { setBusy(false); } };
  return html`<${Sheet} title=${T("Migrate · {v1}", { v1: node.name })}
    foot=${footRow({ onCancel: closeModal, onAction: go, disabled: busy, action: busy ? T("Preparing…") : T("Prepare the migration") })}>
    <div class="notice"><${Ic} i="info"/><span>${migrateIntro(node.name)}</span></div>
    <div class="notice warn"><${Ic} i="warn"/><span>${T("This node is reporting, so the box it runs on now is left alone: it keeps running, keeps its peers connected, and only stops syncing with this panel. You can roll back to it in one click until you tell the panel it's gone.")}</span></div>
    <${PreflightBlock} pf=${pf}/>
    <div class="hint">${T("Nothing is destroyed and nothing is sent to either box — the panel can only hand you a command to run. Prepare it, then run it on the new server.")}</div>
  <//>`;
}

/* ── T-10 · Transfer: hand this node to ANOTHER panel ────────────────────────────────────────────
   The other half of §3's pair, and the opposite operation to Migrate in every way that matters:
   Migrate moves a node to a new BOX and the panel under it never changes; Transfer moves the PANEL
   and the box never changes. Nothing is installed, no address moves, and the only thing that happens
   on the node is that it starts dialling somewhere else.

   The operator pastes the TRANSFER TOKEN the other panel shows under Add node — one value carrying that
   panel's address and a node key valid there. It used to ask for the whole enrolment command, which is a
   carrier for those same two values and a confusing one: for a declarative (NixOS) node the command has
   no `-key` in it at all, so there was nothing to copy, and with two commands offered there was no way to
   know which kind was even wanted. Nothing is installed by a transfer, so the kind never mattered. A
   pasted command is still accepted, for anyone who already has one.

   This panel reaches that address, pushes everything the node needs, and then offers it to the node as a
   CANDIDATE. The node keeps syncing HERE until the far panel answers it, so
   a wrong or unreachable target costs a wait rather than a server. */
export function TransferOutcome({ d, preview }) {
  if (!d) return null;
  const strip = d.strip || [], split = d.split || [], un = d.unrestorable || d.unrecorded || [];
  const vkfb = d.vk_fallback || [], fam = d.turn_family || [], ifaces = d.ifaces || [];
  const users = d.users || [], subs = d.sub_links || [], esc = d.escrow || [];
  const names = xs => xs.map(x => (typeof x === "string" ? x : (x.iface || x.title || x.peer))).join(", ");
  /* A row is label-left / value-right, which is right for "5 configs" and wrong for a sentence: the
     sentence wraps to two lines while one name sits alone in the right-hand column. Such a row STACKS —
     the sentence on its own line, what it applies to underneath — by passing a third element. */
  const row = (label, value, stack) => html`<div class=${"ifrow" + (stack ? " ifrow-stack" : "")}><span class="l">${label}</span><span class="r">${value}</span></div>`;

  /* WHAT STAYS BEHIND. Every row is something no field list would have caught, which is why each is
     named rather than summarised: an escrow sealed to THIS panel's vault, a user whose peers straddle
     two panels, an interface this panel never recorded, a call link that is the operator's and not the
     node's. None of them stops a client connecting; all of them are things an operator has to know
     BEFORE the roster is on someone else's panel. */
  const lost = [
    split.length ? [T("These users have peers on other nodes here too — only this node moves, so those peers stay"),
                    [...new Set(split.map(x => x.user_name || x.user))].join(", "), "stack"] : null,

    vkfb.length ? [T("Peers on the panel-wide call link — the other panel resolves its own"), names(vkfb)] : null,
    un.length ? [T("Never set up through this panel — nothing to hand over"), names(un)] : null,
    subs.length ? [T("Subscription links keep this panel's address in them"), plural(subs.length, "sub link")] : null,
    d.declarative ? [T("Managed by its own configuration — it will point itself back"),
                     T("update panelUrl and the token file there too")] : null,
  ].filter(Boolean);

  const kept = [
    ifaces.length ? [T("Interfaces, with their keys and settings"), ifaces.join(", ")] : null,
    fam.length ? [T("WDTT / csqtt servers, with their configuration"), names(fam)] : null,
    users.length ? [T("Users, and every peer deployed here"),
                    plural(users.length, "user") + " · " + plural(d.peers || 0, "peer")] : null,
    d.blobs ? [T("Stored configs — the links your users already hold keep opening them"),
               plural(d.blobs, "config")] : null,
    esc.length ? [T("Users' encryption keys — re-wrapped there the next time you unlock the vault"),
                  plural(esc.length, "user")] : null,
    d.mesh_links ? [T("Mesh links — the other panel builds its own"), plural(d.mesh_links, "link")] : null,
    /* ⚠️ ESCROW BELONGS HERE, not in the red box it used to sit in. The ciphertext genuinely cannot
       travel — a blob is sealed to THIS panel's vault, so the far panel would hold something openable by
       nobody, which is why transfer_strip clears it. But the ESCROW is not lost with it: the identity
       (`public_key`) does travel, the box is not touched and still holds its own key backups, so the far
       panel asks for a sealed copy on its first syncs and the node seals one to ITS vault. Listing that
       under "what stays with this panel — only you can put right there" described a repair the operator
       neither has to make nor can make, next to a genuine one (a split user), which is what made a
       healthy transfer read as damage. */
    strip.length ? [T("Escrowed server keys — re-sealed to the other panel's vault, not carried"),
                    names(strip)] : null,
  ].filter(Boolean);

  const box = (cls, icon, heading, rows, tail) => html`<div class=${"notice " + cls}>
    <${Ic} i=${icon}/>
    <div style="flex:1;min-width:0">
      <b>${heading}</b>
      <div class="ifcard-rows" style="margin-top:7px">${rows.map(([l, v, st]) => row(l, v, st))}</div>
      <div style="margin-top:8px">${tail}</div>
    </div>
  </div>`;
  return html`<${Fragment}>
    ${/* Always the WARN tone. This box used to turn red exactly when it held a split user — the mildest
          row in it, and a consequence of transferring one node out of several rather than a fault. These
          are things to be aware of before the roster is on someone else's panel, not damage. */ null}
    ${lost.length ? box("warn", "warn", T("Worth knowing before you do this"), lost,
        T("Nothing here disconnects anybody — every peer keeps working. It is what the other panel will not know about, so you know where to look afterwards.")) : null}
    ${kept.length ? box("ok", "check", T("What moves to the other panel"), kept,
        T("The node keeps running throughout — it is not reinstalled, its addresses don't change, and nothing your users hold has to be re-sent.")) : null}
  <//>`;
}

export function openNodeTransfer(node) { openModal(html`<${NodeTransferSheet} node=${node}/>`); }
const TOKEN_PREFIX_HINT = "swgx1_…";   // i18n-keys: the literal prefix every transfer token starts with
export function NodeTransferSheet({ node }) {
  const [paste, setPaste] = useState("");
  const [pf, setPf] = useState(null);          // the checked target + what would move
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState("");

  /* TWO STEPS, deliberately. The paste is an address this panel has never spoken to, so "check" is a
     real action with a real answer — it reaches the target, proves the token works there, and reports
     what would move — and only then is there anything to confirm. Checking writes nothing. */
  const check = async () => {
    if (busy) return;
    setBusy("check"); setMsg(null);
    const r = await api.nodeTransferPreflight({ node: node.id, paste });
    setBusy("");
    if (!r.ok) { setPf(null); return setMsg({ k: "err", t: srvText(r) || T("couldn't reach that panel") }); }
    setPf(r.data);
  };
  const go = async () => {
    if (busy || !pf) return;
    setBusy("go"); setMsg(null);
    const r = await api.nodeTransfer({ node: node.id, paste });
    setBusy("");
    if (!r.ok) return setMsg({ k: "err", t: srvText(r) || T("the transfer didn't start") });
    await Store.poll();
    openModal(html`<${NodeTransferWatch} node=${node}/>`);
  };

  const tgt = (pf || {}).target || {};
  return html`<${Sheet} title=${T("Transfer · {v1}", { v1: node.name })}
    foot=${footRow({ onCancel: closeModal, disabled: !!busy || (pf && !paste.trim()),
      onAction: pf ? go : check,
      action: busy === "check" ? T("Checking…") : busy === "go" ? T("Transferring…")
              : pf ? T("Transfer to {v1}", { v1: tgt.name || tgt.url }) : T("Check the other panel") })}>
    <div class="notice"><${Ic} i="info"/><span>${transferIntro(node.name)}</span></div>
    ${/* ONLY WHILE IT IS STILL BEING ASKED. Once the pre-flight has run, the token has served its whole
          purpose — the panel it names has been reached and answered, and the box below says so by name.
          Leaving the field up made the confirm step re-present its own input, above three boxes that had
          already moved past it. Editing it resets the pre-flight (that is what onInput does), so the way
          back is to change it — which the link below the result offers explicitly. */ null}
    ${!pf ? html`<div class="field"><label>${T("The other panel's transfer token")}</label>
      <textarea class="ta" rows="3" spellcheck="false" autocomplete="off" value=${paste}
        placeholder=${TOKEN_PREFIX_HINT}
        onInput=${e => { setPaste(e.target.value); setPf(null); setMsg(null); }}></textarea>
      <div class="hint">${T("On the other panel: Nodes → Add node, then copy its Transfer token — it carries that panel's address and the new node's key together. An enrolment command still works if you have one; nothing is ever run.")}</div></div>` : null}
    ${pf ? html`<${Fragment}>
      ${/* THREE postures, not two. The first version said "self-signed" for anything not CA-verified, which
            over a plain-HTTP address is simply false — there is no certificate at all there, and the one
            thing an operator must be told is that the token and every config cross in the clear. Found by
            pasting an http:// address at it. */''}
      ${(() => {
        const plain = /^http:\/\//i.test(tgt.url || "");
        const cls = plain ? "danger" : tgt.verified ? "ok" : "warn";
        const icon = plain ? "warn" : tgt.verified ? "check" : "shield";
        const text = plain
          ? T("Reached {v1} — over plain HTTP. Everything in this transfer, the other panel's token included, crosses unencrypted, and the node will dial it the same way.", { v1: tgt.url })
          : tgt.verified
          ? T("Reached {v1} — its certificate is publicly trusted, and the node will check the same thing before it moves.", { v1: tgt.url })
          : T("Reached {v1}. Its certificate is self-signed, so the node will accept it only if it presents the exact certificate this panel just saw.", { v1: tgt.url });
        return html`<div class=${"notice " + cls}><${Ic} i=${icon}/><span>${text}</span></div>`;
      })()}
      <${TransferOutcome} d=${pf} preview=${true}/>
      <button class="btn btn-ghost btn-mini" style="margin-top:10px"
        onClick=${() => { setPf(null); setMsg(null); }}>${T("Use a different token")}</button>
    <//>` : null}
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

/* The wait, and it is a real one. The node learns the new address on its next sync, verifies it, and
   only then moves; until it does, this panel is still its panel and nothing has been lost. So the
   question this screen answers is the one G1 asks — "is it Reporting on the target panel?" — and it
   answers it by ASKING that panel, not by noticing our own silence, which cannot tell a node that moved
   from a node that died. */
export function openNodeTransferWatch(node) { openModal(html`<${NodeTransferWatch} node=${node}/>`); }
export function NodeTransferWatch({ node }) {
  const [st, setSt] = useState(undefined);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true, timer = 0;
    const tick = async () => {
      const r = await api.nodeTransferStatus(node.id);
      if (!live) return;
      setSt(r && r.ok ? r.data : null);
      if (!(r && r.ok && r.data && r.data.state === "done")) timer = setTimeout(tick, 4000);
      else Store.poll();
    };
    tick();
    return () => { live = false; clearTimeout(timer); };
  }, [node.id]);
  const done = (st || {}).state === "done";
  const drop = async () => {
    if (busy) return;
    setBusy(true);
    const r = await api.nodeTransferCancel({ node: node.id });
    setBusy(false);
    if (!r.ok) { toast(srvText(r) || T("couldn't cancel"), "err"); return; }
    await Store.poll();
    toast(done ? T("Cleared.") : T("Transfer withdrawn — the node stays on this panel."), "ok");
    closeModal();
  };
  return html`<${Sheet} title=${T("Transfer · {v1}", { v1: node.name })}
    foot=${footRow({ left: html`<button class="btn btn-ghost" disabled=${busy} onClick=${drop}>
        ${done ? T("Clear this") : T("Withdraw the transfer")}</button>`,
      onCancel: closeModal, cancelLabel: T("Close") })}>
    ${done
      ? html`<div class="notice ok"><${Ic} i="check"/><span>${T("{v1} is now reporting on {v2}. This panel has discarded the token it was given, and this node's record here is yours to keep or remove.", { v1: node.name, v2: (st || {}).url || T("the other panel") })}</span></div>`
      : html`<${Fragment}>
        <div class="notice"><${Ic} i="clock"/><span>${T("Waiting for {v1} to appear on {v2}. It learns the new address on its next sync, checks that panel's identity, and only then moves — so until it does, it is still fully yours.", { v1: node.name, v2: (st || {}).url || T("the other panel") })}</span></div>
        ${st && st.reachable === false ? html`<div class="notice warn"><${Ic} i="warn"/><span>${T("The other panel isn't answering this panel right now ({v1}). The node will keep trying; nothing is lost while it can't get through.", { v1: st.error || "" })}</span></div>` : null}
      <//>`}
    <div class="hint">${T("Withdrawing takes the address back. The node never left, so there is nothing to roll back — it simply stops being offered somewhere else.")}</div>
  <//>`;
}

/* The other end of the migration: the old box is still out there, and both of the operator's decisions
   about it are one click. Rolling back puts its own unmodified token back — it needs no shell on either
   box. Discarding forgets the credential, so the badge stops claiming a box that no longer exists;
   removing the old box was never the panel's call to make (G14). */
export function openNodeRollback(node) { openModal(html`<${NodeRollbackSheet} node=${node}/>`); }
export function NodeRollbackSheet({ node }) {
  const [busy, setBusy] = useState("");
  const at = (node.superseded_box || {}).at;
  const run = async (discard) => {
    if (busy) return;
    setBusy(discard ? "forget" : "back");
    const r = await api.nodeRebuildRollback(discard ? { node: node.id, discard: true } : { node: node.id });
    if (!r.ok) { toast(srvText(r) || T("couldn't roll back"), "err"); setBusy(""); return; }
    await Store.poll();
    toast(discard ? T("Old box forgotten.") : T("Rolled back — the old box resumes on its next sync."), "ok");
    closeModal();
  };
  return html`<${Sheet} title=${T("The old box · {v1}", { v1: node.name })}
    foot=${footRow({
      left: html`<button class="btn btn-ghost" disabled=${!!busy} title=${T("Forget the old box's token — the badge goes away and this panel keeps the new box")} onClick=${() => run(true)}>${busy === "forget" ? T("Working…") : T("It's gone — forget it")}</button>`,
      onCancel: closeModal, disabled: !!busy, onAction: () => run(false),
      action: busy === "back" ? T("Working…") : T("Roll back to it") })}>
    <div class="notice"><${Ic} i="info"/><span>${oldBoxLive(node.name, at ? T("{ago} ago", { ago: seen(Math.floor(Date.now() / 1000 - at)) }) : T("recently"))}</span></div>
    <div class="notice warn"><${Ic} i="warn"/><span>${T("Rolling back hands this panel back to the old box: its own token starts working again and it picks up on its next sync, peers and all. Whatever you installed on the new box stops syncing instead — nothing on it is touched, and you can migrate again whenever you like.")}</span></div>
    <div class="hint">${T("If the migration went fine and the old server is decommissioned, forget it instead — that only drops the panel's copy of its old token.")}</div>
  <//>`;
}
export function openNodeRotate(node) { openModal(html`<${NodeRotateSheet} node=${node}/>`); }
export function NodeRotateSheet({ node }) {
  const go2 = async () => { const r = await api.nodeRotate({ id: node.id }); if (!r.ok) { toast(srvText(r) || T("rotate failed"), "err"); return; } openModal(html`<${NodeTokenSheet} name=${node.name} token=${r.data.token} isNew=${false} kind=${node.kind} platform=${node.platform} endpoint=${node.endpoint_host}/>`); };
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
  // A declaratively-managed node cannot be uninstalled by `bootstrap.sh uninstall` — that command
  // REFUSES on such a host (it would write into /opt the configuration cannot see). And removing the
  // module does NOT tell the panel (nothing calls /api/node/goodbye), so the node does not sign off
  // on its own — it lingers until Force-removed here. Both facts change the instructions below.
  const declarative = !!node.declarative;
  const nixos = node.platform === "nixos";
  const uninstall = declarative
    ? (nixos ? "services.swg-node.enable = false;   # then: sudo nixos-rebuild switch" : "")   // i18n-keys: generated Nix — file text, copied verbatim
    : `curl -fsSL ${BOOTSTRAP_URL} | sudo bash -s uninstall`;
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
      : html`<div class="notice"><${Ic} i="info"/><span>${declarative
          ? T("This node is managed declaratively. Remove it from the configuration that declares it and rebuild — it won't sign off on its own, so Force-remove it here afterwards. It keeps serving its {v1} until then.", { v1: plural(here.length, "peer") })
          : T("Clean removal: flag the node, then run the uninstall command on the server. The node keeps serving its {v1} until it confirms, then drops itself from the panel.", { v1: plural(here.length, "peer") })} ${note}</span></div>`}
    ${uninstall ? html`<div class="field" style="margin-top:14px"><label>${declarative ? T("Set in the node's configuration, then rebuild") : T("Run on the node to uninstall + sign off")}</label>
      <div class="cmdrow"><div class=${"tokenbox" + (declarative ? " block" : "")}>${uninstall}</div><button class="copyaction" onClick=${() => copy(uninstall, T("Copied"))}><${Ic} i="copy"/> ${T("Copy")}</button></div>
      <div class="hint">${declarative ? T("Removing the module stops swg-noded / swg-agent but does not tell the panel — Force remove clears it here.") : T("Removes swg-noded / swg-agent and tells the panel it's gone. Force remove is for when the server is unreachable.")}</div></div>` : null}
  <//>`;
}
