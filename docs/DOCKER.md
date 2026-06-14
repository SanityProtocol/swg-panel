# Docker

Two images and one compose file with three profiles.

## One-liner

`install-docker.sh` (via `bootstrap.sh docker`) installs Docker if missing, stages the
project under `/opt/swg-panel-docker`, writes `.env`, and brings up a profile:

```
# panel only
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh \
  | sudo bash -s docker -pass SECRET -domain panel.example.net

# panel + a local node
… | sudo bash -s docker --profile host-node -pass SECRET -key NODE_KEY -endpoint 203.0.113.7

# node only
… | sudo bash -s docker --profile node -key NODE_KEY -host https://panel.example.net -endpoint 203.0.113.7
```

Flags: `--profile host|node|host-node`, `-pass`, `-domain`, `-base` (subpath, e.g. `/swg`),
`-port`, `-tls selfsigned|none`, `-key`, `-host`, `-endpoint`, `-iface`. Re-run from
`/opt/swg-panel-docker` after editing `.env`: `docker compose --profile <p> up -d`.

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

- **`swg-panel`** (`Dockerfile`) — pure Python + openssl. Serves the UI, TLS, login, and
  the node-sync API. State persists in `./data` (`/etc/swg-panel`, `/var/lib/swg-panel`,
  `/var/www/wgstats`). Mount a real cert over `/etc/swg-panel/tls/` if you have one.
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

## Note

The `swg-node` image compiles `amneziawg-go` from source at build time and exercises a
userspace tun device — smoke-test it on a real Docker host. For best throughput, a
**bare-metal** node with the kernel module (`install-node.sh`) is preferable.
