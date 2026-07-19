# Changelog

All notable user-facing changes to **swgPanel**. This file starts at `1.3.11-beta`;
earlier releases predate the changelog — see the git history. · Русский: [CHANGELOG.ru.md](CHANGELOG.ru.md)

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
