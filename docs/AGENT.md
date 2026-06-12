# swg-agent — the peer actuator

A tiny program that applies exactly one change to a live wg/awg interface. It reads a
JSON request on stdin and writes a JSON result on stdout — no network, no state. It is
invoked by `swg-noded` during reconciliation (directly, or via `sudo -n` if
`node.sudo: true`).

## Operations

| op | does |
|---|---|
| `add-peer` | validate the public key + CIDR, ensure the IP is in-subnet/free, apply the peer to the running interface, and persist it to the `.conf` |
| `remove-peer` | remove the peer from the interface and the `.conf` |
| `describe` | report the interface `meta` (server key, port, subnet, AWG params, DNS) |
| `list-peers` | list current peers |
| `next-ip` | lowest free address in the subnet |

In the declarative model the panel drives `add-peer` / `remove-peer`; `describe` /
`next-ip` are computed panel-side from snapshots, so the node mostly only sees the two
mutating ops.

## Preshared keys

`add-peer` honours an explicit `preshared_key`:

- a literal base64 value → applied verbatim (this is what the panel sends, so client and
  node share the same key);
- `"auto"` / `""` → generate one;
- `"none"` / `null` → no PSK.

## Request / result

```json
{ "op": "add-peer", "iface": "awg0", "public_key": "…",
  "allowed_ips": "10.8.0.5/32", "preshared_key": "<base64|auto|none>", "name": "alice" }
```

Results are `{ "...": ... }` on success or `{ "error": "...", "code": "..." }` on failure;
peer ops are surgical — they never touch other peers on the interface.
