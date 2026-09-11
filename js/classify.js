/* classify.js — read one routing target the way the operator wrote it, and say what it means.
 *
 * LAYER 1 (see docs/APP-JS-SPLIT-PLAN.md). Imports nothing — deliberately. This is a pure grammar, and the
 * moment it reaches for Store or i18n it stops being comparable to its Python twin.
 *
 * THERE ARE EXACTLY TWO IMPLEMENTATIONS OF THIS GRAMMAR and they must agree on every token:
 *   - this file, which decides the badge the operator sees while typing;
 *   - _classify_target() in swg-panel-server, the authority, which buckets patterns for the node in
 *     cascade_plan.
 * `swg-noded` deliberately has no third copy: the panel ships it pre-bucketed lists, so a node can never
 * disagree about what a string meant. The two that remain are pinned together by
 * .campaign/classify-vectors.json — written before either of them — and checked by
 * .campaign/classify-audit.mjs. Change the grammar in one place and that gate goes red.
 *
 * Syntax is LOCKED in docs/PATTERNS-AND-EXTRA-FLAGS-PLAN.md §1.1: `*X` ends with · `X*` starts with ·
 * `*X*` contains · a bare `X.Y` is the name and everything under it · `*.X.Y` is its alias. No regex, ever
 * (§0: `^(a+)+\.com$` backtracks 2.6s in the packet path), and no `?`.
 *
 * WHAT MAKES A KIND, AND WHY IT IS THE DOT AND NOT THE STAR. A star sitting against a dot lands on a label
 * boundary, so the matcher can answer with a hash lookup — flat cost, ~1 µs whether there are 10 patterns or
 * 2000. A star inside a label forces a character scan: 148 µs at 2000, 139× worse (§1.2). Same-looking
 * syntax, two completely different engines underneath, so they are different kinds here and the badge tells
 * the operator which one they just wrote.
 *
 * POLICY IS NOT HERE — with ONE exception, and it is the exception that proves where the line is. The
 * per-interface cap and the per-engine capability gate both take a kind that has already been decided and
 * ask a question about CONTEXT (which interface, which engine); folding those in would make one function
 * answer two questions and drift the moment either policy moved. The Tier-2 length FLOOR (§12.1) asks
 * nothing about context — it is a fact about the token on its own, exactly like the `idn_tier2` refusal it
 * now sits beside, and for the same reason: a two-byte substring does not mean what the operator wrote, it
 * means "every ClientHello carrying these bytes". Kept out of here it would have become a FOURTH reader of
 * a token-level rule, in two languages, and the two review passes before this one each found a divergence
 * of exactly that shape. In here, the shared vector table pins it for free.
 */

// Tier 1 = label-anchored, hash lookup. Tier 2 = character scan. `ip`/`asn` are neither — they never touch
// the host matcher at all, they load straight into the category's nft set.
export const PATTERN_TIER = { site: 1, zone: 1, first: 1, any: 1, starts: 2, ends: 2, contains: 2 };
// THE TIER-2 FLOOR (plan §12.1). A Tier-2 operand is an arbitrary run of bytes matched anywhere in a name,
// so its blast radius is set by its LENGTH and by nothing else: `*ru*` catches ruble.com, brutal.io,
// truecaller.com and every ClientHello that happens to carry those two bytes. Three characters is the floor;
// the badge additionally cautions below five, which is where the sentence, not the refusal, does the work.
export const TIER2_MIN = 3;
export const patternTier = kind => PATTERN_TIER[kind] || 0;
export const isPatternKind = kind => kind in PATTERN_TIER;

const IP_SHAPED = /^[0-9.]+(?:\/[0-9]*)?$/;                    // digits and dots (+ an optional /…) → they meant an address
const IP4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:\/(\d{1,2}))?$/;
const ASN = /^as:?(\d{1,10})$/;                                // AS<n> / AS:<n> — the panel resolves it to that AS's prefixes
const LABEL = /^(?!-)[a-z0-9-]{1,63}(?<!-)$/;                  // one DNS label: no leading/trailing hyphen
const TLD = /^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$/;           // a last label must be alphabetic or punycode — never a number

const bad = why => ({ kind: "invalid", why });

// IDN → punycode, per whole labels. Only safe where the operand IS whole labels: a Tier-2 operand is an
// arbitrary substring, and the punycode of half a label does not exist — see the tier2 guard below.
function puny(s) {
  if (!/[^\x00-\x7f]/.test(s)) return s;
  // `new URL` is a URL parser, not a punycode function, and it will happily read STRUCTURE out of what was
  // handed to it: `яндекс.рф:443` comes back as the bare hostname with the port quietly removed. That made
  // the browser accept a token the panel drops — and only for non-ASCII input, since an ASCII name skips
  // this function entirely and `example.com:443` is refused by both. None of these characters can appear in
  // a hostname, so refusing them here costs nothing and keeps the parser doing one job. (Found by the
  // generated corpus the moment it was pointed at this reader, which is what that step is for.)
  if (/[:/?#@[\]\s]/.test(s)) return null;
  try { return new URL("http://" + s).hostname; } catch { return null; }
}

// A dotted operand that must be a real hostname: ≥2 labels, each a legal label, last one alphabetic/punycode.
function asDomain(s) {
  const d = puny(s);
  if (!d || d.length > 253) return null;
  const labels = d.split(".");
  if (labels.length < 2) return null;
  if (!labels.every(l => LABEL.test(l))) return null;
  if (!TLD.test(labels[labels.length - 1])) return null;
  return d;
}

// A single operand label — the zone in `*.ru`, the name in `google.*` and `*.google.*`.
function asLabel(s, tldRules) {
  const d = puny(s);
  if (!d || d.includes(".")) return null;
  if (!LABEL.test(d)) return null;
  // A zone is the last label of a real name, so it obeys the stricter last-label rule: `*.1` is not a zone.
  // A first/any operand is an ordinary label and may legitimately be numeric (`*.123.*`).
  if (tldRules && !TLD.test(d)) return null;
  return d;
}

/** Classify one raw target token.
 *  → {kind: "ip"|"asn"|"site"|"zone"|"first"|"any"|"starts"|"ends"|"contains", value}
 *  → {kind: "invalid", why} where `why` is a stable code, never prose (each UI writes its own sentence). */
export function classify(raw) {
  let t = String(raw == null ? "" : raw).trim().toLowerCase();
  if (!t) return bad("empty");

  const ma = ASN.exec(t);
  if (ma) return { kind: "asn", value: "as" + String(Number(ma[1])) };

  // Decided BEFORE the scheme/path strip, so `1.2.3.4/` reads as a mistyped CIDR rather than a hostname with
  // a path. Anything made only of digits and dots was meant as an address; say so instead of calling it a
  // bad domain, which is true but unhelpful.
  if (IP_SHAPED.test(t)) {
    const mi = IP4.exec(t);
    if (!mi) return bad("bad_ip");
    if (![1, 2, 3, 4].every(i => +mi[i] <= 255)) return bad("bad_ip");
    if (mi[5] !== undefined && +mi[5] > 32) return bad("bad_ip");
    return { kind: "ip", value: mi.slice(1, 5).join(".") + "/" + (mi[5] === undefined ? "32" : String(+mi[5])) };
  }

  t = t.replace(/^[a-z][a-z0-9+.-]*:\/\//, "").split("/")[0];   // scheme + path — people paste URLs
  t = t.replace(/\.+$/, "");                                    // `yandex.ru.` is a valid FQDN; the last label would be ""
  if (!t) return bad("empty");

  const lead = t.startsWith("*");
  const trail = t.length > 1 && t.endsWith("*");
  if (!lead && !trail) {
    if (t.includes("*")) return bad("star_mid");
    const d = asDomain(t);
    if (d) return { kind: "site", value: d };
    // A LEADING DOT is how people write a zone — `.ru`, `.example.com` — and it is the same reach for a whole
    // zone that a bare label is, said more explicitly. It got `bad_domain` and therefore the catch-all sentence
    // about addresses and AS numbers, which answers a question about IPs that nobody asked. Refused, not
    // guessed, for exactly the reason below; it just gets told what to write instead.
    const undot = t.replace(/^\.+/, "");
    if (t !== undot && undot && !undot.includes("*") && (asDomain(undot) || asLabel(undot, true))) return bad("lead_dot");
    // A single label is the one case worth naming separately: `ru` is almost always someone reaching for the
    // whole zone, and guessing that for them would be a rule of enormous blast radius that nobody asked for.
    return (!t.includes(".") && /^[^\s.]+$/.test(t)) ? bad("bare_label") : bad("bad_domain");
  }

  const core = t.slice(lead ? 1 : 0, trail ? -1 : undefined);
  if (core.includes("*")) return bad("star_mid");               // only the three shapes exist; `goo*gle.com` is not one
  if (!core || core === ".") return bad("empty");

  const headDot = core.startsWith("."), tailDot = core.endsWith(".");

  if (lead && !trail && headDot) {                              // *.X — the star is on a label boundary
    const op = core.slice(1);
    if (!op) return bad("empty");
    if (op.includes(".")) {                                     // *.google.com — the documented alias for the plain name
      const d = asDomain(op);
      return d ? { kind: "site", value: d } : bad("bad_domain");
    }
    const z = asLabel(op, true);                                // *.ru — a whole ending, every name under it
    return z ? { kind: "zone", value: z } : bad("bad_domain");
  }
  if (!lead && trail && tailDot) {                              // X.* — the first part of the name is X
    const op = asLabel(core.slice(0, -1), false);
    return op ? { kind: "first", value: op } : bad("multi_label_operand");
  }
  if (lead && trail && headDot && tailDot) {                    // *.X.* — some part of the name is X
    const op = asLabel(core.slice(1, -1), false);
    return op ? { kind: "any", value: op } : bad("multi_label_operand");
  }

  // Tier 2: the star is inside a label, so there is no boundary to anchor to and the matcher scans.
  // The operand is an arbitrary substring, which is exactly why it cannot be punycoded — half a label has no
  // punycode form. It also could never match: SNI and DNS carry the name already encoded, so a Cyrillic
  // substring would be compared against ASCII bytes for ever. Refuse it rather than ship something inert.
  if (/[^\x00-\x7f]/.test(core)) return bad("idn_tier2");
  if (core.length < TIER2_MIN) return bad("short_tier2");
  return { kind: lead && trail ? "contains" : lead ? "ends" : "starts", value: core };
}

/** Every token in a pasted blob, classified. Splits on whitespace and commas, exactly like the panel's
 *  _split_targets, so what the field accepts and what the server re-reads cannot diverge on the split. */
export const classifyAll = raw => String(raw || "").split(/[\s,]+/).filter(Boolean).map(t => ({ raw: t, ...classify(t) }));
