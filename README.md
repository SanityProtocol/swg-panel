# swg-panel

A self-hosted control panel for running a small WireGuard / AmneziaWG service across one or more entry servers. The panel is the source of truth for your peers; each entry server (a **node**) syncs to it over **outbound HTTPS** and converges on the peer set it has been assigned — so nodes need no inbound access, no SSH, and no rsync.

Built for small, trusted deployments — tens of users, a handful of servers — with multi-hop in mind (edge entry → distant exit).

## How it works

- **Panel** (control plane) — serves the web UI, its own TLS + login, and a node-sync API. It owns the roster (your peers) and the node store. Pure Python, no database.
- **Node** (entry server) — runs `swg-noded`, which every few seconds posts a snapshot of its interface to the panel, receives the peers it *should* have, and reconciles locally through `swg-agent` (adding/removing peers on the live wg/awg interface). Outbound HTTPS only.
- **Declarative** — you change peers in the panel; nodes converge. A node that misses a beat self-heals on the next sync, and a transient panel outage never wipes a node's peers (a node only reconciles on a valid reply).
- **Keys stay where they belong** — peer keypairs are generated in your browser. The private key goes into the config/QR you are shown **once** and never touches the server; the panel stores only the public key, the assigned IP, and the preshared key (so it can keep every node consistent).

## Contents

- [Method × Role](#method-role)
- [The pieces](#the-pieces)
- [Quick start](#quick-start)
- [Installing the panel](#installing-the-panel)
- [Adding a node](#adding-a-node)
- [Managing peers](#managing-peers)
- [Docker](#docker)
- [Configuration reference](#configuration-reference)
- [Operations](#operations)
- [Security](#security)
- [Troubleshooting](#troubleshooting)

## Method × Role

Two independent choices.

**Method** — how it is installed:
- **bare-metal** — systemd services, via `install-host.sh` / `install-node.sh`.
- **docker** — `docker compose` with the `swg-panel` / `swg-node` images.

**Role** — what a box does:
- **host** — the panel only.
- **host+node** — the panel *and* this box is also an entry server (auto-enrolled for you).
- **node** — an entry server only.

Mix freely: a Docker panel with bare-metal nodes, a bare-metal `host+node` plus extra Docker nodes, and so on.

## The pieces

| component | where | what it does |
|---|---|---|
| `swg-panel-server` | host | UI + node-sync API + roster/node store; serves its own TLS + login and the status board |
| `swg-noded` | each node | posts snapshots, pulls the desired peer set, reconciles locally — outbound HTTPS only |
| `swg-agent` | each node | applies a single peer add/remove to the live interface and its `.conf` |
| `users.json` | host | the **roster** — your peers (public key, IP, PSK, and which nodes each lives on) |
| `nodes.json` | host | the **node store** — node names, endpoints, and enrollment-token hashes |

You never edit `users.json` or `nodes.json` by hand — the UI does it.

## Quick start

### A — one box (panel + entry server), bare-metal

On a server that already runs (or will run) wg/awg:

```
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s host
```

Answer **host+node** when asked for the role, give it your public IP and interface, choose a TLS mode, and set an admin password. When it finishes, open `https://<your-host>:8443/`, log in, and you will find this box already listed under **Nodes**. Add peers from the UI (see [Managing peers](#managing-peers)).

### B — a panel and separate nodes, bare-metal

1. **Panel** — on the control box:
   ```
   curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s host
   ```
   Answer **host** for the role. Open the UI and log in.
2. **Each node** — in the UI, **Nodes → Add node**, then run the command it prints on the entry server (see [Adding a node](#adding-a-node)).

### C — Docker

```
git clone https://github.com/SanityProtocol/swg-panel && cd swg-panel
cp .env.example .env        # set PANEL_PASSWORD (and PANEL_DOMAIN)
docker compose --profile host up -d
```

Open `https://<host>:8443/`. For a node, or a panel-plus-local-node, see [Docker](#docker).

## Installing the panel

`install-host.sh` (run by `bootstrap.sh host`, or directly from a clone) sets up the panel and, for `host+node`, the local entry server. It asks:

| prompt | meaning |
|---|---|
| **Role** | `host` (panel only) or `host+node` (also an entry server) |
| **Node name / public IP / interface** | *(host+node only)* identity + address clients dial for this box |
| **Panel domain / IP** | the hostname or IP the panel is reached at |
| **Port** | default **8443** (use 443 if you want; the unit adds the bind capability) |
| **TLS mode** | `selfsigned` · `letsencrypt` · `cloudflare` · `manual` · `none` |
| **Serve mode** | `standalone` (default, self-contained) or `nginx` (reverse-proxied) |
| **Admin user / password** | the web login |

**TLS modes:**
- **selfsigned** — instant; browsers warn once. Good for getting going or behind a tunnel.
- **letsencrypt** — real cert via `acme.sh --standalone`; **needs port 80 free** for issuance *and* renewal.
- **cloudflare** — real cert via DNS-01; **never uses port 80**. The token needs `Zone:DNS:Edit` + `Zone:Read`.
- **manual** — you provide `fullchain.pem` + `key.pem`.
- **none** — plain HTTP (the login travels in clear — use only behind a tunnel).

Unattended example (config via env):

```
sudo -E ROLE=host TLS_MODE=cloudflare CF_TOKEN=… PANEL_DOMAIN=panel.example.net \
     BASIC_USER=admin BASIC_PASS='…' bash -s host \
     < <(curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh)
```

## Adding a node

Nodes are managed entirely from the UI — the installer no longer asks about them.

1. **Nodes → Add node** — give it a name, the public IP/host clients will dial, and a colour. You get a **one-time enrollment token** and the exact command to run.
2. **On the entry server**, with wg/awg already set up, run that command (a clone of the repo provides the script):
   ```
   sudo PANEL_URL="https://panel.example.net:8443" NODE_TOKEN="<token>" ./install-node.sh
   ```
   It also asks for the interface to manage and this node's public endpoint, then installs `swg-noded` and points it at the panel.
3. Within a few seconds the node turns **online** in the Nodes screen.

If the panel uses a self-signed cert, the node does not verify it by default (the token is the credential, and the channel is still encrypted). To verify instead, answer yes to the TLS prompt for a real cert, or pin a self-signed one by passing `TLS_FINGERPRINT=<sha256-hex>` (its sha256 is checked during the TLS handshake, before the token is sent).

**Per-node actions** in the UI: **Edit** (endpoint/colour — the endpoint you set here is what goes into client configs), **Rotate token** (the old token stops working immediately; re-enroll the node), and **Remove** (revokes the token and unassigns the node from your peers).

## Managing peers

A **peer** is one identity (a keypair + IP + PSK) that can be deployed to several nodes at once for redundancy — the client fails over between them by changing its `Endpoint`.

- **Add peer** — pick the interface and one or more nodes, optionally a name. The panel allocates a free IP; your browser generates the keypair and PSK and builds the config(s). You are shown the **config + QR once** — the private key is never stored.
- **Assign / unassign** — deploying the same identity to more nodes just adds its public key + PSK there; the client config gains another endpoint to fail over to.
- **Remove** — drops the peer from the roster; every node it lived on removes it on the next sync.

Live status (online, partial, dangling, …) is computed every refresh from the nodes' snapshots — a peer stays "online" while one replica is briefly unreachable.

## Docker

One compose file, three profiles:

```
docker compose --profile host up -d         # panel only
docker compose --profile node up -d         # entry server only
docker compose --profile host-node up -d    # panel + local entry server
```

Configure via `.env` (copied from `.env.example`):

- **Panel:** `PANEL_PASSWORD` (required), `PANEL_USER`, `PANEL_DOMAIN`, `TLS` (`selfsigned`|`none`), `PANEL_PORT`.
- **Node:** `PANEL_URL` (for `host-node` use `https://swg-panel:8443`), `NODE_TOKEN` (from the Nodes screen), `NODE_ENDPOINT`, `NODE_IFACE`, `NODE_LISTEN_PORT`, `NODE_ADDRESS`, `TLS_VERIFY`, `DNS`.

The flow is the same as bare-metal: bring up the panel, **Nodes → Add node** to get a token, set `NODE_TOKEN`, then start the node profile.

**Two images.** `swg-panel` is pure Python (small, low-risk). `swg-node` builds the userspace **`amneziawg-go`** datapath plus the `awg` tools — a container cannot load the host's kernel module — and needs `NET_ADMIN` + `/dev/net/tun`. Mount a full AmneziaWG server `.conf` at `/etc/swg-node/<iface>.conf` for obfuscation; without one, a plain-WireGuard interface is generated. For best throughput, prefer a **bare-metal** node with the kernel module.

## Configuration reference

**Panel — `/etc/swg-panel/fleet.json`** (see `fleet.example.json`):

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

`store_configs` keeps the generated client configs (including private keys) on the panel — off by default; leave it off unless you understand the trade-off.

**Node — `/etc/swg-agent/config.json`** (see `config.example.json`):

```json
{
  "interfaces": { "awg0": { "cmd": ["awg"], "conf": "/etc/amnezia/amneziawg/awg0.conf" } },
  "endpoint_host": "203.0.113.7",
  "dns": ["1.1.1.1"],
  "panel": { "url": "https://panel.example.net:8443", "token": "…", "verify": false },
  "node":  { "interval": 5, "agent": "/opt/swg-agent/swg-agent", "sudo": false }
}
```

A node can serve several interfaces — list them all under `interfaces`; each peer is applied to the one it belongs to. Set `panel.verify: true` for a real cert, or add `panel.fingerprint: "<sha256-hex>"` to pin a self-signed one.

## Operations

- **Logs:** `journalctl -u swg-panel-server -f` (panel), `journalctl -u swg-noded -f` (node). Docker: `docker compose logs -f`.
- **Rotate a node's token:** Nodes → ⋯ → Rotate token, then re-run the install command (or update the node's `config.json`).
- **Remove a node:** Nodes → Remove. Stop `swg-noded` on the box itself to take it offline.
- **Back up:** `users.json` + `nodes.json` (under `/var/lib/swg-panel`) are the whole state. Copy them somewhere safe.
- **Uninstall:** `… | sudo bash -s uninstall` (or `./uninstall.sh`). It stops the services and removes the panel/node files; it asks before touching wg/awg, and can keep the roster + node store for a reinstall.

## Security

- **Transport:** nodes only ever connect *out* to the panel over TLS. Prefer a real cert (`letsencrypt`/`cloudflare`) so nodes can `verify: true`; with a self-signed cert, pin its fingerprint.
- **Node tokens** authenticate a node to the panel. They are shown once, stored only as a hash, and can be rotated. Treat the node's `config.json` (which holds the live token) as a secret — it is mode `600`.
- **PSKs** are generated per peer and stored in the roster so every node stays consistent; keep `/var/lib/swg-panel` readable only by the panel user.
- **Private keys** are generated in your browser and never sent to the server (unless you deliberately enable `store_configs`). If a peer's key is lost, re-issue the peer.

## Troubleshooting

- **A node stays "awaiting enroll" / never connects.** It hasn't synced yet. Check `journalctl -u swg-noded -f` on the node: a `fingerprint mismatch` means the pin is wrong; an HTTP `401` means the token is wrong or was rotated; a connection error means the panel URL/port or firewall is off.
- **A node is "offline."** It synced before but has gone quiet — check the daemon and the node's outbound network.
- **Peers don't appear on a node.** Confirm the peer is assigned to that node and that its interface matches one the node actually serves. Reads come from the node's latest snapshot, so a freshly added node needs one sync first.
- **Browser warns about the certificate.** Expected with `selfsigned`. Use a real cert for production, or accept the warning behind a trusted tunnel.
- **`acme.sh` failed to issue.** `letsencrypt` needs port 80 reachable; if 80 is taken, use `cloudflare` (DNS-01, no port 80).
