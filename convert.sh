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

cyn(){ local a; printf '  %s (Y/n): ' "$1"; read -r a </dev/tty 2>/dev/null || a=y; case "$a" in [Nn]*) return 1;; *) return 0;; esac; }

# tell the panel this node is about to go down for a conversion, so the UI shows it (best-effort)
signal_status(){
  [ -n "${NTOK:-}" ] && [ -n "${PURL:-}" ] || return 0
  local ins=""; [ "${NVERIFY:-no}" = yes ] || ins="-k"
  curl -fsS $ins --max-time 8 -X POST -H "Authorization: Bearer $NTOK" -H "Content-Type: application/json" \
    --data "{\"state\":\"$1\"}" "${PURL%/}/api/node/proc-status" >/dev/null 2>&1 || true
}
# if the convert aborts (error / Ctrl-C) AFTER we told the panel "converting…" but BEFORE the installer handoff,
# clear that marker so the node's real (down/stale) status shows instead of a stuck "converting…".
CONVERT_SIGNALED=""; CONVERT_HANDOFF=""; _convert_aborted=""
_convert_abort(){ local rc=$?                       # MUST preserve the exit status: an EXIT trap's last command
  [ -n "$_convert_aborted" ] && return $rc; _convert_aborted=1   # would otherwise become the script's exit code (broke convert.sh --check)
  [ -n "$CONVERT_SIGNALED" ] && [ -z "$CONVERT_HANDOFF" ] && signal_status ""
  return $rc; }
trap _convert_abort EXIT INT TERM

# download the turn-proxy server binary: GitHub direct first, then any SWG_TURN_MIRROR proxy prefix(es). Opt-in
# (off by default) — a proxy serving a binary you execute is a supply-chain trust decision. dl_turn_bin <owner> <arch> <out>
dl_turn_bin(){ local owner="$1" arch="$2" out="$3" base url m; base="https://github.com/$owner/releases/latest/download/server-linux-$arch"
  for url in "$base" $(for m in ${SWG_TURN_MIRROR:-}; do printf '%s ' "${m%/}/$base"; done); do
    curl -fsSL --connect-timeout 20 --max-time 240 --retry 3 --retry-delay 3 --retry-all-errors "$url" -o "$out" && return 0
  done; return 1; }
# install a HOST systemd turn-proxy (docker→bare): svc owner listen connect params
turn_install_host(){
  local svc="$1" owner="$2" lis="$3" con="$4" params="$5" inst dir bin arch url
  local ok=1 ver
  inst="${svc#vk-turn-proxy-}"; dir="/opt/vk-turn-proxy/$inst"; bin="$dir/server"
  case "$(uname -m)" in aarch64|arm64) arch=arm64;; *) arch=amd64;; esac
  url="https://github.com/$owner/releases/latest/download/server-linux-$arch"
  mkdir -p "$dir"
  info "  migrating $(b "$svc") — downloading $owner from GitHub (up to ~2 min)…"
  dl_turn_bin "$owner" "$arch" "$bin" && chmod +x "$bin" || ok=0
  # remember the proxy's settings so it survives a failed download: repo.txt (reinstall owner), version, turn.env, the unit.
  printf '%s\n' "$owner" > "$dir/repo.txt"; chmod 644 "$dir/repo.txt" 2>/dev/null || true
  ver=unknown; [ "$ok" = 1 ] && ver="$(curl -fsS -o /dev/null -w '%{redirect_url}' --connect-timeout 15 --max-time 30 "$url" 2>/dev/null | sed -nE 's#.*/releases/download/([^/]+)/.*#\1#p')"
  printf '%s\n' "${ver:-unknown}" > "$dir/version.txt"; chmod 644 "$dir/version.txt" 2>/dev/null || true
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
  echo; info "Turn-proxies on the docker node:"
  while IFS="$(printf '\t')" read -r svc owner lis con params; do [ -n "$svc" ] && printf '    %s  %s → %s\n' "$(b "$svc")" "$lis" "$con"; done <<EOF
$list
EOF
  cyn "Transfer these turn-proxies to bare-metal (host systemd)?" || { info "  left them on docker (they stop when the swg-turn containers go)"; return 0; }
  while IFS="$(printf '\t')" read -r svc owner lis con params; do
    [ -n "$svc" ] || continue
    [ -n "$owner" ] || { warn "  $svc: no fork in the record — skipping"; continue; }
    docker rm -f "swg-turn-${svc#vk-turn-proxy-}" >/dev/null 2>&1 || true   # free the listen port BEFORE the host unit binds it
    if turn_install_host "$svc" "$owner" "$lis" "$con" "$params"; then
      info "  migrated $(b "$svc") → host systemd"
    else
      warn "  $svc: binary download failed — its unit + settings were kept, so it shows on the panel as failed; open it and press Reinstall (no re-entry needed)"
    fi
  done <<EOF
$list
EOF
}

# host systemd turn units → docker record, then tear the units down (swg-noded recreates them as containers)
turn_to_docker(){
  local units u svc exe lis con params owner envf rec="$DOCKER_DIR/data/node/turn-proxy.json"
  command -v python3 >/dev/null 2>&1 || return 0
  units="$(ls /etc/systemd/system/vk-turn-proxy-*.service 2>/dev/null || true)"
  [ -n "$units" ] || return 0
  echo; info "Turn-proxy services on this box:"
  for u in $units; do printf '    %s\n' "$(b "$(basename "$u" .service)")"; done
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
    systemctl disable --now "$svc" 2>/dev/null || true; rm -f "$u"
    info "  migrated $(b "$svc") → docker record (recreated as a container on the node's first run)"
  done
  systemctl daemon-reload 2>/dev/null || true
}

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
  [ -n "$specs" ] || die "no interfaces found (looked in $confd and the docker node's .env)"

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
  signal_status converting-bare; CONVERT_SIGNALED=1     # tell the panel before the datapath goes down
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
    mkdir -p "$(dirname "$dest")"; import_bare_conf "$src" "$dest"   # adds host NAT (docker confs have none)
    info "imported $(b "$nm") → $dest (host NAT added)"
    names="${names:+$names }$nm"
  done
  [ -n "$names" ] || die "no interface confs copied (looked in $confd)"

  # carry the per-interface keypair backups across so the server-key revert baseline survives the move
  if [ -d "$DOCKER_DIR/data/node/iface-keys" ]; then
    mkdir -p /var/lib/swg-noded/iface-keys
    cp -a "$DOCKER_DIR/data/node/iface-keys/." /var/lib/swg-noded/iface-keys/ 2>/dev/null || true
    info "carried interface keypair backups → /var/lib/swg-noded/iface-keys"
  fi

  turn_to_bare   # offer to migrate the docker node's turn-proxies → host systemd units

  # the docker node's data is fully migrated out now (confs imported, keys + turn-proxies carried). Move its
  # dir aside (timestamped backup) so a later bare→docker convert isn't blocked by the leftover .env — the
  # bare-metal install below works off the imported confs + ADOPTED_IFACES, not $DOCKER_DIR.
  if [ -d "$DOCKER_DIR" ]; then
    _bak="$DOCKER_DIR.converted-$(date +%Y%m%d-%H%M%S)"
    if mv "$DOCKER_DIR" "$_bak" 2>/dev/null; then info "moved the old docker dir aside → $(b "$_bak") (backup — safe to delete)"
    else warn "couldn't move $DOCKER_DIR aside — remove it manually before converting back to docker"; fi
  fi

  # 3) hand off to install-node.sh with the SAME token. ADOPTED_IFACES marks the migrated interfaces
  #    as "already on this node" (not orphan / not docker); its picker lets you add more (queued +
  #    created after the tools install). Same token ⇒ the panel keeps one node.
  info "Running install-node.sh — adopt $(b "$names") (and add more if you want), then it wires the daemon…"
  echo
  CONVERT_HANDOFF=1   # installer takes over the "converting…" marker (its swg-noded clears it once the bare node reports)
  exec env NODE_TOKEN="$NTOK" PANEL_URL="$PURL" ENDPOINT_IP="$NEP" ADOPTED_IFACES="$names" \
       SWG_CONVERT=1 TLS_VERIFY="$NVERIFY" bash "$SRC/install-node.sh"
fi

# ── NODE: bare-metal → docker ──
if [ "$FROM" = baremetal ] && [ "$TO" = docker ]; then
  cfg=/etc/swg-agent/config.json
  [ -f "$cfg" ] || die "no bare-metal node found ($cfg missing)"
  command -v python3 >/dev/null 2>&1 || die "python3 is required to read $cfg"
  # token / panel URL / verify / node endpoint
  read -r NTOK PURL NVERIFY NEP <<EOF
$(python3 - "$cfg" <<'PY'
import json,sys
c=json.load(open(sys.argv[1])); p=c.get("panel") or {}
print(p.get("token","-"), p.get("url","-"), "yes" if p.get("verify",True) else "no", c.get("endpoint_host","") or "-")
PY
)
EOF
  [ "$NEP" = "-" ] && NEP=""
  [ -n "$NTOK" ] && [ "$NTOK" != "-" ] && [ "$PURL" != "-" ] || die "couldn't read the node token / panel URL from $cfg"
  # interface  name<TAB>conf-path  lines
  ifaces="$(python3 - "$cfg" <<'PY'
import json,sys
c=json.load(open(sys.argv[1]))
for n,ic in (c.get("interfaces") or {}).items():
    if (ic.get("conf") or ""): print(n+"\t"+ic["conf"])
PY
)"
  [ -n "$ifaces" ] || die "the bare-metal node has no interfaces in $cfg"

  # pre-flight: an existing docker node deployment would be clobbered
  if [ "$CHECK" = yes ]; then
    if [ -f "$DOCKER_DIR/.env" ] || { command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-node; }; then
      warn "a docker node already exists here ($DOCKER_DIR) — remove it first, or pick 'keep and re-install'."; exit 1
    fi
    info "pre-flight OK — interfaces to migrate: $(b "$(printf '%s\n' "$ifaces" | cut -f1 | tr '\n' ' ')")"
    echo; exit 0
  fi
  if [ -f "$DOCKER_DIR/.env" ]; then die "a docker deployment already exists at $DOCKER_DIR — remove it first (run with --check)"; fi

  info "Converting the bare-metal node → docker — keeping its token, endpoint and interfaces."
  # 1) inject each interface's conf into the docker node's conf dir, stripping the host NAT hooks
  #    (the swg-node container does its own NAT). The private key is preserved, so the panel keeps
  #    the same node and peers keep working. The container uses a present conf as-is (no re-gen).
  confd="$DOCKER_DIR/data/node-confs"; mkdir -p "$confd"
  names=""
  while IFS="$(printf '\t')" read -r nm src; do
    [ -n "$nm" ] || continue
    [ -f "$src" ] || { warn "missing $src — skipping interface '$nm'"; continue; }
    grep -viE '^[[:space:]]*Post(Up|Down)[[:space:]]*=' "$src" > "$confd/$nm.conf"; chmod 600 "$confd/$nm.conf"
    info "imported $(b "$nm") → $confd/$nm.conf (key preserved)"
    names="${names:+$names }$nm"
  done <<EOF
$ifaces
EOF
  [ -n "$names" ] || die "no interface confs imported"

  # carry the per-interface keypair backups across so the server-key revert baseline survives the move
  if [ -d /var/lib/swg-noded/iface-keys ]; then
    mkdir -p "$DOCKER_DIR/data/node/iface-keys"
    cp -a /var/lib/swg-noded/iface-keys/. "$DOCKER_DIR/data/node/iface-keys/" 2>/dev/null || true
    info "carried interface keypair backups → $DOCKER_DIR/data/node/iface-keys"
  fi

  # 2) tear down the bare-metal datapath — free the wg ports + remove its units/files. NO panel
  #    goodbye (the token is reused, so the panel keeps this node). Turn-proxies are offered for transfer below.
  info "Stopping the bare-metal node…"
  signal_status converting-docker; CONVERT_SIGNALED=1   # tell the panel before the datapath goes down
  systemctl disable --now swg-noded 2>/dev/null || true
  while IFS="$(printf '\t')" read -r nm src; do
    [ -n "$nm" ] || continue
    awg-quick down "$nm" 2>/dev/null || wg-quick down "$nm" 2>/dev/null || true
    systemctl disable "awg-quick@$nm" 2>/dev/null || true; systemctl disable "wg-quick@$nm" 2>/dev/null || true
    rm -f "/etc/amnezia/amneziawg/$nm.conf" "/etc/wireguard/$nm.conf"
  done <<EOF
$ifaces
EOF
  rm -f /etc/systemd/system/swg-noded.service; systemctl daemon-reload 2>/dev/null || true
  rm -rf /opt/swg-noded /opt/swg-agent /etc/swg-agent /var/lib/swg-noded /etc/sudoers.d/swg-agent

  turn_to_docker   # offer to migrate this box's host turn-proxies → the docker node's record (→ containers)

  # 3) hand off to install-docker.sh (docker node) with the SAME token. It detects the imported confs
  #    (picker shows them as "already on this node"; add more if you want), writes .env and brings the
  #    stack up. Same token ⇒ the panel keeps one node.
  info "Running install-docker.sh (docker node) — adopt $(b "$names") and finish the setup…"
  echo
  CONVERT_HANDOFF=1   # installer takes over the "converting…" marker (its node clears it once the docker node reports)
  exec env NODE_TOKEN="$NTOK" PANEL_URL="$PURL" NODE_ENDPOINT="$NEP" TLS_VERIFY="$NVERIFY" \
       bash "$SRC/install-docker.sh" node
fi

die "unsupported conversion: $FROM → $TO ($ROLE)"
