# csqtt — swg-panel integration patch

`csqtt` (github.com/amurcanov/csqtt) is amurcanov's Rust rewrite and the successor to WDTT — a **raw-IP TUN**
VK-TURN proxy (no WireGuard), its own web panel. This directory holds the patch that makes it manageable by
swg-panel the same way the `wdtt/` forks are, plus a reproducible build.

- **`csqtt-swgpanel.patch`** — pinned to upstream `446293aa` (**v2.1.9**, 2026-09-02). Applies with
  `git apply` from the repo root of a fresh csqtt clone. Verified apply-clean + build-clean on amd64.
  Our build label is **2.1.9-2** (source 2.1.9 + this patch, including the 2026-09-14 keyless source-integrity
  fixes below), published as `csqtt-2.1.9-2` (2026-09-17), amd64 + arm64, and rig-proven on the published amd64 bytes.
  The patch here is now **2.1.9-3**: 2.1.9-2 plus one config on several devices (below). It is rig-proven on a local
  build and **not yet published**, so the node still installs 2.1.9-2.
- **`build.sh <out> [amd64|arm64]`** — clone→checkout pin→apply patch→`cargo zigbuild` static musl binary.
  Needs rustup 1.97.1 + zig + cargo-zigbuild.

## Keyless source-integrity fixes (build 2.1.9-2, 2026-09-14)

For a csqtt instance to be a **share source** for a restricted network, a packet's source address must prove
which identity sent it. Stock csqtt did not enforce this. This patch adds:

- **Uplink source check at both TUN writers** (`protocol.rs`: `write_ingress_packet` and the `InjectTun`
  command path). A packet is written to the server TUN only if it is IPv4 whose source equals the address the
  panel assigned to that session. The assigned address is recorded **with** the ingress packet, so a session
  slot reused before a reassembled packet is flushed cannot misattribute it. Stock wrote any client-chosen
  source unchecked (an in-tunnel spoof).
- **Address is bound to the authenticating password.** `resolve_session_ip` (`model.rs`) now resolves only the
  device bound to the session's password (or the main device for the main password), never a device the client
  merely names; and `getconf_credential_access` (`protocol.rs`) refuses to bind an *unbound* password to a
  device id that is already registered. Together these stop a second valid password from adopting the first
  client's device id and inheriting its address ("device borrow").
- **Shard tables follow `--tun-addr`.** The two hardcoded `[10, 66, 67]` prefixes in `dataplane.rs` (the TUN-RX
  shard index and `BindTunnel`) now read `swgpanel::subnet_prefix()`, matching the already-fixed
  `tun_device::route_index` — a non-default `--tun-addr` shards downlink consistently on multi-shard nodes.
- ⚠️ **Side effect on csqtt's own web panel** (off under `--no-web`, which is how the node runs it): *unbind* clears a
  password's binding but keeps the device row, so that same device reconnecting is now refused `device_mismatch`; a
  new device id binds normally.
- Measured on a namespace rig (real client through a local pion TURN relay, 2.1.9 as control): spoofed source
  **+4 → +0** at the server TUN; a second password presenting the first's device id was handed its address → now
  refused. Reach, revocation cut and a stable address hold on both. The `InjectTun` path and shards > 1 are not rigged.

## One config on several devices (build 2.1.9-3, 2026-09-24, not yet published)

Stock csqtt binds a password to the first device ID that connects and refuses every other device with
`DENIED:device_mismatch`. The client shows this as `пароль привязан к другому устройству`. So a user who moved their
config to a second phone was locked out. The WDTT servers never had this problem: the node runs them with
`-fixed-config`. This build gives csqtt the same behaviour.

- **Under `--desired` (the node always passes it), a bound password follows its user to another device.**
  - A `GETCONF` from a different device ID gets `CredentialAccess::Rebind` instead of a refusal.
  - `rebind_password_device` moves the binding **and the device row (address, keys)** to the new ID.
  - This password's sessions on the old device are then dropped. They carry the old device ID, so the epoch purge
    keyed by the new ID would never reach them.
  - Those sessions are dropped under the same store write lock that moves the password, just as upstream's
    `purge_stale_device_sessions` runs under it. A `GETCONF` that moves the password straight back (both devices
    connecting at the same moment) takes that lock afterwards. So the move and its drop can't interleave with the
    move back, and neither can drop the device that ends up holding the password.
  - The newest device wins, like one WireGuard key used on two phones.
  - There is deliberately no damping. It would also refuse a phone that resumes its old session after sleep, which
    is a legitimate switch back. Measured with both devices left on, there is no storm (S in the table below).
  - ⚠️ The displaced device's app keeps showing "connected" but carries nothing until the user reconnects it. On
    this path the server's close reaches the client as silence, and the client does not redial on its own.
  - Without `--desired`, and for the main password, stock's one-device lock stands.
- **Only onto a device ID nobody holds:** no row, not the main device, and no password bound to it. A binding can
  outlive its row, for example when no address was free. This is the 2.1.9-2 rule for an unbound claim, extended to
  bindings, so a password still can't take another credential's device. The borrow test (keyless T6) is still
  refused.
- **The move only happens if the new device can have an address.** When the old row stays behind (it is shared) and
  the pool is full, the password stays where it is.
  - The access check itself answers `NOCONF` (`rebind_plan` → `Blocked`), before an epoch, a session or anything
    else is set up for the new device.
  - The client retries later.
- **The first-time claim of an unbound password now uses the same "nobody holds it" test**
  (`device_is_unclaimed`). 2.1.9-2 checked for a row only, so a device held by a binding alone, or the main device,
  could be claimed by a second password.
- **A row another password or the main device still names stays where it is** (only in stores from before 2.1.9-2).
  - The new device gets its own row and address in that case.
  - The other credential's sessions on that row are left alone: the purge only touches the moving password's own
    sessions.
  - ⚠️ The password can't move back onto that shared device afterwards. The device now belongs to the credential
    still bound to it, so a move back would be the "device borrow" that 2.1.9-2 refuses. Nothing records where a
    password used to be, so the server can't tell a return from a borrow.
- **The store keeps stock csqtt's shape:** a password bound to a real device ID.
  - The node reads it unchanged: the address comes through `entry.device_id`, and traffic stays on the password row.
  - Any older build that the panel offers as a rollback target runs on it and finds each password on its latest
    device. Nothing needs migrating either way.
  - An earlier draft keyed each password to a synthetic `pw:<hash>` device instead (as `-fixed-config` does in WDTT).
    It was dropped because a rollback would have refused every user on every device, since no client presents that
    ID.
- **Upstream's `a_device_can_bind_multiple_passwords…` test** asserted the pre-2.1.9-2 borrow (`Unbound`). It now
  asserts the refusal and is renamed `a_registered_device_is_never_claimed_by_another_password…` to match. Two new
  tests cover the rebind decision and the row move. The panel-mode switch they flip is per thread and is reset by a
  guard when each test ends. A third test covers a device held only by a binding (for a move and for a first claim), and a full pool (`NOCONF`). `cargo test`:
  235 passed.

Rig (`.campaign/rigs/two-device-csqtt.sh`: two device namespaces ↔ local pion TURN ↔ server, real csqtt client, 9
workers). The control is 2.1.9-2.

| test | 2.1.9-2 | 2.1.9-3 |
|---|---|---|
| D1 device A connects | .2, 20/20 | .2, 20/20 |
| D2 A vanishes (no DISCONNECT), device B, same password | **refused** `пароль привязан к другому устройству` | .2, 50/50 |
| D3 A comes back while B is live | A 50/50 (B was never up) | A 50/50, B 0/10 (its sessions purged) |
| S both devices kept on for 60 s | — | no storm: 0 re-purges, 10 CPU ticks / 60 s; A 25/25, B stays replaced 0/25 |
| D4 store | one device row | one device row (the latest device), traffic on the password row |
| D5 revoke: live device / fresh device | 0/10 / refused | 0/10 / refused |
| D6 another password presenting A's device ID | refused | refused |
| D7 store written by 2.1.9-2, new device on 2.1.9-3 | — | keeps .2 (row moved); the other password keeps .3 |
| D8 rollback: 2.1.9-2 on that store | — | the latest device keeps .2, the older one is refused (stock), nobody is locked out |
| D9 a row two passwords share: one moves to a new phone | — | it gets its own address (.3); the other password's live session on the shared row is untouched (20/20); moving back onto the shared device is refused (borrow rule) |
| server CPU after each switch | ≤ 2 ticks / 5 s | ≤ 1 tick / 5 s |

keyless-csqtt T1–T6 (source check, revoke, borrow) pass unchanged. The host firewall and links were unchanged by every
run.

## What the patch adds (every flag defaults to STOCK when absent; the source-integrity fixes above apply with or without flags)

| flag | effect |
|---|---|
| `--iface <name>` | TUN interface name (stock: `csqtt1`) — multi-instance |
| `--tun-addr <ip>/24` | TUN gateway + subnet, e.g. `10.66.68.1/24` (stock: `10.66.67.1/24`). /24 only (the datapath route table indexes by last octet). Drives the fast-path `route_index` and the IPAM pool together. |
| `--no-web` | run headless: no web admin panel (it binds `0.0.0.0`), no self-signed cert generation, no TLS reload loop, and no DPI/syscalls monitor sockets — those bind fixed loopback ports (46003/46004) that collide on a multi-instance node, and the panel owns all state via `--desired`. |
| `--desired <path>` | declarative desired-passwords JSON, **panel-owned** input; reconciled on start + SIGHUP + 3s mtime poll, **no restart / no tunnel drop**. csqtt's own expiry janitor is disabled in this mode (panel owns expiry). |
| `--no-nat` | ⚠️ **accepted but INERT since 2.1.5** — see below |
| `--max-passwords <n>` | raise the generated-password cap (stock: 20). Inert under `--no-web`: only the web panel's `clients_create` reads it. |

### Two flags are kept deliberately dead

`--no-nat` and `--max-passwords` no longer do anything in the way we run csqtt, and they are kept anyway
because **every installed node writes them into its systemd unit and `clap` exits on an unknown argument**.
Removing either would stop every existing csqtt instance on the update that shipped it, at the moment the
node restarts the server. They are documented as inert rather than quietly dropped.

`--no-nat` specifically: up to 2.0.1 the binary ran `enable_ipv4_forwarding()` + `setup_nat()` itself, and the
flag skipped them so the node could own NAT. In 2.1.5 upstream gutted `net_setup.rs` from 94 lines to two
constants and moved NAT into its own `deploy.sh`, so the binary no longer touches NAT at all — the node owns
it unconditionally, with or without the flag.

## desired.json shape (panel writes it)

```json
{ "passwords": [
    { "password": "P1", "name": "alice", "expires_at": 0, "vk_hash": "", "is_deactivated": false }
] }
```

Reconcile: adds new / removes generated passwords no longer listed (and their bound device), and updates
`expires_at / vk_hash / name / is_deactivated` on existing ones — **never** touching `device_id / up_bytes /
down_bytes` (csqtt owns those runtime fields). The main `--password` is never managed via desired.json.
Removals really persist: upstream's `write_database_snapshot` is a **full sync** that deletes store rows
absent from the snapshot it is given.

## Notes for the next re-port

- Upstream renamed `csqtt-uring/` → **`rust-server/`** and `uring_io.rs` → `tokio_io.rs` (the dataplane moved
  from io_uring to a `current_thread` Tokio runtime with readiness epoll). Paths in the patch follow.
- **The store moved from `passwords.json` to SQLite `csqtt.db`** (WAL), and the first start of 2.1.5 imports
  the JSON and **deletes it**. `swg-noded` reads whichever exists (`_csqtt_read_store`), so both server
  versions work — but a rollback to 2.0.1 finds no JSON and loses device bindings and traffic counters. The
  password set itself comes back from `desired.json` on the next sync.
- **Three earlier workarounds were dropped because upstream fixed them**: the raw SIGTERM handler (2.1.5
  handles SIGTERM properly and bounds every shutdown step), the NAT skip (see above), and the guard around
  `cleanup_orphaned_policy` (now wrapped in a 1s timeout that logs instead of failing the boot).
- ⚠️ **arm64 needs `-C link-self-contained=no`.** Upstream's `.cargo/config.toml` sets it for `x86_64` only,
  because they never build arm64; without it rustc adds its own `crt1.o` beside zig's and `ld.lld` fails with
  `duplicate symbol: _start`. `build.sh` sets it for both arches so the two builds stay identical.
- 2.1.5 added C/C++ dependencies — `rusqlite` (bundled SQLite) and `snmalloc-rs` (`build_cc`) — so the `cc`
  crate needs an explicit cross compiler. `build.sh` writes `zig cc` / `zig c++` / `zig ar` wrappers and
  exports `CC_/CXX_/AR_<target>`, mirroring upstream's own `rust-server/build_linux.sh`.
- v2.1.5 ships a **hand-written** `--help`, not clap's generated one, so our flags do not appear in it. They
  parse correctly; this is cosmetic and matches 2.0.1.

csqtt is **PolyForm-Noncommercial-1.0.0** — build and run only for non-commercial use.
