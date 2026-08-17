# Changelog

All notable user-facing changes to **swgPanel**. This file starts at `1.3.11-beta`;
earlier releases predate the changelog — see the git history. · Русский: [CHANGELOG.ru.md](CHANGELOG.ru.md)

## [1.7.7-beta] — 2026-08-18

### Added
- **Every third-party licence in one place.** [THIRD-PARTY.md](THIRD-PARTY.md) now lists everything swgPanel
  builds, bundles or distributes — each server fork with its upstream, licence, pinned commit and the patch we
  apply, plus what the Docker images and the browser app carry. One item affects what you may do: **csqtt is
  noncommercial-only**, and running one commercially needs a separate licence from its author. Everything else
  the panel supports is free of that restriction.
- **csqtt servers.** csqtt is amurcanov's rewrite of WDTT and its successor: a raw-IP tunnel with no
  WireGuard inside it, which makes it markedly faster over the same VK relay. It is now a first-class kind
  in the panel, not a special case — you create one like any other interface, it carries its own routing,
  filtering and egress, its users appear in Peers with everyone else, and each one gets a one-tap
  `csqtt://` link on their subscription page. A csqtt user's whole credential is a password the panel
  issues, so there is no key to hand out and nothing for them to import.
- **Adopting a csqtt server the panel didn't create.** If csqtt is already running on a node — installed by
  hand, or left behind when a panel's records were lost — the node now finds it and offers it on the node
  page. Adopting keeps every user: the panel takes the server over on its own address and port, keeps
  serving the passwords it already had so nobody is disconnected, and imports each user as a peer you can
  see and manage. Without this the only way back was to delete the server, which would have destroyed
  every user on it.
- **csqtt runs on Docker nodes, not only bare metal.** A container has no systemd, so each server runs as a
  supervised process inside the node and is started again if it ever dies. One thing you set yourself: csqtt's
  dataplane is io_uring, which Docker's default syscall profile blocks outright, so a Docker node that will run
  csqtt needs `SWG_NODE_SECCOMP=unconfined` in its `.env`. Miss it and the panel names that as the reason rather
  than leaving you with a server that silently won't start.
- **Moving or removing a node keeps its csqtt servers straight.** Converting between bare metal and Docker carries
  each server's password store across and takes the old one down before the new one comes up, instead of leaving
  both to fight over the same port and interface. Uninstalling lists every csqtt server, asks per server before
  deleting its password store — the one step that cannot be undone — and on Docker says up front which servers are
  about to leave with the node.
- **qWDTT servers** (SpaceNeuroX's fork) can be created and adopted like the other WDTT forks, including
  its **RAW-IP mode** — a second listener that carries traffic without WireGuard for roughly six times the
  throughput, at the cost of forward secrecy. It is off by default, one switch to turn on, and the panel
  says plainly what you give up.
- **Choose what each peer publishes.** The protocol tag on a deployment is now a switch: click it and that
  kind of config stops appearing on the holder's subscription page. Turn off the direct WireGuard config
  and leave the turn-proxies, or the reverse. The deployment keeps running either way — this is about what
  the holder is offered — and a peer can never be left publishing nothing.

### Changed
- **A node can fetch a server binary itself when the panel can't.** WDTT and csqtt binaries came only through the
  panel's mirror, so anything that stopped the panel reaching GitHub stopped every node installing or updating one
  of those servers. Nodes now fall back to the release directly, and to any mirror you have configured — and say
  in their log when they had to, because a mirror that has quietly stopped working should not look like health.
- **Server fork binaries are current again.** The WDTT forks ship at their latest upstream releases
  (ildarmaga 1.5.40, WDTT-Plus 14, XXcipherX 2.0.0.68), and qWDTT and csqtt are now published like the
  rest — before this, a fresh install had no way to get either of them.
- **RAW-IP is a switch, not a port.** The app it talks to resolves that port from a single app-wide setting
  and ignores whatever a link says, so a port you chose could only ever reach users who had edited their
  app by hand. The panel now fixes it, keeps it free on every node, and allows one RAW server per address —
  turning it on elsewhere on the same address moves it, and says so first.

### Fixed
- **csqtt servers restarted every few seconds on bare metal.** The service definition tried to permit the io_uring
  system calls csqtt's data path depends on, but named a permission group that does not exist — so it was quietly
  ignored and those calls were refused. The server could not carry traffic, the node kept restarting it, and every
  connected client dropped with it. Docker installs were never affected. Updating repairs the service definition of
  any csqtt server you already have, restarting it once.
- **A server's own address now wins over the node's.** On a node with several public IPs, a WDTT or csqtt server
  binds the one you picked for it — but both the panel and the subscription page published the node's address with
  that server's port, a pair nothing listens on. The address the server actually binds now takes precedence, and
  the node's endpoint applies only where a server is bound to every address. This is the rule interfaces already
  followed, where a per-interface endpoint beats the node's.
- **Two delete dialogs could not open at all.** Deleting a turn-proxy, or deleting an interface, failed before the
  confirmation window appeared: the "type the name to confirm" label the delete dialogs share had been left private
  to one screen when the interface was split into modules, so the code was present but unreachable from the other
  two. Deleting a peer or a user was never affected, and nothing was ever removed by accident — the window simply
  never opened.
- **A csqtt server could never install.** The panel resolved a node's request for the csqtt binary to amurcanov's
  own repository — asking for a file only we build, at a tag he spells differently — so it was a 404 every time,
  on every install, from the day csqtt shipped. A node has no other source for that binary, so the server simply
  never appeared: no files, no service, and an error saying the build had not been published yet. It had.
- **The one-click update on a Docker master updated only the node.** The panel and subscription containers were
  left on their old images while the update reported success, so the panel never changed version and its own
  Update button sat on "updating…" indefinitely. The updater was reading a marker written at install time, which
  says `node` on a box converted from bare metal; it now goes by what is actually running.
- **A stopped WDTT or csqtt server still read "starting".** Stopping one from the panel worked, but its card kept
  the same tag it wears before a server has ever come up — so an intentional stop looked identical to one that
  never started, on both the interface and the turn-proxy card. It now reads "stopped", like a stopped interface.
- **Traffic charts that sat at zero.** Fleet throughput, turn-proxy throughput and Online peers had been
  flat for days on a panel whose history files were left owned by another user — every write failed
  silently and nothing said why. A file the panel cannot write is now replaced and logged.
- **csqtt and qWDTT traffic was missing from the graphs**, and their peers showed no rate or total at all:
  a keyless server has no WireGuard peer to read counters from, so the numbers were there but nothing
  looked for them.
- **A csqtt server's card did nothing when clicked.** Its settings sheet referenced a control that only
  exists for WDTT, so the whole dialog failed to open.
- **Adopting a server could pick the wrong fork.** qWDTT stores its files exactly like amurcanov's, so the
  panel guessed wrong and would have managed it with another fork's binary, hiding its RAW mode. It is now
  identified by a flag only that fork has.
- **A stopped server offered up no ports or fork on adoption.** The scan that reads them gave up at the
  first unreadable file in the system's service directory — and on a stock Debian that file sorts second,
  so it almost always gave up, and the operator was asked for values the server's own service file spells
  out.

## [1.7.1-beta] — 2026-08-10

### Added
- **The panel speaks Russian.** Every screen, every message, every confirmation — about 2,400 strings,
  including the panel's own error messages and the activity log, which stays readable for records written
  months ago because verbs are stored in English and translated on display. Switch with the **EN / РУ**
  button in the app bar; the choice is remembered per browser, and the release notes shown in the panel
  follow it too. Dates and numbers follow the panel's language rather than the machine's.
- **Cyrillic in the panel's own typefaces.** The bundled faces carried only Latin, so Russian text fell back
  to whatever the operating system had — a different look on every machine. Both families now ship Cyrillic
  cuts, matched to the Latin x-height so a translated screen keeps its rhythm.

### Changed
- **Settings: "System mesh" and "Nodes egress" are now one section, "Mesh & egress".** They were two
  per-node forms with identical chrome, and egress was two fields; they also interact, since traffic that
  exits through another node travels the mesh to get there. Existing links to the mesh settings still work.
- **The interface is delivered as ES modules** instead of one large file. It loads in a single wave rather
  than three, and the panel can now tell you *which* file is missing if an update is interrupted.

### Fixed
- **A panel that could not come back after a restart.** If the TLS key was left owned by root alone, the
  panel could not read it and the service died on the next start — a reboot, or the restart at the end of an
  update, which made a years-old permission problem look like the update had broken the install. It stayed
  invisible until then, because a running panel holds the certificate it already loaded. Updating now
  repairs the ownership before the restart that would have exposed it.
- **Every update on a Docker install failed.** The step that refreshes the host's addresses built a `sed`
  command whose separator also appears in the value, so the update aborted part-way — after reporting the
  new version, before any of the repair steps ran. It had failed this way since the first Docker release;
  bare-metal was never affected.
- **A failed install could report success.** When the chosen port was already in use, the unattended
  installer printed "Host install complete" and a panel URL over a service that never started. It now
  checks that the panel actually answers, and if it doesn't, says which port is taken and by what.
- **A broken or partial deploy showed a blank page.** If one of the interface's files went missing or
  arrived damaged, nothing rendered and the only trace was a line in the browser console. The panel now
  names the files that failed to load and offers a reload; installs verify the interface after copying it,
  and a Docker image build fails outright rather than shipping an incomplete one. An unsupported browser
  gets its own message instead of the same blank page — the interface needs Safari 16.4+, Firefox 108+ or
  Chrome/Edge 89+.
- **Status colours were missing.** Since `1.6.0-beta` most peer and user statuses were drawn in plain grey,
  so a lost peer read like a ready one. Green, blue, amber and red are back across the roster.
- **Deleting a user or peer left its editor open** behind the confirmation, showing something that no longer
  existed.
- **The subscription page's images never reached the server.** The import-hint screenshot and the
  AmneziaVPN / AmneziaWG / WireGuard logos were tracked and served, but no installer copied them — so the
  iOS import instructions rendered with a blank space where the screenshot should be, and the client logos
  were missing, on every install since they were added. One shared list now drives every copy site, so an
  asset added to the subscription page can't drift out of the installers again.
- **The subscription page's app-open countdown could run under the close button** on a narrow phone. The
  card reserved less room than the fixed × actually occupies; a longer translation pushed it into the
  overlap reliably, where the English text mostly escaped it.
- **A WDTT interface page showed no turn section at all.** A WDTT server is a turn-family server that owns
  its own transport, so nothing "forwards to" it and the section hid itself. Its card now appears there,
  without the add-proxy button, since nothing can be pointed at that interface.
- **Long names no longer break a row.** A peer title that didn't fit is cut with an ellipsis instead of
  pushing its warning icon onto a line of its own, and the widest editor's buttons fit on one row.
- Subscription pages no longer log an error for a peer that simply has no stored config yet.
- **A panel that fails while drawing a screen says so too.** The message above covers files that never
  arrived; a panel whose files are all present but which throws while drawing a screen used to leave
  "connecting…" on screen forever with nothing else. It now says which case it is: the files that didn't
  load, by name — or that all of them loaded and the interface failed while drawing, with where to find
  the error.

## [1.6.4-beta] — 2026-08-08

### Security
- **A queued host request could run commands as root (Docker installs only).** Two places in the Docker host
  helper built a shell command out of values taken from the panel's own request queue, so a crafted port
  could have run arbitrary commands on the host. Neither place needed a shell — both now pass every value as
  an argument, and a port is checked where it is used rather than once per action. The queue itself is also
  verified for the first time: a request is acted on only if it is an ordinary file belonging to the panel,
  which is the rule the bare-metal helper has always applied. Reported by
  [@anupamme](https://github.com/anupamme) (OrbisAI Security).

### Added
- **"Don't offer" a server on a given operating system.** Each server already lets you choose which app its
  users are handed per platform; now you can also choose to offer **nothing**. The server then simply doesn't
  appear on those users' subscription pages — no card, no download link — instead of offering an app that
  can't connect to it. Useful when a server has no sensible client on a platform: iOS users of a
  Windows-only server now see nothing for it, rather than something that fails.

## [1.6.3-beta] — 2026-08-06

### Fixed
- **A node with a pinned dial source reported an error every few seconds.** Mesh links that pin which
  outbound address they dial from made the node log a `dial-src` fault on every sync and show as erroring
  in the panel — while the routing itself was applied correctly the whole time. The same fault stopped the
  node recording what it had pinned, so **clearing** a dial source afterwards left its route in place until
  the machine was rebooted.
- **The colour previews in settings were see-through.** Hovering a colour swatch shows how that colour reads
  against each theme's real background; the preview had lost its backdrop, so the page behind it showed
  through and the colour was impossible to judge.
- **A node could report "SNI parser down — host routing degraded" while working correctly.** Picking an
  SNI routing mode before any interface has a routing category assigned leaves nothing to classify, so the
  classifier is deliberately never started — and the health badge read that deliberate absence as a failure.
  It now tells *idle by design* apart from *down*, which the kernel-SNI engine already did.

### Changed
- **Settings → Authentication is a single panel again.** The password form and two-factor sat in two separate
  boxes; they are now two sections of one card, like every other settings screen.

## [1.6.1-beta] — 2026-08-01

### Fixed
- **Adopting a WDTT server this machine had run before deleted all of its users.** If the box had hosted that
  server in an earlier life — after a re-install, or with a panel restored from an older backup — the take-over
  quietly did nothing and the server was then emptied: every user removed, and the owner password replaced.
  Adoption now runs whenever the panel doesn't already manage the server, whatever the machine has left over.
- **A server's users are never deleted just because the panel hasn't heard of them yet.** Until the panel has
  actually held a password for a server, its existing users are handed up and imported instead of removed —
  which also covers creating a server on top of an older install's directory, and a node that lost its records
  while the server's own store survived. Removing a user now requires you to remove it.
- **Adopting a server no longer resets its clients' addresses.** Each device kept the address it had.
- **The panel could report its TLS type as self-signed while serving a real certificate.** On a fresh install's
  first start it guessed before it had anything to go on, then never corrected itself — so Settings → Access
  read "self-signed" over a working Let's Encrypt certificate for the life of the box. It now reads the
  certificate, and repairs the stored value when a real certificate contradicts it.
- **WDTT configs that import by link were unreadable**, printed one character per line beside the "no VK call
  link" notice. **WDTT-Plus** was also offered a QR code its app can't scan — it takes a link, like the others.
- **The VK call link field was missing for users who only have a WDTT server.** Their config needs the link,
  but the field only appeared for users behind a turn-proxy.

## [1.6.0-beta] — 2026-08-01

The **WDTT** release: a third kind of server you can run from the panel, and the ability to **adopt
servers you already have** instead of rebuilding them.

### Added
- **WDTT servers — a self-contained, disguised VPN server, run from the panel.** WDTT carries a
  WireGuard tunnel inside a stream shaped like a VK video call, so to a network watching the wire it
  doesn't look like a VPN at all. Unlike a turn-proxy (which fronts an interface you already have), a
  WDTT server *is* the interface — it owns its own tunnel — so you create it exactly like a WireGuard
  or AmneziaWG interface, on its own name, subnet and ports, several per server if you like.
- **Four WDTT server forks to choose from** — **amurcanov** (the original), **ildarmaga**,
  **Ivan4537** and **XXcipherX** — each with its own client apps. Pick the fork when you
  create the server; all four are offered by default.
- **WDTT users work like everyone else.** A WDTT user is an ordinary peer in the panel with a
  password instead of a key: add, block, expire, rotate and delete them the same way, on the same
  screens, and the server picks the change up **without dropping anyone's tunnel**.
- **WDTT on subscription pages and in the QR modal.** Each user's page shows their WDTT server
  alongside their WireGuard / AmneziaWG configs, with a one-tap **import link** for the client apps
  that support it, a QR for the ones that scan, and a **download row** for getting the app itself —
  picked per operating system from the client you set as the default for that fork.
- **Routing, content filters and egress apply to WDTT too** — the same per-interface controls as
  wg/awg, and its traffic is counted everywhere: the flow map (as its own relay), per-node totals,
  the protocol and turn-proxy breakdowns, and the interface tags on the nodes list.
- **WDTT builds are versioned, and roll back.** The panel tracks which build each server runs, ships
  new ones as they're published, and lets you pin an older build per server if a new one misbehaves.
- **Adopt the interfaces a server already has.** The node reports every WireGuard / AmneziaWG
  interface and WDTT install it finds that the panel didn't create, and each one shows up on the node
  page as a card you can **Adopt** or **Ignore**. Adopting takes it over **as it is** — same keys,
  same port, same subnet, and its existing peers come across — so nobody re-imports anything and
  nothing goes down. This is how you move an existing hand-rolled server onto the panel.
- **Stopped installs are found too.** A WDTT install that isn't running still shows up (with what it
  knows about itself — fork, ports, subnet, and its users), so you can adopt a server that's been
  switched off, and **Adopt existing** takes a path directly for an install that was moved or renamed.
- **Adopted WDTT users are imported.** Their passwords come across into the roster as peers, so the
  links people already have **keep working** — and the server keeps serving throughout the take-over.
- **Ignored interfaces are remembered**, listed under Settings, and can be un-ignored later; one that
  later becomes managed drops off the list on its own.
- **Rotate every key a user has, in one action.** New in the user editor: re-key all their WireGuard
  peers *and* re-issue their WDTT passwords at once, with each config re-rendering as it flips over.
- **The subscription page tells you when its certificate is wrong** — missing, expired, or issued for
  a different address — as a proper alert, re-issues it when you save the address (even if nothing
  changed), and re-checks it as part of the ongoing self-heal. Only for direct HTTPS: behind a reverse
  proxy the certificate stays the administrator's business.
- **A native arm64 Docker node image.** Both images are now built natively for amd64 *and* arm64, so
  ARM boxes (Ampere, Graviton, Pi-class hardware) run the node image without emulation.

### Changed
- **The installers no longer ask about VPN configuration.** They install the software, stand the
  service up, and stop there — interfaces, turn-proxies and WDTT servers are created in the panel,
  where you can see what you're doing. Anything the box already had is offered for adoption instead
  of being asked about at a prompt. WireGuard and AmneziaWG are always installed, so a fresh panel is
  ready to create an interface the moment you log in.
- **Client apps are chosen per operating system.** Turn-proxy and WDTT settings now show a per-OS
  matrix of the apps that work with each fork — named by their author, coloured, and marked by how
  well they fit — and the default you pick there is what users get offered on their subscription page.
- **Uninstall says exactly what it will remove**, including Docker turn-proxies and WDTT servers on a
  node, and labels interfaces plainly as "AmneziaWG/WireGuard interfaces".
- **One panel password, plus a recovery key.** Resetting the login no longer destroys the encryption
  vault; the recovery key is what restores access to escrowed keys.

### Fixed
- **Converting between bare-metal and Docker no longer loses things.** A convert used to leave behind
  the WireGuard configs that only existed inside the container, the node's pulled routing lists
  (which showed up afterwards as "SNI scanner down"), the subscription service's port and bind (every
  subscription link silently pointed at a dead port), the reverse proxy (left un-reloadable), and — on
  docker→bare — the panel's own roster. Each of those is carried across now, and the conversion never
  tears the old side down before proving the new one starts.
- **Adoption on Docker nodes.** An interface whose config file lives only inside the container is
  rebuilt from the live device (keys, peers, port, MTU) so it can be adopted at all; a foreign WDTT
  server is now identified by its own process — including which fork it is, and its real subnet read
  off the live interface — instead of being guessed at and mislabelled.
- **A Docker node restart no longer un-manages plain-WireGuard interfaces.**
- **Deleting a WDTT server removes its users** from the roster, so a server created afterwards on the
  same name can't inherit the previous one's peers.
- **An uninstall on a box with a WDTT server used to die mid-run**, leaving the install half-removed.
- **The panel could come up with no login at all** on Docker when the subscription service's auth
  mount pre-created an empty file.
- **A WDTT link with an empty password**, a WDTT subnet change that left clients online but without
  internet, and WDTT servers that vanished from the panel while being created, deleted or adopted —
  an operation in flight now shows as a card with its state, not as an empty space.
- **Certificates on Docker** are no longer issued for a domain the panel isn't advertising, and the
  subscription page can now get a Let's Encrypt certificate there at all.
- **Typing in turn-proxy settings is no longer wiped** by the background poll mid-edit.

## [1.5.1-beta] — 2026-07-26

The big one: **content filtering** and a live **Protection** dashboard on the Overview.

### Added
- **Content filtering (blocking).** Block **ads, trackers, malware, adult content, gambling** and more —
  per interface, from curated category lists. Filtering runs on the **entry node** (where the client's tunnel
  lands); domain filters enforce in **Force-DNS** and **Hybrid-SNI** modes, and IP / threat-IP lists enforce in
  **every** mode. Every enabled feed merges into **one set per node** for an O(1) match, and the panel builds
  those lists with a **streaming resolver** so even multi-million-domain lists won't run a small box out of
  memory. Each category ships a small, Force-DNS-safe **default** list — add bigger ones when the server has the RAM.
- **Overview "Protection" card.** A live, range-aware view of what filtering is doing: **Blocked** (packets
  dropped, plus distinct sites broken down **per category**), **Torrents caught**, and **Scanners flagged** — each
  with a hover **"who"** bubble that attributes torrents and scanners to the **user · peer** behind them, newest first.
- **Memory-aware filtering.** The node gates the Force-DNS list fill against available RAM so a large list can
  never thrash a small node offline (it degrades honestly and reports it), and the panel **warns** — with a rough
  "≈130 MB per 1M domains" estimate — before you turn on a big list.

### Changed
- **The flow map's card height is now rock-stable** — it no longer resizes on every poll (which used to scroll
  the page out from under you). Denser fleets get a little more vertical room.
- **The Overview now shows both** *Top nodes by peers* (online, range-aware) **and** *Top nodes by traffic*.
- **Routing / Blocking mode card** tidied up — the lists line sits under the four mode buttons, the info popover
  is clamped to the screen, and **Reset routing** is a compact red icon.
- **Toasts last a little longer (5.5 s), and saving an interface now confirms with a toast.**

### Fixed
- **Panel out-of-memory when resolving large block lists.** The block-union builder now **streams and
  external-sorts** to disk instead of holding the whole union in RAM — a multi-million-domain list no longer
  OOM-kills a 1 GB panel.
- **Hybrid content-blocking could stop dropping learned destinations** after a brief per-source-counter
  experiment; reverted to the known-good path, enforcement verified.
- **Kernel-SNI** now steers domain blocks to the DNS/SNI path (they can't match by destination IP), and block
  sets no longer leak into **Top destinations**.

## [1.4.2-beta] — 2026-07-24

A follow-up to 1.4.1: the AmneziaWG datapath now **actually rebuilds** on repair, and you can trigger a
repair from the panel **even when there's no new version**.

### Fixed
- **The AmneziaWG kernel-module heal now forces a DKMS rebuild.** 1.4.1 installed the build dependencies but,
  on a box where the `amneziawg` package was already present, `apt install` was a no-op and never compiled the
  module — so the interface still failed to come up. The installers and the updater now run `dkms autoinstall`
  (with an `amneziawg-dkms` reinstall fallback) to actually build and load the module for the running kernel.

### Changed
- **The panel's Update repairs even when you're already up to date.** The "up to date" indicator is now a
  button that re-runs the updater — reinstalling anything missing, re-enabling services, and rebuilding the
  datapath (e.g. the AmneziaWG module) — so you can fix a broken node without waiting for a new release. The
  update dialog spells this out.

## [1.4.1-beta] — 2026-07-24

A maintenance release that makes **AmneziaWG install reliably on a fresh box**, and lets the panel's
**Update** button repair a broken datapath on its own.

### Fixed
- **AmneziaWG interfaces failing to come up** — `ip link add … type amneziawg → Unknown device type`.
  Installing the `amneziawg` package only lays down the `awg` *tool*; the datapath is a **DKMS kernel
  module** that has to compile against your running kernel. The installers now also install `dkms` +
  `linux-headers-$(uname -r)` and verify the module actually loads (success is no longer "the CLI exists").
  When you create an interface from the panel, the node now reports the **real cause — with the exact fix —**
  instead of the misleading "a port or subnet may be in use".

### Changed
- **Update now rebuilds the AmneziaWG kernel module when it's missing or stale** — e.g. after a kernel
  upgrade left the previous DKMS build behind, so awg interfaces silently stopped coming up. Clicking
  **Update** in the panel (or running `swg-update`) repairs the node automatically.
- **Turn-proxy platform chips** in the fork list get a cleaner solid-neon look, filled by client kind.

### Docs
- The install one-liner now **asks the method** (bare-metal / Docker) **and role** instead of silently
  installing a panel with no node.
- Noted that on a root shell without `sudo` (common on fresh Debian / VPS images) you simply drop the `sudo`.

## [1.4.0-beta] — 2026-07-23

The headline of this release is **client apps for turn proxies**: the panel now manages the whole client
side, so end-users get a ready-to-use connection from their subscription page with nothing to assemble.

### Added
- **Client apps for turn proxies.** For each fork, choose which app your end-users get on each platform
  (Android / iOS / desktop) — VK TURN Proxy, WINGS V, FreeTurn, WireGuard-TURN, or the CLI sidecar — with
  the compatible choices ranked (native · cross-fork · plain). The subscription page then hands out exactly
  that app's config, matched to the visitor's device: a tap-to-open deep link, a scannable QR, a config
  file, or a ready-to-paste command. Adds the **MYSOREZ** fork, typed per-proxy obfuscation settings,
  panel-mirrored fork binaries with one-click version rollback, and drift detection for the app formats.
- **Reworked subscription page.** One **Start** button per connection that does the right thing for the
  chosen app, an OS picker that re-generates the config and downloads for the selected platform, per-app
  "Get the app" install links, and one-tap **Amnezia VPN** import for WireGuard / AmneziaWG.
- **Expiry dates** for a peer or a subscription — expired and blocked peers are clearly flagged throughout.
- **Multiple VK call links per user**, handed to each app in the form it supports.
- **Redesigned add-peers** — a two-panel layout (this user's peers · the unassigned pool) and a
  primary / backup connection picker.
- **`swg-passwd` — reset the panel login from the shell.** `sudo swg-passwd` resets the admin username and
  password and re-keys the Encryption Vault in place; you're signed back in on the next login, and stored
  configs / subscription links keep working (no re-issue).

### Changed
- **Updating now self-heals a panel or node that's missing pieces** — a lost service, unit, or root helper
  is reinstalled in place (never re-created), so a plain update fixes it with no reinstall. A server that
  lost a keyless interface now has it recreated and re-keyed, and service-health problems are surfaced
  under a new *needs attention* panel.
- **Interface-key escrow is now on by default** (previously off) and moved into the Interfaces screen —
  each node seals its interface private keys to a vault key only you hold, so a wiped node's keys can be
  restored without the panel ever seeing them.
- The peer and turn-proxy status model was reworked for clearer at-a-glance state.

### Fixed
- A fresh **Docker** install no longer fails to start the subscription container.
- Each device is now offered only an app that actually connects to its server, with the right obfuscation —
  plain servers use the plain transport, obfuscated forks use their own — and blocked / expired peers no
  longer show as *dangling*.
- Stopped a background flood of 404s from the subscription surface.

## [1.3.13-beta] — 2026-07-20

### Fixed
- **Updating now repairs a panel that was missing its subscription server.** If a box ended up with the
  subscription files but no `swg-sub` service — an older install, or one where the unit was lost — the
  panel could not start or move the subscription server, and Settings → Subscriptions failed with
  "couldn't bind the subscription server" and rolled back. An update now installs the service (and its
  own unprivileged user) when it's absent, the same way it already heals the privileged network helper —
  so a plain update fixes it, with no need to reinstall. The panel's configured subscription address is
  preserved.

## [1.3.12-beta] — 2026-07-19

### Added
- **Restore a missing or broken interface — keys and all.** If a server loses an interface (its config
  wiped, or the whole box rebuilt), the panel flags it as *dangling* and offers a one-click **Restore**
  that recreates the interface with the **same keys** and re-adds every peer — clients keep working, with
  no configs to redistribute. A peer whose address has drifted out of its interface's subnet shows as
  *broken* with a **Fix** button that corrects the address in place. Both work on a single peer or as a
  batch across a whole node, including rebuilding a node from scratch.
- **Optional interface-key escrow.** Turn on escrow and each node seals its interface private keys to a
  vault key that only you hold; the panel keeps only the ciphertext. A wiped node's keys can then be
  restored from the vault — the panel never sees a private key. Off by default.

### Fixed
- **Switching the panel between a subpath reverse proxy and its own HTTPS now works both ways.** A reverse
  proxy mounted under a path (e.g. `/panel`) can be flipped to built-in TLS at the root — and back —
  without the confirmation failing, and remote nodes re-point themselves to the new address during the
  switch instead of stranding on the old one.
- **A peer's address is validated against its interface subnet before it's applied**, so a bad or
  multi-range address can't quietly break a peer.
- **Converting between Docker and bare-metal keeps your panel address and settings** and no longer trips a
  port collision on the co-located node.
- Assorted robustness fixes to the address-change flow — out-of-range ports are rejected instead of
  silently clamped, and cancel / confirm now report their outcome clearly.

### Changed
- The peer status model and the "needs attention" and missing-interface cards were reworked for clearer
  at-a-glance state — *online / partial / broken / dangling*.

## [1.3.11-beta] — 2026-07-18

### Added
- **Change the panel's own address from the UI.** Switch the panel between a reverse proxy
  (nginx / Cloudflare) and its own built-in HTTPS, or change its path, port, or domain — no SSH
  needed. Connected nodes follow the new address automatically, and the old address keeps serving
  during the switch, so a wrong value can never lock you out.
- **Address-migration ribbon with one-click undo.** A banner appears when you're viewing a previous
  panel address; for moves the panel fully controls (built-in TLS), a single click cancels the move.

### Fixed
- **"The root helper is not available."** Older installs missing the privileged helper now get it
  installed automatically on `update`, so setting the subscription address and other Access changes
  work again.
- **Address no longer reverts when converting to Docker or re-installing.** A confirmed address change
  is now written to the install config (and the Docker `.env`), so a later convert/re-install keeps
  your current address instead of the one from first install.
- **Docker: a path or port change survives a container restart.** Previously a `docker restart` or a
  reboot could quietly roll the panel back to its old address.
- **Switching a Docker panel to its own built-in HTTPS is now safe.** The panel issues *and verifies* the
  certificate before committing; if it can't be issued (missing/blocked credential, DNS not ready), it
  **rolls back automatically** to the working address instead of going down. A stale self-signed certificate
  left by an earlier failed attempt no longer shadows re-issuance, and switching to a mode that needs a
  Cloudflare token is refused up front when the token is missing.

### Changed
- On Docker, TLS and address changes apply through a container-aware path and are made restart-safe.
