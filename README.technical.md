<p align="center"><a href="README.md">English</a> · <a href="README.ru.md">Русский</a> · <b>Technical (EN)</b> · <a href="README.technical.ru.md">Техническое (RU)</a></p>

<p align="center"><code>1.3.13-beta</code></p>

<!-- WHATS-NEW:START -->
> **What's new in 1.3.13-beta** — [full changelog](CHANGELOG.md)
> - **Restore a missing or broken interface** — one click recreates it with the *same keys* and re-adds every peer; a peer whose address drifted out of subnet gets a **Fix**. Works per-peer or across a whole node.
> - **Optional interface-key escrow** — nodes seal their server keys to a vault only you hold, so a wiped node can be rebuilt without the panel ever seeing a private key.
> - **Fixes** — flip a subpath reverse proxy to built-in HTTPS (and back) without stranding nodes; a peer's address is checked against its subnet before it's applied; Docker↔bare-metal convert keeps your address and settings.
<!-- WHATS-NEW:END -->

---

# swg-panel

A self-hosted control panel for running a small WireGuard / AmneziaWG service across one or more entry servers. The panel is the source of truth for your peers; each entry server (a **node**) syncs to it over **outbound HTTPS** and converges on the peer set it has been assigned — so nodes need no inbound access, no SSH, and no rsync.

Multi-hop in mind (edge entry → distant exit), and built to scale — from a couple of peers on one box to large fleets across many servers.

## How it works

- **Panel** (control plane) — serves the web UI, its own TLS + login, and a node-sync API. It owns the roster (your peers) and the node store. Pure Python, no database.
- **Node** (entry server) — runs `swg-noded`, which every few seconds posts a snapshot of its interface to the panel, receives the peers it *should* have, and reconciles locally through `swg-agent` (adding/removing peers on the live wg/awg interface). Outbound HTTPS only.
- **Declarative** — you change peers in the panel; nodes converge. A node that misses a beat self-heals on the next sync, and a transient panel outage never wipes a node's peers (a node only reconciles on a valid reply).
- **Keys are generated in your browser** — peer keypairs are always minted client-side. **By default** (`store_configs`, on) the panel then keeps a copy of each generated config — private key included — so its QR/download stays available any time. Prefer no secrets at rest? Set `store_configs` off (Settings → Client configs) and the panel keeps only the public key, the assigned IP, and the preshared key; the private key is shown **once** at creation and never stored. The PSK is always panel-owned, so every node a peer lives on stays consistent.

## Contents

- [Method × Role](#method-role)
- [The pieces](#the-pieces)
- [Quick start](#quick-start)
- [Installing the panel](#installing-the-panel)
- [Adding a node](#adding-a-node)
- [Managing peers](#managing-peers)
- [Subscriptions & access control](#subscriptions--access-control)
- [Docker](#docker)
- [Converting between bare-metal and Docker](#converting-between-bare-metal-and-docker)
- [Configuration reference](#configuration-reference)
- [Operations](#operations)
- [External API & Integrations](#external-api--integrations)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [Special thanks](#special-thanks)

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

Against a **self-signed** panel the installer **auto-pins the cert on first contact** (trust-on-first-use): the node stores its sha256 and checks it on every handshake, before the token is sent — so a man-in-the-middle can't impersonate the panel even without a CA. A **real-CA** panel is verified against the system trust store instead. Override with `TLS_VERIFY=yes|no` or an explicit `TLS_FINGERPRINT=<sha256-hex>`. If the panel later moves (host/port), a node **auto-re-points** to the new address — but only when it still presents the pinned/trusted cert.

**Per-node actions:** **Edit** (endpoint/colour — the endpoint goes into client configs), **Rotate token** (the old one stops working immediately; re-enroll), **Remove** (revokes the token and unassigns the node).

## Managing peers

A **peer** is one identity (a keypair + IP + PSK) that can be deployed to several nodes at once for redundancy — the client fails over between them by changing its `Endpoint`.

- **Add peer** — pick the interface and one or more nodes, optionally a name. The panel allocates a free IP; your browser generates the keypair and PSK and builds the config(s). You are shown the **config + QR once** — the private key is never stored. The QR is large and tap-to-fullscreen for easy phone scanning.
- **Assign / unassign** — deploying the same identity to more nodes just adds its public key + PSK there; the client config gains another endpoint to fail over to.
- **Copy to another server** — from a peer's page, copy it to a server it isn't on yet. It reuses the same key + PSK but gets a **fresh IP** from that server's subnet (a distinct tunnel sharing the identity). Needs the client private key, so it works when `store_configs` is on or right after the peer was created.
- **Remove** — drops the peer from the roster; every node it lived on removes it on the next sync.

Live status (online, partial, dangling, …) is computed every refresh from the nodes' snapshots — a peer stays "online" while one replica is briefly unreachable. Each deployment also shows its **transport** — **direct** or **via turn-proxy** (inferred when the client's observed endpoint matches a node's turn-proxy) — and, where a turn-proxy is present, the proxy endpoint + **wrap key** to set up the vk-turn-proxy client app.

**Account** — change the panel username/password under the **Account** tab; it takes effect immediately (you're asked to sign in again).

## Subscriptions & access control

**Subscriptions (`swg-sub`)** — a separate, public-facing, **read-only** surface that serves each user a personal page at `https://sub.<domain>/<token>#<unlock-key>` with their config + QR for **every** node they're on: **WireGuard**, **AmneziaWG**, and each **TURN-PROXY fork** they're assigned (WINGS-N, samosvalishe, Moroka8, cacggghp, …), plus a FreeTurn VK-call-link field, protocol/relay badges, light/dark, RU/EN, and copy / download / share. **Off by default** — enable it in **Settings → Subscriptions**.

- **Key custody.** The per-user **unlock key rides in the URL `#fragment`** — never sent to the server. The panel stores only **ciphertext** (encrypted config blobs) plus a public token map (`subs/users.json` = `{token_sha}`); the SK-wrapped unlock keys sit in a separate `subs/escrow.json` the sub surface can't read. A compromise of the internet-facing page yields only ciphertext, never a private key (this is why plaintext `store_configs` was dropped).
- **Isolation.** `swg-sub` is its own process/container running as a dedicated low-privilege user: it mounts panel state `:ro` and **masks** every secret it must never open (`auth`, `panel-settings.json`, `subs/vault.json`, `subs/escrow.json`, the TLS key) with `/dev/null` + `tmpfs`. No login, write, or node code.
- **Serving.** Config mirrors to `subs/serve.json` (`enabled`, `serve.{host,port,tls_mode,cert_path,key_path}`, languages). `swg-sub` terminates its own TLS — its own Let's Encrypt cert for `sub.<domain>`, an explicit cert path, or `reverse-proxy` mode (plain HTTP behind your proxy). Docker: the `swg-sub` container (`:8444`, front with your reverse proxy / Cloudflare). Bare-metal: the `swg-sub` systemd service.

**Suspend / block access** — a declarative per-user (or per-node) `disabled` flag. Flip it and the next node reconcile **removes the peer** (tunnels drop) *and* **suspends the subscription** (the page goes dark) — but `token_sha` and keys are kept, so unblocking is instant: the peer is re-added and the page restored with **no re-issued keys**.

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

Configure via `.env`:

- **Panel:** `PANEL_PASSWORD` (required), `PANEL_USER`, `PANEL_DOMAIN`, `PANEL_BASE` (optional subpath, e.g. `/swg`), `PANEL_PORT`, and `TLS` — `letsencrypt` · `cloudflare` · `cf15` · `selfsigned` · `none`, issued in-container by the bundled `acme.sh` exactly like bare-metal (set `ACME_EMAIL` / `CF_TOKEN` / `CF_ORIGIN_TOKEN` as the chosen mode needs; see [TLS](#installing-the-panel)).
- **Node:** `PANEL_URL` (for a `master` on bridge use `https://swg-panel:8443`; host networking uses loopback), `NODE_TOKEN` (from the Nodes screen), `NODE_ENDPOINT`, `NODE_IFACE` / `NODE_IFACES`, `NODE_LISTEN_PORT`, `NODE_ADDRESS`, `NODE_NET` (`host` · `bridge`), `TLS_VERIFY`, `DNS`.

**Networking** — the installer puts the node on **`network_mode: host`** by default (`NODE_NET=host`), so every interface UDP port — **including interfaces you later create from the panel** — is reachable with no per-port mapping, and throughput is better (no `docker-proxy`). On a `master` the node reaches the co-located panel over loopback. Choose **`bridge`** to isolate the node's network namespace instead; then each interface's `ListenPort` must be **published** in `docker-compose.yml` (the panel flags this and prints the exact line when you create an interface on a bridge node). The node reports its mode to the panel so the guidance only shows where it's needed.

**Two images** (pulled prebuilt from GHCR by default; `--build` builds them locally). `swg-panel` is pure Python + the bundled `acme.sh`. `swg-node` carries the userspace **`amneziawg-go`** datapath + `awg` tools (a container can't load the host kernel module) and needs `NET_ADMIN` + `/dev/net/tun`. It manages one interface by default (AmneziaWG 2.0; `NODE_PLAIN_WG=yes` for plain WG), several via `NODE_IFACES` (`name:port:addr[:proto[:endpoint]],…`), or any confs you mount under `/etc/swg-node/*.conf`. Panel-created interfaces persist across `up -d` (the conf dir is a volume). Masquerade is automatic. For best throughput, prefer a **bare-metal** node with the kernel module. With turn-proxy management enabled, `swg-noded` runs each proxy as a sibling `swg-turn-*` container (host network, `--restart unless-stopped`) over the mounted Docker socket — editing one just recreates the container, no host systemd.

Prebuilt images: `ghcr.io/sanityprotocol/swg-panel` and `ghcr.io/sanityprotocol/swg-node`.

**Re-running an installer is safe** — it detects an existing install, keeps your `.env` + `./data` (token, login, certificate, interfaces), and offers the current values as defaults; the wg/awg and turn-proxy steps show what's already there and let you add more. To start fresh, run the uninstaller first. (Docker: re-apply with `PULL_POLICY=always … bootstrap.sh docker host|node` so the new image + compose land.)

## Converting between bare-metal and Docker

Switch a box's **method** in place: re-run the installer asking for the *other* method, and it offers **convert · keep · abort**.

```bash
# the same one-liner with the other method — e.g. a Docker master ⇆ bare-metal:
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s master         # → bare-metal (a bare role word means bare-metal)
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s docker master  # → Docker
```

A convert **keeps everything** — the panel's URL, login, roster, nodes and TLS cert, and (for a `master`) the local node's token, interfaces and turn-proxies. It is **copy-first**: the new method is staged in full *before* the old one is torn down, so the only downtime is the few seconds of the atomic switch — nodes self-heal on their next sync.

**Roles convert independently.** Converting a `master` first asks whether to move the whole box or just one half — **whole master** (panel + node, the default), **just the host** (only the panel), or **just the node** (only the node). A split leaves a **mixed-method box** (e.g. a Docker panel with a bare-metal node) that you manage in two places — handy for moving a node onto the kernel datapath while the panel stays on Docker.

**Interfaces and turn-proxies migrate in the node stage.** As the node converts it lists the wg/awg interfaces and turn-proxy servers it manages and asks **“Transfer these … into the … node? (Y/n)”** for each set; keys, ports and endpoints carry over (copy-first), and the originals keep serving until the switch. Decline to leave them on the old method and start the new node empty. Both directions behave the same.

**Live status.** The panel header — and the node tile, for a node or master — shows **converting → converted** as it runs (the *converting* tag the moment you confirm, *converted* with the final summary), so you can watch a convert from the console.

> For nodes, **docker → bare-metal** is preferred — the host kernel module out-performs the container's userspace `amneziawg-go`. A node split off a co-located Docker master is automatically pointed at the panel's loopback port, since the compose DNS name isn't reachable from outside the container network.

## Configuration reference

**Panel — `/etc/swg-panel/fleet.json`**:

```json
{
  "roster_path":   "/var/lib/swg-panel/users.json",
  "nodes_path":    "/var/lib/swg-panel/nodes.json",
  "stats_dir":     "/var/www/wgstats",
  "store_configs": true,
  "config_dir":    "/var/lib/swg-panel/configs",
  "node_interval": 5
}
```

`store_configs` keeps the generated client configs (including private keys) on the panel so QR codes and downloads stay available any time — **on by default** (the installers write `true`). Set it to `false` for **no secrets at rest**: the panel then stores only the public key, IP, and PSK, and each config's private key is shown once at creation. The panel flags when it's off (existing peers then need a one-time key rotation to re-capture a config).

**Node — `/etc/swg-agent/config.json`**:

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
- **Back up:** `users.json` + `nodes.json` (under `/var/lib/swg-panel`) are the whole state — copy the directory somewhere off-box and you can rebuild the panel anywhere.
- **Automatic backups + self-repair:** every write to a critical state file (`users.json`, `nodes.json`, `panel-settings.json`) also drops a timestamped copy beside it — `users.json.bak.<epoch>` — and prunes to the **last 8**. On startup the loader validates each primary and, if one is corrupt/empty (bad shutdown, full disk), **automatically restores the newest good backup** — no operator action. So a backup exists after *every change*, not on a schedule. (Off-box copies are still recommended for whole-host loss.)
- **Update:** `… | sudo bash -s update` (or `./update.sh`). Pulls the latest code, auto-detects what's installed (bare-metal panel/node and/or Docker), refreshes the binaries/SPA, and restarts — config + state are preserved. The installed version is stamped in each component's `VERSION` file (repo: [`VERSION`](VERSION)).
- **Re-install keeps data:** re-running *any* installer on a box detects the existing install and preserves everything (login, cert, roster, nodes, node token, interfaces, turn-proxies), offering current values as defaults — safe after an interrupted run or to change an option. To start clean, uninstall first.
- **Recover a node's identity:** a re-installed or converted node persists its enrollment identity to `/var/lib/swg-recovery`, so it can rejoin **without re-enrolling**. Open that menu directly with `… | sudo bash -s recovery` (works even on a box that still has a live node — e.g. to reattach a leftover token after a rebuild).
- **Move the panel:** change its host/port and **pinned nodes auto-re-point** on their next sync — as long as the new address still presents their trusted cert — so a panel migration needs no per-node re-enroll.
- **Uninstall:** `… | sudo bash -s uninstall` (or `./uninstall.sh`). Lists every installed component — the panel, a bare-metal node, the Docker panel and node containers, AmneziaWG, WireGuard, and **each** turn-proxy server — then loops through and asks to uninstall or keep each one. Nothing is removed without a yes; can keep the roster / node store / Docker data dir for a reinstall. `--yes` removes everything, `--dry-run` previews.

## External API & Integrations

A **read-only** REST + Prometheus surface plus outbound **webhooks**, for wiring the panel into external monitoring and automation — Grafana, Uptime Kuma, Prometheus, Terraform/Ansible, or your own scripts. It exposes state the panel already collects from node syncs; it **never changes the fleet**.

- **Read-only.** No token is accepted on any mutating endpoint — a leaked token can observe, never modify.
- **Panel-only.** Nodes are untouched; they sync exactly as before. The API is served from the same in-memory snapshots + roster the panel already keeps — no extra load on nodes, no change to the sync loop.
- **Cheap.** Off the SPA's poll path; the whole-fleet view is cached ~3s and shared by every endpoint and scrape, so an aggressive Prometheus/Grafana setup can't degrade the panel.

Enable it in **Settings → Integrations**: mint a token (shown once), optionally add webhooks.

**Authentication.** Every endpoint except the liveness probes needs a token, sent one of three ways:

```
Authorization: Bearer <token>
X-API-Key: <token>
?token=<token>          # query param, for tools that can't set a header
```

Tokens are minted in the UI (`swgp_…`); only a SHA-256 hash is stored. An admin session cookie also authenticates (so the settings page can preview). Turning the API **off** rejects all tokens immediately. `GET /healthz` and `GET /api/v1/health` are unauthenticated liveness probes and expose no secrets.

**Endpoints:**

| endpoint | auth | what it returns |
|---|---|---|
| `GET /healthz` | no | plain-text `ok` for uptime probes / load balancers |
| `GET /api/v1/health` | no | liveness + coarse node/peer counts + version |
| `GET /api/v1/servers` | yes | every node with status + counts + throughput (mesh links excluded) |
| `GET /api/v1/servers/{id}` | yes | one server by **id or name** (same shape as a `/servers` element) |
| `GET /api/v1/servers/{id}/peers` | yes | peers observed on that node, with last-handshake timing, roster-enriched |
| `GET /api/v1/peers` | yes | roster-wide peer identities with per-target presence |
| `GET /api/v1/summary` | yes | fleet totals + aggregate throughput |
| `GET /metrics` | yes | Prometheus text exposition (`v0.0.4`) |

**Prometheus metrics** — **per-node cardinality only** (never per-peer, which would explode the series count; peer detail lives in the JSON API):

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
| `swg_node_uptime_seconds` | gauge | `node`,`name` | host uptime |

**Webhooks.** The panel POSTs a signed JSON body to each configured URL when a subscribed event fires: `peer.added`, `peer.removed`, `node.online`, `node.offline`.

```json
{ "event": "node.offline", "ts": 1783620181,
  "data": { "id": "1b8e0bcb0b4c", "name": "moscow-1", "last_seen": 1783620090 } }
```

Every delivery carries a signature header so you can verify it came from the panel:

```
X-SWG-Signature: sha256=<hex HMAC-SHA256(secret, raw_body)>
```

The secret is generated when you add the webhook (shown once). Delivery is best-effort with one retry; node online/offline is derived from sync staleness, so `node.offline` fires when a node misses syncs past the offline window (`NODE_OFFLINE`, 30s). The watcher does **no work at all** when no webhooks are configured.

**Examples:**

```bash
# liveness (no auth)
curl -s https://panel.example.com/api/v1/health

# fleet, with a token
curl -s -H 'Authorization: Bearer swgp_…' https://panel.example.com/api/v1/servers | jq

# one node's peers + handshake timing
curl -s -H 'Authorization: Bearer swgp_…' \
  https://panel.example.com/api/v1/servers/moscow-1/peers | jq
```

Prometheus scrape config:

```yaml
scrape_configs:
  - job_name: swg-panel
    metrics_path: /metrics
    authorization:
      credentials: swgp_…            # your API token
    static_configs:
      - targets: ['panel.example.com']
```

Uptime Kuma: add an **HTTP(s) - Keyword** monitor on `/api/v1/health`, keyword `"ok"`. Terraform/Ansible: read `/api/v1/servers` and `/api/v1/peers` to discover fleet state for inventory or drift checks (the API is read-only — provision through the panel UI/roster).

Full reference: [`docs/API.md`](docs/API.md).

## Security

- **Transport & panel identity:** nodes only ever connect *out* to the panel over TLS. A **real-CA** panel is verified against the system trust store; a **self-signed** one is **auto-pinned (trust-on-first-use)** at enrollment, so a man-in-the-middle can't impersonate it. If the panel later moves (host/port), a node **auto-re-points** to the new address only when it still presents the pinned/trusted cert.
- **Request signing (replay-resistant):** every node→panel request carries `X-SWG-TS` + `X-SWG-MAC` = HMAC-SHA256(the node's `token_sha`, `ts`·sha256(body)); the panel verifies it inside a short time window (rejecting replays) and looks the node up by a per-node `token_sha` index — constant-time, so a bogus token can't force pbkdf2 amplification.
- **Node tokens** authenticate a node to the panel. They are shown once, stored only as a hash, and can be rotated. Treat the node's `config.json` (which holds the live token) as a secret — it is mode `600`.
- **PSKs** are generated per peer and stored in the roster so every node stays consistent; keep `/var/lib/swg-panel` readable only by the panel user.
- **Private keys** are generated in your browser. By default (`store_configs` on) the panel keeps the generated config — private key included — so QR/download stay available; set `store_configs` off for no secrets at rest, and each private key is shown only once at creation. Either way, if a peer's key is lost, re-issue the peer.
- **API tokens** are read-only and hashed at rest (SHA-256); a leaked token can observe fleet state but never modify it, and disabling the API in **Settings → Integrations** revokes every token immediately.

## Troubleshooting

- **A node stays "awaiting enroll" / never connects.** It hasn't synced yet. Check `journalctl -u swg-noded -f` on the node: a `fingerprint mismatch` means the pin is wrong; an HTTP `401` means the token is wrong or was rotated; a connection error means the panel URL/port or firewall is off.
- **A node is "offline."** It synced before but has gone quiet — check the daemon and the node's outbound network.
- **Peers don't appear on a node.** Confirm the peer is assigned to that node and that its interface matches one the node actually serves. Reads come from the node's latest snapshot, so a freshly added node needs one sync first.
- **Browser warns about the certificate.** Expected with `selfsigned`. Use a real cert for production, or accept the warning behind a trusted tunnel.
- **Client connects (handshake works) but has no internet / `rx` climbs while `tx` stays ~0.** The node is decrypting packets but not routing them out. Interfaces created by the installer set this up automatically; for a hand-made interface, enable forwarding (`net.ipv4.ip_forward=1`) and add a masquerade for the tunnel subnet out the WAN nic (`iptables -t nat -A POSTROUTING -s <subnet> -o <wan> -j MASQUERADE`).
- **Smart routing doesn't switch instantly — give it a minute or two.** Enabling a list/category or changing its exit is *eventually consistent*, not immediate. The node applies routing on a periodic reconcile (~60s) after pulling the resolved list from the panel, so there's a short delay before matched traffic starts leaving via the new exit — and longer if a connection is already open, since it keeps flowing the old way until it reconnects. Category attribution lags a little further: a destination's IP set fills lazily (as its domains are resolved/seen), so freshly routed traffic can show as **uncategorized** for a bit before it lands in its category. Both converge on their own; nothing is wrong — re-checking after a minute or reconnecting the client speeds it up.
- **`acme.sh` failed to issue.** `letsencrypt` needs port 80 reachable; if 80 is taken, use `cloudflare` (DNS-01, no port 80).

## Special thanks

swgPanel integrates several excellent open-source projects — huge thanks to their authors.

**Turn-proxy forks** — wrap WireGuard/AmneziaWG through VK/Yandex TURN relays to get past tough blocks:

- [cacggghp/vk-turn-proxy](https://github.com/cacggghp/vk-turn-proxy) — the original
- [WINGS-N/vk-turn-proxy](https://github.com/WINGS-N/vk-turn-proxy) — ❤️
- [samosvalishe/free-turn-proxy](https://github.com/samosvalishe/free-turn-proxy)
- [Moroka8/vk-turn-proxy](https://github.com/Moroka8/vk-turn-proxy)
- [kiper292/vk-turn-proxy](https://github.com/kiper292/vk-turn-proxy)
- [anton48/vk-turn-proxy](https://github.com/anton48/vk-turn-proxy)

**Routing / geo-data lists** — the domain & IP lists behind smart routing:

- [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat)
- [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community)
- [Loyalsoldier/geoip](https://github.com/Loyalsoldier/geoip)
- [1andrevich/Re-filter-lists](https://github.com/1andrevich/Re-filter-lists)
- [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script)

And, of course, [WireGuard](https://www.wireguard.com/) and [AmneziaWG](https://github.com/amnezia-vpn/amneziawg-go).
