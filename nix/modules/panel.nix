# services.swg-panel — the control plane, declared.
#
# Two delivery methods, as for the node (docs/NIXOS-SUPPORT-PLAN.md D13):
#   container  the images we publish, driven by virtualisation.oci-containers — panel + swg-sub
#   native     swg-panel-server from the Nix store, as its own unit and its own user
#
# ── TLS is subtracted here, not ported (D7) ──
# The panel image bundles acme.sh and the bare-metal installer drives it. Neither runs on this
# module: TLS=none, plain HTTP on loopback, and `security.acme` + your reverse proxy own
# certificates. acme.sh is irreconcilable with a store install on three counts — it copies itself
# to ~/.acme.sh, it self-upgrades in place, and it installs its own crontab, which on a host with
# no cron simply never runs. Of seven nixpkgs web-service modules surveyed, zero do their own ACME.
#
# `useACMEHost` is the way back to direct TLS when you want it: the panel reads the cert
# `security.acme` already manages, joins its group, and is reloaded on renewal — which is what
# replaces the bare-metal panel's self-restart-on-cert-change.
#
# ⚠️ This file re-declares, in Nix, the contract docker-compose.yml defines. Nothing in the
# language keeps the two in step, so `.campaign/compose-nix-contract.mjs` does.
{ config, lib, pkgs, ... }:

let
  cfg = config.services.swg-panel;
  inherit (lib) mkOption mkEnableOption mkIf types literalExpression optional optionalString;

  # ⚠️ `useACME` is derived from OUR OWN option and nothing else, and that is load-bearing.
  # The first version gated the definitions below on `acme != null`, where
  # `acme = config.security.acme.certs.<host>` — so the CONDITION for defining
  # `security.acme.certs` read `security.acme.certs`. That is an infinite recursion, and it does
  # not announce itself as one: the trace names logrotate, `users.groups` and the acme module, and
  # mentions this file only as "definitions from". Read the certificate's attributes in VALUES, as
  # `certDir` does below; never in a condition that guards a definition of the same option.
  useACME = cfg.useACMEHost != null;
  certDir = if useACME then config.security.acme.certs.${cfg.useACMEHost}.directory else null;

  stateDir = cfg.stateDir;
  etcDir = cfg.configDir;

  # Read at startup and never written — genuine configuration, so the module owns it and rewrites
  # it on every start. (`users.json`, `nodes.json` and the auth file, which the panel DOES write,
  # are state and are only ever seeded.)
  fleetJson = builtins.toJSON {
    roster_path = "${stateDir}/users.json";
    nodes_path = "${stateDir}/nodes.json";
    stats_dir = cfg.statsDir;
    store_configs = cfg.storeConfigs;
    config_dir = "${stateDir}/configs";
    node_interval = cfg.nodeInterval;
  };

  # A store COPY, not a symlink: /etc/swg-panel has to stay a plain writable directory, because the
  # panel rewrites its auth file there.
  fleetFile = pkgs.writeText "swg-panel-fleet.json" fleetJson;

  # The same hash the panel image's entrypoint and the bare-metal installer produce.
  seedAuthPy = pkgs.writeText "swg-panel-seed-auth.py" ''
    import sys, os, hashlib, base64
    u, pw = sys.argv[1], os.environ["PANEL_PASSWORD"]
    salt = os.urandom(16); it = 200000
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, it)
    sys.stdout.write("%s:pbkdf2_sha256$%d$%s$%s\n"
                     % (u, it, base64.b64encode(salt).decode(), base64.b64encode(h).decode()))
  '';

  # ── the login, seeded ON THE HOST, on BOTH arms (T-P5) ────────────────────────────────────────
  # The container arm used to hand the whole environment file to the container, which put the initial
  # admin password in that container's environment for its entire life — readable by anything that can
  # inspect it, forever, for a value that is needed exactly ONCE. The image entrypoint's own rule is
  # "a mounted (non-empty) auth file wins", so seeding it from here means the password never crosses
  # into the container at all, and the two arms stop having two implementations of one hash.
  #
  # Ownership is the only thing that differs: native, the panel is `swgpanel` and reads through group
  # `swg`; container, it is root in its own namespace and there is no `swg` group on the host to
  # name.
  authSeed = owner: pkgs.writeShellScript "swg-panel-seed-auth" ''
    set -eu
    umask 027
    install -d -m 2775 ${etcDir}

    # The login is STATE. Seed it only when there is none: the panel owns this file afterwards and
    # rewrites it when the operator changes their password, so re-asserting it here would silently
    # undo that at the next boot.
    #
    # `-s`, not `-f`: an EMPTY file is not a login. That distinction is not hypothetical — on the
    # container arm, mounting /dev/null over this path in the sub creates an empty one, and the
    # panel image's entrypoint tests the same way for the same reason. Seeding from the host closes
    # that race outright: this runs before either container, so the file is never empty when they look.
    if [ ! -s ${etcDir}/auth ]; then
      if [ -r ${cfg.environmentFile} ]; then
        set -a; . ${cfg.environmentFile}; set +a
      fi
      if [ -n "''${PANEL_PASSWORD:-}" ]; then
        ${pkgs.python3}/bin/python3 ${seedAuthPy} ${lib.escapeShellArg cfg.user} > ${etcDir}/auth.tmp
        chown ${owner} ${etcDir}/auth.tmp
        chmod 0640 ${etcDir}/auth.tmp
        mv -f ${etcDir}/auth.tmp ${etcDir}/auth
        echo "swg-panel: seeded the initial login for ${cfg.user}"
      else
        echo "swg-panel: this panel has no login and PANEL_PASSWORD is not defined in ${toString cfg.environmentFile} — every sign-in will be refused" >&2
      fi
    fi
  '';

  seedScript = pkgs.writeShellScript "swg-panel-seed" ''
    set -eu
    umask 027

    # Configuration the panel only ever READS, rewritten from the module on every start.
    install -m 0640 -o root -g swg ${fleetFile} ${etcDir}/fleet.json

    # …and the address it ADVERTISES, which on this arm the Access screen can no longer supply.
    # Same script the container arm runs, so the two arms cannot drift apart.
    ${accessSeed}
    # The seed runs as root (it has to: the state dir is swgpanel's and this script also writes into
    # root's /etc/swg-panel). The panel REWRITES both of these when the operator changes an unrelated
    # setting, so hand them back — `cfg.user` is the admin LOGIN name, not the system account.
    chown swgpanel:swg ${stateDir}/panel-settings.json ${stateDir}/panel-confirmed.json 2>/dev/null || true

    ${authSeed "root:swg"}
    ${optionalString cfg.localNode.enable (localNodeSeed "swgpanel:swg")}
  '';

  # ── the address this panel ADVERTISES ────────────────────────────────────────────────────────
  # It is not cosmetic. Subscription links are built from it, and it is what an operator copies out
  # of the panel. On every other install an installer seeds it and Settings → Access edits it —
  # neither happens here: the Access screen is refused on a declarative host (T-N10), so if the
  # module does not supply this the panel advertises nothing and subscriptions cannot be issued at
  # all. Measured, not assumed: a Nix panel before this seeded `access.panel.url = ""`.
  #
  # The port belongs in the URL only when this panel is the thing the public reaches — with
  # `useACMEHost` it terminates TLS itself on `cfg.port`. Behind a reverse proxy the public port is
  # the PROXY's and unknowable here, so the URL carries none and the proxy maps it.
  publicUrl =
    if cfg.publicUrl != "" then cfg.publicUrl
    else "https://${cfg.domain}"
         + optionalString (useACME && cfg.port != 443) ":${toString cfg.port}"
         + cfg.basePath;

  # The subscription surface's public address. Deliberately EMPTY unless it is published somewhere
  # distinguishable from the panel — a bare `https://<panel domain>` would be the panel's own URL,
  # and subscription links pointing at the panel are worse than links that visibly do not exist.
  subDomain = if cfg.sub.domain != "" then cfg.sub.domain else cfg.domain;
  subPublicUrl =
    if cfg.sub.publicUrl != "" then cfg.sub.publicUrl
    else if cfg.sub.domain != "" || cfg.sub.basePath != "" then "https://${subDomain}${cfg.sub.basePath}"
    else "";

  # Where the subscription surface is REACHED on this host — the address an operator copies off the
  # Access screen into an nginx or Caddy vhost. It is whatever the port is actually PUBLISHED on, which
  # on the container arm is `sub.host` (the container binds 0.0.0.0 in its own namespace and the publish
  # decides reachability), and on the native arm is the bind itself. This used to be hardcoded to
  # loopback on the container arm, from when the publish was hardcoded too; the publish now honours
  # `sub.host` exactly as the panel's does, so an operator who widens it was being shown an address the
  # surface is no longer on — the same contradiction the panel's own publish comment describes.
  subBindHost = cfg.sub.host;

  # "" = a reverse proxy in front (no certificate is ours); "skip" = TLS is terminated here but the
  # certificate is security.acme's, not this panel's to issue, renew or reason about. Both read as
  # "not our TLS" everywhere the panel branches on the mode, which is the point — it is what keeps
  # the certificate-expiry watch, the sub-certificate alarm and the boot TLS-mode inference quiet
  # about a certificate they do not own.
  tlsMode = if useACME then "skip" else "";

  # Shared by both arms, so there is one shape and no drift. MERGE, never rewrite: panel-settings.json
  # is the panel's own state and holds far more than this. Re-asserted on every start, because on a
  # declarative host the configuration is the source of truth and nothing else can change these.
  accessSeedPy = pkgs.writeText "swg-panel-seed-access.py" ''
    import json, os, sys

    settings, blessed = sys.argv[1], sys.argv[2]
    url, sub_url, mode, host, port, base, sub_host, sub_port = sys.argv[3:11]

    try:
        with open(settings) as f:
            d = json.load(f)
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}

    acc = d.setdefault("access", {})
    pan = acc.setdefault("panel", {})
    sub = acc.setdefault("sub", {})
    tls = acc.setdefault("tls", {})
    pan["url"] = url
    pan["host"] = host
    pan["port"] = int(port)
    pan["base"] = base or "/"
    tls["mode"] = mode
    # An empty sub URL means "not published anywhere yet". Do not overwrite one an adopted install
    # already carried with a blank (T-M1 moves an existing panel onto this module state and all).
    if sub_url:
        sub["url"] = sub_url
    # The address a TLS terminator in front of the subscription page must actually dial. The panel
    # cannot see it — swg-sub's bind is swg-sub's own environment — so before this it showed the
    # unseeded default (0.0.0.0:8444) beside a surface that is on loopback, which is the one number
    # an operator writing an nginx or Caddy vhost copies out of this screen.
    sub["host"] = sub_host
    sub["port"] = int(sub_port)

    def write(path, doc):
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(doc, f, indent=2)
        os.replace(tmp, path)

    write(settings, d)
    # The BLESSED baseline too, or the panel's boot reconcile rolls the URL back to the one confirmed
    # before the rebuild — a domain change in configuration.nix would silently not take effect. On
    # every other install this file only ever advances through a browser confirm; here the rebuild IS
    # the confirmation, and there is no way to perform the browser one.
    write(blessed, {"url": url, "mode": mode})
  '';

  accessSeed = pkgs.writeShellScript "swg-panel-seed-access" ''
    set -eu
    umask 027
    ${pkgs.python3}/bin/python3 ${accessSeedPy} \
      ${lib.escapeShellArg "${stateDir}/panel-settings.json"} \
      ${lib.escapeShellArg "${stateDir}/panel-confirmed.json"} \
      ${lib.escapeShellArg publicUrl} \
      ${lib.escapeShellArg subPublicUrl} \
      ${lib.escapeShellArg tlsMode} \
      ${lib.escapeShellArg cfg.host} \
      ${lib.escapeShellArg (toString cfg.port)} \
      ${lib.escapeShellArg cfg.basePath} \
      ${lib.escapeShellArg subBindHost} \
      ${lib.escapeShellArg (toString cfg.sub.port)}
  '';

  # ── the master role: a co-located node, enrolled without a round trip (T-N12) ────────────────
  # ⚠️ This writer is PORTED, not re-derived, from install-docker.sh's single-pass master. Two of its
  # rules are non-obvious and both are locking bugs:
  #   · find the existing entry by TOKEN first and by name second. After the panel's stable-id
  #     migration the store is keyed by an opaque id, so `nodes[name] = …` adds a SECOND, name-keyed
  #     copy of a node that is already there.
  #   · when the hash is refreshed, DROP `token_sha`. It indexes the previous token, and the panel
  #     skips its pbkdf2 fallback for any entry that has one — leaving a stale one beside a new hash
  #     locks the node out for good ("invalid node token" on every sync, for ever).
  # The panel expects this path: its sync handler re-stages mesh links for "a node that entered the
  # store outside /api/nodes/create (auto-enrolled master/local node)".
  localNodeSeedPy = pkgs.writeText "swg-panel-seed-localnode.py" ''
    import sys, os, json, hashlib, base64

    path, name, tokfile, color = sys.argv[1:5]
    token = open(tokfile).read().strip()
    if not token:
        sys.exit("swg-panel: local-node tokenFile is empty — nothing to enrol")
    try:
        nodes = json.load(open(path)); assert isinstance(nodes, dict)
    except Exception:
        nodes = {}

    def tok_hash(t):
        salt = os.urandom(16)
        h = hashlib.pbkdf2_hmac("sha256", t.encode(), salt, 200000)
        return "pbkdf2_sha256$200000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()

    def validates(th, t):
        try:
            algo, it, salt, h = th.split("$")
            return algo == "pbkdf2_sha256" and base64.b64encode(
                hashlib.pbkdf2_hmac("sha256", t.encode(), base64.b64decode(salt), int(it))).decode() == h
        except Exception:
            return False

    key = next((k for k, v in nodes.items() if isinstance(v, dict) and validates(v.get("token_hash", ""), token)), None)
    if key is None:
        key = next((k for k, v in nodes.items() if isinstance(v, dict) and v.get("name") == name), None)
    if key is None:
        nodes[name] = {"name": name, "color": color, "endpoint_host": "",
                       "stats_file": "stats-%s.json" % name, "token_hash": tok_hash(token), "created": 0}
        print("swg-panel: enrolled the local node %s" % name)
    else:
        e = nodes[key]; e["name"] = name
        e.setdefault("color", color); e.setdefault("endpoint_host", "")
        e.setdefault("stats_file", "stats-%s.json" % name); e.setdefault("created", 0)
        if not validates(e.get("token_hash", ""), token):
            e["token_hash"] = tok_hash(token)
            e.pop("token_sha", None)
            print("swg-panel: refreshed the local node %s's token" % name)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(nodes, f, indent=2)
    os.replace(tmp, path)
  '';

  localNodeSeed = owner: pkgs.writeShellScript "swg-panel-seed-localnode" ''
    set -eu
    umask 027
    ${pkgs.python3}/bin/python3 ${localNodeSeedPy} \
      ${lib.escapeShellArg "${stateDir}/nodes.json"} \
      ${lib.escapeShellArg cfg.localNode.name} \
      ${lib.escapeShellArg (toString cfg.localNode.tokenFile)} \
      ${lib.escapeShellArg cfg.localNode.color}
    chown ${owner} ${stateDir}/nodes.json 2>/dev/null || true
    chmod 0640 ${stateDir}/nodes.json 2>/dev/null || true
  '';

  # What a co-located node dials. NOT the public address, which moves on an address flip and would
  # leave the box's own node talking to itself through its reverse proxy. This endpoint is plain
  # HTTP by construction — the panel adds it with no cert (`LISTENERS.add(…, None, None)`) — which
  # is why the node must also stop verifying a certificate that is not there.
  localNodeUrl = "http://127.0.0.1:${toString cfg.localPort}";

  # Where the panel touches a file to ask for an update. Defined here so T-N7's unit and the panel
  # agree on the path — and deliberately NOT passed to the panel yet: see the note at its use.
  updateTrigger = "${stateDir}/.update-request";

  # T-N7 / D14 tier 2. `rebuild` is built unconditionally because tier ONE needs its `command`: even
  # with the button unwired, the Update dialog has to show what an update IS on this host, and the
  # only way that string cannot drift from what the button runs is for both to come from here.
  rebuild = import ./rebuild.nix {
    inherit pkgs lib;
    name = "panel";
    inherit (cfg.selfUpdate) flakeRef updateInputs;
    resultFile = "${stateDir}/host_proc";
    resultShape = "host_proc";
    # The panel REWRITES host_proc itself (it marks the host "updating" the moment the button is
    # pressed). Root-owned, that write fails silently and the header keeps a stale tag for ever.
    resultOwner = if cfg.delivery == "native" then "swgpanel:swg" else "";
    stampFile = "${stateDir}/.update-stamp";
    triggerFile = updateTrigger;
  };

in
{
  # swg-sub on the native arm lives in its own file because it is its own SECURITY BOUNDARY (D8),
  # not because this one was getting long. Its options are declared HERE, because a subscription
  # surface with no panel is not a thing and it reads the panel's state.
  imports = [ ./sub.nix ];

  options.services.swg-panel = {
    enable = mkEnableOption "the swg control panel";

    delivery = mkOption {
      type = types.enum [ "container" "native" ];
      default = "container";
      description = ''
        How the panel runs. `container` uses the image published to GHCR and brings the public
        subscription surface (swg-sub) with it. `native` runs swg-panel-server from the Nix store as
        its own user; swg-sub on that arm lands separately.
      '';
    };

    backend = mkOption {
      type = types.enum [ "docker" "podman" ];
      default = "docker";
      description = "Container runtime for `delivery = \"container\"`.";
    };

    image = mkOption {
      type = types.str;
      default = "ghcr.io/sanityprotocol/swg-panel:latest";
      description = ''
        The panel image, which swg-sub also runs (swg-sub is pure stdlib and needs no build of its
        own). **Pin it by digest** if you want a `nixos-rebuild --rollback` that goes back to the
        code you were running; a moving tag does not.
      '';
    };

    package = mkOption {
      type = types.package;
      default = pkgs.callPackage ../package.nix { };
      defaultText = literalExpression "pkgs.callPackage <swg-panel>/nix/package.nix { }";
      description = "The swg-panel package, for `delivery = \"native\"`. Resolved against YOUR pkgs.";
    };

    host = mkOption {
      type = types.str;
      default = "127.0.0.1";
      description = ''
        Address the panel listens on. Loopback by default, deliberately: the panel is meant to sit
        behind your own reverse proxy with `security.acme` terminating TLS. Widen it only if you
        also set `useACMEHost`, or you will be serving a login over plain HTTP to the internet.
      '';
    };

    port = mkOption {
      type = types.port;
      default = 8443;
      description = "Port the panel listens on.";
    };

    localPort = mkOption {
      type = types.port;
      default = 8088;
      description = ''
        A dedicated plain-HTTP loopback port that a public address change never moves, so a
        master's co-located node can dial the panel without ever stranding. Harmless on a panel
        with no local node.
      '';
    };

    basePath = mkOption {
      type = types.str;
      default = "";
      example = "/swg";
      description = "Subpath to serve under, when the panel is mounted somewhere other than `/`.";
    };

    domain = mkOption {
      type = types.str;
      default = "localhost";
      description = "The panel's public hostname. Presentation and link generation; certificates come from `security.acme`.";
    };

    publicUrl = mkOption {
      type = types.str;
      default = "";
      example = "https://panel.example.org:8443/swg";
      description = ''
        The full address the panel advertises, when `https://<domain><basePath>` is not it — a plain-HTTP
        proxy in front, or a public port that is neither 443 nor `port`.

        Leave it empty and the module derives one from `domain`, `basePath` and (with `useACMEHost`)
        `port`. It is written into the panel's own settings on every start, because on a declarative host
        the Access screen is read-only and cannot supply it — without it subscription links have no base
        to hang off and the panel advertises nothing.
      '';
    };

    useACMEHost = mkOption {
      type = types.nullOr types.str;
      default = null;
      example = "panel.example.org";
      description = ''
        Serve TLS directly from a certificate `security.acme` already manages, instead of putting a
        reverse proxy in front. The panel joins the certificate's group so it can read the key, and
        the certificate's `reloadServices` gains the panel unit, so a renewal takes effect without
        anyone noticing — that is what replaces the bare-metal panel's watch-and-restart.

        The certificate itself is never configured here. Declare it under `security.acme.certs` with
        whatever challenge you use.

        ⚠️ This module puts that certificate in the `swg` group, so the panel can read its key
        through its own group. Do not set `security.acme.certs.<host>.group` yourself as well — and
        if the same certificate also fronts something else, give that consumer the `swg` group
        rather than changing this one.
      '';
    };

    environmentFile = mkOption {
      type = types.path;
      example = "/run/secrets/swg-panel.env";
      description = ''
        A file that must define `PANEL_PASSWORD=<initial admin password>`. It is used **once**, to
        seed the login on a panel that has none; after that the password lives in the panel's own
        auth file and is changed in the UI, and this value is ignored.

        A path to a file, deliberately, and not the password itself: a password written into a Nix
        option lands in the world-readable store.

        ⚠️ Give it a **string** path (`"/run/secrets/swg-panel.env"`), not a Nix path literal
        (`/run/secrets/swg-panel.env`). A path literal is copied into the store at build time, which
        is the very thing this option exists to avoid — so the module refuses one.
      '';
    };

    user = mkOption {
      type = types.str;
      default = "admin";
      description = "Initial admin username, used with the same seeding as the password above.";
    };

    stateDir = mkOption {
      type = types.path;
      default = "/var/lib/swg-panel";
      description = ''
        The roster, the node store, subscription blobs and the encryption escrow. **Must persist** —
        this is the fleet.
      '';
    };

    configDir = mkOption {
      type = types.path;
      default = "/etc/swg-panel";
      description = ''
        The panel's own config directory. ⚠️ It is **writable state**, not configuration: the panel
        rewrites the auth file here when the operator changes their password, and the installer's
        own `ReadWritePaths` lists it for that reason. The module seeds what belongs here and then
        stays out of the way.
      '';
    };

    statsDir = mkOption {
      type = types.path;
      default = "/var/www/wgstats";
      description = "Where node snapshots are mirrored for the status board.";
    };

    subTlsDir = mkOption {
      type = types.path;
      default = "/etc/swg-sub/tls";
      description = "swg-sub's OWN certificate directory — never the panel's key (D8).";
    };

    storeConfigs = mkOption {
      type = types.bool;
      default = true;
      description = ''
        Keep a copy of each peer's config on the panel, so its QR and download stay available and an
        existing peer can be re-shared. **On by default — the same as the bare-metal and Docker
        installers, and as the panel's own default when nothing sets it.** This module used to force
        it off; that made a Nix panel the odd one out, where every other install could re-issue a
        config and this one silently could not.

        What "on" stores is not the plaintext key: it is an AES-GCM blob the server cannot read on its
        own (the browser-side Encryption Vault gates every decrypt). Set it to `false` for a panel
        that must keep nothing at rest — then QR and download only work in the moment a peer is
        created, and existing peers need a one-time key rotation to capture a config.
      '';
    };

    nodeInterval = mkOption {
      type = types.int;
      default = 5;
      description = "How often, in seconds, a node syncs to this panel.";
    };

    sub = {
      enable = mkOption {
        type = types.bool;
        default = true;
        description = ''
          Run the public subscription surface alongside the panel (`delivery = "container"`).

          It is installed inert: the whole surface 404s until it is switched on in
          Settings → Subscriptions. It runs as a SEPARATE container with the state mounted
          read-only and the panel's secrets masked, because it is the one process here that is
          deliberately reachable from the internet.
        '';
      };
      port = mkOption {
        type = types.port;
        default = 8444;
        description = "Loopback port for the subscription surface, to be fronted by your reverse proxy.";
      };
      domain = mkOption {
        type = types.str;
        default = "";
        description = "The subscription page's own hostname, when it is not the panel's.";
      };

      publicUrl = mkOption {
        type = types.str;
        default = "";
        example = "https://sub.example.org/swgsub";
        description = ''
          The address subscription links are built from, when `https://<sub.domain><sub.basePath>` is not
          it.

          ⚠️ With neither this, `sub.domain` nor `sub.basePath` set, the module writes NO subscription
          base at all — deliberately. The only address it could derive would be the panel's own, and a
          subscription link that opens the panel is worse than one that visibly does not exist yet.
        '';
      };
      host = mkOption {
        type = types.str;
        default = "127.0.0.1";
        description = ''
          Address the subscription surface listens on (`delivery = "native"`). Loopback by default,
          for the same reason as the panel: terminate TLS in front of it.

          On the container arm this is the address the port is PUBLISHED on rather than the address the
          process binds (it binds inside its own namespace) — the reachability is the same either way.
        '';
      };

      basePath = mkOption {
        type = types.str;
        default = "";
        example = "/swgsub";
        description = "Subpath to serve under, when the surface is mounted somewhere other than `/`.";
      };

      trustProxyHeaders = mkOption {
        type = types.bool;
        default = true;
        description = ''
          Trust `X-Forwarded-For` for rate limiting. On by default here because this arm always sits
          behind a reverse proxy — without it every request appears to come from the proxy and the
          rate limiter counts them as one client.
        '';
      };
    };

    localNode = {
      enable = mkOption {
        type = types.bool;
        default = false;
        description = ''
          Enrol a co-located `services.swg-node` on this machine — the **master** role, the same one
          the other two install methods offer.

          What it removes is a round trip: without it you bring the panel up, mint a token in the
          Nodes screen, put it in a secrets file and rebuild. With it, you generate the token with
          your own secrets tooling, hand the same file to both modules, and one rebuild is enough.
          Nothing is minted in the Nix store — the token is only ever read from `tokenFile` at
          activation, and only its hash reaches `nodes.json`.

          Re-running is safe: an entry that already validates against this token is left alone, and
          one whose token changed is refreshed in place rather than duplicated.

          The node module is configured separately, and there are exactly two things it has to get
          right — the address it dials, and not verifying a certificate that is not there:

          ```nix
          services.swg-node = {
            enable = true;
            endpoint = "203.0.113.10";                    # what CLIENTS dial
            panelUrl = "${localNodeUrl}";   # what THIS node dials — plain HTTP, on loopback
            verifyPanelTls = false;                       # there is no certificate on that endpoint
            tokenFile = "/run/secrets/swg-local-node-token";   # the same file as below
          };
          ```

          That URL is deliberately not the public one: the public address moves on an address change,
          and dialing it would send this box's own node out through its reverse proxy and back.
        '';
      };

      name = mkOption {
        type = types.str;
        defaultText = literalExpression "config.networking.hostName";
        default = config.networking.hostName;
        description = "The node's name in the panel. Defaults to this machine's hostname.";
      };

      tokenFile = mkOption {
        type = types.nullOr types.str;
        default = null;
        example = "/run/secrets/swg-local-node-token";
        description = ''
          A file holding the enrolment token — the SAME file `services.swg-node.tokenFile` points at.
          Generate it with your secrets tooling; the panel stores only its hash.

          ⚠️ A **string** path, not a Nix path literal, for the reason every other secret option here
          says so: a path literal is copied into the world-readable store.
        '';
      };

      color = mkOption {
        type = types.str;
        default = "#34d399";
        description = "The node's colour in the panel, matching what `/api/nodes/create` would pick.";
      };
    };

    secretsDependencies = mkOption {
      type = types.listOf types.str;
      default = [ ];
      example = [ "sops-install-secrets.service" ];
      description = ''
        Units that must have finished before this panel's secret is read — the unit your secrets
        tooling runs to decrypt it.

        ⚠️ Without this there is an ordering RACE, and it is a real footgun rather than a theoretical
        one: `environmentFile` typically points into `/run/secrets`, which does not exist until
        sops-nix or agenix has written it. Win the race and the panel is seeded; lose it and the file
        is unreadable, the panel starts with **no login at all**, and — because the login is state and
        is only ever seeded when absent — it stays that way after the secret appears. The failure is
        therefore not transient, which is exactly why it deserves an option rather than a note.

        agenix orders its activation script before `multi-user.target`, so it usually needs nothing
        here; sops-nix's systemd-based mode does. Name the unit if you are unsure — ordering after a
        unit that does not exist is harmless.
      '';
    };

    selfUpdate = {
      enable = mkOption {
        type = types.bool;
        default = true;
        description = ''
          Wire the panel's **Update** button to a `nixos-rebuild switch` of this machine.

          **On by default — so the Update button just works, the same as on every other install.**
          The defaults below assume the standard layout the panel's own config snippet lays down: a
          flake at `/etc/nixos` whose attribute is this host's name, with `swg-panel` as an input.
          Paste that snippet and Update works with no further configuration.

          If your layout differs, point `flakeRef`/`updateInputs` at it, or set `enable = false` and
          the button falls back to showing the exact command for you to run by hand. This is safe to
          leave on regardless: a `nixos-rebuild switch` is atomic, so a layout mismatch makes the
          button report a clear error and change nothing — it can never half-update or break the
          running machine.

          The rebuild runs as its own root unit, so it survives restarting the very services it is
          updating. Its outcome — including the tail of its output when it fails — comes back to the
          panel, because a rebuild can fail for reasons that have nothing to do with swg (an
          unrelated input that will not fetch, an out-of-tree kernel module against a new kernel)
          and "the button is broken" is a different problem from "your kernel pin needs bumping".
        '';
      };

      flakeRef = mkOption {
        type = types.str;
        default = "/etc/nixos#${config.networking.hostName}";
        defaultText = literalExpression ''"/etc/nixos#''${config.networking.hostName}"'';
        example = "/etc/nixos#myhost";
        description = ''
          What to build, including the attribute. Defaults to this host's flake at `/etc/nixos` —
          the layout the panel's snippet creates. Empty string means a plain `nixos-rebuild switch`,
          which uses whatever this system is already configured from.

          Fixed here, in the configuration, rather than taken from the panel: the trigger file's
          *contents* are ignored (the panel writes a timestamp), so nothing an operator types in a
          browser crosses the privilege boundary into a root rebuild.
        '';
      };

      updateInputs = mkOption {
        type = types.listOf types.str;
        default = [ "swg-panel" ];
        example = [ "swg-panel" ];
        description = ''
          Flake inputs to refresh before rebuilding — defaults to just the one this module came from,
          so pressing Update pulls a newer swg-panel and nothing else (nixpkgs and the kernel stay
          pinned).

          ⚠️ Empty means the rebuild lands on whatever your lock already pins, which is very often
          the version already running — the button then succeeds and changes nothing. Only meaningful
          for a local flake (`flakeRef` starting with `/`), which is the default.
        '';
      };
    };

    extraEnvironment = mkOption {
      type = types.attrsOf types.str;
      default = { };
      description = "Extra environment for the panel, merged last.";
    };
  };

  config = mkIf cfg.enable (lib.mkMerge [
    {
      assertions = [
        {
          # See the node module for why `builtins.isPath` is the load-bearing half of this.
          assertion = !(builtins.isPath cfg.environmentFile)
                      && !(lib.hasPrefix builtins.storeDir (toString cfg.environmentFile));
          message = ''
            services.swg-panel.environmentFile points into the Nix store
            (${toString cfg.environmentFile}). The store is world-readable, so the initial admin
            password would be readable by every user on this machine.

            This happens when the value is written as a Nix PATH LITERAL rather than a string:
              environmentFile = /run/secrets/swg-panel.env;     # copied into the store
              environmentFile = "/run/secrets/swg-panel.env";   # read at runtime, correct
          '';
        }
        {
          # `nix flake update` operates on a flake DIRECTORY. Naming inputs against a remote ref is
          # not a no-op that quietly does less than asked — it is a build-time mistake with a
          # runtime symptom (the button succeeds, nothing moves), so it fails here instead.
          assertion = cfg.selfUpdate.updateInputs == [ ] || rebuild.localFlake;
          message = ''
            services.swg-panel.selfUpdate.updateInputs names inputs to refresh, but flakeRef
            (${cfg.selfUpdate.flakeRef}) is not a local path — there is no lock on this machine to
            update. Point flakeRef at the flake on this host (e.g. "/etc/nixos#${config.networking.hostName}"),
            or clear updateInputs and let the remote ref be fetched fresh on each build.
          '';
        }
        {
          assertion = !cfg.localNode.enable || cfg.localNode.tokenFile != null;
          message = ''
            services.swg-panel.localNode.enable needs localNode.tokenFile — the file holding the
            enrolment token, which services.swg-node.tokenFile must point at too. Nothing is minted
            here: a token generated into a Nix option would land in the world-readable store.
          '';
        }
        {
          # The co-located node dials a port that a public address change never moves. With no such
          # port there is nothing stable to dial, and the node would have to be pointed at the public
          # address — out through the operator's own reverse proxy and back, and broken by the next
          # address flip.
          assertion = !cfg.localNode.enable || cfg.localPort != 0;
          message = ''
            services.swg-panel.localNode.enable needs a non-zero localPort. That is the dedicated
            plain-HTTP loopback endpoint a co-located node dials, and the one address a public
            address change never moves.
          '';
        }
        # ⚠️ There is deliberately NO assertion that `useACMEHost` names a declared certificate.
        # It cannot be written: this module sets `reloadServices` on that cert, which CREATES the
        # attribute, so any `certs ? <name>` test would be true because we made it true. A check
        # that cannot fail is worse than none — `security.acme` itself errors on a certificate with
        # no domain or challenge configured, and that is the honest place for it.
      ];

      # ── D14 tier 2: the trigger the panel already knows how to touch, given something to do ──
      # Defined for BOTH arms, and unconditional except for selfUpdate.enable: what differs between
      # them is only where the panel writes the trigger from (its own filesystem, or a bind mount),
      # and the unit watches the host path either way.
      systemd.services.swg-update = mkIf cfg.selfUpdate.enable {
        description = "swg-panel — rebuild this host on the panel's request";
        # ⚠️ A single Update writes the trigger once, but a `.path` unit that trips systemd's
        # 5-starts-per-10s limit fails PERMANENTLY, and the same omission has already cost this
        # project every Access change once (V.1). It costs nothing to not repeat it.
        unitConfig.StartLimitIntervalSec = 0;
        serviceConfig = {
          Type = "oneshot";
          ExecStart = rebuild.script;
        } // rebuild.resourceGuard;   # nice/idle-IO/OOM-first — a rebuild must never starve its host
      };

      systemd.paths.swg-update = mkIf cfg.selfUpdate.enable {
        description = "watch for a swg-panel update request";
        wantedBy = [ "paths.target" ];
        pathConfig = {
          PathModified = updateTrigger;
          Unit = "swg-update.service";
        };
      };

      # ⚠️ The container arm needs the poll and the native arm does not, and this is measured, not
      # defensive: the panel container writes the trigger through a bind mount, and inotify does not
      # cross one — a host `.path` unit never sees that write. install-docker.sh reaches the same
      # conclusion and retires its `.path` for exactly this reason. The stamp file in the rebuild
      # script is what stops the two triggers from running it twice.
      systemd.timers.swg-update = mkIf (cfg.selfUpdate.enable && cfg.delivery == "container") {
        description = "poll for a swg-panel update request (the panel writes it across a bind mount)";
        wantedBy = [ "timers.target" ];
        timerConfig = {
          OnActiveSec = "30s";
          OnUnitActiveSec = "30s";
          Unit = "swg-update.service";
        };
      };

      warnings =
        optional (cfg.host != "127.0.0.1" && cfg.useACMEHost == null) ''
          services.swg-panel.host is ${cfg.host} and useACMEHost is unset, so the panel is serving
          plain HTTP off loopback — its login would travel in the clear. Put a reverse proxy in
          front and leave host at 127.0.0.1, or set useACMEHost to serve TLS directly.
        '';
    }

    # ── container arm ────────────────────────────────────────────────────────────────────────────
    (mkIf (cfg.delivery == "container") {
      virtualisation.oci-containers.backend = cfg.backend;
      virtualisation.docker.enable = mkIf (cfg.backend == "docker") true;
      virtualisation.podman = mkIf (cfg.backend == "podman") { enable = true; };
      virtualisation.containers.enable = mkIf (cfg.backend == "podman") true;

      systemd.tmpfiles.rules = [
        "d ${etcDir} 0755 root root -"
        "d ${stateDir} 0755 root root -"
        "d ${cfg.statsDir} 0755 root root -"
        "d ${cfg.subTlsDir} 0755 root root -"
      ]
      # Pre-create the trigger so the watch has an inode from the first boot. `f` creates only when
      # absent — it never truncates one the panel has already written.
      ++ optional cfg.selfUpdate.enable "f ${updateTrigger} 0660 root root -";

      # The container arm has no ExecStartPre of its own to hang these on — `oci-containers` owns the
      # unit — so they get their own oneshot, ordered before the container. The same two scripts the
      # native arm runs, deliberately: one shape, no drift.
      #
      # ⚠️ Ordered before the PANEL, which swg-sub is in turn ordered after — so the auth file is
      # already non-empty by the time either container looks at it. That is also what retires the
      # empty-file race the image entrypoint's `-s` test exists for.
      systemd.services.swg-panel-access-seed = {
        description = "swg-panel — seed the declared address and the initial login";
        wantedBy = [ "multi-user.target" ];
        before = [ "${cfg.backend}-swg-panel.service" ];
        after = [ "systemd-tmpfiles-setup.service" ] ++ cfg.secretsDependencies;
        wants = cfg.secretsDependencies;
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          ExecStart = [ accessSeed (authSeed "root:root") ]
                       ++ optional cfg.localNode.enable (localNodeSeed "root:root");
        };
      };

      virtualisation.oci-containers.containers.swg-panel = {
        inherit (cfg) image;
        environment = {
          PANEL_USER = cfg.user;
          PANEL_DOMAIN = cfg.domain;
          SUB_DOMAIN = subDomain;
          # ⚠️ This is the whole of "disable the bundled acme.sh" (D7): nothing in the image reaches
          # for a certificate, and security.acme owns them instead. But that is TWO cases, not one.
          # Behind a proxy (no useACMEHost) the panel serves plain HTTP and TLS=none says so. With
          # useACMEHost the operator asked this panel to terminate TLS ITSELF — and the certificate
          # is already mounted below, so the only thing missing was telling the entrypoint where it
          # is. Without that it took TLS=none literally: it logged "serving plain HTTP (login travels
          # in the clear)" while a perfectly good certificate sat mounted beside it, unread. Any mode
          # that is neither `none` nor a CA mode means "a mounted certificate wins" to the image.
          TLS = if useACME then "mounted" else "none";
          SWG_PANEL_BASE = cfg.basePath;
          SWG_PANEL_LOCAL_PORT = toString cfg.localPort;
          # ⚠️ In a container os.uname().nodename is the container id. Without the HOST's hostname a
          # master's co-located node is never recognised as local, and its update stops being tied
          # to the panel's.
          SWG_HOST_HOSTNAME = config.networking.hostName;
          SWG_PANEL_PLATFORM = "nixos";
          SWG_DECLARATIVE = "1";
          # Tier 1 always, tier 2 only when wired. The command is the SAME value the unit runs, so
          # the dialog cannot describe an update this host would not perform.
          SWG_UPDATE_CMD = rebuild.command;
        } // lib.optionalAttrs useACME {
          # The mounted certificate's path INSIDE the container — the mount is the same path on both
          # sides, so these are the host paths too.
          SWG_PANEL_TLS_CERT = "${certDir}/fullchain.pem";
          SWG_PANEL_TLS_KEY = "${certDir}/key.pem";
        } // lib.optionalAttrs cfg.selfUpdate.enable {
          # The path INSIDE the container; ${stateDir} is mounted at /var/lib/swg-panel, and the
          # host-side unit above watches the same inode from the other end of that bind mount.
          SWG_UPDATE_TRIGGER = "/var/lib/swg-panel/.update-request";
        } // cfg.extraEnvironment;
        # ⚠️ NO environmentFiles, deliberately, and this is the whole of T-P5 on this arm. Handing the
        # file to the container put the initial admin password in that container's environment for
        # its entire life — inspectable by anything that can read a container's env, forever, for a
        # value needed exactly once at first boot. The host seeds the auth file instead (the image's
        # own rule is that a non-empty one wins), so the secret never crosses the boundary.
        # Anything else an operator wants in the container's env goes through `extraEnvironment`.
        ports = [
          # Loopback only, always: TLS is terminated in front of this, not in it.
          # PUBLISHED ON `host`, not hardcoded to loopback. The two settings contradicted each other:
          # `useACMEHost` means "this panel terminates TLS itself, there is no proxy in front", and a
          # port published only on 127.0.0.1 means the opposite — the panel served a valid certificate
          # that nothing outside the box could ever reach (Cloudflare answered 521). `host` defaults to
          # loopback, so the proxied arrangement is unchanged; an operator who widened it now gets what
          # they asked for on this arm too.
          "${cfg.host}:${toString cfg.port}:8443"
          # The stable endpoint a co-located node dials. Host port == container port on purpose, so
          # a public address change never moves it.
          "127.0.0.1:${toString cfg.localPort}:${toString cfg.localPort}"
        ];
        volumes = [
          "${etcDir}:/etc/swg-panel"
          "${stateDir}:/var/lib/swg-panel"
          "${cfg.statsDir}:/var/www/wgstats"
          "${cfg.subTlsDir}:/etc/swg-sub/tls"
        ] ++ optional useACME "${certDir}:${certDir}:ro";
      };

      virtualisation.oci-containers.containers.swg-sub = mkIf cfg.sub.enable {
        inherit (cfg) image;
        # NOT the panel entrypoint: no acme, no fleet writes, just serve. This is what makes the
        # internet-facing surface a different process from the one that owns the fleet.
        entrypoint = "/opt/swg-panel/swg-sub";
        # ⚠️ Ordering is load-bearing, not tidiness. Mounting /dev/null over
        # /etc/swg-panel/auth CREATES an empty auth file on the host as its mount target. The panel
        # entrypoint tests `[ ! -s ]`, not `-f`, precisely so that an empty one still seeds a login
        # — but let the sub win the race and there is a moment where the panel has no password set.
        dependsOn = [ "swg-panel" ];
        environment = {
          SWG_SUB_FLEET = "/etc/swg-panel/fleet.json";
          SWG_SUB_WEB = "/opt/swg-panel";
          SWG_SUB_HOST = "0.0.0.0";
          SWG_SUB_PORT = "8444";
          SWG_SUB_TRUST_XFF = if cfg.sub.trustProxyHeaders then "1" else "0";
        };
        ports = [ "${cfg.sub.host}:${toString cfg.sub.port}:8444" ];   # same rule as the panel's, above
        volumes = [
          "${etcDir}:/etc/swg-panel:ro"
          "${stateDir}:/var/lib/swg-panel:ro"
          "${cfg.statsDir}:/var/www/wgstats:ro"
          "${cfg.subTlsDir}:/etc/swg-sub/tls:ro"
          # Defence in depth, and the sub's actual security boundary (D8). A container runs as root,
          # so `:ro` alone would not stop a compromise from opening these — masking them means there
          # is nothing to open. swg-sub reads none of them; it takes its config from subs/serve.json.
          "/dev/null:/etc/swg-panel/auth:ro"                      # the panel login hash
          "/dev/null:/var/lib/swg-panel/panel-settings.json:ro"   # webhook secrets, API token hashes
          "/dev/null:/var/lib/swg-panel/subs/vault.json:ro"       # the subscription-key vault
          "/dev/null:/var/lib/swg-panel/subs/escrow.json:ro"      # SK-wrapped per-user unlock keys
        ];
        extraOptions = [
          # A directory needs a tmpfs to mask it; /dev/null only masks a file.
          "--tmpfs=/etc/swg-panel/tls"        # the PANEL's private key — never the internet-facing surface's
          "--tmpfs=/var/lib/swg-panel/configs"
        ];
      };
    })

    # ── native arm ───────────────────────────────────────────────────────────────────────────────
    # A renewal reloads the panel — on WHICHEVER arm runs it. This used to live in the native branch
    # below, so on the container arm nothing was wired at all: a renewed certificate would have been
    # read at the next restart, whenever that happened to be, and silently — nobody sees a reload
    # that was never asked for. The unit name differs by arm because the units do.
    (mkIf useACME {
      security.acme.certs.${cfg.useACMEHost}.reloadServices =
        [ (if cfg.delivery == "container" then "${cfg.backend}-swg-panel.service" else "swg-panel-server.service") ];
    })

    (mkIf (cfg.delivery == "native") {
      users.groups.swg = { };
      users.users.swgpanel = {
        isSystemUser = true;
        group = "swg";
        description = "swg control panel";
      };

      # The installer's exact ownership and modes, and the setgid bits are load-bearing: they are
      # what lets swg-sub — a different user in group swg — reach the files it may read, and what
      # lets the panel rewrite its auth file in a directory root owns.
      systemd.tmpfiles.rules = [
        "d ${etcDir} 2775 root swg -"
        "d ${etcDir}/tls 0750 root swg -"
        "d ${stateDir} 0750 swgpanel swg -"
        # …and hand the CONTENTS to swgpanel too, on every boot. State outlives the service user: a box
        # that ran the container arm (panel as root) or an older native one (a swgpanel with a different
        # uid) leaves files this swgpanel cannot read — and a 0600 session.key it cannot read is the one
        # that hurts, because the panel then signs cookies with a throwaway secret and logs every
        # operator out on each restart. `Z` is the recursive form and the `-` mode leaves each file's own
        # permissions alone, so users.json and session.key keep their 0600. Nothing under here is meant
        # to belong to anyone else on this arm — there is no swg-netctl in the Nix module.
        "Z ${stateDir} - swgpanel swg -"
        "d ${stateDir}/subs 0750 swgpanel swg -"
        "d ${stateDir}/subs/blobs 0750 swgpanel swg -"
        "d ${cfg.statsDir} 2775 swgpanel swg -"
        # swg-sub's own TLS material, reachable by the user that actually serves it. `z` adjusts what
        # is there and creates nothing, because who WRITES these differs by arm: on the container arm
        # the panel image copies the panel certificate in here as root:root 0600, and after a flip
        # back to native the unprivileged swgsub could not read its own key — it died on
        # load_cert_chain, restarted, and came up serving PLAIN HTTP with only a traceback to say so.
        # Measured on a container→native round trip on a live master.
        "d ${cfg.subTlsDir} 0750 root swg -"
        "z ${cfg.subTlsDir}/fullchain.pem 0640 root swg -"
        "z ${cfg.subTlsDir}/key.pem 0640 root swg -"
      ] ++ optional cfg.storeConfigs "d ${stateDir}/configs 0750 swgpanel swg -"
        # Owned by the PANEL: it is the panel that touches this to ask for an update, and it runs
        # unprivileged. `f` creates only when absent.
        ++ optional cfg.selfUpdate.enable "f ${updateTrigger} 0660 swgpanel swg -";

      security.acme.certs = mkIf useACME {
        ${cfg.useACMEHost} = {
          # (a renewal reloads the panel — defined for BOTH arms outside this branch, which is
          # native-only; see the `reloadServices` block above.)

          # ⚠️ The panel reads the key through its OWN group, and the certificate is put in that
          # group — rather than the panel user joining the certificate's group, which is the
          # obvious way round and is an INFINITE RECURSION: `users.users.swgpanel.extraGroups`
          # would read `security.acme.certs.<h>.group`, so `users.groups` depends on
          # `security.acme.certs`, which depends on this module's definitions, which depend on
          # `users.groups`. Measured, not feared — it takes the whole evaluation down with a stack
          # trace that names logrotate and never mentions either module.
          #
          # A hard definition, not mkDefault, on purpose: this module takes ownership of that
          # certificate's group. Setting it yourself gets a conflict message naming both
          # definitions, which is a better outcome than a panel that starts and cannot read its key.
          group = "swg";
        };
      };

      systemd.services.swg-panel-server = {
        description = "swg-panel — the control plane";
        wantedBy = [ "multi-user.target" ];
        # `wants` as well as `after`: ordering alone does not PULL the secrets unit in, and a unit
        # that is merely ordered-after one nothing started is ordered after nothing at all.
        after = [ "network.target" ] ++ cfg.secretsDependencies;
        wants = cfg.secretsDependencies;

        path = with pkgs; [ openssl curl coreutils ];

        environment = {
          SWG_PANEL_FLEET = "${etcDir}/fleet.json";
          SWG_PANEL_WEB = "${cfg.package}/libexec/swg-panel";
          SWG_PANEL_HOST = cfg.host;
          SWG_PANEL_PORT = toString cfg.port;
          SWG_PANEL_LOCAL_PORT = toString cfg.localPort;
          SWG_PANEL_AUTH = "${etcDir}/auth";
          SWG_PANEL_BASE = cfg.basePath;
          SWG_PANEL_TLS_CERT = optionalString useACME "${certDir}/fullchain.pem";
          SWG_PANEL_TLS_KEY = optionalString useACME "${certDir}/key.pem";
          SWG_PANEL_PLATFORM = "nixos";
          SWG_DECLARATIVE = "1";
          # Tier 1: what an update IS on this host, shown in the Update dialog whether or not the
          # button is wired. The same value the rebuild unit runs, by construction.
          SWG_UPDATE_CMD = rebuild.command;

          # ⚠️ The panel's own service-health probe expects the BARE-METAL installer's five units by
          # default, and three of them do not exist here — there is no `swg-netctl` at all (T-N10),
          # and one-click update is a `.path`, not a `.timer`, and only when it is switched on. Left
          # to the default this host would report three permanently missing services and a
          # "needs attention" row nobody could ever clear. So the module names what it actually
          # created; a key it omits is not checked.
          SWG_PANEL_UNITS = lib.concatStringsSep "," (
            [ "panel:swg-panel-server.service" ]
            ++ optional cfg.sub.enable "sub:swg-sub.service"
            ++ optional cfg.selfUpdate.enable "update:swg-update.path");
        } // lib.optionalAttrs cfg.selfUpdate.enable {
          # ⚠️ Set ONLY with selfUpdate.enable. The panel touches this file to ask for an update and
          # a root unit decides what "update" means; with no such unit the button would report
          # success and change nothing, which is worse than the honest fallback that says so.
          SWG_UPDATE_TRIGGER = updateTrigger;
        } // cfg.extraEnvironment;

        serviceConfig = {
          Type = "simple";
          # Both, explicitly. The installer's unit sets only User= and relies on the account's
          # primary group being swg — true there, and an assumption worth not inheriting.
          User = "swgpanel";
          Group = "swg";

          # Root, so it can write into a directory root owns and read the secret. `+` is what makes
          # it root; without it this would run as swgpanel and could read neither.
          ExecStartPre = "+${seedScript}";
          ExecStart = "${cfg.package}/libexec/swg-panel/swg-panel-server";

          Restart = "on-failure";
          RestartSec = 2;

          # The installer's write set, exactly: config, state, stats. /etc/swg-panel is in it
          # because the panel rewrites its auth file there — a second, independent confirmation
          # that that directory is state and not configuration.
          NoNewPrivileges = true;
          ProtectSystem = "strict";
          ReadWritePaths = [ etcDir stateDir cfg.statsDir ];
          ProtectHome = true;
          PrivateTmp = true;
        } // lib.optionalAttrs (cfg.port < 1024) {
          AmbientCapabilities = [ "CAP_NET_BIND_SERVICE" ];
        };
      };
    })
  ]);
}
