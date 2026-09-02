# csqtt — swg-panel integration patch

`csqtt` (github.com/amurcanov/csqtt) is amurcanov's Rust rewrite and the successor to WDTT — a **raw-IP TUN**
VK-TURN proxy (no WireGuard), its own web panel. This directory holds the patch that makes it manageable by
swg-panel the same way the `wdtt/` forks are, plus a reproducible build.

- **`csqtt-swgpanel.patch`** — pinned to upstream `de7afc23` (**v2.1.5**, 2026-08-28). Applies with
  `git apply` from the repo root of a fresh csqtt clone. Verified apply-clean + build-clean on amd64 + arm64.
- **`build.sh <out> [amd64|arm64]`** — clone→checkout pin→apply patch→`cargo zigbuild` static musl binary.
  Needs rustup 1.97.1 + zig + cargo-zigbuild.

## What the patch adds (every flag defaults to STOCK when absent → an un-flagged binary is byte-for-byte upstream)

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
