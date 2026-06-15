# Docker

Two images and one compose file with three profiles.

## One-liner

`install-docker.sh` (via `bootstrap.sh docker`) installs Docker if missing, stages the
project under `/opt/swg-panel-docker`, writes `.env`, and brings up a profile — passing the
profile as a bare word (`host` / `node` / `host-node`) and **prompting for what it needs**:

```
# panel        — asks for a domain + TLS choice (login auto-generated; change it later in the panel)
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s docker host
# entry server — asks for the panel URL + key (from Nodes → Add node) + endpoint
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s docker node
# panel + a local node
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s docker host-node
```

Flags skip the matching prompt (the panel's enroll command uses them): `-pass`, `-domain`,
`-base` (subpath, e.g. `/swg`), `-port`, `-tls letsencrypt|cloudflare|cf15|selfsigned|none`,
`-email`, `-cf-token`, `-cf-origin`, `-key`, `-host`, `-endpoint`, `-iface`, `-ifaces`.
`--profile <p>` also still works. Re-run from `/opt/swg-panel-docker` after editing `.env`:
`docker compose --profile <p> up -d`.

## TLS

The panel image bundles **acme.sh**, so the container issues real certificates itself — the
same options as bare-metal:

| `TLS=` | What it does | Needs |
|---|---|---|
| `letsencrypt` | Let's Encrypt over HTTP-01 | port **80** published (compose maps `80:80`), DNS → this host, `ACME_EMAIL` |
| `cloudflare` | Let's Encrypt over DNS-01 (no port 80) | `CF_TOKEN` (Zone:DNS:Edit + Zone:Read), `ACME_EMAIL` |
| `cf15` | 15-year Cloudflare **Origin** cert — only valid behind CF's proxy | `CF_ORIGIN_TOKEN` (Zone → SSL and Certificates → Edit) |
| `selfsigned` | self-signed (default) — fine for testing | — |
| `none` | plain HTTP — only behind a tunnel/reverse-proxy | — |

acme.sh state and the issued cert persist under `./data/etc` (`/etc/swg-panel/{acme,tls}`),
so a restart renews/reuses rather than re-issuing. A cert mounted over
`/etc/swg-panel/tls/fullchain.pem` always wins and skips acme entirely.

**Renewal** is automatic for `letsencrypt`/`cloudflare`: the container runs `acme.sh --cron`
every 12h, re-issues once a cert nears expiry, and signals the panel (`SIGHUP`) to reload the
new cert into its live TLS context — **no downtime, no restart**. `cf15` (15y) and
`selfsigned` (10y) are long-lived and not auto-renewed; `none` and mounted certs are managed
by you.

## By hand

```
docker compose --profile host up -d         # panel only
docker compose --profile node up -d         # entry server only
docker compose --profile host-node up -d    # panel + a local entry server
```

Copy `.env.example` to `.env` and set the values (`PANEL_PASSWORD` is required). The flow
matches bare-metal: bring up the panel, **Nodes → Add node** to mint a key, set
`NODE_TOKEN`, then start the node profile. For `host-node`, point the node at the panel's
service name: `PANEL_URL=https://swg-panel:8443`. Set `PANEL_BASE=/swg` to mount the panel
under a subpath.

## Images

By default `docker-compose.yml` **pulls prebuilt multi-arch images from GHCR**
(`ghcr.io/sanityprotocol/swg-panel`, `…/swg-node`) — no local build, no Docker Hub limit.
`PULL_POLICY=always` to always re-pull the latest. To build from source instead, comment the
`image:` line and uncomment the `build:` block for that service.

- **`swg-panel`** — pure Python + openssl + bundled **acme.sh**. Serves the UI, issues/serves
  TLS (see above), login, and the node-sync API. State persists in `./data`
  (`/etc/swg-panel`, `/var/lib/swg-panel`, `/var/www/wgstats`). Mount a real cert over
  `/etc/swg-panel/tls/` to override acme.
- **`swg-node`** (`Dockerfile.node`) — builds the userspace **`amneziawg-go`** datapath
  plus the `awg` tools, brings the interface up, and runs `swg-noded`. A container cannot
  load the host kernel module, so this is the userspace path. Requires `NET_ADMIN` +
  `/dev/net/tun`.

## The node's interfaces

The entrypoint manages one or several interfaces, from the first source that applies:

1. **Mounted confs** — every `/etc/swg-node/*.conf` is managed as-is (one file per
   interface; the way to ship your own AmneziaWG obfuscation):
   ```yaml
       volumes:
         - ./awg0.conf:/etc/swg-node/awg0.conf:ro
         - ./wg1.conf:/etc/swg-node/wg1.conf:ro
   ```
2. **`NODE_IFACES`** — generate several: `name:port:address[:proto]` entries,
   comma-separated (`:wg` = plain WireGuard, otherwise AmneziaWG v2). Example:
   `awg0:51820:10.8.0.1/24,wg1:51821:10.9.0.1/24:wg`.
3. **Single (default)** — `NODE_IFACE` / `NODE_LISTEN_PORT` / `NODE_ADDRESS`, AmneziaWG v2
   (or plain with `NODE_PLAIN_WG=yes`).

Publish each interface's `ListenPort` in the compose `ports:` list so clients can reach
it. All managed interfaces sync to the panel and appear in the Nodes screen.

## Turn-proxy

`docker node` / `docker host-node` run a **TURN-PROXY** step after `compose up` (same as
bare-metal): it installs [vk-turn-proxy](https://github.com/cacggghp/vk-turn-proxy) as a
**host** systemd service forwarding to the container's published wg port
(`-connect 127.0.0.1:<NODE_LISTEN_PORT>`). Press Enter to skip, or `new` to install a fork.

## Note

The `swg-node` image compiles `amneziawg-go` from source at build time and exercises a
userspace tun device — smoke-test it on a real Docker host. For best throughput, a
**bare-metal** node with the kernel module (`install-node.sh`) is preferable.
