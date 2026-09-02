#!/bin/sh
# swg-node entrypoint: bring up one or more userspace AmneziaWG interfaces, then run
# the HTTPS sync daemon. The panel manages peers declaratively; this box only needs
# its own server interface(s). Interfaces come from one of three sources:
#
#   1. mounted confs — every /etc/swg-node/*.conf (or CONF_SRC) is managed as-is
#      (the way to ship full AmneziaWG obfuscation; one file per interface);
#   2. NODE_IFACES spec — "name:port:address[:proto]" entries, comma-separated, each
#      generated (AmneziaWG v2 by default, ":wg" for plain WireGuard);
#   3. single fallback — NODE_IFACE / NODE_LISTEN_PORT / NODE_ADDRESS (back-compat).
#
# Publish each interface's UDP ListenPort in compose for the panel/clients to reach it.
set -eu
log(){ printf '\033[0;36m[swg-node]\033[0m %s\n' "$*"; }
rand32(){ od -An -N4 -tu4 /dev/urandom | tr -d ' '; }   # one unsigned 32-bit int

: "${PANEL_URL:?PANEL_URL required (host-node: https://swg-panel:8443)}"
# systemd's LoadCredential= puts the enrolment token in a per-unit tmpfs and exports its directory
# here. Preferred over NODE_TOKEN when present, because an EnvironmentFile= token stays in this
# process's environment for the life of the daemon and is inherited by every subprocess it spawns —
# a credential is read once and gone. A no-op everywhere else: CREDENTIALS_DIRECTORY is unset in a
# container, so the images and their compose contract are untouched (D15 — this file is shared
# verbatim, and a fork of it would cost a sixth AWG params generator).
if [ -n "${CREDENTIALS_DIRECTORY:-}" ] && [ -r "${CREDENTIALS_DIRECTORY}/token" ]; then
  NODE_TOKEN="$(tr -d '\r\n' < "${CREDENTIALS_DIRECTORY}/token")"
fi
: "${NODE_TOKEN:?NODE_TOKEN required (create the node in the Nodes screen)}"
: "${NODE_ENDPOINT:?NODE_ENDPOINT required (public IP/host clients dial)}"
AWG_DIR=/etc/amnezia/amneziawg
mkdir -p "$AWG_DIR" /var/lib/swg-noded /etc/swg-agent
# A self-learned re-point (operator changed the panel host/port; swg-noded verified the new address presents the
# same trusted cert and switched) is persisted to the state volume — honour it ahead of the .env PANEL_URL so it
# survives a container recreate (which regenerates config.json from the env).
if [ -f /var/lib/swg-noded/panel-url ]; then
  _pu="$(head -n1 /var/lib/swg-noded/panel-url 2>/dev/null | tr -d '[:space:]')"
  if [ -n "$_pu" ] && [ "$_pu" != "$PANEL_URL" ]; then
    log "using self-learned panel URL $_pu (was ${PANEL_URL})"; PANEL_URL="$_pu"
  fi
fi
# ...and the CREDENTIAL and TLS posture that go with it. A same-panel address swap only ever moves the URL,
# which is why this used to be one file. A TRANSFER to a DIFFERENT panel (T-10) moves the token too, and can
# move the posture: without these three, a container recreate — or a nixos-rebuild, which runs this same
# script on the native arm — would restore the OLD panel's token from the environment and the node would 401
# against its new panel for ever, while that panel reported a completed transfer.
if [ -f /var/lib/swg-noded/panel-token ]; then
  _pt="$(head -n1 /var/lib/swg-noded/panel-token 2>/dev/null | tr -d '[:space:]')"
  if [ -n "$_pt" ] && [ "$_pt" != "$NODE_TOKEN" ]; then
    log "using self-learned panel token (transferred to another panel)"; NODE_TOKEN="$_pt"
  fi
fi
if [ -f /var/lib/swg-noded/panel-verify ]; then
  _pv="$(head -n1 /var/lib/swg-noded/panel-verify 2>/dev/null | tr -d '[:space:]')"
  [ -n "$_pv" ] && TLS_VERIFY="$_pv"
fi
if [ -f /var/lib/swg-noded/panel-fp ]; then
  _pf="$(head -n1 /var/lib/swg-noded/panel-fp 2>/dev/null | tr -d '[:space:]')"
  # `[ -n ]`, like panel-verify above. An empty or truncated panel-fp used to blank TLS_FINGERPRINT, and a
  # blank pin does not fail closed — it drops the check entirely and accepts ANY certificate, silently turning
  # a pinned node into an unverified one. Falling back to the configured pin is the safe reading of a file we
  # could not read.
  if [ -n "$_pf" ]; then
    # A learned pin OVERRIDES the configured one so a node that was re-pointed or transferred to another panel
    # keeps working. That is right for an installed node, but on a DECLARATIVE host (NixOS) the operator edits
    # the config, rebuilds, and nothing happens — the learned value quietly wins. Cost a 13h outage to find, so
    # say it out loud rather than change the precedence, which transfer depends on.
    if [ -n "$TLS_FINGERPRINT" ] && [ "$_pf" != "$TLS_FINGERPRINT" ]; then
      # `printf %.16s`, not ${var:0:16}: this file is #!/bin/sh and /bin/sh is dash in the node image, where
    # substring expansion is a fatal "Bad substitution" — it would kill the entrypoint at exactly the moment
    # this warning fires, i.e. a re-pointed node would fail to BOOT instead of logging a line. It was the only
    # such expansion in the file; verified under the image's own dash.
    log "panel pin: using the LEARNED fingerprint $(printf %.16s "$_pf")… (from an earlier re-point/transfer), NOT the configured $(printf %.16s "$TLS_FINGERPRINT")…. To force the configured one, remove /var/lib/swg-noded/panel-fp and restart."
    fi
    TLS_FINGERPRINT="$_pf"
  fi
fi
# First boot seeds the NODE_IFACES bootstrap; after that, ./data/node-confs is the SINGLE source of
# truth — a bootstrap interface deleted from the panel must NOT be regenerated on the next reboot.
BOOT_MARKER=/var/lib/swg-noded/.bootstrapped   # persisted with ./data/node
FIRST_BOOT=no; [ -f "$BOOT_MARKER" ] || FIRST_BOOT=yes
# Per-interface "seeded" list: a NODE_IFACES entry with no conf is created the FIRST time we see it
# (a freshly-added interface on a re-install), but NOT regenerated once seeded (so a panel-deleted one
# stays gone). Replaces the all-or-nothing FIRST_BOOT gate, which skipped interfaces added on re-install.
SEEDED=/var/lib/swg-noded/.seeded-ifaces
if [ ! -f "$SEEDED" ]; then : > "$SEEDED"
  if [ "$FIRST_BOOT" = no ]; then   # legacy node: treat the interfaces it already HAS (confs on disk) as seeded
    for _sc in "$AWG_DIR"/*.conf "${WG_DIR:-/etc/wireguard}"/*.conf; do [ -f "$_sc" ] && basename "$_sc" .conf >> "$SEEDED"; done
  fi
fi
iface_seeded(){ grep -qxF "$1" "$SEEDED" 2>/dev/null; }
mark_seeded(){ iface_seeded "$1" || echo "$1" >> "$SEEDED"; }
MANAGED=""                                  # space-separated interface names
IFJSON=""; IFSEP=""                          # swg-agent interfaces map (built per-interface, with its endpoint)
# A CONVERTED node keeps its plain-WireGuard confs in WG_DIR — that is where bare-metal wrote them, and the
# convert carries them over as-is. Every place that turns an interface NAME into a conf path has to know that,
# or the interface silently drops out of the managed set on the next container start.
iface_conf(){ [ -f "$AWG_DIR/$1.conf" ] && { printf '%s\n' "$AWG_DIR/$1.conf"; return; }; printf '%s\n' "${WG_DIR:-/etc/wireguard}/$1.conf"; }
# WHICH TOOL DRIVES AN INTERFACE — the conf's own answer first, its location only as a fallback. Location is
# not evidence: a container writes EVERY conf to the AmneziaWG directory, so a plain-WireGuard interface that
# has been through one (a convert, a run-model switch) came back up as `awg`, silently changing what it is —
# the panel re-badges it, `wg show` stops reading it, and setting obfuscation on it later would break every
# client. The content cannot be probed either: an AmneziaWG conf with no obfuscation set looks exactly like a
# WireGuard one. So swg-agent writes `#swg:cmd <tool>` when it creates the file.
# ONE derivation, used by everything that needs the answer — the bring-up loop below used to repeat it from
# the directory alone, so a marked plain-WireGuard conf in the AmneziaWG dir was handed to swg-noded as `wg`
# and brought up with `awg-quick`: an amneziawg device that `wg show` cannot read, reported to the panel as
# "cannot read interface" on every reconcile, for ever. The two answers must come from the same place.
iface_cmd(){ # iface_cmd <conf-path> → wg | awg
  _ic="$(sed -n 's/^#swg:cmd \{1,\}\([a-z]\{1,\}\).*/\1/p' "$1" 2>/dev/null | head -1)"
  case "$_ic" in wg|awg) printf '%s\n' "$_ic"; return ;; esac
  case "$1" in "${WG_DIR:-/etc/wireguard}"/*) printf 'wg\n' ;; *) printf 'awg\n' ;; esac
}
add_iface(){ # add_iface <name> <endpoint> [conf]  — record an interface + its own endpoint for the config
  MANAGED="$MANAGED $1"
  _cf="${3:-$(iface_conf "$1")}"
  _cmd="$(iface_cmd "$_cf")"
  _onb=""; grep -q '^#swg:onboarded' "$_cf" 2>/dev/null && _onb=', "onboarded": true'   # add-only adopted iface (keep its peers)
  IFJSON="$IFJSON$IFSEP    \"$1\": { \"cmd\": [\"$_cmd\"], \"conf\": \"$_cf\", \"endpoint_host\": \"${2:-$NODE_ENDPOINT}\"${_onb} }"
  IFSEP=",
"
}

# emit AmneziaWG v2 obfuscation params (H1–H4 ranges, S1–S4, conservative QUIC-Initial I1)
gen_awg_params(){
  s1=$(( 15 + $(rand32) % 136 )); s2=$(( 15 + $(rand32) % 136 ))
  while [ "$s1" -eq "$s2" ] || [ $((s1+56)) -eq "$s2" ]; do s2=$(( 15 + $(rand32) % 136 )); done
  s3=$(( 15 + $(rand32) % 86 )); s4=$(( 15 + $(rand32) % 86 ))
  b1=$(( 5 + $(rand32) % 900000000 ));          b2=$(( 1000000000 + $(rand32) % 900000000 ))
  b3=$(( 2000000000 + $(rand32) % 900000000 )); b4=$(( 3000000000 + $(rand32) % 900000000 ))
  printf 'Jc = 4\nJmin = 40\nJmax = 70\nS1 = %s\nS2 = %s\nS3 = %s\nS4 = %s\nH1 = %s-%s\nH2 = %s-%s\nH3 = %s-%s\nH4 = %s-%s\n' \
    "$s1" "$s2" "$s3" "$s4" "$b1" $((b1+15)) "$b2" $((b2+15)) "$b3" $((b3+15)) "$b4" $((b4+15))
  printf 'I1 = <b 0xc000000001><r 64><t>\nI2 = <r 24><t>\nI3 = <r 32>\nI4 = <b 0xc000000001><r 32><t>\nI5 = <t><r 48>\n'   # I1-I5: QUIC-Initial-shaped junk (0xc0 long header, QUIC v1) + random bytes + timestamp
}

# gen_conf <name> <port> <address> <plain?yes|no>  — generate a server interface conf
gen_conf(){
  _name="$1"; _port="$2"; _addr="$3"; _plain="$4"; _dest="$AWG_DIR/$_name.conf"
  {
    echo "[Interface]"
    echo "PrivateKey = $(awg genkey)"
    echo "Address = $_addr"
    echo "ListenPort = $_port"
    echo "MTU = ${NODE_MTU:-1280}"   # headroom for turn-proxy obfuscation overhead
    [ "$_plain" = yes ] || gen_awg_params
  } > "$_dest"
  chmod 600 "$_dest"
  if [ "$_plain" = yes ]; then log "generated plain-WireGuard interface $_name on :$_port ($_addr)"
  else log "generated AmneziaWG v2 interface $_name on :$_port ($_addr)"; fi
}

# ───────── 1) source the interface set ─────────
if ls /etc/swg-node/*.conf >/dev/null 2>&1 || { [ -n "${CONF_SRC:-}" ] && [ -f "${CONF_SRC:-}" ]; }; then
  for src in /etc/swg-node/*.conf ${CONF_SRC:-}; do
    [ -f "$src" ] || continue
    name="$(basename "$src" .conf)"; dest="$AWG_DIR/$name.conf"
    [ -f "$dest" ] || cp "$src" "$dest"
    chmod 600 "$dest"; add_iface "$name" "$NODE_ENDPOINT"   # mounted confs carry no endpoint → node-level
    log "interface $name from mounted conf ($src)"
  done
elif [ -n "${NODE_IFACES:-}" ]; then
  # spec: name:port:address[:proto[:endpoint]]  (comma-separated). proto "wg" => plain WireGuard;
  # endpoint = the public IP/host clients dial for THIS interface (defaults to NODE_ENDPOINT).
  OIFS="$IFS"; IFS=','
  for entry in $NODE_IFACES; do
    IFS="$OIFS"
    name="$(echo "$entry" | cut -d: -f1)"
    port="$(echo "$entry" | cut -d: -f2)"; port="${port:-51820}"
    addr="$(echo "$entry" | cut -d: -f3)"; addr="${addr:-10.8.0.1/24}"
    proto="$(echo "$entry" | cut -d: -f4)"
    ep="$(echo "$entry" | cut -d: -f5)"; ep="${ep:-$NODE_ENDPOINT}"
    [ -n "$name" ] || { log "skipping malformed NODE_IFACES entry: $entry"; IFS=','; continue; }
    plain=no; [ "$proto" = wg ] && plain=yes
    [ -z "$proto" ] && [ "${NODE_PLAIN_WG:-no}" = yes ] && plain=yes
    if [ -f "$AWG_DIR/$name.conf" ]; then log "interface $name already present ($AWG_DIR/$name.conf)"
    elif ! iface_seeded "$name"; then gen_conf "$name" "$port" "$addr" "$plain"; mark_seeded "$name"   # newly added (first boot or added on re-install)
    else log "interface $name was removed from the panel — not regenerating"; IFS=','; continue; fi
    mark_seeded "$name"; add_iface "$name" "$ep"; IFS=','
  done
  IFS="$OIFS"
elif ls "$AWG_DIR"/*.conf >/dev/null 2>&1; then
  # No mounted confs and no NODE_IFACES spec, but the node already has panel-created confs persisted
  # in AWG_DIR (e.g. kept across an uninstall/reinstall). THOSE are the interface set — handled by the
  # re-manage loop below. Do NOT also invent the default awg0: it would collide on :51820 and show DOWN.
  log "using persisted interface conf(s) — not generating a default bootstrap interface"
elif [ -n "${NODE_IFACE:-}" ]; then
  # single bootstrap interface — ONLY when explicitly named (NODE_IFACE). Blank => zero interfaces (panel-managed).
  name="$NODE_IFACE"
  plain=no; [ "${NODE_PLAIN_WG:-no}" = yes ] && plain=yes
  if [ -f "$AWG_DIR/$name.conf" ]; then log "interface $name already present ($AWG_DIR/$name.conf)"; mark_seeded "$name"; add_iface "$name" "$NODE_ENDPOINT"
  elif ! iface_seeded "$name"; then gen_conf "$name" "${NODE_LISTEN_PORT:-51820}" "${NODE_ADDRESS:-10.8.0.1/24}" "$plain"; mark_seeded "$name"; add_iface "$name" "$NODE_ENDPOINT"
  else log "interface $name was removed from the panel — not regenerating"; fi
else
  log "no bootstrap interface configured — this node is managed from the panel (add one: Interfaces → Load new interface)"
fi

# also re-manage any interfaces created from the panel and persisted in the conf dir (survives a
# container recreate when /etc/amnezia/amneziawg is a mounted volume) — they're not in the bootstrap
# set above. config.json is rebuilt every start, so listing them here is what keeps them after re-up.
for _c in "$AWG_DIR"/*.conf "${WG_DIR:-/etc/wireguard}"/*.conf; do
  [ -f "$_c" ] || continue
  _n="$(basename "$_c" .conf)"
  case " $MANAGED " in *" $_n "*) : ;; *) add_iface "$_n" "$NODE_ENDPOINT" "$_c"; log "interface $_n from persisted conf (panel-created)";; esac
done

[ -n "$MANAGED" ] || log "no interfaces yet — syncing anyway so the node still reports (add one from the panel: Interfaces → Load new interface)"   # do NOT exit: exiting makes the container restart-loop whenever the panel has removed every interface

# ───────── 2) bring each up + NAT its subnet ─────────
# Datapath is decided by the HOST, not by us: awg-quick tries the kernel first and uses it whenever the host
# has the amneziawg module loaded (a NET_ADMIN container creates kernel devices fine — it just can't LOAD the
# module), and falls back to amneziawg-go otherwise. WG_QUICK_USERSPACE_IMPLEMENTATION only names the fallback.
export WG_QUICK_USERSPACE_IMPLEMENTATION=amneziawg-go
WAN="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n1)"; WAN="${WAN:-eth0}"
NATTED=""                                   # subnets already masqueraded (dedupe)

# Clear our OWN leftovers: with host networking our wg/awg devices live in the HOST netns and survive a
# container recreate, where they can still hold one of our ListenPorts (→ "Address already in use").
#
# Only ever delete a device that is actually IN THE WAY. "Not in the managed set" is not the same as "ours":
# it also matches every pre-existing WireGuard/AmneziaWG interface on the box — the ones adoption exists to
# discover and take over — and deleting those destroyed a working setup the first time the container started.
# So: take a device only when it occupies a port one of our managed interfaces is about to bind.
_wants=""                                   # ports our managed confs are going to listen on
for _c in $MANAGED; do
  _p="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]\+\).*/\1/p' "$(iface_conf "$_c")" 2>/dev/null | head -n1)"
  [ -n "$_p" ] && _wants="${_wants:+$_wants }$_p"     # NO leading space: " $_wants " would then hold a DOUBLE
done                                                  # space, which an empty $_lp matches — deleting everything
for _i in $(ip -o link show 2>/dev/null | sed -n 's/^[0-9]\+: \([^:@]*\).*/\1/p'); do
  case " $MANAGED " in *" $_i "*) continue ;; esac
  ip -d link show "$_i" 2>/dev/null | grep -qE 'amneziawg|wireguard' || continue
  _lp="$( { awg show "$_i" dump 2>/dev/null || wg show "$_i" dump 2>/dev/null; } | head -n1 | cut -f3 )"
  # A USERSPACE interface (wireguard-go, amneziawg-go, every WDTT server) answers over its UAPI socket in
  # /var/run/wireguard, which is not mounted into this container — so we read nothing. Unknown port means we
  # cannot claim it is in our way, and this is the exact class of interface adoption exists to take over.
  if [ -z "$_lp" ]; then
    log "leaving unmanaged interface $_i alone (couldn't read its listen port — likely userspace)"
    continue
  fi
  case " $_wants " in
    *" $_lp "*) log "removing stale interface $_i — it holds port $_lp, which a managed interface needs"
                ip link delete "$_i" 2>/dev/null || true ;;
    *)          log "leaving unmanaged interface $_i alone (adoption candidate)" ;;
  esac
done

for IFACE in $MANAGED; do
  dest="$(iface_conf "$IFACE")"
  # A plain-WireGuard conf is brought up with wg-quick; awg-quick would look for it under ITS OWN dir and fail
  # ("does not exist"), leaving an interface listed as managed but down. Pass the PATH, not the name, so
  # neither tool re-resolves it against the wrong directory. Which tool: the SAME answer add_iface wrote into
  # config.json — see iface_cmd.
  _q="$(iface_cmd "$dest")-quick"
  log "bringing up $IFACE via $_q"
  # clear any leftover SAME-NAMED device first (host netns survives a container stop → plain `up` = "File exists").
  $_q down "$dest" 2>/dev/null || ip link del "$IFACE" 2>/dev/null || true
  # one interface failing (e.g. a port still held by something) must NOT crash-loop the whole node — log
  # it and keep going so the rest + swg-noded still come up and the panel can see the node + the gap.
  $_q up "$dest" || { log "WARNING: $_q up $IFACE failed (port in use / NET_ADMIN?) — skipping it"; continue; }
  addr_line="$(awk -F= 'tolower($1) ~ /^[[:space:]]*address[[:space:]]*$/ {print $2; exit}' "$dest" | tr -d ' ' | cut -d, -f1)"
  SUBNET="$(python3 -c "import ipaddress,sys;print(ipaddress.ip_network(sys.argv[1],strict=False))" "$addr_line" 2>/dev/null || echo "")"
  [ -n "$SUBNET" ] || { log "WARNING: could not read subnet for $IFACE — skipping its NAT"; continue; }
  case " $NATTED " in *" $SUBNET "*) : ;; *)
    if iptables -t nat -C POSTROUTING -s "$SUBNET" -o "$WAN" -j MASQUERADE 2>/dev/null; then :; else
      iptables -t nat -A POSTROUTING -s "$SUBNET" -o "$WAN" -j MASQUERADE \
        && log "NAT: masquerading $SUBNET out $WAN ($IFACE)" \
        || log "WARNING: could not add MASQUERADE for $SUBNET (need NET_ADMIN) — clients may have no internet"
    fi
    NATTED="$NATTED $SUBNET" ;;
  esac
done

# ───────── 3) swg-agent config: declarative HTTPS sync, all interfaces listed (with per-interface endpoints) ─────────
VERIFY=false; [ "${TLS_VERIFY:-yes}" = yes ] && VERIFY=true
FP=""; [ -n "${TLS_FINGERPRINT:-}" ] && FP=",
    \"fingerprint\": \"${TLS_FINGERPRINT}\""
cat > /etc/swg-agent/config.json <<JSON
{
  "interfaces": {
$IFJSON
  },
  "endpoint_host": "${NODE_ENDPOINT}",
  "dns": ["${DNS:-1.1.1.1}"],
  "panel": {
    "url": "${PANEL_URL}",
    "token": "${NODE_TOKEN}",
    "verify": ${VERIFY}${FP}
  },
  "node": { "interval": ${INTERVAL:-5}, "agent": "${SWG_AGENT_BIN:-/opt/swg-agent/swg-agent}", "sudo": false }
}
JSON
chmod 600 /etc/swg-agent/config.json

# mark bootstrap done — from now on ./data/node-confs is the source of truth (deletes stick across reboots)
touch "$BOOT_MARKER" 2>/dev/null || true

# ───────── 4) sync loop: sample interfaces -> POST snapshot -> reconcile desired peers ─────────
log "syncing to ${PANEL_URL} (interfaces:${MANAGED}, endpoint ${NODE_ENDPOINT})"
export SWG_AGENT_CONFIG=/etc/swg-agent/config.json SWG_NODED_STATE=/var/lib/swg-noded
# The two overrides above and here are what let this same script bootstrap a node whose programs
# live somewhere other than /opt — a Nix store path, say. Defaults unchanged, so every existing
# container behaves exactly as before. This script is the node's bootstrap on BOTH delivery
# methods: it generates config.json, brings up every persisted interface before the daemon starts,
# and sets up NAT — which is also the answer to "what brings interfaces up at boot on a host where
# `systemctl enable` cannot work".
exec "${SWG_NODED_BIN:-/opt/swg-noded/swg-noded}"
