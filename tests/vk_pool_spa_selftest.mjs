// The pool editor's loader and the Check pulse's colour (js/screen-settings.js, S12b) — extracted from the source and run
// against a fake api/bus, as panel_twin_selftest.mjs does (the module imports preact through the importmap).
//   [1] a pool answer older than the one held never replaces it (a GET served before a save, answered after it)
//   [2] a failed fetch is asked again at the next poll — and not at once (no emit, so no render loop)
//   [3] a pool fetch in flight does not swallow a results fetch: each kind has its own
//   [4] an answer is shown only on the row that still holds the URL it was about, and only for its hour
//   [5] a row with no id yet is never "being asked" through the run's current link
// Run: node tests/vk_pool_spa_selftest.mjs            (exit 0 = all pass)
//      node tests/vk_pool_spa_selftest.mjs --perturb  plants each defect in turn; every one must go RED
import { readFileSync } from "fs";
const SRC = readFileSync(new URL("../js/screen-settings.js", import.meta.url), "utf8");
const PLANTS = {
  "take-older": ["if (Array.isArray(d.pool) && (VKP.rev === null || (d.rev || 0) >= VKP.rev))", "if (Array.isArray(d.pool))"],
  "fail-keeps-mark": ["() => { VKP.busy[k] = false; VKP.asked[k] = undefined; });", "() => { VKP.busy[k] = false; });"],
  "fail-emits": ["() => { VKP.busy[k] = false; VKP.asked[k] = undefined; });", "() => { VKP.busy[k] = false; VKP.asked[k] = undefined; bus.emit(); });"],
  "one-busy": ["  if (VKP.busy[k]) return Promise.resolve();", "  if (VKP.busy.pool || VKP.busy.res) return Promise.resolve();"],
  "any-url": ["if (r && r.url === e.url && panelNowS() - r.at < VK_CHECK_FRESH) return r.v;", "if (r && panelNowS() - r.at < VK_CHECK_FRESH) return r.v;"],
  "no-hour": ["if (r && r.url === e.url && panelNowS() - r.at < VK_CHECK_FRESH) return r.v;", "if (r && r.url === e.url) return r.v;"],
  "idless-busy": ["(e.id && ((Store.panelSettings || {}).vk_check || {}).cur === e.id)", "(((Store.panelSettings || {}).vk_check || {}).cur === e.id)"],
};

function build(src) {
  const pick = re => { const m = src.match(re); if (!m) throw new Error("anchor missing: " + re); return m[0]; };
  return pick(/const VKP = \{[^\n]*\n/) + pick(/function vkpTake\(d\) \{[\s\S]*?\n\}\n/) + pick(/function vkpLoad\(what, mark\) \{[\s\S]*?\n\}\n/)
    + pick(/const VK_CHECK_FRESH = [^\n]*\n/) + pick(/function vkCheckTone\(P, e\) \{[\s\S]*?\n\}\n/);
}

async function run(src) {
  const fails = [];
  const check = (name, ok, d) => { console.log((ok ? "  PASS " : "  FAIL ") + name + (ok ? "" : "  — " + JSON.stringify(d))); if (!ok) fails.push(name); };
  let now = 1_800_000_000, emits = 0;
  const calls = [];
  const pending = {};                            // what → resolver of the call in flight
  const api = {
    vkPoolGet: () => new Promise(res => { calls.push("pool"); pending.pool = res; }),
    vkPoolResults: () => new Promise(res => { calls.push("res"); pending.res = res; }),
  };
  const bus = { emit: () => { emits++; } };
  const Store = { panelSettings: { vk_check: {} } };
  const panelNowS = () => now;
  const f = new Function("api", "bus", "Store", "panelNowS", build(src) + "return { VKP, vkpTake, vkpLoad, vkCheckTone };");
  const { VKP, vkpTake, vkpLoad, vkCheckTone } = f(api, bus, Store, panelNowS);
  const tick = () => new Promise(r => setTimeout(r, 0));

  // [1]
  vkpTake({ pool: [{ id: "a", url: "u7" }], rev: 7 });
  vkpTake({ pool: [{ id: "a", url: "u6" }], rev: 6 });
  check("[1] an older pool answer does not replace a newer one", VKP.rev === 7 && VKP.pool[0].url === "u7", [VKP.rev, VKP.pool]);
  // [2]
  emits = 0;
  const p = vkpLoad("pool", 8); pending.pool({ ok: false }); await p; await tick();
  check("[2] a failed fetch is asked again at the next poll", VKP.asked.pool === undefined && !VKP.busy.pool, VKP.asked);
  check("[2] …and not at once (no emit)", emits === 0, emits);
  const p2 = vkpLoad("pool", 8); pending.pool({ ok: true, data: { pool: [], rev: 8, res: {} } }); await p2; await tick();
  check("[2] a fetch that succeeds re-renders once", emits === 1 && VKP.rev === 8, [emits, VKP.rev]);
  // [3]
  calls.length = 0; delete pending.res;
  vkpLoad("pool", 9); vkpLoad("res", 3);
  check("[3] a pool fetch in flight does not swallow a results fetch", calls.join(",") === "pool,res", calls);
  pending.pool({ ok: true, data: { pool: [], rev: 9 } }); if (pending.res) pending.res({ ok: true, data: { res: {} } }); await tick(); await tick();
  // [4]
  const P = { checking: new Set(), res: { a: { at: now - 60, v: "alive", url: "u1" } } };
  check("[4] an answer shows on the row that holds its URL", vkCheckTone(P, { id: "a", url: "u1" }) === "alive");
  check("[4] …not on the row once its URL changed", vkCheckTone(P, { id: "a", url: "u2" }) === "", vkCheckTone(P, { id: "a", url: "u2" }));
  now += 3601;
  check("[4] …and not after its hour", vkCheckTone(P, { id: "a", url: "u1" }) === "", vkCheckTone(P, { id: "a", url: "u1" }));
  // [5]
  Store.panelSettings = { vk_check: { cur: undefined } };
  check("[5] a row with no id is not the run's current link", vkCheckTone(P, { url: "u9" }) === "", vkCheckTone(P, { url: "u9" }));
  return fails;
}

if (process.argv.includes("--perturb")) {
  const missed = [];
  for (const [name, [a, b]] of Object.entries(PLANTS)) {
    if (SRC.split(a).length !== 2) { console.log(`PLANT ${name.padEnd(16)} anchor missing — fix the plant`); missed.push(name); continue; }
    let f;
    try { f = await run(SRC.replace(a, b)); } catch (e) { f = []; console.log("  (crashed: " + e.message + ")"); }
    console.log(`PLANT ${name.padEnd(16)} ${f.length ? "RED  (" + f[0] + ")" : "GREEN — NOT CAUGHT"}`);
    if (!f.length) missed.push(name);
  }
  console.log("perturb:", missed.length ? "MISSED " + missed.join(", ") : "all caught");
  process.exit(missed.length ? 1 : 0);
}
const f = await run(SRC);
console.log(f.length ? `\n${f.length} FAILED` : "\nALL PASS");
process.exit(f.length ? 1 : 0);
