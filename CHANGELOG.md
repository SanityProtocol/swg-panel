# Changelog

All notable user-facing changes to **swgPanel**. This file starts at `1.3.11-beta`;
earlier releases predate the changelog — see the git history. · Русский: [CHANGELOG.ru.md](CHANGELOG.ru.md)

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
