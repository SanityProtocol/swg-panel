/* swg-sub front-end — the public per-user subscription page.
 *
 * Everything secret happens here, in the browser: the unlock key rides in the URL fragment
 * (never sent to the server), decrypts each peer's private key + PSK client-side, and the
 * config is assembled locally. The server only ever hands us ciphertext + non-secret params.
 *
 * URL shape:  https://sub.<domain>/<token>#<unlock-key>
 *   <token>       — last path segment; identifies the ciphertext bucket to fetch.
 *   <unlock-key>  — URL fragment; base64url of a 32-byte AES-GCM key. Decrypts the secrets.
 *
 * Phase 3 renders every peer's every deployment (desktop-style). Phase 5 layers the mobile
 * primary-QR + swipe UX on top of this same data.
 */
(function () {
  "use strict";

  // ── theme + language bootstrap (runs before the page fetches/renders) ──
  var _ls = function (k) { try { return localStorage.getItem(k); } catch (_) { return null; } };
  var _lsSet = function (k, v) { try { if (v) localStorage.setItem(k, v); else localStorage.removeItem(k); } catch (_) {} };
  (function () {
    var m = _ls("swgsub-theme"); if (m === "light" || m === "dark") document.documentElement.setAttribute("data-theme", m);
    var l = _ls("swgsub-lang"); if (l === "ru" || l === "en") document.documentElement.lang = l;
  })();

  // ── i18n (English + Russian) ──
  var LANG = (function () { var s = _ls("swgsub-lang"); if (s === "en" || s === "ru") return s; return (navigator.language || "").slice(0, 2).toLowerCase() === "ru" ? "ru" : "en"; })();
  var STR = {
    en: {
      loading: "Loading…", noConfigs: "No configs yet",
      noConfigsSub: "There are no active peers on this subscription. New peers will appear here automatically.",
      peer: "Peer", primary: "Primary", download: "Download .conf", dl: "Download", copyConfig: "Copy config", copyLink: "Copy link",
      copied: "Copied", copyFailed: "Copy failed", showConfig: "Show config text", showLink: "Show link",
      clientCmd: "Client command", generating: "Generating…", qrTooBig: "config too large to encode as QR",
      noTurn: "No turn-proxy forwards to this server.", cantGen: "couldn’t generate this link",
      pasteInto: "Paste into", tapCopy: "Tap to copy",
      notReady: "Not ready yet — open this peer once in the panel to publish it.",
      outOfDate: "This link is out of date — ask your administrator for a fresh one.",
      someBad: "Some peers couldn’t be decrypted — this link may be out of date. Ask your administrator for a fresh one.",
      invalid: "Invalid link", invalidSub: "This subscription link is missing its identifier.",
      badKey: "The unlock key in this link isn’t valid.",
      incomplete: "Incomplete link",
      incompleteSub: "This link is missing the part after “#”. Copy the whole URL — the section after the # is what unlocks your configs and it never leaves your device.",
      notFound: "Link not found", notFoundSub: "This subscription doesn’t exist, was revoked, or subscriptions are turned off.",
      err: "Something went wrong", errServer: "Couldn’t load this subscription (server error). Please try again later.",
      errNet: "Couldn’t load this subscription. Check your connection and try again.",
      errResp: "The server returned an unexpected response.",
      unsupported: "Unsupported browser",
      unsupportedSub: "This page needs a modern browser with Web Crypto (and a secure https:// connection) to decrypt your configs.",
      wg: "WireGuard", awg: "AmneziaWG", turn: "Turn",
      langName: "EN", themeToLight: "Switch to light", themeToDark: "Switch to dark", langLabel: "Language",
    },
    ru: {
      loading: "Загрузка…", noConfigs: "Пока нет конфигураций",
      noConfigsSub: "На этой подписке нет активных пиров. Новые появятся здесь автоматически.",
      peer: "Пир", primary: "Основной", download: "Скачать .conf", dl: "Скачать", copyConfig: "Скопировать", copyLink: "Скопировать ссылку",
      copied: "Скопировано", copyFailed: "Не удалось", showConfig: "Показать текст конфига", showLink: "Показать ссылку",
      clientCmd: "Команда клиента", generating: "Генерация…", qrTooBig: "конфиг слишком большой для QR",
      noTurn: "Нет turn-прокси для этого сервера.", cantGen: "не удалось сгенерировать ссылку",
      pasteInto: "Вставьте в", tapCopy: "Нажмите, чтобы скопировать",
      notReady: "Ещё не готово — откройте этот пир один раз в панели, чтобы опубликовать.",
      outOfDate: "Эта ссылка устарела — попросите у администратора новую.",
      someBad: "Некоторые пиры не удалось расшифровать — возможно, ссылка устарела. Попросите у администратора новую.",
      invalid: "Неверная ссылка", invalidSub: "В этой ссылке отсутствует идентификатор.",
      badKey: "Ключ разблокировки в этой ссылке недействителен.",
      incomplete: "Неполная ссылка",
      incompleteSub: "В ссылке отсутствует часть после «#». Скопируйте URL целиком — часть после # разблокирует ваши конфиги и никогда не покидает ваше устройство.",
      notFound: "Ссылка не найдена", notFoundSub: "Эта подписка не существует, была отозвана или подписки отключены.",
      err: "Что-то пошло не так", errServer: "Не удалось загрузить подписку (ошибка сервера). Попробуйте позже.",
      errNet: "Не удалось загрузить подписку. Проверьте соединение и попробуйте снова.",
      errResp: "Сервер вернул неожиданный ответ.",
      unsupported: "Браузер не поддерживается",
      unsupportedSub: "Для расшифровки конфигов нужен современный браузер с Web Crypto и защищённое соединение https://.",
      wg: "WireGuard", awg: "AmneziaWG", turn: "Turn",
      langName: "RU", themeToLight: "Светлая тема", themeToDark: "Тёмная тема", langLabel: "Язык",
    },
  };
  function t(k) { return (STR[LANG] && STR[LANG][k]) || STR.en[k] || k; }
  function servers(n) {
    if (LANG === "ru") { var f = ["сервер", "сервера", "серверов"], a = Math.abs(n) % 100, n1 = a % 10;
      var w = (a > 10 && a < 20) ? f[2] : (n1 > 1 && n1 < 5) ? f[1] : (n1 === 1) ? f[0] : f[2]; return n + " " + w; }
    return n + " " + (n === 1 ? "server" : "servers");
  }

  var AWG_ORDER = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4", "I1", "I2", "I3", "I4", "I5"];

  // ── base64 (both standard and url-safe, padding optional) → bytes ──
  function b64ToBytes(s) {
    s = String(s || "").replace(/-/g, "+").replace(/_/g, "/").replace(/\s+/g, "");
    while (s.length % 4) s += "=";
    var bin = atob(s), out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  // ── config assembly — byte-identical to the panel's buildConf() ──
  function guardAllowed(a) {
    var parts = ((a || "").trim() || "0.0.0.0/0, ::/0").split(",").map(function (x) { return x.trim(); }).filter(Boolean);
    if (parts.indexOf("0.0.0.0/0") >= 0 && !parts.some(function (p) { return p.indexOf(":") >= 0; })) parts.push("::/0");
    return parts.join(", ");
  }
  function buildConf(o) {
    var L = ["[Interface]", "PrivateKey = " + o.privkey, "Address = " + o.address];
    if (o.dns && o.dns.length) L.push("DNS = " + o.dns.join(", "));
    L.push("MTU = " + (o.mtu || 1280));
    for (var i = 0; i < AWG_ORDER.length; i++) {
      var k = AWG_ORDER[i];
      if (o.awg_params && o.awg_params[k] != null) L.push(k + " = " + o.awg_params[k]);
    }
    L.push("", "[Peer]", "PublicKey = " + o.server_pubkey);
    if (o.psk) L.push("PresharedKey = " + o.psk);
    L.push("AllowedIPs = " + guardAllowed(o.allowed), "Endpoint = " + o.endpoint,
      "PersistentKeepalive = " + (o.keepalive != null && o.keepalive !== "" ? o.keepalive : 25));
    return L.join("\n") + "\n";
  }

  // ── QR — mirrors the panel's qrDataURL() ──
  function qrDataURL(text, targetPx) {
    var q = qrcode(0, "L");
    q.addData(text); q.make();
    var n = q.getModuleCount(), quiet = 4, total = n + quiet * 2;
    var cell = Math.max(3, Math.floor((targetPx || 320) / total));
    var size = total * cell;
    var c = document.createElement("canvas"); c.width = c.height = size;
    var ctx = c.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, size, size);
    ctx.fillStyle = "#000";
    for (var r = 0; r < n; r++)
      for (var col = 0; col < n; col++)
        if (q.isDark(r, col)) ctx.fillRect((col + quiet) * cell, (r + quiet) * cell, cell, cell);
    return c.toDataURL("image/png");
  }

  function el(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  // ── brand theme — follow the panel's per-mode accent colour (drives the logo, tabs, buttons, favicon) ──
  var THEME = { color: "", light: "" };   // set from the served subscription data
  function isLight() {
    var d = document.documentElement.getAttribute("data-theme");   // manual override wins; else the OS preference
    if (d === "light") return true; if (d === "dark") return false;
    return !!(window.matchMedia && matchMedia("(prefers-color-scheme: light)").matches);
  }
  function hexLum(h) {
    h = String(h).replace("#", ""); if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    var r = parseInt(h.slice(0, 2), 16) / 255, g = parseInt(h.slice(2, 4), 16) / 255, b = parseInt(h.slice(4, 6), 16) / 255;
    return isNaN(r) ? 0.5 : 0.299 * r + 0.587 * g + 0.114 * b;
  }
  function applyFavicon(accent, light) {
    var centre = light ? "#FFFFFF" : "#0A0E15";
    var svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
      + "<rect width='32' height='32' rx='8' fill='" + accent + "'/>"
      + "<circle cx='16' cy='14.5' r='5.5' fill='" + centre + "'/></svg>";
    var link = document.querySelector("link[rel~='icon']");
    if (!link) { link = document.createElement("link"); link.rel = "icon"; document.head.appendChild(link); }
    link.setAttribute("href", "data:image/svg+xml," + encodeURIComponent(svg));
  }
  function applyBrand() {
    var light = isLight();
    var brand = (light ? THEME.light : THEME.color) || (light ? "#0E9BB0" : "#1FC8D6");   // panel's per-mode defaults
    var de = document.documentElement;
    de.style.setProperty("--brand", brand);
    de.style.setProperty("--brand-2", "color-mix(in srgb, " + brand + " 70%, #fff)");
    de.style.setProperty("--brand-ink", hexLum(brand) > 0.55 ? "#04232A" : "#EAFBFF");
    applyFavicon(brand, light);
  }
  try { if (window.matchMedia) matchMedia("(prefers-color-scheme: light)").addEventListener("change", function () { applyBrand(); paintCtl(); }); } catch (_) {}

  // ── language + theme controls (top-right) ──
  var SUPPORTED = ["en", "ru"];
  var LANGS = ["en"], LANG_DEFAULT = "en";       // which languages the admin enabled + the default (from the served data)
  var _lastData = null, _lastKey = null;
  function resolveLang() {
    var enabled = LANGS.filter(function (l) { return SUPPORTED.indexOf(l) >= 0; });
    if (!enabled.length) enabled = ["en"];
    var saved = _ls("swgsub-lang");
    LANG = (saved && enabled.indexOf(saved) >= 0) ? saved
         : (enabled.indexOf(LANG_DEFAULT) >= 0 ? LANG_DEFAULT : enabled[0]);
    document.documentElement.lang = LANG;
    return enabled;
  }
  function setLang(l) { LANG = l; _lsSet("swgsub-lang", l); document.documentElement.lang = l; paintCtl(); if (_lastData && _lastKey) render(_lastData, _lastKey); }
  function setTheme(mode) {   // "light" | "dark" | "" (auto)
    _lsSet("swgsub-theme", mode);
    if (mode) document.documentElement.setAttribute("data-theme", mode); else document.documentElement.removeAttribute("data-theme");
    applyBrand(); paintCtl();
  }
  var _iconSun = "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round'><circle cx='12' cy='12' r='4.2'/><path d='M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4'/></svg>";
  var _iconMoon = "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21 12.8A8.5 8.5 0 1 1 11.2 3a6.6 6.6 0 0 0 9.8 9.8z'/></svg>";
  function paintCtl() {
    var enabled = LANGS.filter(function (l) { return SUPPORTED.indexOf(l) >= 0; }); if (!enabled.length) enabled = ["en"];
    var lb = document.getElementById("lang-btn");
    if (lb) {
      if (enabled.length > 1) { lb.hidden = false; lb.textContent = (STR[LANG] || STR.en).langName; lb.title = t("langLabel"); }
      else lb.hidden = true;                       // one language → no selector, just the default
    }
    var tb = document.getElementById("theme-btn");
    if (tb) { var light = isLight(); tb.innerHTML = light ? _iconMoon : _iconSun; tb.title = light ? t("themeToDark") : t("themeToLight"); }
  }
  function wireControls() {
    var lb = document.getElementById("lang-btn"), tb = document.getElementById("theme-btn");
    if (lb && !lb._wired) { lb._wired = 1; lb.onclick = function () {
      var en = LANGS.filter(function (l) { return SUPPORTED.indexOf(l) >= 0; }); if (!en.length) en = ["en"];
      setLang(en[(en.indexOf(LANG) + 1) % en.length]); }; }
    if (tb && !tb._wired) { tb._wired = 1; tb.onclick = function () { setTheme(isLight() ? "dark" : "light"); }; }
  }

  function showState(msg, sub) {
    var s = document.getElementById("state");
    s.hidden = false;
    s.className = "state";
    s.innerHTML = "";
    var h = el("p", "state-msg", msg);
    s.appendChild(h);
    if (sub) s.appendChild(el("p", "state-sub", sub));
    document.getElementById("peers").hidden = true;
  }

  function fileName(user, peer, tgt) {
    var s = (user || "peer") + "-" + (peer || "") + "-" + (tgt.node || "");
    return s.replace(/[^\w.-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "swg";
  }
  function download(text, name, ext) {
    var blob = new Blob([text], { type: "application/octet-stream" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name.replace(/\.(conf|txt)$/i, "") + "." + (ext || "conf");
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }
  function copyText(text, btn, label) {
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(function () {
      btn.textContent = t("copied"); setTimeout(function () { btn.textContent = label; }, 1400);
    }, function () {});
  }

  // A single deployment (node/iface) card: QR + actions + collapsible config text.
  function targetCard(userName, peer, tgt, conf, reason) {
    var card = el("div", "tgt");
    if (tgt.primary) card.appendChild(el("div", "primary", t("primary")));
    card.appendChild(el("div", "tgt-node", tgt.node_name || tgt.node || tgt.iface || "server"));

    if (!conf) {
      card.appendChild(el("div", "qr-fail", reason || t("notReady")));
      return card;
    }

    var qwrap = el("div", "qr");
    try {
      var img = el("img", "qrimg");
      img.alt = "config QR";
      img.src = qrDataURL(conf, 320);
      qwrap.appendChild(img);
    } catch (_) {
      qwrap.appendChild(el("div", "qr-fail", t("qrTooBig")));
    }
    card.appendChild(qwrap);

    var acts = el("div", "acts");
    var name = fileName(userName, peer.title, tgt);
    var dl = el("button", "btn", t("download"));
    dl.onclick = function () { download(conf, name); };
    acts.appendChild(dl);
    var cp = el("button", "btn ghost", t("copyConfig"));
    cp.onclick = function () {
      (navigator.clipboard ? navigator.clipboard.writeText(conf) : Promise.reject()).then(function () {
        cp.textContent = t("copied"); setTimeout(function () { cp.textContent = t("copyConfig"); }, 1400);
      }, function () { cp.textContent = t("copyFailed"); setTimeout(function () { cp.textContent = t("copyConfig"); }, 1400); });
    };
    acts.appendChild(cp);
    card.appendChild(acts);

    var det = el("details", "cfg");
    det.appendChild(el("summary", null, t("showConfig")));
    det.appendChild(el("pre", null, conf));
    card.appendChild(det);
    return card;
  }

  // Prev/next + dots for a peer's deployment carousel. The scroll container does the swiping (CSS
  // scroll-snap); this just drives it from buttons and reflects the position. Offsets are measured
  // live so it's robust to gaps and to the desktop→mobile layout switch. Hidden on wide screens via CSS.
  function carouselNav(grid, count) {
    var nav = el("div", "peer-nav");
    var prev = el("button", "nav-btn", "‹"); prev.setAttribute("aria-label", "Previous server"); prev.type = "button";
    var next = el("button", "nav-btn", "›"); next.setAttribute("aria-label", "Next server"); next.type = "button";
    var dots = el("div", "nav-dots"), dotEls = [];
    for (var i = 0; i < count; i++) { var d = el("span", "nav-dot"); dotEls.push(d); dots.appendChild(d); }
    function offset(i) { return grid.children[i].getBoundingClientRect().left - grid.getBoundingClientRect().left + grid.scrollLeft; }
    function current() { var sl = grid.scrollLeft, best = 0, bd = Infinity; for (var i = 0; i < count; i++) { var dd = Math.abs(offset(i) - sl); if (dd < bd) { bd = dd; best = i; } } return best; }
    function go(i) { i = Math.max(0, Math.min(count - 1, i)); grid.scrollTo({ left: offset(i), behavior: "smooth" }); }
    prev.onclick = function () { go(current() - 1); };
    next.onclick = function () { go(current() + 1); };
    function sync() { var idx = current(); for (var i = 0; i < dotEls.length; i++) dotEls[i].className = "nav-dot" + (i === idx ? " on" : ""); prev.disabled = idx <= 0; next.disabled = idx >= count - 1; }
    var raf = 0;
    grid.addEventListener("scroll", function () { if (raf) return; raf = requestAnimationFrame(function () { raf = 0; sync(); }); }, { passive: true });
    dotEls.forEach(function (d, i) { d.onclick = function () { go(i); }; });
    nav.appendChild(prev); nav.appendChild(dots); nav.appendChild(next);
    setTimeout(sync, 0);
    return nav;
  }

  // The direct WireGuard/AmneziaWG config for a deployment (byte-identical to the panel's buildConf).
  function confFor(secret, tgt) {
    return buildConf({
      privkey: secret.k, address: (tgt.ip || "").split("/")[0] + "/32",
      dns: tgt.dns || [], mtu: tgt.mtu || 1280, awg_params: tgt.awg || {},
      server_pubkey: tgt.server_pubkey || "", psk: secret.p || "", endpoint: tgt.endpoint || "",
      allowed: "0.0.0.0/0, ::/0", keepalive: 25,
    });
  }


  // One turn-proxy config for a peer (a single deployment × fork). Turn artifacts aren't QRs — they're
  // config TEXT or app links — so we show the text (tap to copy) with a "Paste into <app>" line above it
  // and Copy/Download beneath. The shared SWGTurn.artifact builds it (same as the admin). A peer's turn
  // configs are laid out as swipeable cards (one per view) by paint()'s carousel.
  function turnConfigCard(userName, peer, tgt, tp, conf, vkLink, reason) {
    var card = el("div", "tgt");
    card.appendChild(el("div", "tgt-node", tgt.node_name || tgt.node || tgt.iface || "server"));
    if (!conf) { card.appendChild(el("div", "qr-fail", reason || t("notReady"))); return card; }
    var art = SWGTurn.artifact(conf, tp, vkLink);
    card.appendChild(el("div", "turn-app", t("pasteInto") + " " + (art.app || art.fork)));   // which app to paste into
    var box = el("div", "turntext-wrap"), acts = el("div", "acts");
    card.appendChild(box); card.appendChild(acts);
    function fill(text) {
      box.innerHTML = ""; acts.innerHTML = "";
      var copyLabel = art.uri ? t("copyLink") : t("copyConfig");
      var pre = el("pre", "turntext", text); pre.title = t("tapCopy");
      box.appendChild(pre);
      var cp = el("button", "btn ghost", copyLabel);
      pre.onclick = function () { copyText(text, cp, copyLabel); };
      cp.onclick = function () { copyText(text, cp, copyLabel); };
      var dl = el("button", "btn", t("dl") + " ." + (art.ext || "conf"));
      dl.onclick = function () { download(text, fileName(userName, peer.title, tgt) + "-" + (art.fork || "turn"), art.ext || "conf"); };
      acts.appendChild(cp); acts.appendChild(dl);
      if (art.cmd) { var dc = el("details", "cfg"); dc.appendChild(el("summary", null, t("clientCmd"))); dc.appendChild(el("pre", null, art.cmd)); card.appendChild(dc); }
    }
    if (art.text != null) fill(art.text);
    else { box.appendChild(el("div", "hint", t("generating")));
      Promise.resolve().then(art.buildAsync).then(fill).catch(function (e) { box.innerHTML = ""; box.appendChild(el("div", "qr-fail", (e && e.message) || t("cantGen"))); }); }
    return card;
  }

  function render(data, cryptoKey) {
    _lastData = data; _lastKey = cryptoKey;
    LANGS = (data.langs && data.langs.enabled && data.langs.enabled.length) ? data.langs.enabled : ["en"];
    LANG_DEFAULT = (data.langs && data.langs.default) || "en";
    resolveLang(); wireControls(); paintCtl();     // the admin controls which languages are offered + the default
    THEME.color = data.theme_color || ""; THEME.light = data.theme_color_light || "";
    applyBrand();                                    // logo + favicon follow the panel's theme colour
    var who = document.getElementById("who");
    who.textContent = data.user && data.user.name ? data.user.name : "";
    var wrap = document.getElementById("peers");
    wrap.innerHTML = "";
    var peers = data.peers || [];
    if (!peers.length) {
      showState(t("noConfigs"), t("noConfigsSub"));
      return Promise.resolve();
    }
    var vkLink = data.vk_link || "", userName = data.user && data.user.name;

    // Decrypt every peer's secret (privkey+psk) with the fragment key.
    var jobs = peers.map(function (peer) {
      if (!peer.sec) return Promise.resolve({ peer: peer, secret: null });
      var all = b64ToBytes(peer.sec);
      return crypto.subtle.decrypt({ name: "AES-GCM", iv: all.slice(0, 12) }, cryptoKey, all.slice(12))
        .then(function (buf) { return { peer: peer, secret: JSON.parse(new TextDecoder().decode(new Uint8Array(buf))) }; })
        .catch(function () { return { peer: peer, secret: null, bad: true }; });
    });

    return Promise.all(jobs).then(function (rows) {
      var anyBad = rows.some(function (r) { return r.bad; });
      // Which top-level tabs apply: WG/AWG if the user has ≥1 deployment of that protocol; TURN only when the
      // feature is on AND ≥1 deployment has a proxy forwarding to it (same gate as the admin view).
      var has = { wg: false, awg: false, turn: false };
      rows.forEach(function (r) { (r.peer.targets || []).forEach(function (t) {
        has[t.type === "awg" ? "awg" : "wg"] = true;
        if (data.turn_enabled && (t.turn || []).length) has.turn = true;
      }); });
      var tabs = ["wg", "awg", "turn"].filter(function (m) { return has[m]; });
      if (!tabs.length) { showState(t("noConfigs"), t("noConfigsSub")); return; }
      var mode = tabs[0];   // WG first when present, else the first available

      var bar = el("div", "modebar"), listEl = el("div", "peer-list"), btns = {};
      tabs.forEach(function (m) {
        var b = el("button", "modetab" + (m === mode ? " on" : ""), t(m));
        b.onclick = function () { if (mode === m) return; mode = m; tabs.forEach(function (x) { btns[x].className = "modetab" + (x === mode ? " on" : ""); }); paint(); };
        btns[m] = b; bar.appendChild(b);
      });
      if (tabs.length > 1) wrap.appendChild(bar);
      wrap.appendChild(listEl);

      function paint() {
        listEl.innerHTML = "";
        rows.forEach(function (row) {
          var peer = row.peer, secret = row.secret;
          // Items for the selected tab. WG/AWG: one per matching deployment. TURN: one per (deployment × fork)
          // config, so a peer with several turn-proxies is a swipeable set of configs.
          var items = [];
          if (mode === "turn") {
            (peer.targets || []).forEach(function (tt) {
              var seen = {};
              (tt.turn || []).forEach(function (tp) { var f = SWGTurn.fork(tp.service); if (seen[f]) return; seen[f] = 1; items.push({ tgt: tt, tp: tp }); });
            });
          } else {
            (peer.targets || []).forEach(function (tt) { if ((tt.type === "awg") === (mode === "awg")) items.push({ tgt: tt }); });
          }
          if (!items.length) return;                       // this peer has nothing in the selected mode
          var sec = el("section", "peer");
          var head = el("div", "peer-head");
          head.appendChild(el("span", "peer-title", peer.title || t("peer")));
          head.appendChild(el("span", "peer-count", servers(items.length)));
          sec.appendChild(head);
          var reason = row.bad ? t("outOfDate") : (!peer.sec ? t("notReady") : null);
          var grid = el("div", "tgts");
          items.forEach(function (it) {
            var conf = secret && secret.k ? confFor(secret, it.tgt) : null;
            grid.appendChild(mode === "turn" ? turnConfigCard(userName, peer, it.tgt, it.tp, conf, vkLink, reason)
                                             : targetCard(userName, peer, it.tgt, conf, reason));
          });
          sec.appendChild(grid);
          if (items.length > 1) sec.appendChild(carouselNav(grid, items.length));
          listEl.appendChild(sec);
        });
      }
      paint();
      document.getElementById("state").hidden = true;
      wrap.hidden = false;
      if (anyBad) wrap.appendChild(el("p", "foot-warn", t("someBad")));
    });
  }

  function start() {
    wireControls(); paintCtl();                    // theme toggle works even before the data loads
    var lp = document.querySelector("#state p"); if (lp) lp.textContent = t("loading");
    var seg = location.pathname.split("/").filter(Boolean);
    var token = seg.length ? seg[seg.length - 1] : "";
    var keyB64 = (location.hash || "").replace(/^#/, "").trim();

    if (!token) return showState(t("invalid"), t("invalidSub"));
    if (!keyB64) return showState(t("incomplete"), t("incompleteSub"));

    var keyBytes;
    try {
      keyBytes = b64ToBytes(keyB64);
      if (keyBytes.length !== 32) throw new Error("bad key length");
    } catch (_) {
      return showState(t("invalid"), t("badKey"));
    }

    crypto.subtle.importKey("raw", keyBytes, { name: "AES-GCM" }, false, ["decrypt"])
      .then(function (cryptoKey) {
        return fetch("/api/" + encodeURIComponent(token), { cache: "no-store" }).then(function (res) {
          if (res.status === 404) { showState(t("notFound"), t("notFoundSub")); return null; }
          if (!res.ok) { showState(t("err"), t("errServer")); return null; }
          return res.json().then(function (j) {
            if (!j || !j.ok || !j.data) { showState(t("err"), t("errResp")); return null; }
            return render(j.data, cryptoKey);
          });
        });
      })
      .catch(function () {
        showState(t("err"), t("errNet"));
      });
  }

  if (!window.crypto || !crypto.subtle) {
    showState(t("unsupported"), t("unsupportedSub"));
  } else {
    start();
  }
})();
