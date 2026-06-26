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
. "$SRC/lib/common.sh"   # shared helpers (dl_turn_bin + validators)
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
# ── consistent list rows (green name + detail), matching the installers' summaries ──
# iface_row <name> <proto> <conf> <endpoint> — green name, proto, endpoint:listenport, address (from the conf)
iface_row(){ local n="$1" proto="$2" conf="$3" ep="$4" lp addr   # set -e safe: a missing/empty conf renders "?" — without the || true a sed file-not-found (rc 2) trips pipefail+set -e, and the bootstrap then LOOPS on the failed --check
  lp="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$conf" 2>/dev/null | head -1 || true)"
  addr="$(sed -n 's/^[[:space:]]*Address[[:space:]]*=[[:space:]]*\([0-9./]*\).*/\1/p' "$conf" 2>/dev/null | head -1 || true)"
  printf '    %s%s%s  %s%-10s%s  %s:%s  %s\n' "$C_GREEN" "$(printf '%-10s' "$n")" "$RESET" "$BOLD" "$(proto_label "$proto")" "$RESET" "${ep:-?}" "${lp:-?}" "${addr:-?}"; }
# the interface a turn-proxy forwards to: the iface whose ListenPort matches the connect port (else empty)
fwd_iface_for(){ local cp="${1##*:}" f lp; for f in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf "$DOCKER_DIR/data/node-confs/"*.conf; do [ -f "$f" ] || continue; lp="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$f" | head -1)"; [ -n "$lp" ] && [ "$lp" = "$cp" ] && { basename "$f" .conf; return 0; }; done; return 0; }   # no match → empty + success (a non-zero here would trip set -e in callers)
# turn_row <service> <listen> <connect> — green service + "listen → connect (iface)"
turn_row(){ local fw; fw="$(fwd_iface_for "${3:-}")"; printf '    %s%s%s %s → %s%s\n' "$C_GREEN" "$1" "$RESET" "${2:-?}" "${3:-?}" "${fw:+ ($fw)}"; }
# turn_unit_lc <unit-path> — echo "<listen>\t<connect>" for a host turn-proxy systemd unit (turn.env, else ExecStart)
turn_unit_lc(){ local u="$1" svc inst envf exe lis="" con=""
  svc="$(basename "$u" .service)"; inst="${svc#vk-turn-proxy-}"; envf="/opt/vk-turn-proxy/$inst/turn.env"
  if [ -f "$envf" ]; then lis="$(sed -n 's/^SWG_LISTEN=//p' "$envf" | head -1)"; con="$(sed -n 's/^SWG_CONNECT=//p' "$envf" | head -1)"; fi
  if [ -z "$lis" ]; then exe="$(sed -n 's/^ExecStart=//p' "$u" | head -1)"
    lis="$(printf '%s' "$exe" | sed -n 's/.*-listen[ =]\{1,\}\([^ ]*\).*/\1/p')"; con="$(printf '%s' "$exe" | sed -n 's/.*-connect[ =]\{1,\}\([^ ]*\).*/\1/p')"; fi
  printf '%s\t%s\n' "$lis" "$con"; }
detect_wan(){ ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n1; }
# import a (docker) conf as a BARE-METAL conf: drop any PostUp/PostDown, then add host NAT (the bare
# datapath has no container to masquerade for it). Keys + Address + Amnezia params carry over.
import_bare_conf(){ # <src> <dest>
  local src="$1" dest="$2" addr subnet wan up down
  addr="$(sed -n 's/^[[:space:]]*[Aa]ddress[[:space:]]*=//p' "$src" | head -1 | sed 's/,.*//; s/[[:space:]]//g')"
  subnet="$(python3 -c 'import ipaddress,sys;print(ipaddress.ip_network(sys.argv[1],strict=False))' "$addr" 2>/dev/null || echo "$addr")"
  wan="$(detect_wan)"; [ -n "$wan" ] || wan=eth0
  up="sysctl -q -w net.ipv4.ip_forward=1; iptables -t nat -A POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -A FORWARD -i %i -o ${wan} -j ACCEPT; iptables -A FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
  down="iptables -t nat -D POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -D FORWARD -i %i -o ${wan} -j ACCEPT; iptables -D FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
  awk -v up="$up" -v down="$down" '
    /^[[:space:]]*[Pp]ost(Up|Down)[[:space:]]*=/ {next}     # drop any existing NAT hooks
    {print}
    /^\[Interface\][[:space:]]*$/ && !d {print "PostUp = " up; print "PostDown = " down; d=1}
  ' "$src" > "$dest"
  chmod 600 "$dest"
}

cyn(){ local a; printf '  %s (Y/n): ' "$1"; read -r a 2>/dev/null </dev/tty || a=y; case "$a" in [Nn]*) return 1;; *) return 0;; esac; }

# Lifecycle signalling is handled by lc_init (lib/common.sh): it's armed at the point we tell the panel
# "converting…", and its EXIT/INT traps then emit converted-* (success) / convert-aborted / convert-failed.
# docker→bare runs install-node.sh as a subprocess (this script stays in control → its trap fires); bare→docker
# execs install-docker.sh, which carries SWG_CONVERT_DIR so IT emits the terminal.

# install a HOST systemd turn-proxy (docker→bare): svc owner listen connect params
turn_install_host(){
  local svc="$1" owner="$2" lis="$3" con="$4" params="$5" inst dir bin arch url
  local ok=1 ver fork fdir sbin mk
  inst="${svc#vk-turn-proxy-}"; fork="${inst%-*}"
  fdir="/opt/vk-turn-proxy/.bin/$fork"; sbin="$fdir/server"   # ONE binary per fork — shared by every instance
  dir="/opt/vk-turn-proxy/$inst"; bin="$dir/server"          # this instance: turn.env + a 'server' symlink → the shared binary
  case "$(uname -m)" in aarch64|arm64) arch=arm64;; *) arch=amd64;; esac
  url="https://github.com/$owner/releases/latest/download/server-linux-$arch"
  mkdir -p "$fdir" "$dir"
  mk="/var/lib/swg-noded/turn-pending/$svc"; mkdir -p /var/lib/swg-noded/turn-pending 2>/dev/null || true
  printf '%s\n%s\n%s\n' "$lis" "$con" "$owner" > "$mk" 2>/dev/null || true   # the running node shows this as "installing" until its unit is up
  if [ -x "$sbin" ]; then info "  $(b "$svc") — reusing the $fork binary already downloaded"
  else
    info "  migrating $(b "$svc") — downloading $owner from GitHub (up to ~2 min)…"
    dl_turn_bin "$owner" "$arch" "$sbin" && chmod +x "$sbin" || ok=0
  fi
  ln -sfn "../.bin/$fork/server" "$bin"   # unit ExecStart points here; resolves to the shared binary
  # remember the fork's settings so it survives a failed download: repo.txt (reinstall owner) + version (shared), turn.env + unit.
  printf '%s\n' "$owner" > "$fdir/repo.txt"; chmod 644 "$fdir/repo.txt" 2>/dev/null || true
  ver=unknown; [ "$ok" = 1 ] && ver="$(curl -fsS -o /dev/null -w '%{redirect_url}' --connect-timeout 15 --max-time 30 "$url" 2>/dev/null | sed -nE 's#.*/releases/download/([^/]+)/.*#\1#p')"
  printf '%s\n' "${ver:-unknown}" > "$fdir/version.txt"; chmod 644 "$fdir/version.txt" 2>/dev/null || true
  cat > "$dir/turn.env" <<EOF
SWG_LISTEN=${lis}
SWG_CONNECT=${con}
SWG_PARAMS=${params}
EOF
  cat > "/etc/systemd/system/$svc.service" <<EOF
[Unit]
Description=vk-turn-proxy ($owner) — ${lis} → ${con}
After=network-online.target
Wants=network-online.target

[Service]
EnvironmentFile=-${dir}/turn.env
ExecStart=${bin} -listen \${SWG_LISTEN} -connect \${SWG_CONNECT} \$SWG_PARAMS
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload 2>/dev/null || true
  # TURN_DEFER_START: write+enable but DON'T start (docker still holds the listen port) — the switch starts it later.
  if [ -n "${TURN_DEFER_START:-}" ]; then systemctl enable "$svc" 2>/dev/null || true
  else systemctl enable --now "$svc" 2>/dev/null || true; fi   # without the binary the unit just stays down (panel shows it, Reinstall re-fetches)
  rm -f "$mk" 2>/dev/null || true   # done → the node reports the real unit now (up, or down if the download failed)
  [ "$ok" = 1 ]
}

# pre-download every fork's turn binary into the shared cache (/opt/vk-turn-proxy/.bin/<fork>/server) WHILE the
# docker node is still up + serving — so the post-switch turn_to_bare reuses them (no slow download after the cutover).
turn_predownload(){
  local rec="$DOCKER_DIR/data/node/turn-proxy.json" list svc owner lis con params arch fork fdir sbin n=0
  command -v python3 >/dev/null 2>&1 || return 0
  [ -f "$rec" ] || return 0
  case "$(uname -m)" in aarch64|arm64) arch=arm64;; *) arch=amd64;; esac
  list="$(python3 - "$rec" <<'PY' 2>/dev/null
import json, sys
try: d = json.load(open(sys.argv[1])); tps = d.get("turn_proxies") or []
except Exception: tps = []
for t in (tps if isinstance(tps, list) else []):
    if t.get("service"): print("\t".join([t.get("service",""), t.get("owner",""), t.get("listen",""), t.get("connect",""), (t.get("params") or "")]))
PY
)"
  [ -n "$list" ] || return 0
  info "Pre-downloading turn-proxy binaries while the docker node still serves (keeps the cutover quick)…"
  while IFS="$(printf '\t')" read -r svc owner lis con params; do
    [ -n "$svc" ] && [ -n "$owner" ] || continue
    fork="${svc#vk-turn-proxy-}"; fork="${fork%-*}"; fdir="/opt/vk-turn-proxy/.bin/$fork"; sbin="$fdir/server"
    [ -x "$sbin" ] && { sub "$(b "$fork") binary already present"; continue; }
    mkdir -p "$fdir"
    info "Downloading $(b "$fork") turn-proxy binary…"
    if dl_turn_bin "$owner" "$arch" "$sbin"; then chmod +x "$sbin" 2>/dev/null || true; sub "downloaded $(b "$fork") binary"; n=$((n+1))
    else warn "  $fork: pre-download failed — turn_to_bare will retry it after the switch"; rm -f "$sbin" 2>/dev/null || true; fi
  done <<EOF
$list
EOF
  [ "$n" -gt 0 ] && sub "cached $n turn-proxy binary(ies) — the switch + migration will be fast"
  return 0
}

# docker turn record → host systemd units, then drop the swg-turn containers
turn_to_bare(){
  local rec="$DOCKER_DIR/data/node/turn-proxy.json" list svc owner lis con params
  command -v python3 >/dev/null 2>&1 || return 0
  [ -f "$rec" ] || return 0
  list="$(python3 - "$rec" <<'PY' 2>/dev/null
import json, sys
try: d = json.load(open(sys.argv[1])); tps = d.get("turn_proxies") or []
except Exception: tps = []
for t in (tps if isinstance(tps, list) else []):
    if t.get("service"): print("\t".join([t.get("service",""), t.get("owner",""), t.get("listen",""), t.get("connect",""), (t.get("params") or "")]))
PY
)"
  [ -n "$list" ] || return 0
  echo; info "Turn-proxy services to migrate (host systemd units written now; brought up at the switch):"; echo
  while IFS="$(printf '\t')" read -r svc owner lis con params; do [ -n "$svc" ] && turn_row "$svc" "$lis" "$con"; done <<EOF
$list
EOF
  echo
  cyn "Transfer these turn-proxies into the bare-metal node?" || { info "  leaving them on docker — they stop at the switch; you can add fresh ones in the next step"; return 0; }
  # Write each host unit NOW, enabled but NOT started, WHILE the docker turn containers still hold the listen
  # ports — install-node starts them after the switch frees the ports.
  while IFS="$(printf '\t')" read -r svc owner lis con params; do
    [ -n "$svc" ] || continue
    [ -n "$owner" ] || { warn "  $svc: no fork in the record — skipping"; continue; }
    if TURN_DEFER_START=1 turn_install_host "$svc" "$owner" "$lis" "$con" "$params"; then
      sub "prepared $(b "$svc") → host systemd (starts at the switch)"; MIGRATED_TURNS="${MIGRATED_TURNS:+$MIGRATED_TURNS }$svc"
    else
      warn "  $svc: binary download failed — its unit + settings were kept, so it shows on the panel as failed; open it and press Reinstall (no re-entry needed)"
    fi
  done <<EOF
$list
EOF
}

# host systemd turn units → docker record (COPY ONLY — the host units are torn down later, at the switch, so
# an abort mid-copy never loses a turn-proxy). Records the migrated services in MIGRATED_TURNS for the teardown.
turn_to_docker(){
  local units u svc exe lis con params owner envf _lis _con rec="$DOCKER_DIR/data/node/turn-proxy.json"
  command -v python3 >/dev/null 2>&1 || return 0
  units="$(ls /etc/systemd/system/vk-turn-proxy-*.service 2>/dev/null || true)"
  [ -n "$units" ] || return 0
  echo; info "Turn-proxy services to migrate:"; echo
  # NB: '|| true' — turn_unit_lc has no trailing newline, so read returns 1 at EOF and would abort under set -e.
  for u in $units; do svc="$(basename "$u" .service)"; IFS="$(printf '\t')" read -r _lis _con < <(turn_unit_lc "$u") || true; turn_row "$svc" "$_lis" "$_con"; done
  echo
  cyn "Transfer these turn-proxies into the docker node?" || { info "  left the host turn-proxies running"; return 0; }
  mkdir -p "$(dirname "$rec")"
  for u in $units; do
    svc="$(basename "$u" .service)"
    exe="$(sed -n 's/^ExecStart=//p' "$u" | head -1)"
    case "$exe" in
      *'${SWG_'*)   # EnvironmentFile form — read listen/connect/params out of turn.env
        envf="$(sed -n 's/^EnvironmentFile=-\{0,1\}//p' "$u" | head -1)"
        lis="$(sed -n 's/^SWG_LISTEN=//p' "$envf" 2>/dev/null | head -1)"
        con="$(sed -n 's/^SWG_CONNECT=//p' "$envf" 2>/dev/null | head -1)"
        params="$(sed -n 's/^SWG_PARAMS=//p' "$envf" 2>/dev/null | head -1)" ;;
      *)            # legacy baked-ExecStart form
        lis="$(printf '%s' "$exe" | sed -n 's/.*-listen[ =]\{1,\}\([^ ]*\).*/\1/p')"
        con="$(printf '%s' "$exe" | sed -n 's/.*-connect[ =]\{1,\}\([^ ]*\).*/\1/p')"
        params="$(printf '%s' "$exe" | sed -n 's/.*-connect[ =]\{1,\}[^ ]*[[:space:]]*\(.*\)$/\1/p')" ;;
    esac
    owner="$(sed -n 's/.*vk-turn-proxy (\([^)]*\)).*/\1/p' "$u" | head -1)"
    python3 - "$rec" "$svc" "$owner" "$lis" "$con" "$params" <<'PY' || true
import json, sys, re
p, svc, owner, lis, con, params = sys.argv[1:7]
try: d = json.load(open(p)); tps = d.get("turn_proxies") if isinstance(d, dict) else None; tps = tps if isinstance(tps, list) else []
except Exception: tps = []
tps = [t for t in tps if t.get("service") != svc]
m = re.search(r"-wrap-key[ =]+(\S+)", params or "")
tps.append({"service": svc, "listen": lis, "connect": con, "params": (params or "").strip(),
            "wrap_key": (m.group(1) if m else ""), "owner": owner})
json.dump({"turn_proxies": tps}, open(p, "w"))
PY
    MIGRATED_TURNS="${MIGRATED_TURNS:+$MIGRATED_TURNS }$svc"   # staged only — torn down at the switch (below)
    sub "staged $(b "$svc") → docker record (recreated as a container on the node's first run)"
  done
}

CHECK=no; [ "${1:-}" = --check ] && { CHECK=yes; shift; }
FROM="${1:-}"; TO="${2:-}"; ROLE="${3:-}"
[ -n "$FROM" ] && [ -n "$TO" ] && [ -n "$ROLE" ] || die "usage: convert.sh [--check] <docker|baremetal> <docker|baremetal> <node|host|master>"

# prominent title — same look as the installers / update.sh (only on the real run, not the --check pre-flight)
if [ "$CHECK" != yes ]; then
  _fl="$([ "$FROM" = docker ] && echo DOCKER || echo BARE-METAL)"; _tl="$([ "$TO" = docker ] && echo DOCKER || echo BARE-METAL)"
  echo; info "SWG $_fl → $_tl CONVERSION ($ROLE)"; echo
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
  { printf "SWG_RV_FROM='%s'\nSWG_RV_TO='%s'\nSWG_RV_ROLE='%s'\n" "$FROM" "$TO" "$ROLE"
    printf "SWG_RV_TOKEN='%s'\nSWG_RV_URL='%s'\nSWG_RV_EP='%s'\nSWG_RV_VERIFY='%s'\n" "$NTOK" "$PURL" "$NEP" "${NVERIFY:-no}"
    printf "SWG_RV_NAMES='%s'\nSWG_RV_AT='%s'\n" "${1:-}" "$(date +%s 2>/dev/null || echo 0)"
  } > "$RECOVERY" 2>/dev/null && chmod 600 "$RECOVERY" 2>/dev/null || true
}
clear_recovery(){ rm -f "$RECOVERY" 2>/dev/null || true; }
MIGRATED_TURNS=""   # turn-proxy services turn_to_bare moved onto host systemd (for the final summary)
# final summary after a docker→bare convert: interfaces (now bare) + turn-proxies that migrated.
print_bare_summary(){   # print_bare_summary <iface names> <endpoint ip> <panel url>
  local ifn="$1" nep="$2" purl="$3" n conf proto svc inst lis con u units
  echo; echo "$(b '──────────────── CONVERSION COMPLETE ────────────────')"; echo
  echo "  Node      $(b "$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo node)")  →  now $(b bare-metal), syncs to $(b "$purl")"
  echo; echo "  $(b 'Interfaces') (managed bare-metal — peers stay in the panel):"; echo
  # ALL bare interfaces on disk (migrated $ifn PLUS any created during the install-node.sh step), not just $ifn.
  for conf in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf; do
    [ -f "$conf" ] || continue; n="$(basename "$conf" .conf)"
    case "$conf" in */wireguard/*) proto=wg;; *) proto=awg;; esac
    iface_row "$n" "$proto" "$conf" "$nep"
  done
  # ALL host turn-proxies on the box (migrated PLUS any added in the turn-add step), not just $MIGRATED_TURNS —
  # mirrors the interface loop above which scans disk, not just the migrated set.
  units="$(ls /etc/systemd/system/vk-turn-proxy-*.service 2>/dev/null || true)"
  if [ -n "$units" ]; then
    echo; echo "  $(b 'Turn-proxies') (host systemd, managed from the panel):"; echo
    for u in $units; do svc="$(basename "$u" .service)"; inst="${svc#vk-turn-proxy-}"
      lis="$(sed -n 's/^SWG_LISTEN=//p' "/opt/vk-turn-proxy/$inst/turn.env" 2>/dev/null | head -1 || true)"
      con="$(sed -n 's/^SWG_CONNECT=//p' "/opt/vk-turn-proxy/$inst/turn.env" 2>/dev/null | head -1 || true)"
      turn_row "$svc" "$lis" "$con"
    done
  else
    echo; echo "  $(b 'Turn-proxies'): none."
  fi
  echo; node_reconfig_block baremetal
}
# a LIVE docker node = an actual swg-node container (running or stopped). A bare $DOCKER_DIR with no
# container is just a stale leftover (e.g. a previous convert that didn't finish moving it aside).
docker_node_present(){ command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-node; }

# ── PANEL host conversion ──────────────────────────────────────────────────────
# The panel's state is the SAME JSON in both methods (one swg-panel-server binary); only the LOCATION differs:
#   /var/lib/swg-panel ↔ $DOCKER_DIR/data/lib  (roster users.json, nodes.json + node token HASHES, configs/)
#   /etc/swg-panel     ↔ $DOCKER_DIR/data/etc  (fleet.json, auth login, tls/ cert, acme/ renewal state)
#   /var/www/wgstats   ↔ $DOCKER_DIR/data/stats(status snapshots)
# So conversion is a copy-first state move + a port hand-off. URL/port/TLS/login are preserved so every node
# stays connected (nodes.json token hashes carry over). Master (panel + local node) conversion comes next.
docker_panel_present(){ command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-panel; }
bare_panel_present(){ [ -f /etc/systemd/system/swg-panel-server.service ] || [ -x /opt/swg-panel/swg-panel-server ]; }
# teardown_bare_panel() now lives in lib/common.sh (so install-docker.sh can call it at the atomic switch).
# master convert: emit the lifecycle status to BOTH the panel header (host_proc file) and the local node tile
# (proc-status POST to the loopback panel), so "converting/converted" shows on the node too, not just the panel.
lc_emit_hostnode(){ lc_emit_file "$1" "${2:-}"; lc_emit_post "$1" "${2:-}"; }

if { [ "$ROLE" = host ] || [ "$ROLE" = master ]; } && [ "$FROM" = baremetal ] && [ "$TO" = docker ]; then
  ETC=/etc/swg-panel; STATE=/var/lib/swg-panel; STATS=/var/www/wgstats; pconf="$ETC/install.conf"; PROFILE="$ROLE"
  bare_panel_present || [ -n "${SWG_RV_URL:-}" ] || die "no bare-metal panel found (swg-panel-server missing)"
  gv(){ sed -n "s/^$1=//p" "$pconf" 2>/dev/null | head -1; }
  PDOM="$(gv PANEL_DOMAIN)"; PPORT="$(gv PORT)"; PTLS="$(gv TLS_MODE)"; PEMAIL="$(gv ACME_EMAIL)"; PBASE="$(gv PANEL_BASE)"
  PCFTOKEN="$(gv CF_TOKEN)"; PCFORIGIN="$(gv CF_ORIGIN_TOKEN)"   # carry CF creds so cloudflare/cf15 renewal works in the container
  PUSER="$(sed -n 's/^\([^:]*\):.*/\1/p' "$ETC/auth" 2>/dev/null | head -1)"
  [ -n "${SWG_RV_URL:-}" ] && PDOM="${PDOM:-$SWG_RV_URL}"
  [ -n "$PDOM" ] || die "couldn't read the panel domain ($pconf missing and no recovery state)"
  case "$PTLS" in letsencrypt|letsencrypt-ip|cloudflare|cf15|selfsigned|none) :;; *) PTLS=selfsigned;; esac
  [ -n "$PPORT" ] || PPORT=443
  docker_panel_present && die "a docker panel (swg-panel container) already exists — remove it first"

  # MASTER: also read the co-located node's identity (preserve its token so the panel keeps the same node) +
  # its interface confs (imported below). The local node reaches the panel on the compose net (swg-panel:8443).
  NTOK=""; NEP=""; mifaces=""
  if [ "$ROLE" = master ] && command -v python3 >/dev/null 2>&1 && [ -f /etc/swg-agent/config.json ]; then
    NTOK="$(python3 -c 'import json;print((json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("token","") or "")' 2>/dev/null || true)"
    NEP="$(python3 -c 'import json;print(json.load(open("/etc/swg-agent/config.json")).get("endpoint_host","") or "")' 2>/dev/null || true)"
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
    sub "pre-flight OK"
    if [ "$ROLE" = master ]; then info "Master → docker keeps: URL $(b "$PDOM"), login, roster, nodes, the $(b "$PTLS") cert AND the local node (token + interfaces + turn-proxies). Brief downtime at the switch."
    else info "Panel → docker keeps: URL $(b "$PDOM"), login, roster, nodes + the $(b "$PTLS") cert. Brief panel downtime at the switch (nodes self-heal)."; fi
    exit 0
  fi
  command -v docker >/dev/null 2>&1 || die "docker is required"

  info "Converting the bare-metal $(b "$ROLE") → docker — keeping the panel's URL/login/roster/nodes/cert$([ "$ROLE" = master ] && echo " and the local node")."
  PURL="$PDOM"; write_recovery ""   # persist FROM/TO/ROLE for resume BEFORE any teardown
  # panel HEADER status: converting → converted-docker (+ convert-aborted/-failed on a bad exit). The bare panel
  # serves /var/lib/swg-panel/host_proc now (and it gets staged into the container); we repoint LC_FILE at the
  # container's host_proc after the switch so the success/failure terminal lands where the docker panel reads it.
  LC_FILE=/var/lib/swg-panel/host_proc
  if [ "$ROLE" = master ] && [ -n "$NTOK" ]; then   # MASTER: status on BOTH the panel header (file) AND the local node tile (POST to the loopback panel)
    LC_URL="https://127.0.0.1:$PPORT"; LC_TOKEN="$NTOK"; LC_VERIFY=no
    lc_init convert-docker lc_emit_hostnode
  else
    lc_init convert-docker lc_emit_file
  fi
  if [ "$RESUMING" != yes ] && [ -e "$DOCKER_DIR" ]; then
    _bak="$DOCKER_DIR.pre-convert-$(date +%Y%m%d-%H%M%S 2>/dev/null || echo bak)"
    mv "$DOCKER_DIR" "$_bak" 2>/dev/null && info "moved a leftover $(b "$DOCKER_DIR") aside → $(b "$_bak")" || rm -rf "$DOCKER_DIR" 2>/dev/null || true
  fi

  # 1) COPY-FIRST: stage the panel state while the bare panel is STILL UP + serving every node
  mkdir -p "$DOCKER_DIR"/data/lib "$DOCKER_DIR"/data/etc "$DOCKER_DIR"/data/stats
  [ -d "$STATE" ] && cp -a "$STATE/." "$DOCKER_DIR/data/lib/"   2>/dev/null || true   # roster, nodes.json, configs
  [ -d "$ETC" ]   && cp -a "$ETC/."   "$DOCKER_DIR/data/etc/"   2>/dev/null || true   # fleet.json, auth, tls/
  [ -d "$STATS" ] && cp -a "$STATS/." "$DOCKER_DIR/data/stats/" 2>/dev/null || true
  # carry the acme.sh renewal state (bare keeps it in /root/.acme.sh; the container reads data/etc/acme) and
  # point its stored reload command at the container (kill -HUP 1) instead of the systemd unit, so renewals reload.
  for _ah in /root/.acme.sh "${HOME:-/root}/.acme.sh"; do [ -d "$_ah" ] && { mkdir -p "$DOCKER_DIR/data/etc/acme"; cp -a "$_ah/." "$DOCKER_DIR/data/etc/acme/" 2>/dev/null || true; break; }; done
  find "$DOCKER_DIR/data/etc/acme" -name '*.conf' -exec sed -i "s#^Le_ReloadCmd=.*#Le_ReloadCmd='kill -HUP 1'#" {} + 2>/dev/null || true
  sub "staged roster + nodes + login + $(b "$PTLS") cert (+ acme renewal) → $DOCKER_DIR/data"

  # MASTER: the local node's interfaces + turn-proxies are migrated in the NODE STAGE (the install-docker node
  # sub-step below): migrate_baremetal_ifaces + migrate_baremetal_turns each ask "Transfer? (Y/n)" and copy-first.
  # So convert.sh stages ONLY the panel here — no node items before the host (nothing to orphan if interrupted).

  # 2) stage the compose project (prebuilt image pulled from GHCR)
  cp -a "$SRC/docker-compose.yml" "$DOCKER_DIR/" 2>/dev/null || true
  for f in Dockerfile Dockerfile.node Dockerfile.turn .dockerignore VERSION swg-panel-server swg-agent swg-noded index.html app.css app.js reconcile.js; do
    [ -e "$SRC/$f" ] && cp -a "$SRC/$f" "$DOCKER_DIR/" 2>/dev/null || true; done
  [ -d "$SRC/vendor" ] && cp -a "$SRC/vendor" "$DOCKER_DIR/" 2>/dev/null || true
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
  # ── HOST convert: exec install-docker host (panel only) — it owns the lifecycle terminal. ──
  if [ "$ROLE" = host ]; then
    info "Running install-docker.sh (host) — the panel setup; it switches over as the last step…"; echo
    lc_handoff
    exec env ROLE=host SWG_CONVERT_DIR=convert-docker SWG_CONVERT_KILL_PANEL=1 TLS_VERIFY=no bash "$SRC/install-docker.sh" host
  fi
  # ── MASTER convert = the HOST converter + the NODE converter, run in sequence ───────────────────────────────
  # The master's host-part IS install-docker host and its node-part IS install-docker node — guaranteed identical
  # to the individual converters, no bespoke master path. install-docker host brings up swg-panel + tears down the
  # bare panel; install-docker node then ADDS swg-node to the SAME compose project (EXISTING_DOCKER reads the .env)
  # and migrates this box's interfaces + turn-proxies in its own node stage. convert.sh owns the lifecycle terminal
  # (SWG_LC_PARENT=1 ⇒ neither sub-step emits its own), writing 'converted-docker' with the final line below.
  echo; info "HOST → docker — converting the panel (the local node keeps serving until the node step below)…"; echo
  env ROLE=host SWG_CONVERT_DIR=convert-docker SWG_CONVERT_KILL_PANEL=1 SWG_LC_PARENT=1 TLS_VERIFY=no \
      bash "$SRC/install-docker.sh" host \
    || die "the panel (host) convert failed — your state is safe in $DOCKER_DIR/data; check 'docker compose logs'"
  LC_FILE="$DOCKER_DIR/data/lib/host_proc"   # docker panel now owns host_proc → convert.sh's EXIT terminal lands there
  echo; info "NODE → docker — converting this box's local node (adds swg-node to the panel's compose project)…"; echo
  # CO-LOCATED node specifics (a standalone node doesn't need these): reach the LOCAL panel on the host-published
  # port (host networking can't resolve the compose name swg-panel), and manage turns via the panel (socket) so the
  # migrated turn-proxies materialise as containers. NODE_TOKEN/ENDPOINT are the preserved local-node identity.
  env SWG_CONVERT_DIR=convert-docker NODE_TOKEN="${NTOK:-}" NODE_ENDPOINT="${NEP:-$PDOM}" \
      PANEL_URL="https://127.0.0.1:$PPORT" TURN_MANAGE=panel SWG_LC_PARENT=1 TLS_VERIFY=no \
      bash "$SRC/install-docker.sh" node \
    || warn "the local node convert reported an error — check it on the panel."
  clear_recovery
  echo; ok "$(b master) converted to docker — panel + local node (host convert + node convert). Same login, roster, nodes + cert + local node. Nodes reconnect on their next sync."
  _sch=https; [ "$PTLS" = none ] && _sch=http
  _psuf=":$PPORT"; if { [ "$_sch" = https ] && [ "$PPORT" = 443 ]; } || { [ "$_sch" = http ] && [ "$PPORT" = 80 ]; }; then _psuf=""; fi
  echo; echo "──────────────── SUMMARY ────────────────"; echo
  echo "  Panel     $(b "${_sch}://${PDOM}${_psuf}${PBASE}/")"
  echo "  Login     unchanged — your existing $(b "${PUSER:-admin}") login + password"
  echo "  TLS       $(b "$PTLS")  ·  Method $(b docker) (was bare-metal)"
  echo "  Node      local node preserved (token + interfaces + turn-proxies)"
  echo "  Dir       $(b "$DOCKER_DIR")  ·  edit $(b .env), then $(b "docker compose --profile master up -d")"
  echo "  Logs      $(b "cd $DOCKER_DIR && docker compose logs -f")"
  echo
  exit 0
fi

# ── PANEL host/master: docker → bare-metal ── (mirror of the bare→docker block; reuses install-host.sh + install-node.sh)
if { [ "$ROLE" = host ] || [ "$ROLE" = master ]; } && [ "$FROM" = docker ] && [ "$TO" = baremetal ]; then
  ETC=/etc/swg-panel; STATE=/var/lib/swg-panel; STATS=/var/www/wgstats; envf="$DOCKER_DIR/.env"
  [ -f "$envf" ] || [ -n "${SWG_RV_URL:-}" ] || die "no docker panel settings found at $envf"
  getv(){ sed -n "s/^$1=//p" "$envf" 2>/dev/null | head -1 | sed 's/^"//; s/"$//'; }
  PDOM="$(getv PANEL_DOMAIN)"; PPORT="$(getv PANEL_PORT)"; PTLS="$(getv TLS)"; PEMAIL="$(getv ACME_EMAIL)"
  PBASE="$(getv PANEL_BASE)"; PUSER="$(getv PANEL_USER)"; PCFT="$(getv CF_TOKEN)"; PCFO="$(getv CF_ORIGIN_TOKEN)"
  NTOK="$(getv NODE_TOKEN)"; NEP="$(getv NODE_ENDPOINT)"   # master: the local node's preserved identity
  # fallback: a docker master's node token should be in .env, but if it's blank/placeholder read it straight from
  # the running node container so the local-node tile reliably gets "converting" at the START (matches bare→docker).
  case "${NTOK:-}" in ""|set-in-nodes-screen) NTOK="$(docker exec swg-node sh -c 'cat /etc/swg-agent/config.json' 2>/dev/null | python3 -c 'import json,sys;print((json.load(sys.stdin).get("panel") or {}).get("token","") or "")' 2>/dev/null || true)";; esac
  [ -n "${SWG_RV_URL:-}" ] && PDOM="${PDOM:-$SWG_RV_URL}"
  [ -n "$PDOM" ] || die "couldn't read the panel domain (docker .env missing and no recovery state)"
  case "$PTLS" in letsencrypt|letsencrypt-ip|cloudflare|cf15|selfsigned|none) :;; *) PTLS=selfsigned;; esac
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
  if [ "$ROLE" = master ] && [ -n "$NTOK" ]; then LC_URL="https://127.0.0.1:$PPORT"; LC_TOKEN="$NTOK"; LC_VERIFY=no; lc_init convert-bare lc_emit_hostnode
  else lc_init convert-bare lc_emit_file; fi

  # 1) COPY-FIRST: stage the panel state to the bare locations while the container is STILL UP + serving
  mkdir -p "$STATE" "$ETC" "$STATS"
  # Copy the panel state straight OUT of the RUNNING container — robust no matter how its data volume is wired
  # (a broken/empty ./data bind mount was silently losing the roster, login + nodes). Fall back to ./data only
  # when the container isn't found (e.g. a resume after it's already gone).
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx swg-panel; then
    docker cp swg-panel:/var/lib/swg-panel/. "$STATE/" 2>/dev/null || true   # roster (users.json), nodes.json, configs
    docker cp swg-panel:/etc/swg-panel/.     "$ETC/"   2>/dev/null || true   # fleet.json, auth, tls/, acme/
    docker cp swg-panel:/var/www/wgstats/.   "$STATS/" 2>/dev/null || true
  else
    [ -d "$DOCKER_DIR/data/lib" ]   && cp -a "$DOCKER_DIR/data/lib/."   "$STATE/" 2>/dev/null || true
    [ -d "$DOCKER_DIR/data/etc" ]   && cp -a "$DOCKER_DIR/data/etc/."   "$ETC/"   2>/dev/null || true
    [ -d "$DOCKER_DIR/data/stats" ] && cp -a "$DOCKER_DIR/data/stats/." "$STATS/" 2>/dev/null || true
  fi
  # GUARD: never proceed (and let install-host seed a blank panel) if the login + node store didn't come across.
  { [ -s "$ETC/auth" ] && [ -f "$STATE/nodes.json" ]; } || die "couldn't stage the panel state (login/nodes missing) — aborting to avoid data loss. The docker panel is untouched; check 'docker exec swg-panel ls -la /var/lib/swg-panel /etc/swg-panel'."
  # carry the acme renewal state back to the host (/root/.acme.sh) + repoint its reload cmd at the systemd unit
  if [ -d "$ETC/acme" ]; then
    mkdir -p /root/.acme.sh; cp -a "$ETC/acme/." /root/.acme.sh/ 2>/dev/null || true
    find /root/.acme.sh -name '*.conf' -exec sed -i "s#^Le_ReloadCmd=.*#Le_ReloadCmd='systemctl restart swg-panel-server'#" {} + 2>/dev/null || true
  fi
  # write the bare install.conf so install-host.sh's prompts DEFAULT to the preserved settings (Enter accepts)
  cat > "$ETC/install.conf" <<EOF
ROLE_SEL=host
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
  info "Installing the bare-metal panel — the docker panel keeps serving until the switch…"
  env ROLE=host PANEL_DOMAIN="$PDOM" PORT="$PPORT" PANEL_BASE="$PBASE" ACME_EMAIL="$PEMAIL" \
      CF_TOKEN="$PCFT" CF_ORIGIN_TOKEN="$PCFO" BASIC_USER="$PUSER" SERVE_MODE=internal SWG_CONVERT_DIR=convert-bare SWG_LC_PARENT=1 SWG_DEFER_START=1 \
      bash "$SRC/install-host.sh" \
    || die "install-host.sh failed — your panel state is safe in $STATE + $ETC; re-run the bare-metal host install to finish"

  # 3) THE ATOMIC SWITCH — only NOW stop the docker panel and start the bare one. Downtime is just this stop+start
  #    (~1-3s), not the whole install above. Same URL/port ⇒ nodes stay connected. A master keeps its docker NODE
  #    running for the node phase below (copy-first); install-node tears it down at its OWN switch (the last step).
  info "Switching over — stopping the docker panel, starting the bare-metal panel…"
  if [ "$ROLE" = master ]; then
    docker rm -f swg-panel >/dev/null 2>&1 || true   # stop ONLY the panel — the docker NODE keeps serving (copy-first)
  else
    ( cd "$DOCKER_DIR" && on_tty docker compose down ) 2>/dev/null || true; docker rm -f swg-panel >/dev/null 2>&1 || true
  fi
  _pu=no; for _i in 1 2 3; do if systemctl start swg-panel-server 2>/dev/null; then _pu=yes; break; fi; sleep 1; done   # bind :443 now that docker released it (brief retry for the handoff)
  [ "$_pu" = yes ] || die "couldn't start the bare-metal panel after stopping the docker panel — check 'systemctl status swg-panel-server'; your panel state is safe in $STATE + $ETC"

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
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx swg-node; then
      mkdir -p "$DOCKER_DIR/data/node-confs" "$DOCKER_DIR/data/node"
      docker cp swg-node:/etc/amnezia/amneziawg/. "$DOCKER_DIR/data/node-confs/" 2>/dev/null || true
      docker cp swg-node:/var/lib/swg-noded/.      "$DOCKER_DIR/data/node/"       2>/dev/null || true
    fi
    for f in "$DOCKER_DIR/data/node-confs/"*.conf; do [ -f "$f" ] || continue
      nm="$(basename "$f" .conf)"
      if grep -qiE '^[[:space:]]*(Jc|Jmin|Jmax|S1|S2|H1|H2|H3|H4|I1)[[:space:]]*=' "$f"; then dest="/etc/amnezia/amneziawg/$nm.conf"; else dest="/etc/wireguard/$nm.conf"; fi
      mkdir -p "$(dirname "$dest")"; import_bare_conf "$f" "$dest"
      sub "imported local-node interface $(b "$nm") → $dest (host NAT added)"; mnames="${mnames:+$mnames }$nm"
    done
    if [ -d "$DOCKER_DIR/data/node/iface-keys" ]; then mkdir -p /var/lib/swg-noded/iface-keys; cp -a "$DOCKER_DIR/data/node/iface-keys/." /var/lib/swg-noded/iface-keys/ 2>/dev/null || true; fi
    if [ -n "$mnames" ]; then   # install-node migrates the docker turns itself (Step 2), so no separate turn step here
      env NODE_TOKEN="$NTOK" PANEL_URL="https://127.0.0.1:$PPORT" ENDPOINT_IP="$NEP" ADOPTED_IFACES="$mnames" \
          SWG_CONVERT=1 TLS_VERIFY=no SWG_DOCKER_DIR="$DOCKER_DIR" bash "$SRC/install-node.sh" \
        || warn "the local node setup reported an error — check it on the panel."
    fi
  else
    # host-only (no node phase): the bare panel is up → flip the header tile to "converted" NOW, mirroring the
    # master's tile-split above. Otherwise only the end-of-run EXIT trap emits it (after the dir-move + summary),
    # which can land after the console's brief success-show window — so "converted" never appears on the header.
    lc_emit_file converted-bare
  fi

  # 3) move the old docker dir aside so a later convert-back isn't blocked by the leftover .env, then done
  if [ -d "$DOCKER_DIR" ]; then
    _bak="$DOCKER_DIR.converted-$(date +%Y%m%d-%H%M%S 2>/dev/null || echo bak)"
    mv "$DOCKER_DIR" "$_bak" 2>/dev/null && info "moved the old docker dir aside → $(b "$_bak") (backup — safe to delete)" || warn "couldn't move $DOCKER_DIR aside — remove it manually before converting back to docker"
  fi
  clear_recovery
  _psuf=""; case "$PPORT" in 443|80|"") :;; *) _psuf=":$PPORT";; esac
  echo; ok "$(b "$ROLE") converted to bare-metal — $(b "https://$PDOM$_psuf$PBASE/") (same login, roster, nodes + cert$([ "$ROLE" = master ] && echo " + local node")). Nodes reconnect on their next sync."
  echo; echo "──────────────── SUMMARY ────────────────"; echo
  # ── PANEL (the host) — its own group ──
  echo "  $(b PANEL)  ·  bare-metal (was docker)"
  echo "    URL      $(b "https://$PDOM$_psuf$PBASE/")"
  echo "    Login    unchanged — your existing $(b "${PUSER:-admin}") login + password"
  echo "    TLS      $(b "$PTLS")"
  echo "    Config   $(b /etc/swg-panel/)"
  echo "    Logs     $(b "journalctl -u swg-panel-server -f")"
  if [ "$ROLE" = master ]; then
    # ── LOCAL NODE — its own group (this master is also an entry server) ──
    echo
    echo "  $(b "LOCAL NODE")  ·  token + keys preserved, reports to the panel above"
    if [ -n "${mnames:-}" ]; then
      echo "    Interfaces"
      for _n in $mnames; do
        _c="/etc/amnezia/amneziawg/$_n.conf"; _pr=AmneziaWG; [ -f "$_c" ] || { _c="/etc/wireguard/$_n.conf"; _pr=WireGuard; }
        _lp="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$_c" 2>/dev/null | head -1)"
        _ad="$(sed -n 's/^[[:space:]]*Address[[:space:]]*=[[:space:]]*\([0-9./]*\).*/\1/p' "$_c" 2>/dev/null | head -1)"
        printf '      %s%-10s%s %-9s  %s:%-6s %s\n' "$C_GREEN" "$_n" "$RESET" "$_pr" "${NEP:-?}" "${_lp:-?}" "${_ad:-?}"
      done
    fi
    _turns="$(ls /etc/systemd/system/ 2>/dev/null | sed -n 's/\(.*turn-proxy.*\)\.service$/\1/p' | tr '\n' ' ')"
    [ -n "$_turns" ] && echo "    Turn     $(b "$_turns")"
    echo "    Config   $(b /etc/amnezia/amneziawg/) + $(b /etc/wireguard/)"
    echo "    Logs     $(b "journalctl -u swg-noded -f")"
  fi
  echo
  exit 0
fi

# ── NODE: docker → bare-metal ──
if [ "$FROM" = docker ] && [ "$TO" = baremetal ]; then
  envf="$DOCKER_DIR/.env"; confd="$DOCKER_DIR/data/node-confs"
  [ -f "$envf" ] || [ -n "${SWG_RV_TOKEN:-}" ] || die "no docker node settings found at $envf"   # resuming? the saved identity covers a half-torn-down .env
  getv(){ sed -n "s/^$1=//p" "$envf" 2>/dev/null | head -1 | sed 's/^"//; s/"$//'; }
  NTOK="$(getv NODE_TOKEN)"; PURL="$(getv PANEL_URL)"; NEP="$(getv NODE_ENDPOINT)"
  NIFS="$(getv NODE_IFACES)"; NIF="$(getv NODE_IFACE)"; NPLAIN="$(getv NODE_PLAIN_WG)"; NVERIFY="$(getv TLS_VERIFY)"
  [ -n "${SWG_RV_TOKEN:-}" ] && { NTOK="$SWG_RV_TOKEN"; PURL="$SWG_RV_URL"; NEP="$SWG_RV_EP"; NVERIFY="${SWG_RV_VERIFY:-no}"; }   # resume: saved identity wins
  [ "$NVERIFY" = yes ] || NVERIFY=no
  # co-located master-split (the panel STAYS on docker, only the local node converts to bare): the node's PANEL_URL
  # is the compose DNS name (swg-panel:PORT), unreachable outside the compose network. Point the bare node at the
  # panel's published loopback port instead, and don't verify the cert (it's for the domain, not 127.0.0.1).
  case "$PURL" in *://swg-panel:*|*://swg-panel/*|*://swg-panel)
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx swg-panel; then
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
  [ -n "$specs" ] || die "no interfaces found (looked in $confd and the docker node's .env)"

  # pre-flight: a bare-metal conf of the same NAME already present is a real clash (the docker
  # node still holds the ports, but those free up the moment we stop its container below).
  # On a RESUME these confs are OURS — the interrupted run already imported them — so they're not a clash;
  # the import step below keeps them as-is ("resume: don't re-import").
  conflicts=""
  if [ "$RESUMING" != yes ]; then
    for s in $specs; do nm="${s%:*}"
      { [ -e "/etc/amnezia/amneziawg/$nm.conf" ] || [ -e "/etc/wireguard/$nm.conf" ]; } && conflicts="${conflicts:+$conflicts }$nm"
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
  LC_URL="$PURL"; LC_TOKEN="$NTOK"; LC_VERIFY="${NVERIFY:-no}"; lc_init convert-bare lc_emit_post   # converting… now; converted-bare/aborted/failed on exit
  # NB: the DOCKER NODE STAYS UP + serving through the copy below AND install-node.sh's prompts. install-node
  #     does the ATOMIC SWITCH (it runs with SWG_CONVERT=1): it stops the docker datapath + clears leftover
  #     host netdevs ONLY right before it brings the bare interfaces up — never before.
  # 1) copy each interface's .conf into the bare-metal location (private key + Amnezia params carry over)
  names=""
  for s in $specs; do nm="${s%:*}"; pr="${s#*:}"
    src="$confd/$nm.conf"
    if [ "$pr" = wg ]; then dest="/etc/wireguard/$nm.conf"; else dest="/etc/amnezia/amneziawg/$nm.conf"; fi
    if [ -f "$dest" ]; then sub "kept $(b "$nm") → $dest (already imported)"; names="${names:+$names }$nm"; continue; fi   # resume: don't re-import
    [ -f "$src" ] || { warn "missing $src — skipping interface '$nm'"; continue; }
    mkdir -p "$(dirname "$dest")"; import_bare_conf "$src" "$dest"   # adds host NAT (docker confs have none)
    sub "imported $(b "$nm") → $dest (host NAT added)"
    names="${names:+$names }$nm"
  done
  [ -n "$names" ] || die "no interface confs copied (looked in $confd)"

  # carry the per-interface keypair backups across so the server-key revert baseline survives the move
  if [ -d "$DOCKER_DIR/data/node/iface-keys" ]; then
    mkdir -p /var/lib/swg-noded/iface-keys
    cp -a "$DOCKER_DIR/data/node/iface-keys/." /var/lib/swg-noded/iface-keys/ 2>/dev/null || true
    sub "carried interface keypair backups → /var/lib/swg-noded/iface-keys"
  fi

  # 3) THE SWITCH — install-node.sh runs all its prompts WHILE docker still serves: Step 1 interfaces, then
  #    Step 2 migrates the docker turn-proxies (deferred) + adds more. Then, as its LAST step, the atomic cutover:
  #    stop the docker datapath + turn containers → bring up bare interfaces → start the turn units → start
  #    swg-noded. So the node goes down + comes back ONCE, fully converted, in a single non-interactive step.
  info "Running install-node.sh — adopt $(b "$names") (add more if you want); then it does the switch as the last step…"
  echo
  # NB: '|| warn' — a non-zero exit (e.g. one interface failed to come up) must NOT abort the convert under set -e.
  env NODE_TOKEN="$NTOK" PANEL_URL="$PURL" ENDPOINT_IP="$NEP" ADOPTED_IFACES="$names" \
      SWG_CONVERT=1 TLS_VERIFY="$NVERIFY" SWG_DOCKER_DIR="$DOCKER_DIR" bash "$SRC/install-node.sh" \
    || warn "install-node.sh reported an error — check the node on the panel."

  # move the old docker dir aside (turn_to_bare needed its turn record) so a later bare→docker convert isn't
  # blocked by the leftover .env — UNLESS the docker PANEL is still running from this dir (a co-located master-split:
  # only the node converted, the panel stays on docker and needs the dir + its compose/.env + bind mounts).
  if [ -d "$DOCKER_DIR" ] && ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qx swg-panel; then
    _bak="$DOCKER_DIR.converted-$(date +%Y%m%d-%H%M%S)"
    if mv "$DOCKER_DIR" "$_bak" 2>/dev/null; then info "moved the old docker dir aside → $(b "$_bak") (backup — safe to delete)"
    else warn "couldn't move $DOCKER_DIR aside — remove it manually before converting back to docker"; fi
  fi
  clear_recovery   # convert finished cleanly → drop the recovery marker
  # the conversion is verified complete here; the lc EXIT trap (clean exit below) emits "converted-bare", which
  # the panel shows green for a few seconds, then the bare node reports normally (online) on its next sync.
  print_bare_summary "$names" "$NEP" "$PURL"   # complete summary: interfaces + the turn-proxies that migrated
  exit 0           # done (this block no longer execs install-node.sh, so end here, not the catch-all die)
fi

# ── NODE: bare-metal → docker ──
if [ "$FROM" = baremetal ] && [ "$TO" = docker ]; then
  cfg=/etc/swg-agent/config.json
  [ -f "$cfg" ] || [ -n "${SWG_RV_TOKEN:-}" ] || die "no bare-metal node found ($cfg missing)"   # resuming? recovery state covers a half-torn-down config
  command -v python3 >/dev/null 2>&1 || die "python3 is required to read $cfg"
  # token / panel URL / verify / node endpoint
  read -r NTOK PURL NVERIFY NEP <<EOF
$(python3 - "$cfg" <<'PY'
import json,sys
try: c=json.load(open(sys.argv[1]))   # on a RESUME the bare config is already gone → recovery state fills these in
except Exception: c={}
p=c.get("panel") or {}
print(p.get("token","-"), p.get("url","-"), "yes" if p.get("verify",True) else "no", c.get("endpoint_host","") or "-")
PY
)
EOF
  [ "$NEP" = "-" ] && NEP=""
  [ -n "${SWG_RV_TOKEN:-}" ] && { NTOK="$SWG_RV_TOKEN"; PURL="$SWG_RV_URL"; NEP="$SWG_RV_EP"; NVERIFY="${SWG_RV_VERIFY:-no}"; }   # resume: saved identity wins
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
  [ -n "$ifaces" ] || die "the bare-metal node has no interfaces in $cfg"

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
    mv "$DOCKER_DIR" "$_bak" 2>/dev/null && info "moved a leftover $(b "$DOCKER_DIR") aside → $(b "$_bak") (backup — safe to delete)" || rm -rf "$DOCKER_DIR" 2>/dev/null || true
  fi

  info "Converting the bare-metal node → docker — keeping its token, endpoint and interfaces."
  # signal "converting" to the panel NOW — before the (non-destructive) import below — so the node tile shows
  # it immediately, not after the per-interface import lines. install-docker.sh (exec'd later) emits the terminal.
  LC_URL="$PURL"; LC_TOKEN="$NTOK"; LC_VERIFY="${NVERIFY:-no}"; lc_init convert-docker lc_emit_post
  # interfaces + turn-proxies are migrated in install-docker's NODE STAGE now — migrate_baremetal_ifaces +
  # migrate_baremetal_turns each ask "Transfer? (Y/n)" and copy-first (keys preserved, bare side comes down at the
  # switch). convert.sh no longer pre-stages node items before handing off. Just collect the names for recovery.
  names="$(printf '%s\n' "$ifaces" | while IFS="$(printf '\t')" read -r nm _; do [ -n "$nm" ] && printf '%s ' "$nm"; done || true)"; names="$(echo $names)"
  [ -n "$names" ] || die "the bare-metal node has no interfaces"

  # 3) everything is staged; the BARE NODE IS STILL UP + serving the whole time. Persist the identity (so an
  #    interrupt during the final switch can resume), then hand off — install-docker.sh does the ATOMIC SWITCH:
  #    it tears the bare node down ONLY right before bringing the container up (see SWG_CONVERT_DIR=convert-docker).
  write_recovery "$names"

  # 4) hand off to install-docker.sh (docker node) with the SAME token. It detects the imported confs
  #    (picker shows them as "already on this node"; add more if you want), writes .env and brings the
  #    stack up. Same token ⇒ the panel keeps one node.
  info "Running install-docker.sh (docker node) — adopt $(b "$names") and finish the setup…"
  echo
  lc_handoff   # exec replaces us → install-docker.sh owns the terminal; SWG_CONVERT_DIR makes it emit "converted-docker"
  exec env NODE_TOKEN="$NTOK" PANEL_URL="$PURL" NODE_ENDPOINT="$NEP" TLS_VERIFY="$NVERIFY" SWG_CONVERT_DIR=convert-docker \
       SWG_CONVERT_TURNS="$MIGRATED_TURNS" bash "$SRC/install-docker.sh" node
fi

die "unsupported conversion: $FROM → $TO ($ROLE)"
