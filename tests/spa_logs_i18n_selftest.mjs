/* Self-test — the 1.8.9 qualification's Russian pass: the logs screens, the panel's new sentences and the Disguise-as size (q189
 * SPA-14, SPA-15, SPA-16, PLO-12, SPA-17b, and a line the lead saw live). The merge gate: no English inside a Russian screen, and
 * Russian plurals that agree.
 *
 * [1] SPA-14 — the viewer's "Clock off" chip says its offset in the operator's units ("+3 мин", not "+3 min") and the disk
 *     budget's used figure is a localised number ("12,3 МБ", not "12.3 МБ").
 * [2] SPA-15 — the range download's progress counts its servers through a genitive plural: «ждём 1 из 1 сервера»,
 *     «из 21 сервера», «из 5 серверов» — never «из 1 серверов».
 * [3] PLO-12 — the budget table's tooltips are sentences of ours: "not supported" from the `unsupported` flag, a failed
 *     apply with the node's (or the root helper's) English only as its detail — never that English alone.
 * [4] SPA-16 — the mesh-link sheet's read-only HeaderProtectionKey cell holds its Russian: «свой у каждого», the words of its
 *     interface twin in the same 150 px cell (the old «у каждого линка свой» needed 160 and was cut).
 * [5] SPA-17b — every sentence the panel answers on the log routes, its "Listen on" check, the link door's mesh_awg check and
 *     the torrent-policy check has its Russian line, and none of them is assembled at runtime (each a literal or a perr), so
 *     srvText() can always find it. (The tool behind this, .campaign/i18n-extract.mjs --server, read 25 untranslated + 5
 *     assembled at 52aa9c4.)
 * [6] the Disguise-as size counts its bytes as it counts its packets: «5 пакетов, 226 байт», «1 232 байта» — not «байт: 226»
 *     (seen live on a candidate panel); the Built-in option's size and the big-packet warning the same.
 *
 * [7] the operator-ease pass (OE, 1.8.9) — what it saw in English on Russian screens: the interface's custom endpoint placeholder,
 *     a new peer's address placeholder, the top destinations' "Uncategorised", a settings save's sections in the activity log
 *     («Subscriptions»), "endpoint" in Restore or migrate, the Node-created title («Нода создан»), and a log line's level
 *     (`info`, `err`); and the UP TO DATE pill's tooltip, which promised a click the pill cannot take (pointer-events: none);
 *     and catLabelOf's other bare word, "Custom" (an inline custom rule among the top destinations), seen after the pass.
 *
 * The real js/i18n.js with the real Russian catalog; the real logBudgetState.
 * Run: node tests/spa_logs_i18n_selftest.mjs
 *      --perturb <skew | usedmb | genserver | plo12 | perlink | assembled | ruline | bytes | placeholder | address | uncat |
 *                 settingsname | endpointru | nodecreated | lvlrow | uptodate | customlbl>   one fix undone → RED (exit 0 when caught)
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const MODE = process.argv.includes("--perturb") ? process.argv[process.argv.indexOf("--perturb") + 1] : null;
const PLANTS = {   // file → [anchor, what it was before the fix]
  skew: ["js/logview.js", 'T("{v1} min", { v1: Math.round(Math.abs(s) / 60) }) : T("{v1} s", { v1: Math.abs(s) })',
         'Math.round(Math.abs(s) / 60) + " min" : Math.abs(s) + " s"'],
  usedmb: ["js/screen-settings.js", 'T("{v1} MB", { v1: fmtNum(st.used_mb) })', 'T("{v1} MB", { v1: st.used_mb })'],
  genserver: ["js/logview.js", 'v2: fmtNum(total - done), v3: plural(total, "gen|server") });', 'v2: fmtNum(total - done), v3: fmtNum(total) });'],
  plo12: ["js/screen-settings.js", 'title: T("This server\'s journald has no namespaces, so swg\'s logs cannot have a budget of their own here.") }',
          "title: st.err }"],
  perlink: ["js/lang/ru.js", '"val|per link": "свой у каждого",', '"val|per link": "у каждого линка свой",'],
  assembled: ["swg-panel-server", '**perr("{v1} log viewers are open already", v1=LIVE_REQ_MAX)', '"error": "%d log viewers are open already" % LIVE_REQ_MAX'],
  ruline: ["js/lang/ru.js", '  "Listen on must be an IPv4 address of this node, or Auto": "«Слушать на» — IPv4-адрес этой ноды или «Авто»",\n', ""],
  bytes: ["js/iface.js", 'v2: fmtNum(bytes) + " " + pluralWord(bytes, "byte"), v3:', 'v2: fmtNum(bytes), v3:'],
  placeholder: ["js/iface.js", 'customPlaceholder=${T("IP or hostname — e.g. vpn.example.com")}/>', 'customPlaceholder="IP or hostname — e.g. vpn.example.com"/>'],
  address: ["js/sheets-crud.js", 'placeholder=${s.ipHint || T("address")}', 'placeholder=${s.ipHint || "address"}'],
  uncat: ["js/routing.js", '  if (c === "uncat") return T("Uncategorised");', '  if (c === "uncat") return "Uncategorised";'],
  customlbl: ["js/routing.js", '(String(c).startsWith("custom") ? T("Custom") : c));', '(String(c).startsWith("custom") ? "Custom" : c));'],
  settingsname: ["js/i18n.js", '  if (e && e.verb === "Updated panel settings") return n.split(", ").map(x => T(x)).join(", ");\n', ""],
  endpointru: ["js/lang/ru.js", '"word|endpoint": "эндпоинт",', '"word|endpoint": "endpoint",'],
  nodecreated: ["js/lang/ru.js", '"Node created": "Нода создана",', '"Node created": "Нода создан",'],
  lvlrow: ["js/logview.js", '<span class="lv-lv">${levelShort(lv)}</span>', '<span class="lv-lv">${lv}</span>'],
  uptodate: ["app.js", 'title="${esc(T("This panel is on the latest version"))}"', 'title="${esc(T("On the latest version — click to re-run the updater anyway (repairs this box: reinstalls missing pieces, re-enables services, rebuilds the datapath / AmneziaWG kernel module)"))}"'],
};
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
let I, SS;
try {
  I = await import(pathToFileURL(path.join(ROOT, "js", "i18n.js")).href);
  await I.loadLang();
  SS = await load("js/screen-settings.js");
} finally { for (const p of made) fs.rmSync(p, { force: true }); }
const { T, plural } = I;
check("the Russian catalog is loaded", I.lang() === "ru" && T("Not supported") === "Не поддерживается", T("Not supported"));
const RU = read("js/lang/ru.js"), LV = read("js/logview.js"), SET = read("js/screen-settings.js"), PANEL = read("swg-panel-server");
const ruHas = k => RU.includes(JSON.stringify(k) + ":");

// [1] SPA-14
console.log("\n[1] units and numbers in Russian");
const sk = LV.slice(LV.indexOf("const skewText = s =>"), LV.indexOf("\n", LV.indexOf("const skewText = s =>")));
check("[1] the clock-off chip says its offset through the catalog's units, not a bare \" min\" / \" s\"",
      sk.includes('T("{v1} min"') && sk.includes('T("{v1} s"') && !/"\s*min"|"\s*s"/.test(sk.replace(/T\("\{v1\} (min|s)"/g, "")), sk);
check("[1] …which read «3 мин» and «45 с»", T("{v1} min", { v1: 3 }) === "3 мин" && T("{v1} s", { v1: 45 }) === "45 с",
      [T("{v1} min", { v1: 3 }), T("{v1} s", { v1: 45 })]);
check("[1] the budget's used figure is a localised number: «12,3 МБ»",
      SET.includes('T("{v1} MB", { v1: fmtNum(st.used_mb) })') && T("{v1} MB", { v1: I.fmtNum(12.3) }) === "12,3 МБ",
      T("{v1} MB", { v1: I.fmtNum(12.3) }));

// [2] SPA-15
console.log("\n[2] the range download counts its servers in the genitive");
const forms = [1, 2, 5, 11, 21, 22].map(n => plural(n, "gen|server"));
check("[2] «1 сервера, 2 серверов, 5 серверов, 11 серверов, 21 сервера, 22 серверов»",
      JSON.stringify(forms) === JSON.stringify(["1 сервера", "2 серверов", "5 серверов", "11 серверов", "21 сервера", "22 серверов"]), forms);
check("[2] the progress line: «Читаем …: ждём 1 из 1 сервера.»",
      T("Reading {v1}: waiting on {v2} of {v3}.", { v1: "X", v2: "1", v3: plural(1, "gen|server") }) === "Читаем X: ждём 1 из 1 сервера.",
      T("Reading {v1}: waiting on {v2} of {v3}.", { v1: "X", v2: "1", v3: plural(1, "gen|server") }));
check("[2] …and the viewer passes the count through that plural, in the line and in the bar's label",
      (LV.match(/v3: plural\(total, "gen\|server"\)/g) || []).length === 2 && !LV.includes("of {v3} servers"),
      (LV.match(/v3: [^}]*\}/g) || []).slice(0, 4));

// [3] PLO-12
console.log("\n[3] the budget table's tooltips");
const nsErr = "this system's journald has no namespaces", rsErr = "journald@swg-node did not restart: Job failed";
const su = SS.logBudgetState({ st: { mb: 100, err: nsErr, unsupported: true }, saved: 100 });
const sa = SS.logBudgetState({ st: { mb: 100, err: rsErr }, saved: 100 });
check("[3] \"not supported\": a Russian sentence from the flag — not the node's English",
      su.text === "Не поддерживается" && /пространства имён/.test(su.title) && !su.title.includes(nsErr), su);
check("[3] a failed apply: a Russian sentence with the node's line as its detail, never that line alone",
      sa.text === "Не применён" && sa.title.startsWith("Лимит не удалось применить (") && sa.title.includes(rsErr) && sa.title !== rsErr, sa);

// [4] SPA-16
console.log("\n[4] the link sheet's per-link cell");
const pl = (RU.match(/"val\|per link": "([^"]*)"/) || [])[1], pi = (RU.match(/"val\|per interface": "([^"]*)"/) || [])[1];
check("[4] «val|per link» is no longer than its interface twin, which fits the same read-only cell", pl && pi && pl.length <= pi.length, [pl, pi]);

// [5] SPA-17b
console.log("\n[5] the panel's new sentences");
const SENT = ["{v1} log viewers are open already", "{v1} downloads are being made already", "cannot spool the download: {v1}",
  "no such download", "no such download (made files are kept {v1} min)", "no such request", "no such viewer",
  "nodes and sources are lists", "nodes, sources and levels are lists", "pick at least one server and one source",
  "pick at least one server, one source and one level", "since and until are times in seconds",
  "the range must end after it starts, and span 31 days at most", "invalid body", "busy — send it again",
  "not this request's key", "bad part number", "parts must come in order", "this server's part is closed",
  "the panel cannot spool it", "log_level must be off, error, warning or info", "log_debug must be 0, 3600, 86400 or -1",
  "Listen on must be an IPv4 address of this node, or Auto", "mesh_awg must be an object", "torrent policy must be one of: {v1}"];
const inPanel = SENT.filter(k => !PANEL.includes(JSON.stringify(k)));
check("[5] the corpus is the panel's own (every sentence is in swg-panel-server as written)", !inPanel.length, inPanel);
const noRu = SENT.filter(k => !ruHas(k));
check("[5] every one has its Russian line", !noRu.length, noRu);
const asm = PANEL.split("\n").map((l, i) => [i + 1, l]).filter(([, l]) => !/perr\(/.test(l)
  && (/"error"\s*:\s*f"[^"]*\{/.test(l) || /"error"\s*:\s*"[^"]*%[sdr]/.test(l) || /"error"\s*:\s*(?:"(?:[^"\\]|\\.)*"\s*\+|[^,}]*\+\s*"(?:[^"\\]|\\.)*")/.test(l)));
check("[5] no panel message is assembled at runtime (the extractor's three shapes: f-string, % and +)", !asm.length,
      asm.map(([i, l]) => i + ": " + l.trim().slice(0, 90)));

// [6] the Disguise-as size
console.log("\n[6] the Disguise-as size counts its bytes");
const IFS = read("js/iface.js");
const bw = [1, 2, 5, 21, 226, 1232].map(n => n + " " + I.pluralWord(n, "byte"));
check("[6] «1 байт, 2 байта, 5 байт, 21 байт, 226 байт, 1232 байта»",
      JSON.stringify(bw) === JSON.stringify(["1 байт", "2 байта", "5 байт", "21 байт", "226 байт", "1232 байта"]), bw);
const KEY = "The disguise sends before each handshake: {v1}, {v2} — about {v3} a month for a device that stays connected.";
check("[6] the line reads «… хендшейком: 5 пакетов, 226 байт — около 7.5M в месяц …»",
      T(KEY, { v1: plural(5, "packet"), v2: "226 " + I.pluralWord(226, "byte"), v3: "7.5M" })
        === "Маскировка отправляет перед каждым хендшейком: 5 пакетов, 226 байт — около 7.5M в месяц для постоянно подключённого устройства.",
      T(KEY, { v1: plural(5, "packet"), v2: "226 " + I.pluralWord(226, "byte"), v3: "7.5M" }));
check("[6] …and the picker builds it, the Built-in option's size and the big-packet warning that way (no «байт: N» left)",
      IFS.includes('v2: fmtNum(bytes) + " " + pluralWord(bytes, "byte"), v3:') && IFS.includes('pluralWord(MIMIC_BUILTIN_SIZE[1], "byte")')
      && IFS.includes('v2: fmtNum(big[1].bytes) + " " + pluralWord(big[1].bytes, "byte")') && !/байт: \{v\d\}/.test(RU), "");

// [7] the operator-ease pass
console.log("\n[7] what the operator-ease pass saw in English on Russian screens (OE, 1.8.9)");
let RT7, SRV7 = I;
try {
  RT7 = await load("js/routing.js");
  if (MODE === "settingsname") { SRV7 = await load("js/i18n.js"); await SRV7.loadLang(); }
} finally { for (const p of made) fs.rmSync(p, { force: true }); }
const IF7 = read("js/iface.js"), SC7 = read("js/sheets-crud.js"), APP7 = read("app.js");
check("[7] the interface's custom endpoint placeholder: «IP или имя хоста — например, vpn.example.com»",
      IF7.includes('customPlaceholder=${T("IP or hostname — e.g. vpn.example.com")}/>')
      && T("IP or hostname — e.g. vpn.example.com") === "IP или имя хоста — например, vpn.example.com", "");
check("[7] a new peer's address placeholder: «адрес»", SC7.includes('placeholder=${s.ipHint || T("address")}') && T("address") === "адрес", "");
const unc = (() => { try { return RT7.catLabelOf("uncat"); } catch (e) { return "THREW " + e.message; } })();
check("[7] the top destinations' Uncategorised: «Без категории»", unc === "Без категории", unc);
const cus = (() => { try { return RT7.catLabelOf("custom_ab12"); } catch (e) { return "THREW " + e.message; } })();
check("[7] …and an inline custom rule among them: «Свой», the routing screens' word for it", cus === T("Custom") && cus === "Свой", cus);
const sv = SRV7.srvName({ verb: "Updated panel settings", kind: "panel", name: "Subscriptions, Network, Routing & Blocking" });
check("[7] a settings save in the activity log names its sections in Russian: «Подписки, Сеть, Маршрутизация и блокировка»",
      sv === [T("Subscriptions"), T("Network"), T("Routing & Blocking")].join(", ") && /^Подписки, /.test(sv)
      && SRV7.srvName({ verb: "Created user", kind: "user", name: "Subscriptions" }) === "Subscriptions", sv);
check("[7] an interface's endpoint in Restore or migrate: «эндпоинт», not \"endpoint\"",
      RU.includes('"word|endpoint": "эндпоинт",') && T("word|endpoint") === "эндпоинт", T("word|endpoint"));
check("[7] the Node-created title agrees: «Нода создана»", RU.includes('"Node created": "Нода создана",') && T("Node created") === "Нода создана", T("Node created"));
const lv7 = ["err", "warn", "info", "debug"].map(k => T("lvl|" + k));
check("[7] a log line's level in its column: «ошиб», «пред», «инфо», «отлад» — each within its 5 characters, English unchanged",
      LV.includes('<span class="lv-lv">${levelShort(lv)}</span>') && JSON.stringify(lv7) === JSON.stringify(["ошиб", "пред", "инфо", "отлад"])
      && lv7.every(x => x.length <= 5) && LV.includes('const levelShort = k => ({ err: T("lvl|err"), warn: T("lvl|warn"), info: T("lvl|info"), debug: T("lvl|debug") })[k];'), lv7);
check("[7] the UP TO DATE pill promises no click it cannot take (.upd-uptodate has pointer-events: none): «На этой панели последняя версия»",
      APP7.includes('title="${esc(T("This panel is on the latest version"))}"') && !/click to re-run the updater/.test(APP7)
      && T("This panel is on the latest version") === "На этой панели последняя версия", "");

done(MODE, MODE || "");
