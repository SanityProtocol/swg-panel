/* idn.js — show a punycode name the way it was written.
 *
 * LAYER 1 (see docs/APP-JS-SPLIT-PLAN.md). Imports nothing.
 *
 * WHY THIS EXISTS. Everything downstream of the classifier speaks punycode, and it has to: a DNS query and a
 * TLS ClientHello both carry `xn--p1ai`, never `рф`, so a rule stored as anything else would match nothing on
 * any engine (ROUTING-RULE-BUILDER-PLAN §5.2). But an operator who typed `*.рф` was then shown a badge
 * reading `.xn--p1ai`, and could not recognise their own rule — the value is right and the display is
 * useless. This turns the value back into the name for DISPLAY ONLY. Nothing here ever reaches storage, the
 * plan, or a node.
 *
 * THE DECODER IS NOT TRUSTED. `punyDecode` is RFC 3492 §6.2, ~30 lines of well-specified arithmetic, and a
 * mistake in it would put a WRONG name in front of the operator — worse than the unreadable one. So the
 * result is handed back to the platform's own encoder (`new URL()`, which is IDNA) and used only if it
 * re-encodes to exactly the label we started from. A decoder bug therefore degrades to showing punycode,
 * which is where we already were. There is no browser API for the decode direction or this would use it.
 *
 * MIXED SCRIPTS STAY ENCODED. `xn--pple-43d` decodes to `аpple` — a Cyrillic а in front of Latin `pple`.
 * Rendering that as a name is how a rule reads as one thing and routes another, and a routing rule is
 * exactly the kind of text someone audits at a glance. A label whose letters come from more than one script
 * keeps its punycode, so the reader sees that something is unusual instead of being reassured. Digits,
 * hyphens and marks are script-neutral and do not count.
 *
 * ⚠️ ITS LIMIT, stated rather than papered over. This is not UTS-39 and does not try to be: it answers
 * "is this label written in one alphabet", in one pass, which is what catches a confusable with Latin —
 * and a brand homograph is made of exactly that. What it does NOT do is UTS-39's identifier profiles,
 * confusable folding, or per-TLD script policy.
 *
 * It used to have a second, worse limit: scripts outside a list of eleven shared one "other" bucket, so a
 * label mixing two of THOSE agreed with itself and was RENDERED — the exact shape this function exists to
 * refuse, in the one case nobody would think to look at. The table now names every script that carries an
 * IDN top-level domain, and a letter outside it answers `unknown`, which makes the label refused rather
 * than trusted. So an unlisted script costs a real name its readable form and shows punycode; it can no
 * longer cost a reader a name that lies.
 */

const B = 36, TMIN = 1, TMAX = 26, SKEW = 38, DAMP = 700, INITIAL_BIAS = 72, INITIAL_N = 128;
const MAXINT = 0x7fffffff;

const digitOf = cp => {                          // one basic code point → its digit value, or -1
  if (cp >= 0x30 && cp <= 0x39) return cp - 0x16;          // '0'-'9' → 26..35
  if (cp >= 0x41 && cp <= 0x5a) return cp - 0x41;          // 'A'-'Z' → 0..25
  if (cp >= 0x61 && cp <= 0x7a) return cp - 0x61;          // 'a'-'z' → 0..25
  return -1;
};

const adapt = (delta, numpoints, first) => {
  delta = first ? Math.floor(delta / DAMP) : delta >> 1;
  delta += Math.floor(delta / numpoints);
  let k = 0;
  while (delta > ((B - TMIN) * TMAX) >> 1) { delta = Math.floor(delta / (B - TMIN)); k += B; }
  return k + Math.floor(((B - TMIN + 1) * delta) / (delta + SKEW));
};

/** One punycode label WITHOUT its `xn--` prefix → the Unicode label, or null if it is not valid punycode.
 *  RFC 3492 §6.2 with the IDNA parameters. Every overflow check in the RFC is kept: they are what stop a
 *  crafted label from running away, and this runs on whatever an operator pastes. */
export function punyDecode(input) {
  if (!input) return null;
  const out = [];
  let n = INITIAL_N, i = 0, bias = INITIAL_BIAS;
  const delim = input.lastIndexOf("-");                     // the LAST hyphen separates basic from extended
  for (let j = 0; j < Math.max(delim, 0); j++) {
    const c = input.charCodeAt(j);
    if (c > 0x7f) return null;                              // a basic code point is ASCII by definition
    out.push(c);
  }
  for (let idx = delim >= 0 ? delim + 1 : 0; idx < input.length;) {
    const oldi = i;
    for (let w = 1, k = B; ; k += B) {
      if (idx >= input.length) return null;
      const d = digitOf(input.charCodeAt(idx++));
      if (d < 0 || d > Math.floor((MAXINT - i) / w)) return null;
      i += d * w;
      const t = k <= bias ? TMIN : (k >= bias + TMAX ? TMAX : k - bias);
      if (d < t) break;
      if (w > Math.floor(MAXINT / (B - t))) return null;
      w *= B - t;
    }
    bias = adapt(i - oldi, out.length + 1, oldi === 0);
    if (Math.floor(i / (out.length + 1)) > MAXINT - n) return null;
    n += Math.floor(i / (out.length + 1));
    i %= out.length + 1;
    out.splice(i++, 0, n);
  }
  try { return String.fromCodePoint(...out); } catch { return null; }
}

// Which script a letter belongs to, coarsely — enough to answer "is this label written in one alphabet".
// Anything that is not a letter (digits, hyphen, combining marks) is script-neutral and answers "".
const SCRIPTS = [["latin", /\p{Script=Latin}/u], ["cyrillic", /\p{Script=Cyrillic}/u],
                 ["greek", /\p{Script=Greek}/u], ["han", /\p{Script=Han}/u],
                 ["arabic", /\p{Script=Arabic}/u], ["hebrew", /\p{Script=Hebrew}/u],
                 ["hiragana", /\p{Script=Hiragana}/u], ["katakana", /\p{Script=Katakana}/u],
                 ["hangul", /\p{Script=Hangul}/u], ["thai", /\p{Script=Thai}/u],
                 ["devanagari", /\p{Script=Devanagari}/u],
                 // §10.5 item 3. Every remaining script that carries an IDN top-level domain, so a real name
                 // in one of them is READ rather than shown as punycode. Ordered after the eleven above only
                 // because those are the common ones and this is a linear scan over a label of ≤63 letters.
                 ["armenian", /\p{Script=Armenian}/u], ["georgian", /\p{Script=Georgian}/u],
                 ["bengali", /\p{Script=Bengali}/u], ["gujarati", /\p{Script=Gujarati}/u],
                 ["gurmukhi", /\p{Script=Gurmukhi}/u], ["kannada", /\p{Script=Kannada}/u],
                 ["malayalam", /\p{Script=Malayalam}/u], ["oriya", /\p{Script=Oriya}/u],
                 ["sinhala", /\p{Script=Sinhala}/u], ["tamil", /\p{Script=Tamil}/u],
                 ["telugu", /\p{Script=Telugu}/u], ["thaana", /\p{Script=Thaana}/u],
                 ["tibetan", /\p{Script=Tibetan}/u], ["lao", /\p{Script=Lao}/u],
                 ["myanmar", /\p{Script=Myanmar}/u], ["khmer", /\p{Script=Khmer}/u],
                 ["ethiopic", /\p{Script=Ethiopic}/u], ["syriac", /\p{Script=Syriac}/u]];
/* A letter in NONE of them answers `unknown`, and `singleScript` refuses any label containing one. That is
   the fix for item 3's real defect: `other` was one shared bucket, so a label mixing two scripts that were
   both outside the list — Cherokee beside Vai — agreed with itself and was RENDERED, which is the exact
   shape the function exists to refuse. Erring the other way costs a genuine name in an unlisted script its
   readable form (it shows as punycode, which is correct and merely ugly); erring the way it did costs the
   operator a rule that reads as one thing and routes another. With the table above covering every
   IDN-carrying script, what is left is rare enough that safe-and-ugly is the right trade. */
const scriptOf = ch => { for (const [name, re] of SCRIPTS) if (re.test(ch)) return name;
  return /\p{L}/u.test(ch) ? "unknown" : ""; };
/** True when every letter in the label comes from one script. A label mixing two is the homograph shape and
 *  is left as punycode — Japanese, which legitimately mixes three, is admitted as the one known exception. */
export function singleScript(s) {
  const seen = new Set();
  for (const ch of s) { const k = scriptOf(ch); if (k) seen.add(k); }
  if (seen.has("unknown")) return false;      // cannot tell two unlisted scripts apart → never render it
  if (seen.size <= 1) return true;
  return [...seen].every(k => k === "han" || k === "hiragana" || k === "katakana");
}

/** One label as it should be READ. `xn--p1ai` → `рф`; anything that does not decode, does not re-encode to
 *  itself, or mixes scripts comes back exactly as it went in. */
export function idnLabel(label) {
  const s = String(label || "");
  if (!/^xn--/i.test(s)) return s;
  const u = punyDecode(s.slice(4).toLowerCase());
  if (!u || !singleScript(u)) return s;
  let back = null;                                          // the platform's own IDNA encoder is the referee
  try { back = new URL("http://" + u + ".test").hostname; } catch { return s; }
  return back === s.toLowerCase() + ".test" ? u : s;
}

/** A whole host name as it should be READ, label by label. `xn--80aswg.xn--p1ai` → `сайт.рф`. */
export const idnHost = name => String(name || "").split(".").map(idnLabel).join(".");
/** True when reading it changes it — the caller then has two forms and should show both somewhere. */
export const idnDiffers = name => idnHost(name) !== String(name || "");
