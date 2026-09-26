#!/usr/bin/env bash
# uninstall.sh — interactive, component-by-component remover for swg-panel.
#
# Detects every installed entity on this box — the bare-metal panel, a bare-metal node,
# a Docker deployment, AmneziaWG, WireGuard, and EACH installed turn-proxy server — lists
# them, then loops through and asks "uninstall or keep?" for each one. Nothing is removed
# without a yes. Run as root. --dry-run prints the plan and changes nothing; --yes assumes
# yes to every component (still asks the destructive sub-questions unless those are preset).
set -uo pipefail   # not -e: an uninstaller should keep going even if a piece is gone

DRYRUN=false; ASSUME_YES=false
for a in "$@"; do case "$a" in --dry-run) DRYRUN=true;; -y|--yes) ASSUME_YES=true;; esac; done

c(){ printf '\033[%sm' "$1"; }
info(){ echo "$(c '38;5;39')▸$(c 0) $*"; }   # universal flags: ▸ light-blue, :: blue, ✓ green, ! brown, ✗ red
sub(){  echo "$(c '38;5;33')::$(c 0) $*"; }
ok(){   echo "$(c '0;32')✓$(c 0) $*"; }
warn(){ echo "$(c '38;5;130')!$(c 0) $*" >&2; }
die(){  echo "$(c '0;31')✗ $*$(c 0)" >&2; exit 1; }
b(){ printf '\033[1m%s\033[0m' "$*"; }
run(){ if $DRYRUN; then echo "    [dry] $*"; else "$@"; fi; }
rmrf(){ local p; for p in "$@"; do if [ -e "$p" ] || [ -L "$p" ]; then run rm -rf "$p"; fi; done; }
# Drop a directory only once nothing is left in it. Used where a `rm -rf` would take a file this run
# deliberately KEPT — a foreign interface's .conf and its keys living in the same directory as ours.
rmdir_if_empty(){ local d="$1"
  [ -d "$d" ] || return 0
  if [ -n "$(ls -A "$d" 2>/dev/null)" ]; then
    $DRYRUN && echo "    [dry] keeping $d (still holds files this run did not remove)" \
            || info "  keeping $(b "$d") — it still holds files this run did not remove"
    return 0
  fi
  run rmdir "$d"
}
# ufw_forget <record-file> — delete EXACTLY the ufw rules our installer recorded opening (install-host.sh's
# serve_internal writes one `<port>/tcp` per line, only for a rule it actually ADDED — never for one ufw already had,
# which is somebody else's). A rule opened by an installer older than that record cannot be told from the operator's
# own, so it is named, not deleted. No record + no ufw = nothing to do.
ufw_forget(){ local f="$1" r p
  command -v ufw >/dev/null 2>&1 || return 0
  if [ -f "$f" ]; then
    while IFS= read -r r; do
      case "$r" in [0-9]*/tcp) ;; *) continue;; esac
      run sh -c "ufw delete allow '$r' >/dev/null 2>&1" && info "  removed the ufw rule 'allow $r' the installer added"
    done < "$f"
    return 0
  fi
  p="$(sed -n 's/^PORT=//p' "$(dirname "$f")/install.conf" 2>/dev/null | head -1)"
  [ -n "$p" ] && grep -q '^SERVE_MODE=internal$' "$(dirname "$f")/install.conf" 2>/dev/null \
    && ufw show added 2>/dev/null | grep -qx "ufw allow $p/tcp" \
    && info "  ufw still allows $p/tcp — an older installer opened it for the panel; if nothing else needs it: ufw delete allow $p/tcp"
  return 0; }
# ask_yn <prompt> <default> <outvar>  — preset outvar (env) or --yes skips the prompt
ask_yn(){ local v p="$1" d="${2:-n}"
  # A PRESET answer (unattended run) is normalised exactly like a typed one. It used to be returned verbatim, so
  # the obvious FOO=y — the same letter the prompt offers as "Y/n" — was compared against "yes", didn't match, and
  # silently meant NO: an unattended uninstall with PANEL_DATA_DEL=y kept the data it was told to delete.
  if [ -n "${!3:-}" ]; then case "${!3}" in [Yy]*) printf -v "$3" yes;; *) printf -v "$3" no;; esac; return; fi
  # …and so is the DEFAULT taken when there is no terminal. Same defect as the preset path above, one branch
  # down: this wrote the raw letter, so a default of `y` became "y", every consumer compares against "yes",
  # and each keep-by-default question silently answered NO. An unattended uninstall therefore DELETED the
  # interface keys + peers it promises to keep (DOCKER_KEEP_CONFS, KNODE) and left the containers it took an
  # interface over from switched off (RESTORE_CTRS) — the exact "no server at all" state that prompt exists
  # to avoid. Normalise it the same way a typed answer is normalised.
  if ! { true </dev/tty; } 2>/dev/null; then case "$d" in [Yy]*) printf -v "$3" yes;; *) printf -v "$3" no;; esac; return; fi
  read -rp "$p ($([ "$d" = y ] && echo 'Y/n' || echo 'y/N')): " v </dev/tty || true
  v="${v:-$d}"; case "$v" in [Yy]*) printf -v "$3" yes;; *) printf -v "$3" no;; esac; echo; }   # one trailing blank after the prompt
# ask_comp <label> — the per-component yes/no (honours --yes); returns 0 = uninstall
# ⚠️ `--yes` MEANS "YES TO EVERY SWG COMPONENT", NOT "yes to somebody else's data". A component marked
# never-auto is always typed: --yes does not answer it, and with no terminal it is KEPT. That is the whole
# protection for an interface swg never created — the one thing in this list that is not ours to delete.
ask_comp(){ local v verb="${3:-Uninstall}" noauto="${4:-}"
  if [ "$noauto" = never-auto ]; then
    if ! { true </dev/tty; } 2>/dev/null; then info "Kept — this one is never decided unattended. Re-run from a terminal to choose."; return 1; fi
  elif $ASSUME_YES; then return 0; fi
  if ! { true </dev/tty; } 2>/dev/null; then return 1; fi   # no usable tty, not --yes => keep
  read -rp "  $verb $(b "$1")${2:+  ($(c '0;90')$2$(c 0))}? (y/N): " v </dev/tty || true
  case "$v" in [Yy]*) return 0;; *) return 1;; esac; }

[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && info "DRY RUN — nothing will be changed."

DOCKER_DIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"
TURN_DIR="${TURN_DIR:-/opt/vk-turn-proxy}"
WDTT_DIR="${WDTT_DIR:-/opt/swg-wdtt}"     # WDTT servers: per-instance config-dir (identity + passwords) + .bin/<fork> shared binaries
CSQTT_DIR="${CSQTT_DIR:-/opt/swg-csqtt}"  # csqtt servers: per-instance config-dir (password store) + .bin/<arch> shared binary
# BOTH paths a shared record can live at. swg-noded keeps its three run-model-independent records (turn-proxy /
# wdtt / csqtt) in the node state dir now — the one directory every run-model shares — and /etc/swg-agent only so
# a rollback to an older build still finds one. Removing a component while leaving the state-dir copy behind is
# not tidy-up left undone: the node reads that record on its next start and RE-INSTALLS the instance just removed,
# with a fresh identity. This file deliberately does not source lib/common.sh, so the pair is spelled out here.
rec_paths(){ printf '%s %s\n' "${SWG_NODED_STATE:-/var/lib/swg-noded}/$1" "/etc/swg-agent/$1"; }
SD="${SYSTEMD_DIR:-/etc/systemd/system}"   # overridable for testing

# A declaratively managed host (NixOS and friends) keeps /etc/systemd/system as a read-only symlink
# into its store. Every `systemctl disable --now` below then fails — and this script deliberately
# runs `set -uo pipefail` WITHOUT -e, so it would walk past the failure and delete /opt/swg-* and
# /var/lib/swg-* WHILE THE SERVICES KEPT RUNNING. Measured on a read-only unit dir: disable exits 1
# with "Access denied", `--now` never reaches the stop, and the unit stays active+enabled. A partial,
# destructive uninstall is worse than refusing, so refuse.
#
# `[ -w ]` is NOT enough: for root it reports the mode bits and ignores a read-only mount. Probe with
# a real write.
unit_dir_writable(){ local p="$SD/.swg-uninstall-probe.$$"
  ( : > "$p" ) 2>/dev/null || return 1; rm -f "$p"; return 0; }
# ⚠️ …AND THAT PROBE ANSWERS "COULD *I* WRITE HERE", WHICH IS A DIFFERENT QUESTION. As a non-root
# `--dry-run` — which the root check above deliberately allows — it fails on EVERY ordinary systemd host,
# because /etc/systemd/system is root-owned everywhere. Answering the DECLARATIVE question from it told an
# ordinary Ubuntu user their host was NixOS, and made the `--dry-run` that same root check offers
# unreachable for the only people who need it. So below, the probe is trusted only where it means
# something — as root — and otherwise the host has to say so itself, which this asks without needing any
# privilege at all:
unit_dir_immutable(){   # would a unit written here be unable to stick, whoever we are?
  [ -e /etc/NIXOS ] && return 0
  grep -qsE '^ID="?nixos"?[[:space:]]*$' /etc/os-release && return 0
  # The MOUNT says so. `findmnt --target` answers for the RESOLVED path, which is the point: on a
  # declarative host $SD is a symlink into an immutable store, and it is the store's mount that is `ro`,
  # not the symlink. Measured: `rw,relatime,…` on Ubuntu, `ro,nosuid,nodev,relatime` on NixOS.
  local o=""
  command -v findmnt >/dev/null 2>&1 && o="$(findmnt -no OPTIONS --target "$SD" 2>/dev/null)"
  if [ -z "$o" ]; then   # no findmnt, or it could not answer: longest matching mount point in /proc/mounts
    local rp; rp="$(readlink -f "$SD" 2>/dev/null || echo "$SD")"
    o="$(awk -v p="$rp/" 'BEGIN{best=0}
           { mp=$2; if (mp != "/") mp=mp"/"
             if (index(p, mp)==1 && length(mp)>=best) { best=length(mp); opt=$4 } }
           END{ print opt }' "${PROC_MOUNTS:-/proc/mounts}" 2>/dev/null)"
  fi
  case ",$o," in *,ro,*) return 0 ;; esac
  return 1
}
# A DRY RUN refuses too, unlike the installers'. There the exemption earns its keep — a dry run shows what the
# bare-metal install WOULD lay down, which is worth seeing on a box you are migrating off. Nothing equivalent is
# true of an uninstaller: the plan it printed here described deleting the node's interfaces and purging its
# packages, and signed off with "re-run without --dry-run to apply" — an instruction that then refuses. A plan
# for an operation that cannot happen is not a preview, it is a wrong answer, and it reads as "this tool handles
# NixOS". The refusal below already names the paths to remove by hand, which is the only thing the plan could
# honestly have offered.
if [ -d "$SD" ] && ! unit_dir_writable && { [ "$(id -u)" = 0 ] || unit_dir_immutable; }; then
  # Name NixOS when it IS NixOS. The generic message below is right about the mechanism and useless
  # about the next action: on a declarative host the operator's move is an edit and a rebuild, and
  # the two things they will otherwise trip on — which options to turn off, and that a node removed
  # this way never signs off — are exactly what an uninstaller is expected to tell them.
  if [ -e /etc/NIXOS ] || grep -qsE '^ID="?nixos"?[[:space:]]*$' /etc/os-release; then
    die "NixOS detected — this uninstaller must not run here.
    Every \`systemctl disable --now\` below fails on a read-only unit directory, and this script
    keeps going without -e, so it would delete /opt/swg-* and /var/lib/swg-* while every service
    kept running.

    Turn them off in the configuration that declares them, and rebuild:
        services.swg-panel.enable = false;   # and/or services.swg-node.enable = false;
    Then remove whatever state you no longer want: /var/lib/swg-panel, /var/lib/swg-noded,
    /etc/swg-panel, /etc/amnezia/amneziawg.
    A node removed this way never signs off, so the panel keeps showing it — delete it there too.
    See nix/README.md (\"Removing a node\")."
  fi
  # Says what was OBSERVED, not what was concluded from it. Reaching here means either we are root and a
  # real write failed, or the mount itself reports `ro` — "read-only" was a guess in the first case.
  die "cannot write to $SD, so nothing here could be disabled — either this host's services are managed
    declaratively (NixOS?), or the directory sits on a read-only mount.
    Remove the swg services from your system configuration and rebuild instead. Running this
    uninstaller here would delete /opt/swg-* and /var/lib/swg-* while every service kept running."
fi
# docker data-dir fate — decided up front, applied after teardown. `:-` so an UNATTENDED run's preset survives:
# a bare ="" clobbered the caller's DOCKER_DATA_DEL=y before ask_yn ever read it, so the data dir it was told to
# delete was kept — the same silent-preset class as the [Yy] normalisation in ask_yn, one layer further out.
DOCKER_DATA_DEL="${DOCKER_DATA_DEL:-}"; DOCKER_KEEP_CONFS="${DOCKER_KEEP_CONFS:-}"
# This box's own panel address as its install recorded it — read NOW, before rm_panel / rm_docker_* remove the files
# that say so. _url_is_this_box (below) uses it to recognise a node that signs off to the panel on this very box.
_OWN_PANEL_HOST="$(sed -n 's/^PANEL_DOMAIN=//p' /etc/swg-panel/install.conf "$DOCKER_DIR/.env" 2>/dev/null | head -1 \
                   | tr -d '"' | sed -e 's#^[A-Za-z]*://##' -e 's#[/:].*##')"
DOMAIN=""
[ -f /etc/nginx/sites-available/swg-panel.conf ] && \
  DOMAIN="$(sed -n 's/[[:space:]]*server_name[[:space:]]\+\([^;]*\);.*/\1/p' /etc/nginx/sites-available/swg-panel.conf | head -n1 | tr -d ' ')"

# ───────────────────────── removal actions ─────────────────────────
REMOVED_PANEL=false; REMOVED_NODE=false

rm_panel(){
  info "Removing swg-panel (control panel)"
  # ASKED FIRST: what "keep the data" keeps decides the acme renewal and /etc/swg-panel below, not only the roster.
  # Default NO = keep it for a future re-install (matches the docker data-dir prompt); yes = wipe it.
  local PANEL_DATA_DEL="${PANEL_DATA_DEL:-}" _kept=""
  ask_yn "  Delete the panel's data — /var/lib/swg-panel (users, peers, nodes) and /etc/swg-panel (its login, certificate and address)?" n PANEL_DATA_DEL
  if [ -e $SD/swg-panel-server.service ]; then run systemctl disable --now swg-panel-server; fi
  # swg-sub (the subscription surface) is a companion of the panel — remove it alongside
  if [ -e $SD/swg-sub.service ]; then run systemctl disable --now swg-sub; fi
  # swg-netctl (the panel's privileged network/TLS helper: .service + .path + .timer) — a companion of the panel.
  # ⚠️ BOTH FAMILIES, exactly as rm_netctl does. The standalone netctl component is offered ONLY when there is
  # no bare panel ("rm_panel would otherwise sweep them"), so this sweep is the only thing that reaps them on a
  # box that has one — and it listed just the bare trio. A box carrying leftover swg-netctl-docker.* from an
  # earlier conversion therefore kept them through an uninstall, with the .path waiting and the .timer RUNNING,
  # polling a queue for a panel that no longer existed. Measured on a bare-metal master: 4 swg units survived.
  # ⚠️ …BUT THE DOCKER FAMILY ONLY WHEN NO DOCKER PANEL IS LEFT. A box can carry both panels (guard_second_panel parks
  # one beside the other), and there swg-netctl-docker.* is not a leftover — it is the LIVE docker panel's address
  # helper. Removing the bare panel took it anyway: the docker panel kept running with nothing to carry out its address
  # changes (1.8.8 qualification, R8). rm_docker_panel removes it with the docker panel; rm_netctl, the same test.
  for _nc in swg-netctl.path swg-netctl.timer swg-netctl.service; do
    run systemctl disable --now "$_nc" 2>/dev/null || true; done   # unguarded — disabling something already gone is harmless
  docker_running swg-panel || for _nc in swg-netctl-docker.path swg-netctl-docker.timer swg-netctl-docker.service; do
    run systemctl disable --now "$_nc" 2>/dev/null || true; done
  # ⚠️ `.service.d` FOR swg-netctl TOO — the two beside it already reap theirs, and this is the ONE unit
  # here that actually gets a drop-in written: `update.sh`'s `ensure_acme_home` pins LE_WORKING_DIR into
  # `swg-netctl.service.d/acme-home.conf`, because acme.sh otherwise follows $HOME and the helper has none.
  # Left behind, the drop-in outlives the unit AND the install — measured on a scratch box: uninstall, then
  # a fresh install from nothing, and `systemctl show -p Environment swg-netctl` still carried the OLD
  # install's LE_WORKING_DIR, from a file written nine minutes before the unit above it. A drop-in
  # OVERRIDES the unit, so the day a new install canonicalises a different store the stale pin wins — and
  # worse, `ensure_acme_home` skips its heal when it finds any LE_WORKING_DIR in that directory, so the
  # residue suppresses the very correction that would fix it. ([[acme-store-split-and-arms]])
  rmrf $SD/swg-panel-server.service $SD/swg-panel-server.service.d $SD/swg-sub.service $SD/swg-sub.service.d \
       $SD/swg-netctl.service $SD/swg-netctl.service.d $SD/swg-netctl.path $SD/swg-netctl.timer /usr/local/bin/swg-netctl \
       /var/lib/swg-netctl
  docker_running swg-panel || rmrf $SD/swg-netctl-docker.service $SD/swg-netctl-docker.path $SD/swg-netctl-docker.timer /usr/local/bin/swg-netctl-docker
  rm_updater_if_last bare-gone   # the one-click updater: shared with a docker install, so it goes only with the last of them
  # ⚠️ A DANGLING ENABLEMENT SYMLINK OUTLIVES ITS UNIT FILE, and `systemctl disable` CANNOT clear it: it
  # reads [Install] from the FRAGMENT to learn which symlinks to drop, so once the fragment is gone the link
  # in multi-user.target.wants/ is orphaned and systemd reports that name for ever as "not-found inactive
  # dead" — a swg unit no uninstall can remove. Observed on a bare-metal master, left by an earlier partial
  # removal. Delete ours by name, and only where the target is genuinely gone.
  for _l in "$SD"/*.wants/swg-*.service "$SD"/*.wants/swg-*.path "$SD"/*.wants/swg-*.timer; do
    { [ -L "$_l" ] && [ ! -e "$_l" ]; } && rmrf "$_l"
  done
  run systemctl daemon-reload
  rmrf /etc/nginx/sites-enabled/swg-panel.conf /etc/nginx/sites-available/swg-panel.conf \
       /etc/nginx/conf.d/swg-panel.conf /etc/nginx/.htpasswd-swg
  command -v nginx >/dev/null 2>&1 && { run nginx -t && run systemctl reload nginx || warn "reload nginx manually if it's running"; }
  # ⚠️ TWO FAULTS LIVED IN THIS BLOCK, one aimed outward and one inward.
  # (1) NEIGHBOUR SAFETY. `--remove` ran unconditionally on whatever domain we were installed under, so
  #     uninstalling US stopped the renewal of a certificate something else on this box may still serve
  #     under the same name (an nginx vhost, another panel). Only ever touch an entry that actually
  #     installs into OUR cert paths — the same test prune_stale_acme_installs uses.
  # (2) `--remove` DROPS THE RENEWAL CONF AND KEEPS THE KEY ("You can remove them by yourself"), and that
  #     stranded key makes the domain un-reissuable: a later re-install stops at "Domain key exists, do you
  #     want to overwrite it? ... add '--force'" instead of reaching the CA, and it cannot heal itself,
  #     because Le_Keylength is written only on a successful key creation and the conf is now gone. So an
  #     uninstall+reinstall — the exact thing an operator does when something looks wrong — left a box that
  #     could never issue a certificate again. Drop the directory, don't just deregister it.
  if [ -n "$DOMAIN" ] && [ "$DOMAIN" != "_" ]; then
    local _acme="" _a _h _conf _dom _rp _dir
    for _a in /root/.acme.sh/acme.sh "${HOME:-/root}/.acme.sh/acme.sh" "$(command -v acme.sh 2>/dev/null || true)"; do
      [ -n "$_a" ] && [ -x "$_a" ] && { _acme="$_a"; break; }
    done
    # every store this box might keep, including the stray /.acme.sh a HOME-less helper used to write
    for _h in /root/.acme.sh "${HOME:-/root}/.acme.sh" /.acme.sh; do
      [ -d "$_h" ] || continue
      for _conf in "$_h"/*/*.conf; do
        [ -f "$_conf" ] || continue
        _dom="$(sed -n "s/^Le_Domain='\{0,1\}\([^']*\).*/\1/p" "$_conf" | head -1)"
        [ "$_dom" = "$DOMAIN" ] || continue
        _rp="$(sed -n "s/^Le_RealFullChainPath='\{0,1\}\([^']*\).*/\1/p" "$_conf" | head -1)"
        case "$_rp" in /etc/swg-panel/tls/*|/etc/swg-sub/tls/*) ;;
          *) warn "keeping the acme entry for $DOMAIN in $_h — it installs into ${_rp:-somewhere else}, so it is not ours to remove"; continue;; esac
        _dir="$(dirname "$_conf")"
        # a KEPT certificate keeps its renewal: the re-install serves the same certificate and never re-issues it
        [ "$PANEL_DATA_DEL" = yes ] || { info "Kept acme.sh's renewal of $DOMAIN — the certificate stays with the panel's data"; continue; }
        info "Removing acme.sh renewal for $DOMAIN (it installs into $_rp)"
        case "$_dir" in *_ecc) [ -n "$_acme" ] && run "$_acme" --home "$_h" --remove -d "$DOMAIN" --ecc || true;;
                        *)     [ -n "$_acme" ] && run "$_acme" --home "$_h" --remove -d "$DOMAIN" || true;; esac
        rmrf "$_dir"
      done
      # …and the residue of an issuance that never succeeded: a key with no certificate, which carries no
      # conf to identify it by, and which is exactly what would trap the next install.
      _dir="$_h/${DOMAIN}_ecc"
      if [ -d "$_dir" ] && ! { [ -s "$_dir/fullchain.cer" ] && head -1 "$_dir/${DOMAIN}.cer" 2>/dev/null | grep -q 'BEGIN CERTIFICATE'; }; then
        info "Removing a failed acme entry for $DOMAIN in $_h (a domain key with no certificate)"
        rmrf "$_dir"
      fi
    done
  fi
  ufw_forget /etc/swg-panel/ufw-added   # the ports the installer opened close with the panel, kept data or not
  # /usr/local/bin/swg-passwd is the panel's login-reset helper (install-host.sh) — it outlived every uninstall.
  rmrf /opt/swg-panel /opt/swg-sub /var/www/wgstats /var/www/acme /usr/local/bin/swg-passwd
  if [ "$PANEL_DATA_DEL" = yes ]; then rmrf /var/lib/swg-panel /etc/swg-panel /etc/swg-sub   # /etc/swg-sub = swg-sub's OWN tls dir
  else
    # ⚠️ KEEPING THE DATA KEEPS THE PANEL, not only its roster. /etc/swg-panel went with every uninstall — the login,
    # the TLS certificate and key, install.conf — so the re-install minted a new certificate and every node pinned to
    # the old one stopped syncing ("tls fingerprint mismatch") until its own installer was re-run; an Enter-through
    # re-install also moved the panel to the default-route address, minted a new login name and renamed its node
    # (1.8.8 qualification, round 4). The Docker path always kept them (data/etc). Kept here too: the re-install then
    # finds its own login, certificate, address and node name and comes back as the same panel. Secrets that are not
    # its identity still go: stored client configs, the panel's ssh dir, the Cloudflare tokens in install.conf (the
    # Docker path strips the same from .env), and the ufw record whose rules were removed just above.
    rmrf /var/lib/swg-panel/.ssh /var/lib/swg-panel/configs /etc/swg-panel/ufw-added
    [ -f /etc/swg-panel/install.conf ] && run sed -i -E 's/^(CF_TOKEN|CF_ORIGIN_TOKEN)=.*/\1=/' /etc/swg-panel/install.conf
    _kept=""; [ -d /var/lib/swg-panel ] && _kept="/var/lib/swg-panel (users, peers, nodes)"
    [ -d /etc/swg-panel ] && _kept="${_kept:+$_kept and }/etc/swg-panel (its login, certificate and address)"
    [ -n "$_kept" ] && ok "Kept $_kept — a re-install comes back as this same panel, and its nodes keep syncing"
  fi
  # Hand any KEPT state back to root BEFORE the users go. State deliberately outlives an uninstall, and a
  # deleted user leaves its files holding a numeric uid that belongs to nobody — which `useradd -r` then
  # reissues to whichever service account is created first on the next install. That is how a panel ended up
  # unable to read its own 0600 session.key (the sub user had inherited the old panel's uid), signing cookies
  # with a throwaway secret and logging every operator out on each restart. root owns nothing by accident.
  for _sd in /var/lib/swg-panel /var/lib/swg-noded /etc/swg-panel /etc/swg-sub; do   # the key too: its group goes below
    [ -d "$_sd" ] && run chown -R root:root "$_sd" 2>/dev/null || true
  done
  if id swgpanel >/dev/null 2>&1; then run userdel swgpanel; fi
  if id swgsub >/dev/null 2>&1; then run userdel swgsub; fi   # swg-sub's dedicated read-only user
  REMOVED_PANEL=true; ok "swg-panel removed"
}

# Tell the panel this node is going away (the "goodbye" signal) so it removes itself cleanly —
# using the node's own bearer token + panel URL from its config. Best-effort: if the panel is
# unreachable, the operator can Force-remove it from the Nodes screen instead.
# _goodbye_post <panel-url> <token> <verify:yes|no> — POST the node's bearer token to /api/node/goodbye
_goodbye_post(){
  local url="$1" tok="$2" verify="$3"
  [ -n "$url" ] && [ -n "$tok" ] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  # ⚠️ NOT ON A DRY RUN. This POST is not a `run` — it went out for real from `--dry-run`, and the panel acted on it:
  # measured on a bare master (1.8.8 qualification, q1), the dry run flagged its node "uninstalled" and logged
  # "Node uninstalled — kept for re-install"; for a node the operator had marked for removal, a received sign-off
  # COMPLETES that removal, peers and all. A dry run describes the sign-off; it never sends one.
  if $DRYRUN; then echo "    [dry] sign off from the panel ($url)"; return 0; fi
  info "Signing off from the panel…"
  # ⚠️ THE REASON COMES BACK ON STDOUT, INTO THE ONE LINE BELOW — never printed raw. A refused connection printed
  # python's own `<urlopen error [Errno 111] Connection refused>` above the friendly warning (1.8.8 qualification),
  # and a rejected token a bare "HTTP 401" — and then "Couldn't reach the panel" about a panel that had answered.
  local _why _rc
  _why="$(python3 - "$url" "$tok" "$verify" <<'PY'
import ssl, sys, http.client, urllib.request
url = sys.argv[1].rstrip("/") + "/api/node/goodbye"; tok = sys.argv[2]; verify = sys.argv[3] == "yes"
ctx = ssl.create_default_context()
if not verify:                                 # self-signed / pinned panel: don't verify for the goodbye
    ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request(url, data=b"{}", method="POST",
                             headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json",
                                      "User-Agent": "swg-noded"})   # urllib's default Python-urllib UA gets 403'd by some WAFs
# The panel removes the node when it RECEIVES the request (node_remove runs before the reply), so a
# truncated/5xx response from a proxy in front still means it landed. exit 0 = clean, 2 = uncertain
# (got an error response, node probably dropped), 1 = never reached the panel.
try:
    r = urllib.request.urlopen(req, timeout=10, context=ctx)
    try: r.read()
    except http.client.IncompleteRead: pass
    sys.exit(0)
except ConnectionResetError:
    # Covers http.client.RemoteDisconnected, which subclasses it. The panel removes the node BEFORE it
    # replies (see the note above), so a connection closed with no status line is the same "it landed"
    # case as the IncompleteRead handled just above, one step earlier. It was falling through to the
    # generic handler and reporting "never reached the panel" — while the panel's own event log recorded
    # 'Node uninstalled — kept for re-install'. Sending the operator to remove a node that is already
    # gone is worse than saying nothing.
    sys.exit(2)
except urllib.error.HTTPError as e:
    if e.code in (200, 404): sys.exit(0)        # removed / already gone
    if 500 <= e.code <= 599: sys.exit(2)        # proxy/gateway error — request reached the panel, node likely dropped
    print("HTTP %s" % e.code); sys.exit(3)      # 401 etc — it answered, and rejected it: not removed
except Exception as e:
    r = getattr(e, "reason", None) or e         # a URLError carries the socket error as its reason
    r = str(getattr(r, "strerror", None) or r or type(r).__name__)
    print(r[:1].lower() + r[1:]); sys.exit(1)   # "connection refused", "timed out", "name or service not known"
PY
)"; _rc=$?
  case $_rc in
    0) ok "Panel notified — your peers are KEPT for a re-install (re-enroll with the same token to restore them). To purge for good, use Nodes → remove in the panel.";;
    2) warn "The panel closed the connection without a reply — it almost certainly ACTIONED the sign-off (it removes the node before responding). Check the Nodes screen to confirm.";;
    3) warn "The panel turned the sign-off down (${_why:-rejected}); the node will just go offline there (your peers are kept). Remove it from the Nodes screen if you want it gone.";;
    *) warn "Couldn't reach the panel${_why:+ ($_why)}; the node will just go offline there (your peers are kept). Remove it from the Nodes screen if you want it gone.";;
  esac
}
# ⚠️ NOBODY LEFT TO TELL. A node whose panel is THIS box's own (a master's co-located node dials http://127.0.0.1:8088)
# signs off to a panel this same run may already have removed — the components go panel first — so the bare-metal
# master's uninstall ended its node removal with "Couldn't reach the panel; the node will just go offline there", about
# a panel that no longer exists (1.8.8 qualification, q1). The docker path skipped this case already; both now ask the
# same two things. Skipped ONLY when no panel of either method is left on the box: "uninstall the node, keep the panel"
# still signs off, so that panel shows it Uninstalled — and a bare node beside a DOCKER panel (or the reverse) still
# reaches it at the same loopback address, which the docker path's container-only test used to skip.
_url_is_this_box(){ local h="${1#*://}"; h="${h%%/*}"
  case "$h" in \[*) h="${h#\[}"; h="${h%%\]*}";; *) h="${h%%:*}";; esac   # drop the port (an IPv6 host is bracketed)
  [ -n "$h" ] || return 1
  case "$h" in swg-panel|localhost|127.*|::1) return 0;; esac
  [ -n "${_OWN_PANEL_HOST:-}" ] && [ "$h" = "$_OWN_PANEL_HOST" ] && return 0
  # a here-string, not a pipe into grep -q: under pipefail an early match SIGPIPEs the producer and reads as "no"
  grep -qxF -- "$h" <<< "$(ip -o addr show 2>/dev/null | awk '{print $4}' | cut -d/ -f1; hostname -I 2>/dev/null | tr ' ' '\n')"; }
_panel_left_here(){ [ -f "$SD/swg-panel-server.service" ] || docker_running swg-panel; }
_goodbye_nobody(){ [ -n "$1" ] && _url_is_this_box "$1" && ! _panel_left_here; }
_goodbye_skipped(){ info "No sign-off to send: this node's panel was this box's own, and it is gone now (removed in this run) — nobody is left to tell."; }
# bare-metal node — read the panel URL + token from its config.json
node_goodbye(){
  local cfg=/etc/swg-agent/config.json
  [ -f "$cfg" ] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  local url tok verify
  url="$(python3 -c 'import json,sys;print((json.load(open(sys.argv[1])).get("panel") or {}).get("url",""))' "$cfg" 2>/dev/null)"
  tok="$(python3 -c 'import json,sys;print((json.load(open(sys.argv[1])).get("panel") or {}).get("token",""))' "$cfg" 2>/dev/null)"
  verify="$(python3 -c 'import json,sys;print("yes" if (json.load(open(sys.argv[1])).get("panel") or {}).get("verify",True) else "no")' "$cfg" 2>/dev/null)"
  _goodbye_nobody "$url" && { _goodbye_skipped; return 0; }
  _goodbye_post "$url" "$tok" "$verify"
}
# docker node — the token + panel URL live in the deployment .env (config.json is inside the container)
docker_node_goodbye(){
  local env="$DOCKER_DIR/.env"; [ -f "$env" ] || return 0
  local url tok verify
  url="$(sed -n 's/^PANEL_URL=//p' "$env" | head -1)"; url="${url%\"}"; url="${url#\"}"
  tok="$(sed -n 's/^NODE_TOKEN=//p' "$env" | head -1)"; tok="${tok%\"}"; tok="${tok#\"}"
  verify="$(sed -n 's/^TLS_VERIFY=//p' "$env" | head -1)"; verify="${verify%\"}"; verify="${verify#\"}"
  [ "$verify" = yes ] || verify=no
  # A panel-only install has NO node: its .env carries the placeholder NODE_TOKEN=set-in-nodes-screen (compose
  # interpolates every service), and a files cleanup on such a box said "No sign-off to send: this node's panel was
  # this box's own…" about a node it never had (1.8.8 qualification, q5). Nothing to sign off, nothing to say.
  [ "$tok" = set-in-nodes-screen ] && return 0
  # A co-located master's node signs off to its OWN panel — skipped when no panel is left to hear it (see above).
  _goodbye_nobody "$url" && { _goodbye_skipped; return 0; }
  _goodbye_post "$url" "$tok" "$verify"
}
# POST proc-status (best-effort) — flashes a red "uninstalling" tag on the panel the moment teardown starts.
_proc_post(){  # <url> <token> <verify> <state>
  local url="$1" tok="$2" verify="$3" state="$4"
  { [ -n "$url" ] && [ -n "$tok" ] && command -v python3 >/dev/null 2>&1; } || return 0
  $DRYRUN && return 0   # a dry run tells the panel nothing (see _goodbye_post)
  python3 - "$url" "$tok" "$verify" "$state" <<'PY' 2>/dev/null || true
import ssl, sys, json, urllib.request
url = sys.argv[1].rstrip("/") + "/api/node/proc-status"; tok = sys.argv[2]; verify = sys.argv[3] == "yes"; state = sys.argv[4]
ctx = ssl.create_default_context()
if not verify: ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request(url, data=json.dumps({"state": state}).encode(), method="POST",
                             headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json", "User-Agent": "swg-noded"})
try: urllib.request.urlopen(req, timeout=6, context=ctx).read()
except Exception: pass
PY
}
docker_node_uninstalling(){   # red "uninstalling" tag while a docker node tears down (token/URL from the .env)
  local env="$DOCKER_DIR/.env"; [ -f "$env" ] || return 0
  local url tok verify
  url="$(sed -n 's/^PANEL_URL=//p' "$env" | head -1)"; url="${url%\"}"; url="${url#\"}"
  tok="$(sed -n 's/^NODE_TOKEN=//p' "$env" | head -1)"; tok="${tok%\"}"; tok="${tok#\"}"
  verify="$(sed -n 's/^TLS_VERIFY=//p' "$env" | head -1)"; verify="${verify%\"}"; verify="${verify#\"}"; [ "$verify" = yes ] || verify=no
  [ "$tok" = set-in-nodes-screen ] && return 0   # the panel-only placeholder is not a node's token (docker_node_goodbye)
  _proc_post "$url" "$tok" "$verify" uninstalling
}

# Containers we took an interface over from — see the restore at the end of the run. config.json is the
# authoritative record, but on a DOCKER node it lives inside the node container and is gone after a recreate,
# so swg-noded also mirrors the map into its state dir, which is a bind mount the host can always read. Read
# both and dedupe: whichever exists wins, and a container named twice is started once.
adopted_ctrs(){ # adopted_ctrs <config.json> <adopted-containers.json>
  python3 - "$1" "$2" 2>/dev/null <<'PYADOPT' || true
import json, sys
out = []
try:
    with open(sys.argv[1]) as f:
        for _i, v in (json.load(f).get("interfaces") or {}).items():
            if isinstance(v, dict) and v.get("adopted_from"):
                out.append(v["adopted_from"])
except Exception:
    pass
try:
    with open(sys.argv[2]) as f:
        d = json.load(f)
    if isinstance(d, dict):
        out += [v for v in d.values() if isinstance(v, str) and v]
except Exception:
    pass
seen = set()
for c in out:
    if c and c not in seen:
        seen.add(c)
        print(c)
PYADOPT
}
# Append to the run-wide list (a box can carry a bare-metal AND a docker node), keeping it unique.
capture_adopted(){ local _n
  _n="$(adopted_ctrs "$1" "$2")"
  [ -n "$_n" ] && ADOPTED_CTRS="$(printf '%s\n%s\n' "${ADOPTED_CTRS:-}" "$_n" | awk 'NF && !seen[$0]++')"
  return 0; }

rm_node(){
  info "Removing swg-node (bare-metal entry server)"
  node_goodbye   # signal the panel before we tear down the config it needs
  # ⚠️ THE RELAY'S DIVERT COMES DOWN BEFORE ANYTHING ELSE, AND BEFORE THE RELAY ITSELF. A tproxy rule whose
  # relay has been uninstalled is not a leftover, it is a BLACKHOLE: the kernel takes those packets out of
  # the forwarding path and nothing is left on the box that would ever remove the rule. nft half first, then
  # the routing half, exactly as swg-noded's own disarm does it.
  run sh -c 'nft delete table inet swg_relay >/dev/null 2>&1 || true'
  run sh -c 'n=0; while [ $n -lt 4 ] && ip rule del fwmark 0x9c40 lookup 6990 2>/dev/null; do n=$((n+1)); done; true'
  run sh -c 'ip route flush table 6990 >/dev/null 2>&1 || true'
  run sh -c 'for u in $(systemctl list-units --all --plain --no-legend "swg-relay@*.service" 2>/dev/null | awk "{print \$1}"); do systemctl disable --now "$u" >/dev/null 2>&1 || true; done'
  # ⚠️ THE SLICE IS A UNIT TOO, and it was the one thing this block left behind — `swg-relay.slice` stayed
  # on disk and ACTIVE after a full uninstall, so a box that had removed swg still had an swg unit loaded.
  # It is written beside `swg-relay@.service` by the node (`RELAY_SLICE`), so it comes off beside it.
  # Found by checking what a completed uninstall actually left, 1.8.5 qualification.
  run systemctl stop swg-relay.slice 2>/dev/null || true
  rmrf $SD/"swg-relay@.service" $SD/swg-relay.slice /etc/swg-panel/relay
  if [ -e $SD/swg-noded.service ]; then run systemctl disable --now swg-noded; fi
  run systemctl unmask dnsmasq 2>/dev/null || true   # install masked the distro dnsmasq (node ran its own); restore it
  rmrf $SD/swg-noded.service $SD/swg-noded.service.d; run systemctl daemon-reload
  # An interface TAKEN OVER from somebody else's container came with a promise: their server keeps serving, just
  # from here instead. Uninstalling ends that — we delete the interface further down — and the container it came
  # from is still stopped with restart=no, exactly as the take-over left it. Removing swgPanel then leaves the
  # operator with NO server at all: ours gone, theirs disabled and never told to come back. Capture the pairs now,
  # while the record still exists; the restore itself is deferred to the end of the run, past the interface
  # removal, or their container would come back to a port ours is still holding.
  capture_adopted /etc/swg-agent/config.json /var/lib/swg-noded/adopted-containers.json
  # The panel's system mesh links go with the node that carried them — they are not peer interfaces and
  # are never offered as a separate question. Before the agent config is deleted, so `swg_owns` still has
  # something to read for everything else.
  info "  removing the panel's system mesh links"
  remove_ifaces /etc/amnezia/amneziawg awg-quick mesh
  remove_ifaces /etc/wireguard        wg-quick  mesh
  rmrf /opt/swg-agent /opt/swg-noded /srv/swg-queue /var/log/swg-agent /var/lib/swg-noded /var/lib/swg-recovery /etc/sudoers.d/swg-agent
  rmrf /etc/swg-agent   # turn-proxy.json here is just a panel-facing record; a kept turn-proxy keeps running
  # The AppArmor grant the installer added so the wg CLI could read userspace interface sockets is a
  # policy change we made to this box, so it goes back when we do. It lives INSIDE a file the
  # distribution and the operator may also write in, so only the span between our own two markers is
  # cut — never the file — and the profile is reloaded so the removal actually takes effect.
  # ⚠️ TWIN: these two markers are lib/common.sh's APPARMOR_LOCAL_BEGIN/_END, spelled out because
  # this file deliberately does not source it (see the note at the top). Change one, change both.
  for _aal in /etc/apparmor.d/local/*; do
    [ -f "$_aal" ] && grep -qsF '# --- swgPanel: userspace WireGuard datapaths (begin) ---' "$_aal" || continue
    # ⚠️ UNCONDITIONAL, AND BEFORE THE KEEP QUESTIONS BELOW. The grant is a policy change we made to
    # this box, so it goes back when we do — but an operator who then KEEPS a WDTT/csqtt server or a
    # userspace awg interface is left with a running datapath whose socket the wg CLI can no longer
    # read. Nothing of ours reads it once the node is gone, so the removal stands; it is said out loud
    # rather than left to be discovered.
    info "  reverting the swgPanel AppArmor grant in $_aal (a kept userspace server's socket becomes unreadable by the wg CLI)"
    run sed -i '/# --- swgPanel: userspace WireGuard datapaths (begin) ---/,/# --- swgPanel: userspace WireGuard datapaths (end) ---/d' "$_aal"
    _aap="/etc/apparmor.d/$(basename "$_aal")"
    [ -f "$_aap" ] && command -v apparmor_parser >/dev/null 2>&1 && run apparmor_parser -r "$_aap" 2>/dev/null || true
  done
  for u in swgpush swgagent; do if id "$u" >/dev/null 2>&1; then run userdel -r "$u"; fi; done
  # NOT rm_node_netobjects here. This runs FIRST in the component list, while "keep my interfaces / turn-proxies /
  # WDTT servers" are offered later and default to keep — and those objects are their datapath. A kept WDTT server
  # runs with -no-nat, so its SNAT is precisely the swg-egress:<iface> rule this would delete: the server survives
  # the uninstall with no internet for any of its clients. Deferred to the end of the run, past every prompt.
  NEED_NETOBJ_SWEEP=true
  REMOVED_NODE=true; ok "swg-node removed"
}

# swg-panel and swg-node are SEPARATE containers — remove each on its own. The shared
# deployment dir / network / images / data are only torn down once BOTH are gone.
docker_running(){ command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$1"; }
_rm_node_data(){  rmrf "$DOCKER_DIR/data/node" "$DOCKER_DIR/data/node-confs"; }      # node-only state + iface confs
_rm_panel_data(){ rmrf "$DOCKER_DIR/data/etc" "$DOCKER_DIR/data/lib" "$DOCKER_DIR/data/stats"; }  # login/roster/certs
ask_full_data_fate(){   # the LAST swg container is going → decide the WHOLE data dir up front (before teardown)
  local desc=""
  [ -d "$DOCKER_DIR/data/lib" ] && desc="login, roster (users+peers), "
  [ -d "$DOCKER_DIR/data/etc" ] && desc="${desc}nodes, certs, "
  [ -d "$DOCKER_DIR/data/node-confs" ] && desc="${desc}interface configs / peers, "
  [ -d "$DOCKER_DIR/data/node/wdtt" ] && desc="${desc}WDTT identities + passwords, "   # same irrecoverable weight as the bare-metal /opt/swg-wdtt question
  [ -d "$DOCKER_DIR/data/node/csqtt" ] && desc="${desc}csqtt password stores, "        # csqtt has no keypair — the store IS what its clients authenticate against
  desc="${desc%, }"; [ -n "$desc" ] || desc="state"
  ask_yn "  Delete the data dir $DOCKER_DIR/data ($desc)?" n DOCKER_DATA_DEL
  DOCKER_KEEP_CONFS="${DOCKER_KEEP_CONFS:-}"      # keep a preset; only defined-ness is needed under set -u
  if [ "$DOCKER_DATA_DEL" = yes ] && [ -d "$DOCKER_DIR/data/node-confs" ]; then
    ask_yn "  Keep at least the peers? Leaves data/node-confs (keys + peers) so a future install can re-onboard them." y DOCKER_KEEP_CONFS
  fi
}
apply_full_data_fate(){   # run AFTER teardown, using the decision captured by ask_full_data_fate
  if [ "$DOCKER_DATA_DEL" != yes ]; then
    # KEEP .env so a plain `docker node` re-install recovers NODE_TOKEN / PANEL_URL on its own (peers re-sync
    # and the re-install lifecycle shows) — without it the box has no key and stays stuck "Uninstalled". Strip
    # panel secrets so no plain password is left at rest; compose + binaries are re-staged by the installer anyway.
    [ -f "$DOCKER_DIR/.env" ] && run sed -i -E '/^(PANEL_PASSWORD|CF_TOKEN|CF_ORIGIN_TOKEN|ACME_EMAIL)=/d' "$DOCKER_DIR/.env"
    rmrf "$DOCKER_DIR/docker-compose.yml" "$DOCKER_DIR/Dockerfile" "$DOCKER_DIR/Dockerfile.node" \
         "$DOCKER_DIR/.dockerignore" "$DOCKER_DIR/VERSION" "$DOCKER_DIR/docker" "$DOCKER_DIR/vendor" \
         "$DOCKER_DIR/swg-panel-server" "$DOCKER_DIR/swg-agent" "$DOCKER_DIR/swg-noded" \
         "$DOCKER_DIR/index.html" "$DOCKER_DIR/app.css" "$DOCKER_DIR/app.js" "$DOCKER_DIR/reconcile.js" \
         "$DOCKER_DIR/js"
    # Say what that .env still holds. A panel-only install has no node token — its NODE_TOKEN is the placeholder
    # set-in-nodes-screen — and "(node token)" named a key the box never had (1.8.8 qualification, q5).
    local _tok _held="" _env=""
    if [ -f "$DOCKER_DIR/.env" ]; then
      _tok="$(sed -n 's/^NODE_TOKEN=//p' "$DOCKER_DIR/.env" | head -1)"; _tok="${_tok%\"}"; _tok="${_tok#\"}"
      case "$_tok" in ""|set-in-nodes-screen) ;; *) _held="node token";; esac
      { [ -d "$DOCKER_DIR/data/lib" ] || [ -d "$DOCKER_DIR/data/etc" ]; } && _held="${_held:+$_held, }the panel's address and ports"
      _env=" + .env${_held:+ ($_held)}"
    fi
    ok "Kept $DOCKER_DIR/data$_env for a future reinstall"
    return
  fi
  # CASES 2 & 3 — wiping the live data dir: first stash a recovery copy (node token + interface keys) under
  # $DOCKER_DIR.uninstalled-<ts> so a future re-install can recover this node from the leftover-identity list
  # (its peers re-sync from the panel). Panel / TLS secrets are stripped from the copy.
  # ⚠️ NOT WHEN THE RUN WAS TOLD TO KEEP NONE. With ARCHIVES_DEL=y preset (an unattended wipe) the copy was made,
  # announced as "kept for re-install", and deleted a minute later by the archive sweep at the end of this run.
  local _saved=no
  case "${ARCHIVES_DEL:-}" in [Yy]*)
    [ -f "$DOCKER_DIR/.env" ] && info "  no recovery copy saved — ARCHIVES_DEL=y asks for none to be kept (this node cannot be recovered from this box)";;
  *) if [ -f "$DOCKER_DIR/.env" ]; then
    _bak="$DOCKER_DIR.uninstalled-$(date +%Y%m%d-%H%M%S 2>/dev/null || echo bak)"
    run mkdir -p "$_bak/data"
    run cp -a "$DOCKER_DIR/.env" "$_bak/.env"
    [ -d "$DOCKER_DIR/data/node-confs" ] && run cp -a "$DOCKER_DIR/data/node-confs" "$_bak/data/node-confs"
    [ -d "$DOCKER_DIR/data/node" ] && run cp -a "$DOCKER_DIR/data/node" "$_bak/data/node"   # swg-noded state incl. turn-proxy.json → turn-proxies re-create on recovery
    run sed -i -E '/^(PANEL_PASSWORD|CF_TOKEN|CF_ORIGIN_TOKEN|ACME_EMAIL)=/d' "$_bak/.env"
    info "  saved a recovery copy (node token + interface keys + turn-proxies) to $(b "$_bak") — re-install and pick it from the recovery list"
    _saved=yes; RUN_ARCHIVES="${RUN_ARCHIVES:-} $_bak"
  fi;;
  esac
  if [ "$DOCKER_KEEP_CONFS" = yes ]; then
    # CASE 2 — keep the peers (interface server keys) LIVE so existing client configs keep working
    run sh -c "find '$DOCKER_DIR' -mindepth 1 -maxdepth 1 ! -name data -exec rm -rf {} + 2>/dev/null; find '$DOCKER_DIR/data' -mindepth 1 -maxdepth 1 ! -name node-confs ! -name node -exec rm -rf {} + 2>/dev/null"
    ok "Kept $DOCKER_DIR/data/node-confs (peers) + node (turn-proxies) live$([ "$_saved" = yes ] && printf '; token recoverable from the backup')"
  else
    # CASE 3 — wipe everything live; full recovery (token + interface keys) is in the backup
    rmrf "$DOCKER_DIR"
    ok "Removed $DOCKER_DIR$([ "$_saved" = yes ] && printf ' — a recovery copy (token + interface keys) is kept for re-install')"
  fi
}
# The compose project's own networks (swg-panel-docker_default + its br-… bridge). `compose down` drops them only when
# it runs — and a docker panel removed while its node stays, or a stack whose containers went one by one, never gets
# one, so the network outlived the uninstall (1.8.8 qualification). By the project's label, so nothing else's network
# is touched; docker refuses while anything is still attached, so a container that stays is never cut off.
docker_rm_project_networks(){
  command -v docker >/dev/null 2>&1 || return 0
  local _nw
  for _nw in $(docker network ls -q --filter "label=com.docker.compose.project=$(basename "$DOCKER_DIR")" 2>/dev/null); do
    run sh -c "docker network rm '$_nw' >/dev/null 2>&1 || true"
  done; }
# The ONE-CLICK UPDATER — swg-update, swg-update-check, swg-update.{service,path,timer} and the stamp — is one set of
# files that a bare-metal panel (install-host.sh's mk_update_unit) and a docker install of any profile
# (install-docker.sh's wire_host_updater) both write, at the same paths, reading the same trigger list. So it belongs
# to whichever of them is still here, and goes only with the last: a bare panel, or a swg-panel / swg-node container.
# Each remover used to take it with ITSELF — on a box carrying both panels, removing the parked bare one left the live
# docker panel's Update button writing a trigger that nothing read, and removing the docker one did the same to the
# bare one (1.8.8 qualification, R8). $1 = bare-gone: this run is removing the bare panel right now, so it does not
# count even while a dry run leaves its files where they are.
rm_updater_if_last(){
  if { [ "${1:-}" != bare-gone ] && { [ -d /opt/swg-panel ] || [ -f "$SD/swg-panel-server.service" ]; }; } \
     || docker_running swg-panel || docker_running swg-node; then return 0; fi
  for _su in swg-update.timer swg-update.path; do run systemctl disable --now "$_su" 2>/dev/null || true; done
  rmrf "$SD/swg-update.service" "$SD/swg-update.path" "$SD/swg-update.timer" /usr/local/bin/swg-update \
       /usr/local/bin/swg-update.new /usr/local/bin/swg-update-check /var/lib/swg-update.stamp
  run systemctl daemon-reload 2>/dev/null || true
}
docker_cleanup_if_last(){   # shared bits (network/images/data dir) — only once NO swg container remains
  if docker_running swg-panel || docker_running swg-node; then return 0; fi
  rm_updater_if_last   # the host one-click updater — unless a bare-metal panel on this box still uses it
  if command -v docker >/dev/null 2>&1; then
    local DC=""; if docker compose version >/dev/null 2>&1; then DC="docker compose"; elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"; fi
    # activate every profile so `down` stops profile-gated services too (swg-sub); plain `down` skips them and --remove-orphans won't (it's in the compose file, not an orphan)
    [ -n "$DC" ] && [ -f "$DOCKER_DIR/docker-compose.yml" ] && run sh -c "cd '$DOCKER_DIR' && COMPOSE_PROFILES=host,master,node,host-node $DC down --remove-orphans >/dev/null 2>&1 || true"   # drop the network + any straggler
    docker_rm_project_networks   # …and the network itself when `down` could not (see above)
    local RMI="${REMOVE_DOCKER_IMAGES:-}"; echo; ask_yn "  Remove the pulled swg-panel / swg-node images too?" n RMI
    # ⚠️ BY REPOSITORY, NOT BY TAG. This named `:latest` explicitly, which was every box until
    # SWG_IMAGE_TAG started reaching existing installs — a box pinned to `sha-<short>` then kept every
    # image it had, while the uninstaller reported having removed them. Measured on a pinned box: six
    # images, 1.5 GB, still present after an uninstall that was told REMOVE_DOCKER_IMAGES=y.
    [ "$RMI" = yes ] && run sh -c 'docker images --format "{{.Repository}}:{{.Tag}}" 2>/dev/null \
        | grep -E "^(ghcr\.io/sanityprotocol/swg-(panel|node)|swg-panel-docker-swg-(panel|node)):" \
        | xargs -r docker rmi >/dev/null 2>&1 || true'
  fi
  apply_full_data_fate
}
rm_docker_panel(){ info "Removing Docker panel container (swg-panel)"
  # ⚠️ INHERIT THE PRESET. `local DELP=""` unconditionally SHADOWED any environment answer, so ask_yn
  # saw an empty variable, fell through to its default (n) and an unattended run KEPT the panel data it
  # was told to delete — silently, while printing "Kept the panel data". Exactly the defect ask_yn's own
  # comment documents for the preset path, one layer up, and `local RMI="${REMOVE_DOCKER_IMAGES:-}"`
  # three lines below is the same idea done right. Same question as the bare-metal path, same variable.
  local DELP="${PANEL_DATA_DEL:-}"
  if docker_running swg-node; then    # node stays → only the panel's OWN data is in play (decide now)
    ask_yn "  Delete the panel data (login, roster (users+peers), nodes, certs)? The node's interface configs are kept." n DELP
  else ask_full_data_fate; fi         # panel is the last container → the whole data dir
  run sh -c 'docker rm -f swg-panel swg-sub >/dev/null 2>&1 || true'   # swg-sub is the panel's companion surface (a profile-gated service `down` won't stop) — remove it alongside
  docker_rm_project_networks   # the panel + sub were the network's only members (a node runs on host networking)
  # …and its host-side address helper (install-docker.sh's wire_docker_netctl). It was left for a separate
  # "(leftover helper)" question, which also listed it as a leftover while this very panel was still running.
  for _nc in swg-netctl-docker.path swg-netctl-docker.timer swg-netctl-docker.service; do
    [ -e "$SD/$_nc" ] && run systemctl disable --now "$_nc" 2>/dev/null || true
  done
  rmrf "$SD/swg-netctl-docker.service" "$SD/swg-netctl-docker.service.d" "$SD/swg-netctl-docker.path" "$SD/swg-netctl-docker.timer" /usr/local/bin/swg-netctl-docker
  run systemctl daemon-reload 2>/dev/null || true
  if docker_running swg-node; then
    [ "$DELP" = yes ] && { _rm_panel_data; info "  Removed the panel data; node interface configs untouched."; } \
                      || info "  Kept the panel data; node interface configs untouched."
  else docker_cleanup_if_last; fi     # applies the data-dir decision captured above
  ok "swg-panel container removed"; }
rm_docker_node(){  info "Removing Docker node container (swg-node)"
  docker_node_uninstalling   # flash a red "uninstalling" tag on the panel before we tear down
  local KNODE="${DOCKER_KEEP_CONFS:-}"   # same shadowing bug as DELP above — inherit, do not blank
  if docker_running swg-panel; then   # master/panel stays → only the NODE's own data is in play (decide now)
    ask_yn "  Keep the node's interface configs (peers)? Leaves data/node-confs so a future install can re-onboard them." y KNODE
  else ask_full_data_fate; fi         # node is the last container → the whole data dir
  # capture the node's interface names FROM THE CONTAINER first — the ./data/node-confs bind mount can be empty,
  # and a host-networking node creates its wg/awg netdevs in the HOST namespace (they survive `docker rm`), so we
  # need the names to delete the leftover host interfaces below (else the next install hits "awg0 already exists").
  local _ifn _n _c
  _ifn="$(docker exec swg-node sh -c 'for d in /etc/amnezia/amneziawg /etc/wireguard; do ls "$d"/*.conf 2>/dev/null; done' 2>/dev/null | sed 's#.*/##; s#\.conf$##' | tr '\n' ' ')"
  [ -n "$_ifn" ] || _ifn="$(for _c in "$DOCKER_DIR/data/node-confs/"*.conf; do [ -f "$_c" ] && basename "$_c" .conf; done | tr '\n' ' ')"
  # Same debt the bare-metal node owes (see rm_node): an interface taken over from somebody else's container
  # left that container stopped with restart=no. Read the mirror off the bind-mounted state dir, and — for a
  # take-over that predates the mirror — the container's own config.json while it is still up to be asked.
  _acfg="$(mktemp 2>/dev/null || echo /tmp/swg-adopted.$$)"
  docker exec swg-node cat /etc/swg-agent/config.json >"$_acfg" 2>/dev/null || : >"$_acfg"
  capture_adopted "$_acfg" "$DOCKER_DIR/data/node/adopted-containers.json"
  rm -f "$_acfg"
  run sh -c 'docker rm -f swg-node >/dev/null 2>&1 || true'
  run sh -c 'ids=$(docker ps -aq --filter name=swg-turn- 2>/dev/null); [ -n "$ids" ] && docker rm -f $ids >/dev/null 2>&1 || true'   # this node's turn-proxy containers
  docker_node_goodbye                 # sign off AFTER the container is stopped — else its next 5s sync re-reports and clears the panel's "Uninstalled" tag (leaving it merely "offline")
  # delete the leftover HOST-namespace wg/awg netdevs the (host-networking) node created
  for _n in $_ifn; do [ -n "$_n" ] || continue
    command -v ip >/dev/null 2>&1 && ip link show "$_n" >/dev/null 2>&1 || continue
    awg-quick down "$_n" >/dev/null 2>&1 || wg-quick down "$_n" >/dev/null 2>&1 || true   # clean teardown if it can
    ip link delete dev "$_n" >/dev/null 2>&1 || true                                      # ALWAYS force-delete (down may exit 0 without removing it)
    info "  removed leftover host interface $(b "$_n")"; done
  if docker_running swg-panel; then
    [ "$KNODE" = yes ] && info "  Kept $DOCKER_DIR/data/node-confs (peers re-onboardable); panel data untouched." \
                       || { _rm_node_data; info "  Removed the node's interface configs; panel data untouched."; }
  else docker_cleanup_if_last; fi     # applies the data-dir decision captured above
  # Same deferred sweep the bare-metal rm_node arms. A docker node given host networking (or one that force-removed
  # an interface, so wg-quick PostDown never ran) leaves its iptables/nft/ipset objects in the HOST namespace, where
  # nothing else reclaims them; without this the docker path swept nothing at all.
  NEED_NETOBJ_SWEEP=true
  ok "swg-node container removed"; }
rm_docker_files(){ info "Removing the Docker deployment files ($DOCKER_DIR)"
  # This component can run without rm_docker_node ever firing, so it owes the same debt: a container we took
  # an interface over from is still stopped with restart=no. Capture before anything is torn down.
  capture_adopted /dev/null "$DOCKER_DIR/data/node/adopted-containers.json"
  # The dir-based component doesn't go through rm_docker_node/panel, so tear down ANY swg container here too
  # (incl. compose's "<id>_swg-node" recreate-backups, which is why the node sometimes isn't detected by name).
  ( cd "$DOCKER_DIR" 2>/dev/null && { docker compose down --remove-orphans >/dev/null 2>&1 || docker-compose down --remove-orphans >/dev/null 2>&1; } ) || true
  docker_rm_project_networks
  for _p in swg-node swg-panel swg-turn-; do docker ps -aq -f "name=$_p" 2>/dev/null | xargs -r docker rm -f >/dev/null 2>&1 || true; done
  docker_node_goodbye   # sign off AFTER the container is gone (no further sync clears the panel's "Uninstalled")
  ask_full_data_fate; apply_full_data_fate; rmrf /var/lib/swg-recovery; ok "Docker deployment files removed"; }

down_ifaces(){ local dir="$1" tool="$2" f n              # quietly bring each interface down (wg/awg-quick is noisy)
  for f in "$dir"/*.conf; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"
    $DRYRUN && { echo "    [dry] $tool down $n"; continue; }
    { command -v "$tool" >/dev/null 2>&1 && "$tool" down "$n"; ip link delete "$n"; } >/dev/null 2>&1 || true; done; }
# Down each interface + delete its .conf, printing ONE green ✓ line (name · address · port) — used by the
# peer-removal components (down_ifaces above is the quiet, no-display version used before purging a package).
remove_ifaces(){ local dir="$1" tool="$2" want="${3:-own}" f n addr port
  for f in "$dir"/*.conf; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"
    _iface_pick "$n" "$want" || continue
    addr="$(awk -F= 'tolower($1)~/address/{gsub(/[ \t]/,"",$2);split($2,a,",");print a[1];exit}' "$f" 2>/dev/null)"
    port="$(awk -F= 'tolower($1)~/listenport/{gsub(/[ \t]/,"",$2);print $2;exit}' "$f" 2>/dev/null)"
    if $DRYRUN; then echo "    [dry] down + disable ${tool}@$n + remove $n"
    else { command -v "$tool" >/dev/null 2>&1 && "$tool" down "$n"; ip link delete "$n"; } >/dev/null 2>&1 || true
      # DISABLE the unit instance, not just `down` it. Without this the enable symlink in
      # multi-user.target.wants survives the conf it points at, and once the wg/awg package is removed too
      # there is no unit file behind it either — systemd then reports `wg-quick@<n>.service not-found failed`
      # for ever and tries again on every boot. A full uninstall left 36 of these on a test box. swg-agent
      # already disables the instance on its own delete/stop paths; this is the same call, in the uninstaller.
      run systemctl disable "${tool}@$n" >/dev/null 2>&1 || true
      rm -f "$f"; fi
    printf '    %s✓ %s%s%s%s\n' "$(c '0;32')" "$n" "$(c 0)" "${addr:+ · $addr}" "${port:+ · :$port}"
  done; }

# Peers (the interface .conf files) and the wg/awg PACKAGE are removed INDEPENDENTLY — so you can wipe the
# panel + peers but KEEP the wg/awg service installed (or remove the package but keep the configs). Each is
# its own component in the list, so the peer question is always asked regardless of the package answer.
# `rmdir_if_empty`, never `rm -rf`, because a FOREIGN .conf may still be sitting in this directory —
# kept on purpose by the operator, or kept because nothing could establish whose it was.
rm_awg_peers(){
  info "Removing AmneziaWG interface configs (peers)"
  remove_ifaces /etc/amnezia/amneziawg awg-quick own
  rmdir_if_empty /etc/amnezia/amneziawg
}
rm_awg_foreign(){
  info "Removing the AmneziaWG interfaces that are NOT swg's"
  remove_ifaces /etc/amnezia/amneziawg awg-quick foreign
  rmdir_if_empty /etc/amnezia/amneziawg
}
# ⚠️ SAY WHAT ACTUALLY HAPPENED. These printed their ✓ unconditionally, so a purge that failed — and
# apt fails for an ordinary reason, another apt holding /var/lib/dpkg/lock-frontend — still reported
# "WireGuard package removed" AND listed it under Removed: in the summary. Measured on hel-flux
# 2026-09-08: both wireguard packages still `ii` after a run that claimed to have removed them. The
# error text was right there on screen, contradicted two lines later by the verdict.
rm_awg_pkg(){
  info "Uninstalling the AmneziaWG package (kernel module + tools)"
  down_ifaces /etc/amnezia/amneziawg awg-quick      # if the configs were kept, bring the ifaces down before pulling the module
  if command -v apt-get >/dev/null 2>&1; then
    if run apt-get purge -y amneziawg amneziawg-tools amneziawg-dkms; then
      run add-apt-repository -y --remove ppa:amnezia/ppa; run apt-get autoremove -y
      ok "AmneziaWG package removed"
    else
      NOT_DONE+=("AmneziaWG package (kernel module + tools)")
      warn "apt could not purge the AmneziaWG packages (see the error above) — they are STILL INSTALLED. Re-run once apt is free."
    fi
  else warn "Non-apt system — remove the amneziawg packages with your package manager."; fi
}
rm_wg_peers(){
  info "Removing WireGuard interface configs (peers)"
  remove_ifaces /etc/wireguard wg-quick own
  rmdir_if_empty /etc/wireguard
}
rm_wg_foreign(){
  info "Removing the WireGuard interfaces that are NOT swg's"
  remove_ifaces /etc/wireguard wg-quick foreign
  rmdir_if_empty /etc/wireguard
}
rm_wg_pkg(){
  info "Uninstalling the WireGuard package"
  down_ifaces /etc/wireguard wg-quick
  if command -v apt-get >/dev/null 2>&1; then
    if run apt-get purge -y wireguard wireguard-tools; then run apt-get autoremove -y; ok "WireGuard package removed"
    else
      NOT_DONE+=("WireGuard package (kernel module + tools)")
      warn "apt could not purge the WireGuard packages (see the error above) — they are STILL INSTALLED. Re-run once apt is free."
    fi
  else warn "Non-apt system — remove the wireguard packages with your package manager."; fi
}
rm_netctl(){   # a leftover swg-netctl (e.g. after a docker convert) with no bare panel around to sweep it up
  info "Removing swg-netctl (leftover helper)"
  # BOTH families: the bare-metal swg-netctl.* and the docker helper swg-netctl-docker.*. The docker pair was
  # invisible to every uninstall — the detection globbed swg-netctl.* , which needs a literal dot and so never
  # matched swg-netctl-docker.service — leaving an ACTIVE .timer polling a queue for a panel that was gone.
  # ⚠️ …but only a family whose panel is GONE (asked now, after the panel components ran): a docker panel that is
  # still here — kept by this run — keeps its own helper, and a bare panel likewise.
  if [ ! -d /opt/swg-panel ] && [ ! -f $SD/swg-panel-server.service ]; then
    for _nc in swg-netctl.path swg-netctl.timer swg-netctl.service; do
      [ -e "$SD/$_nc" ] && run systemctl disable --now "$_nc" 2>/dev/null || true   # one at a time: a multi-unit disable aborts wholesale on the first missing unit
    done
    rmrf $SD/swg-netctl.service $SD/swg-netctl.service.d $SD/swg-netctl.path $SD/swg-netctl.timer /usr/local/bin/swg-netctl
  fi
  if ! docker_running swg-panel; then
    for _nc in swg-netctl-docker.path swg-netctl-docker.timer swg-netctl-docker.service; do
      [ -e "$SD/$_nc" ] && run systemctl disable --now "$_nc" 2>/dev/null || true
    done
    rmrf $SD/swg-netctl-docker.service $SD/swg-netctl-docker.service.d $SD/swg-netctl-docker.path $SD/swg-netctl-docker.timer /usr/local/bin/swg-netctl-docker
  fi
  run systemctl daemon-reload; ok "swg-netctl removed"
}
# Host-side remnants of a DOCKER or converted install that no container remover owns: swg-sub's own tls dir and its
# systemd drop-in (written by the bare-metal install, survived the convert), and the node sysctl drop-in. Removing
# these also arms the datapath sweep — this is the "re-run this uninstaller" the sweep message promises.
rm_leftovers(){
  info "Removing leftover swg files (docker/converted install)"
  for _u in swg-sub.service; do [ -e "$SD/$_u" ] && run systemctl disable --now "$_u" 2>/dev/null || true; done
  # + the rest of what the BARE install laid down and a bare→docker convert leaves behind (teardown_bare_panel moves
  # the panel's state aside but not these): its stats dir, the login-reset helper, and a ufw rule it opened — whose
  # record the convert carried into the docker data (or into the moved-aside /etc/swg-panel.converted-*).
  rmrf /etc/swg-sub /opt/swg-sub "$SD/swg-sub.service" "$SD/swg-sub.service.d" /usr/local/bin/swg-sub \
       /var/www/wgstats /usr/local/bin/swg-passwd
  # Left alone while a docker panel runs, which changes nothing: Docker publishes its ports past ufw (its own nat and
  # FORWARD rules, never ufw's INPUT chain), so this rule never governed the port that panel serves.
  if ! docker_running swg-panel; then
    for _uf in "$DOCKER_DIR/data/etc/ufw-added" /etc/swg-panel.converted-*/ufw-added; do [ -f "$_uf" ] && ufw_forget "$_uf"; done
  fi
  # ⚠️ AND THE RELAY UNITS, for the box the FIX CANNOT REACH. `rm_node` learned to remove swg-relay.slice,
  # but `rm_node` only runs when a node component is still detected — so a box uninstalled by an older
  # build keeps an ACTIVE slice for ever, and re-running the new uninstaller walks straight past it. This
  # component is the one that runs when nothing owns the remnants, which is exactly that box's situation.
  # Idempotent and safe beside rm_node: both stop the same units, and stopping a stopped slice is a no-op.
  for _u in swg-relay.slice; do [ -e "$SD/$_u" ] && run systemctl stop "$_u" 2>/dev/null || true; done
  rmrf "$SD/swg-relay@.service" "$SD/swg-relay.slice" /etc/swg-panel/relay
  run systemctl daemon-reload
  # Service identities the pre-convert BARE install created. rm_panel/rm_node own these, and neither runs on a
  # docker-only box, so they outlived the uninstall — leaving swgpanel + group swg on a box with no swg on it.
  # Same -r split as the owners use (swgpush/swgagent carry a home dir; swgpanel/swgsub do not).
  # ⚠️ ASKED AT RUN TIME, NOT AT DETECTION. This component is listed after the docker ones, so by now they have been
  # removed or kept. A docker install still HERE keeps them (it is not ours to orphan); one removed with its data KEPT
  # no longer blocks them — that box kept every bare-era identity and file for good (1.8.8 qualification) — and its
  # kept data is handed to root first, as rm_panel does, so a uid freed here cannot be reissued to a new service user
  # that then owns it.
  if docker_running swg-panel || docker_running swg-node; then
    info "  keeping the service users — a docker install is still on this box"
  else
    [ -d "$DOCKER_DIR/data" ] && run chown -R root:root "$DOCKER_DIR/data" 2>/dev/null || true
    for _su in swgpanel swgsub; do id "$_su" >/dev/null 2>&1 && run userdel "$_su" 2>/dev/null || true; done
    for _su in swgpush swgagent; do id "$_su" >/dev/null 2>&1 && run userdel -r "$_su" 2>/dev/null || true; done
    REMOVED_LEFTOVERS=true    # lets the shared group cleanup at the end run for a docker/converted box too
  fi
  NEED_NETOBJ_SWEEP=true
  ok "leftover swg files removed"
}
# A KEPT PANEL THAT WAS PARKED FOR THE ONE THIS RUN REMOVED IS STARTED AGAIN. It was stopped for one reason only — two
# panels would answer at one address — and with the other gone that reason is gone too. Left stopped, the box had no
# panel at all while the summary said "Kept: Bare-metal swg-panel" (1.8.8 qualification, R8: nothing answered on its
# ports). Started rather than explained, because keeping a component means keeping it working (the take-over restore
# above does the same) and the operator who kept it has nothing left to decide; its one-click updater is still there
# (rm_updater_if_last). Safe for its servers: each panel's nodes hold that panel's token only, so the ones enrolled to
# the removed panel are refused by this one and keep their peers (a refused sync never reconciles), and this panel's
# own nodes simply find it back. A panel the operator stopped with nothing beside it is not parked and is left alone.
unpark_kept_panel(){
  local _lbl="" _how="" _why=""
  if $_BARE_PARKED && [ -f "$SD/swg-panel-server.service" ] && ! docker_running swg-panel; then
    _lbl="Bare-metal swg-panel"
    if run systemctl enable --now swg-panel-server 2>/dev/null; then
      [ -f "$SD/swg-sub.service" ] && { run systemctl enable --now swg-sub 2>/dev/null || warn "  couldn't start swg-sub — start it by hand: systemctl enable --now swg-sub"; }
      _how="started again"
    else _how="still stopped"; warn "couldn't start the bare-metal panel — start it by hand: systemctl enable --now swg-panel-server swg-sub"; fi
    _why="the Docker panel answered at the same address"
  elif $_DOCKER_PARKED && docker_running swg-panel && [ ! -f "$SD/swg-panel-server.service" ] && [ ! -d /opt/swg-panel ]; then
    _lbl="Docker panel (swg-panel)"
    if run sh -c 'for c in swg-panel swg-sub; do docker inspect "$c" >/dev/null 2>&1 || continue
                    docker update --restart=unless-stopped "$c" >/dev/null && docker start "$c" >/dev/null || exit 1; done'; then
      _how="started again"
    else _how="still stopped"; warn "couldn't start the Docker panel — start it by hand: cd $DOCKER_DIR && docker compose up -d"; fi
    _why="the bare-metal panel answered at the same address"
  fi
  [ -n "$_lbl" ] || return 0
  [ "$_how" = "started again" ] && ok "$_lbl started again — it was stopped only because $_why, and that panel is gone now."
  local i; for i in "${!DID_KEEP[@]}"; do
    [ "${DID_KEEP[$i]}" = "$_lbl" ] && DID_KEEP[$i]="$_lbl — $_how (it had been stopped while $_why)"; done
  return 0; }
_has_bare_netctl(){ ls $SD/swg-netctl.* >/dev/null 2>&1; }
_has_docker_netctl(){ ls $SD/swg-netctl-docker.* >/dev/null 2>&1; }
_has_leftovers(){ [ -d /etc/swg-sub ] || [ -d /opt/swg-sub ] || [ -e "$SD/swg-sub.service" ] || [ -d "$SD/swg-sub.service.d" ] \
  || [ -d /var/www/wgstats ] || [ -e /usr/local/bin/swg-passwd ] \
  || [ -e "$SD/swg-relay.slice" ] || [ -e "$SD/swg-relay@.service" ] || [ -d /etc/swg-panel/relay ] \
  || id swgpanel >/dev/null 2>&1 || id swgsub >/dev/null 2>&1 || id swgpush >/dev/null 2>&1 || id swgagent >/dev/null 2>&1 \
  || getent group swg >/dev/null 2>&1; }

# Delete the node-owned egress rules tagged for ONE interface (nat/POSTROUTING SNAT + filter/FORWARD accept +
# mangle/FORWARD MSS), matching swg-noded's own tags. The trailing quote in --comment "tag" keeps swg-egress:wdtt1
# from matching swg-egress:wdtt11.
_rm_egress_rules(){ local ifn="$1" t c l
  command -v iptables >/dev/null 2>&1 || return 0
  for t in "nat POSTROUTING swg-egress:$ifn" "filter FORWARD swg-egress-acl:$ifn" "mangle FORWARD swg-egress-mss:$ifn"; do
    set -- $t
    while IFS= read -r l; do
      [ -n "$l" ] || continue
      run sh -c "iptables -t $1 $(printf '%s' "$l" | sed "s/^-A /-D /")"
    done <<EOS
$(iptables -t "$1" -S "$2" 2>/dev/null | grep -F -- "--comment \"$3\"")
EOS
  done; }

# Remove the node's DATAPATH objects — the filtering / routing / NAT state swg-noded creates at runtime and that
# nothing else cleans up (it lives in the kernel, not on disk, so removing files leaves it behind). Every match is
# by an swg-OWNED name so a co-resident firewall/VPN is never touched:
#   • iptables rules whose --comment starts with "swg-"  (nat/filter/mangle: egress, fwd, inet, catk tags)
#   • the "swg_smart" nftables table (smart-routing / blocking)
#   • "swgk_*" / "swgs_*" ipsets (Kernel-SNI categories, and its per-person selections)
#   • policy-routing rules + tables in swg's OWN band 7000-7099 (SWG_RT_BASE..SWG_RT_MAX; priority == table id)
#     + the upstream-mark rules in 6890-6989 (SWG_RT_UP_BASE..SWG_RT_UP_MAX; rules only — they name no table)
#   • the forwarding sysctl drop-in the installer wrote
rm_node_netobjects(){
  info "Removing swg datapath objects (iptables/nft/ipset/policy-routing tagged swg-*)"
  local t chain l n
  if command -v iptables >/dev/null 2>&1; then
    for t in nat filter mangle; do
      for chain in $(iptables -t "$t" -S 2>/dev/null | sed -n 's/^-N \([A-Za-z0-9_-]*\).*/\1/p'; echo PREROUTING INPUT FORWARD OUTPUT POSTROUTING); do
        iptables -t "$t" -S "$chain" 2>/dev/null | grep -F -- '--comment "swg-' | while IFS= read -r l; do
          [ -n "$l" ] && run sh -c "iptables -t $t $(printf '%s' "$l" | sed 's/^-A /-D /')"
        done
      done
    done
  fi
    # The loop above only deletes rules that CARRY a swg- comment. Our own chains (SWG_INET, SWGK, SWG_CATK) and
    # the jumps INTO them have no comment, so they survived every uninstall — leaving an empty SWG_INET plus a live
    # "-A FORWARD -j SWG_INET" behind. Drop the jumps first (iptables refuses to delete a referenced chain), then
    # flush + delete the chains. Matched on our SWG prefix, so nothing else is touched.
    if command -v iptables >/dev/null 2>&1; then
      for t in nat filter mangle; do
        for chain in $(iptables -t "$t" -S 2>/dev/null | sed -n 's/^-N \(SWG[A-Za-z0-9_]*\).*/\1/p'); do
          iptables -t "$t" -S 2>/dev/null | grep -E -- "-j ${chain}$" | while IFS= read -r l; do
            [ -n "$l" ] && run sh -c "iptables -t $t $(printf '%s' "$l" | sed 's/^-A /-D /')"
          done
          run sh -c "iptables -t $t -F $chain"; run sh -c "iptables -t $t -X $chain"
        done
      done
    fi
    # nft: swg_smart is not the only table we create (swg_turn is the other) — sweep every swg* table we own.
    if command -v nft >/dev/null 2>&1; then
      nft list tables 2>/dev/null | sed -n 's/^table \([a-z0-9]*\) \(swg[A-Za-z0-9_]*\).*/\1 \2/p' | while read -r fam tbl; do
        [ -n "$tbl" ] && run nft delete table "$fam" "$tbl"
      done
    fi
    # ipsets: swgk_* are the kernel-SNI sets, but swgp_src (turn client-IP capture) is ours too.
    if command -v ipset >/dev/null 2>&1; then
      for n in $(ipset list -name 2>/dev/null | grep '^swg'); do run ipset destroy "$n"; done
    fi
  if command -v ip >/dev/null 2>&1; then
    for n in $(ip rule show 2>/dev/null | sed -n 's/^\([0-9]\+\):.*/\1/p' | awk '$1>=7000 && $1<=7099'); do
      run ip rule del pref "$n"; run ip route flush table "$n"
    done
    # ⚠️ AND THE UPSTREAM-MARK BAND BELOW IT (swg-noded's SWG_RT_UP_BASE..SWG_RT_UP_MAX = 6890..6989: `fwmark M lookup T`,
    # how the relay names a leg). It survived every uninstall — `6890: from all fwmark 0x1aea lookup 7000` was still
    # there on a fully removed master (1.8.8 qualification). A priority in it is NOT a table id (its rule looks up one in
    # the 7000 band, flushed above), so only the rule goes — never `table 6890`. Band spelled out: this file does not
    # read swg-noded; derived there as BASE − (MAX − BASE) − 11, so a change to the table band moves it.
    for n in $(ip rule show 2>/dev/null | sed -n 's/^\([0-9]\+\):.*/\1/p' | awk '$1>=6890 && $1<=6989'); do
      run ip rule del pref "$n"
    done
  fi
  # Orphaned wg-quick PostUp rules for a node<->node MESH link (swg-agent writes the FORWARD accept pair; `swg_` is
  # noded's reserved mesh link-name prefix). They carry no swg- comment and sit in no SWG* chain, so neither loop
  # above sees them, and PostDown never runs when the container/interface is force-removed. Only ever deleted when
  # the named link is GONE — a rule for a link that still exists belongs to something the operator kept.
  if command -v iptables >/dev/null 2>&1; then
    for n in $(iptables -S 2>/dev/null | grep -oE '[-]{1,2}[io] swg_[A-Za-z0-9_]+' | awk '{print $2}' | sort -u); do
      ip link show "$n" >/dev/null 2>&1 && continue          # link still up → not an orphan, leave it alone
      iptables -S 2>/dev/null | grep -E -- "-[io] ${n}( |$)" | while IFS= read -r l; do
        [ -n "$l" ] && run sh -c "iptables $(printf '%s' "$l" | sed 's/^-A /-D /')"
      done
    done
  fi
  # 99-swg-forward.conf is the BARE installer's name; install-docker.sh writes 99-swg-node.conf instead, so the
  # docker drop-in was never removed. Both are ours and both are unconditionally rewritten by a re-install.
  rmrf /etc/sysctl.d/99-swg-forward.conf /etc/sysctl.d/99-swg-node.conf
  ok "swg datapath objects removed"
}

rm_turn(){ local unit="$1" name fork
  name="$(basename "$unit" .service)"; fork="${name#vk-turn-proxy-}"
  info "Removing turn-proxy ($fork)"
  [ -e "$unit" ] && run systemctl disable --now "$name"
  rmrf "$unit" "$TURN_DIR/$fork"; run systemctl daemon-reload
  ls $SD/vk-turn-proxy-"${fork%-*}"-*.service >/dev/null 2>&1 || rmrf "$TURN_DIR/.bin/${fork%-*}"   # fork's last instance → drop its shared binary
  # last one out removes the shared dir + the panel-facing record
  ls $SD/vk-turn-proxy-*.service >/dev/null 2>&1 || rmrf "$TURN_DIR" $(rec_paths turn-proxy.json)
  ok "turn-proxy ($fork) removed"
}

# A WDTT server owns BOTH its service and its userspace interface (it brings the tunnel up itself), so removing one
# is the turn-proxy flow plus an `ip link delete`. Its config-dir holds the SERVER IDENTITY (wg-keys.dat) and the
# password store: deleting those can never be undone and no client on this instance could ever connect again — so
# that part is a separate question, default NO, mirroring how the panel keeps its roster for a re-install.
# (ask_yn returns immediately once the var is set, so the question is asked ONCE however many instances there are.)
rm_wdtt(){ local unit="$1" name iface fork
  name="$(basename "$unit" .service)"; iface="${name#swg-wdtt-}"
  fork="$(sed -n 's/^Description=swg-wdtt (\([^)]*\)).*/\1/p' "$unit" 2>/dev/null | head -1)"; fork="${fork%%/*}"
  info "Removing WDTT server ($iface${fork:+ · $fork})"
  [ -e "$unit" ] && run systemctl disable --now "$name"
  rmrf "$unit"; run systemctl daemon-reload
  command -v ip >/dev/null 2>&1 && run ip link delete dev "$iface" 2>/dev/null || true   # its userspace tunnel outlives the process
  rmrf "/var/run/wireguard/$iface.sock"   # the wireguard-go UAPI socket outlives it too — and a stale one makes the node report a PHANTOM adoption candidate
  # The node owns this instance's egress rules (WDTT runs with -no-nat). Nothing else removes them, so they'd
  # linger after an uninstall and a LATER install could reuse the iface name with a different subnet — leaving a
  # MASQUERADE for the old one and clients with no internet. Delete by our own comment tag only.
  _rm_egress_rules "$iface"
  # ask_yn returns immediately once its variable is set, so a single answer used to apply to EVERY instance —
  # while the prompt named one specific path. This is the one irrecoverable action in the script, so ask per
  # instance (a name-scoped variable), and let an unattended run still answer once via WDTT_DATA_DEL.
  local _delvar="WDTT_DATA_DEL_${iface//[^A-Za-z0-9_]/_}"
  [ -n "${WDTT_DATA_DEL:-}" ] && printf -v "$_delvar" '%s' "$WDTT_DATA_DEL"
  ask_yn "  Delete this WDTT interface identity + passwords ($WDTT_DIR/$iface)? Clients on it could never be restored." n "$_delvar"
  if [ "${!_delvar}" = yes ]; then
    rmrf "$WDTT_DIR/$iface"
  else
    ok "Kept $WDTT_DIR/$iface (server identity + passwords) for a future re-install"
  fi
  ls $SD/swg-wdtt-*.service >/dev/null 2>&1 || {          # last one out: shared per-fork binaries + the panel-facing record
    rmrf "$WDTT_DIR/.bin" $(rec_paths wdtt.json)
    [ "${WDTT_DATA_DEL:-}" = yes ] && rmrf "$WDTT_DIR"   # :- — the per-instance answers live in WDTT_DATA_DEL_<iface>; this global is only ever set by an unattended run, so under `set -u` an interactive uninstall died right here
  }
  ok "WDTT server ($iface) removed"
}

# csqtt: the same shape as rm_wdtt, with one difference that changes what the irrecoverable question means. csqtt has
# NO server keypair — a password IS the credential — so its config-dir holds the password STORE and nothing else can
# stand in for it: delete it and every client on this instance is locked out with no way back, exactly as if a WDTT
# identity had been destroyed. Same per-instance question, same default NO.
rm_csqtt(){ local unit="$1" name iface
  name="$(basename "$unit" .service)"; iface="${name#swg-csqtt-}"
  info "Removing csqtt server ($iface)"
  [ -e "$unit" ] && run systemctl disable --now "$name"
  rmrf "$unit"; run systemctl daemon-reload
  command -v ip >/dev/null 2>&1 && run ip link delete dev "$iface" 2>/dev/null || true   # its raw TUN outlives the process
  # The node owns this instance's egress rules (csqtt runs with --no-nat), same as WDTT — remove by our comment tag.
  _rm_egress_rules "$iface"
  local _delvar="CSQTT_DATA_DEL_${iface//[^A-Za-z0-9_]/_}"
  [ -n "${CSQTT_DATA_DEL:-}" ] && printf -v "$_delvar" '%s' "$CSQTT_DATA_DEL"
  ask_yn "  Delete this csqtt server's password store ($CSQTT_DIR/$iface)? Clients on it could never be restored." n "$_delvar"
  if [ "${!_delvar}" = yes ]; then
    rmrf "$CSQTT_DIR/$iface"
  else
    ok "Kept $CSQTT_DIR/$iface (password store) for a future re-install"
  fi
  ls $SD/swg-csqtt-*.service >/dev/null 2>&1 || {          # last one out: shared binary + the panel-facing record
    rmrf "$CSQTT_DIR/.bin" $(rec_paths csqtt.json)
    [ "${CSQTT_DATA_DEL:-}" = yes ] && rmrf "$CSQTT_DIR"
  }
  ok "csqtt server ($iface) removed"
}

# ───────────────────────── detect installed components ─────────────────────────
declare -a CLABEL=() CDETAIL=() CFN=() CARG=() CHINT=() CVERB=() CPROMPT=() CNOAUTO=()   # init empty (not just `declare -a`) — bash 5.2 + set -u treats a never-assigned array as unbound for ${#arr[@]}
# ── richer component details: interface names+ports, node endpoints, turn-proxy ports ──
# ── WHOSE INTERFACE IS THIS? ────────────────────────────────────────────────────────────────────
# `install-node.sh` has a scope test that refuses to ADOPT an interface swg did not create — a client
# tunnel, another product's server. The uninstaller had no matching test: it listed every .conf in the
# directory under "AmneziaWG interfaces", so `--yes` (or one careless Enter on a list whose label reads
# as though all of it were ours) brought a stranger's interface DOWN, disabled its unit, and deleted its
# keys with the `rm -rf` that follows. Measured on hel-flux 2026-09-08 — an awg0 from May with its own
# flux_* keys, an interface this box's own panel correctly lists as an ADOPTION CANDIDATE rather than
# owning, was in the removal plan. The installer and the uninstaller must answer this the same way.
#
# The bare node's agent config is the authority for what swg manages here. UNREADABLE ⇒ NOTHING IS
# CLAIMED: a missing answer must not become a confident yes about somebody else's data. The lists are
# built before any component runs, so a config the node component is about to delete is still present.
swg_owned_ifaces(){
  [ -f /etc/swg-agent/config.json ] && command -v python3 >/dev/null 2>&1 || return 0
  python3 - <<'PY' 2>/dev/null || true
import json
try: c = json.load(open("/etc/swg-agent/config.json"))
except Exception: raise SystemExit
print(" ".join(str(k) for k in (c.get("interfaces") or {})))
PY
}
_SWG_OWNED=" $(swg_owned_ifaces 2>/dev/null | tr '\n' ' ') "
swg_owns(){ case "$_SWG_OWNED" in *" $1 "*) return 0;; *) return 1;; esac; }
# THREE BUCKETS, and every .conf in the directory is in exactly one:
#   mesh     `swg_`-prefixed — the panel's system links. ALWAYS ours; the prefix is ours by construction,
#            so this holds even when the agent config cannot be read.
#   own      a peer interface the node's agent config names.
#   foreign  everything else — see the note above.
#
# ⚠️ THE MESH LINKS ARE THE NODE COMPONENT'S TO REMOVE, and until now nothing removed them. They were
# excluded from the printed list on the grounds that "the node component removes them" — and it did not;
# they only ever came down because `remove_ifaces` had no filter at all and took every .conf in the
# directory, with `rm -rf` finishing the job. The first version of the ownership split made that
# accidental coverage explicit and lost it: three mesh interfaces survived a COMPLETED uninstall on
# hel-flux, still up, with :9999-:10001 still bound. `rm_node` now removes them, where the comment always
# said they were removed.
_iface_mesh(){ case "$1" in "${SWG_SYS_PREFIX:-swg_}"*) return 0;; *) return 1;; esac; }
_iface_pick(){ local n="$1" want="${2:-own}"
  case "$want" in
    mesh)    _iface_mesh "$n" ;;
    own)     if _iface_mesh "$n"; then return 1; else swg_owns "$n"; fi ;;
    foreign) if _iface_mesh "$n" || swg_owns "$n"; then return 1; else return 0; fi ;;
    *)       return 0 ;;
  esac
}
iface_list(){  # <dir> [own|foreign|all] -> "awg0:51820, awg505:51234" (name + ListenPort from each .conf)
  local dir="$1" want="${2:-own}" out="" f n p
  for f in "$dir"/*.conf; do [ -f "$f" ] || continue
    n="$(basename "$f" .conf)"
    _iface_pick "$n" "$want" || continue
    p="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$f" 2>/dev/null | head -1)"
    out="${out:+$out, }${n}${p:+:$p}"
  done
  printf '%s' "$out"
}
bm_node_detail(){  # bare-metal node: endpoint + interfaces from config.json
  local cfg=/etc/swg-agent/config.json ep ifs
  if [ -f "$cfg" ] && command -v python3 >/dev/null 2>&1; then
    ep="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("endpoint_host",""))' "$cfg" 2>/dev/null)"
    ifs="$(python3 -c 'import json,sys;print(", ".join(k for k in (json.load(open(sys.argv[1])).get("interfaces") or {}) if not k.startswith("swg_")))' "$cfg" 2>/dev/null)"
  fi
  printf 'swg-noded%s%s' "${ep:+ · endpoint $ep}" "${ifs:+ · ifaces: $ifs}"
}
docker_node_detail(){  # docker node: name/endpoint + interfaces (name:port) from the deployment .env
  local env="$DOCKER_DIR/.env" ep nm ni ifs
  if [ -f "$env" ]; then
    ep="$(sed -n 's/^NODE_ENDPOINT=//p' "$env" | head -1 | tr -d '"')"
    nm="$(sed -n 's/^NODE_NAME=//p' "$env" | head -1 | tr -d '"')"
    ni="$(sed -n 's/^NODE_IFACES=//p' "$env" | head -1 | tr -d '"')"
    if [ -n "$ni" ]; then ifs="$(printf '%s' "$ni" | tr ',' '\n' | cut -d: -f1,2 | tr '\n' ',' | sed 's/,$//; s/,/, /g')"
    else ifs="$(sed -n 's/^NODE_IFACE=//p' "$env" | head -1 | tr -d '"')"; fi
  fi
  # Turn-proxies and WDTT servers, DOCKER form. Both are detected elsewhere by their host systemd units
  # (vk-turn-proxy-*.service / swg-wdtt-*.service), which a docker install simply does not have: turn-proxies
  # run as SIBLING CONTAINERS and WDTT as a supervised subprocess inside swg-node. They were therefore removed
  # with the node container while never appearing in the component list — the operator was never told a WDTT
  # server and its identity were about to go. They cannot be offered as separate components (nothing can keep
  # them once the node container is gone), so they are DISCLOSED here, on the node they belong to.
  local tn wl wn
  tn="$(docker ps -a --filter 'name=swg-turn-' --format '{{.Names}}' 2>/dev/null | sed 's/^swg-turn-//' | tr '\n' ',' | sed 's/,$//; s/,/, /g')"
  # uninstall.sh is standalone (it must run on a box where lib/ may be gone), so the record is parsed here rather
  # than via common.sh's wdtt_local. Heredoc body at column 0: indenting a python program is an IndentationError,
  # and 2>/dev/null would swallow it and silently report "no WDTT" on a box that has one.
  wl="$(python3 - "$DOCKER_DIR/data/node/wdtt.json" <<'PYWD' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    raise SystemExit
out = []
for i in (d.get("wdtt") or []):
    if isinstance(i, dict) and i.get("iface"):
        out.append("%s%s" % (i["iface"], ("/" + i["fork"]) if i.get("fork") else ""))
print(", ".join(out))
PYWD
)"
  wn="$(printf '%s' "$wl" | tr ',' '\n' | grep -c . 2>/dev/null)"
  # csqtt, same disclosure and for the same reason — a supervised subprocess inside swg-node, so no host unit names
  # it and it would leave with the container unannounced. Its record is a flat {iface: inst} map, not WDTT's list.
  local cl cn
  cl="$(python3 - "$DOCKER_DIR/data/node/csqtt.json" <<'PYCQ' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    raise SystemExit
if not isinstance(d, dict):
    raise SystemExit
out = []
for k, i in d.items():
    if isinstance(i, dict):
        n = len(i.get("passwords") or {})
        out.append("%s%s" % (k, (" (%d pw)" % n) if n else ""))
print(", ".join(out))
PYCQ
)"
  cn="$(printf '%s' "$cl" | tr ',' '\n' | grep -c . 2>/dev/null)"
  printf 'container swg-node%s%s%s%s%s%s' "${nm:+ · $nm}" "${ep:+ · endpoint $ep}" "${ifs:+ · ifaces: $ifs}" \
         "${tn:+ · turn-proxies: $tn}" "${wl:+ · WDTT ($wn): $wl}" "${cl:+ · csqtt ($cn): $cl}"
}
turn_exec_env(){  # <unit> -> "<listen>\t<connect>", resolving the EnvironmentFile (turn.env) form
  local unit="$1" exe envf
  exe="$(sed -n 's/^ExecStart=//p' "$unit" 2>/dev/null | head -1)"
  case "$exe" in
    *'${SWG_'*)   # env-file form — values live in turn.env, not the ExecStart
      envf="$(sed -n 's/^EnvironmentFile=-\{0,1\}//p' "$unit" 2>/dev/null | head -1)"
      printf '%s\t%s' "$(sed -n 's/^SWG_LISTEN=//p' "$envf" 2>/dev/null | head -1)" "$(sed -n 's/^SWG_CONNECT=//p' "$envf" 2>/dev/null | head -1)" ;;
    *)            # legacy baked-ExecStart form
      printf '%s\t%s' "$(printf '%s' "$exe" | sed -n 's/.*-listen[ =]\{1,\}\([^ ]*\).*/\1/p')" "$(printf '%s' "$exe" | sed -n 's/.*-connect[ =]\{1,\}\([^ ]*\).*/\1/p')" ;;
  esac
}
turn_fwd_iface(){  # connect "ip:port" -> the wg/awg interface whose ListenPort matches the port (else empty)
  local cp="${1##*:}" f lp
  for f in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf; do [ -f "$f" ] || continue
    lp="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$f" 2>/dev/null | head -1)"
    [ -n "$lp" ] && [ "$lp" = "$cp" ] && { basename "$f" .conf; return; }
  done
}
turn_detail(){  # <unit> -> "1.2.3.4:57000 → 127.0.0.1:51820 (wg7)" — the listen → connect (iface) style used elsewhere
  local lis con fw; IFS="$(printf '\t')" read -r lis con < <(turn_exec_env "$1")
  fw="$(turn_fwd_iface "$con")"
  printf '%s%s%s' "${lis:-?}" "${con:+ → $con}" "${fw:+ ($fw)}"
}
add(){ CLABEL+=("$1"); CDETAIL+=("$2"); CFN+=("$3"); CARG+=("${4:-}"); CHINT+=("${5:-}"); CVERB+=("${6:-Uninstall}"); CPROMPT+=("${7:-$1}"); CNOAUTO+=("${8:-}"); }   # $6 = question verb (default Uninstall); $7 = shorter label for the question (defaults to the list label); $8 = "never-auto" ⇒ --yes does NOT answer it
turn_listen(){ local lis con; IFS="$(printf '\t')" read -r lis con < <(turn_exec_env "$1"); printf '%s' "$lis"; }
# WDTT: params live in the instance's wdtt.env (the unit's ExecStart only references them), so read that.
wdtt_env(){ local iface="$1" k="$2"; sed -n "s/^$k=//p" "$WDTT_DIR/$iface/wdtt.env" 2>/dev/null | head -1; }
wdtt_listen(){ local n; n="$(basename "$1" .service)"; wdtt_env "${n#swg-wdtt-}" SWG_LISTEN; }
wdtt_detail(){  # <unit> -> "amurcanov · DTLS 1.2.3.4:56000 · wg :56001 · 10.66.66.1/24 · identity kept"
  local unit="$1" n iface fork lis wgp addr id
  n="$(basename "$unit" .service)"; iface="${n#swg-wdtt-}"
  fork="$(sed -n 's/^Description=swg-wdtt (\([^)]*\)).*/\1/p' "$unit" 2>/dev/null | head -1)"; fork="${fork%%/*}"
  lis="$(wdtt_env "$iface" SWG_LISTEN)"; wgp="$(wdtt_env "$iface" SWG_WGPORT)"; addr="$(wdtt_env "$iface" SWG_WGADDR)"
  [ -f "$WDTT_DIR/$iface/wg-keys.dat" ] && id="server identity on disk" || id="no identity file"
  printf '%s%s%s%s · %s' "${fork:-wdtt}" "${lis:+ · DTLS $lis}" "${wgp:+ · $iface:$wgp}" "${addr:+ · $addr}" "$id"
}
# csqtt: same idea, its own env file. There is no identity file to report — the store IS the identity, so say how
# many passwords would go with it, which is the number that decides the keep/delete answer.
csqtt_env(){ local iface="$1" k="$2"; sed -n "s/^$k=//p" "$CSQTT_DIR/$iface/csqtt.env" 2>/dev/null | head -1; }
csqtt_listen(){ local n; n="$(basename "$1" .service)"; csqtt_env "${n#swg-csqtt-}" SWG_LISTEN; }
csqtt_detail(){  # <unit> -> "csqtt · 1.2.3.4:56006 · 10.12.0.1/24 · 4 passwords on disk"
  local unit="$1" n iface lis addr pw
  n="$(basename "$unit" .service)"; iface="${n#swg-csqtt-}"
  lis="$(csqtt_env "$iface" SWG_LISTEN)"; addr="$(csqtt_env "$iface" SWG_TUNADDR)"
  # csqtt <=2.0.1 kept passwords.json; 2.1.5 migrated it into SQLite csqtt.db and removed it. Reading only the
  # JSON reported "no password store" for a server holding users — on the screen that says what is about to be
  # destroyed, which is the one place that must not understate it.
  pw="$(python3 -c 'import json,os,sqlite3,sys
d = sys.argv[1]
try:
    j = os.path.join(d, "passwords.json")
    if os.path.isfile(j):
        print(len(json.load(open(j)).get("passwords") or {}))
    else:
        c = sqlite3.connect(os.path.join(d, "csqtt.db"))
        try: print(len(list(c.execute("SELECT 1 FROM passwords"))))
        finally: c.close()
except Exception: print("")' "$CSQTT_DIR/$iface" 2>/dev/null)"
  if [ -n "$pw" ]; then pw="$pw password(s) on disk"; else pw="no password store"; fi
  printf 'csqtt%s%s · %s' "${lis:+ · $lis}" "${addr:+ · $addr}" "$pw"
}

[ -d /opt/swg-panel ] || [ -f $SD/swg-panel-server.service ] && \
  add "Bare-metal swg-panel" "control panel (/opt/swg-panel)" rm_panel
[ -d /opt/swg-noded ] || [ -d /opt/swg-agent ] || [ -f $SD/swg-noded.service ] && \
  add "Bare-metal node (swg-node)" "$(bm_node_detail)" rm_node
# (the "swg-netctl (leftover helper)" component is added AFTER the docker detection below, for the same reason.)
# (the "Leftover swg files" component is added AFTER the docker detection below — it must know whether a docker
#  install is present, since the identities it removes own that install's data-dir files.)

# Docker: the panel and node are separate containers — offer each independently. If the
# deployment dir exists but neither container does, offer a files-only cleanup.
DPANEL=false; DNODE=false
if command -v docker >/dev/null 2>&1; then
  docker_running swg-panel && DPANEL=true
  docker_running swg-node  && DNODE=true
fi
$DPANEL && add "Docker panel (swg-panel)" "container swg-panel" rm_docker_panel
$DNODE  && add "Docker node (swg-node)"   "$(docker_node_detail)"   rm_docker_node
# A PANEL PARKED FOR THE OTHER ONE. guard_second_panel (lib/common.sh) stops one panel when a panel of the other method
# would answer beside it at the same address: a bare one disabled + stopped, a docker one stopped with restart=no. Which
# of them is parked is read NOW, before anything is removed — unpark_kept_panel (below) needs to know it once the other
# one is gone. TWIN of lib/common.sh's docker_parked / docker_panel_live (this file does not source it).
_ctr_parked(){ [ "$(docker inspect -f '{{.State.Running}} {{.HostConfig.RestartPolicy.Name}}' "$1" 2>/dev/null)" = "false no" ]; }
_BARE_PARKED=false; _DOCKER_PARKED=false
if [ -f "$SD/swg-panel-server.service" ] && $DPANEL; then
  if ! systemctl is-enabled --quiet swg-panel-server 2>/dev/null; then ! _ctr_parked swg-panel && _BARE_PARKED=true
  else _ctr_parked swg-panel && _DOCKER_PARKED=true; fi
fi
# swg-netctl units lingering WITHOUT the panel they serve → offer on their own. ⚠️ PER FAMILY: swg-netctl.* belongs to
# a bare panel (rm_panel sweeps both families), swg-netctl-docker.* to a docker one — which rm_docker_panel now removes.
# Testing only "is there a bare panel" listed a LIVE docker panel's own helper as "(leftover helper)" (1.8.8 qualification).
{ { [ ! -d /opt/swg-panel ] && [ ! -f $SD/swg-panel-server.service ] && _has_bare_netctl; } || { ! $DPANEL && _has_docker_netctl; }; } && \
  add "swg-netctl (leftover helper)" "privileged network/TLS helper units" rm_netctl

# swg-sub's dirs/units and the bare-metal service identities are removed by rm_panel/rm_node, which a docker-only
# or post-convert box never runs — so they outlived every uninstall on exactly the boxes that have them. Offered
# whenever no BARE-METAL panel/node is left (those own them). A docker install on the box used to keep this off the
# list altogether — live, being removed in this very run, or already removed with its data dir KEPT — so a converted
# box kept every bare-era file and identity for good. rm_leftovers now decides the identities at run time instead,
# after the docker components above have been removed or kept (`swgpanel` owns data a convert copied in).
if [ ! -d /opt/swg-panel ] && [ ! -f $SD/swg-panel-server.service ] \
   && [ ! -d /opt/swg-noded ] && [ ! -f $SD/swg-noded.service ] && _has_leftovers; then
  add "Leftover swg files" "swg-sub dirs/units + service identities from a docker or converted install" rm_leftovers
fi
if ! $DPANEL && ! $DNODE && { [ -f "$DOCKER_DIR/docker-compose.yml" ] || [ -f "$DOCKER_DIR/.env" ]; }; then
  add "Docker deployment (files)" "$DOCKER_DIR" rm_docker_files
fi

# NB: grep on a here-string, NOT 'dpkg -l | grep -q' — under pipefail, grep -q exits on first match and the
# still-writing dpkg gets SIGPIPE (141), so the pipe reports failure even on a match (amneziawg sorts early in
# dpkg -l, so it always tripped this; wireguard sorts late and usually slipped through).
pkg_ii(){ grep -qE "$1" <<< "$(dpkg -l 2>/dev/null)"; }
# interface configs (the PEERS) vs the system PACKAGE — detected + offered SEPARATELY
awg_ifaces(){ ls /etc/amnezia/amneziawg/*.conf >/dev/null 2>&1 || ls $SD/awg*.service >/dev/null 2>&1; }
wg_ifaces(){  ls /etc/wireguard/*.conf >/dev/null 2>&1 || ls $SD/wg-quick@*.service >/dev/null 2>&1; }
awg_pkg(){ command -v dpkg >/dev/null 2>&1 && pkg_ii '^ii +amneziawg(-tools| |$)'; }
wg_pkg(){  command -v dpkg >/dev/null 2>&1 && pkg_ii '^ii +wireguard '; }
# The host WG/AWG PACKAGES are swg's to purge only when a BARE-METAL swg node installed them. A docker node runs
# its datapath in-container (userspace amneziawg-go), so on a docker-only box these host packages belong to
# something else (e.g. wg-easy, or another VPN) — purging them would break it. Peers (interface .conf files) are
# still offered separately since those files ARE swg's own.
_f=""; _fw=""   # the foreign interface lists, set by the registrations below and READ by the package ones
_bare_swg=false; { [ -d /opt/swg-noded ] || [ -d /opt/swg-agent ] || [ -f "$SD/swg-noded.service" ] || [ -d /opt/swg-panel ] || [ -f "$SD/swg-panel-server.service" ]; } && _bare_swg=true
awg_ifaces && { _d="$(iface_list /etc/amnezia/amneziawg own)"; [ -n "$_d" ] && add "AmneziaWG interfaces" "$_d" rm_awg_peers "" "$_d" Remove
                _f="$(iface_list /etc/amnezia/amneziawg foreign)"; [ -n "$_f" ] && add "AmneziaWG interfaces NOT created by swg" "$_f" rm_awg_foreign "" "$_f" Remove "AmneziaWG interfaces NOT created by swg" never-auto; true; }
# ⚠️ AND THE PACKAGE THAT INTERFACE NEEDS. Purging it runs `down_ifaces` first — which brings the
# foreign interface DOWN — and then removes the kernel module out from under it, so keeping the .conf
# and purging the package still ends with somebody else's tunnel dead, just less obviously. When a
# foreign interface of this kind is present the package question is therefore never-auto too: it must
# be typed, it is kept with no terminal, and the hint says why.
awg_pkg    && $_bare_swg && { if [ -n "$_f" ]; then add "AmneziaWG package (kernel module + tools)" "amneziawg · amneziawg-tools · amneziawg-dkms" rm_awg_pkg "" "$_f needs it" Uninstall "AmneziaWG package (kernel module + tools)" never-auto
                             else add "AmneziaWG package (kernel module + tools)" "amneziawg · amneziawg-tools · amneziawg-dkms" rm_awg_pkg; fi; }
wg_ifaces  && { _d="$(iface_list /etc/wireguard own)"; [ -n "$_d" ] && add "WireGuard interfaces" "$_d" rm_wg_peers "" "$_d" Remove
                _fw="$(iface_list /etc/wireguard foreign)"; [ -n "$_fw" ] && add "WireGuard interfaces NOT created by swg" "$_fw" rm_wg_foreign "" "$_fw" Remove "WireGuard interfaces NOT created by swg" never-auto; true; }
wg_pkg     && $_bare_swg && { if [ -n "$_fw" ]; then add "WireGuard package (kernel module + tools)" "wireguard · wireguard-tools" rm_wg_pkg "" "$_fw needs it" Uninstall "WireGuard package (kernel module + tools)" never-auto
                             else add "WireGuard package (kernel module + tools)" "wireguard · wireguard-tools" rm_wg_pkg; fi; }
true   # don't let the last &&-test leave a non-zero status

for unit in $(ls $SD/vk-turn-proxy-*.service 2>/dev/null || true); do
  add "Turn-proxy (service) $(basename "$unit" .service)" "$(turn_detail "$unit")" rm_turn "$unit" "$(turn_listen "$unit")" "" "Turn-proxy $(basename "$unit" .service)"   # type + green service name, then listen → connect (iface)
done
for unit in $(ls $SD/swg-wdtt-*.service 2>/dev/null || true); do   # WDTT servers — listed per instance, like turn-proxies
  add "WDTT (service + interface) $(basename "$unit" .service)" "$(wdtt_detail "$unit")" rm_wdtt "$unit" "$(wdtt_listen "$unit")" "" "WDTT-proxy $(basename "$unit" .service)"
done
for unit in $(ls $SD/swg-csqtt-*.service 2>/dev/null || true); do   # csqtt servers — same, one entry per instance
  add "csqtt (service + interface) $(basename "$unit" .service)" "$(csqtt_detail "$unit")" rm_csqtt "$unit" "$(csqtt_listen "$unit")" "" "csqtt server $(basename "$unit" .service)"
done

N=${#CLABEL[@]}
[ "$N" -gt 0 ] || die "swg-panel does not appear to be installed here (nothing to do)"

# ───────────────────────── list, then prompt per component ─────────────────────────
echo; info "Found these installed components:"; echo
for i in $(seq 0 $((N-1))); do printf '    %s%s%s  %s\n' "$(c '0;32')" "${CLABEL[$i]}" "$(c 0)" "$(c '0;90')${CDETAIL[$i]}$(c 0)"; done
echo
$ASSUME_YES && info "--yes: every component will be uninstalled (you'll still be asked the destructive sub-questions)." \
            || echo "  You'll be asked about each component one by one — nothing is removed without your yes."
echo

# Per component: ask "Uninstall X?"; if yes, the removal fn asks its own destructive sub-questions
# (keep peers / delete data dir) so the peers' fate is decided in context, not up front.
DID_REMOVE=(); DID_KEEP=(); NOT_DONE=()   # NOT_DONE: asked for, attempted, and the box says otherwise
for i in $(seq 0 $((N-1))); do
  if ask_comp "${CPROMPT[$i]}" "${CHINT[$i]}" "${CVERB[$i]}" "${CNOAUTO[$i]}"; then "${CFN[$i]}" "${CARG[$i]}"
    case " ${NOT_DONE[*]-} " in *" ${CLABEL[$i]} "*) :;; *) DID_REMOVE+=("${CLABEL[$i]}");; esac
  else info "Kept ${CLABEL[$i]}."; DID_KEEP+=("${CLABEL[$i]}")
    # Does what was kept RUN on swg's datapath objects? A package, the panel, a helper, leftover files or somebody
    # else's interface does not — keeping one of those used to skip the sweep below all the same, so the common
    # "remove swg, keep the wg/awg packages" left every swg ip rule, nft table and iptables tag behind for good.
    # Anything not named here counts as datapath (a new component is safe until someone decides otherwise).
    case "${CFN[$i]}" in rm_awg_pkg|rm_wg_pkg|rm_awg_foreign|rm_wg_foreign|rm_panel|rm_docker_panel|rm_docker_files|rm_netctl|rm_leftovers) ;;
      *) KEPT_DATAPATH=true;; esac
  fi
  echo
done

# Datapath sweep, LAST — after every keep/remove decision. rm_node_netobjects deletes swg-tagged iptables rules,
# the swg_smart nft table, swgk_* ipsets and our ip rules/tables; those are the datapath of the very interfaces,
# turn-proxies and WDTT servers the operator may have chosen to KEEP, so it cannot run before they are asked.
# Anything kept has already had its own rules removed by its own remover (rm_wdtt → _rm_egress_rules).
if [ "${NEED_NETOBJ_SWEEP:-false}" = true ]; then
  if [ "${KEPT_DATAPATH:-false}" = true ]; then
    # The sweep is all-or-nothing by tag — it cannot tell a kept interface's swg-egress rule from a removed one's.
    # Keeping something means keeping it WORKING, so leave the objects: stale rules on a box that still runs our
    # datapath are harmless, whereas deleting a kept WDTT server's SNAT silently kills internet for its clients.
    info "Some components were kept — leaving the routing/filter objects in place so they keep working."
    info "  To clear them later, once nothing swg-related remains: re-run this uninstaller."
  else
    rm_node_netobjects
  fi
fi

# Containers we TOOK an interface over from (see rm_node). Their server was somebody else's before it was ours,
# and the take-over stopped it with restart=no on the promise that we would serve it instead. That promise ends
# here, so put them back the way we found them — after the interfaces above are gone, so the port they bind is
# free. Default YES: leaving a box with neither our interface nor their container is the one outcome nobody wants.
if [ -n "${ADOPTED_CTRS:-}" ] && command -v docker >/dev/null 2>&1; then
  _nc="$(printf '%s\n' "$ADOPTED_CTRS" | grep -c .)"
  info "$_nc container(s) had an interface taken over by this node — still stopped, as the take-over left them."
  ask_yn "  Start them again? Without this the box is left with no server at all — ours removed, theirs off." y RESTORE_CTRS
  if [ "${RESTORE_CTRS:-}" = yes ]; then
    printf '%s\n' "$ADOPTED_CTRS" | while IFS= read -r _c; do [ -n "$_c" ] || continue
      docker inspect "$_c" >/dev/null 2>&1 || { info "  $(b "$_c") is gone — nothing to restore"; continue; }
      run sh -c "docker update --restart=always '$_c' >/dev/null 2>&1 || true"
      if $DRYRUN; then echo "    [dry] docker start $_c"; continue; fi
      if docker start "$_c" >/dev/null 2>&1; then ok "restarted $(b "$_c") — its own server is serving again"
      else warn "  could not start $(b "$_c") — start it by hand: docker start $_c"; fi
    done
  else info "  Left stopped — start one by hand with: docker start <name>"; fi
fi

unpark_kept_panel
# Recovery archives from earlier converts/uninstalls (.converted-* / .uninstalled-*). They are OURS, but they are
# deliberately-kept state — a node token plus interface private keys — and the installer offers them as a recovery
# list, so they are never deleted without being asked. Default NO; a preset ARCHIVES_DEL=y covers unattended wipes.
_archives(){ ls -d /opt/swg-panel*.converted-* /opt/swg-panel*.uninstalled-* /etc/swg-panel*.converted-* \
                   /etc/swg-panel*.uninstalled-* /var/lib/swg-panel*.converted-* /var/lib/swg-panel*.uninstalled-* 2>/dev/null; }
if [ -n "$(_archives)" ]; then
  _na="$(_archives | wc -l)"
  # …and say which of them THIS run saved (asked interactively, the answer covers it too — so it must say so).
  _nr=0; for _a in ${RUN_ARCHIVES:-}; do [ -e "$_a" ] && _nr=$((_nr+1)); done
  info "$_na recovery archive(s) remain (node token + interface keys)$([ "$_nr" -gt 0 ] && printf ' — %s saved by this run, the rest from earlier converts/uninstalls' "$_nr")."
  ask_yn "  Delete them too? A future install can no longer offer them for recovery." n ARCHIVES_DEL
  if [ "${ARCHIVES_DEL:-}" = yes ]; then _archives | while IFS= read -r _a; do [ -n "$_a" ] && rmrf "$_a"; done
    ok "removed $_na recovery archive(s)$([ "$_nr" -gt 0 ] && printf ' — including the copy saved above: this node can no longer be recovered from this box')"
  else info "  Kept — delete by hand once you no longer need them."; fi
fi

# group cleanup (shared by panel + agent) — only if we removed a bare-metal piece, or swept the bare-metal
# identities off a docker/converted box (where REMOVED_PANEL/REMOVED_NODE are never set but the group is ours).
if { $REMOVED_PANEL || $REMOVED_NODE || [ "${REMOVED_LEFTOVERS:-false}" = true ]; } && getent group swg >/dev/null 2>&1; then
  run groupdel swg 2>/dev/null || info "group 'swg' still in use — left in place."
fi
rmdir /etc/swg-agent 2>/dev/null || true
# The interface-config dirs, once EMPTY and NOT a package's. Our installers create them (writef's mkdir -p) and a
# bare→docker convert empties them; with the wg/awg package still installed dpkg owns them and they stay (so does
# anything with a file left in it, or any box without dpkg to ask). Seen: both left empty after a full uninstall.
if [ "${#DID_REMOVE[@]}" -gt 0 ] && command -v dpkg >/dev/null 2>&1; then
  for _d in /etc/amnezia/amneziawg /etc/amnezia /etc/wireguard; do
    [ -d "$_d" ] && [ -z "$(ls -A "$_d" 2>/dev/null)" ] && ! dpkg -S "$_d" >/dev/null 2>&1 && run rmdir "$_d"
  done
fi

echo; echo "$(b '──────────────── SUMMARY ────────────────')"; echo
if [ "${#DID_REMOVE[@]}" -gt 0 ]; then echo "  $(b Removed):"
  for x in "${DID_REMOVE[@]}"; do echo "    $(c '0;31')✗$(c 0) $x"; done; fi
[ "${#DID_REMOVE[@]}" -gt 0 ] && [ "${#DID_KEEP[@]}" -gt 0 ] && echo
if [ "${#DID_KEEP[@]}" -gt 0 ]; then echo "  $(b Kept):"
  for x in "${DID_KEEP[@]}"; do echo "    $(c '0;32')•$(c 0) $x"; done; fi
# The list that has to exist for the other two to be worth anything: what was asked for, attempted, and
# did not happen. Without it a failed purge sat under "Removed" and the operator had no reason to look.
if [ "${#NOT_DONE[@]}" -gt 0 ]; then echo
  echo "  $(b 'Asked for but NOT removed') — the box still has these:"
  for x in "${NOT_DONE[@]}"; do echo "    $(c '0;33')!$(c 0) $x"; done; fi
echo
$DRYRUN && ok "DRY RUN — nothing was actually removed; re-run without --dry-run to apply." \
        || ok "Uninstall complete."
echo     # one blank line after the summary block (consistency)
