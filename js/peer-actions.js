/* peer-actions.js — the destructive and lifecycle actions on a peer or a user.
 *
 * LAYER 3 (see docs/APP-JS-SPLIT-PLAN.md). Imports util / store / model / ui / crypto / views.
 *
 * Every irreversible thing an operator can do to a peer lives here behind a confirm: rotate keys, delete,
 * unassign, block and unblock, set an expiry, restore a missing deployment, correct an out-of-subnet IP,
 * and the two-phase ghost recreate (recreate the interface, then rekey the peers that were on it once it
 * reports back live). Grouping them is what stops each screen growing its own variant of "are you sure".
 *
 * Screens call these; this module never calls a screen. The one exception is the ghost recreate, which has
 * to raise the Load-interface sheet — that sheet belongs to the interface layer above, so it arrives as an
 * injected opener rather than an import.
 */

import { T, Tsplit, plural } from "./i18n.js";
import { tkey, seen, isPrimaryTarget } from "./util.js";
import { Store, api, useStore } from "./store.js";
import { targetType, iTypeOf, ghostIface, ghostPeers } from "./model.js";
import { searchMatch, revealAssignedPeer } from "./views.js";
import { Ic, toast, mutate, openModal, pushModal, openConfirm, closeModal, closeAllModals, Tag,
         Portal, useAnchoredList } from "./ui.js";
import {
  SubAutoNote, useSubRec, subFeatureOn, ensureVaultUnlocked, subPublishOrPrompt, genKeys, genPSK,
  buildConf, parseFullConf, getConfig, subSKCached, ivkResealForNode, subReconcileUser,
} from "./crypto.js";
import { h, Fragment } from "preact";
import { useState, useEffect } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// The ghost recreate needs the Load-interface sheet, which lives a layer up (js/iface.js when it lands).
// app.js wires this at boot; until then the action simply does nothing rather than importing upward.
let _openLoadIface = () => {};
export const setLoadIfaceOpener = fn => { _openLoadIface = fn; };

// Rotate a peer's keypair while KEEPING its PSK (PSK is user-owned — rotated only from the user
// module). Mints a new keypair in the browser, preserves each target's current config settings
// (DNS/MTU/AllowedIPs/keepalive) where readable, and re-issues. The old config stops working,
// so the client must re-import the fresh QR/config. Only meaningful for an assigned peer.
export async function rotatePeerKeys(peer) {
  const key = "peer:" + peer.id;
  Store.rotating[peer.id] = Date.now();   // grid shows "rotating" until the new key is live
  let keys, psk, configs;
  try {
    keys = await genKeys(); psk = genPSK(); configs = {};   // rotate BOTH the keypair and the PSK
    for (const t of peer.targets) {
      const m = Store.ifaceMeta(t.node, t.iface);
      if (!m) { delete Store.rotating[peer.id]; Store.rowErrors[key] = { msg: T("{v1} hasn't reported {v2} yet", { v1: Store.nodeName(t.node), v2: t.iface }), at: Date.now(), node: t.node, iface: t.iface }; Store.apply(); return; }
      const cur = await getConfig(peer.pubkey, t.node, t.iface);
      const s = cur ? parseFullConf(cur) : null;
      configs[tkey(t.node, t.iface)] = buildConf({ privkey: keys.priv, address: (t.ip || "").split("/")[0] + "/32",
        dns: s ? s.dns : m.dns, mtu: s ? s.mtu : 1280, awg_params: m.awg_params, server_pubkey: m.public_key,
        psk, endpoint: m.endpoint, allowed: s ? s.allowed : "0.0.0.0/0, ::/0", keepalive: s ? s.keepalive : 25 });
    }
  } catch (e) { delete Store.rotating[peer.id]; Store.rowErrors[key] = { msg: String(e.message || e), at: Date.now() }; Store.apply(); return; }
  await mutate({
    key,
    call: () => api.peerRekey({ peer_id: peer.id, user_id: peer.user_id, pubkey: keys.pub, psk }),   // no plaintext to the server
    onOk: () => { delete Store.sessionConfigs[peer.pubkey]; Store.sessionConfigs[keys.pub] = configs; Store.configEpoch++;
      subPublishOrPrompt(peer.user_id, peer.id, keys.priv, psk); },
  });
}

// Rotate EVERY key a user holds — each WG/AWG peer gets a fresh keypair + PSK (rotatePeerKeys), each WDTT peer a
// fresh WRAP password (wdttPeerRotate). All old configs/links die → every device must re-import. Confirmed once.
export function rotateAllUserKeys(user, after) {
  const peers = Store.peersOfUser(user.id);
  if (!peers.length) { toast(T("This user has no peers to rotate."), "err"); return; }
  // The count is bold and mid-sentence, so the sentence is translated whole and split on its own marker —
  // Russian puts the owner before the count, and two concatenated fragments could not express that.
  const [rotBefore, rotAfter] = Tsplit("Rotate the keys for all {what} of {name}. Every existing config, QR and link stops working — each device must re-import. This can't be undone.",
    "what", { name: user.name });
  openConfirm({ title: T("Rotate all keys · {name}", { name: user.name }), confirmLabel: T("Rotate all keys"), warn: true, back: after,
    body: html`${rotBefore}<b>${plural(peers.length, "peer")}</b>${rotAfter}`,
    onConfirm: () => {
      // Optimistic + non-blocking: flip EVERY peer to "Rotating" the instant you confirm, close the dialog at once,
      // and fire the rotations in parallel (was 19 sequential rekeys → "Working…" hung). Each card re-resolves the
      // live peer and re-renders its new QR as it flips rotating→ready.
      peers.forEach(p => { Store.rotating[p.id] = Date.now(); });
      Store.apply();
      (async () => {
        const oks = await Promise.all(peers.map(async p => {
          try {
            if (p.csqtt_password) { Store.rotating[p.id] = Date.now(); await api.csqttPeerRotate({ peer_id: p.id }); }  // keyless csqtt peer → new access password
            else if (p.wdtt_password) { Store.rotating[p.id] = Date.now(); await api.wdttPeerRotate({ peer_id: p.id }); }   // keyless WDTT peer → new WRAP password
            else await rotatePeerKeys(p);                                                                              // WG/AWG peer → new keypair + PSK
            return true;
          } catch (_) { return false; }
        }));
        const n = oks.filter(Boolean).length;
        await Store.poll();
        toast(T("Rotated keys for {count} — every device must re-import.", { count: plural(n, "peer") }), n ? "ok" : "err");
      })();
    } });
}

// Confirmed unassign — revokes the holder (PSK rotates) and is irreversible (keys change).
// `back` = where Cancel returns to (e.g. the peer view it was launched from).
export function confirmUnassign(peer, back) {
  openConfirm({ title: peer.name ? T("Unassign peer · {name}", { name: peer.name }) : T("Unassign peer"), confirmLabel: T("Unassign"), danger: true, back,
    body: T("This revokes access immediately and is irreversible — the keys change, so re-assigning later means sending the user a brand-new QR / config to import."),
    onConfirm: () => mutate({ key: "peer:" + peer.id,
      patch: s => { const p = s.roster.peers[peer.id]; if (p) p.user_id = null; },
      call: () => api.peerUnassign({ peer_id: peer.id }),
      onOk: () => { delete Store.sessionConfigs[peer.pubkey]; Store.configEpoch++; } }) });
}
// Confirmed delete (unassigned peers only). `back` = Cancel target.
export function confirmDeletePeer(peer, back) {
  openConfirm({ title: T("Delete peer"), confirmLabel: T("Delete"), danger: true, back,
    body: T("This is irreversible — the peer's key is removed from every interface it's deployed on."),
    // Close the WHOLE stack, not just the confirm. `back` returns you where you came from, which is right for
    // Cancel and wrong for a delete: the editor you opened this from is an editor for a peer that no longer
    // exists. Emptying the stack also makes ConfirmSheet.go() skip its own closeModal (it bumps _modalSeq).
    onConfirm: () => { closeAllModals();
      return mutate({ key: "peer:" + peer.id, patch: s => { delete s.roster.peers[peer.id]; },
        call: () => api.peerDelete({ peer_id: peer.id }) }); } });
}

// ── Restore a missing interface (dangling) · Correct an out-of-subnet IP (broken) ─────────────────
// Both affordances are GATED: reconcile only sets a deployment restorable/correctable once the problem has
// persisted past the ~2-minute grace (never a hiccup or a peer still being created), and every modal states
// how long it's been wrong so the operator doesn't act prematurely. Restore is per-INTERFACE — recreating a
// vanished interface recovers EVERY dangling peer on it at once — so pressing it on any dangling row (or the
// batch) recreates that node/iface. Correct is per-PEER — each broken peer's own record needs a valid address.
function _durText(ms) { const m = Math.max(1, Math.floor((ms || 0) / 60000)); return T("more than {count}", { count: plural(m, "minute") }); }
function _missingIface(node, iface) {
  const nr = (Store.nodes || []).find(n => n.id === node) || {};
  return (nr.missing_ifaces || {})[iface] || null;   // {subnet, listen_port, address, awg_params, public_key, key_source} | null
}
// Restore is an INTERFACE action (it recreates the whole interface, recovering EVERY dangling peer on it) —
// this shared confirm is opened both from a peer row/modal and from the node's interface list, so the copy
// stays consistent and always frames it as an interface, not a peer. `problemMs` drives the gate line; `mi` is
// the node's missing-interface record (null => the panel never captured a config, so it can't recreate).
function _openRestoreInterface({ node, iface, mi, problemMs, rowKey, back }) {
  if (ghostIface(node, iface)) return openRecreateRekey(node, iface, back);   // lost + keyless → can't restore, redirect to recreate + rekey
  const where = Store.nodeName(node) + " · " + iface;
  const gate = T("This isn't a brief hiccup or a peer still being created — the interface has stayed missing for {dur}.", { dur: _durText(problemMs) });
  const clean = !!(mi && mi.key_source);                 // "backup" | "vault" → original key recoverable
  const vault = !!(mi && mi.key_source === "vault");     // key gone from the node → recover from the operator vault (full wipe)
  const src = vault ? T("the operator vault") : T("the node's own backup");
  const lockedVault = vault && !subSKCached();
  const vars = { iface, node: Store.nodeName(node), src, gate };
  const body = !mi
    ? T("The panel has no saved configuration for interface {iface} on {node} yet, so it can't be recreated automatically. {gate}", vars)
    : clean
      ? T("Recreate the missing interface {iface} on {node} with its ORIGINAL server key (from {src}) and saved settings. This restores the INTERFACE, not a single peer — every peer that lives on {iface} re-converges over the next few syncs, and existing clients keep working (no new QR / config to distribute). {unlock}{gate}",
          { ...vars, unlock: lockedVault ? T("You'll be asked to unlock the vault first to release the escrowed key. ") : "" })
      : T("Recreate the missing interface {iface} on {node} with its saved settings. This restores the INTERFACE, not a single peer. The original server key can't be recovered, so the interface gets a NEW key — every client on {iface} must re-import a fresh QR / config. {gate}", vars);
  openConfirm({ title: T("Restore interface · {where}", { where }), confirmLabel: mi ? T("Restore interface") : T("Close"), danger: !!mi && !clean, back, body,
    note: (mi && clean) ? html`<${SubAutoNote}/>` : null,
    onConfirm: mi ? (async () => {
      let sealed = null;
      try { sealed = await ivkResealForNode(node, mi); }   // vault key → unseal + re-seal to the node (null for a backup/new-key restore)
      catch (e) { toast(T("Vault restore failed: {err}", { err: (e && e.message) || e }), "err", 5000); return; }
      await mutate({ key: rowKey, call: () => api.ifaceRecreate({ node, iface, ...(sealed ? { sealed_key: sealed } : {}) }),
        onOk: () => toast(T("Restoring interface {iface} on {node} — its peers re-converge over the next syncs.", { iface, node: Store.nodeName(node) }), "ok") });
    }) : null });
}
export function confirmRestoreDeployment(peer, t, back) {
  _openRestoreInterface({ node: t.node, iface: t.iface, mi: _missingIface(t.node, t.iface), problemMs: t.problemMs, rowKey: "peer:" + peer.id, back });
}
export function confirmRestoreInterface(node, iface, mi, back) {
  _openRestoreInterface({ node, iface, mi, problemMs: (mi && mi.problemMs) || 0, rowKey: "iface:" + node + "|" + iface, back });
}

// ── GHOST interface: lost + KEYLESS — recreate FRESH + rekey every peer ───────────────────────────────
// A ghost interface is gone from the node AND has no recoverable key/config, so Restore can't help (it would
// hit /api/iface/recreate, which 400s without a saved config). The only fix is to recreate it fresh — a NEW
// server key — and rekey every peer on it so their clients re-import. Two sources: a COLD ghost (server-
// reported `ghost_ifaces`, no saved config at all) or a WARM-but-keyless missing interface (a `missing_ifaces`
// entry whose key_source is '' — a config exists but no key to restore). Ripeness = the same ~2min grace as
function _subnet24(ip) { const m = String(ip || "").match(/^(\d+)\.(\d+)\.(\d+)\.\d+/); return m ? m[1] + "." + m[2] + "." + m[3] + ".0/24" : ""; }
// Open the recreate-and-rekey flow: the create form, pre-filled with parameters INFERRED from the ghost's
// peers (protocol from a target's type, subnet widened from a peer IP, endpoint from the node's own IP), all
// editable, with a warning that clients must re-import. On create it stages the peers for phase-2 auto-rekey.
export function openRecreateRekey(node, iface, back) {
  const g = ghostIface(node, iface) || {};
  const peers = ghostPeers(node, iface);
  let proto = "wg"; const ips = [];
  peers.forEach(p => (p.targets || []).forEach(t => { if (t.node === node && t.iface === iface) { if (t.type === "awg") proto = "awg"; if (t.ip) ips.push(t.ip); } }));
  const nr = (Store.nodes || []).find(n => n.id === node) || {};
  const pre = { iface, proto, subnet: g.subnet || _subnet24(ips[0]), endpoint: (nr.ips || [])[0] || "" };
  const rekeyable = peers.filter(p => p.user_id).map(p => p.id);   // only ASSIGNED peers can be rekeyed (rekey needs a holder)
  _openLoadIface({ node, pre, ghost: { node, iface, peers: rekeyable, total: peers.length }, back });
}

// Phase 2 of a ghost recreate: once the recreated interface reports back LIVE (with its brand-new server key),
// rekey every peer that was on it so their clients get fresh configs. Staged by openRecreateRekey; fired here
// on each poll. If the operator leaves before the interface returns, nothing is lost — the interface comes
// back and its peers surface as needing a rekey (stale client config → faulty), so it degrades gracefully.
export function maybeRekeyGhosts() {
  const staged = Store.ghostRekey || {};
  for (const gk of Object.keys(staged)) {
    const rec = staged[gk]; const bar = gk.indexOf("|"); const node = gk.slice(0, bar), iface = gk.slice(bar + 1);
    if (Date.now() - (rec.at || 0) > 900000) { delete staged[gk]; continue; }   // give up after 15min
    const m = Store.ifaceMeta(node, iface);
    if (!m || !m.public_key) continue;                                          // fresh interface not live yet → wait
    delete staged[gk];                                                          // clear BEFORE rekeying so we never double-fire
    // The panel just recreated this interface, so the node's brand-new server key isn't drift to review — adopt it
    // automatically instead of leaving it flagged MODIFIED (the panel initiated the change). Best-effort; the
    // manual Adopt/Restore on the interface sheet stays as a fallback.
    if (m.drift && m.drift.public_key) api.ifaceAdopt({ node, iface, key: "public_key" }).catch(() => {});
    const peers = (rec.peers || []).map(id => (Store.recon.peers || []).find(p => p.id === id)).filter(p => p && p.user_id);
    peers.forEach(p => { rotatePeerKeys(p).catch(() => {}); });
    if (peers.length) toast(T("Interface {iface} is back — rekeying {count}; hand out the fresh configs.", { iface, count: plural(peers.length, "peer") }), "ok", 5000);
  }
}
// Node-rebuild recovery (P5): after re-installing a wiped box (it re-enrolls empty), one press recreates ALL of
// its missing interfaces with their original identities — vault keys released with a single unlock, then each
// peer re-converges. Interfaces without a recoverable key get a fresh one (their clients re-import).
export function confirmRestoreAllInterfaces(nid, back) {
  const nr = (Store.nodes || []).find(n => n.id === nid) || {};
  const miss = Object.entries(nr.missing_ifaces || {}).filter(([, mi]) => mi && mi.ripe);
  if (!miss.length) { toast(T("No interfaces to restore yet — a missing interface must persist a couple of minutes first."), "info"); return; }
  const anyVault = miss.some(([, mi]) => mi.key_source === "vault");
  const newKey = miss.filter(([, mi]) => !mi.key_source).length;
  // "N have no recoverable key" needs subject-verb agreement English can only get from two sentences, so it
  // IS two keys picked by the count — plural() alone would produce "1 interface have".
  const newKeyNote = !newKey ? T(" Existing clients keep working — no re-distribution.")
    : newKey === 1 ? T(" One has no recoverable key, so it gets a new one and those clients must re-import.")
    : T(" {n} have no recoverable key, so they get a new one and those clients must re-import.", { n: newKey });
  openConfirm({ title: T("Restore {count} · {node}", { count: plural(miss.length, "interface"), node: Store.nodeName(nid) }),
    confirmLabel: T("Restore {n}", { n: miss.length }), danger: newKey > 0, back,
    body: T("Recreate {count} missing on {node} with their saved settings and, where recoverable, their ORIGINAL server keys — every peer re-converges.{vault}{newkey} This is the node-rebuild recovery: after re-installing the box, one press brings its interfaces back.",
      { count: plural(miss.length, "interface"), node: Store.nodeName(nid),
        vault: anyVault ? T(" You'll unlock the vault once to release the escrowed keys.") : "", newkey: newKeyNote }),
    note: html`<ul class="restore-list">${miss.map(([ifn, mi]) => html`<li>${ifn}${!mi.key_source ? html` <span class="rl-new">${T("new key")}</span>` : mi.key_source === "vault" ? html` <span class="faint">${T("(from vault)")}</span>` : null}</li>`)}</ul>`,
    onConfirm: async () => {
      let ok = 0, failed = 0;
      for (const [ifn, mi] of miss) {
        let sealed = null;
        try { sealed = await ivkResealForNode(nid, mi); }
        catch (e) { failed++; toast(T("{iface}: {err}", { iface: ifn, err: (e && e.message) || e }), "err", 5000); continue; }
        const r = await mutate({ key: "iface:" + nid + "|" + ifn, call: () => api.ifaceRecreate({ node: nid, iface: ifn, ...(sealed ? { sealed_key: sealed } : {}) }) });
        if (r && r.ok) ok++; else failed++;
      }
      toast(T("Restoring {count} on {node}{failed} — peers re-converge over the next syncs.",
        { count: plural(ok, "interface"), node: Store.nodeName(nid), failed: failed ? T(" ({n} failed)", { n: failed }) : "" }), failed ? "info" : "ok");
    } });
}

export function confirmCorrectDeployment(peer, t, back) {
  const who = peer.title || peer.name || T("kind|peer");
  const where = Store.nodeName(t.node) + " · " + t.iface;
  const gate = T("This isn't a transient state — the address has stayed out of range for {dur}.", { dur: _durText(t.problemMs) });
  openConfirm({ title: T("Fix {who} · {where}", { who, where }), confirmLabel: T("Fix address"), back,
    body: T("This peer's address {ip} is outside {iface}'s subnet on {node}, so the node can't add it. Fix reassigns the peer the LOWEST free address in {iface}'s subnet — the next one not already taken by another peer on that interface — then the node re-converges. If this peer runs on {iface} across several nodes, they all move to the one new address. Keys and PSK stay the same. {gate}",
      { ip: t.ip || "—", iface: t.iface, node: Store.nodeName(t.node), gate }),
    note: html`<${SubAutoNote}/>`,
    onConfirm: () => mutate({ key: "peer:" + peer.id, call: () => api.peerCorrect({ peer_id: peer.id, target: { node: t.node, iface: t.iface } }),
      onOk: r => toast(T("Address fixed{to}.", { to: (r && r.data && r.data.ip) ? " → " + r.data.ip : "" }), "ok") }) });
}

// Batch (grid button next to the status dropdown). `rows` = the currently-filtered {p, t} rows.
export function confirmRestoreAll(rows, back) {
  const seen = new Set(), targets = [];
  for (const { t } of rows) { if (!t.restorable) continue; const k = t.node + "|" + t.iface; if (seen.has(k)) continue; seen.add(k); targets.push(t); }
  if (!targets.length) { toast(T("Nothing to restore yet — a missing interface must persist a couple of minutes before it's offered."), "info"); return; }
  const dirty = targets.filter(t => { const mi = _missingIface(t.node, t.iface); return !mi || !mi.key_source; }).length;
  const n = targets.length, one = n === 1;
  const dirtyNote = !dirty ? T(" Existing clients keep working — no re-distribution.")
    : dirty === 1 ? T(" One has no recoverable key, so it gets a new one and those clients must re-import.")
    : T(" {n} have no recoverable key, so they get a new one and those clients must re-import.", { n: dirty });
  openConfirm({ title: T("Restore {count} missing", { count: plural(n, "interface") }), confirmLabel: T("Restore {n}", { n }), danger: dirty > 0, back,
    body: T("Recreate {count} missing with saved settings and, where recoverable, the ORIGINAL server key — every dangling peer on {them} re-converges.{dirty} Only interfaces missing long enough to be a real outage are included.",
      { count: plural(n, "interface"), them: one ? T("ref|it") : T("ref|them"), dirty: dirtyNote }),
    note: html`<ul class="restore-list">${targets.map(t => html`<li>${Store.nodeName(t.node)} · ${t.iface}${_missingIface(t.node, t.iface) && !_missingIface(t.node, t.iface).key_source ? html` <span class="rl-new">${T("new key")}</span>` : null}</li>`)}</ul>`,
    onConfirm: async () => { let ok = 0; for (const t of targets) { const r = await mutate({ call: () => api.ifaceRecreate({ node: t.node, iface: t.iface }) }); if (r && r.ok) ok++; } toast(T("Restoring {count} — peers re-converge over the next syncs.", { count: plural(ok, "interface") }), "ok"); } });
}
export function confirmCorrectAll(rows, back) {
  const seen = new Set(), items = [];
  for (const { p, t } of rows) { if (!t.correctable) continue; const k = p.id + "|" + t.iface; if (seen.has(k)) continue; seen.add(k); items.push({ p, t }); }
  if (!items.length) { toast(T("Nothing to fix yet — a broken address must persist a couple of minutes before it's offered."), "info"); return; }
  openConfirm({ title: T("Fix {count}", { count: plural(items.length, "broken address") }), confirmLabel: T("Fix {n}", { n: items.length }), back,
    body: T("Reassign each of these {count} the LOWEST free address in its interface's subnet (the next one not already taken on that interface), then let the nodes re-converge. Keys and PSK are unchanged. Only records wrong long enough to be a real mismatch are included.",
      { count: plural(items.length, "peer") }),
    note: html`<${Fragment}><ul class="restore-list">${items.map(({ p, t }) => html`<li>${p.title || p.name || T("kind|peer")} · ${Store.nodeName(t.node)} · ${t.iface} <span class="faint">(${t.ip || "—"})</span></li>`)}</ul><${SubAutoNote}/></>`,
    onConfirm: async () => { let ok = 0; for (const { p, t } of items) { const r = await mutate({ key: "peer:" + p.id, call: () => api.peerCorrect({ peer_id: p.id, target: { node: t.node, iface: t.iface } }) }); if (r && r.ok) ok++; } toast(T("Fixed {count}.", { count: plural(ok, "address") }), "ok"); } });
}

// ── Block / unblock access (declarative revoke — reversible, keys unchanged) ──────────────────────
// Blocking drops the peer (or every peer of a user) from each node's desired set: the node removes it and
// the live session tears down within a sync. The keys are untouched, so unblocking reconnects the SAME
// config/QR with no re-issue. A user block also suspends the subscription page (kept — the URL still shows
// "Subscription disabled" and re-enables instantly). `now_s` stamps the transient "restoring" marker.
export const now_s = () => Math.floor(Date.now() / 1000);
const _peerName = p => p.title ? " · " + p.title : p.name ? " · " + p.name : "";
export function confirmBlockPeer(peer, back) {
  openConfirm({ title: T("Block access") + _peerName(peer), confirmLabel: T("Block"), danger: true, back,
    body: T("This removes the peer from every server it's deployed on, cutting its connection within a sync. The keys are unchanged, so unblocking later restores the same config — no new QR needed."),
    onConfirm: () => mutate({ key: "peer:" + peer.id,
      patch: s => { const p = s.roster.peers[peer.id]; if (p) p.disabled = true; },
      call: () => api.peerBlock({ peer_id: peer.id }) }) });
}
export function confirmUnblockPeer(peer, back) {
  openConfirm({ title: T("Unblock access") + _peerName(peer), confirmLabel: T("Unblock"), back,
    body: T("This restores the peer on every server it's deployed on. It reconnects with its existing keys once the servers converge."),
    onConfirm: () => mutate({ key: "peer:" + peer.id,
      patch: s => { const p = s.roster.peers[peer.id]; if (p) { delete p.disabled; p.unblock_at = now_s(); } },
      call: () => api.peerUnblock({ peer_id: peer.id }) }) });
}
export function confirmBlockUser(user, back) {
  openConfirm({ title: T("Block access · {name}", { name: user.name || T("kind|user") }), confirmLabel: T("Block"), danger: true, back,
    body: T("This blocks every peer of this user and, if they have a subscription, disables its page — the link still resolves but shows “Subscription disabled”. Nothing is deleted: unblocking restores connectivity and the same subscription URL."),
    onConfirm: () => mutate({ key: "user:" + user.id,
      patch: s => { const u = s.roster.users[user.id]; if (u) u.disabled = true; },
      call: () => api.userBlock({ user_id: user.id }) }) });
}
export function confirmUnblockUser(user, back) {
  openConfirm({ title: T("Unblock access · {name}", { name: user.name || T("kind|user") }), confirmLabel: T("Unblock"), back,
    body: T("This restores every peer and re-enables the subscription page. Connections come back once the servers converge."),
    onConfirm: () => mutate({ key: "user:" + user.id,
      patch: s => { const u = s.roster.users[user.id]; if (u) { delete u.disabled; u.unblock_at = now_s(); } },
      call: () => api.userUnblock({ user_id: user.id }) }) });
}
// Ghost Block/Unblock button — label + action derive from state. A peer blocked only because its whole user is
// blocked can't be individually unblocked, so point the operator at the user instead of a dead per-peer toggle.
export function peerBlockBtn(peer, back) {
  if (peer.userDisabled && !peer.selfDisabled)
    return html`<button class="btn btn-danger" disabled title=${T("Blocked because the user is blocked — unblock the user")}><${Ic} i="off"/> ${T("status|Blocked")}</button>`;
  return peer.selfDisabled
    ? html`<button class="btn btn-ghost" onClick=${() => confirmUnblockPeer(peer, back)}><${Ic} i="refresh"/> ${T("Unblock")}</button>`
    : html`<button class="btn btn-danger" onClick=${() => confirmBlockPeer(peer, back)}><${Ic} i="off"/> ${T("Block")}</button>`;
}
export function userBlockBtn(user, back) {
  return user.disabled
    ? html`<button class="btn btn-ok" onClick=${() => confirmUnblockUser(user, back)}><${Ic} i="refresh"/> ${T("Unblock")}</button>`
    : html`<button class="btn btn-danger" onClick=${() => confirmBlockUser(user, back)}><${Ic} i="off"/> ${T("Block")}</button>`;
}

// ── Access expiry (a timed revoke): a peer/subscription stops working once its date passes. Enforced live on the
// node side (dropped from the desired set) and surfaced as a subscription lifecycle badge. The "about to expire"
// warn window is a panel Display setting (default 3 days). Dates are stored as epoch seconds, like every other
// timestamp; a <input type=date> maps to the END of the chosen day so it stays valid THROUGH that date. ──
export const DAY_S = 86400;
export const expiryWarnDays = () => { const d = +((Store.panelSettings || {}).expiry_warn_days); return (d >= 0 && d <= 365) ? d : 3; };
export function fmtDate(sec) { if (!sec) return ""; try { return new Date(sec * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }); } catch (_) { return ""; } }
export function expiryInputVal(sec) { if (!sec) return ""; const d = new Date(sec * 1000); if (isNaN(d.getTime())) return ""; const p = n => String(n).padStart(2, "0"); return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()); }
export function expiryFromInput(str) { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(str || "").trim()); if (!m) return 0; const d = new Date(+m[1], +m[2] - 1, +m[3], 23, 59, 59); const s = Math.floor(d.getTime() / 1000); return s > 0 ? s : 0; }
// The SUBSCRIPTION's lifecycle sentence for a user (block wins over a lapsed date; the soft "about to expire" warn
// only shows inside the warn window). `cls` colours the whole line green (active) / orange (about-to-expire) / red
// (blocked|expired). Block/expiry carry the date they happened / will happen.
export function subState(user) {
  const now = now_s(), u = user || {}, exp = +(u.expiry || 0);
  if (u.disabled) return { cls: "s-blocked", text: T("Subscription was blocked") + (u.disabledAt ? " on " + fmtDate(u.disabledAt) : "") };
  if (exp && now >= exp) return { cls: "s-expired", text: T("Subscription expired on {v1}", { v1: fmtDate(exp) })};
  if (exp && now >= exp - expiryWarnDays() * DAY_S) return { cls: "s-expiring", text: T("Subscription is about to expire on {v1}", { v1: fmtDate(exp) })};
  return { cls: "s-active", text: exp ? T("Subscription is active until {v1}", { v1: fmtDate(exp) }) : T("Subscription is active") };
}
// The PEER's OWN lifecycle sentence — its own block flag + its own expiry date, independent of the subscription and
// of the connectivity status (online/ready/…) shown elsewhere. Returns null for an active peer with no expiry (the
// common case → nothing to show). Same colour scheme as subState.
export function peerState(peer) {
  const now = now_s(), p = peer || {}, exp = +(p.ownExpiry || 0);
  if (p.selfDisabled) return { cls: "s-blocked", text: T("Peer was blocked") + (p.disabledAt ? " on " + fmtDate(p.disabledAt) : "") };
  if (exp && now >= exp) return { cls: "s-expired", text: T("Peer expired on {v1}", { v1: fmtDate(exp) })};
  if (exp && now >= exp - expiryWarnDays() * DAY_S) return { cls: "s-expiring", text: T("Peer is about to expire on {v1}", { v1: fmtDate(exp) })};
  if (exp) return { cls: "s-active", text: T("Peer is active until {v1}", { v1: fmtDate(exp) })};
  return null;
}
// pos: "hd" = centred in a modal title row · "center" = its own centred line (edit-user card) · "bar" = a right-
// aligned line UNDER the header (peer modal / edit-peer). Absent = a plain inline span.
const _statCls = pos => pos ? " substat-" + pos : "";   // i18n-keys: a CSS class fragment
// The USER's own lifecycle sentence — used as the header fallback when there is NO active subscription to report on
// (a disabled or never-enabled subscription). Mirrors peerState: block / expired / about-to-expire, else null (a
// user with no expiry and no block has nothing to say, so the line stays empty).
export function userState(user) {
  const now = now_s(), u = user || {}, exp = +(u.expiry || 0);
  if (u.disabled) return { cls: "s-blocked", text: T("User was blocked") + (u.disabledAt ? " on " + fmtDate(u.disabledAt) : "") };
  if (exp && now >= exp) return { cls: "s-expired", text: T("User expired on {v1}", { v1: fmtDate(exp) })};
  if (exp && now >= exp - expiryWarnDays() * DAY_S) return { cls: "s-expiring", text: T("User is about to expire on {v1}", { v1: fmtDate(exp) })};
  return null;
}
// The subscription sentence, coloured whole (green active / orange about-to-expire / red blocked|expired). Shown
// only when subscriptions are on; tracks state off each poll. With an ACTIVE subscription it reports the
// subscription's lifecycle; with none (disabled or never enabled) it never claims one — it falls back to the user's
// own expiry (userState) and stays silent when there's nothing noteworthy.
export function SubStatusLine({ user, pos }) {
  useStore();
  const rec = useSubRec(user.id);   // the subscription record — .enabled tells a live subscription from a disabled/never-enabled one
  if (!subFeatureOn()) return null;
  const u = (Store.recon.users || []).find(x => x.id === user.id) || user;
  const st = (rec && rec.enabled) ? subState(u) : userState(u);
  if (!st) return null;
  return html`<span class=${"substat " + st.cls + _statCls(pos)}>${st.text}</span>`;
}
// The peer's own lifecycle sentence (null when there's nothing to say — active with no expiry). Independent of the
// subscription feature — a peer's block/expiry applies either way.
export function PeerStatusLine({ peer, pos }) {
  useStore();
  const rp = (Store.recon.peers || []).find(p => p.id === peer.id) || peer;
  const st = peerState(rp);
  if (!st) return null;
  return html`<span class=${"substat " + st.cls + _statCls(pos)}>${st.text}</span>`;
}

// ── assigning a peer to a user, and marking a deployment PRIMARY ───────────────────────────────
export function UserCombo({ onPick, placeholder }) {
  const [q, setQ] = useState(""); const [open, setOpen] = useState(false);
  const users = Store.recon.users.slice().sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const ql = q.toLowerCase();
  const shown = users.filter(u => searchMatch(u.name + " " + (u.tag || ""), ql)).slice(0, 8);
  const { wrapRef, listRef, pos, popStyle } = useAnchoredList(open, setOpen, [q]);
  const pick = uid => { setOpen(false); setQ(""); onPick(uid); };
  return html`<div class="usercombo" ref=${wrapRef}>
    <input class="uc-input" value=${q} placeholder=${placeholder || T("Assign to…")} onClick=${() => setOpen(true)}
      onInput=${e => { setQ(e.target.value); setOpen(true); }}
      onKeyDown=${e => { if (e.key === "Enter" && shown.length === 1) { e.preventDefault(); pick(shown[0].id); } else if (e.key === "Escape") setOpen(false); }}/>
    ${open && pos ? html`<${Portal}><div class="uc-list uc-pop" ref=${listRef} style=${popStyle}>${shown.length ? shown.map(u => html`<button class="uc-opt" key=${u.id}
      onClick=${() => pick(u.id)}><span>${u.name}</span>${u.tag ? html`<span class="tagchip">${u.tag}</span>` : null}</button>`)
      : html`<div class="uc-empty">${users.length ? T("no match") : T("no users yet")}</div>`}</div><//>` : null}
  </div>`;
}

// A type-to-filter user *select* that holds a value (current owner) — used by the create/edit
// peer forms. Like UserCombo but reflects a selection and can offer "— unassigned —".
export function UserPicker({ value, onChange, allowUnassigned, placeholder }) {
  const [q, setQ] = useState(""); const [open, setOpen] = useState(false);
  const users = Store.recon.users.slice().sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const sel = users.find(u => u.id === value);
  const selText = sel ? sel.name + (sel.tag ? " · " + sel.tag : "") : "";
  const ql = q.toLowerCase();
  const shown = users.filter(u => searchMatch(u.name + " " + (u.tag || ""), ql)).slice(0, 8);
  const { wrapRef, listRef, pos, popStyle } = useAnchoredList(open, setOpen, [q]);
  const pick = uid => { setOpen(false); setQ(""); onChange(uid); };
  return html`<div class="usercombo" ref=${wrapRef}>
    <input class="uc-input" value=${open ? q : selText}
      placeholder=${placeholder || (allowUnassigned ? T("— unassigned —") : T("Assign to a user…"))}
      onClick=${() => { setOpen(true); setQ(""); }} onInput=${e => { setQ(e.target.value); setOpen(true); }}
      onKeyDown=${e => { if (e.key === "Escape") { setOpen(false); return; }
        // while actively filtering, Enter never saves the form: exactly one match selects it, anything else does nothing.
        if (e.key === "Enter" && open && q) { e.preventDefault(); if (shown.length === 1) pick(shown[0].id); } }}/>
    ${open && pos ? html`<${Portal}><div class="uc-list uc-pop" ref=${listRef} style=${popStyle}>
      ${allowUnassigned ? html`<button class="uc-opt" onClick=${() => pick("")}><span class="faint">${T("— unassigned —")}</span></button>` : null}
      ${shown.length ? shown.map(u => html`<button class="uc-opt" key=${u.id} onClick=${() => pick(u.id)}><span>${u.name}</span>${u.tag ? html`<span class="tagchip">${u.tag}</span>` : null}</button>`)
        : html`<div class="uc-empty">${users.length ? T("no match") : T("no users yet")}</div>`}
    </div><//>` : null}
  </div>`;
}

// Simple assign for an UNASSIGNED peer: just record the owner (roster metadata). The key / PSK /
// config are kept, so a config already handed out keeps working — no fresh credential, no warning.
export function assignPeer(peer, userId) {
  if (!userId) return;
  return mutate({ key: "peer:" + peer.id,
    patch: s => { const p = s.roster.peers[peer.id]; if (p) p.user_id = userId; },
    call: () => api.peerUpdate({ peer_id: peer.id, user_id: userId }),
    onOk: () => { revealAssignedPeer(userId, peer.id); subReconcileUser(userId); } });   // keeps its key, so publish via backfill (prompts to unlock if locked)
}

// Reassign an ALREADY-assigned peer to a different user — this DOES rotate keys (the previous
// holder must be revoked), so it's confirmed and the new owner needs a re-issued config.
export function confirmReassign(peer, userId, back) {
  const to = Store.recon.users.find(u => u.id === userId);
  const toName = to ? to.name : T("the selected user");
  openConfirm({
    title: T("Reassign peer"), confirmLabel: T("Reassign"), danger: true, back,
    body: T("Reassigning to ") + toName + " rotates the peer's keys. The current user loses access immediately and permanently — assigning them back later would still be a brand-new credential. " + T("{v1} gets a fresh QR / config that must be re-distributed.", { v1: toName }),
    onConfirm: () => assignPeerToUser(peer, userId),
  });
}

// A ★ toggle to mark one of a peer's deployments as PRIMARY (ordered first for the user). Persists immediately.
// Hidden when the peer has a single connection (nothing to choose). Stop propagation so it never bubbles to a card link.
export function PrimaryToggle({ peer, t, compact }) {
  useStore();
  const targets = ((Store.recon.peers.find(p => p.id === peer.id) || {}).targets) || peer.targets || [];
  if (targets.length < 2) return null;
  const isP = isPrimaryTarget(targets, t);
  const [busy, setBusy] = useState(false);
  const set = async (ev) => { if (ev) ev.stopPropagation(); if (isP || busy) return; setBusy(true);
    try { await api.peerSetPrimary({ peer_id: peer.id, node: t.node, iface: t.iface }); await Store.poll(); } catch (_) {} setBusy(false); };
  return html`<button type="button" class=${"primtog" + (isP ? " on" : "")} disabled=${busy || isP}
    title=${isP ? T("Primary connection — the user's first choice") : T("Make this the primary connection")} onClick=${set}>
    <span class="primstar">${isP ? "★" : "☆"}</span>${compact ? null : html`<span>${isP ? T("Primary") : T("Make primary")}</span>`}</button>`;
}

// inline user assignment <select>
// Assign an unassigned peer to a user with a FRESH credential: mint a new keypair + PSK in
// the browser, rebuild the client config for every target, push via rekey. The new owner
// gets a working config; nobody inherits a key a previous holder could still have.
// Verify-only (mints a fresh key + rebuilds configs, so we reveal only on confirm). Routed
// through mutate() for the unified error path; no optimistic patch — heavy/crypto action.
export async function assignPeerToUser(peer, userId) {
  if (!userId) return;
  const key = "peer:" + peer.id;
  let keys, psk, configs;
  try {
    keys = await genKeys(); psk = genPSK(); configs = {};
    for (const t of peer.targets) {
      const m = Store.ifaceMeta(t.node, t.iface);
      if (!m) { Store.rowErrors[key] = { msg: T("{v1} hasn't reported {v2} yet", { v1: Store.nodeName(t.node), v2: t.iface }), at: Date.now(), node: t.node, iface: t.iface }; Store.apply(); return; }
      configs[tkey(t.node, t.iface)] = buildConf({ privkey: keys.priv, address: t.ip + "/32", dns: m.dns, mtu: 1280, awg_params: m.awg_params, server_pubkey: m.public_key, psk, endpoint: m.endpoint, allowed: "0.0.0.0/0, ::/0", keepalive: 25 });
    }
  } catch (e) { Store.rowErrors[key] = { msg: String(e.message || e), at: Date.now() }; Store.apply(); return; }
  await mutate({
    key,
    call: () => api.peerRekey({ peer_id: peer.id, user_id: userId, pubkey: keys.pub, psk }),   // no plaintext to the server
    onOk: () => { Store.sessionConfigs[keys.pub] = configs; Store.configEpoch++; revealAssignedPeer(userId, peer.id);
      subPublishOrPrompt(userId, peer.id, keys.priv, psk); },
  });
}
