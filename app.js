/* swg-panel — single-page operator console.
   Buildless Preact + htm (vendored ESM, no build step). The data model is
   User → Peer → Target: a User is identity only; a Peer is one credential
   (pubkey+psk) deployed to one or more Targets, where a target is one
   (node, iface, ip). Peers are managed from the Users angle and from the Peers
   (by-node) angle; unassigned peers carry no user.

   Live polling re-renders the active screen every few seconds; Preact diffs the
   tree, so open inputs/editors are preserved without the old manual update()
   regions. */

import { h, render, Fragment } from "preact";
import { useState, useEffect, useRef, useMemo, useCallback } from "preact/hooks";
import htm from "htm";
import { T, Tsplit, loadLang, plural, srvText } from "./js/i18n.js";
import {
  $, $$, esc,
} from "./js/util.js";
import {
  confirmLeave, matchRoute,
} from "./js/router.js";
import {
  Store, api, hooks as storeHooks, setUnauthorizedHandler, useStore,
} from "./js/store.js";
import {
  ConfirmSheet, applyForkColors, applyThemeColors, clearModalStack, closeModal, cycleLang, cycleThemeMode,
  dismissHostProc, gotoSettingsSection, inProc, openConfirm, openModal, paintLangBtn, paintThemeBtn,
  procAborted, procFailed, procInClass, procLabel, procSuccess, setModalRenderer, setPendingSection,
  setQrZoomProbe, toast, trackIfaceOps,
} from "./js/ui.js";
import {
  cryptoReady, ifaceKeyAutoRestore, escrowAutoVerify, lockVault, looksLikeVaultKey, qrZoomEl, subAutoHeal, subBootRestore, subForget, subRewrap,
  subSKCached, subUnlock, subUnlockWithKey, subVaultCreate,
} from "./js/crypto.js";
import {
  OnlineUsersTag, onlineUserRows, serviceIssues,
} from "./js/views.js";
import {
  maybeRekeyGhosts, setLoadIfaceOpener,
} from "./js/peer-actions.js";
import {
  openTurnUpdates, trackTurnRestarts,
} from "./js/turn.js";
import {
  VaultKeySheet,
} from "./js/peer-ui.js";
import {
  IfaceDetail, LoadIfaceSheet,
} from "./js/iface.js";
import {
  CHECK_SVG, INFO_SVG, NodeDetail, NodesScreen, UPD_SPIN_SVG, WARN_SVG, X_SVG, checkForUpdate, fixBubbleHtml,
  hostHoverBubble, hostUpdRepairing, hostUpdating, noteHostUpdateDone, openUpdateDone, pendingUpdateDone,
  seenPanelVer, setSeenPanelVer, takePendingUpdateDone, turnUpdBubbleHtml, updBubbleHtml, updateHost, versionHoverBubble,
} from "./js/screen-nodes.js";
import {
  Overview, ServiceIssueSheet, maybeAlertServices, recordDashTick, setAppReady,
} from "./js/screen-overview.js";
import {
  ActivityHistoryScreen, ConnectionsScreen, PeersScreen, UsersScreen,
} from "./js/screen-roster.js";
import {
  AccountScreen, PanelSettingsScreen,
} from "./js/screen-settings.js";

// Fill the Store's callback slots (see js/store.js). These live above the Store in the module graph, so it
// cannot import them — it calls back into them instead. Each assignment moves into the owning module as the
// split proceeds; all targets are hoisted function declarations, so wiring them here is safe.
Object.assign(storeHooks, {
  themeColors: () => applyThemeColors(),
  forkColors: () => applyForkColors(),
  dashTick: () => recordDashTick(),
  alertServices: () => maybeAlertServices(),
  rekeyGhosts: () => maybeRekeyGhosts(),
  vaultKeyCached: () => subSKCached(),
  vaultAutoHeal: () => subAutoHeal(),
  ifaceKeyAutoRestore: () => ifaceKeyAutoRestore(),
  escrowAutoVerify: () => escrowAutoVerify(),
});
setUnauthorizedHandler(() => require401());
setQrZoomProbe(() => !!qrZoomEl);   // Esc inside a Sheet must collapse an open QR enlargement, not close the sheet
// The ghost-recreate flow (js/peer-actions.js) has to raise the Load-interface sheet, which lives above it.
setLoadIfaceOpener(({ node, pre, ghost, back }) =>
  openModal(html`<${LoadIfaceSheet} node=${node} pre=${pre} ghost=${ghost} back=${back}/>`));

const html = htm.bind(h);









// ───────────────────────── drag-to-reorder ─────────────────────────

















// Owner controls: assigned peers can only be Unassigned (revokes the holder); unassigned
// peers offer Assign-to (fresh key) and Delete. Deletion is gated to unassigned peers.


// ═════════════════════════ ROUTER + APP ═════════════════════════
const ROUTES = [
  { re: /^\/$/, fn: Overview, tab: "overview" },
  { re: /^\/connections$/, fn: ConnectionsScreen, tab: "connections" },
  { re: /^\/node\/([^/]+)\/([^/]+)$/, fn: IfaceDetail, tab: "nodes", keys: ["node", "iface"] },
  { re: /^\/node\/(.+)$/, fn: NodeDetail, tab: "nodes", keys: ["node"] },
  { re: /^\/nodes$/, fn: NodesScreen, tab: "nodes" },
  { re: /^\/peers$/, fn: PeersScreen, tab: "peers" },
  { re: /^\/activity$/, fn: ActivityHistoryScreen, tab: "overview" },
  { re: /^\/users$/, fn: UsersScreen, tab: "users" },
  { re: /^\/account$/, fn: AccountScreen, tab: "account" },
  { re: /^\/panel\/settings$/, fn: PanelSettingsScreen, tab: "panel-settings" },
];

// ─── "previous panel address" ribbon ──────────────────────────────────────────
// A browser tab can sit on an OLD panel address (a host/port from before an Access & TLS change). During the
// migration grace it still serves; after, it 52x / refuses. Either way it isn't an error — just an old address
// drifting away. We compare where THIS tab is loaded against the panel's CONFIRMED canonical address (from
// /api/state, `panel_public_url` — advances only on confirm, so it never flashes mid-change) and, when they
// differ, show a persistent, calm (amber, not alarm-red) ribbon naming the current address so it's never
// mistaken for a fault. The initiating tab's richer red countdown ribbon, when present, takes precedence.
function _effPort(scheme, port) { return String(port || (scheme === "https" ? "443" : "80")); }
function _parseAddr(rawUrl) {
  const raw = (rawUrl || "").trim(); if (!raw) return null;
  let u; try { u = new URL(/^https?:\/\//i.test(raw) ? raw : "https://" + raw); } catch (_) { return null; }
  const host = u.hostname, scheme = (u.protocol || "https:").replace(":", "");
  if (!host || host === "0.0.0.0") return null;
  return { host, scheme, port: _effPort(scheme, u.port), base: (u.pathname || "").replace(/\/+$/, "") };
}
function oldAddrCurrent() {   // → the current canonical addr {host,scheme,port,base,label} if THIS tab is on a different one, else null
  const c = _parseAddr(Store.panelPublicUrl); if (!c) return null;
  const scheme = location.protocol.replace(":", "");
  const hereBase = location.pathname.replace(/\/+$/, "");
  // ⚠️ THE CONSOLE ADDRESS IS NOT A STALE ONE. With private access on, the panel's public url is
  // deliberately NOT where the console lives — that address answers node routes and 404s these pages —
  // so a tab on the console differs from `panelPublicUrl` by design, on every load, for as long as the
  // feature is on. Left to the plain comparison the ribbon fires permanently and its "Go to the current
  // address" button sends the operator to a 404. Measured on a declarative host, where the console is
  // the only way in at all.
  const _acc = (Store.panelSettings || {}).access || {};
  const _cw = _acc.console_wired || null;
  const _cport = String((_cw && _cw.port) || ((_acc.console || {}).mode === "own" ? (_acc.console || {}).port : "") || "");
  if (_cport && _effPort(scheme, location.port) === _cport) return null;   // this IS the console door
  if (location.hostname === c.host && _effPort(scheme, location.port) === c.port && hereBase === c.base) return null;   // on the current address (host + port + mount PATH)
  const showPort = !((c.scheme === "https" && c.port === "443") || (c.scheme === "http" && c.port === "80"));
  return { ...c, label: c.scheme + "://" + c.host + (showPort ? ":" + c.port : "") + c.base };
}
// The ONE address-migration ribbon — global, on every screen, server-driven so it survives navigation + reload.
// Shows a live countdown while a confirmed migration is still gracing out (panel_migrate_until), then falls back to
// "you're on a previous address" until this tab moves to the current one.
function OldAddrRibbon() {
  useStore();
  // PURE model — we SHOW REALITY, we don't predict it: the ribbon appears iff THIS tab's actual address differs
  // from the panel's BLESSED (confirmed) address. `oldAddrCurrent()` compares window.location to the server's
  // CONFIRMED url, which advances ONLY on a real confirm (never on a bare Save). Consequences, all for free:
  //   • editing + Save (not yet confirmed) → blessed unchanged → a tab on it shows nothing (the confirm/revert
  //     card owns that screen); no ribbon+confirm collision, no screen special-casing.
  //   • confirm succeeds → blessed advances → the just-opened new tab matches (no ribbon); OTHER tabs on the old
  //     address now differ → ribbon.
  //   • confirm fails / can't validate (CF/nginx/unreachable) → blessed never moved → the new tab differs from
  //     blessed and points back home; the panel is exactly where it was.
  // No countdown, no "will stop working" — those were guesses about the future; the browser already knows the truth.
  const c = oldAddrCurrent();
  const ref = useRef(null);
  useEffect(() => {
    document.body.classList.toggle("has-oldaddr", !!c);
    if (c && ref.current) document.body.style.setProperty("--oldaddr-h", ref.current.offsetHeight + "px");
    return () => document.body.classList.remove("has-oldaddr");
  });
  if (!c) return null;
  // "Cancel the move" is ORTHOGONAL to visibility — it never decides whether the ribbon shows. It appears only while
  // the panel still allows an instant undo (a panel-controlled move whose old address is still served); the server
  // clears that the moment the grace ends. Clicking it moves blessed back → this tab matches again → ribbon vanishes.
  const canRevert = Store.panelMigrateRevertable && Store.panelMigratePrev;
  const revertMove = async () => {
    const r = await api.post("/api/access/cancel", Store.panelMigratePrev).catch(() => null);
    if (r && r.ok) { toast(T("Move cancelled — the panel stays on this address."), "ok"); await Store.poll(); }
    else toast(srvText(r) || T("Couldn't cancel the move."), "err");
  };
  return html`<div class="addr-old-ribbon" ref=${ref} role="status">
    <span><b>${T("You're on a previous panel address.")}</b> ${ribbonNow(c.label)}</span>
    ${canRevert ? html`<button class="btn btn-mini" onClick=${revertMove}>${T("Cancel the move — keep this address")}</button>` : null}
    <a class="btn btn-mini" href=${c.label}>${T("Go to the current address ↗")}</a>
  </div>`;
}

// The new address is a LINK inside the sentence — translate whole, split on the marker (see Tsplit).
// "fix 3 issues" — a counted noun, so the count and the word travel together through plural().
const fixLabel = n => T("fix {count}", { count: plural(n, "issue") });

// Two styled runs in one sentence: the command name (monospace, never translated) and "untouched" (bold).
// Split twice on the same principle as Tsplit — the sentence stays one translatable unit.
function relinkWhy() {
  const [a, rest] = Tsplit("Your password was changed with {cmd}, which runs on the server and can't reach your encryption key. Your stored configs, QR codes and subscription links are {safe} — the vault just needs reconnecting.", "cmd");
  const [b, c] = [rest.split("{safe}")[0], rest.split("{safe}").slice(1).join("{safe}")];
  return html`<${Fragment}>${a}<b class="mono">swg-passwd</b>${b}<b>${T("untouched")}</b>${c}<//>`;
}

function ribbonNow(addr) {
  const [before, after] = Tsplit("The panel is now reached at {addr}.", "addr");
  return html`<${Fragment}>${before}<a href=${addr}>${addr}</a>${after}<//>`;
}

function App() {
  useStore();                                   // re-render on every poll
  const [hash, setHash] = useState(location.hash || "#/");
  const [modalStack, setModalStack] = useState([]);
  useEffect(() => { setModalRenderer(setModalStack); }, []);
  // Arm the panel-service alert once App is mounted (so openModal's setState is live), and fire it immediately
  // in case the first poll already landed a critical issue before mount. Later polls re-check via Store.apply.
  useEffect(() => { setAppReady(true); maybeAlertServices(); return () => setAppReady(false); }, []);

  // Access & TLS confirm handshake: the confirm itself fires at BOOT (maybeConfirmApply), before anything
  // auth-gated, because a domain change lands on a host our cookie doesn't cover — App wouldn't even mount.
  // Here we only report the OUTCOME once App is up: success (we reloaded, carrying our login onto this address)
  // or failure (confirm didn't match a pending change).
  useEffect(() => {
    let ok = false, fail = null, console_ok = false;
    try {
      const _ov = sessionStorage.getItem("__apply_ok");
      ok = _ov === "1" || _ov === "console"; console_ok = _ov === "console"; if (ok) sessionStorage.removeItem("__apply_ok");
      fail = sessionStorage.getItem("__apply_fail"); if (fail) sessionStorage.removeItem("__apply_fail");
    } catch (_) {}
    if (!ok && !fail) return;
    setPendingSection("access");
    if (location.hash !== "#/panel/settings") location.hash = "#/panel/settings";
    // defer past any hashchange (its handler resets the modal stack) so the outcome modal survives
    setTimeout(() => {
      if (console_ok) openModal(html`<${ConfirmSheet} title=${T("Console address confirmed")} confirmLabel=${T("Got it")}
        back=${() => { gotoSettingsSection("access"); closeModal(); }}
        body=${T("The operator console is served here now, and you're signed in. The panel's own address answers only what the nodes ask for — so close the other tab, it can't open the console any more.")}/>`);
      else if (ok) openModal(html`<${ConfirmSheet} title=${T("New address confirmed")} confirmLabel=${T("Got it")}
        back=${() => { gotoSettingsSection("access"); closeModal(); }}
        body=${T("This is now the address the panel is reached at, and you're signed in here. You can close the other tab — it's on the previous address.")}/>`);
      else openModal(html`<${ConfirmSheet} title=${T("Couldn’t confirm the new address")} warn=${true} confirmLabel=${T("OK")}
        body=${((fail && fail !== "1" && fail) || T("The confirmation didn’t match a pending change.")) + T(" The panel kept its current address.")}/>`);
    }, 0);
  }, []);
  // Docker restart-safe change, step 3 (reachability commit) — GLOBAL so it fires on ANY screen, not only when the
  // Access & TLS card is open. The new container came up "awaiting reachability"; this browser reaching /api/state
  // here IS the proof the new address answers through the proxy (nodes dial the same url the same way), so commit —
  // which clears the marker and stands the server's auto-revert timer down. A guard ref makes it fire once per nonce.
  const committedNonce = useRef("");
  useEffect(() => {
    const a = Store.dockerAwaiting;
    if (a && a.nonce && committedNonce.current !== a.nonce) {
      committedNonce.current = a.nonce;
      api.post("/api/access/docker-commit", { nonce: a.nonce }).then(() => Store.poll && Store.poll()).catch(() => { committedNonce.current = ""; });
    }
  });
  useEffect(() => {
    const onHash = () => {
      const nh = location.hash || "#/";
      if (!confirmLeave(nh)) return;   // a screen had unsaved edits and the operator declined; the URL is already restored
      setHash(nh); clearModalStack(); window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onHash);
    // Esc/Enter inside dialogs are owned by <Sheet> (with its dirty-guard); nothing global here.
    // A MOUSE click on an icon button / nav tab shouldn't leave a lingering focus ring (it persists
    // after a modal closes, then any keypress like Shift re-shows it). Suppressing the focus on
    // mousedown keeps the click working while keyboard Tab still focuses (and shows the ring).
    const onMD = e => { const el = e.target && e.target.closest && e.target.closest(".iconbtn, #tabs a"); if (el) e.preventDefault(); };
    document.addEventListener("mousedown", onMD, true);
    return () => { window.removeEventListener("hashchange", onHash); document.removeEventListener("mousedown", onMD, true); };
  }, []);

  const { route, params } = matchRoute(ROUTES, hash);

  // static chrome lives in index.html — keep it in sync imperatively
  useEffect(() => {
    trackTurnRestarts();                                             // detect completed turn restarts → green flash
    trackIfaceOps();                                                 // interface start/restart progress lifecycle
    const lp = $("#livepill");                                       // online USERS, with a per-user peer-count bubble
    if (lp) {
      lp.classList.toggle("off", onlineUserRows(null).length === 0);   // 0 = grey, no dot
      render(html`<${OnlineUsersTag} nodeId=${null} cls="bare" trigger=${c => html`<span class="dot"></span><b id="kpi-online">${c}</b> ${T("val|online")}`}/>`, lp);
    }
    const v = Store.versions || {}, el = $("#appver");
    if (v.panel) {            // panel came back on a different version → it was updated; prompt a hard reload
      if (seenPanelVer && seenPanelVer !== v.panel) noteHostUpdateDone(seenPanelVer, v.panel);
      setSeenPanelVer(v.panel);
    }
    // Pop the "Panel updated — reload" prompt only once the host lifecycle has FINISHED (host_proc no longer
    // in-progress). On a master the panel restarts after its own phase while the node phase is still running, so
    // firing on the version bump alone would show "updated" once now and again when host_proc lands its terminal —
    // i.e. twice on the header. Holding it until host_proc settles makes that a single "updated".
    if (pendingUpdateDone && !inProc(Store.hostProc)) { const _u = takePendingUpdateDone(); openUpdateDone(_u[0], _u[1]); }
    if (el && v.panel) {        // panel version + info icon → the changelog hover bubble (reuses the update-bubble look)
      // aria-label, not title — the icon carries no text of its own so AT still needs a name, but the
      // changelog bubble is what a sighted hover gets and a native tooltip would just cover it. Same
      // reinstatement reason as the turn badge: this innerHTML is rewritten on every poll.
      el.innerHTML = `<span class="appver-wrap"><b>${esc(v.panel)}</b><span class="appver-info" aria-label="${esc(T("Changelog"))}">${INFO_SVG}</span></span>`;
      if (!el._verWired) { el._verWired = true; versionHoverBubble(el); }   // wire once — #appver persists across polls
    }
    const ht = $("#host-tport");      // how the PANEL itself is deployed (docker / bare-metal)
    if (ht && Store.env && ("docker" in Store.env)) {
      const dk = !!Store.env.docker;
      ht.className = "tport " + (dk ? "docker" : "baremetal");
      // Say which runtime it really is. The pill is about THIS panel, and a podman-hosted one used to
      // read DOCKER — the same lie the node cards told before they learned to ask.
      ht.textContent = dk ? (Store.env.runtime === "podman" ? T("kind|podman") : T("kind|docker"))
                          : T("kind|bare-metal");
      ht.hidden = false;
    }
    const slot = $("#updslot");
    if (slot) {
      // a host lifecycle status (re-install / update) OWNS the slot — in-progress, then its terminal
      // (success ~5s auto-clears, aborted/failed until ×) — so it never shows alongside the update-check
      // T("up to date")/button. With no lifecycle status, the slot is the normal update widget.
      let body;
      const _hl = esc((hostUpdRepairing && ({ updating: T("repairing"), updated: T("repaired"), "update-failed": T("repair failed") }[Store.hostProc]))
                      || procLabel(Store.hostProc) || "");   // a Fix/re-run reads as "repairing…" / "repaired", not "updating"
      const _healN = serviceIssues().length;   // self-healable issues (missing/broken swg units + AmneziaWG datapath) → the updater repairs them
      // ⚠️ THE CHECK BUTTON IS "Check status", NOT "check for updates" — it calls checkUpdate() AND
      // Store.poll(), so it re-reads service issues as well as the version, and it toasts about the
      // repairable ones. It was the LAST branch of this chain, so it vanished the moment the panel went
      // outdated — a state that lasts days — leaving no on-demand refresh anywhere in the product exactly
      // when an operator most wants one. It now rides ALONGSIDE the steady-state badges.
      const _checkBtn = `<button class="iconbtn lg" id="upd-check" title="${esc(T("Check status"))}"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 4v4h-4"/></svg></button>`;
      if (inProc(Store.hostProc)) body = `<span class="hostproc-tag ${procInClass(Store.hostProc)}">${UPD_SPIN_SVG} ${_hl}</span>`;
      else if (procSuccess(Store.hostProc)) body = `<span class="hostproc-tag ok">${CHECK_SVG} ${_hl}</span>`;   // green, auto-clears (no ×)
      else if (procAborted(Store.hostProc)) body = `<span class="hostproc-tag aborted">${INFO_SVG} ${_hl}<button class="xbtn" id="hostproc-x" title="${esc(T("Dismiss"))}">${X_SVG}</button></span>`;
      else if (procFailed(Store.hostProc)) body = `<span class="hostproc-tag fail${Store.hostProcErr ? ' tg-click' : ''}" id="hostproc-tag">${WARN_SVG} ${_hl}<button class="xbtn" id="hostproc-x" title="${esc(T("Dismiss"))}">${X_SVG}</button></span>`;   // whole tag clickable → error popup
      else if (hostUpdating) body = `<span class="livepill upd-busy">${esc(hostUpdRepairing ? T("repairing…") : T("updating…"))} ${UPD_SPIN_SVG}</span>`;
      else if (Store.hostChecking) body = `<span class="livepill upd-busy">${esc(T("checking…"))} ${UPD_SPIN_SVG}</span>`;   // Check status click → brief "checking…" pill (updates + issues)
      // Priority: a real upgrade first (updating heals too, so no "Fix" then) → else self-healable issues → else up-to-date / check.
      else if (Store.panelOutdated) body = `<button class="livepill updpill" id="host-upd">${esc(T("update to"))} <b>${esc(Store.latestRemote || "?")}</b></button>`;
      else if (_healN > 0) body = `<button class="livepill updpill fixpill" id="host-fix">${WARN_SVG} ${esc(fixLabel(_healN))}</button>`;
      else if (Store.updFlash && Date.now() < Store.updFlash) body = `<button class="livepill upd-uptodate" id="host-repair" title="${esc(T("On the latest version — click to re-run the updater anyway (repairs this box: reinstalls missing pieces, re-enables services, rebuilds the datapath / AmneziaWG kernel module)"))}"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg> ${esc(T("up to date"))}</button>`;
      else body = _checkBtn;
      // Steady = a badge you can act on. NOT the in-flight tags (updating / checking / proc): re-polling
      // there is meaningless or already happening, and the header would flicker spinner↔button. Derived
      // from what the chain PRODUCED, so the chain stays one untouched if/else-if run.
      if (/id="host-(upd|fix|repair)"/.test(body)) body += _checkBtn;
      // Turn-family updates are a DIFFERENT AXIS from this box's health, so they ride BESIDE the chain rather
      // than inside it. Ranked above "fix" they would hide a broken unit behind a version bump; ranked below
      // they would vanish for the days a panel sits outdated — the same disappearing act the check button's
      // comment above records. Suppressed only while a host lifecycle/check is in flight, where the header is
      // already busy and a second badge would just add noise.
      // Counts FORKS, not (fork, node) rows: an operator thinks "csqtt has an update", not "csqtt-on-A and
      // csqtt-on-B have updates", and the same grouping drives the bubble — so badge count == lines listed.
      const _turnN = new Set((Store.turnUpdates || []).map(r => r.fork)).size;
      const _turnBadge = (_turnN && !/hostproc-tag|upd-busy/.test(body))
        // No `title=`: the hover bubble below IS this badge's caption, and it names the forks, the nodes and
        // the versions rather than restating the label. A native tooltip would surface a second later, on top
        // of it, saying less. (parkTitles in hostHoverBubble enforces that generally; the header rewrites this
        // element every poll, so the attribute must not be here to be reinstated mid-hover.)
        ? `<button class="livepill updpill turnpill" id="turn-upd">${esc(plural(_turnN, "update"))}</button>` : "";
      // Left of the check button in BOTH layouts: the badges read as a row of things that are true, and the
      // check is the verb that refreshes them — a verb belongs at the end of the row, not between two facts.
      if (_turnBadge) body = body.includes(_checkBtn) ? body.replace(_checkBtn, _turnBadge + _checkBtn) : body + _turnBadge;
      slot.innerHTML = body;
      const b = $("#host-upd"); if (b) { b.onclick = updateHost; hostHoverBubble(b, updBubbleHtml, updateHost); }   // version + date + changelog on hover; the bubble's own Update button runs the SAME action (on touch the anchor is underneath it)
      const rp = $("#host-repair"); if (rp) rp.onclick = updateHost;   // up-to-date → still allow a re-run/repair (heals the datapath even with no new version)
      const fx = $("#host-fix"); if (fx) { fx.onclick = () => openModal(html`<${ServiceIssueSheet} issues=${serviceIssues()}/>`); hostHoverBubble(fx, fixBubbleHtml); }   // the issue(s) on hover; click = review + run the repair
      const tu = $("#turn-upd"); if (tu) { tu.onclick = openTurnUpdates; hostHoverBubble(tu, turnUpdBubbleHtml, openTurnUpdates); }   // forks + versions on hover; the bubble's own foot is the action (and reachable on touch, where the anchor is underneath it)
      const c = $("#upd-check"); if (c) c.onclick = checkForUpdate;
      const hx = $("#hostproc-x"); if (hx) hx.onclick = e => { e.stopPropagation(); dismissHostProc(); };
      const htg = $("#hostproc-tag"); if (htg && Store.hostProcErr) htg.onclick = () => openConfirm({ title: procLabel(Store.hostProc), log: Store.hostProcErr, confirmLabel: T("Close") });
    }
    $$("#tabs a").forEach(a => a.classList.toggle("active", a.dataset.tab === route.tab));
    const acct = $("#acct-btn"); if (acct) acct.onclick = () => doLogout();   // header logout icon → straight to the confirm
    const tb = $("#theme-btn"); if (tb && !tb._wired) { tb._wired = true; tb.onclick = cycleThemeMode; paintThemeBtn(tb); }   // light/dark/auto switch
    const lb = $("#lang-btn"); if (lb && !lb._wired) { lb._wired = true; lb.onclick = cycleLang; paintLangBtn(lb); }            // EN / RU
    const vl = $("#vaultlock-btn");   // padlock: removed from the header by request — kept (wired to lockVault) but always hidden
    if (vl) { vl.hidden = true; if (!vl._wired) { vl._wired = true; vl.onclick = lockVault; } }
  });

  return html`<${Fragment}>
    ${h(OldAddrRibbon)}
    ${h(route.fn, params)}
    ${modalStack}
  <//>`;
}

// ───────────────────────── auth: login page + logout ─────────────────────────
let _loginShown = false;
// Two-factor (TOTP / Google Authenticator) card for Settings → Authentication.
function require401() { showLogin(); throw new Error("unauthorized"); }   // i18n-keys: a control-flow sentinel, never displayed
function showLogin() { if (_loginShown) return; _loginShown = true; document.body.classList.add("loggedout"); try { render(h(LoginScreen), viewEl); } catch (_) {} }
// Shown right after signing in when the panel password was reset with `swg-passwd` and the new password doesn't
// open the vault. swg-passwd runs on the box, where the encryption key doesn't exist, so it can't re-wrap the
// vault — but it destroys NOTHING: every stored config, QR, subscription link and escrowed server key is intact.
// Either the OLD panel password or the encryption key gets us back in, and the vault is then re-wrapped under
// `panelPw` — which only exists here, before the post-login reload, hence asking on this screen.
// Skippable: the vault stays locked and the usual unlock prompt appears on the next action that needs it.
function VaultRelinkCard({ panelPw, onDone }) {
  const [pw, setPw] = useState(""); const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const ref = useRef(null);
  useEffect(() => { ref.current && ref.current.focus(); }, []);
  const submit = async e => {
    if (e) e.preventDefault();
    if (!pw || busy) return;
    setBusy(true); setErr("");
    try {
      // One field takes both: an encryption key is recognisable on sight (base64 of 32 bytes), so try it that way
      // first and fall back to treating the input as the old password (a password of that exact shape is possible,
      // if unlikely). When both fail, report the error for whichever the input actually looked like — telling
      // someone who pasted a key that their "password" was wrong sends them looking in the wrong place.
      if (looksLikeVaultKey(pw)) {
        try { await subUnlockWithKey(pw); }
        catch (keyErr) { try { await subUnlock(pw); } catch (_) { throw keyErr; } }
      } else await subUnlock(pw);
      await subRewrap(panelPw);        // the vault now opens with the password just signed in with
      onDone();
    } catch (e2) { setErr((e2 && e2.message) || T("That didn't unlock the Encryption Vault.")); setBusy(false); }
  };
  return html`<div class="login-wrap"><form class="login-card" onSubmit=${submit}>
    <div class="login-brand"><span class="brand-mark"></span><span class="brand-name">swg<span>Panel</span></span></div>
    <h2>${T("Reconnect your vault")}</h2>
    <p class="muted" style="margin:-4px 0 12px">${relinkWhy()}</p>
    <div class="field"><label>${T("Old panel password, or your encryption key")}</label>
      <input ref=${ref} type="password" value=${pw} autocomplete="off" placeholder=${T("Password or encryption key")} onInput=${e => setPw(e.target.value)}/></div>
    <p class="muted" style="margin:-4px 0 12px">${T("The encryption key is the one shown when this panel set up encryption — you were asked to save it.")}</p>
    ${err ? html`<div class="formmsg err">${err}</div>` : null}
    <button class="btn btn-primary" type="submit" disabled=${busy || !pw} style="width:100%;justify-content:center;margin-top:4px">${busy ? T("Reconnecting…") : T("Reconnect vault")}</button>
    <button class="btn btn-ghost" type="button" disabled=${busy} style="width:100%;justify-content:center;margin-top:8px" onClick=${onDone}>${T("Skip for now")}</button>
  </form></div>`;
}
function LoginScreen() {
  const [u, setU] = useState(""); const [p, setP] = useState(""); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const [twofa, setTwofa] = useState(false); const [code, setCode] = useState("");
  const [relink, setRelink] = useState(null);   // set to the NEW panel password when the vault needs reconnecting first
  // The `autofocus` attribute is inert here: showLogin() renders this form long after page load, and a
  // browser only honours autofocus for elements present when the document flushes its autofocus candidates
  // (Preact doesn't special-case it either). Focus explicitly — on mount, and again when the 2FA step
  // replaces the form, so the code can be typed without reaching for the mouse.
  const focusRef = useRef(null);
  useEffect(() => { focusRef.current && focusRef.current.focus(); }, [twofa]);
  const submit = async e => {
    if (e) e.preventDefault();
    if (busy) return;
    setBusy(true); setErr("");
    try {
      const r = await api.login({ username: u, password: p, code: twofa ? code.trim() : undefined });
      if (r && r.ok) {
        // Convenience cache: auto-unlock config encryption with the login password (survives the reload via
        // sessionStorage). If there is NO vault yet — a fresh install — create one under this same password, so encryption is
        // simply on from the start: the operator never has to go and set it up by hand before their first peer,
        // and signing in both creates AND unlocks it (subVaultCreate caches the key too). Strictly gated on "no
        // vault exists": subUnlock also throws on a WRONG password, and creating there would mint a new key over
        // an existing wrap and orphan every stored config.
        let unlocked = true;
        try { await subUnlock(p); } catch (_) {
          unlocked = false;
          try {
            const v = await api.subVault();
            if (!(v && v.ok && v.data && v.data.exists)) {
              await subVaultCreate(p); unlocked = true;
              // the key just minted here is the ONLY way back in after an out-of-band password reset — show it
              // once the SPA is up (the raw key is already in the session cache subVaultCreate wrote).
              try { sessionStorage.setItem("__vault_show_key", "1"); } catch (_) {}
            }
          } catch (_) {}
        }
        // swg-passwd changed the panel password on the box, where the vault key isn't reachable, so the vault
        // could not follow it. Nothing was destroyed — if this password somehow still opens the vault just
        // re-wrap and move on; otherwise hand the operator the
        // re-connect prompt, where the OLD panel password or the encryption key gets us back in.
        if (r.data && r.data.vault_reset) {
          if (unlocked) { try { await subRewrap(p); sessionStorage.setItem("__vault_reconnected", "1"); } catch (_) {} }
          else { setRelink(p); setBusy(false); return; }   // ask HERE — after the reload the new password is gone, and the re-wrap needs it
        }
        location.reload(); return;
      }
      if (r && r.twofa_required) {                       // password OK — panel wants the 6-digit code
        const msg = srvText(r) || "";
        setTwofa(true); setErr(msg);
        if (msg) {                                       // a REJECTED code: clear it (else the next digits append) and
          setCode("");                                   // take focus back from the Verify button so retyping just works.
          focusRef.current && focusRef.current.focus();  // same DOM node — `twofa` didn't flip, so it is not remounted
        }
        setBusy(false); return;
      }
      setErr(srvText(r) || T("Login failed.")); setBusy(false);
    } catch (_) { setErr(T("Couldn't reach the panel.")); setBusy(false); }
  };
  if (relink) return html`<${VaultRelinkCard} panelPw=${relink} onDone=${() => location.reload()}/>`;
  return html`<div class="login-wrap"><form class="login-card" onSubmit=${submit}>
    <div class="login-brand"><span class="brand-mark"></span><span class="brand-name">swg<span>Panel</span></span></div>
    <h2>${twofa ? T("Two-factor") : T("Sign in")}</h2>
    ${twofa ? html`
      <p class="muted" style="margin:-4px 0 12px">${T("Enter the 6-digit code from your authenticator app, or a recovery code.")}</p>
      <div class="field"><label>${T("Authentication code")}</label><input ref=${focusRef} value=${code} onInput=${e => setCode(e.target.value)} inputmode="text" autocomplete="one-time-code" placeholder="123 456"/></div>
      ${err ? html`<div class="formmsg err">${err}</div>` : null}
      <button class="btn btn-primary" type="submit" disabled=${busy} style="width:100%;justify-content:center;margin-top:4px">${busy ? T("Verifying…") : T("Verify")}</button>
      <button class="btn btn-ghost" type="button" onClick=${() => { setTwofa(false); setCode(""); setErr(""); }} style="width:100%;justify-content:center;margin-top:8px">${T("Back")}</button>
    ` : html`
      <div class="field"><label>${T("Username")}</label><input ref=${focusRef} value=${u} onInput=${e => setU(e.target.value)} autocomplete="username"/></div>
      <div class="field"><label>${T("Password")}</label><input type="password" value=${p} onInput=${e => setP(e.target.value)} autocomplete="current-password"/></div>
      ${err ? html`<div class="formmsg err">${err}</div>` : null}
      <button class="btn btn-primary" type="submit" disabled=${busy} style="width:100%;justify-content:center;margin-top:4px">${busy ? T("Signing in…") : T("button|Sign in")}</button>
    `}
  </form></div>`;
}
function doLogout() {
  openConfirm({ title: T("Log out"), confirmLabel: T("Log out"),
    body: T("Are you sure you want to logout?"),
    onConfirm: async () => { subForget(); try { await api.logout(); } catch (_) {} location.reload(); } });
}
// Account form as a modal (same chrome as the node sheets).

// ───────────────────────── boot ─────────────────────────
const viewEl = $("#view");
viewEl.innerHTML = `<div class="loading"><span class="spin"></span>${T("connecting…")}</div>`;
// Access & TLS confirm: if we landed here with ?__apply=<nonce>, confirm it BEFORE anything auth-gated. The
// confirm is authorized by the nonce (not a session) and carries our login onto this address, so it MUST run
// even when we're not logged in here — a domain change lands on a host our cookie doesn't cover, which would
// otherwise 401 Store.init() → login screen → App (and its confirm handler) never mounts. On success we reload
// to pick up the fresh session cookie; the "confirmed" note shows after, in App (the `__apply_ok` branch).
async function maybeConfirmApply() {
  // ?__applyurl=<nonce> — a reverse-proxy DOMAIN/URL swap confirm: we were opened on the NEW url, so this request
  // arrives THROUGH the proxy on the new host, which is the panel's proof the proxy routes it here. ?__apply=<nonce>
  // is the direct/rebind confirm (new listener). Both are nonce-authorized (not a session) and carry our login onto
  // this address, so they MUST run before anything auth-gated (a domain change lands where our cookie doesn't cover).
  const mu = /[?&]__applyurl=([A-Za-z0-9]+)/.exec(location.search);
  // ?__applyconsole=<nonce> — the OPERATOR CONSOLE moving to its own address. We were opened on the new
  // console listener, and arriving here at all is the panel's proof the operator can reach it — which is
  // why the panel's own address only drops to a node-only door once this lands. Same nonce authorization
  // and the same reason it must run pre-auth, only more so: the console door is a different ORIGIN, so a
  // session cookie provably cannot reach it and we would otherwise stare at a login while the timer ran out.
  const mc = /[?&]__applyconsole=([A-Za-z0-9]+)/.exec(location.search);
  const m = mu || mc || /[?&]__apply=([A-Za-z0-9]+)/.exec(location.search);
  if (!m) return false;
  // strip the query so a reload can't re-fire, and land on Access & TLS — presetting the hash HERE (before the
  // reload) means App's outcome effect doesn't have to change it, so the hashchange handler can't wipe the modal.
  history.replaceState(null, "", location.pathname + "#/panel/settings");
  let r = null;
  const endpoint = mu ? "/api/access/confirm-url" : (mc ? "/api/access/console-confirm" : "/api/access/confirm");
  try { r = await api.post(endpoint, { nonce: m[1] }); } catch (_) { r = null; }   // never throws us to login: confirm is pre-auth
  if (r && r.ok) { try { sessionStorage.setItem("__apply_ok", mc ? "console" : "1"); } catch (_) {} location.reload(); return true; }
  try { sessionStorage.setItem("__apply_fail", srvText(r) || "1"); } catch (_) {}   // shown by App once it mounts (if we're authed here)
  return false;
}
/* The app bar is STATIC markup in index.html — it paints before any module runs, which is the point (the
   chrome is up while the SPA boots). So it can't call T(); it is translated here instead, once, right after
   loadLang() and before the first render.

   Keyed on data-tab and on the element id, never on the label text: the tab's identity is `data-tab`, which
   is also what marks it active, and a text match would quietly stop finding it the moment it's translated. */
function paintChrome() {
  const tab = { overview: T("nav|Overview"), connections: T("nav|Live"), users: T("nav|Users"),
                nodes: T("nav|Nodes"), peers: T("nav|Peers") };
  $$("#tabs a").forEach(a => { const k = a.dataset.tab; if (tab[k]) a.textContent = tab[k]; });
  const brand = $(".brand"); if (brand) brand.setAttribute("aria-label", T("nav|Overview"));
  const hint = [["#host-tport", T("How this panel is deployed")], ["#vaultlock-btn", T("Lock encryption key")],
                ["#lang-btn", T("Language")], ["#theme-btn", T("Theme")],
                ["#panel-settings-btn", T("Panel settings")], ["#acct-btn", T("Log out")]];
  for (const [sel, label] of hint) {
    const el = $(sel);
    if (!el) continue;
    el.title = label;
    if (el.hasAttribute("aria-label")) el.setAttribute("aria-label", label);
  }
}

(async () => {
  await loadLang();         // before the first render: T() is synchronous, and a late catalog would paint English then flip
  paintChrome();            // the static app bar, which loaded before any of this
  // INSECURE CONTEXT. Web Crypto is exposed only over https:// (or http on localhost/127.0.0.1); anywhere
  // else `crypto.subtle` is undefined and peer creation, the Encryption Vault and every config/QR fail with
  // a bare TypeError that reads as a panel bug. Warn, do NOT block: unlike swgSub — whose whole purpose is
  // decrypting configs, so it stops dead — the panel's nodes, traffic and health views work fine without it,
  // and an operator watching a fleet over a LAN address should keep them.
  if (!cryptoReady()) {
    const b = document.createElement("div");
    b.className = "insecure-banner";
    b.innerHTML = `<b>${esc(T("Not a secure connection"))}</b> ${esc(T("Your browser only provides Web Crypto over https:// (or http://localhost), so creating peers, unlocking the Encryption Vault and showing configs or QR codes will not work here. Monitoring is unaffected."))}`;
    document.body.insertBefore(b, document.body.firstChild);
  }
  await subBootRestore();   // restore the config-encryption convenience cache from sessionStorage (post-login reload)
  if (await maybeConfirmApply()) return;   // confirmed → reloading; stop this boot pass
  try { await Store.init(); }
  catch (e) { if (!_loginShown) viewEl.innerHTML = `<div class="empty"><b>${esc(T("Can't reach the panel"))}</b>${esc(e.message)}</div>`; return; }
  if (!location.hash) location.hash = "#/";
  // landed here right after a confirm (we reloaded to pick up the carried session) → open the settings screen
  // straight on Access & TLS, BEFORE it mounts and defaults to Display. (The outcome modal is shown by App.)
  try { if (sessionStorage.getItem("__apply_ok")) setPendingSection("access"); } catch (_) {}
  render(h(App), viewEl);
  // Tell the boot guard in index.html that the SPA is up. Set AFTER the first render, so it means
  // "something is on screen", not merely "this file parsed" — a module that loads and then throws
  // mid-boot must still count as a failure.
  window.__swgBooted = true;
  try { if (sessionStorage.getItem("__vault_reconnected")) { sessionStorage.removeItem("__vault_reconnected"); setTimeout(() => toast(T("Encryption Vault reconnected."), "ok"), 400); } } catch (_) {}
  try { if (sessionStorage.getItem("__vault_show_key")) { sessionStorage.removeItem("__vault_show_key"); setTimeout(() => openModal(html`<${VaultKeySheet}/>`), 500); } } catch (_) {}
})();

