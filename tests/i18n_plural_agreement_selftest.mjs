/* Self-test: a COUNT is never the subject of a fixed-plural Russian verb.
 *
 * `plural(n, noun)` declines the noun — "1 пир · 2 пира · 5 пиров" — because Russian picks between three
 * forms and the rule is not derivable from English. It cannot decline the VERB, and nothing else does
 * either, so a sentence written as "{count} получат …" is right for 2 and 5 and wrong for exactly 1:
 *
 *     1 пир получат свежие конфиги для импорта      ← reported by the operator, on the recreate card
 *
 * English hides this completely ("{count} get fresh configs"), so a translator following the source
 * sentence structure reproduces the bug every time — which is why four strings had it, not one.
 *
 * ⚠️ THE FIX IS THE SENTENCE, NOT MACHINERY. Adding verb agreement would mean a conjugation table per verb
 * per language; phrasing so that NO finite verb agrees with the number costs nothing and cannot rot. Every
 * fixed string puts the count where Russian never inflects around it — after "это", after a colon, or in
 * parentheses.
 *
 * ⚠️ AND THIS IS A DENYLIST, WHICH IS AN HONEST WEAKNESS. It catches a count followed by a verb form from
 * the list below — the shape that has actually shipped. It cannot know Russian grammar, so a new verb has
 * to be added when a new one appears. It fails closed in the direction that matters: adding a verb to the
 * list can only ever find more, never fewer.
 *
 * Run: node tests/i18n_plural_agreement_selftest.mjs   --perturb  puts the shipped sentences back, RED.
 */
import fs from "node:fs";
import path from "node:path";
import { ROOT, check, done } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const RU = path.join(ROOT, "js", "lang", "ru.js");
let src = fs.readFileSync(RU, "utf8");

// The four sentences exactly as they shipped, to prove this gate would have caught them.
const SHIPPED = [
  "Пересоздайте его с новым ключом; {count} получат свежие конфиги для импорта.",
  "Его *{count}* получат новые ключи, как только он вернётся",
  "При приёме его *{count}* перейдут — откройте установку",
  "При приёме его *{count}* перейдут — каждый станет",
];
if (PERTURB) src += "\nconst __shipped = " + JSON.stringify(SHIPPED) + ";\n";

// 3rd-person-plural forms that would follow a count acting as the subject. Grown, never guessed.
const PLURAL_VERBS = ["получат", "перейдут", "будут", "станут", "сойдутся", "вернутся", "появятся",
                      "исчезнут", "обновятся", "изменятся", "заменятся", "потеряют", "требуют",
                      "останутся", "продолжат", "начнут", "перестанут", "уйдут", "придут",
                      // ⚠️ SINGULAR TOO, for the same reason in reverse: «1 правило указывает» is right
                      // and «2 правила указывает» is wrong, so a fixed singular verb after a count is the
                      // identical bug seen from the other end. Nothing had it; the shape is now watched.
                      "указывают", "указывает"];
// ⚠️ `{v1}` AS WELL AS `{count}`, and this gate was blind to half its own subject without it. A count
// reaches a sentence through whichever slot the call site named, and the two idioms in this tree are
// `T("…{count}…", { count: plural(n, "peer") })` and `T("…{v1}…", { v1: plural(n, "target") })` — the
// second is what every routing summary uses. Measured when this list grew: adding `{v1}` to the pattern
// matches ZERO existing values, so it costs nothing today and covers the half that was unwatched.
// [[i18n-bare-gate]] is the same lesson: a slot the audit does not know about is a slot with no audit.
//
// `{count}`/`{v1}`, optionally wrapped in Trich's bold markers, then punctuation/space, then a verb.
// ⚠️ NOT `\b`. JavaScript's word boundary is defined on [A-Za-z0-9_], so after a Cyrillic letter it never
// matches and the whole rule silently finds nothing — which is exactly what section [3] caught on the first
// run of this gate. A negative lookahead for another Cyrillic letter is the boundary that means anything
// here. NOT global either: `.test()` on a /g/ regex carries lastIndex between calls and alternates
// true/false on the same input.
const BAD = new RegExp("\\*?\\{(?:count|v1)\\}\\*?[\\s—,:-]*(" + PLURAL_VERBS.join("|") + ")(?![А-Яа-яЁё])");

// ⚠️ PARSE THE CATALOG, don't eyeball the file: a value split across lines is still one sentence, and a key
// (which is ENGLISH) must never be mistaken for a value. Values are the string literals after a `":`.
const values = [];
for (const m of src.matchAll(/"((?:[^"\\]|\\.)*)"\s*(?::|,)/g)) {
  const v = m[1];
  if (/[Ѐ-ӿ]/.test(v)) values.push(v);     // Cyrillic ⇒ it is a translation, not a key
}

console.log("\n[1] the catalog is actually being read");
check("Russian values were found at all", values.length > 500, values.length);
check("…including ones that carry a count", values.filter(v => v.includes("{count}")).length > 5,
      values.filter(v => v.includes("{count}")).length);

console.log("\n[2] no count is the subject of a verb that cannot agree with it");
const hits = [];
for (const v of values) {
  const m = BAD.exec(v);
  if (m) hits.push(m[0] + "   …in: " + v.slice(0, 70));
}
check("nothing reads '1 пир получат'", hits.length === 0, hits.join("\n        "));

console.log("\n[3] the shape this gate exists for is one it can see");
// Without this the denylist could silently stop matching (a renamed marker, a changed dash) and the gate
// would go quiet rather than green-for-a-reason.
const caught = SHIPPED.filter(s => BAD.test(s));
check("all four shipped sentences match the rule", caught.length === SHIPPED.length,
      SHIPPED.filter(s => !BAD.test(s)).join(" | "));

console.log("\n[4] the replacements put the count somewhere Russian never inflects");
const fixed = values.filter(v => /это \*?\{count\}\*?/.test(v));
check("the rewritten sentences use the 'это {count}' form", fixed.length >= 4, fixed.length);

console.log("\n[5] ⚠️ …and the ENGLISH sentence is checked too, because that is where the next one hid");
// This gate was built for Russian and shipped blind to its own other half. `T("{v1} points nowhere",
// { v1: plural(dead, "rule") })` renders "3 rules points nowhere" — the identical defect, in the language
// the key is written in, in the very release that added the {v1} pattern above. English inflects a present
// verb for the singular, so a count-as-subject is wrong for every n except the one the author had in mind;
// its sibling "{v1} can't run here" is fine only because a modal does not inflect.
//
// ⚠️ THE SLOT IS NOT THE SIGNAL — THE CALL SITE IS. Reading the catalog the way section [2] does produces
// sixteen false alarms here, because `{v1}` is this tree's general-purpose slot and it usually carries a
// port, an interface or a subnet: "port {v1} is already used" is correct English. Only a slot bound to
// `plural(…)` holds a COUNT. So this reads the CODE, pairs each sentence with the slots that are counts,
// and checks the verb after those. A denylist, like [2], and honest about it: it can only ever find more.
const EN_VERBS = ["points", "is", "was", "has", "does", "goes", "runs", "needs", "takes", "gets", "uses",
                  "keeps", "makes", "requires", "matches", "belongs", "appears", "stops", "starts",
                  "shows", "stays", "carries", "sends", "leaves", "returns", "becomes", "remains",
                  // and the plural side, wrong for exactly 1 in the same way
                  "are", "were", "have", "do", "point", "go", "run", "need", "remain"];
const enBad = slot =>
  new RegExp("\\*?\\{" + slot + "\\}\\*?[\\s—,:-]+(" + EN_VERBS.join("|") + ")\\b");

// Every T()/Trich() whose variables object binds a slot to plural()/pluralWord(). The object body carries
// no nested braces at any of this tree's call sites, which is what makes a regex honest here — and [5b]
// asserts the scan actually found the shape, so a refactor that breaks it cannot pass quietly.
const files = [];
(function walk(d) { for (const e of fs.readdirSync(d, { withFileTypes: true })) {
  if (e.name === "lang" || e.name === "vendor") continue;
  const f = path.join(d, e.name);
  if (e.isDirectory()) walk(f); else if (e.name.endsWith(".js")) files.push(f);
} })(path.join(ROOT, "js"));

const counted = [];   // { sentence, slot, file }
for (const f of files) {
  const t = fs.readFileSync(f, "utf8");
  for (const m of t.matchAll(/\bT(?:rich)?\(\s*"((?:[^"\\]|\\.)*)"\s*,\s*\{([^{}]*)\}/g)) {
    for (const b of m[2].matchAll(/(\w+)\s*:\s*plural(?:Word)?\(\s*([A-Za-z_$][\w.$]*)/g)) {
      // ⚠️ A CAP IS NOT A COUNT. `plural(TIER2_CAP, "text pattern")` interpolates a CONSTANT — the sentence
      // reads "8 text patterns is all one interface can match", which is the idiomatic measure reading and
      // cannot be wrong for some other n, because there is no other n. A rule that flagged it would be
      // switched off rather than obeyed, and then it would not be watching the real ones either.
      if (/^[A-Z][A-Z0-9_]*$/.test(b[2])) continue;
      counted.push({ sentence: m[1], slot: b[1], file: path.basename(f) });
    }
  }
}
check("call sites binding a count into a sentence were found", counted.length >= 8, counted.length);
// ⚠️ AND ONE SENTENCE IS EXEMPT BECAUSE ITS AUTHOR ALREADY SOLVED IT — the OTHER way, with a separate
// singular sentence chosen by an explicit `=== 1` branch, so the plural wording is only ever reached for
// n≥2 where "are" is right. That is a legitimate fix, not an oversight. The exemption is granted only
// while the proof is present: delete the singular branch and this goes red, which is the point of writing
// it as evidence rather than as a name on a list. [[lesson-affirmative-not-diff]]
const EXEMPT = [{
  file: "iface.js",
  starts: "Recreating {v1} — keep this tab open and its {v2} are rekeyed",
  proof: /\(ghost\.peers \|\| \[\]\)\.length === 1[\s\S]{0,400}its 1 peer is rekeyed automatically/,
}];
for (const e of EXEMPT) {
  check("the '%s…' exemption still has its singular branch".replace("%s", e.starts.slice(0, 34)),
        e.proof.test(fs.readFileSync(path.join(ROOT, "js", e.file), "utf8")),
        "the singular sentence is gone — the plural wording now renders for n=1 too");
}
const exempt = c => EXEMPT.some(e => e.file === c.file && c.sentence.startsWith(e.starts));
const enHits = counted.filter(c => !exempt(c) && enBad(c.slot).test(c.sentence))
                      .map(c => c.file + ": " + c.sentence.slice(0, 78));
check("no count is the subject of an English verb that inflects", enHits.length === 0,
      enHits.join("\n        "));

console.log("\n[5b] …and the English rule can see the shape it exists for");
check("the sentence that shipped this release matches the rule", enBad("v1").test("{v1} points nowhere"));
check("…and so does the plural side", enBad("count").test("{count} are offline"));
check("…while its sibling with a modal verb does not", !enBad("v1").test("{v1} can't run here"));
// ⚠️ AND A SLOT THAT IS NOT A COUNT IS NOT ITS BUSINESS: "port {v1} is already used" is correct English,
// and a rule that flagged it would be turned off rather than obeyed.
check("…and a non-count slot is out of scope by construction",
      !counted.some(c => /^port \{v1\} is /.test(c.sentence)));

done(PERTURB, "the shipped sentences restored");
