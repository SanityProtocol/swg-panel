<h1 align="center">🚧 WORK IN PROGRESS 🚧</h1>
<h2 align="center">PROJECT NOT READY</h2>
<p align="center"><code>1.0.0-alpha</code></p>

---

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
- **master** — the panel *and* this box is also an entry server (auto-enrolled for you).
- **node** — an entry server only.

Mix freely: a Docker panel with bare-metal nodes, a bare-metal `master` plus extra Docker nodes, and so on.

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

Four one-liners — each **prompts for whatever it needs**. Choose a method (bare-metal or Docker) per box; mix freely.

### A — bare-metal (systemd)

**Panel** — asks the role: master (panel + this box is a node) or host (panel only)

```
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s host
```

**Node** — asks for the panel URL + the key from Nodes → Add node

```
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s node
```

### B — Docker

**Panel** — installs Docker if needed, asks for a domain + admin username (password auto-generated)

```
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s docker host
```

**Node** — asks for the panel URL + the key from Nodes → Add node

```
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s docker node
```

Open the panel URL, log in, and add entry servers from **Nodes → Add node** — it prints the exact bare-metal *and* Docker command (key pre-filled) for each. Details: [Installing the panel](#installing-the-panel) · [Adding a node](#adding-a-node) · [Docker](#docker).

**Update** any box later, in place (auto-detects what's installed):

```
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s update
```

## Installing the panel

`install-host.sh` (run by `bootstrap.sh host`, or directly from a clone) sets up the panel and, for a `master`, the local entry server. Two sequenced sections — **Panel setup**, then **Node setup** (master only):

| section | prompt | meaning |
|---|---|---|
| Panel · 1 | **Role** | `master` (default — panel + this box is an entry server) or `host` (panel only) |
| Panel · 2 | **Panel URL** | IP, host, or host with a subpath (`vpn.example.com/swg`) to mount the panel under an existing site. Default is this host's public IP. |
| Panel · 3 | **TLS** | `letsencrypt` (default) · `cloudflare` · `cf15` · `selfsigned` · `skip` |
| Panel · 4 | **Serve mode** | `internal` (default, self-contained) · `nginx` · `caddy` · `skip` |
| Panel | **Port / admin** | port (default **443** for `internal`; the unit adds the bind capability for ports < 1024) and the web login — suggests `admin` + 3 digits; changeable later under **Account** |
| Node · 1 | **Node name** | *(master)* this box's node name (default: hostname) |
| Node · 2 | **Endpoint IP** | *(master)* public IP clients dial for this box (default: detected) |
| Node · 3 | **Interfaces** | *(master)* manages **every** wg/awg interface found (scanning all of `/etc/amnezia` and `/etc/wireguard`); offers to **create** one if none exist; press **Enter** to proceed or **`new`** to add another. New interfaces get a server key, tunnel subnet, and an automatic forward + masquerade (`PostUp`/`PostDown`) so clients reach the internet. |
| Node · 4 | **Turn-proxy** | *(master)* optional [vk-turn-proxy](https://github.com/cacggghp/vk-turn-proxy) — tunnels wg/awg through VK/Yandex TURN servers. Detects any installed proxy (by its `-listen`/`-connect` unit) and lists it; **Enter** to skip or **`new`** to install a fork (`wings`/`samosvalishe`/`kiper292` for Android, `anton48` for iOS). It fetches the release binary, **auto-derives** the `-connect` port from the wg/awg interface you just set up (lists all of them), **generates a 64-hex wrap key** with the fork's flags (`-wrap-srtp`/`-wrap`/`-wrap-mode`; `kiper292` has none), and records `listen`/`connect`/`wrap_key` for the panel + client configs. |

**TLS:**
- **letsencrypt** (default) — real cert via `acme.sh` (HTTP-01 standalone for `internal`/`caddy`, webroot behind `nginx`); needs port 80 reachable.
- **cloudflare** — real cert via DNS-01; **never uses port 80**. The token needs `Zone:DNS:Edit` + `Zone:Read`.
- **cf15** — Cloudflare **Origin** certificate, **15 years**, issued via the CF API (needs the *Origin CA Key*). ⚠️ Only trusted **behind Cloudflare's proxy** (orange cloud) — a direct hit to the origin shows an untrusted cert. No renewal needed for 15 years.
- **selfsigned** — instant; browsers warn once. Good for getting going or behind a tunnel.
- **skip** — bring your own cert (set `CERT_FULLCHAIN`/`CERT_KEY`), or terminate TLS elsewhere. With no cert the panel/proxy serves plain HTTP.

**Serve modes:** `internal` self-contained (own TLS + login); `nginx` / `caddy` reverse-proxy on loopback (TLS terminated by the proxy, with a `location`/`handle` block honoring any subpath); `skip` leaves the panel on a loopback port for you to front yourself. Every mode uses the panel's own pbkdf2 login, so the **Account** tab works throughout.

Unattended example (config via env):

```
sudo -E ROLE=master TLS_MODE=cloudflare CF_TOKEN=… PANEL_DOMAIN=panel.example.net \
     BASIC_USER=admin BASIC_PASS='…' bash -s host \
     < <(curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh)
```

## Adding a node

Nodes are managed entirely from the UI — the installer no longer asks about them.

1. **Nodes → Add node** — give it a name, the public IP/host clients dial, and a colour. You get a **one-time enrollment token** and the exact one-liner.
2. **On the entry server**, paste that one-liner — it fetches the repo and runs the node installer:
   ```
   curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh \
     | sudo bash -s node -key SECURE_NODE_KEY -host https://panel.example.net
   ```
   It runs **Node setup** (endpoint · interfaces) and starts `swg-noded`. Prefer Docker? The panel shows a `… bash -s docker node -key … -host …` command too.
3. Within a few seconds the node turns **online** in the Nodes screen.

With a self-signed panel cert the node doesn't verify it by default — the token is the credential and the channel is still encrypted. To verify instead, use a real cert and answer yes to the TLS prompt, or pin the self-signed one with `TLS_FINGERPRINT=<sha256-hex>` (checked during the handshake, before the token is sent).

**Per-node actions:** **Edit** (endpoint/colour — the endpoint goes into client configs), **Rotate token** (the old one stops working immediately; re-enroll), **Remove** (revokes the token and unassigns the node).

## Managing peers

A **peer** is one identity (a keypair + IP + PSK) that can be deployed to several nodes at once for redundancy — the client fails over between them by changing its `Endpoint`.

- **Add peer** — pick the interface and one or more nodes, optionally a name. The panel allocates a free IP; your browser generates the keypair and PSK and builds the config(s). You are shown the **config + QR once** — the private key is never stored. The QR is large and tap-to-fullscreen for easy phone scanning.
- **Assign / unassign** — deploying the same identity to more nodes just adds its public key + PSK there; the client config gains another endpoint to fail over to.
- **Copy to another server** — from a peer's page, copy it to a server it isn't on yet. It reuses the same key + PSK but gets a **fresh IP** from that server's subnet (a distinct tunnel sharing the identity). Needs the client private key, so it works when `store_configs` is on or right after the peer was created.
- **Remove** — drops the peer from the roster; every node it lived on removes it on the next sync.

Live status (online, partial, dangling, …) is computed every refresh from the nodes' snapshots — a peer stays "online" while one replica is briefly unreachable. Each deployment also shows its **transport** — **direct** or **via turn-proxy** (inferred when the client's observed endpoint matches a node's turn-proxy) — and, where a turn-proxy is present, the proxy endpoint + **wrap key** to set up the vk-turn-proxy client app.

**Account** — change the panel username/password under the **Account** tab; it takes effect immediately (you're asked to sign in again).

## Docker

**One-liner** — installs Docker if missing, stages the project under `/opt/swg-panel-docker`, writes `.env`, brings up a profile, and **prompts for what it needs**:

```
# panel
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s docker host
# entry server (node)
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s docker node
# panel + a local node
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s docker host-node
```

Flags skip the prompts (the panel's enroll command uses them): `-pass`, `-domain`, `-key`, `-host`, `-endpoint`, `-base`, `-port`, `-tls`, `-ifaces` — e.g. `… bash -s docker node -key NODE_KEY -host https://panel.example.net`.

**Or by hand** — one compose file, three profiles:

```
docker compose --profile host up -d         # panel only
docker compose --profile node up -d         # entry server only
docker compose --profile host-node up -d    # panel + local entry server
```

Configure via `.env` (copied from `.env.example`):

- **Panel:** `PANEL_PASSWORD` (required), `PANEL_USER`, `PANEL_DOMAIN`, `PANEL_BASE` (optional subpath, e.g. `/swg`), `TLS` (`selfsigned`|`none`), `PANEL_PORT`.
- **Node:** `PANEL_URL` (for `host-node` use `https://swg-panel:8443`), `NODE_TOKEN` (from the Nodes screen), `NODE_ENDPOINT`, `NODE_IFACE` / `NODE_IFACES`, `NODE_LISTEN_PORT`, `NODE_ADDRESS`, `TLS_VERIFY`, `DNS`.

Same flow as bare-metal: bring up the panel, **Nodes → Add node** for a token, set `NODE_TOKEN`, then start the node profile.

**Two images.** `swg-panel` is pure Python. `swg-node` builds the userspace **`amneziawg-go`** datapath + `awg` tools (a container can't load the host kernel module) and needs `NET_ADMIN` + `/dev/net/tun`. It manages one interface by default (AmneziaWG 2.0; `NODE_PLAIN_WG=yes` for plain WG), several via `NODE_IFACES` (`name:port:addr[:proto],…`), or any confs you mount under `/etc/swg-node/*.conf` — publish each ListenPort in compose. Masquerade is automatic. For best throughput, prefer a **bare-metal** node with the kernel module.

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
  "panel": { "url": "https://panel.example.net", "token": "…", "verify": false },
  "node":  { "interval": 5, "agent": "/opt/swg-agent/swg-agent", "sudo": false }
}
```

A node can serve several interfaces — list them all under `interfaces`; each peer is applied to the one it belongs to. Set `panel.verify: true` for a real cert, or add `panel.fingerprint: "<sha256-hex>"` to pin a self-signed one.

## Operations

- **Logs:** `journalctl -u swg-panel-server -f` (panel), `journalctl -u swg-noded -f` (node). Docker: `docker compose logs -f`.
- **Rotate a node's token:** Nodes → ⋯ → Rotate token, then re-run the install command (or update the node's `config.json`).
- **Remove a node:** Nodes → Remove. Stop `swg-noded` on the box itself to take it offline.
- **Back up:** `users.json` + `nodes.json` (under `/var/lib/swg-panel`) are the whole state. Copy them somewhere safe.
- **Update:** `… | sudo bash -s update` (or `./update.sh`). Pulls the latest code, auto-detects what's installed (bare-metal panel/node and/or Docker), refreshes the binaries/SPA, and restarts — config + state are preserved. The installed version is stamped in each component's `VERSION` file (repo: [`VERSION`](VERSION)).
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
- **Client connects (handshake works) but has no internet / `rx` climbs while `tx` stays ~0.** The node is decrypting packets but not routing them out. Interfaces created by the installer set this up automatically; for a hand-made interface, enable forwarding (`net.ipv4.ip_forward=1`) and add a masquerade for the tunnel subnet out the WAN nic (`iptables -t nat -A POSTROUTING -s <subnet> -o <wan> -j MASQUERADE`).
- **`acme.sh` failed to issue.** `letsencrypt` needs port 80 reachable; if 80 is taken, use `cloudflare` (DNS-01, no port 80).
