# swg-panel-server — the control plane

A single stdlib-Python program. It serves the web UI, its own TLS + login, the
`/wgstats` status board, and two HTTP APIs. No database; state is the JSON files in
[the data model](STATE.md).

## What it owns

- the **roster** (`users.json`) and **node store** (`nodes.json`);
- IP allocation, and the per-node **desired peer set** computed from the roster;
- client-config inputs (server key/endpoint/AWG params) taken from each node's snapshot.

## Config — `/etc/swg-panel/fleet.json`

```json
{
  "roster_path":   "/var/lib/swg-panel/users.json",
  "nodes_path":    "/var/lib/swg-panel/nodes.json",
  "stats_dir":     "/var/www/wgstats",
  "store_configs": false,
  "config_dir":    "/var/lib/swg-panel/configs",
  "node_interval": 5
}
```

## Environment

`SWG_PANEL_FLEET`, `SWG_PANEL_WEB`, `SWG_PANEL_HOST`, `SWG_PANEL_PORT`, `SWG_PANEL_AUTH`
(a `user:pbkdf2_sha256$…` file; blank = no login), `SWG_PANEL_TLS_CERT` /
`SWG_PANEL_TLS_KEY` (blank = plain HTTP).

## Endpoints

**Node-facing** — `Authorization: Bearer <node-token>`:

- `POST /api/node/sync` — body `{snapshot}`; returns `{desired, interval}`. Identifies the
  node by its token, caches the snapshot, and writes it to the status board.

**Admin** — HTTP Basic auth; mutations are serialized:

- `GET  /api/fleet` · `GET /api/nodes` · `GET /api/roster` · `GET /api/describe?node=` ·
  `GET /api/next-ip?nodes=&iface=` · `GET /api/config?pubkey=&node=`
- `POST /api/add-peer` · `POST /api/remove-peer` · `POST /api/rename` · `POST /api/adopt`
- `POST /api/nodes/create` (→ one-time token) · `/api/nodes/update` · `/api/nodes/rotate`
  (→ new token) · `/api/nodes/delete`

## TLS + serve modes

Standalone (default) binds `0.0.0.0:PORT` and serves its own TLS + login. The installer
can also put it behind nginx. Certificates come from `selfsigned`, `letsencrypt`
(`acme.sh --standalone`, needs port 80), `cloudflare` (DNS-01, no port 80), or `manual`.
