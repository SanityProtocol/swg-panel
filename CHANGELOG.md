# Changelog

All notable user-facing changes to **swgPanel**. This file starts at `1.3.11-beta`;
earlier releases predate the changelog — see the git history. · Русский: [CHANGELOG.ru.md](CHANGELOG.ru.md)

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
