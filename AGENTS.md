# AGENTS.md

Operating instructions for an automated agent — an LLM assistant, a CI job, Ansible, anything without a
human at a terminal. Humans want [README.md](README.md); this file is the machine-readable contract.

Everything here is about **operating swgPanel on a server**. Nothing in it is required to read the code.

---

## The one thing that will bite you

**The installers are interactive.** `install-host.sh`, `install-node.sh`, `install-docker.sh`,
`update.sh` and `uninstall.sh` read answers from `/dev/tty`, not stdin. Piping the curl one-liner without
supplying configuration does not fail — it **blocks, or silently takes defaults**, which on a panel means
a self-signed certificate and an address nobody can reach.

Every question has an environment variable. Set the ones you care about and no question is asked. That is
the supported unattended path, not a workaround.

**Always dry-run first.** `--dry-run` renders every file the run would write under `./dryrun/` and
executes nothing — no packages, no systemd, no Docker, no network. Diff that before committing to a box.

---

## Choosing a path

Two independent axes — pick one value from each. **Method**: bare-metal, Docker or NixOS.
**Role**: master, host or node.

| role | what it is |
|---|---|
| `master` | panel **and** this box carries WireGuard/AmneziaWG interfaces |
| `host` | panel only; entry servers are separate boxes |
| `node` | entry server only; syncs to a panel elsewhere |

A node reaches the panel over **outbound HTTPS only**. Nothing dials into a node — no inbound port, no
SSH, no rsync. Do not design an orchestration that expects to push to nodes.

---

## Bare-metal

`bootstrap.sh` is the front door; it fetches the repo and dispatches.

```bash
# panel only, fully unattended
curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh \
  | ROLE=host PANEL_DOMAIN=panel.example.org TLS_MODE=letsencrypt ACME_EMAIL=you@example.org \
    BASIC_USER=admin BASIC_PASS='…' SERVE_MODE=internal sudo -E bash -s host
```

`sudo -E` matters — without it the environment does not survive into the installer.

The variables are declared in a `CONFIG` block at the top of each script; that block is the source of
truth, and this table is the subset an agent usually needs.

**`install-host.sh`** (panel; `ROLE=master` also makes this box an entry server)

| variable | meaning |
|---|---|
| `ROLE` | `master` \| `host` |
| `PANEL_DOMAIN` | IP, hostname, or `host/subpath`. Blank = this host's IP |
| `SERVE_MODE` | `internal` \| `nginx` \| `caddy` \| `skip` |
| `TLS_MODE` | `letsencrypt` \| `cloudflare` \| `selfsigned` \| `skip` |
| `ACME_EMAIL`, `CF_TOKEN`, `CF_ORIGIN_TOKEN` | credentials for the chosen TLS mode |
| `CERT_FULLCHAIN`, `CERT_KEY` | paths, when bringing your own certificate |
| `BASIC_USER`, `BASIC_PASS` | panel login. Blank password = random, printed at the end |
| `STORE_CONFIGS` | `true` (default) keeps client configs so QR/download work later |
| `HOST_NODE_NAME`, `HOST_ENDPOINT_IP`, `MANAGE_IFACES` | master only |

**`install-node.sh`** (entry server)

| variable | meaning |
|---|---|
| `PANEL_URL` | `https://host[:port][/subpath]` |
| `NODE_TOKEN` | one-time enrolment token, minted by the panel |
| `ENDPOINT_IP` | the public address **clients** dial for this node |
| `NODE_NAME` | local label only — not the panel-side name |

A node token comes from a **running panel** (Nodes → Add node). You cannot invent one. For a `master`
the panel mints its own local node in the same pass, so no token step exists there.

`bootstrap.sh` also accepts flags that map onto these: `-key`→`NODE_TOKEN`, `-host`→`PANEL_URL`,
`-name`→`NODE_NAME`, `-endpoint`→`ENDPOINT_IP`. `SWG_REPO` / `SWG_REF` point it at a fork or a branch.

## Docker

```bash
… | sudo bash -s docker host -pass SECRET -domain panel.example.org
… | sudo bash -s docker node -key KEY -host https://panel.example.org -endpoint 203.0.113.7
```

Staged under `/opt/swg-panel-docker` with a `.env` (copy `.env.example`; `PANEL_PASSWORD` is required).
Compose profiles are named after the roles: `master`, `host`, `node`. `docker host` asks the role in
step 1 — pass `-role master|host` to skip it. `--dry-run` renders the `.env` and runs no Docker commands.

## NixOS

There is no installer to run, and `bootstrap.sh` **refuses on a declarative host on purpose** — it would
write into `/opt`, which `nixos-rebuild` neither manages nor sees. Declare `services.swg-panel` and/or
`services.swg-node` instead. Both offer `delivery = "container"` (published images) and
`delivery = "native"` (programs from the Nix store); a panel never learns how a node was installed, so
any mix works. Secrets go in files referenced by `environmentFile` / `tokenFile`, never inline — the Nix
store is world-readable.

Two things here return success without having done what you think, which is the failure mode this file
exists to prevent:

- **`nixos-rebuild switch` exits 0 without restarting `swg-noded`** on the native arm — it prints
  `NOT restarting the following changed units`. That is deliberate: a restart re-runs the bootstrap and
  drops every connected client, which an unrelated config change has no business doing. So a green rebuild
  is not evidence the new code is running; check the process and bounce it when you mean to
  (`systemctl restart swg-noded`). The panel's own Update button already does this for you — the caveat
  applies to a rebuild *you* run.
- **Nix reads only git-*tracked* files.** A file written into `/etc/nixos` but never `git add`-ed arrives
  *absent*, and the rebuild succeeds against the older content with no warning.

Full guide, including both of the above in context: [nix/README.md](nix/README.md).

---

## Verifying, without credentials

`GET /healthz` on the panel and on the subscription server is unauthenticated liveness — no data, no
session. Use it as the readiness probe.

Everything else under `/api/` requires a session; **`401` is the healthy answer** for an unauthenticated
caller. Treat `401` from `/api/state` as "the panel is up and auth is on", not as a failure. A `200`
there without credentials means authentication is not configured — that is the thing to alarm on.

A node's own health is local: `systemctl is-active swg-noded` (bare-metal / native) or
`docker ps` / `podman ps` (container). It logs a reconcile line every interval.

---

## Never do these

- **Never hand-edit `users.json` or `nodes.json`.** They are the roster and the node store, owned by the
  API. Both are versioned envelopes with backups and repair-on-read; a hand-written file loses peers or
  desynchronises node tokens, and the panel may refuse to start rather than come up empty.
- **Never run two panels against one state directory.** The panel takes a lock and refuses; if you defeat
  it, the two hold independent copies of `nodes.json` and clobber each other's writes — node tokens
  desync, every sync 401s, and no configuration reaches any node.
- **Never expect a node to reconcile from a failed sync.** A network error, a `401`, or a TLS-pin failure
  *skips* the pass by design, so a panel outage cannot wipe a node's peers. Absence of change after a
  failed sync is correct behaviour, not a stuck node.
- **Never re-mint a token for a box that already has one.** A re-enrolled node appears as a *second* node
  and strips the first. Reuse the token the box holds.
- **Never put secrets on a command line** where they land in `ps` or shell history. The installers read
  them from the environment for this reason.
- **Do not assume an uninstall removed the data.** State is deliberately preserved so a reinstall can
  recover; `--yes` still asks the destructive sub-questions unless they are preset.

## Updating and removing

```bash
… | sudo bash -s update      # --dry-run · -y/--yes take every upgrade · -f/--force re-apply
… | sudo bash -s uninstall   # --dry-run · --yes assume yes per component
```

`update.sh` auto-detects every installed shape (bare-metal or Docker, panel/master/node) and preserves
config and state. `uninstall.sh` walks component by component and removes nothing without a yes.

⚠️ **A command-line update is one machine.** Updating through the panel — the Update button, or the
host-update API — also asks every node that can update itself to follow, in the same pass. Running
`update.sh` on the panel host does not: it updates that host and its co-located node only, so a fleet
updated this way needs each remaining node updated in turn.

---

## Where to read more

| | |
|---|---|
| [README.md](README.md) · [Русский](README.ru.md) | what it is, for a person |
| [README.technical.md](README.technical.md) | architecture, every flag, the unattended examples |
| [API.md](API.md) | the HTTP API |
| [nix/README.md](nix/README.md) | the NixOS module, both delivery arms, adopting an existing box |
| [CHANGELOG.md](CHANGELOG.md) | what changed, per release |
