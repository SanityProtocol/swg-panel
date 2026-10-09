/* Self-test — the 1.8.9 qualification's Russian pass over the logs screens and the panel's new sentences (q189 SPA-14, SPA-15,
 * SPA-16, PLO-12, SPA-17b). The merge gate: no English inside a Russian screen, and Russian plurals that agree.
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
 *
 * The real js/i18n.js with the real Russian catalog; the real logBudgetState.
 * Run: node tests/spa_logs_i18n_selftest.mjs
 *      --perturb <skew | usedmb | genserver | plo12 | perlink | assembled | ruline>   one fix undone → RED (exit 0 when caught)
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

done(MODE, MODE || "");
