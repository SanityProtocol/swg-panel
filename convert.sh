#!/usr/bin/env bash
# convert.sh [--check] <from-method> <to-method> <role>
#   Migrate a swg deployment between docker and bare-metal, preserving settings / identity / interfaces.
#   Driven by bootstrap.sh's cross-method conflict prompt; can also be run by hand.
#
#   --check          only run the port/interface pre-flight (prints clashes, exits non-zero if any)
#   from/to          docker | baremetal
#   role             node | host | master
#
# Status: all four directions are automated — node and panel, each way (docker ↔ bare-metal), plus master
# (panel + co-located node) as a unit. A reverse-proxy panel converts to docker plain-HTTP-behind-proxy
# (TLS=none + loopback binds) and back; identity/roster/nodes/cert/interfaces/turn-proxies are preserved.
# NOTE: bare→docker reads the panel URL/base/TLS from /etc/swg-panel/install.conf — keep that file current
# (an Access address-migration must update it, or the convert will resurrect the pre-migration address).
set -euo pipefail
# ⚠️ ONLY THE TERMINAL'S FOREGROUND CAN READ IT. Under `curl … | sudo bash`, sudo-rs (Ubuntu 26.04's sudo) runs the
# script in the BACKGROUND of its own terminal: /dev/tty still opens, and the first read STOPS the process (SIGTTIN) with
# nothing on screen — the installer "hung at the TLS question" (client report 2026-10-06; sudo-rs issue #1263). So every
# question reads SWG_TTY: /dev/tty while this process group is the terminal's foreground, /dev/null otherwise (an EOF,
# which each question already answers with its no-terminal default) — no terminal at all, or the background under sudo-rs.
# ⚠️ NOT UNDER CLASSIC SUDO. It backgrounds the script the same way (≥ 1.9.13 with use_pty: Ubuntu 24.04, Debian 12/13) but
# brings it to the foreground at that first read, so `curl … | sudo bash` asked its questions there, as in 1.8.8 — taking
# every background start as unreadable took them all away (1.8.9 qualification IN-2). Which sudo it is: the first sudo up
# the chain, by its binary's path (sudo-rs, cargo), else by its --version. No sudo above (a job the operator put in the
# background): the terminal, as ever. /proc/<pid>/stat after the command name: state ppid pgrp session tty_nr tpgid.
# Without /proc: as before.
_swg_tty_fg(){ local s f p e i IFS=' '; { read -r s </proc/$$/stat; } 2>/dev/null || return 0; read -ra f <<< "${s##*) }"
  [ "${f[2]:-}" = "${f[5]:-}" ] && return 0; [ "${f[5]:-0}" -gt 0 ] 2>/dev/null || return 1
  for i in 1 2 3 4; do p="${f[1]:-0}"; [ "$p" -gt 1 ] 2>/dev/null || return 0; e="$(readlink "/proc/$p/exe" 2>/dev/null)" || e=""
    case "${e##*/}" in sudo*) case "$e" in *sudo-rs*|*cargo*) return 1;; esac
      case "$("$e" --version 2>/dev/null)" in sudo-rs*) return 1;; esac; return 0;; esac
    { read -r s <"/proc/$p/stat"; } 2>/dev/null || return 0; read -ra f <<< "${s##*) }"; done; return 0; }
SWG_TTY=/dev/tty; _swg_tty_fg || SWG_TTY=/dev/null
swg_tty_ok(){ [ "$SWG_TTY" = /dev/tty ] && { : </dev/tty; } 2>/dev/null; }
if [ "$SWG_TTY" = /dev/null ] && [ -z "${SWG_TTY_WARNED:-}" ] && { : </dev/tty; } 2>/dev/null; then   # said once per run
  printf '%s\n' "! This terminal cannot be read: the script runs in its background, which \`curl … | sudo bash\` does under sudo-rs (Ubuntu 26.04's sudo). Questions take their defaults. To answer them, run: sudo bash -c \"\$(curl -fsSL <bootstrap.sh URL>)\" -- <arguments>" >&2
  export SWG_TTY_WARNED=1
fi
SRC="$(cd "$(dirname "$0")" && pwd)"
. "$SRC/lib/common.sh"   # shared helpers (dl_turn_bin + validators)
# Refuse on a declaratively managed host BEFORE anything is written — a bare↔docker conversion laid down here would
# be invisible to the host's own tooling. Defined in lib/common.sh, above; a `--dry-run` still runs.
refuse_on_declarative_host 'services.swg-node = { enable = true; ... };'
DOCKER_DIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"
if { [ -t 1 ] || [ -n "${SWG_FORCE_COLOR:-}" ]; } && [ -z "${NO_COLOR:-}" ]; then C_BLUE=$'\033[38;5;39m'; C_BL=$'\033[38;5;33m'; C_BROWN=$'\033[38;5;130m'; C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; RESET=$'\033[0m'; BOLD=$'\033[1m'
else C_BLUE=""; C_BL=""; C_BROWN=""; C_RED=""; C_GREEN=""; RESET=""; BOLD=""; fi
# we lc_init a tee (stdout → pipe) before exec'ing/running the installers, so THEIR [ -t 1 ] would be false
# and they'd print uncoloured. Propagate our colour decision so they force colour (the codes reach the tty
# through the tee). Only when we actually have colour (a tty / already forced; respects NO_COLOR).
[ -n "$BOLD" ] && export SWG_FORCE_COLOR=1
b(){ printf '%s%s%s' "$BOLD" "$*" "$RESET"; }
# universal row flags (shared across every script): ▸ light-blue action, :: blue sub-item, ✓ green, ! brown, ✗ red
info(){ echo "${C_BLUE}▸${RESET} ${BOLD}$*${RESET}"; }   # bold action/step line (matches the installers)
sub(){  echo "${C_BL}::${RESET} $*"; }                    # indented sub-item / progress detail
ok(){   echo "${C_GREEN}✓${RESET} $*"; }
warn(){ echo "${C_BROWN}!${RESET} $*" >&2; }
die(){  echo "${C_RED}✗ $*${RESET}" >&2; exit 1; }
# ── the docker-only one-click updater, retired on the way OUT of docker ────────────────────────────────
# `wire_host_updater` lays `swg-update{,-check}` + swg-update.service/.timer down on EVERY docker profile,
# node included, because a container cannot recreate itself: the panel/node touches a trigger and this
# host-side unit does the `compose pull && up`. None of that means anything once the box is bare-metal, and
# convert.sh removed none of it — so a converted node kept a 30 s timer polling for docker update requests
# on a box with no docker install, and `update.sh` never touches it again (a bare-metal NODE has no wrapper
# BY DESIGN; `ensure_update_unit` is panel-only). Two identical bare-metal nodes then differ by history
# alone, and the stale wrapper on the converted one is never rewritten.
#
# ⚠️ WHEN matters, because a bare PANEL's updater is the SAME five paths: a PANEL convert retires this BEFORE
# install-host.sh writes the bare panel's own (it "ran later" only in this comment — the call sat after install-host,
# and removed the updater the bare panel had just been given: Update pressed, nothing ran, 1.8.8 qualification). A
# NODE convert retires it only when no panel, bare or docker, is left on the box to own those files.
# Best-effort throughout — a missing unit must not trip set -e.
# Found on hel-fresh doing the bare→docker→bare round trip, 1.8.6 qualification.
# ⚠️ PLAIN COMMANDS, not `run`/`rmrf`: those are the INSTALLERS' helpers (install-host.sh, install-docker.sh,
# uninstall.sh each define their own) and convert.sh has neither — it calls things directly, like line 139
# below. Written with them first, this function would have died with "run: command not found" on the one
# path nobody re-runs. `|| true` on every step because the file is `set -euo pipefail` and a unit that was
# never installed must not abort a conversion that has otherwise finished.
retire_docker_updater(){
  local _u
  for _u in swg-update.timer swg-update.path; do
    [ -e "/etc/systemd/system/$_u" ] || continue
    systemctl disable --now "$_u" >/dev/null 2>&1 || true
  done
  rm -f /etc/systemd/system/swg-update.service /etc/systemd/system/swg-update.path \
        /etc/systemd/system/swg-update.timer /usr/local/bin/swg-update \
        /usr/local/bin/swg-update-check /var/lib/swg-update.stamp 2>/dev/null || true
  systemctl daemon-reload 2>/dev/null || true
}

# "name=host,…" — the endpoint each ADOPTED interface's clients already dial on the docker node, handed to
# install-node.sh (ADOPTED_ENDPOINTS) so a docker → bare-metal convert KEEPS it. Without it install-node re-detected
# every interface's endpoint from the default route: on a box behind NAT or dialled by a DNS name the panel's client
# configs changed to the box's raw address (measured: 1.8.8 qualification, every interface → 10.0.2.15, where the
# docker node served 192.168.77.x). Same precedence the docker node itself used: what the RUNNING node reports for the
# interface (its agent config inside the container), else the NODE_IFACES spec's endpoint field, else NODE_ENDPOINT.
# Usage: docker_iface_endpoints "<names>" <node-endpoint> "<NODE_IFACES spec>"
docker_iface_endpoints(){ local names="$1" nep="$2" specs="$3" live n ep e out=""
  live="$(docker exec swg-node cat /etc/swg-agent/config.json 2>/dev/null | python3 -c '
import json, sys
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
for n, ic in (d.get("interfaces") or {}).items():
    e = (ic or {}).get("endpoint_host") or ""
    if e: print("%s=%s" % (n, e))' 2>/dev/null || true)"
  for n in $names; do
    ep="$(printf '%s\n' "$live" | sed -n "s/^$n=//p" | sed -n 1p)"
    if [ -z "$ep" ]; then for e in $(printf '%s' "$specs" | tr ',' ' '); do
      [ "${e%%:*}" = "$n" ] && { ep="$(printf '%s' "$e" | cut -d: -f5-)"; break; }; done; fi
    [ -n "$ep" ] || ep="$nep"
    ep="$(printf '%s' "$ep" | tr -cd 'A-Za-z0-9.:_[]-')"   # a host and nothing else — ',' and '=' frame the list
    case "$ep" in ""|127.*|localhost) continue;; esac       # never hand clients a loopback
    out="${out:+$out,}$n=$ep"
  done
  printf '%s' "$out"; }

detect_wan(){ ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | sed -n 1p || true; }   # || true: no default route → pipeline nonzero; caller falls back to eth0
# import a (docker) conf as a BARE-METAL conf: drop any PostUp/PostDown, then add host NAT (the bare
# datapath has no container to masquerade for it). Keys + Address + Amnezia params carry over.
# conf_privkey <conf> — its interface's private key (the one thing two copies of one interface's conf always share)
conf_privkey(){ sed -n 's/^[[:space:]]*PrivateKey[[:space:]]*=[[:space:]]*//p' "$1" 2>/dev/null | sed -n 1p | tr -d '[:space:]'; }
# same_iface_conf <a> <b> — 0 iff both confs hold the same private key: the same interface, however else they differ
same_iface_conf(){ local k; k="$(conf_privkey "$1")"; [ -n "$k" ] && [ "$k" = "$(conf_privkey "$2")" ]; }
# ⚠️ AN ADOPTED INTERFACE KEEPS ITS HOOKS — ITS OWN, NEVER OURS — ACROSS A CONVERT. A bare → Docker convert stripped every
# PostUp/PostDown, an adopted (#swg:onboarded) conf's too, and the bare original went with the switch: its hooks were gone
# for good. The way back wrote swg's NAT hooks INTO it (1.8.8 qualification, round 8; since 1.8.7). Its hooks run where
# they were written — on this host: install-docker.sh keeps the original, byte for byte, in
# /etc/swg-panel-confs.converted-<ts> (the container does not run them: a hook that fails there takes the interface down);
# coming back, they are put back from it — or from the host's own conf of it (a Docker node that adopted a host interface
# left that in place) — and nothing of ours is written into it: on bare metal an adopted interface's NAT is its own
# hooks' (swg adds none — as before the convert). The Docker original is kept byte for byte beside them, and one line
# says so. The container's own rule for it goes after the switch (reap_container_nat, below).
conf_is_adopted(){ grep -qE '^[[:space:]]*#swg:onboarded([[:space:]]|$)' "$1" 2>/dev/null; }
conf_hooks(){ awk 'tolower($0) ~ /^[[:space:]]*(pre|post)(up|down)[[:space:]]*=/' "$1" 2>/dev/null || true; }
# adopted_hooks_from <name> <docker conf> [<host conf>…] — the conf an adopted interface's own hooks come back from: a host
# conf of it (same key), else the newest original a bare → Docker convert kept. Prints its path, or nothing.
adopted_hooks_from(){ local nm="$1" src="$2" c; shift 2
  for c in "$@" $(ls -dt /etc/swg-panel-confs.converted-*/ 2>/dev/null | sed "s#/\$#/$nm.conf#"); do
    [ -f "$c" ] && same_iface_conf "$c" "$src" && [ -n "$(conf_hooks "$c")" ] && { printf '%s\n' "$c"; return 0; }
  done; return 0; }
# keep_docker_original <docker conf> — the adopted conf as the Docker node had it, byte for byte, in this run's backup
# (one directory per run: not called in a $(…), whose subshell would forget it). Sets KEPT_ORIG to the copy.
CONF_BACKUP=""; KEPT_ORIG=""
keep_docker_original(){ local nm; nm="$(basename "$1")"; KEPT_ORIG=""
  [ -n "${CONF_BACKUP:-}" ] || { CONF_BACKUP="/etc/swg-panel-confs.converted-$(date +%Y%m%d-%H%M%S 2>/dev/null || echo bak).from-docker"; mkdir -p "$CONF_BACKUP" && chmod 700 "$CONF_BACKUP"; }
  cp -p "$1" "$CONF_BACKUP/$nm" 2>/dev/null && chmod 600 "$CONF_BACKUP/$nm" 2>/dev/null && KEPT_ORIG="$CONF_BACKUP/$nm"; return 0; }
# adopted_import_line <name> <dest> <hooks-from or ""> <kept Docker original> — the one line an adopted interface gets
adopted_import_line(){
  if [ -n "$3" ]; then sub "imported $(b "$1") → $2 (adopted: its own hooks put back from $(b "$3"); nothing of ours in it — the Docker original is kept byte for byte in $(b "$4"))"
  else sub "imported $(b "$1") → $2 (adopted: no hooks of its own found, none of ours written — its NAT here is its own setup's, as before the convert; the Docker original is kept byte for byte in $(b "$4"))"; fi; }
# ⚠️ …AND THE CONTAINER'S RULE FOR IT GOES WITH THE CONTAINER. On Docker every interface is NATed by the node container's
# own tagged rule (docker/node-entrypoint.sh: swg-nat:<name>), and a stopped container leaves it in the host's table. A
# panel-made interface takes it over with its hooks (the same rule, reaped then added); an adopted one comes back with
# its OWN hooks, or none, and ours stayed beside them for good — a second MASQUERADE the box did not have before it went
# to Docker (1.8.8 qualification, round 9: a bare → Docker → bare round trip of an adopted wg9). Removed after the switch,
# unless the interface's own hooks carry that very tag (then the rule is theirs).
reap_container_nat(){   # <adopted interface…> → prints each name whose rule it removed
  [ $# -gt 0 ] || return 0
  python3 - "$@" <<'PYNAT' 2>/dev/null || true
import re, shlex, subprocess, sys
for nm in sys.argv[1:]:
    hooks = ""
    for c in ("/etc/amnezia/amneziawg/%s.conf" % nm, "/etc/wireguard/%s.conf" % nm):
        try:
            hooks = "".join(l for l in open(c, errors="replace") if re.match(r"\s*(pre|post)(up|down)\s*=", l, re.I))
            break
        except OSError:
            continue
    if re.search(r'swg-nat:(%s|%%i)(?=["\s;]|$)' % re.escape(nm), hooks):
        continue                                    # its own hooks carry our tag: the rule is theirs
    tag = re.compile(r'--comment "?%s"?(?=\s|$)' % re.escape("swg-nat:" + nm))
    out = subprocess.run(["iptables", "-t", "nat", "-S", "POSTROUTING"], capture_output=True, text=True).stdout
    gone = 0
    for ln in out.splitlines():
        if ln.startswith("-A POSTROUTING") and tag.search(ln):
            if subprocess.run(["iptables", "-t", "nat", "-D"] + shlex.split(ln)[1:], capture_output=True).returncode == 0:
                gone += 1
    if gone:
        print(nm)
PYNAT
}
# reap_adopted_container_nat <imported interface…> — after the switch: the ones that came back ADOPTED (their bare conf says
# so — a resumed convert included) lose the container's rule, and one line names them
reap_adopted_container_nat(){ local nm c ad="" gone
  for nm in "$@"; do for c in "/etc/amnezia/amneziawg/$nm.conf" "/etc/wireguard/$nm.conf"; do
    [ -f "$c" ] && conf_is_adopted "$c" && { ad="${ad:+$ad }$nm"; break; }; done; done
  [ -n "$ad" ] || return 0
  gone="$(reap_container_nat $ad | tr '\n' ' ')"; gone="${gone% }"
  [ -n "$gone" ] && sub "removed the Docker node's NAT rule for $(b "$gone") — an adopted interface's NAT here is its own hooks', as before the convert"
  return 0; }
import_bare_conf(){ # <src> <dest> [<conf whose hooks an ADOPTED src takes back>]
  local src="$1" dest="$2" orig="${3:-}" addr subnet wan up down
  if conf_is_adopted "$src"; then                         # its own hooks or none — never ours (see above)
    if [ -n "$orig" ]; then
      HOOKS="$(conf_hooks "$orig")" awk '
        tolower($0) ~ /^[[:space:]]*(pre|post)(up|down)[[:space:]]*=/ {next}
        {print}
        /^\[Interface\][[:space:]]*$/ && !d {if (ENVIRON["HOOKS"] != "") print ENVIRON["HOOKS"]; d=1}' "$src" > "$dest"
    else cp "$src" "$dest"; fi
    chmod 600 "$dest"; return 0
  fi
  addr="$(sed -n 's/^[[:space:]]*[Aa]ddress[[:space:]]*=//p' "$src" | sed -n 1p | sed 's/,.*//; s/[[:space:]]//g')"
  subnet="$(python3 -c 'import ipaddress,sys;print(ipaddress.ip_network(sys.argv[1],strict=False))' "$addr" 2>/dev/null || echo "$addr")"
  wan="$(detect_wan)"; [ -n "$wan" ] || wan=eth0
  up="$(nat_hook_up "${subnet}" "${wan}")"   # reap-then-add: one copy whatever was there (lib/common.sh)
  down="$(nat_hook_down "${subnet}" "${wan}")"
  awk -v up="$up" -v down="$down" '
    /^[[:space:]]*[Pp]ost(Up|Down)[[:space:]]*=/ {next}     # drop any existing NAT hooks
    {print}
    /^\[Interface\][[:space:]]*$/ && !d {print "PostUp = " up; print "PostDown = " down; d=1}
  ' "$src" > "$dest"
  chmod 600 "$dest"
}

# Lifecycle signalling is handled by lc_init (lib/common.sh): it's armed at the point we tell the panel
# "converting…", and its EXIT/INT traps then emit converted-* (success) / convert-aborted / convert-failed.
# docker→bare runs install-node.sh as a subprocess (this script stays in control → its trap fires); bare→docker
# execs install-docker.sh, which carries SWG_CONVERT_DIR so IT emits the terminal.

CHECK=no; [ "${1:-}" = --check ] && { CHECK=yes; shift; }
# Accept the spelling we PRINT. Every banner and sentence here says "bare-metal", so that is what people type —
# and it used to fall through to the catch-all "unsupported conversion", which named the very spelling it had
# just rejected and never said what it wanted instead. Normalise the obvious variants, and validate up front so
# a typo is answered with the accepted values rather than a dead end.
_norm_method(){ case "$(printf '%s' "${1:-}" | tr 'A-Z' 'a-z')" in
  bare-metal|bare_metal|bare|baremetal|metal|bm|host-os|native) echo baremetal;;
  docker|dockerized|dockerised|container|compose)               echo docker;;
  *) printf '%s' "${1:-}";; esac; }
_norm_role(){ case "$(printf '%s' "${1:-}" | tr 'A-Z' 'a-z')" in
  master|host-node|hostnode) echo master;; host|panel) echo host;; node|entry) echo node;;
  *) printf '%s' "${1:-}";; esac; }
_USAGE="usage: convert.sh [--check] <docker|baremetal> <docker|baremetal> <node|host|master>"
FROM="$(_norm_method "${1:-}")"; TO="$(_norm_method "${2:-}")"; ROLE="$(_norm_role "${3:-}")"
[ -n "$FROM" ] && [ -n "$TO" ] && [ -n "$ROLE" ] || die "$_USAGE"
# ⚠️ REFUSE WHAT WE DO NOT UNDERSTAND, and refuse `--dry-run` LOUDLY. This read $1 $2 $3 and dropped
# everything after them, so `convert.sh baremetal docker node --dry-run` printed the conversion banner and
# then CONVERTED — the one flag every sibling script honours, silently ignored by the one script whose work
# cannot be undone. It is not a typo an operator has to invent, either: `bootstrap.sh` collects unrecognised
# flags into `PASS` and hands them straight here (both convert call sites), and its `run_script` sets
# `_keep_tmp=1` the moment it sees `--dry-run` — so the front door prints "dry-run preview kept at …" about
# a conversion that has already happened.
#
# The answer is a refusal, not an implementation. A convert tears the old method down before the new one is
# up; rendering that under a $PREFIX the way the installers do would be a second, unexercised code path
# through the most destructive script here, which is a worse trade than one clear sentence. `--check` is the
# rehearsal this script actually has, so name it.
# ⚠️ ARGUMENTS FIRST, ROOT SECOND. Both are refusals and neither needs the other, but answering "run as
# root" to a command that is ALSO misspelled costs two round trips for one mistake — and it hides the more
# important of the two sentences behind a `sudo`. Parsing is pure string work; nothing has been touched yet.
# ⚠️ AND `-y` IS NOT AN UNKNOWN FLAG, IT IS THE FRONT DOOR'S. `bootstrap.sh` puts every flag it does not
# recognise into `PASS` and hands it to BOTH convert call sites, and `-y`/`--yes` is the documented
# unattended form of `update.sh` and `uninstall.sh` — so `bootstrap.sh node -y` on a box that has the other
# method installed reached here and died at argument parsing, after the operator had already answered the
# menu and the "proceed with the conversion" confirm. It used to be dropped in silence; refusing every
# unrecognised word turned that into a failed conversion for a flag the front door itself forwards.
# Accepted, and nothing more: this script asks no question of its own (the turn-proxy transfer questions belonged to
# a second migration path nothing called — removed, 1.8.9 qualification IN-5; the installers it runs ask theirs).
for _x in "${@:4}"; do case "$_x" in
  -y|--yes) ;;
  --dry-run) die "convert.sh has no dry run — a conversion cannot be rehearsed by rendering files, because it takes the old method down before the new one is up. Use $(b "convert.sh --check $FROM $TO $ROLE") for the port/interface pre-flight." ;;
  *) die "‘$_x’ isn't an option here. $_USAGE" ;;
esac; done
# ⚠️ ROOT, LIKE EVERY SIBLING. This was the one script here with no root check at all: it went straight
# into the pre-flight as an ordinary user, whose failed write probe made `declarative_host` call an Ubuntu
# box "managed declaratively", so the first thing anybody who forgot `sudo` saw was advice about NixOS
# modules. There is no `--dry-run` to exempt (see just above), so this is unconditional.
[ "$(id -u)" = 0 ] || die "run as root"
for _a in "FROM:$FROM" "TO:$TO"; do case "${_a#*:}" in docker|baremetal) :;;
  *) die "‘${_a#*:}’ isn't a method (${_a%%:*}). Use $(b docker) or $(b baremetal). $_USAGE";; esac; done
case "$ROLE" in node|host|master) :;; *) die "‘$ROLE’ isn't a role. Use $(b node), $(b host) or $(b master). $_USAGE";; esac
[ "$FROM" != "$TO" ] || die "nothing to convert: $FROM → $TO are the same. $_USAGE"

# prominent title — same look as the installers / update.sh (only on the real run, not the --check pre-flight)
if [ "$CHECK" != yes ]; then
  _fl="$([ "$FROM" = docker ] && echo DOCKER || echo BARE-METAL)"; _tl="$([ "$TO" = docker ] && echo DOCKER || echo BARE-METAL)"
  echo; info "SWG $_fl → $_tl CONVERSION ($ROLE)"; echo
  seal_archives   # every recovery archive an earlier build left becomes root's alone (lib/common.sh, F90)
fi

# ── crash/network-drop recovery ──────────────────────────────────────────────
# A convert tears the old method down before the new one is finished. If the session drops in between,
# the node's IDENTITY (token + panel URL) would be lost and the installer would start from scratch —
# orphaning the node on the panel. So we persist it to /var/lib/swg-recovery the moment a convert starts
# (BEFORE any teardown) and only delete it once the convert completes. bootstrap.sh sees this file on the
# next run and resumes the convert with the SAME identity instead of treating the box as a fresh install.
RECOVERY="/var/lib/swg-recovery"
RESUMING=no   # set when we picked up a recovery marker → this is finishing an interrupted convert, not a fresh one
if [ "$CHECK" != yes ] && [ -f "$RECOVERY" ]; then . "$RECOVERY" 2>/dev/null || true; RESUMING=yes; fi   # resume: the saved identity wins (the source may be half torn down)
write_recovery(){   # write_recovery <space-separated interface names>
  mkdir -p /var/lib 2>/dev/null || true
  ( umask 077   # 0600 from its first byte — it holds the node token
    { printf "SWG_RV_FROM='%s'\nSWG_RV_TO='%s'\nSWG_RV_ROLE='%s'\n" "$FROM" "$TO" "$ROLE"
      printf "SWG_RV_TOKEN='%s'\nSWG_RV_URL='%s'\nSWG_RV_EP='%s'\nSWG_RV_VERIFY='%s'\n" "$NTOK" "$PURL" "$NEP" "${NVERIFY:-no}"
      printf "SWG_RV_FP='%s'\n" "$(printf '%s' "${NFP:-}" | tr -cd '0-9A-Fa-f:')"   # the panel-cert pin (hex only — this file is sourced)
      printf "SWG_RV_NAMES='%s'\nSWG_RV_AT='%s'\n" "${1:-}" "$(date +%s 2>/dev/null || echo 0)"
    } > "$RECOVERY" ) 2>/dev/null && chmod 600 "$RECOVERY" 2>/dev/null || true
}
clear_recovery(){ rm -f "$RECOVERY" 2>/dev/null || true; }
# the per-server summary now lives in lib/common.sh (print_summary) — shared by every install / convert / update.
# a LIVE docker node = an actual swg-node container (running or stopped). A bare $DOCKER_DIR with no
# container is just a stale leftover (e.g. a previous convert that didn't finish moving it aside).
docker_node_present(){ command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -cx swg-node >/dev/null; }

# ── PANEL host conversion ──────────────────────────────────────────────────────
# The panel's state is the SAME JSON in both methods (one swg-panel-server binary); only the LOCATION differs:
#   /var/lib/swg-panel ↔ $DOCKER_DIR/data/lib  (roster users.json, nodes.json + node token HASHES, configs/)
#   /etc/swg-panel     ↔ $DOCKER_DIR/data/etc  (fleet.json, auth login, tls/ cert, acme/ renewal state)
#   /var/www/wgstats   ↔ $DOCKER_DIR/data/stats(status snapshots)
# So conversion is a copy-first state move + a port hand-off. URL/port/TLS/login are preserved so every node
# stays connected (nodes.json token hashes carry over). Master (panel + local node) conversion comes next.
docker_panel_present(){ command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -cx swg-panel >/dev/null; }
bare_panel_present(){ [ -f /etc/systemd/system/swg-panel-server.service ] || [ -x /opt/swg-panel/swg-panel-server ]; }
# teardown_bare_panel() now lives in lib/common.sh (so install-docker.sh can call it at the atomic switch).
# master convert: emit the lifecycle status to BOTH the panel header (host_proc file) and the local node tile
# (proc-status POST to the loopback panel), so "converting/converted" shows on the node too, not just the panel.
lc_emit_hostnode(){ lc_emit_file "$1" "${2:-}"; lc_emit_post "$1" "${2:-}"; }

# ── settings a Docker install keeps only in its .env, and the bare services read from their ENVIRONMENT ──────────
# SWG_LATEST_URL (the panel's release check — a box that follows dev) and SWG_TURN_MIRROR (the node's proxy for the
# turn-proxy downloads) reach a container from the .env and nowhere else; the bare services read the same variables
# from their environment, and a systemd drop-in is where a bare install keeps one. Nothing carried them, so a box
# converted to bare-metal went back to main's release check and the direct download, silently (1.8.8 qualification,
# round 7 — the mirror of what a convert BACK to Docker now keeps). Written as a drop-in THIS convert owns by its name:
# a later convert rewrites it, or removes it when the .env no longer sets anything; the uninstaller keeps the panel's
# as your own on "keep the data" and removes the node's with the node. The console's port and address come back the same
# way — CONSOLE_PORT / CONSOLE_BIND as SWG_PANEL_CONSOLE_PORT / _HOST, the names the bare panel reads — when they are not
# Docker's own defaults (8445, 127.0.0.1): a bare → Docker convert carried an operator's console drop-in into the .env,
# and the convert back dropped it (1.8.8 qualification, round 10, F95). (Every other .env key either has its bare home
# already — install.conf, the panel's settings, the node's config — or exists only for Docker: SWG_IMAGE_TAG,
# SWG_TURN_IMAGE, PULL_POLICY, SWG_NODE_SECCOMP, NODE_NET, TURN_MANAGE; a key compose does not pass reached nothing.)
DOTENV_DROPIN=50-swg-from-docker.conf
_dotenv_val(){ local v; v="$(sed -n "s/^$1=//p" "$2" 2>/dev/null | sed -n 1p)"   # as compose reads it: quotes, or a trailing ` # …`
  case "$v" in \"*) v="${v#\"}"; v="${v%%\"*}";; \'*) v="${v#\'}"; v="${v%%\'*}";;
               *) v="$(printf '%s' "$v" | sed 's/[[:space:]]\{1,\}#.*$//; s/[[:space:]]*$//')";; esac
  printf '%s' "$v"; }
carry_env_to_dropin(){ # <.env> <unit> <KEY | UNITKEY=ENVKEY/default/check…> — one line saying what it kept, and where
  local envf="$1" unit="$2" k v body="" names="" d f uk ek dflt chk; shift 2
  d="/etc/systemd/system/$unit.service.d"; f="$d/$DOTENV_DROPIN"
  for k in "$@"; do
    # KEY: the same name on both sides. UNITKEY=ENVKEY/default/check: the service reads UNITKEY, the .env holds ENVKEY,
    # Docker's own default is nothing of the operator's to keep, and a value that fails the check is named, not carried
    uk="$k"; ek="$k"; dflt=""; chk=""
    case "$k" in *=*) uk="${k%%=*}"; ek="${k#*=}"; IFS=/ read -r ek dflt chk <<< "$ek";; esac
    v="$(_dotenv_val "$ek" "$envf")"; [ -n "$v" ] || continue
    [ -n "$dflt" ] && [ "$v" = "$dflt" ] && continue
    if [ -n "$chk" ] && ! printf '%s' "$v" | grep -cxE "$chk" >/dev/null; then
      warn "the Docker .env's $ek ($v) is not a plain value — not carried; set $uk in a drop-in by hand if you need it"; continue; fi
    v="$(printf '%s' "$v" | sed 's/\\/\\\\/g; s/"/\\"/g; s/%/%%/g')"   # systemd: \ and " escaped inside "…", % is a specifier
    body="${body}Environment=\"$uk=$v\""$'\n'; names="${names:+$names, }$ek"
  done
  if [ -z "$body" ]; then   # nothing to keep: a drop-in an EARLIER convert wrote must not outlive the setting
    [ -f "$f" ] && { rm -f "$f"; rmdir "$d" 2>/dev/null || true; systemctl daemon-reload 2>/dev/null || true; }
    return 0
  fi
  mkdir -p "$d"
  { printf '# Kept from the Docker install this box was converted from — your own setting, carried by convert.sh.\n'
    printf '# Edit or remove it like any drop-in, then: systemctl daemon-reload && systemctl restart %s\n[Service]\n' "$unit"
    printf '%s' "$body"; } > "$f"
  chmod 644 "$f" 2>/dev/null || true
  systemctl daemon-reload 2>/dev/null || true
  sub "kept from the Docker .env: $names → $(b "$f")"
}
# ── …and the other way: what a BARE service holds in its own drop-ins, for the Docker .env (bare → docker) ───────────
# The mirror of carry_env_to_dropin. An operator's drop-in for swg-panel-server or swg-noded — SWG_LATEST_URL following
# dev, SWG_TURN_MIRROR, a console port — was deleted with the bare units (teardown_bare_panel, lc_teardown_baremetal),
# and the Docker box came up on main's release check and the direct download (1.8.8 qualification, round 7c). Every
# Environment= that the Docker side reads through its .env is carried: SWG_LATEST_URL and SWG_TURN_MIRROR as they are
# (SWG_CARRY_ENV → install-docker.sh), the console's SWG_PANEL_CONSOLE_PORT / _HOST as the installer's CONSOLE_PORT /
# CONSOLE_BIND. Anything else — another variable, another directive — is NAMED, and every such file is kept as it was in
# /etc/swg-panel-dropins.converted-<ts> (uninstall.sh counts /etc/swg-panel*.converted-* among the convert backups).
# Ours are not read: zz-swg-update.conf (the Update trigger; Docker has its own) and 10-swg-reach-sweep.conf (the node's
# downgrade sweep). 50-swg-from-docker.conf (an earlier Docker → bare convert's) IS read — it holds the operator's values —
# but never parked: it is our own file, and every Docker → bare → Docker trip parked it in a directory of its own (1.8.8
# qualification, round 8); its values reach the .env, and the Docker install it came from keeps them too.
# carry_dropins_to_env <carry-file> <unit…> — sets DROPIN_GIVE (assignments for install-docker.sh's env), says it in one line
DROPIN_GIVE=""
carry_dropins_to_env(){
  local carry="$1" park="/etc/swg-panel-dropins.converted-$(date +%Y%m%d-%H%M%S 2>/dev/null || echo bak)" out kept="" skip="" parked="" kind k v u f
  shift; : > "$carry"; DROPIN_GIVE=""
  out="$(python3 - "$@" <<'PY' 2>/dev/null || true
import glob, os, re, shlex, sys
OURS = {"swg-panel-server": {"zz-swg-update.conf"}, "swg-noded": {"10-swg-reach-sweep.conf"}}
# the Docker .env key each variable arrives through: carried as it is (C), or given to the installer as its own (G)
MAP = {"swg-panel-server": {"SWG_LATEST_URL": ("SWG_LATEST_URL", "C"), "SWG_PANEL_CONSOLE_PORT": ("CONSOLE_PORT", "G"),
                            "SWG_PANEL_CONSOLE_HOST": ("CONSOLE_BIND", "G")},
       "swg-noded": {"SWG_TURN_MIRROR": ("SWG_TURN_MIRROR", "C")}}
SAFE_G = {"CONSOLE_PORT": r"[0-9]{1,5}", "CONSOLE_BIND": r"[0-9A-Fa-f.:]{2,45}"}
for unit in sys.argv[1:]:
    for f in sorted(glob.glob("/etc/systemd/system/%s.service.d/*.conf" % unit)):
        name = os.path.basename(f)
        if name in OURS.get(unit, ()):
            continue
        if name != "50-swg-from-docker.conf":
            print("FILE\t%s\t%s" % (unit, f))            # the operator's file → kept, as it was, in the parking place
        env, other = {}, []
        for ln in open(f, errors="replace").read().splitlines():
            st = ln.strip()
            if not st or st[0] in "#;" or st.startswith("["):
                continue
            k, _, v = st.partition("=")
            if k.strip() != "Environment":
                other.append(k.strip() + "="); continue
            if not v.strip():
                env.clear(); continue                     # an empty Environment= resets the list, as systemd reads it
            try:
                words = shlex.split(v, posix=True)
            except ValueError:
                other.append("Environment= (unreadable)"); continue
            for w in words:
                kk, eq, vv = w.partition("=")
                if eq:
                    env[kk] = vv.replace("%%", "%")
        for kk, vv in env.items():
            m = MAP.get(unit, {}).get(kk)
            if not m:
                print("SKIP\t%s\t%s" % (name, kk)); continue
            key, how = m
            if how == "G" and not re.fullmatch(SAFE_G[key], vv):
                print("SKIP\t%s\t%s: not a plain value" % (name, kk)); continue
            if how == "C" and ("'" in vv or "\n" in vv):
                print("SKIP\t%s\t%s: a quote the .env cannot hold" % (name, kk)); continue
            print("%s\t%s\t%s" % ("CARRY" if how == "C" else "GIVE", key, vv))
        for o in other:
            print("SKIP\t%s\t%s" % (name, o))
PY
)"
  [ -n "$out" ] || return 0
  while IFS="$(printf '\t')" read -r kind k v; do
    case "$kind" in
      FILE)  u="$k"; f="$v"; mkdir -p "$park/$u.service.d" && chmod 700 "$park" && cp -p "$f" "$park/$u.service.d/" \
               && chmod 600 "$park/$u.service.d/$(basename "$f")" && parked=yes ;;
      CARRY) grep -q "^$k=" "$carry" 2>/dev/null || { printf "%s='%s'\n" "$k" "$v" >> "$carry"; kept="${kept:+$kept, }$k"; } ;;
      GIVE)  DROPIN_GIVE="${DROPIN_GIVE:+$DROPIN_GIVE }$k=$v"; kept="${kept:+$kept, }$k" ;;
      SKIP)  skip="${skip:+$skip, }$v ($k)" ;;
    esac
  done <<EOF
$out
EOF
  [ -n "$kept$skip$parked" ] || return 0                 # only our own file, nothing of the operator's to say
  sub "kept from the bare-metal drop-ins: ${kept:-nothing the Docker side reads}$([ -n "$kept" ] && printf ' (→ the Docker .env)')$([ -n "$skip" ] && printf '; not carried: %s' "$skip")$([ -n "$parked" ] && printf ' — the drop-in files are kept as they were in %s' "$(b "$park")")"
}
# The node's client DNS (the DNS line of the configs the panel makes for its interfaces, unless set in the panel) is an
# install setting on both sides — the Docker .env's DNS, the bare node's config "dns" — and neither convert carried it:
# a node set to its own resolver came out on 1.1.1.1. Only a plain address list is carried (it is written into JSON).
_dns_ok(){ printf '%s' "$1" | grep -cE '^[0-9A-Za-z.:, _-]{1,200}$' >/dev/null; }

if { [ "$ROLE" = host ] || [ "$ROLE" = master ]; } && [ "$FROM" = baremetal ] && [ "$TO" = docker ]; then
  ETC=/etc/swg-panel; STATE=/var/lib/swg-panel; STATS=/var/www/wgstats; pconf="$ETC/install.conf"; PROFILE="$ROLE"
  bare_panel_present || [ -n "${SWG_RV_URL:-}" ] || die "no bare-metal panel found (swg-panel-server missing)"
  gv(){ sed -n "s/^$1=//p" "$pconf" 2>/dev/null | sed -n 1p || true; }   # || true: a missing install.conf must fall through to recovery state, not abort under pipefail+set -e
  PDOM="$(gv PANEL_DOMAIN)"; PPORT="$(gv PORT)"; PTLS="$(gv TLS_MODE)"; PEMAIL="$(gv ACME_EMAIL)"; PBASE="$(gv PANEL_BASE)"
  PCFTOKEN="$(gv CF_TOKEN)"; PCFORIGIN="$(gv CF_ORIGIN_TOKEN)"   # carry CF creds so cloudflare/cf15 renewal works in the container
  PSERVE="$(gv SERVE_MODE)"; PSUBDOM="$(gv SUB_DOMAIN)"
  # A bare-metal REVERSE-PROXY panel (nginx/caddy/skip serve mode) → docker plain-HTTP-behind-proxy: TLS=none +
  # containers on loopback, so the operator's existing nginx/Caddy keeps reaching them on the same port. (Docker
  # conflates serve+cert into one TLS var, so the serve mode maps here.)
  _PBIND=0.0.0.0; _SBIND=0.0.0.0; _SXFF=0; _RVPROXY=no
  case "$PSERVE" in nginx|caddy|skip) _RVPROXY=yes; PTLS=none; _PBIND=127.0.0.1; _SBIND=127.0.0.1; _SXFF=1;; esac
  # env passed to install-docker so TLS=none + the loopback binds win over its defaults (a reverse-proxy convert)
  _RVENV=""; [ "$_RVPROXY" = yes ] && _RVENV="TLS=none PANEL_BIND=127.0.0.1 SUB_BIND=127.0.0.1 SUB_TRUST_XFF=1 SUB_DOMAIN=$PSUBDOM"
  PUSER="$(sed -n 's/^\([^:]*\):.*/\1/p' "$ETC/auth" 2>/dev/null | sed -n 1p || true)"   # || true: missing auth file must not abort under pipefail+set -e
  [ -n "${SWG_RV_URL:-}" ] && PDOM="${PDOM:-$SWG_RV_URL}"
  [ -n "$PDOM" ] || die "couldn't read the panel domain ($pconf missing and no recovery state)"
  case "$PTLS" in letsencrypt|letsencrypt-ip|cloudflare|cf15|selfsigned|none) :;; *) PTLS=selfsigned;; esac
  [ -n "$PPORT" ] || PPORT=443
  # The co-located node dials the STABLE loopback, never the public port: a later address change never moves it,
  # which is the whole reason PANEL_LOCAL_PORT exists. The convert used to hand it https://127.0.0.1:<public>,
  # so the first address change after a convert would have stranded it — the exact failure that port prevents.
  PLOCALPORT="$(gv LOCAL_PORT)"; [ -n "$PLOCALPORT" ] || PLOCALPORT=8088
  # The sub's port: the PANEL is the source of truth, not install.conf. install.conf records the value from
  # INSTALL time, but the operator changes the sub address later in Settings → Access & TLS, which writes
  # panel-settings.json — install.conf is only refreshed for the PANEL url (persist-url), never for the sub. Read
  # the live value first and fall back. (Observed: install.conf said 8444 while the panel had served 2087 for
  # hours, so the convert published the sub on a port nothing advertised.)
  # Heredoc body sits at column 0 — indenting a python program to match the shell block is an IndentationError,
  # and `2>/dev/null` would hide it and silently fall back to install.conf's stale value.
  PSUBPORT="$(python3 - <<'PY' 2>/dev/null | tr -dc '0-9'
import json
d = json.load(open("/var/lib/swg-panel/panel-settings.json"))
print(((d.get("access") or {}).get("sub") or {}).get("port") or "")
PY
)"
  [ -n "$PSUBPORT" ] || PSUBPORT="$(gv SUB_PORT)"
  [ -n "$PSUBPORT" ] || PSUBPORT=8444
  docker_panel_present && die "a docker panel (swg-panel container) already exists — remove it first"

  # MASTER: also read the co-located node's identity (preserve its token so the panel keeps the same node) +
  # its interface confs (imported below). The local node reaches the panel on the compose net (swg-panel:8443).
  NTOK=""; NEP=""; mifaces=""; NDNS=""
  if [ "$ROLE" = master ] && command -v python3 >/dev/null 2>&1 && [ -f /etc/swg-agent/config.json ]; then
    NTOK="$(python3 -c 'import json;print((json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("token","") or "")' 2>/dev/null || true)"
    NEP="$(python3 -c 'import json;print(json.load(open("/etc/swg-agent/config.json")).get("endpoint_host","") or "")' 2>/dev/null || true)"
    NDNS="$(python3 -c 'import json;d=json.load(open("/etc/swg-agent/config.json")).get("dns");print(str(d[0]).strip() if isinstance(d,list) and d else "")' 2>/dev/null || true)"
    _dns_ok "$NDNS" || NDNS=""   # the local node's client DNS (see _dns_ok)
    mifaces="$(python3 - <<'PY' 2>/dev/null
import json
try: c=json.load(open("/etc/swg-agent/config.json"))
except Exception: c={}
for n,ic in (c.get("interfaces") or {}).items():
    if (ic.get("conf") or ""): print(n+"\t"+ic["conf"])
PY
)"
  fi

  if [ "$CHECK" = yes ]; then
    [ -e "$DOCKER_DIR" ] && info "note: a leftover $(b "$DOCKER_DIR") will be moved aside."
    command -v docker >/dev/null 2>&1 || info "note: Docker isn't installed on this box yet — the conversion installs it first (get.docker.com), before anything else is touched."
    sub "pre-flight OK"
    if [ "$ROLE" = master ]; then info "Master → docker keeps: URL $(b "$PDOM"), login, roster, nodes, the $(b "$PTLS") cert AND the local node (token + interfaces + turn-proxies). Brief downtime at the switch."
    else info "Panel → docker keeps: URL $(b "$PDOM"), login, roster, nodes + the $(b "$PTLS") cert. Brief panel downtime at the switch (nodes self-heal)."; fi
    exit 0
  fi
  # ⚠️ DOCKER IS INSTALLED HERE, NOT REFUSED. A bare-metal box asked to become a Docker one usually has no Docker
  # yet: the pre-flight said "OK", the operator said yes, and this line answered "docker is required" (1.8.8
  # qualification, a fresh 1.8.7 master VM) — while install-docker.sh, which this hands off to, installs it for a
  # fresh install. Installed and proven BEFORE the recovery marker and the staging below, so a failure leaves the
  # bare-metal install untouched and nothing to resume.
  if ! command -v docker >/dev/null 2>&1; then
    info "installing Docker (get.docker.com) — nothing else has been touched yet"
    sh -c "curl -fsSL https://get.docker.com | sh" \
      || die "Docker could not be installed — nothing has been changed, and your bare-metal install is still serving. Install it by hand (curl -fsSL https://get.docker.com | sh) and re-run."
  fi
  if ! docker info >/dev/null 2>&1; then
    systemctl start docker >/dev/null 2>&1 || true
    for _dwait in 1 2 3 4 5 6 7 8 9 10; do docker info >/dev/null 2>&1 && break; sleep 1; done
    docker info >/dev/null 2>&1 || die "the Docker daemon isn't running (docker info failed). Start it with $(b 'systemctl start docker') and re-run — nothing has been changed, and your bare-metal install is still serving."
  fi

  info "Converting the bare-metal $(b "$ROLE") → docker — keeping the panel's URL/login/roster/nodes/cert$([ "$ROLE" = master ] && echo " and the local node")."
  PURL="$PDOM"; write_recovery ""   # persist FROM/TO/ROLE for resume BEFORE any teardown
  # panel HEADER status: converting → converted-docker (+ convert-aborted/-failed on a bad exit). The bare panel
  # serves /var/lib/swg-panel/host_proc now (and it gets staged into the container); we repoint LC_FILE at the
  # container's host_proc after the switch so the success/failure terminal lands where the docker panel reads it.
  LC_FILE=/var/lib/swg-panel/host_proc
  if [ "$ROLE" = master ] && [ -n "$NTOK" ]; then   # MASTER: status on BOTH the panel header (file) AND the local node tile (POST to the loopback panel)
    LC_URL="https://127.0.0.1:$PPORT"; LC_TOKEN="$NTOK"; LC_VERIFY=no; LC_FP=""   # loopback: this box's own panel
    lc_init convert-docker lc_emit_hostnode
  else
    lc_init convert-docker lc_emit_file
  fi
  if [ "$RESUMING" != yes ] && [ -e "$DOCKER_DIR" ]; then
    _bak="$DOCKER_DIR.pre-convert-$(date +%Y%m%d-%H%M%S 2>/dev/null || echo bak)"
    mv "$DOCKER_DIR" "$_bak" 2>/dev/null && { seal_archive "$_bak"; info "moved a leftover $(b "$DOCKER_DIR") aside → $(b "$_bak")"; } || rm -rf "$DOCKER_DIR" 2>/dev/null || true
  fi

  # 1) COPY-FIRST: stage the panel state while the bare panel is STILL UP + serving every node
  mkdir -p "$DOCKER_DIR"/data/lib "$DOCKER_DIR"/data/etc "$DOCKER_DIR"/data/stats
  [ -d "$STATE" ] && cp -a "$STATE/." "$DOCKER_DIR/data/lib/"   2>/dev/null || true   # roster, nodes.json, configs
  [ -d "$ETC" ]   && cp -a "$ETC/."   "$DOCKER_DIR/data/etc/"   2>/dev/null || true   # fleet.json, auth, tls/
  [ -d "$STATS" ] && cp -a "$STATS/." "$DOCKER_DIR/data/stats/" 2>/dev/null || true   # status snapshots + health-*.rrd graph history
  _rrd_src=$(find "$STATS" -maxdepth 1 -name 'health-*.rrd' 2>/dev/null | wc -l | tr -d ' ' || true); _rrd_dst=$(find "$DOCKER_DIR/data/stats" -maxdepth 1 -name 'health-*.rrd' 2>/dev/null | wc -l | tr -d ' ' || true)   # || true: $STATS may be absent (find exits nonzero); wc still prints 0
  [ "${_rrd_src:-0}" -gt 0 ] && [ "${_rrd_dst:-0}" -lt "${_rrd_src:-0}" ] && warn "health graphs: staged ${_rrd_dst:-0}/${_rrd_src} rrd file(s) — some history may not have transferred"
  # carry the acme.sh renewal state (bare keeps it in /root/.acme.sh; the container reads data/etc/acme) and
  # point its stored reload command at the container (kill -HUP 1) instead of the systemd unit, so renewals reload.
  for _ah in /root/.acme.sh "${HOME:-/root}/.acme.sh"; do [ -d "$_ah" ] && { mkdir -p "$DOCKER_DIR/data/etc/acme"; cp -a "$_ah/." "$DOCKER_DIR/data/etc/acme/" 2>/dev/null || true; break; }; done
  find "$DOCKER_DIR/data/etc/acme" -name '*.conf' -exec sed -i "s#^Le_ReloadCmd=.*#Le_ReloadCmd='kill -HUP 1'#" {} + 2>/dev/null || true
  # ...and its LOG_FILE, which is an ABSOLUTE path to the home it was written on. Left alone, every acme run
  # in the container writes to a directory that does not exist there and each one prints a shell error per
  # line it tried to log — observed as ~20 "No such file or directory" lines on every single renewal pass,
  # burying the one line that actually said what failed.
  sed -i "s#^LOG_FILE=.*#LOG_FILE='/etc/swg-panel/acme/acme.sh.log'#" \
    "$DOCKER_DIR/data/etc/acme/account.conf" 2>/dev/null || true
  sub "staged roster + nodes + login + $(b "$PTLS") cert + ${_rrd_dst:-0} health graph(s) (+ acme renewal) → $DOCKER_DIR/data"

  # MASTER: the local node's interfaces + turn-proxies are migrated in the NODE STAGE (the install-docker node
  # sub-step below): migrate_baremetal_ifaces + migrate_baremetal_turns each ask "Transfer? (Y/n)" and copy-first.
  # So convert.sh stages ONLY the panel here — no node items before the host (nothing to orphan if interrupted).

  # 2) stage the compose project (prebuilt image pulled from GHCR)
  cp -a "$SRC/docker-compose.yml" "$DOCKER_DIR/" 2>/dev/null || true
  for f in Dockerfile Dockerfile.node .dockerignore VERSION swg-panel-server swg-agent swg-noded index.html app.css app.js reconcile.js; do
    [ -e "$SRC/$f" ] && cp -a "$SRC/$f" "$DOCKER_DIR/" 2>/dev/null || true; done
  [ -d "$SRC/vendor" ] && cp -a "$SRC/vendor" "$DOCKER_DIR/" 2>/dev/null || true
  [ -d "$SRC/js" ] && cp -a "$SRC/js" "$DOCKER_DIR/" 2>/dev/null || true   # js/ = the SPA's ES modules (docs/APP-JS-SPLIT-PLAN.md) — copied as a DIRECTORY, like vendor/, so adding a module never touches this loop
  [ -d "$SRC/docker" ] && cp -a "$SRC/docker" "$DOCKER_DIR/" 2>/dev/null || true

  # 3) .env — login (auth file) + cert are PRESERVED in data/etc so the entrypoint keeps them; PANEL_PASSWORD is
  #    an unused placeholder (compose requires it). For a master the node section carries the local node's token +
  #    endpoint and points it at the panel on the compose network. Same URL/port/TLS ⇒ nodes stay connected.
  # the swg-node service marks PANEL_URL/NODE_TOKEN/NODE_ENDPOINT REQUIRED, and compose interpolates ALL services
  # even for `--profile host` — so a host convert must still give them non-empty PLACEHOLDERS (the node never
  # starts on a host). A master fills them with the real local-node identity.
  _nurl="https://swg-panel:8443"; _ntok="${NTOK:-set-in-nodes-screen}"; _nep="${NEP:-$PDOM}"
  cat > "$DOCKER_DIR/.env" <<EOF
# generated by convert.sh (bare-metal → docker) — profile: $PROFILE
PANEL_PASSWORD=converted-login-preserved
PANEL_USER=${PUSER:-admin}
PANEL_DOMAIN=$PDOM
PANEL_BASE=$PBASE
TLS=$PTLS
ACME_EMAIL=$PEMAIL
CF_TOKEN=$PCFTOKEN
CF_ORIGIN_TOKEN=$PCFORIGIN
PANEL_PORT=$PPORT
PANEL_BIND=$_PBIND
SUB_BIND=$_SBIND
SUB_TRUST_XFF=$_SXFF
SUB_DOMAIN=$PSUBDOM
PANEL_URL=$_nurl
NODE_TOKEN=$_ntok
NODE_ENDPOINT=$_nep
TLS_VERIFY=no
EOF
  chmod 600 "$DOCKER_DIR/.env"

  # 4) hand off to install-docker.sh — it imports the staged .env (EXISTING_DOCKER → URL/TLS/login/token
  #    default to the preserved values), shows the PANEL + NODE setup (Step 1 interfaces, Step 2 turn-proxies),
  #    then as its LAST step does the atomic switch: stop the bare panel (SWG_CONVERT_KILL_PANEL) + bare node +
  #    migrated turn units, then compose up. KEEP_AUTH preserves the staged login. Mirrors the node convert.
  write_recovery "$mifaces"
  # Do NOT pass TLS: ask_choice treats an already-set value as the answer, so ANY value here prints the whole
  # certificate menu with no question under it and silently picks for the operator. install-docker already
  # defaults to "reuse" whenever the staged data/etc/tls covers this URL — which is exactly the carry-over we
  # want — so leaving it unset gives a real prompt with the right default preselected, and Enter keeps the cert.
  # $_RVENV still sets TLS=none for a reverse-proxy convert: that one IS a deliberate non-interactive override.
  # the operator's own drop-ins for the bare panel (and a master's node) → the Docker .env (carry_dropins_to_env)
  _carry="$(mktemp 2>/dev/null || echo /tmp/swg-carry.$$)"
  if [ "$ROLE" = master ]; then carry_dropins_to_env "$_carry" swg-panel-server swg-noded; else carry_dropins_to_env "$_carry" swg-panel-server; fi
  # ── HOST convert: exec install-docker host (panel only) — it owns the lifecycle terminal. ──
  if [ "$ROLE" = host ]; then
    info "Running install-docker.sh (host) — the panel setup; it switches over as the last step…"; echo
    lc_handoff
    exec env ROLE=host ACME_EMAIL="$PEMAIL" $_RVENV SUB_PORT="$PSUBPORT" PANEL_LOCAL_PORT="$PLOCALPORT" SWG_CONVERT_DIR=convert-docker SWG_CONVERT_KILL_PANEL=1 TLS_VERIFY=no \
         SWG_CARRY_ENV="$_carry" $DROPIN_GIVE bash "$SRC/install-docker.sh" host
  fi
  # ── MASTER convert = the HOST converter + the NODE converter, run in sequence ───────────────────────────────
  # The master's host-part IS install-docker host and its node-part IS install-docker node — guaranteed identical
  # to the individual converters, no bespoke master path. install-docker host brings up swg-panel + tears down the
  # bare panel; install-docker node then ADDS swg-node to the SAME compose project (EXISTING_DOCKER reads the .env)
  # and migrates this box's interfaces + turn-proxies in its own node stage. convert.sh owns the lifecycle terminal
  # (SWG_LC_PARENT=1 ⇒ neither sub-step emits its own), writing 'converted-docker' with the final line below.
  echo; info "HOST → docker — converting the panel (the local node keeps serving until the node step below)…"; echo
  env ROLE=host ACME_EMAIL="$PEMAIL" $_RVENV SUB_PORT="$PSUBPORT" PANEL_LOCAL_PORT="$PLOCALPORT" SWG_CONVERT_DIR=convert-docker SWG_CONVERT_KILL_PANEL=1 SWG_LC_PARENT=1 TLS_VERIFY=no \
      SWG_CARRY_ENV="$_carry" $DROPIN_GIVE bash "$SRC/install-docker.sh" host \
    || die "the panel (host) convert failed — your state is safe in $DOCKER_DIR/data; check 'docker compose logs'"
  LC_FILE="$DOCKER_DIR/data/lib/host_proc"   # docker panel now owns host_proc → convert.sh's EXIT terminal lands there
  # MIRRORS docker→bare: the panel (host) is converted the moment the docker panel ANSWERS — wait for it to actually
  # serve (so the stamp doesn't age out before the console's first poll), flip the header tile to "converted" NOW,
  # and repoint the lifecycle emit to the node tile so the EXIT trap finishes the NODE's terminal after the step below.
  for _i in $(seq 1 30); do curl -sk -o /dev/null --max-time 2 "https://127.0.0.1:${PPORT}${PBASE}/" 2>/dev/null && break; sleep 1; done
  lc_emit_file converted-docker; LC_EMIT=lc_emit_post
  echo; info "NODE → docker — converting this box's local node (adds swg-node to the panel's compose project)…"; echo
  # CO-LOCATED node specifics (a standalone node doesn't need these): reach the LOCAL panel on the host-published
  # port (host networking can't resolve the compose name swg-panel), and manage turns via the panel (socket) so the
  # migrated turn-proxies materialise as containers. NODE_TOKEN/ENDPOINT are the preserved local-node identity.
  env SWG_CONVERT_DIR=convert-docker NODE_TOKEN="${NTOK:-}" NODE_ENDPOINT="${NEP:-$PDOM}" \
      PANEL_URL="http://127.0.0.1:${PLOCALPORT:-8088}" TURN_MANAGE=panel SWG_LC_PARENT=1 TLS_VERIFY=no ${NDNS:+DNS="$NDNS"} \
      SWG_CARRY_ENV="$_carry" bash "$SRC/install-docker.sh" node \
    || warn "the local node convert reported an error — check it on the panel."
  clear_recovery
  echo; ok "$(b master) converted to docker — panel + local node (host convert + node convert). Same login, roster, nodes + cert + local node. Nodes reconnect on their next sync."
  print_summary CONVERSION both   # bare→docker master: both the panel + the local node converted
  exit 0
fi

# ── PANEL host/master: docker → bare-metal ── (mirror of the bare→docker block; reuses install-host.sh + install-node.sh)
if { [ "$ROLE" = host ] || [ "$ROLE" = master ]; } && [ "$FROM" = docker ] && [ "$TO" = baremetal ]; then
  ETC=/etc/swg-panel; STATE=/var/lib/swg-panel; STATS=/var/www/wgstats; envf="$DOCKER_DIR/.env"
  [ -f "$envf" ] || [ -n "${SWG_RV_URL:-}" ] || die "no docker panel settings found at $envf"
  getv(){ sed -n "s/^$1=//p" "$envf" 2>/dev/null | sed -n 1p | sed 's/^"//; s/"$//' || true; }   # || true: a missing .env must fall through to recovery state, not abort under pipefail+set -e
  PDOM="$(getv PANEL_DOMAIN)"; PPORT="$(getv PANEL_PORT)"; PTLS="$(getv TLS)"; PEMAIL="$(getv ACME_EMAIL)"
  PBASE="$(getv PANEL_BASE)"; PUSER="$(getv PANEL_USER)"; PCFT="$(getv CF_TOKEN)"; PCFO="$(getv CF_ORIGIN_TOKEN)"
  # awk $1: some .env lines carry an inline "# comment" (e.g. PANEL_LOCAL_PORT=8088  # …) — take just the value, else
  # it leaks into the unquoted env passed to install-host and env chokes on the '#'.
  PSUBPORT="$(getv SUB_PORT | awk '{print $1}')"; [ -n "$PSUBPORT" ] || PSUBPORT=8444   # the docker sub's published port → the bare swg-sub's bind
  PLOCALPORT="$(getv PANEL_LOCAL_PORT | awk '{print $1}')"; [ -n "$PLOCALPORT" ] || PLOCALPORT=8088   # the co-located node's loopback dial port
  NTOK="$(getv NODE_TOKEN)"; NEP="$(getv NODE_ENDPOINT)"   # master: the local node's preserved identity
  # fallback: a docker master's node token should be in .env, but if it's blank/placeholder read it straight from
  # the running node container so the local-node tile reliably gets "converting" at the START (matches bare→docker).
  case "${NTOK:-}" in ""|set-in-nodes-screen) NTOK="$(docker exec swg-node sh -c 'cat /etc/swg-agent/config.json' 2>/dev/null | python3 -c 'import json,sys;print((json.load(sys.stdin).get("panel") or {}).get("token","") or "")' 2>/dev/null || true)";; esac
  [ -n "${SWG_RV_URL:-}" ] && PDOM="${PDOM:-$SWG_RV_URL}"
  [ -n "$PDOM" ] || die "couldn't read the panel domain (docker .env missing and no recovery state)"
  case "$PTLS" in letsencrypt|letsencrypt-ip|cloudflare|cf15|selfsigned|none) :;; *) PTLS=selfsigned;; esac
  # the .env's TLS can be blank/stale (it just defaulted to "selfsigned") — when it claims no real CA, look at the
  # cert ACTUALLY in use (the container's openssl) so we report the truth: a real Let's Encrypt cert must not show
  # as "selfsigned" (and $PTLS also drives install-host's renewal setup). A valid CA value in .env is trusted as-is.
  case "$PTLS" in
    selfsigned|none)
      case "$(docker exec swg-panel sh -c 'openssl x509 -in /etc/swg-panel/tls/fullchain.pem -noout -issuer 2>/dev/null' 2>/dev/null || true)" in
        *"Let's Encrypt"*)          PTLS=letsencrypt ;;
        *Cloudflare*|*CloudFlare*)  PTLS=cf15 ;;
      esac ;;
  esac
  [ -n "$PPORT" ] || PPORT=443
  [ "$RESUMING" != yes ] && bare_panel_present && die "a bare-metal panel (swg-panel-server) already exists — remove it first"

  if [ "$CHECK" = yes ]; then
    sub "pre-flight OK"
    if [ "$ROLE" = master ]; then info "Master → bare-metal keeps: URL $(b "$PDOM"), login, roster, nodes, the $(b "$PTLS") cert AND the local node (token + interfaces + turn-proxies). Brief downtime at the switch."
    else info "Panel → bare-metal keeps: URL $(b "$PDOM"), login, roster, nodes + the $(b "$PTLS") cert. Brief panel downtime at the switch (nodes self-heal)."; fi
    exit 0
  fi

  info "Converting the docker $(b "$ROLE") → bare-metal — keeping the panel's URL/login/roster/nodes/cert$([ "$ROLE" = master ] && echo " and the local node")."
  PURL="$PDOM"; write_recovery ""
  # panel HEADER status during the convert: show "converting to bare-metal" on the still-running docker panel
  # (install-host then continues it on the bare panel as converting-bare → converted-bare / convert-aborted/-failed).
  docker exec swg-panel sh -c 'printf "%s" converting-bare > /var/lib/swg-panel/host_proc' >/dev/null 2>&1 || true
  # convert.sh OWNS the lifecycle terminal so "converted-bare" lands WITH the final summary below — NOT when
  # install-host exits mid-flow (esp. a master, where the node phase still follows). Emit "converting" to the bare
  # host_proc (the docker panel header already shows it above; install-host serves this file after the switch) AND,
  # for a master, the local-node tile — NOW, right after the proceed-confirm. install-host runs with SWG_LC_PARENT=1
  # so it does NOT emit its own terminal; convert.sh's EXIT trap emits converted/aborted/failed at the very end.
  LC_FILE="$STATE/host_proc"
  if [ "$ROLE" = master ] && [ -n "$NTOK" ]; then LC_URL="https://127.0.0.1:$PPORT"; LC_TOKEN="$NTOK"; LC_VERIFY=no; LC_FP=""; lc_init convert-bare lc_emit_hostnode
  else lc_init convert-bare lc_emit_file; fi

  # 1) COPY-FIRST: stage the panel state to the bare locations while the container is STILL UP + serving
  mkdir -p "$STATE" "$ETC" "$STATS"
  # Read the panel state straight OUT of the RUNNING container via tar — NOT `docker cp`. docker cp resolves a
  # bind-mounted path to its HOST source, which a prior back-and-forth convert may have moved aside (mv of the docker
  # dir while the container runs) — leaving the host source EMPTY while the container still serves the data by inode.
  # tar runs inside the container's mount namespace, so it always reads the LIVE data the panel is actually using.
  # Fall back to ./data on disk only when the container isn't found (e.g. a resume after it's already gone).
  _rrd_src=0
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -cx swg-panel >/dev/null; then
    _rrd_src=$(docker exec swg-panel sh -c 'ls /var/www/wgstats/health-*.rrd 2>/dev/null | wc -l' 2>/dev/null | tr -d ' '); _rrd_src=${_rrd_src:-0}
    docker exec swg-panel tar c -C /var/lib/swg-panel . 2>/dev/null | tar x -C "$STATE" 2>/dev/null || true   # roster (users.json), nodes.json, configs
    docker exec swg-panel tar c -C /etc/swg-panel   . 2>/dev/null | tar x -C "$ETC"   2>/dev/null || true   # fleet.json, auth, tls/, acme/
    docker exec swg-panel tar c -C /var/www/wgstats . 2>/dev/null | tar x -C "$STATS" 2>/dev/null || true   # status snapshots + health-*.rrd graph history
  else
    [ -d "$DOCKER_DIR/data/lib" ]   && cp -a "$DOCKER_DIR/data/lib/."   "$STATE/" 2>/dev/null || true
    [ -d "$DOCKER_DIR/data/etc" ]   && cp -a "$DOCKER_DIR/data/etc/."   "$ETC/"   2>/dev/null || true
    [ -d "$DOCKER_DIR/data/stats" ] && { cp -a "$DOCKER_DIR/data/stats/." "$STATS/" 2>/dev/null || true; _rrd_src=$(find "$DOCKER_DIR/data/stats" -maxdepth 1 -name 'health-*.rrd' 2>/dev/null | wc -l | tr -d ' '); }
  fi
  _rrd_dst=$(find "$STATS" -maxdepth 1 -name 'health-*.rrd' 2>/dev/null | wc -l | tr -d ' ')
  sub "staged roster + nodes + login + cert + ${_rrd_dst:-0} health graph(s) → bare-metal"
  # only a SHORTFALL is a problem: the destination can legitimately hold more (graphs from an earlier install that
  # the copy didn't overwrite), and "transferred 2/1" read like a bug in the counting rather than a note.
  [ "${_rrd_src:-0}" -gt 0 ] && [ "${_rrd_dst:-0}" -lt "${_rrd_src:-0}" ] && warn "health graphs: transferred ${_rrd_dst:-0}/${_rrd_src} rrd file(s) — some node-health history may be missing"
  # GUARD: never proceed (and let install-host seed a blank panel) if the login + node store didn't come across.
  { [ -s "$ETC/auth" ] && [ -f "$STATE/nodes.json" ]; } || die "couldn't stage the panel state (login/nodes missing) — aborting to avoid data loss. The docker panel is untouched; check 'docker exec swg-panel ls -la /var/lib/swg-panel /etc/swg-panel'."
  # Stash the JUST-STAGED settings + blessed url NOW, while they're known-good — install-host's cert reloadcmd can
  # transiently (re)start the panel mid-install and reset them (see §2c, restored right before the switch).
  [ -f "$STATE/panel-settings.json" ]  && cp -a "$STATE/panel-settings.json"  "$STATE/.panel-settings.preconvert"  2>/dev/null || true
  [ -f "$STATE/panel-confirmed.json" ] && cp -a "$STATE/panel-confirmed.json" "$STATE/.panel-confirmed.preconvert" 2>/dev/null || true
  # carry the acme renewal state back to the host (/root/.acme.sh) + repoint its reload cmd at the systemd unit
  if [ -d "$ETC/acme" ]; then
    mkdir -p /root/.acme.sh; cp -a "$ETC/acme/." /root/.acme.sh/ 2>/dev/null || true
    # a SIGHUP, not a restart: the panel reloads its certificate live, and a restart drops open requests and a
    # Renew-now job waiting on this very renewal (see install-host.sh; update.sh heals the old form)
    find /root/.acme.sh -name '*.conf' -exec sed -i "s#^Le_ReloadCmd=.*#Le_ReloadCmd='systemctl kill -s HUP swg-panel-server.service 2>/dev/null || true'#" {} + 2>/dev/null || true
    sed -i "s#^LOG_FILE=.*#LOG_FILE='/root/.acme.sh/acme.sh.log'#" /root/.acme.sh/account.conf 2>/dev/null || true   # same trap, other direction
  fi
  # write the bare install.conf so install-host.sh's prompts DEFAULT to the preserved settings (Enter accepts)
  # ROLE_SEL is what a LATER re-install defaults to, so it must be the deployment's real role. Hardcoding
  # "host" made a re-install of a MASTER offer "host" as the default — i.e. quietly drop the co-located node —
  # while the menu above it still showed master as the default. (The install-host invocation itself is
  # ROLE=host on purpose: the node half is installed separately by install-node.sh right after.)
  cat > "$ETC/install.conf" <<EOF
ROLE_SEL=$([ "$ROLE" = master ] && echo master || echo host)
PANEL_DOMAIN=$PDOM
PANEL_BASE=$PBASE
PORT=$PPORT
TLS_MODE=$PTLS
SERVE_MODE=internal
ACME_EMAIL=$PEMAIL
CF_TOKEN=$PCFT
CF_ORIGIN_TOKEN=$PCFO
EOF
  sub "staged roster + nodes + login + $(b "$PTLS") cert (+ acme renewal) → $STATE + $ETC"

  # 2) INSTALL the bare panel WHILE the docker panel is STILL UP and serving the UI. SWG_DEFER_START=1 ⇒ install-host
  #    installs + enables the panel but does NOT start it (so it doesn't fight docker for :443) — the docker panel
  #    keeps the port and keeps showing "converting" (header + node tile) through this whole step. It reuses the
  #    staged login (KEEP_AUTH); TLS defaults to reuse when the staged cert still covers the host (else it prompts).
  # Clear any STALE swg-sub drop-ins from a PRIOR bare-metal install (this box may have been bare→docker→bare): they're
  # swg-netctl-managed env overrides (SWG_SUB_HOST/PORT) that would shadow the fresh unit with a dead bind. The panel
  # re-asserts the correct one at boot (_reconcile_sub_listen_at_boot) from access.sub. (A no-op on a box that was
  # never bare-metal.) That heal is what makes this delete safe: it used to claim an "apply-sub after the switch"
  # that nothing ever called, so the sub silently fell back to the unit default while the panel kept advertising
  # the configured port — links pointed at a port nothing listened on, with the service reporting perfectly healthy.
  rm -f /etc/systemd/system/swg-sub.service.d/*.conf 2>/dev/null || true
  # ⚠️ RETIRE THE DOCKER UPDATER BEFORE install-host WRITES THE BARE ONE — never after. They are the SAME five paths
  # (/usr/local/bin/swg-update, swg-update-check, swg-update.{service,timer}, the stamp): a bare panel and a docker
  # install on one box share one updater by design. Retired after, as this used to be, it deleted the updater the bare
  # panel had just been given: every Update press then wrote a trigger nothing read and the panel sat on "updating"
  # (1.8.8 qualification, docker → bare master). The docker panel still serves until the switch; it just can't
  # one-click-update in the minute this install takes.
  retire_docker_updater
  info "Installing the bare-metal panel — the docker panel keeps serving until the switch…"
  # A MASTER has a co-located node coming in the LATER install-node step, but there's no agent config for install-host
  # to detect yet — flag it so the panel binds the dedicated loopback port (SWG_PANEL_LOCAL_PORT) that the node dials.
  _LNENV=""; [ "$ROLE" = master ] && _LNENV="SWG_HAS_LOCAL_NODE=1 LOCAL_PORT=$PLOCALPORT"
  # …and what install.conf must record about that node. install-host runs as ROLE=host here, so it wrote back
  # ROLE_SEL=host with an empty HOST_NODE_NAME / HOST_ENDPOINT_IP over the master line staged above, and the next
  # re-install or update read a panel-only box (1.8.8 qualification, round 4). The node's name is the panel's record
  # for this node's token; its endpoint is the one the Docker node served.
  _MNAME=""; [ "$ROLE" = master ] && _MNAME="$(panel_node_name_tok "$STATE/nodes.json" "$NTOK")"
  # Pass NEITHER TLS_MODE nor SERVE_MODE: ask_choice/ask_valid treat an already-set value as the answer, so both
  # menus printed in full with no question under them and the installer picked for the operator — and the pick was
  # "letsencrypt", which then tried to re-issue a certificate we had just staged and aborted on :80 (held by the
  # docker panel that is deliberately still serving). install.conf above already carries both as the DEFAULTS, so
  # dropping them here gives real prompts with "reuse" preselected: Enter keeps the cert and the web-server mode.
  env ROLE=host PANEL_DOMAIN="$PDOM" PORT="$PPORT" PANEL_BASE="$PBASE" ACME_EMAIL="$PEMAIL" SUB_PORT="$PSUBPORT" $_LNENV \
      CF_TOKEN="$PCFT" CF_ORIGIN_TOKEN="$PCFO" BASIC_USER="$PUSER" SWG_CONVERT_DIR=convert-bare SWG_LC_PARENT=1 SWG_DEFER_START=1 \
      ${_MNAME:+HOST_NODE_NAME="$_MNAME"} ${NEP:+HOST_ENDPOINT_IP="$NEP"} \
      bash "$SRC/install-host.sh" \
    || die "install-host.sh failed — your panel state is safe in $STATE + $ETC; re-run the bare-metal host install to finish"
  [ "$ROLE" = master ] && sed -i 's/^ROLE_SEL=.*/ROLE_SEL=master/' "$ETC/install.conf" 2>/dev/null   # the role, not install-host's ROLE=host
  carry_env_to_dropin "$envf" swg-panel-server SWG_LATEST_URL \
      'SWG_PANEL_CONSOLE_PORT=CONSOLE_PORT/8445/[0-9]{1,5}' 'SWG_PANEL_CONSOLE_HOST=CONSOLE_BIND/127.0.0.1/[0-9A-Fa-f.:]{2,45}'   # the release check and the console's own address, before the first start below

  # 2c) RESTORE the known-good staged settings, right before the switch. install-host's acme --install-cert reloadcmd
  #     restarts swg-panel-server DURING the install (while docker still holds the port), so the panel partial-boots
  #     once and reconciles the staged panel-settings/blessed against a not-yet-final state — which can leave the bare
  #     panel booting on a blank url / wrong TLS mode (UI shows selfsigned / no address / subs off though it serves the
  #     real cert). We stashed the good copies right after staging (below §1); put them back so the real start reads the
  #     preserved access + subs + blessed url intact. (Bare-metal only; the bare->docker block uses .env.)
  _owner="$(stat -c '%U:%G' "$STATE" 2>/dev/null || echo root:root)"
  # The staged copy came out of the CONTAINER, where the panel runs as root — so every file it brought over is
  # root-owned, while the bare-metal panel runs as an unprivileged service user. It then can't read its own roster
  # and, because an unreadable file is indistinguishable from a corrupt one, refuses to start rather than come up
  # empty: the UI showed "No nodes yet" while the journal repeated "users.json is corrupt". Only two files were
  # being chowned individually; do the whole tree, now that install-host has created the user.
  chown -R "$_owner" "$STATE" 2>/dev/null || true
  netctl_dirs_heal "$STATE"   # …but swg-netctl's claims/ stays root's (F96)
  chmod 600 "$STATE"/users.json "$STATE"/nodes.json 2>/dev/null || true      # roster + node tokens stay owner-only
  [ -d "$STATE/configs" ] && chmod 700 "$STATE/configs" 2>/dev/null || true  # stored client configs
  [ -f "$STATE/.panel-settings.preconvert" ]  && { mv -f "$STATE/.panel-settings.preconvert"  "$STATE/panel-settings.json";  chown "$_owner" "$STATE/panel-settings.json"  2>/dev/null || true; }
  [ -f "$STATE/.panel-confirmed.preconvert" ] && { mv -f "$STATE/.panel-confirmed.preconvert" "$STATE/panel-confirmed.json"; chown "$_owner" "$STATE/panel-confirmed.json" 2>/dev/null || true; }

  # 3) THE ATOMIC SWITCH — only NOW stop the docker panel and start the bare one. Downtime is just this stop+start
  #    (~1-3s), not the whole install above. Same URL/port ⇒ nodes stay connected. A master keeps its docker NODE
  #    running for the node phase below (copy-first); install-node tears it down at its OWN switch (the last step).
  info "Switching over — stopping the docker panel, starting the bare-metal panel…"
  docker rm -f swg-sub >/dev/null 2>&1 || true   # stop the docker subscription surface too (else it keeps holding the sub port; the bare swg-sub takes over below)
  if [ "$ROLE" = master ]; then
    docker rm -f swg-panel >/dev/null 2>&1 || true   # stop ONLY the panel — the docker NODE keeps serving (copy-first)
  else
    ( cd "$DOCKER_DIR" && on_tty docker compose down ) 2>/dev/null || true; docker rm -f swg-panel >/dev/null 2>&1 || true
  fi
  remove_docker_netctl   # the bare panel brings its own swg-netctl; the docker pair would drain the same queue
  # Wait for docker to FULLY release the panel port before starting the bare one. On a slow / 1-core box the
  # docker-proxy teardown lingers, so an immediate start binds into a busy port, crashes, and its Restart loop then
  # contends on the state-dir lock. Poll until the port is free (bounded), then start.
  for _i in $(seq 1 30); do ss -ltnH "sport = :$PPORT" 2>/dev/null | grep -c . >/dev/null || break; sleep 0.5; done
  # Clear a STALE state-dir lock (only when NO swg-panel-server is alive) so a crashed prior start can't block the switch.
  pgrep -f "swg-panel-server" >/dev/null 2>&1 || rm -f "$STATE/.panel.lock" 2>/dev/null || true
  _pu=no; for _i in 1 2 3 4 5; do if systemctl start swg-panel-server 2>/dev/null; then _pu=yes; break; fi; sleep 2; done   # bind the port now that docker released it (retry for the handoff)
  [ "$_pu" = yes ] || die "couldn't start the bare-metal panel after stopping the docker panel — check 'systemctl status swg-panel-server'; your panel state is safe in $STATE + $ETC"
  # wait until the bare panel actually ANSWERS (not just "systemctl start" returned) before stamping "converted"
  # below — an early stamp ages out of the success-show window before the panel can serve the console's first poll,
  # so the header would blank instead of flipping converting→converted the moment the bare panel is reachable.
  for _i in $(seq 1 30); do curl -sk -o /dev/null --max-time 2 "https://127.0.0.1:${PPORT}${PBASE}/" 2>/dev/null && break; sleep 1; done

  # Same repair in reverse: the cert dir moved back out of the container and the ports are the bare ones now.
  nginx_convert_fixup /etc/swg-panel/tls "$(ngx_upstream "$PPORT")" "$(ngx_upstream "$PSUBPORT")"

  # Bring the bare swg-sub up when subscriptions were ON: issue its cert (same acme state — reuses the panel cert for a
  # same-domain sub) and (re)start it so the public sub surface migrates too. The main unit already binds SWG_SUB_PORT
  # =$PSUBPORT and the stale drop-ins are gone, so a restart binds the right port. Best-effort: a missing sub host /
  # disabled subs just leaves swg-sub inert (its normal state until turned on in the panel).
  # Start it UNCONDITIONALLY first: install-host ran under SWG_DEFER_START (so the new panel wouldn't fight docker
  # for the port), which left swg-sub enabled-but-never-started, and the cert/host branch below only fires when subs
  # were already on — so every converted box with subs OFF came up reporting "Subscription server isn't running".
  # swg-sub is inert until subscriptions are enabled in the panel; what it must be is RUNNING, so the panel can
  # rebind it the moment they are. Safe here: the docker sub container was removed just above, so the port is free.
  systemctl start swg-sub 2>/dev/null || true
  if python3 -c 'import json,sys; sys.exit(0 if (json.load(open(sys.argv[1])).get("subscriptions") or {}).get("enabled") else 1)' "$STATE/panel-settings.json" 2>/dev/null; then
    _subhost="$(python3 -c 'import json,sys
from urllib.parse import urlparse
print(urlparse(((( json.load(open(sys.argv[1])).get("access") or {}).get("sub") or {}).get("url") or "")).hostname or "")' "$STATE/panel-settings.json" 2>/dev/null || true)"
    [ -n "$_subhost" ] || _subhost="$PDOM"
    /usr/local/bin/swg-netctl issue-cert sub "$_subhost" >/dev/null 2>&1 || true
    systemctl restart swg-sub 2>/dev/null || true
    sub "brought up the subscription surface (swg-sub) for $_subhost:$PSUBPORT"
  fi

  # THEN THE NODE — only after the panel is up (host first, then node). Stage the local node straight from the
  # still-running swg-node container (confs → bare locations + host NAT, keypairs, turn units deferred), then
  # install-node adopts it: Step 1 interfaces → Step 2 turn-proxies → its own switch (docker node stays up till then).
  mnames=""
  if [ "$ROLE" = master ]; then
    echo; info "Panel is up on bare-metal — now the local node (the docker node keeps serving until its own switch)."
    # the HOST (panel) is fully up NOW → flip its header tile to "converted" immediately; don't make it wait for
    # the node phase. The node tile stays "converting" until install-node finishes — convert.sh's EXIT trap emits
    # the node's terminal WITH the final summary. Repoint LC_EMIT to node-only so that trap won't re-touch the host.
    lc_emit_file converted-bare; LC_EMIT=lc_emit_post
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -cx swg-node >/dev/null; then
      mkdir -p "$DOCKER_DIR/data/node-confs" "$DOCKER_DIR/data/node"
      docker cp swg-node:/etc/amnezia/amneziawg/. "$DOCKER_DIR/data/node-confs/" 2>/dev/null || true
      docker cp swg-node:/var/lib/swg-noded/.      "$DOCKER_DIR/data/node/"       2>/dev/null || true
      # …and the PLAIN-WireGuard dir. Only the AWG dir is a bind mount, so a wg conf can exist ONLY inside the
      # container — and was destroyed with it: the panel then reported those interfaces as lost, and for the ones
      # it had never issued keys for ("adopted"), as unrecoverable. Staged into the same dir; the loop below
      # routes each conf to the right host dir by its contents. Never clobbers an AWG conf of the same name.
      _wgtmp="$(mktemp -d)"
      docker cp swg-node:/etc/wireguard/. "$_wgtmp/" 2>/dev/null || true
      for _wf in "$_wgtmp"/*.conf; do [ -f "$_wf" ] || continue
        [ -e "$DOCKER_DIR/data/node-confs/$(basename "$_wf")" ] || cp -a "$_wf" "$DOCKER_DIR/data/node-confs/"
      done
      rm -rf "$_wgtmp"
    fi
    for f in "$DOCKER_DIR/data/node-confs/"*.conf; do [ -f "$f" ] || continue
      nm="$(basename "$f" .conf)"
      if grep -qiE '^[[:space:]]*(Jc|Jmin|Jmax|S1|S2|H1|H2|H3|H4|I1)[[:space:]]*=' "$f"; then dest="/etc/amnezia/amneziawg/$nm.conf"; else dest="/etc/wireguard/$nm.conf"; fi
      mkdir -p "$(dirname "$dest")"
      # an ADOPTED interface takes its own hooks back (see import_bare_conf) — read before the original may move aside
      _hf=""; _hc=""; _kept=""
      if conf_is_adopted "$f"; then
        _hf="$(adopted_hooks_from "$nm" "$f" "$dest")"; [ -n "$_hf" ] && { _hc="$(mktemp)"; cp "$_hf" "$_hc"; }
        keep_docker_original "$f"; _kept="$KEPT_ORIG"
      fi
      # an interface this node adopted from the host still has its original here (the node-only convert's same-key
      # case, see below) — never overwritten: kept beside the import
      if [ -f "$dest" ]; then _imp="$(mktemp)"; import_bare_conf "$f" "$_imp" "$_hc"
        cmp -s "$_imp" "$dest" || { mv -f "$dest" "$dest.pre-convert"; sub "$(b "$nm"): the conf already on this host is kept as $(b "$dest.pre-convert")"; }
        rm -f "$_imp"; fi
      import_bare_conf "$f" "$dest" "$_hc"; [ -n "$_hc" ] && rm -f "$_hc"
      if conf_is_adopted "$f"; then adopted_import_line "$nm" "$dest" "$_hf" "$_kept"; mnames="${mnames:+$mnames }$nm"; continue; fi
      sub "imported local-node interface $(b "$nm") → $dest (host NAT added)"; mnames="${mnames:+$mnames }$nm"
    done
    migrate_node_state to-baremetal "$DOCKER_DIR"
    # WDTT server state → the bare-metal paths (carries each wg-keys.dat identity + owner passwords so clients keep
    # working, no re-mint; strips the docker run-model's stale runtime files — see migrate_wdtt in lib/common.sh).
    migrate_wdtt to-baremetal "$DOCKER_DIR"
    migrate_csqtt to-baremetal "$DOCKER_DIR"   # same carry for csqtt (password store + node-owned owner password)
    # ALWAYS run install-node for a master — even with NO interfaces to migrate. The co-located node still has to
    # become a bare swg-noded that syncs (ready for interfaces added later from the panel); gating on $mnames left a
    # 0-interface master's node orphaned as a docker container after the dir-move below. (install-node migrates the
    # docker turn-proxies itself in Step 2, so there's no separate turn step here.)
    # Dial the DEDICATED STABLE loopback ($PLOCALPORT, plain HTTP at ROOT) — the same URL a fresh master's node uses
    # (install-host.sh LOCAL_PANEL_URL) — NOT the public TLS port. A later panel address/port flip never moves :8088,
    # so the co-located node can't be stranded by it; pointing it at the public port would defeat that stable-port design.
    MEPS="$(docker_iface_endpoints "$mnames" "$NEP" "$(getv NODE_IFACES)")"
    [ -n "$MEPS" ] && sub "keeping each interface's client endpoint: $(printf '%s' "$MEPS" | sed 's/,/, /g')"
    carry_env_to_dropin "$envf" swg-noded SWG_TURN_MIRROR   # before install-node.sh first starts swg-noded
    NDNS="$(_dotenv_val DNS "$envf")"; _dns_ok "$NDNS" || NDNS=""
    env NODE_TOKEN="$NTOK" PANEL_URL="http://127.0.0.1:$PLOCALPORT" ENDPOINT_IP="$NEP" ADOPTED_IFACES="$mnames" ADOPTED_ENDPOINTS="$MEPS" \
        SWG_CONVERT=1 TLS_VERIFY=no SWG_DOCKER_DIR="$DOCKER_DIR" ${NDNS:+DNS="$NDNS"} bash "$SRC/install-node.sh" \
      || warn "the local node setup reported an error — check it on the panel."
    reap_adopted_container_nat $mnames   # the node container's rule for an adopted interface (see reap_container_nat)
    # The containers went one by one (the docker node had to outlive the panel, copy-first), so compose never took
    # the project down and its network — swg-panel-docker_default and its br-… bridge — outlived the install. Remove
    # it now that nothing is attached (docker refuses while anything still is, so this can't cut a live container off).
    for _nw in $(docker network ls -q --filter "label=com.docker.compose.project=$(basename "$DOCKER_DIR")" 2>/dev/null); do
      docker network rm "$_nw" >/dev/null 2>&1 || true
    done
  else
    # host-only (no node phase): the bare panel is up → flip the header tile to "converted" NOW, mirroring the
    # master's tile-split above. Otherwise only the end-of-run EXIT trap emits it (after the dir-move + summary),
    # which can land after the console's brief success-show window — so "converted" never appears on the header.
    lc_emit_file converted-bare
  fi

  # (the docker updater was retired BEFORE install-host — the files it would remove here are the bare panel's now)
  # 3) move the old docker dir aside so a later convert-back isn't blocked by the leftover .env, then done
  if [ -d "$DOCKER_DIR" ]; then
    _bak="$DOCKER_DIR.converted-$(date +%Y%m%d-%H%M%S 2>/dev/null || echo bak)"
    mv "$DOCKER_DIR" "$_bak" 2>/dev/null && { seal_archive "$_bak"; info "moved the old docker dir aside → $(b "$_bak") (backup — safe to delete)"; } || warn "couldn't move $DOCKER_DIR aside — remove it manually before converting back to docker"
  fi
  clear_recovery
  _psuf=""; case "$PPORT" in 443|80|"") :;; *) _psuf=":$PPORT";; esac
  echo; ok "$(b "$ROLE") converted to bare-metal — $(b "https://$PDOM$_psuf$PBASE/") (same login, roster, nodes + cert$([ "$ROLE" = master ] && echo " + local node")). Nodes reconnect on their next sync."
  print_summary CONVERSION "$([ "$ROLE" = master ] && echo both || echo host)"   # docker→bare: the panel (+ the local node for a master) converted
  exit 0
fi

# ── NODE: docker → bare-metal ──
if [ "$FROM" = docker ] && [ "$TO" = baremetal ]; then
  envf="$DOCKER_DIR/.env"; confd="$DOCKER_DIR/data/node-confs"
  [ -f "$envf" ] || [ -n "${SWG_RV_TOKEN:-}" ] || die "no docker node settings found at $envf"   # resuming? the saved identity covers a half-torn-down .env
  getv(){ sed -n "s/^$1=//p" "$envf" 2>/dev/null | sed -n 1p | sed 's/^"//; s/"$//' || true; }   # || true: a missing .env must fall through to recovery state, not abort under pipefail+set -e
  NTOK="$(getv NODE_TOKEN)"; PURL="$(getv PANEL_URL)"; NEP="$(getv NODE_ENDPOINT)"
  NIFS="$(getv NODE_IFACES)"; NIF="$(getv NODE_IFACE)"; NPLAIN="$(getv NODE_PLAIN_WG)"; NVERIFY="$(getv TLS_VERIFY)"
  # ⚠️ …AND THE PANEL-CERT PIN. Only TLS_VERIFY was carried, which is `no` on every node of a self-signed panel —
  # the PIN is how such a node trusts it — so the bare node came out verifying nothing at all. Carry the pin the
  # running node actually uses: a self-learned one (data/node/panel-fp, from a re-point/transfer) wins over the .env
  # value, and the learned verify flag likewise — exactly as docker/node-entrypoint.sh decides them.
  NFP="$(getv TLS_FINGERPRINT | sed 's/[[:space:]]\{1,\}#.*$//' | tr -cd '0-9A-Fa-f:' || true)"
  # (`|| true` inside: no learned file is the NORMAL case, and a failed `head` under pipefail + set -e would abort here)
  _lfp="$(head -n1 "$DOCKER_DIR/data/node/panel-fp" 2>/dev/null | tr -cd '0-9A-Fa-f:' || true)"; [ -n "$_lfp" ] && NFP="$_lfp"
  _lvf="$(head -n1 "$DOCKER_DIR/data/node/panel-verify" 2>/dev/null | tr -d '[:space:]' || true)"; [ -n "$_lvf" ] && NVERIFY="$_lvf"
  # …and a learned verify=yes with NO learned pin is CA verification — a transfer to a panel a public CA vouches for.
  # The .env's pin is the one of the panel the node LEFT: carried, it pinned the new panel to the old certificate and
  # the bare node never synced (the same rule as docker/node-entrypoint.sh and lib/common.sh docker_node_panel).
  [ "$_lvf" = yes ] && [ -z "$_lfp" ] && NFP=""
  # ⚠️ …AND THE ADDRESS AND TOKEN IT LEARNED. A node the panel RE-POINTED (host/port moved) or TRANSFERRED (another
  # panel took it over) runs on data/node/panel-url / panel-token — node-entrypoint.sh reads them ahead of the .env on
  # every start — while the .env still names where it USED to sync. Converting from the .env alone handed the bare
  # node the old address (it synced nowhere) or the old panel's token (401 for ever). Same precedence as the entrypoint.
  _lpu="$(head -n1 "$DOCKER_DIR/data/node/panel-url" 2>/dev/null | tr -d '[:space:]' || true)"
  [ -n "$_lpu" ] && [ "$_lpu" != "$PURL" ] && { sub "the node re-pointed itself to $(b "$_lpu") — converting with that, not the .env's ${PURL:-(blank)}"; PURL="$_lpu"; }
  _lpt="$(head -n1 "$DOCKER_DIR/data/node/panel-token" 2>/dev/null | tr -d '[:space:]' || true)"
  [ -n "$_lpt" ] && [ "$_lpt" != "$NTOK" ] && { sub "the node was transferred — converting with the token it learned, not the .env's"; NTOK="$_lpt"; }
  [ -n "${SWG_RV_TOKEN:-}" ] && { NTOK="$SWG_RV_TOKEN"; PURL="$SWG_RV_URL"; NEP="$SWG_RV_EP"; NVERIFY="${SWG_RV_VERIFY:-no}"; NFP="${SWG_RV_FP:-}"; }   # resume: saved identity wins
  [ "$NVERIFY" = yes ] || NVERIFY=no
  # co-located master-split (the panel STAYS on docker, only the local node converts to bare): the node's PANEL_URL
  # is the compose DNS name (swg-panel:PORT), unreachable outside the compose network. Point the bare node at the
  # panel's published loopback port instead, and don't verify the cert (it's for the domain, not 127.0.0.1).
  case "$PURL" in *://swg-panel:*|*://swg-panel/*|*://swg-panel)
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -cx swg-panel >/dev/null; then
      _pp="$(getv PANEL_PORT)"; PURL="https://127.0.0.1:${_pp:-443}"; NVERIFY=no
      sub "co-located split → bare node will sync to the local docker panel at $PURL"
    fi ;;
  esac
  [ -n "$NTOK" ] && [ -n "$PURL" ] || die "couldn't read the node token / panel URL (docker .env missing and no recovery state)"

  # interface specs as "name:proto" (proto = awg|wg). The PERSISTED confs in data/node-confs are the
  # real interface set the docker node manages (node-entrypoint scans that dir) — .env's NODE_IFACES
  # only lists what was set at INSTALL time, so panel-added interfaces (e.g. da221) are missing there.
  # Detect each protocol from its conf (AmneziaWG obfuscation keys ⇒ awg, else wg).
  specs=""
  if [ -d "$confd" ]; then
    for f in "$confd"/*.conf; do
      [ -f "$f" ] || continue
      nm="$(basename "$f" .conf)"
      if grep -qiE '^[[:space:]]*(Jc|Jmin|Jmax|S1|S2|H1|H2|H3|H4|I1)[[:space:]]*=' "$f"; then pr=awg; else pr=wg; fi
      specs="${specs:+$specs }$nm:$pr"
    done
  fi
  if [ -z "$specs" ] && [ -n "$NIFS" ]; then        # fall back to .env if no confs are on disk yet
    OIFS=$IFS; IFS=','
    for e in $NIFS; do IFS=$OIFS
      nm="$(printf '%s' "$e" | cut -d: -f1)"; pr="$(printf '%s' "$e" | cut -d: -f4)"
      [ "$pr" = wg ] || pr=awg
      [ -n "$nm" ] && specs="${specs:+$specs }$nm:$pr"; IFS=','
    done; IFS=$OIFS
  elif [ -z "$specs" ] && [ -n "$NIF" ]; then
    pr=awg; [ "$NPLAIN" = yes ] && pr=wg; specs="$NIF:$pr"
  fi
  if [ -z "$specs" ] && [ -n "${SWG_RV_NAMES:-}" ]; then   # resume after the docker dir was already moved → derive from the bare confs
    for nm in $SWG_RV_NAMES; do
      if   [ -e "/etc/wireguard/$nm.conf" ];          then specs="${specs:+$specs }$nm:wg"
      elif [ -e "/etc/amnezia/amneziawg/$nm.conf" ];  then specs="${specs:+$specs }$nm:awg"; fi
    done
  fi
  # keep only specs whose conf is actually on disk — a bare .env NODE_IFACE default (no conf), or confs lost from
  # data/node-confs, would otherwise be "migrated" as a ghost (and trip the pre-flight). You can't migrate a conf-less iface.
  _sp=""; for s in $specs; do nm="${s%:*}"
    { [ -e "$confd/$nm.conf" ] || [ -e "/etc/amnezia/amneziawg/$nm.conf" ] || [ -e "/etc/wireguard/$nm.conf" ]; } && _sp="${_sp:+$_sp }$s"
  done; specs="$_sp"
  # No wg/awg interfaces is FINE — an empty master/node (nothing added yet), or a WDTT-only node, converts as-is:
  # interfaces are added later from the panel, and any WDTT servers carry over via migrate_wdtt. Just convert what's
  # there — never refuse for "nothing yet" (mirrors the installer, which allows an interface-less install).
  [ -n "$specs" ] || sub "no wg/awg interfaces to migrate — converting the node as-is (add interfaces from the panel later)"

  # pre-flight: a bare-metal conf of the same NAME already present is a real clash (the docker
  # node still holds the ports, but those free up the moment we stop its container below).
  # On a RESUME these confs are OURS — the interrupted run already imported them — so they're not a clash;
  # the import step below keeps them as-is ("resume: don't re-import").
  # ⚠️ …BUT NOT THE INTERFACE ITSELF. A Docker node that ADOPTED one of this host's interfaces rebuilt its conf inside the
  # container; the host's own original is still in /etc/wireguard (or the AmneziaWG dir), holding the SAME private key.
  # That read as a clash and refused the convert, with only a manual remedy (1.8.8 qualification, round 4; since 1.6.0).
  # Same key = same interface: it is carried like the rest, and its original is kept beside it (see the import below).
  conflicts=""
  if [ "$RESUMING" != yes ]; then
    for s in $specs; do nm="${s%:*}"
      for _bc in "/etc/amnezia/amneziawg/$nm.conf" "/etc/wireguard/$nm.conf"; do
        [ -e "$_bc" ] || continue
        same_iface_conf "$_bc" "$confd/$nm.conf" && continue
        conflicts="${conflicts:+$conflicts }$nm"; break
      done
    done
  fi
  if [ "$CHECK" = yes ]; then
    if [ -n "$conflicts" ]; then
      warn "a bare-metal interface already exists with these name(s): $(b "$conflicts")"
      echo  "  Rename/remove them (or pick 'keep and re-install'), then retry." >&2
      exit 1
    fi
    sub "pre-flight OK"
    # "converting" is emitted ONLY after the user confirms "proceed?" (real run, lc_init below) — never in this
    # pre-flight — so declining the prompt leaves no stale converting status on the panel. The interface list is
    # shown once, in install-node's "Transfer?" step below — no need to duplicate it here in the pre-flight.
    exit 0
  fi
  [ -n "$conflicts" ] && die "interface name clash: $conflicts (run with --check first)"

  info "Converting the docker node → bare-metal — keeping its token, endpoint and interfaces."
  write_recovery "$(for s in $specs; do printf '%s ' "${s%:*}"; done)"   # persist identity BEFORE teardown so a dropped session can resume
  # …with the node's pin: the status POSTs carry the token, and panel_req checks the panel with it (never curl -k)
  LC_URL="$PURL"; LC_TOKEN="$NTOK"; LC_VERIFY="${NVERIFY:-no}"; LC_FP="${NFP:-}"; lc_init convert-bare lc_emit_post   # converting… now; converted-bare/aborted/failed on exit
  # NB: the DOCKER NODE STAYS UP + serving through the copy below AND install-node.sh's prompts. install-node
  #     does the ATOMIC SWITCH (it runs with SWG_CONVERT=1): it stops the docker datapath + clears leftover
  #     host netdevs ONLY right before it brings the bare interfaces up — never before.
  # 1) copy each interface's .conf into the bare-metal location (private key + Amnezia params carry over)
  names=""
  for s in $specs; do nm="${s%:*}"; pr="${s#*:}"
    src="$confd/$nm.conf"
    if [ "$pr" = wg ]; then dest="/etc/wireguard/$nm.conf"; else dest="/etc/amnezia/amneziawg/$nm.conf"; fi
    # an ADOPTED interface takes its own hooks back (see import_bare_conf) — read before its host original moves aside
    _hf=""; _hc=""; _kept=""
    if [ -f "$src" ] && conf_is_adopted "$src"; then
      _hf="$(adopted_hooks_from "$nm" "$src" "/etc/amnezia/amneziawg/$nm.conf" "/etc/wireguard/$nm.conf")"
      [ -n "$_hf" ] && { _hc="$(mktemp)"; cp "$_hf" "$_hc"; }
    fi
    # the host's own original of an interface this node adopted (same key) — keep it beside the import, never overwrite
    for _bc in "/etc/amnezia/amneziawg/$nm.conf" "/etc/wireguard/$nm.conf"; do
      [ -f "$_bc" ] && [ -f "$src" ] && same_iface_conf "$_bc" "$src" || continue
      _imp="$(mktemp)"; import_bare_conf "$src" "$_imp" "$_hc"
      if cmp -s "$_imp" "$_bc"; then rm -f "$_imp"; continue; fi                     # already our import (a resume)
      rm -f "$_imp"; mv -f "$_bc" "$_bc.pre-convert"
      sub "$(b "$nm") is the host interface this node adopted — its original conf is kept as $(b "$_bc.pre-convert")"
    done
    if [ -f "$dest" ]; then sub "kept $(b "$nm") → $dest (already imported)"; names="${names:+$names }$nm"; continue; fi   # resume: don't re-import
    [ -f "$src" ] || { warn "missing $src — skipping interface '$nm'"; continue; }
    mkdir -p "$(dirname "$dest")"; import_bare_conf "$src" "$dest" "$_hc"   # adds host NAT (docker confs have none) — an adopted one, its own hooks
    if conf_is_adopted "$src"; then keep_docker_original "$src"; adopted_import_line "$nm" "$dest" "$_hf" "$KEPT_ORIG"
    else sub "imported $(b "$nm") → $dest (host NAT added)"; fi
    [ -n "$_hc" ] && rm -f "$_hc"
    names="${names:+$names }$nm"
  done
  # die only if we EXPECTED interfaces ($specs non-empty) but none copied — a real "confs vanished" error. An empty
  # node (no specs) legitimately copies nothing and converts as-is; don't refuse it.
  [ -n "$names" ] || [ -z "$specs" ] || die "no interface confs copied (looked in $confd)"

  # carry the node's host-local derived state (keypair backups + the pulled routing lists) — see lib/common.sh
  migrate_node_state to-baremetal "$DOCKER_DIR"

  # carry the WDTT server state to the bare-metal paths (each wg-keys.dat identity + the node-owned owner passwords,
  # so clients keep working after the switch — no re-mint; strips the docker run-model's stale runtime files that the
  # reconcile rewrites). Single source of truth: migrate_wdtt in lib/common.sh.
  migrate_wdtt to-baremetal "$DOCKER_DIR"
  migrate_csqtt to-baremetal "$DOCKER_DIR"   # same carry for csqtt (password store + node-owned owner password)

  # 3) THE SWITCH — install-node.sh runs all its prompts WHILE docker still serves: Step 1 interfaces, then
  #    Step 2 migrates the docker turn-proxies (deferred) + adds more. Then, as its LAST step, the atomic cutover:
  #    stop the docker datapath + turn containers → bring up bare interfaces → start the turn units → start
  #    swg-noded. So the node goes down + comes back ONCE, fully converted, in a single non-interactive step.
  info "Running install-node.sh — adopt $(b "$names") (add more if you want); then it does the switch as the last step…"
  echo
  # NB: '|| warn' — a non-zero exit (e.g. one interface failed to come up) must NOT abort the convert under set -e.
  NEPS="$(docker_iface_endpoints "$names" "$NEP" "$NIFS")"
  [ -n "$NEPS" ] && sub "keeping each interface's client endpoint: $(printf '%s' "$NEPS" | sed 's/,/, /g')"
  carry_env_to_dropin "$envf" swg-noded SWG_TURN_MIRROR   # before install-node.sh first starts swg-noded
  NDNS="$(_dotenv_val DNS "$envf")"; _dns_ok "$NDNS" || NDNS=""
  env NODE_TOKEN="$NTOK" PANEL_URL="$PURL" ENDPOINT_IP="$NEP" ADOPTED_IFACES="$names" ADOPTED_ENDPOINTS="$NEPS" \
      SWG_CONVERT=1 TLS_VERIFY="$NVERIFY" TLS_FINGERPRINT="$NFP" SWG_DOCKER_DIR="$DOCKER_DIR" ${NDNS:+DNS="$NDNS"} bash "$SRC/install-node.sh" \
    || warn "install-node.sh reported an error — check the node on the panel."
  reap_adopted_container_nat $names   # the node container's rule for an adopted interface (see reap_container_nat)

  # move the old docker dir aside so a later bare→docker convert isn't
  # blocked by the leftover .env — UNLESS the docker PANEL is still running from this dir (a co-located master-split:
  # only the node converted, the panel stays on docker and needs the dir + its compose/.env + bind mounts).
  # The docker updater has no job on a bare NODE (a bare node has none by design) — but the same files ARE the
  # updater of a panel still on this box: a docker panel staying put (co-located split) or a bare-metal panel beside
  # this node. Retiring them there broke that panel's Update button, so only when no panel remains.
  if ! bare_panel_present && ! docker ps --format '{{.Names}}' 2>/dev/null | grep -cx swg-panel >/dev/null; then
    retire_docker_updater
  fi
  if [ -d "$DOCKER_DIR" ] && ! docker ps --format '{{.Names}}' 2>/dev/null | grep -cx swg-panel >/dev/null; then
    _bak="$DOCKER_DIR.converted-$(date +%Y%m%d-%H%M%S)"
    if mv "$DOCKER_DIR" "$_bak" 2>/dev/null; then seal_archive "$_bak"; info "moved the old docker dir aside → $(b "$_bak") (backup — safe to delete)"
    else warn "couldn't move $DOCKER_DIR aside — remove it manually before converting back to docker"; fi
  fi
  clear_recovery   # convert finished cleanly → drop the recovery marker
  # the conversion is verified complete here; the lc EXIT trap (clean exit below) emits "converted-bare", which
  # the panel shows green for a few seconds, then the bare node reports normally (online) on its next sync.
  print_summary CONVERSION node   # unified per-server summary; detects the box + flags the converted node
  exit 0           # done (this block no longer execs install-node.sh, so end here, not the catch-all die)
fi

# ── NODE: bare-metal → docker ──
if [ "$FROM" = baremetal ] && [ "$TO" = docker ]; then
  cfg=/etc/swg-agent/config.json
  [ -f "$cfg" ] || [ -n "${SWG_RV_TOKEN:-}" ] || die "no bare-metal node found ($cfg missing)"   # resuming? recovery state covers a half-torn-down config
  command -v python3 >/dev/null 2>&1 || die "python3 is required to read $cfg"
  # token / panel URL / verify / node endpoint / panel-cert pin
  # ⚠️ THE PIN TOO. It was never read, and TLS_VERIFY alone is `no` on every node of a self-signed panel (the pin is
  # how such a node trusts it), so the docker node came up with `verify: False` and no fingerprint — trusting any
  # certificate at all, where the bare node it replaced had been pinned (1.8.8 qualification, by reading this path).
  read -r NTOK PURL NVERIFY NEP NFP NDNS <<EOF
$(python3 - "$cfg" <<'PY'
import json,sys
try: c=json.load(open(sys.argv[1]))   # on a RESUME the bare config is already gone → recovery state fills these in
except Exception: c={}
p=c.get("panel") or {}
fp="".join(ch for ch in str(p.get("fingerprint") or "") if ch in "0123456789abcdefABCDEF:")
dns=c.get("dns") if isinstance(c.get("dns"), list) else []
d0=str(dns[0]).strip() if dns else ""
print(p.get("token","-"), p.get("url","-"), "yes" if p.get("verify",True) else "no", c.get("endpoint_host","") or "-", fp or "-",
      d0 or "-")   # last: `read` gives it the rest of the line
PY
)
EOF
  [ "$NEP" = "-" ] && NEP=""
  [ "$NFP" = "-" ] && NFP=""
  [ "$NDNS" = "-" ] && NDNS=""; _dns_ok "$NDNS" || NDNS=""   # the node's client DNS (see _dns_ok) — the installers write one
  [ -n "${SWG_RV_TOKEN:-}" ] && { NTOK="$SWG_RV_TOKEN"; PURL="$SWG_RV_URL"; NEP="$SWG_RV_EP"; NVERIFY="${SWG_RV_VERIFY:-no}"; NFP="${SWG_RV_FP:-}"; }   # resume: saved identity wins
  [ -n "$NTOK" ] && [ "$NTOK" != "-" ] && [ "$PURL" != "-" ] || die "couldn't read the node token / panel URL (config missing and no recovery state)"
  # interface  name<TAB>conf-path  lines
  ifaces="$(python3 - "$cfg" <<'PY'
import json,sys
try: c=json.load(open(sys.argv[1]))
except Exception: c={}
for n,ic in (c.get("interfaces") or {}).items():
    if (ic.get("conf") or ""): print(n+"\t"+ic["conf"])
PY
)"
  if [ -z "$ifaces" ] && [ -d "$DOCKER_DIR/data/node-confs" ]; then   # resume after the bare config was removed → derive from the already-imported docker confs
    for f in "$DOCKER_DIR/data/node-confs/"*.conf; do [ -f "$f" ] && printf '%s\t%s\n' "$(basename "$f" .conf)" "$f"; done > /tmp/.swg_ifaces.$$ 2>/dev/null
    ifaces="$(cat /tmp/.swg_ifaces.$$ 2>/dev/null)"; rm -f /tmp/.swg_ifaces.$$
  fi
  # No interfaces is FINE — an empty or WDTT-only bare node converts as-is (add interfaces later from the panel; any
  # WDTT servers carry over in install-docker's node stage). Convert what's there — never refuse for "nothing yet".
  [ -n "$ifaces" ] || info "no wg/awg interfaces on the bare-metal node — converting it as-is (manage from the panel)"

  # pre-flight: a LIVE docker node would be clobbered. A stale leftover $DOCKER_DIR (no container — e.g.
  # a previous convert that aborted before moving it aside) is NOT a conflict; the convert moves it aside.
  if [ "$CHECK" = yes ]; then
    if docker_node_present; then
      warn "a docker node (swg-node container) already exists here — remove it first, or pick 'keep and re-install'."; exit 1
    fi
    [ -e "$DOCKER_DIR" ] && info "note: a leftover $(b "$DOCKER_DIR") from a previous run will be moved aside."
    sub "pre-flight OK"
    # "converting" is emitted ONLY after "proceed?" is confirmed (real run, lc_init below) — not in this pre-flight.
    # The interface list is shown once, in install-docker's "Transfer?" step below — no duplicate here.
    exit 0
  fi
  if docker_node_present; then die "a docker node (swg-node container) already exists — remove it first (run with --check)"; fi
  # RESUME keeps the half-built $DOCKER_DIR (it holds the confs/turn records already staged before the interrupt).
  # A FRESH convert clears any leftover from a previous FAILED attempt — it's just an outdated copy, no prompt.
  if [ "$RESUMING" != yes ] && [ -e "$DOCKER_DIR" ]; then
    _bak="$DOCKER_DIR.pre-convert-$(date +%Y%m%d-%H%M%S 2>/dev/null || echo bak)"
    mv "$DOCKER_DIR" "$_bak" 2>/dev/null && { seal_archive "$_bak"; info "moved a leftover $(b "$DOCKER_DIR") aside → $(b "$_bak") (backup — safe to delete)"; } || rm -rf "$DOCKER_DIR" 2>/dev/null || true
  fi

  info "Converting the bare-metal node → docker — keeping its token, endpoint and interfaces."
  # signal "converting" to the panel NOW — before the (non-destructive) import below — so the node tile shows
  # it immediately, not after the per-interface import lines. install-docker.sh (exec'd later) emits the terminal.
  LC_URL="$PURL"; LC_TOKEN="$NTOK"; LC_VERIFY="${NVERIFY:-no}"; LC_FP="${NFP:-}"; lc_init convert-docker lc_emit_post   # with its pin (panel_req)
  # interfaces + turn-proxies are migrated in install-docker's NODE STAGE now — migrate_baremetal_ifaces +
  # migrate_baremetal_turns each ask "Transfer? (Y/n)" and copy-first (keys preserved, bare side comes down at the
  # switch). convert.sh no longer pre-stages node items before handing off. Just collect the names for recovery.
  names="$(printf '%s\n' "$ifaces" | while IFS="$(printf '\t')" read -r nm _; do [ -n "$nm" ] && printf '%s ' "$nm"; done || true)"; names="$(echo $names)"   # empty is fine (interface-less node) — just collected for recovery

  # NB: the WDTT server state (identity + owner passwords) is carried + the bare swg-wdtt units are stopped inside
  # install-docker.sh's node stage (migrate_baremetal_ifaces copy-first + the atomic switch), which runs for BOTH a
  # standalone node (exec below) and a master — so it isn't duplicated here.

  # 3) everything is staged; the BARE NODE IS STILL UP + serving the whole time. Persist the identity (so an
  #    interrupt during the final switch can resume), then hand off — install-docker.sh does the ATOMIC SWITCH:
  #    it tears the bare node down ONLY right before bringing the container up (see SWG_CONVERT_DIR=convert-docker).
  write_recovery "$names"

  # 4) hand off to install-docker.sh (docker node) with the SAME token. It detects the imported confs
  #    (picker shows them as "already on this node"; add more if you want), writes .env and brings the
  #    stack up. Same token ⇒ the panel keeps one node.
  info "Running install-docker.sh (docker node) — adopt $(b "$names") and finish the setup…"
  echo
  _carry="$(mktemp 2>/dev/null || echo /tmp/swg-carry.$$)"; carry_dropins_to_env "$_carry" swg-noded   # its own drop-ins → .env
  lc_handoff   # exec replaces us → install-docker.sh owns the terminal; SWG_CONVERT_DIR makes it emit "converted-docker"
  exec env NODE_TOKEN="$NTOK" PANEL_URL="$PURL" NODE_ENDPOINT="$NEP" TLS_VERIFY="$NVERIFY" TLS_FINGERPRINT="$NFP" SWG_CONVERT_DIR=convert-docker \
       ${NDNS:+DNS="$NDNS"} SWG_CARRY_ENV="$_carry" bash "$SRC/install-docker.sh" node
fi

die "unsupported conversion: $FROM → $TO ($ROLE) — supported: baremetal→docker and docker→baremetal, for node, host or master."
