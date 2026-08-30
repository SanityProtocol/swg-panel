<p align="center"><b>English</b> · <a href="API.ru.md">Русский</a> · <a href="README.technical.md">Technical guide (EN)</a> · <a href="README.technical.ru.md">Техническое руководство (RU)</a></p>

---

# External Integration API

A **read-only** REST + Prometheus surface plus outbound **webhooks**, for wiring swg-panel into
external monitoring and automation — Grafana, Uptime Kuma, Prometheus, Terraform/Ansible, or your
own scripts. It exposes state the panel already collects from node syncs; it never changes the fleet.

- **Read-only.** No API token is accepted on any mutating endpoint. A leaked token can observe, never modify.
- **Panel-only.** Nodes are untouched — they sync exactly as before. The panel serves the API from the
  same in-memory snapshots + roster it already keeps. No extra load on nodes, no change to the sync loop.
- **Cheap.** Off the SPA's poll path; the whole-fleet view is cached ~3s and shared by every endpoint and
  scrape, so an aggressive Prometheus/Grafana setup can't degrade the panel.

Enable it in **Settings → Integrations**: mint a token (shown once), optionally add webhooks.

## Contents

- [Authentication](#authentication)
- [Endpoints](#endpoints)
- [Webhooks](#webhooks)
- [Examples](#examples)

## Authentication

Every endpoint except the liveness probes needs a token, sent one of three ways:

| where | how to send it | when to use it |
|---|---|---|
| header | `Authorization: Bearer <token>` | the default |
| header | `X-API-Key: <token>` | tools that reserve `Authorization` for their own auth |
| query | `?token=<token>` | tools that cannot set a header at all |

Tokens are minted in the UI (`swgp_…`); only a SHA-256 hash is stored. An admin session cookie also
authenticates (so the settings page can preview). Turning the API **off** rejects all tokens immediately.

`GET /healthz` and `GET /api/v1/health` are **unauthenticated** liveness probes and expose no secrets.

## Endpoints

### `GET /healthz`
Plain-text `ok` — for uptime probes / load balancers. No auth.

### `GET /api/v1/health`
Liveness + coarse counts. No auth.
```json
{ "status": "ok", "version": "1.8.4-beta",
  "nodes": { "total": 5, "online": 5 },
  "peers": { "total": 27, "online": 20 } }
```

### `GET /api/v1/servers`
Every node with status + counts + throughput. Mesh-link interfaces are excluded — counts are client-facing.
```json
{ "servers": [
  { "id": "1b8e0bcb0b4c", "name": "moscow-1",
    "status": "online", "online": true,          // status: online | offline | never_seen
    "kind": "baremetal", "version": "1.8.4-beta",
    "hostname": "moscow-1", "endpoint_host": "203.0.113.11", "routing_mode": "kernel",
    "interfaces": ["awg0"],
    "peers": 10, "peers_online": 8,
    "rx_bytes_per_sec": 1096290, "tx_bytes_per_sec": 658712,
    "last_seen": 1783620087, "last_seen_age_s": 4,
    "cpu_percent": 59.5, "cpu_max_percent": 97.0, "cpu_saturated_cores": 1, "cpu_cores": [97, 22],
    "cpu_iowait_percent": 1.4, "mem_percent": 52.8, "disk_percent": 45.0, "uptime_s": 3543645 } ] }
```

### `GET /api/v1/servers/{id}`
One server (accepts the node **id or name**). Same shape as an element of `/servers`.

### `GET /api/v1/servers/{id}/peers`
Peers observed on that node, with **last-handshake timing**, enriched from the roster.
```json
{ "node": "1b8e0bcb0b4c", "name": "moscow-1", "peers": [
  { "peer_id": "p_9d40f5665d", "public_key": "1+5Gf…=", "iface": "awg0",
    "user": "bob", "title": null, "address": "10.8.0.10",
    "online": true, "endpoint": "203.0.113.9:51820",
    "last_handshake": 1783620085, "handshake_age_s": 2,
    "rx_bytes": 1771968226, "tx_bytes": 1757010049,
    "rx_bytes_per_sec": 413322, "tx_bytes_per_sec": 247993 } ] }
```

### `GET /api/v1/peers`
Roster-wide peer identities with per-target presence. A peer is `online` if it's online on **any** of its
deployed nodes (matching the panel's most-alive-wins view for multi-node peers).
```json
{ "peers": [
  { "peer_id": "p_9d40f5665d", "public_key": "1+5Gf…=", "title": null,
    "user": "bob", "user_id": "u_…", "online": true, "last_handshake": 1783620085,
    "targets": [ { "node": "1b8e0bcb0b4c", "iface": "awg0", "address": "10.8.0.10",
                   "online": true, "node_live": true } ] } ] }
```

### `GET /api/v1/summary`
Fleet totals.
```json
{ "version": "1.8.4-beta",
  "nodes": { "total": 5, "online": 5 }, "peers": { "total": 27, "online": 20 },
  "throughput": { "rx_bytes_per_sec": 2082447, "tx_bytes_per_sec": 1249463 },
  "generated_at": 1783620181 }
```

### `GET /metrics`
Prometheus text exposition (`v0.0.4`). **Per-node cardinality only** — never per-peer, which would
explode the series count on a large fleet (peer detail lives in the JSON API). Series:

| metric | type | labels | meaning |
|---|---|---|---|
| `swg_panel_up` | gauge | — | 1 whenever the panel answers |
| `swg_panel_build_info` | gauge | `version` | build info (value 1) |
| `swg_nodes_total` / `swg_nodes_online` | gauge | — | fleet node counts |
| `swg_peers_total` / `swg_peers_online` | gauge | — | fleet peer counts |
| `swg_fleet_rx_bytes_per_second` / `…_tx_…` | gauge | — | fleet aggregate throughput |
| `swg_node_up` | gauge | `node`,`name` | 1 online / 0 offline |
| `swg_node_peers` / `swg_node_peers_online` | gauge | `node`,`name` | per-node peer counts |
| `swg_node_rx_bytes_per_second` / `…_tx_…` | gauge | `node`,`name` | per-node throughput |
| `swg_node_last_seen_timestamp_seconds` | gauge | `node`,`name` | last sync (unix) |
| `swg_node_cpu_percent` / `_memory_percent` / `_disk_percent` | gauge | `node`,`name` | host health |
| `swg_node_cpu_max_percent` | gauge | `node`,`name` | busiest single logical CPU |
| `swg_node_cpu_saturated_cores` | gauge | `node`,`name` | count of logical CPUs ≥ 90% |
| `swg_node_cpu_iowait_percent` | gauge | `node`,`name` | time waiting on I/O — **not** CPU |
| `swg_node_uptime_seconds` | gauge | `node`,`name` | host uptime |

`swg_node_cpu_percent` is **CPU utilization, meaned across logical CPUs (0–100)** — a fully busy 8-CPU node
reads `100`, not `800`, so it is directly comparable across differently-sized nodes.
`swg_node_cpu_max_percent` and `swg_node_cpu_saturated_cores` catch what a mean hides: a pinned
single-threaded datapath saturates one CPU, and on 8 CPUs that is a mean of `12.5`. Alert on
`swg_node_cpu_saturated_cores > 0` rather than on the mean.

`swg_node_cpu_iowait_percent` is the share of time blocked on I/O. It **raises the load average but is not
CPU** — alerting on load alone is what makes a busy disk look like a busy processor.

> **Changed in 1.2.12-beta.** `swg_node_cpu_percent` previously reported *load average per core*, which
> counts uninterruptible-sleep tasks — so disk I/O and a brief fork storm (an ssh login) both read as
> "CPU", and the value could exceed 100. Alert thresholds tuned against the old meaning should be
> revisited. A node still running an older `swg-noded` falls back to the old load-per-core value until
> it is updated, and emits neither `swg_node_cpu_saturated_cores` nor `swg_node_cpu_iowait_percent`.

## Webhooks

The panel POSTs a signed JSON body to each configured URL when a subscribed event fires. Events:
`peer.added`, `peer.removed`, `node.online`, `node.offline`.

```json
{ "event": "node.offline", "ts": 1783620181,
  "data": { "id": "1b8e0bcb0b4c", "name": "moscow-1", "last_seen": 1783620090 } }
```

Every delivery carries a signature header so you can verify it came from the panel:

```http
X-SWG-Signature: sha256=<hex HMAC-SHA256(secret, raw_body)>
```

The secret is generated when you add the webhook (shown once). Delivery is best-effort with one retry;
node online/offline is derived from sync staleness, so `node.offline` fires when a node misses syncs past
the offline window (`NODE_OFFLINE`, 30s). The online/offline watcher does **no work at all** when you have
no webhooks configured.

## Examples

**Liveness** — no auth:

```bash
curl -s https://panel.example.com/api/v1/health
```

**The whole fleet** — with a token:

```bash
curl -s -H 'Authorization: Bearer swgp_…' https://panel.example.com/api/v1/servers | jq
```

**One node's peers**, with handshake timing:

```bash
curl -s -H 'Authorization: Bearer swgp_…' https://panel.example.com/api/v1/servers/moscow-1/peers | jq
```

**Prometheus** — scrape config:

```yaml
scrape_configs:
  - job_name: swg-panel
    metrics_path: /metrics
    authorization:
      credentials: swgp_…            # your API token
    static_configs:
      - targets: ['panel.example.com']
```

Uptime Kuma: add an **HTTP(s) - Keyword** monitor on `/api/v1/health`, keyword `"ok"`.

Terraform/Ansible: read `/api/v1/servers` and `/api/v1/peers` to discover fleet state for inventory or
drift checks (the API is read-only — provision through the panel UI/roster).
