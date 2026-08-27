<p align="center"><b>English</b> · <a href="README.ru.md">Русский</a></p>

# swgPanel on NixOS

Run the panel, a node, or both on NixOS, declaratively. Two delivery methods are supported and
neither is a stepping stone to the other: a **container arm** running the images we publish, and a
**native arm** running these programs from your Nix store on the kernel datapath. There is also
`nix/adopt.sh` for moving a box you already run onto either arm without re-minting a single key.

This page is task-ordered: start at the top and end with a working install.

## Contents

- [What you need before you start](#what-you-need-before-you-start)
- [Installing](#installing) — nine steps, from turning flakes on to checking it worked
- [Updating](#updating) — the Update button, by hand, and what a failed rebuild tells you
- [Moving an existing install onto NixOS](#moving-an-existing-install-onto-nixos) — keeping every key your clients already trust
- [Removing](#removing) — a node, the panel, or everything
- [Reference](#reference) — the delivery methods, the support boundary, and the traps of a declarative host

⚠️ **Do not run `bootstrap.sh` on NixOS.** It refuses, and so do `install-host.sh`,
`install-node.sh`, `install-docker.sh`, `update.sh` and `convert.sh`. They had to be taught, because
the failure was not obvious: `/` is writable and `nixos-rebuild` never touches `/opt`, so
`mkdir -p /opt/… && cp` **succeeds** and the run only falls over later on `PATH` or `apt-get`,
leaving a half-install your configuration cannot see. `--dry-run` still works, which is how you look
at what a bare-metal install *would* have written on a box you are moving off.

---

## What you need before you start

- A NixOS host you can `nixos-rebuild switch` — flakes are the documented path, and `default.nix`
  gives channel users the same outputs without them.
- **A secrets file on the box, outside the Nix store.** Every token and password goes in a file; an
  option value lands in the world-readable store. A secret manager's path works too
  (`config.sops.secrets.swg-panel.path`, agenix, …).
- For a panel: a domain, and something to terminate TLS — `security.acme` plus a reverse proxy, or
  the panel itself via `useACMEHost`.
- For a node: the public IP clients will dial, and a node token minted in the panel's **Nodes**
  screen (shown once).

---

## Installing

### Step 1 — flakes

**You do not need to turn flakes on to install this.** `nixos-rebuild --flake` enables them for its
own `nix` calls — nixos-rebuild passes `--extra-experimental-features "nix-command flakes"` itself —
so every `nixos-rebuild` in this guide works on a stock box with flakes off.

What *does* need them is a bare **`nix`** command: `nix build`, `nix flake check`, `nix flake update`.
The panel's Update button runs one, and so do the tyre-kicking commands in step 2. So add the line
now and let the first rebuild, in step 9, apply it:

```bash
sudo nano /etc/nixos/configuration.nix
```

Inside the outer `{ … }`, anywhere among the other settings:

```nix
  nix.settings.experimental-features = [ "nix-command" "flakes" ];
```

Save and exit nano with **Ctrl+O, Enter, Ctrl+X**. Until step 9 applies it, a bare `nix` command
needs the flag spelled out:

```bash
nix --extra-experimental-features 'nix-command flakes' flake metadata /etc/nixos
```

⚠️ **Do not try to apply it with a plain `sudo nixos-rebuild switch` first.** Without `--flake` that
command wants a `nixos-config` entry in `NIX_PATH`, and a host that is already flake-managed — or
simply provisioned without channels — does not have one. It fails with
`error: file 'nixos-config' was not found in the Nix search path` before it changes anything.

### Step 2 — create the flake

Two things decide what goes in it: **where your configuration lives** (`/etc/nixos`, unless you
moved it) and **your hostname**, because the flake names its configuration after the machine.

```bash
hostname          # e.g. "myhost" — use whatever this prints, everywhere below
nixos-version     # e.g. "25.11.2026…" — the channel this machine is ON
```

⚠️ **Pin nixpkgs to the channel `nixos-version` just printed**, not to whatever is newest. The
flake's `nixpkgs` input *is* your system's package set, so writing a higher one here upgrades the
whole OS on your next rebuild — a much larger change than installing this, and not one to make by
accident. `25.11` below is an example; use yours.

Create the file:

```bash
sudo nano /etc/nixos/flake.nix
```

Paste this, replacing **`myhost`** with what `hostname` printed:

```nix
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";   # ← YOUR channel, from `nixos-version`
  inputs.swg-panel.url = "github:SanityProtocol/swg-panel";

  outputs = { self, nixpkgs, swg-panel, ... }: {
    nixosConfigurations.myhost = nixpkgs.lib.nixosSystem {    # ← YOUR hostname
      system = "x86_64-linux";                 # aarch64-linux on ARM — `uname -m` tells you
      modules = [
        ./configuration.nix
        swg-panel.nixosModules.default         # panel + node; .swg-panel or .swg-node for one
      ];
    };
  };
}
```

Save (**Ctrl+O, Enter, Ctrl+X**) and check that it evaluates before you build anything:

```bash
sudo nixos-rebuild build --flake /etc/nixos#myhost
```

A silent finish, or a line ending in `/nix/store/…-nixos-system-myhost-…`, means it is good. It
changes nothing yet — `build` only builds. If it fails with **`error: Path 'flake.nix' in the repository
"/etc/nixos" is not tracked by Git.`**, your `/etc/nixos` is a git repository and git has not been
told about the new file:

```bash
sudo git -C /etc/nixos add flake.nix
```

Nix only reads *tracked* files out of a git directory, so an untracked `flake.nix` is invisible to it.

You do not have to touch `/etc/nixos/configuration.nix` again — the flake pulls it in on the
`./configuration.nix` line, so everything already on this machine keeps working.

**Not using flakes at all?** The package is reachable the old way too, though the module examples
below assume a flake:

```nix
(import (fetchTarball "https://github.com/SanityProtocol/swg-panel/archive/main.tar.gz"))
  .packages.x86_64-linux.default
```

**Want to look before you commit to any of this?** These touch nothing on the machine:

```bash
nix build github:SanityProtocol/swg-panel          # just builds the package
nix flake check github:SanityProtocol/swg-panel    # ⚠️ builds two NixOS VMs — minutes, not seconds
```

To build against **your** nixpkgs rather than ours, add the overlay in `configuration.nix`:

```nix
nixpkgs.overlays = [ inputs.swg-panel.overlays.default ];   # → pkgs.swg-panel
```

### Step 3 — pick a delivery method

|  | `container` (default) | `native` |
|---|---|---|
| what runs | the images we publish | our programs from your store |
| datapath | kernel module **if the host has one** (see [step 7](#step-7--optional-give-a-container-node-the-kernel-datapath)), else userspace | kernel module, installed by the module |
| kernel-module exposure | **none** | a module that will not build **fails your `nixos-rebuild`** |
| in your closure and rollbacks | the image digest | everything |
| turn / WDTT / csqtt | sibling containers + supervised subprocesses | host units, in a probed unit directory |
| reboot after the first switch | no | yes, once, for the kernel module |

Rough guidance: take **native** for throughput and for a closure that contains everything; take
**container** to keep the host's kernel tree out of it entirely. See
[Where support ends](#where-support-ends) for the one boundary worth reading before you commit to
the native arm.

⚠️ **On the container arm, set `backend = "podman"`.** It defaults to `docker`, and nixpkgs marks
the `docker` package insecure — so a `backend = "docker"` host refuses to evaluate on a stock
channel until you bump nixpkgs or add `nixpkgs.config.permittedInsecurePackages`. Podman carries no
such flag and runs the same image. Every container example below sets it.

### Step 4 — put the secrets on the box

Write only the ones this box needs — a panel needs a password, a node needs a token, a master needs
both.

⚠️ **A node token comes from a panel that is already running.** If you are building your first
box, install the **panel** now (skip the node lines here), then mint the token in its **Nodes**
screen and come back. The one exception is a **master**, where you generate the token yourself
before either service starts — that is the whole point of `localNode`, and its own step 5 block
shows how.

```bash
sudo install -d -m 0700 /etc/swg-secrets

# Panel: the INITIAL login password.
printf 'PANEL_PASSWORD=%s\n' 'choose-something-long' | sudo tee /etc/swg-secrets/panel.env >/dev/null

# Node, container arm: the token from the panel's Nodes screen.
printf 'NODE_TOKEN=%s\n' 'paste-the-token' | sudo tee /etc/swg-secrets/node.env >/dev/null

# Node, native arm: the RAW token, no KEY= prefix.
printf '%s' 'paste-the-token' | sudo tee /etc/swg-secrets/node-token >/dev/null

sudo chmod 0600 /etc/swg-secrets/*
```

`PANEL_PASSWORD` seeds the **initial** login and is then ignored — the panel owns its auth file
afterwards and the password is changed in the UI. Re-asserting it on every boot would quietly undo
that, so the module seeds only when there is no login at all.

The two node spellings are not interchangeable. `tokenFile` carries the raw token and is **native
only** (it is read via systemd's `LoadCredential`); the container arm reads `NODE_TOKEN=…` from
`environmentFile`, because a host credential cannot cross into a container.

### Step 5 — declare what this box runs

Everything from here on goes in **`/etc/nixos/configuration.nix`**, inside the outer `{ … }`
alongside the settings already there:

```bash
sudo nano /etc/nixos/configuration.nix
```

Pick one of the three below and paste it in. The blocks are written as complete files — if you are
pasting into an existing `configuration.nix`, take only the `services.swg-*` (and `security.acme`,
`services.nginx`, …) lines and leave its own outer braces and its `{ config, pkgs, ... }:` header
alone. Save with **Ctrl+O, Enter, Ctrl+X**; step 9 applies it.

The panel's **Nodes** screen prints this same sequence — token file → `flake.nix` →
`nixos-rebuild` — filled in for whichever arm you choose, if you would rather copy it from there.

#### A panel

```nix
{
  services.swg-panel = {
    enable = true;
    backend = "podman";                                  # delivery defaults to "container"
    domain = "panel.example.org";
    environmentFile = "/etc/swg-secrets/panel.env";      # must define PANEL_PASSWORD=

    # Where subscription links are published. Say this, or none can be issued — see below.
    sub.publicUrl = "https://panel.example.org";
  };

  # The panel listens on 127.0.0.1:8443 by default. Terminate TLS in front of it.
  security.acme = {
    acceptTerms = true;                                  # required, or no certificate is issued
    defaults.email = "you@example.org";
  };
  services.nginx.virtualHosts."panel.example.org" = {
    enableACME = true; forceSSL = true;
    locations."/".proxyPass = "http://127.0.0.1:8443";
  };
}
```

If you would rather the panel terminate TLS itself and skip the proxy, set
`useACMEHost = "panel.example.org"` and `host = "0.0.0.0"`: it reads the certificate `security.acme`
already manages, joins its group, and is reloaded on renewal.

⚠️ **`host` defaults to `127.0.0.1`.** That is right behind a local reverse proxy and wrong for
anything else — a panel reached directly, or proxied from another machine, needs `host = "0.0.0.0"`
or nothing can connect to it.

⚠️ **With none of `sub.domain`, `sub.basePath` or `sub.publicUrl` set, no subscription base is
written and subscription links cannot be issued.** Deliberate: the only address the module could
otherwise derive is the panel's own, and a subscription link that opens the panel is worse than one
that visibly does not exist yet. If swg-sub shares the panel's hostname on a different port, say so
explicitly — the module refuses to guess a URL that would point at the panel.

The subscription surface (**swg-sub**) comes with the panel on both arms and is installed **inert**:
the whole surface 404s until you enable it in Settings → Subscriptions.

#### A node

**Container arm:**

```nix
{
  services.swg-node = {
    enable = true;
    backend = "podman";
    panelUrl = "https://panel.example.org:8443";
    endpoint = "203.0.113.10";                           # the public IP CLIENTS dial
    environmentFile = "/etc/swg-secrets/node.env";       # defines NODE_TOKEN=
  };
}
```

**Native arm:**

```nix
{
  services.swg-node = {
    enable = true;
    delivery = "native";
    panelUrl = "https://panel.example.org:8443";
    endpoint = "203.0.113.10";
    tokenFile = "/etc/swg-secrets/node-token";           # the raw token
  };
}
```

The first native switch installs the AmneziaWG kernel module, so **reboot once** afterwards —
`awg-quick` runs on the userspace datapath until you do. The module says so when it matters and
stays quiet when it does not.

Every interface port lands on the host in both arms (host netns), so there is nothing to publish:
the one you configure and every one the panel picks later are already there.

#### A master — panel and node on one machine

The other install methods offer this too; here it is `localNode`, and what it removes is a round
trip. Without it you bring the panel up, mint a token in the Nodes screen, put it in a secrets file
and rebuild again. You generate the token yourself; nothing is minted into the Nix store. Hand the
same token to both modules:

```bash
tok=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')   # 64 hex chars, coreutils only
printf '%s' "$tok" | sudo tee /etc/swg-secrets/node-token >/dev/null
printf 'NODE_TOKEN=%s\n' "$tok" | sudo tee /etc/swg-secrets/node.env >/dev/null
sudo chmod 0600 /etc/swg-secrets/node-token /etc/swg-secrets/node.env
```

```nix
{
  services.swg-panel = {
    enable = true;
    backend = "podman";
    domain = "panel.example.org";
    environmentFile = "/etc/swg-secrets/panel.env";
    sub.publicUrl = "https://panel.example.org";
    localNode = { enable = true; tokenFile = "/etc/swg-secrets/node-token"; };
  };

  services.swg-node = {
    enable = true;
    backend = "podman";
    endpoint = "203.0.113.10";                           # what CLIENTS dial
    panelUrl = "http://127.0.0.1:8088";                  # what THIS node dials — see below
    verifyPanelTls = false;
    environmentFile = "/etc/swg-secrets/node.env";       # the same token
  };
}
```

The panel stores only the token's hash. Re-running is safe: an entry that already validates is left
alone, and one whose token changed is refreshed in place rather than duplicated.

⚠️ **The node dials `http://127.0.0.1:<localPort>`, not the public address.** That endpoint exists
for exactly this and a public address change never moves it — dialing the public URL instead would
send the box's own node out through your reverse proxy and back, and break on the next address
change. It is **plain HTTP by construction** (the panel adds it with no certificate), which is why
`verifyPanelTls = false` belongs there; the module warns if you point it at `https://127.0.0.1`.

On a **native** master, set `delivery = "native"` on both modules.

⚠️ **This block sets up no way IN.** It is the enrolment half only — `host` still defaults to
`127.0.0.1` and nothing terminates TLS, so the panel is reachable from the box and nowhere else.
Add the `security.acme` + `services.nginx` half from [the panel block above](#a-panel), or
`useACMEHost` + `host = "0.0.0.0"`, exactly as you would for a panel on its own. The node half is
unaffected either way: it dials the loopback endpoint, not the public address.

### Step 6 — open the UDP ports

**Do not skip this.** NixOS filters `INPUT` by default, and our interfaces get their ports from the
**panel, at runtime**, while `networking.firewall` is evaluated at **build** time. Left alone, an
interface you create in the panel syncs, reports healthy, shows its peers — and no client can reach
it.


In `/etc/nixos/configuration.nix`:
```nix
services.swg-node.udpPortRanges = [ { from = 51820; to = 51899; } ];
```

That opens the range **and** tells the node what was declared, so the **panel raises a node issue**
the moment an interface lands outside it, instead of leaving you to work it out from a connection
that never handshakes. Keep the range in step with what you use in the UI. Leave it empty and the
module says so at build time; `networking.firewall.enable = false` silences both.

### Step 7 — optional: give a container node the kernel datapath

The container arm deliberately declares **no** kernel module — that is what its "kernel-module
exposure: none" row means. It uses the host's module if the host has one, and the userspace
`amneziawg-go` datapath if it does not. For the faster datapath on a container node, declare the
module yourself:


In `/etc/nixos/configuration.nix`:
```nix
boot.extraModulePackages = [ config.boot.kernelPackages.amneziawg ];
boot.kernelModules = [ "amneziawg" ];
```

Reboot once after the first switch. `services.swg-node.kernelModule` does **not** do this — it is a
native-arm option and is inert on the container arm.

### Step 8 — optional: let the panel manage turn proxies

Turn management mounts the container runtime's socket into the node, which is root on this host, so
it is off by default on the container arm. On podman it also needs a docker-compatible CLI and a
rootful socket — the module asserts this rather than failing obscurely later:


In `/etc/nixos/configuration.nix`:
```nix
services.swg-node.turnManage = true;

virtualisation.podman = {
  dockerCompat = true;          # the daemon shells out to `docker`
  dockerSocket.enable = true;   # …and drives sibling containers through a rootful socket
};
```

A **native** node manages turn proxies unconditionally, with no socket involved.

If you also run **csqtt** servers on a container node, add `seccomp = "unconfined"` — see
[csqtt needs seccomp](#csqtt-on-the-container-arm-needs-seccomp).

### Step 9 — rebuild, then check it worked

Apply everything (`myhost` = what `hostname` printed back in step 2):

```bash
sudo nixos-rebuild switch --flake /etc/nixos#myhost
```

The first run downloads a fair amount and can take several minutes. It ends with
`Done. The new configuration is /nix/store/…`, having listed the units it started along the way —
`podman-swg-panel.service`, `podman-swg-node.service` and friends.

**If it fails, nothing changed.** A `nixos-rebuild` is atomic: the machine keeps running exactly
what it ran before, so you can read the error, edit the file and run it again. If a rebuild
*succeeded* and left you worse off, step back one generation:

```bash
sudo nixos-rebuild switch --rollback
```

Now check the services. Use the `podman-*` names on the container arm and the plain ones on the
native arm:

```bash
# Panel
systemctl status podman-swg-panel      # or swg-panel-server on the native arm
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8088/healthz        # 200 = up
```

`/healthz` is the unauthenticated liveness probe, on the panel's dedicated loopback port
(`localPort`, 8088 by default). Any `/api/` path answers 401 until you log in, which is also a
healthy answer — but a *wrong path* answers 401 too, so it makes a poor check.

```bash
# Node
journalctl -u podman-swg-node -n 20    # or swg-noded on the native arm
```

You are looking for `syncing to https://… (interfaces: …, endpoint …)` and **no** `sync error`
lines. `Connection refused` here means the node cannot reach `panelUrl` — check the address, and on
a master check it is the loopback one from step 5, not the public address.

Then log in to the panel with the password from step 4, and change it in the UI — it was only ever
the seed. Your node appears in **Nodes** and goes online within one sync interval.

Two things people hit right after this:

- **The node is online but no client connects.** That is step 6 — the firewall. NixOS filters
  `INPUT`, and an interface the panel picked a port for is not in your `udpPortRanges`.
- **Nothing is listening on the public address.** The panel binds `127.0.0.1` by default; see the
  `host` note in step 5.

---

## Updating

The panel never runs its own updater. It touches a file, and a root unit decides what "update"
means — `bootstrap.sh update` on bare metal, `compose pull && up` in Docker, and here a rebuild.

### The Update button, on by default

`selfUpdate.enable` defaults to `true`, with `flakeRef = "/etc/nixos#<hostname>"` and
`updateInputs = [ "swg-panel" ]`. The panel's config snippet names its flake attribute `swg` and
sets `flakeRef = "/etc/nixos#swg"` to match, so the button works on a stock install with nothing
else to set. Point it elsewhere only if your flake lives elsewhere or its attribute is not the
hostname:

```nix
services.swg-panel.selfUpdate = {
  flakeRef = "/etc/nixos#myhost";   # your flake#attribute; the default assumes #<hostname>
  updateInputs = [ "swg-panel" ];   # refreshed before the rebuild
};
```

`services.swg-node.selfUpdate` takes the same three options. On a host running both, each has its
own trigger and its own unit; they rebuild the same machine and each keeps a stamp, so one rebuild
does not provoke the other.

⚠️ **`updateInputs` is the difference between an update and a no-op.** A rebuild builds what your
lock pins, which is very often the version already running — so name the input this module came
from, or the button will succeed and change nothing. It only applies to a local flake; a remote
`flakeRef` is fetched fresh on every build, and naming inputs against one fails the build rather
than quietly doing less than you asked.

### Updating by hand

```bash
sudo nix flake update swg-panel --flake /etc/nixos
sudo nixos-rebuild switch --flake /etc/nixos#myhost
```

To take the button out of the loop entirely, set `selfUpdate.enable = false`. The dialog then shows
the exact `nixos-rebuild` to run and says plainly that nothing is wired, rather than letting the
button report success and change nothing. A node behaves the same way, and refuses the bootstrap
updater — which on a host like this appears to work, writes into `/opt`, and leaves an install your
configuration cannot see — reporting why instead.

### ⚠️ On the native arm, a rebuild does not restart the daemon

A new version does not take effect until you restart it. That is deliberate: a restart re-runs the
bootstrap, which brings each interface down and up, and every connected client drops until the next
reconcile.

```bash
sudo systemctl restart swg-noded        # when you are ready for the bounce
```

Set `restartOnRebuild = true` if you would rather have it happen automatically.

### When a rebuild fails, you get the reason

`nixos-rebuild` can fail for causes that have nothing to do with swg — an unrelated input that will
not fetch, an out-of-tree kernel module against a new kernel — and it fails *after* the services it
was updating have been restarted, so nothing in them sees it. The unit writes its verdict and the
tail of its output where the panel and the node read them, so the UI distinguishes "the button is
broken" from "your kernel pin needs bumping". When the flake the defaults expect is not there, the
rebuild fails with an actionable message — which `flakeRef` to set, or to disable and run it by
hand — not a raw `nix` error.

**The rebuild yields, so pressing Update cannot take the box down.** `nixos-rebuild` evaluates a
whole system, and on a small entry server (2 CPU / ~2 GB) an unconstrained run saturates both cores
and drives memory into reclaim — enough to stop sshd answering and the panel serving *while it
builds*. The update unit therefore runs niced, idle-IO and as the first out-of-memory victim, so
interactive work always wins and, if memory does run out, the kernel kills the rebuild (which is
atomic — the running system is untouched) and reports it, never the panel or the daemon. That keeps
the button *safe* on any size box; to let it *succeed* under ~2 GB, give the evaluation headroom:

```nix
zramSwap.enable = true;      # or a swapDevices entry
```

Podman's `io.containers.autoupdate=registry` remains available on the container arm if you would
rather the runtime chase the image; this module does not wire it.

---

## Moving an existing install onto NixOS

The likeliest first thing anyone does here is not a fresh install — it is moving the box they
already run. What is at stake in that move is **identity**: each interface's private key, each WDTT
instance's `wg-keys.dat`, each csqtt password store, and the node's enrolment token. Every one of
them is something clients are already talking to, and re-minting any of them looks exactly like a
successful move until the clients stop connecting.

The good news is that most of it does not move at all.

| from → to | what moves |
|---|---|
| bare-metal → **native** | **nothing.** The native arm keeps bare-metal's paths on purpose, and the module asserts them. |
| docker → **container** | **nothing.** Point the module at the dirs the compose stack already mounts. |
| bare-metal → **container** | the run-model-specific paths only: WDTT, csqtt, their records, the turn record. |
| docker → **native** | the same set, the other way, plus the interface confs. |

### ⚠️ Re-use the token. Do not mint a new one.

A node is identified to the panel by its **token**, and the panel maps that token to the entry your
peers are assigned to. So:

- **Right:** take the token the box already holds — `adopt.sh` finds it
  (`/etc/swg-agent/config.json` on bare metal, `NODE_TOKEN` in the docker `.env`) and
  `--token-out FILE` writes it out for your secrets tooling. Or, if it is lost, **Nodes → the node →
  Rotate token**, which issues a new token for the *same* entry.
- **Wrong:** "add a node" in the panel and use that token. That mints a *new* entry. The box comes
  up as a second node beside the first, and — because the new entry has no peers assigned — its next
  reconcile **removes every peer from the live interface**. Measured, not feared: that is what the
  control in `probeM1-run.sh` does, and it is why `adopt.sh` reads the token for you.

On a **master**, `localNode.name` must be the name the panel already uses for this node, or the
enrolment seeder writes a second entry beside it rather than refreshing the one you have.
`adopt.sh` prints the right name — it finds it by verifying the token against each entry's hash, the
same way the panel does.

### The order matters

`nixos-rebuild` cannot remove units a package manager installed, and once this host is declarative
`/etc/systemd/system` is read-only — at which point both `uninstall.sh` and `adopt.sh` **refuse**,
because a `systemctl disable` that fails there leaves a script deleting files out from under running
services. Run these **on the box that has the install, while it is still imperative**.

#### Step 1 — report (changes nothing)

```bash
sudo ./nix/adopt.sh --to native        # what is here, what carries, the config to paste
```

Add `--token-out /etc/swg-secrets/node-token` to have it write the existing token out for you.

#### Step 2 — carry, if the route needs one

```bash
sudo ./nix/adopt.sh --to native --carry
```

It copies; the originals stay put, so an abort loses nothing. A no-op on the two routes where
nothing moves.

#### Step 3 — release the old units

```bash
sudo ./nix/adopt.sh --to native --release
```

Units only. It stops each service **and checks that it actually stopped** before removing its file,
and it keeps every byte of state.

⚠️ **Do not use `uninstall.sh` for this step.** It signs the node off the panel
(`/api/node/goodbye`) and deletes `/var/lib/swg-noded`, `/etc/swg-agent` and
`/opt/swg-{wdtt,csqtt}` — precisely the identity the move exists to keep.

#### Step 4 — declare the module and rebuild

Leave `services.swg-node.interfaces` **unset**. The confs already on disk are the interface set;
that option only seeds a node that has none.

### Route notes

**bare-metal → native.** Nothing to copy: `/etc/amnezia/amneziawg`, `/etc/wireguard`,
`/etc/swg-agent`, `/var/lib/swg-noded` and `/opt/{vk-turn-proxy,swg-wdtt,swg-csqtt}` are already
where the module looks.

**docker → container.** Nothing to copy either — point the module at the dirs the compose stack
already mounts:

```nix
services.swg-node  = { stateDir = "/opt/swg-panel-docker/data/node"; confDir = "/opt/swg-panel-docker/data/node-confs"; };
services.swg-panel = { stateDir = "/opt/swg-panel-docker/data/lib"; configDir = "/opt/swg-panel-docker/data/etc";
                       statsDir = "/opt/swg-panel-docker/data/stats"; subTlsDir = "/opt/swg-panel-docker/data/sub-tls"; };
```

`--release` takes the compose stack down. It deliberately leaves the `swg-turn-*` containers alone:
they are not compose-managed, and the node picks them straight back up.

**The two cross routes.** `--carry` calls the same helpers the docker↔bare-metal convert uses, so
there is exactly one copy of the path map in this repository. It never moves; it copies, and it is
loud when it cannot — a silent failure here is the one that looks like success.

- **docker → native** also brings the interface confs to `/etc/amnezia/amneziawg` (a native node's
  `stateDir` and `confDir` cannot be moved — the module asserts them). One thing does **not** come
  across: turn proxies. A bare-metal-convention node reads its turn set from the **units on disk**,
  and `adopt.sh` writes none, so re-create each proxy from the panel afterwards — the carried record
  keeps its listen/connect/fork, so you are re-entering nothing. If this box still runs a distro the
  installers support, `./convert.sh docker baremetal node` does the same carry *and* rebuilds the
  turn units, after which this becomes the no-op route above.
- **bare-metal → container** carries WDTT, csqtt and both records into `stateDir`, plus the turn
  record (on this arm the record *is* the config, and the node recreates each proxy as a container
  from it). Plain-WireGuard confs in `/etc/wireguard` are copied into `confDir` as well: a container
  node never mounts that directory, so an interface left there would silently drop out of the
  managed set.

### One extra step for an adopted native panel

The panel runs as `swgpanel:swg`, and NixOS allocates its own ids for those accounts — so state
copied from another machine is owned by a uid that no longer means anything here:

```bash
sudo chown -R swgpanel:swg /var/lib/swg-panel && sudo chown -R root:swg /etc/swg-panel
```

Skip it and the panel **refuses to start** rather than starting on an unreadable roster. That
refusal is deliberate and worth knowing about: a panel that came up with an empty roster would tell
every node it has no peers, and the nodes would believe it.

Your existing login is kept. `environmentFile` is still required, but its `PANEL_PASSWORD` is only
ever used to seed a panel that has **no** login at all, so on an adopted one it is read and ignored.

### Checks that say it worked

- The panel shows **one** entry for this box, not two, and it goes online.
- Each interface's public key is the one it had before (`awg show <iface> public-key`), and its
  peers come back after the first sync.
- `sha256sum /opt/swg-wdtt/*/wg-keys.dat` is unchanged from before the move.

---

## Removing

### Removing a node

**1. Delete the node in the panel's Nodes screen.** Both installers call `/api/node/goodbye` on
their way out; removing the module from your configuration tells the panel **nothing** —
`nixos-rebuild` stops the unit and takes the files away, and from the panel's side that is
indistinguishable from a node that went quiet. It goes `dangling` and stays there. This is the same
step you would take for a box that burned down, and the panel renders that state correctly: its
peers stay assigned until you delete it, which is what you want while you are *moving* a node rather
than retiring one.

**2. Take the module out of your configuration and rebuild.**

```bash
sudo nano /etc/nixos/configuration.nix
```

Either set the flag, or delete the whole `services.swg-node = { … };` block:

```nix
services.swg-node.enable = false;
```

```bash
sudo nixos-rebuild switch --flake /etc/nixos#myhost
```

The node's **turn proxies go with it.** Nothing in the generation describes them — the panel creates
them at runtime, as sibling containers on the container arm and as `vk-turn-proxy-*` units on the
native one — so a removal has to stop them explicitly or they stay running, still bound to their
public UDP ports, on a box you had just decommissioned. Only a removal does this: a restart, or a
rebuild that merely changes the node, leaves them alone. What they are stays behind with the rest of
the state, so re-enabling the module brings them back.

**3. Delete the state by hand, when you mean it.** `stateDir`, `confDir` and the interface keys are
not removed by a rebuild — `StateDirectory` has no removal semantics, and it would be the wrong
default here anyway: those files are the node's identity.

```bash
sudo rm -rf /var/lib/swg-noded /etc/amnezia/amneziawg /etc/wireguard /etc/swg-agent \
            /opt/swg-wdtt /opt/swg-csqtt /opt/vk-turn-proxy
```

A container node can leave address-carrying husk interfaces behind — its userspace datapath devices
outliving the container, with nothing running on them. They are harmless and do not block a
re-install; remove them with `ip link del <iface>` if you want the box clean.

### Removing the panel

In `/etc/nixos/configuration.nix`, either set the flag or delete the whole
`services.swg-panel = { … };` block, then rebuild:

```nix
services.swg-panel.enable = false;
```

A rebuild takes the panel, swg-sub, their units and their ports with it, and leaves the state alone.
Delete that when you mean it:

```bash
sudo rm -rf /var/lib/swg-panel /etc/swg-panel
```

⚠️ `/var/lib/swg-panel` is the **roster** — every peer, every node entry, the login and the
subscription vault. There is no other copy. Back it up before you delete it.

### Removing everything from the box

```bash
# 1. delete the node in the panel first (see above), then rebuild with both modules gone:
sudo nixos-rebuild switch --flake /etc/nixos#myhost

# 2. state
sudo rm -rf /var/lib/swg-panel /var/lib/swg-noded /etc/swg-panel /etc/swg-agent \
            /etc/swg-secrets /etc/amnezia /etc/wireguard \
            /opt/swg-wdtt /opt/swg-csqtt /opt/vk-turn-proxy

# 3. leftover tunnel devices, if any
for i in $(ip -br link | awk '{print $1}' | grep -E '^(wg|awg|swg_|wdtt|csqtt)'); do
  sudo ip link del "$i"
done

# 4. on the container arm: images, networks, and podman's own leftovers
sudo podman system reset -f
```

⚠️ **`podman system reset` rather than `podman rmi -af`.** Removing images leaves podman's DNS
helper running and still holding `10.88.0.1:53`, and the next container that wants the default
network fails to start with `aardvark-dns failed to start: … Address already in use` — on a box you
had just cleaned, which is the last place you would look. `reset` takes the networks and the helper
with it.

⚠️ **`uninstall.sh` refuses on a declarative host, `--dry-run` included**, and that refusal is the
right answer: it cannot remove units `nixos-rebuild` owns, and half-removing them is worse than not
starting.

---

## Reference

### csqtt on the container arm needs `seccomp`

csqtt's dataplane is io_uring and has no fallback, and the default seccomp profile of both runtimes
denies `io_uring_setup` — so a csqtt server inside the node container dies the instant it starts,
with `create io_uring`. That is a container setting, not anything the panel can reach:

```nix
services.swg-node.seccomp = "unconfined";   # only if you run csqtt servers on this node
```

It is not the default because it turns the profile off for the whole node container, and most nodes
run no csqtt at all. WDTT and turn proxies do not need it. The panel says which option to set when
it sees the failure.

### Interfaces are not in your `configuration.nix`

That is deliberate — they are fleet state, like peers, and making you rebuild per interface would be
a different product — but `nixos-rebuild` cannot see them. They live in `stateDir`/`confDir`,
survive a system rollback, and `stateDir` must persist if you run impermanence.

### Access & TLS: read-only, and where the address comes from

Settings → **Access & TLS** is the panel's whole address and certificate mechanism everywhere else.
Here it is a **read-only view**: it shows the options that carry the address this panel is actually
running, and the panel refuses an address, mount-path or certificate change at the API — the save
and the apply both — rather than accepting one that the next rebuild would undo.

That leaves the module holding the address, so the module writes it:

| option | what it decides |
|---|---|
| `domain`, `basePath`, `port`, `useACMEHost` | the URL the panel advertises, and whether it terminates TLS itself |
| `publicUrl` | that URL verbatim, when the derivation above is not it (a plain-HTTP proxy, an unusual public port) |
| `sub.domain`, `sub.basePath`, `sub.publicUrl` | the base every subscription link is built from |

These are written into the panel's own settings on **every start**, so a `nixos-rebuild` is how the
address changes — including the confirmed-address baseline, which everywhere else only ever advances
through a browser confirm that cannot be performed here.

**The operator console can have its own port, and here that is the only way to move it.** Elsewhere
an operator flips this in Access & TLS and confirms it in a browser; that screen is read-only here, so
the option *is* the switch — set a port and the console moves there, leave it 0 and there is one door
as before.

```nix
services.swg-panel.consolePort = 8445;      # 0 = off, the default
services.swg-panel.consoleHost = "127.0.0.1";   # loopback: reached over an SSH tunnel, nothing exposed
```

`port` then answers only what a node dials and returns **404** for everything else — the console pages,
the operator API and `/api/v1/*` and `/metrics` all move to the tunnel port with you. Nothing about the
fleet changes: nodes keep dialling the same address, which keeps answering the same routes.

Nothing opens the firewall for you. Left on loopback the console is reachable only from the box —
`ssh -L 8445:127.0.0.1:8445 <this host>`, then `http://localhost:8445` — and is served over plain HTTP,
because loopback carries no eavesdropper. Widen `consoleHost` and it is served with the panel's own
certificate and the firewall rule is yours to write.

**TLS is subtracted, not ported.** The panel image bundles acme.sh and the bare-metal installer
drives it; neither runs here. `security.acme` and your reverse proxy own certificates — which is
what every comparable nixpkgs module does.

The privileged helper the panel uses elsewhere for this (`swg-netctl`) is **not installed on either
arm**, and does not need to be: with the guard in place, no request the panel can make ever reaches
its queue — measured on both arms, against an ordinary panel that does enqueue.

### How swg-sub is separated from the panel

It is the one process here that is deliberately reachable from the internet, so it is separated on
four axes at once:

- a **different user** (`swgsub`, group `swg`) — never the panel's,
- a **read-only filesystem** (`ProtectSystem=strict` and no `ReadWritePaths` at all),
- its **own TLS material** in its own directory — handing the panel's private key to this process
  would let its compromise impersonate the panel,
- and a **kernel-level mask** over six paths it must never open: the login hash, the panel's TLS
  directory, the subscription-key vault, the escrow, the webhook/API secrets, and any stored client
  configs. Masked rather than merely unreadable, so a bug in this process cannot reach them even if
  the file permissions were wrong.

### Where support ends

**nixpkgs owns the native datapath.** `linuxPackages.amneziawg` is an out-of-tree kernel module
maintained there, not here; when it stops building against a new kernel that is a nixpkgs issue and
we will help, but we do not own it. The container arm we support end to end, because nothing in it
depends on the host's kernel tree.

That boundary is only tolerable because the recovery is two lines and does not cost you the product:

```nix
services.swg-node.kernelModule = false;   # fall back to the userspace datapath
```

`awg-quick` tries the kernel device first and uses `amneziawg-go` when it is not there, so nothing
else changes — same interfaces, same peers, same conf files, less throughput. Turn it back on when
the module builds again.

It is also instrumented rather than mysterious: a failed rebuild writes its reason and the tail of
its output where the panel and the node read them, so the Update dialog says *your kernel pin needs
bumping* instead of *the button is broken*. And this repo's own CI floats nixpkgs weekly against
both VM suites for exactly this — the early warning is meant to reach us before it reaches you.

### Switching `delivery` on a node that already runs

Changing `delivery` and rebuilding is not a migration, and it is not a supported one — the two arms
keep state in different places on purpose, so what the running node can see changes with it.
Measured on a live master, native → container → native:

- **Plain-WireGuard interfaces disappear.** Their confs are in `/etc/wireguard`, which the container
  does not mount (it gets `confDir` only, and a container-arm install writes *every* conf there,
  `wg` and `awg` alike). The interface itself keeps running — the panel reports it as **missing with
  a restore offered**, and it comes back when you switch back.
- **turn / WDTT / csqtt go with the arm.** The native arm's fork servers are host units with their
  state under `/opt`; the container arm's are supervised subprocesses under the mounted state dir.
  Neither can see the other's, so the panel reports them missing on whichever arm did not install
  them. The host's copies are untouched — identities and password stores survive the round trip.
- **Turn management is opt-in on the container arm only.** A native node manages turn proxies
  unconditionally, so a switch turns that off unless you ask for it, and the panel's turn cards go
  read-only with a line saying why.

If you want the other arm, prefer recreating the node's interfaces on it over switching in place. If
you do switch, expect the panel to walk you through the restores — none of the above loses a key.

The native arm keeps **bare-metal's paths on purpose** (`/var/lib/swg-noded`,
`/etc/amnezia/amneziawg`), which is what makes
[moving an existing bare-metal node here](#moving-an-existing-install-onto-nixos) move no data at all.

### Living with a declarative host

Four things this repo has been bitten by, none of them obvious from either side alone.

**`networking.nftables.flushRuleset` — set it to `false` if you use nftables.** It flips to `true`
on its own the moment you set `nftables.ruleset` or `rulesetFile` (and for `stateVersion` below
23.11), and then every reload issues `flush ruleset`, which takes our tables with it. Routing and
blocking self-heal on the next reconcile, so the symptom is a minute of traffic doing the wrong
thing after an unrelated rebuild — the hardest kind of report to act on.

```nix
networking.nftables.flushRuleset = false;
```

Note also that `networking.nftables.enable` blacklists `ip_tables`, which kills iptables-**legacy**.
`iptables-nft` is unaffected, and that is what we use.

**Pinning `boot.kernelPackages` is what makes the datapath risky**, not NixOS. On the channel's
default kernel the AmneziaWG module comes prebuilt from cache.nixos.org; pin ahead of what Hydra has
built and you are asking for an out-of-tree module to compile against a kernel nobody has tried it
on — and because it is a build dependency of your system closure, failing means your whole
`nixos-rebuild` fails. See [Where support ends](#where-support-ends) for the two-line recovery.

**Impermanence: `/var/lib/swg-noded/` must persist.** A token-enrolled node survives an "erase your
darlings" wipe, because the token is re-supplied from your secrets. **Self-generated identities do
not** — each interface's private key is generated on the node and lives there. Wipe that directory
and every client's `[Peer]` public key stops matching: the panel still shows the node, the interface
still comes up, and nothing hand-shakes. The fork binaries the node downloads live there too and are
deliberately not in the closure, so a rollback does not bring them back either.

**`nixos-rebuild --rollback` rolls back the code, not the state.** Peers, interfaces and routing
lists are fleet state that the panel owns — a rollback puts the previous programs back and they read
today's state, which is the behaviour you want and worth knowing before you reach for it.

### What the package contains

One derivation, because the repository is one unit: `VERSION` is the single source of truth stamped
into every component, so splitting it would put version skew a rebuild away.

| path | what |
|---|---|
| `libexec/swg-panel/` | `swg-panel-server` + the SPA (`js/`, `vendor/`, `index.html`, …) + `VERSION` |
| `libexec/swg-sub/` | `swg-sub` + its static assets + `VERSION` — a separate unit, user and TLS dir |
| `libexec/swg-noded/` | `swg-noded`, `swg-sni`, `VERSION` |
| `libexec/swg-agent/` | `swg-agent` |
| `libexec/swg-node/` | `node-entrypoint.sh` — the node's bootstrap, shared with the container images |
| `bin/` | `swg-netctl`, `swg-passwd`, and wrappers for the five programs above |

Two of the programs resolve files **relative to themselves** — `swg-noded` looks for `VERSION` and
`swg-sni` beside itself, the panel and `swg-sub` fall back to `VERSION` beside themselves — so each
program ships in a directory with its own data, mirroring what the installers write to `/opt`. The
`bin/` entries **exec** those paths rather than symlinking to them: for a symlinked script the
kernel hands the interpreter the *symlink's* path, so both lookups would miss. That is measured, not
assumed — the panel launched through a symlink reports an empty version.

Every program's `#!/usr/bin/env python3` is rewritten to a store interpreter at build time, so a
node does not depend on `python3` being in its system profile. (`node-entrypoint.sh` still calls
`python3` from `PATH` to compute interface subnets, so the module supplies one anyway.)

### What Nix does *not* manage

The panel keeps a lot of things fresh, and most of it is **data, not code**: turn-proxy fork
binaries, routing and blocking lists, GeoIP, the catalog, TLS fingerprints. All of that keeps
working untouched. The store-managed set is four artifacts — three Python programs and the SPA.

⚠️ **Downloaded fork binaries are not in the closure.** They live in the node's state directory,
which is deliberate (they are third-party artifacts on a dynamic catalog, not ours to pin), but it
means `nixos-rebuild --rollback` does not restore them. `/var/lib/swg-noded/` is must-persist.

### What is supported

| | |
|---|---|
| `nix/package.nix`, `flake.nix`, `default.nix` | the package, the overlay, `checks` |
| `services.swg-node`, `delivery = "container"` | the shipped image, driven by `virtualisation.oci-containers` |
| `services.swg-node`, `delivery = "native"` | our programs from the store, the kernel datapath, host units |
| `udpPortRanges` | the runtime-port ↔ declarative-firewall collision, opened and reported |
| `services.swg-panel`, both arms | the control plane; swg-sub rides along on both |
| swg-sub, both arms | its own user, its own TLS dir, and a six-path kernel mask |
| Access & TLS guard | the screen is read-only; the module writes the address, on both arms |
| self-update | the Update button as `nixos-rebuild switch --flake`, on by default, niced so it cannot starve the box, with the failure reason |
| master role | panel + co-located node, enrolled from one shared token file |
| adoption | moving an existing bare-metal or docker install onto either arm, identity intact |
| VM tests + CI | `checks.x86_64-linux.{fleet-native,container-arm}`, weekly against our pin and against the channel |
| the installers refuse here | `bootstrap.sh` and the five installers detect a declarative host and stop |

### Upstreaming intent

The `services.swg-panel` and `services.swg-node` option namespaces are **claimed by this
repository**. The module is maintained here, at the same commit as the code it starts, rather than
in a separate `swg-panel-nix` repo — every comparable project that ships its own NixOS module does
the same, for the same reason. If a nixpkgs module for swg-panel is ever proposed, it should be this
one, moved; two modules owning one namespace break for anyone who imports both.

Two VM suites run against the flake — a panel and a real native node converging on the kernel
datapath, and the container arm's host-side half. A weekly workflow builds both **twice**: once
against the committed `flake.lock`, which gates our own changes, and once with the nixpkgs input
floated to the channel, which is the early warning for the support boundary above and is allowed to
fail without failing the run. `.github/workflows/nix.yml`; deliberately off the image build's path.
