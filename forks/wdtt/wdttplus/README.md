# WDTT server — WDTT Plus fork (swg-panel patched build)

Upstream: https://github.com/Ivan4537/WDTT-Plus — the admin / Telegram-bot / WARP-exit fork of WDTT. The server is
the Go package at the repo root; same `wdtt://` wire, WRAP / GETCONF / DTLS protocol as the rest of the WDTT family.
swg-panel is the control plane: the bot, the admin socket and every node-side service reachable from inside the
tunnel are off under our flags.

## Pin and label

| | |
|---|---|
| upstream commit | `b3935b947acd81d95107869c8f33507f3f5c1309` (tag `v18`) |
| our build label | **18-2**: 18 plus the stale-binding fix below. Published as `wdtt-wdttplus-18-2` (2026-09-25; amd64 `dffd34f7…`, arm64 `b51ceb51…`) and rig-proven on the published amd64 bytes. `wdtt-wdttplus-18` stays as its rollback target. |
| note | upstream's `wdttServerVersion` const at this tag still reads `"17"`, so `--version` prints `17` |

Tags move; the commit is the pin. The previous pin was v15 `3038b8dd`. The patch was regenerated against v18 with
`git diff`. It applies with no fuzz.

## Build

```bash
./build.sh                 # → ./wdtt-server (static, CGO_ENABLED=0)
GOARCH=arm64 ./build.sh
```

Needs Go ≥ 1.25 (upstream `go.mod`: `go 1.25.0`). The build is reproducible: `golang:1.25.14-bookworm`, amd64, gives
the same binary from a fresh clone as from a local tree.

## What the patch adds (`wdtt-wdttplus.patch`, `server.go` only)

| change | effect |
|---|---|
| `-iface`, `-wg-addr`, `-mtu` | interface name, subnet and MTU become flags, so several instances can run on one node. Stock defaults are kept. The address pool follows `-wg-addr`. |
| `-no-nat` | the node owns NAT, forwarding and sysctls, so the server skips `setupFullConeNAT` and `enableBBR` |
| `-fixed-config` | one keypair and one address per password, on any device (the device key is `pw:<password>`) |
| `-desired <file>` | the panel owns the password set. It is reconciled on boot, on SIGHUP and when the file's mtime changes. A password that is gone or deactivated loses its WireGuard peer and device, and its WRAP key, which cuts the live session. Expiry belongs to the panel, so the expiry janitor is off. |
| reconcile skips owner devices | devices of the node-owned `-password` (listed in the admin profile) are never reaped. Before this, every unrelated roster change cut the owner's session. |
| reconcile logs `saveDB()` failures | persistence is strict since v17. A failed save now logs `[DESIRED] … база не сохранена` instead of being ignored. |
| reconcile clears a stale device binding | under `-fixed-config`, GETCONF presents `pw:<password>` and binds it. A password already bound to a client's own device ID (a store from before `-fixed-config`, or adopted from a stock server) was refused with `device_mismatch` on **every** device, that one included. Reconcile now moves such a binding onto `pw:<password>` (18-2), and the old device row goes with it, keeping its address and keys. The only exception is a row the owner or another password still names: then the binding is cleared, the next GETCONF gets a fresh address, and the old row is reaped. Either way the old device is marked unbound in the binding history, as every other unbind path does, and a moved binding is recorded as active on its key. A binding to a `pw:` row is only cleared: that row is another password's fixed-config device. Who holds a row is counted before anything moves, so two passwords sharing one never depend on map order (`migrateFixedBindingsLocked`, test `TestMigrateFixedBindingsKeepsTheAddressAndNeverTakesASharedRow`). |
| `-no-panel` | no admin socket, no Telegram bot. In-tunnel requests that make the **node** act for a client are answered with an error frame and never run: `WDTT_UPDATE1` (GitHub release metadata), `WDTT_UPDATE_APK1` (APK download of up to 200 MB), `WDTT_HTTPS_POST1` (a POST to any public HTTPS host) and `WDTT_DEPLOY1` / `WDTT_DEPLOY_CHUNK1` (the admin relay). Without the flag, upstream behaviour is unchanged. |

The v17+ backup scheduler is left in place. It does nothing unless a backup policy is enabled, and only the admin socket
or the bot can enable one, both of which are off under `-no-panel`.

The node runs it as (`swg-noded` `_wdtt_unit_text` / `_wdtt_argv`):

```bash
wdtt-server -iface wdtt0 -wg-addr 10.66.66.1/24 -listen 0.0.0.0:56000 -wg-port 56001 -config-dir <dir> \
  -desired <dir>/desired.json -no-nat -password <owner> -max-passwords <n> -fixed-config -no-panel
```

## Validation (rig, 2026-09-14)

Everything runs in network namespaces: client ↔ local pion TURN ↔ server. The real client needs no VK; the host
firewall was unchanged. Control = v15 + the previous patch; fixed = this build. The server picked the **kernel**
WireGuard backend in both.

| test | v15 control | 18 fixed |
|---|---|---|
| T1 reach from the assigned address | 3/3 | 3/3 |
| T2 spoofed source, packets at the server interface | 0 | 0 |
| T3 revoke: live session / reconnect | cut 0/3 / refused | cut 0/3 / refused |
| T4 same address after reconnect from another device id | same | same |
| T5 unrelated roster change: session and address kept | 3/3, same | 3/3, same |
| T7 owner device after an unrelated reconcile | **reaped, 0/3** | kept, 3/3 |

The fixed build also passes T1–T5 and T7 with the real v18 client, which uses the `WDTT_MUX1` relay path.

In-tunnel requests, sent by the real v18 client over a **generated** password's tunnel. The control is the same v18
build with the refusal switched off.

| request | v18, refusal off | 18 fixed |
|---|---|---|
| `WDTT_UPDATE1`, `WDTT_HTTPS_POST1`, `WDTT_UPDATE_APK1` | the node resolves and fetches (20 DNS queries from the node in 15 s) | `ERR отключено на этом сервере (-no-panel)`, 0 DNS, 0 HTTPS |
| `WDTT_DEPLOY1` `list` (owner password in the payload) | **OK**: the admin listing is returned | `ERR отключено на этом сервере (-no-panel)` |

## Validation: one config on several devices (rig, 2026-09-24)

`.campaign/rigs/two-device-wdttplus.sh`: two device namespaces ↔ local pion TURN ↔ server with the node's argv, real
unpatched qWDTT client in WG mode. The control is 18.

| test | 18 | 18-2 |
|---|---|---|
| P1 device A, then (A vanished) device B, then A again, same password | same address, 30/30 each | same address, 30/30 each |
| P2 the server's own store, with the password and its row moved to `phone-old` at .7: device A / device B | **refused on both** (`пароль привязан к другому устройству`) | both connect at .7 (the old row, keys kept), 30/30; binding moved to `pw:<password>` |

The host firewall and links were unchanged by either run.
