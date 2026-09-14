# WDTT server — ildarmaga fork (swg-panel patched build)

Second server fork in the WDTT family (alongside `../` = amurcanov). Same `wdtt://` wire, same
WRAP/GETCONF/DTLS protocol, **byte-identical crypto** — so the same client apps (anton48 iOS,
WDTT/qWDTT Android, PWDTT desktop) work against either fork.

Upstream: https://github.com/ildarmaga/wdtt — a Go workspace (`.` + `./panel` + `./server`). We build
**only** `server/cmd` (the standalone datapath server); the bundled web panel (`:2860`), subscription
server (`:2096`), SQLite panel, and Xray routing are NOT built or used — the swg-panel is the control
plane.

## Build label: `1.5.0-3` — and an honest word on the source

⚠️ **ildarmaga publishes no source past `ef69799`.** Its tags `1.5.40`, `1.5.55` and `1.5.61` all point
at that single docs commit, and the shipped `1.5.x` binaries were built from commits that were never
pushed (the `1.5.61` binary's `vcs.revision` is not on GitHub). So the newest *buildable* source is the
`v1.5.0` tree at `ef69799`. We build **that**, plus our patch, and label the result **`1.5.0-3`** rather
than borrow a `1.5.40`/`1.5.61` number we cannot reproduce. What an earlier note called "1.5.40-2" was in
truth source `1.5.0` + our patch; `1.5.0-3` is the same source with the K5 revocation/source fixes below.
Nothing here is published — this is a local build + rig proof only.

## Build

```bash
./build.sh                 # → wdtt-ildarmaga-server-amd64 (static)
GOARCH=arm64 ./build.sh    # → wdtt-ildarmaga-server-arm64
```

Requires a Go 1.25 toolchain. `CGO_ENABLED=0` static build (pure-Go `modernc.org/sqlite`).

## Patch (`wdtt-ildarmaga.patch`, pinned to upstream `ef69799` — `v1.5.0`)

Across `server/{config,server,server_conn,server_raw,server_util,server_wg}.go`, `cmd/wdtt/main.go`, and
new files `server/desired_ingest.go` (+ tests). Adds these flags (defaults keep stock behavior when
absent):

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

## Security fixes in `1.5.0-3` (NETWORKS §16 · K5)

The patch also closes the keyless-fork revocation/source defects, each proven on a namespace rig
(`cli ↔ local pion TURN ↔ server`) with the pre-fix build (`ef69799` + the flags patch only) as control:

- **WG revocation now cuts access (the key defect).** `ingestDesiredFile` used `DeleteUser(sdb, pw, nil)`,
  which left the `pw:<password>` row in `wdtt_devices`; on reload the leftover device resolved to no user,
  `bindOrphanDeviceToMainLocked` re-homed it to the **owner** password, and its WG peer was re-added — the
  revoked client kept its tunnel. Now `DeleteUser` is given the password's device rows (`pw:<password>` under
  `-fixed-config`, plus any `wdtt_user_devices` bindings), and `passwordForDeviceLocked` /
  `bindOrphanDeviceToMainLocked` resolve a `pw:<password>` device to exactly that password — never the owner —
  so a revoked password's device becomes an orphan the reload drops. Measured: live session ping after
  revoke went **3→0**; the address stays stable across reconnects and an unrelated roster change.
- **RAW source check no longer skipped for qWDTT sessions.** The relay loop skipped
  `rawIPv4SourceMatches` for `GETCONF_RAW` (qWDTT-protocol) sessions, letting such a client write any source
  into the TUN. The check now applies to every session. Measured: spoofed-source packets reaching the server
  RAW TUN went **3→0**, legit traffic unaffected.
- **RAW revocation cuts live sessions + frees the address.** Removing a password now cancels its live RAW
  sessions (`cancelRawSessionsForPassword`) and returns its pool address (`freeRawIPsForPassword`). Measured:
  live RAW session ping after revoke went **3→0**.
- **A revoke never deletes a device row another password still binds.** `wdtt_user_devices` is keyed
  `(password, device_id)`, so one `wdtt_devices` row can belong to several passwords; the revocation fix hands
  `DeleteUser` only the bindings no other password shares (unit test `TestRevokeKeepsSharedDeviceRow`, red on the
  first version of this fix). Under `-fixed-config` — how the node runs it — generated passwords get no stock bindings,
  so this guards stores that picked some up before.
- Server CPU after a WG or RAW revoke stays at idle (3–6 ticks/10 s, control 4–5): the session cancel does not leave a
  spinning reader behind.

⚠️ **ildarmaga RAW stays excluded from network shares regardless** (fail-closed policy); its WG path and its
revocation are fixed here so a revoked user loses access on every path.

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
