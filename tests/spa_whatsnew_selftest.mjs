/* Self-test: the update bubble shows the notes of EXACTLY the version on its badge, read when it opens (1.8.9).
 *
 * 1.8.8's publish: the bubble put the previous release's notes under "What's new in 1.8.8-beta" — the panel shipped the
 * changelog's TOP entry in /api/state, and a stale CDN copy made that the old release. Now the bubble asks /api/changelog
 * when it opens and picks the entry by version.
 *
 * [1] nothing in hand → "Loading changelog…" and one request, carrying the badge's version (?want=)
 * [2] the changelog has the version, not at the top → THAT entry's notes and date, not the top one's
 * [3] the changelog lacks the version (a stale copy) → no other release's notes: it points to the changelog
 * [4] …and a copy without it is asked for again, but not on every open (at most every 30 s); one that has it is kept
 * [5] the repaint: the bubble re-renders itself when the changelog lands
 *
 * Run: node tests/spa_whatsnew_selftest.mjs     --perturb top|retry|want   plants one and expects RED.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done, spa } from "./spa_env.mjs";

const MODE = process.argv.includes("--perturb") ? process.argv[process.argv.indexOf("--perturb") + 1] : null;
const PLANTS = {
  top: ["export const changelogEntry = (version) => ((_changelogCache && _changelogCache.entries) || []).find(e => e.version === version) || null;",
        "export const changelogEntry = (version) => ((_changelogCache && _changelogCache.entries) || [])[0] || null;"],
  retry: ["(has || age < CHANGELOG_WANT_RETRY)", "true"],
  want: ['api.changelog(want).then', 'api.changelog().then'],
};
let SN, made = null;
if (MODE) {
  const s = fs.readFileSync(path.join(ROOT, "js", "screen-nodes.js"), "utf8");
  const [a, b] = PLANTS[MODE];
  if (s.split(a).length !== 2) { console.log("ANCHOR MISSING for " + MODE); process.exit(1); }
  made = path.join(ROOT, "js", "__perturb_whatsnew.js"); fs.writeFileSync(made, s.replace(a, b));
}
try { SN = await import(pathToFileURL(made || path.join(ROOT, "js", "screen-nodes.js")).href); }
finally { if (made) { try { fs.unlinkSync(made); } catch (_) { /* gone */ } } }
const { Store, api } = await spa("store.js");

const E = v => ({ version: v, date: v === "1.8.9-beta" ? "2026-10-05" : "2026-09-29", notes: ["**Notes of " + v + ".** text"] });
let answer = { ok: true, data: { current: "1.8.8-beta", entries: [E("1.8.8-beta"), E("1.8.7-beta")] } };
const calls = [];
api.get = p => { calls.push(p); return Promise.resolve(answer); };
const tick = () => new Promise(r => setTimeout(r, 0));

console.log("\n[1] nothing in hand");
Store.latestRemote = "1.8.9-beta";
let repainted = 0;
const h1 = SN.updBubbleHtml(() => { repainted++; });
check("says it is loading", /Loading changelog/.test(h1), h1);
check("one request, carrying the badge's version", calls.length === 1 && /want=1\.8\.9-beta/.test(calls[0]), calls);
await tick(); await tick();

console.log("\n[3] a stale copy (no 1.8.9 in it)");
const h3 = SN.updBubbleHtml(() => {});
check("no other release's notes under 1.8.9", !/Notes of 1\.8\.8/.test(h3) && !/2026-09-29/.test(h3), h3);
check("…it points to the changelog", /See the changelog for what/.test(h3), h3);
console.log("\n[5] the repaint");
check("the bubble was told to repaint when the changelog landed", repainted === 1, repainted);

console.log("\n[4] asked again — but not on every open");
const n0 = calls.length;
SN.updBubbleHtml(() => {}); SN.updBubbleHtml(() => {});
check("two opens within 30 s → no new request", calls.length === n0, calls);
const realNow = Date.now; Date.now = () => realNow() + 31000;
answer = { ok: true, data: { current: "1.8.8-beta", entries: [E("2.0.0-beta"), E("1.8.9-beta"), E("1.8.8-beta")] } };
SN.updBubbleHtml(() => {}); await tick(); await tick();
check("31 s on → asked again", calls.length === n0 + 1, calls);

console.log("\n[2] the version is there, not at the top");
const h2 = SN.updBubbleHtml(() => {});
check("1.8.9's own notes and date", /Notes of 1\.8\.9/.test(h2) && /2026-10-05/.test(h2), h2);
check("…not the top entry's", !/Notes of 2\.0\.0/.test(h2), h2);
const n1 = calls.length;
Date.now = () => realNow() + 31000 + 60000;
SN.updBubbleHtml(() => {}); await tick();
check("a copy that has it is kept (no request a minute later)", calls.length === n1, calls);
Date.now = realNow;
done(!!MODE, MODE);
