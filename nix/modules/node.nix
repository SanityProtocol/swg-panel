# services.swg-node — an entry server, declared.
#
# Two delivery methods, both first-class (docs/NIXOS-SUPPORT-PLAN.md D13):
#   container  the images we already publish, driven by virtualisation.oci-containers
#   native     our programs from the Nix store, run directly on the host   (lands with T-N8)
#
# The panel never learns how a node was installed and the node never learns how the panel was, so
# any panel drives any node in any combination. Nothing here may become a Nix-specific wire format.
#
# ⚠️ This file re-declares, in Nix, the contract docker-compose.yml defines — env keys, capabilities,
# devices, volumes, sysctls. Nothing in the language keeps the two in step, so
# `.campaign/compose-nix-contract.mjs` does. Run it after touching either.
{ config, lib, pkgs, ... }:

let
  cfg = config.services.swg-node;
  inherit (lib) mkOption mkEnableOption mkIf types literalExpression optional optionalAttrs;

  # What we tell the node its firewall allows — and ONLY when there is a firewall for a port to be
  # outside of. With `networking.firewall.enable = false` everything is open, so reporting a range
  # would make the panel flag interfaces that are perfectly reachable.
  declaredPorts =
    if config.networking.firewall.enable && cfg.udpPortRanges != [ ]
    then lib.concatMapStringsSep "," (r: "${toString r.from}-${toString r.to}") cfg.udpPortRanges
    else "";

  # The node's whole environment, in one place, because that IS the contract.
  env = {
    PANEL_URL = cfg.panelUrl;
    NODE_ENDPOINT = cfg.endpoint;
    # We always run the container in the host's network namespace, so every interface port — the
    # bootstrap one and every port the panel later picks — is on the host with nothing to publish.
    # The node reports this so the panel only shows port-publishing guidance where it is needed.
    NODE_NET = "host";
    NODE_IFACES = cfg.interfaces;
    NODE_MTU = toString cfg.mtu;
    DNS = cfg.dns;
    TLS_VERIFY = if cfg.verifyPanelTls then "yes" else "no";
    TLS_FINGERPRINT = cfg.panelTlsFingerprint;
    # What OWNS this installation (T-P1). `kind` stays "docker" — a NixOS host running our image IS
    # a docker node for every behavioural purpose, and overriding that would flip ~54 daemon
    # branches and five SPA sites at once.
    SWG_NODE_PLATFORM = "nixos";
    SWG_DECLARATIVE = "1";
  } // (lib.optionalAttrs (declaredPorts != "") { SWG_UDP_PORTS = declaredPorts; })
    // cfg.extraEnvironment;

  # Turn management is a CONTAINER-arm contract only. On a native node the daemon is already on the
  # host, so it manages turn proxies unconditionally — there is no socket to mount and no image to
  # name, and setting these there would be three keys that mean nothing.
  turnEnv =
    if cfg.turnManage then {
      TURN_MANAGE = "panel";
      SWG_TURN_IMAGE = cfg.turnImage;
      # ⚠️ The #1 silent failure. Turn proxies run as SIBLING containers with the fork binary
      # bind-mounted from the host, so the daemon needs the HOST path of what it sees as
      # /var/lib/swg-noded. Without it turn management is accepted and then quietly does nothing.
      SWG_HOST_NODE_DIR = cfg.stateDir;
      SWG_TURN_RECORD = "/var/lib/swg-noded/turn-proxy.json";
    } else { TURN_MANAGE = "manual"; };

  # T-N7 / D14 tier 2 — the same seam as the panel's, pointed at this node's own trigger. Built
  # unconditionally because tier ONE needs its `command`: even unwired, the failure this node reports
  # to the panel has to name what an update actually is here.
  updateTrigger = "${cfg.stateDir}/.update-request";
  rebuild = import ./rebuild.nix {
    inherit pkgs lib;
    name = "node";
    inherit (cfg.selfUpdate) flakeRef updateInputs;
    # swg-noded reads this on its next sync and forwards it as a proc-status, then deletes it. Root
    # on both arms (the daemon runs as root; the container runs as root), so no chown is needed.
    resultFile = "${cfg.stateDir}/.update-result";
    resultShape = "node";
    stampFile = "${cfg.stateDir}/.update-stamp";
    triggerFile = updateTrigger;
  };

in
{
  options.services.swg-node = {
    enable = mkEnableOption "the swg entry-server daemon (swg-noded)";

    delivery = mkOption {
      type = types.enum [ "container" "native" ];
      default = "container";
      description = ''
        How this node runs. `container` uses the images published to GHCR and carries no
        kernel-module exposure — a broken out-of-tree module cannot fail your `nixos-rebuild`.
        `native` runs the programs from the Nix store, which is what puts them in your closure and
        your rollbacks. Neither is a stepping stone to the other.
      '';
    };

    backend = mkOption {
      type = types.enum [ "docker" "podman" ];
      default = "docker";
      description = ''
        Container runtime. Podman works, including the privileged `--pid=host` helper the daemon
        uses to reach the host, but turn management shells out to a `docker` CLI, so it needs
        `virtualisation.podman.dockerCompat` and a rootful docker-compatible socket.
        Podman also refuses every pull without `/etc/containers/policy.json`, which
        `virtualisation.containers.enable` supplies.
      '';
    };

    image = mkOption {
      type = types.str;
      default = "ghcr.io/sanityprotocol/swg-node:latest";
      description = ''
        The node image. **Pin it by digest** — `ghcr.io/sanityprotocol/swg-node@sha256:…` — if you
        want the container arm to give you what the store gives the native one: a `nixos-rebuild
        --rollback` that actually goes back to the code you were running. A moving tag does not.
      '';
    };

    panelUrl = mkOption {
      type = types.str;
      example = "https://panel.example.org:8443";
      description = "The panel this node syncs to. Outbound HTTPS only — nothing dials the node.";
    };

    endpoint = mkOption {
      type = types.str;
      example = "203.0.113.10";
      description = "Public IP or hostname clients dial for this node.";
    };

    environmentFile = mkOption {
      type = types.nullOr types.path;
      default = null;
      example = "/run/secrets/swg-node.env";
      description = ''
        A file the container runtime reads at start, which must define `NODE_TOKEN=<enrolment
        token>`. Mint the token in the panel's Nodes screen; it is shown once.

        A path to a file, deliberately, and not the token itself: a token written into a Nix option
        lands in the world-readable store. Point this at sops-nix, agenix, or any file root can read.

        ⚠️ Give it a **string** path (`"/run/secrets/swg-node.env"`), not a Nix path literal
        (`/run/secrets/swg-node.env`). A path literal is copied into the store at build time, which
        is the very thing this option exists to avoid — so the module refuses one.
      '';
    };

    tokenFile = mkOption {
      type = types.nullOr types.str;
      default = null;
      example = "/run/secrets/swg-node-token";
      description = ''
        A file containing ONLY the enrolment token — no `NODE_TOKEN=` wrapper — handed to the daemon
        through systemd's `LoadCredential`. `delivery = "native"` only; when set it replaces
        `environmentFile`, which is then not needed at all.

        Preferred over `environmentFile` where it works, because the difference is not cosmetic: an
        `EnvironmentFile=` token stays in the daemon's environment for its whole life and is
        **inherited by every subprocess it spawns** — swg-agent, awg-quick, nft, the turn binaries.
        A credential is read once, out of a per-unit tmpfs, and is gone.

        ⚠️ **Not available on `delivery = "container"`**, and not for want of trying: `LoadCredential`
        mounts into the UNIT's namespace, and a container the unit starts has its own — the path
        simply is not there. That arm keeps `environmentFile`.

        ⚠️ A **string** path, not a Nix path literal, for the same reason `environmentFile` is: a path
        literal is copied into the world-readable store, which is the one thing this exists to avoid.
      '';
    };

    secretsDependencies = mkOption {
      type = types.listOf types.str;
      default = [ ];
      example = [ "sops-install-secrets.service" ];
      description = ''
        Units that must have finished before this node's token is read — the unit your secrets
        tooling runs to decrypt it.

        ⚠️ Without this there is an ordering RACE with a nasty tail. `/run/secrets` does not exist
        until sops-nix or agenix has written it; lose the race and the bootstrap exits on
        `NODE_TOKEN required`, the unit restarts, and it will recover — but on a FIRST boot it can
        instead write a `config.json` this node then treats as authoritative. Ordering after a unit
        that does not exist is harmless, so name it if you are unsure.
      '';
    };

    stateDir = mkOption {
      type = types.path;
      default = "/var/lib/swg-noded";
      description = ''
        Host directory for the node's state — server keys, turn-proxy records, learned panel URL.
        **Must persist.** A token-enrolled node survives an impermanence wipe because the secret
        re-supplies the token, but its self-generated server keys do not.
      '';
    };

    confDir = mkOption {
      type = types.path;
      default = "/etc/amnezia/amneziawg";
      description = ''
        Host directory for interface `.conf` files. Persisting these is what lets interfaces
        created from the panel — and their server keypairs — survive a container recreate.
      '';
    };

    interfaces = mkOption {
      type = types.str;
      default = "";
      example = "awg0:51820:10.8.0.1/24";
      description = ''
        Optional bootstrap interfaces, `name:port:addr[:proto[:endpoint]]`, comma-separated. Blank
        is the normal case: the node comes up with none and you add them from the panel.

        Interfaces you create in the panel are **not** in your configuration.nix. That is
        deliberate — they are fleet state, like peers, and making you rebuild per interface would be
        a different product — but it means `nixos-rebuild` cannot see them. They live in
        `stateDir`/`confDir` and survive a system rollback.
      '';
    };

    mtu = mkOption { type = types.int; default = 1280; description = "Interface MTU. 1280 leaves headroom for turn-proxy obfuscation."; };
    dns = mkOption { type = types.str; default = "1.1.1.1"; description = "DNS handed to clients."; };

    verifyPanelTls = mkOption {
      type = types.bool; default = true;
      description = "Verify the panel's certificate. Turn off only for a self-signed panel, and pin its fingerprint instead.";
    };
    panelTlsFingerprint = mkOption {
      type = types.str; default = "";
      description = "sha256 of the panel's certificate. Pinning this makes a self-signed panel MITM-resistant.";
    };

    turnManage = mkOption {
      type = types.bool;
      default = false;
      description = ''
        Let the panel install and manage turn proxies on this node. They run as sibling containers,
        so this mounts the container runtime's socket into the node — which is root on this host.
        Off by default for that reason; it is exactly the compose default.

        `delivery = "container"` only. A native node runs on the host already and manages turn
        proxies unconditionally, with no socket involved.
      '';
    };
    turnImage = mkOption {
      type = types.str; default = cfg.image;
      description = "Image each turn-proxy container runs from. Follows `image` unless you say otherwise.";
    };

    seccomp = mkOption {
      type = types.nullOr types.str;
      default = null;
      example = "unconfined";
      description = ''
        Seccomp profile for the node container. Leave null for the runtime's default, which is what
        you want. Set `unconfined` **only** if you run csqtt servers here: csqtt's dataplane is
        io_uring, the default profile denies `io_uring_setup`, and the server dies the instant it
        starts. This relaxes syscall filtering only — capabilities and devices stay limited, which
        is why it is preferred over the `privileged: true` some csqtt recipes reach for.
      '';
    };

    package = mkOption {
      type = types.package;
      default = pkgs.callPackage ../package.nix { };
      defaultText = literalExpression "pkgs.callPackage <swg-panel>/nix/package.nix { }";
      description = ''
        The swg-panel package, for `delivery = "native"`. Resolved against YOUR pkgs, not the ones
        this flake pins, so importing the module never drags our nixpkgs into your closure.
      '';
    };

    restartOnRebuild = mkOption {
      type = types.bool;
      default = false;
      description = ''
        Let `nixos-rebuild switch` restart the node daemon when its unit changes
        (`delivery = "native"`).

        Off by default because a restart re-runs the bootstrap, which brings each managed interface
        `down` and back `up` — every connected client drops until the next reconcile restores the
        runtime peers. The price of leaving it off is that a **new version does not take effect on a
        rebuild**: restart the service when you mean to upgrade.
      '';
    };

    kernelModule = mkOption {
      type = types.bool;
      default = true;
      description = ''
        Install the AmneziaWG **kernel** module for the running kernel (`delivery = "native"` only).
        That is the datapath you came for, and on the channel's default kernel it comes prebuilt from
        cache.nixos.org.

        ⚠️ An out-of-tree module is a hard build dependency of your system closure, so if it does not
        build against your kernel your `nixos-rebuild` **fails outright** rather than degrading. That
        is a real risk only if you pin `boot.kernelPackages` ahead of what Hydra has built. Turn this
        off and you fall back to the userspace datapath, which is always available — `awg-quick`
        tries the kernel device first and uses `amneziawg-go` when that fails, so nothing else has to
        change. The container arm carries none of this exposure at all.
      '';
    };

    udpPortRanges = mkOption {
      type = types.listOf (types.attrsOf types.port);
      default = [ ];
      example = literalExpression "[ { from = 51820; to = 51899; } ]";
      description = ''
        UDP port ranges to open for this node's interfaces, and to tell the panel about.

        This exists because of a collision that is otherwise silent: **interfaces get their ports
        from the panel, at any time, while `networking.firewall` is evaluated at build time.** NixOS
        filters `INPUT` by default, so an interface created from the panel on a stock node syncs,
        reports healthy, shows its peers — and no client can reach it.

        Declaring a range here does two things: it opens those ports, and it tells the node what was
        declared, so the **panel raises a node issue** the moment an interface lands outside it
        instead of leaving you to discover it from a connection that never handshakes. Keep the range
        in step with what you use in the UI, and leave the ports themselves to the panel.

        Left empty, nothing is opened and nothing is reported — manage the firewall yourself, or turn
        it off. `networking.firewall.enable = false` also silences the reporting, because then there
        is nothing to be outside of.
      '';
    };

    selfUpdate = {
      enable = mkOption {
        type = types.bool;
        default = true;
        description = ''
          Wire the panel's **Update** button for this node to a `nixos-rebuild switch` of this
          machine.

          **On by default — so the Update button just works, the same as on every other install.**
          The defaults below assume the standard layout the panel's own config snippet lays down: a
          flake at `/etc/nixos` whose attribute is this host's name, with `swg-panel` as an input.
          Paste that snippet and Update works with no further configuration.

          If your layout differs (a flake elsewhere, a different attribute, a classic non-flake
          config), point `flakeRef`/`updateInputs` at it, or set `enable = false` and the panel falls
          back to showing the command for you to run by hand. This is safe to leave on regardless: a
          `nixos-rebuild switch` is atomic, so a layout mismatch makes the button report a clear
          error and change nothing — it can never half-update or break the running machine.

          On a host that runs both this and `services.swg-panel`, each has its own trigger and its
          own unit; they rebuild the same machine, and the stamp each keeps stops one rebuild from
          immediately provoking the other.
        '';
      };

      flakeRef = mkOption {
        type = types.str;
        default = "/etc/nixos#${config.networking.hostName}";
        defaultText = literalExpression ''"/etc/nixos#''${config.networking.hostName}"'';
        example = "/etc/nixos#myhost";
        description = ''
          What to build, including the attribute. Defaults to this host's flake at `/etc/nixos` —
          the layout the panel's snippet creates. Empty string means a plain `nixos-rebuild switch`
          (whatever this system is configured from). Fixed here rather than taken from the panel: the
          trigger file's contents are ignored, so nothing that crosses the network reaches a root
          rebuild.
        '';
      };

      updateInputs = mkOption {
        type = types.listOf types.str;
        default = [ "swg-panel" ];
        example = [ "swg-panel" ];
        description = ''
          Flake inputs to refresh before rebuilding — defaults to just the one this module came from,
          so pressing Update actually pulls a newer swg-panel and nothing else (nixpkgs and the
          kernel stay pinned). ⚠️ Empty means the rebuild lands on whatever your lock pins — very
          often the version already running, so the update succeeds and changes nothing. Only
          meaningful for a local flake, which is the default `flakeRef`.
        '';
      };
    };

    extraEnvironment = mkOption {
      type = types.attrsOf types.str;
      default = { };
      example = literalExpression ''{ SWG_TURN_MIRROR = "https://ghproxy.example/"; }'';
      description = "Extra environment for the node, merged last. An escape hatch for keys this module does not model yet.";
    };
  };

  config = mkIf cfg.enable (lib.mkMerge [
    {
      # ── D14 tier 2 (T-N7), for BOTH arms ──
      # The node's own trigger and its own unit, deliberately separate from the panel's even on a
      # master: they are two triggers written by two processes, and one `nixos-rebuild` is idempotent
      # anyway. Each keeps its own stamp, so the second trigger's run finds nothing newer and exits.
      systemd.services.swg-node-update = mkIf cfg.selfUpdate.enable {
        description = "swg-node — rebuild this host on the panel's request";
        # A `.path` unit whose service trips systemd's 5-starts-per-10s limit fails PERMANENTLY —
        # the same omission that once broke every Access change on this project (plan V.1).
        unitConfig.StartLimitIntervalSec = 0;
        serviceConfig = {
          Type = "oneshot";
          ExecStart = rebuild.script;
        } // rebuild.resourceGuard;   # nice/idle-IO/OOM-first — a rebuild must never starve its host
      };

      systemd.paths.swg-node-update = mkIf cfg.selfUpdate.enable {
        description = "watch for a swg-node update request";
        wantedBy = [ "paths.target" ];
        pathConfig = {
          PathModified = updateTrigger;
          Unit = "swg-node-update.service";
        };
      };

      # Container arm only, and measured rather than defensive: the daemon writes the trigger through
      # a bind mount, and inotify does not cross one — the `.path` unit above never sees that write.
      # install-docker.sh retires its own `.path` for exactly this reason.
      systemd.timers.swg-node-update = mkIf (cfg.selfUpdate.enable && cfg.delivery == "container") {
        description = "poll for a swg-node update request (the daemon writes it across a bind mount)";
        wantedBy = [ "timers.target" ];
        timerConfig = {
          OnActiveSec = "30s";
          OnUnitActiveSec = "30s";
          Unit = "swg-node-update.service";
        };
      };

      # Not an assertion: an operator who manages the firewall elsewhere is doing something
      # legitimate, and this must not stop their build. But the failure it warns about is silent and
      # looks like success, so it must not be silent here either.
      # A co-located node dialing the panel's loopback endpoint over HTTPS. That endpoint is plain
      # HTTP by construction — the panel adds it with no cert at all — so this is not a strictness
      # preference, it is a connection that cannot succeed. A warning rather than an assertion
      # because the URL is a free-form string and somebody may legitimately front loopback.
      warnings = lib.optional (lib.hasPrefix "https://127.0.0.1" cfg.panelUrl || lib.hasPrefix "https://localhost" cfg.panelUrl) ''
        services.swg-node.panelUrl is ${cfg.panelUrl}, but the panel's dedicated loopback endpoint
        for a co-located node serves PLAIN HTTP — it is added with no certificate. Use
        http://127.0.0.1:<services.swg-panel.localPort> and verifyPanelTls = false.
      '' ++ lib.optional (config.networking.firewall.enable && cfg.udpPortRanges == [ ]) ''
        services.swg-node: networking.firewall is enabled and services.swg-node.udpPortRanges is
        empty. Interfaces you create from the panel get their ports at runtime, and the firewall is
        evaluated at build time, so such an interface will sync, report healthy, show its peers —
        and be unreachable from the internet. Declare the range you intend to use
        (e.g. udpPortRanges = [ { from = 51820; to = 51899; } ];), open the ports another way, or
        set networking.firewall.enable = false.
      '';

      assertions = [
        {
          # Exactly one source for the token. Neither is a silent default: with neither set the
          # bootstrap exits on `NODE_TOKEN required` at every start, which is a crash loop the
          # operator has to read a journal to explain. With both, which one wins is an implementation
          # detail of a shell script — not something a configuration should have to know.
          assertion = (cfg.environmentFile != null) != (cfg.tokenFile != null);
          message = ''
            services.swg-node needs exactly one of environmentFile or tokenFile.

              tokenFile       = "/run/secrets/swg-node-token";   # the token alone, via LoadCredential
              environmentFile = "/run/secrets/swg-node.env";     # a file defining NODE_TOKEN=…

            Prefer tokenFile on delivery = "native": an EnvironmentFile token stays in the daemon's
            environment for its whole life and is inherited by every subprocess it spawns.
          '';
        }
        {
          # LoadCredential mounts into the UNIT's mount namespace. A container the unit starts has
          # its own, so the credentials directory is simply not there — this is not a limitation
          # worth working around with a bind mount, it is the boundary doing its job.
          assertion = cfg.tokenFile == null || cfg.delivery == "native";
          message = ''
            services.swg-node.tokenFile works only with delivery = "native". systemd's
            LoadCredential mounts the token into the unit's own namespace, which a container started
            by that unit does not share. Use environmentFile on the container arm.
          '';
        }
        {
          # Same rule as the panel module's, for the same reason: naming inputs against a remote ref
          # is a build-time mistake whose only symptom at runtime is an update that succeeds and
          # changes nothing.
          assertion = cfg.selfUpdate.updateInputs == [ ] || rebuild.localFlake;
          message = ''
            services.swg-node.selfUpdate.updateInputs names inputs to refresh, but flakeRef
            (${cfg.selfUpdate.flakeRef}) is not a local path — there is no lock on this machine to
            update. Point flakeRef at the flake on this host, or clear updateInputs.
          '';
        }
        {
          # The native arm deliberately shares bare-metal's paths — that is what makes moving an
          # existing bare-metal node onto NixOS move NO data at all. The bootstrap script hardcodes
          # them, so honouring a custom path here would silently write somewhere the daemon never
          # reads.
          assertion = cfg.delivery != "native"
                      || (cfg.stateDir == "/var/lib/swg-noded" && cfg.confDir == "/etc/amnezia/amneziawg");
          message = ''
            services.swg-node.delivery = "native" keeps bare-metal's paths on purpose:
            stateDir = "/var/lib/swg-noded" and confDir = "/etc/amnezia/amneziawg". An existing
            bare-metal node then moves onto NixOS with nothing to copy — no keys, no confs, no
            re-enrolment. Use delivery = "container" if you need these somewhere else.
          '';
        }
        {
          # firezone's module warns about this in prose; there is no reason it cannot be checked.
          #
          # `builtins.isPath` is the load-bearing half, and the reason is subtle enough that the
          # first version of this assertion did not fire at all: `toString ./secret` yields the
          # SOURCE path, so a store-prefix test sees nothing wrong. The copy happens later, when the
          # unit generator interpolates the value into a string — by which time the file is in the
          # store and there is no option left to check. So catch the path LITERAL itself. A string
          # (what sops-nix and agenix hand you) is never copied.
          assertion = builtins.all (f: !(builtins.isPath f) && !(lib.hasPrefix builtins.storeDir (toString f)))
                        (lib.filter (f: f != null) [ cfg.environmentFile cfg.tokenFile ]);
          message = ''
            services.swg-node.environmentFile or .tokenFile points into the Nix store
            (${toString (if cfg.tokenFile != null then cfg.tokenFile else cfg.environmentFile)}). The store is world-readable, so the enrolment token
            in that file would be readable by every user on this machine — which is exactly what
            passing a file instead of the token was meant to prevent.

            This happens when the value is written as a Nix PATH LITERAL rather than a string:
              environmentFile = /run/secrets/swg-node.env;     # copied into the store
              environmentFile = "/run/secrets/swg-node.env";   # read at runtime, correct
          '';
        }
        {
          assertion = !(cfg.turnManage && cfg.backend == "podman" && !config.virtualisation.podman.dockerCompat);
          message = ''
            services.swg-node.turnManage needs a docker-compatible CLI and socket: the daemon
            shells out to `docker` to run each turn proxy as a sibling container, and reaches the
            host through a `--privileged --pid=host` helper. On podman set
            virtualisation.podman.dockerCompat = true and enable a rootful podman socket, or use
            backend = "docker".
          '';
        }
      ];
    }

    (mkIf (cfg.udpPortRanges != [ ]) {
      networking.firewall.allowedUDPPortRanges = cfg.udpPortRanges;
    })

    (mkIf (cfg.delivery == "container") {
      virtualisation.oci-containers.backend = cfg.backend;

      # The installer enables the docker service explicitly, on the grounds that the panel must
      # survive a reboot. The same applies here, and oci-containers does not do it for us.
      virtualisation.docker.enable = mkIf (cfg.backend == "docker") true;
      virtualisation.podman = mkIf (cfg.backend == "podman") {
        enable = true;
        # A bare podman refuses EVERY pull without /etc/containers/policy.json, which this supplies.
        # Measured on a NixOS 26.05 VM, where it looked exactly like a broken registry.
        defaultNetwork.settings.dns_enabled = lib.mkDefault true;
      };
      virtualisation.containers.enable = mkIf (cfg.backend == "podman") true;

      # ⚠️ The compose `sysctls:` block does NOT apply under host networking — the container shares
      # the host's network namespace, so these have to be set on the host. Without route_localnet
      # Force-DNS silently blackholes: it DNATs a client's :53 to a loopback dnsmasq, and the kernel
      # drops that. Measured on a fresh NixOS VM: both come up 0.
      boot.kernel.sysctl = {
        "net.ipv4.ip_forward" = lib.mkDefault true;
        "net.ipv4.conf.all.route_localnet" = lib.mkDefault true;
      };

      systemd.tmpfiles.rules = [
        "d ${cfg.stateDir} 0700 root root -"
        "d ${cfg.confDir} 0700 root root -"
        # Host UAPI sockets for userspace wireguard-go. Without this the wg CLI inside the container
        # cannot see a FOREIGN userspace interface — a WDTT server's, say — so the adoption scan
        # lists every kernel wg/awg device and silently omits the one thing it exists for.
        "d /run/wireguard 0755 root root -"
        # The bare-metal fork roots, mounted read-only above. Created here because a bind mount of a path
        # that does not exist is the runtime's problem to invent, not ours to discover at first boot — and
        # on a host that has never run the native arm they are simply empty.
        "d /opt/swg-wdtt 0700 root root -"
        "d /opt/swg-csqtt 0700 root root -"
      ] ++ lib.optional cfg.selfUpdate.enable "f ${updateTrigger} 0600 root root -";

      # The CONTAINER reads the environment file, so it is the container's unit that must wait for
      # whatever produces it. (On the panel's container arm the equivalent ordering sits on the seed
      # oneshot instead — that arm's container never reads the secret at all.)
      systemd.services."${cfg.backend}-swg-node" = mkIf (cfg.secretsDependencies != [ ]) {
        after = cfg.secretsDependencies;
        wants = cfg.secretsDependencies;
      };

      # A turn proxy is a SIBLING container the panel creates at RUNTIME, so it has no unit of its
      # own and nothing stops it when the node goes away: `services.swg-node.enable = false` plus a
      # rebuild leaves every turn proxy running and still bound to its public UDP port, on a box the
      # operator considers decommissioned. Measured — after the node was removed, `turn-server` was
      # still listening on the box's public address with no unit behind it. Every other run model
      # reaps them (uninstall.sh does it explicitly); NixOS has no uninstaller, so the module must.
      #
      # Deliberately NOT an ExecStopPost on the node's own unit: that fires on every restart too, and
      # a restart is not a removal — on a kernel-datapath host the interfaces survive it, so the
      # proxies would drop live traffic for nothing. A separate unit whose definition never changes
      # is only ever stopped when it LEAVES the configuration, which is exactly the question being
      # asked; a rebuild that merely changes the node's image leaves this one untouched.
      systemd.services.swg-node-turn-reap = mkIf cfg.turnManage {
        description = "Reap swg-node's turn-proxy containers when the node leaves the configuration";
        wantedBy = [ "multi-user.target" ];
        serviceConfig = { Type = "oneshot"; RemainAfterExit = true; };
        script = "true";     # nothing to do on the way IN; the node creates its own proxies
        preStop = ''
          # Shutdown stops this unit as well, and there it would mean the opposite: the proxies are
          # created `--restart unless-stopped`, so on docker the daemon brings them back at boot.
          [ "$(${pkgs.systemd}/bin/systemctl is-system-running 2>/dev/null)" = stopping ] && exit 0

          # WAIT for the node, rather than being ORDERED after it. Both spellings of the ordering
          # were tried on the lab box and both raced: switch-to-configuration reloads systemd before
          # it stops obsolete units, and a reload drops the dependencies of a unit whose file has
          # just disappeared — so the two stop jobs ran concurrently. Measured: reap at 08:20:31,
          # node re-creates both proxies at 08:20:36, node finally stops at 08:20:41, proxies left
          # running. Waiting needs no dependency to survive, and it doubles as the guard for the
          # case where the node is NOT going away: then it never goes quiet, and leaving its proxies
          # alone is the right answer.
          #
          # The unit's state, not `${cfg.backend} ps`: a container disappears from `ps` as soon as
          # stop is ISSUED, while the daemon inside it is still running and still reconciling. That
          # read the node as gone 6s early and reaped into a live daemon, which promptly re-created
          # everything. `deactivating` is the state that matters and only systemd reports it.
          gone=0
          for _ in $(${pkgs.coreutils}/bin/seq 1 60); do
            st=$(${pkgs.systemd}/bin/systemctl is-active ${cfg.backend}-swg-node.service 2>/dev/null || true)
            case "$st" in
              active|activating|deactivating|reloading) ;;
              *) gone=1; break ;;
            esac
            ${pkgs.coreutils}/bin/sleep 1
          done
          [ "$gone" = 1 ] || exit 0

          ids=$(${pkgs.${cfg.backend}}/bin/${cfg.backend} ps -aq --filter name=swg-turn- 2>/dev/null || true)
          [ -n "$ids" ] && ${pkgs.${cfg.backend}}/bin/${cfg.backend} rm -f $ids >/dev/null 2>&1 || true
          exit 0
        '';
      };

      virtualisation.oci-containers.containers.swg-node = {
        inherit (cfg) image;
        environment = env // turnEnv // lib.optionalAttrs cfg.selfUpdate.enable {
          # The path INSIDE the container; cfg.stateDir is mounted at /var/lib/swg-noded, and the
          # host unit watches the same inode from the other end of that bind mount.
          SWG_UPDATE_TRIGGER = "/var/lib/swg-noded/.update-request";
        };
        # Stays on this arm: a container cannot see a host credential (see tokenFile's assertion).
        environmentFiles = lib.optional (cfg.environmentFile != null) cfg.environmentFile;
        volumes = [
          "${cfg.stateDir}:/var/lib/swg-noded"
          "${cfg.confDir}:/etc/amnezia/amneziawg"
          "/run/wireguard:/run/wireguard"
          # READ-ONLY, and only so a switch can carry state FORWARD. A bare-metal node keeps each WDTT /
          # csqtt instance's directory — its identity, its owner password, its user store — under /opt; a
          # container keeps them in the state dir. Without these the container cannot even SEE what the
          # previous run-model left on the same box, so it treats live servers as absent: WDTT holds for an
          # escrow unlock (the escrow working, but an unlock the operator should not have needed) and csqtt
          # comes back with a new owner password. The daemon only ever COPIES out of them.
          "/opt/swg-wdtt:/opt/swg-wdtt:ro"
          "/opt/swg-csqtt:/opt/swg-csqtt:ro"
        ] ++ optional cfg.turnManage
          (if cfg.backend == "podman"
           then "/run/podman/podman.sock:/var/run/docker.sock"
           else "/var/run/docker.sock:/var/run/docker.sock");
        extraOptions = [
          # Host netns: every interface port is on the host, including the ones the panel picks
          # later, so nothing has to be published and re-published.
          "--network=host"
          "--cap-add=NET_ADMIN"
          # ⚠️ NOT redundant, and podman-only in effect. `iptables -m set --match-set` opens its ipset
          # session on a SOCK_RAW netlink socket, which needs CAP_NET_RAW — docker's default capability
          # set carries it, podman's does not. Measured on a NixOS host with the shipped image, bisected
          # capability by capability: NET_ADMIN alone gives "Can't open socket to ipset" on every rule,
          # NET_ADMIN + NET_RAW works, and SYS_MODULE / SYS_ADMIN / DAC_READ_SEARCH do not help. The
          # `ipset` binary itself works either way, which is what makes it look like a set problem
          # rather than a capability one. Without this the node's signature rules fail on EVERY
          # reconcile and report the failure to the panel for ever. Harmless where it is already default.
          "--cap-add=NET_RAW"
          "--device=/dev/net/tun:/dev/net/tun"
        ] ++ optional (cfg.seccomp != null) "--security-opt=seccomp=${cfg.seccomp}";
      };
    })

    (mkIf (cfg.delivery == "native") {
      # The kernel datapath. Prebuilt from cache.nixos.org for the channel's default kernel — the
      # whole install took 83s on a fresh VM, far too fast to have compiled it. See the option's
      # description for the one case where this is a real risk.
      boot.extraModulePackages = mkIf cfg.kernelModule [ config.boot.kernelPackages.amneziawg ];
      boot.kernelModules = mkIf cfg.kernelModule [ "amneziawg" ];

      # Tell the operator to reboot — but ONLY when it is actually needed. The module is wired into
      # this configuration, yet an out-of-tree module cannot enter a kernel that is already running:
      # after the FIRST `nixos-rebuild` that adds it (or a kernel bump), it lives in the new
      # generation but not in the booted one, so `awg-quick` runs on the userspace amneziawg-go
      # fallback until a reboot. The datapath works meanwhile — this is a throughput note, not an
      # outage — so the message must not nag.
      #
      # The condition is a RUNTIME fact, not an eval-time one: whether the module is in the *booted*
      # kernel. So it lives in an activation script (its echo lands in `nixos-rebuild switch` output —
      # the Nix equivalent of an installer's summary) rather than in `warnings`, and it asks the
      # kernel directly. `modinfo` on NixOS searches the booted system's module tree, so it fails
      # exactly when a reboot is pending and succeeds once you have rebooted into this config — which
      # is why a re-install or a no-op switch after the reboot prints nothing. Gated on kernelModule:
      # with the userspace datapath chosen (kernelModule = false) there is nothing to reboot for.
      system.activationScripts.swgAwgKernelRebootHint = lib.mkIf cfg.kernelModule ''
        if ! ${pkgs.kmod}/bin/modinfo amneziawg > /dev/null 2>&1; then
          echo ""
          echo "swg-node: the AmneziaWG KERNEL module is installed in this configuration but is not yet"
          echo "          in the running kernel. REBOOT to use the kernel datapath — until then the node"
          echo "          runs on the userspace amneziawg-go fallback (fully working, lower throughput)."
          echo "          (Set services.swg-node.kernelModule = false to stay on userspace and silence this.)"
          echo ""
        fi
      '';

      # Same two as the container arm, and for the same measured reason: a fresh NixOS host comes up
      # with both at 0, and without route_localnet Force-DNS silently blackholes.
      # ⚠️ rp_filter is deliberately NOT set here, though an earlier draft of the plan listed it.
      # The full client→node→internet datapath was measured working on a stock NixOS VM with the
      # defaults, and changing a kernel knob nothing has been shown to need is how a module acquires
      # settings nobody can later justify. `networking.firewall.checkReversePath` is the one to look
      # at if asymmetric routing ever does bite; it is the operator's to set.
      boot.kernel.sysctl = {
        "net.ipv4.ip_forward" = lib.mkDefault true;
        "net.ipv4.conf.all.route_localnet" = lib.mkDefault true;
      };

      # awg-quick@.service ships with amneziawg-tools, but a store path's lib/systemd/system is NOT
      # in systemd's search path, so without this the template unit simply does not exist.
      systemd.packages = [ pkgs.amneziawg-tools ];

      systemd.tmpfiles.rules = [
        "d ${cfg.stateDir} 0700 root root -"
        "d ${cfg.confDir} 0700 root root -"
        "d /etc/swg-agent 0700 root root -"
        "d /run/wireguard 0755 root root -"
      ] ++ lib.optional cfg.selfUpdate.enable "f ${updateTrigger} 0600 root root -";

      # The native arm's version of the same hole the container arm's reaper closes: here a turn
      # proxy is an imperatively written `vk-turn-proxy-*.service`, so it is not part of any
      # generation and `switch-to-configuration` never touches it. Removing the node would leave it
      # running and bound to its public port. Same `before`-not-`after` reasoning as the other arm.
      #
      # `disable --now`, NOT a delete: on bare metal the unit FILES are the source of truth for which
      # proxies exist (swg-noded reconciles the panel's list from what is on disk), so removing them
      # would make a re-enable come back with the proxies silently forgotten. Stopping them and
      # dropping the wanted-by symlink leaves the record intact and the ports released. On NixOS the
      # units usually live in /run — where they would not have survived a reboot anyway — and there
      # `disable` is simply a no-op that `stop` does the real work behind.
      systemd.services.swg-node-turn-reap = {
        description = "Stop this node's turn proxies when the node leaves the configuration";
        wantedBy = [ "multi-user.target" ];
        serviceConfig = { Type = "oneshot"; RemainAfterExit = true; };
        script = "true";
        preStop = ''
          [ "$(${pkgs.systemd}/bin/systemctl is-system-running 2>/dev/null)" = stopping ] && exit 0

          # Same wait-do-not-order reasoning as the container arm above, including why the test is
          # for a FULLY stopped unit: `deactivating` still means a daemon that can put them back.
          gone=0
          for _ in $(${pkgs.coreutils}/bin/seq 1 60); do
            st=$(${pkgs.systemd}/bin/systemctl is-active swg-noded.service 2>/dev/null || true)
            case "$st" in
              active|activating|deactivating|reloading) ;;
              *) gone=1; break ;;
            esac
            ${pkgs.coreutils}/bin/sleep 1
          done
          [ "$gone" = 1 ] || exit 0

          for u in $(${pkgs.systemd}/bin/systemctl list-units --all --no-legend 'vk-turn-proxy-*.service' \
                     2>/dev/null | ${pkgs.gawk}/bin/awk '{print $1}'); do
            ${pkgs.systemd}/bin/systemctl disable --now "$u" >/dev/null 2>&1 || true
          done
          exit 0
        '';
      };

      systemd.services.swg-noded = {
        description = "swg-noded — outbound HTTPS sync to the swg panel";
        wantedBy = [ "multi-user.target" ];

        # ⚠️ Off by default, and the reason is measured, not stylistic: this unit's ExecStart is the
        # bootstrap, and for every managed interface the bootstrap does `awg-quick down` then `up`.
        # A restart therefore tears each interface down and rebuilds it from its .conf, so every
        # connected client drops until the next reconcile puts the runtime peers back. Peers,
        # routing and interfaces are runtime state — that is the product — and a `nixos-rebuild`
        # that touched an unrelated dependency should not cost the fleet a reconnect.
        #
        # The cost of that choice, stated plainly rather than left to be discovered: a new version
        # does NOT take effect on `nixos-rebuild switch`. Restart it when you mean to
        # (`systemctl restart swg-noded`), or set restartOnRebuild = true and accept the bounce.
        restartIfChanged = cfg.restartOnRebuild;

        # ⚠️ python3 is not optional and its absence is SILENT. The bootstrap computes each
        # interface's subnet with `python3 -c "import ipaddress…"`, so without it the interfaces come
        # up, look healthy, get NO MASQUERADE, and the daemon never starts — a node serving clients
        # with no internet. Measured, twice. (Our own programs carry a store interpreter in their
        # shebang; this is for the shell script that starts them.)
        path = with pkgs; [
          python3
          nftables iptables ipset iproute2 dnsmasq
          wireguard-tools amneziawg-tools
          # The userspace datapath, always present as the fallback: awg-quick tries the kernel
          # device FIRST and only reaches for this when that fails, so shipping it costs a kernel
          # node nothing and saves a host whose module lags its kernel. (Measured: with
          # WG_QUICK_USERSPACE_IMPLEMENTATION set, awg-quick still made a kernel device.)
          amneziawg-go
          # gawk was missing from the first version of this list, and the cost was exactly the
          # failure the note above describes: the bootstrap reads each interface's Address with
          # `awk`, so without it every interface came up, looked healthy, and got NO MASQUERADE —
          # a node serving clients with no internet. Measured on the VM. The list is now checked
          # mechanically by .campaign/nix-path-audit.mjs rather than remembered.
          gawk
          # ⚠️ `sh` itself, and it is load-bearing in a way no other entry here is. NixOS sets a
          # unit's PATH to EXACTLY these packages plus the five its `apply` appends (coreutils,
          # findutils, gnugrep, gnused, systemd) — no shell among them — and `host_sh`, the daemon's
          # 59-site helper for everything host-side, runs `sh -c`.
          #
          # MEASURED on the VM, on a node carrying a WDTT instance: without this entry, 27 host_sh
          # calls in one 45-second run returned rc=127, "No such file or directory: 'sh'". A node
          # with no turn/WDTT/csqtt never calls host_sh and looks perfect, which is why this survived
          # T-N8 and T-N1 — both probed nodes that had none.
          # BY INSPECTION, and worth knowing because it is the quiet part: T-N1's read-only unit-dir
          # probe is itself a host_sh call, and its no-marker branch keeps /etc/systemd/system and
          # says "assuming it is writable" — on a host where it is not. That branch is lazy (it runs
          # when a unit PATH is first computed), so neither probe run reached it.
          bash
          procps conntrack-tools curl gnutar openssl kmod gnused gnugrep coreutils
        ];

        # ⚠️ `wants` as well as `after`: ordering alone does not PULL the secrets unit in, and being
        # ordered after a unit nothing started is being ordered after nothing.
        after = [ "network-online.target" ] ++ cfg.secretsDependencies;
        wants = [ "network-online.target" ] ++ cfg.secretsDependencies;

        environment = env // {
          # D15: the bootstrap is shared verbatim with the container arm, and these two overrides are
          # the whole difference — the programs live in the store here, not in /opt.
          SWG_NODED_BIN = "${cfg.package}/libexec/swg-noded/swg-noded";
          SWG_AGENT_BIN = "${cfg.package}/libexec/swg-agent/swg-agent";
        } // lib.optionalAttrs cfg.selfUpdate.enable {
          # ⚠️ Set ONLY with selfUpdate.enable. Without a unit watching it, writing the trigger is a
          # button that reports success and changes nothing; the daemon's honest refusal is better.
          SWG_UPDATE_TRIGGER = updateTrigger;
        };

        serviceConfig = {
          Type = "simple";
          # The bootstrap, not the daemon: it generates config.json, brings up every persisted
          # interface, sets up NAT — and then `exec`s the daemon, so systemd tracks the same pid.
          # ExecStartPre cannot be used for it precisely BECAUSE of that exec: the pre-step would
          # become the daemon and never return.
          #
          # This is also what closes the boot gap the probed unit directory opens. Where
          # `systemctl enable` cannot work, nothing else would bring interfaces up after a reboot,
          # and the panel being unreachable at boot must never mean an entry server serves nobody.
          ExecStart = "${cfg.package}/libexec/swg-node/node-entrypoint.sh";
          Restart = "on-failure";
          RestartSec = 3;

          # The shape the installer actually generates — not the stale reference copy in systemd/.
          # Root, because it samples kernel interfaces and runs swg-agent, which writes interface
          # .confs under /etc. ProtectSystem=true and NOT strict for exactly that reason: strict
          # would make /etc read-only and peers would stop persisting.
          NoNewPrivileges = true;
          ProtectSystem = true;
        } // lib.optionalAttrs (cfg.tokenFile != null) {
          # The token lands in a per-unit tmpfs the bootstrap reads once through
          # $CREDENTIALS_DIRECTORY, instead of an environment variable the daemon and every
          # subprocess it spawns then carry for the life of the process (T-P5).
          LoadCredential = [ "token:${cfg.tokenFile}" ];
        } // lib.optionalAttrs (cfg.environmentFile != null) {
          EnvironmentFile = cfg.environmentFile;
          ProtectHome = true;
          PrivateTmp = true;
          # ⚠️ Mandatory. User-namespace isolation breaks netlink route operations, which is most of
          # what this daemon does.
          PrivateUsers = false;
          # ⚠️ Do NOT add AmbientCapabilities = [ "CAP_NET_ADMIN" ]. It presumes a non-root service;
          # here it is at best a no-op and at worst reads as a promise that the daemon is
          # unprivileged, which it is not and cannot be — netlink, nft, conf writes, swg-agent.
        };
      };
    })
  ]);
}
