# swg-panel — Nix entry point.
#
# The module lives in the main repo on purpose (docs/NIXOS-SUPPORT-PLAN.md D1): VERSION is the
# single source of truth stamped into every component, so a separate `swg-panel-nix` repo would be
# version skew on day one. Every comparable project that ships its own NixOS module does the same.
#
# Nix is deliberately OFF the main CI path (D17) — `checks` run in their own workflow and never
# gate the image build, which is the release path.
{
  description = "swg-panel — a self-hosted control panel for a small WireGuard / AmneziaWG service";

  inputs = {
    # Pinned to a stable channel rather than unstable: the people this is for are running a VPN
    # appliance, and the native arm's datapath (linuxPackages.amneziawg) is a kernel module whose
    # breakage fails `nixos-rebuild` outright (VI.2). Consumers overriding this input is normal.
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    # Only ever read by default.nix, to give channel users the same outputs without flakes.
    flake-compat = { url = "github:edolstra/flake-compat"; flake = false; };
  };

  outputs = { self, nixpkgs, ... }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      # WHICH BUILD, threaded from the flake because only the flake knows it. `shortRev` exists for a clean
      # git tree, `dirtyShortRev` for one with uncommitted changes, and neither for a tarball input — in
      # which case this is "" and the package stamps the bare VERSION exactly as it did before.
      # ⚠️ In the `let`, not in the outputs attrset: that set is not recursive, so a sibling could not read it.
      # Parenthesised because `or` here is attribute-selection fallback, not a boolean.
      buildRev = self.shortRev or (self.dirtyShortRev or "");
      _revModule = { _module.args.swgBuildRev = buildRev; };
    in
    {
      # The overlay is the supported way to get the package against YOUR nixpkgs rather than ours.
      # The modules' `package` option defaults to a callPackage against the consumer's pkgs for the
      # same reason (D1), so importing a module never drags this flake's nixpkgs into your closure.
      overlays.default = final: _prev: {
        swg-panel = final.callPackage ./nix/package.nix { srcRoot = ./.; rev = buildRev; };
      };

      packages = forAllSystems (system:
        let pkgs = nixpkgs.legacyPackages.${system}; in
        {
          swg-panel = pkgs.callPackage ./nix/package.nix { srcRoot = ./.; rev = buildRev; };
          default = self.packages.${system}.swg-panel;
        });

      checks = forAllSystems (system:
        let pkgs = nixpkgs.legacyPackages.${system}; in
        {
          # The package builds, its shebangs resolved, and every VERSION landed.
          package = self.packages.${system}.swg-panel;
        }
        # The VM tests boot a real fleet, so they are x86_64 only — an aarch64 runner would emulate
        # the guest under TCG rather than fail, which is slow enough to read as a hang.
        // nixpkgs.lib.optionalAttrs (system == "x86_64-linux") {
          # A panel and a real native node, enrolled and converging: the happy path, the CRITICAL
          # invariant, the D6 reboot, and adoption's re-mint control.
          fleet-native = pkgs.testers.runNixOSTest (import ./nix/checks/fleet.nix { srcRoot = ./.; });
          # The container arm's host-side half — sysctls, tmpfiles, the runtime, the generated
          # unit's contract. It deliberately never starts a container: a test VM has no registry
          # to pull from, and the alternatives (a stand-in image, a pinned digest) each cost more
          # than they buy. The file says why, at length.
          container-arm = pkgs.testers.runNixOSTest (import ./nix/checks/container-arm.nix { srcRoot = ./.; });
        });

      # `services.swg-node` and `services.swg-panel` are claimed by this repo (D2) — maintained at the same
      # commit as the code it starts. It takes nothing from this flake's inputs: the container arm
      # names a published image, and each native arm's `package` option callPackages
      # against the CONSUMER's pkgs, so importing this never drags our nixpkgs into your closure.
      # ⚠️ THE REV REACHES THE MODULES THROUGH `_module.args`, NOT THROUGH THE PACKAGE ARGUMENT, and that is
      # the whole trick. Each module's `package` option defaults to `pkgs.callPackage ../package.nix { }` —
      # deliberately the CONSUMER's pkgs (D1), so importing a module never drags this flake's nixpkgs into
      # their closure — and a default written there cannot see `self`. Threading it as a module arg keeps
      # that property and simply tells the default which build it came from. A consumer who imports the
      # module FILE directly, with no flake, gets the `""` fallback in the module's own signature and the
      # bare VERSION exactly as before.
      #
      # Measured before this existed: the box built through `nixosModules.default`, so stamping only
      # `packages.<system>.swg-panel` and the overlay changed nothing at all — the installed VERSION still
      # read `1.8.6-beta` after a full rebuild. Wiring the two outputs nobody's NixOS config goes through is
      # exactly the shape of a fix that passes review and ships a no-op.
      nixosModules = {
        swg-node = { imports = [ ./nix/modules/node.nix _revModule ]; };
        swg-panel = { imports = [ ./nix/modules/panel.nix _revModule ]; };
        # Both, because a master runs both on one host and importing two modules to describe one
        # machine is friction with nothing behind it.
        default = { imports = [ ./nix/modules/node.nix ./nix/modules/panel.nix _revModule ]; };
      };
    };
}
