# WDTT server — xxcipherx fork (swg-panel patched build)

Third server fork in the WDTT family (`XXcipherX/proxy-turn-vk-android`, the video-masquerade fork of `../` =
amurcanov). Same `wdtt://` wire, WRAP/GETCONF/DTLS protocol. We build only the Go server at
`app/src/main/assets/linux-server`; the swg-panel is the control plane.

## Build

```bash
./build.sh [output]          # clones upstream@pin, applies the patch, static CGO_ENABLED=0 binary
GOARCH=arm64 ./build.sh
```

- Pinned upstream: `b44df2d4acb2b30bdab1dff2b6bad083294d4df8` = tag `v2.0.0.72`. **Our build label: `2.0.0.72`.**
- **Requires Go ≥ 1.27.1** (upstream `go.mod` says `go 1.27.1`), e.g. `golang:1.27.1-bookworm`.
- Server change vs the previous pin `v2.0.0.70` (`a9c0ff7a`): `go.mod`/`go.sum` (Go 1.27.1, `pion/dtls` 3.1.8,
  `x/crypto` 0.57) and one banner line in `main.go`.
- ⛔ Not published. Nothing lists this build until it is released and its entry added in the same change.

## Patch (`wdtt-xxcipherx.patch`, 5 files)

Flags — absent flags keep stock behaviour:

| flag | effect |
|---|---|
| `-iface <name>` / `-wg-addr <cidr>` / `-mtu <n>` | multi-instance identity; the host pool follows `-wg-addr` (allocator and store validator agree) |
| `-max-passwords <n>` | raise the stock 10-password cap |
| `-desired <path>` | panel-owned `desired.json`, reconciled on boot, SIGHUP and mtime change, no restart |
| `-no-nat` | the node owns NAT/forward/sysctls; the server touches only its own interface |
| `-fixed-config` | a generated password owns ONE keypair + address, returned to any device ID |

Correctness fixes carried in the patch (2.0.0.72):

- **`-fixed-config` works.** GETCONF keys a generated password's device `pw:<password>` (`getconfDeviceKey`) instead of the
  client's device ID. Before, the flag was parsed but unused: a second device was refused `device_mismatch`, and every
  re-created device got a new keypair. A `pw:` key belongs to the password it names, so neither the owner nor another
  password can claim it by sending that string as a device ID.
- **The reconcile reaps only what a removal or deactivation requires.** It touches a device only when it belongs to a
  generated password that is gone or deactivated, and never the owner password's devices. Before, every device-ID key
  read as a missing password: each unrelated `desired.json` change deleted every device, dropped every client (the
  owner's too), and handed addresses to whoever connected next.
- **A password added through `desired.json` is admitted at once.** The reconcile sets its access state (and removes it
  for a removed password). Before, a new password passed WRAP and was then closed silently at accept until a restart.
- **A store written by the earlier build loads.** Under `-fixed-config` a device-ID binding is re-keyed to `pw:` with its
  keypair and address kept, and a binding to a deleted device is dropped. The reconcile also never leaves one again.
  Before, a removal left such a binding and the next start failed validation (`references missing device`), permanently.
- A `pw:` key is validated as "pw:" + a stored password, so a long password cannot make the store invalid.

The owner password stays the `-password` flag, never in `desired.json`.

## Validation (2026-09-14, namespaces only)

Real xxcipherx client (with a test-only static-TURN-credentials change that lives outside `forks/`) → local pion TURN →
server invoked exactly as `swg-noded` runs it (`-no-nat -desired … -password <owner> -max-passwords N -fixed-config`).
Control = `v2.0.0.70` + the previous patch; fixed = this `build.sh` output. Host ruleset and link list unchanged across
every run.

| test | control (2.0.0.70) | fixed (2.0.0.72) |
|---|---|---|
| T1 reach from the assigned address | 3/3 | 3/3 |
| T2 spoofed source at the server TUN | 0 packets (3 from the assigned address) | 0 (3) |
| T4 same password, second device ID | `DENIED:device_mismatch` | same address, same keypair |
| T5 unrelated roster change (add a password) | 2 devices reaped; live session 0/3; next client took the address; reconnect got a new address and key | 0 reaped; 3/3; address and key unchanged |
| T7 owner password's live session across that change | 0/3, device deleted | 3/3, device kept |
| T0 password added by SIGHUP connects | no config in 35 s | config at once |
| T3 revoke: live session / unrelated user / reconnect | 0/3 / **0/3** / refused | 0/3 / 3/3 / refused |
| T6 restart after the revoke | **refuses to start** (`references missing device`) | starts; the user keeps its address |
| T6b upgrade: start on the store control refused | — | starts, drops the dangling binding; that user connects, 3/3 |
