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
iface_row(){ local n="$1" proto="$2" conf="$3" ep="$4" lp addr
  lp="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$conf" 2>/dev/null | head -1)"
  addr="$(sed -n 's/^[[:space:]]*Address[[:space:]]*=[[:space:]]*\([0-9./]*\).*/\1/p' "$conf" 2>/dev/null | head -1)"
  printf '    %s%s%s  %-4s  %s:%s  %s\n' "$C_GREEN" "$(printf '%-10s' "$n")" "$RESET" "$proto" "${ep:-?}" "${lp:-?}" "${addr:-?}"; }
# the interface a turn-proxy forwards to: the iface whose ListenPort matches the connect port (else empty)
fwd_iface_for(){ local cp="${1##*:}" f lp; for f in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf "$DOCKER_DIR/data/node-confs/"*.conf; do [ -f "$f" ] || continue; lp="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$f" | head -1)"; [ -n "$lp" ] && [ "$lp" = "$cp" ] && { basename "$f" .conf; return; }; done; }
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
  systemctl enable --now "$svc" 2>/dev/null || true   # without the binary the unit just stays down (panel shows it, Reinstall re-fetches)
  rm -f "$mk" 2>/dev/null || true   # done → the node reports the real unit now (up, or down if the download failed)
  [ "$ok" = 1 ]
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
  echo; info "Turn-proxy services to migrate:"; echo
  while IFS="$(printf '\t')" read -r svc owner lis con params; do [ -n "$svc" ] && turn_row "$svc" "$lis" "$con"; done <<EOF
$list
EOF
  echo
  cyn "Transfer these turn-proxies to bare-metal (host systemd)?" || { info "  left them on docker (they stop when the swg-turn containers go)"; return 0; }
  while IFS="$(printf '\t')" read -r svc owner lis con params; do
    [ -n "$svc" ] || continue
    [ -n "$owner" ] || { warn "  $svc: no fork in the record — skipping"; continue; }
    docker rm -f "swg-turn-${svc#vk-turn-proxy-}" >/dev/null 2>&1 || true   # free the listen port BEFORE the host unit binds it
    if turn_install_host "$svc" "$owner" "$lis" "$con" "$params"; then
      sub "migrated $(b "$svc") → host systemd"; MIGRATED_TURNS="${MIGRATED_TURNS:+$MIGRATED_TURNS }$svc"
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
  echo; echo "  Manage    peers + per-interface egress in the panel → $(b 'Interfaces / Nodes')"
  echo "  Edit      interfaces in $(b /etc/amnezia/amneziawg/) / $(b /etc/wireguard/)  ·  daemon $(b /etc/swg-agent/config.json)"
  echo "  Logs      $(b 'journalctl -u swg-noded -f')  ·  the node turns green in ~5s"
}
# a LIVE docker node = an actual swg-node container (running or stopped). A bare $DOCKER_DIR with no
# container is just a stale leftover (e.g. a previous convert that didn't finish moving it aside).
docker_node_present(){ command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-node; }

# ── Panel/host conversion isn't automated yet → non-zero so the caller loops back to keep/abort ──
case "$ROLE" in host|master)
  warn "Converting the PANEL between docker and bare-metal isn't automated yet (only nodes are)."
  echo  "  Choose 'keep and re-install', or uninstall the existing panel first and install the other method." >&2
  exit 1;;
esac

# ── NODE: docker → bare-metal ──
if [ "$FROM" = docker ] && [ "$TO" = baremetal ]; then
  envf="$DOCKER_DIR/.env"; confd="$DOCKER_DIR/data/node-confs"
  [ -f "$envf" ] || [ -n "${SWG_RV_TOKEN:-}" ] || die "no docker node settings found at $envf"   # resuming? the saved identity covers a half-torn-down .env
  getv(){ sed -n "s/^$1=//p" "$envf" 2>/dev/null | head -1 | sed 's/^"//; s/"$//'; }
  NTOK="$(getv NODE_TOKEN)"; PURL="$(getv PANEL_URL)"; NEP="$(getv NODE_ENDPOINT)"
  NIFS="$(getv NODE_IFACES)"; NIF="$(getv NODE_IFACE)"; NPLAIN="$(getv NODE_PLAIN_WG)"; NVERIFY="$(getv TLS_VERIFY)"
  [ -n "${SWG_RV_TOKEN:-}" ] && { NTOK="$SWG_RV_TOKEN"; PURL="$SWG_RV_URL"; NEP="$SWG_RV_EP"; NVERIFY="${SWG_RV_VERIFY:-no}"; }   # resume: saved identity wins
  [ "$NVERIFY" = yes ] || NVERIFY=no
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
    # show "converting" on the panel NOW — the pre-flight runs the instant [c] is chosen, before the "proceed?"
    # prompt. The real convert (lc_init) re-affirms it + owns the terminal; declining at the prompt leaves it
    # to time out → failed (the designed fallback).
    [ -n "$NTOK" ] && [ -n "$PURL" ] && { LC_URL="$PURL"; LC_TOKEN="$NTOK"; LC_VERIFY="${NVERIFY:-no}"; LC_EMIT=lc_emit_post; lc_emit converting-bare; }
    info "Interfaces to migrate:"; echo
    for s in $specs; do iface_row "${s%:*}" "${s#*:}" "$confd/${s%:*}.conf" "$NEP"; done
    echo
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

  # 3) bring the node UP FIRST — hand wg/awg + the daemon to install-node.sh so it's reporting in seconds;
  #    only THEN migrate the turn-proxies (their binary downloads are slow and must not hold the node back).
  #    ADOPTED_IFACES marks the migrated interfaces as "already on this node"; same token ⇒ one panel node.
  #    NB: NOT exec — we return to migrate turn-proxies + tidy up once the node is live.
  info "Running install-node.sh — adopt $(b "$names") (and add more if you want), then it wires the daemon…"
  echo
  # NB: '|| warn' — a non-zero exit (e.g. one interface failed to come up) must NOT abort the convert under
  # set -e, or the turn-proxy migration + dir cleanup below would be skipped (the node would lose its proxies).
  env NODE_TOKEN="$NTOK" PANEL_URL="$PURL" ENDPOINT_IP="$NEP" ADOPTED_IFACES="$names" \
      SWG_CONVERT=1 TLS_VERIFY="$NVERIFY" bash "$SRC/install-node.sh" \
    || warn "install-node.sh reported an error — continuing with the turn-proxy migration (check the interface(s) on the panel)."

  echo; info "Node is up — migrating its turn-proxies now (downloads can be slow; the node already serves peers)."
  turn_to_bare   # docker turn-proxies → host systemd units (reads the still-present $DOCKER_DIR turn record)

  # offer the SAME "add more?" step interfaces got — re-enter install-node.sh's turn menu now that the
  # existing proxies are migrated and listed (it also (re)writes the bare turn record incl. the migrated
  # units). Non-fatal: a failure here must not skip the dir cleanup + final summary below.
  env SWG_TURN_ADD=1 bash "$SRC/install-node.sh" \
    || warn "turn-proxy add step reported an error — continuing (check the panel)."

  # finally move the old docker dir aside (turn_to_bare needed its turn record) so a later bare→docker
  # convert isn't blocked by the leftover .env.
  if [ -d "$DOCKER_DIR" ]; then
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
    [ -n "$NTOK" ] && [ "$NTOK" != "-" ] && [ -n "$PURL" ] && { LC_URL="$PURL"; LC_TOKEN="$NTOK"; LC_VERIFY="${NVERIFY:-no}"; LC_EMIT=lc_emit_post; lc_emit converting-docker; }   # show "converting" on the panel the moment [c] is chosen
    info "Interfaces to migrate:"; echo
    printf '%s\n' "$ifaces" | while IFS="$(printf '\t')" read -r _n _cf; do [ -n "$_n" ] || continue
      _pr=awg; case "$_cf" in */wireguard/*) _pr=wg;; esac; iface_row "$_n" "$_pr" "$_cf" "$NEP"; done
    echo; exit 0
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
  # 1) inject each interface's conf into the docker node's conf dir, stripping the host NAT hooks
  #    (the swg-node container does its own NAT). The private key is preserved, so the panel keeps
  #    the same node and peers keep working. The container uses a present conf as-is (no re-gen).
  confd="$DOCKER_DIR/data/node-confs"; mkdir -p "$confd"
  names=""
  while IFS="$(printf '\t')" read -r nm src; do
    [ -n "$nm" ] || continue
    if [ -f "$confd/$nm.conf" ]; then sub "kept $(b "$nm") → $confd/$nm.conf (already imported)"; names="${names:+$names }$nm"; continue; fi   # resume
    [ -f "$src" ] || { warn "missing $src — skipping interface '$nm'"; continue; }
    grep -viE '^[[:space:]]*Post(Up|Down)[[:space:]]*=' "$src" > "$confd/$nm.conf"; chmod 600 "$confd/$nm.conf"
    sub "imported $(b "$nm") → $confd/$nm.conf (key preserved)"
    names="${names:+$names }$nm"
  done <<EOF
$ifaces
EOF
  [ -n "$names" ] || die "no interface confs imported"

  # carry the per-interface keypair backups across so the server-key revert baseline survives the move
  if [ -d /var/lib/swg-noded/iface-keys ]; then
    mkdir -p "$DOCKER_DIR/data/node/iface-keys"
    cp -a /var/lib/swg-noded/iface-keys/. "$DOCKER_DIR/data/node/iface-keys/" 2>/dev/null || true
    sub "carried interface keypair backups → $DOCKER_DIR/data/node/iface-keys"
  fi

  # 2) COPY-FIRST: stage the turn-proxies into the docker record too (interactive) while the bare node is
  #    STILL UP — so an abort/failure here leaves the node fully intact (no recovery needed; just re-run).
  turn_to_docker   # migrate this box's host turn-proxies → the docker node's record (→ containers)

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
