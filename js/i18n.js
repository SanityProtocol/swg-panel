/* i18n.js — one lookup for every user-visible string in the panel.
 *
 * LAYER 0 (see docs/APP-JS-SPLIT-PLAN.md §8). A LEAF: imports nothing from js/, because util.js's
 * formatters (T("just now"), "3d ago") are themselves translatable and import THIS.
 *
 * The key IS the English text. `T("Delete peer")` — not `T("peers.delete.title")`. Three reasons, in a
 * ~2,300-string retrofit: nobody has to invent 2,300 names, the call site still shows you the sentence
 * you are reading, and an untranslated string renders as correct English instead of a bare key. The cost
 * is that editing the English silently orphans its translation — which is why the catalog is GENERATED
 * and checked (.campaign/i18n-extract.mjs), not hand-maintained.
 *
 * Two escapes from plain lookup:
 *   context   T("nodes|Remove") — same English, different translation. The prefix is stripped for the
 *             fallback, so an untranslated context key still renders "Remove".
 *   variables T("Rotated keys for {n} peers", { n }) — never build a sentence with `+`. Word order
 *             differs between languages, and three concatenated fragments cannot be reordered.
 *
 * WHY `T` AND NOT THE CONVENTIONAL `t`: this codebase had `t` long before it had translations — it is the
 * local name for a peer TARGET in every grid, row and deployment loop (hundreds of scopes, several of which
 * are the most string-dense code in the panel). A translate call shadowed inside one of those is a
 * TypeError at render. Renaming one import beat renaming hundreds of locals.
 *
 * Counting is not interpolation. Russian has three plural forms where English has two, so a count needs
 * plural(n, "peer"), which consults the catalog's own noun table — see PLURALS in js/lang/ru.js.
 */

import { h } from "preact";

const LOCALES = {
  // A literal map, deliberately: the panel stamps cache keys onto import specifiers with a static regex,
  // and `import("./lang/" + code + ".js")` cannot be rewritten — it would ship unversioned and go stale.
  ru: () => import("./lang/ru.js"),
};

/* [code, name in its OWN language, short label for the switch button]. Both are written in the language
   they name — the button advertises where you are going, so an English speaker who cannot read Cyrillic
   still recognises «РУ», and a Russian speaker sees "EN". */
export const LANGS = [["en", "English", "EN"], ["ru", "Русский", "РУ"]];

/* The language a click on the switch would take you to. With two languages that is simply the other one;
   with three it walks the list, which is what the button already did. */
export function nextLang() {
  const codes = LANGS.map(([c]) => c);
  return codes[(codes.indexOf(LANG) + 1) % codes.length];
}
const STORE_KEY = "swg-lang";

function pick() {
  try {
    const saved = localStorage.getItem(STORE_KEY);
    if (saved && (saved === "en" || LOCALES[saved])) return saved;
  } catch (_) { /* private mode */ }
  try {
    const nav = (navigator.language || "").slice(0, 2).toLowerCase();
    if (LOCALES[nav]) return nav;
  } catch (_) { /* no navigator */ }
  return "en";
}

let LANG = pick();
let STR = {};          // English text -> translation
let PLURALS = {};      // English singular noun -> that language's forms

export const lang = () => LANG;

/* Load the active language's catalog. Awaited once at boot, BEFORE the first render — T() is synchronous
   everywhere else, and a late catalog would paint English and then flip. English needs no catalog. */
export async function loadLang() {
  STR = {}; PLURALS = {};
  const get = LOCALES[LANG];
  if (!get) return;
  try {
    const m = await get();
    STR = m.STR || {};
    PLURALS = m.PLURALS || {};
  } catch (e) {
    console.error("i18n: could not load", LANG, e);   // fall through to English rather than a blank panel
  }
}

export function setLang(code) {
  try { localStorage.setItem(STORE_KEY, code); } catch (_) { /* ignore */ }
  location.reload();   // simplest correct answer: every module read T() at render time
}

const stripCtx = k => { const i = k.indexOf("|"); return i > 0 ? k.slice(i + 1) : k; };

export function T(key, vars) {
  let out = STR[key];
  if (out == null) out = stripCtx(key);          // untranslated -> the English text itself
  if (vars) for (const k in vars) out = out.split("{" + k + "}").join(vars[k]);
  return out;
}

/* One translated sentence with a placeholder that has to be STYLED — a bold name, a coloured count. It cannot
   be one text node, and it must not be two fragments concatenated around the styled bit: word order differs
   (Russian routinely puts the name last). So translate the WHOLE sentence, then split it on its own marker and
   let the caller render the pieces around the styled element.

     const [before, after] = Tsplit("Rotate the keys for {what} of {name}.", "what", { name });
     html`${before}<b>${plural(n, "peer")}</b>${after}`

   Returns [before, after] — `after` is "" when the marker is missing, so a broken key degrades to a prefix
   rather than throwing. */
export function Tsplit(key, marker, vars) {
  const parts = T(key, vars).split("{" + marker + "}");
  return [parts[0], parts.slice(1).join("{" + marker + "}")];
}

/* Prose with several STYLED runs in it — the routing explainers carry a dozen. Splitting on a dozen
   markers would be unreadable, and chopping the paragraph into a dozen keys would hand a translator
   fragments with no sentence to work in. So the styling travels INSIDE the string and this renders it:

     *emphasis*   -> <b>                      words the translator chose to stress
     `literal`    -> <span class="mono">      an address, port, flag or file the operator will TYPE

   The second marker is not decoration. This prose is dense with things like `127.0.0.1`, `-connect` and
   `docker compose up -d`; rendering those bold instead of monospaced makes them read as emphasis rather
   than as something to copy, and it silently changes a UI the translation is supposed to leave alone.

   Only these two are understood, so a catalog entry can never inject markup — and vars are substituted
   AFTER the markers are parsed, so a value that happens to contain a `*` or a backtick (a URL, a peer
   name someone typed) is text, not markup.

   Use T() for anything with one styled run or none, and Tsplit() when the styled part is a value the code
   supplies (a name, a count) rather than words the translator chose. */
export function Trich(key, vars) {
  const s = T(key), out = [];
  const re = /\*([^*]+)\*|`([^`]+)`/g;
  let at = 0, m;
  // A var may be an ELEMENT, not just text — the address-change notices show old → new in their own
  // colours, and flattening those to strings would drop the colour that carries the meaning. So splice
  // structurally instead of string-substituting: text splits around the placeholder and the value goes in
  // between, whatever it is. (String values behave exactly as before.)
  const sub = txt => {
    if (!vars) return txt;
    let parts = [txt];
    for (const k in vars) {
      const v = vars[k], next = [];
      for (const p of parts) {
        if (typeof p !== "string") { next.push(p); continue; }
        const bits = p.split("{" + k + "}");
        bits.forEach((b, i) => { if (i) next.push(v); if (b) next.push(b); });
      }
      parts = next;
    }
    return parts.length === 1 ? parts[0] : parts;
  };
  while ((m = re.exec(s))) {
    if (m.index > at) out.push(sub(s.slice(at, m.index)));
    out.push(m[1] != null ? h("b", null, sub(m[1])) : h("span", { class: "mono" }, sub(m[2])));
    at = re.lastIndex;
  }
  if (at < s.length) out.push(sub(s.slice(at)));
  return out;
}

/* Just the noun in the form `n` requires, without the number — for the layouts that style the count
   separately ("12" in one span, "peers" in the next). Same table, same rules; only the number is dropped. */
export function pluralWord(n, noun) {
  const out = plural(n, noun), sp = out.indexOf(" ");
  return sp < 0 ? out : out.slice(sp + 1);
}

/* A user-facing message that came from the PANEL, not from here.
 *
 * The server's English sentence IS its catalog key — the same convention the rest of the panel uses, so
 * there is no second naming scheme to invent, drift from, or audit. The wire already carries that
 * sentence in `error`, so most server messages need no server change at all: T() finds the translation
 * if there is one and returns the English if there isn't, which is exactly the fallback we want.
 *
 * A sentence with a VALUE in it can't be looked up once the value is baked in ("couldn't bind
 * 0.0.0.0:443 — permission denied"), so those responses also carry `error_key` — the same sentence with
 * {v1}, {v2} left as markers — and `error_vars`. The interpolated `error` stays on the wire untouched:
 * logs, /api/v1 consumers and any older cached build keep reading precisely what they read before.
 *
 * Returns "" when there is no message, so callers keep their own fallback: srvText(r) || T("Failed"). */
export function srvText(r) {
  if (!r) return "";
  if (r.error_key) return T(r.error_key, srvVars(r.error_vars));
  if (r.error) return T(r.error);
  return "";
}

/* A value in a server message is usually a plain string, but a COUNTED one arrives as {n, noun} — the
   panel deliberately doesn't guess the plural, because Russian picks between three forms and the rule
   isn't derivable from English. Declining it here means the same wire payload reads correctly in any
   language we add later. */
export function srvVars(vars) {
  if (!vars) return undefined;
  const out = {};
  for (const k in vars) {
    const v = vars[k];
    out[k] = (v && typeof v === "object" && "n" in v) ? plural(v.n, v.noun) : v;
  }
  return out;
}

/* The activity log's optional context line. Old rows carry only `detail` — a bare value or, for the two
   that had prose, an English sentence — so they still render; new rows carry detail_key + detail_vars
   and translate. */
export function srvDetail(e) {
  if (!e) return "";
  if (e.detail_key) return T(e.detail_key, srvVars(e.detail_vars));
  return e.detail || "";
}

/* An activity VERB. It is stored in English on purpose (see ev_append) and translated only for display,
   so history written before this existed reads in Russian too. Routing and filtering use kind/id. */
export const srvVerb = v => (v ? T(v) : "");

/* A counted noun. English gets two forms from the noun itself; every other language consults its own
   table, because the rule is not derivable — Russian picks between three by the last digit, with a
   correction for the teens. */
/* The English plural of a noun the catalog does not list — which in ENGLISH is every noun, because
   `PLURALS` is only ever populated by a translation catalog and English has none. So this rule is not
   a rare fallback: it is what the English UI actually prints, for all 27 nouns the panel pluralises.
   A bare `+ "s"` got four of them wrong ("2 proxys", "2 addresss", "2 prefixs", "2 broken addresss").

   Two orthography rules cover every one of them, and neither can touch the other 23: a consonant
   before a final `y` takes `-ies`, and a sibilant ending takes `-es`. Lowercase-only on purpose —
   an acronym like "IP" must stay "IPs", not become "IPes".

   Only the HEAD noun inflects: "broken address" → "broken addresses", "new host" → "new hosts". */
function enPlural(w) {
  const at = w.lastIndexOf(" ") + 1, head = w.slice(at);
  const p = /[^aeiou]y$/.test(head) ? head.slice(0, -1) + "ies"
    : /(s|x|z|ch|sh)$/.test(head) ? head + "es"
      : head + "s";
  return w.slice(0, at) + p;
}

export function plural(n, noun) {
  const forms = PLURALS[noun];
  // A noun may carry a context prefix for the same reason a key does — "cap|Peer" is the badge's
  // capitalised English, distinct from the "peer" that appears mid-sentence. English falls back through
  // the same stripCtx as T(), so an unlisted noun still reads correctly rather than printing the prefix.
  if (!forms) { const w = stripCtx(noun); return n + " " + (n === 1 ? w : enPlural(w)); }
  if (LANG === "ru") {
    const a = Math.abs(n) % 100, d = a % 10;
    const i = (a > 10 && a < 20) ? 2 : (d > 1 && d < 5) ? 1 : (d === 1) ? 0 : 2;
    return n + " " + forms[i];
  }
  return n + " " + (n === 1 ? forms[0] : forms[1]);
}

/* Dates and numbers follow the picker, not the browser: an operator who chose Russian in a panel opened
   from an en-US machine should not get American dates. */
export const locale = () => (LANG === "en" ? "en-GB" : LANG);
export const fmtNum = n => { try { return Number(n).toLocaleString(locale()); } catch (_) { return String(n); } };
