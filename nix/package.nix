# swg-panel — every program and web asset a full install lays down, in ONE store path.
#
# One derivation, not three, because the repo is one unit: VERSION is the single source of truth
# stamped into every component (CLAUDE.md), so splitting the package would put version skew a
# rebuild away — the same reason the NixOS module lives in this repo rather than a foo-nix one
# (docs/NIXOS-SUPPORT-PLAN.md D1).
#
# ── why the layout mirrors /opt, and why $out/bin holds wrappers, not symlinks ──
# Two of our programs resolve files RELATIVE TO THEMSELVES:
#     swg-noded    dirname(__file__)/VERSION        and  dirname(argv[0])/swg-sni
#     panel / sub  $SWG_{PANEL,SUB}_WEB/VERSION  →  dirname(__file__)/VERSION
# so a program and its data have to sit in one directory — hence $out/libexec/<component>/,
# a store-path copy of what the installers write to /opt/<component>/.
# The bin entries EXEC the libexec path instead of symlinking to it: for a symlinked script the
# kernel hands the interpreter the SYMLINK's path, so argv[0]/__file__ would point at $out/bin
# and both lookups above would silently miss (VERSION reads empty, swg-sni "not found").
#
# ── the manifest ──
# panelWeb/subWeb below are the FOURTH place in this tree that names shipped assets — the others
# are Dockerfile's COPY lines, lib/common.sh's SUB_WEB and swg-sub's own STATIC map. A file that
# is added to some of them and not the rest breaks only a FRESH build or install, which is how
# 3b731f7 reached CI. `.campaign/shipped-assets-audit.mjs` holds all four in step; run it
# whenever an asset is added or removed.
{ lib
, stdenvNoCC
, python3
, runtimeShell
  # Root of the source tree. Defaults to this file's parent so the module can `callPackage
  # ./package.nix { }` against the CONSUMER's pkgs (D1) without threading a src through.
, srcRoot ? ../.
}:

let
  fs = lib.fileset;

  version = lib.fileContents (srcRoot + "/VERSION");

  # Panel web root — matches install-host.sh's copy loop ("index.html app.css app.js
  # reconcile.js turn-artifacts.js") and Dockerfile's first COPY.
  panelWeb = [ "index.html" "app.css" "app.js" "reconcile.js" "turn-artifacts.js" ];

  # swg-sub's static allow-list. Byte-for-byte the same list, in the same order, as SUB_WEB in
  # lib/common.sh — keep it that way so a drift is a one-line diff.
  subWeb = [ "sub.html" "sub.js" "sub.css" "turn-artifacts.js" ];

  # Directories copied whole, exactly as the installers and the Dockerfile copy them, so adding
  # a module or a font never touches this file.
  trees = [ "js" "vendor" ];

  programs = [
    "swg-panel-server"   # the panel: UI + node-sync API
    "swg-sub"            # the public subscription surface — its own user and unit (D8)
    "swg-noded"          # node daemon
    "swg-sni"            # SNI classifier, launched by swg-noded from its own directory
    "swg-agent"          # one peer op, stdin → stdout
    "swg-netctl"         # Access/TLS helper, root-side of the panel's queue
    "swg-passwd"         # `swg-passwd` — reset the panel login
  ];

  # lib.fileset throws on a path that does not exist, so a shipped file lost to .gitignore or a
  # rename fails EVALUATION rather than producing a quietly incomplete store path (V.6b).
  shipped = fs.unions (map (p: srcRoot + "/${p}")
    ([ "VERSION" "docker/node-entrypoint.sh" ] ++ programs ++ trees ++ panelWeb ++ subWeb));

in
stdenvNoCC.mkDerivation {
  pname = "swg-panel";
  inherit version;

  src = fs.toSource { root = srcRoot; fileset = shipped; };

  # python3 is a HOST input, not a native one: patchShebangs --host rewrites
  # `#!/usr/bin/env python3` to this interpreter, so every program carries its own. Round A of the
  # NixOS work found python3 absent from a node's system profile and the failure was silent — a
  # program whose shebang cannot resolve just does not run. This makes that impossible for ours.
  # (node-entrypoint.sh still calls `python3` from PATH, so the module's `path` needs it too.)
  buildInputs = [ python3 ];

  dontBuild = true;
  dontConfigure = true;

  installPhase = ''
    runHook preInstall

    # ── panel: program + SPA + VERSION in one directory ──
    install -Dm755 swg-panel-server $out/libexec/swg-panel/swg-panel-server
    install -Dm644 VERSION          $out/libexec/swg-panel/VERSION
    for f in ${lib.concatStringsSep " " panelWeb}; do
      install -Dm644 "$f" "$out/libexec/swg-panel/$f"
    done
    ${lib.concatMapStringsSep "\n    " (d: "cp -R --no-preserve=mode ${d} $out/libexec/swg-panel/${d}") trees}

    # ── swg-sub: its own directory, its own copy of VERSION (separate unit, user and TLS dir) ──
    install -Dm755 swg-sub          $out/libexec/swg-sub/swg-sub
    install -Dm644 VERSION          $out/libexec/swg-sub/VERSION
    for f in ${lib.concatStringsSep " " subWeb}; do
      install -Dm644 "$f" "$out/libexec/swg-sub/$f"
    done
    install -Dm644 vendor/qrcode.js $out/libexec/swg-sub/vendor/qrcode.js

    # ── node: swg-sni sits beside swg-noded because that is the first place it is looked for ──
    install -Dm755 swg-noded        $out/libexec/swg-noded/swg-noded
    install -Dm755 swg-sni          $out/libexec/swg-noded/swg-sni
    install -Dm644 VERSION          $out/libexec/swg-noded/VERSION

    install -Dm755 swg-agent        $out/libexec/swg-agent/swg-agent

    # The node's bootstrap: generates config.json, brings up every persisted interface before the
    # daemon starts, sets up NAT. Shared verbatim with the container arm (D15) — the native unit
    # runs this same file from the store.
    install -Dm755 docker/node-entrypoint.sh $out/libexec/swg-node/node-entrypoint.sh

    # ── $out/bin ──
    # swg-netctl and swg-passwd resolve nothing relative to themselves, so they are the real files.
    install -Dm755 swg-netctl $out/bin/swg-netctl
    install -Dm755 swg-passwd $out/bin/swg-passwd

    # The rest get a wrapper that execs the libexec path, so the interpreter sees THAT path as
    # argv[0]/__file__ and the sibling-file lookups above resolve. See the header.
    mkbin() {
      printf '#!%s\nexec %s "$@"\n' "${runtimeShell}" "$2" > "$out/bin/$1"
      chmod 755 "$out/bin/$1"
    }
    mkbin swg-panel-server $out/libexec/swg-panel/swg-panel-server
    mkbin swg-sub          $out/libexec/swg-sub/swg-sub
    mkbin swg-noded        $out/libexec/swg-noded/swg-noded
    mkbin swg-sni          $out/libexec/swg-noded/swg-sni
    mkbin swg-agent        $out/libexec/swg-agent/swg-agent

    runHook postInstall
  '';

  # --host: resolve the interpreter from buildInputs, which is what a cross build wants too.
  postFixup = ''
    patchShebangs --host $out/libexec $out/bin
  '';

  # A store path with an unpatched `#!/usr/bin/env python3` would run on the workstation that
  # built it and fail on a machine with no python3 on PATH — the exact silent failure above, just
  # moved. Fail the BUILD instead. `env` is only ever there because patchShebangs missed.
  doInstallCheck = true;
  installCheckPhase = ''
    bad=$(grep -rl '^#!/usr/bin/env' $out/libexec $out/bin || true)
    if [ -n "$bad" ]; then
      echo "unpatched shebang — patchShebangs did not resolve these:" >&2
      echo "$bad" >&2
      exit 1
    fi
    test -x $out/libexec/swg-noded/swg-noded
    test -s $out/libexec/swg-panel/VERSION
    test -s $out/libexec/swg-noded/VERSION
    test -s $out/libexec/swg-sub/VERSION
  '';

  meta = {
    description = "Self-hosted control panel for a small WireGuard / AmneziaWG service";
    longDescription = ''
      The panel is the source of truth for peers; each node syncs to it over outbound HTTPS only.
      This package ships all five programs plus the buildless SPA; the NixOS modules in the same
      flake decide which of them a given host runs.
    '';
    homepage = "https://github.com/SanityProtocol/swg-panel";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "swg-panel-server";
  };
}
