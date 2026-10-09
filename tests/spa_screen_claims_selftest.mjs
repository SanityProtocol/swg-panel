/* Self-test — four screens stop claiming what does not hold (the 1.8.9 qualification's fix round 2, stop rule 1b). Each was
 * measured false on a real box; each sentence now says what is true, in English and in Russian.
 *
 * [1] DN-2 / NLH-2 (V-LOGS F-2) — the Logs level "Off" said "the logs kept so far are deleted". Measured: swg's own journals
 *     go (158 MB + 80 MB → 0 files), but a server's system journal keeps the kernel's P2P guard lines with users' addresses, a
 *     bare-metal turn / relay / WDTT / csqtt unit not restarted since the update still writes there, and in Docker the node
 *     container's own log keeps every earlier line (Debug's SNI host names included) until it is recreated, while a turn
 *     container started before Off keeps logging client addresses. The hint now says what Off deletes and what it cannot, for
 *     the kinds of server the fleet has; the Save confirm line names swg's logs.
 * [2] V-FEAT-B F-2 — "Block everywhere" (and a route through an exit or a node) said torrents from "programs running on it" are
 *     dropped / blocked. Measured: a client on the server itself with encryption forced got 8 peers and 2.3 MB in 60 s with no
 *     counter moving, and µTP on a flow past its 4th packet got through. Both hints now say a program on the server is stopped
 *     only when its handshakes are unencrypted; "Each interface decides" keeps "not checked".
 * [3] V-FEAT-A F5 — the raw fork id "samosvalishe" on operator screens (the node's badge row, the manage sheet's title and its
 *     gear's tooltip; also the pending card, the delete sheet, the front tag's tooltip, the "Connected via" bubbles, a device's
 *     transport row and the flow map's hover). Every one now prints forkLabel — "hackdiaz-dev" — and keeps the id for its
 *     colour; turnLabel (the id) is used nowhere outside turn-catalog.js.
 * [4] V-FEAT-A F6 — the Disguise picker said a restart brings devices back "within a few seconds". Measured 15.2–15.4 s (the
 *     devices still on their old set come back on WireGuard's own rekey after silence): it now says about 15 seconds.
 *
 * The real js/i18n.js with the real Russian catalog; the real modules (screen-settings, screen-nodes, ui, iface, mimic).
 * Run: node tests/spa_screen_claims_selftest.mjs
 *      --perturb <offhint | confirm | p2pblock | p2proute | tag | bubble | title | fewsec>   one fix undone → RED (exit 0 when caught)
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const MODE = process.argv.includes("--perturb") ? process.argv[process.argv.indexOf("--perturb") + 1] : null;
const OLD_OFF = "Nothing is stored, and the logs kept so far are deleted. Failure details go blank: when something breaks, the panel can't say why.";
const PLANTS = {   // file → [anchor, what it was before the fix]
  offhint: ["js/screen-settings.js", 'export const logOffHint = ({ bare, docker }) => [',
            'export const logOffHint = () => T(' + JSON.stringify(OLD_OFF) + '); const _wasOffHint = ({ bare, docker }) => ['],
  confirm: ["js/screen-settings.js", 'T("Logging — off: swg\'s stored logs are deleted")', 'T("Logging — off: the stored logs are deleted")'],
  p2pblock: ["js/screen-settings.js", 'block: T("Torrent traffic is dropped on every way out of this server: its interfaces and traffic other nodes send out through it. A torrent program on the server itself is stopped only when its handshakes are unencrypted — an encrypted one gets through. Web, calls and games are not affected."),',
             'block: T("Torrent traffic is dropped on every way out of this server: its interfaces, traffic other nodes send out through it, and programs running on it. Web, calls and games are not affected."),'],
  p2proute: ["js/screen-settings.js", 'Traffic other nodes send out through this server is blocked. A torrent program on the server itself is stopped only when its handshakes are unencrypted — an encrypted one gets through.", { v1 })',
             'Traffic other nodes send out through this server, and programs running on it, are blocked.", { v1 })'],
  tag: ["js/screen-nodes.js", '" muted" : "")}>${forkLabel(turnFork(tp.service))}</span>`;', '" muted" : "")}>${turnFork(tp.service)}</span>`;'],
  bubble: ["js/ui.js", "const tf = turnFork(r.viaTurn), tn = forkLabel(tf), tc = turnColor(tf),", "const tf = turnFork(r.viaTurn), tn = tf, tc = turnColor(tf),"],
  title: ["js/turn.js", "turnSheetTitle(forkLabel(turnFork(svc)), title)", "turnSheetTitle(turnFork(svc), title)"],
  fewsec: ["js/iface.js", 'T("The interface restarts; connected devices reconnect in about 15 seconds.")',
           'T("The interface restarts; connected devices reconnect within a few seconds.")'],
};
if (MODE && !PLANTS[MODE]) { console.log("unknown perturbation " + MODE); process.exit(2); }
const read = f => {
  let s = fs.readFileSync(path.join(ROOT, f), "utf8");
  if (MODE && PLANTS[MODE][0] === f) {
    if (s.split(PLANTS[MODE][1]).length !== 2) { console.log("PLANT ANCHOR MISSING — this run would measure nothing: " + MODE); process.exit(1); }
    s = s.replace(PLANTS[MODE][1], PLANTS[MODE][2]);
  }
  return s;
};
// a module, or a planted copy of it beside the original (its relative imports, i18n.js included, stay the same instance)
const made = [];
async function load(f) {
  if (!MODE || PLANTS[MODE][0] !== f) return import(pathToFileURL(path.join(ROOT, f)).href);
  const p = path.join(ROOT, path.dirname(f), "__perturbed_" + path.basename(f));
  fs.writeFileSync(p, read(f)); made.push(p);
  return import(pathToFileURL(p).href);
}

globalThis.localStorage = { getItem: k => (k === "swg-lang" ? "ru" : null), setItem: () => {}, removeItem: () => {} };
let I, SS, SN, UI, IF, M, TC;
try {
  I = await import(pathToFileURL(path.join(ROOT, "js", "i18n.js")).href);
  await I.loadLang();
  SS = await load("js/screen-settings.js");
  SN = await load("js/screen-nodes.js");
  UI = await load("js/ui.js");
  IF = await load("js/iface.js");
  M = await load("js/mimic.js");
  TC = await load("js/turn-catalog.js");
} finally { for (const p of made) fs.rmSync(p, { force: true }); }
const { T } = I;
check("the Russian catalog is loaded", I.lang() === "ru" && T("Not supported") === "Не поддерживается", T("Not supported"));
const RU = read("js/lang/ru.js");
const ruHas = k => RU.includes(JSON.stringify(k) + ":");
const JS = Object.fromEntries(fs.readdirSync(path.join(ROOT, "js")).filter(f => f.endsWith(".js") && !f.startsWith("__perturbed_"))
  .map(f => [f, read("js/" + f)]));
// the text a vnode tree renders, and every attribute value in it (a title is read as much as a label)
const flat = x => Array.isArray(x) ? x.map(flat).join("") : x && typeof x === "object" && x.props ? flat(x.props.children)
  : x == null || x === false || x === true ? "" : String(x);
const attrs = x => Array.isArray(x) ? x.flatMap(attrs) : x && typeof x === "object" && x.props
  ? [...Object.entries(x.props).filter(([k, v]) => k !== "children" && typeof v === "string").map(([, v]) => v), ...attrs(x.props.children)] : [];

// ── [1] Off ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
console.log("\n[1] Logs → Off says what it deletes and what it cannot (DN-2 / NLH-2)");
const K = {
  head: "swg's own logs are deleted, and nothing more is kept in them. A server's system journal keeps what it already holds — the kernel's P2P guard lines, with users' addresses, among them.",
  bare: "On bare metal, a turn proxy, relay or WDTT / csqtt server not restarted since the update still writes there.",
  docker: "In Docker, each container's own log keeps its lines until the container is recreated; a turn container started before Off goes on logging until its next start.",
  tail: "Failure details go blank: when something breaks, the panel can't say why.",
};
for (const k of Object.values(K)) check("[1] RU line for “" + k.slice(0, 60) + "…”", ruHas(k), k);
// a helper missing (the tree before the fix) or throwing is a red check, never a crashed run
const offFor = a => { try { return SS.logOffHint(a); } catch (e) { return "THREW " + e.message; } };
const want = parts => parts.map(p => T(K[p])).join(" ");
check("[1] bare metal only: what goes, the system journal it cannot touch, the units not restarted — no Docker sentence",
      offFor({ bare: true, docker: false }) === want(["head", "bare", "tail"]), offFor({ bare: true, docker: false }));
check("[1] Docker only: what goes, the system journal, each container's own log — no bare-metal sentence",
      offFor({ bare: false, docker: true }) === want(["head", "docker", "tail"]), offFor({ bare: false, docker: true }));
check("[1] both kinds: all four, in that order", offFor({ bare: true, docker: true }) === want(["head", "bare", "docker", "tail"]),
      offFor({ bare: true, docker: true }));
check("[1] …in Russian: «Собственные логи swg удаляются», «Системный журнал сервера хранит то, что в нём уже есть», «В Docker»",
      /^Собственные логи swg удаляются/.test(offFor({ bare: true, docker: true })) && /Системный журнал сервера хранит то, что в нём уже есть/.test(offFor({ bare: true, docker: true }))
      && /В Docker собственный лог каждого контейнера/.test(offFor({ bare: true, docker: true })), offFor({ bare: true, docker: true }));
check("[1] the old claim is gone from every screen and from the catalog (\"the logs kept so far are deleted\")",
      !Object.values(JS).some(s => s.includes("the logs kept so far are deleted")) && !RU.includes("the logs kept so far are deleted")
      && !/kept so far/.test(offFor({ bare: true, docker: true })));
const SET = JS["screen-settings.js"];
check("[1] the card asks for the hint with the fleet's kinds: the panel's own (log_panel.docker) and every node's",
      SET.includes("${logOffHint({") && SET.includes('bare: !(ps.log_panel || {}).docker || (Store.nodes || []).some(n => n.kind !== "docker")')
      && SET.includes('docker: !!(ps.log_panel || {}).docker || (Store.nodes || []).some(n => n.kind === "docker")'), "");
check("[1] the Save confirm line names swg's logs, in both languages",
      SET.includes('T("Logging — off: swg\'s stored logs are deleted")') && !SET.includes('"Logging — off: the stored logs are deleted"')
      && T("Logging — off: swg's stored logs are deleted") === "Логирование — выкл: сохранённые логи swg удаляются",
      T("Logging — off: swg's stored logs are deleted"));

// ── [2] torrents ────────────────────────────────────────────────────────────────────────────────────────────────────────
console.log("\n[2] the torrent policy's hints say what happens to a program on the server itself (V-FEAT-B F-2)");
const H = (() => { try { return SS.P2P_HINT(); } catch (e) { return {}; } })();
const routedOf = v => { try { return H.routed(v); } catch (e) { return "THREW " + e.message; } };
const ONLY = "A torrent program on the server itself is stopped only when its handshakes are unencrypted — an encrypted one gets through.";
const BLOCK = "Torrent traffic is dropped on every way out of this server: its interfaces and traffic other nodes send out through it. " + ONLY + " Web, calls and games are not affected.";
const ROUTED = "Torrent traffic may leave only through {v1}. If that way is down, torrent traffic is blocked — never sent out another way. Traffic other nodes send out through this server is blocked. " + ONLY;
check("[2] Block everywhere: a program on the server is stopped only by an unencrypted handshake (and has its Russian)",
      SET.includes("block: T(" + JSON.stringify(BLOCK) + ")") && ruHas(BLOCK) && H.block === T(BLOCK)
      && /только когда её хендшейки не зашифрованы, — зашифрованная проходит/.test(H.block || ""), H.block);
check("[2] a route through an exit or a node: the same, and the route's target in it (and its Russian)",
      SET.includes("T(" + JSON.stringify(ROUTED) + ", { v1 })") && ruHas(ROUTED) && routedOf("WARP") === T(ROUTED, { v1: "WARP" })
      && /через WARP\./.test(routedOf("WARP")) && /зашифрованная проходит/.test(routedOf("WARP")), routedOf("WARP"));
check("[2] …and the card shows that hint for a route", SET.includes("${routed ? P2P_HINT().routed(p2pTarget(curRec, exits, node)) : P2P_HINT()[cur]}"), "");
check("[2] \"Each interface decides\" keeps what was true: programs on the server are not checked",
      /programs running on it, are not checked/.test(SET) && H.iface === T("Only interfaces with Torrents / P2P switched on block it. Traffic other nodes send out through this server, and programs running on it, are not checked."));
const claims = Object.entries(JS).flatMap(([f, s]) => [...s.matchAll(/T\("([^"]*programs running on it[^"]*)"/g)].map(m => [f, m[1]]))
  .filter(([, k]) => !/are not checked/.test(k));
check("[2] no other sentence on any screen says programs running on the server are dropped or blocked", !claims.length, claims);

// ── [3] fork names ──────────────────────────────────────────────────────────────────────────────────────────────────────
console.log("\n[3] a turn proxy's fork is shown by its name, never by the id in its service name (V-FEAT-A F5)");
const SVC = "vk-turn-proxy-samosvalishe-51823", LBL = "hackdiaz-dev";
check("[3] the catalog's fallback names samosvalishe hackdiaz-dev (what every check below expects)",
      TC.forkLabel("samosvalishe") === LBL && TC.turnFork(SVC) === "samosvalishe", TC.forkLabel("samosvalishe"));
const shows = v => { const all = flat(v) + " " + attrs(v).join(" "); return all.includes(LBL) && !/samosvalishe/i.test(flat(v)); };
const tag = SN.TurnTag("n1", { service: SVC, listen: "0.0.0.0:51823" });
check("[3] the node's badge row: «hackdiaz-dev», coloured by the fork's id (tf-samosvalishe)",
      flat(tag) === LBL && /\btf-samosvalishe\b/.test(tag.props.class), [flat(tag), tag.props.class]);
const tc = TC.turnColor("samosvalishe");
const dot = UI.connDot({ online: true, viaTurn: SVC, node: "n1" });
check("[3] a device's \"Connected via\" dot: the name, in the fork's own colour", shows(dot) && attrs(dot).some(a => a.includes(tc)), [flat(dot), attrs(dot)]);
const ep = UI.endpointCell({ via: "turn", viaTurn: SVC, online: true, node: "n1", observed: {} });
check("[3] the endpoint cell's bubble: the name, in the fork's colour", shows(ep) && attrs(ep).some(a => a.includes(tc)), [flat(ep), attrs(ep)]);
const badge = UI.gridStatusBadge({ online: true, viaTurn: SVC, node: "n1", status: "online" }, { status: "online" });
check("[3] the status badge's bubble: the name, in the fork's colour", shows(badge) && attrs(badge).some(a => a.includes(tc)), [flat(badge), attrs(badge)]);
const TU = JS["turn.js"];
check("[3] the manage sheet's title and its gear's tooltip name the fork by forkLabel",
      TU.includes("turnSheetTitle(forkLabel(turnFork(svc)), title)") && TU.includes('T("Version, rollback & server defaults for {v1}", { v1: forkLabel(turnFork(svc)) })')
      && !/turnSheetTitle\(turnFork\(/.test(TU), "");
check("[3] …and so do the delete sheet and a pending card", TU.includes("<${DeleteTurnSheet} node=${node} service=${svc} label=${forkLabel(turnFork(svc))}/>")
      && TU.includes('<span class="ifname">${forkLabel(turnFork(s))}</span>'), "");
check("[3] …the front tag's tooltip, a device's transport row and the flow map's hover",
      JS["sheets-crud.js"].includes('T("Turn-proxy") + (f ? " · " + forkLabel(f) : "")')
      && JS["peer-ui.js"].includes('style=${"--tfc:" + turnColor(turnFork(lt.viaTurn))}>${forkLabel(turnFork(lt.viaTurn))}</span>')
      && JS["screen-overview.js"].includes('return s.kind === "turn" ? forkLabel(s.fork) : s.label || s.kind || id; };')
      && JS["screen-overview.js"].includes('name: sm.kind === "turn" ? forkLabel(sm.fork) : sm.label || sm.kind,'), "");
const tl = Object.entries(JS).filter(([f, s]) => f !== "turn-catalog.js" && /\bturnLabel\b/.test(s)).map(([f]) => f);
check("[3] turnLabel — the fork id of a service name — is used nowhere outside turn-catalog.js", !tl.length, tl);

// ── [4] the Disguise restart ────────────────────────────────────────────────────────────────────────────────────────────
console.log("\n[4] a Disguise change that restarts the interface says about 15 seconds (V-FEAT-A F6)");
const P0Q = "<b 0xc10000000108><r 8><b 0x000044be><r 1000><r 214>";
const lines = v => { const out = []; const w = x => { if (Array.isArray(x)) x.forEach(w);
  else if (x && typeof x === "object" && x.props) { if (x.type === "p") out.push(flat(x.props.children)); w(x.props.children); } }; w(v); return out; };
const pick = o => IF.MimicPick({ port: "443", peers: 4, restart: false, bad: "", onPick: () => {}, ...o });
const qL = M.mimicLines({ I1: P0Q }), bL = M.mimicLines(M.MIMIC_BUILTIN);
const rs = lines(pick({ eff: qL, was: bL, restart: true })).find(l => /Интерфейс перезапустится/.test(l)) || "";
check("[4] the restart clause: «…переподключатся примерно через 15 секунд.»", /Интерфейс перезапустится; подключённые устройства переподключатся примерно через 15 секунд\.$/.test(rs), rs);
check("[4] …its English says about 15 seconds, and no Disguise line says a few seconds",
      JS["iface.js"].includes('T("The interface restarts; connected devices reconnect in about 15 seconds.")')
      && !JS["iface.js"].includes("reconnect within a few seconds") && ruHas("The interface restarts; connected devices reconnect in about 15 seconds."), "");
check("[4] …and no restart, no clause", !lines(pick({ eff: qL, was: bL, restart: false })).some(l => /перезапустится/.test(l)));

done(MODE, MODE || "");
