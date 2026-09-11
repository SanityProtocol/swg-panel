#!/usr/bin/env python3
"""Self-test — THE NIX ARM MUST STAMP WHICH BUILD IT IS, and through the path people actually use.

Every other arm puts a commit in the VERSION it installs. The Nix arm installed the repo's bare `VERSION`,
so two different builds of the same branch both reported `1.8.6-beta` and the panel could not tell a node
running last week's code from one running today's.

⚠️ THIS IS AN ANCHOR GATE, and it says so. The behaviour was verified by building on a real NixOS box:
`/nix/store/0nc3ci79…-swg-panel-1.8.6-beta+28190a9/libexec/swg-noded/VERSION` read `1.8.6-beta+28190a9`, the
daemon ran from it, and the panel then reported that string for the node. What this file defends is the
WIRING, because two parts of it are invisible to a green build:

  1. WHICH OUTPUT. A NixOS config imports `nixosModules.*`, and each module's `package` default is
     `pkgs.callPackage ../package.nix { }` against the CONSUMER's pkgs (D1) — it cannot see `self`.
     Stamping only `packages.<system>` and the overlay changed NOTHING: measured, a full rebuild still
     installed `1.8.6-beta`. The rev has to reach the modules through `_module.args`.
  2. `echo`, NOT `printf '%s\\n'`. A Nix indented string passes backslashes through untouched, so the
     printf form writes a literal backslash-n into the file and every reader sees a version ending in it.

Run: python3 tests/nix_version_stamp_selftest.py      (0 = pass)
     --perturb   drops the module-args threading and expects RED.
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

PKG = open(os.path.join(ROOT, "nix", "package.nix"), encoding="utf-8").read()
FLAKE = open(os.path.join(ROOT, "flake.nix"), encoding="utf-8").read()
MODS = {n: open(os.path.join(ROOT, "nix", "modules", n), encoding="utf-8").read()
        for n in ("node.nix", "panel.nix")}

_ANCH = "        default = { imports = [ ./nix/modules/node.nix ./nix/modules/panel.nix _revModule ]; };"
assert FLAKE.count(_ANCH) == 1, "anchor missing — this run would FALSE-PASS"
if PERTURB:                                   # the shape that shipped a no-op: outputs wired, modules not
    FLAKE = FLAKE.replace(_ANCH, "        default = { imports = [ ./nix/modules/node.nix ./nix/modules/panel.nix ]; };")
    FLAKE = FLAKE.replace("        swg-node = { imports = [ ./nix/modules/node.nix _revModule ]; };",
                          "        swg-node = ./nix/modules/node.nix;")
    FLAKE = FLAKE.replace("        swg-panel = { imports = [ ./nix/modules/panel.nix _revModule ]; };",
                          "        swg-panel = ./nix/modules/panel.nix;")

print("[1] package.nix takes a rev and folds it into the version")
check("it accepts a `rev` argument", re.search(r"^, rev \? \"\"", PKG, re.M) is not None)
check("the version is base + rev when one is given",
      'version = baseVersion + lib.optionalString (rev != "") ("+" + rev);' in PKG)
check("the base still comes from the repo's VERSION file",
      'baseVersion = lib.fileContents (srcRoot + "/VERSION");' in PKG)

print("\n[2] the INSTALLED VERSION is the stamped one, not a copy of the repo file")
check("a stamped file is written", 'echo "$version" > VERSION.stamped' in PKG)
check("⚠️ with echo, never printf — a Nix '' string would keep the backslash",
      "printf '%s\\n' \"$version\" > VERSION.stamped" not in PKG)
check("no directory still installs the raw VERSION",
      not re.search(r"install -Dm644 VERSION\s+\$out", PKG), 
      [l.strip() for l in PKG.splitlines() if "install -Dm644 VERSION " in l])
n = len(re.findall(r"install -Dm644 VERSION\.stamped", PKG))
check("all three components get it (panel, sub, noded)", n == 3, n)

print("\n[3] the flake computes the rev, and tolerates having none")
check("shortRev with a dirty fallback and then \"\"",
      'buildRev = self.shortRev or (self.dirtyShortRev or "");' in FLAKE)
check("it lives in the `let` — the outputs attrset is not recursive",
      FLAKE.index("buildRev =") < FLAKE.index("    {\n"), "buildRev is defined after the attrset opens")

print("\n[4] ⚠️ IT REACHES THE MODULES — the path a NixOS config actually takes")
check("a _module.args carrier exists", "_module.args.swgBuildRev = buildRev;" in FLAKE)
for m in ("swg-node", "swg-panel", "default"):
    check("nixosModules.%s carries it" % m,
          re.search(r"%s = \{ imports = \[[^\]]*_revModule \]" % re.escape(m), FLAKE) is not None)
for name, src in MODS.items():
    check("%s accepts swgBuildRev with a default" % name, re.search(r"^, swgBuildRev \? \"\"", src, re.M) is not None)
    check("%s passes it to the package" % name,
          "default = pkgs.callPackage ../package.nix { rev = swgBuildRev; };" in src)
    check("%s no longer callPackages with no args" % name,
          "callPackage ../package.nix { };" not in src)

print("\n[5] the outputs are wired too (belt and braces, but not the load-bearing half)")
check("packages.<system> passes it", "pkgs.callPackage ./nix/package.nix { srcRoot = ./.; rev = buildRev; }" in FLAKE)
check("the overlay passes it", "final.callPackage ./nix/package.nix { srcRoot = ./.; rev = buildRev; }" in FLAKE)

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
