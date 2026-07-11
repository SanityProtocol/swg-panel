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
      copied: "Copied", copyFailed: "Copy failed", showConfig: "Show config text", showLink: "Show link", showQR: "Show QR",
      toQR: "QR", toConfig: "Config", toLink: "Link", copyShort: "Copy", dlShort: "Download",
      clientCmd: "Client command", generating: "Generating…", qrTooBig: "config too large to encode as QR",
      noTurn: "No turn-proxy forwards to this server.", cantGen: "couldn’t generate this link",
      pasteInto: "Use in", tapCopy: "Tap to copy",
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
      copied: "Скопировано", copyFailed: "Не удалось", showConfig: "Показать текст конфига", showLink: "Показать ссылку", showQR: "Показать QR",
      toQR: "QR", toConfig: "Конфиг", toLink: "Ссылка", copyShort: "Копир.", dlShort: "Скачать",
      clientCmd: "Команда клиента", generating: "Генерация…", qrTooBig: "конфиг слишком большой для QR",
      noTurn: "Нет turn-прокси для этого сервера.", cantGen: "не удалось сгенерировать ссылку",
      pasteInto: "Использовать в", tapCopy: "Нажмите, чтобы скопировать",
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
  // Turn-proxy fork display order — mirrors the panel's TURN_FORKS so the sub lists forks the same way the
  // admin sees them in settings.
  var FORK_ORDER = ["cacggghp", "WINGS-N", "samosvalishe", "Moroka8", "kiper292", "anton48"];
  function forkRank(f) { var i = FORK_ORDER.indexOf(f); return i < 0 ? FORK_ORDER.length : i; }

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

  // Shrink a config/link <pre> so it fits its box in BOTH axes without scrolling — down to a legible floor
  // (past which overflow:auto lets it scroll). A ceiling keeps it from looking oversized on big/tablet screens.
  function fitText(pre) {
    var CEIL = 20, FLOOR = 7;
    pre.style.fontSize = CEIL + "px";                // grow to the ceiling; a short config fills its box…
    for (var i = 0, f = CEIL; i < 60 && f > FLOOR; i++) {
      if (pre.scrollHeight <= pre.clientHeight + 1 && pre.scrollWidth <= pre.clientWidth + 1) break;   // …shrink until it fits both axes (keys stay one line), then scroll
      f -= 0.5; pre.style.fontSize = f + "px";
    }
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
  // Decode a data: URL to a Blob WITHOUT fetch() — the sub's strict CSP (connect-src) would block fetching it.
  function dataUrlToBlob(url) {
    var comma = url.indexOf(","), mime = (url.slice(0, comma).match(/:(.*?);/) || [])[1] || "image/png";
    var bin = atob(url.slice(comma + 1)), arr = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new Blob([arr], { type: mime });
  }
  // Copy / save the QR itself (a PNG) — used when the QR is the thing on screen, so Copy/Download act on
  // what you see, not the hidden config text.
  function copyImage(url, btn, restore) {
    function done(ok) { if (btn) { btn.textContent = ok ? t("copied") : t("copyFailed"); setTimeout(function () { btn.textContent = restore; }, 1400); } }
    if (!window.ClipboardItem || !navigator.clipboard || !navigator.clipboard.write) return done(false);
    try {
      var blob = dataUrlToBlob(url), item = {}; item[blob.type] = blob;
      navigator.clipboard.write([new ClipboardItem(item)]).then(function () { done(true); }, function () { done(false); });
    } catch (_) { done(false); }
  }
  function downloadImage(url, name) {
    var a = document.createElement("a");
    a.href = url; a.download = (name || "qr").replace(/\.(conf|txt|png)$/i, "") + ".png";
    document.body.appendChild(a); a.click(); a.remove();
  }
  // The direct WireGuard/AmneziaWG config for a deployment (byte-identical to the panel's buildConf).
  function confFor(secret, tgt) {
    return buildConf({
      privkey: secret.k, address: (tgt.ip || "").split("/")[0] + "/32",
      dns: tgt.dns || [], mtu: tgt.mtu || 1280, awg_params: tgt.awg || {},
      server_pubkey: tgt.server_pubkey || "", psk: secret.p || "", endpoint: tgt.endpoint || "",
      allowed: tgt.allowed || "0.0.0.0/0, ::/0", keepalive: (tgt.keepalive != null ? tgt.keepalive : 25),
    });
  }

  // ── ONE server deployment as a full-viewport cell: a big centred QR (default) or the config/link text,
  //    toggled IN PLACE. Returns { el, ctrl }. ctrl drives the peer's fixed bottom bar (toggle/copy/download)
  //    so the currently-swiped cell's actions live in one steady spot. A turn artifact may resolve async
  //    (wingsv:// needs zlib) — the cell shows "Generating…" then fills. ──
  function makeCell(userName, peer, it, mode, secret, vkLink, reason) {
    var tgt = it.tgt, cell = el("div", "scell");
    var node = el("div", "scell-node");
    if (mode !== "turn" && tgt.primary && (peer.targets || []).length > 1) node.appendChild(el("span", "scell-primary", t("primary")));
    var srvRow = el("div", "scell-srv");   // server name + (turn fork tag) on one line
    srvRow.appendChild(el("span", "scell-server", tgt.node_name || tgt.node || tgt.iface || "server"));
    node.appendChild(srvRow);
    var stage = el("div", "scell-stage");
    cell.appendChild(node); cell.appendChild(stage);

    var conf = secret && secret.k ? confFor(secret, tgt) : null;
    var ctrl = { ready: false, payload: "", ext: "conf", isLink: false, hasQR: false, cmd: null, view: "qr",
                 base: fileName(userName, peer.title, tgt), redraw: null, notify: null };

    ctrl.copyInto = function (btn, restore) {
      (navigator.clipboard ? navigator.clipboard.writeText(ctrl.payload) : Promise.reject()).then(function () {
        if (btn) { btn.textContent = t("copied"); setTimeout(function () { btn.textContent = restore; }, 1400); }
      }, function () { if (btn) { btn.textContent = t("copyFailed"); setTimeout(function () { btn.textContent = restore; }, 1400); } });
    };

    function draw() {
      if (ctrl._ro) { ctrl._ro.disconnect(); ctrl._ro = null; }
      stage.innerHTML = "";
      if (!ctrl.ready) { stage.appendChild(el("div", "cfg-fail", reason || (mode === "turn" ? t("generating") : t("notReady")))); if (ctrl.notify) ctrl.notify(); return; }
      if (ctrl.view === "qr" && ctrl.hasQR) {
        var box = el("div", "qrbox");
        try { ctrl.qrUrl = qrDataURL(ctrl.payload, 760); var img = el("img", "qrimg"); img.alt = "config QR"; img.src = ctrl.qrUrl; box.appendChild(img); }
        catch (_) { ctrl.qrUrl = null; ctrl.hasQR = false; ctrl.view = "text"; return draw(); }
        stage.appendChild(box);
      } else {
        var wrap = el("div", "textwrap");
        var pre = el("pre", "cfgtext" + (ctrl.isLink ? " wrap" : ""), ctrl.payload); pre.title = t("tapCopy");
        pre.onclick = function () { ctrl.copyInto(null, ""); };
        wrap.appendChild(pre);
        if (ctrl.cmd) { var c = el("div", "cmdblk"); c.appendChild(el("div", "cmdlbl", t("clientCmd")));
          var cp = el("pre", "cfgtext cmdtext", ctrl.cmd); cp.title = t("tapCopy");
          cp.onclick = function () { if (navigator.clipboard) navigator.clipboard.writeText(ctrl.cmd); };
          c.appendChild(cp); wrap.appendChild(c); }
        stage.appendChild(wrap);
        // auto-fit the config to the stage (re-fits on rotation / cell resize)
        if (window.ResizeObserver) { ctrl._ro = new ResizeObserver(function () { fitText(pre); }); ctrl._ro.observe(stage); }
        else setTimeout(function () { fitText(pre); }, 0);
      }
      if (ctrl.notify) ctrl.notify();
    }
    ctrl.redraw = draw;

    if (mode === "turn") {
      var tp = it.tp;
      srvRow.appendChild(el("span", "scell-tag", SWGTurn.fork(tp.service)));   // fork tag beside the server name
      if (!conf) { draw(); return { el: cell, ctrl: ctrl }; }
      var art = SWGTurn.artifact(conf, tp, vkLink);
      node.appendChild(el("span", "scell-paste", t("pasteInto") + " " + (art.app || art.fork)));
      var apply = function (text) {
        ctrl.payload = text; ctrl.ready = true; ctrl.ext = art.ext || "conf";
        ctrl.isLink = !!art.uri; ctrl.hasQR = !!art.qr; ctrl.cmd = art.cmd || null;
        ctrl.view = (art.qr && !art.cmd) ? "qr" : "text";   // scannable link/conf → QR; sidecar dual → wg text first
        draw();
      };
      if (art.text != null) apply(art.text);
      else { draw(); Promise.resolve().then(art.buildAsync).then(apply).catch(function (e) { ctrl.ready = false; stage.innerHTML = ""; stage.appendChild(el("div", "cfg-fail", (e && e.message) || t("cantGen"))); if (ctrl.notify) ctrl.notify(); }); }
    } else {
      if (conf) { ctrl.payload = conf; ctrl.ready = true; ctrl.hasQR = true; ctrl.ext = "conf"; ctrl.view = "qr"; }
      draw();
    }
    return { el: cell, ctrl: ctrl };
  }

  // ── ONE peer as a full-viewport page: head (title + server dots) · a horizontal swipe row of server
  //    cells · a fixed bottom bar (toggle / copy / download) that always acts on the visible cell. ──
  function peerPage(row, mode, vkLink, userName) {
    var peer = row.peer, secret = row.secret, items = [];
    if (mode === "turn") {
      (peer.targets || []).forEach(function (tt) {
        var seen = {}, tps = [];
        (tt.turn || []).forEach(function (tp) { var f = SWGTurn.fork(tp.service); if (seen[f]) return; seen[f] = 1; tps.push({ tp: tp, f: f }); });
        tps.sort(function (a, b) { return forkRank(a.f) - forkRank(b.f); });   // canonical fork order (as in the panel)
        tps.forEach(function (x) { items.push({ tgt: tt, tp: x.tp }); });
      });
    } else {
      (peer.targets || []).forEach(function (tt) { if ((tt.type === "awg") === (mode === "awg")) items.push({ tgt: tt }); });
    }
    if (!items.length) return null;
    var reason = row.bad ? t("outOfDate") : (!peer.sec ? t("notReady") : null);

    var page = el("section", "ppage");
    var head = el("div", "ppage-head");
    head.appendChild(el("span", "ppage-title", peer.title || t("peer")));
    var dotEls = [];
    if (items.length > 1) { var dots = el("div", "ppage-dots"); for (var i = 0; i < items.length; i++) { var d = el("span", "pdot"); dotEls.push(d); dots.appendChild(d); } head.appendChild(dots); }
    page.appendChild(head);

    var srow = el("div", "srow");
    var ctrls = items.map(function (it) { var c = makeCell(userName, peer, it, mode, secret, vkLink, reason); srow.appendChild(c.el); return c.ctrl; });
    page.appendChild(srow);

    var bar = el("div", "pbar");
    var toggle = el("button", "pbtn ghost", ""); toggle.type = "button";
    var copyB = el("button", "pbtn ghost", ""); copyB.type = "button";
    var dlB = el("button", "pbtn primary", ""); dlB.type = "button";
    bar.appendChild(toggle); bar.appendChild(copyB); bar.appendChild(dlB);
    page.appendChild(bar);

    var curIdx = 0;
    function cur() { return ctrls[curIdx]; }
    function syncBar() {
      var c = cur();
      if (c && c.ready && c.hasQR) { toggle.hidden = false; toggle.textContent = (c.view === "qr") ? (c.isLink ? t("toLink") : t("toConfig")) : t("toQR"); }
      else toggle.hidden = true;
      var can = !!(c && c.ready && c.payload);
      copyB.hidden = dlB.hidden = !can;
      if (can) { copyB.textContent = t("copyShort"); dlB.textContent = t("dlShort"); }
      for (var i = 0; i < dotEls.length; i++) dotEls[i].className = "pdot" + (i === curIdx ? " on" : "");
    }
    ctrls.forEach(function (c) { c.notify = function () { if (ctrls[curIdx] === c) syncBar(); }; });
    toggle.onclick = function () { var c = cur(); if (!c || !c.hasQR) return; c.view = (c.view === "qr") ? "text" : "qr"; c.redraw(); syncBar(); };
    copyB.onclick = function () { var c = cur(); if (!c) return; if (c.view === "qr" && c.qrUrl) copyImage(c.qrUrl, copyB, t("copyShort")); else c.copyInto(copyB, t("copyShort")); };
    dlB.onclick = function () { var c = cur(); if (!c) return; var nm = c.base + (mode === "turn" ? "-turn" : ""); if (c.view === "qr" && c.qrUrl) downloadImage(c.qrUrl, nm); else download(c.payload, nm, c.ext || "conf"); };

    function current() { var sl = srow.scrollLeft, best = 0, bd = Infinity; for (var i = 0; i < srow.children.length; i++) { var dd = Math.abs((srow.children[i].offsetLeft - srow.offsetLeft) - sl); if (dd < bd) { bd = dd; best = i; } } return best; }
    var raf = 0;
    srow.addEventListener("scroll", function () { if (raf) return; raf = requestAnimationFrame(function () { raf = 0; var i = current(); if (i !== curIdx) { curIdx = i; syncBar(); } }); }, { passive: true });
    dotEls.forEach(function (d, i) { d.onclick = function () { srow.scrollTo({ left: srow.children[i].offsetLeft - srow.offsetLeft, behavior: "smooth" }); }; });
    setTimeout(syncBar, 0);
    return page;
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

      var bar = el("div", "modebar"), pager = el("div", "pager"), btns = {};
      tabs.forEach(function (m) {
        var b = el("button", "modetab" + (m === mode ? " on" : ""), t(m));
        b.onclick = function () { if (mode === m) return; mode = m; tabs.forEach(function (x) { btns[x].className = "modetab" + (x === mode ? " on" : ""); }); paint(); };
        btns[m] = b; bar.appendChild(b);
      });
      if (tabs.length > 1) wrap.appendChild(bar);
      wrap.appendChild(pager);

      function paint() {
        pager.scrollTop = 0; pager.innerHTML = "";
        rows.forEach(function (row) { var pg = peerPage(row, mode, vkLink, userName); if (pg) pager.appendChild(pg); });
        if (!pager.children.length) pager.appendChild(el("div", "ppage cfg-fail", t("noConfigs")));
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
