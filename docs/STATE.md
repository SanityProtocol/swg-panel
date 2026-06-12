# Data model

The panel keeps three kinds of state. You never edit them by hand — the UI and the
sync API do. All are plain JSON under `/var/lib/swg-panel` (state) and `/etc/swg-panel`
(config).

## Roster — `users.json` (desired peers)

Public-key-keyed. One entry is one identity that may live on several nodes:

```json
{
  "<public_key>": {
    "name": "alice", "ip": "10.8.0.5", "if": "awg0", "type": "user",
    "psk": "<base64>", "nodes": ["node1", "node2"],
    "created_at": 1700000000, "deleted_at": null
  }
}
```

- `if` is the interface the peer belongs to; on a multi-interface node it decides where
  the peer is applied.
- `psk` lives here so every node the peer is on stays consistent (the panel, not the
  node, owns it). The **private** key is never stored — it is generated in the browser
  and shown once.
- `nodes` is the list of node names the identity is deployed to. A legacy single `node`
  field is still honoured.

## Node store — `nodes.json`

Name-keyed node metadata + the enrollment-token hash:

```json
{
  "node1": {
    "name": "node1", "color": "#34d399", "endpoint_host": "203.0.113.7",
    "stats_file": "stats-node1.json",
    "token_hash": "pbkdf2_sha256$200000$…", "created": 1700000000
  }
}
```

The token itself is shown once at creation and only its hash is kept.

## Snapshots (observed state)

Each node POSTs this every `node_interval` seconds; the panel caches it in memory and
also writes it to `stats_dir/<stats_file>` for the status board:

```json
{ "hostname": "node1", "generated_at": 1700000000,
  "interfaces": { "awg0": {
    "peers": [ { "public_key": "…", "online": true, "handshake_age": 12,
                 "endpoint": "…", "allowed_ips": "10.8.0.5/32",
                 "rx_speed": 0, "tx_speed": 0 } ],
    "meta":  { "public_key": "…", "listen_port": 51820, "endpoint": "203.0.113.7:51820",
               "address": "10.8.0.1/24", "subnet": "10.8.0.0/24",
               "awg_params": { "Jc": 4, "…": 0 }, "dns": ["1.1.1.1"] } } } }
```

`meta` is what the panel and the browser use to allocate IPs and build client configs.

## Status (derived, never stored)

`reconcile.js` rolls a per-node deployment status up to a per-peer status on every
refresh: **online** (present everywhere live, ≥1 online) · **ready** (present, none
online yet) · **partial** (present on some live nodes, missing on others) · **pending**
(new, inside the grace window) · **dangling** (missing past grace) · **removing/gone**
(deleted, still/no longer present) · **unknown** (every target node is stale). Stale
nodes never count as "missing", so a peer stays online while a replica is briefly down.
