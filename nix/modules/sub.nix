# swg-sub on the native arm — the public subscription surface.
#
# Its own file because it is its own SECURITY BOUNDARY (docs/NIXOS-SUPPORT-PLAN.md D8), not because
# panel.nix was getting long. This is the one process in the whole system that is deliberately
# reachable from the internet, and it is separated from the panel on four axes at once: a different
# user, a read-only filesystem, its own TLS material, and a kernel-level mask over the secrets it
# must never open. Handing the panel's TLS private key to an internet-facing process would let its
# compromise impersonate the panel; that is the thing being prevented.
#
# ⚠️⚠️ There USED to be a `systemd/swg-sub.service` reference copy in this repo. It was DELETED
# (2026-08-24, Z-11) rather than annotated, and this note stays so nobody restores it from history
# thinking it was an oversight. It said `User=swgpanel` — the PANEL's own account — offered
# `SWG_SUB_TLS_KEY=/etc/swg-panel/tls/key.pem`, and carried **no InaccessiblePaths line at all**.
# Following it collapsed all three boundaries at once, on the one surface where every one of them is
# the point. A "reference copy" that has to be kept in step with a generator is a second declaration
# of the same contract, which is this repo's most-repeated bug class; the generated unit
# (`install-host.sh`'s `write_sub_unit`) and this module are the only two, and they agree.
#
# Options live in panel.nix under `services.swg-panel.sub` — a subscription surface with no panel
# is not a thing, and it reads the panel's state.
{ config, lib, pkgs, ... }:

let
  cfg = config.services.swg-panel;
  sub = cfg.sub;
  inherit (lib) mkIf optional optionalString;

  stateDir = cfg.stateDir;
  etcDir = cfg.configDir;

  # The six paths this process must never be able to open, each `-`-prefixed so a host where one
  # does not exist yet still starts. Masked at the KERNEL level rather than left to file modes:
  # the point is that a bug in this process cannot reach them even if the permissions were wrong.
  #
  #   the login hash · the PANEL's TLS key (never this process's) · the subscription-key vault
  #   (one key that unwraps every peer's) · the SK-wrapped per-user unlock keys and tokens ·
  #   webhook signing secrets and API token hashes · any stored client configs
  #
  # swg-sub reads NONE of them; it takes its configuration from subs/serve.json. The unlock key
  # rides in the URL fragment and never reaches the server, so what it can serve is ciphertext and
  # non-secret parameters — never a private key, never the fleet.
  masked = [
    "-${etcDir}/auth"
    "-${etcDir}/tls"
    "-${stateDir}/subs/vault.json"
    "-${stateDir}/subs/escrow.json"
    "-${stateDir}/panel-settings.json"
    "-${stateDir}/configs"
  ];

in
{
  config = mkIf (cfg.enable && cfg.delivery == "native" && sub.enable) {
    users.users.swgsub = {
      isSystemUser = true;
      # Group swg, and that is the whole of its read access: the panel's state is 0750
      # swgpanel:swg, so group membership lets it traverse to the files it may read while the
      # owner-only ones (0600) stay closed to it. A different user from the panel, deliberately —
      # this is the boundary, and reusing swgpanel would erase it while everything still worked.
      group = "swg";
      description = "swg subscription surface (public, read-only)";
    };

    # Its OWN certificate directory. Never the panel's — that one is masked above.
    systemd.tmpfiles.rules = [ "d ${cfg.subTlsDir} 0750 root swg -" ];

    systemd.services.swg-sub = {
      description = "swg-sub — public per-user subscription surface (read-only)";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];

      environment = {
        SWG_SUB_FLEET = "${etcDir}/fleet.json";
        SWG_SUB_WEB = "${cfg.package}/libexec/swg-sub";
        SWG_SUB_HOST = sub.host;
        SWG_SUB_PORT = toString sub.port;
        SWG_SUB_BASE = sub.basePath;
        SWG_SUB_TLS_DIR = cfg.subTlsDir;
        SWG_SUB_TRUST_XFF = if sub.trustProxyHeaders then "1" else "0";
      };

      serviceConfig = {
        Type = "simple";
        User = "swgsub";
        # Explicit, unlike the panel's generated unit, which sets only User= and relies on the
        # account's primary group. The installer's swg-sub unit sets both, and so does this.
        Group = "swg";
        ExecStart = "${cfg.package}/libexec/swg-sub/swg-sub";
        Restart = "on-failure";
        RestartSec = 2;

        # ── the hardening set, in full ──
        # ⚠️ There is deliberately NO ReadWritePaths. This process writes nothing, so with
        # ProtectSystem=strict the entire filesystem is read-only to it. Adding one "just for
        # logs" or "just for a cache" is how that property gets lost.
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        PrivateDevices = true;
        ProtectControlGroups = true;
        ProtectKernelModules = true;
        ProtectKernelTunables = true;
        RestrictNamespaces = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        InaccessiblePaths = masked;
      } // lib.optionalAttrs (sub.port < 1024) {
        # The installer adds this at install time when the sub is on a privileged port, and
        # swg-netctl's drop-in re-adds it whenever the panel moves it onto one.
        AmbientCapabilities = [ "CAP_NET_BIND_SERVICE" ];
      };
    };
  };
}
