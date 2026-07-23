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
 *   • samosvalishe freeturn:// JSON "v": 1 — the free-turn-proxy server (vk-turn-proxy is archived); the
 *                 link embeds the WG config + rtpopus obf key. Imported by turn-proxy-android + the CLI.
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

  // ── descriptor-driven protobuf encoder (WINGS-N C path) ──
  // WINGSV_SCHEMA mirrors WINGS-N/WINGSV_DeX external/wingsv-proto/wingsv.proto (the schema shared by the WINGS V
  // app + wingsv-panel): each message is its field list {name, num, type, opt?, repeated?, msg?}. A generic walker
  // (pbEncodeMsg) turns a plain JS object into proto3 wire bytes, so tracking a proto change = editing this table,
  // not hand-positioning field numbers in code. Enums are encoded as their integer varint. Only the fields we
  // populate for a VK_TURN_PROFILE share link are listed; numbers are verbatim from the .proto.
  //   type: "uint32" | "bool" | "string" | "bytes" | "enum" (varint) | "msg" (length-delimited sub-message)
  //   opt:  proto3 explicit-presence — emit whenever the object carries the key (even at the zero value).
  //   (non-opt scalars follow proto3 default-omission: a zero/false/""/empty value is left off the wire.)
  var WINGSV_SCHEMA = {
    Endpoint:  [{ name: "host", num: 1, type: "string" }, { name: "port", num: 2, type: "uint32" }],
    Cidr:      [{ name: "addr", num: 1, type: "bytes" }, { name: "prefix", num: 2, type: "uint32" }],
    Interface: [{ name: "private_key", num: 1, type: "bytes" }, { name: "addrs", num: 2, type: "string", repeated: true },
                { name: "dns", num: 3, type: "string", repeated: true }, { name: "mtu", num: 4, type: "uint32", opt: true }],
    Peer:      [{ name: "public_key", num: 1, type: "bytes" }, { name: "preshared_key", num: 2, type: "bytes" },
                { name: "allowed_ips", num: 3, type: "msg", msg: "Cidr", repeated: true }],
    WireGuard: [{ name: "iface", num: 1, type: "msg", msg: "Interface" }, { name: "peer", num: 2, type: "msg", msg: "Peer" },
                { name: "endpoint", num: 3, type: "msg", msg: "Endpoint" }],
    AmneziaWG: [{ name: "awg_quick_config", num: 1, type: "string" }],
    Turn:      [{ name: "endpoint", num: 1, type: "msg", msg: "Endpoint" }, { name: "link", num: 2, type: "string" },
                { name: "threads", num: 3, type: "uint32", opt: true }, { name: "use_udp", num: 4, type: "bool", opt: true },
                { name: "no_obfuscation", num: 5, type: "bool", opt: true }, { name: "local_endpoint", num: 6, type: "msg", msg: "Endpoint" },
                { name: "session_mode", num: 9, type: "enum" }, { name: "links", num: 10, type: "string", repeated: true },
                { name: "creds_group_size", num: 12, type: "uint32", opt: true },
                { name: "manual_captcha", num: 13, type: "bool", opt: true }, { name: "captcha_auto_solver", num: 14, type: "string" },
                { name: "restart_on_network_change", num: 15, type: "bool", opt: true }, { name: "runtime_mode", num: 16, type: "enum" },
                { name: "user_dns", num: 17, type: "string", repeated: true },
                { name: "tunnel_mode", num: 18, type: "enum" }, { name: "wrap_mode", num: 19, type: "enum" },
                { name: "wrap_key", num: 20, type: "bytes" }, { name: "wrap_ciphers", num: 21, type: "enum", repeated: true },
                { name: "wrap_key_delivery", num: 22, type: "enum" }, { name: "browser_fingerprint", num: 27, type: "string" }],
    Config:    [{ name: "ver", num: 1, type: "uint32" }, { name: "type", num: 2, type: "enum" }, { name: "turn", num: 3, type: "msg", msg: "Turn" },
                { name: "wg", num: 4, type: "msg", msg: "WireGuard" }, { name: "backend", num: 5, type: "enum" }, { name: "awg", num: 7, type: "msg", msg: "AmneziaWG" }]
  };
  function pbIsDefault(t, v) { return t === "bool" ? !v : t === "string" ? String(v) === "" : t === "bytes" ? (!v || !v.length) : (+v || 0) === 0; }
  function pbFieldBytes(d, v) {
    if (d.type === "msg") return pbLen(d.num, pbEncodeMsg(d.msg, v));
    if (d.type === "string") return pbStr(d.num, String(v));
    if (d.type === "bytes") return pbBin(d.num, v);
    return pbVar(d.num, d.type === "bool" ? (v ? 1 : 0) : Math.floor(+v || 0));   // uint32 / enum / bool → varint
  }
  function pbEncodeMsg(msgName, obj) {
    var schema = WINGSV_SCHEMA[msgName], out = [];
    for (var i = 0; i < schema.length; i++) {
      var d = schema[i], v = obj[d.name];
      if (v === undefined || v === null) continue;                         // field not set on this object
      if (d.repeated) { for (var j = 0; j < v.length; j++) out = out.concat(pbFieldBytes(d, v[j])); continue; }
      if (d.type === "msg") { out = out.concat(pbFieldBytes(d, v)); continue; }   // present sub-message → emit
      if (!d.opt && pbIsDefault(d.type, v)) continue;                      // proto3 scalar default-omission
      out = out.concat(pbFieldBytes(d, v));                               // opt → emit even at zero (explicit presence)
    }
    return out;
  }

  // ── client (app) settings — admin-chosen values fed into config/QR/link generation (the SETTINGS SPLIT) ──
  // These are the app-DEDICATED knobs (connection count, streams, transport toggle…); server + coupled settings
  // come from tp/the .conf. Values arrive as `cs` (from panel_settings.turn_client_settings[fork]); each reader
  // falls back to the fork's authoritative default so a config is correct even before the admin touches anything.
  function csNum(cs, key, dflt) { var v = (cs || {})[key]; return (v === undefined || v === null || v === "" || isNaN(+v)) ? dflt : Math.floor(+v); }
  function csBool(cs, key, dflt) { var v = (cs || {})[key]; return (v === undefined || v === null || v === "") ? dflt : (v === true || v === "true" || v === 1 || v === "1"); }
  function csEnum(cs, key, map, dflt) { var v = (cs || {})[key]; if (v === undefined || v === null || v === "") return dflt; return map[String(v)] != null ? map[String(v)] : dflt; }
  function splitList(s) { return String(s || "").split(",").map(function (x) { return x.trim(); }).filter(Boolean); }

  // Canonical JSON matching Python's json.dumps(sort_keys=True, separators=(",",":")) — keys sorted at every
  // level, no whitespace. Lets the anton48 C-path encoder reproduce the app's own quick_link.py output BYTE for
  // byte (our field values are ASCII: base64/hex/IPs/URLs, so ensure_ascii vs JSON.stringify never diverges).
  function sortedCanonical(v) {
    if (Array.isArray(v)) return v.map(sortedCanonical);
    if (v && typeof v === "object") { var o = {}; Object.keys(v).sort().forEach(function (k) { o[k] = sortedCanonical(v[k]); }); return o; }
    return v;
  }
  function jsonSortedCompact(obj) { return JSON.stringify(sortedCanonical(obj)); }

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
  // C path: build the wingsv.Config as a plain object and marshal it through the schema-driven encoder above, so
  // the wire format stays pinned to wingsv.proto (the app + wingsv-panel share it). A VK_TURN_PROFILE (type 10)
  // carries its tunnel type in Turn.tunnel_mode plus the embedded wg/awg sub-config; backend = VK_TURN (7).
  var WINGSV_SESSION_MODES = { mainline: 2, mux: 3 };                     // TurnSessionMode (auto omitted → field absent = the app's default)
  var WINGSV_RUNTIME_MODES = { vpn: 1, proxy: 2 };                        // ProxyRuntimeMode (auto/UNSPECIFIED=0 omitted → app default)
  function wingsvConfigBytes(cf, tp, vk, rawConf, cs) {
    var LOCAL_HOST = "127.0.0.1", LOCAL_PORT = 9000;
    var isAwg = !!(cf.awg_params && Object.keys(cf.awg_params).length);   // AmneziaWG interface → awg transport
    var lp = String(tp.listen || ""), ci = lp.lastIndexOf(":");
    var turn = {
      endpoint: { host: ci >= 0 ? lp.slice(0, ci) : lp, port: ci >= 0 ? (+lp.slice(ci + 1) || 0) : 0 },   // public proxy ip:listen
      local_endpoint: { host: LOCAL_HOST, port: LOCAL_PORT },             // where the app's local turn client listens
      use_udp: csBool(cs, "useUDP", true),                                // admin-set; default true (unchanged)
      tunnel_mode: isAwg ? 2 : 1                                          // AMNEZIAWG : WIREGUARD
    };
    var vkList = Array.isArray(vk) ? vk.map(function (s) { return (s || "").trim(); }).filter(Boolean) : ((vk || "").trim() ? [(vk || "").trim()] : []);
    if (vkList.length > 1) turn.links = vkList;                           // MULTIPLE VK links → the app's link pool (Turn.links, repeated #10) — each its own stream pool
    else if (vkList.length === 1) turn.link = vkList[0];                  // single → legacy Turn.link (#2); empty → omitted (recipient adds their VK link in-app)
    if ((cs || {}).threads) turn.threads = csNum(cs, "threads", 24);       // -n worker count — omitted → app default
    var sm = csEnum(cs, "sessionMode", WINGSV_SESSION_MODES, 0); if (sm) turn.session_mode = sm;
    var bf = (cs || {}).browserFingerprint; if (bf && bf !== "auto") turn.browser_fingerprint = String(bf);   // TLS-imitation family
    var cg = csNum(cs, "credsGroupSize", 0); if (cg) turn.creds_group_size = cg;
    if (csBool(cs, "manualCaptcha", false)) turn.manual_captcha = true;                  // force manual captcha (off → the app's default)
    var cas = (cs || {}).captchaSolver; if (cas && cas !== "auto") turn.captcha_auto_solver = String(cas); // v2/v1/bypass; auto → app default (Enhanced), field omitted
    if (csBool(cs, "restartOnNetworkChange", false)) turn.restart_on_network_change = true;
    if (csBool(cs, "noObfuscation", false)) turn.no_obfuscation = true;                  // disable obfuscation (off → the app's default)
    var rmode = csEnum(cs, "runtimeMode", WINGSV_RUNTIME_MODES, 0); if (rmode) turn.runtime_mode = rmode;   // VPN vs local PROXY
    var udns = splitList((cs || {}).userDns); if (udns.length) turn.user_dns = udns;     // custom DNS resolvers (comma-separated)
    if (tp.wrap_key) { turn.wrap_mode = 2; turn.wrap_key = hexToBytes(tp.wrap_key); }   // WRAP_MODE_PREFERRED + key
    var config = { ver: 1, type: 10, backend: 7, turn: turn };            // VK_TURN_PROFILE + VK_TURN backend
    if (isAwg) {
      config.awg = { awg_quick_config: String(rawConf || "").replace(/^([ \t]*Endpoint[ \t]*=).*$/m, "$1 " + LOCAL_HOST + ":" + LOCAL_PORT) };
    } else {
      var iface = { private_key: b64ToBytes(cf.privkey), addrs: splitList(cf.address), dns: (cf.dns || []).slice() };
      if (cf.mtu) iface.mtu = +cf.mtu || 1280;
      var peer = { public_key: b64ToBytes(cf.server_pubkey) };
      if (cf.psk) peer.preshared_key = b64ToBytes(cf.psk);
      peer.allowed_ips = splitList(cf.allowed).map(function (c) {
        var sp = c.split("/"), a = sp[0], pfx = sp[1];
        return { addr: ipToBytes(a), prefix: pfx != null ? +pfx : (a.indexOf(":") >= 0 ? 128 : 32) };
      });
      config.wg = { iface: iface, peer: peer, endpoint: { host: LOCAL_HOST, port: LOCAL_PORT } };   // WG dials the local turn client
    }
    return new Uint8Array(pbEncodeMsg("Config", config));
  }
  function wingsvLink(baseConf, tp, vk, clientSettings) {
    if (typeof CompressionStream === "undefined") return Promise.reject(new Error("this browser can't build a wingsv:// link (no CompressionStream) — copy the fields into the WINGS V app manually"));
    var proto = wingsvConfigBytes(parseFullConf(baseConf), tp, vk, baseConf, clientSettings);   // vk = the VK-link list (or string); wingsvConfigBytes normalizes → Turn.links[] / Turn.link (empty → omitted)
    var stream = new CompressionStream("deflate"); var w = stream.writable.getWriter(); w.write(proto); w.close();
    return new Response(stream.readable).arrayBuffer().then(function (buf) {
      var comp = new Uint8Array(buf);
      var payload = new Uint8Array(1 + comp.length); payload[0] = 0x12; payload.set(comp, 1);
      var s = ""; for (var i = 0; i < payload.length; i++) s += String.fromCharCode(payload[i]);
      return "wingsv://" + btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    });
  }

  // ── samosvalishe freeturn:// link ── `freeturn://` + base64url(JSON), matching turn-proxy-android's
  // FreeturnLink (which mirrors free-turn-proxy docs/uri.md, v1). The WG config rides in the "wg" field
  // (comments + MTU stripped, Endpoint → the app's local turn listen 127.0.0.1:9000); the VK call link is
  // NOT included — the recipient supplies their own in the app. Obfuscation is rtpopus and its key MUST
  // match the free-turn-proxy server's -obf-profile/-obf-key on the node.
  function b64urlUtf8(s) {
    var bytes = new TextEncoder().encode(String(s)), bin = "";
    for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  // Strip comments, blank lines and any MTU line (MTU rides in its own link field) — shorter link, denser
  // QR. Mirrors ShareLinkBuilder.normalizeConf so our links look like the app's own.
  function freeturnConf(conf) {
    return String(conf || "").split("\n").map(function (l) { return l.trim(); }).filter(function (l) {
      if (!l || l.charAt(0) === "#" || l.charAt(0) === ";") return false;
      if (/^MTU/i.test(l) && l.indexOf("=") >= 0) return false;
      return true;
    }).join("\n");
  }
  function freeturnLink(tp, rawConf, vkLinks, cs) {
    var wg = freeturnConf(String(rawConf || "").replace(/^([ \t]*Endpoint[ \t]*=).*$/m, "$1 127.0.0.1:9000"));
    var cf = parseFullConf(rawConf);
    var o = { v: 1, provider: "vk", peer: tp.listen || "" };        // key order matches FreeturnLink.encode()
    // Carry the VK links IN the freeturn:// link, matching the CLI's flags: `link` = the primary (one URL, like
    // -link) and `links` = all URLs comma-joined (like -links, each its own stream pool). The Android app's current
    // share parser (FreeturnLink.parse) reads a fixed key set that DOESN'T include these, so an older app silently
    // ignores them — but the app shares the CLI core that DOES honour -link/-links, so this is worth testing on the app.
    var vks = (vkLinks || []).map(function (s) { return (s || "").trim(); }).filter(Boolean);
    if (vks.length) { o.link = vks[0]; o.links = vks.join(","); }
    // Client (app) knobs — omitted when default/blank so the link stays minimal (empty/default keys are dropped, per uri.md).
    var n = csNum(cs, "n", 0); if (n > 0) o.n = n;                   // parallel TURN streams (-n); omit → app default (10)
    var spc = csNum(cs, "spc", 0); if (spc > 0) o.spc = spc;        // streams per cached credential (-streams-per-cred); omit → default (10)
    var dnsMode = String((cs || {}).dns || "").trim(); if (dnsMode && dnsMode !== "auto") o.dns = dnsMode;   // plain|doh (auto = default → omit)
    var dnss = String((cs || {}).dnss || "").trim(); if (dnss) o.dnss = dnss;   // custom DNS servers (-dns-servers)
    if (csBool(cs, "mcap", false)) o.mcap = true;                   // manual VK captcha
    var key = (tp.wrap_key || "").trim();
    if (key) { o.obf = "rtpopus"; o.key = key; }                    // omitted → server must also run obf none
    // Stable per-peer Client ID for attribution. We run the server OPEN (no clients.json), so cid never gates auth;
    // deriving it from the peer's tunnel IP keeps it stable across regenerations and allowlist-ready for later.
    var addr = String(cf.address || "").split("/")[0];
    o.cid = "swg-" + (addr || (tp.listen || "")).replace(/[^0-9A-Za-z]+/g, "-");
    o.wg = wg;
    return "freeturn://" + b64urlUtf8(JSON.stringify(o));
  }

  // ── MYSOREZ / cacggghp VKTGZ profile ── the MYSOREZ VK TURN Proxy Android app (MYSOREZ/vk-turn-proxy-android)
  // imports a shareable profile string: "VKTGZ:" + base64( gzip( Gson-JSON of a ProxyProfile ) ). The app strips the
  // prefix, base64-decodes, gunzips and gson.fromJson's it (it also accepts plain base64 / raw JSON without the
  // prefix). We drive the cacggghp CORE, so config mirrors AppPreferences.createDefaultConfig(): the five built-in
  // customFlags (UDP on, VLESS, --manual-captcha, -no-dtls, -debug) — each ENABLED flag's `argument` is appended to
  // the client command. serverAddress = the proxy endpoint, vkLink = the VK call link, localPort = the WG dial target
  // (127.0.0.1:9000). Base64 is STANDARD (NO_WRAP, padded) — not url-safe — since it is not a URL. Async (gzip).
  // The VK TURN Proxy app is a generic core-launcher: it runs `<imported core> -peer <ip> <linkArg> <vk> -listen
  // 127.0.0.1:9000 [-n N]` plus each enabled customFlag. So the SAME app drives a DIFFERENT core per server fork, and
  // the customFlags/linkArg must match THAT core's wire — cacggghp (plain), MYSOREZ (its own mzrtp, -password + captcha),
  // or a rtpopus core loaded as a universal launcher (Moroka8 -wrap-key / samosvalishe -obf-key). See the compat matrix.
  function vktgzCoreFlags(fork, key, cs) {
    var f = [], la = String((cs || {}).linkArgument || "").trim();
    if (fork === "MYSOREZ") {                     // MYSOREZ CORE v1.5.x (-vk/-password RTP-AEAD): VK-Calls anon bypass + VK-ID smart-captcha auto-solver. Needs the LATEST core (≤v1.4.2 is the old cacggghp-family -vk-link binary that can't pass VK-ID). NO cacggghp flags.
      la = la || "-vk";
      if (key) f.push({ id: "flag-pw", label: "Password", argument: "-password " + key, enabled: true, deletable: true });
      f.push({ id: "flag-anon", label: "VK bypass",    argument: "-vk-anon-path " + (String((cs || {}).vkAnonPath || "").trim() || "vkcalls"), enabled: true, deletable: true });   // v1.5.x primary anon path (api.vk.me) — usually avoids the captcha entirely
      f.push({ id: "flag-cap",  label: "Captcha mode", argument: "-captcha-mode " + (String((cs || {}).captchaMode || "").trim() || "auto"),   enabled: true, deletable: true });   // auto = Go v2 smart-captcha solver (the app doesn't feed a stdin token, so DON'T use wv)
      f.push({ id: "flag-auth", label: "VK auth",      argument: "-vk-auth "      + (String((cs || {}).vkAuth || "").trim()      || "anonymous"), enabled: true, deletable: true });
      var dev = String((cs || {}).deviceId || "").trim(); if (dev) f.push({ id: "flag-dev", label: "Device ID", argument: "-device-id " + dev, enabled: true, deletable: true });
    } else if (fork === "Moroka8") {              // Moroka8 CORE (rtpopus v1) loaded into the app: -wrap -wrap-key <K>
      la = la || "-vk-link";
      if (key) f.push({ id: "flag-wrap", label: "Wrap", argument: "-wrap -wrap-key " + key, enabled: true, deletable: true });
    } else if (fork === "samosvalishe") {         // free-turn CORE (rtpopus) loaded into the app: -obf-profile rtpopus -obf-key <K> (its link flag is -links; -link is deprecated)
      la = la || "-links";
      if (key) f.push({ id: "flag-obf", label: "Obfuscation", argument: "-obf-profile rtpopus -obf-key " + key, enabled: true, deletable: true });
    } else {                                      // cacggghp CORE (plain) — the app's five built-in customFlags (AppPreferences.createDefaultConfig)
      la = la || "-vk-link";
      f = [{ id: "flag-udp",     label: "UDP",            argument: "-udp",             enabled: csBool(cs, "udp", true),            deletable: false },
           { id: "flag-vless",   label: "VLESS",          argument: "-vless",           enabled: false,                              deletable: false },
           { id: "flag-captcha", label: "Manual Captcha", argument: "--manual-captcha", enabled: csBool(cs, "manualCaptcha", false), deletable: false },
           { id: "flag-nodtls",  label: "Disable DTLS",   argument: "-no-dtls",         enabled: false,                              deletable: false },
           { id: "flag-debug",   label: "Debug",          argument: "-debug",           enabled: csBool(cs, "debug", false),         deletable: false }];
      if (key) f.push({ id: "flag-wrap", label: "Wrap key", argument: "-wrap-key " + key, enabled: true, deletable: true });
    }
    return { flags: f, linkArgument: la };
  }
  function vktgzProfile(cf, tp, vkList, cs, fork) {
    var listen = tp.listen || "";
    var addr = String(cf.address || "").split("/")[0];
    var core = vktgzCoreFlags(fork, (tp.wrap_key || "").trim(), cs);
    var flags = core.flags;
    String((cs || {}).rawFlags || "").split(/[\r\n]+/).map(function (s) { return s.trim(); }).filter(Boolean)   // admin-added raw args (the app's Raw-mode flags box)
      .forEach(function (f, i) { flags.push({ id: "flag-raw-" + i, label: "Custom", argument: f, enabled: true, deletable: true }); });
    var config = { serverAddress: listen, vkLink: (vkList && vkList[0]) || "", linkArgument: core.linkArgument,
      localPort: "127.0.0.1:9000", isRawMode: false, rawCommand: "", customFlags: flags };
    var threads = csNum(cs, "threads", 0); if (threads > 0) config.threads = threads;   // -n; omitted → the app's own default (8)
    return { id: "swg-" + (addr || listen).replace(/[^0-9A-Za-z]+/g, "-"), name: "SWG " + (addr || listen), isDefault: false, config: config };
  }
  function vktgzLink(baseConf, tp, vkList, cs, fork) {
    if (typeof CompressionStream === "undefined") return Promise.reject(new Error("this browser can't build a VKTGZ profile (no CompressionStream) — enter the fields into the MYSOREZ app manually"));
    var json = new TextEncoder().encode(JSON.stringify(vktgzProfile(parseFullConf(baseConf), tp, vkList, cs, fork)));
    var stream = new CompressionStream("gzip"); var w = stream.writable.getWriter(); w.write(json); w.close();
    return new Response(stream.readable).arrayBuffer().then(function (buf) {
      var comp = new Uint8Array(buf), s = "";
      for (var i = 0; i < comp.length; i++) s += String.fromCharCode(comp[i]);
      return "VKTGZ:" + btoa(s);   // standard base64 (Android Base64.NO_WRAP — padded, no line breaks)
    });
  }

  // ── Amnezia VPN vpn:// deep link (WG/AWG configs) ── `vpn://` + base64url( qCompress( raw .conf ) ). Amnezia's
  // importer (client/core/controllers/selfhosted/importController.cpp: strip "vpn://" → fromBase64(Base64UrlEncoding|
  // OmitTrailingEquals) → qUncompress → checkConfigFormat) accepts a RAW WireGuard/AmneziaWG .conf as the payload —
  // it detects [Interface]/[Peer] and builds its own amnezia-awg / amnezia-wireguard container. The AWG obfuscation
  // params ride in the .conf under their standard names (Amnezia's configKeys ARE Jc/Jmin/Jmax/S1..S4/H1..H4/I1..),
  // so an AWG peer imports fully obfuscated; a plain WG peer imports as WireGuard. Qt qCompress = a 4-byte BIG-ENDIAN
  // uncompressed length prefixed to a standard zlib stream — CompressionStream("deflate") produces exactly that zlib
  // stream (RFC 1950), which Qt's qUncompress (zlib inflate) reads. Async (needs zlib), like wingsv://.
  function amneziaVpnLink(baseConf) {
    if (typeof CompressionStream === "undefined") return Promise.reject(new Error("this browser can't build a vpn:// link (no CompressionStream) — scan the QR or import the .conf into Amnezia VPN instead"));
    var data = new TextEncoder().encode(String(baseConf || ""));
    var stream = new CompressionStream("deflate"); var w = stream.writable.getWriter(); w.write(data); w.close();
    return new Response(stream.readable).arrayBuffer().then(function (buf) {
      var comp = new Uint8Array(buf), n = data.length;
      var out = new Uint8Array(4 + comp.length);
      out[0] = (n >>> 24) & 0xff; out[1] = (n >>> 16) & 0xff; out[2] = (n >>> 8) & 0xff; out[3] = n & 0xff;   // qCompress length header
      out.set(comp, 4);
      var s = ""; for (var i = 0; i < out.length; i++) s += String.fromCharCode(out[i]);
      return "vpn://" + btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    });
  }

  // A server's NATIVE client encoder (the app built for that fork).
  // Returns an ENCODER id (matches swg-panel-server TURN_CLIENTS[*].encoder, which the SPA passes as `asClient`).
  function nativeEncoder(fork) {
    return ({ "WINGS-N": "wingsv", "kiper292": "kiper292", "anton48": "anton48",
      "samosvalishe": "freeturn", "MYSOREZ": "vktgz", "cacggghp": "vktgz" })[fork] || "sidecar";
  }
  // The fork (turn-proxy server) a client encoder is NATIVE to — the canonical publisher, reverse of nativeEncoder.
  // Lets the UI colour a cross-fork (experimental) pairing: the SERVER used vs the fork the chosen app belongs to.
  function encoderFork(enc) {
    return ({ wingsv: "WINGS-N", anton48: "anton48", kiper292: "kiper292", freeturn: "samosvalishe", vktgz: "MYSOREZ" })[enc] || "";
  }
  // A stable per-peer id (attribution / allowlist-ready), derived from the peer's tunnel IP so it survives regen.
  function stableCid(cf, tp) { return "swg-" + String(String(cf.address || "").split("/")[0] || (tp.listen || "")).replace(/[^0-9A-Za-z]+/g, "-"); }

  // App name / platform / author per client encoder — for the "<server> via <app> (<platform>) by <author>" label.
  var CLIENT_META = {
    wingsv:   { app: "WINGS V",        platform: "Android", author: "WINGS-N" },
    anton48:  { app: "VK TURN Proxy",  platform: "iOS",     author: "anton48" },
    kiper292: { app: "WireGuard-TURN", platform: "Android", author: "kiper292" },
    freeturn: { app: "FreeTurn",       platform: "Android", author: "samosvalishe" },
    vktgz:    { app: "VK TURN Proxy",  platform: "Android", author: "MYSOREZ" }
  };
  function clientLabel(fork, enc, mode) {
    var m = CLIENT_META[enc];
    return m ? (fork + " via " + m.app + " (" + m.platform + (mode || "") + ") by " + m.author) : (fork + " · CLI client (desktop)");
  }

  // Build the client-import artifact for a peer deployed BEHIND a turn-proxy. `asClient` (an encoder id) selects which
  // client app to target; omitted → the server's native client. ONE server can offer several apps (multi-client); a
  // cross-fork client (asClient !== native) is EXPERIMENTAL — the wire formats share an ancestor but interop is
  // unverified, so the descriptor carries experimental:true for the UI to flag. Returns a descriptor:
  // { fork, label, ext, qr, experimental, hint, uri?, cmd?, text? OR buildAsync } — `text` ready, `buildAsync` a
  // promise (wingsv://, VKTGZ need compression). `qr` = the client imports via a scannable QR.
  function artifact(baseConf, tp, vkLink, cs, vkLinks, asClient) {
    var fork = label(tp.service);
    var enc = asClient || nativeEncoder(fork);            // which client app's encoder to run
    var experimental = enc !== nativeEncoder(fork);       // cross-fork client → unverified interop
    cs = cs || {};                                        // client (app) settings for THIS client (admin-chosen; defaults applied per reader)
    var listen = tp.listen || "";
    // The user's VK call links — an ordered list (primary first). vkLink is the legacy single (= primary). Each fork
    // uses what its app supports: WINGS embeds all (Turn.links[]), anton48 all (multiline vkLink), kiper292/sidecar
    // the primary; freeturn shows them all for the user to paste in-app.
    var vkList = (Array.isArray(vkLinks) && vkLinks.length ? vkLinks : (vkLink ? [vkLink] : [])).map(function (s) { return (s || "").trim(); }).filter(Boolean);
    var vkRaw = vkList[0] || "";                          // the PRIMARY VK call link — empty when unset
    var vkText = vkRaw || "<PASTE VK CALL LINK>";          // placeholder ONLY in plain-text configs (a visible fill-in line the user edits)
    var vkMissing = vkList.length === 0;                   // every fork reports this so the UI can flag "create a VK link"
    var cf = parseFullConf(baseConf);
    if (enc === "wingsv") {
      // qr:true — the WINGS V app scans a QR of the SAME wingsv:// string it imports from a link/paste
      // (WINGSV WingsImportParser.parseFromText: one entry point for scan, paste and deep-link). Long link →
      // the sub/panel QR renderer falls back to text if it can't encode.
      return { fork: fork, app: "WINGS V", label: clientLabel(fork, "wingsv"), ext: "txt", uri: true, qr: true, vkMissing: vkMissing, experimental: experimental, enc: enc,
        hint: "Scan the QR with the WINGS V app, or paste the wingsv:// link (Settings → import from link).",
        buildAsync: function () { return wingsvLink(baseConf, tp, vkList, cs); } };   // pass ALL VK links → Turn.links[]; empty omitted
    }
    if (enc === "kiper292") {
      var wdt = csNum(cs, "watchdogTimeout", 0);                       // inactivity watchdog (s); 0 = off → emit only when > 0
      var block = ["", "#@wgt:EnableTURN = true", "#@wgt:UseUDP = false", "#@wgt:IPPort = " + listen,
        "#@wgt:VKLink = " + vkText, "#@wgt:Mode = vk_link", "#@wgt:PeerType = proxy_v2",
        "#@wgt:StreamNum = " + csNum(cs, "streamNum", 4), "#@wgt:LocalPort = 9000",
        "#@wgt:StreamsPerCred = " + csNum(cs, "streamsPerCred", 4)]
        .concat(wdt > 0 ? ["#@wgt:WatchdogTimeout = " + wdt] : []).join("\n");
      return { fork: fork, app: "WireGuard-TURN", label: clientLabel(fork, "kiper292"), ext: "conf", qr: true, vkMissing: vkMissing, experimental: experimental, enc: enc,
        hint: "Scan the QR or import .conf into the kiper292 WireGuard-TURN app. The TURN settings ride along as #@wgt: comments (the Endpoint stays the real server).",
        text: baseConf.replace(/\s*$/, "") + "\n" + block + "\n" };
    }
    if (enc === "anton48") {
      // C path — a faithful port of the app's own generator (anton48/vk-turn-proxy-ios/quick_link.py, build_link):
      // JSON with sort_keys + compact separators, then URL-SAFE base64 WITHOUT padding. The url-safe alphabet is
      // not cosmetic: standard btoa can emit "+", which a URL query parser turns into a space and corrupts the link.
      // Field values + mode logic verified against quick_link.py AND the server's flag help (srtp-build146):
      //  • -srtp server  → useSrtp=true, useWrap=false                (plain DTLS-SRTP transport)
      //  • -wrap-srtp -wrap-key K → useWrap=true, wrapKeyHex=K, useSrtp=false   (WRAP+SRTP-mimic; server help says so)
      //  • useUDP default FALSE (TCP-control bypasses VK's per-cred allocation-rate throttle).
      //  • useWrapA/useWrapS emitted explicitly (even false) so the link fully defines the mode — omitting useWrapA
      //    can't switch a device OUT of SRTP-WRAP-A (stale useWrapA=true wins useWrapA>useSrtp>useWrap precedence).
      //  • allowedIPs is NOT emitted (removed iOS build 160 — the app pins 0.0.0.0/0 under includeAllNetworks).
      // CROSS-FORK (experimental): this app also drives OTHER servers. Moroka8 (-wrap + hex -wrap-key) → the plain
      // useWrap+wrapKeyHex path below already matches. samosvalishe/free-turn (rtpopus SRTP + -obf-key + client-id)
      // → WRAP-S mode: useWrapS=true, obfProfile=rtpopus, the obf key in wrapKeyHex, and an allowlist-ready clientID.
      var isWrapS = (fork === "samosvalishe") || csBool(cs, "useWrapS", false);
      // vkturnproxy obfuscates ONLY on its native/friendly pairings: anton48 (native — bare -srtp = SRTP, -wrap-srtp = SRTP+WRAP),
      // Moroka8 (-wrap = SRTP+WRAP), samosvalishe (rtpopus = WRAP-S). Every PLAIN pairing — cacggghp/kiper292 (no obf) AND
      // MYSOREZ/WINGS-N (whose native wrap the vkturnproxy app can't ride) — connects bare DTLS+WG → Legacy: all obf modes off,
      // no wrap key (never carry the server's own -password/-wrap key here — it isn't an anton48 SRTP-WRAP key). See compat matrix.
      var vkObf = (fork === "anton48" || fork === "Moroka8" || fork === "samosvalishe");
      var dnsOverride = String((cs || {}).dnsServers || "").trim();      // admin override → else the peer's own DNS → else 1.1.1.1
      var s = { privateKey: cf.privkey, peerPublicKey: cf.server_pubkey, presharedKey: cf.psk || "",   // emit even when empty → deterministically clears any stale device PSK (our PSK is panel-owned + consistent)
        tunnelAddress: cf.address,
        dnsServers: dnsOverride || (cf.dns && cf.dns.length ? cf.dns.join(",") : "1.1.1.1"),
        peerAddress: listen, vkLink: vkList.join("\n"), numConnections: csNum(cs, "numConnections", 30),   // MULTIPLE VK links → newline-joined (the VK TURN Proxy app's vkLink is a multiline string, one link per line); empty → ""
        useDTLS: true, useSrtp: (vkObf && !isWrapS && !tp.wrap_key), useUDP: csBool(cs, "useUDP", false),
        useWrap: (vkObf && !isWrapS && !!tp.wrap_key), wrapKeyHex: vkObf ? (tp.wrap_key || "") : "",
        useWrapA: csBool(cs, "useWrapA", false), useWrapS: isWrapS,   // WRAP-A = amurcanov (future); WRAP-S = free-turn cross-drive. Emitted explicitly (mode precedence useWrapA>useSrtp>useWrap)
        obfProfile: (function () { var o = String((cs || {}).obfProfile || "").trim(); return (o && o !== "auto") ? o : "rtpopus"; })(),   // admin-set rtpopus2/3 for those servers; auto/blank → the app default rtpopus (unchanged)
        clientID: isWrapS ? stableCid(cf, tp) : "" };   // WRAP-S needs an allowlist-ready client-id; free-turn runs open so it is attribution-only
      // Keys the app's parser accepts but quick_link.py's CONFIG omits — emitted only when set (empty would clobber a device value):
      var wrapApw = String((cs || {}).wrapAPassword || "").trim(); if (wrapApw) s.wrapAPassword = wrapApw;   // amurcanov WRAP-A secret (future)
      var turnOv = String((cs || {}).turnServerOverride || "").trim(); if (turnOv) s.turnServerOverride = turnOv;   // pin fresh conns to a specific TURN relay
      if (csBool(cs, "vkAuth", false)) s.vkAuth = true;                  // VK cookie-auth path (instead of anon PoW)
      var uri = "vkturnproxy://import?data=" + b64urlUtf8(jsonSortedCompact({ version: 1, type: "connection", settings: s }));
      return { fork: fork, app: "VK TURN Proxy", label: clientLabel(fork, "anton48", isWrapS ? " · WRAP-S" : ""), ext: "txt", uri: true, qr: false, vkMissing: vkMissing, experimental: experimental, enc: enc,
        hint: "Open the link on the iPhone (or the app's Settings → Import from connection link) to import into the VK TURN Proxy app.",
        text: uri };
    }
    if (enc === "vktgz") {
      // The VK TURN Proxy Android app is a core-launcher: it imports a VKTGZ: profile AND runs a user-imported core.
      // Which core depends on the SERVER fork — its own (cacggghp/MYSOREZ) or, as a universal launcher, an rtpopus
      // fork's core (Moroka8 / samosvalishe). The profile's customFlags/linkArg (vktgzCoreFlags) match that core's wire.
      var coreName = ({ MYSOREZ: "MYSOREZ", Moroka8: "Moroka8", samosvalishe: "free-turn", cacggghp: "cacggghp" })[fork] || fork;
      var launcher = (fork === "Moroka8" || fork === "samosvalishe");   // the app hosts ANOTHER fork's core (universal launcher)
      return { fork: fork, app: "VK TURN Proxy", label: clientLabel(fork, "vktgz"), ext: "txt", qr: true, wrap: true, vkMissing: vkMissing, experimental: experimental, enc: enc,
        vk: true, vkLinks: vkList,
        hint: "Import the " + coreName + " core (client-android-arm64 from the " + coreName + " releases) into the VK TURN Proxy app"
          + (launcher ? " — it runs as a launcher for that core" : "") + ", then scan the QR (Profiles → Import) or paste the VKTGZ: text — the VK call link + endpoint ride inside" + (vkMissing ? " once you add a VK link." : "."),
        buildAsync: function () { return vktgzLink(baseConf, tp, vkList, cs, fork); } };
    }
    if (enc === "freeturn") {
      // samosvalishe now = free-turn-proxy server (the old standalone vk-turn-proxy server is archived). Its
      // clients (turn-proxy-android + free-turn-proxy CLI) import a freeturn:// link — one scannable QR that
      // carries the proxy endpoint, the rtpopus obfuscation key, and the whole WG config.
      return { fork: fork, app: "FreeTurn", label: clientLabel(fork, "freeturn"), ext: "txt", uri: true, qr: true, vkMissing: vkMissing, experimental: experimental, enc: enc,
        vk: true, vkLinks: vkList,   // the freeturn:// link now CARRIES the VK links (link/links, like the CLI's -link/-links) — testing whether the app honours them; the sub still lists them as a fallback to paste in-app
        hint: "Scan the QR with the FreeTurn app (samosvalishe/turn-proxy-android), or paste the freeturn:// link — it now includes the VK call link(s). If your app doesn't pick them up, add them in the app manually.",
        text: freeturnLink(tp, baseConf, vkList, cs) };
    }
    // sidecar forks (cacggghp / Moroka8 / unknown): WG dials the local client on :9000
    var sidecar = baseConf.replace(/^([ \t]*Endpoint[ \t]*=).*$/m, "$1 127.0.0.1:9000");
    sidecar = /^[ \t]*MTU[ \t]*=/m.test(sidecar) ? sidecar.replace(/^([ \t]*MTU[ \t]*=).*$/m, "$1 1280")
      : sidecar.replace(/^([ \t]*Address[ \t]*=.*)$/m, "$1\nMTU = 1280");
    // The CLI binaries that can drive THIS fork's server, NATIVE (the fork's own build) first. The rtpopus pair share a
    // wire, but the native build is the better pick: independent release cadence (one project going stale doesn't strand
    // you), and samosvalishe's -obf-profile even reaches rtpopus2/3 relays the Moroka8 CLI (v1 -wrap only) can't. Each
    // author carries the command in ITS OWN flag syntax; a plain fork (empty key) just drops the obf flag. Compat matrix.
    var rawExtra = String((cs || {}).rawFlags || "").split(/[\r\n]+/).map(function (s) { return s.trim(); }).filter(Boolean).join(" ");   // admin-added extra CLI flags
    var authorForks = ({ Moroka8: ["Moroka8", "samosvalishe"], samosvalishe: ["samosvalishe", "Moroka8"],
      anton48: ["samosvalishe", "Moroka8"], MYSOREZ: ["MYSOREZ"] })[fork] || ["samosvalishe"];   // plain forks + WINGS: the universal free-turn CLI (plain)
    function authorCmd(a) {
      var link = (a === "MYSOREZ") ? " -vk " : (a === "samosvalishe") ? " -links " : " -vk-link ", obf = "";
      if (tp.wrap_key) {
        if (a === "Moroka8") obf = " -wrap -wrap-key " + tp.wrap_key;
        else if (a === "samosvalishe") obf = " -obf-profile rtpopus -obf-key " + tp.wrap_key;
        else if (a === "MYSOREZ") obf = " -password " + tp.wrap_key + " -vk-anon-path vkcalls -captcha-mode auto -vk-auth anonymous";
      }
      return "./client -listen 127.0.0.1:9000 -peer " + listen + link + vkText + obf + (rawExtra ? " " + rawExtra : "");
    }
    var authors = authorForks.map(function (a) { return { fork: a, cmd: authorCmd(a), native: (a === fork) }; });
    return { fork: fork, app: fork, label: clientLabel(fork, "sidecar"), ext: "conf", qr: true, vkMissing: vkMissing, experimental: experimental, enc: enc,
      hint: "This server needs a separate client binary. Scan the QR or import .conf into WireGuard/AmneziaWG, then run the client alongside it:",
      cmd: authors[0].cmd, cliAuthors: authors,   // authors[0] = the native/preferred build (backward-compatible single cmd)
      text: sidecar };
  }

  root.SWGTurn = { artifact: artifact, fork: label, label: label, nativeEncoder: nativeEncoder, encoderFork: encoderFork, amneziaVpn: amneziaVpnLink };
})(typeof window !== "undefined" ? window : this);
