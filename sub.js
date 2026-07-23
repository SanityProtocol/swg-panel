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
      peer: "Peer", primary: "Primary", download: "Download .conf", dl: "Download", copyConfig: "Copy config",
      copied: "Copied", copiedClip: "Copied to clipboard", copyFailed: "Copy failed", showConfig: "Show config text", showLink: "Show link", showQR: "Show QR",
      dlShort: "Download", enlarge: "Tap to enlarge", share: "Share",
      getApp: "Get {app}", getAppBy: "Get {app} by {author} manually", getAppManual: "Get {app} manually",
      getWgClient: "WireGuard clients", getAwgClient: "AmneziaWG clients",
      dlOpenPage: "Open {host}({app}) downloads page", dlLatest: "Latest release · {ver}",
      start: "Start", startOpen: "Start — opens {app}", startGet: "Start — installs {app} if you don't have it",
      startHow: "Open the app, or install it?", startOpenApp: "Open {app}", startHaveIt: "I already have it", startGetApp: "Get {app}", startNeedIt: "Install it",
      importHint1: "Once the app opens:", importHint2: "1. Go to ", importHint3: "2. Tap ", appOpening: "App is opening in {n}…",
      vpnCopied: "Link copied — paste it into Amnezia VPN",
      cmdCopied: "Command copied", vkCopied: "VK link copied — paste it in the app",
      pasteStep1: "1. Open ", pasteStep2: "2. Paste the copied connection link", pasteStep3: "3. Click ",
      pasteConnect: "Connect", pasteDownload: "Download the app here", amneziaDownloads: "AmneziaVPN downloads",
      mzGetConfig: "Download the config here", cliGetClient: "Download the client here", cliDownBy: "Download the binary by {author}", cliNative: "native",
      cliSteps: { linux:   ["1. Download the client", "2. Make it executable (chmod +x)", "3. Open a *terminal* in that directory", "4. Paste and run the command", "5. Wait for success and start *WG*"],
                  macos:   ["1. Download the client", "2. Make it executable (chmod +x)", "3. If blocked, right-click → *Open*", "4. Open *Terminal* in that directory", "5. Paste and run the command", "6. Wait for success and start *WG*"],
                  windows: ["1. Download the client", "2. Open *PowerShell* in that directory", "3. Paste and run the command", "4. Wait for success and start *WG*"],
                  android: ["1. Install *Termux* from *F-Droid*", "2. Run termux-setup-storage", "3. Download the client", "4. Make it executable (chmod +x)", "5. Paste and run the command", "6. Wait for success and start *WG*"] },
      linkCopied: "Connection link copied",
      wtDownloaded: "Config file downloaded", wtStep1: "1. Open the WG Turn app", wtStep2a: "2. Click on the ", wtStep2b: " button",
      wtStep3: "3. Select “Import from file or archive”", wtStep4: "4. Locate the downloaded .conf file", wtStep5: "5. Flip the connection toggle",
      mzBtn1: "Download the GUI app", mzBtn2: "Install TURN Proxy core", mzBtn3: "Assemble and connect", mzBtn3Sub: "Follow the instructions",
      mzCopied: "Config string copied", mzGetCore: "Don't forget to download the core",
      mzStep1: "1. Open the *TURN Proxy* app", mzStep2: "2. Go to *Settings*", mzStep3: "3. Click on *Core (Binary)*", mzStep4: "4. Press *Import*",
      mzStep5: "5. Locate the downloaded core file", mzStep6: "6. Click on *Profiles and Backup*", mzStep7: "7. Click *Import* → *From clipboard*",
      mzStep8: "8. Go to *Main*", mzStep9: "9. Click *CONNECT*", mzStep10: "10. Wait for success and start *WG*", mzStep11: "11. *Exclude Private IPs* and *TURN Proxy* app",
      clientCmd: "Client command", generating: "Generating…", qrTooBig: "config too large to encode as QR",
      cantGen: "couldn’t generate this link", tapCopy: "Tap to copy",
      vkAddApp: "Add this VK call link to {app}", vkAddFork: "Add this VK call link to {fork} app",
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
      subDisabledSub: "This subscription has been turned off. Please contact your administrator.",
      subBlockedWord: "BLOCKED", subExpiredWord: "EXPIRED",
      subExpiredSub: "This subscription has expired. Please contact your administrator.",
      err: "Something went wrong", errServer: "Couldn’t load this subscription (server error). Please try again later.",
      errNet: "Couldn’t load this subscription. Check your connection and try again.",
      errResp: "The server returned an unexpected response.",
      unsupported: "Unsupported browser",
      unsupportedSub: "This page needs a modern browser with Web Crypto (and a secure https:// connection) to decrypt your configs.",
      wg: "WireGuard", awg: "AmneziaWG", turn: "Turn", turnApp: "Turn proxy app", forkApp: "{fork} app",
      slowPlain: "Plain — no obfuscation, so slower (may be throttled)",
      langName: "EN", themeToLight: "Switch to light", themeToDark: "Switch to dark", langLabel: "Language", osLabel: "Device / OS",
    },
    ru: {
      loading: "Загрузка…", noConfigs: "Пока нет конфигураций",
      noConfigsSub: "На этой подписке нет активных пиров. Новые появятся здесь автоматически.",
      peer: "Пир", primary: "Основной", download: "Скачать .conf", dl: "Скачать", copyConfig: "Скопировать",
      copied: "Скопировано", copiedClip: "Скопировано в буфер обмена", copyFailed: "Не удалось", showConfig: "Показать текст конфига", showLink: "Показать ссылку", showQR: "Показать QR",
      dlShort: "Скачать", enlarge: "Нажмите, чтобы увеличить", share: "Поделиться",
      getApp: "Установить {app}", getAppBy: "Скачать {app} от {author} вручную", getAppManual: "Установить {app} вручную",
      getWgClient: "Клиенты WireGuard", getAwgClient: "Клиенты AmneziaWG",
      dlOpenPage: "Открыть страницу загрузок {host}({app})", dlLatest: "Последняя версия · {ver}",
      start: "Старт", startOpen: "Старт — откроет {app}", startGet: "Старт — установит {app}, если его нет",
      startHow: "Открыть приложение или установить?", startOpenApp: "Открыть {app}", startHaveIt: "Уже установлено", startGetApp: "Установить {app}", startNeedIt: "Установить",
      importHint1: "Когда приложение откроется:", importHint2: "1. Откройте ", importHint3: "2. Нажмите ", appOpening: "Приложение откроется через {n}…",
      vpnCopied: "Ссылка скопирована — вставьте её в Amnezia VPN",
      cmdCopied: "Команда скопирована", vkCopied: "Ссылка VK скопирована — вставьте её в приложении",
      pasteStep1: "1. Откройте ", pasteStep2: "2. Вставьте скопированную ссылку", pasteStep3: "3. Нажмите ",
      pasteConnect: "Подключиться", pasteDownload: "Скачать приложение здесь", amneziaDownloads: "Загрузки AmneziaVPN",
      mzGetConfig: "Скачать конфиг здесь", cliGetClient: "Скачать клиент здесь", cliDownBy: "Скачать бинарник от {author}", cliNative: "родной",
      cliSteps: { linux:   ["1. Скачайте клиент", "2. Сделайте его исполняемым (chmod +x)", "3. Откройте *терминал* в этой папке", "4. Вставьте и запустите команду", "5. Дождитесь подключения и запустите *WG*"],
                  macos:   ["1. Скачайте клиент", "2. Сделайте его исполняемым (chmod +x)", "3. Если заблокировано — ПКМ → *«Открыть»*", "4. Откройте *Терминал* в этой папке", "5. Вставьте и запустите команду", "6. Дождитесь подключения и запустите *WG*"],
                  windows: ["1. Скачайте клиент", "2. Откройте *PowerShell* в этой папке", "3. Вставьте и запустите команду", "4. Дождитесь подключения и запустите *WG*"],
                  android: ["1. Установите *Termux* из *F-Droid*", "2. Выполните termux-setup-storage", "3. Скачайте клиент", "4. Сделайте его исполняемым (chmod +x)", "5. Вставьте и запустите команду", "6. Дождитесь подключения и запустите *WG*"] },
      linkCopied: "Ссылка для подключения скопирована",
      wtDownloaded: "Файл конфигурации загружен", wtStep1: "1. Откройте приложение WG Turn", wtStep2a: "2. Нажмите кнопку ", wtStep2b: "",
      wtStep3: "3. Выберите «Импорт из файла или архива»", wtStep4: "4. Найдите загруженный файл .conf", wtStep5: "5. Включите переключатель подключения",
      mzBtn1: "Скачать приложение (GUI)", mzBtn2: "Установить ядро TURN Proxy", mzBtn3: "Собрать и подключиться", mzBtn3Sub: "Следуйте инструкциям",
      mzCopied: "Строка конфигурации скопирована", mzGetCore: "Не забудьте скачать ядро",
      mzStep1: "1. Откройте приложение *TURN Proxy*", mzStep2: "2. Перейдите в *«Настройки»*", mzStep3: "3. Нажмите *«Ядро (Binary)»*", mzStep4: "4. Нажмите *«Импорт»*",
      mzStep5: "5. Выберите загруженный файл ядра", mzStep6: "6. Нажмите *«Профили и Бэкап»*", mzStep7: "7. Нажмите *«Импорт»* → *«Из буфера»*",
      mzStep8: "8. Перейдите на *«Главную»*", mzStep9: "9. Нажмите *«ЗАПУСТИТЬ»*", mzStep10: "10. Дождитесь подключения и запустите *WG*", mzStep11: "11. *Исключите приватные IP* и приложение *TURN Proxy*",
      clientCmd: "Команда клиента", generating: "Генерация…", qrTooBig: "конфиг слишком большой для QR",
      cantGen: "не удалось сгенерировать ссылку", tapCopy: "Нажмите, чтобы скопировать",
      vkAddApp: "Добавьте эту ссылку на звонок VK в {app}", vkAddFork: "Добавьте эту ссылку на звонок VK в приложении",
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
      subDisabledSub: "Эта подписка отключена. Обратитесь к администратору.",
      subBlockedWord: "ЗАБЛОКИРОВАНО", subExpiredWord: "ИСТЕКЛО",
      subExpiredSub: "Срок действия этой подписки истёк. Обратитесь к администратору.",
      err: "Что-то пошло не так", errServer: "Не удалось загрузить подписку (ошибка сервера). Попробуйте позже.",
      errNet: "Не удалось загрузить подписку. Проверьте соединение и попробуйте снова.",
      errResp: "Сервер вернул неожиданный ответ.",
      unsupported: "Браузер не поддерживается",
      unsupportedSub: "Для расшифровки конфигов нужен современный браузер с Web Crypto и защищённое соединение https://.",
      wg: "WireGuard", awg: "AmneziaWG", turn: "Turn", turnApp: "Приложение для turn proxy", forkApp: "Приложение {fork}",
      slowPlain: "Без обфускации — медленнее (возможно ограничение скорости)",
      langName: "RU", themeToLight: "Светлая тема", themeToDark: "Тёмная тема", langLabel: "Язык", osLabel: "Устройство / ОС",
    },
  };
  function t(k) { return (STR[LANG] && STR[LANG][k]) || STR.en[k] || k; }
  function servers(n) {
    if (LANG === "ru") { var f = ["сервер", "сервера", "серверов"], a = Math.abs(n) % 100, n1 = a % 10;
      var w = (a > 10 && a < 20) ? f[2] : (n1 > 1 && n1 < 5) ? f[1] : (n1 === 1) ? f[0] : f[2]; return n + " " + w; }
    return n + " " + (n === 1 ? "server" : "servers");
  }

  var AWG_ORDER = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4", "I1", "I2", "I3", "I4", "I5"];
  // Turn-proxy fork display order, wg-only set and colours are driven by the panel's turn_catalog (single source of
  // truth — the keystone). The hardcoded *_FALLBACK values are the last-known set for an OLDER panel that doesn't
  // serve the catalog in the sub bundle yet; catalog-driven is also more CURRENT (the fallback lacks MYSOREZ, which
  // the catalog carries). Mirrors app.js's TURN_FORKS_FALLBACK + turnForkList().
  var FORK_ORDER_FALLBACK = ["cacggghp", "WINGS-N", "samosvalishe", "Moroka8", "kiper292", "anton48"];
  function turnServers() { return (_lastData && _lastData.turn_catalog && _lastData.turn_catalog.servers) || null; }
  function turnServer(f) { var s = turnServers() || []; for (var i = 0; i < s.length; i++) if (s[i].id === f) return s[i]; return null; }
  function forkRank(f) { var s = turnServers(); if (s && s.length) { for (var i = 0; i < s.length; i++) if (s[i].id === f) return i; return s.length; } var j = FORK_ORDER_FALLBACK.indexOf(f); return j < 0 ? FORK_ORDER_FALLBACK.length : j; }
  // WireGuard-only forks (the client can't front AmneziaWG) — from the catalog server's `protocols` (no "awg"); so
  // such a fork isn't offered for an AWG peer. The fallback mirrors the panel's old TURN_WG_ONLY.
  var TURN_WG_ONLY_FALLBACK = { kiper292: 1, anton48: 1, samosvalishe: 1 };
  function turnWgOnly(f) { var s = turnServer(f); if (s && s.protocols) return s.protocols.indexOf("awg") < 0; return !!TURN_WG_ONLY_FALLBACK[f]; }

  // AXIS-3: the client-app install link for a server fork, from the panel's turn_catalog (server → clients[0] →
  // platforms). Returns {app, url, platform} or null when the fork's client has no published app link (e.g. the
  // CLI sidecar forks cacggghp/Moroka8). The catalog rides the sub bundle (_lastData.turn_catalog); missing on an
  // older panel → no link (graceful). "platform" is the store key (android/ios); the value is the download URL.
  // The client-app for the SELECTED OS ONLY — the first curated client (native GUI before cross-fork before CLI)
  // whose app actually runs on the visitor's OS. NEVER falls back to a wrong-OS build (an iPhone must not be offered
  // WINGS V for Android): returns null when no client ships for this OS, so the cell just shows no get-app row.
  // platforms[os] may carry `url` (resolved latest asset) and/or `github` (releases page) — prefer the resolved asset.
  // A peer's targets ordered PRIMARY-first (the one flagged `primary`, else the first), then creation order.
  function orderedTargets(targets) {
    var ts = (targets || []).slice();
    for (var i = 0; i < ts.length; i++) if (ts[i] && ts[i].primary) { ts.unshift(ts.splice(i, 1)[0]); break; }
    return ts;
  }
  // Rank a turn-proxy fork by the class of the client it resolves to for THIS visitor — matching the panel picker:
  // native app · friendly app · native sidecar · friendly sidecar · plain (so the "best" connection sorts first).
  function turnCellRank(forkId) {
    var ga = turnGetApp(forkId); if (!ga) return 9;
    var srv = turnServer(forkId), compat = (srv && srv.compat) || {};
    var isCli = ga.cid === "sidecar" || ga.enc === "sidecar";
    var cls = isCli ? (compat.sidecar || "native") : (compat[ga.cid] || "");
    return cls === "native" ? (isCli ? 3 : 1)
      : (cls === "friendly" || cls === "friendly_core") ? (isCli ? 4 : 2)
      : cls === "plain" ? 5 : 6;
  }
  // Obfuscation-carrying forks (mirrors app.js _FORK_GUI_OBF / _FORK_CLI_OBF): a native/friendly GUI app rides the
  // fork's own wire, and so does its CLI — EXCEPT WINGS, whose wrap needs the app's SessionHello, so its CLI is plain.
  var _TURN_GUI_OBF = { Moroka8: 1, samosvalishe: 1, anton48: 1, MYSOREZ: 1, "WINGS-N": 1 };
  var _TURN_CLI_OBF = { Moroka8: 1, samosvalishe: 1, anton48: 1, MYSOREZ: 1 };
  // Does the client we resolve for THIS visitor connect WITHOUT obfuscation? Plain = the fork's normal transport,
  // which VK throttles → slower. A plain fork (cacggghp/kiper292) is always plain; an obfuscated fork is plain only
  // for a cross-fork "plain"-class client. Same rule as the panel picker, so the turtle matches the admin view.
  function turnCellPlain(forkId) {
    var ga = turnGetApp(forkId); if (!ga || !ga.cid) return false;
    var compat = (turnServer(forkId) || {}).compat || {};
    var isCli = ga.cid === "sidecar";
    var cls = isCli ? (compat.sidecar || "") : (compat[ga.cid] || "");
    var ridesObf = isCli ? !!_TURN_CLI_OBF[forkId]
                         : ((cls === "native" || cls === "friendly" || cls === "friendly_core") && !!_TURN_GUI_OBF[forkId]);
    return !ridesObf;
  }
  // A turtle (warning-orange) marks a plain/slow connection on the cell badge. Monochrome SVG so it takes the CSS
  // `color` via fill=currentColor — an emoji couldn't be recoloured. Side profile: dome shell · head · legs · tail.
  var TURTLE_SVG = '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor" aria-hidden="true">'
    + '<path d="M3.5 14.2c0-4 3.4-6.8 7.6-6.8s7.4 2.6 7.4 5.9c0 .8-.6 1.3-1.4 1.3H4.7c-.7 0-1.2-.6-1.2-1.4z"/>'
    + '<circle cx="20.4" cy="12.4" r="1.8"/>'
    + '<rect x="6" y="14.2" width="2.2" height="3.2" rx="1.1"/><rect x="14" y="14.2" width="2.2" height="3.2" rx="1.1"/>'
    + '<path d="M3.2 12.6 L.9 11.6 L2.1 13.9 Z"/></svg>';
  function turnGetApp(forkId) {
    var srv = turnServer(forkId), clients = ((_lastData && _lastData.turn_catalog) || {}).clients || {};
    var os = subOs();
    function has(links) { return links && (links.url || links.github || links.play || links.appstore); }
    // Build the resolved-app record for one client id on the visitor's OS (null if it doesn't ship for this OS).
    function build(cid) {
      var cl = clients[cid], links = cl && cl.platforms && cl.platforms[os];   // this OS only — no cross-OS fallback
      if (!has(links)) return null;
      // The app you actually download for this OS (desktop "WINGS DeX" vs Android "WINGS V"); attribute it to the
      // publishing fork (native_fork) so it's clear it's the same source as the fork chip.
      var store = links.play || links.appstore;                      // store / TestFlight install link
      var page = links.page || links.github || store || links.url;   // downloads PAGE (bubble header / "manually")
      var file = links.url || store || page;                         // DIRECT installer (button); store when no file
      return { app: links.name || cl.name || cid, cid: cid, enc: cl.encoder || cid, author: cl.native_fork || "", platform: os, store: store || "",
               productName: links.name || "",   // OS-specific product name (desktop "WINGS DeX") — differs from the encoder's app name
               file: file, fileName: urlFileName(file), page: page,
               tag: links.tag || "", assets: links.assets || [] };   // assets = LATEST release's files → the bubble
    }
    // a CLI resolves to ONE build (the author the admin picked, else the fork's native/first CLI) — carried as .cliAuthor
    var cliAuthors = (srv && srv.cli_authors) || ["samosvalishe"];
    function withCli(rec, author) { if (rec && rec.cid === "sidecar") rec.cliAuthor = author || cliAuthors[0]; return rec; }
    // compat map for this fork (modern catalog); a legacy serve.json had none → hasCompat gates the fallbacks below.
    var compat = (srv && srv.compat) || {};
    var hasCompat = false; for (var _c in compat) { hasCompat = true; break; }
    // 1) the admin's chosen END-USER default for this (fork, OS): a client id, or "sidecar@<author>" (a CLI build).
    //    Honoured ONLY if that client is still COMPATIBLE with the fork — a saved default goes stale when a pairing is
    //    retired (e.g. VK TURN Proxy dropped from MYSOREZ), and a stale default must never resurrect a dead pairing.
    var def = (((_lastData && _lastData.turn_client_default) || {})[forkId] || {})[os];
    if (def) {
      if (def.indexOf("sidecar@") === 0) { if (compat.sidecar || !hasCompat) { var d0 = build("sidecar"); if (d0) return withCli(d0, def.split("@")[1]); } }
      else if (clients[def] && (compat[def] || !hasCompat)) { var d = build(def); if (d) return d; }
    }
    // 2) no (valid) default → the compat-ranked top app for this OS (matches the panel picker's default ordering):
    //    native non-CLI · friendly non-CLI · native CLI · friendly CLI · plain; hidden (no `compat` class) omitted.
    var isCli = function (id) { return id === "sidecar" || ((clients[id] || {}).encoder === "sidecar"); };
    var rank = function (id) { var cl = compat[id], cli = isCli(id);   // apps before sidecars in each band; plain last (matches the panel picker)
      return cl === "native" ? (cli ? 3 : 1)
        : (cl === "friendly" || cl === "friendly_core") ? (cli ? 4 : 2)
        : cl === "plain" ? (cli ? 6 : 5) : 9; };
    var ranked = [];
    for (var id in clients) if (compat[id] && has(clients[id].platforms && clients[id].platforms[os])) ranked.push(id);
    ranked.sort(function (a, b) { return rank(a) - rank(b) || (a < b ? -1 : a > b ? 1 : 0); });
    for (var k = 0; k < ranked.length; k++) { var r2 = build(ranked[k]); if (r2) return withCli(r2, cliAuthors[0]); }
    // 3) legacy fallback: the fork's own clients list order — ONLY when there's no compat map (serve.json predating
    //    `compat`). With a compat map present, step 2 already decided; never resurrect a client the compat map omits.
    if (!hasCompat) {
      var cids = (srv && srv.clients) || [];
      for (var j = 0; j < cids.length; j++) { var r = build(cids[j]); if (r) return withCli(r, cliAuthors[0]); }
    }
    return null;
  }
  // The visitor's device OS, mapped to a catalog platform key (best-effort from the UA / platform string).
  function _subDetectOs() {
    var ua = ((navigator.userAgent || "") + " " + (navigator.platform || "")).toLowerCase();
    if (/android/.test(ua)) return "android";
    if (/iphone|ipad|ipod/.test(ua)) return "ios";
    if (/mac/.test(ua)) return "macos";
    if (/win/.test(ua)) return "windows";
    if (/linux/.test(ua)) return "linux";
    return "";
  }
  // The SELECTED OS — auto-detected, overridable via the header OS picker; drives which client-settings value-set
  // AND which download the config/Start button use. Persisted so a re-open keeps the choice.
  var OS_LIST = [["android", "Android"], ["ios", "iOS"], ["linux", "Linux"], ["windows", "Windows"], ["macos", "macOS"]];
  // per-OS brand glyphs (viewBox-only → sized by CSS); macOS = the Finder face, matching the panel's OS picker.
  var OS_ICON = {
    android: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7.2 9.3h9.6v7.2a1 1 0 0 1-1 1H15v2.1a1.1 1.1 0 0 1-2.2 0V17.5h-1.6v2.1a1.1 1.1 0 0 1-2.2 0V17.5h-.8a1 1 0 0 1-1-1zM5 9.6a1.1 1.1 0 0 1 1.1 1.1v4.4a1.1 1.1 0 0 1-2.2 0v-4.4A1.1 1.1 0 0 1 5 9.6zm14 0a1.1 1.1 0 0 1 1.1 1.1v4.4a1.1 1.1 0 0 1-2.2 0v-4.4A1.1 1.1 0 0 1 19 9.6zM8.3 8.4a3.9 3.9 0 0 1 1.7-2.7l-.82-1.35a.28.28 0 0 1 .48-.28l.83 1.4a4.6 4.6 0 0 1 3 0l.83-1.4a.28.28 0 0 1 .48.28L14 5.7a3.9 3.9 0 0 1 1.7 2.7zm1.8-1.6a.62.62 0 1 0 0-1.24.62.62 0 0 0 0 1.24zm3.8 0a.62.62 0 1 0 0-1.24.62.62 0 0 0 0 1.24z"/></svg>',
    ios: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.8 12.7c-.02-2.2 1.8-3.26 1.88-3.32-1.02-1.5-2.62-1.7-3.19-1.72-1.36-.14-2.65.8-3.34.8-.68 0-1.75-.78-2.88-.76-1.5.02-2.85.86-3.61 2.19-1.54 2.68-.4 6.65 1.1 8.83.73 1.07 1.6 2.27 2.74 2.23 1.1-.045 1.52-.71 2.85-.71 1.33 0 1.7.71 2.87.69 1.18-.02 1.93-1.09 2.65-2.16.83-1.24 1.18-2.44 1.2-2.5-.026-.01-2.3-.885-2.32-3.51zM13.6 6.35c.6-.73.995-1.74.888-2.75-.86.035-1.9.57-2.52 1.3-.55.64-1.03 1.68-.9 2.66.955.075 1.93-.49 2.53-1.21z"/></svg>',
    windows: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 5.6l7.4-1.02v7.06H3zm8.3-1.14L21 3.1v8.54h-9.7zM3 12.44h7.4v7.06L3 18.44zm8.3 0H21v8.5l-9.7-1.36z"/></svg>',
    macos: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="M11.8 3.8c-1.1 2.1-.9 3.4.8 4.9-1.9 1.2-2 2.7-.3 4.3-1.7 1.1-1.9 3.3.2 6.2"/><path d="M8.3 9v1.7M15.6 9v1.7"/><path d="M7.7 14.4c2.6 2.1 6.3 2.1 8.9 0"/></svg>',
    linux: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12.504 0c-.155 0-.315.008-.48.021-4.226.333-3.105 4.807-3.17 6.298-.076 1.092-.3 1.953-1.05 3.02-.885 1.051-2.127 2.75-2.716 4.521-.278.832-.41 1.684-.287 2.489a.424.424 0 00-.11.135c-.26.268-.45.6-.663.839-.199.199-.485.267-.797.4-.313.136-.658.269-.864.68-.09.189-.136.394-.132.602 0 .199.027.4.055.536.058.399.116.728.04.97-.249.68-.28 1.145-.106 1.484.174.334.535.47.94.601.81.2 1.91.135 2.774.6.926.466 1.866.67 2.616.47.526-.116.97-.464 1.208-.946.587-.003 1.23-.269 2.26-.334.699-.058 1.574.267 2.577.2.025.134.063.198.114.333l.003.003c.391.778 1.113 1.132 1.884 1.071.771-.06 1.592-.536 2.257-1.306.631-.765 1.683-1.084 2.378-1.503.348-.199.629-.469.649-.853.023-.4-.2-.811-.714-1.376v-.097l-.003-.003c-.17-.2-.25-.535-.338-.926-.085-.401-.182-.786-.492-1.046h-.003c-.059-.054-.123-.067-.188-.135a.357.357 0 00-.19-.064c.431-1.278.264-2.55-.173-3.694-.533-1.41-1.465-2.638-2.175-3.483-.796-1.005-1.576-1.957-1.56-3.368.026-2.152.236-6.133-3.544-6.139zm.529 3.405h.013c.213 0 .396.062.584.198.19.135.33.332.438.533.105.259.158.459.166.724 0-.02.006-.04.006-.06v.105a.086.086 0 01-.004-.021l-.004-.024a1.807 1.807 0 01-.15.706.953.953 0 01-.213.335.71.71 0 00-.088-.042c-.104-.045-.198-.064-.284-.133a1.312 1.312 0 00-.22-.066c.05-.06.146-.133.183-.198.053-.128.082-.264.088-.402v-.02a1.21 1.21 0 00-.061-.4c-.045-.134-.101-.2-.183-.333-.084-.066-.167-.132-.267-.132h-.016c-.093 0-.176.03-.262.132a.8.8 0 00-.205.334 1.18 1.18 0 00-.09.4v.019c.002.089.008.179.02.267-.193-.067-.438-.135-.607-.202a1.635 1.635 0 01-.018-.2v-.02a1.772 1.772 0 01.15-.768c.082-.22.232-.406.43-.533a.985.985 0 01.594-.2zm-2.962.059h.036c.142 0 .27.048.399.135.146.129.264.288.344.465.09.199.14.4.153.667v.004c.007.134.006.2-.002.266v.08c-.03.007-.056.018-.083.024-.152.055-.274.135-.393.2.012-.09.013-.18.003-.267v-.015c-.012-.133-.04-.2-.082-.333a.613.613 0 00-.166-.267.248.248 0 00-.183-.064h-.021c-.071.006-.13.04-.186.132a.552.552 0 00-.12.27.944.944 0 00-.023.33v.015c.012.135.037.2.08.334.046.134.098.2.166.268.01.009.02.018.034.024-.07.057-.117.07-.176.136a.304.304 0 01-.131.068 2.62 2.62 0 01-.275-.402 1.772 1.772 0 01-.155-.667 1.759 1.759 0 01.08-.668 1.43 1.43 0 01.283-.535c.128-.133.26-.2.418-.2zm1.37 1.706c.332 0 .733.065 1.216.399.293.2.523.269 1.052.468h.003c.255.136.405.266.478.399v-.131a.571.571 0 01.016.47c-.123.31-.516.643-1.063.842v.002c-.268.135-.501.333-.775.465-.276.135-.588.292-1.012.267a1.139 1.139 0 01-.448-.067 3.566 3.566 0 01-.322-.198c-.195-.135-.363-.332-.612-.465v-.005h-.005c-.4-.246-.616-.512-.686-.71-.07-.268-.005-.47.193-.6.224-.135.38-.271.483-.336.104-.074.143-.102.176-.131h.002v-.003c.169-.202.436-.47.839-.601.139-.036.294-.065.466-.065zm2.8 2.142c.358 1.417 1.196 3.475 1.735 4.473.286.534.855 1.659 1.102 3.024.156-.005.33.018.513.064.646-1.671-.546-3.467-1.089-3.966-.22-.2-.232-.335-.123-.335.59.534 1.365 1.572 1.646 2.757.13.535.16 1.104.021 1.67.067.028.135.06.205.067 1.032.534 1.413.938 1.23 1.537v-.043c-.06-.003-.12 0-.18 0h-.016c.151-.467-.182-.825-1.065-1.224-.915-.4-1.646-.336-1.77.465-.008.043-.013.066-.018.135-.068.023-.139.053-.209.064-.43.268-.662.669-.793 1.187-.13.533-.17 1.156-.205 1.869v.003c-.02.334-.17.838-.319 1.35-1.5 1.072-3.58 1.538-5.348.334a2.645 2.645 0 00-.402-.533 1.45 1.45 0 00-.275-.333c.182 0 .338-.03.465-.067a.615.615 0 00.314-.334c.108-.267 0-.697-.345-1.163-.345-.467-.931-.995-1.788-1.521-.63-.4-.986-.87-1.15-1.396-.165-.534-.143-1.085-.015-1.645.245-1.07.873-2.11 1.274-2.763.107-.065.037.135-.408.974-.396.751-1.14 2.497-.122 3.854a8.123 8.123 0 01.647-2.876c.564-1.278 1.743-3.504 1.836-5.268.048.036.217.135.289.202.218.133.38.333.59.465.21.201.477.335.876.335.039.003.075.006.11.006.412 0 .73-.134.997-.268.29-.134.52-.334.74-.4h.005c.467-.135.835-.402 1.044-.7zm2.185 8.958c.037.6.343 1.245.882 1.377.588.134 1.434-.333 1.791-.765l.211-.01c.315-.007.577.01.847.268l.003.003c.208.199.305.53.391.876.085.4.154.78.409 1.066.486.527.645.906.636 1.14l.003-.007v.018l-.003-.012c-.015.262-.185.396-.498.595-.63.401-1.746.712-2.457 1.57-.618.737-1.37 1.14-2.036 1.191-.664.053-1.237-.2-1.574-.898l-.005-.003c-.21-.4-.12-1.025.056-1.69.176-.668.428-1.344.463-1.897.037-.714.076-1.335.195-1.814.12-.465.308-.797.641-.984l.045-.022zm-10.814.049h.01c.053 0 .105.005.157.014.376.055.706.333 1.023.752l.91 1.664.003.003c.243.533.754 1.064 1.189 1.637.434.598.77 1.131.729 1.57v.006c-.057.744-.48 1.148-1.125 1.294-.645.135-1.52.002-2.395-.464-.968-.536-2.118-.469-2.857-.602-.369-.066-.61-.2-.723-.4-.11-.2-.113-.602.123-1.23v-.004l.002-.003c.117-.334.03-.752-.027-1.118-.055-.401-.083-.71.043-.94.16-.334.396-.4.69-.533.294-.135.64-.202.915-.47h.002v-.002c.256-.268.445-.601.668-.838.19-.201.38-.336.663-.336zm7.159-9.074c-.435.201-.945.535-1.488.535-.542 0-.97-.267-1.28-.466-.154-.134-.28-.268-.373-.335-.164-.134-.144-.333-.074-.333.109.016.129.134.199.2.096.066.215.2.36.333.292.2.68.467 1.167.467.485 0 1.053-.267 1.398-.466.195-.135.445-.334.648-.467.156-.136.149-.267.279-.267.128.016.034.134-.147.332a8.097 8.097 0 01-.69.468zm-1.082-1.583V5.64c-.006-.02.013-.042.029-.05.074-.043.18-.027.26.004.063 0 .16.067.15.135-.006.049-.085.066-.135.066-.055 0-.092-.043-.141-.068-.052-.018-.146-.008-.163-.065zm-.551 0c-.02.058-.113.049-.166.066-.047.025-.086.068-.14.068-.05 0-.13-.02-.136-.068-.01-.066.088-.133.15-.133.08-.031.184-.047.259-.005.019.009.036.03.03.05v.02h.003z"/></svg>'
  };
  var _selOs = null;
  function subOs() {
    if (_selOs) return _selOs;
    var saved = _ls("swgsub-os");
    _selOs = (saved && OS_LIST.some(function (o) { return o[0] === saved; })) ? saved : (_subDetectOs() || "android");
    return _selOs;
  }
  function setSubOs(os) { _selOs = os; _lsSet("swgsub-os", os); paintCtl(); reRender(); }
  // SETTINGS SPLIT: the admin's saved default VALUES for the client being encoded (`enc` — the OS-resolved app, which
  // may be a cross-fork one; defaults to the fork's native encoder), for the VISITOR'S OS
  // (turn_client_settings[fork][clientId][os]) — so a phone gets the Android value-set and a laptop the desktop
  // one. Falls back to the app's primary platform when it doesn't ship for the visitor's OS. Schema is per-client;
  // this just selects which saved value-set to apply. The encoder fills anything unset with the app's own default.
  function turnClientCS(forkId, enc) {
    var clients = ((_lastData && _lastData.turn_catalog) || {}).clients || {};
    enc = enc || ((typeof SWGTurn.nativeEncoder === "function") ? SWGTurn.nativeEncoder(forkId) : null);
    var cid = null, cl = null;
    for (var id in clients) { if ((clients[id].encoder || id) === enc) { cid = id; cl = clients[id]; break; } }
    if (!cl) return {};
    var oses = cl.platforms ? Object.keys(cl.platforms) : [];
    var dev = subOs();
    var pk = (dev && oses.indexOf(dev) >= 0) ? dev : (oses[0] || "");
    var store = ((_lastData && _lastData.turn_client_settings) || {})[forkId] || {};
    return ((store[cid] || {})[pk]) || {};
  }

  // AXIS-3: canonical install links for the WireGuard / AmneziaWG client apps (the WG/AWG cells). Unlike the turn
  // forks, these are the well-known official apps, so their store links are hardcoded defaults (not admin-curated).
  // Platform-aware — the sub page is opened on the user's OWN device, so we link to the matching store; desktop
  // falls back to the app's install page.
  // The WG/AWG client apps, per OS. Amnezia VPN is the one app with a `vpn://` browser one-tap import (Android only —
  // WireGuard/AmneziaWG register NO URL scheme on any OS), so it leads; the others import a .conf by file/QR.
  var WG_CLIENTS = {
    amneziavpn: { name: "AmneziaVPN", autostart: true, logo: "_a/amneziavpn.svg", page: "https://amnezia.org/en/downloads",   // "— Autostart" (the vpn:// one-tap auto-import) only applies on Android
      android: "https://play.google.com/store/apps/details?id=org.amnezia.vpn",
      ios: "https://apps.apple.com/app/amneziavpn/id1600529900",
      macos: "https://apps.apple.com/app/amneziavpn/id1600529900",   // Apple-Silicon Macs run the iOS app from the App Store (same id) → "just tap open"
      windows: "https://amnezia.org/en/downloads", linux: "https://amnezia.org/en/downloads" },   // Win/Linux = .exe/.tar via the downloads page (no store)
    amneziawg: { name: "AmneziaWG", logo: "_a/amneziawg.png", page: "https://github.com/amnezia-vpn/amneziawg-windows-client/releases",
      android: "https://play.google.com/store/apps/details?id=org.amnezia.awg",
      ios: "https://apps.apple.com/app/amneziawg/id6478942365", macos: "https://apps.apple.com/app/amneziawg/id6478942365",   // one App Store listing runs on iPhone/iPad + Mac
      windows: "https://github.com/amnezia-vpn/amneziawg-windows-client/releases", linux: "" },   // no standalone Linux app
    wireguard: { name: "WireGuard", logo: "_a/wireguard.svg", page: "https://www.wireguard.com/install/",
      android: "https://play.google.com/store/apps/details?id=com.wireguard.android",
      ios: "https://apps.apple.com/app/wireguard/id1441195209", macos: "https://apps.apple.com/app/wireguard/id1451685025",
      windows: "https://download.wireguard.com/windows-client/wireguard-installer.exe", linux: "https://www.wireguard.com/install/" }   // Linux = per-distro
  };
  var WG_ORDER = { awg: ["amneziavpn", "amneziawg"], wg: ["amneziavpn", "amneziawg", "wireguard"] };
  // Real Safari on iOS/iPadOS specifically — the ONLY browser that pops a modal "Safari cannot open the page because
  // the address is invalid" when an unregistered custom scheme (e.g. vkturnproxy://) is fired. Chrome/Firefox/Edge on
  // iOS fail silently, so they keep the auto-fire + fallback. Best-effort (Brave / SFSafariViewController can slip in).
  function isIOSSafari() {
    var ua = navigator.userAgent || "";
    var ios = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    return ios && /Version\/\d/.test(ua) && /Safari\//.test(ua) &&
      !/CriOS|FxiOS|EdgiOS|OPiOS|OPT\/|DuckDuckGo|GSA\/|YaBrowser|FBAN|FBAV|FB_IAB|Instagram|Line\/|SnapChat|Twitter/.test(ua);
  }
  function wgGetApp(type) {   // returns the WG/AWG client apps for the CURRENT OS → the "Get … manually" bubble (two-target rows)
    var awg = type === "awg";
    var order = WG_ORDER[awg ? "awg" : "wg"], os = subOs(), items = [];
    var cat = (_lastData && _lastData.wg_catalog) || {};
    order.forEach(function (id) {
      var app = WG_CLIENTS[id]; if (!app) return;
      var res = cat[id] || null, plat = (res && res.platforms && res.platforms[os]) || null;
      var page = (res && res.page) || app.page || app[os] || "";                          // row body → the app's downloads page
      // download icon → the best DIRECT installer for this OS (panel-resolved), else the store / page
      var dl = (plat && (plat.url || plat.store || plat.page || plat.github)) || app[os] || page;
      if (!dl && !page) return;                                                            // nothing offered for this OS
      var nm = app.name + ((app.autostart && os === "android") ? " — Autostart" : "");     // Autostart (one-tap auto-import) is Android-only
      items.push({ id: id, name: nm, logo: app.logo, page: page || dl, dl: dl, isFile: !!urlFileName(dl) });
    });
    if (!items.length) return null;
    var primary = items[0];   // Amnezia VPN → the Start button's get-app fallback
    return { app: awg ? "AmneziaWG" : "WireGuard", platform: os,
             file: primary.dl, fileName: "", page: primary.page,
             headerTitle: t(awg ? "getAwgClient" : "getWgClient"), wgItems: items };
  }
  var AMNEZIA_VPN = { name: "Amnezia VPN" };
  // The MYSOREZ VK TURN Proxy app un-bundled its engine ("core") in v2.0.0 — the arm64 core binary the app imports.
  // It's a UNIVERSAL LAUNCHER: it runs the SERVER FORK's own core, so the core to import is *that fork's*, not a fixed
  // one. Resolve per-fork from the fork's repo owner (stable asset name → the LATEST release, no version pin). A
  // MYSOREZ server needs MYSOREZ's core, a cacggghp server needs cacggghp's, etc. Fallback: cacggghp (the family root).
  var CORE_FALLBACK = "https://github.com/cacggghp/vk-turn-proxy/releases/latest/download/client-android-arm64";
  function coreUrlFor(forkId) {
    var o = (turnServer(forkId) || {}).owner;
    return o ? "https://github.com/" + o + "/releases/latest/download/client-android-arm64" : CORE_FALLBACK;
  }
  function platLbl(p) { return ({ android: "Android", ios: "iOS", windows: "Windows", macos: "macOS", linux: "Linux" })[p] || ""; }
  // The OS an asset targets, inferred from its filename ("" if unknown — e.g. a store link).
  function assetOs(name) {
    var L = String(name || "").toLowerCase();
    if (/\.apk$|client-android|[-_]android[-_.]/.test(L)) return "android";
    if (/\.ipa$/.test(L)) return "ios";
    if (/\.(exe|msi)$|client-windows|[-_]windows[-_.]|win(?:64|32)/.test(L)) return "windows";
    if (/\.(dmg|pkg)$|client-darwin|darwin|mac(?:os)?[-_.]/.test(L)) return "macos";
    if (/\.(deb|appimage|rpm)$|client-linux|[-_]linux[-_.]|\.tar(?:\.|$)/.test(L)) return "linux";
    if (/client-freebsd|[-_]freebsd[-_.]/.test(L)) return "freebsd";   // a real client, but for an OS we don't list → scoped out of every bubble
    return "";
  }
  // If a URL points at a downloadable installer, its filename; else "" (a store / instructions PAGE — opened, not saved).
  function urlFileName(u) {
    u = String(u || "");
    if (!/\/releases\/(?:latest\/)?download\/|\.(apk|ipa|exe|msi|deb|dmg|pkg|appimage|rpm|zip|tar(?:\.[a-z]+)?)(?:$|\?)/i.test(u)) return "";   // tagged (/releases/download/<tag>/) OR latest (/releases/latest/download/)
    return u.split(/[?#]/)[0].split("/").pop() || "";
  }
  // Download a file by navigating to it in the SAME tab — no _blank, and crucially NO `download` attribute: on a
  // cross-origin link Chrome ignores the attribute's name and saves the file as the redirected CDN URL's basename
  // (a GUID). A plain same-tab navigation to an attachment URL lets the browser honour the server's
  // Content-Disposition filename instead (GitHub / the WG installer CDN all send it).
  function triggerDownload(url) {
    var a = document.createElement("a"); a.href = url; a.rel = "noopener";
    document.body.appendChild(a); a.click();
    setTimeout(function () { try { a.remove(); } catch (_) {} }, 0);
  }
  // Installer assets only — drop checksums / signatures / patch-deltas / source archives / server-role binaries, which
  // aren't things a user installs. Leaves the real .apk/.exe/.deb/.dmg/… + extensionless CLI client binaries.
  function installerAssets(assets) {
    return (assets || []).filter(function (a) {
      var n = (a && a.name) || "";
      if (/\.(sha\d+|sig|asc|txt|json|patch|md|ya?ml)$/i.test(n)) return false;
      if (/(^|[-_.])sources?([-_.]|$)/i.test(n)) return false;
      if (/^server[-_]/i.test(n)) return false;
      if (/^lib[a-z0-9]|\.aar$|xcframework/i.test(n)) return false;   // dev libraries/frameworks (libfreeturn-*, mobile.aar, Mobile.xcframework.zip) — not user-run clients
      return true;
    });
  }
  // Friendly "OS · format · arch" label from an asset filename (falls back to the raw name if nothing parses).
  function assetLabel(name) {
    var L = String(name || "").toLowerCase();
    var os = platLbl(assetOs(name));
    var arch = /arm64[-_]?v8a/.test(L) ? "ARM64" : /armeabi[-_]?v7a|armv7/.test(L) ? "ARM32"
      : /arm64|aarch64/.test(L) ? "ARM64" : /x86[_-]?64|amd64|x64/.test(L) ? "x64"
      : /x86|[-_]386(?:[-_.]|$)/.test(L) ? "x86" : /riscv64/.test(L) ? "RISC-V"
      : /mips64le/.test(L) ? "MIPS64LE" : /mipsle/.test(L) ? "MIPSLE" : /mips/.test(L) ? "MIPS"
      : /[-_]arm(?:[-_.]|$)/.test(L) ? "ARM32" : /universal/.test(L) ? "Universal" : "";
    var m = L.match(/\.(apk|ipa|exe|msi|dmg|pkg|deb|rpm|appimage|zip|tar\.(?:gz|xz|zst)|tar)$/);
    var fmt = m ? m[1].toUpperCase().replace("APPIMAGE", "AppImage") : (/client-(?:linux|darwin|android|freebsd)/.test(L) ? "Binary" : "");
    var parts = [os, fmt, arch].filter(Boolean);
    return parts.length ? parts.join(" · ") : String(name || "");
  }
  // The "Get the app manually" control above the QR. When the resolved release exposes direct installer files for the
  // visitor's OS it opens a BUBBLE — header = the downloads PAGE link ("Open GitHub (App) downloads page"), items = each
  // latest-release file for THIS OS as a direct download. With no file list (store-only apps) it stays a plain link.
  function storeLabel(u) {
    return /testflight\.apple/.test(u) ? "TestFlight" : /apps\.apple/.test(u) ? "App Store" : /play\.google/.test(u) ? "Google Play" : "Install page";
  }
  function getAppRow(ga) {
    var wrap = el("div", "scell-getapp");
    if (ga.wgItems) {   // WG/AWG multi-app bubble: each row = logo/name → downloads page + a download icon → direct file
      var btnW = el("button", "scell-getapp-a scell-getapp-btn"); btnW.type = "button";
      btnW.textContent = t("getAppManual").replace("{app}", ga.app) + " ▾";
      btnW.onclick = function (e) { e.stopPropagation(); openDlBubble(btnW, ga, null); };
      wrap.appendChild(btnW);
      return wrap;
    }
    var files = installerAssets(ga.assets);
    var want = ga.platform;   // keep only this OS's files (drop other-OS variants); OS-less items (store links) stay
    var scoped = files.filter(function (f) { var o = assetOs(urlFileName(f.url) || f.name); return !o || o === want; });
    files = scoped.length ? scoped : files;
    // Lead the bubble with the store/TestFlight install link where one exists (e.g. iOS: the recommended path — the
    // .ipa needs self-signing), so both show: "… · TestFlight" then "iOS · IPA".
    if (ga.store) files = [{ name: ga.app + " · " + storeLabel(ga.store), url: ga.store }].concat(files);
    var label = ga.author
      ? t("getAppBy").replace("{app}", ga.app).replace("{author}", ga.author)
      : (files.length ? t("getAppManual").replace("{app}", ga.app)   // opens a bubble → "Get <app> manually"
                      : t("getApp").replace("{app}", ga.app) + (platLbl(ga.platform) ? " · " + platLbl(ga.platform) : ""));
    if (files.length) {
      var btn = el("button", "scell-getapp-a scell-getapp-btn"); btn.type = "button";
      btn.textContent = label + " ▾";
      btn.onclick = function (e) { e.stopPropagation(); openDlBubble(btn, ga, files); };
      wrap.appendChild(btn);
    } else {
      var a = el("a", "scell-getapp-a"); a.href = ga.page; a.target = "_blank"; a.rel = "noopener";
      a.textContent = label + " ↗";
      wrap.appendChild(a);
    }
    return wrap;
  }
  // Device/browser BACK while an instructions popover/overlay is open should just CLOSE it, not navigate away. Opening
  // one pushes a single throwaway history entry; a Back press pops it → popstate → we close every hint. Closing by any
  // OTHER means (×/Esc/backdrop/outside) pops that entry itself (disarmOverlayBack) so history stays balanced. Only one
  // hint is open at a time, and a transition (choice → walkthrough) REUSES the one entry (arm is idempotent) — no churn.
  var _ovArmed = false;
  function closeAllHints() { closeImportHint(); closePasteHint(); closeWgTurnHint(); closeVktgzChoice(); closeVktgzHint(); closeCliHint(); }
  function _ovOnPop() { _ovArmed = false; window.removeEventListener("popstate", _ovOnPop); closeAllHints(); }
  function armOverlayBack() {
    if (_ovArmed) return;
    try { history.pushState({ swgOv: 1 }, ""); } catch (_) { return; }
    _ovArmed = true; window.addEventListener("popstate", _ovOnPop);
  }
  function disarmOverlayBack() {
    if (!_ovArmed) return;
    _ovArmed = false; window.removeEventListener("popstate", _ovOnPop);
    try { history.back(); } catch (_) {}   // drop the entry we pushed (listener already gone → the popstate is a no-op)
  }
  // The single user-initiated dismiss for every hint: close whichever is open + drop the Back entry. (A transition
  // between hints uses the raw close* instead, so the entry carries over.) Only one is ever open, so closing all is safe.
  function dismissHints() { closeAllHints(); disarmOverlayBack(); }
  // Swipe DOWN on a full-screen hint closes it (a natural "dismiss sheet" gesture). Tracks a mostly-vertical drag past a
  // threshold; horizontal drags (pager swipes) and taps are ignored.
  function attachSwipeDown(ov, onClose) {
    var y0 = 0, x0 = 0, tracking = false;
    ov.addEventListener("touchstart", function (e) {
      if (e.touches.length !== 1) { tracking = false; return; }
      tracking = true; y0 = e.touches[0].clientY; x0 = e.touches[0].clientX;
    }, { passive: true });
    ov.addEventListener("touchend", function (e) {
      if (!tracking) return;
      tracking = false;
      var t = (e.changedTouches && e.changedTouches[0]) || null; if (!t) return;
      var dy = t.clientY - y0, dx = t.clientX - x0;
      if (dy > 70 && dy > Math.abs(dx) * 1.5) onClose();   // clear downward flick
    }, { passive: true });
  }

  // Download bubble — a single global popover anchored just below its trigger, growing downward, capped so it never
  // overlaps the button bar (maxHeight = barTop − top − 12).
  var _dlBubble = null;
  function closeDlBubble() {
    if (!_dlBubble) return;
    _dlBubble.remove(); _dlBubble = null;
    document.removeEventListener("mousedown", _dlOutside, true);
    document.removeEventListener("keydown", _dlKey, true);
    window.removeEventListener("resize", closeDlBubble);
  }
  function _dlOutside(e) { if (_dlBubble && !_dlBubble.contains(e.target)) closeDlBubble(); }
  function _dlKey(e) { if (e.key === "Escape") { e.preventDefault(); closeDlBubble(); } }
  function openDlBubble(anchor, ga, files) {
    if (_dlBubble && _dlBubble._anchor === anchor) { closeDlBubble(); return; }   // second click on same trigger → toggle off
    closeDlBubble();
    var b = el("div", "dl-bubble"); b._anchor = anchor;
    if (ga.headerTitle) {   // multi-app bubble (WG/AWG) — a plain title, no single releases page to link
      b.appendChild(el("div", "dl-bubble-title", ga.headerTitle));
    } else {
      var isGithub = /github\.com/.test(ga.page || "");
      var head = el("a", "dl-bubble-head"); head.href = ga.page; head.target = "_blank"; head.rel = "noopener";
      head.textContent = t("dlOpenPage").replace("{host}", isGithub ? "GitHub " : "").replace("{app}", ga.app) + " ↗";
      b.appendChild(head);
      if (ga.tag) b.appendChild(el("div", "dl-bubble-ver", t("dlLatest").replace("{ver}", ga.tag)));
    }
    var list = el("div", "dl-bubble-list");
    if (ga.wgItems) {   // WG/AWG two-target rows: [logo + name] → downloads page · [⬇] → best direct installer for this OS
      ga.wgItems.forEach(function (f) {
        var row = el("div", "dl-bubble-item has-logo wg-row");
        var body = el("a", "dl-row-body"); body.href = f.page; body.target = "_blank"; body.rel = "noopener";
        if (f.logo) { var lg = el("img", "dl-item-logo"); lg.src = f.logo; lg.alt = ""; body.appendChild(lg); }
        var colw = el("span", "dl-item-col");
        colw.appendChild(el("span", "dl-item-label", f.name));
        colw.appendChild(el("span", "dl-item-file", String(f.page).replace(/^https?:\/\//, "").split(/[\/?#]/)[0]));
        body.appendChild(colw);
        body.addEventListener("click", function () { setTimeout(closeDlBubble, 60); });
        row.appendChild(body);
        var dlb = el("a", "dl-row-dl"); dlb.href = f.dl; dlb.title = t("dlShort"); dlb.setAttribute("aria-label", t("dlShort")); dlb.appendChild(iconEl("download"));
        if (f.isFile) dlb.onclick = function (e) { e.preventDefault(); triggerDownload(f.dl); setTimeout(closeDlBubble, 60); };   // direct installer → download in place
        else { dlb.target = "_blank"; dlb.rel = "noopener"; dlb.addEventListener("click", function () { setTimeout(closeDlBubble, 60); }); }   // store / page → new tab
        row.appendChild(dlb);
        list.appendChild(row);
      });
    } else files.forEach(function (f) {
      var fn = urlFileName(f.url);
      var it = el("a", "dl-bubble-item" + (f.logo ? " has-logo" : "")); it.href = f.url; it.rel = "noopener";
      if (!fn) it.target = "_blank";   // store / page → new tab; a direct file downloads in the same tab (correct name)
      if (f.logo) { var lg = el("img", "dl-item-logo"); lg.src = f.logo; lg.alt = ""; it.appendChild(lg); }
      var col = f.logo ? el("span", "dl-item-col") : it;   // with a logo, the text sits in a column beside it
      col.appendChild(el("span", "dl-item-label", fn ? assetLabel(fn) : (f.name || f.url)));
      col.appendChild(el("span", "dl-item-file", fn || String(f.url).replace(/^https?:\/\//, "").split(/[\/?#]/)[0]));
      if (f.logo) it.appendChild(col);
      it.addEventListener("click", function () { setTimeout(closeDlBubble, 60); });
      list.appendChild(it);
    });
    b.appendChild(list);
    document.body.appendChild(b);
    // Open right under the "Get … manually ▾" link (it lives in the header now), centred on it, growing downward —
    // capped so it never runs into the button bar at the bottom.
    var ar = anchor.getBoundingClientRect();
    var bar = (anchor.closest && anchor.closest(".ppage") && anchor.closest(".ppage").querySelector(".pbar"))
      || document.querySelector(".pbar") || document.querySelector(".bar");
    var barTop = bar ? bar.getBoundingClientRect().top : window.innerHeight - 8;
    var top = ar.bottom + 8;
    b.style.left = "50%"; b.style.transform = "translateX(-50%)"; b.style.bottom = "auto";
    b.style.top = Math.round(top) + "px";
    b.style.maxHeight = Math.max(140, barTop - top - 12) + "px";
    _dlBubble = b;
    setTimeout(function () {
      document.addEventListener("mousedown", _dlOutside, true);
      document.addEventListener("keydown", _dlKey, true);
      window.addEventListener("resize", closeDlBubble);
    }, 0);
  }

  // "Ask on tap" choice popover (Safari-on-iOS): Open the app (deliberate scheme fire) vs Get the app (store/TestFlight).
  var _startChoice = null;
  var _schemeFiredAt = {};
  var IMPORT_HINT_IMG = "_a/import-hint.png";   // anton48 iOS "Settings → Import" hint (screenshot, server details blurred)   // hasAppKey → last no-fallback scheme fire time, for stale-"installed"-flag recovery (a quick re-tap = it didn't open)
  var _ihPreload = new Image(); _ihPreload.src = IMPORT_HINT_IMG;   // warm it on load (keep the ref so it isn't GC'd before the fetch) → tapping Start shows the hint instantly, no download then
  function closeStartChoice() {
    if (!_startChoice) return;
    _startChoice.remove(); _startChoice = null;
    document.removeEventListener("mousedown", _scOutside, true);
    document.removeEventListener("keydown", _scKey, true);
    window.removeEventListener("resize", closeStartChoice);
  }
  function _scOutside(e) { if (_startChoice && !_startChoice.contains(e.target)) closeStartChoice(); }
  function _scKey(e) { if (e.key === "Escape") { e.preventDefault(); closeStartChoice(); } }
  function openStartChoice(anchor, c, onOpen, onGet) {
    closeStartChoice(); closeDlBubble();
    var app = c.app || t("theApp");
    var b = el("div", "start-choice");
    b.appendChild(el("div", "start-choice-t", t("startHow")));
    var mk = function (label, sub, fn, variant) {
      var btn = el("button", "start-choice-b " + variant); btn.type = "button";
      btn.appendChild(el("span", "start-choice-l", label));
      if (sub) btn.appendChild(el("span", "start-choice-s", sub));
      btn.onclick = function () { closeStartChoice(); fn(); };
      return btn;
    };
    b.appendChild(mk(t("startGetApp").replace("{app}", c.dlAppName || app), t("startNeedIt"), onGet, "get"));   // Get first — bluish
    b.appendChild(mk(t("startOpenApp").replace("{app}", app), t("startHaveIt"), onOpen, "open"));               // Open second — greenish
    document.body.appendChild(b);
    var bar = (anchor.closest && anchor.closest(".ppage") && anchor.closest(".ppage").querySelector(".pbar")) || document.querySelector(".pbar") || document.querySelector(".bar");
    var barTop = bar ? bar.getBoundingClientRect().top : window.innerHeight - 76;
    b.style.left = "50%"; b.style.transform = "translateX(-50%)"; b.style.top = "auto";
    b.style.bottom = Math.max(8, window.innerHeight - barTop + 12) + "px";
    _startChoice = b;
    setTimeout(function () {
      document.addEventListener("mousedown", _scOutside, true);
      document.addEventListener("keydown", _scKey, true);
      window.addEventListener("resize", closeStartChoice);
    }, 0);
  }

  // Import-hint popover (anton48 iOS): after the app opens, its "Import Connection Link?" prompt only shows once you
  // reach Settings → Import (app-side quirk). Show a reminder + a screenshot (server details blurred) so the user knows
  // where to tap when they return to the browser. Dismisses on tap-outside / Esc / a short auto-timeout.
  var _importHint = null, _importPending = 0, _importCd = null, _cdTimer = 0;
  function closeImportHint() {
    if (!_importHint) return;
    clearTimeout(_importPending); _importPending = 0;   // closing before the app opens cancels the pending open
    clearInterval(_cdTimer); _cdTimer = 0; _importCd = null;   // stop the "App is opening in N…" countdown
    _importHint.remove(); _importHint = null;
    document.removeEventListener("keydown", _ihKey, true);
  }
  function _ihKey(e) { if (e.key === "Escape") dismissHints(); }
  function showImportHint() {
    closeImportHint();
    // full-screen overlay (like the enlarged QR): dimmed backdrop, centred instruction + the screenshot; tap/Esc closes.
    var ov = el("div", "ih-overlay");
    var inner = el("div", "ih-inner");
    _importCd = el("div", "ih-countdown"); _importCd.style.display = "none"; inner.appendChild(_importCd);   // "App is opening in N…" — driven by fireScheme's 5s countdown, hidden once the app opens
    var txt = el("div", "ih-text");
    txt.appendChild(el("div", "ih-line ih-lead", t("importHint1")));   // first line a bit bigger
    var l2 = el("div", "ih-line"); l2.appendChild(document.createTextNode(t("importHint2"))); l2.appendChild(el("b", null, "Settings")); txt.appendChild(l2);
    var l3 = el("div", "ih-line"); l3.appendChild(document.createTextNode(t("importHint3"))); l3.appendChild(el("b", null, "Import")); txt.appendChild(l3);
    inner.appendChild(txt);
    var img = el("img", "ih-img"); img.src = IMPORT_HINT_IMG; img.alt = ""; inner.appendChild(img);
    ov.appendChild(inner);
    var x = el("button", "ih-close"); x.type = "button"; x.setAttribute("aria-label", "Close"); x.textContent = "×";
    x.onclick = dismissHints; ov.appendChild(x);
    ov.onclick = function (e) { if (e.target === ov) dismissHints(); };   // only the dark backdrop closes — no auto-dismiss
    document.body.appendChild(ov);
    _importHint = ov;
    attachSwipeDown(ov, dismissHints);
    setTimeout(function () { document.addEventListener("keydown", _ihKey, true); }, 0);
    armOverlayBack();
  }

  // WG/AWG Amnezia VPN on a desktop with no vpn:// handler (Windows/Linux): the link is already copied, so show a
  // full-screen "paste it in" card (like the anton48 hint) — app icon, the three steps, and a "download the app" link
  // that toggles a small AmneziaVPN-downloads bubble for this OS. No auto-dismiss: backdrop / Esc / × closes it.
  var _pasteHint = null;
  function closePasteHint() {
    if (!_pasteHint) return;
    _pasteHint.remove(); _pasteHint = null;
    document.removeEventListener("keydown", _phKey, true);
  }
  function _phKey(e) { if (e.key === "Escape") dismissHints(); }
  function amneziaIcon() {   // the AmneziaVPN app logo
    var img = el("img", "ph-icon"); img.src = (WG_CLIENTS.amneziavpn || {}).logo || "_a/amneziavpn.svg"; img.alt = ""; return img;
  }
  function amneziaDlPanel() {   // static (in-overlay) downloads bubble: header link + this-OS item, styled like .dl-bubble
    var os = subOs(), pageUrl = "https://amnezia.org/en/downloads", av = WG_CLIENTS.amneziavpn || {}, osUrl = av[os] || pageUrl;
    var b = el("div", "dl-bubble ph-dlpanel");
    var head = el("a", "dl-bubble-head"); head.href = pageUrl; head.target = "_blank"; head.rel = "noopener";
    head.textContent = t("amneziaDownloads") + " ↗"; b.appendChild(head);
    var list = el("div", "dl-bubble-list");
    var it = el("a", "dl-bubble-item has-logo"); it.href = osUrl; it.target = "_blank"; it.rel = "noopener";
    var lg = el("img", "dl-item-logo"); lg.src = av.logo; lg.alt = ""; it.appendChild(lg);
    var col = el("span", "dl-item-col");
    col.appendChild(el("span", "dl-item-label", platLbl(os) || "Desktop"));
    col.appendChild(el("span", "dl-item-file", String(osUrl).replace(/^https?:\/\//, "").split(/[?#]/)[0]));
    it.appendChild(col); list.appendChild(it); b.appendChild(list);
    return b;
  }
  function showPasteHint() {
    closePasteHint(); closeImportHint();
    var ov = el("div", "ih-overlay ph-overlay");
    var inner = el("div", "ih-inner ph-inner");
    var copied = el("div", "ph-copied"); copied.appendChild(iconEl("checks")); copied.appendChild(el("span", null, t("linkCopied")));
    inner.appendChild(copied);   // green "Connection link copied" ✓✓ — well above the steps
    var head = el("div", "ph-head");
    head.appendChild(amneziaIcon());
    head.appendChild(el("span", "ph-title", "AmneziaVPN"));
    inner.appendChild(head);
    var steps = el("div", "ph-steps");
    var s1 = el("div", "ph-step"); s1.appendChild(document.createTextNode(t("pasteStep1"))); s1.appendChild(el("b", null, "AmneziaVPN")); steps.appendChild(s1);
    steps.appendChild(el("div", "ph-step", t("pasteStep2")));
    var s3 = el("div", "ph-step"); s3.appendChild(document.createTextNode(t("pasteStep3"))); s3.appendChild(el("b", null, t("pasteConnect"))); steps.appendChild(s3);
    inner.appendChild(steps);
    var dl = el("a", "ph-dl"); dl.href = "#"; dl.textContent = t("pasteDownload");
    var panel = null;
    dl.onclick = function (e) {
      e.preventDefault();
      if (panel) { panel.remove(); panel = null; dl.classList.remove("open"); return; }   // toggle
      panel = amneziaDlPanel(); inner.appendChild(panel); dl.classList.add("open");
    };
    inner.appendChild(dl);
    ov.appendChild(inner);
    var x = el("button", "ih-close"); x.type = "button"; x.setAttribute("aria-label", "Close"); x.textContent = "×";
    x.onclick = dismissHints; ov.appendChild(x);
    ov.onclick = function (e) { if (e.target === ov) dismissHints(); };   // only the dark backdrop closes — no auto-dismiss
    document.body.appendChild(ov);
    _pasteHint = ov;
    attachSwipeDown(ov, dismissHints);
    setTimeout(function () { document.addEventListener("keydown", _phKey, true); }, 0);
    armOverlayBack();
  }

  // WG Turn (kiper292) has no scheme — its app imports a downloaded .conf FILE. Start downloads the config, then this
  // overlay (same full-screen card as the paste hint) walks the file-import steps. Backdrop / Esc / × closes it.
  var _wgTurnHint = null;
  function closeWgTurnHint() {
    if (!_wgTurnHint) return;
    _wgTurnHint.remove(); _wgTurnHint = null;
    document.removeEventListener("keydown", _wtKey, true);
  }
  function _wtKey(e) { if (e.key === "Escape") dismissHints(); }
  function wgTurnPlus() {   // the app's blue rounded-square "+" button, rendered inline in step 2
    var span = el("span", "wt-plus");
    span.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 6.5v11M6.5 12h11" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/></svg>';
    return span;
  }
  function appDlPanelFor(name, fileUrl, pageUrl) {   // static in-overlay downloads bubble (styled like .dl-bubble)
    var b = el("div", "dl-bubble ph-dlpanel");
    var head = el("a", "dl-bubble-head"); head.href = pageUrl || fileUrl || "#"; head.target = "_blank"; head.rel = "noopener";
    head.textContent = (name || "App") + " ↗"; b.appendChild(head);
    var url = fileUrl || pageUrl || "#", fn = urlFileName(fileUrl), list = el("div", "dl-bubble-list");
    var it = el("a", "dl-bubble-item"); it.href = url; if (!fn) it.target = "_blank"; it.rel = "noopener";
    it.appendChild(el("span", "dl-item-label", platLbl(subOs()) || (name || "Download")));
    it.appendChild(el("span", "dl-item-file", String(url).replace(/^https?:\/\//, "").split(/[?#]/)[0]));
    list.appendChild(it); b.appendChild(list);
    return b;
  }
  function showWgTurnHint(c) {
    closeWgTurnHint(); closePasteHint(); closeImportHint();
    var ov = el("div", "ih-overlay ph-overlay");
    var inner = el("div", "ih-inner ph-inner");
    var done = el("div", "ph-copied"); done.appendChild(iconEl("checks")); done.appendChild(el("span", null, t("wtDownloaded")));
    inner.appendChild(done);   // green "Config file downloaded" ✓✓
    var head = el("div", "ph-head"); head.appendChild(el("span", "ph-title", "WG Turn")); inner.appendChild(head);
    var steps = el("div", "ph-steps");
    steps.appendChild(el("div", "ph-step", t("wtStep1")));
    var s2 = el("div", "ph-step wt-step2"); s2.appendChild(document.createTextNode(t("wtStep2a"))); s2.appendChild(wgTurnPlus()); s2.appendChild(document.createTextNode(t("wtStep2b"))); steps.appendChild(s2);
    steps.appendChild(el("div", "ph-step", t("wtStep3")));
    steps.appendChild(el("div", "ph-step", t("wtStep4")));
    steps.appendChild(el("div", "ph-step", t("wtStep5")));
    inner.appendChild(steps);
    var dl = el("a", "ph-dl"); dl.href = "#"; dl.textContent = t("pasteDownload");
    var panel = null;
    dl.onclick = function (e) {
      e.preventDefault();
      if (panel) { panel.remove(); panel = null; dl.classList.remove("open"); return; }
      panel = appDlPanelFor((c && c.dlAppName) || "WG Turn", c && c.dlAppUrl, c && c.dlAppPage); inner.appendChild(panel); dl.classList.add("open");
    };
    inner.appendChild(dl);
    ov.appendChild(inner);
    var x = el("button", "ih-close"); x.type = "button"; x.setAttribute("aria-label", "Close"); x.textContent = "×";
    x.onclick = dismissHints; ov.appendChild(x);
    ov.onclick = function (e) { if (e.target === ov) dismissHints(); };
    document.body.appendChild(ov);
    _wgTurnHint = ov;
    attachSwipeDown(ov, dismissHints);
    setTimeout(function () { document.addEventListener("keydown", _wtKey, true); }, 0);
    armOverlayBack();
  }

  // MYSOREZ VK TURN Proxy — assemble in 3 steps. The app is a UI shell that needs a separate "core" binary + a VKTGZ
  // profile. Start shows a 3-button screen (get the GUI app · get the core · assemble+connect); "assemble" copies the
  // VKTGZ: string and shows the 10-step import walkthrough. Backdrop / Esc / × closes.
  var _vktgzChoice = null, _vktgzHint = null;
  function closeVktgzChoice() {
    if (!_vktgzChoice) return;
    _vktgzChoice.remove(); _vktgzChoice = null;
    document.removeEventListener("keydown", _mzKey, true);
    document.removeEventListener("mousedown", _mzOutside, true);
    window.removeEventListener("resize", closeVktgzChoice);
  }
  function closeVktgzHint() { if (!_vktgzHint) return; _vktgzHint.remove(); _vktgzHint = null; document.removeEventListener("keydown", _mzKey, true); }
  function _mzKey(e) { if (e.key === "Escape") dismissHints(); }
  function _mzOutside(e) { if (_vktgzChoice && !_vktgzChoice.contains(e.target)) dismissHints(); }
  function _openUrl(url) { if (!url) return; if (urlFileName(url)) triggerDownload(url); else window.open(url, "_blank", "noopener"); }
  function stepEl(text) {   // a .ph-step that bolds *…*-wrapped names (app / screen / menu / button labels)
    var d = el("div", "ph-step"), parts = String(text).split("*");
    for (var i = 0; i < parts.length; i++) { if (i % 2) d.appendChild(el("b", null, parts[i])); else if (parts[i]) d.appendChild(document.createTextNode(parts[i])); }
    return d;
  }
  // the 3 buttons are a COMPACT popover above the button bar (like the Safari ask-on-tap) — NOT a full-screen card
  function showVktgzChoice(c, anchor) {
    closeStartChoice(); closeDlBubble(); closeVktgzChoice(); closeVktgzHint();
    var b = el("div", "start-choice mz-choice");
    b.appendChild(el("div", "start-choice-t", "VK TURN Proxy"));
    var mk = function (n, label, sub, fn, go) {
      var btn = el("button", "start-choice-b mz-cbtn" + (go ? " go" : "")); btn.type = "button";
      btn.appendChild(el("span", "mz-num", String(n)));
      var col = el("span", "mz-cbtn-col");        // label + a secondary line (the download filename / a hint), stacked
      col.appendChild(el("span", "start-choice-l", label));
      if (sub) col.appendChild(el("span", "start-choice-s", sub));
      btn.appendChild(col);
      // button 3 transitions to the walkthrough (raw close → keep the one Back entry); 1 & 2 just close (drop it).
      btn.onclick = function () { if (go) closeVktgzChoice(); else dismissHints(); fn(); };
      return btn;
    };
    b.appendChild(mk(1, t("mzBtn1"), urlFileName(c.dlAppUrl) || c.dlAppName || "", function () { _openUrl(c.dlAppUrl); }));   // direct APK — its filename below
    b.appendChild(mk(2, t("mzBtn2"), urlFileName(coreUrlFor(c.forkId)), function () { _openUrl(coreUrlFor(c.forkId)); }));   // direct core binary (THIS fork's core) — its filename below
    b.appendChild(mk(3, t("mzBtn3"), t("mzBtn3Sub"), function () {                                                            // copy VKTGZ + walkthrough
      if (navigator.clipboard) navigator.clipboard.writeText(c.payload || "").catch(function () {});
      showVktgzHint(c);
    }, true));
    document.body.appendChild(b);
    // the tapped Start button lives IN the action bar → its own .pbar is the reliable anchor (a pager slide's bar
    // moves with the carousel, so scope to the button, not the first .pbar in the document).
    var bar = (anchor && anchor.closest && (anchor.closest(".pbar") || (anchor.closest(".ppage") && anchor.closest(".ppage").querySelector(".pbar")))) || document.querySelector(".pbar") || document.querySelector(".bar");
    var barTop = bar ? bar.getBoundingClientRect().top : (window.innerHeight - 76);
    // seat the card just ABOVE the buttons area, clamped by its measured height so it can never overlap the bar
    // (top clamp) nor spill past the viewport bottom (bottom clamp) whatever the scroll position.
    var ch = b.getBoundingClientRect().height;
    var top = Math.max(8, Math.min(barTop - ch - 12, window.innerHeight - ch - 8));
    b.style.left = "50%"; b.style.transform = "translateX(-50%)"; b.style.bottom = "auto"; b.style.top = top + "px";
    _vktgzChoice = b;
    setTimeout(function () {
      document.addEventListener("mousedown", _mzOutside, true);
      document.addEventListener("keydown", _mzKey, true);
      window.addEventListener("resize", closeVktgzChoice);
    }, 0);
    armOverlayBack();
  }
  function showVktgzHint(c) {
    closeVktgzHint(); closeVktgzChoice();
    var ov = el("div", "ih-overlay ph-overlay mz-ov");
    var inner = el("div", "ih-inner ph-inner");
    var done = el("div", "ph-copied"); done.appendChild(iconEl("checks")); done.appendChild(el("span", null, t("mzCopied")));
    inner.appendChild(done);
    var head = el("div", "ph-head"); head.appendChild(el("span", "ph-title", "VK TURN Proxy")); inner.appendChild(head);
    var steps = el("div", "ph-steps");
    for (var i = 1; i <= 11; i++) steps.appendChild(stepEl(t("mzStep" + i)));
    inner.appendChild(steps);
    var links = el("div", "mz-links");
    var la = el("a", "ph-dl"); la.href = "#"; la.textContent = t("pasteDownload"); la.onclick = function (e) { e.preventDefault(); _openUrl(c.dlAppUrl); }; links.appendChild(la);
    var lc = el("a", "ph-dl"); lc.href = "#"; lc.textContent = t("mzGetCore"); lc.onclick = function (e) { e.preventDefault(); _openUrl(coreUrlFor(c.forkId)); }; links.appendChild(lc);
    var lg = el("a", "ph-dl"); lg.href = "#"; lg.textContent = t("mzGetConfig"); lg.onclick = function (e) { e.preventDefault(); if (c.wgConf) download(c.wgConf, c.base, "conf"); }; links.appendChild(lg);
    inner.appendChild(links);
    ov.appendChild(inner);
    var x = el("button", "ih-close"); x.type = "button"; x.setAttribute("aria-label", "Close"); x.textContent = "×"; x.onclick = dismissHints; ov.appendChild(x);
    ov.onclick = function (e) { if (e.target === ov) dismissHints(); };
    document.body.appendChild(ov); _vktgzHint = ov;
    attachSwipeDown(ov, dismissHints);
    setTimeout(function () { document.addEventListener("keydown", _mzKey, true); }, 0);
    armOverlayBack();
  }

  // CLI (sidecar) client: Start copies the command — with the "./client" swapped to the ACTUAL downloaded binary for
  // this OS (Windows → .\client-windows-…exe) — and shows the OS's short run steps + client/config download links.
  var _cliHint = null;
  function closeCliHint() { if (!_cliHint) return; _cliHint.remove(); _cliHint = null; document.removeEventListener("keydown", _cliKey, true); }
  function _cliKey(e) { if (e.key === "Escape") dismissHints(); }
  // Format a raw "./client <flags>" cmd into a runnable line for this OS.
  function cliCmdStr(cmd, bin) {
    var flags = String(cmd || "").replace(/^\s*\.?[\\/]?client\s*/, "");
    return ((subOs() === "windows") ? ".\\" : "./") + (bin || "client") + (flags ? " " + flags : "");
  }
  function cliCommand(c) { return cliCmdStr(c.cmd, c.dlAppFile); }   // the native/preferred author's command (what Start copies)
  function showCliHint(c) {
    closeCliHint();
    var ov = el("div", "ih-overlay ph-overlay mz-ov");
    var inner = el("div", "ih-inner ph-inner");
    var done = el("div", "ph-copied"); done.appendChild(iconEl("checks")); done.appendChild(el("span", null, t("cmdCopied")));
    inner.appendChild(done);
    var head = el("div", "ph-head cli-head");
    head.appendChild(el("span", "ph-title", (c.forkId ? c.forkId + " " : "") + "Sidecar"));
    inner.appendChild(head);
    var steps = el("div", "ph-steps"), arr = ((t("cliSteps") || {})[subOs()]) || ((t("cliSteps") || {}).linux) || [];
    for (var i = 0; i < arr.length; i++) steps.appendChild(stepEl(arr[i]));
    inner.appendChild(steps);
    // one block per compatible CLI build (NATIVE first): "Download the binary by <author>" (fork-coloured) + its own command
    var authors = (c.cliAuthors && c.cliAuthors.length) ? c.cliAuthors : [{ fork: "samosvalishe", cmd: c.cmd, native: false }];
    var alist = el("div", "cli-authors");
    authors.forEach(function (a) {
      var col = forkColor(a.fork), owner = ((turnServer(a.fork) || {}).owner) || "";
      var dl = (a.fork === "samosvalishe" && c.dlAppUrl) ? c.dlAppUrl : ("https://github.com/" + owner + "/releases");
      var row = el("div", "cli-author");
      var hd = el("div", "cli-auth-hd");
      var lnk = el("a", "ph-dl cli-auth-dl"); lnk.href = dl; lnk.style.color = col;
      lnk.textContent = t("cliDownBy").replace("{author}", a.fork);
      lnk.onclick = function (e) { e.preventDefault(); _openUrl(dl); };
      hd.appendChild(lnk);
      row.appendChild(hd);
      var cmdS = cliCmdStr(a.cmd, "client");
      var cbox = el("pre", "cfgtext cmdtext cli-auth-cmd", cmdS); cbox.title = t("tapCopy");
      cbox.onclick = function () { if (navigator.clipboard) navigator.clipboard.writeText(cmdS).catch(function () {}); showToast(t("cmdCopied")); };
      row.appendChild(cbox);
      alist.appendChild(row);
    });
    inner.appendChild(alist);
    var links = el("div", "mz-links");
    var lg = el("a", "ph-dl"); lg.href = "#"; lg.textContent = t("mzGetConfig"); lg.onclick = function (e) { e.preventDefault(); if (c.payload) download(c.payload, c.base, c.ext || "conf"); }; links.appendChild(lg);
    inner.appendChild(links);
    ov.appendChild(inner);
    var x = el("button", "ih-close"); x.type = "button"; x.setAttribute("aria-label", "Close"); x.textContent = "×"; x.onclick = dismissHints; ov.appendChild(x);
    ov.onclick = function (e) { if (e.target === ov) dismissHints(); };
    document.body.appendChild(ov); _cliHint = ov;
    attachSwipeDown(ov, dismissHints);
    setTimeout(function () { document.addEventListener("keydown", _cliKey, true); }, 0);
    armOverlayBack();
  }

  // brief centred toast (e.g. "link copied")
  var _toastEl = null, _toastT = 0;
  function showToast(msg) {
    if (_toastEl) { try { _toastEl.remove(); } catch (_) {} clearTimeout(_toastT); }
    var el2 = el("div", "sub-toast", msg); document.body.appendChild(el2); _toastEl = el2;
    _toastT = setTimeout(function () { try { el2.remove(); } catch (_) {} if (_toastEl === el2) _toastEl = null; }, 2800);
  }

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
    check: [["path", { d: "M20 6 9 17l-5-5" }]],
    launch: [["path", { d: "M14 4h6v6" }], ["path", { d: "M20 4l-8 8" }], ["path", { d: "M18 14v3a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V9a3 3 0 0 1 3-3h3" }]],
    link: [["path", { d: "M9.5 14.5l5-5" }], ["path", { d: "M11.5 6.5l1.2-1.2a3.6 3.6 0 0 1 5.1 5.1L17.7 11.4" }], ["path", { d: "M12.5 17.5l-1.2 1.2a3.6 3.6 0 0 1-5.1-5.1L6.3 12.6" }]],
    checks: [["path", { d: "M1.5 13.5l4 4 9-9" }], ["path", { d: "M10.5 14.5l.7.7 9-9" }]]   // double check (copied)
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
  // The signature START button face: a glowing brand orb (radial gradient) with two pairs of radiating "connect"
  // arcs and a central power glyph — reads as start / turn-on / go. Inline SVG so it themes off the CSS vars.
  var START_SVG =
    '<svg viewBox="0 0 100 100" aria-hidden="true" focusable="false">' +
    '<defs><radialGradient id="startorb" cx="50%" cy="34%" r="74%">' +
    '<stop offset="0" stop-color="var(--brand-2)"/><stop offset=".62" stop-color="var(--brand)"/>' +
    '<stop offset="1" stop-color="color-mix(in srgb, var(--brand) 72%, #000)"/></radialGradient></defs>' +
    '<circle cx="50" cy="50" r="47" fill="url(#startorb)"/>' +
    '<g fill="none" stroke="var(--brand-ink)" stroke-linecap="round">' +
    '<path d="M31 33 a29 29 0 0 0 0 34" stroke-width="3" stroke-opacity=".30"/>' +
    '<path d="M69 33 a29 29 0 0 1 0 34" stroke-width="3" stroke-opacity=".30"/>' +
    '<path d="M23 25 a41 41 0 0 0 0 50" stroke-width="2.4" stroke-opacity=".15"/>' +
    '<path d="M77 25 a41 41 0 0 1 0 50" stroke-width="2.4" stroke-opacity=".15"/></g>' +
    '<g stroke="var(--brand-ink)" stroke-width="6" stroke-linecap="round" fill="none">' +
    '<path d="M50 27 v19"/><path d="M38.5 38 a17 17 0 1 0 23 0"/></g></svg>';
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
    awg: '<svg viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="av" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="512" y2="512"><stop offset="0" stop-color="#1FC8D6"/><stop offset="1" stop-color="#2B7CD3"/></linearGradient></defs><path d="M174.6 444.7c7.7-.6 18.2.3 17-12.5-5.1-1.9-10.6-3.8-15.4-6.1-.6-.3-1.3-.6-1.9-1-9.6 6.1-15.4 16.3-24.6 22.7-.3.6-1 1-1.3 1.6 1.6.3 3.5 1 5.4 1.6 7.4.4 13.8-5.3 20.8-6.3 M0 388.4c.3.3.6.6 1 .3h.3v-2.9L0 387.1zm280.5-152.9c6.7-.3 13.4-.3 19.8 3.8 1 0 1.9-.3 2.6 0 16.3 10.2 7.7-7.7 7.7-8.6 0-2.9.3-5.4 1-7.7-2.2-4.2-4.2-8.3-5.8-12.5-4.2-11.5-7.7-23.3-11.5-34.9-4.2 9-8 18.2-11.2 27.8-.3.6-.6 1.3-1.3 1.9-2.2 2.6-6.7 2.6-10.9 1.9 2.6 5.4 4.8 10.9 6.7 16.6 1.6 3.7 2.6 7.9 2.9 11.7m28.2-90.2c-1.9 4.5-4.2 9-6.1 13.1 22.4 8.3 42.5 20.2 60.1 36.1 2.9 2.6 5.1 5.4 7.4 8.3 1.3 1.6 2.2 3.5 3.2 5.4 4.5.3 9.3 0 13.8-2.2 3.2-1.6 6.1-4.5 9-6.7 0 0-.3 0-.3-.3 5.4-7.7 12.8-14.7 16.6-22.7-2.6-1.9-5.1-3.8-8-5.4-2.6-1.6-3.8-4.5-2.6-7.4.3-.6.6-1.6 1.3-2.2 1-2.2.3-5.1-1.6-6.4-2.6-1.6-5.4-2.9-8.3-2.9-1.6 0-3.5-.3-4.8-1.6-8.6-7.7-16.3-15.7-24.9-22.4-12.2-9.6-24.6-18.6-37.1-27.5-4.5-3.2-9.9-4.5-15.7-4.5-4.8.3-9.6 0-14.1 0h-.6c1.9 5.1 4.5 9.9 5.1 15.4 1.2 12.2 12.7 22.7 7.6 33.9 M127.6 472.5c-1.9 2.9-4.5 5.1-6.1 8.3-4.2 9-4.8-1.6-8-1.6h-3.2c-.6 2.6-1.3 5.4-1.6 8-.6 2.9-.6 6.1-1 9-.3 3.2 2.2 5.8 5.1 4.8 3.5-1.3 5.8-3.5 7.4-7 2.2-5.4 4.2-10.6 6.1-16-.3-1 1-3.5 1.3-5.5m328.2-251.4 1.6-1.6c14.1-12.8 30.4-21.7 47.7-29.4 2.2-1 4.5-2.2 6.7-3.2.3 0 .3-.6 0-.6h-.3c-9.6-1.3-18.2-.3-27.5 1.6-6.1 1.3-12.2 2.9-18.2 4.2-.3 2.2-1 4.8-1.9 7-2.7 7.6-5.2 15-8.1 22m-21.1 35.2c-2.2 3.5-4.2 7.7-6.7 11.2-3.2 4.5-7.7 8.3-15 8.6-2.9 0-6.4-2.6-9.3-2.2-.6 23.3-2.6 46.7-8.3 69.7-2.9 10.9-7 21.1-12.5 31.7-1.6 3.2-6.4 3.8-8.3 1-.3-.3-.3-.6-.6-1.3-6.1-13.1-12.2-25.9-17.3-39-.6-1.6-1-2.9-1.6-4.5l-4.8 4.8c-4.2 4.5-10.9 6.7-15.7 10.6-3.2 2.6-6.7 4.2-10.2 5.1 1.9 3.8 3.8 7.7 6.1 11.2 6.4 10.9 12.2 21.7 15.4 33.9 3.5 13.4 2.6 17-9.6 24-11.5 6.7-23.7 12.8-35.8 18.9-2.2 1.3-5.1 1.6-7.7 1.6-9.6.3-19.2 0-28.8 0-21.4.6-42.9.3-63.7-5.8-.6 13.4-12.8 19.8-21.4 24.6-1.3.6-2.2 1.3-2.9 1.9 2.6 1.3 4.8 2.6 7.4 3.5 1.3.6 2.6 1 3.8 1.3 5.4 1 10.9 1.3 16 2.2 16 2.6 31.7 6.1 47.7 8 16.6 1.9 33.3.6 49.3-5.4 14.4-5.4 29.1-10.6 43.5-15.7 7.4-2.6 15.4-3.5 23-3.5 1.9 0 3.8 1.3 4.8 3.2 1.3 2.2 2.9 3.5 6.7 5.1 1.3.6 2.2 1.6 2.9 2.6 1.6 3.8 3.5 7.7 5.1 11.5 4.2 8.6 9 17 17 22.7 1.3 1 2.9 1.6 4.8 2.2s4.2-.6 3.8-2.6c-1.3-10.9-2.2-21.4-4.5-32-2.9-12.8-6.1-25.6-7-39-.6-10.2 1.6-19.5 8.3-27.5 6.4-8 12.5-16 18.9-24 8-9.9 13.1-20.8 12.2-34.2-1-13.1-.6-25.9 3.5-38.7 2.9-8.6 5.4-17.3 11.5-24.6 3.8-4.8 6.4-10.2 7.4-16.3.3-2.9-1.9-5.1-4.8-5.1H444c-2.6 0-4.8-1.9-5.1-4.5v-.6c-.6 1-1.3 1.9-1.9 2.6-.7.6-1.7 1.9-2.3 2.8 M97.9 250.9c2.2-.6 4.5-1 7-1.6.6-.3 1.3-.3 1.9-.6.3 0 .3 0 .6-.3 9.6-20.5 23.7-37.4 40-52.8 11.5-10.9 24-20.2 37.4-28.5 0-3.2.3-6.4 1.3-9.6 1.3-4.2 1.6-9 2.6-13.4 0-.6.3-1.3.3-1.9 0-.3 0-.6.3-1.3 3.2-10.2 5.1-20.5 6.1-30.7-14.1 4.2-27.8 8.6-42.2 12.5-4.8 1.3-7.7 3.8-10.2 8-5.4 9-11.5 17.6-17.6 26.2-1.3 1.9-2.9 3.2-4.5 4.8-1.3 1.3-3.5 1.3-4.8 0-1.6-1.6-4.5-1-5.4 1.3-1 2.6-1.9 5.1-3.2 7.4-2.2 3.8-3.2 9-7.4 10.6-1.9.6-3.8 1.6-4.8 3.5-6.7 14.4-13.4 28.5-20.2 42.5-4.2 10.2-8 19.5-11.2 29.1 9.3-.6 18.2-1.6 27.2-3.5 2.3-.4 4.5-1.1 6.8-1.7 M221.3 218.3c-1.6 1.9-1.3 5.1-2.2 7.4.3 0 .3.3.6.3 1-2.6 1.6-5.4 2.6-8-.6-.4-1-.1-1 .3M189 142.4c-.3.6-.3 1.3-.6 1.9-1 4.5-1 9-2.6 13.4-1 3.2-1.3 6.4-1.3 9.6 1.3-.6 2.2-1.6 3.5-2.2 3.5-1.9 7-3.5 11.2-3.5 1.9 0 3.2 1.9 2.6 3.8-6.1 19.5-12.5 39-18.6 58.5 11.2-1.3 20.5-8.6 29.1-18.2l1-1c.6-.6 2.6-1.6 2.6-1.6 2.6 3.2 5.1 6.4 7.7 9.6 2.2-7 4.5-13.8 6.4-20.8 2.6-8 5.4-16 8.3-24 .6-1.6 1.3-3.5 2.2-4.8 1.9-2.9 4.8-2.9 6.7 0 8.3 14.7 17 29.1 24 44.5 4.2.6 8.6.6 10.9-1.9.3-.3.6-1 1-1.6 3.2-9.6 7-18.9 11.5-28.1-1.9-6.1-3.8-12.2-5.8-18.2v-.6l1-1c3.5.6 7.4 1 10.9 2.2.6.3 1.3.6 1.9.6 1.9-4.2 4.2-8.6 6.1-13.1 4.8-11.5-6.7-22.1-8-33.6-.6-5.4-3.2-10.6-5.4-15.7-11.8-.6-20.5-5.4-24.9-17-3.5-8.6-6.4-17.6-9.3-26.9-1-3.5-2.2-7-3.2-10.6-1 2.9-1 6.1-1.3 8.3-.3 6.4-4.5 9.6-6.1 14.7-.6-.3-1-.3-1.6-.3-5.1-.3-10.6 4.5-15.4 5.4-.3 2.6-.6 4.8-1 7.4-1.6 10.6-8.3 16-18.6 17.6-9.6 1.6-10.6 2.2-11.5 11.8 0 .6-1 1-1.6 1.3-1.9.6-3.8 1.3-5.8 1.9-1 10.2-2.6 20.8-6.1 30.7.5.9.1 1.2.1 1.5 M250.8 65.7c1.6-5.1 5.8-8.3 6.1-14.7 0-2.2.3-5.4 1.3-8.3-2.2-7-4.2-14.1-6.4-21.1-1-2.9-2.2-5.4-3.5-8s-4.5-3.8-6.7-1.6c-1.6 1.9-2.6 4.2-3.2 8-1 9-1.6 17.6-2.6 26.5-.6 8-1.3 16-2.2 24 4.8-1 10.2-5.8 15.4-5.4.8.3 1.1.6 1.8.6 M409.7 205.5c-5.4 9-4.8 22.4-17 26.5-3.5 1.3-7 1.6-10.6 1.9-2.6.3-5.1.6-7.7 1-1 .3-1.6.3-2.6.6-12.8 3.5-20.2 12.8-30.1 19.2-2.9 1.9-6.4 2.6-9.6 3.8.6 11.5-2.9 22.4-8 32.3-1.9 3.5 1.6 9.6-1.9 11.8-.6.6-1.9 1-3.5 1-1.9 0-3.8.6-5.4 1 1.3 3.5 2.2 7 2.9 10.9 11.2-.6 21.4-3.8 30.7-9.3-1.9-6.1-3.8-12.2-5.8-17.9-1-2.6-1.3-5.1-1.6-7.7-1.3-7 0-9.6 6.4-13.1 11.5-6.7 23.7-11.2 36.5-14.4 5.8-1.6 11.8-2.2 17.9-3.5 1.3-.3 2.6 0 3.8 0 0 .6.3 1.3.3 1.9v2.9c2.2-7 6.4-13.4 14.4-19.8 13.4-10.2 23.7-23 28.8-38.1-5.4 1-10.2 0-14.7-3.5-2.6-1.9-5.4-4.2-7.7-6.1-.3-.3-1-.6-1.3-1-4.3 7.4-7.8 14.4-14.2 19.6 M374.9 216.7c0 1.6-1.3 3.2-2.6 3.8-13.4 6.7-26.5 14.7-42.2 16.3-6.7.6-11.5-1.6-14.7-7-1.3-2.2-2.2-4.5-3.5-6.4-.6 2.2-1 4.8-1 7.7 0 1 8.6 18.9-7.7 8.6-.6-.3-1.6 0-2.6 0 10.6 6.4 20.8 13.1 31.3 19.5 3.2-1.3 6.7-1.9 9.6-3.8 9.9-6.1 17.3-15.7 30.1-19.2 1-.3 1.6-.3 2.6-.6 2.6-.6 5.1-1 7.7-1 3.5-.3 7-1 10.6-1.9 12.2-4.2 11.8-17.6 17-26.5l-.3.3c-3.8-1.9-8-3.8-11.8-5.8-.3-.3-.6-.3-1.3-.6-2.9 2.2-5.8 4.8-9 6.7-4.8 2.2-9.3 2.9-13.8 2.2.9 1.9 1.6 4.8 1.6 7.7 M332 258.6c-10.6-6.4-20.8-13.1-31.3-19.5-6.1-4.2-12.8-3.8-19.8-3.8 0 .6.3 1.3.3 1.9 1 7-1.6 12.8-7.7 16.6-6.4 4.2-13.4 7.4-20.5 9.6.3 2.9.6 5.8 1 8.6.6 7 1.3 13.8 1.6 20.8 13.1-2.9 26.2-3.8 39.7-3.8 7 0 12.2 3.2 15.7 9.3 1 1.9 1.9 4.2 2.9 6.4 1.6-.6 3.5-1 5.4-1.3 1.6 0 2.6-.3 3.2-1 3.5-2.2.3-8.3 1.9-11.8 4.7-9.7 7.9-20.2 7.6-32 M86.7 302.1c1.6 0 3.2.3 4.5.3h3.5c.6-8.6 1.6-17.3 3.5-25.6-13.4.3-26.9.6-40.3.3-1.9 8-3.5 16.3-4.5 24.6 11.2-.9 22.4-.6 33.3.4 M418 235.2c-8 6.1-12.2 12.8-14.4 19.8v18.6c2.9-.3 6.4 2.6 9.3 2.2 7.4-.3 11.5-3.8 15-8.3 2.6-3.5 4.5-7.4 6.7-11.2.6-1.3 1.6-2.2 2.6-3.5.6-.6 1.3-1.6 1.9-2.6 0-6.1 1.3-11.8 5.1-16.3 3.5-4.5 7.4-9 11.5-12.8 3.2-7 5.8-14.4 8-21.7.6-2.2 1.3-4.8 1.9-7-5.8 1.3-11.2 2.9-17 4.2-.6 0-1.3.3-1.6.3-5.3 15-15.5 28.1-29 38.3 M176.6 245.8c4.2.6 8 1.6 11.8 3.8 2.9.3 6.1 1 9 1.3 4.8 0 9.3.3 14.1.3 2.9-8.6 5.4-17.3 8.3-26.2-.3 0-.3-.3-.6-.3 1.3-2.2.6-5.4 2.2-7.4.3-.3.6-.3 1-.6.6-1.6 1-3.2 1.6-4.8-2.6-3.2-4.8-6.4-7.7-9.6 0 0-1.9 1-2.6 1.6l-1 1c-8.6 9.6-17.9 17-29.1 18.2-2.6 7.9-4.8 15.3-7 22.7 M396.3 199.7c.3.3.6.3 1.3.6 3.8 1.9 8 3.8 11.8 5.8l.3-.3c6.4-5.1 9.9-12.2 13.4-19.5-3.5-3.2-6.7-6.4-10.2-9.3-3.8 8-11.2 15-16.6 22.7q0-.45 0 0 M2.6 388.4v-3.5l-1 1v2.9c.3-.1.6-.1 1-.4 M10.9 386.5c13.1-2.9 25.9-6.4 39-9 2.9-.6 5.4-.6 7.7-.3 2.2-1 4.2-2.2 6.1-3.5 10.9-9 23.7-10.9 36.8-11.2.3-3.2 2.6-5.8 5.1-8 7.4-6.4 16-8.6 25.6-9.6 3.2-.3 6.1 2.6 5.4 5.4 0 .6-.3 1.3-.3 1.6-1.3 4.2-2.2 8.3-3.5 12.8 3.8-1.9 8-3.2 12.8-1 7 3.5 15-.3 22.7 0 10.9-29.1 33.6-51.8 65.2-64.3-1-6.7-2.9-13.4-5.8-19.8-3.8-8.3-11.5-11.5-22.7-6.1-12.5 6.1-26.2 10.6-40 8-.3 1-.6 1.6-.6 2.6-.6 1.9-1.9 4.2-3.8 5.4-4.5 3.2-9 6.4-13.8 8.6-15.4 7.7-31 13.8-48 16.6-1.3.3-2.6.3-4.5.3 0-4.5.3-8.6.6-13.1h-3.5c-1.6 0-3.2 0-4.8-.3-10.9-1-22.1-1-32.9-.6-1.3 11.8-1.6 24-1 36.5 0 1.6-.6 3.5-1.6 4.8-5.4 5.4-10.9 10.9-16.6 15.7-9.6 8.3-19.8 16.3-29.4 24.3-1 .6-1.6 1.3-2.2 2.2v3.5c2.5-.2 5.1-.9 8-1.5 M238.3 297.6c5.4-1.9 11.2-3.5 17-4.5-.3-7-1-13.8-1.6-20.8-.3-2.9-.6-5.8-1-8.6-1.6.3-2.9 1-4.5 1.3-13.1 3.5-26.5 4.5-40 4.5-.6 0-1.3-.3-2.2-.3.3-1 .3-1.9.6-2.6 1.3-4.2 2.6-8.3 3.8-12.8-7-.6-12.5-1.6-13.4-2.9-2.9-.3-6.1-1-9-1.3-3.8-2.2-8-3.5-11.8-3.8-3.8 12.2-7.7 24-11.5 36.1 13.4 2.6 27.2-1.9 40-8 11.2-5.4 18.9-2.2 22.7 6.1 2.9 6.4 4.8 13.1 5.8 19.8 1.6-.9 3.5-1.6 5.1-2.2m-49.9-47.7c2.9.3 5.8 1 9 1.3-3.3-.3-6.1-1-9-1.3M124.1 405c5.8 1.6 11.8 1 17.3-2.6 6.4-4.2 13.1-8 20.2-10.6 1-9.9 3.2-19.2 6.4-28.1-7.7-.3-15.4 3.5-22.7 0-4.8-2.2-9-1-13.1 1-2.2 8-4.5 16-6.7 24-.3 1.3-1.3 2.6-2.6 2.9-2.6.6-4.8 0-7-1.3-9.3-6.1-13.8-15-15.7-25.6v-2.6c-13.1.3-25.6 2.2-36.8 11.2-1.6 1.3-3.8 2.6-5.8 3.5 4.8.6 9 2.9 12.2 8.6 5.1 9.3 12.8 17.3 20.5 24.6l2.6 2.6c6.9-7.6 18.7-11.1 31.2-7.6 M144.9 446.6c2.9-1.6 3.8-1 4.8 1.3 9-6.4 15-16.6 24.6-22.7-9-4.8-13.4-12.5-13.4-23.3 0-3.2.3-6.7.6-9.9-7 2.6-13.4 6.4-20.2 10.6-5.4 3.5-11.5 4.5-17.3 2.6-12.5-3.5-24.3 0-31 8 6.4 6.4 12.8 12.5 18.9 18.9 1 1 2.2 2.6 2.2 3.8 0 5.4.3 10.9 0 16.3 5.4 0 10.9-.3 16.6-.6 4.9-.5 9.7-2.4 14.2-5 M350.6 335.3c1.6-1.6 2.9-3.2 4.5-4.8-2.9-8-5.4-15.7-8-23.7-9.3 5.4-19.5 8.6-30.7 9.3.3 1.6.3 3.5.3 5.4.3 10.6 3.2 20.5 7.7 29.7 3.5-1 7-2.6 10.6-5.4 4.7-3.8 11.4-6 15.6-10.5 M149.7 447.9c-1.3-2.2-2.2-2.9-4.8-1.3-4.5 2.6-9.3 4.5-14.1 4.8-5.4.3-10.9.3-16.6.6 0 3.2-.3 6.7-.6 9.9-.6 5.8-1.9 11.8-3.2 17.6h3.2c3.5 0 4.2 10.6 8 1.6 1.3-3.2 3.8-5.4 6.1-8.3.3-.3.6-.6 1-1.3 1-3.5 1.9-7 3.2-10.6 3.2-8.6 9-12.5 16.6-11.2.6-.8.9-1.5 1.2-1.8 M200.2 435.1c-.6-.3-1.3-.3-1.9-.6-2.2-.6-4.5-1.3-6.7-2.2 1.3 12.8-9.3 11.8-17 12.5-7.4.6-13.4 6.7-20.8 6.4.3 0 .3 0 .6.3 7.4 3.2 14.4 7 21.4 10.6 1-.6 1.9-1.3 2.9-1.9 8.7-5.3 20.9-11.7 21.5-25.1m-72.6 37.4c-.6 2.2-1.6 4.5-1.3 6.1.6-1.3 1-2.9 1.6-4.2.3-1 .6-1.9 1-3.2-.3.4-1 .7-1.3 1.3 M98.5 276.1c1.6-7 3.5-13.8 6.1-20.5 1-2.6 1.9-4.8 3.2-7.4-.3 0-.3 0-.6.3-.6.3-1.3.3-1.9.6-2.6.6-4.8 1-7 1.6s-4.5 1-6.7 1.6c-9 1.9-17.9 2.9-27.2 3.5-2.2 6.7-4.2 13.8-5.8 20.5 12.7.5 26.2.5 39.9-.2 M211.4 251.8c-4.8 0-9.3-.3-14.1-.3.6 1.3 6.4 2.2 13.4 2.9.1-1.3.4-1.9.7-2.6" fill="url(#av)"/></svg>',
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
    var CEIL = 15, FLOOR = 3, f = CEIL, j;   // ceiling (config/link text never grows past this, even when it'd fit bigger); floor low so a huge AWG config still fits alongside the command
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
  // Fallback fork colours for an older panel with no catalog in the bundle; the catalog server's `color` is
  // authoritative when present (and the admin's turn_fork_colors override rides on top of either — THEME.forkOv).
  var FORK_COLORS_FALLBACK = {
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
  function forkColor(fork) { var s = turnServer(fork), d = (s && s.color) || FORK_COLORS_FALLBACK[fork] || { dark: "#8FA8C0", light: "#5E7085" }; return pickThemed(THEME.forkOv[fork], d.dark, d.light); }
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
    var ob = document.getElementById("os-btn");
    if (ob) { var cur = subOs(), lbl = (OS_LIST.filter(function (o) { return o[0] === cur; })[0] || ["", cur])[1];
      ob.innerHTML = OS_ICON[cur] || OS_ICON.linux; ob.title = t("osLabel") + ": " + lbl; }   // show the CURRENT OS's icon
    var menu = document.getElementById("os-menu");
    if (menu) [].forEach.call(menu.children, function (mi) { mi.classList.toggle("on", mi.getAttribute("data-os") === subOs()); });
  }
  // Header OS picker: a "devices" icon that opens a menu of the OSes — the choice re-generates the configs (settings
  // value-set) and swaps the downloads to that OS. Built once, in wireControls.
  function closeOsMenu() { var m = document.getElementById("os-menu"); if (m) m.hidden = true; document.removeEventListener("click", closeOsMenu); document.removeEventListener("keydown", _osKey); }
  function _osKey(e) { if (e.key === "Escape") closeOsMenu(); }
  function ensureOsControl() {
    var ctl = document.querySelector(".topctl"); if (!ctl || document.getElementById("os-btn")) return;
    var b = el("button", "ctl os-ctl"); b.id = "os-btn"; b.type = "button"; b.innerHTML = OS_ICON[subOs()] || OS_ICON.linux;   // the detected/selected OS's icon
    ctl.insertBefore(b, ctl.firstChild);   // OS picker sits first (left of language / theme)
    var menu = el("div", "os-menu"); menu.id = "os-menu"; menu.hidden = true;
    OS_LIST.forEach(function (o) {
      var mi = el("button", "os-mi"); mi.type = "button"; mi.setAttribute("data-os", o[0]);
      mi.innerHTML = "<span class='os-mi-ic'>" + (OS_ICON[o[0]] || "") + "</span>";   // icon + title
      mi.appendChild(el("span", "os-mi-t", o[1]));
      mi.onclick = function () { closeOsMenu(); setSubOs(o[0]); };
      menu.appendChild(mi);
    });
    document.body.appendChild(menu);
    b.onclick = function (e) {
      e.stopPropagation();
      if (!menu.hidden) return closeOsMenu();
      var r = b.getBoundingClientRect();
      // align the menu's LEFT edge with the button's left edge; if that would run off the right, shift it left to fit
      menu.style.top = (r.bottom + 8) + "px"; menu.style.right = "auto"; menu.style.left = "-9999px";
      menu.hidden = false;                                   // unhide first so offsetWidth is measurable
      var mw = menu.offsetWidth || 148;
      menu.style.left = Math.max(8, Math.min(r.left, window.innerWidth - mw - 8)) + "px";
      paintCtl();
      setTimeout(function () { document.addEventListener("click", closeOsMenu); document.addEventListener("keydown", _osKey); }, 0);
    };
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
      // Hysteresis: engage past 90px, release below 40px. Collapsing the header flips .bar to position:fixed and
      // changes document height; a single hard threshold let that height change re-cross the line and oscillate
      // (Firefox jumped back up). The dead-band + overflow-anchor:none (CSS) keep it stable.
      if (!landscape) { document.body.classList.remove("scrolled"); return; }
      var on = document.body.classList.contains("scrolled");
      if (!on && y > 90) document.body.classList.add("scrolled");
      else if (on && y < 40) document.body.classList.remove("scrolled");
    };
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update, { passive: true });
    update();
  }
  function wireControls() {
    suppressButtonFocus();
    wireStickyHeader();
    ensureOsControl();
    var lb = document.getElementById("lang-btn"), tb = document.getElementById("theme-btn");
    if (lb && !lb._wired) { lb._wired = 1; lb.onclick = function () {
      var en = LANGS.filter(function (l) { return SUPPORTED.indexOf(l) >= 0; }); if (!en.length) en = ["en"];
      setLang(en[(en.indexOf(LANG) + 1) % en.length]); }; }
    if (tb && !tb._wired) { tb._wired = 1; tb.onclick = function () { setTheme(isLight() ? "dark" : "light"); }; }
  }

  function showState(msg, sub, kind) {
    // kind (optional): "blocked" | "expired" renders the message as a prominent status WORD (red), shown under the
    // header username and before the explanatory text. Plain states (loading, errors) pass no kind → unchanged.
    var s = document.getElementById("state");
    s.hidden = false;
    s.className = "state" + (kind ? " state-" + kind : "");
    s.innerHTML = "";
    var h = el("p", "state-msg" + (kind ? " state-word" : ""), msg);
    s.appendChild(h);
    if (sub) s.appendChild(el("p", "state-sub", sub));
    document.getElementById("peers").hidden = true;
  }

  // Download base name: nodename_<port>_<peer-last-ip-octet>. The port is the interface's listen port for a WG/AWG
  // config, or the turn-proxy's listen port for a turn config — so WG and turn files for the same peer never collide.
  function fileName(tgt, mode, tp) {
    var node = tgt.node_name || tgt.node || "node";
    var port = (mode === "turn" && tp)
      ? ((String(tp.listen || "").split(":").pop()) || (String(tp.service || "").match(/(\d+)\D*$/) || [])[1] || "")   // turn-proxy listen port
      : (String(tgt.endpoint || "").split(":").pop() || "");                                                            // iface listen port (from Endpoint)
    var ipLast = (String(tgt.ip || "").split("/")[0].split(".").pop()) || "";   // last octet of the peer's tunnel IP
    var s = node + "_" + port + "_" + ipLast;
    return s.replace(/[^\w.-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60) || "swg";
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
      // "Get … manually" → a bubble of the WG/AWG client apps for this OS (Amnezia VPN, AmneziaWG, WireGuard). Amnezia
      // VPN leads (the only vpn:// one-tap, Android) but all are offered; the Start button's get-app falls back to it.
      var wga = wgGetApp(tgt.type);
      if (wga) node.appendChild(getAppRow(wga));   // under the server/app name line (in the header block)
    }
    var stage = el("div", "scell-stage");
    cell.appendChild(node); cell.appendChild(stage);

    var conf = secret && secret.k ? confFor(secret, tgt) : null;
    var ctrl = { ready: false, payload: "", ext: "conf", isLink: false, hasQR: false, cmd: null, view: "qr",
                 base: fileName(tgt, mode, it.tp), redraw: null, notify: null,
                 srvName: (tgt.node_name || tgt.node || tgt.iface || "server"), srvColor: nodeColor(tgt.node, ifaceColor(tgt.type)),
                 // enlarged-QR caption tail = the CLIENT app: WG/AWG cells name WireGuard/AmneziaWG; a turn cell overrides it with its app below.
                 zoomTail: (mode !== "turn" ? (tgt.type === "awg" ? "AmneziaWG" : "WireGuard") : (tgt.node_name || tgt.node || tgt.iface || "")) };

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
        box.onclick = function () { zoomQR(ctrl.payload, [peer.title, ctrl.zoomTail].filter(Boolean).join(" · ")); };
        var cmdQ = cmdBlock(true);               // QR view: keep the "Client command" label, same as the config view
        if (!cmdQ) { stage.appendChild(box); }   // plain single QR
        else {                                   // dual config: QR replaces the WG/AWG config, the command stays under it
          var wrapq = el("div", "textwrap"); wrapq.appendChild(box); wrapq.appendChild(cmdQ);
          stage.appendChild(wrapq); attachFit(wrapq);
        }
      } else if (ctrl.view === "link" && ctrl.openUri) {   // WG/AWG third view: the vpn:// deep-link as copy-able text
        var wrapL = el("div", "textwrap");
        var cfgL = el("div", "cfgwrap");
        var preL = el("pre", "cfgtext wrap", ctrl.openUri); preL.title = t("tapCopy");
        preL.onclick = function () { if (navigator.clipboard) navigator.clipboard.writeText(ctrl.openUri).catch(function () {}); flashCopied(cfgL); };
        cfgL.appendChild(preL);
        cfgL.appendChild(copyBtn("cfgcopy", function () { return ctrl.openUri; }, cfgL));
        wrapL.appendChild(cfgL);
        stage.appendChild(wrapL); attachFit(wrapL);
      } else if (ctrl.view === "config" && ctrl.wgConf) {   // MYSOREZ third view: the underlying WG/AWG .conf as text (the VKTGZ QR/string are the other two)
        var wrapW = el("div", "textwrap");
        var cfgW = el("div", "cfgwrap");
        var preW = el("pre", "cfgtext", ctrl.wgConf); preW.title = t("tapCopy");
        preW.onclick = function () { if (navigator.clipboard) navigator.clipboard.writeText(ctrl.wgConf).catch(function () {}); flashCopied(cfgW); };
        cfgW.appendChild(preW);
        cfgW.appendChild(copyBtn("cfgcopy", function () { return ctrl.wgConf; }, cfgW));
        wrapW.appendChild(cfgW);
        stage.appendChild(wrapW); attachFit(wrapW);
      } else {
        var wrap = el("div", "textwrap");
        var cfgwrap = el("div", "cfgwrap");   // relative box so the copy affordance sits in the bottom-right corner
        var pre = el("pre", "cfgtext" + (ctrl.wrapCfg ? " wrap" : ""), ctrl.payload); pre.title = t("tapCopy");
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
      var ga = turnGetApp(forkId);   // resolves the client for the VISITOR'S OS (also drives the get-app row / Start button below)
      // Encode the artifact for the app we actually RESOLVED for this OS (its encoder), not the fork's NATIVE app — so
      // the config always matches the app shown. A Moroka8 relay reached via anton48's VK TURN Proxy on iOS must get the
      // vkturnproxy:// deeplink, NOT a sidecar CLI command that GUI can't run; on desktop the same fork resolves to the
      // CLI and gets the ./client command. Cross-fork pairings (enc's home fork ≠ relay fork) stay flagged experimental.
      var asClient = (ga && ga.enc) ? ga.enc : null;
      var art = conf ? SWGTurn.artifact(conf, tp, vkLink, turnClientCS(forkId, asClient), (_lastData && _lastData.vk_links), asClient) : null;   // SETTINGS SPLIT: the RESOLVED client's saved values (asClient) + all VK links. _lastData (NOT `data` — makeCell isn't nested in render()) is the current payload, set at render() entry.
      // App name shown = the OS-resolved client's name (the OS-specific product name — desktop "WINGS DeX" vs Android
      // "WINGS V" — else that client's name, e.g. the CLI on desktop); only when NO client ships for this OS does it
      // fall back to the encoder's app name. Keeps the badge in step with the OS-correct download (never a wrong-OS app).
      var appName = (ga && (ga.productName || ga.app)) || (art && art.app);
      // app badge: a branded/resolved app name → "{fork} · {app}"; otherwise just "{fork} app". Every fork now resolves
      // to a client for the visitor's OS (cacggghp → VK TURN Proxy on mobile, CLI on desktop), so there's no "no app" case.
      var appInfo = appName ? { badge: appName, kind: "app", app: appName }
                  : { badge: t("forkApp").replace("{fork}", forkId), kind: "fork", fork: forkId };
      // badge = just the fork when it echoes its own id (a generic fork like Moroka8 with no app name); "fork · App"
      // when there's a real app name (WINGS V/DeX, FreeTurn, WireGuard-TURN, VK TURN Proxy, CLI client)
      var hasAppName = appName && appName !== forkId;
      ctrl.app = appName;   // Axis-3: the client app name for the "Open in {app}" deep-link button
      // Colour the app name by the fork its client is NATIVE to (server used vs app's home fork). Same fork for a
      // native pairing → one colour; a cross-fork (experimental) app → the app chip takes its own fork's colour.
      var appFork = (art && typeof SWGTurn.encoderFork === "function" && SWGTurn.encoderFork(art.enc)) || forkId;
      var appColor = forkColor(appFork);
      // Enlarged-QR caption (peer.title · …): a turn cell names the APP; the main-screen caption keeps the server name.
      ctrl.zoomTail = hasAppName ? appName : forkId;
      // Badge = "<server used> · <app>": the server chip in the used fork's colour, the app chip in its native fork's.
      var tag = el("span", "scell-tag");
      var srvChip = el("span", null, forkId); srvChip.style.color = fc; tag.appendChild(srvChip);
      if (hasAppName) {
        tag.appendChild(el("span", "scell-tag-sep", " · "));
        var appChip = el("span", null, appName); appChip.style.color = appColor; tag.appendChild(appChip);
      }
      srvRow.appendChild(tag);
      // role + interface next to the badge: multi → "Primary/Backup WG"; single → "WG". Primary/single = iface colour, backup = grey.
      var ifaceUp = (tgt.type === "awg") ? "AWG" : "WG";
      var isBackup = multi && !tgt.primary;
      var role = el("span", "scell-role" + (isBackup ? " scell-backup" : ""), (multi ? (tgt.primary ? t("primary") : t("backup")) + " " : "") + ifaceUp);
      if (!isBackup) role.style.color = ifaceColor(tgt.type);
      srvRow.appendChild(role);
      // Plain (unobfuscated) → the fork's normal transport, which VK throttles: mark it slow with a brand-coloured turtle.
      if (turnCellPlain(forkId)) { var slow = el("span", "scell-slow"); slow.title = t("slowPlain"); slow.innerHTML = TURTLE_SVG; srvRow.appendChild(slow); }
      // AXIS-3: "Get the app" install link under the badge — for a first-time user who doesn't have the client app
      // yet. Shown only when the fork's client has a published app link (CLI sidecar forks have none). Complements
      // the bar's "Open in app": open if you have it, get it if you don't (never branch on install-state — can't detect).
      if (ga) { ctrl.dlAppUrl = ga.file; ctrl.dlAppFile = ga.fileName; ctrl.dlAppName = ga.app; ctrl.dlAppPage = ga.page; ctrl.wgTurn = (ga.cid === "wgturn"); node.appendChild(getAppRow(ga)); }   // Start button → the DIRECT installer file; the text link (getAppRow) → the releases page
      ctrl.vktgz = !!(ga && ga.cid === "mysorez" && art && art.enc === "vktgz");   // MYSOREZ VK TURN Proxy app importing a VKTGZ: profile → the 3-button assemble flow
      ctrl.cliApp = !!(ga && ga.cid === "sidecar");   // the CLI (sidecar) client → copy the OS command + file-run steps
      ctrl.forkId = forkId;
      // The WG/AWG .conf the MYSOREZ user imports into a SEPARATE WireGuard client must dial the LOCAL turn core
      // (127.0.0.1:9000 — the VKTGZ profile's -listen), NOT the real server, exactly like the sidecar config. The
      // other clients don't need this: sidecar already rewrites it (artifact.text), WINGS/freeturn embed the local
      // endpoint inside their own import link, and kiper292/anton48 are integrated apps that keep the real Endpoint.
      ctrl.wgConf = (ctrl.vktgz && conf) ? conf.replace(/^([ \t]*Endpoint[ \t]*=).*$/m, "$1 127.0.0.1:9000") : conf;
      if (!conf) { draw(); return { el: cell, ctrl: ctrl }; }
      // VK-link notice (freeturn/samosvalishe forks): lives in the cell, positioned by syncVHints BETWEEN the
      // up-arrow and the box (the up-arrow moves up to make room). Same slot for the "no VK link" warning.
      if (art.vkMissing) {
        var vkw2 = el("div", "scell-vk scell-vkwarn");
        vkw2.appendChild(el("div", "scell-vkwarn-t", t("vkMissingT")));
        vkw2.appendChild(el("div", "scell-vkwarn-d", t("vkMissing").replace("{app}", t("theApp"))));
        cell.appendChild(vkw2);
      } else if (art.vk && !ctrl.vktgz) {   // MYSOREZ: the VKTGZ profile already embeds the VK link → no separate "add this link" prompt
        // show only the PRIMARY VK call link (tap-to-copy). The config still embeds every link for forks that accept
        // several; the on-screen prompt just names the one to add so it stays simple.
        var vall = (art.vkLinks && art.vkLinks.length) ? art.vkLinks : ((vkLink || "").trim() ? [(vkLink || "").trim()] : []);
        ctrl.vkPrimary = vall[0] || "";   // Start copies this — freeturn/samosvalishe apps can't auto-receive the VK link
        var vlist = vall.slice(0, 1);
        var vkw = el("div", "scell-vk");
        var vkLbl = (appInfo.kind === "app") ? t("vkAddApp").replace("{app}", appInfo.app)
                  : t("vkAddFork").replace("{fork}", appInfo.fork);
        vkw.appendChild(el("span", "scell-vklbl", vkLbl));
        vlist.forEach(function (raw) {
          var vkb = el("button", "scell-vkbtn", raw); vkb.title = t("tapCopy");
          vkb.onclick = function () { (navigator.clipboard ? navigator.clipboard.writeText(raw) : Promise.reject()).then(function () { var o = raw; vkb.textContent = t("copied"); setTimeout(function () { vkb.textContent = o; }, 1400); }, function () {}); };
          vkw.appendChild(vkb);
        });
        cell.appendChild(vkw);
      }
      var apply = function (text) {
        ctrl.payload = text; ctrl.ready = true; ctrl.ext = art.ext || "conf";
        ctrl.isLink = !!art.uri; ctrl.hasQR = !!art.qr; ctrl.cmd = art.cmd || null; ctrl.cliAuthors = art.cliAuthors || null;
        if (ctrl.cliAuthors && ga && ga.cliAuthor) {   // the admin picked ONE CLI build for this OS → show only it (no author list, no native tag)
          var pick = ctrl.cliAuthors.filter(function (a) { return a.fork === ga.cliAuthor; });
          if (pick.length) { ctrl.cliAuthors = [pick[0]]; ctrl.cmd = pick[0].cmd; }
        }
        // wrap a long single-line payload (a scheme URI OR a paste-token like VKTGZ:) so config view reads across
        // lines instead of shrinking to one tiny line; a multi-line .conf (kiper292/sidecar) stays unwrapped.
        ctrl.wrapCfg = !!(art.uri || art.wrap);
        if (art.uri) ctrl.openUri = text;   // Axis-3: a scheme fork's config IS the tappable open-in-app URI (ctrl.app already = art.app)
        ctrl.view = art.qr ? "qr" : "text";   // anything scannable (incl. dual config + command) opens on the QR
        draw();
      };
      if (art.text != null) apply(art.text);
      else { draw(); Promise.resolve().then(art.buildAsync).then(apply).catch(function (e) { ctrl.ready = false; stage.innerHTML = ""; stage.appendChild(el("div", "cfg-fail", (e && e.message) || t("cantGen"))); if (ctrl.notify) ctrl.notify(); }); }
    } else {
      if (wga) { ctrl.dlAppUrl = wga.file; ctrl.dlAppFile = wga.fileName; ctrl.dlAppName = wga.app; }   // Start-button download-fallback (WG/AWG client app)
      if (conf) { ctrl.payload = conf; ctrl.ready = true; ctrl.hasQR = true; ctrl.ext = "conf"; ctrl.view = "qr"; }
      // "Open in Amnezia VPN" — build the vpn:// deep link (base64url(qCompress(.conf))) async off the same config, then
      // refresh the bar. Amnezia imports the WG/AWG .conf (AWG obfuscation included). Offered on ALL platforms now (the
      // Start button deep-links it like a turn fork; Safari-iOS gets the same ask-on-tap + its own `vpn` installed-flag).
      if (conf) {
        ctrl.app = AMNEZIA_VPN.name; ctrl.dlAppName = AMNEZIA_VPN.name;   // the Start button opens/gets Amnezia VPN → the ask reads "Open/Get Amnezia VPN"
        Promise.resolve().then(function () { return SWGTurn.amneziaVpn(conf); })
          .then(function (link) { ctrl.openUri = link; if (ctrl.notify) ctrl.notify(); })
          .catch(function () {});   // no deep link (no CompressionStream) → QR + download + "Get the app" remain
      }
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
  // A BLOCKED or EXPIRED peer still takes a slot in the carousel, but instead of QR/config/buttons it shows the peer
  // name + a centred BLOCKED / EXPIRED word + the same text as the whole-sub screen — so the holder sees WHY this one
  // config stopped working. One page per dead peer (no protocol split, no deployment arrows, no action bar).
  function deadPeerPage(row) {
    var peer = row.peer;
    var expired = !!peer.expired && !peer.disabled;   // an explicit block wins over a lapsed date if somehow both
    var page = el("section", "ppage");
    page.setAttribute("data-mode", "dead");
    var srow = el("div", "srow");
    var cell = el("div", "scell");
    var stage = el("div", "scell-stage");
    var box = el("div", "peer-dead " + (expired ? "state-expired" : "state-blocked"));
    box.appendChild(el("p", "peer-dead-name", peer.title || t("peer")));
    box.appendChild(el("p", "state-word", expired ? t("subExpiredWord") : t("subBlockedWord")));
    box.appendChild(el("p", "state-sub", expired ? t("subExpiredSub") : t("subDisabledSub")));
    stage.appendChild(box); cell.appendChild(stage); srow.appendChild(cell); page.appendChild(srow);
    // up/down peer-nav hints so the carousel still walks past this page (render hides the ends)
    page.appendChild(hint("vhint vhint-u", "u")); page.appendChild(hint("vhint vhint-d", "d"));
    return page;
  }
  function peerProtoPage(mode, row, vkLink, userName) {
    var peer = row.peer, secret = row.secret, items = [];
    if (mode === "turn") {
      orderedTargets(peer.targets).forEach(function (tt) {
        var seen = {}, tps = [], isAwg = (tt.type === "awg");
        (tt.turn || []).forEach(function (tp) { var f = SWGTurn.fork(tp.service); if (seen[f]) return;
          if (isAwg && turnWgOnly(f)) return;   // a WireGuard-only fork can't front this AmneziaWG interface
          if (!turnGetApp(f)) return;           // no client app for the visitor's OS → hide this deployment entirely (no card, no dot)
          seen[f] = 1; tps.push({ tp: tp, f: f }); });
        tps.sort(function (a, b) { return turnCellRank(a.f) - turnCellRank(b.f) || forkRank(a.f) - forkRank(b.f); });   // client-priority, then canonical fork order
        tps.forEach(function (x) { items.push({ tgt: tt, tp: x.tp }); });
      });
    } else {
      orderedTargets(peer.targets).forEach(function (tt) { if ((tt.type === "awg") === (mode === "awg")) items.push({ tgt: tt }); });   // primary connection first
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
    // Primary/Backup is a DEPLOYMENT role — a single deployment reached via several turn-proxies is NOT a "backup".
    // So base `multi` on distinct deployments (it.tgt), not on the number of turn cells.
    var _deps = {}; items.forEach(function (it) { _deps[it.tgt.node + "|" + it.tgt.iface] = 1; });
    var multi = Object.keys(_deps).length > 1;
    var ctrls = items.map(function (it) { var cc = makeCell(userName, peer, it, mode, secret, vkLink, reason, multi); srow.appendChild(cc.el); return cc.ctrl; });
    page.appendChild(srow);

    // up/down swipe HINT (vertical, between peers) — flanks the QR top/bottom; render hides the ends.
    var vUp = hint("vhint vhint-u", "u"), vDown = hint("vhint vhint-d", "d");
    page.appendChild(vUp); page.appendChild(vDown);

    var bar = el("div", "pbar");
    var toggle = iconBtn("pbtn ico", "doc", t("showConfig"));
    var copyB = iconBtn("pbtn ico", "copy", t("copyConfig"));
    var dlB = iconBtn("pbtn ico", "download", t("download"));
    var shareB = iconBtn("pbtn ico", "share", t("share"));
    // The signature START button — deep-links into the app if installed, else downloads it (apk/exe/deb). Replaces the
    // old plain "Open in app" button: bigger, round, glowing. The utility icons stay small, centred on its centre.
    var startB = el("button", "pbtn-start"); startB.type = "button";
    startB.innerHTML = START_SVG; startB.setAttribute("aria-label", t("start"));
    // START is the CENTRE slot — utilities split to its left (Config, Copy) and right (Download, Share). The toggle
    // slot is only visibility-toggled (never removed), so START stays centred whether 3 or 4 utilities are visible.
    bar.appendChild(toggle); bar.appendChild(copyB); bar.appendChild(startB); bar.appendChild(dlB); bar.appendChild(shareB);
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
          var im = c.querySelector(".qrimg"); if (im) { im.style.maxWidth = ""; im.style.maxHeight = ""; }   // drop the portrait QR cap
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
      if (isQRbox) {
        // The QR is viewport-sized (min(..vw,..vh)) and won't shrink for an extra line (get-app / VK) or the taller
        // Start bar — so cap it to the room left, keeping it square + scannable (floor 140px). Only bites when tight.
        var imgEl = configEl.querySelector && configEl.querySelector(".qrimg");
        if (imgEl) {
          var pad = 2 * (parseFloat(getComputedStyle(configEl).paddingTop) || 12);   // qrbox top+bottom padding
          // shrink to the room left (never overlap the bar); floor 96px — the inline QR is a preview, tap-to-enlarge scans.
          var maxDim = Math.max(96, configCap - pad);
          imgEl.style.maxWidth = maxDim + "px"; imgEl.style.maxHeight = maxDim + "px";
        }
      } else if (configEl.classList && configEl.classList.contains("cfgtext")) {
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
    // Lay out EVERY deployment cell of this page — not just the current — so swiping to a sibling reveals an
    // already-placed card instead of one that slides in at paddingTop:0 and then jumps into position. syncVHints
    // targets srow.children[curIdx], so walk curIdx over all cells (their vertical math is horizontal-scroll-invariant),
    // then finish on the real current so the shared page chrome (arrows, head) ends up correct. A handful of cells.
    function layoutAll() {
      if (ctrls.length <= 1) { syncVHints(); return; }
      var save = curIdx;
      for (var i = 0; i < ctrls.length; i++) { curIdx = i; syncVHints(); }
      curIdx = save; syncVHints();
    }
    function scheduleVH() {
      var run = function () { layoutAll(); if (_relayoutRail) _relayoutRail(); };   // rail re-centres right after the box is placed
      requestAnimationFrame(run); setTimeout(run, 90); setTimeout(run, 220);          // rAF + catch the async config re-fit
    }
    function syncBar() {
      var c = cur();
      if (c.srvName) { srvEl.textContent = "· " + c.srvName; srvEl.style.color = c.srvColor || ""; }   // "iPhone · edge-1"
      // buttons keep FIXED positions — a hidden one reserves its slot (visibility:hidden)
      var showToggle = c.ready && c.hasQR;
      toggle.style.visibility = showToggle ? "" : "hidden";
      if (showToggle) {
        var vs = cellViews(c), ci = vs.indexOf(c.view); if (ci < 0) ci = 0;
        var nx = vs[(ci + 1) % vs.length];   // the toggle advertises the NEXT view
        setIcon(toggle, nx === "qr" ? "qr" : nx === "link" ? "link" : "doc",
                nx === "qr" ? t("showQR") : nx === "link" ? t("showLink") : (c.isLink ? t("showLink") : t("showConfig")));
      }
      var v = (c.ready && c.payload) ? "" : "hidden";
      copyB.style.visibility = v; dlB.style.visibility = v; shareB.style.visibility = v;
      // START: enabled whenever the cell is ready. Title reflects what it does — open the app (has a deep-link) or
      // get it (download only). "app" name falls back to a generic label.
      startB.style.visibility = c.ready ? "" : "hidden";
      var appNm = c.app || c.dlAppName || t("turnApp");
      var st = c.openUri ? t("startOpen").replace("{app}", appNm) : t("startGet").replace("{app}", appNm);
      startB.title = st; startB.setAttribute("aria-label", t("start") + " · " + st);
      for (var i = 0; i < dotEls.length; i++) dotEls[i].className = "pdot" + (i === curIdx ? " on" : "");
      if (sL) { sL.style.opacity = (curIdx <= 0) ? "0" : ""; sR.style.opacity = (curIdx >= items.length - 1) ? "0" : ""; }
      scheduleVH();
    }
    ctrls.forEach(function (cc) { cc.notify = function () { if (ctrls[curIdx] === cc) syncBar(); else scheduleVH(); }; });   // a non-current cell finishing async still re-lays-out (so it's placed before you swipe to it)
    // WG/AWG with an Amnezia VPN vpn:// link get a THREE-state toggle: QR → link → config. MYSOREZ (VKTGZ) gets its own
    // three: QR (VKTGZ) → link (VKTGZ string) → config (the WG .conf). Everything else stays QR ↔ text.
    function cellViews(c) {
      if (!c.hasQR) return ["text"];
      if (c.vktgz && c.wgConf) return ["qr", "link", "config"];
      return (mode !== "turn" && c.openUri) ? ["qr", "link", "text"] : ["qr", "text"];
    }
    function viewText(c) {   // what Copy/Download/Share act on
      if (c.view === "config" && c.wgConf) return c.wgConf;
      return (c.view === "link" && c.openUri) ? c.openUri : c.payload;
    }
    toggle.onclick = function () { var c = cur(); if (!c.hasQR) return;
      var vs = cellViews(c), i = vs.indexOf(c.view); if (i < 0) i = 0; c.view = vs[(i + 1) % vs.length]; c.redraw(); syncBar(); };
    copyB.onclick = function () { var c = cur();
      if (c.view === "qr" && c.qrUrl) { copyImage(c.qrUrl, null); flashIcon(copyB, "copy", t("copyConfig")); }
      else (navigator.clipboard ? navigator.clipboard.writeText(viewText(c)) : Promise.reject()).then(function () { flashIcon(copyB, "copy", t("copyConfig")); }, function () {});
    };
    dlB.onclick = function () { var c = cur(); var nm = c.base;
      if (c.view === "qr" && c.qrUrl) downloadImage(c.qrUrl, nm);
      else if (c.view === "config" && c.wgConf) download(c.wgConf, nm, "conf");
      else if (c.view === "link" && c.openUri) download(c.openUri, nm, "txt");
      else download(c.payload, nm, c.ext || "conf"); };
    shareB.onclick = function () { var c = cur();
      var isConfV = (c.view === "config" && c.wgConf), isLinkV = (c.view === "link" && c.openUri);
      var content = viewText(c), nm = c.base + "." + (isConfV ? "conf" : isLinkV ? "txt" : (c.ext || "conf"));
      if (navigator.share) {
        try { var f = new File([content], nm, { type: "text/plain" });
          if (navigator.canShare && navigator.canShare({ files: [f] })) { navigator.share({ files: [f], title: nm }).catch(function () {}); return; }
        } catch (_) {}
        navigator.share({ title: nm, text: content }).catch(function () {}); return;
      }
      (navigator.clipboard ? navigator.clipboard.writeText(content) : Promise.reject()).then(function () { flashIcon(shareB, "share", t("share")); }, function () {});
    };
    // START: try the app deep-link; if the app opens the page goes hidden (→ cancel). If it's STILL visible after a
    // beat, nothing handled the scheme → the app isn't installed → download it (apk/exe/deb). No deep-link → download
    // straight away. No app link either → the .conf itself. (There's no reliable "is app installed" API — this is it.)
    function startDownload(c) {
      var os = subOs();
      if (c.dlAppUrl && c.dlAppFile) triggerDownload(c.dlAppUrl);                 // direct installer → same-tab attachment download (real name, not a GUID)
      else if (c.dlAppUrl && (os === "ios" || os === "android")) window.location.href = c.dlAppUrl;   // store / TestFlight: same-tab (window.open in the fallback timer is popup-blocked on mobile)
      else if (c.dlAppUrl) window.open(c.dlAppUrl, "_blank", "noopener");         // desktop store / install page → new tab
      else if (c.payload) download(c.payload, c.base, c.ext || "conf");
    }
    // Per-app "this app is installed" flag, keyed by the scheme (e.g. vkturnproxy). Set once the user deliberately
    // opens the app (or an auto-fire is detected as opened) so Safari-on-iOS skips the ask next time.
    function hasAppKey(c) { return "swgsub-hasapp-" + (String(c.openUri || "").split("://")[0] || "app"); }
    // Fire the deep-link with NO store fallback — for a DELIBERATE "Open" or a remembered-installed app. Firing a
    // fallback here is what loaded TestFlight BEHIND the app in in-app browsers (Telegram) that don't fire the
    // visibility/blur events we'd use to cancel it. If the app doesn't open, a quick re-tap recovers (below).
    function fireScheme(c) {
      var go = function () { _schemeFiredAt[hasAppKey(c)] = Date.now(); try { window.location.href = c.openUri; } catch (_) {} };
      if (/^vkturnproxy:/i.test(c.openUri || "")) {   // anton48: show the "Settings → Import" screenshot FIRST, then open the app after 5s so the user can read it
        showImportHint();
        if (_importCd) {   // count "App is opening in 5… 4… 3… 2… 1…" down to the open, then hide the line
          var _n = 5; _importCd.style.display = ""; _importCd.textContent = t("appOpening").replace("{n}", _n);
          _cdTimer = setInterval(function () {
            _n -= 1;
            if (_n <= 0) { clearInterval(_cdTimer); _cdTimer = 0; if (_importCd) _importCd.style.display = "none"; }
            else if (_importCd) _importCd.textContent = t("appOpening").replace("{n}", _n);
          }, 1000);
        }
        _importPending = setTimeout(go, 5000);
      } else { go(); }
    }
    // Fire the deep-link, then fall back to the download if nothing handled it — for the AUTO-fire path on browsers
    // that fail silently (Chrome/Firefox on iOS, Android, desktop). If the app opens, the page goes hidden → cancel.
    function fireDeepLink(c) {
      var t0 = Date.now(), left = false, key = hasAppKey(c);
      var mark = function () { left = true; };
      document.addEventListener("visibilitychange", mark); window.addEventListener("pagehide", mark); window.addEventListener("blur", mark);
      try { window.location.href = c.openUri; } catch (_) {}   // hand the scheme link to the OS (opens the app if installed)
      setTimeout(function () {
        document.removeEventListener("visibilitychange", mark); window.removeEventListener("pagehide", mark); window.removeEventListener("blur", mark);
        if (left || document.hidden || Date.now() - t0 > 1500) { _lsSet(key, "1"); return; }   // app took over → remember it's installed
        _lsSet(key, "");                        // still here, no hand-off → not installed → forget any stale flag…
        startDownload(c);                       // …and get the app
      }, 1000);
    }
    // WG/AWG Amnezia VPN (vpn://) OFF Android: no browser scheme exists (iOS/Mac/Win/Linux all import a .vpn file or a
    // PASTED vpn:// string). So copy the link (to paste into the app) + open the app — the App Store on iOS AND macOS
    // (AmneziaVPN is one universal App Store app; Apple-Silicon Macs run it), the downloads page on Windows/Linux.
    function startCopyOpen(c) {
      if (navigator.clipboard) navigator.clipboard.writeText(c.openUri).catch(function () {});   // initiate copy in the gesture
      var os = subOs();
      if (os === "ios" || os === "macos") { showToast(t("vpnCopied")); if (c.dlAppUrl) setTimeout(function () { window.location.href = c.dlAppUrl; }, 1400); return; }   // copy → "Copied" → open the App Store (install / open, then paste the link)
      showPasteHint();                                                                            // Windows/Linux (+ anything else): the link is copied → "paste it into AmneziaVPN" steps + downloads
    }
    startB.onclick = function () {
      var c = cur(); if (!c.ready) return;
      startB.classList.add("go"); setTimeout(function () { startB.classList.remove("go"); }, 600);   // tap pulse
      if (!c.openUri) {
        if (c.wgTurn) { download(c.payload, c.base, c.ext || "conf"); showWgTurnHint(c); return; }   // WG Turn: no scheme → download the .conf + show the file-import steps
        if (c.vktgz) { showVktgzChoice(c, startB); return; }   // MYSOREZ: 3-button popover (get app · get core · assemble+connect)
        if (c.cliApp && c.cmd) { var cmd = cliCommand(c); if (navigator.clipboard) navigator.clipboard.writeText(cmd).catch(function () {}); showCliHint(c); return; }   // CLI/sidecar → copy the per-OS command (matching the downloaded binary) + show the run steps
        if (c.cmd) { if (navigator.clipboard) navigator.clipboard.writeText(c.cmd).catch(function () {}); showToast(t("cmdCopied")); return; }
        startDownload(c); return;                                                          // no scheme, no command → get the app
      }
      if (/^vpn:/i.test(c.openUri) && subOs() !== "android") { startCopyOpen(c); return; }   // Amnezia VPN off Android → copy the link + get the app
      // freeturn/samosvalishe: the app imports the config via its scheme but CAN'T auto-receive the VK call link →
      // copy the primary VK link so the user can paste it, THEN fire the scheme (below) as usual.
      if (c.vkPrimary) { if (navigator.clipboard) navigator.clipboard.writeText(c.vkPrimary).catch(function () {}); showToast(t("vkCopied")); }
      // Safari-on-iOS (+ in-app webviews it can't be told apart from): firing an unregistered scheme pops an
      // un-suppressable "address is invalid" modal, so ASK — Open (deliberate) fires the scheme with NO fallback,
      // Get goes to the store. Every OTHER browser fails silently → keep the clean auto-fire + fallback.
      if (isIOSSafari() && c.dlAppUrl) {
        var key = hasAppKey(c);
        var open = function () { _lsSet(key, "1"); fireScheme(c); };          // "Open": remember + open, NO TestFlight fallback
        var get = function () { startDownload(c); };
        if (_ls(key)) {   // remembered as installed → open directly; a quick re-tap (didn't open) clears it + re-asks
          if (_schemeFiredAt[key] && Date.now() - _schemeFiredAt[key] < 4000) { _lsSet(key, ""); openStartChoice(startB, c, open, get); return; }
          fireScheme(c); return;
        }
        openStartChoice(startB, c, open, get);
        return;
      }
      fireDeepLink(c);
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
    fitBrand();                                      // RU control may have just shown/hidden — re-check logo↔controls fit
    // BLOCKED / EXPIRED user: logo (header brand) + username (header "who") stay; the body is a single centered
    // status word (BLOCKED / EXPIRED) under the name, then the explanatory text — no peers, tabs, or QRs.
    // Blocked is reversible from the panel (unblock); expired clears when the admin extends the date.
    if (data.disabled) {
      document.getElementById("peers").hidden = true;
      showState(t("subBlockedWord"), t("subDisabledSub"), "blocked");
      return Promise.resolve();
    }
    if (data.expired) {
      document.getElementById("peers").hidden = true;
      showState(t("subExpiredWord"), t("subExpiredSub"), "expired");
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
      // A blocked/expired peer gets a placeholder page (name + BLOCKED/EXPIRED), not real configs — so it's kept out
      // of the protocol-group computation and rendered separately after the live peers.
      var deadRows = rows.filter(function (r) { return r.peer.disabled || r.peer.expired; });
      var liveRows = rows.filter(function (r) { return !(r.peer.disabled || r.peer.expired); });
      // Which protocol groups apply: WG/AWG if ≥1 deployment of that type; TURN only when the feature is on AND
      // ≥1 deployment has a proxy forwarding to it (same gate as the admin view).
      var has = { wg: false, awg: false, turn: false };
      liveRows.forEach(function (r) { (r.peer.targets || []).forEach(function (t) {
        has[t.type === "awg" ? "awg" : "wg"] = true;
        if (data.turn_enabled && (t.turn || []).length) has.turn = true;
      }); });
      var groups = ["wg", "awg", "turn"].filter(function (m) { return has[m]; });
      if (!groups.length && !deadRows.length) { showState(t("noConfigs"), t("noConfigsSub")); return; }

      // ONE flat vertical pager through EVERY config, grouped by protocol: all WG, then all AWG, then all Turn.
      // The mode buttons don't switch views — each JUMPS to the first page of its group; the group whose page is
      // in view is highlighted and its button disabled (you're already there).
      var bar = el("div", "modebar"), pager = el("div", "pager"), btns = {}, firstOf = {};
      var pinMode = null, pinTimer = 0;
      function highlight(cur) { groups.forEach(function (m) { var on = (m === cur); btns[m].className = "modetab" + (on ? " on" : ""); btns[m].disabled = on; }); }
      groups.forEach(function (mode) {
        var b = el("button", "modetab mtab-" + mode); b.type = "button"; b.title = t(mode); b.setAttribute("aria-label", t(mode));
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
        liveRows.forEach(function (row) {
          var pg = peerProtoPage(mode, row, vkLink, userName);
          if (pg) { if (!firstOf[mode]) firstOf[mode] = pg; pager.appendChild(pg); }
        });
      });
      // blocked/expired peers last — one placeholder page each, so they're visible in the carousel but carry no config
      deadRows.forEach(function (row) { pager.appendChild(deadPeerPage(row)); });
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
          if (tAxis === "v") e.preventDefault();   // take over VERTICAL only (one peer per firm gesture). HORIZONTAL is left
          // to the carousel's native scroll-snap so the card tracks the finger live and snaps on release (scroll-snap-stop:
          // always still limits it to one deployment) — no wait-for-release-then-animate.
        }, { passive: false });
        pager.addEventListener("touchend", function (e) {
          if (!tOwn || tAxis !== "v") return;   // horizontal already handled natively (finger-tracked + snapped)
          var dt = Date.now() - tT;
          var dy = e.changedTouches[0].clientY - tY, vel = Math.abs(dy) / Math.max(1, dt);
          if (Math.abs(dy) > 85 || (Math.abs(dy) > 45 && vel > 0.7)) stepConfig(dy < 0 ? 1 : -1);   // FIRM swipe only
        }, { passive: false });
        var wAcc = 0, wT = 0, hAcc = 0, hT = 0;
        // Firefox reports wheel deltas in LINES (deltaMode 1) or PAGES (2), not pixels like Chrome — so the raw
        // deltas are tiny and never reach the 120px step threshold, blocking scroll entirely. Normalise to pixels.
        function wpx(d, e) { return e.deltaMode === 1 ? d * 16 : e.deltaMode === 2 ? d * (pager.clientHeight || 800) : d; }
        pager.addEventListener("wheel", function (e) {
          if (scrollableUnder(e.target)) return;
          e.preventDefault();
          if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) {   // horizontal wheel → step ONE deployment (no fling-skip)
            var nx = Date.now(); if (nx - hT > 180) hAcc = 0; hT = nx;
            hAcc += wpx(e.deltaX, e);
            if (Math.abs(hAcc) > 120) { stepCell(hAcc > 0 ? 1 : -1); hAcc = 0; }
            return;
          }
          var now = Date.now(); if (now - wT > 180) wAcc = 0; wT = now;
          wAcc += wpx(e.deltaY, e);
          if (Math.abs(wAcc) > 120) { stepConfig(wAcc > 0 ? 1 : -1); wAcc = 0; }
        }, { passive: false });
      }

      document.getElementById("state").hidden = true;
      wrap.hidden = false;
      if (anyBad) wrap.appendChild(el("p", "foot-warn", t("someBad")));
    });
  }

  // The header defaults to a CENTRED logo below the fixed top-right controls. On narrow screens / wide default
  // fonts (Android) the centred wordmark collides with those controls; we can't know that from width alone, so
  // measure it in the centred state and — only then — add body.logo-inline (CSS then moves the logo LEFT onto
  // the controls' line). Re-checked on resize / orientation / language-toggle (RU shows/hides, changing the gap).
  function fitBrand() {
    document.body.classList.remove("logo-inline");                 // always measure the DEFAULT centred layout
    var brand = document.querySelector(".brand"), ctl = document.querySelector(".topctl");
    if (brand && ctl && brand.getBoundingClientRect().right > ctl.getBoundingClientRect().left - 8) {
      document.body.classList.add("logo-inline");
    }
  }
  window.addEventListener("resize", function () { requestAnimationFrame(fitBrand); }, { passive: true });
  window.addEventListener("orientationchange", function () { setTimeout(fitBrand, 60); });

  function start() {
    wireControls(); paintCtl(); fitBrand();        // theme toggle works even before the data loads
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
        return fetch("api/" + encodeURIComponent(token), { cache: "no-store" }).then(function (res) {   // RELATIVE (no leading /) → resolves under any reverse-proxy mount, same as the assets
          if (res.status === 404) { showState(t("notFound"), t("notFoundSub")); return null; }
          if (!res.ok) { showState(t("err"), t("errServer")); return null; }
          return res.json().then(function (j) {
            if (!j || !j.ok || !j.data) { showState(t("err"), t("errResp")); return null; }
            return render(j.data, cryptoKey);
          });
        });
      })
      .catch(function (e) {
        // Surface the REAL cause: this catch wraps importKey + fetch + render, so a render throw (not just a
        // network drop) landed here too and used to masquerade as "check your connection". Log it, and show the
        // message so the page tells the truth (a genuine fetch reject still reads sensibly, e.g. "Failed to fetch").
        try { console.error("swgSub: could not load subscription —", e); } catch (_) {}
        showState(t("err"), (e && e.message) ? String(e.message).slice(0, 300) : t("errNet"));
      });
  }

  if (!window.crypto || !crypto.subtle) {
    showState(t("unsupported"), t("unsupportedSub"));
  } else {
    start();
  }
})();
