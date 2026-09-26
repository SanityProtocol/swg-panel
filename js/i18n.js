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
    // …and a PHRASE the panel nested as a sentence of its own (`perr("traffic cascaded in")`) is translated before it goes in
    out[k] = (v && typeof v === "object" && "error_key" in v) ? srvText(v)
      : (v && typeof v === "object" && "n" in v) ? plural(v.n, v.noun) : v;
  }
  return out;
}

/* The activity log's optional context line. A row carries `detail` — a bare value (a name, node/iface, a URL) —
   and, when that detail is prose, detail_key + detail_vars, which translate. Rows written before a detail had
   its key keep their English on disk for good (the log is never rewritten), so the few prose shapes that were
   ever written are recognised here — each only under the VERB that wrote it, so a user or a node that happens
   to be named like one of these phrases is never "translated". Two details are lists the browser itself can
   name: the settings sections a Save touched (the SPA's own labels) and a user's changed fields. */
const USER_FIELDS = { tag: "Tag", note: "Note", vk_link: "VK call link", vk_links: "VK call links", expiry: "Subscription expiry" };
const ACT_FIELDS = { awg_params: "act|AmneziaWG parameters", listen_port: "act|listen port", mtu: "MTU" };
const LEGACY_DETAIL = {
  "Deleted peer": [[/^(\d+) targets?$/, m => plural(+m[1], "target")]],
  "Unassigned peer": [[/^was (.+)$/, m => T("was {v1}", { v1: m[1] })]],
  "Assigned peer": [[/^fresh key issued$/, () => T("fresh key issued")]],
  "An exit key restore expired without being applied": [[/^the node never reported the restored key — it may be too old to accept one$/,
    () => T("the node never reported the restored key — it may be too old to accept one")]],
  "Interface came back different from the request": [[/^(.+): (awg_params|listen_port|mtu)$/, m => `${m[1]}: ${T(ACT_FIELDS[m[2]])}`]],
  "Adopted from the live interface": [[/^couldn't read (.+?) — adopted from the live interface instead \(keys, peers and ports kept; any DNS\/Table\/PostUp lines in that file are not\)$/,
    m => T("couldn't read {v1} — adopted from the live interface instead (keys, peers and ports kept; any DNS/Table/PostUp lines in that file are not)", { v1: m[1] })]],
  "Updated panel settings": [[/^(.+)$/, m => m[1].split(", ").map(x => T(x)).join(", ")]],
  "Updated user": [[/^([a-z_]+(?:, [a-z_]+)*)$/, m => m[1].split(", ").map(f => (USER_FIELDS[f] ? T(USER_FIELDS[f]) : f)).join(", ")]],
};
// …and the reclaimed-server rows, whose verb carried the family (see LEGACY_VERB)
const RECLAIMED = [[/^(\d+) user\(s\) kept$/, m => T("{count} kept", { count: plural(+m[1], "user") })],
                   [/^no users in its store$/, () => T("no users in its store")]];
for (const v of ["Reclaimed a WDTT server", "Reclaimed a csqtt server", "Reclaimed a wdtt server"]) LEGACY_DETAIL[v] = RECLAIMED;

/* An activity row's NAME is a value — a person, a node, an interface — and renders as it is. Two rows once carried
   prose there instead ("Update requested · with the panel", "Starting interface · wg0 (automatic, attempt 2 of 5)");
   the panel now writes the node / interface as the name and the prose as a keyed detail, and the old rows are
   recognised here, under their own verb only. */
export function srvName(e) {
  const n = (e && e.name) || "";
  if (e && e.verb === "Update requested" && n === "with the panel") return T("with the panel");
  const m = e && e.verb === "Starting interface" && /^(.+) \(automatic, attempt (\d+) of (\d+)\)$/.exec(n);
  if (m) return `${m[1]} (${T("automatic, attempt {v1} of {v2}", { v1: m[2], v2: m[3] })})`;
  return n;
}

export function srvDetail(e) {
  if (!e) return "";
  if (e.detail_key) return T(e.detail_key, srvVars(e.detail_vars));
  const d = e.detail || "";
  for (const [re, f] of (d && LEGACY_DETAIL[e.verb]) || []) { const m = re.exec(d); if (m) return f(m); }
  return d;
}

/* An activity VERB. It is stored in English on purpose (see ev_append) and translated only for display,
   so history written before this existed reads in Russian too. Routing and filtering use kind/id.
   Three verbs were once written with a value inside them, so no key could match; new rows use fixed verbs
   (the value moved to the detail) and the old ones are recognised here. */
const LEGACY_VERB = [
  [/^VK pool changed — reassigned (\d+) user\(s\)$/, m => T("VK pool changed — reassigned %d user(s)").replace("%d", m[1])],
  [/^VK links per new user: (\d+) → (\d+)$/, m => T("VK links per new user: %d → %d").replace("%d", m[1]).replace("%d", m[2])],
  [/^Reclaimed a (wdtt|csqtt) server$/, m => T(m[1] === "wdtt" ? "Reclaimed a WDTT server" : "Reclaimed a csqtt server")],
];
export const srvVerb = v => {
  if (!v) return "";
  // A verb whose English is also a BUTTON's: the catalog holds the button's imperative («Сбросить выученные IP»),
  // and the log needs what happened — its own context key, for the rows already on disk too.
  if (v === "Reset learned IPs") return T("act|Reset learned IPs");
  if (STR[v] == null) for (const [re, f] of LEGACY_VERB) { const m = re.exec(v); if (m) return f(m); }
  return T(v);
};

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
// English has no catalog, so its plurals are DERIVED — right for regular nouns, wrong for the few that are not.
// "Reaches the devices of 2 persons" reached a user's row before anyone noticed: the word is "people".
const EN_IRREGULAR = { person: "people", child: "children", man: "men", woman: "women" };
function enPlural(w) {
  const at = w.lastIndexOf(" ") + 1, head = w.slice(at);
  const irr = EN_IRREGULAR[head.toLowerCase()];
  const p = irr ? (head[0] === head[0].toUpperCase() ? irr[0].toUpperCase() + irr.slice(1) : irr)
    : /[^aeiou]y$/.test(head) ? head.slice(0, -1) + "ies"
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
