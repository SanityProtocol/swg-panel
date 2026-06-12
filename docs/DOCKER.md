# Docker

Two images and one compose file with three profiles.

```
docker compose --profile host up -d         # panel only
docker compose --profile node up -d         # entry server only
docker compose --profile host-node up -d    # panel + a local entry server
```

Copy `.env.example` to `.env` and set the values (`PANEL_PASSWORD` is required). The flow
matches bare-metal: bring up the panel, **Nodes → Add node** to mint a token, set
`NODE_TOKEN`, then start the node profile. For `host-node`, point the node at the panel's
service name: `PANEL_URL=https://swg-panel:8443`.

## Images

- **`swg-panel`** (`Dockerfile`) — pure Python + openssl. Serves the UI, TLS, login, and
  the node-sync API. State persists in `./data` (`/etc/swg-panel`, `/var/lib/swg-panel`,
  `/var/www/wgstats`). Mount a real cert over `/etc/swg-panel/tls/` if you have one.
- **`swg-node`** (`Dockerfile.node`) — builds the userspace **`amneziawg-go`** datapath
  plus the `awg` tools, brings the interface up, and runs `swg-noded`. A container cannot
  load the host kernel module, so this is the userspace path. Requires `NET_ADMIN` +
  `/dev/net/tun`.

## The node's interface

By default the entrypoint generates a plain-WireGuard server conf from `NODE_ADDRESS` /
`NODE_LISTEN_PORT`. For AmneziaWG obfuscation, mount a full server conf:

```yaml
    volumes:
      - ./awg0.conf:/etc/swg-node/awg0.conf:ro
```

## Note

The `swg-node` image compiles `amneziawg-go` from source at build time and exercises a
userspace tun device — smoke-test it on a real Docker host. For best throughput, a
**bare-metal** node with the kernel module (`install-node.sh`) is preferable.
