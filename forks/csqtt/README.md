# csqtt — swg-panel integration patch (Phase A1)

`csqtt` (github.com/amurcanov/csqtt) is amurcanov's Rust rewrite and the successor to WDTT — a **raw-IP TUN**
VK-TURN proxy (no WireGuard), io_uring dataplane, its own web panel. This directory holds the patch that makes
it manageable by swg-panel the same way the `wdtt/` forks are, plus a reproducible build.

- **`csqtt-swgpanel.patch`** — pinned to upstream `31114cb7` (v2.0.1, 2026-08-17). Applies with
  `git apply` from the repo root of a fresh csqtt clone. Verified apply-clean + build-clean + fleet-validated.
- **`build.sh <out> [amd64|arm64]`** — clone→checkout pin→apply patch→`cargo zigbuild` static musl binary.
  Needs rustup 1.97.1 + zig + cargo-zigbuild (see the A0 scratchpad toolchain).

## What the patch adds (every flag defaults to STOCK when absent → an un-flagged binary is byte-for-byte upstream)

| flag | effect |
|---|---|
| `--iface <name>` | TUN interface name (stock: `csqtt1`) — multi-instance |
| `--tun-addr <ip>/24` | TUN gateway + subnet, e.g. `10.66.68.1/24` (stock: `10.66.67.1/24`). /24 only (the datapath route table indexes by last octet). Drives net_setup, the fast-path `route_index`, and the IPAM pool together. |
| `--no-nat` | skip `ip_forward` + iptables MASQUERADE/FORWARD/MSS — the **node owns NAT** for csqtt subnets |
| `--desired <path>` | declarative desired-passwords JSON, **panel-owned** input; reconciled on start + SIGHUP + 3s mtime poll, **no restart / no tunnel drop**. csqtt's own expiry janitor is disabled in this mode (panel owns expiry). desired.json = panel's sole-writer INPUT; `passwords.json` = csqtt's sole-writer OUTPUT → no write race. |
| `--max-passwords <n>` | raise the generated-password cap (stock: 20) |

Plus a **clean-stop fix**: stock csqtt registers tokio's SIGTERM handler but leaves the notify unconsumed, so
SIGTERM is neither handled nor fatal and the box must SIGKILL. Under `--no-nat` (our managed mode) the patch
installs a raw async-signal-safe handler that `_exit`s immediately — the node owns NAT (nothing to unwind) and
the store persists incrementally. Measured: SIGTERM → exit in ~3 ms; the TUN auto-drops within ~2 s.

## desired.json shape (panel writes it)

```json
{ "passwords": [
    { "password": "P1", "name": "alice", "expires_at": 0, "vk_hash": "", "is_deactivated": false }
] }
```

Reconcile: adds new / removes generated passwords no longer listed (and their bound device), and updates
`expires_at / vk_hash / name / is_deactivated` on existing ones — **never** touching `device_id / up_bytes /
down_bytes` (csqtt owns those runtime fields). The main `--password` is never managed via desired.json.

## Fleet validation (svo-im, 2026-08-16)

Two isolated `--no-nat` instances (csqtt1/10.66.67.1 + csqtt2/10.66.68.1) ran together; host iptables +
ip_forward untouched; `--desired` add/update/remove all applied via SIGHUP with the **same PID** (no restart),
instance B unaffected; both exited cleanly on SIGTERM; ifaces auto-dropped; protected services (nginx/mongod)
untouched throughout.

## Not done here (later phases)

Build/host the binary in the panel mirror + `CSQTT_BUILDS` version board (A3) · arm64 build is supported by
`build.sh` but not yet exercised on hardware · node lifecycle/reconciler + unit template with io_uring syscall
allowances (A2). Nothing is published to GitHub until the whole csqtt integration is complete and tested.
