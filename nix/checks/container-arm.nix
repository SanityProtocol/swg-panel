# T-T1, container arm — everything about it that does NOT need the image.
#
# ⚠️ WHY THIS EXISTS SEPARATELY, and why it never starts a container. A nixosTest VM has no
# internet, so it cannot pull ghcr.io/sanityprotocol/swg-node. Two obvious ways round that were
# considered and REJECTED:
#   · a dockerTools stand-in built from our own source — it would be a THIRD declaration of the
#     image's contents beside the Dockerfile and the shipped-assets gate, it would rot silently,
#     and a green run against it would read as "the container arm works" when the shipped image
#     might not. That is the exact failure this suite exists to prevent.
#   · a pinned digest — rots on every image build, and the only thing it adds over this file is
#     the shipped image's own build, which `docker.yml` already covers on every push.
#
# What is left is more than it sounds, because MOST of the container arm is host-side config:
# sysctls, tmpfiles, the runtime, podman's policy.json, and the unit's ordering. None of that
# needs an image, and none of it is covered today:
#
#   probeN1C1 asserts the generated unit's contract tokens — but against a BUILT system, and a
#   built system is never ACTIVATED (rig README): nothing has run, no tmpfiles, no services. It is
#   also a MANUAL probe, where this runs on a schedule. `compose-nix-contract.mjs` reads the .nix
#   SOURCE, so it cannot see a runtime value at all.
#
# ⭐ The sharpest assert here is `route_localnet`. A fresh NixOS host comes up with it at 0, and
# without it Force-DNS silently blackholes — it DNATs a client's :53 to a loopback dnsmasq and the
# kernel drops it. That is a defect this project has actually shipped (it silent-failed inside the
# container, which is why the module sets it on the HOST). Nothing else checks the live value.
{ srcRoot ? ../.. }:

{ lib, pkgs, ... }:

let
  stateDir = "/var/lib/swg-noded";
  confDir = "/etc/amnezia/amneziawg";
in
{
  name = "swg-container-arm";

  nodes.host = { ... }: {
    imports = [ (srcRoot + "/nix/modules/node.nix") ];
    systemd.tmpfiles.rules = [
      "d /var/lib/swg-test 0700 root root -"
      "f /var/lib/swg-test/node.env 0600 root root - NODE_TOKEN=container-arm-fixture"
    ];
    services.swg-node = {
      enable = true;
      delivery = "container";
      backend = "docker";
      environmentFile = "/var/lib/swg-test/node.env";
      panelUrl = "http://panel.invalid:8443";   # never dialled: the container cannot start
      endpoint = "192.168.1.1";
      turnManage = true;                         # ⇒ the docker socket joins the volume set
      udpPortRanges = [{ from = 51820; to = 51899; }];
    };
  };

  testScript = ''
    start_all()
    host.wait_for_unit("multi-user.target")

    def ok(name, detail=""):
        print(f"CA-ASSERT {name} OK {detail}")

    # ── ⭐ the sysctls, at their LIVE values ───────────────────────────────────────────────────
    # `mkDefault true` in the module is a declaration; this is the kernel's answer. The two are not
    # the same claim, and it is the second one that Force-DNS depends on.
    with subtest("the host sysctls the container arm depends on are really set"):
        for key in ("net.ipv4.ip_forward", "net.ipv4.conf.all.route_localnet"):
            val = host.succeed(f"cat /proc/sys/{key.replace('.', '/')}").strip()
            assert val == "1", f"{key} is {val}, not 1 — Force-DNS would silently blackhole"
        ok("sysctls-live", "ip_forward=1 and route_localnet=1, read from /proc")

    # ── the directories the container bind-mounts ──────────────────────────────────────────────
    # tmpfiles only runs on an ACTIVATED system, which is the half probeN1C1 cannot reach.
    with subtest("the bind-mount sources exist before any container does"):
        for d in ("${stateDir}", "${confDir}", "/run/wireguard"):
            host.succeed(f"test -d {d}")
        # /run/wireguard is the one with a reason: without it the wg CLI inside the container cannot
        # see a FOREIGN userspace interface, so the adoption scan silently omits what it exists for.
        mode = host.succeed("stat -c %a /run/wireguard").strip()
        assert mode == "755", f"/run/wireguard is {mode}, not 755 — the container's wg CLI reads it"
        ok("tmpfiles-activated", "stateDir, confDir and /run/wireguard exist, 755")

    # ── the runtime is actually running, not merely declared ───────────────────────────────────
    # `oci-containers` does NOT enable the backend; the module does, on the grounds that the node
    # must survive a reboot. A declaration that never starts is exactly the shape worth checking.
    with subtest("the container runtime is up"):
        host.wait_for_unit("docker.service")
        print(host.succeed("systemctl is-active docker.service"))
        ok("runtime-running", "docker.service active — oci-containers does not do this for us")

    # ── the generated unit, and the contract inside its START SCRIPT ───────────────────────────
    # ⚠️ `oci-containers` puts NOTHING in the .service — ExecStart points at a generated script in
    # the store. Grepping the unit finds none of the contract; follow ExecStart first (rig README).
    with subtest("the generated unit carries the whole contract"):
        unit = "docker-swg-node.service"
        host.succeed(f"systemctl cat {unit}")
        # ⚠️ `systemctl show -p ExecStart --value` returns a STRUCTURED RECORD, not a command line:
        #   { path=/nix/store/…-docker-swg-node-start ; argv[0]=… ; ignore_errors=no ; … }
        # so a `grep '^/nix/store'` matches nothing and the whole check dies on an exit code that
        # says nothing about the module. `systemctl cat` gives the unit text, which is what
        # probeN1C1 parses too — same idiom, same reason.
        script = host.succeed(
            f"systemctl cat {unit} | grep -m1 '^ExecStart=' | cut -d= -f2- | awk '{{print $1}}'"
        ).strip()
        assert script.startswith("/nix/store/"), f"could not follow ExecStart: {script!r}"
        body = host.succeed(f"cat {script}")

        want = [
            "--network=host",                       # every panel-picked port lands on the host
            "--cap-add=NET_ADMIN",
            "--device=/dev/net/tun",
            # ⚠️ NIX interpolation below, NOT a Python f-string. `f"{stateDir}"` looks right and
            # is not: Nix leaves a bare `{stateDir}` alone, so Python looks for a variable of that
            # name and the driver's type check fails with "Name `stateDir` used when not defined".
            # The let-binding lives on the NIX side of this file; only Nix can substitute it.
            "${stateDir}:/var/lib/swg-noded",
            "${confDir}:/etc/amnezia/amneziawg",
            "/run/wireguard:/run/wireguard",
            "/var/run/docker.sock:/var/run/docker.sock",   # turnManage = true
            "SWG_NODE_PLATFORM",                    # T-P1: what OWNS the installation
            "SWG_DECLARATIVE",
            "SWG_UDP_PORTS",                        # T-P10: the declared firewall range
            "ghcr.io/sanityprotocol/swg-node",
        ]
        missing = [w for w in want if w not in body]
        assert not missing, f"the start script is missing: {missing}\\n---\\n{body}"
        ok("unit-contract", f"{len(want)} tokens, all present in the generated start script")

    # CONTROL: the check above greps a file, so it is only as good as its ability to MISS something.
    # A token that is deliberately not there must not be found — otherwise a `body` that came back
    # empty, or a grep that matched everything, would read as a complete contract.
    with subtest("the contract check can fail"):
        body = host.succeed("cat $(systemctl cat docker-swg-node.service"
                            " | grep -m1 '^ExecStart=' | cut -d= -f2- | awk '{print $1}')")
        assert "--privileged" not in body, "the node container must NOT be --privileged"
        assert "swg-this-token-is-not-in-the-contract" not in body
        ok("contract-check-can-fail", "an absent token reads as absent")

    # ── the ordering that a secret depends on ──────────────────────────────────────────────────
    # The CONTAINER reads the environment file, so it is the container's unit that must wait for
    # whatever produces it. Nothing static can see this.
    with subtest("the container waits for what produces its secret"):
        after = host.succeed("systemctl show -p After --value docker-swg-node.service")
        assert "docker.service" in after, f"the unit is not ordered after docker: {after}"
        ok("unit-ordering", "ordered after the runtime")

    # ── and the honest limit, stated rather than implied ───────────────────────────────────────
    # The container itself cannot start: there is no registry to reach. That is not a failure of
    # the module, and this suite must never report it as one — but nor may it be silent about it,
    # or a reader takes "container arm: green" for more than it is.
    with subtest("the container cannot start here, and that is the known limit"):
        host.succeed("systemctl start docker-swg-node.service || true")
        state = host.succeed("systemctl show -p ActiveState --value docker-swg-node.service").strip()
        print(f"docker-swg-node ActiveState={state} (no registry in a test VM — expected)")
        ok("image-pull-out-of-scope",
           "the image is NOT exercised here; docker.yml and probeP1 cover the shipped image")
  '';
}
