/* screen-settings.js — Panel settings and the account page.
 *
 * LAYER 11 (see docs/APP-JS-SPLIT-PLAN.md). The largest screen, and the one that reaches furthest: it
 * renders the routing/blocking policy UI, the turn-proxy catalog, the subscription vault, the escrow and
 * the Access & TLS flow, so it imports most of the stack.
 *
 * Access & TLS is the delicate part. Changing the panel's own address can lock the operator out of the
 * panel they are changing it from, so the flow is deliberately three-step — save a CANDIDATE, confirm it
 * from the new address, auto-revert if that confirmation never arrives — and the state machine for that
 * lives here rather than being split between screen and store.
 */

import { T, Trich, Tsplit, plural, srvText } from "./i18n.js";
import { normVkLink, _VK_CALL_RE } from "./peer-ui.js";   // validate pool links by the same rule as the per-user field
import {
  BASE, ago, ipChoices, seen, url,
} from "./util.js";
import {
  LEAVE_MSG, clearUnsavedGuard, setUnsavedGuard,
} from "./router.js";
import {
  IFACE_COLOR_DEFAULTS, THEME_COLOR_DEFAULT, THEME_COLOR_LIGHT_DEFAULT, clampBrand, pickThemed,
} from "./theme.js";
import {
  Store, api, bus, useStore,
} from "./store.js";
import {
  forkSupportsAwg, turnColor, turnFork, turnForkList, turnForksVisible,
} from "./turn-catalog.js";
import {
  ConfirmSheet, Disclosure, Dropdown, ExitDevicePick, ExitEgressPick, Ic, NodeIpPick, Popover, Sheet, Switch, ThemedSwatch, autoGrow, closeModal, copy, footRow,
  goSettings, openConfirm, openModal, pushModal, registerSectionSetter, takePendingSection, toast,
  useHostOnNode,
  exitRefusalText,
} from "./ui.js";
import {
  AWG_ORDER,
  SUB_LANG_LIST, VaultPromptSheet, downloadConf, ivkSetEscrow, nginxServerBlock, nixDirectTlsBlock, nixProxyBlock,
  ensureVaultUnlocked, ivkResealForNodeBlob, nixUpstream, normPublicUrl, qrDataURL, runConfigMigration, subBaseUrl, subForget, subKeyB64, subRewrap, subSKCached, subUnlock,
  subVaultCreate, urlPortOf, withUrlPort,
} from "./crypto.js";
import {
  AsnHint, BlockListPicker, CAT_PROVIDER_DEFAULTS, DescInfo, FleetAssign, HostHealth, ListInfo,
  MODE_META, ModeTabs, NewBlockCatSheet, ProvTag, blockCatDisabled, blockSrcOk, capBadges, catCap, catDescOf,
  catLabelOf, catListUrl, catRawId, catUsableInMode, loadBlockCatalog, newRid,
  TargetField, candAddr, cardAddrs, cardGateway, isCardName, candOf, exitHealth, exitOptionGroups, fleetRuleCats, provLabelOf, providerColor, providerUsage, reportDropped,
  resetRouting, sizeSummary,
  exitHealthMark,
} from "./routing.js";
import { classifyAll } from "./classify.js";   // the one grammar — CustomListSheet accepts what a rule accepts
import { customCaps, customTargets } from "./rulerows.js";   // what a list record holds — preact-free, so it is gated
import {
  TURN_FORKS_DEFAULT, TurnCollectedIps, openRosterCheck, openServerClients, openServerDefaults,
  turnForkPlatforms, turnUpdateTarget, turnUpdating,
} from "./turn.js";
import {
  IgnoredIfacesCard, openIfaceEditor,
} from "./iface.js";
import { h, Fragment } from "preact";
import { useState, useEffect, useRef, useCallback } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);


// ── Shared VK call-link pool ──────────────────────────────────────────────────
// A bag of VK call links the panel hands out to users, one at random, instead of the operator pasting the
// same link everywhere. Saves on its own button (its own endpoint), so it is deliberately NOT part of the
// Turn section's dirty tracking — the save cascades to every holder and that shouldn't ride along with an
// unrelated settings change.
//
// ⚠️ "Dead" is MANUAL and there is no liveness check, by measurement rather than by choice: a bogus call
// hash and a real one both return HTTP 200 and byte-identical page shells, so the panel cannot tell them
// apart from the outside. Anything automatic here would be a coin flip presented as a fact.
// ── Shared VK call-link pool ─────────────────────────────────────────────────────────────────────────────
// One set of operations, two surfaces: five rows inline in Turn settings, twenty per page in the "View all"
// sheet. Everything below is deliberately OPTIMISTIC — the row changes the instant it is clicked and the
// request follows. A pool edit moves real users, so the panel should never make the operator watch a spinner
// to find out whether their click landed.
const VK_PAGE_INLINE = 5, VK_PAGE_SHEET = 15;

function usePool() {
  useStore();
  const ps = Store.panelSettings || {};
  const server = Array.isArray(ps.vk_pool) ? ps.vk_pool : [];
  const [local, setLocal] = useState(null);        // optimistic overlay; null = showing the server's list
  const wantRev = useRef(0);
  const revRef = useRef(ps.vk_pool_rev || 0);
  const chain = useRef(Promise.resolve());
  const pool = local || server;
  // Drop the overlay only once the server has caught up, so the row never flashes back to its old value in
  // the gap between "saved" and "the next poll arrived".
  useEffect(() => {
    const rv = ps.vk_pool_rev || 0;
    if (local && rv >= wantRev.current) setLocal(null);
    if (!local) revRef.current = rv;
  }, [ps.vk_pool_rev, local]);

  // ⚠️ SERIALISED. Each save carries the revision it was read at, and the server bumps that by one, so two
  // actions fired a moment apart must not both send the old number — the second would be refused as stale by
  // the very guard that exists to stop a different session clobbering this one.
  const send = (next, okMsg) => {
    setLocal(next);
    wantRev.current = revRef.current + 1;
    chain.current = chain.current.then(async () => {
      const r = await api.vkPool(next, revRef.current);
      if (!r || !r.ok) {
        setLocal(null);                            // revert to whatever the server actually holds
        if ((r || {}).code === "conflict") { revRef.current = (r.data || {}).rev || 0; await Store.poll(); }
        toast(srvText(r) || T("Couldn't save the VK pool"), "err");
        return;
      }
      revRef.current = (r.data || {}).rev || revRef.current + 1;
      const moved = (r.data || {}).reassigned || 0;
      Store.configEpoch++; bus.emit();
      toast(moved ? T("{v1} — moved {v2} to another link.", { v1: okMsg, v2: plural(moved, "user") }) : okMsg, "ok");
      await Store.poll().catch(() => {});
    });
    return chain.current;
  };

  const holders = url => (Store.recon.users || []).filter(u => (u.vk_links || []).includes(url)).length;
  const problem = (url, skipId) => {
    const v = normVkLink(url);
    if (!v) return T("Enter a VK call link.");
    // ONE key, not a translated half plus a glued literal: word order moves between languages, so the
    // example has to be a placeholder the translator can put where it belongs. peer-ui.js keeps the bare
    // key because it renders the example as markup (<span class="mono">), which is not a concatenation.
    if (!_VK_CALL_RE.test(v)) return T("Expected a VK call link like {v1}", { v1: "https://vk.ru/call/join/…" });
    if (pool.some(e => e.id !== skipId && e.url === v)) return T("The same link is in the pool twice.");
    return "";
  };
  return {
    pool, holders, problem,
    saveUrl: (e, raw) => { const v = normVkLink(raw); const why = problem(v, e.id);
      if (why) { toast(why, "err"); return false; }
      if (v !== e.url) send(pool.map(x => x.id === e.id ? { ...x, url: v } : x), T("Link updated."));
      return true; },
    addMany: (list) => send([...pool, ...list.map(u => ({ url: u, dead: false, added: Math.floor(Date.now() / 1000) }))],
                            list.length > 1 ? T("Added {v1}.", { v1: plural(list.length, "VK link") }) : T("Link added.")),
    toggleDead: e => send(pool.map(x => x.id === e.id ? { ...x, dead: !x.dead } : x), e.dead ? T("Marked alive.") : T("Marked dead.")),
    remove: e => send(pool.filter(x => x.id !== e.id), T("Link removed.")),
    removeDead: () => { const n = pool.filter(x => x.dead).length;
      send(pool.filter(x => !x.dead), T("Removed {v1}.", { v1: plural(n, "dead VK link") })); },
    removeAll: () => send([], T("Removed {v1}.", { v1: plural(pool.length, "VK link") })),
  };
}

// Split a pasted blob into links. An operator with a .txt of them should be able to paste the lot: newlines,
// commas, semicolons and plain spaces all separate, blanks and duplicates fall out.
function vkSplitPaste(text) {
  const seen = new Set(); const out = [];
  for (const part of String(text || "").split(/[\s,;]+/)) {
    const v = normVkLink(part.trim());
    if (v && !seen.has(v)) { seen.add(v); out.push(v); }
  }
  return out;
}

// Split in two so the trigger can sit on the one-line bar while the paste box, which needs the full width,
// opens above it instead of squeezing into a third of the row.
function VkAddBtn({ onClick }) {
  return html`<button class="btn btn-ghost btn-mini" onClick=${onClick}><${Ic} i="plus"/> ${T("Add links")}</button>`;
}
function VkPasteBox({ onAdd, onClose }) {
  const [text, setText] = useState("");
  const links = vkSplitPaste(text);
  const bad = links.filter(u => !_VK_CALL_RE.test(u)).length;
  const setOpen = () => onClose();
  return html`<div class="vkpool-add">
    <textarea class="vkpool-paste" rows="3" autofocus placeholder=${T("Paste one link per line — or separated by commas or spaces")}
      value=${text} onInput=${e => setText(e.target.value)}
      onKeyDown=${e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); if (links.length && !bad) { onAdd(links); setText(""); onClose(); } } }}></textarea>
    <div class="vkpool-foot">
      <span class="faint" style="font-size:11px">${bad ? T("{v1} of these isn't a VK call link.", { v1: String(bad) })
        : links.length ? T("{v1} ready to add", { v1: plural(links.length, "VK link") }) : T("Paste one or many.")}</span>
      <span class="grow"></span>
      <button class="btn btn-ghost btn-mini" onClick=${() => { setText(""); onClose(); }}>${T("Cancel")}</button>
      <button class="btn btn-primary btn-mini" disabled=${!links.length || !!bad}
        onClick=${() => { onAdd(links); setText(""); onClose(); }}>${T("Add")}</button>
    </div>
  </div>`;
}

// The row list, shared by both surfaces. `withDate` adds the "added" column the sheet has room for.
function VkPoolRows({ P, rows, withDate }) {
  const [draft, setDraft] = useState({});
  const urlOf = e => (draft[e.id] !== undefined ? draft[e.id] : e.url);
  const clear = id => setDraft(d => { const n = { ...d }; delete n[id]; return n; });
  return html`<div class="vkpool">
    ${rows.map(e => { const v = urlOf(e), held = P.holders(e.url), edited = normVkLink(v) !== e.url;
      const save = () => { if (P.saveUrl(e, v)) clear(e.id); };
      return html`
      <div class=${"vkpool-row" + (e.dead ? " dead" : "")} key=${e.id}>
        <div class=${"vkbox" + (e.dead ? " dead" : "")} style="flex:1">
          <${Ic} i="users"/>
          <input class="vkbox-input" value=${v} placeholder=${T("https://vk.com/call/join/…")}
            onInput=${ev => setDraft(d => ({ ...d, [e.id]: ev.target.value }))}
            onKeyDown=${ev => { if (ev.key === "Enter") { ev.preventDefault(); save(); }
                                if (ev.key === "Escape") clear(e.id); }}/>
          ${edited ? html`<button class="btn btn-mini vkbox-save" onClick=${save}
            title=${T("Save this link (or press Enter)")}><${Ic} i="check"/></button>` : null}
        </div>
        ${withDate ? html`<span class="vkpool-added" title=${T("When it was added")}>${e.added ? ago(e.added) : "—"}</span>` : null}
        <span class=${"vkpool-held" + (held ? "" : " none")} title=${T("Users holding this link")}>${held || "—"}</span>
        <button class=${"btn btn-ghost btn-mini iconbtn vkpool-dead" + (e.dead ? " on" : "")} onClick=${() => P.toggleDead(e)}
          title=${e.dead ? T("Mark as alive — hand it out again") : T("Mark as dead — stop handing it out and move its users off")}>
          <${Ic} i=${e.dead ? "check" : "off"}/></button>
        <button class="btn btn-ghost btn-mini iconbtn" onClick=${() => P.remove(e)}
          title=${T("Remove from the pool")}><${Ic} i="trash"/></button>
      </div>`; })}
  </div>`;
}

// What the pool adds up to. "Used" is links with at least one holder — a pool with eight links and two in
// use is a different situation from eight links evenly loaded, and the row-by-row counts do not say it.
function VkPoolTotals({ P, big }) {
  const total = P.pool.length;
  if (!total) return null;
  const urls = new Set(P.pool.map(e => e.url));
  const used = P.pool.filter(e => P.holders(e.url) > 0).length;
  const people = (Store.recon.users || []).filter(u => (u.vk_links || []).some(x => urls.has(x))).length;
  const dead = P.pool.filter(e => e.dead).length;
  return html`<div class=${"vkpool-tot" + (big ? " big" : "")}>
    <span>${plural(total, "VK link")}</span>
    <span class="vkpool-dot">·</span>
    <span>${T("{v1} in use", { v1: String(used) })}</span>
    <span class="vkpool-dot">·</span>
    ${/* "у N пользователей" needs the GENITIVE, which is not the form plural() picks for a bare count — the
          catalog already carries this kind of case variant for "на N ноде". English strips the prefix and
          still reads "held by 2 users". */""}
    <span>${T("held by {v1}", { v1: plural(people, "gen|user") })}</span>
    ${dead ? html`<span class="vkpool-dot">·</span><span class="vk-dead-n">${plural(dead, "dead VK link")}</span>` : null}
  </div>`;
}

// Sort is a VIEW concern only — the stored order never changes, so a sort can never rewrite the pool.
const VK_SORTS = { users: (P) => (a, b) => P.holders(b.url) - P.holders(a.url),
                   status: () => (a, b) => (a.dead ? 1 : 0) - (b.dead ? 1 : 0),
                   added: () => (a, b) => (b.added || 0) - (a.added || 0) };
function vkSorted(P, pool, sort, desc) {
  if (!sort) return pool;
  const out = pool.slice().sort(VK_SORTS[sort](P));
  return desc ? out : out.reverse();
}
// The sort control sits ON the column it sorts, as a bare ↓↑ the way the peer and user grids do it — the
// columns here are an icon and a count wide, so a labelled sort bar was both wider than the thing it sorted
// and a second place to look. Same widths as the row's cells, so each arrow lands over its own column.
function VkSortHead({ sort, desc, setSort, setDesc, withDate, left }) {
  const click = k => { if (sort === k) setDesc(d => !d); else { setSort(k); setDesc(true); } };
  // The resting mark is the PAIR "↓↑" — it says "this sorts both ways", which one arrow does not. What made
  // it unreadable before was the size and the tracking (10px, -0.5px, --faint), not the pair: see the CSS.
  const arw = k => sort === k ? (desc ? "↓" : "↑") : "↓↑";
  const cell = (k, cls, title) => html`<button class=${cls + " vkh" + (sort === k ? " on" : "")}
    title=${title} onClick=${() => click(k)}>${arw(k)}</button>`;
  return html`<div class="vkpool-head">
    ${left || null}
    <span class="grow"></span>
    ${withDate ? cell("added", "vkpool-added", T("Sort by when it was added")) : null}
    ${cell("users", "vkpool-held", T("Sort by how many users hold it"))}
    ${cell("status", "btn btn-mini iconbtn", T("Sort by alive or dead"))}
    <span class="btn btn-mini iconbtn vkh-pad"></span>
  </div>`;
}
function VkPager({ page, setPage, pages }) {
  if (pages <= 1) return null;
  return html`<div class="vkpool-pager vkpool-pager-in">
    <button class="btn btn-ghost btn-mini" disabled=${page <= 0} onClick=${() => setPage(p => p - 1)}>${T("Prev")}</button>
    <span class="faint">${T("{v1} of {v2}", { v1: String(page + 1), v2: String(pages) })}</span>
    <button class="btn btn-ghost btn-mini" disabled=${page >= pages - 1} onClick=${() => setPage(p => p + 1)}>${T("Next")}</button>
  </div>`;
}

function VkPoolSheet() {
  const P = usePool();
  const [sort, setSort] = useState("added");
  const [desc, setDesc] = useState(true);
  const [page, setPage] = useState(0);
  const rows = vkSorted(P, P.pool, sort, desc);
  const pages = Math.max(1, Math.ceil(rows.length / VK_PAGE_SHEET));
  const pg = Math.min(page, pages - 1);
  const deadN = P.pool.filter(e => e.dead).length;
  const [addOpen, setAddOpen] = useState(false);
  // ⚠️ noGuard: Sheet flags itself dirty on ANY input event inside it and never clears that, so after adding
  // links the paste box left it "dirty" and Esc offered to discard changes that had already been saved a
  // moment earlier. Nothing in here is ever pending — every row commits on its own — which is exactly the
  // case noGuard exists for ("view modals save every field inline, so there's nothing to discard").
  return html`<${Sheet} title=${T("Shared VK call link pool")} width=${860} noGuard=${true} onClose=${closeModal}
    foot=${html`<${Fragment}>
      <${VkAddBtn} onClick=${() => setAddOpen(o => !o)}/>
      ${deadN ? html`<button class="btn btn-ghost btn-mini" onClick=${() => openConfirm({
          title: T("Remove every dead link?"), danger: true, confirmLabel: T("Remove them"),
          body: T("The {v1} in the pool marked dead will be removed, and anyone still holding one moves to a live link.", { v1: plural(deadN, "VK link") }),
          onConfirm: () => { P.removeDead(); return true; } })}>
        <${Ic} i="trash"/> ${T("Remove dead ({v1})", { v1: String(deadN) })}</button>` : null}
      ${P.pool.length ? html`<button class="btn btn-ghost btn-mini danger" onClick=${() => openConfirm({
          title: T("Remove every link in the pool?"), danger: true, requireType: T("REMOVE ALL"),
          confirmLabel: T("Remove them all"),
          // ⚠️ Says what actually happens, which is more than "they are deleted": there is nothing left to
          // reassign to, so holders end up with NO pool link at all and new users get none either.
          // ⚠️ THE COUNT IS IN PARENTHESES, and that is grammar, not layout. "All 1 VK link are removed"
          // is wrong in English and «1 VK-ссылка будут удалены» is wrong in Russian — a count can never be
          // the subject of a verb neither language will inflect for it (091ac8e). The subject is the POOL,
          // which is singular in both, and the number sits where nothing agrees with it.
          body: T("The whole pool is removed ({v1}). Anyone holding one is left without it, and there is nothing left to hand out — new users get no link until you add one.", { v1: plural(P.pool.length, "VK link") }),
          onConfirm: () => { P.removeAll(); return true; } })}>
        <${Ic} i="trash"/> ${T("Remove all")}</button>` : null}
      <span class="grow"></span>
      <button class="btn btn-ghost" onClick=${closeModal}>${T("Close")}</button></>`}>
    <${VkSortHead} sort=${sort} desc=${desc} setSort=${setSort} setDesc=${setDesc} withDate=${true}
      left=${html`<${VkPoolTotals} P=${P} big=${true}/>`}/>
    ${P.pool.length ? html`<${VkPoolRows} P=${P} rows=${rows.slice(pg * VK_PAGE_SHEET, (pg + 1) * VK_PAGE_SHEET)} withDate=${true}/>`
      : html`<div class="vkpool-empty">${T("The pool is empty — add a link and new users will get one automatically.")}</div>`}
    ${addOpen ? html`<${VkPasteBox} onAdd=${P.addMany} onClose=${() => setAddOpen(false)}/>` : null}
    <div class="vkpool-bar"><span></span><${VkPager} page=${pg} setPage=${setPage} pages=${pages}/><span></span></div>
  <//>`;
}

function VkPoolEditor() {
  const P = usePool();
  const [sort, setSort] = useState("");
  const [desc, setDesc] = useState(true);
  const [page, setPage] = useState(0);
  const rows = vkSorted(P, P.pool, sort, desc);
  const pages = Math.max(1, Math.ceil(rows.length / VK_PAGE_INLINE));
  const pg = Math.min(page, pages - 1);
  const liveLeft = P.pool.filter(e => !e.dead).length;
  const [addOpen, setAddOpen] = useState(false);
  return html`<${Fragment}>
    <div class="seclabel" style="margin-top:18px">${T("Shared VK call link pool")}</div>
    <p class="hint" style="margin:0 0 10px">${Trich("Links handed out to users *at random* — a new user gets one automatically, and you can give anyone more from the pool in their *Manage* view.")}</p>
    ${P.pool.length > 1
      ? html`<${VkSortHead} sort=${sort} desc=${desc} setSort=${setSort} setDesc=${setDesc}
              left=${html`<${VkPoolTotals} P=${P}/>`}/>`
      : html`<div class="vkpool-head"><${VkPoolTotals} P=${P}/></div>`}
    ${P.pool.length ? html`<${VkPoolRows} P=${P} rows=${rows.slice(pg * VK_PAGE_INLINE, (pg + 1) * VK_PAGE_INLINE)}/>`
      : html`<div class="vkpool-empty">${T("The pool is empty — add a link and new users will get one automatically.")}</div>`}
    ${P.pool.length && !liveLeft ? html`<div class="hint vk-warn">${T("No live links left — users on a dead link will keep it until you add a working one.")}</div>` : null}
    ${addOpen ? html`<${VkPasteBox} onAdd=${P.addMany} onClose=${() => setAddOpen(false)}/>` : null}
    <div class="vkpool-bar">
      <${VkAddBtn} onClick=${() => setAddOpen(o => !o)}/>
      <${VkPager} page=${pg} setPage=${setPage} pages=${pages}/>
      ${P.pool.length > VK_PAGE_INLINE ? html`<button class="btn btn-ghost btn-mini" onClick=${() => openModal(html`<${VkPoolSheet}/>`)}>
        ${T("View all ({v1})", { v1: String(P.pool.length) })}</button>` : html`<span></span>`}
    </div>
  <//>`;
}


export function AccountScreen() {
  const [user, setUser] = useState("");
  const [cur, setCur] = useState(""); const [np, setNp] = useState(""); const [np2, setNp2] = useState("");
  const [msg, setMsg] = useState(null); const [enabled, setEnabled] = useState(true);
  useEffect(() => { api.account().then(r => { if (r.ok) { if (r.data.username) setUser(r.data.username); if (!r.data.auth_enabled) { setEnabled(false); setMsg({ ok: false, t: T("This panel has no login configured — changes are disabled.") }); } } }); }, []);
  const save = async () => {
    if (!user.trim()) return setMsg({ ok: false, t: T("Username can't be empty.") });
    if (user.includes(":")) return setMsg({ ok: false, t: T("Username can't contain a colon.") });
    if (!cur) return setMsg({ ok: false, t: T("Enter your current password to confirm.") });
    if (np && np !== np2) return setMsg({ ok: false, t: T("New passwords don't match.") });
    if (np && np.length < 8) return setMsg({ ok: false, t: T("New password must be at least 8 characters.") });
    setMsg({ ok: true, t: T("Saving…") });
    // Re-wrap the vault BEFORE the credential change lands. /api/account rotates the session secret, so the
    // moment it returns our cookie is dead and subRewrap's own API calls 401 — it swallows that and returns
    // false, silently leaving the vault sealed under the OLD password. Do it while the session is still
    // valid, and roll back if the credential change is then rejected, so a wrong current password leaves
    // the vault exactly as it was. Same SK throughout — no blob is ever re-encrypted.
    let reWrapped = false;
    if (np) {
      if (!subSKCached()) { try { await subUnlock(cur); } catch (_) {} }   // not unlocked this session — the current password is right here
      if (subSKCached()) { try { reWrapped = await subRewrap(np); } catch (_) { reWrapped = false; } }
    }
    const r = await api.accountSave({ username: user.trim(), current_password: cur, new_password: np });
    if (!r.ok) {
      if (reWrapped) { try { await subRewrap(cur); } catch (_) {} }   // undo — the password never actually changed
      return setMsg({ ok: false, t: srvText(r) || T("Failed to update.") });
    }
    setMsg({ ok: true, t: T("Updated. Reloading — sign in with your new credentials…") });
    setTimeout(() => location.reload(), 1400);
  };
  return html`<div class="screen">
    <div class="crumb"><b>${T("Account")}</b></div>
    <div class="card" style="max-width:520px">
      <h3 style="margin:0 0 4px">${T("Admin login")}</h3>
      <p class="hint" style="margin:0 0 18px">${Trich("Change the panel username and password. Takes effect immediately — you'll be asked to sign in again. Changing the password also reconnects your *Encryption Vault* to it — the encryption key itself is unchanged, so stored configs and subscription links keep working (no re-issue).")}</p>
      ${msg ? html`<div class=${"formmsg " + (msg.ok ? "ok" : "err")}>${msg.t}</div>` : null}
      <div class="field"><label>${T("Username")}</label><input value=${user} onInput=${e => setUser(e.target.value)} autocomplete="username"/></div>
      <div class="field"><label>${T("Current password")}</label><input type="password" value=${cur} onInput=${e => setCur(e.target.value)} autocomplete="current-password" placeholder=${T("required to confirm changes")}/></div>
      <div class="field"><label>${T("New password")}</label><input type="password" value=${np} onInput=${e => setNp(e.target.value)} autocomplete="new-password" placeholder=${T("leave blank to keep current")}/></div>
      <div class="field"><label>${T("Confirm new password")}</label><input type="password" value=${np2} onInput=${e => setNp2(e.target.value)} autocomplete="new-password"/></div>
      <div style="margin-top:8px"><button class="btn btn-primary" disabled=${!enabled} onClick=${save}>${T("Save changes")}</button></div>
    </div>
  </div>`;
}

export const AWG_KEYS = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4",
  "I1", "I2", "I3", "I4", "I5"];
// client-side AmneziaWG obfuscation generator — mirrors the panel's gen_awg_params (for the "Generate" button)
export function genAwg() {
  const r = n => Math.floor(Math.random() * n), w = 15;
  let s1 = 15 + r(135), s2 = 15 + r(135);
  while (s2 === s1 || s2 === s1 + 56) s2 = 15 + r(135);
  const b = [5, 1e9, 2e9, 3e9].map(base => base + r(9e8));
  return { Jc: 4, Jmin: 40, Jmax: 70, S1: s1, S2: s2, S3: 15 + r(85), S4: 15 + r(85),
    H1: `${b[0]}-${b[0] + w}`, H2: `${b[1]}-${b[1] + w}`, H3: `${b[2]}-${b[2] + w}`, H4: `${b[3]}-${b[3] + w}`,
    I1: "<b 0xc000000001><r 64><t>", I2: "<r 24><t>", I3: "<r 32>",
    I4: "<b 0xc000000001><r 32><t>", I5: "<t><r 48>" };
}
/* Placeholder text for an EMPTY cell — what that field becomes when a new interface is created. Derived from
   genAwg() so the shown constants can never drift from the ones we actually emit. S1-S4 and H1-H4 are the
   exception: the node rolls those fresh FOR EACH interface, which is a property worth keeping — two
   interfaces never share a fingerprint, so a censor who learns one server's headers does not thereby
   recognise the rest. Hence "blank = random" rather than a value. */
export function awgBlankHints() {
  const g = genAwg();
  const out = {};
  for (const k of AWG_KEYS) out[k] = /^[SH][1-4]$/.test(k) ? T("blank = random") : String(g[k]);
  return out;
}
// labelled grid of the 12 AWG fields — read-only display (node settings) or editable (panel settings).
export function AwgGrid({ value, onChange, readOnly, placeholders }) {
  const v = value || {};
  // J / S / H / I as columns, fields stacked — same layout as the interface AWG display
  return html`<div class="awg-cols">${[["Jc", "Jmin", "Jmax"], ["S1", "S2", "S3", "S4"], ["H1", "H2", "H3", "H4"], ["I1", "I2", "I3", "I4", "I5"]].map(grp => html`<div class="awg-col">${grp.map(k => html`<label class="awg-f"><span>${k}</span>${readOnly
    ? html`<span class="awg-val">${v[k] != null && v[k] !== "" ? v[k] : "—"}</span>`
    : html`<input value=${v[k] ?? ""} placeholder=${(placeholders || {})[k] || ""}
        onInput=${e => onChange({ ...v, [k]: e.target.value })} spellcheck="false"/>`}</label>`)}</div>`)}</div>`;
}

// Add / edit an outbound webhook (Settings → Integrations). Immediate-persist via a dedicated endpoint —
// not part of the batched Save. On create the panel returns the signing secret once; edits keep the secret.
// The ids are canonical (stored on the hook, sent to the panel); only the labels are translated, and they
// are resolved on RENDER — a module-level T() runs before loadLang() and would freeze in English.
export const WH_EVENTS = ["peer.added", "peer.removed", "node.online", "node.offline"];   // i18n-keys
const whEventLabel = ev => ({
  "peer.added": T("Peer added"), "peer.removed": T("Peer removed"),
  "node.online": T("Node came online"), "node.offline": T("Node went offline"),
}[ev] || ev);
export function WebhookSheet({ hook, onSaved, onClose }) {
  const [url, setUrl] = useState((hook && hook.url) || "");
  const [events, setEvents] = useState(new Set((hook && hook.events) || WH_EVENTS));
  const [enabled, setEnabled] = useState(hook ? hook.enabled !== false : true);
  const [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState("");                 // shown once, only on create
  const valid = /^https?:\/\/.+/i.test(url.trim());
  const toggle = ev => setEvents(s => { const n = new Set(s); n.has(ev) ? n.delete(ev) : n.add(ev); return n; });
  const save = async () => {
    if (!valid) return toast(T("Enter a valid http(s) URL."), "err");
    setBusy(true);
    const r = await api.apiWebhookSave({ id: hook && hook.id, url: url.trim(), events: [...events], enabled });
    setBusy(false);
    if (!r.ok) return toast(srvText(r) || T("Failed to save webhook"), "err");
    if (r.data && r.data.secret && !hook) { setSecret(r.data.secret); onSaved && onSaved(); return; }   // creation: reveal the secret, keep the sheet open
    onSaved && onSaved(); onClose && onClose();
  };
  return html`<${Sheet} title=${hook ? T("Edit webhook") : T("Add webhook")} onClose=${onClose}
    foot=${secret ? html`<${Fragment}><span class="grow"></span><button class="btn" onClick=${onClose}>${T("Done")}</button></>`
      : html`<${Fragment}><span class="grow"></span>
        <button class="btn btn-ghost" onClick=${onClose}>${T("Cancel")}</button>
        <button class="btn btn-primary" disabled=${busy || !valid} onClick=${save}>${hook ? T("Save") : T("Add webhook")}</button></>`}>
    ${secret ? html`<div class="notice ok"><${Ic} i="check"/><span>${Trich("Webhook saved. This is its *signing secret* — shown once. Every delivery carries an `X-SWG-Signature: sha256=HMAC(secret, body)` header so you can verify it's from this panel.")}</span></div>
      <div class="tokreveal"><code class="tokval">${secret}</code><button class="btn btn-mini" onClick=${() => copy(secret, T("Secret"))}><${Ic} i="copy"/> ${T("Copy")}</button></div>`
    : html`<div class="field"><label>${T("Payload URL")}</label>
        <input value=${url} onInput=${e => setUrl(e.target.value)} placeholder="https://example.com/hooks/swg" spellcheck="false"/>
        <div class="hint">${T("The panel POSTs a JSON body here on each selected event. A signing secret is generated on save.")}</div></div>
      <div class="seclabel">${T("Events")}</div>
      <div class="wh-events">${WH_EVENTS.map(ev => html`<label class="wh-ev" key=${ev}>
        <input type="checkbox" checked=${events.has(ev)} onChange=${() => toggle(ev)}/><span class="mono">${ev}</span><span class="wh-ev-lbl">${whEventLabel(ev)}</span></label>`)}</div>
      <label class="wh-en"><${Switch} on=${enabled} onChange=${setEnabled}/><span>${T("Deliveries enabled")}</span></label>`}
  <//>`;
}

// Settings → Integrations: the read-only external API (tokens + Prometheus) and outbound webhooks. All actions
// persist immediately via dedicated endpoints (outside the batched Save), mirrored optimistically into Store.
export function IntegrationsSettings() {
  const cfg = () => ((Store.panelSettings || {}).api) || { enabled: false, tokens: [], webhooks: [] };
  const [label, setLabel] = useState("");
  const [minted, setMinted] = useState(null);               // {label, token} — revealed once after minting
  const [busy, setBusy] = useState(false);
  const c = cfg();
  const baseUrl = `${location.origin}${BASE}`;
  const optimistic = next => { Store.panelSettings = { ...(Store.panelSettings || {}), api: next }; bus.emit(); };
  const setEnabled = async v => { optimistic({ ...cfg(), enabled: v }); const r = await api.panelSettings({ api_enabled: v }); if (r && r.ok === false) toast(srvText(r) || T("Failed"), "err"); };
  const mint = async () => {
    setBusy(true);
    const r = await api.apiTokenCreate(label.trim());
    setBusy(false);
    if (!r.ok) return toast(srvText(r) || T("Failed to create token"), "err");
    setMinted({ label: r.data.label, token: r.data.token });
    setLabel("");
    optimistic({ ...cfg(), enabled: true, tokens: [...(cfg().tokens || []), { id: r.data.id, label: r.data.label, created: r.data.created, last_used: null }] });
  };
  const revoke = t => openConfirm({ title: T("Revoke API token"), confirmLabel: T("Revoke"), danger: true,
    body: Trich("Revoke *{label}*? Any integration still using it stops working immediately.", { label: t.label }),
    onConfirm: async () => { await api.apiTokenRevoke(t.id); optimistic({ ...cfg(), tokens: (cfg().tokens || []).filter(x => x.id !== t.id) }); } });
  const editHook = h => openModal(html`<${WebhookSheet} hook=${h} onClose=${closeModal}/>`);
  const delHook = h => openConfirm({ title: T("Delete webhook"), confirmLabel: T("Delete"), danger: true,
    body: Trich("Stop sending events to *{v1}*?", { v1: h.url }),
    onConfirm: async () => { await api.apiWebhookDelete(h.id); optimistic({ ...cfg(), webhooks: (cfg().webhooks || []).filter(x => x.id !== h.id) }); } });
  const testHook = async h => { const r = await api.apiWebhookTest(h.id); toast(r.ok ? T("Delivered — HTTP {v1}", { v1: (r.data || {}).status || "200" }) : T("Delivery failed: {v1}", { v1: srvText(r) || T("val|unreachable") }), r.ok ? "ok" : "err", 4200); };
  return html`<div class="card">
    <div class="seclabel turnhead" style="margin-top:0">${T("External API")}<span class="grow"></span>
      <${Switch} on=${c.enabled === true} title=${c.enabled ? T("API on — tokens are accepted") : T("API off — all tokens are rejected")} onChange=${setEnabled}/></div>
    <p class="hint" style="margin:0 0 12px">${Trich("A *read-only* REST + Prometheus surface for external monitoring and automation — Grafana, Uptime Kuma, Prometheus, Terraform/Ansible. No token can ever change the fleet. Authenticate with a bearer token below; `/healthz` and `/api/v1/health` stay open as liveness probes.")}</p>
    ${c.enabled !== true ? html`<div class="notice warn"><${Ic} i="warn"/><span>${Trich("The API is *off* — endpoints return 401. Minting a token turns it on, or flip the switch above.")}</span></div>` : null}

    <div class="seclabel">${T("Access tokens")}</div>
    <div class="tok-add"><input value=${label} onInput=${e => setLabel(e.target.value)} placeholder=${T("Label (e.g. grafana, prometheus)")} spellcheck="false" onKeyDown=${e => { if (e.key === "Enter") mint(); }}/>
      <button class="btn btn-primary" disabled=${busy} onClick=${mint}><span class="plus"><${Ic} i="plus"/></span> ${T("Create token")}</button></div>
    ${minted ? html`<div class="notice ok"><${Ic} i="check"/><span>${Trich("New token *{label}* — copy it now, it won't be shown again.", { label: minted.label })}</span></div>
      <div class="tokreveal"><code class="tokval">${minted.token}</code><button class="btn btn-mini" onClick=${() => copy(minted.token, T("Token"))}><${Ic} i="copy"/> ${T("Copy")}</button><button class="btn btn-mini btn-ghost" onClick=${() => setMinted(null)}>${T("Dismiss")}</button></div>` : null}
    ${(c.tokens || []).length ? html`<div class="toklist">${c.tokens.map(t => html`<div class="tokrow" key=${t.id}>
      <div class="tokrow-main"><span class="tokrow-label">${t.label}</span>
        <span class="tokrow-meta">${T("created {v1}", { v1: ago(t.created) })}${t.last_used ? T(" · last used {v1}", { v1: ago(t.last_used) }) : T(" · never used")}</span></div>
      <button class="btn btn-mini btn-danger" onClick=${() => revoke(t)}><${Ic} i="trash"/> ${T("Revoke")}</button></div>`)}</div>`
      : html`<p class="hint" style="margin:2px 0 0">${T("No tokens yet — create one to let an external system read the fleet.")}</p>`}

    <div class="seclabel">${T("Webhooks")}</div>
    <p class="hint" style="margin:0 0 10px">${T("The panel POSTs a signed JSON body to your endpoint when a peer is added/removed or a node goes online/offline. Use them for alerting or automation.")}</p>
    ${(c.webhooks || []).length ? html`<div class="toklist">${c.webhooks.map(h => html`<div class=${"tokrow" + (h.enabled === false ? " off" : "")} key=${h.id}>
      <div class="tokrow-main"><span class="tokrow-label mono">${h.url}</span>
        <span class="tokrow-meta">${(h.events || []).join(", ") || T("all events")}${h.enabled === false ? " · " + T("val|disabled") : ""}</span></div>
      <button class="btn btn-mini" title=${T("Send a test ping")} onClick=${() => testHook(h)}><${Ic} i="refresh"/> ${T("Test")}</button>
      <button class="btn btn-mini" onClick=${() => editHook(h)}><${Ic} i="pencil"/></button>
      <button class="btn btn-mini btn-danger" onClick=${() => delHook(h)}><${Ic} i="trash"/></button></div>`)}</div>` : null}
    <div style="margin-top:10px"><button class="btn btn-ghost" onClick=${() => editHook(null)}><${Ic} i="plus"/> ${T("Add webhook")}</button></div>

    <div class="seclabel">${T("Endpoints")}</div>
    <div class="apiendpoints">
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/api/v1/health</span><span class="apiep-d">${T("liveness + counts (no auth)")}</span></div>
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/metrics</span><span class="apiep-d">${T("Prometheus exposition")}</span></div>
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/api/v1/servers</span><span class="apiep-d">${T("nodes with status + counts")}</span></div>
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/api/v1/servers/{id}/peers</span><span class="apiep-d">${T("peers + last-handshake timing")}</span></div>
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/api/v1/peers</span><span class="apiep-d">${T("all peers, per-node presence")}</span></div>
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/api/v1/summary</span><span class="apiep-d">${T("fleet totals")}</span></div>
    </div>
    <div class="apisnip"><div class="apisnip-h">${T("Test it")}<button class="btn btn-mini" onClick=${() => copy(`curl -H 'Authorization: Bearer <token>' ${baseUrl}/api/v1/servers`, T("Command"))}><${Ic} i="copy"/> ${T("Copy")}</button></div>
      <code class="apisnip-c">${`curl -H 'Authorization: Bearer <token>' ${baseUrl}/api/v1/servers`}</code></div>
    <div class="apisnip"><div class="apisnip-h">${T("Prometheus scrape config")}<button class="btn btn-mini" onClick=${() => copy(`scrape_configs:\n  - job_name: swg-panel\n    metrics_path: /metrics\n    scheme: ${location.protocol.replace(":", "")}\n    authorization:\n      credentials: <token>\n    static_configs:\n      - targets: ['${location.host}${BASE}']`, T("Scrape config"))}><${Ic} i="copy"/>${T("Copy")}</button></div>
      <code class="apisnip-c">${`scrape_configs:\n  - job_name: swg-panel\n    metrics_path: /metrics\n    authorization:\n      credentials: <token>\n    static_configs:\n      - targets: ['${location.host}${BASE}']`}</code></div>
  </div>`;
}

// Cloudflare's proxy only connects back to origin HTTPS on this fixed port set (everything else is
// unreachable behind the orange cloud). A bundled snapshot of CF's published IP ranges (v4 + v6) for the
// copy-list — it changes rarely; the panel never fetches it live.
export const CF_HTTPS_PORTS = [443, 8443, 2053, 2083, 2087, 2096];
export const CF_IP_RANGES = [
  "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18",
  "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17",
  "162.158.0.0/15", "104.16.0.0/13", "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
  "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32", "2405:8100::/32",
  "2a06:98c0::/29", "2c0f:f248::/32"];
// Built on FIRST READ, never at import: modules load before loadLang() resolves, so a T() evaluated
// here freezes in English whatever the catalog says (see --frozen). A memoised FUNCTION rather than a
// lazy array/object facade — Dropdown calls flatMap() on its options, and a facade only ever has the
// methods someone remembered to forward.
let _tls_mode_opts = null;
export const TLS_MODE_OPTS = () => (_tls_mode_opts || (_tls_mode_opts = [
  { value: "", label: T("None — plain HTTP (behind a reverse proxy / Cloudflare)") },
  { value: "letsencrypt", label: T("Let's Encrypt (HTTP-01 — needs port 80 reachable)") },
  { value: "cloudflare", label: T("Let's Encrypt via Cloudflare DNS (no port 80; needs a token)") },
  { value: "cf15", label: T("Cloudflare Origin certificate (15y — only valid behind Cloudflare)") },
  { value: "selfsigned", label: T("Self-signed") },
  // `skip` — this panel TERMINATES TLS with a certificate it does not issue or renew. It was always a real
  // mode and never an offered choice, so the only way into it was a config file; an operator who already
  // had a certificate had to place the files by hand and edit install.conf to stop the panel re-issuing
  // over them. It is a choice now, and the paths below are what makes it one. It also stays the mode a
  // declarative host (NixOS, where security.acme owns the certificate) is put into by its module, which
  // names no paths — hence one label that reads true for both.
  { value: "skip", label: T("Existing certificate files (issued and renewed outside the panel)") }]));

export const tlsModeLabel = (mode) =>
  ((TLS_MODE_OPTS().find(o => o.value === (mode || "")) || {}).label || "—");

// The panel + swg-sub network address (bindable IP + port) and the ONE certificate config both derive from.
// A change is applied LIVE: the panel dual-listens on the new address and only drops the old once the browser
// confirms the new one works, so a bad value never locks the operator out. swg-sub just restarts.
export function AccessTLSCard({ onChange }) {
  const acc = (Store.panelSettings || {}).access || {};
  const p0 = acc.panel || {}, s0 = acc.sub || {}, t0 = acc.tls || {}, k0 = acc.console || {};
  // This host's installation is owned elsewhere (a NixOS module, a config-management run): the address,
  // the mount path and the certificate are that configuration's, so this screen renders as a read-only
  // view of what it decided. The server refuses the save AND the apply — this is the honest surface,
  // never the enforcement.
  const declarative = !!((Store.env || {}).declarative);
  const nixAccess = String((Store.env || {}).nix_access || "");
  const subsOn = !!((Store.panelSettings || {}).subscriptions || {}).enabled;
  const localPort = Number(p0.local_port || 0);   // co-located node's loopback port (live, read-only) — 0/absent ⇒ no local node ⇒ hide the field
  const [pUrl, setPUrl] = useState(normPublicUrl(p0.url || "")); const [pHost, setPHost] = useState(p0.host || "0.0.0.0"); const [pPort, setPPort] = useState(String(p0.port || 443));
  const [sUrl, setSUrl] = useState(s0.url || ""); const [sHost, setSHost] = useState(s0.host || "0.0.0.0"); const [sPort, setSPort] = useState(String(s0.port || 8444));
  const [mode, setMode] = useState(t0.mode || ""); const [email, setEmail] = useState(t0.email || "");
  const [cfTok, setCfTok] = useState(""); const [cfOrig, setCfOrig] = useState("");
  // paths, not secrets — they round-trip from the server, so the fields keep what was saved
  const [certPath, setCertPath] = useState(t0.cert_path || ""); const [keyPath, setKeyPath] = useState(t0.key_path || "");
  // the subscription surface may sit on a domain of its own, and then it needs its own certificate —
  // the issuing modes have always produced two. Blank = serve it the panel's, which covers the usual
  // case of one hostname on two ports.
  const [subCertPath, setSubCertPath] = useState(t0.sub_cert_path || ""); const [subKeyPath, setSubKeyPath] = useState(t0.sub_key_path || "");
  const [hasCfTok, setHasCfTok] = useState(!!t0.has_cf_token); const [hasCfOrig, setHasCfOrig] = useState(!!t0.has_cf_origin_token);
  // PRIVATE PANEL ACCESS. "" = the panel's own address, as it has always been; "own" = a loopback listener
  // reached through an SSH tunnel, with the public address dropping to a node-only door. The saved block is
  // written by the panel only once a browser has PROVED it can reach the new address, so it is safe to seed.
  // `cHost` is no longer a control — private access IS loopback (D28), and the server forces it on apply.
  // It stays in the form only so the baseline comparison and the wired-deployment path keep their shape.
  const [cMode, setCMode] = useState(k0.mode || ""); const [cHost, setCHost] = useState("127.0.0.1");
  const [cPort, setCPort] = useState(String(k0.port || 9443));
  const [consolePend, setConsolePend] = useState(null);   // a console move awaiting its confirm: {nonce,host,port,scheme,base,expires} — the operator opens the new address and the change commits only there
  const [consoleIn, setConsoleIn] = useState(0);          // seconds left on that confirm window, from the server's absolute deadline (so a reload continues the SAME countdown)
  const [ips, setIps] = useState([]); const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const [polling, setPolling] = useState(false);
  const [confirmUrl, setConfirmUrl] = useState("");   // set while an address change is verifying → the operator confirms it by opening the new address in a new tab (we can't auto-navigate safely: an unreachable new address would strand them, and a cross-origin reachability probe is blocked by our own CSP)
  const [dockerFlip, setDockerFlip] = useState("");   // Docker restart-safe change, step 3: the container is recreating onto the new address. new dial url — shown with a "reconnect" button HELD for a few seconds (see dockerArm) so the operator doesn't open it before the container is back
  const [dockerArm, setDockerArm] = useState(0);      // seconds until the Docker reconnect button arms — a short hold covering the container restart (opening the new address before it's up just fails)
  const [dockerRestart, setDockerRestart] = useState(null);   // Docker restart-safe change, step 1 (Save done): {nonce,url_changed,old_url,new_url,port,port_move,armUntil,error} — nodes now dual-connect to new_url; the operator reviews, then Confirm & restart (dry-run + recreate) or Revert (no-op). Nothing has recreated yet.
  const [drArmIn, setDrArmIn] = useState(0);          // seconds until the "Confirm & restart" button arms — a hold covering one node-sync so nodes LEARN the new address before the recreate (so it can't strand them)
  const [dockerFlipPort, setDockerFlipPort] = useState(0);   // >0 = the step-3 reconnect card is for a reverse-proxy INTERNAL-port move: show the new port to re-point the proxy at (the public url is unchanged), not a "reconnect at new address" link
  const [nixRecipe, setNixRecipe] = useState("");    // declarative host: which worked example is open ("proxy" | "direct")
  const [nixWeb, setNixWeb] = useState("nginx");    // …and which web server that example is written for
  const [confirmVerified, setConfirmVerified] = useState(true);   // false = the reachability gate FAILED-OPEN (revealed Confirm without proving the new address answers) → surface that so Confirm-appearing isn't mistaken for "reachable"
  const [rpSwap, setRpSwap] = useState(null);         // unified reverse-proxy swap in progress: {port_changed,url_changed,path_changed,old_url,new_url,old_host,old_port,new_host,new_port,nonce} — panel serves old+new ports/paths and advertises the new url as a node candidate until the operator re-points the proxy and confirms (no timeout). Any combination of port/url/path.
  const [rpArmIn, setRpArmIn] = useState(0);          // seconds until the rp-swap Confirm button ARMS — a deliberate 60s hold (with a confirm modal) so the operator can't reflexively drop the old address before verifying the proxy actually serves the new one
  const [staleWarn, setStaleWarn] = useState(false);  // the server's SAVED address settings changed out from under this open form (a rollback / boot reconcile / another tab) WHILE the operator has unsaved edits → warn before they apply a now-stale value
  // The "you're on a previous panel address" ribbon is GLOBAL (OldAddrRibbon) + server-driven — it shows on every
  // screen and survives reload, so there's no per-card migration ribbon/state here.
  const rollbackRef = useRef(null);            // the panel address that was live BEFORE an apply → restore the SAVED url on revert (the server rolls back the bind/cert, but the saved url is still the new one → it'd advertise a dead address to nodes)
  const didPanelRef = useRef(false);           // whether THIS save applied a panel change / a sub change — the shared /api/access/status keeps the LAST result of each, so a sub-only save must ignore a stale panel "saved" (and vice-versa)
  const didSubRef = useRef(false);
  const cancelledRef = useRef(false);          // the operator CANCELLED this change (vs it timing out unconfirmed) → the revert message/modal should say "cancelled", not "check DNS/firewall". Set on the Cancel click, cleared when a fresh apply starts + once the revert is shown.
  // Baseline of what's currently live — the form is compared to this to decide what changed (and thus what needs
  // a live apply). Refreshed after a successful save so the button disables until the next edit.
  const [orig, setOrig] = useState({ pUrl: normPublicUrl(p0.url || ""), pHost: p0.host || "0.0.0.0", pPort: String(p0.port || 443),
    sUrl: s0.url || "", sHost: s0.host || "0.0.0.0", sPort: String(s0.port || 8444), mode: t0.mode || "", email: t0.email || "",
    cert_path: t0.cert_path || "", key_path: t0.key_path || "",
    sub_cert_path: t0.sub_cert_path || "", sub_key_path: t0.sub_key_path || "",
    cMode: k0.mode || "", cHost: k0.host || "127.0.0.1", cPort: String(k0.port || 9443) });
  useEffect(() => { api.get("/api/access/ips").then(r => { if (r && r.ok) setIps(r.ips || []); }); }, []);
  // Recover an in-progress reverse-proxy swap after a page reload (server keeps the old address serving until confirmed).
  useEffect(() => { api.get("/api/access/status").then(r => { const p = r && r.ok && r.panel;
    // Recover a swap after reload — and continue the SAME arming countdown (server sends arm_secs remaining from when
    // the swap was armed), so a reload can't reset the safety hold back to a fresh 60s.
    if (p && p.state === "rp-swap") setRpSwap({ port_changed: p.port_changed, url_changed: p.url_changed, path_changed: p.path_changed, old_url: p.old_url, new_url: p.new_url, old_host: p.old_host, old_port: p.old_port, new_host: p.new_host, new_port: p.new_port, nonce: p.nonce, armUntil: Date.now() + (p.arm_secs != null ? p.arm_secs : 60) * 1000 });
    // Recover an in-progress docker restart-safe change after a reload — step 1 (awaiting Confirm/Revert), continuing
    // the SAME arming countdown the server reports.
    else if (p && p.state === "docker-restart") setDockerRestart({ nonce: p.nonce, url_changed: p.url_changed, old_url: p.old_url, new_url: p.new_url, port: p.port, port_move: p.port_move, armUntil: Date.now() + (p.arm_secs != null ? p.arm_secs : 20) * 1000, error: p.dryrun_failed ? (p.message || "") : "" });
    // The new container came up in "awaiting reachability" — THIS page reaching the panel here IS the proof, so commit
    // (clears the marker + stands the auto-revert timer down). If it can't reach the panel it never gets here → auto-revert.
    else if (p && p.state === "docker-awaiting" && p.nonce) api.post("/api/access/docker-commit", { nonce: p.nonce }).catch(() => {});
    // Recover a console move awaiting its confirm. This tab is still fully alive during one — the panel's own
    // address keeps serving the console until the confirm lands (that is the point) — so the card, its
    // countdown and its Cancel all come back on a reload.
    const k = r && r.ok && r.console;
    if (k && k.state === "verifying" && k.nonce)
      setConsolePend({ nonce: k.nonce, host: k.host, port: k.port, scheme: k.https ? "https" : "http", base: k.base || "", expires: k.expires });
    }).catch(() => {}); }, []);
  // The Confirm button is held disabled until rpSwap.armUntil (an absolute clock deadline), so the operator has time
  // to open the new address + verify their proxy first. Anchoring to a deadline (not a from-60 counter) means a page
  // reload continues the same countdown — the server tells us the remaining time on recovery.
  useEffect(() => {
    if (!rpSwap) { setRpArmIn(0); return; }
    const until = rpSwap.armUntil || (Date.now() + 60000);
    const tick = () => setRpArmIn(Math.max(0, Math.ceil((until - Date.now()) / 1000)));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [rpSwap]);
  // The URL the operator opens to confirm a console move. Composed HERE, not by the server, for one reason:
  // a console bound to 0.0.0.0 has no hostname of its own, and only the browser knows which name it actually
  // reached this panel on. A concrete bind (127.0.0.1, a public IP) is used verbatim.
  const consoleUrl = (c) => {
    if (!c) return "";
    const raw = String(c.host || "");
    const h = (raw === "0.0.0.0" || raw === "::" || !raw) ? location.hostname : (raw.includes(":") ? "[" + raw + "]" : raw);
    return `${c.scheme || "https"}://${h}:${c.port}${c.base || ""}/?__applyconsole=${encodeURIComponent(c.nonce || "")}`;
  };
  // The console confirm window, anchored to the server's absolute deadline so a page reload continues the
  // SAME countdown rather than restarting it. At 0 the panel has already put everything back on its own.
  useEffect(() => {
    if (!consolePend) { setConsoleIn(0); return; }
    const tick = async () => {
      const left = Math.max(0, Math.ceil(((consolePend.expires || 0) * 1000 - Date.now()) / 1000));
      setConsoleIn(left);
      if (left > 0) return;
      setConsolePend(null);
      // Which of the two endings was it? This tab can't be told: if the confirm DID land, this address is
      // now a node-only door and every call from here 404s — including the one that would have said so. So
      // ask, and read the silence correctly. Announcing "it wasn't confirmed" to a tab whose panel simply
      // moved out from under it would be the one misleading sentence in the whole flow.
      const still = await api.get("/api/access/status").catch(() => null);
      if (still && still.ok) { resync(); setMsg({ ok: false, t: T("The tunnel wasn't confirmed in time, so the panel is still on its public address.") }); }
      else setMsg({ ok: true, t: T("Private access is on — this address serves the nodes now. Carry on in the tab you confirmed from.") });
    };
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [consolePend]);
  // Docker-flip reconnect hold: tick down to 0, then the reconnect button arms (gives the container time to restart)
  useEffect(() => {
    if (dockerArm <= 0) return;
    const t = setTimeout(() => setDockerArm(dockerArm - 1), 1000);
    return () => clearTimeout(t);
  }, [dockerArm]);
  // The "Confirm & restart" button is held disabled until dockerRestart.armUntil so ONLINE nodes sync at least once
  // and learn the new address (they now dual-connect) BEFORE the recreate — anchored to a deadline so a reload
  // continues the same countdown (the server reports the remaining arm_secs on recovery).
  useEffect(() => {
    if (!dockerRestart) { setDrArmIn(0); return; }
    const until = dockerRestart.armUntil || (Date.now() + 20000);
    const tick = () => setDrArmIn(Math.max(0, Math.ceil((until - Date.now()) / 1000)));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [dockerRestart]);
  // Pull the CURRENT saved config back into the form (+ baseline) — used after a revert, where the backend rolled
  // the bind back to the live one, so the form never keeps showing a value the panel rejected.
  const resync = async () => {
    const r = await api.get("/api/state").catch(() => null);
    const ps = ((r || {}).data || {}).panel_settings;
    if (ps) { Store.panelSettings = ps; bus.emit(); }   // refresh the GLOBAL store too, so a remount/reload can't rehydrate the rejected value the apply rolled back
    const a = (ps || {}).access || {};
    const pp = a.panel || {}, ss = a.sub || {}, tt = a.tls || {};
    setPUrl(normPublicUrl(pp.url || "")); setPHost(pp.host || "0.0.0.0"); setPPort(String(pp.port || 443));
    setSUrl(ss.url || ""); setSHost(ss.host || "0.0.0.0"); setSPort(String(ss.port || 8444));
    setMode(tt.mode || ""); setEmail(tt.email || "");
    setCertPath(tt.cert_path || ""); setKeyPath(tt.key_path || "");
    setSubCertPath(tt.sub_cert_path || ""); setSubKeyPath(tt.sub_key_path || "");
    const kk = a.console || {};
    setCMode(kk.mode || ""); setCHost(kk.host || "127.0.0.1"); setCPort(String(kk.port || 9443));
    setOrig({ pUrl: normPublicUrl(pp.url || ""), pHost: pp.host || "0.0.0.0", pPort: String(pp.port || 443),
      sUrl: ss.url || "", sHost: ss.host || "0.0.0.0", sPort: String(ss.port || 8444), mode: tt.mode || "", email: tt.email || "",
      cert_path: tt.cert_path || "", key_path: tt.key_path || "",
      sub_cert_path: tt.sub_cert_path || "", sub_key_path: tt.sub_key_path || "",
      cMode: kk.mode || "", cHost: kk.host || "127.0.0.1", cPort: String(kk.port || 9443) });
  };
  // poll the apply state machine while a change is in flight. When it's ready to confirm, we DON'T auto-navigate:
  // an unreachable new address would strand the operator, and a cross-origin reachability probe is blocked by our
  // own CSP — so we surface a "Confirm on the new address" link (opened in a new tab, a top-level navigation CSP
  // doesn't block). The new tab's SPA POSTs the confirm; this tab keeps polling and reports saved / reverted.
  useEffect(() => {
    if (!polling) return; let live = true, timer;
    const tick = async () => {
      const r = await api.get("/api/access/status"); if (!live) return;
      if (r && r.ok) {
        const p = r.panel || {}, s = r.sub || {};
        const dp = didPanelRef.current, ds = didSubRef.current;   // react ONLY to a service this save actually changed — the shared status keeps each one's LAST result, so it's stale for the other
        if (dp && p.state === "verifying" && p.redirect) {
          setConfirmUrl(p.redirect);   // show the confirm affordance (rendered in the card); the operator opens it to prove the new address is reachable
          setConfirmVerified(p.verified !== false);   // false = the gate FAILED-OPEN (couldn't reach the new address) → Confirm is unverified, warn
          let h = p.redirect; try { h = new URL(p.redirect).host; } catch (_) {}
          setMsg(p.verified === false
            ? { ok: false, t: T("Couldn't verify {v1} answers yet — it may still be warming up. You can open it to confirm, but if it doesn't load, cancel (nothing is committed until it answers).", { v1: h }) }
            : { ok: true, t: T("Confirming the new address ({v1}) — open it in a new tab so it can reach this panel. It reverts on its own if it can't be reached.", { v1: h }) });
        } else {
          setConfirmUrl("");
          const parts = [];
          if (dp && p.state === "reverted")   // pending ended without a confirm: a deliberate Cancel vs a timeout (unreachable/not opened) read differently
            parts.push(cancelledRef.current
              ? T("Change cancelled — kept the current address.")
              : T("The new address wasn't confirmed — kept the current one. Check its DNS / Cloudflare / firewall / port, then try again."));
          else if (dp && (p.state === "checking" || p.state === "issuing"))   // pre-confirm progress: reachability probe / cert issuance — not an error, not done
            parts.push(p.state === "issuing" ? (p.message || T("Issuing the certificate…")) : T("Waiting for the new address to start responding…"));
          else if (dp && p.state === "rp-swap")   // reverse-proxy swap still pending — the notice drives it; just wait for the confirm
            parts.push(T("Waiting to confirm the reverse-proxy change…"));
          else if (dp && p.state && p.state !== "idle") parts.push(T("Panel: {v1}", { v1: p.message || p.state }));
          if (ds && subsOn && s.state && s.state !== "idle") parts.push(T("Subscriptions: {v1}", { v1: s.message || s.state }));
          const fail = (dp && ["failed", "reverted"].includes(p.state)) || (ds && s.state === "failed");
          if (parts.length) setMsg({ ok: !fail, t: parts.join(" · ") });
        }
        const fail = (dp && ["failed", "reverted"].includes(p.state)) || (ds && s.state === "failed");
        const done = (!dp || ["saved", "failed", "reverted", "idle"].includes(p.state)) && (!ds || ["saved", "failed", "reverted", "idle"].includes(s.state));
        if (done) { setPolling(false); setBusy(false); setConfirmUrl(""); setRpSwap(null);   // clear busy too — a non-navigating finish (revert) reloads nothing, so the Save button would otherwise stay stuck on "Saving…"
          if (fail) {
            // The server reverted the live bind/cert, but the SAVED url is still the new (unreachable) one — it'd be
            // advertised to nodes as the panel's address. Roll it back to what was live before, THEN resync the form.
            const rb = rollbackRef.current; rollbackRef.current = null;
            if (rb) { try { await api.panelSettings({ access: { panel: { url: rb.url, host: rb.host, port: rb.port } } }); } catch (_) {} }
            resync();    // the form was left showing the rejected value → pull the rolled-back config back in
            if (dp && (p.state === "reverted" || p.state === "failed")) {
              const cancelled = p.state === "reverted" && cancelledRef.current;   // deliberate Cancel → neutral "cancelled", not a warning to troubleshoot
              openModal(html`<${ConfirmSheet} title=${cancelled ? T("Address change cancelled") : T("Address change not confirmed")} warn=${!cancelled} confirmLabel="OK"
                body=${cancelled ? T("You cancelled the change — the panel kept the current address.") : ((p.message && p.state === "failed") ? p.message : T("The new address wasn’t confirmed, so the panel kept the current one. Check its DNS / Cloudflare / firewall / port, then try again."))}/>`);
            }
            cancelledRef.current = false;   // consumed
          } else {
            rollbackRef.current = null;
            const gs = +(p.grace_secs || 0), nu = p.new_url || "";
            if (dp && p.state === "saved") {
              if (gs > 0) {   // a REBIND: this tab may now be on the OLD address — the GLOBAL "previous address" ribbon (top of every screen) guides the operator across + counts down
                openModal(html`<${ConfirmSheet} title=${T("New address confirmed")} confirmLabel=${T("Got it")}
                  body=${html`The panel is now reached at <b>${nu || T("the new address")}</b>. If this tab is on the previous address, the ribbon at the top takes you across — it keeps working while nodes move over, then stops. Switch when you’re ready.`}/>`);
              } else {        // url-only / cert-only: same bind → this address keeps working, just verified the new URL
                openModal(html`<${ConfirmSheet} title=${T("Panel address confirmed")} confirmLabel=${T("Done")}
                  body=${html`Verified — the panel is now reached at <b>${nu || T("the new address")}</b>.`}/>`);
              }
            }
          }
          return; }
      }
      timer = setTimeout(tick, 1400);
    };
    tick(); return () => { live = false; clearTimeout(timer); };
  }, [polling]);

  const presets = new Set(["0.0.0.0", "127.0.0.1", ...ips.map(x => x.ip)]);
  const ipOpts = (host, withLocal) => [
    ...(withLocal ? [{ value: "127.0.0.1", label: T("127.0.0.1 — local only") }] : []),
    ...ips.map(x => ({ value: x.ip, label: `${x.ip} — ${x.iface}` })),
    { value: "0.0.0.0", label: T("0.0.0.0 — any IP") },
    { value: "__custom", label: T("Custom IP…") }];
  const cfMode = (mode === "cloudflare" || mode === "cf15");
  const behindProxy = (mode === "" || mode === "skip");   // plain HTTP → a reverse proxy fronts panel + sub; their listen host:port is internal (nginx upstream), not a public address
  // THE host port a service is reached at: the process bind on bare-metal, the published port on docker.
  // Direct TLS makes the url's port and that socket one thing, so the url owns it and no Port field is shown;
  // behind a proxy the two are independent (the proxy bridges them) and the field is authoritative. A url with no
  // port means the scheme default, matching _compute_public_url server-side. The empty-url branch is load-bearing:
  // a fresh install has access.sub.url = "" with port 8444, and deriving 443 from "" reports dirty on load.
  const _hostPortN = (url, rawPort, dflt) => {
    const stored = parseInt(rawPort) || dflt;
    const t = (url || "").trim();
    const n = (behindProxy || !t) ? stored : (parseInt(urlPortOf(t), 10) || (/^http:\/\//i.test(t) ? 80 : 443));
    return Math.max(1, Math.min(65535, n));
  };
  const _pPortN = () => _hostPortN(pUrl, pPort, 443);
  const _sPortN = () => _hostPortN(sUrl, sPort, 8444);
  // Cloudflare only proxies a fixed set of HTTPS ports, and the port that must be in that set is the one CLIENTS
  // reach — the derived host port, not the raw field. cf15 puts this into `blocked`, so it gates, not hints.
  const pBad = cfMode && !CF_HTTPS_PORTS.includes(_pPortN());
  const sBad = subsOn && cfMode && !CF_HTTPS_PORTS.includes(_sPortN());
  // A port outside 1–65535 is invalid on ANY mode. Block it here — otherwise the port silently clamps to 65535 on
  // save while the URL keeps the out-of-range :port, a url/bind desync the change then fails on. (Server rejects too.)
  const _portRangeBad = p => { const s = String(p == null ? "" : p).trim(); return !!s && (!/^\d+$/.test(s) || +s < 1 || +s > 65535); };
  // Behind a proxy the field is authoritative, so range-check what was typed. In direct mode the port comes from
  // the url, so check the url's port text — an out-of-range :99999 must not clamp silently to 65535 on save.
  const pPortRangeBad = behindProxy ? _portRangeBad(pPort) : _portRangeBad(urlPortOf(pUrl));
  const sPortRangeBad = subsOn && (behindProxy ? _portRangeBad(sPort) : _portRangeBad(urlPortOf(sUrl)));
  const hard = mode === "cf15";                                   // cf15 origin certs ONLY work behind CF → block
  // Direct TLS (not behind a proxy) → this service terminates its own TLS and is reached DIRECTLY, so a loopback
  // listen IP isn't publicly reachable (Cloudflare/clients can't hit 127.0.0.1) → 521. Only valid behind a proxy.
  const _isLoopback = (h) => /^(127\.\d|::1|localhost)/i.test((h || "").trim());
  // The tunnel command, with the two things the panel CANNOT know left as placeholders. It knows its own
  // hostname, but that is not necessarily the SSH one: behind Cloudflare `location.hostname` is the CDN,
  // so filling it in would hand the operator a command that dials Cloudflare instead of their server.
  const sshTunnelCmd = (port) => `ssh -L ${port}:127.0.0.1:${port} ssh_user@server_ip`;
  // The address the panel is reached on today. panelPublicUrl is the CONFIRMED canonical one — the same
  // value the fleet is told to dial — so it is the honest answer to "where is this reachable"; it only
  // advances on a real confirm, never on an unsaved edit. Falls back to this tab's own origin, which is
  // by definition an address that works: the operator is reading the page on it.
  const panelHereUrl = () => {
    const u = String((Store.panelPublicUrl || "")).trim().replace(/\/+$/, "");
    if (u) return u;
    return (location.origin + location.pathname).replace(/\/+$/, "") || location.origin;
  };
  // The one option that turns private access on, shown where the screen cannot offer a switch. Written
  // as an ADDITION to the block above it rather than a whole services.swg-panel — the operator already
  // has that block on screen, and a second complete one invites a paste that drops their other options.
  const nixConsoleSample = () => [
    "services.swg-panel = {",   // i18n-keys: generated Nix — file text, copied verbatim
    "  # …your existing options…",   // i18n-keys: generated Nix — file text, copied verbatim
    "  consolePort = 8445;",   // i18n-keys: generated Nix — file text, copied verbatim
    "};"].join("\n");

  // Docker published the console port, or the NixOS module opened it: the address is the deployment's,
  // not this form's. Then the preset is a toggle and the fields would be a control that cannot move
  // what it appears to move — so they go, and the address is stated instead.
  const cWired = acc.console_wired || null;
  const cDockerUnwired = !!acc.console_docker_unwired;
  const _cReach = cWired ? cWired.host : cHost;
  const _cPortN = () => (cWired ? cWired.port : (parseInt(cPort) || 0)) || 9443;
  const _cLoopback = _isLoopback(_cReach);                     // a loopback console is served plain HTTP (no eavesdropper on loopback) and is reachable only through an SSH tunnel
  const cPortBad = !cWired && cMode === "own" && (_portRangeBad(cPort) || !(parseInt(cPort) || 0));   // only gates Save in the mode that binds it — "Same address" leaves the field inert
  const hasPanelCert = !behindProxy;                           // the panel terminates its own TLS → a non-loopback console inherits that certificate; behind a proxy it would be plain HTTP on a public port
  const pLoopbackDirect = !behindProxy && _isLoopback(pHost);
  const sLoopbackDirect = subsOn && !behindProxy && _isLoopback(sHost);
  // Crossing proxy → direct TLS: fold the internal port into the url, so the address the operator was already
  // serving carries over into direct mode (where the url owns the port — see _hostPortN). The url and the port
  // are never mirrored otherwise; one writable copy of the number, per mode.
  const setModeLinked = m => {
    const toDirect = !(m === "" || m === "skip"), wasProxy = behindProxy;
    setMode(m);
    if (toDirect && wasProxy) { setPUrl(withUrlPort(pUrl, pPort)); if (subsOn) setSUrl(withUrlPort(sUrl, sPort)); }
  };
  const wasBehindProxy = (orig.mode === "" || orig.mode === "skip");
  const modeFlip = behindProxy !== wasBehindProxy;                      // the Type change crosses the reverse-proxy ↔ direct-TLS line (the panel's own socket flips HTTP↔HTTPS)
  const flipToTls = modeFlip && !behindProxy;                           // reverse proxy → direct TLS (panel starts terminating its own TLS)
  const blocked = (hard && (pBad || sBad)) || pLoopbackDirect || sLoopbackDirect || pPortRangeBad || sPortRangeBad || cPortBad || (cMode === "own" && cDockerUnwired);
  // ONE-AT-A-TIME cooldown: while a previous address change is verifying or gracing out, Save is locked — the
  // only allowed action is Cancel. Server-enforced too (a stray apply gets a 'cooldown' 409); this just mirrors it.
  const cooldown = Store.accessCooldown || { secs: 0, reason: "" };
  const cooldownActive = (cooldown.secs || 0) > 0;                          // Save is locked on EVERY tab during a change
  const showCooldownNotice = cooldownActive && !confirmUrl && !rpSwap && !dockerRestart && !consolePend && !polling && !busy;   // only surface the notice where THIS tab isn't already driving the change — the driver shows its own progress ("Waiting…") then the confirm area, so confirm always wins the race over the generic cooldown

  const ipField = (host, setHost, withLocal, bad) => {
    const val = presets.has(host) ? host : "__custom";
    return html`<div class="field"><label>${T("Listen IP")}${bad ? html` <span class="ciw" title=${T("Loopback isn't reachable with direct TLS")}><${Ic} i="warn"/></span>` : null}</label>
      <div style=${bad ? "border-radius:8px;box-shadow:0 0 0 3px color-mix(in srgb,var(--dangling) 40%,transparent)" : ""}><${Dropdown} value=${val} onChange=${v => setHost(v === "__custom" ? (presets.has(host) ? "" : host) : v)}
        options=${ipOpts(host, withLocal)}/></div>
      ${val === "__custom" ? html`<input class=${"mt8" + (bad ? " bad" : "")} type="text" placeholder="e.g. 203.0.113.5" value=${host} onInput=${e => setHost(e.target.value)}/>` : null}</div>`;
  };
  const portField = (port, setPort, bad, badTitle) => html`<div class="field"><label>${T("Internal port")}${bad ? html` <span class="ciw" title=${badTitle || T("Cloudflare can't reach this port")}><${Ic} i="warn"/></span>` : null}</label>
    <input class=${bad ? "bad" : ""} type="text" value=${port} onInput=${e => setPort(e.target.value)}/></div>`;
  const loopNote = (which) => html`<div class="notice err"><${Ic} i="warn"/><span>
    ${Trich("*Loopback won't work with direct TLS.* The {which} terminates its own TLS and is reached *directly* — Cloudflare / clients connect straight to this box — so a `127.0.0.1` Listen IP isn't reachable from outside and fails publicly (Cloudflare shows *521*). Set the Listen IP to `0.0.0.0` (a public interface). Loopback is only correct *behind a reverse proxy* (TLS mode “None”). Save is disabled until this is fixed.", { which })}</span></div>`;
  // Reverse-proxy ↔ direct-TLS is a COORDINATED CUTOVER: the panel and the proxy can't both hold the public port,
  // so one has to make way for the other. Spell out exactly what the operator must do around the Save.
  const flipNote = () => html`<div class="notice warn" style="margin:0 0 14px"><${Ic} i="warn"/><div style="min-width:0">
    ${flipToTls
      ? Trich("*Switching to direct TLS — a coordinated cutover.* The panel will terminate its *own* TLS on *{addr}* — with direct TLS the port comes from the *Public URL* (there is no separate internal port), so put the port clients reach in the URL and set the Listen IP to a *public* address (`0.0.0.0`). Your reverse proxy currently owns that port — *free it first* (stop nginx/Caddy there); the panel and the proxy can't both hold it. On Save the panel binds the new HTTPS address *alongside* the current one and you confirm from it — nodes then reach the panel directly. Nothing is dropped until you confirm.", { addr: (pHost.trim() || "0.0.0.0") + ":" + _pPortN() })
      : Trich("*Switching to a reverse proxy — a coordinated cutover.* The panel will serve *plain HTTP* on *{addr}* for your proxy to front. Behind a proxy the listen address is its own setting — an *Internal port* field appears below; set it and the Listen IP to `127.0.0.1`, and leave the Public URL as the address your proxy serves. Stand up nginx/Caddy to terminate TLS and `proxy_pass` to that address (sample below), then confirm — the panel keeps serving its current direct-TLS address until you do.", { addr: (pHost.trim() || "127.0.0.1") + ":" + _pPortN() })}
    </div></div>`;
  const cfNote = html`<div class=${"notice " + (hard ? "err" : "warn")}><${Ic} i="warn"/><span>
    ${T("Cloudflare's proxy only reaches origin HTTPS on {ports}.", { ports: CF_HTTPS_PORTS.join(", ") })} ${hard ? T("A cf15 origin certificate is only valid behind Cloudflare, so this port won't work — pick one of those.") : T("If this panel is behind Cloudflare, this port won't be reachable.")}<br/>
    ${T("If it IS behind Cloudflare, restrict this port to Cloudflare's IP ranges:")}<br/>
    <button class="btn btn-mini mt8" onClick=${() => copy(CF_IP_RANGES.join("\n"), T("Cloudflare IP ranges"))}><${Ic} i="copy"/> ${T("Copy Cloudflare IP ranges")}</button></span></div>`;

  // ── ONE action. The operator never chooses "save" vs "apply" or an order: this saves the config, then runs
  //    exactly the live-applies the change requires, safely. A panel address/cert change is applied with the
  //    dual-listen + browser-confirm dance (a wrong value auto-reverts — it can never lock you out). ──
  // canonical public URL for change-detection/save: behind a proxy the URL's external port stays; with direct TLS
  // it's stripped (the listen Port field owns the port), so a portless↔ported URL isn't seen as a spurious change.
  const _canonUrl = raw => normPublicUrl(raw);   // URLs always keep their port (normPublicUrl only hides the scheme-default 443/80)
  const panelBindChanged = () => (pHost.trim() || "0.0.0.0") !== (orig.pHost || "0.0.0.0") || _pPortN() !== _origPPortN();
  const panelUrlChanged  = () => _canonUrl(pUrl) !== _canonUrl(orig.pUrl);   // the public address everyone dials — a change is verified (confirm) before it takes over
  const subBindChanged   = () => (sHost.trim() || "0.0.0.0") !== (orig.sHost || "0.0.0.0") || _sPortN() !== _origSPortN();
  const subUrlChanged    = () => _canonUrl(sUrl) !== _canonUrl(orig.sUrl);   // the sub public URL's path is swg-sub's mount base → a change must restart it
  const certChanged      = () => mode !== (orig.mode || "") || email.trim() !== (orig.email || "") || !!cfTok || !!cfOrig
                                 || certPath.trim() !== (orig.cert_path || "") || keyPath.trim() !== (orig.key_path || "")
                                 || subCertPath.trim() !== (orig.sub_cert_path || "") || subKeyPath.trim() !== (orig.sub_key_path || "");
  const urlChanged       = () => pUrl.trim() !== (orig.pUrl || "") || sUrl.trim() !== (orig.sUrl || "");
  // The console preset. Only the fields that matter for the mode it is IN: with "Same address" the host and
  // port are inert leftovers in the form, and comparing them would report a change that applies to nothing.
  const consoleChanged   = () => (cMode || "") !== (orig.cMode || "") ||
                                 (!cWired && cMode === "own" && (parseInt(cPort) || 0) !== (parseInt(orig.cPort) || 0));
  const dirty            = () => panelBindChanged() || subBindChanged() || certChanged() || urlChanged() || consoleChanged();
  // Pull the CURRENT saved settings from the store (kept fresh by the /api/state poll) into the form + baseline —
  // like resync() but with no fetch. Used to silently correct a form whose baseline drifted behind the server.
  const _storeAccess = () => (((Store.panelSettings || {}).access) || {});
  const _serverBaseline = () => { const a = _storeAccess(), pp = a.panel || {}, ss = a.sub || {}, tt = a.tls || {}, kk = a.console || {};
    return { pUrl: normPublicUrl(pp.url || ""), pHost: pp.host || "0.0.0.0", pPort: String(pp.port || 443),
      sUrl: ss.url || "", sHost: ss.host || "0.0.0.0", sPort: String(ss.port || 8444), mode: tt.mode || "", email: tt.email || "",
      cMode: kk.mode || "", cHost: kk.host || "127.0.0.1", cPort: String(kk.port || 9443) }; };
  const resyncFromStore = () => { const b = _serverBaseline();
    setPUrl(b.pUrl); setPHost(b.pHost); setPPort(b.pPort); setSUrl(b.sUrl); setSHost(b.sHost); setSPort(b.sPort); setMode(b.mode); setEmail(b.email);
    setCMode(b.cMode); setCHost(b.cHost); setCPort(b.cPort); setOrig(b); };
  // Detect the SAVED address settings changing out from under this open form — a rollback (an aborted combined
  // save, or the blessed-startup boot reconcile), or a change confirmed on another tab. A stale port/url left in
  // the fields would otherwise ride along on the next Save (exactly the phantom-port-change trap). If the form is
  // CLEAN we adopt the true values; if the operator has UNSAVED edits we warn instead of clobbering them.
  useEffect(() => {
    if (busy || polling || rpSwap || dockerRestart || confirmUrl) return;   // an in-flight change owns the form
    if (!((Store.panelSettings || {}).access || {}).panel) return;    // store not populated yet → never resync to blanks
    if (JSON.stringify(_serverBaseline()) === JSON.stringify(orig)) { if (staleWarn) setStaleWarn(false); return; }
    if (!dirty()) { resyncFromStore(); if (staleWarn) setStaleWarn(false); }
    else if (!staleWarn) setStaleWarn(true);
  });
  // Contention: the two services would trade ports on one host, so applying both at once needs one to bind a
  // port the other still holds — a single host can't do that atomically. Detect it and guide two saves instead
  // of attempting a doomed order (which is what produced the "Address already in use" + both-on-443 mess).
  const _overlap = (a, b) => { a = (a || "").trim() || "0.0.0.0"; b = (b || "").trim() || "0.0.0.0"; return a === b || a === "0.0.0.0" || b === "0.0.0.0"; };
  // Compare derived-against-derived: in direct mode `orig.pPort` is the stored value while the live figure comes
  // from the url, so a raw stored number would mis-fire this guard in both directions.
  const _origPPortN = () => _hostPortN(orig.pUrl, orig.pPort, 443);
  const _origSPortN = () => _hostPortN(orig.sUrl, orig.sPort, 8444);
  const subWantsPanelLive = () => subsOn && subBindChanged() && _sPortN() === _origPPortN() && _overlap(sHost, orig.pHost);   // sub's target is the panel's current port
  const panelWantsSubLive = () => subsOn && panelBindChanged() && _pPortN() === _origSPortN() && _overlap(pHost, orig.sHost); // panel's target is the sub's current port

  // Wait for an in-flight subscription apply to reach a terminal state — so the panel apply below never binds
  // a port while the sub is still vacating it (the race that surfaced as "Address already in use").
  const _awaitSub = async () => {
    for (let i = 0; i < 60; i++) {                 // ~90s cap (a cert issuance can be slow); most settle in a few s
      const r = await api.get("/api/access/status").catch(() => null);
      const s = (r && r.sub) || {};
      if (["saved", "failed", "reverted", "idle"].includes(s.state)) return s;
      await new Promise(res => setTimeout(res, 1500));
    }
    return { state: "unknown", message: T("The subscription update didn't finish in time.") };
  };

  const saveAndApply = async () => {
    // Scroll the status/confirm area (top of the card) into view — the Save button lives in the footer, so the
    // result (a status line, a proxy-confirm card, or a validation error) would otherwise land off-screen above.
    // Clear the sticky header stack (appbar + the optional old-address ribbon) so the banner isn't hidden under it.
    requestAnimationFrame(() => {
      const c = document.querySelector(".acctls"); if (!c) return;
      let off = 0; document.querySelectorAll(".appbar, .addr-old-ribbon").forEach(el => { const cs = getComputedStyle(el); if (cs.position === "sticky" || cs.position === "fixed") off += el.getBoundingClientRect().height; });
      window.scrollTo({ top: Math.max(0, c.getBoundingClientRect().top + window.scrollY - off - 12), behavior: "smooth" });
    });
    if (blocked) return setMsg({ ok: false, t: T("Fix the highlighted port first.") });
    if (!dirty()) return;
    // Moving the console is its own change on its own machine (it binds a second listener and rewrites the
    // door policy), and the panel runs address changes strictly one at a time. Combining it with an address
    // or certificate edit in one Save would just have the second half refused mid-flight, so say so first.
    if (consoleChanged()) {
      if (panelBindChanged() || panelUrlChanged() || certChanged() || subBindChanged() || subUrlChanged())
        return setMsg({ ok: false, t: T("Change private access on its own — save the address and certificate changes first, then turn the tunnel on.") });
      return applyConsole();
    }
    // Trading ports between panel and sub can't be done in one shot on a single host — one must free its port
    // before the other can take it. Guide the operator through two saves instead of attempting a doomed order.
    if (subWantsPanelLive() || panelWantsSubLive()) {
      if (subWantsPanelLive() && panelWantsSubLive())
        return setMsg({ ok: false, t: T("The panel and subscription are swapping ports — a single host can't swap two ports at once. First move one of them to a spare free port and Save, then set both to their final ports and Save again.") });
      const first = subWantsPanelLive() ? T("the panel") : T("the subscription server");
      const second = subWantsPanelLive() ? T("the subscription server") : T("the panel");
      return setMsg({ ok: false, t: `The panel and subscription are trading ports. Do it in two saves so one frees the port before the other takes it: first move ${first} and Save, then set ${second}'s port and Save again.` });
    }
    const needSub = subsOn && (subBindChanged() || certChanged() || subUrlChanged());   // sub-URL change → new mount base → swg-sub must re-read it
    const pBindChg = panelBindChanged(), pUrlChg = panelUrlChanged();   // capture BEFORE setOrig resets them → so the post-save proxy guidance knows what changed
    const needPanel = pBindChg || certChanged() || pUrlChg;
    didPanelRef.current = needPanel; didSubRef.current = needSub;   // so the status poll reacts only to what THIS save changes (the shared status is stale for the other)
    cancelledRef.current = false;   // fresh apply — a later revert is a timeout unless the operator clicks Cancel
    setBusy(true); setMsg({ ok: true, t: T("Saving your changes…") });
    // No fold: the url is what the operator typed, and in direct mode it already carries the port (it IS the port).
    // Folding a separate Port field in was the backstop for the old two-copies design; with one source of truth it
    // could only ever overwrite the url with a stale number.
    const npUrl = normPublicUrl(pUrl), nsUrl = normPublicUrl(sUrl);
    setPUrl(npUrl); setSUrl(nsUrl);                                    // reflect it back in the fields
    const r = await api.panelSettings({ access: {
      panel: { url: npUrl, host: pHost.trim() || "0.0.0.0", port: _pPortN() },
      sub: { url: nsUrl, host: sHost.trim() || "0.0.0.0", port: _sPortN() },
      tls: { mode, email: email.trim(), cf_token: cfTok, cf_origin_token: cfOrig,
             cert_path: certPath.trim(), key_path: keyPath.trim(),
             sub_cert_path: subCertPath.trim(), sub_key_path: subKeyPath.trim() } } });
    if (!r || r.ok === false) { setBusy(false); return setMsg({ ok: false, t: (r && (srvText(r) || (r.errors || []).join("; "))) || T("Save failed.") }); }
    const rtls = ((r.data || {}).access || {}).tls || {};        // redacted echo → refresh the "(set)" markers
    setHasCfTok(!!rtls.has_cf_token); setHasCfOrig(!!rtls.has_cf_origin_token); setCfTok(""); setCfOrig("");
    // remember the address that was live before this apply — if the new one doesn't confirm, we re-save this so the
    // panel's canonical url (advertised to nodes) rolls back with the bind/cert the server already reverts.
    if (needPanel) rollbackRef.current = { url: orig.pUrl, host: orig.pHost || "0.0.0.0", port: +orig.pPort || 443 };
    setConfirmUrl(""); setDockerFlip(""); setDockerArm(0); setDockerFlipPort(0);
    setOrig({ pUrl: npUrl, pHost: pHost.trim() || "0.0.0.0", pPort: String(_pPortN()),
      sUrl: nsUrl, sHost: sHost.trim() || "0.0.0.0", sPort: String(_sPortN()), mode, email: email.trim(),
      cert_path: certPath.trim(), key_path: keyPath.trim(),
      sub_cert_path: subCertPath.trim(), sub_key_path: subKeyPath.trim() });
    // subscription server first (a background restart — it can never lock you out of the panel). Don't start
    // polling yet: the panel apply below arms its pending, and we want the very first poll tick to already see
    // it (so the confirm-redirect fires immediately, not after a wasted interval).
    // …or when its certificate is missing/wrong, even though the address is unchanged: apply-sub is what issues
    // it, so without this a broken cert could only be repaired by editing the address to something else and back.
    // Direct TLS only — Store.subCert is {} behind a reverse proxy, where the cert isn't ours to issue.
    if (needSub || (Store.subCert || {}).needs_issue) {
      setMsg({ ok: true, t: T("Updating the subscription server…") });
      await api.post("/api/access/apply-sub", {});
      const ss = await _awaitSub();               // let it settle before the panel apply — no bind race
      if (ss.state === "failed") {
        setBusy(false);
        // The sub step failed, so we ABORT before applying the panel — but its NEW address was already saved up-front
        // and would sit AHEAD of the (unchanged) live panel: a restart would then adopt a url/base/port that never
        // took, the exact mismatch we guard against. And the sub self-healed its bind but its saved url is still new.
        // Roll the SAVED panel+sub config back to the pre-change (== live) values — a partial access block merges,
        // keeping tls — THEN resync, so nothing is left ahead of what's actually running.
        try {
          await api.panelSettings({ access: {
            panel: { url: orig.pUrl, host: orig.pHost || "0.0.0.0", port: +orig.pPort || 443 },
            sub: { url: orig.sUrl, host: orig.sHost || "0.0.0.0", port: +orig.sPort || 8444 } } });
        } catch (_) {}
        await resync();
        return setMsg({ ok: false, t: T("{v1} No panel change was applied — settings rolled back.", { v1: ss.message || T("The subscription server couldn't be updated.") }) });
      }
    }
    // then the panel address/cert (dual-listen + confirm — the operator confirms by opening the new address)
    if (needPanel) {
      const rp = await api.post("/api/access/apply", {});
      if (rp && rp.ok === false) { setBusy(false); await resync(); return setMsg({ ok: false, t: srvText(rp) || T("Couldn't apply the panel address.") }); }
      if (rp && rp.docker_restart) {   // Docker restart-safe change, step 1: nodes now dual-connect to the new address; the operator reviews, then Confirm & restart (dry-run + recreate) or Revert. NOTHING is recreated yet — no dual-listen is possible in a single container, so the recreate waits until Confirm.
        const d = rp.docker_restart; setBusy(false);
        setDockerRestart({ nonce: d.nonce, url_changed: d.url_changed, old_url: d.old_url, new_url: d.new_url, port: d.port, port_move: d.port_move, armUntil: Date.now() + (d.arm_secs != null ? d.arm_secs : 20) * 1000, error: "" });
        return setMsg({ ok: true, t: d.port_move ? T("Saved — review, then Confirm & restart below (you'll re-point your reverse proxy to the new port).") : T("Saved — the nodes are learning the new address. Review, then Confirm & restart below (or Revert).") });
      }
      if (rp && rp.rp_swap) {   // unified reverse-proxy swap (port and/or url and/or path) → both old+new serve; operator re-points the proxy then confirms below
        const s = { ...rp.rp_swap, armUntil: Date.now() + 60000 }; setRpSwap(s); setBusy(false);   // fresh swap → full 60s arming hold
        const bits = [];
        if (s.port_changed) bits.push(T("both ports"));
        if (s.url_changed) bits.push(T("the old and new address"));
        return setMsg({ ok: true, t: T("Saved — the panel now serves {v1}. Update your reverse proxy, then confirm below.", { v1: bits.join(" + ") || T("the change") }) });
      }
      if (rp && !rp.applied) {    // a live bind/cert change is in progress → the status poll surfaces a Confirm link on the first tick
        setMsg({ ok: true, t: T("Preparing the new panel address…") });
        setPolling(true); return;
      }
    }
    if (needSub) setPolling(true);   // no panel redirect — just watch the sub restart finish
    setBusy(false);
    setMsg({ ok: true, t: needSub ? T("Saved & applying — the subscription server is restarting.") : (needPanel ? (behindProxy ? T("Saved — the reverse proxy serves this URL; nothing to restart.") : T("Saved & applied.")) : T("Saved.")) });
  };

  // Report state up to the settings footer (which owns the Save button + status line, like every other section).
  // Runs after each render; the parent only re-renders when a DISPLAYED bit actually changes (see onAccess).
  useEffect(() => { if (onChange) onChange({ dirty: dirty() && !blocked && !cooldownActive && !declarative, busy: busy || polling, msg, run: saveAndApply }); });

  // Move the operator console, or bring it back. Its own endpoint and its own state machine on the panel —
  // the address pipeline's gate, grace and cert paths all answer questions about the address NODES dial, and
  // this is not that address.
  const applyConsole = async () => {
    setBusy(true); setMsg({ ok: true, t: T("Setting up private access…") });
    const r = await api.post("/api/access/console-apply", {
      mode: cMode, host: cHost.trim() || "127.0.0.1", port: parseInt(cPort) || 0 }).catch(() => null);
    setBusy(false);
    // ⚠️ "no reply" and "refused" are different events and only one of them is the operator's to act on.
    // Every refusal this endpoint can return carries its own sentence (port in use, port belongs to
    // swg-sub, bind failed, cooldown, container publishes no port, declaratively managed), so the
    // generic line only ever appeared when the request got NO answer — and then it said the panel had
    // declined something it had never been asked. `!r` is `.catch(() => null)`: the panel was mid-move,
    // restarting, or this tab is on an address that stopped serving. Say that, and say what to do.
    if (!r) { await resync(); return setMsg({ ok: false, t: T("The panel didn't answer. It may be restarting, or this tab may be on an address that no longer serves it — reload the page to see where things stand.") }); }
    if (r.ok === false) { await resync(); return setMsg({ ok: false, t: srvText(r) || T("Couldn't change private access.") }); }
    if (r.applied) {   // back to the panel's own address — nothing to confirm, it can only ever restore access
      await resync();
      return setMsg({ ok: true, t: r.panel_url
        ? T("The console is served at {v1} again, and the panel's own address answers everything once more.", { v1: r.panel_url })
        : T("Private access is off — the panel is on its public address again.") });
    }
    setConsolePend({ nonce: r.nonce, host: r.host, port: r.port, scheme: r.scheme, base: r.base || "", expires: r.expires });
    setMsg({ ok: true, t: T("Nothing has changed yet — open the tunnel and confirm you can reach the panel through it.") });
  };
  // Back out before the confirm. Everything the apply did was additive (a second listener; the panel's own
  // address never stopped serving the console), so this is instant and cannot strand anyone.
  const cancelConsole = async () => {
    setBusy(true);
    try {
      const r = await api.post("/api/access/console-cancel", {});
      if (!r || r.ok === false) { toast(srvText(r) || T("Couldn't cancel the change."), "err"); setBusy(false); return; }
      setConsolePend(null); await resync(); setBusy(false);
      setMsg({ ok: true, t: T("Cancelled — the panel stays where it is.") });
      toast(T("Cancelled — the panel stays where it is."), "ok");
    } catch (_) { toast(T("Couldn't cancel the change."), "err"); setBusy(false); }
  };
  // Abort a change that's still VERIFYING (not yet confirmed) — the server drops the un-confirmed listener /
  // restores the cert and rolls the saved url back. The only other option during verifying is to confirm it.
  const cancelChange = async () => {
    cancelledRef.current = true;   // so the reverted-state message/modal reads "cancelled", not the "check DNS/firewall" troubleshooting copy
    try {
      const r = await api.post("/api/access/cancel", {});
      if (!r || r.ok === false) { cancelledRef.current = false; toast(srvText(r) || T("Couldn't cancel the change."), "err"); }   // cancel didn't take → a later timeout-revert should read as a failure, not "cancelled"
      else toast(T("Change cancelled — kept the current address."), "ok");
    } catch (_) { cancelledRef.current = false; toast(T("Couldn't cancel the change."), "err"); }
    // the polling loop sees the reverted state and clears the confirm affordance + resyncs the form
  };
  // Confirm a unified reverse-proxy swap. If the PUBLIC URL changed, we prove the proxy routes the new address here
  // by opening it in a new tab — its SPA POSTs the confirm THROUGH the proxy on the new host/path (the browser proof;
  // this also drops the old port for a combined change). If ONLY the internal port changed (browser can't reach it),
  // the operator vouches via confirm-proxy. Either way, THIS tab polls status and reports the outcome.
  const confirmRpSwap = () => {
    if (!rpSwap) return;
    if (rpSwap.url_changed) {
      const base = String(rpSwap.new_url || "").replace(/\/+$/, "");
      if (!base || !rpSwap.nonce) return;
      window.open(base + "/?__applyurl=" + encodeURIComponent(rpSwap.nonce), "_blank", "noopener");
      setPolling(true);
      setMsg({ ok: true, t: T("Opened the new address to confirm your proxy routes it here. If it loads there, the switch completes and nodes move over.") });
      return;
    }
    // pure internal-port change → the confirm proves the proxy is on the new port (it travels through the proxy);
    // the server drops the old port only if this request arrived on the new listener, else it refuses (no lockout).
    (async () => {
      setBusy(true);
      try {
        const r = await api.post("/api/access/confirm-proxy", {});
        if (!r || r.ok === false) {
          const em = srvText(r) || T("Couldn't confirm.");
          setBusy(false); toast(em, "err");
          if (r && r.code === "proxy_not_switched") setMsg({ ok: false, t: em });   // prominent: fix the proxy then retry — the swap stays pending, nothing was dropped
          return;
        }
        setRpSwap(null); await resync(); setBusy(false);
        setMsg({ ok: true, t: T("Done — the panel is now on the new port only.") });
        toast(T("Old port dropped — panel is on the new port."), "ok");
      } catch (_) { toast(T("Couldn't confirm."), "err"); setBusy(false); }
    })();
  };
  // Guarded entry to confirmRpSwap: a modal that spells out exactly what's about to change and the real risk — a
  // wrong web-server (nginx / Caddy / …) config can LOCK YOU OUT (the old address stops, the new one won't answer).
  // Only "Proceed" runs the confirm. (The button that opens this is itself held for 60s — see rpArmIn.)
  const confirmRpSwapGuarded = () => {
    if (!rpSwap) return;
    const bits = [];
    if (rpSwap.port_changed) bits.push(html`<li>${Trich("The old internal port *{old}* *stops serving* — your proxy must already forward to *{new}*.", { old: rpSwap.old_port, new: (rpSwap.new_host || "127.0.0.1") + ":" + rpSwap.new_port })}</li>`);
    if (rpSwap.url_changed) bits.push(html`<li>${Trich("I open *{url}* in a new tab — it's adopted *only if it loads there* and reaches this panel. Nodes then move to it.", { url: rpSwap.new_url })}</li>`);
    openModal(html`<${ConfirmSheet} title=${T("Finish the reverse-proxy switch?")} warn=${true}
      confirmLabel=${rpSwap.url_changed ? T("Proceed — open the new address") : T("Proceed — drop the old port")} cancelLabel=${T("Not yet")}
      body=${html`<div>${T("On Proceed:")}</div><ul style="margin:6px 0 10px;padding-left:18px">${bits}</ul>
        <div style="color:var(--dangling)">${Trich("*⚠️ You can lose access to the panel.* If your web server (nginx / Caddy / Traefik / …) isn't already routing the new address to this panel — wrong upstream port, missing `server_name`, or missing `location` — the old address stops and the new one won't answer.")}</div>
        <div style="margin-top:8px">${Trich("Before proceeding, confirm *{addr}* actually opens the panel. If anything's off, cancel and fix your proxy first — *nothing has changed yet*.", { addr: rpSwap.url_changed ? rpSwap.new_url : ((rpSwap.new_host || "127.0.0.1") + ":" + rpSwap.new_port) })}</div>`}
      onConfirm=${() => confirmRpSwap()}/>`);
  };
  // ...or back out: tear down whatever the swap added (new port / new path / new-url candidate); the old address
  // never stopped serving, so nodes stay put.
  const revertRpSwap = async () => {
    setBusy(true);
    try {
      const r = await api.post("/api/access/cancel", {});
      if (!r || r.ok === false) { toast(srvText(r) || T("Couldn't revert."), "err"); setBusy(false); return; }
      setRpSwap(null); await resync(); setBusy(false);
      setMsg({ ok: true, t: T("Reverted — the panel stays on the current address.") });
      toast(T("Reverted — kept the current address."), "ok");
    } catch (_) { toast(T("Couldn't revert."), "err"); setBusy(false); }
  };
  // Docker restart-safe change, step 2: Confirm & restart. The server first DRY-RUNS the new settings in a throwaway
  // container (issue+verify the cert, check the port is free); only on success does it recreate the live container.
  // A dry-run failure changes nothing — we keep the card and show why, so the operator can fix it and retry, or revert.
  const confirmDockerRestart = async () => {
    if (!dockerRestart) return;
    setBusy(true); setMsg({ ok: true, t: T("Checking the new address (dry-run)…") });
    try {
      const r = await api.post("/api/access/docker-confirm", { nonce: dockerRestart.nonce });
      if (r && r.docker_recreate) {   // dry-run passed → the container is recreating onto the new address; show the reconnect hold
        setDockerRestart(null); setDockerFlip(r.new_url || dockerRestart.new_url || ""); setDockerFlipPort(r.port_move ? (r.port || dockerRestart.port || 0) : 0); setDockerArm(20); setBusy(false);
        return setMsg({ ok: true, t: r.message || T("Restarting the panel container. Reconnect at {v1} once it's back.", { v1: r.new_url || dockerRestart.new_url }) });
      }
      setBusy(false);
      // ONE rendering, in the confirm box — that is where Confirm/Revert live, so the failure belongs beside the
      // actions it applies to. Setting the page banner to the SAME string as well showed the identical sentence
      // twice on one screen (three times, with the box's own lead-in and trailing hint duplicating the server's).
      setDockerRestart({ ...dockerRestart, error: srvText(r) || T("The panel couldn't verify the new address.") });
      return setMsg(null);
    } catch (_) { setBusy(false); setMsg({ ok: false, t: T("Couldn't run the dry-run.") }); }
  };
  // Revert step 1 before any recreate: drop the candidate the nodes were dual-connecting to and roll settings back.
  // Everything step 1 did was additive, so this is an instant, safe no-op for the live panel.
  const revertDockerRestart = async () => {
    setBusy(true);
    try {
      const r = await api.post("/api/access/docker-revert", {});
      if (!r || r.ok === false) { toast(srvText(r) || T("Couldn't revert."), "err"); setBusy(false); return; }
      setDockerRestart(null); await resync(); setBusy(false);
      setMsg({ ok: true, t: T("Reverted — the panel stays on the current address.") });
      toast(T("Reverted — kept the current address."), "ok");
    } catch (_) { toast(T("Couldn't revert."), "err"); setBusy(false); }
  };
  // ── declaratively managed → a READ-ONLY view, not a form with fifteen disabled inputs ─────────────
  // The values the worked examples below are built from — this panel's own, so they can be pasted rather
  // than adapted. A host of 0.0.0.0 is dialled on loopback (nixUpstream), and the subscription page only
  // gets a virtual host once it HAS an address: with no sub.domain / sub.publicUrl the module writes no
  // subscription base at all, and inventing the panel's own domain for it would be worse than an absence.
  const _nixDom = (u => { try { return new URL(/^https?:\/\//i.test(u) ? u : "https://" + u).hostname; } catch (_) { return ""; } })(p0.url || "");
  const _nixSubUrl = subBaseUrl();
  const _nixSubHost = (u => { try { return new URL(/^https?:\/\//i.test(u) ? u : "https://" + u).hostname; } catch (_) { return ""; } })(_nixSubUrl);
  const _nixSubBase = (u => { try { return new URL(/^https?:\/\//i.test(u) ? u : "https://" + u).pathname; } catch (_) { return ""; } })(_nixSubUrl);
  // Subscriptions ON with no address yet is the common half-configured state, and "it has no address"
  // is a diagnosis, not an answer: the page is being served on 8444 right now and the operator still
  // has to invent a hostname, a vhost and the module option that ties them together. Suggest one —
  // `sub.<panel domain>` — and mark it as a suggestion to replace rather than a value read from here.
  const subSuggested = !_nixSubHost && subsOn && !!_nixDom;
  const subVhostDom = _nixSubHost || (subSuggested ? "sub." + _nixDom : "");
  const nixProxy = () => nixProxyBlock(nixWeb, [
    { domain: _nixDom, base: p0.base, host: p0.host, port: p0.port || 8443 },
    ...(subVhostDom ? [{ domain: subVhostDom, base: _nixSubBase, host: s0.host, port: s0.port || 8444,
                         suggest: subSuggested }] : [])]);
  const nixDirect = () => nixDirectTlsBlock(_nixDom, p0.port || 8443, p0.base);

  // Disabling the fields would say "you may not touch this". The truth is different: the operator's next
  // action is real, it is just in another file. So show the options that hold this panel's LIVE address
  // and get out of the way — the server builds that snippet from the running process's own environment,
  // which is why it is shown INSTEAD of the saved access settings rather than beside them: on a
  // declarative host those settings were never seeded and would read 0.0.0.0:443 next to a panel that is
  // actually on 127.0.0.1:8443. Safe as an early return because every hook in this component is above it.
  if (declarative) return html`<div class="card acctls">
    <div class="notice" style="margin:0 0 14px;border-color:var(--accent);background:var(--accent-dim, rgba(31,200,214,.08))"><${Ic} i="info"/><div style="min-width:0">
      ${Trich("*This panel's address is managed declaratively.* Its URL, listen address, mount path and certificate come from the configuration that built this machine, so they are shown here rather than edited here — change them there and rebuild. Everything the panel is *for* is unaffected: peers, interfaces, routing and subscriptions all work exactly as they do anywhere else.")}
    </div></div>
    ${nixAccess ? html`<div class="seclabel" style="margin-top:0">${T("Where this panel's address is set")}</div>
    <p class="hint" style="margin:0 0 12px">${T("These options carry what this panel is running right now — where it listens, the hostname it advertises, the path it is mounted at. Edit them in your configuration, rebuild, and this screen follows.")}</p>
    <pre class="mono nixblock">${nixAccess}</pre>
    <button class="btn btn-mini" onClick=${() => copy(nixAccess, T("the panel's address options"))}><${Ic} i="copy"/>${T("Copy")}</button>

    ${/* The number an operator writing a vhost actually needs, and the one thing this screen used to make
          them derive. Kept as plain rows rather than folded into the examples below: it is true whichever
          web server they run, and it stays true when they run none. */""}
    <div class="seclabel">${T("Where a TLS terminator sends traffic")}</div>
    <div class="subaddr wide">
      <div class="subaddr-row"><span class="subaddr-k">${T("Panel")}</span><span class="subaddr-v mono">${nixUpstream(p0.host)}:${p0.port || 8443}${(p0.base && p0.base !== "/") ? p0.base : ""}</span></div>
      <div class="subaddr-row"><span class="subaddr-k">${T("Subscription page")}</span><span class="subaddr-v mono">${nixUpstream(s0.host)}:${s0.port || 8444}${(s0.base && s0.base !== "/") ? s0.base : ""}${subsOn ? "" : html` <span class="faint">${T("(inert until subscriptions are on)")}</span>`}</span></div>
      ${localPort > 0 ? html`<div class="subaddr-row"><span class="subaddr-k">${T("This box's own node")}</span><span class="subaddr-v mono">127.0.0.1:${localPort} <span class="faint">${T("(plain HTTP, never proxied)")}</span></span></div>` : null}
    </div>
    <p class="hint" style="margin:6px 0 0">${T("Internal addresses on this host. Changing the public URL, the path or the certificate never moves them, so a proxy pointed here keeps working.")}</p>

    ${/* ── PRIVATE PANEL ACCESS, read-only ─────────────────────────────────────────────────────────
          Shown ALWAYS, on or off. Off, this screen used to carry no sign the feature existed at all —
          and it is the one platform where the console is the only way in, so an operator had nothing
          to discover and nothing to copy. On, it now says the same things in the same order as every
          other installation: the port, the tunnel command with its Copy button, and what happens to
          the nodes. The only difference is the switch, which lives in the configuration here. */""}
    <div class="seclabel">${T("Private panel access")}</div>
    ${/* The pitch is for an operator who has NOT turned this on. Once it is on they are reading it
          through the tunnel it describes, and the paragraph argues for a thing they already did. The
          port gets no row of its own either: it is in the snippet above and in the command below, and
          a third copy only invites the question of which one is authoritative. */""}
    ${cWired ? null : html`<p class="hint" style="margin:0 0 12px">${Trich("Your nodes and your browser reach this panel through the same door today. They don't have to. Serve the panel *on the server itself* and reach it over an SSH tunnel — the public address then keeps the fleet running while answering *nothing else*: every panel page, every operator API call and the integration API return `404` there.")}</p>`}
    ${cWired ? html`
      <div class="notice" style="margin:0 0 12px"><${Ic} i="info"/><div style="min-width:0">
        ${Trich("*The panel is served on `127.0.0.1:{v1}` on the server*, which nothing outside that machine can open. It is plain HTTP on purpose: the traffic never crosses a network, and a certificate issued for your panel's domain would only mis-name itself on a loopback address.", { v1: String(cWired.port) })}
        <div style="margin:10px 0 0">${T("Open the tunnel from your own machine:")}</div>
        <div style="display:flex;gap:8px;align-items:center;margin:6px 0">
          <button class="btn btn-mini" style="flex:none" onClick=${() => copy(sshTunnelCmd(cWired.port), T("SSH tunnel command"))}><${Ic} i="copy"/>${T("Copy")}</button>
          <pre class="mono" style="flex:1;min-width:0;white-space:pre;overflow:auto;padding:10px;border-radius:6px;background:var(--code-bg, rgba(127,127,127,.09));margin:0;font-size:.85em">${`ssh -L ${cWired.port}:127.0.0.1:${cWired.port} `}<b>ssh_user</b>@<b>server_ip</b></pre>
        </div>
        <div class="hint" style="margin:0">${Trich("Put in the login and address you already use for SSH — `ssh_user` and `server_ip`.")}</div>
        <div style="margin:10px 0 0">${Trich("When the tunnel is up, the panel will be accessible at {v1}", { v1: html`<a class="mono" style="color:var(--brand);font-weight:600" href=${"http://127.0.0.1:" + cWired.port + "/"} target="_blank" rel="noopener">${"http://127.0.0.1:" + cWired.port + "/"}</a>` })}</div>
        <div class="hint" style="margin:8px 0 0">${Trich("*The nodes are unaffected*: they keep dialling the public address, which keeps answering exactly the routes they use.")}</div>
      </div></div>`
    : html`
      <p class="hint" style="margin:0 0 12px">${Trich("This host's Access screen is read-only, so the option *is* the switch — there is nothing to turn on here. Give the panel a console port in your configuration and rebuild; the console moves there, and this section then shows the tunnel command for it.")}</p>
      <pre class="mono nixblock">${nixConsoleSample()}</pre>
      <button class="btn btn-mini" onClick=${() => copy(nixConsoleSample(), T("the private-access option"))}><${Ic} i="copy"/>${T("Copy")}</button>`}

    <div class="seclabel">${T("A sample configuration")}</div>
    <p class="hint" style="margin:0 0 12px">${T("Two arrangements, both with this panel's own domain, path and port already filled in. Pick one, paste it beside the options above, and rebuild.")}</p>
    <${Disclosure} title=${T("Terminate TLS in front of the panel")} summary=${T("recommended")} sumCls="on"
      open=${nixRecipe === "proxy"} onToggle=${() => setNixRecipe(r => r === "proxy" ? "" : "proxy")}>
      <div class="segrow" role="radiogroup">
        <button type="button" role="radio" aria-checked=${nixWeb === "nginx"} class=${"seg" + (nixWeb === "nginx" ? " on" : "")} onClick=${() => setNixWeb("nginx")}>nginx</button>
        <button type="button" role="radio" aria-checked=${nixWeb === "caddy"} class=${"seg" + (nixWeb === "caddy" ? " on" : "")} onClick=${() => setNixWeb("caddy")}>Caddy</button>
      </div>
      ${subVhostDom ? html`<p class="hint" style="margin:0 0 8px">${subSuggested
        ? Trich("Two virtual hosts: the panel, and the subscription page — a *separate service* on its own port. Subscriptions are on but the page has no address yet, so this gives it `{v1}`; change that to whatever you want to publish it as.", { v1: subVhostDom })
        : Trich("Two virtual hosts: the panel, and the subscription page — a *separate service* on its own port.")}</p>` : null}
      <pre class="mono nixblock">${nixProxy()}</pre>
      <button class="btn btn-mini" onClick=${() => copy(nixProxy(), T("the reverse-proxy configuration"))}><${Ic} i="copy"/>${T("Copy")}</button>
      ${subVhostDom ? null : html`<p class="hint" style="margin:12px 0 0">${Trich("The subscription page is off. Turn it on in Subscriptions and give it `sub.domain`, and a virtual host for it appears here.")}</p>`}
      <div class="hint" style="margin-top:10px">${Trich("Leave the panel on its loopback address in this arrangement — the proxy is the only thing that should be reachable from outside.")}</div>
    <//>
    <${Disclosure} title=${T("Terminate TLS in the panel itself")} summary=${T("no proxy")}
      open=${nixRecipe === "direct"} onToggle=${() => setNixRecipe(r => r === "direct" ? "" : "direct")}>
      <pre class="mono nixblock">${nixDirect()}</pre>
      <button class="btn btn-mini" onClick=${() => copy(nixDirect(), T("the direct-TLS configuration"))}><${Ic} i="copy"/>${T("Copy")}</button>
      <div class="hint" style="margin-top:10px">${Trich("The panel reads a certificate `security.acme` already manages and is reloaded when it renews. Declare the certificate itself however you validate it (HTTP-01, DNS-01) — but *don't set its `group`*: this module puts it in `swg` so the panel can read the key, and a second `group` fights it.")}</div>
      ${subVhostDom ? html`<div class="hint" style="margin-top:8px">${Trich("The subscription page still needs its own terminator — it is a separate service on `{v1}`, and this option covers the panel only.", { v1: nixUpstream(s0.host) + ":" + (s0.port || 8444) })}</div>` : null}
    <//>` : null}
  </div>`;
  let _confHost = confirmUrl; try { _confHost = new URL(confirmUrl).host; } catch (_) {}
  return html`<div class="card acctls">
    ${(busy || msg) ? html`<div class=${"notice acc-status" + (busy || (msg && msg.ok) ? "" : " warn")} style=${"margin:0 0 14px" + (busy || (msg && msg.ok) ? ";border-color:var(--accent);background:var(--accent-dim, rgba(31,200,214,.08))" : "")}><${Ic} i=${busy ? "clock" : (msg && msg.ok ? "info" : "warn")}/><div style="min-width:0">
      ${msg ? html`<b>${msg.t}</b>` : null}
      ${busy ? html`<div class="hint" style="margin:4px 0 0">${T("Applying your change — this can take up to a minute or two. It hasn't hung; please wait.")}</div>` : null}
      ${/* Gate-wait (probing/issuing the new address, before the confirm affordance) — give the operator an escape hatch
            instead of only waiting out the auto-revert. Uniquely the PANEL apply keeps busy true through polling (a
            sub-only save clears it); the confirm card owns Cancel once confirmUrl is set. */""}
      ${(busy && polling && !confirmUrl && !rpSwap && !dockerRestart && !dockerFlip) ? html`<div style="margin-top:10px"><button class="btn btn-ghost btn-mini" onClick=${cancelChange}>${T("Cancel this change")}</button></div>` : null}
    </div></div>` : null}
    ${rpSwap ? html`<div class="notice" style="margin:0 0 14px;border-color:var(--accent);background:var(--accent-dim, rgba(31,200,214,.08))"><${Ic} i="info"/><div style="min-width:0">
      ${Trich("*Finish the reverse-proxy switch.* The panel is serving the old *and* new setup at once — each node keeps its current address and only moves once the old one stops. Update your reverse proxy to match {v1}, then confirm. Nothing goes down in between.", { v1: rpSwap.port_changed && rpSwap.url_changed ? T("(both changes below)") : "" })}
      <ul style="margin:8px 0 2px;padding-left:18px">
        ${rpSwap.port_changed ? html`<li>${Trich("Internal port {old} → {new} — point your proxy's upstream at {addr} (co-located loopback nodes follow automatically).", {
          old: html`<span class="mono" style="font-weight:700;color:var(--dangling)">${rpSwap.old_port}</span>`,
          new: html`<span class="mono" style="font-weight:700;color:var(--online)">${rpSwap.new_port}</span>`,
          addr: html`<span class="mono" style="font-weight:700;color:var(--online)">${(rpSwap.new_host || "127.0.0.1")}:${rpSwap.new_port}</span>`,
        })}</li>` : null}
        ${rpSwap.url_changed ? html`<li>${Trich("Public address {old} → {new} — {what} (copy the *panel* nginx sample below), keeping the old one live for now.", {
          old: html`<span class="mono" style="font-weight:700;color:var(--dangling)">${rpSwap.old_url}</span>`,
          new: html`<span class="mono" style="font-weight:700;color:var(--online)">${rpSwap.new_url}</span>`,
          what: rpSwap.path_changed
            ? Trich("add a location for the new path {v1}", { v1: html`<span class="mono" style="font-weight:700;color:var(--online)">${(() => { try { return new URL(rpSwap.new_url).pathname.replace(/\/+$/, "") + "/"; } catch (_) { return T("the new path"); } })()}</span>` })
            : Trich("route {v1} to this panel", { v1: html`<span class="mono" style="font-weight:700;color:var(--online)">${rpSwap.new_url}</span>` }),
        })}</li>` : null}
      </ul>
      ${rpSwap.url_changed ? html`<div class="hint" style="margin:4px 0 0">${T("On confirm the new address opens in a new tab to prove your proxy routes it here before switching nodes over; if it can't load, just revert — nothing changes.")}</div>
      <div class="notice warn" style="margin:8px 0 0"><${Ic} i="warn"/><div>${Trich("*Make sure the new address already opens this panel* (proxy upstream / `server_name` / `location`). If it doesn't, the confirm simply won't take — the old address keeps serving, so you can't be locked out.")}</div></div>` : null}
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">${rpArmIn > 0
        ? html`<button class="btn btn-primary" disabled title=${T("Take a moment to open the new address and check your proxy first")}>${T("Confirm in {n}s — verify your proxy first", { n: rpArmIn })}</button>`
        : (rpSwap.url_changed
            ? html`<a class="btn btn-primary" href=${(String(rpSwap.new_url || "").replace(/\/+$/, "")) + "/?__applyurl=" + encodeURIComponent(rpSwap.nonce || "")} target="_blank" rel="noopener" onClick=${() => { setPolling(true); setMsg({ ok: true, t: T("Opening the new address to confirm your proxy routes it here — if it loads, the switch completes and nodes move over.") }); }}>${T("Confirm — open the new address ↗")}</a>`
            : html`<button class="btn btn-primary" disabled=${busy} onClick=${confirmRpSwapGuarded}>${T("Confirm — drop the old port")}</button>`)}<button class="btn btn-ghost" disabled=${busy} onClick=${revertRpSwap}>${T("Revert")}</button></div>
    </div></div>` : null}
    ${dockerRestart ? html`<div class="notice ${dockerRestart.error ? "warn" : ""}" style=${dockerRestart.error ? "margin:0 0 14px" : "margin:0 0 14px;border-color:var(--accent);background:var(--accent-dim, rgba(31,200,214,.08))"}><${Ic} i=${dockerRestart.error ? "warn" : "info"}/><div style="min-width:0">
      ${dockerRestart.port_move
        ? Trich("*Confirm the internal-port change.* The public address doesn't change, so the nodes aren't affected — but the panel will restart onto a new internal port, so your *reverse proxy must be re-pointed* to it. When you Confirm, the panel dry-runs the new port (checks it's free), restarts onto it, then waits for you to re-point the proxy. If it stays unreachable it *rolls back to the current port automatically*.")
        : Trich("*Confirm the address change.* The nodes are now told to *also* try `{v1}`, so they're already connected there before the restart. When you Confirm, the panel first *dry-runs* the new settings in a throwaway container (issues the certificate, checks the port), and only then restarts onto the new address. If it can't be reached afterwards, it *rolls back automatically*.", { v1: dockerRestart.new_url })}
      ${dockerRestart.port_move
        ? html`<ul style="margin:8px 0 2px;padding-left:18px"><li>${Trich("New internal port `{v1}` — after Confirm, point your reverse proxy's upstream at it and reload the proxy.", { v1: dockerRestart.port })}</li></ul>`
        : dockerRestart.url_changed
        ? html`<ul style="margin:8px 0 2px;padding-left:18px"><li>${Trich("New address `{v1}` — make sure DNS / your firewall / Cloudflare route it to this panel.", { v1: dockerRestart.new_url })}</li></ul>`
        : null}
      ${dockerRestart.error ? html`<div class="notice warn" style="margin:8px 0 0"><${Ic} i="warn"/><div style="min-width:0"><b>${T("Dry-run failed.")}</b> ${srvText(dockerRestart)}</div></div>` : null}
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">${drArmIn > 0
        ? html`<button class="btn btn-primary" disabled title=${T("The nodes are still learning the new address")}>${T("Confirm & restart in {n}s…", { n: drArmIn })}</button>`
        : html`<button class="btn btn-primary" disabled=${busy} onClick=${confirmDockerRestart}>${busy ? T("Checking…") : T("Confirm & restart")}</button>`}<button class="btn btn-ghost" disabled=${busy} onClick=${revertDockerRestart}>${T("Revert")}</button></div>
    </div></div>` : null}
    ${dockerFlip ? html`<div class="notice" style="margin:0 0 14px;border:1px solid var(--accent);background:var(--accent-dim, rgba(31,200,214,.08))"><${Ic} i="clock"/><div style="min-width:0">
      ${dockerFlipPort > 0
        ? html`${Trich("*Restarting onto internal port {v1}.* Point your reverse proxy's upstream at `127.0.0.1:{v1}` and reload the proxy — this page comes back once it routes there. It confirms itself when reachable; if it stays unreachable it rolls back to the current port automatically.", { v1: dockerFlipPort })}
          <div style="margin-top:10px">${dockerArm > 0
            ? html`<button class="btn btn-primary" disabled title=${T("Waiting for the container to restart")}>${T("Restarting in {n}s…", { n: dockerArm })}</button>`
            : html`<a class="btn btn-primary" href=${dockerFlip} target="_blank" rel="noopener">${T("Reload this page ↻")}</a>`}</div>`
        : html`${Trich("*Restarting the panel container.* Reconnect at the new address once it's back — it confirms itself when you reach it. If the new address can't be reached (or the certificate can't be issued), the panel rolls back automatically to the current address.")}
          <div style="margin-top:10px">${dockerArm > 0
            ? html`<button class="btn btn-primary" disabled title=${T("Waiting for the container to restart")}>${T("Reconnect in {n}s…", { n: dockerArm })}</button>`
            : html`<a class="btn btn-primary" href=${dockerFlip} target="_blank" rel="noopener">${T("Reconnect at the new address ↗")}</a>`}</div>`}
    </div></div>` : null}
    ${confirmUrl ? html`<div class="notice ${confirmVerified ? "" : "warn"}" style=${confirmVerified ? "margin:0 0 14px;border-color:var(--accent);background:var(--accent-dim, rgba(31,200,214,.08))" : "margin:0 0 14px"}><${Ic} i=${confirmVerified ? "info" : "warn"}/><div style="min-width:0">
      ${confirmVerified
        ? html`${Trich("*Confirm the new address.* Open `{v1}` in a new tab to confirm it — the change is applied *only once* it loads there.", { v1: _confHost })}`
        : html`${Trich("*Couldn't verify the new address yet.* I probed `{v1}` from here and it didn't answer in time — it may still be warming up (a fresh Cloudflare origin can be slow), *or* it's not reachable at all (e.g. a direct-TLS panel bound to `127.0.0.1` instead of a public IP, or a port your proxy/DNS doesn't route). Open it to confirm anyway — the change applies *only if it loads*.", { v1: _confHost })}`}
      ${Trich("If that tab *can't* load, just close it: this panel stays on the current address and reverts automatically. Nothing is committed until the new address answers.")}
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap"><a class="btn btn-primary" href=${confirmUrl} target="_blank" rel="noopener">${T("Open the new address to confirm ↗")}</a><button class="btn btn-ghost" onClick=${cancelChange}>${T("Cancel this change")}</button></div>
    </div></div>` : null}
    ${showCooldownNotice ? html`<div class="notice warn" style="margin:0 0 14px"><${Ic} i="warn"/><div style="min-width:0">
      <b>${T("Operation cooldown.")}</b> ${cooldown.reason === "verifying" ? T("An address change is still waiting to be confirmed.")
        : cooldown.reason === "console" ? T("A private-access change is still waiting to be confirmed — finish or cancel it in the tab that started it.")
        : Trich("The previous change is still settling (*{v1}s* left).", { v1: cooldown.secs })} ${Trich("Address changes run *one at a time* — Save is locked until it finishes. If a change is in flight, you can still cancel it from the tab that started it.")}
    </div></div>` : null}
    ${staleWarn ? html`<div class="notice warn" style="margin:0 0 14px"><${Ic} i="warn"/><div style="min-width:0">
      ${Trich("*These settings changed elsewhere.* The panel's saved address settings were updated by the server (a rollback, a boot reconcile, or a change confirmed in another tab) while you have *unsaved edits* here — so a field below may be based on an *old* value. *Reload the page* before saving, or your change could re-apply a value the panel already reverted.")} <button class="btn btn-mini" style="margin-left:6px" onClick=${() => { resyncFromStore(); setStaleWarn(false); }}>${T("Discard my edits & refresh")}</button>
    </div></div>` : null}

    <div class="seclabel" style="margin-top:0">${T("Certificate")}</div>
    <p class="hint" style="margin:0 0 12px">${T("How TLS is terminated — this decides which ports are valid below. One choice issues both certificates (the panel's and swg-sub's, always separate keys).")}</p>
    ${(() => {
      // Renewal health, said where the certificate is configured. The panel has always WATCHED its own
      // cert, but nothing rendered the result: a renewal failing every hour for a month was visible only
      // to someone reading the server log, while this screen showed a healthy certificate the whole time.
      const ts = Store.tls || {};
      const d = Number(ts.days_left);
      if (ts.renew_ok === false) return html`<div class="notice warn" style="margin:0 0 12px" title=${ts.renew_last || ""}><${Ic} i="warn"/><div style="min-width:0">
        ${Trich("*Automatic renewal is failing.* The certificate is still valid for *{v1}* more day(s), but nothing is renewing it — check that this host is reachable by the validation method above.", { v1: isFinite(d) ? d : "?" })}
      </div></div>`;
      if (!ts.self_signed && isFinite(d) && d <= 21) return html`<div class="notice warn" style="margin:0 0 12px"><${Ic} i="warn"/><div style="min-width:0">
        ${Trich("*This certificate expires in {v1} day(s).*", { v1: d })}
      </div></div>`;
      return null;
    })()}
    <div class="field"><label>${T("Type")}</label><${Dropdown} value=${mode} onChange=${setModeLinked} options=${TLS_MODE_OPTS()}/></div>
    ${(mode === "letsencrypt" || mode === "cloudflare") ? html`<div class="field"><label>${T("Account email")}</label><input type="text" placeholder=${T("admin@example.com")} value=${email} onInput=${e => setEmail(e.target.value)}/></div>` : null}
    ${mode === "cloudflare" ? html`<div class="field"><label>${T("Cloudflare API token")}</label><input type="password" placeholder=${hasCfTok ? T("•••••••• (set — leave blank to keep)") : T("Zone:DNS:Edit token")} value=${cfTok} onInput=${e => setCfTok(e.target.value)}/>
      <div class="hint">${T("Used for DNS-01 validation. Stored on the panel only; never sent to the browser. Enter \"-\" to clear.")}</div></div>` : null}
    ${mode === "cf15" ? html`<div class="field"><label>${T("Cloudflare Origin CA token")}</label><input type="password" placeholder=${hasCfOrig ? T("•••••••• (set — leave blank to keep)") : T("Zone:SSL and Certificates:Edit token")} value=${cfOrig} onInput=${e => setCfOrig(e.target.value)}/>
      <div class="hint">${Trich("Requests a 15-year Cloudflare Origin certificate — valid *only* behind Cloudflare's proxy. Stored on the panel only. Enter \"-\" to clear.")}</div></div>` : null}
    ${mode === "skip" ? html`<div class="field"><label>${T("Full-chain certificate")}</label>
      <input type="text" placeholder="/etc/letsencrypt/live/example.com/fullchain.pem" value=${certPath} onInput=${e => setCertPath(e.target.value)}/>
      <div class="hint">${T("An absolute path on the panel host — the certificate with its chain. It must cover the panel's public address.")}</div></div>
    <div class="field"><label>${T("Private key")}</label>
      <input type="text" placeholder="/etc/letsencrypt/live/example.com/privkey.pem" value=${keyPath} onInput=${e => setKeyPath(e.target.value)}/>
      <div class="hint">${T("Absolute path too, and the key must not have a passphrase. Both files are copied into place and re-checked every few hours, so a renewal written over them is picked up on its own. Leave both blank if a certificate is already installed and nothing here should touch it.")}</div></div>` : null}
    ${mode === "skip" ? html`<div class="field"><label>${T("Subscription certificate")}</label>
      <input type="text" placeholder="/etc/letsencrypt/live/subs.example.net/fullchain.pem" value=${subCertPath} onInput=${e => setSubCertPath(e.target.value)}/></div>
    <div class="field"><label>${T("Subscription private key")}</label>
      <input type="text" placeholder="/etc/letsencrypt/live/subs.example.net/privkey.pem" value=${subKeyPath} onInput=${e => setSubKeyPath(e.target.value)}/>
      <div class="hint">${T("Only needed when the subscription page answers to a different name than the panel. Leave both blank and it is served the certificate above — which is what you want when the two share a hostname, or one certificate covers both.")}</div></div>` : null}
    ${modeFlip ? flipNote() : null}

    <div class="seclabel">${T("Public panel address")}</div>
    <p class="hint" style="margin:0 0 12px">${T("Where the panel itself is reached.")}${behindProxy
      ? T(" Your proxy fronts this URL and forwards to the internal address below — the two are independent.")
      : Trich(" The panel serves this address directly, so *the URL carries the port* (there is no separate internal port to set).")}</p>
    <div class="field"><label>${T("Public URL")}</label><input type="text" placeholder=${T("https://panel.example.com  or  https://example.com/swgpanel")} value=${pUrl} onInput=${e => setPUrl(e.target.value)}/></div>
    <div class="fieldrow">${ipField(pHost, setPHost, true, pLoopbackDirect)}${behindProxy
      ? portField(pPort, setPPort, pBad || pPortRangeBad, pPortRangeBad ? T("Port must be a number between 1 and 65535") : null)
      : null}</div>
    ${pLoopbackDirect ? loopNote("panel") : (pBad ? cfNote : null)}
    ${localPort > 0 ? html`<div class="localnode-note">${Trich("This box's own node reaches the panel on {v1} — a dedicated plain-HTTP loopback port, served at the root. It's set at install and a public address, port, path, or certificate change never moves it, so the co-located node never loses the panel.", { v1: html`<b class="mono">127.0.0.1:${localPort}</b>` })}</div>` : null}
    ${(behindProxy && (panelBindChanged() || panelUrlChanged())) ? html`<div class="notice" style="margin:8px 0 12px"><${Ic} i="info"/><div style="min-width:0">
      ${Trich("*Behind a reverse proxy.*")}
      ${panelBindChanged() ? Trich(" Saving binds `{v1}` *alongside* the current port (both keep serving) — you then re-point your reverse proxy and confirm to drop the old one, with no downtime. External nodes dial your public URL through the proxy, so they don't change; only a co-located node that dials the panel on `127.0.0.1` needs its `panel.url` port updated too.", { v1: (pHost.trim() || "127.0.0.1") + ":" + _pPortN() }) : null}
      ${panelUrlChanged() ? Trich(" The public URL is served by *your reverse proxy*, not the panel — make sure the proxy serves it (server_name / TLS cert / path) before relying on it. The panel's own mount path stays `SWG_PANEL_BASE`. Nodes are told this URL as their dial address, so external nodes re-point to it on their next sync — make sure they can reach it; one that can't must have its `panel.url` updated by hand.") : null}
    </div></div>`
    : panelBindChanged() ? html`<div class="notice" style="margin:8px 0 12px"><${Ic} i="info"/><div style="min-width:0">
      ${Trich("*Nodes re-point themselves.* On save, online nodes learn the new address on their next sync and switch to it — the old address stays reachable for ~3 minutes so they can. A node that is *offline* during the change (or one installed without verifying/pinning the panel cert) must be re-pointed by hand: set `panel.url` in `/etc/swg-agent/config.json` (bare-metal) or `PANEL_URL` in `.env` (docker) to the new address, then restart `swg-noded` / recreate the container.")}
    </div></div>` : null}
    ${behindProxy ? html`<details class="nginx-sample" style="margin:8px 0 4px"><summary style="cursor:pointer;color:var(--muted);font-size:.9em">${Trich("Reverse-proxy config for the panel (nginx) — full `server { }` for the values above")}</summary>
      <pre class="mono" style="white-space:pre;overflow:auto;padding:10px;border-radius:6px;background:var(--code-bg, rgba(127,127,127,.09));margin:8px 0 6px;font-size:.85em">${nginxServerBlock(pUrl, pHost, _pPortN())}</pre>
      <button class="btn btn-mini" onClick=${() => copy(nginxServerBlock(pUrl, pHost, _pPortN()), T("panel nginx server block"))}><${Ic} i="copy"/>${T("Copy")}</button>
      <div class="hint" style="margin-top:6px">${Trich("Built from the domain, external port, path (from the Public URL) and the internal listen address above. Point `ssl_certificate` at your real cert, then `nginx -t && systemctl reload nginx`.")}</div>
    </details>` : null}

    <div class="seclabel">${T("Private panel access")}</div>
    ${/* ⚠️ GATED ON THE SAVED STATE (`k0.mode`), NOT ON THE TOGGLE (`cMode`). The paragraph argues for
          moving the console, so it is for someone who has not moved it — once the change is CONFIRMED
          the operator is reading it through the tunnel it describes. But the toggle here is a form
          control, not the applied state: gating on it would make this text appear and vanish under the
          cursor every time the operator flipped it while deciding, and while they are deciding the
          public address is still serving the panel and the pitch is still the context for the choice.
          The saved value is the honest signal, and it matches the declarative branch above, where
          there is no toggle at all and "on" can only mean "already done". */""}
    ${k0.mode === "own" ? null : html`<p class="hint" style="margin:0 0 12px">${Trich("Your nodes and your browser reach this panel through the same door today. They don't have to. Serve the panel *on the server itself* and reach it over an SSH tunnel — the public address then keeps the fleet running while answering *nothing else*: every panel page, every operator API call and the integration API return `404` there.")}</p>`}
    ${/* The toggle and its port are one decision, so they share a row — and the port is a NORMAL field
          (label above, full width of its column) so it reads like every other field on this screen.
          align-items:flex-end bottom-aligns the single-line toggle with the input, not with its label. */ ""}
    <div class="fieldrow" style="align-items:flex-end;margin:0 0 12px">
      <label class="ivk-esc-row" style="flex:1;min-width:140px;align-items:center;margin:0 0 9px;cursor:pointer">
        <${Switch} on=${cMode === "own"} onChange=${v => setCMode(v ? "own" : "")}/>
        <span>${T("Access web panel via SSH tunnel")}</span></label>
      ${(cMode === "own" && !cWired && !cDockerUnwired) ? html`<div class="field">
        <label>${T("Tunnel port")}${cPortBad ? html` <span class="ciw" title=${T("Port must be a number between 1 and 65535")}><${Ic} i="warn"/></span>` : null}</label>
        <input class=${cPortBad ? "bad" : ""} type="text" value=${cPort} onInput=${e => setCPort(e.target.value)}/></div>`
        : html`<div class="field" style="visibility:hidden"><label>&nbsp;</label></div>`}
    </div>
    ${/* Where the panel is reached on its PUBLIC address. The section otherwise said nothing at all in
          its resting state — a heading and a switch — so the one fact an operator wants before flipping
          it (what am I about to change?) was the one fact missing.
          ⚠️ Two independent things decide this line, and they are not the same thing:
            • WHETHER to show it — the TOGGLE. Switched on, the operator is asking for the console to
              move and the notice below already tells them where it lands; repeating the public address
              beside it just competes with that.
            • WHICH TENSE — the SAVED state. Off with public saved is the resting truth ("is"). Off with
              private saved is a pending change back ("will be"), and saying "is" there would describe
              an address that does not serve the panel yet.
          Written as two literal Trich calls rather than one with a computed key: the i18n extractor
          reads the literal argument, and a conditional inside it takes both sentences out of the
          catalogue. */""}
    ${cMode === "own" ? null : html`<div class="hint" style="margin:0 0 12px">${
      k0.mode === "own"
        ? Trich("The panel will be accessible at {v1}", { v1: html`<a class="mono" style="color:var(--brand);font-weight:600" href=${panelHereUrl()} target="_blank" rel="noopener">${panelHereUrl()}</a>` })
        : Trich("The panel is accessible at {v1}", { v1: html`<a class="mono" style="color:var(--brand);font-weight:600" href=${panelHereUrl()} target="_blank" rel="noopener">${panelHereUrl()}</a>` })
    }</div>`}
    ${(cMode === "own" && cDockerUnwired) ? html`<div class="notice warn" style="margin:0 0 12px"><${Ic} i="warn"/><div style="min-width:0">
      ${Trich("*This panel's container doesn't publish a port for this*, so a listener inside it would be unreachable — there is nothing to fill in here yet. *Re-run the Docker installer* to restage `docker-compose.yml` (it adds the port), then come back.")}
    </div></div>` : null}
    ${(cMode === "own" && cWired) ? html`<div class="subaddr wide" style="margin:0 0 10px">
      <div class="subaddr-row"><span class="subaddr-k">${T("Tunnel port")}</span><span class="subaddr-v mono">${cWired.port}</span></div></div>
      <p class="hint" style="margin:0 0 12px">${Trich("This port is set where this panel is deployed, not here — so there is nothing to pick. Change it in `.env` (`CONSOLE_PORT`) and re-run the Docker installer, or in the NixOS option, then come back.")}</p>` : null}
    ${(cMode === "own" && !cDockerUnwired) ? html`
      <div class="notice" style="margin:8px 0 12px"><${Ic} i="info"/><div style="min-width:0">
        ${Trich("*The panel will be served on `127.0.0.1:{v1}` on the server*, which nothing outside that machine can open. It is plain HTTP on purpose: the traffic never crosses a network, and a certificate issued for your panel's domain would only mis-name itself on a loopback address.", { v1: _cPortN() })}
        <div style="margin:10px 0 0">${T("Open the tunnel from your own machine:")}</div>
        <div style="display:flex;gap:8px;align-items:center;margin:6px 0">
          <button class="btn btn-mini" style="flex:none" onClick=${() => copy(sshTunnelCmd(_cPortN()), T("SSH tunnel command"))}><${Ic} i="copy"/>${T("Copy")}</button>
          <pre class="mono" style="flex:1;min-width:0;white-space:pre;overflow:auto;padding:10px;border-radius:6px;background:var(--code-bg, rgba(127,127,127,.09));margin:0;font-size:.85em">${`ssh -L ${_cPortN()}:127.0.0.1:${_cPortN()} `}<b>ssh_user</b>@<b>server_ip</b></pre>
        </div>
        <div class="hint" style="margin:0">${Trich("Put in the login and address you already use for SSH — `ssh_user` and `server_ip`.")}</div>
        <div style="margin:10px 0 0">${Trich("When the tunnel is up, the panel will be accessible at {v1}", { v1: html`<a class="mono" style="color:var(--brand);font-weight:600" href=${"http://127.0.0.1:" + _cPortN() + "/"} target="_blank" rel="noopener">${"http://127.0.0.1:" + _cPortN() + "/"}</a>` })}</div>
        <div class="hint" style="margin:8px 0 0">${Trich("*The nodes are unaffected*: they keep dialling the public address, which keeps answering exactly the routes they use.")}</div>
        <div class="hint" style="margin:8px 0 0">${Trich("*To close the door further*, restrict the public panel port in your firewall to the addresses your nodes connect from. The panel can't list them for you — it never sees a node's source address, and behind a proxy it would only see the proxy — so use the addresses you know. ⚠️ Get that list wrong and the fleet stops syncing, so change it while you can still watch the Nodes screen.")}</div>
      </div></div>` : null}
    ${consolePend ? html`<div class="notice" style="margin:0 0 14px;border-color:var(--accent);background:var(--accent-dim, rgba(31,200,214,.08))"><${Ic} i="info"/><div style="min-width:0">
      ${Trich("*Nothing has changed yet.* The panel is now served *both* here and through the tunnel — open it through the tunnel to prove you can reach it. Only then does this address stop serving the panel.")}
      <div class="hint" style="margin:6px 0 0">${Trich("If you don't, everything goes back on its own in *{n}s* — you cannot be locked out by not finishing.", { n: consoleIn })}</div>
      <div class="hint" style="margin:4px 0 0">${Trich("Once it's confirmed, *this tab stops working*: this address will answer only what the nodes ask for. Carry on in the tunnelled one.")}</div>
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
        <a class="btn btn-primary" href=${consoleUrl(consolePend)} target="_blank" rel="noopener">${T("Open the panel through the tunnel to confirm ↗")}</a>
        <button class="btn btn-ghost" disabled=${busy} onClick=${cancelConsole}>${T("Cancel this change")}</button></div>
    </div></div>` : null}

    ${subsOn ? html`<div class="seclabel">${T("Subscription address")}</div>
      <p class="hint" style="margin:0 0 12px">${T("Where the swg-sub page is reached (a separate service; changing it only restarts swg-sub).")}${behindProxy
        ? "" : Trich(" As with the panel, *the URL carries the port*.")}</p>
      <div class="field"><label>${T("Public URL")}</label><input type="text" placeholder=${T("https://sub.example.com  or  https://example.com/swgsub")} value=${sUrl} onInput=${e => setSUrl(e.target.value)}/></div>
      <div class="fieldrow">${ipField(sHost, setSHost, true, sLoopbackDirect)}${behindProxy
        ? portField(sPort, setSPort, sBad || sPortRangeBad, sPortRangeBad ? T("Port must be a number between 1 and 65535") : null)
        : null}</div>
      ${sLoopbackDirect ? loopNote(T("subscription server")) : (sBad ? cfNote : null)}
      ${(behindProxy && (subBindChanged() || subUrlChanged())) ? html`<div class="notice" style="margin:8px 0 12px"><${Ic} i="info"/><div style="min-width:0">
        ${Trich("*Behind a reverse proxy.* Point your proxy at `{v1}` and make sure it serves this URL's path. swg-sub picks it up on Save — a path or domain change reloads it live (no downtime; existing links keep working during a grace), a host/port change restarts it. If the panel has no root helper, it saves and asks you to run `systemctl reload swg-sub`.", { v1: (sHost.trim() || "127.0.0.1") + ":" + _sPortN() })}
      </div></div>` : null}
      ${behindProxy ? html`<details class="nginx-sample" style="margin:8px 0 4px"><summary style="cursor:pointer;color:var(--muted);font-size:.9em">${Trich("Reverse-proxy config for the subscription page (nginx) — full `server { }` for the values above")}</summary>
        <pre class="mono" style="white-space:pre;overflow:auto;padding:10px;border-radius:6px;background:var(--code-bg, rgba(127,127,127,.09));margin:8px 0 6px;font-size:.85em">${nginxServerBlock(sUrl, sHost, _sPortN())}</pre>
        <button class="btn btn-mini" onClick=${() => copy(nginxServerBlock(sUrl, sHost, _sPortN()), T("subscription nginx server block"))}><${Ic} i="copy"/>${T("Copy")}</button>
        <div class="hint" style="margin-top:6px">${Trich("If swg-sub shares the panel's domain, merge its `location` into that server block instead of a second one — then reload nginx.")}</div>
      </details>` : null}` : null}
  </div>`;
}

// Interface-key escrow (lives in Settings → Interfaces): each entry server seals its interface private key under
// the browser-held Encryption Vault key, so a fully-wiped node's interface can be restored with its ORIGINAL key.
// Presentational — the toggle only stages a value; the Settings screen applies it on Save (via ivkSetEscrow) like
// every other field. Needs the Encryption Vault set up (Client configs) — independent of store_configs.
export function InterfaceKeyEscrow({ value, onChange, vaultExists }) {
  if (vaultExists === null || value === null) return html`<div class="hint">${T("Checking…")}</div>`;
  if (!vaultExists) return html`<p class="hint" style="margin:0">${Trich("Set up your *Encryption Vault* first in {v1} — each server's interface key is sealed under it.", { v1: html`<button class="linkbtn" onClick=${() => goSettings("configs")}>${T("Client configs → Encryption")}</button>` })}</p>`;
  return html`<div class="ivk-escrow">
    <label class="ivk-esc-row"><${Switch} on=${!!value} onChange=${onChange}/>
      <span>${Trich("*Escrow interface server keys* — each entry server seals its interface private key to your browser-held *Encryption Vault* key (the panel only ever stores ciphertext). Lets you *restore an interface cleanly after a full wipe / lost box*, with no client re-import. Off ⇒ a wiped node's interfaces can only be recreated with new keys, and every client on them re-imports.")}</span></label>
    ${value && !subSKCached() ? html`<div class="hint" style="margin-top:6px">${T("Keep the Encryption Vault unlocked when you need to restore — releasing an escrowed key requires it.")}</div>` : null}
  </div>`;
}

// Subscription encryption setup. The Subscription Key is generated + wrapped IN THE BROWSER; the server only
// ever gets the wrapped form. It's shown once (like 2FA recovery codes) and is independent of the login password.
export function SubVaultCard() {
  const [state, setState] = useState({ loading: true });
  const [pw, setPw] = useState(""); const [busy, setBusy] = useState(false);
  const [sk, setSk] = useState(null);                    // the shown-once Subscription Key
  const [resetMode, setResetMode] = useState(false); const [confirm, setConfirm] = useState("");
  const [shown, setShown] = useState(null);   // the encryption key, revealed on demand while the vault is unlocked
  const load = () => api.subVault().then(r => setState({ loading: false, exists: !!(r && r.ok && r.data && r.data.exists) })).catch(() => setState({ loading: false, exists: false }));
  useEffect(() => { load(); }, []);
  const create = async () => {
    if (!pw) return; setBusy(true);
    try { setSk(await subVaultCreate(pw)); setPw(""); }
    catch (e) { toast((e && e.message) || T("Setup failed"), "err"); }
    setBusy(false);
  };
  const doReset = async () => {
    setBusy(true); const r = await api.subReset(); setBusy(false);
    if (r && r.ok) { subForget(); setResetMode(false); setConfirm(""); setSk(null); load(); toast(T("Config encryption reset."), "ok"); }   // drop the now-stale cached SK
    else toast(srvText(r) || T("Reset failed"), "err");
  };
  if (state.loading) return html`<div class="hint">${T("Checking…")}</div>`;
  if (sk) return html`<div class="notice ok"><div style="min-width:0">
    ${Trich("*Save your encryption key now — it is shown only once.* It protects every stored client config (and your subscriptions) and is independent of your login password; store it somewhere safe (a password manager). Lose it and your login both, and you'd re-key the affected peers.")}
    <div class="tokenbox" style="margin:8px 0;word-break:break-all">${sk}</div>
    <div class="chiprow">
      <button class="btn btn-mini" onClick=${() => copy(sk, T("Encryption key copied"))}><${Ic} i="copy"/>${T("Copy")}</button>
      <button class="btn btn-mini" onClick=${() => downloadConf(sk, "swg-config-key")}><${Ic} i="download"/>${T("Download")}</button>
      <span class="grow"></span>
      <button class="btn btn-primary btn-mini" onClick=${() => { setSk(null); load(); }}>${T("I've saved it")}</button>
    </div></div></div>`;
  if (!state.exists) return html`<${Fragment}>
    <p class="hint" style="margin:0 0 8px">${T("Set up once. Confirm your panel password — an encryption key is generated in your browser and shown once; the server only ever stores it wrapped, so it can't read your clients' private keys.")}</p>
    <div class="fieldrow">
      <div class="field"><label>${T("Confirm password")}</label><input type="password" value=${pw} onInput=${e => setPw(e.target.value)} autocomplete="current-password"/></div>
      <div class="field" style="flex:none;align-self:end"><button class="btn btn-primary" disabled=${busy || !pw} onClick=${create}>${busy ? T("Setting up…") : T("Set up encryption")}</button></div>
    </div><//>`;
  return html`<${Fragment}>
    <div class="notice ok" style="margin-bottom:8px"><${Ic} i="check"/><span>${Trich("Your *Encryption Vault* is configured — stored configs are wrapped automatically, and their QRs (and any subscription links) keep working across your password changes.")}</span></div>
    <p class="hint" style="margin:0 0 8px">${Trich("The vault opens with your *panel password*, which follows every change you make in the panel. Your *encryption key* opens it too — that's what gets you back in if the panel password is ever reset on the server with *swg-passwd*, so keep a copy somewhere safe.")}</p>
    ${shown ? html`<div class="notice ok"><div style="min-width:0">
        ${Trich("*Your encryption key.* Anyone holding this can read every stored config — treat it like a password and store it in a password manager.")}
        <div class="tokenbox" style="margin:8px 0;word-break:break-all">${shown}</div>
        <div class="chiprow">
          <button class="btn btn-mini" onClick=${() => copy(shown, T("Encryption key copied"))}><${Ic} i="copy"/>${T("Copy")}</button>
          <button class="btn btn-mini" onClick=${() => downloadConf(shown, "swg-config-key")}><${Ic} i="download"/>${T("Download")}</button>
          <span class="grow"></span>
          <button class="btn btn-ghost btn-mini" onClick=${() => setShown(null)}>${T("Hide")}</button>
        </div></div></div>` : null}
    ${resetMode
      ? html`<div class="notice warn"><div style="min-width:0">${Trich("*Reset drops all stored encrypted configs and invalidates every subscription URL.* You'll set up a new encryption key afterwards, then re-issue affected peers. Type *RESET* to confirm.")}
          <div class="chiprow" style="margin-top:8px"><input type="text" placeholder=RESET value=${confirm} onInput=${e => setConfirm(e.target.value)} style="max-width:120px"/>
            <button class="btn btn-danger btn-mini" disabled=${busy || confirm !== "RESET"} onClick=${doReset}>${T("Reset encryption")}</button>
            <button class="btn btn-ghost btn-mini" onClick=${() => { setResetMode(false); setConfirm(""); }}>${T("Cancel")}</button></div></div></div>`
      : html`<div class="chiprow">${shown ? null : html`<button class="btn btn-ghost btn-mini" disabled=${!subSKCached()}
            title=${subSKCached() ? T("Show the key again — it never leaves your browser") : T("Unlock the vault first to reveal its key")}
            onClick=${() => setShown(subKeyB64())}><${Ic} i="key"/>${T("Show encryption key")}</button>`}<span class="grow"></span>
          <button class="btn btn-ghost btn-mini danger" onClick=${() => setResetMode(true)}>${T("Reset encryption…")}</button></div>`}
  <//>`;
}
// The one-time "Encrypt stored configs" migration prompt — shown in Client configs whenever LEGACY plaintext
// configs are still on the panel (Store.configsPlaintext). Requires the vault (set it up in the card above first)
// + the encryption key unlocked; runs runConfigMigration (encrypt-all → capture overrides → purge plaintext where
// a blob exists), then reports peers that couldn't be encrypted (→ rekey). Resumable: re-running does the rest.
export function ConfigMigrationCard() {
  useStore();                          // re-render as the plaintext count drops after a pass
  const [busy, setBusy] = useState(false);
  const [pw, setPw] = useState("");
  const [report, setReport] = useState(null);
  const [vaultExists, setVaultExists] = useState(true);
  useEffect(() => { api.subVault().then(r => setVaultExists(!!(r && r.ok && r.data && r.data.exists))).catch(() => {}); }, []);
  const n = Store.configsPlaintext || 0;
  if (n <= 0 && !report) return null;                          // nothing to migrate
  const flaggedNames = report ? report.flagged.map(pid => {
    const p = (Store.recon.peers || []).find(x => x.id === pid) || {};
    return (p.name ? p.name + " · " : "") + (p.title || "peer");
  }) : [];
  const run = async () => {
    if (!subSKCached()) {                                  // a cached SK ⇒ the vault exists (e.g. just set up this session)
      if (!vaultExists) { toast(T("Set up the encryption key above first."), "err"); return; }
      if (!pw) { toast(T("Enter your panel password to unlock the encryption key."), "err"); return; }
      try { await subUnlock(pw); setPw(""); } catch (e) { toast((e && e.message) || T("Unlock failed"), "err"); return; }
    }
    setBusy(true);
    try {
      const rep = await runConfigMigration();
      setReport(rep);
      // TWO WHOLE SENTENCES, not one glued from fragments: word order differs between languages and a
      // sentence assembled with `+` cannot be reordered by a translator. This was a bare template literal
      // — no T() anywhere in it — so a Russian panel got the whole toast in English.
      toast(rep.purged
        ? T("Encrypted {v1} · purged {v2} plaintext.", { v1: plural(rep.migrated, "config"), v2: rep.purged })
        : T("Encrypted {v1}.", { v1: plural(rep.migrated, "config") }), "ok");
    } catch (e) { toast((e && e.message) || T("Migration failed"), "err"); }
    setBusy(false);
  };
  const pwField = html`<input class="subpw" type="password" style="max-width:220px" value=${pw} autocomplete="off"
    placeholder=${T("Panel password (unlocks the encryption key)")} onKeyDown=${e => { if (e.key === "Enter") run(); }} onInput=${e => setPw(e.target.value)}/>`;
  return html`<div class=${"notice " + (n > 0 ? "warn" : "ok")} style="margin-top:10px"><div style="min-width:0">
    ${n > 0
      ? Trich("*{v1} in plaintext still on the panel.* Encrypt them so the server can no longer read a client private key. Safe and resumable — the plaintext is deleted only after its encrypted copy exists.", { v1: plural(n, "config") })
      : Trich("*All stored configs are encrypted.*")}
    ${report ? html`<div class="hint" style="margin-top:8px">${Trich("Encrypted {v1} of {v2} · purged {v3} plaintext", { v1: html`<b>${report.migrated}</b>`, v2: report.total, v3: html`<b>${report.purged}</b>` })}${report.orphansPurged ? ` (+${report.orphansPurged} orphan)` : ""}${report.remaining ? ` · ${report.remaining} still plaintext` : ""}.
      ${report.flagged.length ? html`<div style="margin-top:6px">${(() => {
        /* The Trich call is REPEATED per branch instead of choosing the key first. A key picked by a
           ternary never reaches the catalog: every i18n tool reads the literal that DIRECTLY follows the
           call, so both of these sentences were absent from ru.js and rendered in English forever — with
           the audit green, because it never knew they were keys. Verbose here, correct everywhere else. */
        const a = { v1: plural(report.flagged.length, "peer"), v2: flaggedNames.slice(0, 8).join(", ") + (flaggedNames.length > 8 ? T(" +{n} more", { n: flaggedNames.length - 8 }) : "") };
        return report.flagged.length === 1
          ? Trich("*{v1}* couldn't be encrypted (unassigned, or no stored key) — *rekey* or assign it to include: {v2}.", a)
          : Trich("*{v1}* couldn't be encrypted (unassigned, or no stored key) — *rekey* or assign them to include: {v2}.", a);
      })()}</div>` : html`<div style="margin-top:6px">${T("Every assigned peer with a stored key is encrypted.")}</div>`}</div>` : null}
    <div class="chiprow" style="margin-top:8px">
      ${(n > 0 && !subSKCached()) ? pwField : null}
      ${n > 0 ? html`<button class="btn btn-primary btn-mini" disabled=${busy || (!vaultExists && !subSKCached())} onClick=${run}>${busy ? T("Encrypting…") : (report ? T("Encrypt remaining") : T("Encrypt stored configs"))}</button>` : null}
    </div>
  </div></div>`;
}
export function PanelSettingsScreen() {
  // NOTE: deliberately NOT subscribed to the 5s poll (no useStore) — this is an edit form seeded from a
  // snapshot at mount. Re-rendering every poll re-diffs every controlled input (the source of the checkbox
  // repaint flicker) and is pointless for a form; it still re-renders on its own edits (setNodeEdits etc.),
  // and save() re-polls + reseeds. A node added/renamed mid-edit just won't reflect until you re-enter.
  const ps = Store.panelSettings || {};
  const idf = ps.interface_defaults || {}; const mir = ps.mirrors || {}; const adv = ps.advanced || {};
  const declarative = !!((Store.env || {}).declarative);   // → the subscription address is a module option, not a field here
  const [dns, setDns] = useState((idf.dns || []).join(", "));
  const [mtu, setMtu] = useState(String(idf.mtu || 1280));
  const [ka, setKa] = useState(String(idf.keepalive || 25));
  const [awgDef, setAwgDef] = useState(() => ({ ...(idf.awg_params || {}) }));   // new-interface AWG obfuscation
  // only FILLED cells count: a blank one means "leave it to the node", so clearing a cell must read as
  // back-to-default rather than as a change, and must not be sent as an empty override.
  const awgTrim = o => AWG_KEYS.reduce((a, k) => { const v = String((o || {})[k] ?? "").trim(); if (v) a[k] = v; return a; }, {});
  const [awgOpen, setAwgOpen] = useState(false);
  const [geoMir, setGeoMir] = useState(mir.geo || "");
  const [turnMir, setTurnMir] = useState(mir.turn || "");
  // Geo-data: catalog provider enable/disable + scheduled list refresh (replacing the geo mirror).
  const _provReg = Store.catalogProviders || [];
  // Only the providers that HAVE a switch. Curated (`builtin`) is not one: it never had one that did anything,
  // so it is neither staged here nor sent, and the stored map loses its dead key on the next save (§6.5).
  const _provTog = _provReg.filter(p => !p.builtin);
  const [provEnabled, setProvEnabled] = useState(() => Object.fromEntries(_provTog.map(p => [p.id, p.enabled !== false])));
  const _gu = ps.geo_update || {};
  const [guEvery, setGuEvery] = useState(String(_gu.every_days == null ? 1 : _gu.every_days));
  const [guAt, setGuAt] = useState(_gu.at || "04:00");
  const [geoUpdating, setGeoUpdating] = useState(false);   // the Update-all-lists button in flight → poll provider status
  const updateAllLists = async () => {
    setGeoUpdating(true);
    const r = await api.geoUpdate();
    if (!r || !r.ok) { setGeoUpdating(false); return toast(srvText(r) || T("Couldn't start update"), "err"); }
    // poll /api/state until no provider is still "updating" (or a 25s cap)
    const t0 = Date.now();
    const tick = async () => { await Store.poll();
      const busy = (Store.catalogProviders || []).some(p => p.status === "updating");   // i18n-keys
      if (busy && Date.now() - t0 < 25000) return setTimeout(tick, 1500);
      setGeoUpdating(false); };
    setTimeout(tick, 1500);
  };
  const retryProvider = async (pid) => {   // manual retry after a provider's automatic fetch retries (4×, backoff) all failed
    const r = await api.geoProviderRetry(pid);
    if (!r || !r.ok) return toast(srvText(r) || T("Couldn't retry"), "err");
    const t0 = Date.now();
    const tick = async () => { await Store.poll();
      const busy = (Store.catalogProviders || []).some(p => p.id === pid && p.status === "downloading");
      if (busy && Date.now() - t0 < 25000) return setTimeout(tick, 1500); };
    setTimeout(tick, 1500);
  };
  /* Give up on a provider that is still fetching. The socket underneath cannot be interrupted — four tries at
     a 30s timeout against GitHub's 60-req/h window run to completion whatever we do — so the panel bumps that
     provider's generation, discards whatever comes back, and clears the row now. It also turns the provider
     OFF, and the local switch follows so the form is not left dirty against a server that already said no. */
  const cancelProvider = async (pid) => {
    const r = await api.geoProviderCancel(pid);
    if (!r || !r.ok) return toast(srvText(r) || T("Couldn't cancel"), "err");
    setProvEnabled(m => ({ ...m, [pid]: false }));
    await Store.poll();
  };
  /* Turning a provider OFF is the one move on this row that reaches the fleet: every rule naming one of its
     lists goes inert on the next sync, and until now that happened without a word (§6.4). So the switch asks
     first whenever any rule uses it, and names how far it reaches.

     The switch is a controlled checkbox that the click has ALREADY flipped in the DOM by the time this runs,
     and deferring the answer to a dialog means nothing here sets `on`. It still snaps back, because the modal
     stack is state on `App` — opening the dialog re-renders this tree, and preact re-syncs `checked` against
     its prop on every pass. Measured: wrong for the click's own tick, right by the next microtask. A local
     state bump to force that render was written, then dropped when breaking it changed nothing; if the modal
     host ever moves to a root of its own (as Portal did), this is where it will need one. */
  const setProvOn = (p, v) => {
    const u = v ? null : providerUsage(p.id);
    if (!u || !u.rules) return setProvEnabled(m => ({ ...m, [p.id]: v }));
    openConfirm({
      title: T("Turn off {v1}?", { v1: p.label }), warn: true, confirmLabel: T("Turn it off"),
      body: Trich("*{v1}* is used by {v2} on {v3}. Turning it off hides its lists and stops those rules routing on every node — the rules themselves stay, and start working again when you turn it back on. Nothing reaches the fleet until you save.", {
        v1: p.label, v2: plural(u.rules, "prep|rule"), v3: plural(u.ifaces, "prep|interface") }),
      onConfirm: () => setProvEnabled(m => ({ ...m, [p.id]: false })),
    });
  };
  // Transient "updated" / T("up to date") — show for 5s AFTER a busy→done transition, then hide. In-progress
  // (downloading/updating) always shows; failed persists (with Retry). No flash on first load (statuses stay hidden).
  const [provFlash, setProvFlash] = useState({});   // pid -> expiry ts
  const _provSeen = useRef({});
  useEffect(() => {
    const now = Date.now(), seen = _provSeen.current; let next = null;
    for (const p of (Store.catalogProviders || [])) {
      const prev = seen[p.id];
      if (p.status !== prev) {
        if (prev !== undefined && (p.status === "updated" || p.status === "uptodate")) { next = next || { ...provFlash }; next[p.id] = now + 5000; }   // i18n-keys
        seen[p.id] = p.status;
      }
    }
    if (next) setProvFlash(next);
  }, [Store.catalogProviders]);
  useEffect(() => {
    const exps = Object.values(provFlash).filter(t => t > Date.now());
    if (!exps.length) return;
    const t = setTimeout(() => setProvFlash(f => ({ ...f })), Math.min(...exps) - Date.now() + 50);
    return () => clearTimeout(t);
  }, [provFlash]);
  const _scMode = Store.storeMode || "encrypted";   // the RESOLVED enum (server considers the panel/fleet default)
  const [sc, setSc] = useState(_scMode);
  const [tput, setTput] = useState(ps.throughput_perspective === "peers" ? "peers" : "nodes");
  const [tunit, setTunit] = useState(ps.throughput_units === "bits" ? "bits" : "bytes");
  const [staleS, setStaleS] = useState(String(Math.round((adv.node_stale_ms || 30000) / 1000)));
  const [graceS, setGraceS] = useState(String(Math.round((adv.peer_grace_ms || 60000) / 1000)));
  const [ttlD, setTtlD] = useState(String(adv.geo_ttl_days || 3));
  const [topTalk, setTopTalk] = useState(String(ps.top_talkers || 10));
  const [topDest, setTopDest] = useState(String(ps.top_destinations || 10));
  const [warnDays, setWarnDays] = useState(String(ps.expiry_warn_days == null ? 3 : ps.expiry_warn_days));
  const [lists, setLists] = useState((ps.custom_lists || []).map(l => ({ ...l, _rid: newRid(), targets: customTargets(l) })));
  const [turnEnabledS, setTurnEnabledS] = useState(ps.turn_enabled !== false);   // master turn-proxy switch
  const [turnForks, setTurnForks] = useState(new Set(ps.enabled_turn_forks || TURN_FORKS_DEFAULT));   // forks offered in the install picker
  const [vkLinkS, setVkLinkS] = useState(ps.vk_link || "");   // VK call link baked into generated turn-proxy client configs
  // ---- themed colour pickers ({dark,light} each) — Interfaces / Display / Turn sections ----
  const asThemed = (v, dd, dl) => (v && typeof v === "object") ? { dark: v.dark || dd, light: v.light || dl } : { dark: v || dd, light: v || dl };
  const sameThemed = (a, dd, dl) => (a.dark || "").toLowerCase() === dd.toLowerCase() && (a.light || "").toLowerCase() === dl.toLowerCase();
  const _bprovs = (Store.blockCatalog || {}).providers || [];   // content-filter feeds share the provider_colors map (ids never collide with catalog ids)
  const _provColDefault = p => {
    const c = CAT_PROVIDER_DEFAULTS[p];
    if (c) return { dark: c.color, light: c.colorL };
    const bp = _bprovs.find(x => x.id === p);
    if (bp && bp.color) return { dark: bp.color, light: bp.color_l || bp.color };   // block feeds ship a dark + light default hex
    if (p === "custom") return { dark: "#8A94A6", light: "#5E6875" };
    return { dark: "#8FA8C0", light: "#5E7085" };
  };
  const _provColKeys = [..._provReg.map(p => p.id), ..._bprovs.map(p => p.id), "custom"];
  const [provColors, setProvColors] = useState(() => Object.fromEntries([..._provReg.map(p => p.id), "custom"].map(k => [k, asThemed((ps.provider_colors || {})[k], _provColDefault(k).dark, _provColDefault(k).light)])));
  useEffect(() => {   // block catalog loads async — seed its providers' default colours once present (only keys not already set)
    if (!_bprovs.length) return;
    setProvColors(c => { let ch = false; const n = { ...c }; for (const p of _bprovs) if (n[p.id] === undefined) { n[p.id] = asThemed((ps.provider_colors || {})[p.id], p.color, p.color_l || p.color); ch = true; } return ch ? n : c; });
  }, [Store.blockCatalog]);
  const provColorOverrides = () => { const o = {}; for (const k of _provColKeys) { const d = _provColDefault(k); const t = asThemed(provColors[k], d.dark, d.light); if (!sameThemed(t, d.dark, d.light)) o[k] = t; } return o; };
  const [customEnabled, setCustomEnabled] = useState(ps.custom_lists_enabled !== false);
  const [forkColors, setForkColors] = useState(() => Object.fromEntries(turnForkList().map(f => [f.id, asThemed((ps.turn_fork_colors || {})[f.id], f.color, f.colorL)])));
  const _tu = ps.turn_update || {};   // turn-proxy auto-update schedule: every_days (0=off) + node-checked panel-local hour
  const [tuEvery, setTuEvery] = useState(String(_tu.every_days == null ? 0 : _tu.every_days));
  const [tuAt, setTuAt] = useState(_tu.at || "04:00");
  const [ifaceColors, setIfaceColors] = useState(() => ({
    wg: asThemed((ps.iface_colors || {}).wg, IFACE_COLOR_DEFAULTS.wg.dark, IFACE_COLOR_DEFAULTS.wg.light),
    awg: asThemed((ps.iface_colors || {}).awg, IFACE_COLOR_DEFAULTS.awg.dark, IFACE_COLOR_DEFAULTS.awg.light),
    wdtt: asThemed((ps.iface_colors || {}).wdtt, IFACE_COLOR_DEFAULTS.wdtt.dark, IFACE_COLOR_DEFAULTS.wdtt.light),
    csqtt: asThemed((ps.iface_colors || {}).csqtt, IFACE_COLOR_DEFAULTS.csqtt.dark, IFACE_COLOR_DEFAULTS.csqtt.light) }));
  const [themeColorS, setThemeColorS] = useState(clampBrand(ps.theme_color || THEME_COLOR_DEFAULT, false));         // dark-mode accent (shown = applied)
  const [themeColorLightS, setThemeColorLightS] = useState(clampBrand(ps.theme_color_light || THEME_COLOR_LIGHT_DEFAULT, true));   // light-mode accent
  const themeVal = { dark: themeColorS, light: themeColorLightS };   // the theme accent as one themed swatch
  // peer-health DETECTION toggles (not colours): each condition ON by default; unchecking stops it flagging the status.
  const _sc = ps.status_conditions || {};
  const [statusConds, setStatusConds] = useState({ blocked: _sc.blocked !== false, faulty: _sc.faulty !== false });
  // interface-key escrow (Interfaces section): staged like a field — the toggle sets a pending value; Save applies it.
  const [ivkEscrow, setIvkEscrow] = useState(null);           // pending value (null = still loading)
  const [ivkEscrowInit, setIvkEscrowInit] = useState(null);   // saved value → dirty when they differ
  const [ivkVaultExists, setIvkVaultExists] = useState(null); // vault set up? escrow needs it
  useEffect(() => { api.subVault().then(r => { const okd = !!(r && r.ok && r.data); const on = okd && !!r.data.ivk_enabled; setIvkEscrow(on); setIvkEscrowInit(on); setIvkVaultExists(okd ? !!r.data.exists : false); }).catch(() => setIvkVaultExists(false)); }, []);
  // overrides derived from a raw source (state OR the stored panel-settings), normalized identically so a legacy
  // single-colour value in panel-settings compares equal to its normalized {dark,light} form (no phantom "dirty").
  const forkOvFrom = src => { const o = {}; for (const f of turnForkList()) { const t = asThemed((src || {})[f.id], f.color, f.colorL); if (!sameThemed(t, f.color, f.colorL)) o[f.id] = t; } return o; };
  const ifaceOvFrom = src => { const o = {}; for (const k of ["wg", "awg", "wdtt", "csqtt"]) { const t = asThemed((src || {})[k], IFACE_COLOR_DEFAULTS[k].dark, IFACE_COLOR_DEFAULTS[k].light); if (!sameThemed(t, IFACE_COLOR_DEFAULTS[k].dark, IFACE_COLOR_DEFAULTS[k].light)) o[k] = t; } return o; };
  const forkColorOverrides = () => forkOvFrom(forkColors);
  const ifaceColorOverrides = () => ifaceOvFrom(ifaceColors);
  const statusCondsOut = () => ({ blocked: statusConds.blocked, faulty: statusConds.faulty });
  const themeColorOut = () => themeColorS.toLowerCase() === THEME_COLOR_DEFAULT.toLowerCase() ? "" : themeColorS;
  const themeColorLightOut = () => themeColorLightS.toLowerCase() === THEME_COLOR_LIGHT_DEFAULT.toLowerCase() ? "" : themeColorLightS;
  // deployed version(s) of a fork across the fleet (from snapshots) — "" if it's never been installed
  // deployed versions of a fork across the fleet. Classic forks come from snap.turn_proxies; WDTT *and csqtt*
  // forks own their interface so they live in snap.wdtt / snap.csqtt (keyed by the instance's `fork`), and don't
  // report a binary version yet → show "installed" so a deployed one reads as used, not T("not yet used").
  // csqtt was missing here, so a node running two csqtt servers still showed that fork as never used.
  const forkVersions = fid => { const v = new Set();
    for (const snap of Object.values(Store.stats || {})) {
      for (const tp of (snap.turn_proxies || [])) if (tp.service && turnFork(tp.service) === fid && tp.version) v.add(tp.version);
      for (const w of [...(snap.wdtt || []), ...(snap.csqtt || [])]) if (w && w.fork === fid) v.add(w.version || "installed");   // i18n-keys
    }
    return [...v]; };
  // per-NODE view of a fork for the hover bubble: one row per node carrying its version + whether it's mid-update
  // (a shared per-fork binary → one version/node; updating if ANY of its instances is installing or Update-clicked).
  const forkNodeStates = fid => {
    const m = {};   // nodeId -> {version, installing (real, clears when done), updatePending (Update-clicked, 120s hint)}
    for (const [nid, snap] of Object.entries(Store.stats || {})) {
      for (const tp of (snap.turn_proxies || [])) {
        if (!tp.service || turnFork(tp.service) !== fid) continue;
        const cur = m[nid] || { version: "", installing: false, updatePending: false };
        if (tp.version) cur.version = tp.version;
        if (tp.installing) cur.installing = true;
        const uk = nid + "|" + tp.service;
        if (turnUpdating[uk] && Date.now() < turnUpdating[uk]) cur.updatePending = true;
        m[nid] = cur;
      }
      for (const w of [...(snap.wdtt || []), ...(snap.csqtt || [])]) {   // self-contained kinds (keyed by fork, usually no version string)
        if (!w || w.fork !== fid) continue;
        const cur = m[nid] || { version: "", installing: false, updatePending: false };
        cur.version = w.version || cur.version || "installed";   // i18n-keys
        if (w.active && w.active !== "active") cur.installing = true;   // starting / awaiting restore
        m[nid] = cur;
      }
    }
    return Object.entries(m).map(([node, v]) => ({ node, ...v })).sort((a, b) => Store.byNode(a.node, b.node));
  };
  const [turnCheck, setTurnCheck] = useState({});   // {forkId: {status:'checking'|'uptodate'|'update', latest}}
  const checkTurnUpdates = async () => {
    setTurnCheck(Object.fromEntries(turnForkList().map(f => [f.id, { status: "checking" }])));
    const r = await api.turnCheckUpdates({ forks: turnForkList().map(f => ({ id: f.id, owner: f.owner })) });
    const latest = (r && r.ok && r.data.latest) || {};
    const next = {};
    for (const f of turnForkList()) {
      const lt = latest[f.id] || "", dep = forkVersions(f.id);
      next[f.id] = (lt && dep.length && dep.some(v => v !== lt)) ? { status: "update", latest: lt } : { status: "uptodate" };
    }
    setTurnCheck(next);
    setTimeout(() => setTurnCheck(c => Object.fromEntries(Object.entries(c).map(([k, v]) => [k, v.status === "update" ? v : {}]))), 5000);   // T("up to date") clears after 5s; "update" persists
  };
  // update every deployed instance of a fork to `latest` — reinstall (re-download binary) on each (node,service)
  // A node whose turn management is off does not IGNORE a request the panel stages — it fails it, and
  // that lands as a red error tag on a node whose operator asked for nothing, with a pending that never
  // clears (the node never reports a new version). Same for an architecture with no published build.
  // Every control that offers this by hand is already gated on these two flags (js/turn.js, js/iface.js);
  // this loop walks the SNAPSHOTS, which know nothing about either, so it has to ask.
  const canTurnAct = nid => { const n = (Store.nodes || []).find(x => x.id === nid); return !!(n && n.turn_manage && n.turn_arch_ok !== false); };
  const skipNote = skipped => { if (skipped) toast(T("{v1} skipped — turn-proxy management is off there, or their architecture has no published build.", { v1: plural(skipped, "node") }), "err"); };
  const updateFork = async (fid, latest) => {
    const fork = turnForkList().find(x => x.id === fid) || {};
    if (fork.kind === "csqtt") {   // csqtt: one binary per NODE — release each node's hold and it takes the current build
      const all = [];
      for (const [nid, snap] of Object.entries(Store.stats || {})) for (const c of (snap.csqtt || [])) if (c && c.iface) all.push({ node: nid, iface: c.iface });
      const ct = all.filter(t => canTurnAct(t.node));
      const cskip = new Set(all.filter(t => !canTurnAct(t.node)).map(t => t.node)).size;
      if (!ct.length) { skipNote(cskip); return; }
      setTurnCheck(c => ({ ...c, [fid]: { status: "updating", latest } }));   // i18n-keys
      turnUpdateTarget[fid] = { ver: latest, until: Date.now() + 120000 };
      const seen = new Set();
      for (const t of ct) { if (seen.has(t.node)) continue; seen.add(t.node); await api.csqttVersion({ node: t.node, iface: t.iface, ver: "" }); }
      await Store.poll();
      setTurnCheck(c => ({ ...c, [fid]: {} }));
      toast(T("Update requested on {v1} — each node applies it on its next sync.", { v1: plural(seen.size, "node") }), "ok");
      skipNote(cskip);
      return;
    }
    if (fork.kind === "wdtt") {   // WDTT: release each instance's hold → the node swaps its shared binary to the current published build
      const all = [];
      for (const [nid, snap] of Object.entries(Store.stats || {})) for (const w of (snap.wdtt || [])) if (w && w.fork === fid && w.iface) all.push({ node: nid, iface: w.iface });
      const wt = all.filter(t => canTurnAct(t.node));
      const wskip = new Set(all.filter(t => !canTurnAct(t.node)).map(t => t.node)).size;
      if (!wt.length) { skipNote(wskip); return; }
      setTurnCheck(c => ({ ...c, [fid]: { status: "updating", latest } }));   // i18n-keys
      for (const t of wt) await api.wdttVersion({ node: t.node, iface: t.iface, ver: "" });
      await Store.poll();
      setTurnCheck(c => ({ ...c, [fid]: {} }));
      toast(T("Update requested on {v1} — each node applies it on its next sync.", { v1: plural(wt.length, "WDTT server") }), "ok");
      skipNote(wskip);
      return;
    }
    const owner = fork.owner || "";
    const all = [];
    for (const [nid, snap] of Object.entries(Store.stats || {})) for (const tp of (snap.turn_proxies || [])) if (tp.service && turnFork(tp.service) === fid) all.push({ node: nid, service: tp.service });
    const targets = all.filter(t => canTurnAct(t.node));
    const skipped = new Set(all.filter(t => !canTurnAct(t.node)).map(t => t.node)).size;
    if (!targets.length) { skipNote(skipped); return; }
    setTurnCheck(c => ({ ...c, [fid]: { status: "updating", latest } }));   // i18n-keys
    turnUpdateTarget[fid] = { ver: latest, until: Date.now() + 120000 };   // persists past the turnCheck reset so the bubble can show per-node updating→updated
    for (const t of targets) { turnUpdating[t.node + "|" + t.service] = Date.now() + 120000; await api.turnReinstall({ node: t.node, service: t.service, owner }); }
    await Store.poll();
    setTurnCheck(c => ({ ...c, [fid]: {} }));
    toast(T("Update requested on {v1} — each node applies it on its next sync.", { v1: plural(targets.length, "proxy") }), "ok");
    skipNote(skipped);
  };
  // Security (panel login) — folded into the unified Save: credentials update on Save (if changed), and a
  // validation error blocks Save. Username is loaded from the server once on mount.
  const [secUser, setSecUser] = useState(""); const [secOrigUser, setSecOrigUser] = useState("");
  const [secCur, setSecCur] = useState(""); const [secNp, setSecNp] = useState(""); const [secNp2, setSecNp2] = useState("");
  const [secAuth, setSecAuth] = useState(true);   // false = panel has no login configured (fields disabled)
  const [sec2fa, setSec2fa] = useState(false);    // TOTP currently enabled on the account
  useEffect(() => { api.account().then(r => { if (r && r.ok) { setSecAuth(r.data.auth_enabled !== false); setSec2fa(!!r.data.twofa_enabled); if (r.data.username) { setSecUser(r.data.username); setSecOrigUser(r.data.username); } } }); }, []);
  const secChanged = () => secAuth && (secUser.trim() !== secOrigUser || !!secNp);
  // The exits list reports its own Save block up here, the same way Access & TLS reports its {dirty,busy,run}:
  // the verdict on a device is the SERVER's (§11.3 — one grammar, one reader), so the screen is told the
  // sentence rather than deriving it. Only a NEW or CHANGED device can set it; see NodeExitRow.
  //
  // ⚠️ KEYED BY NODE, AND SAVE IS FLEET-WIDE. The rows exist only for the node in the lens, but `save()`
  // sends every node whose draft differs — so a guard scoped to the visible node lets a bad row on another
  // node through to a 400 the operator cannot see the cause of. The verdicts therefore outlive the rows,
  // and the blank-device half (which needs no server) is checked over every draft here.
  const [exitWhy, setExitWhy] = useState({});
  const exitErr = () => {
    for (const n of (Store.nodes || [])) {
      const ex = (nodeEdits[n.id] || {}).exits || [];
      // Only an ADOPTED exit needs a device typed into it — an imported one's device is minted from its id
      // by the server, so demanding one here would block the Save that creates it.
      const msg = ex.some(x => (x.producer || "adopted") !== "imported" && !String(x.device || "").trim())
        ? T("Choose a device for the new exit, or remove it.")
        : ex.some(x => x.producer === "imported" && x.provider === "profile"
                       && !String(x.profile_text || "").trim() && !(x.profile && x.profile.address))
        ? T("Paste a WireGuard profile for the new exit, or remove it.") : (exitWhy[n.id] || "");
      // Name the node when it is not the one on screen, or the Save button is disabled for a reason the
      // operator is not looking at.
      if (msg) return n.id === selNode ? msg : (n.name + " — " + msg);
    }
    return "";
  };
  const secErr = () => {
    if (!secAuth || !secChanged()) return null;
    if (!secUser.trim()) return T("Username can't be empty.");
    if (secUser.includes(":")) return T("Username can't contain a colon.");
    if (!secCur) return T("Enter your current password to confirm the change.");
    if (secNp && secNp !== secNp2) return T("New passwords don't match.");
    if (secNp && secNp.length < 8) return T("New password must be at least 8 characters.");
    return null;
  };
  const [section, setSection] = useState(takePendingSection() || "display");   // active left-rail section (a Settings activity click can deep-link here)
  useEffect(() => { registerSectionSetter(setSection); return () => registerSectionSetter(null); }, []);   // one-shot section pin + expose setSection so a modal can switch the rail (confirm modal → Access & TLS)
  const [routeTab, setRouteTab] = useState("routing");   // "Routing & Blocking" section: Routing (route→exit) | Blocking (drop) — both gated by the node's mode above
  useEffect(() => { if (routeTab === "blocking" || section === "geo") loadBlockCatalog(); }, [routeTab, section]);   // lazy-load the block catalog for the Blocking tab and the Geo-data Filters-providers list
  const _bkCountTries = useRef(0);
  useEffect(() => {   // list counts resolve in the background on the panel — refetch a few times until they land (or give up)
    if (routeTab !== "blocking") return;
    const bc = Store.blockCatalog; if (!bc) return;
    const pending = Object.values(bc.categories || {}).some(c => (c.sources || []).length && !c.size);
    if (!pending) { _bkCountTries.current = 0; return; }
    if (_bkCountTries.current >= 6) return;
    const t = setTimeout(() => { _bkCountTries.current++; loadBlockCatalog(true); }, 4000);
    return () => clearTimeout(t);
  }, [routeTab, Store.blockCatalog]);
  const [blockProvEdits, setBlockProvEdits] = useState({});   // staged Filters-providers toggle deltas {prov_id:bool} → panelSettings.block_providers (committed by the shared Save)
  const [geoTab, setGeoTab] = useState("routing");   // Geo-data providers card: Routing (list providers) | Blocking (content-filter feeds)
  const [blockEdits, setBlockEdits] = useState({});   // staged block-category deltas {id:{enabled_nodes?,default_on?,sources?,…}} → api.blockCatalogSave (committed by the shared Save)
  const [bkOpen, setBkOpen] = useState({});   // expanded block-category rows (id→bool) — the expand shows/edits the category's lists
  const [blockRemoved, setBlockRemoved] = useState([]);   // custom block-category ids staged for deletion → api.blockCatalogSave removed[]
  const [bkAutoAdd, setBkAutoAdd] = useState(null);   // a just-created category id → auto-open its Add-list picker
  const rsv = ps.reserved || {};
  const [rsvSubnet, setRsvSubnet] = useState(rsv.mesh_subnet || "10.255.0.0/16");
  const [rsvPort, setRsvPort] = useState(String(rsv.mesh_port_base || 9999));
  const [rsvPrefix, setRsvPrefix] = useState(rsv.iface_prefix || "swg_");
  const [awg, setAwg] = useState(ps.mesh_awg || {});
  const [showAwg, setShowAwg] = useState(false);
  const awgSet = AWG_KEYS.some(k => String(awg[k] ?? "").trim() !== "");
  const [showAdv, setShowAdv] = useState(false);
  const [msg, setMsg] = useState(null);
  // subscriptions section state — enable + languages ride the global save; the vault ceremony uses /api/sub/*.
  // The sub's address, URL and certificate now live in the Access & TLS section (access.sub / access.tls).
  const subCfg = ps.subscriptions || {};
  const [subsOn, setSubsOn] = useState(!!subCfg.enabled);
  const [autoGen, setAutoGen] = useState(!!subCfg.auto_generate);   // auto-mint a subscription link for each new user
  const subLangCfg = (subCfg.languages && typeof subCfg.languages === "object") ? subCfg.languages : {};
  const [subLangs, setSubLangs] = useState((subLangCfg.enabled && subLangCfg.enabled.length) ? [...subLangCfg.enabled] : ["en"]);
  const [subLangDef, setSubLangDef] = useState(subLangCfg.default || "en");
  const toggleSubLang = (id, on) => {
    let next = on ? [...new Set([...subLangs, id])] : subLangs.filter(l => l !== id);
    if (!next.length) next = [id];                 // never empty — at least one language
    setSubLangs(next);
    if (next.indexOf(subLangDef) < 0) setSubLangDef(next[0]);   // default must stay enabled
  };
  // per-node pending edits (mode / mesh / egress) — lifted here so switching node or section keeps unsaved
  // changes; the single Save commits the global settings AND one nodeUpdate per changed node.
  const eq = (a, b) => { const c = v => v == null ? "" : Array.isArray(v) ? JSON.stringify([...v].sort()) : typeof v === "object" ? JSON.stringify(Object.keys(v).sort().reduce((o, k) => (o[k] = v[k], o), {})) : String(v); return c(a) === c(b); };
  const nFields = n => ({ routing_mode: n.routing_mode || "kernel", ip_learning: n.ip_learning !== false, endpoint_host: n.endpoint_host || "",
    mesh_subnet: n.mesh_subnet || "", mesh_port: n.mesh_port ? String(n.mesh_port) : "", mesh_prefix: n.mesh_prefix || "",
    default_egress_ip: n.default_egress_ip || "", panel_ip: n.panel_ip || "", mesh_egress_ip: n.mesh_egress_ip || "",
    default_exit: n.default_exit || "",
    endpoint_hosts: [...(n.endpoint_hosts || [])],
    catalog_cats: [...(n.catalog_cats || [])],   // provider-catalog categories opted into on this node (node-lens; separate from the 26 built-ins)
    // ⚠️ REBUILT FROM A KEY LIST ON PURPOSE. /api/state attaches a derived `why_not` to each stored exit, and
    // copying the record wholesale would make the node read DIRTY the moment that verdict changed on the
    // server — a Save button lighting up for an edit nobody made. Only the fields the operator owns.
    exits: (n.exits || []).map(x => ({ id: x.id || "", label: x.label || "", producer: x.producer || "adopted",
      device: x.device || "", enabled: x.enabled !== false, killswitch: !!x.killswitch,
      // adopted only — the source address SNAT'd onto traffic leaving by this device. An imported exit
      // brings its own address in its profile, so the server refuses the field there.
      // adopted only, both of them — and `gw` for the same reason `egress_ip` is here: an imported exit's
      // device is one the panel made, point-to-point, and a gateway down a tunnel would be wrong. This is
      // the typed override for an uplink whose gateway the node cannot infer; blank means "detect it",
      // which is the ordinary case.
      ...(x.producer === "imported" ? {} : { egress_ip: x.egress_ip || "", gw: x.gw || "" }),
      // imported only. `profile_text` is the PASTE BOX and is deliberately NOT seeded from the stored
      // profile: the server never sends the private key back, so seeding it would show the operator a
      // profile that is missing its key and re-submit it as a replacement. Empty box = keep what is stored.
      ...(x.producer === "imported" ? { provider: x.provider || "warp", licence: x.licence || "",
                                        dial_src: x.dial_src || "",
                                        profile: x.profile || null, profile_text: "" } : {}) })),
    mesh_awg: (n.mesh_awg_set && Object.keys(n.mesh_awg_set).length) ? { ...n.mesh_awg_set } : {} });   // per-node mesh obfuscation override ({} = inherit/auto)
  const [nodeEdits, setNodeEdits] = useState(() => Object.fromEntries((Store.nodes || []).map(n => [n.id, nFields(n)])));
  const [orig, setOrig] = useState(() => Object.fromEntries((Store.nodes || []).map(n => [n.id, nFields(n)])));
  const [gridKeep, setGridKeep] = useState([]);   // provider-list rows kept visible after toggling to 0/N nodes (until × removes them)
  const setNV = (nid, patch) => setNodeEdits(e => ({ ...e, [nid]: { ...nFields((Store.nodes || []).find(n => n.id === nid) || {}), ...(e[nid] || {}), ...patch } }));
  const nv = (nid, f) => (nodeEdits[nid] || {})[f];
  const [saved, setSaved] = useState(0);   // timestamp; the green "All settings saved" flash shows while now < saved
  // Access & TLS reports its {dirty,busy,msg,run} up here so the shared footer drives its Save + status like every
  // other section. The ref always holds the latest; accessSig re-renders the footer only when a shown bit changes.
  const accessRef = useRef({ dirty: false, busy: false, msg: null, run: () => {} });
  const [, setAccessSig] = useState("");
  const onAccess = useCallback(s => {
    accessRef.current = s;
    const sig = (s.dirty ? "1" : "0") + (s.busy ? "1" : "0") + "|" + (s.msg ? (s.msg.ok ? "o" : "e") + s.msg.t : "");
    setAccessSig(prev => prev === sig ? prev : sig);
  }, []);
  const save = async () => {
    // Progress lives on the confirm-modal button ("Saving…" spinner) — it stays open until save() resolves. The
    // header shows the green "All settings saved" flash on success. A thrown request (dead/wedged panel, timeout)
    // surfaces here instead of leaving the modal stuck.
    try {
    if (SECTIONS.some(([s]) => glDirty(s))) {   // only rewrite panel_settings when a GLOBAL setting actually changed (nodes go via nodeUpdate below)
      const dirtySecs = SECTIONS.filter(([s]) => glDirty(s)), secLabel = Object.fromEntries(SECTIONS);   // for the activity one-liner + deep-link
      const r = await api.panelSettings({
        _ev: { first: (dirtySecs[0] || [""])[0], sections: dirtySecs.map(([s]) => secLabel[s]).join(", ") },   // display-only: which sections changed (drives the "Settings changed" activity row)
        interface_defaults: { dns: dns.split(",").map(s => s.trim()).filter(Boolean), mtu: +mtu || 1280, keepalive: +ka || 25,
          awg_params: awgTrim(awgDef) },
        mirrors: { geo: geoMir.trim(), turn: turnMir.trim() },
        providers: provEnabled,
        block_providers: blockProvEdits,
        provider_colors: provColorOverrides(),
        custom_lists_enabled: customEnabled,
        geo_update: { every_days: Math.max(0, Math.min(30, parseInt(guEvery) || 0)), at: guAt },
        store_configs: sc === "off" ? "off" : "encrypted",
        subscriptions: { enabled: subsOn, auto_generate: autoGen,   // base_url + serve now live in Access & TLS (access.sub/access.tls)
          languages: { enabled: subLangs, default: subLangDef } },
        throughput_perspective: tput,
        throughput_units: tunit,
        top_talkers: Math.max(1, Math.min(50, parseInt(topTalk) || 10)),
        top_destinations: Math.max(1, Math.min(50, parseInt(topDest) || 10)),
        expiry_warn_days: Math.max(0, Math.min(365, parseInt(warnDays) || 3)),
        reserved: { mesh_subnet: rsvSubnet.trim(), mesh_port_base: +rsvPort || 9999, iface_prefix: rsvPrefix.trim() || "swg_" },
        mesh_awg: awgSet ? awg : {},
        advanced: { node_stale_ms: (+staleS || 30) * 1000, peer_grace_ms: (+graceS || 60) * 1000, geo_ttl_days: +ttlD || 3 },
        custom_lists: lists.map(({ _rid, domains, cidrs, asns, ...l }) => l),   // send id/title/targets/enabled; the backend re-derives domains+cidrs+asns
        turn_enabled: turnEnabledS,
        turn_update: { every_days: Math.max(0, Math.min(30, parseInt(tuEvery) || 0)), at: tuAt },
        enabled_turn_forks: [...turnForks],
        turn_fork_colors: forkColorOverrides(),
        iface_colors: ifaceColorOverrides(),
        status_conditions: statusCondsOut(),
        theme_color: themeColorOut(),
        theme_color_light: themeColorLightOut(),
        vk_link: vkLinkS.trim(),
      });
      if (!r.ok) return setMsg({ ok: false, t: srvText(r) || T("Failed to save.") });
    }
    // interface-key escrow — applied on Save (not on toggle), like every other field. Enabling needs the vault unlocked.
    if (ivkEscrow !== null && ivkEscrow !== ivkEscrowInit) {
      if (ivkEscrow && !subSKCached()) {
        const ok = await new Promise(res => pushModal(html`<${VaultPromptSheet} opts=${{ title: T("Unlock to enable escrow"), reason: T("Enabling interface-key escrow seals each server's interface key under your Encryption Vault key. Unlock it to apply.") }} onDone=${res}/>`));
        if (!ok || !subSKCached()) return setMsg({ ok: false, t: T("Enabling key escrow needs the Encryption Vault unlocked.") });
      }
      try { await ivkSetEscrow(ivkEscrow); setIvkEscrowInit(ivkEscrow); }
      catch (e) { return setMsg({ ok: false, t: (e && e.message) || T("Couldn't update key escrow.") }); }
    }
    // per-node changes: one nodeUpdate per node whose edits differ from the saved baseline
    const dSub = rsvSubnet.trim(), dPort = String(+rsvPort || 9999), dPfx = rsvPrefix.trim() || "swg_";
    let nerr = null;
    for (const n of (Store.nodes || [])) {
      const e = nodeEdits[n.id] || {}, o = orig[n.id] || {};
      if (!Object.keys(nFields(n)).some(k => !eq(e[k], o[k]))) continue;
      const nr = await api.nodeUpdate({ id: n.id, routing_mode: e.routing_mode, ip_learning: e.ip_learning !== false, endpoint_host: (e.endpoint_host || "").trim(),
        mesh_subnet: (e.mesh_subnet || "").trim() === dSub ? "" : (e.mesh_subnet || "").trim(),
        mesh_port: (e.mesh_port || "").trim() === dPort ? "" : (e.mesh_port || "").trim(),
        mesh_prefix: (e.mesh_prefix || "").trim() === dPfx ? "" : (e.mesh_prefix || "").trim(),
        default_egress_ip: e.default_egress_ip || "", panel_ip: e.panel_ip || "", default_exit: e.default_exit || "",
        mesh_egress_ip: e.mesh_egress_ip || "",
        endpoint_hosts: (e.endpoint_hosts || []).map(h => (h || "").trim()).filter(Boolean),
        catalog_cats: e.catalog_cats || [], mesh_awg: e.mesh_awg || {}, exits: e.exits || [] });
      if (!nr.ok) nerr = srvText(nr) || (T("Couldn't save {v1}", { v1: n.name }));
    }
    if (nerr) return setMsg({ ok: false, t: nerr });
    if (Object.keys(blockEdits).length || blockRemoved.length) {   // block-list category edits (availability/defaults/sources/custom) → panel_settings.block_catalog
      const br = await api.blockCatalogSave({ categories: blockEdits, removed: blockRemoved });
      if (!br.ok) return setMsg({ ok: false, t: srvText(br) || T("Couldn't save block lists.") });
      await loadBlockCatalog(true); setBlockEdits({}); setBlockRemoved([]);
    }
    if (Object.keys(blockProvEdits).length) { await loadBlockCatalog(true); setBlockProvEdits({}); }   // Filters-providers toggles committed via panelSettings above → refresh catalog + clear deltas
    // credentials (if changed) — last, since a username/password change re-auths and forces a reload
    if (secChanged()) {
      // Re-wrap the vault BEFORE the credential change lands. /api/account rotates the session secret, so the
      // moment it returns our cookie is dead and subRewrap's own API calls 401 — it swallows that and returns
      // false, silently leaving the vault sealed under the OLD password. Do it while the session is still
      // valid, and roll back if the credential change is then rejected, so a wrong current password leaves
      // the vault exactly as it was. Same SK throughout — no blob is ever re-encrypted.
      let reWrapped = false;
      if (secNp) {
        if (!subSKCached()) { try { await subUnlock(secCur); } catch (_) {} }   // not unlocked this session — the current password is right here
        if (subSKCached()) { try { reWrapped = await subRewrap(secNp); } catch (_) { reWrapped = false; } }
      }
      const ar = await api.accountSave({ username: secUser.trim(), current_password: secCur, new_password: secNp });
      if (!ar.ok) {
        if (reWrapped) { try { await subRewrap(secCur); } catch (_) {} }   // undo — the password never actually changed
        return setMsg({ ok: false, t: srvText(ar) || T("Couldn't update credentials.") });
      }
      setMsg({ ok: true, t: T("Saved. Reloading — sign in with your new credentials…") });
      return setTimeout(() => location.reload(), 1400);
    }
    setMsg(null); setSaved(Date.now() + 4000);   // green "All settings saved" flash in the header
    await Store.poll();
    const fresh = Object.fromEntries((Store.nodes || []).map(n => [n.id, nFields(n)]));
    setNodeEdits(fresh); setOrig(fresh);
    } catch (e) {
      setMsg({ ok: false, t: T("Couldn't save — {v1}", { v1: (e && e.message) || T("the panel didn't respond. Nothing was lost; try again.") }) });
    }
  };
  // Save click → confirm modal listing the modified values + a reprovisioning warning, then commit.
  const REPROV_WARN = T("Heads up: changing a node's mesh subnet, interface prefix, or AWG params re-provisions its mesh links — it briefly drops off the mesh while every peer pulls the new config and reconnects.");
  const diffList = () => {
    const out = [];
    if (listsJSON(lists) !== listsJSON(ps.custom_lists || [])) out.push(T("Routing lists — presets / custom"));
    if (Object.keys(blockEdits).length || blockRemoved.length) out.push(T("Content filters — categories / lists"));
    if (secChanged()) out.push(T("Authentication — panel credentials"));
    if (glDirty("turn")) out.push(T("Turn proxies — forks / colours / VK link"));
    if (glDirty("geo")) out.push(T("Geo data providers"));
    if (glDirty("defaults")) out.push(T("Interfaces — colours / defaults"));
    if (glDirty("configs")) out.push(T("Client configs → {v1}", { v1: sc === "off" ? T("val|off") : T("val|encrypted") }));
    if (glDirty("subs")) out.push(T("Subscriptions — enable / languages"));
    if (glDirty("display")) out.push(T("Display — theme / status timing"));
    if (glDirty("mesh")) out.push(T("System mesh defaults"));
    for (const n of (Store.nodes || [])) {
      const e = nodeEdits[n.id] || {}, o = orig[n.id] || {}, fl = [];
      // The LABEL, not the slug. This line is the last thing an operator reads before applying, and it
      // was the one place in the panel that said `sni_kernel` — a token that appears nowhere else in the
      // UI, next to a mode card that has been calling it "Kernel SNI" the whole time.
      if (!eq(e.routing_mode, o.routing_mode))
        fl.push(T("mode → {v1}", { v1: (MODE_META[e.routing_mode || "kernel"] || {}).label || e.routing_mode }));
      if (!eq(e.ip_learning !== false, o.ip_learning !== false)) fl.push(T("IP learning → {v1}", { v1: e.ip_learning !== false ? T("val|on") : T("val|off") }));
      if (!eq(e.endpoint_host, o.endpoint_host)) fl.push(T("ingress address → {v1}", { v1: e.endpoint_host || T("val|auto") }));
      if (!eq(e.mesh_subnet, o.mesh_subnet)) fl.push(T("mesh subnet → {v1}", { v1: e.mesh_subnet || T("val|default") }));
      if (!eq(e.mesh_port, o.mesh_port)) fl.push(T("mesh port → {v1}", { v1: e.mesh_port || T("val|default") }));
      if (!eq(e.mesh_prefix, o.mesh_prefix)) fl.push(T("prefix → {v1}", { v1: e.mesh_prefix || T("val|default") }));
      if (!eq(e.default_egress_ip, o.default_egress_ip)) fl.push(T("egress IP → {v1}", { v1: e.default_egress_ip || T("val|auto") }));
      if (!eq(e.default_exit, o.default_exit)) fl.push(T("default exit"));
      if (!eq(e.panel_ip, o.panel_ip)) fl.push(T("panel IP → {v1}", { v1: e.panel_ip || T("val|auto") }));
      if (!eq(e.mesh_egress_ip, o.mesh_egress_ip)) fl.push(T("mesh egress IP → {v1}", { v1: e.mesh_egress_ip || T("val|auto") }));
      if (!eq((e.endpoint_hosts || []).filter(Boolean), (o.endpoint_hosts || []).filter(Boolean))) fl.push(T("other names"));
      if (!eq(e.catalog_cats, o.catalog_cats)) fl.push(T("catalog categories"));
      // ⚠️ THE FOURTH LIST A PER-NODE FIELD HAS TO BE NAMED IN, and the one with teeth: `anyDirty` reads
      // SECF, so Save lights up — but `confirmSave` opens on `diffList()`, and a field missing HERE means
      // pressing Save says "No changes to save" and nothing is written. An enabled button that does nothing,
      // with the edits still on screen. Gated by tests/settings_node_fields_selftest.py.
      if (!eq(e.exits, o.exits)) fl.push(T("external exits"));
      if (!eq(e.mesh_awg, o.mesh_awg)) fl.push(T("mesh AWG params"));
      if (fl.length) out.push(n.name + " — " + fl.join(", "));
    }
    return out;
  };
  const needsReprov = () => (Store.nodes || []).some(n => { const e = nodeEdits[n.id] || {}, o = orig[n.id] || {}; return !eq(e.mesh_subnet, o.mesh_subnet) || !eq(e.mesh_prefix, o.mesh_prefix) || !eq(e.mesh_awg, o.mesh_awg); });
  const confirmSave = () => {
    const ch = diffList();
    if (!ch.length) { toast(T("No changes to save."), "ok"); return; }
    const rp = needsReprov();
    openConfirm({ title: T("Save settings"), confirmLabel: T("Save"), busyLabel: T("Saving…"), warn: rp, onConfirm: save,
      body: html`<div class="savediff"><div class="savediff-h">${T("{v1} to apply:", { v1: plural(ch.length, "change") })}</div><ul>${ch.map(c => html`<li>${c}</li>`)}</ul>${rp ? html`<div class="savediff-w">${REPROV_WARN}</div>` : null}</div>`,
      note: html`<div class="savediff-note">${T("Applying can take up to a minute — the nodes reconfigure and re-pull their lists. This stays open until it finishes.")}</div>` });
  };
  const refreshGeo = async () => { const r = await api.refreshGeo(); toast(r.ok ? T("Geo lists will refresh on each node's next sync.") : (srvText(r) || T("Failed")), r.ok ? "ok" : "err"); };
    // Custom lists AUTOSAVE on add/edit/delete — they persist on their own (POST just custom_lists), no global Save needed.
  // Re-baseline the local rows from the server afterwards so the row content + the routing dirty-state both stay correct.
  const persistLists = async newLists => {
    setLists(newLists);
    // `patterns` joins the stripped set for the same reason the other three are stripped: the server
    // re-derives every kind from `targets`, and sending a stale copy alongside is a second source of truth.
    const r = await api.panelSettings({ custom_lists: newLists.map(({ _rid, domains, cidrs, asns, patterns, ...l }) => l) });
    if (!r.ok) return setMsg({ ok: false, t: srvText(r) || T("Couldn't save the list.") });
    // §5.4 — say what the save could not keep. Until now this response was not read for it at all, so an
    // unreadable token (and a list whose every token was unreadable) disappeared into an "ok".
    reportDropped(r);
    await Store.poll();
    const ridById = Object.fromEntries(newLists.filter(l => l.id).map(l => [l.id, l._rid]));   // keep row identity so a per-node toggle / edit doesn't remount every row
    setLists(((Store.panelSettings || {}).custom_lists || []).map(l => ({ ...l, _rid: ridById[l.id] || newRid(), targets: customTargets(l) })));
    setSaved(Date.now() + 2500);
  };
  /* Add or replace one list, then persist the WHOLE array — the array is the save (see persistLists), so
     an edit and an add are the same operation with a different starting point. */
  const saveList = l => persistLists(lists.some(x => x._rid === l._rid)
    ? lists.map(x => (x._rid === l._rid ? l : x)) : [...lists, l]);
  const confirmDeleteList = l => openConfirm({ title: T("Delete custom list"), confirmLabel: T("Delete"), danger: true,
    body: Trich("Delete *{v1}*? It's removed from *every node* it's enabled on, and its interface rules stop matching on the next sync. This can't be undone.", { v1: l.title || T("Untitled list") }),
    onConfirm: () => persistLists(lists.filter(x => x._rid !== l._rid)) });
    const SECTIONS = [["display", "Display"], ["security", "Authentication"], ["access", "Panel access"], ["configs", "Client configs"], ["subs", "Subscriptions"], ["mesh", "Network"], ["exits", "WARP"], ["defaults", "Interfaces"], ["turn", "Turn proxies"], ["routing", "Routing & Blocking"], ["geo", "Geo data providers"], ["integrations", "Integrations"]]   // i18n-keys: canonical (deep-link + persisted section); sectionLabel() below carries the display names
/* The fill-in line the panel writes into a plain-text config when no VK link is set. It has to stay
   byte-identical to turn-artifacts.js's copy: the hint below tells the operator which line to look for in
   the generated file, so a TRANSLATED placeholder would describe something that never appears there. */
const VK_LINK_PLACEHOLDER = "<PASTE VK CALL LINK>";   // i18n-keys: emitted verbatim into generated configs

/* Display names for SECTIONS. The array above stays the canonical key list (the value is the deep-link and
   the persisted section), so only the LABEL is translated — literal T() calls, same as evItemLabel. */
const sectionLabel = k => ({
  display: T("Display"), security: T("Authentication"), access: T("Panel access"), configs: T("Client configs"),
  subs: T("Subscriptions"), mesh: T("Network"), exits: T("val|WARP"), defaults: T("Interfaces"),
  turn: T("Turn proxies"), routing: T("Routing & Blocking"), geo: T("Geo data providers"),
  integrations: T("Integrations"),
}[k] || k);   // i18n-keys
  // per-node context: the node whose mode/lists/mesh/egress we're editing — defaults to the first node (no "default")
  const [selNode, setSelNode] = useState(() => ((Store.nodes || [])[0] || {}).id || "");
  const perNodeSection = section === "routing" || section === "mesh" || section === "exits";
  const nodeRec = (Store.nodes || []).find(n => n.id === selNode);
  const nodeMode = nv(selNode, "routing_mode") || "kernel";       // DRAFT mode being edited (drives the mode card + tabs)
  const setMode = m => setNV(selNode, { routing_mode: m });
  const savedMode = (nodeRec && nodeRec.routing_mode) || "kernel"; // what the node is ACTUALLY running (drives the status runbar — only changes on Save)
  const ipLearn = nv(selNode, "ip_learning") !== false;           // per-node "remember learned IPs" toggle (default on)
  const setIpLearn = v => setNV(selNode, { ip_learning: v });
  /* catalog_cats[] is a PIN, and the only writer is this screen (§1.4). It answers one question — keep this
     list resident on this node even when no rule uses it — and it is emphatically NOT the gate it used to be:
     the rule field offers every list from every enabled provider whether or not it is pinned anywhere.

     So the grid has two kinds of row, and telling them apart is the point. A list a rule NAMES is already
     resident and needs no pin; a list that is only pinned is here because someone wanted it kept. Rendering
     only the pins — which is all this did — described a subset of what each node holds and left the common
     case off the screen entirely. `ruleCats` is that other half, computed once per render for the fleet. */
  const ccOf = nid => nv(nid, "catalog_cats") || [];
  const ruleCats = fleetRuleCats();          // one walk for the whole fleet, from the node record (§1.4)
  const catInUse = (id, nid) => !!(ruleCats[nid] && ruleCats[nid].has(id));
  // WHICH INTERFACES name this list, on the node the lens is showing. Read from the node record's
  // `rule_cats` ({iface: [cat]}) and NOT from `Store.describe`, which only carries interfaces the node has
  // reported this cycle — a quiet interface would silently drop out of its own list's usage.
  const catIfaces = (id, nid) => Object.entries(((fleetNodes.find(n => n.id === nid) || {}).rule_cats) || {})
    .filter(([, cats]) => (cats || []).includes(id)).map(([ifn]) => ifn).sort();
  // One renderer for both grids: the interfaces holding a list, each a way into the rule that put it there.
  const usedBy = id => { const ifs = catIfaces(id, selNode);
    return ifs.length
      ? html`<div class="lg-used">${ifs.map(ifn => html`<button type="button" class="lg-ifchip" key=${ifn}
          title=${T("Open {v1} and its routing rules", { v1: ifn })} onClick=${() => openIfaceEditor(selNode, ifn)}>${ifn}</button>`)}</div>`
      : html`<span class="lg-unused" title=${T("Held on this node, but no rule on it names this list.")}>${T("not used here")}</span>`; };
  const catInUseFleet = id => (Store.nodes || []).some(n => catInUse(id, n.id));
  // node's rules. gridKeep holds ids that must stay visible even at 0/N pins (so unpinning doesn't make the row
  // vanish under the cursor — only × removes it, and only when no rule is holding the list).
  const fleetNodes = Store.nodes || [];
  const catOnNode = (id, nid) => ccOf(nid).includes(id);
  const setCatOnNode = (id, nid, on) => setNV(nid, { catalog_cats: on ? [...new Set([...ccOf(nid), id])] : ccOf(nid).filter(c => c !== id) });
  const removeCatFleet = id => { fleetNodes.forEach(n => { if (ccOf(n.id).includes(id)) setCatOnNode(id, n.id, false); }); setGridKeep(g => g.filter(x => x !== id)); };   // × drops it everywhere + hides the row
  const provFleetCats = [...new Set([...fleetNodes.flatMap(n => ccOf(n.id)),
                                     ...fleetNodes.flatMap(n => [...(ruleCats[n.id] || [])]),   // resident because a rule says so
                                     ...gridKeep])].sort((a, b) => catLabelOf(a).toLowerCase().localeCompare(catLabelOf(b).toLowerCase()));
  // No longer "stop matching": a rule is what makes a list route, and the × is disabled while any rule names
  // it (§1.4). All this can do is drop the pins — after which the node keeps the list only while a rule wants it.
  const confirmRemoveCat = id => openConfirm({ title: T("Unpin list from the fleet"), confirmLabel: T("Unpin"), warn: true,
    body: Trich("Stop keeping *{v1}* {v2} on *every node*? No rule uses it, so each node drops it on the next sync. You can pin it again from the catalog any time.",
      { v1: catLabelOf(id), v2: html`<span class="faint">(${provLabelOf(id)})</span>` }),
    onConfirm: () => removeCatFleet(id) });
  const catSaved = id => fleetNodes.some(n => ((orig[n.id] || {}).catalog_cats || []).includes(id));   // present in the last-SAVED fleet state → removing it is a real change (confirm); a draft-only add this session isn't
  const removeCatRow = id => catSaved(id) ? confirmRemoveCat(id) : removeCatFleet(id);   // × removes a just-added (unsaved) list with no prompt; only saved lists confirm
  const SECF = { routing: ["routing_mode", "ip_learning", "catalog_cats"], mesh: ["endpoint_host", "endpoint_hosts", "mesh_subnet", "mesh_port", "mesh_prefix", "mesh_awg", "default_egress_ip", "panel_ip", "mesh_egress_ip", "default_exit"], exits: ["exits"] };
  const nodeDirty = (nid, sec) => (SECF[sec] || []).some(f => !eq((nodeEdits[nid] || {})[f], (orig[nid] || {})[f]));
  const listsJSON = ls => JSON.stringify((ls || []).map(l => ({ id: l.id || "", title: l.title || "", enabled: l.enabled !== false, targets: customTargets(l).trim() })));
  const glDirty = sec =>
    sec === "routing" ? (listsJSON(lists) !== listsJSON(ps.custom_lists || []) || Object.keys(blockEdits).length > 0 || blockRemoved.length > 0) :
    sec === "turn" ? (turnEnabledS !== (ps.turn_enabled !== false) || [...turnForks].sort().join() !== (ps.enabled_turn_forks || TURN_FORKS_DEFAULT).slice().sort().join() || JSON.stringify(forkColorOverrides()) !== JSON.stringify(forkOvFrom(ps.turn_fork_colors)) || vkLinkS.trim() !== (ps.vk_link || "") || String(Math.max(0, parseInt(tuEvery) || 0)) !== String((ps.turn_update || {}).every_days == null ? 0 : (ps.turn_update || {}).every_days) || tuAt !== ((ps.turn_update || {}).at || "04:00")) :
    sec === "security" ? secChanged() :
    sec === "geo" ? (JSON.stringify(provEnabled) !== JSON.stringify(Object.fromEntries((Store.catalogProviders || []).filter(p => !p.builtin).map(p => [p.id, p.enabled !== false]))) || Object.keys(blockProvEdits).length > 0 || JSON.stringify(provColorOverrides()) !== JSON.stringify(ps.provider_colors || {}) || customEnabled !== (ps.custom_lists_enabled !== false) || String(Math.max(0, parseInt(guEvery) || 0)) !== String(_gu.every_days == null ? 1 : _gu.every_days) || guAt !== (_gu.at || "04:00")) :
    sec === "defaults" ? (dns !== (idf.dns || []).join(", ") || mtu !== String(idf.mtu || 1280) || ka !== String(idf.keepalive || 25) || JSON.stringify(ifaceColorOverrides()) !== JSON.stringify(ifaceOvFrom(ps.iface_colors)) || JSON.stringify(statusCondsOut()) !== JSON.stringify({ blocked: (ps.status_conditions || {}).blocked !== false, faulty: (ps.status_conditions || {}).faulty !== false }) || JSON.stringify(awgTrim(awgDef)) !== JSON.stringify(awgTrim(idf.awg_params || {})) || (ivkEscrow !== null && ivkEscrow !== ivkEscrowInit)) :
    sec === "configs" ? (sc !== _scMode) :
    sec === "subs" ? (subsOn !== !!subCfg.enabled || autoGen !== !!subCfg.auto_generate || warnDays !== String(ps.expiry_warn_days == null ? 3 : ps.expiry_warn_days) || JSON.stringify([...subLangs].sort()) !== JSON.stringify([...(subLangCfg.enabled || ["en"])].sort()) || subLangDef !== (subLangCfg.default || "en")) :
    sec === "display" ? (tput !== (ps.throughput_perspective === "peers" ? "peers" : "nodes") || tunit !== (ps.throughput_units === "bits" ? "bits" : "bytes") || staleS !== String(Math.round((adv.node_stale_ms || 30000) / 1000)) || graceS !== String(Math.round((adv.peer_grace_ms || 60000) / 1000)) || topTalk !== String(ps.top_talkers || 10) || topDest !== String(ps.top_destinations || 10) || themeColorS.toLowerCase() !== clampBrand(ps.theme_color || THEME_COLOR_DEFAULT, false).toLowerCase() || themeColorLightS.toLowerCase() !== clampBrand(ps.theme_color_light || THEME_COLOR_LIGHT_DEFAULT, true).toLowerCase()) :
    sec === "mesh" ? (rsvSubnet !== (rsv.mesh_subnet || "10.255.0.0/16") || rsvPort !== String(rsv.mesh_port_base || 9999) || rsvPrefix !== (rsv.iface_prefix || "swg_") || JSON.stringify(awgSet ? awg : {}) !== JSON.stringify(ps.mesh_awg || {})) : false;
  const secDirty = sec => glDirty(sec) || (SECF[sec] ? (Store.nodes || []).some(n => nodeDirty(n.id, sec)) : false);
  const badgeDirty = nid => nid === "" ? glDirty(section) : nodeDirty(nid, section);
  const anyDirty = SECTIONS.some(([s]) => secDirty(s));
  // Unsaved-changes guard: warn before leaving (in-app nav via the router, the Back button, or a browser refresh/close)
  const dirtyRef = useRef(anyDirty); dirtyRef.current = anyDirty;
  useEffect(() => {
    setUnsavedGuard(() => dirtyRef.current);
    const bu = e => { if (dirtyRef.current) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", bu);
    return () => { clearUnsavedGuard(); window.removeEventListener("beforeunload", bu); };
  }, []);
  // LEAVE_MSG() — it is a function so the lookup happens after loadLang(); passing it uncalled hands
  // confirm() a function, which it stringifies, and the dialog shows this line's source instead of the question.
  const leaveSettings = () => { if (!anyDirty || confirm(LEAVE_MSG())) { clearUnsavedGuard(); history.back(); } };
  const MODES = [
    ["kernel", T("Default — IP only. DNS not involved"), T("Matches by destination IP (GeoIP / ASN) — routing never depends on DNS, so your clients' DoH, DoT and plain DNS all keep working untouched. Simplest and most robust; it just can't separate services that share IPs (YouTube vs Google), and a CDN category catches everything behind it. Lists: GeoIP + Custom IPs.")],
    ["forcedns", T("Force DNS — Host + IP. Overrides encrypted DNS"), T("The node becomes your clients' resolver and blocks their encrypted DNS — both DoH (known providers) and all DoT — so it can route by hostname too, per-service precise. Trade-off: it sees and downgrades the client's DNS, can break a client that insists on its own encrypted DNS, and a DoH server it doesn't recognise can still slip past. Lists: GeoSite (host) + GeoIP + Custom IPs/domains.")],
    ["sni", T("SNI Sniffer — Host + IP. DNS stays private"), T("Routes by hostname by reading the SNI from each TLS handshake, so your clients' DNS — DoH, DoT or plain — is never touched, observed or downgraded: the connection stays encrypted end-to-end. Learns each destination on its first connection (a brand-new host routes on the next one); names hidden by ECH, and QUIC / HTTP3, fall back to IP routing. Lists: GeoSite (host) + GeoIP + Custom IPs/domains.")],
  ];
  return html`<div class="screen setscreen">
    <div class="sethead">${Trich("*Panel settings*")}</div>
    ${msg ? html`<div class=${"formmsg " + (msg.ok ? "ok" : "err")}>${msg.t}</div>` : null}
    <div class="setbody">
      <nav class="setrail">${SECTIONS.map(([id]) => html`<button class=${"setrail-i" + (section === id ? " on" : "")} onClick=${() => setSection(id)}>${sectionLabel(id)}${secDirty(id) ? html`<span class="dirtydot"></span>` : null}</button>`)}</nav>
      <div class="setpane">
        ${perNodeSection && (Store.nodes || []).length ? html`<div class="setnodes">${(Store.nodes || []).map(n => html`<button class=${"snbadge" + (selNode === n.id ? " on" : "") + (badgeDirty(n.id) ? " dirty" : "")} style=${"--c:" + Store.nodeColor(n.id)} onClick=${() => setSelNode(n.id)}><span class="ndot"></span>${n.name}</button>`)}</div>` : null}
        ${section === "routing" ? html`<div class="card rcard">
          ${(() => { const mm = MODE_META[nodeMode] || MODE_META.kernel;
            const resetBtn = html`<${Popover} hoverOnly cls="rmode-resetwrap" popCls="rmode-reset-pop"
                  trigger=${html`<button class="rmode-reset-ic" onClick=${() => resetRouting(selNode, nodeRec ? nodeRec.name : T("this node"))}><${Ic} i="refresh"/></button>`}>
                  <div class="rmode-reset-pop-body">${T("Reset this node's smart routing — clear just the learned IPs, or wipe + rebuild + re-pull every list. Use it to recover a stuck node.")}</div>
                <//>`;
            const mmRun = MODE_META[savedMode] || MODE_META.kernel;   // runbar reflects the SAVED/running mode, not the draft
            const caption = html`<div class="rmr-title">${Trich("{v1} currently runs on {v2}", {
      v1: html`<b class="rmr-node">${nodeRec ? nodeRec.name : T("Node")}</b>`,
      v2: html`<b class="rmr-mode">${mmRun.label}</b>`,
    })}</div>`;
            const infoPop = html`<${Popover} hoverOnly cls="rmode-info" popCls="rmode-info-pop" trigger=${html`<span class="rmode-infobtn"><${Ic} i="info"/></span>`}>
                  <div class="rmode-info-body">${Trich("Every mode matches by destination *IP* first (GeoIP / ASN / your IP lists) — that layer is *always on* and carries all traffic, including calls, UDP and QUIC. The choice adds an optional *host (domain)* matching layer on top: none, via the node's *DNS*, or read from the *TLS handshake*. Traffic always stays in-kernel in any mode including *{v1}* (no userspace proxy). Changing it reconfigures {v2} and changes which lists its interfaces can use.", { v1: T("Hybrid SNI"), v2: nodeRec ? nodeRec.name : T("the node") })}<div style="margin-top:9px">${Trich("*Reset routing* recovers a stuck node — clear just the learned IPs, or wipe + rebuild + re-pull everything.")}</div></div>
                <//>`;
            const runbar = savedMode === "kernel"
              ? html`<div class="rmode-runbar">
                  ${caption}
                  <span class="grow"></span>
                  <div class="rmr-actions">${infoPop}${resetBtn}</div>
                </div>`
              : html`<div class="rmode-runbar">
                  <div class="rmr-left">
                    <${HostHealth} node=${selNode} mode=${savedMode} learn=${ipLearn} onLearn=${setIpLearn}/>
                  </div>
                  <span class="grow"></span>
                  <div class="rmr-right">
                    <div class="rmr-rtop">${caption}${infoPop}${resetBtn}</div>
                  </div>
                </div>`;
            return html`
          ${runbar}
          <div class=${"rmode-banner m-" + nodeMode}>
            <div class="rd-head">
              <div class="rd-headmain">
                <div class="rd-titlerow">
                  <span class="rd-ic"><${Ic} i=${mm.icon}/></span>
                  <b class="rd-name">${mm.label}</b>
                  <span class="rmc-tag">${mm.short}</span>
                </div>
                <div class="rd-adds">${mm.adds}</div>
              </div>
            </div>
            <div class="rd-headside">
                <${ModeTabs} value=${nodeMode} onChange=${setMode}/>
            </div>
            <div class="rd-lines">
              ${(mm.bene || []).map(b => html`<div class="rmc-bene"><b>+</b><span>${b}</span></div>`)}
              ${(Array.isArray(mm.block) ? mm.block : mm.block ? [mm.block] : []).filter(x => x.s === "+").map(x => html`<div class="rmc-bene"><b>+</b><span>${x.t}</span></div>`)}
              <div class="rmc-cost"><b>−</b><span>${mm.cost}</span></div>
              ${(Array.isArray(mm.block) ? mm.block : mm.block ? [mm.block] : []).filter(x => x.s === "−").map(x => html`<div class="rmc-cost"><b>−</b><span>${x.t}</span></div>`)}
            </div>
            ${/* WHAT THIS ENGINE CAN ACTUALLY DO, as three facts rather than prose. The +/− lines above argue
                  for a choice; these answer the questions an operator asks while making it — which kinds of
                  rule does it match, what can it block, and who wins when two rules both claim a hostname.
                  The last one is not obvious and is not the same on every engine (plan §10.4x measured it),
                  so it is stated per engine instead of assumed from the label over the rules list.

                  BELOW `.rd-lines`, deliberately. `.rd-headside` is absolutely positioned over this card's
                  top-right, and `.rd-head` reserves its width with a right gutter — but `.rd-lines` and
                  everything after it are full-width and flow UNDER it. Anything added higher up would slide
                  beneath the mode buttons the moment its text got long. */""}
            ${mm.routes ? html`<div class="rd-spec">
              <span class="rds-k">${T("Routes")}</span><span class="rds-v">${mm.routes}</span>
              <span class="rds-k">${T("Overlaps")}</span><span class="rds-v">${mm.overlaps}</span>
            </div>` : null}
            <div class="rmode-desc">${mm.exp}</div>
          </div>`; })()}

          <div class="rltabs">
            <div class="rltab-cap">${Trich("{v1} for {v2}", {
              v1: routeTab === "blocking" ? T("Content filters") : T("Routing lists"),
              v2: html`<b style=${"color:" + (Store.nodeColor(selNode) || "var(--ink)")}>${nodeRec ? nodeRec.name : T("this node")}</b>`,
            })}</div>
            <div class="rltab-group" role="tablist">
              <button role="tab" aria-selected=${routeTab === "routing"} class=${"rltab" + (routeTab === "routing" ? " on" : "")} onClick=${() => setRouteTab("routing")}><${Ic} i="cascade"/>${T("Routing")}</button>
              <button role="tab" aria-selected=${routeTab === "blocking"} class=${"rltab" + (routeTab === "blocking" ? " on" : "")} onClick=${() => setRouteTab("blocking")}><${Ic} i="shield"/>${T("Blocking")}</button>
            </div>
          </div>
          <div class="hint rltab-note"><${Ic} i="info"/><span>${routeTab === "blocking" ? T("Filtering runs on the entry node — where a client's tunnel lands. Exit and relay hops in a multi-hop path never see the client, so there's nothing there for them to filter.") : T("Routing runs on the entry node — where a client's tunnel lands. Exit and relay hops in a multi-hop path just forward what's already been steered.")}</span></div>
          ${routeTab === "blocking" ? html`<div class="hint rltab-warn"><${Ic} i="warn"/><span>${Trich("Large lists are memory-hungry — every enabled list is loaded into RAM on *each* entry node that uses it, roughly *130 MB per 1M domains*. Keep your smallest node's memory in mind before turning on big lists.")}</span></div>` : null}

          ${routeTab === "routing" ? html`
          <div class="lgrid-head">
            <div class="lg-htitle"><span class="seclabel" style="margin:0">${T("Provider lists")}</span><span class="lg-count">${provFleetCats.length}</span><span class="faint lg-sub">${T("held on this node, and the interfaces that ask for them")}</span></div>
            <span class="grow"></span>
          </div>
          ${provFleetCats.length ? html`<div class="lgrid">
            ${provFleetCats.map(id => { const cap = catCap(id); const usable = catUsableInMode(id, nodeMode); const sz = (Store.catSizes || {})[id] || {};
              return html`<div class=${"lgrow" + (usable ? "" : " lg-lock")} key=${id}>
                <div class="lg-cat"><div class="lg-catmain"><span class="lg-title">${catLabelOf(id)}</span>${provLabelOf(id) ? html`<${ProvTag} id=${id}/>` : null}${catInUse(id, selNode)
                  ? html`<span class="lg-inuse" title=${T("A routing rule on this node names this list, so the node already holds it — pinning only decides whether it stays when that rule goes.")}>${T("in use")}</span>` : null}</div>${catRawId(id) ? html`<span class="lg-id">${catRawId(id)}</span>` : null}</div>
                <div class="lg-size">${sizeSummary(sz.host || 0, sz.ip || 0, sz.pat || 0) || html`<span class="faint">—</span>`}</div>
                <div class="lg-fleet">${usedBy(id)}</div>
                <div class="lg-caps">${capBadges(cap)}</div>
                <div class="lg-act">${catListUrl(id, cap) ? html`<a class="ccchip-info" href=${catListUrl(id, cap)} target="_blank" rel="noopener" title=${T("View this list on GitHub")}><${Ic} i="info"/></a>`
                  : catDescOf(id) ? html`<${DescInfo} text=${catDescOf(id)}/>` : null}${!catInUseFleet(id) && catOnNode(id, selNode) ? html`<button class="ccchip-x"
                  title=${T("A leftover pin — no rule names this list. Clear it from every node.")}
                  onClick=${() => removeCatRow(id)}><${Ic} i="x"/></button>` : null}</div>
              </div>`; })}
          </div>` : html`<div class="hint" style="margin:2px 0 0">${Trich("Nothing held here yet. Lists arrive on their own when an interface's routing rule names one — add them in *Interfaces*, on the interface that needs them.")}</div>`}

          ${/* The empty state is BACK, because the thing is reachable again. It was removed when nothing
                could create a list — a heading, a zero and a sentence explaining an absence is noise — and
                the same reasoning now says the opposite: a section you can add to has to be visible when
                it is empty, or there is nowhere to press. */""}
          ${(Store.panelSettings || {}).custom_lists_enabled !== false ? html`
          <div class="lgrid-head" style="margin-top:26px">
            <div class="lg-htitle"><span class="seclabel" style="margin:0">${T("Custom lists")}</span><span class="lg-count">${lists.length}</span><span class="faint lg-sub">${T("one set of addresses, reused by rules on any node — edited in one place")}</span></div>
            <span class="grow"></span>
            <button class="btn btn-add" onClick=${() => openModal(html`<${CustomListSheet} key="new" onSave=${saveList} onClose=${closeModal}/>`)}><${Ic} i="plus"/>${T("New list")}</button>
          </div>
          ${!lists.length ? html`<p class="hint" style="margin:6px 0 0">${T("No lists yet. Worth making when the same addresses are wanted by more than one rule — otherwise type them straight into the rule.")}</p>` : null}
          ${lists.length ? html`<div class="lgrid">
            ${[...lists].sort((a, b) => (a.title || "").toLowerCase().localeCompare((b.title || "").toLowerCase())).map(l => { const cap = customCaps(l);
              /* THE WHOLE ROW OPENS IT. A 4px-tall title inside a 12-column grid is a small target for the
                 one thing anybody comes to this row to do. The row's other controls stay reachable because
                 the handler stands down for anything that is already a control: the interface chips (which
                 go to that interface's rules) and the × both live inside it and both still get their own
                 click. The title stays a real <button> — the row is a div, so it is the keyboard path. */
              return html`<div class="lgrow clk" key=${l._rid} title=${T("Edit this list")}
                  onClick=${e => { if (e.target.closest("button,a")) return;
                                   openModal(html`<${CustomListSheet} key=${l._rid} list=${l} onSave=${saveList} onClose=${closeModal}/>`); }}>
                <div class="lg-cat"><div class="lg-catmain"><button type="button" class="lg-title" title=${T("Edit this list")}
                  onClick=${() => openModal(html`<${CustomListSheet} key=${l._rid} list=${l} onSave=${saveList} onClose=${closeModal}/>`)}>${l.title || T("Untitled list")}</button><span class="catpick-src" style=${"--pc:" + providerColor("custom")}>${T("src|Custom")}</span></div>${l.id ? html`<span class="lg-id">${l.id}</span>` : null}</div>
                <div class="lg-size"><${ListInfo} list=${l}/></div>
                <div class="lg-fleet">${usedBy(l.id)}</div>
                <div class="lg-caps">${capBadges(cap)}</div>
                <div class="lg-act"><button class="ccchip-x" title=${T("Delete this list")} onClick=${() => confirmDeleteList(l)}><${Ic} i="x"/></button></div>
              </div>`; })}
          </div>` : null}` : null}

          <div class="lg-legend">
            <div class="lg-leg-row">${Trich("{v1} matched by address range (GeoIP / ASN) — works in every mode.", { v1: html`<span class="capb ip">IP</span>` })}</div>
            <div class="lg-leg-row">${Trich("{v1} matched by domain name — needs Force-DNS or SNI mode.", { v1: html`<span class="capb host">${T("Host")}</span>` })}</div>
            ${provFleetCats.some(id => !catUsableInMode(id, nodeMode)) ? html`<div class="lg-leg-row faint">${T("Greyed rows are Host-only — this node is IP-only, so they can't match here. The pull stays remembered; switch to Force-DNS or SNI to activate them.")}</div>` : null}
          </div>` : null}

          ${routeTab === "blocking" ? (() => {
            const bc = Store.blockCatalog;
            if (!bc) return html`<div class="hint" style="margin:8px 0 0">${T("Loading block lists…")}</div>`;
            const provList = bc.provider_lists || {};
            const provLabel = p => ((bc.providers || []).find(x => x.id === p) || {}).label || p;
            const provTier = p => ((bc.providers || []).find(x => x.id === p) || {}).tier || "host";
            const provColor = p => { const bp = (bc.providers || []).find(x => x.id === p) || {}; return pickThemed(provColors[p] || asThemed((ps.provider_colors || {})[p], bp.color, bp.color_l || bp.color), _provColDefault(p).dark, _provColDefault(p).light); };
            const srcLabel = s => { const L = (provList[s.provider] || []).find(x => x.id === (s.list || "")); return (L && L.label) || s.list || provLabel(s.provider); };
            const bcat = id => { const b = (bc.categories || {})[id] || {}; return { id, ...b, ...(blockEdits[id] || {}) }; };
            const allIds = [...new Set([...(bc.cat_order || []), ...Object.keys(bc.categories || {}), ...Object.keys(blockEdits)])];
            const cats = allIds.map(bcat).filter(c => c.kind !== "mechanism" && !blockRemoved.includes(c.id));
            const caps = c => { const s = c.sources || []; return { host: s.some(x => provTier(x.provider) === "host"), ip: s.some(x => provTier(x.provider) === "ip") }; };
            const fmtN = n => n == null ? null : n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1).replace(/\.0$/, "") + "M" : n >= 1e3 ? (n / 1e3).toFixed(n >= 1e4 ? 0 : 1).replace(/\.0$/, "") + "k" : String(n);
            const catTotal = c => { const sz = c.size; if (!sz) return null; const t = (sz.host || 0) + (sz.ip || 0); return t ? fmtN(t) : null; };
            const createCat = ({ id, label }) => { setBlockEdits(e => ({ ...e, [id]: { label, sources: [], enabled_nodes: [] } })); setBkOpen(o => ({ ...o, [id]: true })); setBkAutoAdd(id);
              requestAnimationFrame(() => requestAnimationFrame(() => {   // scroll fully to the bottom so the just-added category (+ its auto-opened picker) is in view
                const items = document.querySelectorAll(".bkitem"); const el = items[items.length - 1]; if (!el) return;
                let p = el.parentElement;
                while (p) { const st = getComputedStyle(p).overflowY; if ((st === "auto" || st === "scroll") && p.scrollHeight > p.clientHeight + 4) { p.scrollTo({ top: p.scrollHeight, behavior: "smooth" }); break; } p = p.parentElement; }
                window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
              })); };
            const doRemoveCat = c => { setBkOpen(o => ({ ...o, [c.id]: false })); if ((bc.categories || {})[c.id]) setBlockRemoved(r => r.includes(c.id) ? r : [...r, c.id]); setBlockEdits(e => { const n = { ...e }; delete n[c.id]; return n; }); };
            const removeCat = c => { if ((bc.categories || {})[c.id])   // a SAVED custom category → confirm; an unsaved draft removes with no prompt
                openConfirm({ title: T("Delete category · ") + c.label, confirmLabel: T("Delete category"), danger: true,
                  body: T("Removes this custom category and its lists. It's deleted from the panel when you Save, and nodes stop filtering it on their next sync. You'd have to recreate it to bring it back."),
                  onConfirm: () => doRemoveCat(c) });
              else doRemoveCat(c); };
            const availOn = c => (c.enabled_nodes || []).includes(selNode);
            const modeLabel = (MODE_META[nodeMode] || {}).label || T("this mode");
            const srcAvail = s => blockSrcOk(nodeMode, bc.providers, s);   // shared rule: IP everywhere, domain needs Force-DNS/Hybrid
            // A category with NO IP list can't enforce anything in Default (IP-only) or Kernel-SNI — every list shows "not
            // available". Then the whole category is dead here: show it disabled and don't let it be enabled on this node.
            const catDis = c => blockCatDisabled(nodeMode, bc.providers, c);
            const srcHost = s => provTier(s.provider) !== "ip";
            const setAvail = (c, on) => { const en = new Set(c.enabled_nodes || []); on ? en.add(selNode) : en.delete(selNode);
              setBlockEdits(e => ({ ...e, [c.id]: { ...(e[c.id] || {}), enabled_nodes: [...en] } })); };
            const setDefault = (c, on) => setBlockEdits(e => ({ ...e, [c.id]: { ...(e[c.id] || {}), default_on: on } }));
            const setSources = (c, sources) => setBlockEdits(e => ({ ...e, [c.id]: { ...(e[c.id] || {}), sources } }));
            const addSource = (c, p, l) => { if ((c.sources || []).some(s => s.provider === p && s.list === l)) return; setSources(c, [...(c.sources || []), { provider: p, list: l }]); };
            const removeSource = (c, i) => setSources(c, (c.sources || []).filter((_, j) => j !== i));
            const srcDesc = s => { const L = (provList[s.provider] || []).find(x => x.id === (s.list || "")); return (L && L.desc) || ""; };
            const srcUrl = s => { const L = (provList[s.provider] || []).find(x => x.id === (s.list || "")); return (L && L.src) || ""; };
            const setAvailNode = (c, nid, on) => { const en = new Set(c.enabled_nodes || []); on ? en.add(nid) : en.delete(nid);
              setBlockEdits(e => ({ ...e, [c.id]: { ...(e[c.id] || {}), enabled_nodes: [...en] } })); };
            const bkRow = c => { const src = c.sources || []; const nL = src.length; const open = !!bkOpen[c.id]; const dis = catDis(c);
              return html`<div class=${"bkitem" + (open ? " open" : "") + (dis ? " bk-dis" : "")} key=${c.id}>
                <div class=${"bkrow" + (open ? " open" : "")} onClick=${() => setBkOpen(o => ({ ...o, [c.id]: !open }))}>
                  <div class="lg-pull" onClick=${e => e.stopPropagation()}><${Switch} on=${availOn(c) && !dis} disabled=${dis} title=${dis ? T("No IP list here — can't enforce in {v1}. Add an IP list, or use Force-DNS / Hybrid-SNI.", { v1: modeLabel }) : T("Filter on {v1}", { v1: nodeRec ? nodeRec.name : T("this node") })} onChange=${v => { if (!dis) setAvail(c, v); }}/></div>
                  <div class="bk-cat">
                    <div class="bk-catline"><span class="lg-title">${c.label}</span><span class="bk-chev">▾</span></div>
                    <div class="bk-lists">${nL ? src.map(srcLabel).join(", ") : html`<span class="faint">${T("no lists yet — add one →")}</span>`}</div>
                  </div>
                  <div class="bk-kind">${!c.predefined ? html`<span class="capb custom" title=${T("A category you created")}>${T("src|Custom")}</span>` : null}</div>
                  <div class="bk-size">${(() => { const t = catTotal(c); return t ? html`<span class="bk-count" title=${T("Total entries across this category’s lists")}>${t}</span>` : null; })()}</div>
                  <div class="bk-fleet" onClick=${e => e.stopPropagation()}><${FleetAssign} nodes=${fleetNodes} isOn=${nid => (c.enabled_nodes || []).includes(nid)} onToggle=${(nid, on) => setAvailNode(c, nid, on)}/></div>
                  <div class="bk-cap">${(() => { const cp = caps(c); return cp.host || cp.ip
                    ? html`<${Fragment}>${cp.host ? html`<span class="capb host" title=${T("Matched by domain — needs Force-DNS or Hybrid-SNI mode")}>${T("Host")}</span>` : null}${cp.ip ? html`<span class="capb ip" title=${T("Matched by IP — works in every mode")}>IP</span>` : null}<//>`
                    : html`<span class="bk-nocap" title=${T("No lists yet")}>—</span>`; })()}</div>
                  <button class=${"bk-defchip" + (c.default_on ? " on" : "")} onClick=${e => { e.stopPropagation(); setDefault(c, !c.default_on); }} title=${T("Turn this category on automatically for every new interface (still toggled per interface)")}>Default ${c.default_on ? "ON" : "OFF"}</button>
                  <${BlockListPicker} providers=${bc.providers} provLists=${provList} current=${src} nodeMode=${nodeMode} onAdd=${(p, l) => addSource(c, p, l)} autoOpen=${bkAutoAdd === c.id}/>
                </div>
                ${open ? html`<div class="bk-expand">
                  ${src.length ? src.map((s, i) => html`<div class=${"bk-lrow" + (srcAvail(s) ? "" : " bk-ldis")} key=${i}>
                      <div class="bk-linfo">
                        <div class="bk-ltop"><span class="bk-llabel">${srcLabel(s)}</span><span class="bk-lprov" style=${provColor(s.provider) ? "--pc:" + provColor(s.provider) : ""}>${provLabel(s.provider)}</span></div>
                        ${srcDesc(s) ? html`<span class="bk-ldesc">${srcDesc(s)}</span>` : null}
                      </div>
                      <span class="grow"></span>
                      ${!srcAvail(s) ? html`<span class="bk-nabadge">${T("Not available with {v1}", { v1: modeLabel })}</span>` : null}
                      ${s.n != null ? html`<span class="bk-count" title=${srcHost(s) ? T("domains in this list") : T("IP ranges in this list")}>${fmtN(s.n)}</span>` : null}
                      <span class=${"capb " + (srcHost(s) ? "host" : "ip")} title=${srcHost(s) ? T("Domain list — needs Force-DNS or Hybrid-SNI mode") : T("IP list — works in every mode")}>${srcHost(s) ? T("Host") : T("cap|IP")}</span>
                      ${srcUrl(s) ? html`<a class="catrow-info" href=${srcUrl(s)} target="_blank" rel="noopener" title=${T("See what's in this list")} onClick=${e => e.stopPropagation()}><${Ic} i="info"/></a>` : null}
                      <button class="bk-lremove" title=${T("Remove this list from the category")} onClick=${e => { e.stopPropagation(); removeSource(c, i); }}><${Ic} i="x"/></button>
                    </div>`)
                    : html`<div class="bk-empty">${Trich("No lists yet — use *+ Add list* above to add one.")}</div>`}
                  ${!c.predefined ? html`<div class="bk-catfoot"><span class="grow"></span><button class="bk-delcat" title=${T("Delete this custom category")} onClick=${e => { e.stopPropagation(); removeCat(c); }}><${Ic} i="trash"/>${T("Delete category")}</button></div>` : null}
                </div>` : null}
              </div>`; };
            return html`<${Fragment}>
              <div class="lgrid-head" style="margin-top:16px">
                <div class="lg-htitle"><span class="seclabel" style="margin:0">${T("Block categories")}</span><span class="lg-count">${cats.length}</span><span class="faint lg-sub">${T("drop ads, malware, adult, threat IPs — by domain or IP")}</span></div>
                <span class="grow"></span>
                <button class="btn btn-add" onClick=${() => openModal(html`<${NewBlockCatSheet} existingIds=${allIds} onCreate=${createCat}/>`)}><${Ic} i="plus"/>${T("New category")}</button>
              </div>
              <div class="lgrid">${cats.map(bkRow)}</div>
              <div class="lg-legend">
                <div class="lg-leg-row">${Trich("{v1} matched by IP address — works in every mode.", { v1: html`<span class="capb ip">IP</span>` })}</div>
                <div class="lg-leg-row">${Trich("{v1} matched by domain name — needs *{v2}* or *Hybrid-SNI* mode (they fill the block set from DNS). IP-only and Kernel-SNI can't match domains.", { v1: html`<span class="capb host">${T("Host")}</span>`, v2: T("Force-DNS") })}</div>
                <div class="lg-leg-row">${Trich("{v1} a domain list can't enforce on an IP-only or Kernel-SNI node — it's skipped, never pushed. Switch that node to Force-DNS / Hybrid-SNI, or add an IP list.", { v1: html`<span class="bk-nabadge">${T("Not available")}</span>` })}</div>
              </div>
            <//>`;
          })() : null}
        </div>` : null}
        ${section === "turn" ? html`<div class="card">
          <div class="seclabel turnhead" style="margin-top:0">${T("Turn proxies")}<span class="grow"></span>
            <label class="swt" title=${turnEnabledS ? T("Turn proxies are on") : T("Turn proxies are off")}><input type="checkbox" checked=${turnEnabledS} onChange=${e => setTurnEnabledS(e.target.checked)}/><span class="track"></span><span class="knob"></span></label></div>
          ${!turnEnabledS ? html`<p class="hint" style="margin:0 0 12px"><b class="warntext">${T("Turn proxies are off.")}</b> ${T("Creation buttons and the turn-proxy sections are hidden across the panel. Deployed proxies keep running — they're just not shown here.")}</p>`
            : html`<p class="hint" style="margin:0 0 12px">${Trich("Which forks appear in the *{v1}* picker when you add a proxy to a node, and each fork's colour. Unticking one only *hides it from that list* — it never touches proxies you've already deployed. {v2}", { v1: T("Install a fork"), v2: turnForks.size === 0 ? html`*No forks are enabled — the install picker will be empty.*` : null })}</p>`}
          ${html`<${Fragment}>
          <div class=${"cllist" + (turnEnabledS ? "" : " dimmed")}>${turnForksVisible().map(f => { const fcol = pickThemed(forkColors[f.id], f.color, f.colorL); return html`<div class=${"cl-row" + (turnForks.has(f.id) ? "" : " off")} key=${f.id}>
            <${Switch} on=${turnForks.has(f.id)} title=${T("Offer {v1}", { v1: T("{v1} in the install picker", { v1: f.label }) })} onChange=${v => setTurnForks(s => { const n = new Set(s); v ? n.add(f.id) : n.delete(f.id); return n; })}/>
            <${ThemedSwatch} val=${forkColors[f.id]} title=${T("Colour for {v1}", { v1: f.label })} onChange=${nv => setForkColors(c => ({ ...c, [f.id]: nv }))}
              sample=${(c) => html`<span class="tg tg-turn" style=${"--tfc:" + c}>${f.label}</span>`}/>
            <a class=${"tf-name tf-" + f.id} href=${"https://github.com/" + f.owner} target="_blank" rel="noopener" style=${"color:" + fcol} title=${"github.com/" + f.owner}>${f.label}</a>
            <span class="cl-caps" title=${f.kind === "wdtt" ? T("Self-contained WDTT server — owns its own WireGuard interface (not a WG/AWG front)") : f.kind === "csqtt" ? T("Self-contained csqtt server — owns its own raw-TUN interface (not a WG/AWG front)") : forkSupportsAwg(f.id) ? T("Works with WireGuard and AmneziaWG interfaces") : T("{v1} is WireGuard-only — its client can't front an AmneziaWG interface", { v1: f.label })}>
              ${f.kind === "wdtt"
                ? html`<span class="tg tg-wdtt">WDTT</span>`
                : f.kind === "csqtt"
                ? html`<span class="tg tg-csqtt">CSQTT</span>`
                : html`<${Fragment}><span class="tg tg-wg">wg</span>${forkSupportsAwg(f.id) ? html`<span class="tg tg-awg">awg</span>` : null}<//>`}
            </span>
            ${(() => {
              const v = forkVersions(f.id); const col = fcol;
              if (!v.length) return html`<span class="tf-ver none">${T("not yet used")}</span>`;
              const nodes = forkNodeStates(f.id); const ut = turnUpdateTarget[f.id]; const latest = (ut && Date.now() < ut.until) ? ut.ver : ((turnCheck[f.id] || {}).latest || null);
              // per-node effective version: a hold shows "Held on <held>", else the running version. The row collapses
              // to ONE label when every node agrees, or "N versions" (detail in the hover bubble) when they differ.
              const perNode = nodes.map(n => { const held = (Store.turnHolds[n.node] || {})[f.id] || ""; return { ...n, held, eff: held || n.version || "" }; });
              const distinct = [...new Set(perNode.map(p => p.eff).filter(Boolean))];
              const allHeld = perNode.length > 0 && perNode.every(p => p.held);
              const bub = html`<span class="tf-verpop">
                ${perNode.map(n => html`<span class="tf-vg-node">
                  <span class="tf-vg-dot" style=${"background:" + (Store.nodeColor(n.node) || "var(--ink)")}></span>
                  <span class="tf-vg-nm">${Store.nodeName(n.node)}</span>
                  <span class=${"tf-vg-ver" + (n.held ? " held" : "")}>${n.held ? html`<${Ic} i="off"/> Held on ${n.held}` : (n.version || "—")}</span>
                  ${n.installing ? html`<span class="tf-vg-st upd">${T("updating…")}</span>` : (n.updatePending && latest && n.version === latest) ? html`<span class="tf-vg-st ok"><${Ic} i="check"/>${T("updated")}</span>` : null}
                </span>`)}
              </span>`;
              if (distinct.length > 1) return html`<span class="tf-verwrap" style=${"--tfc:" + col}><span class="tf-ver">${plural(distinct.length, "version")}</span>${bub}</span>`;
              const ver = distinct[0] || v.join(", ");
              if (allHeld) return html`<span class="tf-verwrap" style=${"--tfc:" + col}><span class="tf-ver held"><${Ic} i="off"/> ${T("Held on {v1}", { v1: ver })}</span>${bub}</span>`;
              return html`<span class="tf-verwrap" style=${"--tfc:" + col}><span class="tf-ver">${ver}</span>${bub}</span>`;
            })()}
            <span class="grow"></span>
            ${(() => { const cs = turnCheck[f.id]; if (!cs || !cs.status) return null;   // update status — right-aligned, just before the repo URL (like Geo data)
              if (cs.status === "checking") return html`<span class="tf-chk"><span class="tf-arrow"><${Ic} i="refresh"/></span> checking…</span>`;
              if (cs.status === "updating") return html`<span class="tf-chk"><span class="tf-arrow"><${Ic} i="refresh"/></span> updating…</span>`;   // i18n-keys
              if (cs.status === "update") return html`<button class="tf-chk upd tf-updbtn" title=${T("Update every deployed {v1} proxy to {v2}", { v1: f.label, v2: cs.latest })} onClick=${() => updateFork(f.id, cs.latest)}><${Ic} i="download"/> update to ${cs.latest}</button>`;
              return html`<span class="tf-chk ok"><${Ic} i="check"/> ${T("up to date")}</span>`; })()}
            <span class="tf-plats">${turnForkPlatforms(f).map(p => html`<span key=${p.os} class="tf-platwrap turnwrap" title="">
              <button type="button" aria-disabled=${p.disabled ? "true" : null}
                class=${"tf-plat" + (p.disabled || p.notOffered ? " off" : ((p.native ? " nat" : " cross") + (p.obf ? "" : " plain") + (p.isCli ? " cli" : "")))}
                onClick=${() => { if (!p.disabled) openServerClients(f.id, p.os); }}><${Ic} i=${"os_" + p.os}/></button>
              <span class="turnbub tf-plbub">
                ${p.notOffered
                  ? html`<span class="tf-plbub-l"><span class="tf-plbub-app">${T("Not offered on {v1} — those users get no card for this server", { v1: p.label })}</span></span>`
                  : p.disabled
                  ? html`<span class="tf-plbub-l"><span class="tf-plbub-app">${T("No {v1} app for {v2} yet", { v1: f.label, v2: p.label })}</span></span>`
                  : html`<${Fragment}><span class="tf-plbub-l">
                      <span class="tf-plbub-app">${p.name}<span class="tf-plbub-by"> by </span><span style=${"color:" + (p.color || turnColor(p.author))}>${p.author}</span></span>
                      ${p.coreFork ? html`<span class="tf-plbub-core">${Trich("with {v1} core", { v1: html`<span style=${"color:" + turnColor(p.coreFork)}>${p.coreFork}</span>` })}</span>` : null}
                    </span>
                    <span class=${"tf-plbub-obf" + (p.obfLabel ? "" : " plain")}>${p.obfLabel || "plain"}</span><//>`}
              </span></span>`)}</span>
            <button class="iconbtn tf-gear" title=${T("Server-flag defaults for {v1} (pre-fill new proxies)", { v1: f.label })} onClick=${() => openServerDefaults(f.id)}><${Ic} i="gear"/></button>
          </div>`; })}</div>
          <//>`}
          <${VkPoolEditor}/>
          <div class="seclabel" style="margin-top:18px">${T("Fallback VK call link")}</div>
          <p class="hint" style="margin:0 0 8px">${Trich("Used for *unassigned* peers, and as the link the panel bakes in when you generate a config here to *test a connection yourself* before handing it out. Leave blank to emit a *{v1}* placeholder.", { v1: VK_LINK_PLACEHOLDER })}</p>
          <input class="vklink-in" value=${vkLinkS} onInput=${e => setVkLinkS(e.target.value)} placeholder=${T("https://vk.com/call/join/…")}/>
          ${turnEnabledS ? html`<${Fragment}>
          <div class="seclabel" style="margin-top:18px">${T("Auto-update schedule")}</div>
          <p class="hint" style="margin:0 0 10px">${Trich("The panel checks each deployed proxy's fork for a newer release and, if there is one, updates the binary and restarts the proxy automatically. A restart briefly drops that proxy's clients, so pick a *quiet hour*. (The panel stages the update; each node applies it on its next sync.)")}</p>
          <div class="schedrow">
            <div class="field" style="margin:0"><label>${T("How often")}</label>
              <${Dropdown} value=${tuEvery} onChange=${v => setTuEvery(v)} options=${[
                { value: "1", label: T("Every day") }, { value: "2", label: T("Every 2 days") }, { value: "3", label: T("Every 3 days") },
                { value: "7", label: T("Every week") }, { value: "0", label: T("Off — no auto-updates") }]}/></div>
            <div class="field" style="margin:0"><label>${T("At (panel time)")}</label>
              <input type="time" class="timein" value=${tuAt} disabled=${tuEvery === "0"} onInput=${e => setTuAt(e.target.value || "04:00")}/>
              <div class="hint">${tuEvery === "0" ? T("Auto-updates are off — use “Check for updates” below to update manually.") : T("The panel checks at this local time, on the chosen cadence.")}</div></div>
          </div>
          <div class="georefresh"><span class="faint" style="font-size:11px">${T("Check every deployed proxy's fork for a newer release now, and update the ones that are behind")}</span><button class="btn btn-mini" disabled=${Object.values(turnCheck).some(v => v && v.status === "checking")} onClick=${checkTurnUpdates}><span class=${Object.values(turnCheck).some(v => v && v.status === "checking") ? "tf-arrow" : ""}><${Ic} i="refresh"/></span>${T("Check for updates")}</button></div>
          <div class="seclabel" style="margin-top:18px">${T("Client rosters")}</div>
          <p class="hint" style="margin:0 0 8px">${T("Whether any client app's config/link schema changed upstream on GitHub since we curated it — fetches each app's source file and flags drift per app to review.")}</p>
          <div class="georefresh"><span class="faint" style="font-size:11px">${T("Fetch each client app's schema source from GitHub and flag the ones whose upstream changed")}</span><button class="btn btn-mini" onClick=${() => openRosterCheck()}><${Ic} i="refresh"/>${T("Check client rosters")}</button></div>
          <//>` : null}
          ${turnEnabledS ? html`<${TurnCollectedIps}/>` : null}
        </div>` : null}
        ${section === "geo" ? html`<div class="card">
          <div class="rltabs" style="margin-top:0">
            <div class="rltab-cap">${geoTab === "blocking" ? T("Content filters providers") : T("Routing lists providers")}</div>
            <div class="rltab-group" role="tablist">
              <button role="tab" aria-selected=${geoTab === "routing"} class=${"rltab" + (geoTab === "routing" ? " on" : "")} onClick=${() => setGeoTab("routing")}><${Ic} i="cascade"/>${T("Routing")}</button>
              <button role="tab" aria-selected=${geoTab === "blocking"} class=${"rltab" + (geoTab === "blocking" ? " on" : "")} onClick=${() => setGeoTab("blocking")}><${Ic} i="shield"/>${T("Blocking")}</button>
            </div>
          </div>
          ${geoTab === "routing" ? html`
          <p class="hint" style="margin:0 0 12px">${Trich("*Curated* presets are always available — recommended, ready-to-route lists the panel maintains and resolves itself, with nothing to enable. Turn on any public *provider* below to also search its raw catalog; the panel fetches it so its lists appear in the picker. Turning one off hides its lists and *stops* anything already routed from it until you turn it back on.")}</p>
          <div class="provlist">${(_provReg.length ? _provReg : []).map(p => { const on = p.builtin || provEnabled[p.id] !== false; return html`<div class=${"provrow bprow" + (on ? "" : " off") + (p.builtin ? " builtin" : "")} key=${p.id}>
            ${/* Curated keeps the switch COLUMN and not the switch. Its lists are resolved by the panel and cost
                  nothing when nothing routes them, so there is no state for a switch to hold — and the one that
                  used to sit here held none either, while telling the operator it deactivated what was already
                  routed (§6.5). The spacer keeps every row's swatch on the same line as its neighbours'. */""}
            ${p.builtin ? html`<span class="prov-nosw" aria-hidden="true"></span>` : html`
            ${/* Locked while it fetches: the only thing this row can honestly offer mid-download is Cancel.
                  Toggling it here would leave a running fetch attached to a provider the operator just turned
                  off, and the switch is saved with the whole form, so the state would not even reach the panel
                  until Save. */""}
            <${Switch} on=${on} disabled=${p.status === "downloading"}
              title=${p.status === "downloading" ? T("Fetching this provider's catalog — cancel to stop waiting")
                : on ? T("Enabled — its lists are selectable") : T("Off — its lists are hidden and deactivated on nodes")}
              onChange=${v => setProvOn(p, v)}/>`}
            <${ThemedSwatch} val=${provColors[p.id]} title=${T("{v1} tag colour", { v1: p.label })} onChange=${nv => setProvColors(c => ({ ...c, [p.id]: nv }))}
              sample=${(c) => html`<span class="sw-sample" style=${"--pc:" + c}>${p.label}</span>`}/>
            <div class="bprov-meta">
              <div class="bprov-top">
                <span class="prov-name" style=${"color:" + pickThemed(provColors[p.id], _provColDefault(p.id).dark, _provColDefault(p.id).light)}>${p.label}</span>
                <span class="prov-tiers">${capBadges({ host: (p.tiers || []).includes("host"), ip: (p.tiers || []).includes("ip") })}</span>
                ${/* How far this switch reaches, stated before it is thrown (§6.4). Counts every rule that
                      NAMES one of this provider's lists, across wg/awg interfaces and the self-contained kinds.
                      Shown on a DISABLED row too, unlike "updated …" beside it: on a provider that is already
                      off this is the one line that explains why those rules are routing nothing. */""}
                ${(() => { const u = providerUsage(p.id); return u.rules ? html`<span class="prov-use"
                  title=${T("Rules on your interfaces that route one of this provider's lists")}>${T("used by {v1} on {v2}", { v1: plural(u.rules, "prep|rule"), v2: plural(u.ifaces, "prep|interface") })}</span>` : null; })()}
                ${p.builtin ? html`<span class="prov-always" title=${T("The panel maintains and resolves these itself — there is no provider to enable, and nothing to turn off")}>${T("always on")}</span>`
                  : p.enabled === false ? null : html`<span class=${"prov-upd" + (p.last_updated ? "" : " never")} title=${p.last_updated ? T("When this provider's data was last pulled to the panel") : T("No list from this provider has been routed yet — nothing pulled")}>${p.last_updated ? html`updated ${ago(p.last_updated)}` : T("never updated")}</span>`}
              </div>
              ${p.desc ? html`<span class="bprov-note">${T(p.desc)}</span>` : null}
            </div>
            <span class="grow"></span>
            ${p.builtin || p.enabled === false ? null
              : (() => { const s = p.status, flashing = provFlash[p.id] > Date.now();
              if (s === "downloading") return html`<${Fragment}><span class="prov-st upd" title=${T("Reading this provider's file list from GitHub. Its lists become searchable when it lands; nothing is routed yet.")}><span class="tf-arrow"><${Ic} i="refresh"/></span> ${T("Downloading…")}</span><button class="btn btn-mini" style="margin-left:8px" title=${T("GitHub allows 60 requests an hour without an account, and a fetch inside that window can sit for a couple of minutes. Cancelling stops the wait and turns the provider off — the request itself finishes on its own and its result is thrown away.")} onClick=${() => cancelProvider(p.id)}>${T("Cancel")}</button></>`;
              if (s === "updating") return html`<span class="prov-st upd"><span class="tf-arrow"><${Ic} i="refresh"/></span> updating…</span>`;   // i18n-keys
              if (s === "updated") return flashing ? html`<span class="prov-st ok"><${Ic} i="check"/> ${T("updated")}</span>` : null;   // i18n-keys
              if (s === "uptodate") return flashing ? html`<span class="prov-st ok"><${Ic} i="check"/> ${T("up to date")}</span>` : null;
              if (s === "failed" || p.error) return html`<${Fragment}><span class="prov-st err" title=${srvText(p) || ""}><${Ic} i="warn"/> ${p.last_updated ? T("update failed") : T("download failed")}</span><button class="btn btn-mini" style="margin-left:8px" onClick=${() => retryProvider(p.id)}>${T("Retry")}</button></>`;
              return null; })()}
            ${p.builtin ? null : html`<a class="prov-repo" href=${p.url} target="_blank" rel="noopener" title=${T("Open {v1}", { v1: T("{v1} on GitHub", { v1: p.label }) })}>${(p.url || "").replace(/^https?:\/\/github\.com\//, "")}</a>`}
          </div>`; })}${!_provReg.length ? html`<div class="hint">${T("Loading providers…")}</div>` : null}
            <div class=${"provrow bprow" + (customEnabled ? "" : " off")}>
              <${Switch} on=${customEnabled} title=${customEnabled ? T("On — you can create custom lists") : T("Off — the Custom lists section is hidden")} onChange=${v => setCustomEnabled(v)}/>
              <${ThemedSwatch} val=${provColors.custom} title=${T("Custom-list tag colour")} onChange=${nv => setProvColors(c => ({ ...c, custom: nv }))}
                sample=${(c) => html`<span class="sw-sample" style=${"--pc:" + c}>${T("src|Custom")}</span>`}/>
              <div class="bprov-meta">
                <div class="bprov-top"><span class="prov-name" style="color:var(--ink)">${T("Custom lists")}</span></div>
                <span class="bprov-note">${T("Your own IP / domain lists — turn off to hide the Custom lists section in routing.")}</span>
              </div>
            </div>
          </div>` : null}
          ${geoTab === "blocking" ? html`
          <p class="hint" style="margin:0 0 12px">${Trich("The block-list feeds that fill the *Blocking* tab's content categories (ads, malware, adult, and so on). Core feeds are on by default; turn on any extra feed to add its lists to the Blocking picker. Turning one off hides its lists and *deactivates* anything already filtering from it until you re-enable it. Each feed keeps its own tag colour.")}</p>
          ${(() => { const bcp = (Store.blockCatalog || {}).providers || [];
            const bpOn = p => blockProvEdits[p.id] !== undefined ? blockProvEdits[p.id] : (p.enabled !== false);
            return bcp.length ? html`<div class="provlist">${bcp.map(p => { const on = bpOn(p); const pcv = provColors[p.id] || asThemed((ps.provider_colors || {})[p.id], p.color, p.color_l || p.color); return html`<div class=${"provrow bprow" + (on ? "" : " off")} key=${p.id}>
              <${Switch} on=${on} title=${on ? T("On — its lists are selectable in Blocking") : T("Off — its lists are hidden and deactivated on nodes")} onChange=${v => setBlockProvEdits(m => ({ ...m, [p.id]: v }))}/>
              <${ThemedSwatch} val=${pcv} title=${T("{v1} tag colour", { v1: p.label })} onChange=${nv => setProvColors(c => ({ ...c, [p.id]: nv }))}
                sample=${(c) => html`<span class="sw-sample" style=${"--pc:" + c}>${p.label}</span>`}/>
              <div class="bprov-meta">
                <div class="bprov-top"><span class="prov-name" style=${"color:" + pickThemed(pcv, _provColDefault(p.id).dark, _provColDefault(p.id).light)}>${p.label}</span><span class="prov-tiers">${capBadges({ host: p.tier === "host", ip: p.tier === "ip" })}</span></div>
                ${p.note ? html`<span class="bprov-note">${T(p.note)}</span>` : null}
              </div>
              <span class="grow"></span>
              ${p.url ? html`<a class="prov-repo" href=${p.url} target="_blank" rel="noopener" title=${T("Open {v1}", { v1: p.label })}>${(p.url || "").replace(/^https?:\/\/(github\.com|raw\.githubusercontent\.com)\//, "").replace(/^www\./, "")}</a>` : null}
            </div>`; })}</div>` : html`<div class="hint">${T("Loading providers…")}</div>`; })()}` : null}

          <div class="seclabel" style="margin-top:20px">${T("Update schedule")}</div>
          <p class="hint" style="margin:0 0 10px">${Trich("When each node re-fetches its lists. Refreshing briefly reloads the node's match sets, which clients can feel — so schedule it for a *quiet hour*. (A failed fetch retries on the next sync; existing lists keep working meanwhile.)")}</p>
          <div class="schedrow">
            <div class="field" style="margin:0"><label>${T("How often")}</label>
              <${Dropdown} value=${guEvery} onChange=${v => setGuEvery(v)} options=${[
                { value: "1", label: T("Every day") }, { value: "2", label: T("Every 2 days") }, { value: "3", label: T("Every 3 days") },
                { value: "7", label: T("Every week") }, { value: "0", label: T("Continuous (rolling ") + T("{v1}-day TTL)", { v1: ttlD }) }]}/></div>
            <div class="field" style="margin:0"><label>${T("At (node-local time)")}</label>
              <input type="time" class="timein" value=${guAt} disabled=${guEvery === "0"} onInput=${e => setGuAt(e.target.value || "04:00")}/>
              <div class="hint">${guEvery === "0" ? T("Continuous mode ignores the time — nodes refresh whenever a list is older than the TTL.") : T("Nodes update at this local time, on the chosen cadence.")}</div></div>
          </div>
          <div class="georefresh"><span class="faint" style="font-size:11px">${T("Re-fetch every routed list from its provider now (updates the panel; nodes pull the changes on their schedule)")}</span><button class="btn btn-mini" disabled=${geoUpdating} onClick=${updateAllLists}><span class=${geoUpdating ? "tf-arrow" : ""}><${Ic} i="refresh"/></span> ${geoUpdating ? T("Updating…") : T("Update all lists now")}</button></div>
        </div>` : null}
        ${section === "integrations" ? html`<${IntegrationsSettings}/>` : null}
        ${section === "access" ? html`<${AccessTLSCard} onChange=${onAccess}/>` : null}
        ${section === "defaults" ? html`<div class="card">
          <div class="seclabel turnhead" style="margin-top:0">${T("Interface colours")}<span class="grow"></span>
            ${Object.keys(ifaceColorOverrides()).length ? html`<button class="btn btn-mini" onClick=${() => setIfaceColors({ wg: { ...IFACE_COLOR_DEFAULTS.wg }, awg: { ...IFACE_COLOR_DEFAULTS.awg }, wdtt: { ...IFACE_COLOR_DEFAULTS.wdtt }, csqtt: { ...IFACE_COLOR_DEFAULTS.csqtt } })}><${Ic} i="refresh"/>${T("Reset")}</button>` : null}</div>
          <p class="hint" style="margin:0 0 12px">${T("The colour each protocol's tags take everywhere — a value per theme. Hover a swatch to preview it.")}</p>
          <div class="palrow">
            <span class="palcell sw1"><${ThemedSwatch} val=${ifaceColors.wg} title=WireGuard onChange=${nv => setIfaceColors(c => ({ ...c, wg: nv }))}
              sample=${(c) => html`<span class="tg" style=${"background:color-mix(in srgb," + c + " 15%,transparent);color:" + c}>wg</span>`}/><span class="pallbl">WireGuard</span></span>
            <span class="palcell sw1"><${ThemedSwatch} val=${ifaceColors.awg} title=AmneziaWG onChange=${nv => setIfaceColors(c => ({ ...c, awg: nv }))}
              sample=${(c) => html`<span class="tg" style=${"background:color-mix(in srgb," + c + " 15%,transparent);color:" + c}>awg</span>`}/><span class="pallbl">AmneziaWG</span></span>
            <span class="palcell sw1"><${ThemedSwatch} val=${ifaceColors.wdtt} title=WDTT onChange=${nv => setIfaceColors(c => ({ ...c, wdtt: nv }))}
              sample=${(c) => html`<span class="tg" style=${"background:color-mix(in srgb," + c + " 15%,transparent);color:" + c}>WDTT</span>`}/><span class="pallbl">WDTT</span></span>
            <span class="palcell sw1"><${ThemedSwatch} val=${ifaceColors.csqtt} title=CSQTT onChange=${nv => setIfaceColors(c => ({ ...c, csqtt: nv }))}
              sample=${(c) => html`<span class="tg" style=${"background:color-mix(in srgb," + c + " 15%,transparent);color:" + c}>CSQTT</span>`}/><span class="pallbl">CSQTT</span></span>
          </div>
          <div class="seclabel">${T("Peer health detection")}</div>
          <p class="hint" style="margin:0 0 10px">${Trich("Two ways a peer can be under a filter, each independently switchable. Both raise the same {v1} badge — one is blocked at the door, the other gets in and can't stay. A peer that simply has nothing to send is never flagged.", { v1: html`<span class="b-blocked" style="padding:1px 6px;border-radius:6px">${T("tag|restricted")}</span>` })}</p>
          <div class="condrow"><${Switch} on=${statusConds.blocked} onChange=${v => setStatusConds(c => ({ ...c, blocked: v }))}/>
            <span class="cond-b"><span class="badge b-blocked ic"><${Ic} i="warn"/>${T("tag|restricted")}</span></span>
            <span class="cond-t">${T("The client's packets reach the server but no handshake has ever completed — blocked at the door (likely DPI / MTU / wrong Wireguard or AmneziaWG params).")}</span></div>
          <div class="condrow"><${Switch} on=${statusConds.faulty} onChange=${v => setStatusConds(c => ({ ...c, faulty: v }))}/>
            <span class="cond-b"><span class="badge b-blocked ic"><${Ic} i="warn"/>${T("tag|restricted")}</span></span>
            <span class="cond-t">${T("The tunnel keeps collapsing and being rebuilt: handshakes far more often than the 120s a healthy session renews at, from an endpoint that isn't moving. A peer that simply has nothing to send is not flagged.")}</span></div>
          <div class="seclabel">${T("Defaults")}</div>
          <p class="hint" style="margin:0 0 12px">${T("Applied when creating a new interface — you can still override per interface.")}</p>
          <div class="field"><label>DNS</label><input value=${dns} onInput=${e => setDns(e.target.value)} placeholder=${T("https://8.8.8.8/dns-query, 1.1.1.1")}/><div class="hint">${T("Comma-separated")}</div></div>
          <div class="row2"><div class="field"><label>MTU</label><input value=${mtu} onInput=${e => setMtu(e.target.value)} placeholder="1280"/></div>
            <div class="field"><label>${T("Persistent keepalive (s)")}</label><input value=${ka} onInput=${e => setKa(e.target.value)} placeholder="25"/></div></div>
            <${Disclosure} title=${T("AmneziaWG obfuscation")}
              summary=${AWG_KEYS.some(k => String(awgDef[k] ?? "").trim() !== "") ? T("settings|customised") : T("settings|built-in")}
              open=${awgOpen} onToggle=${() => setAwgOpen(o => !o)}>
              <p class="hint" style="margin:0 0 10px">${T("Given to every new AmneziaWG interface. Leave a cell blank to keep what the node does today — S and H are rolled fresh for each interface, so two interfaces never look alike. WireGuard interfaces ignore all of it.")}</p>
              <${AwgGrid} value=${awgDef} onChange=${setAwgDef} placeholders=${awgBlankHints()}/>
            <//>
          <div class="seclabel">${T("Key escrow & recovery")}</div>
          <p class="hint" style="margin:0 0 10px">${T("Backup each server's interface key so a wiped / rebuilt node restores its interfaces with their original identities.")}</p>
          <${InterfaceKeyEscrow} value=${ivkEscrow} onChange=${setIvkEscrow} vaultExists=${ivkVaultExists}/>
        </div>` : null}
        ${section === "defaults" ? html`<${IgnoredIfacesCard}/>` : null}
        ${section === "security" ? html`<div class="card">
          <div class="seclabel" style="margin-top:0">${T("Authentication")}</div>
          <p class="hint" style="margin:0 0 14px">${Trich("Change the panel username and password — applied on *{v1}*. Changing either takes effect immediately and you'll be asked to sign in again. Changing the password also re-keys your *Encryption Vault* in place, so stored configs and subscription links keep working (no re-issue).", { v1: T("Save") })}</p>
          ${!secAuth ? html`<div class="formmsg err">${T("This panel has no login configured — changes are disabled.")}</div>` : (secErr() ? html`<div class="formmsg err">${secErr()}</div>` : null)}
          <div class="field"><label>${T("Username")}</label><input value=${secUser} disabled=${!secAuth} onInput=${e => setSecUser(e.target.value)} autocomplete="username"/></div>
          <div class="field"><label>${T("Current password")}</label><input type="password" value=${secCur} disabled=${!secAuth} onInput=${e => setSecCur(e.target.value)} autocomplete="current-password" placeholder=${T("required to confirm a change")}/></div>
          <div class="row2"><div class="field"><label>${T("New password")}</label><input type="password" value=${secNp} disabled=${!secAuth} onInput=${e => setSecNp(e.target.value)} autocomplete="new-password" placeholder=${T("leave blank to keep current")}/></div>
            <div class="field"><label>${T("Confirm new password")}</label><input type="password" value=${secNp2} disabled=${!secAuth} onInput=${e => setSecNp2(e.target.value)} autocomplete="new-password"/></div></div>
          <${TwoFactorCard} enabled=${sec2fa} disabled=${!secAuth} onChange=${setSec2fa}/>
        </div>` : null}
        ${section === "configs" ? html`<div class="card">
          <div class="seclabel" style="margin-top:0">${T("Client configs")}</div>
          <div class="field"><label>${T("Store client configs")}</label>
            <${Dropdown} value=${sc} onChange=${v => setSc(v)} options=${[
              { value: "encrypted", label: T("Keep encrypted configs — QRs re-viewable anytime") },
              { value: "off", label: T("Keep nothing — QR shown once") }]}/>
            <div class=${"hint" + (sc === "off" ? " err" : "")}>${sc === "off" ? T("Live tunnels and creation-time QRs are unaffected, but you won't be able to re-view a peer's QR/config later — you'd rotate its key and re-distribute.") : T("Client configs are stored encrypted at rest (the server can't read the private keys) so a peer's QR stays re-viewable — you unlock it with your encryption key below. Requires the encryption key.")}</div></div>
          ${sc === "off" && subsOn ? html`<div class="hint warn" style="margin-top:10px"><${Ic} i="warn"/> ${Trich("Subscriptions are on and need encrypted config storage. Turn {v1} off first, or keep encrypted storage on — saving this as-is will be rejected.", { v1: html`<button class="linkbtn" onClick=${() => setSection("subs")}>${T("Subscriptions")}</button>` })}</div>` : null}
          <div class="seclabel">${T("Encryption")}</div>
          <p class="hint" style="margin:0 0 8px">${T("An encryption key held only by you (independent of your login password) protects stored client configs so the server can't read the private keys, and unlocks a peer's QR any time you're signed in. The same key powers subscriptions when you turn them on.")}</p>
          <${SubVaultCard}/>
          <${ConfigMigrationCard}/>
        </div>` : null}
        ${section === "subs" ? html`<div class="card">
          <div class="seclabel" style="margin-top:0">${T("Subscriptions")}</div>
          <p class="hint" style="margin:0 0 12px">${Trich("A shareable, themed, mobile page per user showing their QRs. The page's private keys ride in the URL *fragment* and are never sent to the panel — nothing readable is stored on the server. Treat each user's URL as a credential (whoever holds it holds that user's configs). A separate *swg-sub* service serves the page; configure it here and install it on the panel host.")}</p>
          <div class="field"><label>${T("Enable subscriptions")}</label>
            <${Dropdown} value=${subsOn ? "on" : "off"} disabled=${sc === "off"} onChange=${v => setSubsOn(v === "on")} options=${[
              { value: "off", label: T("Off — the subscription page is blocked entirely") },
              { value: "on", label: T("On — per-user subscription URLs are served") }]}/>
            ${sc === "off"
              ? html`<div class="hint warn">${Trich("Subscriptions serve the encrypted config blobs — turn on *Keep encrypted configs* in {v1} first.", { v1: html`<button class="linkbtn" onClick=${() => setSection("configs")}>${T("Client configs")}</button>` })}</div>`
              : html`<div class="hint">${T("Off returns 404 for every subscription URL, regardless of the rest.")}</div>`}</div>
          <div class="field"><label class="ivk-esc-row toggle-row"><${Switch} on=${autoGen} disabled=${!subsOn} onChange=${setAutoGen}/>
            <span>${T("Auto-generate subscription links for new users")}</span></label>
            <div class="hint">${T("When you create a user, mint their subscription link automatically, in the background (user creation stays instant). Needs the encryption key unlocked at that moment; otherwise the link is created the next time you open that user with the key unlocked.")}</div></div>
          <div class="seclabel">${T("Access expiry")}</div>
          <p class="hint" style="margin:0 0 12px">${Trich("A subscription or peer with an expiry date shows an orange *about to expire* warning this many days ahead.")}</p>
          <div class="field" style="max-width:340px"><label>${T("Warn before expiry (days)")}</label><input type="text" inputmode="numeric" value=${warnDays} onDblClick=${e => e.target.select()} onInput=${e => { let v = e.target.value.replace(/[^0-9]/g, ""); if (+v > 365) v = "365"; setWarnDays(v); }} placeholder=${T("Default: 3 (0 = warn only once expired)")}/></div>
          <div class="seclabel">${T("Address & certificate")}</div>
          <div class=${"subaddr" + (declarative ? " wide" : "")}>
            <div class="subaddr-row"><span class="subaddr-k">${T("Public URL")}</span><span class="subaddr-v mono">${subBaseUrl() || html`<span class="faint">${declarative ? T("Not set — give it sub.domain or sub.publicUrl") : T("Not set")}</span>`}</span></div>
            ${/* On a declarative host this row used to read 0.0.0.0:8444 — an unseeded default beside a
                  surface that is actually on loopback, and the one number a hand-written vhost needs. The
                  module now writes what it is really reached on, so name the row for what it is FOR. */""}
            <div class="subaddr-row"><span class="subaddr-k">${declarative ? T("Proxy to") : T("Listen")}</span><span class="subaddr-v mono">${(((ps.access || {}).sub || {}).host || "0.0.0.0")}:${(((ps.access || {}).sub || {}).port || 8444)}</span></div>
            <div class="subaddr-row"><span class="subaddr-k">${T("Certificate")}</span><span class="subaddr-v mono">${tlsModeLabel(((ps.access || {}).tls || {}).mode || "")}</span></div>
          </div>
          <div class="hint" style="margin:6px 0 0">${declarative
            ? html`${Trich("This page's address comes from the configuration that built this machine — `services.swg-panel.sub.domain`, `sub.basePath`, `sub.publicUrl` and `sub.port`.")}
                <div style="margin-top:5px">${Trich("{v1} shows them beside a virtual host you can paste.", { v1: html`<button class="linkbtn" onClick=${() => setSection("access")}>${T("Panel access")}</button>` })}</div>`
            : Trich("The subscription page's URL, listen address and certificate are configured in {v1}.", { v1: html`<button class="linkbtn" onClick=${() => setSection("access")}>${T("Panel access")}</button>` })}</div>
          <div class="seclabel">${T("Languages")}</div>
          <div class="field"><label>${T("Offered on the subscription page")}</label>
            <div class="sublangs">${SUB_LANG_LIST.map(([id, name]) => html`<div class=${"sublang" + (subLangs.includes(id) ? " on" : "")} key=${id}>
              <label class="sublang-en"><input type="checkbox" checked=${subLangs.includes(id)} onChange=${e => toggleSubLang(id, e.target.checked)}/><span>${name}</span></label>
              <button class=${"sublang-def" + (subLangDef === id ? " on" : "")} disabled=${!subLangs.includes(id)} onClick=${() => setSubLangDef(id)} title=${T("Load this language by default")}>${subLangDef === id ? T("state|Default") : T("Set default")}</button>
            </div>`)}</div>
            <div class="hint">${Trich("Which languages the page offers. With just one enabled, it hides the selector and loads that language; the *default* is what loads first when several are offered.")}</div></div>
          <div class="seclabel">${T("Encryption")}</div>
          <p class="hint" style="margin:0">${Trich("Subscriptions reuse the same encryption key that protects your stored client configs — set it up under {v1}. No separate key.", { v1: html`<button class="linkbtn" onClick=${() => setSection("configs")}>${T("Client configs → Encryption")}</button>` })}</p>
        </div>` : null}
        ${section === "display" ? html`<div class="card">
          <div class="seclabel turnhead" style="margin-top:0">${T("Interface theme")}<span class="grow"></span>
            ${(themeColorS.toLowerCase() !== THEME_COLOR_DEFAULT.toLowerCase() || themeColorLightS.toLowerCase() !== THEME_COLOR_LIGHT_DEFAULT.toLowerCase()) ? html`<button class="btn btn-mini" onClick=${() => { setThemeColorS(THEME_COLOR_DEFAULT); setThemeColorLightS(THEME_COLOR_LIGHT_DEFAULT); }}><${Ic} i="refresh"/>${T("Reset")}</button>` : null}</div>
          <p class="hint" style="margin:0 0 12px">${Trich("The panel's accent colour — button borders, checkboxes, focus rings, the throughput \"down\" series and the live / hour / day / week / month chart tabs all follow it. A separate colour for each mode; switch *Light / Dark / Auto* from the sun / moon button in the header.")}</p>
          <div class="palrow">
            <${ThemedSwatch} val=${themeVal} title=${T("Interface theme")} onChange=${nv => { setThemeColorS(clampBrand(nv.dark, false)); setThemeColorLightS(clampBrand(nv.light, true)); }}
              sample=${(c) => html`<span class="tsw-theme"><span class="tsw-btn" style=${"color:" + c}>${T("sample|Button")}</span><span class="tsw-chip" style=${"color:" + c}></span></span>`}/>
          </div>
          <div class="seclabel">${T("Display")}</div>
          <div class="field"><label>${T("Throughput perspective")}</label>
            <${Dropdown} value=${tput} onChange=${v => setTput(v)} options=${[
              { value: "nodes", label: T("Nodes — what the node downloads / uploads") },
              { value: "peers", label: T("Peers — what the client downloads / uploads") }]}/>
            <div class="hint">${T("Which way ↓/↑ are labelled across the panel. Same numbers, swapped arrows.")}</div></div>
          <div class="field"><label>${T("Throughput units")}</label>
            <${Dropdown} value=${tunit} onChange=${v => setTunit(v)} options=${[
              { value: "bytes", label: T("Bytes — MB/s, what the node counts") },
              { value: "bits", label: T("Bits — Mbit/s, like a speed test") }]}/>
            <div class="hint">${T("How every speed in the panel is written. The same measurement either way — bits are 8× the number, and are what speed tests, ISP plans and router pages quote. Totals are always in bytes.")}</div></div>
          <div class="seclabel">${T("Status timing")}</div>
          <p class="hint" style="margin:0 0 12px">${T("How long the panel waits before treating things as stale — in seconds.")}</p>
          <div class="row2"><div class="field"><label>${T("Node stale after (s)")}</label><input value=${staleS} onInput=${e => setStaleS(e.target.value)} placeholder="30"/><div class="hint">${T("No sync for this long → the node shows stale.")}</div></div>
            <div class="field"><label>${T("Peer grace window (s)")}</label><input value=${graceS} onInput=${e => setGraceS(e.target.value)} placeholder="60"/><div class="hint">${T("A peer stays \"online\" this long after its last handshake.")}</div></div></div>
          <div class="seclabel">${T("Overview lists")}</div>
          <p class="hint" style="margin:0 0 12px">${T("How many rows the Overview's ranked lists show (1–50).")}</p>
          <div class="row2"><div class="field"><label>${T("Top talkers")}</label><input type="text" inputmode="numeric" value=${topTalk} onDblClick=${e => e.target.select()} onInput=${e => { let v = e.target.value.replace(/[^0-9]/g, ""); if (+v > 50) v = "50"; setTopTalk(v); }} placeholder="10"/><div class="hint">${T("Number of peers in the Top talkers list (max 50).")}</div></div>
            <div class="field"><label>${T("Top destinations")}</label><input type="text" inputmode="numeric" value=${topDest} onDblClick=${e => e.target.select()} onInput=${e => { let v = e.target.value.replace(/[^0-9]/g, ""); if (+v > 50) v = "50"; setTopDest(v); }} placeholder="10"/><div class="hint">${T("Number of categories in the Top destinations list (max 50).")}</div></div></div>
        </div>` : null}
        ${/* Mesh and egress are one topic — this node's addressing: how other nodes reach it, and what source
              IP its traffic leaves with. They were two rail entries with identical chrome (both per-node, both
              a node picker) and egress was two fields. They also interact: cascade sends a node's traffic out
              through ANOTHER node, and that path rides the mesh. One section, two sub-blocks. */""}
        ${/* EXTERNAL EXITS — its own rail item since a47abb9's reroute was reversed. It stopped being "one
              more egress field" the moment it grew three creation paths, a per-provider control, health and
              an unbounded list: in the Network card it was taller than ingress + egress + mesh combined, a
              sub-block dominating the section that contained it. The rail's own grammar already has this
              shape — Turn proxies is create/manage/monitor for a thing interfaces reference, and so is this.
              Cost, stated because it is real: "how does this node get out?" now has two homes, with the
              source addresses still under Network. Reversible — the move is five edits. */""}
        ${section === "exits" ? html`<div class="card">
          ${nodeRec ? html`<${Fragment}>
            <div class="seclabel" style="margin-top:0">${T("{v1} — external exits", { v1: nodeRec.name })}</div>
            <${NodeExitsForm} key=${selNode} node=${nodeRec} vals=${nodeEdits[selNode]} set=${p => setNV(selNode, p)}
              goSection=${setSection} escrowOn=${ivkEscrowInit}
              ${/* Same writer the Network screen uses: exits are saved on the spot and both sides of the
                    dirty check are re-based, so this section no longer stages anything at all. */""}
              saveExits=${async xs => {
                const rr = await api.nodeUpdate({ id: selNode, exits: xs });
                // ⚠️ A REFUSAL IS A SENTENCE, NOT A CODE. The server answers a refused device with its
                // verdict (`refusal`) and the card it is about (`device`); the panel already owns a
                // translated sentence for every one of those codes, and it is the same one the picker
                // shows. Without this the operator got "exit device refused: nic_nogw" in a toast —
                // observed in the browser on hel-flux during 1.8.5 qualification, on the one feature this
                // release leads with. `srvText` stays the fallback for every other failure.
                if (!rr || !rr.ok) {
                  toast(exitRefusalText(rr && rr.refusal, rr && rr.device) || srvText(rr) || T("Couldn't save"), "err");
                  return false;
                }
                await Store.poll();
                const fresh = nFields((Store.nodes || []).find(n => n.id === selNode) || {});
                setNV(selNode, { exits: fresh.exits });
                setOrig(o => ({ ...o, [selNode]: { ...(o[selNode] || {}), exits: fresh.exits.map(x => ({ ...x })) } }));
                return true;
              }}
              onBlock=${m => setExitWhy(w => (w[selNode] === m ? w : { ...w, [selNode]: m }))}/>
          <//>`
            : html`<p class="hint" style="margin:0">${T("No nodes yet — enroll a node to give it a way out that isn't its own address.")}</p>`}
        </div>` : null}
        ${section === "mesh" ? html`<div class="card">
          ${nodeRec ? html`<${Fragment}>
            ${/* T-25: THREE sections, not two. The ingress address lived under "mesh" and its own hint
                  apologised for it — "despite living under Mesh, this is also the host in every client
                  config" — which is a label admitting it is in the wrong place. In / out / between is how
                  an operator thinks about a node's connectivity, and each is now findable by its name. */""}
            <div class="seclabel" style="margin-top:0">${T("{v1} — ingress", { v1: nodeRec.name })}</div>
            <${NodeIngressForm} node=${nodeRec} vals=${nodeEdits[selNode]} set=${p => setNV(selNode, p)}/>
            <div class="seclabel">${T("{v1} — outbound addresses", { v1: nodeRec.name })}</div>
            <${NodeEgressForm} node=${nodeRec} vals=${nodeEdits[selNode]} set=${p => setNV(selNode, p)}
              escrowOn=${ivkEscrowInit} goSection=${setSection}
              ${/* ⚠️ SEEDED AND RE-BASED THROUGH `nFields`, NEVER FROM A RAW RECORD. /api/state attaches
                    derived fields to each exit (`why_not`, `live`, `key_blob`) and `nFields` strips them on
                    purpose — seeding or re-basing with them would leave the draft a different SHAPE from
                    the baseline, so the section would read dirty forever and re-submit server verdicts as
                    if the operator had typed them. */""}
              ${/* One writer for every exit change this screen makes, and it re-bases BOTH sides of the
                    dirty check from the server's answer — the draft and the baseline — so no section is
                    left offering to save something that is already saved. */""}
              saveExits=${async xs => {
                const rr = await api.nodeUpdate({ id: selNode, exits: xs });
                // ⚠️ A REFUSAL IS A SENTENCE, NOT A CODE. The server answers a refused device with its
                // verdict (`refusal`) and the card it is about (`device`); the panel already owns a
                // translated sentence for every one of those codes, and it is the same one the picker
                // shows. Without this the operator got "exit device refused: nic_nogw" in a toast —
                // observed in the browser on hel-flux during 1.8.5 qualification, on the one feature this
                // release leads with. `srvText` stays the fallback for every other failure.
                if (!rr || !rr.ok) {
                  toast(exitRefusalText(rr && rr.refusal, rr && rr.device) || srvText(rr) || T("Couldn't save"), "err");
                  return false;
                }
                await Store.poll();
                const fresh = nFields((Store.nodes || []).find(n => n.id === selNode) || {});
                setNV(selNode, { exits: fresh.exits });
                setOrig(o => ({ ...o, [selNode]: { ...(o[selNode] || {}), exits: fresh.exits.map(x => ({ ...x })) } }));
                return true;
              }}
              openManage=${seed => openModal(html`<${ExitManageSheet} node=${nodeRec}
                seed=${seed || nFields(nodeRec).exits}
                onSaved=${() => {
                  // BOTH SIDES OF THE DIRTY CHECK, and both from the SERVER's answer rather than from what
                  // the sheet happened to hold. Writing only the draft left it equal to the server and
                  // unequal to `orig`, so the section sat there offering to save a change that was already
                  // saved — and pressing it would have written the same thing a second time.
                  const fresh = nFields((Store.nodes || []).find(n => n.id === selNode) || {});
                  setNV(selNode, { exits: fresh.exits });
                  setOrig(o => ({ ...o, [selNode]: { ...(o[selNode] || {}), exits: nFields((Store.nodes || []).find(n => n.id === selNode) || {}).exits } }));
                }}/>`)}/>
            <div class="seclabel">${T("{v1} — mesh", { v1: nodeRec.name })}</div>
            <${NodeMeshForm} node=${nodeRec} vals=${nodeEdits[selNode]} set=${p => setNV(selNode, p)}/>
          <//>`
            : html`<p class="hint" style="margin:0">${T("No nodes yet — enroll a node to configure how it is reached, how it exits, and how it links.")}</p>`}
        </div>` : null}
        <div class="setfoot">
          ${section === "access"
            ? null   /* access status (incl. "applying, be patient") is consolidated into the card's top banner, scrolled into view on Save */
            : (Date.now() < saved ? html`<span class="savedflash"><${Ic} i="check"/> ${T("All settings saved")}</span>` : null)}
          <span class="grow"></span>
          <button class="btn btn-ghost" onClick=${leaveSettings}>${T("Back")}</button>
          ${section === "access"
            ? html`<button class="btn btn-primary" disabled=${accessRef.current.busy || !accessRef.current.dirty} title=${!accessRef.current.dirty ? T("No changes to save") : ""} onClick=${() => accessRef.current.run()}>${accessRef.current.busy ? T("Saving…") : T("Save")}</button>`
            : html`<button class="btn btn-primary" disabled=${!!secErr() || !!exitErr() || !anyDirty} title=${secErr() || exitErr() || (!anyDirty ? T("No changes to save") : "")} onClick=${confirmSave}>${T("Save")}</button>`}</div>
      </div>
    </div>
  </div>`;
}

/* ⚠️ CALLERS PASS A `key`. Every field here is `useState`-seeded from `list`, and an initialiser runs once
   per mounted instance — so replacing an open sheet with another of the same type keeps the first one's
   state: the header reads "New list" over the previous list's name and badges. Not reachable while the
   overlay covers the page, which is why it survives; keyed anyway, because "unreachable today" is a
   property of the modal host, not of this component. */
export function CustomListSheet({ list, onSave, onClose }) {
  const [title, setTitle] = useState(list?.title || "");
  // customTargets, not a second copy of it. This said `domains + cidrs` and left `asns` out, which would
  // drop an AS token the first time anyone opened a list and pressed Save — the exact freeze §6.10 removed
  // from the panel. It never fired, because the Settings screen sets `targets` through customTargets before
  // this ever opens, so the fallback was dead code that disagreed with the live path. Dead and divergent is
  // how it comes back: one caller passing a raw record and the AS is gone with no error anywhere.
  /* THE SAME FIELD A RULE USES. It was a plain textarea, which meant an operator building a list got none
     of what they had just learned building a rule: no per-target badge saying what a token WILL match, no
     `</>` text view, no click-to-edit, no reason attached to the token that was refused. The control was
     already policy-free by construction — `targetGate` returns ok with no mode ("no mode known → gate
     nothing"), and readToken takes its policy injected — so reusing it needed a context flag, not a fork.
     `listEditor`: no engine to gate against, no catalog, and no nesting (see readToken). */
  const [badges, setBadges] = useState(() =>
    classifyAll(customTargets(list)).filter(c => c.kind !== "invalid")
      .map(c => ({ t: "target", raw: c.raw, kind: c.kind, value: c.value })));
  const [lint, setLint] = useState(null);
  // `lint` first: an uncommitted text draft is not "no targets", and saying "add at least one" while the
  // operator is looking at ten lines they just typed would be the panel disagreeing with the screen.
  const err = lint || (!badges.length ? T("add at least one address, domain or pattern") : null);
  // The stored default stays English: this is roster DATA, shared by every operator and read back by the
  // nodes, so it must not depend on which language the person who created the list happened to be using.
  // Display translates it (see the delete prompt) — storage does not.
  // `raw`, not the badge's display text: the badge shows a name IDN-folded for reading, and storage wants
  // what was typed. The server re-derives every kind from it anyway.
  const save = () => { if (err) return; onSave({ ...(list || { _rid: newRid() }),
    title: title.trim() || "Untitled list",   // i18n-keys: the STORED default — roster data, read back by the nodes
    targets: badges.map(b => b.raw).join(", ") }); onClose(); };
  const foot = html`<span class="grow"></span><button class="btn btn-ghost" onClick=${onClose}>${T("Cancel")}</button><button class="btn btn-primary" disabled=${!!err} title=${err || ""} onClick=${save}>${list ? T("Save") : T("Add")}</button>`;
  return html`<${Sheet} title=${list ? T("Edit list") : T("New list")} width=${640} onClose=${onClose} foot=${foot}>
    <div class="field"><label>${T("Title")}</label><input value=${title} onInput=${e => setTitle(e.target.value)} placeholder=${T("e.g. Streaming")}/></div>
    <div class="field"><label>${T("Addresses, domains and patterns")}</label>
      <${TargetField} row=${{ badges }} onChange=${setBadges} onLint=${setLint} listEditor=${true}/>
      <${AsnHint} targets=${badges.map(b => b.raw).join(", ")}/>
      ${err ? html`<div class="rrlint" style="margin-top:5px">${err}</div>`
            : html`<div class="hint">${Trich("Domains match their subdomains too; IPs / CIDRs directly; an *AS number* (e.g. AS62041) resolves to that provider's IP ranges. Patterns work here exactly as they do in a rule.")}</div>`}</div>
  <//>`;
}

// Per-node INGRESS: the one address everything outside dials to reach this node (T-25). It used to sit
// inside the mesh form, where its own hint had to begin "despite living under Mesh…" — a label apologising
// for its own placement is the clearest possible sign the grouping was wrong.
function NodeHostRow({ node, value, onChange, onRemove }) {
  const state = useHostOnNode(value, node.ips || []);
  return html`<div style="display:flex;gap:8px;align-items:flex-start;margin-top:6px">
    <div style="flex:1;min-width:0">
      <input value=${value} placeholder=${T("vpn.example.com")} onInput=${e => onChange(e.target.value)}/>
      ${state === "bad" ? html`<div class="hint err">${T("This doesn't resolve to an address on this node.")}</div>` : null}
    </div>
    <button class="btn btn-mini ico" title=${T("Remove")} onClick=${onRemove}><${Ic} i="trash"/></button>
  </div>`;
}

export function NodeHostList({ node, value, onChange }) {
  const hosts = value || [];
  const set = (i, v) => onChange(hosts.map((h, k) => (k === i ? v : h)));
  return html`<div class="field">
    <label>${T("Hostnames for this node")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— offered wherever a host is asked for")}</span></label>
    ${hosts.map((h, i) => html`<${NodeHostRow} key=${i} node=${node} value=${h}
        onChange=${v => set(i, v)} onRemove=${() => onChange(hosts.filter((_, k) => k !== i))}/>`)}
    <button class="btn btn-ghost btn-mini" style="margin-top:8px" onClick=${() => onChange([...hosts, ""])}>
      <${Ic} i="plus"/> ${T("Add a name")}</button>
    <div class="hint">${T("Every picker that asks for a host offers these — interfaces, turn proxies, WDTT and csqtt. They do not change what clients dial; the ingress address above does that.")}</div>
  </div>`;
}

/* ─── EXTERNAL EXITS — a node's ways OUT that are not its own address (plan decision 10) ───────────
   Lives beside egress rather than on a rail entry of its own, and that is a decision this screen has
   already made once: mesh and egress were two rail entries with identical chrome (both per-node, both a
   node picker) and were merged into one card because they are one topic. A third entry for "the other way
   out" would rebuild exactly that duplication. The Network card reads in / out / between; an exit device is
   another *out*, so it sits next to the one it belongs with and is findable by its own name.

   ⚠️ EVERY EXIT IS SHOWN, including one whose device the panel currently refuses. The list must stay
   SAVABLE: a device that was fine when it was written can stop being offerable later (adopted as an
   interface, a turn instance took the name), and refusing the save then is how the list locks — including
   the save that would remove the bad entry. Creating one is blocked, keeping one is not (`_validate_exits`
   holds the same asymmetry on the server, and this mirrors it rather than inventing a second rule). */
const newExitId = () => Array.from(crypto.getRandomValues(new Uint8Array(4)))
  .map(b => b.toString(16).padStart(2, "0")).join("");   // matches the server's EXIT_ID_RE, so the row keeps one id from birth

/* What the NODE says about an exit it created — registered, up, and what the internet actually sees.
   §7.2's one call proves three things, so it is rendered as one line rather than three fields. */
/* DECISION 8 on screen: whether the panel holds a sealed copy, and the one action that uses it.
   The restore is done BY THE BROWSER — unseal with the operator vault key, re-seal to the node's transport
   key — so the panel relays ciphertext and never holds the plaintext it is escrowing. */
function ExitEscrow({ node, ex, stored, live, goSection, escrowOn }) {
  const [busy, setBusy] = useState(false);
  if ((ex.producer || "adopted") !== "imported" || ex.provider === "profile") return null;
  const blob = (stored || {}).key_blob || null;
  const nodeHasKey = !!(live || {}).public_key;
  // ⚠️ NOTHING IS SAID ABOUT ESCROW ITSELF ANY MORE. It is ON by default and its switch lives on the
  // Interfaces screen; repeating its state under every exit was noise, and an operator who turned it off
  // knows they did. What is left is the one case that is an ACTION rather than a status.
  //
  // ⚠️ AND THERE ARE TWO OF THEM, because the first one was unreachable. `!nodeHasKey` is the rebuilt-node
  // case — and a WARP exit that loses its key registers a fresh account on its very next pass, so the node
  // has a key again within one sync interval. Measured on msk-main: new key reported at t=10s, escrow
  // holding it by t=20s; the window this offer needed was never once observed. The panel now KEEPS the
  // displaced key, so the case an operator actually walks into — "my exit's address changed and I don't
  // know why" — has a row that says so and a way back.
  const prev = (stored || {}).key_blob_prev || null;
  // ⚠️ A RESTORE THAT COULD NOT BE CARRIED OUT IS SAID HERE, ON THE ROW WHOSE BUTTON ASKED FOR IT — and
  // NOT as an exit fault. The node reports it separately from `error` precisely so a working exit stays
  // green: it is up, on its own key, and the only thing that failed is a request. The blob is sealed to
  // this node's transport key, so the reachable causes are a node rebuilt since the seal or a vault that
  // has moved; re-sealing is one more press of the same button, from a browser that can open the escrow.
  // The relay expires on its own within the hour, so this states a fact rather than offering a dismissal.
  const restoreErr = String((live || {}).restore_error || "").trim();
  if (restoreErr) return html`<span class="hint warn">${T("The escrowed key could not be put back — the node has kept the one it has.")}
    ${" "}${T("It reports: {v1}", { v1: T(restoreErr) })}
    ${" "}${T("Try again from a browser that can open the vault; if this node was rebuilt since the key was sealed, the escrow has to be re-sealed to it.")}</span>`;
  // ⚠️ ASK FOR THE VAULT, DON'T REPORT THAT IT IS LOCKED. `ivkResealForNodeBlob` throws
  // "Unlock the Encryption Vault first." and this caught it into a toast — a sentence that names the
  // requirement and offers no way to meet it, on a button whose whole job is the one action that needs it.
  // Measured in the browser: click, toast, nothing else, no prompt, no path forward. Its WDTT twin
  // (`turn.js`, restore this server's identity) has always called `ensureVaultUnlocked` with a title, a
  // reason and the cost of skipping; this is the same idea implemented twice, once correctly. Now once.
  const restore = async (b, ask) => {
    if (!(await ensureVaultUnlocked(ask))) return;   // the operator chose to skip — the prompt said what that costs
    setBusy(true);
    try {
      const sealed = await ivkResealForNodeBlob(node.id, b, T("No escrowed key is stored for this exit."));
      // ⚠️ the pub travels too: the panel cannot read it out of the ciphertext, and without it the
      // sync loop cannot tell "the node applied the restore" from "the node has some key of its own".
      const r = await api.exitRestore(node.id, ex.id, sealed, b && b.pub);
      toast(r && r.ok ? T("Restoring — the node applies it on its next sync.") : (srvText(r) || T("Failed")), r && r.ok ? "ok" : "err");
    } catch (e) { toast((e && e.message) || T("Failed"), "err"); }
    setBusy(false);
  };
  // Two situations, so two reasons — the cost of skipping is not the same thing in both.
  const ASK_BACK = () => ({
    title: T("Unlock to put the old key back"),
    // ⚠️ WHAT IS ACTUALLY GUARANTEED IS THE ACCOUNT, NOT THE ADDRESS. Measured on msk-main: a WARP
    // account holds one address for as long as its device stays up (eight samples over 160 s, seven
    // accounts, none moved) — but the SAME account came back on 104.28.198.244 after a restore of the one
    // that had been on .245, and a pause/resume moved another from .245 to 104.28.230.245. Cloudflare
    // assigns it per bring-up. "so websites see the address they saw before" would have been a promise
    // this panel cannot keep, on the screen where an operator decides whether the restore is worth doing.
    reason: T("This exit's original account is escrowed under your encryption key — the panel only ever held the ciphertext, and only you can open it. Unlock it to put that account back, along with any WARP+ licence on it. Cloudflare picks the exit address, so the old one usually comes back with it."),
    consequence: T("nothing changes. The exit keeps the account it just registered, and the address websites see stays the new one."),
  });
  const ASK_FRESH = () => ({
    title: T("Unlock to restore this exit's key"),
    reason: T("This node has no key for this exit, and the one it had is escrowed under your encryption key — the panel only ever held the ciphertext. Unlock it to give the node its original account back instead of a new one."),
    consequence: T("nothing is restored. The node registers a new account on its next pass instead, and websites start seeing a different address."),
  });
  // ⚠️ `nodeHasKey` DECIDES WHICH QUESTION THIS IS, AND IT HAS TO BE ASKED FIRST. Without it the
  // displaced-key branch outranked the no-key one, so a node that re-registered once (leaving
  // `key_blob_prev`) and was THEN rebuilt got the wrong sentence — "This exit registered a new account, so
  // the address websites see has changed", about an exit that has no account at all — and "Put the old one
  // back" restored `prev`, the generation BEFORE the key the escrow currently holds. Two wrong answers to
  // a question nobody asked. When the node has no key there is only ever one offer: the escrow's own
  // current blob, which is the key it lost.
  if (prev && prev.ct && nodeHasKey) {
    // The node minted its own key and the panel still holds the one before it. Two answers, and neither is
    // a default: going back restores an address something outside this panel may be allow-listed against,
    // and keeping the new one is perfectly reasonable if nothing was.
    return html`<span>${T("This exit registered a new account, so the address websites see has changed. The panel still holds the key it had before.")}
      ${" "}<button class="btn btn-mini" disabled=${busy}
        onClick=${() => restore(prev, ASK_BACK())}>${busy ? T("Restoring…") : T("Put the old one back")}</button>
      ${" "}<button class="btn btn-mini btn-ghost" disabled=${busy} onClick=${async () => {
        setBusy(true);
        try {
          const r = await api.exitEscrowForget(node.id, ex.id);
          toast(r && r.ok ? T("Keeping the new account.") : (srvText(r) || T("Failed")), r && r.ok ? "ok" : "err");
        } catch (e) { toast((e && e.message) || T("Failed"), "err"); }
        setBusy(false);
      }}>${T("Keep the new one")}</button></span>`;
  }
  // ⚠️ `blob || prev`, so a rebuilt node is never left with nothing to restore. `key_blob` is the escrow of
  // the key the exit HAD; `key_blob_prev` only exists alongside it, so the fallback should be unreachable —
  // but "should be unreachable" is how a node with a displaced key and no current escrow would silently get
  // no offer at all, on the one screen that exists to make that recoverable.
  const _restorable = (blob && blob.ct) ? blob : prev;
  if (!_restorable || nodeHasKey) return null;
  // the node has no key and the panel holds one: this is exactly the rebuilt-node case escrow exists for
  return html`<span>${T("This node has no key for this exit. Restore the escrowed one to keep the same address, or leave it to register a new account.")}
    ${" "}<button class="btn btn-mini" disabled=${busy}
      onClick=${() => restore(_restorable, ASK_FRESH())}>${busy ? T("Restoring…") : T("Restore from vault")}</button></span>`;
}

/* `ExitLive` used to live here — a prose line ("Up on wgx-…. Websites see 1.2.3.4. WARP+ is active.")
 * rendered under each exit. `d3a29ad` ("the screen is a grid you read and a sheet you edit in") removed the
 * one place that mounted it and left the function behind, so it rendered nothing while still LOOKING like
 * the exits screen's detail line — which is how it came to be edited, and gated, as if it were live.
 *
 * Deleted rather than re-mounted, and the grid is why: WARP vs WARP+ is now the row's own badge
 * (`exitBadge` reads `live.account_type`), "up"/"waiting"/the error and its retry are `exitHealth`'s
 * `why`, and the egress address has its own field. The only sentence with nowhere left to go was
 * "Cloudflare does not report this as WARP" — and `exitHealth` refuses that one on purpose: see its note on
 * why an imported exit with an unconfirming trace must not go amber (a node whose egress is firewalled to
 * specific destinations would wear a permanent warning for a tunnel that works). Keeping a second, silent
 * implementation of the same verdict ordering was the trap, not the missing line.
 */

/** ── MANAGE EXTERNAL INTERFACES ─────────────────────────────────────────────────────────────────────────
 *  A grid of the devices this node can leave by that the PANEL DID NOT CREATE. WARP accounts and pasted
 *  profiles are deliberately absent: those are made and unmade in Settings → WARP, they carry inputs a grid
 *  row cannot hold (a licence key, a whole profile), and mixing them here would put the same record on two
 *  screens with two ways to edit it.
 *
 *  TWO KINDS OF ROW, and the difference is the whole point of the Type column:
 *    discovered   the node reports the device. Adopting it only means the panel starts KEEPING an opinion
 *                 about it (a name, on/off, a kill-switch); the device runs either way, so there is nothing
 *                 to delete — removing the record just returns it to this list unnamed.
 *    custom       a name the operator typed that the node has NOT reported. Nothing on the box corresponds
 *                 to it yet, so it is the one kind whose row can be deleted outright.
 *
 *  ⚠️ "USED BY" IS THE LOAD-BEARING COLUMN. Switching an exit off is silent and instant — everything
 *  pointing at it falls back to leaving directly, keeping its selection — so the only thing standing
 *  between the operator and "why did three interfaces change egress?" is knowing what is attached BEFORE
 *  they touch the switch. It counts every holder, not just interfaces: an interface pinned to it, a smart
 *  RULE routing one category through it, and the node's own default all break the same way.
 */
function ExitUsedBy({ node, id }) {
  if (!id) return html`<span class="faint">—</span>`;
  const users = [];
  // ⚠️ `Store.describe` HOLDS THE INTERFACES THE NODE REPORTED, not the ones it is configured with, so this
  // can UNDERCOUNT on a node that is down or mid-provision. It cannot overcount, and disabling an exit is
  // reversible and non-destructive (everything attached degrades to direct and keeps its selection), so an
  // undercount misleads without breaking. Said plainly in the bubble rather than papered over.
  for (const [ifn, m] of Object.entries(Store.describe[node.id] || {})) {
    if (!m || m.system) continue;
    if (m.egress_mode === "exit" && String(m.exit_id || "") === String(id)) users.push([ifn, T("all traffic")]);
    else if (m.egress_mode === "smart") {
      const n = (m.routing || []).filter(r => r && r.action === "dev" && String(r.exit_id || "") === String(id)).length;
      if (n) users.push([ifn, plural(n, "rule")]);
    }
  }
  if (String(node.default_exit || "") === String(id)) users.push([T("This node's default"), T("anything not pinned elsewhere")]);
  if (!users.length) return html`<span class="faint">${T("val|Not used")}</span>`;
  const trig = html`<span class="exu-n">${plural(users.length, "user")}</span>`;
  // `.deprow` is the shared bubble row — same padding, radius and hover geometry as every other hover list
  // in the app. Rolling a private one here is what made this bubble look like a different product.
  return html`<${Popover} hoverOnly cls="exu-wrap" popCls="exu-pop" trigger=${trig}>
    ${users.map(([a, b], i) => html`<div class="deprow exu-r" key=${i}>
      <b>${a}</b><span class="grow"></span><span class="faint">${b}</span></div>`)}
    <div class="exu-f">${T("Turning it off sends these out directly — they keep the selection.")}</div>
  <//>`;
}

/** THE THREE QUESTIONS THAT MAKE AN ADOPTED EXIT — what it is called, which device it is, and what source
 *  its traffic leaves as. Asked in two places (the node's egress picker and the manage sheet's add row) and
 *  they were two hand-written copies until this: same fields, same keys, same picker, drifted apart anyway.
 *  The manage sheet's copy still wrote the field names INSIDE the boxes as placeholder text while the other
 *  had grown labels, so the same act looked like two different forms depending on which screen you reached
 *  it from. One component, one answer.
 *
 *  `devEditable` is the only real difference between the callers: a name the operator invented is theirs to
 *  correct, a name the NODE reported is that box's own device and editing it would repoint the exit at
 *  something else. `discovered` is looked up by the caller from the name as it is TYPED, so entering a name
 *  the node already reports turns "Auto" into "Auto (10.66.0.2)" under the operator's hands. */
function ExitFields({ value, onChange, discovered, devEditable, submitLabel, onSubmit, onCancel, hint, addrs, isNic, gw }) {
  const key = e => { if (e.key === "Enter") { e.preventDefault(); onSubmit(); }
                     if (e.key === "Escape") onCancel(); };
  const fld = (cls, label, ctl) => html`<span class=${"exname-f " + cls}>
    <span class="exname-lbl">${label}</span>${ctl}</span>`;
  return html`<div class="exname">
    ${fld("exname-t", T("Title — optional"), html`<input value=${value.title || ""} autofocus maxlength="40"
      spellcheck="false" autocomplete="off"
      onInput=${e => onChange({ title: e.target.value })} onKeyDown=${key}/>`)}
    ${fld("exname-d", T("Device name"), html`<input class="mono" value=${value.device || ""}
      spellcheck="false" autocomplete="off" readonly=${!devEditable} disabled=${!devEditable}
      placeholder=${T("e.g. tun0")}
      onInput=${e => onChange({ device: e.target.value })} onKeyDown=${key}/>`)}
    ${fld("exname-eg", T("Leaves as"), html`<${ExitEgressPick} discovered=${discovered} addrs=${addrs}
      value=${value.egress_ip || ""} onChange=${val => onChange({ egress_ip: val })}/>`)}
    ${/* ⚠️ THE TYPED GATEWAY, AND IT IS NOT OPTIONAL POLISH. The node detects a card's gateway from its
          DEFAULT ROUTE, and a second uplink reached only by policy routing has none — measured in the rig,
          a whole class of two-NIC boxes. Without this field those cards are refused with a sentence telling
          the operator to set a gateway here, which is a promise the UI could not keep.
          CARDS ONLY: down a point-to-point tunnel the node ignores it, so offering it there would be a box
          that reads nothing. The placeholder carries the DETECTED value, so an empty field visibly means
          "use that one" rather than "unset". */""}
    ${isNic ? fld("exname-gw", T("Gateway"), html`<input class="mono" value=${value.gw || ""}
      spellcheck="false" autocomplete="off"
      placeholder=${gw ? T("Detected: {v1}", { v1: gw }) : "10.0.0.1"}
      onInput=${e => onChange({ gw: e.target.value })} onKeyDown=${key}/>`) : null}
    ${/* The actions go to the right, where the thing pressed last belongs — and on the CONTROLS' line, not
          the labels'. */""}
    <span class="exname-act">
      <button class="btn btn-mini" onClick=${onSubmit}>${submitLabel}</button>
      <button class="btn btn-mini ghost" onClick=${onCancel}>${T("val|Cancel")}</button>
    </span>
    ${hint ? html`<div class="hint exname-hint">${hint}</div>` : null}
  </div>`;
}

function ExitManageSheet({ node, seed, onSaved, onClose }) {
  // ── THE ROW MODEL. Four kinds, and every capability in the grid is a function of which one it is:
  //      warp/profile   the panel MADE it. Renamable and switchable here; never created or deleted here,
  //                     because it carries a licence key and a whole pasted config that belong on the WARP
  //                     screen with room to edit them. Its extra fields ride along untouched — see `_src`.
  //      found          the node reports the device. Nothing to delete: it runs whatever the panel thinks.
  //      custom         a name the operator typed that the node has never reported. The only deletable kind.
  const kindOf = (x, isCand) => (x.producer || "adopted") === "imported"
    ? (x.provider === "profile" ? "profile" : "warp")
    : (isCand ? "found" : "custom");
  const isCand = n => !!candOf(node, n);
  const [rows, setRows] = useState(() => {
    const recs = (seed || []).map(x => ({ ...x, _src: x, _kind: kindOf(x, isCand(x.device)) }));
    const taken = new Set(recs.map(x => String(x.device || "")).filter(Boolean));
    const found = (node.exit_candidates || []).filter(c => c && c.offerable && !taken.has(String(c.name)))
      .map(c => ({ id: "", label: "", device: c.name, enabled: true, killswitch: false,
                   producer: "adopted", _kind: "found", _new: true }));
    return [...recs, ...found];
  });
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [adding, setAdding] = useState(false);
  // ⚠️ THE SOURCE IS ASKED AT CREATION, NOT ONLY IN THE ROW. A device added by hand is BY DEFINITION one
  // the node has never reported, so it lands in the one state where Auto is a guess we cannot check — every
  // time. Making the operator add the row, then notice a marker three columns over, puts the question in a
  // different place from the form that created it. One record rather than three useStates, because that is
  // the shape `ExitFields` speaks and the shape the row is built from.
  const [nv, setNv] = useState({});
  const dirtyRef = useRef(false);
  const cleanRef = useRef(null);       // Sheet fills this in — call it once the server has the changes
  const anyDirty = rows.some(r => r._dt || r._dd || r._df || r._de);
  const put = (i, patch) => { dirtyRef.current = true; setRows(rs => rs.map((r, k) => (k === i ? { ...r, ...patch } : r))); };
  // ⚠️ THE PAYLOAD REPLACES `exits` WHOLESALE, so a record is rebuilt from `_src` and not from the six
  // columns this grid shows. Rebuilding a WARP row from the visible fields alone would drop its provider,
  // its licence and its stored profile — i.e. delete the account while appearing to rename it.
  // ⚠️ `r._src || r`, NEVER `r._src || {}`. `asSaved` hands the untouched rows through as PLAIN records —
  // copies of `_src` with no `_src` of their own — so falling back to `{}` spread nothing and every field
  // this grid does not show was rebuilt out of thin air: a pasted profile came back as a WARP account with
  // its private key gone. Reproduced, then fixed. This is the whitelist-rebuild trap: a record rebuilt from
  // the columns a screen HAPPENS to render loses everything it does not.
  const wire = r => ({
    ...(r._src || r), id: r.id || newExitId(), label: (r.label || "").trim(),
    producer: (r.producer || "adopted"), device: (r.device || "").trim(),
    enabled: r.enabled !== false, killswitch: !!r.killswitch,
    ...((r.producer || "adopted") === "imported"
      ? { profile_text: "" }
      : { egress_ip: String(r.egress_ip || "").trim() }),
  });
  const commit = async (payload, tag, live) => {
    setBusy(tag); setMsg("");
    // A discovered row nobody has touched is NOT a record and must not become one just because a sibling
    // was saved — that is how a list of five devices turns into five stored exits behind the operator.
    // Judged on the LIVE row (has anyone touched it?), sent from the payload (what should be written).
    const src = live || payload;
    const keep = payload.filter((r, i) => { const l = src[i] || r; return !l._new || l._dt || l._dd || l._df || l._de; });
    const r = await api.nodeUpdate({ id: node.id, exits: keep.map(wire) });
    setBusy("");
    if (!r || !r.ok) { setMsg(srvText(r) || T("Couldn't save")); return false; }
    await Store.poll();
    if (onSaved) onSaved();
    return true;
  };
  // ONE SAVE, so the grid can be read as a form: edit anything, anywhere, then commit. A per-field save had
  // to answer "does this write only this row?" — and the endpoint replaces the whole list, so making that
  // true meant sending every other row as it was SAVED rather than as it is on screen. Two controls, two
  // payload shapes and a way to get them out of step, for a question nobody asked.
  const clean = next => { dirtyRef.current = false;
    if (cleanRef.current) cleanRef.current();   // …and the sheet's OWN input-listener flag, or it guards forever
    setRows(next.map(r => ({ ...r, _dt: false, _dd: false, _df: false, _de: false,
                             ...((r._dt || r._dd || r._df || r._de) ? { _new: false, _src: wire(r) } : {}) }))); };
  const saveAll = async () => { const next = rows.map(r => ((r._dt || r._dd || r._df || r._de) ? { ...r, id: r.id || newExitId() } : r));
    setRows(next); if (await commit(next, "all", next)) clean(next); };
  const del = (i, r) => openConfirm({
    title: T("Remove this interface?"), confirmLabel: T("Remove"), danger: true,
    body: T("{v1} is a name you added, and this node has never reported a device called that — removing it takes it out of every exit list. Nothing on the box is touched.", { v1: r.label || r.device }),
    onConfirm: async () => { const next = rows.filter((_, k) => k !== i); setRows(next);
      // Deleting commits ONLY the deletion — every survivor goes as it was saved.
      await commit(next.map(r => ({ ...(r._src || r), id: r.id })), "d" + i, next); },
  });
  const addRow = () => {
    const d = String(nv.device || "").trim();
    if (!d) return;
    dirtyRef.current = true;
    setRows(rs => [...rs, { id: newExitId(), label: String(nv.title || "").trim(), device: d,
                            enabled: true, killswitch: false, producer: "adopted",
                            egress_ip: String(nv.egress_ip || "").trim(),
                            // …and the typed gateway, for the same reason `addDevice` carries it: the form
                            // asks for it, and a row built without it is refused by the server.
                            gw: String(nv.gw || "").trim(),
                            _kind: isCand(d) ? "found" : "custom", _dd: true, _added: true }]);
    setAdding(false); setNv({});
  };
  // A pasted profile is set up on the WARP screen and behaves like a WARP account everywhere the operator
  // touches it, so it is named for what it IS to them — a custom WARP — rather than for the file it came in.
  // `warp` / `profile` are NOT here: an imported row's badge comes from exitBadge(), which also knows about
  // WARP+. Duplicating them would be a second answer to the same question.
  const TYPE = { found: ["found", T("val|Discovered")], custom: ["custom", T("val|Custom")],
                 // A row the operator just typed is not a Custom exit yet — it is not an exit at all until
                 // Save. Saying so in the Type column is the honest place for it: that column answers "what
                 // is this", and the truthful answer for an unwritten row is "nothing yet".
                 unsaved: ["unsaved", T("val|Unsaved")] };
  return html`<${Sheet} title=${T("Ways out of {v1}", { v1: node.name })} width=${980}
    dirtyRef=${dirtyRef} cleanRef=${cleanRef} onClose=${onClose}
    foot=${footRow({ left: msg ? html`<span class="err">${msg}</span>` : null,
                     onCancel: onClose || closeModal, cancelLabel: T("Close"),
                     action: anyDirty ? (busy === "all" ? T("Saving…") : T("Save changes")) : null,
                     onAction: saveAll, disabled: !!busy })}>
    <p class="hint" style="margin:0 0 16px">${Trich("Every way *{v1}* can leave that isn't its own address. WARP accounts and pasted profiles are created under Settings → WARP; the devices below the line are this node's own, or names you add here.", { v1: node.name })}</p>
    <div class="exgrid g8x">
      <div class="exg-r"><div class="exg-h">${T("Title")}</div>
      <div class="exg-h">${T("Device")}</div>
      <div class="exg-h">${T("val|Type")}</div>
      <div class="exg-h">${T("Leaves as")}</div>
      <div class="exg-h">${T("Used by")}</div>
      <div class="exg-h c">${T("Kill-switch")}</div>
      <div class="exg-h c">${T("Active")}</div>
      <div class="exg-h"></div></div>
      ${rows.map((r, i) => {
        // ⚠️ THE IMPORTED KINDS GO THROUGH `exitBadge`, the same function the WARP screen uses. Keeping a
        // second lookup here is how one surface came to say "ВАРП" for an account the other showed as
        // WARP+ — the licence is on the record, so both can see it and both must say the same thing.
        // ⚠️ THE STORED TWIN, NOT THE ROW. Rows here are DRAFTS, and `nFields` strips `live`/`why_not` from
        // a draft on purpose (they are panel-owned; carrying them would dirty the section every time the
        // node reported). Health read off the draft sees no `live` and calls every WARP account "still
        // being created" — which is precisely what this grid did while the picker two clicks away had it
        // right. One lookup, used by both the badge and the health.
        const src = (node.exits || []).find(x => String(x.id) === String(r.id)) || null;
        const [cls, lbl] = (r._added && !r._src) ? TYPE.unsaved
          : (r._kind === "warp" || r._kind === "profile")
            ? exitBadge(r, (src || {}).live)
            : (TYPE[r._kind] || TYPE.custom);
        const why = (r._src || {}).why_not || "";
        const c = candOf(node, r.device);
        const off = r.enabled === false;
        return html`<div class="exg-r" key=${r.id || ("f" + r.device)}>
          <div class=${"exg-c" + (off ? " dim" : "")}>
            <input value=${r.label || ""} placeholder=${T("val|Untitled")} maxlength="40"
              onInput=${e => put(i, { label: e.target.value, _dt: true })}/></div>
          <div class=${"exg-c" + (off ? " dim" : "")}>
            ${/* HEALTH, AS A DOT ON THE DEVICE. Four states, and they are genuinely different answers:
                  the panel refuses it (red — it will never carry traffic), the node reports it up (green),
                  the node reports it down (amber — it exists but is not carrying), and the node does not
                  mention it at all (hollow — which is normal for a name typed ahead of the device, and is
                  NOT the same as "down"). Never guessed from the name; each comes from a fact we hold. */""}
            ${(() => {
              // ⚠️ FROM THE SHARED MODEL, not from a fourth reading of the same fields. This cell, the WARP
              // grid's twin, the picker's refusal and the node's egress field must agree about what
              // "waiting" means, and they only do if one function decides it. A row with no stored twin is
              // one the operator has just added and not saved — it has no state yet, and saying "waiting
              // for the node" about a record the node has never been told of would be a lie.
              if (!src) return null;
              const h = exitHealth(src, node);
              return html`<span class="exg-h8"><span class=${"exg-dot " + h.dot} title=${h.why}></span>
                ${exitHealthMark(h)}</span>`;
            })()}
            ${r._kind === "custom"
              ? html`<input class="mono" value=${r.device || ""} spellcheck="false"
                  onInput=${e => put(i, { device: e.target.value, _dd: true })}/>`
              : html`<span class="mono exg-dev">${r.device}</span>`}
            ${why ? html`<span class="exg-bad" title=${why}>${T("val|unusable")}</span>` : null}
          </div>
          <div class="exg-c"><span class=${"exg-t " + cls}
            title=${[(c || {}).address || "", (c || {}).up === false ? T("not up") : ""].filter(Boolean).join(" · ")}>${lbl}</span></div>
          ${/* ⚠️ THE SOURCE THE TRAFFIC LEAVES WITH, and the three categories answer it differently because
                they are genuinely different questions:
                  IMPORTED   the panel made the device and gave it its address — the tunnel's own inside
                             address IS what the packets carry. Nothing to choose, so it is not a control.
                  DISCOVERED the node told us the device's address, so "Auto" can be named: it resolves to
                             that, and it keeps resolving to it after a renumber.
                  HAND-ADDED we know nothing about the device, so Auto is a real unknown — MASQUERADE asks
                             the kernel, and on an UNNUMBERED device (measured in a netns) it answers with
                             the CLIENT subnet's address, so packets leave carrying 10.x, leak the internal
                             subnet upstream and are dropped there while the device still reads up. That is
                             why this row keeps a marker: Auto here is a choice, but not a safe default. */""}
          <div class="exg-c">${(r._kind === "warp" || r._kind === "profile")
            ? (() => {
                const ins = exitInsideAddr(r, ((node.exits || []).find(x => String(x.id) === String(r.id)) || {}).live);
                return ins ? html`<span class="mono faint" title=${T("The tunnel's own address — traffic leaves as this.")}>${ins}</span>`
                           : html`<span class="faint">—</span>`;
              })()
            : (() => {
                const known = candAddr(node, r.device);
                const risky = !known && !String(r.egress_ip || "").trim();
                const why = T("This node has never reported an IP address for this device. If it doesn't have one, traffic sent through it is thrown away on the way out, and nothing here will look wrong. Type the address in if you know it.");
                return html`<span class=${"exg-inw" + (risky ? " risky" : "")} title=${risky ? why : ""}>
                  <${ExitEgressPick} discovered=${known} value=${r.egress_ip || ""}
                    addrs=${cardAddrs(node, r.device)}
                    onChange=${val => put(i, { egress_ip: val, _de: true })}/>
                  ${risky ? html`<span class="exg-warn" title=${why}><${Ic} i="warn"/></span>` : null}
                </span>`;
              })()}</div>
          <div class="exg-c"><${ExitUsedBy} node=${node} id=${r.id}/></div>
          ${/* ⚠️ BOTH SWITCHES SAY WHAT THEY DO. These two are the only controls on this screen that change
                what happens to traffic and to an account, they are deliberately NOT in the editor sheet
                ("one click in the grid"), and both shipped with no explanation at all — while the latency
                number beside them carried two sentences of hover. `Active` is the switch that once destroyed
                the account it claimed to be pausing; that it now keeps it is exactly the fact an operator
                needs before flipping it. `Switch` already takes a `title`; it was simply never passed. */""}
          <div class="exg-c c"><${Switch} on=${!!r.killswitch} title=${KS_TITLE()}
            onChange=${v => put(i, { killswitch: v, _df: true })}/></div>
          <div class="exg-c c"><${Switch} on=${!off} title=${ACTIVE_TITLE()}
            onChange=${v => put(i, { enabled: v, _df: true })}/></div>
          <div class="exg-c exg-act">
            ${r._kind === "custom"
              ? html`<button class="exg-rm" title=${T("Remove")} onClick=${() => del(i, r)}><${Ic} i="trash"/></button>`
              : null}
          </div>
        </div>`;
      })}
    </div>
    ${!rows.length ? html`<p class="hint">${T("This node reports no devices that could be an exit, and nothing has been added by hand.")}</p>` : null}
    ${adding
      ? html`<${ExitFields} value=${nv} onChange=${p => setNv(x => ({ ...x, ...p }))}
          discovered=${candAddr(node, nv.device)} addrs=${cardAddrs(node, nv.device)}
          isNic=${isCardName(node, nv.device)} gw=${cardGateway(node, nv.device)} devEditable=${true}
          submitLabel=${T("val|Add")} onSubmit=${addRow} onCancel=${() => { setAdding(false); setNv({}); }}
          hint=${T("A device this node hasn't reported. Add it if you know it is there — nothing is checked until the node next syncs.")}/>`
      : html`<button class="btn btn-ghost btn-mini" style="margin-top:14px" onClick=${() => setAdding(true)}>
          <${Ic} i="plus"/> ${T("Add an interface by name")}</button>`}
  <//>`;
}

/** The stored profile, rendered back as the file it came from — with the key replaced by the sentinel the
 *  server swaps for the one it holds. The operator edits a real config, and the secret never leaves the box. */
function profileText(ex) {
  const p = ex.profile || {};
  if (!p.address) return "";
  return ["[Interface]",
          "PrivateKey = " + (Store.exitKeyKeep || "(unchanged)"),
          // ⚠️ STRIP BEFORE APPENDING. `parse_wg_profile` stores the bare address (the node's own conf
          // writer appends /32 too), but a record written by hand — or by an older panel — can carry the
          // prefix, and "10.9.0.44/32/32" is not a config anyone can save.
          "Address = " + String(p.address).split("/")[0] + "/32",
          "MTU = " + (p.mtu || 1280),
          // ⚠️ THE OBFUSCATION, or this box lies about what is stored — and then destroys it. An AmneziaWG
          // exit's parameters were kept by the parser and written by the node, and rendered back HERE as a
          // plain WireGuard config. Two consequences, the second much worse than the first: the operator
          // cannot see or edit the obfuscation, and the moment they touch this box at all the WG-only text
          // is what gets parsed on save — silently wiping every Jc/S1/H1 the exit needs to work.
          // AWG_ORDER, the SPA's one ordering, so this box and the node's conf list them the same way.
          ...AWG_ORDER.filter(k => (p.awg || {})[k] != null && String((p.awg || {})[k]).trim() !== "")
                      .map(k => k + " = " + p.awg[k]),
          "", "[Peer]",
          "PublicKey = " + (p.peer_key || ""),
          // The PSK is the profile's second secret and is shown the same way the private key is: a sentinel
          // the operator can leave alone (the stored one is kept) or overwrite (the new one is used).
          ...(p.psk ? ["PresharedKey = " + (Store.exitPskKeep || "(unchanged)")] : []),
          "AllowedIPs = 0.0.0.0/0",
          "Endpoint = " + (p.endpoint || ""),
          ...(p.keepalive ? ["PersistentKeepalive = " + p.keepalive] : [])].join("\n") + "\n";
}

/** ── EDIT ONE EXIT ──────────────────────────────────────────────────────────────────────────────────────
 *  Everything the grid deliberately does not do inline. The grid is for reading a fleet of exits at a
 *  glance; this is for changing one, with room for the two inputs that cannot live in a row — a WARP+
 *  licence key, and a whole WireGuard config edited as text. */
/** An IMPORTED exit's own inside address — the source its packets actually carry, because the panel made
 *  that device and gave it exactly one address. Two places hold it and they arrive at different times: the
 *  node reports `live.address` once the tunnel is up, and a pasted profile carries its own `Address =` from
 *  the moment it is saved. Read both, in that order, so a profile shows something before the node has ever
 *  synced and a WARP account shows what Cloudflare actually handed out rather than what we asked for. */
const exitInsideAddr = (ex, live) => String(((live || (ex || {}).live || {}).address)
  || (((ex || {}).profile || {}).address) || "").split("/")[0].trim();

const exitDefaultTitle = ex => (ex && ex.provider === "profile") ? T("Custom exit") : T("WARP exit");

/** The badge for an imported exit: [class, label]. A WARP account with a licence on it is WARP+ — the
 *  operator paid for it and the whole point of the row is knowing which ones did. Taken from the LICENCE
 *  (what was asked for) or from the account Cloudflare reports (what was granted), because those arrive at
 *  different times and either alone would make the badge flicker: the key is entered a sync before the
 *  account changes, and a restored exit has the account before the panel has re-read the key. */
// The trailing "+" is the whole point of the WARP+ badge and it was the least visible glyph in it — same
// weight, same colour, sitting low. Split on the SYMBOL rather than on a language: every translation of
// this label ends with it ("WARP+", «ВАРП+»), so the split is safe wherever it is rendered.
const badgeLabel = lbl => String(lbl).endsWith("+")
  ? html`${String(lbl).slice(0, -1)}<span class="exg-plus">+</span>`
  : lbl;
// ⚠️ A PASTED PROFILE IS COLOURED BY WHAT IT ACTUALLY IS. Both kinds wore the WARP green, so the one
// visible difference between a WireGuard exit and an AmneziaWG one — which is the difference that decides
// whether the tunnel works at all — was not on the screen anywhere. The two colours are the SAME pair the
// interface badges use (`.iftype.wg` / `.iftype.awg`), so an operator who has learned them upstairs has
// learned these. `live.awg` is the node's answer about the device it built; a draft has no `live` yet and
// falls back to the WireGuard colour, which is what every row looked like before.
const exitBadge = (ex, live) => (ex || {}).provider === "profile"
  ? [(live || {}).awg ? "exawg" : "exwg", T("val|Custom")]
  : (String((ex || {}).licence || "").trim() || /plus/.test(((live || {}).account_type) || ""))
    ? ["warp plus", badgeLabel(T("val|WARP+"))]   // i18n-keys: the first half of each pair is a CSS class, not display text
    : ["warp", T("val|WARP")];

function ExitEditSheet({ node, ex, isNew, escrowOn, goSection, onSave, onClose }) {
  const [v, setV] = useState(() => ({ ...ex, profile_text: "" }));
  const [txt, setTxt] = useState(() => profileText(ex));
  // What this sheet OPENED with, so "did anything change" is a comparison rather than a guess. Captured
  // once: `profileText(ex)` re-renders the stored profile and `ex` is refreshed by the poll underneath us.
  const [txt0] = useState(() => profileText(ex));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const dirtyRef = useRef(false);
  const isProf = v.provider === "profile";
  const set = patch => { dirtyRef.current = true; setV(x => ({ ...x, ...patch })); };
  const stored = (node.exits || []).find(x => String(x.id) === String(ex.id)) || {};
  // The three things this sheet can edit, plus the config box. A NEW exit is always dirty: there is nothing
  // to compare against and the operator has to be able to press Save.
  const dirty = isNew || txt !== txt0
    || ["label", "dial_src", "licence"].some(k => String(v[k] ?? "") !== String(ex[k] ?? ""));
  const save = async () => {
    setBusy(true); setMsg("");
    // Only send `profile_text` when it actually CHANGED. An untouched box still contains the sentinel, and
    // re-submitting it would make the server do a keep-the-key round trip for nothing.
    // A NEW profile has nothing stored to fall back on, so an empty box is refused here rather than
    // stored as an imported exit with no profile — which the node cannot bring up.
    if (isProf && isNew && !txt.trim()) { setBusy(false); return setMsg(T("Paste the profile before saving.")); }
    const body = { ...v, ...(isProf && txt !== profileText(ex) ? { profile_text: txt } : { profile_text: "" }) };
    const ok = await onSave(body);
    setBusy(false);
    if (ok !== true) return setMsg(typeof ok === "string" ? ok : T("Couldn't save"));
    (onClose || closeModal)();
  };
  // WHAT this is and WHO relies on it ride in the sheet's own header, beside the name — they are the row's
  // identity, not fields, and repeating them as a strip inside the body pushed the first real input below
  // the fold. Active and Kill-switch are NOT here either: they are one click in the grid, and a form that
  // also carries them makes an operator open a modal to flip a switch.
  return html`<${Sheet} title=${v.label || exitDefaultTitle(v)} width=${680} dirtyRef=${dirtyRef} onClose=${onClose}
    headExtra=${html`<span class="exed-hx">
      ${(() => { const [bc, bl] = exitBadge(v, ((node.exits || []).find(x => String(x.id) === String(ex.id)) || {}).live);
         return html`<span class=${"exg-t " + bc}>${bl}</span>`; })()}
      <span class="mono exed-dev">${v.device || ""}</span>
      <span class="grow"></span>
      <span class="exed-used"><${ExitUsedBy} node=${node} id=${ex.id}/></span>
    </span>`}
    foot=${footRow({ left: msg ? html`<span class="err">${msg}</span>` : null,
                     onCancel: onClose || closeModal,
                     action: busy ? T("Saving…") : T("Save changes"), onAction: save,
                     /* ⚠️ A SAVE THAT CHANGES NOTHING STILL LOOKS LIKE A SAVE, and here that is worse than it
                        sounds: the config box opens holding a RENDERING of the stored profile, so pressing
                        Save on an untouched sheet sends no `profile_text` (the sentinel is unchanged), the
                        server keeps exactly what it had, and the sheet closes as though something happened.
                        An operator who meant to change something and did not — or who pasted into the wrong
                        place — gets a success for a no-op. Same words the interface sheet already uses. */
                     disabled: busy || !dirty,
                     title: !busy && !dirty ? T("No changes to save") : "" })}>
    ${/* DECISION 7 — which of the node's own addresses dials the exit. Imported only: an adopted device
          dials on its own and there is nothing for us to pin. */""}
    <div class="row2">
      <div class="field"><label>${T("Title")}</label>
        <input value=${v.label || ""} placeholder=${exitDefaultTitle(v)} maxlength="40"
          onInput=${e => set({ label: e.target.value })}/></div>
      <div class="field"><label>${T("Connect from")}</label>
        <${NodeIpPick} ips=${node.ips || []} value=${v.dial_src || ""} onChange=${ip => set({ dial_src: ip })} auto=${T("val|Auto")}/></div>
    </div>
    ${isProf
      ? html`<div class="field"><label>${T("Configuration")}</label>
          <textarea class="exprof" rows="11" spellcheck="false" value=${txt}
            placeholder=${T("Paste the [Interface] / [Peer] profile here")}
            onInput=${e => { dirtyRef.current = true; setTxt(e.target.value); }}/>
          <div class="hint">${T("Edit it here or paste a replacement. IPv4 only — the v6 half is dropped, and routing lines are ignored because this node decides its own. The PrivateKey line is a placeholder: leave it and the stored key is kept, replace it and the new one is used.")}</div></div>`
      : html`<div class="field"><label>${T("WARP+ licence key")}</label>
          <input value=${v.licence || ""} spellcheck="false" autocomplete="off"
            placeholder=${T("WARP+ licence key — optional")}
            onInput=${e => set({ licence: e.target.value })}/>
          <div class="hint">${T("A free account is registered without one. Paste a key from the WARP mobile app to upgrade this exit to WARP+.")}</div></div>`}
    ${/* ⚠️ ONLY THE RECOVERY SURVIVES HERE. The escrow STATUS and the "turn it on" button are gone — escrow
          is on by default and lives on the Interfaces screen, so restating it per exit was noise. But
          "this node has no key for this exit, restore the escrowed one" is not status: it is the one
          action that keeps a rebuilt node's egress IP, it has no other entry point in the panel, and it
          renders only in the state it can be acted on. `ExitEscrow` returns null in every other case. */""}
    <div class="hint exstat" style="margin-top:6px">
      <${ExitEscrow} node=${node} ex=${v} stored=${stored} live=${stored.live} goSection=${goSection} escrowOn=${escrowOn}/>
    </div>
  <//>`;
}

/* The two switches every exits grid carries, worded once. Both grids render the same pair, and a second
   copy of a sentence is how the two come to say different things about one control. Functions rather than
   constants so the language switch reaches them — `T` resolves at call time. */
const KS_TITLE = () => T("On: if this exit stops working, traffic using it is refused. Off: it falls back to this node's own address.");
const ACTIVE_TITLE = () => T("Off pauses this exit — its account and keys are kept, and anything pointing at it stays pointed at it and uses the node's default meanwhile.");

export function NodeExitsForm({ node, vals, set, onBlock, goSection, escrowOn, saveExits }) {
  // ⚠️ IMPORTED ONLY, AND THE SAVE PATH STILL CARRIES EVERYTHING. This section is WARP: the accounts and
  // profiles the PANEL creates, which need a licence field and a whole config a grid row cannot hold.
  // Adopted devices are managed in the exit dropdown's grid. Every write therefore MERGES back over the
  // full list rather than replacing it, or saving a licence key here would delete every external interface
  // the operator had configured over there.
  const all = (vals || {}).exits || node.exits || [];
  const isW = x => (x.producer || "adopted") === "imported";
  const exits = all.filter(isW);
  const stored = id => (node.exits || []).find(o => String(o.id) === String(id)) || {};
  const write = xs => (saveExits ? saveExits([...xs, ...all.filter(x => !isW(x))]) : Promise.resolve(false));
  useEffect(() => { if (onBlock) onBlock(""); }, []);
  const openEdit = (ex, isNew) => openModal(html`<${ExitEditSheet} node=${node} ex=${ex} isNew=${isNew}
    escrowOn=${escrowOn} goSection=${goSection}
    onSave=${async body => {
      const next = isNew ? [...exits, { ...ex, ...body }]
                         : exits.map(x => (String(x.id) === String(ex.id) ? { ...x, ...body } : x));
      const r = await write(next);
      return r === true ? true : T("Couldn't save");
    }}/>`);
  const add = p2 => {
    const rec = { id: newExitId(), label: "", enabled: true, killswitch: false, device: "", ...p2 };
    // ⚠️ A CUSTOM CONFIG IS WRITTEN ONLY ONCE IT EXISTS. Creating the record first and opening the editor
    // afterwards left a broken exit behind whenever the operator changed their mind at the paste box: an
    // imported profile with no profile, which the node cannot bring up and the grid shows as permanently
    // unhealthy. So the sheet opens on an UNSAVED record and the save is what appends it. A WARP account
    // is the opposite — there is nothing to type, so it is written straight away and starts registering.
    if (p2.provider === "profile") return openEdit(rec, true);
    write([...exits, rec]);
  };
  const del = ex => openConfirm({
    title: T("Remove this exit?"), confirmLabel: T("Remove"), danger: true,
    body: ex.provider === "profile"
      ? T("{v1} is removed from this node and its tunnel comes down. The profile and its key are deleted from the panel — you would have to paste it again.", { v1: ex.label || ex.device })
      : T("{v1} is removed from this node and its tunnel comes down. The Cloudflare account is deleted with it: re-adding one registers a NEW account with a different exit IP.", { v1: ex.label || ex.device }),
    onConfirm: () => write(exits.filter(x => String(x.id) !== String(ex.id))),
  });
  // Health, from what the node reports about the exit it was told to create. Four states, same vocabulary
  // as the external-interfaces grid so one dot means one thing across the panel.
  const dot = ex => {
    const h = exitHealth(stored(ex.id), node);
    // ⚠️ THE DOT ALONE WAS TOO QUIET FOR A FAILURE. A 7px circle in a colour is fine for "up" and "down",
    // which are ordinary, but a registration that ERRORED or one that has never started is something the
    // operator has to act on — so those get the marker as well, in the tone the state earns, and both carry
    // the same sentence. Read from the shared model so this grid cannot drift from the picker that refuses
    // the same exit two screens away.
    return html`<span class="exg-h8"><span class=${"exg-dot " + h.dot} title=${h.why}></span>
      ${exitHealthMark(h)}</span>`; };
  return html`<div>
    ${/* §4 — the one thing this UI must never let anyone believe. An exit changes what WEBSITES see; it
          does not change what the client dials, and the client is holding this node's address in its
          config. Said here, where the operator decides, rather than nowhere. */""}
    ${/* The node's name is in the section header two lines up, and where devices live is a fact about a
          different screen. What is left is the one thing the screen has to say. */""}
    <p class="hint" style="margin:0 0 14px">${T("Cloudflare WARP accounts and WireGuard profiles from anywhere else. Websites see the exit rather than this node.")}</p>
    ${exits.length ? html`<div class="exgrid g8">
      <div class="exg-r"><div class="exg-h">${T("Title")}</div>
      <div class="exg-h">${T("Device")}</div>
      <div class="exg-h">${T("val|Type")}</div>
      <div class="exg-h">${T("Exit IP")}</div>
      <div class="exg-h c">${T("Latency")}</div>
      <div class="exg-h c">${T("Kill-switch")}</div>
      <div class="exg-h c">${T("Active")}</div>
      <div class="exg-h"></div>
      <div class="exg-h"></div></div>
      ${exits.map(ex => {
        const l = stored(ex.id).live || {};
        const off = ex.enabled === false;
        // ⚠️ THE WHOLE ROW OPENS THE EDITOR, so the cells that are CONTROLS have to stop the click from
        // reaching it — a switch that also opened a modal would be unusable.
        const stop = e => e.stopPropagation();
        return html`<div class="exg-r" key=${ex.id}>
          <div class=${"exg-c clk" + (off ? " dim" : "")} onClick=${() => openEdit(ex)}>
            ${ex.label || exitDefaultTitle(ex)}</div>
          <div class=${"exg-c clk" + (off ? " dim" : "")} onClick=${() => openEdit(ex)}>
            ${dot(ex)}<span class="mono exg-dev">${ex.device || "—"}</span></div>
          <div class="exg-c clk" onClick=${() => openEdit(ex)}>
            ${(() => { const [bc, bl] = exitBadge(ex, l); return html`<span class=${"exg-t " + bc}>${bl}</span>`; })()}</div>
          <div class="exg-c clk mono" onClick=${() => openEdit(ex)}>
            ${(l.trace || {}).ip || html`<span class="faint">—</span>`}</div>
          ${/* ⚠️ THE HOP TO THE EXIT'S OWN SERVER, not a request made through it. This first showed the time
                of a full HTTPS request to cloudflare.com via the tunnel, which for a Moscow exit one hop
                away read 179 ms — because ~169 ms of that is what a TLS handshake to Cloudflare costs from
                this node whether a tunnel is involved or not. A near-constant offset swamping the part that
                varies is not a latency column. The through-tunnel figure is still measured and lives in the
                hover, where it answers the different question it actually answers. An em dash when the node
                cannot measure it: an invented number is worse than an absent one. */""}
          <div class="exg-c c clk mono" onClick=${() => openEdit(ex)}
            title=${Number.isFinite((l.trace || {}).rtt_ms)
              ? T("Round trip from this node to the exit's own server. A request through the tunnel to a public site takes {v1} ms, which also includes however far that site is.", { v1: (l.trace || {}).rtt_ms })
              : T("Round trip from this node to the exit's own server.")}>
            ${Number.isFinite(l.ping_ms)
              ? T("{v1} ms", { v1: l.ping_ms })
              : html`<span class="faint">—</span>`}</div>
          <div class="exg-c c" onClick=${stop}><${Switch} on=${!!ex.killswitch} title=${KS_TITLE()}
            onChange=${x => write(exits.map(y => (y.id === ex.id ? { ...y, killswitch: x } : y)))}/></div>
          <div class="exg-c c" onClick=${stop}><${Switch} on=${!off} title=${ACTIVE_TITLE()}
            onChange=${x => write(exits.map(y => (y.id === ex.id ? { ...y, enabled: x } : y)))}/></div>
          <div class="exg-c exg-act" onClick=${stop}>
            <button class="exg-ed" title=${T("val|Edit")} onClick=${() => openEdit(ex)}><${Ic} i="pencil"/></button></div>
          <div class="exg-c exg-act" onClick=${stop}>
            <button class="exg-rm" title=${T("Remove")} onClick=${() => del(ex)}><${Ic} i="trash"/></button></div>
        </div>`;
      })}
    </div>`
      : html`<p class="hint" style="margin:0 0 12px">${T("No WARP exits on this node yet. Register a free Cloudflare account, or paste a WireGuard profile from somewhere else.")}</p>`}
    ${/* TWO WAYS TO GET ONE, offered as two actions rather than one button and a provider dropdown: the
          choice is what the operator is actually deciding, and "Register" has to be one click for the path
          that needs no input at all. wgcf is never named — it is plumbing. */""}
    <div class="exadd" style="margin-top:14px">
      <button class="btn btn-ghost btn-mini" onClick=${() => add({ producer: "imported", provider: "warp", licence: "" })}>
        <${Ic} i="plus"/> ${T("Register with WARP")}</button>
      <button class="btn btn-ghost btn-mini" onClick=${() => add({ producer: "imported", provider: "profile", profile_text: "" })}>
        <${Ic} i="plus"/> ${T("Paste a custom config")}</button>
    </div>
  </div>`;
}

export function NodeIngressForm({ node, vals, set }) {
  const v = vals || {};
  return html`<div>
    <p class="hint" style="margin:0 0 12px">${Trich("How peers, clients and turn-proxy links reach *{v1}*.", { v1: node.name })}</p>
    <div class="field"><label>${T("Ingress address")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— what peers and clients dial to reach this node")}</span></label>
      <${NodeIpPick} ips=${ipChoices(node)} value=${v.endpoint_host || ""} onChange=${ip => set({ endpoint_host: ip })} auto=${T("Auto (public IP)")} customPlaceholder=${T("Hostname or IP — e.g. node.example.com")}/>
      <div class="hint">${T("This is the host in every client config and turn-proxy link for this node. Prefer a hostname: moving the box then costs one DNS change, and nothing a client already holds has to be re-issued.")}</div></div>
    ${/* OTHER NAMES THIS NODE ANSWERS TO. Not a second Endpoint — a peer carries exactly one, so this
          cannot mean "use them all". It is the pool every host picker offers: a second domain, or the new
          name during a DNS move, typed once here instead of retyped from memory into the interface, the
          two turn-proxy and the WDTT/csqtt fields (and mistyped into one of them). Each is checked the
          same way a bind is — against what it actually resolves to — because a name in this list that
          lands somewhere else is the failure it exists to prevent. */ null}
    <${NodeHostList} node=${node} value=${v.endpoint_hosts || []} onChange=${hs => set({ endpoint_hosts: hs })}/>
  </div>`;
}

// Per-node mesh overrides, edited in Panel settings → System mesh (keyed by node, so it re-inits on badge switch)
export function NodeMeshForm({ node, vals, set }) {
  const rsv = (Store.panelSettings || {}).reserved || {};
  const dSub = rsv.mesh_subnet || "10.255.0.0/16", dPort = String(rsv.mesh_port_base || 9999), dPfx = rsv.iface_prefix || "swg_";
  const v = vals || {};
  return html`<div>
    <p class="hint" style="margin:0 0 12px">${Trich("Overrides for *{v1}* — blank inherits the default. Changing the subnet, prefix, or AWG re-provisions this node's links on Save (it briefly drops off the mesh while peers reconnect with the new config).", { v1: node.name })}</p>
    <div class="row2"><div class="field"><label>${T("Mesh subnet")}</label><input value=${v.mesh_subnet || ""} onInput=${e => set({ mesh_subnet: e.target.value })} placeholder=${dSub}/></div>
      <div class="field"><label>${T("Mesh port")}</label><input value=${v.mesh_port || ""} onInput=${e => set({ mesh_port: e.target.value })} placeholder=${dPort}/></div></div>
    <div class="field"><label>${T("Interface name prefix")}</label><input value=${v.mesh_prefix || ""} onInput=${e => set({ mesh_prefix: e.target.value })} placeholder=${dPfx}/></div>
    ${(() => {
      const isSet = AWG_KEYS.some(k => String((v.mesh_awg || {})[k] ?? "").trim() !== "");
      return html`<div style="margin-top:6px"><button type="button" class="advtoggle" onClick=${e => { const d = e.currentTarget.nextElementSibling; d.style.display = d.style.display === "none" ? "" : "none"; }}><span class="advcaret">▸</span> ${T("This node's mesh AWG params")}${isSet ? "" : html` <span class="faint" style="font-weight:400">${T("(auto)")}</span>`}</button>
        <div style="display:none;margin-top:8px">
          <${AwgGrid} value=${v.mesh_awg || {}} onChange=${a => set({ mesh_awg: a })}/>
          <div class="hint" style="margin:8px 0 0">${Trich("Obfuscation for the mesh links that terminate on *{v1}* — any node connecting to it adopts these and reconnects on Save. Blank = auto (a fresh set per link).", { v1: node.name })}</div>
          <div style="margin-top:12px;display:flex;gap:8px;justify-content:flex-end"><button type="button" class="btn btn-mini" onClick=${() => set({ mesh_awg: genAwg() })}><${Ic} i="refresh"/>${T("Generate a set")}</button>${isSet ? html`<button type="button" class="btn btn-mini" onClick=${() => set({ mesh_awg: {} })}>${T("Clear (auto)")}</button>` : null}</div>
        </div></div>`;
    })()}
    ${/* The rebuild these settings trigger, available on its own. Until now it fired only as a SIDE EFFECT of
          changing the subnet / prefix / AWG, gated on the value differing — so a node whose links are stuck
          with settings that are already right had no way to ask for it, short of changing the subnet and
          changing it back. Acts immediately (it is not part of the form's Save), so it confirms first, with
          the same warning the change-driven path already shows. */ ""}
    ${(Store.nodes || []).length > 1 ? html`<div class="field" style="margin-top:18px">
      <label>${T("Rebuild links")}</label>
      <div style="display:flex;gap:8px;align-items:center">
        <button type="button" class="btn btn-ghost" onClick=${() => openConfirm({
            title: T("Re-provision this node's mesh links?"), confirmLabel: T("Re-provision"), warn: true,
            body: T("{v1} will briefly drop off the mesh (and any cascade/smart traffic routed through it pauses) until every peer pulls the new config and reconnects — usually a few seconds. Other nodes' links to each other are unaffected.", { v1: node.name }),
            onConfirm: async () => { const r = await api.nodeRemesh({ id: node.id });
              toast(r && r.ok ? T("Rebuilding this node's mesh links…") : (srvText(r) || T("Couldn't re-provision the mesh links.")), r && r.ok ? "ok" : "err");
              if (r && r.ok) await Store.poll(); } })}><${Ic} i="refresh"/> ${T("Re-provision now")}</button>
      </div>
      <div class="hint">${T("Rebuilds this node's links under new interface names, with the settings above. Use it when a link won't come up — a name, address or port clashing with something else on that server. It cannot help two nodes that share one machine: their link is a single interface name that would have to exist twice there.")}</div>
    </div>` : null}
  </div>`;
}

// Per-node egress IP roles, edited in Panel settings → Nodes egress (copied from node settings). Controlled by the parent.
export function NodeEgressForm({ node, vals, set, escrowOn, goSection, openManage, saveExits }) {
  const ips = node.ips || []; const v = vals || {};
  // "Custom interface…" is a MODE of this field, not a value it can hold — picking it opens the device
  // field below and the field's answer is what gets stored. Local state, because nothing is decided until
  // a device is named and there is nothing to save in the meantime.
  // ONE FORM, THREE WAYS IN — "Custom interface…", the pencil on a device the node reported, and the pencil
  // on an external exit that already exists. All three ask the same three questions, so they get one control
  // (`ExitFields`, shared with the manage sheet) rather than several that drift apart. Null = closed.
  //   {kind:"custom"}  a device the node has NOT reported: everything open, and creating it selects it
  //   {kind:"device"}  the pencil on a reported device with no record yet: mints one, does NOT select it
  //   {kind:"exit"}    an existing record: the device name is editable only if we were the ones who invented
  //                    it, i.e. the node has never reported a device by that name
  const [form, setForm] = useState(null);
  const [armed, setArmed] = useState("");   // the exit id whose row is asking "delete?" — see exitOptionGroups
  // ⚠️ MANAGE CLOSES THE LIST; THE PENCIL DOES NOT. A sheet would open with the popup sitting on top of it,
  // so that one has to close first — and it cannot close itself, because the click is stopped so it does not
  // also choose the row and the outside-click handler ignores anything inside the popup. `Dropdown` hands
  // its close out here for it. Editing is the opposite case: it is a job done INSIDE the list (see
  // `onRename`), so the list stays and the picker is told the form belongs to it.
  const ddClose = useRef(null);
  const closeList = () => { if (ddClose.current) ddClose.current(); };
  const exitsNow = () => (vals || {}).exits || node.exits || [];
  // MINTING IS ONE FUNCTION for every way in, so "picked from the list", "typed by hand" and "titled with
  // the pencil" cannot become three different records. It is the same shape the External exits screen
  // makes, which is what earns it the same refusals, kill-switch and lowering.
  // ⚠️ EVERY EXIT WRITE FROM HERE GOES STRAIGHT TO THE SERVER. Staging them dirtied the WARP section too —
  // it stages the same `exits` field — so flipping a switch in this dropdown lit up a Save button on a
  // screen the operator had never opened, offering to save a change that was not theirs to review. The
  // manage grid already wrote directly; this was the last path that did not, and with it gone `exits`
  // leaves this section's field list entirely. `default_exit` still stages: that one IS a Network setting.
  // ⚠️ THE SELECTION LANDS ONLY IF THE SAVE DID. Setting it first was an optimistic update with no
  // rollback: a refused save left `default_exit` pointing at an id that was never written, so the picker
  // rendered BLANK — no "Default (eth0)", no selection, nothing to say what the node was doing. Observed
  // on hel-flux, 1.8.5 qualification, when a refusal was the very thing being tested. `saveExits` already
  // answers true/false; this just waits for the answer.
  const commitExits = async (xs, extra) => {
    const ok = saveExits ? await saveExits(xs) : true;
    if (ok && extra) set(extra);
    return ok;
  };
  // ⚠️ A DRAFT FOR THE TEXT, BECAUSE THIS ONE WRITES THROUGH. Every other field on this screen is staged and
  // saved by the section's Save button; an exit's are committed the moment they change, so that editing one
  // in a modal does not leave the section offering to re-save what is already saved. A text input on that
  // path would POST once per keystroke — so typing lands here and only blur / Enter / a dropdown change
  // reaches `setExitEgress`. `null` means "no draft", which is NOT the same as "" (a cleared field).
  // ⚠️ KEYED BY EXIT ID. A bare string draft belongs to whichever exit happens to be selected when it is
  // READ — type a source for one exit, switch the picker before blurring, and the half-typed text reappears
  // in the next exit's field as if it were its stored value.
  const [egDraft, setEgDraft] = useState(null);   // null | {id, val}
  // The edit form lives outside the popup but belongs to it, and the picker is told so through `keep`. Asked
  // of the DOM rather than of a ref because the form is created after the popup opens and re-created on
  // every keystroke — `closest()` has no lifecycle to get wrong.
  const setExitEgress = async (id, val) => {
    await commitExits(exitsNow().map(x => (String(x.id) === String(id)
      ? { ...x, egress_ip: String(val || "").trim() } : x)));
  };
  // ⚠️ `select` IS NOT ALWAYS TRUE, and that is the whole difference between the two callers. Creating a
  // device from "Custom interface…" is an answer to "where should traffic leave by", so the new record is
  // chosen. Putting a TITLE on a device the node already reported is not — it is bookkeeping about some
  // other row, and selecting it would silently repoint this node's default egress because the operator
  // renamed something. Same writer, one flag, because the record they produce is identical.
  // ⚠️ `gw` IS A FIELD OF THE RECORD, NOT OF THE FORM. `ExitFields` renders the typed gateway, collects it
  // and — until this — nothing carried it any further: the box accepted an address, the save built a record
  // without one, and the server refused the very card the field exists to make legal ("exit device refused:
  // nic_nogw", with the gateway sitting in the box that was meant to prevent it). A NIC reached only by
  // policy routing has no detectable gateway, which is a whole class of two-uplink boxes, so this was the
  // feature's only door and it was nailed shut. Found in the browser on hel-flux, 1.8.5 qualification.
  const addDevice = async (dev, title = "", eg = "", select = true, gw = "") => {
    const d = String(dev || "").trim();
    if (!d) return;
    const have = exitsNow().find(x => String(x.device || "") === d);
    const patch = { label: String(title || "").trim(), egress_ip: String(eg || "").trim(),
                    gw: String(gw || "").trim() };
    const next = have
      ? exitsNow().map(x => (x === have ? { ...x, ...patch } : x))
      : [...exitsNow(), { id: newExitId(), ...patch, producer: "adopted",
                          device: d, enabled: true, killswitch: false }];
    setForm(null);
    await commitExits(next, select ? { default_exit: have ? have.id : next[next.length - 1].id } : null);
  };
  // ⚠️ THE SOURCE RIDES WITH THE RENAME, so this form is not two acts wearing one button. It is still not a
  // REPOINT: `device` stays read-only for an existing exit, because changing which device an exit is is a
  // different decision and belongs where the whole record is on screen.
  // ⚠️ AND THE DEVICE, WHEN THE FORM LET THEM EDIT IT. `devEditable` is deliberately true for an exit whose
  // device the node does NOT report — "a name the operator invented is theirs to correct" — and this
  // dropped it, so that correction was offered and silently did nothing. A reported device's name is still
  // not editable, so nothing here can repoint an exit at a box's real card by accident; the field simply
  // has to mean what it looks like it means. Blank is ignored rather than written, because the callers that
  // cannot edit the device pass nothing.
  const renameExit = async (id, title, eg, gw, dev) => {
    setForm(null);
    const d = String(dev || "").trim();
    await commitExits(exitsNow().map(x => (String(x.id) === String(id)
      ? { ...x, label: String(title || "").trim(), egress_ip: String(eg || "").trim(),
          gw: String(gw || "").trim(), ...(d ? { device: d } : {}) } : x)));
  };
  const commitForm = () => {
    if (!form) return;
    if (form.kind === "exit") return renameExit(form.id, form.title, form.egress_ip, form.gw, form.device);
    // "device" is the PENCIL on a device the node reported but the panel has no record for — an edit, so it
    // mints the record and stops there. "custom" is the create, and creating is choosing.
    addDevice(form.device, form.title, form.egress_ip, form.kind === "custom", form.gw);
  };
  return html`<div>
    <p class="hint" style="margin:0 0 12px">${Trich("How *{v1}* leaves for the internet by default, and as which address. An interface that makes its own choice keeps it — these apply to the ones set to Auto, and to traffic cascaded in from other nodes.", { v1: node.name })}</p>
    ${/* DECISION 4 — the node's default WAY OUT, deliberately placed before the address it leaves AS. The
          two are one ladder read top to bottom: where, then as what. Same semantics as its neighbour and as
          every per-interface field — live, node-wide, and beaten by any interface that chose for itself. */""}
    ${/* The two halves of one sentence — WHERE it leaves, then AS WHAT — so they sit on one line and are
          read together. Wraps to stacked below ~440px rather than squashing two dropdowns into slivers. */""}
    ${/* ⚠️ ONLY "custom" TAKES THE ROW'S PLACE, and the difference is what the operator is doing. Creating a
          device is answering the question the row asks, so the row steps aside for the answer. EDITING one
          is a note about some OTHER row — the current selection is still the thing on screen and still
          relevant, so it stays and the fields appear beneath it. */""}
    <div class=${"row2 egrow" + (form && form.kind === "custom" ? " editing" : "")}>
    <div class="field"><label>${T("Default exit")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— where traffic leaves by")}</span></label>
      ${/* THE SAME GROUPED LIST THE INTERFACE AND RULE PICKERS OFFER, minus the two kinds that cannot mean
            anything here: a node's DEFAULT cannot be "forward to another node" (that is a per-interface
            decision about that interface's traffic) and it cannot be "smart cascade" (a rule list is the
            thing that HAS a default, not a default itself). Same words, same order, one builder. */""}
      ${/* One handler, three kinds of answer: an exit id (choose it), `dev:<name>` (a device the node
            reported — mint the record and choose that), or `__custom__` (a device it did NOT report — the
            operator types the name below). The record is identical in the last two cases, so a device that
            starts out typed and is reported later does not become a second thing. */""}
      ${/* ⚠️ A SECOND DOOR TO THE SAME ROOM, on purpose. "Manage…" already sits on the list's last row, but
            only someone who OPENS the list finds it — and the operator who wants to fix an exit is not
            necessarily choosing one. The gear is where every other screen puts "the fuller version of this",
            and it opens the identical sheet, so there is nothing to keep in step. */""}
      <div class="exdd-row">
      ${/* The form belongs to this list, and so does any popup opened FROM the form — portalled to the
            body, so nothing the caller holds `contains` it. "A click in some open list is not a click away
            from this list" is the whole rule, and it needs no marker on either side to say so. */""}
      <${Dropdown} value=${v.default_exit || ""} closeRef=${ddClose}
        keep=${t => !!(t && t.closest && t.closest(".exname, .ddpop"))}
        ${/* While the form is up it sits directly below this control, so the list has to open the other way
              or it covers the fields the operator opened it to edit. */""}
        drop=${form ? "up" : "auto"}
        ${/* a half-answered "delete?" must not be waiting there the next time the list is opened */""}
        onClose=${() => setArmed("")}
        onChange=${x => {
          if (x === "__custom__") return setForm({ kind: "custom", device: "", title: "", egress_ip: "" });
          setForm(null);
          if (String(x).startsWith("dev:")) return addDevice(String(x).slice(4));
          set({ default_exit: x });
        }}
        options=${[
        // NAME THE INTERFACE, not the concept. "This node's own connection" is a phrase; `Default (eth0)`
        // is the thing, and it matches the "Auto (MASQUERADE)" idiom the field below already uses. Falls
        // back to the bare word only while the node has not reported which device its default route uses.
        { value: "", label: node.wan_iface ? T("Default ({v1})", { v1: node.wan_iface }) : T("val|Default") },
        // ⚠️ THE DRAFT, NOT THE STORED RECORD. Built from `node.exits` the switch flipped the draft and the
        // row went on rendering the server's answer — it toggled, Save lit up, and nothing on screen moved.
        // A control has to show what it just did.
        ...exitOptionGroups({ ...node, exits: v.exits || node.exits || [] }, {
          // the DRAFT above supplies the labels (a rename shows before it is saved); the STORE supplies the
          // live state, which the draft does not carry — see `exitOptionGroups`.
          stored: node.exits || [],
          // this screen MANAGES exits, so it offers the devices the node reports that have no record yet —
          // choosing one mints it (see `onChange` below). A screen that only chooses does not ask for them.
          devices: true,
          // ⚠️ THE SWITCH WRITES `exits`, WHICH IS NOT ONE OF THIS SECTION'S FIELDS — until it was added to
          // SECF.mesh, flipping it edited the draft and left Save grey, so the change was silently dropped
          // on the next navigation. Same shape as the `diffList` trap: a control that changes something the
          // dirty check cannot see is worse than no control.
          // TURNING OFF THE ONE THAT IS CHOSEN MOVES THE CHOICE BACK TO DEFAULT, in the same click. Leaving
          // it selected would strand the field on a value the list refuses to let anyone pick again, which
          // is the shape of a control that has to be fought rather than used — and the node would be
          // routing out its default anyway, so the field would be showing something that is not happening.
          onToggle: (id, on) => {
            // ⚠️ A DISCOVERED DEVICE HAS NOWHERE TO REMEMBER "off". Its switch reads ON because the node
            // reports it and the panel does not refuse it; switching it off is a DECISION, and a decision
            // needs a record to live in — so one is minted, disabled, which is also what makes the row go
            // dim and stay in the list instead of springing back on the next render.
            if (String(id).startsWith("dev:")) {
              const dev = String(id).slice(4);
              if (on) return;                       // already the effective state; nothing to write
              return commitExits([...exitsNow(), { id: newExitId(), label: "", producer: "adopted",
                                                   device: dev, enabled: false, killswitch: false }]);
            }
            commitExits(exitsNow().map(x => (String(x.id) === String(id) ? { ...x, enabled: on } : x)),
                        (!on && String(v.default_exit || "") === String(id)) ? { default_exit: "" } : null);
          },
          custom: "__custom__",
          // ⚠️ NO `closeList()`. Editing a row is a job you do INSIDE the list — you want to see the row you
          // are renaming, and the one you are going to rename next. `keep` tells the picker the form belongs
          // to it, and `drop="up"` keeps the list off the fields. Choosing "Custom interface…" is the
          // opposite: that IS a selection, so the list closes itself on the way out, as any choice does.
          onRename: a => setForm({ ...a, title: a.title || "", egress_ip: a.egress_ip || "" }),
          // ⚠️ SEEDED FROM THE DRAFT, AND IT RE-BASES ON THE WAY BACK. This section stages `exits` and the
          // sheet saves them itself, so without both halves an operator who managed exits there and then
          // pressed Save here would silently restore what they had just changed — the staged copy is older
          // than the server's the moment the sheet writes.
          onManage: () => { closeList(); if (openManage) openManage(v.exits); },
          // ⚠️ ASKED IN THE ROW, NOT IN A MODAL. A dialog over an open dropdown covers the list being read
          // and takes the popup with it when dismissed, so clearing three stale entries meant reopening
          // the dropdown three times. What the modal used to explain is still true and still cheap: the
          // device keeps running, this only drops the panel's record, and a device the node still reports
          // comes straight back as a row you can pick — but it is a fact about a kind of row, so it lives
          // in the group's own hint rather than being re-read on every single delete.
          armed, onArm: setArmed,
          onRemove: a => { setArmed("");
            commitExits(exitsNow().filter(x => String(x.id) !== String(a.id)),
                        String(v.default_exit || "") === String(a.id) ? { default_exit: "" } : null); },
        })]}/>
      ${openManage ? html`<button type="button" class="btn btn-icon exdd-gear" title=${T("Manage…")}
        aria-label=${T("Manage…")} onClick=${() => openManage(v.exits)}><${Ic} i="gear"/></button>` : null}
      </div>
      ${(node.exits || []).length ? null : html`<div class="hint">${T("No exits on this node yet — add one under External exits to offer it here.")}</div>`}</div>
    ${(() => {
      // ONE QUESTION — "as which address does traffic leave" — with three category-specific answers below.
      // ⚠️ This reverses an earlier reading. The imported branch once showed `dial_src` instead, on the
      // grounds that a WARP account's inside address is 172.16.0.2 on every node and so says nothing. True,
      // but it answers a DIFFERENT question: `dial_src` is which of this node's addresses BUILDS the tunnel,
      // and the field asks what source the packets carry. For an imported exit that IS the inside address —
      // and a pasted profile's is its own (10.9.0.44); only WARP's is a constant.
      const _x = (node.exits || []).find(e => e.id === (v.default_exit || ""));
      if (!_x) {
        return html`<div class="field"><label>${T("Default egress IP")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— direct internet exit")}</span></label>
          <${NodeIpPick} ips=${ips} value=${v.default_egress_ip || ""} onChange=${ip => set({ default_egress_ip: ip })} auto=${T("Auto (MASQUERADE)")}/></div>`;
      }
      //   ADOPTED  something else on the box runs the device, so the source is a CHOICE and this is the
      //            control that makes it — Auto (named with the reported address when we have one), or a
      //            pinned value. Written through immediately; see `setExitEgress`.
      //   IMPORTED the panel made the device and gave it exactly one address, so there is nothing to
      //            choose and the field reads it back.
      if ((_x.producer || "adopted") !== "imported") {
        // ⚠️ EDITABLE HERE, not just in the manage sheet. It was read-only on the argument that a per-exit
        // value with a second control is a second place to change one thing — but the field is already on
        // screen, already labelled, and already showing the answer, so making the operator open a modal to
        // change the thing they are looking at is the worse trade. Both surfaces write the SAME record
        // through the same `commitExits`, so they cannot disagree; there is simply more than one door.
        const _known = candAddr(node, _x.device);
        const _drafted = (egDraft && String(egDraft.id) === String(_x.id)) ? egDraft.val : null;
        const _risky = !_known && !String(_drafted ?? _x.egress_ip ?? "").trim();
        return html`<div class="field"><label>${T("Default egress IP")}</label>
          <${ExitEgressPick} key=${_x.id} discovered=${_known} value=${_drafted ?? (_x.egress_ip || "")}
            addrs=${cardAddrs(node, _x.device)}
            onChange=${val => setEgDraft({ id: _x.id, val })}
            onCommit=${val => { setEgDraft(null); setExitEgress(_x.id, val); }}/>
          ${_risky ? html`<div class="hint err">${T("This node has never reported an IP address for this device. If it doesn't have one, traffic sent through it is thrown away on the way out, and nothing here will look wrong. Type the address in if you know it.")}</div>` : null}</div>`;
      }
      // ⚠️ THE FIELD ASKS ONE QUESTION — "as which address does traffic leave" — and every category answers
      // it in its own terms. For an imported exit the answer is the tunnel's OWN address: the panel made
      // that device, gave it exactly one address, and that is what the packets carry. `dial_src` answers a
      // DIFFERENT question (which of this node's addresses BUILDS the tunnel), so it is named in the hint
      // and set where it belongs, in the exit's own editor. Read-only for the reason it always was: a
      // per-exit value with a second control here is a second place to change one thing.
      const _ins = exitInsideAddr(_x);
      // ⚠️ "Set by the exit" WAS AN ANSWER TO NOTHING. It appeared in exactly one case — an imported exit
      // whose address we do not have — and that case is never a mystery: a pasted profile carries its
      // address from the moment it is saved, so the only exit without one is a WARP account the node has
      // not registered yet, or one whose registration failed. Both have a REASON, and the reason is what
      // the operator needs. So the field says "—" and the line beneath it says what is actually happening.
      const _h = exitHealth(_x, node);
      return html`<div class="field"><label>${T("Default egress IP")}</label>
        <input value=${_ins || "—"} disabled readonly
          style=${_ins ? "font-family:var(--mono)" : ""}/>
        ${/* NO LINE UNDER A KNOWN ADDRESS. The field is labelled, the value is an address, and the sentence
              explaining where it came from was three lines of prose for a fact nobody had asked about. The
              hint is kept for the case that genuinely needs one: no address, and a reason why. */""}
        ${_ins ? null
          : html`<div class=${"hint " + (_h.tone === "bad" ? "err" : "warnish")}>${_h.why}</div>`}</div>`;
    })()}
      ${form ? html`<${ExitFields} value=${form}
        onChange=${p => setForm(f => ({ ...f, ...p }))}
        discovered=${candAddr(node, form.device)} addrs=${cardAddrs(node, form.device)}
        isNic=${isCardName(node, form.device)} gw=${cardGateway(node, form.device)}
        ${/* ⚠️ A NAME WE INVENTED IS EDITABLE; A NAME THE NODE REPORTED IS NOT. The manage sheet has always
              let the operator correct a name they typed, and one screen refusing what the other allows is
              how a UI teaches people not to trust it. But a reported name is that box's own device, and
              editing it here would silently repoint the exit at something else — a different act, and one
              that belongs where the whole record is on screen. */""}
        devEditable=${form.kind === "custom" || (form.kind === "exit" && !candOf(node, form.device))}
        submitLabel=${form.kind === "custom" ? T("val|Add") : T("Save changes")}
        onSubmit=${commitForm} onCancel=${() => setForm(null)}
        ${/* Only the create case has anything to say: what KIND of device this is for, which is the one
              thing the form cannot show. The edit hint used to explain what a title is for, to someone who
              had just clicked a pencil on a row that already had one. */""}
        hint=${form.kind === "custom"
          ? T("A tunnel something else on this node runs that it hasn't reported — a proxy's TUN, a WireGuard client. It is added to this node's exits and chosen here.")
          : ""}/>` : null}
    </div>
    <div class="field"><label>${T("Panel egress connection IP")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— source to reach the panel")}</span></label>
      <${NodeIpPick} ips=${ips} value=${v.panel_ip || ""} onChange=${ip => set({ panel_ip: ip })} auto=${T("Auto (default route)")}/></div>
    <div class="field"><label>${T("Mesh egress IP")} <span class="faint" style="text-transform:none;letter-spacing:0">${T("— source to dial other nodes")}</span></label>
      <${NodeIpPick} ips=${ips} value=${v.mesh_egress_ip || ""} onChange=${ip => set({ mesh_egress_ip: ip })} auto=${T("Auto (default route)")}/>
      <div class="hint">${T("Which of this node's addresses it dials the other nodes' mesh links from. A single connection can still override it on its own card.")}</div></div>
  </div>`;
}

// Account form as a modal (opened from the header user icon).

// ═════════════════════════ MODALS / SHEETS ═════════════════════════
// Universal dialog behaviours live here so every sheet gets them for free (no per-sheet code):
//  • autofocus the first field on open
//  • Enter submits (clicks the primary button) unless you're in a textarea
//  • Esc / backdrop closes — but if any field changed, it warns before discarding
//  • Tab is trapped within the dialog
// Dirtiness is detected by snapshotting field values on open and comparing live, so it works
// regardless of which inputs a given sheet renders.
// `onClose` is the single dismiss target for EVERY exit path — ✕, Esc, overlay-click, the discard
// confirm. Openers pass the place to return to (e.g. reopen the peer view); default just closes.
// Cancel/Save buttons in a sheet's foot should call the same target so all paths land identically.






// Self-contained: setup → scan → verify → recovery codes → enabled/disable.
export function TwoFactorCard({ enabled, disabled, onChange }) {
  const [stage, setStage] = useState("idle");     // idle | setup | recovery | disabling
  const [setup, setSetup] = useState(null);        // {secret, otpauth}
  const [qr, setQr] = useState("");
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState([]);
  const [disPw, setDisPw] = useState(""); const [disCode, setDisCode] = useState("");
  const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const reset = () => { setStage("idle"); setSetup(null); setQr(""); setCode(""); setErr(""); setDisPw(""); setDisCode(""); };
  const beginSetup = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api.twofaSetup();
      if (!r || !r.ok) { setErr(srvText(r) || T("Couldn't start setup.")); setBusy(false); return; }
      setSetup(r.data); setStage("setup");
      try { setQr(await qrDataURL(r.data.otpauth, 200)); } catch (_) { setQr(""); }
    } catch (_) { setErr(T("Couldn't reach the panel.")); }
    setBusy(false);
  };
  const doEnable = async () => {
    if (busy) return; setBusy(true); setErr("");
    try {
      const r = await api.twofaEnable(code.trim());
      if (!r || !r.ok) { setErr(srvText(r) || T("That code isn't valid — try the current one.")); setBusy(false); return; }
      setRecovery((r.data && r.data.recovery) || []); setStage("recovery"); setCode(""); onChange && onChange(true);
    } catch (_) { setErr(T("Couldn't reach the panel.")); }
    setBusy(false);
  };
  const doDisable = async () => {
    if (busy) return; setBusy(true); setErr("");
    try {
      const r = await api.twofaDisable({ current_password: disPw, code: disCode.trim() });
      if (!r || !r.ok) { setErr(srvText(r) || T("Couldn't disable — check your password and code.")); setBusy(false); return; }
      reset(); onChange && onChange(false); toast(T("Two-factor authentication disabled."), "ok");
    } catch (_) { setErr(T("Couldn't reach the panel.")); }
    setBusy(false);
  };
  const copyRecovery = () => { try { navigator.clipboard.writeText(recovery.join("\n")); toast(T("Recovery codes copied."), "ok"); } catch (_) {} };

  // A SECTION of the Authentication card, not a card of its own — so the pane reads as one settings area with
  // two headings, like Access & TLS. No margin-top:0 here: this is the second section and wants the gap.
  return html`<${Fragment}>
    <div class="seclabel">${T("Two-factor authentication")}
      ${enabled && stage === "idle" ? html`<span class="grow"></span><span class="tg tg-ok">${T("state|On")}</span>` : null}</div>
    ${err ? html`<div class="formmsg err">${err}</div>` : null}
    ${!enabled && stage === "idle" ? html`
      <p class="hint" style="margin:0 0 12px">${T("Add a second step at sign-in using an authenticator app (Google Authenticator, Authy, 1Password…).")} ${disabled ? html`<b class="warntext">${T("Configure a panel login first.")}</b>` : null}</p>
      <button class="btn btn-primary" disabled=${disabled || busy} onClick=${beginSetup}>${busy ? T("Starting…") : T("Set up two-factor")}</button>
    ` : null}
    ${enabled && stage === "idle" ? html`
      <p class="hint" style="margin:0 0 12px">${T("Sign-in requires a code from your authenticator app. Keep your recovery codes somewhere safe in case you lose the device.")}</p>
      <button class="btn btn-danger" onClick=${() => { reset(); setStage("disabling"); }}>${T("Disable two-factor")}</button>
    ` : null}
    ${stage === "setup" ? html`
      <p class="hint" style="margin:0 0 12px">${T("Scan this with your authenticator app, then enter the 6-digit code it shows to confirm.")}</p>
      <div class="twofa-setup">
        ${qr ? html`<img class="twofa-qr" src=${qr} alt=${T("TOTP QR code")} width="200" height="200"/>` : html`<div class="twofa-qr empty">${T("QR unavailable")}</div>`}
        <div class="twofa-manual">
          <label>${T("Can't scan? Enter this key manually")}</label>
          <code class="twofa-secret">${setup && setup.secret}</code>
          <div class="field" style="margin-top:12px"><label>${T("Code from the app")}</label>
            <input autofocus value=${code} onInput=${e => setCode(e.target.value)} inputmode="text" autocomplete="one-time-code" placeholder="123 456"/></div>
          <div class="btnrow" style="margin-top:8px">
            <button class="btn btn-primary" disabled=${busy || code.trim().length < 6} onClick=${doEnable}>${busy ? T("Verifying…") : T("Verify & enable")}</button>
            <button class="btn btn-ghost" disabled=${busy} onClick=${reset}>${T("Cancel")}</button>
          </div>
        </div>
      </div>
    ` : null}
    ${stage === "recovery" ? html`
      <p class="hint" style="margin:0 0 12px">${Trich("*Two-factor is on.* Save these recovery codes now — each works once if you lose your authenticator. *They won't be shown again.*")}</p>
      <div class="twofa-codes">${recovery.map(c => html`<code key=${c}>${c}</code>`)}</div>
      <div class="btnrow" style="margin-top:12px">
        <button class="btn btn-ghost" onClick=${copyRecovery}><${Ic} i="copy"/>${T("Copy codes")}</button>
        <button class="btn btn-primary" onClick=${reset}>${T("Done")}</button>
      </div>
    ` : null}
    ${stage === "disabling" ? html`
      <p class="hint" style="margin:0 0 12px">${T("Confirm with your password and a current code to turn two-factor off.")}</p>
      <div class="field"><label>${T("Current password")}</label><input type="password" value=${disPw} onInput=${e => setDisPw(e.target.value)} autocomplete="current-password"/></div>
      <div class="field"><label>${T("Authentication code (or recovery code)")}</label><input value=${disCode} onInput=${e => setDisCode(e.target.value)} autocomplete="one-time-code" placeholder="123 456"/></div>
      <div class="btnrow" style="margin-top:8px">
        <button class="btn btn-danger" disabled=${busy || !disPw || !disCode.trim()} onClick=${doDisable}>${busy ? T("Disabling…") : T("Disable two-factor")}</button>
        <button class="btn btn-ghost" disabled=${busy} onClick=${reset}>${T("Cancel")}</button>
      </div>
    ` : null}
  <//>`;
}
