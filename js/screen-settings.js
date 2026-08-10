/* screen-settings.js — Panel settings and the account page.
 *
 * LAYER 11 (see docs/APP-JS-SPLIT-PLAN.md). The largest screen, and the one that reaches furthest: it
 * renders the routing/blocking policy UI, the turn-proxy catalog, the subscription vault, the escrow and
 * the Access & TLS flow, so it imports most of the stack.
 *
 * Access & TLS is the delicate part. Changing the panel's own address can lock the operator out of the
 * panel they are changing it from, so the flow is deliberately three-step — save a CANDIDATE, confirm it
 * from the new address, auto-revert if that confirmation never arrives — and the state machine for that
 * lives here rather than being split between screen and store.
 */

import { T, Trich, Tsplit, plural, srvText } from "./i18n.js";
import {
  BASE, ago, seen, url,
} from "./util.js";
import {
  LEAVE_MSG, clearUnsavedGuard, setUnsavedGuard,
} from "./router.js";
import {
  IFACE_COLOR_DEFAULTS, THEME_COLOR_DEFAULT, THEME_COLOR_LIGHT_DEFAULT, clampBrand, pickThemed,
} from "./theme.js";
import {
  Store, api, bus, useStore,
} from "./store.js";
import {
  forkSupportsAwg, turnColor, turnFork, turnForkList, turnForksVisible,
} from "./turn-catalog.js";
import {
  ConfirmSheet, Dropdown, Ic, NodeIpPick, Popover, Sheet, Switch, ThemedSwatch, autoGrow, closeModal, copy,
  goSettings, openConfirm, openModal, pushModal, registerSectionSetter, takePendingSection, toast,
} from "./ui.js";
import {
  SUB_LANG_LIST, VaultPromptSheet, downloadConf, ivkSetEscrow, nginxServerBlock, normPublicUrl, qrDataURL,
  runConfigMigration, subBaseUrl, subForget, subKeyB64, subRewrap, subSKCached, subUnlock, subVaultCreate,
  urlPortOf, withUrlPort,
} from "./crypto.js";
import {
  AsnHint, BlockListPicker, CAT_PROVIDER_DEFAULTS, CatPicker, DescInfo, FleetAssign, HostHealth, ListInfo,
  MODE_META, ModeTabs, NewBlockCatSheet, ProvTag, blockCatDisabled, blockSrcOk, capBadges, catCap, catDescOf,
  catLabelOf, catListUrl, catRawId, catUsableInMode, customCaps, invalidTargets, loadBlockCatalog, newRid,
  provLabelOf, providerColor, resetRouting, sizeSummary, splitTargets,
} from "./routing.js";
import {
  TURN_FORKS_DEFAULT, TurnCollectedIps, openRosterCheck, openServerClients, openServerDefaults,
  turnForkPlatforms, turnUpdateTarget, turnUpdating,
} from "./turn.js";
import {
  IgnoredIfacesCard,
} from "./iface.js";
import { h, Fragment } from "preact";
import { useState, useEffect, useRef, useCallback } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);


export function AccountScreen() {
  const [user, setUser] = useState("");
  const [cur, setCur] = useState(""); const [np, setNp] = useState(""); const [np2, setNp2] = useState("");
  const [msg, setMsg] = useState(null); const [enabled, setEnabled] = useState(true);
  useEffect(() => { api.account().then(r => { if (r.ok) { if (r.data.username) setUser(r.data.username); if (!r.data.auth_enabled) { setEnabled(false); setMsg({ ok: false, t: T("This panel has no login configured — changes are disabled.") }); } } }); }, []);
  const save = async () => {
    if (!user.trim()) return setMsg({ ok: false, t: T("Username can't be empty.") });
    if (user.includes(":")) return setMsg({ ok: false, t: T("Username can't contain a colon.") });
    if (!cur) return setMsg({ ok: false, t: T("Enter your current password to confirm.") });
    if (np && np !== np2) return setMsg({ ok: false, t: T("New passwords don't match.") });
    if (np && np.length < 8) return setMsg({ ok: false, t: T("New password must be at least 8 characters.") });
    setMsg({ ok: true, t: T("Saving…") });
    // Re-wrap the vault BEFORE the credential change lands. /api/account rotates the session secret, so the
    // moment it returns our cookie is dead and subRewrap's own API calls 401 — it swallows that and returns
    // false, silently leaving the vault sealed under the OLD password. Do it while the session is still
    // valid, and roll back if the credential change is then rejected, so a wrong current password leaves
    // the vault exactly as it was. Same SK throughout — no blob is ever re-encrypted.
    let reWrapped = false;
    if (np) {
      if (!subSKCached()) { try { await subUnlock(cur); } catch (_) {} }   // not unlocked this session — the current password is right here
      if (subSKCached()) { try { reWrapped = await subRewrap(np); } catch (_) { reWrapped = false; } }
    }
    const r = await api.accountSave({ username: user.trim(), current_password: cur, new_password: np });
    if (!r.ok) {
      if (reWrapped) { try { await subRewrap(cur); } catch (_) {} }   // undo — the password never actually changed
      return setMsg({ ok: false, t: srvText(r) || T("Failed to update.") });
    }
    setMsg({ ok: true, t: T("Updated. Reloading — sign in with your new credentials…") });
    setTimeout(() => location.reload(), 1400);
  };
  return html`<div class="screen">
    <div class="crumb"><b>${T("Account")}</b></div>
    <div class="card" style="max-width:520px">
      <h3 style="margin:0 0 4px">${T("Admin login")}</h3>
      <p class="hint" style="margin:0 0 18px">${Trich("Change the panel username and password. Takes effect immediately — you'll be asked to sign in again. Changing the password also reconnects your *Encryption Vault* to it — the encryption key itself is unchanged, so stored configs and subscription links keep working (no re-issue).")}</p>
      ${msg ? html`<div class=${"formmsg " + (msg.ok ? "ok" : "err")}>${msg.t}</div>` : null}
      <div class="field"><label>${T("Username")}</label><input value=${user} onInput=${e => setUser(e.target.value)} autocomplete="username"/></div>
      <div class="field"><label>${T("Current password")}</label><input type="password" value=${cur} onInput=${e => setCur(e.target.value)} autocomplete="current-password" placeholder=${T("required to confirm changes")}/></div>
      <div class="field"><label>${T("New password")}</label><input type="password" value=${np} onInput=${e => setNp(e.target.value)} autocomplete="new-password" placeholder=${T("leave blank to keep current")}/></div>
      <div class="field"><label>${T("Confirm new password")}</label><input type="password" value=${np2} onInput=${e => setNp2(e.target.value)} autocomplete="new-password"/></div>
      <div style="margin-top:8px"><button class="btn btn-primary" disabled=${!enabled} onClick=${save}>${T("Save changes")}</button></div>
    </div>
  </div>`;
}

export const AWG_KEYS = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4", "I1"];
// client-side AmneziaWG obfuscation generator — mirrors the panel's gen_awg_params (for the "Generate" button)
export function genAwg() {
  const r = n => Math.floor(Math.random() * n), w = 15;
  let s1 = 15 + r(135), s2 = 15 + r(135);
  while (s2 === s1 || s2 === s1 + 56) s2 = 15 + r(135);
  const b = [5, 1e9, 2e9, 3e9].map(base => base + r(9e8));
  return { Jc: 4, Jmin: 40, Jmax: 70, S1: s1, S2: s2, S3: 15 + r(85), S4: 15 + r(85),
    H1: `${b[0]}-${b[0] + w}`, H2: `${b[1]}-${b[1] + w}`, H3: `${b[2]}-${b[2] + w}`, H4: `${b[3]}-${b[3] + w}`,
    I1: "<b 0xc300000001><r 1200>" };
}
// labelled grid of the 12 AWG fields — read-only display (node settings) or editable (panel settings).
export function AwgGrid({ value, onChange, readOnly }) {
  const v = value || {};
  // J / S / H / I as columns, fields stacked — same layout as the interface AWG display
  return html`<div class="awg-cols">${[["Jc", "Jmin", "Jmax"], ["S1", "S2", "S3", "S4"], ["H1", "H2", "H3", "H4"], ["I1"]].map(grp => html`<div class="awg-col">${grp.map(k => html`<label class="awg-f"><span>${k}</span>${readOnly
    ? html`<span class="awg-val">${v[k] != null && v[k] !== "" ? v[k] : "—"}</span>`
    : html`<input value=${v[k] ?? ""} onInput=${e => onChange({ ...v, [k]: e.target.value })} spellcheck="false"/>`}</label>`)}</div>`)}</div>`;
}

// Add / edit an outbound webhook (Settings → Integrations). Immediate-persist via a dedicated endpoint —
// not part of the batched Save. On create the panel returns the signing secret once; edits keep the secret.
// The ids are canonical (stored on the hook, sent to the panel); only the labels are translated, and they
// are resolved on RENDER — a module-level T() runs before loadLang() and would freeze in English.
export const WH_EVENTS = ["peer.added", "peer.removed", "node.online", "node.offline"];   // i18n-keys
const whEventLabel = ev => ({
  "peer.added": T("Peer added"), "peer.removed": T("Peer removed"),
  "node.online": T("Node came online"), "node.offline": T("Node went offline"),
}[ev] || ev);
export function WebhookSheet({ hook, onSaved, onClose }) {
  const [url, setUrl] = useState((hook && hook.url) || "");
  const [events, setEvents] = useState(new Set((hook && hook.events) || WH_EVENTS));
  const [enabled, setEnabled] = useState(hook ? hook.enabled !== false : true);
  const [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState("");                 // shown once, only on create
  const valid = /^https?:\/\/.+/i.test(url.trim());
  const toggle = ev => setEvents(s => { const n = new Set(s); n.has(ev) ? n.delete(ev) : n.add(ev); return n; });
  const save = async () => {
    if (!valid) return toast(T("Enter a valid http(s) URL."), "err");
    setBusy(true);
    const r = await api.apiWebhookSave({ id: hook && hook.id, url: url.trim(), events: [...events], enabled });
    setBusy(false);
    if (!r.ok) return toast(srvText(r) || T("Failed to save webhook"), "err");
    if (r.data && r.data.secret && !hook) { setSecret(r.data.secret); onSaved && onSaved(); return; }   // creation: reveal the secret, keep the sheet open
    onSaved && onSaved(); onClose && onClose();
  };
  return html`<${Sheet} title=${hook ? T("Edit webhook") : T("Add webhook")} onClose=${onClose}
    foot=${secret ? html`<${Fragment}><span class="grow"></span><button class="btn" onClick=${onClose}>${T("Done")}</button></>`
      : html`<${Fragment}><span class="grow"></span>
        <button class="btn btn-ghost" onClick=${onClose}>${T("Cancel")}</button>
        <button class="btn btn-primary" disabled=${busy || !valid} onClick=${save}>${hook ? T("Save") : T("Add webhook")}</button></>`}>
    ${secret ? html`<div class="notice ok"><${Ic} i="check"/><span>${Trich("Webhook saved. This is its *signing secret* — shown once. Every delivery carries an `X-SWG-Signature: sha256=HMAC(secret, body)` header so you can verify it's from this panel.")}</span></div>
      <div class="tokreveal"><code class="tokval">${secret}</code><button class="btn btn-mini" onClick=${() => copy(secret, T("Secret"))}><${Ic} i="copy"/> ${T("Copy")}</button></div>`
    : html`<div class="field"><label>${T("Payload URL")}</label>
        <input value=${url} onInput=${e => setUrl(e.target.value)} placeholder="https://example.com/hooks/swg" spellcheck="false"/>
        <div class="hint">${T("The panel POSTs a JSON body here on each selected event. A signing secret is generated on save.")}</div></div>
      <div class="seclabel">${T("Events")}</div>
      <div class="wh-events">${WH_EVENTS.map(ev => html`<label class="wh-ev" key=${ev}>
        <input type="checkbox" checked=${events.has(ev)} onChange=${() => toggle(ev)}/><span class="mono">${ev}</span><span class="wh-ev-lbl">${whEventLabel(ev)}</span></label>`)}</div>
      <label class="wh-en"><${Switch} on=${enabled} onChange=${setEnabled}/><span>${T("Deliveries enabled")}</span></label>`}
  <//>`;
}

// Settings → Integrations: the read-only external API (tokens + Prometheus) and outbound webhooks. All actions
// persist immediately via dedicated endpoints (outside the batched Save), mirrored optimistically into Store.
export function IntegrationsSettings() {
  const cfg = () => ((Store.panelSettings || {}).api) || { enabled: false, tokens: [], webhooks: [] };
  const [label, setLabel] = useState("");
  const [minted, setMinted] = useState(null);               // {label, token} — revealed once after minting
  const [busy, setBusy] = useState(false);
  const c = cfg();
  const baseUrl = `${location.origin}${BASE}`;
  const optimistic = next => { Store.panelSettings = { ...(Store.panelSettings || {}), api: next }; bus.emit(); };
  const setEnabled = async v => { optimistic({ ...cfg(), enabled: v }); const r = await api.panelSettings({ api_enabled: v }); if (r && r.ok === false) toast(srvText(r) || T("Failed"), "err"); };
  const mint = async () => {
    setBusy(true);
    const r = await api.apiTokenCreate(label.trim());
    setBusy(false);
    if (!r.ok) return toast(srvText(r) || T("Failed to create token"), "err");
    setMinted({ label: r.data.label, token: r.data.token });
    setLabel("");
    optimistic({ ...cfg(), enabled: true, tokens: [...(cfg().tokens || []), { id: r.data.id, label: r.data.label, created: r.data.created, last_used: null }] });
  };
  const revoke = t => openConfirm({ title: T("Revoke API token"), confirmLabel: T("Revoke"), danger: true,
    body: Trich("Revoke *{label}*? Any integration still using it stops working immediately.", { label: t.label }),
    onConfirm: async () => { await api.apiTokenRevoke(t.id); optimistic({ ...cfg(), tokens: (cfg().tokens || []).filter(x => x.id !== t.id) }); } });
  const editHook = h => openModal(html`<${WebhookSheet} hook=${h} onClose=${closeModal}/>`);
  const delHook = h => openConfirm({ title: T("Delete webhook"), confirmLabel: T("Delete"), danger: true,
    body: Trich("Stop sending events to *{v1}*?", { v1: h.url }),
    onConfirm: async () => { await api.apiWebhookDelete(h.id); optimistic({ ...cfg(), webhooks: (cfg().webhooks || []).filter(x => x.id !== h.id) }); } });
  const testHook = async h => { const r = await api.apiWebhookTest(h.id); toast(r.ok ? T("Delivered — HTTP {v1}", { v1: (r.data || {}).status || "200" }) : T("Delivery failed: {v1}", { v1: srvText(r) || T("val|unreachable") }), r.ok ? "ok" : "err", 4200); };
  return html`<div class="card">
    <div class="seclabel turnhead" style="margin-top:0">${T("External API")}<span class="grow"></span>
      <${Switch} on=${c.enabled === true} title=${c.enabled ? T("API on — tokens are accepted") : T("API off — all tokens are rejected")} onChange=${setEnabled}/></div>
    <p class="hint" style="margin:0 0 12px">${Trich("A *read-only* REST + Prometheus surface for external monitoring and automation — Grafana, Uptime Kuma, Prometheus, Terraform/Ansible. No token can ever change the fleet. Authenticate with a bearer token below; `/healthz` and `/api/v1/health` stay open as liveness probes.")}</p>
    ${c.enabled !== true ? html`<div class="notice warn"><${Ic} i="warn"/><span>${Trich("The API is *off* — endpoints return 401. Minting a token turns it on, or flip the switch above.")}</span></div>` : null}

    <div class="seclabel">${T("Access tokens")}</div>
    <div class="tok-add"><input value=${label} onInput=${e => setLabel(e.target.value)} placeholder=${T("Label (e.g. grafana, prometheus)")} spellcheck="false" onKeyDown=${e => { if (e.key === "Enter") mint(); }}/>
      <button class="btn btn-primary" disabled=${busy} onClick=${mint}><span class="plus"><${Ic} i="plus"/></span> ${T("Create token")}</button></div>
    ${minted ? html`<div class="notice ok"><${Ic} i="check"/><span>${Trich("New token *{label}* — copy it now, it won't be shown again.", { label: minted.label })}</span></div>
      <div class="tokreveal"><code class="tokval">${minted.token}</code><button class="btn btn-mini" onClick=${() => copy(minted.token, T("Token"))}><${Ic} i="copy"/> ${T("Copy")}</button><button class="btn btn-mini btn-ghost" onClick=${() => setMinted(null)}>${T("Dismiss")}</button></div>` : null}
    ${(c.tokens || []).length ? html`<div class="toklist">${c.tokens.map(t => html`<div class="tokrow" key=${t.id}>
      <div class="tokrow-main"><span class="tokrow-label">${t.label}</span>
        <span class="tokrow-meta">${T("created {v1}", { v1: ago(t.created) })}${t.last_used ? T(" · last used {v1}", { v1: ago(t.last_used) }) : T(" · never used")}</span></div>
      <button class="btn btn-mini btn-danger" onClick=${() => revoke(t)}><${Ic} i="trash"/> ${T("Revoke")}</button></div>`)}</div>`
      : html`<p class="hint" style="margin:2px 0 0">${T("No tokens yet — create one to let an external system read the fleet.")}</p>`}

    <div class="seclabel">${T("Webhooks")}</div>
    <p class="hint" style="margin:0 0 10px">${T("The panel POSTs a signed JSON body to your endpoint when a peer is added/removed or a node goes online/offline. Use them for alerting or automation.")}</p>
    ${(c.webhooks || []).length ? html`<div class="toklist">${c.webhooks.map(h => html`<div class=${"tokrow" + (h.enabled === false ? " off" : "")} key=${h.id}>
      <div class="tokrow-main"><span class="tokrow-label mono">${h.url}</span>
        <span class="tokrow-meta">${(h.events || []).join(", ") || T("all events")}${h.enabled === false ? " · disabled" : ""}</span></div>
      <button class="btn btn-mini" title=${T("Send a test ping")} onClick=${() => testHook(h)}><${Ic} i="refresh"/> ${T("Test")}</button>
      <button class="btn btn-mini" onClick=${() => editHook(h)}><${Ic} i="pencil"/></button>
      <button class="btn btn-mini btn-danger" onClick=${() => delHook(h)}><${Ic} i="trash"/></button></div>`)}</div>` : null}
    <div style="margin-top:10px"><button class="btn btn-ghost" onClick=${() => editHook(null)}><${Ic} i="plus"/> ${T("Add webhook")}</button></div>

    <div class="seclabel">${T("Endpoints")}</div>
    <div class="apiendpoints">
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/api/v1/health</span><span class="apiep-d">${T("liveness + counts (no auth)")}</span></div>
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/metrics</span><span class="apiep-d">${T("Prometheus exposition")}</span></div>
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/api/v1/servers</span><span class="apiep-d">${T("nodes with status + counts")}</span></div>
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/api/v1/servers/{id}/peers</span><span class="apiep-d">${T("peers + last-handshake timing")}</span></div>
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/api/v1/peers</span><span class="apiep-d">${T("all peers, per-node presence")}</span></div>
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/api/v1/summary</span><span class="apiep-d">${T("fleet totals")}</span></div>
    </div>
    <div class="apisnip"><div class="apisnip-h">${T("Test it")}<button class="btn btn-mini" onClick=${() => copy(`curl -H 'Authorization: Bearer <token>' ${baseUrl}/api/v1/servers`, T("Command"))}><${Ic} i="copy"/> ${T("Copy")}</button></div>
      <code class="apisnip-c">${`curl -H 'Authorization: Bearer <token>' ${baseUrl}/api/v1/servers`}</code></div>
    <div class="apisnip"><div class="apisnip-h">${T("Prometheus scrape config")}<button class="btn btn-mini" onClick=${() => copy(`scrape_configs:\n  - job_name: swg-panel\n    metrics_path: /metrics\n    scheme: ${location.protocol.replace(":", "")}\n    authorization:\n      credentials: <token>\n    static_configs:\n      - targets: ['${location.host}${BASE}']`, T("Scrape config"))}><${Ic} i="copy"/>${T("Copy")}</button></div>
      <code class="apisnip-c">${`scrape_configs:\n  - job_name: swg-panel\n    metrics_path: /metrics\n    authorization:\n      credentials: <token>\n    static_configs:\n      - targets: ['${location.host}${BASE}']`}</code></div>
  </div>`;
}

// Cloudflare's proxy only connects back to origin HTTPS on this fixed port set (everything else is
// unreachable behind the orange cloud). A bundled snapshot of CF's published IP ranges (v4 + v6) for the
// copy-list — it changes rarely; the panel never fetches it live.
export const CF_HTTPS_PORTS = [443, 8443, 2053, 2083, 2087, 2096];
export const CF_IP_RANGES = [
  "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18",
  "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17",
  "162.158.0.0/15", "104.16.0.0/13", "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
  "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32", "2405:8100::/32",
  "2a06:98c0::/29", "2c0f:f248::/32"];
// Built on FIRST READ, never at import: modules load before loadLang() resolves, so a T() evaluated
// here freezes in English whatever the catalog says (see --frozen). A memoised FUNCTION rather than a
// lazy array/object facade — Dropdown calls flatMap() on its options, and a facade only ever has the
// methods someone remembered to forward.
let _tls_mode_opts = null;
export const TLS_MODE_OPTS = () => (_tls_mode_opts || (_tls_mode_opts = [
  { value: "", label: T("None — plain HTTP (behind a reverse proxy / Cloudflare)") },
  { value: "letsencrypt", label: T("Let's Encrypt (HTTP-01 — needs port 80 reachable)") },
  { value: "cloudflare", label: T("Let's Encrypt via Cloudflare DNS (no port 80; needs a token)") },
  { value: "cf15", label: T("Cloudflare Origin certificate (15y — only valid behind Cloudflare)") },
  { value: "selfsigned", label: T("Self-signed") }]));

// The panel + swg-sub network address (bindable IP + port) and the ONE certificate config both derive from.
// A change is applied LIVE: the panel dual-listens on the new address and only drops the old once the browser
// confirms the new one works, so a bad value never locks the operator out. swg-sub just restarts.
export function AccessTLSCard({ onChange }) {
  const acc = (Store.panelSettings || {}).access || {};
  const p0 = acc.panel || {}, s0 = acc.sub || {}, t0 = acc.tls || {};
  const subsOn = !!((Store.panelSettings || {}).subscriptions || {}).enabled;
  const localPort = Number(p0.local_port || 0);   // co-located node's loopback port (live, read-only) — 0/absent ⇒ no local node ⇒ hide the field
  const [pUrl, setPUrl] = useState(normPublicUrl(p0.url || "")); const [pHost, setPHost] = useState(p0.host || "0.0.0.0"); const [pPort, setPPort] = useState(String(p0.port || 443));
  const [sUrl, setSUrl] = useState(s0.url || ""); const [sHost, setSHost] = useState(s0.host || "0.0.0.0"); const [sPort, setSPort] = useState(String(s0.port || 8444));
  const [mode, setMode] = useState(t0.mode || ""); const [email, setEmail] = useState(t0.email || "");
  const [cfTok, setCfTok] = useState(""); const [cfOrig, setCfOrig] = useState("");
  const [hasCfTok, setHasCfTok] = useState(!!t0.has_cf_token); const [hasCfOrig, setHasCfOrig] = useState(!!t0.has_cf_origin_token);
  const [ips, setIps] = useState([]); const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const [polling, setPolling] = useState(false);
  const [confirmUrl, setConfirmUrl] = useState("");   // set while an address change is verifying → the operator confirms it by opening the new address in a new tab (we can't auto-navigate safely: an unreachable new address would strand them, and a cross-origin reachability probe is blocked by our own CSP)
  const [dockerFlip, setDockerFlip] = useState("");   // Docker restart-safe change, step 3: the container is recreating onto the new address. new dial url — shown with a "reconnect" button HELD for a few seconds (see dockerArm) so the operator doesn't open it before the container is back
  const [dockerArm, setDockerArm] = useState(0);      // seconds until the Docker reconnect button arms — a short hold covering the container restart (opening the new address before it's up just fails)
  const [dockerRestart, setDockerRestart] = useState(null);   // Docker restart-safe change, step 1 (Save done): {nonce,url_changed,old_url,new_url,port,port_move,armUntil,error} — nodes now dual-connect to new_url; the operator reviews, then Confirm & restart (dry-run + recreate) or Revert (no-op). Nothing has recreated yet.
  const [drArmIn, setDrArmIn] = useState(0);          // seconds until the "Confirm & restart" button arms — a hold covering one node-sync so nodes LEARN the new address before the recreate (so it can't strand them)
  const [dockerFlipPort, setDockerFlipPort] = useState(0);   // >0 = the step-3 reconnect card is for a reverse-proxy INTERNAL-port move: show the new port to re-point the proxy at (the public url is unchanged), not a "reconnect at new address" link
  const [confirmVerified, setConfirmVerified] = useState(true);   // false = the reachability gate FAILED-OPEN (revealed Confirm without proving the new address answers) → surface that so Confirm-appearing isn't mistaken for "reachable"
  const [rpSwap, setRpSwap] = useState(null);         // unified reverse-proxy swap in progress: {port_changed,url_changed,path_changed,old_url,new_url,old_host,old_port,new_host,new_port,nonce} — panel serves old+new ports/paths and advertises the new url as a node candidate until the operator re-points the proxy and confirms (no timeout). Any combination of port/url/path.
  const [rpArmIn, setRpArmIn] = useState(0);          // seconds until the rp-swap Confirm button ARMS — a deliberate 60s hold (with a confirm modal) so the operator can't reflexively drop the old address before verifying the proxy actually serves the new one
  const [staleWarn, setStaleWarn] = useState(false);  // the server's SAVED address settings changed out from under this open form (a rollback / boot reconcile / another tab) WHILE the operator has unsaved edits → warn before they apply a now-stale value
  // The "you're on a previous panel address" ribbon is GLOBAL (OldAddrRibbon) + server-driven — it shows on every
  // screen and survives reload, so there's no per-card migration ribbon/state here.
  const rollbackRef = useRef(null);            // the panel address that was live BEFORE an apply → restore the SAVED url on revert (the server rolls back the bind/cert, but the saved url is still the new one → it'd advertise a dead address to nodes)
  const didPanelRef = useRef(false);           // whether THIS save applied a panel change / a sub change — the shared /api/access/status keeps the LAST result of each, so a sub-only save must ignore a stale panel "saved" (and vice-versa)
  const didSubRef = useRef(false);
  const cancelledRef = useRef(false);          // the operator CANCELLED this change (vs it timing out unconfirmed) → the revert message/modal should say "cancelled", not "check DNS/firewall". Set on the Cancel click, cleared when a fresh apply starts + once the revert is shown.
  // Baseline of what's currently live — the form is compared to this to decide what changed (and thus what needs
  // a live apply). Refreshed after a successful save so the button disables until the next edit.
  const [orig, setOrig] = useState({ pUrl: normPublicUrl(p0.url || ""), pHost: p0.host || "0.0.0.0", pPort: String(p0.port || 443),
    sUrl: s0.url || "", sHost: s0.host || "0.0.0.0", sPort: String(s0.port || 8444), mode: t0.mode || "", email: t0.email || "" });
  useEffect(() => { api.get("/api/access/ips").then(r => { if (r && r.ok) setIps(r.ips || []); }); }, []);
  // Recover an in-progress reverse-proxy swap after a page reload (server keeps the old address serving until confirmed).
  useEffect(() => { api.get("/api/access/status").then(r => { const p = r && r.ok && r.panel;
    // Recover a swap after reload — and continue the SAME arming countdown (server sends arm_secs remaining from when
    // the swap was armed), so a reload can't reset the safety hold back to a fresh 60s.
    if (p && p.state === "rp-swap") setRpSwap({ port_changed: p.port_changed, url_changed: p.url_changed, path_changed: p.path_changed, old_url: p.old_url, new_url: p.new_url, old_host: p.old_host, old_port: p.old_port, new_host: p.new_host, new_port: p.new_port, nonce: p.nonce, armUntil: Date.now() + (p.arm_secs != null ? p.arm_secs : 60) * 1000 });
    // Recover an in-progress docker restart-safe change after a reload — step 1 (awaiting Confirm/Revert), continuing
    // the SAME arming countdown the server reports.
    else if (p && p.state === "docker-restart") setDockerRestart({ nonce: p.nonce, url_changed: p.url_changed, old_url: p.old_url, new_url: p.new_url, port: p.port, port_move: p.port_move, armUntil: Date.now() + (p.arm_secs != null ? p.arm_secs : 20) * 1000, error: p.dryrun_failed ? (p.message || "") : "" });
    // The new container came up in "awaiting reachability" — THIS page reaching the panel here IS the proof, so commit
    // (clears the marker + stands the auto-revert timer down). If it can't reach the panel it never gets here → auto-revert.
    else if (p && p.state === "docker-awaiting" && p.nonce) api.post("/api/access/docker-commit", { nonce: p.nonce }).catch(() => {});
    }).catch(() => {}); }, []);
  // The Confirm button is held disabled until rpSwap.armUntil (an absolute clock deadline), so the operator has time
  // to open the new address + verify their proxy first. Anchoring to a deadline (not a from-60 counter) means a page
  // reload continues the same countdown — the server tells us the remaining time on recovery.
  useEffect(() => {
    if (!rpSwap) { setRpArmIn(0); return; }
    const until = rpSwap.armUntil || (Date.now() + 60000);
    const tick = () => setRpArmIn(Math.max(0, Math.ceil((until - Date.now()) / 1000)));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [rpSwap]);
  // Docker-flip reconnect hold: tick down to 0, then the reconnect button arms (gives the container time to restart)
  useEffect(() => {
    if (dockerArm <= 0) return;
    const t = setTimeout(() => setDockerArm(dockerArm - 1), 1000);
    return () => clearTimeout(t);
  }, [dockerArm]);
  // The "Confirm & restart" button is held disabled until dockerRestart.armUntil so ONLINE nodes sync at least once
  // and learn the new address (they now dual-connect) BEFORE the recreate — anchored to a deadline so a reload
  // continues the same countdown (the server reports the remaining arm_secs on recovery).
  useEffect(() => {
    if (!dockerRestart) { setDrArmIn(0); return; }
    const until = dockerRestart.armUntil || (Date.now() + 20000);
    const tick = () => setDrArmIn(Math.max(0, Math.ceil((until - Date.now()) / 1000)));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [dockerRestart]);
  // Pull the CURRENT saved config back into the form (+ baseline) — used after a revert, where the backend rolled
  // the bind back to the live one, so the form never keeps showing a value the panel rejected.
  const resync = async () => {
    const r = await api.get("/api/state").catch(() => null);
    const ps = ((r || {}).data || {}).panel_settings;
    if (ps) { Store.panelSettings = ps; bus.emit(); }   // refresh the GLOBAL store too, so a remount/reload can't rehydrate the rejected value the apply rolled back
    const a = (ps || {}).access || {};
    const pp = a.panel || {}, ss = a.sub || {}, tt = a.tls || {};
    setPUrl(normPublicUrl(pp.url || "")); setPHost(pp.host || "0.0.0.0"); setPPort(String(pp.port || 443));
    setSUrl(ss.url || ""); setSHost(ss.host || "0.0.0.0"); setSPort(String(ss.port || 8444));
    setMode(tt.mode || ""); setEmail(tt.email || "");
    setOrig({ pUrl: normPublicUrl(pp.url || ""), pHost: pp.host || "0.0.0.0", pPort: String(pp.port || 443),
      sUrl: ss.url || "", sHost: ss.host || "0.0.0.0", sPort: String(ss.port || 8444), mode: tt.mode || "", email: tt.email || "" });
  };
  // poll the apply state machine while a change is in flight. When it's ready to confirm, we DON'T auto-navigate:
  // an unreachable new address would strand the operator, and a cross-origin reachability probe is blocked by our
  // own CSP — so we surface a "Confirm on the new address" link (opened in a new tab, a top-level navigation CSP
  // doesn't block). The new tab's SPA POSTs the confirm; this tab keeps polling and reports saved / reverted.
  useEffect(() => {
    if (!polling) return; let live = true, timer;
    const tick = async () => {
      const r = await api.get("/api/access/status"); if (!live) return;
      if (r && r.ok) {
        const p = r.panel || {}, s = r.sub || {};
        const dp = didPanelRef.current, ds = didSubRef.current;   // react ONLY to a service this save actually changed — the shared status keeps each one's LAST result, so it's stale for the other
        if (dp && p.state === "verifying" && p.redirect) {
          setConfirmUrl(p.redirect);   // show the confirm affordance (rendered in the card); the operator opens it to prove the new address is reachable
          setConfirmVerified(p.verified !== false);   // false = the gate FAILED-OPEN (couldn't reach the new address) → Confirm is unverified, warn
          let h = p.redirect; try { h = new URL(p.redirect).host; } catch (_) {}
          setMsg(p.verified === false
            ? { ok: false, t: T("Couldn't verify {v1} answers yet — it may still be warming up. You can open it to confirm, but if it doesn't load, cancel (nothing is committed until it answers).", { v1: h }) }
            : { ok: true, t: T("Confirming the new address ({v1}) — open it in a new tab so it can reach this panel. It reverts on its own if it can't be reached.", { v1: h }) });
        } else {
          setConfirmUrl("");
          const parts = [];
          if (dp && p.state === "reverted")   // pending ended without a confirm: a deliberate Cancel vs a timeout (unreachable/not opened) read differently
            parts.push(cancelledRef.current
              ? T("Change cancelled — kept the current address.")
              : T("The new address wasn't confirmed — kept the current one. Check its DNS / Cloudflare / firewall / port, then try again."));
          else if (dp && (p.state === "checking" || p.state === "issuing"))   // pre-confirm progress: reachability probe / cert issuance — not an error, not done
            parts.push(p.state === "issuing" ? (p.message || T("Issuing the certificate…")) : T("Waiting for the new address to start responding…"));
          else if (dp && p.state === "rp-swap")   // reverse-proxy swap still pending — the notice drives it; just wait for the confirm
            parts.push(T("Waiting to confirm the reverse-proxy change…"));
          else if (dp && p.state && p.state !== "idle") parts.push(T("Panel: {v1}", { v1: p.message || p.state }));
          if (ds && subsOn && s.state && s.state !== "idle") parts.push(T("Subscriptions: {v1}", { v1: s.message || s.state }));
          const fail = (dp && ["failed", "reverted"].includes(p.state)) || (ds && s.state === "failed");
          if (parts.length) setMsg({ ok: !fail, t: parts.join(" · ") });
        }
        const fail = (dp && ["failed", "reverted"].includes(p.state)) || (ds && s.state === "failed");
        const done = (!dp || ["saved", "failed", "reverted", "idle"].includes(p.state)) && (!ds || ["saved", "failed", "reverted", "idle"].includes(s.state));
        if (done) { setPolling(false); setBusy(false); setConfirmUrl(""); setRpSwap(null);   // clear busy too — a non-navigating finish (revert) reloads nothing, so the Save button would otherwise stay stuck on "Saving…"
          if (fail) {
            // The server reverted the live bind/cert, but the SAVED url is still the new (unreachable) one — it'd be
            // advertised to nodes as the panel's address. Roll it back to what was live before, THEN resync the form.
            const rb = rollbackRef.current; rollbackRef.current = null;
            if (rb) { try { await api.panelSettings({ access: { panel: { url: rb.url, host: rb.host, port: rb.port } } }); } catch (_) {} }
            resync();    // the form was left showing the rejected value → pull the rolled-back config back in
            if (dp && (p.state === "reverted" || p.state === "failed")) {
              const cancelled = p.state === "reverted" && cancelledRef.current;   // deliberate Cancel → neutral "cancelled", not a warning to troubleshoot
              openModal(html`<${ConfirmSheet} title=${cancelled ? T("Address change cancelled") : T("Address change not confirmed")} warn=${!cancelled} confirmLabel="OK"
                body=${cancelled ? T("You cancelled the change — the panel kept the current address.") : ((p.message && p.state === "failed") ? p.message : T("The new address wasn’t confirmed, so the panel kept the current one. Check its DNS / Cloudflare / firewall / port, then try again."))}/>`);
            }
            cancelledRef.current = false;   // consumed
          } else {
            rollbackRef.current = null;
            const gs = +(p.grace_secs || 0), nu = p.new_url || "";
            if (dp && p.state === "saved") {
              if (gs > 0) {   // a REBIND: this tab may now be on the OLD address — the GLOBAL "previous address" ribbon (top of every screen) guides the operator across + counts down
                openModal(html`<${ConfirmSheet} title=${T("New address confirmed")} confirmLabel=${T("Got it")}
                  body=${html`The panel is now reached at <b>${nu || T("the new address")}</b>. If this tab is on the previous address, the ribbon at the top takes you across — it keeps working while nodes move over, then stops. Switch when you’re ready.`}/>`);
              } else {        // url-only / cert-only: same bind → this address keeps working, just verified the new URL
                openModal(html`<${ConfirmSheet} title=${T("Panel address confirmed")} confirmLabel=${T("Done")}
                  body=${html`Verified — the panel is now reached at <b>${nu || T("the new address")}</b>.`}/>`);
              }
            }
          }
          return; }
      }
      timer = setTimeout(tick, 1400);
    };
    tick(); return () => { live = false; clearTimeout(timer); };
  }, [polling]);

  const presets = new Set(["0.0.0.0", "127.0.0.1", ...ips.map(x => x.ip)]);
  const ipOpts = (host, withLocal) => [
    ...(withLocal ? [{ value: "127.0.0.1", label: T("127.0.0.1 — local only") }] : []),
    ...ips.map(x => ({ value: x.ip, label: `${x.ip} — ${x.iface}` })),
    { value: "0.0.0.0", label: T("0.0.0.0 — any IP") },
    { value: "__custom", label: T("Custom IP…") }];
  const cfMode = (mode === "cloudflare" || mode === "cf15");
  const behindProxy = (mode === "" || mode === "skip");   // plain HTTP → a reverse proxy fronts panel + sub; their listen host:port is internal (nginx upstream), not a public address
  // THE host port a service is reached at: the process bind on bare-metal, the published port on docker.
  // Direct TLS makes the url's port and that socket one thing, so the url owns it and no Port field is shown;
  // behind a proxy the two are independent (the proxy bridges them) and the field is authoritative. A url with no
  // port means the scheme default, matching _compute_public_url server-side. The empty-url branch is load-bearing:
  // a fresh install has access.sub.url = "" with port 8444, and deriving 443 from "" reports dirty on load.
  const _hostPortN = (url, rawPort, dflt) => {
    const stored = parseInt(rawPort) || dflt;
    const t = (url || "").trim();
    const n = (behindProxy || !t) ? stored : (parseInt(urlPortOf(t), 10) || (/^http:\/\//i.test(t) ? 80 : 443));
    return Math.max(1, Math.min(65535, n));
  };
  const _pPortN = () => _hostPortN(pUrl, pPort, 443);
  const _sPortN = () => _hostPortN(sUrl, sPort, 8444);
  // Cloudflare only proxies a fixed set of HTTPS ports, and the port that must be in that set is the one CLIENTS
  // reach — the derived host port, not the raw field. cf15 puts this into `blocked`, so it gates, not hints.
  const pBad = cfMode && !CF_HTTPS_PORTS.includes(_pPortN());
  const sBad = subsOn && cfMode && !CF_HTTPS_PORTS.includes(_sPortN());
  // A port outside 1–65535 is invalid on ANY mode. Block it here — otherwise the port silently clamps to 65535 on
  // save while the URL keeps the out-of-range :port, a url/bind desync the change then fails on. (Server rejects too.)
  const _portRangeBad = p => { const s = String(p == null ? "" : p).trim(); return !!s && (!/^\d+$/.test(s) || +s < 1 || +s > 65535); };
  // Behind a proxy the field is authoritative, so range-check what was typed. In direct mode the port comes from
  // the url, so check the url's port text — an out-of-range :99999 must not clamp silently to 65535 on save.
  const pPortRangeBad = behindProxy ? _portRangeBad(pPort) : _portRangeBad(urlPortOf(pUrl));
  const sPortRangeBad = subsOn && (behindProxy ? _portRangeBad(sPort) : _portRangeBad(urlPortOf(sUrl)));
  const hard = mode === "cf15";                                   // cf15 origin certs ONLY work behind CF → block
  // Direct TLS (not behind a proxy) → this service terminates its own TLS and is reached DIRECTLY, so a loopback
  // listen IP isn't publicly reachable (Cloudflare/clients can't hit 127.0.0.1) → 521. Only valid behind a proxy.
  const _isLoopback = (h) => /^(127\.\d|::1|localhost)/i.test((h || "").trim());
  const pLoopbackDirect = !behindProxy && _isLoopback(pHost);
  const sLoopbackDirect = subsOn && !behindProxy && _isLoopback(sHost);
  // Crossing proxy → direct TLS: fold the internal port into the url, so the address the operator was already
  // serving carries over into direct mode (where the url owns the port — see _hostPortN). The url and the port
  // are never mirrored otherwise; one writable copy of the number, per mode.
  const setModeLinked = m => {
    const toDirect = !(m === "" || m === "skip"), wasProxy = behindProxy;
    setMode(m);
    if (toDirect && wasProxy) { setPUrl(withUrlPort(pUrl, pPort)); if (subsOn) setSUrl(withUrlPort(sUrl, sPort)); }
  };
  const wasBehindProxy = (orig.mode === "" || orig.mode === "skip");
  const modeFlip = behindProxy !== wasBehindProxy;                      // the Type change crosses the reverse-proxy ↔ direct-TLS line (the panel's own socket flips HTTP↔HTTPS)
  const flipToTls = modeFlip && !behindProxy;                           // reverse proxy → direct TLS (panel starts terminating its own TLS)
  const blocked = (hard && (pBad || sBad)) || pLoopbackDirect || sLoopbackDirect || pPortRangeBad || sPortRangeBad;
  // ONE-AT-A-TIME cooldown: while a previous address change is verifying or gracing out, Save is locked — the
  // only allowed action is Cancel. Server-enforced too (a stray apply gets a 'cooldown' 409); this just mirrors it.
  const cooldown = Store.accessCooldown || { secs: 0, reason: "" };
  const cooldownActive = (cooldown.secs || 0) > 0;                          // Save is locked on EVERY tab during a change
  const showCooldownNotice = cooldownActive && !confirmUrl && !rpSwap && !dockerRestart && !polling && !busy;   // only surface the notice where THIS tab isn't already driving the change — the driver shows its own progress ("Waiting…") then the confirm area, so confirm always wins the race over the generic cooldown

  const ipField = (host, setHost, withLocal, bad) => {
    const val = presets.has(host) ? host : "__custom";
    return html`<div class="field"><label>${T("Listen IP")}${bad ? html` <span class="ciw" title=${T("Loopback isn't reachable with direct TLS")}><${Ic} i="warn"/></span>` : null}</label>
      <div style=${bad ? "border-radius:8px;box-shadow:0 0 0 3px color-mix(in srgb,var(--dangling) 40%,transparent)" : ""}><${Dropdown} value=${val} onChange=${v => setHost(v === "__custom" ? (presets.has(host) ? "" : host) : v)}
        options=${ipOpts(host, withLocal)}/></div>
      ${val === "__custom" ? html`<input class=${"mt8" + (bad ? " bad" : "")} type="text" placeholder="e.g. 203.0.113.5" value=${host} onInput=${e => setHost(e.target.value)}/>` : null}</div>`;
  };
  const portField = (port, setPort, bad, badTitle) => html`<div class="field"><label>${T("Internal port")}${bad ? html` <span class="ciw" title=${badTitle || T("Cloudflare can't reach this port")}><${Ic} i="warn"/></span>` : null}</label>
    <input class=${bad ? "bad" : ""} type="text" value=${port} onInput=${e => setPort(e.target.value)}/></div>`;
  const loopNote = (which) => html`<div class="notice err"><${Ic} i="warn"/><span>
    ${Trich("*Loopback won't work with direct TLS.* The {which} terminates its own TLS and is reached *directly* — Cloudflare / clients connect straight to this box — so a `127.0.0.1` Listen IP isn't reachable from outside and fails publicly (Cloudflare shows *521*). Set the Listen IP to `0.0.0.0` (a public interface). Loopback is only correct *behind a reverse proxy* (TLS mode “None”). Save is disabled until this is fixed.", { which })}</span></div>`;
  // Reverse-proxy ↔ direct-TLS is a COORDINATED CUTOVER: the panel and the proxy can't both hold the public port,
  // so one has to make way for the other. Spell out exactly what the operator must do around the Save.
  const flipNote = () => html`<div class="notice warn" style="margin:0 0 14px"><${Ic} i="warn"/><div style="min-width:0">
    ${flipToTls
      ? Trich("*Switching to direct TLS — a coordinated cutover.* The panel will terminate its *own* TLS on *{addr}* — with direct TLS the port comes from the *Public URL* (there is no separate internal port), so put the port clients reach in the URL and set the Listen IP to a *public* address (`0.0.0.0`). Your reverse proxy currently owns that port — *free it first* (stop nginx/Caddy there); the panel and the proxy can't both hold it. On Save the panel binds the new HTTPS address *alongside* the current one and you confirm from it — nodes then reach the panel directly. Nothing is dropped until you confirm.", { addr: (pHost.trim() || "0.0.0.0") + ":" + _pPortN() })
      : Trich("*Switching to a reverse proxy — a coordinated cutover.* The panel will serve *plain HTTP* on *{addr}* for your proxy to front. Behind a proxy the listen address is its own setting — an *Internal port* field appears below; set it and the Listen IP to `127.0.0.1`, and leave the Public URL as the address your proxy serves. Stand up nginx/Caddy to terminate TLS and `proxy_pass` to that address (sample below), then confirm — the panel keeps serving its current direct-TLS address until you do.", { addr: (pHost.trim() || "127.0.0.1") + ":" + _pPortN() })}
    </div></div>`;
  const cfNote = html`<div class=${"notice " + (hard ? "err" : "warn")}><${Ic} i="warn"/><span>
    ${T("Cloudflare's proxy only reaches origin HTTPS on {ports}.", { ports: CF_HTTPS_PORTS.join(", ") })} ${hard ? T("A cf15 origin certificate is only valid behind Cloudflare, so this port won't work — pick one of those.") : T("If this panel is behind Cloudflare, this port won't be reachable.")}<br/>
    ${T("If it IS behind Cloudflare, restrict this port to Cloudflare's IP ranges:")}<br/>
    <button class="btn btn-mini mt8" onClick=${() => copy(CF_IP_RANGES.join("\n"), T("Cloudflare IP ranges"))}><${Ic} i="copy"/> ${T("Copy Cloudflare IP ranges")}</button></span></div>`;

  // ── ONE action. The operator never chooses "save" vs "apply" or an order: this saves the config, then runs
  //    exactly the live-applies the change requires, safely. A panel address/cert change is applied with the
  //    dual-listen + browser-confirm dance (a wrong value auto-reverts — it can never lock you out). ──
  // canonical public URL for change-detection/save: behind a proxy the URL's external port stays; with direct TLS
  // it's stripped (the listen Port field owns the port), so a portless↔ported URL isn't seen as a spurious change.
  const _canonUrl = raw => normPublicUrl(raw);   // URLs always keep their port (normPublicUrl only hides the scheme-default 443/80)
  const panelBindChanged = () => (pHost.trim() || "0.0.0.0") !== (orig.pHost || "0.0.0.0") || _pPortN() !== _origPPortN();
  const panelUrlChanged  = () => _canonUrl(pUrl) !== _canonUrl(orig.pUrl);   // the public address everyone dials — a change is verified (confirm) before it takes over
  const subBindChanged   = () => (sHost.trim() || "0.0.0.0") !== (orig.sHost || "0.0.0.0") || _sPortN() !== _origSPortN();
  const subUrlChanged    = () => _canonUrl(sUrl) !== _canonUrl(orig.sUrl);   // the sub public URL's path is swg-sub's mount base → a change must restart it
  const certChanged      = () => mode !== (orig.mode || "") || email.trim() !== (orig.email || "") || !!cfTok || !!cfOrig;
  const urlChanged       = () => pUrl.trim() !== (orig.pUrl || "") || sUrl.trim() !== (orig.sUrl || "");
  const dirty            = () => panelBindChanged() || subBindChanged() || certChanged() || urlChanged();
  // Pull the CURRENT saved settings from the store (kept fresh by the /api/state poll) into the form + baseline —
  // like resync() but with no fetch. Used to silently correct a form whose baseline drifted behind the server.
  const _storeAccess = () => (((Store.panelSettings || {}).access) || {});
  const _serverBaseline = () => { const a = _storeAccess(), pp = a.panel || {}, ss = a.sub || {}, tt = a.tls || {};
    return { pUrl: normPublicUrl(pp.url || ""), pHost: pp.host || "0.0.0.0", pPort: String(pp.port || 443),
      sUrl: ss.url || "", sHost: ss.host || "0.0.0.0", sPort: String(ss.port || 8444), mode: tt.mode || "", email: tt.email || "" }; };
  const resyncFromStore = () => { const b = _serverBaseline();
    setPUrl(b.pUrl); setPHost(b.pHost); setPPort(b.pPort); setSUrl(b.sUrl); setSHost(b.sHost); setSPort(b.sPort); setMode(b.mode); setEmail(b.email); setOrig(b); };
  // Detect the SAVED address settings changing out from under this open form — a rollback (an aborted combined
  // save, or the blessed-startup boot reconcile), or a change confirmed on another tab. A stale port/url left in
  // the fields would otherwise ride along on the next Save (exactly the phantom-port-change trap). If the form is
  // CLEAN we adopt the true values; if the operator has UNSAVED edits we warn instead of clobbering them.
  useEffect(() => {
    if (busy || polling || rpSwap || dockerRestart || confirmUrl) return;   // an in-flight change owns the form
    if (!((Store.panelSettings || {}).access || {}).panel) return;    // store not populated yet → never resync to blanks
    if (JSON.stringify(_serverBaseline()) === JSON.stringify(orig)) { if (staleWarn) setStaleWarn(false); return; }
    if (!dirty()) { resyncFromStore(); if (staleWarn) setStaleWarn(false); }
    else if (!staleWarn) setStaleWarn(true);
  });
  // Contention: the two services would trade ports on one host, so applying both at once needs one to bind a
  // port the other still holds — a single host can't do that atomically. Detect it and guide two saves instead
  // of attempting a doomed order (which is what produced the "Address already in use" + both-on-443 mess).
  const _overlap = (a, b) => { a = (a || "").trim() || "0.0.0.0"; b = (b || "").trim() || "0.0.0.0"; return a === b || a === "0.0.0.0" || b === "0.0.0.0"; };
  // Compare derived-against-derived: in direct mode `orig.pPort` is the stored value while the live figure comes
  // from the url, so a raw stored number would mis-fire this guard in both directions.
  const _origPPortN = () => _hostPortN(orig.pUrl, orig.pPort, 443);
  const _origSPortN = () => _hostPortN(orig.sUrl, orig.sPort, 8444);
  const subWantsPanelLive = () => subsOn && subBindChanged() && _sPortN() === _origPPortN() && _overlap(sHost, orig.pHost);   // sub's target is the panel's current port
  const panelWantsSubLive = () => subsOn && panelBindChanged() && _pPortN() === _origSPortN() && _overlap(pHost, orig.sHost); // panel's target is the sub's current port

  // Wait for an in-flight subscription apply to reach a terminal state — so the panel apply below never binds
  // a port while the sub is still vacating it (the race that surfaced as "Address already in use").
  const _awaitSub = async () => {
    for (let i = 0; i < 60; i++) {                 // ~90s cap (a cert issuance can be slow); most settle in a few s
      const r = await api.get("/api/access/status").catch(() => null);
      const s = (r && r.sub) || {};
      if (["saved", "failed", "reverted", "idle"].includes(s.state)) return s;
      await new Promise(res => setTimeout(res, 1500));
    }
    return { state: "unknown", message: T("The subscription update didn't finish in time.") };
  };

  const saveAndApply = async () => {
    // Scroll the status/confirm area (top of the card) into view — the Save button lives in the footer, so the
    // result (a status line, a proxy-confirm card, or a validation error) would otherwise land off-screen above.
    // Clear the sticky header stack (appbar + the optional old-address ribbon) so the banner isn't hidden under it.
    requestAnimationFrame(() => {
      const c = document.querySelector(".acctls"); if (!c) return;
      let off = 0; document.querySelectorAll(".appbar, .addr-old-ribbon").forEach(el => { const cs = getComputedStyle(el); if (cs.position === "sticky" || cs.position === "fixed") off += el.getBoundingClientRect().height; });
      window.scrollTo({ top: Math.max(0, c.getBoundingClientRect().top + window.scrollY - off - 12), behavior: "smooth" });
    });
    if (blocked) return setMsg({ ok: false, t: T("Fix the highlighted port first.") });
    if (!dirty()) return;
    // Trading ports between panel and sub can't be done in one shot on a single host — one must free its port
    // before the other can take it. Guide the operator through two saves instead of attempting a doomed order.
    if (subWantsPanelLive() || panelWantsSubLive()) {
      if (subWantsPanelLive() && panelWantsSubLive())
        return setMsg({ ok: false, t: T("The panel and subscription are swapping ports — a single host can't swap two ports at once. First move one of them to a spare free port and Save, then set both to their final ports and Save again.") });
      const first = subWantsPanelLive() ? T("the panel") : T("the subscription server");
      const second = subWantsPanelLive() ? T("the subscription server") : T("the panel");
      return setMsg({ ok: false, t: `The panel and subscription are trading ports. Do it in two saves so one frees the port before the other takes it: first move ${first} and Save, then set ${second}'s port and Save again.` });
    }
    const needSub = subsOn && (subBindChanged() || certChanged() || subUrlChanged());   // sub-URL change → new mount base → swg-sub must re-read it
    const pBindChg = panelBindChanged(), pUrlChg = panelUrlChanged();   // capture BEFORE setOrig resets them → so the post-save proxy guidance knows what changed
    const needPanel = pBindChg || certChanged() || pUrlChg;
    didPanelRef.current = needPanel; didSubRef.current = needSub;   // so the status poll reacts only to what THIS save changes (the shared status is stale for the other)
    cancelledRef.current = false;   // fresh apply — a later revert is a timeout unless the operator clicks Cancel
    setBusy(true); setMsg({ ok: true, t: T("Saving your changes…") });
    // No fold: the url is what the operator typed, and in direct mode it already carries the port (it IS the port).
    // Folding a separate Port field in was the backstop for the old two-copies design; with one source of truth it
    // could only ever overwrite the url with a stale number.
    const npUrl = normPublicUrl(pUrl), nsUrl = normPublicUrl(sUrl);
    setPUrl(npUrl); setSUrl(nsUrl);                                    // reflect it back in the fields
    const r = await api.panelSettings({ access: {
      panel: { url: npUrl, host: pHost.trim() || "0.0.0.0", port: _pPortN() },
      sub: { url: nsUrl, host: sHost.trim() || "0.0.0.0", port: _sPortN() },
      tls: { mode, email: email.trim(), cf_token: cfTok, cf_origin_token: cfOrig } } });
    if (!r || r.ok === false) { setBusy(false); return setMsg({ ok: false, t: (r && (srvText(r) || (r.errors || []).join("; "))) || T("Save failed.") }); }
    const rtls = ((r.data || {}).access || {}).tls || {};        // redacted echo → refresh the "(set)" markers
    setHasCfTok(!!rtls.has_cf_token); setHasCfOrig(!!rtls.has_cf_origin_token); setCfTok(""); setCfOrig("");
    // remember the address that was live before this apply — if the new one doesn't confirm, we re-save this so the
    // panel's canonical url (advertised to nodes) rolls back with the bind/cert the server already reverts.
    if (needPanel) rollbackRef.current = { url: orig.pUrl, host: orig.pHost || "0.0.0.0", port: +orig.pPort || 443 };
    setConfirmUrl(""); setDockerFlip(""); setDockerArm(0); setDockerFlipPort(0);
    setOrig({ pUrl: npUrl, pHost: pHost.trim() || "0.0.0.0", pPort: String(_pPortN()),
      sUrl: nsUrl, sHost: sHost.trim() || "0.0.0.0", sPort: String(_sPortN()), mode, email: email.trim() });
    // subscription server first (a background restart — it can never lock you out of the panel). Don't start
    // polling yet: the panel apply below arms its pending, and we want the very first poll tick to already see
    // it (so the confirm-redirect fires immediately, not after a wasted interval).
    // …or when its certificate is missing/wrong, even though the address is unchanged: apply-sub is what issues
    // it, so without this a broken cert could only be repaired by editing the address to something else and back.
    // Direct TLS only — Store.subCert is {} behind a reverse proxy, where the cert isn't ours to issue.
    if (needSub || (Store.subCert || {}).needs_issue) {
      setMsg({ ok: true, t: T("Updating the subscription server…") });
      await api.post("/api/access/apply-sub", {});
      const ss = await _awaitSub();               // let it settle before the panel apply — no bind race
      if (ss.state === "failed") {
        setBusy(false);
        // The sub step failed, so we ABORT before applying the panel — but its NEW address was already saved up-front
        // and would sit AHEAD of the (unchanged) live panel: a restart would then adopt a url/base/port that never
        // took, the exact mismatch we guard against. And the sub self-healed its bind but its saved url is still new.
        // Roll the SAVED panel+sub config back to the pre-change (== live) values — a partial access block merges,
        // keeping tls — THEN resync, so nothing is left ahead of what's actually running.
        try {
          await api.panelSettings({ access: {
            panel: { url: orig.pUrl, host: orig.pHost || "0.0.0.0", port: +orig.pPort || 443 },
            sub: { url: orig.sUrl, host: orig.sHost || "0.0.0.0", port: +orig.sPort || 8444 } } });
        } catch (_) {}
        await resync();
        return setMsg({ ok: false, t: T("{v1} No panel change was applied — settings rolled back.", { v1: ss.message || T("The subscription server couldn't be updated.") }) });
      }
    }
    // then the panel address/cert (dual-listen + confirm — the operator confirms by opening the new address)
    if (needPanel) {
      const rp = await api.post("/api/access/apply", {});
      if (rp && rp.ok === false) { setBusy(false); await resync(); return setMsg({ ok: false, t: srvText(rp) || T("Couldn't apply the panel address.") }); }
      if (rp && rp.docker_restart) {   // Docker restart-safe change, step 1: nodes now dual-connect to the new address; the operator reviews, then Confirm & restart (dry-run + recreate) or Revert. NOTHING is recreated yet — no dual-listen is possible in a single container, so the recreate waits until Confirm.
        const d = rp.docker_restart; setBusy(false);
        setDockerRestart({ nonce: d.nonce, url_changed: d.url_changed, old_url: d.old_url, new_url: d.new_url, port: d.port, port_move: d.port_move, armUntil: Date.now() + (d.arm_secs != null ? d.arm_secs : 20) * 1000, error: "" });
        return setMsg({ ok: true, t: d.port_move ? T("Saved — review, then Confirm & restart below (you'll re-point your reverse proxy to the new port).") : T("Saved — the nodes are learning the new address. Review, then Confirm & restart below (or Revert).") });
      }
      if (rp && rp.rp_swap) {   // unified reverse-proxy swap (port and/or url and/or path) → both old+new serve; operator re-points the proxy then confirms below
        const s = { ...rp.rp_swap, armUntil: Date.now() + 60000 }; setRpSwap(s); setBusy(false);   // fresh swap → full 60s arming hold
        const bits = [];
        if (s.port_changed) bits.push(T("both ports"));
        if (s.url_changed) bits.push(T("the old and new address"));
        return setMsg({ ok: true, t: T("Saved — the panel now serves {v1}. Update your reverse proxy, then confirm below.", { v1: bits.join(" + ") || T("the change") }) });
      }
      if (rp && !rp.applied) {    // a live bind/cert change is in progress → the status poll surfaces a Confirm link on the first tick
        setMsg({ ok: true, t: T("Preparing the new panel address…") });
        setPolling(true); return;
      }
    }
    if (needSub) setPolling(true);   // no panel redirect — just watch the sub restart finish
    setBusy(false);
    setMsg({ ok: true, t: needSub ? T("Saved & applying — the subscription server is restarting.") : (needPanel ? (behindProxy ? T("Saved — the reverse proxy serves this URL; nothing to restart.") : "Saved & applied.") : "Saved.") });
  };

  // Report state up to the settings footer (which owns the Save button + status line, like every other section).
  // Runs after each render; the parent only re-renders when a DISPLAYED bit actually changes (see onAccess).
  useEffect(() => { if (onChange) onChange({ dirty: dirty() && !blocked && !cooldownActive, busy: busy || polling, msg, run: saveAndApply }); });

  // Abort a change that's still VERIFYING (not yet confirmed) — the server drops the un-confirmed listener /
  // restores the cert and rolls the saved url back. The only other option during verifying is to confirm it.
  const cancelChange = async () => {
    cancelledRef.current = true;   // so the reverted-state message/modal reads "cancelled", not the "check DNS/firewall" troubleshooting copy
    try {
      const r = await api.post("/api/access/cancel", {});
      if (!r || r.ok === false) { cancelledRef.current = false; toast(srvText(r) || T("Couldn't cancel the change."), "err"); }   // cancel didn't take → a later timeout-revert should read as a failure, not "cancelled"
      else toast(T("Change cancelled — kept the current address."), "ok");
    } catch (_) { cancelledRef.current = false; toast(T("Couldn't cancel the change."), "err"); }
    // the polling loop sees the reverted state and clears the confirm affordance + resyncs the form
  };
  // Confirm a unified reverse-proxy swap. If the PUBLIC URL changed, we prove the proxy routes the new address here
  // by opening it in a new tab — its SPA POSTs the confirm THROUGH the proxy on the new host/path (the browser proof;
  // this also drops the old port for a combined change). If ONLY the internal port changed (browser can't reach it),
  // the operator vouches via confirm-proxy. Either way, THIS tab polls status and reports the outcome.
  const confirmRpSwap = () => {
    if (!rpSwap) return;
    if (rpSwap.url_changed) {
      const base = String(rpSwap.new_url || "").replace(/\/+$/, "");
      if (!base || !rpSwap.nonce) return;
      window.open(base + "/?__applyurl=" + encodeURIComponent(rpSwap.nonce), "_blank", "noopener");
      setPolling(true);
      setMsg({ ok: true, t: T("Opened the new address to confirm your proxy routes it here. If it loads there, the switch completes and nodes move over.") });
      return;
    }
    // pure internal-port change → the confirm proves the proxy is on the new port (it travels through the proxy);
    // the server drops the old port only if this request arrived on the new listener, else it refuses (no lockout).
    (async () => {
      setBusy(true);
      try {
        const r = await api.post("/api/access/confirm-proxy", {});
        if (!r || r.ok === false) {
          const em = srvText(r) || T("Couldn't confirm.");
          setBusy(false); toast(em, "err");
          if (r && r.code === "proxy_not_switched") setMsg({ ok: false, t: em });   // prominent: fix the proxy then retry — the swap stays pending, nothing was dropped
          return;
        }
        setRpSwap(null); await resync(); setBusy(false);
        setMsg({ ok: true, t: T("Done — the panel is now on the new port only.") });
        toast(T("Old port dropped — panel is on the new port."), "ok");
      } catch (_) { toast(T("Couldn't confirm."), "err"); setBusy(false); }
    })();
  };
  // Guarded entry to confirmRpSwap: a modal that spells out exactly what's about to change and the real risk — a
  // wrong web-server (nginx / Caddy / …) config can LOCK YOU OUT (the old address stops, the new one won't answer).
  // Only "Proceed" runs the confirm. (The button that opens this is itself held for 60s — see rpArmIn.)
  const confirmRpSwapGuarded = () => {
    if (!rpSwap) return;
    const bits = [];
    if (rpSwap.port_changed) bits.push(html`<li>${Trich("The old internal port *{old}* *stops serving* — your proxy must already forward to *{new}*.", { old: rpSwap.old_port, new: (rpSwap.new_host || "127.0.0.1") + ":" + rpSwap.new_port })}</li>`);
    if (rpSwap.url_changed) bits.push(html`<li>${Trich("I open *{url}* in a new tab — it's adopted *only if it loads there* and reaches this panel. Nodes then move to it.", { url: rpSwap.new_url })}</li>`);
    openModal(html`<${ConfirmSheet} title=${T("Finish the reverse-proxy switch?")} warn=${true}
      confirmLabel=${rpSwap.url_changed ? T("Proceed — open the new address") : T("Proceed — drop the old port")} cancelLabel=${T("Not yet")}
      body=${html`<div>${T("On Proceed:")}</div><ul style="margin:6px 0 10px;padding-left:18px">${bits}</ul>
        <div style="color:var(--dangling)">${Trich("*⚠️ You can lose access to the panel.* If your web server (nginx / Caddy / Traefik / …) isn't already routing the new address to this panel — wrong upstream port, missing `server_name`, or missing `location` — the old address stops and the new one won't answer.")}</div>
        <div style="margin-top:8px">${Trich("Before proceeding, confirm *{addr}* actually opens the panel. If anything's off, cancel and fix your proxy first — *nothing has changed yet*.", { addr: rpSwap.url_changed ? rpSwap.new_url : ((rpSwap.new_host || "127.0.0.1") + ":" + rpSwap.new_port) })}</div>`}
      onConfirm=${() => confirmRpSwap()}/>`);
  };
  // ...or back out: tear down whatever the swap added (new port / new path / new-url candidate); the old address
  // never stopped serving, so nodes stay put.
  const revertRpSwap = async () => {
    setBusy(true);
    try {
      const r = await api.post("/api/access/cancel", {});
      if (!r || r.ok === false) { toast(srvText(r) || T("Couldn't revert."), "err"); setBusy(false); return; }
      setRpSwap(null); await resync(); setBusy(false);
      setMsg({ ok: true, t: T("Reverted — the panel stays on the current address.") });
      toast(T("Reverted — kept the current address."), "ok");
    } catch (_) { toast(T("Couldn't revert."), "err"); setBusy(false); }
  };
  // Docker restart-safe change, step 2: Confirm & restart. The server first DRY-RUNS the new settings in a throwaway
  // container (issue+verify the cert, check the port is free); only on success does it recreate the live container.
  // A dry-run failure changes nothing — we keep the card and show why, so the operator can fix it and retry, or revert.
  const confirmDockerRestart = async () => {
    if (!dockerRestart) return;
    setBusy(true); setMsg({ ok: true, t: T("Checking the new address (dry-run)…") });
    try {
      const r = await api.post("/api/access/docker-confirm", { nonce: dockerRestart.nonce });
      if (r && r.docker_recreate) {   // dry-run passed → the container is recreating onto the new address; show the reconnect hold
        setDockerRestart(null); setDockerFlip(r.new_url || dockerRestart.new_url || ""); setDockerFlipPort(r.port_move ? (r.port || dockerRestart.port || 0) : 0); setDockerArm(20); setBusy(false);
        return setMsg({ ok: true, t: r.message || T("Restarting the panel container. Reconnect at {v1} once it's back.", { v1: r.new_url || dockerRestart.new_url }) });
      }
      setBusy(false);
      // ONE rendering, in the confirm box — that is where Confirm/Revert live, so the failure belongs beside the
      // actions it applies to. Setting the page banner to the SAME string as well showed the identical sentence
      // twice on one screen (three times, with the box's own lead-in and trailing hint duplicating the server's).
      setDockerRestart({ ...dockerRestart, error: srvText(r) || T("The panel couldn't verify the new address.") });
      return setMsg(null);
    } catch (_) { setBusy(false); setMsg({ ok: false, t: T("Couldn't run the dry-run.") }); }
  };
  // Revert step 1 before any recreate: drop the candidate the nodes were dual-connecting to and roll settings back.
  // Everything step 1 did was additive, so this is an instant, safe no-op for the live panel.
  const revertDockerRestart = async () => {
    setBusy(true);
    try {
      const r = await api.post("/api/access/docker-revert", {});
      if (!r || r.ok === false) { toast(srvText(r) || T("Couldn't revert."), "err"); setBusy(false); return; }
      setDockerRestart(null); await resync(); setBusy(false);
      setMsg({ ok: true, t: T("Reverted — the panel stays on the current address.") });
      toast(T("Reverted — kept the current address."), "ok");
    } catch (_) { toast(T("Couldn't revert."), "err"); setBusy(false); }
  };
  let _confHost = confirmUrl; try { _confHost = new URL(confirmUrl).host; } catch (_) {}
  return html`<div class="card acctls">
    ${(busy || msg) ? html`<div class=${"notice acc-status" + (busy || (msg && msg.ok) ? "" : " warn")} style=${"margin:0 0 14px" + (busy || (msg && msg.ok) ? ";border-color:var(--accent);background:var(--accent-dim, rgba(31,200,214,.08))" : "")}><${Ic} i=${busy ? "clock" : (msg && msg.ok ? "info" : "warn")}/><div style="min-width:0">
      ${msg ? html`<b>${msg.t}</b>` : null}
      ${busy ? html`<div class="hint" style="margin:4px 0 0">${T("Applying your change — this can take up to a minute or two. It hasn't hung; please wait.")}</div>` : null}
      ${/* Gate-wait (probing/issuing the new address, before the confirm affordance) — give the operator an escape hatch
            instead of only waiting out the auto-revert. Uniquely the PANEL apply keeps busy true through polling (a
            sub-only save clears it); the confirm card owns Cancel once confirmUrl is set. */""}
      ${(busy && polling && !confirmUrl && !rpSwap && !dockerRestart && !dockerFlip) ? html`<div style="margin-top:10px"><button class="btn btn-ghost btn-mini" onClick=${cancelChange}>${T("Cancel this change")}</button></div>` : null}
    </div></div>` : null}
    ${rpSwap ? html`<div class="notice" style="margin:0 0 14px;border-color:var(--accent);background:var(--accent-dim, rgba(31,200,214,.08))"><${Ic} i="info"/><div style="min-width:0">
      ${Trich("*Finish the reverse-proxy switch.* The panel is serving the old *and* new setup at once — each node keeps its current address and only moves once the old one stops. Update your reverse proxy to match {v1}, then confirm. Nothing goes down in between.", { v1: rpSwap.port_changed && rpSwap.url_changed ? T("(both changes below)") : "" })}
      <ul style="margin:8px 0 2px;padding-left:18px">
        ${rpSwap.port_changed ? html`<li>${Trich("Internal port {old} → {new} — point your proxy's upstream at {addr} (co-located loopback nodes follow automatically).", {
          old: html`<span class="mono" style="font-weight:700;color:var(--dangling)">${rpSwap.old_port}</span>`,
          new: html`<span class="mono" style="font-weight:700;color:var(--online)">${rpSwap.new_port}</span>`,
          addr: html`<span class="mono" style="font-weight:700;color:var(--online)">${(rpSwap.new_host || "127.0.0.1")}:${rpSwap.new_port}</span>`,
        })}</li>` : null}
        ${rpSwap.url_changed ? html`<li>${Trich("Public address {old} → {new} — {what} (copy the *panel* nginx sample below), keeping the old one live for now.", {
          old: html`<span class="mono" style="font-weight:700;color:var(--dangling)">${rpSwap.old_url}</span>`,
          new: html`<span class="mono" style="font-weight:700;color:var(--online)">${rpSwap.new_url}</span>`,
          what: rpSwap.path_changed
            ? Trich("add a location for the new path {v1}", { v1: html`<span class="mono" style="font-weight:700;color:var(--online)">${(() => { try { return new URL(rpSwap.new_url).pathname.replace(/\/+$/, "") + "/"; } catch (_) { return T("the new path"); } })()}</span>` })
            : Trich("route {v1} to this panel", { v1: html`<span class="mono" style="font-weight:700;color:var(--online)">${rpSwap.new_url}</span>` }),
        })}</li>` : null}
      </ul>
      ${rpSwap.url_changed ? html`<div class="hint" style="margin:4px 0 0">${T("On confirm the new address opens in a new tab to prove your proxy routes it here before switching nodes over; if it can't load, just revert — nothing changes.")}</div>
      <div class="notice warn" style="margin:8px 0 0"><${Ic} i="warn"/><div>${Trich("*Make sure the new address already opens this panel* (proxy upstream / `server_name` / `location`). If it doesn't, the confirm simply won't take — the old address keeps serving, so you can't be locked out.")}</div></div>` : null}
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">${rpArmIn > 0
        ? html`<button class="btn btn-primary" disabled title=${T("Take a moment to open the new address and check your proxy first")}>${T("Confirm in {n}s — verify your proxy first", { n: rpArmIn })}</button>`
        : (rpSwap.url_changed
            ? html`<a class="btn btn-primary" href=${(String(rpSwap.new_url || "").replace(/\/+$/, "")) + "/?__applyurl=" + encodeURIComponent(rpSwap.nonce || "")} target="_blank" rel="noopener" onClick=${() => { setPolling(true); setMsg({ ok: true, t: T("Opening the new address to confirm your proxy routes it here — if it loads, the switch completes and nodes move over.") }); }}>${T("Confirm — open the new address ↗")}</a>`
            : html`<button class="btn btn-primary" disabled=${busy} onClick=${confirmRpSwapGuarded}>${T("Confirm — drop the old port")}</button>`)}<button class="btn btn-ghost" disabled=${busy} onClick=${revertRpSwap}>${T("Revert")}</button></div>
    </div></div>` : null}
    ${dockerRestart ? html`<div class="notice ${dockerRestart.error ? "warn" : ""}" style=${dockerRestart.error ? "margin:0 0 14px" : "margin:0 0 14px;border-color:var(--accent);background:var(--accent-dim, rgba(31,200,214,.08))"}><${Ic} i=${dockerRestart.error ? "warn" : "info"}/><div style="min-width:0">
      ${dockerRestart.port_move
        ? Trich("*Confirm the internal-port change.* The public address doesn't change, so the nodes aren't affected — but the panel will restart onto a new internal port, so your *reverse proxy must be re-pointed* to it. When you Confirm, the panel dry-runs the new port (checks it's free), restarts onto it, then waits for you to re-point the proxy. If it stays unreachable it *rolls back to the current port automatically*.")
        : Trich("*Confirm the address change.* The nodes are now told to *also* try `{v1}`, so they're already connected there before the restart. When you Confirm, the panel first *dry-runs* the new settings in a throwaway container (issues the certificate, checks the port), and only then restarts onto the new address. If it can't be reached afterwards, it *rolls back automatically*.", { v1: dockerRestart.new_url })}
      ${dockerRestart.port_move
        ? html`<ul style="margin:8px 0 2px;padding-left:18px"><li>${Trich("New internal port `{v1}` — after Confirm, point your reverse proxy's upstream at it and reload the proxy.", { v1: dockerRestart.port })}</li></ul>`
        : dockerRestart.url_changed
        ? html`<ul style="margin:8px 0 2px;padding-left:18px"><li>${Trich("New address `{v1}` — make sure DNS / your firewall / Cloudflare route it to this panel.", { v1: dockerRestart.new_url })}</li></ul>`
        : null}
      ${dockerRestart.error ? html`<div class="notice warn" style="margin:8px 0 0"><${Ic} i="warn"/><div style="min-width:0"><b>${T("Dry-run failed.")}</b> ${srvText(dockerRestart)}</div></div>` : null}
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">${drArmIn > 0
        ? html`<button class="btn btn-primary" disabled title=${T("The nodes are still learning the new address")}>${T("Confirm & restart in {n}s…", { n: drArmIn })}</button>`
        : html`<button class="btn btn-primary" disabled=${busy} onClick=${confirmDockerRestart}>${busy ? T("Checking…") : T("Confirm & restart")}</button>`}<button class="btn btn-ghost" disabled=${busy} onClick=${revertDockerRestart}>${T("Revert")}</button></div>
    </div></div>` : null}
    ${dockerFlip ? html`<div class="notice" style="margin:0 0 14px;border:1px solid var(--accent);background:var(--accent-dim, rgba(31,200,214,.08))"><${Ic} i="clock"/><div style="min-width:0">
      ${dockerFlipPort > 0
        ? html`${Trich("*Restarting onto internal port {v1}.* Point your reverse proxy's upstream at `127.0.0.1:{v1}` and reload the proxy — this page comes back once it routes there. It confirms itself when reachable; if it stays unreachable it rolls back to the current port automatically.", { v1: dockerFlipPort })}
          <div style="margin-top:10px">${dockerArm > 0
            ? html`<button class="btn btn-primary" disabled title=${T("Waiting for the container to restart")}>${T("Restarting in {n}s…", { n: dockerArm })}</button>`
            : html`<a class="btn btn-primary" href=${dockerFlip} target="_blank" rel="noopener">${T("Reload this page ↻")}</a>`}</div>`
        : html`${Trich("*Restarting the panel container.* Reconnect at the new address once it's back — it confirms itself when you reach it. If the new address can't be reached (or the certificate can't be issued), the panel rolls back automatically to the current address.")}
          <div style="margin-top:10px">${dockerArm > 0
            ? html`<button class="btn btn-primary" disabled title=${T("Waiting for the container to restart")}>${T("Reconnect in {n}s…", { n: dockerArm })}</button>`
            : html`<a class="btn btn-primary" href=${dockerFlip} target="_blank" rel="noopener">${T("Reconnect at the new address ↗")}</a>`}</div>`}
    </div></div>` : null}
    ${confirmUrl ? html`<div class="notice ${confirmVerified ? "" : "warn"}" style=${confirmVerified ? "margin:0 0 14px;border-color:var(--accent);background:var(--accent-dim, rgba(31,200,214,.08))" : "margin:0 0 14px"}><${Ic} i=${confirmVerified ? "info" : "warn"}/><div style="min-width:0">
      ${confirmVerified
        ? html`${Trich("*Confirm the new address.* Open `{v1}` in a new tab to confirm it — the change is applied *only once* it loads there.", { v1: _confHost })}`
        : html`${Trich("*Couldn't verify the new address yet.* I probed `{v1}` from here and it didn't answer in time — it may still be warming up (a fresh Cloudflare origin can be slow), *or* it's not reachable at all (e.g. a direct-TLS panel bound to `127.0.0.1` instead of a public IP, or a port your proxy/DNS doesn't route). Open it to confirm anyway — the change applies *only if it loads*.", { v1: _confHost })}`}
      ${Trich("If that tab *can't* load, just close it: this panel stays on the current address and reverts automatically. Nothing is committed until the new address answers.")}
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap"><a class="btn btn-primary" href=${confirmUrl} target="_blank" rel="noopener">${T("Open the new address to confirm ↗")}</a><button class="btn btn-ghost" onClick=${cancelChange}>${T("Cancel this change")}</button></div>
    </div></div>` : null}
    ${showCooldownNotice ? html`<div class="notice warn" style="margin:0 0 14px"><${Ic} i="warn"/><div style="min-width:0">
      <b>${T("Operation cooldown.")}</b> ${cooldown.reason === "verifying" ? T("An address change is still waiting to be confirmed.") : Trich("The previous change is still settling (*{v1}s* left).", { v1: cooldown.secs })} ${Trich("Address changes run *one at a time* — Save is locked until it finishes. If a change is in flight, you can still cancel it from the tab that started it.")}
    </div></div>` : null}
    ${staleWarn ? html`<div class="notice warn" style="margin:0 0 14px"><${Ic} i="warn"/><div style="min-width:0">
      ${Trich("*These settings changed elsewhere.* The panel's saved address settings were updated by the server (a rollback, a boot reconcile, or a change confirmed in another tab) while you have *unsaved edits* here — so a field below may be based on an *old* value. *Reload the page* before saving, or your change could re-apply a value the panel already reverted.")} <button class="btn btn-mini" style="margin-left:6px" onClick=${() => { resyncFromStore(); setStaleWarn(false); }}>${T("Discard my edits & refresh")}</button>
    </div></div>` : null}

    <div class="seclabel" style="margin-top:0">${T("Certificate")}</div>
    <p class="hint" style="margin:0 0 12px">${T("How TLS is terminated — this decides which ports are valid below. One choice issues both certificates (the panel's and swg-sub's, always separate keys).")}</p>
    <div class="field"><label>${T("Type")}</label><${Dropdown} value=${mode} onChange=${setModeLinked} options=${TLS_MODE_OPTS()}/></div>
    ${(mode === "letsencrypt" || mode === "cloudflare") ? html`<div class="field"><label>${T("Account email")}</label><input type="text" placeholder=${T("admin@example.com")} value=${email} onInput=${e => setEmail(e.target.value)}/></div>` : null}
    ${mode === "cloudflare" ? html`<div class="field"><label>${T("Cloudflare API token")}</label><input type="password" placeholder=${hasCfTok ? T("•••••••• (set — leave blank to keep)") : T("Zone:DNS:Edit token")} value=${cfTok} onInput=${e => setCfTok(e.target.value)}/>
      <div class="hint">${T("Used for DNS-01 validation. Stored on the panel only; never sent to the browser. Enter \"-\" to clear.")}</div></div>` : null}
    ${mode === "cf15" ? html`<div class="field"><label>${T("Cloudflare Origin CA token")}</label><input type="password" placeholder=${hasCfOrig ? T("•••••••• (set — leave blank to keep)") : T("Zone:SSL and Certificates:Edit token")} value=${cfOrig} onInput=${e => setCfOrig(e.target.value)}/>
      <div class="hint">${Trich("Requests a 15-year Cloudflare Origin certificate — valid *only* behind Cloudflare's proxy. Stored on the panel only. Enter \"-\" to clear.")}</div></div>` : null}
    ${modeFlip ? flipNote() : null}

    <div class="seclabel">${T("Panel address")}</div>
    <p class="hint" style="margin:0 0 12px">${T("Where the panel itself is reached.")}${behindProxy
      ? T(" Your proxy fronts this URL and forwards to the internal address below — the two are independent.")
      : Trich(" The panel serves this address directly, so *the URL carries the port* (there is no separate internal port to set).")}</p>
    <div class="field"><label>${T("Public URL")}</label><input type="text" placeholder=${T("https://panel.example.com  or  https://example.com/swgpanel")} value=${pUrl} onInput=${e => setPUrl(e.target.value)}/></div>
    <div class="fieldrow">${ipField(pHost, setPHost, true, pLoopbackDirect)}${behindProxy
      ? portField(pPort, setPPort, pBad || pPortRangeBad, pPortRangeBad ? T("Port must be a number between 1 and 65535") : null)
      : null}</div>
    ${pLoopbackDirect ? loopNote("panel") : (pBad ? cfNote : null)}
    ${localPort > 0 ? html`<div class="localnode-note">${Trich("This box's own node reaches the panel on {v1} — a dedicated plain-HTTP loopback port, served at the root. It's set at install and a public address, port, path, or certificate change never moves it, so the co-located node never loses the panel.", { v1: html`<b class="mono">127.0.0.1:${localPort}</b>` })}</div>` : null}
    ${(behindProxy && (panelBindChanged() || panelUrlChanged())) ? html`<div class="notice" style="margin:8px 0 12px"><${Ic} i="info"/><div style="min-width:0">
      ${Trich("*Behind a reverse proxy.*")}
      ${panelBindChanged() ? Trich(" Saving binds `{v1}` *alongside* the current port (both keep serving) — you then re-point your reverse proxy and confirm to drop the old one, with no downtime. External nodes dial your public URL through the proxy, so they don't change; only a co-located node that dials the panel on `127.0.0.1` needs its `panel.url` port updated too.", { v1: (pHost.trim() || "127.0.0.1") + ":" + _pPortN() }) : null}
      ${panelUrlChanged() ? Trich(" The public URL is served by *your reverse proxy*, not the panel — make sure the proxy serves it (server_name / TLS cert / path) before relying on it. The panel's own mount path stays `SWG_PANEL_BASE`. Nodes are told this URL as their dial address, so external nodes re-point to it on their next sync — make sure they can reach it; one that can't must have its `panel.url` updated by hand.") : null}
    </div></div>`
    : panelBindChanged() ? html`<div class="notice" style="margin:8px 0 12px"><${Ic} i="info"/><div style="min-width:0">
      ${Trich("*Nodes re-point themselves.* On save, online nodes learn the new address on their next sync and switch to it — the old address stays reachable for ~3 minutes so they can. A node that is *offline* during the change (or one installed without verifying/pinning the panel cert) must be re-pointed by hand: set `panel.url` in `/etc/swg-agent/config.json` (bare-metal) or `PANEL_URL` in `.env` (docker) to the new address, then restart `swg-noded` / recreate the container.")}
    </div></div>` : null}
    ${behindProxy ? html`<details class="nginx-sample" style="margin:8px 0 4px"><summary style="cursor:pointer;color:var(--muted);font-size:.9em">${Trich("Reverse-proxy config for the panel (nginx) — full `server { }` for the values above")}</summary>
      <pre class="mono" style="white-space:pre;overflow:auto;padding:10px;border-radius:6px;background:var(--code-bg, rgba(127,127,127,.09));margin:8px 0 6px;font-size:.85em">${nginxServerBlock(pUrl, pHost, _pPortN())}</pre>
      <button class="btn btn-mini" onClick=${() => copy(nginxServerBlock(pUrl, pHost, _pPortN()), T("panel nginx server block"))}><${Ic} i="copy"/>${T("Copy")}</button>
      <div class="hint" style="margin-top:6px">${Trich("Built from the domain, external port, path (from the Public URL) and the internal listen address above. Point `ssl_certificate` at your real cert, then `nginx -t && systemctl reload nginx`.")}</div>
    </details>` : null}

    ${subsOn ? html`<div class="seclabel">${T("Subscription address")}</div>
      <p class="hint" style="margin:0 0 12px">${T("Where the swg-sub page is reached (a separate service; changing it only restarts swg-sub).")}${behindProxy
        ? "" : Trich(" As with the panel, *the URL carries the port*.")}</p>
      <div class="field"><label>${T("Public URL")}</label><input type="text" placeholder=${T("https://sub.example.com  or  https://example.com/swgsub")} value=${sUrl} onInput=${e => setSUrl(e.target.value)}/></div>
      <div class="fieldrow">${ipField(sHost, setSHost, true, sLoopbackDirect)}${behindProxy
        ? portField(sPort, setSPort, sBad || sPortRangeBad, sPortRangeBad ? T("Port must be a number between 1 and 65535") : null)
        : null}</div>
      ${sLoopbackDirect ? loopNote(T("subscription server")) : (sBad ? cfNote : null)}
      ${(behindProxy && (subBindChanged() || subUrlChanged())) ? html`<div class="notice" style="margin:8px 0 12px"><${Ic} i="info"/><div style="min-width:0">
        ${Trich("*Behind a reverse proxy.* Point your proxy at `{v1}` and make sure it serves this URL's path. swg-sub picks it up on Save — a path or domain change reloads it live (no downtime; existing links keep working during a grace), a host/port change restarts it. If the panel has no root helper, it saves and asks you to run `systemctl reload swg-sub`.", { v1: (sHost.trim() || "127.0.0.1") + ":" + _sPortN() })}
      </div></div>` : null}
      ${behindProxy ? html`<details class="nginx-sample" style="margin:8px 0 4px"><summary style="cursor:pointer;color:var(--muted);font-size:.9em">${Trich("Reverse-proxy config for the subscription page (nginx) — full `server { }` for the values above")}</summary>
        <pre class="mono" style="white-space:pre;overflow:auto;padding:10px;border-radius:6px;background:var(--code-bg, rgba(127,127,127,.09));margin:8px 0 6px;font-size:.85em">${nginxServerBlock(sUrl, sHost, _sPortN())}</pre>
        <button class="btn btn-mini" onClick=${() => copy(nginxServerBlock(sUrl, sHost, _sPortN()), T("subscription nginx server block"))}><${Ic} i="copy"/>${T("Copy")}</button>
        <div class="hint" style="margin-top:6px">${Trich("If swg-sub shares the panel's domain, merge its `location` into that server block instead of a second one — then reload nginx.")}</div>
      </details>` : null}` : null}
  </div>`;
}

// Interface-key escrow (lives in Settings → Interfaces): each entry server seals its interface private key under
// the browser-held Encryption Vault key, so a fully-wiped node's interface can be restored with its ORIGINAL key.
// Presentational — the toggle only stages a value; the Settings screen applies it on Save (via ivkSetEscrow) like
// every other field. Needs the Encryption Vault set up (Client configs) — independent of store_configs.
export function InterfaceKeyEscrow({ value, onChange, vaultExists }) {
  if (vaultExists === null || value === null) return html`<div class="hint">${T("Checking…")}</div>`;
  if (!vaultExists) return html`<p class="hint" style="margin:0">${Trich("Set up your *Encryption Vault* first in {v1} — each server's interface key is sealed under it.", { v1: html`<button class="linkbtn" onClick=${() => goSettings("configs")}>${T("Client configs → Encryption")}</button>` })}</p>`;
  return html`<div class="ivk-escrow">
    <label class="ivk-esc-row"><${Switch} on=${!!value} onChange=${onChange}/>
      <span>${Trich("*Escrow interface server keys* — each entry server seals its interface private key to your browser-held *Encryption Vault* key (the panel only ever stores ciphertext). Lets you *restore an interface cleanly after a full wipe / lost box*, with no client re-import. Off ⇒ a wiped node's interfaces can only be recreated with new keys, and every client on them re-imports.")}</span></label>
    ${value && !subSKCached() ? html`<div class="hint" style="margin-top:6px">${T("Keep the Encryption Vault unlocked when you need to restore — releasing an escrowed key requires it.")}</div>` : null}
  </div>`;
}

// Subscription encryption setup. The Subscription Key is generated + wrapped IN THE BROWSER; the server only
// ever gets the wrapped form. It's shown once (like 2FA recovery codes) and is independent of the login password.
export function SubVaultCard() {
  const [state, setState] = useState({ loading: true });
  const [pw, setPw] = useState(""); const [busy, setBusy] = useState(false);
  const [sk, setSk] = useState(null);                    // the shown-once Subscription Key
  const [resetMode, setResetMode] = useState(false); const [confirm, setConfirm] = useState("");
  const [shown, setShown] = useState(null);   // the encryption key, revealed on demand while the vault is unlocked
  const load = () => api.subVault().then(r => setState({ loading: false, exists: !!(r && r.ok && r.data && r.data.exists) })).catch(() => setState({ loading: false, exists: false }));
  useEffect(() => { load(); }, []);
  const create = async () => {
    if (!pw) return; setBusy(true);
    try { setSk(await subVaultCreate(pw)); setPw(""); }
    catch (e) { toast((e && e.message) || T("Setup failed"), "err"); }
    setBusy(false);
  };
  const doReset = async () => {
    setBusy(true); const r = await api.subReset(); setBusy(false);
    if (r && r.ok) { subForget(); setResetMode(false); setConfirm(""); setSk(null); load(); toast(T("Config encryption reset."), "ok"); }   // drop the now-stale cached SK
    else toast(srvText(r) || T("Reset failed"), "err");
  };
  if (state.loading) return html`<div class="hint">${T("Checking…")}</div>`;
  if (sk) return html`<div class="notice ok"><div style="min-width:0">
    ${Trich("*Save your encryption key now — it is shown only once.* It protects every stored client config (and your subscriptions) and is independent of your login password; store it somewhere safe (a password manager). Lose it and your login both, and you'd re-key the affected peers.")}
    <div class="tokenbox" style="margin:8px 0;word-break:break-all">${sk}</div>
    <div class="chiprow">
      <button class="btn btn-mini" onClick=${() => copy(sk, T("Encryption key copied"))}><${Ic} i="copy"/>${T("Copy")}</button>
      <button class="btn btn-mini" onClick=${() => downloadConf(sk, "swg-config-key")}><${Ic} i="download"/>${T("Download")}</button>
      <span class="grow"></span>
      <button class="btn btn-primary btn-mini" onClick=${() => { setSk(null); load(); }}>${T("I've saved it")}</button>
    </div></div></div>`;
  if (!state.exists) return html`<${Fragment}>
    <p class="hint" style="margin:0 0 8px">${T("Set up once. Confirm your panel password — an encryption key is generated in your browser and shown once; the server only ever stores it wrapped, so it can't read your clients' private keys.")}</p>
    <div class="fieldrow">
      <div class="field"><label>${T("Confirm password")}</label><input type="password" value=${pw} onInput=${e => setPw(e.target.value)} autocomplete="current-password"/></div>
      <div class="field" style="flex:none;align-self:end"><button class="btn btn-primary" disabled=${busy || !pw} onClick=${create}>${busy ? T("Setting up…") : T("Set up encryption")}</button></div>
    </div><//>`;
  return html`<${Fragment}>
    <div class="notice ok" style="margin-bottom:8px"><${Ic} i="check"/><span>${Trich("Your *Encryption Vault* is configured — stored configs are wrapped automatically, and their QRs (and any subscription links) keep working across your password changes.")}</span></div>
    <p class="hint" style="margin:0 0 8px">${Trich("The vault opens with your *panel password*, which follows every change you make in the panel. Your *encryption key* opens it too — that's what gets you back in if the panel password is ever reset on the server with *swg-passwd*, so keep a copy somewhere safe.")}</p>
    ${shown ? html`<div class="notice ok"><div style="min-width:0">
        ${Trich("*Your encryption key.* Anyone holding this can read every stored config — treat it like a password and store it in a password manager.")}
        <div class="tokenbox" style="margin:8px 0;word-break:break-all">${shown}</div>
        <div class="chiprow">
          <button class="btn btn-mini" onClick=${() => copy(shown, T("Encryption key copied"))}><${Ic} i="copy"/>${T("Copy")}</button>
          <button class="btn btn-mini" onClick=${() => downloadConf(shown, "swg-config-key")}><${Ic} i="download"/>${T("Download")}</button>
          <span class="grow"></span>
          <button class="btn btn-ghost btn-mini" onClick=${() => setShown(null)}>${T("Hide")}</button>
        </div></div></div>` : null}
    ${resetMode
      ? html`<div class="notice warn"><div style="min-width:0">${Trich("*Reset drops all stored encrypted configs and invalidates every subscription URL.* You'll set up a new encryption key afterwards, then re-issue affected peers. Type *RESET* to confirm.")}
          <div class="chiprow" style="margin-top:8px"><input type="text" placeholder=RESET value=${confirm} onInput=${e => setConfirm(e.target.value)} style="max-width:120px"/>
            <button class="btn btn-danger btn-mini" disabled=${busy || confirm !== "RESET"} onClick=${doReset}>${T("Reset encryption")}</button>
            <button class="btn btn-ghost btn-mini" onClick=${() => { setResetMode(false); setConfirm(""); }}>${T("Cancel")}</button></div></div></div>`
      : html`<div class="chiprow">${shown ? null : html`<button class="btn btn-ghost btn-mini" disabled=${!subSKCached()}
            title=${subSKCached() ? T("Show the key again — it never leaves your browser") : T("Unlock the vault first to reveal its key")}
            onClick=${() => setShown(subKeyB64())}><${Ic} i="key"/>${T("Show encryption key")}</button>`}<span class="grow"></span>
          <button class="btn btn-ghost btn-mini danger" onClick=${() => setResetMode(true)}>${T("Reset encryption…")}</button></div>`}
  <//>`;
}
// The one-time "Encrypt stored configs" migration prompt — shown in Client configs whenever LEGACY plaintext
// configs are still on the panel (Store.configsPlaintext). Requires the vault (set it up in the card above first)
// + the encryption key unlocked; runs runConfigMigration (encrypt-all → capture overrides → purge plaintext where
// a blob exists), then reports peers that couldn't be encrypted (→ rekey). Resumable: re-running does the rest.
export function ConfigMigrationCard() {
  useStore();                          // re-render as the plaintext count drops after a pass
  const [busy, setBusy] = useState(false);
  const [pw, setPw] = useState("");
  const [report, setReport] = useState(null);
  const [vaultExists, setVaultExists] = useState(true);
  useEffect(() => { api.subVault().then(r => setVaultExists(!!(r && r.ok && r.data && r.data.exists))).catch(() => {}); }, []);
  const n = Store.configsPlaintext || 0;
  if (n <= 0 && !report) return null;                          // nothing to migrate
  const flaggedNames = report ? report.flagged.map(pid => {
    const p = (Store.recon.peers || []).find(x => x.id === pid) || {};
    return (p.name ? p.name + " · " : "") + (p.title || "peer");
  }) : [];
  const run = async () => {
    if (!subSKCached()) {                                  // a cached SK ⇒ the vault exists (e.g. just set up this session)
      if (!vaultExists) { toast(T("Set up the encryption key above first."), "err"); return; }
      if (!pw) { toast(T("Enter your panel password to unlock the encryption key."), "err"); return; }
      try { await subUnlock(pw); setPw(""); } catch (e) { toast((e && e.message) || T("Unlock failed"), "err"); return; }
    }
    setBusy(true);
    try {
      const rep = await runConfigMigration();
      setReport(rep);
      toast(`Encrypted ${rep.migrated} config${rep.migrated === 1 ? "" : "s"}${rep.purged ? `, purged ${rep.purged} plaintext` : ""}.`, "ok");
    } catch (e) { toast((e && e.message) || T("Migration failed"), "err"); }
    setBusy(false);
  };
  const pwField = html`<input class="subpw" type="password" style="max-width:220px" value=${pw} autocomplete="off"
    placeholder=${T("Panel password (unlocks the encryption key)")} onKeyDown=${e => { if (e.key === "Enter") run(); }} onInput=${e => setPw(e.target.value)}/>`;
  return html`<div class=${"notice " + (n > 0 ? "warn" : "ok")} style="margin-top:10px"><div style="min-width:0">
    ${n > 0
      ? Trich("*{v1} plaintext config{v2} still on the panel.* Encrypt them so the server can no longer read a client private key. Safe and resumable — the plaintext is deleted only after its encrypted copy exists.", { v1: n, v2: n === 1 ? "" : "s" })
      : Trich("*All stored configs are encrypted.*")}
    ${report ? html`<div class="hint" style="margin-top:8px">${Trich("Encrypted {v1} of {v2} · purged {v3} plaintext", { v1: html`<b>${report.migrated}</b>`, v2: report.total, v3: html`<b>${report.purged}</b>` })}${report.orphansPurged ? ` (+${report.orphansPurged} orphan)` : ""}${report.remaining ? ` · ${report.remaining} still plaintext` : ""}.
      ${report.flagged.length ? html`<div style="margin-top:6px">${Trich(report.flagged.length === 1
        ? "*{v1}* couldn't be encrypted (unassigned, or no stored key) — *rekey* or assign it to include: {v2}."
        : "*{v1}* couldn't be encrypted (unassigned, or no stored key) — *rekey* or assign them to include: {v2}.",
        { v1: plural(report.flagged.length, "peer"), v2: flaggedNames.slice(0, 8).join(", ") + (flaggedNames.length > 8 ? T(" +{n} more", { n: flaggedNames.length - 8 }) : "") })}</div>` : html`<div style="margin-top:6px">${T("Every assigned peer with a stored key is encrypted.")}</div>`}</div>` : null}
    <div class="chiprow" style="margin-top:8px">
      ${(n > 0 && !subSKCached()) ? pwField : null}
      ${n > 0 ? html`<button class="btn btn-primary btn-mini" disabled=${busy || (!vaultExists && !subSKCached())} onClick=${run}>${busy ? "Encrypting…" : (report ? T("Encrypt remaining") : T("Encrypt stored configs"))}</button>` : null}
    </div>
  </div></div>`;
}
export function PanelSettingsScreen() {
  // NOTE: deliberately NOT subscribed to the 5s poll (no useStore) — this is an edit form seeded from a
  // snapshot at mount. Re-rendering every poll re-diffs every controlled input (the source of the checkbox
  // repaint flicker) and is pointless for a form; it still re-renders on its own edits (setNodeEdits etc.),
  // and save() re-polls + reseeds. A node added/renamed mid-edit just won't reflect until you re-enter.
  const ps = Store.panelSettings || {};
  const idf = ps.interface_defaults || {}; const mir = ps.mirrors || {}; const adv = ps.advanced || {};
  const [dns, setDns] = useState((idf.dns || []).join(", "));
  const [mtu, setMtu] = useState(String(idf.mtu || 1280));
  const [ka, setKa] = useState(String(idf.keepalive || 25));
  const [geoMir, setGeoMir] = useState(mir.geo || "");
  const [turnMir, setTurnMir] = useState(mir.turn || "");
  // Geo-data: catalog provider enable/disable + scheduled list refresh (replacing the geo mirror).
  const _provReg = Store.catalogProviders || [];
  const [provEnabled, setProvEnabled] = useState(() => Object.fromEntries(_provReg.map(p => [p.id, p.enabled !== false])));
  const _gu = ps.geo_update || {};
  const [guEvery, setGuEvery] = useState(String(_gu.every_days == null ? 1 : _gu.every_days));
  const [guAt, setGuAt] = useState(_gu.at || "04:00");
  const [geoUpdating, setGeoUpdating] = useState(false);   // the Update-all-lists button in flight → poll provider status
  const updateAllLists = async () => {
    setGeoUpdating(true);
    const r = await api.geoUpdate();
    if (!r || !r.ok) { setGeoUpdating(false); return toast(srvText(r) || T("Couldn't start update"), "err"); }
    // poll /api/state until no provider is still "updating" (or a 25s cap)
    const t0 = Date.now();
    const tick = async () => { await Store.poll();
      const busy = (Store.catalogProviders || []).some(p => p.status === "updating");   // i18n-keys
      if (busy && Date.now() - t0 < 25000) return setTimeout(tick, 1500);
      setGeoUpdating(false); };
    setTimeout(tick, 1500);
  };
  const retryProvider = async (pid) => {   // manual retry after a provider's automatic fetch retries (4×, backoff) all failed
    const r = await api.geoProviderRetry(pid);
    if (!r || !r.ok) return toast(srvText(r) || "Couldn't retry", "err");
    const t0 = Date.now();
    const tick = async () => { await Store.poll();
      const busy = (Store.catalogProviders || []).some(p => p.id === pid && p.status === "downloading");
      if (busy && Date.now() - t0 < 25000) return setTimeout(tick, 1500); };
    setTimeout(tick, 1500);
  };
  // Transient "updated" / T("up to date") — show for 5s AFTER a busy→done transition, then hide. In-progress
  // (downloading/updating) always shows; failed persists (with Retry). No flash on first load (statuses stay hidden).
  const [provFlash, setProvFlash] = useState({});   // pid -> expiry ts
  const _provSeen = useRef({});
  useEffect(() => {
    const now = Date.now(), seen = _provSeen.current; let next = null;
    for (const p of (Store.catalogProviders || [])) {
      const prev = seen[p.id];
      if (p.status !== prev) {
        if (prev !== undefined && (p.status === "updated" || p.status === "uptodate")) { next = next || { ...provFlash }; next[p.id] = now + 5000; }   // i18n-keys
        seen[p.id] = p.status;
      }
    }
    if (next) setProvFlash(next);
  }, [Store.catalogProviders]);
  useEffect(() => {
    const exps = Object.values(provFlash).filter(t => t > Date.now());
    if (!exps.length) return;
    const t = setTimeout(() => setProvFlash(f => ({ ...f })), Math.min(...exps) - Date.now() + 50);
    return () => clearTimeout(t);
  }, [provFlash]);
  const _scMode = Store.storeMode || "encrypted";   // the RESOLVED enum (server considers the panel/fleet default)
  const [sc, setSc] = useState(_scMode);
  const [tput, setTput] = useState(ps.throughput_perspective === "peers" ? "peers" : "nodes");
  const [staleS, setStaleS] = useState(String(Math.round((adv.node_stale_ms || 30000) / 1000)));
  const [graceS, setGraceS] = useState(String(Math.round((adv.peer_grace_ms || 60000) / 1000)));
  const [ttlD, setTtlD] = useState(String(adv.geo_ttl_days || 3));
  const [topTalk, setTopTalk] = useState(String(ps.top_talkers || 10));
  const [topDest, setTopDest] = useState(String(ps.top_destinations || 10));
  const [warnDays, setWarnDays] = useState(String(ps.expiry_warn_days == null ? 3 : ps.expiry_warn_days));
  const [hidden, setHidden] = useState(new Set(ps.hidden_categories || []));   // built-in categories hidden from the routing dropdown
  const [lists, setLists] = useState((ps.custom_lists || []).map(l => ({ ...l, _rid: newRid(), targets: [...(l.domains || []), ...(l.cidrs || [])].join(", ") })));
  const [turnEnabledS, setTurnEnabledS] = useState(ps.turn_enabled !== false);   // master turn-proxy switch
  const [turnForks, setTurnForks] = useState(new Set(ps.enabled_turn_forks || TURN_FORKS_DEFAULT));   // forks offered in the install picker
  const [vkLinkS, setVkLinkS] = useState(ps.vk_link || "");   // VK call link baked into generated turn-proxy client configs
  // ---- themed colour pickers ({dark,light} each) — Interfaces / Display / Turn sections ----
  const asThemed = (v, dd, dl) => (v && typeof v === "object") ? { dark: v.dark || dd, light: v.light || dl } : { dark: v || dd, light: v || dl };
  const sameThemed = (a, dd, dl) => (a.dark || "").toLowerCase() === dd.toLowerCase() && (a.light || "").toLowerCase() === dl.toLowerCase();
  const _bprovs = (Store.blockCatalog || {}).providers || [];   // content-filter feeds share the provider_colors map (ids never collide with catalog ids)
  const _provColDefault = p => {
    const c = CAT_PROVIDER_DEFAULTS[p];
    if (c) return { dark: c.color, light: c.colorL };
    const bp = _bprovs.find(x => x.id === p);
    if (bp && bp.color) return { dark: bp.color, light: bp.color_l || bp.color };   // block feeds ship a dark + light default hex
    if (p === "custom") return { dark: "#8A94A6", light: "#5E6875" };
    return { dark: "#8FA8C0", light: "#5E7085" };
  };
  const _provColKeys = [..._provReg.map(p => p.id), ..._bprovs.map(p => p.id), "custom"];
  const [provColors, setProvColors] = useState(() => Object.fromEntries([..._provReg.map(p => p.id), "custom"].map(k => [k, asThemed((ps.provider_colors || {})[k], _provColDefault(k).dark, _provColDefault(k).light)])));
  useEffect(() => {   // block catalog loads async — seed its providers' default colours once present (only keys not already set)
    if (!_bprovs.length) return;
    setProvColors(c => { let ch = false; const n = { ...c }; for (const p of _bprovs) if (n[p.id] === undefined) { n[p.id] = asThemed((ps.provider_colors || {})[p.id], p.color, p.color_l || p.color); ch = true; } return ch ? n : c; });
  }, [Store.blockCatalog]);
  const provColorOverrides = () => { const o = {}; for (const k of _provColKeys) { const d = _provColDefault(k); const t = asThemed(provColors[k], d.dark, d.light); if (!sameThemed(t, d.dark, d.light)) o[k] = t; } return o; };
  const [customEnabled, setCustomEnabled] = useState(ps.custom_lists_enabled !== false);
  const [forkColors, setForkColors] = useState(() => Object.fromEntries(turnForkList().map(f => [f.id, asThemed((ps.turn_fork_colors || {})[f.id], f.color, f.colorL)])));
  const _tu = ps.turn_update || {};   // turn-proxy auto-update schedule: every_days (0=off) + node-checked panel-local hour
  const [tuEvery, setTuEvery] = useState(String(_tu.every_days == null ? 0 : _tu.every_days));
  const [tuAt, setTuAt] = useState(_tu.at || "04:00");
  const [ifaceColors, setIfaceColors] = useState(() => ({
    wg: asThemed((ps.iface_colors || {}).wg, IFACE_COLOR_DEFAULTS.wg.dark, IFACE_COLOR_DEFAULTS.wg.light),
    awg: asThemed((ps.iface_colors || {}).awg, IFACE_COLOR_DEFAULTS.awg.dark, IFACE_COLOR_DEFAULTS.awg.light),
    wdtt: asThemed((ps.iface_colors || {}).wdtt, IFACE_COLOR_DEFAULTS.wdtt.dark, IFACE_COLOR_DEFAULTS.wdtt.light) }));
  const [themeColorS, setThemeColorS] = useState(clampBrand(ps.theme_color || THEME_COLOR_DEFAULT, false));         // dark-mode accent (shown = applied)
  const [themeColorLightS, setThemeColorLightS] = useState(clampBrand(ps.theme_color_light || THEME_COLOR_LIGHT_DEFAULT, true));   // light-mode accent
  const themeVal = { dark: themeColorS, light: themeColorLightS };   // the theme accent as one themed swatch
  // peer-health DETECTION toggles (not colours): each condition ON by default; unchecking stops it flagging the status.
  const _sc = ps.status_conditions || {};
  const [statusConds, setStatusConds] = useState({ blocked: _sc.blocked !== false, faulty: _sc.faulty !== false });
  // interface-key escrow (Interfaces section): staged like a field — the toggle sets a pending value; Save applies it.
  const [ivkEscrow, setIvkEscrow] = useState(null);           // pending value (null = still loading)
  const [ivkEscrowInit, setIvkEscrowInit] = useState(null);   // saved value → dirty when they differ
  const [ivkVaultExists, setIvkVaultExists] = useState(null); // vault set up? escrow needs it
  useEffect(() => { api.subVault().then(r => { const okd = !!(r && r.ok && r.data); const on = okd && !!r.data.ivk_enabled; setIvkEscrow(on); setIvkEscrowInit(on); setIvkVaultExists(okd ? !!r.data.exists : false); }).catch(() => setIvkVaultExists(false)); }, []);
  // overrides derived from a raw source (state OR the stored panel-settings), normalized identically so a legacy
  // single-colour value in panel-settings compares equal to its normalized {dark,light} form (no phantom "dirty").
  const forkOvFrom = src => { const o = {}; for (const f of turnForkList()) { const t = asThemed((src || {})[f.id], f.color, f.colorL); if (!sameThemed(t, f.color, f.colorL)) o[f.id] = t; } return o; };
  const ifaceOvFrom = src => { const o = {}; for (const k of ["wg", "awg", "wdtt"]) { const t = asThemed((src || {})[k], IFACE_COLOR_DEFAULTS[k].dark, IFACE_COLOR_DEFAULTS[k].light); if (!sameThemed(t, IFACE_COLOR_DEFAULTS[k].dark, IFACE_COLOR_DEFAULTS[k].light)) o[k] = t; } return o; };
  const forkColorOverrides = () => forkOvFrom(forkColors);
  const ifaceColorOverrides = () => ifaceOvFrom(ifaceColors);
  const statusCondsOut = () => ({ blocked: statusConds.blocked, faulty: statusConds.faulty });
  const themeColorOut = () => themeColorS.toLowerCase() === THEME_COLOR_DEFAULT.toLowerCase() ? "" : themeColorS;
  const themeColorLightOut = () => themeColorLightS.toLowerCase() === THEME_COLOR_LIGHT_DEFAULT.toLowerCase() ? "" : themeColorLightS;
  // deployed version(s) of a fork across the fleet (from snapshots) — "" if it's never been installed
  // deployed versions of a fork across the fleet. Classic forks come from snap.turn_proxies; WDTT forks own their
  // interface so they live in snap.wdtt (keyed by the instance's `fork`), and don't report a binary version yet →
  // show "installed" so a deployed WDTT fork reads as used, not T("not yet used").
  const forkVersions = fid => { const v = new Set();
    for (const snap of Object.values(Store.stats || {})) {
      for (const tp of (snap.turn_proxies || [])) if (tp.service && turnFork(tp.service) === fid && tp.version) v.add(tp.version);
      for (const w of (snap.wdtt || [])) if (w && w.fork === fid) v.add(w.version || "installed");   // i18n-keys
    }
    return [...v]; };
  // per-NODE view of a fork for the hover bubble: one row per node carrying its version + whether it's mid-update
  // (a shared per-fork binary → one version/node; updating if ANY of its instances is installing or Update-clicked).
  const forkNodeStates = fid => {
    const m = {};   // nodeId -> {version, installing (real, clears when done), updatePending (Update-clicked, 120s hint)}
    for (const [nid, snap] of Object.entries(Store.stats || {})) {
      for (const tp of (snap.turn_proxies || [])) {
        if (!tp.service || turnFork(tp.service) !== fid) continue;
        const cur = m[nid] || { version: "", installing: false, updatePending: false };
        if (tp.version) cur.version = tp.version;
        if (tp.installing) cur.installing = true;
        const uk = nid + "|" + tp.service;
        if (turnUpdating[uk] && Date.now() < turnUpdating[uk]) cur.updatePending = true;
        m[nid] = cur;
      }
      for (const w of (snap.wdtt || [])) {   // WDTT instances (self-contained; keyed by fork, no version string)
        if (!w || w.fork !== fid) continue;
        const cur = m[nid] || { version: "", installing: false, updatePending: false };
        cur.version = w.version || cur.version || "installed";   // i18n-keys
        if (w.active && w.active !== "active") cur.installing = true;   // starting / awaiting restore
        m[nid] = cur;
      }
    }
    return Object.entries(m).map(([node, v]) => ({ node, ...v })).sort((a, b) => Store.nodeName(a.node).localeCompare(Store.nodeName(b.node)));
  };
  const [turnCheck, setTurnCheck] = useState({});   // {forkId: {status:'checking'|'uptodate'|'update', latest}}
  const checkTurnUpdates = async () => {
    setTurnCheck(Object.fromEntries(turnForkList().map(f => [f.id, { status: "checking" }])));
    const r = await api.turnCheckUpdates({ forks: turnForkList().map(f => ({ id: f.id, owner: f.owner })) });
    const latest = (r && r.ok && r.data.latest) || {};
    const next = {};
    for (const f of turnForkList()) {
      const lt = latest[f.id] || "", dep = forkVersions(f.id);
      next[f.id] = (lt && dep.length && dep.some(v => v !== lt)) ? { status: "update", latest: lt } : { status: "uptodate" };
    }
    setTurnCheck(next);
    setTimeout(() => setTurnCheck(c => Object.fromEntries(Object.entries(c).map(([k, v]) => [k, v.status === "update" ? v : {}]))), 5000);   // T("up to date") clears after 5s; "update" persists
  };
  // update every deployed instance of a fork to `latest` — reinstall (re-download binary) on each (node,service)
  const updateFork = async (fid, latest) => {
    const fork = turnForkList().find(x => x.id === fid) || {};
    if (fork.kind === "wdtt") {   // WDTT: release each instance's hold → the node swaps its shared binary to the current published build
      const wt = [];
      for (const [nid, snap] of Object.entries(Store.stats || {})) for (const w of (snap.wdtt || [])) if (w && w.fork === fid && w.iface) wt.push({ node: nid, iface: w.iface });
      if (!wt.length) return;
      setTurnCheck(c => ({ ...c, [fid]: { status: "updating", latest } }));   // i18n-keys
      for (const t of wt) await api.wdttVersion({ node: t.node, iface: t.iface, ver: "" });
      await Store.poll();
      setTurnCheck(c => ({ ...c, [fid]: {} }));
      toast(T("Update requested on {v1} — each node applies it on its next sync.", { v1: plural(wt.length, "WDTT server") }), "ok");
      return;
    }
    const owner = fork.owner || "";
    const targets = [];
    for (const [nid, snap] of Object.entries(Store.stats || {})) for (const tp of (snap.turn_proxies || [])) if (tp.service && turnFork(tp.service) === fid) targets.push({ node: nid, service: tp.service });
    if (!targets.length) return;
    setTurnCheck(c => ({ ...c, [fid]: { status: "updating", latest } }));   // i18n-keys
    turnUpdateTarget[fid] = { ver: latest, until: Date.now() + 120000 };   // persists past the turnCheck reset so the bubble can show per-node updating→updated
    for (const t of targets) { turnUpdating[t.node + "|" + t.service] = Date.now() + 120000; await api.turnReinstall({ node: t.node, service: t.service, owner }); }
    await Store.poll();
    setTurnCheck(c => ({ ...c, [fid]: {} }));
    toast(T("Update requested on {v1} — each node applies it on its next sync.", { v1: plural(targets.length, "proxy") }), "ok");
  };
  // Security (panel login) — folded into the unified Save: credentials update on Save (if changed), and a
  // validation error blocks Save. Username is loaded from the server once on mount.
  const [secUser, setSecUser] = useState(""); const [secOrigUser, setSecOrigUser] = useState("");
  const [secCur, setSecCur] = useState(""); const [secNp, setSecNp] = useState(""); const [secNp2, setSecNp2] = useState("");
  const [secAuth, setSecAuth] = useState(true);   // false = panel has no login configured (fields disabled)
  const [sec2fa, setSec2fa] = useState(false);    // TOTP currently enabled on the account
  useEffect(() => { api.account().then(r => { if (r && r.ok) { setSecAuth(r.data.auth_enabled !== false); setSec2fa(!!r.data.twofa_enabled); if (r.data.username) { setSecUser(r.data.username); setSecOrigUser(r.data.username); } } }); }, []);
  const secChanged = () => secAuth && (secUser.trim() !== secOrigUser || !!secNp);
  const secErr = () => {
    if (!secAuth || !secChanged()) return null;
    if (!secUser.trim()) return T("Username can't be empty.");
    if (secUser.includes(":")) return T("Username can't contain a colon.");
    if (!secCur) return T("Enter your current password to confirm the change.");
    if (secNp && secNp !== secNp2) return T("New passwords don't match.");
    if (secNp && secNp.length < 8) return T("New password must be at least 8 characters.");
    return null;
  };
  const [section, setSection] = useState(takePendingSection() || "display");   // active left-rail section (a Settings activity click can deep-link here)
  useEffect(() => { registerSectionSetter(setSection); return () => registerSectionSetter(null); }, []);   // one-shot section pin + expose setSection so a modal can switch the rail (confirm modal → Access & TLS)
  const [routeTab, setRouteTab] = useState("routing");   // "Routing & Blocking" section: Routing (route→exit) | Blocking (drop) — both gated by the node's mode above
  useEffect(() => { if (routeTab === "blocking" || section === "geo") loadBlockCatalog(); }, [routeTab, section]);   // lazy-load the block catalog for the Blocking tab and the Geo-data Filters-providers list
  const _bkCountTries = useRef(0);
  useEffect(() => {   // list counts resolve in the background on the panel — refetch a few times until they land (or give up)
    if (routeTab !== "blocking") return;
    const bc = Store.blockCatalog; if (!bc) return;
    const pending = Object.values(bc.categories || {}).some(c => (c.sources || []).length && !c.size);
    if (!pending) { _bkCountTries.current = 0; return; }
    if (_bkCountTries.current >= 6) return;
    const t = setTimeout(() => { _bkCountTries.current++; loadBlockCatalog(true); }, 4000);
    return () => clearTimeout(t);
  }, [routeTab, Store.blockCatalog]);
  const [blockProvEdits, setBlockProvEdits] = useState({});   // staged Filters-providers toggle deltas {prov_id:bool} → panelSettings.block_providers (committed by the shared Save)
  const [geoTab, setGeoTab] = useState("routing");   // Geo-data providers card: Routing (list providers) | Blocking (content-filter feeds)
  const [blockEdits, setBlockEdits] = useState({});   // staged block-category deltas {id:{enabled_nodes?,default_on?,sources?,…}} → api.blockCatalogSave (committed by the shared Save)
  const [bkOpen, setBkOpen] = useState({});   // expanded block-category rows (id→bool) — the expand shows/edits the category's lists
  const [blockRemoved, setBlockRemoved] = useState([]);   // custom block-category ids staged for deletion → api.blockCatalogSave removed[]
  const [bkAutoAdd, setBkAutoAdd] = useState(null);   // a just-created category id → auto-open its Add-list picker
  const rsv = ps.reserved || {};
  const [rsvSubnet, setRsvSubnet] = useState(rsv.mesh_subnet || "10.255.0.0/16");
  const [rsvPort, setRsvPort] = useState(String(rsv.mesh_port_base || 9999));
  const [rsvPrefix, setRsvPrefix] = useState(rsv.iface_prefix || "swg_");
  const [awg, setAwg] = useState(ps.mesh_awg || {});
  const [showAwg, setShowAwg] = useState(false);
  const awgSet = AWG_KEYS.some(k => String(awg[k] ?? "").trim() !== "");
  const [showAdv, setShowAdv] = useState(false);
  const [msg, setMsg] = useState(null);
  // subscriptions section state — enable + languages ride the global save; the vault ceremony uses /api/sub/*.
  // The sub's address, URL and certificate now live in the Access & TLS section (access.sub / access.tls).
  const subCfg = ps.subscriptions || {};
  const [subsOn, setSubsOn] = useState(!!subCfg.enabled);
  const [autoGen, setAutoGen] = useState(!!subCfg.auto_generate);   // auto-mint a subscription link for each new user
  const subLangCfg = (subCfg.languages && typeof subCfg.languages === "object") ? subCfg.languages : {};
  const [subLangs, setSubLangs] = useState((subLangCfg.enabled && subLangCfg.enabled.length) ? [...subLangCfg.enabled] : ["en"]);
  const [subLangDef, setSubLangDef] = useState(subLangCfg.default || "en");
  const toggleSubLang = (id, on) => {
    let next = on ? [...new Set([...subLangs, id])] : subLangs.filter(l => l !== id);
    if (!next.length) next = [id];                 // never empty — at least one language
    setSubLangs(next);
    if (next.indexOf(subLangDef) < 0) setSubLangDef(next[0]);   // default must stay enabled
  };
  // per-node pending edits (mode / mesh / egress) — lifted here so switching node or section keeps unsaved
  // changes; the single Save commits the global settings AND one nodeUpdate per changed node.
  const eq = (a, b) => { const c = v => v == null ? "" : Array.isArray(v) ? JSON.stringify([...v].sort()) : typeof v === "object" ? JSON.stringify(Object.keys(v).sort().reduce((o, k) => (o[k] = v[k], o), {})) : String(v); return c(a) === c(b); };
  const nFields = n => ({ routing_mode: n.routing_mode || "kernel", ip_learning: n.ip_learning !== false, endpoint_host: n.endpoint_host || "",
    mesh_subnet: n.mesh_subnet || "", mesh_port: n.mesh_port ? String(n.mesh_port) : "", mesh_prefix: n.mesh_prefix || "",
    default_egress_ip: n.default_egress_ip || "", panel_ip: n.panel_ip || "",
    enabled_categories: (n.enabled_categories && n.enabled_categories.length) ? [...n.enabled_categories] : null,   // null = all built-ins enabled for this node
    catalog_cats: [...(n.catalog_cats || [])],   // provider-catalog categories opted into on this node (node-lens; separate from the 26 built-ins)
    mesh_awg: (n.mesh_awg_set && Object.keys(n.mesh_awg_set).length) ? { ...n.mesh_awg_set } : {} });   // per-node mesh obfuscation override ({} = inherit/auto)
  const [nodeEdits, setNodeEdits] = useState(() => Object.fromEntries((Store.nodes || []).map(n => [n.id, nFields(n)])));
  const [orig, setOrig] = useState(() => Object.fromEntries((Store.nodes || []).map(n => [n.id, nFields(n)])));
  const [gridKeep, setGridKeep] = useState([]);   // provider-list rows kept visible after toggling to 0/N nodes (until × removes them)
  const setNV = (nid, patch) => setNodeEdits(e => ({ ...e, [nid]: { ...nFields((Store.nodes || []).find(n => n.id === nid) || {}), ...(e[nid] || {}), ...patch } }));
  const nv = (nid, f) => (nodeEdits[nid] || {})[f];
  const [saved, setSaved] = useState(0);   // timestamp; the green "All settings saved" flash shows while now < saved
  // Access & TLS reports its {dirty,busy,msg,run} up here so the shared footer drives its Save + status like every
  // other section. The ref always holds the latest; accessSig re-renders the footer only when a shown bit changes.
  const accessRef = useRef({ dirty: false, busy: false, msg: null, run: () => {} });
  const [, setAccessSig] = useState("");
  const onAccess = useCallback(s => {
    accessRef.current = s;
    const sig = (s.dirty ? "1" : "0") + (s.busy ? "1" : "0") + "|" + (s.msg ? (s.msg.ok ? "o" : "e") + s.msg.t : "");
    setAccessSig(prev => prev === sig ? prev : sig);
  }, []);
  const save = async () => {
    // Progress lives on the confirm-modal button ("Saving…" spinner) — it stays open until save() resolves. The
    // header shows the green "All settings saved" flash on success. A thrown request (dead/wedged panel, timeout)
    // surfaces here instead of leaving the modal stuck.
    try {
    if (SECTIONS.some(([s]) => glDirty(s))) {   // only rewrite panel_settings when a GLOBAL setting actually changed (nodes go via nodeUpdate below)
      const dirtySecs = SECTIONS.filter(([s]) => glDirty(s)), secLabel = Object.fromEntries(SECTIONS);   // for the activity one-liner + deep-link
      const r = await api.panelSettings({
        _ev: { first: (dirtySecs[0] || [""])[0], sections: dirtySecs.map(([s]) => secLabel[s]).join(", ") },   // display-only: which sections changed (drives the "Settings changed" activity row)
        interface_defaults: { dns: dns.split(",").map(s => s.trim()).filter(Boolean), mtu: +mtu || 1280, keepalive: +ka || 25 },
        mirrors: { geo: geoMir.trim(), turn: turnMir.trim() },
        providers: provEnabled,
        block_providers: blockProvEdits,
        provider_colors: provColorOverrides(),
        custom_lists_enabled: customEnabled,
        geo_update: { every_days: Math.max(0, Math.min(30, parseInt(guEvery) || 0)), at: guAt },
        store_configs: sc === "off" ? "off" : "encrypted",
        subscriptions: { enabled: subsOn, auto_generate: autoGen,   // base_url + serve now live in Access & TLS (access.sub/access.tls)
          languages: { enabled: subLangs, default: subLangDef } },
        throughput_perspective: tput,
        top_talkers: Math.max(1, Math.min(50, parseInt(topTalk) || 10)),
        top_destinations: Math.max(1, Math.min(50, parseInt(topDest) || 10)),
        expiry_warn_days: Math.max(0, Math.min(365, parseInt(warnDays) || 3)),
        reserved: { mesh_subnet: rsvSubnet.trim(), mesh_port_base: +rsvPort || 9999, iface_prefix: rsvPrefix.trim() || "swg_" },
        mesh_awg: awgSet ? awg : {},
        advanced: { node_stale_ms: (+staleS || 30) * 1000, peer_grace_ms: (+graceS || 60) * 1000, geo_ttl_days: +ttlD || 3 },
        hidden_categories: [...hidden],
        custom_lists: lists.map(({ _rid, domains, cidrs, ...l }) => l),   // send id/title/targets/enabled; backend re-derives domains+cidrs
        turn_enabled: turnEnabledS,
        turn_update: { every_days: Math.max(0, Math.min(30, parseInt(tuEvery) || 0)), at: tuAt },
        enabled_turn_forks: [...turnForks],
        turn_fork_colors: forkColorOverrides(),
        iface_colors: ifaceColorOverrides(),
        status_conditions: statusCondsOut(),
        theme_color: themeColorOut(),
        theme_color_light: themeColorLightOut(),
        vk_link: vkLinkS.trim(),
      });
      if (!r.ok) return setMsg({ ok: false, t: srvText(r) || T("Failed to save.") });
    }
    // interface-key escrow — applied on Save (not on toggle), like every other field. Enabling needs the vault unlocked.
    if (ivkEscrow !== null && ivkEscrow !== ivkEscrowInit) {
      if (ivkEscrow && !subSKCached()) {
        const ok = await new Promise(res => pushModal(html`<${VaultPromptSheet} opts=${{ title: T("Unlock to enable escrow"), reason: T("Enabling interface-key escrow seals each server's interface key under your Encryption Vault key. Unlock it to apply.") }} onDone=${res}/>`));
        if (!ok || !subSKCached()) return setMsg({ ok: false, t: T("Enabling key escrow needs the Encryption Vault unlocked.") });
      }
      try { await ivkSetEscrow(ivkEscrow); setIvkEscrowInit(ivkEscrow); }
      catch (e) { return setMsg({ ok: false, t: (e && e.message) || T("Couldn't update key escrow.") }); }
    }
    // per-node changes: one nodeUpdate per node whose edits differ from the saved baseline
    const dSub = rsvSubnet.trim(), dPort = String(+rsvPort || 9999), dPfx = rsvPrefix.trim() || "swg_";
    let nerr = null;
    for (const n of (Store.nodes || [])) {
      const e = nodeEdits[n.id] || {}, o = orig[n.id] || {};
      if (!Object.keys(nFields(n)).some(k => !eq(e[k], o[k]))) continue;
      const nr = await api.nodeUpdate({ id: n.id, routing_mode: e.routing_mode, ip_learning: e.ip_learning !== false, endpoint_host: (e.endpoint_host || "").trim(),
        mesh_subnet: (e.mesh_subnet || "").trim() === dSub ? "" : (e.mesh_subnet || "").trim(),
        mesh_port: (e.mesh_port || "").trim() === dPort ? "" : (e.mesh_port || "").trim(),
        mesh_prefix: (e.mesh_prefix || "").trim() === dPfx ? "" : (e.mesh_prefix || "").trim(),
        default_egress_ip: e.default_egress_ip || "", panel_ip: e.panel_ip || "",
        enabled_categories: e.enabled_categories || [], catalog_cats: e.catalog_cats || [], mesh_awg: e.mesh_awg || {} });
      if (!nr.ok) nerr = srvText(nr) || (T("Couldn't save {v1}", { v1: n.name }));
    }
    if (nerr) return setMsg({ ok: false, t: nerr });
    if (Object.keys(blockEdits).length || blockRemoved.length) {   // block-list category edits (availability/defaults/sources/custom) → panel_settings.block_catalog
      const br = await api.blockCatalogSave({ categories: blockEdits, removed: blockRemoved });
      if (!br.ok) return setMsg({ ok: false, t: srvText(br) || T("Couldn't save block lists.") });
      await loadBlockCatalog(true); setBlockEdits({}); setBlockRemoved([]);
    }
    if (Object.keys(blockProvEdits).length) { await loadBlockCatalog(true); setBlockProvEdits({}); }   // Filters-providers toggles committed via panelSettings above → refresh catalog + clear deltas
    // credentials (if changed) — last, since a username/password change re-auths and forces a reload
    if (secChanged()) {
      // Re-wrap the vault BEFORE the credential change lands. /api/account rotates the session secret, so the
      // moment it returns our cookie is dead and subRewrap's own API calls 401 — it swallows that and returns
      // false, silently leaving the vault sealed under the OLD password. Do it while the session is still
      // valid, and roll back if the credential change is then rejected, so a wrong current password leaves
      // the vault exactly as it was. Same SK throughout — no blob is ever re-encrypted.
      let reWrapped = false;
      if (secNp) {
        if (!subSKCached()) { try { await subUnlock(secCur); } catch (_) {} }   // not unlocked this session — the current password is right here
        if (subSKCached()) { try { reWrapped = await subRewrap(secNp); } catch (_) { reWrapped = false; } }
      }
      const ar = await api.accountSave({ username: secUser.trim(), current_password: secCur, new_password: secNp });
      if (!ar.ok) {
        if (reWrapped) { try { await subRewrap(secCur); } catch (_) {} }   // undo — the password never actually changed
        return setMsg({ ok: false, t: srvText(ar) || T("Couldn't update credentials.") });
      }
      setMsg({ ok: true, t: T("Saved. Reloading — sign in with your new credentials…") });
      return setTimeout(() => location.reload(), 1400);
    }
    setMsg(null); setSaved(Date.now() + 4000);   // green "All settings saved" flash in the header
    await Store.poll();
    const fresh = Object.fromEntries((Store.nodes || []).map(n => [n.id, nFields(n)]));
    setNodeEdits(fresh); setOrig(fresh);
    } catch (e) {
      setMsg({ ok: false, t: T("Couldn't save — {v1}", { v1: (e && e.message) || T("the panel didn't respond. Nothing was lost; try again.") }) });
    }
  };
  // Save click → confirm modal listing the modified values + a reprovisioning warning, then commit.
  const REPROV_WARN = T("Heads up: changing a node's mesh subnet, interface prefix, or AWG params re-provisions its mesh links — it briefly drops off the mesh while every peer pulls the new config and reconnects.");
  const diffList = () => {
    const out = [];
    if ([...hidden].sort().join() !== (ps.hidden_categories || []).slice().sort().join() || listsJSON(lists) !== listsJSON(ps.custom_lists || [])) out.push(T("Routing lists — presets / custom"));
    if (Object.keys(blockEdits).length || blockRemoved.length) out.push(T("Content filters — categories / lists"));
    if (secChanged()) out.push(T("Authentication — panel credentials"));
    if (glDirty("turn")) out.push(T("Turn proxies — forks / colours / VK link"));
    if (glDirty("geo")) out.push(T("Geo data providers"));
    if (glDirty("defaults")) out.push("Interfaces — colours / defaults");
    if (glDirty("configs")) out.push(T("Client configs → {v1}", { v1: sc === "off" ? T("val|off") : T("val|encrypted") }));
    if (glDirty("subs")) out.push("Subscriptions — enable / languages");
    if (glDirty("display")) out.push(T("Display — theme / status timing"));
    if (glDirty("mesh")) out.push(T("System mesh defaults"));
    for (const n of (Store.nodes || [])) {
      const e = nodeEdits[n.id] || {}, o = orig[n.id] || {}, fl = [];
      if (!eq(e.routing_mode, o.routing_mode)) fl.push(T("mode → {v1}", { v1: e.routing_mode }));
      if (!eq(e.ip_learning !== false, o.ip_learning !== false)) fl.push(T("IP learning → {v1}", { v1: e.ip_learning !== false ? T("val|on") : T("val|off") }));
      if (!eq(e.endpoint_host, o.endpoint_host)) fl.push(T("ingress IP → {v1}", { v1: e.endpoint_host || T("val|auto") }));
      if (!eq(e.mesh_subnet, o.mesh_subnet)) fl.push(T("mesh subnet → {v1}", { v1: e.mesh_subnet || T("val|default") }));
      if (!eq(e.mesh_port, o.mesh_port)) fl.push(T("mesh port → {v1}", { v1: e.mesh_port || T("val|default") }));
      if (!eq(e.mesh_prefix, o.mesh_prefix)) fl.push(T("prefix → {v1}", { v1: e.mesh_prefix || T("val|default") }));
      if (!eq(e.default_egress_ip, o.default_egress_ip)) fl.push(T("egress IP → {v1}", { v1: e.default_egress_ip || T("val|auto") }));
      if (!eq(e.panel_ip, o.panel_ip)) fl.push(T("panel IP → {v1}", { v1: e.panel_ip || T("val|auto") }));
      if (!eq(e.enabled_categories, o.enabled_categories)) fl.push(T("enabled lists"));
      if (!eq(e.catalog_cats, o.catalog_cats)) fl.push(T("catalog categories"));
      if (!eq(e.mesh_awg, o.mesh_awg)) fl.push(T("mesh AWG params"));
      if (fl.length) out.push(n.name + " — " + fl.join(", "));
    }
    return out;
  };
  const needsReprov = () => (Store.nodes || []).some(n => { const e = nodeEdits[n.id] || {}, o = orig[n.id] || {}; return !eq(e.mesh_subnet, o.mesh_subnet) || !eq(e.mesh_prefix, o.mesh_prefix) || !eq(e.mesh_awg, o.mesh_awg); });
  const confirmSave = () => {
    const ch = diffList();
    if (!ch.length) { toast(T("No changes to save."), "ok"); return; }
    const rp = needsReprov();
    openConfirm({ title: T("Save settings"), confirmLabel: T("Save"), busyLabel: T("Saving…"), warn: rp, onConfirm: save,
      body: html`<div class="savediff"><div class="savediff-h">${T("{v1} to apply:", { v1: plural(ch.length, "change") })}</div><ul>${ch.map(c => html`<li>${c}</li>`)}</ul>${rp ? html`<div class="savediff-w">${REPROV_WARN}</div>` : null}</div>`,
      note: html`<div class="savediff-note">${T("Applying can take up to a minute — the nodes reconfigure and re-pull their lists. This stays open until it finishes.")}</div>` });
  };
  const refreshGeo = async () => { const r = await api.refreshGeo(); toast(r.ok ? T("Geo lists will refresh on each node's next sync.") : (srvText(r) || T("Failed")), r.ok ? "ok" : "err"); };
    // Custom lists AUTOSAVE on add/edit/delete — they persist on their own (POST just custom_lists), no global Save needed.
  // Re-baseline the local rows from the server afterwards so the row content + the routing dirty-state both stay correct.
  const persistLists = async newLists => {
    setLists(newLists);
    const r = await api.panelSettings({ custom_lists: newLists.map(({ _rid, domains, cidrs, ...l }) => l) });
    if (!r.ok) return setMsg({ ok: false, t: srvText(r) || T("Couldn't save the list.") });
    await Store.poll();
    const ridById = Object.fromEntries(newLists.filter(l => l.id).map(l => [l.id, l._rid]));   // keep row identity so a per-node toggle / edit doesn't remount every row
    setLists(((Store.panelSettings || {}).custom_lists || []).map(l => ({ ...l, _rid: ridById[l.id] || newRid(), targets: [...(l.domains || []), ...(l.cidrs || [])].join(", ") })));
    setSaved(Date.now() + 2500);
  };
  const openList = l => openModal(html`<${CustomListSheet} list=${l} onSave=${nl => persistLists(l ? lists.map(x => x._rid === nl._rid ? nl : x) : [...lists, nl])} onClose=${closeModal}/>`);
  const confirmDeleteList = l => openConfirm({ title: T("Delete custom list"), confirmLabel: T("Delete"), danger: true,
    body: Trich("Delete *{v1}*? It's removed from *every node* it's enabled on, and its interface rules stop matching on the next sync. This can't be undone.", { v1: l.title || T("Untitled list") }),
    onConfirm: () => persistLists(lists.filter(x => x._rid !== l._rid)) });
    const SECTIONS = [["display", "Display"], ["security", "Authentication"], ["access", "Panel URL"], ["configs", "Client configs"], ["subs", "Subscriptions"], ["mesh", "Mesh & egress"], ["defaults", "Interfaces"], ["turn", "Turn proxies"], ["routing", "Routing & Blocking"], ["geo", "Geo data providers"], ["integrations", "Integrations"]]   // i18n-keys: canonical (deep-link + persisted section); sectionLabel() below carries the display names
/* Display names for SECTIONS. The array above stays the canonical key list (the value is the deep-link and
   the persisted section), so only the LABEL is translated — literal T() calls, same as evItemLabel. */
const sectionLabel = k => ({
  display: T("Display"), security: T("Authentication"), access: T("Panel URL"), configs: T("Client configs"),
  subs: T("Subscriptions"), mesh: T("Mesh & egress"), defaults: T("Interfaces"),
  turn: T("Turn proxies"), routing: T("Routing & Blocking"), geo: T("Geo data providers"),
  integrations: T("Integrations"),
}[k] || k);   // i18n-keys
  // per-node context: the node whose mode/lists/mesh/egress we're editing — defaults to the first node (no "default")
  const [selNode, setSelNode] = useState(() => ((Store.nodes || [])[0] || {}).id || "");
  const perNodeSection = section === "routing" || section === "mesh";
  const nodeRec = (Store.nodes || []).find(n => n.id === selNode);
  const nodeMode = nv(selNode, "routing_mode") || "kernel";       // DRAFT mode being edited (drives the mode card + tabs)
  const setMode = m => setNV(selNode, { routing_mode: m });
  const savedMode = (nodeRec && nodeRec.routing_mode) || "kernel"; // what the node is ACTUALLY running (drives the status runbar — only changes on Save)
  const ipLearn = nv(selNode, "ip_learning") !== false;           // per-node "remember learned IPs" toggle (default on)
  const setIpLearn = v => setNV(selNode, { ip_learning: v });
    // node-lens for the provider catalog: catalog_cats[] = the categories the operator opted THIS node into (staged; commits on Save)
  const ccOf = nid => nv(nid, "catalog_cats") || [];
  const addCatalogCat = id => { if (!id || id === "all" || (lists || []).some(l => l.id === id) || id === "custom") return; setNV(selNode, { catalog_cats: [...new Set([...ccOf(selNode), id])] }); };   // provider cats + curated presets (bare id) are both first-class opt-ins
  const removeCatalogCat = id => setNV(selNode, { catalog_cats: ccOf(selNode).filter(c => c !== id) });
  // Fleet-wide provider-list grid: rows = the union of every node's opted-in provider cats. gridKeep holds ids that
  // must stay visible even at 0/N nodes (so toggling PULL off doesn't make the row vanish — only × removes it).
  const fleetNodes = Store.nodes || [];
  const catOnNode = (id, nid) => ccOf(nid).includes(id);
  const setCatOnNode = (id, nid, on) => setNV(nid, { catalog_cats: on ? [...new Set([...ccOf(nid), id])] : ccOf(nid).filter(c => c !== id) });
  const pullCatOnNode = (id, on) => { setCatOnNode(id, selNode, on); if (!on) setGridKeep(g => g.includes(id) ? g : [...g, id]); };   // keep the row even at 0/N
  const fleetToggleCat = (id, nid, on) => { setCatOnNode(id, nid, on); if (!on) setGridKeep(g => g.includes(id) ? g : [...g, id]); };   // fleet popover toggle: keep the row visible at 0/N
  const removeCatFleet = id => { fleetNodes.forEach(n => { if (ccOf(n.id).includes(id)) setCatOnNode(id, n.id, false); }); setGridKeep(g => g.filter(x => x !== id)); };   // × drops it everywhere + hides the row
  const provFleetCats = [...new Set([...fleetNodes.flatMap(n => ccOf(n.id)), ...gridKeep])].sort((a, b) => catLabelOf(a).toLowerCase().localeCompare(catLabelOf(b).toLowerCase()));
  const compatCats = () => provFleetCats.filter(id => catUsableInMode(id, nodeMode));   // usable on selNode in its mode (shared rule)
  const allCompatOn = () => compatCats().length > 0 && compatCats().every(id => catOnNode(id, selNode));
  const toggleAllCompat = () => { const off = allCompatOn();
    if (off) setGridKeep(g => [...new Set([...g, ...compatCats()])]);              // Disable all: keep the rows visible (0/N)
    setNV(selNode, { catalog_cats: off ? ccOf(selNode).filter(id => !compatCats().includes(id)) : [...new Set([...ccOf(selNode), ...compatCats()])] }); };
  const confirmRemoveCat = id => openConfirm({ title: T("Remove list from the fleet"), confirmLabel: T("Remove"), danger: true,
    body: Trich("Remove *{v1}* {v2} from *every node*? Interface rules that use it stop matching, and each node drops its records on the next sync. You can add it back from the catalog any time.",
      { v1: catLabelOf(id), v2: html`<span class="faint">(${provLabelOf(id)})</span>` }),
    onConfirm: () => removeCatFleet(id) });
  const catSaved = id => fleetNodes.some(n => ((orig[n.id] || {}).catalog_cats || []).includes(id));   // present in the last-SAVED fleet state → removing it is a real change (confirm); a draft-only add this session isn't
  const removeCatRow = id => catSaved(id) ? confirmRemoveCat(id) : removeCatFleet(id);   // × removes a just-added (unsaved) list with no prompt; only saved lists confirm
  const customOnNode = (l, nid) => !(l.disabled_nodes || []).includes(nid);
  const setCustomOnNode = (l, nid, on) => persistLists(lists.map(x => x._rid === l._rid ? { ...x, disabled_nodes: on ? (x.disabled_nodes || []).filter(z => z !== nid) : [...new Set([...(x.disabled_nodes || []), nid])] } : x));
  // dirty tracking — per global section + per node-per-section, drives the rail dots and badge glow
  const SECF = { routing: ["routing_mode", "ip_learning", "enabled_categories", "catalog_cats"], mesh: ["endpoint_host", "mesh_subnet", "mesh_port", "mesh_prefix", "mesh_awg", "default_egress_ip", "panel_ip"] };
  const nodeDirty = (nid, sec) => (SECF[sec] || []).some(f => !eq((nodeEdits[nid] || {})[f], (orig[nid] || {})[f]));
  const listsJSON = ls => JSON.stringify((ls || []).map(l => ({ id: l.id || "", title: l.title || "", enabled: l.enabled !== false, targets: (l.targets ?? [...(l.domains || []), ...(l.cidrs || [])].join(", ")).trim() })));
  const glDirty = sec =>
    sec === "routing" ? ([...hidden].sort().join() !== (ps.hidden_categories || []).slice().sort().join() || listsJSON(lists) !== listsJSON(ps.custom_lists || []) || Object.keys(blockEdits).length > 0 || blockRemoved.length > 0) :
    sec === "turn" ? (turnEnabledS !== (ps.turn_enabled !== false) || [...turnForks].sort().join() !== (ps.enabled_turn_forks || TURN_FORKS_DEFAULT).slice().sort().join() || JSON.stringify(forkColorOverrides()) !== JSON.stringify(forkOvFrom(ps.turn_fork_colors)) || vkLinkS.trim() !== (ps.vk_link || "") || String(Math.max(0, parseInt(tuEvery) || 0)) !== String((ps.turn_update || {}).every_days == null ? 0 : (ps.turn_update || {}).every_days) || tuAt !== ((ps.turn_update || {}).at || "04:00")) :
    sec === "security" ? secChanged() :
    sec === "geo" ? (JSON.stringify(provEnabled) !== JSON.stringify(Object.fromEntries((Store.catalogProviders || []).map(p => [p.id, p.enabled !== false]))) || Object.keys(blockProvEdits).length > 0 || JSON.stringify(provColorOverrides()) !== JSON.stringify(ps.provider_colors || {}) || customEnabled !== (ps.custom_lists_enabled !== false) || String(Math.max(0, parseInt(guEvery) || 0)) !== String(_gu.every_days == null ? 1 : _gu.every_days) || guAt !== (_gu.at || "04:00")) :
    sec === "defaults" ? (dns !== (idf.dns || []).join(", ") || mtu !== String(idf.mtu || 1280) || ka !== String(idf.keepalive || 25) || JSON.stringify(ifaceColorOverrides()) !== JSON.stringify(ifaceOvFrom(ps.iface_colors)) || JSON.stringify(statusCondsOut()) !== JSON.stringify({ blocked: (ps.status_conditions || {}).blocked !== false, faulty: (ps.status_conditions || {}).faulty !== false }) || (ivkEscrow !== null && ivkEscrow !== ivkEscrowInit)) :
    sec === "configs" ? (sc !== _scMode) :
    sec === "subs" ? (subsOn !== !!subCfg.enabled || autoGen !== !!subCfg.auto_generate || warnDays !== String(ps.expiry_warn_days == null ? 3 : ps.expiry_warn_days) || JSON.stringify([...subLangs].sort()) !== JSON.stringify([...(subLangCfg.enabled || ["en"])].sort()) || subLangDef !== (subLangCfg.default || "en")) :
    sec === "display" ? (tput !== (ps.throughput_perspective === "peers" ? "peers" : "nodes") || staleS !== String(Math.round((adv.node_stale_ms || 30000) / 1000)) || graceS !== String(Math.round((adv.peer_grace_ms || 60000) / 1000)) || topTalk !== String(ps.top_talkers || 10) || topDest !== String(ps.top_destinations || 10) || themeColorS.toLowerCase() !== clampBrand(ps.theme_color || THEME_COLOR_DEFAULT, false).toLowerCase() || themeColorLightS.toLowerCase() !== clampBrand(ps.theme_color_light || THEME_COLOR_LIGHT_DEFAULT, true).toLowerCase()) :
    sec === "mesh" ? (rsvSubnet !== (rsv.mesh_subnet || "10.255.0.0/16") || rsvPort !== String(rsv.mesh_port_base || 9999) || rsvPrefix !== (rsv.iface_prefix || "swg_") || JSON.stringify(awgSet ? awg : {}) !== JSON.stringify(ps.mesh_awg || {})) : false;
  const secDirty = sec => glDirty(sec) || (SECF[sec] ? (Store.nodes || []).some(n => nodeDirty(n.id, sec)) : false);
  const badgeDirty = nid => nid === "" ? glDirty(section) : nodeDirty(nid, section);
  const anyDirty = SECTIONS.some(([s]) => secDirty(s));
  // Unsaved-changes guard: warn before leaving (in-app nav via the router, the Back button, or a browser refresh/close)
  const dirtyRef = useRef(anyDirty); dirtyRef.current = anyDirty;
  useEffect(() => {
    setUnsavedGuard(() => dirtyRef.current);
    const bu = e => { if (dirtyRef.current) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", bu);
    return () => { clearUnsavedGuard(); window.removeEventListener("beforeunload", bu); };
  }, []);
  // LEAVE_MSG() — it is a function so the lookup happens after loadLang(); passing it uncalled hands
  // confirm() a function, which it stringifies, and the dialog shows this line's source instead of the question.
  const leaveSettings = () => { if (!anyDirty || confirm(LEAVE_MSG())) { clearUnsavedGuard(); history.back(); } };
  const MODES = [
    ["kernel", T("Default — IP only. DNS not involved"), T("Matches by destination IP (GeoIP / ASN) — routing never depends on DNS, so your clients' DoH, DoT and plain DNS all keep working untouched. Simplest and most robust; it just can't separate services that share IPs (YouTube vs Google), and a CDN category catches everything behind it. Lists: GeoIP + Custom IPs.")],
    ["forcedns", T("Force DNS — Host + IP. Overrides encrypted DNS"), T("The node becomes your clients' resolver and blocks their encrypted DNS — both DoH (known providers) and all DoT — so it can route by hostname too, per-service precise. Trade-off: it sees and downgrades the client's DNS, can break a client that insists on its own encrypted DNS, and a DoH server it doesn't recognise can still slip past. Lists: GeoSite (host) + GeoIP + Custom IPs/domains.")],
    ["sni", T("SNI Sniffer — Host + IP. DNS stays private"), T("Routes by hostname by reading the SNI from each TLS handshake, so your clients' DNS — DoH, DoT or plain — is never touched, observed or downgraded: the connection stays encrypted end-to-end. Learns each destination on its first connection (a brand-new host routes on the next one); names hidden by ECH, and QUIC / HTTP3, fall back to IP routing. Lists: GeoSite (host) + GeoIP + Custom IPs/domains.")],
  ];
  return html`<div class="screen setscreen">
    <div class="sethead">${Trich("*Panel settings*")}</div>
    ${msg ? html`<div class=${"formmsg " + (msg.ok ? "ok" : "err")}>${msg.t}</div>` : null}
    <div class="setbody">
      <nav class="setrail">${SECTIONS.map(([id]) => html`<button class=${"setrail-i" + (section === id ? " on" : "")} onClick=${() => setSection(id)}>${sectionLabel(id)}${secDirty(id) ? html`<span class="dirtydot"></span>` : null}</button>`)}</nav>
      <div class="setpane">
        ${perNodeSection && (Store.nodes || []).length ? html`<div class="setnodes">${(Store.nodes || []).map(n => html`<button class=${"snbadge" + (selNode === n.id ? " on" : "") + (badgeDirty(n.id) ? " dirty" : "")} style=${"--c:" + Store.nodeColor(n.id)} onClick=${() => setSelNode(n.id)}><span class="ndot"></span>${n.name}</button>`)}</div>` : null}
        ${section === "routing" ? html`<div class="card rcard">
          ${(() => { const mm = MODE_META[nodeMode] || MODE_META.kernel;
            const resetBtn = html`<${Popover} hoverOnly cls="rmode-resetwrap" popCls="rmode-reset-pop"
                  trigger=${html`<button class="rmode-reset-ic" onClick=${() => resetRouting(selNode, nodeRec ? nodeRec.name : T("this node"))}><${Ic} i="refresh"/></button>`}>
                  <div class="rmode-reset-pop-body">${T("Reset this node's smart routing — clear just the learned IPs, or wipe + rebuild + re-pull every list. Use it to recover a stuck node.")}</div>
                <//>`;
            const mmRun = MODE_META[savedMode] || MODE_META.kernel;   // runbar reflects the SAVED/running mode, not the draft
            const caption = html`<div class="rmr-title">${Trich("{v1} currently runs on {v2}", {
      v1: html`<b class="rmr-node">${nodeRec ? nodeRec.name : T("Node")}</b>`,
      v2: html`<b class="rmr-mode">${mmRun.label}</b>`,
    })}</div>`;
            const infoPop = html`<${Popover} hoverOnly cls="rmode-info" popCls="rmode-info-pop" trigger=${html`<span class="rmode-infobtn"><${Ic} i="info"/></span>`}>
                  <div class="rmode-info-body">${Trich("Every mode matches by destination *IP* first (GeoIP / ASN / your IP lists) — that layer is *always on* and carries all traffic, including calls, UDP and QUIC. The choice adds an optional *host (domain)* matching layer on top: none, via the node's *DNS*, or read from the *TLS handshake*. Traffic always stays in-kernel in any mode including *{v1}* (no userspace proxy). Changing it reconfigures {v2} and changes which lists its interfaces can use.", { v1: T("Hybrid SNI"), v2: nodeRec ? nodeRec.name : T("the node") })}<div style="margin-top:9px">${Trich("*Reset routing* recovers a stuck node — clear just the learned IPs, or wipe + rebuild + re-pull everything.")}</div></div>
                <//>`;
            const runbar = savedMode === "kernel"
              ? html`<div class="rmode-runbar">
                  ${caption}
                  <span class="grow"></span>
                  <div class="rmr-actions">${infoPop}${resetBtn}</div>
                </div>`
              : html`<div class="rmode-runbar">
                  <div class="rmr-left">
                    <${HostHealth} node=${selNode} mode=${savedMode} learn=${ipLearn} onLearn=${setIpLearn}/>
                  </div>
                  <span class="grow"></span>
                  <div class="rmr-right">
                    <div class="rmr-rtop">${caption}${infoPop}${resetBtn}</div>
                  </div>
                </div>`;
            return html`
          ${runbar}
          <div class=${"rmode-banner m-" + nodeMode}>
            <div class="rd-head">
              <div class="rd-headmain">
                <div class="rd-titlerow">
                  <span class="rd-ic"><${Ic} i=${mm.icon}/></span>
                  <b class="rd-name">${mm.label}</b>
                  <span class="rmc-tag">${mm.short}</span>
                </div>
                <div class="rd-adds">${mm.adds}</div>
              </div>
              <div class="rd-headside">
                <${ModeTabs} value=${nodeMode} onChange=${setMode}/>
                ${mm.lists ? html`<div class="rmode-lists">${mm.lists.map((l, i) => html`${i ? " + " : ""}<b>${l}</b>`)}</div>` : null}
              </div>
            </div>
            <div class="rd-lines">
              ${(mm.bene || []).map(b => html`<div class="rmc-bene"><b>+</b><span>${b}</span></div>`)}
              ${(Array.isArray(mm.block) ? mm.block : mm.block ? [mm.block] : []).filter(x => x.s === "+").map(x => html`<div class="rmc-bene"><b>+</b><span>${x.t}</span></div>`)}
              <div class="rmc-cost"><b>−</b><span>${mm.cost}</span></div>
              ${(Array.isArray(mm.block) ? mm.block : mm.block ? [mm.block] : []).filter(x => x.s === "−").map(x => html`<div class="rmc-cost"><b>−</b><span>${x.t}</span></div>`)}
            </div>
            <div class="rmode-desc">${mm.exp}</div>
          </div>`; })()}

          <div class="rltabs">
            <div class="rltab-cap">${Trich("{v1} for {v2}", {
              v1: routeTab === "blocking" ? T("Content filters") : T("Routing lists"),
              v2: html`<b style=${"color:" + (Store.nodeColor(selNode) || "var(--ink)")}>${nodeRec ? nodeRec.name : T("this node")}</b>`,
            })}</div>
            <div class="rltab-group" role="tablist">
              <button role="tab" aria-selected=${routeTab === "routing"} class=${"rltab" + (routeTab === "routing" ? " on" : "")} onClick=${() => setRouteTab("routing")}><${Ic} i="cascade"/>${T("Routing")}</button>
              <button role="tab" aria-selected=${routeTab === "blocking"} class=${"rltab" + (routeTab === "blocking" ? " on" : "")} onClick=${() => setRouteTab("blocking")}><${Ic} i="shield"/>${T("Blocking")}</button>
            </div>
          </div>
          <div class="hint rltab-note"><${Ic} i="info"/><span>${routeTab === "blocking" ? T("Filtering runs on the entry node — where a client's tunnel lands. Exit and relay hops in a multi-hop path never see the client, so there's nothing there for them to filter.") : T("Routing runs on the entry node — where a client's tunnel lands. Exit and relay hops in a multi-hop path just forward what's already been steered.")}</span></div>
          ${routeTab === "blocking" ? html`<div class="hint rltab-warn"><${Ic} i="warn"/><span>${Trich("Large lists are memory-hungry — every enabled list is loaded into RAM on *each* entry node that uses it, roughly *130 MB per 1M domains*. Keep your smallest node's memory in mind before turning on big lists.")}</span></div>` : null}

          ${routeTab === "routing" ? html`
          <div class="lgrid-head">
            <div class="lg-htitle"><span class="seclabel" style="margin:0">${T("Provider lists")}</span><span class="lg-count">${provFleetCats.length}</span><span class="faint lg-sub">${T("provider-maintained · read-only")}</span></div>
            <span class="grow"></span>
            ${compatCats().length ? html`<button class="btn btn-mini" onClick=${toggleAllCompat}>${allCompatOn() ? T("Disable all") : T("Enable all")}</button>` : null}
            <${CatPicker} addMode=${true} primary=${true} mode=${nodeMode} triggerLabel=${T("Add preset list")} selected=${ccOf(selNode)} onChange=${id => ccOf(selNode).includes(id) ? removeCatalogCat(id) : addCatalogCat(id)} onAdd=${id => { if (!ccOf(selNode).includes(id)) addCatalogCat(id); }}/>
          </div>
          ${provFleetCats.length ? html`<div class="lgrid">
            ${provFleetCats.map(id => { const cap = catCap(id); const usable = catUsableInMode(id, nodeMode); const sz = (Store.catSizes || {})[id] || {};
              return html`<div class=${"lgrow" + (usable ? "" : " lg-lock")} key=${id}>
                <div class="lg-pull"><${Switch} on=${catOnNode(id, selNode)} disabled=${!usable} title=${usable ? T("Pull this list on {v1}", { v1: nodeRec ? nodeRec.name : T("this node") }) : T("Host-only — needs Force-DNS or SNI on this node")} onChange=${v => pullCatOnNode(id, v)}/></div>
                <div class="lg-cat"><div class="lg-catmain"><span class="lg-title">${catLabelOf(id)}</span>${provLabelOf(id) ? html`<${ProvTag} id=${id}/>` : null}</div>${catRawId(id) ? html`<span class="lg-id">${catRawId(id)}</span>` : null}</div>
                <div class="lg-size">${sizeSummary(sz.host || 0, sz.ip || 0) || html`<span class="faint">—</span>`}</div>
                <div class="lg-fleet"><${FleetAssign} nodes=${fleetNodes} isOn=${nid => catOnNode(id, nid)} onToggle=${(nid, on) => fleetToggleCat(id, nid, on)} disabledFor=${nid => (nv(nid, "routing_mode") || "kernel") === "kernel" && !cap.ip ? T("Host-only — this node is IP-only") : null}/></div>
                <div class="lg-caps">${capBadges(cap)}</div>
                <div class="lg-act">${catListUrl(id, cap) ? html`<a class="ccchip-info" href=${catListUrl(id, cap)} target="_blank" rel="noopener" title=${T("View this list on GitHub")}><${Ic} i="info"/></a>`
                  : catDescOf(id) ? html`<${DescInfo} text=${catDescOf(id)}/>` : null}<button class="ccchip-x" title=${T("Remove from the fleet")} onClick=${() => removeCatRow(id)}><${Ic} i="x"/></button></div>
              </div>`; })}
          </div>` : html`<div class="hint" style="margin:2px 0 0">${Trich("No preset lists yet — use *Add preset list* to pull from the catalog.")}</div>`}

          ${(Store.panelSettings || {}).custom_lists_enabled !== false ? html`
          <div class="lgrid-head" style="margin-top:26px">
            <div class="lg-htitle"><span class="seclabel" style="margin:0">${T("Custom lists")}</span><span class="lg-count">${lists.length}</span><span class="faint lg-sub">${T("your own IPs / domains · editable · apply immediately")}</span></div>
            <span class="grow"></span>
            <button class="btn btn-add" onClick=${() => openList(null)}><${Ic} i="plus"/>${T("New custom list")}</button>
          </div>
          ${lists.length ? html`<div class="lgrid">
            ${[...lists].sort((a, b) => (a.title || "").toLowerCase().localeCompare((b.title || "").toLowerCase())).map(l => { const cap = customCaps(l);
              return html`<div class="lgrow" key=${l._rid}>
                <div class="lg-pull"><${Switch} on=${customOnNode(l, selNode)} title=${T("Enable on {v1}", { v1: nodeRec ? nodeRec.name : T("this node") })} onChange=${v => setCustomOnNode(l, selNode, v)}/></div>
                <div class="lg-cat"><div class="lg-catmain"><button class="lg-title" onClick=${() => openList(l)}>${l.title || T("Untitled list")}</button><span class="catpick-src" style=${"--pc:" + providerColor("custom")}>${T("src|Custom")}</span></div><button class="lg-id" onClick=${() => openList(l)}>${T("edit")}</button></div>
                <div class="lg-size"><${ListInfo} list=${l}/></div>
                <div class="lg-fleet"><${FleetAssign} nodes=${fleetNodes} isOn=${nid => customOnNode(l, nid)} onToggle=${(nid, on) => setCustomOnNode(l, nid, on)}/></div>
                <div class="lg-caps">${capBadges(cap)}</div>
                <div class="lg-act"><button class="ccchip-x" title=${T("Delete this list")} onClick=${() => confirmDeleteList(l)}><${Ic} i="x"/></button></div>
              </div>`; })}
          </div>` : html`<div class="hint" style="margin:2px 0 0">${T("No custom lists yet.")}</div>`}` : null}

          <div class="lg-legend">
            <div class="lg-leg-row">${Trich("{v1} matched by address range (GeoIP / ASN) — works in every mode.", { v1: html`<span class="capb ip">IP</span>` })}</div>
            <div class="lg-leg-row">${Trich("{v1} matched by domain name — needs Force-DNS or SNI mode.", { v1: html`<span class="capb host">${T("Host")}</span>` })}</div>
            ${provFleetCats.some(id => !catUsableInMode(id, nodeMode)) ? html`<div class="lg-leg-row faint">${T("Greyed rows are Host-only — this node is IP-only, so they can't match here. The pull stays remembered; switch to Force-DNS or SNI to activate them.")}</div>` : null}
          </div>` : null}

          ${routeTab === "blocking" ? (() => {
            const bc = Store.blockCatalog;
            if (!bc) return html`<div class="hint" style="margin:8px 0 0">${T("Loading block lists…")}</div>`;
            const provList = bc.provider_lists || {};
            const provLabel = p => ((bc.providers || []).find(x => x.id === p) || {}).label || p;
            const provTier = p => ((bc.providers || []).find(x => x.id === p) || {}).tier || "host";
            const provColor = p => { const bp = (bc.providers || []).find(x => x.id === p) || {}; return pickThemed(provColors[p] || asThemed((ps.provider_colors || {})[p], bp.color, bp.color_l || bp.color), _provColDefault(p).dark, _provColDefault(p).light); };
            const srcLabel = s => { const L = (provList[s.provider] || []).find(x => x.id === (s.list || "")); return (L && L.label) || s.list || provLabel(s.provider); };
            const bcat = id => { const b = (bc.categories || {})[id] || {}; return { id, ...b, ...(blockEdits[id] || {}) }; };
            const allIds = [...new Set([...(bc.cat_order || []), ...Object.keys(bc.categories || {}), ...Object.keys(blockEdits)])];
            const cats = allIds.map(bcat).filter(c => c.kind !== "mechanism" && !blockRemoved.includes(c.id));
            const caps = c => { const s = c.sources || []; return { host: s.some(x => provTier(x.provider) === "host"), ip: s.some(x => provTier(x.provider) === "ip") }; };
            const fmtN = n => n == null ? null : n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1).replace(/\.0$/, "") + "M" : n >= 1e3 ? (n / 1e3).toFixed(n >= 1e4 ? 0 : 1).replace(/\.0$/, "") + "k" : String(n);
            const catTotal = c => { const sz = c.size; if (!sz) return null; const t = (sz.host || 0) + (sz.ip || 0); return t ? fmtN(t) : null; };
            const createCat = ({ id, label }) => { setBlockEdits(e => ({ ...e, [id]: { label, sources: [], enabled_nodes: [] } })); setBkOpen(o => ({ ...o, [id]: true })); setBkAutoAdd(id);
              requestAnimationFrame(() => requestAnimationFrame(() => {   // scroll fully to the bottom so the just-added category (+ its auto-opened picker) is in view
                const items = document.querySelectorAll(".bkitem"); const el = items[items.length - 1]; if (!el) return;
                let p = el.parentElement;
                while (p) { const st = getComputedStyle(p).overflowY; if ((st === "auto" || st === "scroll") && p.scrollHeight > p.clientHeight + 4) { p.scrollTo({ top: p.scrollHeight, behavior: "smooth" }); break; } p = p.parentElement; }
                window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
              })); };
            const doRemoveCat = c => { setBkOpen(o => ({ ...o, [c.id]: false })); if ((bc.categories || {})[c.id]) setBlockRemoved(r => r.includes(c.id) ? r : [...r, c.id]); setBlockEdits(e => { const n = { ...e }; delete n[c.id]; return n; }); };
            const removeCat = c => { if ((bc.categories || {})[c.id])   // a SAVED custom category → confirm; an unsaved draft removes with no prompt
                openConfirm({ title: T("Delete category · ") + c.label, confirmLabel: T("Delete category"), danger: true,
                  body: T("Removes this custom category and its lists. It's deleted from the panel when you Save, and nodes stop filtering it on their next sync. You'd have to recreate it to bring it back."),
                  onConfirm: () => doRemoveCat(c) });
              else doRemoveCat(c); };
            const availOn = c => (c.enabled_nodes || []).includes(selNode);
            const modeLabel = (MODE_META[nodeMode] || {}).label || T("this mode");
            const srcAvail = s => blockSrcOk(nodeMode, bc.providers, s);   // shared rule: IP everywhere, domain needs Force-DNS/Hybrid
            // A category with NO IP list can't enforce anything in Default (IP-only) or Kernel-SNI — every list shows "not
            // available". Then the whole category is dead here: show it disabled and don't let it be enabled on this node.
            const catDis = c => blockCatDisabled(nodeMode, bc.providers, c);
            const srcHost = s => provTier(s.provider) !== "ip";
            const setAvail = (c, on) => { const en = new Set(c.enabled_nodes || []); on ? en.add(selNode) : en.delete(selNode);
              setBlockEdits(e => ({ ...e, [c.id]: { ...(e[c.id] || {}), enabled_nodes: [...en] } })); };
            const setDefault = (c, on) => setBlockEdits(e => ({ ...e, [c.id]: { ...(e[c.id] || {}), default_on: on } }));
            const setSources = (c, sources) => setBlockEdits(e => ({ ...e, [c.id]: { ...(e[c.id] || {}), sources } }));
            const addSource = (c, p, l) => { if ((c.sources || []).some(s => s.provider === p && s.list === l)) return; setSources(c, [...(c.sources || []), { provider: p, list: l }]); };
            const removeSource = (c, i) => setSources(c, (c.sources || []).filter((_, j) => j !== i));
            const srcDesc = s => { const L = (provList[s.provider] || []).find(x => x.id === (s.list || "")); return (L && L.desc) || ""; };
            const srcUrl = s => { const L = (provList[s.provider] || []).find(x => x.id === (s.list || "")); return (L && L.src) || ""; };
            const setAvailNode = (c, nid, on) => { const en = new Set(c.enabled_nodes || []); on ? en.add(nid) : en.delete(nid);
              setBlockEdits(e => ({ ...e, [c.id]: { ...(e[c.id] || {}), enabled_nodes: [...en] } })); };
            const bkRow = c => { const src = c.sources || []; const nL = src.length; const open = !!bkOpen[c.id]; const dis = catDis(c);
              return html`<div class=${"bkitem" + (open ? " open" : "") + (dis ? " bk-dis" : "")} key=${c.id}>
                <div class=${"bkrow" + (open ? " open" : "")} onClick=${() => setBkOpen(o => ({ ...o, [c.id]: !open }))}>
                  <div class="lg-pull" onClick=${e => e.stopPropagation()}><${Switch} on=${availOn(c) && !dis} disabled=${dis} title=${dis ? T("No IP list here — can't enforce in {v1}. Add an IP list, or use Force-DNS / Hybrid-SNI.", { v1: modeLabel }) : T("Filter on {v1}", { v1: nodeRec ? nodeRec.name : T("this node") })} onChange=${v => { if (!dis) setAvail(c, v); }}/></div>
                  <div class="bk-cat">
                    <div class="bk-catline"><span class="lg-title">${c.label}</span><span class="bk-chev">▾</span></div>
                    <div class="bk-lists">${nL ? src.map(srcLabel).join(", ") : html`<span class="faint">${T("no lists yet — add one →")}</span>`}</div>
                  </div>
                  <div class="bk-kind">${!c.predefined ? html`<span class="capb custom" title=${T("A category you created")}>${T("src|Custom")}</span>` : null}</div>
                  <div class="bk-size">${(() => { const t = catTotal(c); return t ? html`<span class="bk-count" title=${T("Total entries across this category’s lists")}>${t}</span>` : null; })()}</div>
                  <div class="bk-fleet" onClick=${e => e.stopPropagation()}><${FleetAssign} nodes=${fleetNodes} isOn=${nid => (c.enabled_nodes || []).includes(nid)} onToggle=${(nid, on) => setAvailNode(c, nid, on)}/></div>
                  <div class="bk-cap">${(() => { const cp = caps(c); return cp.host || cp.ip
                    ? html`<${Fragment}>${cp.host ? html`<span class="capb host" title=${T("Matched by domain — needs Force-DNS or Hybrid-SNI mode")}>${T("Host")}</span>` : null}${cp.ip ? html`<span class="capb ip" title=${T("Matched by IP — works in every mode")}>IP</span>` : null}<//>`
                    : html`<span class="bk-nocap" title=${T("No lists yet")}>—</span>`; })()}</div>
                  <button class=${"bk-defchip" + (c.default_on ? " on" : "")} onClick=${e => { e.stopPropagation(); setDefault(c, !c.default_on); }} title=${T("Turn this category on automatically for every new interface (still toggled per interface)")}>Default ${c.default_on ? "ON" : "OFF"}</button>
                  <${BlockListPicker} providers=${bc.providers} provLists=${provList} current=${src} nodeMode=${nodeMode} onAdd=${(p, l) => addSource(c, p, l)} autoOpen=${bkAutoAdd === c.id}/>
                </div>
                ${open ? html`<div class="bk-expand">
                  ${src.length ? src.map((s, i) => html`<div class=${"bk-lrow" + (srcAvail(s) ? "" : " bk-ldis")} key=${i}>
                      <div class="bk-linfo">
                        <div class="bk-ltop"><span class="bk-llabel">${srcLabel(s)}</span><span class="bk-lprov" style=${provColor(s.provider) ? "--pc:" + provColor(s.provider) : ""}>${provLabel(s.provider)}</span></div>
                        ${srcDesc(s) ? html`<span class="bk-ldesc">${srcDesc(s)}</span>` : null}
                      </div>
                      <span class="grow"></span>
                      ${!srcAvail(s) ? html`<span class="bk-nabadge">${T("Not available with {v1}", { v1: modeLabel })}</span>` : null}
                      ${s.n != null ? html`<span class="bk-count" title=${srcHost(s) ? T("domains in this list") : T("IP ranges in this list")}>${fmtN(s.n)}</span>` : null}
                      <span class=${"capb " + (srcHost(s) ? "host" : "ip")} title=${srcHost(s) ? T("Domain list — needs Force-DNS or Hybrid-SNI mode") : T("IP list — works in every mode")}>${srcHost(s) ? T("Host") : T("cap|IP")}</span>
                      ${srcUrl(s) ? html`<a class="catrow-info" href=${srcUrl(s)} target="_blank" rel="noopener" title=${T("See what's in this list")} onClick=${e => e.stopPropagation()}><${Ic} i="info"/></a>` : null}
                      <button class="bk-lremove" title=${T("Remove this list from the category")} onClick=${e => { e.stopPropagation(); removeSource(c, i); }}><${Ic} i="x"/></button>
                    </div>`)
                    : html`<div class="bk-empty">${Trich("No lists yet — use *+ Add list* above to add one.")}</div>`}
                  ${!c.predefined ? html`<div class="bk-catfoot"><span class="grow"></span><button class="bk-delcat" title=${T("Delete this custom category")} onClick=${e => { e.stopPropagation(); removeCat(c); }}><${Ic} i="trash"/>${T("Delete category")}</button></div>` : null}
                </div>` : null}
              </div>`; };
            return html`<${Fragment}>
              <div class="lgrid-head" style="margin-top:16px">
                <div class="lg-htitle"><span class="seclabel" style="margin:0">${T("Block categories")}</span><span class="lg-count">${cats.length}</span><span class="faint lg-sub">${T("drop ads, malware, adult, threat IPs — by domain or IP")}</span></div>
                <span class="grow"></span>
                <button class="btn btn-add" onClick=${() => openModal(html`<${NewBlockCatSheet} existingIds=${allIds} onCreate=${createCat}/>`)}><${Ic} i="plus"/>${T("New category")}</button>
              </div>
              <div class="lgrid">${cats.map(bkRow)}</div>
              <div class="lg-legend">
                <div class="lg-leg-row">${Trich("{v1} matched by IP address — works in every mode.", { v1: html`<span class="capb ip">IP</span>` })}</div>
                <div class="lg-leg-row">${Trich("{v1} matched by domain name — needs *{v2}* or *Hybrid-SNI* mode (they fill the block set from DNS). IP-only and Kernel-SNI can't match domains.", { v1: html`<span class="capb host">${T("Host")}</span>`, v2: T("Force-DNS") })}</div>
                <div class="lg-leg-row">${Trich("{v1} a domain list can't enforce on an IP-only or Kernel-SNI node — it's skipped, never pushed. Switch that node to Force-DNS / Hybrid-SNI, or add an IP list.", { v1: html`<span class="bk-nabadge">${T("Not available")}</span>` })}</div>
              </div>
            <//>`;
          })() : null}
        </div>` : null}
        ${section === "turn" ? html`<div class="card">
          <div class="seclabel turnhead" style="margin-top:0">${T("Turn proxies")}<span class="grow"></span>
            <label class="swt" title=${turnEnabledS ? T("Turn proxies are on") : T("Turn proxies are off")}><input type="checkbox" checked=${turnEnabledS} onChange=${e => setTurnEnabledS(e.target.checked)}/><span class="track"></span><span class="knob"></span></label></div>
          ${!turnEnabledS ? html`<p class="hint" style="margin:0 0 12px"><b class="warntext">${T("Turn proxies are off.")}</b> ${T("Creation buttons and the turn-proxy sections are hidden across the panel. Deployed proxies keep running — they're just not shown here.")}</p>`
            : html`<p class="hint" style="margin:0 0 12px">${Trich("Which forks appear in the *{v1}* picker when you add a proxy to a node, and each fork's colour. Unticking one only *hides it from that list* — it never touches proxies you've already deployed. {v2}", { v1: T("Install a fork"), v2: turnForks.size === 0 ? html`*No forks are enabled — the install picker will be empty.*` : null })}</p>`}
          ${html`<${Fragment}>
          <div class=${"cllist" + (turnEnabledS ? "" : " dimmed")}>${turnForksVisible().map(f => { const fcol = pickThemed(forkColors[f.id], f.color, f.colorL); return html`<div class=${"cl-row" + (turnForks.has(f.id) ? "" : " off")} key=${f.id}>
            <${Switch} on=${turnForks.has(f.id)} title=${T("Offer {v1}", { v1: T("{v1} in the install picker", { v1: f.label }) })} onChange=${v => setTurnForks(s => { const n = new Set(s); v ? n.add(f.id) : n.delete(f.id); return n; })}/>
            <${ThemedSwatch} val=${forkColors[f.id]} title=${T("Colour for {v1}", { v1: f.label })} onChange=${nv => setForkColors(c => ({ ...c, [f.id]: nv }))}
              sample=${(c) => html`<span class="tg tg-turn" style=${"--tfc:" + c}>${f.label}</span>`}/>
            <a class=${"tf-name tf-" + f.id} href=${"https://github.com/" + f.owner} target="_blank" rel="noopener" style=${"color:" + fcol} title=${"github.com/" + f.owner}>${f.label}</a>
            <span class="cl-caps" title=${f.kind === "wdtt" ? T("Self-contained WDTT server — owns its own WireGuard interface (not a WG/AWG front)") : forkSupportsAwg(f.id) ? T("Works with WireGuard and AmneziaWG interfaces") : T("{v1} is WireGuard-only — its client can't front an AmneziaWG interface", { v1: f.label })}>
              ${f.kind === "wdtt"
                ? html`<span class="tg tg-wdtt">WDTT</span>`
                : html`<${Fragment}><span class="tg tg-wg">wg</span>${forkSupportsAwg(f.id) ? html`<span class="tg tg-awg">awg</span>` : null}<//>`}
            </span>
            ${(() => {
              const v = forkVersions(f.id); const col = fcol;
              if (!v.length) return html`<span class="tf-ver none">${T("not yet used")}</span>`;
              const nodes = forkNodeStates(f.id); const ut = turnUpdateTarget[f.id]; const latest = (ut && Date.now() < ut.until) ? ut.ver : ((turnCheck[f.id] || {}).latest || null);
              // per-node effective version: a hold shows "Held on <held>", else the running version. The row collapses
              // to ONE label when every node agrees, or "N versions" (detail in the hover bubble) when they differ.
              const perNode = nodes.map(n => { const held = (Store.turnHolds[n.node] || {})[f.id] || ""; return { ...n, held, eff: held || n.version || "" }; });
              const distinct = [...new Set(perNode.map(p => p.eff).filter(Boolean))];
              const allHeld = perNode.length > 0 && perNode.every(p => p.held);
              const bub = html`<span class="tf-verpop">
                ${perNode.map(n => html`<span class="tf-vg-node">
                  <span class="tf-vg-dot" style=${"background:" + (Store.nodeColor(n.node) || "var(--ink)")}></span>
                  <span class="tf-vg-nm">${Store.nodeName(n.node)}</span>
                  <span class=${"tf-vg-ver" + (n.held ? " held" : "")}>${n.held ? html`<${Ic} i="off"/> Held on ${n.held}` : (n.version || "—")}</span>
                  ${n.installing ? html`<span class="tf-vg-st upd">${T("updating…")}</span>` : (n.updatePending && latest && n.version === latest) ? html`<span class="tf-vg-st ok"><${Ic} i="check"/>${T("updated")}</span>` : null}
                </span>`)}
              </span>`;
              if (distinct.length > 1) return html`<span class="tf-verwrap" style=${"--tfc:" + col}><span class="tf-ver">${plural(distinct.length, "version")}</span>${bub}</span>`;
              const ver = distinct[0] || v.join(", ");
              if (allHeld) return html`<span class="tf-verwrap" style=${"--tfc:" + col}><span class="tf-ver held"><${Ic} i="off"/> ${T("Held on {v1}", { v1: ver })}</span>${bub}</span>`;
              return html`<span class="tf-verwrap" style=${"--tfc:" + col}><span class="tf-ver">${ver}</span>${bub}</span>`;
            })()}
            <span class="grow"></span>
            ${(() => { const cs = turnCheck[f.id]; if (!cs || !cs.status) return null;   // update status — right-aligned, just before the repo URL (like Geo data)
              if (cs.status === "checking") return html`<span class="tf-chk"><span class="tf-arrow"><${Ic} i="refresh"/></span> checking…</span>`;
              if (cs.status === "updating") return html`<span class="tf-chk"><span class="tf-arrow"><${Ic} i="refresh"/></span> updating…</span>`;   // i18n-keys
              if (cs.status === "update") return html`<button class="tf-chk upd tf-updbtn" title=${T("Update every deployed {v1} proxy to {v2}", { v1: f.label, v2: cs.latest })} onClick=${() => updateFork(f.id, cs.latest)}><${Ic} i="download"/> update to ${cs.latest}</button>`;
              return html`<span class="tf-chk ok"><${Ic} i="check"/> ${T("up to date")}</span>`; })()}
            <span class="tf-plats">${turnForkPlatforms(f).map(p => html`<span key=${p.os} class="tf-platwrap turnwrap">
              <button type="button" aria-disabled=${p.disabled ? "true" : null}
                class=${"tf-plat" + (p.disabled || p.notOffered ? " off" : ((p.native ? " nat" : " cross") + (p.obf ? "" : " plain") + (p.isCli ? " cli" : "")))}
                onClick=${() => { if (!p.disabled) openServerClients(f.id, p.os); }}><${Ic} i=${"os_" + p.os}/></button>
              <span class="turnbub tf-plbub">
                ${p.notOffered
                  ? html`<span class="tf-plbub-l"><span class="tf-plbub-app">${T("Not offered on {v1} — those users get no card for this server", { v1: p.label })}</span></span>`
                  : p.disabled
                  ? html`<span class="tf-plbub-l"><span class="tf-plbub-app">${T("No {v1} app for {v2} yet", { v1: f.label, v2: p.label })}</span></span>`
                  : html`<${Fragment}><span class="tf-plbub-l">
                      <span class="tf-plbub-app">${p.name}<span class="tf-plbub-by"> by </span><span style=${"color:" + (p.color || turnColor(p.author))}>${p.author}</span></span>
                      ${p.coreFork ? html`<span class="tf-plbub-core">${Trich("with {v1} core", { v1: html`<span style=${"color:" + turnColor(p.coreFork)}>${p.coreFork}</span>` })}</span>` : null}
                    </span>
                    <span class=${"tf-plbub-obf" + (p.obfLabel ? "" : " plain")}>${p.obfLabel || "plain"}</span><//>`}
              </span></span>`)}</span>
            <button class="iconbtn tf-gear" title=${T("Server-flag defaults for {v1} (pre-fill new proxies)", { v1: f.label })} onClick=${() => openServerDefaults(f.id)}><${Ic} i="gear"/></button>
          </div>`; })}</div>
          ${turnEnabledS ? html`<${Fragment}>
          <div class="seclabel" style="margin-top:18px">${T("Auto-update schedule")}</div>
          <p class="hint" style="margin:0 0 10px">${Trich("The panel checks each deployed proxy's fork for a newer release and, if there is one, updates the binary and restarts the proxy automatically. A restart briefly drops that proxy's clients, so pick a *quiet hour*. (The panel stages the update; each node applies it on its next sync.)")}</p>
          <div class="schedrow">
            <div class="field" style="margin:0"><label>${T("How often")}</label>
              <${Dropdown} value=${tuEvery} onChange=${v => setTuEvery(v)} options=${[
                { value: "1", label: T("Every day") }, { value: "2", label: T("Every 2 days") }, { value: "3", label: T("Every 3 days") },
                { value: "7", label: T("Every week") }, { value: "0", label: T("Off — no auto-updates") }]}/></div>
            <div class="field" style="margin:0"><label>${T("At (panel time)")}</label>
              <input type="time" class="timein" value=${tuAt} disabled=${tuEvery === "0"} onInput=${e => setTuAt(e.target.value || "04:00")}/>
              <div class="hint">${tuEvery === "0" ? T("Auto-updates are off — use “Check for updates” below to update manually.") : T("The panel checks at this local time, on the chosen cadence.")}</div></div>
          </div>
          <div class="georefresh"><span class="faint" style="font-size:11px">${T("Check every deployed proxy's fork for a newer release now, and update the ones that are behind")}</span><button class="btn btn-mini" disabled=${Object.values(turnCheck).some(v => v && v.status === "checking")} onClick=${checkTurnUpdates}><span class=${Object.values(turnCheck).some(v => v && v.status === "checking") ? "tf-arrow" : ""}><${Ic} i="refresh"/></span>${T("Check for updates")}</button></div>
          <div class="seclabel" style="margin-top:18px">${T("Client rosters")}</div>
          <p class="hint" style="margin:0 0 8px">${T("Whether any client app's config/link schema changed upstream on GitHub since we curated it — fetches each app's source file and flags drift per app to review.")}</p>
          <div class="georefresh"><span class="faint" style="font-size:11px">${T("Fetch each client app's schema source from GitHub and flag the ones whose upstream changed")}</span><button class="btn btn-mini" onClick=${() => openRosterCheck()}><${Ic} i="refresh"/>${T("Check client rosters")}</button></div>
          <//>` : null}
          <//>`}
          <div class="seclabel" style="margin-top:18px">${T("Fallback VK call link")}</div>
          <p class="hint" style="margin:0 0 8px">${Trich("Used for *unassigned* peers, and as the link the panel bakes in when you generate a config here to *test a connection yourself* before handing it out. Leave blank to emit a *{v1}* placeholder. Assigned users should get their *own* VK link — set it in their profile or QR view before you distribute. *Subscription pages ignore this link* and use only the per-user one.", { v1: "<PASTE VK CALL LINK>" })}</p>
          <input class="vklink-in" value=${vkLinkS} onInput=${e => setVkLinkS(e.target.value)} placeholder=${T("https://vk.com/call/join/…")}/>
          ${turnEnabledS ? html`<${TurnCollectedIps}/>` : null}
        </div>` : null}
        ${section === "geo" ? html`<div class="card">
          <div class="rltabs" style="margin-top:0">
            <div class="rltab-cap">${geoTab === "blocking" ? T("Content filters providers") : T("Routing lists providers")}</div>
            <div class="rltab-group" role="tablist">
              <button role="tab" aria-selected=${geoTab === "routing"} class=${"rltab" + (geoTab === "routing" ? " on" : "")} onClick=${() => setGeoTab("routing")}><${Ic} i="cascade"/>${T("Routing")}</button>
              <button role="tab" aria-selected=${geoTab === "blocking"} class=${"rltab" + (geoTab === "blocking" ? " on" : "")} onClick=${() => setGeoTab("blocking")}><${Ic} i="shield"/>${T("Blocking")}</button>
            </div>
          </div>
          ${geoTab === "routing" ? html`
          <p class="hint" style="margin:0 0 12px">${Trich("*Curated* presets are on by default — recommended, ready-to-route lists maintained by the panel. Turn on any public *provider* below to also search its raw catalog; the panel fetches it so its lists appear in the picker. Disabling a provider hides its lists and *deactivates* anything already routed from it until you re-enable it.")}</p>
          <div class="provlist">${(_provReg.length ? _provReg : []).map(p => { const on = provEnabled[p.id] !== false; return html`<div class=${"provrow bprow" + (on ? "" : " off") + (p.builtin ? " builtin" : "")} key=${p.id}>
            <${Switch} on=${on} title=${on ? (p.builtin ? T("On — presets are selectable") : T("Enabled — its lists are selectable")) : T("Off — its lists are hidden and deactivated on nodes")} onChange=${v => setProvEnabled(m => ({ ...m, [p.id]: v }))}/>
            <${ThemedSwatch} val=${provColors[p.id]} title=${T("{v1} tag colour", { v1: p.label })} onChange=${nv => setProvColors(c => ({ ...c, [p.id]: nv }))}
              sample=${(c) => html`<span class="sw-sample" style=${"--pc:" + c}>${p.label}</span>`}/>
            <div class="bprov-meta">
              <div class="bprov-top">
                <span class="prov-name" style=${"color:" + pickThemed(provColors[p.id], _provColDefault(p.id).dark, _provColDefault(p.id).light)}>${p.label}</span>
                <span class="prov-tiers">${capBadges({ host: (p.tiers || []).includes("host"), ip: (p.tiers || []).includes("ip") })}</span>
                ${p.builtin || p.enabled === false ? null : html`<span class=${"prov-upd" + (p.last_updated ? "" : " never")} title=${p.last_updated ? T("When this provider's data was last pulled to the panel") : T("No list from this provider has been routed yet — nothing pulled")}>${p.last_updated ? html`updated ${ago(p.last_updated)}` : T("never updated")}</span>`}
              </div>
              ${p.desc ? html`<span class="bprov-note">${T(p.desc)}</span>` : null}
            </div>
            <span class="grow"></span>
            ${p.builtin || p.enabled === false ? null
              : (() => { const s = p.status, flashing = provFlash[p.id] > Date.now();
              if (s === "downloading") return html`<span class="prov-st upd"><span class="tf-arrow"><${Ic} i="refresh"/></span> ${T("Downloading…")}</span>`;
              if (s === "updating") return html`<span class="prov-st upd"><span class="tf-arrow"><${Ic} i="refresh"/></span> updating…</span>`;   // i18n-keys
              if (s === "updated") return flashing ? html`<span class="prov-st ok"><${Ic} i="check"/> ${T("updated")}</span>` : null;   // i18n-keys
              if (s === "uptodate") return flashing ? html`<span class="prov-st ok"><${Ic} i="check"/> ${T("up to date")}</span>` : null;
              if (s === "failed" || p.error) return html`<${Fragment}><span class="prov-st err" title=${srvText(p) || ""}><${Ic} i="warn"/> ${p.last_updated ? T("update failed") : T("download failed")}</span><button class="btn btn-mini" style="margin-left:8px" onClick=${() => retryProvider(p.id)}>${T("Retry")}</button></>`;
              return null; })()}
            ${p.builtin ? null : html`<a class="prov-repo" href=${p.url} target="_blank" rel="noopener" title=${T("Open {v1}", { v1: T("{v1} on GitHub", { v1: p.label }) })}>${(p.url || "").replace(/^https?:\/\/github\.com\//, "")}</a>`}
          </div>`; })}${!_provReg.length ? html`<div class="hint">${T("Loading providers…")}</div>` : null}
            <div class=${"provrow bprow" + (customEnabled ? "" : " off")}>
              <${Switch} on=${customEnabled} title=${customEnabled ? T("On — you can create custom lists") : T("Off — the Custom lists section is hidden")} onChange=${v => setCustomEnabled(v)}/>
              <${ThemedSwatch} val=${provColors.custom} title=${T("Custom-list tag colour")} onChange=${nv => setProvColors(c => ({ ...c, custom: nv }))}
                sample=${(c) => html`<span class="sw-sample" style=${"--pc:" + c}>${T("src|Custom")}</span>`}/>
              <div class="bprov-meta">
                <div class="bprov-top"><span class="prov-name" style="color:var(--ink)">${T("Custom lists")}</span></div>
                <span class="bprov-note">${T("Your own IP / domain lists — turn off to hide the Custom lists section in routing.")}</span>
              </div>
            </div>
          </div>` : null}
          ${geoTab === "blocking" ? html`
          <p class="hint" style="margin:0 0 12px">${Trich("The block-list feeds that fill the *Blocking* tab's content categories (ads, malware, adult, and so on). Core feeds are on by default; turn on any extra feed to add its lists to the Blocking picker. Turning one off hides its lists and *deactivates* anything already filtering from it until you re-enable it. Each feed keeps its own tag colour.")}</p>
          ${(() => { const bcp = (Store.blockCatalog || {}).providers || [];
            const bpOn = p => blockProvEdits[p.id] !== undefined ? blockProvEdits[p.id] : (p.enabled !== false);
            return bcp.length ? html`<div class="provlist">${bcp.map(p => { const on = bpOn(p); const pcv = provColors[p.id] || asThemed((ps.provider_colors || {})[p.id], p.color, p.color_l || p.color); return html`<div class=${"provrow bprow" + (on ? "" : " off")} key=${p.id}>
              <${Switch} on=${on} title=${on ? T("On — its lists are selectable in Blocking") : T("Off — its lists are hidden and deactivated on nodes")} onChange=${v => setBlockProvEdits(m => ({ ...m, [p.id]: v }))}/>
              <${ThemedSwatch} val=${pcv} title=${T("{v1} tag colour", { v1: p.label })} onChange=${nv => setProvColors(c => ({ ...c, [p.id]: nv }))}
                sample=${(c) => html`<span class="sw-sample" style=${"--pc:" + c}>${p.label}</span>`}/>
              <div class="bprov-meta">
                <div class="bprov-top"><span class="prov-name" style=${"color:" + pickThemed(pcv, _provColDefault(p.id).dark, _provColDefault(p.id).light)}>${p.label}</span><span class="prov-tiers">${capBadges({ host: p.tier === "host", ip: p.tier === "ip" })}</span></div>
                ${p.note ? html`<span class="bprov-note">${T(p.note)}</span>` : null}
              </div>
              <span class="grow"></span>
              ${p.url ? html`<a class="prov-repo" href=${p.url} target="_blank" rel="noopener" title=${T("Open {v1}", { v1: p.label })}>${(p.url || "").replace(/^https?:\/\/(github\.com|raw\.githubusercontent\.com)\//, "").replace(/^www\./, "")}</a>` : null}
            </div>`; })}</div>` : html`<div class="hint">${T("Loading providers…")}</div>`; })()}` : null}

          <div class="seclabel" style="margin-top:20px">${T("Update schedule")}</div>
          <p class="hint" style="margin:0 0 10px">${Trich("When each node re-fetches its lists. Refreshing briefly reloads the node's match sets, which clients can feel — so schedule it for a *quiet hour*. (A failed fetch retries on the next sync; existing lists keep working meanwhile.)")}</p>
          <div class="schedrow">
            <div class="field" style="margin:0"><label>${T("How often")}</label>
              <${Dropdown} value=${guEvery} onChange=${v => setGuEvery(v)} options=${[
                { value: "1", label: T("Every day") }, { value: "2", label: T("Every 2 days") }, { value: "3", label: T("Every 3 days") },
                { value: "7", label: T("Every week") }, { value: "0", label: T("Continuous (rolling ") + T("{v1}-day TTL)", { v1: ttlD }) }]}/></div>
            <div class="field" style="margin:0"><label>${T("At (node-local time)")}</label>
              <input type="time" class="timein" value=${guAt} disabled=${guEvery === "0"} onInput=${e => setGuAt(e.target.value || "04:00")}/>
              <div class="hint">${guEvery === "0" ? T("Continuous mode ignores the time — nodes refresh whenever a list is older than the TTL.") : T("Nodes update at this local time, on the chosen cadence.")}</div></div>
          </div>
          <div class="georefresh"><span class="faint" style="font-size:11px">${T("Re-fetch every routed list from its provider now (updates the panel; nodes pull the changes on their schedule)")}</span><button class="btn btn-mini" disabled=${geoUpdating} onClick=${updateAllLists}><span class=${geoUpdating ? "tf-arrow" : ""}><${Ic} i="refresh"/></span> ${geoUpdating ? T("Updating…") : T("Update all lists now")}</button></div>
        </div>` : null}
        ${section === "integrations" ? html`<${IntegrationsSettings}/>` : null}
        ${section === "access" ? html`<${AccessTLSCard} onChange=${onAccess}/>` : null}
        ${section === "defaults" ? html`<div class="card">
          <div class="seclabel turnhead" style="margin-top:0">${T("Interface colours")}<span class="grow"></span>
            ${Object.keys(ifaceColorOverrides()).length ? html`<button class="btn btn-mini" onClick=${() => setIfaceColors({ wg: { ...IFACE_COLOR_DEFAULTS.wg }, awg: { ...IFACE_COLOR_DEFAULTS.awg }, wdtt: { ...IFACE_COLOR_DEFAULTS.wdtt } })}><${Ic} i="refresh"/>${T("Reset")}</button>` : null}</div>
          <p class="hint" style="margin:0 0 12px">${T("The colour each protocol's tags take everywhere — a value per theme. Hover a swatch to preview it.")}</p>
          <div class="palrow">
            <span class="palcell sw1"><${ThemedSwatch} val=${ifaceColors.wg} title=WireGuard onChange=${nv => setIfaceColors(c => ({ ...c, wg: nv }))}
              sample=${(c) => html`<span class="tg" style=${"background:color-mix(in srgb," + c + " 15%,transparent);color:" + c}>wg</span>`}/><span class="pallbl">WireGuard</span></span>
            <span class="palcell sw1"><${ThemedSwatch} val=${ifaceColors.awg} title=AmneziaWG onChange=${nv => setIfaceColors(c => ({ ...c, awg: nv }))}
              sample=${(c) => html`<span class="tg" style=${"background:color-mix(in srgb," + c + " 15%,transparent);color:" + c}>awg</span>`}/><span class="pallbl">AmneziaWG</span></span>
            <span class="palcell sw1"><${ThemedSwatch} val=${ifaceColors.wdtt} title=WDTT onChange=${nv => setIfaceColors(c => ({ ...c, wdtt: nv }))}
              sample=${(c) => html`<span class="tg" style=${"background:color-mix(in srgb," + c + " 15%,transparent);color:" + c}>WDTT</span>`}/><span class="pallbl">WDTT</span></span>
          </div>
          <div class="seclabel">${T("Peer health detection")}</div>
          <p class="hint" style="margin:0 0 10px">${Trich("Which failure conditions the panel flags on a peer. All on by default — untick one to stop it showing that status (the peer just reads online / ready instead). Both appear in {v1}.", { v1: html`<span class="b-faulty" style="padding:1px 6px;border-radius:6px">${T("val|orange")}</span>` })}</p>
          <div class="condrow"><${Switch} on=${statusConds.blocked} onChange=${v => setStatusConds(c => ({ ...c, blocked: v }))}/>
            <span class="cond-b"><span class="badge b-blocked ic"><${Ic} i="warn"/>${T("tag|restricted")}</span></span>
            <span class="cond-t">${T("Endpoint is reaching the server, but the handshake never completes (likely DPI / MTU / wrong Wireguard or AmneziaWG params).")}</span></div>
          <div class="condrow"><${Switch} on=${statusConds.faulty} onChange=${v => setStatusConds(c => ({ ...c, faulty: v }))}/>
            <span class="cond-b"><span class="badge b-faulty ic"><${Ic} i="warn"/>${T("tag|faulty")}</span></span>
            <span class="cond-t">${T("Handshake is up but no inbound data has flowed for a while — a one-way block / DPI on the return path. (This can't tell a genuinely-stuck peer from a simply-idle one, so turn it off if idle peers bother you.)")}</span></div>
          <div class="seclabel">${T("Defaults")}</div>
          <p class="hint" style="margin:0 0 12px">${T("Applied when creating a new interface — you can still override per interface.")}</p>
          <div class="field"><label>DNS</label><input value=${dns} onInput=${e => setDns(e.target.value)} placeholder=${T("https://8.8.8.8/dns-query, 1.1.1.1")}/><div class="hint">${T("Comma-separated")}</div></div>
          <div class="row2"><div class="field"><label>MTU</label><input value=${mtu} onInput=${e => setMtu(e.target.value)} placeholder="1280"/></div>
            <div class="field"><label>${T("Persistent keepalive (s)")}</label><input value=${ka} onInput=${e => setKa(e.target.value)} placeholder="25"/></div></div>
          <div class="seclabel">${T("Key escrow & recovery")}</div>
          <p class="hint" style="margin:0 0 10px">${T("Backup each server's interface key so a wiped / rebuilt node restores its interfaces with their original identities.")}</p>
          <${InterfaceKeyEscrow} value=${ivkEscrow} onChange=${setIvkEscrow} vaultExists=${ivkVaultExists}/>
        </div>` : null}
        ${section === "defaults" ? html`<${IgnoredIfacesCard}/>` : null}
        ${section === "security" ? html`<div class="card">
          <div class="seclabel" style="margin-top:0">${T("Authentication")}</div>
          <p class="hint" style="margin:0 0 14px">${Trich("Change the panel username and password — applied on *{v1}*. Changing either takes effect immediately and you'll be asked to sign in again. Changing the password also re-keys your *Encryption Vault* in place, so stored configs and subscription links keep working (no re-issue).", { v1: T("Save") })}</p>
          ${!secAuth ? html`<div class="formmsg err">${T("This panel has no login configured — changes are disabled.")}</div>` : (secErr() ? html`<div class="formmsg err">${secErr()}</div>` : null)}
          <div class="field"><label>${T("Username")}</label><input value=${secUser} disabled=${!secAuth} onInput=${e => setSecUser(e.target.value)} autocomplete="username"/></div>
          <div class="field"><label>${T("Current password")}</label><input type="password" value=${secCur} disabled=${!secAuth} onInput=${e => setSecCur(e.target.value)} autocomplete="current-password" placeholder=${T("required to confirm a change")}/></div>
          <div class="row2"><div class="field"><label>${T("New password")}</label><input type="password" value=${secNp} disabled=${!secAuth} onInput=${e => setSecNp(e.target.value)} autocomplete="new-password" placeholder=${T("leave blank to keep current")}/></div>
            <div class="field"><label>${T("Confirm new password")}</label><input type="password" value=${secNp2} disabled=${!secAuth} onInput=${e => setSecNp2(e.target.value)} autocomplete="new-password"/></div></div>
          <${TwoFactorCard} enabled=${sec2fa} disabled=${!secAuth} onChange=${setSec2fa}/>
        </div>` : null}
        ${section === "configs" ? html`<div class="card">
          <div class="seclabel" style="margin-top:0">${T("Client configs")}</div>
          <div class="field"><label>${T("Store client configs")}</label>
            <${Dropdown} value=${sc} onChange=${v => setSc(v)} options=${[
              { value: "encrypted", label: T("Keep encrypted configs — QRs re-viewable anytime") },
              { value: "off", label: T("Keep nothing — QR shown once") }]}/>
            <div class=${"hint" + (sc === "off" ? " err" : "")}>${sc === "off" ? T("Live tunnels and creation-time QRs are unaffected, but you won't be able to re-view a peer's QR/config later — you'd rotate its key and re-distribute.") : T("Client configs are stored encrypted at rest (the server can't read the private keys) so a peer's QR stays re-viewable — you unlock it with your encryption key below. Requires the encryption key.")}</div></div>
          ${sc === "off" && subsOn ? html`<div class="hint warn" style="margin-top:10px"><${Ic} i="warn"/> ${Trich("Subscriptions are on and need encrypted config storage. Turn {v1} off first, or keep encrypted storage on — saving this as-is will be rejected.", { v1: html`<button class="linkbtn" onClick=${() => setSection("subs")}>${T("Subscriptions")}</button>` })}</div>` : null}
          <div class="seclabel">${T("Encryption")}</div>
          <p class="hint" style="margin:0 0 8px">${T("An encryption key held only by you (independent of your login password) protects stored client configs so the server can't read the private keys, and unlocks a peer's QR any time you're signed in. The same key powers subscriptions when you turn them on.")}</p>
          <${SubVaultCard}/>
          <${ConfigMigrationCard}/>
        </div>` : null}
        ${section === "subs" ? html`<div class="card">
          <div class="seclabel" style="margin-top:0">${T("Subscriptions")}</div>
          <p class="hint" style="margin:0 0 12px">${Trich("A shareable, themed, mobile page per user showing their QRs. The page's private keys ride in the URL *fragment* and are never sent to the panel — nothing readable is stored on the server. Treat each user's URL as a credential (whoever holds it holds that user's configs). A separate *swg-sub* service serves the page; configure it here and install it on the panel host.")}</p>
          <div class="field"><label>${T("Enable subscriptions")}</label>
            <${Dropdown} value=${subsOn ? "on" : "off"} disabled=${sc === "off"} onChange=${v => setSubsOn(v === "on")} options=${[
              { value: "off", label: T("Off — the subscription page is blocked entirely") },
              { value: "on", label: T("On — per-user subscription URLs are served") }]}/>
            ${sc === "off"
              ? html`<div class="hint warn">${Trich("Subscriptions serve the encrypted config blobs — turn on *Keep encrypted configs* in {v1} first.", { v1: html`<button class="linkbtn" onClick=${() => setSection("configs")}>${T("Client configs")}</button>` })}</div>`
              : html`<div class="hint">${T("Off returns 404 for every subscription URL, regardless of the rest.")}</div>`}</div>
          <div class="field"><label class="ivk-esc-row toggle-row"><${Switch} on=${autoGen} disabled=${!subsOn} onChange=${setAutoGen}/>
            <span>${T("Auto-generate subscription links for new users")}</span></label>
            <div class="hint">${T("When you create a user, mint their subscription link automatically, in the background (user creation stays instant). Needs the encryption key unlocked at that moment; otherwise the link is created the next time you open that user with the key unlocked.")}</div></div>
          <div class="seclabel">${T("Access expiry")}</div>
          <p class="hint" style="margin:0 0 12px">${Trich("A subscription or peer with an expiry date shows an orange *about to expire* warning this many days ahead.")}</p>
          <div class="field" style="max-width:340px"><label>${T("Warn before expiry (days)")}</label><input type="text" inputmode="numeric" value=${warnDays} onDblClick=${e => e.target.select()} onInput=${e => { let v = e.target.value.replace(/[^0-9]/g, ""); if (+v > 365) v = "365"; setWarnDays(v); }} placeholder=${T("Default: 3 (0 = warn only once expired)")}/></div>
          <div class="seclabel">${T("Address & certificate")}</div>
          <div class="subaddr">
            <div class="subaddr-row"><span class="subaddr-k">${T("Public URL")}</span><span class="subaddr-v mono">${subBaseUrl() || html`<span class="faint">${T("Not set")}</span>`}</span></div>
            <div class="subaddr-row"><span class="subaddr-k">${T("Listen")}</span><span class="subaddr-v mono">${(((ps.access || {}).sub || {}).host || "0.0.0.0")}:${(((ps.access || {}).sub || {}).port || 8444)}</span></div>
            <div class="subaddr-row"><span class="subaddr-k">${T("Certificate")}</span><span class="subaddr-v mono">${(TLS_MODE_OPTS().find(o => o.value === (((ps.access || {}).tls || {}).mode || "")) || {}).label || "—"}</span></div>
          </div>
          <div class="hint" style="margin:6px 0 0">${Trich("The subscription page's URL, listen address and certificate are configured in {v1}.", { v1: html`<button class="linkbtn" onClick=${() => setSection("access")}>${T("Panel URL")}</button>` })}</div>
          <div class="seclabel">${T("Languages")}</div>
          <div class="field"><label>${T("Offered on the subscription page")}</label>
            <div class="sublangs">${SUB_LANG_LIST.map(([id, name]) => html`<div class=${"sublang" + (subLangs.includes(id) ? " on" : "")} key=${id}>
              <label class="sublang-en"><input type="checkbox" checked=${subLangs.includes(id)} onChange=${e => toggleSubLang(id, e.target.checked)}/><span>${name}</span></label>
              <button class=${"sublang-def" + (subLangDef === id ? " on" : "")} disabled=${!subLangs.includes(id)} onClick=${() => setSubLangDef(id)} title=${T("Load this language by default")}>${subLangDef === id ? T("state|Default") : T("Set default")}</button>
            </div>`)}</div>
            <div class="hint">${Trich("Which languages the page offers. With just one enabled, it hides the selector and loads that language; the *default* is what loads first when several are offered.")}</div></div>
          <div class="seclabel">${T("Encryption")}</div>
          <p class="hint" style="margin:0">${Trich("Subscriptions reuse the same encryption key that protects your stored client configs — set it up under {v1}. No separate key.", { v1: html`<button class="linkbtn" onClick=${() => setSection("configs")}>${T("Client configs → Encryption")}</button>` })}</p>
        </div>` : null}
        ${section === "display" ? html`<div class="card">
          <div class="seclabel turnhead" style="margin-top:0">${T("Interface theme")}<span class="grow"></span>
            ${(themeColorS.toLowerCase() !== THEME_COLOR_DEFAULT.toLowerCase() || themeColorLightS.toLowerCase() !== THEME_COLOR_LIGHT_DEFAULT.toLowerCase()) ? html`<button class="btn btn-mini" onClick=${() => { setThemeColorS(THEME_COLOR_DEFAULT); setThemeColorLightS(THEME_COLOR_LIGHT_DEFAULT); }}><${Ic} i="refresh"/>${T("Reset")}</button>` : null}</div>
          <p class="hint" style="margin:0 0 12px">${Trich("The panel's accent colour — button borders, checkboxes, focus rings, the throughput \"down\" series and the live / hour / day / week / month chart tabs all follow it. A separate colour for each mode; switch *Light / Dark / Auto* from the sun / moon button in the header.")}</p>
          <div class="palrow">
            <${ThemedSwatch} val=${themeVal} title=${T("Interface theme")} onChange=${nv => { setThemeColorS(clampBrand(nv.dark, false)); setThemeColorLightS(clampBrand(nv.light, true)); }}
              sample=${(c) => html`<span class="tsw-theme"><span class="tsw-btn" style=${"color:" + c}>${T("sample|Button")}</span><span class="tsw-chip" style=${"color:" + c}></span></span>`}/>
          </div>
          <div class="seclabel">${T("Display")}</div>
          <div class="field"><label>${T("Throughput perspective")}</label>
            <${Dropdown} value=${tput} onChange=${v => setTput(v)} options=${[
              { value: "nodes", label: T("Nodes — what the node downloads / uploads") },
              { value: "peers", label: T("Peers — what the client downloads / uploads") }]}/>
            <div class="hint">${T("Which way ↓/↑ are labelled across the panel. Same numbers, swapped arrows.")}</div></div>
          <div class="seclabel">${T("Status timing")}</div>
          <p class="hint" style="margin:0 0 12px">${T("How long the panel waits before treating things as stale — in seconds.")}</p>
          <div class="row2"><div class="field"><label>${T("Node stale after (s)")}</label><input value=${staleS} onInput=${e => setStaleS(e.target.value)} placeholder="30"/><div class="hint">${T("No sync for this long → the node shows stale.")}</div></div>
            <div class="field"><label>${T("Peer grace window (s)")}</label><input value=${graceS} onInput=${e => setGraceS(e.target.value)} placeholder="60"/><div class="hint">${T("A peer stays \"online\" this long after its last handshake.")}</div></div></div>
          <div class="seclabel">${T("Overview lists")}</div>
          <p class="hint" style="margin:0 0 12px">${T("How many rows the Overview's ranked lists show (1–50).")}</p>
          <div class="row2"><div class="field"><label>${T("Top talkers")}</label><input type="text" inputmode="numeric" value=${topTalk} onDblClick=${e => e.target.select()} onInput=${e => { let v = e.target.value.replace(/[^0-9]/g, ""); if (+v > 50) v = "50"; setTopTalk(v); }} placeholder="10"/><div class="hint">${T("Number of peers in the Top talkers list (max 50).")}</div></div>
            <div class="field"><label>${T("Top destinations")}</label><input type="text" inputmode="numeric" value=${topDest} onDblClick=${e => e.target.select()} onInput=${e => { let v = e.target.value.replace(/[^0-9]/g, ""); if (+v > 50) v = "50"; setTopDest(v); }} placeholder="10"/><div class="hint">${T("Number of categories in the Top destinations list (max 50).")}</div></div></div>
        </div>` : null}
        ${/* Mesh and egress are one topic — this node's addressing: how other nodes reach it, and what source
              IP its traffic leaves with. They were two rail entries with identical chrome (both per-node, both
              a node picker) and egress was two fields. They also interact: cascade sends a node's traffic out
              through ANOTHER node, and that path rides the mesh. One section, two sub-blocks. */""}
        ${section === "mesh" ? html`<div class="card">
          ${nodeRec ? html`<${Fragment}>
            <div class="seclabel" style="margin-top:0">${T("{v1} — mesh", { v1: nodeRec.name })}</div>
            <${NodeMeshForm} node=${nodeRec} vals=${nodeEdits[selNode]} set=${p => setNV(selNode, p)}/>
            <div class="seclabel">${T("{v1} — egress", { v1: nodeRec.name })}</div>
            <${NodeEgressForm} node=${nodeRec} vals=${nodeEdits[selNode]} set=${p => setNV(selNode, p)}/>
          <//>`
            : html`<p class="hint" style="margin:0">${T("No nodes yet — enroll a node to configure its mesh and egress.")}</p>`}
        </div>` : null}
        <div class="setfoot">
          ${section === "access"
            ? null   /* access status (incl. "applying, be patient") is consolidated into the card's top banner, scrolled into view on Save */
            : (Date.now() < saved ? html`<span class="savedflash"><${Ic} i="check"/> ${T("All settings saved")}</span>` : null)}
          <span class="grow"></span>
          <button class="btn btn-ghost" onClick=${leaveSettings}>${T("Back")}</button>
          ${section === "access"
            ? html`<button class="btn btn-primary" disabled=${accessRef.current.busy || !accessRef.current.dirty} title=${!accessRef.current.dirty ? T("No changes to save") : ""} onClick=${() => accessRef.current.run()}>${accessRef.current.busy ? T("Saving…") : T("Save")}</button>`
            : html`<button class="btn btn-primary" disabled=${!!secErr() || !anyDirty} title=${secErr() || (!anyDirty ? T("No changes to save") : "")} onClick=${confirmSave}>${T("Save")}</button>`}</div>
      </div>
    </div>
  </div>`;
}

export function CustomListSheet({ list, onSave, onClose }) {
  const [title, setTitle] = useState(list?.title || "");
  const [targets, setTargets] = useState(list ? (list.targets ?? [...(list.domains || []), ...(list.cidrs || [])].join(", ")) : "");
  const toks = splitTargets(targets), bad = invalidTargets(targets);   // same token validation as the interface smart-rule editor
  const err = !toks.length ? T("add at least one IP or domain")
    : bad.length ? T("not a valid IP, CIDR or domain: {v1}", { v1: bad.slice(0, 4).join(", ") + (bad.length > 4 ? "…" : "") }) : null;
  // The stored default stays English: this is roster DATA, shared by every operator and read back by the
  // nodes, so it must not depend on which language the person who created the list happened to be using.
  // Display translates it (see the delete prompt) — storage does not.
  const save = () => { if (err) return; onSave({ ...(list || { _rid: newRid() }), title: title.trim() || "Untitled list", targets }); onClose(); };   // i18n-keys
  const foot = html`<span class="grow"></span><button class="btn btn-ghost" onClick=${onClose}>${T("Cancel")}</button><button class="btn btn-primary" disabled=${!!err} title=${err || ""} onClick=${save}>${list ? T("Save") : T("Add")}</button>`;
  return html`<${Sheet} title=${list ? T("Edit list") : T("New list")} width=${520} onClose=${onClose} foot=${foot}>
    <div class="field"><label>${T("Title")}</label><input value=${title} onInput=${e => setTitle(e.target.value)} placeholder=${T("e.g. Streaming")}/></div>
    <div class="field"><label>${T("IPs / domains / AS numbers")}</label>
      <textarea class="rrdoms" rows="1" spellcheck="false" placeholder=${T("comma-separated — spotify.com, 1.2.3.0/24, AS62041")} value=${targets} onInput=${e => { autoGrow(e.target); setTargets(e.target.value); }} ref=${el => autoGrow(el)}/>
      <${AsnHint} targets=${targets}/>
      ${err ? html`<div class="rrlint" style="margin-top:5px">${err}</div>` : html`<div class="hint">${Trich("Domains match their subdomains too; IPs / CIDRs directly; an *AS number* (e.g. AS62041) resolves to that provider's IP ranges.")}</div>`}</div>
  <//>`;
}

// Per-node mesh overrides, edited in Panel settings → System mesh (keyed by node, so it re-inits on badge switch)
export function NodeMeshForm({ node, vals, set }) {
  const rsv = (Store.panelSettings || {}).reserved || {};
  const dSub = rsv.mesh_subnet || "10.255.0.0/16", dPort = String(rsv.mesh_port_base || 9999), dPfx = rsv.iface_prefix || "swg_";
  const v = vals || {};
  return html`<div>
    <p class="hint" style="margin:0 0 12px">${Trich("Overrides for *{v1}* — blank inherits the default. Changing the subnet, prefix, or AWG re-provisions this node's links on Save (it briefly drops off the mesh while peers reconnect with the new config).", { v1: node.name })}</p>
    <div class="field"><label>${T("Mesh Ingress IP")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— the address peers dial to reach this node")}</span></label>
      <${NodeIpPick} ips=${node.ips || []} value=${v.endpoint_host || ""} onChange=${ip => set({ endpoint_host: ip })} auto=${T("Auto (public IP)")}/></div>
    <div class="row2"><div class="field"><label>${T("Mesh subnet")}</label><input value=${v.mesh_subnet || ""} onInput=${e => set({ mesh_subnet: e.target.value })} placeholder=${dSub}/></div>
      <div class="field"><label>${T("Mesh port")}</label><input value=${v.mesh_port || ""} onInput=${e => set({ mesh_port: e.target.value })} placeholder=${dPort}/></div></div>
    <div class="field"><label>${T("Interface name prefix")}</label><input value=${v.mesh_prefix || ""} onInput=${e => set({ mesh_prefix: e.target.value })} placeholder=${dPfx}/></div>
    ${(() => {
      const isSet = AWG_KEYS.some(k => String((v.mesh_awg || {})[k] ?? "").trim() !== "");
      return html`<div style="margin-top:6px"><button type="button" class="advtoggle" onClick=${e => { const d = e.currentTarget.nextElementSibling; d.style.display = d.style.display === "none" ? "" : "none"; }}><span class="advcaret">▸</span> ${T("This node's mesh AWG params")}${isSet ? "" : html` <span class="faint" style="font-weight:400">${T("(auto)")}</span>`}</button>
        <div style="display:none;margin-top:8px">
          <${AwgGrid} value=${v.mesh_awg || {}} onChange=${a => set({ mesh_awg: a })}/>
          <div class="hint" style="margin:8px 0 0">${Trich("Obfuscation for the mesh links that terminate on *{v1}* — any node connecting to it adopts these and reconnects on Save. Blank = auto (a fresh set per link).", { v1: node.name })}</div>
          <div style="margin-top:12px;display:flex;gap:8px;justify-content:flex-end"><button type="button" class="btn btn-mini" onClick=${() => set({ mesh_awg: genAwg() })}><${Ic} i="refresh"/>${T("Generate a set")}</button>${isSet ? html`<button type="button" class="btn btn-mini" onClick=${() => set({ mesh_awg: {} })}>${T("Clear (auto)")}</button>` : null}</div>
        </div></div>`;
    })()}
  </div>`;
}

// Per-node egress IP roles, edited in Panel settings → Nodes egress (copied from node settings). Controlled by the parent.
export function NodeEgressForm({ node, vals, set }) {
  const ips = node.ips || []; const v = vals || {};
  return html`<div>
    <p class="hint" style="margin:0 0 12px">${Trich("Which of *{v1}*'s IPs it uses for each outbound role.", { v1: node.name })}</p>
    <div class="field"><label>${T("Default egress IP")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— direct internet exit")}</span></label>
      <${NodeIpPick} ips=${ips} value=${v.default_egress_ip || ""} onChange=${ip => set({ default_egress_ip: ip })} auto=${T("Auto (MASQUERADE)")}/></div>
    <div class="field"><label>${T("Panel egress connection IP")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— source to reach the panel")}</span></label>
      <${NodeIpPick} ips=${ips} value=${v.panel_ip || ""} onChange=${ip => set({ panel_ip: ip })} auto=${T("Auto (default route)")}/></div>
  </div>`;
}

// Account form as a modal (opened from the header user icon).

// ═════════════════════════ MODALS / SHEETS ═════════════════════════
// Universal dialog behaviours live here so every sheet gets them for free (no per-sheet code):
//  • autofocus the first field on open
//  • Enter submits (clicks the primary button) unless you're in a textarea
//  • Esc / backdrop closes — but if any field changed, it warns before discarding
//  • Tab is trapped within the dialog
// Dirtiness is detected by snapshotting field values on open and comparing live, so it works
// regardless of which inputs a given sheet renders.
// `onClose` is the single dismiss target for EVERY exit path — ✕, Esc, overlay-click, the discard
// confirm. Openers pass the place to return to (e.g. reopen the peer view); default just closes.
// Cancel/Save buttons in a sheet's foot should call the same target so all paths land identically.






// Self-contained: setup → scan → verify → recovery codes → enabled/disable.
export function TwoFactorCard({ enabled, disabled, onChange }) {
  const [stage, setStage] = useState("idle");     // idle | setup | recovery | disabling
  const [setup, setSetup] = useState(null);        // {secret, otpauth}
  const [qr, setQr] = useState("");
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState([]);
  const [disPw, setDisPw] = useState(""); const [disCode, setDisCode] = useState("");
  const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const reset = () => { setStage("idle"); setSetup(null); setQr(""); setCode(""); setErr(""); setDisPw(""); setDisCode(""); };
  const beginSetup = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api.twofaSetup();
      if (!r || !r.ok) { setErr(srvText(r) || T("Couldn't start setup.")); setBusy(false); return; }
      setSetup(r.data); setStage("setup");
      try { setQr(await qrDataURL(r.data.otpauth, 200)); } catch (_) { setQr(""); }
    } catch (_) { setErr(T("Couldn't reach the panel.")); }
    setBusy(false);
  };
  const doEnable = async () => {
    if (busy) return; setBusy(true); setErr("");
    try {
      const r = await api.twofaEnable(code.trim());
      if (!r || !r.ok) { setErr(srvText(r) || T("That code isn't valid — try the current one.")); setBusy(false); return; }
      setRecovery((r.data && r.data.recovery) || []); setStage("recovery"); setCode(""); onChange && onChange(true);
    } catch (_) { setErr(T("Couldn't reach the panel.")); }
    setBusy(false);
  };
  const doDisable = async () => {
    if (busy) return; setBusy(true); setErr("");
    try {
      const r = await api.twofaDisable({ current_password: disPw, code: disCode.trim() });
      if (!r || !r.ok) { setErr(srvText(r) || T("Couldn't disable — check your password and code.")); setBusy(false); return; }
      reset(); onChange && onChange(false); toast(T("Two-factor authentication disabled."), "ok");
    } catch (_) { setErr(T("Couldn't reach the panel.")); }
    setBusy(false);
  };
  const copyRecovery = () => { try { navigator.clipboard.writeText(recovery.join("\n")); toast(T("Recovery codes copied."), "ok"); } catch (_) {} };

  // A SECTION of the Authentication card, not a card of its own — so the pane reads as one settings area with
  // two headings, like Access & TLS. No margin-top:0 here: this is the second section and wants the gap.
  return html`<${Fragment}>
    <div class="seclabel">${T("Two-factor authentication")}
      ${enabled && stage === "idle" ? html`<span class="grow"></span><span class="tg tg-ok">${T("state|On")}</span>` : null}</div>
    ${err ? html`<div class="formmsg err">${err}</div>` : null}
    ${!enabled && stage === "idle" ? html`
      <p class="hint" style="margin:0 0 12px">${T("Add a second step at sign-in using an authenticator app (Google Authenticator, Authy, 1Password…).")} ${disabled ? html`<b class="warntext">${T("Configure a panel login first.")}</b>` : null}</p>
      <button class="btn btn-primary" disabled=${disabled || busy} onClick=${beginSetup}>${busy ? "Starting…" : T("Set up two-factor")}</button>
    ` : null}
    ${enabled && stage === "idle" ? html`
      <p class="hint" style="margin:0 0 12px">${T("Sign-in requires a code from your authenticator app. Keep your recovery codes somewhere safe in case you lose the device.")}</p>
      <button class="btn btn-danger" onClick=${() => { reset(); setStage("disabling"); }}>${T("Disable two-factor")}</button>
    ` : null}
    ${stage === "setup" ? html`
      <p class="hint" style="margin:0 0 12px">${T("Scan this with your authenticator app, then enter the 6-digit code it shows to confirm.")}</p>
      <div class="twofa-setup">
        ${qr ? html`<img class="twofa-qr" src=${qr} alt=${T("TOTP QR code")} width="200" height="200"/>` : html`<div class="twofa-qr empty">${T("QR unavailable")}</div>`}
        <div class="twofa-manual">
          <label>${T("Can't scan? Enter this key manually")}</label>
          <code class="twofa-secret">${setup && setup.secret}</code>
          <div class="field" style="margin-top:12px"><label>${T("Code from the app")}</label>
            <input autofocus value=${code} onInput=${e => setCode(e.target.value)} inputmode="text" autocomplete="one-time-code" placeholder="123 456"/></div>
          <div class="btnrow" style="margin-top:8px">
            <button class="btn btn-primary" disabled=${busy || code.trim().length < 6} onClick=${doEnable}>${busy ? T("Verifying…") : T("Verify & enable")}</button>
            <button class="btn btn-ghost" disabled=${busy} onClick=${reset}>${T("Cancel")}</button>
          </div>
        </div>
      </div>
    ` : null}
    ${stage === "recovery" ? html`
      <p class="hint" style="margin:0 0 12px">${Trich("*Two-factor is on.* Save these recovery codes now — each works once if you lose your authenticator. *They won't be shown again.*")}</p>
      <div class="twofa-codes">${recovery.map(c => html`<code key=${c}>${c}</code>`)}</div>
      <div class="btnrow" style="margin-top:12px">
        <button class="btn btn-ghost" onClick=${copyRecovery}><${Ic} i="copy"/>${T("Copy codes")}</button>
        <button class="btn btn-primary" onClick=${reset}>${T("Done")}</button>
      </div>
    ` : null}
    ${stage === "disabling" ? html`
      <p class="hint" style="margin:0 0 12px">${T("Confirm with your password and a current code to turn two-factor off.")}</p>
      <div class="field"><label>${T("Current password")}</label><input type="password" value=${disPw} onInput=${e => setDisPw(e.target.value)} autocomplete="current-password"/></div>
      <div class="field"><label>${T("Authentication code (or recovery code)")}</label><input value=${disCode} onInput=${e => setDisCode(e.target.value)} autocomplete="one-time-code" placeholder="123 456"/></div>
      <div class="btnrow" style="margin-top:8px">
        <button class="btn btn-danger" disabled=${busy || !disPw || !disCode.trim()} onClick=${doDisable}>${busy ? T("Disabling…") : T("Disable two-factor")}</button>
        <button class="btn btn-ghost" disabled=${busy} onClick=${reset}>${T("Cancel")}</button>
      </div>
    ` : null}
  <//>`;
}
