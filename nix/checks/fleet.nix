# T-T1 — the fleet test: a panel and real nodes, on a VLAN, doing the thing.
#
# ⚠️ THIS FILE IS THE THIN SLICE (T-T1 stage 1). It proves the mechanism end to end — a panel and a
# native node built from OUR modules, enrolled through the panel's own API, converging on a peer —
# before breadth is added on top. The scenarios the plan names (the CRITICAL invariant, the D6
# reboot regression, adoption, a WDTT-carrying node) land here once this slice is green.
#
# Why a nixosTest rather than another rig probe: the probes each build a system and RUN one unit out
# of it by hand, which is why the README has a whole section on what that misses (no users, no
# groups, no tmpfiles, `wantedBy` is a symlink you have to go look for). A nixosTest boots the
# activated system, so all of that is real and none of it has to be faked.
#
# ── things this file already knows, so they are not rediscovered ──
#  · The test VMs have NO internet. The panel resolves its provider catalog inline on a cold first
#    sync — ~65 s on a networked box (rig README). Here it fails fast instead; `catalog_index()`
#    never raises and returns {} on error, so nothing downstream cares. Timeouts below still allow
#    for the slow case, because a timeout that is exactly long enough is a flake.
#  · `/api/state` is memoized (STATE_CACHE_TTL, 2 s). Reading it straight after a sync can return
#    the previous build, which reads exactly like the panel having ignored the snapshot. Poll it.
#  · nodes.json entries must be id-keyed. We never hand-write one — every node here is minted by
#    `/api/nodes/create`, which is also the operator's real path, so the stable-id migration that
#    re-keys name-keyed fixtures never enters the picture.
#  · An interface conf legally CHANGES as peers land (swg-agent appends a [Peer] per peer). Identity
#    is the PrivateKey line and the key the interface presents, never the file's sha.
{ srcRoot ? ../.. }:

{ lib, pkgs, ... }:

let
  # The password reaches the panel through a file, which is what the module demands — a Nix path
  # literal is REFUSED, and a value written into an option lands in the world-readable store. In a
  # test VM the store is the test's own, so seeding it from `environment.etc` is fine here and
  # nowhere else; the assertion that catches the real mistake is exercised at eval, not here.
  panelPw = "swg-test-password";
  panelPort = 8443;

  swgPkg = pkgs.callPackage (srcRoot + "/nix/package.nix") { srcRoot = srcRoot; };
in
{
  name = "swg-fleet-native";

  nodes = {
    panel = { ... }: {
      imports = [ (srcRoot + "/nix/modules/panel.nix") ];
      environment.etc."swg-test/panel.env".text = "PANEL_PASSWORD=${panelPw}\n";
      services.swg-panel = {
        enable = true;
        delivery = "native";
        package = swgPkg;
        environmentFile = "/etc/swg-test/panel.env";
        # Widened from the loopback default on purpose: a node has to reach it. There is no ACME in
        # a test VM, so this is plain HTTP — which is exactly what `host` warns you about, and
        # exactly what a fleet on an isolated VLAN wants.
        host = "0.0.0.0";
        port = panelPort;
        sub.enable = false;          # swg-sub has its own probe (T-N11); it is not what this tests.
      };
      networking.firewall.allowedTCPPorts = [ panelPort ];
    };

    node1 = { ... }: {
      imports = [ (srcRoot + "/nix/modules/node.nix") ];
      # The token does not exist until the panel mints one, so the unit starts with a placeholder,
      # gets 401 (which must NOT wipe anything — the CRITICAL invariant's little brother), and is
      # restarted with the real token by the testScript. That is the operator's actual sequence.
      systemd.tmpfiles.rules = [
        # ⚠️ /var/lib, NOT /run. A token on tmpfs is re-created as `placeholder` at every boot, so the
        # reboot scenario below would be measuring this tmpfiles rule rather than the node. `f` only
        # writes when the file is absent, so the real token the testScript puts here survives.
        "d /var/lib/swg-test 0700 root root -"
        "f /var/lib/swg-test/node.env 0600 root root - NODE_TOKEN=placeholder"
      ];

      # ⭐ A WDTT INSTANCE, as a fixture. This is the most important thing in the file.
      # A node with no turn-proxy, WDTT or csqtt never calls `host_sh` AT ALL — which is how a
      # native unit with no shell on its PATH, and 59 dead call sites, survived both T-N8 and T-N1.
      # No binary is needed and none could be fetched (these VMs have no internet): the RECORD alone
      # is what makes the daemon reach for `sh -c`, which is the code path under test. Same fixture
      # shape probeSH-run.sh used to measure 27 failed calls in 45 seconds on a shell-less build.
      #
      # An activation script rather than `environment.etc`: the daemon REWRITES this record, and an
      # environment.etc entry is a read-only symlink into the store. Rather than a fixture, that
      # would be a second bug wearing the first one's clothes.
      system.activationScripts.swgWdttFixture = {
        text = ''
          mkdir -p /etc/swg-agent /opt/swg-wdtt/wdtt0
          printf 'KEYS\n' > /opt/swg-wdtt/wdtt0/wg-keys.dat
          chmod 700 /opt/swg-wdtt /opt/swg-wdtt/wdtt0
          if [ ! -s /etc/swg-agent/wdtt.json ]; then
            printf '%s\n' '{"wdtt":[{"iface":"wdtt0","owner_password":"fixture","listen":"0.0.0.0:9000"}]}' \
              > /etc/swg-agent/wdtt.json
          fi
        '';
        deps = [ ];
      };
      services.swg-node = {
        enable = true;
        delivery = "native";
        package = swgPkg;
        environmentFile = "/var/lib/swg-test/node.env";
        panelUrl = "http://panel:${toString panelPort}";
        endpoint = "192.168.1.2";
        verifyPanelTls = false;
        # A bootstrap interface, so there is somewhere for a peer to land and so node-entrypoint.sh's
        # own interface bring-up (D15 — the native arm's bootstrap) is exercised rather than assumed.
        interfaces = "awg0:51820:10.8.0.1/24";
        turnManage = true;   # so the daemon manages host units, which is what reaches host_sh
        # Declared, not left empty: the module warns otherwise, and it is right to — an interface the
        # panel creates gets its port at RUNTIME while a declarative firewall is evaluated at BUILD
        # time, so a peer would sync, report healthy and never hand-shake. T-P10's whole point.
        udpPortRanges = [ { from = 51820; to = 51899; } ];
      };
    };
  };

  testScript = ''
    import json
    import time

    start_all()

    # ── the panel is ALIVE before anything is asserted about it ────────────────────────────────
    # "no error in the log" is not aliveness: a panel that never started logs no failures either.
    panel.wait_for_unit("swg-panel-server.service")
    panel.wait_for_open_port(${toString panelPort})
    print(panel.succeed("systemctl show -p ActiveState -p SubState swg-panel-server.service"))

    # Every scenario reports itself on one line. Two reasons, both learned rather than stylistic:
    # a green run otherwise says only "the build succeeded", which is equally true of a suite whose
    # scenarios were deleted; and the harness around this greps these lines and REFUSES a run that
    # is missing any of them, so the suite cannot silently shrink. Keep the names in step with
    # EXPECTED in .campaign/nixlab/probeT1-run.sh.
    def ok(name, detail=""):
        print(f"T1-ASSERT {name} OK {detail}")

    def api(path, data=None, tok=None):
        """One API call from the PANEL machine, returning parsed JSON.

        Fails loudly on a non-JSON body: the panel answers 404 with HTML when a path is wrong, and
        a parse error there reads exactly like 'the panel is dead' if it is swallowed."""
        cmd = "curl -sS -m 60 -b /tmp/jar -c /tmp/jar"
        if tok:
            cmd += f" -H 'Authorization: Bearer {tok}'"
        if data is not None:
            cmd += " -H 'Content-Type: application/json' -d " + json.dumps(json.dumps(data))
        cmd += f" http://127.0.0.1:${toString panelPort}{path}"
        raw = panel.succeed(cmd)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise Exception(f"{path} did not return JSON — first 300 bytes: {raw[:300]!r}")

    # The seed's own verdict, always printed. It says which branch ExecStartPre took, and without it
    # a refused login is indistinguishable from a login that was never seeded.
    print(panel.succeed("journalctl -u swg-panel-server.service --no-pager | grep -i 'swg-panel:' || echo '(no seed line in the journal)'"))

    # ── the seeded login works, which is also T-P5's claim re-proven on an activated system ────
    # ⚠️ The fields are `username`/`password`. The first draft sent `user`/`pass`, and the panel
    # refused BOTH the real credential and the deliberate wrong one — so the "a wrong password is
    # refused" control below was GREEN while nothing worked. A control that cannot tell a working
    # system from a broken one is the failure this project keeps paying for; it is the POSITIVE
    # assert that caught it. Keep them as a pair, in this order.
    with subtest("the module-seeded login authenticates"):
        r = api("/api/login", {"username": "admin", "password": "${panelPw}"})
        assert r.get("ok"), f"login refused: {r}"
        ok("seeded-login", "the module-seeded credential authenticates")

    with subtest("a wrong password is refused"):
        bad = api("/api/login", {"username": "admin", "password": "not-the-password"})
        assert not bad.get("ok"), f"ANY password is accepted: {bad}"
        api("/api/login", {"username": "admin", "password": "${panelPw}"})   # log back in
        ok("wrong-password-refused", "so the success above means the hash matched")

    # ── mint a node the way the operator does ──────────────────────────────────────────────────
    with subtest("the panel mints a node and a token"):
        r = api("/api/nodes/create", {"name": "node1"})
        assert r.get("ok"), f"nodes/create failed: {r}"
        node_id, token = r["data"]["id"], r["data"]["token"]
        print(f"minted node id={node_id} token={token[:6]}…")
        ok("node-minted", f"id={node_id}")

    # ── hand the node its token and let the real daemon converge ───────────────────────────────
    # Diagnostics BEFORE the assert, not after it. The node boots with a placeholder token on
    # purpose (see the tmpfiles rule) — so this is also where we see what a node does when the panel
    # rejects it, which must be "keep trying", never "wipe anything".
    # ⚠️ The native node's unit is `swg-noded`, NOT `swg-node` — the same name the bare-metal
    # installer uses, which is the whole point (a node is a node however it was installed). The
    # container arm's is `''${backend}-swg-node` (escaped: testScript is a Nix string, so a bare
    # $-brace is INTERPOLATED — this comment cost a run). Asking for the wrong unit returns
    # "could not be found", which reads exactly like a module that failed to define anything.
    print(node1.succeed("systemctl status swg-noded.service --no-pager -l || true"))
    print(node1.succeed("journalctl -u swg-noded.service --no-pager | tail -40 || true"))
    print(node1.succeed("cat /var/lib/swg-test/node.env || echo '(no env file — the tmpfiles rule did not land)'"))

    # ⚠️ THE CONTROL FOR EVERYTHING BELOW, and it costs nothing: the node has been running since
    # boot with `NODE_TOKEN=placeholder`, a token this panel never minted. If it were online HERE,
    # the "it synced" assert further down would be measuring nothing. A good token brings a node
    # online in ~6 s (measured), so 30 s of a bad one not appearing is a real answer, not a race.
    with subtest("a token the panel never minted does not enrol"):
        node1.succeed("grep -q placeholder /var/lib/swg-test/node.env")   # the premise, stated
        time.sleep(30)
        st = api("/api/state")
        entry = next((n for n in (st.get("data") or {}).get("nodes") or []
                      if n.get("id") == node_id), None)
        assert entry is not None, "the minted node vanished from /api/state"
        assert entry.get("status") != "online", (
            f"a node presenting an unminted token came ONLINE — enrolment is not authenticated: {entry}")
        print(f"unminted token → status={entry.get('status')!r}, as it must be")
        ok("unminted-token-refused", f"status={entry.get('status')!r}")

    with subtest("the node enrols and syncs"):
        node1.succeed(f"echo NODE_TOKEN={token} > /var/lib/swg-test/node.env")
        node1.succeed("chmod 600 /var/lib/swg-test/node.env")
        # `reset-failed` first: the unit retries on-failure and can have hit its start limit while
        # the token was a placeholder, in which case a plain `restart` is refused and the failure
        # reads as "the node is broken" rather than "systemd is rate-limiting us".
        node1.succeed("systemctl reset-failed swg-noded.service || true")
        node1.succeed("systemctl restart swg-noded.service")
        node1.wait_for_unit("swg-noded.service")

        # Poll /api/state rather than sleeping: it is memoized for 2 s and a cold panel's first
        # sync is slow, so a fixed sleep is a flake generator either way.
        #
        # ⚠️ The field is `status` ("online" | "offline" | "dangling"), NOT a bare `online` key —
        # that one lives on a DIFFERENT structure in the same response. The first draft polled
        # `n.get("online")`, which is absent here, so the loop could never have succeeded no matter
        # how well the node behaved. It then hammered /api/state ~1000 times in 180 s and buried
        # every diagnostic above it in the log. Both halves of that are fixed here: the field, and
        # a poll that breathes.
        seen = {}

        def node_reported(_):
            time.sleep(3)                      # the node syncs every 5 s; polling faster only floods
            st = api("/api/state")
            for n in (st.get("data") or {}).get("nodes") or []:
                if n.get("id") == node_id:
                    seen.clear(); seen.update(n)
                    return n.get("status") == "online"
            return False

        try:
            retry(node_reported, timeout_seconds=180)
        finally:
            # UNCONDITIONAL, and after the wait rather than before it: the interesting journal is the
            # one written while the node was trying with a real token, and on the failure path it is
            # the only thing that says why.
            print("panel's view of the node:", json.dumps(
                {k: seen.get(k) for k in ("id", "name", "status", "last_seen", "kind", "platform",
                                          "declarative", "peer_count", "hostname")}, indent=2)
                  if seen else "(the panel has no entry with this id at all)")
            print(node1.succeed("journalctl -u swg-noded.service --no-pager | tail -60 || true"))

        ok("node-enrolled", "online after presenting the minted token")
        print(panel.succeed("cat /var/lib/swg-panel/nodes.json"))

    # ── the interface the node bootstrapped is real, on the kernel datapath ────────────────────
    def unit_path(m, unit="swg-noded.service"):
        """The PATH systemd gives that unit.

        Deliberately NOT `environment.systemPackages`: a node's tools come from the module's own
        `path`, and going through it is what proves they are there. Adding amneziawg-tools to the
        test machine instead would have made this assert pass on a module that ships none — which
        is the same shape as the bug that left the native unit with no shell and 59 dead `host_sh`
        call sites. `awg` on the login shell's PATH is 127 here, and that is correct."""
        raw = m.succeed(
            f"systemctl show -p Environment --value {unit} | tr ' ' '\\n' | grep '^PATH=' | head -1 | cut -d= -f2-"
        ).strip()
        assert raw, f"{unit} declares no PATH — the module's `path` is empty or the unit is gone"
        return raw

    with subtest("awg0 is up and the node presents its key"):
        print(node1.succeed("ip -br link show awg0"))
        npath = unit_path(node1)
        print(f"swg-noded PATH has {len(npath.split(':'))} entries")
        pub = node1.succeed(f"PATH={npath} awg show awg0 public-key").strip()
        # A WireGuard/AmneziaWG public key is 32 bytes base64 = 44 chars ending in '='.
        assert len(pub) == 44 and pub.endswith("="), f"awg0 has no usable public key: {pub!r}"
        print(f"awg0 public key: {pub}")

        # CONTROL for the assert above: the same call WITHOUT the unit's PATH must fail. Without
        # this, a green line here would be equally true of a test that found `awg` somewhere else
        # entirely and never exercised the module's path at all.
        node1.fail("awg show awg0 public-key")
        ok("iface-up-kernel-datapath", f"awg0 pub={pub[:12]}…, and bare `awg` is 127 as it must be")

    # ── ⭐ the shell the native unit did not have ──────────────────────────────────────────────
    # This is what the WDTT fixture buys, and it is the assert that would have caught 4848680.
    # `host_sh` runs `sh -c` at 59 call sites; NixOS gives a unit exactly the packages in `path`
    # plus five its `apply` appends, and none of those provides a shell. Every call then returns
    # 127 — quietly, because `sh -c` hands back the command's own exit code, so a missing binary
    # is indistinguishable from "the operation failed".
    with subtest("the node's host_sh calls actually run"):
        # Aliveness FIRST: absence of rc=127 is equally true of a daemon that never called host_sh,
        # which is precisely how this bug survived two probes. Prove the call path was reached.
        node1.wait_until_succeeds(
            "journalctl -u swg-noded.service --no-pager | grep -qE 'wdtt|host_sh'", timeout=90)
        # NOT `log` — the driver binds that name to its own AbstractLogger, and shadowing it is a
        # type error rather than a runtime surprise (the driver type-checks testScript, which is the
        # only reason this was a 12-second failure instead of a confusing one).
        journal = node1.succeed("journalctl -u swg-noded.service --no-pager")
        bad = [ln for ln in journal.splitlines()
               if "host_sh rc=127" in ln or "No such file or directory: 'sh'" in ln]
        assert not bad, "host_sh has no shell on this node:\n" + "\n".join(bad[:5])
        print(f"host_sh: {len(bad)} shell-less calls (must be 0); the WDTT record reached the call path")
        ok("host-sh-has-a-shell", "the WDTT record reached the call path and none returned 127")

    # ── the product: a peer, deployed by the panel, landing on the live interface ──────────────
    with subtest("a peer created in the panel lands on the node"):
        # A real keypair, made with the node's own tools — the browser does this in production and
        # the private half never reaches the panel, which is why only the public half appears here.
        npath = unit_path(node1)
        peer_pub = node1.succeed(f"PATH={npath} sh -c 'wg genkey | wg pubkey'").strip()
        r = api("/api/peers/create", {
            "pubkey": peer_pub,
            "targets": [{"node": node_id, "iface": "awg0", "ip": "10.8.0.2"}],
        })
        assert r.get("ok"), f"peers/create refused: {r}"

        node1.wait_until_succeeds(
            f"PATH={npath} awg show awg0 peers | grep -q {peer_pub}", timeout=120)
        print(node1.succeed(f"PATH={npath} awg show awg0"))
        ok("peer-deployed", f"{peer_pub[:12]}… is on the live interface")

    # ── ⭐ THE CRITICAL INVARIANT ──────────────────────────────────────────────────────────────
    # swg-noded reconciles ONLY on a valid HTTP 200 carrying a `desired` object. A network error, a
    # 401 or a TLS-pin failure SKIPS the pass. A panel outage must never wipe a node's peers — this
    # is the one behaviour in the whole product that is worth more than the panel itself.
    with subtest("a panel outage does not wipe the node's peers"):
        panel.succeed("systemctl stop swg-panel-server.service")
        panel.wait_until_fails("systemctl is-active --quiet swg-panel-server.service")

        # Several sync intervals (nodeInterval defaults to 5 s), so the node has genuinely tried and
        # failed a number of times rather than merely not having got round to it yet.
        time.sleep(45)
        tries = node1.succeed(
            "journalctl -u swg-noded.service --since '-45s' --no-pager | grep -ciE 'refused|error|failed|unreachable' || true").strip()
        print(f"node logged {tries} failure-ish lines while the panel was down")

        still = node1.succeed(f"PATH={npath} awg show awg0 peers")
        assert peer_pub in still, (
            "THE CRITICAL INVARIANT IS BROKEN: the peer disappeared while the panel was down.\n"
            f"awg show awg0 peers:\n{still}")
        print("peer survived the outage")
        ok("critical-invariant", f"panel stopped 45 s, {tries} failures logged, peer still there")

        panel.succeed("systemctl start swg-panel-server.service")
        panel.wait_for_open_port(${toString panelPort})

    # ── ⭐ THE D6 REGRESSION ───────────────────────────────────────────────────────────────────
    # On a host where `systemctl enable` cannot work (a read-only unit directory), nothing systemd
    # brings an interface back after a reboot. What does is the node's OWN bootstrap — D15:
    # node-entrypoint.sh walks the conf directory and raises every persisted interface BEFORE the
    # daemon starts. The panel is deliberately DOWN across the reboot, so nothing can be attributed
    # to a sync: if awg0 and its peer are there afterwards, the node did it alone.
    with subtest("a reboot with the panel unreachable still brings interfaces up"):
        panel.succeed("systemctl stop swg-panel-server.service")
        panel.wait_until_fails("systemctl is-active --quiet swg-panel-server.service")

        node1.shutdown()
        node1.start()
        node1.wait_for_unit("multi-user.target")
        node1.wait_for_unit("swg-noded.service")

        npath = unit_path(node1)
        node1.wait_until_succeeds(f"PATH={npath} awg show awg0 public-key", timeout=90)
        back = node1.succeed(f"PATH={npath} awg show awg0 peers")
        assert peer_pub in back, (
            "D6 REGRESSION: the interface came back without its peer, with the panel down.\n"
            f"awg show awg0 peers:\n{back}")
        # And the identity is the same interface, not a fresh one: a re-minted key would silently
        # disconnect every client. Assert the PrivateKey line, never the conf's sha — swg-agent
        # appends a [Peer] section per peer, so the FILE legitimately changes.
        pub_after = node1.succeed(f"PATH={npath} awg show awg0 public-key").strip()
        assert pub_after == pub, f"awg0 came back with a DIFFERENT key: {pub} -> {pub_after}"
        ok("d6-reboot-offline", "awg0 + its peer came back with the panel down, same key")

        panel.succeed("systemctl start swg-panel-server.service")
        panel.wait_for_open_port(${toString panelPort})
        api("/api/login", {"username": "admin", "password": "${panelPw}"})

    # ── ⭐ ADOPTION'S SHARPEST CONTROL — deliberately LAST, it destroys the fleet state ────────
    # T-M1 measured this on the rig and it is the reason nix/README.md carries a warning: hand an
    # already-enrolled box a FRESHLY MINTED token instead of the one it holds and the panel gets TWO
    # nodes for one machine, while the live interface is stripped of every peer — the new node's
    # desired set is empty, and the node converges to it faithfully. That is the product working
    # exactly as designed, which is what makes it dangerous.
    with subtest("a re-minted token makes a second node and strips the interface"):
        r = api("/api/nodes/create", {"name": "node1-remint"})
        assert r.get("ok"), f"nodes/create refused: {r}"
        second_id, second_token = r["data"]["id"], r["data"]["token"]

        node1.succeed(f"echo NODE_TOKEN={second_token} > /var/lib/swg-test/node.env")
        node1.succeed("systemctl restart swg-noded.service")

        npath = unit_path(node1)
        node1.wait_until_succeeds(
            f"! (PATH={npath} awg show awg0 peers | grep -q {peer_pub})", timeout=120)

        st = api("/api/state")
        ids = {n.get("id") for n in (st.get("data") or {}).get("nodes") or []}
        assert {node_id, second_id} <= ids, (
            f"expected BOTH the original and the re-minted node, got {ids}")
        ok("adoption-remint-strips",
           f"one box, two nodes ({node_id}, {second_id}); awg0 lost its peer, as measured in T-M1")
  '';
}
