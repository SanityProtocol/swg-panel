/* store.js — the data spine: the API client, the Store, and the reactive bus.
 *
 * LAYER 1 (see docs/APP-JS-SPLIT-PLAN.md). Imports util + theme and NOTHING above itself: every screen
 * imports the Store, so if the Store imported a screen the graph would cycle.
 *
 * `hooks` is how it stays that way. Store.apply() has to trigger six pieces of work that live in higher
 * layers — repaint the theme, accumulate the dashboard's trend series, raise the service-issue modal,
 * finish a ghost rekey, and consult the encryption vault. Rather than importing upward, each is a NAMED
 * slot the owning module fills in. Named rather than a generic list because they fire at three different
 * points of apply() and the ORDER is load-bearing.
 *
 * Every slot is scaffolding with a known end: when the module that owns a callback is extracted, its
 * assignment moves there, and the slot can go away once nothing above the Store needs to be called back.
 *
 * A 401 is the same shape of problem — the fetch layer must not import the login screen — so the handler
 * is injected too. The default THROWS, matching require401's contract, so an unwired build fails loudly
 * rather than treating an expired session as an empty response.
 */

import { url } from "./util.js";
import { T, lang } from "./i18n.js";
import { pickThemed, NODE_COLOR_DEFAULT } from "./theme.js";
import { reconcile } from "../reconcile.js";
import { useState, useEffect } from "preact/hooks";

export const hooks = {
  themeColors: null,      // applyThemeColors  — re-inject the accent + per-kind colours
  forkColors: null,       // applyForkColors   — turn-fork tints
  dashTick: null,         // recordDashTick    — dashboard live trend series
  alertServices: null,    // maybeAlertServices— critical panel-service modal
  rekeyGhosts: null,      // maybeRekeyGhosts  — phase 2 of a ghost recreate
  vaultKeyCached: null,   // subSKCached       — is the encryption vault unlocked this session?
  vaultAutoHeal: null,    // subAutoHeal       — re-issue blobs after an unlock
  ifaceKeyAutoRestore: null,  // ifaceKeyAutoRestore — put a migrated interface's escrowed key back (T-22)
  escrowAutoVerify: null,     // escrowAutoVerify — prove an unstamped escrow blob opens, which only the browser can
};

let _on401 = () => { throw new Error("unauthorized"); };   // i18n-keys: a control-flow sentinel, never displayed
export const setUnauthorizedHandler = fn => { _on401 = fn; };

// ───────────────────────── api ─────────────────────────
// Every request has a ceiling so a wedged/overloaded panel rejects instead of hanging a modal open forever (a save
// modal used to await a dead request with no exit). 90s is generous — a save's HTTP round-trip returns once state is
// written; the node reconcile that "takes a minute" happens asynchronously on the node, not in this request.
export const REQ_TIMEOUT = 90000;
/* Every request carries the UI language. The panel does not translate anything itself — but a few answers
   are fetched from OUTSIDE it (the changelog lives in the repo, in one file per language), and the server
   is the one holding the outbound connection. One header here beats a query parameter on each endpoint:
   it applies to calls that already exist, and it cannot be forgotten by the next endpoint someone adds. */
async function _fetch(u, opts) {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), REQ_TIMEOUT);
  const o = { ...(opts || {}), signal: ac.signal, headers: { ...((opts || {}).headers || {}), "X-SWG-Lang": lang() } };
  try { return await fetch(u, o); }
  catch (e) { if (e && e.name === "AbortError") throw new Error(T("the panel didn't respond in time")); throw e; }
  finally { clearTimeout(t); }
}
export const api = {
  async get(p) { const r = await _fetch(url(p)); if (r.status === 401) return _on401(); return r.json(); },
  async post(p, b) { const r = await _fetch(url(p), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) }); if (r.status === 401 && !/\/api\/login$/.test(p)) return _on401(); return r.json(); },
  login(b) { return this.post("/api/login", b); },
  logout() { return this.post("/api/logout", {}); },
  state() { return this.get("/api/state"); },
  events(limit) { return this.get("/api/events?limit=" + (limit || 15)); },
  eventDelete(eid) { return this.post("/api/events/delete", { eid }); },
  eventsClear() { return this.post("/api/events/clear", {}); },
  nodeHistory(node, range) { return this.get("/api/node-history?node=" + encodeURIComponent(node) + "&range=" + encodeURIComponent(range)); },
  meshHistory(range) { return this.get("/api/mesh-history?range=" + encodeURIComponent(range)); },
  categoryHistory(range) { return this.get("/api/category-history?range=" + encodeURIComponent(range)); },
  turnHistory(range) { return this.get("/api/turn-history?range=" + encodeURIComponent(range)); },
  peerHistory(range) { return this.get("/api/peer-history?range=" + encodeURIComponent(range)); },
  blockStats(range) { return this.get("/api/block-stats?range=" + encodeURIComponent(range)); },
  // DISTINCT peers/users seen online over a range — set-union of per-bucket presence bitmaps, never a mean
  // and never a traffic proxy (so an idle-but-connected peer counts). One call feeds the bars, the node
  // cards and the doughnuts' "online" figure, so they can no longer disagree.
  presence(range, blocks, step, nodes) {
    return this.get("/api/presence?range=" + encodeURIComponent(range) + "&blocks=" + blocks + "&step=" + step
      + (nodes && nodes.length ? "&nodes=" + encodeURIComponent(nodes.join(",")) : ""));
  },
  ifaceSeries(node, iface, range) { return this.get("/api/iface-series?node=" + encodeURIComponent(node) + "&iface=" + encodeURIComponent(iface) + "&range=" + encodeURIComponent(range)); },
  turnSeries(node, fork, range) { return this.get("/api/turn-series?node=" + encodeURIComponent(node) + "&fork=" + encodeURIComponent(fork) + "&range=" + encodeURIComponent(range)); },
  meshSeries(node, peer, range) { return this.get("/api/mesh-series?node=" + encodeURIComponent(node) + "&peer=" + encodeURIComponent(peer) + "&range=" + encodeURIComponent(range)); },
  turnIps() { return this.get("/api/turn-ips"); },
  turnIpsFlush(body) { return this.post("/api/turn-ips/flush", body || {}); },   // {node?, ip?, service?}: ip → delete one; service → this proxy's offline; else node/fleet inactive (keep online)
  catalog(search, page) { return this.get("/api/catalog?search=" + encodeURIComponent(search || "") + "&page=" + (page || 0)); },
  catalogIndex() { return this.get("/api/catalog/index"); },
  catalogRefresh() { return this.post("/api/catalog/refresh", {}); },
  blockCatalog() { return this.get("/api/block-catalog"); },                       // block-list categories + providers + pickable lists (Routing & Blocking → Blocking tab)
  blockCatalogSave(body) { return this.post("/api/block-catalog/save", body || {}); },   // staged commit: category deltas + provider toggles
  listInfo(cat) { return this.get("/api/list-info?cat=" + encodeURIComponent(cat)); },
  geoUpdate() { return this.post("/api/geo/update", {}); },
  geoProviderRetry(provider) { return this.post("/api/geo/provider-retry", { provider }); },
  nextIp(nodes, iface) { return this.get("/api/next-ip?nodes=" + encodeURIComponent(nodes.join(",")) + "&iface=" + encodeURIComponent(iface)); },
  config(pubkey, node, iface) { return this.get("/api/config?pubkey=" + encodeURIComponent(pubkey) + "&node=" + encodeURIComponent(node) + "&iface=" + encodeURIComponent(iface)); },
  account() { return this.get("/api/account"); },
  accountSave(b) { return this.post("/api/account", b); },
  twofaSetup() { return this.post("/api/account/2fa/setup", {}); },
  twofaEnable(code) { return this.post("/api/account/2fa/enable", { code }); },
  twofaDisable(b) { return this.post("/api/account/2fa/disable", b); },
  nodes() { return this.get("/api/nodes"); },
  nodeCreate(b) { return this.post("/api/nodes/create", b); },
  nodeUpdate(b) { return this.post("/api/nodes/update", b); },
  nodeArrivedClear(b) { return this.post("/api/nodes/arrived/clear", b); },   // dismiss the "arrived here" note
  turnReclaim(b) { return this.post("/api/turn/reclaim", b); },   // a wdtt/csqtt server the node holds and no panel claims
  escrowVerified(b) { return this.post("/api/iface/escrow/verified", b); },   // the browser opened the blob: it is for THIS vault
  resolveHost(h) { return this.get("/api/resolve?host=" + encodeURIComponent(h)); },   // does this name land on this node?
  connectionUpdate(b) { return this.post("/api/connection/update", b); },
  panelSettings(b) { return this.post("/api/panel/settings", b); },
  subVault() { return this.get("/api/sub/vault"); },
  subVaultSet(b) { return this.post("/api/sub/vault", b); },
  subReset() { return this.post("/api/sub/reset", {}); },
  subUsers() { return this.get("/api/sub/users"); },
  subUserEnable(b) { return this.post("/api/sub/user/enable", b); },
  subUserRotate(b) { return this.post("/api/sub/user/rotate", b); },
  subUserDisable(b) { return this.post("/api/sub/user/disable", b); },
  subBlob(b) { return this.post("/api/sub/blob", b); },
  subBlobGet(pid) { return this.get("/api/sub/blob?peer_id=" + encodeURIComponent(pid)); },   // read one peer's ciphertext for in-browser Show-QR decrypt
  subEscrow(b) { return this.post("/api/sub/escrow", b); },   // ensure a user holds an encryption unlock-key (encrypted config storage, no subscription)
  purgePlaintext(b) { return this.post("/api/config/purge-plaintext", b || {}); },   // migration: delete legacy plaintext where a blob exists
  plaintextPeers() { return this.get("/api/config/plaintext-peers"); },   // migration: exactly which peers still hold plaintext (+ orphan count)
  refreshGeo() { return this.post("/api/panel/refresh-geo", {}); },
  // external integration API (Settings → Integrations): read-only tokens + webhooks
  apiTokenCreate(label) { return this.post("/api/integrations/token", { label }); },
  apiTokenRevoke(id) { return this.post("/api/integrations/token/revoke", { id }); },
  apiWebhookSave(b) { return this.post("/api/integrations/webhook", b); },
  apiWebhookDelete(id) { return this.post("/api/integrations/webhook/delete", { id }); },
  apiWebhookTest(id) { return this.post("/api/integrations/webhook/test", { id }); },
  routingReset(b) { return this.post("/api/node/routing-reset", b); },   // per-node: wipe + rebuild + re-pull all smart-routing state
  asnCount(n) { return this.get("/api/asn?n=" + encodeURIComponent(n)); },   // resolve an ASN → prefix count (live editor feedback)
  nodeRotate(b) { return this.post("/api/nodes/rotate", b); },
  // Restore / migrate: arms the rebuild (baseline, interface restores, turn capture, mesh re-provision)
  // and rotates the token, which is BOTH the handle for the new box and the lockout of the old one.
  // NOT nodeRotate — that rotates a token and nothing else. See the plan's §3.1.
  nodeRebuild(b) { return this.post("/api/nodes/rebuild", b); },
  // T-11: the SAME analysis, read-only and before the token rotates. It writes nothing, so the confirm
  // sheets can show what a rebuild would do while the operator can still decide not to.
  nodeRebuildPreflight(nid) { return this.get("/api/nodes/rebuild/preflight?node=" + encodeURIComponent(nid)); },
  nodeRebuildRollback(b) { return this.post("/api/nodes/rebuild/rollback", b); },   // {discard:true} = forget the old box instead
  nodeRemesh(b) { return this.post("/api/nodes/remesh", b); },   // rebuild THIS node's mesh links on demand
  // T-10 — Transfer to ANOTHER panel. One endpoint in two modes so the preview and the act cannot answer
  // different questions: the pre-flight parses the paste, reaches the target and reports what would move;
  // the commit does the same and then pushes. Neither touches the box.
  nodeTransferPreflight(b) { return this.post("/api/nodes/transfer/preflight", b); },
  nodeTransfer(b) { return this.post("/api/nodes/transfer", b); },
  // "is it Reporting on the target panel yet" — asked OF the target, not inferred from our silence.
  nodeTransferStatus(nid) { return this.get("/api/nodes/transfer/status?node=" + encodeURIComponent(nid)); },
  nodeTransferCancel(b) { return this.post("/api/nodes/transfer/cancel", b); },   // withdraw the candidate; the node never left
  nodeFlagRemove(b) { return this.post("/api/nodes/flag-remove", b); },
  nodeUnflagRemove(b) { return this.post("/api/nodes/unflag-remove", b); },
  nodeDelete(b) { return this.post("/api/nodes/delete", b); },
  saveOrder(b) { return this.post("/api/order", b); },   // drag-to-reorder: {kind:"node"|"iface"|"turn", node?, order:[ids]}
  // users
  userCreate(b) { return this.post("/api/users/create", b); },
  userUpdate(b) { return this.post("/api/users/update", b); },
  userDelete(b) { return this.post("/api/users/delete", b); },
  userBlock(b) { return this.post("/api/user/block", b); },       // revoke WG + suspend the subscription URL
  userUnblock(b) { return this.post("/api/user/unblock", b); },   // restore both
  // peers
  peerCreate(b) { return this.post("/api/peers/create", b); },
  peerUpdate(b) { return this.post("/api/peers/update", b); },
  peerAddTarget(b) { return this.post("/api/peers/add-target", b); },
  peerUpdateTarget(b) { return this.post("/api/peers/update-target", b); },
  peerRemoveTarget(b) { return this.post("/api/peers/remove-target", b); },
  peerSetRole(b) { return this.post("/api/peers/set-role", b); },   // role: "primary" | "backup" | "" (clear)
  peerDelete(b) { return this.post("/api/peers/delete", b); },
  peerUnassign(b) { return this.post("/api/peers/unassign", b); },
  peerRekey(b) { return this.post("/api/peers/rekey", b); },
  peerBlock(b) { return this.post("/api/peers/block", b); },      // drop this peer from every node's desired set
  peerUnblock(b) { return this.post("/api/peers/unblock", b); },
  peerAdopt(b) { return this.post("/api/peers/adopt", b); },
  peerCorrect(b) { return this.post("/api/peers/correct", b); },   // broken: reassign an in-subnet IP
  ifaceUpdate(b) { return this.post("/api/iface/update", b); },
  ifaceOnboard(b) { return this.post("/api/iface/onboard", b); },
  ifaceIgnore(b) { return this.post("/api/iface/ignore", b); },       // dismiss an adoption candidate
  ifaceUnignore(b) { return this.post("/api/iface/unignore", b); },   // bring an ignored candidate back
  ifaceCreate(b) { return this.post("/api/iface/create", b); },
  ifaceCancel(b) { return this.post("/api/iface/cancel", b); },
  ifaceDelete(b) { return this.post("/api/iface/delete", b); },
  ifaceRestart(b) { return this.post("/api/iface/restart", b); },   // bounce the iface service on the node
  ifaceStop(b) { return this.post("/api/iface/stop", b); },         // stop (down + disable) the iface
  ifaceStart(b) { return this.post("/api/iface/start", b); },       // start (up + enable) the iface
  ifaceAdopt(b) { return this.post("/api/iface/adopt", b); },     // drift: pull the node's server-edited value
  ifaceRestore(b) { return this.post("/api/iface/restore", b); }, // drift: re-assert the panel's value
  ifaceRecreate(b) { return this.post("/api/iface/recreate", b); }, // restore a MISSING iface with its original identity
  turnManage(b) { return this.post("/api/turn/manage", b); },     // edit listen/connect (+ wrap key)
  turnTitle(b) { return this.post("/api/turn/title", b); },       // set the display title only — no restart/bounce
  turnRotate(b) { return this.post("/api/turn/rotate", b); },     // regenerate the wrap key
  turnDelete(b) { return this.post("/api/turn/delete", b); },         // stop + remove the service
  turnRestart(b) { return this.post("/api/turn/restart", b); },       // restart the service
  turnStop(b) { return this.post("/api/turn/stop", b); },             // stop the service (kept down, survives reconcile)
  turnStart(b) { return this.post("/api/turn/start", b); },           // start a stopped service
  turnReinstall(b) { return this.post("/api/turn/reinstall", b); },   // re-download the binary (fix a failed install / update) + (re)start
  turnInstall(b) { return this.post("/api/turn/install", b); },       // install a new turn-proxy (download + unit)
  turnOnboard(b) { return this.post("/api/turn/onboard", b); },       // adopt a host .service by path
  turnCancel(b) { return this.post("/api/turn/cancel", b); },
  turnCheckUpdates(b) { return this.post("/api/turn/check-updates", b); },   // resolve each fork's latest release tag
  wdttSet(b) { return this.post("/api/wdtt/set", b); },                      // create/update a WDTT instance on a node (declarative)
  wdttDelete(b) { return this.post("/api/wdtt/delete", b); },                // remove a WDTT instance
  wdttAdopt(b) { return this.post("/api/wdtt/adopt", b); },                  // adopt a FOREIGN WDTT server (seeded create: reuses its identity + passwords)
  wdttPeerCreate(b) { return this.post("/api/wdtt-peer/create", b); },       // keyless WDTT peer (mints the WRAP password). UNUSED by the SPA since a peer may hold any mix of kinds — peerCreate takes a keyless target set and mints the password itself. The endpoint stays for API consumers.
  wdttPeerRotate(b) { return this.post("/api/wdtt-peer/rotate", b); },       // rotate a WDTT peer's password (revoke the old link)
  wdttRestore(b) { return this.post("/api/wdtt/restore", b); },              // restore a WDTT server's vaulted identity (owner pw + keypair)
  wdttRecreateFresh(b) { return this.post("/api/wdtt/recreate-fresh", b); }, // abandon the vaulted identity → mint a fresh key (users re-import)
  wdttVersions(q) { return this.get("/api/wdtt/versions?node=" + encodeURIComponent(q.node || "") + "&iface=" + encodeURIComponent(q.iface || "") + "&fork=" + encodeURIComponent(q.fork || "")); },   // our published builds (rollback targets) + any hold
  wdttVersion(b) { return this.post("/api/wdtt/version", b); },              // roll a WDTT instance to a build (ver) or release the hold (ver="")
  csqttSet(b) { return this.post("/api/csqtt/set", b); },                    // create/update a csqtt instance on a node (declarative)
  containerAdopt(b) { return this.post("/api/container/adopt", b); },   // take a wg/awg server over from another container (Amnezia)
  csqttAdopt(b) { return this.post("/api/csqtt/adopt", b); },                // adopt a FOREIGN csqtt server (its users come across)
  csqttDelete(b) { return this.post("/api/csqtt/delete", b); },              // remove a csqtt instance
  csqttPeerCreate(b) { return this.post("/api/csqtt-peer/create", b); },     // keyless csqtt peer (mints the access password). UNUSED by the SPA — see wdttPeerCreate above.
  csqttPeerRotate(b) { return this.post("/api/csqtt-peer/rotate", b); },     // rotate a csqtt peer's password (revoke the old link)
  rosterCheck() { return this.get("/api/turn/roster-check"); },              // client-app schema drift vs upstream GitHub (P1 ack-only clients)
  rosterAck(client) { return this.post("/api/turn/roster-ack", { client }); },   // acknowledge a client's current upstream as the baseline
  p4Report(refresh) { return this.get("/api/turn/p4/report" + (refresh ? "?refresh=1" : "")); },  // P4a versioned per-field roster (parseable forks)
  p4Adopt(client, body) { return this.post("/api/turn/p4/adopt", { client, ...(body || {}) }); },   // adopt {add,remove,vadd,vrem}
  p4SetVersion(client, index) { return this.post("/api/turn/p4/setversion", { client, index }); },     // rollback to an observed version (index=null → latest)
  turnVersions(q) { return this.get("/api/turn/versions?owner=" + encodeURIComponent(q.owner || "") + "&node=" + encodeURIComponent(q.node || "") + "&service=" + encodeURIComponent(q.service || "") + "&fork=" + encodeURIComponent(q.fork || "")); },   // mirrored (rollback-able) versions + any per-(node,fork) hold
  changelog() { return this.get("/api/changelog"); },   // full panel changelog (newest-first) for the version info bubble
  nodeSelfUpdate(b) { return this.post("/api/node/update", b); },   // flag a node to self-update (≠ nodeUpdate, which renames)
  hostUpdate() { return this.post("/api/host/update", {}); },
  checkUpdate() { return this.post("/api/update/check", {}); },
  procClearNode(node) { return this.post("/api/node/proc-clear", { node }); },   // dismiss a stuck/failed re-install/convert/update tag
  procClearHost() { return this.post("/api/host/proc-clear", {}); },
};

// ───────────────────────── store + reactive bus ─────────────────────────
export const bus = { subs: new Set(), emit() { this.subs.forEach(f => { try { f(); } catch (e) { console.error(e); } }); }, sub(f) { this.subs.add(f); return () => this.subs.delete(f); } };
export function useStore() { const [, set] = useState(0); useEffect(() => bus.sub(() => set(x => x + 1)), []); }

export const Store = {
  fleet: [], storeConfigs: false, env: {}, versions: {},
  roster: { version: 1, users: {}, peers: {} }, stats: {}, nodes: [], describe: {}, events: [],
  recon: { peers: [], users: [], orphans: [], nodeStatus: {} },
  sessionConfigs: {},        // pubkey -> { "node|iface" -> confText }   (built at creation, in-memory)
  configEpoch: 0,            // bumps when a config is re-issued, so QR cards re-read it
  recentlyCreated: {},       // id -> ts (row flash)
  rotating: {},              // peer id -> ts — key rotation in flight; grid shows "rotating" until the new key is live
  ifaceOp: {},               // "node|iface" -> { verb:start|restart, phase:busy|ok|fail, started, until, err }
  ifaceNew: {},              // "node|iface" -> { type } — optimistic "creating/onboarding" card shown the instant Create is clicked (until the server's own pending/meta picks it up)
  ctrAdopt: {},              // "node|container:iface" -> { at } — optimistic "taking over" the instant it is
                             // confirmed, until /api/state carries the node's adopt_container back (or it ages out)
  ifaceGone: {},             // "node|iface" -> { at } — ifaceNew's mirror image: optimistic "deleting" card shown the instant Delete is confirmed (until the node stops reporting the interface)
  ghostRekey: {},            // "node|iface" -> { peers:[id], at } — a ghost recreate staged its peers; maybeRekeyGhosts() rekeys them once the fresh interface reports its new key (phase 2)
  turnNew: {},               // "node|service" -> { listen, connect, ... } — optimistic "installing" turn card (full entered data), shown until the node reports the real proxy
  pending: {},               // opId -> { apply(store), done }  — optimistic overlay (Model B)
  rowErrors: {},             // entityKey -> { msg, at }        — explained failure, shown on the row
  async init() {
    await this.poll();
    // Poll every 5s, but SKIP while the tab is HIDDEN — a background tab needs no live data, and each poll
    // makes the (often 1-CPU) panel rebuild the /api/state bundle. Resume with an immediate poll the moment
    // the operator returns, so they never look at stale numbers.
    setInterval(() => { if (document.visibilityState !== "hidden") this.poll().catch(() => {}); }, 5000);
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") this.poll().catch(() => {}); });
  },
  // One round trip: /api/state bundles roster + nodes (incl. health_history) + per-node
  // interface meta + raw snapshots. Status is still derived in the browser via reconcile.js.
  _server: { roster: { version: 1, users: {}, peers: {} }, nodes: [] },   // pristine, last fetched
  async poll() {
    const [s, ev] = await Promise.all([api.state(), api.events().catch(() => null)]);
    const d = (s && s.data) || {};
    this._server = { roster: d.roster || { version: 1, users: {}, peers: {} }, nodes: d.nodes || [] };
    this.describe = d.describe || {};
    this.stats = d.snapshots || {};
    // store_configs is now an enum: "encrypted" (blob at rest) | "off". storeConfigs stays a convenience bool
    // meaning "the panel keeps configs" (now encrypted). configsPlaintext = legacy plaintext files awaiting migration.
    this.storeMode = (d.store_configs === "off" || d.store_configs === false) ? "off" : "encrypted";
    this.storeConfigs = this.storeMode !== "off";
    this.configsPlaintext = d.configs_plaintext || 0;
    this.panelSettings = d.panel_settings || this.panelSettings || {};
    this.subCert = d.sub_cert || {};              // subscription TLS health; {} behind a reverse proxy (admin's own)
    this.panelServices = d.panel_services || {};   // THIS host's own swg units (active/enabled/present) → service-health needs-attention. {} on docker/older panels
    // Non-empty = the panel could not persist its session-signing secret, so every operator is signed
    // out on each restart. "" on a healthy panel and on older ones that do not report it.
    this.sessionEphemeral = d.session_ephemeral || "";
    this.datapath = d.datapath || {};              // THIS host's kernel datapath health (awg module loadable?) → healable "Fix" issue
    this.turnCatalog = d.turn_catalog || this.turnCatalog || null;   // single-source turn fork/client catalog (server-owned); turnForks() falls back to TURN_FORKS_FALLBACK when absent (mixed-version safe)
    this.turnHolds = d.turn_holds || this.turnHolds || {};   // {node: {fork: held_version}} → fork-row "held" flag
    this.panelPublicUrl = d.panel_public_url || this.panelPublicUrl || "";   // CONFIRMED canonical address → flag a tab on an old panel address
    this.panelMigrateRevertable = !!d.panel_migrate_revertable;   // a still-gracing panel-controlled move → the ribbon offers an instant "cancel the move" (server auto-clears at grace end)
    this.panelMigratePrev = d.panel_migrate_prev || null;         // the OLD address to cancel back to (only while revertable)
    this.accessCooldown = d.access_cooldown || { secs: 0, reason: "" };   // one-at-a-time: while a change verifies/graces, Access&TLS disables Save + shows the cooldown
    this.dockerAwaiting = d.docker_awaiting || null;   // a docker restart-safe recreate awaiting a reachability confirm → a global effect auto-commits (reaching /api/state here IS the proof)
    hooks.forkColors && hooks.forkColors();   // keep every .tf-<fork> tag/badge in sync with the picker override
    hooks.themeColors && hooks.themeColors();  // keep wg/awg/blocked/faulty colours + the --brand theme in sync with the pickers
    this.smartCaps = d.smart_caps || this.smartCaps || {};   // per-category {ip,host} → [IP]/[Host] grouping + kernel-mode greying
    this.catDomains = d.cat_domains || this.catDomains || {};   // curated domains per host category → hover tooltip
    this.catLabels = d.cat_labels || this.catLabels || {};   // custom_<hash> → custom-list title (for the destination bars)
    this.catalogProviders = d.catalog_providers || this.catalogProviders || [];   // Geo-data provider registry [{id,label,url,tiers,enabled,error}]
    this.catSizes = d.cat_sizes || this.catSizes || {};   // {cat:{ip,host}} resolved-list record counts → list-size display
    this.env = d.env || this.env || {};
    this.versions = d.versions || this.versions;
    this.tls = d.tls || this.tls || {};   // cert expiry + renewal health → the Access & TLS card

    this.latestRemote = d.latest_remote; this.panelOutdated = !!d.panel_outdated;
    if ("latest_remote_date" in d) this.latestRemoteDate = d.latest_remote_date || "";   // update-bubble: release date + changelog notes
    if ("latest_remote_notes" in d) this.latestRemoteNotes = d.latest_remote_notes || [];
    if (s && s.ok) { this.hostProc = d.host_proc || null; this.hostProcErr = d.host_proc_err || null; }   // only on a clean poll → the tag HOLDS through the panel's own re-install downtime
    if (ev && Array.isArray(ev.data)) this.events = ev.data;
    this.apply();
    // Silent auto-heal net: catch peers that ended up unpublished (created/assigned while locked, or in another
    // session) and publish them once the key is available. Gated on a cheap signature — the peer/user counts plus
    // lock state — so the extra /api/sub/users round-trip fires on a roster change or an unlock, not every idle poll.
    try {
      const hk = ((hooks.vaultKeyCached && hooks.vaultKeyCached()) && this.storeMode === "encrypted")
        ? (Object.keys(this.roster.peers || {}).length + ":" + Object.keys(this.roster.users || {}).length)
        : "off";
      if (hk !== this._healKey) { this._healKey = hk; if (hk !== "off") hooks.vaultAutoHeal && hooks.vaultAutoHeal(); }
    } catch (_) {}
    // T-22: and the same net for a MIGRATED node's server keys. Its own signature — the set of interfaces
    // any node is holding for the vault — because that set changes on a migration, not on a roster edit,
    // and it must not be gated on `storeMode === "encrypted"`: the interface-key vault is a separate thing
    // and is commonly on when subscription encryption is not.
    try {
      const heldList = [];
      for (const n of (this.nodes || [])) {
        for (const i of (n.awaiting_key || [])) heldList.push(n.id + "|" + i);
        for (const w of (((this.stats[n.id] || {}).wdtt) || [])) if (w && w.await_restore && w.iface) heldList.push(n.id + "|w:" + w.iface);
      }
      const held = heldList.sort().join(",");
      if (held !== this._heldKey) { this._heldKey = held; if (heldList.length) hooks.ifaceKeyAutoRestore && hooks.ifaceKeyAutoRestore(); }
      // …and escrow the panel is holding but cannot classify. Keyed on the SET of unverified interfaces,
      // not on the ciphertext: an unstamped node re-seals every five seconds, so the blob changes
      // constantly while the thing worth acting on — which interfaces are unproved — does not.
      const unver = [];
      for (const n of (this.nodes || [])) {
        const ifs = (this.describe || {})[n.id] || {};
        for (const [ifn, m] of Object.entries(ifs)) if (m && m.escrow_unverified) unver.push(n.id + "|i|" + ifn);
        // …and the WDTT twin, which is escrowed the same way and would otherwise never wake this
        for (const ifn of Object.keys(n.wdtt_escrow_unverified || {})) unver.push(n.id + "|w|" + ifn);
      }
      const uk = unver.sort().join(",");
      if (uk !== this._unverKey) { this._unverKey = uk; if (unver.length) hooks.escrowAutoVerify && hooks.escrowAutoVerify(); }
    } catch (_) {}
  },
  // Re-derive everything the UI reads from a PRISTINE copy of server data + the optimistic
  // overlay. Confirmed ops (done) are dropped first — fresh server data already reflects them
  // — then still-pending patches are layered on a fresh clone, so re-applying is idempotent and
  // an in-flight change never blinks out between polls.
  apply() {
    for (const id of Object.keys(this.pending)) if (this.pending[id].done) delete this.pending[id];
    const snap = (typeof structuredClone === "function") ? structuredClone(this._server)
                                                         : JSON.parse(JSON.stringify(this._server));
    this.roster = snap.roster; this.nodes = snap.nodes;
    for (const id of Object.keys(this.pending)) { try { this.pending[id].apply(this); } catch (_) {} }
    // fleet entries carry the stable id (the connector everywhere) + the mutable name (display)
    this.fleet = this.nodes.map(n => ({ id: n.id, name: n.name, color: n.color, transport: "https" }));
    const retiring = new Set();   // pubkeys mid-removal (rotation/delete) — keep them out of the orphans grid
    for (const n of this.nodes) for (const pk of (n.retiring || [])) retiring.add(pk);
    const systemIfaces = new Set();   // node|iface that are panel-managed mesh links (swg_*) — their peers
    for (const nid of Object.keys(this.describe || {}))   // are managed via nodes.json, NOT the roster: not orphans
      for (const ifn of Object.keys(this.describe[nid] || {}))
        if (this.describe[nid][ifn] && this.describe[nid][ifn].system) systemIfaces.add(nid + "|" + ifn);
    const _adv = (this.panelSettings || {}).advanced || {};   // operator-tunable stale/grace thresholds
    // rx-history for FAULTY detection persists across polls (keyed node|iface|pubkey, like reconcile's `observed`)
    this._rxHistory = this._rxHistory || {};
    this._probSince = this._probSince || {};   // {pid: firstProblemMs} — persists so Restore/Correct only offers after a real, sustained problem (not a hiccup / mid-create)
    const _sc = (this.panelSettings || {}).status_conditions || {};   // peer-health detection toggles (default on)
    this.recon = reconcile(this.roster, this.stats, Date.now(), { retiring, systemIfaces, rotating: new Set(Object.keys(this.rotating)),
      history: this._rxHistory, faultyMs: _adv.faulty_ms || 45000, probSince: this._probSince,
      detectBlocked: _sc.blocked !== false, detectFaulty: _sc.faulty !== false,
      expiryWarnDays: (this.panelSettings || {}).expiry_warn_days,   // "about to expire" warn window (days) for the derived status
      ...(_adv.restore_grace_ms ? { restoreGraceMs: _adv.restore_grace_ms } : {}),
      ...(_adv.node_stale_ms ? { nodeStaleMs: _adv.node_stale_ms } : {}), ...(_adv.peer_grace_ms ? { graceMs: _adv.peer_grace_ms } : {}) });
    // Missing-interface Restore gate: the node view carries `missing_ifaces` but the server doesn't stamp WHEN
    // each went missing, so track first-sight client-side (like the peer probSince) and mark each ripe once it
    // has stayed missing past the grace window — so the node screen offers Restore only for a real outage.
    this._missIfSince = this._missIfSince || {};
    { const _now = Date.now(), _grace = _adv.restore_grace_ms || 120000, _seen = new Set();
      for (const n of (this.nodes || [])) { const mi = n.missing_ifaces || {}, gi = n.ghost_ifaces || {};
        for (const ifn of Object.keys(mi)) { const k = n.id + "|" + ifn; _seen.add(k);
          if (!this._missIfSince[k]) this._missIfSince[k] = _now;
          mi[ifn].problemMs = _now - this._missIfSince[k];
          mi[ifn].ripe = mi[ifn].problemMs >= _grace; }
        for (const ifn of Object.keys(gi)) { const k = n.id + "|g|" + ifn; _seen.add(k);   // ghosts get the SAME grace (a briefly-lost iface isn't a ghost yet)
          if (!this._missIfSince[k]) this._missIfSince[k] = _now;
          gi[ifn].problemMs = _now - this._missIfSince[k];
          gi[ifn].ripe = gi[ifn].problemMs >= _grace; }
        // BROKEN (reported but down) gets the same grace for the same reason: an interface is briefly down
        // during any restart, and a Repair button that flashes on every bounce is one nobody trusts.
        const bi = n.broken_ifaces || {};
        for (const ifn of Object.keys(bi)) { const k = n.id + "|b|" + ifn; _seen.add(k);
          if (!this._missIfSince[k]) this._missIfSince[k] = _now;
          bi[ifn].problemMs = _now - this._missIfSince[k];
          bi[ifn].ripe = bi[ifn].problemMs >= _grace; } }
      for (const k of Object.keys(this._missIfSince)) if (!_seen.has(k)) delete this._missIfSince[k]; }
    // a rotation is "done" once the new key shows up live (or after a 45s safety cap) — drop the marker
    for (const id of Object.keys(this.rotating)) {
      const pr = this.recon.peers.find(p => p.id === id);
      // Keep the marker for ≥4s even if the peer still reads ready — an optimistic "Rotating" (set the instant you
      // confirm) must survive the poll that lands before the rekey has actually taken the peer not-ready.
      if ((pr && (pr.status === "online" || pr.status === "ready" || pr.status === "partial") && Date.now() - this.rotating[id] > 4000) || (Date.now() - this.rotating[id] > 45000)) delete this.rotating[id];
    }
    // auto-clear a peer's pinned action error once it's no longer true — no manual dismiss needed. A
    // "<node> hasn't reported <iface> yet" error resolves the instant that iface's meta arrives; a generic
    // action failure clears once the peer reconciles healthy. A long age cap sweeps anything else (e.g. the
    // peer was deleted, or a one-off failure on a row that never settles). Runs every apply(), so the bubble
    // disappears on the same poll the condition clears.
    for (const k of Object.keys(this.rowErrors)) {
      if (!k.startsWith("peer:")) continue;
      const e = this.rowErrors[k];
      const pr = this.recon.peers.find(p => p.id === k.slice(5));
      const resolved = e.iface ? !!this.ifaceMeta(e.node, e.iface)
                               : (pr && (pr.status === "online" || pr.status === "ready"));
      if (!pr || resolved || Date.now() - (e.at || 0) > 120000) delete this.rowErrors[k];
    }
    try { hooks.dashTick && hooks.dashTick(); } catch (_) {}   // accumulate the dashboard's live-only trend series (online counts)
    bus.emit();
    hooks.alertServices && hooks.alertServices();   // raise the on-load modal for an un-silenced CRITICAL panel-service issue (guarded: once per incident, never over an open modal)
    try { hooks.rekeyGhosts && hooks.rekeyGhosts(); } catch (_) {}   // phase 2 of a ghost recreate: rekey its peers once the fresh interface is live
  },
  node(id) { return this.fleet.find(n => n.id === id); },              // lookup by stable id
  nodeName(id) { const n = this.node(id); return (n && n.name) || id; }, // display title (falls back to id)
  nodeColor(id) { const n = this.node(id); return pickThemed(n && n.color, NODE_COLOR_DEFAULT.dark, NODE_COLOR_DEFAULT.light); },
  ifacesOf(node) { return Object.keys(this.describe[node] || {}); },   // node = id (describe keyed by id)
  ifaceMeta(node, iface) { return (this.describe[node] || {})[iface] || null; },
  // a panel-managed inter-node mesh link (swg_*): never a user-peer target / egress NIC. Authoritative
  // signal is the backend `.system` flag; fall back to the reserved prefix for un-updated nodes.
  ifaceIsSystem(node, iface) {
    if (!iface) return false;
    const m = (this.describe[node] || {})[iface] || {};
    const pfx = (this.panelSettings || {}).reserved?.iface_prefix || "swg_";
    // NB: wdtt* is NOT system — it IS a valid peer target (for keyless WDTT peers). Peer-create dispatches on the
    // target's kind (iTypeOf → "wdtt"), so a wdtt* target mints a WDTT peer, not a broken WG one. Only the turn
    // Forwards-to pickers exclude wdtt* (their own filter), since a -connect fork can't front a WDTT interface.
    return !!m.system || String(iface).startsWith(pfx) || String(iface).startsWith("swg_");
  },
  userIfacesOf(node) {   // wg/awg from describe + WDTT + csqtt ifaces (self-contained kinds own their iface, absent from describe → pulled from the readback)
    const base = this.ifacesOf(node).filter(i => !this.ifaceIsSystem(node, i));
    const wd = ((this.stats[node] || {}).wdtt || []).map(w => w && w.iface).filter(Boolean);
    const cs = ((this.stats[node] || {}).csqtt || []).map(c => c && c.iface).filter(Boolean);
    return Array.from(new Set([...base, ...wd, ...cs]));
  },
  peer(id) { return this.recon.peers.find(p => p.id === id); },
  user(id) { return this.recon.users.find(u => u.id === id); },
  peersOfUser(id) { return this.recon.peers.filter(p => p.user_id === id); },
  unassignedPeers() { return this.recon.peers.filter(p => p.unassigned); },
};
