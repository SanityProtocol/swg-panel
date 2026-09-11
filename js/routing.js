/* routing.js — smart-routing and content-blocking policy: categories, catalogs and their pickers.
 *
 * LAYER 4 (see docs/APP-JS-SPLIT-PLAN.md). Imports util / store / model / ui / charts-free.
 *
 * NOT a screen, which is what the reference graph showed and the July map got wrong: Settings and the
 * interface sheets both render this, so it is a component library they share. Keep it that way — the
 * moment it imports a screen, Settings and iface can no longer both use it.
 *
 * Two policy tiers run in parallel and deliberately mirror each other's shape: ROUTING (send this
 * category out that exit) and BLOCKING (drop it). Each has one capability rule — routeTierOk and
 * blockTierOk — that every mode-gate in the UI defers to, so what a node can actually enforce is decided
 * in one place rather than per control.
 */

import { T, Trich, Tsplit, plural, pluralWord, srvText } from "./i18n.js";
import { classify, classifyAll, patternTier, TIER2_MIN } from "./classify.js";
import { idnHost, idnDiffers } from "./idn.js";
import { rulesToRows, rowsToRules, badgeIdentity, badgeCovers, rowHasBadge, newGid,
         badgeText, readToken as rrReadToken,
         customTargets, customCaps, listBuckets, TIER2_CAP, listTier2, tier2Count } from "./rulerows.js";
import { esc, seen } from "./util.js";
import { isSelfContainedName, nodeStale } from "./model.js";
import { Store, api, bus, useStore } from "./store.js";
import { pickThemed } from "./theme.js";
import { Ic, Tag, Panel, Switch, Dropdown, Disclosure, autoGrow, Sheet, footRow, secTitle, SearchBox,
         Popover, Portal, toast, openModal, pushModal, closeModal, closeAllModals, openConfirm, goSettings,
         useReorder, GRIP_SVG, NodeIpPick, ConfirmPhrase } from "./ui.js";
import { h, Fragment } from "preact";
import { useState, useEffect, useRef, useMemo } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// Phase 3 smart-routing categories (keep in sync with SMART_CATEGORIES in swg-panel-server). A category is a
// destination set the node routes into the chosen exit's mesh link. Domain-tier ones (Google/YouTube/Yandex/
// VK/Meta/Twitter/Netflix) match by domain via the node's dnsmasq — so YouTube splits from the rest of Google;
// the rest (Telegram/Cloudflare/RU-net/All) match by provider IP ranges (geoip). "Russia" is TWO distinct lists:
// ru_net = the whole Russian IP space (geoip, every mode); ru_blocked = sites blocked INSIDE Russia (circumvention
// domains, Force-DNS only) — different meanings, so they're separate categories you route independently.
// Curated "Recommended presets" — MUST stay in sync with CURATED_PRESETS in swg-panel-server (id + label + order).
// Built on FIRST READ, never at import: modules load before loadLang() resolves, so a T() evaluated
// here freezes in English whatever the catalog says (see --frozen). A memoised FUNCTION rather than a
// lazy array/object facade — Dropdown calls flatMap() on its options, and a facade only ever has the
// methods someone remembered to forward.
let _smart_categories = null;
export const SMART_CATEGORIES = () => (_smart_categories || (_smart_categories = [
  // The brand rows carry the marker: a product name is the same string in every language, and listing
  // them as untranslated trains you to skim the report past the rows that are real sentences.
  ["google", "Google"], ["youtube", "YouTube"], ["telegram", "Telegram"], ["netflix", "Netflix"],   // i18n-keys: brand names
  ["meta", "Meta (FB / IG / WA)"], ["twitter", "X (Twitter)"], ["tiktok", "TikTok"], ["discord", "Discord"],   // i18n-keys: brand names
  ["yandex", "Yandex"], ["vk", "VK"], ["openai", "ChatGPT (OpenAI)"], ["claude", "Claude (Anthropic)"],   // i18n-keys: brand names
  ["grok", "Grok (xAI)"], ["gemini", T("Gemini (Google AI)")], ["copilot", T("Microsoft Copilot")], ["signal", "Signal"],   // i18n-keys: brand names
  ["spotify", "Spotify"], ["twitch", "Twitch"], ["disney", "Disney+"], ["reddit", "Reddit"], ["github", "GitHub"],   // i18n-keys: brand names
  ["ru_net", T("Russia — all IPs")], ["ru_gov", T("Russia — Government")], ["ru_banks", T("Russia — Banks")],
  ["ru_blocked", T("Russia — Blocked (all)")], ["ru_blocked_media", T("Russia — Blocked (media)")],
  ["all", T("All traffic (catch-all)")],
]));
export const CURATED_HEAVY = { ru_blocked: 1, ru_net: 1 };   // UI weight flag — large lists
// Same rule as the table it derives from: built on first read, not at import.
let _smart_cat_label = null;
export const SMART_CAT_LABEL = new Proxy({}, { get: (_, k) => (_smart_cat_label || (_smart_cat_label = Object.fromEntries(SMART_CATEGORIES())))[k] });
export const CAT_UNCAT_COLOR = "#8A94A6";   // muted slate — the "everything else" catch-all, deliberately off-palette
// HSL→hex, no deps.
export function hsl2hex(h, s, l) {
  s /= 100; l /= 100;
  const k = n => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
  const f = n => { const c = l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1)); return Math.round(255 * c).toString(16).padStart(2, "0"); };
  return "#" + f(0) + f(8) + f(4);
}
// Colour for a ranked bar by its ROW INDEX: a golden-angle hue rotation (~137.5° per step) so consecutive rows
// are always far apart on the wheel — adjacent bars can never look similar, at ANY list length (so the count is
// free to be configurable). Talkers and destinations use a different start hue + saturation so the two lists read
// as distinct colour families.
export const dashRankColor = (i, kind) => kind === "talker" ? hsl2hex((205 + i * 137.508) % 360, 68, 62) : hsl2hex((32 + i * 137.508) % 360, 58, 55);
// labels for catalog categories the CatPicker has fetched this session — lets a just-added (staged, not yet
// saved+polled) catalog cat show its provider label immediately, before Store.catLabels carries it.
const _CATALOG_LABEL_CACHE = {};
// If a resolved label has NO capital letters (a bare list name like "timeweb"), capitalise its first letter —
// but leave intentional casing alone ("iCloud", "YouTube" stay as-is).
export const capFirst = s => (typeof s === "string" && s && !/[A-Z]/.test(s)) ? s.charAt(0).toUpperCase() + s.slice(1) : s;
// A block-list category (the blku_* union or a blk:* source) — rides the smart chain for its drop verdict but is
// NOT a routing destination, so it's excluded from the destination stats (Top destinations / flow map).
export const isBlockCat = c => /^blku?[_:]/i.test(String(c));
export function catLabelOf(c) {   // built-in label · custom-list title (keyed by the list's id AND name, so whichever the node emits resolves to the human title) · inline custom → "Custom" · else the id
  if (c === "uncat") return "Uncategorised";
  const lt = {};
  (Store.panelSettings?.custom_lists || []).forEach(l => { if (l && l.title) { if (l.id) lt[l.id] = l.title; if (l.name) lt[l.name] = l.title; } });
  if (isProviderCat(c)) return capFirst(prettyCatLabel(c, (Store.catLabels || {})[c] || _CATALOG_LABEL_CACHE[c]));   // provider list → humanised (country names etc.)
  return capFirst(SMART_CAT_LABEL[c] || (Store.catLabels || {})[c] || lt[c] || _CATALOG_LABEL_CACHE[c] || (String(c).startsWith("custom") ? "Custom" : c));
}
// Host/IP capability flags for a list — ALWAYS Host first, IP second (house rule).
export const capBadges = caps => html`<span class="capbs">
  ${caps && caps.host ? html`<span class="capb host" title=${T("Matchable by domain — needs Force-DNS or SNI mode")}>${T("Host")}</span>` : null}
  ${caps && caps.ip ? html`<span class="capb ip" title=${T("Matchable by IP range — works in every mode")}>${T("cap|IP")}</span>` : null}</span>`;
// A provider-catalog id is "<prov>:<rawid>"; return the provider's display label (MetaCubeX / v2fly / …) for the source tag.
export const isProviderCat = c => typeof c === "string" && c.includes(":") && !String(c).startsWith("custom");
// A "Curated" category = one of the panel's own hand-maintained built-in sets (bare id, no ":"). These are presented
// as the first-class "Curated" provider — the old "built-in" concept, retired. ("all" is the catch-all, not a list.)
export const isCuratedCat = c => typeof c === "string" && !c.includes(":") && c !== "all" && c !== "custom" && !String(c).startsWith("custom") && SMART_CAT_LABEL[c] != null;
// The provider a category belongs to: "<prov>" for a namespaced catalog id, "curated" for a built-in, else "".
export const providerOf = c => isProviderCat(c) ? String(c).split(":")[0] : (isCuratedCat(c) ? "curated" : "");

/* Where a provider's lists are actually used, walked over the panel's own view of the fleet (§6.4).
 *
 * Turning a provider off is not a display setting: the sync manifest omits every category namespaced to a
 * disabled provider, and the node then DELETES that set — so each of these rules stops routing on the next
 * sync, in silence. The count exists so the row can say how far that reaches before the switch moves.
 *
 * "Used by" counts a rule that NAMES one of the provider's lists, whether or not that rule is switched on
 * today. Counting only the live ones would read more exact and then say nothing at all about a fleet whose
 * rules are all parked — which is the one case where the operator has no other way to find out that
 * re-enabling a rule later will do nothing.
 *
 * Three places hold interface rules and all three matter: wg/awg interfaces in `describe`, and the
 * self-contained kinds, whose rules live on the node record (`wdtt_cfg` / `csqtt_cfg`) because the node
 * reports no `describe` entry for them. Blocking is deliberately out: its feeds are a separate registry
 * with a separate toggle, and mixing the two counts would name a number neither switch controls. */
/* One line for everything a save could not KEEP (§5.4).
 *
 * Three things used to make the panel store less than it was given, and all three were silent: a token no
 * grammar can read, a rule naming a list that is no longer in any catalog, and — before this — a save refused
 * outright because ONE entry was bad, which is how an interface becomes unsavable by the very edit that would
 * fix it. The panel is lenient now and says what it left out; this renders that.
 *
 * The wording lives here rather than on the panel because only the browser can finish the sentence: it holds
 * the provider registry that turns `mc:netflix` into "no longer published by MetaCubeX", so the server ships a
 * discriminator and the operator gets a name.
 *
 * Reaching this at all with an `unreadable` is a disagreement between the two classifiers — `egressSaveBlock`
 * refuses to build a badge the panel would then throw away — which is what the shared vector table exists to
 * catch. Loud on purpose for exactly that reason. */
export function reportDropped(r) {
  const rep = ((r && r.data) || {}).dropped || {};
  const list = rep.entries || [];
  const total = rep.total || list.length;   // the server caps what it carries back; the count stays whole
  if (!list.length) return;
  const parts = list.slice(0, 6).map(d => {
    const e = String((d && d.entry) || "");
    // A whole LIST dropped is not a token dropped: every entry in it was unreadable, so the row the
    // operator just saved is gone rather than shortened. Same report, its own sentence — "couldn't be
    // read" beside a list TITLE would send them looking for a bad character in the name.
    if ((d || {}).reason === "list_empty") return T("the list {v1} had nothing readable in it — not saved", { v1: e });
    if ((d || {}).reason !== "unknown_list") return T("{v1} couldn't be read", { v1: e });
    const prov = provLabelOf(e);
    return prov ? T("{v1} is no longer published by {v2}", { v1: catRawId(e), v2: prov })
                : T("{v1} is no longer a list the panel knows", { v1: e });
  });
  if (total > parts.length) parts.push(T("…and {v1} more", { v1: total - parts.length }));
  toast(T("Saved — {v1} not kept: {v2}", { v1: plural(total, "entry"), v2: parts.join("; ") }), "warn", 9000);
}

/* What the fleet's routing rules NAME, read once (§1.4, §6.4).
 *
 * A rule is what makes a list resident: the sync manifest is built from the rules, and the node pulls what it
 * names. `catalog_cats` is the other half — a PIN, "keep this list here even when no rule uses it" — and it is
 * the only half Settings used to show. That was fine while `catalog_cats` also gated the picker, because then
 * nothing could be routed without first appearing there. The field ended that: a list can now be routed on a
 * node that has never had it in `catalog_cats`, so a screen that renders only the pins describes a subset of
 * what the node is actually holding, and says nothing about the common case.
 *
 * READ FROM `rule_cats`, WHICH THE PANEL BUILDS FROM THE NODE RECORD. This used to walk `Store.describe`, and
 * that was wrong in a way nothing on screen would have shown: describe is built from the node's SNAPSHOT, so
 * a node that is down, restarting, or reporting a subset of its interfaces drops those interfaces — and their
 * rules — out of every count built on it. The blast radius of disabling a provider would have read low, and
 * the routing-lists grid would have quietly lost rows, on exactly the nodes an operator is most likely to be
 * worrying about. Rules are panel state; they do not stop existing because a node went quiet.
 *
 * Custom lists are left out: they have their own section and their own per-node control, which is a gate
 * (`disabled_nodes`) rather than a pin, and folding the two into one grid would put two different mechanisms
 * behind one identical-looking switch. */
const isListCat = c => !!c && (isProviderCat(c) || isCuratedCat(c));

/** {nodeId: Set(category)} for the whole fleet, in one walk. */
export function fleetRuleCats() {
  const out = {};
  for (const n of (Store.nodes || [])) {
    const s = new Set();
    for (const cats of Object.values(n.rule_cats || {}))
      for (const c of (cats || [])) if (isListCat(c)) s.add(c);
    out[n.id] = s;
  }
  return out;
}

export function providerUsage(pid) {
  const out = { rules: 0, ifaces: 0 };
  if (!pid) return out;
  for (const n of (Store.nodes || []))
    for (const cats of Object.values(n.rule_cats || {})) {
      const hits = (cats || []).filter(c => providerOf(c) === pid).length;
      if (hits) { out.rules += hits; out.ifaces++; }
    }
  return out;
}
// Provider list ids are cryptic (bare ISO country codes "ad"/"ae", "category-ads-all", "tld-cn"). Make them human:
// 2-letter codes → the country name via the browser's built-in Intl.DisplayNames (no hardcoded country table);
// known prefixes get expanded; everything else is title-cased. `fallback` = the panel's plain label.
const _REGION_NAMES = (() => { try { return new Intl.DisplayNames(["en"], { type: "region" }); } catch { return null; } })();
const _titleize = s => String(s).replace(/[-_]+/g, " ").trim().replace(/\b([a-z])/g, (_, c) => c.toUpperCase());
// Curated friendly names for popular service ids — the providers ship NO titles/descriptions (their lists are
// just id-named files), so this is our own polish for the common ones. Everything else falls back to Intl country
// names / prefix expansion / title-case. Keyed by the provider's raw id (after the "<prov>:").
// Built on FIRST READ, never at import: modules load before loadLang() resolves, so a T() evaluated
// here freezes in English whatever the catalog says (see --frozen). A memoised FUNCTION rather than a
// lazy array/object facade — Dropdown calls flatMap() on its options, and a facade only ever has the
// methods someone remembered to forward.
let _cat_friendly = null;
export const CAT_FRIENDLY = () => (_cat_friendly || (_cat_friendly = {
  meta: "Meta / Facebook", facebook: "Meta / Facebook", openai: "ChatGPT / OpenAI", twitter: "Twitter / X",   // i18n-keys: brand names
  xai: "Grok / xAI", grok: "Grok / xAI", anthropic: "Claude / Anthropic", claude: "Claude / Anthropic",   // i18n-keys: brand names
  gemini: T("Gemini (Google AI)"), perplexity: T("Perplexity AI"), deepseek: "DeepSeek", copilot: T("Microsoft Copilot"),   // i18n-keys: brand names
  google: "Google", youtube: "YouTube", netflix: "Netflix", telegram: "Telegram", whatsapp: "WhatsApp",   // i18n-keys: brand names
  instagram: "Instagram", tiktok: "TikTok", github: "GitHub", disney: "Disney+", spotify: "Spotify",   // i18n-keys: brand names
  twitch: "Twitch", reddit: "Reddit", discord: "Discord", vk: "VK", yandex: "Yandex", cloudflare: "Cloudflare",   // i18n-keys: brand names
  ru_gov: T("Russian Government"), ru_banks: T("Russian Banks"), ru_social: T("Russian Social (VK / OK)"),
}));
export function prettyCatLabel(id, fallback) {
  const rid = String(id || "").includes(":") ? String(id).split(":")[1] : String(id || "");
  if (CAT_FRIENDLY()[rid.toLowerCase()]) return CAT_FRIENDLY()[rid.toLowerCase()];   // curated friendly name (ids vary in case across providers)
  if (/^[a-z]{2}$/i.test(rid) && _REGION_NAMES) {                 // ISO 3166 alpha-2 → country name
    try { const n = _REGION_NAMES.of(rid.toUpperCase()); if (n && n.toUpperCase() !== rid.toUpperCase()) return n; } catch (e) {}
  }
  let m;
  if ((m = rid.match(/^geolocation-(.+)$/))) return T("Geolocation: {v1}", { v1: prettyCatLabel(m[1], null) });
  if ((m = rid.match(/^category-(.+?)(-all)?$/))) return _titleize(m[1]) + (m[2] ? " (all)" : "");
  if ((m = rid.match(/^tld-(.+)$/))) return T("TLD .{v1}", { v1: m[1].toLowerCase() });
  return fallback || _titleize(rid) || rid;
}
export const catRawId = id => String(id || "").includes(":") ? String(id).split(":")[1] : String(id || "");   // the provider's raw id ("telegram")
// Providers ship NO descriptions (their lists are bare id-named files). These are OUR curated one-liners for the
// popular categories; everything else shows a live sample of its records instead ("e.g. netflix.com, fast.com").
// Built on FIRST READ, never at import: modules load before loadLang() resolves, so a T() evaluated
// here freezes in English whatever the catalog says (see --frozen). A memoised FUNCTION rather than a
// lazy array/object facade — Dropdown calls flatMap() on its options, and a facade only ever has the
// methods someone remembered to forward.
let _cat_desc = null;
export const CAT_DESC = () => (_cat_desc || (_cat_desc = {
  google: T("Google search, accounts & core services"), youtube: T("YouTube video + its CDN"),
  netflix: T("Netflix streaming & app"), meta: T("Facebook, Instagram & WhatsApp"), facebook: T("Facebook, Instagram & WhatsApp"),
  telegram: T("Telegram messenger"), whatsapp: T("WhatsApp messenger"), instagram: "Instagram", twitter: "Twitter / X",   // i18n-keys: brand names
  openai: T("ChatGPT & the OpenAI API"), tiktok: T("TikTok video"), github: T("GitHub & its CDN"), disney: T("Disney+ streaming"),
  spotify: T("Spotify audio"), twitch: T("Twitch live streaming"), reddit: "Reddit", discord: T("Discord voice & chat"),   // i18n-keys: brand name
  cloudflare: T("Cloudflare CDN / edge network"), vk: T("VKontakte"), yandex: T("Yandex services"),
  ru_gov: T("Russian government sites"), ru_banks: T("Russian banks"), ru_social: T("Russian social (VK / OK)"),
  claude: T("Claude & the Anthropic API"), grok: T("Grok (xAI) — grok.com & x.ai"),
  gemini: T("Google Gemini AI — kept separate from the rest of Google"), copilot: T("Microsoft & GitHub Copilot"),
  signal: T("Signal private messenger"),
  ru_net: T("The whole Russian IP space (GeoIP) — works in every mode"),
  ru_blocked: T("Sites blocked inside Russia — comprehensive (~86k domains, heavy)"),
  ru_blocked_media: T("News / media blocked inside Russia — light subset (~130)"),
}));
export const catDescOf = id => CAT_DESC()[catRawId(id).toLowerCase()] || "";
// Info icon that shows a description bubble on hover — used for curated presets (which have no external URL to link).
export const DescInfo = ({ text }) => text ? html`<span class="catrow-info descinfo" tabindex="0" role="note" onClick=${e => e.stopPropagation()}>
  <${Ic} i="info"/><span class="descbub" role="tooltip">${text}</span></span>` : null;
// The provider's GitHub page for a specific list — where the operator can see exactly what it contains (the raw
// file, or blackmatrix7's folder with its README). Built from the same paths we fetch, as human github.com URLs.
export function catListUrl(id, caps) {
  const rid = catRawId(id), prov = String(id).includes(":") ? String(id).split(":")[0] : "";
  const host = !!(caps && caps.host);
  switch (prov) {
    case "mc": return "https://github.com/MetaCubeX/meta-rules-dat/blob/meta/geo/" + (host ? "geosite" : "geoip") + "/" + rid + ".list";
    case "v2": return "https://github.com/v2fly/domain-list-community/blob/master/data/" + rid;
    case "ls": return "https://github.com/Loyalsoldier/geoip/blob/release/text/" + rid + ".txt";
    case "rf": return "https://github.com/1andrevich/Re-filter-lists/blob/main/" + rid + ".lst";
    case "bm": return "https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Clash/" + rid;
    default: return "";
  }
}
// Record count for a provider-catalog cat (Host+IP tiers), shipped by the panel in Store.catSizes {cat:{ip,host}}.
export const fmtCount = n => n == null ? "…" : n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "") + "k" : String(n);
// "142 hosts · 38 nets" style summary from per-tier counts (Host first). Empty string when nothing is known.
// plural(), not an "s" glued on: Russian picks between three forms, and this line is now on every badge in
// every rule rather than tucked inside a Settings row nobody opens.
export function sizeSummary(host, ip, pat) {
  const p = [];
  if (host) p.push(plural(host, "host").replace(String(host), fmtCount(host)));
  if (ip) p.push(plural(ip, "net").replace(String(ip), fmtCount(ip)));
  // PATTERNS COUNT TOO, and only a custom list has any — a provider list resolves to hosts and nets on the
  // panel, so those callers pass nothing and read exactly as before. Left out, this line said "1 host · 2
  // nets" for a list that also held six patterns, and said NOTHING AT ALL for a list that was only patterns:
  // an entry the operator had just typed, reported as an empty list. `pattern`, not `text pattern` — that
  // noun means the three kinds §12.1's cap counts, and this counts all six.
  if (pat) p.push(plural(pat, "pattern").replace(String(pat), fmtCount(pat)));
  return p.join(" · ");
}
// A small record-count pill that, on hover, shows the list's counts (Host domains · IP nets) + the first few
// entries. Provider cats lazy-fetch /api/list-info (session-cached); custom lists read their own targets. With
// `eager`, the count loads on mount so it shows inline (used in the catalog search where sizes aren't preshipped).
const _LIST_INFO_CACHE = {};   // cat -> resolved list-info (count + sample), so CatalogRow paging never re-fetches
// Plain "N hosts · M nets" text for a list. Counts come from the panel's shipped cat_sizes (routed cats) or the
// custom list's own targets — no fetch, no hover bubble (the full sample lives inline in the catalog browse row).
export function ListInfo({ cat, list }) {
  let hostN = null, ipN = null;
  let patN = 0;
  if (list) { const b = listBuckets(list); hostN = b.host.length; ipN = b.ip.length; patN = b.pat.length; }
  else if (cat) { const s = (Store.catSizes || {})[cat] || {}; hostN = s.host; ipN = s.ip; }
  const summary = sizeSummary(hostN || 0, ipN || 0, patN);
  if (!summary) return null;
  return html`<span class="listsize">${summary}</span>`;
}

// A rich catalog-browse row (the "Add from catalog" list): title + the raw id (name) dimmed under it, the
// provider tag, a description (curated, else a live sample of records), "N hosts · M nets", and Host/IP tags.
// Eager-loads /api/list-info (session-cached) for the counts + samples. Providers ship no descriptions, so the
// second line falls back to "e.g. <first few records>" — self-explanatory from the list's own contents.
export function CatalogRow({ it, added, onPick }) {
  const [fetched, setFetched] = useState(() => _LIST_INFO_CACHE[it.id] || null);
  // A LIST THE OPERATOR WROTE IS NOT A CATALOG LIST. Its targets are in panel settings, right here, and
  // /api/list-info answers `400 bad cat` for one by design — so this asked the panel about every "Your
  // lists" row on every dropdown open, got a 400 for each, and left the row reading `—` where the same
  // list's own BADGE reads "2 nets". The mapper already hands the record over as `it.list`; the tiers are
  // built from it in the shape the endpoint returns, so nothing below this line has to know the difference.
  // Only a non-empty tier is included, exactly as the server does, or a domain-less list shadows its own
  // IP samples with an empty (and truthy) array.
  const own = it.list, ownB = own ? listBuckets(own) : null;
  const ownDoms = ownB ? ownB.host : [], ownIps = ownB ? ownB.ip : [];
  const info = own ? { tiers: { ...(ownDoms.length ? { host: { n: ownDoms.length, sample: ownDoms.slice(0, 4) } } : {}),
                               ...(ownIps.length ? { ip: { n: ownIps.length, sample: ownIps.slice(0, 4) } } : {}) } }
                   : fetched;
  // DEBOUNCED, because a keystroke replaces this whole page: fifty rows unmount and fifty more mount, and
  // without the delay each keystroke fired fifty requests for rows nobody looked at. The ask itself polls
  // while the panel says it is still fetching (askListInfo) — it never holds a request thread open.
  useEffect(() => {
    if (own) return;                                  // nothing to fetch, and the endpoint would refuse it
    if (info && !(info.tiers && Object.keys(info.tiers).some(k => info.tiers[k] && info.tiers[k].pending))) return;
    let live = true;
    const t = setTimeout(() => askListInfo(it.id, () => live && setFetched(_LIST_INFO_CACHE[it.id] || null),
                                           { waitMs: LIST_ASK_MS, errOnGiveUp: false }), 250);
    return () => { live = false; clearTimeout(t); }; }, [it.id]);
  const title = prettyCatLabel(it.id, it.label), rid = catRawId(it.id), desc = catDescOf(it.id);
  const hostD = info && info.tiers && info.tiers.host, ipD = info && info.tiers && info.tiers.ip;
  const summary = sizeSummary((hostD && hostD.n) || 0, (ipD && ipD.n) || 0);
  const samples = ((hostD && hostD.sample) || (ipD && ipD.sample) || []).slice(0, 4);
  const more = (((hostD && hostD.n) || (ipD && ipD.n) || 0) > samples.length);
  const anyFailed = info && info.tiers && Object.keys(info.tiers).some(t => info.tiers[t].failed);
  const anyPending = info && info.tiers && Object.keys(info.tiers).some(t => info.tiers[t].pending);
  const empty = info && !info.err && !summary && !samples.length && !anyFailed && !anyPending;   // resolved to 0 routable records
  const sub = desc || (samples.length ? "e.g. " + samples.join(", ") + (more ? "…" : "")
    : (!info || anyPending ? T("preparing…") : anyFailed ? T("couldn't load — will retry") : empty ? T("no routable records") : "—"));
  return html`<button type="button" class=${"catrow" + (added ? " sel" : "") + (empty ? " off" : "")} disabled=${empty} title=${empty ? T("This list has no routable records") : ""} onClick=${() => !empty && onPick(it.id)}>
    <span class=${"catpick-tick" + (added ? " on" : "")}>${added ? "✓" : ""}</span>
    <div class="catrow-main">
      <div class="catrow-l1"><span class="catrow-title">${title}</span>${rid.toLowerCase() !== title.toLowerCase() ? html`<span class="catrow-id">${rid}</span>` : null}${CURATED_HEAVY[it.id] ? html`<span class="catrow-heavy" title=${T("Large list — noticeable memory / reload on any node that routes it")}>${T("tag|heavy")}</span>` : null}</div>
      ${sub ? html`<div class="catrow-l2">${desc ? html`<span class="catrow-desc">${desc}</span>` : null}${desc && samples.length ? html`<span class="catrow-eg"> · e.g. ${samples.join(", ")}${more ? "…" : ""}</span>` : (!desc ? html`<span class="catrow-eg">${sub}</span>` : null)}</div>` : null}
    </div>
    <div class="catrow-right">
      <${ProvTag} id=${it.id} label=${it.provider_label || provLabelOf(it.id)}/>${capBadges(it.caps)}${summary ? html`<span class="catrow-size">${summary}</span>` : null}
      ${catListUrl(it.id, it.caps) ? html`<a class="catrow-info" href=${catListUrl(it.id, it.caps)} target="_blank" rel="noopener" title=${T("View this list on GitHub")} onClick=${e => e.stopPropagation()}><${Ic} i="info"/></a>`
        : html`<${DescInfo} text=${catDescOf(it.id)}/>`}</div>
  </button>`;
}
export function provLabelOf(c) {
  const pid = providerOf(c);
  if (!pid) return "";
  return ((Store.catalogProviders || []).find(p => p.id === pid) || {}).label || (pid === "curated" ? T("Curated") : pid);
}
// Each provider gets a distinct colour (default palette + a Panel-settings per-mode override, like turn forks).
export const CAT_PROVIDER_DEFAULTS = { mc: { color: "#5B8FF9", colorL: "#2C6FD6" }, v2: { color: "#61DDAA", colorL: "#1E9E6E" },
  ls: { color: "#F6BD16", colorL: "#B8890A" }, rf: { color: "#E8684A", colorL: "#C2452A" }, bm: { color: "#B07BE0", colorL: "#8347C0" },
  curated: { color: "#E85D9E", colorL: "#C43B7E" } };   // "Curated" — the panel's own maintained set (rose; distinct from every fetched provider)
export function providerColor(prov) {
  const ov = (Store.panelSettings && Store.panelSettings.provider_colors) || {};
  const d = CAT_PROVIDER_DEFAULTS[prov] || (prov === "custom" ? { color: "#8A94A6", colorL: "#5E6875" } : { color: "#8FA8C0", colorL: "#5E7085" });
  return pickThemed(ov[prov], d.color, d.colorL);
}

// Provider source tag — colour-coded by provider. Curated built-ins and catalog cats both get a coloured chip;
// only genuinely source-less chips (a raw "Custom" label) stay plain. `plain` forces the neutral chip.
export function ProvTag({ id, label, plain }) {
  // A CUSTOM LIST HAS A SOURCE TOO. `providerOf` answers "" for one — its id carries no `provider:` prefix and
  // it is not a curated built-in — so the badge fell through to the neutral chip while the SAME list wore
  // `providerColor("custom")` in the settings grid, which reads as two different kinds of thing. The colour
  // exists (`#8A94A6`); only this path was not asking for it. `plain` still forces neutral, for a label with
  // genuinely no source behind it.
  const prov = providerOf(id) || (customListOf(id) ? "custom" : "");
  if (plain || !prov) return html`<span class="catpick-src legacy">${label}</span>`;
  return html`<span class="catpick-src" style=${"--pc:" + providerColor(prov)}>${label || provLabelOf(id)}</span>`;
}
// Routing-mode metadata: icon + labels + the full explanation (shown in the mode banner).
// NOTE: all three modes are kernel-based — there is NO "Kernel" mode. The IP-only mode is "Default". (Stored value
// stays "kernel"|"forcedns"|"sni" — the node reads it — but never DISPLAY the word "Kernel".) See MODES for the text.
// Each entry is framed as an OPTIONAL host-matching layer ON TOP of the always-on IP base: `adds` = what the layer
// does, `bene` = its upside (+), `cost` = its trade-off (−), `exp` = the full description under the selected card.
/* Built on first use, not at module load: every string here goes through T(), and T() only answers after
   loadLang(). Cached for the process — setLang() reloads the page. (Same rule as ui.js's label tables.)
   MODE_META stays the exported NAME so call sites read unchanged; it is a Proxy over the built table. */
function buildModeMeta() {
  /* ⚠️ THE ARBITRATION IS WRITTEN ONCE, HERE, AND EVERY SENTENCE ABOUT IT IS DERIVED FROM IT.
     It used to be stated twice: this table's `overlaps` per mode, and a HARDCODED "the most specific rule
     wins" on the rule list and its four collapsed summaries. They disagreed — the label claimed
     specificity on all four engines, while this table correctly said IP-only and Kernel-SNI answer by rule
     ORDER. On those two the screen contradicted itself, and the wrong half was the actionable one: an
     operator told ordering does not matter stops dragging rows, which is the only control that works
     there. (§10.4y corrected `first match wins` → `most specific wins` GLOBALLY, which fixed two engines
     and broke the other two — one sentence cannot describe four engines.)
     A mode now names its arbitration and nothing else; the card sentence, the rule-list label and the
     collapsed summary all read this table. */
  const WINS = {
    order:    { card: T("First match — the order you set"),       label: T("— the first matching rule wins") },
    specific: { card: T("Most specific name; IP rules in order"), label: T("— the most specific rule wins") },
  };
  const arb = k => ({ wins: k, overlaps: WINS[k].card, winsLabel: WINS[k].label });
  return {
  kernel:   { icon: "globe",  label: T("Default routing"), short: T("IP only"), tag: T("no host layer"),
    adds: T("Just the always-on IP layer — no domain matching added"),
    bene: [T("Simplest & most robust · never touches DNS · carries all traffic (calls, UDP, QUIC)")],
    cost: T("Can't separate services that share IPs (YouTube vs Google), no Host routing"),
    block: { s: "−", t: T("Blocks by IP / threat-feed only — domain content filters can't apply") },
    exp: T("Matches by destination IP (GeoIP / ASN) — routing never depends on DNS, so your clients' DoH, DoT and plain DNS all keep working untouched. Simplest and most robust; it just can't separate services that share IPs (YouTube vs Google), and a CDN category catches everything behind it."),
    // NO `blocks:` HERE, and not an oversight. What an engine can block is already the +/− `block` lines
    // above — "Blocks by IP / threat-feed only", "Enforces domain content filters directly" — and saying it
    // twice in one card cost a row of height for a second phrasing of the same fact.
    routes: T("IP ranges, networks (AS)"),
    ...arb("order"),
  },
  forcedns: { icon: "compass", label: T("Force-DNS"), short: T("Host via DNS"), tag: T("host layer · via DNS"),
    adds: T("Adds domain matching by resolving your clients' DNS through the node"),
    bene: [T("Per-service precise · fills before the first connection (no first-hit miss)")],
    cost: T("Intercepts & downgrades client DNS — blocks their DoH / DoT"),
    block: [{ s: "+", t: T("Enforces domain content filters directly") },
            { s: "−", t: T("Long block lists cost CPU per DNS query — keep them small (≈100k domains)") }],
    exp: T("The node becomes your clients' resolver and blocks their encrypted DNS — both DoH (known providers) and all DoT — so it can route by hostname too, per-service precise. Trade-off: it sees and downgrades the client's DNS, can break a client that insists on its own encrypted DNS, and a DoH server it doesn't recognise can still slip past. A client answering from its own cache never asks, so a rule you add after it looked a name up takes effect on its next lookup — the node caps what clients may keep at 60 seconds for exactly that reason."),
    routes: T("IP ranges, networks, sites, zones"),
    ...arb("specific"),
  },
  sni_kernel: { icon: "cpu", label: T("Kernel SNI"), short: T("Host via SNI"), tag: T("host layer · SNI in-kernel"),
    adds: T("Scans the TLS SNI in-kernel — client DNS stays private"),
    bene: [T("Daemonless & parallel per-CPU · lightest at high connection rates"), T("Wins stability and high-connection-rate CPU over Hybrid")],
    cost: T("Substring match only · needs xt_string + ipset on the node"),
    block: { s: "−", t: T("Domain content filters inert — steer them to Force-DNS / Hybrid") },
    exp: T("Scans the SNI from each TLS handshake entirely in the kernel (xt_string) and learns each destination's IP into the routing set — no userspace helper, and your clients' DNS (DoH, DoT or plain) is never touched. Runs in parallel across CPUs, so it stays light even at high connection rates. Needs the node's kernel to provide xt_string + ipset. It matches a run of characters, not a name: a rule for example.com also matches notexample.com.evil.net, which is why whole-ending rules like *.ru cannot be matched here at all — this node counts them and says so, so you can move them to Force-DNS or Hybrid SNI. Names hidden by ECH, and QUIC / HTTP3, fall back to IP routing."),
    routes: T("IP ranges, networks, sites (as text), text patterns"),
    ...arb("order"),
  },
  sni:      { icon: "eye", label: T("Hybrid SNI"), short: T("Host via SNI"), tag: T("host layer · SNI in userspace"),
    adds: T("Parses the TLS SNI in a small helper — client DNS stays private"),
    bene: [T("Precise parsed-SNI matching · unbothered by big lists"), T("Has fewer kernel deps, wins accuracy over Kernel")],
    cost: T("Runs a helper process (fails open — learning pauses — if it stops)"),
    block: { s: "+", t: T("Enforces domain content filters — learns & drops; best for large block lists") },
    exp: T("Routes by hostname by parsing the SNI from each TLS handshake in a small userspace helper, so your clients' DNS — DoH, DoT or plain — is never touched, observed or downgraded: the connection stays encrypted end-to-end. Parses the real SNI field (precise, fine with very large lists). Learns each destination on its first connection (a brand-new host routes on the next one); names hidden by ECH, and QUIC / HTTP3, fall back to IP routing."),
    routes: T("IP ranges, networks, sites, zones, name patterns, text patterns"),
    ...arb("specific"),
  },
}; }
let _modeMeta = null;
/* "…turn them on in <Settings ▸ Routing & Blocking>." — the tail is a button. */
function noFilterCats(onNav) {
  const [a, b] = Tsplit("No content-filter categories are enabled on this node yet — turn them on in {where}.", "where");
  return html`<${Fragment}>${a}<button type="button" class="linkbtn" onClick=${onNav}>${T("Settings ▸ Routing & Blocking")}</button>${b}<//>`;
}
/* "Type <RESET LEARNED> or <RESET ALL> to confirm your action" — two coloured literals. */
// ⚠️ ONE DEFINITION EACH. The token an operator must type was written out three times — in the prompt, in
// the placeholder and in the comparison — with only the placeholder translatable. Translate that one and the
// panel asks for a phrase the gate does not accept; leave it and a Russian operator types a Latin phrase
// nothing else on the screen uses. Both are avoided by deriving all three from the same call.
const TOK_LEARN = () => T("token|RESET LEARNED");
const TOK_ALL = () => T("token|RESET ALL");
function resetPrompt() {
  const one = T("Type {learn} or {all} to confirm your action");
  const [a, r1] = [one.split("{learn}")[0], one.split("{learn}").slice(1).join("{learn}")];
  const [b, c] = [r1.split("{all}")[0], r1.split("{all}").slice(1).join("{all}")];
  return html`<${Fragment}>${a}<span class="ct-learn"><${ConfirmPhrase} phrase=${TOK_LEARN()} bold=${true}/></span>${b}<span class="ct-all"><${ConfirmPhrase} phrase=${TOK_ALL()} bold=${true}/></span>${c}<//>`;
}

export const MODE_META = new Proxy({}, { get: (_, k) => (_modeMeta || (_modeMeta = buildModeMeta()))[k] });

/* What this NODE's engine does with an overlap: "order" | "specific" | "" when the record has not loaded.
   ⚠️ "" MUST NOT collapse into the kernel default. "We could not look the engine up" and "it is IP-only"
   are different answers, and defaulting the first to the second turns a missing record into a confident
   wrong promise — §4.2 keeps the same two apart for badges, for the same reason. The first draft of this
   wrote `(record || {}).routing_mode || "kernel"`, which applies the fallback to a missing RECORD rather
   than a missing FIELD, and an unknown node duly announced "first match wins". */
const winsOf = nodeId => {
  const n = (Store.nodes || []).find(x => x.id === nodeId);
  return n ? ((MODE_META[n.routing_mode || "kernel"] || {}).wins || "") : "";
};

/* The COLLAPSED summary — "3 rules · most specific wins" — for the four sheets that show routing behind a
   Disclosure. One helper rather than four copies, because four copies is how the promise drifted from the
   mode card in the first place.
   ⚠️ Each sentence is a literal directly inside its OWN Trich call. Choosing the key with a ternary and
   passing it to one call would make both invisible to the catalog audit, which reads the literal that
   FOLLOWS the call — the exact defect that left two sentences untranslatable in ConfigMigrationCard. */
/* The collapsed Disclosure line, which is the DEFAULT view — so it is the only thing an operator sees after
   changing a node's match mode. It used to say "5 rules · most specific wins" whatever the engine could
   actually run, and every badge the new engine cannot match was dimmed one click away, behind a fold.
   Switching a node to IP-only turns every host-tier target inert at once; the summary now says how many,
   because a count that silently stays 5 is the `*.ru` class again — accepted, stored, routing nothing.
   Takes the ROWS, not a count: it needs the badges to ask the gate about them. */
export function rulesSummary(nodeId, rows, catchAll) {
  const list = rows || [];
  const n = list.length;
  if (!n) return T("no rules yet");
  const a = { v1: n, v2: pluralWord(n, "rule") };
  const w = winsOf(nodeId);
  const head = w === "order" ? Trich("*{v1}* {v2} · first match wins", a)
             : w === "specific" ? Trich("*{v1}* {v2} · most specific wins", a)
             : Trich("*{v1}* {v2}", a);    // engine unknown — count only, promise nothing
  // NOTHING TO SAY WITHOUT A MODE. An unloaded node record means the gate would refuse everything, so this
  // counts nothing rather than announcing that every rule is broken — the same fail-safe `listGate` and
  // `useHostOnNode` take. A locked legacy row is re-emitted verbatim and is not ours to judge.
  const rec = (Store.nodes || []).find(x => x.id === nodeId);
  const mode = rec ? (rec.routing_mode || "kernel") : "";
  let off = 0;
  if (mode) for (const r of list) if (!r.locked)
    for (const bg of (r.badges || [])) if (!badgeGate(mode, nodeId, bg).ok) off++;
  // ⚠️ AND A DESTINATION THAT IS GONE, which is a different fact from a target this engine cannot run and
  // must not be folded into it: one says "this node's mode can't match that", the other says "the place you
  // told it to send the traffic is not there any more". Counted HERE because this section is COLLAPSED by
  // default — an operator who never opens it would otherwise never learn that a rule routes nothing.
  // Measured on the live fleet: svo-im/awg0's catch-all names a node id that is not in nodes.json, the
  // control rendered blank inside the section, and the summary said only "1 rule".
  // ⚠️ AND IT FAILS SAFE, like the count above it. `off` stays 0 when the node record has not loaded ("the
  // gate would refuse everything, so this counts nothing rather than announcing that every rule is
  // broken"); this had the opposite reflex — an empty `Store.nodes` makes `known` empty, and every single
  // `action:"exit"` rule then counts as pointing nowhere. The collapsed summary would read
  // "3 rules · 3 rules pointing nowhere" on a perfectly healthy interface, on any render that lands before
  // /api/state has answered. A detection that cannot see must report nothing, not everything.
  // [[lesson-detection-failure-fail-safe]]
  const _nr = (Store.nodes || []).find(x => x.id === nodeId);
  const known = new Set((Store.nodes || []).map(n => n.id));
  const _xids = new Set(((_nr || {}).exits || []).map(e => String(e.id)));
  const _gone = r => (r && !r.locked)
    && ((r.action === "exit" && r.node && !known.has(r.node))
        || (r.action === "dev" && r.exit_id && !_xids.has(String(r.exit_id))));
  let dead = _nr ? list.filter(_gone).length + (_gone(catchAll) ? 1 : 0) : 0;
  const parts = [];
  if (off) parts.push(T("{v1} can't run here", { v1: plural(off, "target") }));
  // ⚠️ THE COUNT IS NOT THE SUBJECT OF A VERB THAT INFLECTS. "{v1} points nowhere" renders "3 rules points
  // nowhere" — the same shape as «1 пир получат» (091ac8e) and the two this release already fixed. Its
  // sibling above gets away with the identical structure because "can't run" does not inflect; "points"
  // does, so this uses a participle, which does not.
  if (dead) parts.push(T("{v1} pointing nowhere", { v1: plural(dead, "rule") }));
  return parts.length ? html`${head}<span class="rs-off"> · ${parts.join(" · ")}</span>` : head;
}

// Match-mode picker — a compact row of four icons (IP · Force-DNS · Kernel-SNI · Hybrid-SNI); the selected one is
// highlighted in its mode colour and its full detail card renders below (see the routing banner). Icon-only keeps
// it tight; the tooltip + the detail card carry the names, so no per-option text is needed here.
export function ModeTabs({ value, onChange }) {
  return html`<div class="rmode-tabs" role="radiogroup">
    ${["kernel", "forcedns", "sni_kernel", "sni"].map(m => { const mm = MODE_META[m], on = m === value;
      return html`<button type="button" role="radio" aria-checked=${on} key=${m} title=${mm.label}
        class=${"rmtab m-" + m + (on ? " on" : "")} onClick=${() => onChange(m)}><${Ic} i=${mm.icon}/></button>`; })}
  </div>`;
}
// Full-width detail for the currently-selected mode (icon + name + tag, what it adds, +benefit / −trade-off, full text).
// Operator recovery: wipe a node's smart-routing state (tables, learned IPs, cached lists), then let it rebuild from
// scratch + re-pull every enabled/curated list from the panel. Destructive → modal confirm, never a browser popup.
export function resetRouting(node, name) {
  openModal(html`<${ResetRoutingSheet} node=${node} name=${name || "node"}/>`);
}
// Two-scope reset: "learned" clears only the node's SNI-learned IPs; "all" wipes tables + learned IPs + list cache
// and rebuilds/re-pulls. Each button is gated by its own typed token ("RESET LEARNED" / "RESET ALL").
export function ResetRoutingSheet({ node, name }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const t = typed.trim();   // case-sensitive: the tokens must be typed in CAPS exactly
  const learnOk = t === TOK_LEARN(), allOk = t === TOK_ALL();
  const run = async scope => {
    if (busy) return; setBusy(true);
    const r = await api.routingReset({ id: node, scope });
    if (r && r.ok === false) toast(srvText(r) || T("Reset failed."), "err", 4500);
    else toast(scope === "learned"
      ? T("Learned IPs cleared — the node forgets them and re-learns on its next sync.")
      : T("Routing reset queued — the node wipes, rebuilds and re-pulls on its next sync."), "ok");
    closeModal();
  };
  return html`<${Sheet} title=${T("Reset routing · {v1}", { v1: name })} onClose=${closeModal}
    foot=${html`<${Fragment}><span class="grow"></span>
      <button class="btn btn-ghost" onClick=${closeModal}>${T("Cancel")}</button>
      <button class="btn btn-warn" disabled=${busy || !learnOk} onClick=${() => run("learned")}><${Ic} i="refresh"/> ${T("Reset learned IPs")}</button>
      <button class="btn btn-danger" disabled=${busy || !allOk} onClick=${() => run("all")}><${Ic} i="refresh"/> ${T("Reset all routing")}</button></>`}>
    <div class="notice warn"><${Ic} i="warn"/><span>${Trich("*Reset learned IPs* clears only the IPs this node has learned from SNI so far — its tables and lists stay in place and it re-learns as traffic flows. *Reset all routing* wipes the smart-routing tables, learned IPs and cached lists, then rebuilds from scratch and re-pulls every list from the panel; routing may blip for a few seconds.")}</span></div>
    <label class="confirm-type"><span>${resetPrompt()}</span>
      <input class="ctype-input" type="text" autofocus spellcheck="false" autocomplete="off" placeholder=${TOK_LEARN() + " / " + TOK_ALL()} value=${typed}
        onInput=${e => setTyped(e.target.value)}/></label>
  <//>`;
}
// Live host-layer health for a node, from its reported smartroute: is the mode's fill engine actually alive (swg-sni
// for SNI, dnsmasq for Force-DNS), plus the SNI first-hit reset count. Surfaces a SILENT host-layer failure (dead
// reader ⇒ host categories quietly stop routing). Hidden for IP-only and for nodes too old to report it (no false alarms).
export function HostHealth({ node, mode, learn, onLearn }) {
  if (mode === "kernel") return null;
  const sr = (Store.stats[node] || {}).smartroute || {};
  if (!sr.mode) return null;                                  // node hasn't reported host-layer health yet → don't guess
  const eng = sr.engine || "";                                // ACTUAL running engine (may differ from configured — see degrade)
  const label = eng === "dns" ? T("DNS resolver") : eng === "sni_kernel" ? T("SNI scanner") : T("SNI parser");
  const ok = sr.engine_ok !== false;
  let extra = null, note = null;
  // Destinations the engine has in its routing sets (geoip + SNI-learned), excluding block-list sets. Kernel-SNI keeps
  // learned IPs in an ipset it doesn't surface, so this reads 0 there — shown only when the node reports set counts.
  const routed = Object.entries(sr.sets || {}).reduce((n, [k, v]) => n + (String(k).includes("blku") ? 0 : (v || 0)), 0);
  // §10.5 item 4: what the node LOWERED from the pattern channel. Every other reading here is about what did
  // NOT fit (`xts_cap`, `sni_cap`), so a node building exactly what it was asked said nothing at all — and
  // Force-DNS, which has no bound to report against, said nothing in every case. `{kind: n}` from the engine
  // that installed it, summed: the operator wants to know the patterns arrived, not which bucket they are in
  // (the kinds are in `smart_status` for anyone reading it). Counted by the engine from what it WROTE, so a
  // lowering that silently built nothing shows 0 here rather than echoing the request back.
  const lowered = Object.values(sr.lowered || {}).reduce((n, v) => n + (v || 0), 0);
  if (routed || lowered || (eng.startsWith("sni") && sr.resets)) {
    const bits = [];
    if (routed) bits.push(T("{v1} routed", { v1: plural(routed, "destination").replace(String(routed), fmtCount(routed)) }));
    if (lowered) bits.push(T("matching {v1}", { v1: plural(lowered, "pattern") }));
    if (eng.startsWith("sni") && sr.resets) bits.push(T("{v1} rerouted", { v1: plural(sr.resets, "new host") }));
    extra = bits.join(" · ");
  }
  if (mode === "sni_kernel" && eng === "sni_user") note = T("kernel SNI scanner unavailable — running userspace SNI parser");   // degraded-open
  // The kernel scanner is one xt_string rule per ENTRY, walked per packet on a first hit, so it takes each
  // category's first N and stops (§6.7). Before this the node applied that silently and nobody could see
  // it: the panel holds the whole list, the node holds the whole list, and only the chain knew. Named here
  // because this is the one place that already answers "what is this node's host layer actually doing".
  //
  // "entries", not "names", since Phase 3: a `contains` operand shares this budget with the list's names —
  // to xt_string they are the same rule — so a category can be truncated with names to spare. `long` is
  // the other way an entry fails to become a rule: xt_string refuses a pattern over 128 bytes outright, and
  // that is worth saying rather than dropping, because it is the one case the operator can actually fix.
  else if (sr.xts_cap && ((sr.xts_cap.capped || []).length || sr.xts_cap.long)) {
    const c = sr.xts_cap, bits = [];
    // NO BUDGET NUMBER IN THE SENTENCE. It used to say "only to the first 256", which is the cap and was
    // true right up until the pattern ceiling landed: a category holding 300 typed patterns builds 100 rules
    // and the sentence claimed 256. The count that is always true — and the only one the operator can act on
    // — is how many entries did not make it. `cap` stays in the payload for anyone reading smart_status.
    if ((c.capped || []).length)
      bits.push(T("{v1} matched only in part here — {v2} not matched", {
        v1: c.capped.map(x => catLabelOf(x)).join(", "), v2: plural(c.missed || 0, "entry") }));
    if (c.long)
      bits.push(T("{v1} too long for this scanner to match — over {v2} characters", {
        v1: plural(c.long, "entry"), v2: c.maxlen }));
    note = bits.join(" · ");
  }
  // The same report for the other engine that bounds something. It was first written as the SAME KEY as
  // xts_cap's — one fact, one phrasing — and the catalog is what showed that was never true: the Russian for
  // that key bakes «записей» (entries) into the sentence, so reusing it would have said "only part of the
  // entries" about a truncation that dropped no entries. Its own key, then, and the difference is the honest
  // one: kernel-SNI drops chain entries, names and substrings together, while this drops text patterns and
  // nothing else.
  //
  // IT NAMES THE OPERANDS, NOT THE CATEGORIES, and that is the difference between a report and a shrug. The
  // node also sends `capped` (the category ids that lost something) and it was written to say WHICH rules
  // stopped matching — but it cannot: a Tier-2 pattern only ever lives in an INLINE CUSTOM rule (a reusable
  // list carries none), and `catLabelOf` renders every inline custom cat as the single word "Custom". So that
  // sentence read "Custom matched only in part here" for one rule and "Custom, Custom" for two. The operands
  // are what the operator typed, `targetLabel` puts the stars back exactly as the badge shows them, and they
  // can be searched for. The count stays, because the sample is bounded and the count is the real size.
  //
  // Naming them matters MORE here than it would per-interface, not less: the node's bound is node-WIDE while
  // the operator's cap is per interface, so this count can exceed anything the open interface shows and the
  // operand that stopped matching may belong to a different one. A category id could not have told them
  // which; the operand can be searched for across the fleet.
  else if (sr.sni_cap && sr.sni_cap.missed) {
    const smp = (sr.sni_cap.sample || []).filter(x => Array.isArray(x) && x.length === 2);
    const more = sr.sni_cap.missed - smp.length;
    const shown = smp.map(([k, v]) => targetLabel(k, v)).join(", ");
    // AND IT NAMES THE LIMIT, which the sibling above deliberately does not — the difference is UNITS, not
    // house style, so do not unify them. `xts_cap` counts chain ENTRIES while the operator typed patterns,
    // and one typed pattern is not one entry, so its number described something the operator could not
    // count. Here both numbers are the same thing: `_SNI_TIER2_MAX` bounds DISTINCT TIER-2 OPERANDS and
    // `missed` counts distinct Tier-2 operands, so "200 past a limit of 1000" is arithmetic the operator can
    // check. Exact, not `fmtCount` — that renders 1000 as "1k", which is the right register for a measured
    // quantity and the wrong one for a decided limit, where the point is that it IS a specific number.
    // `cap` is written in the same object literal as `missed`, so it is there whenever this branch runs.
    const cap = sr.sni_cap.cap;
    // An older node sends no sample at all; then the count is the whole of what is known, and saying just
    // that beats padding it out. Same rule as everywhere else here: fewer facts, never invented ones.
    note = !smp.length
      ? T("{v1} past this node's limit of {v2}", { v1: plural(sr.sni_cap.missed, "text pattern"), v2: cap })
      : T("{v1} past this node's limit of {v2} — no longer matched: {v3}", {
          v1: plural(sr.sni_cap.missed, "text pattern"), v2: cap,
          v3: more > 0 ? shown + " " + T("…and {v1} more", { v1: more }) : shown });
  }
  // `no_lower`: kinds the running engine cannot express AT ALL — not truncated, not capped, simply not run.
  // Kernel-SNI takes only `contains`, Force-DNS only `zone`; anything else reaches the node, builds the
  // category's set and its mark rule, and then nothing ever fills that set. The rule reads healthy and
  // routes nothing, which is the ending this tree has shipped twice before under other names.
  //
  // APPENDED, not another `else if`. A truncation and an unrunnable kind are different facts and one node
  // can have both — and of the two, "these match nothing here" is the one the operator has to act on.
  // The kinds are in `smart_status` for anyone reading it; the sentence carries the count and the way out,
  // which is the same convention `lowered` follows.
  const noRun = Object.values(sr.no_lower || {}).reduce((n, v) => n + (v || 0), 0);
  if (noRun) {
    const s = T("{v1} this engine can't match at all — switch this node's mode, or route them from a node that can",
                { v1: plural(noRun, "pattern") });
    note = note ? note + " · " + s : s;
  }
  return html`<div class=${"rmode-health " + (ok ? "ok" : "down")}>
    <span class="rmh-dot"></span><b>${label}</b> <span>${ok ? T("healthy") : T("down — host routing degraded")}</span>
    ${extra ? html`<span class="rmh-sep">·</span><span>${extra}</span>
      ${onLearn ? html`<button class=${"learn-toggle" + (learn ? " on" : "")} title=${T("IP learning is {v1} · click to turn it {v2}", { v1: learn ? T("ON — the node remembers each learned IP") : T("OFF — routing stays fresh, no remembered IPs"), v2: learn ? T("val|off") : T("val|on") })} onClick=${() => onLearn(!learn)}><${Ic} i="database"/></button>` : null}
      <${Popover} hoverOnly cls="rmh-info" popCls="rmode-info-pop" trigger=${html`<span class="rmh-infobtn"><${Ic} i="info"/></span>`}>
        <div class="rmode-info-body">${Trich("A host's name is only visible once its connection starts, so the *first* connection to a brand-new host has already left on the default path before it can be routed. The engine learns that host's IP and *resets that one connection* so the client instantly reconnects on the correct route — that's the *new hosts rerouted* count; every later connection matches by IP and is never reset.")}<div style="margin-top:9px">${Trich("The *records* toggle (the database icon) controls *IP learning*. Each IP is remembered by *category* (not by domain), so it stays valid even if you later change that category's lists or custom domains. Nothing is kept forever: *On* (default) holds a learned IP for about *1 hour*, so repeat connections route instantly. *Off* keeps the node *fresh* — an IP is held only about *2 minutes*, so a host whose address rotates is never routed on a stale IP (at a little extra CPU, as more connections are re-scanned). Once it expires, the IP is simply re-learned on the next connection.")}</div></div>
      <//>` : null}
    ${note ? html`<span class="rmh-note">${note}</span>` : null}
  </div>`;
}
// "on N/M nodes ▾" fleet-assignment popover — toggle a list on each node. disabledFor(nid) → a reason string greys it.
// `noteFor(nid)` is optional and answers a question the switch cannot: this switch is a PIN, so "on 0/3" is a
// true statement about pins and a badly misleading one about a list three nodes are routing right now (§1.4).
// The count rides in the trigger so it is legible without opening the popover.
export function FleetAssign({ nodes, isOn, onToggle, disabledFor, noteFor }) {
  const on = (nodes || []).filter(n => isOn(n.id)).length;
  const noted = noteFor ? (nodes || []).filter(n => noteFor(n.id)).length : 0;
  return html`<${Popover} cls="fleetassign" popCls="fleetpop"
    trigger=${html`<span class="fleet-trig">on <b>${on}</b>/${(nodes || []).length}${noted
      ? html` <span class="fleet-note">· ${T("in use on {v1}", { v1: plural(noted, "prep|node") })}</span>` : null} <span class="fleet-caret">▾</span></span>`}
    children=${html`<div class="fleetlist"><div class="fleetlist-h">${T("Enabled on")}</div>${(nodes || []).map(n => { const dis = disabledFor && disabledFor(n.id);
      const note = noteFor && noteFor(n.id);
      return html`<div class=${"fleetrow" + (dis ? " off" : "")} title=${dis || ""}>
        <span class="fleet-dot" style=${"--c:" + Store.nodeColor(n.id)}></span><span class="fleet-nm">${n.name}</span><span class="grow"></span>
        ${note ? html`<span class="fleet-note">${note}</span>` : null}
        <${Switch} on=${isOn(n.id)} disabled=${!!dis} onChange=${v => onToggle(n.id, v)}/></div>`; })}</div>`}/>`;
}
// Per-category match capability, shipped by /api/state (Store.smartCaps). ip = matchable by geoip (works in
// EVERY routing mode); host = matchable by domain via the node's dnsmasq (needs DNS → forcedns). A
// host-ONLY category (youtube today) is dead weight in kernel mode, so the UI greys/hides it there.
export const catCap = id => (Store.smartCaps || {})[id] || { ip: false, host: false };
// ── the ONE rule behind every ROUTING mode-gate (mirrors blockTierOk) ──
// An IP list routes in every mode; a domain (host) list needs a host layer — any non-IP-only mode, INCLUDING
// Kernel-SNI (it matches domains in-kernel, unlike blocking which can't hold a big domain set). So routing's rule
// is looser than blocking's by exactly Kernel-SNI. Every routing usability gate derives from this — one place.
export const routeTierOk = (mode, tier) => tier === "ip" || mode !== "kernel";
export const routeCapsUsable = (mode, caps) => !!(caps && ((caps.ip && routeTierOk(mode, "ip")) || (caps.host && routeTierOk(mode, "host"))));
export const catUsableInMode = (id, mode) => routeCapsUsable(mode, catCap(id));

// ── the ONE rule behind every TYPED-TARGET mode-gate (the third of the trio, beside routeTierOk above and
// blockTierOk below) ────────────────────────────────────────────────────────────────────────────────────
// routeTierOk answers for a LIST, whose tiers the panel already resolved. This answers for what the operator
// TYPES, where the shape of the string decides which engine can run it. Nine kinds, four engines, one table —
// see docs/ROUTING-RULE-BUILDER-PLAN.md §4.1, where every cell is argued.
//   1 = native · "text" = it runs, degraded, and the badge says so · 0 = this engine cannot run it.
// The two star-in-a-label kinds sit on opposite sides of the Kernel-SNI column on purpose: xt_string asks only
// "do these bytes appear anywhere", so it answers `contains` natively and can anchor NEITHER end — which is
// also why a zone and a first/any name are refused there rather than silently becoming a substring.
export const PATTERN_ENGINE_OK = {
  ip:       { kernel: 1, forcedns: 1, sni_kernel: 1,      sni: 1 },
  asn:      { kernel: 1, forcedns: 1, sni_kernel: 1,      sni: 1 },
  site:     { kernel: 0, forcedns: 1, sni_kernel: "text", sni: 1 },
  zone:     { kernel: 0, forcedns: 1, sni_kernel: 0,      sni: 1 },
  first:    { kernel: 0, forcedns: 0, sni_kernel: 0,      sni: 1 },
  any:      { kernel: 0, forcedns: 0, sni_kernel: 0,      sni: 1 },
  contains: { kernel: 0, forcedns: 0, sni_kernel: 1,      sni: 1 },
  starts:   { kernel: 0, forcedns: 0, sni_kernel: 0,      sni: 1 },
  ends:     { kernel: 0, forcedns: 0, sni_kernel: 0,      sni: 1 },
};
// Which kinds have a datapath TODAY, anywhere in the fleet. A domain, an IP and an AS number already route in
// exactly this form, so the field ships them now; the six star-forms are classified, labelled and REFUSED
// until the engine slice that lowers them lands (plan §8, phases 2-4 — one line each, right here).
// This exists because `category:"tld"` was validated and stored for four minor versions while nothing on any
// node ever read it: two rules, both accepted, both silently routing nothing (§5.1). A kind the datapath
// cannot run must be unreachable in the UI, not merely undocumented.
// `1` = every engine PATTERN_ENGINE_OK says can run this kind has its lowering BUILT. An OBJECT names the
// engines that do, and the rest stay refused — which is how a phase ships one arm at a time without the field
// quietly promising the other. `zone` now runs on BOTH engines the matrix allows it on: dnsmasq matches the
// label and everything under it, swg-sni matches the name's last label. It stays an object rather than a `1`
// because the two remaining columns are refusals of DIFFERENT kinds — Kernel-SNI and IP-only cannot run a
// zone at all, and no future slice will change that — and because the star-forms land here the same way.
//
// EVERY KIND NOW SHIPS ON EVERY ENGINE THE MATRIX ALLOWS IT ON, and not one entry collapses to `1`. Phase 4
// gave Hybrid SNI the Tier-2 scan it was missing, so `contains` is whole; `first`, `any`, `starts` and `ends`
// run there and only there, because Hybrid SNI is the one engine holding the PARSED hostname as a string.
// The objects stay objects, and this is the case that shows why: with `contains` complete it is tempting to
// write `contains: 1`, and that would silently start promising it on Force-DNS and IP-only the day either
// grows a host layer — the object says "these two engines, because those are the ones with a lowering", and
// the four refusals it produces are four different sentences, not one. `zone` is the same shape for the same
// reason. Nothing here is redundant with PATTERN_ENGINE_OK: that table says what an engine COULD express,
// this one says what somebody wrote the code for.
export const PATTERN_SHIPPED = { ip: 1, asn: 1, site: 1, zone: { forcedns: 1, sni: 1 },
                                 first: { sni: 1 }, any: { sni: 1 },
                                 contains: { sni_kernel: 1, sni: 1 },
                                 starts: { sni: 1 }, ends: { sni: 1 } };
const _shippedOn = (kind, mode) => { const v = PATTERN_SHIPPED[kind];
  return !!v && (v === 1 || !mode || !!v[mode]); };   // no mode known → gate nothing, as everywhere else
// Preference order for "switch this node to…" — Force-DNS first (cheapest host layer, and the switch the panel
// already offers), then Hybrid SNI, which is the only engine that runs every kind.
const _FIX_MODES = ["forcedns", "sni", "sni_kernel"];
// WHY AN ENGINE REFUSES A KIND is a property of the MATCHER, not of the pattern, so it is said once per
// engine rather than once per cell. Default routing has no host layer at all; Force-DNS matches whole names,
// so it can answer a suffix and nothing positional; Kernel-SNI asks only whether some bytes appear anywhere,
// so it can anchor neither end. Hybrid SNI has no entry because it refuses nothing — its column is all 1s.
// This replaced `routeTierOk(mode, "host")`, which asks the wrong question: it separates "has a host layer"
// from "has none", which is accidentally right for the two kinds shipped today and becomes wrong the moment
// Phase 3 ships `contains` — Force-DNS would then be told it "looks for text anywhere in the name", false
// twice over. A wrong sentence about a real refusal is worse than a vague one, and it would have shipped
// silently, so the table is written for the whole matrix now rather than for the cells reachable today.
const ENGINE_NO = { kernel: "engine", forcedns: "whole", sni_kernel: "anchor" };
/** Can this node run a target of this kind, and if not, what would fix it?
 *  → {ok:true} · {ok:true, degraded:true} · {ok:false, why:"invalid"|"unbuilt"|"engine", fix?:<mode>}
 *  `mode` "" means the node record has not loaded: gate NOTHING. A badge greyed because we could not look up
 *  the engine is a lie about the configuration, and the server validates either way (§4.2). */
export function targetGate(mode, kind) {
  if (!kind || kind === "invalid") return { ok: false, why: "invalid" };
  if (!PATTERN_SHIPPED[kind]) return { ok: false, why: "unbuilt" };
  const row = PATTERN_ENGINE_OK[kind];
  // The fix we offer must be a mode that works TODAY, not one the capability matrix merely allows: sending an
  // operator to switch a node to an engine whose lowering is not written yet is worse than saying nothing.
  const fix = _FIX_MODES.find(m => row && row[m] && _shippedOn(kind, m)) || "";
  // WHICH NO IS THIS? Asked in this order because a PARTIALLY shipped kind makes the two answers collide: a
  // zone is refused on Kernel-SNI because xt_string cannot anchor one — a permanent fact — and telling that
  // operator "no node can match it yet" is false, since the Force-DNS node next to it matches zones today.
  // So the engine's own no is decided first, and "unbuilt" is left meaning only what it says.
  if (mode && row && !row[mode]) return { ok: false, why: ENGINE_NO[mode] || "engine", ...(fix ? { fix } : {}) };
  if (!_shippedOn(kind, mode)) return { ok: false, why: "unbuilt", ...(fix ? { fix } : {}) };
  if (!mode || !row) return { ok: true };
  const v = row[mode];
  if (v === "text") return { ok: true, degraded: true };
  return { ok: true };
}
export const patternOk = (mode, kind) => targetGate(mode, kind).ok;

// How a classified target is SAID BACK. The operator typed a string; the badge shows the reading, and the
// sentence under the field says what it will match in words that assume nothing about suffixes or keywords.
// Two separate things on purpose: the badge is the canonical FORM (so `*.google.com` and `google.com` show as
// one thing), and the sentence is the CONSEQUENCE.
//
// A LABEL-ANCHORED VALUE IS READ BACK OUT OF PUNYCODE. The classifier converts, and has to: `xn--p1ai` is
// what a DNS query and a ClientHello carry, so it is what gets stored and matched. Showing it is another
// matter — an operator who typed `*.рф` got a badge reading `.xn--p1ai` and could not recognise their own
// rule. js/idn.js turns it back for DISPLAY only, refusing where the answer would mislead; the stored value
// is untouched, and every caller that COMPARES badges uses `value`, never this. Tier-2 kinds are absent on
// purpose: an IDN substring is refused by the grammar (`idn_tier2`), so their operand is always ASCII.
const idnOf = v => idnHost(String(v == null ? "" : v));
export function targetLabel(kind, value) {
  switch (kind) {
    case "zone": return "." + idnOf(value);
    case "first": return idnOf(value) + ".*";
    case "any": return "*." + idnOf(value) + ".*";
    case "contains": return "*" + value + "*";
    case "starts": return value + "*";
    case "ends": return "*" + value;
    case "ip": return String(value).replace(/\/32$/, "");
    case "asn": return String(value).toUpperCase();
    default: return idnOf(value);
  }
}
/** The punycode a readable label is standing in for, or "" when it is not standing in for anything. The
 *  badge keeps this in its tooltip: the name is what the operator recognises, the encoded form is what is
 *  actually stored and matched, and hiding the second one would make the rule impossible to verify. */
export const targetPuny = (kind, value) => idnDiffers(String(value == null ? "" : value))
  ? String(value) : "";
// The kind's name, in the .capb slot beside the value. Written for someone who has never heard of a suffix
// match; the engine's own word lives in the tooltip. `first` and `any` deliberately share one label — both are
// "this name, wherever it sits", and the difference is visible in the badge's own form.
// Built on FIRST READ, never at import: modules load before loadLang() resolves (see --frozen).
let _kind_label = null;
export const KIND_LABEL = () => (_kind_label || (_kind_label = {
  site: T("kind|site"), zone: T("kind|zone"), first: T("kind|name"), any: T("kind|name"),
  contains: T("kind|contains"), starts: T("kind|starts with"), ends: T("kind|ends with"),
  ip: T("kind|IP range"), asn: T("kind|network"),
}));
// Amber (--partial): a kind whose blast radius is orders larger than it looks. A zone is every name under a
// whole ending; the three Tier-2 shapes match text, so they catch names nobody meant (notgoogle.com).
export const KIND_WIDE = { zone: 1, contains: 1, starts: 1, ends: 1 };
// The OTHER half of §12.1's Tier-2 floor, and the half a refusal cannot do. Three characters is the hard
// floor (`short_tier2`, in the grammar, where both readers see it); between three and five the operator is
// allowed to mean it and is told what they are asking for, because `*abc*` is not a mistake the way `*ab*`
// is — it is a decision, and the only thing missing is the size of it.
const TIER2_WARN = 5;
const isTier2 = kind => patternTier(kind) === 2;   // ONE tier table, in the classifier, where the grammar is
/* §10.5 item 9 — THE NODE'S OWN LIMIT, FROM THE NODE. xt_string refuses an operand longer than
   `_XTS_MAXLEN` outright, and that number lived only in swg-noded: an over-long pattern was accepted here,
   stored, shipped, and dropped at the node with a report, so the operator learned about it one sync later.
   The panel still does not KNOW the limit — item 5 is why, a second copy of an engine's limits drifts and
   the node's is the one that decides — it is TOLD, in `smart_status`, by the engine that enforces it, and
   only while that engine is running. A node too old to send it, or on another mode, says nothing and this
   stays quiet: no number, no sentence, rather than a guess ([[lesson-detection-failure-fail-safe]]).
   Tier 2 only, and `.length` is right for it: the classifier refuses a non-ASCII Tier-2 operand
   (`idn_tier2`), so characters and the bytes xt_string counts are the same thing here. */
const opMaxlen = node => (((Store.stats || {})[node] || {}).smartroute || {}).op_maxlen || 0;
export const opTooLongNote = (node, kind, value) => {
  if (patternTier(kind) !== 2) return "";
  const max = opMaxlen(node), n = String(value || "").length;
  return max && n > max
    ? " " + T("This node matches at most {v1} of a pattern — this one is {v2} and would be dropped.",
              { v1: plural(max, "character"), v2: plural(n, "character") })
    : "";
};
const tier2Note = v => String(v).length < TIER2_WARN
  ? " " + T("Only {v1} long — a short fragment turns up inside names that have nothing to do with it.",
            { v1: plural(String(v).length, "character") })
  : "";
/** One sentence saying what this target will match. Shown under the field before the badge is committed, and
 *  in the badge's tooltip after. `n` (the IP count) is only used by the ip kind. */
export function targetSentence(kind, value) {
  const v = targetLabel(kind, value);
  switch (kind) {
    case "site": return T("{v1} and every name under it — www.{v1}, mail.{v1}…", { v1: idnOf(value) });
    case "zone": return T("Every address ending in {v1} — millions of sites", { v1: v });
    case "first": return T("Any address whose first part is {v1} — {v1}.com, {v1}.ru, {v1}.de", { v1: idnOf(value) });
    case "any": return T("Any address with {v1} as one of its parts", { v1: idnOf(value) });
    case "contains": return T("Any address with {v1} anywhere in it — also matches not{v1}.com", { v1: value }) + tier2Note(value);
    case "starts": return T("Any address whose text starts with {v1} — also matches {v1}mail.com", { v1: value }) + tier2Note(value);
    case "ends": return T("Any address whose text ends with {v1} — also matches not{v1}", { v1: value }) + tier2Note(value);
    case "ip": { const bits = +String(value).split("/")[1];
      return bits === 32 ? T("One address") : T("{v1} addresses", { v1: fmtCount(Math.pow(2, 32 - bits)) }); }
    case "asn": return T("All IP ranges announced by {v1}", { v1: v });
    default: return "";
  }
}
/** Why a token was refused, in the operator's words. `why` is classify()'s stable code — never its prose, so
 *  each surface writes its own sentence and the grammar stays free of UI copy. */
export function targetWhy(why, raw) {
  const t = String(raw || "").trim().toLowerCase();
  switch (why) {
    // The one refusal worth teaching rather than just reporting: a bare label is almost always someone
    // reaching for a whole zone, and guessing that for them would be a rule of enormous blast radius.
    // `.ru` is the same reach written the way most people write a zone, so it gets the same sentence — the
    // leading dots come off for the substitution, or it reads "the whole ..ru zone".
    case "bare_label": case "lead_dot": return T("Did you mean the whole .{v1} zone? Write *.{v1}.", { v1: t.replace(/^\.+/, "") });
    case "bad_ip": return T("That isn't a valid IP address or range.");
    // Answer about the thing they typed. This used to fall through to the catch-all below, so someone who
    // typed a NAME was told it was not an address, an IP range or an AS number — three nouns, none of them
    // the one in the field.
    case "bad_domain": return T("That isn't a valid web address.");
    case "star_mid": return T("A * goes at the start or the end of a name, not in the middle.");
    case "multi_label_operand": return T("Put one name between the stars, not a dotted address.");
    case "idn_tier2": return T("A partial-word match can't be written in non-Latin letters — names travel already encoded.");
    // The floor, said as what it protects rather than as a rule. `*ru*` reads to an operator as "Russian
    // sites" and to the matcher as ruble.com, brutal.io and truecaller.com.
    case "short_tier2": return T("Too short to match on — under {v1} characters this catches names that have nothing to do with what you meant.", { v1: TIER2_MIN });
    default: return T("That isn't an address, IP range or AS number.");
  }
}
// hover bubble listing a list's domains/IPs (only when there are some); `note` = a faint footer caption
let _ruleSeq = 0;
export const newRid = () => "rr" + (++_ruleSeq);


// The full catalog index, fetched once and searched CLIENT-side — so search matches the readable title
// (country names, friendly names) and descriptions, not just the raw provider id. ~3.5k tiny rows.
//
// Each row is DECORATED once, here, with the two things the search needs: `disp` (the readable title, a regex
// plus an Intl.DisplayNames lookup) and `hay` (id · raw id · title · description, lowercased and joined). The
// filter used to compute both for all ~3.5k rows on every keystroke, which was tolerable in a Settings screen
// nobody opens and is not in the panel's primary routing control. Now a keystroke is a substring scan over a
// flat array, and prettyCatLabel runs once per row for the life of the page instead of once per row per key.
let _CATALOG_INDEX = null;
let _CATALOG_BY_ID = {};
let _CATALOG_SIG = "";       // which providers the cached index was built from
// ⚠️ AN EMPTY INDEX IS NOT A CACHED ANSWER, and treating it as one is why a provider you just switched on
// showed nothing. `/api/catalog/index` returns ONLY the enabled providers, so with them all off it answers
// `items: []` — and `[]` is truthy, so this returned that empty array for the life of the page. Enabling
// MetaCubeX and v2fly then downloaded 3,335 lists the panel had and the field could not see, until a full
// reload. The caller's guard was locked the same way (`!cidx` is false for `[]`), so neither could recover.
//
// Cached only when it holds something AND the enabled set has not changed since — a toggle in Settings
// invalidates it on the next poll, which is what makes "switch it on and search" work in one page.
let _CATALOG_TRY = { sig: null, at: 0, p: null };   // last attempt: which providers, when, and its promise
const _CATALOG_RETRY_MS = 20000;
export function loadCatalogIndex() {
  const sig = JSON.stringify((Store.panelSettings || {}).providers || {});
  if (_CATALOG_INDEX && _CATALOG_INDEX.length && _CATALOG_SIG === sig) return Promise.resolve(_CATALOG_INDEX);
  // ⚠️ BOUNDED, or "an empty index is not an answer" becomes a request per render. Measured right after that
  // fix went in: opening the field on a panel with no catalog fired /api/catalog/index twice on the first
  // open and three times on the second, because the caller's guard stays true while the answer stays empty
  // and the effect re-runs on every render. Re-asking is right; re-asking in a loop is not.
  // One attempt in flight is shared, and an empty answer is not retried for 20s unless the enabled providers
  // change — which is the only thing that can make the answer different sooner.
  const now = Date.now();
  if (_CATALOG_TRY.sig === sig && _CATALOG_TRY.p && now - _CATALOG_TRY.at < _CATALOG_RETRY_MS) return _CATALOG_TRY.p;
  const p = api.catalogIndex().then(r => {
    if (r && r.ok) { const pl = r.data.provider_labels || {}; _CATALOG_SIG = sig;
      _CATALOG_INDEX = (r.data.items || []).map(it => { const disp = prettyCatLabel(it.id, "");
        return { ...it, provider_label: pl[it.provider] || it.provider, disp,
                 hay: (it.id + " " + catRawId(it.id) + " " + disp + " " + catDescOf(it.id)).toLowerCase() }; });
      _CATALOG_BY_ID = Object.fromEntries(_CATALOG_INDEX.map(it => [it.id, it])); }
    return _CATALOG_INDEX || [];
  }).catch(() => []);
  _CATALOG_TRY = { sig, at: now, p };
  return p;
}

// Block-list catalog (Blocking tab): categories + providers + pickable lists. Loaded on demand and cached, then
// mirrored onto Store.blockCatalog so screens can read it synchronously; pass force=true to refetch after a save.
let _BLOCK_CATALOG = null;
export function loadBlockCatalog(force) {
  if (_BLOCK_CATALOG && !force) return Promise.resolve(_BLOCK_CATALOG);
  return api.blockCatalog().then(r => {
    if (r && r.ok) { _BLOCK_CATALOG = r.data; Store.blockCatalog = r.data; bus.emit(); }
    return _BLOCK_CATALOG || null;
  }).catch(() => null);
}

// Concise, user-facing tooltips for the built-in traffic/abuse mechanisms shown in the interface's Block-traffic section.
// ── the ONE rule behind every block-UI mode-gate ──
// A domain (host) list enforces only where the node fills domain sets from DNS (Force-DNS / Hybrid-SNI); an IP list
// matches in every mode. IP-only can't match domains at all; Kernel-SNI can't hold a domain blocklist. Every gate
// below (source availability, category disable, picker badge) derives from this — one place, no drift.
export const blockTierOk = (mode, tier) => tier === "ip" || (mode !== "kernel" && mode !== "sni_kernel");
export const blockHostBlind = mode => !blockTierOk(mode, "host");                                  // this node can't enforce ANY domain list
export const blockProvTier = (providers, p) => ((providers || []).find(x => x.id === p) || {}).tier || "host";
export const blockSrcOk = (mode, providers, s) => blockTierOk(mode, blockProvTier(providers, s.provider));   // a single list/source enforces here?
export const blockCatHasIp = (providers, c) => (c.sources || []).some(s => blockProvTier(providers, s.provider) === "ip");
export const blockCatDisabled = (mode, providers, c) => blockHostBlind(mode) && !blockCatHasIp(providers, c);   // no enforceable list → dead on this node
// Built on FIRST READ, never at import: modules load before loadLang() resolves, so a T() here would
// freeze in English whatever the catalog says (see --frozen).
let _mech_hint = null;
export const MECH_HINT = () => (_mech_hint || (_mech_hint = {
  torrents:     T("Drop BitTorrent / P2P — protects this exit IP's reputation. Free port-hint by default; signature scan where the node supports it."),
  smtp:         T("Drop outbound mail on TCP :25 — stops spam being relayed through this exit."),
  portscan:     T("Rate-limit outbound port-scans, brute-force and SYN-floods leaving this interface."),
  cryptomining: T("Drop known cryptomining / Stratum-pool traffic."),
  quic:         T("Drop QUIC / HTTP-3 (UDP :443) so connections fall back to TCP and stay inspectable."),
  doh:          T("Drop DoH / DoT / DoQ so DNS can't slip past the tunnel's filtering."),
  webrtc:       T("Block WebRTC / STUN — prevents the client's real IP leaking around the tunnel."),
}));

// The default block set for a NEW interface on `node`: every default-on category available here — mechanisms are
// built-in (always available), content/IP categories must be enabled on this node (Settings ▸ Routing & Blocking).
export function defaultBlockFor(node) {
  const bc = Store.blockCatalog; if (!bc) return [];
  return Object.values(bc.categories || {}).filter(c => c && c.default_on && c.enabled !== false &&
    (c.kind === "mechanism" || (c.enabled_nodes || []).includes(node))).map(c => c.id);
}

// Per-interface "Block traffic" (screen ③) — the daily policy surface. Content/IP categories the operator enabled on
// THIS node plus the built-in traffic/abuse mechanisms; a chip toggles the category id in the interface's block[], and
// the node drops matching traffic on its next sync. Domain (content) categories are inert on an IP-only (kernel) node
// — shown greyed with a reason, the choice kept for when the mode changes.
export function BlockTraffic({ node, value, onChange }) {
  useStore(); useEffect(() => { loadBlockCatalog(); }, []);
  const bc = Store.blockCatalog;
  const mode = ((Store.nodes || []).find(n => n.id === node) || {}).routing_mode || "kernel";
  const active = id => (value || []).includes(id);
  const toggle = id => { const s = new Set(value || []); s.has(id) ? s.delete(id) : s.add(id); onChange([...s]); };
  if (!bc) return html`<div class="blk-field"><div class="hint">${T("Loading block catalog…")}</div></div>`;
  const cats = bc.categories || {};
  const list = [...new Set([...(bc.cat_order || []), ...Object.keys(cats)])].map(id => cats[id]).filter(c => c && c.enabled !== false);
  const availOn = c => (c.enabled_nodes || []).includes(node);
  const content = list.filter(c => (c.kind === "content" || c.kind === "ip") && availOn(c));
  const mech = list.filter(c => c.kind === "mechanism");
  const chip = c => { const dis = blockCatDisabled(mode, bc.providers, c); return html`<button type="button" key=${c.id} disabled=${dis}
      class=${"blkchip" + (active(c.id) && !dis ? " on" : "") + (dis ? " inert" : "")}
      title=${dis ? T("No IP list in this category — domain lists can't match in {mode}. Use Force-DNS / Hybrid-SNI, or add an IP list.", { mode: (MODE_META[mode] || {}).label || mode })
                 : (c.kind === "ip" ? T("Matched by IP address — works in every mode.") : T("Matched by domain name."))}
      onClick=${() => { if (!dis) toggle(c.id); }}><span class="blkchip-g">⊘</span>${c.label}${!c.predefined ? html`<span class="blkchip-tag">${T("tag|custom")}</span>` : null}</button>`; };
  const mchip = c => html`<button type="button" key=${c.id} class=${"blkchip mech" + (active(c.id) ? " on" : "")}
      title=${MECH_HINT()[c.id] || ""} onClick=${() => toggle(c.id)}><span class="blkchip-g">⊘</span>${c.label}</button>`;
  return html`<div class="blk-field">
    <div class="blk-grp"><div class="blk-gtitle">${T("Content filtering")}</div>
      ${content.length ? html`<div class="blk-chips">${content.map(chip)}</div>`
        : html`<div class="hint blk-empty">${noFilterCats(() => { closeAllModals(); goSettings("routing"); })}</div>`}</div>
    <div class="blk-grp"><div class="blk-gtitle">${T("Traffic & abuse")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— built-in")}</span></div>
      <div class="blk-chips">${mech.map(mchip)}</div></div>
  </div>`;
}



// Add-a-list picker for a block category (expanded row): a popover of every enabled provider's lists, grouped by
// provider, minus the ones already in this category. Tapping one adds it; the popover stays open for multiple adds.
export function BlockListPicker({ providers, provLists, current, nodeMode, onAdd, autoOpen }) {
  const [q, setQ] = useState("");
  const has = (p, l) => (current || []).some(s => s.provider === p && s.list === l);
  const ql = q.trim().toLowerCase();
  // A domain (host) provider list can't enforce where domains aren't DNS-filled (IP-only, Kernel-SNI). IP lists work
  // everywhere. Same shared rule (blockTierOk) as every other block gate. Badge it, still addable.
  const naLabel = (MODE_META[nodeMode] || {}).label || nodeMode;
  const naFor = p => blockSrcOk(nodeMode, providers, { provider: p }) ? null : naLabel;
  return html`<${Popover} alignRight flipFit clickOnly cls="bk-addwrap" popCls="bk-pickpop" autoOpen=${autoOpen}
      trigger=${html`<button class="btn btn-mini"><${Ic} i="plus"/> ${T("Add list")}</button>`}>
    <div class="bk-pick" onClick=${e => e.stopPropagation()}>
      <input class="bk-picksearch" ref=${el => { if (el && !el._foc) { el._foc = 1; requestAnimationFrame(() => el.focus()); } }} placeholder=${T("Search lists…")} value=${q} onInput=${e => setQ(e.target.value)}/>
      <div class="bk-picklist">
        ${(providers || []).filter(p => p.enabled !== false).map(p => {
          const items = (provLists[p.id] || []).filter(it => !has(p.id, it.id) && (!ql || (it.label + " " + (it.desc || "") + " " + p.label).toLowerCase().includes(ql)));
          if (!items.length) return null;
          const na = naFor(p.id);
          return html`<div class="bk-pickgrp" key=${p.id}><div class="bk-pickprov" style=${p.color ? "--pc:" + p.color : ""}>${p.label}</div>
            ${items.map(it => html`<button class=${"bk-pickitem" + (na ? " na" : "")} key=${it.id} onClick=${() => onAdd(p.id, it.id)}><span class="bk-pilabel">${it.label}${na ? html`<span class="bk-nabadge">${T("Not available with {v1}", { v1: na })}</span>` : null}</span>${it.desc ? html`<span class="bk-pidesc">${it.desc}</span>` : null}</button>`)}</div>`;
        })}
        ${(providers || []).every(p => p.enabled === false || !(provLists[p.id] || []).some(it => !has(p.id, it.id) && (!ql || (it.label + " " + p.label).toLowerCase().includes(ql))))
          ? html`<div class="bk-pickempty">${ql ? T("No lists match.") : T("Every available list is already added.")}</div>` : null}
      </div>
    </div>
  <//>`;
}

// Create a custom block category — just a name. It matches by whatever the lists you add are (domains and/or IPs).
export function NewBlockCatSheet({ existingIds, onCreate }) {
  const [name, setName] = useState("");
  const nm = name.trim();
  const id = "cl_" + nm.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const dup = (existingIds || []).includes(id);
  const bad = !nm || id === "cl_" || dup;
  const create = () => { if (bad) return; onCreate({ id, label: nm }); closeModal(); };
  return html`<${Sheet} title=${T("New block category")} onClose=${closeModal}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>${T("Cancel")}</button><button class="btn btn-primary" disabled=${bad} onClick=${create}>${T("Create")}</button></>`}>
    <div class="field"><label>${T("Name")}</label>
      <input type="text" autofocus spellcheck="false" value=${name} placeholder=${T("e.g. Corporate block")}
        onInput=${e => setName(e.target.value)} onKeyDown=${e => { if (e.key === "Enter") create(); }}/>
      <div class="hint">${T("Add lists next — the category matches by domain or IP depending on the lists you pick.")}</div></div>
    ${dup ? html`<div class="hint"><b class="warntext">${T("A category with that name already exists.")}</b></div>` : null}
  <//>`;
}

// Searchable provider-catalog category picker — replaces the native <select> for routing rules. The
// catalog holds ~3.5k categories (far too many for a dropdown), so this is a combobox: a button showing
// the current label, opening a portal'd popover with a search box (filters the full index locally, by title/
// id/description) plus the operator's own custom lists pinned on top. caps ({ip,host}) drive kernel greying —
// a host-only category can't match by dest IP, so it's disabled (not hidden) in kernel mode with a note.
// addMode: the picker becomes a multi-select "Add from catalog" affordance — it stays open on each pick,
// shows a ✓ on already-added ids (from `selected`), and hides the Custom row, custom lists, and the 26
// built-ins (those are managed by the checkboxes above it). Used by the Settings node-lens.
/* Where a WIDE catalog popover goes. Rows carry a title, a description, sizes and caps, so it spans the
   container rather than the trigger — and the container is the nearest of the sheet body, a Settings card or
   a Settings pane. Anchoring to .card/.setpane alone walks straight past a modal to a card BEHIND it and
   lands the popover somewhere unrelated; nearest-ancestor-wins keeps Settings on exactly what it had.
   Shared by the catalog browser (CatPicker addMode) and the rule field, so they open the same way. */
export function placeWide(el) {
  const r = el.getBoundingClientRect();
  const below = window.innerHeight - r.bottom - 12, above = r.top - 12;
  const box = el.closest(".sheet-body, .card, .setpane");
  const br = box ? box.getBoundingClientRect() : r, pad = 18;
  const flip = below < 360 && above > below;
  return { left: Math.round(br.left + pad), top: Math.round(flip ? r.top - 4 : r.bottom + 6),
    width: Math.round(br.width - pad * 2), flip, wide: true, maxh: Math.max(300, Math.round(flip ? above : below)) };
}

export function CatPicker({ value, mode, customLists, catalogCats, listTitle, onChange, onAdd, addMode, selected, triggerLabel, primary }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [cidx, setCidx] = useState(addMode ? _CATALOG_INDEX : null);   // the full catalog index (addMode only), loaded once
  const [pos, setPos] = useState(null);
  const ref = useRef(null), popRef = useRef(null), inRef = useRef(null), listRef = useRef(null);
  const selSet = new Set(selected || []);
  const curLabel = addMode ? (triggerLabel || T("Add from catalog"))
    : value === "custom" ? T("Custom IPs / domains…")
    : (SMART_CAT_LABEL[value] || (listTitle || {})[value] || (Store.catLabels || {})[value] || value || T("Choose a category…"));
  const usable = caps => routeCapsUsable(mode, caps);   // shared routing rule: IP everywhere, domain needs a host layer (non-IP-only)
  const place = () => { const el = ref.current; if (!el) return; const r = el.getBoundingClientRect();
    const below = window.innerHeight - r.bottom - 12, above = r.top - 12;
    if (addMode) { setPos(placeWide(el)); return; }   // the catalog browser spans its container, not its trigger
    const flip = below < 300 && above > below;                 // not enough room under the trigger → open upward
    setPos({ left: Math.round(r.left), top: Math.round(flip ? r.top - 4 : r.bottom + 4), width: Math.round(r.width),
      flip, maxh: Math.max(200, Math.round(flip ? above : below)) }); };   // list caps to the space actually available
  useEffect(() => {   // addMode: load the full index ONCE, then search/paginate locally (matches title + id + description)
    if (open && addMode && !(cidx && cidx.length)) { let live = true; loadCatalogIndex().then(x => live && setCidx(x)); return () => { live = false; }; }
  }, [open, addMode]);
  useEffect(() => {   // position + outside-click/Esc/scroll handling while open
    if (!open) return; place();
    const onMove = () => place();
    const onDoc = e => { const t = e.target; if (!((ref.current && ref.current.contains(t)) || (popRef.current && popRef.current.contains(t)))) setOpen(false); };
    const onKey = e => {
      if (e.key === "Escape") { setOpen(false); ref.current && ref.current.focus(); return; }
      // start typing anywhere while the dropdown is open (focus outside the box) → clear the box + focus it + start a
      // FRESH search with the typed char, so you can search → select → search again without re-clicking the field.
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey && inRef.current && document.activeElement !== inRef.current) {
        e.preventDefault();
        inRef.current.focus();
        setQ(e.key); setPage(0);
      }
    };
    window.addEventListener("scroll", onMove, true); window.addEventListener("resize", onMove);
    document.addEventListener("mousedown", onDoc, true); document.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("scroll", onMove, true); window.removeEventListener("resize", onMove); document.removeEventListener("mousedown", onDoc, true); document.removeEventListener("keydown", onKey); };
  }, [open]);
  // Focus-on-open is done via the input's ref-callback (fires exactly when the input MOUNTS — robust against the
  // Portal render timing that made `[open]`/`[pos]` effects miss the very first open). `focusGuard` fires it once
  // per open. Reset when the popover closes.
  const focusGuard = useRef(false);
  const sessionPicked = useRef(false);   // addMode: did the operator add/toggle anything this open session? (drives Enter-to-close)
  useEffect(() => { if (!open) { focusGuard.current = false; sessionPicked.current = false; } }, [open]);
  const pick = id => { if (addMode) sessionPicked.current = true; onChange(id); if (addMode) return; setOpen(false); setQ(""); setPage(0); };   // addMode stays open for multi-add
  const capBadge = capBadges;   // shared Host-first renderer (defined near catLabelOf)
  // addMode: filter the full index by title/id/description, sort by readable title, paginate 40/page locally.
  const per = 50;
  const goPage = (np, toTop) => { setPage(np); requestAnimationFrame(() => { const el = listRef.current; if (el) el.scrollTop = toTop ? 0 : el.scrollHeight; }); };
  const _aq = q.trim().toLowerCase();
  // Curated "Recommended presets" — pinned above the provider catalog, always shown in full (only ~26).
  const _curatedAll = addMode ? SMART_CATEGORIES().filter(([id]) => id !== "all")
    .map(([id, label]) => ({ id, provider: "curated", provider_label: T("Curated"), caps: catCap(id), recommended: true, disp: label })) : [];
  const curatedFiltered = _curatedAll.filter(it => !_aq || it.id.toLowerCase().includes(_aq)
    || it.disp.toLowerCase().includes(_aq) || catDescOf(it.id).toLowerCase().includes(_aq))
    .sort((a, b) => a.disp.toLowerCase().localeCompare(b.disp.toLowerCase()));
  // `hay` and `disp` are precomputed in loadCatalogIndex — one substring scan per row, no relabelling per key.
  const filtered = addMode && cidx ? cidx.filter(it => !_aq || it.hay.includes(_aq))
    .sort((a, b) => a.disp.toLowerCase().localeCompare(b.disp.toLowerCase())) : [];
  const total = filtered.length;
  const pages = Math.max(1, Math.ceil(total / per));
  const items = filtered.slice(page * per, (page + 1) * per);
  const _matchTotal = curatedFiltered.length + total, _firstMatch = curatedFiltered[0] || items[0];
  const lists = customLists || [];
  // Routing picker (non-addMode): TWO sections — Provider lists (the node's opted-in provider-catalog cats, each
  // source-tagged) and Custom lists (your own). Never the full catalog — filtered client-side; add more via Settings.
  // A currently-selected LEGACY built-in (existing rule) is shown under Provider lists so it stays editable.
  const _ql = q.trim().toLowerCase();
  const _match = (id, label) => !_ql || String(label).toLowerCase().includes(_ql) || String(id).toLowerCase().includes(_ql);
  const _provRows = (catalogCats || []).map(c => ({ id: c.id, label: c.title, caps: catCap(c.id), src: provLabelOf(c.id) }));
  if (!addMode && value && !isProviderCat(value) && value !== "custom" && !lists.some(l => l.id === value) && !_provRows.some(r => r.id === value))
    _provRows.push({ id: value, label: catLabelOf(value), caps: catCap(value), src: provLabelOf(value) || T("Curated") });   // keep a curated/legacy rule visible + editable, tagged by its provider
  const localGroups = addMode ? [] : [
    { grp: T("Provider lists"), rows: _provRows.filter(r => _match(r.id, r.label)).sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase())) },
    { grp: T("Custom lists"), rows: lists.filter(l => _match(l.id, l.title)).map(l => ({ id: l.id, label: l.title, caps: customCaps(l), src: T("Custom"), list: l })).sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase())) },
  ].filter(g => g.rows.length);
  const localEmpty = !addMode && !localGroups.length && !!_ql;
  return html`<div class=${"catpick" + (addMode ? " catpick-add" : "")} ref=${ref}>
    ${addMode ? html`<button type="button" class=${(primary ? "btn btn-add" : "btn btn-mini") + (open ? " on" : "")} onClick=${() => setOpen(o => !o)}><${Ic} i="plus"/> ${curLabel}</button>`
      : html`<button type="button" class=${"catpick-btn" + (open ? " on" : "")} onClick=${() => setOpen(o => !o)}>
      <span class="catpick-lbl">${curLabel}</span><span class="catpick-caret">▾</span>
    </button>`}
    ${open && pos ? html`<${Portal}><div ref=${popRef} class=${"catpick-pop" + (pos.flip ? " flip" : "") + (pos.wide ? " wide" : "")} style=${"left:" + pos.left + "px;top:" + pos.top + "px;" + (pos.wide ? "width:" + pos.width + "px;" : "min-width:" + Math.max(pos.width, 320) + "px;") + "--catpick-maxh:" + (pos.maxh - 108) + "px"}>
      <div class="catpick-search">
        <${Ic} i="search"/>
        <input ref=${el => { inRef.current = el; if (el && open && !focusGuard.current) { focusGuard.current = true; requestAnimationFrame(() => el.focus()); } }} type="text" placeholder=${addMode ? T("Search {v1} lists — name, country, service…", { v1: (cidx && cidx.length) || "" }) : T("Filter this node's lists…")} value=${q}
          onInput=${e => { setQ(e.target.value); setPage(0); }} spellcheck="false" autocomplete="off"
          onKeyDown=${e => { if (e.key === "Enter" && addMode && _matchTotal === 1 && _firstMatch) {   // ONLY when exactly one result:
            e.preventDefault(); e.stopPropagation();
            (onAdd || pick)(_firstMatch.id);   // add-only (never toggles off)
            setOpen(false);
          } /* any other case (0 or many results): Enter does nothing */ }}/>
      </div>
      <div class="catpick-list" ref=${listRef}>
        ${!addMode ? html`
          ${!_ql ? html`<button type="button" class=${"catpick-row" + (value === "custom" ? " sel" : "")} onClick=${() => pick("custom")}>
            <span class="catpick-rlbl"><${Ic} i="pencil"/> ${T("Custom IPs / domains…")}</span></button>` : null}
          ${localGroups.map(g => html`<div class="catpick-grp">${g.grp}</div>
            ${g.rows.map(it => { const ok = it.caps ? usable(it.caps) : true; return html`<button type="button" disabled=${!ok}
              class=${"catpick-row" + (value === it.id ? " sel" : "") + (ok ? "" : " off")} onClick=${() => ok && pick(it.id)}
              title=${ok ? "" : T("Host-only list — switch this node to Force-DNS to use it")}>
              <span class="catpick-rlbl">${it.label}${it.src ? html`<${ProvTag} id=${it.id} label=${it.src} plain=${it.legacy || !!it.list}/>` : null}</span>
              ${/* A curated preset is a first-class provider ("Curated") but keeps a BARE id, so isProviderCat()
                    alone hid its size: the panel ships cat_sizes for curated cats too (they resolve on the panel,
                    same as provider lists), the row just never asked for it. */
                it.caps ? capBadge(it.caps) : null}${it.list ? html`<${ListInfo} list=${it.list}/>` : ((isProviderCat(it.id) || isCuratedCat(it.id)) ? html`<${ListInfo} cat=${it.id}/>` : null)}
              ${isProviderCat(it.id) && catListUrl(it.id, it.caps) ? html`<a class="catrow-info" href=${catListUrl(it.id, it.caps)} target="_blank" rel="noopener" title=${T("View this list on GitHub")} onClick=${e => e.stopPropagation()}><${Ic} i="info"/></a>`
                : (!isProviderCat(it.id) && catDescOf(it.id)) ? html`<${DescInfo} text=${catDescOf(it.id)}/>` : null}</button>`; })}`)}
          ${localEmpty ? html`<div class="catpick-empty">${T("No list on this node matches “{q}”. Add more in Settings → Routing lists.", { q })}</div>` : null}
        ` : html`
          ${page === 0 && curatedFiltered.length ? html`<div class="catpick-grp">${T("Recommended presets")}</div>
            ${curatedFiltered.map(it => html`<${CatalogRow} key=${it.id} it=${it} added=${selSet.has(it.id)} onPick=${pick}/>`)}` : null}
          ${total ? html`<div class="catpick-grp">${T("Provider catalog")}</div>
            ${items.map(it => html`<${CatalogRow} key=${it.id} it=${it} added=${selSet.has(it.id)} onPick=${pick}/>`)}` : null}
          ${cidx == null && !curatedFiltered.length ? html`<div class="catpick-empty">${T("Loading catalog…")}</div>`
            : _matchTotal === 0 ? html`<div class="catpick-empty">${T("No list matches “{q}”.", { q })}${cidx && cidx.length === 0 ? html`<br/><span class="faint">${T("Enable a provider in Settings → Geo data providers to search its catalog.")}</span>` : ""}</div>` : null}
        `}
      </div>
      ${mode === "kernel" ? html`<div class="catpick-note">${Trich("Greyed lists match by *domain* only — this node is *IP-only* (no host layer). Switch it to Force-DNS or SNI to use them.")}</div>` : null}
      ${addMode && total > per ? html`<div class="catpick-foot">
        <span class="catpick-count">${page * per + 1}–${Math.min(total, (page + 1) * per)} of ${total}</span>
        <span class="grow"></span>
        <div class="catpick-nav">
          <button type="button" class="btn btn-mini" disabled=${page === 0} onClick=${() => goPage(Math.max(0, page - 1), false)}>${T("‹ Prev")}</button>
          <button type="button" class="btn btn-mini" disabled=${page >= pages - 1} onClick=${() => goPage(Math.min(pages - 1, page + 1), true)}>${T("Next ›")}</button>
        </div>
      </div>` : null}
    </div><//>` : null}
  </div>`;
}

/* ── the rule builder's field: one place to say everything a row sends somewhere ────────────────────────
 *
 * Replaces three controls that used to sit in a row — the category dropdown, its "Custom IPs / domains…"
 * entry, and the textarea that appeared underneath when you chose it. They were a mode switch you had to
 * make before you could type, and the dropdown could only ever hold one thing, so "these fifteen services
 * to Germany" was fifteen rows. See docs/ROUTING-RULE-BUILDER-PLAN.md §3.
 *
 * The field SEARCHES AND ACCEPTS AT THE SAME TIME. Typing `google` offers both the curated Google list and
 * "match the name google.com"; neither reading is behind a mode. What is typed is classified by the shared
 * grammar (js/classify.js) and said back as a badge with its kind and a sentence — we infer the kind rather
 * than making the operator name it, which is what every routing engine's own UI does and what assumes the
 * operator knows what a suffix match is.
 *
 * A badge is never silently dropped. One that this node's engine cannot run is kept and marked INERT with
 * the reason and, where one exists, the button that fixes it — the same rule the panel already holds for
 * per-node list assignment and for stored ids it merely cannot validate. A token that means nothing
 * anywhere is a different thing entirely and is refused out loud, before it can become a badge (§5.3).
 */

// Caps for a category from wherever they are known: /api/state's smart_caps (a routed cat), the catalog index
// (anything searchable), or this session's list-info cache (a row just browsed). {} = not known — and an
// unknown capability gates NOTHING, for the same reason an unloaded node record does.
export function catCapsAny(id) {
  const s = (Store.smartCaps || {})[id]; if (s && (s.ip || s.host)) return s;
  const ix = _CATALOG_BY_ID[id]; if (ix && ix.caps && (ix.caps.ip || ix.caps.host)) return ix.caps;
  const li = _LIST_INFO_CACHE[id];
  if (li && li.tiers) return { ip: !!(li.tiers.ip && li.tiers.ip.n), host: !!(li.tiers.host && li.tiers.host.n) };
  return {};
}
// The operator's own list, by either of the two ids the fleet may name it with.
const customListOf = id => (Store.panelSettings?.custom_lists || []).find(l => l && (l.id === id || l.name === id)) || null;
/** The same verdict shape as targetGate, for a LIST badge. Three reasons, one treatment: this engine cannot
 *  match the list's tier, the list is switched off on this node, or its provider is switched off. */
export function listGate(mode, id, node) {
  const cl = customListOf(id);
  if (cl && (cl.disabled_nodes || []).includes(node)) return { ok: false, why: "list_off_node" };
  const prov = providerOf(id);
  if (prov && prov !== "curated" && (Store.panelSettings?.providers || {})[prov] === false) return { ok: false, why: "prov_off" };
  if (!mode) return { ok: true };                       // node record not loaded → gate nothing
  const caps = cl ? customCaps(cl) : catCapsAny(id);
  if (!caps.ip && !caps.host) return { ok: true };      // capability unknown → gate nothing
  return routeCapsUsable(mode, caps) ? { ok: true } : { ok: false, why: "engine", fix: "forcedns" };
}
/** The verdict for any badge — the one call every gate in the field and in egressSaveBlock goes through. */
export const badgeGate = (mode, node, b) => b.t === "list" ? listGate(mode, b.id, node) : targetGate(mode, b.kind);

/* Why a badge cannot run here, said in one sentence, plus the label of the mode that would fix it. Never a
   bare "unsupported": the operator has to be able to act on it, and for three of the five reasons the action
   is one click away. */
export function gateReason(g, modeLabel) {
  switch (g.why) {
    // "unbuilt" HAS TWO MEANINGS AND THEY NEEDED TWO SENTENCES, which only became visible with a kind that is
    // shipped on ONE engine. `contains` on Hybrid SNI took this branch — the matrix allows it, the lowering is
    // not written yet — and said "no node can match it" directly beside the badge's own fix button offering
    // "Switch this node to Kernel SNI", which matches it today. `g.fix` is exactly the discriminator: it is set
    // only when some mode both allows the kind AND ships it, so if it exists then a node CAN match this and the
    // absolute sentence is false. Same hazard the check ORDER above was written for, one step further along.
    case "unbuilt": return g.fix
      ? T("No engine on this node routes this kind yet — {v1} does.", { v1: (MODE_META[g.fix] || {}).label || g.fix })
      : T("This panel doesn't route this kind of address yet — it's classified and stored, but no node can match it.");
    case "list_off_node": return T("Switched off for this node in Settings ▸ Routing lists.");
    case "prov_off": return T("This list's provider is switched off — turn it back on in Settings ▸ Geo data providers.");
    case "engine": return T("{v1} matches by IP only — this needs a host layer.", { v1: modeLabel });
    // ⚠️ ONE SENTENCE PER ENGINE MUST BE TRUE OF EVERY KIND THAT ENGINE REFUSES — five each, and both of
    // these were written for one of the five. `anchor` said "can't match a whole ending", the ZONE case,
    // and was shown on `qualstarts*`, `qualfirst.*` and `*.qualany.*`, none of which is an ending. `whole`
    // said "can't match part of one", the substring case, and was shown on `qualfirst.*` and
    // `*.qualany.*`, which are whole labels, not parts.
    // So state the MATCHER's limit and let every refusal follow from it, rather than listing the cases —
    // a list is what went wrong here, and a list silently stops covering the row when a kind is added.
    // xt_string reports only THAT some bytes occur, never where, so no anchor of any sort is expressible;
    // dnsmasq keys on a suffix, so a name-and-everything-under-it is the only shape there is.
    case "anchor": return T("{v1} only asks whether some text appears somewhere in a name — it never learns WHERE, so it can't anchor to a beginning, an ending or a label.", { v1: modeLabel });
    case "whole": return T("{v1} matches a whole name and everything under it — never a single label on its own, and never part of a name.", { v1: modeLabel });
    // NOT about the node, so it names no engine and offers no fix: switching engines does not raise it.
    // §12.1's cap is a cost bound on the one part of the matcher whose cost grows, and the way out is to
    // stop hand-writing them — which is what the sentence says rather than only stating the number.
    case "cap": return T("{v1} is all one interface can match by text — remove one to add another, or use a list instead.",
                         { v1: plural(TIER2_CAP, "text pattern") });
    default: return T("Not a valid address, IP range or AS number.");
  }
}

/* Record counts for a list, from whatever the panel already knows — the operator's own list (its targets are
   right there), a routed cat's shipped cat_sizes, or this session's /api/list-info cache. `null` means nobody
   has resolved it yet, which is the state the badge calls PREPARING; `{err:true}` means the panel tried and
   came back empty-handed, which is NOT READY and offers a retry.
   ONE function, because the badge and the cost meter both need this and a second copy is how they end up
   disagreeing — which is exactly what happened while building this: the badge resolved and the meter, computed
   in an earlier render, went on quoting a number that was already wrong. */
const _LIST_INFO_PENDING = {};   // id -> ts of the ask now in flight
const _LIST_INFO_WAIT = {};      // id -> Set(onDone) — everyone waiting on that one ask
// Three different nothings, and they are not interchangeable: PENDING is the panel still fetching (→ null, the
// badge waits), FAILED is the panel having tried (→ {err}, the badge offers a retry), and zero counts with
// neither flag is a list that resolved and routes nothing (→ 0, which is a number and gets shown).
const _sizeOfInfo = d => {
  if (!d || !d.tiers) return { err: true };
  const host = (d.tiers.host || {}).n || 0, ip = (d.tiers.ip || {}).n || 0;
  if (host || ip) return { host, ip };
  const any = f => Object.keys(d.tiers).some(k => d.tiers[k] && d.tiers[k][f]);
  if (any("pending")) return null;
  return any("failed") ? { err: true } : { host: 0, ip: 0 };
};
export function listSizeNow(id) {
  const cl = customListOf(id);
  if (cl) { const b = listBuckets(cl); return { host: b.host.length, ip: b.ip.length, pat: b.pat.length }; }
  const s = (Store.catSizes || {})[id];
  if (s && (s.host || s.ip)) return { host: s.host || 0, ip: s.ip || 0 };
  const c = _LIST_INFO_CACHE[id];
  return c ? _sizeOfInfo(c) : null;
}
/* The panel answers "still fetching" now instead of holding the connection open (§6.1), so asking once is not
   enough — ask again, on a timer, and give up out loud rather than spinning for ever. Both numbers are the
   plan's: re-ask every ~1.5 s, stop after ~60 s. */
const LIST_ASK_MS = 1500, LIST_WAIT_MS = 60000;
/** Resolve one list, polling while the panel says it is still working. Writes the answer into the shared cache
 *  and calls `onDone` after every attempt, so a badge and the cost meter redraw together.
 *
 *  TWO CALLERS, TWO HORIZONS, and the difference is who is waiting. A BADGE is a list the operator committed
 *  to, so it waits the full minute and, when nothing comes, writes an error — "we waited and nothing came" is
 *  a state it can show and offer a retry on, where an absent entry would just start the cycle again. A BROWSE
 *  ROW is one of fifty things being scrolled past: it asks, re-asks once, and then stops, leaving the pending
 *  answer alone so a badge made from that row can take over the waiting. Fifty rows polling every 1.5 s for a
 *  minute would be the same thundering herd this endpoint was just fixed to avoid, on the client side. */
function askListInfo(id, onDone, opts) {
  // EVERY caller is told, not just the one that started it. A badge picked from a browse row asks about the
  // same id that row is already asking about, so it used to return here and then never hear anything — the
  // row's short poll gave up, cleared the flag, and the badge sat on "preparing…" for ever with nobody left
  // waiting. Whoever owns the request notifies all of them, and the last notification is what lets a badge
  // start its own longer wait where the row left off.
  const waiters = _LIST_INFO_WAIT[id] || (_LIST_INFO_WAIT[id] = new Set());
  waiters.add(onDone);
  if (_LIST_INFO_PENDING[id]) return;
  const { retry = false, waitMs = LIST_WAIT_MS, errOnGiveUp = true } = opts || {};
  const first = Date.now();
  _LIST_INFO_PENDING[id] = first;
  const fire = () => { for (const f of [...(_LIST_INFO_WAIT[id] || [])]) { try { f(); } catch (_) { /* unmounted */ } } };
  const stop = d => { if (d) _LIST_INFO_CACHE[id] = d; delete _LIST_INFO_PENDING[id]; fire(); delete _LIST_INFO_WAIT[id]; };
  const go = force => api.listInfo(id, force).then(r => {
    const d = (r && r.ok) ? r.data : { err: true };
    const busy = !!(d.tiers && Object.keys(d.tiers).some(k => d.tiers[k] && d.tiers[k].pending));
    if (!busy) return stop(d);
    _LIST_INFO_CACHE[id] = d;
    if (Date.now() - first >= waitMs) return stop(errOnGiveUp ? { err: true } : null);
    fire();
    setTimeout(() => { if (_LIST_INFO_PENDING[id] === first) go(false); }, LIST_ASK_MS);
  }).catch(() => stop({ err: true }));
  go(!!retry);
}
/* Resolve every list in the row that nobody has resolved yet, and re-render when one lands. Picking a list
   already had to ask /api/list-info for its size, and that endpoint already kicks the panel's own background
   resolve, so resolve-on-pick needs no new endpoint and no second call (§6.2). */
function useListSizes(ids, onLand, tries) {
  const key = ids.join(",");
  useEffect(() => {
    let live = true;
    for (const id of ids) if (!listSizeNow(id)) askListInfo(id, () => live && onLand());
    return () => { live = false; };
  }, [key, tries]);
}
// STATUS ONLY — the SIZE is deliberately not drawn here any more. "28 hosts · 911 nets" beside every list
// badge is the widest thing in a rule row and the least often needed: it helps you CHOOSE a list, which is
// the dropdown row's job (`catrow-size`), not to recognise one you already picked. Four lists in a rule used
// to push the row to two lines for a number nobody was reading. It moves to the badge's tooltip in `Badge`,
// so it is a hover away rather than gone.
//
// The other two states STAY, because neither is a size: "preparing…" says the rule is fine and waiting, and
// "not ready" is the only retry there is for a list the panel has not fetched. Dropping those with the
// number would have removed the way out of a stuck list to save the same pixels.
function ListBadgeSize({ cat, onRetry }) {
  // ⚠️ "NOT FOUND" IS NOT "NOT READY", and the badge used to say the second for both. A list the panel has
  // simply not fetched yet is a WAIT with a way out; a list it has no record of is a rule that will never
  // match anything. They looked identical — same word, same amber, same retry — so an id that does not
  // exist rendered as a plausible provider badge: `v2:no-such-list` even wears v2fly's own green chip.
  //
  // Both states are reachable without anyone typing nonsense: a provider switched off in Settings, or a
  // list withdrawn upstream, turns a rule that used to work into one naming something gone.
  //
  // Said only when it can be PROVEN — `knownListId` answers false only with a loaded, non-empty catalog
  // that does not contain the id; while the catalog is unknown it says nothing, and the wait applies.
  if (!knownListId(cat)) return html`<span class="tfb-size missing"
    title=${T("No list with this id — its provider may be switched off in Settings, or the list was withdrawn upstream. The rule keeps it, and it matches nothing until it comes back.")}>${T("list|not found")}</span>`;
  const sz = listSizeNow(cat);
  // RESOLVED TO NOTHING IS ALSO A PROBLEM, and moving the size to the tooltip lost the signal that used to
  // say so: the old branch printed the count or the word "empty", and returning null for both meant a list
  // that resolves to zero records — which is what a made-up id under a REAL provider does — showed no state
  // at all. It is the only signal available when the catalog is not loaded and `knownListId` cannot judge.
  if (sz && !sz.err) return sizeSummary(sz.host, sz.ip) ? null : html`<span class="tfb-size missing"
    title=${T("The panel resolved this list and it holds nothing — check the id, or the source may have emptied it.")}>${T("list|empty")}</span>`;
  if (!sz) return html`<span class="tfb-size preparing" title=${T("The panel is fetching this list now — it routes as soon as it lands.")}>${T("preparing…")}</span>`;
  // The rule saves and routes as soon as the list lands; this is not an error, it is a wait with a way out.
  return html`<button type="button" class="tfb-size notready" title=${T("The panel hasn't fetched this list yet. The rule saves either way and routes as soon as it lands — click to ask again.")}
    onClick=${e => { e.stopPropagation(); delete _LIST_INFO_CACHE[cat]; delete _LIST_INFO_PENDING[cat];
                     askListInfo(cat, onRetry, { retry: true }); onRetry(); }}>${T("not ready")}</button>`;
}

// ── THE TEXT FORM OF A BADGE ──────────────────────────────────────────────────────────────────────────
// The grammar itself lives in `js/rulerows.js`, beside `badgeIdentity` and `badgeCovers`, because it is a
// FORMAT and not a screen: operators keep it in files and paste it between panels, so it must not depend on
// what this panel happens to have loaded. That module imports no preact, which is what lets
// `.campaign/textform-audit.mjs` prove the round trip in node — a property no amount of clicking can hold.
//
// Policy is injected rather than baked in: which KINDS this node's engine accepts, and which LIST IDS this
// panel can vouch for, are both live state, and neither belongs in a grammar.
/* `listEditor` is the CUSTOM-LIST context: a field editing a list, not a rule. A list may not contain another
   list — cascade_plan expands `custom_lists[cat]` into its domains/cidrs/patterns and never recurses, so a
   nested id would store cleanly, badge cleanly, and route NOTHING. That is the `*.ru` shape exactly, and the
   cheapest place to stop it is the grammar, where the refusal already travels back to the field. */
const readToken = (tok, mode, listEditor) => rrReadToken(tok, {
  allowKind: k => targetGate(mode, k).ok,
  knownList: listEditor ? () => false : knownListId,
});

// Is this a list this panel can route? Checked against the three places one can come from — and REFUSED only
// when we can PROVE it is none of them.
//
// ⚠️ THE CATALOG IS LAZY. `_CATALOG_BY_ID` fills when the dropdown first opens, so a strict check refused
// every provider list until the operator had happened to browse — measured here, where the providers `mc`
// (metacubex) and `v2` (v2fly) are configured and `list:metacubex:youtube` was rejected as unknown purely
// because nothing had asked for the index yet. A refusal that depends on where the operator clicked before
// is not a refusal, it is a race. So an unloaded catalog means "cannot say", and the token is accepted:
// the SERVER is the real authority and already drops a category none of the catalog, the custom lists and
// the built-ins have heard of, reporting it as `unknown_list` (swg-panel-server:10927).
export const knownListId = id => !!id && (
  SMART_CATEGORIES().some(([c]) => c === id)                                    // a curated preset
  || (Store.panelSettings?.custom_lists || []).some(l => l && l.id === id)      // one the operator wrote
  // ⚠️ THE BENEFIT OF THE DOUBT IS ONLY FOR PROVIDER IDS. A BARE id can always be judged: the curated
  // presets and the custom lists are both held locally, so `list:nope` is provably nothing on any panel,
  // catalog or no catalog. Extending the doubt to it meant a plain typo was accepted everywhere and then
  // shown as "not ready" — a WAIT, for a list that is never coming. Only `provider:list` needs the index.
  || (isProviderCat(id) && (!!_CATALOG_BY_ID[id]                                // already indexed…
                            || !_CATALOG_INDEX || !_CATALOG_INDEX.length)));    // …or there is no index to ask
// ⚠️ AN EMPTY INDEX IS NOT AN ANSWER, and the first version of this guard treated it as one. `[]` is truthy,
// so a panel whose providers are configured but whose lists have not been fetched — exactly the state this
// one is in — loaded a successful, EMPTY catalog and then refused every provider list with a straight face.
// "Found nothing" is not "looked and it is not there"; only a non-empty index can say a list does not exist.

// WHOSE LIST IS THIS — the one answer the chip and the tooltip both use, so they cannot disagree.
// "Custom" was the fallback for anything without a provider, which made it a claim rather than a label: an
// id the panel has never heard of has no provider EITHER, so a `list:no-such-thing` typed in the text view
// came back badged "Custom list" — naming a source it does not have. A custom list is one that is actually
// in `custom_lists`; everything else with no provider is simply unknown, and the badge already says so a
// second way ("not found", or "empty" when it resolved to no records).
const listSourceOf = id => provLabelOf(id) || (customListOf(id) ? T("Custom") : T("Unknown list"));

// The resolved size as a string, or "" — for the badge TOOLTIP, since the badge no longer spends a row on it.
const listSizeOf = cat => { const sz = listSizeNow(cat);
  return sz && !sz.err ? (sizeSummary(sz.host, sz.ip) || T("empty")) : ""; };

/* One badge. A list keeps its provider colour; its size moved to the tooltip (see ListBadgeSize). A typed
   target shows the canonical form of what was written plus the kind, in the same .capb slot a list uses for
   Host/IP. Inert badges keep their content and lose their colour — a capability change must never look
   like a deletion. */
function Badge({ b, gate, node, modeLabel, onRemove, onEdit, onFix, onRetry, onReveal, editing }) {
  const inert = !gate.ok;
  const isList = b.t === "list";
  const wide = !isList && KIND_WIDE[b.kind];
  const puny = isList ? "" : targetPuny(b.kind, b.value);
  const title = inert ? gateReason(gate, modeLabel)
    // NAMED BY ITS PROVIDER, from the same source as the chip beside it, so the two cannot say different
    // things about one badge: "Curated list — …", "v2fly list — …", "Custom list — …".
    : isList ? T("{v1} list — the panel resolves it and every node routing it pulls the same copy.",
                 { v1: listSourceOf(b.id) })
      + (listSizeOf(b.id) ? " · " + listSizeOf(b.id) : "")
    : targetSentence(b.kind, b.value)
      + (puny ? " · " + T("Stored and matched as {v1}.", { v1: puny }) : "")
      // A STORED badge can be over the node's limit too — it was typed before this node moved to an engine
      // that has one, or posted by an API client. The live sentence says it while typing; without this the
      // same operand goes quiet the moment it becomes a badge, which is the half of §10.5 item 9 that is
      // about a rule the operator has already finished writing.
      + opTooLongNote(node, b.kind, b.value)
      + (gate.degraded ? " · " + T("On this node it is matched as text anywhere in the name.") : "");
  return html`<span class=${"tfbadge" + (isList ? " list" : " tgt") + (wide ? " wide" : "") + (inert ? " inert" : "") + (gate.degraded ? " degraded" : "") + (editing ? " editing" : "")} title=${title}>
    ${inert ? html`<span class="tfb-g" aria-hidden="true">⊘</span>` : null}
    ${/* A LIST BADGE WAS INERT. Clicking it fell through to the box, which opens the dropdown at the top —
          so the operator had to go and find the thing they had just pointed at. It now opens AT that list. */""}
    <button type="button" class="tfb-main" onClick=${() => (isList ? (onReveal && onReveal(b.id)) : onEdit())} title=${title}>
      <span class="tfb-lbl">${isList ? catLabelOf(b.id) : targetLabel(b.kind, b.value)}</span>
      ${isList ? html`<${ProvTag} id=${b.id} label=${listSourceOf(b.id)}/>`
        : html`<span class=${"capb " + (wide ? "wide" : "kind")}>${KIND_LABEL()[b.kind]}</span>`}
    </button>
    ${isList ? html`<${ListBadgeSize} cat=${b.id} onRetry=${onRetry}/>` : null}
    ${inert && gate.fix && onFix ? html`<button type="button" class="tfb-fix" title=${T("Switch this node to {v1}", { v1: (MODE_META[gate.fix] || {}).label || gate.fix })}
      onClick=${e => { e.stopPropagation(); onFix(gate.fix); }}><${Ic} i="refresh"/></button>` : null}
    <button type="button" class="tfb-x" title=${T("Remove")} aria-label=${T("Remove {v1}", { v1: isList ? catLabelOf(b.id) : targetLabel(b.kind, b.value) })}
      onClick=${e => { e.stopPropagation(); onRemove(); }}><${Ic} i="x"/></button>
  </span>`;
}

// Overflow threshold: past this many badges a row would push its destination dropdown off screen, so the tail
// collapses behind a count that expands in place. Fifteen services in one row is the point of the field.
const BADGE_CAP = 10;

// `trailing` is a SLOT IN THE FOOT, not another column. The rule row wants the box across the full width of
// the dialog with the destination control tucked under it on the right, level with the entry count — and the
// foot belongs to this component (it is built from state nobody outside can see), so the destination comes
// IN rather than the foot going OUT. The alternative was `display:contents` on `.tfield` to flatten it into
// the row's grid, which would have zeroed the very box the popover measures itself against.
/* `listEditor` — this field is editing a LIST's contents, not a rule. One context flag rather than three
   behaviour flags (`addMode` on CatPicker is the same shape): a caller cannot combine them wrongly, and
   everything it switches follows from the one fact. It was briefly called `noLists`, which named one of the
   four things it does and left the other three — the copy, the toggle's placement, the absent catalog —
   reading as unrelated.
   No node, no catalog, no nesting. The custom-list editor is the one consumer
   with no interface behind it: `mode` is absent so targetGate refuses nothing on engine grounds ("no mode
   known → gate nothing", as _shippedOn already said), the budget belongs to the rule that NAMES this list
   rather than to the list, and the catalog is hidden because a list cannot hold one. Everything else — the
   badges, the text view, click-to-edit, the per-token reasons — is the same control an operator already
   knows from a rule, which is the whole point of reusing it. */
export function TargetField({ row, mode, node, tier2All, onChange, onSwitchMode, onLint, trailing, leading, listEditor }) {
  // ── THE FIELD'S STATE, and the two rules that keep it consistent ────────────────────────────────────
  // This component is large because it is one control with two readings (badges and text) over one rule.
  // Two invariants make the combinations safe, and both are enforced by there being exactly ONE writer:
  //
  //   1. `asText` and `editing` are never both set. `setEditing({b})` happens only in `edit()`, which is
  //      reachable only from a badge — and the text view returns before any badge is rendered. `toText`,
  //      the only place that sets `asText`, clears `editing` on the way in.
  //   2. A badge being edited STAYS in `badges`. It used to be removed, which put half the rule in `q`
  //      where `toText` and the sheet's own save could not see it, and both lost it. Nothing may
  //      reintroduce that: the box is a DRAFT of a badge, never its only copy.
  //
  // If a third reading is ever added, replace the booleans with one mode enum rather than adding a flag —
  // two flags are already the most that can be checked by reading.
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  // −1 IS "NOTHING HIGHLIGHTED", and it has to exist. `act` indexes `rows`, and 0 was doing double duty as
  // both "the first row is selected" and "no selection" — so after every commit, and on every keystroke, the
  // first row of the dropdown lit up. With an empty box that row is the first preset, which is why clicking
  // any list left `ChatGPT / OpenAI` highlighted as though it were the one just picked.
  const [act, setAct] = useState(-1);
  // The badge currently pulled into the box, and the slot it came from: `{b, at}`, or null. Escape restores
  // it — an edit has to be abandonable, and without this the badge was simply gone the moment it was clicked
  // and the only way back was to retype it. `at` is kept so a cancelled (or merely re-clicked) badge returns
  // to ITS position instead of the end of the row, which is what the operator arranged.
  const [editing, setEditing] = useState(null);
  const [reveal, setReveal] = useState(null);   // a list id to scroll to once the dropdown has rendered it
  // TEXT VIEW. Badges are unselectable, so a rule could be built but never READ OUT — no copy for a backup,
  // no paste from a file someone already keeps, no copying a set of targets to a second interface without
  // retyping it one badge at a time. `asText` swaps the box for a textarea holding the same targets, ONE PER
  // LINE: lines are what a file, a diff and a grep are made of, and the paste path already splits on
  // whitespace, so text written here pastes back into any other rule field unchanged.
  const [asText, setAsText] = useState(false);
  const [draft, setDraft] = useState("");
  const [page, setPage] = useState(0);
  const [cidx, setCidx] = useState(_CATALOG_INDEX);
  const [expand, setExpand] = useState(false);
  const [say, setSay] = useState("");                       // aria-live: what just happened
  // THE FOOT'S OWN MESSAGE, and a separate state from `say` because the two answer different questions at
  // the same moment. `say` is "what just happened" and every action sets it; this is "why does the box still
  // hold text". Remove a badge while refusals wait and the two diverge: aria-live must say "Removed
  // *seed001*", while the foot must still say why the leftovers bounced — that is the sentence the operator
  // is in the middle of acting on, and `remove` does not touch the box, so it is still true.
  //
  // It carries the `q` it was written for, which makes it SELF-INVALIDATING: typing, editing a badge back
  // into the box, or another paste all change `q` and the message stops being shown on its own. No call site
  // has to remember to clear it, which is the kind of discipline that holds until the next path is added.
  const [pending, setPending] = useState({ text: "", forQ: null });
  const [tries, bump] = useState(0);                        // a size landed, went late, or was asked for again
  const ref = useRef(null), popRef = useRef(null), inRef = useRef(null);
  const badges = row.badges || [];
  const modeLabel = (MODE_META[mode] || {}).label || mode;
  useListSizes(badges.filter(b => b.t === "list").map(b => b.id), () => bump(x => x + 1), tries);
  // The size meter below counts an AS badge's prefixes, so this field is a READER of the ASN cache and has
  // to be woken when a lookup lands — exactly like the list sizes on the line above. Without it the meter
  // showed a stale count beside AsnHint's fresh one; see the note on `_asnSubs`.
  useAsnCounts(badges.filter(b => b.t === "target" && b.kind === "asn").map(b => b.value));

  const ql = q.trim().toLowerCase();
  // A `list:` TOKEN IS NOT A TARGET, and the classifier is right to refuse it — `list:youtube` is not a
  // hostname. But then typing one did nothing at all: Enter is gated on `readGate.ok`, so a valid list
  // pasted as text committed while the same text TYPED sat in the box being called a bad domain. Read here,
  // once, so the box offers the same thing the paste path and the textarea already do.
  const listTok = /^list:(.+)$/i.exec(q.trim());
  /* ⚠️ A SECOND READER OF THE SAME QUESTION. `readToken` learned `listEditor` and refused a nested id at the
     grammar — and this line kept saying yes, because it asks `knownListId` directly. The dropdown duly
     offered "Telegram · add this list to the rule" inside the CUSTOM-LIST editor, which cannot hold one.
     Found by clicking, not by reading: both readers were individually correct. */
  const readList = (listTok && !listEditor) ? { id: listTok[1].trim(), ok: knownListId(listTok[1].trim()) } : null;
  const reading = (!listTok && q.trim()) ? classify(q.trim()) : null;     // the "use this" row, when what is typed parses
  // Tier-2 targets on this INTERFACE (§12.1), counted by the parent because the row that is full is not
  // necessarily the row being typed in. Passed as the WHOLE total including this row's, not as "everyone
  // else's": `badges` is `row.badges`, so subtracting this row upstream and adding it back here computed
  // the same number by a longer route, and two expressions of one figure is how they drift.
  const t2Used = tier2All || 0;
  // WHAT THE FIELD REFUSES = what the ENGINE refuses, plus the one thing targetGate cannot be asked about:
  // the budget is a property of the interface, not of the token or of the node's engine, so it cannot live
  // in a per-kind table. It gets the same shape and the same treatment because to the operator it is the
  // same no — this cannot go in, and here is why. Said in the dropdown BEFORE the click rather than
  // announced after it: §4.2 already established one visual for a target this interface will not take, and
  // a row that reads live and then refuses is the shape of defect a live node caught in Phase 3.
  //
  // …EXCEPT for one the row already holds. A row is a set, so re-typing a pattern that is already a badge
  // adds nothing and costs nothing — telling that operator "remove one to add another" would be a lie about
  // a target that is right there in front of them. `reading` has no `t`, which badgeIdentity reads as a
  // target, so it compares against the typed badges exactly as addAll's own dedupe does.
  const readGate = reading && reading.kind !== "invalid"
    ? (g => g.ok && isTier2(reading.kind) && t2Used >= TIER2_CAP && !rowHasBadge(row, reading)
        ? { ok: false, why: "cap" } : g)(targetGate(mode, reading.kind))
    : null;

  // A row is a SET: adding the same thing twice is a no-op, not an error — but it is announced, because a
  // gesture that silently does nothing reads as a broken control. Returns what was added, and separately
  // what the §12.1 budget refused — a paste of two hundred substrings must not report itself as a success.
  //
  // THE ONE CHOKE POINT. Every way a badge can arrive — a picked row, a typed token, a pasted blob — comes
  // through here, so the budget is counted once and cannot be enforced on two of the three paths.
  const addAll = (toks, opts) => {
    const next = [...((opts && opts.base) || badges)], added = [], overCap = [];
    // `t2Used` is the INTERFACE's Tier-2 count and already includes this row. Rebuilding the row from a base
    // means this row's current Tier-2 badges are on their way out, so the budget has to give them back first
    // — otherwise re-saving a row unchanged would count its own operands twice and refuse itself.
    const t2Base = (opts && opts.base)
      ? t2Used - badges.filter(b => b.t === "target" && isTier2(b.kind)).length
                + opts.base.filter(b => b.t === "target" && isTier2(b.kind)).length
      : t2Used;
    let t2 = t2Base;
    for (const t of toks) { const b = t.t === "list" ? t : { t: "target", raw: t.raw, kind: t.kind, value: t.value };
      if (next.some(x => badgeIdentity(x) === badgeIdentity(b))) continue;
      // Counted as it goes, not up front: a paste has to stop at the budget rather than be refused whole,
      // and what came before the limit is worth keeping.
      if (b.t === "target" && isTier2(b.kind)) {
        if (t2 >= TIER2_CAP) { overCap.push(targetLabel(b.kind, b.value)); continue; }
        t2 += 1;
      }
      next.push(b); added.push(b.t === "list" ? catLabelOf(b.id) : targetLabel(b.kind, b.value)); }
    // `defer` returns the new list instead of emitting it, so a caller that also has to REMOVE a badge can
    // do both in one onChange. Two calls would each be computed from the same stale `badges` and the second
    // would silently undo the first.
    if (added.length && !(opts && opts.defer)) onChange(next);
    return { added, overCap, next };
  };
  // The bulk paths announce what the dropdown says inline, THROUGH THE SAME FUNCTION — a paste can cross the
  // budget partway, which the dropdown's one-token reading cannot express, and two copies of one sentence is
  // how the two stop agreeing. §12.1: "nobody hand-writes a hundred substrings; past that the right answer is
  // a list, and the message should say so."
  const capSay = () => gateReason({ why: "cap" }, modeLabel);
  // LISTS ONLY — `commitList` is its one caller and a list can never be a Tier-2 target, so there is no
  // budget to check on this path. It was briefly given one; the branch could not fire, and a guard that
  // cannot fire is a guard the next person will trust.
  /* THE PICK CLEARS THE QUERY — reversed 2026-09-07, and the reason the first version kept it was real but
     smaller than what it cost. Keeping it let a second list be added from the same search without retyping.
     What it did in exchange: THE QUERY IS NOT ONLY A FILTER. The same string is read as a pending TARGET,
     so after picking `tester` out of a search for "test" the field went on offering "use what you typed"
     and linting «did you mean the whole .test zone?» — about a target the operator never meant to type,
     while the badge they DID add sat beside it. They then had to clear the box by hand before typing
     anything else.
     One input cannot be both "what I am typing" and "a filter that no longer counts"; that is a hidden mode,
     and the common case (pick one, move on) paid for the rare one (pick several from one search). Picking
     from a dropdown clearing the input is also what every other chip field does.
     The dropdown STAYS OPEN and focus stays in the input, so a second list is still one click away — it is
     the search term that goes, not the list of things to click. */
  const commit = b => {
    const { added } = addAll([b]);
    setEditing(null);
    setQ(""); setPage(0); setAct(-1); setPending({ text: "", forQ: null });
    setSay(added.length ? T("Added {v1}", { v1: added[0] }) : T("Already in this rule."));
    if (inRef.current) inRef.current.focus();
  };
  const commitList = id => commit({ t: "list", id });
  const commitTyped = () => {
    // THROUGH `readToken`, so the box understands `list:youtube` exactly as the textarea does. Text copied
    // out of one rule has to paste into another as the same thing, and the box is where most of it lands.
    const parts = String(q || "").split(/[\s,]+/).filter(Boolean).map(t => ({ tok: t, r: readToken(t, mode, listEditor) }));
    if (!parts.length) return;
    const good = [], bad = [];
    for (const { tok, r } of parts) (r && r.b) ? good.push(r.b) : bad.push({ raw: tok, why: (r || {}).why });
    // Paste a blob and the tokens that read cleanly land as badges; the ones that don't stay behind as text so
    // they can be fixed in place. Never a modal, never a silent drop (§3.2).
    // AN EDIT THAT CHANGED NOTHING IS NOT AN EDIT. Clicking along a row to read each badge commits each one
    // in turn, and replacing a badge with itself removes and re-appends it — so the row quietly reordered
    // under the operator, which is the exact thing keeping the badge in place was meant to stop.
    if (editing && !bad.length && good.length === 1 && badgeIdentity(good[0]) === badgeIdentity(editing.b)) {
      setEditing(null); setQ(""); setPage(0); setAct(-1); setPending({ text: "", forQ: null });
      return "";
    }
    // THE EDITED BADGE IS REPLACED, not duplicated: dropping it from the base means the new value is not
    // refused as a duplicate of itself, and the old one does not survive beside it.
    const base = editing ? badges.filter(x => x !== editing.b) : badges;
    const { added, overCap, next } = addAll(good, { base, defer: true });
    const rest = [...bad.map(b => b.raw), ...overCap].join(" ");
    if (added.length || editing) { onChange(next); setEditing(null); }
    setQ(rest);                                            // both kinds of leftover stay in the box, editable
    const msg = bad.length ? (bad[0].why === "unknown_list" ? (listEditor ? T("A list can't contain another list — add its addresses here instead") : T("No list called {v1} on this panel", { v1: bad[0].raw }))
                                                            : T("{v1} was not added", { v1: bad[0].raw }))
      : overCap.length ? capSay()
      : added.length ? T("Added {v1}", { v1: added.join(", ") })
      : T("Already in this rule.");
    setSay(msg);
    setPending({ text: rest ? msg : "", forQ: rest });      // only while something actually stayed behind
    setPage(0); setAct(-1);
    return rest;                                           // "" when everything landed — edit() needs to know
  };
  // Clicking a typed badge returns it to the field AS THE BADGE READS, not as it is stored. Those are the
  // same string for almost everything, and were not for an IDN name: a `site` is stored canonical, so
  // clicking `яндекс.рф` put `xn--d1acpjx3f.xn--p1ai` in the box — the operator's own name, handed back in a
  // form they did not write and cannot edit. (Patterns keep the written form, which is why the zone badges
  // beside it came back correctly and hid this.)
  //
  // idnHost on the RAW, not targetLabel on the value: raw carries the syntax that produced the kind, and a
  // zone's label (`.ru`) does not classify back to a zone. Decoding whole labels leaves `*`, `/` and every
  // ASCII token untouched, and what comes back re-reads to the same kind and value — so committing it again
  // stores exactly what was there before.
  //
  // ONE THING IN THE BOX AT A TIME. This used to APPEND the clicked badge to whatever the box already held,
  // so clicking three badges in a row merged three separate rules into one run of text — `*google* *.ru
  // google.com`, a single string where the operator had clicked three things, with the foot then counting
  // "2 entries · 2 names" about a box they never typed into. Clicking a badge means "edit THIS one", so
  // anything already in the box goes back to being badges first, in the same gesture.
  //
  // If part of the box CANNOT become a badge — an unreadable token, or Tier-2 over §12.1's budget — the
  // clicked badge is left exactly where it is and the leftovers keep the box. Pulling it in on top of them
  // would be the same merge again, one step later; refusing says which token is in the way, and a second
  // click opens the badge once the box is clear.
  // ⚠️ THE BADGE STAYS IN THE ROW WHILE IT IS EDITED. It used to be removed the instant you clicked it,
  // leaving it alive only as text inside this component — a second, invisible half of the rule that every
  // other path had to know about. Two paths did not: `toText` built its draft from `badges` and destroyed
  // it, and SAVING THE SHEET mid-edit dropped it silently, because the parent had already been told it was
  // gone. Both were measured, not theorised.
  //
  // Keeping it means there is nothing to restore: Escape just clears the box, `toText` reads the row and
  // sees everything, a save mid-edit keeps the original, and clicking along a row no longer reorders it —
  // which is what the "put an untouched badge back in its own slot" branch existed to undo.
  const edit = i => { const b = badges[i]; if (b.t !== "target") return;
    if (editing && editing.b === b) { if (inRef.current) inRef.current.focus(); return; }
    if (commitTyped()) return;              // something in the box could not land — fix that before moving on
    setEditing({ b });
    setQ(idnHost(b.raw));                   // `raw`, so an IDN name comes back as the operator wrote it
    setPending({ text: "", forQ: null }); setPage(0); setAct(-1);
    if (inRef.current) inRef.current.focus(); };
  const remove = i => { const b = badges[i]; onChange(badges.filter((_, j) => j !== i));
    setSay(T("Removed {v1}", { v1: b.t === "list" ? catLabelOf(b.id) : targetLabel(b.kind, b.value) })); };
  // By id rather than index, because the dropdown row knows which LIST it is and not where its badge sits.
  const removeList = id => { onChange(badges.filter(b => !(b.t === "list" && b.id === id)));
    setSay(T("Removed {v1}", { v1: catLabelOf(id) }));
    if (inRef.current) inRef.current.focus(); };

  // `!(cidx && cidx.length)` — an empty index means "nothing was enabled when we asked", not "asked and
  // there is nothing", so opening the dropdown after switching a provider on has to ask again.
  useEffect(() => { if (open && !(cidx && cidx.length)) { let live = true; loadCatalogIndex().then(x => live && setCidx(x)); return () => { live = false; }; } }, [open, cidx]);
  const place = () => { const el = ref.current; if (!el) return; setPos(placeWide(el)); };
  useEffect(() => {
    if (!open) return; place();
    const onMove = () => place();
    const onDoc = e => { const t = e.target;
      if (!((ref.current && ref.current.contains(t)) || (popRef.current && popRef.current.contains(t)))) setOpen(false); };
    window.addEventListener("scroll", onMove, true); window.addEventListener("resize", onMove);
    document.addEventListener("mousedown", onDoc, true);
    return () => { window.removeEventListener("scroll", onMove, true); window.removeEventListener("resize", onMove); document.removeEventListener("mousedown", onDoc, true); };
  }, [open]);

  // What the dropdown offers, as ONE flat list — because the keyboard walks it as one list and "the top row"
  // has to mean the same thing to Enter as it does to the eye. An empty query offers only the presets and the
  // operator's own lists: 3,000 alphabetical country files is not an answer to "what do you want to route",
  // and rendering a page of them would fire a page of list-info fetches on every focus.
  const per = 50;
  const _curated = SMART_CATEGORIES().filter(([id]) => id !== "all")
    .map(([id, label]) => ({ id, provider: "curated", provider_label: T("Curated"), caps: catCap(id), disp: label }))
    .filter(it => !ql || it.id.toLowerCase().includes(ql) || it.disp.toLowerCase().includes(ql) || catDescOf(it.id).toLowerCase().includes(ql))
    .sort((a, b) => a.disp.toLowerCase().localeCompare(b.disp.toLowerCase()));
  const _mine = (Store.panelSettings?.custom_lists || [])
    .filter(l => l && (!ql || String(l.title || "").toLowerCase().includes(ql) || String(l.id || "").toLowerCase().includes(ql)))
    // `label` is what CatalogRow titles the row with — without it prettyCatLabel falls through to titleizing
    // the id, and "Office subnets" rendered as "Cl Office".
    .map(l => ({ id: l.id, provider: "custom", provider_label: T("Custom"), caps: customCaps(l),
                 disp: l.title || l.id, label: l.title || l.id, list: l }))
    .sort((a, b) => a.disp.toLowerCase().localeCompare(b.disp.toLowerCase()));
  const _cat = (ql.length >= 2 && cidx) ? cidx.filter(it => it.hay.includes(ql)).sort((a, b) => a.disp.localeCompare(b.disp)) : [];
  const catPage = _cat.slice(page * per, (page + 1) * per);
  const pages = Math.max(1, Math.ceil(_cat.length / per));
  const has = id => badges.some(b => b.t === "list" && b.id === id);
  // OPEN THE DROPDOWN AT A LIST, not at the top. Presets and the operator's own lists are always listed in
  // full, so an empty query already shows them; a PROVIDER-CATALOG list is only listed while searching, and
  // then only 50 to a page — so this searches for it and lands on the page that actually holds it. Without
  // both halves "open at it" would silently mean "open at the top" for exactly the long lists where finding
  // it by hand is the hard part.
  const revealList = id => {
    setOpen(true); setEditing(null);
    const local = SMART_CATEGORIES().some(([c]) => c === id)
               || (Store.panelSettings?.custom_lists || []).some(l => l && l.id === id);
    if (local) { setQ(""); setPage(0); }
    else {
      const term = catRawId(id).toLowerCase();
      setQ(catRawId(id));
      const hits = (cidx || []).filter(it => it.hay.includes(term)).sort((a, b) => a.disp.localeCompare(b.disp));
      const at = hits.findIndex(it => it.id === id);
      setPage(at >= 0 ? Math.floor(at / per) : 0);
    }
    setReveal(id);
  };

  const rows = [];
  if (reading && reading.kind !== "invalid") rows.push({ k: "use" });
  if (!listEditor) {                      // a list cannot hold a list, so it is not offered one
    _curated.forEach(it => rows.push({ k: "list", it, grp: T("Recommended presets") }));
    _mine.forEach(it => rows.push({ k: "list", it, grp: T("Your lists") }));
    catPage.forEach(it => rows.push({ k: "list", it, grp: T("Provider catalog") }));
  }
  const activeRow = rows[Math.min(act, rows.length - 1)];
  /* ONE RESULT IS NOT A CHOICE. Narrow the search to a single row and there is nothing left to choose
     between, so it is highlighted for you and Enter takes it — no reach for the mouse. The catalog picker
     already works this way ("ONLY when exactly one result"), so this is the same rule in the other picker
     rather than a new one to learn.
     ⚠️ Everything else goes back to -1, and -1 has to keep meaning "nothing highlighted": collapsing it
     into 0 = "the first row" is what lit a phantom highlight on the first preset after every commit. The
     effect is keyed on the SEARCH, not on `act`, so arrow keys still move freely between keystrokes.
     ⚠️ AND ON `open`. Escape closes the dropdown without clearing `q`, and `rows` is computed whether or
     not the popover is showing — so without this the highlight survived the dismissal and Enter committed
     a list the operator could no longer see, instead of the text they had typed. A highlight nobody can
     see must not decide what a key does. */
  useEffect(() => { setAct(open && rows.length === 1 ? 0 : -1); }, [rows.length, q, open]);

  // The scroll has to wait for the portal AND for the row itself: setting the query and the page re-renders
  // the list, and the popover is a Portal that lands a tick or two later. Retried and BOUNDED — a `reveal`
  // that never resolves (a list the catalog no longer carries) clears itself rather than leaving the field
  // pinned to an id it can never find.
  //
  // ⚠️ setTimeout AND NOT requestAnimationFrame, which is what this was written with first. Chrome throttles
  // rAF to nothing while its WINDOW IS NOT FOCUSED — `document.visibilityState` still reads "visible", so
  // nothing about the page says the callback has stopped arriving; measured here, zero rAF callbacks in
  // 600 ms with the window merely behind another one. A panel left open beside a terminal is exactly that
  // case, so the retry would have quietly done nothing for the operator and been blamed on the selector.
  useEffect(() => {
    if (!reveal || !open) return;
    let timer = 0, tries = 0, passes = 0;
    const sel = '[data-lid="' + String(reveal).replace(/["\\]/g, "\\$&") + '"]';
    const centre = () => {
      const root = popRef.current, el = root && root.querySelector(sel);
      if (!el) { if (++tries < 25) timer = setTimeout(centre, 20); else setReveal(null); return; }
      const list = root.querySelector(".catpick-list") || root;
      const lr = list.getBoundingClientRect(), er = el.getBoundingClientRect();
      list.scrollTop += (er.top + er.height / 2) - (lr.top + lr.height / 2);   // put it on the list's midline
      if (passes === 0) {                                     // highlight once; re-centring must not re-announce
        const tf = [...root.querySelectorAll(".tfrow")];
        setAct(tf.indexOf(el) + (root.querySelector(".tfuse") ? 1 : 0));       // the "use what you typed" row is rows[0]
      }
      // RE-CENTRED, not centred once. Every row asks the panel for its own size and sample line and grows
      // when the answer lands, so rows ABOVE the target push it down after the first correction — scrolling
      // a single time leaves it wherever the late layout put it, which for a row far down the list is off
      // screen entirely. Six passes over ~400ms outlast the fetches without pinning the list against the
      // operator's own scrolling for any noticeable time.
      if (++passes < 6) timer = setTimeout(centre, 70); else setReveal(null);
    };
    timer = setTimeout(centre, 0);
    return () => clearTimeout(timer);
  }, [reveal, open, page, q]);

  // ── the two directions of the text view ─────────────────────────────────────────────────────────
  // A LIST HAS NO TEXT FORM, and pretending otherwise would lose it: a `list` badge is an id like `youtube`,
  // which re-read as text classifies as a bare label and is refused. So the textarea holds the TYPED targets
  // only, the list badges stay visible above it, and the round trip is total for everything it does show.
  // EVERY badge, lists included — `badgeText` gives a list its identity string (`list:youtube`), so the
  // textarea holds the whole rule and not the part that happened to be typeable. For targets it is `raw`,
  // not the canonical form: a `site` is stored punycoded, and handing back `xn--d1acpjx3f.xn--p1ai` for a
  // name typed in Cyrillic is not the operator's rule.
  const toText = () => { loadCatalogIndex();   // so `list:` ids can be checked for real by the time they return
    // ⚠️ THE BOX IS PART OF THE RULE TOO. Building the draft from `badges` alone dropped whatever was typed
    // and not yet committed — and worse, a badge CLICKED TO EDIT has already left `badges` and lives only as
    // text in the box, so switching to text view destroyed it outright. Measured: edit `keep.com`, press
    // `</>`, and it is gone from the draft, from the row, and from Escape's reach. Same shape as the
    // all-or-nothing bug in fromText — one half of the truth read as the whole of it.
    //
    // `q` is NOT cleared here: leaving it means Escape returns to exactly the box that was left behind, and
    // fromText clears it on the way in, so a committed draft cannot duplicate it.
    // The edited badge is in the row AND its text is in the box, so it is written ONCE — as whatever the box
    // currently holds, which is the version the operator is working on.
    const typed = q.trim();
    setDraft([...badges.map(b => (editing && b === editing.b) ? typed : badgeText(b)).filter(Boolean),
              ...(!editing && typed ? [typed] : [])].join("\n"));
    setAsText(true); setOpen(false); setEditing(null); setPending({ text: "", forQ: null }); };
  /* ⚠️ THE TEXT VIEW IS A DRAFT, AND THE PARENT HAS TO KNOW. `draft` is local state; the row only learns of
     it when `fromText` commits (the `</>` toggle) — so a sheet whose own Save reads `row.badges` while the
     operator is still in text view saves what was there BEFORE, closes, and reports success. Typed, gone,
     no message. Measured in the custom-list sheet; the interface sheet's Save has the same shape.
     `onLint` (declared since this component was written and never called until now) is that channel: a
     non-empty string means "what you can see is not what would be saved", and the parent blocks on it. */
  /* ⚠️ ONLY WHEN THE VALUE CHANGES. `draft` is a dependency, so this effect runs on every keystroke in the
     text view — and the message it reports is the same string every time. Without the guard each keystroke
     called onLint → setRow → a fresh rows array → a state update on the sheet → a re-render of every rule
     on the interface, to say something the parent already knew. The parent's only interest is the
     transition between "there is unapplied text" and "there is not". */
  const lintSent = useRef("");
  useEffect(() => {
    if (!onLint) return;
    const v = asText && draft.trim()
      ? (pending.text || T("This text hasn't been applied yet — press </> to apply it, or Escape to discard."))
      : "";
    if (v === lintSent.current) return;
    lintSent.current = v;
    onLint(v);
  }, [asText, draft, pending.text]);

  const fromText = () => {
    // THE LINE IS THE UNIT HERE, not the token. `classifyAll` splits on whitespace, which is right for a
    // pasted blob and wrong for a textarea whose whole promise is one target per line: `not a domain!!` came
    // back as three separate refusals — `not`, `a`, `domain!!` — and the operator's own line was gone from
    // the box they were meant to fix it in. So each line is read whole, and only a line that reads cleanly
    // ALL THE WAY THROUGH is split, which keeps a space-separated paste working. Anything else is refused as
    // the line it was written as.
    const good = [], bad = [];
    for (const line of draft.split(/\n/).map(x => x.trim()).filter(Boolean)) {
      const parts = line.split(/[\s,]+/).filter(Boolean).map(t => readToken(t, mode, listEditor));
      if (parts.length && parts.every(r => r && r.b)) good.push(...parts.map(r => r.b));
      else bad.push({ raw: line, why: (parts.find(r => r && r.bad) || {}).why });
    }
    // Rebuilt from the LISTS, not added to what is there: the text is the whole truth about typed targets,
    // so a line deleted in the textarea has to disappear from the row. Lists lead because they are not in
    // the text and have nowhere else to be.
    const { added, overCap, next } = addAll(good, { base: [], defer: true });
    const rest = [...bad.map(x => x.raw), ...overCap].join("\n");
    if (rest) {
      // ALL OR NOTHING, and this is the whole reason the text view is safe to use. Committing the good
      // lines and leaving only the REFUSED ones in the box breaks the one invariant it rests on — that the
      // textarea is the complete truth about this rule's typed targets. Caught doing exactly that: 140
      // patterns against §12.1's cap of 100 committed the first 100 and left 40 lines behind, so the box no
      // longer described the rule, and the next trip through it deleted the 100 it could no longer see.
      // Nothing is applied while anything is unusable; the draft stays whole and says which line is wrong.
      const msg = bad.length
        ? (bad[0].why === "unknown_list" ? (listEditor ? T("A list can't contain another list — add its addresses here instead") : T("No list called {v1} on this panel", { v1: bad[0].raw }))
                                         : T("{v1} was not added", { v1: bad[0].raw }))
        : capSay();
      setSay(msg); setPending({ text: msg, forQ: null });
      return;
    }
    onChange(next);
    setAsText(false); setDraft(""); setQ(""); setPending({ text: "", forQ: null });   // the draft IS the rule now
    setSay(added.length ? T("{v1} in this rule", { v1: plural(added.length, "target") }) : T("Rule emptied."));
  };

  const onKey = e => {
    if (e.key === "Escape") {
      if (editing) { e.stopPropagation();      // the badge never left the row — just stop editing it
        setQ(""); setEditing(null); setOpen(false); setPending({ text: "", forQ: null }); setAct(-1);
        setSay(T("Edit discarded — {v1} is unchanged", { v1: targetLabel(editing.b.kind, editing.b.value) }));
        return; }
      if (open) { e.stopPropagation(); setOpen(false); }
      return; }
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setAct(a => Math.min(a + 1, rows.length - 1)); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); setAct(a => Math.max(a - 1, -1)); return; }
    if (e.key === "Enter") {
      e.preventDefault();
      if (activeRow && activeRow.k === "list") { const id = activeRow.it.id;   // same toggle the click does
        if (has(id)) removeList(id); else if (listGate(mode, id, node).ok) commitList(id);
        return; }
      if (readList) { if (readList.ok) commitList(readList.id);
        else { const m = T("No list called {v1} on this panel", { v1: q.trim() }); setSay(m); setPending({ text: m, forQ: q }); }
        return; }
      if (readGate && readGate.ok) commitTyped();
      return;
    }
    // `,`, SPACE and Tab all commit what is typed. Space was deliberately excluded here — "pasting prose
    // would become noisy and nothing is unreachable without it (§12.3)" — and that was REVERSED on request
    // after using it: every other chip field on the web commits on space, and the reason it was left out
    // does not survive contact with this one. Pasting is not affected either way: `onPaste` intercepts any
    // clipboard text containing whitespace and splits it itself, so a paste never arrives here a key at a
    // time. And no target this field accepts can contain a space — a hostname, an IP/CIDR and an AS number
    // are all space-free — so swallowing the key costs nothing that could otherwise be typed.
    if (e.key === "," || e.key === " " || (e.key === "Tab" && q.trim() && readGate && readGate.ok)) {
      if (e.key === " " && !q.trim()) return;                 // a lone space in an empty box is not a commit
      e.preventDefault(); commitTyped(); return; }
    if (e.key === "Backspace" && !q && badges.length) { e.preventDefault(); edit(badges.length - 1); }
  };
  const onPaste = e => {
    const txt = (e.clipboardData || {}).getData ? e.clipboardData.getData("text") : "";
    if (!txt || !/[\s,]/.test(txt.trim())) return;                    // a single token: let it type normally
    e.preventDefault();
    // Same reader as the box and the textarea: paste a rule copied out as text and it lands as badges,
    // `list:` lines included. Which format you get is the format you paste INTO, not the one you copied from.
    const parts = txt.split(/[\s,]+/).filter(Boolean).map(t => ({ tok: t, r: readToken(t, mode, listEditor) }));
    const good = parts.filter(x => x.r && x.r.b).map(x => x.r.b);
    const bad = parts.filter(x => !(x.r && x.r.b)).map(x => ({ raw: x.tok }));
    const { added, overCap } = addAll(good);
    const rest = [...bad.map(b => b.raw), ...overCap].join(" ");
    setQ(rest);
    const msg = overCap.length ? capSay()
      : T("{v1} added, {v2} left to fix", { v1: added.length, v2: bad.length });
    setSay(msg);
    setPending({ text: rest ? msg : "", forQ: rest });      // only while something actually stayed behind
  };

  // SEVERAL TOKENS IN THE BOX — which is exactly when `reading`, a ONE-token classification of the whole
  // string, stops being a reading and becomes a MISREADING. Three refused substrings read back as
  // `*a* *b* *c*` classify as `star_mid`, and the operator was told their stars were in the wrong place when
  // every one of them was fine and the budget was the only reason any of them bounced.
  //
  // So the foot shows `pending` here and NOTHING otherwise: a one-token verdict on a many-token string is
  // false however sure it sounds, and silence is the honest fallback. Below one token it is the opposite —
  // a single leftover gets its own lint, which names the actual problem and beats any summary.
  // Same `[\s,]` split the paste path decides on, so the two cannot disagree about what "several" means.
  const leftovers = /[\s,]/.test((q || "").trim());

  // The cost meter (§3.4). An estimate, and labelled as one: list sizes are what the panel resolved, a typed
  // name is one name, an AS number is however many prefixes it announced when the hint last asked.
  const meter = (() => {
    let names = 0, nets = 0;
    for (const b of badges) {
      if (b.t === "list") { const s = listSizeNow(b.id); if (s && !s.err) { names += s.host || 0; nets += s.ip || 0; } continue; }
      if (b.kind === "ip") nets += 1;
      else if (b.kind === "asn") nets += asnNets(b.value);
      else names += 1;
    }
    // plural(), not "n + word": Russian picks between three forms and the rule is not derivable from English.
    const bits = [plural(badges.length, "entry")];
    if (names) bits.push(plural(names, "name").replace(String(names), fmtCount(names)));
    if (nets) bits.push(plural(nets, "network").replace(String(nets), fmtCount(nets)));
    return bits.join(" · ");
  })();

  const shown = expand ? badges : badges.slice(0, BADGE_CAP);
  const hidden = badges.length - shown.length;
  // THE FIX BUTTON, IN ONE PLACE — because it is rendered from two rows and BOTH were unusable with a mouse,
  // in two different ways, and a second copy is how one of them gets repaired and the other does not.
  //
  // ⚠️ IT MUST CLOSE THE DROPDOWN. `onSwitchMode` opens a confirm on the global overlay (z-index 50) and this
  // popover is a Portal at z-index 90, deliberately above the sheet so the field can escape it. Nothing closed
  // the popover, so the confirm opened UNDERNEATH it and `elementFromPoint` over its "Switch mode" button
  // returned this row: the dialog was visible, looked live, and swallowed every click. Measured on a live
  // panel, not reasoned about. Closing here is the local fix — raising the overlay instead would put every
  // confirm above every in-sheet popover, which is the stacking this z-order exists to produce.
  const fixBtn = g => g.fix && onSwitchMode
    ? html` <button type="button" class="linkbtn" onClick=${e => { e.stopPropagation(); setOpen(false); onSwitchMode(g.fix); }}>${T("Switch this node to {v1}", { v1: (MODE_META[g.fix] || {}).label || g.fix })}</button>`
    : null;
  // A TICKED ROW TOGGLES OFF. The row draws a ✓ when the list is already in this rule, which reads as a
  // checkbox — and clicking it called `commitList`, which finds the badge already there and answers "Already
  // in this rule." So the tick could be turned on and never off from the place that turns it on, and the
  // only way back was the badge's own ×. Removal ignores the gate on purpose: a list this node can no longer
  // run still has a badge, and taking something out is always safe.
  const listRow = it => { const g = listGate(mode, it.id, node), added = has(it.id), i = rows.findIndex(r => r.it === it);
    // `i >= 0` because BOTH sides can be −1: findIndex misses return −1, and −1 is also "nothing highlighted".
    // Left as a bare `i === act` those two agree, and every row the lookup failed on draws itself as selected.
    return html`<div class=${"tfrow" + (i >= 0 && i === act ? " act" : "")} key=${it.id} data-lid=${it.id} onMouseEnter=${() => setAct(i)}>
      <${CatalogRow} it=${it} added=${added} onPick=${() => (added ? removeList(it.id) : g.ok && commitList(it.id))}/>
      ${!g.ok ? html`<div class="tfrow-why">${gateReason(g, modeLabel)}${fixBtn(g)}</div>` : null}
    </div>`; };
  let lastGrp = null;

  /* WHERE THE TOGGLE LIVES DEPENDS ON WHETHER THERE IS A RAIL. In a rule row it sits in the grip column,
     beside the drag handle, because it is a control ON the field rather than a fact ABOUT it. The
     custom-list sheet has no row and therefore no grip — so that same absolute offset put it outside the
     modal's content entirely, floating in the margin. There it goes in the foot, labelled and right-aligned,
     which is also the only place a label fits. Brand-coloured rather than faint: in the rail it is one of
     several controls and stays quiet; on its own it is the only way to reach the text view, so it has to
     read as a control at all. */
  const vtog = (on) => listEditor
    ? html`<button type="button" class=${"tf-vtog inline" + (on ? " on" : "")} aria-pressed=${on ? "true" : "false"}
        title=${on ? T("Back to badges — reads every line and turns it into a target. Escape discards instead.")
                   : T("Show as text — copy it out, paste it in, or edit every target at once")}
        onClick=${on ? fromText : toText}><${Ic} i="code"/><span>${on ? T("Show badges") : T("Show text")}</span></button>`
    : html`<button type="button" class=${"tf-vtog" + (on ? " on" : "")} aria-pressed=${on ? "true" : "false"}
        title=${on ? T("Back to badges — reads every line and turns it into a target. Escape discards instead.")
                   : T("Show as text — copy it out, paste it in, or edit every target at once")}
        onClick=${on ? fromText : toText}><${Ic} i="code"/></button>`;

  if (asText) return html`<div class="tfield" ref=${ref}>
    ${/* IN THE RAIL, not the foot. It belongs beside the drag grip because it is a control ON the field
          rather than a fact ABOUT it, and the foot is where the facts are — the entry count, the reading of
          what is typed, the destination. Absolutely placed into the row's grip column: the state it toggles
          lives here, so lifting it into the row would have meant lifting `asText` with it. */""}
    ${listEditor ? null : vtog(true)}
    ${/* ESCAPE ABANDONS THE DRAFT, exactly as it abandons a badge edit. Without it the only way out of text
          view was to make every line valid — an operator who pasted the wrong file, or who opened the view
          just to copy from it, would have had to repair text they never meant to keep. */""}
    <textarea class="tf-text" spellcheck="false" autocomplete="off" autocorrect="off" data-enter="self" data-noautofocus="1"
      aria-label=${T("Targets, one per line")} placeholder=${T("One target per line — example.com, *.ru, 10.0.0.0/8, AS13335")}
      value=${draft} onInput=${e => setDraft(e.target.value)}
      onKeyDown=${e => { if (e.key !== "Escape") return; e.stopPropagation(); e.preventDefault();
        setAsText(false); setDraft(""); setPending({ text: "", forQ: null });
        setSay(T("Text discarded — the rule is unchanged.")); }}
      ref=${el => { if (el && !el._tf) { el._tf = 1; requestAnimationFrame(() => { try { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } catch {} }); } }}/>
    <div class="tf-foot">
      <span class="tf-lstart">${leading ? html`<span class="tf-lead">${leading}</span>` : null}
        <span class="tf-say">${plural(draft.split(/\n/).filter(x => x.trim()).length, "line")}</span></span>
      ${pending.text ? html`<span class="tf-lint err">${pending.text}</span>` : null}
      ${listEditor ? html`<span class="grow"></span>${vtog(true)}` : null}
      ${trailing ? html`<span class="tf-trail">${trailing}</span>` : null}
    </div>
    <span class="tf-live" aria-live="polite">${say}</span>
  </div>`;

  return html`<div class="tfield" ref=${ref}>
    ${/* Badges cannot be selected, so without this a rule can be built and never read back out. */""}
    ${listEditor ? null : vtog(false)}
    <div class="tf-box" onClick=${() => inRef.current && inRef.current.focus()}>
      ${shown.map((b, i) => html`<${Badge} key=${badgeIdentity(b) + i} b=${b} gate=${badgeGate(mode, node, b)} node=${node} modeLabel=${modeLabel}
        editing=${!!(editing && editing.b === b)}
        onRemove=${() => remove(i)} onEdit=${() => edit(i)} onFix=${onSwitchMode} onRetry=${() => bump(x => x + 1)}
        onReveal=${revealList}/>`)}
      ${hidden > 0 ? html`<button type="button" class="tf-more" onClick=${() => setExpand(true)}>${T("+{v1} more", { v1: hidden })}</button>` : null}
      ${expand && badges.length > BADGE_CAP ? html`<button type="button" class="tf-more" onClick=${() => setExpand(false)}>${T("show fewer")}</button>` : null}
      ${/* While the dropdown is open, Enter and Escape belong to the FIELD: Enter commits the highlighted row
            and Escape closes the dropdown. Without this the Sheet's own handler treats Enter as "press the
            primary button", so committing a badge also saved the whole interface — which it duly did, twice,
            while this was being tested. Closed, both go back to the sheet, so a second Escape still closes it. */""}
      <input ref=${inRef} class=${"tf-in" + (reading && reading.kind === "invalid" ? " bad" : "")} type="text" spellcheck="false" autocomplete="off"
        data-enter=${open ? "self" : null} data-noautofocus="1"
        role="combobox" aria-expanded=${open ? "true" : "false"} aria-autocomplete="list"
        placeholder=${badges.length ? T("add another…")
          : listEditor ? T("Address, IP range, AS number or pattern…")
          : T("Search a service, or type an address, IP range or AS number…")}
        value=${q} onInput=${e => { setQ(e.target.value); setPage(0); setAct(-1); setOpen(true); }}
        onFocus=${() => setOpen(true)} onKeyDown=${onKey} onPaste=${onPaste}/>
    </div>
    <div class="tf-foot">
      ${/* THE × AND THE COUNT ARE ONE ITEM. Anchoring the × to the foot's top could not line it up: the foot
            is baseline-aligned and the destination select is the tallest thing on the line, so the count
            sits 11px below the top and the × floated above it. Paired in a flex box they align to each
            OTHER by construction — no offset to keep in step with the select's height. */""}
      <span class="tf-lstart">${leading ? html`<span class="tf-lead">${leading}</span>` : null}
        ${badges.length ? html`<span class="tf-meter" title=${T("An estimate from what the panel has resolved so far. The node's own report is the authority once it syncs.")}>${meter}</span>` : null}</span>
${/* The reading and its consequence live in the dropdown's "use what you typed" row while that row exists —
       saying the same sentence here at the same time is just noise. What is left for this line is what has no
       row of its own: a token that parses as nothing, and the empty-row invitation. */""}
      ${leftovers ? (pending.text && pending.forQ === q
            ? html`<span class="tf-lint err">${pending.text}</span>` : null)
        : (listEditor && listTok) ? html`<span class="tf-lint err">${T("A list can't contain another list — add its addresses here instead")}</span>`
        : readList && !readList.ok ? html`<span class="tf-lint err">${T("No list called {v1} on this panel", { v1: q.trim() })}</span>`
        : reading && reading.kind === "invalid" ? html`<span class="tf-lint err">${targetWhy(reading.why, q)}</span>`
        : reading ? (open ? null : html`<span class="tf-say">${readGate && readGate.ok ? targetSentence(reading.kind, reading.value) : gateReason(readGate || {}, modeLabel)}</span>`)
        : !badges.length ? html`<span class="tf-say">${listEditor ? T("Type an address, IP range, AS number or pattern.")
              : Trich("Try a service name like *YouTube*, or type an address, IP range or AS number.")}</span>` : null}
      ${listEditor ? html`<span class="grow"></span>${vtog(false)}` : null}
      ${trailing ? html`<span class="tf-trail">${trailing}</span>` : null}
    </div>
    <span class="tf-live" aria-live="polite">${say}</span>
    ${/* IN A CUSTOM LIST THE POPOVER IS ONLY EVER THE "use what you typed" ROW, so it opens only when that
          row exists. Empty, it was a box whose entire content repeated the placeholder directly above it —
          chrome reporting that it has nothing to report. The reading it would have shown is not lost: the
          foot already prints it whenever the dropdown is closed. */""}
    ${open && pos && (!listEditor || rows.length) ? html`<${Portal}><div ref=${popRef} class=${"catpick-pop wide tfpop" + (pos.flip ? " flip" : "")}
        style=${"left:" + pos.left + "px;top:" + pos.top + "px;width:" + pos.width + "px;--catpick-maxh:" + (pos.maxh - 90) + "px"}>
      <div class="catpick-list">
${/* A DISABLED <button> DOES NOT DELIVER CLICKS TO ITS CHILDREN, so the "Switch this node to…" control that
       used to live inside this row was dead to a real mouse — and it is rendered ONLY when `readGate.ok` is
       false, which is exactly when the row is disabled, so it was dead every single time it appeared. Script
       clicks fired it (that is how it was isolated: dispatchEvent worked, a real click did nothing), which is
       also why no automated check would have caught it.
       So the row is a BUTTON only while it is actually actionable, and a DIV once it is not. The classes are
       unchanged, so `.tfuse.off` still dims it and `cursor:not-allowed` still says it cannot be used — what
       changes is that the one control inside it that IS meant to be used can now be clicked. */""}
        ${readList ? html`<div class="catpick-grp">${T("Use what you typed")}</div>
          <${readList.ok ? "button" : "div"} type=${readList.ok ? "button" : null} class=${"tfuse" + (act <= 0 ? " act" : "") + (readList.ok ? "" : " off")}
            onMouseEnter=${() => setAct(0)} onClick=${readList.ok ? () => commitList(readList.id) : null}>
            <span class="tfbadge list"><span class="tfb-lbl">${readList.ok ? catLabelOf(readList.id) : readList.id}</span></span>
            <span class="tfuse-say">${readList.ok ? T("Add this list to the rule") : T("No list called {v1} on this panel", { v1: q.trim() })}</span>
          <//>` : null}
        ${reading && reading.kind !== "invalid" ? html`<div class="catpick-grp">${T("Use what you typed")}</div>
          <${readGate.ok ? "button" : "div"} type=${readGate.ok ? "button" : null} class=${"tfuse" + (act <= 0 ? " act" : "") + (readGate.ok ? "" : " off")}
            onMouseEnter=${() => setAct(0)} onClick=${readGate.ok ? () => commitTyped() : null}>
            <span class=${"tfbadge tgt" + (KIND_WIDE[reading.kind] ? " wide" : "")}><span class="tfb-lbl">${targetLabel(reading.kind, reading.value)}</span>
              ${/* `kind`, not `host`: this chip carries the KIND, and `capb host` is the tier chip whose legend
                     two screens over reads "matched by domain name — needs Force-DNS or Hybrid-SNI". An `ip`
                     target is not wide, so it took that class and wore the host-tier colour while its own text
                     said IP. The committed badge below has always used `kind`; this is the preview catching up. */""}
              <span class=${"capb " + (KIND_WIDE[reading.kind] ? "wide" : "kind")}>${KIND_LABEL()[reading.kind]}</span></span>
            <span class="tfuse-say">${readGate.ok
              ? targetSentence(reading.kind, reading.value) + opTooLongNote(node, reading.kind, reading.value)
              : gateReason(readGate, modeLabel)}</span>
            ${!readGate.ok ? fixBtn(readGate) : null}
          <//>` : null}
        ${rows.filter(r => r.k === "list").map(r => { const head = r.grp !== lastGrp ? (lastGrp = r.grp) : null;
          return html`<${Fragment}>${head ? html`<div class="catpick-grp">${head}</div>` : null}${listRow(r.it)}<//>`; })}
        ${/* A STAR MEANS THEY ARE WRITING A PATTERN, NOT SEARCHING. No list is called `*.ru`, so "No list
              matches “*.ru”." is a true sentence about a question nobody asked — and it sat directly under
              the "Use what you typed" row that had already answered them, which made the field read as
              though it had rejected the rule it was in fact offering to create. The same is arguably true
              of an IP or an AS number, which can no more be a list name; left alone deliberately, because
              a plain domain like `youtube.com` IS worth searching the catalog for and the line between
              those two is the star, not "does it classify". */""}
        ${/* All three report on a CATALOG SEARCH. A custom list has no catalog, so "nothing matches" is an
              answer to a question nobody asked — and the operator reads it as their own address being
              rejected, which is the opposite of what it means. */""}
        ${!listEditor && ql.length >= 2 && !q.includes("*") && !_cat.length && cidx ? html`<div class="catpick-empty">${T("No list matches “{q}”.", { q })}</div>` : null}
        ${!listEditor && ql.length === 1 ? html`<div class="catpick-empty">${T("Keep typing to search the provider catalog.")}</div>` : null}
        ${!listEditor && !rows.length && !ql ? html`<div class="catpick-empty">${T("Type a service name, an address, an IP range or an AS number.")}</div>` : null}
      </div>
      ${_cat.length > per ? html`<div class="catpick-foot">
        <span class="catpick-count">${page * per + 1}–${Math.min(_cat.length, (page + 1) * per)} of ${_cat.length}</span><span class="grow"></span>
        <div class="catpick-nav">
          <button type="button" class="btn btn-mini" disabled=${page === 0} onClick=${() => { setPage(p => Math.max(0, p - 1)); setAct(-1); }}>${T("‹ Prev")}</button>
          <button type="button" class="btn btn-mini" disabled=${page >= pages - 1} onClick=${() => { setPage(p => Math.min(pages - 1, p + 1)); setAct(-1); }}>${T("Next ›")}</button>
        </div></div>` : null}
    </div><//>` : null}
  </div>`;
}

// One smart-routing rule ROW: many things → one destination (exit node / direct / block). Reuses the
// drag-reorder hook. Order builds the node's chain, so it settles ties between rules naming the SAME target
// and it is the whole story on Kernel-SNI — but it does not decide an overlap between two DIFFERENT targets:
// swg-sni and dnsmasq both answer that by specificity (measured, plan §10.4x), which is what the label over
// the list now says and what the `takenBy` lint below points at where the two disagree.
export function RoutingRules({ node, rows, catchAll, onChange }) {
  const others = (Store.nodes || []).filter(n => n.id !== node);
  const _nrec = (Store.nodes || []).find(n => n.id === node);
  // what "the node default" resolves to here, if the node has one — see `catchVal`
  const _dflt = ((_nrec || {}).exits || []).find(x => String(x.id) === String((_nrec || {}).default_exit || "")) || null;
  const exits = (_nrec || {}).exits || [];
  // "" means the node record has not loaded. Kept distinct from "kernel" on purpose: a badge greyed because
  // we could not look up the engine is a lie about the configuration (§4.2).
  const _mode = _nrec ? (_nrec.routing_mode || "kernel") : "";
  const dispRows = rows || [];
  const emit = (rs, ca) => onChange(rs, ca === undefined ? catchAll : ca);
  const rs = useReorder(dispRows.map(r => r._gid), ids => emit(ids.map(id => dispRows.find(r => r._gid === id)).filter(Boolean)), "y", { container: ".rrlist", card: ".rrrow" });
  const setRow = (gid, patch) => emit(dispRows.map(r => r._gid === gid ? { ...r, ...patch } : r));
  const addRow = () => emit([...dispRows, { _gid: newGid(), enabled: true, badges: [], action: others[0] ? "exit" : "direct", node: (others[0] || {}).id || "" }]);
  const destVal = r => r.action === "exit" ? "exit|" + (r.node || "")
    : r.action === "dev" ? "dev|" + (r.exit_id || "") : r.action;
  const onDest = (gid, v) => setRow(gid, destPatch(v));
  // ⚠️ ONE FUNCTION, BOTH CONTROLS. The row's destination and the catch-all's used to build their patch
  // separately from the same `split("|")`, and they had already drifted — the catch-all listed its options
  // in a different order and could not name an exit at all. A destination is one grammar; it gets one
  // reader, and a kind added here reaches both places or neither.
  const destPatch = v => { const [a, x] = v.split("|");
    return a === "exit" ? { action: "exit", node: x, exit_id: "" }
      : a === "dev" ? { action: "dev", exit_id: x, node: "" }
      : { action: a, node: "", exit_id: "" }; };
  // THE SAME LIST THE INTERFACE'S OWN EGRESS PICKER USES, from the same builder, minus the smart-cascade
  // entry — a rule IS the smart cascade, so offering it inside one would be a rule that routes to itself.
  // The two are the same decision asked at two scopes ("where does this leave by"), so they read the same
  // way round and use the same words; an operator who has learned one has learned the other.
  // ⚠️ NO ROW CONTROLS, BUT THE CANDIDATE DEVICES ARE HERE. Switching an exit off or deleting it is
  // node-wide and a rule row is the wrong place to do it, so this takes none of those controls — only the
  // grouping, the names and the health. It DOES offer the devices the node reports: a list that omitted
  // them made the same device appear in one picker and not the next, and the record a reference needs is
  // minted server-side on the save (`_mint_device_exit`), not by whichever screen happens to be open.
  /* Is the value this control is holding something the list above can name? Answered from the SAME two
     sources the list is built from, so it cannot disagree with it. `dev|` is included for completeness —
     `prune_exit_refs` rewrites references to a deleted EXIT, so that half should never dangle, and a guard
     that only covers the half you remembered is how the other one gets found in production. */
  const goneDest = v => {
    const [a, x] = String(v || "").split("|");
    if (a === "exit" && x && !others.some(n => n.id === x))
      return { value: v, label: T("A node that is no longer here"),
               why: T("This rule forwards to a node that is not in this panel any more, so it routes nothing and traffic takes the next matching rule instead. Choose another destination, or delete the rule.") };
    // ⚠️ `exits`, NOT `_nrec.exits`. `_nrec` is a `.find()` and can be undefined — every other line in this
    // function says `(_nrec || {})` for that reason — so this threw `Cannot read properties of undefined`
    // and took the WHOLE RoutingRules render down whenever the control held a `dev|…` value and the node
    // record was not in the store: a node deleted while its sheet is open, or any render that lands before
    // /api/state has populated Store.nodes. A blank dropdown is a bug; a blank screen is worse than the bug.
    if (a === "dev" && x && !(exits.some(e => String(e.id) === x)))
      return { value: v, label: T("An exit that is no longer here"),
               why: T("This rule leaves by an exit that is not on this node any more, so it routes nothing and traffic takes the next matching rule instead. Choose another destination, or delete the rule.") };
    return null;
  };
  const destOpts = (withDefault, held) => { const _gone = goneDest(held); return [
    ...(withDefault && _dflt ? [{ value: "__dflt__",
      label: T("Node default ({v1})", { v1: _dflt.label || _dflt.device || _dflt.id }) }] : []),
    { value: "direct", label: T("Direct (this node)") },
    ...exitOptionGroups(_nrec, { prefix: "dev|", devices: true }),
    ...(others.length ? [{ group: T("Forward to node (cascade)"),
                           items: others.map(n => ({ value: "exit|" + n.id, label: T("Forward to {node}", { node: n.name }) })) }] : []),
    // LAST, and outside every group. Block is not a place traffic goes, it is traffic not going — so it
    // sits apart from the lists of destinations rather than reading as one more of them.
    { value: "block", label: T("Block") },
    // ⚠️ …AND THE DESTINATION THAT IS GONE, if this control is holding one. A rule can name a node that has
    // since been removed from the panel; that node is not in `others`, so no option carried its value and
    // the control rendered COMPLETELY BLANK — indistinguishable from "nothing chosen yet", while a real
    // choice sat in the store and `cascade_plan` dropped it (`if not P or P not in nodes: continue`).
    // Measured on the live fleet: svo-im/awg0's catch-all is `all -> exit via 0138f33f65c3`, a node id that
    // is not in nodes.json, and the row read `Everything else  →  [    ]` while every packet left by the
    // node's default instead. This is the rule `exitOptionGroups` already states for the picker one scope
    // up — "a stored selection that has since broken must stay visible and nameable" — reached from the
    // other side, and it is the same reason: a blank is not a report.
    ...(_gone ? [{ value: _gone.value, label: _gone.label, className: "bad", refuse: _gone.why }] : []),
  ]; };
  // A rule this node's engine can't run is a dead end unless the operator can leave it — so every gate that
  // names a mode also offers the switch. Generalised from the old Force-DNS-only affordance: the field's
  // capability table names whichever engine would run the badge, and this reprovisions the node into it.
  const switchMode = target => { const mm = MODE_META[target] || {};
    openConfirm({ title: T("Switch {v1} to {v2}?", { v1: _nrec ? _nrec.name : T("this node"), v2: mm.label || target }), warn: true,
      confirmLabel: T("Switch mode"),
      body: T("This reprovisions the node so it can match by hostname. IP rules keep working, and the rule changes you have open stay open — save them afterwards."),
      onConfirm: async () => {
        const r = await api.nodeUpdate({ id: node, routing_mode: target });
        if (!r || !r.ok) return toast(srvText(r) || T("Couldn't switch mode"), "err");
        await Store.poll();
        toast(T("Switched to {v1} — save to apply your rules.", { v1: mm.label || target }), "ok");
      } });
  };
  // ⚠️ "NOTHING SAID" IS ITS OWN ANSWER, and it used to be spelled the same as "direct". No stored rule
  // meant the control DISPLAYED "Direct (this node)" — a value nobody had chosen — and the panel routed the
  // remainder out the node's own address even on a node whose stated default was an exit. Now silence is
  // `__dflt__`, which names what it resolves to, and someone who genuinely wants direct says so and gets a
  // stored rule. Only offered where there is a default to name: with none, silence and direct really are
  // the same thing and a second entry saying so would be a choice without a difference.
  const catchVal = !catchAll ? (_dflt ? "__dflt__" : "direct")
    : catchAll.action === "exit" ? "exit|" + (catchAll.node || "")
    : catchAll.action === "dev" ? "dev|" + (catchAll.exit_id || "") : catchAll.action;
  const setCatch = v => {
    if (v === "__dflt__") return emit(dispRows, null);          // silence — the node's default applies
    const p = destPatch(v);
    // A destination that names nothing (an exit or node id that is gone) falls back to silence too, rather
    // than storing a rule that routes to a blank.
    emit(dispRows, (p.action === "exit" && p.node) || (p.action === "dev" && p.exit_id)
      || p.action === "block" || p.action === "direct"
      ? { enabled: true, category: "all", ...p } : null); };
  // The SAME badge in a later row can never fire, and that holds under specificity too — it is one operand,
  // so both rules resolve to one key and the chain takes the earlier. (This is the one place row order really
  // is the answer, which is why this check survived the label change unaltered.) Per badge, not per row: one
  // row of fifteen services shadowing one entry of the next is what the old per-rule check couldn't see.
  const seenB = {};
  // §12.1's budget is the INTERFACE's, so it is counted here — the one place that holds every row — and each
  // field is told what the OTHER rows have already spent. A field counting only itself would let ten rows of
  // a hundred through, which is the scan this cap exists to prevent.
  const tier2All = tier2Count(dispRows, customListOf);   // rulerows knows the grammar; the Store lookup is ours
  return html`<div class="field"><label>${T("Routing rules")} <span class="faint" style="text-transform:none;letter-spacing:0">${(MODE_META[_mode] || {}).winsLabel || ""}</span></label>
    <div class="rrlist" ...${rs.container()}>${dispRows.map((row, ri) => {
      const badges = row.badges || [];
      const dupes = [];
      for (const b of badges) { const k = badgeIdentity(b); if (seenB[k]) dupes.push(b); seenB[k] = true; }
      // ROW ORDER AND SPECIFICITY DISAGREE HERE — the one case the operator cannot see and cannot fix by
      // dragging. The engines answer an overlap by SPECIFICITY (swg-sni's kind ladder then longest operand;
      // dnsmasq's longest matching key on Force-DNS, measured — plan §10.4x), so a broad rule placed ABOVE
      // a narrower one still loses that narrower one's hosts. Below-only on purpose: a narrower rule placed
      // above is the arrangement that reads correctly anyway, and warning there would fire on every list of
      // a zone plus its exceptions. Different destination only — two rules sending the same hosts to the
      // same place is not something anyone needs told.
      const takenBy = [];
      for (const lower of dispRows.slice(ri + 1)) {
        if (destVal(lower) === destVal(row)) continue;
        for (const nb of lower.badges || [])
          if (badges.some(b => badgeCovers(b, nb)) && !takenBy.some(x => badgeIdentity(x) === badgeIdentity(nb)))
            takenBy.push(nb);
      }
      const self = row.action === "exit" && row.node === node;
      const inert = badges.filter(b => !badgeGate(_mode, node, b).ok);
      const asns = badges.filter(b => b.t === "target" && b.kind === "asn").map(b => b.raw).join(", ");
      const it = rs.item(row._gid);
      return html`<div key=${row._gid} class=${"rrrow rrrow-b" + it.cls + ((dupes.length || self || inert.length || takenBy.length || row.locked) ? " warn" : "")} data-rid=${it.rid}>
        <span class="drag-grip" title=${T("Drag to reorder")} ...${rs.grip(row._gid)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span>
        ${/* Built once and handed to BOTH branches: the destination now rides in the field's foot (see
              TargetField's `trailing`), and a locked row has to carry the identical control or the two
              shapes of row would stop lining up with each other down the list. */""}
        ${/* NO `rrarrow` HERE. The exit options are themselves written "→ nixos", so the row read
              "→  → nixos" — two arrows for one destination. The catch-all below keeps its arrow: there it
              is the only one, and it is what joins "Everything else" to the control. */""}
        ${(() => { const dest = html`<span class="rrdest" title=${row.locked ? T("Stored as written — this rule is kept exactly as it is.") : ""}>
            <${Dropdown} disabled=${!!row.locked} value=${destVal(row)}
              onChange=${v => onDest(row._gid, v)} options=${destOpts(false, destVal(row))}/>
          </span>`;
          /* ASKED FIRST — but only when there is something to lose. A row still being built (no targets
             yet) goes with one click, because confirming the removal of an empty thing teaches the operator
             to click through the dialog without reading it, which is how the confirm that MATTERS stops
             working. The body says the removal is local until Save, which is true and is the fact that
             decides whether to worry.
             LEADING, not trailing: it is the row's destructive control, and it sits at the far left of the
             foot rather than beside the destination, where it was one careless click from the dropdown. */
          const removeBtn = html`<button class="xbtn" title=${T("Remove rule")} onClick=${() => {
            const n = (row.badges || []).length;
            const drop = () => emit(dispRows.filter(x => x._gid !== row._gid));
            if (!n) return drop();
            openConfirm({ title: T("Remove rule"), confirmLabel: T("Remove"), danger: true,
              body: T("This rule routes {v1}. Removing it here is not written to the node until you save the interface.", { v1: plural(n, "target") }),
              onConfirm: drop });
          }}><${Ic} i="x"/></button>`;
          return row.locked
          ? html`<div class="tfield locked"><div class="tf-box">${badges.map((b, i) => html`<span key=${i} class="tfbadge tgt inert"><span class="tfb-g" aria-hidden="true">⊘</span>
              <span class="tfb-main"><span class="tfb-lbl">${targetLabel(b.kind, b.value)}</span><span class="capb wide">${KIND_LABEL()[b.kind] || T("kind|zone")}</span></span></span>`)}</div>
            <div class="tf-foot"><span class="tf-lead">${removeBtn}</span><span class="tf-lint" title=${T("Nothing on any node has ever read a stored TLD rule. It is kept exactly as written until the migration converts it.")}>${T("A legacy TLD rule — kept as written, and it has never routed anything.")}</span>
              <span class="tf-trail">${dest}</span></div></div>`
          : html`<${TargetField} row=${row} mode=${_mode} node=${node} onSwitchMode=${switchMode}
              ${/* The draft is written INTO THE ROW so that egressSaveBlock sees it — and egressSaveBlock is what
                    all four save buttons already ask (both interface sheets, the WDTT one and the csqtt
                    one). A new prop threaded up through EgressPicker would have had to be wired into each
                    of them separately, and the one that got missed is the one that loses the text.
                    `_draft` never reaches the wire: dirtiness and the payload are both built from
                    egressBody(), which is rowsToRules() — transient row fields are not in it. */""}
              onLint=${msg => setRow(row._gid, { _draft: msg || undefined })}
              tier2All=${tier2All} trailing=${dest} leading=${removeBtn}
              onChange=${bs => setRow(row._gid, { badges: bs })}/>`; })()}
        ${self ? html`<span class="rrlint">${T("can't exit via itself")}</span>`
          : dupes.length ? html`<span class="rrlint">${T("already sent somewhere else above: {toks}", { toks: dupes.slice(0, 3).map(b => b.t === "list" ? catLabelOf(b.id) : targetLabel(b.kind, b.value)).join(", ") + (dupes.length > 3 ? "…" : "") })}</span>`
          : takenBy.length ? html`<span class="rrlint">${T("a more specific rule below wins these hosts: {toks}", { toks: takenBy.slice(0, 3).map(b => targetLabel(b.kind, b.value)).join(", ") + (takenBy.length > 3 ? "…" : "") })}</span>` : null}
        ${asns ? html`<${AsnHint} targets=${asns}/>` : null}
      </div>`;
    })}</div>
    <div class="rrfoot">
      <span class="rrfoot-lead"><button class="btn btn-mini" onClick=${addRow}><${Ic} i="plus"/> ${T("Add rule")}</button><b class="rrfoot-label">${T("Everything else")}</b></span>
      ${/* THE SAME WRAPPER THE RULE ROWS USE, not a second set of numbers that happen to line up. The
            catch-all's arrow, dropdown and trailing button have to sit under the rule rows' own — and once
            the destination moved into the field's foot, matching that by hand meant guessing a width. One
            class, one rule, both places. */""}
      <span class="tf-trail">
        <span class="rrarrow">→</span>
        <span class="rrdest rrcatch"><${Dropdown} value=${catchVal}
          onChange=${setCatch} options=${destOpts(true, catchVal)}/></span>
        ${/* NO GEAR. It linked to Settings ▸ Routing lists, which is where lists are PINNED and inspected —
              but every rule that names one is written right here, so the shortcut mostly offered a detour
              from the screen the operator was already on. The link survives where it is actually needed:
              the empty blocking state still offers it, in a sentence that says what it is for. */""}
      </span>
    </div>
    ${dispRows.length || catchAll ? null : html`<div class="hint">${Trich("No rules yet. Add a rule to send some destinations through another node, or set *Everything else* to channel everything.")}</div>`}
  </div>`;
}

/* ⚠️ DON'T WRITE A TARGET VALIDATOR HERE. A private one lived at this spot — `validTarget`, `isIpTarget`,
   `domainTargets` and three regexes — and it drifted from the classifier it was mirroring (it called
   `x.com.` invalid; the classifier strips the trailing dot on purpose). `.campaign/classify-audit.mjs`
   gates three readers of that grammar and could never see a fourth one living here. Ask js/classify.js. */
// Live feedback for AS<n> tokens in a rule/list: shows "AS62041 → 5 prefixes" (or "not found") so the operator knows
// the ASN resolved. Counts are cached module-wide (keyed by AS number) so switching rows never re-fetches.
const _asnCache = {};
/* ⚠️ TWO COMPONENTS READ THIS CACHE, and only one of them was ever told the answer had arrived.
   `AsnHint` forced its own re-render; the rule's SIZE METER (in TargetField, a sibling above it) counts an
   AS badge's prefixes into "N networks" and read whatever happened to be in here at the time. Measured on a
   live panel: the meter said «10 записей · 7 имён · 1 сеть» with «AS13335 → 877 префиксов» rendered two
   lines below it, and only corrected on an unrelated re-render, when it jumped to 878 — so the operator's
   two readings of the same rule disagreed until they touched something else.
   One fetch, one subscriber list: every reader learns at the same moment, and a second reader added later
   gets it for free instead of re-finding this. */
const _asnSubs = new Set();
/** THE cache key for an AS, from any shape any reader holds. `classify` normalises `AS:013335` to the value
 *  `as13335` (it runs the digits through Number), so a reader keying off the classified BADGE and a reader
 *  keying off the RAW text disagreed on a leading zero: the hint fetched and cached `013335` while the size
 *  meter looked up `13335`, found nothing and said "1 network" beside the hint's real count. Exactly the
 *  contradiction this subscriber list was added to end, one input further along. One normalisation, every
 *  reader — and it mirrors classify.js's own ASN rule rather than re-deriving it loosely. */
const asnKey = v => { const m = /^(?:as:?)?(\d{1,10})$/i.exec(String(v == null ? "" : v).trim());
                      return m ? String(Number(m[1])) : ""; };
function useAsnCounts(raw) {
  // Normalised HERE, not by the caller: the two existing readers hold different shapes (raw text vs a
  // classified badge) and a third will hold a third. A hook that trusts its callers to pre-key it is the
  // same convention that let `as013335` open two cache entries for one AS.
  const nums = [...new Set((raw || []).map(asnKey).filter(Boolean))];
  const [, force] = useState(0);
  useEffect(() => {
    const bump = () => force(x => x + 1);
    _asnSubs.add(bump);
    return () => { _asnSubs.delete(bump); };
  }, []);
  useEffect(() => {
    nums.forEach(n => {
      if (_asnCache[n] !== undefined) return;
      _asnCache[n] = "loading";
      api.asnCount(n).then(r => { _asnCache[n] = (r && r.ok && r.data) ? r.data : { count: 0 };
                                  _asnSubs.forEach(f => f()); });
    });
  }, [nums.join(",")]);
}
/** How many prefixes an `as<n>` target resolves to, 0 while unresolved or unknown. */
export const asnNets = value => {
  const c = _asnCache[asnKey(value)];
  return (c && typeof c === "object" && c.count) || 0;
};
export function AsnHint({ targets }) {
  const asns = [...new Set((String(targets || "").match(/\bas:?\d{1,10}\b/gi) || []).map(asnKey).filter(Boolean))];
  useAsnCounts(asns);   // already keys, and the hook keys again — idempotent, which is the point
  if (!asns.length) return null;
  return html`<div class="asn-hint">${asns.map(n => { const c = _asnCache[n]; const load = c === "loading" || c === undefined;
    const cnt = (c && typeof c === "object") ? c.count : 0;
    return html`<span class=${"asn-tok " + (load ? "load" : cnt ? "ok" : "bad")}>AS${n} ${load ? T("resolving…") : cnt ? T("→ {v1}", { v1: plural(cnt, "prefix") }) : T("→ not found")}</span>`; })}</div>`;
}

// ── egress: where an interface's traffic actually leaves the node ────────────────────────────────
export function EgressPicker({ node, value, onChange, noRules }) {
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const ipIfaces = nrec.ip_ifaces || [];
  // ⚠️ EGRESS = A PHYSICAL NIC, AND ONLY THE KERNEL KNOWS WHICH THOSE ARE. This filtered `ip_ifaces` BY NAME
  // — dropping the self-contained servers (WDTT + csqtt raw-TUN) and mesh links, which are the inbound
  // datapath and never a way out — and everything else was called a NIC. So a TUN some proxy on the box
  // left behind was offered as "Direct — tun0", which is wrong in the way that matters: "Direct" promises
  // a multi-access link whose exit IP the operator picks, and a tunnel is neither. `ether_ifaces` is the
  // node's ARPHRD_ETHER list, the same one `exit_device_refusal` has always used to refuse a NIC as an exit
  // DEVICE — the two halves of one classification, finally reading from one source.
  const others = (Store.nodes || []).filter(n => n.id !== node);
  const exits = nrec.exits || [];
  // The node's default exit, if it has a usable one — what "Auto" actually resolves to on this node.
  const _dflt = (nrec.exits || []).find(x => String(x.id) === String(nrec.default_exit || "")) || null;
  // ⚠️ `auto` AND `direct` COLLAPSE TO ONE ROW, because underneath they are one stored mode: `egressBody`
  // writes `egress_mode:"direct"` for both, and the only difference is whether a NIC/IP refinement is set.
  // They were two rows for as long as the NIC pin lived in this list; with the pin demoted to its own
  // control below, a second row would be a choice without a difference.
  const ifSel = value.mode === "smart" ? "smart" : value.mode === "forward" ? "forward|" + (value.node || "")
    : value.mode === "exit" ? "exit|" + (value.exitId || "") : "auto";
  // Is the value this control is holding something the list below can name? Answered from the SAME source
  // the list is built from, so the two cannot disagree. [[two-readers-one-grammar]]
  // ⚠️ `others` EXCLUDES THIS NODE, and the question here is "does this id resolve to a node", not "is it a
  // node we would offer". A record forwarding to the node's own id is refused on write today, so it can
  // only arrive by hand — but reading it as "a node that is no longer here" would be actively wrong about a
  // node that is right here, and send the operator looking for something that was never removed.
  const _unnamed = value.mode === "forward" && !!value.node && !others.some(n => n.id === value.node);
  const _goneFwd = _unnamed && !(Store.nodes || []).some(n => n.id === value.node);
  // ⚠️ TWO REASONS THE LIST CANNOT NAME THIS VALUE, AND BOTH NEED A ROW. Splitting them fixed the
  // sentence and broke the control: a forward pointing at THIS node is not in `others` either, so with
  // only the `_goneFwd` row it rendered blank — the exact "control shows nothing" failure that let a
  // ghost reference sit unnoticed for a day. And `prune_node_refs` cannot heal this one: the id IS live,
  // so the sweep leaves it alone and only the operator can resolve it.
  const _selfFwd = _unnamed && !_goneFwd;
  // The chosen exit, if it is still there. An interface KEEPS its selection when the exit is turned off, its
  // device goes bad, or the exit is deleted (decision 3) — so all three are reachable here, and each is a
  // different sentence. What they are NOT is a reason to refuse the save or to silently reset the field.
  const exSel = value.mode === "exit" ? exits.find(x => String(x.id) === String(value.exitId || "")) : null;
  const exNote = value.mode !== "exit" ? "" : !exSel
    ? T("That exit no longer exists — traffic goes out directly. Choose another, or add it back under Settings → Network.")
    : exSel.enabled === false
    ? T("This exit is turned off — traffic goes out directly until it is turned back on. The interface keeps this selection.")
    : exSel.why_not
    ? T("This exit's device can't be used right now — traffic goes out directly. Settings → Network says why.")
    : "";
  // WHICH SOURCE THE CHOSEN EXIT LEAVES AS. Said here because the choice is made here and the field lives
  // on the EXIT, one screen away — and because "which card" without "which address on it" is only half the
  // question an operator with a multi-address uplink is asking.
  //
  // ⚠️ IT IS NOT EDITABLE FROM HERE, deliberately. `egress_ip` belongs to the exit, and several interfaces
  // may share one exit: an innocent-looking field on this sheet would silently change where OTHER
  // interfaces leave from. So this reports and points, and the editing stays where the whole record is.
  //
  // Adopted only — an imported exit's device is one the panel minted and its address is not the operator's
  // to override, so there would be nothing to point at.
  const exSrc = (value.mode === "exit" && exSel && !exNote && (exSel.producer || "adopted") !== "imported")
    ? (String(exSel.egress_ip || "").trim()
        ? T("Leaves as {v1}. That source belongs to the exit, so every interface using it shares one — change it under Settings → Network.", { v1: exSel.egress_ip })
        : T("Leaves as whichever address the node picks on {v1}. Pin one on the exit under Settings → Network.", { v1: exSel.device || "" }))
    : "";
  let ipOpts = [];
  if (value.mode === "direct") ipOpts = ipIfaces.filter(p => !value.nic || p.iface === value.nic).map(p => p.ip);
  else if (value.mode === "forward") { const tn = others.find(n => n.id === value.node); ipOpts = (tn && tn.ips) || []; }
  // Spread `value` so the rules keep their place across a mode switch: someone who flips to Auto to look at
  // something and flips back must not find their routing gone.
  // ⚠️ TAKES THE VALUE, NOT AN EVENT. This was `e => e.target.value` for a native <select>; `Dropdown` hands
  // the value straight over, so the old signature read `undefined` off a string and every row in the list
  // silently did nothing when clicked.
  const onIf = v => {
    // ⚠️ AUTO KEEPS THE PIN AND THE SOURCE IP. It used to clear them, which was right while choosing "Auto"
    // was how you cleared a NIC — the NIC was in this list. Now a pinned interface DISPLAYS as Auto, so
    // clicking the row it is already on would silently wipe a setting edited in another control. The pin's
    // own "None" is how it is cleared; the other modes still clear it, because a pin means nothing there.
    if (v === "auto") return onChange({ ...value, mode: "auto", node: "", exitId: "" });
    if (v === "smart") return onChange({ ...value, mode: v, nic: "", node: "", ip: "" });
    const [mode, x] = v.split("|");
    if (mode === "forward") return onChange({ ...value, mode, node: x, nic: "", ip: "", exitId: "" });
    if (mode === "exit") return onChange({ ...value, mode, exitId: x, nic: "", node: "", ip: "" });
    onChange({ ...value, mode, nic: x, node: "", ip: "", exitId: "" });
  };
  return html`<${Fragment}>
    <div class="field"><label>${T("Outbound (egress) interface")}</label>
      ${/* ⚠️ THE SAME LIST THE NODE'S OWN EGRESS PICKER OFFERS, from the same builder. This was a hand-written
            <select> with every exit in ONE flat group called "out via a device on this node" — a WARP account,
            a pasted profile and a TUN somebody else runs, shelved together, an untitled account reading as a
            raw `wgx-f4256ea7`, and no way to tell one that is still registering from one that is carrying
            traffic. `exitOptionGroups` exists precisely so this list is written once and spelled twice (an
            interface stores `exit|<id>`, the node's default stores a bare id) — it had one caller.
            NO ROW CONTROLS HERE. Switching an exit off, renaming or deleting it is node-wide, and this is an
            interface's editor: the shared builder makes every one of those optional, and this screen takes
            none of them. `Manage…` is not offered for the same reason — exits are managed where they live. */""}
      ${/* ⚠️ "AUTO" NAMES WHAT IT RESOLVES TO. An interface stored as direct-with-nothing-set inherits the
            node's default exit — `cascade_plan` literally rewrites its mode to `exit` and lends it that id —
            and the label said "Auto (MASQUERADE)" whatever the node was configured to do. So the one entry
            that means "no opinion" was also the one that never said what the opinion would be. Same idiom
            the egress-source picker uses: the parenthetical exists only when we can name the answer. */""}
      <${Dropdown} value=${ifSel} onChange=${onIf} options=${[
        { value: "auto", label: _dflt ? T("Auto ({v1})", { v1: _dflt.label || _dflt.device || _dflt.id })
                                      : T("Auto (MASQUERADE)") },
        // ⚠️ THE NAT PIN IS NOT IN THIS LIST ANY MORE — see the control below. It was named for what it
        // changes (decision B1) and that was still not enough: this list answers "where does traffic GO",
        // and the pin answers nothing of the kind. It routes nothing. Read here it was taken for a milder
        // way of leaving by a card, which is the one thing it cannot do — twice, by the operator who
        // commissioned it. A row that has to be explained every time it is read is in the wrong place, so
        // it moved to a control of its own that says so.
        // ⚠️ `devices: true` HERE TOO. These lists used to differ: the node's own egress picker offered the
        // devices the node reports and this one did not, so an operator could send the WHOLE node out
        // `wg-lab0` but not a single interface — the same device, present in one list and absent from the
        // next. It was opt-in because choosing one MINTS a record and only that screen could write the
        // node's exit list; the mint now happens server-side on the save that references it
        // (`_mint_device_exit`), so every picker can offer them and a cancelled sheet leaves nothing.
        ...exitOptionGroups(nrec, { prefix: "exit|", devices: true }),
        ...(others.length ? [{ group: T("Forward to node (cascade)"), items: others.map(n => ({ value: "forward|" + n.id, label: T("Forward to {node}", { node: n.name }) })) }] : []),
        // ⚠️ A FORWARD WHOSE TARGET NODE IS GONE MUST BE NAMED, NOT BLANK. The options above are built from
        // the nodes that DO exist, so a stored `forward|<removed id>` matched nothing and the control
        // rendered EMPTY — the same silent hole `goneDest` closes for a rule's destination, in the control
        // next to it. Meanwhile `cascade_plan` drops the forwarding (`if not P or P not in nodes: return`),
        // so the interface behaves as direct while still claiming to cascade. `prune_node_refs` now repairs
        // this on the server, but a reference can still be held here between the node's removal and that
        // sweep — and a control that shows nothing is how it went unnoticed for a day.
        ...(_selfFwd ? [{ value: ifSel, label: T("This node itself"), className: "bad",
                          refuse: T("This interface is set to forward everything to the node it is already on, which cannot work — the traffic would leave by this node's own address anyway. Choose another destination.") }] : []),
        ...(_goneFwd ? [{ value: ifSel, label: T("A node that is no longer here"), className: "bad",
                          refuse: T("This interface forwards everything to a node that is not in this panel any more, so it routes nothing and its clients leave by this node's own address. Choose another destination.") }] : []),
        // A MODE, not a destination — last, outside every group, the way `Block` sits apart in the rule
        // picker.
        ...(others.length ? [{ value: "smart", label: T("Routing (smart cascade)"), className: "egopt-mode" }] : []),
      ]}/>
      ${/* The hint has to carry the same distinction the list does, or it re-merges the two things the
            labels just separated: pinning a source is not a way out, and the sentence used to call it one
            ("exit directly out a NIC") while the group below now offers actually leaving by that card. */""}
      <div class="hint">${exits.length
        ? T("Leave by a device on this node, channel everything through another node, or route per-destination (smart).")
        : T("Leave normally, channel everything through another node, or route per-destination (smart).")}</div>
      ${exNote ? html`<div class="hint err">${exNote}</div>` : null}
      ${exSrc ? html`<div class="hint">${exSrc}</div>` : null}</div>
    ${/* THE NAT PIN IS NOT HERE ANY MORE — it lives under each sheet's "Advanced settings", as
          `NatSourcePick` below. It is not an egress DESTINATION and it was read as one twice; the sheets
          are where the "this is advanced, and it is not routing" framing can actually be built. */""}
    ${value.mode === "smart"
      ? (noRules ? null : html`<${RoutingRules} node=${node} rows=${value.rows || []} catchAll=${value.catchAll} onChange=${(rows, catchAll) => onChange({ ...value, rows, catchAll })}/>`)
      : (value.mode !== "auto" && value.mode !== "exit") ? html`<div class="field"><label>${T("Outbound (egress) IP")}</label>
      <${NodeIpPick} ips=${ipOpts} value=${value.ip || ""} onChange=${ip => onChange({ ...value, ip })} auto=${value.mode === "forward" ? T("Auto (target node default)") : T("val|Auto")}/>
      <div class="hint">${value.mode === "forward" ? T("Source IP on the target node that clients egress from.") : T("Source IP clients egress from.")}</div></div>` : null}
  <//>`;
}

/** Does the NAT source pin apply to this egress mode at all?
 *
 *  ⚠️ ONLY `auto` AND `direct`, and this is a CORRECTNESS test, not a tidiness one. `egressBody` sends
 *  `wan_iface` for exactly those two modes — an `exit` saves `{egress_mode, exit_id}` and a `smart` saves
 *  `{egress_mode, routing}`, neither of which carries it. So offering the control in the other modes is
 *  offering something the save throws away, AND the control had to set `mode` to make the value meaningful,
 *  which silently destroyed the mode it was sitting under. Measured: an interface on an exit lost its
 *  `exit_id`, and one on smart routing lost every rule, from a dropdown in a collapsed section. */
export const natPinApplies = eg => ((eg || {}).mode === "auto" || (eg || {}).mode === "direct");

/** THE NAT SOURCE CARD — `wan_iface`, and nothing else.
 *
 *  ⚠️ WHY IT IS A COMPONENT OF ITS OWN, AND NOT A ROW IN THE EGRESS LIST. It does not route. It installs
 *  one `-o <card>` MASQUERADE and waits for traffic that something ELSE sends to that card. Sat in the
 *  egress list — the control that answers "where does traffic go" — it was read as a milder way of leaving
 *  by that card, which is the one thing it cannot do. Twice, by the operator who chose its name. A row that
 *  has to be explained every time it is read is in the wrong place, so it moved under "Advanced settings",
 *  where the sheet can frame it as advanced and its own sentence can lead with what it does NOT do.
 *
 *  KEPT, not removed: three setups need it and none can be said any other way — routing the operator
 *  manages outside the panel, forcing our NAT where the baseline defers to a foreign rule (`_egress_des`
 *  returns on `wan_ov` BEFORE the `_has_foreign_egress` test), and choosing which card a cascade's
 *  forwarded traffic is NAT'd out of.
 *
 *  Takes the same `value`/`onChange` pair as `EgressPicker` because it edits the SAME draft — `nic` is one
 *  field of one egress record, and giving it a second state to keep in step is how the two would drift. */
export function NatSourcePick({ node, value, onChange }) {
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const ipIfaces = nrec.ip_ifaces || [];
  // Falls back to the old name filter only while the node has not reported it: a node that has not spoken
  // yet must not lose its egress list, and this is the same "found nothing is not asked-and-there-is-
  // nothing" rule the refusal set follows.
  const nics = (nrec.ether_ifaces && nrec.ether_ifaces.length)
    ? nrec.ether_ifaces.filter(n => !isSelfContainedName(n) && !n.startsWith("swg_"))
    : [...new Set(ipIfaces.map(p => p.iface))].filter(n => !isSelfContainedName(n) && !n.startsWith("swg_"));
  // ⚠️ A PINNED NIC IS A NAT SELECTOR, NOT A ROUTE — and when it names a card this node's traffic does not
  // leave by, the ONE rule it produces can never match. `_egress_des` (swg-noded:1629) is a ladder that
  // RETURNS on `wan_ov`, so the baseline MASQUERADE out the real WAN is never added either: the clients
  // egress un-NATted, are dropped upstream, and every screen keeps saying the interface is healthy. This is
  // the `Direct — wdttraw2` defect one layer down — there a device that could not carry traffic was offered,
  // here a device that can is pinned for a job it is not doing.
  //
  // A WARNING, NOT A REFUSAL, and that is deliberate: a second uplink the operator policy-routes to by hand
  // outside the panel is a real setup, and this control is the only way to NAT for it. So it names the
  // consequence and the two controls that avoid it, and leaves the choice alone.
  //
  // ⚠️ ONLY SAID WHEN THE NODE HAS TOLD US ITS WAY OUT. A blank `wan_iface` is a node that has not reported,
  // not a mismatch — the same "found nothing is not asked-and-there-is-nothing" rule the `nics` list above
  // and the refusal set both follow. Recomputed from the live snapshot each render, so a failover that moves the
  // default route onto the pinned card clears this by itself.
  // ⚠️ EITHER SPELLING OF THE ONE MODE. `egressBody` stores `auto`+nic and `direct`+nic identically, so a
  // pin is LIVE under both — and testing only `direct` let a freshly-pinned draft (still `auto` until it is
  // saved and read back) show no warning at all.
  const nicNote = (value.mode === "direct" || value.mode === "auto") && value.nic
    && nrec.wan_iface && value.nic !== nrec.wan_iface
    // ⚠️ NAMES THE CONTROL IT SITS IN. It used to say "or Auto", which was the row directly above it while
    // the pin lived in the mode list; from inside its own section that points at a different control on a
    // different question. "Off" is the option one click away, in the dropdown this sentence is under.
    ? T("This node's traffic leaves by {v2}, not {v1}, so this rule can never match and clients would leave with no NAT at all. Choose “Off”, or {v2} — unless you route to {v1} yourself.",
        { v1: value.nic, v2: nrec.wan_iface })
    : "";
  // Nothing to pin to, or a mode that does not store a pin — either way a control here is a dead field,
  // and in the second case a destructive one (see `natPinApplies`).
  if (!nics.length || !natPinApplies(value)) return null;
  // ⚠️ THE HEADING DOES NOT NAME A CARD, and that is deliberate — it is the third attempt at this label and
  // the first two both failed the same way. "Direct — source from eth2" and then "NAT source card" each led
  // with the DEVICE, and each was read as "send traffic out that card" (twice, by the operator who
  // commissioned the naming). Naming the ACT instead removes the misreading structurally rather than
  // apologising for it in the hint. It also fixes Russian, where a bare `карта` reads as "map" first and
  // `карточка` is already the word for a UI card — so the old label said something close to "map for the
  // NAT address". `Off` rather than `Not pinned`: "pinned" is our implementation's metaphor, not the
  // operator's, and in Russian it had to agree in gender with a noun this heading no longer contains.
  // ⚠️ IT CARRIES ITS OWN SECTION HEADING. The callers place it inside a shared "Advanced settings" body
  // next to that protocol's settings, and a heading supplied by four callers is four chances to word it
  // differently — or, as happened here, to render it TWICE beside the component's own label.
  return html`<${Fragment}>
    <div class="field secdiv"><label>${T("Extra NAT")}</label></div>
    <div class="field">
    <${Dropdown} value=${value.nic || ""}
      onChange=${n => onChange({ ...value, nic: n, mode: n ? "direct" : "auto" })}
      options=${[{ value: "", label: T("val|Off") }, ...nics.map(n => ({ value: n, label: n }))]}/>
    ${/* THE SENTENCE THIS CONTROL EXISTS TO CARRY, and it leads with the negative because that is the half
          every reader gets wrong: it does not send anything anywhere. */""}
    <div class="hint">${T("This doesn't send traffic out that card. It only changes the source address of traffic that already leaves by it — use it when you route to that card yourself, outside the panel. To leave by a card, pick it under “Leave by a device”.")}</div>
    ${nicNote ? html`<div class="hint err">${nicNote}</div>` : null}
    </div>
  <//>`;
}

/* The stored rule list becomes the rows the operator edits, here and only here — the pair every save path
   already funnels through, so no save path learns the row shape (§5, §7.3). Badges that came from STORAGE are
   marked as such: a stored entry that this node's engine can no longer run is shown inert and kept, while
   creating one is refused, and the two cases are only distinguishable by where the badge came from. */
export const egressInit = m => {
  const { rows, catchAll } = rulesToRows(m.routing || []);
  for (const r of rows) for (const b of (r.badges || [])) b.stored = true;
  return { mode: m.egress_mode === "smart" ? "smart" : m.egress_mode === "forward" ? "forward"
      : m.egress_mode === "exit" ? "exit" : (m.egress_ip || m.wan_iface) ? "direct" : "auto",
    nic: m.wan_iface || "", node: m.egress_node || "", ip: m.egress_ip || "",
    // The exit an interface leaves by, by ID. Read here or the editor QUIETLY UNDOES THE SELECTION: with no
    // `exit` arm this ternary lands on "auto", so opening an exit interface to change its MTU and pressing
    // Save rewrites it to direct, with the operator having changed nothing they can see.
    exitId: m.exit_id || "", rows, catchAll };
};

// WHY SAVE IS BLOCKED, or null. One call, consulted by all four Save buttons — and it is deliberately ONE
// call rather than two, which the name now says: it was `egressError`, and it answers two questions.
//
//   1. IS THE CONFIG VALID — an empty row, an invalid badge, a hostname on an IP-only node. `mode` is the
//      node's routing_mode; in kernel (IP-only) a rule cannot name a hostname, only a host layer matches by
//      name. The field already refuses to CREATE such a badge, so this is the backstop for the two cases the
//      field cannot reach: a row with nothing in it, and a stored entry the panel would reject on the way in.
//   2. IS THERE TEXT THE EDITOR HAS NOT APPLIED — `row._draft`. Not an invalid value at all, a transient
//      editor state, and the reason it lives here anyway is that this is the ONE thing every Save path
//      consults. Split into a second function and a caller that forgets to call it saves the row as it was
//      BEFORE, silently, with the operator looking at the lines they just typed. That bug existed; the fix
//      was to put the check where nothing can route around it.
//
// It walks rows, and the shadowing lint that used to live here is now per badge, in the row.
export function egressSaveBlock(eg, mode) {
  // An interface set to "exit" with no exit chosen is the shape this tree keeps having to close: accepted by
  // the field, stored, badged, and routing nothing. Checked here because this is the one gate every Save
  // path consults — and note it sits ABOVE the smart-only return, which is exactly the line a fifth mode
  // gets added below by mistake.
  if (eg && eg.mode === "exit" && !String(eg.exitId || "").trim())
    return T("Choose which exit this interface leaves by.");
  if (!eg || eg.mode !== "smart") return null;
  for (const row of (eg.rows || [])) {
    if (row.locked) continue;                         // a legacy rule is re-emitted verbatim; nothing to validate
    // TEXT STILL IN THE TEXT VIEW IS NOT IN THE RULE. `draft` is local to the field until `</>` applies it,
    // so saving here would write what the row held BEFORE — silently, with the operator looking at the lines
    // they just typed. Checked before the emptiness test on purpose: "add at least one target" is the wrong
    // sentence to show someone staring at ten of them.
    if (row._draft) return row._draft;
    // THE SAME SHAPE THE `exit` MODE IS GUARDED FOR SIX LINES UP: a destination that names nothing is
    // accepted by the field, stored, and routes nothing. NOT a check that the exit still EXISTS — that one
    // degrades at plan time on purpose, and refusing it here is how an interface becomes unsavable
    // including the save that would move it off the deleted exit.
    if (row.action === "dev" && !String(row.exit_id || "").trim())
      return T("Choose which exit this rule leaves by.");
    const badges = row.badges || [];
    if (!badges.length) return T("A rule needs at least one service, address or IP range.");
    const bad = badges.filter(b => b.t === "target" && b.kind === "invalid").map(b => b.raw);
    if (bad.length) {
      const list = bad.slice(0, 4).join(", ") + (bad.length > 4 ? "…" : "");
      return bad.length > 1 ? T("Invalid targets: {list}", { list }) : T("Invalid target: {list}", { list });
    }
    if (mode === "kernel") {
      // ASYMMETRIC ON PURPOSE: block CREATION, tolerate what is already there. A badge that came from storage
      // was fine when it was written and stopped being enforceable when the node's engine changed — refusing
      // the save is how the interface becomes unsavable, including the save that would remove the badge. The
      // panel now keeps it and drops it at plan time, so Save is honest either way; the badge is inert, with
      // the reason and the one-click switch on it (§4.2, and §1.7e where the lockout was reproduced).
      const doms = badges.filter(b => b.t === "target" && b.kind === "site" && !b.stored).map(b => targetLabel(b.kind, b.value));
      // One key per count, not a sentence assembled with `+`: the pieces cannot be reordered, and Russian
      // needs the noun in a case the English suffix trick cannot express.
      if (doms.length) {
        const list = doms.slice(0, 3).join(", ") + (doms.length > 3 ? "…" : "");
        return doms.length > 1
          ? T("IP-only mode routes by IP only — remove the domains ({list}), or switch this node to Force-DNS.", { list })
          : T("IP-only mode routes by IP only — remove the domain ({list}), or switch this node to Force-DNS.", { list });
      }
    }
  }
  return null;
}

// The interface's egress/traffic mode as a header badge — shared by wg/awg + WDTT detail: direct | cascade
// (whole-interface forward to a node) | smart cascade (per-destination routing).
/** The node's report about one device, by name — and `candAddr`, the bare address out of it. Six places
 *  asked this question and four of them spelled it out inline, two with the same `.find()` written twice on
 *  one line to reach through it. One spelling, so "what address does the node say this device has" cannot
 *  come back differently on two screens. */
export const candOf = (node, name) =>
  ((node || {}).exit_candidates || []).find(c => c && c.name === String(name || "").trim()) || null;
export const candAddr = (node, name) => String((candOf(node, name) || {}).address || "").split("/")[0];

/** Every address this node reports ON `name`, or [] — the choices for "which of this card's addresses does
 *  traffic leave as".
 *
 *  ⚠️ ONLY MEANINGFUL FOR A CARD. `_validate_exits` deliberately does NOT check an exit's `egress_ip`
 *  against the node's addresses, and its reasoning is right for the case it was written for: an adopted
 *  TUN belongs to software the panel cannot see, so refusing an address we do not know about would block
 *  the exact setup the field exists for. A NETWORK CARD is the other case — the node reports its addresses
 *  (`ip_ifaces`, `{ip, iface}` pairs), so here the panel CAN offer them, and a free-text box where a list
 *  would do is how an operator types the address of the other card by mistake. Typing stays available for
 *  everything this list cannot know. */
export const cardAddrs = (node, name) => (((node || {}).ip_ifaces) || [])
  .filter(p => p && String(p.iface) === String(name || "") && p.ip).map(p => p.ip);

/** Is `name` one of this node's network cards? Cards are the only devices a gateway means anything for —
 *  down a point-to-point tunnel the node ignores it (`_devexit_gw`), so a field offered there would be one
 *  the operator can fill and nothing reads. */
export const isCardName = (node, name) => (((node || {}).ether_ifaces) || []).includes(String(name || ""));

/** The gateway the NODE detected on `name`, or "" — what a blank override falls back to.
 *  ⚠️ `ether_gws` is `null` when the node has never reported gateways (an older build), and `{}` when it
 *  reported and found none. Both read as "" here, which is right for a placeholder; the REFUSAL set is
 *  where that difference matters. */
export const cardGateway = (node, name) => String((((node || {}).ether_gws) || {})[String(name || "")] || "");

/** IS THIS EXIT READY TO CARRY TRAFFIC, and if not, what do we tell the operator?
 *
 *  ⚠️ ONE ANSWER, FOUR SURFACES. The exit picker, the manage grid, the WARP grid and the node's egress
 *  field each need this, and each of them used to work it out for itself from a slightly different subset
 *  of the same fields — which is how one screen came to show a hollow "waiting" dot for an exit another
 *  showed as fine. The states are not cosmetic: the picker REFUSES a choice on the strength of them.
 *
 *  Takes the NODE, not a pre-resolved candidate: the adopted arm needs the node's report about the device,
 *  and an API that made each caller fetch it was one where forgetting to silently downgraded a healthy exit
 *  to "the node has never mentioned this" — the one state that cannot be told from the real thing by looking.
 *
 *  ⚠️ AND THE TWO ARMS DISAGREE ABOUT "the node has not mentioned this device", on purpose:
 *    IMPORTED  we asked the node to CREATE it. Silence means it has not finished (or has not started), so
 *              the exit cannot carry anything yet and the picker says so.
 *    ADOPTED   the operator typed a name for a device something else runs, explicitly ahead of the node
 *              seeing it ("nothing is checked until the node next syncs"). Silence is the DOCUMENTED
 *              flow, not a fault — refusing it here would break the feature that exists to allow it.
 */
export function exitHealth(x, node) {
  const ex = x || {};
  const l = ex.live || {};
  const cand = candOf(node, ex.device);
  const why = String(ex.why_not || "").trim();
  // The panel's own refusal outranks anything the node says: a device we will never lower cannot be
  // "waiting", and telling the operator to wait for something that is never coming is the worse lie.
  if (why) return { state: "refused", tone: "bad", dot: "bad", why: T("Refused: {v1}", { v1: why }) };
  // ⚠️ A NODE OLDER THAN THE FEATURE ITSELF, which no test below can catch because it has nothing to read.
  // Such a node reports no exits at all, so `l` is empty for ever — and the tests then resolved to PROGRESS:
  // an imported exit sat on "Waiting for the node to set this up…" with a spinner that could never stop, and
  // an adopted one on "This node hasn't reported a device by this name" about a device that is present and
  // up. Measured against `main`'s swg-noded on hel-flux: both, indefinitely, with nothing on the row naming
  // the cause. The panel derives `exits_unsupported` from the ABSENCE of the `exits` key in the snapshot
  // (never from a version string), and it is False for a node that has simply not synced yet — so this
  // cannot swallow the real `creating` a freshly-created exit passes through.
  //
  // Placed above the producer split because it is true of BOTH: the node neither builds an imported exit nor
  // lowers the routing for an adopted one, so a device exit on such a node is just as silently dead.
  if ((node || {}).exits_unsupported)
    return { state: "unsupported", tone: "warn", icon: "warn", dot: "unknown",
             why: T("This node's software is too old for exits. Update the node — nothing else needs changing.") };
  if ((ex.producer || "adopted") !== "imported") {
    if (!cand) return { state: "unreported", tone: "", dot: "unknown",
                        why: T("This node hasn't reported a device by this name.") };
    if (cand.up === false) return { state: "down", tone: "warn", dot: "down",
                                    why: T("The node reports this device is not up.") };
    return { state: "ok", tone: "", dot: "up", why: T("Up on the node.") };
  }
  // ⚠️ A REPORT ABOUT THE CONFIG YOU JUST REPLACED IS NOT A REPORT ABOUT THIS ONE, and every test below
  // reads one: `error`, `up` and `handshake` all describe whatever the node last converged on. Save a new
  // profile and, until the node's next pass lands, the row went on stating the old verdict with total
  // confidence — green for a config that no longer exists, or the previous config's failure against the
  // paste that fixes it. The panel stamps each exit with a digest of the material the node is sent
  // (`exit_cfg_sig`) and the node echoes back the one it is working to, so "not caught up yet" is a fact
  // on the wire rather than a guess from a timer.
  //
  // Requires the node to have sent a stamp AT ALL: a node older than its panel never will, and treating
  // its silence as "behind" would spin every exit on it for ever.
  //
  // ⚠️ AND IT REQUIRES THE NODE TO BE REPORTING. "Applying your changes on the node…" is a claim that work
  // is happening; on a node that has gone dark nothing is, and the spinner would turn for ever while hiding
  // the one reading that still means something — `l.error`, the reason this exit was broken before the
  // operator tried to fix it. Edit an exit on an offline node and the row promised progress it had no
  // grounds for, which is the same complaint this whole state was added to answer, pointed the other way.
  // Stale, the row falls through and states the last thing the node actually said. That is old, but it is
  // TRUE, and the node's own card on this screen already says it has stopped reporting.
  if (ex.cfg_sig && l.cfg_sig && l.cfg_sig !== ex.cfg_sig && !nodeStale((node || {}).id))
    return { state: "configuring", tone: "busy", icon: "refresh", dot: "unknown",
             why: T("Applying your changes on the node…") };
  if (l.error) return { state: "failed", tone: "bad", dot: "bad",
    // An error with no "and then what" reads as stuck — the node reports when it will try again, so say it.
    // ⚠️ THROUGH T(), like every other sentence the SPA shows. The node's own words arrived verbatim, so a
    // Russian panel read «Не удалось: the escrowed key did not open…» on the screen this release leads
    // with. Sentence-as-key is the convention here, so T() translates the ones the catalogue knows and
    // returns the rest unchanged — nothing regresses, and the fixed ones stop being English.
    why: T(l.error) + (l.retry_in ? " " + T("Retrying in {v1}.", { v1: l.retry_in >= 60
      ? T("{v1} min", { v1: Math.round(l.retry_in / 60) }) : T("{v1} s", { v1: l.retry_in }) }) : "") };
  // ⚠️ PROGRESS IS NOT A FAULT. A WARP account the node has not finished registering wore the same amber
  // warning triangle as a failed one, so the first thing an operator saw after creating an exit was a
  // panel telling them something was wrong with it. `busy` renders the circling-arrows icon the panel
  // already uses for `rotating` and `restoring` — the same vocabulary for the same kind of state.
  if (!l.device) return { state: "creating", tone: "busy", icon: "refresh", dot: "unknown",
                          why: T("Waiting for the node to set this up…") };
  // What the node ACTUALLY SAW, when it saw anything. The probe crosses the whole tunnel, so its failure
  // names the real obstacle — timed out, connection refused, network unreachable — which no sentence the
  // panel can compose from `up`/`handshake` ever could. Reported separately from `l.error` on purpose: that
  // one means the exit could not be built, this one means it was built and carried nothing.
  const probe = String((l.trace || {}).err || "").trim();
  const said = t => probe ? t + " " + T("The node reports: {v1}", { v1: probe }) : t;
  if (!l.up) return { state: "down", tone: "warn", dot: "down",
                      why: said(T("The node reports this device is not up.")) };
  // ⚠️ UP IS NOT WORKING. This returned "ok" the moment the device existed, whatever was at the other end —
  // so a pasted AmneziaWG profile brought up as plain WireGuard was drawn GREEN while carrying nothing: the
  // interface was up, and up was the whole question. A handshake is the first fact that is only true if the
  // far side agreed — right keys, reachable endpoint, matching obfuscation.
  //
  // `=== 0` and not falsy: 0 means the node asked and the answer was NEVER, while `undefined` is a node too
  // old to say and must keep the old reading rather than turn every exit on the fleet amber.
  // ⚠️ A SECOND FACT FROM THE SAME PASS, because `handshake` alone has a value that means two things. The
  // node computes an age as `now - timestamp`, so for one whole second after every rekey that age IS 0 —
  // the same 0 that means NEVER. Fixed in the node (the age now floors at 1), but a node is allowed to be
  // older than its panel here, and on an older one this drew a fault on every healthy exit in turn, about
  // once every two minutes each. The trace settles it: it is a request that crossed this tunnel in the
  // same pass, and traffic cannot have crossed a peer that never answered. This only ever silences a false
  // alarm — an exit that really has never handshaken has no trace either, and still warns below.
  // ⚠️ AND THE ADVICE HAS TO MATCH WHAT THE OPERATOR ACTUALLY TYPED. Both sentences below tell them to
  // "check the endpoint and the keys" — true of a PASTED profile, and false of a WARP account, where the
  // panel registered the account and the node holds the key: there is no endpoint and no key on that
  // screen to check, so the one instruction the row gives cannot be followed. Measured on nixos: a WARP
  // exit sending 520 KiB and receiving 0 B, with `tcpdump -ni any "udp port 2408"` showing 12 packets Out
  // and 0 In, while ICMP to the same address answered in 13 ms and the WARP API answered over HTTPS —
  // a network that drops WARP's datapath and nothing else. The same code on msk-main handshakes fine
  // (over IPv6). Nothing on that node was misconfigured and nothing on that screen could have fixed it.
  if (l.handshake === 0 && !(l.trace || {}).ip) return { state: "nohandshake", tone: "warn", icon: "warn", dot: "down",
    why: said((ex.provider || "warp") === "warp"
      ? T("The tunnel is up, but Cloudflare never answered it. Nothing here is yours to correct — the keys and the endpoint are the panel's own. Networks that block WARP look exactly like this, so try a pasted profile instead, or put this exit on another node.")
      : l.awg
      ? T("The device is up, but this peer has never answered. Check the endpoint, the keys, and that the server really is AmneziaWG with these exact obfuscation values.")
      : T("The device is up, but this peer has never answered. Check the endpoint and the keys — and if the server is AmneziaWG, its profile must be pasted with its obfuscation lines intact.")) };
  // ⚠️ NO `unproven` STATE HERE, and the reason is worth keeping. The first fix for "green with no IP and no
  // latency" warned whenever an imported exit had no trace — but the trace is a request to cloudflare.com,
  // so a node whose egress is firewalled to specific destinations would have a perfectly good tunnel and a
  // permanent amber warning. The real hole was in the node: `_exit_handshake` asked with the tool for the
  // RECORD, which returns nothing the moment record and device disagree — exactly the case worth reporting.
  // It now asks by what the device IS and falls back to the other tool, so `handshake` is answerable for any
  // device that exists, and the `=== 0` test above catches the reported case without inventing a second one.
  return { state: "ok", tone: "", dot: "up", why: T("Up on the node.") };
}

/** The one marker for an exit's health. Three screens rendered this by hand and all three hardcoded the
 *  warning triangle, so a state that is not a warning could not look like anything else — which is how a
 *  WARP account still being created came to wear a fault icon. The health verdict names its own icon; this
 *  just draws it. */
export const exitHealthMark = (h) => {
  if (!h || !h.tone) return null;
  // A `busy` marker is progress, not a fault — there is nothing to open and nothing to read, so it keeps
  // the plain hover caption it always had.
  if (h.tone === "busy" || !h.why)
    return html`<span class=${"ddwarn " + h.tone} title=${h.why}><${Ic} i=${h.icon || "warn"}/></span>`;
  // ⚠️ CLICKABLE, like every other fault marker in the panel. A native `title` shows on hover, at the
  // mercy of the browser's delay, is unselectable and unreachable on a touch screen — and the reason an
  // exit is not working is the one sentence an operator most needs to be able to read, copy and act on.
  // `CmdErr` and `StatusTag` already answer this the same way, so this is the third caller of one idiom
  // rather than a third idiom. `stopPropagation` because these markers sit inside rows that are themselves
  // buttons: in the exits table the row opens the editor, in the dropdown it selects the exit.
  return html`<span class=${"ddwarn ddwarn-clk " + h.tone} title=${T("Show the reason")}
    onClick=${e => { e.preventDefault(); e.stopPropagation();
                     openConfirm({ title: T("This exit isn't working"), log: h.why, confirmLabel: T("Close") }); }}
    ><${Ic} i=${h.icon || "warn"}/></span>`;
};

/** ── THE NODE'S EXITS, AS DROPDOWN GROUPS ───────────────────────────────────────────────────────────────
 *  ONE list, so every control that asks "where does this leave by" asks it the same way and an operator who
 *  has learned one has learned the others. The groups are the operator's taxonomy, not the schema's:
 *
 *    Exit via WARP                    what the PANEL created and holds the key to — a registered WARP
 *                                     account, and a pasted profile, which is set up in the same place and
 *                                     is therefore an external WARP profile as far as anyone using it is
 *                                     concerned. It is labelled `Custom — <name> — <device>` so the two are
 *                                     still tellable apart at a glance.
 *    Exit via an external interface   a device the panel did NOT create and only points at.
 *
 *  `prefix` because the same option means the same thing at two scopes but is STORED differently: an
 *  interface or a rule keeps `exit|<id>` alongside its other destination kinds, the node's default keeps a
 *  bare id because an exit is the only thing it can be. One list, two spellings, no second copy.
 *
 *  `onToggle` turns each row into a switch as well as a choice. A row that is OFF is dimmed and REFUSES
 *  the choice, saying so — it stays in the list because the switch that unblocks it is in the row, and
 *  because a stored selection that was later switched off still has to be showable.
 *
 *  `onManage` puts a Manage button on that same last row — the row is already the list's "none of these"
 *  answer, so the fuller version of it belongs beside rather than below.
 *
 *  `custom` appends "Custom interface…". Without it the answer to "I want everything out this TUN" was
 *  "go to another screen, add an exit, come back and pick it" — the device is on the box, the operator
 *  knows its name, and the list they are already looking at is where it belongs.
 *
 *  ⚠️ REMOVAL CONFIRMS **IN THE ROW**, not in a modal. A confirm dialog over an open dropdown is the wrong
 *  shape twice over: it covers the list the operator is reading, and dismissing it takes the popup with it —
 *  so deleting three stale entries meant reopening the dropdown three times. Armed, the row swaps its own
 *  controls for the question and answers it in place; the list never moves and the next row is one click
 *  away. `armed` is the id currently asking, `onArm` sets it, `onRemove` is the yes.
 *
 *  `onRemove` puts a red X on the external rows that are RECORDS — the ones the operator added, by typing a
 *  name or by choosing a reported device. A purely discovered row has nothing to remove: the device is on
 *  the box whatever the panel thinks, and an X there would promise something this screen cannot do.
 *
 *  `onRename` puts a pencil on every EXTERNAL-INTERFACE row. Those rows are the only ones whose name is a
 *  bare device (`tun-lab0`), because nothing else in the panel offers a place to title them — a WARP exit
 *  has a Name field on its own screen and an interface has its own card. Without it the only way to give
 *  one a human name was to go and find it in External exits, which is the detour this list exists to end.
 */
export function exitOptionGroups(node, { prefix = "", onToggle = null, custom = "", onRename = null, onRemove = null, onManage = null, armed = "", onArm = null, stored = null, devices = false } = {}) {
  const exits = ((node || {}).exits || []).filter(x => x && x.id);
  // ⚠️ TWO SOURCES, AND THEY ARE NOT INTERCHANGEABLE. The rows are built from whatever the caller passed —
  // usually a DRAFT, so a rename shows before it is saved — but `nFields` deliberately strips `live` and
  // `why_not` from that draft, because they are panel-owned and including them would make the section go
  // dirty every time the node reported something new. Health read off the draft therefore sees no `live`
  // at all and calls every WARP account "still being created", triangle and all, including the ones that
  // are up. Measured on the rig: seven healthy exits, seven warnings. So health comes from `stored`.
  const health = x => exitHealth((stored || exits).find(o => String(o.id) === String(x.id)) || x, node);
  // The row's own controls, as one slot. A pencil is offered only where `onRename` says a row can be
  // titled; the switch only where there is something to switch.
  const ctl = (x, pencil, sw) => (x || pencil || sw)
    ? html`<${Fragment}>${x}${pencil}${sw}<//>`
    : null;
  const rmBtn = arg => (onRemove
    ? html`<button type="button" class="ddrm" title=${T("Remove")}
        onClick=${e => { e.stopPropagation(); (onArm || onRemove)(onArm ? arg.id : arg); }}><${Ic} i="x"/></button>`
    : null);
  // The row, asking. Deliberately the whole control slot: half a row of switches beside "delete?" reads as
  // two questions, and the switch is exactly the thing not to leave clickable while a delete is pending.
  const confirmRow = arg => html`<span class="ddconf">
    <span class="ddconf-q">${T("Delete?")}</span>
    <button type="button" class="ddconf-y" onClick=${e => { e.stopPropagation(); onRemove(arg); }}>${T("val|Yes")}</button>
    <button type="button" class="ddconf-n" onClick=${e => { e.stopPropagation(); onArm(""); }}>${T("val|No")}</button>
  </span>`;
  const penBtn = arg => (onRename
    ? html`<button type="button" class="ddpen" title=${T("Rename")}
        onClick=${e => { e.stopPropagation(); onRename(arg); }}><${Ic} i="pencil"/></button>`
    : null);
  const mk = (x, label) => {
    const on = x.enabled !== false;
    const live = x.live || {};
    // ⚠️ AN EXIT THAT CANNOT CARRY TRAFFIC IS NOT A CHOICE. A WARP account still registering, or one whose
    // registration failed, has no device on the box — choose it and the node has nothing to route to, so the
    // traffic falls through to direct and leaves from the very address the exit exists to hide. Refused the
    // same way an OFF row is (dimmed, still listed, says why) rather than hidden, because a stored selection
    // that has since broken must stay visible and nameable.
    // ADOPTED rows are deliberately exempt — see `exitHealth`: a device the node has not reported yet is the
    // documented way to name one ahead of time, not a fault.
    const h = health(x);
    const notReady = (x.producer || "adopted") === "imported" && h.state !== "ok";
    const mark = h.tone
      ? exitHealthMark(h)
      : null;
    return {
      value: prefix + x.id, label,
      // DIM, NOT DISABLED. `disabled` would take the row out of arrow-key navigation entirely — and the row
      // has to stay reachable, because the switch that unblocks it lives in the row. It refuses the CHOICE
      // and says why instead. A stored selection that was later switched off still renders here, which is
      // the other reason the row cannot simply vanish.
      className: (on && !notReady) ? "" : "dim",
      ...(on
        ? (notReady ? { refuse: h.why } : {})
        // NOT "switch it on HERE" — the switch is only in this row on the screen that MANAGES exits. The
        // interface and rule pickers share this list and offer no controls, so "here" pointed at nothing.
        : { refuse: T("{v1} is turned off. Switch it on first, then choose it.", { v1: label }) }),
      title: [live.address || "", x.device || "", on ? "" : T("Turned off"), notReady ? h.why : ""]
        .filter(Boolean).join(" · "),
      ...(String(armed || "") === String(x.id) && onRemove && x._ext
        ? { extra: confirmRow({ id: x.id, label, device: x.device || "" }),
            // While a row is asking, choosing it would answer a different question.
            refuse: T("Answer the question on this row first."), className: (on ? "" : "dim") + " arming" }
        // ⚠️ THE MARKER IS NOT PART OF THE ROW CONTROLS, even though it sits where they do. A picker that
        // only CHOOSES passes no `onToggle`/`onRename`/`onRemove` — and when the marker rode along with
        // them, those pickers dimmed a not-ready exit and refused it while showing nothing that said why.
        // Dimming without a reason is the shape this whole health model exists to end.
        : { extra: ctl(onRemove && x._ext ? rmBtn({ id: x.id, label, device: x.device || "" }) : null,
                       // ⚠️ `gw` RIDES ALONG OR THE FORM OPENS EMPTY AND SAVES THAT. The pencil seeds every
                       // field the form can edit; leaving the typed gateway out meant the operator opened a
                       // card that HAD one, saw a blank box, and any save wrote the blank back.
                       onRename && x._ext ? penBtn({ kind: "exit", id: x.id, device: x.device || "", title: x.label || "",
                                                     egress_ip: x.egress_ip || "", gw: x.gw || "" }) : null,
                       // The switch answers "may this be chosen?", and on a broken row that is not the
                       // question — turning it on would change nothing and reads as the fix. The marker
                       // takes its place and carries the reason.
                       notReady ? mark
                         : onToggle ? html`<${Switch} on=${on} onChange=${v => onToggle(x.id, v)}/>` : null) }),
    };
  };
  // ONE NAMER FOR BOTH GROUPS — `exitLabel`. Each used to spell a row its own way: imported rows read as a
  // bare `wgx-229f0c44` when untitled, adopted ones as a bare `wg-lab0`, and a pasted profile carried a
  // third shape ("Custom — <title> — <device>"). The same exit therefore read differently depending on
  // which list you opened it from, and an untitled one never said what it WAS.
  const warp = exits.filter(x => (x.producer || "adopted") === "imported").map(x => mk(x, exitLabel(x, node)));
  const ext = exits.filter(x => (x.producer || "adopted") !== "imported")
    .map(x => mk({ ...x, _ext: true }, exitLabel(x, node)));
  // ⚠️ AND EVERY DEVICE THE NODE ALREADY HAS. An exit record is the panel's bookkeeping, not the world:
  // the box may be running a TUN or a WireGuard client that nobody has told the panel about, and hiding
  // those behind "Custom interface…" made the operator TYPE the name of a device sitting in front of them
  // — the thing the node reports precisely so nobody has to. Offered here, chosen like any other row; the
  // record is minted on selection.
  //
  // `offerable` is the PANEL's verdict (exit_device_refusal), already stamped onto each candidate: a NIC,
  // a mesh link, an interface serving clients and a device one of our own exits already owns are all
  // reported by the node and all filtered out here, each for a reason the picker can name.
  // ⚠️ OPT-IN, because choosing one MINTS A RECORD and only some callers can do that. A candidate is a
  // device the node reports that the panel has no exit for yet; picking it is "create this exit and choose
  // it", which the node's own egress screen handles in its `onChange`. An interface editor or a rule row
  // cannot — they write their own field, not the node's exit list — so offering it there would be an option
  // that does nothing. The screens that manage exits ask for these; the screens that merely choose do not.
  const taken = new Set(exits.map(x => String(x.device || "")).filter(Boolean));
  for (const c of (devices ? ((node || {}).exit_candidates || []) : [])) {
    if (!c || !c.offerable || taken.has(String(c.name))) continue;
    ext.push({
      // Named like every other row: a candidate IS a discovered device, so it reads `Discovered — wg-lab0`
      // rather than a bare `wg-lab0` that says nothing about what it is or why it is in this group.
      value: prefix + "dev:" + c.name, label: exitLabel({ producer: "adopted", device: c.name }, node),
      title: [c.address || "", c.endpoint ? "→ " + c.endpoint : "", c.up ? "" : T("not up")].filter(Boolean).join(" · "),
      // ⚠️ THE SWITCH IS ON EVERY ROW OR IT MEANS NOTHING. A discovered device has no record yet, so it had
      // no switch — and a list where some rows carry one and some do not reads as a rendering fault rather
      // than as a difference. It shows ON, because a device the node reports and the panel does not refuse
      // IS available; switching it off is a decision, and a decision needs a record to live in, which is
      // what `onToggle` mints. Identical to choosing it, minus the choosing.
      // NO X. There is no record to remove — the device is on the box whether the panel likes it or not.
      extra: ctl(null, penBtn({ kind: "device", device: c.name, title: "", egress_ip: "" }),
                 onToggle ? html`<${Switch} on=${true} onChange=${v => onToggle("dev:" + c.name, v)}/>` : null),
    });
  }
  // LAST IN ITS OWN GROUP, and the group is rendered even with nothing else in it — on a node whose only
  // way out is a device nobody has named yet, an empty group is exactly where the operator should look.
  if (custom) ext.push({ value: custom, label: T("Custom interface…"),
    ...(onManage ? { extra: html`<button type="button" class="btn btn-mini ddmanage"
      onClick=${e => { e.stopPropagation(); onManage(); }}>${T("Manage…")}</button>` } : {}) });
  return [
    ...(warp.length ? [{ group: T("Exit via WARP"), items: warp }] : []),
    // "an external interface" stopped being true the moment a NIC could be one — the node's own card is
    // not external to it. The group is what traffic LEAVES BY, whichever kind of device that is.
    ...(ext.length ? [{ group: T("Leave by a device"), items: ext }] : []),
  ];
}

/** Is this WARP account a paid one? From the LICENCE (what was asked for) or the account Cloudflare reports
 *  (what was granted) — they arrive a sync apart, and either alone makes the answer flicker. */
export const exitIsPlus = ex => !!(String((ex || {}).licence || "").trim()
  || /plus/.test((((ex || {}).live) || {}).account_type || ""));

/** What KIND of exit this is, in the operator's own words — the name a row falls back to when it has no
 *  title. The five kinds the panel can produce, and the vocabulary each already had on the exits screen:
 *
 *    imported · warp            WARP exit          (a registered Cloudflare account)
 *    imported · warp · licence  WARP+ exit         (paid — the whole point of the row is knowing which)
 *    imported · profile         Custom exit        (a WireGuard profile the operator pasted)
 *    adopted  · node reports it Discovered         (a device already on the box)
 *    adopted  · it does not     Custom             (a name the operator typed ahead of the device)
 *
 *  ⚠️ The last two are told apart by the NODE'S OWN candidate list, not by a stored flag. A device the
 *  operator typed before the node reported it becomes Discovered the moment it appears — which is the
 *  truth about it, and a stored flag would have frozen the guess made at creation time. */
export function exitTypeLabel(ex, node) {
  const x = ex || {};
  if ((x.producer || "adopted") === "imported")
    return x.provider === "profile" ? T("Custom exit")
      : exitIsPlus(x) ? T("WARP+ exit") : T("WARP exit");
  // ⚠️ A NETWORK CARD SAYS SO, and this is the whole of decision B1 in one line. `Direct — source from
  // eth2` (a NAT pin) and an eth2 EXIT (a route) can now both be on screen at once, and they do completely
  // different things. Naming each by WHAT IT CHANGES is what keeps them apart: this half is the route, so
  // it names the thing traffic leaves by. Read from the node's own candidate list (`proto`), not guessed
  // from the name — the same source the refusal set uses, so the two cannot disagree about what a card is.
  const _cand = ((node || {}).exit_candidates || []).find(c => c && String(c.name) === String(x.device || ""));
  return _cand ? (_cand.proto === "nic" ? T("val|Network card") : T("val|Discovered")) : T("val|Custom");
}

/** ONE name for an exit, everywhere it is listed: `<title, or what kind it is> — <device>`.
 *
 *  Both halves, always. A titled row that hid its device made the operator open the pencil to answer "which
 *  interface is `TW` again?" — and the device is the half that has to match what they see in `ip link`. An
 *  untitled row used to render as the bare device (`wgx-229f0c44`), which says nothing about what it IS;
 *  now it says `WARP exit — wgx-229f0c44`. Every list shares this, so an exit cannot read one way in the
 *  node's default picker and another in an interface's. */
export function exitLabel(ex, node) {
  const x = ex || {};
  const dev = String(x.device || "").trim();
  const title = String(x.label || "").trim();
  // ⚠️ A TITLE THAT MERELY REPEATS THE DEVICE IS NOT A TITLE. `_validate_exits` falls the stored label back
  // to the device name, so plenty of untitled rows carry `label === device` — and rendering both halves gave
  // `wgx-f4256ea7 — wgx-f4256ea7`, which says the same thing twice and still never says what the exit IS.
  // Such a row is untitled, and the kind goes in front of the device instead.
  const name = (title && title !== dev) ? title : exitTypeLabel(x, node);
  return dev ? T("{v1} — {v2}", { v1: name, v2: dev }) : name;
}

/** One exit record off a node, or null — the shared lookup, so "which exit is this?" has one answer. */
export const exitOf = (node, id) => (((Store.nodes || []).find(n => n.id === node) || {}).exits || [])
  .find(x => String(x.id) === String(id)) || null;

export function ifTrafficBadge(mode, egNode, node, exitId) {
  if (mode === "forward" && egNode) return html`<span class="egb egb-fwd" style=${"color:" + Store.nodeColor(egNode)} title=${T("Cascade — exits via {v1}", { v1: Store.nodeName(egNode) })}><${Ic} i="cascade"/>${T("cascade →")} ${Store.nodeName(egNode)}</span>`;
  if (mode === "smart") return html`<span class="egb egb-smart" title=${T("Per-destination smart routing")}><${Ic} i="cascade"/>${T("smart cascade")}</span>`;
  if (mode === "forward") return html`<span class="egb egb-cascade"><${Ic} i="cascade"/>${T("tag|cascade")}</span>`;
  if (mode === "exit") {
    // Decision 5: badge the EXIT'S OWN LABEL. The provider is not the point — the same badge covers a WARP
    // tunnel, a pasted profile and an adopted wg0 — and a badge reading "WARP" over someone's `wg0` is worse
    // than no badge. A selection whose exit is gone still says so rather than reading `direct`, which is what
    // the fall-through below would have rendered: true of the packets, and a lie about the interface.
    const x = exitOf(node, exitId);
    if (!x)
      return html`<span class="egb egb-exit egb-gone" title=${T("The exit this interface was set to is gone — traffic goes out directly, and the interface keeps the selection")}><${Ic} i="device"/>${T("exit — removed")}</span>`;
    // DECISION 3 — degrade, never rewrite: an exit that is turned off, or whose device stopped being usable,
    // still routes NOTHING while the interface keeps the selection. The badge has to say so or it is the
    // most confident thing on the card and the only wrong one. Three signals rather than colour alone —
    // icon, tint and title — and the exit keeps its NAME (decision 5), because the operator needs to know
    // WHICH exit is not working, not merely that something is not.
    const degraded = x.enabled === false || !!x.why_not;
    return html`<span class=${"egb egb-exit" + (degraded ? " egb-gone" : "")}
      title=${degraded
        ? (x.enabled === false
            ? T("This exit is turned off — traffic goes out directly, and the interface keeps the selection")
            : T("This exit's device can't be used — traffic goes out directly, and the interface keeps the selection"))
        : T("Leaves this node through {v1}", { v1: x.device || x.label })}>
      <${Ic} i=${degraded ? "warn" : "device"}/>${T("exit →")} ${x.label || x.device}</span>`;
  }
  return html`<span class="egb egb-direct" title=${T("Exits directly from this node")}><${Ic} i="globe"/>${T("tag|direct")}</span>`;
}

// serialise an egress selection into the API body shape (shared by the interface and WDTT save paths)
export const egressBody = eg => eg.mode === "smart"
  ? { egress_mode: "smart", routing: rowsToRules(eg.rows, eg.catchAll) }
  // An exit carries an ID and nothing else — not a NIC and not a node. Sending the others alongside would
  // be harmless today (the server's ladder pops them) and a trap tomorrow, since a stale `wan_iface` riding
  // along is how a mode ends up meaning two things.
  : eg.mode === "exit" ? { egress_mode: "exit", exit_id: eg.exitId || "" }
  : { egress_mode: eg.mode === "auto" ? "direct" : eg.mode, egress_node: eg.node || "", egress_ip: eg.ip || "", wan_iface: eg.nic || "" };
