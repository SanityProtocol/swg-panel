/* swg-sub front-end — the public per-user subscription page.
 *
 * Everything secret happens here, in the browser: the unlock key rides in the URL fragment
 * (never sent to the server), decrypts each peer's private key + PSK client-side, and the
 * config is assembled locally. The server only ever hands us ciphertext + non-secret params.
 *
 * URL shape:  https://sub.<domain>/<token>#<unlock-key>
 *   <token>       — last path segment; identifies the ciphertext bucket to fetch.
 *   <unlock-key>  — URL fragment; base64url of a 32-byte AES-GCM key. Decrypts the secrets.
 *
 * Phase 3 renders every peer's every deployment (desktop-style). Phase 5 layers the mobile
 * primary-QR + swipe UX on top of this same data.
 */
(function () {
  "use strict";

  var AWG_ORDER = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4", "I1", "I2", "I3", "I4", "I5"];

  // ── base64 (both standard and url-safe, padding optional) → bytes ──
  function b64ToBytes(s) {
    s = String(s || "").replace(/-/g, "+").replace(/_/g, "/").replace(/\s+/g, "");
    while (s.length % 4) s += "=";
    var bin = atob(s), out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  // ── config assembly — byte-identical to the panel's buildConf() ──
  function guardAllowed(a) {
    var parts = ((a || "").trim() || "0.0.0.0/0, ::/0").split(",").map(function (x) { return x.trim(); }).filter(Boolean);
    if (parts.indexOf("0.0.0.0/0") >= 0 && !parts.some(function (p) { return p.indexOf(":") >= 0; })) parts.push("::/0");
    return parts.join(", ");
  }
  function buildConf(o) {
    var L = ["[Interface]", "PrivateKey = " + o.privkey, "Address = " + o.address];
    if (o.dns && o.dns.length) L.push("DNS = " + o.dns.join(", "));
    L.push("MTU = " + (o.mtu || 1280));
    for (var i = 0; i < AWG_ORDER.length; i++) {
      var k = AWG_ORDER[i];
      if (o.awg_params && o.awg_params[k] != null) L.push(k + " = " + o.awg_params[k]);
    }
    L.push("", "[Peer]", "PublicKey = " + o.server_pubkey);
    if (o.psk) L.push("PresharedKey = " + o.psk);
    L.push("AllowedIPs = " + guardAllowed(o.allowed), "Endpoint = " + o.endpoint,
      "PersistentKeepalive = " + (o.keepalive != null && o.keepalive !== "" ? o.keepalive : 25));
    return L.join("\n") + "\n";
  }

  // ── QR — mirrors the panel's qrDataURL() ──
  function qrDataURL(text, targetPx) {
    var q = qrcode(0, "L");
    q.addData(text); q.make();
    var n = q.getModuleCount(), quiet = 4, total = n + quiet * 2;
    var cell = Math.max(3, Math.floor((targetPx || 320) / total));
    var size = total * cell;
    var c = document.createElement("canvas"); c.width = c.height = size;
    var ctx = c.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, size, size);
    ctx.fillStyle = "#000";
    for (var r = 0; r < n; r++)
      for (var col = 0; col < n; col++)
        if (q.isDark(r, col)) ctx.fillRect((col + quiet) * cell, (r + quiet) * cell, cell, cell);
    return c.toDataURL("image/png");
  }

  function el(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }
  function showState(msg, sub) {
    var s = document.getElementById("state");
    s.hidden = false;
    s.className = "state";
    s.innerHTML = "";
    var h = el("p", "state-msg", msg);
    s.appendChild(h);
    if (sub) s.appendChild(el("p", "state-sub", sub));
    document.getElementById("peers").hidden = true;
  }

  function fileName(user, peer, tgt) {
    var s = (user || "peer") + "-" + (peer || "") + "-" + (tgt.node || "");
    return s.replace(/[^\w.-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "swg";
  }
  function download(text, name) {
    var blob = new Blob([text], { type: "application/octet-stream" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name.replace(/\.conf$/i, "") + ".conf";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  // A single deployment (node/iface) card: QR + actions + collapsible config text.
  function targetCard(userName, peer, tgt, conf, reason) {
    var card = el("div", "tgt");
    if (tgt.primary) card.appendChild(el("div", "primary", "Primary"));
    card.appendChild(el("div", "tgt-node", tgt.node || tgt.iface || "server"));

    if (!conf) {
      card.appendChild(el("div", "qr-fail", reason ||
        "Not ready yet — open this peer once in the panel to publish it."));
      return card;
    }

    var qwrap = el("div", "qr");
    try {
      var img = el("img", "qrimg");
      img.alt = "config QR";
      img.src = qrDataURL(conf, 320);
      qwrap.appendChild(img);
    } catch (_) {
      qwrap.appendChild(el("div", "qr-fail", "config too large to encode as QR"));
    }
    card.appendChild(qwrap);

    var acts = el("div", "acts");
    var name = fileName(userName, peer.title, tgt);
    var dl = el("button", "btn", "Download .conf");
    dl.onclick = function () { download(conf, name); };
    acts.appendChild(dl);
    var cp = el("button", "btn ghost", "Copy config");
    cp.onclick = function () {
      (navigator.clipboard ? navigator.clipboard.writeText(conf) : Promise.reject()).then(function () {
        cp.textContent = "Copied"; setTimeout(function () { cp.textContent = "Copy config"; }, 1400);
      }, function () { cp.textContent = "Copy failed"; setTimeout(function () { cp.textContent = "Copy config"; }, 1400); });
    };
    acts.appendChild(cp);
    card.appendChild(acts);

    var det = el("details", "cfg");
    det.appendChild(el("summary", null, "Show config text"));
    det.appendChild(el("pre", null, conf));
    card.appendChild(det);
    return card;
  }

  // Prev/next + dots for a peer's deployment carousel. The scroll container does the swiping (CSS
  // scroll-snap); this just drives it from buttons and reflects the position. Offsets are measured
  // live so it's robust to gaps and to the desktop→mobile layout switch. Hidden on wide screens via CSS.
  function carouselNav(grid, count) {
    var nav = el("div", "peer-nav");
    var prev = el("button", "nav-btn", "‹"); prev.setAttribute("aria-label", "Previous server"); prev.type = "button";
    var next = el("button", "nav-btn", "›"); next.setAttribute("aria-label", "Next server"); next.type = "button";
    var dots = el("div", "nav-dots"), dotEls = [];
    for (var i = 0; i < count; i++) { var d = el("span", "nav-dot"); dotEls.push(d); dots.appendChild(d); }
    function offset(i) { return grid.children[i].getBoundingClientRect().left - grid.getBoundingClientRect().left + grid.scrollLeft; }
    function current() { var sl = grid.scrollLeft, best = 0, bd = Infinity; for (var i = 0; i < count; i++) { var dd = Math.abs(offset(i) - sl); if (dd < bd) { bd = dd; best = i; } } return best; }
    function go(i) { i = Math.max(0, Math.min(count - 1, i)); grid.scrollTo({ left: offset(i), behavior: "smooth" }); }
    prev.onclick = function () { go(current() - 1); };
    next.onclick = function () { go(current() + 1); };
    function sync() { var idx = current(); for (var i = 0; i < dotEls.length; i++) dotEls[i].className = "nav-dot" + (i === idx ? " on" : ""); prev.disabled = idx <= 0; next.disabled = idx >= count - 1; }
    var raf = 0;
    grid.addEventListener("scroll", function () { if (raf) return; raf = requestAnimationFrame(function () { raf = 0; sync(); }); }, { passive: true });
    dotEls.forEach(function (d, i) { d.onclick = function () { go(i); }; });
    nav.appendChild(prev); nav.appendChild(dots); nav.appendChild(next);
    setTimeout(sync, 0);
    return nav;
  }

  function render(data, cryptoKey) {
    var who = document.getElementById("who");
    who.textContent = data.user && data.user.name ? data.user.name : "";

    var wrap = document.getElementById("peers");
    wrap.innerHTML = "";
    var peers = data.peers || [];
    if (!peers.length) {
      showState("No configs yet", "There are no active peers on this subscription. New peers will appear here automatically.");
      return Promise.resolve();
    }

    // Decrypt every peer's secret (privkey+psk) with the fragment key, then assemble configs.
    var jobs = peers.map(function (peer) {
      if (!peer.sec) return Promise.resolve({ peer: peer, secret: null });
      var all = b64ToBytes(peer.sec);
      return crypto.subtle.decrypt({ name: "AES-GCM", iv: all.slice(0, 12) }, cryptoKey, all.slice(12))
        .then(function (buf) {
          var obj = JSON.parse(new TextDecoder().decode(new Uint8Array(buf)));
          return { peer: peer, secret: obj };            // {k: privkey, p: psk}
        })
        .catch(function () { return { peer: peer, secret: null, bad: true }; });
    });

    return Promise.all(jobs).then(function (rows) {
      var anyBad = false;
      rows.forEach(function (row) {
        var peer = row.peer, secret = row.secret;
        if (row.bad) anyBad = true;
        var sec = el("section", "peer");
        var head = el("div", "peer-head");
        head.appendChild(el("span", "peer-title", peer.title || "Peer"));
        head.appendChild(el("span", "peer-count", (peer.targets || []).length + (peer.targets && peer.targets.length === 1 ? " server" : " servers")));
        sec.appendChild(head);

        // Distinguish "couldn't decrypt" (stale/wrong link) from "not published yet" (no ciphertext).
        var reason = row.bad ? "This link is out of date — ask your administrator for a fresh one."
          : (!peer.sec ? "Not ready yet — open this peer once in the panel to publish it." : null);
        var grid = el("div", "tgts");
        (peer.targets || []).forEach(function (tgt) {
          var conf = null;
          if (secret && secret.k) {
            conf = buildConf({
              privkey: secret.k,
              address: (tgt.ip || "").split("/")[0] + "/32",
              dns: tgt.dns || [],
              mtu: tgt.mtu || 1280,
              awg_params: tgt.awg || {},
              server_pubkey: tgt.server_pubkey || "",
              psk: secret.p || "",
              endpoint: tgt.endpoint || "",
              allowed: "0.0.0.0/0, ::/0",
              keepalive: 25
            });
          }
          grid.appendChild(targetCard(data.user && data.user.name, peer, tgt, conf, reason));
        });
        sec.appendChild(grid);
        // On a phone each peer is a one-QR-per-view carousel (primary first) — native swipe via scroll-snap,
        // plus prev/next + dots. On a wide screen the CSS lays every deployment out in a row and hides the nav.
        if ((peer.targets || []).length > 1) sec.appendChild(carouselNav(grid, peer.targets.length));
        wrap.appendChild(sec);
      });
      document.getElementById("state").hidden = true;
      wrap.hidden = false;
      if (anyBad) {
        var warn = el("p", "foot-warn", "Some peers couldn't be decrypted — this link may be out of date. Ask your administrator for a fresh one.");
        wrap.appendChild(warn);
      }
    });
  }

  function start() {
    var seg = location.pathname.split("/").filter(Boolean);
    var token = seg.length ? seg[seg.length - 1] : "";
    var keyB64 = (location.hash || "").replace(/^#/, "").trim();

    if (!token) return showState("Invalid link", "This subscription link is missing its identifier.");
    if (!keyB64) return showState("Incomplete link", "This link is missing the part after “#”. Copy the whole URL — the section after the # is what unlocks your configs and it never leaves your device.");

    var keyBytes;
    try {
      keyBytes = b64ToBytes(keyB64);
      if (keyBytes.length !== 32) throw new Error("bad key length");
    } catch (_) {
      return showState("Invalid link", "The unlock key in this link isn’t valid.");
    }

    crypto.subtle.importKey("raw", keyBytes, { name: "AES-GCM" }, false, ["decrypt"])
      .then(function (cryptoKey) {
        return fetch("/api/" + encodeURIComponent(token), { cache: "no-store" }).then(function (res) {
          if (res.status === 404) { showState("Link not found", "This subscription doesn’t exist, was revoked, or subscriptions are turned off."); return null; }
          if (!res.ok) { showState("Something went wrong", "Couldn’t load this subscription (server error). Please try again later."); return null; }
          return res.json().then(function (j) {
            if (!j || !j.ok || !j.data) { showState("Something went wrong", "The server returned an unexpected response."); return null; }
            return render(j.data, cryptoKey);
          });
        });
      })
      .catch(function () {
        showState("Something went wrong", "Couldn’t load this subscription. Check your connection and try again.");
      });
  }

  if (!window.crypto || !crypto.subtle) {
    showState("Unsupported browser", "This page needs a modern browser with Web Crypto (and a secure https:// connection) to decrypt your configs.");
  } else {
    start();
  }
})();
