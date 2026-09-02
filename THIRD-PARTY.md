# Third-party software

· Русский: [THIRD-PARTY.ru.md](THIRD-PARTY.ru.md)

swgPanel itself is MIT (see [LICENSE](LICENSE)). It also **builds, ships and runs** software written by other
people, under their own licences. This file says exactly what, under which licence, and where the source is —
in one place, so you can check it without reading the build scripts.

Two things here affect what **you** may do, not just us:

- **csqtt is noncommercial-only.** Running a csqtt server commercially needs a separate written licence from
  its author. See [csqtt](#csqtt-noncommercial) below.
- **Most WDTT forks are GPL-3.0.** You are free to use, study, modify and redistribute them, and the source for
  every binary we publish is linked below.

---

## Server binaries we publish

The panel and nodes never download an unknown binary: each fork's server is built by us from a **pinned upstream
commit** with a **small patch** that lets the panel own the peer set, and published as a GitHub release. The
recipe and the patch are in this repository, so any release can be reproduced and diffed against upstream.

| Server | Upstream | Licence | Pinned commit | Our patch + recipe | Release |
|---|---|---|---|---|---|
| WDTT (original) | [amurcanov/proxy-turn-vk-android](https://github.com/amurcanov/proxy-turn-vk-android) | **GPL-3.0** | `51057cc` (v1.2.4) | [`forks/wdtt/`](forks/wdtt/) | `wdtt-amurcanov-1.2.4-2` |
| WDTT — ildarmaga | [ildarmaga/wdtt](https://github.com/ildarmaga/wdtt) | **GPL-3.0** ‡ | `ef697994` (v1.5.40 ‡) | [`forks/wdtt/ildarmaga/`](forks/wdtt/ildarmaga/) | `wdtt-ildarmaga-1.5.40` |
| WDTT-Plus | [Ivan4537/WDTT-Plus](https://github.com/Ivan4537/WDTT-Plus) | **GPL-3.0** | `10c6939b` (v14) | [`forks/wdtt/wdttplus/`](forks/wdtt/wdttplus/) | `wdtt-wdttplus-14` |
| WDTT — XXcipherX | [XXcipherX/proxy-turn-vk-android](https://github.com/XXcipherX/proxy-turn-vk-android) | **GPL-3.0** | `9a3a7b87` (v2.0.0.68) | [`forks/wdtt/xxcipherx/`](forks/wdtt/xxcipherx/) | `wdtt-xxcipherx-2.0.0.68` |
| qWDTT — SpaceNeuroX | [SpaceNeuroX/proxy-turn-vk-android](https://github.com/SpaceNeuroX/proxy-turn-vk-android) | **GPL-3.0** | `854a72fe` (Release 1.4.1) | [`forks/qwdtt/`](forks/qwdtt/) | `wdtt-qwdtt-1.4.1` |
| csqtt | [amurcanov/csqtt](https://github.com/amurcanov/csqtt) | **PolyForm Noncommercial 1.0.0** | `de7afc23` (v2.1.5) † | [`forks/csqtt/`](forks/csqtt/) | `csqtt-2.0.1` † |

† **csqtt's recipe is ahead of its release.** `forks/csqtt/` is ported to v2.1.5 (`de7afc23`) and builds the
2.1.5 binary, but that release is not published yet, so the current release is still `csqtt-2.0.1` — built from
upstream `31114cb7` with the patch as it stood at `929eddf8` in this repository. Every other row's recipe and
release describe the same binary; this one will too once `csqtt-2.1.5` is cut.

‡ **ildarmaga: two things this table cannot say in a cell.** The repository's `LICENSE` is the full text of
the **GNU GPL v3**, with a copyright header for the WDTT server/panel and the bundled PWDTT client binaries
prepended to it. GitHub's own detector reports the repository as "Other" / `NOASSERTION`, because that header
stops the file matching the GPL template byte-for-byte — but the grant it carries is the standard one, so the
binary we publish is a GPL binary and the source offer below covers it. Separately, the version in brackets is
not a distinguishing identifier: upstream's tags `v1.5.2` through `v1.5.40` **all point at commit `ef697994`**,
whose own message is "docs: changelog for v1.5.0". The commit is what pins our build; the tag name is only how
we label the release.

### Source for the GPL binaries

For every GPL-licensed binary above, the Corresponding Source is:

1. the **upstream repository at the pinned commit** in the table, plus
2. our **patch and build script**, in the linked directory of this repository.

`build.sh` in each directory clones that exact commit, applies that exact patch, and produces the published
binary — nothing else is added. Those directories are the source offer for the binaries we distribute, which is
why they stay in the repository rather than living only on a build machine.

### <a id="csqtt-noncommercial"></a>csqtt is noncommercial

csqtt is published by its author under the **PolyForm Noncommercial License 1.0.0**, whose notice reads:

> Copyright 2026 amurcanov. Commercial use of CSQTT requires a separate written license from the licensor.

That restriction travels with the software: it applies to our build too, and therefore to you. Use csqtt for
personal or other noncommercial purposes, or obtain a commercial licence from the author. Every other server
kind the panel supports (WireGuard, AmneziaWG, the turn-proxies, the WDTT forks) is free of that restriction.

---

## Bundled in the Docker images

Our images on GHCR contain third-party programs compiled at build time:

| Image | Component | Licence | Source |
|---|---|---|---|
| `swg-node` | amneziawg-go (userspace datapath) | MIT | [amnezia-vpn/amneziawg-go](https://github.com/amnezia-vpn/amneziawg-go) |
| `swg-node` | amneziawg-tools (`awg`, `awg-quick`) | **GPL-2.0** | [amnezia-vpn/amneziawg-tools](https://github.com/amnezia-vpn/amneziawg-tools) |
| `swg-panel` | acme.sh (TLS issuance/renewal) | **GPL-3.0** | [acmesh-official/acme.sh](https://github.com/acmesh-official/acme.sh) |

Each is built from its upstream default branch, unmodified — see [`Dockerfile.node`](Dockerfile.node) and
[`Dockerfile`](Dockerfile) for the exact steps. Because we make no changes to them, upstream is the complete
Corresponding Source.

---

## Turn-proxy forks

The turn-proxy forks are **not** built or redistributed by us. A node downloads each fork's own release binary
directly from its author's GitHub releases, so those projects distribute their own work and their licences apply
between you and them. They are credited in the READMEs; the panel shows which fork each proxy runs.

---

## Vendored in the browser app

The SPA has no build step, so these ship as files in this repository and are served as-is:

| Component | Licence | Source |
|---|---|---|
| Preact + hooks | MIT | [preactjs/preact](https://github.com/preactjs/preact) |
| htm | Apache-2.0 | [developit/htm](https://github.com/developit/htm) |
| qrcode-generator | MIT | [kazuhikoarase/qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator) |
| JetBrains Mono, Hanken Grotesk, Onest (woff2) | SIL Open Font License 1.1 | Google Fonts |

---

If anything here is wrong or out of date — a licence we have misread, or a component we have missed — please
open an issue. Getting this right matters more to us than getting it short.
