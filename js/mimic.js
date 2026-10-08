/* mimic.js — what AmneziaWG's I1–I5 packets look like (docs/AWG-MIMICRY-PLAN.md §2).
 *
 * I1–I5 are sent, in order, before every handshake a side starts; the other side drops them, so a client's set may differ
 * from the server's and from every other client's (F1, proven on the wire: plan §6.1). A preset is `render(rand)` → the five
 * strings: what a real client keeps for a session is drawn here ONCE and baked into `<b>`; what it varies per packet is `<r>`.
 *
 * Only `<b> <r> <t>` are used. Each line is read by every app that imports the config, and an app that cannot read one line
 * refuses the whole config (F9): amneziawg-go 0.2.15 refuses any `<r>/<rc>/<rd>` over 1000 bytes (so QUIC's tail is split),
 * and 3.x dropped `<c>`. `mimicCheck` refuses exactly those shapes.
 *
 * No preset name is stored anywhere: `mimicOf` reads the preset back from the five stored strings, so what the sheet shows is
 * always what the record holds (memory new-record-field-must-be-published).
 *
 * Pure: no i18n, no DOM. The Edit sheet words what these return.
 */
export const MIMIC_KEYS = ["I1", "I2", "I3", "I4", "I5"];   // i18n-keys: conf key names, as the conf spells them

// rand(n) → an integer in [0, n). Fresh draws come from the browser's CSPRNG; the gate passes its own.
export const mimicRand = n => crypto.getRandomValues(new Uint32Array(1))[0] % n;

const hex = (v, bytes) => v.toString(16).padStart(bytes * 2, "0");
const set = I1 => ({ I1, I2: "", I3: "", I4: "", I5: "" });

// QUIC v1 client Initial, shape only (RFC 9000 §17.2.2): first byte 0xc0 | low nibble (header protection makes it look
// random), version 1, DCID length + a DCID drawn per packet, SCID length 0, token length 0, a 2-byte varint Length covering
// the rest, then random bytes. 1200–1232 bytes: a client Initial is at least 1200 (§14.1); 1232 fits any 1280 path.
const QUIC_DCID = [8, 20], QUIC_MIN = 1200, QUIC_MAX = 1232;
function renderQuic(rand) {
  const dcid = QUIC_DCID[rand(QUIC_DCID.length)], total = QUIC_MIN + rand(QUIC_MAX - QUIC_MIN + 1), nib = rand(16);
  const len = total - (1 + 4 + 1 + dcid + 1 + 1 + 2);   // what follows the Length field
  return set(`<b 0x${hex(0xc0 | nib, 1)}00000001${hex(dcid, 1)}><r ${dcid}><b 0x0000${hex(0x4000 | len, 2)}><r 1000><r ${len - 1000}>`);
}

// A standard DNS query: a random ID per packet, RD set, one question (type A, class IN) and an EDNS0 OPT record (4096-byte
// UDP size). The name is drawn once from names every network resolves all day — none typeable (plan §2, review round 2) and
// none a censor restricts where swgPanel is used (YouTube and WhatsApp are throttled in Russia: a query for one draws the very
// attention the disguise is there to avoid — analysis round 2026-10-08).
export const DNS_NAMES = ["www.google.com", "www.apple.com", "www.microsoft.com", "www.cloudflare.com", "www.wikipedia.org",
  "www.yandex.ru", "www.amazon.com", "www.samsung.com"];   // i18n-keys: host names
const DNS_HEAD = "01000001000000000001", DNS_TAIL = "00010001" + "0000291000000000000000";   // after the <r 2> ID: RD, one question, one additional · A IN · the OPT record
const qname = name => name.split(".").map(l => hex(l.length, 1) + [...l].map(c => hex(c.charCodeAt(0), 1)).join("")).join("") + "00";
function renderDns(rand) {
  return set(`<r 2><b 0x${DNS_HEAD}${qname(DNS_NAMES[rand(DNS_NAMES.length)])}${DNS_TAIL}>`);
}

// What every swgPanel generator writes for a new interface (F2): the same five strings on every server. Offered as a pick
// too — the way back to the set an interface was made with.
export const MIMIC_BUILTIN = { I1: "<b 0xc000000001><r 64><t>", I2: "<r 24><t>", I3: "<r 32>", I4: "<b 0xc000000001><r 32><t>", I5: "<t><r 48>" };

/* The presets the picker offers, in its order. `port` = where the protocol is normally seen and a node can usually listen
   (the port-fit hint) — QUIC only: UDP 53 is held by the node's own resolver on a stock Ubuntu (systemd-resolved; a wildcard
   bind there fails — measured on swgt 2026-10-08), so moving an interface there would stop it. `sizes` = the smallest and
   largest packet a render can give, in bytes. */
const dnsBytes = name => 2 + DNS_HEAD.length / 2 + qname(name).length / 2 + DNS_TAIL.length / 2;
export const MIMIC_PRESETS = {
  off: { render: () => set("") },
  quic: { render: renderQuic, port: 443, sizes: [QUIC_MIN, QUIC_MAX] },
  dns: { render: renderDns, sizes: [Math.min(...DNS_NAMES.map(dnsBytes)), Math.max(...DNS_NAMES.map(dnsBytes))] },
  builtin: { render: () => ({ ...MIMIC_BUILTIN }) },
};
export const mimicRender = (id, rand = mimicRand) => MIMIC_PRESETS[id].render(rand);

const val = (awg, k) => { const v = String((awg || {})[k] ?? "").trim(); return v === "-" ? "" : v; };   // "-" = no such line

const RE_QUIC = /^<b 0xc[0-9a-f]00000001(08|14)><r (8|20)><b 0x00004([0-9a-f]{3})><r 1000><r (\d+)>$/i;
const RE_DNS = new RegExp(`^<r 2><b 0x${DNS_HEAD}((?:[0-9a-f]{2})+)${DNS_TAIL}>$`, "i");
const isQname = h => {   // labels of 1–63 bytes, ending in the root label
  for (let i = 0; i < h.length;) { const n = parseInt(h.slice(i, i + 2), 16); if (n === 0) return i + 2 === h.length;
    if (n > 63 || i + 2 + n * 2 > h.length) return false; i += 2 + n * 2; }
  return false;
};
function isQuic(s) {
  const m = RE_QUIC.exec(s); if (!m) return false;
  const dcid = parseInt(m[1], 16), len = parseInt(m[3], 16), total = 1 + 4 + 1 + dcid + 1 + 1 + 2 + len;
  return +m[2] === dcid && 1000 + +m[4] === len && total >= QUIC_MIN && total <= QUIC_MAX;
}
function isDns(s) {
  const m = RE_DNS.exec(s);
  return !!m && isQname(m[1]);
}

/* The Edit sheet's three views of I1–I5 (`rec` = the record's awg_params, `draft` = the cells):
   the record's lines ("" = none) · the cells a pick writes — the preset's line, else "-" where the record holds one (removed),
   else blank (it never had one, so nothing changes) · the lines Save would leave — the update merges, so a blank cell keeps
   the record's line and "-" takes it off. */
export const mimicLines = rec => Object.fromEntries(MIMIC_KEYS.map(k => [k, val(rec, k)]));
export const mimicFill = (I, rec) => Object.fromEntries(MIMIC_KEYS.map(k => [k, I[k] || (val(rec, k) ? "-" : "")]));
export const mimicAfter = (draft, rec) => Object.fromEntries(MIMIC_KEYS.map(k => {
  const d = String((draft || {})[k] ?? "").trim(); return [k, d === "-" ? "" : d || val(rec, k)]; }));

/* Which preset these five strings are: "off" | "quic" | "dns" | "builtin" | "custom". Blank and "-" are both no line. */
export function mimicOf(awg) {
  const v = MIMIC_KEYS.map(k => val(awg, k));
  if (v.every(x => !x)) return "off";
  if (MIMIC_KEYS.every((k, i) => v[i] === MIMIC_BUILTIN[k])) return "builtin";
  if (v.slice(1).some(Boolean)) return "custom";
  return isQuic(v[0]) ? "quic" : isDns(v[0]) ? "dns" : "custom";
}

/* One I line: is it something every app reads, and how many bytes does it put on the wire?
   → { ok: true, bytes } | { ok: false, why, tag? }. A blank or "-" line is ok and 0 bytes (no packet).
   why: "ctl" a character outside printable ASCII (a line break, a tab, a Unicode space or line separator) · "long" over 4096
        characters · "tag" not a tag this grammar knows · "c" a <c> (gone in AmneziaWG 3.x) · "big" a random part over 1000
        bytes · "t2" <t> twice in one packet · "huge" more than one UDP packet carries (65,507 bytes).
   ASCII whitespace at the ends is trimmed first, as the panel's sanitize trims what it stores. Every AmneziaWG value is
   printable ASCII, and the node's own tools split a conf on Unicode line breaks (Python's splitlines), so nothing else may
   stay in a line. Twin: swg-panel-server awg_i_check (tests/awg_i_check_selftest.py). */
export const MIMIC_TAG_MAX = 1000, MIMIC_LINE_MAX = 4096, MIMIC_UDP_MAX = 65507;
const awgTrim = v => String(v ?? "").replace(/^[ \t\n\r\f\v]+|[ \t\n\r\f\v]+$/g, "");
const AWG_BAD_CHAR = /[^\x20-\x7e]/;
export function mimicCheck(s) {
  s = awgTrim(s);
  if (AWG_BAD_CHAR.test(s)) return { ok: false, why: "ctl" };
  if (s === "" || s === "-") return { ok: true, bytes: 0 };
  if (s.length > MIMIC_LINE_MAX) return { ok: false, why: "long" };
  let bytes = 0, t = 0;
  // spaces between tags and <r 0> are read by every build (measured 2026-10-08: amneziawg-go 0.2.15, 3.1.20260828, the pinned
  // 0.0.20250522); odd hex is refused by 3.x and the pinned build, two <t> by 0.2.15, <c> by 3.x and the pinned build
  for (let rest = s; (rest = rest.replace(/^ +/, ""));) {
    const m = /^<([a-z]+)(?: ([^<>]*))?>/.exec(rest);
    if (!m) return { ok: false, why: "tag", tag: (rest.match(/^<[^>]*>?/) || [rest.slice(0, 16)])[0] };
    const [whole, name, arg] = m;
    rest = rest.slice(whole.length);
    if (name === "c") return { ok: false, why: "c", tag: whole };
    if (name === "t" && arg === undefined) { if (++t > 1) return { ok: false, why: "t2", tag: whole }; bytes += 4; continue; }
    if (name === "b" && /^0x(?:[0-9a-fA-F]{2})+$/.test(arg || "")) { bytes += (arg.length - 2) / 2; continue; }
    if (["r", "rc", "rd"].includes(name) && /^\d+$/.test(arg || "")) {
      if (+arg > MIMIC_TAG_MAX) return { ok: false, why: "big", tag: whole };
      bytes += +arg; continue;
    }
    return { ok: false, why: "tag", tag: whole };
  }
  return bytes > MIMIC_UDP_MAX ? { ok: false, why: "huge" } : { ok: true, bytes };
}

/* Any AmneziaWG field the Edit sheet changes: an I line by mimicCheck, every other field printable ASCII only (twin of the
   panel's awg_value_refusal) — so the sheet holds Save instead of closing on a save the panel refuses. */
export function awgFieldCheck(k, v) {
  return MIMIC_KEYS.includes(k) ? mimicCheck(v) : AWG_BAD_CHAR.test(awgTrim(v)) ? { ok: false, why: "ctl" } : { ok: true, bytes: 0 };
}
// the built-in set's packets and bytes, for the picker's row (fixed — computed once, not on every poll's render)
export const MIMIC_BUILTIN_SIZE = MIMIC_KEYS.reduce(([n, b], k) => { const x = mimicCheck(MIMIC_BUILTIN[k]).bytes; return x ? [n + 1, b + x] : [n, b]; }, [0, 0]);
