/* crypto.js — key material, the encryption vault, and everything a client config is made of.
 *
 * LAYER 2 (see docs/APP-JS-SPLIT-PLAN.md). Imports util / store / ui / turn-catalog.
 *
 * The custody rule this module exists to keep: peer keypairs are generated HERE, in the browser. The
 * private key goes into the config and the QR and never reaches the panel — the server only ever sees a
 * public key, an assigned IP, and (when subscriptions are on) an AES-GCM blob it cannot read. Everything
 * that could break that rule is in this one file: genKeys, the subscription vault (PBKDF2 + AES-GCM), the
 * interface-key sealed box (X25519 -> HKDF -> keystream XOR + HMAC), config assembly and the QR encoder.
 *
 * VaultPromptSheet comes with it. ensureVaultUnlocked has to raise that prompt, so leaving the sheet in a
 * screen module would mean this layer importing upward — the vault's own UI belongs to the vault.
 */

import { b64, esc, url, tkey } from "./util.js";
import { T, Tsplit, srvText } from "./i18n.js";
import { Store, api, bus } from "./store.js";
import { Ic, Sheet, Panel, toast, copy, closeModal, pushModal } from "./ui.js";
import { turnFork, turnForkList } from "./turn-catalog.js";
import { h, Fragment } from "preact";
import { useState, useEffect, useRef } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// ───────────────────────── crypto + config (in-browser; private key never leaves) ─────────────────────────
export async function genKeys() {
  const kp = await crypto.subtle.generateKey({ name: "X25519" }, true, ["deriveBits"]);
  const raw = new Uint8Array(await crypto.subtle.exportKey("raw", kp.publicKey));
  const pk8 = new Uint8Array(await crypto.subtle.exportKey("pkcs8", kp.privateKey));
  return { pub: b64(raw), priv: b64(pk8.slice(-32)) };
}
export function genPSK() { const b = new Uint8Array(32); crypto.getRandomValues(b); return b64(b); }

// ── subscription vault crypto — all client-side (AES-GCM + PBKDF2 via WebCrypto). The panel only ever
//    receives wrapped/ciphertext blobs it can't read. See swg-panel-server's subscriptions helper block. ──
export const SUB_CHECK = "swg-sub-v1";   // known plaintext → lets the browser verify it unwrapped the vault correctly
export async function subWrapKey(password, saltBytes) {   // password → AES key, via PBKDF2 (never leaves the browser)
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt: saltBytes, iterations: 200000, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}
export async function subEnc(key, bytes) {   // → base64( iv(12) ‖ ciphertext )
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, bytes));
  const out = new Uint8Array(12 + ct.length); out.set(iv); out.set(ct, 12); return b64(out);
}
export async function subDec(key, b64s) {    // base64(iv‖ct) → bytes; throws on wrong key / tamper (GCM auth)
  const all = _b64ToBytes(b64s); return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: all.slice(0, 12) }, key, all.slice(12)));
}
// Wrap the SK under a password → the request body for the vault's single keyslot.
export async function subSlotBody(password, skBytes) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const wk = await subWrapKey(password, salt);
  return { salt: b64(salt), sk_by_pw: await subEnc(wk, skBytes),
           sk_check: await subEnc(wk, new TextEncoder().encode(SUB_CHECK)) };
}
// First-time setup: mint the Subscription Key, wrap it with the password (convenience cache), store the
// wrapped form + a verifier. Returns the SK (base64) to SHOW ONCE — it is never sent to the server in the clear.
// That shown key is the ONLY way back in if the password is ever reset outside the panel (swg-passwd), so it is
// surfaced on every path that creates a vault — and stays revealable from Settings while the vault is unlocked.
export async function subVaultCreate(password) {
  const sk = crypto.getRandomValues(new Uint8Array(32));
  const skKey = await _importAes(sk, ["encrypt", "decrypt"]);
  const r = await api.subVaultSet({ ...await subSlotBody(password, sk),
    fresh: true,   // a NEW SK → the server drops the now-undecryptable escrow keypair
    // SK self-verifier (encrypted UNDER the SK) so a cached SK can be validated against THIS vault on boot —
    // a stale cache left over from a previous (reset) vault is then detected + discarded, never trusted.
    sk_verify: await subEnc(skKey, new TextEncoder().encode(SUB_CHECK)) });
  if (!r || r.ok === false) throw new Error(srvText(r) || T("couldn't save the vault"));
  _subSK = skKey;                                          // unlock immediately with the NEW SK (replaces any stale cache)
  try { sessionStorage.setItem(_SK_CACHE, b64(sk)); } catch (_) {}
  try { await ivkSetEscrow(true); } catch (_) {}          // interface-key escrow ON by default — a fresh box vaults its interface keys from first setup
  return b64(sk);
}

// Two small subscription-aware view helpers. They live with the vault because both answer a question
// only this module can: is the subscription feature on, and what is this user's subscription record.
// A user's subscription record from the cached status map: undefined=loading · null=none/feature-off · object.
export function useSubRec(userId) {
  const [rec, setRec] = useState(undefined);
  useEffect(() => { let ok = true;
    if (!subFeatureOn() || !userId) { setRec(null); return; }
    subUsersMap().then(m => { if (ok) setRec(m[userId] || null); }).catch(() => { if (ok) setRec(null); });
    return () => { ok = false; }; }, [userId, Store.configEpoch]);
  return rec;
}
// Standout reassurance for "you'll need to re-distribute the configs" warnings: interface / turn-proxy
// IP/port/endpoint changes are NOT baked into the encrypted blob (only the private key + PSK are), so every
// subscription page re-renders the corrected config on its own. Renders nothing when subscriptions are off.
export function SubAutoNote() {
  if (!subFeatureOn()) return null;
  return html`<div class="sub-auto"><${Ic} i="check"/><span><b>${T("Subscribed users need nothing")}</b>${T(" — their subscription page serves the corrected config automatically; only manually-shared QR codes / configs need re-distributing.")}</span></div>`;
}


// ── Subscription Key session cache + the token/URL/blob operations that ride on it ──
// The Subscription Key (SK) is unwrapped from the vault ONCE per session with the login password
// (the "convenience cache") and held only in memory as an AES-GCM key — never persisted, never sent
// to the server. Every per-user secret (the unlock-key, the URL token, each peer's config) is wrapped
// with it in the browser; the panel only ever stores ciphertext it can't read.
export const b64url = u => b64(u).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
export async function sha256hex(s) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, "0")).join("");
}
const _importAes = (bytes, uses) => crypto.subtle.importKey("raw", bytes, { name: "AES-GCM" }, false, uses);

// ── interface-key vault (P4): X25519 sealed-box (ECDH → HKDF → keystream-XOR + HMAC), byte-identical to
//    swg-noded's pure-stdlib implementation, so a node seal opens here and a browser seal opens on the node.
//    Lets a FULLY-WIPED node restore its interface cleanly — the panel only ever relays ciphertext. ──
const _X25519_PKCS8 = new Uint8Array([0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x6e, 0x04, 0x22, 0x04, 0x20]);
async function _ivkHkdf(ikm, salt, infoStr, len) {
  const k = await crypto.subtle.importKey("raw", ikm, "HKDF", false, ["deriveBits"]);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: "HKDF", hash: "SHA-256", salt, info: new TextEncoder().encode(infoStr) }, k, len * 8));
}
export async function ivkSeal(pubB64, plaintext) {   // seal bytes to an X25519 public key → {eph, ct, mac}
  const eph = await crypto.subtle.generateKey({ name: "X25519" }, true, ["deriveBits"]);
  const ephPub = new Uint8Array(await crypto.subtle.exportKey("raw", eph.publicKey));
  const pub = await crypto.subtle.importKey("raw", _b64ToBytes(pubB64), { name: "X25519" }, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits({ name: "X25519", public: pub }, eph.privateKey, 256));
  const ks = await _ivkHkdf(shared, ephPub, "swg-ivk-enc", plaintext.length);
  const mk = await _ivkHkdf(shared, ephPub, "swg-ivk-mac", 32);
  const ct = plaintext.map((b, i) => b ^ ks[i]);
  const mkKey = await crypto.subtle.importKey("raw", mk, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const macIn = new Uint8Array(ephPub.length + ct.length); macIn.set(ephPub); macIn.set(ct, ephPub.length);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", mkKey, macIn));
  return { eph: b64(ephPub), ct: b64(ct), mac: b64(mac) };
}
export async function ivkUnseal(privRaw, blob) {     // open a {eph, ct, mac} blob with a raw 32-byte X25519 private key
  const pkcs8 = new Uint8Array(_X25519_PKCS8.length + 32); pkcs8.set(_X25519_PKCS8); pkcs8.set(privRaw, _X25519_PKCS8.length);
  const priv = await crypto.subtle.importKey("pkcs8", pkcs8, { name: "X25519" }, false, ["deriveBits"]);
  const ephPub = _b64ToBytes(blob.eph), ct = _b64ToBytes(blob.ct), mac = _b64ToBytes(blob.mac);
  const pub = await crypto.subtle.importKey("raw", ephPub, { name: "X25519" }, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits({ name: "X25519", public: pub }, priv, 256));
  const mk = await _ivkHkdf(shared, ephPub, "swg-ivk-mac", 32);
  const mkKey = await crypto.subtle.importKey("raw", mk, { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
  const macIn = new Uint8Array(ephPub.length + ct.length); macIn.set(ephPub); macIn.set(ct, ephPub.length);
  if (!(await crypto.subtle.verify("HMAC", mkKey, mac, macIn))) throw new Error(T("vault blob failed its integrity check"));
  const ks = await _ivkHkdf(shared, ephPub, "swg-ivk-enc", ct.length);
  return ct.map((b, i) => b ^ ks[i]);
}
// Enable / disable interface-key escrow. Enabling mints the vault X25519 keypair once (private half SK-wrapped)
// so nodes seal their interface keys PROACTIVELY — the key has to be escrowed BEFORE a wipe. Disabling keeps the
// keypair + blobs (so re-enabling reuses them) and just stops the panel handing nodes the vault key.
export async function ivkSetEscrow(enabled) {
  if (!enabled) { const r = await api.post("/api/sub/ivk", { enabled: false }); if (!r || !r.ok) throw new Error(srvText(r) || T("couldn't disable escrow")); return false; }
  const sk = subSKCached(); if (!sk) throw new Error(T("Unlock the Encryption Vault first."));
  const body = { enabled: true };
  const v = await api.subVault();
  if (!(v && v.ok && v.data && v.data.ivk_pub)) {   // first enable → mint the keypair in the browser
    const kp = await crypto.subtle.generateKey({ name: "X25519" }, true, ["deriveBits"]);
    const pubRaw = new Uint8Array(await crypto.subtle.exportKey("raw", kp.publicKey));
    const pk8 = new Uint8Array(await crypto.subtle.exportKey("pkcs8", kp.privateKey));
    body.ivk_pub = b64(pubRaw); body.ivk_priv_by_sk = await subEnc(sk, pk8.slice(-32));
  }
  const r = await api.post("/api/sub/ivk", body); if (!r || !r.ok) throw new Error(srvText(r) || T("couldn't enable escrow"));
  return true;
}
export async function ivkVaultPriv() {               // the vault X25519 private key (raw 32 bytes), unwrapped under the SK
  const sk = subSKCached(); if (!sk) throw new Error(T("Unlock the vault first."));
  const v = await api.subVault();
  if (!v || !v.ok || !v.data || !v.data.ivk_priv_by_sk) throw new Error(T("No interface-key vault is set up."));
  return await subDec(sk, v.data.ivk_priv_by_sk);
}
// For a vault-sourced missing interface: unseal the escrowed key and RE-seal it to the node's transport key, so
// the panel relays only ciphertext. Returns the sealed_key for /api/iface/recreate, or null if not a vault key.
export async function ivkResealForNode(node, mi) {
  if (!mi || mi.key_source !== "vault") return null;
  if (!subSKCached()) throw new Error(T("Unlock the Encryption Vault first."));
  if (!mi.key_blob) throw new Error(T("No escrowed key is stored for this interface."));
  const tpub = ((Store.stats[node] || {}).transport_pub) || "";
  if (!tpub) throw new Error(T("The node hasn't reported its transport key yet — try again in a few seconds."));
  return await ivkSeal(tpub, await ivkUnseal(await ivkVaultPriv(), mi.key_blob));
}
// A WDTT server's escrowed identity (owner pw + wg-keys.dat) → unseal with the vault key + re-seal to the node's
// transport key, so a full-wipe restore relays only ciphertext. `keyBlob` is the node-view's wdtt_vault[iface].
export async function wdttResealForNode(node, keyBlob) {
  if (!subSKCached()) throw new Error(T("Unlock the Encryption Vault first."));
  if (!keyBlob || !keyBlob.ct) throw new Error(T("No escrowed identity is stored for this WDTT server."));
  const tpub = ((Store.stats[node] || {}).transport_pub) || "";
  if (!tpub) throw new Error(T("The node hasn't reported its transport key yet — try again in a few seconds."));
  return await ivkSeal(tpub, await ivkUnseal(await ivkVaultPriv(), keyBlob));
}

let _subSK = null;                       // the unwrapped encryption key (CryptoKey), cached for this session
const _SK_CACHE = "swg_ck";              // key-cache: sessionStorage always (tab-scoped); ALSO localStorage when the
const _SK_PERSIST = "swg_ck_keep";       // operator opts into "keep this device unlocked" (survives a browser restart).
export function subSKCached() { return _subSK; }
// Is device-persist opted in on THIS device? When on, the raw key also lives in localStorage so a cookie-only
// login (browser restart, no password typed) can restore it — the same convenience the auth cookie already gives,
// still 100% client-side (the server never receives the key; localStorage, unlike a cookie, is never transmitted).
export function subPersistOn() { try { return localStorage.getItem(_SK_PERSIST) === "1"; } catch (_) { return false; } }
export function subSetPersist(on) {
  try {
    if (on) { localStorage.setItem(_SK_PERSIST, "1"); const b = sessionStorage.getItem(_SK_CACHE); if (b) localStorage.setItem(_SK_CACHE, b); }
    else { localStorage.removeItem(_SK_PERSIST); localStorage.removeItem(_SK_CACHE); }
  } catch (_) {}
}
export function subForget() { _subSK = null; try { sessionStorage.removeItem(_SK_CACHE); localStorage.removeItem(_SK_CACHE); } catch (_) {} }   // drop the key from memory + both stores (logout / password change / lock)
// Operator-initiated lock (header padlock): drop the cached key so subscription-affecting actions prompt for it
// again — for re-locking on a shared machine, and to exercise the unlock prompt. Also turns OFF device-persist (an
// explicit lock means "stop keeping this device unlocked"), clears the heal skip-set so a later unlock re-checks
// every user, and bumps configEpoch so open QR views fall back to the unlock bar.
export function lockVault() {
  subForget();
  try { localStorage.removeItem(_SK_PERSIST); } catch (_) {}
  try { for (const k in _healTried) delete _healTried[k]; } catch (_) {}
  Store.configEpoch++; bus.emit();
  try { toast(T("Encryption Vault locked on this device."), "ok"); } catch (_) {}
}
// Restore the session convenience cache after a reload (login reloads the page). Raw key bytes live in
// sessionStorage — tab-scoped, cleared on logout, never sent to the server; the deliberate convenience-cache
// tradeoff so a normal login auto-unlocks config encryption without re-typing the password.
export async function subBootRestore() {
  if (_subSK) return;
  // localStorage first (device-persist survives a browser restart / cookie-only login), then sessionStorage (tab).
  let s = null; try { s = localStorage.getItem(_SK_CACHE) || sessionStorage.getItem(_SK_CACHE); } catch (_) {}
  if (!s) return;
  try { sessionStorage.setItem(_SK_CACHE, s); } catch (_) {}   // mirror into the tab cache so the rest of the code path is unchanged
  try {
    const key = await _importAes(_b64ToBytes(s), ["encrypt", "decrypt"]);
    const v = await api.subVault();
    if (!v || !v.ok || !v.data || !v.data.exists) { subForget(); return; }   // vault gone (reset) → the cache is stale
    if (v.data.sk_verify) {                                                    // validate the cache matches THIS vault's SK
      let ok = false;
      try { ok = new TextDecoder().decode(await subDec(key, v.data.sk_verify)) === SUB_CHECK; } catch (_) {}
      if (!ok) { subForget(); return; }                                       // stale SK (a different/reset vault) → discard, never trust
    }
    _subSK = key;
  } catch (_) { subForget(); }
}
// Unwrap the SK from the vault with the panel password → cache it.
export async function subUnlock(password) {
  const v = await api.subVault();
  if (!v || v.ok === false || !v.data || !v.data.exists) throw new Error(T("Config encryption isn't set up yet."));
  const wk = await subWrapKey(password, _b64ToBytes(v.data.salt));
  let skBytes;
  try {
    if (new TextDecoder().decode(await subDec(wk, v.data.sk_check)) !== SUB_CHECK) throw new Error("bad");
    skBytes = await subDec(wk, v.data.sk_by_pw);        // GCM auth fails here on a wrong password
  } catch (_) { throw new Error(T("That password didn't unlock the Encryption Vault.")); }
  _subSK = await _importAes(skBytes, ["encrypt", "decrypt"]);
  try { sessionStorage.setItem(_SK_CACHE, b64(skBytes)); if (subPersistOn()) localStorage.setItem(_SK_CACHE, b64(skBytes)); } catch (_) {}   // tab cache; also localStorage when device-persist is opted in
  // self-heal: give an older vault (pre-sk_verify) an SK self-verifier so a cached SK can be validated on boot.
  if (!v.data.sk_verify) {
    try { await api.subVaultSet({ salt: v.data.salt, sk_by_pw: v.data.sk_by_pw, sk_check: v.data.sk_check,
      sk_verify: await subEnc(_subSK, new TextEncoder().encode(SUB_CHECK)) }); } catch (_) {}   // the wrap is resent verbatim — the server merges, so the escrow keypair survives
  }
  try { subFlushPending(); } catch (_) {}   // save anything the operator skipped earlier this session (incl. overwriting a stale rotate blob)
  try { subAutoHeal(); } catch (_) {}   // key just became available → silently publish anything left unpublished while locked
  return _subSK;
}
// Re-wrap the vault under a NEW panel password so the convenience cache keeps auto-unlocking after a password
// change. The SK itself is unchanged, so every stored config, subscription link and escrowed key stays valid.
// Uses the raw SK from the session cache; returns false if it isn't cached (then the operator unlocks with the
// old password or their encryption key first). Best-effort.
export async function subRewrap(newPassword) {
  let skB64 = null; try { skB64 = sessionStorage.getItem(_SK_CACHE); } catch (_) {}
  if (!skB64 || !newPassword) return false;
  try {
    const v = await api.subVault(); if (!v || !v.ok || !v.data || !v.data.exists) return false;
    const r = await api.subVaultSet(await subSlotBody(newPassword, _b64ToBytes(skB64)));
    return !!(r && r.ok !== false);
  } catch (_) { return false; }
}
// The recovery path: unlock with the ENCRYPTION KEY itself (the value shown once at setup) instead of a password.
// The key IS the SK, so there's nothing to unwrap — it's validated against sk_verify, which is encrypted UNDER the
// SK, proving the pasted key belongs to THIS vault before anything trusts it. Used when the panel password was
// reset out of band (swg-passwd) and no password opens the vault any more.
export async function subUnlockWithKey(keyB64) {
  const raw = String(keyB64 || "").trim();
  let bytes; try { bytes = _b64ToBytes(raw); } catch (_) { throw new Error(T("That doesn't look like an encryption key.")); }
  if (bytes.length !== 32) throw new Error(T("That doesn't look like an encryption key."));
  const v = await api.subVault();
  if (!v || v.ok === false || !v.data || !v.data.exists) throw new Error(T("Config encryption isn't set up yet."));
  const key = await _importAes(bytes, ["encrypt", "decrypt"]);
  if (v.data.sk_verify) {   // vaults created before sk_verify existed can't be checked — accept, subAutoHeal sorts it out
    let ok = false;
    try { ok = new TextDecoder().decode(await subDec(key, v.data.sk_verify)) === SUB_CHECK; } catch (_) {}
    if (!ok) throw new Error(T("That key doesn't match this panel's Encryption Vault."));
  }
  _subSK = key;
  try { sessionStorage.setItem(_SK_CACHE, b64(bytes)); if (subPersistOn()) localStorage.setItem(_SK_CACHE, b64(bytes)); } catch (_) {}
  try { subFlushPending(); } catch (_) {}
  try { subAutoHeal(); } catch (_) {}
  return _subSK;
}
// Does this string look like an encryption key (base64 of 32 bytes) rather than a password? Used by the prompts
// that accept either, so one field can take both without making the operator pick a mode.
export function looksLikeVaultKey(s) { return /^[A-Za-z0-9+/_-]{43}=?$/.test(String(s || "").trim()); }
// The cached encryption key, base64 — for showing it to the operator. Null when the vault is locked.
export function subKeyB64() { try { return subSKCached() ? sessionStorage.getItem(_SK_CACHE) : null; } catch (_) { return null; } }

// Enable a user's subscription: mint a fresh 256-bit URL token, and REUSE the user's existing unlock-key if
// they already hold one (their encrypted-config blobs are encrypted under it — minting a fresh key would orphan
// them); only mint a fresh unlock-key for a brand-new escrow. Returns {token, unlockKeyB64} for the URL. SK unlocked.
export async function subEnableUser(uid) {
  const sk = subSKCached(); if (!sk) throw new Error(T("Unlock the Encryption Vault first."));
  const token = b64url(crypto.getRandomValues(new Uint8Array(32)));   // the URL path segment (opaque, 256-bit)
  const rec = (await subUsersMap(true))[uid];
  let unlockBytes, unlock_by_sk;
  if (rec && rec.unlock_by_sk) { unlockBytes = await subDec(sk, rec.unlock_by_sk); unlock_by_sk = rec.unlock_by_sk; }
  else { unlockBytes = crypto.getRandomValues(new Uint8Array(32)); unlock_by_sk = await subEnc(sk, unlockBytes); }
  const r = await api.subUserEnable({
    user_id: uid, token_sha: await sha256hex(token),
    unlock_by_sk,
    token_by_sk: await subEnc(sk, new TextEncoder().encode(token)),
  });
  if (!r || r.ok === false) throw new Error(srvText(r) || T("couldn't enable the subscription"));
  return { token, unlockKeyB64: b64url(unlockBytes) };
}

// If "auto-generate subscription links for new users" is on, mint the new user's link in the BACKGROUND so
// user creation stays instant. Silently defers when subscriptions are off or the encryption key isn't unlocked
// this session — the link is then created the next time the user is opened with the key unlocked.
export function subAutoGenIfEnabled(userId) {
  if (!userId || !subFeatureOn() || !subSKCached()) return;
  if (!(((Store.panelSettings || {}).subscriptions || {}).auto_generate)) return;
  (async () => { try { await subEnableUser(userId); subUsersForget(); Store.configEpoch++; bus.emit(); } catch (_) {} })();
}

// Rotate a user's URL (kill the old link): fresh token, SAME unlock-key, so existing ciphertext stays valid.
export async function subRotateUser(uid) {
  const sk = subSKCached(); if (!sk) throw new Error(T("Unlock the Subscription Key first."));
  const tokenBytes = crypto.getRandomValues(new Uint8Array(32));
  const token = b64url(tokenBytes);
  const r = await api.subUserRotate({
    user_id: uid, token_sha: await sha256hex(token),
    token_by_sk: await subEnc(sk, new TextEncoder().encode(token)),
  });
  if (!r || r.ok === false) throw new Error(srvText(r) || T("couldn't rotate the URL"));
  return { token };
}

// Recover ONLY the unlock-key (CryptoKey, encrypt+decrypt) from a user's escrow — works for a plain
// encrypted-config user (no subscription token) as well as a subscribed one. Used to encrypt/decrypt blobs.
export async function subRecoverUnlock(escRec) {
  const sk = subSKCached(); if (!sk) throw new Error(T("Unlock the Encryption Vault first."));
  if (!escRec || !escRec.unlock_by_sk) throw new Error(T("no encryption key for this user"));
  return _importAes(await subDec(sk, escRec.unlock_by_sk), ["encrypt", "decrypt"]);
}

// Recover a user's {token, unlockKey(CryptoKey), unlockKeyB64} from their escrow record via the SK.
export async function subRecover(escRec) {
  const sk = subSKCached(); if (!sk) throw new Error(T("Unlock the Subscription Key first."));
  if (!escRec || !escRec.unlock_by_sk || !escRec.token_by_sk) throw new Error(T("no subscription for this user"));
  const unlockBytes = await subDec(sk, escRec.unlock_by_sk);
  const token = new TextDecoder().decode(await subDec(sk, escRec.token_by_sk));
  // encrypt (publish a peer's secret) AND decrypt (Show-QR reads the peer's blob back) — same key material.
  return { token, unlockKey: await _importAes(unlockBytes, ["encrypt", "decrypt"]), unlockKeyB64: b64url(unlockBytes) };
}

// The shareable URL base for a user. Canonical source is Access & TLS (access.sub.url); falls back to the
// legacy subscriptions.base_url. Blank → null (operator must set it in Access & TLS). When the public URL
// carries no explicit port, we append the sub's listen port so a directly-reached sub — or one behind
// Cloudflare on an alt HTTPS port like 8443 — links to the right place. 443/80 are scheme defaults → left
// implicit; a reverse proxy that remaps the port overrides this by putting an explicit port in the URL.
// Public URLs (panel / sub) are often typed without a scheme — store them WITH https:// so every link builds
// correctly (and the port logic in subBaseUrl can parse them).
export function normPublicUrl(s) {
  s = (s || "").trim().replace(/\/+$/, "");
  if (!s) return s;
  if (!/^https?:\/\//i.test(s)) s = "https://" + s;
  // drop the scheme-default port so the field shows "host", not "host:443" — the listen port is its own field
  return s.replace(/^(https:\/\/[^/:]+):443\b/i, "$1").replace(/^(http:\/\/[^/:]+):80\b/i, "$1");
}
// The URL always carries its port. In direct TLS the URL's port and the Port field are the SAME socket, so the two
// are kept in sync (typing in one updates the other). These helpers read/write the port in a URL's authority,
// hiding the scheme-default (443/80) so the URL reads clean when it's on the standard port.
export const urlPortOf = s => { const m = /^(?:https?:\/\/)?(?:\[[^\]]+\]|[^/:]+):(\d+)/i.exec((s || "").trim()); return m ? m[1] : ""; };
export function withUrlPort(url, port) {
  let s = (url || "").trim();
  const p = parseInt(port, 10);
  s = s.replace(/^(https?:\/\/)?(\[[^\]]+\]|[^/:]+):\d+/i, "$1$2");   // drop any existing port
  if (!p || p === 443 || p === 80) return s;                          // scheme-default → keep the URL portless
  return s.replace(/^((?:https?:\/\/)?(?:\[[^\]]+\]|[^/:]+))/i, "$1:" + p);
}
// Is an apply-redirect address actually reachable from THIS browser? Probed BEFORE we navigate the whole page
// to a new panel address, so a domain that isn't wired up (DNS / Cloudflare / firewall) doesn't strand the
// operator on a dead page with no feedback. no-cors: a genuine network failure throws; any served response
// (even an error page) resolves — enough to tell "the address exists" from "it doesn't answer at all".
// Build a copy-paste nginx `location` block for a reverse-proxy front end, from a section's public URL (its path
// is the mount) and the service's internal listen host:port (the proxy upstream). 0.0.0.0 bind → dial 127.0.0.1.
// A COMPLETE nginx server block for this service, derived from what's in the form: the public URL gives the
// server_name (domain), the external listen port (a :port in the URL, else 443/80), and the mount path (the
// location); the internal host:port is the proxy upstream. So the operator sees exactly what goes where — not just
// a fragment. `upstreamHost`/`upstreamPort` are the panel's/sub's internal listen (what nginx proxies TO).
export function nginxServerBlock(publicUrl, upstreamHost, upstreamPort) {
  let scheme = "https", domain = "", extPort = 0, path = "";
  try {
    const u = new URL(/^https?:\/\//i.test(publicUrl) ? publicUrl : "https://" + (publicUrl || ""));
    scheme = (u.protocol || "https:").replace(":", "");
    domain = u.hostname || "";
    extPort = u.port ? parseInt(u.port, 10) : 0;    // an explicit :port in the public URL = nginx's external listen port
    path = (u.pathname || "").replace(/\/+$/, "");
  } catch (_) {}
  const ssl = scheme === "https";
  const listenPort = extPort || (ssl ? 443 : 80);
  const loc = (path && path !== "/") ? path + "/" : "/";
  const up = (upstreamHost && upstreamHost.trim() && upstreamHost.trim() !== "0.0.0.0") ? upstreamHost.trim() : "127.0.0.1";
  const upPort = parseInt(upstreamPort, 10) || "";
  const dom = domain || "your.domain";
  const L = [];
  L.push("server {");
  L.push("    listen " + listenPort + (ssl ? " ssl" : "") + ";");   // i18n-keys: generated nginx — file text, copied verbatim
  L.push("    listen [::]:" + listenPort + (ssl ? " ssl" : "") + ";");   // i18n-keys: generated nginx — file text, copied verbatim
  L.push("    server_name " + dom + ";");   // i18n-keys: generated nginx — file text, copied verbatim
  if (ssl) {
    L.push("");
    L.push("    ssl_certificate     /etc/ssl/" + dom + "/fullchain.pem;   # your TLS cert covering " + dom);   // i18n-keys: generated nginx — file text, copied verbatim
    L.push("    ssl_certificate_key /etc/ssl/" + dom + "/privkey.pem;");   // i18n-keys: generated nginx — file text, copied verbatim
  }
  L.push("");
  L.push("    location " + loc + " {");   // i18n-keys: generated nginx — file text, copied verbatim
  L.push("        proxy_pass http://" + up + ":" + upPort + ";   # the panel's internal listen address");   // i18n-keys: generated nginx, not UI
  L.push("        proxy_set_header Host              $http_host;");   // $http_host keeps the PORT — $host strips it, and the address-change confirm compares Host against host:port
  L.push("        proxy_set_header X-Forwarded-For   $remote_addr;");
  L.push("        proxy_set_header X-Forwarded-Proto $scheme;");
  L.push("    }");
  L.push("}");
  return L.join("\n");
}
// ── NixOS: a working configuration for the address this panel is already running ────────────────
// On a declarative host Settings → Access is read-only, so the operator's next move is in another
// file. Showing the module options alone answers "where is this set" but not "what do I write" —
// these render the two arrangements that actually work, with THIS panel's domain, path and internal
// port already in them, so the block can be pasted rather than adapted. The generated Nix is file
// text, never UI copy: it is not translated, exactly like the nginx block above.
export function nixUpstream(host) {
  const h = String(host || "").trim();
  return (h && h !== "0.0.0.0" && h !== "::") ? h : "127.0.0.1";   // a wildcard bind is dialled on loopback
}
function _nixLoc(base) {
  const b = String(base || "").replace(/\/+$/, "");
  return (b && b !== "/") ? b + "/" : "/";
}
export function nixProxyBlock(kind, hosts) {
  // ONE block for however many virtual hosts this panel needs — the panel, and the subscription page
  // when it has an address of its own. Two separate blocks would each carry `services.nginx = { … }`
  // and `security.acme.acceptTerms`, and Nix REFUSES a second definition of the same attribute: an
  // operator pasting both would get an eval error out of a screen that said "a working configuration".
  const hs = (hosts || []).filter(h => h && h.domain);
  if (!hs.length) return "";
  const L = [];
  // A host we are SUGGESTING an address for (subscriptions are on, but nothing has published the
  // page yet) carries the module option that gives it one — a vhost for a domain the panel does not
  // advertise would be a proxy to a page whose links are still empty.
  const sug = hs.filter(h => h.suggest);
  if (sug.length) {
    for (const h of sug) L.push('services.swg-panel.sub.domain = "' + h.domain + '";');   // i18n-keys: generated Nix — file text, copied verbatim
    L.push("");
  }
  if (kind === "caddy") {
    L.push("services.caddy = {");   // i18n-keys: generated Nix — file text, copied verbatim
    L.push("  enable = true;");
    for (const h of hs) {
      const loc = _nixLoc(h.base);
      L.push('  virtualHosts."' + h.domain + '".extraConfig = ' + "''");
      L.push("    reverse_proxy " + (loc === "/" ? "" : loc + "* ") + nixUpstream(h.host) + ":" + (parseInt(h.port, 10) || 8443));
      L.push("  " + "'';");
    }
    L.push("};");
  } else {
    L.push("services.nginx = {");   // i18n-keys: generated Nix — file text, copied verbatim
    L.push("  enable = true;");
    L.push("  recommendedProxySettings = true;");
    for (const h of hs) {
      L.push('  virtualHosts."' + h.domain + '" = {');
      L.push("    enableACME = true;");
      L.push("    forceSSL = true;");
      L.push('    locations."' + _nixLoc(h.base) + '".proxyPass = "http://' + nixUpstream(h.host) + ":" + (parseInt(h.port, 10) || 8443) + '";');
      L.push("  };");
    }
    L.push("};");
  }
  L.push("");
  L.push("security.acme.acceptTerms = true;");
  L.push('security.acme.defaults.email = "you@example.org";');
  L.push("networking.firewall.allowedTCPPorts = [ 80 443 ];");
  return L.join("\n");
}
export function nixDirectTlsBlock(domain, port, base) {
  const dom = String(domain || "").trim() || "panel.example.org";
  const prt = parseInt(port, 10) || 8443;
  const b = String(base || "").replace(/\/+$/, "");
  const L = [];
  L.push("services.swg-panel = {");   // i18n-keys: generated Nix — file text, copied verbatim
  L.push('  host = "0.0.0.0";');
  L.push("  port = " + prt + ";");
  L.push('  domain = "' + dom + '";');
  if (b && b !== "/") L.push('  basePath = "' + b + '";');
  L.push('  useACMEHost = "' + dom + '";');
  L.push("};");
  L.push("");
  L.push("security.acme.acceptTerms = true;");
  L.push('security.acme.certs."' + dom + '" = { email = "you@example.org"; };');
  L.push("networking.firewall.allowedTCPPorts = [ " + prt + " ];");
  return L.join("\n");
}

export function subBaseUrl() {
  const ps = Store.panelSettings || {};
  const sub = (ps.access || {}).sub || {};
  const tlsMode = ((ps.access || {}).tls || {}).mode || "";
  const behindProxy = tlsMode === "" || tlsMode === "skip";   // plain HTTP → a reverse proxy fronts swg-sub on the public port
  let raw = String(sub.url || (ps.subscriptions || {}).base_url || "").trim().replace(/\/+$/, "");
  if (!raw) return "";
  // Re-derive host:port LIVE from the settings every time (only the token is stored), so a port/host change
  // flows into every link. The public URL is often typed WITHOUT a scheme ("sub.example.net") — default it,
  // otherwise new URL() throws and the configured listen port silently never gets appended.
  if (!/^https?:\/\//i.test(raw)) raw = "https://" + raw;
  try {
    const u = new URL(raw);
    const lp = parseInt(sub.port, 10);
    // append the sub's INTERNAL listen port only when it's reached DIRECTLY — behind a reverse proxy the public
    // URL already maps the public port (and may carry a subpath like /swgsub), so appending :8444 would break it.
    if (!behindProxy && !u.port && lp && !((u.protocol === "https:" && lp === 443) || (u.protocol === "http:" && lp === 80))) u.port = String(lp);
    return (u.origin + u.pathname).replace(/\/+$/, "");
  } catch (_) { return raw.replace(/\/+$/, ""); }
}
export const SUB_LANG_LIST = [["en", "English"], ["ru", "Русский"]];   // languages the swgSub page ships (must match swg-panel-server SUB_LANGS)
export async function subUrlFor(escRec) {
  const base = subBaseUrl(); if (!base) return null;
  const { token, unlockKeyB64 } = await subRecover(escRec);
  return base + "/" + token + "#" + unlockKeyB64;
}

// Encrypt one peer's secret (private key + PSK) under the user's unlock-key and store the ciphertext.
// This is the ONLY way a peer's key reaches the subscription page — encrypted here, decrypted only by
// whoever holds the URL fragment. Best-effort: callers must not let a failure here break peer creation.
export async function subEncryptPeer(uid, pid, privkey, psk, unlockKey) {
  const sec = await subEnc(unlockKey, new TextEncoder().encode(JSON.stringify({ k: privkey, p: psk || "" })));
  const r = await api.subBlob({ user_id: uid, peer_id: pid, sec });
  if (!r || r.ok === false) throw new Error(srvText(r) || T("couldn't store the subscription config"));
}

// Is the subscriptions feature switched on for this panel?
export function subFeatureOn() { return !!(((Store.panelSettings || {}).subscriptions || {}).enabled); }
// The per-user subscription records (enabled + the SK-wrapped escrow), briefly cached.
let _subUsersCache = { at: 0, map: null };
export async function subUsersMap(force) {
  if (!force && _subUsersCache.map && Date.now() - _subUsersCache.at < 4000) return _subUsersCache.map;
  try { const r = await api.subUsers(); _subUsersCache = { at: Date.now(), map: (r && r.ok && r.data && r.data.users) || {} }; }
  catch (_) { _subUsersCache = { at: Date.now(), map: {} }; }
  return _subUsersCache.map;
}
export function subUsersForget() { _subUsersCache = { at: 0, map: null }; }
// Get a user's encryption unlock-key, minting an escrow entry (unlock-key wrapped by the SK) the first time
// they own an encrypted-stored peer. Idempotent: an existing key is returned as-is (every blob is encrypted
// under it), and the server returns the authoritative one so a race can't fork keys. null if the vault is locked.
export async function ensureUserUnlockKey(uid) {
  const sk = subSKCached(); if (!sk || !uid) return null;
  const rec = (await subUsersMap(true))[uid];
  if (rec && rec.unlock_by_sk) { try { return await subRecoverUnlock(rec); } catch (_) { return null; } }
  const unlockKeyBytes = crypto.getRandomValues(new Uint8Array(32));
  const r = await api.subEscrow({ user_id: uid, unlock_by_sk: await subEnc(sk, unlockKeyBytes) });
  if (!r || r.ok === false || !r.data || !r.data.unlock_by_sk) return null;
  subUsersForget();
  try { return await subRecoverUnlock(r.data); } catch (_) { return null; }
}
// Publish a peer's freshly-minted secret to the encrypted config store — the ONLY moment the browser holds the
// private key (create / rekey / reassign). In encrypted mode this IS the config store (and doubles as the
// subscription blob when the user is subscribed). Best-effort and silent: skips in "off" mode or while the
// vault is locked (then the peer publishes on a later rekey, or via the migration/encrypt-all pass). NEVER
// breaks peer creation.
// Reserved bucket for UNASSIGNED peers (mirrors SUB_ORPHAN on the server): their config is encrypted under a
// dedicated SK-escrowed key so it survives a reload just like an assigned peer's, and is re-keyed into the
// user's bucket on assignment.
export const SUB_ORPHAN = "_orphan";
export async function subMaybePublish(userId, peerId, privkey, psk) {
  try {
    if (Store.storeMode !== "encrypted" || !peerId || !subSKCached()) return;
    const uid = userId || SUB_ORPHAN;                      // unassigned → the orphan bucket
    const unlockKey = await ensureUserUnlockKey(uid);
    if (!unlockKey) return;
    await subEncryptPeer(uid, peerId, privkey, psk, unlockKey);
  } catch (e) {
    // Best-effort stays best-effort: the peer itself is fine and this must never break the flow. But swallowing
    // it ENTIRELY meant a rotate could report "keys changed" for every peer while the new config never reached
    // the subscription — the operator saw success, the user's page kept serving the old QR (or "Not ready yet"),
    // and nothing anywhere said otherwise. Seen for real: subs/blobs left un-writable by root-owned tooling, so
    // every publish 500'd and the only trace was a console line. Pin it to the peer's row — the same surface
    // rotatePeerKeys already uses for the failures it can name, auto-expiring like the rest.
    if (peerId) {
      Store.rowErrors["peer:" + peerId] = {
        msg: T("its config wasn't published to the subscription — {v1}", { v1: String((e && e.message) || e) }),
        at: Date.now() };
      Store.apply();
    }
  }
}
// Peers whose publish was SKIPPED while the vault was locked — peer_id → {userId, privkey, psk}. The private key
// lives ONLY in this tab (never on the server), so this is the one chance to still save it: unlocking the vault
// later in the SAME session flushes these into the vault, OVERWRITING any stale blob (the rotate case: the peer
// already has a blob with its OLD key, which a count-based heal can't spot). Cleared on reload, like every
// in-session key copy — after that the config is unrecoverable and the peer must be rekeyed.
const _pendingPublish = new Map();
export async function subFlushPending() {
  if (Store.storeMode !== "encrypted" || !subSKCached() || !_pendingPublish.size) return;
  let n = 0;
  for (const [peerId, p] of [..._pendingPublish]) {
    try { await subMaybePublish(p.userId, peerId, p.privkey, p.psk); _pendingPublish.delete(peerId); n++; } catch (_) {}
  }
  if (n) bus.emit();
}
// Peers the backfill confirmed have NO recoverable config server-side (no session key, no stored plaintext, no
// blob) — the panel never held their private key, so it can't rebuild or publish them (key custody). Re-probing
// them just re-floods the console with 404s on every heal pass / reload. Remember them keyed by PUBKEY, so a
// rekey / re-issue (which changes the pubkey) transparently re-probes. Persisted so a reload doesn't repeat the
// whole sweep — the whole point is to stop the recurring flood, not just the in-session repeat.
const _subNoConf = new Map((() => { try { return Object.entries(JSON.parse(localStorage.getItem("swg-sub-noconf") || "{}")); } catch (_) { return []; } })());
function _saveSubNoConf() { try { localStorage.setItem("swg-sub-noconf", JSON.stringify(Object.fromEntries(_subNoConf))); } catch (_) {} }
export function subNoConfSet(pid, pubkey) { if (_subNoConf.get(pid) !== pubkey) { _subNoConf.set(pid, pubkey); _saveSubNoConf(); } }
export function subNoConfClear(pid) { if (_subNoConf.delete(pid)) _saveSubNoConf(); }
export function subNoConfHas(pid, pubkey) { return !!pubkey && _subNoConf.get(pid) === pubkey; }
// Ensure the encryption vault is unlocked before an action that needs it. Resolves true when the key is
// available (already unlocked, or the operator just unlocked it) or not needed (store mode isn't encrypted);
// false when the operator chose to skip. Shows a modal (VaultPromptSheet) explaining the action + the cost of
// skipping. Never throws.
let _vaultPromptPending = null;   // the in-flight unlock promise while the modal is open — coalesces concurrent asks
export function ensureVaultUnlocked(opts) {
  if (Store.storeMode !== "encrypted") return Promise.resolve(true);   // nothing is stored encrypted → no key needed
  if (subSKCached()) return Promise.resolve(true);                     // already unlocked this session
  if (_vaultPromptPending) return _vaultPromptPending;                 // a modal is already up → share it (one prompt for a burst of actions)
  _vaultPromptPending = new Promise(function (resolve) {
    pushModal(html`<${VaultPromptSheet} opts=${opts || {}} onDone=${v => { _vaultPromptPending = null; resolve(v); }}/>`);
  });
  return _vaultPromptPending;
}
// subMaybePublish, but if the vault is locked it PROMPTS the operator (instead of silently skipping) so they can
// unlock + publish or knowingly skip. Use for user-triggered actions (create / rekey / reassign a peer).
export async function subPublishOrPrompt(userId, peerId, privkey, psk) {
  if (Store.storeMode !== "encrypted" || !peerId) return;   // userId may be null → published to the orphan bucket
  if (!subSKCached()) {
    const ok = await ensureVaultUnlocked({
      title: T("Unlock to publish this config"),
      reason: T("This peer's config is stored encrypted — only you can read it, with your encryption key. Unlock the key to publish this peer now, so its QR appears on the user's subscription page and stays re-viewable in the panel later."),
      consequence: T("the peer is created and works right away, but its config isn't published — its QR won't appear on the subscription page. You can still save it by unlocking the key in this browser tab before you reload; after a reload the key is gone from the browser (it was never on the server) and you'd have to rekey the peer to re-issue it."),
    });
    if (!ok) { _pendingPublish.set(peerId, { userId, privkey, psk }); return; }   // skipped → remember, so a later in-session unlock still saves it (incl. overwriting a stale rotate blob)
  }
  await subMaybePublish(userId, peerId, privkey, psk);
  _pendingPublish.delete(peerId);   // published → no longer pending
}
// A subscription-affecting action that DOESN'T hand us a fresh private key (e.g. assigning an EXISTING peer to a
// user, which keeps its key) can still leave that user with an unpublished peer → an empty "Not ready yet" QR on
// their subscription page. Publish the user's recoverable-but-unpublished peers, PROMPTING for the key first if
// the vault is locked (Skip leaves them unpublished, as the modal warns). Only acts for a subscribed user with a
// real gap, so it never prompts pointlessly. Best-effort; never throws.
export async function subReconcileUser(userId) {
  if (Store.storeMode !== "encrypted" || !userId) return;
  let rec; try { rec = (await subUsersMap(true))[userId]; } catch (_) { return; }
  if (!rec || !rec.enabled) return;                              // not subscribed → no client QR to keep populated
  if ((rec.peers || 0) <= (rec.provisioned || 0)) return;        // already fully published → nothing to do
  if (!subSKCached()) {
    const ok = await ensureVaultUnlocked({
      title: T("Unlock to update this subscription"),
      reason: T("This user is subscribed, and this change left a peer whose config isn't published yet. Unlock your encryption key to publish it now, so the peer's QR appears on their subscription page."),
      consequence: T("the peer works right away, but it shows “Not ready yet” (an empty QR) on the user's subscription page. Unlock the key in this browser tab before you reload and it publishes automatically; after a reload you'd have to rekey the peer to re-issue it."),
    });
    if (!ok || !subSKCached()) return;                           // operator skipped
  }
  try { const k = await ensureUserUnlockKey(userId); if (k) { await subBackfillUser(userId, k); bus.emit(); } } catch (_) {}
}
// Peers whose encrypted blob we've already ensured this session (so viewing a multi-deployment peer's QRs
// doesn't re-encrypt the same blob repeatedly).
const _blobEnsured = new Set();
// Viewing a peer's QR/config with the vault unlocked PUBLISHES its blob if it's missing — this is the real
// "open the peer once to publish it" path for a peer created while the vault was locked (its config lives in
// this session or the plaintext store, but no blob was written). Idempotent + best-effort; never throws.
export async function ensurePeerBlob(peer, conf) {
  if (Store.storeMode !== "encrypted" || !subSKCached() || !peer || !peer.id || !conf) return;   // user_id optional (orphan bucket)
  if (_blobEnsured.has(peer.id)) return;
  _blobEnsured.add(peer.id);
  try {
    const g = await api.subBlobGet(peer.id);
    if (g && g.ok && g.data && g.data.sec) return;             // already published — nothing to do
    const parsed = parseFullConf(conf);
    if (parsed && parsed.privkey) await subMaybePublish(peer.user_id, peer.id, parsed.privkey, parsed.psk);
  } catch (_) { _blobEnsured.delete(peer.id); }                // let a later open retry
}

// Publish every EXISTING peer of a user to their (just-enabled) subscription — subMaybePublish only fires
// at peer creation, so without this a user's current peers would never reach the sub page. One blob per
// peer (the private key is shared across a peer's deployments). A peer whose config isn't available
// (store_configs off, or a pre-existing/imported peer with no stored key) can't be published — counted in
// `missing` so the caller can warn instead of leaving a silently-empty page. Best-effort per peer.
export async function subBackfillUser(uid, unlockKey) {
  const peers = Store.peersOfUser(uid);
  let published = 0, missing = 0; const missingPeers = [];
  for (const p of peers) {
    if (subNoConfHas(p.id, p.pubkey)) { missing++; missingPeers.push(p.id); continue; }   // known: no recoverable config for this key → don't re-probe (kills the 404 sweep on every heal pass / reload)
    let conf = anySessionConf(p.pubkey);                          // just-created config still in this session
    // the private key is the same on every deployment, so any target that has a stored config will do — try them
    // all. Only worth probing /api/config while legacy PLAINTEXT files still await migration; in the encrypted
    // steady state (0 plaintext) it just 404s, so skip it and rely on the blob check below.
    if (!conf && Store.configsPlaintext > 0) {
      for (const t of (p.targets || [])) {
        try { const r = await api.config(p.pubkey, t.node, t.iface); if (r && r.ok && r.data && r.data.config) { conf = r.data.config; break; } } catch (_) {}
      }
    }
    const parsed = conf ? parseFullConf(conf) : null;
    if (!parsed || !parsed.privkey) {
      // no readable plaintext config — but an encrypted blob may already cover it (idempotent resume), or it may
      // still sit in the ORPHAN bucket from when this peer was unassigned → re-key that into the user's bucket.
      try {
        const g = await api.subBlobGet(p.id);
        if (g && g.ok && g.data && g.data.sec) {
          if (g.data.user_id === uid) { subNoConfClear(p.id); published++; continue; }     // already in this user's bucket
          const srcRec = (await subUsersMap())[g.data.user_id];           // the bucket it's in now (e.g. orphan)
          if (srcRec && srcRec.unlock_by_sk) {
            const srcKey = await subRecoverUnlock(srcRec);
            const secret = JSON.parse(new TextDecoder().decode(await subDec(srcKey, g.data.sec)));
            if (secret && secret.k) { await subEncryptPeer(uid, p.id, secret.k, secret.p, unlockKey); subNoConfClear(p.id); published++; continue; }
          }
        }
      } catch (_) {}
      subNoConfSet(p.id, p.pubkey);                                 // remember: no recoverable config for this key → skip next time
      missing++; missingPeers.push(p.id); continue;                 // no key available → can't encrypt / flag for rekey
    }
    try {
      await subEncryptPeer(uid, p.id, parsed.privkey, parsed.psk, unlockKey);
      await captureOverridesFrom(p, parsed);                       // move the config's non-secret DNS/MTU/AllowedIPs into the roster
      subNoConfClear(p.id); published++;
    } catch (_) { missing++; missingPeers.push(p.id); }
  }
  return { published, missing, total: peers.length, missingPeers };
}

// Silent safety net: publish every subscription-enabled user whose LIVE peers outnumber their provisioned
// blobs — i.e. peers created/assigned while the vault was locked (possibly in another admin session), which
// would otherwise show "Not ready yet" on the subscription page. Runs only with the key already available
// (no prompt — the per-action subPublishOrPrompt owns the "ask for the password" flow); best-effort, never
// throws. Guarded against re-entrancy so overlapping polls/unlocks don't double-run. Idempotent.
let _autoHealRunning = false;
const _healTried = {};   // uid → the exact blob deficit we last attempted with the key available. Peers whose key
                         // can't be recovered (no session/plaintext config, no blob — they need a rekey) can't be
                         // published, so re-probing them every heal is wasted work + console 404 noise at fleet
                         // scale. Attempt a given gap once; retry only when the deficit changes (a peer added, or
                         // one got published elsewhere). Cleared for a user the moment they're fully covered.
export async function subAutoHeal() {
  if (Store.storeMode !== "encrypted" || !subSKCached() || _autoHealRunning) return;
  _autoHealRunning = true;
  try {
    let st; try { st = await api.subUsers(); } catch (_) { return; }
    const users = (st && st.data && st.data.users) || {};
    let healed = 0;
    for (const uid of Object.keys(users)) {
      const u = users[uid] || {};
      if (!u.enabled) { delete _healTried[uid]; continue; }        // only a live subscription renders "Not ready yet"
      const deficit = (u.peers || 0) - (u.provisioned || 0);
      if (deficit <= 0) { delete _healTried[uid]; continue; }       // every live peer already has a blob → nothing to do
      if (_healTried[uid] === deficit) continue;                    // this exact gap was already attempted → don't re-probe
      _healTried[uid] = deficit;
      try {
        const k = await ensureUserUnlockKey(uid);
        if (k) { const r = await subBackfillUser(uid, k); healed += (r.published || 0); if (r.published) delete _healTried[uid]; }
        else delete _healTried[uid];                                // couldn't get the key → let a later pass retry
      } catch (_) { delete _healTried[uid]; }
    }
    if (healed) bus.emit();   // refresh any open sub / QR views now that blobs exist
  } finally { _autoHealRunning = false; }
}

// Migrating a plaintext config → blob keeps ONLY {k,p}; its non-secret DNS/MTU/AllowedIPs/keepalive would be
// lost, so capture them into the roster (once — never clobber an existing override). Sparse vs the interface default.
export async function captureOverridesFrom(peer, parsed) {
  if (peer.overrides && Object.keys(peer.overrides).length) return;   // already has roster overrides
  const t0 = (peer.targets || [])[0]; if (!t0) return;
  const ov = configOverrides({ dns: (parsed.dns || []).join(", "), mtu: parsed.mtu, allowed: parsed.allowed, keepalive: parsed.keepalive },
                             Store.ifaceMeta(t0.node, t0.iface));
  if (Object.keys(ov).length) { try { await api.peerUpdate({ peer_id: peer.id, overrides: ov }); } catch (_) {} }
}

// The one-time migration pass. Touches ONLY the peers the server says still hold plaintext (O(plaintext), so a
// 1000-peer fleet isn't a full-fleet probe): encrypt each ASSIGNED one's config into its blob, capture non-secret
// overrides, then purge plaintext ONLY where a blob now exists (server re-checks) + clean orphan .conf files
// (dead keys, no live peer). Resumable — re-running does only the stragglers. `flagged` = peers that couldn't be
// encrypted (unassigned, or no stored/importable key) → the rekey affordance. Requires the vault unlocked.
export async function runConfigMigration() {
  if (!subSKCached()) throw new Error(T("Unlock the Encryption Vault first."));
  let list = [];
  try { const pp = await api.plaintextPeers(); list = (pp && pp.data && pp.data.peers) || []; } catch (_) {}
  let migrated = 0; const flagged = [];
  // group the assigned plaintext-holders by user (one unlock-key each); unassigned can't be encrypted → flag.
  const byUser = {};
  for (const it of list) {
    const p = (Store.recon.peers || []).find(x => x.id === it.peer_id);
    if (!p) continue;
    if (!p.user_id) { flagged.push(p.id); continue; }
    (byUser[p.user_id] = byUser[p.user_id] || []).push(p);
  }
  for (const uid of Object.keys(byUser)) {
    const unlockKey = await ensureUserUnlockKey(uid);
    if (!unlockKey) { byUser[uid].forEach(p => flagged.push(p.id)); continue; }
    for (const p of byUser[uid]) {
      let conf = anySessionConf(p.pubkey);
      if (!conf) for (const t of (p.targets || [])) {
        try { const r = await api.config(p.pubkey, t.node, t.iface); if (r && r.ok && r.data && r.data.config) { conf = r.data.config; break; } } catch (_) {}
      }
      const parsed = conf ? parseFullConf(conf) : null;
      if (!parsed || !parsed.privkey) { flagged.push(p.id); continue; }
      try { await subEncryptPeer(uid, p.id, parsed.privkey, parsed.psk, unlockKey); await captureOverridesFrom(p, parsed); migrated++; }
      catch (_) { flagged.push(p.id); }
    }
  }
  const pr = await api.purgePlaintext({ purge_orphans: true });    // blob-gated purge + orphan cleanup (dead keys)
  await Store.poll();                                              // refresh the plaintext count
  return { migrated, total: list.length, flagged: [...new Set(flagged)],
           purged: (pr && pr.data && pr.data.purged) || 0, orphansPurged: (pr && pr.data && pr.data.orphans_purged) || 0,
           remaining: (pr && pr.data && pr.data.remaining) || 0 };
}

export const AWG_ORDER = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4", "I1", "I2", "I3", "I4", "I5"];
// IPv6 leak-guard: a FULL v4 tunnel (AllowedIPs contains 0.0.0.0/0) MUST also capture v6 (::/0), else the client's
// IPv6 traffic escapes the tunnel over its real IP (the tunnels are v4-only, so captured v6 is dropped node-side and
// apps fall back to v4 — no leak). Append ::/0 when it's missing. Split-tunnel (specific v4 CIDRs, no 0.0.0.0/0) is
// left untouched — routing only some v4 is an explicit choice and v6 staying local is expected there.
export function guardAllowed(a) {
  const parts = ((a || "").trim() || "0.0.0.0/0, ::/0").split(",").map(s => s.trim()).filter(Boolean);
  if (parts.includes("0.0.0.0/0") && !parts.some(p => p.includes(":"))) parts.push("::/0");
  return parts.join(", ");
}
/* Builds a WireGuard .conf. Every line here is FILE TEXT the client parses — not one byte of it is UI,
   so nothing in this function is translated.   // i18n-keys */
export function buildConf(o) {
  const L = ["[Interface]", "PrivateKey = " + o.privkey, "Address = " + o.address];   // i18n-keys: generated WireGuard .conf — file text
  if (o.dns && o.dns.length) L.push("DNS = " + o.dns.join(", "));   // i18n-keys: generated WireGuard .conf — file text
  L.push("MTU = " + (o.mtu || 1280));   // i18n-keys: generated WireGuard .conf — file text
  for (const k of AWG_ORDER) if (o.awg_params && o.awg_params[k] != null) L.push(k + " = " + o.awg_params[k]);
  L.push("", "[Peer]", "PublicKey = " + o.server_pubkey);   // i18n-keys: generated WireGuard .conf — file text
  if (o.psk) L.push("PresharedKey = " + o.psk);   // i18n-keys: generated WireGuard .conf — file text
  L.push("AllowedIPs = " + guardAllowed(o.allowed), "Endpoint = " + o.endpoint,   // i18n-keys: generated WireGuard .conf — file text
    "PersistentKeepalive = " + (o.keepalive != null && o.keepalive !== "" ? o.keepalive : 25));   // i18n-keys: generated WireGuard .conf — file text
  return L.join("\n") + "\n";
}
// Full parse of a client config back into buildConf()'s shape — so an edit/copy can
// rebuild the config from the existing one (the only place the private key lives).
export function parseFullConf(text) {
  const m = re => (text.match(re) || [])[1];
  const dnsLine = m(/DNS\s*=\s*(.+)/);
  const awg = {};
  for (const k of AWG_ORDER) { const v = m(new RegExp("^" + k + "\\s*=\\s*(\\S+)", "m")); if (v != null) awg[k] = v; }
  return {
    privkey: m(/PrivateKey\s*=\s*(\S+)/) || "",
    address: m(/Address\s*=\s*(.+)/) || "",
    dns: dnsLine ? dnsLine.split(",").map(s => s.trim()).filter(Boolean) : [],
    mtu: m(/MTU\s*=\s*(\d+)/) || 1280,
    awg_params: awg,
    server_pubkey: m(/PublicKey\s*=\s*(\S+)/) || "",
    psk: m(/PresharedKey\s*=\s*(\S+)/) || "",
    allowed: m(/AllowedIPs\s*=\s*(.+)/) || "0.0.0.0/0, ::/0",
    endpoint: m(/Endpoint\s*=\s*(\S+)/) || "",
    keepalive: m(/PersistentKeepalive\s*=\s*(\d+)/) || 25,
  };
}
// Same config, Endpoint swapped to the turn-proxy's public listen address (import via turn-proxy).

// Sparse per-peer NON-secret overrides for the roster: only the fields the operator set to something
// OTHER than the interface's live default (so a peer left on defaults stores nothing and keeps tracking
// fleet-wide changes). `opts` = {dns (string), mtu, allowed, keepalive}; `meta` = the (first) target's
// interface meta. Mirrors the server's clean_overrides / effective_client_params so panel + sub + roster
// agree. dns=[] is kept as an explicit "no DNS line" when the interface default is non-empty.
export function configOverrides(opts, meta) {
  const ov = {}; meta = meta || {};
  const dnsArr = String(opts.dns || "").split(",").map(s => s.trim()).filter(Boolean);
  const defDns = (meta.dns || []).map(String);
  if (JSON.stringify(dnsArr) !== JSON.stringify(defDns)) ov.dns = dnsArr;
  const mtu = String(opts.mtu || "").trim();
  if (mtu && mtu !== String(meta.mtu || 1280)) ov.mtu = +mtu;
  const allowed = String(opts.allowed || "").trim();
  if (allowed && guardAllowed(allowed) !== "0.0.0.0/0, ::/0") ov.allowed = allowed;
  const ka = String(opts.keepalive || "").trim();
  if (ka !== "" && ka !== "25") ov.keepalive = +ka;
  return ov;
}

export function downloadConf(text, base, ext) {
  // octet-stream (not text/plain) so the browser keeps the chosen name instead of appending .txt
  ext = String(ext || "conf").replace(/^\./, "");
  const blob = new Blob([text], { type: "application/octet-stream" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = base.replace(/[^\w.-]+/g, "_").replace(/\.(conf|txt)$/i, "") + "." + ext; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// Turn-proxy client-artifact encoders live in the shared turn-artifacts.js (window.SWGTurn) so the
// admin app and the subscription page build byte-identical configs from ONE source. _b64ToBytes stays
// here (used beyond turn, e.g. subDec).
function _b64ToBytes(b64) { try { const s = atob(String(b64 || "").trim()); const a = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a; } catch (_) { return new Uint8Array(0); } }

// Client-import artifact for a peer behind a turn-proxy — the per-fork wire formats live in the shared
// turn-artifacts.js (window.SWGTurn), loaded by both the admin app and the subscription page.
export function turnArtifact(baseConf, tp, vkLink, vkLinks, asClient, os) {
  const fork = turnFork(tp.service);
  // Every client (the server's own OR a cross-fork one) gets the admin's saved values for THIS (server, client, OS); the encoder
  // fills anything unset with the app's own default. `os` omitted → the client's primary platform (config-gen has
  // no device context yet; the sub page can pass the visitor's OS later).
  const native = (typeof SWGTurn.nativeEncoder === "function") ? SWGTurn.nativeEncoder(fork) : null;
  const cs = turnClientSettingsFor(fork, asClient || native, os);
  return SWGTurn.artifact(baseConf, tp, vkLink, cs, vkLinks, asClient);
}
// The client apps a server offers (from the catalog `clients` list) → {id, encoder, name, cross}. The server's
// OWN app sorts first; a cross-fork app (shared-ancestor wire, another fork's client) follows it.
export function turnClientsFor(fork) {
  const cmap = (Store.turnCatalog && Store.turnCatalog.clients) || {};
  const ids = ((turnForkList().find(x => x.id === fork) || {}).clients) || [];
  const native = (typeof SWGTurn.nativeEncoder === "function") ? SWGTurn.nativeEncoder(fork) : null;
  const PL = { android: "Android", ios: "iOS", windows: "Windows", linux: "Linux", macos: "macOS" };
  const out = ids.map(id => {
    const c = cmap[id] || {}; const plat = Object.keys(c.platforms || {})[0];
    return { id, encoder: c.encoder || id, name: c.name || id, plat: plat ? (PL[plat] || plat) : "", cross: (c.encoder || id) !== native };
  });
  return out.sort((a, b) => (a.cross ? 1 : 0) - (b.cross ? 1 : 0));
}
// A FUNCTION: a module-level T() is evaluated at import, before loadLang() resolves, and would freeze
// this warning in English for the life of the page (same rule as ui.js's label tables).
// the catalog client id whose encoder matches (clients map their own encoder; id==encoder for most)
function _clientIdForEncoder(encoder) {
  const cmap = (Store.turnCatalog && Store.turnCatalog.clients) || {};
  for (const cid in cmap) if ((cmap[cid].encoder || cid) === encoder) return cid;
  return encoder;
}
// merged client-app settings for (server, client, OS): the client's own schema defaults overlaid by the admin's
// saved values at panel_settings.turn_client_settings[fork][clientId][os]. `os` omitted → the client's primary
// platform. Fed into the config/QR/link encoder (the SETTINGS SPLIT). The SCHEMA is per-client (unchanged); this
// just selects WHICH saved value-set to apply.
export function turnClientSettingsFor(fork, encoder, os) {
  const cmap = (Store.turnCatalog && Store.turnCatalog.clients) || {};
  const cid = _clientIdForEncoder(encoder);
  const c = cmap[cid] || {};
  const srv = ((Store.turnCatalog || {}).servers || []).find(s => s.id === fork);   // the mysorez app's knobs depend on the fork's core → prefer the per-(fork,client) schema
  const schema = (srv && srv.client_schemas && srv.client_schemas[cid]) || c.settings || [];
  const useOs = os || Object.keys(c.platforms || {})[0] || "";
  const saved = (((((Store.panelSettings && Store.panelSettings.turn_client_settings) || {})[fork]) || {})[cid] || {})[useOs] || {};
  const out = {};
  for (const d of schema) { const v = saved[d.key]; out[d.key] = (v === undefined || v === null) ? d.default : v; }
  return out;
}

// ───────────────────────── QR ─────────────────────────
export function qrDataURL(text, targetPx) {
  const q = qrcode(0, "L");
  q.addData(text); q.make();
  const n = q.getModuleCount(), quiet = 4, total = n + quiet * 2;
  const cell = Math.max(3, Math.floor((targetPx || 360) / total));
  const size = total * cell;
  const c = document.createElement("canvas"); c.width = c.height = size;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, size, size);
  ctx.fillStyle = "#000";
  for (let r = 0; r < n; r++)
    for (let col = 0; col < n; col++)
      if (q.isDark(r, col)) ctx.fillRect((col + quiet) * cell, (r + quiet) * cell, cell, cell);
  return c.toDataURL("image/png");
}
/* "set one up in <a>Settings → …</a>" — the placeholder is a LINK, so the sentence cannot be one text node.
   Translated whole and split on its own marker, so each language keeps its word order around the link. */
function vaultMissing(onNav) {
  const [before, after] = Tsplit("No Encryption Vault is set up yet — set one up in {where}, then try again.", "where");
  return html`<${Fragment}>${before}<a href="#/panel/settings" onClick=${onNav}>${T("Settings → Client configs → Encryption")}</a>${after}<//>`;
}

export function QR({ conf, label, px }) {
  let src = null;
  try { src = qrDataURL(conf, px || 360); } catch (_) { src = null; }
  if (!src) return html`<div class="qr-fail">${T("config too large")}<br>${T("to encode as QR")}</div>`;
  return html`<div class="qr" title=${T("Tap to enlarge for scanning")} onClick=${() => qrZoom(conf, label)}>
    <img class="qrimg" alt=${T("config QR")} src=${src}/></div>`;
}
export let qrZoomEl = null;   // the open QR enlargement, if any — Esc collapses it (instead of closing the modal)
export function qrZoom(conf, label) {
  if (qrZoomEl) { try { qrZoomEl.remove(); } catch (_) {} qrZoomEl = null; }
  let img;
  try { img = `<img class="qrimg" alt="${esc(T("config QR"))}" src="${qrDataURL(conf, 920)}">`; }
  catch (e) { img = `<div class="qr-fail">${esc(T("config too large to encode"))}</div>`; }
  const ov = document.createElement("div");
  ov.className = "qr-overlay";
  ov.innerHTML = `<div class="qr-overlay-inner"><div class="qr-overlay-card">${img}</div>` +
    `<div class="qr-overlay-cap">${label || esc(T("Scan in WireGuard / AmneziaWG"))}</div></div>`;
  const onKey = e => { if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); close(); } };
  function close() { try { ov.remove(); } catch (_) {} if (qrZoomEl === ov) qrZoomEl = null; document.removeEventListener("keydown", onKey, true); }
  ov.onclick = close;
  document.addEventListener("keydown", onKey, true);
  qrZoomEl = ov;
  document.body.appendChild(ov);
}
export function dataUrlToBlob(url) {
  const comma = url.indexOf(","), meta = url.slice(0, comma), b64 = url.slice(comma + 1);
  const mime = (meta.match(/:(.*?);/) || [])[1] || "image/png";
  const bin = atob(b64), arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return new Blob([arr], { type: mime });
}
// Copy the QR *image* (a PNG) to the clipboard — used when the QR is what's on screen, so Copy acts on
// what you see rather than the hidden config text. Mirrors sub.js copyImage.
export function copyQrImage(text, what) {
  let url; try { url = qrDataURL(text, 640); } catch (_) { toast(T("QR too large to copy as an image."), "err", 2200); return; }
  if (!window.ClipboardItem || !navigator.clipboard || !navigator.clipboard.write) { toast(T("This browser can't copy an image."), "err", 2200); return; }
  try {
    const blob = dataUrlToBlob(url), item = {}; item[blob.type] = blob;
    navigator.clipboard.write([new ClipboardItem(item)]).then(() => toast(T("{what} copied.", { what: what || "QR" }), "ok", 1500), () => toast(T("Copy failed."), "err", 2200));
  } catch (_) { toast(T("Copy failed."), "err", 2200); }
}

// resolve a per-target client config: session (built at creation) → stored → none
// Resolve a peer's config and RE-RENDER it on the fly: client-side fields (private key, address,
// DNS, MTU, AllowedIPs, keepalive, PSK) come from the stored/session source, but the server-facing
// fields (Endpoint, server PublicKey, AmneziaWG params) are rebuilt from the CURRENT interface
// metadata — so an interface endpoint change shows up in every config/QR without a re-issue.
export function rerenderConf(text, node, iface) {
  if (!text) return text;
  const meta = Store.ifaceMeta(node, iface);
  if (!meta) return text;
  // surgical in-place updates: swap the Endpoint line and refresh any existing AmneziaWG param
  // lines to the interface's current values — never rebuild the rest, so it can't be malformed.
  let out = text;
  if (meta.endpoint) out = out.replace(/^([ \t]*Endpoint[ \t]*=).*$/m, (m, p1) => p1 + " " + meta.endpoint);
  const awg = meta.awg_params || {};
  for (const k of AWG_ORDER) {
    if (awg[k] == null) continue;
    const re = new RegExp("^([ \\t]*" + k + "[ \\t]*=).*$", "m");
    if (re.test(out)) out = out.replace(re, (m, p1) => p1 + " " + awg[k]);
  }
  return out;
}
// Per-peer render params — the peer's stored overrides where set, else the interface's LIVE defaults.
// Mirrors the server's effective_client_params so a blob-only render matches what the sub page produces.
export function effectiveClientParams(peer, meta) {
  const ov = (peer && peer.overrides) || {}; meta = meta || {};
  return {
    dns: ("dns" in ov) ? ov.dns : (meta.dns || []),
    mtu: ov.mtu || meta.mtu || 1280,
    allowed: ov.allowed || "0.0.0.0/0, ::/0",
    keepalive: ("keepalive" in ov) ? ov.keepalive : 25,
  };
}

// The ENCRYPTED-AT-REST config path: fetch the peer's ciphertext blob, decrypt it in-browser with the
// user's unlock-key (recovered from the vault), and rebuild the config LIVE from the decrypted {k,p} +
// the peer's overrides + the interface's current params. Returns null (caller falls back to plaintext /
// session) when the peer is unassigned, the vault is locked, or no blob exists yet. Never sends a key.
export async function blobConfig(peer, node, iface) {
  if (!peer || !subSKCached()) return null;                // user_id optional — unassigned peers use the orphan bucket
  const t = (peer.targets || []).find(x => x.node === node && x.iface === iface);
  const meta = Store.ifaceMeta(node, iface);
  if (!t || !meta) return null;
  let sec, unlockKey;
  try {
    const r = await api.subBlobGet(peer.id);
    if (!r || !r.ok || !r.data || !r.data.sec) return null;
    sec = r.data.sec;
    const buid = r.data.user_id || peer.user_id || SUB_ORPHAN;   // decrypt with the key of the bucket the blob is IN
    const rec = (await subUsersMap())[buid];
    if (!rec || !rec.unlock_by_sk) return null;
    unlockKey = await subRecoverUnlock(rec);   // unlock-key only (works whether or not the user is subscribed)
  } catch (_) { return null; }
  try {
    const secret = JSON.parse(new TextDecoder().decode(await subDec(unlockKey, sec)));   // GCM auth fails on a wrong key
    if (!secret || !secret.k) return null;
    const eff = effectiveClientParams(peer, meta);
    return buildConf({ privkey: secret.k, address: (t.ip || "").split("/")[0] + "/32",
      dns: eff.dns, mtu: eff.mtu, awg_params: meta.awg_params, server_pubkey: meta.public_key,
      psk: secret.p || peer.psk, endpoint: meta.endpoint, allowed: eff.allowed, keepalive: eff.keepalive });
  } catch (_) { return null; }
}

// A config the server currently can't build (e.g. the peer's interface is a ghost — gone with no key) returns
// EMPTY every time. Without a memory of that, a QR/config view re-requests it on every render/remount and floods
// the console + server with identical 404s. Remember an empty result per (pubkey,node,iface) and skip re-fetching
// it — invalidated by a configEpoch bump (an action that could change the answer: create / rekey / vault unlock)
// or a short TTL (so a restored interface self-heals without a manual refresh).
const _configMiss = new Map();   // "pubkey|node|iface" -> { epoch, at }
const _CONFIG_MISS_TTL = 30000;
function _configMissFresh(mk) {
  const m = _configMiss.get(mk);
  return !!(m && m.epoch === Store.configEpoch && (Date.now() - m.at) < _CONFIG_MISS_TTL);
}
export function getConfig(pubkey, node, iface) {
  const s = Store.sessionConfigs[pubkey];
  if (s && s[tkey(node, iface)]) return Promise.resolve(rerenderConf(s[tkey(node, iface)], node, iface));
  const peer = (Store.recon.peers || []).find(p => p.pubkey === pubkey);
  // A peer PROVEN to have no config server-side (while the vault was unlocked / store isn't encrypted) survives
  // reloads via _subNoConf — skip the blob + config probes that would just 404 again on every card render. A
  // rekey / re-issue changes the pubkey, so this self-invalidates. A LOCKED vault is not proof, so below we
  // neither trust nor write _subNoConf while locked (the short-TTL _configMiss handles that transient case).
  if (peer && subNoConfHas(peer.id, pubkey)) return Promise.resolve(null);
  const mk = pubkey + "|" + node + "|" + iface;
  if (_configMissFresh(mk)) return Promise.resolve(null);   // known-empty this epoch → don't re-hammer the server
  const definitive = Store.storeMode !== "encrypted" || subSKCached();   // a miss now means "no config", not "vault locked"
  const miss = () => { _configMiss.set(mk, { epoch: Store.configEpoch, at: Date.now() }); if (peer && definitive) subNoConfSet(peer.id, pubkey); };
  const hit = () => { _configMiss.delete(mk); if (peer) subNoConfClear(peer.id); };
  // encrypted-at-rest blob first (assigned peer + vault unlocked); else the transitional plaintext store.
  return blobConfig(peer, node, iface).then(c => {
    if (c) { hit(); return c; }
    // /api/config is the LEGACY plaintext endpoint; in the (normal) encrypted-at-rest steady state there are no
    // plaintext files, so it 404s for every peer. Only probe it while legacy files still await migration —
    // otherwise skip it, which is what killed the recurring /api/config 404 flood.
    if (Store.configsPlaintext > 0) return api.config(pubkey, node, iface).then(r => {
      const conf = rerenderConf(r.ok ? r.data.config : null, node, iface);
      if (conf) hit(); else miss();
      return conf;
    }).catch(() => { miss(); return null; });
    miss();
    return null;
  });
}
export function anySessionConf(pubkey) {
  const s = Store.sessionConfigs[pubkey]; return s ? (Object.values(s)[0] || null) : null;
}



// A blocking prompt for a user-triggered action that needs the encryption key when it isn't unlocked this
// session. Explains WHY the key is needed and the cost of skipping; "Unlock & continue" proceeds, "Skip"
// continues without the encrypted step. Resolves the ensureVaultUnlocked() promise with true/false.
export function VaultPromptSheet({ opts, onDone }) {
  const [pw, setPw] = useState(""); const [busy, setBusy] = useState(false);
  const [keep, setKeep] = useState(subPersistOn());   // "keep this device unlocked" — device-persist opt-in
  const [exists, setExists] = useState(null);   // null = checking; whether an encryption vault is set up at all
  useEffect(() => { let ok = true; api.subVault().then(r => { if (ok) setExists(!!(r && r.ok && r.data && r.data.exists)); }).catch(() => { if (ok) setExists(false); }); return () => { ok = false; }; }, []);
  const done = v => { closeModal(); onDone(v); };
  const unlock = async () => {
    if (!pw || busy) return; setBusy(true);
    try { await subUnlock(pw); subSetPersist(keep); Store.configEpoch++; bus.emit(); setBusy(false); done(true); }
    catch (e) { setBusy(false); toast((e && e.message) || T("That password didn’t unlock the Encryption Vault."), "err"); }
  };
  return html`<${Sheet} title=${opts.title || T("Enter your password to continue")} width=${480} onClose=${() => done(false)}
    foot=${html`<${Fragment}><span class="grow"></span>
      <button class="btn btn-ghost" disabled=${busy} onClick=${() => done(false)}>${T("Skip")}</button>
      <button class="btn btn-primary" disabled=${busy || !pw || exists === false} onClick=${unlock}>${busy ? T("Unlocking…") : T("Unlock vault")}</button></>`}>
    <div class="vaultprompt">
      <p class="vp-reason">${opts.reason || T("This action needs your Encryption Vault, which isn’t unlocked in this session.")}</p>
      ${exists === false
        ? html`<div class="notice err"><${Ic} i="warn"/><span>${vaultMissing(() => done(false))}</span></div>`
        : html`<${Fragment}><div class="field"><label>${T("Panel password")}</label>
            <input class="subpw" type="password" autofocus value=${pw} autocomplete="off" placeholder=${T("Panel password")}
              onKeyDown=${e => { if (e.key === "Enter") unlock(); }} onInput=${e => setPw(e.target.value)}/></div>
            <div class="vp-keep"><label class="vp-keep-row"><input type="checkbox" checked=${keep} onChange=${e => setKeep(e.target.checked)}/> <span>${T("Keep this device unlocked")}</span></label>
              <div class="hint">${T("Stay unlocked across restarts on this device — the key is stored only here, never sent to the server.")}</div></div><//>`}
      <div class="notice warn vp-skip"><${Ic} i="info"/><span><b>${T("If you skip:")}</b> ${opts.consequence || T("the action completes, but anything that needed the key won’t be saved.")}</span></div>
    </div>
  <//>`;
}
