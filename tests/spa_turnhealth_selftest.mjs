/* Self-test: a crash-looping turn-proxy reads as crash-looping on EVERY surface, not just the node card.
 *
 * The node reports a loop as `flapping` (restarts in the episode) and `flapping_for` (seconds it has gone
 * on), and the panel's node card turned that into an Issue line. Nothing in the SPA read it: the proxy card
 * and its sheet derived health from `tp.running === false`, and a looping unit reads `active` whenever it is
 * caught between crashes. So one snapshot drew two answers side by side — the node card said "crash-looping"
 * while the proxy card beside it rendered green, and the chips on the interface cards stayed bright.
 *
 * Two readers of one fact is how that happened, so the fix is ONE reader: `turnLooping` / `turnDown` in
 * model.js, used by the card, the sheet and every chip, and the card's text is the node card's own sentence.
 *
 * What this drives, through the REAL modules (TurnCard returns vnodes without a DOM, so what it shows is
 * read directly — no fake DOM agreeing with whatever it is told):
 *   [1] the model: looping is down for every chip, stopped is not looping, unknown is not down
 *   [2] the card: a looping proxy that reads running is dimmed and says crash-looping, with the numbers;
 *       the same proxy without the verdict is not; a loop in its backoff is not called plain "down"
 *   [3] one reader: no `.running` read anywhere in js/ outside model.js — the general form, so the NEXT
 *       reader cannot drift quietly — and the card's sentence is the panel's node-card sentence, verbatim
 *
 * Run: node tests/spa_turnhealth_selftest.mjs
 *      Each arm must redden EXACTLY its own sections — one that reddens another has proved nothing.
 *      --perturb          the card ignores the verdict                         — RED in [2] only
 *      --perturb-reader   the sheet footer reads `tp.running` itself again     — RED in [3] only
 *      --perturb-model    turnDown forgets that a loop is down (bright chips)  — RED in [1] only
 */
import { readFileSync, writeFileSync, unlinkSync, readdirSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";
import { spa, check, FAILS, ROOT } from "./spa_env.mjs";

const ARMS = {
  "--perturb": ["turn.js", "  const looping = turnLooping(tp) && !installing && !queued && !failed;\n",
                "  const looping = false;\n", [2]],
  "--perturb-reader": ["turn.js", "        : ((!turnDown(tp) || looping) && !failed)\n",
                       "        : (tp.running !== false && !failed)\n", [3]],
  "--perturb-model": ["model.js", "(tp.running === false || turnLooping(tp))", "tp.running === false", [1]],
};
const MODE = Object.keys(ARMS).find(a => process.argv.includes(a));

const JS = path.join(ROOT, "js");
const src = {};
for (const f of readdirSync(JS)) if (f.endsWith(".js")) src[f] = readFileSync(path.join(JS, f), "utf8");

let model = await spa("model.js"), turn = await spa("turn.js");
if (MODE) {
  const [file, anchor, repl] = ARMS[MODE];
  // ⚠️ A perturbation whose anchor has drifted proves nothing and reports green.
  if (src[file].split(anchor).length - 1 !== 1) {
    console.log("PERTURB ANCHOR MISSING OR NOT UNIQUE — this run would FALSE-PASS");
    process.exit(1);
  }
  src[file] = src[file].replace(anchor, repl);
  // Written BESIDE the real module so its own relative imports resolve exactly as they do in the browser.
  const tmp = path.join(JS, ".perturbed-" + file.replace(/\.js$/, ".mjs"));
  writeFileSync(tmp, src[file]);
  try {
    const m = await import(pathToFileURL(tmp).href);
    if (file === "model.js") model = m; else turn = m;
  } finally {
    unlinkSync(tmp);
  }
}

const SVC = "vk-turn-proxy-WINGS-N-56004";
const base = { service: SVC, listen: "82.24.110.35:56004", connect: "127.0.0.1:51820" };

// ── [1] the model ─────────────────────────────────────────────────────────────────────────────────
console.log("[1] one verdict, read the same way by every chip");
const { turnLooping, turnDown, turnLoopMins } = model;
const loopUp = { ...base, running: true, flapping: 9, flapping_for: 300 };
check("[1] a loop caught between crashes is looping", turnLooping(loopUp) === true, turnLooping(loopUp));
check("[1] …and down for every chip that greys a proxy, although it reads running", turnDown(loopUp) === true, turnDown(loopUp));
const loopBack = { ...base, running: false, flapping: 9, flapping_for: 900 };
check("[1] a loop in its backoff is looping AND down", turnLooping(loopBack) && turnDown(loopBack));
const stoppedLoop = { ...base, running: false, stopped: true, flapping: 9 };
check("[1] a proxy stopped from the panel is not looping, whatever it did", turnLooping(stoppedLoop) === false);
check("[1] a healthy proxy is neither", !turnLooping({ ...base, running: true }) && !turnDown({ ...base, running: true }));
check("[1] a plainly stopped unit is down but not looping",
      turnDown({ ...base, running: false }) === true && turnLooping({ ...base, running: false }) === false);
check("[1] a proxy the node could not look at is not called down", turnDown({ ...base }) === false, turnDown({ ...base }));
const mins = [undefined, 0, 30, 60, 61, 5400].map(f => turnLoopMins({ ...base, flapping: 3, flapping_for: f }));
check("[1] duration in whole minutes, rounded up, never 0 — and an older node with none reads 1",
      JSON.stringify(mins) === JSON.stringify([1, 1, 1, 1, 2, 90]), JSON.stringify(mins));

// ── [2] the card ──────────────────────────────────────────────────────────────────────────────────
console.log("\n[2] the proxy card says what the node card says");
const flat = (x, out = []) => {
  if (!x || typeof x !== "object") return out;
  if (Array.isArray(x)) { x.forEach(y => flat(y, out)); return out; }
  out.push(x); flat(x.props && x.props.children, out); return out;
};
const card = tp => {
  const v = turn.TurnCard({ node: "n1", tp, nrec: {}, metas: { awg0: { listen_port: 51820 } } });
  const tags = flat(v).filter(n => n.type && n.type.name === "StatusTag").map(n => n.props);
  return { cls: (v && v.props && v.props.class) || "", tags };
};
let c = card(loopUp);
const loopTag = c.tags.find(t => t.label === "crash-looping");
check("[2] a looping proxy that reads running says crash-looping", !!loopTag, JSON.stringify(c.tags.map(t => t.label)));
check("[2] …is dimmed like every proxy that needs attention", / down\b/.test(c.cls), c.cls);
check("[2] …and its detail names the count and the minutes", !!loopTag && /\b9\b/.test(loopTag.msg) && /\b5 min\b/.test(loopTag.msg),
      loopTag && loopTag.msg);
c = card({ ...base, running: true });
check("[2] control: the same proxy with no verdict is not dimmed", !/ down\b/.test(c.cls), c.cls);
check("[2] control: …and says nothing about looping", !c.tags.some(t => t.label === "crash-looping"), JSON.stringify(c.tags));
c = card(loopBack);
check("[2] a loop in its backoff is named as a loop, not as plain down",
      c.tags.some(t => t.label === "crash-looping") && !c.tags.some(t => t.label === "down"), JSON.stringify(c.tags.map(t => t.label)));
c = card({ ...stoppedLoop });
check("[2] a stopped proxy is not called crash-looping", !c.tags.some(t => t.label === "crash-looping"), JSON.stringify(c.tags));

// ── [3] one reader, one sentence ──────────────────────────────────────────────────────────────────
console.log("\n[3] one reader of `running`, and one sentence for the loop");
const strip = s => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");   // comments cannot read anything
const readers = [];
for (const [f, s] of Object.entries(src)) {
  if (f === "model.js") continue;
  strip(s).split("\n").forEach((ln, i) => { if (/\.running\b/.test(ln)) readers.push(f + ":" + (i + 1)); });
}
check("[3] nothing in js/ reads `.running` except model.js", readers.length === 0, readers.join(", "));
check("[3] …and model.js does (a scan that finds no reader anywhere is not a scan)", /\.running\b/.test(strip(src["model.js"])));
const KEY = "{v1}: crash-looping — {v2} restarts in {v3} min";
check("[3] the card's sentence is the node card's sentence, verbatim — on both sides of the wire",
      src["turn.js"].includes('T("' + KEY + '"') && readFileSync(process.env.SWG_PANEL_SERVER || path.join(ROOT, "swg-panel-server"), "utf8").includes('perr("' + KEY + '"'));

// ── verdict ───────────────────────────────────────────────────────────────────────────────────────
const red = [...new Set(FAILS.map(f => +(/^\[(\d+)\]/.exec(f) || [])[1]).filter(Boolean))].sort();
console.log("");
if (MODE) {
  const want = ARMS[MODE][3];
  const ok = JSON.stringify(red) === JSON.stringify(want);
  console.log(ok ? `PERTURB OK (${MODE}) — red in exactly [${want}], ${FAILS.length} checks`
                 : `PERTURB FAILED (${MODE}) — red in [${red}], expected exactly [${want}]`);
  process.exit(ok ? 0 : 1);
}
console.log(FAILS.length ? "FAIL: " + FAILS.join(", ") : "ALL PASS");
process.exit(FAILS.length ? 1 : 0);
