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
      copied: "Copied", copiedClip: "Copied to clipboard", copyFailed: "Copy failed", showConfig: "Show config text", showLink: "Show link", showQR: "Show QR",
      toQR: "QR", toConfig: "Config", toLink: "Link", copyShort: "Copy", dlShort: "Download", enlarge: "Tap to enlarge", share: "Share",
      prevConfig: "Previous config", nextConfig: "Next config",
      clientCmd: "Client command", generating: "Generating…", qrTooBig: "config too large to encode as QR",
      noTurn: "No turn-proxy forwards to this server.", cantGen: "couldn’t generate this link",
      pasteInto: "Use in", tapCopy: "Tap to copy",
      vkThen: "Then add this VK call link in the app:", vkNone: "Then add a VK call link in the app — create a VK call and copy its vk.ru/call/join/… link.",
      vkAddApp: "Add this VK call link to {app}", vkAddFork: "Add this VK call link to {fork} app", vkAddGeneric: "Add this VK call link to the turn proxy app",
      backup: "Backup",
      vkMissingT: "No VK call link provided in the subscription", vkMissing: "Create a VK call and add its vk.ru/call/join/… link in {app}", theApp: "the app",
      notReady: "Not ready yet — open this peer once in the panel to publish it.",
      outOfDate: "This link is out of date — ask your administrator for a fresh one.",
      someBad: "Some peers couldn’t be decrypted — this link may be out of date. Ask your administrator for a fresh one.",
      invalid: "Invalid link", invalidSub: "This subscription link is missing its identifier.",
      badKey: "The unlock key in this link isn’t valid.",
      incomplete: "Incomplete link",
      incompleteSub: "This link is missing the part after “#”. Copy the whole URL — the section after the # is what unlocks your configs and it never leaves your device.",
      notFound: "Link not found", notFoundSub: "This subscription doesn’t exist, was revoked, or subscriptions are turned off.",
      subDisabled: "Subscription disabled", subDisabledSub: "This subscription has been turned off. Please contact your administrator.",
      err: "Something went wrong", errServer: "Couldn’t load this subscription (server error). Please try again later.",
      errNet: "Couldn’t load this subscription. Check your connection and try again.",
      errResp: "The server returned an unexpected response.",
      unsupported: "Unsupported browser",
      unsupportedSub: "This page needs a modern browser with Web Crypto (and a secure https:// connection) to decrypt your configs.",
      wg: "WireGuard", awg: "AmneziaWG", turn: "Turn", turnApp: "Turn proxy app", forkApp: "{fork} app",
      langName: "EN", themeToLight: "Switch to light", themeToDark: "Switch to dark", langLabel: "Language",
    },
    ru: {
      loading: "Загрузка…", noConfigs: "Пока нет конфигураций",
      noConfigsSub: "На этой подписке нет активных пиров. Новые появятся здесь автоматически.",
      peer: "Пир", primary: "Основной", download: "Скачать .conf", dl: "Скачать", copyConfig: "Скопировать", copyLink: "Скопировать ссылку",
      copied: "Скопировано", copiedClip: "Скопировано в буфер обмена", copyFailed: "Не удалось", showConfig: "Показать текст конфига", showLink: "Показать ссылку", showQR: "Показать QR",
      toQR: "QR", toConfig: "Конфиг", toLink: "Ссылка", copyShort: "Копир.", dlShort: "Скачать", enlarge: "Нажмите, чтобы увеличить", share: "Поделиться",
      prevConfig: "Предыдущий конфиг", nextConfig: "Следующий конфиг",
      clientCmd: "Команда клиента", generating: "Генерация…", qrTooBig: "конфиг слишком большой для QR",
      noTurn: "Нет turn-прокси для этого сервера.", cantGen: "не удалось сгенерировать ссылку",
      pasteInto: "Использовать в", tapCopy: "Нажмите, чтобы скопировать",
      vkThen: "Затем добавьте эту ссылку на звонок VK в приложении:", vkNone: "Затем добавьте ссылку на звонок VK в приложении — создайте звонок VK и скопируйте ссылку vk.ru/call/join/…",
      vkAddApp: "Добавьте эту ссылку на звонок VK в {app}", vkAddFork: "Добавьте эту ссылку на звонок VK в приложении", vkAddGeneric: "Добавьте эту ссылку на звонок VK в приложении",
      backup: "Запасной",
      vkMissingT: "Ссылка на звонок VK не указана в подписке", vkMissing: "Создайте звонок VK и добавьте ссылку vk.ru/call/join/… в {app}", theApp: "приложении",
      notReady: "Ещё не готово — откройте этот пир один раз в панели, чтобы опубликовать.",
      outOfDate: "Эта ссылка устарела — попросите у администратора новую.",
      someBad: "Некоторые пиры не удалось расшифровать — возможно, ссылка устарела. Попросите у администратора новую.",
      invalid: "Неверная ссылка", invalidSub: "В этой ссылке отсутствует идентификатор.",
      badKey: "Ключ разблокировки в этой ссылке недействителен.",
      incomplete: "Неполная ссылка",
      incompleteSub: "В ссылке отсутствует часть после «#». Скопируйте URL целиком — часть после # разблокирует ваши конфиги и никогда не покидает ваше устройство.",
      notFound: "Ссылка не найдена", notFoundSub: "Эта подписка не существует, была отозвана или подписки отключены.",
      subDisabled: "Подписка отключена", subDisabledSub: "Эта подписка отключена. Обратитесь к администратору.",
      err: "Что-то пошло не так", errServer: "Не удалось загрузить подписку (ошибка сервера). Попробуйте позже.",
      errNet: "Не удалось загрузить подписку. Проверьте соединение и попробуйте снова.",
      errResp: "Сервер вернул неожиданный ответ.",
      unsupported: "Браузер не поддерживается",
      unsupportedSub: "Для расшифровки конфигов нужен современный браузер с Web Crypto и защищённое соединение https://.",
      wg: "WireGuard", awg: "AmneziaWG", turn: "Turn", turnApp: "Приложение для turn proxy", forkApp: "Приложение {fork}",
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
  // Forks whose client is WireGuard-only (no AmneziaWG) — mirrors the panel's TURN_WG_ONLY. They can't front an
  // AmneziaWG interface, so they're not offered for an AWG peer. (samosvalishe = free-turn-proxy/FreeTurn app.)
  var TURN_WG_ONLY = { kiper292: 1, anton48: 1, samosvalishe: 1 };

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
  // A chevron arrow as an inline SVG (built via the DOM so the strict CSP is happy). dir: l/r/u/d.
  function chevronEl(dir) {
    var NS = "http://www.w3.org/2000/svg";
    var D = { l: "M15 18l-6-6 6-6", r: "M9 18l6-6-6-6", u: "M18 15l-6-6-6 6", d: "M6 9l6 6 6-6" };
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "2.4");
    svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
    var p = document.createElementNS(NS, "path"); p.setAttribute("d", D[dir]); svg.appendChild(p);
    return svg;
  }
  function arrowBtn(cls, dir, label) {
    var b = el("button", cls); b.type = "button"; b.setAttribute("aria-label", label); b.appendChild(chevronEl(dir)); return b;
  }
  // Action-bar icons, DOM-built for the strict CSP. Each is a list of [svgTag, attrs].
  var ICONS = {
    qr: [["rect", { x: 3, y: 3, width: 7, height: 7, rx: 1.5 }], ["rect", { x: 14, y: 3, width: 7, height: 7, rx: 1.5 }],
         ["rect", { x: 3, y: 14, width: 7, height: 7, rx: 1.5 }], ["path", { d: "M14 14h3v3M21 14v3M17 21h4M14 21h.01M21 21v.01M17 17h.01" }]],
    doc: [["path", { d: "M6 2h9l5 5v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z" }], ["path", { d: "M14 2v6h6" }], ["path", { d: "M8 13h8M8 17h5" }]],
    copy: [["rect", { x: 9, y: 9, width: 11, height: 11, rx: 2 }], ["path", { d: "M5 15V5a2 2 0 0 1 2-2h10" }]],
    download: [["path", { d: "M12 3v11" }], ["path", { d: "M7 10l5 5 5-5" }], ["path", { d: "M4 15v2a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3v-2" }]],
    share: [["circle", { cx: 18, cy: 5, r: 3 }], ["circle", { cx: 6, cy: 12, r: 3 }], ["circle", { cx: 18, cy: 19, r: 3 }], ["path", { d: "M8.6 13.5l6.8 4M15.4 6.5l-6.8 4" }]],
    check: [["path", { d: "M20 6 9 17l-5-5" }]]
  };
  function iconEl(name) {
    var NS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
    (ICONS[name] || []).forEach(function (spec) { var e = document.createElementNS(NS, spec[0]); for (var k in spec[1]) e.setAttribute(k, spec[1][k]); svg.appendChild(e); });
    return svg;
  }
  function iconBtn(cls, name, label) {
    var b = el("button", cls); b.type = "button"; b.title = label; b.setAttribute("aria-label", label); b.appendChild(iconEl(name)); return b;
  }
  // brief "Copied to clipboard" bubble centred over a text box (its wrapper must be position:relative)
  function flashCopied(container) {
    if (!container) return;
    var old = container.querySelector(".copied-bubble"); if (old) old.remove();
    var b = el("div", "copied-bubble", t("copiedClip")); container.appendChild(b);
    setTimeout(function () { if (b.parentNode) b.parentNode.removeChild(b); }, 1300);
  }
  function setIcon(btn, name, label) {
    var old = btn.querySelector("svg"); if (old) old.remove();
    btn.insertBefore(iconEl(name), btn.firstChild);
    if (label != null) { btn.title = label; btn.setAttribute("aria-label", label); }
  }

  // The brand protocol marks (WireGuard / AmneziaWG / Turn), one cyan→blue family. Kept as full SVG so the
  // gradient fills survive; parsed via DOMParser (no script — CSP-safe) and every gradient id is uniquified
  // per instance so several copies on one page never share a <defs> id.
  var PROTO_SVG = {
    wg: '<svg viewBox="0 0 300 300" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="wg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1FC8D6"/><stop offset="1" stop-color="#2B7CD3"/></linearGradient></defs><path d="m 101.94526,94.697 c 30.017,-18.364 68.366,-7.1401 82.735,20.476 2.7233,5.2338 3.0694,13.291 1.3447,18.782 -5.9546,18.956 -20.014,29.587 -39.312,34.103 5.6892,-4.8707 10.218,-10.394 11.659,-18.025 a 26.402,26.402 0 0 0 -4.5425,-20.956 26.76,26.76 0 0 0 -30.811,-9.3892 c -11.881,4.5111 -18.389,15.354 -17.216,28.683 1.0898,12.381 10.484,20.405 28.061,23.453 -2.627,1.3904 -4.6503,2.4144 -6.6299,3.5172 a 63.918,63.918 0 0 0 -20.544,17.868 c -1.7839,2.4084 -3.0104,2.6024 -5.727,0.94116 -35.338,-21.61 -37.609,-75.844 0.98226,-99.453 z m -26.449,133.53 c -5.6769,1.441 -11.178,3.5742 -16.981,5.4775 2.8385,-19.151 25.265,-36.788 44.23,-34.776 a 48.881,48.881 0 0 0 -9.242,25.893 c -6.302,1.1606 -12.241,1.9414 -18.007,3.405 z m 120.79,-186.98 c 5.6099,0.20612 11.23,0.12091 16.844,0.25378 a 29.052,29.052 0 0 1 4.1674,0.58069 40.607,40.607 0 0 1 -4.2357,5.4332 c -2.007,1.8701 -4.2745,3.6986 -7.1661,0.856 -0.6955,-0.68372 -2.3386,-0.52679 -3.5487,-0.54272 -5.5823,-0.07336 -11.172,-0.25177 -16.746,-0.04132 a 104.04,104.04 0 0 0 -14.425,1.473 c -0.89368,0.16046 -2.2299,3.1315 -1.8191,4.227 0.9693,2.5853 2.3833,5.4363 4.4779,7.0898 7.7403,6.11 15.972,11.596 23.748,17.664 7.556,5.8966 14.589,12.358 18.875,21.253 5.5843,11.59 5.747,23.743 3.3388,35.95 -4.0203,20.378 -14.333,37.261 -31.032,49.524 -6.7288,4.941 -15.06,7.7451 -22.767,11.295 -6.778,3.1225 -13.755,5.8115 -20.549,8.9008 -12.249,5.5695 -19.133,18.865 -17.108,32.688 1.8585,12.685 12.987,23.271 25.735,25.456 15.292,2.6216 31.071,-7.3163 34.812,-22.86 4.2067,-17.478 -5.2898,-33.083 -23.065,-37.813 -0.78271,-0.20831 -1.5684,-0.40552 -3.2012,-0.8269 4.7549,-2.1245 8.8614,-3.6381 12.653,-5.7244 q 9.9213,-5.4594 19.481,-11.562 c 1.8742,-1.199 2.8868,-1.1996 4.4852,0.18225 12.225,10.57 19.518,23.718 21.563,39.839 3.3845,26.684 -9.2471,51.198 -33.072,63.762 -36.86,19.439 -81.965,-2.6864 -90.106,-43.552 -6.9738,-35.003 17.73,-66.754 47.462,-72.884 12.787,-2.6364 24.48,-7.9596 33.57,-17.807 5.8652,-6.3541 8.7084,-11.806 9.6772,-14.266 a 39.565,39.565 0 0 0 2.7211,-14.469 33.867,33.867 0 0 0 -2.9654,-12.398 c -3.104,-7.075 -14.995,-18.33 -17.939,-20.704 l -28,-21.921 c -0.98761,-0.81256 -2.0994,-0.75366 -4.5079,-0.59045 -2.8611,0.19391 -10.175,0.59888 -13.331,-0.22815 2.553,-1.9321 9.5132,-4.7451 12.502,-7.007 -9.0734,-6.1297 -19.43,-3.9158 -28.941,-5.7461 2.1992,-4.0959 13.081,-10.39 19.27,-11.091 a 91.533,91.533 0 0 0 -1.6876,-10.281 c -0.37781,-1.3917 -1.9312,-2.7408 -3.2864,-3.5355 -3.286,-1.9267 -6.7694,-3.5167 -10.549,-5.4327 a 21.936,21.936 0 0 1 11.332,-3.5055 42.316,42.316 0 0 1 11.348,1.1056 c 6.7422,1.5405 12.124,0.53491 17.488,-4.048 -4.222,-1.7002 -8.4435,-3.2535 -12.538,-5.0907 a 123.04,123.04 0 0 1 -11.779,-6.1583 c 10.622,1.4755 20.896,5.4585 31.757,4.0034 q 0.1387,-0.74048 0.27728,-1.4809 c -8.1194,-1.8899 -16.239,-3.7798 -25.229,-5.8724 15.04,-1.3769 29.042,-1.604 42.301,4.8541 3.731,1.8173 7.6348,3.3215 11.211,5.3972 1.7443,1.0124 2.9186,3.0078 4.3496,4.5594 1.1366,1.2325 2.0495,2.8837 3.446,3.6264 5.3,2.8184 11.134,2.9291 17.078,2.7879 0.0444,-0.67694 0.0861,-1.3114 0.1308,-1.9933 5.9821,1.8693 12.715,8.7679 12.704,13.806 -9.6911,0 -19.374,-0.037 -29.056,0.05389 -1.0348,0.0097 -2.0626,0.76563 -3.0936,1.1754 0.97986,0.57067 1.9428,1.5994 2.9423,1.6362 z" fill="url(#wg)" fill-rule="evenodd"/><path d="m 183.78526,26.906 a 1.4806,1.4806 0 0 0 -0.18927,2.3686 2.2326,2.2326 0 0 0 3.0724,0.8219 c 0.9328,-0.47052 1.8478,-0.97137 2.975,-1.5665 -0.9079,-0.775 -1.6362,-1.4148 -2.3857,-2.0324 -1.318,-1.086 -2.411,-0.40386 -3.4724,0.40833 z" fill="#2B7CD3" opacity=".55"/></svg>',
    awg: '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="ag" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1FC8D6"/><stop offset="1" stop-color="#2B7CD3"/></linearGradient></defs><path d="M20.28 0.84 20.64 0.84 20.64 2.76 20.52 2.88 20.52 3.72 20.4 3.84 20.28 4.44 20.76 5.28 20.88 5.76 21.48 6.36 21.84 6.36 22.32 6.6 22.2 9.96 22.56 10.92 22.56 12.48 22.44 12.6 22.44 12.96 22.2 13.32 22.2 13.56 21.96 13.92 21.84 15.0 21.6 15.36 21.48 15.84 21.0 16.44 20.76 17.04 20.04 17.76 18.84 18.6 16.8 20.64 16.68 21.0 16.44 21.24 16.32 21.72 15.96 22.2 15.84 22.8 15.48 23.16 15.12 23.16 14.88 22.92 14.64 22.44 14.52 21.48 14.28 21.12 14.28 20.88 14.04 20.64 12.96 20.64 12.84 20.76 10.32 20.64 10.08 20.76 9.6 21.36 9.24 23.04 9.12 23.16 8.76 23.16 8.52 22.92 7.2 20.04 6.48 19.44 5.52 19.08 5.04 18.6 4.92 18.6 3.48 17.16 2.88 16.32 2.28 15.12 2.28 14.88 1.92 14.28 1.92 13.92 1.56 12.96 1.56 11.28 1.68 11.16 1.68 10.2 1.8 10.08 1.8 9.0 1.92 8.88 2.28 7.56 2.76 6.6 3.6 5.52 3.6 4.68 3.72 4.56 3.72 4.2 3.6 4.08 3.6 1.8 3.72 1.68 3.72 1.32 4.2 1.32 4.44 1.68 4.8 2.4 4.8 2.64 5.04 3.12 5.04 3.48 5.28 3.84 6.0 3.0 6.48 3.0 7.08 2.52 8.76 1.68 9.0 1.68 9.48 1.44 10.56 1.44 10.68 1.32 12.96 1.32 13.08 1.44 13.8 1.44 13.92 1.56 14.88 1.68 15.6 2.04 15.96 2.04 16.44 2.28 17.04 1.92 17.76 1.92 18.0 2.28 18.0 2.52 18.24 3.0 18.48 3.24 18.84 3.24 19.44 2.4 20.16 0.96ZM10.92 3.6 13.44 3.6 13.56 3.72 13.92 3.72 14.04 3.84 14.64 3.96 15.72 4.56 16.44 4.68 17.04 5.16 17.4 5.28 17.76 5.64 17.76 5.88 17.64 6.0 17.64 6.84 17.52 6.96 17.52 7.68 17.4 7.8 17.4 9.0 17.28 9.12 17.28 9.72 17.16 9.84 17.16 10.56 17.04 10.68 17.04 11.16 16.8 11.64 16.8 12.0 16.56 12.48 16.56 13.08 16.44 13.2 16.32 14.16 16.2 14.28 16.08 15.6 15.96 15.72 15.84 16.44 15.48 17.28 15.24 17.4 15.0 16.44 14.76 16.08 14.76 15.6 14.4 15.0 14.4 14.76 13.92 13.8 13.92 13.08 13.44 11.76 13.32 10.32 12.96 9.48 12.96 9.12 12.84 9.0 12.6 8.04 12.36 7.8 12.0 7.8 11.88 7.92 11.76 8.4 11.52 8.76 11.52 9.0 11.28 9.48 11.16 10.44 11.04 10.56 11.04 11.04 10.92 11.16 10.92 11.64 10.68 12.24 10.56 13.2 10.08 14.16 10.08 14.4 9.96 14.52 9.48 16.2 9.24 16.56 9.0 17.52 8.76 17.64 8.52 17.28 8.52 17.04 8.28 16.56 8.28 16.08 7.92 15.12 7.92 14.76 7.68 14.28 7.56 13.44 7.32 12.96 7.32 12.48 7.08 11.88 7.08 11.4 6.72 10.44 6.72 9.96 6.48 9.36 6.48 8.76 6.36 8.64 6.36 8.16 6.24 8.04 6.24 7.44 6.12 7.32 6.12 6.84 5.88 6.24 5.88 5.76 6.48 5.16 7.8 4.44 8.04 4.44 9.24 3.96 9.72 3.96 10.32 3.72 10.8 3.72ZM19.32 8.28 19.8 9.0 19.92 10.08 20.04 10.2 19.92 12.48 19.68 12.96 19.56 13.68 19.08 14.52 19.08 14.76 18.6 15.72 17.52 16.92 17.88 16.2 18.0 14.76 18.12 14.64 18.12 14.28 18.36 13.8 18.36 13.32 18.48 13.2 18.48 12.84 18.72 12.24 18.72 11.52 18.84 11.4 18.84 10.92 18.96 10.8 18.96 10.32 19.08 10.2 19.08 9.48 19.2 9.36 19.32 8.4ZM3.96 8.4 4.08 8.4 4.44 9.12 4.92 10.8 5.28 11.4 5.52 12.6 5.64 12.72 5.64 13.2 5.76 13.32 5.76 13.92 6.0 14.52 6.0 16.44 5.64 16.68 5.16 16.44 4.32 15.48 3.24 13.32 3.12 12.6 3.0 12.48 3.0 12.0 3.12 11.88 3.12 10.32 3.24 10.2 3.24 9.84 3.6 9.24 3.6 9.0 3.96 8.52ZM12.12 13.08 12.24 13.2 12.24 13.56 12.6 14.52 12.96 16.44 13.08 16.56 13.44 17.88 12.84 18.6 12.24 18.84 10.8 18.72 10.56 18.48 10.8 18.0 10.8 17.64 10.92 17.52 11.04 16.92 11.16 16.8 11.16 16.44 11.28 16.32 11.28 15.96 11.52 15.36 11.52 14.88 11.64 14.76 11.76 13.92 12.12 13.2Z" fill="url(#ag)" fill-rule="evenodd"/></svg>',
    turn: '<svg viewBox="1.5 1.6 21 20.8" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g1" gradientUnits="userSpaceOnUse" x1="2" y1="4" x2="22" y2="20"><stop offset="0" stop-color="#1FC8D6"/><stop offset="1" stop-color="#2B7CD3"/></linearGradient></defs><path d="M16.7 5.2 A8.7 8.7 0 1 0 16.7 18.8" fill="none" stroke="url(#g1)" stroke-width="1.6" stroke-linecap="round"/><path d="M14.44 18.98 L12.94 21.57" fill="none" stroke="url(#g1)" stroke-width="0.95" stroke-linecap="round"/><path d="M12.32 19.66 L15.06 20.88" fill="none" stroke="url(#g1)" stroke-width="0.95" stroke-linecap="round"/><path d="M7.87 19.12 L4.91 19.64" fill="none" stroke="url(#g1)" stroke-width="0.95" stroke-linecap="round"/><path d="M5.98 17.94 L6.8 20.82" fill="none" stroke="url(#g1)" stroke-width="0.95" stroke-linecap="round"/><path d="M3.53 14.17 L1.24 12.25" fill="none" stroke="url(#g1)" stroke-width="0.95" stroke-linecap="round"/><path d="M3.22 11.97 L1.55 14.45" fill="none" stroke="url(#g1)" stroke-width="0.95" stroke-linecap="round"/><path d="M4.53 7.68 L4.53 4.68" fill="none" stroke="url(#g1)" stroke-width="0.95" stroke-linecap="round"/><path d="M6.03 6.02 L3.04 6.34" fill="none" stroke="url(#g1)" stroke-width="0.95" stroke-linecap="round"/><path d="M10.15 4.27 L12.45 2.34" fill="none" stroke="url(#g1)" stroke-width="0.95" stroke-linecap="round"/><path d="M12.38 4.35 L10.22 2.26" fill="none" stroke="url(#g1)" stroke-width="0.95" stroke-linecap="round"/><path d="M11 9.7 V12.4" fill="none" stroke="url(#g1)" stroke-width="1.35" stroke-linecap="round"/><path d="M11 12.4 L8.1 14.4" fill="none" stroke="url(#g1)" stroke-width="1.35" stroke-linecap="round"/><path d="M11 12.4 L13.9 14.4" fill="none" stroke="url(#g1)" stroke-width="1.35" stroke-linecap="round"/><circle cx="11" cy="7.7" r="2.0" fill="none" stroke="url(#g1)" stroke-width="1.35"/><circle cx="7.5" cy="15.4" r="1.5" fill="none" stroke="url(#g1)" stroke-width="1.35"/><circle cx="14.5" cy="15.4" r="1.5" fill="none" stroke="url(#g1)" stroke-width="1.35"/><path d="M17.5 9.9 H20.4" fill="none" stroke="url(#g1)" stroke-width="1.25" stroke-linecap="round"/><path d="M17.5 11.7 H21.4" fill="none" stroke="url(#g1)" stroke-width="1.25" stroke-linecap="round"/><path d="M17.5 13.5 H20.4" fill="none" stroke="url(#g1)" stroke-width="1.25" stroke-linecap="round"/></svg>'
  };
  var _protoN = 0;
  function protoIcon(mode) {
    var raw = PROTO_SVG[mode];
    if (!raw) return document.createElementNS("http://www.w3.org/2000/svg", "svg");
    var s = "_p" + (++_protoN);
    raw = raw.replace(/id="([^"]+)"/g, 'id="$1' + s + '"').replace(/url\(#([^)]+)\)/g, 'url(#$1' + s + ')');
    var doc = new DOMParser().parseFromString(raw, "image/svg+xml");
    return document.importNode(doc.documentElement, true);
  }

  // Shrink a config/link <pre> so it fits its box in BOTH axes without scrolling — down to a legible floor
  // (past which overflow:auto lets it scroll). A ceiling keeps it from looking oversized on big/tablet screens.
  // box = a single .cfgtext OR a .textwrap wrapping one/two config blocks (config + sidecar client-command). Shrink
  // EVERY block's font in lockstep until the whole box fits VERTICALLY (all lines show); over-wide lines scroll
  // horizontally (thin bar) — never vertically.
  function fitText(box) {
    if (box.querySelector && box.querySelector(".qrbox")) return;   // QR view: the QR is fixed and the command keeps its normal font
    var pres = (box.classList && box.classList.contains("cfgtext") && !box.classList.contains("cmdtext")) ? [box]
             : (box.querySelectorAll ? [].slice.call(box.querySelectorAll(".cfgtext:not(.cmdtext)")) : []);   // the command keeps its own font
    if (!pres.length) return;
    // Landscape/desktop is a simple scrolling document — every config box uses ONE uniform CSS font size (no
    // per-config fit-shrinking, which made wrapping links render larger than the width-limited AWG config).
    if (window.matchMedia && window.matchMedia("(orientation: landscape)").matches) {
      for (var q = 0; q < pres.length; q++) pres[q].style.fontSize = "";
      return;
    }
    var CEIL = 21, FLOOR = 3, f = CEIL, j;   // ceiling; floor low so a huge AWG config still fits alongside the command
    for (j = 0; j < pres.length; j++) pres[j].style.fontSize = CEIL + "px";
    for (var i = 0; i < 80 && f > FLOOR; i++) {
      var fits = box.scrollHeight <= box.clientHeight + 1;                 // whole box fits vertically…
      for (j = 0; fits && j < pres.length; j++)                           // …and every NON-wrapping block fits its width
        if (!pres[j].classList.contains("wrap") && !pres[j].classList.contains("cmdtext") && pres[j].scrollWidth > pres[j].clientWidth + 1) fits = false;
      if (fits) break;
      f -= 0.5; for (j = 0; j < pres.length; j++) pres[j].style.fontSize = f + "px";
    }
  }

  // ── brand theme — follow the panel's per-mode accent colour (drives the logo, tabs, buttons, favicon) ──
  // FORK/IFACE default colours mirror the panel's TURN_FORKS / IFACE_COLOR_DEFAULTS so the sub's fork tags and
  // WG/AWG tabs match the admin view; the panel's per-fork / per-protocol OVERRIDES ride in the served data.
  var FORK_COLORS = {
    "cacggghp": { dark: "#5FB0E0", light: "#2C7EC0" }, "WINGS-N": { dark: "#C98BE0", light: "#9B4FC7" },
    "samosvalishe": { dark: "#E0A85F", light: "#C07A1E" }, "Moroka8": { dark: "#E07A9A", light: "#C24468" },
    "kiper292": { dark: "#6FD9A8", light: "#12A46B" }, "anton48": { dark: "#D9CF5F", light: "#8E8420" } };
  var IFACE_COLORS = { wg: { dark: "#3FD89A", light: "#0E9E63" }, awg: { dark: "#1FC8D6", light: "#0E9BB0" } };
  var THEME = { color: "", light: "", forkOv: {}, ifaceOv: {}, nodeOv: {} };   // set from the served subscription data
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
  // Resolve a themed override ({dark,light} | string | null) for the current mode — mirrors the panel's pickThemed.
  function pickThemed(v, defDark, defLight) {
    var light = isLight();
    if (v && typeof v === "object") return (light ? v.light : v.dark) || (light ? defLight : defDark);
    if (typeof v === "string" && v) return v;
    return light ? defLight : defDark;
  }
  function forkColor(fork) { var d = FORK_COLORS[fork] || { dark: "#8FA8C0", light: "#5E7085" }; return pickThemed(THEME.forkOv[fork], d.dark, d.light); }
  function ifaceColor(type) { var k = (type || "").toLowerCase() === "awg" ? "awg" : "wg"; return pickThemed(THEME.ifaceOv[k], IFACE_COLORS[k].dark, IFACE_COLORS[k].light); }
  function nodeColor(nodeId, fallback) { var c = THEME.nodeOv[nodeId]; return (c && (c.dark || c.light)) ? pickThemed(c, fallback, fallback) : fallback; }   // server name in its panel colour
  function modeColor(m) { return m === "turn" ? "#7C5CFF" : ifaceColor(m); }   // Turn = the panel's turn-proxy accent (violet)
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
  try { if (window.matchMedia) matchMedia("(prefers-color-scheme: light)").addEventListener("change", function () { applyBrand(); paintCtl(); if (_lastData && _lastKey) render(_lastData, _lastKey); }); } catch (_) {}

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
  // Capture where the reader is right now (which page + deployment + QR/config view) so a rebuild can restore it.
  function capturePos() {
    var pager = document.querySelector("#peers .pager");
    if (!pager) return null;
    var pages = pager.children; if (!pages.length) return null;
    var top = pager.getBoundingClientRect().top + 6, pi = pages.length - 1;
    for (var i = 0; i < pages.length; i++) { if (pages[i].getBoundingClientRect().bottom > top) { pi = i; break; } }
    var pg = pages[pi], sub = (pg && pg._pos) ? pg._pos() : { cell: 0, view: null };
    return { page: pi, cell: sub.cell, view: sub.view };
  }
  function reRender() {   // rebuild for a lang/theme change, but land the reader back where they were
    if (!_lastData || !_lastKey) return;
    var pos = capturePos();
    render(_lastData, _lastKey, pos);
  }
  function setLang(l) { LANG = l; _lsSet("swgsub-lang", l); document.documentElement.lang = l; paintCtl(); reRender(); }
  function setTheme(mode) {   // "light" | "dark" | "" (auto)
    _lsSet("swgsub-theme", mode);
    if (mode) document.documentElement.setAttribute("data-theme", mode); else document.documentElement.removeAttribute("data-theme");
    applyBrand(); paintCtl();
    reRender();   // re-tint the fork tags + mode tabs for the new mode, keeping the reader in place
  }
  var _iconSun = "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round'><circle cx='12' cy='12' r='4.2'/><path d='M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4'/></svg>";
  var _iconMoon = "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21 12.8A8.5 8.5 0 1 1 11.2 3a6.6 6.6 0 0 0 9.8 9.8z'/></svg>";
  function paintCtl() {
    var enabled = LANGS.filter(function (l) { return SUPPORTED.indexOf(l) >= 0; }); if (!enabled.length) enabled = ["en"];
    var lb = document.getElementById("lang-btn");
    if (lb) {
      if (enabled.length > 1) { lb.hidden = false;
        var nextLang = enabled[(enabled.indexOf(LANG) + 1) % enabled.length];   // the button shows what you'd SWITCH TO
        lb.textContent = (STR[nextLang] || STR.en).langName; lb.title = t("langLabel"); }
      else lb.hidden = true;                       // one language → no selector, just the default
    }
    var tb = document.getElementById("theme-btn");
    if (tb) { var light = isLight(); tb.innerHTML = light ? _iconMoon : _iconSun; tb.title = light ? t("themeToDark") : t("themeToLight"); }
  }
  var _noFocusRing = false;
  function suppressButtonFocus() {   // mouse-clicking a button must not leave it focused (a later key press would flash its focus ring)
    if (_noFocusRing) return; _noFocusRing = true;
    document.addEventListener("mousedown", function (e) {
      var b = e.target && e.target.closest && e.target.closest("button");
      if (b) e.preventDefault();   // don't focus on click; keyboard Tab focus still works
    }, false);
  }
  var _stickWired = false;
  function wireStickyHeader() {   // landscape/desktop only: past the fold, collapse the header into a sticky top bar + a side rail
    if (_stickWired) return; _stickWired = true;
    var update = function () {
      var landscape = window.matchMedia && window.matchMedia("(orientation: landscape)").matches;
      var y = window.scrollY || document.documentElement.scrollTop || 0;
      document.body.classList.toggle("scrolled", !!landscape && y > 70);
    };
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update, { passive: true });
    update();
  }
  function wireControls() {
    suppressButtonFocus();
    wireStickyHeader();
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

  // ── Fullscreen QR viewer (tap the QR to enlarge for scanning; tap anywhere / Esc to close). Mirrors the
  //    admin panel's qrZoom. DOM-built (no innerHTML) so the strict CSP is happy. ──
  var qrZoomEl = null;
  function zoomQR(payload, label) {
    if (qrZoomEl) { try { qrZoomEl.remove(); } catch (_) {} qrZoomEl = null; }
    var ov = el("div", "qz-overlay"), inner = el("div", "qz-inner"), card = el("div", "qz-card");
    try { var img = el("img", "qrimg"); img.alt = "config QR"; img.src = qrDataURL(payload, 920); card.appendChild(img); }
    catch (e) { card.appendChild(el("div", "qz-fail", t("qrTooBig"))); }
    inner.appendChild(card);
    if (label) inner.appendChild(el("div", "qz-cap", label));
    ov.appendChild(inner);
    function onKey(e) { if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); close(); } }
    function close() { try { ov.remove(); } catch (_) {} if (qrZoomEl === ov) qrZoomEl = null; document.removeEventListener("keydown", onKey, true); }
    ov.onclick = close;
    document.addEventListener("keydown", onKey, true);
    qrZoomEl = ov;
    document.body.appendChild(ov);
  }

  // ── ONE server deployment as a full-viewport cell: a big centred QR (default) or the config/link text,
  //    toggled IN PLACE. Returns { el, ctrl }. ctrl drives the peer's fixed bottom bar (toggle/copy/download)
  //    so the currently-swiped cell's actions live in one steady spot. A turn artifact may resolve async
  //    (wingsv:// needs zlib) — the cell shows "Generating…" then fills. ──
  function makeCell(userName, peer, it, mode, secret, vkLink, reason, multi) {
    var tgt = it.tgt, cell = el("div", "scell");
    var node = el("div", "scell-node");
    var srvRow = el("div", "scell-srv");   // holds the protocol/app badge + the Primary/Backup role — the server name rides the peer-title line
    node.appendChild(srvRow);
    if (mode !== "turn") {   // WG/AWG cells get a protocol badge (like the turn app badge) + Primary/Backup when there's >1 deployment
      var ic0 = ifaceColor(tgt.type);
      var ib = el("span", "scell-tag", tgt.type === "awg" ? t("awg") : t("wg"));
      ib.style.color = ic0;
      srvRow.appendChild(ib);
      if (multi) {
        var isBk0 = !tgt.primary;
        var role0 = el("span", "scell-role" + (isBk0 ? " scell-backup" : ""), tgt.primary ? t("primary") : t("backup"));
        if (!isBk0) role0.style.color = ic0;
        srvRow.appendChild(role0);
      }
    }
    var stage = el("div", "scell-stage");
    cell.appendChild(node); cell.appendChild(stage);

    var conf = secret && secret.k ? confFor(secret, tgt) : null;
    var ctrl = { ready: false, payload: "", ext: "conf", isLink: false, hasQR: false, cmd: null, view: "qr",
                 base: fileName(userName, peer.title, tgt), redraw: null, notify: null,
                 srvName: (tgt.node_name || tgt.node || tgt.iface || "server"), srvColor: nodeColor(tgt.node, ifaceColor(tgt.type)) };

    ctrl.copyInto = function (btn, restore) {
      (navigator.clipboard ? navigator.clipboard.writeText(ctrl.payload) : Promise.reject()).then(function () {
        if (btn) { btn.textContent = t("copied"); setTimeout(function () { btn.textContent = restore; }, 1400); }
      }, function () { if (btn) { btn.textContent = t("copyFailed"); setTimeout(function () { btn.textContent = restore; }, 1400); } });
    };

    // the sidecar client-command block — shown UNDER the config OR under the QR (the QR only replaces the WG/AWG
    // config). Under the QR it carries no "CLIENT COMMAND" label and keeps the normal config font (not shrunk).
    // a small copy affordance overlaid on a text box; getText() supplies the payload when tapped; `bubbleIn` (a
    // position:relative wrapper) gets a centred "Copied to clipboard" bubble on success.
    function copyBtn(cls, getText, bubbleIn) {
      var b = iconBtn(cls, "copy", t("copyConfig"));
      b.onclick = function (e) { if (e) e.stopPropagation();
        (navigator.clipboard ? navigator.clipboard.writeText(getText()) : Promise.reject())
          .then(function () { setIcon(b, "check", t("copied")); setTimeout(function () { setIcon(b, "copy", t("copyConfig")); }, 1400); flashCopied(bubbleIn); }, function () {}); };
      return b;
    }
    function cmdBlock(withLabel) {
      if (!ctrl.cmd) return null;
      var c = el("div", "cmdblk");
      if (withLabel) c.appendChild(el("div", "cmdlbl", t("clientCmd")));
      var box = el("div", "cmdrow");   // the one-line command + a copy affordance pinned to its right edge
      var cp = el("pre", "cfgtext cmdtext", ctrl.cmd); cp.title = t("tapCopy");   // fixed readable font via CSS; clips if long
      var copy = copyBtn("cmdcopy", function () { return ctrl.cmd; }, box);
      cp.onclick = function () { copy.onclick(); };
      box.appendChild(cp); box.appendChild(copy);
      c.appendChild(box); return c;
    }
    // Re-fit the block(s) only when the stage WIDTH changes (viewport / rotation). Our layout pass nudges the stage's
    // top padding — a HEIGHT-only change — and re-fitting on that would fight the placement (fit ↔ shift oscillation).
    function attachFit(wrap) {
      var doFit = function () {
        fitText(wrap);
        var mp = wrap.querySelector(".cfgtext");   // remember the config's fitted size so the QR view's command matches
        if (mp && !wrap.querySelector(".qrbox") && mp.style.fontSize) ctrl.cfgFont = mp.style.fontSize;
        if (ctrl.notify) ctrl.notify();
      };
      if (window.ResizeObserver) { var _lw = -1;
        ctrl._ro = new ResizeObserver(function () { var w = Math.round(stage.getBoundingClientRect().width); if (w === _lw) return; _lw = w; doFit(); });
        ctrl._ro.observe(stage); }
      else setTimeout(doFit, 0);
    }
    function draw() {
      if (ctrl._ro) { ctrl._ro.disconnect(); ctrl._ro = null; }
      stage.innerHTML = "";
      if (!ctrl.ready) { stage.appendChild(el("div", "cfg-fail", reason || (mode === "turn" ? t("generating") : t("notReady")))); if (ctrl.notify) ctrl.notify(); return; }
      if (ctrl.view === "qr" && ctrl.hasQR) {
        var box = el("div", "qrbox");
        try { ctrl.qrUrl = qrDataURL(ctrl.payload, 760); var img = el("img", "qrimg"); img.alt = "config QR"; img.src = ctrl.qrUrl; box.appendChild(img); }
        catch (_) { ctrl.qrUrl = null; ctrl.hasQR = false; ctrl.view = "text"; return draw(); }
        box.title = t("enlarge");   // tap the QR to open it fullscreen for scanning
        box.onclick = function () { zoomQR(ctrl.payload, [peer.title, tgt.node_name || tgt.node].filter(Boolean).join(" · ")); };
        var cmdQ = cmdBlock(true);               // QR view: keep the "Client command" label, same as the config view
        if (!cmdQ) { stage.appendChild(box); }   // plain single QR
        else {                                   // dual config: QR replaces the WG/AWG config, the command stays under it
          var wrapq = el("div", "textwrap"); wrapq.appendChild(box); wrapq.appendChild(cmdQ);
          stage.appendChild(wrapq); attachFit(wrapq);
        }
      } else {
        var wrap = el("div", "textwrap");
        var cfgwrap = el("div", "cfgwrap");   // relative box so the copy affordance sits in the bottom-right corner
        var pre = el("pre", "cfgtext" + (ctrl.isLink ? " wrap" : ""), ctrl.payload); pre.title = t("tapCopy");
        pre.onclick = function () { ctrl.copyInto(null, ""); flashCopied(cfgwrap); };
        cfgwrap.appendChild(pre);
        cfgwrap.appendChild(copyBtn("cfgcopy", function () { return ctrl.payload; }, cfgwrap));
        wrap.appendChild(cfgwrap);
        var cmdT = cmdBlock(true); if (cmdT) wrap.appendChild(cmdT);   // config view: labelled, fit with the config
        stage.appendChild(wrap); attachFit(wrap);
      }
      if (ctrl.notify) ctrl.notify();
    }
    ctrl.redraw = draw;

    if (mode === "turn") {
      var tp = it.tp, forkId = SWGTurn.fork(tp.service);
      var fc = forkColor(forkId);                                               // the panel's colour for this fork
      var art = conf ? SWGTurn.artifact(conf, tp, vkLink) : null;
      // app badge: cacggghp = no app → "Turn proxy app"; a branded name → that name; otherwise "{fork} app"
      var appInfo = (forkId === "cacggghp") ? { badge: t("turnApp"), kind: "none" }
                  : (art && art.app) ? { badge: art.app, kind: "app", app: art.app }
                  : { badge: t("forkApp").replace("{fork}", forkId), kind: "fork", fork: forkId };
      // badge = just the fork when it has no branded app name (cacggghp, or a generic fork that echoes its own id
      // like Moroka8); "fork · App" when there's a real app name (WINGS V, FreeTurn, WireGuard-TURN, VK TURN Proxy)
      var hasAppName = forkId !== "cacggghp" && art && art.app && art.app !== forkId;
      var badgeText = hasAppName ? (forkId + " · " + art.app) : forkId;
      var tag = el("span", "scell-tag", badgeText);
      tag.style.color = fc;
      srvRow.appendChild(tag);
      // role + interface next to the badge: multi → "Primary/Backup WG"; single → "WG". Primary/single = iface colour, backup = grey.
      var ifaceUp = (tgt.type === "awg") ? "AWG" : "WG";
      var isBackup = multi && !tgt.primary;
      var role = el("span", "scell-role" + (isBackup ? " scell-backup" : ""), (multi ? (tgt.primary ? t("primary") : t("backup")) + " " : "") + ifaceUp);
      if (!isBackup) role.style.color = ifaceColor(tgt.type);
      srvRow.appendChild(role);
      if (!conf) { draw(); return { el: cell, ctrl: ctrl }; }
      // VK-link notice (freeturn/samosvalishe forks): lives in the cell, positioned by syncVHints BETWEEN the
      // up-arrow and the box (the up-arrow moves up to make room). Same slot for the "no VK link" warning.
      if (art.vkMissing) {
        var vkw2 = el("div", "scell-vk scell-vkwarn");
        vkw2.appendChild(el("div", "scell-vkwarn-t", t("vkMissingT")));
        vkw2.appendChild(el("div", "scell-vkwarn-d", t("vkMissing").replace("{app}", t("theApp"))));
        cell.appendChild(vkw2);
      } else if (art.vk) {
        var raw = (vkLink || "").trim();
        var vkw = el("div", "scell-vk");
        var vkLbl = (appInfo.kind === "none") ? t("vkAddGeneric")
                  : (appInfo.kind === "app") ? t("vkAddApp").replace("{app}", appInfo.app)
                  : t("vkAddFork").replace("{fork}", appInfo.fork);
        vkw.appendChild(el("span", "scell-vklbl", vkLbl));
        var vkb = el("button", "scell-vkbtn", raw); vkb.title = t("tapCopy");
        vkb.onclick = function () { (navigator.clipboard ? navigator.clipboard.writeText(raw) : Promise.reject()).then(function () { var o = raw; vkb.textContent = t("copied"); setTimeout(function () { vkb.textContent = o; }, 1400); }, function () {}); };
        vkw.appendChild(vkb);
        cell.appendChild(vkw);
      }
      var apply = function (text) {
        ctrl.payload = text; ctrl.ready = true; ctrl.ext = art.ext || "conf";
        ctrl.isLink = !!art.uri; ctrl.hasQR = !!art.qr; ctrl.cmd = art.cmd || null;
        ctrl.view = art.qr ? "qr" : "text";   // anything scannable (incl. dual config + command) opens on the QR
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

  var hint = function (cls, dir) { var s = el("span", cls); s.setAttribute("aria-hidden", "true"); s.appendChild(chevronEl(dir)); return s; };

  // ── ONE (peer, protocol) as a full-viewport page: title · a horizontal swipe row of the peer's deployment
  //    cells (servers for WG/AWG, forks for TURN) · the fixed icon action bar (acts on the visible cell). The
  //    vertical pager stacks these grouped by protocol, so up/down walks peer→peer and left/right walks a
  //    peer's deployments. Returns null if this peer has no deployment in `mode`. ──
  var _relayoutRail = null;   // render() points this at its alignRail so a page's layout pass can re-centre the icon rail
  function peerProtoPage(mode, row, vkLink, userName) {
    var peer = row.peer, secret = row.secret, items = [];
    if (mode === "turn") {
      (peer.targets || []).forEach(function (tt) {
        var seen = {}, tps = [], isAwg = (tt.type === "awg");
        (tt.turn || []).forEach(function (tp) { var f = SWGTurn.fork(tp.service); if (seen[f]) return;
          if (isAwg && TURN_WG_ONLY[f]) return;   // a WireGuard-only fork can't front this AmneziaWG interface
          seen[f] = 1; tps.push({ tp: tp, f: f }); });
        tps.sort(function (a, b) { return forkRank(a.f) - forkRank(b.f); });   // canonical fork order (as in the panel)
        tps.forEach(function (x) { items.push({ tgt: tt, tp: x.tp }); });
      });
    } else {
      (peer.targets || []).forEach(function (tt) { if ((tt.type === "awg") === (mode === "awg")) items.push({ tgt: tt }); });
    }
    if (!items.length) return null;
    var reason = row.bad ? t("outOfDate") : (!peer.sec ? t("notReady") : null);

    var page = el("section", "ppage");
    page.setAttribute("data-mode", mode);
    var head = el("div", "ppage-head");
    var titleEl = el("span", "ppage-title", (peer.title || t("peer")) + " ");
    var srvEl = el("span", "ppage-srv");   // "· edge-1" in the server colour — updated per deployment by syncBar
    titleEl.appendChild(srvEl); head.appendChild(titleEl);
    // deployment nav row (only when >1 deployment): the dots flanked by left/right hint arrows — the LEFT/RIGHT
    // SWIPE walks the deployments; the arrows are graphical hints (non-interactive), each fading at its end.
    var dotEls = [], sL, sR;
    if (items.length > 1) {
      var navrow = el("div", "navrow");
      var dots = el("div", "ppage-dots"); for (var i = 0; i < items.length; i++) { var d = el("span", "pdot"); dotEls.push(d); dots.appendChild(d); }
      navrow.appendChild(dots);   // the dots stay by the peer name; the L/R arrows move to the screen edges
      head.appendChild(navrow);
      sL = hint("navarrow navarrow-l", "l"); sR = hint("navarrow navarrow-r", "r");
      page.appendChild(sL); page.appendChild(sR);   // screen-edge arrows, vertically centred on the box by syncVHints
    }
    page.appendChild(head);

    var srow = el("div", "srow");
    var ctrls = items.map(function (it) { var cc = makeCell(userName, peer, it, mode, secret, vkLink, reason, items.length > 1); srow.appendChild(cc.el); return cc.ctrl; });
    page.appendChild(srow);

    // up/down swipe HINT (vertical, between peers) — flanks the QR top/bottom; render hides the ends.
    var vUp = hint("vhint vhint-u", "u"), vDown = hint("vhint vhint-d", "d");
    page.appendChild(vUp); page.appendChild(vDown);

    var bar = el("div", "pbar");
    var toggle = iconBtn("pbtn ico", "doc", t("showConfig"));
    var copyB = iconBtn("pbtn ico", "copy", t("copyConfig"));
    var dlB = iconBtn("pbtn ico", "download", t("download"));
    var shareB = iconBtn("pbtn ico", "share", t("share"));
    bar.appendChild(toggle); bar.appendChild(copyB); bar.appendChild(dlB); bar.appendChild(shareB);
    page.appendChild(bar);

    var curIdx = 0;
    function cur() { return ctrls[curIdx]; }
    function flashIcon(btn, base, label) { setIcon(btn, "check", t("copied")); setTimeout(function () { setIcon(btn, base, label); }, 1400); }
    // Keep the up/down hints an IDENTICAL gap from the visible content box, whatever its size — so a taller
    // config (e.g. AWG with the full S1–I5 ranges) pushes them out exactly as the QR does. Measured live.
    var VH_GAP = 16, VH_GAP_CFG = 8;   // arrow↔box gap — normal for a QR, tighter for a config (arrows hug it)
    // One layout pass for the vertical stack around the content box (QR / config / turn link):
    //   [ name block ] — G — [ up arrow ] — VH_GAP — [ content ] — VH_GAP — [ down arrow ] — G — [ buttons ]
    // The content stays centred; the up/down arrows keep a fixed gap off its edges (so a big config pushes them
    // out); and the name block (peer title + server name) is placed so the gap above the up-arrow EQUALS the gap
    // below the down-arrow — everything reflows as the box grows/shrinks. Skipped in the landscape/desktop flow.
    function syncVHints() {
      var cellEl = srow.children[curIdx] || srow.children[0];
      var stage = cellEl && cellEl.querySelector(".scell-stage");
      var content = stage && stage.querySelector(".qrbox, .textwrap, .cfg-fail");   // .textwrap wraps 1–2 config blocks
      if (!content) return;
      // a QR (or QR+command) keeps the normal arrow gap; a plain config gets a tighter one (arrows hug it)
      var isQR = content.classList.contains("qrbox") || (content.querySelector && !!content.querySelector(".qrbox"));
      var vg = isQR ? VH_GAP : VH_GAP_CFG;
      var pr = page.getBoundingClientRect();
      var uH = vUp.offsetHeight || 27, dH = vDown.offsetHeight || 27;

      // Desktop / landscape scrolls as a normal document — restore FULL in-flow layout (CSS handles the rest); the
      // up/down chevrons are hidden (CSS), and the L/R deployment buttons are centred on the content column.
      if (window.matchMedia && window.matchMedia("(orientation: landscape)").matches) {
        head.style.top = ""; head.style.gap = ""; head.style.paddingTop = "";
        vUp.style.left = ""; vDown.style.left = ""; vUp.style.top = ""; vDown.style.top = "";
        Array.prototype.forEach.call(srow.children, function (c) {   // clear ALL portrait inline positioning on every cell
          var st = c.querySelector(".scell-stage"); if (st) { st.style.alignItems = ""; st.style.paddingTop = ""; }
          var n = c.querySelector(".scell-node"); if (n) n.style.top = "";
          var k = c.querySelector(".scell-vk"); if (k) k.style.top = "";
          var w = c.querySelector(".textwrap"); if (w) w.style.gap = "";
        });
        if (sL && sR) {   // centre the nav buttons on the CURRENT cell's content (QR / config, incl. the client command)
          var sc = stage.getBoundingClientRect();
          var midY = Math.round(sc.top - pr.top + sc.height / 2);
          sL.style.top = midY + "px"; sR.style.top = midY + "px"; sL.style.left = ""; sR.style.left = "";
        }
        return;
      }

      // Portrait: distribute EVERY content line evenly between the two screen edges. Each visible line — up-arrow,
      // peer+server title, deployment dots, app tag, VK notice, the config/QR box, the client command — gets the SAME
      // gap G above and below (incl. the outer margins to the edges). Two pairs stay intentionally tight: the VK
      // notice's own two lines, and the command's label+box. G is solved from the room left after the fixed-height
      // lines; the config box is the one element that resizes (font-fit) so the whole column fits.
      var node = cellEl.querySelector(".scell-node");
      var vk = cellEl.querySelector(".scell-vk");
      var hasVk = vk && getComputedStyle(vk).display !== "none";
      // the box and its parts (config vs. sidecar command)
      var isTextwrap = content.classList.contains("textwrap");
      var configEl = content.classList.contains("qrbox") ? content
                   : ((content.querySelector && (content.querySelector(".qrbox") || content.querySelector(".cfgtext:not(.cmdtext)"))) || content);
      var isQRbox = !!(configEl.classList && configEl.classList.contains("qrbox"));
      var cmdEl = content.querySelector ? content.querySelector(".cmdblk") : null;
      // the head holds [ title , (dots) ] — measure them apart so title↔dots also gets G
      var titleEl2 = head.querySelector(".ppage-title"), navrow2 = head.querySelector(".navrow");
      var titleH = titleEl2 ? titleEl2.offsetHeight : head.offsetHeight;
      var hasDots = !!navrow2, dotsH = hasDots ? navrow2.offsetHeight : 0;
      var tagH = node ? node.offsetHeight : 0, hasTag = tagH > 2;
      var vkH = hasVk ? vk.offsetHeight : 0;
      var cmdH = cmdEl ? cmdEl.offsetHeight : 0, hasCmd = cmdH > 0;
      var uShown = vUp.style.display !== "none", dShown = vDown.style.display !== "none";
      var barTop = bar.getBoundingClientRect().top - pr.top;
      var GAP_MIN = 8;

      var nEl = 2 /* title + config */ + (uShown ? 1 : 0) + (dShown ? 1 : 0) + (hasDots ? 1 : 0) + (hasTag ? 1 : 0) + (hasVk ? 1 : 0) + (hasCmd ? 1 : 0);
      var nGaps = nEl + 1;
      var fixedH = (uShown ? uH : 0) + titleH + (hasDots ? dotsH : 0) + (hasTag ? tagH : 0) + (hasVk ? vkH : 0) + (hasCmd ? cmdH : 0) + (dShown ? dH : 0);

      // fit the CONFIG alone (not the command) to what's left after GAP_MIN on every gap
      stage.style.alignItems = "flex-start";
      if (isTextwrap) content.style.maxHeight = "";                              // the wrap is natural height; only the config is capped
      var configCap = Math.max(48, barTop - fixedH - GAP_MIN * nGaps);
      if (!isQRbox && configEl.classList && configEl.classList.contains("cfgtext")) {
        configEl.style.maxHeight = configCap + "px";
        fitText(configEl);
        if (configEl.style.fontSize && ctrls[curIdx]) ctrls[curIdx].cfgFont = configEl.style.fontSize;   // QR view's command matches
      }
      var configH = Math.min(configEl.offsetHeight, configCap);
      var G = Math.max(GAP_MIN, Math.floor((barTop - fixedH - configH) / nGaps));   // the one gap that makes ALL lines equal

      // walk the stack top→bottom, giving every line the same gap G
      var cellTop = cellEl.getBoundingClientRect().top - pr.top;                  // VK + tag are absolute WITHIN the cell
      var y = G, upTop = null, headTop, tagTopP = null, vkTopP = null, configTop, boxBottom, downTop = null;
      if (uShown) { upTop = y; y += uH + G; }
      headTop = y; y += titleH; if (hasDots) y += G + dotsH;
      if (hasTag) { y += G; tagTopP = y; y += tagH; }
      if (hasVk) { y += G; vkTopP = y; y += vkH; }
      y += G; configTop = y; y += configH;
      if (hasCmd) y += G + cmdH;
      boxBottom = y;
      if (dShown) { y += G; downTop = y; }

      head.style.paddingTop = "0px"; head.style.gap = G + "px"; head.style.top = Math.round(headTop) + "px";
      if (isTextwrap) content.style.gap = G + "px";                              // config↔command gap = G
      if (hasTag) { var nt = Math.round(tagTopP - cellTop); Array.prototype.forEach.call(srow.children, function (c) { var n = c.querySelector(".scell-node"); if (n) n.style.top = nt + "px"; }); }
      if (hasVk) vk.style.top = Math.round(vkTopP - cellTop) + "px";
      if (uShown) vUp.style.top = Math.round(upTop) + "px";
      if (dShown) vDown.style.top = Math.round(downTop) + "px";
      // nudge the stage's top padding so the config's TOP lands at configTop (converges over the few layout passes)
      var curTop = configEl.getBoundingClientRect().top - pr.top;
      var curPad = parseFloat(stage.style.paddingTop) || 0;
      stage.style.paddingTop = Math.max(0, Math.round(curPad + configTop - curTop)) + "px";
      // centre the up/down arrows over the config box; the L/R deployment arrows sit at the vertical mid of the stack
      var cr2 = configEl.getBoundingClientRect();
      var aCx = Math.round((cr2.left + cr2.right) / 2 - pr.left);
      vUp.style.left = aCx + "px"; vDown.style.left = aCx + "px";
      if (sL && sR) {
        var topRef = uShown ? (upTop + uH) : 0, botRef = dShown ? downTop : boxBottom;
        var midY = Math.round((topRef + botRef) / 2 + (botRef - topRef) * 0.1);   // a touch below centre
        sL.style.top = midY + "px"; sR.style.top = midY + "px";
      }
    }
    function scheduleVH() {
      var run = function () { syncVHints(); if (_relayoutRail) _relayoutRail(); };   // rail re-centres right after the box is placed
      requestAnimationFrame(run); setTimeout(run, 90); setTimeout(run, 220);          // rAF + catch the async config re-fit
    }
    function syncBar() {
      var c = cur();
      if (c.srvName) { srvEl.textContent = "· " + c.srvName; srvEl.style.color = c.srvColor || ""; }   // "iPhone · edge-1"
      // buttons keep FIXED positions — a hidden one reserves its slot (visibility:hidden)
      var showToggle = c.ready && c.hasQR;
      toggle.style.visibility = showToggle ? "" : "hidden";
      if (showToggle) { var q = (c.view === "qr"); setIcon(toggle, q ? "doc" : "qr", q ? (c.isLink ? t("showLink") : t("showConfig")) : t("showQR")); }
      var v = (c.ready && c.payload) ? "" : "hidden";
      copyB.style.visibility = v; dlB.style.visibility = v; shareB.style.visibility = v;
      for (var i = 0; i < dotEls.length; i++) dotEls[i].className = "pdot" + (i === curIdx ? " on" : "");
      if (sL) { sL.style.opacity = (curIdx <= 0) ? "0" : ""; sR.style.opacity = (curIdx >= items.length - 1) ? "0" : ""; }
      scheduleVH();
    }
    ctrls.forEach(function (cc) { cc.notify = function () { if (ctrls[curIdx] === cc) syncBar(); }; });
    toggle.onclick = function () { var c = cur(); if (!c.hasQR) return; c.view = (c.view === "qr") ? "text" : "qr"; c.redraw(); syncBar(); };
    copyB.onclick = function () { var c = cur();
      if (c.view === "qr" && c.qrUrl) { copyImage(c.qrUrl, null); flashIcon(copyB, "copy", t("copyConfig")); }
      else (navigator.clipboard ? navigator.clipboard.writeText(c.payload) : Promise.reject()).then(function () { flashIcon(copyB, "copy", t("copyConfig")); }, function () {});
    };
    dlB.onclick = function () { var c = cur(); var nm = c.base + (mode === "turn" ? "-turn" : ""); if (c.view === "qr" && c.qrUrl) downloadImage(c.qrUrl, nm); else download(c.payload, nm, c.ext || "conf"); };
    shareB.onclick = function () { var c = cur(); var nm = c.base + (mode === "turn" ? "-turn" : "") + "." + (c.ext || "conf");
      if (navigator.share) {
        try { var f = new File([c.payload], nm, { type: "text/plain" });
          if (navigator.canShare && navigator.canShare({ files: [f] })) { navigator.share({ files: [f], title: nm }).catch(function () {}); return; }
        } catch (_) {}
        navigator.share({ title: nm, text: c.payload }).catch(function () {}); return;
      }
      (navigator.clipboard ? navigator.clipboard.writeText(c.payload) : Promise.reject()).then(function () { flashIcon(shareB, "share", t("share")); }, function () {});
    };

    function current() { var sl = srow.scrollLeft, best = 0, bd = Infinity; for (var i = 0; i < srow.children.length; i++) { var dd = Math.abs((srow.children[i].offsetLeft - srow.offsetLeft) - sl); if (dd < bd) { bd = dd; best = i; } } return best; }
    var raf = 0;
    srow.addEventListener("scroll", function () { if (raf) return; raf = requestAnimationFrame(function () { raf = 0; var i = current(); if (i !== curIdx) { curIdx = i; syncBar(); } else syncVHints(); }); }, { passive: true });
    dotEls.forEach(function (d, i) { d.onclick = function () { srow.scrollTo({ left: srow.children[i].offsetLeft - srow.offsetLeft, behavior: "smooth" }); }; });
    if (sL && sR) {   // the edge arrows are clickable nav buttons (used in the landscape/desktop layout; harmless in portrait)
      var goCell = function (dir) { var i = current(), j = Math.max(0, Math.min(i + dir, srow.children.length - 1));
        if (j !== i) srow.scrollTo({ left: srow.children[j].offsetLeft - srow.offsetLeft, behavior: "smooth" }); };
      sL.onclick = function () { goCell(-1); }; sR.onclick = function () { goCell(1); };
    }
    try { new ResizeObserver(scheduleVH).observe(srow); } catch (_) {}   // viewport / rotation → re-measure the hint gap
    setTimeout(syncBar, 0);
    // Position snapshot/restore so a language or theme switch (which rebuilds every page) can drop the user back
    // onto the SAME deployment + QR/config view they were reading — not the first config.
    page._pos = function () { return { cell: curIdx, view: ctrls[curIdx] ? ctrls[curIdx].view : null }; };
    page._seek = function (cell, view) {
      cell = Math.max(0, Math.min(cell | 0, srow.children.length - 1));
      curIdx = cell;
      var c = ctrls[cell];
      if (c && view && c.hasQR && c.view !== view) { c.view = view; if (c.redraw) c.redraw(); }
      var target = srow.children[cell];
      if (target) srow.scrollLeft = target.offsetLeft - srow.offsetLeft;
      syncBar();
    };
    return page;
  }

  function render(data, cryptoKey, keepPos) {
    _lastData = data; _lastKey = cryptoKey;
    LANGS = (data.langs && data.langs.enabled && data.langs.enabled.length) ? data.langs.enabled : ["en"];
    LANG_DEFAULT = (data.langs && data.langs.default) || "en";
    resolveLang(); wireControls(); paintCtl();     // the admin controls which languages are offered + the default
    THEME.color = data.theme_color || ""; THEME.light = data.theme_color_light || "";
    THEME.forkOv = data.turn_fork_colors || {}; THEME.ifaceOv = data.iface_colors || {};   // panel colour overrides
    THEME.nodeOv = data.node_colors || {};   // per-node server colours
    applyBrand();                                    // logo + favicon follow the panel's theme colour
    var who = document.getElementById("who");
    who.textContent = data.user && data.user.name ? data.user.name : "";
    // BLOCKED user: logo (header brand) + username (header "who") stay; the body is a single centered
    // "Subscription disabled" message — no peers, tabs, or QRs. Reversible from the panel (unblock).
    if (data.disabled) {
      document.getElementById("peers").hidden = true;
      showState(t("subDisabled"), t("subDisabledSub"));
      return Promise.resolve();
    }
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
      // Which protocol groups apply: WG/AWG if ≥1 deployment of that type; TURN only when the feature is on AND
      // ≥1 deployment has a proxy forwarding to it (same gate as the admin view).
      var has = { wg: false, awg: false, turn: false };
      rows.forEach(function (r) { (r.peer.targets || []).forEach(function (t) {
        has[t.type === "awg" ? "awg" : "wg"] = true;
        if (data.turn_enabled && (t.turn || []).length) has.turn = true;
      }); });
      var groups = ["wg", "awg", "turn"].filter(function (m) { return has[m]; });
      if (!groups.length) { showState(t("noConfigs"), t("noConfigsSub")); return; }

      // ONE flat vertical pager through EVERY config, grouped by protocol: all WG, then all AWG, then all Turn.
      // The mode buttons don't switch views — each JUMPS to the first page of its group; the group whose page is
      // in view is highlighted and its button disabled (you're already there).
      var bar = el("div", "modebar"), pager = el("div", "pager"), btns = {}, firstOf = {};
      var pinMode = null, pinTimer = 0;
      function highlight(cur) { groups.forEach(function (m) { var on = (m === cur); btns[m].className = "modetab" + (on ? " on" : ""); btns[m].disabled = on; }); }
      groups.forEach(function (mode) {
        var b = el("button", "modetab"); b.type = "button"; b.title = t(mode); b.setAttribute("aria-label", t(mode));
        b.appendChild(protoIcon(mode));
        var mc = modeColor(mode); b.style.setProperty("--mc", mc); b.style.setProperty("--mc-ink", hexLum(mc) > 0.6 ? "#06222a" : "#EAFBFF");
        b.onclick = function () {
          pinMode = mode; highlight(mode);                                       // highlight NOW, don't wait for the scroll
          var f = firstOf[mode]; if (f) f.scrollIntoView({ behavior: "smooth", block: "start" });
          // Hold the pin until the smooth-scroll actually LANDS on this group (syncGroup releases it) — a fixed timer
          // would drop the pin mid-flight and briefly light up whichever group the scroll is passing through.
          clearTimeout(pinTimer); pinTimer = setTimeout(function () { pinMode = null; syncGroup(); }, 1500);   // safety fallback only
        };
        btns[mode] = b; bar.appendChild(b);
      });
      groups.forEach(function (mode) {
        rows.forEach(function (row) {
          var pg = peerProtoPage(mode, row, vkLink, userName);
          if (pg) { if (!firstOf[mode]) firstOf[mode] = pg; pager.appendChild(pg); }
        });
      });
      if (!pager.children.length) { showState(t("noConfigs"), t("noConfigsSub")); return; }
      if (groups.length > 1) wrap.appendChild(bar);
      wrap.appendChild(pager);

      var pages = Array.prototype.slice.call(pager.children);
      // up/down hint per page: hint both directions, except no "up" on the first page and no "down" on the last
      // (a lone page hints neither). left/right hints are handled inside the page (per deployment).
      pages.forEach(function (pg, i) {
        var u = pg.querySelector(".vhint-u"), d = pg.querySelector(".vhint-d");
        if (u) u.style.display = (pages.length > 1 && i > 0) ? "" : "none";
        if (d) d.style.display = (pages.length > 1 && i < pages.length - 1) ? "" : "none";
      });

      // Highlight + disable the button for the protocol group whose page is at the top. Viewport-relative rects
      // so it works whether the PAGER scrolls (phone) or the WINDOW does (desktop).
      // Sit the fixed left rail so its vertical centre lines up with the QR/config box of the page in view — not
      // the viewport centre (the header pushes the QR below it). All pages share a layout, so the current one's
      // box is representative; re-run on scroll/resize since a QR↔config toggle can change the box height.
      function alignRail() { /* icon row is static now — nothing to reposition */ }
      _relayoutRail = alignRail;   // let a page's layout pass (QR↔config toggle, fit, swipe) re-centre the rail
      function syncGroup() {
        // highlight the group of the page actually in view (the top-most visible one — same logic as paging)
        var pg = pages[curIndex()];
        var mode = pg ? pg.getAttribute("data-mode") : (pages[0] ? pages[0].getAttribute("data-mode") : groups[0]);
        if (pinMode) {
          if (mode === pinMode) { pinMode = null; clearTimeout(pinTimer); }   // scroll arrived → release the pin
          else { highlight(pinMode); return; }                                // still travelling → keep the target lit
        }
        highlight(mode);
      }
      var raf = 0, navLock = false;
      function curIndex() {
        // portrait: the PAGER is the scroll container, so measure against its top. landscape/desktop: the WINDOW
        // scrolls, so measure against a fixed point just below the sticky header (in viewport coords).
        var pagerScrolls = getComputedStyle(pager).overflowY !== "visible";
        var top = pagerScrolls ? (pager.getBoundingClientRect().top + 6) : 80;
        for (var i = 0; i < pages.length; i++) { if (pages[i].getBoundingClientRect().bottom > top) return i; }
        return pages.length - 1;
      }
      // Step exactly ONE peer up/down (shared by the vertical swipe + wheel). A lock during the animation stops a
      // fling from chaining.
      function stepConfig(dir) {
        if (navLock) return;
        navLock = true; setTimeout(function () { navLock = false; }, 460);
        var i = curIndex(), j = Math.max(0, Math.min(i + dir, pages.length - 1));
        if (j !== i) pages[j].scrollIntoView({ behavior: "smooth", block: "start" });
      }
      // Step exactly ONE deployment left/right in the CURRENT page's carousel (mirrors stepConfig for the
      // horizontal axis) — so a fast flick advances one server/fork, not three.
      function stepCell(dir) {
        if (navLock) return;
        var pg = pages[curIndex()]; if (!pg) return;
        var srow = pg.querySelector(".srow"); if (!srow) return;
        var cells = srow.children; if (cells.length < 2) return;
        var sl = srow.scrollLeft, cur = 0, bd = Infinity;
        for (var i = 0; i < cells.length; i++) { var d = Math.abs((cells[i].offsetLeft - srow.offsetLeft) - sl); if (d < bd) { bd = d; cur = i; } }
        var j = Math.max(0, Math.min(cur + dir, cells.length - 1));
        if (j === cur) return;
        navLock = true; setTimeout(function () { navLock = false; }, 460);
        srow.scrollTo({ left: cells[j].offsetLeft - srow.offsetLeft, behavior: "smooth" });
      }

      function onScroll() { if (raf) return; raf = requestAnimationFrame(function () { raf = 0; syncGroup(); }); }
      pager.addEventListener("scroll", onScroll, { passive: true });
      window.addEventListener("scroll", onScroll, { passive: true });
      window.addEventListener("resize", onScroll, { passive: true });
      // Restore the reader's place (deployment + QR/config view + which page) after a lang/theme rebuild — BEFORE
      // the first syncGroup so nothing flashes the top config first.
      if (keepPos && pages.length) {
        var kp = Math.max(0, Math.min(keepPos.page | 0, pages.length - 1));
        var kpg = pages[kp];
        if (kpg && kpg._seek) kpg._seek(keepPos.cell, keepPos.view);
        kpg.scrollIntoView({ block: "start" });   // instant (no smooth) — land, don't animate from the top
      }
      syncGroup();
      requestAnimationFrame(syncGroup);   // re-sync once laid out
      setTimeout(alignRail, 120);         // catch the QR's async first paint

      // ── Deliberate VERTICAL paging (phone): a fling can skip several peers, so take over vertical touch/wheel
      //    and step EXACTLY ONE peer per FIRM gesture. HORIZONTAL gestures are left to the deployment carousel
      //    (native scroll-snap), so left/right still swipes a peer's servers/forks. ──
      var isPager = getComputedStyle(pager).overflowY !== "visible";   // phone: the pager scrolls (desktop scrolls the window → leave native)
      if (isPager) {
        var scrollableUnder = function (node) {   // a config-text box that itself needs scrolling — let it, don't page
          for (var n = node; n && n !== pager; n = n.parentNode) {
            if (n.classList && n.classList.contains("cfgtext") && n.scrollHeight > n.clientHeight + 2) return true;
          }
          return false;
        };
        var tX = 0, tY = 0, tT = 0, tAxis = null, tOwn = false;
        pager.addEventListener("touchstart", function (e) { tOwn = !scrollableUnder(e.target); tAxis = null; tX = e.touches[0].clientX; tY = e.touches[0].clientY; tT = Date.now(); }, { passive: true });
        pager.addEventListener("touchmove", function (e) {
          if (!tOwn) return;
          var dx = e.touches[0].clientX - tX, dy = e.touches[0].clientY - tY;
          if (tAxis === null && (Math.abs(dx) > 8 || Math.abs(dy) > 8)) tAxis = (Math.abs(dx) > Math.abs(dy)) ? "h" : "v";
          if (tAxis) e.preventDefault();   // take over BOTH axes — step exactly one config/deployment on release
        }, { passive: false });
        pager.addEventListener("touchend", function (e) {
          if (!tOwn || !tAxis) return;
          var dt = Date.now() - tT;
          if (tAxis === "v") {
            var dy = e.changedTouches[0].clientY - tY, vel = Math.abs(dy) / Math.max(1, dt);
            if (Math.abs(dy) > 85 || (Math.abs(dy) > 45 && vel > 0.7)) stepConfig(dy < 0 ? 1 : -1);   // FIRM swipe only
          } else {
            var dx = e.changedTouches[0].clientX - tX, velx = Math.abs(dx) / Math.max(1, dt);
            if (Math.abs(dx) > 75 || (Math.abs(dx) > 40 && velx > 0.7)) stepCell(dx < 0 ? 1 : -1);   // FIRM swipe → ONE deployment
          }
        }, { passive: false });
        var wAcc = 0, wT = 0, hAcc = 0, hT = 0;
        pager.addEventListener("wheel", function (e) {
          if (scrollableUnder(e.target)) return;
          e.preventDefault();
          if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) {   // horizontal wheel → step ONE deployment (no fling-skip)
            var nx = Date.now(); if (nx - hT > 180) hAcc = 0; hT = nx;
            hAcc += e.deltaX;
            if (Math.abs(hAcc) > 120) { stepCell(hAcc > 0 ? 1 : -1); hAcc = 0; }
            return;
          }
          var now = Date.now(); if (now - wT > 180) wAcc = 0; wT = now;
          wAcc += e.deltaY;
          if (Math.abs(wAcc) > 120) { stepConfig(wAcc > 0 ? 1 : -1); wAcc = 0; }
        }, { passive: false });
      }

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
