# Стороннее программное обеспечение

· English: [THIRD-PARTY.md](THIRD-PARTY.md)

Сам swgPanel распространяется под MIT (см. [LICENSE](LICENSE)). При этом он **собирает, поставляет и запускает**
программы, написанные другими людьми, под их собственными лицензиями. Здесь сказано, что именно, под какой
лицензией и где исходники — в одном месте, чтобы это можно было проверить, не читая скрипты сборки.

Два пункта касаются того, что можете делать **вы**, а не только мы:

- **csqtt — только для некоммерческого использования.** Коммерческая эксплуатация сервера csqtt требует
  отдельной письменной лицензии от его автора. См. [csqtt](#csqtt-noncommercial) ниже.
- **Большинство форков WDTT — GPL-3.0.** Вы вправе использовать, изучать, изменять и распространять их, а
  исходники к каждому публикуемому нами бинарнику указаны ниже.

> Названия и идентификаторы лицензий, ссылки на репозитории и текст уведомлений намеренно оставлены на языке
> оригинала. Юридически значимы тексты самих лицензий у правообладателей; при расхождении между этим переводом
> и [английской версией](THIRD-PARTY.md) действует английская.

---

## Серверные бинарники, которые публикуем мы

Панель и ноды никогда не скачивают неизвестный бинарник: сервер каждого форка собирается нами из
**зафиксированного коммита** апстрима с **небольшим патчем**, который позволяет панели владеть списком пиров, и
публикуется как GitHub release. Рецепт сборки и патч лежат в этом репозитории, поэтому любой релиз можно
воспроизвести и сравнить с апстримом.

| Сервер | Апстрим | Лицензия | Зафиксированный коммит | Наш патч и рецепт | Релиз |
|---|---|---|---|---|---|
| WDTT (оригинал) | [amurcanov/proxy-turn-vk-android](https://github.com/amurcanov/proxy-turn-vk-android) | **GPL-3.0** | `51057cc` (v1.2.4) | [`forks/wdtt/`](forks/wdtt/) | `wdtt-amurcanov-1.2.4-2` |
| WDTT — ildarmaga | [ildarmaga/wdtt](https://github.com/ildarmaga/wdtt) | см. репозиторий (лицензия SPDX не объявлена) | `ef697994` (v1.5.40) | [`forks/wdtt/ildarmaga/`](forks/wdtt/ildarmaga/) | `wdtt-ildarmaga-1.5.40` |
| WDTT-Plus | [Ivan4537/WDTT-Plus](https://github.com/Ivan4537/WDTT-Plus) | **GPL-3.0** | `10c6939b` (v14) | [`forks/wdtt/wdttplus/`](forks/wdtt/wdttplus/) | `wdtt-wdttplus-14` |
| WDTT — XXcipherX | [XXcipherX/proxy-turn-vk-android](https://github.com/XXcipherX/proxy-turn-vk-android) | **GPL-3.0** | `9a3a7b87` (v2.0.0.68) | [`forks/wdtt/xxcipherx/`](forks/wdtt/xxcipherx/) | `wdtt-xxcipherx-2.0.0.68` |
| qWDTT — SpaceNeuroX | [SpaceNeuroX/proxy-turn-vk-android](https://github.com/SpaceNeuroX/proxy-turn-vk-android) | **GPL-3.0** | `854a72fe` (Release 1.4.1) | [`forks/qwdtt/`](forks/qwdtt/) | `wdtt-qwdtt-1.4.1` |
| csqtt | [amurcanov/csqtt](https://github.com/amurcanov/csqtt) | **PolyForm Noncommercial 1.0.0** | `31114cb7` (v2.0.1) | [`forks/csqtt/`](forks/csqtt/) | `csqtt-2.0.1` |

### Исходники к бинарникам под GPL

Для каждого перечисленного выше бинарника под GPL соответствующий исходный код — это:

1. **репозиторий апстрима на зафиксированном коммите** из таблицы, плюс
2. наш **патч и скрипт сборки** в указанном каталоге этого репозитория.

`build.sh` в каждом каталоге клонирует именно этот коммит, применяет именно этот патч и производит
опубликованный бинарник — больше ничего не добавляется. Эти каталоги и есть предложение исходного кода к
распространяемым нами бинарникам, поэтому они хранятся в репозитории, а не только на сборочной машине.

### <a id="csqtt-noncommercial"></a>csqtt — только некоммерческое использование

csqtt публикуется его автором под **PolyForm Noncommercial License 1.0.0**, уведомление которой гласит:

> Copyright 2026 amurcanov. Commercial use of CSQTT requires a separate written license from the licensor.

Это ограничение следует за программой: оно распространяется и на нашу сборку, а значит и на вас. Используйте
csqtt в личных или иных некоммерческих целях либо получите коммерческую лицензию у автора. Все остальные виды
серверов, которые поддерживает панель (WireGuard, AmneziaWG, turn-прокси, форки WDTT), этого ограничения не
несут.

---

## Что входит в Docker-образы

Наши образы на GHCR содержат сторонние программы, скомпилированные во время сборки:

| Образ | Компонент | Лицензия | Исходники |
|---|---|---|---|
| `swg-node` | amneziawg-go (датапас в пользовательском пространстве) | MIT | [amnezia-vpn/amneziawg-go](https://github.com/amnezia-vpn/amneziawg-go) |
| `swg-node` | amneziawg-tools (`awg`, `awg-quick`) | **GPL-2.0** | [amnezia-vpn/amneziawg-tools](https://github.com/amnezia-vpn/amneziawg-tools) |
| `swg-panel` | acme.sh (выпуск и продление TLS) | **GPL-3.0** | [acmesh-official/acme.sh](https://github.com/acmesh-official/acme.sh) |

Каждый собирается из ветки по умолчанию своего апстрима, без изменений — точные шаги см. в
[`Dockerfile.node`](Dockerfile.node) и [`Dockerfile`](Dockerfile). Поскольку мы их не меняем, полным
соответствующим исходным кодом является апстрим.

---

## Форки turn-прокси

Форки turn-прокси мы **не** собираем и **не** распространяем. Нода скачивает релизный бинарник каждого форка
напрямую из GitHub releases его автора, поэтому эти проекты распространяют свою работу сами, и их лицензии
действуют между вами и ними. Они указаны в README; панель показывает, какой форк работает в каждом прокси.

---

## Встроено в браузерное приложение

У SPA нет шага сборки, поэтому эти файлы лежат в репозитории и отдаются как есть:

| Компонент | Лицензия | Исходники |
|---|---|---|
| Preact + hooks | MIT | [preactjs/preact](https://github.com/preactjs/preact) |
| htm | Apache-2.0 | [developit/htm](https://github.com/developit/htm) |
| qrcode-generator | MIT | [kazuhikoarase/qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator) |
| JetBrains Mono, Hanken Grotesk, Onest (woff2) | SIL Open Font License 1.1 | Google Fonts |

---

Если здесь что-то неверно или устарело — лицензия, которую мы прочитали неправильно, или компонент, который мы
упустили, — пожалуйста, откройте issue. Нам важнее, чтобы этот файл был точным, чем коротким.
