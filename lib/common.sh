# swg-panel — shared installer helpers (sourced by install-host/node/docker.sh + convert.sh).
# Pure, stateless helpers that were byte-identical across the installers. Functions that depend on
# per-script state (port_free, v_host/v_port, have) are CALLED here but defined by the sourcing script,
# so behaviour is unchanged. Keep only provably-identical helpers here; don't add drifted ones.
#
# NB: this file is sourced, not executed — no shebang, no `set`, no side effects at load time.

# ── validators ──
v_iface(){   case "$1" in ""|*[!a-zA-Z0-9_-]*) return 1;; esac; [ "${#1}" -le 15 ]; }
v_subnet(){  have python3 || return 0; python3 -c "import ipaddress,sys;ipaddress.ip_network(sys.argv[1],strict=False)" "$1" >/dev/null 2>&1; }
v_hostport(){ case "$1" in *:*) v_host "${1%%:*}" && v_port "${1##*:}";; *) return 1;; esac; }

# ── ports ──
next_free_port(){ local p="${1:-51820}"; while [ "$p" -le 65535 ] && ! port_free "$p"; do p=$((p+1)); done; echo "$p"; }

# ── turn-proxy: the 6 forks + their owner/repo, and the binary download (GitHub direct, then opt-in mirrors) ──
turn_repo_owner(){ case "$1" in
  WINGS-N) echo "WINGS-N/vk-turn-proxy";; samosvalishe) echo "samosvalishe/vk-turn-proxy";;
  kiper292) echo "kiper292/vk-turn-proxy";; anton48) echo "anton48/vk-turn-proxy";;
  Moroka8) echo "Moroka8/vk-turn-proxy";;
  cacggghp) echo "cacggghp/vk-turn-proxy";; *) return 1;; esac; }
dl_turn_bin(){ local owner="$1" arch="$2" out="$3" base url m; base="https://github.com/$owner/releases/latest/download/server-linux-$arch"
  for url in "$base" $(for m in ${SWG_TURN_MIRROR:-}; do printf '%s ' "${m%/}/$base"; done); do
    curl -fsSL --connect-timeout 20 --max-time 240 --retry 3 --retry-delay 3 --retry-all-errors "$url" -o "$out" && return 0
  done; return 1; }
