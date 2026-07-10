/* turn-artifacts.js — shared, buildless, dependency-free.
 *
 * Builds the per-fork CLIENT import artifact for a peer deployed behind a vk-turn-proxy, from a plain
 * WireGuard/AmneziaWG .conf string. Loaded as a classic script by BOTH the admin SPA (index.html →
 * app.js) and the public subscription page (sub.html → sub.js), so the fork wire-formats live in ONE
 * place — there is exactly one copy to keep in step when a fork changes its format.
 *
 * SECURITY: this file holds NO secrets and does NO I/O. It is pure encoding: it takes a config the
 * caller already has (the private key comes from the caller — in the subscription page, decrypted
 * client-side from the URL fragment) and returns text/links. It never reads state, never talks to a
 * server, and is identical whether it runs in the operator's browser or a subscriber's phone.
 *
 * FORMAT SYNC (checked 2026-07): only anton48 ships an actual generator (quick_link.py, git-only, not a
 * release asset), so reimplementing the documented, versioned formats here is equivalent and simpler.
 * Schema versions targeted (bump deliberately on a fork's major release — the update flow only pulls a
 * newer server binary, it can't change these):
 *   • anton48   vkturnproxy:// JSON  "version": 1
 *   • samosvalishe freeturn://  JSON "v": 1
 *   • kiper292  #@wgt: comments, PeerType SERVER-COUPLED → proxy_v2 (what a "kiper292" proxy IS)
 *   • WINGS-N   wingsv:// = 0x12 ‖ zlib(protobuf Config); hand-encoded. Config.ver = 1.
 */
(function (root) {
  "use strict";

  var AWG_ORDER = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4", "I1", "I2", "I3", "I4", "I5"];

  // ── byte helpers ──
  function b64ToBytes(b64) {
    try { var s = atob(String(b64 || "").trim()); var a = new Uint8Array(s.length); for (var i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a; }
    catch (_) { return new Uint8Array(0); }
  }
  function hexToBytes(h) { h = String(h || "").replace(/[^0-9a-fA-F]/g, ""); var a = new Uint8Array(h.length >> 1); for (var i = 0; i < a.length; i++) a[i] = parseInt(h.substr(i * 2, 2), 16); return a; }
  function ipToBytes(addr) {
    addr = String(addr || "").trim();
    if (addr.indexOf(":") >= 0) {                                    // IPv6 (handles :: expansion)
      var parts = addr.split("::");
      var head = parts[0], tail = parts[1];
      var h = head ? head.split(":").filter(Boolean) : [], t = tail ? tail.split(":").filter(Boolean) : [];
      var groups = addr.indexOf("::") >= 0 ? h.concat(Array(Math.max(0, 8 - h.length - t.length)).fill("0"), t) : addr.split(":");
      var b = new Uint8Array(16); groups.slice(0, 8).forEach(function (g, i) { var v = parseInt(g || "0", 16) || 0; b[i * 2] = v >> 8; b[i * 2 + 1] = v & 0xff; }); return b;
    }
    var p = addr.split("."), bb = new Uint8Array(4); for (var i = 0; i < 4; i++) bb[i] = (+p[i]) || 0; return bb;
  }

  // ── protobuf primitives (hand-serialize, no lib) ──
  function pbVarint(n) { var o = [], v = Math.floor(n); while (v > 127) { o.push((v % 128) | 0x80); v = Math.floor(v / 128); } o.push(v & 0x7f); return o; }
  function pbKey(f, w) { return pbVarint((f << 3) | w); }
  function pbLen(f, arr) { return pbKey(f, 2).concat(pbVarint(arr.length), arr); }          // length-delimited (string / bytes / message)
  function pbVar(f, n) { return pbKey(f, 0).concat(pbVarint(n)); }                           // varint (uint / bool / enum)
  function pbStr(f, s) { return pbLen(f, [].slice.call(new TextEncoder().encode(String(s)))); }
  function pbBin(f, u8) { return pbLen(f, [].slice.call(u8)); }
  function epBytes(hostport) { var s = String(hostport || ""); var i = s.lastIndexOf(":"); if (i < 0) return null; return pbStr(1, s.slice(0, i)).concat(pbVar(2, +s.slice(i + 1) || 0)); }

  // Parse a client .conf back into fields (the private key lives only in the caller's config).
  function parseFullConf(text) {
    var m = function (re) { return (text.match(re) || [])[1]; };
    var dnsLine = m(/DNS\s*=\s*(.+)/);
    var awg = {};
    for (var i = 0; i < AWG_ORDER.length; i++) { var k = AWG_ORDER[i]; var v = m(new RegExp("^" + k + "\\s*=\\s*(\\S+)", "m")); if (v != null) awg[k] = v; }
    return {
      privkey: m(/PrivateKey\s*=\s*(\S+)/) || "",
      address: m(/Address\s*=\s*(.+)/) || "",
      dns: dnsLine ? dnsLine.split(",").map(function (s) { return s.trim(); }).filter(Boolean) : [],
      mtu: m(/MTU\s*=\s*(\d+)/) || 1280,
      awg_params: awg,
      server_pubkey: m(/PublicKey\s*=\s*(\S+)/) || "",
      psk: m(/PresharedKey\s*=\s*(\S+)/) || "",
      allowed: m(/AllowedIPs\s*=\s*(.+)/) || "0.0.0.0/0, ::/0",
      endpoint: m(/Endpoint\s*=\s*(\S+)/) || "",
      keepalive: m(/PersistentKeepalive\s*=\s*(\d+)/) || 25
    };
  }

  // ── fork id from a service name (vk-turn-proxy-<fork>-<port>) ──
  function label(service) {
    var s = (service || "turn-proxy").replace(/^vk-turn-proxy-?/, "") || "turn";
    s = s.replace(/-\d+$/, "") || "turn";
    return s === "main" ? "cacggghp" : s;             // legacy "main" services still display as cacggghp
  }

  // ── WINGS-N wingsv:// link ── wingsv:// + base64url( 0x12 ‖ zlib( proto.Marshal(wingsv.Config) ) ).
  function wingsvConfigBytes(cf, tp, vk, rawConf) {
    var LOCAL = "127.0.0.1:9000";
    var isAwg = !!(cf.awg_params && Object.keys(cf.awg_params).length);   // AmneziaWG interface → awg transport
    var pep = epBytes(tp.listen);
    var turn = [];
    if (pep) turn = turn.concat(pbLen(1, pep));                     // endpoint = public proxy (internet ip:listen)
    turn = turn.concat(pbStr(2, vk));                              // link
    turn = turn.concat(pbLen(6, epBytes(LOCAL)));                  // local_endpoint = local turn listen (127.0.0.1:9000)
    turn = turn.concat(pbVar(4, 1));                              // use_udp = true
    turn = turn.concat(pbVar(18, isAwg ? 2 : 1));                 // tunnel_mode = AMNEZIAWG : WIREGUARD
    if (tp.wrap_key) { turn = turn.concat(pbVar(19, 2), pbBin(20, hexToBytes(tp.wrap_key))); }   // wrap_mode = PREFERRED + key
    var transport;
    if (isAwg) {
      var quick = String(rawConf || "").replace(/^([ \t]*Endpoint[ \t]*=).*$/m, "$1 " + LOCAL);
      transport = pbLen(7, pbStr(1, quick));                       // Config.awg = AmneziaWG{ awg_quick_config }
    } else {
      var iface = pbBin(1, b64ToBytes(cf.privkey));
      (cf.address || "").split(",").map(function (s) { return s.trim(); }).filter(Boolean).forEach(function (a) { iface = iface.concat(pbStr(2, a)); });
      (cf.dns || []).forEach(function (d) { iface = iface.concat(pbStr(3, d)); });
      if (cf.mtu) iface = iface.concat(pbVar(4, +cf.mtu || 1280));
      var peer = pbBin(1, b64ToBytes(cf.server_pubkey));
      if (cf.psk) peer = peer.concat(pbBin(2, b64ToBytes(cf.psk)));
      (cf.allowed || "").split(",").map(function (s) { return s.trim(); }).filter(Boolean).forEach(function (c) {
        var sp = c.split("/"), a = sp[0], pfx = sp[1];
        peer = peer.concat(pbLen(3, pbBin(1, ipToBytes(a)).concat(pbVar(2, pfx != null ? +pfx : (a.indexOf(":") >= 0 ? 128 : 32)))));
      });
      transport = pbLen(4, pbLen(1, iface).concat(pbLen(2, peer), pbLen(3, epBytes(LOCAL))));   // Config.wg → local turn client
    }
    var type = isAwg ? 10 : 4;                          // AWG → VK_TURN_PROFILE ; WG → ALL
    return new Uint8Array(pbVar(1, 1).concat(pbVar(2, type), pbLen(3, turn), transport, pbVar(5, 7)));   // ver, type, turn, wg|awg, backend=VK_TURN
  }
  function wingsvLink(baseConf, tp, vk) {
    if (typeof CompressionStream === "undefined") return Promise.reject(new Error("this browser can't build a wingsv:// link (no CompressionStream) — copy the fields into the WINGS V app manually"));
    var proto = wingsvConfigBytes(parseFullConf(baseConf), tp, (vk || "").trim() || "<PASTE VK CALL LINK>", baseConf);
    var cs = new CompressionStream("deflate"); var w = cs.writable.getWriter(); w.write(proto); w.close();
    return new Response(cs.readable).arrayBuffer().then(function (buf) {
      var comp = new Uint8Array(buf);
      var payload = new Uint8Array(1 + comp.length); payload[0] = 0x12; payload.set(comp, 1);
      var s = ""; for (var i = 0; i < payload.length; i++) s += String.fromCharCode(payload[i]);
      return "wingsv://" + btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    });
  }

  // Build the client-import artifact for a peer deployed BEHIND a turn-proxy, matching the DEPLOYED fork.
  // Returns a descriptor: { fork, label, ext, hint, uri?, cmd?, text? OR buildAsync } — `text` is ready,
  // `buildAsync` is a promise (wingsv:// needs zlib).
  function artifact(baseConf, tp, vkLink) {
    var fork = label(tp.service);
    var listen = tp.listen || "";
    var vk = (vkLink || "").trim() || "<PASTE VK CALL LINK>";
    var cf = parseFullConf(baseConf);
    if (fork === "WINGS-N") {
      return { fork: fork, label: "WINGS-N · WINGS V (wingsv:// link)", ext: "txt", uri: true,
        hint: "Import this wingsv:// link into the WINGS V app (paste it, or its Settings → import from link).",
        buildAsync: function () { return wingsvLink(baseConf, tp, vk); } };
    }
    if (fork === "kiper292") {
      var block = ["", "#@wgt:EnableTURN = true", "#@wgt:UseUDP = false", "#@wgt:IPPort = " + listen,
        "#@wgt:VKLink = " + vk, "#@wgt:Mode = vk_link", "#@wgt:PeerType = proxy_v2",
        "#@wgt:StreamNum = 4", "#@wgt:LocalPort = 9000", "#@wgt:StreamsPerCred = 4"].join("\n");
      return { fork: fork, label: "kiper292 · WireGuard-TURN (Android)", ext: "conf",
        hint: "Import this .conf into the kiper292 WireGuard-TURN app — the TURN settings ride along as #@wgt: comments (Endpoint stays the real server).",
        text: baseConf.replace(/\s*$/, "") + "\n" + block + "\n" };
    }
    if (fork === "anton48") {
      var s = { privateKey: cf.privkey, peerPublicKey: cf.server_pubkey, presharedKey: cf.psk,
        tunnelAddress: cf.address, allowedIPs: "0.0.0.0/0",
        dnsServers: (cf.dns && cf.dns.length ? cf.dns.join(",") : "1.1.1.1"),
        peerAddress: listen, vkLink: vk, numConnections: 12,
        useUDP: true, useDTLS: true, useSrtp: !tp.wrap_key,
        useWrap: !!tp.wrap_key, wrapKeyHex: tp.wrap_key || "" };
      var uri = "vkturnproxy://import?data=" + btoa(JSON.stringify({ settings: s, type: "connection", version: 1 }));
      return { fork: fork, label: "anton48 · VK TURN Proxy (iOS)", ext: "txt", uri: true,
        hint: "Open this link on the iPhone (or the app's Settings → Import from connection link) to import into the anton48 app.",
        text: uri };
    }
    // sidecar forks (cacggghp / samosvalishe / Moroka8 / unknown): WG dials the local client on :9000
    var sidecar = baseConf.replace(/^([ \t]*Endpoint[ \t]*=).*$/m, "$1 127.0.0.1:9000");
    sidecar = /^[ \t]*MTU[ \t]*=/m.test(sidecar) ? sidecar.replace(/^([ \t]*MTU[ \t]*=).*$/m, "$1 1280")
      : sidecar.replace(/^([ \t]*Address[ \t]*=.*)$/m, "$1\nMTU = 1280");
    var flags = tp.wrap_key ? (" -wrap-key " + tp.wrap_key) : "";
    return { fork: fork, label: fork + " · sidecar client", ext: "conf",
      hint: "This fork runs a separate client binary. Import this .conf into WireGuard, then run the fork's client alongside it:",
      cmd: "./client -listen 127.0.0.1:9000 -peer " + listen + " -vk-link " + vk + flags,
      text: sidecar };
  }

  root.SWGTurn = { artifact: artifact, fork: label, label: label };
})(typeof window !== "undefined" ? window : this);
