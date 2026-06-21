#!/usr/bin/env bash
# convert.sh [--check] <from-method> <to-method> <role>
#   Migrate a swg deployment between docker and bare-metal, preserving settings / identity / interfaces.
#   Driven by bootstrap.sh's cross-method conflict prompt; can also be run by hand.
#
#   --check          only run the port/interface pre-flight (prints clashes, exits non-zero if any)
#   from/to          docker | baremetal
#   role             node | host | master
#
# Status: NODE  docker → bare-metal is automated. The reverse (bare-metal → docker) and the PANEL
# (host, and the panel half of master) are not yet — those exit non-zero so the caller falls back to
# "keep and re-install" or a manual uninstall+install.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DOCKER_DIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then C_BLUE=$'\033[38;5;39m'; C_YEL=$'\033[33m'; C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; RESET=$'\033[0m'; BOLD=$'\033[1m'
else C_BLUE=""; C_YEL=""; C_RED=""; C_GREEN=""; RESET=""; BOLD=""; fi
b(){ printf '%s%s%s' "$BOLD" "$*" "$RESET"; }
info(){ echo "${C_BLUE}::${RESET} $*"; }
warn(){ echo "${C_YEL}!${RESET} $*" >&2; }
die(){  echo "${C_RED}error:${RESET} $*" >&2; exit 1; }

CHECK=no; [ "${1:-}" = --check ] && { CHECK=yes; shift; }
FROM="${1:-}"; TO="${2:-}"; ROLE="${3:-}"
[ -n "$FROM" ] && [ -n "$TO" ] && [ -n "$ROLE" ] || die "usage: convert.sh [--check] <docker|baremetal> <docker|baremetal> <node|host|master>"

# ── Panel/host conversion isn't automated yet → non-zero so the caller loops back to keep/abort ──
case "$ROLE" in host|master)
  warn "Converting the PANEL between docker and bare-metal isn't automated yet (only nodes are)."
  echo  "  Choose 'keep and re-install', or uninstall the existing panel first and install the other method." >&2
  exit 1;;
esac

# ── NODE: docker → bare-metal ──
if [ "$FROM" = docker ] && [ "$TO" = baremetal ]; then
  envf="$DOCKER_DIR/.env"; confd="$DOCKER_DIR/data/node-confs"
  [ -f "$envf" ] || die "no docker node settings found at $envf"
  getv(){ sed -n "s/^$1=//p" "$envf" 2>/dev/null | head -1 | sed 's/^"//; s/"$//'; }
  NTOK="$(getv NODE_TOKEN)"; PURL="$(getv PANEL_URL)"; NEP="$(getv NODE_ENDPOINT)"
  NIFS="$(getv NODE_IFACES)"; NIF="$(getv NODE_IFACE)"; NPLAIN="$(getv NODE_PLAIN_WG)"; NVERIFY="$(getv TLS_VERIFY)"
  [ "$NVERIFY" = yes ] || NVERIFY=no

  # interface specs as "name:proto" (proto = awg|wg) from NODE_IFACES, else the single NODE_IFACE
  specs=""
  if [ -n "$NIFS" ]; then
    OIFS=$IFS; IFS=','
    for e in $NIFS; do IFS=$OIFS
      nm="$(printf '%s' "$e" | cut -d: -f1)"; pr="$(printf '%s' "$e" | cut -d: -f4)"
      [ "$pr" = wg ] || pr=awg
      [ -n "$nm" ] && specs="${specs:+$specs }$nm:$pr"; IFS=','
    done; IFS=$OIFS
  elif [ -n "$NIF" ]; then
    pr=awg; [ "$NPLAIN" = yes ] && pr=wg; specs="$NIF:$pr"
  fi
  [ -n "$specs" ] || die "no interfaces found in the docker node's .env"

  # pre-flight: a bare-metal conf of the same NAME already present is a real clash (the docker
  # node still holds the ports, but those free up the moment we stop its container below).
  conflicts=""
  for s in $specs; do nm="${s%:*}"
    { [ -e "/etc/amnezia/amneziawg/$nm.conf" ] || [ -e "/etc/wireguard/$nm.conf" ]; } && conflicts="${conflicts:+$conflicts }$nm"
  done
  if [ "$CHECK" = yes ]; then
    if [ -n "$conflicts" ]; then
      warn "a bare-metal interface already exists with these name(s): $(b "$conflicts")"
      echo  "  Rename/remove them (or pick 'keep and re-install'), then retry." >&2
      exit 1
    fi
    info "pre-flight OK — interfaces to migrate: $(b "$(for s in $specs; do printf '%s ' "${s%:*}"; done)")"
    echo
    exit 0
  fi
  [ -n "$conflicts" ] && die "interface name clash: $conflicts (run with --check first)"

  info "Converting the docker node → bare-metal — keeping its token, endpoint and interfaces."
  # 1) stop the docker datapath so it releases the wg UDP ports + /dev/net/tun
  if command -v docker >/dev/null 2>&1; then
    docker rm -f swg-node >/dev/null 2>&1 || true
    # node-only deployment (no panel container) → take the whole stack down to free its network
    if ! docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-panel; then
      [ -f "$DOCKER_DIR/docker-compose.yml" ] && ( cd "$DOCKER_DIR" && { docker compose down >/dev/null 2>&1 || docker-compose down >/dev/null 2>&1 || true; } )
    fi
  fi
  # 2) copy each interface's .conf into the bare-metal location (private key + Amnezia params carry over)
  names=""
  for s in $specs; do nm="${s%:*}"; pr="${s#*:}"
    src="$confd/$nm.conf"
    [ -f "$src" ] || { warn "missing $src — skipping interface '$nm'"; continue; }
    if [ "$pr" = wg ]; then dest="/etc/wireguard/$nm.conf"; else dest="/etc/amnezia/amneziawg/$nm.conf"; fi
    mkdir -p "$(dirname "$dest")"; cp "$src" "$dest"; chmod 600 "$dest"
    info "imported $(b "$nm") → $dest"
    names="${names:+$names,}$nm"
  done
  [ -n "$names" ] || die "no interface confs copied (looked in $confd)"

  # 3) hand off to install-node.sh with the SAME token. We do NOT pass MANAGE_IFACES: the copied
  #    confs are auto-detected, so its interface picker shows them as adoptable and lets you add more
  #    (queued + created after the tools install). Same token ⇒ the panel keeps one node.
  info "Running install-node.sh — adopt $(b "$names") (and add more if you want), then it wires the daemon…"
  echo
  exec env NODE_TOKEN="$NTOK" PANEL_URL="$PURL" ENDPOINT_IP="$NEP" \
       TLS_VERIFY="$NVERIFY" bash "$SRC/install-node.sh"
fi

# ── NODE: bare-metal → docker (not yet) ──
if [ "$FROM" = baremetal ] && [ "$TO" = docker ]; then
  warn "Converting a bare-metal node → docker isn't automated yet."
  echo  "  Choose 'keep and re-install', or uninstall the bare-metal node first and install the docker node." >&2
  exit 1
fi

die "unsupported conversion: $FROM → $TO ($ROLE)"
