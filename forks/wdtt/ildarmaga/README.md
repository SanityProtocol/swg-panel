# WDTT server — ildarmaga fork (swg-panel patched build)

Second server fork in the WDTT family (alongside `../` = amurcanov). Same `wdtt://` wire, same
WRAP/GETCONF/DTLS protocol, **byte-identical crypto** — so the same client apps (anton48 iOS,
WDTT/qWDTT Android, PWDTT desktop) work against either fork.

Upstream: https://github.com/ildarmaga/wdtt — a Go workspace (`.` + `./panel` + `./server`). We build
**only** `server/cmd` (the standalone datapath server); the bundled web panel (`:2860`), subscription
server (`:2096`), SQLite panel, and Xray routing are NOT built or used — the swg-panel is the control
plane.

## Build

```bash
./build.sh                 # → wdtt-ildarmaga-server-amd64 (static)
GOARCH=arm64 ./build.sh    # → wdtt-ildarmaga-server-arm64
```

Requires a Go 1.25 toolchain. `CGO_ENABLED=0` static build (pure-Go `modernc.org/sqlite`).

## Patch (`wdtt-ildarmaga.patch`, pinned to upstream `ce79eeae` — v1.4.63)

~46 lines across `server/{config,server,server_util,server_wg}.go`. Adds these flags (defaults keep
stock behavior when absent):

| flag | effect |
|---|---|
| `-iface <name>` | WG interface name (multi-instance per node) |
| `-wg-addr <cidr>` | server WG address/subnet, e.g. `10.66.70.1/24` |
| `-mtu <n>` | WG MTU |
| `-max-users <n>` | per-instance password/user cap (else stock default; subnet is the real ceiling) |
| `-no-nat` | node owns host NAT/sysctls → skip `setupFullConeNAT` + `syncVPNLocalServices` + `enableBBR` (all host mutation). Under `-no-nat` the server touches only its own TUN; a clean stop self-removes the iface. |

Headless run (server-only, no panel/SQLite — falls back to flags when there's no `panel.db`):

```bash
wdtt-ildarmaga-server -iface wdtt0 -wg-addr 10.66.66.1/24 -listen 0.0.0.0:56000 \
  -wg-port 56001 -config-dir /opt/swg-wdtt/wdtt0 -password <owner> -no-nat -max-users 200
```

## Validation (Phase 0 · R1, 2026-07-28)

Boot-verified headless on a live node under `-no-nat`: interface up on the parameterized subnet,
DTLS + WG listeners bound, **zero host mutation** (`WDTT_MANAGED` iptables count and TCP congestion
control unchanged from baseline), clean teardown (TUN self-clears, no rules to remove). The initial
`-no-nat` missed `syncVPNLocalServices`/`enableBBR`; the patch now guards all three host-mutation
paths at the function level.

Remaining Phase 0 gates for this fork: R3 (fixed-config device-agnostic peer — needs the fixed-config
patch + a GETCONF client harness) and R2 (routing/blocking datapath on a wdtt interface). Declarative
reconcile (the swg-noded integration) is deferred — ildarmaga exposes a localhost admin API
(`127.0.0.1:2861` `POST /admin/reload`) which is the likely hook, vs a `-desired` file patch.
