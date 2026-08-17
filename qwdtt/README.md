# qWDTT server — swg-panel build

Our patched build of the **qWDTT** server (`SpaceNeuroX/proxy-turn-vk-android`) — a WDTT fork, so it
integrates as one more `kind:"wdtt"` fork, not a new interface type: DTLS + password-HKDF WRAP over its
own userspace WireGuard, a `passwords.json` store, and *a peer is a password*. All the WDTT machinery
(`reconcile_wdtt`, `wdtt_snapshot`, `WdttCard`, Users/Peers, collected relay IPs, overview) applies
unchanged. See `docs/QWDTT-AND-TCP-TRANSPORT-PLAN.md`.

Upstream ships no server binary, so we build from a pinned commit and host the result (same pattern as
`wdtt/`).

## Build

```bash
./build.sh [output]          # clones upstream@pin, applies the patch, builds a static binary
GOARCH=arm64 ./build.sh      # cross-build (amd64/arm64 only — same arch gate as turn)
```

- Pinned upstream: **`854a72fe`** ("Release 1.4.1", 2026-08-15).
  ⚠️ **Pin a commit, never a tag** — `v1.3.8`/`v1.3.9`/`v1.4.0`/`v1.4.0-beta` all still point at the
  July commit `2dd5d37f`.
- Static (`CGO_ENABLED=0`), ~8.8 MB, **Go 1.26** (upstream `go.mod`; the WDTT forks are Go 1.25).
- Layout differs from amurcanov's: the server is one flat `server.go` (+`admin_api.go`) at the **repo
  root**, not under `app/src/main/assets/linux-server`. The amurcanov patch does not apply here.

## What the patch adds (`qwdtt-swgpanel.patch` — one new file + hooks)

Almost everything lives in a new **`swgpanel.go`**; `server.go` carries only small hooks, so upstream
drift is cheap to re-port. Every flag defaults to **stock** behaviour, so an unflagged binary is
upstream (single `wdtt0` on `10.66.66.1/16`, bot-driven, self-managed NAT).

| Flag | Purpose |
|---|---|
| `-iface <name>` | interface name (default `wdtt0`) — **multiple instances per node** |
| `-wg-addr <cidr>` | interface address/subnet; the client IP pool is walked from it (stock hardcodes `10.66.0.0/16`, which cannot host sibling instances) |
| `-mtu <n>` | interface MTU (default 1280) |
| `-max-passwords <n>` | raise the stock 10 generated-password cap |
| `-desired <path>` | **panel-owned `desired.json`**: declarative password set, reconciled on boot + **SIGHUP** + mtime change, **no restart, no tunnel drop**. Runtime state (device bindings, traffic) stays in `passwords.json` (server-owned) → no write race. The panel owns expiry, so the server's janitor is off in this mode (expiry still enforced at WRAP/GETCONF). |
| `-no-nat` | skip BBR sysctls + iptables/nft NAT/forward (WG **and** raw paths) — the node owns them |
| `-fixed-config` | one generated password = one keypair + IP for any device (wg/awg parity), instead of upstream's per-device binding (`MaxDevices`/`DeviceIDs`) |
| `-api-addr <addr>` | bind the HTTP control API here; **empty (the default) = the API never starts** |

Two upstream behaviours the patch fixes:

- ⚠️ **The HTTP control API was bound to the public DTLS port.** Stock `main()` runs
  `http.ListenAndServe(*listen, mux)` on the very same `ip:port` as the DTLS data path, exposing
  `/admin/*` (auth: the owner deploy password in `X-Admin-Password`) and `/api/profile/{status,unbind}`
  (auth: knowing a user password) to the internet — with `Access-Control-Allow-Origin: *`. Besides the
  admin surface, it makes the port trivially fingerprintable: anything that is supposed to look like a
  VK call answers HTTP. We default it **off** and require an explicit (loopback) `-api-addr`.
  *This is also what made qWDTT's `deploy.sh` open TCP on the DTLS port — an HTTP admin API, never a
  TCP data transport.*
- **Stop leak**: upstream's signal handler calls `os.Exit(0)`, skipping the deferred `ip link del`.
  The patch runs one idempotent teardown (interface + `WDTT_MANAGED` rules) before exit.

### `desired.json` schema (panel writes; the server reads)

Identical to the WDTT one — `swg-noded`'s `_wdtt_desired_body` needs no change:

```json
{ "passwords": {
    "<generated-password>": {
      "expires_at": 0,                 // unix secs, 0 = never
      "vk_hash": "<vk call hash>",     // TURN credential
      "ports": "56000,56001,9000",
      "is_deactivated": false          // soft block
    }
} }
```

The **owner** password stays the `-password` flag (server identity) — never in `desired.json`.

## Validation (A0, live on svo-im, 2026-08-17)

One instance `wdtt9` / `10.77.0.1/24` / DTLS `:56750` / internal wg `:56751`, run with
`-no-nat -fixed-config -desired`:

- boots on our flags; interface created from `-wg-addr`; **no TCP listener on the DTLS port** and an
  HTTP probe of it gets nothing (the `-api-addr` fix);
- **host firewall byte-identical while running** and `ip_forward` untouched (`-no-nat`);
- `desired.json` reconcile: two passwords added at boot; then remove-one + change-a-field via **SIGHUP
  with the same PID** (no restart), plus the mtime watcher firing independently;
- **a real qWDTT client connected end-to-end through a VK relay**: DTLS handshakes on 9 workers, a wg
  peer at `10.77.0.2/32` (from our pool), device stored as `pw:<password>` (fixed-config), and traffic
  through the tunnel egressing at the server's public IP;
- clean **SIGTERM** exit: interface gone, firewall identical to the pre-run snapshot, and the box's
  protected services (nginx/mongod/swg-noded) untouched throughout.
