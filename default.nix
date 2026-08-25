# Channel (non-flake) users get exactly the flake's outputs, pinned by flake.lock (D1):
#     nix-build -A packages.x86_64-linux.default
#     (import ./.).nixosModules.swg-node        # once T-N8/T-N9 land
(import
  (
    let lock = builtins.fromJSON (builtins.readFile ./flake.lock); in
    fetchTarball {
      url = "https://github.com/edolstra/flake-compat/archive/${lock.nodes.flake-compat.locked.rev}.tar.gz";
      sha256 = lock.nodes.flake-compat.locked.narHash;
    }
  )
  { src = ./.; }
).defaultNix
