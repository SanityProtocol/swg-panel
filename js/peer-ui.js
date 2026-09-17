/* peer-ui.js — everything an operator sees when they open a peer or a user.
 *
 * LAYER 6 (see docs/APP-JS-SPLIT-PLAN.md). Imports every layer below; imported by the roster screens.
 *
 * The QR modal and the target cards are one unit even though they read like two: the modal is a stack of
 * per-deployment cards, each card resolves its own config through the vault, and both the peer view and
 * the user view render the same cards with different chrome. Splitting card from modal would have meant
 * threading the config-resolution state between two modules for no gain.
 *
 * Everything secret here comes from crypto.js and stays in the browser — these components render a
 * private key into a QR and a .conf and never send one anywhere.
 */

import { T, Trich, Tsplit, plural, srvText } from "./i18n.js";
import { esc, tkey, dur, ago, seen, fmtBytes, ipOf, portOf, orderedTargets, isPrimaryTarget, targetRole,
         useStableOrder, isSelfContainedKind } from "./util.js";
import { Store, api, bus, useStore } from "./store.js";
import { targetType, iTypeOf, kindOf, nodeStale, ghostIface, turnProxiesFor, tgtXfer, isSelfContainedTgt, peerUncategorised } from "./model.js";
import { go } from "./router.js";
import { turnFork, turnLabel, turnColor, turnClientColor, turnClientAuthor, turnForkList, forkLabel } from "./turn-catalog.js";
import {
  Ic, ICON, Tag, Panel, Badge, Sheet, footRow, secTitle, SearchBox, Switch, Dropdown, Disclosure, autoGrow,
  Popover, CapList, useCapped, Portal, toast, copy, mutate, openModal, pushModal, closeModal, closeAllModals, closeModals, openConfirm,
  openChildOrRoot, ConfirmSheet, subjectBlocked, statusLabel, rowSingle, rowDouble, rowNoSelect, RowError,
  useAnchoredList, goSettings, LogBody, rateCell, uncatPop, ListPager, LIST_PAGE, pageSlice, modalDepth,
} from "./ui.js";
import {
  QR, qrDataURL, qrZoom, copyQrImage, buildConf, parseFullConf, downloadConf, getConfig, configOverrides,
  anySessionConf, rerenderConf, effectiveClientParams, turnArtifact, turnClientsFor, turnClientSettingsFor,
  subFeatureOn, subSKCached, subBaseUrl, subUsersMap, useSubRec, ensureVaultUnlocked, subUrlFor,
  subEnableUser, subRotateUser, subBackfillUser, subKeyB64, VaultPromptSheet, ensurePeerBlob,
  subPersistOn, subSetPersist, subUnlock, subRecover, subUsersForget, confWasUnreachable, confWasSealedOld} from "./crypto.js";
import {
  confirmDeletePeer, confirmUnassign, confirmBlockPeer, confirmUnblockPeer, confirmBlockUser,
  confirmUnblockUser, peerBlockBtn, userBlockBtn, rotateAllUserKeys, PeerStatusLine, SubStatusLine,
  fmtDate, expiryInputVal, expiryFromInput, expiryWarnDays, RoleToggle, UserCombo, UserPicker,
  confirmReassign, assignPeerToUser, openRecreateRekey, confirmRestoreDeployment, confirmCorrectDeployment,
  now_s,
} from "./peer-actions.js";
import { searchMatch, userStats, userStatTag, groupShares, shareDeviceName, namedFew,
         deviceLabel, deviceNameAt, ownerNameAt, userReach, reachTally, netsCached, netsFetch, netTally, netRowOnline, wantNetsCount,
         peerAudience, peerAudCached, peerAudFetch, reachableByGroup } from "./views.js";
import { AppDropdown, OsDropdown, ForkTag, turnForkPlatforms, WDTT_COLOR, appNameColor, turnEnabled,
         _OS_TABS } from "./turn.js";
import { h, Fragment } from "preact";
import { useState, useEffect, useRef, useMemo } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// `child` = opened from another modal (user modal, peer view, edit peer). Then it's PUSHED onto the modal
// stack so the parent stays mounted behind it (no reload, scroll preserved) and ✕/Esc/backdrop/"Back" just
// pop back to it. Root (from a table) replaces the top as before.
export function openPeerConfigs(peer, opts) {
  opts = opts || {};
  const child = !!opts.child;      // pushed onto the stack (opened from another modal) → "Back" pops to the parent
  const hideVk = !!opts.hideVk;    // the parent (user modal) already shows the VK link — don't repeat it here
  const cols = Math.min(peer.targets.length || 1, 3);   // up to 3 QRs per view; the modal sizes to fit (more → page with ‹ ›)
  const wcols = Math.max(cols, 2);                       // hold 2 QRs wide even for a single deployment (roomier layout)
  const width = wcols * QR_ITEM + (wcols - 1) * QR_GAP + 56;
  const vkUser = peer.user_id ? Store.recon.users.find(u => u.id === peer.user_id) : null;
  // an unassigned peer always leads with "Unassigned peer", then its title — or, with no title, its internal IP
  const ipShort = (((peer.targets || [])[0] || {}).ip || "").split("/")[0];
  const parts = []; parts.push(vkUser ? vkUser.name : T("Unassigned peer"));
  if (peer.title) parts.push(peer.title);
  else if (!vkUser && ipShort) parts.push(ipShort);
  const nm = parts.join(" · ");
  const title = html`<span class="qrhd"><span class="qrhd-nm">${nm}</span></span>`;
  // In a subscription: subscription status in the header (right), the peer's own status on a line under it.
  // Not in a subscription: the peer's own status takes the header slot (nothing under it).
  const headExtra = vkUser ? html`<${SubStatusLine} user=${vkUser} pos="hr"/>` : html`<${PeerStatusLine} peer=${peer} pos="hr"/>`;
  (child ? pushModal : openModal)(html`<${Sheet} title=${title} width=${width} headExtra=${headExtra} noGuard=${true} onClose=${closeModal} onBack=${child ? closeModal : null}
    subject=${{ kind: "peer", id: peer.id }} foot=${html`<${QRPeerFoot} pid=${peer.id}/>`}>
    ${vkUser ? html`<${PeerStatusLine} peer=${peer} pos="bar"/>` : null}
    <${VaultUnlockPanel} need=${(peer.targets || []).some(t => !isSelfContainedKind(targetType(t)))}/>
    ${!hideVk && vkUser && targetsWantVk(peer.targets) ? html`<${VkLinkField} user=${vkUser}/>` : null}
    <${QRRow} cards=${orderedTargets(peer.targets).map(t => html`<${TargetCard} key=${tkey(t.node, t.iface)} peer=${peer} t=${t} bare=${true} primary=${peer.targets.length > 1 ? targetRole(t) : ""}/>`)}/>
  <//>`);
}

// A horizontal carousel of fixed-width cards. Steps ONE card at a time; the counter + ‹/› enabled-state derive
// from live scroll metrics (not a mid-scroll index guess), so it never jumps back or gets stuck before the last.
export const QR_ITEM = 292, QR_GAP = 14;   // card width; mirrored by `.qrrow > .deploy` in app.css
// ← / → scroll the carousel. Only the TOPMOST mounted (paged) carousel responds — a peer modal opened over a
// user modal steals the arrows until it closes — so nested modals don't scroll in lockstep. Each paged QRRow
// pushes a stepper; the last one registered wins. Ignored while typing or with a modifier held.
const _qrNavStack = [];
function _qrNavKey(e) {
  if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
  const t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
  const step = _qrNavStack[_qrNavStack.length - 1];
  if (!step) return;
  e.preventDefault();
  step(e.key === "ArrowLeft" ? -1 : 1);
}
export function QRRow({ cards }) {
  const ref = useRef(null);
  const [m, setM] = useState({ l: 0, cw: 0, sw: 0, step: QR_ITEM + QR_GAP });
  useEffect(() => { const el = ref.current; if (!el) return;
    const measure = () => {
      const first = el.firstElementChild;                                   // real card width (varies by card type)
      const cardW = first ? first.getBoundingClientRect().width : QR_ITEM;
      const cs = getComputedStyle(el);
      const gap = parseFloat(cs.columnGap || cs.gap) || QR_GAP;
      setM({ l: el.scrollLeft, cw: el.clientWidth, sw: el.scrollWidth, step: cardW + gap });
    };
    measure(); el.addEventListener("scroll", measure, { passive: true });
    let ro; try { ro = new ResizeObserver(measure); ro.observe(el); } catch (_) {}
    return () => { el.removeEventListener("scroll", measure); if (ro) ro.disconnect(); }; }, [cards.length]);
  const n = cards.length;
  const step = m.step || (QR_ITEM + QR_GAP);
  const paged = m.sw > m.cw + 4;
  const atStart = m.l <= 2;
  const atEnd = m.sw > 0 && m.l + m.cw >= m.sw - 2;
  const per = Math.max(1, Math.round(m.cw / step));                         // cards visible per view
  let first = Math.max(0, Math.min(Math.round(m.l / step), n - per));       // 0-based index of the first visible card
  if (atEnd) first = Math.max(0, n - per);
  const last = Math.min(n - 1, first + per - 1);
  const range = first === last ? `${first + 1} of ${n}` : `${first + 1}–${last + 1} of ${n}`;
  const go = d => { const el = ref.current; if (el) el.scrollBy({ left: d * step, behavior: "smooth" }); };
  // register this carousel as the arrow-key target while it's paged (a stable wrapper calls the freshest `go`,
  // which closes over the current step measurement)
  const goRef = useRef(go); goRef.current = go;
  useEffect(() => {
    if (!paged) return;
    const stepper = d => goRef.current(d);
    if (!_qrNavStack.length) window.addEventListener("keydown", _qrNavKey);
    _qrNavStack.push(stepper);
    return () => { const i = _qrNavStack.lastIndexOf(stepper); if (i >= 0) _qrNavStack.splice(i, 1);
      if (!_qrNavStack.length) window.removeEventListener("keydown", _qrNavKey); };
  }, [paged]);
  return html`<div class=${"qrrowwrap" + (paged ? " paged" : "")}>
    <div class="qrrow" ref=${ref}>${cards}</div>
    ${paged ? html`<div class="qrnav">
      <button class="qrnavbtn" disabled=${atStart} onClick=${() => go(-1)} aria-label=${T("Previous")}>‹</button>
      <span class="qrnavcount">${range}</span>
      <button class="qrnavbtn" disabled=${atEnd} onClick=${() => go(1)} aria-label=${T("Next")}>›</button>
    </div>` : null}
  </div>`;
}

// ── QR-modal building blocks (shared by the peer + user views) ──────────────────────────────────

// The single unlock gate. One panel, one password — unlocking reveals BOTH the stored QRs and the subscription
// link (one encryption key gates both). Renders nothing once unlocked, or when no vault is set up.
export function VaultUnlockPanel({ need } = {}) {
  const [exists, setExists] = useState(null);
  const [ready, setReady] = useState(!!subSKCached());
  const [pw, setPw] = useState(""); const [busy, setBusy] = useState(false);
  const [keep, setKeep] = useState(subPersistOn());
  useEffect(() => { if (subSKCached()) { setReady(true); return; }
    let ok = true; api.subVault().then(r => { if (ok) setExists(!!(r && r.ok && r.data && r.data.exists)); }).catch(() => { if (ok) setExists(false); });
    return () => { ok = false; }; }, []);
  // WDTT targets are keyless (server-minted key) — their QR needs no vault. When a modal has nothing that DOES
  // (all-WDTT peer, no WG config / sub link), the caller passes need=false so we don't claim "unlock to see QR codes".
  if (need === false || ready || subSKCached() || !exists) return null;
  const unlock = async () => {
    if (!pw || busy) return; setBusy(true);
    try { await subUnlock(pw); subSetPersist(keep); setPw(""); setReady(true); Store.configEpoch++; bus.emit(); }
    catch (e) { toast((e && e.message) || T("That password didn’t unlock the Encryption Vault."), "err"); }
    setBusy(false);
  };
  return html`<div class="unlockpanel">
    <div class="unlockpanel-msg"><${Ic} i="key"/><span>${T("Unlock the Encryption Vault to see configs, QR codes and the subscription link.")}</span></div>
    ${/* ⚠️ A FORM OF ITS OWN, so a password manager looks for this password's username INSIDE it. Loose in a sheet, Chrome took
          the nearest text field before it — the user sheet's group search — and wrote the saved login there (measured: the
          picker opened reading "snproto"). autocomplete=off does not stop that; a form boundary does. Enter still unlocks
          once: keydown handles it and cancels the implicit submit. */""}
    <form class="unlockpanel-row" onSubmit=${e => e.preventDefault()}>
      <input class="subpw" type="password" autofocus autocomplete="current-password" placeholder=${T("Panel password")} value=${pw}
        onKeyDown=${e => { if (e.key === "Enter") { e.preventDefault(); unlock(); } }} onInput=${e => setPw(e.target.value)}/>
      <button type="button" class="btn btn-primary" disabled=${busy || !pw} onClick=${unlock}>${busy ? T("Unlocking…") : T("Unlock")}</button>
    </form>
    <label class="vp-keep-row"><input type="checkbox" checked=${keep} onChange=${e => setKeep(e.target.checked)}/> <span>${T("Trust this device and keep it unlocked")}</span></label>
  </div>`;
}
// The subscription link + controls (user modal). Shown only once the vault is unlocked — the link's secret is
// derived from the key. Enable / Rotate / Disable, each behind a confirm; the link + copy sits above them.
export function SubLinkActions({ user }) {
  useStore();
  const rec = useSubRec(user.id);
  const [url, setUrl] = useState(null);
  const [busy, setBusy] = useState(false);
  const [optim, setOptim] = useState(false);   // optimistic "link building" state — enable runs in the background
  const base = subBaseUrl();
  useEffect(() => { let ok = true;
    (async () => { if (rec && rec.enabled && subSKCached()) { try { const u = await subUrlFor(rec); if (ok) setUrl(u); } catch (_) { if (ok) setUrl(null); } } else if (ok) setUrl(null); })();
    return () => { ok = false; }; }, [rec && rec.enabled, Store.configEpoch]);
  if (!subFeatureOn() || !subSKCached() || rec === undefined) return null;   // locked → the unlock panel owns it
  const after = async () => { setOptim(false); subUsersForget(); Store.configEpoch++; bus.emit(); };   // clear the optimistic flag once the real record is (re)fetched — else a later disable stays stuck "building"
  const settingsLink = html`<a href="#/panel/settings" onClick=${() => closeAllModals()}>${T("Settings → Subscriptions")}</a>`;
  const confirm = opts => pushModal(html`<${ConfirmSheet} ...${opts}/>`);   // stacks over the user modal; pops back on cancel/confirm
  const act = fn => async () => { setBusy(true); try { await fn(); } catch (e) { toast((e && e.message) || T("Failed"), "err"); } setBusy(false); await after(); };
  // Enable is OPTIMISTIC: the confirm closes instantly and the panel shows the link building right away while
  // the token-mint + config-publish runs in the background (the browser already holds everything the link needs;
  // the server only stores the token hash). On failure we roll the optimistic state back and toast.
  const enableBg = async () => {
    try { await subEnableUser(user.id); const r2 = (await subUsersMap(true))[user.id]; if (r2 && r2.enabled && r2.unlock_by_sk) { const { unlockKey } = await subRecover(r2); await subBackfillUser(user.id, unlockKey); } }
    catch (e) { setOptim(false); toast((e && e.message) || T("Couldn't create the subscription link"), "err"); }
    finally { await after(); }
  };
  const enable = () => confirm({ title: T("Enable subscription"), confirmLabel: T("Enable"),
    body: T("Create a shareable link to this user's QR codes. New peers appear on it automatically; the unlock secret rides in the link and never reaches the server."),
    onConfirm: () => { setOptim(true); enableBg(); } });   // returns immediately → the confirm closes; work continues in the background
  const rotate = () => confirm({ title: T("Rotate subscription link"), confirmLabel: T("Rotate"), warn: true,
    body: T("Issue a fresh link and invalidate the current one. A config already scanned keeps working until you rekey or remove the peer."),
    onConfirm: act(() => subRotateUser(user.id)) });
  const disable = () => confirm({ title: T("Disable subscription"), confirmLabel: T("Disable"), warn: true,
    body: T("This only turns off this user's subscription LINK — the page stops resolving. It does NOT disconnect their peers: existing connections keep working, and a config already scanned keeps working until you rekey or remove the peer. To actually cut this user's access, use Block instead. Re-enabling later issues a fresh link over the same configs."),
    onConfirm: act(() => api.subUserDisable({ user_id: user.id })) });
  const enabled = !!(rec && rec.enabled) || optim;
  if (!enabled) return html`<div class="sublink sublink-off">
    <span class="sublink-off-msg">${T("No subscription link yet — enable one to share this user's QRs.")}</span>
    <button class="btn btn-primary btn-mini" disabled=${busy} onClick=${enable}>${T("Enable subscription")}</button>
  </div>`;
  return html`<div class="field sublink-field">
    <label>${T("Subscription link")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— this user's shareable QR page")}</span></label>
    <div class="sublink sublink-row">
      ${url ? html`<${SubUrlBar} url=${url}/>` : !base
        ? html`<div class="hint warn">${Trich("Set a public base URL in {v1} to build the link.", { v1: settingsLink })}</div>`
        : html`<div class="hint">${T("Building link…")}</div>`}
      <span class="fieldbtns">
        <button class="btn btn-ghost btn-mini fbtn" disabled=${busy} onClick=${rotate}>${T("Rotate token")}</button>
        <button class="btn btn-ghost btn-mini fbtn" disabled=${busy} onClick=${disable}>${T("Disable URL")}</button>
      </span>
    </div>
  </div>`;
}
// One user-modal card: a peer's PRIMARY/only QR under a two-line clickable header that opens the peer's own
// modal. Line 1: title (or "Peer .{last IP octet}") · server name + protocol badge. Line 2: interface badge
// (+N when there are more deployments) · status. Reuses TargetCard's QR body + actions via its `head` override.
export function UserPeerCard({ peer, onOpen }) {
  useStore();   // re-render on each poll so the status badge (looked up live below) tracks block/unblock, like TargetCard
  const targets = peer.targets || [];
  // The peer's PRIMARY deployment represents it here. `targets[0]` was whichever happened to be written first,
  // which on a peer spanning several kinds picked one arbitrarily to stand for the whole peer — and the card
  // then claimed a single protocol badge for a peer that may hold four. orderedTargets puts the primary first,
  // and where the peer spans more than one KIND the deployment count names them instead of hiding the rest.
  const t = orderedTargets(targets)[0] || {};
  const kinds = [...new Set(targets.map(targetType))];
  const col = Store.nodeColor(t.node);
  const dnode = Store.nodeName(t.node);
  const ltype = targetType(t);
  const oct = String(t.ip || "").split("/")[0].split(".").pop() || "";
  const nm = peer.title || (oct ? T("Peer .{v1}", { v1: oct }) : T("Peer"));
  const lt = ((Store.recon.peers.find(p => p.id === peer.id) || {}).targets || []).find(d => d.node === t.node && d.iface === t.iface) || t;
  const head = html`<div class="upc-head">
    <div class="upc-l1"><span class="upc-nm">${nm}</span><span class="grow"></span>${peerUncategorised(lt) && lt.status !== "blocked" && lt.status !== "faulty"
      // This head is SHARED by every card kind in the configs modal, which is why fixing the deploy-head
      // below did not reach it — that branch only renders when no head is passed, and one always is.
      ? uncatPop(html`<span class="badge b-uncat ic"><${Ic} i="warn"/>${statusLabel(lt.status)}</span>`)
      : html`<${Badge} s=${lt.status}/>`}</div>
    <div class="upc-l2"><span class="upc-srv" style=${"color:" + col}>${dnode}</span><${Tag} kind=${ltype} label=${t.iface}/><span class="grow"></span>${targets.length > 1 ? html`<span class="upc-deps" title=${kinds.join(" · ")}>${kinds.length > 1 ? kinds.join(" · ") : plural(targets.length, "deployment")}</span>` : null}</div>
  </div>`;
  // Only a MULTI-config peer opens its own modal (a single-config peer has nothing extra to show — it's already
  // fully presented here). When it does: the whole card opens it EXCEPT the QR image (enlarges) and the action
  // buttons (their own jobs). `.hot` is toggled by the pointer so the card highlights only over clickable regions.
  if (!onOpen) return html`<div class="upc-wrap upc-static">
    <${TargetCard} peer=${peer} t=${t} bare=${true} head=${head}/>
  </div>`;
  const own = el => el && el.closest(".qr, button, a");
  const onClick = e => { if (own(e.target)) return; onOpen(peer); };
  const onMove = e => e.currentTarget.classList.toggle("hot", !own(e.target));
  const onLeave = e => e.currentTarget.classList.remove("hot");
  return html`<div class="upc-wrap" onClick=${onClick} onMouseMove=${onMove} onMouseLeave=${onLeave} title=${T("Open this peer's configs")}>
    <${TargetCard} peer=${peer} t=${t} bare=${true} head=${head}/>
  </div>`;
}
// The VK link baked into a peer's turn configs IN THE PANEL: the owning user's own link, falling back to the
// panel-wide test link (Settings → Turn proxies) for the admin's own testing + for unassigned peers. The
// subscription page never falls back — it uses only the per-user link (see swg-sub).
export function userVkLink(user) {
  return (((user && user.vk_link) || "").trim()) || (((Store.panelSettings || {}).vk_link || "").trim());
}
// ALL of a user's VK call links (primary first) for the forks that embed several; falls back to the single link,
// then the panel test link (panel-side only — subscriptions never fall back).
export function userVkLinks(user) {
  let arr = (user && Array.isArray(user.vk_links) && user.vk_links.length) ? user.vk_links.slice()
          : (user && (user.vk_link || "").trim() ? [user.vk_link] : []);
  if (!arr.length) { const t = ((Store.panelSettings || {}).vk_link || "").trim(); if (t) arr = [t]; }
  return arr.map(s => (s || "").trim()).filter(Boolean);
}
// Does this peer have a VK hash OF ITS OWN — its own vk_hash, or its user's link(s)? When it doesn't, the
// generator above still produces a complete-looking link by baking in the panel-wide fallback, and the operator
// has no way to tell the two apart by looking. That matters twice over: the fallback is one link shared by every
// such peer, and the SUBSCRIPTION page deliberately uses only per-user links — so the user's own page hands out
// a link without it. Says so at the moment a config is generated, which is the only moment anyone would act.
// Note `user` is also null when peer.user_id does not resolve, which is the same situation from here.
export function vkOwnHash(peer, user) {
  if (((peer || {}).vk_hash || "").trim()) return true;
  const own = (user && Array.isArray(user.vk_links) && user.vk_links.length) ? user.vk_links
            : (user && (user.vk_link || "").trim() ? [user.vk_link] : []);
  return own.some(s => (s || "").trim());
}
// Is any of these deployments behind a turn-proxy? (turn feature on AND a proxy forwards to the interface.) Gates
// the per-user VK field + the sub's VK warning — no turn-proxy on a user's interfaces ⇒ they never use a VK link.
// Does this peer ride a VK call — i.e. does it need the user's VK link? Two ways in: fronted by a turn-proxy,
// or ON a WDTT server. WDTT carries its own vk_hash per user but FRONTS nothing, so turnProxiesFor() finds
// nothing for it — which left a WDTT-only user with no VK field at all, and no way to set the link their
// config needs.
export function targetsWantVk(targets) {
  if (turnEnabled() && (targets || []).some(t => turnProxiesFor(t.node, t.iface).length > 0)) return true;
  return (targets || []).some(isSelfContainedTgt);
}
export const _VK_CALL_RE = /^https:\/\/(?:[\w.-]+\.)?vk(?:ontakte)?\.(?:com|ru)\/call\/join\/[\w-]+/i;
// let the operator paste a VK link with or without the scheme — add https:// when it's missing
export function normVkLink(s) { s = (s || "").trim(); return s && !/^https?:\/\//i.test(s) ? "https://" + s : s; }
// Per-user VK call link, editable inline from the QR modals. Shown only when the user has a peer behind a
// turn-proxy. Empty → amber border + a hint (the panel falls back to the test link; the subscription page won't).
// Saves on blur / Enter; re-renders turn configs with the new link.
export function VkLinkField({ user }) {
  useStore();   // re-render on each poll so the count + field reflect a Manage-modal save (or an inline Add) without reopening the modal
  const lu = (Store.recon.users || []).find(x => x.id === user.id) || user;   // live user — the modal's `user` prop is a stale snapshot
  const primary = (lu.vk_links && lu.vk_links.length) ? lu.vk_links[0] : (lu.vk_link || "");   // the true primary = vk_links[0] (the Manage modal reorders it there); fall back to the single vk_link
  // track the SAVED value locally: the modal holds a stale `user` snapshot, so we key off the LIVE primary.
  const [saved, setSaved] = useState(primary);
  const [val, setVal] = useState(primary);
  const [busy, setBusy] = useState(false);
  const [subd, setSubd] = useState(false);
  const [saveStatus, setSaveStatus] = useState(null);   // "saved" | "failed" — shown ~5s next to the button
  const savedTimer = useRef(null);
  const flashStatus = s => { setSaveStatus(s); if (savedTimer.current) clearTimeout(savedTimer.current); savedTimer.current = setTimeout(() => setSaveStatus(null), 5000); };
  useEffect(() => { setVal(primary); setSaved(primary); }, [user.id, primary]);   // reset when the live primary changes (Manage save / external), but not while the user is typing (val isn't a dep)
  useEffect(() => { let ok = true; if (subFeatureOn()) subUsersMap().then(m => { if (ok) setSubd(!!(m[user.id] && m[user.id].enabled)); }).catch(() => {}); return () => { ok = false; }; }, [user.id]);
  useEffect(() => () => { if (savedTimer.current) clearTimeout(savedTimer.current); }, []);
  const v = normVkLink(val);                    // accept the link with or without https:// — add it when missing
  const invalid = !!v && !_VK_CALL_RE.test(v);
  const empty = !v;
  const set = !empty && !invalid;               // a valid link is present → blue highlight
  const dirty = v !== saved;
  const add = async () => {
    if (!dirty || invalid || empty) return;
    setBusy(true);
    const existing = (lu.vk_links && lu.vk_links.length ? lu.vk_links : (lu.vk_link ? [lu.vk_link] : []));
    const ordered = [v, ...existing.filter(u => u !== v)];   // the typed link becomes primary; existing links are kept (dedup) → the count grows
    const r = await api.userUpdate({ id: user.id, vk_links: ordered, vk_link: v });
    setBusy(false);
    if (!r || !r.ok) { flashStatus("failed"); toast(srvText(r) || T("Couldn't add the VK link"), "err"); return; }
    setSaved(v);                                  // dirty=false → button disables; the live count reflects the new list on the next poll
    flashStatus("saved");
    Store.poll(); Store.configEpoch++; bus.emit();   // turn configs re-render with the updated links
  };
  return html`<div class=${"field vkfield" + (invalid ? " warn" : set ? " set" : " warn")} style="margin-bottom:14px">
    <label>${T("VK call link")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— for this user's configs that ride a VK call")}</span></label>
    <div class="vkfield-row">
      <div class="vkbox">
        <${Ic} i="link"/>
        <input class="vkbox-input" data-noautofocus value=${val} placeholder=${T("vk.ru/call/join/…")} disabled=${busy}
          onInput=${e => setVal(e.target.value)} onKeyDown=${e => { if (e.key === "Enter") { e.preventDefault(); add(); } }}/>
      </div>
      <span class="fieldbtns">
        ${saveStatus === "saved" ? html`<span class="vk-status ok"><${Ic} i="check"/> ${T("Saved")}</span>`
          : saveStatus === "failed" ? html`<span class="vk-status err"><${Ic} i="warn"/> ${T("Failed")}</span>` : null}
        <button class="btn btn-ghost btn-mini fbtn" disabled=${busy || !dirty || invalid || empty} onClick=${add}>${busy ? T("Adding…") : T("Add link")}</button>
        <button class="btn btn-ghost btn-mini fbtn" onClick=${() => pushModal(html`<${VkLinksSheet} user=${user}/>`)} title=${T("Manage all of this user's VK call links (add more, set primary)")}>${T("Manage")}${(lu.vk_links && lu.vk_links.length > 1) ? ` (${lu.vk_links.length})` : ""}</button>
      </span>
    </div>
    ${invalid ? html`<div class="hint err">${T("Expected a VK call link like")} <span class="mono">https://vk.ru/call/join/…</span></div>`
      : empty ? html`<div class="hint vk-warn">${noVkLinks()}${subd ? html` ${noVkSubbed()}` : ""}</div>` : null}
  </div>`;
}
// Manage ALL of a user's VK call links (grid CRUD + which is primary). The primary is the one single-link apps use;
// FreeTurn passes them all. Reordered so the primary is first on save (vk_links[0] = primary; vk_link mirrors it).
export function VkLinksSheet({ user }) {
  useStore();   // re-render on each poll so a link just taken from the pool shows as a POOL link, not a personal one
  const lu = (Store.recon.users || []).find(x => x.id === user.id) || user;   // live user — the modal's `user` prop is a stale snapshot
  const start = (lu.vk_links && lu.vk_links.length ? lu.vk_links : (lu.vk_link ? [lu.vk_link] : [])).slice();
  // Which of this user's links came from the shared pool. Keyed by URL (provenance is stored pool-id → URL),
  // so a link the operator retypes by hand stops reading as a pool link — which is exactly right: once it no
  // longer matches the pool entry, the pool no longer owns it and won't rewrite it under them.
  const poolUrls = new Set(Object.values(lu.vk_pool || {}));
  const fromPool = (url) => poolUrls.has(url);
  const [rows, setRows] = useState(start.length ? start.map(u => ({ url: u })) : [{ url: "" }]);
  const [adding, setAdding] = useState(false);
  const [primary, setPrimary] = useState(0);
  const [busy, setBusy] = useState(false);
  const setUrl = (i, v) => setRows(rs => rs.map((r, j) => j === i ? { url: v } : r));
  const addRow = () => setRows(rs => [...rs, { url: "" }]);
  const delRow = (i) => { setRows(rs => { const n = rs.filter((_, j) => j !== i); return n.length ? n : [{ url: "" }]; });
    setPrimary(p => (i === p ? 0 : i < p ? p - 1 : p)); };
  const norm = rows.map(r => normVkLink(r.url));                       // add https:// where missing
  const bad = norm.some(u => u && !_VK_CALL_RE.test(u));
  const poolLeft = ((Store.panelSettings || {}).vk_pool || [])
    .filter(e => e && e.url && !e.dead && !norm.includes(e.url)).length;   // links this user could still be given
  // The pick happens on the server (it holds the pool and excludes what they already have). Unsaved edits in
  // this sheet would be lost by the round trip, so save them first when there are any.
  const addFromPool = async () => {
    setAdding(true);
    if (dirty) { const ok = await persist(false); if (!ok) { setAdding(false); return; } }
    const r = await api.userVkPoolAdd(user.id);
    setAdding(false);
    if (!r || !r.ok) return toast(srvText(r) || T("Couldn't add a link from the pool"), "err");
    const got = (r.data || {}).vk_links || [];
    setRows(got.map(u => ({ url: u })));
    Store.poll(); Store.configEpoch++; bus.emit();
    toast(T("Added a link from the pool."), "ok");
  };
  const dirty = JSON.stringify(norm.filter(Boolean)) !== JSON.stringify(start);
  const persist = async (close) => {
    const clean = norm.filter(Boolean);
    if (clean.some(u => !_VK_CALL_RE.test(u))) { toast(T("One of the links isn't a valid VK call link."), "err"); return false; }
    const uniq = [...new Set(clean)];
    const primUrl = norm[primary];                                    // move the chosen primary to the front
    const ordered = primUrl && uniq.includes(primUrl) ? [primUrl, ...uniq.filter(u => u !== primUrl)] : uniq;
    setBusy(true);
    const r = await api.userUpdate({ id: user.id, vk_links: ordered });
    setBusy(false);
    if (!r || !r.ok) { toast(srvText(r) || T("Couldn't save the VK links"), "err"); return false; }
    if (close) closeModal();
    Store.poll(); Store.configEpoch++; bus.emit();                    // turn configs re-render with the updated links
    if (close) toast(ordered.length ? T("Saved {v1}.", { v1: plural(ordered.length, "VK link") }) : T("VK links cleared."), "ok");
    return true;
  };
  const save = () => persist(true);
  return html`<${Sheet} title=${html`${T("VK call links")} <span class="faint" style="text-transform:none;letter-spacing:0">— ${user.name}</span>`} width=${560} onClose=${closeModal}
    foot=${html`<${Fragment}><button class="btn btn-ghost" onClick=${addRow}><${Ic} i="plus"/> ${T("Add link")}</button>
      <button class="btn btn-ghost" disabled=${adding || busy || !poolLeft} onClick=${addFromPool}
        title=${poolLeft ? T("Give this user one more link from the shared pool") : T("No unused link left in the shared pool")}>
        <${Ic} i="users"/> ${adding ? T("Adding…") : T("Add from pool")}</button>
      <span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>${T("Cancel")}</button>
      <button class="btn btn-primary" disabled=${busy || bad} onClick=${save}>${busy ? T("Saving…") : T("Save")}</button></>`}>
    <div class="iface-intro" style="margin-top:2px"><div>${vkLinksIntro()}</div></div>
    <div class="vklinks-grid">
      ${rows.map((r, i) => { const nv = norm[i]; const rbad = nv && !_VK_CALL_RE.test(nv); return html`
        <div class=${"vklinks-row" + (rbad ? " warn" : "")}>
          <button type="button" class=${"primtog vklinks-star" + (primary === i ? " on" : "")}
            title=${primary === i ? T("The primary link — single-link apps use this one") : T("Set as the primary link")}
            onClick=${() => setPrimary(i)}><span class="primstar">${primary === i ? "★" : "☆"}</span></button>
          <div class=${"vkbox" + (fromPool(r.url) ? " frompool" : "")} style="flex:1">
            <${Ic} i=${fromPool(r.url) ? "users" : "link"}/>
            ${/* A pool link is the POOL's to edit: retyping it here would silently detach this user from the
                  pool entry, and the next edit or mark-dead would no longer reach them. Read-only, and the
                  tooltip says where to change it. Personal links stay fully editable. */ ""}
            <input class="vkbox-input" value=${r.url} placeholder=${T("vk.ru/call/join/…")}
              readOnly=${fromPool(r.url)}
              title=${fromPool(r.url) ? T("From the shared pool — change it in Settings → Turn proxies, or remove it here") : ""}
              onInput=${e => setUrl(i, e.target.value)}/>
          </div>
          <button class="iconbtn" title=${T("Remove this link")} onClick=${() => delRow(i)}><${Ic} i="trash"/></button>
        </div>`; })}
    </div>
    ${bad ? html`<div class="hint err">${T("Every link must look like")} <span class="mono">https://vk.ru/call/join/…</span></div>` : null}
    ${/* Apps genuinely differ — the vkturnproxy link carries every link, the wdtt:// one takes 4 and csqtt 6,
          and single-link apps take only the primary. So this says the ORDER matters rather than naming a cap
          that would be wrong for half the fleet. Only shown once a user holds more than the tightest cap. */ ""}
    ${norm.filter(Boolean).length > (((typeof SWGTurn !== "undefined" && SWGTurn.vkLinkCaps) || {}).wdtt || 4)
      ? html`<div class="hint">${T("Apps differ: some use every link, some only the first few, some only the primary — the star sets which comes first.")}</div>` : null}
  </div>`;
}
// Quick "Set expiry" — a small date picker reachable straight from the QR modal (no trip to the edit screen).
// A user sets the SUBSCRIPTION expiry; a peer sets its OWN expiry, capped at the user's (can't outlive it).
export function openSetExpiry(kind, id) { pushModal(html`<${SetExpirySheet} kind=${kind} id=${id}/>`); }
export function SetExpirySheet({ kind, id }) {
  const isUser = kind === "user";
  const rec = isUser ? Store.user(id) : Store.peer(id);   // Store.peer already returns the RECONCILED peer (carries ownExpiry)
  const cur = isUser ? ((rec && rec.expiry) || 0) : ((rec && rec.ownExpiry) || 0);
  const owner = !isUser && rec && rec.user_id ? Store.user(rec.user_id) : null;
  const ownerExp = owner ? (owner.expiry || 0) : 0;   // a peer can't be set to outlive its user's subscription
  const [d, setD] = useState(expiryInputVal(cur));
  const [busy, setBusy] = useState(false);
  if (!rec) { closeModal(); return null; }
  const save = async () => {
    setBusy(true);
    const sec = expiryFromInput(d);
    const r = isUser ? await api.userUpdate({ id, expiry: sec }) : await api.peerUpdate({ peer_id: id, expiry: sec });
    setBusy(false);
    if (!r || r.ok === false) { toast(srvText(r) || T("Couldn't set the expiry"), "err"); return; }
    subUsersForget(); await Store.poll(); closeModal();
    toast(sec ? T("Expiry set to {v1}", { v1: fmtDate(sec) }) : T("Expiry cleared"), "ok");
  };
  const nm = rec.name || rec.title || "";
  return html`<${Sheet} title=${(isUser ? T("Subscription expiry") : T("Peer expiry")) + (nm ? " · " + nm : "")} width=${430} noGuard=${true} onClose=${closeModal} onBack=${closeModal}
      foot=${footRow({ onCancel: closeModal, disabled: busy, onAction: save, action: T("Save") })}>
    <p class="hint" style="margin:2px 0 14px">${isUser
      ? T("After this date the whole subscription counts as expired — its page shows “Expired” and its peers stop being served. Blank = never expires.")
      : T("After this date just this peer expires (its config stops working); the rest of the user's peers are unaffected. It can't be set later than the user's subscription expiry. Blank = follows the subscription.")}</p>
    <div class="daterow"><input type="date" class="datein" min=${expiryInputVal(now_s())} max=${ownerExp ? expiryInputVal(ownerExp) : ""} value=${d} onInput=${e => setD(e.target.value)}/>${d ? html`<button class="btn btn-ghost btn-mini" onClick=${() => setD("")}>${T("Clear")}</button>` : null}</div>
  <//>`;
}
// Live footer for the QR modals — re-renders on each poll (useStore), so the Block/Unblock label flips right
// after the action without the modal being reopened. "Set expiry" sits to the LEFT of Block.
export function QRPeerFoot({ pid }) {
  useStore();
  const p = Store.peer(pid);
  if (!p) return null;
  const hasExp = !!(p.ownExpiry && p.ownExpiry > 0);
  return html`<${Fragment}><span class="grow"></span><button class=${"btn btn-exp" + (hasExp ? " on" : "")} onClick=${() => openSetExpiry("peer", pid)}><${Ic} i="clock"/> ${hasExp ? T("Reset expiry") : T("Set expiry")}</button>${peerBlockBtn(p)}<//>`;
}
export function QRUserFoot({ uid }) {
  useStore();
  const u = Store.user(uid);
  if (!u) return null;
  const hasExp = !!(u.expiry && u.expiry > 0);
  const peers = Store.peersOfUser(uid);
  const nCfg = peers.reduce((a, p) => a + ((p.targets || []).length || 0), 0);
  const count = plural(peers.length, "peer") + (nCfg > 1 ? " (" + T("{v1} configs)", { v1: nCfg }) : "");
  return html`<${Fragment}><span class="qrfoot-count">${count}</span><${UserCounts} user=${u} className="qrfoot-ucounts"/><span class="grow"></span><button class=${"btn btn-exp" + (hasExp ? " on" : "")} onClick=${() => openSetExpiry("user", uid)}><${Ic} i="clock"/> ${hasExp ? T("Reset expiry") : T("Set expiry")}</button><button class="btn btn-warn" onClick=${() => rotateAllUserKeys(u)} title=${T("Rotate the keys of every peer this user holds — all configs/links must be re-imported")}><${Ic} i="key"/> ${T("Rotate all keys")}</button>${userBlockBtn(u)}<//>`;
}
export function openUserEdit(user) {
  // Wider than the default sheet: this one carries the widest thing in the panel that is not a table — the user's networks, a row
  // per network with its node and device counts — and at 640 those rows wrapped while the fields beside them sat half empty.
  openModal(html`<${Sheet} title=${T("Edit · {v1}", { v1: user.name })} width=${780} subject=${{ kind: "user", id: user.id }}><${UserEditCard} user=${user} done=${closeModal}/><//>`);
}
// Every QR/config the user owns, grouped by peer — one horizontal row of deployment QRs per peer (the peer's
// PRIMARY deployment first, tagged, when it has more than one). Same TargetCard the peer QR modal uses, so a
// stored-config / session-config peer renders its QR and an un-stored one shows the same hint.
// The subscription URL + one-tap copy. Hovering highlights the whole row (URL + button) as a single
// click target; clicking anywhere copies. Used under the title in the user + peer QR modals.
// Shown at the top of the QR/config modals when the encryption vault is configured but not unlocked this
// session: the stored configs are ciphertext, so a peer's QR can't be rebuilt until the admin unlocks the
// key with the panel password. Unlocking caches the SK (subUnlock) and bumps configEpoch so every open
// TargetCard re-resolves via the blob. Renders nothing when there's no vault or it's already unlocked.

// The one-time "save your encryption key" moment, shown right after a vault is created — including the automatic
// setup at first sign-in, where the key used to be minted and silently discarded. It is the operator's only way
// back into their configs if the panel password is ever reset from the server, so it is deliberately a modal with
// an explicit acknowledgement rather than a toast. The key never leaves the browser; this reads the session cache.
/* Sentences that carry a STYLED run inside them (a bold warning, a bold link target). Each is one key with
   a marker, split around the styled element — see Tsplit in js/i18n.js for why this beats concatenation. */
function keyOnlyCopy() {
  const [a, b] = Tsplit("Config encryption is on. This key protects every stored client config and subscription link — the panel only ever stores it wrapped under your password, so {only}.", "only");
  return html`<${Fragment}>${a}<b>${T("this is the only copy in the clear")}</b>${b}<//>`;
}
function keyWhere() {
  const [a, b] = Tsplit("Store it in a password manager. It's what gets you back to your configs if your panel password is ever reset from the server — and anyone who holds it can read them, so treat it like a password. You can see it again any time from {where} while the vault is unlocked.", "where");
  return html`<${Fragment}>${a}<b>${T("Settings → Client configs")}</b>${b}<//>`;
}
function noVkSet(onNav) {
  const [a, b] = Tsplit("No VK call link set — configs carry a placeholder. Set it in {where}.", "where");
  return html`<${Fragment}>${a}<a href="#/panel/settings" onClick=${onNav}>${T("Panel settings → Turn proxies")}</a>${b}<//>`;
}
function noVkLinks() {
  const [a, b] = Tsplit("No VK links for this user yet — panel is using your {test} link to build turn configs. Fix before distributing.", "test");
  return html`<${Fragment}>${a}<b>${T("test")}</b>${b}<//>`;
}
function noVkSubbed() {
  const [a, b] = Tsplit("Right now their subscription page will show the turn configs {without} a VK link, so they'd have to add one in their turn app.", "without");
  return html`<${Fragment}>${a}<b>${T("without")}</b>${b}<//>`;
}
function vkLinksIntro() {
  const [a, b] = Tsplit("Each link is a VK call room the user's turn proxy pulls TURN credentials from. Mark one {primary} — apps that take a single link use it; some proxies use all of them (more links = more capacity).", "primary");
  return html`<${Fragment}>${a}<b>${T("primary")}</b>${b}<//>`;
}

export function VaultKeySheet() {
  const k = subKeyB64();
  if (!k) return null;
  return html`<${Sheet} title=${T("Save your encryption key")} width=${560} onClose=${closeModal}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-primary" onClick=${closeModal}>${T("I've saved it")}</button></>`}>
    <div class="vaultprompt">
      <p class="vp-reason">${keyOnlyCopy()}</p>
      <div class="tokenbox" style="margin:8px 0;word-break:break-all">${k}</div>
      <div class="chiprow">
        <button class="btn btn-mini" onClick=${() => copy(k, T("Encryption key copied"))}><${Ic} i="copy"/> ${T("Copy")}</button>
        <button class="btn btn-mini" onClick=${() => downloadConf(k, "swg-config-key")}><${Ic} i="download"/> ${T("Download")}</button>
      </div>
      <div class="notice warn vp-skip" style="margin-top:10px"><${Ic} i="info"/><span>${keyWhere()}</span></div>
    </div>
  <//>`;
}

export function SubUrlBar({ url }) {
  const [copied, setCopied] = useState(false);
  if (!url) return null;
  const copy = () => { (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject())
    .then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }, () => {}); };
  return html`<div class="suburl" onClick=${copy} title=${T("Copy subscription link")}>
    <${Ic} i="link"/><span class="suburl-txt">${url}</span>
    <span class=${"suburl-copy" + (copied ? " ok" : "")}><${Ic} i=${copied ? "check" : "copy"}/></span>
  </div>`;
}

// The owning user's subscription link, shown under the title in the peer QR modal. Only appears when the
// peer is assigned to a subscription-enabled user; if the Subscription Key isn't unlocked this session it
// points the operator to the user's QR view (where unlocking lives), rather than a dead control here.

// Per-user subscription control: enable/create the shareable link, show + copy it, rotate (kill the old
// link), or disable. All the crypto is client-side — enabling needs the Subscription Key, which is
// unlocked once per session with the panel password (the convenience cache). Off entirely unless the
// subscriptions feature is enabled in Settings.

export function openUserConfigs(user, back) {
  const peers = Store.peersOfUser(user.id);
  // the user modal shows ONE card per peer, so size by the peer COUNT (up to 3 across), not the widest peer's
  // deployment count — otherwise a user's modal width flip-flopped on whether any one peer had 3+ configs
  const cols = Math.min(peers.length || 1, 3);
  const wcols = Math.max(cols, 2);                        // hold 2 cards wide even for a single peer (roomier layout)
  const width = wcols * QR_ITEM + (wcols - 1) * QR_GAP + 56;
  const anyTurn = peers.some(p => targetsWantVk(p.targets));
  const title = html`<span class="qrhd"><span class="qrhd-nm">${user.name}</span>${user.tag ? html`<span class="qrhd-tag">${user.tag}</span>` : null}</span>`;
  const headExtra = html`<${SubStatusLine} user=${user} pos="hr"/>`;   // subscription status, right-aligned (the count now sits by the name)
  openModal(html`<${Sheet} title=${title} width=${width} headExtra=${headExtra} noGuard=${true} onClose=${back || closeModal}
    subject=${{ kind: "user", id: user.id }} foot=${html`<${QRUserFoot} uid=${user.id}/>`}>
    <${VaultUnlockPanel}/>
    <${SubLinkActions} user=${user}/>
    ${anyTurn ? html`<${VkLinkField} user=${user}/>` : null}
    ${peers.length ? html`<${QRRow} cards=${peers.map(p => html`<${UserPeerCard} key=${p.id} peer=${p} onOpen=${(p.targets || []).length > 1 ? () => openPeerConfigs(p, { child: true, hideVk: true }) : null}/>`)}/>`
      : html`<div class="empty" style="padding:24px">${T("This user has no peers yet.")}</div>`}
  <//>`);
}
// Turn-proxy client configs for one deployment — one section per turn-proxy on the interface, generated
// on the fly for the DEPLOYED fork. `conf` is the base WG config (needs the private key, so session/stored).
// Turn always opens FROM another modal (a peer or user QR view), so it's PUSHED — ✕/Esc/backdrop/"Back" pop
// straight back to whatever it was launched from, with that view intact.
export function openTurnConfigs(peer, t, conf) {
  pushModal(html`<${Sheet} title=${T("Turn configs · {v1}", { v1: peer.title || peer.name || T("val|peer") })} width=${560} noGuard=${true} onClose=${closeModal} onBack=${closeModal} subject=${{ kind: "peer", id: peer.id }}>
    <${TurnConfigSheet} peer=${peer} t=${t} conf=${conf}/>
  <//>`);
}
export function TurnConfigSheet({ peer, t, conf }) {
  const [selFork, setSelFork] = useState(0);
  const [inst, setInst] = useState({});   // fork → chosen instance index (for redundant same-fork proxies)
  const [selClient, setSelClient] = useState({});   // "fork|os" → chosen client-app index (servers that offer several apps on an OS)
  const [selOs, setSelOs] = useState({});   // fork → chosen device OS (which platform's app + settings to generate for)
  // One badge PER FORK; the peer's own fork (observed viaTurn) sorts first and is selected by default. When a
  // fork has several proxies (redundancy), a dropdown picks which one. Only the selected proxy's config shows.
  const lt = ((Store.recon.peers.find(p => p.id === peer.id) || {}).targets || []).find(d => d.node === t.node && d.iface === t.iface) || t;
  const all = turnProxiesFor(t.node, t.iface);
  const sorted = lt.viaTurn ? [...all].sort((a, b) => (b.service === lt.viaTurn ? 1 : 0) - (a.service === lt.viaTurn ? 1 : 0)) : all;
  const order = [], byFork = {};
  sorted.forEach(p => { const f = turnFork(p.service); if (!byFork[f]) { byFork[f] = []; order.push(f); } byFork[f].push(p); });
  const vkUser = peer.user_id ? Store.recon.users.find(u => u.id === peer.user_id) : null;
  const vk = userVkLink(vkUser);   // this user's own link, falling back to the panel test link (subs never fall back)
  const vkLinks = userVkLinks(vkUser);   // all of the user's links — forks that support several embed them all
  const base = (peer.title || peer.name || "peer") + "-" + Store.nodeName(t.node);
  if (!order.length) return html`<div class="hint">${T("No turn-proxy forwards to this interface.")}</div>`;
  const fi = Math.min(selFork, order.length - 1); const fork = order[fi];
  const list = byFork[fork]; const ii = Math.min(inst[fork] || 0, list.length - 1); const cur = list[ii];
  const cmap = (Store.turnCatalog && Store.turnCatalog.clients) || {};
  const allClients = turnClientsFor(fork);   // already compat-matrix-only and compat-ranked (see turnClientsFor); it drops dead pairings such as anton48 + VK-TURN-by-MYSOREZ, matching Settings and the sub page
  const osOf = c => Object.keys((cmap[c.id] || {}).platforms || {});
  const osList = _OS_TABS.map(([o]) => o).filter(o => allClients.some(c => osOf(c).includes(o)));   // OSes this fork's apps cover
  const curOs = (selOs[fork] && osList.includes(selOs[fork])) ? selOs[fork] : (osList[0] || "");
  const clients = allClients.filter(c => osOf(c).includes(curOs));   // apps available on the chosen OS
  const okey = fork + "|" + curOs;
  const ci = Math.min(selClient[okey] || 0, Math.max(0, clients.length - 1));
  const client = clients[ci] || null;
  const clientOsName = c => (((cmap[c.id] || {}).platforms || {})[curOs] || {}).name || c.name;   // per-OS app name (WINGS V vs WINGS DeX)
  return html`<div class="turncfg">
    ${order.length > 1 ? html`<div class="turntabs">${order.map((f, k) => html`<button key=${f}
      class=${"snbadge turntab" + (k === fi ? " on" : "")} style=${"--c:" + turnColor(f)} onClick=${() => setSelFork(k)}>${forkLabel(f)}</button>`)}</div>` : null}
    ${list.length > 1 ? html`<div class="turninst">
      <label>${T("Which {v1} proxy", { v1: forkLabel(fork) })}</label>
      <${Dropdown} className="selwrap" value=${ii} onChange=${v => setInst(m => ({ ...m, [fork]: v }))}
        ariaLabel=${T("Which {v1} proxy", { v1: forkLabel(fork) })}
        options=${list.map((p, k) => ({ value: k, label: (p.listen || ("proxy " + (k + 1))) + (p.title ? " (" + p.title + ")" : "") }))}/></div>` : null}
    ${(osList.length > 1 || clients.length > 1) ? html`<div class="turncfg-devrow">
      ${osList.length > 1 ? html`<div class="turncfg-os"><label>${T("Device")}</label><${OsDropdown} value=${curOs} options=${osList} onChange=${o => setSelOs(m => ({ ...m, [fork]: o }))}/></div>` : null}
      ${clients.length > 1 ? html`<div class="turncfg-app"><label>${T("App")}</label><${AppDropdown} value=${client ? client.id : null}
        options=${clients.map(c => { const rel = ((turnForkList().find(x => x.id === fork) || {}).compat || {})[c.id]; const isCli = (c.encoder === "sidecar" || c.id === "sidecar");
          return { id: c.id, name: clientOsName(c), author: (turnClientAuthor(c.id) || {}).fork || fork, color: turnClientColor(c.id) || turnColor(fork), nameColor: appNameColor(rel, isCli), plain: rel === "plain",
            autostart: !!((((cmap[c.id] || {}).platforms || {})[curOs] || {}).autostart) }; })}
        onChange=${id => setSelClient(m => ({ ...m, [okey]: Math.max(0, clients.findIndex(c => c.id === id)) }))}/></div>` : null}
    </div>` : null}
    ${!vk ? html`<div class="notice warn"><${Ic} i="warn"/><span>${noVkSet(() => closeAllModals())}</span></div>` : null}
    <${TurnCfgItem} key=${cur.service + "|" + (client ? client.encoder : "") + "|" + curOs} conf=${conf} tp=${cur} vk=${vk} vkLinks=${vkLinks} base=${base} client=${client} os=${curOs}/>
  </div>`;
}
// One turn-proxy's client artifact. Sync forks fill `text`; wingsv:// fills `buildAsync` (needs zlib), so
// we resolve it in an effect and show a generating placeholder until ready. A QR⇄text toggle (default QR where the
// client scans one, per `a.qr`) mirrors the sub page: in QR view the wg/awg config or link is a scannable
// QR (tap to enlarge) and Copy grabs the IMAGE; the CLI command (`a.cmd`) always stays text — you can't scan a
// shell line. Text view is the wrapping, auto-growing textarea.
export function TurnCfgItem({ conf, tp, vk, vkLinks, base, client, os }) {
  const a = turnArtifact(conf, tp, vk, vkLinks, client ? client.encoder : undefined, os);
  const [text, setText] = useState(a.text != null ? a.text : null);
  const [err, setErr] = useState(null);
  const [view, setView] = useState(a.qr ? "qr" : "text");   // default QR where the app scans one
  const taRef = useRef(null);
  useEffect(() => {
    if (a.text != null) { setText(a.text); return; }
    let ok = true; setText(null); setErr(null);
    Promise.resolve().then(a.buildAsync).then(t => { if (ok) setText(t); }).catch(e => { if (ok) setErr((e && e.message) || T("couldn't generate")); });
    return () => { ok = false; };
  }, [tp.service, conf, vk, client && client.encoder, os]);
  useEffect(() => { setView(a.qr ? "qr" : "text"); }, [tp.service, client && client.encoder]);   // reset to the default when the client changes
  useEffect(() => { if (view === "text") autoGrow(taRef.current); }, [text, view]);   // dynamic height to fit wrapped content, no scroll
  const ready = text != null;
  const qrView = a.qr && view === "qr";
  return html`<div class="turncfg-item">
    <div class="turncfg-head"><span class="tcf-label">${artLabel(a)}</span></div>
    ${a.hint ? html`<div class="hint" style="margin:2px 0 6px">${T(a.hint, a.hintArgs)}</div>` : null}
    ${err ? html`<div class="hint err">${err}</div>`
      : qrView ? (ready ? html`<div class="turncfg-qr"><${QR} conf=${text} label=${a.label}/></div>` : html`<div class="turncfg-qr qr-pending">${T("generating…")}</div>`)
      : html`<div class="turncfg-tawrap"><textarea class="turncfg-ta" readonly spellcheck="false" data-noautofocus ref=${taRef} onClick=${e => { e.target.select(); copy(text, a.uri ? T("Link copied") : T("Config copied")); }}>${ready ? text : T("generating…")}</textarea>
          <button class="cmd-copy" title=${T("Copy")} disabled=${!ready} onClick=${() => copy(text, a.uri ? T("Link copied") : T("Config copied"))}><${Ic} i="copy"/></button></div>`}
    ${a.cmd ? html`<div class="turncfg-cmd"><div class="tokenbox">${a.cmd}</div>
      <button class="cmd-copy" title=${T("Copy command")} onClick=${() => copy(a.cmd, T("Command copied"))}><${Ic} i="copy"/></button></div>` : null}
    <div class="turncfg-foot">
      ${a.qr ? html`<button class="btn btn-mini" onClick=${() => setView(v => v === "qr" ? "text" : "qr")}><${Ic} i=${qrView ? "doc" : "qr"}/> ${qrView ? T("Show config") : T("Show QR")}</button>` : null}
      <span class="grow"></span>
      <button class="btn btn-mini" disabled=${!ready} onClick=${() => qrView ? copyQrImage(text, T("QR image")) : copy(text, a.uri ? T("Link copied") : T("Config copied"))}><${Ic} i="copy"/> ${T("Copy")}</button>
      <button class="btn btn-mini" disabled=${!ready} onClick=${() => downloadConf(text, base + "-" + a.fork + (portOf(tp.listen) ? "-" + portOf(tp.listen) : ""), a.ext)}><${Ic} i="download"/> Download .${a.ext || "conf"}</button>
    </div>
  </div>`;
}

// One user as a collapsible row: status · name · tag · note · peers · last · rate · total · controls.
// Click the row to expand its peers (the shared EmbeddedPeers grid); click again to collapse.

// Inline-editable peer title (optimistic). The operator's label to tell a user's devices apart.

// NETWORKS P3 (feature 13) — what this user's devices can reach beyond the internet: networks other devices front
// on the same node, and the node's own local network. Asked for ONCE when the sheet opens, never per poll — it is a
// cross-product (docs/NETWORKS-PLAN.md §4.10). Renders nothing when there is nothing beyond the internet to show.
// ⚠️ ONE ROW PER NETWORK ON A NODE, not per deployment. It listed every deployment of every device with the networks under it,
// so a user with 8 devices read as 12 blocks, and a device's turn-server deployments (the "+3" in the peer grid) looked like
// devices of their own. Each row: the network, how it is reached, the node, and how many of this user's devices there route
// it — the devices themselves on hover, capped. Paged, so 2 rows and 200 read the same.
function UserNetworksPanel({ user }) {
  const [data, setData] = useState(null), [page, setPage] = useState(1);
  useEffect(() => {
    let ok = true;
    api.userNetworks({ user_id: user.id }).then(r => { if (ok && r && r.ok) setData(r.data); }).catch(() => {});
    return () => { ok = false; };
  }, [user.id]);
  const via = id => { const q = Store.peer(id); return q ? (q.title || q.name || T("Untitled")) : ""; };
  const devName = (p, t) => {                               // the title, else where it is: its address, or its server
    const q = Store.peer(p.peer_id), tg = q && (q.targets || []).find(x => x.node === t.node && x.iface === t.iface);
    const where = tg && tg.ip ? String(tg.ip).split("/")[0] : t.iface;
    return p.title ? p.title + " (" + where + ")" : where;
  };
  const rank = c => (c === true ? 2 : c === null ? 1 : 0);  // a device reaches it if ANY of its deployments there routes it
  const rows = new Map();
  for (const p of ((data && data.peers) || []).filter(p => !p.blocked)) for (const t of p.targets) {
    const put = (key, seed, covered) => {
      const r = rows.get(key) || Object.assign({ key, node: t.node, devs: new Map() }, seed);
      const d = r.devs.get(p.peer_id);
      if (!d) r.devs.set(p.peer_id, { name: devName(p, t), covered });
      else if (rank(covered) > rank(d.covered)) d.covered = covered;
      rows.set(key, r);
    };
    for (const n of t.networks) put(t.node + "|" + n.prefix, { prefix: n.prefix, via: n.via, restricted: !!n.restricted, until: n.until || 0 }, n.covered);
    // ⚠️ NEVER `true`: a node's LAN is reached only where this device's own routing names it, which is the panel's answer
    // in `lan.covered`. An answer from a panel that predates the field is unknown (null), never reachable.
    if (t.lan) put(t.node + "|lan", { prefix: t.lan.addrs.join(", "), lan: t.lan }, t.lan.covered === undefined ? null : t.lan.covered);
  }
  const list = [...rows.values()].sort((a, b) => Store.nodeName(a.node).localeCompare(Store.nodeName(b.node))
    || (a.lan ? 1 : 0) - (b.lan ? 1 : 0) || a.prefix.localeCompare(b.prefix));
  if (!list.length) return null;
  const pages = Math.max(1, Math.ceil(list.length / LIST_PAGE)), pg = Math.min(page, pages);
  // ⚠️ OWNERSHIP IS ASKED FIRST. `share_grants` always puts the owner into its own grant list, so a restricted device of
  // this user's own granted to them and the row read "shared with this user" — about their own device. It is not shared
  // with them; it is theirs, and it sits behind one of their own devices.
  const ownDev = r => { const p = r.via ? Store.peer(r.via) : null; return !!(p && p.user_id === user.id); };
  // Which of their devices it sits behind — "their own device" alone left the operator to go and look it up. The address
  // is the one that device answers on THIS node, since that is the deployment carrying the network.
  const devOf = r => {
    const p = r.via ? Store.peer(r.via) : null;
    if (!p) return "";
    return deviceNameAt(p, r.node);
  };
  // WHO opened it, not just that it is open: "shared with this user" said nothing about whom to go to in order to change it.
  const sharerOf = r => { const p = r.via ? Store.peer(r.via) : null; const u = p && p.user_id ? Store.user(p.user_id) : null; return u ? u.name : ""; };
  const how = r => r.lan ? (r.lan.open ? T("the node's local network") : T("the node's local network, closed"))
    : ownDev(r) ? T("behind their own device {v1}", { v1: devOf(r) })
      : r.restricted ? (sharerOf(r)
        ? (r.until ? T("shared by {v1} until {date}", { v1: sharerOf(r), date: fmtDate(r.until) }) : T("shared by {v1}", { v1: sharerOf(r) }))
        : (r.until ? T("shared until {date}", { date: fmtDate(r.until) }) : T("shared with this user")))
        : T("open to everyone on the node");
  const row = r => {
    const devs = [...r.devs.values()], node = Store.nodeName(r.node);
    const ok = devs.filter(d => d.covered === true).length, no = devs.filter(d => d.covered === false).length;
    const unk = devs.length - ok - no;
    const state = d => d.covered === true ? T("reachable") : d.covered === false ? T("not in this device's routing") : T("routing unknown");
    const cls = d => d.covered === true ? "ok" : d.covered === false ? "soon" : "off";
    return html`<div class="unet" key=${r.key}>
      <span class=${"mono unet-p" + (r.lan && !r.lan.open ? " off" : "")}>${r.prefix}</span>
      <span class="unet-how">${how(r)}</span>
      <span class="nm unet-node" style=${"color:" + (Store.nodeColor(r.node) || "var(--ink)")}>${node}</span>
      <span class="grow"></span>
      <${Popover} hoverOnly cls="netcount-pop" popCls="netroute-bub" trigger=${html`<span class="netcount"
          aria-label=${T("{total} of this user's devices on {node}: {ok} reach it, {no} leave it out of their routing, {unk} unknown", { total: devs.length, node, ok, no, unk })}>
        ${ok ? html`<span class="n ok">${ok}</span>` : null}${no ? html`<span class="n soon">${no}</span>` : null}${unk ? html`<span class="n unk">${unk}</span>` : null}</span>`}>
        <span class="netroute-h">${T("{prefix} on {node}", { prefix: r.prefix, node })}</span>
        ${r.via ? html`<div class="netbub-row">${T("Through {via}", { via: via(r.via) })}</div>` : null}
        <${CapList} items=${devs} cap=${10} row=${d => html`<div class=${"netbub-row nb-dot " + cls(d)} key=${d.name}><b>${d.name}</b> <span class="faint">${state(d)}</span></div>`}/>
      <//>
    </div>`;
  };
  return html`<div class="field"><label>${T("Networks this user can reach")}</label>
    <div class="unets">${pageSlice(list, pg).map(row)}</div>
    <${ListPager} page=${pg} setPage=${setPage} total=${list.length}/>
    <div class="hint">${T("Worked out when this sheet opens. A device whose routing leaves a network out can be widened from its own settings.")}</div></div>`;
}

// ── USER GROUPS (docs/GROUPS-PLAN.md G11) ────────────────────────────────────────────────────────────────────────────────────────
// A user's groups on their sheet: chips that open each group, six shown and the rest counted with the names on hover — and, on the
// label's own line, the way IN. Putting someone in a group used to mean leaving this sheet for Users → Groups, opening the group
// and searching for them there: the one screen that knows who this person is could not do the one thing you came to it for. The
// list offers the groups they are NOT in, and ends with a new group that opens already holding them.
// A type-to-filter GROUP picker for a person's sheet. It replaced a Dropdown listing every group there is — five rows on this
// fleet, and 200 groups rendered one 7,300px list with nothing to search it by (measured, 1.8.7 qualification §C9). The first
// matches, how many more there are, and "Create new group…" always last and always in view, the way UserPicker offers people.
function GroupCombo({ groups, onPick, onCreate, disabled }) {
  const [q, setQ] = useState(""); const [open, setOpen] = useState(false);
  const hits = groups.filter(g => searchMatch(g.name, q.toLowerCase()));
  const shown = hits.slice(0, 6);   // six, not UserPicker's eight: with the count line and "Create new group…" the list then fits unscrolled (.uc-groups)
  const { wrapRef, listRef, pos, popStyle } = useAnchoredList(open, setOpen, [q]);
  const done = () => { setOpen(false); setQ(""); };
  const inRef = useRef(null);
  // the whole pill is the control — its "+" included, which opened nothing when only the field inside it listened
  const openFromPill = e => { if (disabled || e.target === inRef.current) return; setOpen(true); if (inRef.current) inRef.current.focus(); };
  return html`<div class=${"usercombo ugroup-combo" + (open ? " open" : "")} ref=${wrapRef} onClick=${openFromPill}>
    <${Ic} i="plus"/>
    ${/* ⚠️ type=search, autocomplete=off: this sheet also holds the vault's password field, and Chrome filled the text input
          before it with the SAVED LOGIN — the picker opened reading "snproto" (measured). A search field is not a username. */""}
    ${/* The pill is as wide as its words, in either language, and never narrower than them while you type: the field shares a
          grid cell with invisible copies of the label and of the query, so it takes the wider of the two (.uc-size). It was a fixed 170 px, which left
          the English label off-centre with a gap after it (operator, 2026-09-17). */""}
    <span class="uc-size" data-l=${T("Add to a group")} data-q=${q}><input ref=${inRef} class="uc-input" type="search" size="1" autocomplete="off" value=${q} disabled=${disabled} placeholder=${T("Add to a group")} aria-label=${T("Add to a group")}
      onClick=${() => setOpen(true)} onInput=${e => { setQ(e.target.value); setOpen(true); }}
      onKeyDown=${e => { if (e.key === "Escape") { done(); return; }
        // while the list is open Enter never saves the sheet: exactly one match picks it, anything else does nothing
        if (e.key === "Enter" && open) { e.preventDefault(); if (q && hits.length === 1) { done(); onPick(hits[0].id); } } }}/></span>
    ${open && pos ? html`<${Portal}><div class="uc-list uc-pop uc-groups" ref=${listRef} style=${popStyle}>
      ${shown.map(g => html`<button class="uc-opt uc-group" key=${g.id} onClick=${() => { done(); onPick(g.id); }}><${Ic} i="users"/><span>${g.name}</span><span class="faint">${plural(g.users.length, "member")}</span></button>`)}
      ${hits.length > shown.length ? html`<div class="uc-empty">${T("{v1} more — type to narrow", { v1: hits.length - shown.length })}</div>`
        : hits.length ? null : html`<div class="uc-empty">${T("no match")}</div>`}
      <button class="uc-opt uc-new" onClick=${() => { done(); onCreate(); }}>${T("Create new group…")}</button>
    </div><//>` : null}
  </div>`;
}
function UserGroupsField({ user }) {
  // ⚠️ OPTIMISTIC. A membership is one delta against a roster that only refreshes on the next poll, so waiting for the
  // round trip left a badge sitting there after it had been removed — the click looked ignored. `pend` holds what this
  // sheet has just done, is applied over the store's answer, and each entry clears itself the moment the roster agrees;
  // a refusal puts it straight back and says so, so the optimism is never a lie that outlives the request.
  const [pend, setPend] = useState({});          // gid -> "in" | "out"
  const base = Store.groupsByUser(user.id);
  const baseIds = new Set(base.map(g => g.id));
  useEffect(() => {
    const next = {};
    for (const [gid, want] of Object.entries(pend)) if ((want === "in") !== baseIds.has(gid)) next[gid] = want;
    if (Object.keys(next).length !== Object.keys(pend).length) setPend(next);
  });
  const mine = [...base.filter(g => pend[g.id] !== "out"),
    ...Object.keys(pend).filter(gid => pend[gid] === "in" && !baseIds.has(gid)).map(gid => Store.group(gid)).filter(Boolean)]
    .sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const rest = mine.slice(6);
  const [busy, setBusy] = useState(false);
  const mineIds = new Set(mine.map(g => g.id));
  const others = Store.groups().filter(g => !mineIds.has(g.id));
  const write = async (call, ok, gid, want) => {
    if (busy) return;
    setBusy(true);
    if (gid) setPend(p => ({ ...p, [gid]: want }));       // show it at once
    let r = null;
    try { r = await call(); } catch (e) { r = null; }
    setBusy(false);
    if (r && r.ok) { toast(ok, "ok"); Store.poll(); }
    else {
      if (gid) setPend(p => { const n = { ...p }; delete n[gid]; return n; });   // refused → put it back
      toast(srvText(r) || T("The group wasn't saved."), "err");
    }
  };
  const add = v => {
    if (v === "__new") { openCreateGroup([user.id]); return; }
    const g = Store.group(v);
    if (g) write(() => api.groupUpdate({ id: v, add: [user.id] }), T("{name} is now in {group}.", { name: user.name, group: g.name }), v, "in");
  };
  // ⚠️ Taking someone OUT takes away what the group grants, so a group that grants networks asks first — the same sentence the
  // group's own delete uses, because it is the same loss. A group that grants nothing just goes.
  const drop = g => {
    const go = () => write(() => api.groupUpdate({ id: g.id, remove: [user.id] }),
      T("{name} is no longer in {group}.", { name: user.name, group: g.name }), g.id, "out");
    const shares = groupShares(g.id);
    if (!shares.length) return go();
    openConfirm({ title: T("Remove {name} from the group", { name: user.name }), confirmLabel: T("Remove"), danger: true,
      body: T("They lose the networks shared with this group, unless they're shared with them another way: {devices}.",
              { devices: namedFew(shares.map(shareDeviceName)) }),
      onConfirm: go });
  };
  return html`<div class="field ugroups-field">
    <label>${T("Groups")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— members reach each other's devices, and a network can be shared with the group")}</span></label>
    <div class="ugroups">
      ${/* The badges wrap inside their OWN box: with the control as a sibling of the pills it wrapped to a line of its own the
            moment there were more than a few, which is the opposite of sitting with them. */""}
      <div class="ugroups-list">
        ${mine.slice(0, 6).map(g => html`<span class="ugroup" key=${g.id}>
          <button type="button" class="ugroup-nm" onClick=${() => openGroup(g.id)}><${Ic} i="users"/><span>${g.name}</span></button>
          ${/* The same × every other tag in the panel is removed by (.tfb-x, the routing rule builder's): faint until
                hovered, then a red wash. The circled `iconbtn danger` it used to be was a control this panel uses
                nowhere else for taking a tag off. */""}
          <button type="button" class="tfb-x ugroup-x" disabled=${busy} title=${T("Remove {name} from the group", { name: user.name })}
            aria-label=${T("Remove {name} from the group", { name: user.name })} onClick=${() => drop(g)}><${Ic} i="x"/></button>
        </span>`)}
        ${rest.length ? html`<${Popover} hoverOnly cls="ugroup-pop" popCls="netroute-bub" trigger=${html`<span class="ugroup more">+${rest.length}</span>`}>
          <${CapList} items=${rest} cap=${10} row=${g => html`<div class="netbub-row" key=${g.id}>${g.name}</div>`}/>
        <//>` : null}
        ${mine.length ? null : html`<span class="ugroups-none">${T("Not in any group.")}</span>`}
      </div>
      ${/* The way in sits with the badges, at the right of their first line. With groups left to join it opens that list
            (ending in a new one); with none, there is nothing to list — so it opens the new-group window itself. */""}
      ${others.length
        ? html`<${GroupCombo} groups=${others} disabled=${busy} onPick=${add} onCreate=${() => openCreateGroup([user.id])}/>`
        : html`<button type="button" class="ugroup-add-btn" disabled=${busy} onClick=${() => openCreateGroup([user.id])}>
            <${Ic} i="plus"/>${T("Add to a group")}</button>`}
    </div>
  </div>`;
}

// ⚠️ A BUBBLE'S BODY IS A COMPONENT, not inline markup: Popover is handed its children already built, so anything written inline
// here would be computed for every row of the list on every poll. As a component it renders only while the bubble is open.

// Who this person's devices can open connections to: each person, then their devices, online ones lit. Group NAMES used to be
// listed here and said nothing — a group is a means, and what an operator is looking for is who ends up reaching whom.
function ReachBody({ user }) {
  const rows = userReach(user.id);
  const anyOnline = rows.some(r => r.online);
  // Open on what is live when anything is: an operator looking at a lit chip is asking who is reachable NOW. With nothing
  // online there is no such question, so it opens on everything rather than on an empty list. Mounted per opening, so the
  // default is decided each time the bubble is shown.
  const [all, setAll] = useState(!anyOnline);
  const show = all ? rows : rows.filter(r => r.online);
  const devs = r => (all ? r.devices : r.devices.filter(d => d.online));
  const count = r => (r.online && r.online !== r.devices.length
    ? T("{v1} ({v2} online)", { v1: plural(r.devices.length, "device"), v2: r.online })
    : plural(r.devices.length, "device"));
  return html`<${Fragment}>
    <div class="rb-head"><span class="netroute-h">${T("Can reach")}</span><span class="grow"></span>
      ${anyOnline ? html`<div class="dpsw rb-sw" role="radiogroup" aria-label=${T("Can reach")}>
        <button type="button" role="radio" aria-checked=${!all} class=${!all ? "on" : ""} onClick=${() => setAll(false)}>${T("Online")}</button>
        <button type="button" role="radio" aria-checked=${all} class=${all ? "on" : ""} onClick=${() => setAll(true)}>${T("filter|All")}</button>
      </div>` : null}</div>
    ${show.length ? html`<${CapList} items=${show} cap=${8} row=${r => html`<div class="rb-grp" key=${r.user.id}>
      <div class="rb-u"><b>${r.user.name}</b><span class="grow"></span><span class="faint">${count(r)}</span></div>
      <${CapList} items=${devs(r)} cap=${6} row=${d => html`<div class="rb-d" key=${d.peer.id}>
        <span class=${"nb-dot2 " + (d.online ? "on" : "idle")}></span>
        <b>${deviceNameAt(d.peer, d.node)}</b>
        <span class="faint">${T("prep|on")}</span>
        <span class="nb-node" style=${"color:" + (Store.nodeColor(d.node) || "var(--dim)")}>${Store.nodeName(d.node)}</span>
      </div>`}/>
    </div>`}/>` : html`<div class="netbub-row sub">${T("Nobody — no shared group, and no interface here is open to everyone.")}</div>`}
  <//>`;
}

// Who reaches the networks behind ONE device — the inverse of the bubble above, hung off every networks indicator (the grid's
// chip and the peer view's badge). ⚠️ SHARING IS PER DEVICE, NOT PER NETWORK, so this is ONE audience rather than one per
// prefix: its owner alone, everyone on the node, or the people and groups it was shared with. Each grantee is shown what the
// grant is actually worth — devices on a node this one is deployed to, since reach is judged per node and a grantee whose
// devices are all elsewhere reaches nothing.
export function ReachedByBody({ peer, blocked, down, onView }) {
  useStore();
  const rep = peerAudCached(peer.id);
  useEffect(() => { peerAudFetch(peer.id); }, [peer.id]);
  const a = peerAudience(peer);
  const until = u => (u ? html`<span class="faint">${T("until {date}", { date: fmtDate(u) })}</span>` : null);
  // ⚠️ The NODE'S verdict outranks the roster's intent: one that cannot restrict carries a restricted network for nobody, so
  // naming its grantees without saying this would be confidently wrong. Asked, never assumed.
  const cantShare = ((rep && rep.targets) || []).filter(t => t.can_share === false).map(t => Store.nodeName(t.node));
  return html`<${Fragment}>
    <div class="rb-head"><span class="netroute-h">${T("Can be reached by")}</span><span class="grow"></span>
      ${onView ? html`<button type="button" class="btn btn-mini" onClick=${onView}>${T("View")}</button>` : null}</div>
    ${(peer.routes || []).length ? html`<div class="rb-d"><b class="mono">${(peer.routes || []).join(", ")}</b></div>` : null}
    ${blocked ? html`<div class="netbub-row sub">${T("Blocked — nothing reaches these through it.")}</div>`
      : down ? html`<div class="netbub-row sub">${T("Offline — nothing reaches these until it reconnects.")}</div>` : null}
    <div class="rb-grp">
      ${a.mode === "everyone" ? html`<div class="rb-u"><b>${T("Anyone on {v1}", { v1: namedFew(a.nodes.map(n => Store.nodeName(n))) })}</b></div>`
        : a.mode === "owner" ? html`<div class="rb-u"><b>${a.owner ? T("Only {v1}'s devices", { v1: a.owner.name }) : T("Only its owner's devices")}</b>
            ${a.private ? html`<span class="grow"></span><span class="tg tg-priv">${T("tag|private")}</span>` : null}</div>`
        // ⚠️ NO DOTS HERE. A grant is not a connection: a green dot beside a name would read as "online" when all it means
        // is "allowed". The number beside each name is the honest signal — devices on a node this one is deployed to, so a
        // grant worth nothing shows as 0 rather than looking the same as one that works.
        : html`<${Fragment}>
          <div class="rb-u"><b>${T("Shared with")}</b><span class="grow"></span><span class="faint">${a.owner ? T("owner: {v1}", { v1: a.owner.name }) : ""}</span></div>
          <${CapList} items=${a.users} cap=${8} row=${u => html`<div class=${"rb-d" + (u.devices ? "" : " none")} key=${u.id}><b>${u.name}</b>
            <span class="faint">${plural(u.devices, "device")}</span>${until(u.until)}</div>`}/>
          <${CapList} items=${a.groups} cap=${6} row=${g => html`<div class="rb-d" key=${g.id}><b>${g.name}</b>
            <span class="faint">${T("group · {v1}", { v1: plural(g.members, "member") })}</span>${until(g.until)}</div>`}/>
        <//>`}
    </div>
    ${cantShare.length ? html`<div class="netbub-row sub foot">${T("{v1} can't restrict who reaches a network, so it carries these for nobody.", { v1: namedFew(cantShare) })}</div>` : null}
  <//>`;
}

// The networks they reach, as the PANEL answers it — the same list their sheet shows, with the device each network sits behind.
function NetsBody({ user }) {
  const [, force] = useState(0);
  const hit = netsCached(user.id);
  useEffect(() => { if (!hit) netsFetch(user.id).then(() => force(x => x + 1)); }, [user.id]);
  // ⚠️ THE REACH BUBBLE'S RULE, for the chip that now says the same thing: open on what is live when anything is, on everything
  // when nothing is. The choice is decided when the rows are KNOWN, not at mount — a bubble opened before its answer lands
  // would otherwise have settled on "all" while it still read "Loading…".
  const rows = hit ? hit.rows : [];
  const anyOnline = rows.some(netRowOnline);
  const [pick, setPick] = useState(null);
  const all = pick == null ? !anyOnline : pick;
  const [shown, more] = useCapped(all ? rows : rows.filter(netRowOnline), 12);   // before the early return: a hook runs on every render
  if (!hit) return html`<${Fragment}><span class="netroute-h">${T("Networks")}</span>
    <div class="netbub-row sub">${T("Loading…")}</div><//>`;
  // ⚠️ GROUPED BY HOW THEY GET IT, and "how" is the heading rather than a phrase buried mid-row — so every row can then be
  // the same shape: prefix, the device carrying it, the node. ⚠️ The first bucket used to read "shared with this user",
  // which was WRONG for a user's own device: `share_grants` always puts the owner in its own grant list, so a restricted
  // device of theirs granted to them and the row repeated it back. Ownership is asked BEFORE sharing is.
  const ownerOf = r => (r.via ? Store.peer(r.via) : null);
  const mine = r => { const p = ownerOf(r); return !!(p && p.user_id === user.id); };
  const BUCKETS = [
    [T("This user's networks"), r => !r.lan && mine(r)],
    [T("Shared with this user"), r => !r.lan && !mine(r) && r.restricted],
    [T("Open to everyone on the node"), r => !r.lan && !mine(r) && !r.restricted],
    [T("The node's own local network"), r => !!r.lan],
  ];
  // One dot, reachability first (operator's choice): a network this user's devices do not route is unreachable whatever the
  // device carrying it is doing, and that is the thing worth seeing first. Otherwise it is live or not by `netRowOnline` — the
  // rule the chip counts with, so a green dot here is exactly one of the chip's online number.
  const dot = r => r.covered === false ? "no" : r.covered == null ? "unk" : netRowOnline(r) ? "on" : "idle";
  const dotTitle = r => r.covered === false ? T("Not in this user's routing — they can't reach it")
    : r.covered == null ? T("Routing unknown — this device's build doesn't say") : "";
  const row = r => {
    const dev = ownerOf(r);
    // Their own device is named by its title (they can see and edit it); anyone else's is named by WHOSE it is.
    const who = mine(r) ? deviceNameAt(dev, r.node) : ownerNameAt(dev, r.node);
    return html`<div class="nb-row" key=${r.node + r.prefix}>
      <span class=${"nb-dot2 " + dot(r)} title=${dotTitle(r)}></span>
      <b class="mono">${r.prefix}</b>
      ${dev ? html`<span class="faint">${T("via")}</span><span class=${"rb-dev" + (netRowOnline(r) ? " on" : "")} title=${who}>${who}</span>` : null}
      <span class="faint">${T("prep|on")}</span>
      <span class="nb-node" style=${"color:" + (Store.nodeColor(r.node) || "var(--dim)")}>${Store.nodeName(r.node)}</span>
      ${r.until ? html`<span class="faint">${T("until {date}", { date: fmtDate(r.until) })}</span>` : null}
    </div>`;
  };
  return html`<${Fragment}>
    <div class="rb-head"><span class="netroute-h">${T("Networks")}</span><span class="grow"></span>
      ${anyOnline ? html`<div class="dpsw rb-sw" role="radiogroup" aria-label=${T("Networks")}>
        <button type="button" role="radio" aria-checked=${!all} class=${!all ? "on" : ""} onClick=${() => setPick(false)}>${T("Online")}</button>
        <button type="button" role="radio" aria-checked=${all} class=${all ? "on" : ""} onClick=${() => setPick(true)}>${T("filter|All")}</button>
      </div>` : null}</div>
    ${rows.length ? BUCKETS.map(([label, inBucket]) => {
      const rs = shown.filter(inBucket);
      return rs.length ? html`<div class="nb-group" key=${label}>
        <div class="nb-group-h">${label}</div>${rs.map(row)}</div>` : null;
    }) : html`<div class="netbub-row sub">${T("Nothing beyond the internet.")}</div>`}
    ${more}
  <//>`;
}

// The two things a LIST can say about a person: who their devices reach, and which networks they reach. Same chip and bubble as
// the Groups screen's counts, so one fact reads the same wherever it appears. A zero count renders nothing — a row of zeroes on
// every line is noise. ⚠️ The networks count is the roster's own (their devices' networks + what is shared with them) until the
// bubble has been opened once; from then on it is the panel's number, which is what the user's sheet shows.
export function UserCounts({ user, className }) {
  useStore();                                     // both the batch and netsFetch() emit when an answer lands
  useEffect(() => { wantNetsCount(user.id); });   // this row asks for its own number; the asks go out as one request
  // The chip counts DEVICES, and says the number worth acting on: online while any are, otherwise all of them. It is lit
  // in the same case, which is what tells you the bubble will open on the live ones.
  const reach = reachTally(user.id);
  const people = reach.shown;
  // The networks chip says it the same way (operator, 2026-09-17): the online count, lit in the connection colour, while any
  // network is live; otherwise all of them — and its bubble opens on the same set. The panel's rows the moment they are known,
  // never replaced by the roster's guess afterwards; the guess is only what the very first paint shows, and cannot say what is
  // live, so it is never lit.
  const nt = netTally(user.id);
  const nets = nt.shown;
  if (!people && !nets) return null;
  // ⚠️ title="" ON PURPOSE. The user ROW carries title="Double-click for QR / configs", and a title on an ancestor is
  // what the browser shows over every descendant — so hovering these chips raised a caption about something else
  // entirely, on top of the bubble they do open. An empty title on the way down suppresses it.
  return html`<span class=${"ucounts" + (className ? " " + className : "")} title="" onClick=${e => e.stopPropagation()}>
    ${people ? html`<${Popover} hoverOnly cls="grp-pop" popCls="netroute-bub netbub-wide"
      trigger=${html`<span class=${"grp-n" + (reach.online ? " lit" : "")} data-chip="reach" aria-label=${reach.online
        ? T("Can reach {v1} online now", { v1: plural(reach.online, "device") })
        : T("Can reach {v1}, none online", { v1: plural(reach.total, "device") })}><${Ic} i="users"/>${people}</span>`}>
      <${ReachBody} user=${user}/>
    <//>` : null}
    ${nets ? html`<${Popover} hoverOnly cls="grp-pop" popCls="netroute-bub netbub-wide"
      trigger=${html`<span class=${"grp-n" + (nt.online ? " lit-net" : "")} data-chip="networks" aria-label=${nt.online
        ? T("Reaches {v1} online now", { v1: plural(nt.online, "network") })
        : T("Reaches {v1}, none online", { v1: plural(nt.total, "network") })}><${Ic} i="network"/>${nets}</span>`}>
      <${NetsBody} user=${user}/>
    <//>` : null}
  </span>`;
}

// One group: its name and its members, saved as ONE change — a rename plus an add/remove delta against the members this window
// opened with, so two operators editing one group never undo each other. The members are the People window's list: search to add,
// a filter past a page, 15 rows a page. When networks are shared with the group, the window says what adding or removing does.
export function openGroup(gid) { (modalDepth() > 0 ? pushModal : openModal)(html`<${GroupSheet} gid=${gid}/>`); }
// `seed` are the members a new group opens with — the user whose sheet asked for it. It is also wired straight to a click handler
// ("New group" on the Groups screen), so anything that is not a list of ids is no seed at all.
export function openCreateGroup(seed) {
  const ids = Array.isArray(seed) ? seed : [];
  (modalDepth() > 0 ? pushModal : openModal)(html`<${GroupSheet} gid=${null} seed=${ids}/>`);
}
export function confirmDeleteGroup(g, inSheet) {
  const shares = groupShares(g.id);
  openConfirm({ title: T("Delete group · {name}", { name: g.name }), confirmLabel: T("Delete group"), danger: true,
    body: T("Its members stay as users; only the group is deleted.") + (shares.length ? " " + T("Networks shared with it stop being reachable for its members, unless they're shared with them another way: {devices}.",
      { devices: namedFew(shares.map(shareDeviceName)) }) : ""),
    onConfirm: async () => {
      let r = null;
      try { r = await api.groupDelete({ id: g.id }); } catch (e) { r = null; }
      // only a delete that happened closes the group window — a failed one keeps it, and whatever was being edited in it
      if (r && r.ok) { closeModals(inSheet ? 2 : 1); toast(T("Group deleted."), "ok"); Store.poll(); }
      else { closeModal(); toast(srvText(r) || T("The group wasn't deleted."), "err"); Store.poll(); }
    } });
}
// A member's devices the rest of the group can reach: the number, and the devices on hover (the users grid's reach bubble idiom).
// ⚠️ The bubble body is a component: the member list pages 15 rows and each row would otherwise build its list on every poll.
function GroupMemberDevices({ uid, name }) {
  const devs = reachableByGroup(uid);
  const all = Store.peersByUser(uid).filter(p => !p.unassigned).length;
  const aria = T("{name}: {n} the group can reach, of {total}", { name, n: plural(devs.length, "device"), total: all });
  if (!devs.length) return html`<span class="faint gmem-dev" aria-label=${aria}>${T("none the group can reach")}</span>`;
  return html`<${Popover} hoverOnly cls="grp-pop gmem-pop" popCls="netroute-bub netbub-wide" trigger=${html`<span class="faint gmem-dev" aria-label=${aria}>${plural(devs.length, "device")}</span>`}>
    <${GroupMemberDevicesBody} devs=${devs} all=${all}/>
  <//>`;
}
function GroupMemberDevicesBody({ devs, all }) {
  return html`<${Fragment}>
    <span class="netroute-h">${T("Devices the group can reach")}</span>
    <${CapList} items=${devs} cap=${6} row=${d => html`<div class="rb-d" key=${d.peer.id}>
      <span class=${"nb-dot2 " + (d.online ? "on" : "idle")}></span>
      <b>${deviceNameAt(d.peer, d.node)}</b>
      <span class="faint">${T("prep|on")}</span>
      <span class="nb-node" style=${"color:" + (Store.nodeColor(d.node) || "var(--dim)")}>${Store.nodeName(d.node)}</span>
    </div>`}/>
    ${all > devs.length ? html`<div class="netbub-row sub foot">${T("{n} not counted: Private, or on an interface that doesn't let others in.", { n: plural(all - devs.length, "device") })}</div>` : null}
  <//>`;
}

function GroupSheet({ gid, seed }) {
  useStore();
  const g = gid ? Store.group(gid) : null;
  const base = useRef(null);
  if (base.current === null) base.current = { name: g ? g.name : "", users: g ? g.users.slice() : [] };
  // A new group opens holding whoever asked for it (a user's sheet), as an unsaved change against an empty group — so Cancel
  // leaves nothing behind and Create sends them as its members.
  const [name, setName] = useState(base.current.name);
  const [members, setMembers] = useState(() => (gid ? base.current.users : (seed || [])).slice());
  const [q, setQ] = useState(""), [page, setPage] = useState(1), [err, setErr] = useState(""), [busy, setBusy] = useState(false);
  const dirtyRef = useRef(false), closeRef = useRef(null), cleanRef = useRef(null);
  const nameOf = new Map(Store.recon.users.map(u => [u.id, u.name]));      // one pass, not a search per member per comparison
  const uname = id => nameOf.get(id) || "";
  const byName = (a, b) => uname(a).localeCompare(uname(b));
  const list = members.filter(id => nameOf.has(id)).sort(byName);
  const add = list.filter(u => !base.current.users.includes(u)), remove = base.current.users.filter(u => !members.includes(u));
  dirtyRef.current = name.trim() !== base.current.name || add.length > 0 || remove.length > 0;
  if (gid && !g) return html`<${Sheet} title=${T("Group · {name}", { name: base.current.name })}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>${T("Close")}</button><//>`}>
    <div class="empty"><b>${T("This group no longer exists.")}</b></div><//>`;
  const ql = q.trim().toLowerCase();
  const rows = ql ? list.filter(id => uname(id).toLowerCase().includes(ql)) : list;
  const pages = Math.max(1, Math.ceil(rows.length / LIST_PAGE)), pg = Math.min(page, pages);
  const addOne = id => {
    if (!id || members.includes(id)) return;
    setMembers(m => [...m, id]); setQ("");
    setPage(Math.floor([...list, id].sort(byName).indexOf(id) / LIST_PAGE) + 1);   // to the page the new member lands on
  };
  const drop = id => setMembers(m => m.filter(x => x !== id));
  // Sheet marks itself dirty on ANY input; the filter and the person search change nothing, so they hand the guard back (§18.1).
  const typedOnly = () => { if (cleanRef.current) cleanRef.current(); };
  const shares = gid ? groupShares(gid) : [];
  const save = async () => {
    const nm = name.trim();
    if (!nm) { setErr(T("Give the group a name.")); return; }
    setBusy(true); setErr("");
    let r = null;
    try {
      r = gid ? await api.groupUpdate({ id: gid, ...(nm !== base.current.name ? { name: nm } : {}), add, remove })
              : await api.groupCreate({ name: nm, users: list });
    } catch (e) { r = null; }
    setBusy(false);
    if (!r || !r.ok) { setErr(srvText(r) || T("The group wasn't saved.")); return; }
    dirtyRef.current = false; if (cleanRef.current) cleanRef.current();
    toast(gid ? T("Group saved.") : T("Group created."), "ok");
    closeModal(); Store.poll();
  };
  return html`<${Sheet} title=${gid ? T("Group · {name}", { name: base.current.name }) : T("New group")} width=${620}
    dirtyRef=${dirtyRef} closeRef=${closeRef} cleanRef=${cleanRef}
    foot=${html`<${Fragment}>
      ${gid ? html`<button class="btn btn-danger" onClick=${() => confirmDeleteGroup(g, true)}><${Ic} i="trash"/> ${T("Delete group")}</button>` : null}
      <span class="grow"></span>
      <button class="btn btn-ghost" onClick=${() => (closeRef.current ? closeRef.current() : closeModal())}>${T("Cancel")}</button>
      <button class="btn btn-primary" disabled=${busy || !name.trim() || (gid && !dirtyRef.current)} onClick=${save}>${gid ? T("Save") : T("Create group")}</button><//>`}>
    <div class="field"><label>${T("Name")}</label><input value=${name} maxlength="64" placeholder=${T("Ivanov family")} onInput=${e => setName(e.target.value)}/></div>
    <div class="field"><label>${T("Members")} <span class="faint gcount">${list.length}</span></label>
      <div class="sharebar" onInput=${typedOnly} onChange=${typedOnly}>
        <div class="sharebar-add"><${UserPicker} value=${null} placeholder=${T("Add a person…")} exclude=${list} onChange=${addOne}/></div>
        ${list.length > LIST_PAGE ? html`<input class="sharebar-filter" value=${q} data-enter="self" placeholder=${T("Filter the list…")}
          aria-label=${T("Filter the list…")} onInput=${e => { setQ(e.target.value); setPage(1); }}/>` : null}
      </div>
      ${list.length ? html`<div class="sharegrid gmembers" role="table">
          ${pageSlice(rows, pg).map(id => { const u = Store.user(id) || {};
            return html`<div class="sharegrid-r" role="row" key=${id}>
            <span class="nm">${uname(id)}${u.tag ? html`<span class="tagchip">${u.tag}</span>` : null}</span>
            <${GroupMemberDevices} uid=${id} name=${uname(id)}/>
            <span><button type="button" class="iconbtn danger" title=${T("Remove {name} from the group", { name: uname(id) })}
              aria-label=${T("Remove {name} from the group", { name: uname(id) })} onClick=${() => drop(id)}><${Ic} i="x"/></button></span></div>`; })}
          ${!rows.length ? html`<div class="sharegrid-empty">${T("Nobody on the list matches “{q}”.", { q })}</div>` : null}
        </div>
        <${ListPager} page=${pg} setPage=${setPage} total=${rows.length}/>`
      : html`<div class="sharegrid-empty gempty">${T("No members yet — add people with the search above.")}</div>`}
    </div>
    ${shares.length ? html`<div class="hint">${T("Networks shared with this group: {devices}. Everyone you add reaches them; anyone you remove loses them, unless they're shared with them another way.",
      { devices: namedFew(shares.map(shareDeviceName)) })}</div>` : null}
    ${err ? html`<div class="formmsg err">${err}</div>` : null}
  <//>`;
}

export function UserEditCard({ user, done }) {
  useStore();          // re-render on poll, so the Block/Unblock button flips after the action without reopening
  const [name, setName] = useState(user.name || "");
  const [tag, setTag] = useState(user.tag || "");
  const [note, setNote] = useState(user.note || "");
  const [expDate, setExpDate] = useState(expiryInputVal(user.expiry || 0));   // subscription expiry (blank = never)
  const showVk = Store.peersOfUser(user.id).some(p => targetsWantVk(p.targets));   // a peer behind a turn-proxy, or on a WDTT server
  const dirty = name !== (user.name || "") || tag !== (user.tag || "") || note !== (user.note || "") || expDate !== expiryInputVal(user.expiry || 0);   // VK links save on their own (VkLinkField) → not part of this
  const save = async () => {
    if (!name.trim()) { toast(T("Name can't be empty."), "err"); return; }
    const expSec = expiryFromInput(expDate);
    // A subscription can't expire before its longest-lived peer (the server enforces this too — check here for a
    // clean message instead of a rejected save).
    const maxPeer = Store.peersOfUser(user.id).reduce((m, p) => Math.max(m, +(p.ownExpiry || 0)), 0);
    if (expSec && maxPeer && expSec < maxPeer) { toast(T("Subscription expiry can't be earlier than a peer's expiry ({date}).", { date: fmtDate(maxPeer) }), "err"); return; }
    done();   // close the editor immediately; the row updates optimistically  (VK links are owned by VkLinkField — saved on their own)
    mutate({
      key: "user:" + user.id,
      patch: s => { const u = s.roster.users[user.id]; if (u) { u.name = name.trim(); u.tag = tag.trim(); u.note = note; u.expiry = expSec; } },
      call: () => api.userUpdate({ id: user.id, name: name.trim(), tag: tag.trim(), note, expiry: expSec }),
    });
  };
  const del = () => openConfirm({ title: T("Delete user · {name}", { name: user.name }), confirmLabel: T("Delete user"), danger: true, back: done,
    body: T("Their peers are revoked and become unassigned.") + " " + T("This can't be undone.") + (() => {
      // A gateway among them takes its networks down for everyone who used them (docs/NETWORKS-PLAN.md §18).
      const gws = Store.peersOfUser(user.id).filter(p => (p.routes || []).length);
      return gws.length ? " " + T("Their devices that carry networks ({devices}) take them down too — everyone who reaches them through those devices loses access.",
        { devices: gws.map(p => p.title || T("Untitled")).join(", ") }) : "";
    })(),
    // Delete closes the editor it was opened from — see confirmDeletePeer for why `back` is not enough.
    // Two frames, not the whole stack: the confirm and this editor. Identical when the editor is the only
    // thing open (the usual case), and correct rather than lucky when something opened it.
    onConfirm: () => { closeModals(2);
      return mutate({ key: "user:" + user.id,
        patch: s => { delete s.roster.users[user.id]; for (const p of Object.values(s.roster.peers)) if (p.user_id === user.id) p.user_id = null; },
        call: () => api.userDelete({ id: user.id }) }); } });
  return html`<div class="card" style="max-width:740px">
    <${SubStatusLine} user=${user} pos="center"/>
    <div class="field"><label>${T("Name")}</label><input value=${name} onInput=${e => setName(e.target.value)} maxlength="64"/></div>
    <div class="fieldrow">
      <div class="field"><label>${T("Tag")}</label><input value=${tag} onInput=${e => setTag(e.target.value)} placeholder=${T("Friend, Family, Work…")} maxlength="32"/></div>
      <div class="field"><label>${T("Note")}</label><input value=${note} onInput=${e => setNote(e.target.value)} placeholder=${T("Uses iPhone and router")} maxlength="200"/></div>
    </div>
    <${UserGroupsField} user=${user}/>
    <div class="field"><label>${T("Access expires")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— the whole subscription; blank = never")}</span></label>
      <div class="daterow"><input type="date" class="datein" value=${expDate} onInput=${e => setExpDate(e.target.value)}/>${expDate ? html`<button class="btn btn-ghost btn-mini" onClick=${() => setExpDate("")}>${T("Clear")}</button>` : null}</div>
      <div class="hint">${T("On this date the subscription and all its peers stop working (they reappear if you extend it). A peer's own expiry can't be later than this.")}</div></div>
    <${VaultUnlockPanel}/>
    <${SubLinkActions} user=${user}/>
    ${showVk ? html`<${VkLinkField} user=${user}/>` : null}
    <${UserNetworksPanel} user=${user}/>
    <div class="editfoot"><button class="btn btn-danger" onClick=${del}><${Ic} i="trash"/> ${T("Delete user")}</button><button class="btn btn-warn" onClick=${() => rotateAllUserKeys(user, done)} title=${T("Rotate the keys of every peer this user holds — all configs/links must be re-imported")}><${Ic} i="key"/> ${T("Rotate all keys")}</button>${userBlockBtn(user, done)}<span class="grow"></span><button class="btn btn-ghost" onClick=${done}>${T("Cancel")}</button><button class="btn btn-primary" disabled=${!dirty} onClick=${save}>${T("Save")}</button></div>
  </div>`;
}

// one credential: its targets, each a QR card; owner controls + edit + add-target

// A peer deployment card. A WDTT deployment is keyless — it has no WG config/QR, so it dispatches to a dedicated
// card that shows the wdtt:// client link instead of the (empty) WireGuard config. Everything else is WG/AWG.
export function TargetCard(props) {
  const tt = targetType(props.t);
  return tt === "csqtt" ? html`<${TargetCardCsqtt} ...${props}/>`
       : tt === "wdtt" ? html`<${TargetCardWdtt} ...${props}/>`
       : html`<${TargetCardWg} ...${props}/>`;
}
// The wdtt:// client artifact input for a peer's WDTT deployment, assembled from the node read-back (endpoint /
// ports / iface) + the panel-owned per-peer password + the user's VK link. Mirrors what swg-sub builds server-side.
// A link shown on a card: the same readonly textarea + corner copy button the Alternatives sheet uses, so the
// two places a config appears behave the same way (click selects, the icon copies). autoGrow keeps it to the
// text's own height; the CSS caps it so one long link can't stretch the card past its neighbours.
export function LinkBox({ uri }) {
  const ref = useRef(null);
  useEffect(() => { autoGrow(ref.current); }, [uri]);
  return html`<div class="turncfg-tawrap">
    <textarea class="turncfg-ta" readonly spellcheck="false" data-noautofocus ref=${ref}
      onClick=${e => { e.target.select(); copy(uri, T("Link copied")); }}>${uri}</textarea>
    <button class="cmd-copy" title=${T("Copy link")} onClick=${() => copy(uri, T("Link copied"))}><${Ic} i="copy"/></button>
  </div>`;
}
// An artifact's label is English prose composed in turn-artifacts.js, so T() on the finished string can never
// match a key — it carries a fork and an author. Recompose it here from the parts instead; a fork with no client
// metadata (the CLI clients) keeps its own label, which IS a fixed sentence and translates directly.
// How this app takes the config, in the order that is easiest for the person holding the phone: a deeplink it
// can open itself, else a QR to scan, else a link to paste. The label used to say "imports a pasted link"
// whichever it was, so an app that opens on a tap — the ⚡ in the picker beside it — read as the most laborious
// of the three. autostart is per-OS, because the same app can register the scheme on Android and not on desktop.
export function clientHandoff(cl, cid, qr, os) {
  const name = (cl && cl.name) || cid;
  const deeplink = !!((((cl || {}).platforms || {})[os] || {}).autostart);
  if (deeplink) return T("{v1} — opens with one tap", { v1: name });
  if (qr) return T("{v1} — scans a QR code", { v1: name });
  return T("{v1} — imports a pasted link", { v1: name });
}
export function artLabel(a) {
  const m = (typeof SWGTurn !== "undefined" && SWGTurn.clientMeta) ? SWGTurn.clientMeta(a.enc) : null;
  if (!m) return T(a.label || "");
  return T("{v1} via {v2} ({v3}) by {v4}", { v1: a.fork, v2: m.app, v3: m.platform + (a.labelMode || ""), v4: m.author });
}
export function wdttArtInput(peer, t) {
  const rb = ((Store.stats[t.node] || {}).wdtt || []).find(w => w && w.iface === t.iface) || {};
  const nrec = (Store.nodes || []).find(n => n.id === t.node) || {};
  const user = (peer.user_id != null) ? (Store.roster.users || {})[peer.user_id] : null;
  // Host a client dials: the server's OWN bind IF it's a real IP → the node's endpoint_host → the node's reported
  // public IP. The bind wins because it is the operator's per-server choice and the only address that answers: on a
  // node with several public IPs, a node-wide endpoint_host pointed clients at an address this server never bound.
  // Same rule wg/awg already follow, where a per-interface endpoint_host beats the node's (apply_iface_meta).
  // A wildcard (0.0.0.0/blank) means bound-to-all, so there the node's endpoint is right. Never 0.0.0.0 — a dead link.
  const _lh = ipOf(rb.listen || "");
  const _pub = (((Store.stats[t.node] || {}).node_ips) || []).find(ip => ip && !/^(0\.|10\.|127\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)/.test(ip)) || "";
  return { password: peer.wdtt_password || "",
    endpoint_host: (_lh && _lh !== "0.0.0.0" ? _lh : "") || (nrec.endpoint_host || "").trim() || _pub,
    dtls_port: String(rb.listen || "").split(":").pop() || "56000",
    wg_port: rb.wg_port || 56001, tun_port: "9000",
    raw_port: rb.raw_port || "",   // RAW-IP mode, when this server accepts it (the user enters it in the app)
    vk_hash: peer.vk_hash || "", vk_links: userVkLinks(user) };
}
// The csqtt:// client link input for a peer's csqtt deployment — assembled from the node read-back (endpoint /
// listen port) + the panel-owned per-peer password + the user's VK call hashes. Mirrors wdttArtInput.
export function csqttArtInput(peer, t) {
  const rb = ((Store.stats[t.node] || {}).csqtt || []).find(c => c && c.iface === t.iface) || {};
  const nrec = (Store.nodes || []).find(n => n.id === t.node) || {};
  const user = (peer.user_id != null) ? (Store.roster.users || {})[peer.user_id] : null;
  const _lh = ipOf(rb.listen || "");
  const _pub = (((Store.stats[t.node] || {}).node_ips) || []).find(ip => ip && !/^(0\.|10\.|127\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)/.test(ip)) || "";
  const host = (_lh && _lh !== "0.0.0.0" ? _lh : "") || (nrec.endpoint_host || "").trim() || _pub;   // bind wins (see above); never 0.0.0.0 — a dead link
  const port = String(rb.listen || "").split(":").pop() || "46000";
  // Raw VK inputs — csqttArtifact strips/dedupes/caps them into the link's `hashes` (one place, shared with the sub page).
  return { host, port, password: peer.csqtt_password || "", vk_hash: peer.vk_hash || "", vk_links: userVkLinks(user) || [] };
}
export function csqttClientCfg(inp) {
  const art = (typeof SWGTurn !== "undefined" && SWGTurn.csqttArtifact) ? SWGTurn.csqttArtifact(inp) : null;
  return { art, uri: art && art.text, qr: !!(art && art.qr) };   // the encoder decides — the CSQTT app can't scan yet
}
export function TargetCardCsqtt({ peer: peerProp, t, bare, primary, head }) {
  useStore();
  const peer = Store.recon.peers.find(p => p.id === peerProp.id) || peerProp;   // LIVE peer → current csqtt_password (a rotate would else leave a stale link)
  const lt = (((Store.recon.peers.find(p => p.id === peer.id) || {}).targets) || []).find(d => d.node === t.node && d.iface === t.iface) || t;
  const col = Store.nodeColor(t.node); const dnode = Store.nodeName(t.node);
  const inp = csqttArtInput(peer, t);
  const dc = csqttClientCfg(inp);
  // the link is complete, but only because the panel-wide fallback filled it in — see vkOwnHash
  const vkFallbackHere = !vkOwnHash(peer, (peer.user_id != null) ? (Store.roster.users || {})[peer.user_id] : null);
  // An UNASSIGNED peer has no user, so the half of this note about "their subscription page" and "set a VK link
  // on the user" names something that does not exist — it reads as an instruction the operator cannot follow.
  // State the fact that still applies, and stop.
  const vkUnassigned = peer.user_id == null;
  const vkNote = (dc.art && dc.art.vkMissing)
    ? html`<div class="hint vk-note">${T("No VK call link on this user — the link won't authenticate until one is set.")}</div>`
    : vkFallbackHere
      ? html`<div class="hint vk-note">${vkUnassigned ? T("Using the panel's fallback VK call link.")
          : T("Using the panel's fallback VK call link — this user has none of their own. Their subscription page hands out a link without it, so set a VK link on the user before sending them there.")}</div>`
      : null;
  const uri = dc.uri;
  const idParts = []; if (peer.name) idParts.push(esc(peer.name)); if (peer.title) idParts.push(esc(peer.title));
  const label = `<span class="qrc-id">${idParts.length ? idParts.join(" · ") : esc(T("val|Unassigned"))}</span>`
    + `<span class="qrc-srv" style="color:${esc(col)}">${esc(dnode)}</span><span class="tg tg-csqtt">${esc(t.iface)}</span>`;
  return html`<div class="deploy deploy-csqtt">
    ${head || html`<div class="deploy-head"><div class="nmwrap"><a class="nm nmlink" style=${"color:" + col} onClick=${() => { closeModal(); go("#/node/" + encodeURIComponent(t.node)); }}>${dnode}</a></div><${Tag} kind="csqtt" label=${t.iface}/><span class="grow"></span><${Badge} s=${lt.status}/></div>`}
    <div class=${"deploy-body" + (uri && !dc.qr ? " deploy-body-stack" : "")   /* no scanner → the link stacks, same as a WDTT link card */}>
      ${primary === "backup" ? html`<span class="qr-primary qr-backup">${T("Backup")}</span>`
        : primary ? html`<span class="qr-primary">${T("Primary")}</span>` : null}
      ${!uri ? html`<div class="qr-none">${T("csqtt link unavailable — the server isn't reporting yet.")}</div>`
        : dc.qr ? html`<${QR} conf=${uri} label=${label}/>`
        : html`<${LinkBox} uri=${uri}/>`}
      ${bare ? null : html`<div class="dmeta">
        <div class="row"><span class="k">${T("row|kind")}</span><span class="vv">${T("csqtt · keyless (server-minted address)")}</span></div>
        <div class="row"><span class="k">${T("row|endpoint")}</span><span class="vv">${inp.host || "—"}:${inp.port}</span></div>
        <div class="row"><span class="k">${T("row|address")}</span><span class="vv">${lt.ip || "—"}<span class="faint" style="text-transform:none;letter-spacing:0"> ${T("— assigned on first connect")}</span></span></div>
        <div class="row"><span class="k">${T("row|status")}</span><span class="vv"><${Badge} s=${lt.status}/></span></div>
      </div>`}
    </div>
    ${/* A FOOTNOTE, below the body — never inside it. .deploy-body is a flex row and .qr is min-width:0, so a
          sibling of prose collapsed the QR column to 0px and the note appeared to have REPLACED the config.
          Same trap the RAW note hit (see the .tg-raw comment in app.css); same fix. */""}
    ${vkNote}
    ${uri ? html`<div class="acts">
      <button class="btn btn-mini" onClick=${() => copy(uri, T("csqtt link copied"))}><${Ic} i="copy"/> ${T("Copy")}</button>
    </div>` : null}
  </div>`;
}
// The clients a WDTT fork can drive (catalog ids the SPA knows) + one client's encoded artifact.
// Same authority and same order as every other client list — see turnClientsFor. This one matters twice
// over: [0] is the client whose config the peer card shows by default, so it must be the fork's OWN app by
// compat class rather than by whichever id happened to be authored first.
export function wdttClientIds(fork) {
  const cmap = (Store.turnCatalog && Store.turnCatalog.clients) || {};
  return turnClientsFor(fork).map(c => c.id).filter(cid => cmap[cid]);
}
export function wdttClientCfg(w, cid, fork, os) {
  const cl = ((Store.turnCatalog && Store.turnCatalog.clients) || {})[cid] || {};
  const enc = cl.encoder || "wdtt";
  // SETTINGS SPLIT, applied here rather than in wdttArtInput because it is keyed by the CLIENT, which only this
  // layer knows. qWDTT is the one family app whose link carries a knob (`workers`); the encoder has always had
  // the branch for it and nothing ever populated it, so the admin's value was saved and silently dropped. The
  // other encoders take no client values at all, so there is nothing to pass them.
  const wIn = (enc === "qwdtt" && fork) ? { ...w, ...pickDefined(turnClientSettingsFor(fork, enc, os), ["workers"]) } : w;
  const art = (typeof SWGTurn !== "undefined" && SWGTurn.wdttArtifact) ? SWGTurn.wdttArtifact(wIn, enc) : null;
  return { cl, qr: !!cl.qr, art, uri: art && art.text };   // qr = the app scans a QR; else it imports a pasted link
}
// Only the keys that carry a real value: the encoder omits a blank `workers` entirely (the app then uses its own
// default), so an empty saved value must not become `workers=` in the link.
function pickDefined(o, keys) {
  const out = {};
  for (const k of keys) { const v = (o || {})[k]; if (v !== undefined && v !== null && String(v).trim() !== "") out[k] = v; }
  return out;
}
export function TargetCardWdtt({ peer: peerProp, t, bare, primary, head }) {
  useStore();   // re-render on each poll so the status badge stays live
  const peer = Store.recon.peers.find(p => p.id === peerProp.id) || peerProp;   // LIVE peer → its current wdtt_password; the frozen prop would keep a stale link after a rotate
  const lt = (((Store.recon.peers.find(p => p.id === peer.id) || {}).targets) || []).find(d => d.node === t.node && d.iface === t.iface) || t;
  const col = Store.nodeColor(t.node); const dnode = Store.nodeName(t.node);
  const w = wdttArtInput(peer, t);
  // Show the DEFAULT client's config (the fork's first/native app) — a QR where the app scans one, else the plain
  // link. Every other app + per-OS build lives behind "Alternatives" (a child modal, like the turn-proxy config view).
  const rb = ((Store.stats[t.node] || {}).wdtt || []).find(x => x && x.iface === t.iface) || {};
  const fork = rb.fork || "amurcanov";
  const clientIds = wdttClientIds(fork);
  const dc = wdttClientCfg(w, clientIds[0] || "wdttapp", fork);
  // same as the csqtt card: complete-looking link, filled in from the panel-wide fallback — see vkOwnHash
  const vkFallbackHere = !vkOwnHash(peer, (peer.user_id != null) ? (Store.roster.users || {})[peer.user_id] : null);
  // An UNASSIGNED peer has no user, so the half of this note about "their subscription page" and "set a VK link
  // on the user" names something that does not exist — it reads as an instruction the operator cannot follow.
  // State the fact that still applies, and stop.
  const vkUnassigned = peer.user_id == null;
  const vkNote = (dc.art && dc.art.vkMissing)
    ? html`<div class="hint vk-note">${T("No VK call link on this user — the link won't authenticate until one is set.")}</div>`
    : vkFallbackHere
      ? html`<div class="hint vk-note">${vkUnassigned ? T("Using the panel's fallback VK call link.")
          : T("Using the panel's fallback VK call link — this user has none of their own. Their subscription page hands out a link without it, so set a VK link on the user before sending them there.")}</div>`
      : null;
  const uri = dc.uri;
  const idParts = []; if (peer.name) idParts.push(esc(peer.name)); if (peer.title) idParts.push(esc(peer.title));
  const label = `<span class="qrc-id">${idParts.length ? idParts.join(" · ") : esc(T("val|Unassigned"))}</span>`
    + `<span class="qrc-srv" style="color:${esc(col)}">${esc(dnode)}</span><span class="tg tg-wdtt">${esc(t.iface)}</span>`;
  return html`<div class="deploy deploy-wdtt">
    ${head || html`<div class="deploy-head"><div class="nmwrap"><a class="nm nmlink" style=${"color:" + col} onClick=${() => { closeModal(); go("#/node/" + encodeURIComponent(t.node)); }}>${dnode}</a></div><${Tag} kind="wdtt" label=${t.iface}/><span class="grow"></span><${Badge} s=${lt.status}/></div>`}
    <div class=${"deploy-body" + (uri && !dc.qr ? " deploy-body-stack" : "")   /* a QR sits BESIDE its meta (the body's default row); a LINK has to stack — see .deploy-body-stack */}>
      ${primary === "backup" ? html`<span class="qr-primary qr-backup">${T("Backup")}</span>`
        : primary ? html`<span class="qr-primary">${T("Primary")}</span>` : null}
      ${!uri ? html`<div class="qr-none">${T("WDTT link unavailable — the server isn't reporting yet.")}</div>`
        : dc.qr ? html`<${QR} conf=${uri} label=${label}/>`
        : html`<${LinkBox} uri=${uri}/>`}
      ${bare ? null : html`<div class="dmeta">
        <div class="row"><span class="k">${T("row|kind")}</span><span class="vv">${T("WDTT · keyless (server-minted key)")}</span></div>
        <div class="row"><span class="k">${T("row|endpoint")}</span><span class="vv">${w.endpoint_host || "—"}:${w.dtls_port}</span></div>
        <div class="row"><span class="k">${T("row|address")}</span><span class="vv">${lt.ip || "—"}${lt.raw_ip
          ? html` <span class="tg tg-raw" title=${T("This peer's address on the RAW datapath — it holds both at once")}>RAW ${lt.raw_ip}</span>`
          : html`<span class="faint" style="text-transform:none;letter-spacing:0"> ${T("— assigned on first connect")}</span>`}</span></div>
        <div class="row"><span class="k">${T("row|status")}</span><span class="vv"><${Badge} s=${lt.status}/></span></div>
      </div>`}
    </div>
    ${/* A FOOTNOTE, below the body — never inside it. .deploy-body is a flex row and .qr is min-width:0, so a
          sibling of prose collapsed the QR column to 0px and the note appeared to have REPLACED the config.
          Same trap the RAW note hit (see the .tg-raw comment in app.css); same fix. */""}
    ${vkNote}
    ${uri ? html`<div class="acts">
      <button class="btn btn-mini" onClick=${() => copy(uri, T("WDTT link copied"))}><${Ic} i="copy"/> ${T("Copy")}</button>
      ${clientIds.length > 1 ? html`<button class="btn btn-mini" onClick=${() => pushModal(html`<${WdttConfigSheet} peer=${peer} t=${t}/>`)}><${Ic} i="dots"/> ${T("Alternatives")}</button>` : null}
    </div>` : null}
  </div>`;
}
// "Alternatives" — every app for this WDTT fork, by device: a Device dropdown + app chips ("app · by author", in the
// author's colour) on one line, and the chosen app's config (QR where it scans one, else the link) underneath.
export function WdttConfigSheet({ peer, t }) {
  useStore();
  const w = wdttArtInput(peer, t);
  const rb = ((Store.stats[t.node] || {}).wdtt || []).find(x => x && x.iface === t.iface) || {};
  const fork = rb.fork || "amurcanov";
  const cmap = (Store.turnCatalog && Store.turnCatalog.clients) || {};
  const all = wdttClientIds(fork).map(id => ({ id, ...(cmap[id] || {}) }));
  const osOf = c => Object.keys((cmap[c.id] || {}).platforms || {});
  const osList = _OS_TABS.map(([o]) => o).filter(o => all.some(c => osOf(c).includes(o)));
  const [os, setOs] = useState(osList[0] || "android");
  const curOs = osList.includes(os) ? os : (osList[0] || "");
  const clients = all.filter(c => osOf(c).includes(curOs));
  const [ci, setCi] = useState(0);
  const cidx = Math.min(ci, Math.max(0, clients.length - 1));
  const client = clients[cidx] || null;
  const authorOf = id => (turnClientAuthor(id) || {}).fork || (cmap[id] || {}).author || fork;
  const clr = id => turnClientColor(id) || turnColor(authorOf(id));
  const base = (peer.title || peer.name || "peer") + "-" + Store.nodeName(t.node);
  return html`<${Sheet} title=${T("WDTT client apps · {v1}", { v1: peer.title || peer.name || T("val|peer") })} width=${600} noGuard=${true} onClose=${closeModal} onBack=${closeModal}
      headExtra=${html`<${PeerStatusLine} peer=${peer} pos="hr"/>`}>
    <div class="turncfg">
      <${PeerStatusLine} peer=${peer} pos="bar"/>
      <div class="turncfg-devrow">
        ${osList.length > 1 ? html`<div class="turncfg-os"><label>${T("Device")}</label><${OsDropdown} value=${curOs} options=${osList} onChange=${o => { setOs(o); setCi(0); }}/></div>` : null}
        ${clients.length > 1 ? html`<div class="turncfg-app"><label>${T("App")}</label><${AppDropdown} value=${client ? client.id : null}
          options=${clients.map(c => { const rel = ((turnForkList().find(f => f.id === fork) || {}).compat || {})[c.id];
            return { id: c.id, name: c.name || c.id, author: authorOf(c.id), color: clr(c.id), nameColor: appNameColor(rel, false), plain: rel === "plain",
              autostart: !!(((c.platforms || {})[curOs] || {}).autostart) }; })}
          onChange=${id => setCi(Math.max(0, clients.findIndex(c => c.id === id)))}/></div>` : null}
      </div>
      ${client ? html`<${WdttCfgItem} key=${client.id + "|" + curOs} w=${w} cid=${client.id} base=${base} fork=${fork} os=${curOs}/>` : html`<div class="hint">${T("No client app for this device.")}</div>`}
    </div>
  <//>`;
}
export function WdttCfgItem({ w, cid, base, fork, os }) {
  const dc = wdttClientCfg(w, cid, fork, os); const uri = dc.uri;
  const [view, setView] = useState(dc.qr ? "qr" : "text");
  const taRef = useRef(null);
  useEffect(() => { setView(dc.qr ? "qr" : "text"); }, [cid]);
  useEffect(() => { if (view === "text") autoGrow(taRef.current); }, [uri, view]);
  const qrView = dc.qr && view === "qr";
  return html`<div class="turncfg-item">
    <div class="turncfg-head"><span class="tcf-label">${clientHandoff(dc.cl, cid, dc.qr, os)}</span></div>
    ${!uri ? html`<div class="qr-none">${T("WDTT link unavailable — the server isn't reporting yet.")}</div>`
      : qrView ? html`<div class="turncfg-qr"><${QR} conf=${uri} label=${dc.cl.name || cid}/></div>`
      : html`<div class="turncfg-tawrap"><textarea class="turncfg-ta" readonly spellcheck="false" data-noautofocus ref=${taRef} onClick=${e => { e.target.select(); copy(uri, T("WDTT link copied")); }}>${uri}</textarea>
          <button class="cmd-copy" title=${T("Copy link")} onClick=${() => copy(uri, T("WDTT link copied"))}><${Ic} i="copy"/></button></div>`}
    <div class="turncfg-foot">
      ${dc.qr ? html`<button class="btn btn-mini" onClick=${() => setView(v => v === "qr" ? "text" : "qr")}><${Ic} i=${qrView ? "doc" : "qr"}/> ${qrView ? T("Show link") : T("Show QR")}</button>` : null}
      <span class="grow"></span>
      <button class="btn btn-mini" disabled=${!uri} onClick=${() => qrView ? copyQrImage(uri, T("QR image")) : copy(uri, T("WDTT link copied"))}><${Ic} i="copy"/> ${T("Copy link")}</button>
      <button class="btn btn-mini" disabled=${!uri} onClick=${() => downloadConf(uri, base + "-wdtt", "txt")}><${Ic} i="download"/> ${T("Download .txt")}</button>
    </div>
  </div>`;
}
export function TargetCardWg({ peer: peerProp, t, bare, primary, head }) {
  useStore();   // re-render on each poll so the status badge stays live (t is a snapshot from open)
  const peer = Store.recon.peers.find(p => p.id === peerProp.id) || peerProp;   // LIVE peer → its current pubkey; the modal's prop is frozen at open, so a rotation (new key) would otherwise keep the QR gone
  const [conf, setConf] = useState(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => { let ok = true; getConfig(peer.pubkey, t.node, t.iface).then(c => { if (ok) { setConf(c); setLoaded(true); ensurePeerBlob(peer, c); } }); return () => { ok = false; }; }, [peer.pubkey, t.node, t.iface, Store.configEpoch]);
  // live target (status / observed) from the store, falling back to the passed-in snapshot
  const ft = (Store.recon.peers.find(p => p.id === peer.id) || {}).targets;
  const lt = (ft && ft.find(d => d.node === t.node && d.iface === t.iface)) || t;
  const col = Store.nodeColor(t.node);
  const obs = lt.observed;
  const tps = turnProxiesFor(t.node, t.iface);
  const dnode = Store.nodeName(t.node);
  // zoom caption: username + title (or "Unassigned"), then the server name (in its colour) + iface tag
  const idParts = []; if (peer.name) idParts.push(esc(peer.name)); if (peer.title) idParts.push(esc(peer.title));
  const ltype = targetType(t);
  const label = `<span class="qrc-id">${idParts.length ? idParts.join(" · ") : esc(T("val|Unassigned"))}</span>`
    + `<span class="qrc-srv" style="color:${esc(col)}">${esc(dnode)}</span><span class="tg tg-${ltype}">${esc(t.iface)}</span>`;

  return html`<div class="deploy">
    ${head || html`<div class="deploy-head"><div class="nmwrap"><a class="nm nmlink" style=${"color:" + col} onClick=${() => { closeModal(); go("#/node/" + encodeURIComponent(t.node)); }}>${dnode}</a></div><${Tag} kind=${ltype} label=${t.iface}/><span class="grow"></span>${peerUncategorised(t) && lt.status !== "blocked" && lt.status !== "faulty"
      ? uncatPop(html`<span class="badge b-uncat ic"><${Ic} i="warn"/>${statusLabel(lt.status)}</span>`)
      : html`<${Badge} s=${lt.status}/>`}</div>`}
    <div class="deploy-body">
      ${primary === "backup" ? html`<span class="qr-primary qr-backup">${T("Backup")}</span>`
        : primary ? html`<span class="qr-primary">${T("Primary")}</span>` : null}
      ${conf ? html`<${QR} conf=${conf} label=${label}/>`
        : html`<div class="qr-none">${!loaded ? T("loading…")
            // ⚠️ Say which of the two it is. "No stored config — re-issue this peer" is a claim about what
            // is ON DISK, and it was being printed whenever the panel merely could not be reached — telling
            // an operator their config was gone, and recommending the one action that would actually destroy it.
            : confWasSealedOld(peer.pubkey, t.node, t.iface)
              // A THIRD state, and the honest one: the ciphertext is on the panel, but the key that opens it was
              // replaced. No amount of unlocking or waiting brings it back — re-issuing is genuinely the answer
              // here, which is exactly why it must not share wording with the two states where it is destructive.
              ? T("This config was encrypted with a previous encryption key and can no longer be opened. Re-issue this peer to give it a fresh config and QR.")
            : confWasUnreachable(peer.pubkey, t.node, t.iface)
              ? T("Couldn't reach the panel just now, so this peer's stored config could not be read. It has not been lost — try again in a moment.")
            : (Store.storeMode === "encrypted" && !subSKCached())
              // A FOURTH state, found by testing the other three: the vault is merely LOCKED. blobConfig()
              // returns null before it reads anything, so this fell through to "No stored config — re-issue",
              // which recommends destroying a config that is intact and one unlock away. Same defect as the
              // two above, and the one an operator meets most often — every fresh tab starts here.
              ? T("The Encryption Vault is locked, so this peer's stored config can't be read. Unlock it to show the QR — the config has not been lost.")
            : Store.storeConfigs ? T("No stored config — re-issue this peer to enable its QR & download.")
            : T("Config shown right after creation, or enable store_configs to keep it.")}</div>`}
      ${bare ? null : html`<div class="dmeta">
        <div class="row"><span class="k">${T("row|address")}</span><span class="vv">${t.ip || "—"}</span></div>
        <div class="row"><span class="k">${T("row|handshake")}</span><span class="vv">${obs ? seen(obs.handshake_age) : "—"}</span></div>
        <div class="row"><span class="k">${T("row|rate")}</span><span class="vv">${(() => { const xf = tgtXfer(t); return xf ? rateCell(xf.rx_speed, xf.tx_speed) : "—"; })()}</span></div>
        <div class="row"><span class="k">${T("row|transport")}</span><span class="vv">${lt.viaTurn ? html`via <span class="tg tg-turn" style=${"--tfc:" + turnColor(turnLabel(lt.viaTurn))}>${turnLabel(lt.viaTurn)}</span>` : (lt.via === "direct" ? "direct" : "—")}</span></div>
        ${tps.map(tp => html`<div class="row"><span class="k">${T("turn-proxy")}</span><span class="vv">${tp.listen || "—"}
          ${tp.wrap_key ? html`<${Fragment}> ${T("· key")} <span class="addr">${String(tp.wrap_key).slice(0, 8)}…</span><button class="copybtn" title=${T("Copy wrap key")} onClick=${() => copy(tp.wrap_key, T("Wrap key copied"))}><${Ic} i="copy"/></button></>` : null}</span></div>`)}
      </div>`}
    </div>
    ${conf ? html`<div class="acts">
      <button class="btn btn-mini" onClick=${() => downloadConf(conf, (peer.name || "peer") + "-" + dnode)}><${Ic} i="download"/> ${T("Config")}</button>
      <button class="btn btn-mini" onClick=${() => copy(conf, T("Config copied"))}><${Ic} i="copy"/> ${T("Copy")}</button>
      ${tps.length ? html`<button class="btn btn-mini" title=${T("Generate turn-proxy client configs")} onClick=${() => openTurnConfigs(peer, t, conf)}><${Ic} i="relay"/> ${T("Turn")}</button>` : null}
    </div>` : null}
  </div>`;
}
