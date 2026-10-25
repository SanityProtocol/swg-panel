/* Self-test: the exits screen must not report on a config that is no longer there.
 *
 * Two states were lying, and both looked like "the exit broke for a few seconds".
 *
 * 1. `handshake` is an age in seconds with 0 reserved for NEVER — and the node computed that age as
 *    `now - timestamp`, which IS 0 for the whole second after every rekey. One exit in five wore an amber
 *    "this peer has never answered" roughly every 24 seconds. Fixed in the node (the age floors at 1), but
 *    a node is allowed to be older than its panel, so the panel cross-checks: a trace is a request that
 *    crossed this tunnel in the same pass, and traffic cannot have crossed a peer that never answered.
 *
 * 2. `error`, `up` and `handshake` all describe whatever the node last converged on. Between a save and
 *    the node's next pass the row stated the OLD verdict with full confidence. The panel stamps the exit
 *    with a digest of what the node is sent and the node echoes back the one it is working to, so the row
 *    can say "being configured" instead of guessing from a timer.
 *
 * Run: node tests/spa_exithealth_selftest.mjs
 *      --perturb        removes both freshness guards and expects RED.
 *      --perturb-stale  removes ONLY the "is the node still reporting" half — the way `configuring`
 *                       shipped — and expects section [2b] to be what goes red.
 *      --perturb-warp   sends a WARP exit down the PASTED-PROFILE advice, the way it shipped, and expects
 *                       section [4] to be what goes red.
 *
 * 3. And when it does warn, the advice has to be something the operator can act on. "Check the endpoint and
 *    the keys" is true of a pasted profile and FALSE of a WARP account — the panel registered it and the
 *    node holds the key, so neither is on that screen. Measured on nixos: a WARP exit sending 520 KiB and
 *    receiving 0 B, `tcpdump "udp port 2408"` → 12 packets Out / 0 In, while ICMP to the same address
 *    answered in 13 ms and the WARP API answered over HTTPS. A network dropping WARP's datapath, nothing
 *    misconfigured, and one instruction on screen that could not be followed.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

// ⚠️ TWO PERTURBATIONS, NOT ONE, because there are two independent guards and a single mode that removes
// both can only ever prove that SOMETHING went red. `--perturb-stale` strips the staleness half alone —
// which is exactly how this shipped — so section [2b] has to be the thing that catches it.
const PSTALE = process.argv.includes("--perturb-stale");
const PWARP = process.argv.includes("--perturb-warp");
// `--perturb-stalled`: the row ignores the node's dead-tunnel verdict (how it read before `no_traffic` existed)
// and section [5] has to be what goes red.
const PSTALLED = process.argv.includes("--perturb-stalled");
// `--perturb-recover`: the row ignores `back_in` (a tunnel carrying again still reads "passes no traffic") — [5b] goes red.
const PRECOVER = process.argv.includes("--perturb-recover");
// `--perturb-recstale`: a stale node's last `back_in` is still believed — [5b] goes red.
const PRECSTALE = process.argv.includes("--perturb-recstale");
// `--perturb-adopted`: an adopted device's own verdict is ignored (how the adopted arm read before SOCKS5 P2) — [9] goes red.
const PADOPTED = process.argv.includes("--perturb-adopted");
// `--perturb-adstale`: a stale node's last `back_in` is believed for an adopted device — [9] goes red.
const PADSTALE = process.argv.includes("--perturb-adstale");
const PERTURB = PSTALE || PWARP || PSTALLED || PRECOVER || PRECSTALE || PADOPTED || PADSTALE || process.argv.includes("--perturb");
const SRC = path.join(ROOT, "js", "routing.js");
let mod = SRC;

if (PERTURB) {
  let s = fs.readFileSync(SRC, "utf8");
  const guards = PADSTALE ? [
    ["    const fresh = !nodeStale((node || {}).id);", "    const fresh = true;"],
  ] : PADOPTED ? [
    ["    const nt = l.no_traffic;\n", "    const nt = null;\n"],
  ] : PWARP ? [
    // the shipped shape: no provider arm at all, so a WARP exit gets the pasted-profile instruction
    ['said((ex.provider || "warp") === "warp"', "said((false)"],
  ] : PSTALE ? [
    ["&& !nodeStale((node || {}).id))", ")"],
  ] : PRECSTALE ? [
    ["&& !nodeStale((node || {}).id)) return { state: \"recovering\"", ") return { state: \"recovering\""],
  ] : PRECOVER ? [
    ["if (l.no_traffic && Number.isFinite(l.no_traffic.back_in) && !nodeStale((node || {}).id)) return", "if (false) return"],
  ] : PSTALLED ? [
    // ⚠️ ITS OWN ARM. Without one the flag fell through to the default guards below: something went red, and
    // none of it was section [5] — a perturbation of a flag nothing reads.
    ["if (l.no_traffic) return", "if (false) return"],
  ] : [
    ["if (ex.cfg_sig && l.cfg_sig && l.cfg_sig !== ex.cfg_sig && !nodeStale((node || {}).id))", "if (false)"],
    ["l.handshake === 0 && !(l.trace || {}).ip", "l.handshake === 0"],
  ];
  for (const [a, b] of guards) {
    // ⚠️ A PERTURBATION THAT MATCHES NOTHING LEAVES A CLEAN PASS BEHIND. Assert, don't hope.
    if (!s.includes(a)) { console.log("ANCHOR MISSING: " + a); process.exit(1); }
    s = s.replace(a, b);
  }
  // Alongside the original so its own relative imports still resolve.
  mod = path.join(ROOT, "js", "__perturb_exithealth.js");
  fs.writeFileSync(mod, s);
}
const { exitHealth, exitHealthMark } = await import(pathToFileURL(mod).href);
const { Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);
if (PERTURB) fs.unlinkSync(mod);

const NODE = { id: "n1", name: "n1" };
// ⚠️ "STILL REPORTING" IS AN INPUT TO THIS FUNCTION, so the fixture has to state it. `Store.recon.nodeStatus`
// starts empty, which reads as STALE — leave it and every `configuring` check below would pass for the wrong
// reason (the state suppressed, not the state reached), which is a green that measures nothing.
Store.recon.nodeStatus = { n1: "live" };
const ex = (o = {}, live = {}) => ({
  id: "aabbccdd", producer: "imported", provider: "profile", device: "wgx-aabbccdd",
  enabled: true, cfg_sig: "111111111111", ...o,
  live: { device: "wgx-aabbccdd", up: true, handshake: 42, cfg_sig: "111111111111",
          trace: { ip: "203.0.113.7" }, ...live },
});
const st = (o, l) => exitHealth(ex(o, l), NODE).state;

console.log("\n[1] a row waits for the node instead of narrating the config it replaced");
check("in step, it reports normally", st({}, {}) === "ok", st({}, {}));
const busy = exitHealth(ex({ cfg_sig: "222222222222" }, {}), NODE);
check("a saved exit the node has not caught up with is `configuring`", busy.state === "configuring", busy.state);
check("…and it circles rather than warning", busy.tone === "busy" && busy.icon === "refresh",
      busy.tone + "/" + busy.icon);
check("…which draws no fault marker to click",
      (exitHealthMark(busy) || {}).props === undefined || busy.tone === "busy");
check("…and it outranks the PREVIOUS config's failure",
      st({ cfg_sig: "222222222222" }, { error: "wg-quick up failed" }) === "configuring",
      st({ cfg_sig: "222222222222" }, { error: "wg-quick up failed" }));
check("the error is shown again once the node is reporting on THIS config",
      st({}, { error: "wg-quick up failed" }) === "failed", st({}, { error: "wg-quick up failed" }));

console.log("\n[2] and a node that cannot answer the question is not spun for ever");
// The whole fleet would circle on the first poll after a panel upgrade.
check("a node too old to stamp its report is left alone",
      st({ cfg_sig: "222222222222" }, { cfg_sig: undefined }) === "ok",
      st({ cfg_sig: "222222222222" }, { cfg_sig: undefined }));
check("…and so is a stored exit the panel never stamped",
      st({ cfg_sig: "" }, { cfg_sig: "333333333333" }) === "ok",
      st({ cfg_sig: "" }, { cfg_sig: "333333333333" }));
check("a brand-new exit still reads `creating`, not `configuring`",
      st({ cfg_sig: "222222222222" }, { device: "", cfg_sig: "" }) === "creating",
      st({ cfg_sig: "222222222222" }, { device: "", cfg_sig: "" }));

console.log("\n[2b] ⚠️ …and a node that has gone DARK is not narrated as making progress");
// "Applying your changes on the node…" claims work is happening. Save an exit on a node that has stopped
// reporting and nothing is: the spinner would turn for ever AND hide `l.error`, the one reading that still
// means something. Stale, the row falls back to the last thing the node actually said — old, but true.
Store.recon.nodeStatus = { n1: "stale" };
check("an exit edited while its node is offline does NOT spin",
      st({ cfg_sig: "222222222222" }, {}) !== "configuring", st({ cfg_sig: "222222222222" }, {}));
check("…and the previous config's error is visible again, not hidden behind a spinner",
      st({ cfg_sig: "222222222222" }, { error: "wg-quick up failed" }) === "failed",
      st({ cfg_sig: "222222222222" }, { error: "wg-quick up failed" }));
check("…a node the panel has no status for at all is treated the same way",
      (Store.recon.nodeStatus = {}, st({ cfg_sig: "222222222222" }, {})) !== "configuring");
Store.recon.nodeStatus = { n1: "live" };
check("…and a live node still spins, so the guard did not just disable the state",
      st({ cfg_sig: "222222222222" }, {}) === "configuring", st({ cfg_sig: "222222222222" }, {}));

console.log("\n[3] `handshake: 0` means NEVER, and only when nothing crossed the tunnel");
check("up, never answered, nothing got through → amber",
      st({}, { handshake: 0, trace: {} }) === "nohandshake", st({}, { handshake: 0, trace: {} }));
// The rekey second, as an older node still reports it. A request came back through this very tunnel in the
// same pass, so "never answered" is not a possible reading of it.
check("…but a trace that CAME BACK settles it — that is not a peer that never answered",
      st({}, { handshake: 0 }) === "ok", st({}, { handshake: 0 }));
check("a node too old to report a handshake at all keeps the old reading",
      st({}, { handshake: undefined }) === "ok", st({}, { handshake: undefined }));
check("a healthy exit carries no marker at all", exitHealthMark(exitHealth(ex(), NODE)) === null);
check("a real fault still does", exitHealthMark(exitHealth(ex({}, { handshake: 0, trace: {} }), NODE)) !== null);

console.log("\n[4] ⚠️ and the advice names something the operator can actually reach");
// ⚠️ THE TEXT, NOT THE STATE. All three cases below are `nohandshake` — the defect was never in the verdict,
// it was in the one instruction beside it, so a check on `state` measures nothing here.
const why = (o, l) => exitHealth(ex(o, l), NODE).why || "";
const dead = { handshake: 0, trace: {} };
const warpWhy = why({ provider: "warp" }, dead);
check("a WARP exit is not told to check an endpoint it never entered",
      !/Check the endpoint/.test(warpWhy), warpWhy);
check("…it is told what was observed — Cloudflare never answered",
      /Cloudflare never answered/.test(warpWhy), warpWhy);
check("…that there is nothing on this screen to correct",
      /nothing here is yours to correct/i.test(warpWhy), warpWhy);
check("…and given two things it can actually do",
      /pasted profile/.test(warpWhy) && /another node/.test(warpWhy), warpWhy);
// …while the pasted-profile arms are untouched: their advice was right and must stay.
const profWhy = why({ provider: "profile" }, dead);
check("a pasted profile IS still told to check the endpoint and the keys",
      /Check the endpoint and the keys/.test(profWhy), profWhy);
check("…and an AmneziaWG one is told about its obfuscation values",
      /exact obfuscation values/.test(why({ provider: "profile" }, { ...dead, awg: true })),
      why({ provider: "profile" }, { ...dead, awg: true }));
check("all three are still the same VERDICT — only the sentence differs",
      st({ provider: "warp" }, dead) === "nohandshake" && st({ provider: "profile" }, dead) === "nohandshake",
      st({ provider: "warp" }, dead) + "/" + st({ provider: "profile" }, dead));
// The node's own observation still rides along, whichever arm was taken.
check("…and the node's probe error is still appended to the WARP sentence",
      /timed out/.test(why({ provider: "warp" }, { ...dead, trace: { err: "TimeoutError: timed out" } })),
      why({ provider: "warp" }, { ...dead, trace: { err: "TimeoutError: timed out" } }));

// ── [5] a tunnel the NODE judged dead (`no_traffic`) — the row says where the traffic went ──────────────────
// The node reports `no_traffic` only once it has already routed around the tunnel, and what happened to the
// traffic depends on this exit's own kill-switch — so the two sentences must never be worded alike, and the
// verdict must outrank the handshake/trace readings below it (a dead WARP edge can still handshake).
const gone = { no_traffic: { since: 1789482000, why: "TimeoutError: timed out" } };
check("[5] a tunnel the node judged dead reads `stalled`, not ok", st({}, gone) === "stalled", st({}, gone));
check("[5] …even while its last handshake still looks fresh", st({}, { ...gone, handshake: 12 }) === "stalled",
      st({}, { ...gone, handshake: 12 }));
const offWhy = why({ killswitch: false }, gone), onWhy = why({ killswitch: true }, gone);
check("[5] kill-switch OFF: says the traffic is going out through the node's own IP",
      /node's own IP/.test(offWhy) && !/kill-switch is holding/.test(offWhy), offWhy);
check("[5] kill-switch ON: says the kill-switch is holding it, never that it went direct",
      /kill-switch is holding/.test(onWhy) && !/own IP/.test(onWhy), onWhy);
check("[5] …and both say it recovers by itself", /by itself/.test(offWhy) && /by itself/.test(onWhy));
check("[5] a node too old to judge (no `no_traffic`) reads exactly as before", st({}, {}) === "ok", st({}, {}));
check("[5] it draws a clickable fault marker", exitHealthMark(exitHealth(ex({}, gone), NODE)) !== null);

// ── [5b] (S9d) carrying again, the node waits a minute before it routes back — the row says so, not "no traffic" ──
const back = { no_traffic: { since: 1789482000, why: "TimeoutError: timed out", back_in: 37 }, trace: { ip: "198.51.100.9" }, handshake: 12 };
const dinEx = { profile: { listen_port: 51820, address: "10.254.0.0" } };
check("[5b] a judged-dead tunnel carrying again reads `recovering`", st({}, back) === "recovering", st({}, back));
check("[5b] …a dial-in one too, not \"passes no traffic — check NAT\"", (() => { const h = exitHealth(ex(dinEx, back), NODE);
  return h.state === "recovering" && !/check NAT/.test(h.why); })(), exitHealth(ex(dinEx, back), NODE));
check("[5b] …says traffic moves back within a minute — no countdown a 5 s poll cannot age", /within a minute/.test(why({}, back))
      && !/\d+ s\b/.test(why({}, back)), why({}, back));
Store.recon.nodeStatus = { n1: "stale" };
check("[5b] …but a node gone dark is not taken at its last word: the row falls back to the stalled reading",
      st({}, back) === "stalled", st({}, back));
Store.recon.nodeStatus = { n1: "live" };
check("[5b] …progress, not a fault: no clickable \"This exit isn't working\"", exitHealth(ex({}, back), NODE).tone === "busy", exitHealth(ex({}, back), NODE));
check("[5b] …still saying where the traffic is meanwhile", /node's own IP/.test(why({ killswitch: false }, back)), why({ killswitch: false }, back));

// ── [9] (S10 / SOCKS5 P2) an ADOPTED device the node judged dead — a TUN the operator runs, whose proxy died ──────────
// `live` is the device's own report (the panel joins `snap.devexit` by device): state + verdict, never a created exit's row.
const ADN = { id: "n1", name: "n1", exit_candidates: [{ name: "tun9", up: true }] };
const ad = (o = {}, live = {}) => exitHealth({ id: "11223344", producer: "adopted", device: "tun9", enabled: true, ...o, live }, ADN);
const adGone = { state: "dead", no_traffic: { since: 1789482000, why: "TimeoutError: timed out" } };
check("[9] an adopted device the node judged dead reads `stalled`", ad({}, adGone).state === "stalled", ad({}, adGone));
check("[9] …kill-switch OFF: the traffic goes out through the node's own IP", /node's own IP/.test(ad({ killswitch: false }, adGone).why)
      && !/kill-switch is holding/.test(ad({ killswitch: false }, adGone).why), ad({ killswitch: false }, adGone).why);
check("[9] …kill-switch ON: the kill-switch holds it", /kill-switch is holding/.test(ad({ killswitch: true }, adGone).why)
      && !/own IP/.test(ad({ killswitch: true }, adGone).why), ad({ killswitch: true }, adGone).why);
check("[9] …with the node's own words for why", /timed out/.test(ad({}, adGone).why), ad({}, adGone).why);
check("[9] …and a clickable fault marker", exitHealthMark(ad({}, adGone)) !== null);
const adBack = { state: "dead", no_traffic: { ...adGone.no_traffic, back_in: 20 } };
check("[9] carrying again: `recovering`, progress not a fault", ad({}, adBack).state === "recovering" && ad({}, adBack).tone === "busy",
      ad({}, adBack));
Store.recon.nodeStatus = { n1: "stale" };
check("[9] …but a stale node's last back_in is not believed", ad({}, adBack).state === "stalled", ad({}, adBack));
Store.recon.nodeStatus = { n1: "live" };
check("[9] a healthy adopted device (or a node too old to judge it) reads ok as before",
      ad({}, { state: "up" }).state === "ok" && ad({}, {}).state === "ok", [ad({}, { state: "up" }), ad({}, {})]);
check("[9] a device that is not up still reads `down` first",
      exitHealth({ producer: "adopted", device: "tun9", live: adGone }, { id: "n1", exit_candidates: [{ name: "tun9", up: false }] }).state === "down");

done(PERTURB, PADSTALE ? "a stale node's back_in believed for an adopted device" : PADOPTED ? "an adopted device's verdict ignored" : PRECSTALE ? "a stale node's back_in believed" : PRECOVER ? "the recovering state ignored" : PWARP ? "the WARP arm of the never-answered advice removed"
                    : PSTALE ? "the staleness half of `configuring` removed"
                    : PSTALLED ? "the node's dead-tunnel verdict ignored" : "both freshness guards removed");
