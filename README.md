<h1 align="center">🚧 WORK IN PROGRESS 🚧</h1>
<h2 align="center">PROJECT NOT READY</h2>
<p align="center"><code>1.24.0-alpha</code></p>

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

**Panel** — installs Docker if needed, then asks the role (master: panel + this box is a node, auto-enrolled · host: panel only) and a domain + TLS choice (login auto-generated, change it later in the panel)

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
| Node · 4 | **Turn-proxy** | *(master)* optional [vk-turn-proxy](https://github.com/cacggghp/vk-turn-proxy) — tunnels wg/awg through VK/Yandex TURN servers. Detects any installed proxy (by its `-listen`/`-connect` unit) and lists it; **Enter** to skip or pick a fork by **number** to install one (`WINGS-N`/`samosvalishe`/`kiper292`/`Moroka8` for Android, `anton48` for iOS). It fetches the release binary, **auto-derives** the `-connect` port from the wg/awg interface you just set up (lists all of them), **generates a 64-hex wrap key** with the fork's flags (`-wrap-srtp`/`-wrap`/`-wrap-mode`; `kiper292` has none), and records `listen`/`connect`/`wrap_key` for the panel + client configs. On **bare-metal** each proxy is a systemd service whose target lives in an `EnvironmentFile`, so a panel edit just rewrites it + restarts (no `daemon-reload`); on **Docker** it's a sibling **container** (`swg-turn-*`, managed over the mounted Docker socket — no `--privileged`/`--pid=host`). |

**TLS:**
- **letsencrypt** (default) — real cert via `acme.sh` (HTTP-01 standalone for `internal`/`caddy`, webroot behind `nginx`); needs port 80 reachable.
- **cloudflare** — real cert via DNS-01; **never uses port 80**. The token needs `Zone:DNS:Edit` + `Zone:Read`.
- **cf15** — Cloudflare **Origin** certificate, **15 years**, issued via the CF API (needs an **API token** with `Zone` → `SSL and Certificates` → `Edit`; the legacy Origin CA Key is deprecated). ⚠️ Only trusted **behind Cloudflare's proxy** (orange cloud) — a direct hit to the origin shows an untrusted cert. No renewal needed for 15 years.
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
   It runs **Node setup** — interfaces (each with its own endpoint IP) and an optional turn-proxy — and starts `swg-noded`. Prefer Docker? The panel shows a `… bash -s docker node -key … -host …` command too.
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

**One-liners** — install Docker if missing, stage `docker-compose.yml` + `.env` under `/opt/swg-panel-docker`, bring up a profile, and **prompt for what they need**. Same two entry points as bare-metal:

**Panel** — Step 1 asks the role, exactly like bare-metal: **master** (panel + this box also runs WG/AWG as a co-located node container, auto-enrolled in one pass) or **host** (panel only). `master` is the default.

```
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s docker host
```

**Node** — a separate entry server; asks for the panel URL + the key from **Nodes → Add node** (this is how the `host` role's nodes are deployed)

```
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s docker node
```

Flags skip the prompts (the panel's enroll command uses them): `-role master|host`, `-pass`, `-domain`, `-key`, `-host`, `-endpoint`, `-base`, `-port`, `-tls`, `-ifaces`, `-net host|bridge` — e.g. `… bash -s docker node -key NODE_KEY -host https://panel.example.net`.

**Or by hand** — one compose file, three profiles named after the roles:

**Panel + a local node** (role `master`)

```
docker compose --profile master up -d
```

**Panel only** (role `host`)

```
docker compose --profile host up -d
```

**Entry server only** (role `node`)

```
docker compose --profile node up -d
```

By hand the `master` profile does **not** auto-enroll the local node — add it in **Nodes → Add node**, set `NODE_TOKEN`, and point it at the panel's service name (`PANEL_URL=https://swg-panel:8443`). The `master` *installer role* does all of that for you. (`host-node` still works as an alias of `master` for older setups.)

Configure via `.env` (copied from `.env.example`):

- **Panel:** `PANEL_PASSWORD` (required), `PANEL_USER`, `PANEL_DOMAIN`, `PANEL_BASE` (optional subpath, e.g. `/swg`), `PANEL_PORT`, and `TLS` — `letsencrypt` · `cloudflare` · `cf15` · `selfsigned` · `none`, issued in-container by the bundled `acme.sh` exactly like bare-metal (set `ACME_EMAIL` / `CF_TOKEN` / `CF_ORIGIN_TOKEN` as the chosen mode needs; see [TLS](#installing-the-panel)).
- **Node:** `PANEL_URL` (for a `master` on bridge use `https://swg-panel:8443`; host networking uses loopback), `NODE_TOKEN` (from the Nodes screen), `NODE_ENDPOINT`, `NODE_IFACE` / `NODE_IFACES`, `NODE_LISTEN_PORT`, `NODE_ADDRESS`, `NODE_NET` (`host` · `bridge`), `TLS_VERIFY`, `DNS`.

**Networking** — the installer puts the node on **`network_mode: host`** by default (`NODE_NET=host`), so every interface UDP port — **including interfaces you later create from the panel** — is reachable with no per-port mapping, and throughput is better (no `docker-proxy`). On a `master` the node reaches the co-located panel over loopback. Choose **`bridge`** to isolate the node's network namespace instead; then each interface's `ListenPort` must be **published** in `docker-compose.yml` (the panel flags this and prints the exact line when you create an interface on a bridge node). The node reports its mode to the panel so the guidance only shows where it's needed.

**Two images** (pulled prebuilt from GHCR by default; `--build` builds them locally). `swg-panel` is pure Python + the bundled `acme.sh`. `swg-node` carries the userspace **`amneziawg-go`** datapath + `awg` tools (a container can't load the host kernel module) and needs `NET_ADMIN` + `/dev/net/tun`. It manages one interface by default (AmneziaWG 2.0; `NODE_PLAIN_WG=yes` for plain WG), several via `NODE_IFACES` (`name:port:addr[:proto[:endpoint]],…`), or any confs you mount under `/etc/swg-node/*.conf`. Panel-created interfaces persist across `up -d` (the conf dir is a volume). Masquerade is automatic. For best throughput, prefer a **bare-metal** node with the kernel module. With turn-proxy management enabled, `swg-noded` runs each proxy as a sibling `swg-turn-*` container (host network, `--restart unless-stopped`) over the mounted Docker socket — editing one just recreates the container, no host systemd.

**Re-running an installer is safe** — it detects an existing install, keeps your `.env` + `./data` (token, login, certificate, interfaces), and offers the current values as defaults; the wg/awg and turn-proxy steps show what's already there and let you add more. To start fresh, run the uninstaller first. (Docker: re-apply with `PULL_POLICY=always … bootstrap.sh docker host|node` so the new image + compose land.)

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
- **Uninstall:** `… | sudo bash -s uninstall` (or `./uninstall.sh`). Lists every installed component — the panel, a bare-metal node, the Docker panel and node containers, AmneziaWG, WireGuard, and **each** turn-proxy server — then loops through and asks to uninstall or keep each one. Nothing is removed without a yes; can keep the roster / node store / Docker data dir for a reinstall. `--yes` removes everything, `--dry-run` previews.

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
