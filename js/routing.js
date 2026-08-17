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

import { T, Trich, Tsplit, plural, srvText } from "./i18n.js";
import { esc, seen, isSelfContainedIface } from "./util.js";
import { Store, api, bus, useStore } from "./store.js";
import { pickThemed } from "./theme.js";
import { Ic, Tag, Panel, Switch, Dropdown, Disclosure, autoGrow, Sheet, footRow, secTitle, SearchBox,
         Popover, Portal, toast, openModal, pushModal, closeModal, closeAllModals, openConfirm, goSettings,
         useReorder, GRIP_SVG, NodeIpPick } from "./ui.js";
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
  ["google", "Google"], ["youtube", "YouTube"], ["telegram", "Telegram"], ["netflix", "Netflix"],
  ["meta", "Meta (FB / IG / WA)"], ["twitter", "X (Twitter)"], ["tiktok", "TikTok"], ["discord", "Discord"],
  ["yandex", "Yandex"], ["vk", "VK"], ["openai", "ChatGPT (OpenAI)"], ["claude", "Claude (Anthropic)"],
  ["grok", "Grok (xAI)"], ["gemini", T("Gemini (Google AI)")], ["copilot", T("Microsoft Copilot")], ["signal", "Signal"],
  ["spotify", "Spotify"], ["twitch", "Twitch"], ["disney", "Disney+"], ["reddit", "Reddit"], ["github", "GitHub"],
  ["ru_net", T("Russia — all IPs")], ["ru_gov", "Russia — Government"], ["ru_banks", "Russia — Banks"],
  ["ru_blocked", "Russia — Blocked (all)"], ["ru_blocked_media", "Russia — Blocked (media)"],
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
  meta: "Meta / Facebook", facebook: "Meta / Facebook", openai: "ChatGPT / OpenAI", twitter: "Twitter / X",
  xai: "Grok / xAI", grok: "Grok / xAI", anthropic: "Claude / Anthropic", claude: "Claude / Anthropic",
  gemini: T("Gemini (Google AI)"), perplexity: T("Perplexity AI"), deepseek: "DeepSeek", copilot: T("Microsoft Copilot"),
  google: "Google", youtube: "YouTube", netflix: "Netflix", telegram: "Telegram", whatsapp: "WhatsApp",
  instagram: "Instagram", tiktok: "TikTok", github: "GitHub", disney: "Disney+", spotify: "Spotify",
  twitch: "Twitch", reddit: "Reddit", discord: "Discord", vk: "VK", yandex: "Yandex", cloudflare: "Cloudflare",
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
  netflix: T("Netflix streaming & app"), meta: "Facebook, Instagram & WhatsApp", facebook: "Facebook, Instagram & WhatsApp",
  telegram: T("Telegram messenger"), whatsapp: T("WhatsApp messenger"), instagram: "Instagram", twitter: "Twitter / X",
  openai: T("ChatGPT & the OpenAI API"), tiktok: T("TikTok video"), github: T("GitHub & its CDN"), disney: "Disney+ streaming",
  spotify: T("Spotify audio"), twitch: T("Twitch live streaming"), reddit: "Reddit", discord: T("Discord voice & chat"),
  cloudflare: T("Cloudflare CDN / edge network"), vk: "VKontakte", yandex: T("Yandex services"),
  ru_gov: T("Russian government sites"), ru_banks: T("Russian banks"), ru_social: T("Russian social (VK / OK)"),
  claude: T("Claude & the Anthropic API"), grok: "Grok (xAI) — grok.com & x.ai",
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
// Custom-list caps + size from its targets (domains → Host, IPs/CIDRs → IP). Accepts a targets string or a list obj.
export const customTargets = l => (typeof l === "string") ? l : (l && (l.targets ?? [...(l.domains || []), ...(l.cidrs || [])].join(", "))) || "";
export function customCaps(l) { const raw = customTargets(l); const doms = domainTargets(raw), ips = splitTargets(raw).filter(isIpTarget);
  return { host: doms.length > 0, ip: ips.length > 0 }; }
// Record count for a provider-catalog cat (Host+IP tiers), shipped by the panel in Store.catSizes {cat:{ip,host}}.
export const fmtCount = n => n == null ? "…" : n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "") + "k" : String(n);
// "142 hosts · 38 nets" style summary from per-tier counts (Host first). Empty string when nothing is known.
export function sizeSummary(host, ip) {
  const p = [];
  if (host) p.push(fmtCount(host) + (host === 1 ? " host" : " hosts"));
  if (ip) p.push(fmtCount(ip) + (ip === 1 ? " net" : " nets"));
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
  if (list) { const raw = customTargets(list); hostN = domainTargets(raw).length; ipN = splitTargets(raw).filter(isIpTarget).length; }
  else if (cat) { const s = (Store.catSizes || {})[cat] || {}; hostN = s.host; ipN = s.ip; }
  const summary = sizeSummary(hostN || 0, ipN || 0);
  if (!summary) return null;
  return html`<span class="listsize">${summary}</span>`;
}

// A rich catalog-browse row (the "Add from catalog" list): title + the raw id (name) dimmed under it, the
// provider tag, a description (curated, else a live sample of records), "N hosts · M nets", and Host/IP tags.
// Eager-loads /api/list-info (session-cached) for the counts + samples. Providers ship no descriptions, so the
// second line falls back to "e.g. <first few records>" — self-explanatory from the list's own contents.
export function CatalogRow({ it, added, onPick }) {
  const [info, setInfo] = useState(() => _LIST_INFO_CACHE[it.id] || null);
  useEffect(() => {   // one synchronous (server-side, retried) fetch → counts + samples; caches so paging is instant
    if (info) return; let live = true;
    api.listInfo(it.id).then(r => { const d = r && r.ok ? r.data : { err: true }; _LIST_INFO_CACHE[it.id] = d; if (live) setInfo(d); })
      .catch(() => live && setInfo({ err: true }));
    return () => { live = false; }; }, [it.id]);
  const title = prettyCatLabel(it.id, it.label), rid = catRawId(it.id), desc = catDescOf(it.id);
  const hostD = info && info.tiers && info.tiers.host, ipD = info && info.tiers && info.tiers.ip;
  const summary = sizeSummary((hostD && hostD.n) || 0, (ipD && ipD.n) || 0);
  const samples = ((hostD && hostD.sample) || (ipD && ipD.sample) || []).slice(0, 4);
  const more = (((hostD && hostD.n) || (ipD && ipD.n) || 0) > samples.length);
  const anyFailed = info && info.tiers && Object.keys(info.tiers).some(t => info.tiers[t].failed);
  const empty = info && !info.err && !summary && !samples.length && !anyFailed;   // resolved to 0 routable records
  const sub = desc || (samples.length ? "e.g. " + samples.join(", ") + (more ? "…" : "")
    : (!info ? T("loading…") : anyFailed ? T("couldn't load — will retry") : empty ? T("no routable records") : "—"));
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
  return ((Store.catalogProviders || []).find(p => p.id === pid) || {}).label || (pid === "curated" ? "Curated" : pid);
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
  const prov = providerOf(id);
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
function buildModeMeta() { return {
  kernel:   { icon: "globe",  label: T("Default routing"), short: T("IP only"), tag: T("no host layer"),
    adds: T("Just the always-on IP layer — no domain matching added"),
    bene: [T("Simplest & most robust · never touches DNS · carries all traffic (calls, UDP, QUIC)")],
    cost: T("Can't separate services that share IPs (YouTube vs Google), no Host routing"),
    block: { s: "−", t: T("Blocks by IP / threat-feed only — domain content filters can't apply") },
    exp: T("Matches by destination IP (GeoIP / ASN) — routing never depends on DNS, so your clients' DoH, DoT and plain DNS all keep working untouched. Simplest and most robust; it just can't separate services that share IPs (YouTube vs Google), and a CDN category catches everything behind it."),
    lists: ["GeoIP", T("Custom IPs / ASNs")] },
  forcedns: { icon: "compass", label: T("Force-DNS"), short: T("Host via DNS"), tag: T("host layer · via DNS"),
    adds: T("Adds domain matching by resolving your clients' DNS through the node"),
    bene: [T("Per-service precise · fills before the first connection (no first-hit miss)")],
    cost: T("Intercepts & downgrades client DNS — blocks their DoH / DoT"),
    block: [{ s: "+", t: T("Enforces domain content filters directly") },
            { s: "−", t: T("Long block lists cost CPU per DNS query — keep them small (≈100k domains)") }],
    exp: T("The node becomes your clients' resolver and blocks their encrypted DNS — both DoH (known providers) and all DoT — so it can route by hostname too, per-service precise. Trade-off: it sees and downgrades the client's DNS, can break a client that insists on its own encrypted DNS, and a DoH server it doesn't recognise can still slip past."),
    lists: ["GeoSite", "GeoIP", T("Custom IPs/Domains/ASNs")] },
  sni_kernel: { icon: "cpu", label: T("Kernel SNI"), short: T("Host via SNI"), tag: T("host layer · SNI in-kernel"),
    adds: T("Scans the TLS SNI in-kernel — client DNS stays private"),
    bene: [T("Daemonless & parallel per-CPU · lightest at high connection rates"), T("Wins stability and high-connection-rate CPU over Hybrid")],
    cost: T("Substring match only · needs xt_string + ipset on the node"),
    block: { s: "−", t: T("Domain content filters inert — steer them to Force-DNS / Hybrid") },
    exp: T("Scans the SNI from each TLS handshake entirely in the kernel (xt_string) and learns each destination's IP into the routing set — no userspace helper, and your clients' DNS (DoH, DoT or plain) is never touched. Runs in parallel across CPUs, so it stays light even at high connection rates. Matches by substring only and needs the node's kernel to provide xt_string + ipset. Names hidden by ECH, and QUIC / HTTP3, fall back to IP routing."),
    lists: ["GeoSite", "GeoIP", T("Custom IPs/Domains/ASNs")] },
  sni:      { icon: "eye", label: T("Hybrid SNI"), short: T("Host via SNI"), tag: T("host layer · SNI in userspace"),
    adds: T("Parses the TLS SNI in a small helper — client DNS stays private"),
    bene: [T("Precise parsed-SNI matching · unbothered by big lists"), T("Has fewer kernel deps, wins accuracy over Kernel")],
    cost: T("Runs a helper process (fails open — learning pauses — if it stops)"),
    block: { s: "+", t: T("Enforces domain content filters — learns & drops; best for large block lists") },
    exp: T("Routes by hostname by parsing the SNI from each TLS handshake in a small userspace helper, so your clients' DNS — DoH, DoT or plain — is never touched, observed or downgraded: the connection stays encrypted end-to-end. Parses the real SNI field (precise, fine with very large lists). Learns each destination on its first connection (a brand-new host routes on the next one); names hidden by ECH, and QUIC / HTTP3, fall back to IP routing."),
    lists: ["GeoSite", "GeoIP", T("Custom IPs/Domains/ASNs")] },
}; }
let _modeMeta = null;
/* "IP-only mode — a.com, b.com are domains. Use IPs/CIDRs, or <switch this node to Force-DNS>." The tail is a
   BUTTON, and English needs two forms for one-vs-many. Two keys, each split around the button. */
function ipOnlyLint(domToks, onSwitch) {
  const list = domToks.slice(0, 3).join(", ") + (domToks.length > 3 ? "…" : "");
  // Tsplit's key must be a LITERAL — a ternary inside the call is invisible to the audit, which then
  // reports both translations as orphaned. Choose the call, not the string.
  const [a, b] = domToks.length > 1
    ? Tsplit("IP-only mode — {toks} are domains. Use IPs/CIDRs, or {switch}.", "switch", { toks: list })
    : Tsplit("IP-only mode — {toks} is a domain. Use IPs/CIDRs, or {switch}.", "switch", { toks: list });
  return html`<${Fragment}>${a}<button type="button" class="linkbtn" onClick=${onSwitch}>${T("switch this node to Force-DNS")}</button>${b}<//>`;
}
/* "…turn them on in <Settings ▸ Routing & Blocking>." — the tail is a button. */
function noFilterCats(onNav) {
  const [a, b] = Tsplit("No content-filter categories are enabled on this node yet — turn them on in {where}.", "where");
  return html`<${Fragment}>${a}<button type="button" class="linkbtn" onClick=${onNav}>${T("Settings ▸ Routing & Blocking")}</button>${b}<//>`;
}
/* "Type <RESET LEARNED> or <RESET ALL> to confirm your action" — two coloured literals. */
function resetPrompt() {
  const one = T("Type {learn} or {all} to confirm your action");
  const [a, r1] = [one.split("{learn}")[0], one.split("{learn}").slice(1).join("{learn}")];
  const [b, c] = [r1.split("{all}")[0], r1.split("{all}").slice(1).join("{all}")];
  return html`<${Fragment}>${a}<b class="ct-learn">RESET LEARNED</b>${b}<b class="ct-all">RESET ALL</b>${c}<//>`;
}

export const MODE_META = new Proxy({}, { get: (_, k) => (_modeMeta || (_modeMeta = buildModeMeta()))[k] });

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
  const learnOk = t === "RESET LEARNED", allOk = t === "RESET ALL";
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
      <input class="ctype-input" type="text" autofocus spellcheck="false" autocomplete="off" placeholder=${T("RESET LEARNED / RESET ALL")} value=${typed}
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
  if (routed || (eng.startsWith("sni") && sr.resets)) {
    const bits = [];
    if (routed) bits.push(T("{v1} routed", { v1: plural(routed, "destination").replace(String(routed), fmtCount(routed)) }));
    if (eng.startsWith("sni") && sr.resets) bits.push(T("{v1} rerouted", { v1: plural(sr.resets, "new host") }));
    extra = bits.join(" · ");
  }
  if (mode === "sni_kernel" && eng === "sni_user") note = T("kernel SNI scanner unavailable — running userspace SNI parser");   // degraded-open
  return html`<div class=${"rmode-health " + (ok ? "ok" : "down")}>
    <span class="rmh-dot"></span><b>${label}</b> <span>${ok ? "healthy" : T("down — host routing degraded")}</span>
    ${extra ? html`<span class="rmh-sep">·</span><span>${extra}</span>
      ${onLearn ? html`<button class=${"learn-toggle" + (learn ? " on" : "")} title=${T("IP learning is {v1} · click to turn it {v2}", { v1: learn ? T("ON — the node remembers each learned IP") : T("OFF — routing stays fresh, no remembered IPs"), v2: learn ? T("val|off") : T("val|on") })} onClick=${() => onLearn(!learn)}><${Ic} i="database"/></button>` : null}
      <${Popover} hoverOnly cls="rmh-info" popCls="rmode-info-pop" trigger=${html`<span class="rmh-infobtn"><${Ic} i="info"/></span>`}>
        <div class="rmode-info-body">${Trich("A host's name is only visible once its connection starts, so the *first* connection to a brand-new host has already left on the default path before it can be routed. The engine learns that host's IP and *resets that one connection* so the client instantly reconnects on the correct route — that's the *new hosts rerouted* count; every later connection matches by IP and is never reset.")}<div style="margin-top:9px">${Trich("The *records* toggle (the database icon) controls *IP learning*. Each IP is remembered by *category* (not by domain), so it stays valid even if you later change that category's lists or custom domains. Nothing is kept forever: *On* (default) holds a learned IP for about *1 hour*, so repeat connections route instantly. *Off* keeps the node *fresh* — an IP is held only about *2 minutes*, so a host whose address rotates is never routed on a stale IP (at a little extra CPU, as more connections are re-scanned). Once it expires, the IP is simply re-learned on the next connection.")}</div></div>
      <//>` : null}
    ${note ? html`<span class="rmh-note">${note}</span>` : null}
  </div>`;
}
// "on N/M nodes ▾" fleet-assignment popover — toggle a list on each node. disabledFor(nid) → a reason string greys it.
export function FleetAssign({ nodes, isOn, onToggle, disabledFor }) {
  const on = (nodes || []).filter(n => isOn(n.id)).length;
  return html`<${Popover} cls="fleetassign" popCls="fleetpop"
    trigger=${html`<span class="fleet-trig">on <b>${on}</b>/${(nodes || []).length} <span class="fleet-caret">▾</span></span>`}
    children=${html`<div class="fleetlist"><div class="fleetlist-h">${T("Enabled on")}</div>${(nodes || []).map(n => { const dis = disabledFor && disabledFor(n.id);
      return html`<div class=${"fleetrow" + (dis ? " off" : "")} title=${dis || ""}>
        <span class="fleet-dot" style=${"--c:" + Store.nodeColor(n.id)}></span><span class="fleet-nm">${n.name}</span><span class="grow"></span>
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
// hover bubble listing a list's domains/IPs (only when there are some); `note` = a faint footer caption
let _ruleSeq = 0;
export const newRid = () => "rr" + (++_ruleSeq);


// The full catalog index, fetched once and searched CLIENT-side — so search matches the readable title
// (country names, friendly names) and descriptions, not just the raw provider id. ~3.5k tiny rows.
let _CATALOG_INDEX = null;
export function loadCatalogIndex() {
  if (_CATALOG_INDEX) return Promise.resolve(_CATALOG_INDEX);
  return api.catalogIndex().then(r => {
    if (r && r.ok) { const pl = r.data.provider_labels || {};
      _CATALOG_INDEX = (r.data.items || []).map(it => ({ ...it, provider_label: pl[it.provider] || it.provider })); }
    return _CATALOG_INDEX || [];
  }).catch(() => []);
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
    : (SMART_CAT_LABEL[value] || (listTitle || {})[value] || (Store.catLabels || {})[value] || value || "Choose a category…");
  const usable = caps => routeCapsUsable(mode, caps);   // shared routing rule: IP everywhere, domain needs a host layer (non-IP-only)
  const place = () => { const el = ref.current; if (!el) return; const r = el.getBoundingClientRect();
    const below = window.innerHeight - r.bottom - 12, above = r.top - 12;
    if (addMode) {   // the catalog browser spans the FULL card width (grid-wide), anchored under its header row
      const card = el.closest(".card") || el.closest(".setpane");
      const cr = card ? card.getBoundingClientRect() : r; const pad = 18;
      const flip = below < 360 && above > below;
      setPos({ left: Math.round(cr.left + pad), top: Math.round(flip ? r.top - 4 : r.bottom + 6),
        width: Math.round(cr.width - pad * 2), flip, wide: true, maxh: Math.max(300, Math.round(flip ? above : below)) });
      return;
    }
    const flip = below < 300 && above > below;                 // not enough room under the trigger → open upward
    setPos({ left: Math.round(r.left), top: Math.round(flip ? r.top - 4 : r.bottom + 4), width: Math.round(r.width),
      flip, maxh: Math.max(200, Math.round(flip ? above : below)) }); };   // list caps to the space actually available
  useEffect(() => {   // addMode: load the full index ONCE, then search/paginate locally (matches title + id + description)
    if (open && addMode && !cidx) { let live = true; loadCatalogIndex().then(x => live && setCidx(x)); return () => { live = false; }; }
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
    .map(([id, label]) => ({ id, provider: "curated", provider_label: "Curated", caps: catCap(id), recommended: true, disp: label })) : [];
  const curatedFiltered = _curatedAll.filter(it => !_aq || it.id.toLowerCase().includes(_aq)
    || it.disp.toLowerCase().includes(_aq) || catDescOf(it.id).toLowerCase().includes(_aq))
    .sort((a, b) => a.disp.toLowerCase().localeCompare(b.disp.toLowerCase()));
  const filtered = addMode && cidx ? cidx.filter(it => { if (!_aq) return true;
    return it.id.toLowerCase().includes(_aq) || catRawId(it.id).toLowerCase().includes(_aq)
      || prettyCatLabel(it.id, "").toLowerCase().includes(_aq) || catDescOf(it.id).toLowerCase().includes(_aq); })
    .map(it => ({ ...it, disp: prettyCatLabel(it.id, "") })).sort((a, b) => a.disp.toLowerCase().localeCompare(b.disp.toLowerCase())) : [];
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
    _provRows.push({ id: value, label: catLabelOf(value), caps: catCap(value), src: provLabelOf(value) || "Curated" });   // keep a curated/legacy rule visible + editable, tagged by its provider
  const localGroups = addMode ? [] : [
    { grp: T("Provider lists"), rows: _provRows.filter(r => _match(r.id, r.label)).sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase())) },
    { grp: T("Custom lists"), rows: lists.filter(l => _match(l.id, l.title)).map(l => ({ id: l.id, label: l.title, caps: customCaps(l), src: "Custom", list: l })).sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase())) },
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
              <span class="catpick-rlbl">${it.label}${it.src ? html`<${ProvTag} id=${it.id} label=${it.src} plain=${it.legacy || it.src === "Custom"}/>` : null}</span>
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

// One smart-routing rule row: a category → a destination (exit node / direct / block). Reuses the
// drag-reorder hook; order is priority (first match wins on the node).
export function RoutingRules({ node, rules, onChange }) {
  const others = (Store.nodes || []).filter(n => n.id !== node);
  const _ps = Store.panelSettings || {};
  const _nrec = (Store.nodes || []).find(n => n.id === node);   // built-in categories enabled for THIS node (null/[] = all)
  const _mode = (_nrec && _nrec.routing_mode) || "kernel";        // host-only cats are unusable in kernel mode → drop them from the dropdown
  const customLists = (_ps.custom_lists || []).filter(l => !(l.disabled_nodes || []).includes(node));   // per-node: hide lists the operator disabled on THIS node
  const catalogCats = (_nrec && _nrec.catalog_cats || []).map(id => ({ id, title: catLabelOf(id) }));   // provider-catalog cats opted into this node → the Provider lists section
  const listTitle = Object.fromEntries([...(_ps.custom_lists || []).map(l => [l.id, l.title]), ...catalogCats.map(c => [c.id, c.title])]);
  const catLabel = c => c === "custom" ? T("Custom IPs / domains") : (SMART_CAT_LABEL[c] || listTitle[c] || c);
  const allRule = rules.find(r => r.category === "all");          // the catch-all ("everything else") → footer dropdown
  const dispRules = rules.filter(r => r.category !== "all");
  const emit = drules => onChange(allRule ? [...drules, allRule] : drules);   // catch-all is always kept LAST (first-match)
  const rs = useReorder(dispRules.map(r => r._rid), ids => emit(ids.map(id => dispRules.find(r => r._rid === id)).filter(Boolean)), "y", { container: ".rrlist", card: ".rrrow" });
  const setRule = (rid, patch) => emit(dispRules.map(r => r._rid === rid ? { ...r, ...patch } : r));
  const addRule = () => emit([...dispRules, { _rid: newRid(), enabled: true, category: "custom", action: others[0] ? "exit" : "direct", node: (others[0] || {}).id || "" }]);
  const destVal = r => r.action === "exit" ? "exit|" + (r.node || "") : r.action;
  const onDest = (rid, v) => { const [a, n] = v.split("|"); setRule(rid, a === "exit" ? { action: "exit", node: n } : { action: a, node: "" }); };
  // auto-mode: a domain rule can't match in kernel mode — offer a one-click switch of THIS node to Force-DNS instead of a dead-end
  const switchToForceDns = async () => {
    if (!confirm(T("Switch {v1} to Force-DNS mode?\n\nThis reprovisions the node (adds its DNS resolver) so domain rules can match. IP rules keep working. Save your rule changes afterwards.", { v1: _nrec ? _nrec.name : T("this node") }))) return;
    const r = await api.nodeUpdate({ id: node, routing_mode: "forcedns" });
    if (!r || !r.ok) return toast(srvText(r) || T("Couldn't switch mode"), "err");
    await Store.poll();
    toast(T("Switched to Force-DNS — domain rules now match. Save to apply."), "ok");
  };
  const catchVal = !allRule ? "direct" : allRule.action === "exit" ? "exit|" + (allRule.node || "") : allRule.action;   // "exit|<n>" | "block" | "direct" (default = no stored catch-all)
  const setCatch = v => { const [a, n] = v.split("|");
    onChange(a === "exit" && n ? [...dispRules, { _rid: newRid(), enabled: true, category: "all", action: "exit", node: n }]
      : a === "block" ? [...dispRules, { _rid: newRid(), enabled: true, category: "all", action: "block" }]
      : dispRules); };   // "direct" is the implicit default → no stored rule
  const seen = {};
  return html`<div class="field"><label>${T("Routing rules")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— first match wins")}</span></label>
    <div class="rrlist" ...${rs.container()}>${dispRules.map(r => {
      const ckey = r.category === "custom" ? "custom:" + (r.targets || "") : r.category;
      const dup = seen[ckey]; seen[ckey] = true;
      const self = r.action === "exit" && r.node === node;
      const badToks = r.category === "custom" ? invalidTargets(r.targets || "") : [];
      const ipOnly = _mode === "kernel";                       // kernel matches by dest IP only — no hostname routing
      const domToks = (ipOnly && r.category === "custom") ? domainTargets(r.targets || "") : [];   // domains a kernel node can't match
      const it = rs.item(r._rid);
      return html`<div key=${r._rid} class=${"rrrow" + it.cls + ((dup || self || badToks.length || domToks.length) ? " warn" : "")} data-rid=${it.rid}>
        <span class="drag-grip" title=${T("Drag to reorder")} ...${rs.grip(r._rid)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span>
        <${CatPicker} value=${r.category} mode=${_mode} customLists=${customLists} catalogCats=${catalogCats} listTitle=${listTitle}
          onChange=${v => setRule(r._rid, { category: v })}/>
        <span class="rrarrow">→</span>
        <select class="selwrap" value=${destVal(r)} onChange=${e => onDest(r._rid, e.target.value)}>
          <option value="direct">${T("Direct (this node)")}</option>
          <option value="block">${T("Block")}</option>
          ${others.length ? html`<optgroup label=${T("Exit via node")}>${others.map(n => html`<option value=${"exit|" + n.id}>→ ${n.name}</option>`)}</optgroup>` : null}
        </select>
        <button class="xbtn" title=${T("Remove rule")} onClick=${() => emit(dispRules.filter(x => x._rid !== r._rid))}><${Ic} i="x"/></button>
        ${self ? html`<span class="rrlint">${T("can't exit via itself")}</span>` : dup ? html`<span class="rrlint">${T("shadowed by an earlier {cat} rule", { cat: catLabel(r.category) })}</span>` : null}
        ${r.category === "custom" ? html`<textarea class="rrdoms" rows="1" spellcheck="false" placeholder=${ipOnly ? T("IPs / CIDRs / AS numbers (IP-only mode) — e.g. 1.2.3.0/24, AS62041") : T("IPs / domains / AS numbers — e.g. youtube.com, 1.2.3.0/24, AS62041")} value=${r.targets || ""} onInput=${e => { autoGrow(e.target); setRule(r._rid, { targets: e.target.value }); }} ref=${el => autoGrow(el)}/>${!splitTargets(r.targets || "").length ? html`<span class="rrlint">${ipOnly ? T("add at least one IP or CIDR") : T("add at least one IP or domain")}</span>` : badToks.length ? html`<span class="rrlint">${T("not a valid IP, CIDR or domain: {toks}", { toks: badToks.join(", ") })}</span>` : domToks.length ? html`<span class="rrlint">${ipOnlyLint(domToks, switchToForceDns)}</span>` : null}` : null}
        ${r.category === "custom" ? html`<${AsnHint} targets=${r.targets}/>` : null}
      </div>`;
    })}</div>
    <div class="rrfoot">
      <span class="rrfoot-lead"><button class="btn btn-mini" onClick=${addRule}><${Ic} i="plus"/> ${T("Add rule")}</button><b class="rrfoot-label">${T("Everything else")}</b></span>
      <span class="rrarrow">→</span>
      <select class="selwrap rrcatch" value=${catchVal} onChange=${e => setCatch(e.target.value)}>
        <option value="direct">${T("Direct (this node)")}</option>
        ${others.map(n => html`<option value=${"exit|" + n.id}>→ ${n.name}</option>`)}
        <option value="block">${T("Block")}</option>
      </select>
      <button class="xbtn rrfoot-gear" title=${T("Manage routing lists in Settings → Routing lists")} onClick=${() => goSettings("routing")}><${Ic} i="gear"/></button>
    </div>
    ${dispRules.length || allRule ? null : html`<div class="hint">${Trich("No rules yet. Add a rule to send a category through another node, or set *Everything else* to channel everything.")}</div>`}
  </div>`;
}

// custom-rule target validation — mirrors the backend _split_targets / _clean_targets exactly, so the UI
// rejects anything the node would silently drop. A token is valid if it's an IPv4 (optionally /0-32) or a
// domain (after stripping scheme/path and a leading "*."). Leading-dot / single-label names are invalid.
const _RR_IP4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(\/\d{1,2})?$/;
const _RR_ASN = /^as:?\d{1,10}$/i;                  // AS<n> / AS:<n> — the panel resolves it to the ASN's IPv4 prefixes
const _RR_LABEL = /^(?!-)[a-z0-9-]{1,63}(?<!-)$/;   // one DNS label
export const splitTargets = raw => String(raw || "").split(/[\s,]+/).filter(Boolean);
export function validTarget(tok) {
  const t = String(tok).trim().toLowerCase(); if (!t) return false;
  if (_RR_ASN.test(t)) return true;                 // AS<n> → resolved to CIDRs on the panel (counts as an IP target)
  // a bare IPv4 or IPv4/CIDR — all four octets ≤255, prefix 0-32 (rejects "22.1", "22.11.5/4343", "1.1.1.1/", "1.1.1.1/555")
  const mi = t.match(_RR_IP4);
  if (mi) return [1, 2, 3, 4].every(i => +mi[i] <= 255) && (!mi[5] || +mi[5].slice(1) <= 32);
  // otherwise a real domain: strip scheme + path + a leading "*."; need ≥2 labels, each a valid DNS label,
  // and an ALPHABETIC TLD (so "22.1", "1.1.1.1", "1.1.1.1/555"→"1.1.1.1" all fail — a bare number is never a host)
  let d = t.replace(/^https?:\/\//, "").split("/")[0];
  if (d.startsWith("*.")) d = d.slice(2);
  if (/[^\x00-\x7f]/.test(d)) { try { d = new URL("http://" + d).hostname; } catch { return false; } }   // IDN (Cyrillic etc.) → punycode, so it validates + matches the node's ASCII rules
  if (!d || d.length > 253) return false;
  const labels = d.split(".");
  return labels.length >= 2 && labels.every(l => _RR_LABEL.test(l)) && /^([a-z]{2,}|xn--[a-z0-9-]+)$/.test(labels[labels.length - 1]);
}
export const invalidTargets = raw => splitTargets(raw).filter(t => !validTarget(t));
export const isIpTarget = tok => { const t = String(tok).trim().toLowerCase(); if (_RR_ASN.test(t)) return true; const m = t.match(_RR_IP4); return !!m && [1, 2, 3, 4].every(i => +m[i] <= 255) && (!m[5] || +m[5].slice(1) <= 32); };   // AS<n> resolves to IPs → an IP target
export const domainTargets = raw => splitTargets(raw).filter(t => validTarget(t) && !isIpTarget(t));   // real hostnames among the valid tokens (kernel mode can't match these)
// Live feedback for AS<n> tokens in a rule/list: shows "AS62041 → 5 prefixes" (or "not found") so the operator knows
// the ASN resolved. Counts are cached module-wide (keyed by AS number) so switching rows never re-fetches.
const _asnCache = {};
export function AsnHint({ targets }) {
  const asns = [...new Set((String(targets || "").match(/\bas:?\d{1,10}\b/gi) || []).map(t => t.replace(/^as:?/i, "")))];
  const [, force] = useState(0);
  useEffect(() => {
    let alive = true;
    asns.forEach(n => { if (_asnCache[n] === undefined) { _asnCache[n] = "loading";
      api.asnCount(n).then(r => { _asnCache[n] = (r && r.ok && r.data) ? r.data : { count: 0 }; if (alive) force(x => x + 1); }); } });
    return () => { alive = false; };
  }, [asns.join(",")]);
  if (!asns.length) return null;
  return html`<div class="asn-hint">${asns.map(n => { const c = _asnCache[n]; const load = c === "loading" || c === undefined;
    const cnt = (c && typeof c === "object") ? c.count : 0;
    return html`<span class=${"asn-tok " + (load ? "load" : cnt ? "ok" : "bad")}>AS${n} ${load ? T("resolving…") : cnt ? T("→ {v1}", { v1: plural(cnt, "prefix") }) : T("→ not found")}</span>`; })}</div>`;
}

// ── egress: where an interface's traffic actually leaves the node ────────────────────────────────
export function EgressPicker({ node, value, onChange, noRules }) {
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const ipIfaces = nrec.ip_ifaces || [];
  // Egress = a PHYSICAL exit NIC. Drop panel-managed tunnels — self-contained servers (WDTT + csqtt raw-TUN) and
  // mesh links — they're the INBOUND datapath, never a place to egress out of (and never the instance's own iface).
  const nics = [...new Set(ipIfaces.map(p => p.iface))].filter(n => !isSelfContainedIface(n) && !n.startsWith("swg_"));
  const others = (Store.nodes || []).filter(n => n.id !== node);
  const ifSel = value.mode === "smart" ? "smart" : value.mode === "forward" ? "forward|" + (value.node || "") : value.mode === "direct" ? "direct|" + (value.nic || "") : "auto";
  let ipOpts = [];
  if (value.mode === "direct") ipOpts = ipIfaces.filter(p => !value.nic || p.iface === value.nic).map(p => p.ip);
  else if (value.mode === "forward") { const tn = others.find(n => n.id === value.node); ipOpts = (tn && tn.ips) || []; }
  const onIf = e => {
    const v = e.target.value;
    if (v === "auto") return onChange({ mode: "auto", nic: "", node: "", ip: "", rules: value.rules || [] });
    if (v === "smart") return onChange({ mode: "smart", nic: "", node: "", ip: "", rules: value.rules || [] });
    const [mode, x] = v.split("|");
    onChange(mode === "forward" ? { mode, node: x, nic: "", ip: "", rules: value.rules || [] } : { mode, nic: x, node: "", ip: "", rules: value.rules || [] });
  };
  return html`<${Fragment}>
    <div class="field"><label>${T("Outbound (egress) interface")}</label>
      <select class="selwrap" value=${ifSel} onChange=${onIf}>
        <option value="auto">${T("Auto (MASQUERADE)")}</option>
        ${nics.map(n => html`<option value=${"direct|" + n}>${T("Direct — {v1}", { v1: n })}</option>`)}
        ${others.length ? html`<optgroup label=${T("Forward to node (cascade)")}>${others.map(n => html`<option value=${"forward|" + n.id}>${T("Forward to {node}", { node: n.name })}</option>`)}</optgroup>` : null}
        ${others.length ? html`<option value="smart">${T("Smart routing (by destination)")}</option>` : null}
      </select>
      <div class="hint">${T("Exit directly out a NIC, channel everything through another node, or route per-destination (smart).")}</div></div>
    ${value.mode === "smart"
      ? (noRules ? null : html`<${RoutingRules} node=${node} rules=${value.rules || []} onChange=${rs => onChange({ ...value, rules: rs })}/>`)
      : value.mode !== "auto" ? html`<div class="field"><label>${T("Outbound (egress) IP")}</label>
      <${NodeIpPick} ips=${ipOpts} value=${value.ip || ""} onChange=${ip => onChange({ ...value, ip })} auto=${value.mode === "forward" ? T("Auto (target node default)") : "Auto"}/>
      <div class="hint">${value.mode === "forward" ? T("Source IP on the target node that clients egress from.") : T("Source IP clients egress from.")}</div></div>` : null}
  <//>`;
}

export const egressInit = m => ({ mode: m.egress_mode === "smart" ? "smart" : m.egress_mode === "forward" ? "forward" : (m.egress_ip || m.wan_iface) ? "direct" : "auto",
  nic: m.wan_iface || "", node: m.egress_node || "", ip: m.egress_ip || "",
  rules: (m.routing || []).map(r => ({ ...r, _rid: newRid(), ...(r.category === "custom" ? { targets: [...(r.domains || []), ...(r.cidrs || [])].join(", ") } : {}) })) });

// null when the egress config is savable; otherwise a message the sheets show + disable Save on. `mode` = the node's
// routing_mode: in kernel (IP-only) a custom rule can't use domains — only Force-DNS matches by hostname.
export function egressError(eg, mode) {
  if (!eg || eg.mode !== "smart") return null;
  for (const r of (eg.rules || [])) {
    if (r.category !== "custom") continue;
    const toks = splitTargets(r.targets || "");
    if (!toks.length) return T("A custom rule needs at least one IP or domain.");
    const bad = toks.filter(t => !validTarget(t));
    if (bad.length) {
      const list = bad.slice(0, 4).join(", ") + (bad.length > 4 ? "…" : "");
      return bad.length > 1 ? T("Invalid targets: {list}", { list }) : T("Invalid target: {list}", { list });
    }
    if (mode === "kernel") {
      const doms = domainTargets(r.targets || "");
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
export function ifTrafficBadge(mode, egNode) {
  if (mode === "forward" && egNode) return html`<span class="egb egb-fwd" style=${"color:" + Store.nodeColor(egNode)} title=${T("Cascade — exits via {v1}", { v1: Store.nodeName(egNode) })}><${Ic} i="cascade"/>${T("cascade →")} ${Store.nodeName(egNode)}</span>`;
  if (mode === "smart") return html`<span class="egb egb-smart" title=${T("Per-destination smart routing")}><${Ic} i="cascade"/>${T("smart cascade")}</span>`;
  if (mode === "forward") return html`<span class="egb egb-cascade"><${Ic} i="cascade"/>${T("tag|cascade")}</span>`;
  return html`<span class="egb egb-direct" title=${T("Exits directly from this node")}><${Ic} i="globe"/>${T("tag|direct")}</span>`;
}

// serialise an egress selection into the API body shape (shared by the interface and WDTT save paths)
export const egressBody = eg => eg.mode === "smart"
  ? { egress_mode: "smart", routing: (eg.rules || []).map(({ _rid, ...r }) => r) }
  : { egress_mode: eg.mode === "auto" ? "direct" : eg.mode, egress_node: eg.node || "", egress_ip: eg.ip || "", wan_iface: eg.nic || "" };
