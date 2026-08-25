# The self-update rebuild, shared by services.swg-panel and services.swg-node.
#
# ⚠️ NOT a NixOS module — a plain function. It is called from each service module's `let` block, so
# there is one definition of what "update" means on a declarative host and no import-order or
# option-merge semantics to reason about. (Two modules that both defined the same unit would have
# to agree on every value or fail evaluation with a conflict the operator has to decode.)
#
# ── why this exists at all (docs/NIXOS-SUPPORT-PLAN.md D14) ──
# The panel never runs the updater. It touches a file, and a root unit decides what "update" means:
# bare-metal → `bootstrap.sh update`; docker → `compose pull && up` (a container cannot recreate
# itself — the same class of problem as this one, already solved this way); here → a rebuild.
# So the seam is already there and already used twice; this only fills in the third ExecStart.
#
# ── the one thing that cannot be worked around ──
# `nixos-rebuild` fails for reasons that have nothing to do with us: a broken unrelated input, an
# out-of-tree kernel module against a new kernel. Bare-metal's updater cannot fail that way. And it
# fails AFTER the process that asked for it has been restarted, so nothing in the daemon ever sees
# it. Hence `resultFile`: the verdict and the output tail are written where the panel or the node
# will read them, which is the difference between "the button is broken" and "your kernel pin needs
# bumping".
{ pkgs
, lib
  # A label for the generated script, so two of these on one host are distinguishable in the store.
, name
  # What to build. "" ⇒ plain `nixos-rebuild switch`, which uses whatever this system is configured
  # from. Otherwise a flake ref including its attribute, e.g. "/etc/nixos#myhost".
, flakeRef
  # Input names to refresh BEFORE rebuilding. Empty ⇒ the rebuild lands on whatever the lock already
  # pins, which is very often the version already running.
, updateInputs
  # Where the verdict goes, and the shape it takes: "host_proc" (the panel's own file: line 1 =
  # state, the rest = the failure tail) or "node" (.update-result, read and relayed by swg-noded).
, resultFile
, resultShape
  # user:group to hand the result file to, when the reader is not root. "" ⇒ leave it root-owned.
, resultOwner ? ""
  # Marks a trigger batch as handled, so the polling timer on the container arm cannot re-fire the
  # rebuild it just ran.
, stampFile
, triggerFile
}:

let
  # The flake DIRECTORY — everything before the `#`. `nix flake update` operates on the flake, not
  # on the output attribute, and passing the whole ref is an error rather than a no-op.
  flakeDir = lib.head (lib.splitString "#" flakeRef);
  localFlake = lib.hasPrefix "/" flakeDir;

  # ⚠️ Absolute paths out of the RUNNING system, not out of `pkgs`. `nixos-rebuild` must be the one
  # this machine is currently on — that is what knows how to switch it — and the attribute that
  # carries it in nixpkgs has moved (nixos-rebuild / nixos-rebuild-ng), so naming it here would make
  # this module's evaluation depend on which nixpkgs the operator pinned. /run/current-system/sw/bin
  # is present on every NixOS system by construction.
  nixosRebuild = "/run/current-system/sw/bin/nixos-rebuild";
  nixBin = "/run/current-system/sw/bin/nix";

  # The steps, as the operator would type them. `command` below is this same list — so the string
  # the panel SHOWS in the Update dialog is literally the thing the button RUNS, and the two cannot
  # drift into disagreeing about what an update is on this host.
  # A preflight, because selfUpdate.enable now defaults ON: the defaults assume the standard layout
  # the panel's snippet creates (a flake at /etc/nixos named after the host), and a host that differs
  # would otherwise fail on a raw `nix` error nobody can act on. Catch the common miss — no flake
  # where flakeRef points — and say what to do instead. `set -e` in the subshell turns the `exit 1`
  # into a reported update-failed carrying this text, which is exactly the actionable half the
  # resultFile exists for. A non-local flakeRef is fetched fresh and needs no such check.
  preflight = lib.optional localFlake ''
    if [ ! -e ${flakeDir}/flake.nix ]; then
      echo "swg self-update: this host has no flake at ${flakeDir}, so the panel cannot rebuild it here."
      echo "The Update button defaults to the layout the panel's config snippet creates. If yours differs:"
      echo "  • set services.swg-panel.selfUpdate.flakeRef (or services.swg-node.selfUpdate.flakeRef) to your flake, e.g. \"/path/to#attr\", or"
      echo "  • set selfUpdate.enable = false and run the command the Update dialog shows, by hand."
      exit 1
    fi
  '';

  steps = preflight
    ++ lib.optional (updateInputs != [ ] && localFlake)
      "${nixBin} flake update ${lib.concatStringsSep " " updateInputs} --flake ${flakeDir}"
    ++ [ "${nixosRebuild} switch${lib.optionalString (flakeRef != "") " --flake ${flakeRef}"}" ];

  # The human form drops the store prefixes (they are noise in a dialog) and carries a sudo per
  # step, because `sudo a && b` only elevates `a`.
  humanSteps =
    lib.optional (updateInputs != [ ] && localFlake)
      "sudo nix flake update ${lib.concatStringsSep " " updateInputs} --flake ${flakeDir}"
    ++ [ "sudo nixos-rebuild switch${lib.optionalString (flakeRef != "") " --flake ${flakeRef}"}" ];

  script = pkgs.writeShellScript "swg-rebuild-${name}" ''
    set -u
    PATH=/run/current-system/sw/bin:${lib.makeBinPath [ pkgs.coreutils ]}:$PATH
    export PATH

    # ⚠️ `nix flake update` is a `nix-command`, and it FAILS with "experimental Nix feature
    # 'nix-command' is disabled" on a host that has not turned those features on globally — which is
    # common, because `nixos-rebuild --flake` enables them for its OWN invocation and never needs the
    # global switch. So a flake-managed host can rebuild by hand all day and still have the panel's
    # Update button die on its first step. `nixos-rebuild` below is unaffected (it self-enables); this
    # env var carries the features to the standalone `nix` call without cluttering the command the
    # dialog shows. Found live: the button reported "updated", the lock never moved, and the panel
    # looped because the version was still behind.
    export NIX_CONFIG="extra-experimental-features = nix-command flakes"

    # Idempotence, for the polling timer the container arm needs (inotify does not cross a bind
    # mount, so a `.path` unit never sees the write a container makes to the trigger). Stamp BEFORE
    # rebuilding, never after: a rebuild restarts this very host's services, and a stamp written
    # afterwards would be missed by a run that was interrupted — which then loops for ever.
    if [ -e ${stampFile} ] && [ ! ${triggerFile} -nt ${stampFile} ]; then
      exit 0
    fi
    touch ${stampFile}

    LOG=$(mktemp) || exit 1
    rc=0
    # ⚠️ A SUBSHELL, not a brace group, and `set -e` rather than `|| exit $?` on each line. Both
    # halves are load-bearing and the first version had neither: `exit` inside `{ ...; }` exits the
    # SCRIPT, so the whole reporting block below was skipped and a failed rebuild reported nothing
    # at all — while the success path, which never reaches an `exit`, worked perfectly and made it
    # look correct. Caught by running it; the same bug class as `{ : > f; }` exiting dash, which
    # this project has already paid for once.
    (
      set -e
    ${lib.concatMapStringsSep "\n    " (c: "  ${c}") steps}
    ) > "$LOG" 2>&1 || rc=$?

    # 20 lines, like every other lifecycle failure this project reports. The tail is what carries
    # the actionable half — an unrelated input that will not fetch, a kernel module that will not
    # build — and it is the whole reason this script exists rather than a bare ExecStart.
    TAIL=$(tail -n 20 "$LOG" 2>/dev/null)
    rm -f "$LOG"

    if [ "$rc" -eq 0 ]; then STATE=updated; else STATE=update-failed; fi

    # A successful switch installs the new binaries but does NOT restart swg-noded — the daemon carries
    # `restartIfChanged = false` so an unrelated rebuild never drops the live datapath. An UPDATE is the
    # one case where that is wrong: the operator pressed Update expecting the node to RUN the new version,
    # and without this it keeps serving the old one until a reboot, with no prompt (the kernel-module hint
    # stays silent when the module is already loaded). So bounce it here. `try-restart` is a no-op where
    # there is no such unit — a panel-only host, or the container arm (its node is the backend-swg-node
    # container, recreated by the rebuild itself) — and the interfaces are kernel state that survives it,
    # so users are not dropped. Best-effort: a failed bounce must not fail an update that already landed.
    if [ "$rc" -eq 0 ]; then
      /run/current-system/sw/bin/systemctl try-restart swg-noded.service >/dev/null 2>&1 || true
    fi
    umask 027
    TMP=${resultFile}.tmp
    ${if resultShape == "host_proc" then ''
      # The panel's own marker: line 1 is the state, and anything after it is shown only for a
      # *-failed one. On success it writes the bare state with no trailing newline, exactly as
      # lib/common.sh's lc_emit_file does — the panel splits on the first newline either way, but
      # matching the existing writer means one format to reason about, not two.
      if [ "$rc" -eq 0 ]; then printf '%s' "$STATE" > "$TMP"
      else printf '%s\n%s\n' "$STATE" "$TAIL" > "$TMP"; fi
    '' else ''
      # swg-noded's relay file: same first-line-is-the-state shape, read and POSTed as a proc-status
      # on its next sync, then deleted.
      printf '%s\n%s\n' "$STATE" "$TAIL" > "$TMP"
    ''}
    ${lib.optionalString (resultOwner != "") ''
      # The reader is unprivileged and REWRITES this file itself later. Left root-owned, its next
      # write fails silently and the tag sticks for ever.
      chown ${resultOwner} "$TMP" 2>/dev/null || true
    ''}
    mv -f "$TMP" ${resultFile}
    exit "$rc"
  '';

  # ── Keep the rebuild from starving the box it runs on (found live) ──
  # `nixos-rebuild` EVALUATES a whole system before it builds one, and that evaluation is a single
  # long CPU-and-memory spike that runs inside THIS service's own cgroup (the daemon does the actual
  # package builds elsewhere, but a panel-only update barely builds anything — the eval is the cost).
  # On a small entry server — 2 CPU / ~2 GB, an ordinary node — an unconstrained run saturates both
  # cores and drives memory into reclaim, so sshd stops answering and the panel stops serving *for
  # the duration of the build*. Observed: one Update press took a 1.9 GB box down until it was
  # power-cycled. These make the rebuild yield rather than dominate, and this is the whole reason the
  # button is safe to default on:
  #   • Nice / CPUWeight / IOSchedulingClass — interactive work (sshd, the panel) always wins the
  #     scheduler and the disk, so the box stays reachable while it rebuilds.
  #   • OOMScoreAdjust — if memory runs out anyway, the kernel kills THIS first. That is precisely
  #     the safe outcome and not a regrettable one: a killed rebuild is atomic (the running system is
  #     untouched) and resultFile still reports the clean failure — never the panel or the daemon
  #     dying under it. The build volunteers as the victim so the services at the default score live.
  # It does not make a small box big enough to SUCCEED — that is the operator's swap/zram, which
  # nix/README recommends for <2 GB hosts — it makes the attempt unable to take the box down.
  resourceGuard = {
    Nice = 19;
    CPUWeight = 20;
    IOSchedulingClass = "idle";
    OOMScoreAdjust = 900;
  };

in
{
  inherit script;
  command = lib.concatStringsSep " && " humanSteps;
  # Surfaced so each module can assert on it rather than re-deriving the rule.
  inherit localFlake;
  # The systemd hardening that keeps the rebuild from starving its own host — merged into each
  # arm's swg-update serviceConfig, so there is one definition of "an update must not take the box
  # down" exactly as there is one definition of what an update IS.
  inherit resourceGuard;
}
