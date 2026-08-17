/* turn-catalog.js — which turn-proxy forks exist, and what each one is.
 *
 * LAYER 1 (see docs/APP-JS-SPLIT-PLAN.md). Imports store + theme.
 *
 * Both halves of the catalog live here: the boot/offline FALLBACK data, and the accessors that prefer the
 * SERVED catalog (Store.turnCatalog) over it. They were split across 6,000 lines of app.js — the fallback
 * const near the top and the accessors down in the turn UI — which is what forced turnOwner's hand-rolled
 * TDZ guard. One module, one answer to "what is this fork".
 *
 * It started as a layer-0 leaf holding only the data; the accessors read Store, so bringing them here
 * moves the whole module up a layer rather than leaving the catalog answerable from two places.
 */

import { Store } from "./store.js";
import { pickThemed } from "./theme.js";

// `turnForks()` returns the served catalog mapped to the shape the SPA has always used ({id,label,owner,wrap,
// keyflag,color,colorL,protocols}); this array is only the boot/offline FALLBACK (and a mixed-version safety
// net if the panel predates the catalog). Keep it in step with TURN_SERVERS. `protocols` (a fork missing "awg"
// is WireGuard-only) supersedes the old TURN_WG_ONLY set. See docs/TURN-PROXY-OVERHAUL-PLAN.md.
// WireGuard-only rationale: kiper292 = plain wireguard-go + a parser that REJECTS awg params; anton48 (iOS) has
// no AmneziaWG fields; samosvalishe = free-turn-proxy's FreeTurn app (integrated plain-WG client). WINGS-N is
// app-integrated but DOES support awg; the sidecar forks relay UDP transparently.
// Order mirrors the panel's TURN_SERVER_ORDER (cacggghp + WINGS-N pinned, then by server+app stars). This is
// only the boot/offline fallback; the served catalog is authoritative.
export const TURN_FORKS_FALLBACK = [
  { id: "cacggghp", label: "cacggghp", owner: "cacggghp/vk-turn-proxy", wrap: "", keyflag: "-wrap-key", color: "#5FB0E0", colorL: "#2C7EC0", protocols: ["wg", "awg"], hidden: true },
  { id: "WINGS-N", label: "WINGS-N", owner: "WINGS-N/vk-turn-proxy", wrap: "-wrap-mode on", color: "#C98BE0", colorL: "#9B4FC7", protocols: ["wg", "awg"] },
  { id: "MYSOREZ", label: "MYSOREZ", owner: "MYSOREZ/vk-turn-proxy", wrap: "", keyflag: "-wrap-key", color: "#4FC7B4", colorL: "#12897A", protocols: ["wg", "awg"] },
  { id: "samosvalishe", label: "samosvalishe", owner: "samosvalishe/free-turn-proxy", wrap: "-obf-profile rtpopus", keyflag: "-obf-key", color: "#E0A85F", colorL: "#C07A1E", protocols: ["wg"] },
  { id: "kiper292", label: "kiper292", owner: "kiper292/vk-turn-proxy", wrap: "", keyflag: "-wrap-key", color: "#6FD9A8", colorL: "#12A46B", protocols: ["wg"], hidden: true },
  { id: "anton48", label: "anton48", owner: "anton48/vk-turn-proxy", wrap: "-wrap-srtp", color: "#D9CF5F", colorL: "#8E8420", protocols: ["wg"] },
  { id: "Moroka8", label: "Moroka8", owner: "Moroka8/vk-turn-proxy", wrap: "-wrap", color: "#E07A9A", colorL: "#C24468", protocols: ["wg", "awg"] },
];

// turn-proxy display label: strip the vk-turn-proxy- prefix and render as name:port (a "-NNNN"
// suffix in the service name becomes ":NNNN"; otherwise the listen port is appended).
export function turnLabel(service, port) {   // just the fork name — the port shows in the Listen row
  let s = (service || "turn-proxy").replace(/^vk-turn-proxy-?/, "") || "turn";   // i18n-keys: internal fork/service id
  s = s.replace(/-\d+$/, "") || "turn";
  return s === "main" ? "cacggghp" : s;   // legacy "main" services (pre-rename) still display as cacggghp
}
// the fork id baked into a service name (vk-turn-proxy-<fork>-<port>) → its owner repo (for version/update checks)
export function turnFork(svc) { return turnLabel(svc, ""); }
export function turnOwner(svc) {
  const f = turnFork(svc); const fk = turnForkList().find(x => x.id === f);
  return fk ? fk.owner : (f && f !== "turn" ? f + "/vk-turn-proxy" : "");
}

// the installable turn-proxy forks (owner repo + the fork's obfuscation flags — the node appends a
// fresh -wrap-key). Mirrors the installer's turn_repo_owner / turn_wrap_flags.
// each fork has a dark-mode `color` and a deeper `colorL` (light-mode default, legible on white).
// The turn fork registry is now SERVER-OWNED (swg-panel-server TURN_SERVERS → /api/state.turn_catalog).
// the live fork list — served catalog mapped to the SPA shape, else the fallback (mixed-version safe).
// (named turnForkList, not turnForks — the Settings card has a local `turnForks` Set for the picker toggles.)
export function turnForkList() {
  const cat = Store.turnCatalog;
  if (cat && Array.isArray(cat.servers) && cat.servers.length)
    return cat.servers.map(s => ({ id: s.id, label: s.label || s.id, product: s.product || "", raw: !!s.raw, owner: s.owner || "", kind: s.kind || "turn",
      wrap: s.wrap || "", keyflag: s.keyflag, color: (s.color || {}).dark, colorL: (s.color || {}).light, hidden: !!s.hidden,
      protocols: (Array.isArray(s.protocols) && s.protocols.length) ? s.protocols : ["wg", "awg"],
      settings: Array.isArray(s.settings) ? s.settings : [], client_settings: Array.isArray(s.client_settings) ? s.client_settings : [], clients: s.clients || [], compat: s.compat || {}, client_schemas: s.client_schemas || {}, cli_authors: Array.isArray(s.cli_authors) ? s.cli_authors : ["samosvalishe"] }));
  return TURN_FORKS_FALLBACK;
}
// Operator-facing fork list — the full catalog MINUS hidden/dead forks (cacggghp/kiper292). Lookups (turnColor/
// turnFork label) use the FULL turnForkList() so a deployed hidden-fork instance still resolves; only the pickers/
// toggles/dropdowns use this filtered view.
export function turnForksVisible() { return turnForkList().filter(f => !f.hidden); }
// A fork's OPERATOR-FACING name (the catalog label), never the internal id. They differ for every fork whose author
// name isn't its id — Ivan4537/wdttplus, XXcipherX/xxcipherx, SpaceNeuroX/qwdtt, amurcanov/csqtt — and the id leaking
// into a label position is a recurring drift (see ForkTag). One lookup, so there is a single place to be right.
export function forkLabel(fork) { return (turnForkList().find(f => f.id === fork) || {}).label || fork || ""; }
// A fork has TWO names and they are not interchangeable: `label` is the AUTHOR (SpaceNeuroX) and `product` is the
// server software they ship (qWDTT). Author identifies who maintains it — the fork tag, the settings row, the
// version board; product identifies what is running — the Listen row of an interface card. The picker needs both,
// because "SpaceNeuroX" alone doesn't say it's a qWDTT server and "qWDTT" alone doesn't say whose.
export function forkProduct(fork) {
  const f = turnForkList().find(x => x.id === fork) || {};
  return f.product || (f.kind === "wdtt" ? "WDTT" : f.label) || fork || "";
}
export function forkPickLabel(fork) {   // fork dropdowns: "author · product" (author alone where there is no product)
  const f = turnForkList().find(x => x.id === fork) || {};
  const lbl = f.label || fork || "";
  return f.product ? lbl + " · " + f.product : lbl;
}
export function forkSupportsAwg(fork) {
  const f = turnForkList().find(x => x.id === fork);
  return f ? (f.protocols || ["wg", "awg"]).includes("awg") : true;   // unknown fork → assume awg-capable (permissive, matches prior default)
}
// stable colour for a turn-proxy fork in the ACTIVE mode (peers connected via it get their badge tinted this);
// a Panel-settings override (turn_fork_colors[id] = {dark,light}) wins over the fork's catalog default.
export function turnColor(label) {
  const ov = (Store.panelSettings && Store.panelSettings.turn_fork_colors) || {};
  const fk = turnForkList().find(x => x.id === label);
  return pickThemed(ov[label], (fk && fk.color) || "#8FA8C0", (fk && fk.colorL) || "#5E7085");
}
// A client app's colour = its NATIVE fork's turn-proxy server colour (a cross-fork/experimental app still shows its
// HOME server's colour). null for the generic CLI (no native fork) — callers fall back to the current fork's colour.
export function turnClientColor(clientId) {
  const c = ((Store.turnCatalog && Store.turnCatalog.clients) || {})[clientId] || {};
  if (c.color) return pickThemed(c.color, c.color.dark, c.color.light);   // explicit app colour (author isn't a fork, e.g. SpaceNeuroX/luminescq)
  return c.native_fork ? turnColor(c.native_fork) : null;
}
// The app's author = its NATIVE fork (who makes it). null for the generic CLI (no native fork). `owner` is that
// fork's GitHub owner/repo, so callers can link "by <author>" to the source.
export function turnClientAuthor(clientId) {
  const c = ((Store.turnCatalog && Store.turnCatalog.clients) || {})[clientId] || {};
  // an explicit `author` (real app author — may not be a server fork, e.g. SpaceNeuroX/luminescq) wins over the
  // native_fork (which is only for schema sharing). owner links "by <author>" to the app's own repo.
  if (c.author) {
    const p = ((c.platforms && Object.values(c.platforms)[0]) || {}).github || "";
    const m = p.match(/github\.com\/([^/]+\/[^/]+)/);
    return { fork: c.author, owner: m ? m[1] : "" };
  }
  if (!c.native_fork) return null;
  const f = turnForkList().find(x => x.id === c.native_fork) || {};
  return { fork: c.native_fork, owner: f.owner || "" };
}
