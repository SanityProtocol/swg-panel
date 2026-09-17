/* Self-test: a wingsv:// link must FULLY DEFINE the mode — every optional bool stated, on or off.
 *
 * The defect this gates, measured in the field 2026-09-16 on a customer's box. `wingsvConfigBytes` wrote
 * three optional bools only when they were TRUE:
 *
 *     if (csBool(cs, "noObfuscation", false)) turn.no_obfuscation = true;
 *
 * Off ⇒ the property is never assigned ⇒ `pbEncodeMsg` skips it (`v === undefined` → continue) ⇒ the field
 * is ABSENT from the link ⇒ the app keeps whatever it already had. Re-importing does not help: the app
 * updates its existing profile in place. So a device that once received `no_obfuscation: true` stayed
 * obfuscation-off for ever, and turning the setting off in the panel could never reach it.
 *
 * Why that is not cosmetic: with obfuscation off the app sends PLAIN WireGuard. A `wg` interface accepts
 * that happily; an `awg` interface needs the Jc/S1/I1 junk and drops it in SILENCE. The proxy meanwhile
 * negotiates WRAP, creates sessions and logs `online=true` heartbeats, and the interface shows rx 0 with no
 * peer ever reaching a 127.0.0.1 endpoint. Every server-side surface reads healthy; only the link is wrong.
 * It cost about six hours, and decoding the link answered it in two minutes.
 *
 * What this drives, through the REAL artifact builder and a REAL decode of the emitted link:
 *   [1] every optional bool is PRESENT when the setting is off, carrying 0 — the case that was missing
 *   [2] …and present carrying 1 when it is on
 *   [3] use_udp (num 4) is present either way — it always was, and is the pattern the others now copy
 *   [4] STRUCTURAL: every `opt: true` BOOL in WINGSV_SCHEMA.Turn is assigned unconditionally in
 *       wingsvConfigBytes. Enumerated from the schema, not hardcoded, so a bool added later is covered
 *       the day it appears. (The `opt` uint32s — threads, creds_group_size — are deliberately NOT in
 *       scope: zero there means "app default", and omitting them latches nothing.)
 *   [5] both branches carry them — an AmneziaWG peer and a plain WireGuard peer
 *
 * Hermetic: no network, no DOM. turn-artifacts.js is a classic script, so it is evaluated in a vm context
 * with the handful of web globals it touches; node 20 supplies CompressionStream/Response/btoa natively.
 *
 * Run: node tests/wingsv_flags_selftest.mjs        (0 = pass)
 *      --perturb   restores the `if (…) turn.no_obfuscation = true;` form — expects [1] and [4] to go RED.
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import zlib from "node:zlib";
import { ROOT, check, done } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const SRC_PATH = path.join(ROOT, "turn-artifacts.js");
let src = fs.readFileSync(SRC_PATH, "utf8");

if (PERTURB) {
  const fixed = 'turn.no_obfuscation = csBool(cs, "noObfuscation", false);';
  const broken = 'if (csBool(cs, "noObfuscation", false)) turn.no_obfuscation = true;';
  // ⚠️ a perturbation whose anchor has drifted proves nothing and reports green — fail loudly instead.
  if (src.split(fixed).length - 1 !== 1) {
    console.error("perturbation anchor missing or not unique — this gate would FALSE-PASS");
    process.exit(1);
  }
  src = src.replace(fixed, broken);
}

// ── load the classic script ───────────────────────────────────────────────────────────────────────
const ctx = { CompressionStream, Response, btoa, atob, TextEncoder, TextDecoder, console };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(src, ctx, { filename: "turn-artifacts.js" });
const SWGTurn = ctx.SWGTurn;

// ── protobuf reader: just enough to say which fields a message carries ────────────────────────────
function varint(b, i) { let v = 0, s = 0; for (;;) { const x = b[i++]; v |= (x & 0x7f) << s; s += 7; if (!(x & 0x80)) return [v, i]; } }
function fields(b) {
  const out = []; let i = 0;
  while (i < b.length) {
    let k; [k, i] = varint(b, i);
    const num = k >>> 3, wt = k & 7;
    if (wt === 0) { let v; [v, i] = varint(b, i); out.push([num, v]); }
    else if (wt === 2) { let n; [n, i] = varint(b, i); out.push([num, b.subarray(i, i + n)]); i += n; }
    else if (wt === 5) { out.push([num, b.subarray(i, i + 4)]); i += 4; }
    else if (wt === 1) { out.push([num, b.subarray(i, i + 8)]); i += 8; }
    else break;
  }
  return out;
}
/** Decode a wingsv:// link → the Turn sub-message's fields as a Map(num → value). */
function turnFields(link) {
  const b64 = link.replace(/^wingsv:\/\//, "").replace(/-/g, "+").replace(/_/g, "/");
  const raw = Buffer.from(b64 + "=".repeat((4 - (b64.length % 4)) % 4), "base64");
  if (raw[0] !== 0x12) throw new Error("link does not start with the 0x12 marker");
  const proto = zlib.inflateSync(raw.subarray(1));
  const turn = fields(proto).find(([n, v]) => n === 3 && Buffer.isBuffer(v));
  if (!turn) throw new Error("no Turn sub-message in the config");
  return new Map(fields(turn[1]));
}

// ── fixtures ──────────────────────────────────────────────────────────────────────────────────────
const AWG_CONF = [
  "[Interface]", "PrivateKey = qJ8kXk4l8yhWJ7Yy0m2n3o4p5q6r7s8t9u0v1w2x3y4=", "Address = 10.11.0.3/32",
  "DNS = 1.1.1.1", "MTU = 1280", "Jc = 4", "Jmin = 40", "Jmax = 70", "S1 = 107", "S2 = 45",
  "H1 = 276550957-276550972", "H2 = 1662626875-1662626890", "H3 = 2831673535-2831673550",
  "H4 = 3411791847-3411791862", "",
  "[Peer]", "PublicKey = bh0yiucznIoSE7ArHRuEWKKzzUNXpsl7bAK6vAz3PC4=",
  "PresharedKey = Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyMTI=",
  "AllowedIPs = 0.0.0.0/0, ::/0", "Endpoint = 82.24.110.35:51822", "PersistentKeepalive = 25", ""].join("\n");
const WG_CONF = AWG_CONF.split("\n").filter(l => !/^(Jc|Jmin|Jmax|S[1-4]|H[1-4])\s*=/.test(l)).join("\n");
const TP = { service: "vk-turn-proxy-WINGS-N-56004", listen: "82.24.110.35:56004",
             wrap_key: "15c012d61639ed3100000000000000000000000000000000000000000000abcd" };
const VK = ["https://vk.com/call/join/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"];

const link = cs => SWGTurn.artifact(AWG_CONF, TP, VK, cs, VK, "wingsv").buildAsync();

// The optional BOOLS of Turn, read out of the shipped schema rather than restated here.
const OPT_BOOLS = [...src.matchAll(/\{\s*name:\s*"([a-z_0-9]+)",\s*num:\s*(\d+),\s*type:\s*"bool",\s*opt:\s*true\s*\}/g)]
  .map(m => ({ name: m[1], num: +m[2] }));

// ⚠️ EVERY optional bool is driven EXPLICITLY here, use_udp included. Its own default is TRUE
// (`csBool(cs, "useUDP", true)`), so leaving it out of the fixture made "[1] …carries 0" assert against a
// field this test had never asked to be off — the assertion was wrong, the code was right. A fixture that
// does not state what it is testing produces exactly that kind of false red.
const OFF = { useUDP: false, noObfuscation: false, restartOnNetworkChange: false, manualCaptcha: false };
const ON = { useUDP: true, noObfuscation: true, restartOnNetworkChange: true, manualCaptcha: true };

const run = async () => {
  check("[0] the schema still declares optional bools to check", OPT_BOOLS.length >= 4, OPT_BOOLS);

  // ── [1] OFF must still be STATED — the case the defect dropped ──────────────────────────────────
  const off = turnFields(await link(OFF));
  for (const f of OPT_BOOLS) {
    check(`[1] ${f.name} (num ${f.num}) is present when the setting is OFF`, off.has(f.num),
          "absent — an absent field cannot clear what the device already stored");
    if (off.has(f.num)) check(`[1] …and carries 0`, off.get(f.num) === 0, off.get(f.num));
  }

  // ── [2] ON is stated too ────────────────────────────────────────────────────────────────────────
  const on = turnFields(await link(ON));
  for (const f of OPT_BOOLS) {
    check(`[2] ${f.name} carries 1 when the setting is ON`, on.get(f.num) === 1, on.get(f.num));
  }

  // ── [3] use_udp — the field that always did this right ──────────────────────────────────────────
  check("[3] use_udp (num 4) is present either way — the pattern the others now follow",
        off.has(4) && on.has(4), { off: off.has(4), on: on.has(4) });

  // ── [4] STRUCTURAL: no optional bool may be written only-when-true ──────────────────────────────
  const body = src.slice(src.indexOf("function wingsvConfigBytes"), src.indexOf("function wingsvLink"));
  for (const f of OPT_BOOLS) {
    const oneWay = new RegExp("if\\s*\\([^)]*\\)\\s*turn\\." + f.name + "\\s*=", "m").test(body);
    // TWO legitimate shapes, and the first draft of this check knew only one: a STATEMENT
    // (`turn.no_obfuscation = …`) or a MEMBER of the `var turn = { … }` initialiser (`use_udp: …`).
    // Knowing only the statement form reported use_udp — the one field that was always correct — as
    // "never assigned at all", which would have taught a reader to distrust this section.
    const stated = new RegExp("(^|\\n)\\s*turn\\." + f.name + "\\s*=", "m").test(body)
                || new RegExp("(^|[\\n{,])\\s*" + f.name + "\\s*:", "m").test(body);
    check(`[4] ${f.name} is assigned unconditionally, not only-when-true`, stated && !oneWay,
          oneWay ? "written inside an if — it becomes a one-way switch" : "never assigned at all");
  }

  // ── [5] both branches: AmneziaWG and plain WireGuard ────────────────────────────────────────────
  const wg = turnFields(await SWGTurn.artifact(WG_CONF, TP, VK, OFF, VK, "wingsv").buildAsync());
  for (const f of OPT_BOOLS) {
    check(`[5] ${f.name} is stated for a plain-WireGuard peer too`, wg.has(f.num), "absent on the wg branch");
  }
  check("[5] the two branches really are different configs",
        turnFields(await link(OFF)).get(18) === 2 && wg.get(18) === 1,
        { awg_tunnel_mode: off.get(18), wg_tunnel_mode: wg.get(18) });

  done(PERTURB, "no_obfuscation restored to the only-when-true form");
};

run().catch(e => { console.error("harness error:", e && e.stack || e); process.exit(1); });
