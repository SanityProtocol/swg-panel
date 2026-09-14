# WDTT server — swg-panel build

Our patched build of the **WDTT** server (`amurcanov/proxy-turn-vk-android`, the Go server at
`app/src/main/assets/linux-server`). WDTT is a self-contained, key-owning VPN (DTLS + password-HKDF
WRAP obfuscation front over its own userspace WireGuard). swg-panel integrates it as a
`kind:"self-contained"` turn-proxy server: the panel owns the password custody and the
subscription artifacts, the node runs the server.

Upstream ships **no release binaries**, so we build from a pinned commit and apply a small patch, then
host the result in our binary mirror (same pattern as the turn-proxy forks).

## Build

```bash
./build.sh [output]          # clones upstream@pin, applies the patch, builds a static binary
GOARCH=arm64 ./build.sh      # cross-build (amd64/arm64 only — same arch gate as turn)
```

- Pinned upstream: `51057cc552cdb7db4fee8cc04e6feb84569490b5` (upstream v1.2.4; bump deliberately in `build.sh`, then re-test).
- Build label: **`1.2.4-3`** — our third build of upstream 1.2.4 (same pin; adds the owner-device fix below).
  `1.2.4-2` is the published one; `1.2.4-3` is **not published** yet.
- Static (`CGO_ENABLED=0`), ~8 MB, Go 1.25 (matches upstream `go.mod`).

## What the patch adds (`wdtt-swgpanel.patch`, 4 files)

All additions are gated so absent flags reproduce **stock** upstream behavior (single `wdtt0` on
`10.66.66.1/24`, bot-driven, self-managed NAT).

| Flag | Purpose |
|---|---|
| `-iface <name>` | interface name (default `wdtt0`) — **multiple instances per node** |
| `-wg-addr <cidr>` | interface address/subnet (default `10.66.66.1/24`); host pool derived from it |
| `-mtu <n>` | interface MTU (default 1280) |
| `-max-passwords <n>` | raise the stock 10 generated-password cap (we build → fleet scale) |
| `-desired <path>` | **panel-owned `desired.json`**: declarative generated-password set, reconciled on boot + **SIGHUP** + mtime change, with **no restart / no tunnel drop**. Runtime state (device bindings, traffic) stays in `passwords.json` (WDTT-owned) → no write race. Panel owns expiry (WDTT's janitor is disabled in this mode; expiry still enforced at WRAP/GETCONF). |
| `-no-nat` | skip WDTT's BBR sysctl + iptables/nft NAT+forward — the **node** owns NAT/sysctls for wdtt subnets, exactly as for our wg/awg interfaces. WDTT then mutates only its own interface. |

Also fixes the stock **stop leak**: upstream's signal handler calls `os.Exit(0)`, skipping the deferred
`ip link del` (and never removing its firewall rules). The patch runs a single idempotent teardown
(interface + `WDTT_MANAGED` rules) on SIGTERM/SIGINT before exit.

### `desired.json` schema (panel writes; WDTT reads)

```json
{ "passwords": {
    "<generated-password>": {
      "expires_at": 0,                 // unix secs, 0 = never
      "vk_hash": "<vk call hash>",     // TURN credential
      "ports": "56000,56001,9000",     // link-advertised dtls,wg,tun (cosmetic; see plan §7b)
      "is_deactivated": false          // soft block (keeps device binding)
    }
} }
```

The **owner** password stays the `-password` flag (server identity, vaulted) — never in `desired.json`.

### Revocation reap (`reconcileDesired`)

Every reconcile removes the WireGuard peer and device of any generated password that is gone or deactivated, so a
revoked client's **live** tunnel is cut, not only its next connection. Under `-fixed-config` a generated password's
device is keyed `pw:<password>`; a stock-mode device is found through its password's `device_id`.

`1.2.4-3` judges **only** those devices. A device of the owner `-password` is keyed by the client's device id, belongs
to no generated password, and is left alone. Before `1.2.4-3` the reap deleted it on **every** reconcile, including
an unrelated roster change. That cut the owner's live session and put its address back in the pool, where the next new
password was given it. Test: `TestReconcileKeepsOwnerDevice`.

## Validation

P1 live-validated on a throwaway box (2026-07-27): two isolated instances (custom iface/subnet/ports),
`-no-nat` (zero host mutation), `desired.json` add via SIGHUP + add via mtime watcher + update + remove
(all no-restart), and clean SIGTERM teardown (interfaces removed, ports freed, firewall/sysctl clean).

`1.2.4-3` was tested on a rig on 2026-09-14. The control was the same pin with the previous patch, built locally.
That is the source `1.2.4-2` was built from; the published `1.2.4-2` binary itself was not run. The rig is network
namespaces only, with a local pion TURN relay and the unpatched qWDTT Go client in WG mode. The server ran with the
node's own argv: `-desired -no-nat -password <owner> -max-passwords -fixed-config`.

| test | control | `1.2.4-3` |
|---|---|---|
| reach from the assigned address | 3/3 | 3/3 |
| spoofed source (never assigned) reaching the server's TUN | 0 packets (3 from the real address) | 0 (3) |
| password removed + SIGHUP: live session / fresh start | cut at once (+0.02 s, 0 replies in the last 5 s) / no config, WRAP auth refused | same |
| address after reconnect, and with a different device id | unchanged, same key | unchanged, same key |
| unrelated change (add a password): first client | 50/50 replies, address kept | 50/50, kept |
| unrelated change: owner-password device | **reaped**: 1 reply, then its address went to the next new password | kept: 50/50 replies, address kept |
