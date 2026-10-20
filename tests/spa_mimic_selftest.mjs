/* Self-test: AmneziaWG "Disguise as" — js/mimic.js and the Edit sheet's picker (docs/AWG-MIMICRY-PLAN.md §2, §3.1, §5).
 *
 * [1] a fixed draw renders exactly the strings P0 put on the wire and every app was shown to read (plan §6.1 — QUIC at DCID 8
 *     and 20, the www.google.com query); copied here because the rig lives in the git-excluded .campaign/, and compared to
 *     the rig too where it is present.
 * [2] every preset, drawn many times: it validates, it is recognized as itself, its size is in its range, only I1 is set,
 *     every random part is at most 1000 bytes, no <c>, at most one <t>.
 * [3] two renders differ only in the drawn parts (the rest is one template), and each drawn part does vary.
 * [4] the recognizer: the built-in set, Off in its three spellings, Custom for anything else (a QUIC with a wrong Length, a
 *     second line, a broken name).
 * [5] the validator: the shapes that make an app refuse the whole config are red, with their reason; sizes are counted.
 * [6] the sheet's flow, end to end without a DOM: pick → the cells → what Save sends → the panel's merge → the record, which
 *     reads back as the pick; a pick that changes nothing sends nothing; a typed cell is Custom.
 * [7] the picker's lines (MimicPick): the options, size, port fit, the built-in note, the Save line and its restart clause, an
 *     error shown alone, the warning for a packet above 1232 bytes.
 * [8] the sheet's wiring: I1–I5 removals never open the "clients break" window; a bad changed line holds Save.
 *
 * The browser half (the sheet fed by a real panel's /api/state) is checked against a running panel — logic only here.
 * Every draw below comes from one SEEDED generator, so a run measures the renderer and never luck (q189 SPA-18: "more than
 * 250 distinct of 300" failed ~2 % of runs on the CSPRNG's draws); the CSPRNG path the sheet uses is checked on its own, by
 * properties every draw must have.
 *
 * Run: node tests/spa_mimic_selftest.mjs
 *      --perturb r1001|c|t2|nl|big|cap|ascii|huge   plants a defect in js/mimic.js (a preset that breaks an app, or a validator that
 *      lets one through) and expects RED.
 *      --perturb fixednib   the QUIC nibble no longer drawn (the draw count kept) — the seeded variety checks still go RED
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done, spa } from "./spa_env.mjs";

const MODE = process.argv.includes("--perturb") ? process.argv[process.argv.indexOf("--perturb") + 1] : null;
const QT = "<r 1000><r ${len - 1000}>";
const PLANTS = {
  r1001: [QT, "<r 1001><r ${len - 1001}>"],                                   // QUIC's tail over amneziawg-go 0.2.15's cap
  c: [QT, "<r 1000><r ${len - 1004}><c>"],                                    // a <c>, gone in 3.x
  t2: ["return set(`<r 2><b 0x", "return set(`<t><t><r 2><b 0x"],             // two <t> in one packet
  nl: ["${DNS_TAIL}>`", "${DNS_TAIL}>\n`"],                                    // a line break in the conf
  big: ["QUIC_MIN = 1200, QUIC_MAX = 1232", "QUIC_MIN = 1500, QUIC_MAX = 1500"], // a 1500-byte I1
  cap: ["if (+arg > MIMIC_TAG_MAX)", "if (false)"],                           // the validator lets <r 1001> through
  ascii: ["const AWG_BAD_CHAR = /[^\\x20-\\x7e]/;", "const AWG_BAD_CHAR = /[\\x00-\\x1f\\x7f]/;"],   // Unicode line breaks let through
  huge: ["return bytes > MIMIC_UDP_MAX ?", "return false ?"],                 // no ceiling on a packet
  fixednib: ["nib = rand(16);", "nib = (rand(16), 0);"],                      // a renderer that stops varying a part
};
if (MODE && !PLANTS[MODE]) { console.log("unknown perturbation " + MODE); process.exit(2); }
let M, made = null;
try {
  if (!MODE) M = await spa("mimic.js");
  else {
    const src = fs.readFileSync(path.join(ROOT, "js", "mimic.js"), "utf8"), [a, b] = PLANTS[MODE];
    if (src.split(a).length !== 2) throw new Error("plant anchor did not match exactly once — this run would measure nothing");
    made = path.join(ROOT, "js", "__perturbed_mimic.js"); fs.writeFileSync(made, src.replace(a, b));
    M = await import(pathToFileURL(made).href);
  }
} finally { if (made) fs.rmSync(made, { force: true }); }
const IF = await spa("iface.js");
const { MIMIC_KEYS, MIMIC_BUILTIN, mimicRender, mimicOf, mimicCheck, mimicFill, mimicAfter, mimicLines } = M;

const queue = a => { let i = 0; return n => { const v = a[i++]; if (v === undefined || v >= n) throw new Error(`draw ${i}: ${v} of ${n}`); return v; }; };
// one seeded generator (mulberry32) for every draw below: the same renders on every run (q189 SPA-18)
const seeded = seed => { let x = seed >>> 0; return n => { x = (x + 0x6D2B79F5) >>> 0; let t = x; t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) % n; }; };
const R = seeded(1889);
// the tags of one line, as the apps read them
const tags = s => [...String(s).matchAll(/<([a-z]+)(?: ([^>]*))?>/g)].map(m => ({ name: m[1], arg: m[2] }));

// [1]
console.log("[1] a fixed draw = what P0 proved on the wire");
const P0 = {   // .campaign/rigs/mimic-p0.sh, run 2 (74/74) and the AmneziaVPN imports, 2026-10-07/08
  QUIC8: "<b 0xc10000000108><r 8><b 0x000044be><r 1000><r 214>",
  QUIC20: "<b 0xc20000000114><r 20><b 0x000044b2><r 1000><r 202>",
  DNSQ: "<r 2><b 0x010000010000000000010377777706676f6f676c6503636f6d00000100010000291000000000000000>",
};
const rig = path.join(ROOT, ".campaign", "rigs", "mimic-p0.sh");
if (fs.existsSync(rig)) {
  const r = fs.readFileSync(rig, "utf8");
  for (const [k, v] of Object.entries(P0)) check(`the rig's ${k} is the string copied here`, r.includes(`${k}='I1 = ${v}'`));
}
// a render that throws is a red check, not a crashed run (a perturbation must report, not die)
const fixed = (id, a) => { try { return mimicRender(id, queue(a)); } catch (e) { return { I1: "THREW " + e.message, I2: "", I3: "", I4: "", I5: "" }; } };
const q8 = fixed("quic", [0, 32, 1]), q20 = fixed("quic", [1, 32, 2]), dq = fixed("dns", [0]);
check("QUIC, DCID 8, 1232 bytes, nibble 1 = QUIC8", q8.I1 === P0.QUIC8, q8.I1);
check("QUIC, DCID 20, 1232 bytes, nibble 2 = QUIC20", q20.I1 === P0.QUIC20, q20.I1);
check("DNS, the first name = DNSQ", dq.I1 === P0.DNSQ, dq.I1);
check("…and I2–I5 are blank in all three", [q8, q20, dq].every(r => MIMIC_KEYS.slice(1).every(k => r[k] === "")));
check("P0's strings read back as QUIC, QUIC, DNS", mimicOf({ I1: P0.QUIC8 }) === "quic" && mimicOf({ I1: P0.QUIC20 }) === "quic" && mimicOf({ I1: P0.DNSQ }) === "dns");
check("P0's sizes: 1232, 1232, 43 bytes", mimicCheck(P0.QUIC8).bytes === 1232 && mimicCheck(P0.QUIC20).bytes === 1232 && mimicCheck(P0.DNSQ).bytes === 43);

// [2]
console.log("\n[2] every preset, drawn 300 times");
const RANGE = { quic: [1200, 1232], dns: [40, 80] };   // plan §2 — literals, not the module's constants
const draws = {};
for (const id of ["off", "quic", "dns"]) {
  const rs = draws[id] = Array.from({ length: 300 }, () => mimicRender(id, R));
  const bad = rs.find(r => !MIMIC_KEYS.every(k => mimicCheck(r[k]).ok));
  check(`${id}: every render validates`, !bad, bad && MIMIC_KEYS.map(k => [k, mimicCheck(bad[k])]));
  const wrong = rs.find(r => mimicOf(r) !== id);
  check(`${id}: every render is recognized as ${id}`, !wrong, wrong && [mimicOf(wrong), wrong.I1]);
  check(`${id}: I2–I5 are blank`, rs.every(r => MIMIC_KEYS.slice(1).every(k => r[k] === "")));
  check(`${id}: no line breaks or control characters anywhere`, rs.every(r => MIMIC_KEYS.every(k => !/[\x00-\x1f\x7f]/.test(r[k]))));
  const t = rs.flatMap(r => tags(r.I1));
  check(`${id}: only <b> <r> <t>`, t.every(x => ["b", "r", "t"].includes(x.name)), [...new Set(t.map(x => x.name))]);
  check(`${id}: every <r> at most 1000`, t.every(x => x.name !== "r" || +x.arg <= 1000), t.filter(x => x.name === "r" && +x.arg > 1000)[0]);
  check(`${id}: at most one <t> a packet`, rs.every(r => tags(r.I1).filter(x => x.name === "t").length <= 1));
  if (RANGE[id]) {
    const sz = rs.map(r => mimicCheck(r.I1).bytes), lo = Math.min(...sz), hi = Math.max(...sz);
    check(`${id}: sizes within ${RANGE[id].join("–")} (seen ${lo}–${hi})`, lo >= RANGE[id][0] && hi <= RANGE[id][1]);
    check(`${id}: the range the picker states holds every size`, lo >= M.MIMIC_PRESETS[id].sizes[0] && hi <= M.MIMIC_PRESETS[id].sizes[1], M.MIMIC_PRESETS[id].sizes);
  }
}
check("off: no line at all", draws.off.every(r => MIMIC_KEYS.every(k => r[k] === "")));
check("built-in: renders the fixed set every generator writes, and reads back as builtin", (r => MIMIC_KEYS.every(k => r[k] === MIMIC_BUILTIN[k]) && mimicOf(r) === "builtin")(mimicRender("builtin")));
// the sheet's own draw — the browser's CSPRNG (mimicRand) — by properties EVERY draw must have, so it can never flake
const csp = ["quic", "dns"].flatMap(id => Array.from({ length: 50 }, () => [id, mimicRender(id)]));
check("the sheet's default draw (the CSPRNG): every render validates, reads back as itself and stays in its stated size range",
      csp.every(([id, r]) => mimicCheck(r.I1).ok && mimicOf(r) === id && mimicCheck(r.I1).bytes >= M.MIMIC_PRESETS[id].sizes[0]
                && mimicCheck(r.I1).bytes <= M.MIMIC_PRESETS[id].sizes[1]), csp.find(([id, r]) => mimicOf(r) !== id));

// [3]
console.log("\n[3] two renders differ only in what is drawn");
const quicTpl = s => s.replace(/^<b 0xc[0-9a-f]00000001(08|14)><r (8|20)><b 0x00004[0-9a-f]{3}><r 1000><r \d+>$/, "Q");
check("QUIC: every render is the one template", draws.quic.every(r => quicTpl(r.I1) === "Q"), draws.quic.find(r => quicTpl(r.I1) !== "Q"));
const qOf = s => /^<b 0xc([0-9a-f])00000001(..)>/.exec(s) || [];
check("QUIC: both DCID lengths drawn", new Set(draws.quic.map(r => qOf(r.I1)[2])).size === 2);
check("QUIC: the first-byte nibble varies", new Set(draws.quic.map(r => qOf(r.I1)[1])).size >= 8);
check("QUIC: the size varies", new Set(draws.quic.map(r => mimicCheck(r.I1).bytes)).size >= 10);
const dnsName = s => /^<r 2><b 0x01000001000000000001((?:[0-9a-f]{2})+)00010001(0000291000000000000000)>$/.exec(s);
check("DNS: every render is the one template around the name", draws.dns.every(r => dnsName(r.I1)));
check("DNS: the name varies", new Set(draws.dns.map(r => (dnsName(r.I1) || [])[1])).size >= 4);
const a = mimicRender("quic", R), b = mimicRender("quic", R);
check("two QUIC renders: same template, and not the same string every time",
      quicTpl(a.I1) === quicTpl(b.I1) && new Set(draws.quic.map(r => r.I1)).size > 250);

// [4]
console.log("\n[4] the recognizer");
check("the built-in set → builtin", mimicOf(MIMIC_BUILTIN) === "builtin");
check("…with surrounding spaces still builtin", mimicOf(Object.fromEntries(MIMIC_KEYS.map(k => [k, " " + MIMIC_BUILTIN[k] + " "]))) === "builtin");
check("no keys, blanks, \"-\" → off", mimicOf({}) === "off" && mimicOf(undefined) === "off"
      && mimicOf(Object.fromEntries(MIMIC_KEYS.map(k => [k, ""]))) === "off" && mimicOf(Object.fromEntries(MIMIC_KEYS.map(k => [k, "-"]))) === "off");
check("the built-in set with one line changed → custom", mimicOf({ ...MIMIC_BUILTIN, I3: "<r 33>" }) === "custom");
check("QUIC with a second line → custom", mimicOf({ I1: P0.QUIC8, I2: "<r 24>" }) === "custom");
check("QUIC whose Length disagrees with its tail → custom", mimicOf({ I1: P0.QUIC8.replace("<r 214>", "<r 215>") }) === "custom");
check("QUIC whose DCID length disagrees with its <r> → custom", mimicOf({ I1: P0.QUIC8.replace("><r 8>", "><r 9>") }) === "custom");
check("QUIC over 1232 bytes → custom", mimicOf({ I1: "<b 0xc10000000108><r 8><b 0x000044c0><r 1000><r 216>" }) === "custom");
check("DNS with a broken name → custom", mimicOf({ I1: P0.DNSQ.replace("0377777706", "0477777706") }) === "custom");
check("DNS in capitals still dns", mimicOf({ I1: P0.DNSQ.toUpperCase().replace("<R 2><B 0X", "<r 2><b 0x") }) === "dns");
check("a lone <r 64> → custom", mimicOf({ I1: "<r 64>" }) === "custom");

// [5]
console.log("\n[5] the validator");
const red = (s, why, what) => { const c = mimicCheck(s); check(`${what} → refused (${why})`, !c.ok && c.why === why, c); };
red("<r 1001>", "big", "<r 1001>");
red("<b 0x01><rc 1001>", "big", "<rc 1001>");
red("<rd 5000>", "big", "<rd 5000>");
red("<c><r 3>", "c", "a <c>");
red("<t><r 4><t>", "t2", "two <t>");
red("<r 3>\n<r 4>", "ctl", "a line break");
red("<r 3>\t<r 4>", "ctl", "a tab between tags");
red("<r 3>\u2028<r 4>", "ctl", "a Unicode line separator");
red("<r 3>\u0085<r 4>", "ctl", "U+0085 (Python splits on it)");
red("\ufeff<r 3>", "ctl", "a leading BOM");
red("<r 3>\u00a0<r 4>", "ctl", "a non-breaking space");
red("<r 1000>".repeat(70), "huge", "a 70,000-byte packet");
check("a trailing tab is trimmed, as the panel trims what it stores", mimicCheck("<r 3>\t").ok && mimicCheck("<r 3>\t").bytes === 3);
check("exactly 65,507 bytes is read", mimicCheck("<r 1000>".repeat(65) + "<r 507>").ok);
check("any other field: printable ASCII only (S1 with a line separator refused, a padded value fine)",
      !M.awgFieldCheck("S1", "28\u2028x").ok && M.awgFieldCheck("S1", " 28 ").ok && !M.awgFieldCheck("I1", "<c>").ok);
red("<r " + "9".repeat(5000) + ">", "long", "a line over 4096 characters");
red("<x 3>", "tag", "an unknown tag");
red("<b 0xabc>", "tag", "<b> with an odd number of hex digits");
red("<b abc>", "tag", "<b> without 0x");
red("<r 3", "tag", "an unclosed tag");
red("junk<r 3>", "tag", "text outside a tag");
check("blank and \"-\" are no packet", mimicCheck("").ok && mimicCheck("").bytes === 0 && mimicCheck(" - ").bytes === 0 && mimicCheck(undefined).ok);
check("the built-in sizes: 73 / 28 / 32 / 41 / 52", MIMIC_KEYS.map(k => mimicCheck(MIMIC_BUILTIN[k]).bytes).join() === "73,28,32,41,52");
check("<r 1000> is the cap, not over it", mimicCheck("<r 1000>").ok);
check("a 1500-byte I1 counts 1500 (the picker warns; plan §5)", mimicCheck("<r 1000><r 500>").ok && mimicCheck("<r 1000><r 500>").bytes === 1500);
check("<rc> and <rd> count like <r>", mimicCheck("<rc 10><rd 5><t>").bytes === 19);
// what every amneziawg-go build read at setconf (swgt, 2026-10-08) must not be refused here — a stricter check would hold Save
// for a line the apps take
check("a space between tags is read (all builds)", mimicCheck("<r 3> <r 4>").ok && mimicCheck("<r 3> <r 4>").bytes === 7);
check("<r 0> is read (all builds)", mimicCheck("<r 0>").ok && mimicCheck("<r 0>").bytes === 0);
check("upper-case hex is read (all builds)", mimicCheck("<b 0xABCD>").ok && mimicCheck("<b 0xABCD>").bytes === 2);

// [6]
console.log("\n[6] the sheet's flow: pick → cells → Save → the panel's merge → the record");
// what EditIfaceSheet's doSave sends for AmneziaWG (non-blank cells, trimmed), and what /api/iface/update does with it (a merge;
// "-" takes the key off)
const sent = draft => Object.fromEntries(Object.entries(draft).map(([k, v]) => [k, String(v ?? "").trim()]).filter(([, v]) => v));
const merge = (rec, body) => { const o = { ...rec }; for (const [k, v] of Object.entries(body)) { if (v === "-") delete o[k]; else o[k] = v; } return o; };
const base = { Jc: "4", Jmin: "40", Jmax: "70", S1: "28", H1: "1-2" };
const recB = { ...base, ...MIMIC_BUILTIN };
for (const [from, rec] of [["built-in", recB], ["QUIC", { ...base, I1: P0.QUIC8 }], ["off", { ...base }]]) {
  for (const id of ["quic", "dns", "off", "builtin"]) {
    const draft = { ...rec, ...mimicFill(mimicRender(id, R), rec) };
    const after = merge(rec, sent(draft));
    check(`${from} → ${id}: the record reads back as ${id}, and is what the sheet said Save would leave`,
          mimicOf(after) === id && JSON.stringify(mimicLines(after)) === JSON.stringify(mimicAfter(draft, rec)), [mimicOf(after), mimicLines(after)]);
    check(`${from} → ${id}: the J/S/H lines are untouched`, Object.keys(base).every(k => after[k] === base[k]));
  }
}
const fOff = mimicFill(mimicRender("off", R), { ...base });
check("Off on an interface with no I lines writes nothing (Save stays dark)", MIMIC_KEYS.every(k => fOff[k] === ""), fOff);
const fQ = mimicFill(mimicRender("quic", R), recB);
check("QUIC over the built-in set: I1 drawn, I2–I5 \"-\" (removed)", fQ.I1.startsWith("<b 0xc") && MIMIC_KEYS.slice(1).every(k => fQ[k] === "-"), fQ);
const fD = mimicFill(mimicRender("dns", R), { ...base, I1: P0.QUIC8 });
check("DNS over QUIC: I2–I5 blank (they were never there)", MIMIC_KEYS.slice(1).every(k => fD[k] === ""), fD);
check("a blank cell keeps the record's line", mimicAfter({ I1: "" }, recB).I1 === MIMIC_BUILTIN.I1);
check("a typed cell over a preset → custom", mimicOf(mimicAfter({ ...draws.quic[0], I1: draws.quic[0].I1 + "<t>" }, {})) === "custom");

// [7]
console.log("\n[7] the picker's lines");
const walk = (n, pick) => { const out = []; const w = x => { if (Array.isArray(x)) x.forEach(w);
  else if (x && typeof x === "object" && x.props) { const r = pick(x); if (r !== undefined) out.push(r); w(x.props.children); } }; w(n); return out; };
const flat = x => Array.isArray(x) ? x.map(flat).join("") : x && typeof x === "object" && x.props ? flat(x.props.children) : x == null || x === false ? "" : String(x);
const lines = n => walk(n, x => x.type === "p" ? { cls: String(x.props.class), t: flat(x.props.children) } : undefined);
const dd = n => walk(n, x => x.props && x.props.options && x.props.onChange ? x.props : undefined)[0];
const pick = o => IF.MimicPick({ port: "51820", peers: 12, restart: false, bad: "", onPick: () => {}, ...o });
const offL = mimicLines({}), qL = mimicLines({ I1: P0.QUIC8 }), bL = mimicLines(MIMIC_BUILTIN);

let v = pick({ eff: qL, was: qL });
let L = lines(v), D = dd(v);
check("the dropdown shows the stored disguise", D && D.value === "quic", D && D.value);
check("its options: Off, QUIC, DNS, Built-in — nothing else while the set is one of them", D && D.options.map(o => o.value).join() === "off,quic,dns,builtin", D && D.options.map(o => o.value));
check("…every one pickable (Built-in is the way back to the set an interface was made with)", D && D.options.every(o => !o.disabled));
check("the closed label is the name alone", D && D.short() === "QUIC (HTTP/3)");
check("size: 1 packet, 1,232 bytes, a monthly figure", L.some(l => /^The disguise sends before each handshake: 1 packet, 1,232 bytes — about [\d.]+M a month/.test(l.t)), L.map(l => l.t));
check("port fit said on 51820", L.some(l => /QUIC looks most natural on UDP 443 — this interface listens on 51820/.test(l.t)));
check("…and not on 443", !lines(pick({ eff: qL, was: qL, port: "443" })).some(l => /most natural/.test(l.t)));
check("what it does / does not", L.some(l => /does not help where only listed addresses are allowed/.test(l.t)));
check("no Save line while nothing changed", !L.some(l => /On Save/.test(l.t)));
v = pick({ eff: qL, was: bL }); L = lines(v);
check("changed from built-in: the Save line counts the devices", L.some(l => /On Save, devices keep working\. .*are disguised as QUIC \(HTTP\/3\)\. Devices on this interface keep their current disguise until re-imported \(12 devices\)/.test(l.t)), L.map(l => l.t));
check("…with no restart clause unless one is due", !L.some(l => /restarts/.test(l.t)));
check("…and with it when it is (3.1, or a line removed)", lines(pick({ eff: qL, was: bL, restart: true })).some(l => /On Save.*The interface restarts; connected devices reconnect/.test(l.t)));
check("to Off: the Off sentence", lines(pick({ eff: offL, was: qL })).some(l => /carry no disguise\. Devices on this interface keep their current one until re-imported \(12 devices\)/.test(l.t)));
check("no device yet: the short sentence", lines(pick({ eff: qL, was: bL, peers: 0 })).some(l => /^Configs issued from now on are disguised as QUIC \(HTTP\/3\)\.$/.test(l.t)));
v = pick({ eff: bL, was: bL }); L = lines(v); D = dd(v);
check("built-in: shown as the fourth option, pickable, with its size", D.value === "builtin" && D.options.length === 4 && !D.options[3].disabled
      && /5 packets, 226 bytes/.test(flat(D.options[3].label)), D.options.map(o => [o.value, o.disabled]));
check("built-in: 5 packets, 226 bytes, and its note", L.some(l => /5 packets, 226 bytes/.test(l.t)) && L.some(l => /every swgPanel install ships/.test(l.t)));
check("built-in: no port line (no protocol to fit)", !L.some(l => /most natural/.test(l.t)));
check("DNS: no port line either — UDP 53 is the node's own resolver on a stock Ubuntu",
      !lines(pick({ eff: mimicLines({ I1: P0.DNSQ }), was: qL })).some(l => /most natural|UDP 53/.test(l.t)));
check("DNS: still named as a disguise in the Save line", lines(pick({ eff: mimicLines({ I1: P0.DNSQ }), was: qL })).some(l => /are disguised as DNS query\./.test(l.t)));
check("no DNS name is a service Russia restricts (YouTube, WhatsApp)", !M.DNS_NAMES.some(n => /youtube|whatsapp/i.test(n)) && M.DNS_NAMES[0] === "www.google.com", M.DNS_NAMES);
v = pick({ eff: offL, was: offL }); L = lines(v);
check("off: no packets, no 'what it does' line", L.some(l => /^No packets before the handshake\.$/.test(l.t)) && !L.some(l => /does not help/.test(l.t)));
const big = mimicLines({ I1: "<r 1000><r 500>" });
L = lines(pick({ eff: big, was: offL }));
check("custom with a 1500-byte I1: the warning", L.some(l => l.cls.includes("warnish") && /I1 is 1,500 bytes — above 1232/.test(l.t)), L);
check("custom: shown as Custom", dd(pick({ eff: big, was: offL })).value === "custom");
check("custom: a fifth row that cannot be picked", (o => o.length === 5 && o[4].value === "custom" && o[4].disabled)(dd(pick({ eff: big, was: offL })).options));
check("built-in picked over QUIC: the Save line names the I1–I5, not a protocol", lines(pick({ eff: bL, was: qL })).some(l => /carry the I1–I5 below\./.test(l.t)));
check("custom: the Save line names the I1–I5, not a preset", lines(pick({ eff: big, was: offL })).some(l => /carry the I1–I5 below\. Devices on this interface keep their current ones until re-imported \(12 devices\)/.test(l.t)));
L = lines(pick({ eff: big, was: offL, bad: "I1: BAD" }));
check("an error is the only line, in red", L.length === 1 && L[0].cls.includes("err") && L[0].t === "I1: BAD", L);

// [8]
console.log("\n[8] the sheet's wiring");
const src = fs.readFileSync(path.join(ROOT, "js", "iface.js"), "utf8");
const i = src.indexOf("export function EditIfaceSheet("), body = src.slice(i, src.indexOf("\nexport function ", i + 10));
check("removing an I line never opens the 'clients break' window", /const awgRm = [^\n]*!MIMIC_KEYS\.includes\(k\)/.test(body));
check("a bad changed line holds Save, and says why", /disabled=\$\{busy [^}]*!!mimErr/.test(body) && /title=\$\{iperr \|\| egressSaveBlock\(eg, emode\) \|\| mimErr/.test(body));
check("the picker sits in the sheet with the record's lines and the form's port", /<\$\{MimicPick\} eff=\$\{mimEff\} was=\$\{mimWas\} port=\$\{port\}/.test(body));
check("every CHANGED field is checked, I lines and the rest (a stored value never blocks an unrelated edit)",
      /const mimBad = isAwg \? AWG_ORDER\.filter\(k => \{ const d = [^\n]*d !== _apT\(k\)/.test(body) && /awgFieldCheck\(k, awg\[k\]\)/.test(body));
check("a \"-\" on a node without datapath.awg.exact holds Save, in the panel's own sentence",
      /\.exact !== 1\)\s*\? T\("\{v1\} cannot hold an empty AmneziaWG field yet/.test(body));
check("…and before the node has reported a set for an interface whose record is not whole",
      /!meta\.awg_exact && !Object\.keys\([^\n]*awg_params\) \|\| \{\}\)\.length/.test(body) && /wait for the node to report this interface/.test(body));
check("…which reaches Save through mimErr", /const mimErr = mimBad \? mimicWhy\(mimBad\[0\], mimBad\[1\]\) : omitNo;/.test(body));
check("the Advanced summary names the disguise", /awgTail \+ " · " \+ MIMIC_TAIL\[mimicOf\(mimEff\)\]\(\)/.test(body));
check("F8: the false 'must re-import after a change' line is gone", !body.includes('"Pushed to the node\'s interface and rendered into configs/QRs. Existing clients must re-import after a change."'));

done(MODE, MODE);
