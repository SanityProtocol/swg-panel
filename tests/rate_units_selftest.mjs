/* Self-test: a throughput figure says which unit it is in, and the operator picks which.
 *
 * Reported from the fleet: "running a speedtest at ~200 Mbps, the graphs show 10-20x less numbers". Every
 * hop was measured before anything changed — the node's own `peer_view` (delta/elapsed), /api/node/sync,
 * /api/state, the hrrd history the graphs are drawn from, and the summing the SPA does in the browser —
 * and each carries the rate EXACTLY (`.campaign/rate-truth-rig.py`, ALL PASS). Nothing under-counts.
 *
 * The gap was the wording. The ladder was ["B","K","M","G"] over base-1024, so
 *
 *      512 B/s   ->  "512 B/s"      the B is there while the number cannot be misread
 *   25 MB/s      ->  "23.8 M/s"     …and gone the moment it can
 *
 * and "M/s" is not a unit: on a screen about network speed it reads as megaBITS, because bits are what
 * every speed test, ISP plan and router page quotes. 200 Mbit/s IS 23.8 MB/s — a factor of 8.39.
 *
 * So the panel always names the unit. BYTES stay the default — it is what the node counts and what totals
 * are already shown in, so two figures on one card agree — and BITS are offered for reading the panel
 * against a speed test without dividing by eight.
 *
 * ⚠️ THE BASE FOLLOWS THE UNIT, and that is the part that is not a formatting flag. Bytes are binary;
 * bits are DECIMAL. A speed test's "200" is 200,000,000 bit/s exactly — printing it over a 1024 ladder
 * gives "190.7 Mbit/s", which is the original defect again in a new place. §3 is the check that matters.
 *
 * Run: node tests/rate_units_selftest.mjs
 *   --perturb        drops the unit letter again, RED.
 *   --perturb-base   formats bits over the 1024 ladder, RED.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const PERTURB_BASE = process.argv.includes("--perturb-base");
const SRC = path.join(ROOT, "js", "util.js");
let mod = SRC;
if (PERTURB || PERTURB_BASE) {
  let s = fs.readFileSync(SRC, "utf8");
  const a = PERTURB
    ? 'bits:  { mul: 8, base: 1000, u: ["bit", "kbit", "Mbit", "Gbit", "Tbit"] },'
    : 'bits:  { mul: 8, base: 1000, u: ["bit", "kbit", "Mbit", "Gbit", "Tbit"] },';
  const b = PERTURB
    ? 'bits:  { mul: 8, base: 1000, u: ["b", "k", "M", "G", "T"] },'
    : 'bits:  { mul: 8, base: 1024, u: ["bit", "kbit", "Mbit", "Gbit", "Tbit"] },';
  // ⚠️ ASSERT THE ANCHOR. A replacement that matches nothing leaves a clean pass behind.
  if (!s.includes(a)) { console.log("ANCHOR MISSING: " + a); process.exit(1); }
  s = s.replace(a, b);
  mod = path.join(ROOT, "js", "__perturb_rateunits.js");
  fs.writeFileSync(mod, s);
}
const { rateIn, niceScaleCeilIn, fmtBytes } = await import(pathToFileURL(mod).href);
if (PERTURB || PERTURB_BASE) fs.unlinkSync(mod);

const MBIT = 200;
const BPS = MBIT * 1000 * 1000 / 8;      // 25,000,000 bytes/s — the reported speed test, on the wire

console.log("[1] ⚠️ the speed test the operator is holding up against the panel reconciles EXACTLY");
check("200 Mbit/s of traffic prints as \"200 Mbit/s\"", rateIn(BPS, "bits") === "200 Mbit/s", rateIn(BPS, "bits"));
check("…and the same traffic in bytes is 23.8 MB/s", rateIn(BPS, "bytes") === "23.8 MB/s", rateIn(BPS, "bytes"));
check("…which is one measurement, not two", Math.abs(23.8 * 1024 * 1024 * 8 / 1e6 - MBIT) < 1);

console.log("\n[2] the unit letter survives every magnitude, in both modes");
for (const [v, u] of [[0, "bits"], [512, "bits"], [1536, "bits"], [BPS, "bits"], [1024 ** 3, "bits"],
                      [0, "bytes"], [512, "bytes"], [1536, "bytes"], [BPS, "bytes"], [1024 ** 3, "bytes"]]) {
  const out = rateIn(v, u);
  const ok = u === "bits" ? /(bit|kbit|Mbit|Gbit|Tbit)\/s$/.test(out) : /B\/s$/.test(out);
  check(`${String(v).padStart(11)} in ${u.padEnd(5)} names its unit`, ok, out);
}
check("⚠️ a bare \"M/s\" is never produced", !/\s\d*\.?\d*\s*M\/s$/.test(rateIn(BPS, "bytes")) && !/\sM\/s$/.test(rateIn(BPS, "bits")));

console.log("\n[3] ⚠️ …and the BASE follows the unit — bits are decimal, bytes are binary");
// The check that stops "200 Mbit/s" turning back into "190.7 Mbit/s".
check("bits roll at 1000, not 1024", rateIn(1000 / 8, "bits") === "1.0 kbit/s", rateIn(1000 / 8, "bits"));
check("…so 999 bit/s has NOT rolled", rateIn(999 / 8, "bits") === "999 bit/s", rateIn(999 / 8, "bits"));
check("bytes roll at 1024, not 1000", rateIn(1024, "bytes") === "1.0 KB/s", rateIn(1024, "bytes"));
check("…so 1023 B/s has NOT rolled", rateIn(1023, "bytes") === "1023 B/s", rateIn(1023, "bytes"));
check("…and 1000 B/s is still bytes, not 1 KB/s", rateIn(1000, "bytes") === "1000 B/s", rateIn(1000, "bytes"));

console.log("\n[4] the y-axis ceiling lands on a round figure in the unit it is labelled in");
for (const [v, u] of [[900, "bits"], [40000, "bits"], [BPS, "bits"], [900, "bytes"], [BPS, "bytes"]]) {
  const ceil = niceScaleCeilIn(v / 0.85, u);
  check(`ceiling for ${rateIn(v, u)} covers it`, ceil >= v, `${rateIn(ceil, u)} < ${rateIn(v, u)}`);
  // round = the mantissa is one of the ladder values, so the badge never reads "190.7"
  const m = parseFloat(rateIn(ceil, u));
  check(`…and reads as a ladder value (${rateIn(ceil, u)})`, [1, 5, 10, 50, 100, 500].includes(m), rateIn(ceil, u));
}
// the ceiling is returned in BYTES, like its input — callers scale a byte series with it
check("⚠️ the ceiling is returned on the wire scale (bytes), not the display scale",
      niceScaleCeilIn(BPS / 0.85, "bits") < BPS * 8, "returning bits would scale every series 8x too tall");

console.log("\n[5] ⚠️ the default is BYTES, and it is the same default in all three places");
// Three independent fallbacks — the formatter, the SPA preference, the stored setting — and an operator
// meets whichever answers first. If they disagreed, a fresh panel would render in one unit and re-render in
// another the moment /api/state arrived.
const ui = fs.readFileSync(path.join(ROOT, "js", "ui.js"), "utf8");
const srv = fs.readFileSync(path.join(ROOT, "swg-panel-server"), "utf8");
check("the SPA falls back to bytes", /throughput_units === "bits" \? "bits" : "bytes"/.test(ui), "ui.js rateUnits");
check("…the server's stored default is bytes", /"throughput_units":\s*"bytes"/.test(srv));
check("…and the server only ever stores one of the two",
      /cur\["throughput_units"\] = "bits" if incoming\["throughput_units"\] == "bits" else "bytes"/.test(srv));
check("…and the formatter itself falls back to bytes, so a render before /api/state matches",
      rateIn(BPS, undefined) === "23.8 MB/s" && rateIn(BPS, "furlongs") === "23.8 MB/s",
      `${rateIn(BPS, undefined)} / ${rateIn(BPS, "furlongs")}`);
// …and bits are reachable, which is the whole point of the setting existing.
check("bits are still one value away", rateIn(BPS, "bits") === "200 Mbit/s", rateIn(BPS, "bits"));
const set = fs.readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");
check("…and the operator has a control for it", /value: "bits", label: T\("Bits/.test(set) && /value: "bytes", label: T\("Bytes/.test(set));
check("…with the default listed first", set.indexOf('value: "bytes", label') < set.indexOf('value: "bits", label'));

console.log("\n[6] ⚠️ …and every screen takes `rate` from the one place that knows the preference");
// util.js is LAYER 0 and store.js imports it, so it must not read a setting; ui.js is where dlul already
// solved this. A screen importing the PURE formatter would render in a unit nobody chose.
check("util.js exports the pure pair", /export function rateIn\(/.test(fs.readFileSync(SRC, "utf8"))
      && /export function niceScaleCeilIn\(/.test(fs.readFileSync(SRC, "utf8")));
check("…and no longer exports a preference-free `rate`", !/export function rate\(/.test(fs.readFileSync(SRC, "utf8")));
check("ui.js exports the preference-aware pair", /export const rate = bps =>/.test(ui) && /export const niceScaleCeil = bps =>/.test(ui));
// ⚠️ app.js IS AN SPA FILE AND IT DOES NOT LIVE IN js/. Scanning only that directory left the module that
// mounts every screen outside the rule — it imports from "./js/util.js", one path segment different, which
// no readdir of js/ would ever see.
const scan = [...fs.readdirSync(path.join(ROOT, "js")).filter(f => f.endsWith(".js")).map(f => ["js", f]),
              ["", "app.js"]];
const offenders = [];
for (const [dir, f] of scan) {
  if (dir === "js" && (f === "util.js" || f === "ui.js")) continue;
  const t = fs.readFileSync(path.join(ROOT, dir, f), "utf8");
  for (const m of t.matchAll(/import \{([^}]*)\} from "\.[^"]*util\.js"/g))
    if (/\b(rateIn|niceScaleCeilIn)\b/.test(m[1])) offenders.push(path.join(dir, f));
}
check("⚠️ no screen imports the pure formatter directly", offenders.length === 0, offenders.join(", "));
check("…and the scan actually reaches app.js", scan.some(([d, f]) => f === "app.js"));
// …and nothing imports a name util.js no longer has — that would be a runtime crash on load, not a wrong unit.
const stale = [];
for (const [dir, f] of scan) {
  const t = fs.readFileSync(path.join(ROOT, dir, f), "utf8");
  for (const m of t.matchAll(/import \{([^}]*)\} from "\.[^"]*util\.js"/g))
    if (/(^|[,\s])(rate|niceScaleCeil)(\s*,|\s*$)/.test(m[1])) stale.push(path.join(dir, f));
}
check("⚠️ …and nobody imports `rate`/`niceScaleCeil` from util.js, which no longer exports them",
      stale.length === 0, stale.join(", "));

console.log("\n[7] volumes are a different formatter and are left alone");
// fmtBytes is the TOTAL, not a rate: bits are a RATE convention (an ISP sells Mbit/s and bills GB), and
// widening it would re-flow every Total column. Out of scope on purpose, asserted so a change is a decision.
check("fmtBytes still returns the compact byte form", fmtBytes(25 * 1024 * 1024) === "25.0M", fmtBytes(25 * 1024 * 1024));

done(PERTURB || PERTURB_BASE, PERTURB ? "the unit letter dropped again" : "bits formatted over the 1024 ladder");
