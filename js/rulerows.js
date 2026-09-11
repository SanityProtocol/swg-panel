/* rulerows.js — the rule list the panel stores ⇄ the rows the operator edits.
 *
 * LAYER 1 (see docs/APP-JS-SPLIT-PLAN.md). Imports only ./classify.js. No Store, no i18n, no DOM — this is
 * the shape change and nothing else, so it can be checked against the panel without a browser.
 *
 * WHY A ROW IS NOT A RULE. A stored rule is one category to one destination, which is what the node
 * consumes and what cascade_plan already emits per (subnet, category). But "send these fifteen services to
 * Germany" is one decision, and making the operator author it fifteen times — fifteen dropdowns, fifteen
 * destinations to keep in step — is the complaint this whole change exists to answer. So the UI works in
 * ROWS: many things, one exit. A row lowers to the rules the node already understands, and rules read back
 * as rows, and the panel, the protocol and swg-noded never learn a second shape.
 *
 * See docs/ROUTING-RULE-BUILDER-PLAN.md §5 (storage) and §7.3 (why not `categories: []`).
 *
 * THE INVARIANTS, each of which is a bug that would otherwise be found in production:
 *
 *  - A row groups a MAXIMAL RUN OF CONSECUTIVE rules with the same (action, node, enabled). Consecutive,
 *    because rule order is what the node's chain reads: pulling two same-destination rules together across
 *    a third would silently reorder the third. (Row order is NOT what decides an overlap between two rules
 *    — the engines answer that by specificity, plan §10.4x — but it is still the order the chain is built
 *    in, so it still decides ties between rules naming the same target, and it is all Kernel-SNI has.)
 *  - `enabled` is part of the key. A row saves one flag for all its rules, so two rules that disagree
 *    about it were never one row.
 *  - The catch-all (`category:"all"`) is not a row at all. It has its own control, it is always last, and
 *    grouping it would let it drift up the list — which is the one rule whose position IS its meaning.
 *  - A legacy `tld` rule is its own row, LOCKED, and is re-emitted byte-for-byte. It carries `tlds` that
 *    nothing else in this file understands; folding it into a neighbour would drop them on the next save.
 *    It also breaks a run rather than being merged through, for the same ordering reason as above.
 *  - Every typed target in a row becomes ONE custom rule, not one each. `custom_cat_id` gives an identical
 *    target bundle a shared nft set; splitting them would multiply sets, chain rules and dnsmasq
 *    directives on the node for no gain.
 *
 * AN `AS<n>` TOKEN IS KEPT, and comes back as one badge. It used not to be: the panel resolved it to that
 * AS's prefixes at save time and dropped the token, so reopening a rule showed the prefixes rather than the
 * AS, re-saving stored them literally, and nothing ever re-resolved them again. Badges made that visible
 * where the old textarea hid it in a comma list, and it is now fixed on the panel side — the tokens live in
 * `asns` beside `domains`/`cidrs` and resolve at plan time. This file just has to read that third array.
 */

import { classify, classifyAll, patternTier } from "./classify.js";
import { idnHost } from "./idn.js";

let _gidSeq = 0;
export const newGid = () => "rg" + (++_gidSeq);

const isCatchAll = r => r && r.category === "all";
const isLegacy = r => !!(r && (r.match || r.tlds));          // a `tld` rule: shaped differently, kept verbatim
// The grouping key. `enabled` is in it because a row saves one flag for all its rules, so two rules that
// disagree about it were never one row. Joined on "|": an action is an enum, a node is a hex id, and the
// flag is 0 or 1 — none of them can contain one.
// ⚠️ THE DESTINATION'S IDENTITY, WHOLE. `dev` rules name an exit, and if the key ignored it, two rules
// pointing at DIFFERENT exits would group into one row, be re-emitted with the first row's exit, and the
// second exit would be silently gone on the next save — §5.8's collapse, in the shape P5 introduces.
const rowKey = r => [r.action || "exit",
                     r.action === "exit" ? (r.node || "") : r.action === "dev" ? (r.exit_id || "") : "",
                     r.enabled === false ? 0 : 1].join("|");

/** The badges one stored rule contributes.
 *  {t:"list", id}                  — a curated preset, a provider-catalog category, or a custom list
 *  {t:"target", raw, kind, value}  — something the operator typed, read back through the shared grammar */
function badgesOf(rule) {
  if (rule.category !== "custom") return [{ t: "list", id: rule.category }];
  // A fresh edit carries `targets`; a stored rule carries the split arrays. Read whichever is there — the
  // same either/or the panel's _validate_routing does, so the two never disagree about what a rule holds.
  if (rule.targets != null) return classifyAll(rule.targets).map(x => ({ t: "target", ...x }));
  return [...(rule.domains || []), ...(rule.cidrs || []), ...(rule.asns || []), ...(rule.patterns || [])]
    .map(raw => ({ t: "target", raw, ...classify(raw) }));
}

/** Stored rule list → {rows, catchAll}. `catchAll` is the `all` rule if there is one (the footer control
 *  owns it), and is never part of a row. Order of rows is the stored order, which is priority order. */
export function rulesToRows(rules) {
  const rows = [];
  let catchAll = null;
  for (const rule of (rules || [])) {
    if (!rule || typeof rule !== "object") continue;
    if (isCatchAll(rule)) { catchAll = rule; continue; }     // last-match semantics live in its own control
    if (isLegacy(rule)) {                                    // opaque here, and must not be merged THROUGH
      rows.push({ _gid: newGid(), enabled: rule.enabled !== false, action: rule.action || "exit",
                  node: rule.node || "", exit_id: rule.exit_id || "", locked: true, legacy: rule,
                  badges: (rule.tlds || []).map(t => ({ t: "target", raw: "*." + t, ...classify("*." + t) })) });
      continue;
    }
    const key = rowKey(rule);
    const last = rows[rows.length - 1];
    if (last && !last.locked && last._key === key) { last.badges.push(...badgesOf(rule)); continue; }
    rows.push({ _gid: newGid(), _key: key, enabled: rule.enabled !== false, action: rule.action || "exit",
                node: rule.action === "exit" ? (rule.node || "") : "",
                exit_id: rule.action === "dev" ? (rule.exit_id || "") : "", badges: badgesOf(rule) });
  }
  return { rows, catchAll };
}

/** Rows → the stored rule list. The catch-all is appended last, always, because that is what makes it the
 *  catch-all. A row with no badges emits nothing rather than an empty rule the panel would have to reject. */
export function rowsToRules(rows, catchAll) {
  const out = [];
  for (const row of (rows || [])) {
    if (!row) continue;
    if (row.legacy) { out.push(row.legacy); continue; }      // verbatim: we do not understand it well enough to rewrite it
    const badges = row.badges || [];
    if (!badges.length) continue;
    const base = { enabled: row.enabled !== false, action: row.action || "exit" };
    if (base.action === "exit") base.node = row.node || "";
    if (base.action === "dev") base.exit_id = row.exit_id || "";
    for (const b of badges) if (b.t === "list") out.push({ ...base, category: b.id });
    const typed = badges.filter(b => b.t === "target");
    // One custom rule for the whole row: identical bundles share an nft set on the node, and `targets` is
    // the form the panel re-splits, so the AS tokens it resolves are still there to resolve.
    if (typed.length) out.push({ ...base, category: "custom", targets: typed.map(b => b.raw).join(", ") });
  }
  if (catchAll) out.push(catchAll);
  return out;
}

/** Badges compared the way the datapath sees them — a list by its id, a target by what it MEANS rather
 *  than how it was typed (`*.google.com` and `google.com` are the same rule). Used by the round-trip gate
 *  and by the duplicate check in a row. */
export const badgeIdentity = b => b.t === "list" ? "list:" + b.id : "target:" + b.kind + ":" + b.value;

/** ── THE TEXT FORM OF A BADGE ──────────────────────────────────────────────────────────────────────────
 *  A rule is copied, pasted and backed up as text, so EVERY badge needs one — including a list, which has no
 *  address to write. It gets the identity string the panel already uses for it, `badgeIdentity`:
 *  `list:youtube`, `list:metacubex:youtube`, `list:<custom id>`. Nothing had to be invented, and the round
 *  trip is exact by construction because the text IS the identity.
 *
 *  `list:` cannot collide with a target: a hostname cannot contain a colon, and the one target kind that can
 *  (`AS:13335`) is matched by the classifier's own AS pattern, never by this prefix.
 *
 *  IT LIVES HERE, not in routing.js, because it is a FORMAT rather than a screen — operators keep it in
 *  files and paste it between panels. This module imports no preact, so `.campaign/textform-audit.mjs` can
 *  prove `text → badge → text` is the identity in node, which is the one property clicking cannot establish.
 *  Documented for operators in docs/ROUTING-TEXT-FORM.md; changing the prefix breaks files people have kept.
 */
export const badgeText = b => b.t === "list" ? badgeIdentity(b) : idnHost(b.raw);

/** One token → `{b}` (a badge) or `{bad, why}`. Shared by the textarea, the paste path and the box, so all
 *  three agree about what `list:` means rather than each growing its own reading.
 *
 *  POLICY IS INJECTED, never baked in. `allowKind` is which kinds this node's ENGINE can run; `knownList` is
 *  which list ids this PANEL can vouch for. Both are live state and neither belongs in a grammar — and
 *  defaulting them to permissive is what lets a gate exercise the grammar on its own terms. */
export function readToken(tok, opts) {
  const allowKind = (opts && opts.allowKind) || (() => true);
  const knownList = (opts && opts.knownList) || (() => true);
  const t = String(tok || "").trim();
  if (!t) return null;
  const m = /^list:(.+)$/i.exec(t);
  if (m) { const id = m[1].trim();          // `.+` is greedy, so a provider's own colon survives verbatim
    return knownList(id) ? { b: { t: "list", id } } : { bad: t, why: "unknown_list" }; }
  const c = classify(t);
  if (c.kind === "invalid" || !allowKind(c.kind)) return { bad: t, why: "target" };
  return { b: { t: "target", raw: t, kind: c.kind, value: c.value } };
}

/** Does `broad` claim EVERY hostname `narrow` claims? — the test behind the "a more specific rule below
 *  wins these hosts" lint. Answers only where containment is PROVABLE from the two operands, and returns
 *  false everywhere else: a missed warning is invisible, an invented one sends the operator to rewrite a
 *  rule that was already right. Fail-safe is the whole design here, not caution for its own sake.
 *
 *  WHY THIS EXISTS. The routing screen used to print "first match wins" over rows the operator can drag,
 *  and for an overlap that is not what happens: swg-sni answers by SPECIFICITY (the kind ladder, then the
 *  longest operand), and dnsmasq does the same on Force-DNS — measured, plan §10.4x. The label now says so.
 *  But specificity is not visible in a list the way row order is, so where the two DISAGREE the row says it.
 *
 *  THE HOST SET EACH KIND CLAIMS, which is what the table below is reasoning about — taken from swg-sni's
 *  `_match`, not from the classifier, because the node is what actually routes:
 *      site V / zone V   H === V or H ends with "." + V      (a whole-label suffix; zone is the 1-label case,
 *                                                             and both are the same set, so both read as `sfx`)
 *      first V           H === V or H starts with V + "."
 *      any V             some LABEL of H is exactly V
 *      starts/ends/      H starts with / ends with / contains V — BYTES, no label boundary at all
 *        contains V
 *
 *  Every rule below is a one-line proof over those sets. The ones deliberately NOT here are the pairs where
 *  containment does not hold in general — `sfx` under `starts` (a host `sub.V` need not start with S even
 *  when V does), anything under `first`, `first` under `ends` — and they return false with the rest. */
const _SFX = { site: 1, zone: 1 };                  // one host set, two kinds — see above
export function badgeCovers(broad, narrow) {
  // A list's members are resolved on the panel and are not known here. BELT-AND-BRACES, and deliberately
  // kept as such: a list badge carries neither `kind` nor `value`, so it would already fall out at the
  // empty-operand check below or at the switch's default. No test input can tell this line from its
  // absence — `.campaign/covers-audit.mjs` says so rather than pretending a case covers it — and it stays
  // because it is the only line that states the REASON. Deleting it would leave list-safety resting on two
  // accidents of shape instead of one rule.
  if (broad.t === "list" || narrow.t === "list") return false;
  if (badgeIdentity(broad) === badgeIdentity(narrow)) return false; // identical is the DUPLICATE lint, not this one
  const B = String(broad.value || ""), N = String(narrow.value || "");
  const bk = _SFX[broad.kind] ? "sfx" : broad.kind, nk = _SFX[narrow.kind] ? "sfx" : narrow.kind;
  if (!B || !N) return false;
  switch (bk) {
    case "contains":                                 // every host of `narrow` contains N (or a label of it) ⊇ B
      return nk === "sfx" || nk === "first" || nk === "any" ? N.includes(B)
           : nk === "starts" || nk === "ends" || nk === "contains" ? N.includes(B) : false;
    case "ends":                                     // H ends with N, and N ends with B ⇒ H ends with B
      return (nk === "sfx" || nk === "ends") && N.endsWith(B);
    case "starts":                                   // H starts with N, and N starts with B ⇒ H starts with B
      return (nk === "first" || nk === "starts") && N.startsWith(B);
    case "any":                                      // some label of H is B
      return nk === "sfx" ? N.split(".").includes(B) : nk === "first" ? N === B : false;
    case "sfx":                                      // H ends in ".N", and N ends in ".B" ⇒ H ends in ".B"
      return nk === "sfx" && N.endsWith("." + B);
    default:                                         // `first` claims a set nothing else sits inside
      return false;
  }
}

/** Is this badge already in this row? A row is a set; adding the same thing twice is a no-op, not an error. */
export const rowHasBadge = (row, badge) =>
  (row.badges || []).some(b => badgeIdentity(b) === badgeIdentity(badge));


/* ── WHAT A LIST BADGE RESOLVES TO ────────────────────────────────────────────────────────────────────
 *
 * A list badge is one badge with no `kind`, and these answer what is inside it. They live HERE, not in
 * routing.js, for one reason: routing.js imports preact, so nothing in it can be checked without a browser
 * — and both defects this pair has had were "the count walked past the patterns", which is what a gate
 * catches and a reading does not. Gated by .campaign/listbudget-audit.mjs, against the panel's own reader.
 *
 * The Store lookup stays in routing.js and is passed IN. Same shape as `readToken`'s `knownList` above:
 * this layer knows the grammar, the caller knows the roster.
 */

// A list's targets as the operator typed them. `asns` is the third array (§6.10, widened to lists): an AS
// token is STORED as a token and resolved at plan time, so leaving it out here would show a list that is
// routing an AS as though it held nothing but the domains beside it.
/* ⚠️ `patterns` BELONGS IN THIS JOIN. It is the read half of the round trip: the editor seeds its field
   from here and saves that text back, so a kind missing here is silently deleted the first time anyone
   opens a list and presses Save — exactly the freeze §6.10 removed for AS tokens, in a new kind. */
export const customTargets = l => (typeof l === "string") ? l
  : (l && (l.targets ?? [...(l.domains || []), ...(l.cidrs || []), ...(l.asns || []), ...(l.patterns || [])].join(", "))) || "";

/* What a list's contents ROUTE: host names, IP/AS nets, patterns — plus `t2`, how many of the patterns are
   Tier 2, which TIER2_CAP bounds. One pass, because the picker's greying, the size line, the catalog row's
   samples and the budget all want a slice of the same walk; buckets hold the operator's own tokens, so a
   sample reads back as typed. Invalid tokens are counted nowhere — the field reports those separately.

   THE CLASSIFIER DECIDES, and nothing here re-derives it. Each of these callers used to carry a grammar of
   its own, and they had already drifted apart (see the note where they stood in routing.js).

   DEDUPE BY WHAT IT MEANS, NOT BY WHAT WAS TYPED, because the panel stores one entry per canonical value:
   `google.com` and `*.google.com` are ONE host, so are `яндекс.рф` and its punycode, so are `1.2.3.4` and
   `1.2.3.4/32`. Counting raw tokens described the typing rather than the list. By KIND too — `*abc*` and
   `abc*` share the operand `abc` and are two different rules. Checked against _clean_targets, not assumed. */
/* MEMOISED ON THE RECORD, VALIDATED ON ITS CONTENT. `customCaps` is asked once per list badge per render —
   by the badge itself, and (since the collapsed summary learned to count what cannot run) while the rules
   section is CLOSED, which is the default view and re-renders on every keystroke in any field of the sheet.
   Measured before adding this: 281 µs for one 500-entry list, 2.8 ms for ten of them, per keystroke.

   The key is the RECORD, so entries die with the poll that replaced them and nothing has to be invalidated
   by hand; `raw` is re-derived and compared, so a record mutated in place misses rather than answers from a
   stale cache. That compare is a join and a string equality against a classify pass over every token — the
   whole point. Records arriving as a plain string (the editor's live text) are not cached: a WeakMap cannot
   hold one, and it changes on every keystroke anyway, so there would be nothing to hit. */
const _bucketMemo = new WeakMap();
export function listBuckets(l) {
  const raw = customTargets(l);
  if (l && typeof l === "object") {
    const hit = _bucketMemo.get(l);
    if (hit && hit.raw === raw) return hit.v;
    const v = _bucketsOf(raw);
    _bucketMemo.set(l, { raw, v });
    return v;
  }
  return _bucketsOf(raw);
}
function _bucketsOf(raw) {
  const host = [], ip = [], pat = [], seenKey = new Set();
  let t2 = 0;
  for (const c of classifyAll(raw)) {
    const k = c.kind + ":" + c.value;
    if (seenKey.has(k)) continue;
    seenKey.add(k);
    if (c.kind === "site") host.push(c.raw);
    else if (c.kind === "ip" || c.kind === "asn") ip.push(c.raw);
    else if (patternTier(c.kind) > 0) { pat.push(c.raw); if (patternTier(c.kind) === 2) t2++; }
  }
  return { host, ip, pat, t2 };
}

/* Which TIERS a list can match in, for the picker's greying. A pattern is HOST-tier exactly like a domain,
   so a list holding only `*.ru` reporting {host:false} would read as "matches nothing anywhere" on the
   engines that in fact run it. */
export function customCaps(l) {
  const b = listBuckets(l);
  return { host: b.host.length + b.pat.length > 0, ip: b.ip.length > 0 };
}

// §12.1's Tier-2 budget, and the number Phase 3 deferred: Tier 2 is the only cost in the node's matcher
// that grows with how many there are, and Phase 3's engine bounded it by something else entirely
// (`_XTS_CAP`, a chain length). This is the number measured for the LINEAR SCAN, which is Phase 4's engine.
//
// PER INTERFACE, NOT PER ROW: the node scans one flat list across every rule the interface carries, so a
// per-row budget would bound nothing — ten rows of ninety-nine is nine hundred and ninety comparisons per
// connection. The node holds its own total (`_SNI_TIER2_MAX`, ten times this) because an API client can
// post what the field refused; this is where a person is told, at the moment they type, which is the only
// place a limit is worth anything.
export const TIER2_CAP = 100;

/** How many Tier-2 operands a list holds. Takes the RECORD — the caller does the roster lookup. */
/* A list is ONE badge with no `kind`, so counting badges saw none of these: a list of 500 substrings
   walked past the panel's cap and met the NODE's instead, which truncates and reports rather than
   refusing at the field. Lists could not hold patterns when this was written; now they can. */
export const listTier2 = list => listBuckets(list).t2;

/** Every Tier-2 operand an interface's rows will ship — the thing TIER2_CAP bounds.
 *  `lookupList(id)` resolves a list badge to its record, or null when the roster has not loaded. */
export const tier2Count = (rows, lookupList) => (rows || []).reduce((n, r) =>
  n + (r.badges || []).reduce((m, b) => m + (b.t === "list" ? listTier2(lookupList ? lookupList(b.id) : null)
                                           : (b.t === "target" && patternTier(b.kind) === 2 ? 1 : 0)), 0), 0);
