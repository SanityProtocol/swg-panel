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
`SWG_PANEL_TLS_KEY` (blank = plain HTTP), and `SWG_PANEL_BASE` (optional subpath mount,
e.g. `/swg` — the server strips it from request paths and rewrites the SPA's `<base href>`
so the panel can live under an existing site; blank = served at root).

## Endpoints

**Node-facing** — `Authorization: Bearer <node-token>`:

- `POST /api/node/sync` — body `{snapshot}`; returns `{desired, interval}`. Identifies the
  node by its token, caches the snapshot, and writes it to the status board.

**Admin** — HTTP Basic auth; mutations are serialized:

- `GET  /api/fleet` · `GET /api/nodes` · `GET /api/roster` · `GET /api/describe?node=` ·
  `GET /api/next-ip?nodes=&iface=` · `GET /api/config?pubkey=&node=` · `GET /api/account`
- `POST /api/add-peer` · `POST /api/copy-peer` · `POST /api/remove-peer` ·
  `POST /api/rename` · `POST /api/adopt` · `POST /api/account` (change login)
- `POST /api/nodes/create` (→ one-time key) · `/api/nodes/update` · `/api/nodes/rotate`
  (→ new key) · `/api/nodes/delete`

## TLS + serve modes

The installer offers four serve modes. **internal** (default) binds `0.0.0.0:PORT` and
serves its own TLS + login. **nginx** / **caddy** keep the panel on a loopback port and put
a reverse proxy in front (TLS terminated there; a subpath becomes a `location`/`handle`
block). **skip** leaves the panel on loopback for you to front yourself. Every mode uses the
panel's own pbkdf2 login (`SWG_PANEL_AUTH`), so the Account tab works throughout.

Certificates come from `letsencrypt` (`acme.sh`, port 80; the default), `cloudflare`
(DNS-01, no port 80), `cf15` (a 15-year Cloudflare **Origin** cert via the CF API — only
valid behind Cloudflare's proxy), `selfsigned`, or `skip` (bring your own / terminate elsewhere).
