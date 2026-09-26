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
  // ── what a save could not keep (§5.4) ──
  // Impersonal «Пропущено», with the count in a parenthesis — the number is interpolated, so it arrives
  // nominative and cannot be declined, and «не сохранена / не сохранены» would have to agree with it. The
  // parenthesis rather than a dash because each clause after the colon carries its own dash («X — не удалось
  // разобрать»), and two dash levels in one line read as one long muddle.
  // budget-ok: toast, wraps
  "Saved — {v1} not kept: {v2}": "Сохранено. Пропущено ({v1}): {v2}",
  "{v1} couldn't be read": "{v1} — не удалось разобрать",
  "{v1} is no longer published by {v2}": "{v1} больше не публикуется источником {v2}",
  "{v1} is no longer a list the panel knows": "{v1} — панель больше не знает такого списка",
  "…and {v1} more": "…и ещё {v1}",

  // ── networks behind a peer (docs/NETWORKS-PLAN.md) ──
  // {node} is a node's own NAME, so no sentence here makes a verb or pronoun agree with it: «{node}: …» or
  // «на {node}» throughout. {peers}/{users} arrive already counted; the users slot reads after «у», so the
  // code passes the genitive noun (gen|user).
  "Networks behind this device": "Сети за этим устройством",
  // NETWORKS P5 — who can reach a network behind a device
  "A date is the last day they can reach these networks; leave it empty for no end.": "Дата — последний день доступа к этим сетям; оставьте пустой, чтобы без срока.",
  "{name}: {devices} on a turn server whose build can't prove who is sending — they can't reach it.": "{name}: {devices} за turn-сервером, сборка которого не подтверждает отправителя, — доступа нет.",
  "{name}: {devices} not connected yet — they reach it once connected.": "{name}: {devices} — подключения ещё не было, доступ появится после него.",
  "{name}: {devices} on a turn server that isn't running.": "{name}: {devices} за turn-сервером, который не запущен.",
  "{name}: {devices} in ildarmaga's raw mode, which can't reach a restricted network.": "{name}: {devices} в raw-режиме ildarmaga, который не может достучаться до сети с ограниченным доступом.",
  "{name}: {devices} not reported by the node yet.": "{name}: {devices} — данных от ноды ещё нет.",
  "{node} runs a version that can't restrict who reaches a network, so it carries this one for nobody — update it.": "{node} работает на версии, которая не умеет ограничивать доступ к сети, поэтому эта сеть там никому не доступна — обновите её.",
  "One of these people no longer exists — remove them and save again.": "Одного из этих людей больше нет — уберите его и сохраните снова.",
  "A date has already passed — pick a later day or leave it empty.": "Дата уже прошла — выберите более поздний день или оставьте поле пустым.",
  "A network can be shared with at most 500 people and groups.": "Открыть сеть можно не более чем 500 людям и группам.",
  "One of these groups no longer exists — remove it and save again.": "Одной из этих групп больше нет — уберите её и сохраните снова.",
  "This page is out of date — reload it, then save again.": "Страница устарела — обновите её и сохраните снова.",
  "Access wasn't saved.": "Доступ не сохранён.",
  "a user who no longer exists": "удалённый пользователь",
  "Networks": "Сети",
  "Networks · {n}": "Сети · {n}",
  "Networks · {name}": "Сети · {name}",
  // NETWORKS §18 — the gaps a use-case walk found: what cuts a gateway off, old nodes, the device's own routing, home ranges
  "This device": "Это устройство",
  "{device} carries {nets} — everyone who reaches them through it loses access.": "{device} проводит {nets} — все, кто попадает туда через него, потеряют доступ.",
  "{device} carries {nets} — everyone who reaches them through it loses access until it's unblocked.": "{device} проводит {nets} — все, кто попадает туда через него, потеряют доступ до разблокировки.",
  "Their devices that carry networks ({devices}) take them down too — everyone who reaches them through those devices loses access.":
    "Через устройства этого пользователя проходят сети ({devices}) — все, кто попадает в них через эти устройства, потеряют доступ.",
  "Their devices that carry networks ({devices}) take them down too — everyone who reaches them through those devices loses access until the user is unblocked.":
    "Через устройства этого пользователя проходят сети ({devices}) — все, кто попадает в них через эти устройства, потеряют доступ до разблокировки пользователя.",
  "{device} stops carrying {nets} on {where} — everyone who reaches them there loses access.": "{device} перестанет проводить {nets} на {where} — все, кто попадал туда там, потеряют доступ.",
  "{device} carries {nets}. On a node you add, they're carried there too — for the same people as now.": "{device} проводит {nets}. На добавленной ноде они тоже будут проводиться — для тех же людей, что и сейчас.",
  // budget-ok: notice, wraps
  "{device} carries {nets}. On a node you add, they're carried there too, and every device on that node can reach them. Open Networks to limit who.":
    "{device} проводит {nets}. На добавленной ноде они тоже будут проводиться, и туда сможет попасть любое устройство на этой ноде. Ограничить доступ можно в окне «Сети».",
  // budget-ok: notice, wraps
  "{nodes} runs an older version that can't limit who reaches a network, so with this choice nobody reaches them there — {name} included. Update {nodes}, or choose “{everyone}”.":
    "{nodes} работает на старой версии, которая не умеет ограничивать доступ к сети, поэтому с таким выбором туда никто не попадёт — и {name} тоже. Обновите {nodes} или выберите «{everyone}».",
  // budget-ok: notice, wraps
  "{nodes} runs an older version that can't limit who reaches a network, so with this choice nobody reaches them there. Update {nodes}, or choose “{everyone}”.":
    "{nodes} работает на старой версии, которая не умеет ограничивать доступ к сети, поэтому с таким выбором туда никто не попадёт. Обновите {nodes} или выберите «{everyone}».",
  "Saving with no networks removes them — you'll be asked first.": "Если сохранить пустое поле, сети будут удалены — сначала появится подтверждение.",
  "Someone changed these networks while this window was open. Cancel and open it again to see the latest.":
    "Пока окно было открыто, кто-то изменил эти сети. Нажмите «Отмена» и откройте окно снова, чтобы увидеть актуальное.",
  // budget-ok: notice, wraps
  "Many home routers use {list}. Anyone whose home network uses the same addresses can't reach it from home — their own network wins — though it still works on mobile data. If you can, renumber this network to something rarer, like 10.57.20.0/24.":
    "Диапазон {list} используют многие домашние роутеры. У кого дома сеть с такими же адресами, тот не попадёт в неё из дома — побеждает домашняя сеть, — хотя через мобильный интернет всё работает. Если можете, перенумеруйте эту сеть во что-то более редкое, например 10.57.20.0/24.",
  "Checking these networks…": "Проверяем эти сети…",
  // budget-ok: notice, wraps
  "This device's config for {node} doesn't route {subnet}, so its answers to clients leave through its own internet connection and never arrive. Add {subnet} to its routing with the gear above and re-import its config.":
    "Конфиг этого устройства для {node} не маршрутизирует {subnet}, поэтому его ответы клиентам уходят через его собственный интернет и не доходят. Добавьте {subnet} в маршруты шестерёнкой выше и заново импортируйте конфиг.",
  "waiting for {node}": "ждёт {node}",
  "carried once saved": "будет проводиться после сохранения",
  "{node} hasn't routed it yet — it does on its next sync, usually within a minute.": "{node} ещё не проложила маршрут — сделает это при следующей синхронизации, обычно в течение минуты.",
  "A widened device reaches these networks only after its user re-imports the config or refreshes their subscription.":
    "Устройство с расширенными маршрутами попадёт в эти сети только после того, как пользователь заново импортирует конфиг или обновит подписку.",
  "Networks this device routes for, like the office LAN behind a router. Clients on the same node reach them through it.":
    "Сети, для которых это устройство служит шлюзом, например офисная сеть за роутером. Клиенты на той же ноде попадают туда через него.",
  "Only {name}": "Только {name}",
  "People you choose": "Выбранные люди",
  // the People window and the per-node counts (NETWORKS §18.2) — sized for 2 people or 200
  "Shared with {users}": "Доступ: {users}",
  "Choose people": "Выбрать людей",
  "{name} always has access, as the owner, and so do the people you choose.": "Владелец, {name}, имеет доступ всегда — как и выбранные люди.",
  "Only the people you choose have access.": "Доступ есть только у выбранных людей.",
  "Nobody has access yet — choose people, or pick “{everyone}”.": "Пока ни у кого нет доступа — выберите людей или «{everyone}».",
  "no device": "нет устройств",
  "{devices} with access": "с доступом: {devices}",
  "no device reaches it yet": "пока ни одно устройство не доходит",
  "no device here": "здесь нет устройств",
  "People with access": "Кому открыт доступ",
  "{users} chosen": "Выбрано: {users}",
  "{name} always has access, as the owner.": "Владелец, {name}, имеет доступ всегда.",
  "Filter the list…": "Фильтр по списку…",
  "Devices": "Устройства",
  "Access until": "Доступ до",
  "Nobody on the list matches “{q}”.": "В списке нет совпадений с «{q}».",
  "Nobody yet — add people or groups with the search above.": "Пока никого — добавьте людей или группы через поиск выше.",
  "{peers} of {users} can reach it": "Доступ есть: {peers} у {users}",
  "Nobody on {node} can reach it yet": "На {node} пока ни у кого нет доступа",
  "Every client on {node} can reach it: {peers} of {users}": "Доступ есть у любого клиента на {node}: {peers} у {users}",
  "No other client is on {node} yet — anyone added there will reach it": "На {node} пока нет других клиентов — любой, кого туда добавят, получит доступ",
  "{peers} route around it — see “Narrowed routing” below": "Маршрутизация не включает эту сеть: {peers} — см. «Сужена маршрутизация» ниже",
  "{devices} not connected yet — they reach it once connected": "Ещё не подключены: {devices} — доступ появится после подключения",
  "{peers} aren't among the people with access": "Нет среди тех, у кого есть доступ: {peers}",
  "{devices} on turn servers that can't reach a restricted network": "За turn-серверами, которые не могут попасть в сеть с ограниченным доступом: {devices}",
  "Access has ended for {users}": "Доступ закончился: {users}",
  // ── user groups (docs/GROUPS-PLAN.md) ──
  // {groups}/{members}/{users} arrive already counted and nominative, so they sit after a colon or in a list — never as the subject
  // a Russian verb would have to agree with (the plural() trap, NETWORKS §16).
  "Access has ended for {groups}": "Доступ закончился: {groups}",
  "Shared with {groups} and {users}": "Доступ: {groups} и {users}",
  "Shared with {groups}": "Доступ: {groups}",
  "{groups} and {users} chosen": "Выбрано: {groups} и {users}",
  "{groups} chosen": "Выбрано: {groups}",
  "Add a person or group…": "Добавить человека или группу…",
  "col|User or group": "Пользователь или группа",
  "a group that no longer exists": "удалённая группа",
  "{users} with no device here": "Без устройств здесь: {users}",
  "Groups": "Группы",
  // ── a user's sheet: the way into a group, and the two counts a list shows beside a name ──
  // «Добавить в группу…» is the placeholder of a list that ADDS: the chips below it are the groups they are already in, so the
  // verb carries the whole meaning and no second word is needed. The toast avoids a past-tense verb agreeing with a name of
  // unknown gender («добавлен/добавлена») — «теперь в группе» states the result instead.
  "Add to a group": "Добавить в группу",
  // The field's own one-line note, in the shape the other labels use («ДОСТУП ИСТЕКАЕТ — вся подписка…»): what a group DOES,
  // short enough to sit under the label instead of a paragraph under the control.
  "— members reach each other's devices, and a network can be shared with the group": "— участники видят устройства друг друга, а сеть можно открыть всей группе",
  "{name} is no longer in {group}.": "{name} — больше не в группе «{group}».",
  "They lose the networks shared with this group, unless they're shared with them another way: {devices}.": "Он потеряет сети, открытые этой группе, — если они не открыты ему другим способом: {devices}.",
  "Create new group…": "Создать группу…",
  "{name} is now in {group}.": "{name} — теперь в группе «{group}».",
  // The counts' aria labels: no name in them, because a screen reader has just read the row's own name, and a Russian name
  // interpolated into a case the sentence needs cannot be declined.
  // The counts' aria labels name no person: a screen reader has just read the row's own name, and a Russian name interpolated
  // into the case a sentence needs cannot be declined.
  "Reaches {v1} online now": "Сейчас доступно {v1}",
  "Reaches {v1}, none online": "Доступно {v1}, ни одна не онлайн",
  "Can reach": "Есть доступ к",
  "Devices the group can reach": "Устройства, доступные группе",
  "none the group can reach": "нет доступных группе",
  "{n} not counted: Private, or on an interface that doesn't let others in.": "{n} не в счёт: приватные или на интерфейсе, закрытом для других.",
  "{name}: {n} the group can reach, of {total}": "{name}: доступно группе — {n} из {total}",
  "Nobody — no shared group, and no interface here is open to everyone.": "Никого: общих групп нет, и ни один интерфейс здесь не открыт всем.",
  "Nothing beyond the internet.": "Ничего, кроме интернета.",
  "Users or groups": "Пользователи или группы",
  "All groups": "Все группы",
  "Of which {v1} was already on the counters.": "Из них {v1} уже было на счётчиках.",
  "Show only users with a device online": "Показать только пользователей с устройством в сети",
  "Traffic — graph and members": "Трафик — график и участники",
  "Members · {n}": "Участники · {n}",
  "No members yet": "Участников пока нет",
  "Add people to this group and their traffic appears here.": "Добавьте людей в группу — их трафик появится здесь.",
  "This group was deleted": "Эта группа удалена",
  "{name} users": "{name}: пользователи",
  "Total users": "Всего пользователей",
  "All time": "За всё время",
  "Today": "Сегодня",
  "Last 7 days": "Последние 7 дней",
  "Traffic window": "Период трафика",
  "The window the traffic figures count — in the panel's days (Settings → Display)": "Период, за который считается трафик, — в днях панели (Настройки → Отображение)",
  "col|Group": "Группа",
  "col|Members": "Участники",
  "col|Networks": "Сети",
  "Add members": "Добавить участников",
  "Double-click to edit the group": "Двойной щелчок — изменить группу",
  "Show this group on the users list": "Показать эту группу в списке пользователей",
  "Every member's devices added together — someone in two groups counts in both.": "Сумма по устройствам всех участников — человек из двух групп учтён в обеих.",
  "Search groups or members…": "Поиск по группам и участникам…",
  "New group": "Новая группа",
  "No groups yet": "Групп пока нет",
  "Put people in a group to share a network with all of them at once, from a device's Networks window.":
    "Объедините людей в группу, чтобы открывать сеть сразу всем — в окне «Сети» устройства.",
  "Members": "Участники",
  "No members yet.": "Участников пока нет.",
  "Devices whose networks are shared with {name}: {n}": "Устройства, чьи сети открыты группе {name}: {n}",
  "Networks shared with this group": "Сети, открытые этой группе",
  "None yet — share a network from a device's Networks window.": "Пока нет — сеть открывают в окне «Сети» устройства.",
  "Edit group": "Изменить группу",
  "Delete group": "Удалить группу",
  "Delete group · {name}": "Удалить группу · {name}",
  "Its members stay as users; only the group is deleted.": "Участники останутся пользователями — удаляется только группа.",
  // budget-ok: confirm body, wraps
  "Networks shared with it stop being reachable for its members, unless they're shared with them another way: {devices}.":
    "Сети, открытые этой группе, станут недоступны её участникам, если доступ не открыт им иначе: {devices}.",
  "Group deleted.": "Группа удалена.",
  "The group wasn't deleted.": "Группа не удалена.",
  "Group · {name}": "Группа · {name}",
  "This group no longer exists.": "Этой группы больше нет.",
  "Create group": "Создать группу",
  "Ivanov family": "Семья Ивановых",
  "Give the group a name.": "Дайте группе название.",
  "The group wasn't saved.": "Группа не сохранена.",
  "Group saved.": "Группа сохранена.",
  "Group created.": "Группа создана.",
  "Remove {name} from the group": "Убрать {name} из группы",
  "No members yet — add people with the search above.": "Участников пока нет — добавьте людей через поиск выше.",
  // budget-ok: hint, wraps
  "Networks shared with this group: {devices}. Everyone you add reaches them; anyone you remove loses them, unless they're shared with them another way.":
    "Этой группе открыты сети: {devices}. Каждый, кого вы добавите, получит к ним доступ; каждый, кого уберёте, потеряет его, если доступ не открыт ему иначе.",
  "{names} and {n} more": "{names} и ещё {n}",
  "Not in any group.": "Не состоит ни в одной группе.",
  // the panel's own words for a group (activity verbs, refusals) — stored in English, translated on display
  "Created group": "Создана группа",
  "Renamed group": "Переименована группа",
  "Changed group members": "Изменён состав группы",
  "Deleted group": "Удалена группа",
  "{count}": "{count}",
  "a group with this name already exists": "группа с таким названием уже есть",
  "the access level must be everyone, user or none": "уровень доступа должен быть everyone, user или none",
  // DEVICE ACCESS (docs/DEVICE-ACCESS-PLAN.md §10.6)
  "Who can open connections to devices here": "Кто может открывать соединения к устройствам здесь",
  "Everyone on this node": "Все на этой ноде",
  "Same user and their groups": "Тот же пользователь и его группы",
  "Nobody": "Никто",
  "Not enforced on {node} — it runs an older version. Update it.": "Не действует на {node} — там старая версия. Обновите ноду.",
  "Couldn't apply on {node}: {detail}": "Не удалось применить на {node}: {detail}",
  "Packets to devices here stopped since {when}: {n}": "Остановлено пакетов к устройствам здесь с {when}: {n}",
  "Applies on {node}'s next sync.": "Применится при следующей синхронизации {node}.",
  "Not enforced on {node} — this interface's subnet overlaps another interface's.": "Не действует на {node} — подсеть этого интерфейса пересекается с подсетью другого.",
  "Not enforced on {node} — the node can't read this interface's address.": "Не действует на {node} — нода не может прочитать адрес этого интерфейса.",
  "Not enforced on {node} — the node doesn't run this interface.": "Не действует на {node} — на ноде нет этого интерфейса.",
  "Not enforced on {node}.": "Не действует на {node}.",
  "Couldn't apply the latest change on {node}: {detail}. The previous rules stay in force.": "Не удалось применить последнее изменение на {node}: {detail}. Действуют прежние правила.",
  "This server build can't prove which user a device connected over RAW belongs to, so no other device can reach those devices.": "Эта сборка сервера не может подтвердить, какому пользователю принадлежит устройство, подключённое через RAW, поэтому ни одно другое устройство до таких устройств не достучится.",
  "reach|not updated": "не обновлено",
  "Any device on this node can open connections to devices here. Internet access and networks behind devices are not affected.": "Любое устройство на этой ноде может открывать соединения к устройствам здесь. На доступ в интернет и на сети за устройствами это не влияет.",
  "No other device can open connections to devices here; their own connections still work. Internet access and networks behind devices are not affected.": "Никакое другое устройство не может открывать соединения к устройствам здесь; их собственные соединения работают. На доступ в интернет и на сети за устройствами это не влияет.",
  "A device here can be reached by its user's other devices on this node and by users who share a group with them. Internet access and networks behind devices are not affected.": "Устройство здесь доступно другим устройствам его пользователя на этой ноде и пользователям, с которыми у него общая группа. На доступ в интернет и на сети за устройствами это не влияет.",
  "This server build can't prove which user a device belongs to, so no other device can reach any device here.": "Эта сборка сервера не может подтвердить, какому пользователю принадлежит устройство, поэтому ни одно другое устройство не достучится до устройств здесь.",
  "Peers reachable by": "Пиры доступны",
  "Not enforced on {node} — update it": "Не действует на {node} — обновите ноду",
  "reach|not enforced": "не действует",
  "Everyone on this node can open connections to devices here": "Все на этой ноде могут открывать соединения к устройствам здесь",
  "reach|everyone": "всем на ноде",
  "Nobody can open connections to devices here": "Никто не может открывать соединения к устройствам здесь",
  "reach|nobody": "никому",
  "Only the same user's devices and their groups can open connections to devices here": "Открывать соединения к устройствам здесь могут только устройства того же пользователя и его групп",
  "reach|user + groups": "только своим",
  "Devices now reach only their own user's devices and their groups' — {n} packets to other devices have been stopped. Put users who should reach each other in a group, or set an interface to Everyone.": "Теперь устройства видят только устройства своего пользователя и его групп — остановлено пакетов к чужим устройствам: {n}. Объедините в группу тех, кто должен видеть друг друга, или выберите для интерфейса «Все на этой ноде».",
  "Other devices reach this one at its tunnel address only as its interface allows — “Who can open connections to devices here”, in the interface's settings.": "Другие устройства достучатся до этого по туннельному адресу, только если это разрешает его интерфейс — «Кто может открывать соединения к устройствам здесь» в настройках интерфейса.",
  "Who can open connections to devices on new interfaces": "Кто может открывать соединения к устройствам на новых интерфейсах",
  "Applies to interfaces created from now on.": "Действует для интерфейсов, созданных с этого момента.",
  "Existing interfaces set to “Everyone on this node”: {n}": "Существующих интерфейсов с уровнем «Все на этой ноде»: {n}",
  "No existing interface is set to “Everyone on this node”.": "Ни у одного существующего интерфейса нет уровня «Все на этой ноде».",
  "Interfaces set to “Everyone on this node”": "Интерфейсы с уровнем «Все на этой ноде»",
  "Any device on the node can open connections to devices on these interfaces. Open one to change its level.": "Любое устройство на ноде может открывать соединения с устройствами на этих интерфейсах. Откройте интерфейс, чтобы изменить уровень.",
  "Filter by node or interface…": "Фильтр по ноде или интерфейсу…",
  "No interface matches “{q}”.": "Ни один интерфейс не подходит под «{q}».",
  "unknown group": "неизвестная группа",
  "users must be a list of user ids": "users должен быть списком id пользователей",
  "add and remove must be lists of user ids": "add и remove должны быть списками id пользователей",
  "{total} other peers on {node}: {ok} can reach it, {soon} not yet, {no} can't": "Других пиров на {node}: {total}; доступ есть: {ok}, пока нет: {soon}, нет: {no}",
  "Who can reach it on {node}": "Кто может попасть сюда на {node}",
  "This device's address on {node}": "Адрес этого устройства на {node}",
  "Everyone on {node}": "Все на {node}",
  "Everyone on its nodes": "Все на его нодах",
  "Only {name}'s own devices on the same node reach them.": "Туда попадают только устройства {name} на той же ноде.",
  "Every device on the same node reaches them — the report below says how many.": "Туда попадает любое устройство на той же ноде — сколько их, сказано ниже.",
  "Remove networks": "Удалить сети",
  "Remove networks?": "Удалить сети?",
  "{device} stops routing {nets}. Everyone who reaches them through it loses access.":
    "{device} перестанет маршрутизировать {nets}. Все, кто попадал туда через него, потеряют доступ.",
  "Who can reach these networks": "Кому доступны эти сети",
  "Add a person…": "Добавить человека…",
  "Last day {name} can reach them — leave empty for no end": "Последний день доступа для {name} — оставьте пустым, чтобы без срока",
  "Stop sharing with {name}": "Закрыть доступ для {name}",
  "everyone is already added": "все уже добавлены",
  "{node} couldn't apply the restriction, so nobody reaches these networks there until it can: {detail}": "{node} не смогла применить ограничение, поэтому там эти сети никому не доступны, пока не сможет: {detail}",
  "{node} hasn't confirmed the restriction yet — it does on its next sync.": "{node} ещё не подтвердила ограничение — подтвердит при следующей синхронизации.",
  "Devices on the network behind {device} ({nets}) can't reach it either — {owner} isn't among the people with access.":
    "Устройства в сети за {device} ({nets}) тоже сюда не попадут — у владельца, {owner}, нет доступа.",
  "Devices on the network behind {device} ({nets}) can't reach it either — that device has no owner, so it can't be given access.":
    "Устройства в сети за {device} ({nets}) тоже сюда не попадут — у этого устройства нет владельца, поэтому ему нельзя открыть доступ.",
  "{devices}, added {date}": "{devices}, добавлен {date}",
  "Connection test": "Проверка связи",
  "Saved. The device uses the new settings once its config is re-imported.": "Сохранено. Устройство применит новые настройки после повторного импорта конфига.",
  "Settings weren't saved.": "Настройки не сохранены.",
  // budget-ok: hover bubble, wraps
  "This device's config doesn't route {subnet}, so its answers to clients leave through its own internet connection and never arrive. Add {subnet} with the gear, then re-import its config.":
    "Конфиг этого устройства не маршрутизирует {subnet}, поэтому его ответы клиентам уходят через его собственный интернет и не доходят. Добавьте {subnet} через шестерёнку, затем заново импортируйте конфиг.",
  // budget-ok: hover bubble, wraps
  "This device's config sends all its traffic into the tunnel — the usual setup for a phone or laptop. On a router it means every device behind it browses the internet through {node} too; to carry only its networks, set the routing to {subnet}.":
    "Конфиг этого устройства отправляет в туннель весь трафик — обычная настройка для телефона или ноутбука. На роутере это значит, что и все устройства за ним выходят в интернет через {node}; чтобы проводить только его сети, укажите маршрут {subnet}.",
  "This device's config sends only {allowed} into the tunnel; everything else uses its own internet connection.":
    "Конфиг этого устройства отправляет в туннель только {allowed}; всё остальное идёт через его собственный интернет.",
  "It's sent by {node} itself, so it answers the same whoever this is shared with.": "Проверку отправляет сама {node}, поэтому ответ не зависит от того, кому открыт доступ.",
  "shared until {date}": "доступ до {date}",
  "shared with this user": "доступ открыт этому пользователю",
  "open to everyone on the node": "открыта всем на ноде",
  "{prefix} on {node}": "{prefix} на {node}",
  "{total} of this user's devices on {node}: {ok} reach it, {no} leave it out of their routing, {unk} unknown":
    "Устройств этого пользователя на {node}: {total}; доходят: {ok}, не включают в маршруты: {no}, неизвестно: {unk}",
  "Couldn't check these networks.": "Не удалось проверить эти сети.",
  "Networks saved.": "Сети сохранены.",
  "Networks removed.": "Сети удалены.",
  "Networks weren't saved.": "Сети не сохранены.",
  "carried": "проводится",
  "refused by the node": "нода отказала",
  "not carried": "не проводится",
  "Narrowed routing, can't reach it: {peers}": "Сужена маршрутизация, доступа нет: {peers}",
  "Edit routing": "Изменить маршруты",
  "Set up the device's side": "Настройка на стороне устройства",
  // The far side, per kind of device (NETWORKS §18). Keenetic's own Russian UI labels are quoted as the router shows them.
  "OpenWrt router": "Роутер OpenWrt",
  "Linux computer": "Компьютер с Linux",
  "Where the tunnel runs": "Где работает туннель",
  "The node sends traffic to this device; the device has to pass it on to its network and send the answers back. Where does the tunnel run?":
    "Нода отправляет трафик на это устройство, а оно должно передать его в свою сеть и вернуть ответы. Где работает туннель?",
  // budget-ok: disclosure body, wraps
  "Every client arrives from {subnet} — the node gives clients of its other interfaces its own address there — so the device only needs to send {subnet} back.":
    "Все клиенты приходят из {subnet} — клиентам других своих интерфейсов нода даёт здесь свой адрес, — поэтому устройству достаточно отправлять обратно только {subnet}.",
  // budget-ok: disclosure body, wraps
  "On the OpenWrt router itself (22.03 or newer). Put the peer section that “{cmd}” prints in place of <peer-section>, and the tunnel's interface name in place of <wg-interface>. Nothing needs translating — the router is already its network's gateway.":
    "На самом роутере OpenWrt (22.03 или новее). Вместо <peer-section> подставьте секцию пира, которую выводит «{cmd}», а вместо <wg-interface> — имя интерфейса туннеля. Транслировать ничего не нужно — роутер и так шлюз своей сети.",
  // budget-ok: disclosure body, wraps
  "Saved to the router's memory, so it survives a reboot, and safe to run again. The tunnel must be in no other firewall zone, wan or lan — “{cmd}” should name only swg.":
    "Настройки сохраняются в память роутера и переживают перезагрузку, а команды можно запускать повторно. Туннель не должен входить ни в какую другую зону файрвола, ни в wan, ни в lan, — «{cmd}» должна называть только swg.",
  // budget-ok: disclosure body, wraps
  "On the MikroTik itself (RouterOS 7), with its WireGuard interface in place of <wg-interface>. Nothing needs translating, and RouterOS saves changes as you make them.":
    "На самом MikroTik (RouterOS 7), подставив его интерфейс WireGuard вместо <wg-interface>. Транслировать ничего не нужно, а RouterOS сохраняет изменения сразу.",
  // budget-ok: disclosure body, wraps
  "Keep the tunnel out of the WAN interface list. The stock firewall then lets it reach the network; if yours isn't the stock one, allow forwarding from <wg-interface> to the LAN.":
    "Не добавляйте туннель в список интерфейсов WAN — тогда стандартный файрвол пропускает его в сеть. Если файрвол у вас не стандартный, разрешите пересылку из <wg-interface> в LAN.",
  "In the Keenetic web interface (KeeneticOS 5), no commands:": "В веб-интерфейсе Keenetic (KeeneticOS 5), без команд:",
  // budget-ok: disclosure body, wraps
  "Internet → Other connections → open this WireGuard connection. Check that “Use for accessing the Internet” is off, and in the peer's settings set “Allowed v4 IPs” to {subnet}. Save.":
    "Интернет → Другие подключения → откройте это подключение WireGuard. Проверьте, что «Использовать для выхода в интернет» выключено, и в настройке пира укажите в «Разрешенные IPv4-подсети» {subnet}. Сохраните.",
  // budget-ok: disclosure body, wraps
  "Network Rules → Routing → IPv4 routes → Create: “Route to network”, destination network address {addr}, subnet mask {mask}, Interface: this WireGuard connection, “Add automatically” ticked. Save.":
    "Сетевые правила → Маршрутизация → IPv4-маршруты → Добавить: «Маршрут до сети», адрес сети назначения {addr}, маска подсети {mask}, «Интерфейс» — это подключение WireGuard, «Добавлять автоматически» отмечено. Сохраните.",
  // budget-ok: disclosure body, wraps
  "Network Rules → Firewall → IPv4 → Add rule: Interface: this WireGuard connection, Action “Permit”, Source and Destination “Any”, Protocol “IPV4”. Save. The tunnel blocks incoming traffic until it has this rule.":
    "Сетевые правила → Межсетевой экран → IPv4 → Добавить правило: «Интерфейс» — это подключение WireGuard, «Действие» — «Разрешить», источник и назначение — «Любой», «Протокол» — «IPV4». Сохраните. Пока этого правила нет, туннель блокирует входящий трафик.",
  // budget-ok: disclosure body, wraps
  "On a Linux computer on that network that runs the tunnel with wg-quick — a Raspberry Pi, a NAS, a server; NetworkManager ignores these lines. Add them to its tunnel config, with its network card (the name after “dev” in “ip route show default”) in place of <lan-device>:":
    "На компьютере с Linux в этой сети, где туннель поднят через wg-quick, — Raspberry Pi, NAS, сервер; NetworkManager эти строки игнорирует. Добавьте их в конфиг туннеля, подставив вместо <lan-device> сетевую карту (имя после «dev» в выводе «ip route show default»):",
  "Then run this once, as root, with the tunnel's name in place of <wg-interface>:": "Затем один раз выполните это от root, подставив имя туннеля вместо <wg-interface>:",
  // budget-ok: disclosure body, wraps
  "The rules come back every time the tunnel starts, and the tunnel starts at boot; the computer's own internet stays off the tunnel. If it runs ufw, also run “ufw allow in on <wg-interface>”.":
    "Правила восстанавливаются при каждом запуске туннеля, а туннель запускается при загрузке; собственный интернет компьютера идёт мимо туннеля. Если на нём работает ufw, выполните ещё «ufw allow in on <wg-interface>».",
  // budget-ok: disclosure body, wraps
  "Devices on the network see these connections come from {subnet}. Some answer only their own network — Windows file sharing and ping, for example — and a computer running its own VPN may send its answers into that VPN. If one doesn't answer, allow {subnet} in its firewall, or route {subnet} to the router on it.":
    "Устройства в сети видят эти подключения из {subnet}. Некоторые отвечают только своей сети — например, общие папки Windows и ping, — а компьютер со своим VPN может отправлять ответы в этот VPN. Если устройство не отвечает, разрешите {subnet} в его файрволе или направьте на нём {subnet} на роутер.",
  // budget-ok: disclosure body, wraps
  "Windows and macOS can be set up as the gateway, but not with a few lines that survive a restart — use a router or a Linux computer.":
    "Windows и macOS можно настроить шлюзом, но не несколькими строками, которые переживут перезагрузку, — используйте роутер или компьютер с Linux.",
  "an unnamed peer": "пир без имени",
  "another peer": "другой пир",
  "{p} isn't a network address.": "{p} — не адрес сети.",
  "{p} is IPv6 — only IPv4 networks can be carried.": "{p} — это IPv6, а проводить можно только сети IPv4.",
  "{p} would send all of the node's internet traffic into this device.": "{p} отправил бы в это устройство весь интернет-трафик ноды.",
  "{p} is a reserved range — loopback, link-local, multicast or cloud metadata.": "{p} — зарезервированный диапазон: loopback, link-local, multicast или метаданные облака.",
  "{node} is already on {p} ({a}), so its clients reach it without a gateway device.": "{node} уже в сети {p} ({a}) — клиенты этой ноды попадают туда без шлюза.",
  "Blocked, so {peers} of {users} lose these networks until it is unblocked — their devices keep sending that traffic into the tunnel, where nothing answers.":
    "Устройство заблокировано — эти сети недоступны до разблокировки: {peers} у {users}. Их устройства по-прежнему отправляют этот трафик в туннель, где никто не отвечает.",
  "Who loses these networks: {peers}": "Кто теряет эти сети: {peers}",
  "Clients of {ifaces} on {node} that use a DNS server on {p} skip Force DNS: those lookups aren't blocked or routed by name.":
    "Клиенты {ifaces} на {node}, которые используют DNS-сервер в сети {p}, обходят Force DNS: такие запросы не блокируются и не маршрутизируются по имени.",
  "{node} is already on {p} ({a}), but it keeps its clients off that network. Turn on “Clients can reach it” under Local network on {node} to let them in.":
    "{node} уже в сети {p} ({a}), но не пускает туда своих клиентов. Чтобы пустить их, включите «Клиентам доступна» в разделе «Локальная сеть» на {node}.",
  "{p} overlaps a tunnel subnet on {node} ({a}).": "{p} пересекается с подсетью туннеля на {node} ({a}).",
  "{p} overlaps a mesh link on {node} ({a}).": "{p} пересекается с mesh-связью на {node} ({a}).",
  "{p} contains {a}, the gateway {node} reaches the internet through.": "В {p} входит {a} — шлюз, через который {node} выходит в интернет.",
  "{p} contains {a}, the address {node} reaches this panel by.": "В {p} входит {a} — адрес, по которому {node} достаёт до этой панели.",
  "{p} contains {a}, the DNS server {node} depends on — it could no longer find this panel.": "В {p} входит {a} — DNS-сервер, от которого зависит {node}: без него панель будет не найти.",
  "{node} can't tell which DNS server it depends on, so it carries no networks.": "{node}: не удаётся определить, от какого DNS-сервера зависит нода, поэтому сети не проводятся.",
  "{node} runs a version that can't check a route is safe — update it to carry networks.": "{node}: версия ноды не умеет проверять безопасность маршрута — обновите её, чтобы проводить сети.",
  "{node} hasn't reported yet; the network waits until it does.": "От {node} ещё нет отчёта — сеть ждёт его.",
  "{node} hasn't finished a sync yet; the network waits.": "{node}: синхронизация ещё не завершилась, сеть ждёт.",
  "A turn server deployment has no key, so nothing can be routed through it.": "У развёртывания на turn-сервере нет ключа, через него ничего не маршрутизировать.",
  "{by} already carries {a} on {node} — a network has one device per node.": "{a} на {node} уже проводит {by}: у сети одно устройство на ноду.",
  "{p} overlaps {a}, which this device already lists.": "{p} пересекается с {a}, которая уже есть у этого устройства.",
  "A device can front at most 8 networks.": "Одно устройство проводит не больше 8 сетей.",
  "This device is blocked or expired, so it carries nothing.": "Устройство заблокировано или его срок истёк — оно ничего не проводит.",
  "{node} installed the route and took it straight back out — it moved the path to {a}.": "{node}: маршрут поставлен и сразу снят — он менял путь до {a}.",
  "{node} already routes {p} through {a}, and leaves that route alone.": "{node}: {p} уже маршрутизируется через {a}, этот маршрут не трогаем.",
  "{node} couldn't check the route to {p} safely, so it didn't install it.": "{node}: не удалось безопасно проверить маршрут до {p}, он не поставлен.",
  // P3 evidence — the gateway as its node sees it, and the one thing operators don't know needs nothing
  "Devices on the same node already reach each other at their tunnel addresses — that needs nothing here.": "Устройства на одной ноде и так видят друг друга по туннельным адресам — для этого здесь ничего не нужно.",
  "{node} doesn't list this device yet.": "{node}: этого устройства пока нет в списке ноды.",
  "Networks this user can reach": "Сети, доступные этому пользователю",
  "Through {via}": "Через {via}",
  "not in this device's routing": "не в маршрутах устройства",
  "routing unknown": "маршруты неизвестны",
  "reachable": "доступна",
  "the node's local network": "локальная сеть ноды",
  "the node's local network, closed": "локальная сеть ноды, закрыта",
  "Worked out when this sheet opens. A device whose routing leaves a network out can be widened from its own settings.": "Рассчитано при открытии. Если сети нет в маршрутах устройства, её можно добавить в его собственных настройках.",
  "The device is connected — traffic through it:": "Устройство подключено, трафик через него:",
  "The device is offline, so nothing reaches these networks until it reconnects.": "Устройство не в сети — до переподключения в эти сети ничего не попадёт.",
  // P4 — the reachability test: the node sends one probe into the network through the device and says what came back
  "Test that the network answers — {node} sends it through this device:": "Проверка, что сеть отвечает: {node} отправит запрос через это устройство:",
  "an address on {p}": "адрес в {p}",
  "Address to test": "Адрес для проверки",
  "Port to connect to — leave empty to ping": "Порт для подключения; пусто — ping",
  "Test from the node": "Проверить с ноды",
  "testing…": "проверяем…",
  "Waiting for {node} to send it and report back — a few seconds.": "Ждём, пока {node} отправит запрос и сообщит результат, — несколько секунд.",
  "{addr} answered through {node} in {ms} ms.": "{addr} ответил через {node} за {ms} мс.",
  "That proves the path only if {addr} is a device on the network — this device's own address there answers even when it passes nothing on.": "Это доказывает путь, только если {addr} — устройство в самой сети: собственный адрес этого устройства там отвечает, даже когда оно ничего не пропускает дальше.",
  "{addr} answered through {node} in {ms} ms — port {port} is closed, but the network is reachable.": "{addr} ответил через {node} за {ms} мс: порт {port} закрыт, но сеть доступна.",
  "The device passed it on, and {from} replied that nothing is at {addr}. Check the address.": "Устройство передало запрос дальше, и {from} ответил, что по адресу {addr} никого нет. Проверьте адрес.",
  "The device passed it on, but nothing is at {addr}. Check the address.": "Устройство передало запрос дальше, но по адресу {addr} никого нет. Проверьте адрес.",
  "{node} sent it through the device, which is connected, and nothing came back. The device has to pass traffic on to its network and send the answers back — see “Set up the device's side”.": "{node}: запрос ушёл через устройство, оно подключено, но ответа нет. Устройство должно пропускать трафик в свою сеть и возвращать ответы — см. «Настройка на стороне устройства».",
  "Some devices ignore pings. If {addr} might, test a port it listens on.": "Некоторые устройства не отвечают на ping. Если {addr} из таких, проверьте порт, который он слушает.",
  "The device isn't connected to {node}, so nothing reaches {addr} through it.": "Устройство не подключено к {node}, поэтому через него до {addr} ничего не доходит.",
  "{node} doesn't carry this network, so nothing was sent.": "{node} не проводит эту сеть, запрос не отправлен.",
  "{node} would send {addr} out through {dev}, not through this device, so nothing was sent — clients on this interface can't reach it either.": "{node}: трафик к {addr} ушёл бы через {dev}, а не через это устройство, поэтому запрос не отправлен — клиенты этого интерфейса туда тоже не попадают.",
  "{node} has no route to {addr} yet, so nothing was sent.": "{node}: маршрута к {addr} пока нет, запрос не отправлен.",
  "{node} doesn't let this device carry {addr} yet, so nothing was sent. It catches up within a sync — test again in a moment.": "{node}: это устройство пока не допущено к {addr}, запрос не отправлен. Нода догонит за одну синхронизацию — проверьте ещё раз чуть позже.",
  "{node} isn't sending {addr} through this device, so it didn't test it.": "{node}: {addr} не направляется через это устройство, проверка не выполнена.",
  "{addr} is the network's own address or its broadcast — test a device on it.": "{addr} — адрес самой сети или широковещательный. Проверьте устройство в этой сети.",
  "{node} can't read its own address on this interface, so it had nothing to send from.": "{node}: не удалось прочитать собственный адрес на этом интерфейсе — отправлять не с чего.",
  "{node} took the test but never answered — it may run a version that can't test networks. Update it.": "{node}: запрос на проверку получен, но ответа так и не было — возможно, версия ноды не умеет проверять сети. Обновите ноду.",
  "{node} didn't pick up the test in time. Check it's online, then test again.": "{node}: нода не забрала проверку вовремя. Убедитесь, что она в сети, и проверьте ещё раз.",
  "{node} couldn't run the test: {detail}": "{node}: проверку выполнить не удалось: {detail}",
  "{node} couldn't run the test.": "{node}: проверку выполнить не удалось.",
  "{addr} isn't an IPv4 address.": "{addr} — не IPv4-адрес.",
  "A port is a number from 1 to 65535.": "Порт — это число от 1 до 65535.",
  "This device isn't on {node}.": "Этого устройства нет на {node}.",
  "{node} isn't syncing, so it can't run a test right now.": "{node} не синхронизируется, проверку сейчас не запустить.",
  // the networks endpoints' own errors — the SPA words every refusal token itself, so these reach a person only
  // through an API call the sheet does not make, or a token newer than the sheet
  "test refused: {v1}": "проверка отклонена: {v1}",
  "a test is already running on this node": "на этой ноде уже идёт проверка",
  "no such test": "такой проверки нет",
  "network refused": "сеть отклонена",
  "share refused": "настройки доступа не сохранены",
  "routes must be a list of CIDR strings": "routes должен быть списком строк CIDR",
  "{node} is already running a test — try again in a few seconds.": "{node} уже выполняет проверку — повторите через несколько секунд.",
  "{addr} is in {p}, which this device doesn't carry:": "{addr} входит в {p}, а эту сеть устройство не проводит:",
  "{addr} isn't in a network this device carries on {node}, so it can't be tested from there.": "{addr} не входит ни в одну сеть, которую это устройство проводит на {node}, поэтому проверить его оттуда нельзя.",
  "Couldn't start the test.": "Не удалось запустить проверку.",
  "The panel no longer has that test — run it again.": "Этой проверки в панели уже нет — запустите её снова.",
  "Tested a network": "Проверена доступность сети",
  // budget-ok: notice, wraps
  "This device's config for {node} sends no keepalive, so {node} loses its session when the device goes quiet — and these networks with it. Set a keepalive on that deployment.": "Конфиг этого устройства для {node} не шлёт keepalive: когда устройство затихает, {node} теряет сессию, а с ней и эти сети. Задайте keepalive для этого развёртывания.",
  // the node's own local network (P2) — a disclosure on the node page, with the switch that closes it
  "Local network": "Локальная сеть",
  "Clients can reach it": "Клиентам доступна",
  "Keep this node's clients off its local network": "Закрыть локальную сеть ноды от её клиентов",
  "Let this node's clients reach its local network": "Открыть локальную сеть ноды её клиентам",
  "Clients of this node can reach its local network again.": "Клиентам ноды снова доступна её локальная сеть.",
  "Clients of this node are now kept off its local network.": "Локальная сеть ноды закрыта от её клиентов.",
  "This node runs a version that can't close its local network — update it. Until then its clients still reach it.": "Версия ноды не умеет закрывать локальную сеть — обновите ноду. Пока клиенты по-прежнему в неё попадают.",
  "Waiting for the node to close it.": "Ждём, пока нода её закроет.",
  "Closed on the node.": "Закрыто на ноде.",
  "The node couldn't read its own addresses, so it left the block as it was.": "Нода не смогла прочитать свои адреса и оставила блокировку как была.",
  "The node couldn't close it, so its clients still reach it: {why}": "Нода не смогла её закрыть, клиенты по-прежнему в неё попадают: {why}",
  // budget-ok: panel body, wraps
  "Clients of this node can reach the private network it sits on — every device on it, not only this node — and so can clients of other nodes whose traffic leaves through this one. A client whose traffic this node sends on to another node reaches that node's network instead. Nobody set this up: it is what routing does when the node's local network is also its way out.":
    "Клиенты этой ноды попадают в частную сеть, в которой она стоит, — на любое устройство в ней, а не только на саму ноду, — как и клиенты других нод, чей трафик выходит через эту. Клиент, чей трафик эта нода отправляет дальше на другую ноду, попадает в сеть той ноды. Этого никто не настраивал: так работает маршрутизация, когда локальная сеть ноды — это и её выход в интернет.",
  "Clients of this node, and of other nodes whose traffic leaves through it, are kept off the private network it sits on. They still reach the internet and this node itself.":
    "Клиенты этой ноды и других нод, чей трафик выходит через неё, не попадают в частную сеть, в которой она стоит. Интернет и сама нода им по-прежнему доступны.",

  // ── geo providers: what turning one off actually costs (§6.4) ──
  // Reads on the row itself, in the same quiet register as «обновлён 3 ч назад» beside it. Both counts are
  // prepositional: «в 3 правилах на 2 интерфейсах» — see the prep| forms in PLURALS.
  "used by {v1} on {v2}": "используется в {v1} на {v2}",
  "Rules on your interfaces that route one of this provider's lists":
    "Правила на ваших интерфейсах, которые маршрутизируют один из списков этого источника",
  "Turn off {v1}?": "Выключить {v1}?",
  "Turn it off": "Выключить",
  // «перестанут маршрутизировать», not «отключатся»: the rules are still there and still say what they said —
  // the node simply stops being given the list they name, which is the thing the operator has to picture.
  "*{v1}* is used by {v2} on {v3}. Turning it off hides its lists and stops those rules routing on every node — the rules themselves stay, and start working again when you turn it back on. Nothing reaches the fleet until you save.":
    "*{v1}* используется в {v2} на {v3}. После выключения его списки скрываются, и на всех нодах эти правила перестают маршрутизировать — сами правила остаются и снова заработают, когда вы включите источник обратно. До сохранения на ноды ничего не уходит.",
  // ── geo providers: a download you can get out of (§6.3) ──
  // budget-ok: toast, wraps
  "Couldn't cancel": "Не удалось отменить",
  "Fetching this provider's catalog — cancel to stop waiting": "Каталог источника скачивается — нажмите «Отмена», чтобы не ждать",
  "Reading this provider's file list from GitHub. Its lists become searchable when it lands; nothing is routed yet.":
    "Панель читает список файлов этого источника с GitHub. Как только он придёт, его списки появятся в поиске; маршрутизировать пока нечего.",
  // The number is the point: GitHub answers 60 requests an hour without an account, and once you are over it a
  // single fetch can sit for minutes. Saying so is what makes Cancel look like a sane thing to press.
  "GitHub allows 60 requests an hour without an account, and a fetch inside that window can sit for a couple of minutes. Cancelling stops the wait and turns the provider off — the request itself finishes on its own and its result is thrown away.":
    "GitHub без учётной записи отвечает на 60 запросов в час, и запрос, попавший в исчерпанное окно, может висеть пару минут. Отмена прекращает ожидание и выключает источник: сам запрос дойдёт до конца сам по себе, а его результат будет отброшен.",
  // ── the routing rule builder's field (docs/ROUTING-RULE-BUILDER-PLAN.md §3) ──
  // The kind label sits in a chip beside the value and has to fit there, so each is one short word. They name
  // what the operator WROTE, not the matcher underneath — «сайт», not «суффикс».
  "kind|site": "сайт",
  "kind|zone": "зона",
  "kind|name": "имя",
  "kind|contains": "внутри",
  "kind|starts with": "начало",
  "kind|ends with": "конец",
  "kind|IP range": "диапазон IP",
  "kind|network": "сеть",
  "{v1} and every name under it — www.{v1}, mail.{v1}…": "{v1} и всё, что под ним — www.{v1}, mail.{v1}…",
  "Every address ending in {v1} — millions of sites": "Любой адрес, оканчивающийся на {v1} — миллионы сайтов",
  "Any address whose first part is {v1} — {v1}.com, {v1}.ru, {v1}.de": "Любой адрес, у которого первая часть — {v1}: {v1}.com, {v1}.ru, {v1}.de",
  "Any address with {v1} as one of its parts": "Любой адрес, в котором {v1} — одна из частей",
  "Any address with {v1} anywhere in it — also matches not{v1}.com": "Любой адрес, где {v1} встречается где угодно — в том числе not{v1}.com",
  "Any address whose text starts with {v1} — also matches {v1}mail.com": "Любой адрес, текст которого начинается на {v1} — в том числе {v1}mail.com",
  "Any address whose text ends with {v1} — also matches not{v1}": "Любой адрес, текст которого оканчивается на {v1} — в том числе not{v1}",
  "One address": "Один адрес",
  "{v1} addresses": "Адресов: {v1}",
  "All IP ranges announced by {v1}": "Все IP-диапазоны, анонсируемые {v1}",
  // A bare label is never guessed for the operator — the whole point is that «ru» and «*.ru» differ by six
  // orders of magnitude. The sentence shows the syntax instead of applying it.
  "Did you mean the whole .{v1} zone? Write *.{v1}.": "Имеется в виду вся зона .{v1}? Тогда пишите *.{v1}.",
  "That isn't a valid IP address or range.": "Это не IP-адрес и не диапазон.",
  "That isn't a valid web address.": "Это не веб-адрес.",
  "{v1} this engine can't match at all — switch this node's mode, or route them from a node that can": "{v1} этот движок вообще не сопоставляет — смените режим этой ноды или ведите их через другую",
  "A * goes at the start or the end of a name, not in the middle.": "Звёздочка ставится в начале или в конце имени, но не в середине.",
  "Put one name between the stars, not a dotted address.": "Между звёздочками ставится одно имя, а не адрес с точками.",
  "A partial-word match can't be written in non-Latin letters — names travel already encoded.":
    "Совпадение по части слова нельзя записать не латиницей — имена передаются уже в кодированном виде.",
  // Не «слишком короткий фрагмент», а что из этого выйдет: «*ru*» читается как «российские сайты», а
  // ловит ruble.com и truecaller.com. Показываем последствие, а не правило.
  "Too short to match on — under {v1} characters this catches names that have nothing to do with what you meant.":
    "Слишком короткий фрагмент: меньше {v1} символов — и под него попадут имена, не имеющие отношения к тому, что вы имели в виду.",
  "Only {v1} long — a short fragment turns up inside names that have nothing to do with it.":
    "Всего {v1} — короткий фрагмент встречается внутри имён, не имеющих к нему отношения.",
  "That isn't an address, IP range or AS number.": "Это не адрес, не диапазон IP и не номер AS.",
  "This panel doesn't route this kind of address yet — it's classified and stored, but no node can match it.":
    "Панель пока не маршрутизирует такие адреса — запись разбирается и сохраняется, но сопоставить её не может ни одна нода.",
  "No engine on this node routes this kind yet — {v1} does.":
    "Движок этой ноды пока не маршрутизирует такие адреса — а «{v1}» умеет.",
  "Switched off for this node in Settings ▸ Routing & Blocking.": "Отключён для этой ноды в «Настройки ▸ Маршрутизация».",
  "This list's provider is switched off — turn it back on in Settings ▸ Geo data providers.":
    "Источник этого списка выключен — включите его в «Настройки ▸ Провайдеры гео-данных».",
  "Stored and matched as {v1}.": "Хранится и сопоставляется как {v1}.",
  "{v1} matches by IP only — this needs a host layer.": "{v1} сопоставляет только по IP — здесь нужен слой доменов.",
  "{v1} only asks whether some text appears somewhere in a name — it never learns WHERE, so it can't anchor to a beginning, an ending or a label.": "{v1} лишь проверяет, встречается ли текст где-то в имени, и не узнаёт ГДЕ, — поэтому не может привязаться ни к началу, ни к окончанию, ни к части имени.",
  "{v1} matches a whole name and everything under it — never a single label on its own, and never part of a name.": "{v1} сопоставляет имя целиком и всё, что под ним, — но не отдельную часть имени саму по себе и не фрагмент имени.",
  "Not a valid address, IP range or AS number.": "Не адрес, не диапазон IP и не номер AS.",
  "empty": "пусто",
  "The panel is fetching this list now — it routes as soon as it lands.": "Панель как раз скачивает этот список — он заработает сразу после загрузки.",
  "preparing…": "готовится…",
  "The panel hasn't fetched this list yet. The rule saves either way and routes as soon as it lands — click to ask again.":
    "Панель ещё не скачала этот список. Правило всё равно сохранится и заработает сразу после загрузки — нажмите, чтобы запросить снова.",
  "not ready": "не готов",
  // budget-ok: title, no layout
  "On this node it is matched as text anywhere in the name.": "На этой ноде сопоставляется как текст в любом месте имени.",
  "Custom": "Свой",
  "Switch this node to {v1}": "Переключить эту ноду на {v1}",
  // budget-ok: aria-live, never rendered
  "Added {v1}": "Добавлено: {v1}",
  "Already in this rule.": "Уже есть в этом правиле.",
  "{v1} was not added": "{v1} не добавлено",
  "Removed {v1}": "Удалено: {v1}",
  "Your lists": "Ваши списки",
  // budget-ok: aria-live, never rendered
  "{v1} added, {v2} left to fix": "Добавлено: {v1}, осталось исправить: {v2}",
  "+{v1} more": "ещё {v1}",
  "show fewer": "свернуть",
  "add another…": "добавить ещё…",
  "Search a service, or type an address, IP range or AS number…": "Найдите сервис или впишите адрес, диапазон IP либо номер AS…",
  "An estimate from what the panel has resolved so far. The node's own report is the authority once it syncs.":
    "Оценка по тому, что панель успела развернуть. После синхронизации точные цифры даёт сама нода.",
  "Try a service name like *YouTube*, or type an address, IP range or AS number.":
    "Впишите название сервиса, например *YouTube*, либо адрес, диапазон IP или номер AS.",
  "Use what you typed": "Взять то, что вписано",
  // budget-ok: centred in a full-width popover
  "Keep typing to search the provider catalog.": "Продолжайте вводить — поиск пойдёт по каталогу источников.",
  "Type a service name, an address, an IP range or an AS number.": "Впишите название сервиса, адрес, диапазон IP или номер AS.",
  // the same two invitations in a CUSTOM LIST, which has no catalog to search — offering to find a
  // service there points at something that is not on the screen
  "Type an address, IP range, AS number or pattern.": "Впишите адрес, диапазон IP, номер AS или шаблон.",
  "Address, IP range, AS number or pattern…": "Адрес, диапазон IP, номер AS или шаблон…",
  "Switch {v1} to {v2}?": "Переключить {v1} на {v2}?",
  // budget-ok: sheet-footer button, sizes to content
  "Switch mode": "Переключить режим",
  "This reprovisions the node so it can match by hostname. IP rules keep working, and the rule changes you have open stay open — save them afterwards.":
    "Нода будет перенастроена, чтобы сопоставлять по именам. Правила по IP продолжат работать, а открытые правки правил никуда не денутся — сохраните их после этого.",
  // budget-ok: toast, wraps
  "Switched to {v1} — save to apply your rules.": "Переключено на {v1} — сохраните, чтобы применить правила.",
  "Nothing on any node has ever read a stored TLD rule. It is kept exactly as written until the migration converts it.":
    "Сохранённое правило по TLD не читала ещё ни одна нода. Оно хранится ровно так, как записано, пока миграция его не преобразует.",
  "A legacy TLD rule — kept as written, and it has never routed anything.":
    "Старое правило по TLD — хранится как записано и ещё ничего не маршрутизировало.",
  "Stored as written — this rule is kept exactly as it is.": "Хранится как записано — это правило остаётся ровно таким.",
  "already sent somewhere else above: {toks}": "выше уже отправлено в другое место: {toks}",
  "a more specific rule below wins these hosts: {toks}": "ниже есть более точное правило — эти адреса забирает оно: {toks}",
  "a more specific rule below wins these hosts for the people it names: {toks}": "ниже есть более точное правило для выбранных людей — у них эти адреса забирает оно: {toks}",
  "No rules yet. Add a rule to send some destinations through another node, or set *Everything else* to channel everything.":
    "Правил пока нет. Добавьте правило, чтобы отправить часть назначений через другую ноду, или укажите в *Всё остальное*, куда идёт весь трафик.",
  "No rules yet. Add a rule to send some destinations out a device on this node or block them, or set *Everything else* to say where the rest goes.":
    "Правил пока нет. Добавьте правило, чтобы выпустить часть назначений через устройство на этой ноде или заблокировать их, или укажите в *Всё остальное*, куда идёт остальной трафик.",
  // The egress option used to be named after the mechanism ("умная маршрутизация"); this names the outcome.
  "Routing (smart cascade)": "Маршрутизация (умный каскад)",
  "A rule needs at least one service, address or IP range.": "В правиле нужен хотя бы один сервис, адрес или диапазон IP.",
  // Type-to-confirm tokens. Localised on purpose: the friction is meant to be a phrase the operator reads
  // and retypes, which a Latin string on a Russian panel is not. Uppercase, and distinct from each other.
  "token|RESET LEARNED": "СБРОС ОБУЧЕННЫХ",
  "token|RESET ALL": "СБРОС ВСЕГО",
  "Ports blocked": "Блок по портам",
  "Filtering *{v1}* across *{v2}*": "Фильтруется *{v1}* на *{v2}*",
  "Filtering *{v1}*": "Фильтруется *{v1}*",
  "Mechanism blocking across *{v1}*": "Блокировка по механизмам на *{v1}*",
  "Torrents": "Торренты",
  "Spam / SMTP": "Спам / SMTP",
  "Mining": "Майнинг",
  "Each row is a round trip measured from that node, so both cross the link in both directions — a difference between them is two samples of the same link, not a direction.": "Каждая строка — это круговая задержка, измеренная с этой ноды, поэтому обе проходят связь в обе стороны: разница между ними — это два замера одной и той же связи, а не две стороны.",
  // ── datapath (relay) ──
  "This leg is losing *{v1}%* right now — that is the case for Relay.": "Связь сейчас теряет *{v1}%* — это как раз случай для Релея.",
  "This leg is clean right now — *Forward* is the cheaper choice.": "Связь сейчас чистая — *Транзит* дешевле.",
  "Phrase copied": "Фраза скопирована",
  "csqtt server": "Сервер csqtt",
  "Endpoint & listen port are edited from the csqtt-proxy modal.": "Эндпоинт и порт прослушивания правятся в окне csqtt-прокси.",
  // ── shared VK call-link pool ──
  "Remove every link in the pool?": "Удалить все ссылки из пула?",
  "REMOVE ALL": "УДАЛИТЬ ВСЁ",
  "Remove them all": "Удалить все",
  "The whole pool is removed ({v1}). Anyone holding one is left without it, and there is nothing left to hand out — new users get no link until you add one.": "Удаляется весь пул ({v1}). Те, у кого они были, останутся без ссылки, и выдавать станет нечего — новые пользователи не получат ничего, пока вы не добавите ссылку.",
  "Remove all": "Удалить все",
  "Links handed out to users *at random* — a new user gets them automatically, and you can give anyone more from the pool in their *Manage* view.": "Ссылки раздаются пользователям *случайным образом*: новый пользователь получает их автоматически, а выдать ещё можно в его разделе *Управление*.",
  "{v1} in use": "{v1} в работе",
  "held by {v1}": "у {v1}",
  "Sort by when it was added": "Сортировать по дате добавления",
  "Sort by how many users hold it": "Сортировать по числу пользователей",
  "Sort by alive or dead": "Сортировать по статусу",
  "Added {v1}.": "Добавлено {v1}.",
  "Removed {v1}.": "Удалено {v1}.",
  "Add links": "Добавить",
  "Paste one link per line — or separated by commas or spaces": "Вставьте по одной ссылке в строку — или через запятую либо пробел",
  "{v1} of these isn't a VK call link.": "{v1} из них не ссылка на VK-звонок.",
  "{v1} ready to add": "{v1} к добавлению",
  "Paste one or many.": "Одну или больше.",
  "When it was added": "Когда добавлена",
  "Remove every dead link?": "Удалить все мёртвые ссылки?",
  "Remove them": "Удалить",
  "The {v1} in the pool marked dead will be removed, and anyone still holding one moves to a live link.": "{v1} в пуле, отмеченные мёртвыми, будут удалены, а те, у кого они ещё остались, перейдут на живую.",
  "Remove dead ({v1})": "Удалить мёртвые ({v1})",
  "View all ({v1})": "Показать все ({v1})",
  "View": "Открыть",
  "Enter a VK call link.": "Введите VK-ссылку.",
  "{v1} — moved {v2} to another link.": "{v1} {v2} переведено на другую ссылку.",
  "Link updated.": "Обновлена.",
  "Link added.": "Добавлена.",
  "Marked alive.": "Живая.",
  "Marked dead.": "Мёртвая.",
  "Link removed.": "Удалена.",
  "Save this link (or press Enter)": "Сохранить ссылку (или нажмите Enter)",
  "Mark as alive — hand it out again": "Отметить живой — снова выдавать",
  "Mark as dead — stop handing it out and move its users off": "Отметить мёртвой — перестать выдавать и перевести её пользователей",
  "Reopen the pool and try again.": "Откройте пул заново и попробуйте ещё раз.",
  "Apps differ: some use every link, some only the first few, some only the primary — the star sets which comes first.": "Приложения ведут себя по-разному: одни берут все ссылки, другие только первые несколько, третьи только основную — звезда задаёт, какая идёт первой.",
  "The pool changed somewhere else while you were editing. Reopen it and redo your change.": "Пул изменили в другом месте, пока вы правили. Откройте заново и повторите изменение.",
  "The primary link — single-link apps use this one": "Основная ссылка — её берут приложения с одной ссылкой",
  "From the shared pool — change it in Settings → Turn proxies, or remove it here": "Из общего пула — измените её в «Настройки → Turn-прокси» или уберите здесь",
  "VK call links": "VK-ссылки",
  "The pool holds at most {v1} links.": "В пуле может быть не больше {v1} ссылок.",
  "{v1} doesn't look like a VK call link.": "{v1} не похоже на ссылку на VK-звонок.",
  "{v1} is already in the pool.": "{v1} уже есть в пуле.",
  "No unused link left in the pool.": "В пуле не осталось свободных ссылок.",
  "Couldn't add a link from the pool": "Не удалось добавить ссылку из пула",
  "Added a link from the pool.": "Ссылка из пула добавлена.",
  "Saved {v1}.": "Готово: {v1}.",
  "Give this user one more link from the shared pool": "Выдать этому пользователю ещё одну ссылку из общего пула",
  "No unused link left in the shared pool": "В общем пуле не осталось свободных ссылок",
  "Add from pool": "Добавить из пула",
  "Couldn't save the VK pool": "Не удалось сохранить пул ссылок",
  "Shared VK call link pool": "Общий пул ссылок на VK-звонки",
  "Users holding this link": "Пользователей с этой ссылкой",
  "Remove from the pool": "Убрать из пула",
  "The pool is empty — add links and new users will get them automatically.": "Пул пуст — добавьте ссылки, и новые пользователи будут получать их автоматически.",
  "Links per new user": "Ссылок новому пользователю",
  "The pool is empty.": "Пул пуст.",
  "Links handed out to users *at random* — from the pool in their *Manage* view. New users get none automatically while the setting below is 0.": "Ссылки раздаются пользователям *случайным образом* — из пула в их разделе *Управление*. Пока настройка ниже равна 0, новые пользователи ничего не получают автоматически.",
  "Taken from the pool, least-used first, when a user is created (0 = none). Existing users keep what they have.": "Берутся из пула при создании пользователя, сначала наименее занятые (0 — не выдавать). У существующих пользователей ничего не меняется.",
  "New users will get {v1}.": "Новые пользователи получат {v1}.",
  "Between 0 and {v1}.": "От 0 до {v1}.",
  "The same link is in the pool twice.": "Эта ссылка добавлена в пул дважды.",
  "No live links left — users on a dead link will keep it until you add a working one.": "Живых ссылок не осталось — пока не добавите рабочую, пользователи останутся на мёртвой.",
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
  "converting to bare-metal": "конвертация в bare-metal",
  "converting to docker": "конвертация в docker",
  "updating": "обновление",
  "uninstalling": "удаление",
  "re-installed": "переустановлен",
  "re-installed and updated": "переустановлен и обновлён",
  "converted to bare-metal": "конвертирован в bare-metal",
  "converted to docker": "конвертирован в docker",
  "updated": "обновлён",
  "changed": "изменился",
  "couldn't check": "не удалось проверить",
  "*GitHub is rate-limiting this panel* for the few sources the published list does not cover, so those rows could not be checked — it is the budget, not the sources. It clears in about {v1} min.":
    "*GitHub ограничивает частоту запросов от этой панели* для тех немногих источников, которых нет в опубликованном списке, — поэтому эти строки проверить не удалось. Дело в лимите, а не в источниках. Он снимется примерно через {v1} мин.",
  "*This panel could not fetch the published client fingerprints*, so it fell back to asking GitHub directly and hit the 60-an-hour limit. Check that the panel can reach *raw.githubusercontent.com* — with it, these rows cost no GitHub budget at all. It clears in about {v1} min.":
    "*Панели не удалось получить опубликованные отпечатки клиентов*, поэтому она обратилась к GitHub напрямую и упёрлась в лимит 60 запросов в час. Проверьте, что панель может достучаться до *raw.githubusercontent.com* — с ним эти строки не тратят лимит GitHub вообще. Лимит снимется примерно через {v1} мин.",
  "not watched": "не отслеживается",
  "Take this interface over: stop that container and run the same server here, keeping its key, port and peers":
    "Перенять этот интерфейс: остановить тот контейнер и поднять тот же сервер здесь, сохранив его ключ, порт и пиров",
  "Take over {v1}":
    "Перенять {v1}",
  "Take it over":
    "Перенять",
  "swgPanel will STOP the container {v1} and run {v2} here instead — same key, same port, same obfuscation, so the configs already on your users' devices keep working, and its peers are imported. That container is only stopped, never deleted: if anything goes wrong the node starts it again, and you can start it yourself to go back. It will not come back on its own afterwards. Give it up to a minute: the container gets a grace period to shut down cleanly, and its runtime takes a moment to clear it away.":
    "swgPanel ОСТАНОВИТ контейнер {v1} и поднимет {v2} здесь — тот же ключ, тот же порт, та же обфускация, поэтому конфигурации, уже стоящие на устройствах ваших пользователей, продолжат работать, а его пиры будут импортированы. Контейнер только останавливается, но не удаляется: если что-то пойдёт не так, нода запустит его снова, и вы сами можете запустить его, чтобы вернуться назад. Сам по себе он больше не поднимется. Дайте до минуты: контейнеру отводится время на корректное завершение, и его среде выполнения нужен момент, чтобы его убрать.",
  "Taking it over — the node does this on its next sync.":
    "Перенимаем — нода сделает это на следующей синхронизации.",
  "Couldn't start the take-over.":
    "Не удалось начать перенос.",
  "took over a container's interface":
    "интерфейс контейнера перенят",
  "container take-over failed":
    "не удалось перенять контейнер",
  "Running inside container {v1} — swgPanel cannot manage it there":
    "Работает внутри контейнера {v1} — swgPanel не может им там управлять",
  "Another program owns this interface: it runs in its own container, from its own config. swgPanel can see it, but a change made here would be undone the next time that container restarts.":
    "Этим интерфейсом владеет другая программа: он работает в своём контейнере и со своей конфигурацией. swgPanel его видит, но изменение, сделанное здесь, откатится при следующем перезапуске того контейнера.",
  "tag|creating": "создаётся",
  "tag|onboarding": "подключается",
  "The node could not set it up — open the error for what to do":
    "Нода не смогла его настроить — откройте ошибку, чтобы понять, что делать",
  "the node refused — open the error above": "нода отказала — откройте ошибку выше",
  "tag|alien": "чужой",
  "its config wasn't published to the subscription — {v1}":
    "его конфиг не попал в подписку — {v1}",
  "Another program is running this server — taking it over stops it first":
    "Этот сервер запущен другой программой — при перенятии он будет сначала остановлен",
  "tag|failed": "не удалось",
  "Took {i} over from container {c} — {n} imported. That container is stopped and will not restart; delete it once you are happy, or start it again to go back.":
    "{i} перенят из контейнера {c} — импортировано: {n}. Тот контейнер остановлен и сам не поднимется; удалите его, когда убедитесь, что всё в порядке, или запустите снова, чтобы вернуться назад.",
  "Taking {i} over from container {c} did not finish within {m} min — the node never reported back. Nothing was taken over; check the node is online and try again.":
    "Перенять {i} из контейнера {c} не удалось за {m} мин — нода так и не ответила. Ничего не перенято; проверьте, что нода на связи, и попробуйте ещё раз.",
  "blank = random": "пусто = случайно",
  "AmneziaWG obfuscation": "Обфускация AmneziaWG",
  "settings|customised": "изменено",
  "settings|built-in": "встроенная",
  "Given to every new AmneziaWG interface. Leave a cell blank to keep what the node does today — S and H are rolled fresh for each interface, so two interfaces never look alike. WireGuard interfaces ignore all of it.":
    "Выдаётся каждому новому интерфейсу AmneziaWG. Оставьте поле пустым, чтобы всё осталось как сейчас: S и H нода заново разыгрывает для каждого интерфейса, поэтому два интерфейса никогда не выглядят одинаково. Интерфейсы WireGuard всё это игнорируют.",
  "{i} in {c} serves {s}, which overlaps {o} already on this node. In its own container that is fine — each has its own network namespace — but taking it over moves it here, where one subnet cannot be served twice. Take over only one of them, or renumber the other first. Nothing was changed.":
    "{i} в {c} обслуживает {s}, а эта подсеть пересекается с {o}, которая уже есть на этой ноде. В своём контейнере это нормально — у каждого своё сетевое пространство имён, — но перенос переносит интерфейс сюда, где одну подсеть нельзя обслуживать дважды. Перенесите только один из них или сначала смените адресацию у другого. Ничего не изменено.",
  "{i} in {c} is {p}, and this node does not have the {p} tools ({t} and {t}-quick) to stand it up. Install them, then take it over again — {c} was not touched and is still serving.":
    "{i} в {c} — это {p}, а на этой ноде нет инструментов {p} ({t} и {t}-quick), чтобы его поднять. Установите их и повторите перенос — {c} не тронут и продолжает обслуживать клиентов.",
  "AmneziaWG tools are not installed on this node, and this node's installation is managed declaratively — re-running an installer would not survive its next rebuild. Add the AmneziaWG tools to the system configuration that declares this node and rebuild it, then this interface creates itself on the next sync.":
    "На этой ноде не установлены инструменты AmneziaWG, а установка этой ноды описана декларативно — повторный запуск установщика не переживёт следующую пересборку. Добавьте инструменты AmneziaWG в конфигурацию системы, которая описывает эту ноду, и пересоберите её — интерфейс создастся сам на следующей синхронизации.",
  "AmneziaWG tools are not installed on this node. Re-run the swgPanel node installer — it builds them from source on any distribution, and falls back to the userspace datapath where the kernel module cannot load. Then this interface creates itself on the next sync.":
    "На этой ноде не установлены инструменты AmneziaWG. Запустите установщик ноды swgPanel заново — он соберёт их из исходников на любом дистрибутиве, а там, где модуль ядра не поднимается, перейдёт на датапас в пользовательском пространстве. После этого интерфейс создастся сам на следующей синхронизации.",
  "AmneziaWG is only half-installed on this node: awg is present but awg-quick is missing. Re-run the swgPanel node installer — it builds both from source — then this interface creates itself on the next sync.":
    "AmneziaWG на этой ноде установлен наполовину: awg есть, а awg-quick нет. Запустите установщик ноды swgPanel заново — он соберёт оба из исходников, — и интерфейс создастся сам на следующей синхронизации.",
  "WireGuard tools are not installed on this node. Install them with your package manager (on Debian/Ubuntu: apt-get install -y wireguard), then this interface creates itself on the next sync.":
    "На этой ноде не установлены инструменты WireGuard. Установите их пакетным менеджером (в Debian/Ubuntu: apt-get install -y wireguard), и интерфейс создастся сам на следующей синхронизации.",
  "WireGuard tools are not installed on this node, and this node's installation is managed declaratively — installing them by hand would not survive its next rebuild. Add the WireGuard tools to the system configuration that declares this node and rebuild it, then this interface creates itself on the next sync.":
    "На этой ноде не установлены инструменты WireGuard, а установка этой ноды описана декларативно — установка их вручную не переживёт следующую пересборку. Добавьте инструменты WireGuard в конфигурацию системы, которая описывает эту ноду, и пересоберите её — интерфейс создастся сам на следующей синхронизации.",
  "AmneziaWG is only half-installed on this node: awg is present but awg-quick is missing. This node's installation is managed declaratively, so it has to be completed in the system configuration that declares this node rather than by an installer run here — add the full AmneziaWG tools and rebuild, then this interface creates itself on the next sync.":
    "AmneziaWG на этой ноде установлен наполовину: awg есть, а awg-quick нет. Установка этой ноды описана декларативно, поэтому доводить её надо в конфигурации системы, которая описывает эту ноду, а не установщиком, запущенным здесь, — добавьте полный набор инструментов AmneziaWG и пересоберите, после чего интерфейс создастся сам на следующей синхронизации.",
  "this node could not execute the tools that bring an interface up: the kernel refused to start them, so the bring-up never began. This is not a port or subnet conflict. This node's installation is managed declaratively, so this belongs in the system configuration that declares it rather than in a command here: the node daemon must not set NoNewPrivileges, and the security policy and capability set that configuration gives this node have to let the WireGuard tools execute. Restart the node daemon once the change is in — a rebuild does not restart it on its own, so the old unit keeps running.":
    "эта нода не смогла запустить инструменты, которыми поднимается интерфейс: ядро отказалось их стартовать, поэтому подъём даже не начался. Это не конфликт порта или подсети. Установка этой ноды описана декларативно, поэтому это относится к конфигурации системы, которая её описывает, а не к команде здесь: демон ноды не должен выставлять NoNewPrivileges, а политика безопасности и набор capabilities, которые эта конфигурация даёт ноде, должны позволять запускать инструменты WireGuard. Перезапустите демон ноды, когда изменение внесено, — пересборка сама его не перезапускает, и продолжает работать старый юнит.",
  "this node could not execute the tools that bring an interface up: AppArmor refused to start them, so the bring-up never began. This is not a port or subnet conflict. This distribution enforces an AppArmor profile for the WireGuard tools, and a confined program may not switch into its child profile while the calling service runs with NoNewPrivileges — which the node daemon does on an installation older than 1.8.7-beta; updating the node removes it. In dmesg the denial reads: apparmor=\"DENIED\" operation=\"exec\" info=\"no new privs\". To clear it by hand, put those profiles into complain mode on the node:  aa-complain /usr/bin/wg /usr/bin/wg-quick  (apt-get install -y apparmor-utils if that command is missing) — then this interface creates itself on the next sync.":
    "эта нода не смогла запустить инструменты, которыми поднимается интерфейс: AppArmor отказался их стартовать, поэтому подъём даже не начался. Это не конфликт порта или подсети. В этом дистрибутиве для инструментов WireGuard включён профиль AppArmor в режиме enforce, а программа под профилем не может переключиться в дочерний профиль, пока вызывающая служба работает с NoNewPrivileges — так работает демон ноды на установках старше 1.8.7-beta; обновление ноды это убирает. В dmesg отказ выглядит так: apparmor=\"DENIED\" operation=\"exec\" info=\"no new privs\". Чтобы снять вручную, переведите эти профили в режим complain на ноде:  aa-complain /usr/bin/wg /usr/bin/wg-quick  (если команды нет — apt-get install -y apparmor-utils), после чего интерфейс создастся сам на следующей синхронизации.",
  "this node could not execute the tools that bring an interface up: AppArmor refused to start them, so the bring-up never began. This is not a port or subnet conflict. A confined program may not switch into its child profile while the calling service runs with NoNewPrivileges, and this node's installation is managed declaratively — so the fix belongs in the system configuration that declares this node, not in a command here: the node daemon must not set NoNewPrivileges, and the AppArmor policy for the WireGuard tools has to allow /run/wireguard so userspace interfaces stay readable. Restart the node daemon once it is in — a rebuild does not restart it on its own, so the old unit keeps running. Then this interface creates itself on the next sync.":
    "эта нода не смогла запустить инструменты, которыми поднимается интерфейс: AppArmor отказался их стартовать, поэтому подъём даже не начался. Это не конфликт порта или подсети. Программа под профилем не может переключиться в дочерний профиль, пока вызывающая служба работает с NoNewPrivileges, а установка этой ноды описана декларативно — поэтому исправление принадлежит конфигурации системы, которая описывает эту ноду, а не команде здесь: демон ноды не должен выставлять NoNewPrivileges, а политика AppArmor для инструментов WireGuard должна разрешать /run/wireguard, чтобы userspace-интерфейсы оставались читаемыми. Перезапустите демон ноды, когда это будет внесено, — пересборка сама его не перезапускает, и продолжает работать старый юнит. После этого интерфейс создастся сам на следующей синхронизации.",
  "this node could not execute the tools that bring an interface up: the kernel refused to start them, so the bring-up never began. This is not a port or subnet conflict, and the datapath module is not the problem. Either those binaries carry file capabilities that this node's capability bounding set no longer covers, or an exec-control layer (SELinux, fapolicyd, or an AppArmor policy this node cannot read) is denying them. Run on the node:  getcap $(command -v ip) $(command -v wg) $(command -v awg)  for the first, and  dmesg | grep -i 'denied'  for the second — one of them names it. Once the tools run again, this interface creates itself on the next sync.":
    "эта нода не смогла запустить инструменты, которыми поднимается интерфейс: ядро отказалось их стартовать, поэтому подъём даже не начался. Это не конфликт порта или подсети, и модуль датапаса тут ни при чём. Либо на этих бинарниках стоят файловые capabilities, которых больше нет в capability bounding set этой ноды, либо их запуск запрещает слой контроля запуска (SELinux, fapolicyd или политика AppArmor, которую нода не может прочитать). Выполните на ноде:  getcap $(command -v ip) $(command -v wg) $(command -v awg)  для первого и  dmesg | grep -i 'denied'  для второго — что-то из них назовёт причину. Как только инструменты снова запускаются, интерфейс создастся сам на следующей синхронизации.",
  // The RTNETLINK refusal, split three ways in 1.8.7: it used to be ONE sentence naming the container
  // fix and the host fix and no configuration at all, so a declaratively managed node was told to edit
  // a docker-compose.yml it does not have. Same three arms, same order, as the exec-refused set above.
  "the interface tools ran on this node, but the kernel refused the operation they asked for (\"RTNETLINK answers: Operation not permitted\"). This is not a port or subnet conflict: the tools are being denied the network privilege they need. This node's installation is managed declaratively, so this belongs in the system configuration that declares it rather than in a command here: the capability set and the security policy that configuration gives this node have to let the WireGuard tools change network state. Restart the node daemon once the change is in — a rebuild does not restart it on its own, so the old unit keeps running.":
    "инструменты интерфейса на этой ноде запустились, но ядро отказало в операции, которую они запросили («RTNETLINK answers: Operation not permitted»). Это не конфликт порта или подсети: инструментам отказывают в сетевой привилегии, которая им нужна. Установка этой ноды описана декларативно, поэтому это относится к конфигурации системы, которая её описывает, а не к команде здесь: набор capabilities и политика безопасности, которые эта конфигурация даёт ноде, должны позволять инструментам WireGuard менять состояние сети. Перезапустите демон ноды, когда изменение внесено, — пересборка сама его не перезапускает, и продолжает работать старый юнит.",
  "this node's container ran the interface tools, but the kernel refused the operation they asked for (\"RTNETLINK answers: Operation not permitted\"). This is not a port or subnet conflict: the tools are being denied the network privilege they need. A container gets this when its capability set no longer covers what those binaries ask for — give the node NET_ADMIN (in docker-compose.yml: cap_add: [NET_ADMIN]) and recreate it (docker compose up -d), then this interface creates itself on the next sync.":
    "контейнер этой ноды запустил инструменты интерфейса, но ядро отказало в операции, которую они запросили («RTNETLINK answers: Operation not permitted»). Это не конфликт порта или подсети: инструментам отказывают в сетевой привилегии, которая им нужна. У контейнера так бывает, когда его набор capabilities больше не покрывает то, что запрашивают эти бинарники, — выдайте ноде NET_ADMIN (в docker-compose.yml: cap_add: [NET_ADMIN]) и пересоздайте её (docker compose up -d), после чего интерфейс создастся сам на следующей синхронизации.",
  "the interface tools ran on this node, but the kernel refused the operation they asked for (\"RTNETLINK answers: Operation not permitted\"). This is not a port or subnet conflict: the tools are being denied the network privilege they need. On a host that means a security policy is confining them —  dmesg | grep -i 'denied'  names which one. Then this interface creates itself on the next sync.":
    "инструменты интерфейса на этой ноде запустились, но ядро отказало в операции, которую они запросили («RTNETLINK answers: Operation not permitted»). Это не конфликт порта или подсети: инструментам отказывают в сетевой привилегии, которая им нужна. На хосте это значит, что их ограничивает политика безопасности —  dmesg | grep -i 'denied'  покажет какая. После этого интерфейс создастся сам на следующей синхронизации.",
  "this node's container could not execute the tools that bring an interface up: the kernel refused to start them, so the bring-up never began. This is not a port or subnet conflict. A container gets this when its capability set no longer covers what those binaries ask for — give the node NET_ADMIN (in docker-compose.yml: cap_add: [NET_ADMIN]) and recreate it (docker compose up -d), then this interface creates itself on the next sync.":
    "контейнер этой ноды не смог запустить инструменты, которыми поднимается интерфейс: ядро отказалось их стартовать, поэтому подъём даже не начался. Это не конфликт порта или подсети. У контейнера так бывает, когда его набор capabilities больше не покрывает то, что запрашивают эти бинарники, — выдайте ноде NET_ADMIN (в docker-compose.yml: cap_add: [NET_ADMIN]) и пересоздайте её (docker compose up -d), после чего интерфейс создастся сам на следующей синхронизации.",
  "interface conf has no Address": "в конфигурации интерфейса нет Address",
  "no free addresses in subnet": "в подсети не осталось свободных адресов",
  "public_key is not a valid WireGuard key": "public_key не является корректным ключом WireGuard",
  "a peer with this public key already exists": "пир с таким публичным ключом уже есть",
  "allowed_ips must be CIDR(s), e.g. 10.0.0.5/32": "allowed_ips должен быть CIDR, например 10.0.0.5/32",
  "allowed_ips must be CIDR(s), e.g. 0.0.0.0/0 or 10.8.0.0/24": "allowed_ips должен быть CIDR, например 0.0.0.0/0 или 10.8.0.0/24",
  "no peer with this public key": "пира с таким публичным ключом нет",
  "listen_port must be a number": "listen_port должен быть числом",
  "listen_port out of range (1-65535)": "listen_port вне диапазона (1–65535)",
  "nothing to set": "нечего задавать",
  "invalid interface name": "недопустимое имя интерфейса",
  "address must be CIDR like 10.99.0.0/31": "адрес должен быть CIDR, например 10.99.0.0/31",
  "private_key required": "требуется private_key",
  "AmneziaWG tools are missing from this node's container image. Update the node (docker compose pull && docker compose up -d) so it runs a current swg-node image, then this interface creates itself on the next sync.":
    "В образе контейнера этой ноды нет инструментов AmneziaWG. Обновите ноду (docker compose pull && docker compose up -d), чтобы она работала на актуальном образе swg-node, и интерфейс создастся сам на следующей синхронизации.",
  "This node's container image has awg but not awg-quick. Update the node (docker compose pull && docker compose up -d) so it runs a current swg-node image, then this interface creates itself on the next sync.":
    "В образе контейнера этой ноды есть awg, но нет awg-quick. Обновите ноду (docker compose pull && docker compose up -d), чтобы она работала на актуальном образе swg-node, и интерфейс создастся сам на следующей синхронизации.",
  "no container given": "контейнер не указан",
  "no wg/awg config found in container {c}": "в контейнере {c} не найдено конфигурации wg/awg",
  "{c} has no config for {i}": "в {c} нет конфигурации для {i}",
  "{c} has {n} wg/awg config(s) but none of them is running ({names}) — nothing to take over":
    "в {c} есть конфигураций wg/awg: {n}, но ни одна из них не запущена ({names}) — перенимать нечего",
  "could not read {p} in {c}": "не удалось прочитать {p} в {c}",
  "{c}: its config has no interface name, key or address to reuse":
    "{c}: в его конфигурации нет ни имени интерфейса, ни ключа, ни адреса, которые можно было бы переиспользовать",
  "{i} in {c} is not actually running — nothing to take over":
    "{i} в {c} на самом деле не запущен — перенимать нечего",
  "{i} in {c} does not match the config we read (its live key is a different one), so taking it over would not keep existing clients working — refusing":
    "{i} в {c} не совпадает с прочитанной конфигурацией (у работающего интерфейса другой ключ), поэтому перенос не сохранил бы работу существующих клиентов — отказано",
  "this node already runs an interface called {i}, so the same name cannot be created here — free it first (delete that interface if it is unused, or move its peers elsewhere). Nothing was changed.":
    "на этой ноде уже работает интерфейс с именем {i}, поэтому создать такое же имя здесь нельзя — сначала освободите его (удалите тот интерфейс, если он не нужен, либо перенесите его пиров). Ничего не изменено.",
  "could not clear the restart policy on {c} — nothing was changed":
    "не удалось снять политику перезапуска с {c} — ничего не изменено",
  "could not stop {c} — nothing was changed": "не удалось остановить {c} — ничего не изменено",
  "{why} — {c} was restarted and is serving again, nothing was taken over":
    "{why} — {c} запущен снова и продолжает обслуживать клиентов, ничего не перенято",
  "name taken": "имя занято",
  "Why this can't be taken over": "Почему его нельзя перенять",
  "This node already runs an interface called {v1}, so the take-over cannot recreate this one under that name — it would collide. Free the name first: open {v1} and delete it if you don't need it, or move its peers to another interface. Nothing has been changed here.":
    "На этой ноде уже работает интерфейс с именем {v1}, поэтому перенос не сможет поднять этот под тем же именем — они столкнутся. Сначала освободите имя: откройте {v1} и удалите его, если он не нужен, либо перенесите его пиров на другой интерфейс. Здесь ничего не изменено.",
  "Container": "Контейнер",
  "Take over": "Перенять",
  "The node does this on its next sync": "Нода сделает это на следующей синхронизации",
  "What happened": "Что произошло",
  "a take-over is already pending on this node": "на этой ноде уже есть незавершённый перенос",
  "bad container name": "неверное имя контейнера",
  "at least one csqtt target is required": "нужна хотя бы одна цель csqtt",
  "invalid iface (letters, digits, - and _; max 15)": "неверное имя интерфейса (буквы, цифры, - и _; не длиннее 15)",
  "no free RAW subnet left in 10.70.0.0/16": "в 10.70.0.0/16 не осталось свободных RAW-подсетей",
  "sub_hide must be a list": "sub_hide должен быть списком",
  "tun_addr must be an IPv4 /24 CIDR, e.g. 10.66.67.1/24":
    "tun_addr должен быть IPv4-подсетью /24, например 10.66.67.1/24",
  "unknown csqtt fork": "неизвестная сборка csqtt",
  "unknown csqtt peer": "неизвестный пир csqtt",
  "Adopting csqtt server": "Принимаем сервер csqtt",
  "Created csqtt peer": "Создан пир csqtt",
  "Imported csqtt user from adopted server": "Пользователь csqtt импортирован с принятого сервера",
  "Imported peer from an adopted container": "Пир импортирован из перенятого контейнера",
  "Removed csqtt instance": "Удалён экземпляр csqtt",
  "Rotated csqtt peer password": "Пароль пира csqtt заменён",
  "Set csqtt instance": "Настроен экземпляр csqtt",
  "Moved RAW-IP": "RAW-IP перенесён",
  "tag|ignored": "скрыт",
  "Another program owns this interface — it runs in its own container":
    "Этим интерфейсом владеет другая программа — он работает в своём контейнере",
  "col|Peer": "ПИР",
  "unnamed": "без имени",
  "This interface runs inside the container *{v1}*, from that container's own config — swgPanel can see it but cannot manage it there, and a change made here would be undone the next time that container restarts. *Take over* stops that container and runs the same server natively, keeping its key, port and peers.":
    "Этот интерфейс работает внутри контейнера *{v1}*, со своей конфигурацией — swgPanel его видит, но управлять им там не может, и изменение, сделанное здесь, откатится при следующем перезапуске того контейнера. *Перенять* остановит тот контейнер и поднимет тот же сервер нативно, сохранив его ключ, порт и пиров.",
  "the node no longer reports this interface inside that container — it may have been stopped, or the container removed.":
    "нода больше не сообщает об этом интерфейсе внутри того контейнера — возможно, он остановлен или контейнер удалён.",
  "tag|taking over": "перенимаем",
  "Withdraw": "Отозвать",
  "Withdraw the request — nothing has happened on the node yet":
    "Отозвать запрос — на ноде ещё ничего не произошло",
  "Request withdrawn.": "Запрос отозван.",
  "Could not withdraw it.": "Не удалось отозвать.",
  "Stop ignoring it — show it on the node again":
    "Перестать игнорировать — снова показывать на ноде",
  "Back on the node screen.": "Снова на экране ноды.",
  "Could not restore it.": "Не удалось вернуть.",
  "in {v1}": "в {v1}",
  "No upstream source is tracked for this client — a format change here would not raise a flag.":
    "Для этого клиента не отслеживается ни один источник — смена формата здесь не поднимет флаг.",
  "The tracked file could not be fetched — the check did not run.":
    "Отслеживаемый файл не удалось получить — проверка не выполнялась.",
  "up to date": "актуален",
  "re-install aborted": "переустановка прервана",
  "convert aborted": "конвертация прервана",
  // 1 char over budget: the four aborted states each need their own noun to stay distinguishable, and
  // this tag sits alone on a node card with room beside it.
  // budget-ok: alone on a node card, measured
  "update aborted": "обновление прервано",
  "uninstall aborted": "удаление прервано",
  "re-install failed": "ошибка переустановки",
  "convert failed": "ошибка конвертации",
  "Not a secure connection": "Соединение не защищено",
  "Your browser only provides Web Crypto over https:// (or http://localhost), so creating peers, unlocking the Encryption Vault and showing configs or QR codes will not work here. Monitoring is unaffected.":
    "Браузер выдаёт Web Crypto только по https:// (или http://localhost), поэтому здесь не будут работать создание пиров, разблокировка Хранилища шифрования и показ конфигов и QR-кодов. На мониторинг это не влияет.",
  "This panel needs a secure connection: your browser only provides the Web Crypto it uses to generate keys over https:// (or http://localhost). Reach the panel over https://, or tunnel it to http://127.0.0.1.":
    "Панели нужно защищённое соединение: браузер выдаёт Web Crypto, которым генерируются ключи, только по https:// (или http://localhost). Откройте панель по https:// или пробросьте её на http://127.0.0.1.",
  "update failed": "ошибка обновления",
  "uninstall failed": "ошибка удаления",
  "take-over failed": "не удалось перенять сервер",
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
  "This panel is managed declaratively, so its config-storage setting comes from its configuration. Set this and rebuild (existing peers then need a one-time Rotate-keys to capture a config):":
    "Эта панель управляется декларативно, поэтому настройка хранения конфигов задаётся её конфигурацией. Задайте это и пересоберите (существующим пирам затем нужна разовая смена ключей, чтобы конфиг сохранился):",
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
  "Unavailable while the node is down / converting": "Недоступно, пока нода не в строю или конвертируется",
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
  // The same repair for an interface the node still REPORTS but whose device is gone. "Пересобрать", not
  // "восстановить": the operator is looking at a card the node is actively reporting, and calling that
  // "missing" reads as the panel being confused rather than as a diagnosis.
  "Rebuild interface · {where}": "Пересборка интерфейса · {where}",
  // budget-ok: sheet-foot button, foot has a grow spacer
  "Rebuild interface": "Пересобрать интерфейс",
  "The device is gone from the node — rebuild it from the saved config with its original server key":
    "Устройство исчезло с ноды — пересоберите интерфейс из сохранённой конфигурации с его исходным ключом сервера",
  "Confirming it's really down (a couple of minutes) before Rebuild is offered":
    "Убеждаемся, что он действительно лежит (пара минут), прежде чем предлагать пересборку",
  "This isn't a brief bounce — the interface has been down on the node for {dur}.":
    "Это не короткий перезапуск — интерфейс лежит на ноде уже {dur}.",
  "Rebuild the down interface {iface} on {node} with its ORIGINAL server key (from {src}) and saved settings. The device is gone from the node, so there is nothing left to restart — this recreates it. Every peer on {iface} re-converges over the next few syncs and existing clients keep working (no new QR / config to distribute). {unlock}{gate}":
    "Пересобрать лежащий интерфейс {iface} на {node} с ИСХОДНЫМ ключом сервера (из {src}) и сохранёнными настройками. Устройство исчезло с ноды, перезапускать нечего — интерфейс будет создан заново. Все пиры на {iface} сойдутся за несколько синхронизаций, а уже розданные клиентам конфиги продолжат работать (перевыпускать QR не нужно). {unlock}{gate}",
  "Rebuild the down interface {iface} on {node} with its saved settings. The device is gone from the node, so there is nothing left to restart. Its original server key can't be recovered, so the interface comes back with a NEW key — every client on {iface} must re-import a fresh QR / config. {gate}":
    "Пересобрать лежащий интерфейс {iface} на {node} с сохранёнными настройками. Устройство исчезло с ноды, перезапускать нечего. Исходный ключ сервера восстановить неоткуда, поэтому интерфейс вернётся с НОВЫМ ключом — каждому клиенту на {iface} придётся заново импортировать конфиг или QR. {gate}",
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
  "{v1} more — type to narrow": "ещё {v1} — уточните поиском",
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
  // Private panel access (D28): the panel served on loopback, reached over an SSH tunnel. "Консоль"
  // is deliberately gone — the screen no longer uses that word in either language.
  "Panel access": "Доступ к панели",
  "Public panel address": "Публичный адрес панели",
  "Private panel access": "Приватный доступ к панели",
  "Access web panel via SSH tunnel": "Доступ к веб-панели через SSH-туннель",
  "Tunnel port": "Порт туннеля",
  "the panel already listens on port {v1} — pick a different, free port for the tunnel":
    "панель уже слушает порт {v1} — выберите для туннеля другой свободный порт",
  "Open the tunnel from your own machine:": "Откройте туннель со своей машины:",
  "SSH tunnel command": "команда SSH-туннеля",
  "Setting up private access…": "Настраиваем приватный доступ…",
  "Couldn't change private access.": "Не удалось изменить приватный доступ.",
  "Cancelled — the panel stays where it is.": "Отменено — панель осталась на прежнем адресе.",
  "Private access is off — the panel is on its public address again.":
    "Приватный доступ выключен — панель снова на публичном адресе.",
  "Private access is on — this address serves the nodes now. Carry on in the tab you confirmed from.":
    "Приватный доступ включён — этот адрес теперь обслуживает только ноды. Продолжайте во вкладке, где подтвердили.",
  "The tunnel wasn't confirmed in time, so the panel is still on its public address.":
    "Туннель не подтвердили вовремя, поэтому панель осталась на публичном адресе.",
  "Nothing has changed yet — open the tunnel and confirm you can reach the panel through it.":
    "Пока ничего не изменилось — откройте туннель и подтвердите, что панель через него доступна.",
  "Change private access on its own — save the address and certificate changes first, then turn the tunnel on.":
    "Меняйте приватный доступ отдельно — сначала сохраните адрес и сертификат, затем включайте туннель.",
  "A private-access change is still waiting to be confirmed — finish or cancel it in the tab that started it.":
    "Изменение приватного доступа ещё ждёт подтверждения — завершите или отмените его во вкладке, где оно начато.",
  "Open the panel through the tunnel to confirm ↗": "Открыть панель через туннель для подтверждения ↗",
  "When the tunnel is up, the panel will be accessible at {v1}": "Когда туннель поднят, панель будет доступна по адресу {v1}",
  "Put in the login and address you already use for SSH — `ssh_user` and `server_ip`.":
    "Подставьте логин и адрес, которыми вы уже пользуетесь для SSH, — `ssh_user` и `server_ip`.",
  "Your nodes and your browser reach this panel through the same door today. They don't have to. Serve the panel *on the server itself* and reach it over an SSH tunnel — the public address then keeps the fleet running while answering *nothing else*: every panel page, every operator API call and the integration API return `404` there.":
    "Сейчас ноды и ваш браузер приходят к панели в одну и ту же дверь. Так быть не обязано. Отдавайте панель *на самом сервере* и подключайтесь через SSH-туннель — публичный адрес продолжит обслуживать флот и не будет отвечать *ни на что другое*: все страницы панели, операторский API и интеграционный API вернут там `404`.",
  "*The panel will be served on `127.0.0.1:{v1}` on the server*, which nothing outside that machine can open. It is plain HTTP on purpose: the traffic never crosses a network, and a certificate issued for your panel's domain would only mis-name itself on a loopback address.":
    "*Панель будет отдаваться на `127.0.0.1:{v1}` на сервере* — снаружи этой машины её открыть нельзя. Это намеренно обычный HTTP: трафик не выходит в сеть, а сертификат, выписанный на домен панели, на localhost всё равно не совпал бы по имени.",
  "*The nodes are unaffected*: they keep dialling the public address, which keeps answering exactly the routes they use.":
    "*Ноды это не затрагивает*: они продолжают ходить на публичный адрес, который по-прежнему отвечает ровно на нужные им маршруты.",
  "*To close the door further*, restrict the public panel port in your firewall to the addresses your nodes connect from. The panel can't list them for you — it never sees a node's source address, and behind a proxy it would only see the proxy — so use the addresses you know. ⚠️ Get that list wrong and the fleet stops syncing, so change it while you can still watch the Nodes screen.":
    "*Чтобы закрыть дверь ещё плотнее*, ограничьте публичный порт панели в фаерволе адресами, с которых подключаются ноды. Панель не может составить этот список за вас — она не видит исходный адрес ноды, а за прокси видела бы только прокси, — поэтому используйте адреса, которые знаете сами. ⚠️ Ошибка в списке остановит синхронизацию флота, поэтому меняйте его, пока можете следить за экраном «Ноды».",
  "*This panel's container doesn't publish a port for this*, so a listener inside it would be unreachable — there is nothing to fill in here yet. *Re-run the Docker installer* to restage `docker-compose.yml` (it adds the port), then come back.":
    "*Контейнер этой панели не публикует для этого порт*, поэтому слушатель внутри него был бы недоступен — заполнять пока нечего. *Переустановите через Docker-инсталлятор*, чтобы он заново разложил `docker-compose.yml` (порт добавится), и вернитесь сюда.",
  "This port is set where this panel is deployed, not here — so there is nothing to pick. Change it in `.env` (`CONSOLE_PORT`) and re-run the Docker installer, or in the NixOS option, then come back.":
    "Этот порт задаётся там, где развёрнута панель, а не здесь — выбирать нечего. Измените его в `.env` (`CONSOLE_PORT`) и переустановите через Docker-инсталлятор, либо в опции NixOS, и вернитесь сюда.",
  "*Nothing has changed yet.* The panel is now served *both* here and through the tunnel — open it through the tunnel to prove you can reach it. Only then does this address stop serving the panel.":
    "*Пока ничего не изменилось.* Панель сейчас отдаётся *и* здесь, *и* через туннель — откройте её через туннель, чтобы подтвердить доступность. Только после этого текущий адрес перестанет её отдавать.",
  "Once it's confirmed, *this tab stops working*: this address will answer only what the nodes ask for. Carry on in the tunnelled one.":
    "После подтверждения *эта вкладка перестанет работать*: адрес будет отвечать только на запросы нод. Продолжайте в той, что открыта через туннель.",
  "Public URL": "Публичный URL",
  "https://panel.example.com  or  https://example.com/swgpanel": "https://panel.example.com  или  https://example.com/swgpanel",
  "Subscription address": "Адрес подписок",
  // ── Operator console door ─────────────────────────────────────────────────────────────────────
  // "Operator console" = операторская консоль — the panel's own UI as distinct from the node-sync
  // surface. "Дверь" is kept for the door metaphor the English leans on; it reads naturally here and
  // there is no established Russian term for a per-listener route policy.
  "If you don't, everything goes back on its own in *{n}s* — you cannot be locked out by not finishing.":
    "Если не подтвердите, через *{n} с* всё вернётся само — не доведя дело до конца, запереть себя снаружи невозможно.",
  "The console is served at {v1} again, and the panel's own address answers everything once more.":
    "Консоль снова обслуживается на {v1}, и собственный адрес панели опять отвечает на всё.",
  "Console address confirmed": "Адрес консоли подтверждён",
  "The operator console is served here now, and you're signed in. The panel's own address answers only what the nodes ask for — so close the other tab, it can't open the console any more.":
    "Операторская консоль теперь обслуживается здесь, и вы уже вошли. Собственный адрес панели отвечает только на то, что спрашивают ноды, — так что закройте ту вкладку, консоль она больше не откроет.",
  "https://sub.example.com  or  https://example.com/swgsub": "https://sub.example.com  или  https://example.com/swgsub",
  "*This panel's address is managed declaratively.* Its URL, listen address, mount path and certificate come from the configuration that built this machine, so they are shown here rather than edited here — change them there and rebuild. Everything the panel is *for* is unaffected: peers, interfaces, routing and subscriptions all work exactly as they do anywhere else.":
    "*Адрес этой панели задан декларативно.* Её URL, адрес прослушивания, путь монтирования и сертификат берутся из конфигурации, которая собрала эту машину, поэтому здесь они показаны, а не редактируются — измените их там и пересоберите. На то, *ради чего* панель существует, это не влияет: пиры, интерфейсы, маршрутизация и подписки работают ровно так же, как везде.",
  "Where this panel's address is set": "Где задаётся адрес этой панели",
  "These options carry what this panel is running right now — where it listens, the hostname it advertises, the path it is mounted at. Edit them in your configuration, rebuild, and this screen follows.":
    "В этих опциях — то, с чем панель работает прямо сейчас: где она слушает, какое имя хоста объявляет, по какому пути смонтирована. Измените их в своей конфигурации, пересоберите — и этот экран последует за ними.",
  "the panel's address options": "опции адреса панели",
  "Where a TLS terminator sends traffic": "Куда TLS-терминатор шлёт трафик",
  "Panel": "Панель",
  "Subscription page": "Страница подписок",
  "(inert until subscriptions are on)": "(бездействует, пока подписки выключены)",
  "This box's own node": "Нода этой машины",
  "(plain HTTP, never proxied)": "(обычный HTTP, не проксируется)",
  "Internal addresses on this host. Changing the public URL, the path or the certificate never moves them, so a proxy pointed here keeps working.":
    "Внутренние адреса на этой машине. Смена публичного URL, пути или сертификата их не двигает — прокси, настроенный сюда, продолжит работать.",
  "A sample configuration": "Пример конфигурации",
  "Two arrangements, both with this panel's own domain, path and port already filled in. Pick one, paste it beside the options above, and rebuild.":
    "Два варианта, в обоих уже подставлены домен, путь и порт этой панели. Выберите один, вставьте рядом с опциями выше и пересоберите.",
  "Terminate TLS in front of the panel": "Терминировать TLS перед панелью",
  "recommended": "рекомендуется",
  "the reverse-proxy configuration": "конфигурацию обратного прокси",
  "Two virtual hosts: the panel, and the subscription page — a *separate service* on its own port.":
    "Два виртуальных хоста: панель и страница подписок — *отдельный сервис* на своём порту.",
  "The subscription page is off. Turn it on in Subscriptions and give it `sub.domain`, and a virtual host for it appears here.":
    "Страница подписок выключена. Включите её в разделе «Подписки» и задайте `sub.domain` — виртуальный хост для неё появится здесь.",
  "Two virtual hosts: the panel, and the subscription page — a *separate service* on its own port. Subscriptions are on but the page has no address yet, so this gives it `{v1}`; change that to whatever you want to publish it as.":
    "Два виртуальных хоста: панель и страница подписок — *отдельный сервис* на своём порту. Подписки включены, но у страницы ещё нет адреса, поэтому здесь ей задан `{v1}` — замените на тот, под которым будете её публиковать.",
  "Leave the panel on its loopback address in this arrangement — the proxy is the only thing that should be reachable from outside.":
    "В этом варианте оставьте панель на loopback-адресе: снаружи должен быть доступен только прокси.",
  "Terminate TLS in the panel itself": "Терминировать TLS в самой панели",
  "no proxy": "без прокси",
  "the direct-TLS configuration": "конфигурацию прямого TLS",
  "The panel reads a certificate `security.acme` already manages and is reloaded when it renews. Declare the certificate itself however you validate it (HTTP-01, DNS-01) — but *don't set its `group`*: this module puts it in `swg` so the panel can read the key, and a second `group` fights it.":
    "Панель читает сертификат, которым уже управляет `security.acme`, и перечитывает его при обновлении. Сам сертификат объявите так, как проходите проверку (HTTP-01, DNS-01), но *не задавайте ему `group`*: модуль кладёт его в группу `swg`, чтобы панель могла прочитать ключ, и второй `group` этому мешает.",
  "The subscription page still needs its own terminator — it is a separate service on `{v1}`, and this option covers the panel only.":
    "Странице подписок всё равно нужен свой терминатор — это отдельный сервис на `{v1}`, а эта опция покрывает только панель.",
  "Existing certificate files (issued and renewed outside the panel)": "Готовые файлы сертификата (выпуск и продление — вне панели)",
  "Full-chain certificate": "Сертификат с полной цепочкой",
  "Private key": "Приватный ключ",
  "An absolute path on the panel host — the certificate with its chain. It must cover the panel's public address.": "Абсолютный путь на хосте панели — сертификат вместе с цепочкой. Он должен покрывать публичный адрес панели.",
  "Absolute path too, and the key must not have a passphrase. Both files are copied into place and re-checked every few hours, so a renewal written over them is picked up on its own. Leave both blank if a certificate is already installed and nothing here should touch it.": "Тоже абсолютный путь, и ключ должен быть без пароля. Оба файла копируются на место и перепроверяются каждые несколько часов, поэтому продление, записанное поверх них, подхватывается само. Оставьте оба поля пустыми, если сертификат уже установлен и трогать его не нужно.",
  "Subscription private key": "Приватный ключ подписок",
  "Only needed when the subscription page answers to a different name than the panel. Leave both blank and it is served the certificate above — which is what you want when the two share a hostname, or one certificate covers both.": "Нужно только если страница подписок отвечает на другое имя, чем панель. Оставьте оба поля пустыми — и ей отдадут сертификат выше, что и требуется, когда у них общее имя хоста или один сертификат покрывает оба.",
  "The subscription certificate needs BOTH paths — the full-chain certificate and its private key.": "Для сертификата подписок нужны ОБА пути — сертификат с полной цепочкой и приватный ключ к нему.",
  "The subscription certificate paths must be absolute (start with /) — they are read on the panel host, not in your browser.": "Пути к сертификату подписок должны быть абсолютными (начинаться с /) — они читаются на хосте панели, а не в браузере.",
  "Existing certificate files isn't available on Docker yet — mount your certificate over the panel's cert path instead (see docker-compose.yml).": "Готовые файлы сертификата пока недоступны в Docker — примонтируйте свой сертификат поверх пути к сертификату панели (см. docker-compose.yml).",
  "Existing certificate files needs BOTH paths — the full-chain certificate and its private key.": "Для готовых файлов сертификата нужны ОБА пути — сертификат с полной цепочкой и приватный ключ к нему.",
  "The certificate path must be absolute (start with /) — it is read on the panel host, not in your browser.": "Путь к сертификату должен быть абсолютным (начинаться с /) — он читается на хосте панели, а не в браузере.",
  "The private key path must be absolute (start with /) — it is read on the panel host, not in your browser.": "Путь к приватному ключу должен быть абсолютным (начинаться с /) — он читается на хосте панели, а не в браузере.",
  "Not set — give it sub.domain or sub.publicUrl": "Не задан — укажите sub.domain или sub.publicUrl",
  "Proxy to": "Прокси на",
  "This page's address comes from the configuration that built this machine — `services.swg-panel.sub.domain`, `sub.basePath`, `sub.publicUrl` and `sub.port`.":
    "Адрес этой страницы задаётся конфигурацией, которая собрала эту машину: `services.swg-panel.sub.domain`, `sub.basePath`, `sub.publicUrl` и `sub.port`.",
  "{v1} shows them beside a virtual host you can paste.": "{v1} показывает их рядом с готовым виртуальным хостом.",
  "This panel is managed declaratively, so its address and certificate belong to the configuration that built it, not to this screen. Edit them there and rebuild — nothing here was changed.":
    "Эта панель управляется декларативно, поэтому её адрес и сертификат принадлежат конфигурации, которая её собрала, а не этому экрану. Измените их там и пересоберите — здесь ничего не изменилось.",
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
  "Remove": "Удалить",
  // §1.4: the × on a provider-list row can only ever drop a PIN — a rule is what keeps a list, and the button
  // is disabled while one names it. «Открепить», not «убрать»: nothing is deleted, it just stops being held.
  "Unpin list from the fleet": "Открепить список от флота",
  "Unpin": "Открепить",
  "Stop keeping *{v1}* {v2} on *every node*? No rule uses it, so each node drops it on the next sync. You can pin it again from the catalog any time.":
    "Перестать держать *{v1}* {v2} на *всех нодах*? Он не используется ни одним правилом, поэтому каждая нода уберёт его при следующей синхронизации. Закрепить снова можно в любой момент из каталога.",
  "*Panel settings*": "*Настройки панели*",
  // budget-ok: tab label, tabs size to content
  "Routing": "Маршрутизация",
  "Blocking": "Блокировки",
  "Provider lists": "Списки провайдера",
  "{v1} can't run here": "не работают здесь: {v1}",
  "matching {v1}": "сопоставляет {v1}",
  "This node matches at most {v1} of a pattern — this one is {v2} and would be dropped.":
    "Эта нода сопоставляет не более {v1} шаблона — здесь {v2}, остальное будет отброшено.",
  "Custom lists": "Свои списки",
  "Delete this list": "Удалить этот список",
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
  "*Curated* presets are always available — recommended, ready-to-route lists the panel maintains and resolves itself, with nothing to enable. Turn on any public *provider* below to also search its raw catalog; the panel fetches it so its lists appear in the picker. Turning one off hides its lists and *stops* anything already routed from it until you turn it back on.":
    "*Отобранные* наборы доступны всегда — рекомендованные, готовые к маршрутизации списки, которые панель ведёт и собирает сама; включать нечего. Включите любого публичного *провайдера* ниже, чтобы искать ещё и по его сырому каталогу; панель его скачает, и его списки появятся в выборе. Выключение провайдера прячет его списки и *останавливает* всё, что уже из него маршрутизируется, пока вы не включите его снова.",
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
  "Routing & Blocking": "Маршрутизация",
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
  "Throughput units": "Единицы скорости",
  "Bits — Mbit/s, like a speed test": "Биты — Мбит/с, как в спидтесте",
  "Bytes — MB/s, what the node counts": "Байты — МБ/с, как считает нода",
  "How every speed in the panel is written. The same measurement either way — bits are 8× the number, and are what speed tests, ISP plans and router pages quote. Totals are always in bytes.":
    "Как записывается любая скорость в панели. Измерение одно и то же — в битах число в 8 раз больше, и именно биты называют спидтесты, тарифы и страницы роутеров. Итоговые объёмы всегда в байтах.",
  "Data": "Данные",
  "Days are counted in": "Сутки считаются по поясу",
  "This server's zone ({v1})": "Пояс этого сервера ({v1})",
  "This server's zone": "Пояс этого сервера",
  "{v1} (this browser's zone)": "{v1} (пояс этого браузера)",
  "Where each day starts and ends — for traffic totals, the charts and the turn-proxy update hour. Changing it shifts the charts' earlier points by the difference until they scroll out (up to 33 days).":
    "Где начинаются и кончаются сутки — для итогов трафика, графиков и часа обновления turn-прокси. После смены пояса прежние точки графиков сдвинутся на разницу, пока не уйдут из окна (до 33 дней).",
  "This server no longer has {v1}, so days are counted in its own zone. Pick another zone and save.":
    "На этом сервере больше нет пояса {v1}, поэтому сутки считаются по его собственному поясу. Выберите другой пояс и сохраните.",
  "This server has no time zone called {v1}. Pick one from the list.": "На этом сервере нет часового пояса {v1}. Выберите пояс из списка.",
  "The traffic ledger is not running: {v1}": "Учёт трафика не работает: {v1}",
  "from and to must be dates, YYYY-MM-DD": "from и to должны быть датами в формате ГГГГ-ММ-ДД",
  "from must not be after to": "from не может быть позже to",
  "from and to must include a day between 1970 and today": "from и to должны захватывать хотя бы один день между 1970 годом и сегодняшним",
  "range must be today, 7d, 30d, month, all or custom": "range должен быть today, 7d, 30d, month, all или custom",
  "by must be peer, user or slot": "by должен быть peer, user или slot",
  "since and window must be integers": "since и window должны быть целыми числами",
  "The traffic history is being written; try again in a moment": "История трафика сейчас записывается; повторите через мгновение",
  "The charts keep {v1} days: a custom window can start on {v2} at the earliest": "Графики хранят {v1} дня: свой период может начинаться не раньше {v2}",
  // Custom on the Overview (P3): the rail's date window, Top talkers on the traffic ledger.
  "The charts go back to {v1}.": "Графики начинаются с {v1}",
  "each on all their servers": "каждый — на всех своих серверах",
  "handed on": "передано",
  "The traffic totals could not be loaded.": "Не удалось загрузить итоги трафика.",
  "since {v1}": "с {v1}",
  // Traffic totals (P2): the window control, the Total cell's bubble, the peer and user views, Settings → Display → Data.
  "This month": "Этот месяц",
  "Last 30 days": "Последние 30 дней",
  "range|Custom": "Свой период",
  "From": "С",
  "To": "По",
  "The start is after the end.": "Начало позже конца.",
  "The start is after today.": "Начало позже сегодняшнего дня.",
  "Traffic — graph and devices": "Трафик — график и устройства",
  "Traffic totals are off — Settings → Display says why.": "Учёт трафика выключен — причина указана в Настройки → Отображение.",
  "Lifetime": "За всё время",
  "Nothing counted yet.": "Пока ничего не посчитано.",
  "Includes devices no longer theirs (deleted or handed on): {n}": "Включает устройства, которые им больше не принадлежат (удалены или переданы): {n}",
  "The whole device — including what it carried for an earlier owner.": "Всё устройство — включая то, что оно передало для прежнего владельца.",
  "This peer's total across all its deployments — every row of it repeats it.": "Итог пира по всем его размещениям — он повторяется в каждой его строке.",
  "The whole peer, not only the deployments this filter shows.": "Весь пир, а не только размещения, которые показывает этот фильтр.",
  "On {v1} now: {v2} — since the interface came up": "Сейчас на {v1}: {v2} — с момента поднятия интерфейса",
  "No traffic in this window.": "За этот период трафика нет.",
  "Traffic": "Трафик",
  "A server this traffic crosses was not reporting for part of the window: what it carried meanwhile lands in the column where it reported again.":
    "Сервер, через который идёт этот трафик, часть периода не отвечал: переданное за это время попадает в столбец, когда он снова вышел на связь.",
  "The graph could not be loaded.": "Не удалось загрузить график.",
  "Open this user's traffic — graph and devices": "Открыть трафик пользователя — график и устройства",
  "deleted": "удалено",
  "Its traffic from before the handover is still this user's": "Трафик до передачи по-прежнему считается за этим пользователем",
  "now {v1}'s": "теперь у {v1}",
  "unassigned": "без владельца",
  "Devices · {n}": "Устройства · {n}",
  "({n} no longer theirs)": "(больше не принадлежат: {n})",
  "No devices yet": "Устройств пока нет",
  "Add a peer for this user and its traffic appears here.": "Добавьте пользователю пир — его трафик появится здесь.",
  "5 minutes": "5 минут",
  "15 minutes": "15 минут",
  "1 hour": "1 час",
  "1 day": "1 день",
  "Infinite history": "Бесконечная история",
  "History resolution": "Детализация истории",
  "How much detail the per-peer traffic graphs can show. Finer costs more disk. A change applies from the next day — today keeps the detail it started with.":
    "Насколько подробными могут быть графики трафика пиров. Чем подробнее, тем больше места на диске. Изменение действует со следующих суток — сегодняшние сохраняют прежнюю детализацию.",
  "Could not read how much disk the traffic history uses.": "Не удалось узнать, сколько места занимает история трафика.",
  "Measuring the traffic history…": "Измеряем историю трафика…",
  "Traffic totals are off, so nothing is being counted: {v1}": "Учёт трафика выключен, поэтому ничего не считается: {v1}",
  "Traffic history uses {v1} in {v2} ({v3} free on that disk).": "История трафика занимает {v1} в {v2} (свободно на этом диске: {v3}).",
  "At {v1} resolution and {v2} active peers it will grow by about {v3} a day ({v4} a year) — an estimate until a full day is recorded.":
    "При детализации {v1} и {v2} активных пирах она будет расти примерно на {v3} в сутки ({v4} в год) — это оценка, пока не записаны полные сутки.",
  "At {v1} resolution and {v2} active peers it grows by about {v3} a day ({v4} a year).":
    "При детализации {v1} и {v2} активных пирах она растёт примерно на {v3} в сутки ({v4} в год).",
  "Turn off infinite history?": "Выключить бесконечную историю?",
  "Turn off": "Выключить",
  "Infinite history — on": "Бесконечная история — включена",
  "Infinite history — off: detail older than 33 days is deleted":
    "Бесконечная история — выключена: детализация старше 33 дней удаляется",
  "The detail is kept for the last 33 days; totals for any period are always kept.":
    "Детализация хранится за последние 33 дня; итоги за любой период хранятся всегда.",
  "Keep every peer's detailed traffic — at the history resolution below — for ever. Turn this off to keep that detail for the last 33 days only; totals for any period are always kept.":
    "Хранить подробный трафик каждого пира — с детализацией, заданной ниже, — всегда. Выключите, чтобы хранить эту детализацию только за последние 33 дня; итоги за любой период хранятся всегда.",
  "The panel will keep the traffic detail — each day's figures at the history resolution — for the last 33 days only. When you save, older detail is deleted and cannot be recovered. Totals for any period are kept — a day further back still shows, as one figure for the whole day.":
    "Панель будет хранить детализацию трафика — цифры каждого дня с заданной детализацией истории — только за последние 33 дня. При сохранении более старая детализация удаляется без возможности восстановления. Итоги за любой период сохраняются — более давний день по-прежнему виден одной цифрой за весь день.",
  "The panel will keep the traffic detail — each day's figures at the history resolution — for the last 33 days only. When you save, the detail of {v1} older days — {v2} — is deleted and cannot be recovered. Totals for any period are kept — a day further back still shows, as one figure for the whole day.":
    "Панель будет хранить детализацию трафика — цифры каждого дня с заданной детализацией истории — только за последние 33 дня. При сохранении детализация более старых дней (дней: {v1}, {v2}) удаляется без возможности восстановления. Итоги за любой период сохраняются — более давний день по-прежнему виден одной цифрой за весь день.",
  "The panel will keep the traffic detail — each day's figures at the history resolution — for the last 33 days only. None is older than that yet, so nothing is deleted when you save; from then on, each day's detail is deleted once it is 33 days old. Totals for any period are kept.":
    "Панель будет хранить детализацию трафика — цифры каждого дня с заданной детализацией истории — только за последние 33 дня. Более старой пока нет, поэтому при сохранении ничего не удаляется; дальше детализация каждого дня удаляется, когда ему исполняется 33 дня. Итоги за любой период сохраняются.",
  "History resolution → {v1}, from the next day": "Детализация истории → {v1}, со следующих суток",
  "id is required, by must be peer, user or group": "нужен id, а by должен быть peer, user или group",
  "No such group": "Такой группы нет",
  "Nodes — what the node downloads / uploads": "Ноды — что нода принимает / отдаёт",
  "Peers — what the client downloads / uploads": "Пиры — что принимает / отдаёт клиент",
  "Which way ↓/↑ are labelled across the panel. Same numbers, swapped arrows.": "Как по всей панели подписаны ↓ и ↑. Числа те же, стрелки меняются местами.",
  "Local networks": "Локальные сети",
  "A full mesh links every pair of nodes: every leg is measured and a new forward target works at once, but each node carries one link per other node. On demand links only the pairs a forward or a smart rule routes over, and removes a link nothing has used for an hour.": "Полный меш связывает каждую пару нод: измеряется каждое плечо, и новая цель пересылки работает сразу, но на каждой ноде держится по линку до каждой другой. «По требованию» связывает только пары, через которые идёт пересылка или умное правило, и удаляет линк, которым никто не пользуется час.",
  "This fleet is linked on demand now.": "Сейчас ноды этого флота связываются по требованию.",
  "Every pair in this fleet is linked now.": "Сейчас связана каждая пара нод этого флота.",
  "Full mesh": "Полный меш",
  "On demand": "По требованию",
  "Auto": "Авто",
  "Auto — a full mesh up to {v1} nodes, on demand above": "Авто — полный меш до {v1} нод, больше — по требованию",
  "The private network each node sits on. Its clients reach it unless it is closed on that node — nobody sets this up, it is what routing does.":
    "Частная сеть, в которой стоит каждая нода. Её клиенты попадают туда, пока это не закрыто на самой ноде: это никто не настраивал, так работает маршрутизация.",
  "No node reports sitting on a private network.": "Ни одна нода не сообщает, что стоит в частной сети.",
  "state|open": "открыта",
  "state|closed": "закрыта",
  "state|can't close": "не умеет закрывать",
  "state|closing": "закрывается",
  "This user's networks": "Сети этого пользователя",
  "Shared with this user": "Открыты этому пользователю",
  "Open to everyone on the node": "Открыты всем на ноде",
  "The node's own local network": "Локальная сеть самой ноды",
  "behind their own device {v1}": "за собственным устройством {v1}",
  "shared by {v1}": "доступ открыт пользователем {v1}",
  "shared by {v1} until {date}": "доступ открыт пользователем {v1} до {date}",
  "via": "через",
  // ⚠️ "prep|on", not "on": the catalog already carries "on" meaning ENABLED ("вкл"), later in the file, and a duplicate
  // key in an object literal silently wins — the bubble's "X on <node>" rendered as "вкл" until this was disambiguated.
  "prep|on": "на",
  "filter|All": "Все",
  "Can be reached by": "Кому доступны",
  "Private": "Личное",
  "This device is Private, so these networks are its owner's alone. Turn Private off in the device's own settings to share them.":
    "Устройство помечено как личное, поэтому эти сети доступны только владельцу. Чтобы поделиться, снимите «Личное» в настройках устройства.",
  "Only this user's own devices reach it and the networks behind it": "Доступ только с других устройств этого пользователя",
  "Everyone on this node can open connections to devices here, except Private ones, which only their user's own devices reach. Private here: {n}":
    "Все на этой ноде могут открывать соединения с устройствами здесь, кроме личных — к ним есть доступ только с устройств того же пользователя. Личных здесь: {n}",
  "This device has no owner yet, so nobody reaches these networks. Assign it to a user, or turn Private off.":
    "У устройства ещё нет владельца, поэтому эти сети недоступны никому. Назначьте его пользователю или снимите «Личное».",
  "Any device on this node can open connections to devices here, except the ones marked Private — only their user's own devices reach those.":
    "Любое устройство на этой ноде может открывать соединения с устройствами здесь, кроме помеченных как личные — к ним есть доступ только с устройств того же пользователя.",
  "Not enforced on {node} — it runs an older version, or hasn't reported yet. Devices there still reach this one.":
    "Не действует на {node} — там старая версия или нода ещё не отчиталась. Устройства на ней по-прежнему имеют доступ к этому устройству.",
  "{by} carries {p} on {node}, and deploying this device there would take it over. Remove that network from this device first, or choose another node.":
    "{by} обслуживает {p} на {node}, и размещение этого устройства там перехватит эту сеть. Сначала уберите сеть из этого устройства или выберите другую ноду.",
  "{v1} is already carried on this node by another device — deploying this one there would take it over":
    "{v1} на этой ноде уже обслуживает другое устройство — размещение этого устройства там перехватит эту сеть",
  "Not enforced for {iface} on {node} — the device has no user, so every device there still reaches it.":
    "Не действует для {iface} на {node} — у устройства нет пользователя, поэтому все устройства там по-прежнему имеют к нему доступ.",
  "Not enforced for {iface} on {node} — this server build can't prove which address the device has, so every device there still reaches it.":
    "Не действует для {iface} на {node} — эта сборка сервера не может подтвердить адрес устройства, поэтому все устройства там по-прежнему имеют к нему доступ.",
  "Saving this opens it again.":
    "После сохранения доступ снова откроется.",
  "The device opens to everyone on {nodes}.":
    "Устройство станет доступно всем на {nodes}.",
  "The device opens as its interface allows.":
    "Устройство станет доступно так, как разрешает интерфейс.",
  "The networks behind it open to everyone on the node.":
    "Сети за ним станут доступны всем на ноде.",
  "The networks behind it open to {who}.":
    "Сети за ним станут доступны: {who}.",
  "The networks behind it stay with this user's own devices.":
    "Сети за ним останутся доступны только устройствам этого пользователя.",
  "tag|private": "личное",
  "Only this user's own devices reach it and the networks behind it — not the people they share a group with, and not everyone on the node, whatever the interface allows.":
    "Доступ только с других устройств этого же пользователя — ни участникам его групп, ни всем на ноде, что бы ни разрешал интерфейс.",
  "Shared with": "Кому открыты",
  "owner: {v1}": "владелец: {v1}",
  "Who reaches the networks behind this device": "Кому доступны сети за этим устройством",
  "Anyone on {v1}": "Любой на {v1}",
  "Only {v1}'s devices": "Только устройства {v1}",
  "Only its owner's devices": "Только устройства владельца",
  "group · {v1}": "группа · {v1}",
  "Blocked — nothing reaches these through it.": "Заблокировано — через него сюда никто не попадёт.",
  "Offline — nothing reaches these until it reconnects.": "Не в сети — пока не подключится, сюда никто не попадёт.",
  "{v1} can't restrict who reaches a network, so it carries these for nobody.":
    "{v1} не умеет ограничивать доступ к сети, поэтому держит их ни для кого.",
  "{v1} ({v2} online)": "{v1} ({v2} онлайн)",
  "Can reach {v1} online now": "Сейчас доступно {v1}",
  "Can reach {v1}, none online": "Доступно {v1}, никто не онлайн",
  "until {date}": "до {date}",
  "Not in this user's routing — they can't reach it": "Нет в маршрутах пользователя — он туда не попадёт",
  "Routing unknown — this device's build doesn't say": "Маршруты неизвестны — сборка устройства их не сообщает",
  "Display in panel": "Показывать в панели",
  "Hide these and close them on every node": "Скрыть их и закрыть на всех нодах",
  "Show these again — each node's own switch then decides who reaches it": "Снова показывать их — дальше доступ решает переключатель на самой ноде",
  "Node local networks — shown in the panel": "Локальные сети нод — показаны в панели",
  "Mesh links — {v1}": "Связи в меше — {v1}",
  "Node local networks — hidden, and closed on every node": "Локальные сети нод — скрыты и закрыты на всех нодах",
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
  // the field takes six kinds now; enumerating them in a label is a list that grows with every one
  "Addresses, domains and patterns": "Адреса, домены и шаблоны",
  "Domains match their subdomains too; IPs / CIDRs directly; an *AS number* (e.g. AS62041) resolves to that provider's IP ranges. Patterns work here exactly as they do in a rule.":
    "Домены совпадают вместе со своими поддоменами; IP и CIDR — напрямую; *номер AS* (например AS62041) разворачивается в диапазоны IP этого провайдера. Шаблоны работают здесь так же, как в правиле.",
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
  "*{v1} on this interface*The node couldn't read their details — they still come across when you adopt.":
    "*{v1} на этом интерфейсе*Нода не смогла прочитать их детали — при приёме они всё равно перейдут.",
  "*{v1}*Nothing is configured on this interface yet. Adopt it to add peers from the panel.":
    "*{v1}*На этом интерфейсе пока ничего не настроено. Примите его, чтобы добавлять пиров из панели.",
  "Ports recovered from its password store — its clients already dial these. The *subnet* is never written to disk, so set that below.":
    "Порты восстановлены из его хранилища паролей — клиенты уже звонят именно на них. *Подсеть* на диск не пишется, поэтому задайте её ниже.",
  // budget-ok: disclosure summary, own line
  // the collapsed routing summary. TWO sentences, one per engine arbitration — see rulesSummary().
  "Delete interface": "Удалить интерфейс",
  "Reassigning to {v1} rotates the peer's keys. The current user loses access immediately and permanently — assigning them back later would still be a brand-new credential.":
    "Переназначение на {v1} перевыпускает ключи пира. Текущий пользователь теряет доступ немедленно и безвозвратно — даже если вернуть пира ему позже, это будут совершенно новые учётные данные.",
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
  "*{v1} in plaintext still on the panel.* Encrypt them so the server can no longer read a client private key. Safe and resumable — the plaintext is deleted only after its encrypted copy exists.":
    "*{v1} на панели всё ещё в открытом виде.* Зашифруйте их, чтобы сервер больше не мог прочитать приватный ключ клиента. Безопасно и с возобновлением — открытая копия удаляется только после того, как появилась зашифрованная.",
  // the migration toast — two whole sentences, because only one of them mentions the purge
  // budget-ok: toast, wraps — and the phrasing matches the report line above it on purpose
  "Encrypted {v1} · purged {v2} plaintext.": "Зашифровано {v1} · вычищено {v2} в открытом виде.",
  "Encrypted {v1}.": "Зашифровано {v1}.",
  "*All stored configs are encrypted.*": "*Все сохранённые конфиги зашифрованы.*",
  "Delete *{v1}*? It's removed from *every node* it's enabled on, and its interface rules stop matching on the next sync. This can't be undone.":
    "Удалить *{v1}*? Он убирается со *всех нод*, где включён, и его правила на интерфейсах перестанут совпадать на следующей синхронизации. Отменить нельзя.",
  "Used for *unassigned* peers, and as the link the panel bakes in when you generate a config here to *test a connection yourself* before handing it out. Leave blank to emit a *{v1}* placeholder.": "Используется для *неназначенных* пиров и как ссылка, которую панель подставляет, когда вы генерируете конфиг здесь, чтобы *проверить соединение самому* перед выдачей. Оставьте пустым — подставится заглушка *{v1}*.",
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
  "Delete WDTT server · {v1}": "Удалить сервер WDTT · {v1}",

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
  "Turn-proxy management is *off* on this node — its configuration has it off (*turnManage*), so these are read-only here. Turn it on there and rebuild, or manage them on the box directly.":
    "Управление turn-прокси *выключено* на этой ноде — так задано в её конфигурации (*turnManage*), поэтому здесь они только для чтения. Включите там и пересоберите — или управляйте ими прямо на сервере.",
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
  "Forward to": "Куда перенаправлять",
  "no obfuscation": "без обфускации",
  "(latest)": "(последняя)",
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
  "{fork} servers share one binary per node, so the version is per node — every {fork} instance on a node moves together. Pinning an older version *holds* it (no auto-update); *Use latest* follows new releases.":
    "Серверы {fork} используют один бинарник на ноду, поэтому версия задаётся на ноду — все экземпляры {fork} на ноде переезжают вместе. Закрепление старой версии *удерживает* её (без автообновления); *Использовать последнюю* следует за новыми релизами.",

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
  "Server name": "Имя сервера",
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
  "Datapath": "Путь данных",
  "The traffic on this leg comes from *{peer}*, so its datapath is chosen there — open this link from {peer}'s page.":
    "Трафик на этом плече идёт со стороны *{peer}*, поэтому путь данных выбирается там — откройте эту связь со страницы {peer}.",
  // Reachable when smart rules name this peer but the panel has not planned a leg for them — usually
  // because no node sync has landed since the panel started. The sentence it replaced claimed only a
  // whole-interface cascade can be accelerated, which stopped being true when smart legs became relayable.
  "The panel hasn't worked out this link's routes yet, so there is nothing to accelerate here. The choice appears after *{node}*'s next sync.":
    "Панель ещё не рассчитала маршруты этой связи, так что ускорять здесь пока нечего. Выбор появится после следующей синхронизации *{node}*.",
  // Under a whole-interface cascade "accelerated" reads as "this interface"; under a smart one it does not.
  "Only the destinations *{ifaces}* routes over this link are relayed — the rest of that traffic is untouched. And the relay terminates TCP, so UDP keeps forwarding either way.":
    "В релей уходят только те назначения, которые *{ifaces}* маршрутизирует через эту связь, — остальной трафик не затрагивается. И релей терминирует TCP, поэтому UDP в любом случае остаётся на пересылке.",
  "Nothing sends its whole traffic through this link yet. Set an interface's egress to *Forward to {peer}* and the datapath choice appears here.":
    "Пока ни один интерфейс не отправляет через эту связь весь свой трафик. Задайте в выходе интерфейса *Переслать на {peer}* — и выбор пути данных появится здесь.",
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
  // budget-ok: popover row tooltip, wraps
  "Leg measured from this node: {v1} of {v2} probe packets lost.": "Замер с этой ноды: потеряно {v1} из {v2} проб.",
  // budget-ok: popover row tooltip, wraps
  "Leg measured from {v3}: {v1} of {v2} probe packets lost.": "Замер с {v3}: потеряно {v1} из {v2} проб.",
  // budget-ok: popover row tooltip, wraps
  "Round-trip latency to {v3}. Loss this way is measured by {v3}, which has not reported it.": "Круговая задержка до {v3}. Потери в эту сторону меряет {v3} — она их пока не сообщила.",
  "col|Drops": "Отброшено",
  "Drops": "Отброшено",
  "col|Latency": "Задержка",
  "(Loss {v1}%)": "(потери {v1}%)",
  "Leg quality · {v1}": "Качество плеча · {v1}",
  "Round trip": "Круговая",
  "min {v1} · max {v2}": "мин {v1} · макс {v2}",
  "Jitter": "Джиттер",
  "Worst probe": "Худшая проба",
  // budget-ok: bubble micro-label in a max-content column, measured 103px, no wrap or clip
  "Last loss": "Последняя потеря",
  // budget-ok: bubble hint, wraps
  "That is a single lost packet — the smallest amount this probe can measure. One is normal; watch whether it keeps happening.": "Это один потерянный пакет — минимум, который эта проба вообще может измерить. Один — норма; смотрите, повторяется ли.",
  // budget-ok: bubble footer, wraps
  "measured by pinging the far end of this link": "измеряется пингом дальнего конца этого канала",
  // budget-ok: appended to a popover row tooltip, wraps
  "Worst probe {v1}%.": "Худшая проба {v1}%.",
  // budget-ok: appended to a popover row tooltip, wraps
  "Last loss {v1} ago.": "Последняя потеря {v1} назад.",
  // budget-ok: appended to a popover row tooltip, wraps
  "Jitter {v1}ms.": "Джиттер {v1}мс.",
  // budget-ok: settings description, wraps
  "The client's packets reach the server but no handshake has ever completed — blocked at the door (likely DPI / MTU / wrong Wireguard or AmneziaWG params).": "Пакеты клиента доходят до сервера, но рукопожатие ни разу не завершилось — блокировка на входе (вероятно DPI / MTU / неверные параметры Wireguard или AmneziaWG).",
  // budget-ok: settings description, wraps
  "The tunnel keeps collapsing and being rebuilt: handshakes far more often than the 120s a healthy session renews at, from an endpoint that isn't moving. A peer that simply has nothing to send is not flagged.": "Туннель постоянно рвётся и пересобирается: рукопожатия намного чаще, чем раз в 120 с, как обновляется здоровая сессия, и при этом адрес не меняется. Пир, которому просто нечего передавать, не помечается.",
  // budget-ok: status reason sentence, wraps
  "the tunnel keeps collapsing and being rebuilt — the session won't hold, which is what a filtered or DPI'd connection looks like": "туннель постоянно рвётся и пересобирается — сессия не держится, так выглядит фильтруемое или DPI-подавленное соединение",
  // budget-ok: settings intro, wraps
  "Two ways a peer can be under a filter, each independently switchable. Both raise the same {v1} badge — one is blocked at the door, the other gets in and can't stay. A peer that simply has nothing to send is never flagged.": "Два способа обнаружить фильтрацию пира, каждый включается отдельно. Оба поднимают один и тот же значок {v1}: в одном случае пира не пускают на входе, в другом он входит, но не может удержаться. Пир, которому просто нечего передавать, не помечается никогда.",
  "Drops · {v1}": "Отброшено · {v1}",
  "{v1} of {v2} packets": "{v1} из {v2} пакетов",
  "{v1} of {v2}": "{v1} из {v2}",
  "Sending": "Отправка",
  "Receiving": "Приём",
  "queue full": "очередь",
  "no session": "нет сессии",
  "refused": "отклонено",
  "overflow": "переполнение",
  "Not counted": "Не учтено",
  // budget-ok: bubble footer, wraps
  "Loss over the last {v1} ({v2} probes of {v3} packets, {v4}-byte). Latency and jitter are from the newest probe.": "Потери за последние {v1} ({v2} проб по {v3} пакетов, {v4} байт). Задержка и джиттер — из последней пробы.",
  "Worst sample": "Худший замер",
  "dropped": "отброшено",
  // budget-ok: bubble micro-label in a max-content column, measured 103px, no wrap or clip
  "Last drop": "Последняя потеря",
  "Since boot": "С загрузки",
  "unit|/min": "/мин",
  "Dropped at the socket · {v1}": "Отброшено на сокете · {v1}",
  "in the last {v1}": "за последние {v1}",
  "Rate": "Темп",
  "per minute": "в минуту",
  "Backlog": "В очереди",
  "waiting": "ждут",
  "Since it started": "С запуска",
  // budget-ok: bubble footer, wraps
  "Packets that reached this server and were discarded because the proxy wasn't reading its socket fast enough. They never reach an interface, so no interface counter can show them.": "Пакеты дошли до сервера и были отброшены, потому что прокси не успевал читать свой сокет. До интерфейса они не доходят, поэтому счётчики интерфейсов их не видят.",
  "Since reset": "С обнуления",
  "Reset ✓": "Сброшено ✓",
  "Resetting…": "Сброс…",
  // budget-ok: button tooltip, wraps
  "Zero the counters and start measuring again from now": "Обнулить счётчики и начать измерять заново с этого момента",
  "Couldn't reset the counters.": "Не удалось сбросить счётчики.",
  "Clear this leg's probe window at both ends and start measuring again from now": "Очистить окно замеров на обоих концах и начать измерять заново с этого момента",
  "Couldn't reset the probe window.": "Не удалось очистить окно замеров.",
  "measured over the last {v1}": "замер за последние {v1}",
  "this node's own queues and datapath, not the path to the client": "собственные очереди и тракт узла, а не путь до клиента",
  // budget-ok: bubble hint, wraps
  "Packets held for the other server were discarded because the link had no working session — it was down.": "Пакеты, ждавшие отправки другому серверу, отброшены: у канала не было рабочей сессии — он лежал.",
  // budget-ok: bubble hint, wraps
  "The program serving this interface didn't read its queue in time — local load, or it was restarting.": "Программа, обслуживающая интерфейс, не успевала читать свою очередь — локальная нагрузка или перезапуск.",
  // budget-ok: bubble hint, wraps
  "Packets waiting to go out were discarded before they could be sent.": "Пакеты, ждавшие отправки, отброшены, не успев уйти.",
  // budget-ok: bubble hint, wraps
  "Not counted: packets for clients that weren't connected, traffic to addresses no client owns, and traffic one client sent from outside its range. None of it is something a connected client lost.": "Не учтено: пакеты для клиентов, которые не были подключены, трафик на адреса, не принадлежащие ни одному клиенту, и трафик, который клиент отправил не со своего адреса. Подключённые клиенты ничего из этого не потеряли.",
  "Sends failed outright — no route out, or a peer whose endpoint this node doesn't know yet.": "Отправка не удалась совсем: нет маршрута наружу или пир, чей адрес узлу ещё неизвестен.",
  // budget-ok: bubble hint, wraps
  "Packets arrived faster than this node could take them in — local load, not the path.": "Пакеты приходили быстрее, чем узел успевал их принять, — локальная нагрузка, а не путь.",
  // budget-ok: bubble hint, wraps
  "Packets came from a source outside the sender's allowed range, or were malformed — usually one misconfigured sender.": "Пакеты пришли с адреса вне разрешённого диапазона отправителя или были повреждены — обычно это один неверно настроенный отправитель.",
  "This node hasn't reported drop counters for this interface yet.": "Узел ещё не прислал счётчики потерь по этому интерфейсу.",
  "unit|ms": "мс",
  "(set at creation — delete & recreate to change)": "(задаётся при создании — меняется пересозданием)",

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
  "Interface *{iface}* is gone from {node} with *no recoverable key*, so it can't be restored — only recreated with a *new server key*. Nothing is deployed on it, so no client is affected. The settings below are its *last saved config* — review them and recreate.":
    "Интерфейс *{iface}* пропал с {node}, и *ключ восстановить нельзя*, поэтому его можно только пересоздать с *новым ключом сервера*. На нём ничего не развёрнуто, так что клиентов это не затронет. Настройки ниже — это *последняя сохранённая конфигурация* интерфейса; проверьте их и пересоздайте.",
  "Interface *{iface}* is gone from {node} with *no recoverable key*, so it can't be restored — only recreated with a *new server key*. Its *{count}* will be rekeyed once it's back, so *every client must re-import* a fresh QR / config. The settings below are its *last saved config* — review them and recreate.":
    "Интерфейс *{iface}* пропал с {node}, и *ключ восстановить нельзя*, поэтому его можно только пересоздать с *новым ключом сервера*. Как только он вернётся, ключи будут выданы заново — это *{count}*, поэтому *каждому клиенту нужен повторный импорт* свежего QR или конфига. Настройки ниже — это *последняя сохранённая конфигурация* интерфейса; проверьте их и пересоздайте.",
  "Interface *{iface}* is gone from {node} with *no recoverable key*, so it can't be restored — only recreated with a *new server key*. Its *{count}* will be rekeyed once it's back, so *every client must re-import* a fresh QR / config. Review the settings below (inferred from the peers) and recreate.":
    "Интерфейс *{iface}* пропал с {node}, и *ключ восстановить нельзя*, поэтому его можно только пересоздать с *новым ключом сервера*. Как только он вернётся, ключи будут выданы заново — это *{count}*, поэтому *каждому клиенту нужен повторный импорт* свежего QR или конфига. Проверьте настройки ниже (выведены из пиров) и пересоздайте.",
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
  "Stop + remove this WDTT server and disconnect its users": "Остановить и удалить этот сервер WDTT, отключив его пользователей",
  "Stop + remove this csqtt server and disconnect its users": "Остановить и удалить этот сервер csqtt, отключив его пользователей",
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
  "These interfaces' client traffic exits the fleet through *{node}*{smart}.":
    "Клиентский трафик этих интерфейсов выходит из флота через *{node}*{smart}.",
  // budget-ok: clause inside wrapping prose
  " — smart-routed by destination": " — с умной маршрутизацией по назначению",
  "This is a panel-managed mesh link to *{node}*. It's created and torn down automatically as nodes are added or removed. To route a user interface's traffic out through this node, set that interface's egress to *Forward to {node}*.":
    "Это меш-линк до *{node}*, которым управляет панель. Он создаётся и сносится автоматически по мере добавления и удаления нод. Чтобы направить трафик пользовательского интерфейса через эту ноду, задайте её в выходе того интерфейса: *Переслать на {node}*.",
  "This is a panel-managed mesh link to *{node}*. On demand, a link exists while a forward, a smart rule or its own settings use it, and is removed an hour after nothing does. To route a user interface's traffic out through this node, set that interface's egress to *Forward to {node}*.": "Это меш-линк до *{node}*, которым управляет панель. В режиме «по требованию» линк существует, пока им пользуется пересылка, умное правило или его собственные настройки, и удаляется через час после того, как пользоваться перестанут. Чтобы направить трафик пользовательского интерфейса через эту ноду, задайте её в выходе того интерфейса: *Переслать на {node}*.",
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
  "Intercepts & downgrades client DNS — a client on encrypted DNS is flagged, not blocked":
    "Перехватывает и понижает DNS клиента — клиента на шифрованном DNS помечает, но не блокирует",
  "Enforces domain content filters directly": "Применяет доменные контент-фильтры напрямую",
  // budget-ok: mode-card bullet, wraps
  "Long block lists cost CPU per DNS query — keep them small (≈100k domains)":
    "Длинные списки блокировки дорогие для CPU на каждый DNS-запрос — держите их небольшими (≈100 тыс. доменов)",
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
  // budget-ok: mode-card bullet, wraps
  "A site name picks an exit only — Direct and Block by name need Force-DNS / Hybrid":
    "Имя сайта выбирает только выход — «Напрямую» и «Заблокировать» по имени работают на Force-DNS / Hybrid",
  "Hybrid SNI": "Hybrid SNI",
  "host layer · SNI in userspace": "слой хостов · SNI в userspace",
  "Parses the TLS SNI in a small helper — client DNS stays private":
    "Разбирает SNI из TLS в помощнике — DNS клиента остаётся приватным",
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
  "Settings ▸ Routing & Blocking": "Настройки ▸ Маршрутизация",
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
  "Recommended presets": "Рекомендуемые наборы",
  "Provider catalog": "Каталог провайдера",
  "Lists from {v1}": "Списки {v1}",
  "{v1} is still downloading its list catalog — its lists appear here when it finishes.": "{v1} ещё загружает каталог списков — они появятся здесь, когда загрузка закончится.",
  "{v1} could not download its list catalog — retry it in Settings ▸ Geo data providers.": "Не удалось загрузить каталог списков {v1} — повторите в «Настройки ▸ Провайдеры гео-данных».",
  "Domains blocked in Russia — the RKN registry, filtered": "Домены, заблокированные в России, — реестр РКН после фильтрации",
  "IP addresses blocked in Russia, merged into ranges": "IP-адреса, заблокированные в России, в виде диапазонов",
  "Community list: sites RKN does not block that refuse visitors from Russia": "Список сообщества: сайты, которые РКН не блокирует, но которые не пускают посетителей из России",
  "Community list: networks RKN does not block that refuse addresses from Russia": "Список сообщества: сети, которые РКН не блокирует, но которые не пускают адреса из России",
  "Discord's networks": "Сети Discord",
  // budget-ok: toast, wraps

  // Routing rules
  // budget-ok: field <label> / disclosure title, own line
  "Routing rules": "Правила маршрутизации",
  // budget-ok: label suffix, wraps with the label
  // the rule-list label, picked by the node's engine — IP-only and Kernel-SNI arbitrate by ROW ORDER
  "— the most specific rule wins": "— выигрывает самое точное правило",
  "— the first matching rule wins": "— выигрывает первое совпадение",
  "Node default ({v1})": "Как у ноды ({v1})",
  "Direct (this node)": "Напрямую (эта нода)",
  "Remove rule": "Удалить правило",
  // budget-ok: confirm body, wraps
  "This rule routes {v1}. Removing it here is not written to the node until you save the interface.":
    "Это правило маршрутизирует {v1}. Удаление здесь попадёт на ноду только после сохранения интерфейса.",
  // budget-ok: toolbar button, row has a grow spacer
  "Add rule": "Добавить правило",
  "Everything else": "Всё остальное",
  // A rule whose destination has been removed from the panel. «Указывает в никуда» is the plain reading of
  // a control that renders blank while a real choice sits in the store.
  "{v1} pointing nowhere": "указывают в никуда: {v1}",
  "This node itself": "Сама эта нода",
  "This interface is set to forward everything to the node it is already on, which cannot work — the traffic would leave by this node's own address anyway. Choose another destination.":
    "Этот интерфейс настроен пересылать всё на ту же ноду, на которой он и находится, а так не получится — трафик всё равно выйдет собственным адресом этой ноды. Выберите другое назначение.",
  "A node that is no longer here": "Ноды больше нет",
  "This interface forwards everything to a node that is not in this panel any more, so it routes nothing and its clients leave by this node's own address. Choose another destination.":
    "Этот интерфейс отправляет весь трафик на ноду, которой в панели больше нет, поэтому он не маршрутизирует ничего, и его клиенты выходят собственным адресом этой ноды. Выберите другое назначение.",
  "An exit that is no longer here": "Выхода больше нет",
  "This rule forwards to a node that is not in this panel any more, so it routes nothing and traffic takes the next matching rule instead. Choose another destination, or delete the rule.":
    "Это правило направляет на ноду, которой в панели больше нет: оно ничего не маршрутизирует, и трафик уходит по следующему подходящему правилу. Выберите другое назначение или удалите правило.",
  "This rule leaves by an exit that is not on this node any more, so it routes nothing and traffic takes the next matching rule instead. Choose another destination, or delete the rule.":
    "Это правило выходит через выход, которого на этой ноде больше нет: оно ничего не маршрутизирует, и трафик уходит по следующему подходящему правилу. Выберите другое назначение или удалите правило.",
  "Matched by domain — needs Force-DNS or Hybrid-SNI mode": "Совпадает по домену — нужен режим Force-DNS или Hybrid-SNI",
  "Domain list — needs Force-DNS or Hybrid-SNI mode": "Список доменов — нужен режим Force-DNS или Hybrid-SNI",
  "IP list — works in every mode": "Список IP — работает в любом режиме",
  // budget-ok: inline lint under a rule row, wraps
  "can't exit via itself": "не может выходить через себя",
  "add at least one address, domain or pattern": "добавьте хотя бы один адрес, домен или шаблон",
  // budget-ok: a foot lint under a field, wraps
  "This text hasn't been applied yet — press </> to apply it, or Escape to discard.":
    "Этот текст ещё не применён — нажмите </>, чтобы применить, или Escape, чтобы отменить.",
  "Text typed into this rule hasn't been added yet — press Enter to add it, or clear it.":
    "Текст, набранный в правиле, ещё не добавлен — нажмите Enter, чтобы добавить его, или сотрите.",
  // a list cannot hold a list — cascade_plan expands one, it never recurses
  "A list can't contain another list — add its addresses here instead":
    "Список не может содержать другой список — добавьте его адреса сюда",
  // budget-ok: hover caption

  // Egress
  "Outbound (egress) interface": "Интерфейс выхода (egress)",
  // decision B1, second pass: the NAT pin is no longer in the "where does traffic go" list at all — it
  // routes nothing, and read there it was taken twice for a milder way of leaving by a card.
  "Leave by a device": "Выход через устройство",
  "val|Network card": "Сетевая карта",
  // ⚠️ THE HEADING DOES NOT NAME A CARD. Third attempt: the first two ("Direct — source from eth2", then
  // "NAT source card") both led with the device and were both read as "send traffic out that card". In
  // Russian it was worse than in English — a bare `карта` reads as MAP first, and `карточка` is already
  // this panel's word for a UI card, so "Карта для адреса NAT" said something close to "map for the NAT
  // address". Naming the ACT drops the ambiguous noun entirely.
  "Extra NAT": "Дополнительный NAT",
  // the exit's typed gateway — cards only, and blank means "use the one the node detected".
  "Gateway": "Шлюз",
  "Detected: {v1}": "Определён: {v1}",
  "This doesn't send traffic out that card. It only changes the source address of traffic that already leaves by it — use it when you route to that card yourself, outside the panel. To leave by a card, pick it under “Leave by a device”.":
    "Это не отправляет трафик через сетевую карту. Оно лишь меняет адрес источника у трафика, который и так через неё уходит — нужно, если вы сами маршрутизируете на эту карту, вне панели. Чтобы выходить через карту, выберите её в «Выход через устройство».",
  "This node's traffic leaves by {v2}, not {v1}, so this rule can never match and clients would leave with no NAT at all. Choose “Off”, or {v2} — unless you route to {v1} yourself.":
    "Трафик этого узла уходит через {v2}, а не через {v1}, поэтому правило никогда не сработает и клиенты будут выходить вообще без NAT. Выберите «Выключен» или {v2} — если только вы сами не маршрутизируете в {v1}.",
  "Leaves as {v1}. That source belongs to the exit, so every interface using it shares one — change it under Settings → Network.":
    "Уходит с адреса {v1}. Этот источник принадлежит exit'у, поэтому он общий для всех интерфейсов, которые им пользуются — изменить можно в Настройках → Сеть.",
  "Leaves as whichever address the node picks on {v1}. Pin one on the exit under Settings → Network.":
    "Уходит с того адреса, который узел сам выберет на {v1}. Закрепить конкретный можно у exit'а в Настройках → Сеть.",
  // the Advanced section is now two named groups: the protocol's own settings, and the extra NAT.
  "WireGuard settings": "Настройки WireGuard",
  "AmneziaWG settings": "Настройки AmneziaWG",
  // `Выключен` agrees with NAT (m.), not with `карта` (f.) — the old "Не закреплена" was gendered to a noun
  // the heading no longer has. "pinned" was our implementation's metaphor anyway, never the operator's.
  "val|Off": "Выключен",
  "Leave by a device on this node, channel everything through another node, or route per-destination (smart).":
    "Выходить через устройство на этом узле, направить весь трафик через другой узел или маршрутизировать по назначению (smart).",
  "Leave normally, channel everything through another node, or route per-destination (smart).":
    "Выходить обычным путём, направить весь трафик через другой узел или маршрутизировать по назначению (smart).",
  "Leave by a device on this node, or route per-destination (smart).":
    "Выходить через устройство на этом узле или маршрутизировать по назначению (smart).",
  "Leave normally, or route per-destination (smart).":
    "Выходить обычным путём или маршрутизировать по назначению (smart).",
  "Outbound (egress) IP": "IP выхода (egress)",
  "Auto (MASQUERADE)": "Авто (MASQUERADE)",
  "Forward to node (cascade)": "Переслать на ноду (каскад)",
  "Forward to {node}": "Переслать на {node}",
  "Per-destination smart routing": "Умная маршрутизация по назначению",
  "Exit via WARP": "Выход через WARP",
  "Custom interface…": "Свой интерфейс…",
  "Ways out of {v1}": "Выходы ноды {v1}",
  "Every way *{v1}* can leave that isn't its own address. WARP accounts and pasted profiles are created under Settings → WARP; the devices below the line are this node's own, or names you add here.":
    "Всё, через что *{v1}* может выходить, кроме собственного адреса. Аккаунты WARP и вставленные профили создаются в разделе «Настройки → WARP»; устройства ниже — собственные устройства этой ноды или имена, добавленные здесь.",
  "val|WARP+": "ВАРП+",
  "WARP exit": "ВАРП выход",
  "WARP+ exit": "ВАРП+ выход",
  "Custom exit": "Свой выход",
  "val|Edit": "Изменить",
  "Exit IP": "IP выхода",
  "Connect from": "Подключаться с",
  "Auto ({v1})": "Авто ({v1})",
  "The tunnel's own address — traffic leaves as this.": "Собственный адрес туннеля — трафик уходит под ним.",
  "This node has never reported an IP address for this device. If it doesn't have one, traffic sent through it is thrown away on the way out, and nothing here will look wrong. Type the address in if you know it.":
    "Нода ни разу не сообщила IP-адрес этого устройства. Если адреса у него нет, трафик через него выбрасывается по дороге, и здесь ничто на это не укажет. Впишите адрес, если знаете его.",
  "Configuration": "Конфигурация",
  "Edit it here or paste a replacement. IPv4 only — the v6 half is dropped, and routing lines are ignored because this node decides its own. The PrivateKey line is a placeholder: leave it and the stored key is kept, replace it and the new one is used.":
    "Редактируйте здесь или вставьте другой. Только IPv4 — часть с v6 отбрасывается, строки маршрутизации игнорируются: нода решает это сама. Строка PrivateKey — заглушка: оставьте её, и сохранённый ключ останется прежним; замените — будет использован новый.",
  "A free account is registered without one. Paste a key from the WARP mobile app to upgrade this exit to WARP+.":
    "Без ключа регистрируется бесплатный аккаунт. Вставьте ключ из мобильного приложения WARP, чтобы поднять этот выход до WARP+.",
  "{v1} is removed from this node and its tunnel comes down. The profile and its key are deleted from the panel — you would have to paste it again.":
    "{v1} будет удалён с этой ноды, туннель опустится. Профиль и его ключ удаляются из панели — вставлять придётся заново.",
  "{v1} is removed from this node and its tunnel comes down. The Cloudflare account is deleted with it: re-adding one registers a NEW account with a different exit IP.":
    "{v1} будет удалён с этой ноды, туннель опустится. Вместе с ним удаляется и аккаунт Cloudflare: при повторном добавлении регистрируется НОВЫЙ аккаунт с другим IP выхода.",
  "No WARP exits on this node yet. Register a free Cloudflare account, or paste a WireGuard profile from somewhere else.":
    "На этой ноде пока нет ВАРП выходов. Зарегистрируйте бесплатный аккаунт Cloudflare или вставьте профиль WireGuard откуда-то ещё.",
  "val|Unsaved": "Не сохранён",
  "Refused: {v1}": "Отклонён: {v1}",
  "This node hasn't reported a device by this name.": "Нода не сообщала об устройстве с таким именем.",
  "Up on the node.": "Поднят на ноде.",
  "The node reports this device is not up.": "Нода сообщает, что устройство не поднято.",
  "val|Type": "Тип",
  "Used by": "Кто использует",
  "Leaves as": "Уходит как",
  "val|Untitled": "Без названия",
  "val|unusable": "недоступен",
  "val|Discovered": "Обнаружен",
  "val|Custom": "Свой",
  "all traffic": "весь трафик",
  "This node's default": "Умолчание этой ноды",
  "anything not pinned elsewhere": "всё, что не закреплено отдельно",
  "val|Not used": "Не используется",
  "Turning it off sends these out directly — they keep the selection.":
    "Если выключить, они пойдут напрямую — выбор при этом сохранится.",
  "Remove this interface?": "Удалить этот интерфейс?",
  "{v1} is a name you added, and this node has never reported a device called that — removing it takes it out of every exit list. Nothing on the box is touched.":
    "{v1} — это имя, которое добавили вы, и нода никогда не сообщала об устройстве с таким именем. Удаление уберёт его из всех списков выходов. На самой машине ничего не меняется.",
  "This node reports no devices that could be an exit, and nothing has been added by hand.":
    "Нода не сообщает ни об одном устройстве, годном для выхода, и вручную ничего не добавлено.",
  "A device this node hasn't reported. Add it if you know it is there — nothing is checked until the node next syncs.":
    "Устройство, о котором нода не сообщала. Добавьте, если знаете, что оно есть — проверка произойдёт при следующей синхронизации.",
  "Add an interface by name": "Добавить интерфейс по имени",
  "Manage…": "Управление…",
  "Couldn't save": "Не удалось сохранить",
  "Title — optional": "Название — необязательно",
  "Rename": "Переименовать",
  "Remove this exit?": "Удалить этот exit?",
  "Delete?": "Удалить?",
  "val|Yes": "Да",
  "val|No": "Нет",
  "Answer the question on this row first.": "Сначала ответьте на вопрос в этой строке.",
  "val|Add": "Добавить",
  "val|Cancel": "Отмена",
  "A tunnel something else on this node runs that it hasn't reported — a proxy's TUN, a WireGuard client. It is added to this node's exits and chosen here.":
    "Туннель, который поднимает что-то другое на этой ноде и о котором она не сообщила — TUN прокси, клиент WireGuard. Он добавится в exit'ы этой ноды и будет выбран здесь.",
  "not up": "не поднят",
  "{v1} — {v2}": "{v1} — {v2}",
  "Turned off": "Выключен",
  "{v1} is turned off. Switch it on first, then choose it.": "{v1} выключен. Сначала включите его, потом выбирайте.",
  "Choose which exit this interface leaves by.": "Выберите, через какой exit выходит этот интерфейс.",
  "Choose which exit this rule leaves by.": "Выберите, через какой exit выходит это правило.",
  "That exit no longer exists — traffic goes out directly. Choose another, or add it back under Settings → Network.":
    "Этого exit'а больше нет — трафик уходит напрямую. Выберите другой или добавьте его снова в Настройках → Сеть.",
  "This exit is turned off — traffic goes out directly until it is turned back on. The interface keeps this selection.":
    "Этот exit выключен — пока его не включат обратно, трафик уходит напрямую. Интерфейс сохраняет выбор.",
  "This exit's device can't be used right now — traffic goes out directly. Settings → Network says why.":
    "Устройство этого exit'а сейчас использовать нельзя — трафик уходит напрямую. Причина указана в Настройках → Сеть.",
  // which SOURCE the chosen exit leaves as — reported here, edited on the exit record itself.
  // §7 — a NIC pinned for NAT that the routing does not use. "Авто" is the word `val|Auto` /
  // `Auto ({v1})` put in the dropdown this sentence points at, so the two agree on screen.
  "exit →": "exit →",
  "exit — removed": "exit — удалён",
  "Not a usable device name — up to 15 characters: letters, digits, dot, dash or underscore.":
    "Такое имя устройства не подходит — до 15 символов: буквы, цифры, точка, дефис или подчёркивание.",
  "This exit is turned off — traffic goes out directly, and the interface keeps the selection":
    "Этот exit выключен — трафик уходит напрямую, интерфейс сохраняет выбор",
  "This exit's device can't be used — traffic goes out directly, and the interface keeps the selection":
    "Устройство этого exit'а использовать нельзя — трафик уходит напрямую, интерфейс сохраняет выбор",
  // The card's three verdicts. `nic` is "we have no data", not a claim about the card.
  "This node hasn't said which of its network cards have a gateway yet. Update the node, and a card that has one can be used as an exit.":
    "Этот узел ещё не сообщил, у каких из его сетевых карт есть шлюз. Обновите узел — и карту со шлюзом можно будет использовать как exit.",
  "This node reports no gateway for {v1}, so there's no way off the box through it. Give it a default route on the node, or set the gateway on the exit under Settings → Network.":
    "Узел не сообщает шлюз для {v1}, поэтому через неё нет выхода с машины. Задайте на узле маршрут по умолчанию или укажите шлюз у exit'а в Настройках → Сеть.",
  "That's already where this node's traffic leaves, so choosing it would change nothing — and it would report no traffic of its own. Leave the outbound interface on Auto instead.":
    "Через неё трафик этого узла и так уходит, так что выбор ничего не изменит — и собственного трафика она показывать не будет. Оставьте интерфейс выхода на «Авто».",
  "Leaves this node through {v1}": "Выходит с этой ноды через {v1}",
  "The exit this interface was set to is gone — traffic goes out directly, and the interface keeps the selection":
    "Указанного для этого интерфейса exit'а больше нет — трафик уходит напрямую, выбор сохраняется",
  "{v1} — external exits": "{v1} — ВАРП выходы",
  "Register with WARP": "Зарегистрировать WARP",
  "state|On": "Вкл",
  "Default exit": "Выход по умолчанию",
  "— where traffic leaves by": "— через что уходит трафик",
  "default exit": "выход по умолчанию",
  "Default ({v1})": "По умолчанию ({v1})",
  "val|Default": "по умолчанию",
  "How *{v1}* leaves for the internet by default, and as which address. An interface that makes its own choice keeps it — these apply to the ones set to Auto, and to traffic cascaded in from other nodes.":
    "Как *{v1}* по умолчанию выходит в интернет и под каким адресом. Интерфейс, сделавший свой выбор, его сохраняет — это применяется к тем, что стоят на «Авто», и к трафику, пришедшему каскадом с других нод.",
  "No exits on this node yet — add one under External exits to offer it here.":
    "На этой ноде пока нет exit'ов — добавьте его в разделе «Внешние exit'ы», чтобы он появился здесь.",
  "Restore from vault": "Восстановить из хранилища",
  "Restoring — the node applies it on its next sync.": "Восстанавливаем — нода применит это на следующей синхронизации.",
  "No escrowed key is stored for this.": "Для этого не сохранён ключ в хранилище.",
  "No escrowed key is stored for this exit.": "Для этого exit'а не сохранён ключ в хранилище.",
  "Retrying in {v1}.": "Повтор через {v1}.",
  "{v1} min": "{v1} мин",
  "{v1} s": "{v1} с",
  "This node has no key for this exit. Restore the escrowed one to keep the same address, or leave it to register a new account.":
    "У этой ноды нет ключа для этого exit'а. Восстановите сохранённый, чтобы адрес не изменился, либо оставьте как есть — будет зарегистрирован новый аккаунт.",
  "val|WARP": "ВАРП",
  "No nodes yet — enroll a node to give it a way out that isn't its own address.":
    "Нод пока нет — подключите ноду, чтобы дать ей путь наружу, отличный от её собственного адреса.",
  "This node isn't dialling out anywhere yet, so there's nothing to offer. Register with WARP or paste a profile instead — or type a device name if you run one.":
    "Эта нода пока никуда не подключается наружу, поэтому предлагать нечего. Зарегистрируйте WARP или вставьте профиль — либо введите имя устройства, если оно у вас есть.",
  "This node already runs that device for one of its own exits — pick that exit instead.":
    "Эта нода уже поднимает это устройство для одного из своих exit'ов — выберите тот exit.",
  "WARP+ licence key": "Ключ WARP+",
  "Paste a custom config": "Вставить свой конфиг",
  "Paste the profile before saving.": "Перед сохранением вставьте профиль.",
  "Cloudflare WARP accounts and WireGuard profiles from anywhere else. Websites see the exit rather than this node.":
    "Аккаунты Cloudflare WARP и профили WireGuard откуда угодно ещё. Сайты видят exit, а не эту ноду.",
  "WARP+ licence key — optional": "Ключ WARP+ — необязательно",
  "Paste the [Interface] / [Peer] profile here": "Вставьте сюда профиль с [Interface] / [Peer]",
  "Paste a WireGuard profile for the new exit, or remove it.":
    "Вставьте профиль WireGuard для нового exit'а или удалите его.",
  "Waiting for the node to set this up…": "Ожидание: нода ещё настраивает…",
  // A WARP exit whose node minted a new account. «Адрес, который видят сайты» is the fact an operator
  // actually notices; «ключ, который был до этого» avoids «предыдущий эскроу», which nobody says.
  "This exit registered a new account, so the address websites see has changed. The panel still holds the key it had before.":
    "Этот выход зарегистрировал новый аккаунт, поэтому адрес, который видят сайты, изменился. Ключ, который был до этого, у панели сохранён.",
  "Put the old one back": "Вернуть прежний",
  // The two vault prompts for an exit restore. They share the WDTT prompt's shape (title / why / what
  // skipping costs) because it is the same act: opening ciphertext only the operator can open.
  "Unlock to put the old key back": "Разблокируйте, чтобы вернуть прежний ключ",
  "This exit's original account is escrowed under your encryption key — the panel only ever held the ciphertext, and only you can open it. Unlock it to put that account back, along with any WARP+ licence on it. Cloudflare picks the exit address, so the old one usually comes back with it.":
    "Исходный аккаунт этого выхода лежит в хранилище под вашим ключом шифрования — панель хранила только шифротекст, открыть его можете только вы. Разблокируйте, чтобы вернуть этот аккаунт вместе с лицензией WARP+, если она на нём была. Адрес выхода назначает Cloudflare, так что прежний обычно возвращается вместе с аккаунтом.",
  "nothing changes. The exit keeps the account it just registered, and the address websites see stays the new one.":
    "ничего не изменится: выход останется на только что зарегистрированном аккаунте, а сайты будут видеть новый адрес.",
  "Unlock to restore this exit's key": "Разблокируйте, чтобы восстановить ключ выхода",
  "This node has no key for this exit, and the one it had is escrowed under your encryption key — the panel only ever held the ciphertext. Unlock it to give the node its original account back instead of a new one.":
    "У ноды нет ключа для этого выхода, а прежний лежит в хранилище под вашим ключом шифрования — панель хранила только шифротекст. Разблокируйте, чтобы вернуть ноде исходный аккаунт вместо нового.",
  "nothing is restored. The node registers a new account on its next pass instead, and websites start seeing a different address.":
    "ничего не восстановится: нода на следующем проходе зарегистрирует новый аккаунт, и сайты увидят другой адрес.",
  "Keep the new one": "Оставить новый",
  "Keeping the new account.": "Оставляем новый аккаунт.",
  // The two switches on the exits grid. «Отказ» not «блокировка» — the traffic is refused, not filtered;
  // «своим адресом» is the whole point of the off state. For Active, «аккаунт и ключи сохраняются» is the
  // fact that had to be said: this is the switch that once destroyed the account it claimed to pause.
  "On: if this exit stops working, traffic using it is refused. Off: it falls back to this node's own address.":
    "Включено: если выход перестанет работать, трафик через него получит отказ. Выключено — он уйдёт своим адресом этой ноды.",
  "Off pauses this exit — its account and keys are kept, and anything pointing at it stays pointed at it and uses the node's default meanwhile.":
    "Выключение ставит выход на паузу: аккаунт и ключи сохраняются, всё, что на него указывает, продолжает на него указывать и пока идёт через выход ноды по умолчанию.",
  // A node whose swg-noded predates the exits feature. «Слишком старая» about the software, not the box —
  // «прошивка» would be wrong for a server — and the second sentence is the whole point: the exit itself is
  // fine, so nothing here needs re-entering after the update.
  "This node's software is too old for exits. Update the node — nothing else needs changing.":
    "Версия swg-noded на этой ноде слишком старая для exit'ов. Обновите ноду — больше ничего менять не нужно.",
  // A WARP exit that never handshook. «Не ваша вина» would be too chatty; «здесь нечего исправлять» says the
  // same thing in the panel's register. «Сети, которые блокируют WARP, выглядят ровно так» keeps the hedge —
  // the panel cannot prove it is the network, only that it looks like one.
  "The tunnel is up, but Cloudflare never answered it. Nothing here is yours to correct — the keys and the endpoint are the panel's own. Networks that block WARP look exactly like this, so try a pasted profile instead, or put this exit on another node.":
    "Туннель поднят, но Cloudflare ни разу не ответил. Здесь нечего исправлять — ключи и endpoint панель выдала сама. Сети, которые блокируют WARP, выглядят ровно так: попробуйте вставить свой профиль или перенести этот выход на другую ноду.",
  "This exit has stopped carrying traffic, so the kill-switch is holding everything that uses it. It resumes by itself once the exit works again.":
    "Этот выход перестал пропускать трафик, поэтому kill-switch удерживает всё, что через него идёт. Трафик возобновится сам, как только выход снова заработает.",
  "This exit has stopped carrying traffic, so everything that uses it is going out through this node's own IP. It moves back by itself once the exit works again.":
    "Этот выход перестал пропускать трафик, поэтому всё, что через него шло, уходит через собственный IP этой ноды. Трафик сам вернётся в выход, как только он снова заработает.",
  "Applying your changes on the node…": "Применяем изменения на ноде…",
  "external exits": "внешние exit'ы",
  "This node is sending something the panel cannot read, so it has stopped syncing: {v1}. Its peers are left exactly as they were.": "Нода присылает данные, которые панель не может прочитать, поэтому синхронизация остановлена: {v1}. Её пиры остались ровно такими, какими были.",
  "external exit": "внешний exit",
  "Choose a device for the new exit, or remove it.": "Выберите устройство для нового exit'а или удалите его.",
  "Active": "Активен",
  "Kill-switch": "Kill-switch",

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
  "The node is converting between bare-metal and docker": "Нода конвертируется между bare-metal и docker",
  // budget-ok: hover caption
  "Server wiped — its identity is escrowed; open to Restore or Recreate fresh":
    "Сервер стёрт — его идентичность в хранилище; откройте, чтобы восстановить или пересоздать заново",
  "Exits directly from this node": "Выходит напрямую с этой ноды",
  // budget-ok: hover caption
  "Stopped by you — open to Start it": "Остановлен вами — откройте, чтобы запустить",
  "Interface down on the node": "Интерфейс не поднят на ноде",
  // budget-ok: hover caption
  "{v1}: the exit device {v2} is down — the kill-switch is holding {v3}, so nothing is leaving. Bring {v2} up to restore it.": "{v1}: устройство выхода {v2} выключено — kill-switch удерживает {v3}, наружу ничего не уходит. Поднимите {v2}, чтобы восстановить выход.",
  "{v1}: the exit device {v2} is down — {v3} is falling back to this node's own IP instead of the exit. Bring {v2} up, or turn the exit's kill-switch on to stop the traffic instead.": "{v1}: устройство выхода {v2} выключено — {v3} уходит через собственный IP этой ноды вместо exit'а. Поднимите {v2} или включите у этого exit'а kill-switch, чтобы трафик вместо этого останавливался.",
  "{v1}: the tunnel through {v2} has stopped carrying traffic — the kill-switch is holding {v3}, so nothing is leaving. Traffic resumes by itself once the exit works again.": "{v1}: туннель через {v2} перестал пропускать трафик — kill-switch удерживает {v3}, наружу ничего не уходит. Трафик возобновится сам, как только exit снова заработает.",
  "{v1}: the tunnel through {v2} has stopped carrying traffic — {v3} is going out through this node's own IP until it works again, then moves back by itself. Turn the exit's kill-switch on to stop the traffic instead.": "{v1}: туннель через {v2} перестал пропускать трафик — {v3} уходит через собственный IP этой ноды, пока exit не заработает, а затем сам вернётся обратно. Включите у этого exit'а kill-switch, чтобы трафик вместо этого останавливался.",
  "This node is at its limit of {v1} places it can route to, so these exits never got a slot: {v2}. Their kill-switch is holding nothing — that traffic is going out directly instead of stopping. Remove an exit or a forward to free a slot.": "Нода достигла предела в {v1} направлений маршрутизации, поэтому эти exit'ы не получили слот: {v2}. Их kill-switch ничего не удерживает — трафик уходит напрямую вместо того, чтобы остановиться. Удалите exit или переброс, чтобы освободить слот.",
  "This node is at its limit of {v1} places it can route to, so these never got a slot and their traffic is going out directly: {v2}. Remove an exit or a forward to free a slot.": "Нода достигла предела в {v1} направлений маршрутизации, поэтому эти не получили слот и их трафик уходит напрямую: {v2}. Удалите exit или переброс, чтобы освободить слот.",
  "This node is at its limit of {v1} places it can route to, and {v2} of the places it sends traffic never got a slot — that traffic is going out directly. Remove an exit or a forward to free a slot.": "Нода достигла предела в {v1} направлений маршрутизации, и {v2} из направлений, куда она шлёт трафик, не получили слот — этот трафик уходит напрямую. Удалите exit или переброс, чтобы освободить слот.",
  "This node's mesh subnet {v1} is not an IPv4 range of /31 or larger, so its links to {v2} cannot be made. Fix it in this node's settings.": "Подсеть меша этой ноды {v1} не является диапазоном IPv4 размером /31 или шире, поэтому меш-линки к этим нодам не создаются: {v2}. Исправьте её в настройках ноды.",
  "The panel's mesh subnet {v1} is not an IPv4 range of /31 or larger, so this node's links to {v2} cannot be made. Fix it in Panel settings.": "Подсеть меша панели {v1} не является диапазоном IPv4 размером /31 или шире, поэтому меш-линки этой ноды к этим нодам не создаются: {v2}. Исправьте её в настройках панели.",
  "This node's mesh subnet {v1} has no free /31 left, so its links to {v2} cannot be made. Widen it in this node's settings.": "В подсети меша этой ноды {v1} не осталось свободных /31, поэтому меш-линки к этим нодам не создаются: {v2}. Расширьте её в настройках ноды.",
  "The panel's mesh subnet {v1} has no free /31 left, so this node's links to {v2} cannot be made. Widen it in Panel settings.": "В подсети меша панели {v1} не осталось свободных /31, поэтому меш-линки этой ноды к этим нодам не создаются: {v2}. Расширьте её в настройках панели.",
  "{v1}: there is no device called {v2} on this node — the kill-switch is holding {v3}, so nothing is leaving. Correct the device name on the exit to restore it.": "{v1}: на этой ноде нет устройства с именем {v2} — kill-switch удерживает {v3}, наружу ничего не уходит. Исправьте имя устройства у этого exit'а, чтобы восстановить выход.",
  "{v1}: there is no device called {v2} on this node — {v3} is falling back to this node's own IP instead of the exit. Correct the device name on the exit, or turn its kill-switch on to stop the traffic instead.": "{v1}: на этой ноде нет устройства с именем {v2} — {v3} уходит через собственный IP этой ноды вместо exit'а. Исправьте имя устройства у этого exit'а или включите у него kill-switch, чтобы трафик вместо этого останавливался.",
  "strict reverse-path filtering is still on for {v1} — replies to routed traffic are dropped, so a cascade or exit route carries packets out and nothing comes back. Set net.ipv4.conf.{v1}.rp_filter=2 on the host (a container can't set it for itself).": "строгая проверка обратного пути всё ещё включена для {v1} — ответы на маршрутизируемый трафик отбрасываются, поэтому каскад или маршрут через exit выпускает пакеты наружу, а обратно ничего не приходит. Установите net.ipv4.conf.{v1}.rp_filter=2 на хосте (контейнер не может сделать это сам).",
  "{v1}: edited directly on the server": "{v1}: изменено напрямую на сервере",
  "{v1}: the escrowed key hasn't been proved to open — unlock the vault and the panel checks it": "{v1}: депонированный ключ ещё не проверен на открытие — разблокируйте хранилище, и панель это проверит",
  "{v1}: egress IP {v2} is no longer on the node": "{v1}: исходящий IP {v2} больше не принадлежит ноде",
  "{v1}: WAN interface {v2} is no longer on the node": "{v1}: WAN-интерфейс {v2} больше не существует на ноде",
  "{v1}: interface down on the node": "{v1}: интерфейс опущен на ноде",
  "{v1}: interface down on the node (repair available)": "{v1}: интерфейс опущен на ноде (доступно исправление)",
  "{v1}: interface stopped": "{v1}: интерфейс остановлен",
  "{v1}: will not start after a reboot — update this node to repair it": "{v1}: не поднимется после перезагрузки — обновите ноду, чтобы это исправить",
  "{v1}: not running": "{v1}: не запущен",
  // «перезапусков: N» — the count after a colon, so it never has to agree with a noun (3 перезапуска / 5 перезапусков)
  "{v1}: crash-looping — {v2} restarts in {v3} min": "{v1}: падает по кругу — перезапусков за {v3} мин: {v2}",
  "the address clients dial ({v1}) is no longer on this node — new turn-proxies are created with it and will fail to start": "адрес, на который подключаются клиенты ({v1}), больше не принадлежит этой ноде — новые turn-прокси создаются с ним и не смогут запуститься",
  "{v1} {v2} is bound to {v3}, which is no longer on this node": "{v1} {v2} привязан к {v3} — этого адреса больше нет на ноде",
  "{v1}: interface missing on the node (restore available)": "{v1}: интерфейс отсутствует на ноде (доступно восстановление)",
  "AmneziaWG kernel module not built/loaded — awg interfaces run on the slower fallback datapath; update the node to rebuild the module": "Модуль ядра AmneziaWG не собран или не загружен — awg-интерфейсы работают на более медленном резервном датапасе в пользовательском пространстве; обновите ноду, чтобы пересобрать модуль",
  "{v1}: on the slower fallback datapath — update the node to move it back to the kernel module": "{v1}: на более медленном резервном датапасе — обновите ноду, чтобы вернуть его на модуль ядра",
  "AmneziaWG runs on the slower fallback datapath — its kernel module isn’t built or loaded; running Update rebuilds it": "AmneziaWG работает на более медленном резервном датапасе — модуль ядра не собран или не загружен; «Обновить» пересоберёт его",
  "AmneziaWG kernel module not built/loaded — awg interfaces can't come up; update the node to rebuild it": "Модуль ядра AmneziaWG не собран или не загружен — awg-интерфейсы не поднимутся; обновите ноду, чтобы пересобрать его",
  "IP forwarding is off on this node — peers connect but nothing they send can leave it. Set net.ipv4.ip_forward=1 on the host (a container can't set it for itself).": "На этой ноде выключена IP-маршрутизация — пиры подключаются, но отправленный ими трафик не может уйти с сервера. Установите net.ipv4.ip_forward=1 на хосте (контейнер не может сделать это сам).",
  "{v1}: this mesh link listens on UDP {v2}, outside this node's declared firewall range ({v3}) — other nodes cannot open the link to this one; it only comes up while this node dials out. Add the mesh port band to the range": "{v1}: меш-линк слушает UDP {v2} вне объявленного диапазона фаервола этой ноды ({v3}) — другие ноды не могут открыть линк к ней, он поднимается, только пока эта нода подключается сама. Добавьте в диапазон порты меш-линков",
  "{v1}: listens on UDP {v2}, outside this node's declared firewall range ({v3}) — clients cannot reach it until the range covers that port, or the interface moves inside it": "{v1}: слушает UDP {v2} вне объявленного диапазона фаервола этой ноды ({v3}) — клиенты не смогут подключиться, пока диапазон не покроет этот порт или интерфейс не переедет внутрь него",
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
    "Нода больше не сообщает об {iface}, и {verdict} — восстанавливать нечего. Пересоздайте его с новым ключом; каждому клиенту нужно будет заново импортировать конфиг — это {count}.",
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
  "AmneziaWG on this node is running on the slower fallback datapath — its kernel module isn't loaded, or its interfaces haven't moved back to it yet. ": "AmneziaWG на этой ноде работает на более медленном резервном датапасе — модуль ядра не загружен или интерфейсы ещё не вернулись на него. ",
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
  // ── the declarative pair: this host's installation comes from its configuration (NixOS) ──
  "This box's installation comes from its {what}, so an update is a rebuild of it — do that on the {side} box, however that configuration is applied.":
    "Установка этого сервера берётся из {what}, поэтому обновление — это его пересборка. Сделайте это на сервере {side} — тем способом, которым применяется эта конфигурация.",
  "This node can't be updated from the panel — run the command shown in the dialog on the box.":
    "Эту ноду нельзя обновить из панели — выполните на сервере команду из диалога.",
  "This box's installation comes from its {what}, so an update is a rebuild of it — run this on the {side} box:":
    "Установка этого сервера берётся из {what}, поэтому обновление — это его пересборка. Выполните это на сервере {side}:",
  // budget-ok: bold run inside wrapping prose
  "own configuration": "собственной конфигурации",
  "There is no rebuild wired to this button on this host, so it can't start one — that is deliberate: a button that reported success and changed nothing would be worse. Set the module's *selfUpdate* option to wire it, or run the command above.":
    "К этой кнопке на этом хосте не подключена пересборка, поэтому запустить её она не может — и это намеренно: кнопка, которая отчиталась об успехе и ничего не изменила, была бы хуже. Включите в модуле опцию *selfUpdate*, чтобы подключить её, или выполните команду выше.",
  "*Update now* asks this host to rebuild itself from that configuration. What it lands on is whatever the configuration's lock pins, so refresh the swg input first if you want a newer version — and the rebuild's own errors come back here if it fails.":
    "*Обновить сейчас* просит хост пересобрать себя из этой конфигурации. Соберётся то, что зафиксировано в её lock-файле, поэтому сначала обновите input swg, если нужна более новая версия, — а ошибки самой пересборки вернутся сюда, если она не удастся.",
  // budget-ok: toast, wraps
  "Update requested — applies on the node's next sync.": "Обновление запрошено — применится на следующей синхронизации ноды.",
  "{v1} skipped — turn-proxy management is off there, or their architecture has no published build.":
    "{v1} пропущено — там выключено управление turn-прокси, либо для их архитектуры нет опубликованной сборки.",
  "Automatic update isn't wired on this install — run the command shown in the dialog on the host.":
    "Автообновление на этой установке не подключено — выполните на хосте команду из диалога.",
  "Update started — the panel will restart shortly.": "Обновление запущено — панель скоро перезапустится.",
  "Update started — the panel will restart shortly. The nodes ({v1}) follow on their next sync.": "Обновление запущено — панель скоро перезапустится. Ноды ({v1}) подтянутся при следующей синхронизации.",
  "Couldn't reach the repo to check for updates.": "Не удалось достучаться до репозитория за обновлениями.",
  // Why the repo could not be reached. The stem is repeated in every one of these rather than glued to a
  // translated fragment: {v1} and the cause sit in a different order in Russian, and a translator needs the
  // whole sentence to move them. «Достучаться» matches the generic line above, which operators already know.
  "Couldn't reach {v1} to check for updates — its name could not be resolved.":
    "Не удалось достучаться до {v1} за обновлениями — имя не резолвится.",
  "Couldn't reach {v1} to check for updates — the connection was refused.":
    "Не удалось достучаться до {v1} за обновлениями — соединение отклонено.",
  "Couldn't reach {v1} to check for updates — the connection was reset.":
    "Не удалось достучаться до {v1} за обновлениями — соединение сброшено.",
  "Couldn't reach {v1} to check for updates — there is no route to it from this server.":
    "Не удалось достучаться до {v1} за обновлениями — с этого сервера до него нет маршрута.",
  "Couldn't reach {v1} to check for updates — it did not answer in time.":
    "Не удалось достучаться до {v1} за обновлениями — он не ответил вовремя.",
  // budget-ok: toast, wraps
  "Couldn't reach {v1} to check for updates — its TLS certificate could not be verified. The CA certificates on this server may be missing or out of date.":
    "Не удалось достучаться до {v1} за обновлениями — не удалось проверить его TLS-сертификат. Возможно, на этом сервере нет корневых сертификатов или они устарели.",
  "Couldn't reach {v1} to check for updates — the TLS connection failed.":
    "Не удалось достучаться до {v1} за обновлениями — не удалось установить TLS-соединение.",
  "Couldn't reach {v1} to check for updates — {v2}.":
    "Не удалось достучаться до {v1} за обновлениями — {v2}.",
  "{v1} is rate-limiting this server's address — try the check again in a few minutes.":
    "{v1} ограничивает запросы с адреса этого сервера — повторите проверку через несколько минут.",
  "{v1} answered {v2} to the update check.": "{v1} ответил {v2} на проверку обновлений.",
  "{v1} answered, but not with a version.": "{v1} ответил, но не версией.",
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

  // ── exit-device picker (plan §11.3/§11.4). Only `bad` warns; the rest say nothing or add a caveat.
  "An interface can't exit through itself.": "Интерфейс не может выходить сам через себя.",
  "That's a mesh link — send traffic there with “Forward to node”, which sets up the return path too.":
    "Это меш-линк — отправьте туда трафик через «Переслать на ноду», там заодно настраивается обратный путь.",
  "That's an interface this node serves clients on, not a way out of it.":
    "Это интерфейс, на котором нода обслуживает клиентов, а не выход из неё.",
  "That's a server device clients arrive on, not a way out.":
    "Это устройство сервера, куда приходят клиенты, а не выход.",
  "Loopback isn't a way out of this node.": "Loopback — не выход из этой ноды.",
  "This node doesn't report a device by that name.": "Нода не сообщает об устройстве с таким именем.",
  "val|No device reported": "устройств не найдено",
  "val|Choose a device…": "выберите устройство…",
  "Device name — e.g. wgcf": "Имя устройства — например, wgcf",
  "This device exists but is down right now — traffic will fall through until it comes back.":
    "Устройство есть, но сейчас не поднято — пока оно не вернётся, трафик пойдёт обычным путём.",
  "This device isn't set to come back after a reboot.":
    "Устройство не настроено на автозапуск после перезагрузки.",
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
  // budget-ok: label suffix, wraps with the label
  "— optional, to tell devices apart": "— необязательно, чтобы различать устройства",
  "iPhone, Router, Laptop…": "iPhone, роутер, ноутбук…",
  "Targets": "Цели",
  "— one, or several for redundancy (same credential)": "— одна или несколько для резерва (тот же ключ)",
  "— check to deploy, uncheck to remove": "— отметить = развернуть, снять = убрать",
  // A peer holding several kinds holds several independent credentials — rotating it rotates all of them.
  "Rotate credentials": "Сменить данные",
  "Rotating credentials…": "Меняем данные…",
  "This peer holds several credentials — a WireGuard keypair and an access password per turn server. All of them are replaced: every config, QR and link this peer already handed out stops working and must be re-imported.":
    "У этого пира несколько учётных данных — пара ключей WireGuard и по паролю доступа на каждый turn-сервер. Заменяются все: каждый выданный конфиг, QR и ссылка перестанут работать, их нужно переимпортировать.",
  "Credentials rotated — send the user their new QR and links; the old ones no longer work.":
    "Данные сменены — отправьте пользователю новый QR и ссылки; старые больше не работают.",
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
  // ONE list for every kind — a peer may hold wg/awg + WDTT + csqtt at once, so the old pair of
  // mutually-exclusive "Servers" / "Addresses" lists (and their per-kind hints) is gone.
  "label|Deployments": "Развёртывания",

  // Naming a NEW self-contained turn instance. Creation used to demand wdtt<N> / csqtt<N>; the operator
  // picks the name now, so these are the checks that pattern was standing in for.
  "Name: letters, digits, - and _ (max 15, starting with a letter or digit).":
    "Имя: буквы, цифры, - и _ (не больше 15, начинается с буквы или цифры).",
  "Names starting with swg_ are reserved for system mesh links.":
    "Имена, начинающиеся с swg_, зарезервированы за служебными связями сети.",
  "{v1} is already a {v2} instance on this node.": "{v1} на этой ноде уже занят экземпляром {v2}.",
  "{v1} is already a WireGuard interface on this node.": "{v1} на этой ноде уже занят интерфейсом WireGuard.",
  "Changing an address moves the peer on that interface.":
    "Смена адреса переносит пира на этом интерфейсе.",
  "Changing an address moves the peer on that interface. The gear holds that deployment's DNS, MTU and routing.":
    "Смена адреса переносит пира на этом интерфейсе. За шестерёнкой — DNS, MTU и маршрутизация этого развёртывания.",
  "These servers assign each address on connect; the user's link per server is on their subscription. There's no client config (key/DNS/MTU) — the server owns the datapath.":
    "Эти серверы выдают адрес при подключении; ссылка на каждый сервер — на подписке пользователя. Клиентского конфига (ключ/DNS/MTU) нет — датапас у сервера.",

  // Per-deployment settings (the gear on a wg/awg row) — see TargetSettingsSheet.
  "Settings — {v1}": "Настройки — {v1}",
  "These apply to this deployment only — {v1} on {v2}. The peer's other deployments keep their own.":
    "Действуют только на это развёртывание — {v1} на {v2}. У остальных развёртываний пира свои.",
  "Reset to interface defaults": "Сбросить к настройкам интерфейса",
  "Apply": "Применить",
  "Settings for this deployment (customised)": "Настройки этого развёртывания (изменены)",
  "Settings for this deployment (DNS, MTU, routing)": "Настройки этого развёртывания (DNS, MTU, маршруты)",
  "Use the gear on a row for that deployment's DNS, MTU and routing.":
    "Шестерёнка в строке — DNS, MTU и маршрутизация этого развёртывания.",
  "AmneziaWG obfuscation parameters come from the interface itself and are the same for every client on it — change them in the interface's settings.":
    "Параметры обфускации AmneziaWG задаются самим интерфейсом и одинаковы для всех его клиентов — меняйте их в настройках интерфейса.",
  "This is a plain WireGuard interface, so it carries no AmneziaWG obfuscation parameters.":
    "Это обычный интерфейс WireGuard, параметров обфускации AmneziaWG у него нет.",
  // "iface: message" — prefixes a field error with the deployment it belongs to.
  "{v1}: {v2}": "{v1}: {v2}",

  // Node create / recover / remove
  "Node colour": "Цвет ноды",
  "Done": "Готово",
  // budget-ok: bold lead-in inside a notice, wraps
  "Shown once.": "Показывается один раз.",
  "This token authenticates the node to the panel — copy it now. You can rotate it later if it leaks.":
    "Этот токен подтверждает ноду перед панелью — скопируйте его сейчас. Позже его можно сменить, если он утечёт.",
  "Pick the one this node runs. Each fetches the installer and prompts for the endpoint.":
    "Выберите то, на чём работает эта нода. Каждая команда скачает установщик и спросит эндпоинт.",
  "① Save the enrolment token on the node":
    "① Сохраните токен подключения на ноде",
  "② Create /etc/nixos/flake.nix":
    "② Создайте /etc/nixos/flake.nix",
  "③ Build, switch, then reboot for the kernel datapath":
    "③ Соберите, переключитесь и перезагрузитесь ради ядерного датапата",
  "③ Build and switch":
    "③ Соберите и переключитесь",
  "Bare-metal (kernel)":
    "Bare-metal (ядро)",
  "Podman (container)":
    "Подман (контейнер)",
  "Runs the published image via podman (nixpkgs flags the docker package insecure; podman is not), no reboot. Replace the endpoint with this server's public IP — the panel's Update button then works with nothing else to set.":
    "Запускает опубликованный образ через podman (nixpkgs помечает пакет docker небезопасным, podman — нет), без перезагрузки. Замените endpoint на публичный IP этого сервера — кнопка «Обновить» в панели затем работает без дополнительной настройки.",
  "① Replace the token file on the node":
    "① Замените файл токена на ноде",
  "② Rebuild to pick it up":
    "② Пересоберите, чтобы применить",
  "This node's configuration already declares it — the two steps above just refresh the token and rebuild.":
    "Конфигурация этой ноды уже её объявляет — два шага выше лишь обновляют токен и пересобирают.",
  "Fresh box shown; if you already use a flake, add the swg-panel input and the services.swg-node block to yours instead. Replace the endpoint with this server's public IP — the panel's Update button then works with nothing else to set.":
    "Показан свежий сервер; если у вас уже есть flake, добавьте вход swg-panel и блок services.swg-node в него. Замените endpoint на публичный IP этого сервера — кнопка «Обновить» в панели затем работает без дополнительной настройки.",
  "Standard":
    "Обычный",
  "Declarative (NixOS)":
    "Декларативно (NixOS)",
  "Enrollment token": "Токен подключения",
  // budget-ok: toast, wraps
  "Copied": "Скопировано",
      "Run on the node —": "Выполните на ноде —",
    "This recovers {name} as {method} — the method it was already running, so its turn-proxies and interfaces are kept. To switch methods, convert the node instead.":
    "Восстановит {name} как {method} — тем же способом, которым нода уже работала, так что её turn-прокси и интерфейсы сохранятся. Чтобы сменить способ, конвертируйте ноду.",
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
  "This doesn't resolve to an address on this node. The proxy *binds* to it, so it must land on this box, or it dies with `bind: cannot assign requested address`.": "Это имя не разрешается в адрес этого узла. Прокси *привязывается* к нему, поэтому оно должно указывать на эту машину, иначе он падает с `bind: cannot assign requested address`.",
  "This doesn't resolve to an address on this node. The server *binds* to it, so it must land on this box, or it dies with `bind: cannot assign requested address`.": "Это имя не разрешается в адрес этого узла. Сервер *привязывается* к нему, поэтому оно должно указывать на эту машину, иначе он падает с `bind: cannot assign requested address`.",
  "Transfer token": "Токен переноса",
  "— to move an existing node here": "— чтобы перенести сюда узел",
  "Carries this panel's address and this token together. On the panel that has the node now: its Transfer window, and paste this — nothing is installed.": "Содержит адрес этой панели и этот токен вместе. На панели, где сейчас узел, откройте «Перенос» и вставьте это — ничего не устанавливается.",
  "The other panel's transfer token": "Токен переноса другой панели",
  "On the other panel: Nodes → Add node, then copy its Transfer token — it carries that panel's address and the new node's key together. An enrolment command still works if you have one; nothing is ever run.": "На другой панели: «Узлы» → «Добавить узел», затем скопируйте её токен переноса — он содержит адрес той панели и ключ нового узла. Команда установки тоже подойдёт, если она у вас есть; ничего не запускается.",
  "Escrowed server keys — re-sealed to the other panel's vault, not carried": "Депонированные ключи серверов — перезапечатываются в хранилище другой панели, а не переносятся",
  "These users have peers on other nodes here too — only this node moves, so those peers stay": "У этих пользователей есть пиры и на других узлах этой панели — переносится только этот узел, остальные пиры остаются",
  "Worth knowing before you do this": "Что стоит знать перед переносом",
  "Nothing here disconnects anybody — every peer keeps working. It is what the other panel will not know about, so you know where to look afterwards.": "Ничто из этого никого не отключает — все пиры продолжают работать. Это то, о чём не будет знать другая панель, чтобы вы знали, где искать потом.",
  "Hostnames for this node": "Имена (hostnames) этого узла",
  "— offered wherever a host is asked for": "— предлагаются везде, где нужен хост",
  "Add a name": "Добавить имя",
  "vpn.example.com": "vpn.example.com",
  "This doesn't resolve to an address on this node.": "Это имя не разрешается в адрес этого узла.",
  "Every picker that asks for a host offers these — interfaces, turn proxies, WDTT and csqtt. They do not change what clients dial; the ingress address above does that.": "Эти имена предлагаются везде, где спрашивают хост — интерфейсы, turn-прокси, WDTT и csqtt. Они не меняют то, что набирают клиенты: за это отвечает адрес входа выше.",
  "other names": "другие имена",
  "Use a different token": "Другой токен",
  "Transferred here": "Перенесён сюда",
  "Arrived from *{v1}* on *{v2}*.": "Прибыл с *{v1}* — *{v2}*.",
  "{date} at {time}": "{date} в {time}",
  "an unrecorded time": "неизвестно когда",
  "It was called «{v1}» there.": "Там он назывался «{v1}».",
  "Anything from before that — its history, its stored baselines — is still on that panel. Clearing this only removes the note here; the node is not touched.": "Всё, что было до этого — история, сохранённые слепки — осталось на той панели. Очистка убирает только эту заметку; сам узел не затрагивается.",
  "Clearing…": "Очищаем…",
  "Couldn't clear it.": "Не удалось очистить.",
  "The panel changes these for you when the node comes back. An address of the old box cannot be bound on the new one, and its address is not known yet — so a listener becomes 0.0.0.0, which is every address the new box turns out to have, and a source address becomes auto. Clients are unaffected either way: a wildcard listener is what tells the panel to advertise this node's ingress name, exactly as a wg/awg interface already does. Anything not listed keeps what it has.": "Панель меняет это за вас, когда узел вернётся. Адрес старой машины нельзя занять на новой, а её адрес пока неизвестен — поэтому слушатель становится 0.0.0.0, то есть всеми адресами, какие у новой машины окажутся, а исходящий адрес — «авто». Клиентов это никак не задевает: 0.0.0.0 как раз и означает, что панель объявляет имя входа этого узла — ровно так же, как уже делает интерфейс wg/awg. Всё, чего нет в списке, сохраняется как есть.",
  "word|endpoint": "endpoint",
  "word|egress": "egress",
  "word|panel source": "источник к панели",
  "word|mesh source": "источник к узлам",
  "What was armed": "Что подготовлено",
  "The command below carries a token that authenticates the node to this panel — copy the command now. You can rotate the token later if it leaks.": "Команда ниже содержит токен, которым узел подтверждает себя этой панели — скопируйте команду сейчас. Токен потом можно сменить, если он утечёт.",
  "Either works: the first is what this node runs today, and the panel follows whichever the new box reports.": "Подойдёт любая: первая — то, на чём узел работает сегодня. Но панель следует той модели, о которой сообщит новая машина.",
  "Reclaim": "Вернуть",
  "Reclaim {v1}": "Вернуть {v1}",
  "Subnet": "Подсеть",
  "Users in its store": "Юзеров в хранилище",
  "This server has no users yet.": "Пользователей пока нет.",
  "They are imported as peers, so reclaiming does not disconnect them.": "Они импортируются как пиры, поэтому возврат их не отключает.",
  "Must be free across the fleet. Both kinds hand out client addresses at runtime, so changing it does not invalidate anyone's credentials.": "Должна быть свободна во всём флоте. Оба вида выдают адреса клиентам во время работы, поэтому её смена не делает недействительными ничьи учётные данные.",
  "The node still runs this server, but this panel holds no record of it — so nothing starts it and nothing manages its users. Reclaiming writes the record back from what the node reports.": "Узел всё ещё держит этот сервер, но в панели нет записи о нём — поэтому его никто не запускает и его пользователями никто не управляет. Возврат восстановит запись из того, что сообщает узел.",
  "This panel holds no record of this {v1} server, though the node still has it — so nothing starts it, its users aren't in the roster, and a rebuild can't bring it back. Open it and Reclaim it to take it back, users and all.": "В панели нет записи об этом сервере {v1}, хотя узел его держит — поэтому его никто не запускает, его пользователей нет в ростере, а пересборка его не вернёт. Откройте его и нажмите «Вернуть», чтобы забрать его вместе с пользователями.",
  "Reclaiming…": "Возврат…",
  "Reclaimed {v1}": "{v1} возвращён",
  "Reclaimed {v1} — {v2} user(s) kept": "{v1} возвращён, юзеров: {v2}",
  "Couldn't reclaim {v1}": "Не удалось вернуть {v1}",
  "Take this server back under the panel, keeping the users in its store": "Вернуть этот сервер под управление панели, сохранив пользователей из его хранилища",
  "Mesh egress IP": "IP для mesh",
  "— source to dial other nodes": "— источник для других узлов",
  "Which of this node's addresses it dials the other nodes' mesh links from. A single connection can still override it on its own card.": "С какого из адресов этого узла он подключается к mesh-связям других узлов. Отдельное соединение может переопределить это на своей карточке.",
  "mesh egress IP → {v1}": "IP для mesh → {v1}",
  "Source IP this node uses to reach the panel. Ignored on same-server installs; falls back to auto if it can't connect.":
    "Адрес источника, с которого нода обращается к панели. На установках на одном сервере игнорируется; при неудаче — авто.",
  "Mesh settings (ingress address, subnet, port, prefix, AWG) for this node are configured in {where} — select this node there.":
    "Настройки меша (адрес входа, подсеть, порт, префикс, AWG) для этой ноды задаются в {where} — выберите там эту ноду.",
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
  "Set in the node's configuration, then rebuild":
    "Задайте в конфигурации ноды и пересоберите",
  "Removing the module stops swg-noded / swg-agent but does not tell the panel — Force remove clears it here.":
    "Удаление модуля остановит swg-noded / swg-agent, но не сообщит панели — «Принудительно удалить» очистит запись здесь.",
  "This node is managed declaratively. Remove it from the configuration that declares it and rebuild — it won't sign off on its own, so Force-remove it here afterwards. It keeps serving its {v1} until then.":
    "Эта нода управляется декларативно. Удалите её из конфигурации, которая её объявляет, и пересоберите — сама она не отметится об уходе, поэтому потом удалите её здесь через «Принудительно удалить». До этого она продолжает обслуживать свои {v1}.",
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
  "Expected a VK call link like {v1}": "Ожидается ссылка на звонок VK вида {v1}",
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
  "Using the panel's fallback VK call link — this user has none of their own. Their subscription page hands out a link without it, so set a VK link on the user before sending them there.":
    "Используется запасная VK-ссылка панели — своей у этого пользователя нет. На его странице подписки ссылка будет выдана без неё, поэтому задайте пользователю VK-ссылку, прежде чем отправлять его туда.",
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
  "Primary connection — click to mark it a backup":
    "Главное подключение — нажмите, чтобы сделать резервным",
  "Backup connection — click to clear the label":
    "Резервное подключение — нажмите, чтобы снять метку",
  "Unmarked — click to make it the primary connection":
    "Без метки — нажмите, чтобы сделать главным",
  "label|Unmarked": "Без метки",
  "Primary": "Главный",
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
  "Traffic by exit": "Трафик по exit'ам",
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
  "Reissue certificate": "Перевыпустить сертификат",
  "Issuing the subscription certificate…": "Выпускаем сертификат подписки…",
  "The subscription service is installed — what is missing is its certificate, which only a reissue can create. “Run update” cannot fix this one.":
    "Служба подписок установлена — не хватает её сертификата, а его создаёт только перевыпуск. «Запустить обновление» здесь не поможет.",
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
  "Create a user, then add devices for them — or create a peer on the Peers screen and assign it later.":
    "Создайте пользователя и добавьте ему устройства — или создайте пир на экране «Пиры» и назначьте его позже.",
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
  "The panel is accessible at {v1}": "Панель доступна по адресу {v1}",
  "The panel will be accessible at {v1}": "Панель будет доступна по адресу {v1}",
  "The panel didn't answer. It may be restarting, or this tab may be on an address that no longer serves it — reload the page to see where things stand.": "Панель не ответила. Возможно, она перезапускается, либо эта вкладка открыта по адресу, который её больше не отдаёт — перезагрузите страницу, чтобы увидеть текущее состояние.",
  "*The panel is served on `127.0.0.1:{v1}` on the server*, which nothing outside that machine can open. It is plain HTTP on purpose: the traffic never crosses a network, and a certificate issued for your panel's domain would only mis-name itself on a loopback address.": "*Панель отдаётся на `127.0.0.1:{v1}` на самом сервере*, и открыть этот адрес снаружи машины невозможно. Это намеренно обычный HTTP: трафик не выходит в сеть, а сертификат, выписанный на домен панели, на loopback-адресе только назвался бы чужим именем.",
  "This host's Access screen is read-only, so the option *is* the switch — there is nothing to turn on here. Give the panel a console port in your configuration and rebuild; the console moves there, and this section then shows the tunnel command for it.": "Экран доступа на этом хосте только для чтения, поэтому сам параметр *и есть* переключатель — включать здесь нечего. Задайте панели порт консоли в своей конфигурации и пересоберите; консоль переедет туда, а этот раздел покажет команду для туннеля.",
  "the private-access option": "параметр приватного доступа",
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
  "*Automatic renewal is failing.* The certificate is still valid for *{v1}* more day(s), but nothing is renewing it — check that this host is reachable by the validation method above.":
    "*Автоматическое обновление не проходит.* Сертификат ещё действует *{v1}* дн., но обновлять его некому — проверьте, что этот хост доступен для выбранного выше способа проверки.",
  "*This certificate expires in {v1} day(s).*":
    "*Этот сертификат истекает через {v1} дн.*",
  "*Nothing on this server renews this certificate.* acme.sh holds no certificate for this address, so it will expire in *{v1}* day(s) unless it is issued again.":
    "*Этот сертификат на сервере никто не обновляет.* У acme.sh нет сертификата для этого адреса, поэтому он истечёт через *{v1}* дн., если его не выпустить заново.",
  "*This certificate has expired.* Browsers refuse the panel and nodes that verify it stop syncing until it is renewed.":
    "*Срок действия этого сертификата истёк.* Браузеры не открывают панель, а ноды, которые его проверяют, не синхронизируются, пока его не обновят.",
  "Couldn't start the renewal.": "Не удалось запустить обновление.",
  "Renew the certificate now?": "Обновить сертификат сейчас?",
  "Renew now": "Обновить сейчас",
  "Renewing…": "Обновляется…",
  "acme.sh renews this certificate for another program on this server as well ({v1}) and runs that program's reload command, which may restart it — exactly as its own scheduled renewals do.":
    "acme.sh обновляет этот сертификат и для другой программы на этом сервере ({v1}) и выполняет её команду перезагрузки, которая может её перезапустить, — точно так же, как при обычных плановых обновлениях.",
  "*Renewed.* The panel now serves a certificate valid until {v1}.":
    "*Обновлено.* Панель теперь отдаёт сертификат, действующий до {v1}.",
  "*Not renewed — acme.sh says it is not due yet* (next renewal: {v1}). The certificate is valid until {v2}.":
    "*Не обновлено — acme.sh считает, что ещё рано* (следующее обновление: {v1}). Сертификат действует до {v2}.",
  "The renewal failed.": "Обновить не удалось.",
  "acme.sh holds no certificate for this address, so there is nothing to renew.":
    "У acme.sh нет сертификата для этого адреса, обновлять нечего.",
  "acme.sh said:": "acme.sh ответил:",
  "Details:": "Подробности:",
  "Nothing was renewed.": "Ничего не обновлено.",
  "*acme.sh holds a certificate from a public CA for this address, but the panel still serves its self-signed one — and acme.sh will install its next renewal over it ({v1}).* Nodes that pinned the self-signed certificate stop syncing at that moment. Switch now with *Save*, then re-run the node installer on the nodes that pinned it.":
    "*У acme.sh есть сертификат публичного CA для этого адреса, но панель всё ещё отдаёт самоподписанный — и acme.sh установит поверх него своё следующее обновление ({v1}).* Ноды, закрепившие самоподписанный сертификат, в этот момент перестанут синхронизироваться. Замените его сейчас кнопкой *Сохранить*, затем перезапустите установщик ноды на нодах, которые его закрепили.",
  "*acme.sh holds a certificate from a public CA for this address, but the panel still serves its self-signed one.* It is not swapped automatically: nodes that pinned the self-signed certificate would stop syncing. Switch it here with *Save*, then re-run the node installer on the nodes that pinned it.":
    "*У acme.sh есть сертификат публичного CA для этого адреса, но панель всё ещё отдаёт самоподписанный.* Автоматически он не заменяется: ноды, закрепившие самоподписанный сертификат, перестали бы синхронизироваться. Замените его здесь кнопкой *Сохранить*, затем перезапустите установщик ноды на нодах, которые его закрепили.",
  "a certificate renewal is running — try again when it has finished (a minute or two)":
    "идёт обновление сертификата — повторите, когда оно закончится (минута-другая)",
  "acme.sh renewed the certificate, but the panel did not install it.": "acme.sh обновил сертификат, но панель его не установила.",
  "a renewal is already running": "обновление уже идёт",
  "an address change is waiting to be confirmed — confirm or cancel it first, then renew":
    "смена адреса ждёт подтверждения — сначала подтвердите или отмените её, затем обновляйте",
  "This panel runs in a container, which renews its certificate itself every 12 hours — restart the container to renew now.":
    "Панель работает в контейнере, который сам обновляет сертификат каждые 12 часов — чтобы обновить сейчас, перезапустите контейнер.",

  "*This certificate should already have been renewed.* It has *{v1}* hour(s) left.":
    "*Этот сертификат уже должен был обновиться.* До его истечения осталось *{v1}* ч.",
  "*Another program on this server renews this certificate* — acme.sh installs each renewal to `{v1}`. The panel takes the renewed certificate from acme.sh within 6 hours, so both keep working.":
    "*Этот сертификат обновляет другая программа на сервере* — acme.sh кладёт каждое обновление в `{v1}`. Панель забирает обновлённый сертификат из acme.sh в течение 6 часов, так что работают обе.",
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
  "Untitled list": "Список без имени",
  "src|Custom": "Свой",
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
  "Ingress address": "Адрес входа",
  "— what peers and clients dial to reach this node": "— по нему к этой ноде подключаются и пиры, и клиенты",
  "Hostname or IP — e.g. node.example.com": "Имя хоста или IP — например node.example.com",
  "(auto)": "(авто)",
  "Obfuscation for the mesh links that terminate on *{v1}* — any node connecting to it adopts these and reconnects on Save. Blank = auto (a fresh set per link).":
    "Маскировка для связей сети, которые приходят на *{v1}* — каждый подключающийся нода примет её и переподключится при сохранении. Пусто — авто (свой набор на связь).",
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
  "Rebuild this link under a new interface name — for a name, address or port that clashes with something else on that server": "Пересобрать этот линк под новым именем интерфейса — если имя, адрес или порт конфликтуют с чем-то ещё на этом сервере",
  "Kernel": "Ядро",
  "Architecture": "Архитектура",
  "Rebuild links": "Пересобрать линки",
  "Re-provision now": "Пересобрать сейчас",
  "Rebuilds this node's links under new interface names, with the settings above. Use it when a link won't come up — a name, address or port clashing with something else on that server. It cannot help two nodes that share one machine: their link is a single interface name that would have to exist twice there.": "Пересобирает линки этого узла под новыми именами интерфейсов, с настройками выше. Пригодится, когда линк не поднимается: имя, адрес или порт конфликтуют с чем-то ещё на этом сервере. Двум узлам на одной машине это не поможет — их линк это одно имя интерфейса, которое должно было бы существовать там дважды.",
  "Rebuilding this node's mesh links…": "Пересобираем линки этого узла…",
  "Couldn't re-provision the mesh links.": "Не удалось пересобрать линки.",
  "Set a public base URL in {v1} to build the link.": "Задайте публичный адрес в {v1}, чтобы собрать ссылку.",
  "Which {v1} proxy": "Какой прокси {v1}",
  "Not available with {v1}": "Не работает с {v1}",
  // budget-ok: empty-state prose in its own block — it wraps, nothing beside it to overlap
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
  "{v1} — outbound addresses": "{v1} — исходящие адреса",
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
  "{v1} has no settings the panel can preset — its options are set in the app itself.":
    "У {v1} нет настроек, которые может задать панель — они настраиваются в самом приложении.",
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
  "Couldn't reach the panel just now, so this peer's stored config could not be read. It has not been lost — try again in a moment.":
    "Сейчас не удалось связаться с панелью, поэтому сохранённый конфиг этого пира прочитать не вышло. Он не потерян — попробуйте ещё раз через минуту.",
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
  // §6.7: the kernel scanner stops once a category's budget is full. The subject is «часть», singular, so
  // this reads correctly whether {v1} is one category or a list of them — and the tail's «не сопоставляется»
  // is the singular a quantifier phrase takes, right for «1 запись», «144 записи» and «256 записей» alike.
  // No budget number: see the comment at the call site — it stopped being one number.
  "{v1} matched only in part here — {v2} not matched":
    "{v1} — здесь сопоставляется лишь часть записей, {v2} не сопоставляется",
  // Hybrid SNI's own truncation (`sni_cap`). SEPARATE keys from the sibling above and not shared ones: that
  // sentence bakes «записей» into the Russian, and nothing was dropped here but text patterns. «сверх лимита
  // ноды» — the node's limit, not the interface's, because the node bounds its whole scan at once and this
  // count can be larger than anything one interface shows.
  //
  // The list goes LAST in both languages on purpose. Putting it in the middle forced the tail to agree with
  // whichever pattern happened to be last («не сопоставляется» vs «не сопоставляются»); after a colon it is
  // an enumeration and the verb agrees with nothing. {v1} is always a quantifier phrase («200 текстовых
  // шаблонов»), so «сверх лимита ноды» reads for 1, 2 and 200 alike.
  // «лимита ноды в {v2}» — «лимит в N» is the idiomatic Russian for "a limit of N", and it takes the bare
  // numeral, so {v2} needs no noun of its own and no agreement with {v1}'s «шаблонов».
  "{v1} past this node's limit of {v2} — no longer matched: {v3}":
    "{v1} сверх лимита ноды в {v2} — больше не сопоставляются: {v3}",
  // The same fact from a node too old to send the sample: the count is all there is, so it is all that is said.
  "{v1} past this node's limit of {v2}":
    "{v1} сверх лимита ноды в {v2}",
  // §12.1's per-interface cap, said when a badge is refused. «по тексту» keeps the distinction the count
  // rests on: a zone is a pattern too and is not counted — only the three kinds matched as text are.
  "{v1} is all one interface can match by text — remove one to add another, or use a list instead.":
    "{v1} — это всё, что один интерфейс может сопоставлять по тексту: удалите один, чтобы добавить другой, или используйте список.",
  // The other way an entry never becomes a rule: xt_string refuses a pattern over 128 bytes outright.
  // A VERB, not a short adjective, and for the same reason the sibling key above takes one: a quantifier
  // phrase governs a singular verb in Russian, so «не помещается» is right for «1 запись», «3 записи» and
  // «5 записей» alike — while «слишком длинны» agreed with none of them.
  "{v1} too long for this scanner to match — over {v2} characters":
    "{v1} не помещается в этот сканер — больше {v2} символов",
  "kernel SNI scanner unavailable — running userspace SNI parser":
    "ядерный сканер SNI недоступен — работает разбор SNI в пользовательском режиме",
  // Was a bare literal beside two translated sentences, so the Russian health line read
  // «Сканер SNI healthy». The i18n audit cannot see a string that never reached T().
  "healthy": "работает",
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
  "Drop DoH / DoT / DoQ so DNS can't slip past the tunnel's filtering. A client whose only resolver is encrypted stops resolving.":
    "Резать DoH, DoT и DoQ, чтобы DNS не проскакивал мимо фильтрации туннеля. Клиент, у которого есть только шифрованный резолвер, перестанет разрешать имена.",
  "Block WebRTC / STUN — prevents the client's real IP leaking around the tunnel.":
    "Закрыть WebRTC и STUN — настоящий адрес клиента не утечёт мимо туннеля.",
  "Matched by IP address — works in every mode.": "По IP-адресу — работает в любом режиме.",
  "Matched by domain name.": "По имени домена.",
  "No lists match.": "Списков не нашлось.",
  "Every available list is already added.": "Все доступные списки уже добавлены.",
  "Couldn't switch mode": "Не удалось сменить режим",
  "→ not found": "→ не найдено",
  "Auto (target node default)": "Авто (как на ноде назначения)",
  "Source IP on the target node that clients egress from.":
    "Адрес на ноде назначения, с которого клиенты выходят.",
  "Source IP clients egress from.": "Адрес, с которого клиенты выходят.",
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
  // Last-resort text in an update row when the server answered !ok with nothing to quote.
  // Stands alone in a narrow cell, so it stays a bare verb rather than a sentence.
  "failed": "не удалось",
  "Couldn't check for updates.": "Не удалось проверить обновления.",
  "No notes for this release.": "Описания у этого выпуска нет.",
  "See the changelog for what's new.": "Что нового — в списке изменений.",
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
  "Days are counted in {v1}": "Сутки считаются по поясу {v1}",
  "Days are counted in this server's zone": "Сутки считаются по поясу этого сервера",
  "System mesh defaults": "Умолчания системной сети",
  "mesh AWG params": "параметры AWG сети",
  "Geo lists will refresh on each node's next sync.": "Гео-списки обновятся при следующей синхронизации нод.",
  "Couldn't save the list.": "Не удалось сохранить список.",
  "Content filters": "Фильтры содержимого",
  "Routing lists": "Списки маршрутизации",
  "Filtering runs on the entry node — where a client's tunnel lands. Exit and relay hops in a multi-hop path never see the client, so there's nothing there for them to filter.":
    "Фильтрация работает на входной ноде — там, где заканчивается туннель клиента. Выходные и промежуточные узлы клиента не видят, фильтровать им нечего.",
  "Routing runs on the entry node — where a client's tunnel lands. Exit and relay hops in a multi-hop path just forward what's already been steered.":
    "Маршрутизация работает на входной ноде — там, где заканчивается туннель клиента. Выходные и промежуточные узлы лишь передают то, что уже направлено.",
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
  // Curated has no switch (§6.5): it stands in the slot where a fetched provider says «обновлён 3 ч назад».
  "always on": "всегда включены",
  "The panel maintains and resolves these itself — there is no provider to enable, and nothing to turn off":
    "Панель ведёт и собирает их сама — включать нечего и выключать нечего.",
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
  "generating key…": "создаём ключ…",
  // an all-keyless peer mints no keypair — its credential is the panel-owned access password
  "creating peer…": "создаём пира…",
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
  "Custom IP — e.g. 203.0.113.5": "Свой адрес — например, 203.0.113.5",
  "e.g. 203.0.113.5": "например, 203.0.113.5",
  "Device name": "Имя устройства",
  "e.g. tun0": "например, tun0",
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
  "AmneziaWG datapath": "Путь данных AmneziaWG",
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
  "Service keeps crashing on the node": "Служба на ноде постоянно падает",
  "Clients can reach it, but every session through it is cut each time it dies. Its journal on the node says why.":
    "Клиенты до него достучатся, но каждое падение обрывает все сессии через него. Почему он падает — видно в его журнале на ноде.",
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
  "tag|re-provisioning": "пересборка",
  "tag|flagged for removal": "помечен к удалению",
  "tag|restarted": "перезапущен",
  // MEASURED in the real turn card (286px wide, its drag grip and TURN badge beside it): «падает по кругу» ran 125px
  // against the English 113px and cut even a fork's default title (WINGS-N → WING…); «падает» is 70px and leaves it
  // whole. The loop itself is spelled out where there is room — the tag's popup and the node's issue line.
  "tag|crash-looping": "падает",
  "tag|pending": "ожидает",
  "tag|unsaved": "не сохр.",
  "tag|orphan": "сирота",
  "hdr|Encrypted DNS": "Шифрованный DNS",
  "The Encryption Vault is locked, so this peer's stored config can't be read. Unlock it to show the QR — the config has not been lost.": "Хранилище ключей заблокировано, поэтому сохранённый конфиг этого пира не прочитать. Разблокируйте его, чтобы показать QR — конфиг не потерян.",
  "This config was encrypted with a previous encryption key and can no longer be opened. Re-issue this peer to give it a fresh config and QR.": "Этот конфиг зашифрован предыдущим ключом шифрования и больше не открывается. Перевыпустите пир, чтобы получить новый конфиг и QR.",
  "its encryption bucket was sealed with a previous encryption key": "его хранилище запечатано предыдущим ключом шифрования",
  "This client resolves names over encrypted DNS, which the node can't see, so its hostname rules don't match and those sites leave by this node — rules by IP still route. Switch the client to plain DNS, move this node to an SNI mode, or turn on the interface's DoH / DoT / DoQ block.":
    "Этот клиент разрешает имена через шифрованный DNS, которого нода не видит, поэтому его правила по имени хоста не срабатывают и эти сайты уходят через эту ноду — правила по IP при этом работают. Переключите клиента на обычный DNS, переведите ноду в режим SNI или включите на интерфейсе блокировку DoH / DoT / DoQ.",
  "tag|unassigned": "свободен",
  "val|total": "всего",
  "val|online": "в сети",
  "tag|direct": "напрямую",
  "tag|cascade": "каскад",
  "tag|smart": "умный",
  "tag|custom": "свой",
  "tag|heavy": "тяжёлый",
  "tag|restricted": "фильтр",
  "tag|untitled": "без имени",
  // Panel-service issue: the session-signing key could not be persisted.
  "Session key": "Ключ сессий",
  "can’t be saved": "не сохраняется",
  "the panel can't save the key it signs sign-ins with ({v1}), so everyone is signed out whenever it restarts — its state directory is owned by another user":
    "панель не может сохранить ключ, которым подписывает входы ({v1}), поэтому при каждом её перезапуске всех выкидывает из панели — каталогом её состояния владеет другой пользователь",
  "val|auto": "авто",
  // Peers toolbar: collapse each peer's deployments into one row. Own keys — the bare words are
  // used elsewhere as nouns; these are the switch's two states.
  "btn|Group": "Объединить",
  "btn|Grouped": "Объединено",
  // the grouped row's IF badge: the row stands for several deployments, so it counts them
  "{n} interfaces": "{n} интерф.",
  "This peer's interfaces": "Интерфейсы этого пира",
  "Collapse each peer's deployments into one row": "Свернуть развёртывания каждого пира в одну строку",
  "One row per peer — its other deployments are behind the +N": "По строке на пира — остальные его развёртывания за +N",
  // the address column on a self-contained turn row: its server mints the client IP on connect
  "val|auto IP": "авто IP",
  "tag|unbound": "не привязан",
  // ── strings that sat bare BESIDE a translated one (see .campaign/i18n-bare.mjs) ──
  // Every entry here was English in a Russian panel: a ternary's other branch, a label table's odd row,
  // a status line, a fallback after `||`. The old audit could not see them — it proves each T() HAS a
  // translation, never that a visible string IS a T().

  // the node rail: the name is a SLOT, because "Hide msk-1" and "Скрыть msk-1" are not the same shape
  "Hide {v1}": "Скрыть {v1}",
  "Show {v1}": "Показать {v1}",
  "Go to {v1}": "Перейти к {v1}",
  // budget-ok: title, no layout
  "Down — {v1}": "Не в сети — {v1}",
  "not reporting": "не отвечает",

  // interface create/edit
  "Letters, digits, _ and -, up to 15 characters.": "Буквы, цифры, _ и -, до 15 символов.",
  "Name: 1–40 chars, letters/digits/-/_ only.": "Имя: 1–40 символов, только буквы/цифры/-/_.",
  "1–40 chars: letters, digits, - or _ only.": "1–40 символов: только буквы, цифры, - или _.",
  "Blank = 1280.": "Пусто = 1280.",
  "val|down": "не работает",          // a datapath, after "wireguard-go · "
  "val|disabled": "отключён",         // a webhook, after its event list

  // the working states — lowercase, they follow nothing and start no sentence
  "requesting…": "запрашиваю…",
  "creating…": "создаю…",
  "applying…": "применяю…",
  "Encrypting…": "Шифрую…",
  "Starting…": "Запускаю…",

  // failures that fall back when the server said nothing
  "Failed.": "Не удалось.",
  "Couldn't retry": "Повтор не удался",
  "couldn't generate": "не удалось создать",
  "Saved.": "Сохранено.",
  // budget-ok: settings status line, a block that wraps
  "Saved & applied.": "Сохранено и применено.",

  // a peer with no name, and a peer with no user
  "(peer)": "(пир)",
  "(unnamed)": "(без имени)",
  "val|Unassigned": "Без владельца",   // NOT status|Unassigned («Свободен»), which is width-capped for the peer grid

  // routing categories: the four Russia sets are sentences, so they translate; the brand rows do not
  "Russia — Government": "Россия — госсайты",
  "Russia — Banks": "Россия — банки",
  "Russia — Blocked (all)": "Россия — блокировки (всё)",
  "Russia — Blocked (media)": "Россия — блокировки (медиа)",
  "Facebook, Instagram & WhatsApp": "Facebook, Instagram и WhatsApp",
  "Disney+ streaming": "Стриминг Disney+",
  "VKontakte": "ВКонтакте",
  "Grok (xAI) — grok.com & x.ai": "Grok (xAI) — grok.com и x.ai",
  "val|Auto": "Авто",                  // the egress-IP picker's "no explicit IP" option

  // the protection tiles and their popover header
  "Blocked": "Блокировки",
  "Filtering": "Фильтрация",

  // the settings footer's list of what a Save will apply
  "Interfaces — colours / defaults": "Интерфейсы — цвета / умолчания",
  "Subscriptions — enable / languages": "Подписки — включение / языки",

  // turn-proxy: the verb is a NOUN in the slot — «Запрошено: переустановка turn-прокси»
  "val|update": "обновление",
  "val|reinstall": "переустановка",

  // the encrypt-configs report. ⚠️ These two were chosen by a ternary INSIDE the Trich call, so no tool
  // ever saw them as keys — they were missing from this catalog entirely and rendered English forever.
  // budget-ok: prose in a hint block, wraps
  "*{v1}* couldn't be encrypted (unassigned, or no stored key) — *rekey* or assign it to include: {v2}.":
    "*{v1}* не удалось зашифровать (без владельца или без сохранённого ключа) — *смените ключи* или назначьте владельца, чтобы включить: {v2}.",
  // budget-ok: prose in a hint block, wraps
  "*{v1}* couldn't be encrypted (unassigned, or no stored key) — *rekey* or assign them to include: {v2}.":
    "*{v1}* не удалось зашифровать (без владельца или без сохранённого ключа) — *смените ключи* или назначьте владельцев, чтобы включить: {v2}.",

  // ── csqtt (amurcanov's Rust rewrite of WDTT — self-contained raw-TUN VK-turn server) ──
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
  "A fresh access password is generated. The current csqtt link stops working — send the user their new link (from the subscription page) to re-import.":
    "Будет выпущен новый пароль доступа. Текущая ссылка csqtt перестанет работать — отправьте пользователю новую (со страницы подписки), чтобы он переимпортировал.",
  "csqtt assigns the address on connect": "Адрес назначает csqtt при подключении",
  "csqtt fields aren't ready yet.": "Поля csqtt ещё не готовы.",
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
  "The running server is stopped and ours starts in its place, on the same port — clients reconnect within seconds.":
    "Работающий сервер будет остановлен, а наш поднимется на его месте, на том же порту — клиенты переподключатся за секунды.",
  "The node *can't read this server's password store* at {v1}, so its users cannot come across. Adopting stops it and starts ours in its place with *no users at all* — everyone it is serving right now is dropped, and you have nothing to re-issue their access from.":
    "Нода *не может прочитать хранилище паролей этого сервера* в {v1}, поэтому его пользователи не перейдут. При приёме он будет остановлен, а наш поднимется на его месте *вообще без пользователей* — все, кого он сейчас обслуживает, отвалятся, и восстановить их доступ будет не из чего.",
  "This usually means the server runs inside a container of its own, where the node can't reach its files. To keep its users, stop it and re-create the server from the panel instead.":
    "Обычно это значит, что сервер работает в собственном контейнере, куда нода не достаёт до его файлов. Чтобы сохранить пользователей, остановите его и создайте сервер заново из панели.",
  "Adopt without its users": "Принять без пользователей",
  "I understand its current users will be lost": "Я понимаю, что его текущие пользователи будут потеряны",
  "couldn't be read": "не удалось прочитать",
  "the node can't read this server's password store at {v1}, so adopting would stop it and take over with NO users — its clients would all be dropped. Confirm to adopt anyway.":
    "нода не может прочитать хранилище паролей этого сервера в {v1}: при приёме он будет остановлен, а мы заберём его БЕЗ пользователей — все его клиенты отвалятся. Подтвердите, чтобы принять всё равно.",
  "A csqtt server is adopted from its card on the node page — the node finds it and offers it there.":
    "Сервер csqtt принимается со своей карточки на странице ноды — нода находит его и предлагает там.",
  "RAW needs port {v1} and {v2} is using it on this node — move that first":
    "RAW нужен порт {v1}, а его занимает {v2} на этой ноде — сначала перенесите его",
  "this server would need port {v1} for RAW, but it is already using it — move its listen or internal WG port first":
    "Этому серверу нужен порт {v1} для RAW, но он сам его занимает — сначала перенесите его порт приёма или внутренний порт WG",
  "{v1} has no RAW-IP mode — only some WDTT forks implement it": "У {v1} нет режима RAW-IP — его реализуют не все форки WDTT",
  "no csqtt instance '{v1}' on node {v2}": "на ноде {v2} нет экземпляра csqtt «{v1}»",
  "this node already manages a csqtt instance on {v1}": "эта нода уже управляет экземпляром csqtt на {v1}",
  "this node doesn't report a csqtt server on {v1} — refresh and try again":
    "эта нода не сообщает о сервере csqtt на {v1} — обновите и попробуйте снова",
  "a csqtt server this panel doesn't manage already holds {v1} on this node — adopt it from the node's page to take it over with its users, or pick another name":
    "сервер csqtt, которым эта панель не управляет, уже занимает {v1} на этой ноде — примите его со страницы ноды, чтобы забрать вместе с пользователями, или выберите другое имя",
  "this server's tunnel subnet isn't an IPv4 /24: {v1}": "подсеть туннеля этого сервера не IPv4 /24: {v1}",
  "unknown csqtt fork: {v1}": "неизвестный форк csqtt: {v1}",
  "this node has no endpoint address yet, so clients would have nothing to dial — set the node's endpoint host, or pass one with the adopt":
    "у этой ноды ещё нет адреса подключения, клиентам будет некуда стучаться — задайте адрес ноды или передайте его при приёме",
  "· {v1} connected": "· подключено {v1}",
  "Adopting brings its *{count}* across — open the install from its card to see them.":
    "При приёме переносятся и его пользователи — это *{count}*; откройте установку с её карточки, чтобы их увидеть.",
  "Adopting brings its *{count}* across — each becomes an unassigned peer you can hand to a user.":
    "При приёме переносятся и его пользователи — это *{count}*; каждый станет непривязанным пиром, которого можно выдать пользователю.",
  "Turn-proxy": "Turn-прокси",
  "RAW mode on": "RAW включён",
  "Extra flags": "Дополнительные флаги",
  // Force-DNS resolver's upstream (docs/DNS-SETTINGS-PLAN.md §4)
  "Upstream DNS": "Вышестоящий DNS",
  "upstream DNS → {v1}": "вышестоящий DNS → {v1}",
  "Where this node's resolver sends the lookups it answers for Force-DNS clients. Empty = 1.1.1.1, 8.8.8.8. Up to four addresses, each optionally with #port (a local resolver like 127.0.0.1#5335 works). If none of them answers, clients on this node can't resolve names.": "Куда резолвер этой ноды отправляет запросы, на которые он отвечает клиентам Force-DNS. Пусто = 1.1.1.1, 8.8.8.8. До четырёх адресов, у каждого можно указать #порт (подойдёт и локальный резолвер, например 127.0.0.1#5335). Если ни один не отвечает, клиенты этой ноды не смогут разрешать имена.",
  "In effect on this node: {v1}": "Сейчас на ноде: {v1}",
  "Not on the node yet — it still asks {v1}. It applies on the next sync; a node too old to know this setting keeps the default until it updates.": "На ноде ещё не применено — она пока спрашивает {v1}. Применится при следующей синхронизации; нода, которая слишком стара для этой настройки, оставит значение по умолчанию до обновления.",
  "Upstream DNS takes at most four addresses.": "Вышестоящий DNS — не больше четырёх адресов.",
  "Upstream DNS: {v1} is not an IP address (optionally with #port).": "Вышестоящий DNS: {v1} — не IP-адрес (можно с #портом).",
  "Upstream DNS: {v1} can't answer DNS queries.": "Вышестоящий DNS: {v1} не может отвечать на DNS-запросы.",
  "Upstream DNS: {v1} is the node's own Force-DNS resolver — it would ask itself.": "Вышестоящий DNS: {v1} — это сам резолвер Force-DNS этой ноды, он спрашивал бы сам себя.",
  // client DNS of a WDTT / csqtt server (docs/DNS-SETTINGS-PLAN.md §3)
  "Client DNS": "DNS для клиентов",
  "Client DNS takes at most two addresses.": "DNS для клиентов — не больше двух адресов.",
  "Client DNS must be IPv4 addresses — {v1} is not one a phone can use.": "DNS для клиентов — только IPv4-адреса: {v1} телефон использовать не сможет.",
  "This fork's build can't set client DNS yet — its clients get {v1}.": "Сборка этого форка пока не умеет задавать DNS — клиенты получают {v1}.",
  "Saved now, applied once this node updates.": "Сохранится сейчас, применится после обновления ноды.",
  "Saved — not on the server yet. The node applies it on its next sync.": "Сохранено, но на сервере пока нет — нода применит при следующей синхронизации.",
  "This node runs Force-DNS: if this server's routing matches by domain, the node's own resolver answers its clients' plain DNS instead.": "На этой ноде Force-DNS: если маршрутизация этого сервера сопоставляет по доменам, обычные DNS-запросы его клиентов вместо этого обслуживает резолвер самой ноды.",
  "Extra flags set their own DNS, and that one wins over this field.": "В дополнительных флагах задан свой DNS — он важнее этого поля.",
  "Given to every client when it connects. Empty = not set by the panel; this fork's default is {v1}. Saving restarts the server.": "Передаётся каждому клиенту при подключении. Пусто = панель не задаёт; по умолчанию у этого форка {v1}. Сохранение перезапускает сервер.",
  "Given to every client when it connects. Empty = not set by the panel; this server gives {v1}. Saving restarts the server.": "Передаётся каждому клиенту при подключении. Пусто = панель не задаёт; сейчас этот сервер выдаёт {v1}. Сохранение перезапускает сервер.",
  "Given to every client when it connects. Saving restarts the server.": "Передаётся каждому клиенту при подключении. Сохранение перезапускает сервер.",
  "val|none": "нет",
  "tag|advanced": "подробно",
  // ── RAW-IP mode (qWDTT): a second listener that trades WireGuard for throughput ──────────────
  "RAW-IP mode": "Режим RAW-IP",
  "Accept RAW connections": "Принимать RAW-подключения",
  "RAW drops WireGuard's handshake: *no forward secrecy and no replay protection*. Anyone who later learns a peer's password can read traffic they recorded earlier. Turn it on for people who need the speed and accept that.": "RAW убирает рукопожатие WireGuard: *нет forward secrecy и защиты от повтора*. Тот, кто потом узнает пароль пира, прочитает записанный ранее трафик. Включайте для тех, кому нужна скорость и кого это устраивает.",
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
  "A second, WireGuard-free listener that is roughly *6x* faster through the same VK relay. The server keeps its normal WireGuard listener either way, so each user picks per device — but RAW has *no forward secrecy and no replay protection*. This only sets what a NEWLY created server starts with; every server can be switched afterwards.": "Второй слушатель без WireGuard: примерно в *6 раз* быстрее через то же VK-реле. Обычный WireGuard-слушатель остаётся в любом случае, так что пользователь выбирает режим на каждом устройстве — но у RAW *нет forward secrecy и защиты от повтора*. Настройка задаёт только состояние НОВОГО сервера; на каждом сервере режим потом переключается.",
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
  "DELETE {v1}": "УДАЛИТЬ {v1}",
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
  "CSQTT client apps · {v1}": "Клиенты CSQTT · {v1}",
  "Geolocation: {v1}": "Геолокация: {v1}",
  "TLD .{v1}": "Домен .{v1}",
  "Reset routing · {v1}": "Сброс маршрутов · {v1}",
  "{v1} routed": "{v1} направлено",
  "{v1} rerouted": "{v1} перенаправл.",
  "IP learning is {v1} · click to turn it {v2}": "Запоминание адресов: {v1} · нажмите, чтобы {v2}",
  "val|off": "выкл",
  "val|on": "вкл",
  "resolving…": "определяем…",
  "→ {v1}": "→ {v1}",
  "Cascade — exits via {v1}": "Каскад — выход через {v1}",
  "Linking to {v1} — this interface's traffic resumes once the link is up": "Связываемся с {v1} — трафик этого интерфейса пойдёт, как только поднимется линк",
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
  "ingress address → {v1}": "адрес входа → {v1}",
  "mesh subnet → {v1}": "подсеть сети → {v1}",
  "mesh port → {v1}": "порт сети → {v1}",
  "prefix → {v1}": "префикс → {v1}",
  "egress IP → {v1}": "адрес выхода → {v1}",
  "panel IP → {v1}": "адрес панели → {v1}",
  "val|default": "по умолчанию",
  // A bare participle, so it agrees with nothing and reads the same in a row tag and in the fleet popover.
  "in use": "используется",
  // Impersonal «используется» agrees with the LIST, not the count, so it works for any number of nodes.
  "in use on {v1}": "используется на {v1}",
  "A routing rule on this node names this list, so the node already holds it — pinning only decides whether it stays when that rule goes.":
    "Список указан в правиле маршрутизации на этой ноде, поэтому нода его уже держит — закрепление решает только, останется ли он, когда правило уйдёт.",
  // budget-ok: a tooltip — its own bubble, wraps
  "No IP list here — can't enforce in {v1}. Add an IP list, or use Force-DNS / Hybrid-SNI.":
    "Здесь нет списка адресов — в режиме {v1} применить нечего. Добавьте список адресов или включите Force-DNS / Hybrid-SNI.",
  "Filter on {v1}": "Фильтр на {v1}",
  "domains in this list": "доменов в списке",
  "IP ranges in this list": "диапазонов адресов в списке",
  // budget-ok: tooltips — their own bubble, wrap
  "the last update failed ({v1}) — the previous copy is still in use": "последнее обновление не удалось ({v1}) — работает предыдущая копия",
  "The panel couldn't download this list ({v1}). It retries on its own, less often each time.":
    "Панель не смогла скачать этот список ({v1}). Она повторяет попытки сама, каждый раз реже.",
  "The panel is downloading this list — the count appears when it's done": "Панель скачивает этот список — число записей появится, когда закончит",
  "not downloaded": "не скачан",
  "None of this category's lists is in use — their providers are switched off, or it has no lists yet. It blocks nothing until one is.":
    "Ни один список этой категории не используется — их источники выключены или списков ещё нет. Пока не появится хотя бы один, она ничего не блокирует.",
  // the two-panels banner (store.js trackInstance)
  "Two different panels are answering at this address.": "По этому адресу отвечают две разные панели.",
  "Each keeps its own servers, settings and lists, and the page shows whichever one answered — so what you see can change between reloads, and changes saved on the one your servers don't sync to never reach them. Keep the one your servers report to; stop the other.":
    "У каждой свои серверы, настройки и списки, а страница показывает ту, что ответила, — поэтому картина может меняться от перезагрузки к перезагрузке, а изменения, сохранённые в панели, с которой ваши серверы не синхронизируются, до них не доходят. Оставьте ту, с которой синхронизируются ваши серверы, а другую остановите.",
  "{v1} · version {v2} · state {v3} · {v4} · running since {v5}": "{v1} · версия {v2} · данные {v3} · {v4} · работает с {v5}",
  "nodes: {n}, reporting here: {r}": "нод: {n}, синхронизируются сюда: {r}",
  "this page": "эта страница",
  "also answered": "отвечала также",
  "last seen {v1}": "последний ответ {v1}",
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
  // ── restore / migrate (node rebuild) ────────────────────────────────────────────────────────────
  // One verb, two doors. "нода" throughout for the panel's record of the server, "машина" for the
  // physical box it runs on — the whole feature turns on that distinction (one node, two boxes), and
  // Russian sysadmin usage keeps them apart the same way.
  "Restore or migrate": "Восстановить/перенести",
  "Migrate": "Перенести",
  "tag|old box alive": "старый сервер жив",
  "recently": "недавно",
  "Addresses": "Адреса",
  "Run this on the box": "Выполните это на машине",
  "Preparing…": "Подготовка…",
  // budget-ok: sheet-foot buttons, foot has a grow spacer
  "Prepare the command": "Подготовить команду",
  "Prepare the migration": "Подготовить перенос",
  "Roll back to it": "Вернуться на неё",
  "It's gone — forget it": "Её больше нет — забыть",
  "Restore or migrate · {v1}": "Восстановление/перенос · {v1}",
  "Migrate · {v1}": "Перенос · {v1}",
  "The old box · {v1}": "Старая машина · {v1}",
  "couldn't prepare the command": "не удалось подготовить команду",
  "couldn't roll back": "не удалось вернуться",
  "Old box forgotten.": "Старая машина забыта.",
  "Rolled back — the old box resumes on its next sync.":
    "Откат — старая машина вернётся на следующей синхронизации.",
  "Rebuild this node from what the panel holds — a paste-on-the-server command that brings back its interfaces, keys and turn-proxies, on this box or a new one":
    "Пересобрать ноду из того, что хранит панель — команда для вставки на сервере вернёт её интерфейсы, ключи и turn-прокси, на этой машине или на новой",
  "Move this node to another server — the panel gives you a command that rebuilds it there from what it holds":
    "Перенести ноду на другой сервер — панель выдаст команду, которая пересоберёт её там из того, что хранит панель",
  "Forget the old box's token — the badge goes away and this panel keeps the new box":
    "Забыть токен старой машины — плашка исчезнет, панель останется на новой машине",
  "Migrated {v1}. The old server is still running and still serving its peers — it's locked out of this panel by a rotated token, nothing else. Roll back to it in one click, or tell the panel it's gone.":
    "Миграция {v1}. Старый сервер продолжает работать и обслуживать свои пиры — от панели его отрезал только смененный токен, больше ничего. Можно вернуться на него одним кликом или сказать панели, что его больше нет.",
  // Tsplit sentences — the {markers} are split points, so every one of them has to survive translation.
  "This gives you a one-line command to run on the {newbox}. It pulls everything the panel holds for {name} — its interfaces with their original keys and settings, its turn-proxies, its place in the mesh — so the node comes back as itself.":
    "Панель выдаст команду в одну строку для запуска на {newbox}. Она заберёт всё, что панель хранит для {name} — интерфейсы с их исходными ключами и настройками, turn-прокси, место в меше — так что нода вернётся сама собой.",
  // budget-ok: a bolded run INSIDE a notice paragraph (Tsplit), not a label — it wraps with the sentence
  "new box": "новой машине",
  "{name} isn't reporting. This gives you a one-line command that rebuilds it from what the panel holds — run it on the {either}. Either way the node comes back as itself, with its interfaces, keys and turn-proxies.":
    "{name} не отчитывается. Панель выдаст команду в одну строку, которая пересоберёт ноду из того, что хранит панель — выполните её на {either}. В любом случае нода вернётся сама собой: со своими интерфейсами, ключами и turn-прокси.",
  "same box, a damaged one, or a brand-new one": "той же машине, на повреждённой или совсем новой",
  "{name} was migrated {when}. The old box is still running and still serving the peers it had — it simply stopped syncing with this panel. Nothing on it was changed.":
    "{name} перенесена {when}. Старая машина продолжает работать и обслуживать доставшиеся ей пиры — она просто перестала синхронизироваться с этой панелью. На ней ничего не менялось.",
  // the outcome of an arming — what comes back, what does not, and what it costs
  // WDTT/csqtt are declarative — the panel ships their config every sync and their users come from the
  // roster — so the honest line is a reassurance, not a warning. "сами" carries that better than a passive.
  "The old box keeps running and keeps serving its peers — it just stops syncing here. One click rolls this panel back to it, from the badge on the node, for as long as you keep it.":
    "Старая машина продолжает работать и обслуживать свои пиры — она лишь перестаёт синхронизироваться здесь. Пока она у вас есть, панель возвращается на неё одним кликом — с плашки на ноде.",
  "No rollback point was kept: this node wasn't reporting, so there was nothing running to roll back to. The command below is the way back.":
    "Точка отката не сохранена: нода не отчитывалась, возвращаться было не на что. Путь назад — команда ниже.",
  "The node's current token stops working immediately — so if the box is only briefly unreachable rather than broken, wait for it instead. The command below is then the only way it gets back in.":
    "Текущий токен ноды перестанет работать сразу же — если машина просто ненадолго недоступна, а не сломана, лучше дождаться её. Иначе вернуться в панель она сможет только по команде ниже.",
  "This node is reporting, so the box it runs on now is left alone: it keeps running, keeps its peers connected, and only stops syncing with this panel. You can roll back to it in one click until you tell the panel it's gone.":
    "Нода отчитывается, поэтому машину, на которой она работает сейчас, никто не трогает: она продолжит работать, пиры на ней останутся подключёнными, прекратится только синхронизация с этой панелью. Вернуться на неё можно одним кликом — пока вы не скажете панели, что её больше нет.",
  "Nothing is destroyed and nothing is sent to either box — the panel can only hand you a command to run. Prepare it, then run it on the new server.":
    "Ничего не уничтожается и ни на одну из машин ничего не отправляется — панель может только выдать команду. Подготовьте её и выполните на новом сервере.",
  "Transferred here from {v1} {v2}. Anything from before that — its history, its stored baselines — is still on that panel.":
    "Передана сюда из {v1} {v2}. Всё, что было до этого — история, сохранённые слепки — осталось на той панели.",
  "Transferred here from {v1} {v2}, where it was called «{v3}». Anything from before that — its history, its stored baselines — is still on that panel.":
    "Передана сюда из {v1} {v2}, там она называлась «{v3}». Всё, что было до этого — история, сохранённые слепки — осталось на той панели.",
  "Rotate token — and get a one-line command that fixes only the credential":
    "Сменить токен — и получить команду, которая чинит только его",
  "Only fix the credential — no re-install":
    "Починить только токен — без переустановки",
  "Run this when the node is healthy and only its token is wrong — after a rotate that landed somewhere unexpected, say. It changes the token and restarts the node; it installs nothing, touches no interface, and leaves the panel address and TLS settings exactly as they are.":
    "Выполните это, если с нодой всё в порядке и неверен только токен — например, после смены токена не на той ноде. Команда меняет токен и перезапускает ноду: ничего не устанавливает, интерфейсы не трогает, адрес панели и настройки TLS оставляет как есть.",
  "no record here — neither it nor its {v1} come back":
    "нет записи в панели — не вернётся ни он, ни его {v1}",
  "no record here — it does not come back":
    "нет записи в панели — не вернётся",
  "no record here — it comes back only if the box's own configuration recreates it":
    "нет записи в панели — вернётся, только если его пересоздаст конфигурация самой машины",
  "the panel never captured a config for it — it can only be recreated fresh":
    "панель не сохранила его конфигурацию — только создать заново",
  "unknown fork or unreadable bind — re-add this proxy by hand":
    "неизвестный форк или нечитаемый bind — добавьте прокси заново вручную",
  "no usable escrow for its identity — it comes back holding, and recreating it re-keys every user":
    "нет рабочего эскроу для его идентичности — вернётся в ожидании, а пересоздание сменит ключ всем пользователям",
  "no escrow and no key backup — it comes back with a new key, so its clients re-import":
    "нет ни эскроу, ни резервной копии ключа — вернётся с новым ключом, клиентам понадобится новый конфиг",
  "its escrowed key opens for nobody — re-seal it before the box is wiped":
    "его ключ в эскроу никто не может открыть — перезапечатайте до того, как машину сотрут",
  "Accept the node's new key instead of restoring the original — you'll re-distribute every QR.":
    "Принять новый ключ ноды вместо восстановления исходного — QR придётся раздать заново.",
  "*The box no longer holds the original key* (it was re-created), but your *Encryption Vault does* — restore it from there and every existing config keeps working.":
    "*На машине исходного ключа больше нет* (её пересоздали), но *он есть в хранилище шифрования* — восстановите оттуда, и все существующие конфиги продолжат работать.",
  "tag|needs the vault":
    "нужно хранилище",
  "The node is waiting rather than minting a new key: unlock the Encryption Vault and restore this interface, and every existing client config keeps working":
    "Нода ждёт, а не создаёт новый ключ: разблокируйте хранилище шифрования и восстановите интерфейс — все существующие конфиги клиентов продолжат работать",
  "waiting for the Encryption Vault — its original key is escrowed":
    "ждёт хранилище шифрования — исходный ключ в эскроу",
  "Restore from the vault":
    "Восстановить из хранилища",
  "Puts the original key back from your Encryption Vault — existing clients keep working, no re-distribution.":
    "Вернёт исходный ключ из хранилища шифрования — существующие клиенты продолжат работать, ничего раздавать заново не нужно.",
  "tag|migrating":
    "переезжает",
  "This node is being migrated — it comes back with this interface as it was. Nothing to do until it reports.":
    "Нода переезжает — интерфейс вернётся таким, каким был. Пока она не отчитается, делать ничего не нужно.",
  "This node is being migrated — the server comes back with it.":
    "Нода переезжает — сервер вернётся вместе с ней.",
  "This node is being migrated — its mesh links are rebuilt automatically":
    "Нода переезжает — связи в меше пересоберутся сами",
  "it comes back with the node — nothing to do":
    "вернётся вместе с нодой — делать ничего не нужно",
  "it comes back with the node":
    "вернётся вместе с нодой",
  "its identity is escrowed — it comes back unchanged, no user re-imports":
    "идентичность в эскроу — вернётся без изменений, пользователям не нужен новый конфиг",
  "Network":
    "Сеть",
  "Panel settings → Network":
    "Настройки панели → Сеть",
  "{v1} — ingress":
    "{v1} — вход",
  "How peers, clients and turn-proxy links reach *{v1}*.":
    "Как пиры, клиенты и ссылки turn-прокси попадают на *{v1}*.",
  "This is the host in every client config and turn-proxy link for this node. Prefer a hostname: moving the box then costs one DNS change, and nothing a client already holds has to be re-issued.":
    "Это тот хост, который попадает в каждый клиентский конфиг и в каждую ссылку turn-прокси этой ноды. Лучше указать имя хоста: тогда переезд машины стоит одной записи DNS, и ничего из того, что уже есть у клиентов, переиздавать не придётся.",
  "No nodes yet — enroll a node to configure how it is reached, how it exits, and how it links.":
    "Нод пока нет — заведите ноду, чтобы настроить вход, выход и связи.",
  "Listen (local)":
    "Слушает (локально)",
  "Mesh links":
    "Связи в меше",
  "comes back without its {v1}":
    "вернётся без параметра {v1}",
  "forwards to {v1}, which is not coming back":
    "ведёт на {v1}, а он не вернётся",
  "The node runs this interface, but this panel holds no record of it: nothing here manages its peers or its settings, and a rebuild can't bring it back. Adopt it from Create new interface, giving it this exact name — the node then adds it to what it manages without touching the peers already on it.":
    "Нода поднимает этот интерфейс, но в панели о нём нет записи: ни пиры, ни настройки отсюда не управляются, и пересборка его не вернёт. Принять его можно через «Создать интерфейс», указав ровно это имя — нода добавит его к тому, чем управляет, не трогая уже поднятые на нём пиры.",
  "MTU":
    "MTU",
  "port":
    "порт",
  "address":
    "адрес",
  "obfuscation":
    "обфускация",
  "What the panel can't bring back":
    "Что панель не сможет вернуть",
  "What comes back as it is":
    "Что вернётся как есть",
  "The configs your users already have keep working — nothing has to be re-sent.":
    "Конфиги, которые уже есть у пользователей, продолжат работать — ничего пересылать не нужно.",
  "Checking what this would do…":
    "Проверяем, что это сделает…",
  "Couldn't check what this would do. The rebuild still works — it reports the same list once it runs.":
    "Не удалось проверить, что это сделает. Восстановление всё равно работает — оно покажет тот же список после запуска.",
  "Rolling back hands this panel back to the old box: its own token starts working again and it picks up on its next sync, peers and all. Whatever you installed on the new box stops syncing instead — nothing on it is touched, and you can migrate again whenever you like.":
    "Откат возвращает панель на старую машину: её собственный токен снова начинает работать, и на следующей синхронизации она подхватывает всё, включая пиры. То, что установлено на новой машине, вместо этого перестаёт синхронизироваться — на ней ничего не трогается, и перенос можно повторить в любой момент.",
  "If the migration went fine and the old server is decommissioned, forget it instead — that only drops the panel's copy of its old token.":
    "Если перенос прошёл нормально и старый сервер выведен из эксплуатации, вместо отката забудьте его — это лишь удалит хранящуюся в панели копию его старого токена.",
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
  "the subscription server has no certificate for {v1}": "у сервера подписок нет сертификата для {v1}",
  "{v1} and {v2}": "{v1} и {v2}",
  "{v1} — subscribers get a TLS error": "{v1} — у подписчиков будет ошибка TLS",
  "mode → {v1}": "режим → {v1}",
  "{v1} will briefly drop off the mesh (and any cascade/smart traffic routed through it pauses) until every peer pulls the new config and reconnects — usually a few seconds. Other nodes' links to each other are unaffected.":
    "{v1} ненадолго выпадет из сети (и каскадный/умный трафик через неё замрёт), пока каждый пир не заберёт новые настройки и не переподключится — обычно это несколько секунд. Связи других нод между собой не затронуты.",
  "turn-proxy": "turn-прокси",
  "loading…": "загрузка…",
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
  "linking →": "связь →",
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
  "Recorded an interface the node reports": "Интерфейс ноды взят в панель",
  "Recorded a server the node runs": "Сервер ноды взят в панель",
  "Imported peer from an onboarded interface": "Пир импортирован с принятого интерфейса",
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
  "Fitted mesh link padding to its MTU (live)": "Паддинг связи сети подогнан под её MTU (на лету)",
  "Flagged node for removal": "Нода помечена к удалению",
  "Host update started": "Обновление хоста запущено",
  "Imported WDTT user from adopted server": "Пользователь WDTT перенесён с принятого сервера",
  "Installed turn-proxy": "Установлен turn-прокси",
  "Linked node": "Ноды связаны",
  "Removed unused mesh links": "Неиспользуемые меш-линки удалены",
  "{count} · on demand, {nodes}": "{count} · по требованию, {nodes}",
  "Linked more node pairs": "Связаны ещё пары нод",
  "Node uninstalled — kept for re-install": "Нода удалена — оставлена для переустановки",
  "Onboarding interface": "Подключаем интерфейс",
  "Onboarding turn-proxy": "Подключаем turn-прокси",
  "Re-ported mesh links (live)": "Связи сети переведены на новый порт (на лету)",
  "Re-provisioned mesh links": "Связи сети пересобраны",
  // activity verbs for the rebuild adapter (ev_append writes English; the browser looks the sentence up)
  "Rebuild armed": "Пересборка подготовлена",
  "Rolled back to the superseded box": "Откат на прежнюю машину",
  "Superseded box discarded": "Прежняя машина забыта",
  "Recreate WDTT server (fresh identity)": "Пересоздать сервер WDTT (новые ключи)",
  "Removed WDTT instance": "Сервер WDTT убран",
  "Removed deployment": "Развёртывание убрано",
  "Removed node": "Нода удалена",
  "Egress reset to direct — its target node was removed": "Выход переключён на прямой — нода назначения удалена",
  "Egress reset to direct — it forwarded to no node at all": "Выход переключён на прямой — каскад не указывал ни на одну ноду",
  "An exit key restore expired without being applied": "Срок восстановления ключа выхода истёк, восстановление не выполнено",
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
  "Take over a container's interface": "Перенимаем интерфейс контейнера",
  "Withdrew a container take-over": "Отозван перенос контейнера",
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
  "Closed its local network (panel setting)": "Локальная сеть ноды закрыта (настройка панели)",
  "Updated panel settings": "Настройки панели изменены",
  "{count} unassigned": "отвязано: {count}",
  "{count} · {where}": "{count} · {where}",
  // ── the panel's own sentences: validation and lookup failures ──
  // The exit registry's and the WireGuard profile parser's refusals. They reach the browser as
  // {"error": …} and render through srvText() → T(), so the English sentence is the key like any other.
  "exits must be a list": "выходы должны быть списком",
  "each exit must be an object": "каждый выход должен быть объектом",
  "exit producer must be adopted|imported": "producer выхода должен быть adopted|imported",
  "unknown exit": "неизвестный выход",
  "default_exit must be one of this node's exits": "выход по умолчанию должен быть одним из выходов этой ноды",
  "the dial source must be an IPv4 address on this node":
    "адрес, с которого строится туннель, должен быть адресом IPv4 этой ноды",
  "the exit egress IP must be an IPv4 address": "адрес, с которым уходит трафик, должен быть адресом IPv4",
  "the exit gateway must be an IPv4 address": "шлюз exit'а должен быть адресом IPv4",
  "paste a WireGuard profile for this exit": "вставьте профиль WireGuard для этого выхода",
  "this exit has no stored key to keep — paste the whole profile":
    "у этого выхода нет сохранённого ключа — вставьте профиль целиком",
  "that doesn't look like a WireGuard profile": "это не похоже на профиль WireGuard",
  "the profile has no usable PrivateKey": "в профиле нет пригодного PrivateKey",
  "the profile's PresharedKey is not a usable key": "PresharedKey в профиле не похож на ключ",
  "the profile has no usable peer PublicKey": "в профиле нет пригодного PublicKey пира",
  "the profile has no usable Endpoint": "в профиле нет пригодного Endpoint",
  "the profile has no IPv4 Address (this exit is IPv4-only)":
    "в профиле нет Address для IPv4 (этот выход работает только по IPv4)",
  "the profile's Address is not an IPv4 address": "Address в профиле — не адрес IPv4",
  "the profile's Endpoint contains characters an endpoint cannot have":
    "в Endpoint профиля есть символы, которых в адресе быть не может",
  "routing must be a list of rules": "правила маршрутизации должны быть списком",
  "each routing rule must be an object": "каждое правило маршрутизации должно быть объектом",
  "rule action must be exit|direct|block|dev": "действие правила должно быть exit|direct|block|dev",
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
  "the panel is busy — this sync is skipped, the next one retries": "панель занята — эта синхронизация пропущена, следующая повторит",
  "invalid owner repo": "неверный репозиторий",
  "invalid version tag": "неверный тег версии",
  "invalid service name": "неверное имя службы",
  "invalid service or title": "неверная служба или название",
  "invalid username or password": "неверный логин или пароль",
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
  "the password file {v1} cannot be read ({v2}) — this panel runs as {v3}, so nobody can sign in and every request is refused. Fix it over SSH or the provider console: chown root:swg {v1}; chmod 640 {v1}; systemctl restart swg-panel-server  (or run swg-passwd to set a new password). If this panel is MEANT to have no login — reached only over an SSH tunnel, say — clear SWG_PANEL_AUTH in its unit instead: blank means no login by design, and an empty file cannot say that.": "файл пароля {v1} не читается ({v2}) — панель работает от пользователя {v3}, поэтому войти не может никто и все запросы отклоняются. Исправьте по SSH или через консоль провайдера: chown root:swg {v1}; chmod 640 {v1}; systemctl restart swg-panel-server  (или запустите swg-passwd, чтобы задать новый пароль). Если панель ДОЛЖНА работать без входа — например, доступна только через SSH-туннель — очистите SWG_PANEL_AUTH в её юните: пустое значение означает «входа нет» намеренно, а пустой файл этого не выражает.",
  "no auth file configured (SWG_PANEL_AUTH unset)": "файл входа не настроен (SWG_PANEL_AUTH не задан)",
  "enter a valid authenticator or recovery code": "введите код из приложения или запасной код",
  "that code isn't valid": "код не подходит",
  "too many wrong codes — wait {v1} minutes, or sign in with one of your recovery codes":
    "слишком много неверных кодов — подождите {v1} мин. или войдите с запасным кодом",
  "that code isn't valid — check the app and your device clock":
    "код не подходит — проверьте приложение и часы на устройстве",
  "awg_params must be an object": "awg_params должен быть объектом",
  "blocks/step must be integers": "blocks и step должны быть целыми",
  "categories/providers must be objects, removed a list": "categories и providers — объекты, removed — список",
  "egress IP must be an IPv4 address": "адрес выхода должен быть IPv4",
  "egress_mode must be direct|forward|smart|exit": "egress_mode: direct, forward, smart или exit",
  "exit_id must be one of this node's exits": "exit_id должен указывать на один из exit'ов этой ноды",
  "egress_node must be another known node": "egress_node должен быть другой известной нодой",
  "endpoint host must be a bare hostname or IP": "адрес входа — только имя хоста или IP",
  "expiry must be an epoch timestamp or 0": "срок — метка времени epoch или 0",
  "kind must be node|iface|turn": "kind: node, iface или turn",
  "listen and connect must be ip:port": "listen и connect задаются как ip:порт",
  "listen must be ip:port": "listen задаётся как ip:порт",
  "max_passwords must be an integer": "max_passwords должен быть целым",
  "mesh port must be 1–65535 (or blank)": "порт сети — от 1 до 65535 (или пусто)",
  "mesh subnet must be a CIDR (or blank)": "подсеть сети — CIDR (или пусто)",
  "mesh_mode must be auto, full or demand": "mesh_mode: auto, full или demand",
  "mesh subnet must be an IPv4 range of /31 or larger (or blank)": "подсеть меша — диапазон IPv4 размером /31 или шире (или пусто)",
  "{v1} holds too few mesh links for this node ({v2} fit, {v3} needed) — choose a larger subnet, or leave it blank to use the panel's": "В подсети {v1} слишком мало места для меш-линков этой ноды (помещается: {v2}, нужно: {v3}) — выберите подсеть шире или оставьте поле пустым, чтобы взять подсеть панели",
  "mtu must be 576–9200": "MTU — от 576 до 9200",
  "mtu out of range (576-9200)": "MTU вне диапазона (576–9200)",
  "mtu must be a number": "MTU должен быть числом",
  "n (AS number) required": "нужен номер AS",
  "order must be a list": "order должен быть списком",
  "port must be 1–65535": "порт — от 1 до 65535",
  "port must be a number": "порт должен быть числом",
  "range must be live|hour|day|week|month": "range: live, hour, day, week или month",
  "range must be live|hour|day|week|month|custom": "range: live, hour, day, week, month или custom",
  "reserved mesh subnet must be a CIDR": "служебная подсеть сети — CIDR",
  "reserved mesh subnet must be an IPv4 range of /31 or larger": "служебная подсеть меша — диапазон IPv4 размером /31 или шире",
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
  "confirm must be made on the new console address": "подтверждать нужно на новом адресе консоли",
  "no matching pending console change": "подходящего запланированного изменения консоли нет",
  "no console change to cancel": "отменять нечего — изменений консоли нет",
  "a console address change is still waiting to be confirmed — finish or cancel that first":
    "изменение адреса консоли всё ещё ждёт подтверждения — сначала завершите или отмените его",
  "a change is still waiting to be confirmed — finish or cancel it first":
    "изменение всё ещё ждёт подтверждения — сначала завершите или отмените его",
  "port {v1} is the subscription server's — pick a different, free port for the console":
    "порт {v1} занят сервером подписок — выберите для консоли другой свободный порт",
  "port {v1} is this box's own node loopback endpoint — pick a different, free port for the console":
    "порт {v1} — это loopback-точка собственной ноды этой машины; выберите для консоли другой свободный порт",
  "this panel's container doesn't publish a console port, so a console bound inside it would be unreachable. Re-run the Docker installer to restage docker-compose.yml (it adds the port), then try again.":
    "контейнер этой панели не публикует порт консоли, поэтому консоль, поднятая внутри него, будет недоступна. Перезапустите установщик Docker, чтобы пересобрать docker-compose.yml (он добавит порт), и попробуйте снова.",
  "couldn't bind {v1} — {v2}. If your reverse proxy still owns that port, stop it there first — the panel and the proxy can't both hold it.":
    "не удалось занять {v1} — {v2}. Если порт всё ещё держит ваш обратный прокси, освободите его там: панель и прокси не могут держать один порт вдвоём.",
  "hold on {v1}s — the nodes are still learning the new address so the restart won't strand them":
    "подождите {v1} с — ноды ещё узнают новый адрес, чтобы перезапуск их не отрезал",
  // the recreate guard's refusals — "present" alone is no longer the reason one is declined (T-8)
  "interface is already present and healthy on the node with the key its clients use — nothing to recreate":
    "интерфейс на ноде уже есть, поднят и работает с тем ключом, который используют его клиенты — пересоздавать нечего",
  "interface is up but serving a different server key — restore the key instead (Adopt/Restore on the interface), which keeps every client working":
    "интерфейс поднят, но отдаёт другой ключ сервера — вместо пересоздания восстановите ключ (Принять/Восстановить на интерфейсе): так все клиенты продолжат работать",
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
  "the change expired while the new address was being checked — nothing was changed": "изменение истекло, пока проверялся новый адрес, — ничего не изменено",
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
  "{v1} is a system mesh link — not a peer interface": "{v1} — служебная связь сети, а не интерфейс для пиров",
  // A peer may hold a mix of kinds; these three replace the flat "that's a WDTT interface" refusal.
  "{v1} is a self-contained turn server — add its users from the peer sheet, not by adopting a WireGuard key":
    "{v1} — самодостаточный turn-сервер: его пользователей добавляют из карточки пира, а не принятием ключа WireGuard",
  "{v1} needs a client key — this peer has none (rotate its keys first)":
    "{v1} нужен клиентский ключ, а у этого пира его нет (сначала смените ему ключи)",
  "{v1} assigns the client address on connect — it can't be set here":
    "{v1} выдаёт адрес клиенту при подключении — здесь его не задать",
  "nothing to change (send ip and/or overrides)": "нечего менять (передайте ip и/или overrides)",
  "{v1} is already used on {v2}": "{v1} уже занят на {v2}",
  "kind|bare-metal": "Железо",
  "kind|docker": "Докер",
  "kind|podman": "Подман",
  "Unlock to restore this server's identity": "Разблокируйте, чтобы восстановить личность сервера",
  "This server's original keypair and owner password are escrowed under your encryption key — the panel only ever held the ciphertext. Unlock it to bring the server back exactly as it was, with every existing user config still working.":
    "Исходная пара ключей сервера и пароль владельца хранятся под вашим ключом шифрования — панель держала только шифртекст. Разблокируйте его, чтобы вернуть сервер ровно таким, каким он был: все текущие конфигурации пользователей продолжат работать.",
  "nothing is restored. The server stays down until you unlock the key, or you can Recreate fresh instead — which mints a new server key and makes every user re-import.":
    "ничего не восстановится. Сервер останется выключенным, пока вы не разблокируете ключ; либо пересоздайте заново — тогда будет выпущен новый ключ сервера и всем пользователям придётся переимпортировать ссылку.",
  "take-over failed: {e}": "не удалось взять под управление: {e}",
  "Delivery": "Способ установки",
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

  /* Catalog-authored field text (fork client/server schemas) and the two sheets that render it.
     These arrive from the panel as DATA, so no extractor ever saw them — they are translated the way
     server messages are: the English sentence is the key. Fork names, blocklist providers and protocol
     names are deliberately absent, being proper nouns that render as-is through T()'s fallback. */
  "64 hex chars — must match the FreeTurn client.": "64 hex-символа — должны совпадать с клиентом FreeTurn.",
  "64 hex chars — must match the client app. Changing it breaks every client using the old key.":
    "64 hex-символа — должны совпадать с приложением. Смена ломает всех клиентов со старым ключом.",
  "AEAD the server accepts for WRAP (-wrap-cipher, WINGS-N v2.1.0). any = accept either; or pin one — the client must offer it.":
    "AEAD, который сервер принимает для WRAP (-wrap-cipher, WINGS-N v2.1.0). any = принимать любой; либо закрепить один — клиент должен его предлагать.",
  "Anonymous credential path (-vk-anon-path): vkcalls = the v1.5.x api.vk.me flow that usually SKIPS the captcha (recommended) · legacy = the old path. Needs the LATEST MYSOREZ core.":
    "Путь анонимных учёток (-vk-anon-path): vkcalls = схема api.vk.me из v1.5.x, обычно БЕЗ капчи (рекомендуется) · legacy = старый путь. Нужно САМОЕ НОВОЕ ядро MYSOREZ.",
  "Browser fingerprint": "Отпечаток браузера",
  "Captcha auto-solver": "Авторешатель капчи",
  "Captcha mode": "Режим капчи",
  "Comma-separated DNS resolvers the app uses (Turn.user_dns). Blank = the app's default.":
    "DNS-резолверы приложения через запятую (Turn.user_dns). Пусто = умолчание приложения.",
  "Comma-separated DNS resolvers. Blank = the peer's own config DNS (else 1.1.1.1).":
    "DNS-резолверы через запятую. Пусто = DNS из конфига самого пира (иначе 1.1.1.1).",
  "Comma-separated DNS servers (-dns-servers). Blank = the app's default.":
    "DNS-серверы через запятую (-dns-servers). Пусто = умолчание приложения.",
  "Connections": "Соединения",
  "Credential group size": "Размер группы учёток",
  "Curated": "Подобранный",
  "Custom DNS": "Свой DNS",
  "DNS mode": "Режим DNS",
  "Debug logging": "Подробный лог",
  "Default client apps": "Клиентские приложения по умолчанию",
  "Device ID": "ID устройства",
  "Disable obfuscation": "Отключить обфускацию",
  "Extra CLI flags": "Дополнительные флаги CLI",
  "Extra arguments appended to the client command, one per line (e.g. -turn <relay>). Blank = none.":
    "Дополнительные аргументы к команде клиента, по одному в строке (например -turn <релей>). Пусто = нет.",
  "Extra command arguments, one per line — appended to the app's flags (the app's Raw-mode 'Флаги и аргументы'). Blank = none.":
    "Дополнительные аргументы команды, по одному в строке — добавляются к флагам приложения (поле «Флаги и аргументы» в Raw-режиме). Пусто = нет.",
  "Extra flags (raw)": "Дополнительные флаги (как есть)",
  "For rtpopus (WRAP-S) servers: which RTP/Opus profile the app mimics (Turn.obfProfile) — must match the server. auto = the app's default (rtpopus).":
    "Для серверов rtpopus (WRAP-S): под какой профиль RTP/Opus маскируется приложение (Turn.obfProfile) — должен совпадать с сервером. auto = умолчание приложения (rtpopus).",
  "Force manual captcha entry in the app (Turn.manual_captcha). Off = the app's default.":
    "Всегда вводить капчу вручную в приложении (Turn.manual_captcha). Выкл = умолчание приложения.",
  "How many TURN streams share one VK credential group (Turn.creds_group_size, WINGSV_DeX v0.3.0). Blank = the app's default.":
    "Сколько TURN-потоков делят одну группу учёток VK (Turn.creds_group_size, WINGSV_DeX v0.3.0). Пусто = умолчание приложения.",
  "How the MYSOREZ core solves the VK captcha (-captcha-mode): auto = Go smart-captcha solver (recommended) · wv = in-app WebView (NOT wired to feed the token back) · rjs = remote JS.":
    "Как ядро MYSOREZ решает капчу VK (-captcha-mode): auto = решатель smart-captcha на Go (рекомендуется) · wv = WebView внутри приложения (токен обратно НЕ передаётся) · rjs = удалённый JS.",
  "How the app runs the tunnel (Turn.runtime_mode). auto = the app decides; vpn = system VPN; proxy = local proxy.":
    "Как приложение поднимает туннель (Turn.runtime_mode). auto = решает приложение; vpn = системный VPN; proxy = локальный прокси.",
  "How the app solves the VK captcha (Turn.captcha_auto_solver): auto = the app's own default (Enhanced) · v2 = Enhanced · v1 = Classic · bypass = solve via vk.me.":
    "Как приложение решает капчу VK (Turn.captcha_auto_solver): auto = собственное умолчание приложения (Enhanced) · v2 = Enhanced · v1 = Classic · bypass = через vk.me.",
  "Link source": "Источник ссылки",
  "MYSOREZ mzrtp obfuscation (-wrap) — needs a password. Off = plain (VK throttles unobfuscated traffic).":
    "Обфускация mzrtp у MYSOREZ (-wrap) — нужен пароль. Выкл = без обфускации (VK режет неприкрытый трафик).",
  "Manual captcha": "Капча вручную",
  "Obfuscation (WRAP)": "Обфускация (WRAP)",
  "Obfuscation key": "Ключ обфускации",
  "Obfuscation profile": "Профиль обфускации",
  "Off = TCP-control (bypasses VK's per-cred allocation-rate throttle — recommended). On only if your network throttles TCP to the relay.":
    "Выкл = управление по TCP (обходит ограничение VK на скорость выдачи по учётке — рекомендуется). Вкл только если ваша сеть режет TCP до релея.",
  "Parallel TURN connections (1–50). The VK TURN Proxy app default is 30.":
    "Параллельные TURN-соединения (1–50). В приложении VK TURN Proxy по умолчанию 30.",
  "Parallel TURN streams (-n). Blank = the app's default (10).":
    "Параллельные TURN-потоки (-n). Пусто = умолчание приложения (10).",
  "Name this connection takes in the FreeTurn app's list (the link's `name`). This setting covers every proxy of this fork, so use {fork}, {host} or {port} to vary it per server — «Frankfurt {port}» becomes «Frankfurt 56009». Blank = the app names it itself.":
    "Имя, под которым это подключение попадёт в список приложения FreeTurn (поле `name` в ссылке). Настройка действует на все прокси этого форка, поэтому используйте {fork}, {host} или {port}, чтобы имя отличалось по серверам — «Frankfurt {port}» станет «Frankfurt 56009». Пусто = приложение назовёт само.",
  "Name this connection takes in the app's server list (build 179+, which keeps several named servers; older ones ignore it). Importing adds a server under this name and keeps the ones already there. This setting covers every proxy of this fork, so use {fork}, {host} or {port} to vary it per server — «Frankfurt {port}» becomes «Frankfurt 56005». Blank = the app names it ServerN.":
    "Имя, под которым это подключение попадёт в список серверов приложения (сборка 179+, где хранится несколько именованных серверов; более старые поле игнорируют). Импорт добавляет сервер с этим именем, уже добавленные остаются. Настройка общая для всех прокси этого форка, поэтому, чтобы имя различалось по серверам, используйте {fork}, {host} или {port} — «Frankfurt {port}» превратится в «Frankfurt 56005». Пусто = приложение само назовёт его ServerN.",
  "Pin fresh connections to a specific TURN relay (ip:port). Blank = the VK-returned relay.":
    "Закрепить новые соединения за конкретным TURN-релеем (ip:порт). Пусто = релей, который вернул VK.",
  "Reach the TURN relay over UDP (-udp). On by default in the app.":
    "Ходить к TURN-релею по UDP (-udp). В приложении включено по умолчанию.",
  "Reach the TURN relay over UDP (Turn.use_udp). On by default.":
    "Ходить к TURN-релею по UDP (Turn.use_udp). По умолчанию включено.",
  "Reconnect when the device network changes (Turn.restart_on_network_change). Off = the app's default.":
    "Переподключаться при смене сети на устройстве (Turn.restart_on_network_change). Выкл = умолчание приложения.",
  "Relay transport": "Транспорт до релея",
  "Resolver mode (-dns-mode). auto = the app decides.":
    "Режим резолвера (-dns-mode). auto = решает приложение.",
  "Restart on network change": "Перезапуск при смене сети",
  "Runtime mode": "Режим работы",
  "SRTP mode": "Режим SRTP",
  "Server defaults": "Настройки сервера по умолчанию",
  "Session mode": "Режим сессии",
  "Shared secret the core HKDFs to the AEAD key — must match the client. Required when WRAP is on. Auto-generated.":
    "Общий секрет, из которого ядро выводит ключ AEAD через HKDF — должен совпадать с клиентом. Обязателен при включённом WRAP. Генерируется автоматически.",
  "Solve the VK captcha manually in the app (--manual-captcha).":
    "Решать капчу VK вручную в приложении (--manual-captcha).",
  "Solve the VK captcha manually in the app (-manual-captcha).":
    "Решать капчу VK вручную в приложении (-manual-captcha).",
  "Stable device id (-device-id) VK ties the session to. Blank = the core generates one.":
    "Постоянный id устройства (-device-id), к которому VK привязывает сессию. Пусто = ядро сгенерирует само.",
  "Stream/worker count (-n). Blank = the app's default (8).":
    "Количество потоков/воркеров (-n). Пусто = умолчание приложения (8).",
  "Streams": "Потоки",
  "Streams per credential": "Потоков на учётку",
  "Streams sharing one VK credential (-streams-per-cred). Blank = default (10).":
    "Сколько потоков делят одну учётку VK (-streams-per-cred). Пусто = по умолчанию 10.",
  "TLS/HTTP imitation family the relay presents (Turn.browser_fingerprint). auto = random per session.":
    "Под какое семейство TLS/HTTP маскируется релей (Turn.browser_fingerprint). auto = случайно на каждую сессию.",
  "TURN relay override": "Явный TURN-релей",
  "TURN session multiplexing (Turn.session_mode). auto = the app decides; mux shares one session across streams.":
    "Мультиплексирование TURN-сессий (Turn.session_mode). auto = решает приложение; mux = одна сессия на все потоки.",
  "Transport to the TURN relay (-transport, free-turn-proxy v2.1). auto = the app default (udp); tcp helps where UDP is throttled or blocked.":
    "Транспорт до TURN-релея (-transport, free-turn-proxy v2.1). auto = умолчание приложения (udp); tcp помогает там, где UDP режут или блокируют.",
  "Turn off the app's traffic obfuscation (Turn.no_obfuscation). Off = the app's default (obfuscation on).":
    "Отключить обфускацию трафика в приложении (Turn.no_obfuscation). Выкл = умолчание приложения (обфускация включена).",
  "UDP control transport": "Управление по UDP",
  "UDP transport": "Транспорт UDP",
  "Use the VK cookie-auth path instead of anonymous proof-of-work.":
    "Использовать вход VK по cookie вместо анонимного proof-of-work.",
  "VK auth": "Авторизация VK",
  "VK authentication (-vk-auth): anonymous = proof-of-work (recommended) · account = needs a creds bridge the app doesn't provide.":
    "Аутентификация VK (-vk-auth): anonymous = proof-of-work (рекомендуется) · account = нужен мост учётных данных, которого в приложении нет.",
  "VK bypass path": "Путь обхода VK",
  "VK cookie auth": "Авторизация VK по cookie",
  "Verbose app logging (-debug).": "Подробный лог приложения (-debug).",
  "WINGS V worker count (-n). Blank = the app's own default.":
    "Количество воркеров WINGS V (-n). Пусто = собственное умолчание приложения.",
  "WRAP = keyed (the key must match the app's WRAP KEY field); SRTP = keyless.":
    "WRAP = с ключом (ключ должен совпадать с полем WRAP KEY в приложении); SRTP = без ключа.",
  "WRAP cipher": "Шифр WRAP",
  "Which call-link source the app uses: -vk-link = VK Calls · -yandex-link = Yandex.":
    "Какой источник ссылок на звонки использует приложение: -vk-link = Звонки VK · -yandex-link = Яндекс.",
  "Worker threads": "Рабочие потоки",
  "TURN worker streams the app opens per VK hash (the qwdtt:// link's `workers`). Blank = the app's default.":
    "Сколько рабочих TURN-потоков приложение открывает на один хеш VK (параметр `workers` в ссылке qwdtt://). Пусто = умолчание приложения.",
  "Workers per hash": "Воркеров на хеш",
  "Wrap key": "Ключ WRAP",
  "off": "выкл",
  "on": "вкл",
  "rtpopus* dress the traffic as an RTP/Opus call; none = plain. Must match the FreeTurn client.":
    "rtpopus* маскируют трафик под звонок RTP/Opus; none = без маскировки. Должно совпадать с клиентом FreeTurn.",
  "{v1} users will be offered nothing for this server":
    "Пользователям {v1} для этого сервера ничего не предложат",
  "{v1} users will be offered {v2}": "Пользователям {v1} предложат {v2}",


  /* Client-artifact text from turn-artifacts.js — the label on a config panel and the hint under it.
     That file is a plain script shared with the subscription page, so it cannot call T(); the panel
     translates what it renders, the way it does for catalog and server sentences. The label is composed
     there from a fork and an author, so it arrives as parts and goes through the placeholder key below. */
  "CSQTT (csqtt://connect)": "CSQTT (csqtt://connect)",
  "Open the csqtt:// link in your csqtt app, or paste it in.":
    "Откройте ссылку csqtt:// в своём csqtt-приложении или вставьте её туда.",
  "Open the link on the iPhone (or VK TURN Proxy → Settings → Import from connection link) to import in WRAP-A mode.":
    "Откройте ссылку на iPhone (или VK TURN Proxy → Настройки → Импорт из ссылки подключения), чтобы импортировать в режиме WRAP-A.",
  "Open the link on the iPhone (or VK TURN Proxy → Settings → Import from connection link) to import in csqtt mode.":
    "Откройте ссылку на iPhone (или VK TURN Proxy → Настройки → Импорт из ссылки подключения), чтобы импортировать в режиме csqtt.",
  "Open the link on the iPhone (or the app's Settings → Import from connection link) to import into the VK TURN Proxy app.":
    "Откройте ссылку на iPhone (или Настройки приложения → Импорт из ссылки подключения), чтобы импортировать в VK TURN Proxy.",
  "Paste the wdtt:// link into PWDTT — «Добавление VK профиля».":
    "Вставьте ссылку wdtt:// в PWDTT — «Добавление VK профиля».",
  "Scan the QR or open the qwdtt:// link in the qWDTT app (Android) or PWDTT (desktop).":
    "Отсканируйте QR или откройте ссылку qwdtt:// в приложении qWDTT (Android) или PWDTT (десктоп).",
  "Scan the QR or open the wdtt:// link in WDTT-Plus.":
    "Отсканируйте QR или откройте ссылку wdtt:// в WDTT-Plus.",
  "Scan the QR or open the wdtt:// link in the WDTT app (Android) or PWDTT (desktop).":
    "Отсканируйте QR или откройте ссылку wdtt:// в приложении WDTT (Android) или PWDTT (десктоп).",
  "Scan the QR with the FreeTurn app (samosvalishe/turn-proxy-android), or paste the freeturn:// link — it carries the VK call link and the whole config.":
    "Отсканируйте QR приложением FreeTurn (samosvalishe/turn-proxy-android) или вставьте ссылку freeturn:// — она несёт ссылку на звонок VK и всю конфигурацию.",
  "Scan the QR with the WINGS V app, or paste the wingsv:// link (Settings → import from link).":
    "Отсканируйте QR приложением WINGS V или вставьте ссылку wingsv:// (Настройки → импорт из ссылки).",
  "This server needs a separate client binary. Scan the QR or import .conf into WireGuard/AmneziaWG, then run the client alongside it:":
    "Этому серверу нужен отдельный клиентский бинарник. Отсканируйте QR или импортируйте .conf в WireGuard/AmneziaWG, а затем запустите клиент рядом:",
  "WDTT via PWDTT (desktop · wdtt:// base64) by ildarmaga":
    "WDTT через PWDTT (десктоп · wdtt:// base64) от ildarmaga",
  "WDTT via VK TURN Proxy (iOS · WRAP-A) by anton48": "WDTT через VK TURN Proxy (iOS · WRAP-A) от anton48",
  "CSQTT via VK TURN Proxy (iOS) by anton48": "CSQTT через VK TURN Proxy (iOS) от anton48",
  "WDTT via WDTT app (Android · WRAP)": "WDTT через приложение WDTT (Android · WRAP)",
  "WDTT via WDTT-Plus (Android · wdtt://connect)": "WDTT через WDTT-Plus (Android · wdtt://connect)",
  "WDTT via qWDTT (Android · qwdtt://)": "WDTT через qWDTT (Android · qwdtt://)",
  "{v1} via {v2} ({v3}) by {v4}": "{v1} через {v2} ({v3}) от {v4}",
  "{v1} — opens with one tap": "{v1} — открывается в одно касание",
  "{v1} — scans a QR code": "{v1} — сканирует QR-код",
  "{v1} — imports a pasted link": "{v1} — импортирует скопированную ссылку",

  // ── T-10 · Transfer: this node moves to ANOTHER PANEL, and the server itself is not touched ─────
  // "Передача" (handover), never "миграция" — Migrate already owns that word here and means the opposite
  // thing (a new box, the same panel). The distinction is the whole feature, so it is carried by the verb.
  "Transfer": "Передать",
  "Transfer · {v1}": "Передача · {v1}",
  "Transfer to {v1}": "Передать на {v1}",
  "Transferring…": "Передаём…",
  "Check the other panel": "Проверить ту панель",
  "Hand this node to another panel — the box keeps running exactly as it is and starts syncing there instead":
    "Передать ноду другой панели — сервер продолжает работать как есть и начинает синхронизироваться с ней",
  "This hands {name} to another panel. The server itself is {untouched} — same box, same interfaces, same addresses — it just starts syncing over there. Its users, their peers and their stored configs go with it.":
    "{name} переходит к другой панели. Сам сервер {untouched} — та же машина, те же интерфейсы, те же адреса — он просто начинает синхронизироваться с новой панелью. Его пользователи, их пиры и сохранённые конфиги уезжают вместе с ним.",
  "not touched at all": "не трогаем вообще",
  "Reached {v1} — over plain HTTP. Everything in this transfer, the other panel's token included, crosses unencrypted, and the node will dial it the same way.":
    "Связь с {v1} есть, но по обычному HTTP. Всё, что уходит при передаче, включая токен той панели, идёт незашифрованным — и нода будет обращаться туда так же.",
  "Reached {v1} — its certificate is publicly trusted, and the node will check the same thing before it moves.":
    "Связь с {v1} есть, сертификат подтверждён публичным CA — нода перед переездом проверит то же самое.",
  "Reached {v1}. Its certificate is self-signed, so the node will accept it only if it presents the exact certificate this panel just saw.":
    "Связь с {v1} есть. Сертификат самоподписанный, поэтому нода примет её, только если та предъявит ровно тот сертификат, который сейчас увидела эта панель.",
  "couldn't reach that panel": "нет связи с той панелью",
  "the transfer didn't start": "передача не началась",

  // The two boxes. Order matters: what STAYS is first, because it is the half nobody would think to ask
  // about — nothing here disconnects a user, and all of it is invisible until someone needs it.
  "Peers on the panel-wide call link — the other panel resolves its own":
    "Пиры на общей ссылке панели — та панель подставит свою",
  "Never set up through this panel — nothing to hand over":
    "Никогда не создавалось через эту панель — передавать нечего",
  "Subscription links keep this panel's address in them":
    "В ссылках подписки остаётся адрес этой панели",
  "Managed by its own configuration — it will point itself back":
    "Управляется своей конфигурацией — она вернёт ноду обратно",
  "update panelUrl and the token file there too": "обновите там panelUrl и файл с токеном",

  "What moves to the other panel": "Что переезжает на другую панель",
  "The node keeps running throughout — it is not reinstalled, its addresses don't change, and nothing your users hold has to be re-sent.":
    "Нода всё это время работает — её не переустанавливают, адреса не меняются, и ничего из того, что уже есть у пользователей, пересылать не нужно.",
  "Interfaces, with their keys and settings": "Интерфейсы, с их ключами и настройками",
  "WDTT / csqtt servers, with their configuration": "Серверы WDTT / csqtt, с их конфигурацией",
  "Users, and every peer deployed here": "Пользователи и все их пиры на этой ноде",
  "Stored configs — the links your users already hold keep opening them":
    "Сохранённые конфиги — ссылки, которые уже есть у пользователей, продолжат их открывать",
  "Users' encryption keys — re-wrapped there the next time you unlock the vault":
    "Ключи шифрования пользователей — перешифруются там при следующей разблокировке хранилища",
  "Mesh links — the other panel builds its own": "Связи меша — та панель поднимет свои",

  // The wait. It is not a progress bar: the node decides when it moves, and until it does this panel is
  // still its panel — so every line here is written to make "nothing has happened yet" reassuring.
  "Waiting for {v1} to appear on {v2}. It learns the new address on its next sync, checks that panel's identity, and only then moves — so until it does, it is still fully yours.":
    "Ждём, когда {v1} появится на {v2}. Нода узнает новый адрес на ближайшей синхронизации, проверит подлинность той панели и только потом переедет — до этого она полностью ваша.",
  "The other panel isn't answering this panel right now ({v1}). The node will keep trying; nothing is lost while it can't get through.":
    "Та панель сейчас не отвечает этой ({v1}). Нода продолжит попытки; пока связи нет, ничего не теряется.",
  "{v1} is now reporting on {v2}. This panel has discarded the token it was given, and this node's record here is yours to keep or remove.":
    "{v1} теперь отчитывается на {v2}. Эта панель удалила выданный ей токен, а запись ноды здесь можно оставить для справки или удалить.",
  "Withdrawing takes the address back. The node never left, so there is nothing to roll back — it simply stops being offered somewhere else.":
    "Отзыв забирает адрес обратно. Нода никуда не уходила, откатывать нечего — ей просто перестают предлагать переезд.",
  "Withdraw the transfer": "Отозвать передачу",
  "Transfer withdrawn — the node stays on this panel.": "Передача отозвана — нода остаётся на этой панели.",
  "Clear this": "Убрать",
  "Cleared.": "Убрано.",
  "couldn't cancel": "не удалось отменить",
  "another panel": "другая панель",
  "the other panel": "другая панель",

  // The badges. Pending borrows the superseded colour — both mean "something out there this panel no
  // longer fully owns"; done is neutral.
  "tag|transferring": "передаётся",
  "tag|transferred": "передана",
  "tag|arrived here": "пришла сюда",
  "tag|unclaimed": "нет записи",
  "Being handed to {v1}. It keeps syncing here until that panel answers it, so nothing has moved yet.":
    "Передаётся на другую панель: {v1}. Пока та панель не ответит, нода синхронизируется здесь — ничего ещё не переехало.",
  "This node now reports to {v1}. Its record here no longer controls it — keep it for reference, or remove it.":
    "Нода теперь синхронизируется с другой панелью: {v1}. Запись здесь ею больше не управляет — оставьте для справки или удалите.",

  // ── T-10, server side ───────────────────────────────────────────────────────────────────────────
  "that is a declarative (NixOS) enrolment — it writes the token to a file and carries no -key, so there is nothing here to read. On the target panel add a NEW node: its Add node screen gives a one-line command that carries both the address and the token.":
    "это декларативное (NixOS) подключение — токен пишется в файл, а -key в команде нет, так что читать здесь нечего. Добавьте на той панели НОВУЮ ноду: её экран «Добавить ноду» даёт однострочную команду с адресом и токеном.",
  "that command enrols a node on THIS panel — paste the one the OTHER panel shows under Add node":
    "эта команда подключает ноду к ЭТОЙ панели — вставьте ту, которую показывает ДРУГАЯ панель в «Добавить ноду»",
  "a transfer of this node is already in flight — cancel it first":
    "передача этой ноды уже идёт — сначала отмените её",
  "this node isn't reporting, so there is no way to tell it where to go. Bring it back first, or use Restore or migrate to rebuild it.":
    "нода не выходит на связь, поэтому сообщить ей новый адрес нечем. Сначала верните её в строй или пересоберите через «Восстановить или перенести».",
  "no transfer in flight for this node": "для этой ноды нет активной передачи",
  "no transfer to cancel": "отменять нечего",
  "the target panel presented a different certificate than the one this transfer started against":
    "та панель предъявила не тот сертификат, с которого началась эта передача",
  "that token belongs to a node that is already set up here — add a NEW node on this panel and transfer to that one":
    "этот токен принадлежит ноде, которая здесь уже настроена — добавьте на этой панели НОВУЮ ноду и передавайте на неё",
  "a different node with the same id already exists on this panel — it cannot take this one's place":
    "нода с таким id на этой панели уже есть, и занять её место нельзя",
  "the bundle names no node": "в пакете не указана нода",
  "unsupported transfer format": "неподдерживаемый формат передачи",
  "this panel can't reach {v1}: {v2}": "эта панель не может связаться с {v1}: {v2}",
  "the target panel refused the transfer: {v1}": "та панель отклонила передачу: {v1}",
  "this node's users, peers and stored configs come to {v1} MB, which is more than a panel will accept in one transfer. Move some of its peers to another node first, or transfer with config storage turned off.":
    "пользователи, пиры и сохранённые конфиги этой ноды занимают {v1} МБ — больше, чем панель примет за одну передачу. Перенесите часть её пиров на другую ноду или передавайте с выключенным хранением конфигов.",
  "this panel already holds different records under {v1}":
    "на этой панели уже есть другие записи с идентификаторами {v1}",

  // Russian leads with the predicate here — "3 обновления доступно" reads as a fragment, "Доступно 3 обновления" does not.
  "{v1} available": "Доступно {v1}",
  "Review & update": "Просмотреть и обновить",
  "Server updates": "Обновления серверов",
  "Update all": "Обновить все",
  "This peer's address on the RAW datapath — it holds both at once": "Адрес этого пира в RAW-датапате — он держит оба одновременно",
  "Using the panel's fallback VK call link.": "Используется запасная VK-ссылка панели.",
  "Deployed servers on this node are behind their newest build — review and update": "Развёрнутые на этом узле серверы отстают от новейшей сборки — просмотреть и обновить",
  "Each update swaps the server's binary and *restarts it*, which briefly drops that server's clients. This one covers {v1} on {v2} — pick a quiet moment, or update them one at a time.": "Каждое обновление подменяет бинарник сервера и *перезапускает его*, из-за чего клиенты этого сервера ненадолго отключаются. Здесь это {v1} на {v2} — выберите спокойное время или обновляйте по одному.",
  "Update {v1}": "Обновить {v1}",   // the per-fork button: {v1} is already declined ("2 ноды")
  "Update": "Обновить",
  "Everything is on its newest build.": "Все серверы на новейшей сборке.",
  "Each update swaps the server's binary and *restarts it*, which briefly drops that server's clients. This one covers {v1} across {v2} — pick a quiet moment, or update them one at a time.":
    "Каждое обновление заменяет бинарник сервера и *перезапускает его*, что ненадолго отключает клиентов этого сервера. Здесь это {v1} на {v2} — выберите тихое время или обновляйте по одному.",

  "Relay": "Релей",
  "No interface on this link can be relayed": "Ни один интерфейс на этой связи нельзя перевести в релей",
      "col|State": "Состояние",
  "relaying": "релей работает",
  "not relaying": "релей не работает",
  "Reason": "Причина",
  "waiting for the node": "ждём ноду",
  "Carried": "Передано",
  "*{v1}* can't be relayed — {v2}. It keeps forwarding.": "*{v1}* нельзя перевести в релей — {v2}. Остаётся на пересылке.",
  "CPU cap": "Лимит CPU",
  "CPU cap must be between {v1} and {v2}": "Лимит CPU должен быть от {v1} до {v2}",
    "Saving this drops every TCP connection currently crossing this link. Clients reconnect on their own.": "Сохранение оборвёт все TCP-соединения, идущие сейчас через этот тоннель. Клиенты переподключатся сами.",
  "{v1}% enforced, {v2}% set": "{v1}% применяется, задано {v2}%",
    "Forward": "Транзит",
  "Packets cross this link untouched. The simplest and cheapest option — *{node}* barely spends CPU on them and there is nothing in the path to fail. Right while the link to {peer} is healthy.": "Пакеты проходят через тоннель как есть, нода их не трогает. Самый простой и дешёвый вариант: *{node}* почти не тратит на них CPU, и ломаться по пути нечему. То, что нужно, пока связь с {peer} работает нормально.",
  "*{node}* answers the client itself and opens its own connection to {peer}. Loss on the link stops reaching the client, so a bad leg costs the user far less. In exchange it uses noticeably more CPU, and on a link that is already healthy it buys nothing. The cap is {node}'s whole relay budget, shared by every leg it accelerates.": "*{node}* сам отвечает клиенту и открывает до {peer} отдельное соединение. Потери на связи дальше клиента не идут, поэтому плохое плечо бьёт по пользователю намного слабее. Взамен заметно растёт нагрузка на CPU, а на хорошей связи выигрыша не будет. Лимит — это весь релейный бюджет {node}, общий для всех плеч, которые он ускоряет.",
      "{v1} configs are published again — saved.": "Конфиги {v1} снова публикуются — сохранено.",
  "{v1} configs hidden from the subscription — saved.": "Конфиги {v1} скрыты из подписки — сохранено.",
  "Routes": "Маршрутизирует",
  "Overlaps": "Пересечения",
  "IP ranges, networks (AS)": "Диапазоны IP, сети (AS)",
  "IP ranges, networks, sites, zones": "Диапазоны IP, сети, сайты, зоны",
  "IP ranges, networks, sites (as text), text patterns": "Диапазоны IP, сети, сайты (как текст), текстовые шаблоны",
  "IP ranges, networks, sites, zones, name patterns, text patterns": "Диапазоны IP, сети, сайты, зоны, шаблоны имён, текстовые шаблоны",
  "First match — the order you set": "Первое совпадение — в заданном вами порядке",
  "Most specific name; IP rules in order": "Самое точное имя; правила по IP — по порядку",
  "The node becomes your clients' resolver: it answers their plain DNS and routes by the hostnames it sees, per-service precise. Trade-off: it sees and downgrades the client's DNS. A client that uses its own encrypted DNS (DoH or DoT) goes unseen — its hostname rules don't match, though rules by IP still route — so the panel marks that device instead of cutting its DNS off. To stop encrypted DNS, turn on the interface's DoH / DoT / DoQ block: it drops known DoH providers and all DoT, a DoH server it doesn't recognise can still slip past, and a client whose only resolver is encrypted stops resolving. A client answering from its own cache never asks, so a rule you add after it looked a name up takes effect on its next lookup — the node caps what clients may keep at 60 seconds for exactly that reason.":
    "Нода становится резолвером клиентов: отвечает на их обычный DNS и маршрутизирует по именам хостов, которые видит, точно до сервиса. Плата: она видит и понижает DNS клиента. Клиент со своим шифрованным DNS (DoH или DoT) остаётся ей невидим — его правила по имени хоста не срабатывают, хотя правила по IP работают, — поэтому панель помечает такое устройство, а не отрезает ему DNS. Чтобы остановить шифрованный DNS, включите на интерфейсе блокировку DoH / DoT / DoQ: она режет DoH известных провайдеров и весь DoT, незнакомый ей DoH-сервер всё же проскочит, а клиент, у которого есть только шифрованный резолвер, перестанет разрешать имена. Клиент, отвечающий из собственного кэша, вообще не спрашивает, поэтому правило, добавленное после того как он разрешил имя, сработает лишь на следующем запросе — именно поэтому нода ограничивает срок хранения ответа у клиента 60 секундами.",
  "Scans the SNI from each TLS handshake entirely in the kernel (xt_string) and learns each destination's IP into the routing set — no userspace helper, and your clients' DNS (DoH, DoT or plain) is never touched. Runs in parallel across CPUs, so it stays light even at high connection rates. Needs the node's kernel to provide xt_string + ipset. It matches a run of characters, not a name: a rule for example.com also matches notexample.com.evil.net, which is why whole-ending rules like *.ru cannot be matched here at all — this node counts them and says so, so you can move them to Force-DNS or Hybrid SNI. Learns each destination on its first connection, which still leaves by the route it would have taken without the rule (a brand-new host routes on the next one); names hidden by ECH, and QUIC / HTTP3, fall back to IP routing.": "Читает SNI из каждого TLS-рукопожатия целиком в ядре (xt_string) и запоминает IP каждого назначения в маршрутный набор — без помощника в userspace, и DNS клиентов (DoH, DoT или обычный) не трогается вовсе. Работает параллельно по ядрам, поэтому остаётся лёгким даже при большом числе соединений. Требует xt_string и ipset в ядре ноды. Совпадает по последовательности символов, а не по имени: правило для example.com совпадёт и с notexample.com.evil.net — поэтому правила на целое окончание вроде *.ru здесь не сопоставляются вовсе — нода их считает и сообщает об этом, чтобы вы перевели их на Force-DNS или Hybrid SNI. Узнаёт каждое назначение на первом соединении, которое ещё уходит тем путём, каким ушло бы без правила (совсем новый хост маршрутизируется со следующего); имена, скрытые ECH, а также QUIC / HTTP3 уходят на маршрутизацию по IP.",
  "Open {v1} and its routing rules": "Открыть {v1} и её правила маршрутизации",
  "Held on this node, but no rule on it names this list.": "Держится на этой ноде, но ни одно её правило этот список не называет.",
  "not used here": "здесь не используется",
  "held on this node, and the interfaces that ask for them": "держатся на этой ноде — и интерфейсы, которые их просят",
  "A leftover pin — no rule names this list. Clear it from every node.": "Остался закреплённым — ни одно правило его не называет. Убрать со всех нод.",
  "Nothing held here yet. Lists arrive on their own when an interface's routing rule names one — add them in *Interfaces*, on the interface that needs them.": "Пока ничего не держится. Списки появляются сами, когда правило интерфейса называет один из них — добавляйте их в *Интерфейсах*, на том интерфейсе, которому они нужны.",
  "one set of addresses, reused by rules on any node — edited in one place":
    "один набор адресов, используемый правилами на любой ноде — правится в одном месте",
  "No lists yet. Worth making when the same addresses are wanted by more than one rule — otherwise type them straight into the rule.":
    "Списков пока нет. Стоит завести, когда одни и те же адреса нужны нескольким правилам — иначе впишите их прямо в правило.",
  "Edit this list": "Изменить список",
  // §5.4: a list whose every token was unreadable is not shortened, it is GONE — its own sentence
  "the list {v1} had nothing readable in it — not saved": "в списке {v1} не оказалось ничего читаемого — не сохранён",
  "Show as text — copy it out, paste it in, or edit every target at once": "Показать текстом — скопировать, вставить или отредактировать все адреса сразу",
  // the labelled foot toggle (custom-list sheet) — a pair, so the label always says where you are going
  "Show text": "Текстом",
  "Show badges": "Значками",
  "Targets, one per line": "Адреса, по одному в строке",
  "One target per line — example.com, *.ru, 10.0.0.0/8, AS13335": "По одному адресу в строке — example.com, *.ru, 10.0.0.0/8, AS13335",
  "{v1} in this rule": "{v1} в этом правиле",
  "Rule emptied.": "Правило очищено.",
  "Text discarded — the rule is unchanged.": "Текст отброшен — правило не изменилось.",
  "Back to badges — reads every line and turns it into a target. Escape discards instead.": "Обратно в плашки — каждая строка станет адресом. Escape — отбросить.",
  "No list called {v1} on this panel": "На этой панели нет списка {v1}",
  "Add this list to the rule": "Добавить этот список в правило",
  "{v1} list — the panel resolves it and every node routing it pulls the same copy.": "Список {v1} — панель его разворачивает, и каждая нода, которая его маршрутизирует, тянет одну и ту же копию.",
  "Unknown list": "Неизвестный список",
  "No list with this id — its provider may be switched off in Settings, or the list was withdrawn upstream. The rule keeps it, and it matches nothing until it comes back.": "Списка с таким id нет — возможно, его источник выключен в настройках или список убрали на стороне провайдера. Правило его сохраняет, но совпадать он не будет, пока не вернётся.",
  // A LIST badge: «список … не найден» — masculine, unlike the bare "not found" ("не найдено") used
  // for an ASN lookup, which is why this one is namespaced rather than sharing that key.
  "list|not found": "не найден",
  "list|empty": "пусто",
  "The panel resolved this list and it holds nothing — check the id, or the source may have emptied it.": "Панель развернула этот список, и в нём ничего нет — проверьте id или источник мог его опустошить.",
  "Edit discarded — {v1} is unchanged": "Правка отменена — {v1} без изменений",
  // ── server sentences that reached the browser in English (G7) ──
  "%s: %s needs a domain URL, not an IP address.": "%s: для %s нужен URL с доменом, а не IP-адрес.",
  "%s: port %d can't be reached behind Cloudflare — a cf15 origin cert is only valid there. Use one of: %s.": "%s: порт %d недоступен через прокси Cloudflare — сертификат cf15 действует только там. Используйте один из: %s.",
  "%s: port must be a number between 1 and 65535.": "%s: порт должен быть числом от 1 до 65535.",
  "Added a pool VK link": "Добавлена ссылка VK в пул",
  "Captured node fingerprint": "Снят отпечаток ноды",
  "Changed deployment settings": "Изменены настройки развёртывания",
  "Cloudflare Origin (cf15) TLS needs a Cloudflare Origin CA token (Zone:SSL + Certificates:Edit) — add it before switching.": "Для TLS Cloudflare Origin (cf15) нужен токен Origin CA (Zone:SSL + Certificates:Edit) — добавьте его до переключения.",
  "Cloudflare TLS needs a Cloudflare DNS API token (Zone:DNS:Edit + Zone:Read) — add it before switching, otherwise it issues a self-signed certificate Cloudflare rejects (526).": "Для TLS Cloudflare нужен токен DNS API (Zone:DNS:Edit + Zone:Read) — добавьте его до переключения, иначе будет выпущен самоподписанный сертификат, который Cloudflare отклонит (526).",
  "Debug": "Отладка",
  "Disable DTLS": "Отключить DTLS",
  "Dismissed the transfer note": "Скрыто уведомление о переносе",
  "Imported user from a server the node runs": "Импортирован пользователь с сервера, который держит нода",
  "Interface came back different from the request": "Интерфейс вернулся не таким, каким его запросили",
  "Manual Captcha": "Ручная капча",
  "Panel and subscription are on the same host and port but different paths — two separate servers can't share host:port. Use a different subdomain or a different port.": "Панель и подписка на одном хосте и порту, но с разными путями — два отдельных сервера не могут делить host:port. Возьмите другой поддомен или другой порт.",
  "Panel and subscription can't share the same address and port (%s:%d).": "Панель и подписка не могут делить один адрес и порт (%s:%d).",
  "Panel: with direct TLS (mode “%s”) the panel is reached directly, so it can't listen on %s (loopback) — it wouldn't be reachable from outside (Cloudflare/clients get 521). Use 0.0.0.0 or a public IP. Loopback is only valid behind a reverse proxy (TLS mode “None”).": "Панель: при прямом TLS (режим «%s») к панели обращаются напрямую, поэтому она не может слушать %s (loopback) — снаружи её будет не достать (Cloudflare и клиенты получат 521). Возьмите 0.0.0.0 или публичный IP. Loopback имеет смысл только за обратным прокси (режим TLS «Нет»).",
  "Received transferred node": "Принята перенесённая нода",
  "Reclaimed a %s server": "Возвращён сервер %s",
  "Reinstalling csqtt": "Переустановка csqtt",
  "Restoring an exit key from the vault": "Восстановление ключа выхода из хранилища",
  "Kept the exit's new key and forgot the previous one": "Оставлен новый ключ выхода, прежний забыт",
  "Rolling back csqtt": "Откат csqtt",
  "Starting interface": "Запуск интерфейса",
  "The local-node port %d clashes with the panel/subscription port — pick a distinct, free loopback port for the co-located node.": "Порт локальной ноды %d конфликтует с портом панели или подписки — выберите для неё отдельный свободный loopback-порт.",
  "Transfer cancelled": "Перенос отменён",
  "Transfer started": "Перенос начат",
  "Transferred": "Перенесено",
  "Updating csqtt to latest": "Обновление csqtt до последней версии",
  "VK bypass": "Обход VK",
  "VK pool changed — reassigned %d user(s)": "Пул VK изменён — переназначено пользователей: %d",
  "VK links per new user: %d → %d": "VK-ссылок новому пользователю: %d → %d",
  "Verified the escrowed key opens": "Проверено, что депонированный ключ открывается",
  "bad device name": "неверное имя устройства",
  "bad host": "неверный хост",
  "exit device refused: ": "устройство выхода отклонено: ",
  "family must be iface or wdtt": "family должен быть iface или wdtt",
  "family must be wdtt or csqtt": "family должен быть wdtt или csqtt",
  "keepalive must be 0-65535": "keepalive должен быть от 0 до 65535",
  "keepalive must be a number": "keepalive должен быть числом",
  "key escrow is not enabled on this panel": "депонирование ключей на этой панели не включено",
  "mtu must be 576-9200": "mtu должен быть от 576 до 9200",
  "no escrowed key for {v1} to verify": "для {v1} нет депонированного ключа, который можно проверить",
  "not JSON": "не JSON",
  "not a sealed key": "не запечатанный ключ",
  "paste the target panel's transfer token (or its enrolment command)": "вставьте токен переноса целевой панели (или её команду подключения)",
  "pool must be a list": "пул должен быть списком",
  "relay_mode must be {v1} or {v2}": "relay_mode должен быть {v1} или {v2}",
  "relay_quota_pct must be a whole number of percent": "relay_quota_pct должен быть целым числом процентов",
  "relay_quota_pct must be between {v1} and {v2}": "relay_quota_pct должен быть от {v1} до {v2}",
  "role must be primary, backup, or empty": "role должен быть primary, backup или пустым",
  "subnet must be an IPv4 CIDR (e.g. 10.66.70.1/24)": "подсеть должна быть IPv4 CIDR (например, 10.66.70.1/24)",
  "that enrolment command carries no -key and -host pair — copy the whole line. Simpler: paste the other panel's Transfer token instead.": "в этой команде подключения нет пары -key и -host — скопируйте строку целиком. Проще: вставьте токен переноса с другой панели.",
  "that is neither a transfer token nor an enrolment command. On the other panel: Nodes -> Add node, and copy the Transfer token it shows.": "это не токен переноса и не команда подключения. На другой панели: Ноды → Добавить ноду, и скопируйте показанный токен переноса.",
  "that looks like a transfer token but this panel cannot read it — copy it again from the other panel's Add node screen, whole and unaltered.": "похоже на токен переноса, но эта панель не может его прочитать — скопируйте его заново с экрана «Добавить ноду» другой панели, целиком и без изменений.",
  "that transfer token carries no usable node key — copy it again": "в этом токене переноса нет пригодного ключа ноды — скопируйте его заново",
  "that transfer token carries no usable panel address: %r": "в этом токене переноса нет пригодного адреса панели: %r",
  "that transfer token is damaged — copy it again from the other panel": "этот токен переноса повреждён — скопируйте его заново с другой панели",
  "that version isn't a published csqtt build": "это не опубликованная сборка csqtt",
  "the -host in that command isn't a usable address: %r": "-host в этой команде не является пригодным адресом: %r",
  "the node reports no usable subnet for {v1}": "нода не сообщает пригодной подсети для {v1}",
  "the target panel didn't recognise that token — it may have been rotated, or it may belong to a different panel than the address it carries": "целевая панель не признала этот токен — возможно, он был перевыпущен или принадлежит не той панели, чей адрес несёт",
  "there is no mesh to re-provision — this fleet has one node": "перевыпускать нечего — во флоте одна нода",
  "there is no superseded box to roll back to": "нет заменённого сервера, к которому можно откатиться",
  "this node already manages {v1}": "эта нода уже управляет {v1}",
  "this node doesn't report a {v1} server on {v2} — refresh and try again": "эта нода не сообщает о сервере {v1} на {v2} — обновите и попробуйте снова",
  "unknown congestion control {v1}": "неизвестный контроль перегрузки {v1}",
  "unknown csqtt instance": "неизвестный экземпляр csqtt",
  "unknown interface": "неизвестный интерфейс",
  "unknown mode": "неизвестный режим",
  "unknown operation": "неизвестная операция",
  "{v1} isn't a usable host or address": "{v1} не является пригодным хостом или адресом",

  // ── the VK TURN Proxy import hint: four finished sentences, one per (launcher × vk-missing) ──
  "Import the {v1} core (client-android-arm64 from the {v1} releases) into the VK TURN Proxy app — it runs as a launcher for that core, then scan the QR (Profiles → Import) or paste the VKTGZ: text — the VK call link + endpoint ride inside once you add a VK link.": "Импортируйте ядро {v1} (client-android-arm64 из релизов {v1}) в приложение VK TURN Proxy — оно работает как лаунчер для этого ядра, затем отсканируйте QR (Профили → Импорт) или вставьте текст VKTGZ: — ссылка на звонок VK и эндпоинт едут внутри, как только вы добавите ссылку VK.",
  "Import the {v1} core (client-android-arm64 from the {v1} releases) into the VK TURN Proxy app — it runs as a launcher for that core, then scan the QR (Profiles → Import) or paste the VKTGZ: text — the VK call link + endpoint ride inside.": "Импортируйте ядро {v1} (client-android-arm64 из релизов {v1}) в приложение VK TURN Proxy — оно работает как лаунчер для этого ядра, затем отсканируйте QR (Профили → Импорт) или вставьте текст VKTGZ: — ссылка на звонок VK и эндпоинт едут внутри.",
  "Import the {v1} core (client-android-arm64 from the {v1} releases) into the VK TURN Proxy app, then scan the QR (Profiles → Import) or paste the VKTGZ: text — the VK call link + endpoint ride inside once you add a VK link.": "Импортируйте ядро {v1} (client-android-arm64 из релизов {v1}) в приложение VK TURN Proxy, затем отсканируйте QR (Профили → Импорт) или вставьте текст VKTGZ: — ссылка на звонок VK и эндпоинт едут внутри, как только вы добавите ссылку VK.",
  "Import the {v1} core (client-android-arm64 from the {v1} releases) into the VK TURN Proxy app, then scan the QR (Profiles → Import) or paste the VKTGZ: text — the VK call link + endpoint ride inside.": "Импортируйте ядро {v1} (client-android-arm64 из релизов {v1}) в приложение VK TURN Proxy, затем отсканируйте QR (Профили → Импорт) или вставьте текст VKTGZ: — ссылка на звонок VK и эндпоинт едут внутри.",

  // ── an exit whose device is up but whose peer never answered ──
  "The device is up, but this peer has never answered. Check the endpoint and the keys — and if the server is AmneziaWG, its profile must be pasted with its obfuscation lines intact.": "Устройство поднято, но этот пир ни разу не ответил. Проверьте эндпоинт и ключи — а если сервер AmneziaWG, его профиль нужно вставлять вместе со строками обфускации.",
  "The device is up, but this peer has never answered. Check the endpoint, the keys, and that the server really is AmneziaWG with these exact obfuscation values.": "Устройство поднято, но этот пир ни разу не ответил. Проверьте эндпоинт, ключи и то, что сервер действительно AmneziaWG именно с этими параметрами обфускации.",
  "Latency": "Задержка",
  "{v1} ms": "{v1} мс",
  "Show the reason": "Показать причину",
  "This exit isn't working": "Этот выход не работает",
  "The node reports: {v1}": "Нода сообщает: {v1}",
  // Sentences swg-noded puts in an exit's `error`, shown verbatim by exitHealth. Sentence-as-key, like the
  // panel's own server messages — T() returns any it does not know unchanged.
  "the escrowed key did not open — it may be sealed to a different vault": "запечатанный ключ не открылся — возможно, он запечатан под другое хранилище",
  "tls fingerprint mismatch": "отпечаток TLS не совпадает",
  "unusable device name": "недопустимое имя устройства",
  "binary download failed": "не удалось скачать бинарник",
  "agent non-JSON": "агент ответил не JSON",
  "The escrowed key could not be put back — the node has kept the one it has.": "Ключ из хранилища вернуть не удалось — нода оставила тот, что у неё есть.",
  "It reports: {v1}": "Она сообщает: {v1}",
  "Try again from a browser that can open the vault; if this node was rebuilt since the key was sealed, the escrow has to be re-sealed to it.": "Повторите из браузера, который может открыть хранилище; если ноду пересобирали после запечатывания ключа, хранилище нужно перезапечатать под неё.",
  "Round trip from this node to the exit's own server.": "Круговая задержка от этой ноды до собственного сервера выхода.",
  "Round trip from this node to the exit's own server. A request through the tunnel to a public site takes {v1} ms, which also includes however far that site is.": "Круговая задержка от этой ноды до собственного сервера выхода. Запрос через туннель к публичному сайту занимает {v1} мс — но туда входит и то, насколько далёк сам сайт.",
  // ── AmneziaWG 3.1 (docs/AWG3-PLAN.md §7.7): the version switch, its window, the 3.1 badges' tooltip, the Settings preset ──
  "AmneziaWG 3.1": "AmneziaWG 3.1",
  "val|set": "задан",
  "val|new on switch": "новый при переключении",
  "Only apps that carry AmneziaWG 3.1 can connect: Amnezia VPN 5.0.1.5 or newer, AmneziaWG from the App Store or from GitHub (not the Google Play build), WG Tunnel 5.6 or newer. WINGS V, Keenetic and MikroTik cannot.": "Подключатся только приложения с поддержкой AmneziaWG 3.1: Amnezia VPN 5.0.1.5 и новее, AmneziaWG из App Store или с GitHub (не сборка из Google Play), WG Tunnel 5.6 и новее. WINGS V, Keenetic и MikroTik — нет.",
  "AmneziaWG version": "Версия AmneziaWG",
  "Every AmneziaWG app can connect.": "Подходит любое приложение AmneziaWG.",
  "Devices on {v1}": "Устройства на {v1}",
  "Filter by device, user or address…": "Устройство, пользователь или адрес…",
  "tag|gateway": "шлюз",
  "No device matches “{q}”.": "Нет устройств под «{q}».",
  "No device is on this interface.": "На этом интерфейсе нет устройств.",
  "Switch {v1} to AmneziaWG 3.1": "Перевести {v1} на AmneziaWG 3.1",
  "Switch {v1} back to AmneziaWG 2.0": "Вернуть {v1} на AmneziaWG 2.0",
  "A turn proxy whose app carries AmneziaWG 2.0 only points here": "Сюда указывает turn-прокси, приложение которого понимает только AmneziaWG 2.0",
  "Switch to 3.1": "Перевести на 3.1",
  "Switch back to 2.0": "Вернуть на 2.0",
  "Network gateways on {v1} — the networks behind each one go dark until it imports the new config:": "Шлюзы сетей на {v1} — сети за каждым из них пропадут, пока он не импортирует новый конфиг:",
  "The panel refuses this switch while these turn proxies point at {v1} — their app carries AmneziaWG 2.0 only:": "Панель откажет в переключении, пока эти turn-прокси указывают на {v1} — их приложение понимает только AmneziaWG 2.0:",
  "Point each at a 2.0 interface, or delete it, and switch once the node has applied that.": "Направьте каждый на интерфейс 2.0 или удалите его и переключайте, когда нода это применит.",
  "Every device on {v1} needs the new config and cannot connect until it imports it.": "Каждому устройству на {v1} нужен новый конфиг — до его импорта оно не подключится.",
  "Affected: {v1} of {v2}.": "Затронуто: {v1} у {v2}.",
  "Affected: {v1}.": "Затронуто: {v1}.",
  "No device is on this interface yet — nothing to re-import.": "На этом интерфейсе пока нет устройств — импортировать заново нечего.",
  "Turn proxies forwarding here: {v1} — their links carry the new config, and their users re-import it too.": "Turn-прокси, ведущие сюда: {v1} — их ссылки несут новый конфиг, и их пользователям тоже нужно импортировать его заново.",
  "Subscription pages and the panel's QR codes show the new config at once; each device still has to import it.": "Страницы подписки и QR-коды панели сразу показывают новый конфиг; импортировать его каждому устройству всё равно нужно.",
  "One of S1–S4 is below 12, which header protection refuses — the switch draws new ones.": "Одно из значений S1–S4 меньше 12, а защита заголовков такого не принимает — переключение задаст новые.",
  "{v1} is not reporting — the switch applies when it is back. Until then its clients keep working on the old config, and new QR codes already show the new one.": "{v1} не выходит на связь — переключение применится, когда она вернётся. До тех пор её клиенты работают на старом конфиге, а новые QR-коды уже показывают новый.",
  "AmneziaWG version for new interfaces": "Версия AmneziaWG для новых интерфейсов",
  "Where the create form's switch starts. A node that cannot run 3.1 starts on 2.0, and existing interfaces keep their version.": "С какой версии начинает переключатель в форме создания. На ноде, которая не умеет 3.1, он начинает с 2.0, а существующие интерфейсы сохраняют свою версию.",
  // …and the panel's own sentences for it (P1 + P2: the refusals and the checks a 3.1 save makes). Counts never lead a verb.
  "HeaderProtectionKey must be a 32-byte key in base64, not all zeros": "HeaderProtectionKey должен быть 32-байтовым ключом в base64, не из одних нулей",
  "RekeyAfterTime + RekeyTimeout + KeepaliveTimeout (up to {v1} s) must not exceed RejectAfterTime ({v2} s at least) — the node would drop data a client still sends": "RekeyAfterTime + RekeyTimeout + KeepaliveTimeout (до {v1} с) не должны превышать RejectAfterTime (не меньше {v2} с) — иначе нода будет отбрасывать данные, которые клиент ещё отправляет",
  "awg_gen must be \"2.0\" or \"3.1\"": "awg_gen должен быть \"2.0\" или \"3.1\"",
  "{v1} cannot run AmneziaWG 3.1 while a turn proxy whose app carries AmneziaWG 2.0 only points at its port: {v2}. Point it at a 2.0 interface, or delete it, and try again once the node has applied that": "{v1} не может работать на AmneziaWG 3.1, пока на его порт указывает turn-прокси, приложение которого понимает только AmneziaWG 2.0: {v2}. Направьте его на интерфейс 2.0 или удалите и повторите, когда нода это применит",
  "{v1} is a mesh link — mesh links stay AmneziaWG 2.0": "{v1} — связь mesh, а связи mesh остаются на AmneziaWG 2.0",
  "{v1} is a plain WireGuard interface — only an AmneziaWG interface can switch to AmneziaWG 3.1": "{v1} — интерфейс обычного WireGuard; на AmneziaWG 3.1 можно перевести только интерфейс AmneziaWG",
  "{v1} must be 12 or more while header protection is on": "{v1}: при включённой защите заголовков нужно 12 или больше",
  "{v1} must be a number or a range like 10-100": "{v1}: нужно число или диапазон вроде 10-100",
  "{v1} must be on or off": "{v1}: нужно on или off",
  "{v1} proxies cannot point at {v2}: it runs AmneziaWG 3.1, and their app ({v3}) carries AmneziaWG 2.0 only — point it at a 2.0 interface": "Прокси {v1} не могут указывать на {v2}: он работает на AmneziaWG 3.1, а их приложение ({v3}) понимает только AmneziaWG 2.0 — направьте прокси на интерфейс 2.0",
  "{v1}: its AmneziaWG kernel module is {v2} — an AmneziaWG 3.1 interface needs 3.1": "{v1}: модуль ядра AmneziaWG здесь версии {v2}, а интерфейсу AmneziaWG 3.1 нужен 3.1",
  "{v1}: its awg tools are AmneziaWG {v2} — an AmneziaWG 3.1 interface needs 3.1": "{v1}: утилиты awg здесь версии AmneziaWG {v2}, а интерфейсу AmneziaWG 3.1 нужны 3.1",
  "{v1}: its userspace AmneziaWG (amneziawg-go), which this interface would run on, is {v2} — an AmneziaWG 3.1 interface needs 3.1": "{v1}: пользовательский AmneziaWG (amneziawg-go), на котором работал бы этот интерфейс, версии {v2}, а интерфейсу AmneziaWG 3.1 нужен 3.1",
  "{v1}: this node does not report its AmneziaWG version — update it": "{v1}: нода не сообщает свою версию AmneziaWG — обновите её",
  "{v1} serves an app that carries AmneziaWG 2.0 only — AmneziaWG 3.1 interfaces are hidden.": "Прокси {v1} обслуживают приложение, которое понимает только AmneziaWG 2.0, — интерфейсы AmneziaWG 3.1 скрыты.",
  "{v1} runs AmneziaWG 3.1, and this proxy's app carries AmneziaWG 2.0 only — its clients cannot connect. Point it at a 2.0 interface.": "Интерфейс {v1} на AmneziaWG 3.1, а приложение этого прокси понимает только AmneziaWG 2.0 — его клиенты не подключатся. Направьте прокси на интерфейс 2.0.",
  "tag|2.0 app": "приложение 2.0",
  "Waiting for the node to apply it — until then its clients keep working on the old config, and new QR codes already show the new one.": "Ждём, пока нода применит переключение, — до тех пор её клиенты работают на старом конфиге, а новые QR-коды уже показывают новый.",
  "tag|switching to 3.1": "переход на 3.1",
  "tag|switching to 2.0": "переход на 2.0",
  "tag|switching": "переход",
  "The panel's QR codes show the new config at once; each device still has to import it.": "QR-коды панели сразу показывают новый конфиг; импортировать его каждому устройству всё равно нужно.",
  // Settings → Interfaces: the AmneziaWG 3.1 defaults (the six values a 3.1 create or switch takes)
  "val|per interface": "свой у каждого",
  "Each interface gets a key of its own — one key shared by every interface would protect nothing.": "У каждого интерфейса свой ключ — один ключ на все интерфейсы ничего бы не защищал.",
  "On for every AmneziaWG 3.1 interface the panel sets up.": "Включено у каждого интерфейса AmneziaWG 3.1, который настраивает панель.",
  "Changes only through the version switch — every device has to re-import after it.": "Меняется только переключением версии — после него каждому устройству нужно заново импортировать конфиг.",
  "Given to an interface when it is created on 3.1 or switched to it; one already on 3.1 keeps its own. A blank cell is Amnezia's default.": "Их получает интерфейс, который создают на 3.1 или переводят на 3.1; интерфейс, уже работающий на 3.1, сохраняет свои. Пустая ячейка — значение Amnezia по умолчанию.",
  // Per-person rules (ROUTING-PEERS-MESH-PLAN §7.1–7.2, §7.4): a rule for chosen people, groups and devices
  "Rule settings": "Настройки правила",
  "Leaves by": "Выход через",
  "For whom": "Для кого",
  "Everyone on this interface": "Все на этом интерфейсе",
  "Chosen people and devices": "Выбранные люди и устройства",
  "Add a person, group or device…": "Добавить человека, группу или устройство…",
  "Devices here": "Устройства здесь",
  "col|User, group or device": "Пользователь, группа или устройство",
  "Can't be told apart on this build — the rule doesn't apply to it.": "На этой сборке это устройство не отличить от других — правило к нему не применяется.",
  "Not connected yet — the rule applies once it connects.": "Ещё не подключалось — правило заработает после подключения.",
  "None of the chosen people has a device on this interface — the rule routes nothing until one does.": "Ни у кого из выбранных нет устройства на этом интерфейсе — правило ничего не направляет, пока оно не появится.",
  "Choose at least one person or device, or pick “Everyone on this interface”.": "Выберите хотя бы одного человека или устройство либо «Все на этом интерфейсе».",
  "Kernel SNI on this node can't match hostnames for chosen people — only this rule's IP addresses and networks apply here. Switch to Hybrid SNI to match them.":
    "Kernel SNI на этом узле не умеет сопоставлять имена хостов для выбранных людей — здесь действуют только IP-адреса и сети этого правила. Переключите узел на Hybrid SNI, чтобы они работали.",
  "Kernel SNI matches site names only for rules that leave by an exit — this rule applies to the list's IP addresses and networks alone here. Switch to Hybrid SNI to match its sites.":
    "Kernel SNI сопоставляет имена сайтов только для правил, которые выпускают трафик через выход, — здесь это правило действует лишь на IP-адреса и сети списка. Переключите узел на Hybrid SNI, чтобы работали и его сайты.",
  "Kernel SNI matches site names only for rules that leave by an exit — a Direct or Block rule by site name does nothing here. Switch to Hybrid SNI to match them.":
    "Kernel SNI сопоставляет имена сайтов только для правил, которые выпускают трафик через выход, — правило «Напрямую» или «Заблокировать» по имени сайта здесь ничего не делает. Переключите узел на Hybrid SNI, чтобы они работали.",
  "{devices} not covered": "не охвачено: {devices}",
  "{devices} · {v1} not covered": "{devices} · не охвачено: {v1}",
  "{devices} in the rule": "в правиле: {devices}",
  "{v1} chosen": "Выбрано: {v1}",
  "Remove {name}": "Убрать {name}",
  "a device that no longer exists": "устройство, которого больше нет",
  // …and the panel's refusals and the node card's line for them
  "“For whom” must list users, groups or devices": "«Для кого» должно перечислять пользователей, группы или устройства",
  "“Everything else” applies to everyone on the interface": "«Всё остальное» действует на всех на интерфейсе",
  "A chosen user, group or device no longer exists — reload and choose again": "Выбранного пользователя, группы или устройства больше нет — перезагрузите страницу и выберите снова",
  "This browser tab is older than the panel — reload it before saving routing.": "Эта вкладка старее панели — перезагрузите её перед сохранением маршрутизации.",
  "{v1} needs an update to route per person — these rules apply to nobody there until it is.": "{v1} нужно обновить для маршрутизации по людям — до обновления эти правила там ни на кого не действуют.",
  "rows must be a list of selections": "rows должен быть списком выборок",
  // The exit IP (ROUTING-PEERS-MESH-PLAN §7.1–7.2, §7.4, D6): which of the far node's addresses this interface's traffic leaves it by
  "As address": "С адреса",
  "Auto ({v1}'s default)": "Авто (по умолчанию для {v1})",
  "Every rule that sends this interface through {v1} leaves as this address.": "Все правила, которые отправляют этот интерфейс через {v1}, выходят с этого адреса.",
  "Everything this interface sends straight out of {v1} leaves as this address.": "Всё, что этот интерфейс отправляет напрямую с {v1}, выходит с этого адреса.",
  "{v1} hasn't reported its addresses yet — type one it has, or leave this on Auto.": "{v1} ещё не сообщил свои адреса — введите один из его адресов или оставьте «Авто».",
  "{v1} isn't reporting this address. Traffic on this rule leaves it with a source it can't receive replies on, so it goes nowhere until the address is back or you choose another.":
    "{v1} не сообщает этот адрес. Трафик этого правила выйдет с адреса, на который узел не сможет получить ответы, и никуда не дойдёт, пока адрес не вернётся или пока вы не выберете другой.",
  "as {v1}": "с {v1}",
  // …and the panel's refusals for it
  "the exit address must be an IPv4 address": "адрес выхода должен быть адресом IPv4",
  "the exit address must name another node in this panel": "адрес выхода должен указывать на другой узел этой панели",
  "the exit addresses must be given per node": "адреса выхода должны задаваться по узлам",
  // The node's default made smart (ROUTING-PEERS-MESH-PLAN §7.3, §7.4, D2/D9/D11): one rule list for its own clients and the
  // traffic other nodes cascade out through it
  "Node default — then this node's {v1}": "Как у узла — затем {v1} этого узла",
  "This node's own clients": "Только клиенты этого узла",
  "Traffic cascaded in from other nodes": "Только трафик с других узлов",
  "All — this node's clients and traffic cascaded in": "Все — клиенты этого узла и трафик с других узлов",
  "chip|own clients": "свои клиенты",
  "chip|cascaded in": "с других узлов",
  "aud|Everyone": "Все",
  "aud|Own clients": "Свои клиенты",
  "aud|Cascaded in": "С других узлов",
  "Traffic that came from {node} skips this rule — it would go back where it came from.":
    "Трафик, пришедший с {node}, пропускает это правило — иначе он вернулся бы туда, откуда пришёл.",
  "Kernel SNI on this node can't match hostnames for traffic cascaded in — only IP addresses and networks apply to it.":
    "Kernel SNI на этом узле не умеет сопоставлять имена хостов для трафика с других узлов — к нему применяются только IP-адреса и сети.",
  "Every rule that sends {iface} through {node} leaves as {addr}.":
    "Все правила, которые отправляют {iface} через {node}, выходят с адреса {addr}.",
  "Every rule that sends {iface} through {node} leaves as {node}'s default address.":
    "Все правила, которые отправляют {iface} через {node}, выходят с адреса по умолчанию узла {node}.",
  "Everything {iface} sends straight out of {node} leaves as {addr}.":
    "Всё, что {iface} отправляет напрямую с {node}, выходит с адреса {addr}.",
  "Everything {iface} sends straight out of {node} leaves as {node}'s default address.":
    "Всё, что {iface} отправляет напрямую с {node}, выходит с адреса по умолчанию узла {node}.",
  "Every rule of this node's default that sends traffic through {node} leaves as {addr}.":
    "Все правила по умолчанию этого узла, которые отправляют трафик через {node}, выходят с адреса {addr}.",
  "Every rule of this node's default that sends traffic through {node} leaves as {node}'s default address.":
    "Все правила по умолчанию этого узла, которые отправляют трафик через {node}, выходят с адреса по умолчанию узла {node}.",
  "Routes {ifaces} here and the traffic {sources} send out through this node.":
    "Направляет {ifaces} этого узла и трафик, который {sources} выпускают через этот узел.",
  "{v1} arrive from two nodes at once and are left to this node's own route.":
    "{v1} приходят сразу с двух узлов и выходят по собственному маршруту этого узла.",
  "default routing rules": "правила маршрутизации по умолчанию",
  "a more specific rule in this node's default wins these hosts: {toks}": "в правилах этого узла по умолчанию есть более точное — эти адреса забирает оно: {toks}",
  "Then this node's default:": "Затем правила этого узла по умолчанию:",
  "a more specific rule below wins these hosts for the traffic it names: {toks}": "ниже есть более точное правило — для своего трафика эти адреса забирает оно: {toks}",
  "an exit": "выход",
  "default routing exit addresses": "адреса выхода для правил по умолчанию",
  // …and the panel's sentences for it
  "{node} needs an update to route traffic cascaded in by destination — until then it all leaves by {catch}.":
    "{node} нужно обновить для маршрутизации входящего трафика по направлениям — до обновления он весь выходит через {catch}.",
  "{v1} ({v2}) isn't sent to {v3}: {v4}, so replies couldn't find their way back. {v5}":
    "{v1} ({v2}) не отправляется на {v3}: {v4}, и ответы не смогли бы вернуться. {v5}",
  "{v1} there uses {v2}": "там {v1} использует {v2}",
  "{v1} on {v2} already sends it {v3}": "{v1} на {v2} уже отправляет туда {v3}",
  "Rules toward {v1} are skipped for {v2} until one of them gets a different subnet.":
    "Правила в сторону {v1} для {v2} пропускаются, пока одному из них не дадут другую подсеть.",
  "Forwarding is off for {v1}, so its traffic leaves by this server's own address until one of them gets a different subnet.":
    "Пересылка для {v1} выключена, и его трафик выходит с собственного адреса этого сервера, пока одному из них не дадут другую подсеть.",
  "traffic cascaded in": "трафик с других узлов",
  "{v1} and traffic cascaded in": "{v1} и трафик с других узлов",
  "this node's own address": "собственный адрес этого узла",
  "A node's default rules apply to its own clients or to traffic cascaded in, not to chosen people":
    "Правила узла по умолчанию действуют на его клиентов или на трафик с других узлов, а не на выбранных людей",
  "a rule's audience must be local or cascaded": "аудитория правила должна быть local или cascaded",
  "“Everything else” applies to both this node's clients and traffic cascaded in":
    "«Всё остальное» действует и на клиентов этого узла, и на трафик с других узлов",
};

/* Counted nouns. Russian selects between three forms by the last digit, with a correction for the
   teens (11–14 take the "many" form despite ending in 1–4) — see plural() in js/i18n.js.
   Order: [1 пир, 2 пира, 5 пиров]. */
export const PLURALS = {
  // The text view's line counter: «12 строк».
  line: ["строка", "строки", "строк"],
  // The rule field's cost meter: "4 entries · 1.2M names · 340k networks".
  entry: ["запись", "записи", "записей"],
  // A list's own size line, shown on every badge and every catalog row.
  host: ["домен", "домена", "доменов"],
  net: ["сеть", "сети", "сетей"],
  name: ["имя", "имени", "имён"],
  network: ["сеть", "сети", "сетей"],
  // The Tier-2 caution: «Всего 4 символа» — the count sits in front, so nominative is right.
  character: ["символ", "символа", "символов"],
  // §12.1's cap, and the node's truncation note. NOT `pattern` on its own: a zone is a pattern too and is
  // not counted here — only the three kinds matched as text are, which is what the limit is about.
  "text pattern": ["текстовый шаблон", "текстовых шаблона", "текстовых шаблонов"],
  // a LIST's own size line, which counts all six pattern kinds — not the three the cap above counts
  pattern: ["шаблон", "шаблона", "шаблонов"],
  // Genitive — this slot sits after «у» ("у 2 пользователей"), where the nominative "пользователя" is wrong.
  "gen|user": ["пользователя", "пользователей", "пользователей"],
  "dead VK link": ["мёртвая ссылка", "мёртвые ссылки", "мёртвых ссылок"],
  domain: ["домен", "домена", "доменов"],
  "threat-IP": ["опасный IP", "опасных IP", "опасных IP"],
  category: ["категория", "категории", "категорий"],
  "VK link": ["VK-ссылка", "VK-ссылки", "VK-ссылок"],
  peer: ["пир", "пира", "пиров"],
  link: ["связь", "связи", "связей"],
  node: ["нода", "ноды", "нод"],
  user: ["пользователь", "пользователя", "пользователей"],
  interface: ["интерфейс", "интерфейса", "интерфейсов"],
  "Auto interface": ["интерфейс на «Авто»", "интерфейса на «Авто»", "интерфейсов на «Авто»"],
  server: ["сервер", "сервера", "серверов"],
  update: ["обновление", "обновления", "обновлений"],
  // Prepositional case — this slot sits after «на» ("на 1 ноде"), where the nominative "нода" is wrong.
  // English has no entry, so plural() strips the prefix and still reads "1 node" / "2 nodes".
  "prep|node": ["ноде", "нодах", "нодах"],
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
  // Prepositional case — these two sit after «в» / «на» ("в 3 правилах на 2 интерфейсах"), where the
  // nominative "правила" / "интерфейса" is wrong. English has no entry, so plural() strips the prefix and
  // still reads "3 rules" / "2 interfaces".
  "prep|rule": ["правиле", "правилах", "правилах"],
  "prep|interface": ["интерфейсе", "интерфейсах", "интерфейсах"],
  IP: ["IP", "IP", "IP"],   // indeclinable acronym: one form covers every count
  issue: ["проблему", "проблемы", "проблем"],
  "nom|issue": ["проблема", "проблемы", "проблем"],   // SUBJECT ("1 проблема на этой ноде"); bare `issue` stays accusative for "исправить / можно починить"
  group: ["группа", "группы", "групп"],   // nominative: «Доступ: 2 группы» (user groups) and the attention list's own groups
  member: ["участник", "участника", "участников"],
  "cap|Member": ["участник", "участника", "участников"],   // the groups grid's count column: capitalised in English, ordinary in Russian   // a group's members — after a colon or a name, never a verb's subject
  person: ["человек", "человека", "человек"],        // how many PEOPLE a user's devices reach — «Доступны устройства: 2 человека»
  minute: ["минуты", "минут", "минут"],          // reads after "больше" (genitive): больше 1 минуты / 5 минут
  address: ["адрес", "адреса", "адресов"],
  "sub link": ["ссылка", "ссылки", "ссылок"],   // a subscription URL — NOT `link`, which is a mesh link ("связь")
  "broken address": ["неверный адрес", "неверных адреса", "неверных адресов"],
  config: ["конфиг", "конфига", "конфигов"],
  // The blocked-categories bubble: «5 сайтов». Was reaching pluralWord with no table at all, so it
  // rendered the English "s"-plural — invisible until the audit learned to see pluralWord() nouns.
  site: ["сайт", "сайта", "сайтов"],
  // A borrowed acronym does not decline in Russian — «1 vCPU», «8 vCPU» — so all three forms are equal.
  // Kept in the table anyway rather than special-cased in code: the noun table is where plural lives.
  vCPU: ["vCPU", "vCPU", "vCPU"],
  CPU: ["CPU", "CPU", "CPU"],
  // the port-scan tile: «3 источника · за 24 ч». Was "source" + (n===1?"":"s"), an English-only plural.
  source: ["источник", "источника", "источников"],   // T-10's transfer summary counts stored client configs

};
