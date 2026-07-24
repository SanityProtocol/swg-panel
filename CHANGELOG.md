# Changelog

All notable user-facing changes to **swgPanel**. This file starts at `1.3.11-beta`;
earlier releases predate the changelog — see the git history. · Русский: [CHANGELOG.ru.md](CHANGELOG.ru.md)

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
