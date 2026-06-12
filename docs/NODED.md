# swg-noded — the node daemon

One outbound-only HTTPS loop. No inbound socket, no SSH, no rsync.

Every `node.interval` seconds it:

1. **samples** each managed interface (`awg show <if> dump` + the interface `.conf`) into
   a snapshot of peers + per-interface `meta`;
2. **POSTs** it to `panel.url` + `/api/node/sync` with `Authorization: Bearer <token>`;
3. receives `{ "desired": { "<iface>": [ {public_key, allowed_ips, preshared_key, name} ] },
   "interval": N }`;
4. **reconciles**: for each interface, adds peers in `desired` that are missing and removes
   live peers that are not in `desired`, each through `swg-agent`.

Safeguard: it reconciles **only** on a valid HTTP 200 with a `desired` object. A network
error, a 401, or a TLS pin failure skips the pass — peers are never wiped by an outage.

## Config — `/etc/swg-agent/config.json`

```json
{
  "interfaces": { "awg0": { "cmd": ["awg"], "conf": "/etc/amnezia/amneziawg/awg0.conf" } },
  "endpoint_host": "203.0.113.7",
  "dns": ["1.1.1.1"],
  "panel": { "url": "https://panel.example.net:8443", "token": "…",
             "verify": false, "fingerprint": null },
  "node":  { "interval": 5, "agent": "/opt/swg-agent/swg-agent", "sudo": false }
}
```

List every interface the node serves; each peer is applied to the one it belongs to.

## TLS

- `verify: true` — verify the panel's certificate against system CAs (use a real cert).
- `fingerprint: "<sha256-hex>"` — pin a self-signed cert; the fingerprint is checked
  **during the TLS handshake, before the token is sent**, and fails closed.
- neither — encrypted but unverified (fine on a trusted path; pin or verify otherwise).

Runs as root (it samples the kernel interface and runs the agent, which writes `.conf`
under `/etc`). With `node.sudo: false` the agent is executed directly.
