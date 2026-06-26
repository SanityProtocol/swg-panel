# Changelog

Notable changes to **swg-panel**. The project is in alpha — `VERSION` is bumped on every change rather
than at tagged releases, so the newest work sits under *Unreleased*.

## Unreleased

Current `VERSION`: `1.25.332-alpha`.

### Added
- **Convert between bare-metal and Docker, in place.** Re-run the installer asking for the *other* method
  and it offers **convert · keep · abort**, stages the new method **copy-first**, then switches atomically —
  URL, login, roster, nodes and TLS cert are preserved (plus, for a `master`, the local node's token,
  interfaces and turn-proxies). Downtime is the few seconds of the switch; nodes self-heal on next sync.
- **Master split.** Converting a `master` first asks whether to move the whole box, or just the **host**
  (panel) or just the **node** — leaving a mixed Docker/bare-metal box you manage in two places.
- **Interface + turn-proxy migration in the node stage**, each behind a **"Transfer? (Y/n)"** prompt, in
  **both directions**; keys, ports and endpoints carry over copy-first, and the originals keep serving
  until the switch.
- **Live lifecycle status on the panel** — `converting → converted` (and `<op>-aborted` / `<op>-failed`
  with a captured log tail) on the panel header and the node tile, for re-install / convert / update /
  uninstall. Stored as `proc_status` on the node entry / `host_proc` for the panel itself.
- **Docs:** a "Converting between bare-metal and Docker" section in `README.md` / `README.ru.md`.

### Fixed
- **Ghost interfaces no longer resurrect.** The installer skips a `config.json` interface whose conf is
  gone, wipes stale confs from a reused `data/node-confs` on a docker convert, and deletes the orphaned
  host-netns wg/awg devices a torn-down host-networked docker node leaves behind.
- **Status reliably reaches the panel.** The proc-status POST now retries, so "converting" no longer
  silently drops, and a stale "converted" flips to "converting" when an opposite convert is run immediately.
- **docker→bare master** shows the node "converting" at conversion start (alongside the header), not only
  once the node stage begins.
- **Co-located master-split node convert** is now sound: the bare node is pointed at the panel's loopback
  port (the compose DNS name isn't reachable from outside the container network); the pre-flight no longer
  loops forever on a conf-less interface (`iface_row` is set-e-safe and ghost specs are dropped); and the
  Docker dir is kept when the panel still runs from it instead of being moved out from under it.

### Changed
- Exactly **one blank line after every data-entry prompt** and after **every summary block**, across all
  installers (`install-host` / `install-node` / `install-docker`), `bootstrap.sh` and `uninstall.sh`.
