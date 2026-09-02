/* model.js — what the roster and the node snapshots MEAN.
 *
 * LAYER 1 (see docs/APP-JS-SPLIT-PLAN.md). Imports util + store; nothing above it.
 *
 * This is the interface TAXONOMY's one home, and that matters more than its size suggests. An
 * interface's kind is partly NAME-SNIFFED (isWdttIface is a filename regex mirroring the node's
 * _WDTT_IFACE_RE) and several of the checks are NEGATIVE — ifaceMatch's "*wg" means "not awg and not
 * wdtt". So a new kind whose name does not match the pattern falls SILENTLY into the WireGuard bucket
 * instead of erroring. The coming TUN-only WDTT is exactly that case: add the kind here, once, and every
 * dropdown, filter, badge and peer-create dispatch follows. See docs/APP-JS-SPLIT-PLAN.md §5.
 */

import { isWdttIface, isCsqttIface, isSelfContainedIface, portOf } from "./util.js";
import { Store } from "./store.js";
import { T } from "./i18n.js";

// ── interface / target taxonomy ──────────────────────────────────────────────────────────────────
// wg vs awg for an interface. A single peer/key can't span both protocols, so the target pickers hide the other
// kind once one is chosen (enforced wherever peers get interfaces — peers module, users module, …).
// THE ONE interface/target-kind classifier — "wg" | "awg" | "wdtt". WDTT wins on the authoritative target `type`
// or its iface NAME (a WDTT interface is never in `describe`). Otherwise the LIVE interface meta is authoritative
// for awg-vs-wg, falling back to the stored target.type only when the node isn't reporting the interface. Every
// badge/count/dispatch keys off this (via iTypeOf / targetType) so a WDTT target can never be mislabelled WG.
// The node's ACTUAL WDTT interfaces: its live readback first, then the panel's own config so a node that is
// down still classifies correctly. The name pattern below is only a last-resort fallback — adoption accepts an
// operator-chosen name (wdttreal0), which the generated-name regex rejects, and such a target was then dropped
// into the WG list and tagged "wg". Peer-create dispatches on this, so it minted the wrong kind of peer too.
export function wdttOn(node, iface) {
  if (!node || !iface) return false;
  if (((Store.stats[node] || {}).wdtt || []).some(w => w && w.iface === iface)) return true;
  const n = (Store.nodes || []).find(x => x.id === node);
  return !!(n && (n.wdtt_cfg || {})[iface]);
}
// The csqtt sibling of wdttOn, and for the same reason: ASK THE NODE before guessing from the name. Without
// it `kindOf` fell from an explicit `type` straight to `/^csqtt\d{1,4}$/`, so an ADOPTED instance — whose name
// the operator or the foreign install chose, not us (`csqttx`, `csqfbm`) — matched nothing, was not in
// `describe` either (csqtt owns its own raw TUN and has no wg/awg conf), and came back classified as plain
// WireGuard anywhere no roster target supplied the type. WDTT never had that hole because it had wdttOn.
export function csqttOn(node, iface) {
  if (!node || !iface) return false;
  if (((Store.stats[node] || {}).csqtt || []).some(c => c && c.iface === iface)) return true;
  const n = (Store.nodes || []).find(x => x.id === node);
  return !!(n && (n.csqtt_cfg || {})[iface]);
}
// ── NAME → kind, asked of the FLEET ───────────────────────────────────────────────────────────────
// Several call sites (dropdown groups, interface filters, NIC lists) hold only an interface NAME — no node,
// no roster target — and so could only ever ask the two regexes "is it called wdtt<N> / csqtt<N>?". That
// question stopped being the same as "what kind is it?" the moment adoption started taking foreign servers
// under their own names (`wdttx`, `csqfbm2`), and creation may now choose a name too. So ask the fleet: scan
// every node's live readback and the panel's own instance config for an interface by that name, and fall back
// to the pattern only for a name nothing in the fleet claims. Cheap — the maps are small and already in memory.
export function scKindByName(name) {
  if (!name) return null;
  for (const nid of Object.keys(Store.stats || {})) {
    if (wdttOn(nid, name)) return "wdtt";
    if (csqttOn(nid, name)) return "csqtt";
  }
  for (const n of (Store.nodes || [])) {
    if ((n.wdtt_cfg || {})[name]) return "wdtt";
    if ((n.csqtt_cfg || {})[name]) return "csqtt";
  }
  return isWdttIface(name) ? "wdtt" : isCsqttIface(name) ? "csqtt" : null;
}
// Does this roster TARGET land on a self-contained turn instance? The authoritative form of util.js's
// isSelfContainedTarget: targetType consults the roster `type`, then the node's live set, then the name.
export const isSelfContainedTgt = (t) => !!t && (targetType(t) === "wdtt" || targetType(t) === "csqtt");
export const isWdttName = (name) => scKindByName(name) === "wdtt";
export const isCsqttName = (name) => scKindByName(name) === "csqtt";
export const isSelfContainedName = (name) => !!scKindByName(name);

export function kindOf(node, iface, type) {
  if (type === "wdtt" || wdttOn(node, iface) || isWdttIface(iface)) return "wdtt";
  if (type === "csqtt" || csqttOn(node, iface) || isCsqttIface(iface)) return "csqtt";   // raw-TUN self-contained kind (not in describe; keyed by the live set, then name/type)
  const m = (Store.describe[node] || {})[iface];
  // The TOOL the node reports wins. "Carries obfuscation params" is a fact about the conf FILE, and the two
  // can disagree: `msk-main/wg0`, taken over from a plain-WG container, picked up S/H/I lines from an
  // ungated set-iface and wore an AWG badge for a device `awg show` cannot see. A node too old to report
  // `tool` omits it, and those keep the old inference.
  if (m && (m.tool === "wg" || m.tool === "awg")) return m.tool;
  if (m) return (m.awg_params && Object.keys(m.awg_params).length) ? "awg" : "wg";
  return (String(type || "wg").toLowerCase() === "awg") ? "awg" : "wg";
}
/* ── how a node was DEPLOYED, and what OWNS that installation ──────────────────────────────────
   Two different facts, and a NixOS host running our image answers BOTH: it is a container for every
   behavioural purpose (`kind`) and its installation belongs to its configuration (`platform`).
   Rendering only one of them is what made the old label wrong.

   Through a MAP, never the two-way ternary this replaces: `kind === "docker" ? docker : bare-metal`
   printed "bare-metal" for every value it did not recognise, so a run model this panel has never
   heard of read as a confident lie. Unknown now renders the raw value, which is at least true.

   Built on each call, not at import: modules load before loadLang() resolves, so a T() evaluated at
   module scope freezes in English whatever the catalog says. */
export const kindLabel = (kind, runtime) => (kind === "docker" && runtime === "podman")
  ? T("kind|podman")
  : (({ docker: T("kind|docker"), baremetal: T("kind|bare-metal") })[kind] || kind || "");

/* The platform pill's text. Platform names are proper nouns — "NixOS" is spelt the same in every
   language — so this is a display map, not a translation: an unknown platform renders as reported. */
const PLATFORM_NAMES = {
  nixos: "NixOS", ubuntu: "Ubuntu", debian: "Debian", fedora: "Fedora", arch: "Arch", alpine: "Alpine",
  centos: "CentOS", rhel: "RHEL", rocky: "Rocky", almalinux: "AlmaLinux", opensuse: "openSUSE",
  "opensuse-leap": "openSUSE Leap", "opensuse-tumbleweed": "openSUSE Tumbleweed", sles: "SLES",
  raspbian: "Raspberry Pi OS", devuan: "Devuan", gentoo: "Gentoo", void: "Void", manjaro: "Manjaro",
  linuxmint: "Linux Mint", pop: "Pop!_OS", kali: "Kali", amzn: "Amazon Linux", ol: "Oracle Linux",
  freebsd: "FreeBSD", openwrt: "OpenWrt", talos: "Talos",
};
// Distribution names are proper nouns — "Ubuntu" is spelt the same in every language — so this is a display
// map, not a translation, and anything unknown renders as the node reported it (capitalised) rather than
// vanishing. Same rule the NixOS-only version of this followed; it just has company now.
export const platformLabel = p => PLATFORM_NAMES[p] || (p ? p.charAt(0).toUpperCase() + p.slice(1) : "");

export const iTypeOf = (node, iface) => kindOf(node, iface, null);   // by (node, iface) — the TargetPicker's one-kind lock + peer-create dispatch key off it
export const targetType = t => t ? kindOf(t.node, t.iface, t.type) : "wg";   // by roster TARGET — every protocol tag/colour uses this
// The port a CLIENT dials for an adoption candidate. For wg/awg that is the interface's own listen port; for a
// running WDTT server it is NOT — the fork's DTLS listener is what clients dial, and the candidate's listen_port
// is the tunnel's own internal WG port, which nothing outside ever connects to. Reporting that as "Listen" put a
// port on the card that no client uses, contradicting both the adopt sheet (which labels the two separately) and
// the card the same interface becomes once adopted. The node's DORMANT rows already report it this way; this is
// the running case catching up. Same distinction the Users-vs-Peers row on that card already makes.
export const candDialPort = cd => {
  const l = ((cd || {}).wdtt || {}).listen;
  const p = l ? Number(String(l).split(":").pop()) : 0;
  return p || (cd || {}).listen_port || 0;
};
// interface type for the grouped dropdowns — awg if any node's interface of this name carries AmneziaWG params
export function ifaceIsAwg(iface) {
  for (const n of Object.keys(Store.describe || {})) { const m = (Store.describe[n] || {})[iface]; if (m && Object.keys(m.awg_params || {}).length) return true; }
  return false;
}
// interface-filter dropdown values: "" / "*" = all · "*awg" / "*wg" / "*wdtt" = all of one type · else an exact name.
export const ifaceIsAll = v => !v || v === "*" || v === "*awg" || v === "*wg" || v === "*wdtt" || v === "*csqtt";   // an aggregate (multi-iface) filter value
// Does an interface pass the filter value? Pass the roster TARGET as `t` wherever there is one (every caller
// has one): its `type` is authoritative, so a wdtt/csqtt deployment on an operator-named interface is filtered
// as its real kind instead of falling through the negative "*wg" test into the WireGuard bucket. Without a
// target this asks the fleet by name (scKindByName), which is still far better than the bare pattern.
export function ifaceMatch(iface, filter, t) {
  if (!filter || filter === "*") return true;
  const sc = t ? (kind => kind === "wdtt" || kind === "csqtt" ? kind : null)(targetType(t)) : scKindByName(iface);
  if (filter === "*wdtt") return sc === "wdtt";
  if (filter === "*csqtt") return sc === "csqtt";
  const awg = t ? targetType(t) === "awg" : ifaceIsAwg(iface);
  if (filter === "*awg") return awg && !sc;
  if (filter === "*wg") return !awg && !sc;   // WDTT/csqtt own their own iface — never lump under WireGuard
  return iface === filter;
}

// ── node + interface liveness ────────────────────────────────────────────────────────────────────
// turn-proxies on a node whose connect-port matches a given iface's listen_port
export function turnProxiesFor(node, iface) {
  const snap = Store.stats[node]; if (!snap) return [];
  const lp = String((((snap.interfaces || {})[iface] || {}).meta || {}).listen_port || "");
  return (snap.turn_proxies || []).filter(tp => lp && portOf(tp.connect) === lp);
}
// a node is "stale" when its last snapshot is older than the staleness window (reconcile.js) — we can't
// trust any live state then, so cross-reference badges grey out (don't claim "active" on a node gone dark).
export function nodeStale(node) { return Store.recon.nodeStatus[node] !== "live"; }

// Is THIS deployment's client resolving over encrypted DNS (DoT/DoH) right now? The node records the source
// address of every such attempt in a self-expiring nft set, so a hit means "currently", not "once did".
//
// Why it matters enough to take the peer's status pill: Force-DNS classifies by WATCHING plain DNS, so a peer
// the node cannot observe is never matched against a category — its traffic leaves by the local exit whatever
// the routing rules say. The node deliberately no longer BLOCKS it for that (dropping DoT black-holed every
// lookup and killed such clients outright), which makes saying so the entire remedy. It is a property of the
// PEER, not of the node, which is why it reads here and not in the node's health roll-up.
export function peerUncategorised(t) {
  const ip = String((t && t.ip) || "").split("/")[0];
  // Store.nodes, NOT Store.node(): the latter reads Store.fleet, which is a deliberately slim
  // {id,name,color,transport} projection — `doh_peers` is not in it, so this silently answered
  // "no" for every peer and the badge could never appear anywhere. Full records live on Store.nodes.
  const nrec = (Store.nodes || []).find(n => n.id === t.node) || {};
  // PRESENCE, not the count. The value is an attempt counter and the entry self-expires, so being in the map
  // at all is the signal — `!!map[ip]` would read a zero-count entry as "not on encrypted DNS", which is the
  // one case where the node is telling us the opposite.
  return !!ip && Object.prototype.hasOwnProperty.call(nrec.doh_peers || {}, ip);
}
export function ifaceNotUp(node, ifn) { const s = (((Store.stats[node] || {}).interfaces) || {})[ifn] || {}; return !!s.down || !!s.stopped; }  // down OR stopped → grey chips
export function turnDown(tp) { return tp && tp.running === false; }

// ── ghost interfaces: lost AND keyless, so the identity cannot be restored — only recreated ──
// Restore, so a brief blip is never called a ghost.
export function ghostIface(node, iface) {
  const nr = (Store.nodes || []).find(n => n.id === node) || {};
  const g = (nr.ghost_ifaces || {})[iface];
  if (g) return { cold: true, ripe: !!g.ripe, problemMs: g.problemMs || 0, subnet: null };
  const mi = (nr.missing_ifaces || {})[iface];
  if (mi && !mi.key_source) return { cold: false, ripe: !!mi.ripe, problemMs: mi.problemMs || 0, subnet: mi.subnet || null };
  return null;
}
// the reconciled peers with a deployment on this (node, iface)
export function ghostPeers(node, iface) {
  return (Store.recon.peers || []).filter(p => (p.targets || []).some(t => t.node === node && t.iface === iface));
}

// ── suggestions: the next free port, interface name and subnet ───────────────────────────────────
// suggest the next listen port for a NEW interface ("iface") or turn-proxy ("turn") on a node: the highest
// existing port OF THAT KIND + 1 (or the base default if none), skipping any port already used by either.
// client-optimistic interfaces still being created on a node → [{name, subnet, port, type}]. Suggestions
// fold these in so a 2nd "Load new interface" before the 1st is live picks the NEXT free name/subnet/port.
export function pendingIf(node) {
  const pfx = node + "|", out = [];
  for (const k of Object.keys(Store.ifaceNew)) if (k.startsWith(pfx)) { const e = Store.ifaceNew[k]; out.push({ name: k.slice(pfx.length), subnet: e.subnet || "", port: e.port || "", type: e.type }); }
  return out;
}
export function pendingTurnPorts(node) {   // listen ports of turn-proxies still being installed (client-optimistic)
  const pfx = node + "|", out = [];
  for (const k of Object.keys(Store.turnNew)) if (k.startsWith(pfx)) { const p = Number(portOf(Store.turnNew[k].listen)); if (p) out.push(p); }
  return out;
}
// Ports claimed by WDTT instances the PANEL already wants but the node has not reported yet (wdtt_cfg = the desired
// set, filled the instant a create/edit is accepted; snap.wdtt only appears once the server is actually running).
// Each claims TWO: the DTLS listen port and the internal wg-port. Without these, a suggestion made moments after
// creating one hands out a port that instance is about to take, and the save then fails on a collision.
export function pendingWdttPorts(node) {
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const out = [];
  for (const w of Object.values(nrec.wdtt_cfg || {})) {
    if (!w) continue;
    const d = Number(String(w.listen || "").split(":").pop()); if (d) out.push(d);
    const g = Number(w.wg_port); if (g) out.push(g);
  }
  return out;
}
// Ports claimed by csqtt instances the panel already wants but the node has not reported yet (csqtt_cfg = the
// desired set). Unlike WDTT, a csqtt server binds ONE port — the DTLS listen (raw TUN, no internal WG port).
export function pendingCsqttPorts(node) {
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const out = [];
  for (const c of Object.values(nrec.csqtt_cfg || {})) {
    if (!c) continue;
    const d = Number(String(c.listen || "").split(":").pop()); if (d) out.push(d);
  }
  return out;
}
export function suggestPort(node, kind, extra) {
  const snap = Store.stats[node] || {};
  const ifacePorts = Object.values(snap.interfaces || {}).map(b => Number((b.meta || {}).listen_port)).filter(Boolean)
    .concat(pendingIf(node).map(p => Number(p.port)).filter(Boolean));   // include interfaces being created
  const turnPorts = ((snap.turn_proxies) || []).map(t => Number(portOf(t.listen))).filter(Boolean)
    .concat(pendingTurnPorts(node));   // include turn-proxies being installed
  // WDTT instances each claim TWO ports (DTLS listen + internal wg-port) and don't appear in snap.interfaces,
  // so fold them into the used-set explicitly — else a suggestion could clash with a running WDTT server.
  const wdttPorts = (snap.wdtt || []).flatMap(w => w ? [Number(String(w.listen || "").split(":").pop()), Number(w.wg_port)] : []).filter(Boolean);
  // csqtt instances (raw TUN) each claim ONE port — the DTLS listen — and, like WDTT, don't appear in snap.interfaces.
  const csqttPorts = (snap.csqtt || []).map(c => c ? Number(String(c.listen || "").split(":").pop()) : 0).filter(Boolean);
  const used = new Set([...ifacePorts, ...turnPorts, ...wdttPorts, ...pendingWdttPorts(node), ...csqttPorts, ...pendingCsqttPorts(node), ...(extra || []).map(Number).filter(Boolean)]);   // extra = ports picked in-modal, not yet applied
  const mine = kind === "turn" ? turnPorts : ifacePorts;
  // Never hand out the UPSTREAM DEFAULTS. An unmanaged WDTT server binds 56000 (DTLS) + 56001 (internal WG) out
  // of the box and a stock WireGuard 51820, so suggesting one walks straight into a collision with something the
  // panel does not manage — and, in WDTT's case, may not even be able to see. Same rule as the name suggestion:
  // the SUGGESTION avoids them, the field stays free to type.
  // 56003 joins them for a different reason: it is the qWDTT app's HARD-CODED default RAW-IP port. The app only
  // dials another one when its "Manual ports" switch is on, so keeping 56003 free fleet-wide is what makes
  // "turn RAW on" a one-click change instead of a per-user instruction. (See _wdtt_alloc_raw_subnet / the RAW
  // field's hint — the panel prefers 56003 for RAW and says so when it can't get it.)
  const reserved = new Set([51820, 56000, 56001, 56003]);
  let p = mine.length ? Math.max(...mine) + 1 : (kind === "turn" ? 56002 : 51821);
  while ((used.has(p) || reserved.has(p)) && p < 65535) p++;
  return p;
}
// Client-side port-collision check (mirrors the server's _node_ports). Returns a human label of whatever
// already occupies `port` on this node, or null if the port is free. `own` = ports this instance already
// holds, so editing it doesn't flag its own port. Lets port fields validate live, before the optimistic
// save closes the modal (else a clash only surfaces as a node-side "FAILED TO APPLY" after the fact).
export function portHolder(node, port, own) {
  const p = Number(port); if (!p) return null;
  const skip = new Set((own || []).map(Number).filter(Boolean));
  if (skip.has(p)) return null;
  const snap = Store.stats[node] || {};
  for (const [ifn, b] of Object.entries(snap.interfaces || {})) if (Number((b.meta || {}).listen_port) === p) return ifn;
  for (const t of ((snap.turn_proxies) || [])) if (Number(portOf(t.listen)) === p) return (t.service || T("a turn-proxy"));
  for (const w of (snap.wdtt || [])) {
    if (!w) continue;
    if (Number(String(w.listen || "").split(":").pop()) === p) return (w.iface || T("a WDTT proxy")) + T(" (WDTT)");
    if (Number(w.wg_port) === p) return (w.iface || T("a WDTT proxy")) + T(" (WDTT internal WG)");
  }
  for (const c of (snap.csqtt || [])) {
    if (!c) continue;
    if (Number(String(c.listen || "").split(":").pop()) === p) return (c.iface || T("a csqtt proxy")) + T(" (CSQTT)");
  }
  for (const pt of pendingIf(node)) if (Number(pt.port) === p) return (pt.name || T("a pending interface"));
  // WDTT instances the panel wants but the node has not started yet — named, so the inline error says which
  // instance is taking the port instead of only failing server-side on save.
  const _nrec = (Store.nodes || []).find(n => n.id === node) || {};
  for (const [ifn, w] of Object.entries(_nrec.wdtt_cfg || {})) {
    if (!w) continue;
    if ((snap.wdtt || []).some(x => x && x.iface === ifn)) continue;   // already reported → handled above
    if (Number(String(w.listen || "").split(":").pop()) === p) return (ifn || T("a WDTT proxy")) + T(" (WDTT, starting)");
    if (Number(w.wg_port) === p) return (ifn || T("a WDTT proxy")) + T(" (WDTT internal WG, starting)");
  }
  // csqtt instances the panel wants but the node has not started yet (csqtt_cfg not yet in snap.csqtt).
  for (const [ifn, c] of Object.entries(_nrec.csqtt_cfg || {})) {
    if (!c) continue;
    if ((snap.csqtt || []).some(x => x && x.iface === ifn)) continue;   // already reported → handled above
    if (Number(String(c.listen || "").split(":").pop()) === p) return (ifn || T("a csqtt proxy")) + T(" (CSQTT, starting)");
  }
  return null;
}
// Validate a port field LIVE (as typed): a human message if empty-but-required is NOT flagged (blank returns null so
// the field isn't red before you type), a non-number, out-of-range, or a collision with another port on this node;
// `own` = ports this iface/proxy already holds (so editing it doesn't flag its own). Drives the inline error + Save gate.
export function portErrMsg(node, port, own) {
  const s = String(port == null ? "" : port).trim();
  if (!s) return null;                                   // empty handled by the field's own required-check, not here
  if (!/^\d+$/.test(s)) return T("Port must be a number.");
  const n = Number(s);
  if (n < 1 || n > 65535) return T("Port must be between 1 and 65535.");
  const h = portHolder(node, n, own);
  return h ? T("Port {port} is already used by {holder} on this node.", { port: n, holder: h }) : null;
}
// next free interface name (<base><n>): highest numeric suffix across ALL interfaces + 1, then skip any taken (mirrors install-node.sh iface_next_index)
export function suggestIface(node, proto) {
  const names = Object.keys((Store.stats[node] || {}).interfaces || {}).concat(pendingIf(node).map(p => p.name));   // include the ones being created
  const base = proto === "wg" ? "wg" : "awg";
  let hi = 0;
  for (const n of names) { const m = /(\d+)$/.exec(n); if (m) hi = Math.max(hi, Number(m[1])); }
  let i = hi + 1;
  while (names.includes(base + i)) i++;
  return base + i;
}
// next free 10.X.0.0/24 tunnel subnet: highest used second octet + 1 (default 10.8) (mirrors install-node.sh next_free_subnet)
// Interface subnets must be UNIQUE across the whole fleet — the mesh routes by subnet, so two nodes on the same
// subnet make return routing ambiguous (a cascaded client's traffic can't be told from the other node's identical
// subnet → black-holed). These helpers collect every user subnet (wg/awg from describe + WDTT wg_addr) so the
// create form suggests a free one and rejects a duplicate. cidr math is done inline (no ipaddress in the browser).
export function cidrNet(cidr) {
  const parts = String(cidr || "").split("/"); const pfx = parseInt(parts[1], 10);
  const oct = String(parts[0]).split(".").map(n => parseInt(n, 10));
  if (oct.length !== 4 || oct.some(n => isNaN(n) || n < 0 || n > 255) || isNaN(pfx) || pfx < 0 || pfx > 32) return null;
  const ipInt = ((oct[0] << 24) >>> 0) + ((oct[1] << 16) >>> 0) + ((oct[2] << 8) >>> 0) + oct[3];
  const mask = pfx === 0 ? 0 : (0xFFFFFFFF << (32 - pfx)) >>> 0;
  return { net: (ipInt & mask) >>> 0, pfx };
}
export function subnetsOverlap(a, b) {
  const A = cidrNet(a), B = cidrNet(b); if (!A || !B) return false;
  const m = Math.min(A.pfx, B.pfx); const mask = m === 0 ? 0 : (0xFFFFFFFF << (32 - m)) >>> 0;
  return ((A.net & mask) >>> 0) === ((B.net & mask) >>> 0);
}
export function fleetSubnets(skipNode, skipIface) {
  const out = [];
  for (const nid of Object.keys(Store.describe || {})) {
    const meta = Store.describe[nid] || {};
    for (const ifn in meta) { const m = meta[ifn]; if (!m || m.system || (nid === skipNode && ifn === skipIface)) continue; if (m.subnet) out.push({ node: nid, iface: ifn, subnet: m.subnet }); }
  }
  for (const nid of Object.keys(Store.stats || {})) {
    for (const w of ((Store.stats[nid] || {}).wdtt || [])) { if (!w || !w.iface || (nid === skipNode && w.iface === skipIface)) continue; if (w.wg_addr) out.push({ node: nid, iface: w.iface, subnet: w.wg_addr }); }
    // csqtt raw-TUN subnets participate in the same fleet-unique check (mesh routes by subnet). tun_addr is the
    // server address (10.X.0.1/24); subnetsOverlap masks to the prefix, so passing the .1 form is fine.
    for (const c of ((Store.stats[nid] || {}).csqtt || [])) { if (!c || !c.iface || (nid === skipNode && c.iface === skipIface)) continue; if (c.tun_addr) out.push({ node: nid, iface: c.iface, subnet: c.tun_addr }); }
  }
  // csqtt instances the panel wants but the node hasn't reported yet (csqtt_cfg not in snap) — so a subnet suggested
  // moments after creating one, or a second back-to-back create, doesn't re-offer a subnet that's about to be taken.
  for (const nrec of (Store.nodes || [])) {
    const nid = nrec.id; if (!nid) continue;
    const reported = new Set(((Store.stats[nid] || {}).csqtt || []).map(c => c && c.iface).filter(Boolean));
    for (const [ifn, c] of Object.entries(nrec.csqtt_cfg || {})) {
      if (!c || reported.has(ifn) || (nid === skipNode && ifn === skipIface)) continue;
      if (c.tun_addr) out.push({ node: nid, iface: ifn, subnet: c.tun_addr });
    }
  }
  return out;
}
export function subnetFleetConflict(subnet, skipNode, skipIface) {
  if (!subnet || !cidrNet(subnet)) return null;
  for (const s of fleetSubnets(skipNode, skipIface)) if (subnetsOverlap(subnet, s.subnet)) return s;
  return null;
}
// The server's own address inside a subnet = the first host (network + 1), keeping the prefix. Used for WDTT,
// whose -wg-addr flag wants the SERVER address (10.8.0.1/24) while the form takes the SUBNET (10.8.0.0/24) — same
// as wg/awg, where the node also puts the server on .1. Idempotent for a value already on .1.
export function subnetServerAddr(subnet) {
  const c = cidrNet(subnet); if (!c) return subnet;
  const ip = (c.net + 1) >>> 0;
  return [(ip >>> 24) & 255, (ip >>> 16) & 255, (ip >>> 8) & 255, ip & 255].join(".") + "/" + c.pfx;
}
export function suggestSubnet(node) {
  const used = new Set();   // FLEET-wide 10.X already taken (any node's user iface / WDTT) → pick the first free one
  for (const s of fleetSubnets(null, null)) { const m = /^10\.(\d{1,3})\./.exec(s.subnet || ""); if (m) used.add(Number(m[1])); }
  for (const p of pendingIf(node)) { const m = /^10\.(\d{1,3})\./.exec(p.subnet || ""); if (m) used.add(Number(m[1])); }
  for (let i = 8; i < 255; i++) if (i !== 255 && !used.has(i)) return "10." + i + ".0.0/24";
  return "10.8.0.0/24";
}

// ── next free WDTT interface name ────────────────────────────────────────────────────────────────
export function nextWdttName(node) {
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  // every name space the node knows about — a WDTT instance shares the interface namespace with wg/awg, so
  // checking only the WDTT ones could propose a name an existing interface already holds
  const used = new Set([...Object.keys(nrec.wdtt_cfg || {}),
                        ...((Store.stats[node] || {}).wdtt || []).map(w => w && w.iface),
                        ...Object.keys(Store.describe[node] || {}),
                        ...Object.keys(nrec.missing_ifaces || {}), ...Object.keys(nrec.ghost_ifaces || {}),
                        ...(nrec.iface_candidates || []).map(c => c && c.name)].filter(Boolean));
  // Numbering starts at 1, never 0 — matching suggestIface (wg1/awg1). wdtt0 in particular is the name every
  // UNPATCHED upstream WDTT compiles in, so suggesting it walks straight into a collision with a foreign server
  // the panel may not even be able to see yet. Only the SUGGESTION avoids it; the field stays free to type.
  for (let i = 1; i < 1000; i++) if (!used.has("wdtt" + i)) return "wdtt" + i;
  return "wdtt1";
}
export function nextCsqttName(node) {
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  // csqtt shares the interface namespace with wg/awg/wdtt — check them all so a suggestion never collides
  const used = new Set([...Object.keys(nrec.csqtt_cfg || {}),
                        ...((Store.stats[node] || {}).csqtt || []).map(c => c && c.iface),
                        ...Object.keys(nrec.wdtt_cfg || {}),
                        ...((Store.stats[node] || {}).wdtt || []).map(w => w && w.iface),
                        // FOREIGN csqtt servers the node found. Same lesson nextWdttName spells out for wdtt0,
                        // and it bites harder here: upstream csqtt hardcodes `csqtt1`, which is precisely the
                        // name this loop suggests first. Proposing it walks onto a live third party's TUN.
                        ...(nrec.csqtt_candidates || []).map(c => c && c.iface),
                        ...Object.keys(Store.describe[node] || {}),
                        ...Object.keys(nrec.missing_ifaces || {}), ...Object.keys(nrec.ghost_ifaces || {}),
                        ...(nrec.iface_candidates || []).map(c => c && c.name)].filter(Boolean));
  for (let i = 1; i < 10000; i++) if (!used.has("csqtt" + i)) return "csqtt" + i;   // csqtt0-9999; start at 1
  return "csqtt1";
}

// Why a name can't be a NEW self-contained instance on this node, or "". Mirrors the server's
// turn_iface_name_error. Creation used to demand `wdtt<N>` / `csqtt<N>`; that pattern was never the node's
// requirement (adoption has always taken foreign names as found) and the panel no longer reads kind off the
// name, so an operator may name their own servers. These are the checks the pattern was standing in for.
export function turnIfaceNameError(node, name, kind) {
  const nm = String(name || "").trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$/.test(nm))
    return T("Name: letters, digits, - and _ (max 15, starting with a letter or digit).");
  if (/^swg_/.test(nm)) return T("Names starting with swg_ are reserved for system mesh links.");
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const other = kind === "wdtt" ? "csqtt" : "wdtt";
  if ((nrec[other + "_cfg"] || {})[nm]) return T("{v1} is already a {v2} instance on this node.", { v1: nm, v2: other.toUpperCase() });
  if ((nrec[kind + "_cfg"] || {})[nm]) return "";                     // editing one we already manage
  if ((Store.describe[node] || {})[nm]) return T("{v1} is already a WireGuard interface on this node.", { v1: nm });
  return "";
}

// ── what a peer publishes to its subscription ────────────────────────────────────────────────────
// A peer's configs come from up to five SOURCES: its own kind per deployment (wg / awg / wdtt / csqtt)
// plus "turn" when a proxy fronts one of its wg/awg interfaces. `sub_hide` (roster) names the sources
// the operator keeps OFF the subscription page — the deployment itself is untouched, only publishing is.
export const SUB_SOURCES = ["wg", "awg", "wdtt", "csqtt", "turn"];
export function peerSubSources(peer) {
  const out = [];
  for (const t of (peer && peer.targets) || []) {
    const ty = targetType(t);
    if (!out.includes(ty)) out.push(ty);
    if (ty === "wdtt" || ty === "csqtt" || out.includes("turn")) continue;
    if (turnProxiesFor(t.node, t.iface).length) out.push("turn");
  }
  return SUB_SOURCES.filter(s => out.includes(s));
}
export const subHidden = peer => ((peer && peer.sub_hide) || []).filter(s => SUB_SOURCES.includes(s));
export const subHides = (peer, src) => subHidden(peer).includes(src);

// A deployment's traffic counters in ONE shape, whatever kind it is. A wg/awg target reads them off the wire
// (`observed`); a keyless one (WDTT / csqtt) has no wire peer, so the node derives the same four numbers from
// its per-password byte counters (`kwXfer`). Every rate/total cell goes through here — a peer's numbers should
// not depend on which kind of server it lives on. Deliberately NOT merged into `observed`: that record also
// means "there is a WireGuard peer here" (handshake age, endpoint, faulty detection), which stays false.
export const tgtXfer = t => (t && (t.observed || t.kwXfer)) || null;
// "Online" for a deployment. wg/awg = the wire handshake age. A keyless server has no handshake, so its
// liveness IS a byte delta over the last poll — the honest age for that is "just now" while it's flowing,
// and unknown otherwise (nothing remembers when a keyless peer was last seen).
export const tgtSeenAge = t => (t && t.observed) ? t.observed.handshake_age : ((t && t.kwXfer && t.online) ? 0 : null);
