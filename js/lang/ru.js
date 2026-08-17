/* ru.js — Russian catalog. Keys are the English source text (see js/i18n.js).
 *
 * Audited by `node .campaign/i18n-extract.mjs --audit`, which lists keys the code uses but this file
 * lacks (they render English) and keys here the code no longer uses (the English was edited).
 *
 * Register: the panel addresses one operator running their own servers — direct, technical, no
 * marketing voice and no formal «Вы» padding. Imperative for buttons ("Удалить", not "Удаление"),
 * infinitive avoided in labels. Established Russian sysadmin loanwords are used where they are what
 * people actually say: интерфейс, пир, нода, прокси, ключ, хендшейк. Product and protocol names
 * (WireGuard, AmneziaWG, WDTT, turn-proxy) are NOT translated.
 */

export const STR = {
  // ── time ──────────────────────────────────────────────────────────────────────────────────────
  // "just now" is a moment, not a duration: "только что" is the natural form.
  "just now": "только что",
  // 1 char over the character budget, kept deliberately: .when is a flex-positioned monospace slot with
  // room to its left, and dropping "назад" would make an elapsed time read as a duration. Visually checked.
  // budget-ok: .when is a flex slot with room to its left, measured
  "{n}m ago": "{n} мин назад",
  "{n}h ago": "{n} ч назад",
  "{n}d ago": "{n} д назад",
  // Compact unit suffixes that sit tight against a number in dense tables (5s, 12m). Russian keeps the
  // same one-letter density: с/м/ч/д. Context-prefixed because bare "s"/"m" mean other things elsewhere.
  "{v1} active": "активных: {v1}",
  " · mean {v1}%": " · среднее {v1}%",
  "unit|s": "с",
  "unit|m": "м",
  "unit|h": "ч",
  "unit|d": "д",

  // ── connectivity-field validation ──────────────────────────────────────────────────────────────
  "Comma-separated CIDRs, e.g. 0.0.0.0/0, ::/0": "CIDR через запятую, например 0.0.0.0/0, ::/0",
  "Required (use 0.0.0.0/0, ::/0 for full tunnel).": "Обязательно (полный туннель: 0.0.0.0/0, ::/0).",
  "Each DNS must be a valid IP.": "Каждый DNS — корректный IP.",
  "MTU must be a number 1280–9200.": "MTU — число от 1280 до 9200.",
  "Keepalive must be 0–65535.": "Keepalive — от 0 до 65535.",

  // ── ports and interfaces (js/model.js) ─────────────────────────────────────────────────────────
  "Port must be a number.": "Порт — это число.",
  "Port must be between 1 and 65535.": "Порт — от 1 до 65535.",
  // The holder is spliced into the sentence below, so it is translated in the INSTRUMENTAL case —
  // "занят чем?". This is why the sentence is one interpolated string and not three concatenated
  // fragments: Russian needs the case, and a fragment cannot carry one.
  "Port {port} is already used by {holder} on this node.": "Порт {port} на этой ноде уже занят: {holder}.",
  "a turn-proxy": "turn-прокси",
  "a WDTT proxy": "WDTT-прокси",
  "a pending interface": "создаваемый интерфейс",
  " (WDTT)": " (WDTT)",
  " (WDTT internal WG)": " (внутр. WG WDTT)",
  " (WDTT, starting)": " (WDTT, запускается)",
  " (WDTT internal WG, starting)": " (внутр. WG WDTT, запуск)",

  // ── charts (js/charts.js) ──────────────────────────────────────────────────────────────────────
  "Throughput": "Трафик",
  "no data": "нет данных",
  "Vertical scale — nearest 1/5/10/50/100/500 unit above the peak (≥15% headroom)":
    "Шкала — ближайшее 1/5/10/50/100/500 выше пика (запас ≥15%)",
  "This node isn't reporting right now — showing the last data it sent.":
    "Нода сейчас не отвечает — показаны последние данные.",

  // ── filters and status (js/views.js) ───────────────────────────────────────────────────────────
  // Dropdown options sit in a fixed-width <select>: these must stay at or under the English width.
  "All nodes": "Все ноды",
  "No nodes": "Нет нод",
  "All interfaces": "Все интерфейсы",
  "No interfaces": "Нет интерфейсов",
  "Mesh": "Меш",
  "This node's mesh status:": "Меш-статус ноды:",
  "Click to switch users / peers": "Переключить: пользователи / пиры",
  "Online peers": "Пиры онлайн",

  // ── activity feed item labels (js/views.js EV_ITEMS stays canonical; these are its display forms) ──
  "event|Peer": "Пир",
  "event|User": "Пользователь",
  "event|Node": "Нода",
  "event|Interface": "Интерфейс",
  "event|Turn-proxy": "Turn-прокси",
  "event|Mesh": "Меш",
  "event|Settings": "Настройки",
  "event|Update": "Обновление",
  "All items": "Все объекты",

  // ── the status vocabulary (js/ui.js STATUS_WORDS) ──────────────────────────────────────────────
  // MEASURED, not estimated. The peers grid is `table-layout: fixed` and the status column is 9% — 98px at
  // a 1214px table — so a badge is hard-capped: the English words run 75-89px and the widest ("Unassigned")
  // has 9px of headroom. Every word below was rendered in the real badge and kept at or under 89px, which is
  // why several are not the most literal choice:
  //   Rotating   "Смена ключа" 104 -> "Ротация" 77      Restricted  "Фильтруется" 103 -> "Фильтр" 73
  //   Blocking   "Блокируется" 102 -> "Закрытие" 85     Unassigned  "Не назначен" 99  -> "Свободен" 85
  //   Blocked    "Блокирован"  98  -> "В блоке" 78      Unknown     "Неизвестно"  95  -> "Неясно" 71
  // The hover reason carries the full explanation, so the badge can afford to be terse.
  // Two internal keys read differently on screen: `disabled` shows as Blocked (access revoked), `blocked`
  // as Restricted (the DPI fault).
  "status|Online": "Онлайн",
  "status|Ready": "Готов",
  "status|Pending": "Ожидает",
  "status|Creating": "Создание",
  "status|Rotating": "Ротация",
  "status|Restoring": "Возврат",
  "status|Partial": "Частично",
  "status|Dangling": "Потерян",
  "status|Broken": "Неверный",
  "status|Faulty": "Сбой",
  "status|Blocked": "В блоке",
  "status|Restricted": "Фильтр",
  "status|Expired": "Истёк",
  "status|Expiring": "Истекает",
  "status|Blocking": "Закрытие",
  "status|Unknown": "Неясно",
  "status|Unassigned": "Свободен",
  "status|Orphan": "Чужой",
  "status|Removing": "Удаление",
  "status|Empty": "Пусто",
  "All statuses": "Все статусы",
  "No peers": "Нет пиров",
  "Offline": "Офлайн",

  // ── why a peer is in that state (js/ui.js STATUS_REASONS) ──────────────────────────────────────
  // Hover prose, not chips — these wrap freely, so they are translated in full.
  "reaching the server but the handshake never completes — likely DPI / MTU / wrong {proto} params":
    "доходит до сервера, но хендшейк не завершается — вероятно DPI / MTU / неверные параметры {proto}",
  "Wireguard or AmneziaWG": "Wireguard или AmneziaWG",
  "connected, but no inbound data is flowing — likely a one-way block / DPI on the return path":
    "подключение есть, но входящий трафик не идёт — вероятно односторонняя блокировка / DPI на обратном пути",
  "the interface is up but this peer's IP is outside its subnet — the record needs correcting, not the interface":
    "интерфейс поднят, но IP пира вне его подсети — исправить нужно запись, а не интерфейс",
  "access is blocked — removed from every server until unblocked":
    "доступ закрыт — снят со всех серверов до разблокировки",
  "the access date has passed — removed from every server until the date is extended":
    "срок доступа истёк — снят со всех серверов до продления",
  "the access date is coming up — will be removed from every server when it passes":
    "срок доступа подходит к концу — по истечении будет снят со всех серверов",
  "Interface {iface} is down — {why}": "Интерфейс {iface} не поднят — {why}",

  // ── interface op lifecycle (js/ui.js ifopBusy/ifopDone/ifopFail) ───────────────────────────────
  // Lowercase: these ride inside a tag next to the interface name, mid-phrase. "ignore" is the panel's
  // word for hiding an interface it doesn't manage, so it translates as скрыть, not игнорировать.
  "state|Default": "По умолчанию",
  "A subscription or peer with an expiry date shows an orange *about to expire* warning this many days ahead.":
    "Подписка или пир со сроком действия предупреждает об истечении за столько дней.",
  "theme|dark": "тёмная",
  "theme|light": "светлая",
  "ifop|starting": "запуск",
  "ifop|stopping": "остановка",
  "ifop|restarting": "перезапуск",
  "ifop|applying": "применение",
  "ifop|ignoring": "скрытие",
  "ifop|restoring": "возврат",
  "ifop|started": "запущен",
  "ifop|stopped": "остановлен",
  "ifop|restarted": "перезапущен",
  "ifop|applied": "применено",
  "ifop|ignored": "скрыт",
  "ifop|restored": "возвращён",
  "ifop|failed to start": "не запустился",
  "ifop|failed to stop": "не остановлен",
  "ifop|failed to restart": "не перезапущен",
  "ifop|failed to apply": "не применено",
  "ifop|couldn\u2019t ignore": "не удалось скрыть",
  "ifop|couldn\u2019t restore": "не удалось вернуть",
  "ifop|failed": "ошибка",
  // turn-proxy request verbs (js/turn.js turnPendLabel) — same lowercase mid-phrase register as above
  "ifop|installing": "установка",
  "ifop|rotating": "смена ключей",
  "ifop|deleting": "удаление",
  "ifop|adopting": "адаптация",
  "turn|creating": "создаётся",
  "turn|pending": "в очереди",
  "turn|ready": "готов",
  "Working on the node": "Нода работает",
  "the install failed on the node": "установка не удалась на ноде",
  "download failed": "ошибка загрузки",
  "the change failed on the node": "изменение не применилось на ноде",
  "Save failed on the node": "Не сохранилось на ноде",

  // ── node/panel install lifecycle (js/ui.js procLabel) ──────────────────────────────────────────
  "re-installing": "переустановка",
  "converting to bare-metal": "перевод на bare-metal",
  "converting to docker": "перевод на docker",
  "updating": "обновление",
  "uninstalling": "удаление",
  "re-installed": "переустановлен",
  "re-installed and updated": "переустановлен и обновлён",
  "converted to bare-metal": "переведён на bare-metal",
  "converted to docker": "переведён на docker",
  "updated": "обновлён",
  "up to date": "актуален",
  "re-install aborted": "переустановка прервана",
  "convert aborted": "перевод прерван",
  // 1 char over budget: the four aborted states each need their own noun to stay distinguishable, and
  // this tag sits alone on a node card with room beside it.
  // budget-ok: alone on a node card, measured
  "update aborted": "обновление прервано",
  "uninstall aborted": "удаление прервано",
  "re-install failed": "ошибка переустановки",
  "convert failed": "ошибка перевода",
  "update failed": "ошибка обновления",
  "uninstall failed": "ошибка удаления",
  "proc|failed": "ошибка",
  // a node that never enrolled: its "re-install" is really a first install
  "installing": "установка",
  "installed": "установлен",
  "installed and updated": "установлен и обновлён",
  "install aborted": "установка прервана",
  "install failed": "ошибка установки",
  "Dismiss — show the node's actual status": "Скрыть — показать реальный статус ноды",
  "Couldn't dismiss.": "Не удалось скрыть.",
  "Command failed on the node": "Команда не выполнилась на ноде",

  // ── modal and sheet chrome (js/ui.js) ──────────────────────────────────────────────────────────
  "Back": "Назад",
  "Cancel": "Отмена",
  "Close": "Закрыть",
  "Confirm": "Подтвердить",
  "Working…": "Выполняю…",
  "Details": "Подробности",
  "Discard": "Отменить",
  "Keep editing": "Продолжить",
  "Discard unsaved changes?": "Отменить несохранённое?",
  // The typed word lands LAST in Russian and first in English — which is exactly why the sentence is one
  // key with a {name} marker the renderer splits on, rather than two fragments around a <b>.
  "Confirm by typing {name}": "Подтвердите вводом {name}",
  "Error": "Ошибка",
  // 4->10 chars, the largest overage in the catalog. Measured rather than guessed: the button grows 77->115px
  // inside the banner's command row, the command box absorbs it (1073->1035px) without clipping, and the
  // banner keeps its exact height. "Копир." would fit the budget and read like a truncation bug.
  // budget-ok: measured — banner keeps its height, command box absorbs the 38px
  "Copy": "Копировать",
  "Command copied": "Команда в буфере",

  // ── lifecycle and turn-proxy hints (js/ui.js) ──────────────────────────────────────────────────
  "Access expired": "Доступ истёк",
  "About to expire": "Скоро истечёт",
  "Connected via": "Подключён через",
  "Last connected via": "Был подключён через",

  // ── app bar (js/ui.js) ─────────────────────────────────────────────────────────────────────────
  "Theme: Auto (follows your system) — click for Light": "Тема: авто (как в системе) — нажмите для светлой",
  "Theme: Light — click for Dark": "Тема: светлая — нажмите для тёмной",
  "Theme: Dark — click for Auto": "Тема: тёмная — нажмите для авто",

  // ── config-storage banner (js/ui.js StoreOffBanner) ────────────────────────────────────────────
  "Config storage is off.": "Хранение конфигов выключено.",
  "Client configs (with their private keys) aren't kept on the panel, so QR codes and downloads only work right after a peer is created — existing peers can't be re-shared. Run this on the {host} to enable it (existing peers then need a one-time Rotate-keys to capture a config):":
    "Конфиги клиентов (с приватными ключами) не хранятся на панели — QR и загрузка работают только сразу после создания пира, переотправить существующие нельзя. Чтобы включить, выполните на {host} (существующим пирам затем понадобится однократная смена ключей, чтобы конфиг сохранился):",
  "Docker host": "хосте Docker",
  "panel host": "хосте панели",

  // ── peer-grid columns (js/grids.js) ────────────────────────────────────────────────────────────
  // One key drives both the <th> and the narrow-screen data-label, so they cannot disagree. Held tight:
  // a column header sets the column's minimum width. `col|` context because several of these words mean
  // something else elsewhere ("Node" the machine vs the column, "Total" the sum vs the column).
  "col|Status": "Статус",
  "col|User": "Пользователь",
  "col|Title": "Название",
  "col|Endpoint": "Эндпоинт",
  "col|Address": "Адрес",
  "col|Node": "Нода",
  "col|IF": "IF",
  "col|Peers": "Пиры",
  "col|Nodes": "Ноды",
  "col|Online": "Онлайн",
  "col|Rate": "Скорость",
  "col|Total": "Всего",
  "Untitled": "Без имени",

  // ── peer-grid rows, actions and pager (js/grids.js) ────────────────────────────────────────────
  "Double-click for QR / configs": "Двойной клик — QR и конфиги",
  "Click to open this user's details": "Открыть карточку пользователя",
  "Assign this peer to a user": "Назначить пира пользователю",
  "Show QR / configs": "Показать QR и конфиги",
  "Unavailable while the node is down / converting": "Недоступно, пока нода не в строю или переводится",
  "Edit peer": "Изменить пира",
  "Delete peer": "Удалить пира",
  "Unassign peer": "Отвязать пира",
  "Recreate & rekey — {iface} is gone with no recoverable key; recreate it fresh and reissue every client's config":
    "Пересоздать с новым ключом — {iface} утерян, ключ восстановить нельзя; создать заново и переиздать конфиги всем клиентам",
  "Restore interface {iface} (recreate the missing interface with its original identity — recovers every peer on it)":
    "Восстановить интерфейс {iface} (создать пропавший интерфейс с прежней идентичностью — вернёт всех его пиров)",
  "Fix address — {ip} is outside {iface}'s subnet": "Исправить адрес — {ip} вне подсети {iface}",
  "Search title, address…": "Поиск по имени, адресу…",
  "New peer": "Новый пир",
  "Rows per page": "Строк на странице",
  "{from}–{to} of {total}": "{from}–{to} из {total}",
  "Older release": "Предыдущий релиз",
  "Newer release": "Следующий релиз",
  // budget-ok: the changelog nav pair is centred in a 644px header and measures 193px together —
  // measured, nothing clipped
  "‹ Prev": "‹ Предыдущая",
  // budget-ok: see "‹ Prev" — same centred group
  "Next ›": "Следующая ›",

  // ── peer + user actions (js/peer-actions.js) ───────────────────────────────────────────────────
  // Counted nouns go through plural() (see PLURALS below) — Russian picks between three forms by the last
  // digit, so "3 интерфейса" and "5 интерфейсов" cannot both come from one string with an "s" glued on.
  // budget-ok: toast, wraps
  "This user has no peers to rotate.": "У этого пользователя нет пиров для смены ключей.",
  "Rotate all keys · {name}": "Смена всех ключей · {name}",
  "Rotate all keys": "Сменить ключи",
  // The count is INTERPOLATED, so it arrives nominative ("1 пир", "3 пира") and cannot be declined. The first
  // draft read "у всех {what}" — after «у всех» Russian demands the genitive, so it rendered "у всех 1 пир".
  // Fixed by restructuring rather than by fighting the grammar: the count now sits after a colon, where the
  // nominative is correct for every number. Same trick as the port-conflict message. Only visible by looking
  // at the rendered dialog — no check can see it.
  "Rotate the keys for all {what} of {name}. Every existing config, QR and link stops working — each device must re-import. This can't be undone.":
    "Смена ключей у пользователя {name}. Затронуто: {what}. Все существующие конфиги, QR и ссылки перестанут работать — каждое устройство придётся импортировать заново. Отменить нельзя.",
  // budget-ok: toast, wraps
  "Rotated keys for {count} — every device must re-import.": "Ключи сменены: {count} — каждое устройство нужно импортировать заново.",
  "Unassign peer · {name}": "Отвязать пира · {name}",
  "Unassign": "Отвязать",
  "This revokes access immediately and is irreversible — the keys change, so re-assigning later means sending the user a brand-new QR / config to import.":
    "Доступ отзывается сразу и необратимо — ключи меняются, поэтому при повторной привязке пользователю нужно выдать новый QR или конфиг.",
  "Delete": "Удалить",
  "Delete this entry?": "Удалить эту запись?",
  "Delete webhook": "Удалить вебхук",
  "Delete custom list": "Удалить свой список",
  "This is irreversible — the peer's key is removed from every interface it's deployed on.":
    "Действие необратимо — ключ пира удаляется со всех интерфейсов, где он развёрнут.",

  // ── restoring a missing interface / fixing an out-of-subnet address ─────────────────────────────
  "more than {count}": "больше {count}",
  "This isn't a brief hiccup or a peer still being created — the interface has stayed missing for {dur}.":
    "Это не кратковременный сбой и не пир в процессе создания — интерфейс отсутствует уже {dur}.",
  "the operator vault": "хранилища оператора",
  "the node's own backup": "резервной копии на ноде",
  "The panel has no saved configuration for interface {iface} on {node} yet, so it can't be recreated automatically. {gate}":
    "У панели пока нет сохранённой конфигурации интерфейса {iface} на {node}, поэтому пересоздать его автоматически нельзя. {gate}",
  "Recreate the missing interface {iface} on {node} with its ORIGINAL server key (from {src}) and saved settings. This restores the INTERFACE, not a single peer — every peer that lives on {iface} re-converges over the next few syncs, and existing clients keep working (no new QR / config to distribute). {unlock}{gate}":
    "Пересоздать пропавший интерфейс {iface} на {node} с ИСХОДНЫМ ключом сервера (из {src}) и сохранёнными настройками. Восстанавливается ИНТЕРФЕЙС, а не один пир — все пиры на {iface} сойдутся за несколько синхронизаций, а существующие клиенты продолжат работать (раздавать новые QR и конфиги не нужно). {unlock}{gate}",
  "You'll be asked to unlock the vault first to release the escrowed key. ":
    "Сначала попросим разблокировать хранилище, чтобы выдать депонированный ключ. ",
  "Recreate the missing interface {iface} on {node} with its saved settings. This restores the INTERFACE, not a single peer. The original server key can't be recovered, so the interface gets a NEW key — every client on {iface} must re-import a fresh QR / config. {gate}":
    "Пересоздать пропавший интерфейс {iface} на {node} с сохранёнными настройками. Восстанавливается ИНТЕРФЕЙС, а не один пир. Исходный ключ сервера восстановить нельзя, поэтому интерфейс получит НОВЫЙ ключ — каждому клиенту на {iface} придётся импортировать свежий QR или конфиг. {gate}",
  // budget-ok: sheet title, 620px wide
  "Restore interface · {where}": "Восстановление интерфейса · {where}",
  "Restore interface": "Восстановить интерфейс",
  // budget-ok: toast, wraps
  "Vault restore failed: {err}": "Не удалось восстановить из хранилища: {err}",
  "Restoring interface {iface} on {node} — its peers re-converge over the next syncs.":
    "Восстанавливаем интерфейс {iface} на {node} — его пиры сойдутся за следующие синхронизации.",
  "Interface {iface} is back — rekeying {count}; hand out the fresh configs.":
    "Интерфейс {iface} вернулся — меняем ключи: {count}; раздайте свежие конфиги.",
  "No interfaces to restore yet — a missing interface must persist a couple of minutes first.":
    "Восстанавливать пока нечего — интерфейс должен отсутствовать хотя бы пару минут.",
  // budget-ok: modal body, wraps
  " Existing clients keep working — no re-distribution.": " Существующие клиенты продолжат работать — раздавать заново не нужно.",
  " One has no recoverable key, so it gets a new one and those clients must re-import.":
    " У одного ключ восстановить нельзя — он получит новый, и его клиентам нужен повторный импорт.",
  " {n} have no recoverable key, so they get a new one and those clients must re-import.":
    " У {n} ключ восстановить нельзя — они получат новые, и их клиентам нужен повторный импорт.",
  "Restore {count} · {node}": "Восстановить {count} · {node}",
  // budget-ok: confirm button, foot has a grow spacer
  "Restore {n}": "Восстановить {n}",
  "Recreate {count} missing on {node} with their saved settings and, where recoverable, their ORIGINAL server keys — every peer re-converges.{vault}{newkey} This is the node-rebuild recovery: after re-installing the box, one press brings its interfaces back.":
    "Пересоздать пропавшие ({count}) на {node} с сохранёнными настройками и, где возможно, с ИСХОДНЫМИ ключами сервера — все пиры сойдутся.{vault}{newkey} Это восстановление после пересборки ноды: переустановили сервер — одно нажатие возвращает его интерфейсы.",
  " You'll unlock the vault once to release the escrowed keys.":   // budget-ok: modal body, wraps
    " Хранилище нужно будет разблокировать один раз, чтобы выдать депонированные ключи.",
  "new key": "новый ключ",
  "(from vault)": "(из хранилища)",
  "{iface}: {err}": "{iface}: {err}",
  "Restoring {count} on {node}{failed} — peers re-converge over the next syncs.":
    "Восстанавливаем {count} на {node}{failed} — пиры сойдутся за следующие синхронизации.",
  " ({n} failed)": " ({n} с ошибкой)",
  "kind|peer": "пир",
  "kind|user": "пользователь",
  "This isn't a transient state — the address has stayed out of range for {dur}.":
    "Это не временное состояние — адрес вне диапазона уже {dur}.",
  // budget-ok: sheet title, 620px wide
  "Fix {who} · {where}": "Исправить {who} · {where}",
  "Fix address": "Исправить адрес",
  "This peer's address {ip} is outside {iface}'s subnet on {node}, so the node can't add it. Fix reassigns the peer the LOWEST free address in {iface}'s subnet — the next one not already taken by another peer on that interface — then the node re-converges. If this peer runs on {iface} across several nodes, they all move to the one new address. Keys and PSK stay the same. {gate}":
    "Адрес пира {ip} вне подсети {iface} на {node}, поэтому нода не может его добавить. Исправление выдаст пиру САМЫЙ МЛАДШИЙ свободный адрес в подсети {iface} — первый не занятый другим пиром на этом интерфейсе — после чего нода сойдётся. Если этот пир живёт на {iface} сразу на нескольких нодах, все перейдут на один новый адрес. Ключи и PSK не меняются. {gate}",
  "Address fixed{to}.": "Адрес исправлен{to}.",
  "Nothing to restore yet — a missing interface must persist a couple of minutes before it's offered.":
    "Восстанавливать пока нечего — интерфейс должен отсутствовать пару минут, прежде чем это предложат.",
  // budget-ok: sheet title, 620px wide
  "Restore {count} missing": "Восстановить пропавшие ({count})",
  "Recreate {count} missing with saved settings and, where recoverable, the ORIGINAL server key — every dangling peer on {them} re-converges.{dirty} Only interfaces missing long enough to be a real outage are included.":
    "Пересоздать пропавшие ({count}) с сохранёнными настройками и, где возможно, с ИСХОДНЫМ ключом сервера — все потерянные пиры на {them} сойдутся.{dirty} Включены только интерфейсы, отсутствующие достаточно долго, чтобы это был настоящий сбой.",
  "ref|it": "нём",
  "ref|them": "них",
  "Restoring {count} — peers re-converge over the next syncs.":
    "Восстанавливаем {count} — пиры сойдутся за следующие синхронизации.",
  "Nothing to fix yet — a broken address must persist a couple of minutes before it's offered.":
    "Исправлять пока нечего — неверный адрес должен продержаться пару минут, прежде чем это предложат.",
  // budget-ok: sheet title, 620px wide
  "Fix {count}": "Исправить {count}",
  // budget-ok: confirm button, foot has a grow spacer
  "Fix {n}": "Исправить {n}",
  "Reassign each of these {count} the LOWEST free address in its interface's subnet (the next one not already taken on that interface), then let the nodes re-converge. Keys and PSK are unchanged. Only records wrong long enough to be a real mismatch are included.":
    "Выдать каждому из этих пиров ({count}) САМЫЙ МЛАДШИЙ свободный адрес в подсети его интерфейса (первый не занятый на этом интерфейсе), после чего ноды сойдутся. Ключи и PSK не меняются. Включены только записи, неверные достаточно долго, чтобы это было настоящим расхождением.",
  // budget-ok: toast, wraps
  "Fixed {count}.": "Исправлено: {count}.",

  // ── block / unblock (js/peer-actions.js) ───────────────────────────────────────────────────────
  "Block access": "Закрыть доступ",
  "Block access · {name}": "Закрыть доступ · {name}",
  "Unblock access": "Открыть доступ",
  "Unblock access · {name}": "Открыть доступ · {name}",
  "Block": "Заблокировать",
  "Unblock": "Разблокировать",
  "This removes the peer from every server it's deployed on, cutting its connection within a sync. The keys are unchanged, so unblocking later restores the same config — no new QR needed.":
    "Пир снимается со всех серверов, где он развёрнут, и соединение обрывается в течение синхронизации. Ключи не меняются, поэтому при открытии доступа заработает тот же конфиг — новый QR не нужен.",
  "This restores the peer on every server it's deployed on. It reconnects with its existing keys once the servers converge.":
    "Пир возвращается на все серверы, где он развёрнут, и переподключается со своими ключами, как только серверы сойдутся.",
  "This blocks every peer of this user and, if they have a subscription, disables its page — the link still resolves but shows “Subscription disabled”. Nothing is deleted: unblocking restores connectivity and the same subscription URL.":
    "Закрываются все пиры пользователя, а если у него есть подписка — отключается её страница: ссылка по-прежнему открывается, но показывает «Подписка отключена». Ничего не удаляется: при открытии доступа возвращаются и связь, и тот же адрес подписки.",
  "This restores every peer and re-enables the subscription page. Connections come back once the servers converge.":
    "Возвращаются все пиры и включается страница подписки. Соединения восстановятся, как только серверы сойдутся.",
  "Blocked because the user is blocked — unblock the user": "Закрыт вместе с пользователем — откройте доступ пользователю",

  // ── the user picker (js/peer-actions.js UserCombo) ─────────────────────────────────────────────
  "— unassigned —": "— не назначен —",
  // budget-ok: input placeholder, hint only
  "Assign to a user…": "Назначить пользователю…",
  // budget-ok: combo popover, sizes to content
  "no match": "нет совпадений",
  // budget-ok: combo popover, sizes to content
  "no users yet": "пользователей пока нет",

  // ── panel settings (js/screen-settings.js) ─────────────────────────────────────────────────────
  // Account, external API, TLS & access, the encryption vault, routing and blocking, subscriptions.
  // budget-ok: breadcrumb, own line
  "Account": "Учётная запись",
  // budget-ok: <h3>, own line
  "Admin login": "Вход администратора",
  "Change the panel username and password. Takes effect immediately — you'll be asked to sign in again. Changing the password also reconnects your *Encryption Vault* to it — the encryption key itself is unchanged, so stored configs and subscription links keep working (no re-issue).":
    "Смена логина и пароля панели. Действует сразу — вас попросят войти заново. Смена пароля также заново привязывает к нему ваше *хранилище шифрования* — сам ключ шифрования не меняется, поэтому сохранённые конфиги и ссылки на подписки продолжают работать (перевыпуск не нужен).",
  "Current password": "Текущий пароль",
  "required to confirm changes": "нужен для подтверждения изменений",
  "New password": "Новый пароль",
  "leave blank to keep current": "оставьте пустым, чтобы не менять",
  "Confirm new password": "Повторите новый пароль",
  // budget-ok: toast, wraps
  "Enter a valid http(s) URL.": "Введите корректный http(s)-адрес.",
  "Webhook saved. This is its *signing secret* — shown once. Every delivery carries an `X-SWG-Signature: sha256=HMAC(secret, body)` header so you can verify it's from this panel.":
    "Вебхук сохранён. Это его *секрет подписи* — показывается один раз. В каждой доставке идёт заголовок `X-SWG-Signature: sha256=HMAC(secret, body)`, по которому можно убедиться, что запрос от этой панели.",
  "Secret": "Секрет",
  // budget-ok: field <label>, own line
  "Payload URL": "URL для полезной нагрузки",
  "The panel POSTs a JSON body here on each selected event. A signing secret is generated on save.":
    "Панель шлёт сюда POST с JSON на каждое выбранное событие. Секрет подписи генерируется при сохранении.",
  "Events": "События",
  "Deliveries enabled": "Доставка включена",
  "Revoke API token": "Отозвать API-токен",
  "Revoke": "Отозвать",
  "Revoke *{label}*? Any integration still using it stops working immediately.":
    "Отозвать *{label}*? Любая интеграция, которая им пользуется, сразу перестанет работать.",
  "External API": "Внешний API",
  "A *read-only* REST + Prometheus surface for external monitoring and automation — Grafana, Uptime Kuma, Prometheus, Terraform/Ansible. No token can ever change the fleet. Authenticate with a bearer token below; `/healthz` and `/api/v1/health` stay open as liveness probes.":
    "Интерфейс *только для чтения*: REST и Prometheus для внешнего мониторинга и автоматизации — Grafana, Uptime Kuma, Prometheus, Terraform/Ansible. Никакой токен не может изменить флот. Авторизация — bearer-токеном ниже; `/healthz` и `/api/v1/health` остаются открытыми как пробы живости.",
  "The API is *off* — endpoints return 401. Minting a token turns it on, or flip the switch above.":
    "API *выключен* — эндпоинты отвечают 401. Выпуск токена включит его, либо переключите тумблер выше.",
  "Access tokens": "Токены доступа",
  "Label (e.g. grafana, prometheus)": "Метка (например grafana, prometheus)",
  "Create token": "Создать токен",
  "New token *{label}* — copy it now, it won't be shown again.": "Новый токен *{label}* — скопируйте сейчас, больше он не покажется.",
  "Token": "Токен",
  "No tokens yet — create one to let an external system read the fleet.": "Токенов пока нет — создайте, чтобы внешняя система могла читать состояние флота.",
  "Webhooks": "Вебхуки",
  // budget-ok: button tooltip, no box
  "Send a test ping": "Отправить тестовый пинг",
  // budget-ok: button in a webhook row, row wraps
  "Test": "Проверить",
  "Endpoints": "Эндпоинты",
  // budget-ok: endpoint description cell, wraps
  "liveness + counts (no auth)": "живость и счётчики (без авторизации)",
  "Prometheus exposition": "экспозиция Prometheus",
  "nodes with status + counts": "ноды со статусом и счётчиками",
  "peers + last-handshake timing": "пиры и время последнего хендшейка",
  "all peers, per-node presence": "все пиры, присутствие по нодам",
  "fleet totals": "итоги по флоту",
  "Test it": "Проверить",
  "Command": "Команда",
  "Prometheus scrape config": "Конфиг сбора для Prometheus",
  "None — plain HTTP (behind a reverse proxy / Cloudflare)": "Нет — обычный HTTP (за обратным прокси / Cloudflare)",
  "Let's Encrypt (HTTP-01 — needs port 80 reachable)": "Let's Encrypt (HTTP-01 — нужен доступный порт 80)",
  "Let's Encrypt via Cloudflare DNS (no port 80; needs a token)": "Let's Encrypt через DNS Cloudflare (без порта 80; нужен токен)",
  "Cloudflare Origin certificate (15y — only valid behind Cloudflare)": "Сертификат Cloudflare Origin (15 лет — работает только за Cloudflare)",
  "Self-signed": "Самоподписанный",
  "127.0.0.1 — local only": "127.0.0.1 — только локально",
  "0.0.0.0 — any IP": "0.0.0.0 — любой IP",
  "Custom IP…": "Свой IP…",
  "Loopback isn't reachable with direct TLS": "Локальный адрес недоступен при прямом TLS",
  "*Loopback won't work with direct TLS.* The {which} terminates its own TLS and is reached *directly* — Cloudflare / clients connect straight to this box — so a `127.0.0.1` Listen IP isn't reachable from outside and fails publicly (Cloudflare shows *521*). Set the Listen IP to `0.0.0.0` (a public interface). Loopback is only correct *behind a reverse proxy* (TLS mode “None”). Save is disabled until this is fixed.":
    "*Локальный адрес не будет работать при прямом TLS.* {which} терминирует собственный TLS, и до него достучиваются *напрямую* — Cloudflare и клиенты подключаются прямо к этому серверу — поэтому IP прослушивания `127.0.0.1` недоступен снаружи и публично не отвечает (Cloudflare показывает *521*). Задайте IP прослушивания `0.0.0.0` (публичный интерфейс). Локальный адрес уместен только *за обратным прокси* (режим TLS «Нет»). Сохранение заблокировано, пока это не исправлено.",

  "*Switching to direct TLS — a coordinated cutover.* The panel will terminate its *own* TLS on *{addr}* — with direct TLS the port comes from the *Public URL* (there is no separate internal port), so put the port clients reach in the URL and set the Listen IP to a *public* address (`0.0.0.0`). Your reverse proxy currently owns that port — *free it first* (stop nginx/Caddy there); the panel and the proxy can't both hold it. On Save the panel binds the new HTTPS address *alongside* the current one and you confirm from it — nodes then reach the panel directly. Nothing is dropped until you confirm.":
    "*Переход на прямой TLS — согласованная пересадка.* Панель будет терминировать *собственный* TLS на *{addr}* — при прямом TLS порт берётся из *публичного URL* (отдельного внутреннего порта нет), поэтому укажите в URL тот порт, на который приходят клиенты, а IP прослушивания задайте *публичный* (`0.0.0.0`). Сейчас этот порт занят вашим обратным прокси — *сначала освободите его* (остановите там nginx/Caddy); панель и прокси не могут держать его вдвоём. При сохранении панель поднимет новый HTTPS-адрес *рядом* с текущим, и вы подтвердите переход уже с него — после этого ноды пойдут к панели напрямую. Пока вы не подтвердите, ничего не отключается.",
  "*Switching to a reverse proxy — a coordinated cutover.* The panel will serve *plain HTTP* on *{addr}* for your proxy to front. Behind a proxy the listen address is its own setting — an *Internal port* field appears below; set it and the Listen IP to `127.0.0.1`, and leave the Public URL as the address your proxy serves. Stand up nginx/Caddy to terminate TLS and `proxy_pass` to that address (sample below), then confirm — the panel keeps serving its current direct-TLS address until you do.":
    "*Переход на обратный прокси — согласованная пересадка.* Панель будет отдавать *обычный HTTP* на *{addr}*, а ваш прокси встанет перед ней. За прокси адрес прослушивания — отдельная настройка: ниже появится поле *Внутренний порт*; задайте его и IP прослушивания `127.0.0.1`, а публичный URL оставьте тем адресом, который отдаёт ваш прокси. Поднимите nginx/Caddy, чтобы он терминировал TLS и делал `proxy_pass` на этот адрес (пример ниже), затем подтвердите — до подтверждения панель продолжает отдавать свой нынешний адрес с прямым TLS.",
  "Cloudflare IP ranges": "Диапазоны IP Cloudflare",
  // budget-ok: button under a wrapping notice
  "Copy Cloudflare IP ranges": "Скопировать диапазоны IP Cloudflare",
  "Change cancelled — kept the current address.": "Изменение отменено — адрес остался прежним.",
  "Couldn't cancel the change.": "Не удалось отменить изменение.",
  "Old port dropped — panel is on the new port.": "Старый порт отключён — панель на новом порту.",
  // budget-ok: toast, wraps
  "Couldn't confirm.": "Не удалось подтвердить.",
  "The old internal port *{old}* *stops serving* — your proxy must already forward to *{new}*.":
    "Старый внутренний порт *{old}* *перестанет отвечать* — ваш прокси уже должен пересылать на *{new}*.",
  "I open *{url}* in a new tab — it's adopted *only if it loads there* and reaches this panel. Nodes then move to it.":
    "Я открою *{url}* в новой вкладке — адрес примется *только если он там откроется* и достучится до этой панели. После этого на него перейдут ноды.",
  "Finish the reverse-proxy switch?": "Завершить переход на обратный прокси?",
  "Not yet": "Ещё нет",
  // budget-ok: lead-in line above a list
  "On Proceed:": "При продолжении:",
  "*⚠️ You can lose access to the panel.* If your web server (nginx / Caddy / Traefik / …) isn't already routing the new address to this panel — wrong upstream port, missing `server_name`, or missing `location` — the old address stops and the new one won't answer.":
    "*⚠️ Вы можете потерять доступ к панели.* Если ваш веб-сервер (nginx / Caddy / Traefik / …) ещё не направляет новый адрес на эту панель — неверный upstream-порт, нет `server_name` или нет `location` — старый адрес отключится, а новый не ответит.",
  "Before proceeding, confirm *{addr}* actually opens the panel. If anything's off, cancel and fix your proxy first — *nothing has changed yet*.":
    "Прежде чем продолжать, убедитесь, что *{addr}* действительно открывает панель. Если что-то не так, отмените и сначала почините прокси — *пока ничего не изменилось*.",
  "Reverted — kept the current address.": "Откатили — адрес остался прежним.",
  "Couldn't revert.": "Не удалось откатить.",
  "Applying your change — this can take up to a minute or two. It hasn't hung; please wait.":
    "Применяем изменение — это может занять минуту-другую. Ничего не зависло, подождите.",
  "Cancel this change": "Отменить это изменение",
  "On confirm the new address opens in a new tab to prove your proxy routes it here before switching nodes over; if it can't load, just revert — nothing changes.":
    "При подтверждении новый адрес откроется в новой вкладке — так вы убедитесь, что прокси ведёт на эту панель, прежде чем переводить ноды; если он не откроется, просто откатите — ничего не изменится.",
  "*Make sure the new address already opens this panel* (proxy upstream / `server_name` / `location`). If it doesn't, the confirm simply won't take — the old address keeps serving, so you can't be locked out.":
    "*Убедитесь, что новый адрес уже открывает эту панель* (upstream прокси / `server_name` / `location`). Если нет, подтверждение просто не сработает — старый адрес продолжит отвечать, так что запереть себя снаружи невозможно.",
  "Take a moment to open the new address and check your proxy first": "Не спешите: сперва откройте новый адрес и проверьте прокси",
  // budget-ok: button in a notice, row wraps
  "Confirm — drop the old port": "Подтвердить — отключить старый порт",
  "Revert": "Откатить",
  "The nodes are still learning the new address": "Ноды ещё узнают новый адрес",
  "Waiting for the container to restart": "Ждём перезапуска контейнера",
  "Discard my edits & refresh": "Отбросить мои правки и обновить",
  "Certificate": "Сертификат",
  // budget-ok: field <label>, own line
  "Account email": "Email учётной записи",
  "admin@example.com": "admin@example.com",
  "Cloudflare API token": "API-токен Cloudflare",
  "Used for DNS-01 validation. Stored on the panel only; never sent to the browser. Enter \"-\" to clear.":
    "Используется для проверки DNS-01. Хранится только на панели и никогда не уходит в браузер. Введите «-», чтобы очистить.",
  "Cloudflare Origin CA token": "Токен Cloudflare Origin CA",
  "Requests a 15-year Cloudflare Origin certificate — valid *only* behind Cloudflare's proxy. Stored on the panel only. Enter \"-\" to clear.":
    "Запрашивает сертификат Cloudflare Origin на 15 лет — действителен *только* за прокси Cloudflare. Хранится только на панели. Введите «-», чтобы очистить.",
  "Panel address": "Адрес панели",
  "Public URL": "Публичный URL",
  "https://panel.example.com  or  https://example.com/swgpanel": "https://panel.example.com  или  https://example.com/swgpanel",
  "Subscription address": "Адрес подписок",
  "https://sub.example.com  or  https://example.com/swgsub": "https://sub.example.com  или  https://example.com/swgsub",
  "Checking…": "Проверяю…",
  "Client configs → Encryption": "Конфиги клиентов → Шифрование",
  "*Escrow interface server keys* — each entry server seals its interface private key to your browser-held *Encryption Vault* key (the panel only ever stores ciphertext). Lets you *restore an interface cleanly after a full wipe / lost box*, with no client re-import. Off ⇒ a wiped node's interfaces can only be recreated with new keys, and every client on them re-imports.":
    "*Депонировать ключи серверов интерфейсов* — каждый входной сервер запечатывает приватный ключ своего интерфейса под ключом *хранилища шифрования*, который держит ваш браузер (панель хранит только шифротекст). Это позволяет *чисто восстановить интерфейс после полной очистки или потери сервера*, без повторного импорта у клиентов. Выключено ⇒ интерфейсы стёртой ноды можно пересоздать только с новыми ключами, и всем их клиентам придётся импортировать заново.",
  "Keep the Encryption Vault unlocked when you need to restore — releasing an escrowed key requires it.":
    "Держите хранилище шифрования открытым, когда нужно восстановление — без него депонированный ключ не выдать.",
  "Config encryption reset.": "Шифрование конфигов сброшено.",
  "Confirm password": "Подтвердите пароль",

  "Your *Encryption Vault* is configured — stored configs are wrapped automatically, and their QRs (and any subscription links) keep working across your password changes.":
    "Ваше *хранилище шифрования* настроено — сохранённые конфиги запечатываются автоматически, а их QR (и ссылки на подписки) продолжают работать при любых сменах пароля.",
  "The vault opens with your *panel password*, which follows every change you make in the panel. Your *encryption key* opens it too — that's what gets you back in if the panel password is ever reset on the server with *swg-passwd*, so keep a copy somewhere safe.":
    "Хранилище открывается вашим *паролем панели*, который следует за каждой сменой пароля в панели. Его открывает и ваш *ключ шифрования* — именно он вернёт вам доступ, если пароль панели однажды сбросят на сервере командой *swg-passwd*, так что храните копию в надёжном месте.",
  "Hide": "Скрыть",
  "Hide mesh (node-to-node relay) traffic": "Скрыть меш-трафик (между нодами)",
  "Show mesh (node-to-node relay) traffic": "Показать меш-трафик (между нодами)",
  // budget-ok: button in a notice, row wraps
  "Confirm & restart": "Подтвердить и перезапустить",
  "Disabling…": "Отключаю…",
  // budget-ok: button in a sheet foot with a grow spacer
  "Re-check": "Проверить снова",
  "Reset encryption": "Сбросить шифрование",
  "Reset encryption…": "Сбросить шифрование…",
  "Show encryption key": "Показать ключ шифрования",
  "Set up the encryption key above first.": "Сначала настройте ключ шифрования выше.",
  "Enter your panel password to unlock the encryption key.": "Введите пароль панели, чтобы открыть ключ шифрования.",
  "Panel password (unlocks the encryption key)": "Пароль панели (открывает ключ шифрования)",
  // budget-ok: switch label, own line
  "Unlock to enable escrow": "Откройте хранилище, чтобы включить депонирование",
  "No changes to save.": "Сохранять нечего.",
  "Remove list from the fleet": "Убрать список из флота",
  "Remove": "Убрать",
  "Remove from the fleet": "Убрать из флота",
  "*Panel settings*": "*Настройки панели*",
  // budget-ok: tab label, tabs size to content
  "Routing": "Маршрутизация",
  "Blocking": "Блокировки",
  "Provider lists": "Списки провайдера",
  "No preset lists yet — use *Add preset list* to pull from the catalog.":
    "Готовых списков пока нет — нажмите *Добавить готовый список*, чтобы взять из каталога.",
  "Custom lists": "Свои списки",
  "New custom list": "Новый свой список",
  "Delete this list": "Удалить этот список",
  "No custom lists yet.": "Своих списков пока нет.",
  // budget-ok: empty state, own block
  "Loading block lists…": "Загружаю списки блокировок…",
  "Delete category · ": "Удалить категорию · ",
  "Delete category": "Удалить категорию",
  "Removes this custom category and its lists. It's deleted from the panel when you Save, and nodes stop filtering it on their next sync. You'd have to recreate it to bring it back.":
    "Убирает эту свою категорию вместе с её списками. Из панели она удалится при сохранении, а ноды перестанут её фильтровать на следующей синхронизации. Чтобы вернуть, придётся создать заново.",
  "A category you created": "Категория, созданная вами",
  "Total entries across this category’s lists": "Всего записей во всех списках этой категории",
  "Matched by IP — works in every mode": "Совпадает по IP — работает в любом режиме",
  "No lists yet": "Списков пока нет",
  "Turn this category on automatically for every new interface (still toggled per interface)":
    "Включать эту категорию автоматически на каждом новом интерфейсе (на самом интерфейсе её всё равно можно выключить)",
  "See what's in this list": "Посмотреть, что в списке",
  "Remove this list from the category": "Убрать этот список из категории",
  "No lists yet — use *+ Add list* above to add one.": "Списков пока нет — нажмите *+ Добавить список* выше.",
  "Delete this custom category": "Удалить эту свою категорию",
  "Block categories": "Категории блокировок",
  "New category": "Новая категория",
  "Which forks appear in the *{v1}* picker when you add a proxy to a node, and each fork's colour. Unticking one only *hides it from that list* — it never touches proxies you've already deployed. {v2}":
    "Какие форки показываются в списке *{v1}*, когда вы добавляете прокси на ноду, и какого цвета каждый форк. Снятая галочка только *убирает форк из этого списка* — она никак не трогает уже развёрнутые прокси. {v2}",
  "Auto-update schedule": "Расписание автообновления",
  "The panel checks each deployed proxy's fork for a newer release and, if there is one, updates the binary and restarts the proxy automatically. A restart briefly drops that proxy's clients, so pick a *quiet hour*. (The panel stages the update; each node applies it on its next sync.)":
    "Панель проверяет форк каждого развёрнутого прокси на новый релиз и, если он есть, сама обновляет бинарник и перезапускает прокси. Перезапуск ненадолго отключает клиентов этого прокси, поэтому выберите *тихий час*. (Панель готовит обновление; каждая нода применяет его на своей следующей синхронизации.)",
  "How often": "Как часто",
  "Every day": "Каждый день",

  "Every 2 days": "Каждые 2 дня",
  "Every 3 days": "Каждые 3 дня",
  "Every week": "Раз в неделю",
  "Off — no auto-updates": "Выкл — без автообновлений",
  "At (panel time)": "В (время панели)",
  "At (node-local time)": "В (местное время ноды)",
  "Check for updates": "Проверить обновления",
  // budget-ok: button in a toolbar with a grow spacer
  "Check client rosters": "Проверить реестры клиентов",
  // budget-ok: field <label>, own line
  "Fallback VK call link": "Запасная ссылка на звонок VK",
  "https://vk.com/call/join/…": "https://vk.com/call/join/…",
  "*Curated* presets are on by default — recommended, ready-to-route lists maintained by the panel. Turn on any public *provider* below to also search its raw catalog; the panel fetches it so its lists appear in the picker. Disabling a provider hides its lists and *deactivates* anything already routed from it until you re-enable it.":
    "*Отобранные* наборы включены по умолчанию — рекомендованные, готовые к маршрутизации списки, которые ведёт панель. Включите любого публичного *провайдера* ниже, чтобы искать ещё и по его сырому каталогу; панель его скачает, и его списки появятся в выборе. Выключение провайдера прячет его списки и *деактивирует* всё, что уже из него маршрутизируется, пока вы не включите его снова.",
  "Retry": "Повторить",
  "Loading providers…": "Загружаю провайдеров…",
  "Custom-list tag colour": "Цвет тега своих списков",
  "The block-list feeds that fill the *Blocking* tab's content categories (ads, malware, adult, and so on). Core feeds are on by default; turn on any extra feed to add its lists to the Blocking picker. Turning one off hides its lists and *deactivates* anything already filtering from it until you re-enable it. Each feed keeps its own tag colour.":
    "Источники списков блокировок, которые наполняют контент-категории вкладки *Блокировки* (реклама, вредоносное, взрослое и так далее). Основные источники включены по умолчанию; включите любой дополнительный, чтобы его списки появились в выборе блокировок. Выключение прячет его списки и *деактивирует* всё, что уже по ним фильтруется, пока вы не включите его снова. У каждого источника свой цвет тега.",
  // budget-ok: section heading, own line
  "Update schedule": "Расписание обновления",
  "When each node re-fetches its lists. Refreshing briefly reloads the node's match sets, which clients can feel — so schedule it for a *quiet hour*. (A failed fetch retries on the next sync; existing lists keep working meanwhile.)":
    "Когда каждая нода заново скачивает свои списки. Обновление ненадолго перезагружает наборы сопоставления на ноде, и клиенты могут это почувствовать — поэтому ставьте его на *тихий час*. (Неудачная загрузка повторится на следующей синхронизации; пока что работают прежние списки.)",
  "Continuous (rolling ": "Непрерывно (скользящее ",
  "Reset": "Сбросить",
  "Peer health detection": "Определение состояния пиров",
  // budget-ok: section heading, own line
  "Defaults": "Значения по умолчанию",
  "https://8.8.8.8/dns-query, 1.1.1.1": "https://8.8.8.8/dns-query, 1.1.1.1",
  // budget-ok: section heading, own line
  "Key escrow & recovery": "Депонирование ключей и восстановление",
  "Authentication": "Вход в панель",
  // Settings section names — the rail is a narrow left column, so these stay short.
  "Mesh & egress": "Меш и выходы",
  "No nodes yet — enroll a node to configure its mesh and egress.":
    "Нод пока нет — подключите ноду, чтобы настроить её меш и выходы.",
  // budget-ok: settings rail entry — the rail sizes to its widest label and the column has room
  "Routing & Blocking": "Политики",
  "Geo data providers": "Провайдеры гео-данных",
  "Integrations": "Интеграции",
  "Change the panel username and password — applied on *{v1}*. Changing either takes effect immediately and you'll be asked to sign in again. Changing the password also re-keys your *Encryption Vault* in place, so stored configs and subscription links keep working (no re-issue).":
    "Смена логина и пароля панели — применяется по кнопке *{v1}*. Любое из изменений действует сразу, и вас попросят войти заново. Смена пароля также перевыпускает ключ вашего *хранилища шифрования* на месте, поэтому сохранённые конфиги и ссылки на подписки продолжают работать (перевыпуск не нужен).",
  "required to confirm a change": "нужен для подтверждения изменения",
  "Client configs": "Конфиги клиентов",
  "Store client configs": "Хранить конфиги клиентов",
  // budget-ok: <select> option, sizes to content
  "Keep encrypted configs — QRs re-viewable anytime": "Хранить зашифрованные конфиги — QR можно открыть в любой момент",
  // budget-ok: <select> option, sizes to content
  "Keep nothing — QR shown once": "Ничего не хранить — QR показывается один раз",
  "Subscriptions": "Подписки",
  "Encryption": "Шифрование",
  "A shareable, themed, mobile page per user showing their QRs. The page's private keys ride in the URL *fragment* and are never sent to the panel — nothing readable is stored on the server. Treat each user's URL as a credential (whoever holds it holds that user's configs). A separate *swg-sub* service serves the page; configure it here and install it on the panel host.":
    "Отдельная страница для каждого пользователя с его QR кодами и конфигами, которой можно поделиться. Приватные ключи завёрнуты во *фрагменте* URL и никогда не уходят на панель — на сервере не хранится ничего читаемого. Относитесь к ссылке каждого пользователя как к учётным данным (у кого ссылка, у того и конфиги). Страницу отдаёт отдельная служба *swg-sub*; настройте её здесь и установите на хосте панели.",
  "Enable subscriptions": "Включить подписки",
  "Off — the subscription page is blocked entirely": "Выкл — страница подписки полностью закрыта",
  // budget-ok: <select> option, sizes to content
  "On — per-user subscription URLs are served": "Вкл — ссылки подписок выдаются для каждого пользователя",
  "Off returns 404 for every subscription URL, regardless of the rest.": "В положении «выкл» любая ссылка подписки отвечает 404, независимо от остального.",
  "When you create a user, mint their subscription link automatically, in the background (user creation stays instant). Needs the encryption key unlocked at that moment; otherwise the link is created the next time you open that user with the key unlocked.":
    "При создании пользователя сразу выпускать его ссылку на подписку в фоне (создание пользователя остаётся мгновенным). В этот момент нужен открытый ключ шифрования; иначе ссылка создастся, когда вы в следующий раз откроете этого пользователя с открытым ключом.",
  "Access expiry": "Срок доступа",
  // budget-ok: field <label>, own line
  "Warn before expiry (days)": "Предупреждать до истечения (дней)",

  // budget-ok: field hint, wraps
  "Default: 3 (0 = warn only once expired)": "По умолчанию 3 (0 = предупреждать только после истечения)",
  "Address & certificate": "Адрес и сертификат",
  "Panel URL": "Адрес панели",
  "Languages": "Языки",
  "Offered on the subscription page": "Предлагаются на странице подписки",
  "Load this language by default": "Загружать этот язык по умолчанию",
  "Which languages the page offers. With just one enabled, it hides the selector and loads that language; the *default* is what loads first when several are offered.":
    "Какие языки предлагает страница. Если включён только один, переключатель скрывается и грузится сразу он; *язык по умолчанию* — тот, что открывается первым, когда языков несколько.",
  "The panel's accent colour — button borders, checkboxes, focus rings, the throughput \"down\" series and the live / hour / day / week / month chart tabs all follow it. A separate colour for each mode; switch *Light / Dark / Auto* from the sun / moon button in the header.":
    "Акцентный цвет панели — ему следуют рамки кнопок, чекбоксы, кольца фокуса, серия «приём» на графиках трафика и вкладки «сейчас / час / сутки / неделя / месяц». Для каждой темы свой цвет; переключить *Светлую / Тёмную / Авто* можно кнопкой солнца или луны в шапке.",
  "Interface theme": "Тема интерфейса",
  "Display": "Отображение",
  "Throughput perspective": "Точка зрения на трафик",
  "Nodes — what the node downloads / uploads": "Ноды — что нода принимает / отдаёт",
  "Peers — what the client downloads / uploads": "Пиры — что принимает / отдаёт клиент",
  "Which way ↓/↑ are labelled across the panel. Same numbers, swapped arrows.": "Как по всей панели подписаны ↓ и ↑. Числа те же, стрелки меняются местами.",
  "Status timing": "Тайминги статусов",
  // budget-ok: field <label>, own line
  "Node stale after (s)": "Нода считается молчащей через (с)",
  // budget-ok: field hint, wraps
  "No sync for this long → the node shows stale.": "Нет синхронизации столько времени → нода показывается как молчащая.",
  "Peer grace window (s)": "Окно ожидания для пира (с)",
  "A peer stays \"online\" this long after its last handshake.": "Пир считается «онлайн» столько времени после последнего хендшейка.",
  "Overview lists": "Списки на обзоре",
  // budget-ok: field hint, wraps
  "Number of peers in the Top talkers list (max 50).": "Сколько пиров показывать в списке самых активных (не больше 50).",
  "Number of categories in the Top destinations list (max 50).": "Сколько категорий показывать в списке направлений (не больше 50).",
  "Title": "Название",
  "e.g. Streaming": "например, Стриминг",
  "IPs / domains / AS numbers": "IP / домены / номера AS",
  "comma-separated — spotify.com, 1.2.3.0/24, AS62041": "через запятую — spotify.com, 1.2.3.0/24, AS62041",
  "Domains match their subdomains too; IPs / CIDRs directly; an *AS number* (e.g. AS62041) resolves to that provider's IP ranges.":
    "Домены совпадают вместе со своими поддоменами; IP и CIDR — напрямую; *номер AS* (например AS62041) разворачивается в диапазоны IP этого провайдера.",
  "Mesh subnet": "Подсеть меша",
  "Mesh port": "Порт меша",
  "Interface name prefix": "Префикс имени интерфейса",
  // budget-ok: button beside a wide input
  "Generate a set": "Сгенерировать набор",
  "Clear (auto)": "Очистить (авто)",
  "Two-factor authentication disabled.": "Двухфакторная аутентификация отключена.",
  // budget-ok: toast, wraps
  "Recovery codes copied.": "Коды восстановления скопированы.",
  "Disable two-factor": "Отключить второй фактор",
  "TOTP QR code": "QR-код TOTP",
  "Can't scan? Enter this key manually": "Не сканируется? Введите этот ключ вручную",
  "Code from the app": "Код из приложения",
  "*Two-factor is on.* Save these recovery codes now — each works once if you lose your authenticator. *They won't be shown again.*":
    "*Второй фактор включён.* Сохраните коды восстановления сейчас — каждый срабатывает один раз, если вы потеряете аутентификатор. *Больше они не покажутся.*",
  // budget-ok: button under a wrapping notice
  "Copy codes": "Скопировать коды",
  "Authentication code (or recovery code)": "Код подтверждения (или код восстановления)",

  "This interface is being *deleted* — the node tears it down on its next sync. It still reports the device, which is the only reason this page is showing.":
    "Этот интерфейс *удаляется* — нода снесёт его на следующей синхронизации. Она всё ещё сообщает об устройстве, только поэтому страница и открывается.",
  "*{v1} peer{v2} on this interface*The node couldn't read their details — they still come across when you adopt.":
    "*{v1} пир{v2} на этом интерфейсе*Нода не смогла прочитать их детали — при приёме они всё равно перейдут.",
  "*{v1}*Nothing is configured on this interface yet. Adopt it to add peers from the panel.":
    "*{v1}*На этом интерфейсе пока ничего не настроено. Примите его, чтобы добавлять пиров из панели.",
  "Ports recovered from its password store — its clients already dial these. The *subnet* is never written to disk, so set that below.":
    "Порты восстановлены из его хранилища паролей — клиенты уже звонят именно на них. *Подсеть* на диск не пишется, поэтому задайте её ниже.",
  // budget-ok: disclosure summary, own line
  "*{v1}* {v2} · first match wins": "*{v1}* {v2} · срабатывает первое совпадение",
  "Delete interface": "Удалить интерфейс",
  "Reassigning to ": "Переназначаем на ",
  "Issue a fresh link and invalidate the current one. A config already scanned keeps working until you rekey or remove the peer.":
    "Выпустить новую ссылку и аннулировать текущую. Уже отсканированный конфиг продолжит работать, пока вы не смените ключи или не удалите пира.",
  "This only turns off this user's subscription LINK — the page stops resolving. It does NOT disconnect their peers: existing connections keep working, and a config already scanned keeps working until you rekey or remove the peer. To actually cut this user's access, use Block instead. Re-enabling later issues a fresh link over the same configs.":
    "Это отключает только ССЫЛКУ подписки этого пользователя — страница перестаёт открываться. Пиры при этом НЕ отключаются: существующие соединения продолжают работать, и уже отсканированный конфиг тоже, пока вы не смените ключи или не удалите пира. Чтобы действительно закрыть доступ, используйте «Закрыть доступ». Повторное включение выпустит новую ссылку поверх тех же конфигов.",
  "vk.ru/call/join/…": "vk.ru/call/join/…",
  "Rebuilding this node's mesh link — it reconnects in a few seconds": "Пересобираем меш-линк этой ноды — она переподключится через несколько секунд",
  // budget-ok: button tooltip, no box
  "Interface defaults in Settings → Interfaces": "Значения по умолчанию для интерфейсов — в «Настройки → Интерфейсы»",
  "Open the interface (read-only) — peers, saved config, and Restore": "Открыть интерфейс (только чтение) — пиры, сохранённый конфиг и восстановление",
  // budget-ok: card tooltip, no box
  "Open the interface (read-only) — recreate & rekey": "Открыть интерфейс (только чтение) — пересоздать и сменить ключи",
  "Open the WDTT server (read-only) — details and Restore": "Открыть сервер WDTT (только чтение) — детали и восстановление",
  "Cancel removal — keep this node": "Отменить удаление — оставить ноду",
  "Deployments": "Подключения",
  "Online": "Онлайн",
  "Dots": "Точки",
  "Arrows": "Стрелки",
  "Pulse": "Пульс",
  "Flow": "Поток",
  "Off": "Выкл",
  // budget-ok: confirm sheet title, 620px wide
  "Stop sending events to *{v1}*?": "Прекратить отправку событий на *{v1}*?",
  "*Confirm the internal-port change.* The public address doesn't change, so the nodes aren't affected — but the panel will restart onto a new internal port, so your *reverse proxy must be re-pointed* to it. When you Confirm, the panel dry-runs the new port (checks it's free), restarts onto it, then waits for you to re-point the proxy. If it stays unreachable it *rolls back to the current port automatically*.":
    "*Подтвердите смену внутреннего порта.* Публичный адрес не меняется, поэтому ноды не затрагиваются — но панель перезапустится на новом внутреннем порту, и ваш *обратный прокси придётся перенаправить* на него. При подтверждении панель сначала прогонит новый порт вхолостую (проверит, что он свободен), перезапустится на него и будет ждать, пока вы перенастроите прокси. Если он так и останется недоступен, панель *автоматически откатится на текущий порт*.",
  "The previous change is still settling (*{v1}s* left).": "Предыдущее изменение ещё устаканивается (осталось *{v1} с*).",
  " The panel serves this address directly, so *the URL carries the port* (there is no separate internal port to set).":
    " Панель отдаёт этот адрес напрямую, поэтому *порт берётся из URL* (отдельного внутреннего порта задавать не нужно).",
  " As with the panel, *the URL carries the port*.": " Как и у панели, *порт берётся из URL*.",
  "*{v1} plaintext config{v2} still on the panel.* Encrypt them so the server can no longer read a client private key. Safe and resumable — the plaintext is deleted only after its encrypted copy exists.":
    "*{v1} конфиг{v2} на панели всё ещё в открытом виде.* Зашифруйте их, чтобы сервер больше не мог прочитать приватный ключ клиента. Безопасно и с возобновлением — открытая копия удаляется только после того, как появилась зашифрованная.",
  "*All stored configs are encrypted.*": "*Все сохранённые конфиги зашифрованы.*",
  "Delete *{v1}*? It's removed from *every node* it's enabled on, and its interface rules stop matching on the next sync. This can't be undone.":
    "Удалить *{v1}*? Он убирается со *всех нод*, где включён, и его правила на интерфейсах перестанут совпадать на следующей синхронизации. Отменить нельзя.",
  "Used for *unassigned* peers, and as the link the panel bakes in when you generate a config here to *test a connection yourself* before handing it out. Leave blank to emit a *{v1}* placeholder. Assigned users should get their *own* VK link — set it in their profile or QR view before you distribute. *Subscription pages ignore this link* and use only the per-user one.":
    "Используется для пиров *без пользователя*, а также как ссылка, которую панель подставляет, когда вы генерируете здесь конфиг, чтобы *самому проверить соединение* перед выдачей. Оставьте пустым, чтобы подставилась заглушка *{v1}*. Назначенным пользователям нужна *своя* ссылка VK — задайте её в профиле или в окне QR до раздачи. *Страницы подписок эту ссылку игнорируют* и берут только персональную.",
  "This interface is gone from the node — uncheck to remove this deployment from the peer":
    "Этот интерфейс пропал с ноды — снимите галочку, чтобы убрать это развёртывание у пира",
  "from server, or e.g. 1.1.1.1": "с сервера или, например, 1.1.1.1",
  // budget-ok: toast, wraps
  "Node force-removed.": "Нода удалена принудительно.",
  // budget-ok: icon-button tooltip, no box
  "Force remove": "Удалить принудительно",
  "Remove node": "Удалить ноду",
  // budget-ok: icon-button tooltip, no box
  "Force remove node": "Удалить ноду принудительно",
  "Flag for removal": "Пометить на удаление",
  "Removes swg-noded / swg-agent and tells the panel it's gone. Force remove is for when the server is unreachable.":
    "Удаляет swg-noded и swg-agent и сообщает панели, что ноды больше нет. Принудительное удаление — на случай, когда сервер недоступен.",
  "Via this turn-proxy": "Через этот turn-прокси",
  "The node is setting it up right now": "Нода настраивает его прямо сейчас",
  "Delete this IP record": "Удалить эту запись IP",
  "Turn-proxy removal requested — the node stops + removes it on its next sync.":
    "Удаление turn-прокси запрошено — нода остановит и удалит его на следующей синхронизации.",
  "Delete turn-proxy": "Удалить turn-прокси",
  "fields removed upstream": "поля убраны в апстриме",
  "values removed upstream": "значения убраны в апстриме",
  "Roll this client's schema to a previous app version": "Откатить схему этого клиента на предыдущую версию приложения",
  "Extra command-line flags that *pre-fill* a new {v1} server. It's self-contained — its real config lives per interface — so there's little to default here beyond advanced flags.":
    "Дополнительные флаги командной строки, которые *предзаполняют* новый сервер {v1}. Он самодостаточен — его настоящая конфигурация живёт на каждом интерфейсе — поэтому задавать здесь по умолчанию почти нечего, кроме продвинутых флагов.",
  "The ExecStart flags that *pre-fill* a new {v1} proxy. Nothing here changes proxies you've already deployed.":
    "Флаги ExecStart, которые *предзаполняют* новый прокси {v1}. Ничто здесь не меняет уже развёрнутые прокси.",
  "WDTT server removed — the node tears it down on its next sync.": "Сервер WDTT удалён — нода снесёт его на следующей синхронизации.",
  "Delete WDTT server": "Удалить сервер WDTT",

  "*Finish the reverse-proxy switch.* The panel is serving the old *and* new setup at once — each node keeps its current address and only moves once the old one stops. Update your reverse proxy to match {v1}, then confirm. Nothing goes down in between.":
    "*Завершите переход на обратный прокси.* Панель сейчас отдаёт и старую, *и* новую конфигурацию одновременно — каждая нода держит свой текущий адрес и переедет, только когда старый отключится. Настройте обратный прокси соответственно {v1}, затем подтвердите. Между этими шагами ничего не падает.",
  "If that tab *can't* load, just close it: this panel stays on the current address and reverts automatically. Nothing is committed until the new address answers.":
    "Если та вкладка *не откроется*, просто закройте её: эта панель останется на текущем адресе и откатится сама. Пока новый адрес не ответит, ничего не фиксируется.",
  "*Behind a reverse proxy.*":
    "*За обратным прокси.*",
  "*Save your encryption key now — it is shown only once.* It protects every stored client config (and your subscriptions) and is independent of your login password; store it somewhere safe (a password manager). Lose it and your login both, and you'd re-key the affected peers.":
    "*Сохраните ключ шифрования сейчас — он показывается только один раз.* Он защищает все сохранённые конфиги клиентов (и ваши подписки) и не зависит от пароля входа; держите его в надёжном месте (менеджер паролей). Потеряете и его, и пароль — придётся перевыпускать ключи затронутым пирам.",
  "*Your encryption key.* Anyone holding this can read every stored config — treat it like a password and store it in a password manager.":
    "*Ваш ключ шифрования.* Любой, у кого он есть, может прочитать все сохранённые конфиги — относитесь к нему как к паролю и храните в менеджере паролей.",

  // ── turn-proxies: cards, setup, ExecStart, client rosters, versions, WDTT (js/turn.js) ─────────
  // Fork names, ExecStart flags, TURN_MANAGE / SWG_GH_TOKEN and bind errors stay verbatim — they are what
  // the operator greps for in logs and units.
  "Turn-proxy fork": "Форк turn-прокси",
  "Forwards to": "Ведёт на",
  "Setup new proxy": "Поднять прокси",
  "Stopped from the panel — open to Start it": "Остановлен из панели — откройте, чтобы запустить",
  "Service down on the node": "Служба не работает на ноде",
  "Forwards to a port with no managed interface behind it — likely a misconfiguration.":
    "Ведёт на порт, за которым нет управляемого интерфейса — похоже на ошибку настройки.",
  "Assigned — waiting for the node to pick it up and install it": "Назначен — ждём, пока нода подхватит и установит",
  "Turn-proxy settings in Settings → Turn proxies": "Настройки turn-прокси — в «Настройки → Turn-прокси»",
  "Turn-proxy management is *off* on this node — no Docker socket was mounted at install (*TURN_MANAGE=manual*), so these are read-only here. Add, edit or restart them on the box directly.":
    "Управление turn-прокси на этой ноде *выключено* — при установке не был примонтирован сокет Docker (*TURN_MANAGE=manual*), поэтому здесь они только для чтения. Добавляйте, правьте и перезапускайте их прямо на ноде.",

  // Collected VK IPs
  "Collected IPs": "Собранные IP",
  "Collected VK IPs": "Собранные IP VK",
  "No connections seen yet.": "Соединений пока не видели.",
  "Flush offline recorded IPs": "Очистить офлайн-записи IP",
  "Flush": "Очистить",
  "Remove {count} offline recorded for *this turn-proxy only*. Currently-online relays are kept, and other proxies are untouched.":
    "Удалить {count} из офлайн-записей *только этого turn-прокси*. Активные сейчас релеи сохранятся, другие прокси не тронуты.",
  "Flush recorded IP history": "Очистить историю записанных IP",
  "Flush the collected turn-proxy IP history across the fleet? The currently-online IPs are kept.":
    "Очистить собранную историю IP turn-прокси по всему флоту? Активные сейчас IP сохранятся.",
  "Unique VK server IPs the nodes collected via turn-proxies.": "Уникальные IP серверов VK, собранные нодами через turn-прокси.",
  "Turn IP": "IP turn",
  // budget-ok: grid header, column sizes to content
  "Last": "Последний раз",
  "Collected by": "Собрал",
  "Flush turn-proxies history": "Очистить историю turn-прокси",
  "No turn-proxy connections collected yet.": "Соединений turn-прокси пока не собрано.",

  // Service lifecycle
  "Turn-proxy {verb} requested — applies on the node's next sync.":
    "Запрошено: {verb} turn-прокси — применится на следующей синхронизации ноды.",
  "Turn-proxy update requested — applies on the node's next sync.":
    "Обновление turn-прокси запрошено — применится на следующей синхронизации ноды.",
  "Pending turn-proxy request cancelled.": "Ожидающий запрос turn-прокси отменён.",
  // budget-ok: toast, wraps
  "Restart requested — applies on the node's next sync.": "Перезапуск запрошен — применится на следующей синхронизации ноды.",
  // budget-ok: toast, wraps
  "Stop requested — applies on the node's next sync.": "Остановка запрошена — применится на следующей синхронизации ноды.",
  // budget-ok: toast, wraps
  "Start requested — applies on the node's next sync.": "Запуск запрошен — применится на следующей синхронизации ноды.",
  "Turn-proxy adopt requested — the node reads it on its next sync.":
    "Приём turn-прокси запрошен — нода прочитает его на следующей синхронизации.",
  "Turn-proxy install requested — the node downloads + starts it on its next sync.":
    "Установка turn-прокси запрошена — нода скачает и запустит его на следующей синхронизации.",
  "No changes.": "Изменений нет.",
  // budget-ok: toast, wraps
  "Title saved — the proxy keeps running.": "Название сохранено — прокси продолжает работать.",
  // budget-ok: toast, wraps
  "Title saved.": "Название сохранено.",
  "Start the service on the node": "Запустить службу на ноде",
  "Stop the service on the node (stays down until started)": "Остановить службу на ноде (останется остановленной до запуска)",
  "Restart the service on the node": "Перезапустить службу на ноде",
  "Re-download the binary and start the service on the node": "Перекачать бинарник и запустить службу на ноде",
  "Installing…": "Устанавливаю…",
  "Reinstall service": "Переустановить службу",

  // ExecStart editor
  "Changing any field rewrites the unit's ExecStart on the node and restarts it.":
    "Изменение любого поля перезаписывает ExecStart юнита на ноде и перезапускает его.",
  "The parameters below are placed verbatim after `-connect` — wrap key, wrap mode, any flags the fork supports.":
    "Параметры ниже подставляются дословно после `-connect` — ключ обёртки, режим обёртки, любые флаги, которые поддерживает форк.",
  // budget-ok: field <label>, own line
  "Listen IP": "Внешний IP",
  "Custom IP:Port…": "Свой IP:порт…",
  "Server parameters": "Параметры сервера",
  "Obfuscation": "Обфускация",
  // budget-ok: inline button beside a wide input
  "Generate key": "Сгенерировать ключ",
  // budget-ok: link-button beside a wide input
  "Generate": "Сгенерировать",
  "Not generated yet": "Ещё не сгенерирован",
  "ExecStart parameters": "Параметры ExecStart",
  // budget-ok: textarea placeholder, wide field
  "extra flags — appended verbatim, e.g. -debug": "дополнительные флаги — подставляются дословно, например -debug",
  "64 hex chars — blank = a fresh key per proxy": "64 hex-символа — пусто = свежий ключ на каждый прокси",
  "Bridge node: the proxy binds `0.0.0.0` inside the container and this port is published, so enter the node's *public* IP/host (what clients dial) here.":
    "Нода на bridge: прокси слушает `0.0.0.0` внутри контейнера, а порт публикуется, поэтому укажите здесь *публичный* IP или хост ноды (куда звонят клиенты).",
  "This isn't a detected address on the node. The proxy *binds* to this address — it must be a real IP on the server, or it dies with `bind: cannot assign requested address`.":
    "Это не обнаруженный на ноде адрес. Прокси *привязывается* к нему, поэтому это должен быть настоящий IP на сервере, иначе он упадёт с `bind: cannot assign requested address`.",
  "This isn't a detected address on the node. The proxy *binds* to it, so it must be a real IP on the server — otherwise it dies with `bind: cannot assign requested address`.":
    "Это не обнаруженный на ноде адрес. Прокси *привязывается* к нему, поэтому это должен быть настоящий IP на сервере — иначе он упадёт с `bind: cannot assign requested address`.",
  "This forwards to a port with no managed interface behind it. Make sure a wg/awg interface is really listening there, or clients reach the proxy but get no tunnel.":
    "Он ведёт на порт, за которым нет управляемого интерфейса. Убедитесь, что там действительно слушает интерфейс wg/awg, иначе клиенты дойдут до прокси, но туннеля не получат.",
  "This *stops, disables and removes* the turn-proxy service *{label}* on the node. Clients pointed at it stop connecting. This can't be undone. (To keep the service running and only unlink it from the panel, use *Disconnect*.)":
    "Это *останавливает, отключает и удаляет* службу turn-прокси *{label}* на ноде. Клиенты, направленные на неё, перестанут подключаться. Отменить нельзя. (Чтобы служба продолжила работать и только отвязалась от панели, используйте *Отвязать*.)",
  "WDTT servers are *self-contained* — each owns its own WireGuard interface. The interface name, subnet, endpoint / DTLS port, internal WG port, egress, routing and filters are set *per interface* (in the interface's create / edit modal), and the WRAP password is minted on the node — everything on the top line is a placeholder. Only the extra flags below pre-fill a new WDTT instance.":
    "Серверы WDTT *самодостаточны* — у каждого свой интерфейс WireGuard. Имя интерфейса, подсеть, эндпоинт и порт DTLS, внутренний порт WG, выход, маршрутизация и фильтры задаются *для каждого интерфейса* (в окне создания или правки интерфейса), а пароль WRAP выпускается на ноде — всё в верхней строке лишь заглушки. Только дополнительные флаги ниже предзаполнят новый экземпляр WDTT.",
  "You're setting the *default* parameters for the actual turn-proxies you'll create on nodes later — nothing is deployed now. The top line is filled in per real proxy: the node's *listen* address (`server_ip:port`), the *interface* it forwards to (`interface_ip:port`), and the obfuscation you set above — those are placeholders here. Whatever you type below is appended to the command as-is.":
    "Вы задаёте параметры *по умолчанию* для тех turn-прокси, которые создадите на нодах позже — сейчас ничего не разворачивается. Верхняя строка подставляется для каждого реального прокси: *внешний адрес* ноды (`server_ip:port`), *интерфейс*, на который он ведёт (`interface_ip:port`), и заданная выше обфускация — здесь это заглушки. Всё, что вы наберёте ниже, добавится к команде как есть.",
  "The top line is this proxy's actual command — the *listen* address and *interface* you set above, plus the obfuscation here. Whatever you type below is appended verbatim.":
    "Верхняя строка — настоящая команда этого прокси: заданные выше *внешний адрес* и *интерфейс* плюс обфускация берётся из панели. Всё, что вы наберёте ниже, добавится к строке запуска.",

  // Client app picker
  // budget-ok: picker heading, own line
  "Select an app for each OS": "Выберите приложение для каждой ОС",
  "not offered": "не предлагается",
  "no client": "нет клиента",
  "Not offered": "Не предлагается",
  // budget-ok: hover bubble, wraps
  " — {os} users get no card for this server": " — пользователи {os} не увидят карточку этого сервера",
  "Don't offer": "Не предлагать",
  " for {os}": " для {os}",
  // budget-ok: faint hint under a picker option, wraps
  "no card on their page": "карточки на их странице не будет",
  // budget-ok: hint block, wraps
  "Pick a client app above first.": "Сначала выберите клиентское приложение выше.",

  // Client rosters (schema diffs)
  "Client rosters": "Реестры клиентов",
  "Each client app's config schema vs upstream on GitHub.": "Схема конфигурации каждого клиента против апстрима на GitHub.",
  "new adoptable fields ·": "новых полей к принятию ·",
  "new values ·": "новых значений ·",
  // budget-ok: inside wrapping hint prose
  "new items that need a panel update (encoder wiring) before they work.":
    "новых пунктов, которым нужно обновление панели (поддержка в кодировщике), чтобы заработать.",
  "Set version": "Задать версию",
  "rolls a client back to a previous app version.": "откатывает клиент на предыдущую версию приложения.",
  "Review": "Разобрать",
  // budget-ok: sheet title, 740px wide
  "Review changes": "Разобрать изменения",
  "Rate-limited by GitHub (60/hour unauthenticated); set `SWG_GH_TOKEN` to lift it. A field tagged \"needs wiring\" becomes usable after a panel update.":
    "GitHub ограничивает частоту (60/час без авторизации); задайте `SWG_GH_TOKEN`, чтобы снять лимит. Поле с пометкой «нужна поддержка» станет доступным после обновления панели.",
  "new adoptable fields": "новые поля к принятию",
  "new values for existing settings": "новые значения существующих настроек",
  "new fields/values — need a panel update to use": "новые поля и значения — нужны обновления панели",
  // budget-ok: <select> option, sizes to content
  "↻ Track latest": "↻ Следить за последней",
  // budget-ok: link text in a version cell, wraps
  "couldn't fetch": "не удалось получить",
  "Preserve current": "Оставить как есть",
  "adopting…": "принимаю…",
  "Adopt changes": "Принять изменения",
  "Schema changes for": "Изменения схемы для",
  " (upstream {ver})": " (апстрим {ver})",
  "Needs-wiring": "Нужна поддержка",
  "items can't be adopted until a panel update teaches the encoder to emit them.":
    "нельзя принять, пока обновление панели не научит кодировщик их выдавать.",
  "Check all": "Отметить все",
  "Add {value} to {field}": "Добавить {value} в {field}",
  "Remove {value} from {field}": "Убрать {value} из {field}",
  "Needs wiring": "Нужна поддержка",
  "Upstream changes to": "Изменения в апстриме у",
  "'s config schema since you last reviewed it. Adopting records you've caught up — the schema edit itself, if one's needed, is a code change.":
    " с момента, когда вы разбирали её в прошлый раз. Принятие фиксирует, что вы в курсе — сама правка схемы, если она нужна, делается в коде.",
  "The source moved but nothing field-level was parsed — adopt to acknowledge the new commit.":
    "Исходник сдвинулся, но на уровне полей ничего не разобрано — примите, чтобы отметить новый коммит.",
  "source changed": "исходник изменился",
  "Best-effort parse (Python/Go source)": "Разбор по мере сил (исходник Python/Go)",

  // Versions
  "Installed": "Установлено",
  // budget-ok: <select> option, sizes to content
  "Use latest version": "Использовать последнюю версию",
  "Version & rollback": "Версия и откат",
  "Pinned to *{held}* but the node is still running *{inst}* — the version swap failed on the node (often a checksum mismatch). Check the proxy's status, then re-try or pick a different version.":
    "Закреплена *{held}*, но нода всё ещё работает на *{inst}* — смена версии на ноде не удалась (часто из-за несовпадения контрольной суммы). Проверьте состояние прокси, затем повторите или выберите другую версию.",
  "A {fork} server shares one binary per node, so the version is per node — every {fork} instance on a node moves together. Pinning an older version *holds* it (no auto-update); *Use latest* follows new releases.":
    "Сервер {fork} использует один бинарник на ноду, поэтому версия задаётся на ноду — все экземпляры {fork} на ноде переезжают вместе. Закрепление старой версии *удерживает* её (без автообновления); *Использовать последнюю* следует за новыми релизами.",

  // Setup sheet
  "Source": "Источник",
  "Install a fork": "Установить форк",
  "Adopt existing service": "Принять существующую службу",
  "Adopt a turn-proxy already running as a systemd service on this node.":
    "Принять turn-прокси, который уже работает как служба systemd на этой ноде.",
  "The node reads the unit's ExecStart (listen, forwards-to, wrap key) on its next sync and it shows up here.":
    "Нода прочитает ExecStart юнита (прослушивание, куда ведёт, ключ обёртки) на следующей синхронизации, и он появится здесь.",
  "Service unit path": "Путь к юниту службы",
  "An address on this server — the proxy binds to it": "Адрес на этом сервере — прокси к нему привязывается",

  // WDTT server
  "WDTT server requested — the node installs it on its next sync. Add users from Peers.":
    "Сервер WDTT запрошен — нода установит его на следующей синхронизации. Пользователей добавляйте из «Пиров».",
  // budget-ok: field <label>, own line
  "Serves": "Обслуживает",
  "Built-in userspace WireGuard": "Встроенный WireGuard в userspace",
  "WDTT owns its own WireGuard interface — users attach to it directly (no forwards-to). WDTT mints each user's key + IP on connect; you add + manage users from Peers.":
    "У WDTT собственный интерфейс WireGuard — пользователи подключаются прямо к нему (никуда вести не нужно). WDTT выпускает ключ и IP каждого пользователя при подключении; добавлять и вести пользователей — из «Пиров».",
  // budget-ok: disclosure title, own line
  "Advanced — built-in interface": "Дополнительно — встроенный интерфейс",
  "Internal subnet": "Внутренняя подсеть",
  "Auto-assigned to avoid collisions with this node's other WDTT servers, interfaces, and ports.":
    "Назначается автоматически, чтобы не столкнуться с другими серверами WDTT, интерфейсами и портами этой ноды.",
  "Restoring the vaulted server identity": "Возвращаем идентичность сервера из хранилища",
  "A vaulted identity exists — restore it to bring this server back with its original key":
    "Идентичность есть в хранилище — восстановите её, чтобы вернуть сервер с исходным ключом",
  "Installing / starting on the node": "Устанавливаем / запускаем на ноде",
  "Connected to this WDTT server": "Подключены к этому серверу WDTT",
  "WDTT fork": "Форк WDTT",
  "WDTT server instance": "Экземпляр сервера WDTT",
  "Fork is set at create. Endpoint & listen port are edited from the WDTT-proxy modal.":
    "Форк задаётся при создании. Эндпоинт и порт прослушивания правятся в окне WDTT-прокси.",
  "Change the endpoint or port?": "Изменить эндпоинт или порт?",
  "Change the internal WG port?": "Изменить внутренний порт WG?",
  "Apply change": "Применить",
  "Change {what}?": "Изменить {what}?",
  "saving…": "сохраняю…",
  "Changing the endpoint or port rewrites the unit's ExecStart on the node and restarts it — every user's link is re-issued.":
    "Смена эндпоинта или порта перезаписывает ExecStart юнита на ноде и перезапускает его — ссылки всех пользователей перевыпускаются.",
  "— self-contained (its own userspace-WireGuard)": "— самодостаточен (свой WireGuard в userspace)",
  "Egress, routing & filters": "Выход, маршрутизация и фильтры",
  "Edit interface": "Изменить интерфейс",
  "This server was wiped. Its identity (server keypair + owner password) is *escrowed in your Encryption Vault*. *Restore* to bring it back with its original identity — no user re-imports.":
    "Этот сервер был стёрт. Его идентичность (пара ключей сервера и пароль владельца) *депонирована в вашем хранилище шифрования*. *Восстановить* — вернуть его с исходной идентичностью, повторный импорт пользователям не нужен.",
  "No escrowed identity is stored for this server.": "Для этого сервера депонированной идентичности нет.",
  "Restoring the original server identity — the node applies it on its next sync.":
    "Возвращаем исходную идентичность сервера — нода применит её на следующей синхронизации.",
  "Recreate with a fresh identity?": "Пересоздать с новой идентичностью?",
  "This *abandons the vaulted server identity* and generates a NEW server key for *{iface}*. Every existing user must *re-import* their link. Use this only if the Encryption Vault can't be unlocked. Type *{iface}* to confirm.":
    "Это *отказывается от депонированной идентичности сервера* и выпускает НОВЫЙ ключ сервера для *{iface}*. Всем существующим пользователям придётся *импортировать заново* свою ссылку. Делайте это, только если хранилище шифрования не открывается. Введите *{iface}* для подтверждения.",
  "This stops and removes the WDTT server *{iface}* on this node and disconnects its users. Each user's credential is a password on *this* server, so its peers go with it (a peer also deployed elsewhere keeps those deployments). Type *{iface}* to confirm.":
    "Это останавливает и удаляет сервер WDTT *{iface}* на этой ноде и отключает его пользователей. Учётные данные каждого пользователя — это пароль на *этом* сервере, поэтому его пиры уходят вместе с ним (пир, развёрнутый ещё где-то, сохраняет те развёртывания). Введите *{iface}* для подтверждения.",
  "This server is being *taken over* right now — its settings are read-only until the node reports the result.":
    "Этот сервер *принимается* прямо сейчас — его настройки только для чтения, пока нода не сообщит результат.",
  "*WDTT* owns its own *WireGuard* interface *({iface} · {addr})* and mints each user's key on connect.":
    "*WDTT* владеет собственным интерфейсом *WireGuard* *({iface} · {addr})* и выпускает ключ каждого пользователя при подключении.",

  // ── interfaces: adopt, details, create/edit, key drift, mesh links (js/iface.js) ────────────────
  // "Adopt" is the panel's word for taking over an interface the node already runs — «принять», kept
  // consistent with the button. WireGuard / AmneziaWG / WDTT / DTLS stay untranslated.
  "Ignored interfaces": "Скрытые интерфейсы",
  "Interfaces found on your nodes that you told the panel to leave alone. They keep running exactly as they are — nothing here is managed, and nothing is shown on the node's page. *Adopt* one to start managing it.":
    "Интерфейсы, найденные на ваших нодах, которые вы велели панели не трогать. Они продолжают работать как есть — здесь ничем не управляют и на странице ноды ничего не показывают. *Примите* один, чтобы начать им управлять.",
  "This interface is *ignored* — the panel isn't managing it and it's hidden from the node's page. It's listed in *Settings → Interfaces*. *Un-ignore* to bring it back as a candidate, or *Adopt* to start managing it now.":
    "Этот интерфейс *скрыт* — панель им не управляет и не показывает его на странице ноды. Он перечислен в *Настройки → Интерфейсы*. *Вернуть* — чтобы снова считать его кандидатом, или *Принять* — чтобы начать управлять прямо сейчас.",
  "A WDTT server is *installed here but not running*. It owns its own tunnel device, so while it is stopped there is no interface, no socket and no process — this directory is its only trace. *Adopt* takes it over and starts it, keeping its server key and users, so existing clients keep working; *Ignore* leaves it alone.":
    "Здесь *установлен, но не запущен* сервер WDTT. Он владеет собственным туннельным устройством, поэтому пока он остановлен, нет ни интерфейса, ни сокета, ни процесса — этот каталог его единственный след. *Принять* берёт его под управление и запускает, сохраняя ключ сервера и пользователей, так что существующие клиенты продолжат работать; *Скрыть* оставит его в покое.",
  "*Its ports couldn't be identified*, so adoption will offer defaults — replace them with the ports this server was actually listening on. Clients dial the port written into the config they already hold, so adopting on the wrong one leaves every existing user unable to connect until you re-issue and re-distribute their links.":
    "*Порты определить не удалось*, поэтому при приёме предложат значения по умолчанию — замените их портами, которые сервер действительно слушал. Клиенты звонят на порт, записанный в уже выданном им конфиге, поэтому приём на неверном порту оставит всех существующих пользователей без связи, пока вы не перевыпустите и не раздадите их ссылки.",
  "This is a *WDTT* interface — a userspace tunnel owned by its own server. *Adopt* takes it over keeping its identity and passwords, so existing clients keep working; *Ignore* leaves it alone.":
    "Это интерфейс *WDTT* — туннель в userspace, которым владеет собственный сервер. *Принять* берёт его под управление, сохраняя идентичность и пароли, так что существующие клиенты продолжат работать; *Скрыть* оставит его в покое.",
  "This interface is on the node but the panel doesn't manage it, so its type isn't established yet — *you choose it while adopting*. *Adopt* to start managing it (its existing peers are kept), or *Ignore* to dismiss it.":
    "Этот интерфейс есть на ноде, но панель им не управляет, поэтому его тип ещё не определён — *вы выбираете его при приёме*. *Принять* — начать управлять (существующие пиры сохранятся), *Скрыть* — убрать из предложений.",
  "Un-ignore": "Вернуть",
  "Ignore": "Скрыть",
  "Interface details": "Об интерфейсе",
  "Interface details (saved)": "Об интерфейсе (сохранённое)",
  "Interface (lost — no recoverable key)": "Интерфейс (потерян — ключ не восстановить)",
  "Start managing this interface from the panel": "Начать управлять этим интерфейсом из панели",
  "Installed on disk, nothing running": "Установлен на диске, ничего не запущено",
  "not running": "не запущен",
  "Type": "Тип",
  "chosen when you adopt": "выбирается при приёме",
  // budget-ok: card row label, own cell
  "Server identity": "Идентичность сервера",
  "Server address": "Адрес сервера",
  // budget-ok: Panel heading, own line
  "Users on this server": "Пользователи этого сервера",
  "Peers on this interface": "Пиры на этом интерфейсе",
  "LAST SEEN": "БЫЛ",
  "EXPIRES": "ИСТЕКАЕТ",
  "TRANSFER": "ТРАФИК",
  "PUBLIC KEY": "ПУБЛИЧНЫЙ КЛЮЧ",
  "LAST HANDSHAKE": "ПОСЛЕДНИЙ ХЕНДШЕЙК",
  "connected before": "подключался раньше",
  "never connected": "не подключался",
  "Password store": "Хранилище паролей",
  "none found": "не найдено",
  "Its *{count}* come across on adopt — open the install from its card to see them.":
    "Его *{count}* перейдут при приёме — откройте установку с её карточки, чтобы посмотреть.",
  "Adopting — the node starts this server with its existing key on the next sync.":
    "Принимаем — нода запустит этот сервер с его существующим ключом на следующей синхронизации.",
  "Adopting the WDTT server — the node takes it over on its next sync.":
    "Принимаем сервер WDTT — нода возьмёт его под управление на следующей синхронизации.",
  "Adopting interface — the node will start managing it.": "Принимаем интерфейс — нода начнёт им управлять.",
  "Its *server key and passwords are kept* — the panel installs our build over this config directory and starts it, so any client that already has a config keeps working.":
    "Его *ключ сервера и пароли сохраняются* — панель ставит нашу сборку поверх этого каталога конфигурации и запускает её, поэтому любой клиент с уже выданным конфигом продолжает работать.",
  "Its *server key and passwords are kept* — a panel-managed instance is built that reuses them, then the old process is stopped. Every client that already has a config keeps working.":
    "Его *ключ сервера и пароли сохраняются* — собирается управляемый панелью экземпляр, который их переиспользует, после чего старый процесс останавливается. Каждый клиент с уже выданным конфигом продолжает работать.",
  "Its *server key and existing peers are kept* (add-only — the panel never removes peers it didn't create), so nothing needs re-distributing.":
    "Его *ключ сервера и существующие пиры сохраняются* (только добавление — панель никогда не удаляет пиров, которых не создавала), поэтому ничего раздавать заново не нужно.",
  "This interface has {count} existing. Changing the *listen port* or *endpoint* will break their current configs — you'd re-distribute the QR codes.":
    "На этом интерфейсе уже есть {count}. Смена *порта прослушивания* или *эндпоинта* сломает их текущие конфиги — QR придётся раздать заново.",
  "A *WDTT server owns this interface* and manages its own peers. Adopting it as {type} leaves both the panel and that server writing the same peer list — it appears to work until they disagree. Adopt it as *WDTT* unless you know why you want this.":
    "Этим интерфейсом *владеет сервер WDTT*, и он сам управляет своими пирами. Приём его как {type} оставит и панель, и этот сервер писать один и тот же список пиров — всё выглядит рабочим, пока они не разойдутся. Принимайте его как *WDTT*, если не знаете точно, зачем вам иначе.",
  "Start managing this interface on {node}. The panel doesn't know its type — {choose}":
    "Начать управлять этим интерфейсом на {node}. Панель не знает его тип — {choose}",
  "choose it below": "выберите его ниже",
  // budget-ok: continues the intro sentence, wraps
  ". Preselected {type} because {why}": ". Предварительно выбран {type}, потому что {why}",
  "Interface type": "Тип интерфейса",
  "Server fork": "Форк сервера",
  "Interface name": "Имя интерфейса",
  "Endpoint host / IP": "Хост / IP эндпоинта",
  "Public endpoint host / IP": "Публичный хост / IP эндпоинта",
  "Auto (node's detected address)": "Авто (определённый адрес ноды)",
  "vpn.xyz.com or 203.0.113.7": "vpn.xyz.com или 203.0.113.7",
  "What clients dial": "Куда звонят клиенты",
  "What clients dial. Leave blank to use the node's detected address.":
    "Куда звонят клиенты. Оставьте пустым, чтобы использовать определённый адрес ноды.",
  "What clients dial — config-facing only": "Куда звонят клиенты — только для конфигов",
  "Tunnel subnet (CIDR)": "Подсеть туннеля (CIDR)",
  "Tunnel subnet": "Подсеть туннеля",
  // budget-ok: field <label>, own line
  "Listen port (DTLS)": "Внешний порт (DTLS)",
  // budget-ok: field <label> / card row label, own line
  "Listen port": "Внешний порт",
  "Internal WG port": "Внутренний порт WG",
  // budget-ok: field hint, wraps
  "The server's own tunnel port": "Собственный туннельный порт сервера",
  "The server's own tunnel port — not dialled by clients": "Собственный туннельный порт сервера — клиенты на него не звонят",
  "DTLS listen (outside)": "Приём DTLS (снаружи)",
  "Loopback userspace-WG port (server-internal)": "Локальный порт userspace-WG (внутри сервера)",
  "Which WDTT server implements this instance": "Какой сервер WDTT реализует этот экземпляр",
  "Datapath": "Датапас",
  "Existing peers": "Существующие пиры",
  // budget-ok: card row label, own cell
  "Config file": "Файл конфигурации",
  "Config directory": "Каталог конфигурации",
  // budget-ok: field <label>, own line
  "Config path": "Путь к конфигурации",
  "Protocol": "Протокол",
  "recoverable": "восстановим",
  "not found": "не найдено",
  "Not found": "Не найдено",
  "Path to the server's key file": "Путь к файлу ключа сервера",
  "If you know where it lives, point at it — the node checks the file first and adopts only if it can read it. Nothing is stopped or overwritten until that check passes, so a wrong path costs nothing.":
    "Если знаете, где он лежит, укажите — нода сперва проверит файл и примет сервер, только если сможет его прочитать. Пока проверка не пройдена, ничего не останавливается и не перезаписывается, так что неверный путь ничего не стоит.",
  "The directory holding its": "Каталог, где лежит его",
  "— for an install the node hasn't discovered (moved, renamed, or stopped).":
    "— для установки, которую нода не обнаружила (перенесена, переименована или остановлена).",
  "the node no longer reports a WDTT install at this path — it may have been started (look for it as an interface) or removed.":
    "нода больше не сообщает об установке WDTT по этому пути — возможно, её запустили (ищите как интерфейс) или удалили.",
  "This node runs in a container, so it can only read paths inside it — a config elsewhere on the host is invisible from here. *The interface must be running*: the node then adopts it from the live device (keys, peers, ports and AmneziaWG parameters, all fresher than any file). A stopped interface whose config the node can't read cannot be adopted.":
    "Эта нода работает в контейнере, поэтому видит только пути внутри него — конфиг где-то ещё на хосте отсюда не виден. *Интерфейс должен быть запущен*: тогда нода примет его прямо с живого устройства (ключи, пиры, порты и параметры AmneziaWG — всё свежее любого файла). Остановленный интерфейс, чей конфиг нода прочитать не может, принять нельзя.",
  // budget-ok: toolbar button, row has a grow spacer
  "Adopt existing": "Принять существующий",
  "Taking over an interface already on the node — its keys and peers are kept.":
    "Берём под управление интерфейс, который уже есть на ноде — его ключи и пиры сохраняются.",
  "If the node has discovered this server it is quicker to adopt it from its *orphan card* on the node screen — the node has already read its fork, ports and identity. Point at the directory here when it hasn't: an install that was moved, renamed, or is stopped.":
    "Если нода уже обнаружила этот интерфейс, лучше принять его с *карточки* на странице ноды — нода уже прочитала его форк, порты и идентичность. Используйте этот функционал только если нода не смогла обнаружить самостоятельно: установка перенесена, переименована или остановлена.",
  // budget-ok: field hint, wraps
  "Fixed — must match the peers that reference it.": "Фиксировано — должно совпадать с пирами, которые на него ссылаются.",
  "Subnet already used by {iface} on {node} — interface subnets must be unique across the fleet.":
    "Подсеть уже занята интерфейсом {iface} на {node} — подсети интерфейсов должны быть уникальны по всему флоту.",
  "AmneziaWG parameters": "Параметры AmneziaWG",
  "Rendered into configs/QRs. Leave blank to keep the interface's existing values.":
    "Подставляются в конфиги и QR. Оставьте пустым, чтобы сохранить текущие значения интерфейса.",
  "Pushed to the node's interface and rendered into configs/QRs. Existing clients must re-import after a change.":
    "Отправляются на интерфейс ноды и подставляются в конфиги и QR. После изменения существующим клиентам нужен повторный импорт.",
  // budget-ok: disclosure title, own line
  "Filters & abuse": "Фильтры и ограничения",
  "Advanced settings": "Дополнительно",
  "MTU · keepalive · DNS": "MTU · keepalive · DNS",
  "Blank = 1280": "Пусто = 1280",
  "0 disables · blank = 25": "0 отключает · пусто = 25",
  "Comma-separated": "Через запятую",
  // budget-ok: field hint, wraps
  "Default for new peers": "По умолчанию для новых пиров",
  // budget-ok: field <label>, own line
  "Host tunnel IP": "IP туннеля на хосте",
  // budget-ok: faint suffix in a field row, wraps
  "(set at creation — delete & recreate to change)": "(задаётся при создании — чтобы изменить, удалите и создайте заново)",

  // Interface detail: down / gone / lost
  "This interface is *down* on the node — its config below is read from the *.conf* (not live). The node reported: {reason}. Use *Start interface* — if the bring-up fails, the exact reason (port clash, a left-over kernel interface of the same name, an unsupported AmneziaWG parameter, …) shows here.":
    "Этот интерфейс *не поднят* на ноде — конфиг ниже прочитан из *.conf* (не живой). Нода сообщила: {reason}. Нажмите *Запустить интерфейс* — если поднять не удастся, точная причина (конфликт порта, оставшийся интерфейс ядра с тем же именем, неподдерживаемый параметр AmneziaWG, …) появится здесь.",
  "This interface is *down* on the node. Change the *Listen port* to a free one and *Save* — the panel will write the new port and restart the interface to bring it up.":
    "Этот интерфейс *не поднят* на ноде. Смените *Внешний порт* на свободный и нажмите *Сохранить* — панель запишет новый порт и перезапустит интерфейс.",
  "Interface *{iface}* is gone from {node} — the panel no longer sees it, so this view is *read-only* and shows the panel's saved config. {verdict} The only action here is *Restore interface*.":
    "Интерфейс *{iface}* пропал с {node} — панель его больше не видит, поэтому это представление *только для чтения* и показывает сохранённый конфиг панели. {verdict} Единственное доступное действие — *Восстановить интерфейс*.",
  "Its original server key is recoverable, so Restore recreates it cleanly and every peer below reconnects with no changes.":
    "Исходный ключ сервера восстановим, поэтому восстановление пересоздаст его чисто, и все пиры ниже переподключатся без изменений.",
  "Its original server key can't be recovered, so Restore recreates it with a NEW key and the peers below must re-import a fresh config.":
    "Исходный ключ сервера восстановить нельзя, поэтому восстановление пересоздаст его с НОВЫМ ключом, и пирам ниже понадобится импортировать свежий конфиг.",
  "Interface *{iface}* is gone from {node} with *no recoverable key*, so it can't be restored — this view is *read-only*. Recreating it means a *new server key*, and every peer below must *re-import* a fresh QR / config. The only action here is *Recreate and rekey interface*.":
    "Интерфейс *{iface}* пропал с {node}, и *ключ восстановить нельзя*, поэтому восстановить его не выйдет — это представление *только для чтения*. Пересоздание означает *новый ключ сервера*, и каждому пиру ниже придётся *импортировать заново* свежий QR или конфиг. Единственное доступное действие — *Пересоздать и сменить ключи*.",
  "Interface *{iface}* is gone from {node} with *no recoverable key*, so it can't be restored — only recreated with a *new server key*. Its *{count}* will be rekeyed once it's back, so *every client must re-import* a fresh QR / config. Review the settings below (inferred from the peers) and recreate.":
    "Интерфейс *{iface}* пропал с {node}, и *ключ восстановить нельзя*, поэтому его можно только пересоздать с *новым ключом сервера*. Его *{count}* получат новые ключи, как только он вернётся, поэтому *каждому клиенту нужен повторный импорт* свежего QR или конфига. Проверьте настройки ниже (выведены из пиров) и пересоздайте.",
  "Recreate and rekey interface": "Пересоздать и сменить ключи",
  "Peers affected": "Затронуто пиров",
  "This interface hasn't been reported in a snapshot yet.": "Этот интерфейс ещё не появлялся в снапшоте.",
  "Action failed on the node": "Действие не удалось на ноде",

  // Service controls
  "Stopped by you — Start it whenever you're ready": "Остановлен вами — запустите, когда будете готовы",
  "Start service": "Запустить",
  "Stop service": "Остановить",
  "Restart service": "Перезапустить",
  "Bring this interface up on the node": "Поднять этот интерфейс на ноде",
  "Take this interface down on the node (stays down until started)": "Опустить этот интерфейс на ноде (останется опущенным до запуска)",
  "Bounce this interface's service on the node (down then up)": "Перезапустить службу этого интерфейса на ноде (вниз, затем вверх)",
  "Take this WDTT server down (stays down until started)": "Остановить этот сервер WDTT (останется остановленным до запуска)",
  "Bounce this WDTT server on the node": "Перезапустить этот сервер WDTT на ноде",
  "Reachable via turn-proxy": "Доступен через turn-прокси",
  // budget-ok: Panel heading, own line
  "Unmanaged on this interface": "Не под управлением на этом интерфейсе",
  "Adopt all": "Принять все",
  "The node applies the take-over on its next sync": "Нода применит приём на следующей синхронизации",
  "This server is being *taken over* — the node stops the existing one and brings it back up under the panel with its original identity and users. Its controls stay disabled until that finishes.":
    "Этот сервер *принимается* — нода останавливает существующий и поднимает его снова под панелью с исходной идентичностью и пользователями. До конца этого его управление остаётся выключенным.",
  "This node isn't reporting this server — it's gone from the box (a rebuild, or a node running a build without WDTT support).":
    "Нода не сообщает об этом сервере — он пропал с сервера (пересборка или нода со сборкой без поддержки WDTT).",
  "This server was wiped.": "Этот сервер был стёрт.",
  "Its identity is escrowed in your Encryption Vault, so it's held offline rather than coming back with a fresh key that would break every user. *Restore* to bring it back with its original identity, or *Recreate fresh* (every user re-imports).":
    "Его идентичность депонирована в вашем хранилище шифрования, поэтому он держится офлайн, а не возвращается со свежим ключом, который сломал бы всех пользователей. *Восстановить* — вернуть его с исходной идентичностью, или *Пересоздать заново* (все пользователи импортируют заново).",
  "Recreate fresh": "Пересоздать заново",
  "Recreating…": "Пересоздаю…",
  "Bring this WDTT server up on the node": "Поднять этот сервер WDTT на ноде",
  "Unavailable while the node is down": "Недоступно, пока нода не в строю",
  "not installed": "не установлен",
  "won’t survive a reboot": "не переживёт перезагрузку",
  "Every client on this interface will stop connecting with their current config. You must re-issue and re-distribute every QR code / config. The original key is discarded.":
    "Все клиенты этого интерфейса перестанут подключаться со своими текущими конфигами. Придётся перевыпустить и раздать каждый QR и конфиг. Исходный ключ отбрасывается.",
  "Key": "Ключ",

  // Docker bridge publishing
  "Creation requested — it applies on the node's next sync. This node runs on `bridge` networking, so this interface's UDP port isn't reachable from outside until you publish it on the host (otherwise peers won't handshake — rx stays 0).":
    "Создание запрошено — применится на следующей синхронизации ноды. Эта нода работает в режиме сети `bridge`, поэтому UDP-порт этого интерфейса недоступен снаружи, пока вы не опубликуете его на хосте (иначе пиры не сделают хендшейк — rx останется 0).",
  "1. Add under {key} in the node's docker-compose.yml": "1. Добавьте в {key} в docker-compose.yml ноды",
  "2. Apply (in the node's compose dir)": "2. Примените (в каталоге compose ноды)",
  "Re-installing the node with host networking avoids per-port publishing entirely.":
    "Переустановка ноды с сетью host избавляет от публикации портов вовсе.",
  "This docker node uses `bridge` networking — after creating you must publish this port in the node's `docker-compose.yml` ({ports}) and `up -d`, or clients can't reach it. (A host-networking node needs none of this.)":
    "Эта docker-нода работает в режиме сети `bridge` — после создания порт нужно опубликовать в `docker-compose.yml` ноды ({ports}) и выполнить `up -d`, иначе клиенты до него не достучатся. (Ноде с сетью host всё это не нужно.)",
  // budget-ok: confirm sheet title, 480px wide
  "Unlock to capture the rekeyed configs": "Откройте хранилище, чтобы сохранить перевыпущенные конфиги",

  // Delete
  "Interface deletion requested — the node tears it down on its next sync.":
    "Удаление интерфейса запрошено — нода снесёт его на следующей синхронизации.",
  "This permanently tears down *{iface}* on the node: the interface goes *down*, its *.conf and server key are removed*, and *every peer on this interface is destroyed*. Peers deployed only here are deleted from the panel and their configs/QRs stop working. This can't be undone.":
    "Это навсегда сносит *{iface}* на ноде: интерфейс *опускается*, его *.conf и ключ сервера удаляются*, и *все пиры на этом интерфейсе уничтожаются*. Пиры, развёрнутые только здесь, удаляются из панели, и их конфиги и QR перестают работать. Отменить нельзя.",

  // Mesh link details
  // budget-ok: field <label>, own line
  "Dial source IP": "IP источника для звонка",
  // budget-ok: field <label>, own line
  "Dial endpoint IP": "IP эндпоинта для звонка",
  "— {node}'s IP": "— IP ноды {node}",
  "Per-connection overrides: which of *{a}*'s IPs dials out, and which of *{b}*'s IPs it dials to (overriding {b}'s default ingress). Changing the endpoint re-connects this link automatically. Neither changes how routed traffic appears externally — that's the exit node's egress IP":
    "Переопределения для этого соединения: с какого IP ноды *{a}* идёт звонок и на какой IP ноды *{b}* он идёт (вместо её входящего адреса по умолчанию). Смена эндпоинта переподключает линк автоматически. Ни то, ни другое не меняет, как маршрутизированный трафик выглядит снаружи — это IP выхода узла-выхода",
  "These interfaces' client traffic exits the fleet through *{node}*{smart}.":
    "Клиентский трафик этих интерфейсов выходит из флота через *{node}*{smart}.",
  // budget-ok: clause inside wrapping prose
  " — smart-routed by destination": " — с умной маршрутизацией по назначению",
  "This is a panel-managed mesh link to *{node}*. It's created and torn down automatically as nodes are added or removed. To route a user interface's traffic out through this node, set that interface's egress to *Forward to {node}*.":
    "Это меш-линк до *{node}*, которым управляет панель. Он создаётся и сносится автоматически по мере добавления и удаления нод. Чтобы направить трафик пользовательского интерфейса через эту ноду, задайте её в выходе того интерфейса: *Переслать на {node}*.",
  "Changing the *endpoint* or *port* will break the existing clients' connections; you will need to re-distribute the configs / QR codes.":
    "Смена *эндпоинта* или *порта* разорвёт соединения существующих клиентов; конфиги и QR придётся раздать заново.",

  // Server-key drift
  "*New server key adopted.* Re-issue and re-distribute the QR codes / configs — *subscribed users update automatically*.":
    "*Новый ключ сервера принят.* Перевыпустите и раздайте QR и конфиги — *у подписчиков всё обновится само*.",
  "*Restoring the original key…* The node reverts to its backed-up key on its next sync — existing clients keep working, no re-distribution.":
    "*Возвращаем исходный ключ…* Нода вернётся к своей резервной копии ключа на следующей синхронизации — существующие клиенты продолжат работать, раздавать заново ничего не нужно.",
  "*Original key restored.* The node reverted to its backed-up key — existing clients keep working, no re-distribution needed.":
    "*Исходный ключ возвращён.* Нода вернулась к резервной копии ключа — существующие клиенты продолжают работать, раздавать заново ничего не нужно.",
  "Restoring the original key": "Возвращаем исходный ключ",
  "The node is reverting this interface to its backed-up original server key on its next sync. Existing clients keep working — no re-distribution needed.":
    "Нода вернёт этот интерфейс к резервной копии исходного ключа сервера на следующей синхронизации. Существующие клиенты продолжат работать — раздавать заново ничего не нужно.",
  "Restore original key": "Вернуть исходный ключ",
  // budget-ok: faint hint under a button, wraps
  "Reverts to the backed-up key — existing clients keep working, no re-distribution.":
    "Возврат к резервной копии ключа — существующие клиенты продолжат работать, раздавать заново ничего не нужно.",
  "Adopt the new server key?": "Принять новый ключ сервера?",
  // budget-ok: drift button, row wraps
  "Adopt new key": "Принять новый ключ",
  "New server key adopted": "Новый ключ сервера принят",
  "*Restore failed.* The node couldn't revert to its backed-up key: {err} — try again, or adopt the new key instead.":
    "*Возврат не удался.* Нода не смогла вернуться к резервной копии ключа: {err} — попробуйте ещё раз или примите новый ключ.",
  "*Server key changed on the node.* This interface's server keypair was rotated directly on the server, so *every client's existing config / QR for this interface no longer connects*.":
    "*Ключ сервера изменён на ноде.* Пара ключей сервера этого интерфейса была сменена прямо на сервере, поэтому *ни один существующий конфиг или QR клиента для этого интерфейса больше не подключается*.",
  "The node kept a backup of the original key.": "Нода сохранила резервную копию исходного ключа.",
  "*The node no longer holds the original key* (it was re-created), so it can't be restored — only adopted.":
    "*Исходного ключа у ноды больше нет* (он был пересоздан), поэтому вернуть его нельзя — только принять новый.",
  "*Edited directly on the server.* The panel paused pushing these so your change survives — Adopt to keep the server value, or Restore to re-apply the panel's:":
    "*Правили прямо на сервере.* Панель приостановила отправку этих значений, чтобы ваше изменение уцелело — «Принять», чтобы оставить значение сервера, или «Вернуть», чтобы применить значение панели:",
  "on node =": "на ноде =",
  "Adopted the server value.": "Значение сервера принято.",
  "Restoring the panel value on the next sync.": "Значение панели вернётся на следующей синхронизации.",
  "Restore panel value": "Вернуть значение панели",

  // ── routing & blocking policy (js/routing.js) ──────────────────────────────────────────────────
  // Mode names stay recognisable: Force-DNS, SNI and MASQUERADE are the words an operator will search for,
  // so they are not translated. The prose around them is.
  "Host": "Хост",
  "cap|IP": "IP",
  "Matchable by domain — needs Force-DNS or SNI mode": "Совпадает по домену — нужен режим Force-DNS или SNI",
  "Matchable by IP range — works in every mode": "Совпадает по диапазону IP — работает в любом режиме",
  // budget-ok: hover caption
  "Large list — noticeable memory / reload on any node that routes it":
    "Большой список — заметная память и перезагрузка на любой ноде, которая его маршрутизирует",
  "View this list on GitHub": "Открыть этот список на GitHub",

  // The four routing modes (MODE_META)
  // budget-ok: mode-card title, own line
  "Default routing": "Обычная маршрутизация",
  "IP only": "Только IP",
  "no host layer": "без слоя хостов",
  // budget-ok: mode-card line, wraps
  "Just the always-on IP layer — no domain matching added": "Только всегда включённый слой IP — совпадений по доменам не добавляется",
  "Simplest & most robust · never touches DNS · carries all traffic (calls, UDP, QUIC)":
    "Проще и надёжнее всего · не трогает DNS · несёт весь трафик (звонки, UDP, QUIC)",
  "Can't separate services that share IPs (YouTube vs Google), no Host routing":
    "Не разделяет сервисы с общими IP (YouTube и Google), маршрутизации по хосту нет",
  "Blocks by IP / threat-feed only — domain content filters can't apply":
    "Блокирует только по IP и фидам угроз — доменные фильтры не применяются",
  "Matches by destination IP (GeoIP / ASN) — routing never depends on DNS, so your clients' DoH, DoT and plain DNS all keep working untouched. Simplest and most robust; it just can't separate services that share IPs (YouTube vs Google), and a CDN category catches everything behind it.":
    "Совпадает по IP назначения (GeoIP / ASN) — маршрутизация не зависит от DNS, поэтому DoH, DoT и обычный DNS клиентов работают нетронутыми. Самый простой и надёжный вариант; но он не разделяет сервисы с общими IP (YouTube и Google), а категория CDN ловит всё, что за ней стоит.",
  "Force-DNS": "Force-DNS",
  "Host via DNS": "Хост через DNS",
  "host layer · via DNS": "слой хостов · через DNS",
  "Adds domain matching by resolving your clients' DNS through the node":
    "Добавляет совпадение по доменам, разрешая DNS клиентов через ноду",
  "Per-service precise · fills before the first connection (no first-hit miss)":
    "Точность · заполняется до первого соединения (промаха на первом нет)",
  "Intercepts & downgrades client DNS — blocks their DoH / DoT":
    "Перехватывает и понижает DNS клиента — блокирует его DoH / DoT",
  "Enforces domain content filters directly": "Применяет доменные контент-фильтры напрямую",
  // budget-ok: mode-card bullet, wraps
  "Long block lists cost CPU per DNS query — keep them small (≈100k domains)":
    "Длинные списки блокировки дорогие для CPU на каждый DNS-запрос — держите их небольшими (≈100 тыс. доменов)",
  "The node becomes your clients' resolver and blocks their encrypted DNS — both DoH (known providers) and all DoT — so it can route by hostname too, per-service precise. Trade-off: it sees and downgrades the client's DNS, can break a client that insists on its own encrypted DNS, and a DoH server it doesn't recognise can still slip past.":
    "Нода становится резолвером клиентов и блокирует их шифрованный DNS — и DoH (известных провайдеров), и весь DoT — благодаря чему может маршрутизировать ещё и по имени хоста, точно до сервиса. Плата: она видит и понижает DNS клиента, может сломать клиент, который настаивает на своём шифрованном DNS, а незнакомый ей DoH-сервер всё же проскочит.",
  "Kernel SNI": "Kernel SNI",
  "Host via SNI": "Хост через SNI",
  "host layer · SNI in-kernel": "слой хостов · SNI в ядре",
  "Scans the TLS SNI in-kernel — client DNS stays private": "Читает SNI из TLS в ядре — DNS клиента остаётся приватным",
  "Daemonless & parallel per-CPU · lightest at high connection rates":
    "Без демона, параллельно по ядрам · лучший при большом числе соединений",
  // budget-ok: mode-card bullet, wraps
  "Wins stability and high-connection-rate CPU over Hybrid":
    "Выигрывает у Hybrid по стабильности и по CPU при большом числе соединений",
  "Substring match only · needs xt_string + ipset on the node":
    "Совпадение только по подстроке · нужны xt_string и ipset на ноде",
  "Domain content filters inert — steer them to Force-DNS / Hybrid":
    "Доменные контент-фильтры не работают — переводите их на Force-DNS / Hybrid",
  "Scans the SNI from each TLS handshake entirely in the kernel (xt_string) and learns each destination's IP into the routing set — no userspace helper, and your clients' DNS (DoH, DoT or plain) is never touched. Runs in parallel across CPUs, so it stays light even at high connection rates. Matches by substring only and needs the node's kernel to provide xt_string + ipset. Names hidden by ECH, and QUIC / HTTP3, fall back to IP routing.":
    "Читает SNI из каждого TLS-рукопожатия целиком в ядре (xt_string) и запоминает IP каждого назначения в маршрутный набор — без помощника в userspace, и DNS клиентов (DoH, DoT или обычный) не трогается вовсе. Работает параллельно по ядрам, поэтому остаётся лёгким даже при большом числе соединений. Совпадает только по подстроке и требует xt_string и ipset в ядре ноды. Имена, скрытые ECH, а также QUIC / HTTP3 уходят на маршрутизацию по IP.",
  "Hybrid SNI": "Hybrid SNI",
  "host layer · SNI in userspace": "слой хостов · SNI в userspace",
  "Parses the TLS SNI in a small helper — client DNS stays private":
    "Разбирает SNI из TLS в маленьком помощнике — DNS клиента остаётся приватным",
  // budget-ok: a wrapping bullet in the routing-mode card, and 1 char over. It is also SHORTER than the
  // string this replaces ("… · умеет regex · …", 78 chars), which shipped and fit — dropping the regex
  // claim shortened the Russian while the English key shrank more, which is the whole "breach".
  "Precise parsed-SNI matching · unbothered by big lists":
    "Точное совпадение по разобранному SNI · не боится больших списков",
  "Has fewer kernel deps, wins accuracy over Kernel":
    "Меньше зависит от ядра, выигрывает у Kernel по точности",
  "Runs a helper process (fails open — learning pauses — if it stops)":
    "Держит процесс-помощник (при остановке пропускает трафик, обучение встаёт)",
  "Enforces domain content filters — learns & drops; best for large block lists":
    "Применяет доменные контент-фильтры · учится и отбрасывает · лучший вариант для больших списков",
  "Routes by hostname by parsing the SNI from each TLS handshake in a small userspace helper, so your clients' DNS — DoH, DoT or plain — is never touched, observed or downgraded: the connection stays encrypted end-to-end. Parses the real SNI field (precise, fine with very large lists). Learns each destination on its first connection (a brand-new host routes on the next one); names hidden by ECH, and QUIC / HTTP3, fall back to IP routing.":
    "Маршрутизирует по имени хоста, разбирая SNI из каждого TLS-рукопожатия в маленьком помощнике в userspace, поэтому DNS клиентов — DoH, DoT или обычный — не трогается, не просматривается и не понижается: соединение остаётся зашифрованным от края до края. Разбирает настоящее поле SNI (точно, спокойно к очень большим спискам). Узнаёт каждое назначение на первом соединении (совсем новый хост маршрутизируется со следующего); имена, скрытые ECH, а также QUIC / HTTP3 уходят на маршрутизацию по IP.",

  // The IP-learning explainer (Trich: *emphasis* travels inside the string)
  "A host's name is only visible once its connection starts, so the *first* connection to a brand-new host has already left on the default path before it can be routed. The engine learns that host's IP and *resets that one connection* so the client instantly reconnects on the correct route — that's the *new hosts rerouted* count; every later connection matches by IP and is never reset.":
    "Имя хоста видно только после начала соединения, поэтому *первое* соединение с совершенно новым хостом уже ушло по маршруту по умолчанию, прежде чем его можно было направить. Движок узнаёт IP этого хоста и *сбрасывает именно это соединение*, чтобы клиент мгновенно переподключился по верному маршруту — это и есть счётчик *новых хостов перенаправлено*; каждое следующее соединение совпадает по IP и уже не сбрасывается.",
  "The *records* toggle (the database icon) controls *IP learning*. Each IP is remembered by *category* (not by domain), so it stays valid even if you later change that category's lists or custom domains. Nothing is kept forever: *On* (default) holds a learned IP for about *1 hour*, so repeat connections route instantly. *Off* keeps the node *fresh* — an IP is held only about *2 minutes*, so a host whose address rotates is never routed on a stale IP (at a little extra CPU, as more connections are re-scanned). Once it expires, the IP is simply re-learned on the next connection.":
    "Переключатель *записей* (иконка базы) управляет *обучением по IP*. Каждый IP запоминается по *категории* (а не по домену), поэтому остаётся верным, даже если вы потом поменяете списки этой категории или свои домены. Ничто не хранится вечно: *Вкл* (по умолчанию) держит выученный IP около *часа*, чтобы повторные соединения шли мгновенно. *Выкл* держит ноду *свежей* — IP живёт всего около *2 минут*, поэтому хост с меняющимся адресом никогда не маршрутизируется по устаревшему IP (ценой небольшого расхода CPU: больше соединений пересканируется). Когда срок истекает, IP просто выучивается заново на следующем соединении.",

  // Reset dialog
  "Reset learned IPs": "Сбросить выученные IP",
  // budget-ok: sheet-foot button, foot has a grow spacer
  "Reset all routing": "Сбросить всю маршрутизацию",
  "*Reset learned IPs* clears only the IPs this node has learned from SNI so far — its tables and lists stay in place and it re-learns as traffic flows. *Reset all routing* wipes the smart-routing tables, learned IPs and cached lists, then rebuilds from scratch and re-pulls every list from the panel; routing may blip for a few seconds.":
    "*Сбросить выученные IP* очищает только те IP, которые нода успела выучить из SNI — её таблицы и списки остаются на месте, и она снова учится по мере трафика. *Сбросить всю маршрутизацию* стирает таблицы умной маршрутизации, выученные IP и кэш списков, затем пересобирает всё с нуля и заново тянет каждый список с панели; маршрутизация может моргнуть на несколько секунд.",
  "Type {learn} or {all} to confirm your action": "Введите {learn} или {all} для подтверждения",
  "RESET LEARNED / RESET ALL": "RESET LEARNED / RESET ALL",
  "Enabled on": "Включено на",

  // Blocking catalog
  "Loading block catalog…": "Загружаю каталог блокировок…",
  "Content filtering": "Контент-фильтрация",
  // budget-ok: group heading on its own line
  "Traffic & abuse": "Трафик и ограничения",
  "— built-in": "— встроенные",
  "No content-filter categories are enabled on this node yet — turn them on in {where}.":
    "На этой ноде пока не включена ни одна категория контент-фильтрации — включите их в {where}.",
  // budget-ok: inline link inside wrapping prose
  "Settings ▸ Routing & Blocking": "Настройки ▸ Политики",
  "No IP list in this category — domain lists can't match in {mode}. Use Force-DNS / Hybrid-SNI, or add an IP list.":
    "В этой категории нет списка IP — доменные списки не совпадают в режиме «{mode}». Используйте Force-DNS / Hybrid-SNI или добавьте список IP.",
  // budget-ok: toolbar button, row has a grow spacer
  "Add list": "Добавить список",
  "Search lists…": "Поиск по спискам…",
  // budget-ok: sheet title, 520px wide
  "New block category": "Новая категория блокировки",
  // budget-ok: input placeholder in a 520px sheet
  "e.g. Corporate block": "например, Корпоративная блокировка",
  "Add lists next — the category matches by domain or IP depending on the lists you pick.":
    "Дальше добавьте списки — категория совпадает по домену или по IP в зависимости от выбранных списков.",
  "A category with that name already exists.": "Категория с таким именем уже есть.",
  "Custom IPs / domains…": "Свои IP / домены…",
  "Recommended presets": "Рекомендуемые наборы",
  "Provider catalog": "Каталог провайдера",
  "Loading catalog…": "Загружаю каталог…",
  "Enable a provider in Settings → Geo data providers to search its catalog.":
    "Включите провайдера в «Настройки → Провайдеры гео-данных», чтобы искать по его каталогу.",
  "Greyed lists match by *domain* only — this node is *IP-only* (no host layer). Switch it to Force-DNS or SNI to use them.":
    "Серые списки совпадают только по *домену* — эта нода работает *только по IP* (без слоя хостов). Переключите её на Force-DNS или SNI, чтобы ими пользоваться.",
  // budget-ok: toast, wraps
  "Switched to Force-DNS — domain rules now match. Save to apply.":
    "Переключено на Force-DNS — доменные правила теперь совпадают. Сохраните, чтобы применить.",

  // Routing rules
  // budget-ok: field <label> / disclosure title, own line
  "Routing rules": "Правила маршрутизации",
  // budget-ok: label suffix, wraps with the label
  "— first match wins": "— срабатывает первое совпадение",
  "Direct (this node)": "Напрямую (эта нода)",
  "Exit via node": "Выход через ноду",
  "Remove rule": "Удалить правило",
  // budget-ok: toolbar button, row has a grow spacer
  "Add rule": "Добавить правило",
  "Everything else": "Всё остальное",
  "No rules yet. Add a rule to send a category through another node, or set *Everything else* to channel everything.":
    "Правил пока нет. Добавьте правило, чтобы отправить категорию через другую ноду, или задайте *Всё остальное*, чтобы гнать через неё весь трафик.",
  "Matched by domain — needs Force-DNS or Hybrid-SNI mode": "Совпадает по домену — нужен режим Force-DNS или Hybrid-SNI",
  "Domain list — needs Force-DNS or Hybrid-SNI mode": "Список доменов — нужен режим Force-DNS или Hybrid-SNI",
  "IP list — works in every mode": "Список IP — работает в любом режиме",
  // budget-ok: inline lint under a rule row, wraps
  "can't exit via itself": "не может выходить через себя",
  "shadowed by an earlier {cat} rule": "перекрыто более ранним правилом «{cat}»",
  "IPs / CIDRs / AS numbers (IP-only mode) — e.g. 1.2.3.0/24, AS62041":
    "IP / CIDR / номера AS (режим только по IP) — например 1.2.3.0/24, AS62041",
  "IPs / domains / AS numbers — e.g. youtube.com, 1.2.3.0/24, AS62041":
    "IP / домены / номера AS — например youtube.com, 1.2.3.0/24, AS62041",
  "add at least one IP or CIDR": "добавьте хотя бы один IP или CIDR",
  "add at least one IP or domain": "добавьте хотя бы один IP или домен",
  "not a valid IP, CIDR or domain: {toks}": "не похоже на IP, CIDR или домен: {toks}",
  "IP-only mode — {toks} are domains. Use IPs/CIDRs, or {switch}.":
    "Режим только по IP — {toks} это домены. Используйте IP/CIDR или {switch}.",
  "IP-only mode — {toks} is a domain. Use IPs/CIDRs, or {switch}.":
    "Режим только по IP — {toks} это домен. Используйте IP/CIDR или {switch}.",
  "switch this node to Force-DNS": "переключите ноду на Force-DNS",
  // budget-ok: hover caption
  "Manage routing lists in Settings → Routing lists": "Управление списками маршрутизации — в «Настройки → Списки маршрутизации»",

  // Egress
  "Outbound (egress) interface": "Интерфейс выхода (egress)",
  "Outbound (egress) IP": "IP выхода (egress)",
  "Auto (MASQUERADE)": "Авто (MASQUERADE)",
  "Forward to node (cascade)": "Переслать на ноду (каскад)",
  "Forward to {node}": "Переслать на {node}",
  "Smart routing (by destination)": "Умная маршрутизация (по назначению)",
  "Exit directly out a NIC, channel everything through another node, or route per-destination (smart).":
    "Выходить напрямую через сетевую карту, гнать всё через другую ноду или маршрутизировать по назначению (умно).",
  "Per-destination smart routing": "Умная маршрутизация по назначению",

  // ── Nodes screen: node cards, interfaces, adopt/restore, health, updates (js/screen-nodes.js) ─
  "Unknown server": "Неизвестный сервер",
  "this server isn't in the fleet.": "этого сервера нет во флоте.",
  "{ago} ago": "{ago} назад",
  "stale for {ago}": "молчит {ago}",
  "reporting": "на связи",
  "awaiting enroll": "ждёт подключения",
  "stale": "молчит",
  "Node connections": "Связи ноды",
  "Link up": "Связь есть",
  "Connecting…": "Подключение…",
  "Link down": "Связи нет",
  "Smart cascade: routes selected destinations out via {node}": "Умный каскад: выбранные направления идут через {node}",
  "smart cascade": "умный каскад",
  "Tunnel": "Туннель",
  "Carrying": "Несёт",
  "Listen": "Слушает",
  "Subnet": "Подсеть",
  // budget-ok: Panel heading on its own line
  "User interfaces": "Интерфейсы",
  "Interfaces": "Интерфейсы",
  "Turn-proxies": "Turn-прокси",
  "Turn proxies": "Turn-прокси",
  "Setup turn-proxy": "Поднять turn-прокси",
  "Create new interface": "Создать интерфейс",
  "Adopt": "Принять",
  // budget-ok: card button, row wraps
  "Restore": "Восстановить",
  "Recreate": "Пересоздать",
  "Create": "Создать",
  "Install": "Установить",
  "Restore server identity": "Вернуть идентичность сервера",
  // budget-ok: sheet-foot button, foot has a grow spacer
  "Recreate & rekey": "Пересоздать и сменить ключи",
  // budget-ok: sheet title, 620px wide
  "Recreate & rekey · {iface}": "Пересоздать и сменить ключи · {iface}",
  // budget-ok: card button in place of Restore
  "Restoring…": "Восстанавливаю…",
  "vCPU": "vCPU",
  "Being taken over — the node applies this on its next sync": "Принимается — нода применит это на следующей синхронизации",
  "Found at": "Найден в",
  "None": "Нет",
  "Fork": "Форк",
  "value|unknown": "неизвестно",
  "Ports": "Порты",
  // budget-ok: faint value in a card row, its own cell
  "set on adopt": "задаётся при приёме",
  "taking it over…": "принимаем…",
  "the node is tearing it down…": "нода сносит его…",
  "reading server…": "читаю сервер…",
  "No managed interfaces reported.": "Управляемых интерфейсов не найдено.",
  "This node isn't sending any data right now": "Эта нода сейчас не присылает данных",
  "This node hasn't reported in yet — its interfaces will show up here once it runs the installer and syncs.":
    "Нода ещё не отчиталась — её интерфейсы появятся здесь, как только она отработает установщик и синхронизируется.",
  "Lost the enrollment token or the install command? Rotate the node's token to generate a fresh install command.":
    "Потеряли токен подключения или команду установки? Смените токен ноды, чтобы получить свежую команду.",
  "Add your first entry server — you'll get a one-time command to run on it.":
    "Добавьте первый входной сервер — вы получите одноразовую команду для запуска на нём.",
  "All servers run {daemon}, which syncs to this panel over HTTPS — the node needs no inbound access.":
    "На всех серверах работает {daemon}, который синхронизируется с этой панелью по HTTPS — входящий доступ ноде не нужен.",

  // Tooltips on the node/interface cards — hover captions, no box to overflow.
  // budget-ok: hover caption
  "Recreate this node's missing interfaces with their original identities — node-rebuild recovery":
    "Пересоздать пропавшие интерфейсы этой ноды с их прежними идентичностями — восстановление после пересборки",
  // budget-ok: hover caption
  "No turn-proxy build for this node's architecture{arch} — only amd64 and arm64 are supported.":
    "Для архитектуры этой ноды{arch} нет сборки turn-прокси — поддерживаются только amd64 и arm64.",
  "Set up the node's first turn-proxy": "Поднять первый turn-прокси на ноде",
  "Setting it up on the node": "Настраиваем на ноде",
  "Drop this pending request": "Снять этот запрос",
  "Cancel this request": "Отменить этот запрос",
  "The node tears it down on its next sync": "Нода снесёт его на следующей синхронизации",
  "The node takes it over on its next sync": "Нода примет его на следующей синхронизации",
  "Taking it over — the node applies this on its next sync": "Принимаем — нода применит это на следующей синхронизации",
  "Adopt this interface — choose its type, keys and peers are kept": "Принять интерфейс — выберите тип; ключи и пиры сохранятся",
  "Adopt this WDTT server — its key and passwords are kept": "Принять этот сервер WDTT — его ключ и пароли сохранятся",
  "On the node, not managed by the panel": "Есть на ноде, но панелью не управляется",
  "Dismissed — the panel isn't managing it": "Скрыт — панель им не управляет",
  "This interface is gone from the node": "Этот интерфейс пропал с ноды",
  "This WDTT server is gone from the node": "Этот сервер WDTT пропал с ноды",
  // budget-ok: hover caption
  "Gone with no recoverable key — recreate fresh + rekey": "Пропал, ключ не восстановить — пересоздать заново и сменить ключи",
  // budget-ok: hover caption
  "Recreate this interface with its original identity — recovers every peer on it":
    "Пересоздать интерфейс с прежней идентичностью — вернёт всех его пиров",
  // budget-ok: hover caption
  "Recreate this interface with a NEW key and rekey every peer on it (clients re-import)":
    "Пересоздать интерфейс с НОВЫМ ключом и сменить ключи всем пирам (клиентам нужен повторный импорт)",
  // budget-ok: hover caption
  "Confirming it's really gone (a couple of minutes) before Restore is offered":
    "Убеждаемся, что он действительно пропал (пара минут), прежде чем предлагать восстановление",
  // budget-ok: hover caption
  "Confirming it's really gone (a couple of minutes) before Recreate is offered":
    "Убеждаемся, что он действительно пропал (пара минут), прежде чем предлагать пересоздание",
  // budget-ok: hover caption on a drag grip
  "Drag to reorder": "Перетащите, чтобы изменить порядок",
  "The node is converting between bare-metal and docker": "Нода переводится между bare-metal и docker",
  // budget-ok: hover caption
  "Server wiped — its identity is escrowed; open to Restore or Recreate fresh":
    "Сервер стёрт — его идентичность в хранилище; откройте, чтобы восстановить или пересоздать заново",
  "Exits directly from this node": "Выходит напрямую с этой ноды",
  // budget-ok: hover caption
  "Stopped by you — open to Start it": "Остановлен вами — откройте, чтобы запустить",
  "Interface down on the node": "Интерфейс не поднят на ноде",
  // budget-ok: hover caption
  "A setting was edited directly on the server — open to Adopt or Restore":
    "Настройку правили прямо на сервере — откройте, чтобы принять или вернуть",

  // The "this interface is gone" explanations. The verdict is coloured, so it rides in as {verdict}.
  "The node no longer reports interface {iface} (subnet {subnet}). {verdict}, so Restore recreates it cleanly — no client changes.":
    "Нода больше не сообщает об интерфейсе {iface} (подсеть {subnet}). {verdict}, поэтому восстановление пересоздаст его чисто — у клиентов ничего не меняется.",
  "The node no longer reports interface {iface} (subnet {subnet}). {verdict}, so Restore recreates it with a new key — clients re-import.":
    "Нода больше не сообщает об интерфейсе {iface} (подсеть {subnet}). {verdict}, поэтому восстановление пересоздаст его с новым ключом — клиентам нужен повторный импорт.",
  "Its original server key is recoverable": "Исходный ключ сервера восстановим",
  "Its original server key can't be recovered": "Исходный ключ сервера восстановить нельзя",
  "The node no longer reports {iface}, and {verdict} — there's nothing to restore. Recreate it with a new key; {count} get fresh configs to re-import.":
    "Нода больше не сообщает об {iface}, и {verdict} — восстанавливать нечего. Пересоздайте его с новым ключом; {count} получат свежие конфиги для импорта.",
  "its server key can't be recovered": "ключ его сервера восстановить нельзя",
  "The node no longer reports WDTT server {iface} (subnet {subnet}). {verdict}, so Restore brings it back unchanged — no user re-imports.":
    "Нода больше не сообщает о сервере WDTT {iface} (подсеть {subnet}). {verdict}, поэтому восстановление вернёт его без изменений — пользователям не нужен повторный импорт.",
  "Its identity is escrowed in your Encryption Vault": "Его идентичность депонирована в хранилище шифрования",
  "The node no longer reports WDTT server {iface} (subnet {subnet}). {verdict}, so it can only come back with a new key — every user re-imports.":
    "Нода больше не сообщает о сервере WDTT {iface} (подсеть {subnet}). {verdict}, поэтому вернуть его можно только с новым ключом — импорт понадобится всем пользователям.",
  "No escrowed identity is stored": "Депонированной идентичности нет",

  // Health card
  "Health": "Состояние",
  "CPU": "CPU",
  "CPU load": "Нагрузка CPU",
  "CPU history": "История CPU",
  "Memory": "Память",
  "Disk": "Диск",
  "No health data reported yet.": "Данных о состоянии пока нет.",

  // Updates
  "Update available": "Есть обновление",
  "Update available — open the node to update": "Есть обновление — откройте ноду, чтобы обновить",
  "Update available — v{ver}": "Есть обновление — v{ver}",
  "Update this master (panel + co-located node) to the latest release":
    "Обновить этот мастер (панель + локальная нода) до последнего релиза",
  "Update this node": "Обновить эту ноду",
  "update node to": "обновить ноду до",
  "This master is on the latest version": "На этом мастере последняя версия",
  "This node is on the latest version": "На этой ноде последняя версия",
  "A container or the datapath isn't running on this node — recreating it should fix it. ":
    "На этой ноде не работает контейнер или датапас — пересоздание должно помочь. ",
  "The AmneziaWG kernel module isn't built or loaded on this node — awg interfaces can't come up. ":
    "На этой ноде не собран или не загружен модуль ядра AmneziaWG — интерфейсы awg не поднимутся. ",
  // budget-ok: hover caption fragment, wraps
  "Re-run the updater to repair.": "Запустите обновление ещё раз, чтобы починить.",
  // budget-ok: hover caption fragment, wraps
  "Update this node to repair.": "Обновите эту ноду, чтобы починить.",
  "repair node": "починить ноду",
  // budget-ok: hover caption
  "Rotate token (re-enroll / re-install)": "Сменить токен (переподключение / переустановка)",
  // budget-ok: hover caption
  "Recover this node — rotate its token and get a fresh paste-on-the-server install command (the node keeps its peers)":
    "Восстановить ноду — сменить её токен и получить свежую команду установки для сервера (пиры сохранятся)",
  "Panel updated": "Панель обновлена",
  "Reload now": "Перезагрузить",
  "The panel was updated from {from} to {to}.": "Панель обновлена с {from} до {to}.",
  "To be sure every change takes effect, give the panel a hard reload — it drops the cached app so the new version loads cleanly.":
    "Чтобы все изменения точно применились, сделайте жёсткую перезагрузку — она сбросит кэш приложения и загрузит новую версию начисто.",
  "Press": "Нажмите",
  // budget-ok: sheet-foot button, foot has a grow spacer
  "Update now": "Обновить сейчас",
  "Update {name}": "Обновление {name}",
  "node's": "ноды",
  "panel's": "панели",
  // budget-ok: confirm sheet title
  "Update this server": "Обновление этого сервера",
  "For a {what} — including third-party components (docker / wg-awg / turn-proxies) — run this on the {side} box:":
    "Для {what} — включая сторонние компоненты (docker / wg-awg / turn-прокси) — выполните это на сервере {side}:",
  // budget-ok: bold run inside wrapping prose
  "full, controlled update": "полного управляемого обновления",
  "For an {what}, press {press} below. This also {repairs} the {side} box — reinstalls anything missing, re-enables services, and rebuilds the datapath (e.g. the AmneziaWG kernel module) — so it's worth running even when you're already up to date.":
    "Для {what} нажмите {press} ниже. Это также {repairs} сервер {side} — доустановит недостающее, включит службы и пересоберёт датапас (например, модуль ядра AmneziaWG) — так что запускать стоит, даже когда версия уже последняя.",
  // budget-ok: bold run inside wrapping prose
  "automatic update of SWG components only": "автоматического обновления только компонентов SWG",
  "repairs": "чинит",
  // budget-ok: toast, wraps
  "Update requested — applies on the node's next sync.": "Обновление запрошено — применится на следующей синхронизации ноды.",
  "Automatic update isn't wired on this install — run the command shown in the dialog on the host.":
    "Автообновление на этой установке не подключено — выполните на хосте команду из диалога.",
  "Update started — the panel will restart shortly.": "Обновление запущено — панель скоро перезапустится.",
  "Couldn't reach the repo to check for updates.": "Не удалось достучаться до репозитория за обновлениями.",
  "Loading changelog…": "Загружаю изменения…",
  "No changelog available.": "Список изменений недоступен.",
  // budget-ok: hover-bubble footer, wraps
  "Click to review & run the repair.": "Нажмите, чтобы посмотреть и запустить починку.",

  // ── create/edit sheets: peers, targets, nodes (js/sheets-crud.js) ──────────────────────────────
  "Create peer": "Создать пира",
  "Create node": "Создать ноду",
  "Create only": "Только создать",
  "Rotate": "Сменить",
  "Rotate link": "Сменить ссылку",
  "Rotate keys": "Сменить ключи",
  "Rotating link…": "Меняю ссылку…",
  "Rotating keys…": "Меняю ключи…",
  "Rotate subscription link": "Сменить ссылку подписки",
  "Disable": "Отключить",
  "Disable subscription": "Отключить подписку",
  // budget-ok: sheet-foot button, foot has a grow spacer
  "Reassign": "Переназначить",
  // budget-ok: confirm sheet title, 620px wide
  "Reassign peer": "Переназначить пира",
  // budget-ok: sheet-foot button, foot has a grow spacer
  "Generate recovery command": "Сгенерировать команду восстановления",
  "Log out": "Выйти",
  "Are you sure you want to logout?": "Точно выйти?",
  // budget-ok: confirm sheet title, 480px wide
  "Unlock to publish this config": "Откройте хранилище, чтобы опубликовать конфиг",
  // budget-ok: confirm sheet title, 480px wide
  "Unlock to update this subscription": "Откройте хранилище, чтобы обновить подписку",
  "Their peers are revoked and become unassigned.": "Их пиры отзываются и остаются без пользователя.",
  "Create a shareable link to this user's QR codes. New peers appear on it automatically; the unlock secret rides in the link and never reaches the server.":
    "Создать ссылку на QR этого пользователя, которой можно поделиться. Новые пиры появляются на ней сами; секрет для расшифровки едет в самой ссылке и никогда не попадает на сервер.",
  "A fresh access password is generated. The current WDTT link stops working — send the user their new link (from the subscription page) to re-import.":
    "Выпускается новый пароль доступа. Текущая ссылка WDTT перестанет работать — отправьте пользователю новую (со страницы подписки) для повторного импорта.",
  "A fresh keypair and preshared key are generated. The current config stops working — you'll need to send out the fresh QR / config to re-import. Useful if a config may have leaked.":
    "Выпускаются новая пара ключей и preshared-ключ. Текущий конфиг перестанет работать — придётся разослать свежий QR или конфиг для повторного импорта. Полезно, если конфиг мог утечь.",
  "Custom IP / Host…": "Свой IP / хост…",
  "Use custom…": "Задать своё…",
  "Subscription certificate": "Сертификат подписки",
  // budget-ok: sheet-foot button, foot has a grow spacer
  "Add peers ▸": "Добавить пиров ▸",
  "Alex": "Алексей",
  "Friend": "Друг",
  // budget-ok: <label> followed by a grow spacer
  "This user’s peers": "Пиры этого пользователя",
  "Create fresh peer": "Создать нового пира",
  "Backup": "Резерв",
  "Add or edit interface deployments": "Добавить или изменить развёртывания",
  "Turn-proxies on this interface": "Turn-прокси на этом интерфейсе",
  "No interfaces available — is a node online?": "Нет доступных интерфейсов — есть ли онлайн-нода?",
  "WDTT assigns the address on connect": "WDTT выдаёт адрес при подключении",
  "Client allowed IPs (routing)": "AllowedIPs клиента (маршрутизация)",
  "Persistent keepalive (s)": "Keepalive (с)",
  "0 disables · blank = 25.": "0 отключает · пусто = 25.",
  "WDTT user added — their connect link is on the assigned subscription.":
    "Пользователь WDTT добавлен — ссылка для подключения на его подписке.",
  // budget-ok: label suffix, wraps with the label
  "— optional, to tell devices apart": "— необязательно, чтобы различать устройства",
  "iPhone, Router, Laptop…": "iPhone, роутер, ноутбук…",
  "Targets": "Цели",
  "— one, or several for redundancy (same key)": "— одна или несколько для резерва (тот же ключ)",
  "— check to deploy, uncheck to remove": "— отметить = развернуть, снять = убрать",
  "WDTT server — the panel mints this user's access password and WDTT mints their WireGuard key + IP on connect, so there's no key or client config to set here. The user's VK link (from their subscription) is the TURN credential.":
    "Сервер WDTT — панель выпускает пароль доступа этого пользователя, а WDTT выдаёт ключ WireGuard и IP при подключении, поэтому здесь нечего задавать: ни ключа, ни клиентского конфига. Учётные данные TURN — это ссылка VK пользователя (с его подписки).",
  "Peer targets updated.": "Цели пира обновлены.",
  "Delete this peer?": "Удалить этого пира?",
  "Yes, delete": "Да, удалить",
  "Peer deleted.": "Пир удалён.",
  // budget-ok: sheet-foot button, foot has a grow spacer
  "Save changes": "Сохранить изменения",
  "Deploy": "Развернуть",
  "Panel address confirmed": "Адрес панели подтверждён",
  "This can't be undone.": "Отменить это нельзя.",
  "Remove this record — *{v1}{v2}*? This can't be undone.": "Удалить запись — *{v1}{v2}*? Отменить это нельзя.",
  "Delete *all {v1}* from the activity log? This can't be undone.": "Удалить из журнала *все {v1}*? Отменить это нельзя.",
  "loading config…": "загружаю конфиг…",
  "sheet|Peer": "Пир",
  "Peer not found": "Пир не найден",
  "It may have been removed.": "Возможно, его удалили.",
  "Edit": "Изменить",
  // budget-ok: disabled-button tooltip, no box
  "Fix or remove the problem interface first — see the note above":
    "Сначала исправьте или уберите проблемный интерфейс — см. заметку выше",
  "Recreate & rekey interface": "Пересоздать и сменить ключи",
  // budget-ok: button tooltip, no box
  "Recreate this interface with a NEW key and rekey every peer on it — clients re-import":
    "Пересоздать интерфейс с НОВЫМ ключом и сменить ключи всем его пирам — клиентам нужен повторный импорт",
  // budget-ok: button tooltip, no box
  "Recreate this missing interface with its original identity — recovers every peer on it":
    "Пересоздать пропавший интерфейс с прежней идентичностью — вернёт всех его пиров",
  // budget-ok: button tooltip, no box
  "Assign the next free in-subnet address ({ip} is out of range)":
    "Выдать следующий свободный адрес в подсети ({ip} вне диапазона)",
  "col|Interface": "Интерфейс",
  "Editing is off while a deployment sits on a missing or misconfigured interface. A peer edit (keys, AmneziaWG params, DNS, address) applies to every deployment, so it would leave this peer inconsistent. To edit it, either Restore / Fix the interface above, or open Targets and remove that interface from this peer.":
    "Редактирование выключено, пока развёртывание сидит на пропавшем или неверно настроенном интерфейсе. Правка пира (ключи, параметры AmneziaWG, DNS, адрес) применяется ко всем развёртываниям и оставила бы пира несогласованным. Чтобы изменить его, восстановите или исправьте интерфейс выше либо откройте «Цели» и уберите этот интерфейс у пира.",
  // budget-ok: label suffix, wraps with the label
  "— optional": "— необязательно",
  // budget-ok: input placeholder in a 620px sheet
  "e.g. iPhone, Work laptop": "например iPhone, рабочий ноутбук",
  "— this peer only; blank = {fallback}": "— только этот пир; пусто = {fallback}",
  "follows the subscription": "как у подписки",
  "never": "никогда",
  "Servers": "Серверы",
  "WDTT servers this user reaches. WDTT assigns each server's address on connect; the user's link per server is on their subscription. No client config (key/DNS/MTU) — WDTT owns the datapath.":
    "Серверы WDTT, до которых достаёт этот пользователь. WDTT выдаёт адрес на каждом сервере при подключении; ссылка на каждый сервер — на подписке пользователя. Клиентского конфига (ключ/DNS/MTU) нет — датапас у WDTT.",
  "Addresses": "Адреса",
  "Changing an address moves the peer on that interface.": "Смена адреса переносит пира на этом интерфейсе.",

  // Node create / recover / remove
  "Node colour": "Цвет ноды",
  "Done": "Готово",
  // budget-ok: bold lead-in inside a notice, wraps
  "Shown once.": "Показывается один раз.",
  "This token authenticates the node to the panel — copy it now. You can rotate it later if it leaks.":
    "Этот токен подтверждает ноду перед панелью — скопируйте его сейчас. Позже его можно сменить, если он утечёт.",
  "Enrollment token": "Токен подключения",
  // budget-ok: toast, wraps
  "Copied": "Скопировано",
  "Run on the node —": "Выполните на ноде —",
  "Pick one. Both fetch the installer and prompt for the node's endpoint.":
    "Выберите любой. Оба скачивают установщик и спросят эндпоинт ноды.",
  "This recovers {name} as {method} — the method it was already running, so its turn-proxies and interfaces are kept. To switch methods, convert the node instead.":
    "Восстановит {name} как {method} — тем же способом, которым нода уже работала, так что её turn-прокси и интерфейсы сохранятся. Чтобы сменить способ, переведите ноду.",
  "Re-provision this node's mesh links?": "Перевыпустить меш-линки этой ноды?",
  "Re-provision": "Перевыпустить",
  "Rotate key": "Сменить ключ",
  // budget-ok: button tooltip, no box
  "Rotate this node's enrollment token (re-enroll / re-install)":
    "Сменить токен подключения этой ноды (переподключение / переустановка)",
  // budget-ok: section label on its own line
  "Egress": "Исходящий трафик",
  // budget-ok: field <label> on its own line
  "Default egress IP": "IP по умолчанию для выхода",
  "— direct internet exit": "— прямой выход в интернет",
  "The fallback source IP this node SNATs to when traffic exits to the internet here — applied to any interface (and traffic received from other nodes) that doesn't set its own egress IP. Interfaces with their own egress IP, and cascading traffic that exits elsewhere, are unaffected.":
    "С этого IP нода выходит в интернет по умолчанию. Он применяется там, где свой IP выхода не задан — к любому интерфейсу этой ноды и к трафику, пришедшему с других нод. Если у интерфейса задан свой IP выхода, используется он. Трафик, который уходит в интернет через другую ноду, это не затрагивает.",
  "Panel egress connection IP": "IP для связи с панелью",
  "— source to reach the panel": "— источник для доступа к панели",
  "Source IP this node uses to reach the panel. Ignored on same-server installs; falls back to auto if it can't connect.":
    "Адрес источника, с которого нода обращается к панели. На установках на одном сервере игнорируется; при неудаче — авто.",
  "Mesh settings (ingress IP, subnet, port, prefix, AWG) for this node are configured in {where} — select this node there.":
    "Настройки меша (входящий IP, подсеть, порт, префикс, AWG) для этой ноды задаются в {where} — выберите там эту ноду.",
  "Panel settings → Mesh & egress": "Настройки панели ▸ Меш и выходы",
  "This node isn't reporting. Generating a recovery command rotates its token and gives you a one-line command to paste on the server — it re-installs/recovers {name} as the {same}, so its interfaces and peers come straight back (no need to find the old token).":
    "Нода не отчитывается. Генерация команды восстановления сменит её токен и выдаст однострочную команду для сервера — она переустановит и восстановит {name} как {same}, так что интерфейсы и пиры вернутся сразу (искать старый токен не нужно).",
  "same node": "ту же ноду",
  "The node's current token stops working immediately — use this only when the node is genuinely down or you've lost its install command.":
    "Текущий токен ноды перестанет работать сразу — делайте это, только если нода действительно недоступна или команда установки потеряна.",
  "The current token stops working immediately. Re-enroll the node with the new token or it will go offline.":
    "Текущий токен перестанет работать сразу. Переподключите ноду с новым токеном, иначе она уйдёт в офлайн.",
  "This cuts {name} off {now} without waiting for it to confirm — {dropped}. Use this only when the server is unreachable. This can't be undone.":
    "Отрежет {name} {now}, не дожидаясь подтверждения — {dropped}. Делайте это, только если сервер недоступен. Отменить нельзя.",
  "immediately": "немедленно",
  "{n} that live only here are dropped": "{n} только здесь — будут отброшены",
  // budget-ok: inside notice prose, wraps
  "peers that live only here are dropped": "пиры, которые есть только здесь, будут отброшены",
  "Type {phrase} to confirm": "Подтвердите вводом {phrase}",
  "{flagged} Run the command below on the node — it'll sign off and disappear here automatically. If you've lost access to the server, use {force} to cut it off.":
    "{flagged} Выполните команду ниже на ноде — она отпишется и исчезнет отсюда сама. Если доступа к серверу нет, воспользуйтесь {force}.",
  "Flagged for removal.": "Помечена на удаление.",
  // budget-ok: sheet-foot button, foot has a grow spacer
  "Force remove now": "Удалить принудительно",
  "Run on the node to uninstall + sign off": "Выполните на ноде, чтобы удалить и отписаться",

  // ── peer view, QR carousel, subscriptions, VK links (js/peer-ui.js) ────────────────────────────
  // "Subscription" here is the panel's shareable per-user QR page, not a paid plan — «подписка» carries that
  // in Russian too, and the sub page itself already uses the word.
  "Previous": "Назад",
  "Unlock the Encryption Vault to see configs, QR codes and the subscription link.":
    "Откройте хранилище шифрования, чтобы увидеть конфиги, QR и ссылку на подписку.",
  "Trust this device and keep it unlocked": "Доверять этому устройству и не запирать",
  "Settings → Subscriptions": "Настройки → Подписки",
  "No subscription link yet — enable one to share this user's QRs.":
    "Ссылки на подписку ещё нет — включите её, чтобы делиться QR этого пользователя.",
  "Enable subscription": "Включить подписку",
  "Subscription link": "Ссылка на подписку",
  "— this user's shareable QR page": "— страница с QR этого пользователя",
  "Building link…": "Собираем ссылку…",
  "Rotate token": "Сменить токен",
  // budget-ok: subscription row button, row wraps
  "Disable URL": "Отключить ссылку",
  "Open this peer's configs": "Открыть конфиги этого пира",
  // budget-ok: icon-button tooltip, no box
  "Copy subscription link": "Скопировать ссылку на подписку",
  // budget-ok: empty-state block, wraps
  "This user has no peers yet.": "У этого пользователя пока нет пиров.",

  // VK call links — the room a turn proxy pulls TURN credentials from. "VK" stays as-is.
  // budget-ok: field <label>, its own line
  "VK call link": "Ссылка на звонок VK",
  // budget-ok: field-label suffix, wraps with the label
  "— for this user's configs that ride a VK call": "— для конфигов этого пользователя, которые идут через звонок VK",
  "Saved": "Сохранено",
  "Failed": "Ошибка",
  "Manage": "Править",
  // budget-ok: button tooltip, no box
  "Manage all of this user's VK call links (add more, set primary)":
    "Управление всеми ссылками VK этого пользователя (добавить, назначить основную)",
  "Expected a VK call link like": "Ожидается ссылка на звонок VK вида",
  // budget-ok: hint line above a mono example, wraps
  "Every link must look like": "Каждая ссылка должна выглядеть как",
  "One of the links isn't a valid VK call link.": "Одна из ссылок не похожа на ссылку звонка VK.",
  // budget-ok: sheet-foot button, foot has a grow spacer
  "Add link": "Добавить ссылку",
  "Set as the primary link": "Сделать основной",
  "Remove this link": "Удалить ссылку",
  "Each link is a VK call room the user's turn proxy pulls TURN credentials from. Mark one {primary} — apps that take a single link use it; some proxies use all of them (more links = more capacity).":
    "Каждая ссылка — комната звонка VK, из которой turn-прокси пользователя берёт учётные данные TURN. Отметьте одну как {primary} — приложения, которым нужна одна ссылка, возьмут её; некоторые прокси используют все (больше ссылок — больше ёмкость).",
  "primary": "основную",
  "No VK links for this user yet — panel is using your {test} link to build turn configs. Fix before distributing.":
    "У пользователя пока нет ссылок VK — панель собирает turn-конфиги с вашей {test} ссылкой. Исправьте до раздачи.",
  "test": "тестовой",
  "Right now their subscription page will show the turn configs {without} a VK link, so they'd have to add one in their turn app.":
    "Сейчас на странице подписки turn-конфиги будут {without} ссылки VK — её придётся добавить прямо в turn-приложении.",
  "without": "без",
  "No VK call link set — configs carry a placeholder. Set it in {where}.":
    "Ссылка на звонок VK не задана — в конфигах стоит заглушка. Задайте её в {where}.",
  "Panel settings → Turn proxies": "Настройки панели → Turn-прокси",
  "No VK call link on this user — the link won't authenticate until one is set.":
    "У пользователя нет ссылки на звонок VK — ссылка не пройдёт авторизацию, пока её не зададут.",

  // Encryption key sheet
  "Save your encryption key": "Сохраните ключ шифрования",
  "I've saved it": "Я сохранил",
  "Config encryption is on. This key protects every stored client config and subscription link — the panel only ever stores it wrapped under your password, so {only}.":
    "Шифрование конфигов включено. Этот ключ защищает все сохранённые конфиги клиентов и ссылки на подписки — панель хранит его только запечатанным под вашим паролем, поэтому {only}.",
  "this is the only copy in the clear": "это единственная копия в открытом виде",
  "Store it in a password manager. It's what gets you back to your configs if your panel password is ever reset from the server — and anyone who holds it can read them, so treat it like a password. You can see it again any time from {where} while the vault is unlocked.":
    "Храните его в менеджере паролей. Именно он вернёт вам доступ к конфигам, если пароль панели сбросят с сервера, — и любой, у кого он есть, сможет их прочитать, так что относитесь к нему как к паролю. Посмотреть его снова можно в {where}, пока хранилище открыто.",
  "Settings → Client configs": "Настройки → Конфиги клиентов",
  "Encryption key copied": "Ключ шифрования скопирован",
  "Download": "Скачать",
  "Download .txt": "Скачать .txt",

  // Peer / user edit + the config cards
  "Name": "Имя",
  "Tag": "Тег",
  "Friend, Family, Work…": "Друг, Семья, Работа…",
  "Note": "Заметка",
  "Uses iPhone and router": "iPhone и роутер",
  "Access expires": "Доступ истекает",
  "— the whole subscription; blank = never": "— вся подписка; пусто = никогда",
  "On this date the subscription and all its peers stop working (they reappear if you extend it). A peer's own expiry can't be later than this.":
    "В эту дату подписка и все её пиры перестают работать (и вернутся, если продлить). Срок отдельного пира не может быть позже.",
  "Name can't be empty.": "Имя не может быть пустым.",
  "Subscription expiry can't be earlier than a peer's expiry ({date}).":
    "Срок действия подписки не может быть раньше срока действия пира ({date}).",
  "Clear": "Очистить",
  "Reset expiry": "Сбросить срок",
  "Set expiry": "Срок действия",
  // budget-ok: sheet-foot button, foot has a grow spacer
  // Five buttons share one flex row in the user-edit footer. With the literal «Удалить пользователя» the row
  // overflowed by 158px; the card is already the user's, so the noun is redundant. Measured after the change.
  "Delete user": "Удалить",
  // budget-ok: sheet-foot button, foot has a grow spacer
  "Save": "Сохранить",
  "Saving…": "Сохраняю…",
  // budget-ok: sheet-foot button, foot has a grow spacer
  "Add": "Добавить",
  "Adding…": "Добавляю…",
  "Add webhook": "Добавить вебхук",
  "Edit webhook": "Изменить вебхук",
  // budget-ok: confirm sheet title, 620px wide
  "Save settings": "Сохранить настройки",
  "Enable": "Включить",
  "Set": "Сделать",
  "Make primary": "Сделать основной",
  // The doughnut ring labels are traffic DIRECTIONS, not the "Download" button in the vault sheet.
  "traffic|Download": "Приём",
  "traffic|Upload": "Отдача",
  // budget-ok: confirm sheet title, 620px wide
  "Delete user · {name}": "Удалить пользователя · {name}",
  // budget-ok: button tooltip, no box
  "Rotate the keys of every peer this user holds — all configs/links must be re-imported":
    "Сменить ключи у всех пиров этого пользователя — все конфиги и ссылки придётся импортировать заново",
  "No turn-proxy forwards to this interface.": "Ни один turn-прокси не ведёт на этот интерфейс.",
  "Device": "Устройство",
  // .turncfg-os and .turncfg-app are flex rows at opposite ends of ONE line (margin-left:auto), so both
  // labels share the width. The panel already calls these "client apps" — «Клиент» is accurate and fits.
  "App": "Клиент",
  "Config": "Конфиг",
  "Turn": "Turn",
  "Generate turn-proxy client configs": "Собрать клиентские конфиги turn-прокси",
  // budget-ok: icon-button tooltip, no box
  "Copy command": "Скопировать команду",
  // budget-ok: icon-button tooltip, no box
  "Copy link": "Скопировать ссылку",
  "QR image": "Картинка QR",
  // budget-ok: toast, wraps
  "Link copied": "Ссылка скопирована",
  "Config copied": "Конфиг скопирован",
  // budget-ok: toast, wraps
  "WDTT link copied": "Ссылка WDTT скопирована",
  // budget-ok: toast, wraps
  "Wrap key copied": "Ключ обёртки скопирован",
  // budget-ok: icon-button tooltip, no box
  "Copy wrap key": "Скопировать ключ обёртки",
  "· key": "· ключ",
  "Primary": "Основной",
  "Alternatives": "Другие варианты",
  "No client app for this device.": "Для этого устройства нет клиента.",
  "WDTT link unavailable — the server isn't reporting yet.": "Ссылка WDTT недоступна — сервер ещё не отчитался.",
  "WDTT · keyless (server-minted key)": "WDTT · без ключа (ключ выдаёт сервер)",
  "— assigned on first connect": "— выдаётся при первом подключении",

  // ── Overview dashboard (js/screen-overview.js) ─────────────────────────────────────────────────
  // Section titles are terse noun phrases, matching the English. The subtitle beside each is lowercase.
  "Fleet": "Флот",
  "Fleet throughput": "Трафик флота",
  "Distribution": "Распределение",
  "Traffic flow map": "Карта потоков",
  "Top nodes by peers": "Ноды по числу пиров",
  "Top nodes by traffic": "Ноды по трафику",
  "Top talkers": "Самые активные",
  "Top destinations": "Куда идёт трафик",
  "Recent activity": "Последние действия",
  "Needs attention": "Требует внимания",
  "Protection": "Защита",
  "Online now": "Сейчас онлайн",
  "Sync": "Синхр.",
  "{n} of {total}": "{n} из {total}",
  "{n} alerting": "{n} с тревогой",
  "live connections →": "активные соединения →",
  "assigned · unassigned": "назначенных · свободных",
  "selected nodes": "выбранные ноды",
  "whole fleet": "весь флот",
  "signal flow · by category": "поток трафика · по категориям",
  "total peers": "всего пиров",
  "online now": "сейчас онлайн",
  "online · {range}": "онлайн · {range}",
  "{range} · by volume": "{range} · по объёму",
  "by live throughput": "по текущей скорости",
  "categories overlap": "категории пересекаются",
  "of {dn} and {up} total": "из {dn} и {up} всего",
  "what blocking caught & is filtering": "что поймала и фильтрует блокировка",
  "Who": "Кто",
  "latest first": "сначала свежие",
  "Prev": "Назад",
  "Next": "Дальше",
  "Show all history »": "Вся история »",
  "Everything's deployed and reporting. No drift across the fleet.":
    "Всё развёрнуто и отчитывается. Расхождений по флоту нет.",
  "gathering — no history yet": "собираем — истории пока нет",
  // budget-ok: empty state inside the chart area, its own block
  "gathering — fills as it polls": "собираем — заполнится по мере опросов",
  "No servers configured in fleet.json.": "В fleet.json не настроено ни одного сервера.",
  "No nodes selected.": "Ноды не выбраны.",
  "No nodes yet": "Нод пока нет",
  "Add your first entry server to start deploying peers. The panel stays the source of truth — each node syncs to it over outbound HTTPS.":
    "Добавьте первый входной сервер, чтобы начать разворачивать пиров. Панель остаётся источником истины — каждая нода синхронизируется с ней по исходящему HTTPS.",
  // budget-ok: sheet title and a toolbar button, both size to content
  "Add node": "Добавить ноду",
  "Traffic by node": "Трафик по нодам",
  "Deployments by node": "Подключения по нодам",
  "Traffic by interface": "Трафик по интерфейсам",
  "Deployments by interface": "Подключения по интерфейсам",
  "Traffic by turn-proxy": "Трафик по turn-прокси",
  "Deployments by turn-proxy": "Подключения по turn-прокси",
  "↓ ingress": "↓ входящий",
  "↑ egress": "↑ исходящий",
  "Flow animation (saved for everyone)": "Анимация потока (сохраняется для всех)",
  "Silence": "Заглушить",
  // budget-ok: sheet-foot button, foot has a grow spacer
  "Run update": "Запустить обновление",
  "“Run update” reinstalls anything missing and re-enables the service — the same repair the Update button runs. A service that keeps crashing needs the logs above.":
    "«Запустить обновление» доустановит недостающее и включит службу — то же самое делает кнопка обновления. Если служба падает снова и снова, смотрите логи выше.",

  // The dashboard rail's jump menu. Its labels are shorter than the section headings they jump to — the rail
  // is a narrow collapsed strip that slides its labels out on hover.
  "nav|Fleet": "Флот",
  "nav|Distribution": "Распределение",
  "nav|Traffic flow": "Потоки",
  "nav|Top charts": "Топ-графики",
  "nav|Activity log": "Журнал",

  // Dashboard range picker. Two cases because the panel uses both: capitalised on the rail buttons,
  // lowercase inside a section subtitle.
  "range|Live": "Сейчас",
  "range|Hour": "Час",
  "range|Day": "Сутки",
  "range|Week": "Неделя",
  "range|Month": "Месяц",
  "range|live": "сейчас",
  "range|hour": "за час",
  "range|day": "за сутки",
  "range|week": "за неделю",
  "range|month": "за месяц",

  // ── Peers / Users / Live / Activity screens (js/screen-roster.js) ──────────────────────────────
  // Section headings are plain nouns; the panel's nav already says where you are, so they stay terse.
  "Peers": "Пиры",
  "Peers on": "Пиры на",
  // budget-ok: measured — Overview stat cards are a fixed 235px and the label does not clip
  "Users": "Пользователи",
  "Overview": "Обзор",
  "Activity history": "История действий",
  "Unmanaged here": "Не под управлением",
  // budget-ok: section <h2>, its own line
  "Unassigned peers": "Пиры без пользователя",
  // budget-ok: measured — same 553px search box
  "Search title, user, address…": "Поиск по имени, пользователю, адресу…",
  // budget-ok: measured — 368px in a 553px search box
  "Search users, tags, notes, peers…": "Поиск по пользователям, тегам, заметкам, пирам…",
  // budget-ok: measured — same 553px search box
  "Search users, tags, peers…": "Поиск по пользователям, тегам, пирам…",
  // budget-ok: measured — same 553px search box
  "Search peer, user, endpoint, IP…": "Поиск по пиру, пользователю, эндпоинту, IP…",
  "Search action, name, detail…": "Поиск по действию, имени, деталям…",
  // budget-ok: measured — 191px button in a 1216px toolbar with a grow spacer, no overflow
  "New user": "Новый пользователь",
  // budget-ok: icon-button tooltip, no box
  "Edit user": "Изменить пользователя",
  // budget-ok: icon-button tooltip, no box
  "Add peer": "Добавить пира",
  "Delete entry": "Удалить запись",
  "Restore all dangling": "Восстановить потерянные",
  "Fix all broken": "Исправить неверные",
  // budget-ok: hover caption on a toolbar button, no box
  "Recreate every missing interface shown here with its original identity":
    "Пересоздать каждый показанный здесь пропавший интерфейс с его исходной идентичностью",
  // budget-ok: hover caption on a toolbar button, no box
  "Assign each broken peer shown here the next free in-subnet address":
    "Выдать каждому показанному здесь неверному пиру следующий свободный адрес в подсети",
  // budget-ok: button tooltip, no box
  "Show only online connections": "Показывать только активные соединения",
  "{n} shown · {online} online": "показано {n} · онлайн {online}",
  "Never": "Никогда",
  // budget-ok: empty-state block, wraps
  "No peers match.": "Нет подходящих пиров.",
  "No peers yet — {add}.": "Пиров пока нет — {add}.",
  "add one": "добавьте",
  // budget-ok: empty-state block, wraps
  "No users yet": "Пользователей пока нет",
  "Create a user, then mint peers for them — or create a peer and assign it later.":
    "Создайте пользователя и выпустите ему пиров — или создайте пира и назначьте его позже.",
  "Nothing matches": "Ничего не подходит",
  "Clear the search.": "Очистите поиск.",
  "Clear the filters.": "Сбросьте фильтры.",
  "Clear all activity?": "Очистить всю историю?",
  // budget-ok: empty-state block, wraps
  "No users online": "Нет пользователей онлайн",
  "No user has an online peer right now.": "Сейчас ни у кого нет активных пиров.",
  "No connections online": "Нет активных соединений",
  "No peer is online with these filters.": "С этими фильтрами нет активных пиров.",
  // budget-ok: button tooltip, no box
  "Hide client (peer) traffic": "Скрыть клиентский трафик (пиры)",
  // budget-ok: button tooltip, no box
  "Show client (peer) traffic": "Показать клиентский трафик (пиры)",
  "All actions": "Все действия",
  "Clear history": "Очистить историю",
  "Loading…": "Загрузка…",
  "No activity yet": "Действий пока нет",
  "Operator actions across the panel will show up here.": "Здесь появятся действия оператора по всей панели.",
  "Try a different search or filter.": "Попробуйте другой запрос или фильтр.",
  // Activity feed action labels — past-tense neuter, agreeing with the implied «действие»
  "event|Added": "Добавлено",
  "event|Changed": "Изменено",
  "event|Removed": "Удалено",

  // ── app shell: address move, update pill, login (app.js) ───────────────────────────────────────
  "Move cancelled — the panel stays on this address.": "Переезд отменён — панель остаётся на этом адресе.",
  "Couldn't cancel the move.": "Не удалось отменить переезд.",
  "You're on a previous panel address.": "Вы на прежнем адресе панели.",
  "The panel is now reached at {addr}.": "Теперь панель доступна по адресу {addr}.",
  "Cancel the move — keep this address": "Отменить переезд — оставить этот адрес",
  "Go to the current address ↗": "Перейти на текущий адрес ↗",
  "New address confirmed": "Новый адрес подтверждён",
  "Got it": "Понятно",
  "This is now the address the panel is reached at, and you're signed in here. You can close the other tab — it's on the previous address.":
    "Теперь панель доступна по этому адресу, и вы здесь авторизованы. Прежнюю вкладку можно закрыть — она на старом адресе.",
  "Couldn’t confirm the new address": "Не удалось подтвердить новый адрес",
  "OK": "ОК",
  "The confirmation didn’t match a pending change.": "Подтверждение не совпало ни с одним ожидающим изменением.",
  " The panel kept its current address.": " Панель осталась на текущем адресе.",

  // The update pill is a narrow slot in the header — these stay as short as the English.
  "Changelog": "Изменения",
  "repairing": "починка",
  "repaired": "починено",
  // budget-ok: measured — 97px -> 111px in the header slot
  "repair failed": "починка не удалась",
  "Dismiss": "Скрыть",
  "repairing…": "починка…",
  "updating…": "обновление…",
  "checking…": "проверка…",
  "update to": "обновить до",
  // budget-ok: MEASURED in the header slot — the pill goes 131px -> 191px and the header absorbs it at a
  // normal width (no overflow). Below ~1000px the header overflows in ENGLISH too (222px at 900px), so the
  // narrow-width problem is the header's own, not this string's; kept correct rather than trimmed for it.
  "fix {count}": "исправить {count}",
  // budget-ok: hover caption, no box
  "On the latest version — click to re-run the updater anyway (repairs this box: reinstalls missing pieces, re-enables services, rebuilds the datapath / AmneziaWG kernel module)":
    "Версия последняя — нажмите, чтобы всё равно запустить обновление (чинит этот сервер: доустанавливает недостающее, включает службы, пересобирает датапас / модуль ядра AmneziaWG)",
  // budget-ok: hover caption on an icon button, no box
  "Check status": "Проверить состояние",

  // ── sign-in and vault reconnect (app.js) ───────────────────────────────────────────────────────
  // The heading is a NOUN, the button an IMPERATIVE — English reuses one word for both, Russian shouldn't.
  "Sign in": "Вход",
  "button|Sign in": "Войти",
  "Signing in…": "Вхожу…",
  "Username": "Логин",
  "Password": "Пароль",
  "Login failed.": "Не удалось войти.",
  "Couldn't reach the panel.": "Панель недоступна.",
  "Can't reach the panel": "Панель недоступна",
  "Two-factor": "Второй фактор",
  "Enter the 6-digit code from your authenticator app, or a recovery code.":
    "Введите 6-значный код из приложения-аутентификатора или код восстановления.",
  "Authentication code": "Код подтверждения",
  // budget-ok: sheet-foot button, foot has a grow spacer
  "Verify": "Подтвердить",
  // budget-ok: sheet-foot button, foot has a grow spacer
  "Verify & enable": "Подтвердить и включить",
  "Verifying…": "Проверяю…",
  // budget-ok: login-card <h2>, full width
  "Reconnect your vault": "Подключите хранилище заново",
  // swg-passwd is a command name and stays monospace and untranslated; "untouched" is the bold reassurance.
  "Your password was changed with {cmd}, which runs on the server and can't reach your encryption key. Your stored configs, QR codes and subscription links are {safe} — the vault just needs reconnecting.":
    "Пароль был изменён командой {cmd}, которая работает на сервере и не может добраться до вашего ключа шифрования. Сохранённые конфиги, QR и ссылки на подписки {safe} — хранилище нужно просто подключить заново.",
  "untouched": "не пострадали",
  "Old panel password, or your encryption key": "Старый пароль панели или ваш ключ шифрования",
  "Password or encryption key": "Пароль или ключ шифрования",
  "The encryption key is the one shown when this panel set up encryption — you were asked to save it.":
    "Ключ шифрования — это тот, что панель показала при настройке шифрования и просила сохранить.",
  // budget-ok: login-card button, width:100%
  "Reconnect vault": "Подключить хранилище",
  "Reconnecting…": "Подключаю…",
  "Skip for now": "Пока пропустить",
  "That didn't unlock the Encryption Vault.": "Это не открыло хранилище шифрования.",
  // budget-ok: toast, wraps
  "Encryption Vault reconnected.": "Хранилище шифрования подключено заново.",

  // ── encryption vault + QR (js/crypto.js) ───────────────────────────────────────────────────────
  // "Encryption Vault" is a product concept the panel names in its own Settings, so it keeps a consistent
  // Russian name — «Хранилище шифрования» — everywhere it appears rather than being paraphrased per screen.
  "Subscribed users need nothing": "Подписчикам ничего не нужно",
  " — their subscription page serves the corrected config automatically; only manually-shared QR codes / configs need re-distributing.":
    " — их страница подписки сама отдаёт исправленный конфиг; раздать заново нужно только QR и конфиги, отправленные вручную.",
  // budget-ok: toast, wraps
  "Encryption Vault locked on this device.": "Хранилище шифрования заблокировано на этом устройстве.",
  "No Encryption Vault is set up yet — set one up in {where}, then try again.":
    "Хранилище шифрования ещё не настроено — настройте его в {where} и повторите.",
  "Settings → Client configs → Encryption": "Настройки → Конфиги клиентов → Шифрование",
  // The QR failure text sits inside the QR square itself — two short lines, so both stay short.
  "config too large": "конфиг слишком",
  "to encode as QR": "большой для QR",
  "config too large to encode": "конфиг слишком большой для QR",
  // budget-ok: hover caption, no box
  "Tap to enlarge for scanning": "Нажмите, чтобы увеличить для сканирования",
  "config QR": "QR конфига",
  // budget-ok: QR overlay caption, centred under a 920px image
  "Scan in WireGuard / AmneziaWG": "Отсканируйте в WireGuard / AmneziaWG",
  // budget-ok: toast, wraps
  "QR too large to copy as an image.": "QR слишком большой, чтобы скопировать картинкой.",
  // budget-ok: toast, wraps
  "This browser can't copy an image.": "Этот браузер не умеет копировать картинки.",
  "{what} copied.": "{what} скопирован.",
  // budget-ok: toast, wraps
  "Copy failed.": "Не удалось скопировать.",
  "That password didn’t unlock the Encryption Vault.": "Этот пароль не открыл хранилище шифрования.",
  "Enter your password to continue": "Введите пароль, чтобы продолжить",
  // budget-ok: sheet-foot button, foot has a grow spacer
  // budget-ok: sheet-foot buttons — the foot has a grow spacer, so they widen into slack
  "Skip": "Пропустить",
  "Unlocking…": "Открываю…",
  // budget-ok: sheet-foot button, sits beside Skip
  "Unlock vault": "Открыть хранилище",
  // budget-ok: sheet-foot button, measured against Skip
  "Unlock": "Открыть",
  "This action needs your Encryption Vault, which isn’t unlocked in this session.":
    "Для этого действия нужно хранилище шифрования, а в этой сессии оно не открыто.",
  "Panel password": "Пароль панели",
  "Keep this device unlocked": "Не запирать на этом устройстве",
  "Stay unlocked across restarts on this device — the key is stored only here, never sent to the server.":
    "Оставаться открытым после перезапусков на этом устройстве — ключ хранится только здесь и никогда не уходит на сервер.",
  "If you skip:": "Если пропустить:",
  "the action completes, but anything that needed the key won’t be saved.":
    "действие выполнится, но всё, чему нужен был ключ, не сохранится.",
  // budget-ok: grid empty state, its own block
  "No matches": "Ничего не найдено",
  "No peers here": "Здесь нет пиров",
  "Try a different search.": "Попробуйте другой запрос.",
  "Create one, or copy an existing peer onto this interface.": "Создайте пира или скопируйте существующего на этот интерфейс.",
  "No peers deployed yet.": "Пиров пока нет.",

  // ── Settings: addresses, TLS, encryption, routing lists, turn, subscriptions, 2FA ──
  "The panel POSTs a signed JSON body to your endpoint when a peer is added/removed or a node goes online/offline. Use them for alerting or automation.":
    "Панель шлёт на ваш адрес подписанный JSON, когда пира добавили или убрали и когда нода ушла в офлайн. Годится для оповещений и автоматизации.",
  "Internal port {old} → {new} — point your proxy's upstream at {addr} (co-located loopback nodes follow automatically).":
    "Внутренний порт {old} → {new} — укажите в proxy_pass {addr} (нода на этой же машине перейдёт сама).",
  "Public address {old} → {new} — {what} (copy the *panel* nginx sample below), keeping the old one live for now.":
    "Публичный адрес {old} → {new} — {what} (образец для *панели* — ниже), старый пока не выключайте.",
  "add a location for the new path {v1}": "добавьте location для нового пути {v1}",
  "the new path": "новый путь",
  "route {v1} to this panel": "направьте {v1} на эту панель",
  "Opening the new address to confirm your proxy routes it here — if it loads, the switch completes and nodes move over.":
    "Открываем новый адрес, чтобы убедиться, что прокси ведёт сюда: если страница откроется, переключение завершится и ноды перейдут.",
  "Confirm — open the new address ↗": "Подтвердить — открыть новый адрес ↗",
  "*Confirm the address change.* The nodes are now told to *also* try `{v1}`, so they're already connected there before the restart. When you Confirm, the panel first *dry-runs* the new settings in a throwaway container (issues the certificate, checks the port), and only then restarts onto the new address. If it can't be reached afterwards, it *rolls back automatically*.":
    "*Подтвердите смену адреса.* Нодам уже сказано пробовать *ещё и* `{v1}`, так что они там на связи до перезапуска. По кнопке панель сначала делает *пробный прогон* новых настроек в одноразовом контейнере (выпускает сертификат, проверяет порт) и только потом перезапускается на новый адрес. Если он не отзовётся, всё *откатится само*.",
  "New internal port `{v1}` — after Confirm, point your reverse proxy's upstream at it and reload the proxy.":
    "Новый внутренний порт `{v1}` — после подтверждения укажите его в proxy_pass и перечитайте конфиг.",
  "New address `{v1}` — make sure DNS / your firewall / Cloudflare route it to this panel.":
    "Новый адрес `{v1}` — проверьте, что DNS, файрвол и Cloudflare ведут его на эту панель.",
  "Dry-run failed.": "Проверка не прошла.",
  "*Restarting onto internal port {v1}.* Point your reverse proxy's upstream at `127.0.0.1:{v1}` and reload the proxy — this page comes back once it routes there. It confirms itself when reachable; if it stays unreachable it rolls back to the current port automatically.":
    "*Перезапуск на внутренний порт {v1}.* Укажите в proxy_pass `127.0.0.1:{v1}` и перечитайте конфиг — страница вернётся, как только прокси туда пойдёт. Доступность подтвердится сама; если её не будет, порт откатится обратно.",
  "Reload this page ↻": "Обновить страницу ↻",
  "*Restarting the panel container.* Reconnect at the new address once it's back — it confirms itself when you reach it. If the new address can't be reached (or the certificate can't be issued), the panel rolls back automatically to the current address.":
    "*Перезапуск контейнера панели.* Как поднимется — зайдите по новому адресу, этого достаточно для подтверждения. Если адрес недоступен или сертификат не выпустился, панель сама вернётся на текущий адрес.",
  "Reconnect at the new address ↗": "Зайти по новому адресу ↗",
  "*Confirm the new address.* Open `{v1}` in a new tab to confirm it — the change is applied *only once* it loads there.":
    "*Подтвердите новый адрес.* Откройте `{v1}` в новой вкладке — изменение применится, *только когда* страница там откроется.",
  "*Couldn't verify the new address yet.* I probed `{v1}` from here and it didn't answer in time — it may still be warming up (a fresh Cloudflare origin can be slow), *or* it's not reachable at all (e.g. a direct-TLS panel bound to `127.0.0.1` instead of a public IP, or a port your proxy/DNS doesn't route). Open it to confirm anyway — the change applies *only if it loads*.":
    "*Новый адрес пока не проверился.* Я запросил `{v1}` отсюда, и он не ответил вовремя — возможно, он ещё прогревается (свежий origin в Cloudflare бывает медленным), *либо* недоступен вовсе (например, панель с прямым TLS слушает `127.0.0.1` вместо публичного адреса, или порт не проходит через прокси/DNS). Всё равно откройте его — изменение применится, *только если он откроется*.",
  "Open the new address to confirm ↗": "Открыть новый адрес для проверки ↗",
  "Operation cooldown.": "Операция ещё идёт.",
  "An address change is still waiting to be confirmed.": "Смена адреса ждёт подтверждения.",
  "Address changes run *one at a time* — Save is locked until it finishes. If a change is in flight, you can still cancel it from the tab that started it.":
    "Смены адреса идут *по одной* — «Сохранить» заблокировано до конца. Если смена уже запущена, отменить её можно во вкладке, где она началась.",
  "*These settings changed elsewhere.* The panel's saved address settings were updated by the server (a rollback, a boot reconcile, or a change confirmed in another tab) while you have *unsaved edits* here — so a field below may be based on an *old* value. *Reload the page* before saving, or your change could re-apply a value the panel already reverted.":
    "*Эти настройки изменились не здесь.* Сохранённые адреса обновил сам сервер (откат, сверка при старте или подтверждение в другой вкладке), а у вас тут *несохранённые правки* — значит, поле ниже может опираться на *старое* значение. *Обновите страницу* перед сохранением, иначе вернёте то, что панель уже откатила.",
  "How TLS is terminated — this decides which ports are valid below. One choice issues both certificates (the panel's and swg-sub's, always separate keys).":
    "Где завершается TLS — от этого зависит, какие порты ниже допустимы. Один выбор выпускает оба сертификата (панели и swg-sub, ключи всегда разные).",
  "This box's own node reaches the panel on {v1} — a dedicated plain-HTTP loopback port, served at the root. It's set at install and a public address, port, path, or certificate change never moves it, so the co-located node never loses the panel.":
    "Нода на этой же машине подключается к панели по {v1} — отдельный порт без TLS на localhost, в корне сайта. Он задаётся при установке, и смена публичного адреса, порта, пути или сертификата не влияет на доступ, поэтому локальная нода не теряет панель.",
  " Saving binds `{v1}` *alongside* the current port (both keep serving) — you then re-point your reverse proxy and confirm to drop the old one, with no downtime. External nodes dial your public URL through the proxy, so they don't change; only a co-located node that dials the panel on `127.0.0.1` needs its `panel.url` port updated too.":
    " При сохранении `{v1}` поднимется *вместе* с текущим портом (работают оба) — затем перенастройте прокси и подтвердите, чтобы убрать старый, без простоя. Внешние ноды ходят на публичный адрес через прокси, им менять нечего; только ноде на этой же машине, который ходит на `127.0.0.1`, нужно поправить порт в `panel.url`.",
  " The public URL is served by *your reverse proxy*, not the panel — make sure the proxy serves it (server_name / TLS cert / path) before relying on it. The panel's own mount path stays `SWG_PANEL_BASE`. Nodes are told this URL as their dial address, so external nodes re-point to it on their next sync — make sure they can reach it; one that can't must have its `panel.url` updated by hand.":
    " Публичный адрес отдаёт *ваш обратный прокси*, а не панель — прежде чем на него полагаться, проверьте прокси (server_name, сертификат, путь). Свой путь монтирования панель берёт из `SWG_PANEL_BASE`. Нодам этот адрес сообщается как адрес подключения, так что внешние перейдут на него при следующей синхронизации — убедитесь, что он им доступен; кому нет, тому `panel.url` придётся править вручную.",
  "*Nodes re-point themselves.* On save, online nodes learn the new address on their next sync and switch to it — the old address stays reachable for ~3 minutes so they can. A node that is *offline* during the change (or one installed without verifying/pinning the panel cert) must be re-pointed by hand: set `panel.url` in `/etc/swg-agent/config.json` (bare-metal) or `PANEL_URL` in `.env` (docker) to the new address, then restart `swg-noded` / recreate the container.":
    "*Ноды перейдут сами.* После сохранения те, что на связи, узнают новый адрес при следующей синхронизации и перейдут — старый адрес держится ещё около 3 минут, чтобы они успели. Нода, который был *офлайн* во время смены (или ставился без проверки и закрепления сертификата панели), придётся перенастроить руками: пропишите `panel.url` в `/etc/swg-agent/config.json` (без Docker) или `PANEL_URL` в `.env` (Docker) и перезапустите `swg-noded` либо пересоздайте контейнер.",
  "Reverse-proxy config for the panel (nginx) — full `server { }` for the values above":
    "Конфиг прокси для панели (nginx) — готовый `server { }` под значения выше",
  "Built from the domain, external port, path (from the Public URL) and the internal listen address above. Point `ssl_certificate` at your real cert, then `nginx -t && systemctl reload nginx`.":
    "Собран из домена, внешнего порта, пути (из публичного адреса) и внутреннего адреса выше. Укажите в `ssl_certificate` свой сертификат, затем `nginx -t && systemctl reload nginx`.",
  "*Behind a reverse proxy.* Point your proxy at `{v1}` and make sure it serves this URL's path. swg-sub picks it up on Save — a path or domain change reloads it live (no downtime; existing links keep working during a grace), a host/port change restarts it. If the panel has no root helper, it saves and asks you to run `systemctl reload swg-sub`.":
    "*За обратным прокси.* Направьте прокси на `{v1}` и проверьте, что он отдаёт путь этого адреса. swg-sub подхватит настройки при сохранении: смена пути или домена перечитывается на лету (без простоя, старые ссылки какое-то время ещё работают), смена хоста или порта — с перезапуском. Если у панели нет прав root, она сохранит и попросит выполнить `systemctl reload swg-sub`.",
  "Reverse-proxy config for the subscription page (nginx) — full `server { }` for the values above":
    "Конфиг прокси для страницы подписки (nginx) — готовый `server { }` под значения выше",
  "If swg-sub shares the panel's domain, merge its `location` into that server block instead of a second one — then reload nginx.":
    "Если swg-sub живёт на домене панели, перенесите его `location` в тот же server-блок вместо второго — и перечитайте конфиг nginx.",
  "Set up your *Encryption Vault* first in {v1} — each server's interface key is sealed under it.":
    "Сначала настройте *хранилище ключей* в {v1} — ключ интерфейса каждого сервера запечатан им.",
  "Set up once. Confirm your panel password — an encryption key is generated in your browser and shown once; the server only ever stores it wrapped, so it can't read your clients' private keys.":
    "Настраивается один раз. Подтвердите пароль панели — ключ шифрования создастся в браузере и покажется один раз; сервер хранит только его в обёртке и не может прочитать приватные ключи клиентов.",
  "*Reset drops all stored encrypted configs and invalidates every subscription URL.* You'll set up a new encryption key afterwards, then re-issue affected peers. Type *RESET* to confirm.":
    "*Сброс удалит все зашифрованные конфиги и обесценит все ссылки на подписки.* Дальше вы заведёте новый ключ шифрования и перевыпустите затронутых пиров. Для подтверждения введите *RESET*.",
  "Encrypted {v1} of {v2} · purged {v3} plaintext": "Зашифровано {v1} из {v2} · вычищено {v3} в открытом виде",
  " +{n} more": " и ещё {n}",
  "Every assigned peer with a stored key is encrypted.": "Все пиры с владельцем и сохранённым ключом зашифрованы.",
  "Applying can take up to a minute — the nodes reconfigure and re-pull their lists. This stays open until it finishes.":
    "Применение может занять до минуты — ноды перенастраиваются и заново тянут списки. Окно закроется по завершении.",
  "Remove *{v1}* {v2} from *every node*? Interface rules that use it stop matching, and each node drops its records on the next sync. You can add it back from the catalog any time.":
    "Убрать *{v1}* {v2} со *всех нод*? Правила интерфейсов с ним перестанут срабатывать, а ноды удалят его записи при следующей синхронизации. Вернуть из каталога можно в любой момент.",
  "Reset this node's smart routing — clear just the learned IPs, or wipe + rebuild + re-pull every list. Use it to recover a stuck node.":
    "Сброс умной маршрутизации на этой ноде: очистить только выученные адреса или стереть, собрать заново и перетянуть все списки. Помогает расклинить нода.",
  "{v1} currently runs on {v2}": "{v1} сейчас работает: {v2}",
  "Node": "Нода",
  "Every mode matches by destination *IP* first (GeoIP / ASN / your IP lists) — that layer is *always on* and carries all traffic, including calls, UDP and QUIC. The choice adds an optional *host (domain)* matching layer on top: none, via the node's *DNS*, or read from the *TLS handshake*. Traffic always stays in-kernel in any mode including *{v1}* (no userspace proxy). Changing it reconfigures {v2} and changes which lists its interfaces can use.":
    "Любой режим сначала смотрит на *IP* назначения (GeoIP, ASN, ваши списки адресов) — этот слой *всегда включён* и ведёт весь трафик, включая звонки, UDP и QUIC. Выбор добавляет сверху необязательный слой по *домену*: никак, через *DNS* ноды или чтением *рукопожатия TLS*. Трафик в любом режиме, включая *{v1}*, остаётся в ядре (без прокси в пользовательском пространстве). Смена режима перенастроит {v2} и изменит, какие списки доступны его интерфейсам.",
  "the node": "нода",
  "*Reset routing* recovers a stuck node — clear just the learned IPs, or wipe + rebuild + re-pull everything.":
    "*Сброс маршрутизации* расклинивает нода: очистить только выученные адреса или стереть, собрать заново и перетянуть всё.",
  "Large lists are memory-hungry — every enabled list is loaded into RAM on *each* entry node that uses it, roughly *130 MB per 1M domains*. Keep your smallest node's memory in mind before turning on big lists.":
    "Большие списки едят память — каждый включённый список грузится в RAM на *каждой* входной ноде, где он нужен, примерно *130 МБ на 1 млн доменов*. Оглядывайтесь на самый слабый нода, прежде чем включать большие списки.",
  "provider-maintained · read-only": "ведёт поставщик · только чтение",
  "your own IPs / domains · editable · apply immediately": "ваши адреса и домены · правятся · применяются сразу",
  "Untitled list": "Список без имени",
  "src|Custom": "Свой",
  "edit": "править",
  "{v1} matched by domain name — needs Force-DNS or SNI mode.":
    "{v1} по имени домена — нужен режим Force-DNS или SNI.",
  "Greyed rows are Host-only — this node is IP-only, so they can't match here. The pull stays remembered; switch to Force-DNS or SNI to activate them.":
    "Серые строки работают только по домену, а эта нода — только по IP, поэтому здесь они не сработают. Выбор запомнится; переключите нода на Force-DNS или SNI, чтобы включить их.",
  "no lists yet — add one →": "списков пока нет — добавьте →",
  "drop ads, malware, adult, threat IPs — by domain or IP":
    "режем рекламу, вирусы, 18+, опасные адреса — по домену или IP",
  "{v1} matched by IP address — works in every mode.": "{v1} по IP-адресу — работает в любом режиме.",
  "{v1} matched by domain name — needs *{v2}* or *Hybrid-SNI* mode (they fill the block set from DNS). IP-only and Kernel-SNI can't match domains.":
    "{v1} по имени домена — нужен режим *{v2}* или *Hybrid-SNI* (они наполняют набор блокировок из DNS). Режимы «только IP» и Kernel-SNI домены не различают.",
  "{v1} a domain list can't enforce on an IP-only or Kernel-SNI node — it's skipped, never pushed. Switch that node to Force-DNS / Hybrid-SNI, or add an IP list.":
    "{v1} доменный список не работает на ноде с режимом «только IP» или Kernel-SNI — его просто пропускают и не отправляют. Переключите нода на Force-DNS или Hybrid-SNI либо добавьте список адресов.",
  "Not available": "Недоступно",
  "Turn proxies are off.": "Turn-прокси выключены.",
  "Creation buttons and the turn-proxy sections are hidden across the panel. Deployed proxies keep running — they're just not shown here.":
    "Кнопки создания и разделы turn-прокси скрыты по всей панели. Уже развёрнутые прокси работают — их просто не видно.",
  "not yet used": "не используется",
  "Check every deployed proxy's fork for a newer release now, and update the ones that are behind":
    "Проверить сейчас у всех развёрнутых прокси, нет ли свежих выпусков, и обновить отставшие",
  "Whether any client app's config/link schema changed upstream on GitHub since we curated it — fetches each app's source file and flags drift per app to review.":
    "Не изменилась ли на GitHub схема конфигов и ссылок клиентских приложений с тех пор, как мы её описали — тянет исходник каждого приложения и помечает расхождения.",
  "Fetch each client app's schema source from GitHub and flag the ones whose upstream changed":
    "Забрать с GitHub исходники схем клиентских приложений и отметить изменившиеся",
  "Downloading…": "Скачивается…",
  "The broadest GeoSite + GeoIP set — per-service domain and country IP rules, tracking upstream Clash data.":
    "Самый широкий набор GeoSite + GeoIP — правила по сервисам и странам, вслед за данными Clash.",
  "Community-curated per-service domain sets — well-maintained, the source many routing rules build on.":
    "Наборы доменов по сервисам от сообщества — аккуратно ведутся, на них строят многие правила.",
  "Release-built GeoIP — country and service IP ranges in clean CIDR text, a solid IP-tier companion.":
    "GeoIP из релизов — диапазоны стран и сервисов чистым CIDR, надёжное дополнение по IP.",
  "Russia-focused domain and IP lists for anti-censorship routing — blocked services and their networks.":
    "Списки доменов и адресов с фокусом на Россию для обхода блокировок — закрытые сервисы и их сети.",
  "600+ per-app rule sets — a dedicated list for almost any single service, some with IP variants.":
    "600+ наборов правил по приложениям — отдельный список почти на любой сервис, часть с адресами.",
  "Built-in recommended presets for common services — panel-maintained, ready to route.":
    "Встроенные готовые наборы для популярных сервисов — ведёт панель, можно сразу маршрутизировать.",
  "A long-running, hand-curated ads + trackers list — small but very low false-positive.":
    "Давний список рекламы и трекеров, собранный вручную — небольшой, но почти без ложных срабатываний.",
  "A well-made combined ads + tracking + malware list in three strengths (Lite / Pro / Xtra).":
    "Добротный сводный список рекламы, слежки и вредоносного в трёх уровнях (Lite / Pro / Xtra).",
  "Academic categorised lists — the only maintained source with a Gaming category (CC BY-SA, attribute).":
    "Академические списки по категориям — единственный живой источник с категорией игр (CC BY-SA, укажите авторство).",
  "Curated threat-IP feeds — attackers, C2 and abuse sources, rebuilt daily. Level 1 is the low-false-positive safe default.":
    "Отобранные ленты опасных адресов — атакующие, C2 и источники злоупотреблений, обновляются ежедневно. Уровень 1 — безопасный вариант по умолчанию.",
  "Every Tor network exit relay — the official bulk list, refreshed hourly.":
    "Все выходные узлы сети Tor — официальный полный список, обновление раз в час.",
  "Fresh phishing domains from PhishTank / OpenPhish. Licensed CC BY-NC — non-commercial use only.":
    "Свежие фишинговые домены из PhishTank / OpenPhish. Лицензия CC BY-NC — только некоммерческое использование.",
  "One heavily-curated all-in-one list tuned for very few false positives — NOT split by category. Pick Big (ads + malware + phishing + tracking, in one) or the separate NSFW list.":
    "Один тщательно отобранный список «всё в одном» с минимумом ложных срабатываний — БЕЗ деления на категории. Возьмите Big (реклама + вредоносное + фишинг + слежка вместе) или отдельный список NSFW.",
  "Public-domain, per-category domain lists — one clean file each for ads, malware, gambling and more (Unlicense).":
    "Общественное достояние, списки доменов по категориям — по одному чистому файлу на рекламу, вредоносное, азартные игры и прочее (Unlicense).",
  "The most popular unified hosts list (ads + malware) plus a few bolt-on category variants.":
    "Самый популярный сводный hosts-список (реклама + вредоносное) плюс несколько дополнений по категориям.",
  "The reference DNS blocklist — ads, tracking, malware and phishing, refreshed several times a day (GPL-3.0).":
    "Эталонный DNS-блоклист — реклама, слежка, вредоносное и фишинг, обновляется несколько раз в день (GPL-3.0).",
  "Your own IP / domain lists — turn off to hide the Custom lists section in routing.":
    "Ваши списки адресов и доменов — выключите, чтобы скрыть раздел своих списков в маршрутизации.",
  "Re-fetch every routed list from its provider now (updates the panel; nodes pull the changes on their schedule)":
    "Подтянуть все маршрутные списки у провайдеров (обновится панель; ноды подтянут изменения по расписанию)",
  "Interface colours": "Цвета интерфейсов",
  "The colour each protocol's tags take everywhere — a value per theme. Hover a swatch to preview it.":
    "Каким цветом метки каждого протокола показываются в панели. Наведите на образец для примерки к светлому и тёмному стилю.",
  "Endpoint is reaching the server, but the handshake never completes (likely DPI / MTU / wrong Wireguard or AmneziaWG params).":
    "Клиент до сервера достучался, но рукопожатие не завершается (похоже на DPI, MTU или неверные параметры WireGuard/AmneziaWG).",
  "Handshake is up but no inbound data has flowed for a while — a one-way block / DPI on the return path. (This can't tell a genuinely-stuck peer from a simply-idle one, so turn it off if idle peers bother you.)":
    "Рукопожатие есть, но входящих данных давно нет — похоже на одностороннюю блокировку или DPI на обратном пути. (Отличить застрявшего пира от просто простаивающего так нельзя, поэтому выключите, если простой мешает.)",
  "Applied when creating a new interface — you can still override per interface.":
    "Подставляется при создании интерфейса — у каждого можно задать своё.",
  "Backup each server's interface key so a wiped / rebuilt node restores its interfaces with their original identities.":
    "Хранить копию ключа интерфейса каждого сервера, чтобы после чистки или пересборки интерфейсы вернулись с прежними ключами.",
  "This panel has no login configured — changes are disabled.": "У панели не настроен вход — изменения недоступны.",
  "Subscriptions are on and need encrypted config storage. Turn {v1} off first, or keep encrypted storage on — saving this as-is will be rejected.":
    "Подписки включены и требуют шифрованного хранения конфигов. Сначала выключите {v1} или оставьте шифрование включённым — иначе сохранение отклонят.",
  "An encryption key held only by you (independent of your login password) protects stored client configs so the server can't read the private keys, and unlocks a peer's QR any time you're signed in. The same key powers subscriptions when you turn them on.":
    "Ключ шифрования есть только у вас (он не связан с паролем входа): он закрывает сохранённые конфиги клиентов (чтобы сервер не читал приватные ключи), и позволяет открывать QR пира не только при создании. На нём же работают подписки, если их включить.",
  "Subscriptions serve the encrypted config blobs — turn on *Keep encrypted configs* in {v1} first.":
    "Подписки отдают зашифрованные конфиги — сначала включите *Хранить шифрованные конфиги* в {v1}.",
  "Auto-generate subscription links for new users": "Сразу выдавать ссылку на подписку новым пользователям",
  "Not set": "Не задано",
  "The subscription page's URL, listen address and certificate are configured in {v1}.":
    "Адрес страницы подписки, порт и сертификат настраиваются в {v1}.",
  "Subscriptions reuse the same encryption key that protects your stored client configs — set it up under {v1}. No separate key.":
    "Подписки работают на том же ключе, что закрывает сохранённые конфиги клиентов — заведите его в {v1}. Отдельного ключа нет.",
  "sample|Button": "Кнопка",
  "How long the panel waits before treating things as stale — in seconds.":
    "Через сколько секунд панель считает данные устаревшими.",
  "How many rows the Overview's ranked lists show (1–50).":
    "Сколько строк показывать в рейтингах на «Обзоре» (1–50).",
  "All settings saved": "Все настройки сохранены",
  "Overrides for *{v1}* — blank inherits the default. Changing the subnet, prefix, or AWG re-provisions this node's links on Save (it briefly drops off the mesh while peers reconnect with the new config).":
    "Параметры для *{v1}* — пустое поле берёт значение по умолчанию. Смена подсети, префикса или параметров AWG пересоберёт подключения этой ноды при сохранении (она ненадолго выпадет из сети, пока соседи переподключаются).",
  "Mesh Ingress IP": "Адрес входа в сеть",
  "— the address peers dial to reach this node": "— по нему пиры подключаются к этой ноде",
  "(auto)": "(авто)",
  "Obfuscation for the mesh links that terminate on *{v1}* — any node connecting to it adopts these and reconnects on Save. Blank = auto (a fresh set per link).":
    "Маскировка для связей сети, которые приходят на *{v1}* — каждый подключающийся нода примет её и переподключится при сохранении. Пусто — авто (свой набор на связь).",
  "Which of *{v1}*'s IPs it uses for each outbound role.":
    "Какие адреса *{v1}* использует для каждой исходящей роли.",
  "state|On": "Вкл",
  "Configure a panel login first.": "Сначала настройте вход в панель.",
  "Sign-in requires a code from your authenticator app. Keep your recovery codes somewhere safe in case you lose the device.":
    "Для входа нужен код из приложения-аутентификатора. Сохраните запасные коды в надёжном месте на случай потери устройства.",
  "Scan this with your authenticator app, then enter the 6-digit code it shows to confirm.":
    "Отсканируйте это приложением-аутентификатором и введите показанный им код из 6 цифр.",
  "QR unavailable": "QR недоступен",
  "Confirm with your password and a current code to turn two-factor off.":
    "Чтобы выключить двухфакторный вход, подтвердите паролем и текущим кодом.",

  // ── strings that were interleaved with interpolations (see i18n-extract --mixed) ──
  "peak {v1}": "пик {v1}",
  "Peer {n}": "Пир {n}",
  "tag|disabled": "выключен",
  "Showing {n} of {total} — the rest come across on adopt.":
    "Показано {n} из {total} — остальные придут при подключении.",
  "Currently {v1}": "Сейчас {v1}",
  "What clients dial · currently {v1}": "Куда стучатся клиенты · сейчас {v1}",
  "System {v1}": "Системный {v1}",
  "Applied to the node (currently {v1})": "Применится на ноде (сейчас {v1})",
  "Set a public base URL in {v1} to build the link.": "Задайте публичный адрес в {v1}, чтобы собрать ссылку.",
  "Which {v1} proxy": "Какой прокси {v1}",
  "Not available with {v1}": "Не работает с {v1}",
  // budget-ok: empty-state prose in its own block — it wraps, nothing beside it to overlap
  "No list on this node matches “{q}”. Add more in Settings → Routing lists.":
    "На этой ноде нет списков по запросу «{q}». Добавьте их в «Настройках → Списки маршрутизации».",
  "Direct — {v1}": "Напрямую — {v1}",
  "{v1} on this node": "{v1} на этой ноде",
  "the node is creating it…": "нода создаёт его…",
  "the node is adding it…": "нода добавляет его…",
  "{n} saturated": "{n} под нагрузкой",
  "idle {n}%": "простой {n}%",
  "{v1} to fix": "{v1} — решить",
  "loading {v1} history…": "загружаем историю за {v1}…",
  "volume over the {v1}": "объём за {v1}",
  "avg over the {v1}": "среднее за {v1}",
  "live rates": "сейчас",
  " · no history yet for this range": " · истории за этот период пока нет",
  "{v1} here": "{v1} здесь",
  "{v1} total": "{v1} всего",
  "Orphan peers {n}": "Чужих пиров {n}",
  "{n} Online": "{n} в сети",
  "created {v1}": "создан {v1}",
  " · last used {v1}": " · использован {v1}",
  " · never used": " · не в ходу",
  "Confirm in {n}s — verify your proxy first": "Подтвердить через {n} с — сначала проверьте прокси",
  "Confirm & restart in {n}s…": "Перезапуск через {n} с…",
  "Restarting in {n}s…": "Перезапуск через {n} с…",
  "Reconnect in {n}s…": "Вернуться через {n} с…",
  "{v1} to apply:": "{v1} к применению:",
  "Not offered on {v1} — those users get no card for this server":
    "Не предлагается на {v1} — этим пользователям карточка сервера не покажется",
  "No {v1} app for {v2} yet": "{v1} для {v2} пока нет",
  "{v1} — mesh": "{v1} — меш",
  "{v1} — egress": "{v1} — выходы",
  "Advanced": "Подробно",
  "Deployments · {n}": "Развёрнуто · {n}",
  "On this date the peer stops working (it reappears if you extend it).":
    "В этот день пир перестанет работать (продлите — и он вернётся).",
  " Can't be later than the subscription's expiry ({v1}).": " Не позже окончания подписки ({v1}).",
  "The client's private key isn't available, so DNS / MTU / routing can't be rebuilt":
    "Приватного ключа клиента нет, поэтому DNS, MTU и маршруты пересобрать нельзя",
  " (enable store_configs, or edit right after creating)":
    " (включите store_configs или правьте сразу после создания)",
  ". Title and address can still change.": ". Имя и адрес менять можно.",
  "Clean removal: flag the node, then run the uninstall command on the server. The node keeps serving its {v1} until it confirms, then drops itself from the panel.":
    "Чистое удаление: пометьте сервер, затем выполните на нём команду удаления. До подтверждения он продолжит обслуживать свои {v1}, потом сам исчезнет из панели.",
  "+{n} more in Settings": "ещё {n} в настройках",
  "{v1} is WireGuard-only — AmneziaWG interfaces are hidden.":
    "{v1} работает только с WireGuard — интерфейсы AmneziaWG скрыты.",
  " offered to {v1} users": " для пользователей {v1}",
  "Choose the {v1} app": "Приложение для {v1}",
  "No {v1} client app yet.": "Клиента для {v1} пока нет.",
  "This server isn't offered on {v1} — those users won't see a card for it, so there's nothing to configure. Pick an app above to start offering it again.":
    "Этот сервер не предлагается на {v1} — карточки не будет, настраивать нечего. Выберите приложение выше, чтобы снова его предлагать.",
  "{v1} has no in-app settings to configure.": "У {v1} нет настроек внутри приложения.",
  "view change → {v1}": "что изменилось → {v1}",
  "Add {v1}": "Новое {v1}",
  "Remove {v1}": "Убрать {v1}",
  "Not deployed on any node yet — version & rollback appear once a {v1} server is running.":
    "Пока не развёрнут ни на одном сервере — версия и откат появятся, когда заработает {v1}.",
  "held · {v1}": "держим · {v1}",
  "Extra command-line flags for this {v1} server. It's self-contained — its real config lives per interface — so there's little here beyond advanced flags.":
    "Дополнительные флаги ExecStart для сервера {v1}. WDTT самодостаточен — его настройки живут в интерфейсах — так что здесь только тонкие флаги.",
  "All {v1}": "Все {v1}",
  "{v1} unmanaged orphan": "{v1} без владельца",
  "view all {n} connections →": "показать все подключения ({n}) →",

  // ── strings that lived in plain literals (see i18n-extract --literals) ──
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "couldn't save the vault": "не удалось сохранить хранилище",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "couldn't disable escrow": "не удалось выключить депонирование",
  "Unlock the Encryption Vault first.": "Сначала откройте хранилище ключей.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "couldn't enable escrow": "не удалось включить депонирование",
  "Unlock the vault first.": "Сначала откройте хранилище.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "No interface-key vault is set up.": "Хранилище ключей интерфейсов не настроено.",
  "No escrowed key is stored for this interface.": "Для этого интерфейса ключ не сохранён.",
  "The node hasn't reported its transport key yet — try again in a few seconds.":
    "Нода ещё не прислал транспортный ключ — повторите через несколько секунд.",
  "No escrowed identity is stored for this WDTT server.": "Для этого сервера WDTT ключ не сохранён.",
  "Config encryption isn't set up yet.": "Шифрование конфигов ещё не настроено.",
  "That password didn't unlock the Encryption Vault.": "Этот пароль не открыл хранилище ключей.",
  "That doesn't look like an encryption key.": "Это не похоже на ключ шифрования.",
  "That key doesn't match this panel's Encryption Vault.": "Ключ не подходит к хранилищу этой панели.",
  "couldn't enable the subscription": "не удалось включить подписку",
  "Unlock the Subscription Key first.": "Сначала откройте ключ подписок.",
  "couldn't rotate the URL": "не удалось сменить ссылку",
  "couldn't store the subscription config": "не удалось сохранить конфиг подписки",
  "This peer's config is stored encrypted — only you can read it, with your encryption key. Unlock the key to publish this peer now, so its QR appears on the user's subscription page and stays re-viewable in the panel later.":
    "Конфиг пира хранится зашифрованным — прочитать его можете только вы своим ключом. Откройте ключ, чтобы опубликовать пира сейчас: его QR появится на странице подписки и останется доступен в панели.",
  "the peer is created and works right away, but its config isn't published — its QR won't appear on the subscription page. You can still save it by unlocking the key in this browser tab before you reload; after a reload the key is gone from the browser (it was never on the server) and you'd have to rekey the peer to re-issue it.":
    "пир создастся и сразу заработает, но его конфиг не опубликуется — QR на странице подписки не появится. Ещё можно всё сохранить, открыв ключ в этой вкладке до перезагрузки страницы; после перезагрузки ключа в браузере не останется (на сервере его и не было), и пира придётся перевыпускать со сменой ключей.",
  "This user is subscribed, and this change left a peer whose config isn't published yet. Unlock your encryption key to publish it now, so the peer's QR appears on their subscription page.":
    "У пользователя есть подписка, а после этой правки конфиг одного пира остался неопубликованным. Откройте ключ шифрования, чтобы опубликовать его и показать QR на странице подписки.",
  "the peer works right away, but it shows “Not ready yet” (an empty QR) on the user's subscription page. Unlock the key in this browser tab before you reload and it publishes automatically; after a reload you'd have to rekey the peer to re-issue it.":
    "пир сразу заработает, но на странице подписки будет значиться «Ещё не готов» с пустым QR. Откройте ключ в этой вкладке до перезагрузки — он опубликуется сам; после перезагрузки пира придётся перевыпускать со сменой ключей.",
  "WDTT · not running": "WDTT · не запущен",
  "Interface ignored — listed in Settings → Interfaces.": "Интерфейс скрыт — он в «Настройках → Интерфейсы».",
  "Interface un-ignored — back as an adoption candidate.": "Интерфейс возвращён в кандидаты на подключение.",
  "The DTLS port is required.": "Нужен порт DTLS.",
  "The internal WG port is required.": "Нужен внутренний порт WG.",
  "The DTLS port and internal WG port must differ.": "Порты DTLS и внутренний WG должны различаться.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Adopt failed": "Не удалось принять",
  "No WDTT forks are enabled in Settings → Turn proxies":
    "В «Настройках → Turn-прокси» не включена ни одна сборка WDTT",
  "Not running, so its ports and subnet can't be read from the server — set them here.":
    "Не запущен, поэтому порты и подсеть с сервера не считать — задайте их здесь.",
  "Pick the fork this install is": "Укажите, что это за сборка",
  "The node found this server but not its identity (wg-keys.dat), so adopting would mint a new key and break every client. Ignore it instead, or restore its config directory first.":
    "Сервер нашёлся, а его ключи (wg-keys.dat) — нет, поэтому при подключении выпустится новый ключ и все клиенты отвалятся. Лучше скройте его или сначала восстановите каталог с настройками.",
  "No WDTT server was found running on this interface, so there is no identity to take over. Start it and re-check, or adopt it as WireGuard/AmneziaWG.":
    "На этом интерфейсе не найден работающий сервер WDTT, перенимать нечего. Запустите его и проверьте снова либо подключите интерфейс как WireGuard/AmneziaWG.",
  "Managed as a WDTT server — the panel rebuilds it with our patched fork over its existing identity.":
    "Ведём как сервер WDTT — панель пересоберёт его нашей сборкой поверх существующих ключей.",
  "Managed as AmneziaWG (obfuscated) — set its parameters below, or leave blank to keep the interface's existing ones.":
    "Ведём как AmneziaWG (с маскировкой) — задайте параметры ниже или оставьте пустыми, чтобы сохранить нынешние.",
  "Managed as plain WireGuard.": "Ведём как обычный WireGuard.",
  "keeping the interface's own": "оставляем как на интерфейсе",
  "Bounce this interface's service on the node": "Перезапустить службу этого интерфейса на ноде",
  "the interface is recreated and its peers are rekeyed, but their new configs are NOT captured — they can't be re-viewed or served on subscription pages, and you'd have to hand every client a fresh QR by other means. (Unlock later in this same tab before reloading and they're still saved; after a reload the new keys are gone for good.)":
    "интерфейс пересоздастся, ключи пиров сменятся, но новые конфиги НЕ сохранятся — их не посмотреть заново и не отдать на страницах подписки, каждому клиенту придётся передавать свежий QR другим путём. (Откроете ключ в этой же вкладке до перезагрузки — конфиги ещё сохранятся; после перезагрузки новые ключи потеряны навсегда.)",
  "Enter the absolute path to the server's config directory (the one holding wg-keys.dat).":
    "Укажите полный путь к каталогу настроек сервера (тому, где лежит wg-keys.dat).",
  "Enter the absolute path to the interface's .conf.": "Укажите полный путь к файлу .conf интерфейса.",
  "WDTT interface name must be wdtt0–wdtt999.": "Интерфейс WDTT называется от wdtt0 до wdtt999.",
  "Enter the tunnel subnet as CIDR, e.g. 10.8.0.0/24.": "Укажите подсеть туннеля в виде CIDR, например 10.8.0.0/24.",
  "Internal WG port must be a number.": "Внутренний порт WG должен быть числом.",
  "Interface name is required (no spaces or /).": "Нужно имя интерфейса (без пробелов и «/»).",
  "Listen port must be a number.": "Порт должен быть числом.",
  "Request failed.": "Запрос не прошёл.",
  "Onboarding requested — applies on the node's next sync.":
    "Подключение запрошено — применится при следующей синхронизации.",
  "Interface creation requested — applies on the node's next sync.":
    "Интерфейс запрошен — создастся при следующей синхронизации.",
  "This subnet is already in use in the fleet": "Такая подсеть уже занята во флоте",
  "Taking over an interface already on the node": "Перенимаем интерфейс, который уже есть на ноде",
  "Create a new interface — switch on to take over one already on the node":
    "Создать новый интерфейс — включите, чтобы перенять существующий",
  "Failed to delete interface.": "Не удалось удалить интерфейс.",
  "No changes to save": "Нечего сохранять",
  "This end": "Эта сторона",
  "— (not dialed yet)": "— (ещё не звонили)",
  "Last handshake": "Рукопожатие",
  "Auto (default route)": "Авто (по умолчанию)",
  "Interface saved — starting…": "Интерфейс сохранён — запускаем…",
  "Interface saved.": "Интерфейс сохранён.",
  "The node's new server key is now the panel's key for this interface. Every client's existing config / QR for this interface has stopped working — re-issue and re-distribute the new QR codes / configs to them.":
    "Новый ключ сервера стал ключом панели для этого интерфейса. Все прежние конфиги и QR по нему больше не работают — перевыпустите их и раздайте заново.",
  "Accept the node's new key — you'll re-distribute every QR.":
    "Принять новый ключ ноды — QR придётся раздать заново.",
  "The node was re-created and no longer holds the original key, so Restore can't recover it — Adopt is the only option. You'll re-distribute every QR.":
    "Нода пересоздали, прежнего ключа на нём нет, поэтому восстановить его нечем — остаётся только принять новый. QR придётся раздать заново.",
  "AWG params": "Параметры AWG",
  "Subscription was blocked": "Подписка заблокирована",
  "Subscription is active": "Подписка активна",
  "Peer was blocked": "Пир заблокирован",
  "User was blocked": "Доступ закрыт",
  "Assign to…": "Назначить…",
  "Primary connection — the user's first choice": "Основное подключение — первое у пользователя",
  "Make this the primary connection": "Сделать основным подключением",
  "Unassigned peer": "Пир без владельца",
  "Couldn't create the subscription link": "Не удалось создать ссылку на подписку",
  "Couldn't add the VK link": "Не удалось добавить ссылку VK",
  "Couldn't save the VK links": "Не удалось сохранить ссылки VK",
  "Couldn't set the expiry": "Не удалось задать срок",
  "Expiry cleared": "Срок снят",
  "Subscription expiry": "Срок действия подписки",
  // budget-ok: a sheet TITLE, not a label — measured at 293px of a 430px head, no clip, no wrap
  "Peer expiry": "Срок действия пира",
  "After this date the whole subscription counts as expired — its page shows “Expired” and its peers stop being served. Blank = never expires.":
    "После этой даты вся подписка считается истёкшей — на странице будет «Истекла», пиры перестанут отдаваться. Пусто — бессрочно.",
  "After this date just this peer expires (its config stops working); the rest of the user's peers are unaffected. It can't be set later than the user's subscription expiry. Blank = follows the subscription.":
    "После этой даты истечёт срок действия только этого пира (его конфиг перестанет работать), остальных это не коснётся. Дата не может быть позже окончания срока действия подписки. Пустая дата = срок действия как у подписки.",
  "Show config": "Конфиг",
  "Show QR": "QR",
  "Show link": "Ссылка",
  "No stored config — re-issue this peer to enable its QR & download.":
    "Конфиг не сохранён — перевыпустите пира, чтобы включить QR и загрузку.",
  "Config shown right after creation, or enable store_configs to keep it.":
    "Конфиг показывается сразу после создания; включите store_configs, чтобы он хранился.",
  "You have unsaved changes that will be lost. Leave without saving?":
    "Есть несохранённые изменения, они пропадут. Уйти без сохранения?",
  "Gemini (Google AI)": "Gemini (ИИ Google)",
  "Microsoft Copilot": "Microsoft Copilot",
  "Russia — all IPs": "Россия — все адреса",
  "All traffic (catch-all)": "Весь трафик (всё подряд)",
  "Perplexity AI": "Perplexity AI",
  "Russian Government": "Госсайты России",
  "Russian Banks": "Банки России",
  "Russian Social (VK / OK)": "Соцсети России (VK / OK)",
  "Google search, accounts & core services": "Поиск, аккаунты и основные службы Google",
  "YouTube video + its CDN": "Видео YouTube и его CDN",
  "Netflix streaming & app": "Netflix — видео и приложение",
  "Telegram messenger": "Мессенджер Telegram",
  "WhatsApp messenger": "Мессенджер WhatsApp",
  "ChatGPT & the OpenAI API": "ChatGPT и API OpenAI",
  "TikTok video": "Видео TikTok",
  "GitHub & its CDN": "GitHub и его CDN",
  "Spotify audio": "Музыка Spotify",
  "Twitch live streaming": "Трансляции Twitch",
  "Discord voice & chat": "Discord — голос и чат",
  "Cloudflare CDN / edge network": "CDN и пограничная сеть Cloudflare",
  "Yandex services": "Службы Яндекса",
  "Russian government sites": "Государственные сайты России",
  "Russian banks": "Российские банки",
  "Russian social (VK / OK)": "Российские соцсети (VK / OK)",
  "Claude & the Anthropic API": "Claude и API Anthropic",
  "Google Gemini AI — kept separate from the rest of Google":
    "Gemini от Google — отдельно от остальных служб Google",
  "Microsoft & GitHub Copilot": "Microsoft и GitHub Copilot",
  "Signal private messenger": "Защищённый мессенджер Signal",
  "The whole Russian IP space (GeoIP) — works in every mode":
    "Всё адресное пространство России (GeoIP) — работает в любом режиме",
  "Sites blocked inside Russia — comprehensive (~86k domains, heavy)":
    "Сайты, закрытые в России — полный список (~86 тыс. доменов, тяжёлый)",
  "News / media blocked inside Russia — light subset (~130)":
    "Новости и СМИ, закрытые в России — краткий список (~130)",
  "couldn't load — will retry": "не загрузилось — попробуем ещё",
  "Custom IPs / ASNs": "Свои адреса и ASN",
  "Custom IPs/Domains/ASNs": "Свои адреса, домены и ASN",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Reset failed.": "Сбросить не удалось.",
  "Learned IPs cleared — the node forgets them and re-learns on its next sync.":
    "Выученные адреса очищены — нода забудет их и выучит заново при следующей синхронизации.",
  // budget-ok: a toast — its own bar, wraps
  "Routing reset queued — the node wipes, rebuilds and re-pulls on its next sync.":
    "Сброс маршрутизации поставлен в очередь — при следующей синхронизации нода всё сотрёт, соберёт и перетянет.",
  "DNS resolver": "DNS-резолвер",
  "SNI scanner": "Сканер SNI",
  "SNI parser": "Разбор SNI",
  "kernel SNI scanner unavailable — running userspace SNI parser":
    "ядерный сканер SNI недоступен — работает разбор SNI в пользовательском режиме",
  "down — host routing degraded": "не работает — домены страдают",
  "OFF — routing stays fresh, no remembered IPs": "ВЫКЛ — маршруты свежие, адреса не запоминаются",
  "Drop BitTorrent / P2P — protects this exit IP's reputation. Free port-hint by default; signature scan where the node supports it.":
    "Резать BitTorrent и P2P — бережёт репутацию этого выходного адреса. По умолчанию дёшево, по портам; где нода умеет — по сигнатурам.",
  "Drop outbound mail on TCP :25 — stops spam being relayed through this exit.":
    "Резать исходящую почту на TCP :25 — через этот выход не пойдёт спам.",
  "Rate-limit outbound port-scans, brute-force and SYN-floods leaving this interface.":
    "Ограничивать исходящее с этого интерфейса: сканы портов, перебор паролей и SYN-потоки.",
  "Drop known cryptomining / Stratum-pool traffic.": "Резать трафик известных майнинг-пулов (Stratum).",
  "Drop QUIC / HTTP-3 (UDP :443) so connections fall back to TCP and stay inspectable.":
    "Резать QUIC и HTTP-3 (UDP :443), чтобы соединения падали на TCP и оставались разбираемыми.",
  "Drop DoH / DoT / DoQ so DNS can't slip past the tunnel's filtering.":
    "Резать DoH, DoT и DoQ, чтобы DNS не проскакивал мимо фильтрации туннеля.",
  "Block WebRTC / STUN — prevents the client's real IP leaking around the tunnel.":
    "Закрыть WebRTC и STUN — настоящий адрес клиента не утечёт мимо туннеля.",
  "Matched by IP address — works in every mode.": "По IP-адресу — работает в любом режиме.",
  "Matched by domain name.": "По имени домена.",
  "No lists match.": "Списков не нашлось.",
  "Every available list is already added.": "Все доступные списки уже добавлены.",
  "Add from catalog": "Добавить из каталога",
  "Filter this node's lists…": "Отбор среди списков ноды…",
  "Host-only list — switch this node to Force-DNS to use it":
    "Список только по доменам — переключите нода на Force-DNS",
  "Custom IPs / domains": "Свои адреса и домены",
  "Couldn't switch mode": "Не удалось сменить режим",
  "→ not found": "→ не найдено",
  "Auto (target node default)": "Авто (как на ноде назначения)",
  "Source IP on the target node that clients egress from.":
    "Адрес на ноде назначения, с которого клиенты выходят.",
  "Source IP clients egress from.": "Адрес, с которого клиенты выходят.",
  "A custom rule needs at least one IP or domain.": "Своему правилу нужен хотя бы один адрес или домен.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "IP-only mode routes by IP only — remove the domains ({list}), or switch this node to Force-DNS.":
    "Режим «только IP» ведёт трафик по адресам — уберите домены ({list}) или переключите нода на Force-DNS.",
  "IP-only mode routes by IP only — remove the domain ({list}), or switch this node to Force-DNS.":
    "Режим «только IP» ведёт трафик по адресам — уберите домен ({list}) или переключите нода на Force-DNS.",
  "Node is running a newer version than the panel — update the panel to catch up":
    "На ноде версия новее, чем у панели — обновите панель",
  "Node settings": "Настройки ноды",
  "Bring this WDTT server back with its original identity — no user re-imports":
    "Вернуть сервер WDTT с прежними ключами — пользователям ничего не переносить",
  "Recreate this WDTT server with a NEW identity — every user re-imports":
    "Пересоздать сервер WDTT с НОВЫМИ ключами — переносить придётся всем",
  "Found on the node — not managed by the panel. Open to Adopt or Ignore.":
    "Найден на ноде, панель им не управляет. Откройте, чтобы подключить или скрыть.",
  "A WDTT server is running on it": "На нём работает сервер WDTT",
  "Ignored candidate — Settings-style dismissed; open to Un-ignore": "Скрытый кандидат — откройте, чтобы вернуть",
  "Found on the node — the panel doesn't manage it. Adopt to manage, or Ignore.":
    "Найден на ноде, панель им не управляет. Подключите или скройте.",
  "Failed to request update.": "Не удалось запросить обновление.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Failed to start update.": "Не удалось запустить обновление.",
  "Couldn't check for updates.": "Не удалось проверить обновления.",
  "No notes for this release.": "Описания у этого выпуска нет.",
  "See the changelog for what's new.": "Что нового — в списке изменений.",
  // budget-ok: the update bubble's footer line — its own row
  "Click to update this server.": "Нажмите, чтобы обновить этот сервер.",
  "Panel services need attention": "Службам панели нужно внимание",
  "Port scans": "Сканы портов",
  "Torrents caught": "Поймано торрентов",
  "Scanners flagged": "Отмечено сканеров",
  "just created, not seen yet": "только создан, ещё не виден",
  "server stale — can't confirm": "сервер молчит — не подтвердить",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Username can't be empty.": "Имя пользователя не может быть пустым.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Username can't contain a colon.": "В имени пользователя не может быть двоеточия.",
  "Enter your current password to confirm.": "Введите текущий пароль для подтверждения.",
  "New passwords don't match.": "Новые пароли не совпадают.",
  "New password must be at least 8 characters.": "В новом пароле должно быть не меньше 8 знаков.",
  "Failed to update.": "Не удалось обновить.",
  "Updated. Reloading — sign in with your new credentials…": "Обновлено. Перезагружаем — войдите с новыми данными…",
  "Peer added": "Пир добавлен",
  "Peer removed": "Пир удалён",
  "Node came online": "Нода на связи",
  "Node went offline": "Нода пропал",
  "Failed to save webhook": "Не удалось сохранить вебхук",
  "Failed to create token": "Не удалось создать токен",
  "API on — tokens are accepted": "API включён — токены принимаются",
  "API off — all tokens are rejected": "API выключен — токены отклоняются",
  "Confirming the new address ({v1}) — open it in a new tab so it can reach this panel. It reverts on its own if it can't be reached.":
    "Проверяем новый адрес ({v1}) — откройте его в новой вкладке, чтобы он достучался до панели. Не ответит — всё откатится само.",
  "The new address wasn't confirmed — kept the current one. Check its DNS / Cloudflare / firewall / port, then try again.":
    "Новый адрес не подтвердился — оставили текущий. Проверьте DNS, Cloudflare, файрвол и порт, потом повторите.",
  "Issuing the certificate…": "Выпускаем сертификат…",
  "Waiting for the new address to start responding…": "Ждём, когда новый адрес начнёт отвечать…",
  "Waiting to confirm the reverse-proxy change…": "Ждём подтверждения смены прокси…",
  "Address change cancelled": "Смена адреса отменена",
  "Address change not confirmed": "Смена адреса не подтверждена",
  "You cancelled the change — the panel kept the current address.":
    "Вы отменили смену — панель осталась на текущем адресе.",
  "The new address wasn’t confirmed, so the panel kept the current one. Check its DNS / Cloudflare / firewall / port, then try again.":
    "Новый адрес не подтвердился, панель осталась на текущем. Проверьте DNS, Cloudflare, файрвол и порт, потом повторите.",
  "Cloudflare can't reach this port": "Cloudflare не достучится до этого порта",
  "If this panel is behind Cloudflare, this port won't be reachable.":
    "Если панель стоит за Cloudflare, этот порт будет недоступен.",
  "The subscription update didn't finish in time.": "Обновление подписки не уложилось во время.",
  "Fix the highlighted port first.": "Сначала исправьте отмеченный порт.",
  "The panel and subscription are swapping ports — a single host can't swap two ports at once. First move one of them to a spare free port and Save, then set both to their final ports and Save again.":
    "Панель и подписка меняются портами, а разом поменять два порта на одной машине нельзя. Переведите сначала одну на любой свободный порт и сохраните, потом задайте обоим итоговые порты и сохраните ещё раз.",
  "Saving your changes…": "Сохраняем изменения…",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Save failed.": "Сохранить не удалось.",
  "Updating the subscription server…": "Обновляем сервер подписок…",
  "The subscription server couldn't be updated.": "Сервер подписок обновить не удалось.",
  "Couldn't apply the panel address.": "Не удалось применить адрес панели.",
  "Saved — review, then Confirm & restart below (you'll re-point your reverse proxy to the new port).":
    "Сохранено — проверьте и нажмите «Подтвердить и перезапустить» ниже (прокси нужно будет перевести на новый порт).",
  "Saved — the nodes are learning the new address. Review, then Confirm & restart below (or Revert).":
    "Сохранено — ноды узнают новый адрес. Проверьте и нажмите «Подтвердить и перезапустить» ниже (или откатите).",
  "Preparing the new panel address…": "Готовим новый адрес панели…",
  "Saved & applying — the subscription server is restarting.":
    "Сохранено и применяется — сервер подписок перезапускается.",
  "Saved — the reverse proxy serves this URL; nothing to restart.":
    "Сохранено — этот адрес отдаёт прокси, перезапускать нечего.",
  "Opened the new address to confirm your proxy routes it here. If it loads there, the switch completes and nodes move over.":
    "Открыли новый адрес, чтобы убедиться, что прокси ведёт сюда. Откроется — переключение завершится и ноды перейдут.",
  "Done — the panel is now on the new port only.": "Готово — панель работает только на новом порту.",
  "Proceed — open the new address": "Дальше — открыть новый адрес",
  "Proceed — drop the old port": "Дальше — убрать старый порт",
  "Reverted — the panel stays on the current address.": "Откатили — панель осталась на текущем адресе.",
  "Checking the new address (dry-run)…": "Проверяем новый адрес (пробный прогон)…",
  "The panel couldn't verify the new address.": "Панель не смогла проверить новый адрес.",
  "Couldn't run the dry-run.": "Пробный прогон не запустился.",
  "(both changes below)": "(оба изменения ниже)",
  "•••••••• (set — leave blank to keep)": "•••••••• (задан — пусто = как есть)",
  "Zone:DNS:Edit token": "Токен Zone:DNS:Edit",
  "Zone:SSL and Certificates:Edit token": "Токен Zone:SSL and Certificates:Edit",
  "Port must be a number between 1 and 65535": "Порт должен быть числом от 1 до 65535",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Setup failed": "Настроить не удалось",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Reset failed": "Сбросить не удалось",
  "Set up encryption": "Настроить шифрование",
  "Show the key again — it never leaves your browser": "Показать ключ снова — он не покидает браузер",
  "Unlock the vault first to reveal its key": "Сначала откройте хранилище, чтобы увидеть ключ",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Unlock failed": "Открыть не удалось",
  "Migration failed": "Перенос не удался",
  "Encrypt remaining": "Зашифровать остальные",
  "Encrypt stored configs": "Зашифровать конфиги",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Couldn't start update": "Не удалось запустить обновление",
  "Enter your current password to confirm the change.": "Введите текущий пароль, чтобы подтвердить изменение.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Failed to save.": "Сохранить не удалось.",
  "Enabling interface-key escrow seals each server's interface key under your Encryption Vault key. Unlock it to apply.":
    "При включении ключ интерфейса каждого сервера запечатывается вашим ключом из хранилища. Откройте хранилище, чтобы применить.",
  "Enabling key escrow needs the Encryption Vault unlocked.": "Для включения нужно открыть хранилище ключей.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Couldn't update key escrow.": "Не удалось изменить хранение ключей.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Couldn't save block lists.": "Не удалось сохранить списки блокировок.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Couldn't update credentials.": "Не удалось изменить учётные данные.",
  "Saved. Reloading — sign in with your new credentials…": "Сохранено. Перезагружаем — войдите с новыми данными…",
  "the panel didn't respond. Nothing was lost; try again.": "панель не ответила. Ничего не потеряно, повторите.",
  "Heads up: changing a node's mesh subnet, interface prefix, or AWG params re-provisions its mesh links — it briefly drops off the mesh while every peer pulls the new config and reconnects.":
    "Учтите: смена подсети сети, префикса интерфейсов или параметров AWG пересоберёт подключения ноды — она ненадолго выпадет из сети, пока каждый сосед забирает новые настройки и переподключается.",
  "Routing lists — presets / custom": "Списки маршрутизации — готовые и свои",
  "Content filters — categories / lists": "Фильтры содержимого — категории и списки",
  "Authentication — panel credentials": "Вход — учётные данные панели",
  "Turn proxies — forks / colours / VK link": "Turn-прокси — сборки, цвета, ссылка VK",
  "Display — theme / status timing": "Вид — тема и время статусов",
  "System mesh defaults": "Умолчания системной сети",
  "mesh AWG params": "параметры AWG сети",
  "Geo lists will refresh on each node's next sync.": "Гео-списки обновятся при следующей синхронизации нод.",
  "Couldn't save the list.": "Не удалось сохранить список.",
  "Default — IP only. DNS not involved": "По умолчанию — только IP. DNS не при делах",
  "Matches by destination IP (GeoIP / ASN) — routing never depends on DNS, so your clients' DoH, DoT and plain DNS all keep working untouched. Simplest and most robust; it just can't separate services that share IPs (YouTube vs Google), and a CDN category catches everything behind it. Lists: GeoIP + Custom IPs.":
    "Смотрит на IP назначения (GeoIP, ASN) — маршрут никогда не зависит от DNS, поэтому DoH, DoT и обычный DNS у клиентов работают как работали. Самый простой и надёжный вариант; он лишь не разделяет службы с общими адресами (YouTube и Google), а категория CDN тянет за собой всё, что за ней. Списки: GeoIP и свои адреса.",
  "Force DNS — Host + IP. Overrides encrypted DNS": "Force DNS — домен и IP. Перебивает шифрованный DNS",
  "The node becomes your clients' resolver and blocks their encrypted DNS — both DoH (known providers) and all DoT — so it can route by hostname too, per-service precise. Trade-off: it sees and downgrades the client's DNS, can break a client that insists on its own encrypted DNS, and a DoH server it doesn't recognise can still slip past. Lists: GeoSite (host) + GeoIP + Custom IPs/domains.":
    "Сервер становится резолвером клиентов и закрывает их шифрованный DNS — и DoH известных провайдеров, и весь DoT — поэтому может вести трафик по именам, точно по службам. Взамен: он видит и понижает DNS клиента, ломает тех, кто держится за свой шифрованный DNS, а незнакомый сервер DoH всё равно проскочит. Списки: GeoSite (домены), GeoIP и свои адреса и домены.",
  "SNI Sniffer — Host + IP. DNS stays private": "Чтение SNI — домен и IP. DNS остаётся приватным",
  "Routes by hostname by reading the SNI from each TLS handshake, so your clients' DNS — DoH, DoT or plain — is never touched, observed or downgraded: the connection stays encrypted end-to-end. Learns each destination on its first connection (a brand-new host routes on the next one); names hidden by ECH, and QUIC / HTTP3, fall back to IP routing. Lists: GeoSite (host) + GeoIP + Custom IPs/domains.":
    "Ведёт трафик по именам, читая SNI из каждого рукопожатия TLS, поэтому DNS клиента — DoH, DoT или обычный — не трогается, не просматривается и не понижается: соединение остаётся зашифрованным до конца. Каждое назначение выучивается на первом подключении (совсем новое имя пойдёт правильно со второго); скрытые через ECH имена, а также QUIC и HTTP3 идут по адресам. Списки: GeoSite (домены), GeoIP и свои адреса и домены.",
  "Content filters": "Фильтры содержимого",
  "Routing lists": "Списки маршрутов",
  "Filtering runs on the entry node — where a client's tunnel lands. Exit and relay hops in a multi-hop path never see the client, so there's nothing there for them to filter.":
    "Фильтрация работает на входной ноде — там, где заканчивается туннель клиента. Выходные и промежуточные узлы клиента не видят, фильтровать им нечего.",
  "Routing runs on the entry node — where a client's tunnel lands. Exit and relay hops in a multi-hop path just forward what's already been steered.":
    "Маршрутизация работает на входной ноде — там, где заканчивается туннель клиента. Выходные и промежуточные узлы лишь передают то, что уже направлено.",
  "Disable all": "Выключить все",
  "Enable all": "Включить все",
  "Add preset list": "Готовый список",
  "Host-only — needs Force-DNS or SNI on this node": "Только по доменам — нужен Force-DNS или SNI на ноде",
  "Host-only — this node is IP-only": "Только домены — нода по IP",
  "Turn proxies are on": "Turn-прокси включены",
  "Turn proxies are off": "Turn-прокси выключены",
  "Self-contained WDTT server — owns its own WireGuard interface (not a WG/AWG front)":
    "Самостоятельный сервер WDTT — со своим интерфейсом WireGuard (не надстройка над WG/AWG)",
  "Works with WireGuard and AmneziaWG interfaces": "Работает с интерфейсами WireGuard и AmneziaWG",
  "Auto-updates are off — use “Check for updates” below to update manually.":
    "Автообновление выключено — обновляйте вручную кнопкой «Проверить обновления» ниже.",
  "The panel checks at this local time, on the chosen cadence.":
    "Панель проверяет в это местное время, с выбранной частотой.",
  "Content filters providers": "Поставщики фильтров",
  "Routing lists providers": "Поставщики списков",
  "On — presets are selectable": "Вкл — готовые списки доступны",
  "Enabled — its lists are selectable": "Включён — его списки доступны",
  "Off — its lists are hidden and deactivated on nodes": "Выкл — его списки скрыты и отключены на нодах",
  "When this provider's data was last pulled to the panel":
    "Когда данные этого поставщика в последний раз тянулись в панель",
  "No list from this provider has been routed yet — nothing pulled":
    "Ни один его список ещё не использовался — тянуть было нечего",
  "On — you can create custom lists": "Вкл — можно создавать свои списки",
  "Off — the Custom lists section is hidden": "Выкл — раздел своих списков скрыт",
  "On — its lists are selectable in Blocking": "Вкл — его списки доступны в блокировках",
  "Continuous mode ignores the time — nodes refresh whenever a list is older than the TTL.":
    "Непрерывный режим время не смотрит — ноды обновляют список, как только он старше срока.",
  "Nodes update at this local time, on the chosen cadence.":
    "Ноды обновляются в это местное время, с выбранной частотой.",
  "Update all lists now": "Обновить все списки",
  "Live tunnels and creation-time QRs are unaffected, but you won't be able to re-view a peer's QR/config later — you'd rotate its key and re-distribute.":
    "На живые туннели и QR при создании это не влияет, но посмотреть конфиг или QR пира позже не выйдет — придётся сменить ключ и раздать заново.",
  "Client configs are stored encrypted at rest (the server can't read the private keys) so a peer's QR stays re-viewable — you unlock it with your encryption key below. Requires the encryption key.":
    "Конфиги клиентов хранятся зашифрованными (сервер не читает приватные ключи), поэтому QR пира можно посмотреть снова — открыв его своим ключом ниже. Нужен ключ шифрования.",
  "Set default": "По умолчанию",
  "Edit list": "Правка списка",
  "New list": "Новый список",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Couldn't start setup.": "Не удалось начать настройку.",
  "That code isn't valid — try the current one.": "Код не подходит — введите текущий.",
  "Couldn't disable — check your password and code.": "Не удалось выключить — проверьте пароль и код.",
  "Set up two-factor": "Настроить вход по коду",
  "Give the user a name.": "Дайте пользователю имя.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "couldn't create user": "не удалось создать пользователя",
  "No peers assigned to this user yet.": "У этого пользователя пока нет пиров.",
  // budget-ok: an empty-state block — nothing beside it
  "No unassigned peers to add.": "Свободных пиров для добавления нет.",
  "Unassign from this user": "Отвязать от пользователя",
  "Assign to this user (keeps its key)": "Назначить (ключ сохранится)",
  "Add peers · {v1}": "Добавить пиры · {v1}",
  "Add peers": "Добавить пиры",
  "finding a free address…": "ищем свободный адрес…",
  "Full tunnel by default. Narrow for split tunnel.": "По умолчанию весь трафик. Сузьте для раздельного туннеля.",
  "Comma-separated IPs. Blank = no DNS line.": "Адреса через запятую. Пусто — строки DNS не будет.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Pick at least one target.": "Выберите хотя бы одно назначение.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "adding WDTT user…": "добавляем пользователя WDTT…",
  "generating key…": "создаём ключ…",
  "A target has an invalid address.": "У одного из назначений неверный адрес.",
  "Apply these changes?": "Применить изменения?",
  "This peer's private key isn't available here, so newly-added targets get the same key + PSK but a fresh QR / config can't be generated. Re-issue (rotate keys) for a downloadable config.":
    "Приватного ключа пира здесь нет, поэтому новые назначения получат тот же ключ и PSK, но свежий QR или конфиг не собрать. Нужен файл — перевыпустите пира со сменой ключей.",
  "store_configs is off, so the client's private key isn't kept — new targets get the same key + PSK, but a fresh QR can't be shown.":
    "store_configs выключен, приватный ключ клиента не хранится — новые назначения получат тот же ключ и PSK, но показать свежий QR не выйдет.",
  "Each address must be a valid IPv4.": "Каждый адрес должен быть верным IPv4.",
  "Expiry can't be later than the subscription's (": "Срок не может быть позже подписки (",
  "Saved (some changes couldn't be persisted).": "Сохранено (часть изменений записать не удалось).",
  "Peer updated.": "Пир обновлён.",
  "Link rotated — the old one no longer works.": "Ссылка сменена — прежняя больше не работает.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Rotate failed.": "Сменить не удалось.",
  "Keys rotated — send the user the new QR / config; the old one no longer works.":
    "Ключи сменены — отправьте пользователю новый QR или конфиг, прежний не работает.",
  "Pick a user to assign this peer to — the existing key and config are kept, applied when you Save.":
    "Выберите, кому назначить пира — ключ и конфиг сохранятся, применится при сохранении.",
  "Reassigning rotates the keys; you'll confirm on Save and the new user needs a fresh config.":
    "Передача другому меняет ключи; подтвердите при сохранении, новому владельцу нужен свежий конфиг.",
  "On Save you'll confirm unassigning — access is revoked and the keys rotate.":
    "При сохранении подтвердите отвязку — доступ пропадёт, ключи сменятся.",
  "On Save you'll confirm reassigning — the current user loses access for good and the new user needs a fresh config.":
    "При сохранении подтвердите передачу — прежний владелец теряет доступ навсегда, новому нужен свежий конфиг.",
  "Give the node a name.": "Дайте ноде имя.",
  "couldn't create node": "не удалось создать нода",
  "A label for this node — you can rename it anytime. The swatches set its colour per theme.":
    "Название ноды — переименовать можно когда угодно. Образцы задают цвет для каждой темы.",
  "Node created": "Нода создан",
  "New token": "Новый токен",
  "A label for this node — rename anytime, nothing else changes. The swatches set its colour per theme.":
    "Название ноды — переименование ничего больше не меняет. Образцы задают цвет для каждой темы.",
  "couldn't generate a recovery command": "не удалось собрать команду восстановления",
  // budget-ok: a note under the removal steps — its own block
  "No peers reference it.": "На него не ссылается ни один пир.",
  "the panel didn't respond in time": "панель не ответила вовремя",
  "The node is setting it up": "Нода его настраивает",
  "Queued — the node creates these one at a time": "В очереди — нода создаёт их по одному",
  "Listen IP is required.": "Нужен адрес прослушивания.",
  "Forward-to must be host:port.": "Пересылать нужно в виде хост:порт.",
  "Failed to save the title.": "Не удалось сохранить название.",
  "Random 64-hex key copied — paste it into the parameters":
    "Случайный ключ из 64 знаков скопирован — вставьте его в параметры",
  "Auto-filled for each real proxy — read-only": "Подставляется для каждого прокси — только чтение",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "This proxy's command — read-only": "Команда запуска этого прокси — только чтение",
  "Manual import — copy the link, then paste or scan it in the app":
    "Перенос вручную — скопируйте ссылку и вставьте или отсканируйте её в приложении",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Save failed": "Сохранить не удалось",
  "Version change requested — applies on each node's next sync.":
    "Смена версии запрошена — применится при следующей синхронизации.",
  "Failed to cancel.": "Отменить не удалось.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Failed to restart.": "Перезапустить не удалось.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Failed to stop.": "Остановить не удалось.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Failed to start.": "Запустить не удалось.",
  "Enter the absolute path to the .service unit.": "Укажите полный путь к файлу .service.",
  "WDTT fields aren't ready yet.": "Поля WDTT ещё не готовы.",
  "Forwards-to must be host:port.": "Пересылать нужно в виде хост:порт.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Turn-proxy install failed.": "Установить turn-прокси не удалось.",
  "No forks enabled — turn them on in Panel settings → Turn proxies.":
    "Ни одна сборка не включена — включите их в «Настройках панели → Turn-прокси».",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Interface must be wdtt0–wdtt999.": "Интерфейс должен быть от wdtt0 до wdtt999.",
  "Subnet must be an IPv4 CIDR (e.g. 10.66.66.1/24).": "Подсеть задаётся как IPv4 CIDR, например 10.66.66.1/24.",
  "The DTLS listen port and internal WG port must differ.": "Порт DTLS и внутренний порт WG должны различаться.",
  "creating WDTT server… (the node installs it on its next sync)":
    "создаём сервер WDTT… (сервер поставит его при следующей синхронизации)",
  "The DTLS port and the internal WG port must differ.": "Порт DTLS и внутренний порт WG должны различаться.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Restore failed.": "Восстановить не удалось.",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Recreating with a fresh identity — users must re-import.":
    "Пересоздаём с новыми ключами — пользователям придётся переносить заново.",
  "This server is being adopted — wait for the node to finish": "Сервер подключается — дождитесь окончания",
  // budget-ok: a message bar / notice — full width, wraps, nothing beside it
  "Action failed.": "Действие не выполнено.",
  "Display rendered": "Показать разобранным",
  "Display raw": "Как есть",
  "the interface didn't come up": "интерфейс не поднялся",
  "the interface didn't stop": "интерфейс не остановился",
  "didn't come back up": "не поднялся обратно",
  "Custom IP — e.g. 203.0.113.5": "Свой адрес — например 203.0.113.5",
  "Dark theme": "Тёмная тема",
  "Light theme": "Светлая тема",
  "Inbound links": "Входящие связи",
  "Mesh connections": "Связи сети",
  "Online users": "Кто в сети",
  "Updated user": "Изменён",
  "Created user": "Создан",
  "Updated peer": "Пир изменён",
  "Created peer": "Пир создан",
  "Subscription server": "Сервер подписок",
  "Network & TLS helper": "Помощник сети и TLS",
  "One-click self-update": "Обновление одной кнопкой",
  "Panel server": "Сервер панели",
  "AmneziaWG datapath": "Датапас AmneziaWG",
  "the subscription server isn’t installed — subscribers can’t load their configs":
    "сервер подписок не установлен — подписчики не получат свои конфиги",
  "the subscription server isn’t running — subscribers can’t load their configs":
    "сервер подписок не запущен — подписчики не получат свои конфиги",
  "the subscription server won’t start again after a reboot": "после перезагрузки сервер подписок сам не поднимется",
  "Panel URL and address changes can’t be applied until it’s restored":
    "«Адрес панели» и смену адреса не применить, пока он не восстановлен",
  "Panel URL and address changes can’t be applied right now":
    "«Адрес панели» и смену адреса сейчас применить нельзя",
  "the network helper won’t start again after a reboot": "после перезагрузки помощник сети сам не поднимется",
  "the one-click Update button won’t work (a manual update still will)":
    "кнопка «Обновить» работать не будет (обновление вручную — будет)",
  "the one-click Update button won’t work right now": "кнопка «Обновить» сейчас не сработает",
  "one-click self-update won’t arm again after a reboot":
    "после перезагрузки обновление одной кнопкой само не включится",
  "the panel won’t start again after a reboot": "после перезагрузки панель сама не поднимется",
  "the AmneziaWG kernel module isn’t built or loaded — awg interfaces can’t come up; running Update rebuilds it":
    "модуль ядра AmneziaWG не собран или не загружен — интерфейсы awg не поднимутся; «Обновить» пересоберёт его",
  // budget-ok: a note under the removal steps — its own block, wraps
  "{v1} reference it; {n} live only here and will be dropped.":
    "На него ссылаются {v1}; из них {n} живут только здесь и пропадут.",
  "{v1} reference it.": "На него ссылаются {v1}.",
  "Invalid targets: {list}": "Неверные назначения: {list}",
  "Invalid target: {list}": "Неверное назначение: {list}",
  "e.g. 1.1.1.1, 1.0.0.1": "например 1.1.1.1, 1.0.0.1",
  "This reconfigures the interface on the node. Existing peers will NOT be able to connect using their old configs — you'll need to re-issue and re-distribute the QR codes. The interface's keys and peers are kept.":
    "Интерфейс на ноде будет перенастроен. Прежние конфиги пиров работать НЕ будут — QR придётся перевыпустить и раздать заново. Ключи интерфейса и сами пиры сохранятся.",
  "VK links cleared.": "Ссылки VK удалены.",
  "This list has no routable records": "В списке нет записей для маршрутов",
  "ON — the node remembers each learned IP": "ВКЛ — нода запоминает каждый выученный адрес",
  "Ignored — the panel isn't managing it. Open to Un-ignore or Adopt.":
    "Скрыт — панель им не управляет. Откройте, чтобы вернуть или подключить.",
  "Type not established — you choose it when adopting": "Тип не определён — выберете при подключении",
  "Mechanism blocking": "По механизмам",
  "Couldn't verify {v1} answers yet — it may still be warming up. You can open it to confirm, but if it doesn't load, cancel (nothing is committed until it answers).":
    "Пока не удалось проверить, отвечает ли {v1} — возможно, он ещё прогревается. Можете открыть его для подтверждения, а если не откроется — отмените (ничего не применится, пока он не ответит).",
  "Cloudflare's proxy only reaches origin HTTPS on {ports}.":
    "Прокси Cloudflare ходит на HTTPS источника только по портам {ports}.",
  "A cf15 origin certificate is only valid behind Cloudflare, so this port won't work — pick one of those.":
    "Сертификат cf15 действителен только за Cloudflare, поэтому этот порт не подойдёт — выберите один из указанных.",
  "If it IS behind Cloudflare, restrict this port to Cloudflare's IP ranges:":
    "Если панель всё-таки за Cloudflare, откройте этот порт только для адресов Cloudflare:",
  "Setting up…": "Настраиваем…",
  "Updating…": "Обновляем…",
  "Auto (public IP)": "Авто (внешний IP)",
  "WDTT server": "Сервер WDTT",
  "not a valid IPv4 address": "неверный адрес IPv4",
  "You've unchecked every interface, so there's nothing left to deploy this peer to — saving will completely delete it. Its access is revoked everywhere and its config / QR stops working. This action is irreversible. Are you sure you want to continue?":
    "Вы сняли отметки со всех интерфейсов, разворачивать пира больше некуда — при сохранении он будет удалён совсем. Доступ пропадёт везде, конфиг и QR перестанут работать. Отменить это нельзя. Продолжаем?",
  "Peer targets": "Назначения пира",
  "Opens the app automatically": "Открывает приложение само",
  "Adopt turn-proxy": "Принять turn-прокси",
  "This rewrites every user's link — the endpoint and DTLS port are part of it. Existing users must re-import from their subscription page. The server key and users are kept; the server briefly reconnects.":
    "Ссылки всех пользователей изменятся — адрес и порт DTLS входят в них. Придётся перенести конфиг заново со страницы подписки. Ключ сервера и пользователи сохранятся, сервер ненадолго переподключится.",
  "This rewrites every user's link — the internal WG port is part of it. Existing users must re-import from their subscription page. The server key and users are kept; the server briefly reconnects.":
    "Ссылки всех пользователей изменятся — внутренний порт WG входит в них. Придётся перенести конфиг заново со страницы подписки. Ключ сервера и пользователи сохранятся, сервер ненадолго переподключится.",
  "Detected *{v1}*{v2} — change only if wrong": "Это *{v1}*{v2} — меняйте, если неверно",
  "Pick the fork this server runs": "Укажите, какая сборка здесь работает",
  "Scrape config": "конфиг сбора",
  "generating…": "создаём…",
  "deleting…": "удаляем…",
  "interface {v1} is down — {v2}": "интерфейс {v1} не работает — {v2}",
  "missing on every server": "нет ни на одном сервере",
  "missing on some live servers": "нет на части живых серверов",
  "created — not seen on a node yet": "создан — на ноде ещё не виден",
  "reaching the server but the handshake never completes — likely DPI / MTU / wrong {v1} params":
    "до сервера доходит, но рукопожатие не завершается — похоже на DPI, MTU или неверные параметры {v1}",
  "this peer's access date has passed": "срок доступа этого пира истёк",
  "the subscription's access date has passed": "срок доступа по подписке истёк",
  "Where the panel itself is reached.": "По этому адресу открывается сама панель.",
  " Your proxy fronts this URL and forwards to the internal address below — the two are independent.":
    " Этот адрес отдаёт ваш прокси, а дальше идёт на внутренний адрес ниже — они независимы.",
  "Where the swg-sub page is reached (a separate service; changing it only restarts swg-sub).":
    "По этому адресу открывается страница подписок (это отдельная служба; смена перезапустит только swg-sub).",
  "Two-factor authentication": "Двухфакторный вход",
  "missing on some servers": "нет на части серверов",
  "handshake never completes": "рукопожатие не проходит",
  "no inbound data flowing": "входящих данных нет",
  "vault blob failed its integrity check": "хранилище не прошло проверку целостности",
  "no encryption key for this user": "у пользователя нет ключа шифрования",
  "no subscription for this user": "у этого пользователя нет подписки",
  "the action failed on the node": "действие не выполнилось на ноде",
  "no rules yet": "правил пока нет",
  "endpoint and listen port": "адрес и порт",
  "the selected user": "выбранному",
  "no routable records": "нет записей маршрутов",
  "this node": "эта нода",
  "no snapshot yet": "снапшота пока нет",
  "no health data reported": "данных о состоянии нет",
  "fleet nodes not shown": "ноды флота не показаны",
  "by list size": "по размеру",
  "on a stale server": "на молчащем сервере",
  "the new address": "новый адрес",
  "the panel": "панель",
  "the subscription server": "сервер подписок",
  "the old and new address": "старый и новый адрес",
  "the change": "изменение",
  "this mode": "этот режим",
  "this peer": "этот пир",
  "the user": "пользователь",
  "no free address": "нет свободных",
  "service is not running on the node": "служба на ноде не запущена",
  "no peers online": "пиров в сети нет",
  "no one online": "никого в сети",
  // budget-ok: the app-bar tabs — measured in the real header, not estimated (see below)
  "nav|Overview": "Обзор",
  "nav|Live": "Онлайн",
  "nav|Users": "Пользователи",
  "nav|Nodes": "Ноды",
  "nav|Peers": "Пиры",
  "How this panel is deployed": "Как развёрнута эта панель",
  "Lock encryption key": "Запереть ключ шифрования",
  "Language": "Язык",
  "Theme": "Тема",
  "Panel settings": "Настройки панели",
  // lowercase state/label tags — the vocabulary mirrors status|… and ifop|… above
  "tag|missing": "пропал",
  "tag|ghost": "призрак",
  "tag|stopped": "остановлен",
  "tag|down": "лежит",
  "tag|gone": "исчез",
  "tag|starting": "запуск",
  "tag|restarting": "перезапуск",
  "tag|restoring": "возврат",
  "tag|converting": "конвертация",
  "tag|modified": "изменён",
  "tag|ready": "готов",
  "tag|running": "работает",
  "tag|paused": "пауза",
  "tag|present": "есть",
  "tag|adopting": "подключение",
  "tag|uninstalled": "удалён",
  "tag|offline": "не на связи",
  "tag|recover": "вернуть",
  "tag|re-provisioning": "пересборка",
  "tag|flagged for removal": "помечен к удалению",
  "tag|restarted": "перезапущен",
  "tag|pending": "ожидает",
  "tag|unsaved": "не сохр.",
  "tag|orphan": "чужой",
  "tag|unassigned": "свободен",
  "val|total": "всего",
  "val|online": "в сети",
  "tag|direct": "напрямую",
  "tag|cascade": "каскад",
  "tag|smart": "умный",
  "tag|custom": "свой",
  "tag|heavy": "тяжёлый",
  "tag|restricted": "фильтр",
  "tag|faulty": "сбой",
  "tag|untitled": "без имени",
  "val|auto": "авто",
  "tag|unbound": "не привязан",
  // ── csqtt (amurcanov's Rust rewrite of WDTT — self-contained raw-TUN VK-turn server) ──
  "csqtt interface name must be csqtt0–csqtt9999.": "Интерфейс csqtt называется от csqtt0 до csqtt9999.",
  "csqtt needs a /24 tunnel subnet, e.g. 10.66.67.0/24.": "csqtt нужна подсеть туннеля /24, например 10.66.67.0/24.",
  "Max passwords must be a number.": "Максимум паролей должен быть числом.",
  "What clients dial (over the VK relay)": "Куда звонят клиенты (через реле VK)",
  "UDP DTLS listen (outside)": "Приём UDP DTLS (снаружи)",
  "Max users": "Максимум пользователей",
  "Cap on simultaneous access passwords · blank = 500": "Предел одновременных паролей доступа · пусто = 500",
  "a csqtt proxy": "прокси csqtt",
  " (CSQTT)": " (CSQTT)",
  " (CSQTT, starting)": " (CSQTT, запускается)",
  "csqtt link unavailable — the server isn't reporting yet.": "Ссылка csqtt недоступна — сервер ещё не отчитался.",
  "csqtt · keyless (server-minted address)": "csqtt · без ключей (адрес выдаёт сервер)",
  "csqtt link copied": "Ссылка csqtt скопирована",
  "Open the csqtt server — details and settings": "Открыть сервер csqtt — детали и настройки",
  "The node brings it up on its next sync": "Нода поднимет его на следующей синхронизации",
  "waiting for the node to bring it up…": "ждём, пока нода поднимет его…",
  "Edit csqtt server · {v1}": "Изменить сервер csqtt · {v1}",
  "{v1} CSQTT": "{v1} CSQTT",
  "Self-contained csqtt server — owns its own raw-TUN interface (not a WG/AWG front)":
    "Самодостаточный сервер csqtt — владеет своим raw-TUN интерфейсом (не надстройка над WG/AWG)",
  "The server assigns the address on connect": "Адрес назначает сервер при подключении",
  "adding csqtt user…": "добавляем пользователя csqtt…",
  "csqtt user added — their connect link is on the assigned subscription.":
    "Пользователь csqtt добавлен — ссылка для подключения на назначенной подписке.",
  "csqtt server — the panel mints this user's access password and csqtt mints their address on connect, so there's no key or client config to set here. The user's VK link (from their subscription) is the TURN credential.":
    "Сервер csqtt — панель выпускает пароль доступа этого пользователя, а csqtt выдаёт адрес при подключении, поэтому здесь нечего задавать: ни ключа, ни клиентского конфига. Учётные данные TURN — это ссылка VK пользователя (с его подписки).",
  "A fresh access password is generated. The current csqtt link stops working — send the user their new link (from the subscription page) to re-import.":
    "Будет выпущен новый пароль доступа. Текущая ссылка csqtt перестанет работать — отправьте пользователю новую (со страницы подписки), чтобы он переимпортировал.",
  "csqtt assigns the address on connect": "Адрес назначает csqtt при подключении",
  "csqtt servers this user reaches. csqtt assigns each server's address on connect; the user's link per server is on their subscription. No client config (key/DNS/MTU) — csqtt owns the datapath.":
    "Серверы csqtt, до которых достаёт этот пользователь. Адрес на каждом сервере csqtt выдаёт при подключении; ссылка на каждый сервер — на подписке пользователя. Клиентского конфига (ключ/DNS/MTU) нет — трактом владеет csqtt.",
  "csqtt fields aren't ready yet.": "Поля csqtt ещё не готовы.",
  "Interface must be csqtt0–csqtt9999.": "Интерфейс должен быть от csqtt0 до csqtt9999.",
  "Subnet must be an IPv4 /24 CIDR (e.g. 10.66.67.1/24).": "Подсеть должна быть IPv4 /24 CIDR (например 10.66.67.1/24).",
  "creating csqtt server… (the node installs it on its next sync)":
    "создаём сервер csqtt… (нода установит его на следующей синхронизации)",
  "csqtt server requested — the node installs it on its next sync. Add users from Peers.":
    "Сервер csqtt заказан — нода установит его на следующей синхронизации. Пользователей добавляйте на вкладке «Пиры».",
  "Built-in raw-IP tunnel": "Встроенный raw-IP туннель",
  "csqtt owns its own raw-IP TUN interface — users attach to it directly (no forwards-to). It mints each user's address on connect; add + manage users from Peers.":
    "csqtt владеет своим raw-IP TUN интерфейсом — пользователи подключаются прямо к нему (никуда не перенаправляет). Адрес каждому он выдаёт при подключении; добавляйте и ведите пользователей на вкладке «Пиры».",
  "Auto-assigned to avoid collisions with this node's other servers, interfaces, and ports. /24 only.":
    "Назначается автоматически, чтобы не столкнуться с другими серверами, интерфейсами и портами этой ноды. Только /24.",
  "Connected to this csqtt server": "Подключены к этому серверу csqtt",
  "CSQTT fork": "Форк CSQTT",
  "Bring this csqtt server up on the node": "Поднять этот сервер csqtt на ноде",
  "Take this csqtt server down (stays down until started)": "Остановить этот сервер csqtt (не поднимется, пока не запустите)",
  "Bounce this csqtt server on the node": "Перезапустить этот сервер csqtt на ноде",
  "— self-contained (its own raw-IP tunnel)": "— самодостаточный (свой raw-IP туннель)",
  "Extra command-line flags for this csqtt server. It's self-contained — its real config lives per interface — so there's little here beyond advanced flags.":
    "Дополнительные флаги командной строки для этого сервера csqtt. Он самодостаточен — его настоящая конфигурация живёт на каждом интерфейсе — поэтому здесь почти ничего нет, кроме продвинутых флагов.",
  "csqtt server removed — the node tears it down on its next sync.":
    "Сервер csqtt удалён — нода снесёт его на следующей синхронизации.",
  "Delete csqtt server · {v1}": "Удалить сервер csqtt · {v1}",
  "Delete server": "Удалить сервер",
  "This removes the *{iface}* csqtt server and *unassigns + deletes* every user on it — their credential is a password on this server, so it means nothing once the server is gone. Type *{iface}* to confirm.":
    "Это удалит сервер csqtt *{iface}* и *отвяжет и удалит* всех его пользователей — их учётные данные это пароль на этом сервере, а без сервера он ничего не значит. Введите *{iface}* для подтверждения.",
  "Type the interface name to confirm": "Введите имя интерфейса для подтверждения",
  "Edit csqtt interface · {v1}": "Изменить интерфейс csqtt · {v1}",
  "*csqtt* owns its own raw-IP tunnel *({iface} · {addr})* and mints each user's address on connect.":
    "*csqtt* владеет своим raw-IP туннелем *({iface} · {addr})* и выдаёт адрес каждому пользователю при подключении.",
  "CSQTT fork: {v1}": "Форк CSQTT: {v1}",

  // ── what a peer publishes to its subscription (the clickable protocol tags) ──
  "Published to the subscription — click to hide it": "Публикуется в подписке — нажмите, чтобы скрыть",
  "Hidden from the subscription — click to publish it again": "Скрыто из подписки — нажмите, чтобы снова опубликовать",
  "This is the last kind of config this peer publishes — a subscription can't be empty.":
    "Это последний вид конфига, который публикует этот пир — подписка не может быть пустой.",
  "A peer has to publish at least one kind of config — keep one selected.":
    "Пир должен публиковать хотя бы один вид конфига — оставьте один выбранным.",

  "RAW-IP port — no WireGuard, no forward secrecy": "RAW-IP порт — без WireGuard, без прямой секретности",
  "This server is using port {v1} itself — move its listen or internal WG port before turning RAW on.":
    "Этот сервер сам занимает порт {v1} — сначала перенесите его порт приёма или внутренний порт WG, потом включайте RAW.",
  "RAW-IP moved from {v1} to {v2} — one raw listener per address.":
    "RAW-IP перенесён с {v1} на {v2} — на один адрес приходится один raw-слушатель.",
  "Move RAW-IP to this server?": "Перенести RAW-IP на этот сервер?",
  "Move RAW here": "Перенести RAW сюда",
  "*{holder}* offers RAW-IP on this address today. The app dials one fixed port for every server, so an address can only run one raw listener — turning it on here turns it off on *{holder}*. Its users keep their links and fall back to WireGuard mode. Servers on this node's other IPs are untouched.":
    "Сейчас RAW-IP на этом адресе отдаёт *{holder}*. Приложение стучится на один и тот же порт для всех серверов, поэтому на адресе может работать только один raw-слушатель — включив его здесь, вы выключите его на *{holder}*. Ссылки его пользователей останутся рабочими, они вернутся в режим WireGuard. Серверы на других IP этой ноды не затрагиваются.",
  "port {v1}": "порт {v1}",
  "The user switches connection mode to *raw* in the app — nothing else. The port isn't theirs to set: the app dials *{v1}* for every server and no link or subscription can carry another one, which is why the panel fixes it. Their link keeps working for WireGuard mode.":
    "Пользователю остаётся переключить режим соединения на *raw* — и всё. Порт задавать не ему: приложение стучится на *{v1}* для всех серверов, и никакая ссылка или подписка другой порт не передаёт — поэтому панель фиксирует его. Ссылка продолжит работать в режиме WireGuard.",
  "*{v1}* offers RAW on this address today. One address can only run one raw listener, so saving moves it here and turns it off there.":
    "Сейчас RAW на этом адресе отдаёт *{v1}*. На адресе может работать только один raw-слушатель, поэтому сохранение перенесёт его сюда и выключит там.",
  "Internal WireGuard port": "Внутренний порт WireGuard",
  "The internal WG port must be a number.": "Внутренний порт WG должен быть числом.",
  "Where the DTLS half forwards, on loopback. No client dials it and no link carries it, so changing it only restarts the server — but it must not sit on the RAW port.":
    "Куда DTLS-половина переправляет трафик, по локальной петле. Ни один клиент туда не стучится и ни одна ссылка его не передаёт, поэтому смена порта лишь перезапускает сервер — но занимать порт RAW он не должен.",
  "Adopt csqtt server · {v1}": "Принять сервер csqtt · {v1}",
  "Adopt this csqtt server — its users are kept and imported": "Принять этот сервер csqtt — его пользователи сохранятся и будут импортированы",
  "Adopting — the node takes it over on the next sync and its users keep connecting.":
    "Принимаем — нода заберёт его на следующей синхронизации, и его пользователи продолжат подключаться.",
  "Its *users are kept* — the panel takes the server over on its own address and port, keeps serving every password it already had, and imports each one as a peer you can see and manage.":
    "Его *пользователи сохранятся* — панель заберёт сервер на его же адресе и порту, продолжит обслуживать все выданные им пароли и импортирует каждого как пира, которого вы видите и которым управляете.",
  "Its *{count}* come across on adopt — each becomes an unassigned peer you can hand to a user.":
    "Его *{count}* перейдут при приёме — каждый станет непривязанным пиром, которого можно выдать пользователю.",
  "The running server is stopped and ours starts in its place, on the same port — clients reconnect within seconds.":
    "Работающий сервер будет остановлен, а наш поднимется на его месте, на том же порту — клиенты переподключатся за секунды.",
  "A csqtt server is adopted from its card on the node page — the node finds it and offers it there.":
    "Сервер csqtt принимается со своей карточки на странице ноды — нода находит его и предлагает там.",
  "RAW needs port {v1} and {v2} is using it on this node — move that first":
    "RAW нужен порт {v1}, а его занимает {v2} на этой ноде — сначала перенесите его",
  "this server would need port {v1} for RAW, but it is already using it — move its listen or internal WG port first":
    "Этому серверу нужен порт {v1} для RAW, но он сам его занимает — сначала перенесите его порт приёма или внутренний порт WG",
  "{v1} has no RAW-IP mode — it is a qWDTT feature": "У {v1} нет режима RAW-IP — это возможность qWDTT",
  "no csqtt instance '{v1}' on node {v2}": "на ноде {v2} нет экземпляра csqtt «{v1}»",
  "this node already manages a csqtt instance on {v1}": "эта нода уже управляет экземпляром csqtt на {v1}",
  "this node doesn't report a csqtt server on {v1} — refresh and try again":
    "эта нода не сообщает о сервере csqtt на {v1} — обновите и попробуйте снова",
  "this server's tunnel subnet isn't an IPv4 /24: {v1}": "подсеть туннеля этого сервера не IPv4 /24: {v1}",
  "unknown csqtt fork: {v1}": "неизвестный форк csqtt: {v1}",
  "this node has no endpoint address yet, so clients would have nothing to dial — set the node's endpoint host, or pass one with the adopt":
    "у этой ноды ещё нет адреса подключения, клиентам будет некуда стучаться — задайте адрес ноды или передайте его при приёме",
  "Turn-proxy": "Turn-прокси",
  "RAW mode on": "RAW включён",
  "Extra flags": "Дополнительные флаги",
  "val|none": "нет",
  "tag|advanced": "подробно",
  // ── RAW-IP mode (qWDTT): a second listener that trades WireGuard for throughput ──────────────
  "RAW-IP mode": "Режим RAW-IP",
  "Accept RAW connections": "Принимать RAW-подключения",
  "RAW drops WireGuard's handshake: *no forward secrecy and no replay protection*. Anyone who later learns a peer's password can read traffic they recorded earlier. Turn it on for people who need the speed and accept that.": "RAW убирает рукопожатие WireGuard: *нет forward secrecy и защиты от повтора*. Тот, кто потом узнает пароль пира, прочитает записанный ранее трафик. Включайте для тех, кому нужна скорость и кого это устраивает.",
  "RAW available · port {v1} · an app setting, not part of the link": "Доступен RAW · порт {v1} · настройка приложения, не часть ссылки",
  "The app keeps the RAW port and the connection mode in its own settings, not in a profile — so they are set once, by hand, and apply to every server.": "Приложение хранит RAW-порт и режим подключения в своих настройках, а не в профиле — они задаются один раз вручную и действуют для всех серверов.",
  "The node refused to install WDTT server {iface}: {err}": "Узел отказался устанавливать WDTT-сервер {iface}: {err}",
  "This server was never installed — remove it or fix the cause": "Этот сервер так и не был установлен — удалите его или устраните причину",
  "Remove this WDTT server from the panel": "Удалить этот WDTT-сервер из панели",
  "no build published yet": "сборка ещё не опубликована",
  "The node refused to install this server, so it was never created: *{err}*. Fix that and create it again, or remove it — there is no identity to restore and nothing to recreate.": "Узел отказался устанавливать этот сервер, поэтому он так и не был создан: *{err}*. Устраните причину и создайте заново — либо удалите: восстанавливать нечего, пересоздавать тоже.",
  "Remove this server": "Удалить сервер",
  "*No identity is escrowed for it*, so it can only come back with a new key — every user re-imports.": "*Личность сервера не депонирована*, поэтому он вернётся только с новым ключом — всем пользователям придётся переимпортировать.",
  "No published build for {v1} yet, so a node has nothing to install. Pick another fork.": "Для {v1} ещё нет опубликованной сборки — узлу нечего устанавливать. Выберите другой форк.",
  "Which csqtt server implements this instance": "Какой csqtt-сервер реализует этот инстанс",
  "CSQTT proxy": "CSQTT-прокси",
  "Enable RAW on new servers": "Включать RAW на новых серверах",
  "New servers start with RAW on": "Новые серверы стартуют с включённым RAW",
  "New servers start with RAW off": "Новые серверы стартуют с выключенным RAW",
  "Forks that offer it (qWDTT today) carry a second, WireGuard-free listener that is roughly *6x* faster through the same VK relay. The server keeps its normal WireGuard listener either way, so each user picks per device — but RAW has *no forward secrecy and no replay protection*. This only sets what a NEWLY created server starts with; every server can be switched afterwards.": "Форки, где он есть (сегодня — qWDTT), поднимают второй слушатель без WireGuard: примерно в *6 раз* быстрее через то же VK-реле. Обычный WireGuard-слушатель остаётся в любом случае, так что пользователь выбирает режим на каждом устройстве — но у RAW *нет forward secrecy и защиты от повтора*. Настройка задаёт только состояние НОВОГО сервера; на каждом сервере режим потом переключается.",
  "row|kind": "тип",
  "row|endpoint": "адрес",
  "row|address": "адрес в ВПН",
  "row|status": "статус",
  "row|handshake": "рукопожатие",
  "row|rate": "скорость",
  "row|transport": "транспорт",
  "val|server": "сервер",
  "val|core": "ядро",
  "val|with": "с",
  "val|orange": "оранжевым",
  "val|turn": "turn",
  "{v1} online": "{v1} в сети",
  "{v1} peers": "{v1} пиров",
  "{v1} static": "{v1} статич.",
  "Adopt {v1}": "Принять {v1}",
  "{v1} — start managing it from the panel": "{v1} — начать управлять из панели",
  "Adopt WDTT install · {v1}": "Подключить установку WDTT · {v1}",
  "Adopt interface · {v1}": "Подключить интерфейс · {v1}",
  "down on the node — {v1}": "не работает на ноде — {v1}",
  "Publish port · {v1}": "Опубликовать порт · {v1}",
  "Recreating {v1} gives its {v2} brand-new keys once it's back. Unlock your encryption key now so each fresh config is captured the moment it's rekeyed — then it stays re-viewable in the panel and is served on the users' subscription pages.":
    "После пересоздания {v1} его {v2} получат совершенно новые ключи. Откройте ключ шифрования сейчас, чтобы каждый свежий конфиг сохранился сразу при смене ключей — тогда его можно будет посмотреть в панели, и он попадёт на страницы подписок.",
  "Recreating {v1} — keep this tab open and its 1 peer is rekeyed automatically once it's back; otherwise rekey it from its peer view. Then hand out the fresh config.":
    "Пересоздаём {v1} — не закрывайте вкладку, и единственному пиру ключи сменятся сами, когда интерфейс поднимется; иначе смените их вручную на странице пира. Потом раздайте свежий конфиг.",
  "Recreating {v1} — keep this tab open and its {v2} are rekeyed automatically once it's back; otherwise rekey each from its peer view. Then hand out the fresh configs.":
    "Пересоздаём {v1} — не закрывайте вкладку, и его {v2} получат новые ключи сами, когда интерфейс поднимется; иначе смените их вручную на странице каждого пира. Потом раздайте свежие конфиги.",
  "An interface named {v1} already exists on this node.": "Интерфейс с именем {v1} на этой ноде уже есть.",
  "{v1} is already on this node but isn't managed by the panel — Adopt it instead (its keys and users are kept).":
    "{v1} на ноде уже есть, но панель им не управляет — лучше подключите его (ключи и пользователи сохранятся).",
  "DELETE {v1}": "DELETE {v1}",
  "Delete interface · {v1}": "Удалить интерфейс · {v1}",
  "Connection to {v1}": "Связь с {v1}",
  "{v1} isn't reporting — reconnect it before changing this link":
    "{v1} не отвечает — верните связь, прежде чем менять это соединение",
  "{v1} ago": "{v1} назад",
  "Auto ({v1}'s ingress)": "Авто (вход {v1})",
  "Edit {v1} interface · {v2}": "Правка интерфейса {v1} · {v2}",
  "{v1} hasn't reported {v2} yet": "{v1} ещё не сообщила про {v2}",
  "Subscription expired on {v1}": "Подписка истекла {v1}",
  "Subscription is about to expire on {v1}": "Подписка истекает {v1}",
  "Subscription is active until {v1}": "Подписка активна до {v1}",
  "Peer expired on {v1}": "Пир истёк {v1}",
  "Peer is about to expire on {v1}": "Пир истекает {v1}",
  "Peer is active until {v1}": "Пир активен до {v1}",
  "User expired on {v1}": "Пользователь истёк {v1}",
  "User is about to expire on {v1}": "Пользователь истекает {v1}",
  "{v1} gets a fresh QR / config that must be re-distributed.":
    "{v1} получит свежий QR и конфиг — их нужно раздать заново.",
  "Peer .{v1}": "Пир .{v1}",
  "Peer": "Пир",
  "Expiry set to {v1}": "Срок задан: {v1}",
  "{v1} configs)": "{v1} конфигов)",
  "Edit · {v1}": "Правка · {v1}",
  "Turn configs · {v1}": "Конфиги turn · {v1}",
  "val|peer": "пир",
  "WDTT client apps · {v1}": "Клиенты WDTT · {v1}",
  "Geolocation: {v1}": "Геолокация: {v1}",
  "TLD .{v1}": "Домен .{v1}",
  "Reset routing · {v1}": "Сброс маршрутов · {v1}",
  "{v1} routed": "{v1} направлено",
  "{v1} rerouted": "{v1} перенаправл.",
  "IP learning is {v1} · click to turn it {v2}": "Запоминание адресов: {v1} · нажмите, чтобы {v2}",
  "val|off": "выкл",
  "val|on": "вкл",
  "Search {v1} lists — name, country, service…": "Поиск среди {v1} списков — имя, страна, сервис…",
  "Switch {v1} to Force-DNS mode?\n\nThis reprovisions the node (adds its DNS resolver) so domain rules can match. IP rules keep working. Save your rule changes afterwards.":
    "Перевести {v1} в режим Force-DNS?\n\nНода будет перенастроена (добавится её DNS-резолвер), чтобы срабатывали правила по доменам. Правила по адресам продолжат работать. Изменения правил сохраните после этого.",
  "resolving…": "определяем…",
  "→ {v1}": "→ {v1}",
  "Cascade — exits via {v1}": "Каскад — выход через {v1}",
  "Cascade: relays {v1} out via {v2}": "Каскад: выводит {v1} через {v2}",
  "{v1} interfaces": "{v1} интерфейсов",
  "Looks like {v1} — {v2}": "Похоже на {v1} — {v2}",
  "Edit WDTT server · {v1}": "Правка сервера WDTT · {v1}",
  "Exits via {v1}": "Выход через {v1}",
  "{v1} destination rule(s)": "правил назначения: {v1}",
  "Edit interface · {v1}": "Правка интерфейса · {v1}",
  "interface is down on the node — awg-quick couldn't bring it up: {v1}":
    "интерфейс на ноде не работает — awg-quick не смог его поднять: {v1}",
  "{v1} unmanaged (orphan)": "{v1} без владельца (чужие)",
  " (peak {v1}%)": " (пик {v1}%)",
  "CPU {v1}%": "CPU {v1}%",
  "1 {v1} saturated{v2}": "1 {v1} под нагрузкой{v2}",
  "All {v1} saturated{v2}": "Все {v1} под нагрузкой{v2}",
  "{v1} of {v2} {v3} saturated{v4}": "{v1} из {v2} {v3} под нагрузкой{v4}",
  " · load {v1}": " · нагрузка {v1}",
  " · iowait {v1}%": " · ждёт диск {v1}%",
  "{v1} saturated": "{v1} под нагрузкой",
  "{v1} can be repaired — click “Fix”": "{v1} можно починить — нажмите «Починить»",
  "stale · {v1}": "молчит · {v1}",
  "{v1} WireGuard": "{v1} WireGuard",
  "{v1} AmneziaWG": "{v1} AmneziaWG",
  "{v1} WDTT": "{v1} WDTT",
  "{v1} {v2}": "{v1} {v2}",
  "Other {v1}": "Ещё {v1}",
  "{v1} needs attention": "{v1} требует внимания",
  "{v1} IPs": "{v1} адресов",
  "{v1} dom": "{v1} доменов",
  "{v1} sites": "{v1} сайтов",
  "packets · {v1} · {v2}": "пакетов · {v1} · {v2}",
  "packets · {v1}": "пакетов · {v1}",
  "none {v1}": "ничего {v1}",
  "connections · {v1}": "соединений · {v1}",
  "Delivered — HTTP {v1}": "Доставлено — HTTP {v1}",
  "Delivery failed: {v1}": "Доставить не удалось: {v1}",
  "val|unreachable": "недоступен",
  "Panel: {v1}": "Панель: {v1}",
  "Subscriptions: {v1}": "Подписки: {v1}",
  "{v1} No panel change was applied — settings rolled back.": "{v1} Настройки панели не менялись — всё откатили.",
  "Saved — the panel now serves {v1}. Update your reverse proxy, then confirm below.":
    "Сохранено — панель теперь отдаёт {v1}. Перенастройте прокси и подтвердите ниже.",
  "Restarting the panel container. Reconnect at {v1} once it's back.":
    "Перезапускаем контейнер панели. Как поднимется — зайдите по {v1}.",
  "Update requested on {v1} — each node applies it on its next sync.":
    "Обновление запрошено: {v1} — каждая нода применит его при следующей синхронизации.",
  "Couldn't save {v1}": "Не сохранилось {v1}",
  "Couldn't save — {v1}": "Не сохранилось — {v1}",
  "Client configs → {v1}": "Конфиги клиентов → {v1}",
  "val|encrypted": "шифруются",
  "IP learning → {v1}": "Память адресов → {v1}",
  "ingress IP → {v1}": "адрес входа → {v1}",
  "mesh subnet → {v1}": "подсеть сети → {v1}",
  "mesh port → {v1}": "порт сети → {v1}",
  "prefix → {v1}": "префикс → {v1}",
  "egress IP → {v1}": "адрес выхода → {v1}",
  "panel IP → {v1}": "адрес панели → {v1}",
  "val|default": "по умолчанию",
  "Pull this list on {v1}": "Тянуть этот список на {v1}",
  "Enable on {v1}": "Включить на {v1}",
  // budget-ok: a tooltip — its own bubble, wraps
  "No IP list here — can't enforce in {v1}. Add an IP list, or use Force-DNS / Hybrid-SNI.":
    "Здесь нет списка адресов — в режиме {v1} применить нечего. Добавьте список адресов или включите Force-DNS / Hybrid-SNI.",
  "Filter on {v1}": "Фильтр на {v1}",
  "domains in this list": "доменов в списке",
  "IP ranges in this list": "диапазонов адресов в списке",
  "Offer {v1}": "Давать {v1}",
  "{v1} in the install picker": "{v1} в выборе при установке",
  "Colour for {v1}": "Цвет для {v1}",
  "{v1} is WireGuard-only — its client can't front an AmneziaWG interface":
    "{v1} работает только с WireGuard — его клиент не встанет перед интерфейсом AmneziaWG",
  "Update every deployed {v1} proxy to {v2}": "Обновить все развёрнутые прокси {v1} до {v2}",
  "Server-flag defaults for {v1} (pre-fill new proxies)": "Флаги по умолчанию для {v1} (подставятся новым прокси)",
  "{v1} tag colour": "Цвет метки {v1}",
  "Open {v1}": "Открыть {v1}",
  "{v1} on GitHub": "{v1} на GitHub",
  "{v1}-day TTL)": "срок {v1} дн.)",
  "not a valid IP, CIDR or domain: {v1}": "не адрес, не CIDR и не домен: {v1}",
  "{v1} turn-proxies forward to this interface": "turn-прокси, ведущих на этот интерфейс: {v1}",
  "Invalid address for {v1}.": "Неверный адрес для {v1}.",
  "Error: {v1}": "Ошибка: {v1}",
  "{v1} (add)": "{v1} (доб.)",
  "{v1} (address)": "{v1} (адрес)",
  "{v1} (remove)": "{v1} (удаление)",
  "Some changes failed: {v1}": "Часть изменений не прошла: {v1}",
  "Delete failed: {v1}": "Удалить не удалось: {v1}",
  "Remove the peer from {v1} — those tunnels drop immediately and the client can no longer connect through them.":
    "Убрать пира с {v1} — эти туннели сразу разорвутся, и клиент больше через них не подключится.",
  "Remove the peer from {v1} — that tunnel drops immediately and the client can no longer connect through it.":
    "Убрать пира с {v1} — туннель сразу разорвётся, и клиент больше через него не подключится.",
  "Change the peer's address on {v1} — the config / QR already handed out for those interfaces stops connecting, so you'll need to re-issue and re-distribute them.":
    "Сменить адрес пира на {v1} — уже розданные конфиги и QR для этих интерфейсов перестанут работать, их придётся перевыпустить и раздать заново.",
  "Change the peer's address on {v1} — the config / QR already handed out for that interface stops connecting, so you'll need to re-issue and re-distribute it.":
    "Сменить адрес пира на {v1} — уже розданный конфиг и QR для этого интерфейса перестанут работать, их придётся перевыпустить и раздать заново.",
  "Remove from {v1}?": "Убрать с {v1}?",
  "Change {v1}?": "Сменить {v1}?",
  "Changing the mesh subnet / port / prefix of {v1} rebuilds all of its node-to-node links with the new settings.":
    "Смена подсети, порта или префикса сети у {v1} пересоберёт все её связи с другими нодами по новым настройкам.",
  "Node settings · {v1}": "Настройки ноды · {v1}",
  "Recover node · {v1}": "Возврат ноды · {v1}",
  "Rotate token · {v1}": "Смена токена · {v1}",
  "Force remove · {v1}": "Снести · {v1}",
  "Turn-proxy · {v1}": "Turn-прокси · {v1}",
  "No turn-proxy build for this node's architecture{v1} — only amd64 and arm64 are supported.":
    "Для архитектуры этой ноды{v1} сборки turn-прокси нет — поддерживаются только amd64 и arm64.",
  "Version, rollback & server defaults for {v1}": "Версия, откат и умолчания сервера для {v1}",
  "Delete turn-proxy · {v1}": "Удалить turn-прокси · {v1}",
  "Not offered on {v1}": "Не предлагается на {v1}",
  "Saved · {v1} · {v2}": "Сохранено · {v1} · {v2}",
  "Server defaults saved — used when creating new {v1} proxies.":
    "Умолчания сервера сохранены — применятся при создании новых прокси {v1}.",
  "Edit WDTT interface · {v1}": "Правка интерфейса WDTT · {v1}",
  "WDTT fork: {v1}": "Сборка WDTT: {v1}",
  "Users online · {v1}": "Кто в сети · {v1}",
  "val|range": "период",
  "the subscription server's certificate doesn't match {v1}": "сертификат сервера подписок не подходит для {v1}",
  "{v1} — subscribers get a TLS error": "{v1} — у подписчиков будет ошибка TLS",
  "mode → {v1}": "режим → {v1}",
  "{v1} will briefly drop off the mesh (and any cascade/smart traffic routed through it pauses) until every peer pulls the new config and reconnects — usually a few seconds. Other nodes' links to each other are unaffected.":
    "{v1} ненадолго выпадет из сети (и каскадный/умный трафик через неё замрёт), пока каждый пир не заберёт новые настройки и не переподключится — обычно это несколько секунд. Связи других нод между собой не затронуты.",
  "turn-proxy": "turn-прокси",
  "loading…": "загрузка…",
  "Which failure conditions the panel flags on a peer. All on by default — untick one to stop it showing that status (the peer just reads online / ready instead). Both appear in {v1}.":
    "Какие неполадки панель отмечает у пира. По умолчанию включено всё — снимите галочку, и этот статус показываться не будет (пир будет просто «в сети» или «готов»). Оба показываются {v1}.",
  "with {v1} core": "на ядре {v1}",
  "by {v1} with {v2} core": "от {v1}, ядро {v2}",
  "by {v1}": "от {v1}",
  "{v1} matched by address range (GeoIP / ASN) — works in every mode.":
    "{v1} по диапазону адресов (GeoIP / ASN) — работает в любом режиме.",
  "Held on {v1}": "Держим {v1}",
  "{v1} for {v2}": "{v1} для {v2}",
  "removed ·": "убрано ·",
  "*{v1}* {v2}": "*{v1}* {v2}",
  "*{v1}* unassigned on {v2} on {v3}": "*{v1}* без владельца на {v2} на {v3}",
  "*{v1}* orphan on {v2} ({v3}) on {v4}": "*{v1}* чужих на {v2} ({v3}) на {v4}",
  "connecting…": "подключаемся…",
  "cascade →": "каскад →",
  "No list matches “{q}”.": "Ничего по «{q}».",
  "Add a second step at sign-in using an authenticator app (Google Authenticator, Authy, 1Password…).":
    "Добавьте второй шаг при входе — код из приложения-аутентификатора (Google Authenticator, Authy, 1Password…).",
  "Turn IPs": "Адреса turn",
  "This node is busy or offline": "Нода занята или не на связи",
  " — turn-proxy actions are disabled until it's reporting again.": " — действия с turn-прокси недоступны, пока она не отзовётся.",
  "Internal port": "Внутренний порт",
  // ── server messages (the panel's own English sentence is the key — see srvText in js/i18n.js) ──
  "couldn't bind {v1} — {v2}": "не удалось занять {v1} — {v2}",
  "Subscriptions need encrypted config storage — turn on 'Keep encrypted configs' first.":
    "Подпискам нужно шифрованное хранение конфигов — сначала включите «Хранить шифрованные конфиги».",
  // ── the panel's own sentences: activity verbs (stored English, translated on display) ──
  "Added deployment": "Добавлено развёртывание",
  "Adopted from the live interface": "Принято с живого интерфейса",
  "Adopted peer": "Пир принят",
  "Adopting WDTT server": "Подключаем сервер WDTT",
  "Assigned peer": "Пир присвоен",
  "Auto-updating turn-proxy": "Автообновление turn-прокси",
  "Blocked access": "Доступ закрыт",
  "Cancelled interface request": "Запрос интерфейса отменён",
  "Cancelled node removal": "Удаление ноды отменено",
  "Cancelled turn-proxy request": "Запрос turn-прокси отменён",
  "Changed address": "Адрес изменён",
  "Corrected peer address": "Адрес пира исправлен",
  "Created API token": "Создан токен API",
  "Created WDTT peer": "Создан пир WDTT",
  "Creating interface": "Создаём интерфейс",
  "Deleted peer": "Пир удалён",
  "Deleted user": "Пользователь удалён",
  "Deleted webhook": "Вебхук удалён",
  "Deleting interface": "Удаляем интерфейс",
  "Disabled two-factor auth": "Двухфакторный вход выключен",
  "Edited peer config": "Конфиг пира изменён",
  "Enabled subscription": "Подписка включена",
  "Enabled two-factor auth": "Двухфакторный вход включён",
  "Enrolled node": "Нода подключена",
  "Flagged node for removal": "Нода помечена к удалению",
  "Host update started": "Обновление хоста запущено",
  "Imported WDTT user from adopted server": "Пользователь WDTT перенесён с принятого сервера",
  "Installed turn-proxy": "Установлен turn-прокси",
  "Linked node": "Ноды связаны",
  "Node uninstalled — kept for re-install": "Нода удалена — оставлена для переустановки",
  "Onboarding interface": "Подключаем интерфейс",
  "Onboarding turn-proxy": "Подключаем turn-прокси",
  "Re-ported mesh links (live)": "Связи сети переведены на новый порт (на лету)",
  "Re-provisioned mesh links": "Связи сети пересобраны",
  "Recreate WDTT server (fresh identity)": "Пересоздать сервер WDTT (новые ключи)",
  "Removed WDTT instance": "Сервер WDTT убран",
  "Removed deployment": "Развёртывание убрано",
  "Removed node": "Нода удалена",
  "Renamed node": "Нода переименована",
  "Renamed peer": "Пир переименован",
  "Renamed user": "Пользователь переименован",
  "Renaming turn-proxy": "Переименовываем turn-прокси",
  "Reset subscription encryption": "Шифрование подписок сброшено",
  "Restarting interface": "Перезапускаем интерфейс",
  "Restore WDTT identity": "Вернуть ключи WDTT",
  "Restored access": "Доступ возвращён",
  "Restoring interface": "Восстанавливаем интерфейс",
  "Revoked API token": "Токен API отозван",
  "Rotated WDTT password": "Пароль WDTT сменён",
  "Rotated node token": "Токен ноды сменён",
  "Saved webhook": "Вебхук сохранён",
  "Set WDTT instance": "Сервер WDTT задан",
  "Stopping interface": "Останавливаем интерфейс",
  "WDTT proxy": "WDTT-прокси",
  "Adopted new server key on": "Принят новый ключ сервера",
  "Adopted server-edited value": "Принято значение сервера",
  "Deleting turn-proxy": "Удаляем turn-прокси",
  "Editing turn-proxy": "Меняем turn-прокси",
  "Ignoring adoption candidate": "Пропускаем кандидата",
  "Reinstalling WDTT": "Переустанавливаем WDTT",
  "Reinstalling turn-proxy": "Переустанавливаем turn-прокси",
  "Restarting turn-proxy": "Перезапускаем turn-прокси",
  "Restored panel value": "Возвращено значение панели",
  "Restoring adoption candidate": "Возвращаем кандидата",
  "Restoring original server key on": "Возвращаем исходный ключ",
  "Rolling back WDTT": "Откатываем WDTT",
  "Rolling back turn-proxy": "Откатываем turn-прокси",
  "Rotating turn-proxy key": "Меняем ключ turn-прокси",
  "Starting turn-proxy": "Запускаем turn-прокси",
  "Stopping turn-proxy": "Останавливаем turn-прокси",
  "Updating WDTT to latest": "Обновляем WDTT до последней",
  "Update requested": "Обновление запрошено",
  "Updated block lists": "Списки блокировок обновлены",
  "Updated interface": "Интерфейс изменён",
  "Updated node": "Нода изменена",
  "Updated panel settings": "Настройки панели изменены",
  "{count} unassigned": "отвязано: {count}",
  "{count} · {where}": "{count} · {where}",
  // ── the panel's own sentences: validation and lookup failures ──
  "bad body": "неверное тело запроса",
  "bad cat": "неверная категория",
  "bad cat/tier": "неверная категория или уровень",
  "bad index": "неверный индекс",
  "bad interface name": "неверное имя интерфейса",
  "bad owner/tag/arch": "неверные репозиторий, тег или архитектура",
  "bad snapshot index": "неверный индекс снапшота",
  "binary unavailable": "бинарник недоступен",
  "config not stored": "конфиг не сохранён",
  "empty name": "пустое имя",
  "iface is required": "нужен интерфейс",
  "internal": "внутренняя ошибка",
  "invalid JSON body": "тело запроса — не JSON",
  "invalid node token": "неверный токен ноды",
  "invalid owner repo": "неверный репозиторий",
  "invalid version tag": "неверный тег версии",
  "invalid service name": "неверное имя службы",
  "invalid service or title": "неверная служба или название",
  "invalid username or password": "неверный логин или пароль",
  "invalid iface (wdtt0..wdtt999)": "неверный интерфейс (wdtt0..wdtt999)",
  "name is required": "нужно имя",
  "name cannot be empty": "имя не может быть пустым",
  "name must be 1–40 chars: letters, digits, - or _": "имя: от 1 до 40 знаков — буквы, цифры, «-» или «_»",
  "no primary listener": "нет основного слушателя",
  "not a WDTT peer": "это не пир WDTT",
  "not resolved yet": "ещё не определено",
  "nothing to update": "обновлять нечего",
  "provider disabled": "поставщик выключен",
  "pubkey is required": "нужен публичный ключ",
  "pubkey is required (reassignment mints a fresh key)": "нужен публичный ключ (при передаче создаётся новый)",
  "start setup first": "сначала запустите настройку",
  "unauthorized": "нет доступа",
  "unknown WDTT fork": "неизвестная сборка WDTT",
  "unknown WDTT instance": "неизвестный сервер WDTT",
  "unknown client": "неизвестный клиент",
  "unknown connection": "неизвестное соединение",
  "unknown node": "неизвестная нода",
  "unknown peer": "неизвестный пир",
  "unknown provider": "неизвестный поставщик",
  "unknown server": "неизвестный сервер",
  "unknown target": "неизвестное назначение",
  "unknown user": "неизвестный пользователь",
  "unknown webhook": "неизвестный вебхук",
  "authentication required": "нужен вход",
  "request signature required": "нужна подпись запроса",
  "request body too large": "тело запроса слишком большое",
  "control characters are not allowed": "управляющие символы недопустимы",
  "current password is incorrect": "текущий пароль неверен",
  "new password must be at least 8 characters": "новый пароль — не меньше 8 знаков",
  "username cannot be empty": "логин не может быть пустым",
  "username cannot contain ':'": "в логине не может быть «:»",
  "login is not enabled": "вход не включён",
  "login is not enabled on this panel": "на этой панели вход не включён",
  "no auth file configured (SWG_PANEL_AUTH unset)": "файл входа не настроен (SWG_PANEL_AUTH не задан)",
  "enter a valid authenticator or recovery code": "введите код из приложения или запасной код",
  "that code isn't valid": "код не подходит",
  "that code isn't valid — check the app and your device clock":
    "код не подходит — проверьте приложение и часы на устройстве",
  "awg_params must be an object": "awg_params должен быть объектом",
  "blocks/step must be integers": "blocks и step должны быть целыми",
  "categories/providers must be objects, removed a list": "categories и providers — объекты, removed — список",
  "egress IP must be an IPv4 address": "адрес выхода должен быть IPv4",
  "egress_mode must be direct|forward|smart": "egress_mode: direct, forward или smart",
  "egress_node must be another known node": "egress_node должен быть другой известной нодой",
  "endpoint host must be a bare hostname or IP": "адрес входа — только имя хоста или IP",
  "expiry must be an epoch timestamp or 0": "срок — метка времени epoch или 0",
  "kind must be node|iface|turn": "kind: node, iface или turn",
  "listen and connect must be ip:port": "listen и connect задаются как ip:порт",
  "listen must be ip:port": "listen задаётся как ip:порт",
  "max_passwords must be an integer": "max_passwords должен быть целым",
  "mesh port must be 1–65535 (or blank)": "порт сети — от 1 до 65535 (или пусто)",
  "mesh subnet must be a CIDR (or blank)": "подсеть сети — CIDR (или пусто)",
  "mtu must be 576–9200": "MTU — от 576 до 9200",
  "mtu must be a number": "MTU должен быть числом",
  "n (AS number) required": "нужен номер AS",
  "order must be a list": "order должен быть списком",
  "port must be 1–65535": "порт — от 1 до 65535",
  "port must be a number": "порт должен быть числом",
  "range must be live|hour|day|week|month": "range: live, hour, day, week или month",
  "reserved mesh subnet must be a CIDR": "служебная подсеть сети — CIDR",
  "routing_mode must be kernel|forcedns|sni|sni_kernel": "routing_mode: kernel, forcedns, sni или sni_kernel",
  "subnet must be a CIDR like 10.8.0.0/24": "подсеть — CIDR, например 10.8.0.0/24",
  "vk_links must be a list": "vk_links должен быть списком",
  "wg_addr must be an IPv4 CIDR (e.g. 10.66.70.1/24)": "wg_addr — IPv4 CIDR, например 10.66.70.1/24",
  "wg_port / max_passwords must be integers": "wg_port и max_passwords должны быть целыми",
  "wg_port must be 1-65535": "wg_port — от 1 до 65535",
  "wg_port must be an integer": "wg_port должен быть целым",
  "WAN interface must be a bare device name": "интерфейс WAN — только имя устройства",
  "webhook host must not be a link-local / reserved address":
    "хост вебхука не может быть служебным или link-local адресом",
  "webhook url must start with http:// or https://": "адрес вебхука должен начинаться с http:// или https://",
  "identity path must be an absolute path with no '..' segments": "путь к ключам — абсолютный, без «..»",
  "an absolute .service path is required": "нужен абсолютный путь к .service",
  "an absolute config path is required": "нужен абсолютный путь к конфигу",
  "a fork + owner repo are required (letters, digits, . _ - and one /)":
    "нужны сборка и репозиторий (буквы, цифры, «.», «_», «-» и одна «/»)",
  "interface name is required": "нужно имя интерфейса",
  "interface name is required (no spaces or /)": "нужно имя интерфейса (без пробелов и «/»)",
  "'{v1}' isn't a usable interface name — letters, digits, _ and -, up to 15 characters":
    "«{v1}» не годится как имя интерфейса — буквы, цифры, «_» и «-», до 15 знаков",
  // ── the panel's own sentences: conflicts, address-change flow, WDTT adoption ──
  "Cloudflare Origin (cf15) TLS needs a Cloudflare Origin CA token — add it in Panel URL before switching.":
    "Для TLS с сертификатом Cloudflare Origin (cf15) нужен токен Origin CA — добавьте его в «Адрес панели» до переключения.",
  "Cloudflare TLS needs a Cloudflare DNS token — add it in Panel URL before switching, otherwise the panel would serve a self-signed certificate Cloudflare rejects (526).":
    "Для TLS через Cloudflare нужен токен DNS — добавьте его в «Адрес панели» до переключения, иначе панель отдаст самоподписанный сертификат, а Cloudflare его отвергнет (526).",
  "Not a valid VK call link — expected https://vk.ru/call/join/…":
    "Это не ссылка на звонок VK — нужна вида https://vk.ru/call/join/…",
  "Peer expiry can't be later than the subscription's expiry ({v1})":
    "Срок действия пира не может быть позже срока действия подписки ({v1})",
  "Subscription expiry can't be earlier than a peer's expiry ({v1})":
    "Срок действия подписки не может быть раньше срока действия пира ({v1})",
  "a change is still waiting to be confirmed — confirm it on the new address, cancel it, or wait for it to revert":
    "изменение ещё ждёт подтверждения — подтвердите его на новом адресе, отмените или дождитесь отката",
  "a peer with this key already exists (use add-target to deploy it elsewhere)":
    "пир с таким ключом уже есть (чтобы развернуть его ещё где-то, добавьте назначение)",
  "a sealed identity is required": "нужны запечатанные ключи",
  "a subscription change is already in progress": "изменение подписки уже идёт",
  "an address change is already pending": "смена адреса уже запланирована",
  "an address change is still waiting to be confirmed — confirm it on the new address, cancel it, or wait for it to revert before changing these settings.":
    "смена адреса ещё ждёт подтверждения — подтвердите её на новом адресе, отмените или дождитесь отката, прежде чем менять эти настройки.",
  "an install for this fork+port is already pending": "установка для этой сборки и порта уже запланирована",
  "another peer already uses this key": "этот ключ уже занят другим пиром",
  "at least one WDTT target is required": "нужно хотя бы одно назначение WDTT",
  "at least one target is required": "нужно хотя бы одно назначение",
  "bad request signature ({v1})": "неверная подпись запроса ({v1})",
  "confirm must be made on the new address": "подтверждать нужно на новом адресе",
  "couldn't bind {v1} — {v2}. If your reverse proxy still owns that port, stop it there first — the panel and the proxy can't both hold it.":
    "не удалось занять {v1} — {v2}. Если порт всё ещё держит ваш обратный прокси, освободите его там: панель и прокси не могут держать один порт вдвоём.",
  "hold on {v1}s — the nodes are still learning the new address so the restart won't strand them":
    "подождите {v1} с — ноды ещё узнают новый адрес, чтобы перезапуск их не отрезал",
  "interface is already present on the node — nothing to recreate":
    "интерфейс на ноде уже есть — пересоздавать нечего",
  "interface isn't reporting a subnet (is it present and online?)":
    "интерфейс не сообщает подсеть (он вообще есть и поднят?)",
  "its subnet {v1} is already used elsewhere in the fleet ({v2}) — adopting it would black-hole one of them":
    "его подсеть {v1} уже занята во флоте ({v2}) — если принять, один из них останется без трафика",
  "ivk_pub and ivk_priv_by_sk are required to enable escrow": "для депонирования нужны ivk_pub и ivk_priv_by_sk",
  "listen port {v1} is already used by {v2} on this node — pick another port":
    "порт {v1} на этой ноде уже занят: {v2} — выберите другой",
  "need nodes and iface": "нужны ноды и интерфейс",
  "no WDTT instance '{v1}' on node {v2}": "на ноде {v2} нет сервера WDTT «{v1}»",
  "no encrypted config for this peer": "у этого пира нет зашифрованного конфига",
  "no encryption key for this user — set up config encryption first":
    "у этого пользователя нет ключа шифрования — сначала настройте шифрование конфигов",
  "no free addresses across selected nodes": "на выбранных нодах нет свободных адресов",
  "no matching address change is waiting to be confirmed": "подходящей смены адреса на подтверждении нет",
  "no matching change is waiting to be confirmed": "подходящего изменения на подтверждении нет",
  "no matching pending change": "подходящего запланированного изменения нет",
  "no pending change to revert": "откатывать нечего",
  "no pending drift for that setting": "по этой настройке расхождений нет",
  "no reachability confirmation is pending": "подтверждения доступности не ожидается",
  "no reverse-proxy port change is waiting to be confirmed": "смены порта за прокси на подтверждении нет",
  "no saved config for that interface — cannot recreate": "сохранённого конфига интерфейса нет — пересоздать нельзя",
  "no subnet info in snapshot": "в снапшоте нет данных о подсети",
  "no turn-proxy build for this node's architecture ({v1}) — forks publish amd64/arm64 only":
    "для архитектуры этой ноды ({v1}) сборки turn-прокси нет — публикуются только amd64 и arm64",
  "node and fork required": "нужны нода и сборка",
  "node and iface required": "нужны нода и интерфейс",
  "node and peer required": "нужны нода и пир",
  "node has not reported yet (is swg-noded running?)": "нода ещё не отчиталась (swg-noded запущен?)",
  "owner or service required": "нужен репозиторий или служба",
  "peer IP is already inside the interface subnet — nothing to correct":
    "адрес пира и так внутри подсети интерфейса — исправлять нечего",
  "peer already has a target on that node/interface": "у пира уже есть назначение на этой ноде и интерфейсе",
  "peer has no such target": "у пира нет такого назначения",
  "peer has no target on that node/interface": "у пира нет назначения на этой ноде и интерфейсе",
  "peer is assigned to a user — unassign it first": "пир привязан к пользователю — сначала отвяжите его",
  "peer is not assigned to this user": "пир не принадлежит этому пользователю",
  "port {v1} is already used by {v2} on this node — pick another port":
    "порт {v1} на этой ноде уже занят: {v2} — выберите другой",
  "salt, sk_by_pw and sk_check are required": "нужны salt, sk_by_pw и sk_check",
  "sealed_identity fields must be strings": "поля sealed_identity должны быть строками",
  "sec (ciphertext) is required": "нужен sec (шифртекст)",
  "set up the encryption key first": "сначала настройте ключ шифрования",
  "switching between a reverse proxy and direct TLS also needs the address to change — direct TLS binds a public address (e.g. 0.0.0.0:443, the port taken from the Public URL); behind a proxy the panel stays on 127.0.0.1:<internal port>. Set the Public URL (and, behind a proxy, the Listen IP/port) to match the new mode, then save.":
    "переход между обратным прокси и прямым TLS требует и смены адреса: с прямым TLS панель слушает публичный адрес (например 0.0.0.0:443, порт берётся из публичного адреса), а за прокси остаётся на 127.0.0.1:<внутренний порт>. Приведите публичный адрес (а за прокси — ещё адрес и порт прослушивания) к новому режиму и сохраните.",
  "that server's identity (wg-keys.dat) can't be found on the node, so adopting it would break every existing client — point at its key file, or ignore it instead":
    "ключи этого сервера (wg-keys.dat) на ноде не найдены, поэтому после подключения отвалятся все клиенты — укажите файл с ключами или скройте сервер",
  "that version isn't a published build for this fork": "такой версии среди опубликованных сборок этой ветки нет",
  "that version isn't in the rollback cache — the panel has no verified binary for it":
    "этой версии нет в кэше отката — проверенного бинарника у панели нет",
  "the DTLS listen port and the internal WG port must be different":
    "порт DTLS и внутренний порт WG должны различаться",
  "the confirm didn't arrive on the new path {v1} (it came in on {v2}) — open the new address and try again":
    "подтверждение пришло не на новый путь {v1}, а на {v2} — откройте новый адрес и повторите",
  "the previous address is no longer serving — can't cancel instantly":
    "прежний адрес уже не отвечает — мгновенно отменить нельзя",
  "the previous change is still settling ({v1}s) — you can only cancel until it finishes":
    "предыдущее изменение ещё применяется ({v1} с) — до конца можно только отменить",
  "this is the peer's only deployment — delete the peer instead (unassign it first)":
    "это единственное развёртывание пира — удаляйте самого пира (сначала отвязав его)",
  "this node already manages a WDTT instance on {v1}": "на {v1} эта нода уже ведёт сервер WDTT",
  "this node doesn't report a WDTT server on {v1} — refresh and try again":
    "нода не сообщает о сервере WDTT на {v1} — обновите и повторите",
  "this panel wasn't reached on the new address (arrived on '{v1}', expected '{v2}') — re-point your reverse proxy to route {v3} here, then try again":
    "запрос пришёл на «{v1}», а ждали «{v2}» — перенастройте обратный прокси, чтобы {v3} вёл сюда, и повторите",
  "this panel wasn't reached on the new path (arrived on '{v1}', expected '{v2}') — add a location for {v3} to your reverse proxy, then try again":
    "запрос пришёл на путь «{v1}», а ждали «{v2}» — добавьте в прокси location для {v3} и повторите",
  "this server's listen address isn't host:port: {v1}": "адрес прослушивания этого сервера не вида хост:порт: {v1}",
  "this server's tunnel subnet isn't an IPv4 CIDR: {v1}": "подсеть туннеля этого сервера не IPv4 CIDR: {v1}",
  "token_sha and token_by_sk are required": "нужны token_sha и token_by_sk",
  "token_sha, unlock_by_sk and token_by_sk are required": "нужны token_sha, unlock_by_sk и token_by_sk",
  "too many ignored interfaces on this node": "на этой ноде слишком много скрытых интерфейсов",
  "unknown WDTT fork: {v1}": "неизвестная сборка WDTT: {v1}",
  "unlock_by_sk is required": "нужен unlock_by_sk",
  "your reverse proxy is still routing to the old port {v1} — point its upstream at {v2} and reload it, then confirm (nothing was dropped)":
    "обратный прокси всё ещё ходит на старый порт {v1} — укажите в нём {v2}, перечитайте конфиг и подтвердите (ничего не потеряно)",
  "your reverse proxy isn't routing to the new bind yet — point its upstream at {v1} and reload it, then confirm (nothing was changed)":
    "обратный прокси ещё не ходит на новый адрес — укажите в нём {v1}, перечитайте конфиг и подтвердите (ничего не изменено)",
  "{v1} must be a valid IPv4 address (or blank)": "{v1} должен быть адресом IPv4 (или пустым)",
  "{v1} must be ip:port": "{v1} задаётся как ip:порт",
  "{v1} {v2} is already used by {v3} on this node — pick another port":
    "{v1} {v2} на этой ноде уже занят: {v3} — выберите другой",
  "{v1} — nothing was changed. Fix it and try again, or Revert.":
    "{v1} — ничего не изменено. Исправьте и повторите либо откатите.",
  "could not write auth file: {v1}": "не удалось записать файл входа: {v1}",
  "couldn't signal the updater: {v1}": "не удалось разбудить обновлятор: {v1}",
  "duplicate target {v1}": "назначение {v1} повторяется",
  "interface subnet {v1} is invalid": "подсеть интерфейса {v1} неверна",
  "invalid address {v1}": "неверный адрес {v1}",
  "target.{v1} is required": "нужно поле target.{v1}",
  "unknown node {v1}": "неизвестная нода {v1}",
  "unknown node(s): {v1}": "неизвестные ноды: {v1}",
  "{v1} is a WDTT interface — add WDTT users via the WDTT flow, not a WireGuard peer":
    "{v1} — интерфейс WDTT: пользователей туда добавляют через WDTT, а не как пира WireGuard",
  "{v1} is a system mesh link — not a peer interface": "{v1} — служебная связь сети, а не интерфейс для пиров",
  "{v1} is already used on {v2}": "{v1} уже занят на {v2}",
  "kind|bare-metal": "Железо",
  "kind|docker": "Докер",
  // budget-ok: a tooltip on an icon button — its own bubble
  "Switch to {name}": "Переключить на {name}",
  "request failed": "запрос не прошёл",
  "awaiting restore": "ждёт восстановления",
  "save failed": "не сохранилось",
  "start failed": "не запустилось",
  "listen port": "порт прослуш.",
  "node offline": "Нода не на связи",
  "sites caught": "сайтов поймано",
  "none flagged": "ничего нет",
  "partially deployed": "развёрнут частично",
  "all events": "все события",
  "both ports": "оба порта",
  "subscription server": "сервер подписок",
  "enabled lists": "включённые списки",
  "catalog categories": "категории каталога",
  "never updated": "не обновлялся",
  "This node's mesh AWG params": "Параметры AWG сети этой ноды",
  "rotate failed": "смена не прошла",
  "app default": "по умолчанию",
  "check failed": "не проверилось",
  "timed out": "истекло время",
  "unassigned peer": "пир без владельца",
  "panel nginx server block": "блок server для nginx (панель)",
  "subscription nginx server block": "блок server для nginx (подписки)",
};

/* Counted nouns. Russian selects between three forms by the last digit, with a correction for the
   teens (11–14 take the "many" form despite ending in 1–4) — see plural() in js/i18n.js.
   Order: [1 пир, 2 пира, 5 пиров]. */
export const PLURALS = {
  peer: ["пир", "пира", "пиров"],
  node: ["нода", "ноды", "нод"],
  user: ["пользователь", "пользователя", "пользователей"],
  interface: ["интерфейс", "интерфейса", "интерфейсов"],
  server: ["сервер", "сервера", "серверов"],
  record: ["запись", "записи", "записей"],
  "destination": ["назначение", "назначения", "назначений"],
  "new host": ["новый домен", "новых домена", "новых доменов"],
  "prefix": ["префикс", "префикса", "префиксов"],
  "proxy": ["прокси", "прокси", "прокси"],
  "cap|Peer": ["пир", "пира", "пиров"],
  target: ["назначение", "назначения", "назначений"],
  "cap|Node": ["нода", "ноды", "нод"],
  "WDTT server": ["сервер WDTT", "сервера WDTT", "серверов WDTT"],   // the u-pc / servbub badges: capitalised in English, ordinary in Russian
  version: ["версия", "версии", "версий"],
  deployment: ["развёртывание", "развёртывания", "развёртываний"],
  change: ["изменение", "изменения", "изменений"],
  device: ["устройство", "устройства", "устройств"],
  list: ["список", "списка", "списков"],
  rule: ["правило", "правила", "правил"],
  IP: ["IP", "IP", "IP"],   // indeclinable acronym: one form covers every count
  issue: ["проблему", "проблемы", "проблем"],
  group: ["группа", "группы", "групп"],   // reads after "исправить" (accusative): исправить 1 проблему / 5 проблем
  minute: ["минуты", "минут", "минут"],          // reads after "больше" (genitive): больше 1 минуты / 5 минут
  address: ["адрес", "адреса", "адресов"],
  "broken address": ["неверный адрес", "неверных адреса", "неверных адресов"],
};
