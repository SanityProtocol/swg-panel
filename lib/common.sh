# swg-panel — shared installer helpers (sourced by install-host/node/docker.sh + convert.sh).
# Pure, stateless helpers that were byte-identical across the installers. Functions that depend on
# per-script state (port_free, v_host/v_port, have) are CALLED here but defined by the sourcing script,
# so behaviour is unchanged. Keep only provably-identical helpers here; don't add drifted ones.
#
# NB: this file is sourced, not executed — no shebang, no `set`, no side effects at load time.

# Web assets swg-sub serves (its STATIC allow-list, minus vendor/qrcode.js which every site copies separately).
# ONE list, shared by every installer/updater copy site — the four images were allow-listed by the server but
# absent from all four copy loops, so `_a/import-hint.png` (and the client logos) 404'd on every install since
# they were added. Keep this in sync with STATIC in swg-sub; nothing else needs touching when an asset is added.
SUB_WEB="sub.html sub.js sub.css turn-artifacts.js"

# ── these installers must REFUSE on a declaratively managed host ────────────────────────────────
# WHY: on NixOS `bootstrap.sh` APPEARS to work. `/` is writable and `nixos-rebuild` never touches
# /opt, so `mkdir -p /opt/swg-noded && cp` succeeds; the run then fails somewhere later on PATH or a
# package manager, leaving a half-install the host's own tooling cannot see, cannot update and will
# not remove on `nixos-rebuild`. That is strictly worse than failing at the front door, and it is
# the reason this guard exists rather than a nicer error message deeper in.
#
# Two signals, in this order and for different reasons:
#   1. NixOS BY NAME (`/etc/NIXOS`, or `ID=nixos` in os-release) — so the refusal can point at the
#      module the operator should be writing instead of describing a symptom.
#   2. a READ-ONLY `/etc/systemd/system` — the general "something else owns this host's services"
#      case, and the condition that actually breaks these scripts. `[ -w ]` is NOT enough: for root
#      it reports the mode bits and ignores a read-only mount, so probe with a real write. The
#      `( : > f )` SUBSHELL matters — `{ : > f; }` exits the whole script under dash.
#
# uninstall.sh carries its own copy of the write probe on purpose: it does not source this file, and
# its question is narrower ("can I write units at all", asked so a failed `systemctl disable` cannot
# lead to deleting /opt while the services keep running). Keep the two in step by intent, not by
# sharing — that script's guard is about destruction, this one about installation.
#
# ⚠️ This one does NOT lean on the sourcing script's `die`, unlike the rest of this file. Four of the
# five scripts source this file BEFORE they define `die` (measured: install-host 61 vs 99, node 37 vs
# 76, update 59 vs 91, convert 17 vs 34) — so a guard that called it would die with "die: command not
# found" on precisely the host it exists to protect, and nowhere else. It prints and exits itself,
# and uses `die` only when one is already defined.
declarative_host(){                  # 0 = managed declaratively; sets DECLARATIVE_KIND=nixos|declarative
  DECLARATIVE_KIND=""
  # ⚠️ anchored at BOTH ends: '^ID="?nixos"?' alone also matches `ID=nixosaurus`. Caught by the probe,
  # not by reading — a loose match here would refuse to install on a distro that is not NixOS at all.
  if [ -e /etc/NIXOS ] || grep -qsE '^ID="?nixos"?[[:space:]]*$' /etc/os-release; then DECLARATIVE_KIND="nixos"; return 0; fi
  local sd="${SYSTEMD_DIR:-/etc/systemd/system}" p
  [ -d "$sd" ] || return 1
  # ⚠️ THE WRITE PROBE IS ONLY EVIDENCE WHEN WE COULD HAVE WRITTEN. Run as an ordinary user it fails on
  # every box in the world, and this then reported an Ubuntu laptop as "managed declaratively" and told the
  # operator to describe swg-panel in their NixOS configuration — a confident wrong diagnosis, with advice
  # they cannot act on, as the FIRST thing anyone sees who forgets `sudo`. Measured: install-node.sh,
  # update.sh and convert.sh all reach this before their own root check (convert.sh had none at all), while
  # install-docker.sh and uninstall.sh got there first and said "run as root", which is the true answer.
  # The NixOS markers above still decide outright — those are real evidence at any privilege level.
  [ "$(id -u)" = 0 ] || return 1
  p="$sd/.swg-install-probe.$$"
  if ( : > "$p" ) 2>/dev/null; then rm -f "$p"; return 1; fi
  DECLARATIVE_KIND="declarative"; return 0
}
# refuse_on_declarative_host <the whole declaration line to show, e.g. services.swg-node = { … };>
refuse_on_declarative_host(){
  # A dry run renders under ./dryrun/ and executes nothing, so it is useful here rather than harmful
  # — it is how you see what the bare-metal install WOULD lay down, which is worth having on the box
  # you are moving off.
  if ${DRYRUN:-false}; then return 0; fi
  declarative_host || return 0
  # The caller passes the COMPLETE line rather than just an option name: the docker installer can be
  # either module and needs `delivery = "container"` in there, which no template here could add.
  # ⚠️ NOT `${1:-...}` with a default containing braces — `${1:-x}` ends at the first `}`, so the
  # default's own `};` leaked into every message as a trailing `;}`. Caught by running it.
  local opt="${1:-}"
  [ -n "$opt" ] || opt='services.swg-node = { enable = true; ... };'
  if [ "$DECLARATIVE_KIND" = "nixos" ]; then
    _refuse "NixOS detected — this installer must not run here.
    It writes into /opt and /etc/systemd/system, which nixos-rebuild neither manages nor sees: the
    run would look like it worked and leave an install you cannot update or remove.

    Declare the module instead — the panel's Nodes screen prints the whole block beside the token:
        ${opt}
    See nix/README.md. Moving an install that is already on this box? nix/adopt.sh carries it
    over with its identity intact — re-minting a token strips every peer from the interface."
  fi
  _refuse "${SYSTEMD_DIR:-/etc/systemd/system} is read-only — this host's services are managed
    declaratively, so an install written here would not survive its next rebuild. Describe swg-panel
    in that configuration instead (see nix/README.md for the NixOS modules)."
}
_refuse(){
  if command -v die >/dev/null 2>&1; then die "$1"; fi
  printf '\033[31m✗ %s\033[0m\n' "$1" >&2; exit 1
}

# pretty protocol name for interface listings: awg → AmneziaWG, wg → WireGuard (anything else passes through).
# The product's own spelling — the summary's _sum_proto_label already says WireGuard, and one listing said both.
proto_label(){ case "$1" in wg) printf 'WireGuard';; awg) printf 'AmneziaWG';; *) printf '%s' "$1";; esac; }
# nat_hook_up / nat_hook_down <subnet> <wan> — the PostUp / PostDown pair a managed interface's conf carries,
# BYTE FOR BYTE what swg-agent writes (_ipt_set / _ipt_reap there): the up REAPS THEN ADDS, so the chain ends with
# exactly one copy of each rule however many a bring-up without its tear-down left behind (a convert, a killed
# container, a crash); the down reaps every copy. The installers wrote a plain `-A` / one `-D`, so after a Docker →
# bare-metal convert every interface carried two copies of each rule and an uninstall left one behind (1.8.8
# qualification, round 4). tests/nat_hooks_selftest.py holds the two writers to one text.
# The MASQUERADE names its interface (swg-nat:%i — wg-quick puts the name): the untagged text was shared by every
# interface on a subnet, so one's down took another's rule (a node's transfer home: the mesh link re-made on the same
# /31, the old one's down leaving the new one with no NAT on either end). See swg-agent _nat_hooks.
_ipt_reap_sh(){ printf 'for _n in 1 2 3 4 5 6 7 8; do iptables %s-D %s 2>/dev/null || break; done' "${1:+$1 }" "$2"; }
_ipt_set_sh(){ printf '%s; iptables %s-A %s || true' "$(_ipt_reap_sh "$1" "$2")" "${1:+$1 }" "$2"; }
nat_hook_up(){ printf 'sysctl -q -w net.ipv4.ip_forward=1 || true; %s; %s; %s' \
  "$(_ipt_set_sh '-t nat' "POSTROUTING -s $1 -o $2 -m comment --comment swg-nat:%i -j MASQUERADE")" "$(_ipt_set_sh '' "FORWARD -i %i -o $2 -j ACCEPT")" \
  "$(_ipt_set_sh '' "FORWARD -i $2 -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT")"; }
nat_hook_down(){ printf '%s; %s; %s; true' \
  "$(_ipt_reap_sh '-t nat' "POSTROUTING -s $1 -o $2 -m comment --comment swg-nat:%i -j MASQUERADE")" "$(_ipt_reap_sh '' "FORWARD -i %i -o $2 -j ACCEPT")" \
  "$(_ipt_reap_sh '' "FORWARD -i $2 -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT")"; }
# installed_sum <path…> — ONE sha256 over every regular file under the given paths (name + content, sorted), or
# nothing when there are none. A re-install compares it before/after to tell "re-installed" from "re-installed AND
# updated": the version stamp cannot, a dev build keeps one VERSION across many commits. (install-docker.sh compares
# the containers' image ids for the same reason.)
installed_sum(){ local p out
  out="$(for p in "$@"; do [ -e "$p" ] && find "$p" -type f -print0 2>/dev/null; done | sort -z | xargs -0 -r sha256sum 2>/dev/null)" || true
  [ -n "$out" ] || return 0
  printf '%s\n' "$out" | sha256sum | cut -d' ' -f1; }
# local_addrs — every address assigned to this box, one per line (what `ip` lists, plus `hostname -I`). Never fails.
local_addrs(){ { ip -o addr show 2>/dev/null | awk '{print $4}' | cut -d/ -f1; hostname -I 2>/dev/null | tr ' ' '\n'; } \
  | awk 'NF && !s[$0]++' || true; }
# host_is_local <host> — 0 iff <host> IS, or resolves to, an address of this box. Unresolvable ⇒ 1: fail safe, it is
# asked before a value is written somewhere that assumes the box can bind it (see install-host.sh's node record).
host_is_local(){ local h="${1:-}" a l; [ -n "$h" ] || return 1; l="$(local_addrs)"
  for a in "$h" $(getent ahosts "$h" 2>/dev/null | awk '!s[$1]++ {print $1}' || true); do
    grep -qxF -- "$a" <<< "$l" && return 0
  done
  return 1; }

# System (panel-managed inter-node mesh-link) interfaces use a reserved name prefix (default `swg_`); user
# interfaces can never use it (the panel rejects it). These are NOT user interfaces and must never be
# presented/offered in any installer / re-installer / docker / convert / uninstall listing.
# is_sys_iface <name> → 0 if it's a system iface; drop_sys_ifaces filters them from stdin (one name/line).
SWG_SYS_PREFIX="${SWG_SYS_PREFIX:-swg_}"
is_sys_iface(){ case "$1" in "$SWG_SYS_PREFIX"*) return 0;; *) return 1;; esac; }
drop_sys_ifaces(){ grep -v "^[[:space:]]*${SWG_SYS_PREFIX}" || true; }

# bold (b) + bold-blue link (bb) text — print_summary uses both, but convert.sh / update.sh don't define bb
# themselves, so provide them here. The guard only FILLS A GAP: a script that defines its own (identical) b/bb
# keeps it, in any source order. Colours are read at call time, so they need not be set when this file is sourced.
command -v b  >/dev/null 2>&1 || b(){  printf '%s%s%s'   "${BOLD:-}" "$*" "${RESET:-}"; }
command -v bb >/dev/null 2>&1 || bb(){ printf '%s%s%s%s' "${BOLD:-}" "${C_BLUE:-}" "$*" "${RESET:-}"; }
# `have` is used by print_summary's detection (and v_subnet) but is normally a per-script helper — convert.sh
# doesn't define it, so _sum_detect printed "have: command not found" and returned no methods → an empty summary.
command -v have >/dev/null 2>&1 || have(){ command -v "$1" >/dev/null 2>&1; }

# ── THE NODE TOKEN GOES ONLY TO THE PANEL THIS NODE TRUSTS ──────────────────────────────────────────────────────────
# panel_req <METHOD> <url> <verify:yes|no> <fingerprint> [<timeout-s>]   — the token in $SWG_TOK, a JSON body in $SWG_BODY
# EVERY installer / updater / converter / uninstaller call that carries the node token goes through this. The panel's
# certificate is checked ON THE CONNECTION THE TOKEN THEN TRAVELS ON, as swg-noded's post_json does: a fingerprint → the
# handshake's certificate must hash to it (sha256 of its DER) or nothing is sent; verify=yes → CA verification, hostname
# included; neither → unverified, the posture the node itself syncs with (a loopback URL, or an operator's TLS_VERIFY=no).
# ⚠️ `curl -k`, which this replaced (auth_curl), sent the token to WHATEVER answered — for every pinned node, i.e. to the
# very certificate a re-install had just refused as a possible interceptor, and when the post did reach the real panel
# it acted on it ("reinstalling" dropped the node's interface keys): 1.8.8 qualification, round 6. A probe first and a
# send afterwards would not do either — the second connection is not the one that was checked.
# The token and the body stay off the argv (/proc/<pid>/cmdline is world-readable; a process's environment is not).
# Prints the answer's body (2xx), else ONE line saying why not. Exit: 0 = 2xx · 3 = the panel answered with an HTTP error
# ("HTTP <code>") · 2 = the request went out and no answer came back · 4 = the certificate is not the one this node
# trusts — NOTHING was sent · 1 = the panel was not reached ("<reason>"). The whole call is held to <timeout-s> (8).
# ⚠️ TWIN: uninstall.sh and bootstrap.sh carry the same program (neither sources this file); the three are held to one
# text by tests/panel_req_selftest.py, which also runs it against live listeners.
panel_req(){ python3 - "$@" <<'PANELREQ'
import hashlib, http.client, math, os, re, signal, ssl, sys, urllib.parse
a = (sys.argv[1:] + [""] * 5)[:5]
meth, url, verify = a[0] or "GET", a[1], a[2] == "yes"
fp = a[3].strip().replace(":", "").lower()
if fp and not re.fullmatch(r"[0-9a-f]{64}", fp):      # a pin that is not a sha256 is never read as "no pin": fail closed
    print("the pin on record (%s…) is not a sha256 fingerprint — nothing was sent" % fp[:16])
    sys.exit(4)
try:
    tmo = max(1.0, float(a[4]))
except ValueError:
    tmo = 8.0
tok, body = os.environ.get("SWG_TOK", ""), os.environ.get("SWG_BODY", "")
u = urllib.parse.urlparse(url if "://" in url else "https://" + url)
sent, conn = False, None


def late(*_):
    raise TimeoutError("timed out")


signal.signal(signal.SIGALRM, late)
signal.alarm(int(math.ceil(tmo)))
try:
    host, port = u.hostname or "", u.port or (443 if u.scheme == "https" else 80)
    path = (u.path or "/") + ("?" + u.query if u.query else "")
    if u.scheme == "http":
        conn = http.client.HTTPConnection(host, port, timeout=tmo)
    elif u.scheme == "https":
        ctx = ssl.create_default_context() if (verify and not fp) else ssl._create_unverified_context()
        conn = http.client.HTTPSConnection(host, port, timeout=tmo, context=ctx)
    else:
        print("unsupported URL scheme %r" % u.scheme)
        sys.exit(1)
    try:
        conn.connect()                                   # the handshake, and a CA check, before a byte of the request
    except ssl.SSLCertVerificationError as e:
        print("the panel's certificate did not verify (%s) — nothing was sent" % (e.verify_message or e.reason or e))
        sys.exit(4)
    if fp and u.scheme == "https":
        got = hashlib.sha256(conn.sock.getpeercert(True) or b"").hexdigest()
        if got != fp:
            print("the panel presents a certificate other than the pinned one (sha256 %s…, pinned %s…) — nothing was sent"
                  % (got[:16], fp[:16]))
            sys.exit(4)
    hdr = {"Authorization": "Bearer " + tok, "User-Agent": "swg-noded"}
    if body:
        hdr["Content-Type"] = "application/json"
    sent = True
    conn.request(meth, path, body=body.encode() if body else None, headers=hdr)
    r = conn.getresponse()
    try:
        data = r.read()
    except http.client.IncompleteRead as e:
        data = e.partial
    if 200 <= r.status < 300:
        sys.stdout.write(data.decode("utf-8", "replace"))
        sys.exit(0)
    print("HTTP %d" % r.status)
    sys.exit(3)
except Exception as e:
    why = str(getattr(e, "reason", None) or getattr(e, "strerror", None) or e or type(e).__name__)
    print(why[:1].lower() + why[1:])
    sys.exit(2 if sent else 1)
finally:
    signal.alarm(0)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
PANELREQ
}

# Prompt for a SECRET (the node enrollment key) with terminal echo OFF, so it never lands in scrollback / a
# screen recording / a shared session — and an EXISTING value (re-install default) is offered as "[keep current]"
# rather than printed. Same contract + non-interactive short-circuit as the installers' ask_valid: a value already
# in the var (from -key / env) is validated and returned with NO prompt. col()/C_BLUE/die/_pnl come from the
# sourcing script (resolved at call time). Usage: ask_secret <prompt> <default> <var> <validator_fn> <hint>
ask_secret(){ local p="$1" d="$2" var="$3" fn="$4" hint="$5" v rc
  if [ -n "${!var:-}" ]; then "$fn" "${!var}" && return
    warn "ignoring invalid $var (${hint})"; fi
  [ -n "${_SWG_NL:-}" ] || echo; _SWG_NL=""
  while :; do
    # 2>/dev/null BEFORE >/dev/tty (and on the read): redirections apply left to right, so the other order printed a
    # raw "/dev/tty: No such device or address" whenever there was no terminal to open.
    printf '  %s%s: ' "$p" "${d:+ [$(col "${C_BLUE:-}" 'keep current')]}" 2>/dev/null >/dev/tty || printf '  %s: ' "$p"
    if read -rs v 2>/dev/null <"${SWG_TTY:-/dev/tty}"; then rc=0; printf '\n' 2>/dev/null >/dev/tty || echo   # read -s swallows the newline the operator pressed
    else rc=1; v=""   # …and with no terminal the prompt line ended blank (1.8.8 qualification): say what happens instead
      if [ -n "$d" ]; then echo "(no terminal — the saved one is kept)"; else echo "(no terminal — nothing given)"; fi; fi
    v="${v:-$d}"
    if "$fn" "$v"; then printf -v "$var" '%s' "$v"; _pnl; return; fi
    [ "$rc" -ne 0 ] && die "no value for ‘$p’ and no interactive input to re-prompt"
    if declare -F "${fn}_why" >/dev/null 2>&1; then warn "$("${fn}_why" "$v")"; else warn "$hint"; fi   # as ask_valid does
  done; }

# the bordered, bold title every summary opens with — keeps one style across install / re-install / convert /
# update for node / host / master. Pass the operation phrase, e.g. "CONVERSION COMPLETE", "INSTALL COMPLETE".
# Leading blank above, blank below — callers add their final trailing blank with summary_end.
summary_title(){ echo; echo "$(b "──────────────── $1 ────────────────")"; echo; }
# the single trailing blank line every summary must end with (consistency across all scripts).
summary_end(){ echo; }

# node summary footer: "reconfigure in the panel, or directly on the server", with the method's real paths +
# commands. <baremetal|docker> [docker_install_dir]. b()/COMPOSE come from the sourcing script (installers/convert).
node_reconfig_block(){
  local method="$1" dir="${2:-/opt/swg-panel-docker}" prof="${3:-}" C="${COMPOSE:-docker compose}"
  # the stack this box runs: `--profile node` on a master recreated the node only and left the panel on its old .env
  [ -n "$prof" ] || { docker ps --format '{{.Names}}' 2>/dev/null | grep -cx swg-panel >/dev/null && prof=master || prof=node; }
  echo "  Interfaces, turn-proxies, WDTT and csqtt servers can be re-configured in the web panel, or directly on the server:"; echo
  if [ "$method" = docker ]; then
    printf '    %-13s %s\n' "Interfaces"   "$(b "ls $dir/data/node-confs/*.conf")"
    printf '    %-13s %s\n' "Turn-proxies" "$(b 'docker ps --filter name=swg-turn')"
    printf '    %-13s %s\n' "WDTT"         "$(b "cat $dir/data/node/wdtt.json")   (servers + their interfaces)"
    printf '    %-13s %s\n' "csqtt"        "$(b "cat $dir/data/node/csqtt.json")  (servers + their interfaces)"
    echo
    printf '    %-13s %s\n' "Directory"    "$(b "cd $dir")"
    printf '    %-13s %s\n' "Restart"      "$(b "cd $dir && $C restart swg-node")"
    printf '    %-13s %s\n' "Logs"         "$(b "cd $dir && $C logs -f swg-node")"
    printf '    %-13s %s\n' "Config"       "$(b "nano $dir/.env") (after edit run $(b "$C --profile $prof up -d"))"
  else
    printf '    %-13s %s\n' "AmneziaWG"    "$(b 'ls /etc/amnezia/amneziawg/*.conf')"
    printf '    %-13s %s\n' "WireGuard"    "$(b 'ls /etc/wireguard/*.conf')"
    printf '    %-13s %s\n' "Turn-proxies" "$(b 'ls /etc/systemd/system/vk-turn-proxy*.service')"
    printf '    %-13s %s\n' "WDTT"         "$(b 'ls /etc/systemd/system/swg-wdtt-*.service')   (servers + their interfaces)"
    printf '    %-13s %s\n' "csqtt"        "$(b 'ls /etc/systemd/system/swg-csqtt-*.service')  (servers + their interfaces)"
    echo
    printf '    %-13s %s\n' "SWG Agent"    "$(b 'nano /etc/swg-agent/config.json')"
    printf '    %-13s %s\n' "Restart"      "$(b 'systemctl restart swg-noded')"
    printf '    %-13s %s\n' "Logs"         "$(b 'swg-logs noded -f')"
  fi
}

# ── unified per-server summary ────────────────────────────────────────────────
# print_summary <OP> [converted-parts] — ONE summary for ANY operation. Builds up to two blocks from what's
# actually on this box: a HOST block (iff a panel is installed) and a NODE block (iff a local node is installed),
# each tagged with its OWN method + version + an optional "newly converted" note. Only the title (+ that note)
# differ between install / re-install / update / convert; absent blocks are omitted; a blank line separates the
# two when both exist. Self-contained — DETECTS the methods and reads the live config, so every caller is just
# `print_summary <OP> [host|node|both]`.   <OP> ∈ INSTALL | RE-INSTALL | UPDATE | CONVERSION.
_SUM_DDIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"
_sum_get(){ sed -n "s/^$2=//p" "$1" 2>/dev/null | sed -n 1p | sed 's/^"//; s/"$//' || true; }   # || true: pipefail+set -e safe when the file is missing
_sum_proto_label(){ case "$1" in wg|wireguard|WireGuard) echo WireGuard;; *) echo AmneziaWG;; esac; }
_sum_fwd_iface(){ local cp="${1##*:}" f lp; for f in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf "$_SUM_DDIR"/data/node-confs/*.conf; do [ -f "$f" ] || continue; lp="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$f" 2>/dev/null | sed -n 1p)"; [ -n "$lp" ] && [ "$lp" = "$cp" ] && { basename "$f" .conf; return 0; }; done; return 0; }
_sum_iface_row(){ local n="$1" proto="$2" conf="$3" ep="$4" lp addr
  lp="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p' "$conf" 2>/dev/null | sed -n 1p || true)"
  addr="$(sed -n 's/^[[:space:]]*Address[[:space:]]*=[[:space:]]*\([0-9./]*\).*/\1/p' "$conf" 2>/dev/null | sed -n 1p || true)"
  printf '    %s%s%s  %s%-10s%s  %s:%s  %s\n' "${C_GREEN:-}" "$(printf '%-10s' "$n")" "${RESET:-}" "${BOLD:-}" "$(_sum_proto_label "$proto")" "${RESET:-}" "${ep:-?}" "${lp:-?}" "${addr:-?}"; }
_sum_turn_row(){ local fw; fw="$(_sum_fwd_iface "${3:-}")"; printf '    %s%s%s %s → %s%s\n' "${C_GREEN:-}" "$1" "${RESET:-}" "${2:-?}" "${3:-?}" "${fw:+ ($fw)}"; }
_sum_node_ep(){ local ep; ep="$(python3 -c 'import json;print((json.load(open("/etc/swg-agent/config.json")).get("endpoint_host") or ""))' 2>/dev/null || true)"; [ -n "$ep" ] || ep="$(_sum_get "$_SUM_DDIR/.env" NODE_ENDPOINT)"; [ -n "$ep" ] || ep="$(detect_public_ip 2>/dev/null || true)"; printf '%s' "$ep"; }
# the host:port the NODE actually dials for the panel — its agent's panel.url (127.0.0.1:443 for a local node,
# the public URL for a remote one). Distinct from the panel's own public URL.
_sum_node_purl(){ local u; u="$(python3 -c 'import json;print((json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("url") or "")' 2>/dev/null || true)"; [ -n "$u" ] || u="$(_sum_get "$_SUM_DDIR/.env" PANEL_URL)"; printf '%s' "$u"; }
# Is <name> a container of a REAL docker install? A bare NAME match is not enough. An aborted conversion
# leaves containers in state `created` — allocated, never started, no compose dir behind them — and matching
# those made a bare-metal master print a Docker summary with "URL https:///" and "TLS ?", because every value
# was then read from an .env that does not exist. Two pieces of positive evidence instead: the container has
# actually run at some point, and the compose environment it would have come from is still there.
_sum_dctr(){ have docker || return 1
  [ -f "$_SUM_DDIR/.env" ] || return 1
  docker ps -a --format '{{.Names}}|{{.State}}' 2>/dev/null \
    | grep -c "^$1|" >/dev/null && ! docker ps -a --format '{{.Names}}|{{.State}}' 2>/dev/null | grep -cx "$1|created" >/dev/null; }
_sum_detect(){ local hm="" nm=""   # echoes "<host_method> <node_method>", each ∈ baremetal|docker|"" (none)
  # ⚠️ A PARKED DOCKER PANEL IS NOT THE ONE THAT ANSWERS. With both panels on the box (guard_second_panel), a bare-metal
  # install that had just stopped the docker panel printed the DOCKER panel's summary — its user name next to the new
  # bare password under "new login — save the password now", its .env and compose commands (1.8.8 qualification, q5).
  # The live docker panel first, then a bare one, then a docker one that is only parked.
  if _sum_dctr swg-panel && ! docker_parked swg-panel; then hm=docker
  elif [ -f /etc/systemd/system/swg-panel-server.service ] || [ -x /opt/swg-panel/swg-panel-server ]; then hm=baremetal
  elif _sum_dctr swg-panel; then hm=docker; fi
  if _sum_dctr swg-node; then nm=docker
  elif [ -f /etc/systemd/system/swg-noded.service ] || [ -f /etc/swg-agent/config.json ]; then nm=baremetal; fi
  printf '%s %s' "$hm" "$nm"; }
_sum_note(){ case "$1" in docker) echo "$(b 'newly converted') (was bare-metal)";; *) echo "$(b 'newly converted') (was docker)";; esac; }

# Subscription surface for the summary — the per-user QR page (swg-sub). Emits three TAB-separated fields:
#   <enabled|disabled|unset>  <auto|manual>  <public url>
# Read straight from panel-settings.json (the panel owns it) rather than from install.conf/.env, which only
# carry the BIND — the public URL and the on/off switch are panel state and can be changed after install.
_sum_sub_state(){   # <baremetal|docker>
  local ps; if [ "$1" = docker ]; then ps="$_SUM_DDIR/data/lib/panel-settings.json"; else ps=/var/lib/swg-panel/panel-settings.json; fi
  [ -f "$ps" ] || { printf 'unset\t\t'; return 0; }
  have python3 || { printf 'unset\t\t'; return 0; }
  python3 - "$ps" <<'PYSUB' 2>/dev/null || printf 'unset\t\t'
import json, sys
try: d = json.load(open(sys.argv[1]))
except Exception: print("unset\t\t"); raise SystemExit
sub = d.get("subscriptions") or {}
url = (((d.get("access") or {}).get("sub") or {}).get("url") or "").rstrip("/")
state = "enabled" if sub.get("enabled") else ("disabled" if "enabled" in sub else "unset")
print("%s\t%s\t%s" % (state, "auto" if sub.get("auto_generate") else "manual", url))
PYSUB
}
summary_sub_block(){   # <method>
  local st auto url
  IFS="$(printf '\t')" read -r st auto url <<EOS
$(_sum_sub_state "$1")
EOS
  echo
  case "$st" in
    enabled)
      local _how="manually"; [ "$auto" = auto ] && _how="automatically"
      echo "  $(b 'Subscriptions') (per-user links created $(b "$_how")):"
      echo
      if [ -n "$url" ]; then printf '    %-9s%s\n' "URL" "$(bb "$url/")$(b '<user-link>')"
      else                   printf '    %-9s%s\n' "URL" "not set yet — set the subscription address in the panel"; fi
      echo
      if [ "$auto" = auto ]; then echo "    A link is minted for every new user automatically."
      else                        echo "    Links are minted per user, on demand — open a user and create theirs."; fi
      ;;
    disabled) echo "  $(b 'Subscriptions') (off):"; echo
              echo "    Every subscription URL returns 404. Nobody can load a config from a link." ;;
    *)        echo "  $(b 'Subscriptions') (not configured yet):"; echo
              echo "    Off until you turn them on — the per-user QR page is not being served." ;;
  esac
  echo
  echo "    Configure in the panel: $(b 'Settings → Subscriptions')"
}
summary_host_block(){   # <method> <converted?yes|no>
  local m="$1" conv="$2" url login tls ver mlabel note="" e dom port base sch ps reset
  if [ "$m" = docker ]; then e="$_SUM_DDIR/.env"; mlabel=Docker
    dom="$(_sum_get "$e" PANEL_DOMAIN)"; port="$(_sum_get "$e" PANEL_PORT)"; base="$(_sum_get "$e" PANEL_BASE)"; tls="$(_sum_get "$e" TLS)"
    login="$(_sum_get "$e" PANEL_USER)"; ver="$(docker exec swg-panel cat /opt/swg-panel/VERSION 2>/dev/null | sed -n 1p || true)"
  else mlabel=Bare-metal
    dom="$(_sum_get /etc/swg-panel/install.conf PANEL_DOMAIN)"; port="$(_sum_get /etc/swg-panel/install.conf PORT)"; base="$(_sum_get /etc/swg-panel/install.conf PANEL_BASE)"; tls="$(_sum_get /etc/swg-panel/install.conf TLS_MODE)"
    login="$(sed -n 's/^\([^:]*\):.*/\1/p' /etc/swg-panel/auth 2>/dev/null | sed -n 1p || true)"; ver="$(cat /opt/swg-panel/VERSION 2>/dev/null | sed -n 1p || true)"
  fi
  sch=https; [ "$tls" = none ] && sch=http; ps=":$port"; case "$port" in 443|80|"") ps="";; esac; url="${sch}://${dom}${ps}${base}/"
  [ "$conv" = yes ] && note="  ·  $(_sum_note "$m")"
  echo "${C_BLUE:-}▸${RESET:-} $(b "$mlabel SWG Host")${ver:+ $(b "v$ver")}$note"
  echo
  # A fresh install MINTS the login, and the auth file only ever holds the pbkdf2 hash — so this summary is the one
  # and only place the plaintext password is ever shown. The installer hands it over in SWG_SUMMARY_PASS; without it
  # (re-install / convert) the existing login is untouched and there's no password to show.
  # A password the operator GAVE is never printed (SWG_SUMMARY_PASS_GIVEN): they have it, and the log of an unattended
  # install would hold it (1.8.8 qualification, round 8) — only a GENERATED one is shown, once.
  if [ -n "${SWG_SUMMARY_PASS:-}" ]; then echo "  $(b 'Panel') (new login — $(b 'save the password now'), it is not shown again):"
  elif [ -n "${SWG_SUMMARY_PASS_GIVEN:-}" ]; then echo "  $(b 'Panel') (new login — with the password you gave):"
  else                                    echo "  $(b 'Panel') (login + the $(b "${tls:-?}") cert preserved):"; fi
  echo
  printf '    %-9s%s\n' "URL"     "$(bb "$url")"
  if [ "$m" = docker ]; then reset="docker exec -it swg-panel swg-passwd"
  else reset="sudo swg-passwd"; fi
  if [ -n "${SWG_SUMMARY_PASS:-}" ]; then
    printf '    %-9s%s\n' "Login"    "$(b "${login:-admin}")"
    printf '    %-9s%s\n' "Password" "$(b "$SWG_SUMMARY_PASS")  (change it in the panel: Account · or reset with $(b "$reset"))"
  elif [ -n "${SWG_SUMMARY_PASS_GIVEN:-}" ]; then
    printf '    %-9s%s\n' "Login"    "$(b "${login:-admin}")"
    printf '    %-9s%s\n' "Password" "the one you gave — not shown  (change it in the panel: Account · or reset with $(b "$reset"))"
  else
    printf '    %-9s%s\n' "Login"   "$(b "${login:-admin}")  (to reset the password run: $(b "$reset"))"
  fi
  printf '    %-9s%s\n' "TLS"     "$(b "${tls:-?}")"
  if [ "$m" = docker ]; then
    printf '    %-9s%s\n' "Config"  "$(b "nano $_SUM_DDIR/.env")"
    printf '    %-9s%s\n' "Restart" "$(b "cd $_SUM_DDIR && docker compose restart swg-panel")"
    printf '    %-9s%s\n' "Logs"    "$(b "cd $_SUM_DDIR && docker compose logs -f swg-panel")"
  else
    printf '    %-9s%s\n' "Config"  "$(b /etc/swg-panel/)  (change URL/TLS by re-running the installer)"
    printf '    %-9s%s\n' "Restart" "$(b 'systemctl restart swg-panel-server')"
    printf '    %-9s%s\n' "Logs"    "$(b 'swg-logs panel -f')"
  fi
  summary_sub_block "$m"    # the subscription surface is part of what a panel install delivers — say where it stands
}
# WHERE A BARE-METAL NODE'S SHARED RECORD ACTUALLY IS. swg-noded moved its three run-model-independent records
# (turn-proxy / wdtt / csqtt) into the state dir, because that is the one directory every run-model already shares
# — see `_shared_record` there. /etc/swg-agent is kept ONLY so a rollback to an older build still finds a record,
# and is never written again once the daemon has migrated it. Every shell reader that kept pointing at the legacy
# path therefore read a file that was stale from the first write after the upgrade, or absent on a box installed
# since: the install/convert summaries reported no WDTT/csqtt servers on boxes that had them, and — worse, because
# it is silent and irreversible — a convert to docker carried a stale record, or skipped the copy entirely because
# `[ -f ]` was false. For WDTT/csqtt that record holds the node-owned owner password and `pw_seen`, so losing it
# re-mints a credential over a store that still holds the old one and every client stops connecting.
# Newest mtime wins, decided exactly as the daemon decides it.
lc_bare_record(){   # lc_bare_record <name.json> [legacy-override] → the path to READ
  local n="$1" old="${2:-/etc/swg-agent/$1}" new="${SWG_NODED_STATE:-/var/lib/swg-noded}/$1"
  if [ -f "$new" ] && [ -f "$old" ]; then
    if [ "$old" -nt "$new" ]; then printf '%s\n' "$old"; else printf '%s\n' "$new"; fi
    return 0
  fi
  if [ -f "$new" ]; then printf '%s\n' "$new"; else printf '%s\n' "$old"; fi
  return 0; }
# …and BOTH paths, for a writer or a remover: the state dir is what this build reads, the legacy path is what a
# rollback would read, so a component being carried over must land in both and one being removed must leave neither.
lc_bare_record_all(){   # lc_bare_record_all <name.json> [legacy-override] → both paths, space separated
  printf '%s %s\n' "${SWG_NODED_STATE:-/var/lib/swg-noded}/$1" "${2:-/etc/swg-agent/$1}"; }

# WDTT servers on this node, from the record swg-noded keeps (bare-metal the node state dir, docker the mounted
# data dir). They own their interface (created by the server, so it has no .conf the interface scan could find)
# AND act as a turn-family proxy — so the summary gives them their own section instead of splitting them.
_sum_wdtt_rows(){   # <baremetal|docker>
  local rec; if [ "$1" = docker ]; then rec="$_SUM_DDIR/data/node/wdtt.json"; else rec="$(lc_bare_record wdtt.json)"; fi
  [ -f "$rec" ] || return 0
  have python3 || return 0
  python3 -c 'import json,sys
try: w=(json.load(open(sys.argv[1])).get("wdtt") or [])
except Exception: w=[]
for i in w:
    if isinstance(i,dict) and i.get("iface"):
        print("\t".join([i["iface"], i.get("fork") or "?", i.get("listen") or ("127.0.0.1:%s" % (i.get("wg_port") or "?")), i.get("wg_addr") or "?"]))' "$rec" 2>/dev/null
}
_sum_wdtt_row(){ printf '    %s%-10s%s  %s%-10s%s  %s  %s\n' "${C_GREEN:-}" "$1" "${RESET:-}" "${BOLD:-}" "$2" "${RESET:-}" "${3:-?}" "${4:-?}"; }

_sum_wdtt_block(){   # <baremetal|docker> — the "WDTT interfaces & proxies" section, printed only when any exist
  local rows _i _f _l _a
  rows="$(_sum_wdtt_rows "$1")"; [ -n "$rows" ] || return 0
  echo; echo "  $(b 'WDTT interfaces & proxies') (own their interface — managed from the panel):"; echo
  while IFS="$(printf '\t')" read -r _i _f _l _a; do [ -n "$_i" ] && _sum_wdtt_row "$_i" "$_f" "$_l" "$_a"; done <<EOS
$rows
EOS
}
# csqtt servers, same section shape. Its record is a flat {iface: inst} map (WDTT's is a list under "wdtt"), and the
# fork column is always csqtt — one implementation, no fork variance — so it reports the subnet's tun_addr instead.
_sum_csqtt_rows(){   # <baremetal|docker>
  local rec; if [ "$1" = docker ]; then rec="$_SUM_DDIR/data/node/csqtt.json"; else rec="$(lc_bare_record csqtt.json)"; fi
  [ -f "$rec" ] || return 0
  have python3 || return 0
  python3 -c 'import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
if isinstance(d,dict):
    for k,i in d.items():
        if isinstance(i,dict):
            print("\t".join([k, "csqtt", i.get("listen") or "?", i.get("tun_addr") or "?"]))' "$rec" 2>/dev/null
}
_sum_csqtt_block(){   # <baremetal|docker> — printed only when any exist
  local rows _i _f _l _a
  rows="$(_sum_csqtt_rows "$1")"; [ -n "$rows" ] || return 0
  echo; echo "  $(b 'csqtt interfaces & proxies') (own their interface — managed from the panel):"; echo
  while IFS="$(printf '\t')" read -r _i _f _l _a; do [ -n "$_i" ] && _sum_wdtt_row "$_i" "$_f" "$_l" "$_a"; done <<EOS
$rows
EOS
}
summary_node_block(){   # <method> <converted?yes|no>
  local m="$1" conv="$2" ver mlabel note="" nep purl conf n proto units svc inst lis con u _trec _meshif
  nep="$(_sum_node_ep)"; purl="$(_sum_node_purl)"
  if [ "$m" = docker ]; then mlabel=Docker; ver="$(docker exec swg-node cat /opt/swg-noded/VERSION 2>/dev/null | sed -n 1p || true)"
  else mlabel=Bare-metal; ver="$(cat /opt/swg-noded/VERSION 2>/dev/null | sed -n 1p || true)"; fi
  [ "$conv" = yes ] && note="  ·  $(_sum_note "$m")"
  echo "${C_BLUE:-}▸${RESET:-} $(b "$mlabel SWG Node")${ver:+ $(b "v$ver")}${purl:+  ·  syncs to $(bb "$purl")}$note"
  if [ "$m" = docker ]; then
    # Header only when there is something under it. Installers no longer create interfaces — the panel does —
    # so a fresh install used to print the heading over an empty list, announcing a section that had no content.
    _ifn=0; for conf in "$_SUM_DDIR"/data/node-confs/*.conf; do [ -f "$conf" ] && _ifn=$((_ifn+1)); done
    echo
    if [ "$_ifn" -eq 0 ]; then echo "  $(b 'Interfaces'):  none yet — add them in the web panel"
    else echo "  $(b 'Interfaces') (in the swg-node container):"; fi
    echo
    _meshif=""
    for conf in "$_SUM_DDIR"/data/node-confs/*.conf; do [ -f "$conf" ] || continue; n="$(basename "$conf" .conf)"
      is_sys_iface "$n" && { _meshif="$_meshif $n"; continue; }   # panel-managed mesh link — never listed as a user interface
      grep -qiE '^[[:space:]]*(Jc|Jmin|S1|H1)[[:space:]]*=' "$conf" && proto=awg || proto=wg; _sum_iface_row "$n" "$proto" "$conf" "$nep"; done
    for n in $_meshif; do printf '    %s Mesh interface %s\n' "${C_BLUE:-}→${RESET:-}" "${C_BLUE:-}$n${RESET:-}"; done
    units="$(docker ps --format '{{.Names}}' 2>/dev/null | grep '^swg-turn-' || true)"; _trec="$_SUM_DDIR/data/node/turn-proxy.json"
    if [ -n "$units" ]; then echo; echo "  $(b 'Turn-proxies') (sibling containers — swg-turn-*, managed from the panel):"; echo
      if [ -f "$_trec" ] && have python3; then   # docker turns are containers — listen/connect live in the node turn record, not a unit file
        python3 -c 'import json,sys
try: tps=(json.load(open(sys.argv[1])).get("turn_proxies") or [])
except Exception: tps=[]
for t in tps:
    if t.get("service"): print(t["service"]+"\t"+t.get("listen","")+"\t"+t.get("connect",""))' "$_trec" 2>/dev/null \
          | while IFS="$(printf '\t')" read -r svc lis con; do [ -n "$svc" ] && _sum_turn_row "$svc" "$lis" "$con"; done
      else for svc in $units; do _sum_turn_row "$svc" "" ""; done; fi
    fi
    _sum_wdtt_block docker
    _sum_csqtt_block docker
  else
    # ⚠️ ASK WHO OWNS IT, don't glob the directory. "What .conf files exist" is a different question from
    # "what does this node manage", and on a box that already ran somebody else's server they differ: this
    # summary listed a FOREIGN awg0 under "managed bare-metal" TWENTY LINES after the same run had correctly
    # reported it as an adoption candidate the panel does not own — and after writing a config.json that does
    # not contain it. One run, two contradictory statements, and the wrong one is the one at the end.
    # Measured on hel-flux 2026-09-08. uninstall.sh answers this from the same file and the two must agree.
    #
    # Unreadable ⇒ fall back to listing everything, which is today's behaviour: here the cost of not knowing
    # is a cosmetic over-claim, whereas in the UNINSTALLER the same unknown costs somebody's data, so that
    # one fails the other way. Same question, opposite safe answer, on purpose.
    # ⚠️ "READ IT, AND IT IS EMPTY" IS AN ANSWER; "could not read it" is not. The first version of this
    # decided by whether the output was non-empty, so a node that manages NOTHING YET — which is every
    # fresh install, because the mesh links are added by swg-noded after this summary prints — took the
    # can't-tell fallback and listed every .conf on the box. That is the same failure this block exists to
    # fix, made one level up. The exit status is what distinguishes them.
    _sum_owned=""; _sum_owned_known=no
    if [ -f /etc/swg-agent/config.json ] && have python3; then
      if _sum_out="$(python3 - <<'PY'
import json
c = json.load(open("/etc/swg-agent/config.json"))
print(" ".join(str(k) for k in (c.get("interfaces") or {})))
PY
)"; then _sum_owned=" $_sum_out "; _sum_owned_known=yes; fi
    fi
    _sum_ours(){ [ "$_sum_owned_known" = yes ] || return 0; case "$_sum_owned" in *" $1 "*) return 0;; *) return 1;; esac; }
    _ifn=0; _foreign=0
    for conf in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf; do [ -f "$conf" ] || continue
      n="$(basename "$conf" .conf)"; is_sys_iface "$n" && continue
      if _sum_ours "$n"; then _ifn=$((_ifn+1)); else _foreign=$((_foreign+1)); fi; done
    echo
    if [ "$_ifn" -eq 0 ]; then echo "  $(b 'Interfaces'):  none yet — add them in the web panel"
    else echo "  $(b 'Interfaces') (managed bare-metal — peers stay in the panel):"; fi
    echo
    _meshif=""
    for conf in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf; do [ -f "$conf" ] || continue; n="$(basename "$conf" .conf)"
      is_sys_iface "$n" && { _meshif="$_meshif $n"; continue; }   # panel-managed mesh link — never listed as a user interface
      _sum_ours "$n" || continue                                  # somebody else's — named above as an adoption candidate
      case "$conf" in */wireguard/*) proto=wg;; *) proto=awg;; esac; _sum_iface_row "$n" "$proto" "$conf" "$nep"; done
    [ "$_foreign" -gt 0 ] && printf '    %s%s wg/awg interface(s) on this box are NOT managed here — adopt them from the panel if you want them%s\n' \
        "${C_GREY:-}" "$_foreign" "${RESET:-}"
    for n in $_meshif; do printf '    %s Mesh interface %s\n' "${C_BLUE:-}→${RESET:-}" "${C_BLUE:-}$n${RESET:-}"; done
    units="$(ls /etc/systemd/system/vk-turn-proxy-*.service 2>/dev/null || true)"
    if [ -n "$units" ]; then echo; echo "  $(b 'Turn-proxies') (host systemd, managed from the panel):"; echo
      for u in $units; do svc="$(basename "$u" .service)"; inst="${svc#vk-turn-proxy-}"
        # what clients dial (SWG_DIAL — set when it is not the bind: a DDNS name, an address behind NAT), else the bind
        lis="$(sed -n 's/^SWG_DIAL=//p' "/opt/vk-turn-proxy/$inst/turn.env" 2>/dev/null | sed -n 1p || true)"
        [ -n "$lis" ] || lis="$(sed -n 's/^SWG_LISTEN=//p' "/opt/vk-turn-proxy/$inst/turn.env" 2>/dev/null | sed -n 1p || true)"
        con="$(sed -n 's/^SWG_CONNECT=//p' "/opt/vk-turn-proxy/$inst/turn.env" 2>/dev/null | sed -n 1p || true)"
        _sum_turn_row "$svc" "$lis" "$con"; done; fi
    _sum_wdtt_block baremetal
    _sum_csqtt_block baremetal
  fi
  echo; node_reconfig_block "$([ "$m" = docker ] && echo docker || echo baremetal)" "$_SUM_DDIR"
}
print_summary(){   # <OP> [converted-parts: host|node|both]
  local op="$1" conv="${2:-}" det hm nm title hc=no nc=no printed=""
  det="$(_sum_detect)"; hm="${det%% *}"; nm="${det##* }"
  case "$op" in INSTALL) title="INSTALL COMPLETE";; RE-INSTALL) title="RE-INSTALL COMPLETE";; UPDATE) title="UPDATE COMPLETE";; CONVERSION) title="CONVERSION COMPLETE";; *) title="$op COMPLETE";; esac
  case " $conv " in *" host "*|*" both "*) hc=yes;; esac
  case " $conv " in *" node "*|*" both "*) nc=yes;; esac
  summary_title "$title"
  [ -n "$hm" ] && { summary_host_block "$hm" "$hc"; printed=1; }
  [ -n "$nm" ] && { [ -n "$printed" ] && echo; summary_node_block "$nm" "$nc"; }
  summary_end
}

# A co-located node dials the panel over LOOPBACK (http://127.0.0.1:<local-port>) — plain HTTP there is the
# design, not a mistake: the request never leaves the box, so there is no wire to intercept. Warning about it
# on every master install/convert taught operators to ignore a message that is real for a REMOTE node.
_url_is_loopback(){ case "${1#*://}" in 127.0.0.1|127.0.0.1:*|localhost|localhost:*|\[::1\]|\[::1\]:*|::1|::1:*) return 0;; *) return 1;; esac; }

# ── validators ──
v_iface(){   case "$1" in ""|*[!a-zA-Z0-9_-]*) return 1;; esac; [ "${#1}" -le 15 ]; }
v_subnet(){  have python3 || return 0; python3 -c "import ipaddress,sys;ipaddress.ip_network(sys.argv[1],strict=False)" "$1" >/dev/null 2>&1; }
v_hostport(){ case "$1" in *:*) v_host "${1%%:*}" && v_port "${1##*:}";; *) return 1;; esac; }

# ── ports ──
next_free_port(){ local p="${1:-51820}"; while [ "$p" -le 65535 ] && ! port_free "$p"; do p=$((p+1)); done; echo "$p"; }

# The name the PANEL currently has for the local node, matched by verifying the node's token against each
# nodes.json token_hash (same pbkdf2 the panel uses). Prints the name (empty if not found). Lets a re-install
# default to the UI-renamed name instead of the hostname.
#   panel_node_name_tok <nodes.json> <raw-token>        (docker: NODE_TOKEN from .env)
#   panel_node_name     <nodes.json> <agent-config.json> (bare-metal: token read from the agent config)
panel_node_name_tok(){ [ -f "$1" ] && [ -n "${2:-}" ] || return 0
  python3 - "$1" "$2" <<'PY' 2>/dev/null || true
import json,sys,hashlib,base64
try: nodes=json.load(open(sys.argv[1]))
except Exception: sys.exit(0)
tb=sys.argv[2].encode()
for _id,n in (nodes.items() if isinstance(nodes,dict) else []):
    h=n.get("token_hash") or ""
    try:
        _algo,it,salt,want=h.split("$")
        got=base64.b64encode(hashlib.pbkdf2_hmac("sha256",tb,base64.b64decode(salt),int(it))).decode()
    except Exception: continue
    if got==want: print(n.get("name") or ""); break
PY
}
panel_node_name(){ [ -f "$2" ] || return 0
  local _t; _t="$(python3 -c 'import json,sys;print((json.load(open(sys.argv[1])).get("panel") or {}).get("token") or "")' "$2" 2>/dev/null || true)"
  panel_node_name_tok "$1" "$_t"; }

# ── lifecycle status signalling (re-install / convert / update / uninstall) ──────────────────────────────
# A script calls `lc_init <op> <emit_fn>` right after step 1, where:
#   op ∈ reinstall | convert-bare | convert-docker | update | uninstall
#   emit_fn ∈ lc_emit_post (node/docker/convert → panel) | lc_emit_file (host → host_proc)
# lc_init signals the in-progress state, captures output for the failed-state log tail, and installs traps so
# the EXIT decides the terminal: Ctrl-C/SIGTERM → "<op> aborted"; any non-zero exit → "<op> failed" + log
# tail; clean exit → the success state (uninstall has none — the goodbye removes the node). Backends read the
# conventional vars the caller sets first: LC_URL/LC_TOKEN/LC_VERIFY (post) or LC_FILE (host_proc path).
# Data-entry spacing: a prompt helper ends with _pnl — ONE trailing blank line + a mark. The next step() skips its
# own leading blank while that mark is up (so prompt→step shows ONE blank, not two); any real output (info/ok/warn/
# sub, or another step) lowers the mark so content→step still gets its separating blank. Net: exactly one blank line
# after every data-entry prompt, everywhere, without doubling.
_SWG_NL=""
_pnl(){ echo; _SWG_NL=1; }                     # call at the end of a prompt helper (interactive path only)
_nlguard(){ _SWG_NL=""; }                      # call from real-output helpers so they don't get swallowed
LC_OP=""; LC_EMIT=""; LC_LOG=""; LC_ABORT=""; LC_HANDOFF=""; LC_DONE=""; LC_SUCCESS=""; LC_WITHHELD=""
_lc_inprogress(){ case "$1" in reinstall) echo reinstalling;; convert-bare) echo converting-bare;; convert-docker) echo converting-docker;; update) echo updating;; uninstall) echo uninstalling;; esac; }
_lc_success(){    case "$1" in reinstall) echo reinstalled;; convert-bare) echo converted-bare;; convert-docker) echo converted-docker;; update) echo updated;; uninstall) echo "";; esac; }
_lc_prefix(){     case "$1" in convert-*) echo convert;; *) echo "$1";; esac; }   # aborted/failed are op-generic
lc_emit(){ [ -n "${LC_EMIT:-}" ] && [ -n "${1:-}" ] && "$LC_EMIT" "$1" "${2:-}" || true; }
lc_handoff(){ LC_HANDOFF=1                                      # another script now owns the terminal (convert→installer)
  # …and exec'd, it never runs our EXIT trap: the log goes now (the tee writes on into the unlinked file) — every bare →
  # Docker convert left a /tmp copy of the whole install's output behind (1.8.9 qualification LC24 #15b)
  if [ -n "${LC_LOG:-}" ]; then rm -f "$LC_LOG" 2>/dev/null || true; fi; }
# The node's TRUST travels with its token: LC_VERIFY (yes = CA verification) and LC_FP (its pinned certificate) — every
# POST goes through panel_req, which checks the panel on the connection the token is sent on. The caller sets LC_FP
# wherever the node has a pin (bare: the agent config's panel.fingerprint; Docker: TLS_FINGERPRINT / its learned
# panel-fp); a loopback URL (a co-located node dialling its own panel) needs neither.
# ⚠️ ONE REFUSAL ENDS IT FOR THE RUN (LC_WITHHELD): a panel that fails the node's trust once gets no further status —
# and no terminal post from the EXIT trap either — and the run says so once. The first refusal is final because nothing
# in a run changes the certificate a panel presents, and retrying it for 25 s would only be noise.
lc_emit_post(){ [ -n "${LC_URL:-}" ] && [ -n "${LC_TOKEN:-}" ] || return 0
  [ -n "${LC_WITHHELD:-}" ] && return 0
  local data="" _i _why _rc
  if [ -n "${2:-}" ]; then data="$(python3 -c 'import json,sys;print(json.dumps({"state":sys.argv[1],"err":sys.argv[2]}))' "$1" "$2" 2>/dev/null)"; fi
  [ -n "$data" ] || data="{\"state\":\"$1\"}"
  # RETRY: a single best-effort POST silently drops the status when the panel is briefly unreachable mid-convert
  # (just restarted / settling, or an opposite convert fired the instant the new panel came up) — exactly why
  # "converting" sometimes never showed and a stale "converted" wouldn't flip to "converting". A few quick retries
  # make converting/converted reliably land. Still best-effort overall (never trips set -e).
  #   • IN-PROGRESS states stay short: the panel is about to restart from THIS op — don't block the update on it.
  #   • TERMINAL states (updated / converted / reinstalled / *-failed / *-aborted) are emitted right when the
  #     panel may be restarting from this very op (a master host-update restarts the panel, THEN posts the node's
  #     "updated"), so wait ~30s for it to come back — otherwise the tag hangs until PROC_GRACE flips it to a
  #     FALSE "<op> failed". (The panel also self-heals "updating" once the node reports the target version, so
  #     this is belt-and-suspenders.)
  # The same split decides the WORDING: an in-progress state has not "finished" anything, and a *-failed or
  # *-aborted state must never be announced as done. Both lines below said "this finished" / "the conversion
  # itself is done" for every op and every outcome — so `bootstrap.sh update` on a box with no install at all
  # ended its "no swg-panel install found" error with a line claiming a conversion had completed.
  local _secs _phase; case "$1" in
    updating|reinstalling|converting-bare|converting-docker|uninstalling) _secs=6; _phase="started";;
    *) _secs=25; _phase="finished";; esac
  # SAY SO while waiting. This runs from the EXIT trap, i.e. AFTER the completion summary has printed, so a
  # silent 25-second loop looks exactly like a hang at the very moment the operator has been told it's done —
  # and the run then exits fine, which is more baffling still. One line on the first failure, one on give-up.
  # ⚠️ The budget is WALL-CLOCK seconds and each attempt gets only what is left of it. It was an attempt COUNT printed
  # as seconds: true while a restarting panel refuses at once, but a panel address that DROPS packets made every attempt
  # wait out `--max-time 6` — 29 × 7 s ≈ 3.4 min after "Update complete" (measured on a Debian VM, 2026-09-18). A
  # refusing panel still gets a retry about every second for the whole budget. 6 s, not less, for an in-progress state:
  # its first attempt keeps the full 6 s it always had — `reinstalling` is where the panel adopts the box's current
  # keys, which no sync repeats, and a node with a dead first nameserver spends ~5 s in DNS alone.
  local _end=$((SECONDS + _secs)) _left; _i=0
  while _left=$((_end - SECONDS)); [ "$_left" -gt 0 ]; do
    _rc=0; _why="$(SWG_TOK="$LC_TOKEN" SWG_BODY="$data" panel_req POST "${LC_URL%/}/api/node/proc-status" \
      "${LC_VERIFY:-no}" "${LC_FP:-}" "$(( _left < 6 ? _left : 6 ))" 2>/dev/null)" || _rc=$?
    if [ "$_rc" = 0 ]; then [ "$_i" -gt 0 ] && echo "    panel reached — status recorded." || true; return 0; fi
    if [ "$_rc" = 4 ]; then LC_WITHHELD=1
      echo "    the panel was not told \"$1\": ${_why:-it is not the panel this node trusts}. The node token goes nowhere for the rest of this run."
      return 0; fi
    # ⚠️ A REFUSAL IS AN ANSWER, NOT AN OUTAGE. HTTP 401/403: the panel is up and does not accept this node's key. It was
    # asked again about once a second for the whole budget — up to 25 s after "Update complete" — to hear the same thing
    # (1.8.8 qualification, round 10, N13). One answer is enough; the line below says what it was.
    case "$_rc:$_why" in "3:HTTP 401"|"3:HTTP 403") break;; esac
    [ "$_i" -eq 0 ] && echo "    telling the panel this $_phase (it may still be restarting) — up to ${_secs}s…"
    _i=$((_i + 1)); [ $((_end - SECONDS)) -gt 0 ] || break; sleep 1
  done
  # Name the state we could not record and stop there. Whether the op succeeded is not this function's news to
  # break: it only failed to POST, which changes nothing either way about what happened on the box.
  # ⚠️ …AND SAY WHAT THE PANEL ANSWERED WHEN IT ANSWERED. A panel that turned every attempt down (HTTP 401: it does not
  # accept this node's key) was reported as "couldn't reach the panel" after the whole budget (1.8.8 qualification,
  # round 8) — the one cause the operator could act on, hidden behind the one they could not.
  case "$_rc:$_why" in
    "3:HTTP 401"|"3:HTTP 403")
      echo "    the panel did not record \"$1\" — it answered $_why: it does not accept this node's key (check the node in the panel's Nodes screen, or re-enroll it).";;
    3:*) echo "    the panel did not record \"$1\" — it answered ${_why:-an error}; it corrects the tag on the node's next sync.";;
    *)   echo "    couldn't reach the panel to record \"$1\" — the panel corrects the tag on the node's next sync.";;
  esac
  return 0; }
# docker_node_panel <install-dir> — the panel a DOCKER node really talks to, and how it trusts it, for the calls made on
# its behalf from the host (update.sh's status, …). Sets DNP_URL DNP_TOKEN DNP_VERIFY DNP_FP: the kept .env, overridden
# by what the node LEARNED (data/node/panel-url / -token / -verify / -fp — a re-point or a Transfer), exactly as
# docker/node-entrypoint.sh decides them at every start (convert.sh reads them the same way). The .env alone named the
# panel the node USED to sync with — and its pin was never read at all, so these calls went out with curl -k.
# ⚠️ TWIN: uninstall.sh's _docker_node_panel (it does not source this file).
# DNP_LEARNED names the learned files that were there (empty = the .env is the whole story).
# ⚠️ A TRANSFER TO A PANEL A PUBLIC CA VOUCHES FOR LEAVES NO PIN BEHIND — and none must come back. swg-noded writes the
# posture it promoted with (swg-noded _persist_panel_auth): panel-verify=yes and NO panel-fp when the far panel answered
# under CA verification. Taking the .env's pin in that case — the pin of the panel the node LEFT — pinned the new panel
# to the old one's certificate: every call refused, and the node itself refused every sync from its next start on
# (docker/node-entrypoint.sh read it the same way). Only a learned verify=yes clears it: a learned verify=no with no fp
# keeps the configured pin, because a blank pin there would mean "verify nothing" (see the entrypoint).
docker_node_panel(){ local d="$1" k v _lv="" _lf=""
  for k in PANEL_URL NODE_TOKEN TLS_VERIFY TLS_FINGERPRINT; do
    v="$(sed -n "s/^$k=//p" "$d/.env" 2>/dev/null | sed -n 1p | sed 's/[[:space:]]\{1,\}#.*$//' | tr -d '"' || true)"
    case "$k" in PANEL_URL) DNP_URL="$v";; NODE_TOKEN) DNP_TOKEN="$v";; TLS_VERIFY) DNP_VERIFY="$v";; TLS_FINGERPRINT) DNP_FP="$v";; esac
  done
  DNP_LEARNED=""
  v="$(head -n1 "$d/data/node/panel-url" 2>/dev/null | tr -d '[:space:]' || true)";    [ -n "$v" ] && { DNP_URL="$v"; DNP_LEARNED="panel-url"; }
  v="$(head -n1 "$d/data/node/panel-token" 2>/dev/null | tr -d '[:space:]' || true)";  [ -n "$v" ] && { DNP_TOKEN="$v"; DNP_LEARNED="$DNP_LEARNED panel-token"; }
  _lv="$(head -n1 "$d/data/node/panel-verify" 2>/dev/null | tr -d '[:space:]' || true)"; [ -n "$_lv" ] && { DNP_VERIFY="$_lv"; DNP_LEARNED="$DNP_LEARNED panel-verify"; }
  _lf="$(head -n1 "$d/data/node/panel-fp" 2>/dev/null | tr -d '[:space:]' || true)";     [ -n "$_lf" ] && { DNP_FP="$_lf"; DNP_LEARNED="$DNP_LEARNED panel-fp"; }
  [ "$_lv" = yes ] && [ -z "$_lf" ] && DNP_FP=""
  DNP_LEARNED="${DNP_LEARNED# }"
  [ "$DNP_VERIFY" = yes ] || DNP_VERIFY=no
  return 0; }
lc_emit_file(){ local f="${LC_FILE:-}"; [ -n "$f" ] || return 0; mkdir -p "$(dirname "$f")" 2>/dev/null || true
  if [ -n "${2:-}" ]; then printf '%s\n%s\n' "$1" "$2" > "$f" 2>/dev/null || true
  else printf '%s' "$1" > "$f" 2>/dev/null || true; fi; }
_lc_exit(){ local rc=$?                                        # MUST preserve rc (EXIT trap's last cmd = exit code)
  [ -n "$LC_DONE" ] && return $rc; LC_DONE=1
  # detach from the tee (restore real stdout/err, close the pipe) and WAIT for it to flush, so the log tail
  # we read below is complete (tee block-buffers — without this the failed-state err would be empty).
  if [ -n "${LC_OUT:-}" ]; then exec 1>&${LC_OUT} 2>&${LC_OUT}; { exec {LC_TEEFD}>&-; } 2>/dev/null
    [ -n "${LC_TEE:-}" ] && wait "$LC_TEE" 2>/dev/null || true; fi
  if   [ -n "$LC_HANDOFF" ]; then :
  elif [ -n "$LC_ABORT" ];   then lc_emit "$(_lc_prefix "$LC_OP")-aborted"
  elif [ "$rc" -ne 0 ];      then lc_emit "$(_lc_prefix "$LC_OP")-failed" "$(tail -n 20 "$LC_LOG" 2>/dev/null)"
  else local s; s="${LC_SUCCESS:-$(_lc_success "$LC_OP")}"; [ -n "$s" ] && lc_emit "$s"; fi   # LC_SUCCESS lets a script override (e.g. "reinstalled-updated")
  # The capture holds the WHOLE run transcript, and print_summary prints the minted panel login in
  # plaintext — the one place it is ever shown. Leaving that in /tmp until the next reboot is a real
  # credential leak on a shared box. The only consumer is the failure tail just above, so drop it here.
  [ -n "${LC_LOG:-}" ] && rm -f "$LC_LOG" 2>/dev/null || true
  # Whatever EXIT trap the caller had installed before lc_init took the slot (see lc_init). Run it LAST, once
  # the lifecycle state is out, and never let it change rc — the caller's exit status is the contract here.
  [ -n "${LC_ATEXIT:-}" ] && { eval "$LC_ATEXIT"; } >/dev/null 2>&1 || true
  return $rc; }
lc_init(){ LC_OP="$1"; LC_EMIT="$2"; LC_ABORT=""; LC_HANDOFF=""; LC_DONE=""; LC_SUCCESS=""
  LC_LOG="$(mktemp 2>/dev/null || echo "/tmp/swg-lc.$$")"; : > "$LC_LOG" 2>/dev/null || true
  chmod 600 "$LC_LOG" 2>/dev/null || true                      # the fallback path (no mktemp) isn't 0600 by itself
  # mirror output to the log AND the terminal; remember the tee pid so _lc_exit can flush it. Prompts read
  # /dev/tty, so interactivity is unaffected. If the fd plumbing isn't supported, fall back to no capture.
  if exec {LC_OUT}>&1 && exec {LC_TEEFD}> >(tee -a "$LC_LOG" >&${LC_OUT}) 2>/dev/null; then
    LC_TEE=$!; exec 1>&${LC_TEEFD} 2>&${LC_TEEFD}
  else LC_OUT=""; fi
  trap 'LC_ABORT=1; exit 130' INT TERM HUP                     # user abort → flag + exit → EXIT trap emits "aborted"
  # Installing an EXIT trap REPLACES whatever was there — bash keeps exactly ONE. update.sh sets one at the top
  # of the script to clear its run marker and reaches this ~35 lines later, so on every REAL update (LC_TOKEN is
  # read straight out of the node config / .env, so this arms itself, not just for a panel-triggered run) the
  # marker was silently orphaned and outlived the process. Adopt the caller's handler instead of discarding it.
  # Strip trap -p's `trap -- '…' EXIT` wrapper; a handler that itself contains quotes would need more care than
  # this, and none does. Never adopt our OWN handler — lc_init can run twice on some convert paths.
  LC_ATEXIT="$(trap -p EXIT)"; LC_ATEXIT="${LC_ATEXIT#trap -- \'}"; LC_ATEXIT="${LC_ATEXIT%\' EXIT}"
  [ "$LC_ATEXIT" = "_lc_exit" ] && LC_ATEXIT=""
  trap '_lc_exit' EXIT
  lc_emit "$(_lc_inprogress "$LC_OP")"; }                      # step 1 done → signal in-progress now

# Run "$@" with stdout+stderr on the CONTROLLING TERMINAL (/dev/tty) so `docker compose` renders its live
# progress BAR. lc_init's capture pipe — and any `| tee` / `exec bash` chain that leaves fd 1 a non-tty —
# makes compose fall back to plain line-by-line text; /dev/tty is the real terminal regardless of fd 1.
# Falls back to the inherited fds when there's no tty (headless/cron). Returns the wrapped command's status.
on_tty(){ if { true >/dev/tty; } 2>/dev/null; then "$@" >/dev/tty 2>/dev/tty; else "$@"; fi; }

# ── convert switch helpers: tear the OLD method down ONLY at the final switch (after the new one is fully
#    staged), so the node stays up the whole time. Generic (scan disk) → no per-name args needed. ───────────
# lc_teardown_baremetal [migrated-turn-svcs…] — stop+remove a bare-metal node: daemon, every wg/awg iface,
# files, and ONLY the host turn-proxies passed in (the ones being recreated on docker; ones the operator chose
# to keep stay running). Generic for the wg/awg side (scan disk) → no per-iface args needed.
lc_teardown_baremetal(){
  systemctl disable --now swg-noded 2>/dev/null || true
  local f n s
  for f in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf; do [ -f "$f" ] || continue; n="$(basename "$f" .conf)"
    awg-quick down "$n" 2>/dev/null || wg-quick down "$n" 2>/dev/null || true
    systemctl disable "awg-quick@$n" 2>/dev/null || true; systemctl disable "wg-quick@$n" 2>/dev/null || true
    rm -f "$f"; done
  for s in "$@"; do [ -n "$s" ] || continue; systemctl disable --now "$s" 2>/dev/null || true; rm -f "/etc/systemd/system/$s.service"; done   # migrated host turn-proxies only
  rm -rf /etc/systemd/system/swg-noded.service /etc/systemd/system/swg-noded.service.d
  swg_log_teardown swg-node swg-relay@.service vk-turn-proxy-.service swg-wdtt-.service swg-csqtt-.service   # (see there)
  systemctl daemon-reload 2>/dev/null || true
  rm -rf /opt/swg-noded /opt/swg-agent /etc/swg-agent /var/lib/swg-noded /etc/sudoers.d/swg-agent /var/log/swg-agent; }
# teardown_bare_panel — stop + remove the bare-metal panel (units + proxy vhost + binary), then move its STATE
# dirs aside (already staged into data/) so the box no longer reads as a bare panel and a later convert-back
# Remove the DOCKER address helper (swg-netctl-docker.*) — the mirror of what teardown_bare_panel does to the
# bare units. Used by the docker→bare convert: the bare panel installs its own swg-netctl, and leaving the docker
# pair behind arms a SECOND drainer on the same request queue. Its .timer then wakes every couple of seconds on a
# box with no compose install, hits systemd's start-limit, and races the real helper for the panel's address
# changes. Existence-guarded, so calling it on a box that never had docker is a no-op.
remove_docker_netctl(){
  # .path BELONGS IN THIS LIST. update.sh writes swg-netctl-docker.path (it superseded the 1s .timer), but this
  # helper was written before that existed and never caught up — so a docker→bare-metal convert left the .path
  # ENABLED and ACTIVE, triggering a .service the same call had just deleted. Reproduced converting a master
  # back: `swg-netctl-docker.service not-found failed`, a permanently broken unit that also masks real failures
  # in `systemctl --failed`. uninstall.sh already listed all three; this is that fix, applied to the convert.
  for _u in swg-netctl-docker.path swg-netctl-docker.timer swg-netctl-docker.service; do
    systemctl disable --now "$_u" >/dev/null 2>&1 || systemctl stop "$_u" >/dev/null 2>&1 || true
  done
  rm -f /etc/systemd/system/swg-netctl-docker.service /etc/systemd/system/swg-netctl-docker.timer \
        /etc/systemd/system/swg-netctl-docker.path /usr/local/bin/swg-netctl-docker
  rm -rf /etc/systemd/system/swg-netctl-docker.service.d   # its log level drop-in (docker_host_log_dropins) goes with it
  systemctl daemon-reload >/dev/null 2>&1 || true; }

# restages cleanly. Used by the bare→docker host/master convert (install-docker.sh, at the atomic switch).
teardown_bare_panel(){
  systemctl disable --now swg-panel-server >/dev/null 2>&1 || true
  systemctl disable --now swg-update.path  >/dev/null 2>&1 || true
  # swg-sub + swg-netctl are PANEL components — stop them too, or the bare swg-sub keeps port 8444 (the docker
  # swg-sub then can't bind it) and swg-netctl.path lingers. (The node datapath is handled separately.)
  # ONE AT A TIME. `systemctl disable --now a b c` ABORTS THE WHOLE OPERATION if any unit is missing — and
  # swg-netctl-docker.* never exist on a bare-metal box, so the single call below used to fail before stopping
  # anything, leaving the bare swg-sub running and holding its port (exactly what the comment above says it is
  # here to prevent). `|| true` then hid it. Proven: `disable --now probe missing.service` leaves probe ACTIVE
  # and returns 1; the same call without the missing unit stops it and returns 0.
  # The `stop` fallback covers a unit whose FILE is already gone while the process is still alive — `disable`
  # refuses that outright, and it is how the orphan survived a second teardown.
  for _u in swg-sub swg-netctl.path swg-netctl.service swg-netctl.timer swg-netctl-docker.path swg-netctl-docker.timer swg-netctl-docker.service; do
    systemctl disable --now "$_u" >/dev/null 2>&1 || systemctl stop "$_u" >/dev/null 2>&1 || true
  done
  rm -f /etc/systemd/system/swg-sub.service /etc/systemd/system/swg-netctl.service /etc/systemd/system/swg-netctl.path /etc/systemd/system/swg-netctl.timer /usr/local/bin/swg-netctl \
        /etc/systemd/system/swg-netctl-docker.service /etc/systemd/system/swg-netctl-docker.timer /usr/local/bin/swg-netctl-docker
  rm -rf /opt/swg-sub
  rm -f /etc/systemd/system/swg-panel-server.service /etc/systemd/system/swg-update.service /etc/systemd/system/swg-update.path /usr/local/bin/swg-update
  rm -rf /etc/systemd/system/swg-panel-server.service.d
  rm -f /etc/nginx/sites-enabled/swg-panel.conf /etc/nginx/sites-available/swg-panel.conf /etc/nginx/conf.d/swg-panel.conf
  command -v nginx >/dev/null 2>&1 && { nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1; } || true
  rm -rf /opt/swg-panel /usr/local/bin/swg-panel-server   # remove the bare binary too, else the box still reads as a bare panel (bootstrap won't offer convert-back)
  local _ts _d; _ts="$(date +%Y%m%d-%H%M%S 2>/dev/null || echo bak)"
  for _d in /var/lib/swg-panel /etc/swg-panel; do [ -d "$_d" ] && mv "$_d" "$_d.converted-$_ts" 2>/dev/null && seal_archive "$_d.converted-$_ts"; done
  swg_log_teardown swg-panel swg-sub.service swg-netctl.service swg-update.service   # (see there)
  systemctl daemon-reload >/dev/null 2>&1 || true; }

# ── A RECOVERY ARCHIVE IS ROOT'S ALONE ────────────────────────────────────────────────────────────────────────────────
# ⚠️ AN ARCHIVE OUTLIVES THE ACCOUNTS THAT OWN ITS FILES. A convert moves the panel's state aside WITH its owners
# (/var/lib/swg-panel.converted-*: swgpanel, group swg; /etc/swg-panel.converted-*: 2775 root:swg), the uninstall keeps it
# by default, and deletes swgpanel, swgsub and group swg — so the archive held a uid and a gid that belonged to nobody, and
# the next accounts created on the box took them: a `useradd -m -U` account (the group's gid) read the archived login hash
# and the LIVE panel's TLS key and could write into the archive, a `useradd -r` account (the panel's uid) read the LIVE
# session.key, the settings, the vault and every PSK (1.8.8 qualification, round 10, F90 — in 1.8.7 too). What an archive
# holds is recovered by root (the installers' recovery list), so it becomes root's the moment it is moved aside: owner
# root:root, no group write, no setgid, no write for others, and the archive itself closed to everyone else (700).
# seal_archives heals the ones an earlier build left — every install, update and convert calls it. TWIN: uninstall.sh
# (_seal_archive, _seal_archives — it does not source this file); change both.
SWG_ARCHIVE_GLOBS='/etc/swg-panel*.converted-* /etc/swg-panel*.uninstalled-* /var/lib/swg-panel*.converted-* /var/lib/swg-panel*.uninstalled-* /opt/swg-panel*.converted-* /opt/swg-panel*.uninstalled-* /opt/swg-panel*.pre-convert-*'
seal_archive(){   # seal_archive <path…> — never through a symlink: -h on the owner, and a link itself is skipped
  local p
  for p in "$@"; do
    [ -e "$p" ] && [ ! -L "$p" ] || continue
    chown -R -h root:root "$p" 2>/dev/null || true
    chmod -R g-ws,o-w "$p" 2>/dev/null || true
    if [ -d "$p" ]; then chmod 700 "$p" 2>/dev/null || true; fi
  done
  return 0; }
# netctl_dirs_heal <state dir> — swg-netctl's claims/ is ROOT'S (its _root_child: root-owned, 0700). The installer's
# `chown -R $PANEL_USER:swg $STATE_DIR` (and a docker → bare convert's) handed it to the panel, so the helper's next run
# moved it aside as claims.untrusted.<ts>.<pid> — one more after every install (1.8.8 qualification, round 10, F96). It goes
# back to root, and the EMPTY untrusted directories an earlier run left go (rmdir: a non-empty one stays, to be read).
netctl_dirs_heal(){ local st="${1:-}" d
  [ -n "$st" ] && [ -d "$st/netctl" ] || return 0
  if [ -d "$st/netctl/claims" ] && [ ! -L "$st/netctl/claims" ]; then
    chown -R -h root:root "$st/netctl/claims" 2>/dev/null || true; chmod 700 "$st/netctl/claims" 2>/dev/null || true
  fi
  # …and status/ is root's too (group swg reads the answers): the same chown -R took it, and the helper moved it aside
  if [ -d "$st/netctl/status" ] && [ ! -L "$st/netctl/status" ]; then
    chown root:swg "$st/netctl/status" 2>/dev/null || chown root "$st/netctl/status" 2>/dev/null || true
    chmod 750 "$st/netctl/status" 2>/dev/null || true
  fi
  for d in "$st"/netctl/claims.untrusted.* "$st"/netctl/status.untrusted.*; do
    if [ -d "$d" ] && [ ! -L "$d" ]; then rmdir "$d" 2>/dev/null || true; fi
  done
  return 0; }
seal_archives(){ local p d="${SWG_DOCKER_DIR:-}"   # …and a Docker dir moved from somewhere else (SWG_DOCKER_DIR)
  for p in $SWG_ARCHIVE_GLOBS ${d:+$d.converted-* $d.uninstalled-* $d.pre-convert-*}; do [ -e "$p" ] && seal_archive "$p"; done; return 0; }
# ⚠️ A DOCKER NODE'S nft TABLES THE HOST CANNOT READ GO WITH THE NODE'S OWN nft, BEFORE ITS CONTAINER DOES (round 12d, R29 —
# F98 on the convert path). An image older than e72529b declared its sets with plain keys, which Debian 12's nft 1.0.6 crashes
# on; left in the kernel at a docker → bare switch, the bare node — which runs the host's nft — could neither read nor change
# them: every sync logged "smart nft check" / "doh block nft load failed" / "mech block nft load failed", and routing and
# blocking edits did not apply until a reboot. So when the host's own nft cannot read the ruleset, the container is stopped
# (a running swg-noded re-creates a table within one sync), a throwaway run of its image deletes every swg* table in one
# batch — the same batch uninstall.sh's _node_nft_sweep sends (it does not source this file) — and the bare node declares
# them afresh on its first sync. A ruleset the host reads is left exactly as before: it keeps enforcing across the switch,
# and the bare node takes it over.
# ⚠️ …AND ITS INTERFACES GO BEFORE ITS TABLES (round 12e, R31-X3). wg0 is kernel WireGuard: it outlives `docker stop` and
# forwards with whatever tables the kernel holds. The teardown deleted it only after `docker rm` and the turn-proxies, so for
# ~0.3 s it forwarded with NO swg table — measured on Debian 12 probing every 10 ms: 17 replies through the reach guard and 3
# TCP connects to a Blocked address. The stopped node's interfaces (its data/node-confs names, the ones the teardown deletes)
# go first now; while one of them cannot be deleted the tables are left enforcing (fail closed: no interface, no forwarding).
lc_node_nft_sweep(){
  local d="${1:-/opt/swg-panel-docker}" img tl dels left
  command -v nft >/dev/null 2>&1 && tl="$(nft list tables 2>/dev/null)" && return 0   # (in a substitution: a crash prints no "Segmentation fault" line)
  img="$(docker inspect -f '{{.Config.Image}}' swg-node 2>/dev/null || true)"
  [ -n "$img" ] || return 0
  docker stop -t 10 swg-node >/dev/null 2>&1 || true
  left="$(lc_del_node_ifaces "$d")"
  if [ -n "$left" ]; then
    warn "this host's nft cannot read the Docker node's nft tables, and its interface(s)$left could not be deleted — the tables are left enforcing; the bare node cannot change them until a reboot"; return 0
  fi
  if ! tl="$(docker run --rm --net host --cap-add NET_ADMIN --entrypoint nft "$img" list tables 2>/dev/null)"; then
    warn "this host's nft cannot read the Docker node's nft tables, and its own nft could not either — the bare node cannot change them until a reboot"; return 0
  fi
  dels="$(printf '%s\n' "$tl" | sed -n 's/^table \([a-z0-9]*\) \(swg[A-Za-z0-9_]*\)$/delete table \1 \2/p')"
  [ -n "$dels" ] || return 0
  if printf '%s\n' "$dels" | docker run -i --rm --net host --cap-add NET_ADMIN --entrypoint nft "$img" -f - >/dev/null 2>&1; then
    info "this host's nft cannot read the Docker node's nft tables — took its interfaces down, then removed the tables with the node's own nft:$(printf '%s\n' "$dels" | sed 's/^delete table [a-z0-9]* / /' | tr -d '\n'); the bare node declares them afresh"
  else
    warn "this host's nft cannot read the Docker node's nft tables, and its own nft could not delete them — the bare node cannot change them until a reboot"
  fi
  return 0; }
# lc_del_node_ifaces <docker_dir> — docker host networking leaves the node's wg/awg interfaces in the HOST netns (`docker stop`
# and `docker rm` cannot remove them): delete the ones it managed, by the names of its confs in data/node-confs. Idempotent.
# Prints the names still there afterwards (nothing: every one is gone), for a caller that must not go on while one forwards.
lc_del_node_ifaces(){
  local d="$1" c n
  for c in "$d/data/node-confs/"*.conf; do [ -f "$c" ] || continue; n="${c##*/}"; n="${n%.conf}"
    command -v ip >/dev/null 2>&1 || { printf ' %s' "$n"; continue; }
    ip link delete dev "$n" >/dev/null 2>&1 || true
    ! ip link show "$n" >/dev/null 2>&1 || printf ' %s' "$n"; done
  return 0; }
lc_teardown_docker(){   # stop+remove the docker datapath (container + stack), freeing wg ports + host netdevs
  local d="${1:-/opt/swg-panel-docker}"
  command -v docker >/dev/null 2>&1 || return 0
  lc_node_nft_sweep "$d"   # its nft tables the host cannot read — its interfaces first — with its own nft, before the container goes
  docker rm -f swg-node >/dev/null 2>&1 || true
  for _c in $(docker ps -aq --filter name=swg-turn- 2>/dev/null || true); do docker rm -f "$_c" >/dev/null 2>&1 || true; done   # turn-proxy containers hold the listen ports the migrated bare units need
  # docker host networking leaves the node's wg/awg interfaces in the HOST netns — `docker rm` can't remove them.
  # Delete the ones it managed (names from data/node-confs) so they don't linger as confless orphans (a later
  # install would adopt one as a ghost) or collide with a fresh bring-up; whatever's still wanted is recreated after.
  # (The sweep above already deleted them when it ran: this finds them gone.)
  lc_del_node_ifaces "$d" >/dev/null
  if ! docker ps -a --format '{{.Names}}' 2>/dev/null | grep -cx swg-panel >/dev/null; then   # node-only → take the stack down
    [ -f "$d/docker-compose.yml" ] && ( cd "$d" && { docker compose down >/dev/null 2>&1 || docker-compose down >/dev/null 2>&1 || true; } )
  fi
  return 0; }   # always succeed — a missing compose file (node-only box) must not return non-zero mid-switch and trip set -e

# lc_clear_convert_leftover <baremetal|docker> [docker_dir] — on a plain (re-)install/update of one method,
# delete the inert copy an ABORTED conversion to the OTHER method left behind (no prompt — just an old copy).
# Guards keep it safe: a docker leftover is removed only when NO swg-node/swg-panel container exists; a
# bare-metal leftover only the /etc confs that MATCH this docker node's confs and only when no swg-noded is
# installed — never a live install or an unrelated WireGuard config. Needs the caller's info() for messaging.
# ⚠️ …AND NEVER WHAT AN UNINSTALL KEPT: its "keep the data" answer leaves data/ (+ .env, the node token) with the
# docker-compose.yml stripped, while a convert's staging copies the compose file in beside the data — so no compose
# file ⇒ kept, and said. TWIN of bootstrap.sh's copy of this (it does not source this file); change both.
lc_clear_convert_leftover(){
  local method="$1" dd="${2:-/opt/swg-panel-docker}" c n d cleared=
  if [ "$method" = baremetal ] && [ -d "$dd" ] && [ ! -f "$dd/docker-compose.yml" ] && command -v docker >/dev/null 2>&1 \
       && ! docker ps -a --format '{{.Names}}' 2>/dev/null | grep -cxE 'swg-(node|panel)' >/dev/null; then
    info "keeping $dd — no container runs from it, but it is not a convert's leftover: an uninstall kept its data (peers, node token) for a re-install. Delete it by hand once you no longer need it."
  elif [ "$method" = baremetal ] && [ -d "$dd" ] && command -v docker >/dev/null 2>&1 \
       && ! docker ps -a --format '{{.Names}}' 2>/dev/null | grep -cxE 'swg-(node|panel)' >/dev/null; then
    info "removing a stale docker leftover at $dd — no container present (likely a cancelled bare→docker convert); your live install is untouched"
    rm -rf "$dd" 2>/dev/null || true
  elif [ "$method" = docker ] && [ -d "$dd/data/node-confs" ] && command -v systemctl >/dev/null 2>&1 \
       && ! systemctl list-unit-files swg-noded.service >/dev/null 2>&1; then
    for c in "$dd/data/node-confs/"*.conf; do [ -f "$c" ] || continue; n="$(basename "$c" .conf)"
      for d in "/etc/amnezia/amneziawg/$n.conf" "/etc/wireguard/$n.conf"; do [ -f "$d" ] && { rm -f "$d"; cleared=1; }; done
    done
    [ -n "$cleared" ] && info "removed stale bare-metal conf leftovers — no swg-noded service present (likely a cancelled docker→bare convert); your live install is untouched"
  fi
  return 0; }   # always succeed — best-effort cleanup; "nothing to clear" must not return non-zero and trip set -e in callers

# migrate_wdtt <to-docker|to-baremetal> [docker_dir] — carry the WDTT server state between the two path conventions
# during a convert. SINGLE SOURCE OF TRUTH for both directions (this logic used to be duplicated in install-docker.sh
# + convert.sh ×2, where the copy/strip stayed in sync but the GATING drifted → a WDTT-only master silently re-minted).
# Paths:
#     bare-metal : /opt/swg-wdtt/<iface>/…               record /etc/swg-agent/wdtt.json
#     docker     : <docker_dir>/data/node/wdtt/<iface>/…  record …/data/node/wdtt.json  (→ container /var/lib/swg-noded)
# The optional THIRD argument names that node dir outright, for a container run-model whose state does not live
# under <docker_dir>/data/node — a Nix `services.swg-node.stateDir`, which defaults to bare-metal's own
# /var/lib/swg-noded. Absent, it is <docker_dir>/data/node exactly as before, so every existing call is unchanged.
# What must NOT happen is a third copy of this path map somewhere else; that duplication is what this ended.
# Each instance's wg-keys.dat is the server IDENTITY; carrying it (+ the record's node-owned owner passwords, and
# passwords.json / panel.db) is what keeps every GETCONF'd client working — a re-mint changes the server pubkey and
# forces every client to reconnect. Copy-first (the source's units are stopped / the container torn down separately,
# at the atomic switch) so a mid-convert abort never drops WDTT; the destination's reconcile then converges.
#
# STRIP (to-baremetal only): a full copy also carries the source run-model's runtime files — the `server` symlink +
# server.pid / server.log / wdtt.env / desired.json, all pointing at the source's paths. The systemd (bare) unit would
# crash-loop on that stale, container-pathed symlink before the reconcile rewrites it, so strip them here (KEEP
# wg-keys.dat / passwords.json / panel.db + the .bin binary cache). to-docker does NOT strip: the docker subprocess
# run-model reads the carried symlink as dangling (paths differ) and rewrites all of it on install — a full copy is
# both safe and simpler. Caller stops/tears down the source datapath separately (see lc_teardown_*).
migrate_wdtt(){
  local dir="$1" dd="${2:-/opt/swg-panel-docker}" nd="${3:-}" src dst srec drec _d strip=no
  [ -n "$nd" ] || nd="$dd/data/node"
  case "$dir" in
    to-docker)    src=/opt/swg-wdtt;   dst="$nd/wdtt"; srec="$(lc_bare_record wdtt.json)"; drec="$nd/wdtt.json";;
    to-baremetal) src="$nd/wdtt";      dst=/opt/swg-wdtt; srec="$nd/wdtt.json";       drec="$(lc_bare_record_all wdtt.json)"; strip=yes;;
    *) return 0;;
  esac
  [ -d "$src" ] || return 0
  # A silent `|| true` here was the worst possible failure mode: what is being carried is the server IDENTITY, and
  # a copy that quietly did nothing looks EXACTLY like a successful convert until the operator's clients stop
  # connecting to a re-minted server. Still non-fatal (a half-converted box is worse than a warned one), but loud.
  local _bad=""
  mkdir -p "$dst" || _bad="couldn't create $dst"
  [ -n "$_bad" ] || cp -a "$src/." "$dst/" || _bad="couldn't copy $src → $dst"
  if [ "$strip" = yes ] && [ -z "$_bad" ]; then
    find "$dst/." -mindepth 2 -maxdepth 2 \( -type l -name server -o -type f \( -name server.pid -o -name server.log -o -name wdtt.env -o -name desired.json \) \) -delete 2>/dev/null || true
  fi
  if [ -z "$_bad" ] && [ -f "$srec" ]; then
    for _d in $drec; do    # to-baremetal lands in BOTH the state dir and the legacy path — see lc_bare_record_all
      mkdir -p "$(dirname "$_d")" && cp -a "$srec" "$_d" || _bad="couldn't copy the WDTT record $srec → $_d"
    done
  fi
  if [ -n "$_bad" ]; then
    warn "WDTT state was NOT carried over: $_bad"
    warn "  the WDTT servers will come up with FRESH identities and existing clients will stop connecting."
    warn "  the originals are untouched in $src — copy them to $dst by hand and restart the node to recover."
    return 0
  fi
  echo "    WDTT server state (identity + config) → $dst"
  return 0; }

# migrate_csqtt <to-docker|to-baremetal> [docker_dir] — the same carry for csqtt servers. Sibling of migrate_wdtt
# rather than a shared core: the paths differ, and so does the honest failure story, which is the part that has to
# be right when it goes wrong.
# Paths:
#     bare-metal : /opt/swg-csqtt/<iface>/…                record /etc/swg-agent/csqtt.json
#     docker     : <docker_dir>/data/node/csqtt/<iface>/…   record …/data/node/csqtt.json  (→ container /var/lib/swg-noded)
# Third argument: the node dir outright, as in migrate_wdtt above.
# csqtt has NO server keypair — a password IS the credential — so nothing here can re-mint a server identity the way
# WDTT can. What must survive is each instance's STORE — passwords.json (csqtt <=2.0.1) or csqtt.db + its -wal/-shm
# sidecars (2.1.5+), which its clients authenticate against — and the
# record's NODE-OWNED owner password + pw_seen. Lose the record and the node re-mints the owner password over a store
# that still holds the old one; lose the store and every client on that server stops connecting.
# STRIP (to-baremetal only): identical reasoning to WDTT — drop the source run-model's runtime files (the `server`
# symlink + server.pid / server.log / .server.lock / csqtt.env / desired.json, all pointing at container paths) so
# the systemd unit doesn't crash-loop on them before the reconcile rewrites them. The strip is a DELETE-list, so
# anything not named survives — the store keeps working whether it is passwords.json or the csqtt.db trio — as
# does .bin (depth 3, so the depth-2 sweep can't reach the binary cache).
migrate_csqtt(){
  local dir="$1" dd="${2:-/opt/swg-panel-docker}" nd="${3:-}" src dst srec drec _d strip=no
  local bare="${CSQTT_DIR:-/opt/swg-csqtt}" brec="${CSQTT_RECORD:-$(lc_bare_record csqtt.json)}" \
        ball="${CSQTT_RECORD:-$(lc_bare_record_all csqtt.json)}"   # overridable, as in uninstall.sh
  [ -n "$nd" ] || nd="$dd/data/node"
  case "$dir" in
    to-docker)    src="$bare";      dst="$nd/csqtt"; srec="$brec";          drec="$nd/csqtt.json";;
    to-baremetal) src="$nd/csqtt";  dst="$bare";     srec="$nd/csqtt.json"; drec="$ball"; strip=yes;;
    *) return 0;;
  esac
  [ -d "$src" ] || return 0
  local _bad=""
  mkdir -p "$dst" || _bad="couldn't create $dst"
  [ -n "$_bad" ] || cp -a "$src/." "$dst/" || _bad="couldn't copy $src → $dst"
  if [ "$strip" = yes ] && [ -z "$_bad" ]; then
    find "$dst/." -mindepth 2 -maxdepth 2 \( -type l -name server -o -type f \( -name server.pid -o -name server.log -o -name .server.lock -o -name csqtt.env -o -name desired.json \) \) -delete 2>/dev/null || true
  fi
  if [ -z "$_bad" ] && [ -f "$srec" ]; then
    for _d in $drec; do    # to-baremetal lands in BOTH the state dir and the legacy path — see lc_bare_record_all
      mkdir -p "$(dirname "$_d")" && cp -a "$srec" "$_d" || _bad="couldn't copy the csqtt record $srec → $_d"
    done
  fi
  if [ -n "$_bad" ]; then
    warn "csqtt state was NOT carried over: $_bad"
    warn "  the csqtt servers will come up with a FRESH owner password and existing clients will stop connecting."
    warn "  the originals are untouched in $src — copy them to $dst by hand and restart the node to recover."
    return 0
  fi
  echo "    csqtt server state (passwords + config) → $dst"
  return 0; }

# migrate_turn_record <to-docker|to-baremetal> [docker_dir] [node_dir] — carry the turn-proxy RECORD, and only that.
#     bare-metal : /etc/swg-agent/turn-proxy.json      docker : <node_dir>/turn-proxy.json
# Deliberately NOT the sibling of migrate_wdtt/migrate_csqtt in what it promises. A turn-proxy has no identity to
# lose — it is a stateless byte-shuffler, and its listen/connect/params ARE the record — so the whole carry is one
# file. What differs is what each run-model does with it afterwards, and that difference is the reason this cannot
# silently stand in for the convert's turn migration:
#   to-docker    the record IS the config (load_turn_proxies returns it as-is on a container node) and swg-noded's
#                background reconcile recreates each container from it, downloading the binary. Carrying it is enough.
#   to-baremetal a bare node reads its turn set from the UNITS ON DISK and drops record entries with no unit, so the
#                record alone shows nothing on the panel until each proxy is re-created. install-node.sh's
#                migrate_docker_turns writes those units (it downloads the binary per fork); this does not, and says so
#                at the call site.
migrate_turn_record(){
  local dir="$1" dd="${2:-/opt/swg-panel-docker}" nd="${3:-}" src dst
  [ -n "$nd" ] || nd="$dd/data/node"
  case "$dir" in
    to-docker)    src="$(lc_bare_record turn-proxy.json)"; dst="$nd/turn-proxy.json";;
    to-baremetal) src="$nd/turn-proxy.json";               dst="$(lc_bare_record_all turn-proxy.json)";;
    *) return 0;;
  esac
  [ -f "$src" ] || return 0
  local _d
  for _d in $dst; do
    [ "$src" = "$_d" ] && continue
    mkdir -p "$(dirname "$_d")" && cp -a "$src" "$_d" \
      || { warn "the turn-proxy record was NOT carried over ($src -> $_d) — the panel will show no turn-proxies for this node until they are re-created"; continue; }
    echo "    turn-proxy record (listen/connect/fork) -> $_d"
  done
  return 0; }

# stop_bare_csqtt — bring down every bare-metal csqtt server so it stops holding its port, TUN device and store.
# A convert to docker hands those instances to a supervised child inside the container; leave the host units running
# and the two fight over the same listen port and iface name, with the panel reporting whichever answered last.
# Units only — the config-dir is carried by migrate_csqtt and removed by nothing here.
stop_bare_csqtt(){
  local unit name n=0 sd="${SYSTEMD_DIR:-/etc/systemd/system}"
  for unit in $(ls "$sd"/swg-csqtt-*.service 2>/dev/null || true); do
    name="$(basename "$unit" .service)"
    systemctl disable --now "$name" >/dev/null 2>&1 || true
    ip link delete dev "${name#swg-csqtt-}" >/dev/null 2>&1 || true   # the raw TUN outlives the process
    rm -f "$unit"; n=$((n+1))
  done
  [ "$n" -gt 0 ] && { systemctl daemon-reload >/dev/null 2>&1 || true; echo "    stopped $n bare-metal csqtt server(s) — the container owns them now"; }
  return 0; }

# ── turn-proxy: the binary download (GitHub direct, then opt-in mirrors) ──

# Axis-2 P3: systemd sandbox for turn-proxy units — shared by install-host/node + convert (mirrors swg-noded's
# TURN_UNIT_HARDENING). A forwarder only shuffles bytes between two sockets, so confine it hard: a compromised
# fork binary is contained to its sockets, not root. Injected into the unit's [Service] via $TURN_HARDENING.
# ⚠️ SystemCallFilter=@system-service is the one that could refuse an odd Go syscall — first suspect if a proxy
# won't start after install (check `swg-logs turn <instance>` for a seccomp kill).
TURN_HARDENING='NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK
RestrictNamespaces=yes
RestrictSUIDSGID=yes
LockPersonality=yes
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM'
dl_turn_bin(){ local owner="$1" arch="$2" out="$3" base url m; base="https://github.com/$owner/releases/latest/download/server-linux-$arch"
  for url in "$base" $(for m in ${SWG_TURN_MIRROR:-}; do printf '%s ' "${m%/}/$base"; done); do
    curl -fsSL --connect-timeout 20 --max-time 240 --retry 3 --retry-delay 3 --retry-all-errors "$url" -o "$out" && return 0
  done; return 1; }

# ── reverse-proxy config generation (shared by install-host "skip" mode + install-docker TLS=none) ──
# The operator runs their own nginx/Caddy; we bind the panel + swg-sub to loopback and PRINT ready configs
# (installing nothing). gen_proxy_conf writes ONE config to stdout; print_proxy_configs saves both + echoes.
#   gen_proxy_conf nginx|caddy <panel_domain> <panel_target> <panel_base> <sub_domain> <sub_target>
#   <panel_target>/<sub_target> = host:port the proxy forwards to (e.g. 127.0.0.1:8088). <sub_domain> "" → no sub block.
gen_proxy_conf(){
  local kind="$1" pd="$2" pt="$3" pbase="$4" sd="$5" st="$6" loc="/"
  [ -n "$pbase" ] && loc="${pbase}/"
  if [ "$kind" = nginx ]; then
    cat <<EOF
# swg-panel reverse proxy for nginx. Get certificates first, e.g.:
#   certbot --nginx -d ${pd}${sd:+ -d $sd}
server {                                     # redirect HTTP -> HTTPS
    listen 80;
    server_name ${pd}${sd:+ $sd};
    location / { return 301 https://\$host\$request_uri; }
}
server {                                     # admin panel
    listen 443 ssl http2;
    server_name ${pd};
    ssl_certificate     /etc/letsencrypt/live/${pd}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${pd}/privkey.pem;
    client_max_body_size 4m;
    location ${loc} {
        proxy_pass http://${pt};
        proxy_set_header Host \$http_host;   # \$http_host keeps the PORT; \$host strips it, and the address-change confirm compares Host against host:port
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    [ -n "$sd" ] && cat <<EOF
server {                                     # subscription page (public, read-only)
    listen 443 ssl http2;
    server_name ${sd};
    ssl_certificate     /etc/letsencrypt/live/${sd}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${sd}/privkey.pem;
    client_max_body_size 2m;
    location / {
        proxy_pass http://${st};
        proxy_set_header Host \$http_host;   # \$http_host keeps the PORT; \$host strips it, and the address-change confirm compares Host against host:port
        proxy_set_header X-Forwarded-For \$remote_addr;   # swg-sub trusts this only with SWG_SUB_TRUST_XFF=1 (set in reverse-proxy installs)
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  else   # caddy — auto-HTTPS
    cat <<EOF
# swg-panel reverse proxy for Caddy (auto-HTTPS). Point DNS at this host first.
${pd} {
$( [ -n "$pbase" ] && printf '    handle %s/* {\n        reverse_proxy %s\n    }' "$pbase" "$pt" || printf '    reverse_proxy %s' "$pt" )
}
EOF
    [ -n "$sd" ] && cat <<EOF
${sd} {
    reverse_proxy ${st}
}
EOF
  fi
}

# print_proxy_configs <out_dir> <panel_domain> <panel_target> <panel_base> <sub_domain> <sub_target>
print_proxy_configs(){
  local dir="$1" pd="$2" pt="$3" pbase="$4" sd="$5" st="$6"
  mkdir -p "$PREFIX$dir"
  gen_proxy_conf nginx "$pd" "$pt" "$pbase" "$sd" "$st" > "$PREFIX$dir/swg-nginx.conf"
  gen_proxy_conf caddy "$pd" "$pt" "$pbase" "$sd" "$st" > "$PREFIX$dir/swg-Caddyfile"
  chmod 644 "$PREFIX$dir/swg-nginx.conf" "$PREFIX$dir/swg-Caddyfile" 2>/dev/null || true
  echo; ok "Reverse-proxy configs saved to ${dir}/ — nothing was installed or reloaded."
  sub "Panel  → ${pt}${pbase}"
  [ -n "$sd" ] && sub "Sub    → ${st}   (${sd})"
  echo; echo "  $(b "── nginx ──  ${dir}/swg-nginx.conf")"; gen_proxy_conf nginx "$pd" "$pt" "$pbase" "$sd" "$st" | sed 's/^/    /'
  echo; echo "  $(b "── Caddy ──  ${dir}/swg-Caddyfile")"; gen_proxy_conf caddy "$pd" "$pt" "$pbase" "$sd" "$st" | sed 's/^/    /'
  echo
}

# ── THE swg-update WRAPPER, AND A BARE BOX'S CHECK: ONE TEXT EACH ──────────────────────────────────────────────────────
# install-host.sh (mk_update_unit), update.sh (install_update_unit) and write_docker_updater (below) each carried the same
# code under their own comments, so /usr/local/bin/swg-update's digest flipped with whichever wrote it last (1.8.8
# qualification, round 8). The texts live here, once; every writer renders them. The wrapper takes the ref the box
# follows (baked in: nothing else on the box records it). The check is a BARE box's (install-host, update.sh): a Docker
# box writes its own in write_docker_updater — there a node's trigger is the container's, which --node-only would skip.
swg_update_wrapper_text(){ local _swg_ref="${1:-main}"
  cat <<WRAP
#!/usr/bin/env bash
# ⚠️ THE WHOLE BODY IS ONE COMPOUND COMMAND, AND THE \`exit\` AT THE END IS PART OF THE FIX.
# THIS SCRIPT REWRITES ITSELF. The update it runs re-bakes /usr/local/bin/swg-update, and bash reads a
# script INCREMENTALLY — so when the pipeline returned, bash went back to the file for the next command at
# the byte offset it had reached, landed in the middle of the NEW file's last line, and ran the tail of a
# comment. Measured on swgt at the end of a completely successful panel update:
#     /usr/local/bin/swg-update: line 15: pass: command not found
# — from \`# extra flags (e.g. --node-only) pass through\`, in a file that is only 14 lines long. Under
# \`set -e\` that is a non-zero exit after the update has already reported success, so a real update ends by
# announcing a failure that did not happen. It fires ONLY when something is actually installed, which is
# why a second run looks clean and why this survived every dry run.
# Braces make bash parse the whole body before executing any of it, and the \`exit\` means it never reads
# from the file again.
{
# swg-update — fixed root entrypoint for the one-click in-place update of EVERY swg component on this box: a bare
# panel, a bare node, a Docker install (a container cannot recreate itself: the panel/node touches its trigger and this
# host unit runs \`compose pull && up\`). swg programs + images only (--no-components: never the docker engine, wg/awg
# or turn-proxies). Logs to journal. ONE TEXT for every writer — swg_update_wrapper_text, lib/common.sh.
set -euo pipefail
# ⚠️ EXPORTED, not just used. \`bootstrap.sh\` derives the ref from the URL IT WAS FETCHED FROM, reading
# \$SWG_BOOTSTRAP_URL out of its own environment. Baked in only as a shell DEFAULT, the piped bash sees the variable
# UNSET, infers nothing and falls back to \`main\`: the wrapper fetched dev's bootstrap, installed main from it and
# re-baked this very file back to main (measured on swgt: 1.8.6-beta -> 1.8.5-beta, wrapper dev -> main, on one press
# of Update; and on a box installed FRESH from a branch). Exporting the URL (rather than forcing SWG_REF) keeps an
# operator's own \$SWG_BOOTSTRAP_URL authoritative — their URL then decides the ref.
URL="\${SWG_BOOTSTRAP_URL:-https://raw.githubusercontent.com/SanityProtocol/swg-panel/${_swg_ref}/bootstrap.sh}"
export SWG_BOOTSTRAP_URL="\$URL"
# ⚠️ DOWNLOADED FIRST, RUN SECOND — AND A SECOND DOOR WHEN RAW CANNOT BE HAD. tests/update_bootstrap_fallback_selftest.py
# runs this text, and every writer of it.
# \`curl | bash\` executes whatever arrived before the connection died, so a reset halfway through bootstrap.sh
# ran half of it. A file is run only once curl says the whole of it arrived.
# raw.githubusercontent.com resolves into the address range filtered in the networks this product is most used
# in, and api.github.com does not (docs/UPDATE-RESILIENCE-PLAN.md, 0a). This one file is the ONLY thing an
# update reads from raw — bootstrap.sh fetches the tree from github.com itself — so reading it through the API
# is what lets a filtered box update at all. Same repo, same ref, same TLS: nothing new to trust. Only a GitHub
# raw URL has that door; an operator's own SWG_BOOTSTRAP_URL mirror is not handed a source it never named.
B="\$(mktemp)"; trap 'rm -f "\$B"' EXIT
API="\$(printf '%s' "\$URL" | sed -nE 's#^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/([^?#]+).*#https://api.github.com/repos/\1/\2/contents/\4?ref=\3#p')"
if ! curl -fsSL --connect-timeout 20 --max-time 120 "\$URL" -o "\$B"; then
  [ -n "\$API" ] || exit 1
  echo "swg-update: could not fetch bootstrap.sh from \$URL — trying api.github.com" >&2
  curl -fsSL --connect-timeout 20 --max-time 120 -H 'Accept: application/vnd.github.raw' "\$API" -o "\$B"
fi
bash "\$B" update -y --no-components "\$@"   # extra flags (e.g. --node-only) pass through
exit
}
WRAP
}
swg_update_check_text(){ cat <<'WRAP2'
#!/usr/bin/env bash
set -euo pipefail
STAMP=/var/lib/swg-update.stamp
PANEL_TRIGGERS="/var/lib/swg-panel/.update-request /opt/swg-panel-docker/data/lib/.update-request"
NODE_TRIGGERS="/var/lib/swg-noded/.update-request /opt/swg-panel-docker/data/node/.update-request"
_run=no; _panel=no
for _t in $PANEL_TRIGGERS $NODE_TRIGGERS; do
  [ -f "$_t" ] || continue
  if { [ ! -e "$STAMP" ] || [ "$_t" -nt "$STAMP" ]; }; then
    _run=yes
    case " $PANEL_TRIGGERS " in *" $_t "*) _panel=yes;; esac   # a PANEL trigger → this is a host update
  fi
done
[ "$_run" = yes ] || exit 0
touch "$STAMP"            # mark this batch handled BEFORE updating, so we never loop
# Only a NODE trigger fired (no panel trigger) → update JUST the node: --node-only keeps the update off the
# panel's host_proc, so a co-located node self-updating doesn't light up "up to date" on the panel header.
if [ "$_panel" = yes ]; then exec /usr/local/bin/swg-update
else exec /usr/local/bin/swg-update --node-only; fi
WRAP2
}
# A Docker box's check, service and timer: ONE TEXT each, which write_docker_updater writes and update.sh's
# ensure_update_unit_docker compares with what the box has (a box upgraded from an older release kept that release's
# texts: they were written only when missing — 1.8.8 qualification, round 10, N12).
swg_update_check_docker_text(){ cat <<'WRAP2'
#!/usr/bin/env bash
set -euo pipefail
STAMP=/var/lib/swg-update.stamp
_run=no
for _t in /var/lib/swg-panel/.update-request /var/lib/swg-noded/.update-request /opt/swg-panel-docker/data/lib/.update-request /opt/swg-panel-docker/data/node/.update-request; do
  [ -f "$_t" ] || continue
  { [ ! -e "$STAMP" ] || [ "$_t" -nt "$STAMP" ]; } && _run=yes
done
[ "$_run" = yes ] || exit 0
touch "$STAMP"            # mark this batch handled BEFORE updating, so we never loop
exec /usr/local/bin/swg-update
WRAP2
}
swg_update_docker_service_text(){ cat <<'UNIT'
[Unit]
Description=swg-panel one-click self-update (swg programs only)

[Service]
Type=oneshot
ExecStart=/usr/local/bin/swg-update-check
UNIT
}
swg_update_docker_timer_text(){ cat <<'UNIT'
[Unit]
Description=poll for a swg-panel one-click update request (docker)

[Timer]
OnActiveSec=30s
OnUnitActiveSec=30s

[Install]
WantedBy=timers.target
UNIT
}
# ── docker one-click self-update wiring (STATIC templates — no per-install config) ──────────────────────────────
# The swg-update + swg-update-check wrappers and the poll service/timer. Shared by install-docker.sh's
# wire_host_updater (fresh install) AND update.sh's ensure_update_unit_docker (heal) so both write byte-identical
# pieces. Writes the files, retires the legacy .path watch, stamps NOW (so the first poll can't fire a spurious
# update), reloads systemd, and enables the 30s timer. Caller owns $DRYRUN gating + container trigger pre-creation.
# systemctl calls are best-effort so this never trips set -e. Returns 0.
write_docker_updater(){
    # ⚠️ THE REF THE BOX WAS INSTALLED FROM, not `main`. `bootstrap.sh` deliberately supports installing a
  # branch or tag (SWG_REF, or inferred from the URL it was fetched from) — and its own comment says why:
  # "a panel tracking a pre-release branch SILENTLY DOWNGRADED itself on every one-click update". That fix
  # covered the bootstrap and NOT this wrapper, which is the thing the Update button actually runs. Baked in
  # at write time because nothing else on the box records the branch, and this file IS rewritten by every
  # update — so a box installed from a ref keeps tracking it without any new state to keep in step.
  _swg_ref="${SWG_REF:-main}"
  # ⚠️ WRITTEN BESIDE, THEN RENAMED. Same reason as update.sh's `install_update_unit`, which this must stay
  # identical to: the braces + `exit` below cannot help the one press of Update that INSTALLS them, because
  # the script running then is the old unguarded wrapper and `cat >` refills the very inode its bash still
  # holds open. A rename gives the new file a new inode, so the old bash reads EOF and exits 0.
  swg_update_wrapper_text "$_swg_ref" > /usr/local/bin/swg-update.new   # the one text (above)
  chmod 755 /usr/local/bin/swg-update.new
  mv -f /usr/local/bin/swg-update.new /usr/local/bin/swg-update   # see the rename note above — NEVER `cat >`
  # The trigger files are written by the panel/node CONTAINER through a bind mount, and inotify does NOT cross that
  # bind mount — a host `.path` unit (PathModified) NEVER sees the container's write. So we POLL the trigger mtimes
  # from the host instead (stat across the bind mount works — it's a shared inode). A timer runs this every 30s.
  swg_update_check_docker_text > /usr/local/bin/swg-update-check   # the one text (above)
  chmod 755 /usr/local/bin/swg-update-check
  swg_update_docker_service_text > /etc/systemd/system/swg-update.service
  swg_update_docker_timer_text > /etc/systemd/system/swg-update.timer
  systemctl disable --now swg-update.path >/dev/null 2>&1 || true   # retire the old inotify watch from a pre-poll install
  rm -f /etc/systemd/system/swg-update.path
  touch /var/lib/swg-update.stamp   # stamp NOW (newer than any just-created triggers) so the first poll doesn't fire a spurious update
  systemctl daemon-reload 2>/dev/null || true
  systemctl enable --now swg-update.timer >/dev/null 2>&1 || true
  return 0
}

# ── THE PANEL PASSWORD LEAVES THE DOCKER .env ONCE THE PANEL HOLDS IT ──────────────────────────────────────────────────
# A Docker panel's login lives in data/etc/auth (pbkdf2) from its first start on — the entrypoint writes it from .env's
# PANEL_PASSWORD only when that file is missing. Yet a fresh install left the password there in plain text (0600, root)
# until the next re-install replaced it with the placeholder (1.8.8 qualification, round 9b). Once the login VERIFIES
# against .env's value, the value goes: "(preserved)" — the placeholder a re-install writes — and one line says so. Every
# later flow reads the login, not the value: a re-install keeps a login it has no password for (install-docker.sh, KEPT
# LOGIN), an update recreates onto the same auth, a convert to bare metal carries data/etc/auth, a keep-data uninstall
# strips the line; compose only needs it non-empty. A placeholder is NEVER a password: the entrypoint refuses to mint a
# login from one (docker/entrypoint.sh), and a re-install with no login left generates a new one instead.
DOCKER_PW_PLACEHOLDERS="(preserved) converted-login-preserved unused-on-node-only"
# login_holds <auth file> <user> <password> — 0 when the login file's user is <user> and its pbkdf2 hash verifies <password>
login_holds(){ [ -s "${1:-}" ] && have python3 || return 1
  SWG_LU="${2:-}" SWG_PW="${3:-}" python3 - "$1" <<'PYLH' 2>/dev/null
import base64, hashlib, hmac, os, sys
try:
    u, h = open(sys.argv[1]).readline().strip().split(":", 1)
    scheme, it, salt, dig = h.split("$")
    ok = u == os.environ["SWG_LU"] and scheme == "pbkdf2_sha256" and hmac.compare_digest(
        hashlib.pbkdf2_hmac("sha256", os.environ["SWG_PW"].encode(), base64.b64decode(salt), int(it)), base64.b64decode(dig))
except Exception:
    ok = False
sys.exit(0 if ok else 1)
PYLH
}
docker_pw_placeholder(){ local p; [ -n "${1:-}" ] || return 0
  for p in $DOCKER_PW_PLACEHOLDERS; do [ "$1" = "$p" ] && return 0; done; return 1; }
# docker_env_forget_password <install dir> [<seconds to wait for the panel to take its login>]
docker_env_forget_password(){
  local d="${1:-}" w="${2:-0}" t0 v
  [ -f "$d/.env" ] && have python3 || return 0
  v="$(sed -n 's/^PANEL_PASSWORD=//p' "$d/.env" | sed -n 1p)"
  case "$v" in \"*\") v="${v#\"}"; v="${v%\"}";; \'*\') v="${v#\'}"; v="${v%\'}";; esac
  docker_pw_placeholder "$v" && return 0
  t0="$(date +%s)"
  until SWG_PW="$v" python3 - "$d/data/etc/auth" <<'PYPW' 2>/dev/null; do
import base64, hashlib, hmac, os, sys
try:
    _u, h = open(sys.argv[1]).readline().strip().split(":", 1)
    scheme, it, salt, dig = h.split("$")
    ok = scheme == "pbkdf2_sha256" and hmac.compare_digest(
        hashlib.pbkdf2_hmac("sha256", os.environ["SWG_PW"].encode(), base64.b64decode(salt), int(it)), base64.b64decode(dig))
except Exception:
    ok = False
sys.exit(0 if ok else 1)
PYPW
    if [ "$(( $(date +%s) - t0 ))" -ge "$w" ]; then
      info "the panel's login does not hold the password in $d/.env yet — it stays there (0600) until an update or a re-install finds the panel holding it"
      return 0
    fi
    sleep 2
  done
  python3 - "$d/.env" <<'PYENV' 2>/dev/null || { warn "couldn't take the panel password out of $d/.env — it stays there (0600)"; return 0; }
import os, sys
p = sys.argv[1]
lines = open(p).read().split("\n")
done = False
for i, ln in enumerate(lines):
    if ln.startswith("PANEL_PASSWORD=") and not done:
        lines[i] = "PANEL_PASSWORD=(preserved)"; done = True
if not done:
    sys.exit(1)
tmp = p + ".tmp"
with open(tmp, "w") as f:
    f.write("\n".join(lines))
os.chmod(tmp, 0o600)
os.replace(tmp, p)
PYENV
  info "the panel holds its login now — its password is no longer kept in $d/.env (a re-install and an update keep the login; to change it: the panel's Account screen, or docker exec -it swg-panel swg-passwd)"
  return 0
}
# ── docker: pre-create the secret files swg-sub masks with /dev/null (docker-compose.yml) ───────────────────────
# swg-sub bind-mounts /dev/null over the panel's auth/panel-settings/vault/escrow so the public surface can never
# read them. Docker needs the mount TARGET to already exist, and swg-sub mounts /etc/swg-panel + /var/lib/swg-panel
# READ-ONLY — so on a FRESH install (files not yet written by the panel) docker can't create the mountpoint and
# swg-sub dies with "read-only file system". Pre-create empty placeholders before `compose up`: the panel's load_json
# treats an empty file as its default, and the entrypoint overwrites auth from PANEL_PASSWORD. Idempotent — an
# existing install already has these files, so this is a no-op (backwards compatible). $1 = install dir.
ensure_docker_mask_files(){
  local d="${1:-}" f; [ -n "$d" ] || return 0
  mkdir -p "$d/data/etc" "$d/data/lib/subs" 2>/dev/null || true
  for f in data/etc/auth data/lib/panel-settings.json data/lib/subs/vault.json data/lib/subs/escrow.json; do
    [ -e "$d/$f" ] || : > "$d/$f" 2>/dev/null || true
  done
  return 0
}

ensure_swap(){ # PANEL-HOST: a low-RAM box with NO active swap OOM-kills the panel on a transient list-resolve spike (a
  # big domain feed peaks a few hundred MB). Add a right-sized swapfile so spikes go to disk, not the OOM-killer.
  # Idempotent, best-effort (never aborts — set-e safe via if-guards), dry-run aware. Self-contained (plain echo +
  # the $DRYRUN global) so install-host and update can both call it. Nodes pull lists (never resolve) → they don't.
  local active memmb freemb sizemb
  active=$(awk 'NR>1{s+=$3} END{print s+0}' /proc/swaps 2>/dev/null || echo 0)
  if [ "${active:-0}" -gt 0 ] 2>/dev/null; then echo "  ✓ swap already active — skipping"; return 0; fi
  memmb=$(( $(awk '/^MemTotal:/{print $2}' /proc/meminfo 2>/dev/null || echo 0) / 1024 ))
  if [ "$memmb" -ge 2048 ]; then echo "  · RAM ${memmb}MB — swap not needed"; return 0; fi
  if [ -e /swapfile ]; then echo "  ! /swapfile exists but no active swap — leaving it alone"; return 0; fi
  freemb=$(( $(df -Pk / 2>/dev/null | awk 'NR==2{print $4}' || echo 0) / 1024 ))
  if   [ "$freemb" -gt 4096 ]; then sizemb=2048
  elif [ "$freemb" -gt 2560 ]; then sizemb=1024
  else echo "  ! only ${freemb}MB free on / — not adding swap (this ${memmb}MB box stays OOM-prone; add swap manually)"; return 0; fi
  if [ "${DRYRUN:-false}" = true ]; then echo "    [skip] create ${sizemb}MB /swapfile + swapon + fstab + vm.swappiness=10"; return 0; fi
  echo "  ✓ adding ${sizemb}MB swap (${memmb}MB RAM, none active) — bounds panel list-resolve spikes"
  if { fallocate -l "${sizemb}M" /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count="$sizemb" status=none; } \
       && chmod 600 /swapfile && mkswap /swapfile >/dev/null 2>&1 && swapon /swapfile 2>/dev/null; then
    grep -qs '/swapfile' /etc/fstab || printf '%s\n' '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl -qw vm.swappiness=10 >/dev/null 2>&1 || true
    grep -qs 'vm.swappiness' /etc/sysctl.conf || printf '%s\n' 'vm.swappiness=10' >> /etc/sysctl.conf
    echo "  ✓ swap active ($(free -m 2>/dev/null | awk '/Swap/{print $2}')MB, swappiness 10)"
  else
    echo "  ! swap setup failed — continuing (box remains OOM-prone until swap is added)"; rm -f /swapfile 2>/dev/null || true
  fi
  return 0
}

# guard_second_panel <baremetal|docker> — the method being installed. TWO PANELS ON ONE BOX. A bare-metal panel and a
# Docker panel keep separate state (/var/lib/swg-panel vs the compose ./data), so the state-dir lock cannot see one from
# the other, and both can be live behind the same address: Docker's port forward catches outside traffic while the host
# process answers another path, or each answers one address family. The browser then shows one fleet on one load and the
# other on the next, and saves land on whichever answered — reported from a client's master (2026-09-24: the node picker
# read 1/1, then 2/2). bootstrap.sh's cross-method prompt only fires when THIS method is missing the part, so a box that
# already had both went through it, and running an installer directly skipped it. Called before the panel is (re)started.
# A convert owns its own switch-over (it stops the old side), so it is exempt. Unattended: SWG_OTHER_PANEL=stop|keep|abort;
# with neither a terminal nor that, it refuses — the same contract as bootstrap.sh's prompts.
# PARKED = stopped by guard_second_panel below, and it must STAY stopped: update.sh asks these before it restarts a
# bare panel or recreates a docker stack. Read from state the guard leaves (a disabled, inactive unit; a stopped
# container with restart=no — compose never writes restart=no), not a marker file that could outlive the facts.
# ⚠️ DISABLED IS THE DECISION; "inactive" IS ONLY WHETHER SOMETHING UNDID IT. 1.8.7's update.sh restarted
# swg-panel-server unconditionally (and enabled + restarted swg-sub), so a box that went back to 1.8.7 and came forward
# again had its parked panel DISABLED but ACTIVE — "not parked" to the old test, which restarted it once more, and two
# panels answered at one address for good. A disabled unit beside a LIVE docker panel is that park, and counts; a
# disabled unit with nothing beside it that is running anyway is the operator's own doing and is left to run.
bare_panel_parked(){ systemctl is-enabled --quiet swg-panel-server 2>/dev/null && return 1
  ! systemctl is-active --quiet swg-panel-server 2>/dev/null || docker_panel_live; }
docker_parked(){ [ "$(docker inspect -f '{{.State.Running}} {{.HostConfig.RestartPolicy.Name}}' "$1" 2>/dev/null)" = "false no" ]; }
docker_panel_live(){ command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -cx swg-panel >/dev/null && ! docker_parked swg-panel; }
guard_second_panel(){
  [ -n "${SWG_CONVERT_DIR:-}" ] && return 0
  local me="$1" what="" live=no ans="" _c
  if [ "$me" = baremetal ]; then
    command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -cx swg-panel >/dev/null || return 0
    what="a Docker panel (container swg-panel)"
    { docker ps --format '{{.Names}}' 2>/dev/null | grep -cx swg-panel >/dev/null \
      || [ "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' swg-panel 2>/dev/null)" = always ]; } && live=yes
  else
    [ -f /etc/systemd/system/swg-panel-server.service ] || return 0
    what="a bare-metal panel (swg-panel-server.service)"
    { systemctl is-active --quiet swg-panel-server 2>/dev/null || systemctl is-enabled --quiet swg-panel-server 2>/dev/null; } && live=yes
  fi
  if [ "$live" != yes ]; then
    echo "  · $what is also installed here, stopped and not set to start — leaving it alone (the uninstaller removes it)"
    return 0
  fi
  echo
  echo "  ! $what is already running on this box, with its OWN servers, users and settings."
  echo "    Installing a second panel beside it makes both answer — the browser shows whichever one replies, and"
  echo "    changes saved on one never reach servers that sync to the other."
  echo "    To MOVE to $( [ "$me" = baremetal ] && echo bare-metal || echo docker ) keeping everything, abort and run bootstrap.sh with that method — it converts."
  echo "    A server on this box that syncs to the one you stop keeps its peers but gets no changes until it is enrolled here."
  if [ "${DRYRUN:-false}" = true ]; then echo "    [skip] dry run — would ask: abort / stop the other / keep both"; return 0; fi
  echo "      [a]bort              exit without changing anything (default)"
  echo "      [s]top the other     stop it and its subscription server (swg-sub), and keep both from starting again (its data stays on disk; nothing is deleted)"
  echo "      [k]eep both          continue anyway"
  ans="${SWG_OTHER_PANEL:-}"
  # a preset answer is said, not taken in silence under a menu whose "(default)" it overrides (1.8.8 qualification)
  [ -n "$ans" ] && echo "  Abort, stop the other, or keep both [a/s/k]: $(b "$ans")  (given by SWG_OTHER_PANEL — not asked)"
  if [ -z "$ans" ]; then
    printf '  Abort, stop the other, or keep both [a/s/k]: ' 2>/dev/null >/dev/tty || printf '  Abort, stop the other, or keep both [a/s/k]: '
    read -r ans 2>/dev/null <"${SWG_TTY:-/dev/tty}" || { echo; echo "  ✗ no interactive input — run from a terminal (ssh -t), or set SWG_OTHER_PANEL=stop|keep|abort"; exit 1; }
  fi
  case "$ans" in
    s|S|stop)
      if [ "$me" = baremetal ]; then
        for _c in swg-sub swg-panel; do   # the panel and the subscription server that belongs to it (a node container is left alone)
          docker update --restart=no "$_c" >/dev/null 2>&1 || true; docker stop "$_c" >/dev/null 2>&1 || true
        done
      else
        # …and the subscription server that belongs to it, as the Docker branch above stops both containers: left
        # running it serves that panel's subscription pages from a store nothing updates any more, on the port the
        # Docker stack's own swg-sub publishes (8444 by default)
        systemctl disable --now swg-panel-server swg-sub >/dev/null 2>&1 || true
      fi
      echo "  ✓ stopped $what and its subscription server (swg-sub) — its data is still on disk"; return 0;;   # both branches stop swg-sub too — say so
    k|K|keep) echo "  · keeping both — two panels will answer on this box"; return 0;;
    *) echo "  ✗ aborted — nothing was changed"; exit 1;;
  esac
}

# seed_access_settings <panel-settings.json path> — merge this run's Access & TLS answers into the panel's own
# settings file. panel-settings.json lives in the STATE dir, which an uninstall KEEPS by default, so a fresh
# install onto a kept state dir would otherwise show the PREVIOUS install's address/TLS in Settings → Access (or
# blanks on a first install), contradicting what is actually running. The panel is the source of truth once the
# operator edits it there (it writes install.conf / .env back via swg-netctl); this just makes the two agree from
# the start. MERGE, never rewrite. Caller exports PANEL_DOMAIN / PANEL_BASE / PORT / TLS_MODE / ACME_EMAIL /
# CF_TOKEN / CF_ORIGIN_TOKEN. Was copy-pasted into install-host.sh and install-docker.sh, identical but for the path.
seed_access_settings(){
  have python3 || { warn "couldn't seed Access settings (no python3) — set them in Settings → Access & TLS"; return 0; }
  mkdir -p "$(dirname "$1")" 2>/dev/null || true
  python3 - "$1" <<'PYACC' || warn "couldn't seed Access settings — set them in Settings → Access & TLS"
import json, os, sys
p = sys.argv[1]
try:
    with open(p) as f: d = json.load(f)
except Exception:
    d = {}
if not isinstance(d, dict): d = {}
dom  = (os.environ.get("PANEL_DOMAIN") or "").strip()
base = (os.environ.get("PANEL_BASE") or "").strip().rstrip("/")
port = (os.environ.get("PORT") or "").strip()
acc  = d.setdefault("access", {})
pan  = acc.setdefault("panel", {}); tls = acc.setdefault("tls", {})
if dom:
    host = dom if "://" in dom else "https://" + dom            # the operator may have typed a scheme
    if port and port not in ("443", "80") and ":" not in host.split("://", 1)[1]:
        host += ":" + port
    pan["url"] = host + (base or "")
if port.isdigit(): pan["port"] = int(port)
pan["base"] = (base or "/")
# behind a reverse proxy the panel serves plain HTTP, and "" (None — reverse proxy) is its TLS type: the installer's
# "skip" / "none" / the proxy's certificate mode seeded here was rolled back by the panel's first start (N4)
tls["mode"]  = "" if os.environ.get("PROXIED") == "yes" else (os.environ.get("TLS_MODE") or tls.get("mode") or "").strip()
tls["email"] = (os.environ.get("ACME_EMAIL") or tls.get("email") or "").strip()
for k, e in (("cf_token", "CF_TOKEN"), ("cf_origin_token", "CF_ORIGIN_TOKEN")):
    v = (os.environ.get(e) or "").strip()
    if v: tls[k] = v                                            # keep an existing token when this run didn't supply one
tmp = p + ".tmp"
with open(tmp, "w") as f: json.dump(d, f, indent=2)
os.replace(tmp, p)
PYACC
  return 0; }

# migrate_node_state <to-docker|to-baremetal> [docker_dir] [node_dir] — carry the node's HOST-LOCAL derived state between the
# two path conventions during a convert: the per-interface keypair backups (the server-key revert baseline) and the
# routing lists pulled from the panel (geo/<cat>.doms + the geoip sets).
#
# The lists are why this exists. The panel ships almost no inline domains — the real per-category list is PULLED into
# the node's geo dir and read back from there. Kernel-SNI builds its xt_string chain ONLY from categories that have
# a non-empty domain list, so a converted node started with an empty geo dir, found nothing to hook, tore the SWGK
# chain down, and reported "SNI scanner down — host routing degraded" until the background pull happened to land —
# indefinitely if the panel's manifest didn't re-offer the category. Carrying the files makes the converted node
# come up already routing, exactly as it was before the move.
migrate_node_state(){
  local dir="$1" dd="${2:-/opt/swg-panel-docker}" nd="${3:-}" src dst d
  [ -n "$nd" ] || nd="$dd/data/node"
  case "$dir" in
    to-docker)    src=/var/lib/swg-noded; dst="$nd";;
    to-baremetal) src="$nd";              dst=/var/lib/swg-noded;;
    *) return 0;;
  esac
  [ "$src" = "$dst" ] && return 0        # same convention on both sides (a nix-container node keeping the
                                         # bare-metal stateDir) — nothing to carry, and cp -a onto itself errors
  for d in iface-keys geo; do
    [ -d "$src/$d" ] || continue
    mkdir -p "$dst/$d" && cp -a "$src/$d/." "$dst/$d/" \
      || { warn "couldn't carry the node's $d over — $([ "$d" = geo ] && echo "host routing re-fills itself from the panel within a minute" || echo "server-key revert loses its baseline")"; continue; }
    case "$d" in
      iface-keys) sub "carried interface keypair backups → $dst/iface-keys";;
      geo)        sub "carried the pulled routing lists → $dst/geo";;
    esac
  done
  return 0; }

# wdtt_local [record…] — one TAB-separated row per WDTT instance this node manages: iface, listen, wg_addr.
# Reads the FIRST record path that exists (docker installs pass their own before the bare-metal default).
# Was three near-copies across install-host / install-node / install-docker, differing only in that lookup.
wdtt_local(){
  local r="" p
  for p in "$@" "$(lc_bare_record wdtt.json)"; do [ -f "$p" ] && { r="$p"; break; }; done
  [ -n "$r" ] || return 0
  python3 - "$r" <<'PYWL' 2>/dev/null || true
import json, sys
try: d = json.load(open(sys.argv[1]))
except Exception: raise SystemExit
for i in (d.get("wdtt") or []):
    if isinstance(i, dict) and i.get("iface"):
        print("%s\t%s\t%s" % (i["iface"], i.get("listen") or ("127.0.0.1:%s" % (i.get("wg_port") or "?")), i.get("wg_addr") or "?"))
PYWL
}
wdtt_row(){ printf '    %s%-10s%s  %s%-10s%s  %s  %s\n' "${C_GREEN:-}" "$1" "${RESET:-}" "${BOLD:-}" "WDTT" "${RESET:-}" "${2:-?}" "${3:-?}"; }

# ── nginx after a convert ────────────────────────────────────────────────────────────────────────
# A convert MOVES the panel's cert dir (/etc/swg-panel → /etc/swg-panel.converted-<ts>, or the other
# way into <docker>/data/etc) and CHANGES the upstream ports. A reverse-proxied install therefore comes
# out the far side with a vhost pointing at a path that no longer exists and a port nothing listens on.
# nginx keeps serving its stale in-memory config, so nothing looks wrong until someone reloads — at which
# point `nginx -t` fails and the site is down. Observed live: subscriptions 502'd after a bare→docker
# convert because the vhost still proxied to the bare :8888 while the container published :8444.
#
# Ownership rule: we only REWRITE the vhost swg itself wrote (sites-available/swg-panel.conf). Everything
# else on the box is the operator's, so for those we DETECT and report the exact old→new values and let
# them make the edit. Silently rewriting a config we didn't author is how you lose someone's tuning.
#
#   nginx_convert_fixup <new_tls_dir> <new_panel_upstream> [<new_sub_upstream>]
#     new_tls_dir       dir now holding fullchain.pem/key.pem, e.g. /opt/swg-panel-docker/data/etc/tls
#     new_panel_upstream  e.g. http://127.0.0.1:8088
#     new_sub_upstream    e.g. https://127.0.0.1:8444   (optional; blank = don't mention the sub)
NGINX_DIR="${NGINX_DIR:-/etc/nginx}"   # overridable so this is testable and dry-runnable against a fake tree
_ngx_enabled_files(){        # list every config file nginx will read (can't use `nginx -T`: it fails when broken)
  local d; for d in "$NGINX_DIR/sites-enabled" "$NGINX_DIR/conf.d"; do
    [ -d "$d" ] || continue
    find "$d" -maxdepth 1 -type f -o -maxdepth 1 -type l 2>/dev/null
  done | sort -u; }
_ngx_port_dead(){ have ss || return 1; [ -z "$(ss -lntH "sport = :$1" 2>/dev/null)" ]; }
# ngx_upstream <port> — "https://127.0.0.1:<port>" or "http://…", decided by ASKING the listener rather than
# assuming. Whether swg-sub terminates its own TLS depends on subscriptions.serve.tls_mode, and the panel's
# loopback listener is plain HTTP while its public one is not — guessing here writes a vhost that 502s.
ngx_upstream(){
  local p="$1"
  curl -sk -o /dev/null --max-time 3 "https://127.0.0.1:$p/" 2>/dev/null && { printf 'https://127.0.0.1:%s' "$p"; return 0; }
  printf 'http://127.0.0.1:%s' "$p"; }
nginx_convert_fixup(){
  local tlsdir="$1" up_panel="$2" up_sub="${3:-}"
  have nginx || return 0
  _ngx_enabled_files | grep -c . >/dev/null || return 0
  local swgvh="" f
  for f in "$NGINX_DIR/sites-enabled/swg-panel.conf" "$NGINX_DIR/conf.d/swg-panel.conf"; do [ -e "$f" ] && swgvh="$f" && break; done
  [ -n "$swgvh" ] && [ -L "$swgvh" ] && swgvh="$(readlink -f "$swgvh" 2>/dev/null || echo "$swgvh")"

  # 1) repair OUR vhost in place — only the two things a convert invalidates, so operator edits survive
  local swgbak=""
  if [ -n "$swgvh" ] && [ -f "$swgvh" ] && [ -f "$tlsdir/fullchain.pem" ]; then
    # NOT beside the vhost: nginx `include sites-enabled/*` would load the backup as a duplicate server
    # block, and it would also show up in the operator-config scan below as a file we don't own.
    swgbak="$(mktemp 2>/dev/null || echo "/tmp/swg-vhost.$$")"; cp -a "$swgvh" "$swgbak" 2>/dev/null || true
    local live_ports; live_ports="$(ss -lntH 2>/dev/null | grep -oE ':[0-9]+ ' | tr -d ': ' | sort -u | tr '\n' ',')"
    python3 - "$swgvh" "$tlsdir" "$up_panel" "$live_ports" <<'PYNGX' 2>/dev/null && sub "repointed the panel vhost ($swgvh) at $tlsdir and $up_panel"
import os, re, sys
p, tls, up = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3]
live = {x for x in (sys.argv[4] if len(sys.argv) > 4 else "").split(",") if x}
s = open(p).read()
# only rewrite a cert path that is actually GONE — never touch one the operator repointed themselves
def cert(m):
    key, path = m.group(1), m.group(2)
    return m.group(0) if os.path.exists(path) else "%s %s/%s;" % (key, tls, os.path.basename(path))
s = re.sub(r"(ssl_certificate|ssl_certificate_key)\s+(\S+);", cert, s)
# We wrote this file, and what we write is the PANEL vhost only — one upstream. If it now names more than one
# distinct loopback port, it has been extended beyond what we generate (a sub vhost bolted into the same file,
# say), and "point every upstream at the panel" would silently redirect the other one. Leave ports alone then;
# the reporting pass below still tells the operator exactly what moved. Also never touch a port that is LIVE:
# a listening upstream is by definition not what this convert broke.
ports = set(re.findall(r"proxy_pass\s+https?://127\.0\.0\.1:(\d+);", s))
if len(ports) <= 1:
    s = re.sub(r"proxy_pass\s+https?://127\.0\.0\.1:(\d+);",
               lambda m: m.group(0) if m.group(1) in live else "proxy_pass %s;" % up, s)
open(p, "w").write(s)
PYNGX
  fi

  # 2) report what we must NOT touch: dangling certs / dead upstreams in the operator's own vhosts
  local bad=0 pf
  while IFS= read -r pf; do
    [ -f "$pf" ] || continue
    [ "$pf" = "$swgvh" ] && continue
    local c
    while IFS= read -r c; do
      [ -n "$c" ] && [ ! -e "$c" ] && { [ "$bad" = 0 ] && warn "nginx configs you maintain still point at things this convert moved:"; bad=1
        warn "  $(basename "$pf"): certificate $c is gone → use $tlsdir/$(basename "$c")"; }
    done <<EOC
$(grep -hoE '^[[:space:]]*ssl_certificate(_key)?[[:space:]]+[^;]+;' "$pf" 2>/dev/null | sed -E 's/^[[:space:]]*ssl_certificate(_key)?[[:space:]]+//; s/;$//')
EOC
    local prt
    while IFS= read -r prt; do
      [ -n "$prt" ] && _ngx_port_dead "$prt" && { [ "$bad" = 0 ] && warn "nginx configs you maintain still point at things this convert moved:"; bad=1
        warn "  $(basename "$pf"): nothing listens on 127.0.0.1:$prt → panel is now $up_panel${up_sub:+, subscriptions $up_sub}"; }
    done <<EOP
$(grep -hoE 'proxy_pass[[:space:]]+https?://127\.0\.0\.1:[0-9]+' "$pf" 2>/dev/null | grep -oE '[0-9]+$' | sort -u)
EOP
  done <<EOF
$(_ngx_enabled_files)
EOF

  # 3) validate + reload. A convert must never leave nginx un-reloadable: if our own edit is what broke
  #    it, put the original back so the operator is no worse off than before.
  if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx >/dev/null 2>&1 || true
    [ "$bad" = 0 ] && sub "nginx config validates and was reloaded"
  else
    [ -n "$swgbak" ] && [ -f "$swgbak" ] && { cp -a "$swgbak" "$swgvh"; warn "our vhost edit didn't validate — restored the original"; }
    warn "nginx -t FAILS, so nginx cannot reload (it is still serving its old in-memory config until something restarts it):"
    nginx -t 2>&1 | sed 's/^/    /' | sed -n 1,4p
  fi
  [ -n "$swgbak" ] && rm -f "$swgbak" 2>/dev/null || true
  return 0; }

# ── Cloudflare credential validation ─────────────────────────────────────────────────────────────
# Both prompts (DNS-01 for `cloudflare`, Origin CA for `cf15`) want a SCOPED API TOKEN: 40 characters of
# [A-Za-z0-9_-]. That is the only form the code wires — acme.sh gets CF_Token, mk_cf_origin sends a Bearer
# header; nothing ever sets CF_Key/CF_Email, so a Global API Key would fail later at issue time. Reject it
# HERE, where the message can say why, instead of after the install has moved on.
#
# The old checks were "non-empty" (docker) and "at least 10 chars" (host), so an email address sailed through
# both and the install proceeded to a certificate that could never issue.
# Deliberately SHAPE-only, not a length equality. The classic scoped token is 40 chars, but Cloudflare also
# issues prefixed ones (cfut_… , ~52 chars), and pinning to 40 would reject a perfectly good credential — a
# worse failure than the one this is fixing, because the operator would have no way past it but --force.
# So: reject what CANNOT be a token (an email, whitespace, quotes, anything far too short) and let the rest
# through to fail loudly at issue time if the scope is wrong.
v_cftoken(){
  case "$1" in *[!A-Za-z0-9_-]*) return 1;; esac      # '@' and '.' land here → an email can never pass
  # 37 lowercase hex is the Global API Key. It is a real Cloudflare credential, which is exactly why it needs
  # rejecting HERE: acme.sh would want CF_Key + CF_Email for it and we only ever set CF_Token, so it would fail
  # at issue time with a generic auth error instead of "you pasted the wrong one of your two credentials".
  case "${#1}" in 37) case "$1" in *[!0-9a-f]*) ;; *) return 1;; esac;; esac
  [ "${#1}" -ge 30 ]
}
v_cforigin(){ v_cftoken "$1"; }                        # same credential type, different scope
# Why a value was rejected — ask_valid shows this instead of a generic hint, so the operator is told what they
# actually pasted rather than being re-prompted with the same sentence.
v_cftoken_why(){
  case "$1" in
    "")        echo "the API token can't be empty";                                                       return;;
    *@*.*)     echo "that looks like an EMAIL address, not an API token";                                 return;;
  esac
  case "${#1}" in
    37) case "$1" in *[!0-9a-f]*) ;; *) echo "that looks like your Global API Key — this needs a scoped API Token (My Profile → API Tokens → Create Token)"; return;; esac;;
  esac
  case "$1" in *[!A-Za-z0-9_-]*) echo "an API token is only letters, digits, '_' and '-' — that value has other characters"; return;; esac
  echo "that is only ${#1} characters — a Cloudflare API token is 40 or more"
}
v_cforigin_why(){ v_cftoken_why "$1"; }

# ── A BARE PANEL'S CERTIFICATE RENEWS ONLY FROM acme.sh's CRON ENTRY ────────────────────────────────────────────────
# acme.sh's daily cron entry (`acme.sh --cron --home /root/.acme.sh`) is the ONE renewer of a bare panel's Let's Encrypt
# certificate, a domain's (90 days) and an IP's (~6 days) alike: the panel's 6-hourly sync-acme brings a renewed
# certificate in and never renews one, and only an operator's "Renew now" does. A box without cron (Debian cloud images,
# "minimal" VPS templates) never got that entry — acme.sh's installer refuses to install there at all ("It is recommended
# to install crontab first … Please add '--force'", 3.1.4), so a convert or a re-install kept a certificate nothing
# renewed and update.sh's heal could not install acme.sh either. It expired: browsers refused the panel, nodes that
# verify it stopped syncing, subscription pages failed (round 12b). Other paths rely on that entry: no systemd timer.
# ensure_acme_cron [<acme.sh> [<home>]] — cron FIRST, installed on demand as nftables / dnsmasq / ipset are (apt, its
# index refreshed first; the unit enabled and started); then, given an acme.sh that is there, its renewal entry when no
# crontab line runs one (acme.sh's own --install-cronjob). Never fatal, never silent: what it cannot fix it says — the
# certificate will NOT renew, and the command that fixes it. ACME_CRON_DID: what it did, for update.sh's summary.
# Bare panels only: install-host.sh and update.sh's bare heal call it (a Docker panel renews inside its container, a
# node uses no acme, NixOS refuses these scripts).
ensure_acme_cron(){
  local a="${1:-}" home="${2:-/root/.acme.sh}" c="" e="" aerr=""
  local reg="${a:-/root/.acme.sh/acme.sh} --install-cronjob --home $home"
  ACME_CRON_DID=""
  if ! command -v crontab >/dev/null 2>&1; then
    if ${DRYRUN:-false}; then
      echo "    [skip] would install cron (apt-get install cron, then enable and start it) — acme.sh renews the certificate only from a daily cron entry, and this box has no crontab"
      return 0
    fi
    if command -v apt-get >/dev/null 2>&1; then
      info "this box has no cron, so acme.sh's daily certificate renewal cannot run — installing cron"
      aerr="$( { apt-get update -qq || true; apt-get install -y cron; } 2>&1 >/dev/null | grep -E '^E: ' | tail -n 1 || true)"
    else
      aerr="no apt-get on this system"
    fi
    if ! command -v crontab >/dev/null 2>&1; then
      warn "cron is missing and could not be installed${aerr:+ ($aerr)} — the panel's Let's Encrypt certificate will NOT renew: it expires (a domain's within 90 days, an IP's within about 6), then browsers refuse the panel and nodes stop syncing. Fix: apt-get install cron && systemctl enable --now cron${a:+, then $reg}"
      return 0
    fi
    systemctl enable --now cron >/dev/null 2>&1 \
      || warn "cron is installed but did not start — acme.sh's renewals need it running: systemctl enable --now cron"
    c=c
  fi
  if [ -n "$a" ] && [ -x "$a" ] && ! acme_cron_entry; then
    if ${DRYRUN:-false}; then echo "    [skip] would register acme.sh's daily renewal entry in root's crontab ($reg)"; return 0; fi
    "$a" --install-cronjob --home "$home" >/dev/null 2>&1 || true
    if acme_cron_entry; then e=e
    else warn "acme.sh's renewal entry is not in root's crontab and could not be added — the certificate will NOT renew on its own. Fix: $reg"; fi
  fi
  case "$c$e" in
    ce) ACME_CRON_DID="cron installed + renewal entry registered"
        ok "cron installed and acme.sh's daily renewal entry registered — the certificate renews on its own again";;
    c)  ACME_CRON_DID="cron installed"; ok "cron installed — acme.sh can renew the certificate from its daily entry";;
    e)  ACME_CRON_DID="renewal entry registered"
        ok "acme.sh's daily renewal entry was missing from root's crontab — registered; the certificate renews on its own again";;
  esac
  return 0; }
# 0 = a crontab line (root's, /etc/crontab or /etc/cron.d; comments aside) runs `acme.sh --cron` — acme.sh's own test
acme_cron_entry(){ { crontab -l 2>/dev/null || true; cat /etc/crontab /etc/cron.d/* 2>/dev/null || true; } \
  | grep -v '^[[:space:]]*#' | grep -c 'acme\.sh --cron' >/dev/null; }

# ── host addresses for a DOCKER panel ────────────────────────────────────────────────────────────
# host_bindable_ips — the HOST's bindable, public-servable addresses as "ip|iface" (comma-separated).
# The panel's own _bindable_ips() cannot produce these in docker: the container is BRIDGED, so it sees
# only the compose network's 172.x — and `ip` isn't even in the panel image. The installer runs on the
# host, so it captures them here and passes them in via .env (SWG_HOST_IPS). Without it the Access & TLS
# ── the SPA module tree ─────────────────────────────────────────────────────────────────────────────
# Verify a DEPLOYED js/ against the SOURCE it was copied from.
#   verify_js_tree <src-dir> <dest-dir>     -> prints nothing and returns 0 when the copy is complete
#
# The SPA is 22 ES modules plus a locale catalog. If a copy drops or truncates one, nothing anywhere says
# so: the panel serves the rest happily and the operator gets a blank page whose only clue is a 404 in a
# console they will never open. So check the copy — right here, while the operator is still watching.
#
# Compares the two DIRECTORIES rather than a manifest of stored hashes. A manifest has to be regenerated
# every time any module changes, and a stale one cries wolf: it once reported six modules "corrupt" that
# had merely been edited, which is exactly how a check trains people to ignore it. The source tree is the
# authority we already have on disk, it is never out of date with itself, and comparing to it catches a
# TRUNCATED file as well as a missing one.
#
# Never fatal on its own: the caller decides, because a half-copied SPA is worth shouting about but not
# worth aborting an update that has already replaced the server binary.
verify_js_tree(){
  local src="$1" dst="$2"
  [ -d "$src" ] && [ -d "$dst" ] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  python3 - "$src" "$dst" <<'PYJS'
import filecmp, os, sys
src, dst = sys.argv[1], sys.argv[2]
bad = []
for root, _dirs, files in os.walk(src):
    for fn in sorted(files):
        if not fn.endswith(".js"):
            continue
        rel = os.path.relpath(os.path.join(root, fn), src)
        a, b = os.path.join(src, rel), os.path.join(dst, rel)
        if not os.path.exists(b):
            bad.append("missing " + rel)
        elif not filecmp.cmp(a, b, shallow=False):   # shallow=False: compare CONTENT, not size+mtime
            bad.append("differs " + rel)
for b in bad:
    print(b)
sys.exit(1 if bad else 0)
PYJS
}

# "Listen IP" picker offers nothing but 0.0.0.0 / 127.0.0.1 on every docker install.
# The interface filter MIRRORS swg-panel-server's _IFACE_SKIP_RE — keep the two in step.
# Excludes by DEVICE TYPE as well as name: the name filter only catches wgN/awgN, so any tunnel the operator
# named otherwise (an adopted `foreign0`, a WDTT server's `wdtt0`) was offered as a bindable public address —
# binding the panel to a VPN tunnel's own IP is never right. Type is read once from `ip -d link`, where the kind
# (wireguard / amneziawg / tun) is the first token of a detail line. Bridges/veth stay NAME-filtered on purpose:
# a host `br0` carrying real traffic is perfectly bindable, while docker's br-*/veth* are not.
host_bindable_ips(){
  command -v ip >/dev/null 2>&1 || return 0
  local tun; tun="$(ip -d link show 2>/dev/null | awk '
      /^[0-9]+: / { name=$2; sub(/:$/,"",name); sub(/@.*/,"",name); next }
      { if (name != "" && ($1=="wireguard" || $1=="amneziawg" || $1=="tun" || $1=="tap")) { print name; name="" } }')"
  ip -o addr show scope global 2>/dev/null | awk -v skip="$tun" '
    BEGIN { n=split(skip, s, "\n"); for (i=1; i<=n; i++) if (s[i] != "") X[s[i]]=1 }
    ($3=="inet" || $3=="inet6") && !($2 in X) &&
    $2 !~ /^(wg[0-9]|awg[0-9]|swg_|docker|br-|veth|virbr|tun[0-9]|tap[0-9]|cni|flannel|kube|cali|nerdctl)/ {
      split($4, a, "/"); printf "%s%s|%s", (m++ ? "," : ""), a[1], $2 }'
}

# ─────────────────────── AmneziaWG: get the BEST datapath this box can run ───────────────────────
# The amnezia PPA is a LAUNCHPAD ppa — Ubuntu only. On Debian (very common on VPS), on any non-apt
# distro, and on a kernel with no matching headers, `add-apt-repository ppa:amnezia/ppa` cannot work,
# and until now that left the node with NO AmneziaWG at all: the installer only warned, then reported a
# successful install. These two rungs close that. Order matters — the kernel module is materially
# faster, so it is always tried first and userspace is only a fallback.

# One clone, two transports. Full diagnosis in bootstrap.sh: on Ubuntu 22.04 (git 2.34 / libcurl3-gnutls
# 7.81 / nghttp2 1.43) GitHub answers git's smart-HTTP `POST /git-upload-pack` over HTTP/2 with a 401 and a
# Basic-auth challenge — on a PUBLIC repo whose `GET /info/refs` it served 200 a moment earlier. git then
# asks for a username, which GIT_TERMINAL_PROMPT=0 turns into a clean failure rather than a hang. The
# HTTP/1.1 retry turns it back into a working clone. Ubuntu 24.04 (git 2.43 / nghttp2 1.59) never sees it.
# Costs nothing where HTTP/2 works: the retry is only ever reached after a failure.
git_clone_depth1(){ # <url> <dest> [<tag or branch>]
  # A throttled link gives up instead of crawling: git aborts a transfer under 10 KB/s for 30 s, and the whole clone is
  # capped at 5 minutes where `timeout` exists. Measured on a home box in Russia (client report 2026-10-06): GitHub at a
  # crawl, and this clone — whose output goes to a log — left the installer silent for longer than anyone waits.
  # --foreground: git stays in the installer's process group, so a Ctrl-C reaches it and ends the run — timeout's own group
  # kept the Ctrl-C from git, and the run carried on once the clone ended (1.8.9 qualification IN-4). A clone that hit the
  # cap is not tried again over HTTP/1.1: that is the slow link, not the 401 above, and a retry only doubled the wait (IN-21).
  local _to="" _rc=0; have timeout && _to="timeout --foreground 300"
  run env GIT_TERMINAL_PROMPT=0 $_to git -c http.lowSpeedLimit=10240 -c http.lowSpeedTime=30 clone --depth=1 ${3:+--branch "$3"} "$1" "$2" && return 0 || _rc=$?
  rm -rf "${2:?}"
  [ "$_rc" != 124 ] || return 124
  run env GIT_TERMINAL_PROMPT=0 $_to git -c http.version=HTTP/1.1 -c http.lowSpeedLimit=10240 -c http.lowSpeedTime=30 clone --depth=1 ${3:+--branch "$3"} "$1" "$2"
}

# ── the amnezia PPA serves Ubuntu, and only Ubuntu ──────────────────────────────────────────────────────────────────
# AmneziaWG's packages come from Launchpad (ppa:amnezia/ppa), which builds for Ubuntu series only. Tried everywhere, it cost
# a Debian user software-properties-common and ~36 packages (packagekit and polkit left running), a raw Python traceback from
# add-apt-repository ("'NoneType' object has no attribute 'people'") and four "E: Unable to locate package amneziawg…" before
# the source build that actually installs AmneziaWG there — the first thing a Debian user saw, and it read as a failed
# install (1.8.8 qualification, R27: Debian 12 and 13). awg_ppa_suite prints the Ubuntu series the PPA would serve this box —
# Ubuntu itself, or a derivative that says ID_LIKE=ubuntu (Mint, Pop!_OS, elementary…), by its UBUNTU_CODENAME, since a
# derivative's own codename need not be an Ubuntu series — and fails anywhere else. SWG_OS_RELEASE: another file (the gate).
awg_ppa_suite(){
  local f="${SWG_OS_RELEASE:-/etc/os-release}" v id like ucn vcn
  [ -r "$f" ] || return 1
  v="$( . "$f" >/dev/null 2>&1; printf '%s|%s|%s|%s' "${ID:-}" "${ID_LIKE:-}" "${UBUNTU_CODENAME:-}" "${VERSION_CODENAME:-}" )" || return 1
  id="${v%%|*}"; v="${v#*|}"; like="${v%%|*}"; v="${v#*|}"; ucn="${v%%|*}"; vcn="${v#*|}"
  case "$id" in ubuntu) ;; *) case " $like " in *" ubuntu "*) ;; *) return 1;; esac;; esac
  [ -n "${ucn:-$vcn}" ] || return 1
  printf '%s\n' "${ucn:-$vcn}"; }
awg_os_name(){ ( . "${SWG_OS_RELEASE:-/etc/os-release}" >/dev/null 2>&1; printf '%s' "${PRETTY_NAME:-${NAME:-this system}}" ) || printf 'this system'; }
# awg_ppa_add <series> — the amnezia PPA for that Ubuntu series. add-apt-repository names the suite after the running system's
# own codename; on a derivative whose codename is no Ubuntu series (elementary's "horus") that entry is re-pointed at it.
awg_ppa_add(){
  local s="$1" own f
  run apt-get install -y software-properties-common || true
  run add-apt-repository -y ppa:amnezia/ppa || true
  own="$( . "${SWG_OS_RELEASE:-/etc/os-release}" >/dev/null 2>&1; printf '%s' "${VERSION_CODENAME:-}" )" || own=""
  if [ -n "$own" ] && [ "$own" != "$s" ]; then
    for f in "${SWG_APT_SOURCES_D:-/etc/apt/sources.list.d}"/*amnezia*; do
      [ -f "$f" ] && run sed -i -E "s/(^|[[:space:]])$own([[:space:]]|\$)/\\1$s\\2/g" "$f"
    done
  fi
  return 0; }

# ── the kernel module rebuilds itself when the kernel changes (docs/AWG-DATAPATH-RESILIENCE-PLAN.md D4) ──────────
# `linux-headers-$(uname -r)` is headers for ONE kernel. The next kernel arrives through the image metapackage with no
# headers, DKMS skips it ("autoinstall for kernel … was skipped since the kernel headers for this kernel do not seem to
# be installed" — measured on a client's box), and the reboot onto it takes every awg interface down. The metapackage
# that installed the image names its twin: linux-image-virtual → linux-headers-virtual, linux-image-cloud-amd64 →
# linux-headers-cloud-amd64 (Ubuntu and Debian both verified). A kernel no metapackage installed prints nothing — the
# pinned userspace fallback (D1) is what covers that box.
awg_headers_meta(){ # print the headers metapackage of every installed kernel IMAGE metapackage, one per line
  # ⚠️ NOT "whatever depends on the RUNNING kernel's image". The moment an image metapackage has moved on to a newer kernel
  # — the exact incident: running 138, 139 already installed — nothing depends on the running image any more and that
  # question answers nothing, so no headers were ever installed for the kernel about to boot. The installed, UNVERSIONED
  # image metapackages are what bring future kernels, and each names its twin: linux-image-virtual → linux-headers-virtual,
  # linux-image-cloud-amd64 → linux-headers-cloud-amd64. A twin the archive does not have (linux-image-unsigned-…) is
  # skipped; a box whose kernels no metapackage installed prints nothing — the userspace fallback (D1) covers it.
  have dpkg-query && have apt-cache || return 0
  local m h
  for m in $(dpkg-query -W -f='${Package} ${db:Status-Abbrev}\n' 'linux-image-*' 2>/dev/null | awk '$2 ~ /^ii/ && $1 ~ /^linux-image-[a-z]/ {print $1}'); do
    h="linux-headers-${m#linux-image-}"
    apt-cache show "$h" >/dev/null 2>&1 && printf '%s\n' "$h"
  done
  return 0
}
ensure_awg_headers_follow(){ # install-if-missing every headers metapackage above. 0 = all present · 10 = installed now · 1 = none · 2 = failed
  local h any=no inst=no fail=no
  for h in $(awg_headers_meta); do
    any=yes
    [ "$(dpkg-query -W -f='${db:Status-Status}' "$h" 2>/dev/null)" = installed ] && continue   # held or not: dpkg says "hold ok installed"
    if $DRYRUN; then echo "    [skip] apt-get install $h"; inst=yes; continue; fi
    # One refresh and one retry: the lists this box last fetched can name a headers version the mirror no longer carries.
    if run apt-get install -y --no-install-recommends "$h" >/dev/null 2>&1 \
       || { run apt-get update -qq >/dev/null 2>&1; run apt-get install -y --no-install-recommends "$h" >/dev/null 2>&1; }; then inst=yes; else fail=yes; fi
  done
  [ "$any" = yes ] || return 1
  [ "$fail" = yes ] && return 2          # before 10: one installed and one failed is still a failure worth saying
  [ "$inst" = yes ] && return 10
  return 0
}
awg_dkms_build_all_kernels(){ # the registered module, built for EVERY installed kernel that has headers — the next boot's included
  # `dkms install amneziawg/<ver>`, never `dkms autoinstall -k`: autoinstall builds EVERY registered module on the box
  # (nvidia, zfs, …), so one that fails for some kernel was recompiled on every update. Already installed → a 0.2 s no-op.
  have dkms || return 0
  local k s v
  for k in /lib/modules/*; do
    k="${k##*/}"
    [ -e "/boot/vmlinuz-$k" ] && [ -e "/lib/modules/$k/build" ] || continue
    for s in /var/lib/dkms/amneziawg/*/source; do
      [ -e "$s" ] || continue
      v="${s%/source}"; v="${v##*/}"
      run dkms install -m amneziawg -v "$v" -k "$k" >/dev/null 2>&1 || true
    done
  done
  return 0
}
awg_dkms_drop_unowned(){ # ONE DKMS owner: drop an amneziawg source tree no package owns (ours) before a package installs its own
  # ⚠️ NOT for dpkg's sake, which is what this first guarded against. Measured (G6, dkms 3.0.11, Ubuntu 24.04): the package
  # installs cleanly over our tree at the same, a newer and an older version, and `dpkg --audit` stays empty. What two
  # registrations DO is take turns: every `dkms autoinstall` (each update) and every package reinstall (unattended
  # upgrades) installs the OTHER one ("Diff between built and installed module!"), so which module the next boot loads
  # depends on which of them ran last. One owner, the package.
  have dkms || return 0
  # Only once the package can really be had: lists can still name one the archive no longer serves, and our module removed
  # before an install that then fails leaves the next boot with no module at all. No obtainable package → nothing removed.
  run apt-get install -y --download-only amneziawg-dkms >/dev/null 2>&1 || return 0
  local d v
  for d in /usr/src/amneziawg-*; do
    # A DKMS tree of THIS module only — never a checkout that merely matches the glob (amneziawg-linux-kernel-module).
    grep -qs '^PACKAGE_NAME="\?amneziawg"\?[[:space:]]*$' "$d/dkms.conf" || continue
    dpkg -S "$d" >/dev/null 2>&1 && continue
    v="${d##*/amneziawg-}"
    run dkms remove "amneziawg/$v" --all >/dev/null 2>&1 || true
    run rm -rf "$d"
  done
  return 0
}

awg_dkms_register_dir(){ # <module src dir> — register upstream's module with DKMS and build it for every kernel with headers
  # The only route that keeps a SOURCE-built module across kernel upgrades. Used by the source build below, and by the
  # update heal for a box an older installer built with `make install` (every Debian node until D4).
  local src="$1" ver
  have dkms || return 1
  ver="$(sed -n 's/^PACKAGE_VERSION="\(.*\)"/\1/p' "$src/dkms.conf" 2>/dev/null)"
  [ -n "$ver" ] || return 1
  run make -C "$src" dkms-install && run dkms add -m amneziawg -v "$ver" \
    && run dkms build -m amneziawg -v "$ver" -k "$(uname -r)" && run dkms install -m amneziawg -v "$ver" -k "$(uname -r)" || return 1
  awg_dkms_build_all_kernels
}
awg_tools_drive_3x(){ # 0 = the `awg` on PATH can configure an AmneziaWG 3.x kernel module — the only kind we build from source
  # Every module below is upstream master: AmneziaWG 3.x since 2026-07-31. Tools older than 3.0 cannot configure one AT ALL
  # (H1–H4 and a peer's keepalive changed type), so `awg setconf` answers "Invalid argument" and every awg interface fails to
  # come up — silently at first, because the old module keeps serving until the next reboot. Measured on Debian 12
  # (2026-09-18): tools v1.0.x → EINVAL on the 3.1 module; v3.0 and v3.1 → configured. Our own source route has built 3.1
  # tools since it began (2026-08-20) and the PPA builds both packages from upstream master, so what this catches is tools
  # WE did not install — built by hand before AmneziaWG 3. Those stay the operator's: never rebuilt, only not outrun.
  # Asked of the PARSER, not a version: versions lie (the PPA's 3.1 tools PACKAGE is 1.0.20210914-…). HeaderProtectionKey
  # is a 3.x key that 2.0 tools do not contain. A wrong "no" costs a box its kernel module (userspace instead), never its
  # interfaces. ⚠️ Generation-specific: a future module that 3.x tools cannot drive needs its own probe here.
  local a; a="$(command -v awg 2>/dev/null)" || return 1
  grep -qa HeaderProtectionKey "$a" 2>/dev/null
}
awg_tools_old_why(){ # the operator-facing reason awg_tools_drive_3x said no, and what to do about it
  local v; v="$(awg --version 2>/dev/null | awk 'NR==1{print $2}')"
  printf 'the awg tools on this node%s predate AmneziaWG 3 and cannot configure the kernel module upstream ships now — rebuild amneziawg-tools to use it' "${v:+ ($v)}"
}
awg_dkms_register_source(){ # clone upstream and register it — ONLY when no amneziawg tree is registered at all. 0 = registered now · 3 = tools too old
  have dkms && have git && have make || return 1
  [ -z "$(dkms status amneziawg 2>/dev/null)" ] || return 1            # a tree exists (ours or the package's): its owner builds it
  awg_tools_drive_3x || return 3   # registering master would outrun the tools: every awg interface down at the next boot
  $DRYRUN && { echo "    [skip] register amneziawg with DKMS from source"; return 0; }
  local w rc=1; w="$(mktemp -d)"
  git_clone_depth1 https://github.com/amnezia-vpn/amneziawg-linux-kernel-module "$w/mod" >"$w/log" 2>&1 \
    && { awg_compat_patch "$w/mod/src" >>"$w/log" 2>&1 || true; } \
    && awg_dkms_register_dir "$w/mod/src" >>"$w/log" 2>&1 && rc=0
  rm -rf "$w"
  return $rc
}

# ── a kernel module that does not COMPILE is remembered, not retried ──────────────────────────────────────────────────
# Ubuntu 26.04's kernel 7.0.0-38 (client report 2026-10-06): upstream's module did not build on it at all, and the
# installer compiled it four or five times per pass — the package's postinst, `dkms autoinstall` twice, a --reinstall,
# every kernel, then once more from source — every update did all of it again, and the failed amneziawg-dkms was left
# half-configured, so every later `apt install` on the box ended in a dpkg error. One record per kernel says what did not
# compile: the package version (pkg) and the upstream commit (src). The next try waits for a new kernel, a newer
# package, or a newer upstream commit; a kernel the record does not name has no record at all.
AWG_MOD_FAILED="${SWG_AWG_MOD_FAILED:-/var/lib/swg-noded/awg-module-failed}"
awg_fail_get(){ # <pkg|src> — what did not compile on THIS kernel; empty (rc 1) when nothing is recorded for it
  [ "$(sed -n 's/^kernel=//p' "$AWG_MOD_FAILED" 2>/dev/null)" = "$(uname -r)" ] || return 1
  local v; v="$(sed -n "s/^$1=//p" "$AWG_MOD_FAILED" 2>/dev/null | sed -n 1p)"; [ -n "$v" ] && printf '%s' "$v"; }
awg_fail_note(){ # <pkg|src> <value> — this kernel's record gains one fact (a record for another kernel is replaced)
  $DRYRUN && return 0
  local k old=""; k="$(uname -r)"
  [ "$(sed -n 's/^kernel=//p' "$AWG_MOD_FAILED" 2>/dev/null)" = "$k" ] && old="$(grep -v -e '^kernel=' -e "^$1=" "$AWG_MOD_FAILED" 2>/dev/null || true)"
  mkdir -p "$(dirname "$AWG_MOD_FAILED")" 2>/dev/null || return 0
  printf 'kernel=%s\n%s%s=%s\n' "$k" "${old:+$old
}" "$1" "$2" > "$AWG_MOD_FAILED.tmp" 2>/dev/null && mv -f "$AWG_MOD_FAILED.tmp" "$AWG_MOD_FAILED" 2>/dev/null || true; }
awg_module_head(){ # the commit upstream's kernel module is at now — empty when it cannot be asked (no git, no network)
  have git || return 0
  # --foreground: a Ctrl-C ends it at once (IN-4); git's low-speed abort ends a stalled helper, which the cap then misses
  local t=""; have timeout && t="timeout --foreground 30"
  $t env GIT_TERMINAL_PROMPT=0 git -c http.lowSpeedLimit=10240 -c http.lowSpeedTime=30 \
    ls-remote https://github.com/amnezia-vpn/amneziawg-linux-kernel-module HEAD 2>/dev/null | cut -f1 | sed -n 1p; }
awg_src_retry_due(){ # [<head>] — 0 unless upstream is still the commit that did not compile on THIS kernel (unknown head: not due)
  local was h; was="$(awg_fail_get src)" || return 0
  h="${1-$(awg_module_head)}"; [ -n "$h" ] || return 1
  case "$h" in "$was"*) return 1;; esac; return 0; }
awg_pkg_retry_due(){ # 0 unless amneziawg-dkms already did not compile on THIS kernel at the version apt would install now
  local was c; was="$(awg_fail_get pkg)" || return 0
  c="$(LC_ALL=C apt-cache policy amneziawg-dkms 2>/dev/null | sed -n 's/^[[:space:]]*Candidate:[[:space:]]*//p' | sed -n 1p)"   # C: apt translates "Candidate:"
  [ -n "$c" ] && [ "$c" != "(none)" ] && [ "$c" != "$was" ]; }
awg_nothing_new(){ # 0 = something did not compile on THIS kernel, and no recorded route has moved since (pkg / upstream)
  # Asked over the kinds that HAVE a record: a source build records only src, a PPA version without a commit only pkg —
  # requiring both made the "nothing new" answer unreachable there, and every update "healed" it again.
  local any=no
  if awg_fail_get pkg >/dev/null; then any=yes; awg_pkg_retry_due && return 1; fi
  if awg_fail_get src >/dev/null; then any=yes; awg_src_retry_due && return 1; fi
  [ "$any" = yes ]; }
# ── a module the kernel REFUSES for its signature (Secure Boot) — no rebuild helps ─────────────────────────────────────
# With Secure Boot on, DKMS signs the module with its own key (MOK), and the kernel loads it only once that key is enrolled
# in the firmware — a step at the box's console, after a reboot. Until then `modprobe` answers "Key was rejected by
# service", the module counts as BUILT, and every heal rebuilt it (a --reinstall, then a source build) to the same refusal.
# Said once with the steps, and recorded for this kernel AND this boot, so swg-noded can tell the panel why instead of
# "update to rebuild". The boot is part of it: enrolling the key takes a reboot, so the record goes stale by itself the moment
# it could have stopped being true — no step has to remember to delete it.
AWG_MOD_REFUSED="${SWG_AWG_MOD_REFUSED:-/var/lib/swg-noded/awg-module-refused}"
awg_mod_key_rejected(){ # 0 = a SIGNED module for THIS kernel exists, and the kernel refuses its signing key
  awg_mod_built || return 1
  # An unsigned module is refused too ("Required key not available" on some kernels) — but there is no key to enrol for it,
  # so it is not this case, and its advice would be wrong.
  [ -n "$(modinfo -k "$(uname -r)" -F signer amneziawg 2>/dev/null)" ] || return 1
  local e; e="$(modprobe amneziawg 2>&1 >/dev/null)" && return 1
  case "$e" in *"Key was rejected"*|*"Required key not available"*) return 0;; esac
  return 1; }
awg_mok_key(){ # the certificate that signed THIS kernel's module — the one to enrol. Matched, not guessed: modinfo's sig_key
  # is the signing certificate's serial (measured on swgt: Ubuntu's dkms signs with shim-signed's MOK.der although its
  # framework.conf still shows dkms's own mok.pub defaults). Without openssl or a sig_key: the first that exists.
  local want k s
  want="$(modinfo -k "$(uname -r)" -F sig_key amneziawg 2>/dev/null | tr -d ':[:space:]' | tr 'a-f' 'A-F' | sed 's/^0*//')"
  for k in ${SWG_MOK_CANDIDATES:-/var/lib/shim-signed/mok/MOK.der /var/lib/dkms/mok.pub}; do   # (no spaces in these paths)
    [ -f "$k" ] || continue
    { [ -n "$want" ] && have openssl; } || { printf '%s' "$k"; return 0; }
    s="$( { openssl x509 -inform DER -in "$k" -noout -serial 2>/dev/null || openssl x509 -in "$k" -noout -serial 2>/dev/null; } \
          | sed -n 's/^serial=//p' | tr 'a-f' 'A-F' | sed 's/^0*//')"
    [ -n "$s" ] && [ "$s" = "$want" ] && { printf '%s' "$k"; return 0; }
  done
  return 1; }
_awg_boot_id(){ cat /proc/sys/kernel/random/boot_id 2>/dev/null; }
awg_key_refused_here(){ # recorded for THIS kernel, in THIS boot
  [ "$(sed -n 's/^kernel=//p' "$AWG_MOD_REFUSED" 2>/dev/null)" = "$(uname -r)" ] \
    && [ "$(sed -n 's/^boot=//p' "$AWG_MOD_REFUSED" 2>/dev/null)" = "$(_awg_boot_id)" ]; }
awg_key_refused_note(){ # say it with the steps, and record it for swg-noded (kernel, boot, the key's path)
  local k; k="$(awg_mok_key)" || k=""
  warn "AmneziaWG: Secure Boot is on, and the kernel refuses the module DKMS built for $(uname -r) — its signing key is not enrolled. Enrol it once: sudo mokutil --import ${k:-<the DKMS signing key>} (choose a one-time password), reboot, and pick “Enroll MOK” on the blue screen at the console. Until then awg interfaces run on the slower userspace datapath; rebuilding the module would not help."
  $DRYRUN && return 0
  mkdir -p "$(dirname "$AWG_MOD_REFUSED")" 2>/dev/null || return 0
  printf 'kernel=%s\nboot=%s\nmok=%s\n' "$(uname -r)" "$(_awg_boot_id)" "$k" > "$AWG_MOD_REFUSED.tmp" 2>/dev/null && mv -f "$AWG_MOD_REFUSED.tmp" "$AWG_MOD_REFUSED" 2>/dev/null || true; }
awg_mod_built(){ modinfo -k "$(uname -r)" amneziawg >/dev/null 2>&1; }   # a module file exists for THIS kernel (loadable or not)
awg_blacklisted(){ modprobe -c 2>/dev/null | grep -qE '^blacklist[[:space:]]+amneziawg$'; }   # the operator's own (modprobe.d)
_awg_kbuild(){ printf '%s' "${SWG_LIB_MODULES:-/lib/modules}/$(uname -r)/build"; }   # this kernel's headers (the gates point it elsewhere)
awg_dkms_compile_failed(){ # after installing amneziawg-dkms: its own build did not COMPILE for this kernel, with its headers here. 0 = that
  # — not a missing prerequisite (no headers), and not a module that built but will not load (Secure Boot: the package is
  # configured): the package's postinst failed, so dpkg holds it half-configured — whatever module file this kernel has
  # besides (a stale `make install`, a source build beside the package: it hid the failure, and the package stayed
  # half-configured, recompiled on every update — 1.8.9 qualification IN-12(e)). ⚠️ AND THE COMPILER SAID SO: DKMS's build
  # log names a compiler error — `: error: `, or gcc's `<file>:<line>:<col>: fatal error:`, a header the newer kernel
  # dropped (read as a box fault, that one was never given up: the package stayed half-configured between updates, failing
  # every apt run on the box — FN-1). A build the BOX cut short — a full disk ("No space left on device"),
  # a killed compiler or assembler ("Killed signal") — fails the same way, and was given up for good on that alone (1.8.9
  # qualification IN-15, on a VM); it is tried again instead, whatever errors of its own it left (cc1's located "fatal
  # error: error writing to …"). A driver's `gcc: fatal error:` has no location and is not a compile failure either.
  [ -e "$(_awg_kbuild)" ] && have dpkg-query || return 1
  case "$(dpkg-query -W -f='${db:Status-Abbrev}' amneziawg-dkms 2>/dev/null)" in iF*|iU*|iH*) ;; *) return 1;; esac
  grep -qsE ': error: |:[0-9]+: fatal error: ' "${SWG_DKMS_TREE:-/var/lib/dkms}"/amneziawg/*/build/make.log \
    && ! grep -qsE 'No space left on device|Killed signal|internal compiler error: Killed' "${SWG_DKMS_TREE:-/var/lib/dkms}"/amneziawg/*/build/make.log; }
awg_dkms_give_up(){ # after that: leave the package manager clean, keep the tools, remember what did not compile
  local v sha; v="$(dpkg-query -W -f='${Version}' amneziawg-dkms 2>/dev/null)"
  warn "AmneziaWG: its kernel module does not compile on kernel $(uname -r) (amneziawg-dkms ${v:-?}) — upstream does not support this kernel yet. The package manager is left clean, and awg interfaces use the userspace datapath; an update tries the module again when a new kernel or a newer AmneziaWG build arrives."
  # Removed, not left half-configured: every later apt run on the box (ours, the operator's, unattended-upgrades) would
  # end in a dpkg error over it. --no-install-recommends on the tools: a recommends on the module must not reinstall it.
  run apt-get remove -y -o DPkg::Lock::Timeout=180 amneziawg-dkms amneziawg >/dev/null 2>&1 || run dpkg --remove --force-remove-reinstreq amneziawg-dkms amneziawg >/dev/null 2>&1 || true
  have awg || run apt-get install -y --no-install-recommends amneziawg-tools >/dev/null 2>&1 || true
  # Recorded only once it is gone: a removal that lost dpkg's lock all the same (unattended-upgrades) was recorded as given
  # up, so no later run tried again, and the package stayed half-configured for good (1.8.9 qualification IN-12(a)).
  case "$(dpkg-query -W -f='${db:Status-Abbrev}' amneziawg-dkms 2>/dev/null)" in
    ""|?n*|?c*) ;;
    *) $DRYRUN || warn "AmneziaWG: amneziawg-dkms could not be removed now (the package manager is busy) — the next update tries again"
       return 0;;
  esac
  [ -n "$v" ] && awg_fail_note pkg "$v"
  sha="$(printf '%s' "$v" | sed -n 's/.*+\([0-9a-f]\{7,40\}\)~.*/\1/p')"   # the PPA builds upstream master and names the commit
  [ -n "$sha" ] && awg_fail_note src "$sha"
  return 0; }
awg_ppa_module_install(){ # the package route's install — once: a compile failure is given up on, never retried. 0 = installed and built
  if ! awg_pkg_retry_due; then
    info "AmneziaWG: not rebuilding the kernel module — amneziawg-dkms $(awg_fail_get pkg) did not compile on $(uname -r); awg interfaces use the userspace datapath"
    have awg || run apt-get install -y --no-install-recommends amneziawg-tools || true
    return 1
  fi
  run apt-get install -y amneziawg amneziawg-dkms amneziawg-tools || run apt-get install -y amneziawg || true
  $DRYRUN && return 0
  # its postinst built from the source as shipped; fixed now (PR #218), the half-configured package builds again
  if awg_compat_patch_installed; then awg_dpkg_recover || true; fi
  if awg_dkms_compile_failed; then awg_dkms_give_up; return 1; fi
  return 0; }
awg_dkms_reinstall(){ # the --reinstall fallback (build_awg_module, update.sh's heal). 1 = given up: it does not compile here
  # The reinstall puts the source back AS SHIPPED — PR #218's fix undone — and its postinst builds that: on a 7.0.0-38 kernel
  # it failed, and amneziawg-dkms was left half-configured for every later apt run, with nothing after it to recover or give
  # up (1.8.9 qualification IN-10: a patched module that built but would not load, e.g. in an LXC guest). So, exactly as
  # awg_ppa_module_install: fix the source again, finish dpkg, and give up on a build that still does not compile.
  run apt-get install --reinstall -y amneziawg-dkms 2>/dev/null || true
  $DRYRUN && return 0
  if awg_compat_patch_installed; then awg_dpkg_recover || true; fi
  if awg_dkms_compile_failed; then awg_dkms_give_up; return 1; fi
  return 0; }

# ── upstream PR #218, applied to the module's source until upstream ships it ─────────────────────────────────────────────
# amneziawg-linux-kernel-module picks the old (struct socket *) or new (struct sock *) setup_udp_tunnel_sock /
# udp_tunnel_sock_release by kernel VERSION — "below 7.1.5 is old". Ubuntu backported the new signature into 7.0.0-38
# under an unchanged version, so the module stopped compiling there (#259) — and on an ordinary kernel upgrade the failed
# DKMS build left linux-headers / linux-generic unconfigured: apt broken for the whole box (bivlked/amneziawg-installer
# #325). PR #218 (open, unmerged) asks the compiler which signature the kernel DECLARES instead of guessing from the
# number. Applied only where the exact version-gated block is present, never twice; once upstream changes that block
# this does nothing. tests/awg_compat_patch_selftest.py builds it against Ubuntu 26.04 (7.0.0-38 and an older 7.0),
# 24.04 and Debian headers and asserts the choice matches each kernel's declaration.
AWG_COMPAT_MARK="swg-panel: udp_tunnel signature detection (amneziawg-linux-kernel-module PR #218)"
awg_compat_patch(){ # <module source dir — holds compat/compat.h> → 0 patched now · 2 already patched · 1 not applicable
  local f="$1/compat/compat.h"
  [ -f "$f" ] || return 1
  grep -qF "$AWG_COMPAT_MARK" "$f" 2>/dev/null && return 2
  have python3 || return 1
  if $DRYRUN; then echo "    [skip] patch $f (udp_tunnel signature detection)"; return 0; fi
  SWG_MARK="$AWG_COMPAT_MARK" python3 - "$f" <<'PY'
import os, sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
old = ("#if LINUX_VERSION_CODE < KERNEL_VERSION(7, 1, 5)\n"
       "#include <net/udp_tunnel.h>\n"
       "#define setup_udp_tunnel_sock(net, sk, sock_cfg) setup_udp_tunnel_sock(net, sk->sk_socket, sock_cfg)\n"
       "#define udp_tunnel_sock_release(sk) udp_tunnel_sock_release(sk->sk_socket)\n"
       "#endif\n")
if s.count(old) != 1:
    sys.exit(1)
new = ("/* " + os.environ["SWG_MARK"] + ".\n"
       " * The kernel's own declaration decides, not LINUX_VERSION_CODE: distros backport the struct sock * form early\n"
       " * under an unchanged version (Ubuntu 7.0.0-38). Exactly one branch matches; the other folds away. */\n"
       "#include <net/udp_tunnel.h>\n"
       "\n"
       "static inline void __compat_udp_tunnel_sock_release(struct sock *sk)\n"
       "{\n"
       "\tif (__builtin_types_compatible_p(typeof(&udp_tunnel_sock_release), void (*)(struct sock *)))\n"
       "\t\t((void (*)(struct sock *))udp_tunnel_sock_release)(sk);\n"
       "\telse\n"
       "\t\t((void (*)(struct socket *))udp_tunnel_sock_release)(sk->sk_socket);\n"
       "}\n"
       "\n"
       "static inline void __compat_setup_udp_tunnel_sock(struct net *net, struct sock *sk,\n"
       "\t\t\t\t\t\t    struct udp_tunnel_sock_cfg *cfg)\n"
       "{\n"
       "\tif (__builtin_types_compatible_p(typeof(&setup_udp_tunnel_sock),\n"
       "\t\t\t\t\t  void (*)(struct net *, struct sock *, struct udp_tunnel_sock_cfg *)))\n"
       "\t\t((void (*)(struct net *, struct sock *, struct udp_tunnel_sock_cfg *))setup_udp_tunnel_sock)(net, sk, cfg);\n"
       "\telse\n"
       "\t\t((void (*)(struct net *, struct socket *, struct udp_tunnel_sock_cfg *))setup_udp_tunnel_sock)(net, sk->sk_socket, cfg);\n"
       "}\n"
       "\n"
       "#define udp_tunnel_sock_release(sk) __compat_udp_tunnel_sock_release(sk)\n"
       "#define setup_udp_tunnel_sock(net, sk, cfg) __compat_setup_udp_tunnel_sock(net, sk, cfg)\n")
tmp = p + ".swg-tmp"
open(tmp, "w", encoding="utf-8").write(s.replace(old, new))
os.replace(tmp, p)
PY
}
awg_compat_patch_installed(){ # the source DKMS builds from (/usr/src/amneziawg-*), fixed where it needs it. 0 = fixed in THIS run
  # Run whether or not today's kernel builds: the box at risk is the one whose module builds NOW and whose NEXT kernel
  # backports the new API — its kernel upgrade is where the failed DKMS hook would leave apt broken.
  local d now=1 rc
  for d in "${SWG_USR_SRC:-/usr/src}"/amneziawg-*/; do
    [ -f "${d}compat/compat.h" ] || continue
    rc=0; awg_compat_patch "${d%/}" || rc=$?
    [ "$rc" = 0 ] || continue
    now=0; info "AmneziaWG: the module source now asks the kernel which udp_tunnel API it declares (upstream PR #218 — Ubuntu's 7.0.0-38 backports the new one) — ${d%/}"
  done
  return $now; }
awg_dpkg_recover(){ # finish a dpkg run an AmneziaWG build failure left pending (amneziawg-dkms, or the kernel headers whose DKMS
  # hook stopped) — called right after the source was fixed, so the DKMS build it re-runs now compiles. 0 = nothing pending now
  have dpkg || return 0
  [ -n "$(dpkg --audit 2>/dev/null)" ] || return 0
  info "AmneziaWG: finishing the package configuration a failed module build left pending (dpkg --configure -a)…"
  # no terminal, and the old config file kept: a pending package's conffile question would wait unseen (IN-12(b))
  run env DEBIAN_FRONTEND=noninteractive dpkg --force-confdef --force-confold --configure -a </dev/null >/dev/null 2>&1 || true
  [ -z "$(dpkg --audit 2>/dev/null)" ] && return 0
  warn "AmneziaWG: some packages are still not configured — see \`dpkg --audit\`"
  return 1; }

awg_build_from_source(){ # build awg tools (+ the DKMS kernel module) from upstream. 0 = tools AND module.
  # Tools first and unconditionally: `awg` + `awg-quick` are what the panel needs to write and bring up a
  # conf, and they build anywhere with a compiler — no distro repo involved. WITH_WGQUICK=yes is what
  # produces awg-quick; without it you get the confusing half-installed state (`awg` present, awg-quick
  # missing) that reads from the panel as "not installed at all".
  #
  # ⚠️ WITH_SYSTEMDUNITS is deliberately NOT passed. Upstream auto-detects it (yes when the systemd unit
  # directory exists) and installs `awg-quick@.service` + `awg-quick.target`, which is exactly what a
  # bare-metal node needs: without that template `systemctl enable awg-quick@<iface>` cannot work however
  # it is spelled, so no awg interface survives a reboot. This line used to carry `WITH_SYSTEMDUNITS=no`,
  # copied from Dockerfile.node where it is correct (a container has no systemd and brings its interfaces
  # up from node-entrypoint.sh). On a VPS it silently removed boot persistence from every AmneziaWG
  # interface on every box that took this route — i.e. all of Debian, since the PPA is Ubuntu-only.
  # Measured on a Debian 12 node: awg-quick@.service absent, no .wants symlink, and the interface down
  # after every reboot until an operator pressed Start in the panel. Plain WireGuard was unaffected
  # because its template comes from the distro's own wireguard-tools.
  #
  # This alone does NOT heal a box that already has the tools — see ensure_awg_quick_unit in update.sh.
  local w built=no _reg=no _cloned=no; w="$(mktemp -d)"
  if ! have awg || ! have awg-quick; then
    info "building AmneziaWG tools from source (the amnezia PPA is Ubuntu-only)…"
    # ca-certificates is NOT optional here: without it every https git clone below fails cert verification.
    # GIT_TERMINAL_PROMPT=0 on each clone below: these are PUBLIC amnezia-vpn repos, so a credential
    # prompt can only mean github.com is unreachable — and git asks on /dev/tty, which the `>log 2>&1`
    # around these blocks does NOT capture, so an install would sit there waiting for a login with its
    # explanation buried in a log file. Failing is handled (`|| true`, and the caller checks the result);
    # hanging is not. Same defect bootstrap.sh had at the top of this very install.
    # Dockerfile.node never hit this because its golang base image ships them; a minimal Debian does not.
    have apt-get && run apt-get install -y --no-install-recommends git make build-essential ca-certificates >/dev/null 2>&1
    if ! have git || ! have make; then
      warn "cannot build AmneziaWG tools — git/make/compiler missing and no apt-get to add them"
      rm -rf "$w"; return 1
    fi
    { git_clone_depth1 https://github.com/amnezia-vpn/amneziawg-tools "$w/tools" \
        && run make -C "$w/tools/src" \
        && run make -C "$w/tools/src" install PREFIX=/usr WITH_BASHCOMPLETION=no \
                WITH_WGQUICK=yes; } >"$w/build.log" 2>&1 || true
    built=yes   # master, like the module below — never probed (a parser that renames the word must not cost a fresh node its module)
  fi
  $DRYRUN && { rm -rf "$w"; return 0; }
  have awg && have awg-quick || {
    warn "AmneziaWG tools did not build: $(tail -n 2 "$w/build.log" 2>/dev/null | tr '\n' ' ' | cut -c1-200)"
    rm -rf "$w"; return 1; }
  # Kernel module. Wanted wherever it is possible: it is the fast datapath, and on Debian this source
  # build is the ONLY way to it. Needs headers for the RUNNING kernel — a provider kernel often has none,
  # and an LXC/OpenVZ guest cannot load a module at all, which is what the userspace rung is for.
  # No modprobe at all (a stripped image, some containers) means no kernel module is possible here — say so
  # by falling through to userspace rather than returning modprobe's 127 to the caller.
  have modprobe || { rm -rf "$w"; return 1; }
  if modprobe amneziawg 2>/dev/null; then rm -rf "$w"; return 0; fi
  # Tools we did not build (they were already here) may be too old for the master module below: it would load now or at
  # the next boot and take every awg interface down. The caller's next rung, userspace, serves them instead.
  [ "$built" = yes ] || awg_tools_drive_3x || { warn "AmneziaWG: $(awg_tools_old_why) — not building it; awg interfaces use the userspace datapath"; rm -rf "$w"; return 1; }
  if awg_mod_key_rejected; then awg_key_refused_note; rm -rf "$w"; return 1; fi   # built, refused for its key: a rebuild changes nothing
  local _head; _head="$(awg_module_head)"
  if ! awg_src_retry_due "$_head"; then
    info "AmneziaWG: upstream's kernel module is still ${_head:0:7}, which did not compile on $(uname -r) — not building it again"
    rm -rf "$w"; return 1
  fi
  info "building the AmneziaWG kernel module for $(uname -r) from source — this can take several minutes on a slow box…"
  have apt-get && run apt-get install -y --no-install-recommends dkms "linux-headers-$(uname -r)" >/dev/null 2>&1
  ensure_awg_headers_follow >/dev/null 2>&1 || true
  if git_clone_depth1 https://github.com/amnezia-vpn/amneziawg-linux-kernel-module "$w/mod" >"$w/mod.log" 2>&1; then
    _cloned=yes
    awg_compat_patch "$w/mod/src" >>"$w/mod.log" 2>&1 || true   # PR #218, until upstream ships it
    # D4: REGISTER WITH DKMS instead of `make install`. Upstream's `install` is modules_install for the build kernel
    # only, so the next kernel upgrade left the box with no module — on every Debian node, headers or not. DKMS
    # rebuilds it when a kernel is installed. A tree the amnezia package already registered is left to its owner.
    _reg=no; have dkms && [ -z "$(dkms status amneziawg 2>/dev/null)" ] && _reg=yes   # registered by THIS run, if it fails
    if [ "$_reg" = yes ] && awg_dkms_register_dir "$w/mod/src" >>"$w/mod.log" 2>&1; then
      :
    else
      { run make -C "$w/mod/src" && run make -C "$w/mod/src" install; } >>"$w/mod.log" 2>&1 || true
    fi
  fi
  run depmod -a >/dev/null 2>&1 || true
  if modprobe amneziawg 2>/dev/null; then rm -rf "$w"; return 0; fi
  # Say why, like the tools build above: the log is deleted with the work dir, and the caller's next line ("the SLOWER
  # userspace datapath") gives no cause. On Ubuntu 26.04's 7.0.0-38 the upstream module does not compile at all.
  if ! $DRYRUN && awg_mod_key_rejected; then awg_key_refused_note; rm -rf "$w"; return 1; fi   # it built — the kernel refuses its key
  local _why; _why="$(grep -m1 -iE 'error|fatal|timed out|could not' "$w/mod.log" 2>/dev/null | cut -c1-200)"
  $DRYRUN || warn "the AmneziaWG kernel module did not build for $(uname -r): ${_why:-no error line in its build log}"
  # A module that did not COMPILE — cloned, headers here, the compiler's own `error:` in the log, no module file: remember
  # the commit, so no update compiles it again, and drop the DKMS registration this run made (a tree that cannot build
  # would only fail again on every kernel install). A clone a slow link cut off, or a missing tool, is NOT that, and is
  # tried again next time.
  if ! $DRYRUN && [ "$_cloned" = yes ] && [ -e "$(_awg_kbuild)" ] && ! awg_mod_built && grep -q ': error: ' "$w/mod.log" 2>/dev/null; then
    [ -n "$_head" ] && awg_fail_note src "$_head"
    if [ "${_reg:-no}" = yes ]; then
      local _v; _v="$(sed -n 's/^PACKAGE_VERSION="\(.*\)"/\1/p' "$w/mod/src/dkms.conf" 2>/dev/null)"
      [ -n "$_v" ] && run dkms remove -m amneziawg -v "$_v" --all >/dev/null 2>&1 || true
    fi
  fi
  rm -rf "$w"
  return 1
}

# ── AppArmor accommodation for the node's WireGuard tools ───────────────────────────────────────
# Shared by install-node.sh, install-host.sh (a master installs a local node) and update.sh, so a
# FRESH install on an affected distribution is not left waiting for its first update to work.
AA_DIR="${AA_DIR:-/etc/apparmor.d}"                                    # AppArmor policy, vendor + local/
AA_PROFILES="${AA_PROFILES:-/sys/kernel/security/apparmor/profiles}"   # loaded profiles + their mode

# Where the node's WireGuard tools are confined by AppArmor, the UAPI sockets that every USERSPACE
# interface is driven through are not in the profile — so `wg show <iface>` is refused and the panel
# reads those interfaces as having no peers at all. Retiring NoNewPrivileges does not touch this: it is
# a file rule inside the profile, not an exec transition, and it bites whether or not the transition
# happens. It is the same policy, reached through a different door, and it lands on exactly the
# interface types the exec fault did NOT break — wdtt, csqtt, and any awg running the userspace
# datapath, all of which live on a socket rather than in the kernel.
#
#     apparmor="DENIED" operation="connect" profile="wg" name="/run/wireguard/wdtt1.sock"
#     apparmor="DENIED" operation="open"    profile="wg" name="/run/wireguard/"
#
# /var/run is a symlink to /run on any system this runs on, and AppArmor mediates the RESOLVED path, so
# the /var/run rules are dead weight there — they are written anyway for the pre-merge layout, where the
# node's own WG_SOCK_DIRS still looks, and a dead rule costs nothing.
# ⚠️ FENCED AT BOTH ENDS. local/<profile> is a file the distribution and the operator may also write
# in, so "delete the file to revert" would be wrong and un-reversing it by hand is worse. Between these
# two markers is ours and only ours: uninstall.sh reaps exactly this span, and the idempotence check
# below looks for the opening one. ⚠️ TWIN: uninstall.sh reaps this span by literal text and
# deliberately does not source this file — change either marker and you must change both, or the
# grant silently outlives the uninstall. Plain dashes, deliberately: `>>>`/`<<<` fences read as redirects and
# here-strings to anything parsing this file as shell — the repo's own heredoc audit flagged them.
APPARMOR_LOCAL_BEGIN='  # --- swgPanel: userspace WireGuard datapaths (begin) ---'
APPARMOR_LOCAL_END='  # --- swgPanel: userspace WireGuard datapaths (end) ---'
APPARMOR_LOCAL_BLOCK="$APPARMOR_LOCAL_BEGIN
  # wireguard-go / amneziawg-go and the wdtt + csqtt forks are driven over a UAPI socket here. Without
  # these the wg CLI cannot read them and every such interface reports zero peers. To revert, delete
  # the lines between these two markers and: apparmor_parser -r <the profile that includes this file>
  /run/wireguard/ r,
  /run/wireguard/*.sock rw,
  /var/run/wireguard/ r,
  /var/run/wireguard/*.sock rw,
$APPARMOR_LOCAL_END"

_aa_profile_file(){   # echo the profile FILE name under $AA_DIR that holds tool $1's policy, or fail.
  # Newer policy names it for the tool (`wg`), older for the path (`usr.bin.wg`). ONE list, because the
  # guard below and the loop must never disagree about what counts as "this box has a profile for it".
  local c; for c in "$1" "usr.bin.$1" "bin.$1"; do [ -f "$AA_DIR/$c" ] && { echo "$c"; return 0; }; done
  return 1
}

ensure_wg_apparmor(){   # HEAL (extend-if-supported) the AppArmor policy confining the node's WireGuard tools.
  # ⚠️ THIS EDITS A SECURITY POLICY ON SOMEONE ELSE'S MACHINE, so it is gated hard and narrowly:
  #   · only a profile the distribution ships an enforcing copy of (complain mode already allows this);
  #   · only through /etc/apparmor.d/local/<name>, the extension point the profile itself opts into by
  #     including it — if the vendor profile carries no such include we do NOT touch the vendor file,
  #     we say what to add and stop. Editing a packaged profile would be both wrong and lost on upgrade;
  #   · APPEND-ONLY and marked, so a second run is a no-op and nothing already in that file is disturbed;
  #   · SWG_NO_APPARMOR_FIX=1 declines it entirely.
  # The grant is the narrowest one that restores the function: read the socket directory, talk to the
  # sockets in it. Nothing else in the profile is widened.
  [ "${SWG_NO_APPARMOR_FIX:-0}" = 1 ] && return 0
  have apparmor_parser || return 0
  local t prof base loc changed=no
  # ⚠️ WE LOOKED, AND COULD NOT SEE. Without the loaded-profile list there is no way to tell enforce
  # from complain, and complain needs no fix at all — so say so rather than act on a guess or pass in
  # silence. (securityfs unmounted, or a confined/containerised context.)
  if [ ! -r "$AA_PROFILES" ] && { _aa_profile_file wg >/dev/null || _aa_profile_file awg >/dev/null; }; then
    warn "AppArmor policy for the WireGuard tools is present but $AA_PROFILES is unreadable — can't tell enforce from complain, so leaving it alone."
    return 0
  fi
  # ⚠️ wg AND awg ONLY, and that is measured rather than assumed. On the node that reported this,
  # `wg-quick` exec'd ip into a CHILD profile (target="wg-quick//ip") but exec'd wg into the STANDALONE
  # one (target="wg"), and it was `profile="wg"` that then denied /run/wireguard — so local/wg is
  # exactly the file that reaches it. Adding wg-quick here would write rules that no socket access ever
  # consults; and a policy that did route wg through a `wg-quick//wg` child would be out of reach of
  # local/ altogether, which is included at the profile's top level and not inside its children. That
  # case degrades to the agent naming the refusal, which is the honest outcome for something we cannot
  # repair from here.
  for t in wg awg; do
    # ⚠️ A PROFILE IS NAMED EITHER WAY, and so is the file that holds it: newer policy uses the tool
    # name (`wg`, /etc/apparmor.d/wg), older uses the path (`/usr/bin/wg`, /etc/apparmor.d/usr.bin.wg).
    # Matching only one spelling reads a confined box as unconfined and silently does nothing.
    grep -Eqs "^[[:space:]]*(${t}|/usr/bin/${t}|/bin/${t}) \(enforce\)\$" "$AA_PROFILES" || continue
    base="$(_aa_profile_file "$t")" || base=""
    prof="${base:+$AA_DIR/$base}"
    if [ -z "$prof" ]; then
      warn "AppArmor enforces a profile for $t but no profile file was found under $AA_DIR — userspace interfaces (wdtt/csqtt/awg-userspace) will read 0 peers."
      continue
    fi
    loc="$AA_DIR/local/$base"
    # the profile must itself pull in local/<name>; that include is the distribution's own invitation
    if ! grep -Eqs "include[[:space:]]+(if[[:space:]]+exists[[:space:]]+)?<local/$base>" "$prof"; then
      warn "AppArmor confines $t but $prof has no <local/$base> include — userspace interfaces (wdtt/csqtt/awg-userspace) will read 0 peers."
      sub "add to $prof, then: apparmor_parser -r $prof"
      printf '%s\n' "$APPARMOR_LOCAL_BLOCK"
      continue
    fi
    if grep -qsF "$APPARMOR_LOCAL_BEGIN" "$loc" 2>/dev/null; then
      # ⚠️ PRESENT IS NOT LOADED. The block is written first and the profile reloaded second, so a
      # reload that failed once (a transient parse error, an abstraction missing mid-upgrade, the
      # module not up yet) left the rules on disk and unread — and every later run would stop HERE,
      # meaning the heal that exists to fix exactly this could never fire again. Reloading a profile
      # that already carries them is a cheap no-op, so it is not conditional on anything.
      ${DRYRUN:-false} && { echo "    [skip] re-assert $loc via apparmor_parser -r $prof"; continue; }
      apparmor_parser -r "$prof" 2>/dev/null \
        || warn "$loc carries the swgPanel rules but $prof would not reload — run: apparmor_parser -r $prof"
      continue
    fi
    # NB: no `changed=yes` here. A dry-run that also prints the ✓ line below is claiming a policy
    # change it did not make — the [skip] line is the whole report.
    if ${DRYRUN:-false}; then echo "    [skip] append swgPanel socket rules to $loc + apparmor_parser -r $prof"; continue; fi
    mkdir -p "$AA_DIR/local" 2>/dev/null || true
    # A separator only when the file needs one: `$(tail -c1)` strips a trailing newline, so it is
    # empty exactly when the file already ends in one. Always prepending it instead would leave one
    # more blank line behind on every install/uninstall cycle, since the reap cuts marker-to-marker.
    [ -s "$loc" ] && [ -n "$(tail -c 1 "$loc" 2>/dev/null)" ] && printf '\n' >> "$loc" 2>/dev/null
    printf '%s\n' "$APPARMOR_LOCAL_BLOCK" >> "$loc" 2>/dev/null \
      || { warn "couldn't write $loc — add the swgPanel block there by hand"; continue; }
    if apparmor_parser -r "$prof" 2>/dev/null; then changed=yes
    else warn "wrote $loc but couldn't reload $prof — run: apparmor_parser -r $prof"; fi
  done
  [ "$changed" = yes ] && ok "AppArmor: the wg CLI may read userspace interface sockets again (wdtt / csqtt / awg-userspace)"
  return 0
}

# ── the userspace AmneziaWG datapath, PINNED (docs/AWG-DATAPATH-RESILIENCE-PLAN.md D1) ─────────────────────────
# awg-quick falls back to `amneziawg-go` by itself when the kernel module is missing — the day a kernel upgrade arrives
# without headers, a DKMS build fails on a new kernel, or a provider kernel has no headers at all. It can only do that
# if the binary is ALREADY on the box, so every bare-metal AWG node carries it, working module or not.
#
# One pinned upstream ref for the whole fleet: tag + sha256 here, the same ref in Dockerfile.node. The bare-metal binary
# is published as a release asset of this repo, like the fork binaries, and rebuilt byte for byte by
# forks/amneziawg-go/build.sh — static (CGO_ENABLED=0 -trimpath -ldflags "-s -w" -buildvcs=false) with Go 1.27.1, so
# one file runs on any glibc. The node IMAGE builds the same ref with its own base image's Go, so it is the same
# source, not the same bytes. Identify the asset by tag + sha256 only — its `--version` prints upstream's stale
# 0.0.20250522. Verified before install: it runs as root at every boot.
AWG_GO_TAG="amneziawg-go-3.1.20260828"          # upstream amnezia-vpn/amneziawg-go tag v3.1.20260828 — ≥ 3.1, or awg_go_needs_install reinstalls it every run
AWG_GO_SHA256_amd64="85ebee7e01d6a18dd05c1116ceb52df60b0a64778afdc00eb06bf1f554ec1524"
AWG_GO_SHA256_arm64="de0eb94f5b09e57438f5fd86fb15cb1aac5a656b9c39b5c41300a24283b9601e"
# sha256 of EARLIER pinned builds (any arch), space-separated. A box still carrying one of OURS is moved to the current pin;
# an amneziawg-go that is not one of ours — installed by the operator, or by another tool — is never touched. When bumping
# the pin, move the old AWG_GO_SHA256_* values here, or the new build reaches fresh installs only.
AWG_GO_REPLACES=""
# ⚠️ A DOWNGRADE HAS TO TAKE THE DEVICE-ACCESS TABLES WITH IT, and on the box at that moment only SYSTEMD is still
# ours. `reconcile_dev_reach` tears `swg_reach` down the moment the panel sends no plan — but that code is in the
# binary a downgrade replaces. Start a swg-noded that predates device access and nothing can touch the table again:
# it has no such function, and the panel stops sending `dev_reach` to a node reporting `net_deps.reach < 2`. The
# last policy is frozen. Never LESS safe than the older release (which enforces nothing at all), but it goes on
# DROPPING what the panel has since allowed: measured on msk-main (1.8.7 qualification S9), downgraded through
# `bootstrap.sh update` with SWG_REF=main, `swg_reach` + `swg_share` stayed; the interface was set to Everyone on
# the panel and a neighbour's probe still died, the frozen table's own `wgn2` drop counter rising 101 → 108.
#
# ⚠️ THIS USED TO LIVE IN update.sh, WHERE IT COULD NEVER RUN. `bootstrap.sh update` clones the REQUESTED ref and runs
# THAT tree's update.sh — `SRC` is the script's own directory — so a downgrade is always performed by the OLDER
# update.sh, which has no sweep. The gate only proved the call sat before the copy. What an older release does
# leave alone is a drop-in: its update.sh heals the swg-noded unit only when the unit is MISSING and never touches
# `swg-noded.service.d/`. So the sweep runs as ExecStartPre, on every start, against the binary about to run — a
# bootstrap downgrade, a hand-copied binary and a restart are all the same moment.
#
# ⚠️ CONDITIONAL ON PURPOSE. The binary is asked directly (`def _reach_drop_table` is in the file or it is not — a
# version string is a claim), so a build that manages the tables finds them untouched and an ordinary restart or
# upgrade opens no unenforced window. `$$` is systemd's escape for `$`; `-` makes a failed sweep never block the start.
# Not covered, by construction — no newer code runs there: a docker node started on an older image, and a NixOS node
# rolled back to an older generation. Their remedy is `nft delete table inet swg_reach; nft delete table inet swg_share`.
NODED_REACH_SWEEP_DROPIN=swg-noded.service.d/10-swg-reach-sweep.conf
noded_reach_sweep_dropin(){ # <noded dir> → the drop-in, on stdout
  cat <<EOF
# written by swg-panel (lib/common.sh noded_reach_sweep_dropin) — rewritten on every update
[Service]
ExecStartPre=-/bin/sh -c 'grep -q "^def _reach_drop_table" ${1}/swg-noded 2>/dev/null && exit 0; command -v nft >/dev/null 2>&1 || exit 0; for t in swg_reach swg_share; do nft list table inet \$\$t >/dev/null 2>&1 || continue; nft delete table inet \$\$t && echo "swg-noded: removed nft table inet \$\$t, which this build cannot manage and which would otherwise enforce a frozen policy"; done; exit 0'
EOF
}
ensure_noded_reach_sweep(){ # <noded dir> [<systemd dir>] — HEAL the drop-in beside an existing bare-metal swg-noded unit
  local sd="${2:-/etc/systemd/system}" f want
  [ -f "$sd/swg-noded.service" ] || return 0
  f="$sd/$NODED_REACH_SWEEP_DROPIN"; want="$(noded_reach_sweep_dropin "$1")"
  [ "$(cat "$f" 2>/dev/null)" = "$want" ] && return 0
  if ${DRYRUN:-false}; then echo "    [skip] write $f (the downgrade sweep for the device-access tables)"; return 0; fi
  mkdir -p "$(dirname "$f")" && printf '%s\n' "$want" > "$f" || { warn "couldn't write $f"; return 0; }
  systemctl daemon-reload 2>/dev/null || true
}

awg_go_needs_install(){ # 0 = no amneziawg-go on PATH, one of our EARLIER pinned builds, or a stale build at OUR path
  have amneziawg-go || return 0
  local bin cur; bin="$(command -v amneziawg-go)"
  cur="$(sha256sum "$bin" 2>/dev/null | cut -d' ' -f1)"
  [ -n "$cur" ] || return 1
  case " $AWG_GO_REPLACES " in *" $cur "*) return 0 ;; esac
  # Before the pin, ensure_awg_userspace built upstream HEAD into /usr/local/bin — swgt still carries a 3.0 build from
  # 2026-07-30 (sha dfe3b143…) that no sha list can name, and it is the datapath every awg interface there falls back
  # to. A build without `random_trailers` in its UAPI is older than AmneziaWG 3.1 (version strings lie; this key does
  # not — docs/AWG3-PLAN.md §4.2). Only OUR file is replaced — we write a regular file there, never a link: a binary
  # anywhere else, or a symlink here pointing at one, is the operator's or a package's.
  [ "$bin" = /usr/local/bin/amneziawg-go ] && [ ! -L "$bin" ] && ! grep -aq random_trailers "$bin" 2>/dev/null && return 0
  return 1
}
awg_go_pinned(){ # fetch the pinned amneziawg-go, verify its sha256, install it. 0 = installed
  local arch sha url tmp u
  case "$(uname -m)" in x86_64|amd64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;; *) return 1 ;; esac
  eval "sha=\${AWG_GO_SHA256_$arch:-}"
  [ -n "$sha" ] || return 1
  url="https://github.com/SanityProtocol/swg-panel/releases/download/$AWG_GO_TAG/amneziawg-go-linux-$arch"
  $DRYRUN && { echo "    [skip] fetch + verify $url"; return 0; }
  have curl && have sha256sum || return 1
  tmp="$(mktemp)"
  # Said out loud, and given up on fast: this download used to run silently with up to four 180 s attempts, and on a home
  # box whose link to GitHub crawls (client report 2026-10-06, Russia) the installer sat quiet for minutes right after the
  # last question — which read as "hangs at the TLS check". A transfer under 20 KB/s for 20 s now aborts (and is retried
  # twice); a slow-but-moving one still has 180 s.
  info "downloading the AmneziaWG userspace fallback (amneziawg-go $AWG_GO_TAG) from GitHub — up to a few minutes on a slow link…"
  # GitHub, then the operator's proxy mirrors (SWG_TURN_MIRROR, as for the turn binaries). A mirror is SAFE here, which it
  # is not for those: whatever it serves must match the pin.
  for u in "$url" $(for m in ${SWG_TURN_MIRROR:-}; do printf '%s ' "${m%/}/$url"; done); do
    if curl -fsSL --connect-timeout 15 --max-time 180 --speed-limit 20480 --speed-time 20 --retry 2 --retry-delay 3 "$u" -o "$tmp" \
       && printf '%s  %s\n' "$sha" "$tmp" | sha256sum -c - >/dev/null 2>&1; then
      install -m 0755 "$tmp" /usr/local/bin/amneziawg-go || { rm -f "$tmp"; return 1; }   # a verified file that did not land is not "installed"
      rm -f "$tmp"; return 0
    fi
  done
  rm -f "$tmp"; return 1                                     # a download that does not match the pin is never installed
}

ensure_awg_userspace(){ # last rung: the userspace datapath, so AWG works even with no loadable module. 0/1
  # awg-quick falls back to this ON ITS OWN — its add_if() exits unless the module is missing AND
  # `amneziawg-go` is on PATH, so simply having the binary is the whole wiring. No env var, no config.
  # Slower than the kernel module (which is why it is last), but it is the same datapath our Docker nodes
  # have always run, and it works on boxes where nothing else can: no matching headers, LXC/OpenVZ guests.
  have amneziawg-go && return 0
  $DRYRUN && return 0
  # The pinned build first: no toolchain, no apt source, seconds instead of minutes. The source build below stays only
  # for an architecture with no published asset, or a box that cannot reach it.
  awg_go_pinned && { info "userspace AmneziaWG datapath installed (pinned $AWG_GO_TAG)"; return 0; }
  have go || { have apt-get && run apt-get install -y --no-install-recommends golang-go git ca-certificates >/dev/null 2>&1; }
  have go || { warn "no Go toolchain — install amneziawg-go by hand for a userspace AmneziaWG datapath"; return 1; }
  info "building the userspace AmneziaWG datapath (amneziawg-go)…"
  local w; w="$(mktemp -d)"
  # The same pinned upstream tag as the published build — same source, this box's own Go, so not the same bytes.
  { git_clone_depth1 https://github.com/amnezia-vpn/amneziawg-go "$w/go" "v${AWG_GO_TAG#amneziawg-go-}" \
      && ( cd "$w/go" && run go build -o /usr/local/bin/amneziawg-go . ); } >"$w/go.log" 2>&1 || true
  # Debian STABLE ships a Go far older than amneziawg-go asks for (bookworm: 1.19 vs a go.mod wanting 1.25),
  # and 1.19 predates Go fetching its own toolchain, so it cannot bootstrap out of it either. backports is
  # Debian's own answer to exactly this and carries a current Go — reach for it once before giving up.
  if ! have amneziawg-go && have apt-get && [ -r /etc/os-release ]; then
    local _cn; _cn="$(sed -n 's/^VERSION_CODENAME=//p' /etc/os-release | tr -d '"')"
    if [ -n "$_cn" ] && [ ! -f /etc/apt/sources.list.d/swg-backports.list ]; then
      info "this distro's Go is too old for amneziawg-go — trying ${_cn}-backports…"
      echo "deb http://deb.debian.org/debian ${_cn}-backports main" > /etc/apt/sources.list.d/swg-backports.list
      run apt-get update -qq >/dev/null 2>&1 || true
      run apt-get install -y -t "${_cn}-backports" --no-install-recommends golang-go >/dev/null 2>&1 || true
      { ( cd "$w/go" && run go build -o /usr/local/bin/amneziawg-go . ); } >>"$w/go.log" 2>&1 || true
      have amneziawg-go || rm -f /etc/apt/sources.list.d/swg-backports.list   # leave no source behind if it did not help
    fi
  fi
  if ! have amneziawg-go; then
    # The usual reason is a distro Go older than amneziawg-go's go.mod (Debian 12 ships 1.19 against a
    # go.mod asking 1.25), and Go only learned to fetch its own toolchain in 1.21 — so the old one cannot
    # bootstrap out of it either. Say exactly that: "no userspace datapath" with no reason is unactionable.
    warn "amneziawg-go did not build (this node's Go is $(go version 2>/dev/null | awk '{print $3}' || echo unknown)): $(
      tail -n 2 "$w/go.log" 2>/dev/null | tr '\n' ' ' | cut -c1-160)"
    rm -rf "$w"; return 1
  fi
  rm -rf "$w"
  return 0
}

# ── MANAGE_IFACES: normalise it, then refuse a name this box does not have ────────────────────────────
# ⚠️ ONE READER, BECAUSE THERE ARE TWO INSTALLERS. install-node.sh and install-host.sh each have their own
# `choose_ifaces`, their own `detect_wg` and their own copy of the same "unknown name → fall through to the
# wg default" fallback. The guard was written into ONE of them, so `MANAGE_IFACES=none bootstrap node`
# refused while `MANAGE_IFACES=none bootstrap master` — the more common first install — went on writing
#     "none": {"cmd": ["wg"], "conf": "/etc/wireguard/none.conf"}
# into config.json and the node reported `reconcile: … errors=['none: cannot read interface']` on EVERY
# pass, for ever, under a green install summary. Fixing a twin and not its sibling is how the sibling gets
# found in production. [[csqtt-wdtt-presence-parity]]
#
# Two jobs, both here so they cannot drift apart again:
#   1. Normalise. `MANAGE_IFACES=" "` — a trailing space out of a copy-paste — is non-empty, takes the
#      "explicit list" branch, and puts a blank entry in SELECTED; every later loop then indexes IF_* with
#      an empty subscript and the install dies at `IF_CMD: bad array subscript` mid-Step 1.
#   2. Validate against what the box HAS. `detect_wg` has already walked every conventional wg/awg
#      location and (in install-node) rebuilt confs for running interfaces that had none, so a name absent
#      from IF_CMD names nothing here. Refused rather than dropped: this is an explicit statement of
#      intent, and quietly managing fewer interfaces than asked is the other half of the same lie.
#      Only reachable unattended — the interactive path picks from a list.
#
# ⚠️ IT WRITES $MANAGE_IFACES; IT DOES NOT ECHO IT. The obvious shape —
# `MANAGE_IFACES="$(manage_ifaces_resolve "$MANAGE_IFACES")"` — puts the whole function inside a COMMAND
# SUBSTITUTION, which is a subshell, so `die`'s `exit 1` kills the subshell and nothing else: the parent
# assigns the empty string and carries on as if MANAGE_IFACES had been blank all along. The refusal would
# have printed its message and then let the install do the very thing it refused. Assign a global from the
# CURRENT shell instead, where `die` means what it says. [[installer-convert-session-2026-06]]
#
# Call AFTER detect_wg. Sets MANAGE_IFACES to the normalised value, or `die`s (the caller's `die`).
manage_ifaces_resolve(){
  local _raw="${MANAGE_IFACES:-}" _n _have="" ; local -a _bad=()
  _raw="$(printf '%s' "$_raw" | tr -s ', ' ',' | sed 's/^,//; s/,$//')"
  MANAGE_IFACES="$_raw"
  [ -n "$_raw" ] || return 0
  local _old_ifs="$IFS"; IFS=','; local -a _want=($_raw); IFS="$_old_ifs"
  for _n in ${_want[@]+"${_want[@]}"}; do _n="${_n// /}"; [ -z "$_n" ] && continue
    [ -n "${IF_CMD[$_n]:-}" ] || _bad+=("$_n"); done
  if [ "${#_bad[@]}" -gt 0 ]; then
    # ⚠️ AN EMPTY ASSOCIATIVE ARRAY STILL EXPANDS TO ONE EMPTY WORD, so `printf '%s\n' "${!IF_CMD[@]}"`
    # emits a blank line and a `${_have:-…}` default never fires — the sentence then read "Found here:"
    # followed by nothing, on the box where the fallback mattered most. Ask the SIZE, not the expansion.
    if [ "${#IF_CMD[@]}" -gt 0 ]; then _have="$(printf '%s\n' "${!IF_CMD[@]}" | sort | tr '\n' ' ')"; fi
    die "MANAGE_IFACES names $(b "${_bad[*]}"), which $([ "${#_bad[@]}" -gt 1 ] && echo are || echo is) not on this box.
    Found here: ${_have:-(no wg/awg interfaces at all)}
    Leave MANAGE_IFACES blank to report every interface this box has and adopt them from the panel."
  fi
}

# panel_pin_changed <old_fp> <new_fp> [<url>] — a node re-install found the panel presenting a DIFFERENT certificate from
# the one this node pinned. 0 = trust the new one, 1 = keep the old pin (and PIN_KEPT=yes). NEVER TAKEN SILENTLY: the bare
# installer re-pinned it with one info line and the Docker one with a warning (1.8.8 qualification, round 4). Anyone able
# to intercept this node's traffic presents a different certificate, and the node would hand them its panel token and
# take its peer set from them. With a terminal the operator decides (default: no); without one it is refused, with the
# way to accept it. Priority 1 (fail safe): a node that keeps its old pin stops syncing and keeps serving the peers it
# has, which is undone by accepting later; a node that trusted an impostor cannot be undone from the node. A run that
# keeps the old pin then stops before anything else happens (pin_kept_stop, below).
# ⚠️ THE QUESTION IS PRINTED ON THE TERMINAL ITSELF. It was `read -rp "…" </dev/tty 2>/dev/null`: read -p writes its prompt
# to stderr, and that redirect sent it to /dev/null — at a terminal the operator saw the warning, then silence, with the
# run waiting for an answer to a question nobody could see (1.8.8 qualification, round 6, a Docker node at a pty).
# ⚠️ A CERTIFICATE A PUBLIC CA VOUCHES FOR IS VERIFIED, NOT PINNED. The panel's own advice after moving it to a CA
# certificate is to re-run the node installer on its pinned nodes; `y` here pinned the CA certificate, which its CA
# re-issues every few months — the node went dark at the first renewal, the 2026-09-25 outage by another road. Given the
# URL, a new certificate that verifies through its CA is offered as CA verification instead (PIN_TO_CA=yes on `y`);
# still asked, still refused unattended — with TLS_VERIFY=yes as the way to accept it.
panel_pin_changed(){ local old="$1" new="$2" url="${3:-}" v="" ca=no q _on
  PIN_KEPT=""; PIN_TO_CA=""
  [ -n "$url" ] && panel_ca_ok "$url" && ca=yes
  # ⚠️ A PIN ON RECORD THAT IS NOT A SHA256 DID NOT "CHANGE". Read as a changed certificate, a damaged pin (a stray
  # character, a digit short) printed "CHANGED (was 56f1d0c2…, now 56f1d0c2…)" — the same sixteen characters twice, and a
  # question about a certificate change that did not happen (1.8.8 qualification, round 8). Said as what it is; the
  # decision after it is the same (asked at a terminal, refused unattended).
  _on="$(printf '%s' "$old" | tr -d ':' | tr 'A-F' 'a-f')"
  if ! printf '%s' "$_on" | grep -cxE '[0-9a-f]{64}' >/dev/null; then
    warn "the pin on record for the panel is not a sha256 fingerprint (\"${old:0:24}$([ "${#old}" -gt 24 ] && printf '…')\") — the panel presents sha256 ${new:0:16}…$([ "$ca" = yes ] && printf '%s' ', and a public CA vouches for it')"
  else
    warn "the panel's certificate CHANGED since this node pinned it (was sha256 ${old:0:16}…, now ${new:0:16}…)$([ "$ca" = yes ] && printf '%s' ' — and a public CA vouches for the new one')"
  fi
  if [ "$ca" = yes ]; then
    echo "  Accept it only if the panel moved to a CA certificate on purpose. Accepted, this node verifies the panel through"
    echo "  its CA from now on instead of pinning it — a CA re-issues the certificate every few months, and a pin would stop"
    echo "  the node at the first renewal."
    q="Verify the panel through its CA from now on? (y/N): "
  else
    echo "  Trust the new one only if the panel's certificate was re-issued on purpose — a machine intercepting this"
    echo "  node's traffic presents a different certificate too, and would receive this node's panel token."
    q="Trust the new certificate? (y/N): "
  fi
  if { [ "${SWG_TTY:-/dev/tty}" = /dev/tty ] && { : </dev/tty; }; } 2>/dev/null; then
    printf '  %s' "$q" 2>/dev/null >/dev/tty
    read -r v <"${SWG_TTY:-/dev/tty}" 2>/dev/null || v=""
    case "$v" in [Yy]*)
      if [ "$ca" = yes ]; then PIN_TO_CA=yes; ok "this node verifies the panel's certificate through its CA from now on — the pin is dropped"
      else ok "re-pinned the panel certificate (sha256 ${new:0:16}…)"; fi
      return 0;; esac
  else echo "  $q$(b n)  (no terminal — a changed certificate is never accepted unattended)"; fi
  PIN_KEPT=yes
  if [ "$ca" = yes ]; then
    warn "kept the old pin — this node will not sync until the panel presents that certificate again. If the panel moved to its CA certificate on purpose, re-run this installer with TLS_VERIFY=yes (or at a terminal, and accept it)"
  else
    warn "kept the old pin — this node will not sync until the panel presents that certificate again. If the new one is the panel's, check it on the panel's host (openssl x509 -noout -fingerprint -sha256 -in <its tls/fullchain.pem>) and re-run this installer with TLS_FINGERPRINT=$new (or at a terminal, and accept it)"
  fi
  return 1; }
# …and a run that KEPT the old pin stops right there: before it changes anything on this box, and before the node token
# goes anywhere. It used to carry on — install the programs, recreate the node, post its lifecycle with the token to
# whatever answered (curl -k) — while its own warning named that answer a possible interceptor (1.8.8 qualification,
# round 6). Priority 1, fail safe: the box keeps exactly what it had and serves the peers it has (a node that cannot reach
# a panel it trusts never reconciles), where carrying on would have left new programs under a pin that still does not
# match — the node could not sync afterwards either. Only accepting the certificate (or the panel presenting the old one
# again) brings it back, and the lines above say how. Exit 1: the re-install the caller asked for did not happen.
pin_kept_stop(){
  warn "stopped before changing anything — this box is exactly as it was and serves the peers it has, and the node token was sent nowhere."
  exit 1; }
# panel_ca_ok <url> — 0 when the panel's certificate verifies through the system's CAs for the URL's host (hostname
# included). A probe, never a call with the token: whatever it answers, every call that carries the token checks the
# panel again on its own connection (panel_req).
panel_ca_ok(){ python3 - "$1" <<'PY' 2>/dev/null
import socket, ssl, sys, urllib.parse
r = sys.argv[1]; u = urllib.parse.urlparse(r if "://" in r else "https://" + r)
if u.scheme != "https" or not u.hostname:
    sys.exit(1)
try:
    with socket.create_connection((u.hostname, u.port or 443), timeout=6) as s:
        with ssl.create_default_context().wrap_socket(s, server_hostname=u.hostname):
            pass
except Exception:
    sys.exit(1)
sys.exit(0)
PY
}

# Shared by install-node.sh and install-docker.sh (one probe, not two copies to drift apart).
# 0 when the panel's certificate fails verification ONLY because it is outside its validity window — expired
# (or not yet valid) — which is a real CA certificate the panel has failed to renew, NOT a self-signed one.
# ⚠️ curl calls both "60", and the installers' TLS auto-detect read every 60 as "self-signed" and PINNED the expired
# certificate. The node then synced — until the panel's certificate was renewed, when the pin stopped matching
# and the node went dark (mesh down) until it was re-installed. Seen live 2026-09-25 on a letsencrypt-ip panel.
panel_cert_expired(){ python3 - "$1" <<'PY' 2>/dev/null
import ssl,socket,sys,urllib.parse
r=sys.argv[1]; u=urllib.parse.urlparse(r if '://' in r else 'https://'+r)
host=u.hostname; port=u.port or 443
try:
    with socket.create_connection((host,port),timeout=6) as s:
        with ssl.create_default_context().wrap_socket(s,server_hostname=host):
            pass
except ssl.SSLCertVerificationError as e:
    sys.exit(0 if getattr(e,"verify_code",0) in (9,10) else 1)   # 9 not yet valid, 10 expired
sys.exit(1)
PY
}

# ── swg's own journals (docs/LOGS-PLAN.md §2, §18) ──────────────────────────────────────────────────────────────────
# Every swg unit logs into a journald namespace of its own — swg-panel (the panel, swg-sub, swg-netctl, swg-update) or
# swg-node (swg-noded and everything it runs) — so the disk budget set in Settings → Logs caps only swg's lines and never
# evicts the box's other logs. Set by a DROP-IN, never in the unit: update.sh does not rewrite an existing unit (the
# operator's edits stay), so only a drop-in reaches every box. Written only where systemd ships journald's namespace
# template — a unit naming a namespace without it fails to start. A unit moves at its next start. The namespaces' sizes
# are written at runtime under /run (swg-netctl for swg-panel, swg-noded for swg-node); the units swg-noded writes get
# their drop-in from swg-noded. Read them with swg-logs.
SWG_LOG_NS_DROPIN=swg-ns.conf
# ⚠️ …AND ONLY WHERE A UNIT CAN ACTUALLY RUN IN ONE. The template file is not enough: where systemd runs but mount namespaces
# are refused (an OpenVZ/Virtuozzo-like container, an LXC that denies unshare), a unit naming a namespace exits
# 226/NAMESPACE while the same unit with 1.8.8's settings runs — an update would have written the drop-ins and the panel,
# noded, sub, netctl and update units would not have started again (1.8.9 qualification IN-11, V-LOGS F-3). So a throwaway
# unit is RUN with one (namespace swg-probe; its journald stopped and its directory removed after), once per boot: the
# answer is kept in /run/swg-log-ns (ok | refused), which swg-noded and swg-netctl read too, under the same lock. Refused:
# no drop-in is written and any already there goes (swg_log_ns_clear) — the box logs into the main journal exactly as
# 1.8.8 did, swg-logs reads it there (`--namespace=+` merges the main journal), the budget rows say "Not supported".
SWG_LOG_NS_PROBE="${SWG_LOG_NS_PROBE:-/var/lib/swg-log-ns}"
_swg_log_ns_run_probe(){   # → 0 when a throwaway unit ran with LogNamespace=swg-probe; the probe namespace is cleaned up either way
  local rc=1 u t mid
  t="$(type -P true 2>/dev/null || true)"; [ -n "$t" ] || t=/bin/true
  if have systemd-run && timeout 60 systemd-run --wait --quiet --collect -p LogNamespace=swg-probe "$t" >/dev/null 2>&1; then rc=0; fi
  u="$(systemctl list-units --all --plain --no-legend 'systemd-journald@swg-probe.*' 'systemd-journald-varlink@swg-probe.*' 2>/dev/null | awk '{print $1}' || true)"
  if [ -n "$u" ]; then systemctl stop $u >/dev/null 2>&1 || true; fi   # first: a namespace journald writes its directory again as it exits
  mid="$(cat /etc/machine-id 2>/dev/null || true)"
  if [ -n "$mid" ]; then rm -rf "/var/log/journal/$mid.swg-probe" "/run/log/journal/$mid.swg-probe" 2>/dev/null || true; fi
  return "$rc"; }
swg_log_ns_ok(){ local d t="" v
  for d in /etc/systemd/system /run/systemd/system /usr/lib/systemd/system /lib/systemd/system; do
    if [ -e "$d/systemd-journald@.service" ]; then t=1; fi; done
  [ -n "$t" ] || return 1
  v="$(cat "$SWG_LOG_NS_PROBE" 2>/dev/null || true)"
  case "$v" in ok) return 0;; refused) return 1;; esac
  # a dry run starts no unit, and only root can start one (systemd-run as another user asks polkit): the template answers
  # there, as it did before the probe — every real caller (an installer, update.sh) is root
  if ${DRYRUN:-false} || [ "$(id -u)" != 0 ]; then return 0; fi
  { if have flock; then flock -w 90 9 || true; fi
    v="$(cat "$SWG_LOG_NS_PROBE" 2>/dev/null || true)"           # another prober may have answered while this one waited
    case "$v" in ok|refused) ;; *) v=refused; if _swg_log_ns_run_probe; then v=ok; fi
      printf '%s\n' "$v" > "$SWG_LOG_NS_PROBE" 2>/dev/null || true;; esac
  } 9>>"$SWG_LOG_NS_PROBE.lock"
  [ "$v" = ok ]; }
swg_log_ns_clear(){   # [<unit or unit prefix>…] — refused (above): every swg-ns.conf drop-in on the box goes; named: only those
  # units' (a convert's teardown, swg_log_teardown below). SWG_LOG_NS_CLEARED = how many
  local f u why=" — this box cannot run a unit in a journal namespace"; SWG_LOG_NS_CLEARED=0
  if [ $# -gt 0 ]; then why=""; else set -- '*'; fi
  for u in "$@"; do
    for f in /etc/systemd/system/$u.d/"$SWG_LOG_NS_DROPIN" /run/systemd/system/$u.d/"$SWG_LOG_NS_DROPIN"; do
      [ -e "$f" ] || continue
      if ${DRYRUN:-false}; then echo "    [skip] rm $f$why"; continue; fi
      if rm -f "$f"; then SWG_LOG_NS_CLEARED=$((SWG_LOG_NS_CLEARED + 1)); fi
      rmdir "${f%/*}" 2>/dev/null || true
    done
  done
  return 0; }
# ⚠️ A CONVERT TAKES THE LOG PIECES OF THE UNITS IT REMOVES (1.8.9 qualification IN-6) — teardown_bare_panel and
# lc_teardown_baremetal removed the units and left them: a bare → Docker convert kept swg-update.service.d/swg-ns.conf, so
# the Docker one-click's output went only to a swg-panel journal nothing sizes any more (`journalctl -u swg-update` and the
# compose logs showed nothing), and a host turn proxy the operator kept logged into a swg-node one. Their swg-ns.conf, the
# level drop-ins swg-netctl / swg-noded keep under /run, the namespace's size there, and swg-logs once no bare swg unit is
# left — uninstall.sh's rm_log_ns, which cannot be called from here (it does not source this file). The journals stay: a
# convert keeps the history, an uninstall takes it.
swg_log_teardown(){   # <namespace> <unit or unit prefix>…
  local ns="$1" u; shift
  swg_log_ns_clear "$@"
  for u in "$@"; do rm -f "/run/systemd/system/$u.d/swg-log.conf"; rmdir "/run/systemd/system/$u.d" 2>/dev/null || true; done
  rm -rf "/run/systemd/journald@$ns.conf.d"
  { [ -e /etc/systemd/system/swg-noded.service ] || [ -e /etc/systemd/system/swg-panel-server.service ]; } || rm -f /usr/local/bin/swg-logs
  return 0; }
swg_log_ns_text(){ printf '[Service]\nLogNamespace=%s\n' "$1"; }   # <namespace> → the drop-in, on stdout
# update.sh's form: each <unit> that exists gets its drop-in when it is missing or different. SWG_LOG_NS_CHANGED = how
# many were written; the caller daemon-reloads before it restarts anything. Where no unit can run in a namespace, every
# drop-in there goes instead (SWG_LOG_NS_CLEARED).
swg_log_ns_heal(){   # <namespace> <unit>...
  local ns="$1" u d want; shift; SWG_LOG_NS_CHANGED=0; SWG_LOG_NS_CLEARED=0
  swg_log_ns_ok || { swg_log_ns_clear; return 0; }
  want="$(swg_log_ns_text "$ns")"
  for u in "$@"; do
    [ -f "/etc/systemd/system/$u" ] || continue
    d="/etc/systemd/system/$u.d"
    [ "$(cat "$d/$SWG_LOG_NS_DROPIN" 2>/dev/null)" = "$want" ] && continue
    mkdir -p "$d" && printf '%s\n' "$want" > "$d/$SWG_LOG_NS_DROPIN" && SWG_LOG_NS_CHANGED=$((SWG_LOG_NS_CHANGED + 1))
  done
  return 0   # set -e callers (update.sh): a drop-in that could not be written is not worth aborting an update for
}
# The panel reads its own journal for Settings → Logs' live viewer (docs/LOGS-PLAN.md §6, §23.6): its unit joins
# systemd-journal by a drop-in of its own — scoped to the service, gone with it. Only where the group exists: a unit naming
# a group that does not exist fails to start. Takes effect at the panel's next start.
SWG_JOURNAL_DROPIN=swg-journal.conf
swg_journal_text(){ printf '[Service]\nSupplementaryGroups=systemd-journal\n'; }
swg_journal_heal(){   # → SWG_JOURNAL_CHANGED = 1 when it was written (the caller daemon-reloads)
  local d=/etc/systemd/system/swg-panel-server.service.d want; SWG_JOURNAL_CHANGED=0
  getent group systemd-journal >/dev/null 2>&1 || return 0
  [ -f /etc/systemd/system/swg-panel-server.service ] || return 0
  want="$(swg_journal_text)"
  [ "$(cat "$d/$SWG_JOURNAL_DROPIN" 2>/dev/null)" = "$want" ] && return 0
  mkdir -p "$d" && printf '%s\n' "$want" > "$d/$SWG_JOURNAL_DROPIN" && SWG_JOURNAL_CHANGED=1
  return 0
}
# Docker hosts: their timer units start a oneshot every 10 s (swg-netctl-docker) and 30 s (swg-update), and systemd's
# Starting/Finished lines about them were most of a box's journal (P0 T1). There is no swg-netctl here to follow the
# fleet's level, so the drop-in is static: LogLevelMax=notice drops those lines, SyslogLevel=notice keeps the units' own
# output (rare: a line when they act). swg-update only where no bare-metal panel shares the unit — that panel's
# swg-netctl writes its level-following drop-in under /run, which a same-named file here would mask.
docker_host_log_dropins(){   # → 0; DOCKER_LOG_DROPINS_CHANGED = how many were written (the caller daemon-reloads)
  local u f want; DOCKER_LOG_DROPINS_CHANGED=0
  want="$(printf '[Service]\nLogLevelMax=notice\nSyslogLevel=notice')"
  for u in swg-netctl-docker.service swg-update.service; do
    [ -f "/etc/systemd/system/$u" ] || continue
    [ "$u" = swg-update.service ] && [ -e /usr/local/bin/swg-netctl ] && continue
    f="/etc/systemd/system/$u.d/swg-log.conf"
    [ "$(cat "$f" 2>/dev/null)" = "$want" ] && continue
    mkdir -p "${f%/*}" && printf '%s\n' "$want" > "$f" && DOCKER_LOG_DROPINS_CHANGED=$((DOCKER_LOG_DROPINS_CHANGED + 1))
  done
  return 0
}
