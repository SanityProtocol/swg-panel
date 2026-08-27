# swg-panel — control-plane (broker + UI) image.
# Self-contained: serves its own TLS + login + the /wgstats board. Nodes reach the
# panel over OUTBOUND HTTPS (no ssh, no inbound) — add them in the Nodes screen.
# Python + openssl + acme.sh (bundled, so the container can issue real TLS certs:
# letsencrypt / cloudflare / cf15 — same options as bare-metal). Nodes run bare-metal
# (install-node.sh) or as the companion swg-node image (see Dockerfile.node).
# Base from AWS ECR Public (mirrors Docker Hub official images) to dodge Docker Hub's
# anonymous pull-rate limit — no account needed. Prebuilt images are also on GHCR (see CI).
FROM public.ecr.aws/docker/library/python:3.12-slim

# acme.sh is pinned + installed from its release tarball (not the piped get.acme.sh installer,
# which exits 0 even when its own download fails — silently shipping an image with no acme.sh;
# it also serves master, currently 3.1.5, which is NOT a tagged release).
# Download is retried, then `acme.sh --version` VERIFIES it landed so a bad fetch fails the build.
# ⚠️ FLOOR, not just a pin: 3.1.4 is the first release that refuses to write the CA's HTTP body to
# <domain>.cer when that body is not a certificate. On 3.1.3 and older a 404 from the CA is stored
# AS the cert, with no fullchain.cer beside it — the container then treats a failed issuance as a
# success and serves no usable TLS. Do not lower this below 3.1.4.
ARG ACME_VERSION=3.1.4
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssl ca-certificates curl socat tar \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL --retry 5 --retry-delay 3 --retry-all-errors \
      "https://github.com/acmesh-official/acme.sh/archive/refs/tags/${ACME_VERSION}.tar.gz" -o /tmp/acme.tar.gz \
 && mkdir -p /tmp/acme && tar -xzf /tmp/acme.tar.gz -C /tmp/acme --strip-components=1 \
 && ( cd /tmp/acme && ./acme.sh --install --home /opt/acme.sh --nocron --noprofile ) \
 # bundle the DNS plugins so 'cloudflare' (DNS-01) never has to fetch dns_cf.sh from GitHub at
 # runtime (which fails on networks that can't reach GitHub); verify the cf plugin is present.
 && mkdir -p /opt/acme.sh/dnsapi && cp -rf /tmp/acme/dnsapi/. /opt/acme.sh/dnsapi/ \
 && ln -sf /opt/acme.sh/acme.sh /usr/local/bin/acme.sh \
 && /opt/acme.sh/acme.sh --version \
 && test -f /opt/acme.sh/dnsapi/dns_cf.sh \
 && rm -rf /tmp/acme /tmp/acme.tar.gz

WORKDIR /opt/swg-panel
COPY swg-panel-server app.css app.js index.html reconcile.js turn-artifacts.js VERSION ./
# swg-sub — the public subscription surface + its buildless front-end. Rides in this image (pure
# stdlib, no extra deps) but runs as a SEPARATE, read-only container (see docker-compose.yml).
# turn-artifacts.js is shared by the admin app + the subscription page (already copied above).
COPY swg-sub sub.html sub.js sub.css ./
COPY swg-passwd /usr/local/bin/swg-passwd
COPY vendor/ ./vendor/
# js/ = the SPA's ES modules (docs/APP-JS-SPLIT-PLAN.md) — copied as a DIRECTORY, like vendor/, so adding a module never touches this loop
COPY js/ ./js/
# Verify the SPA the image will serve. There is no source tree to compare against in here — the build
# context is gone by the time this runs — so instead check the property that actually matters: every
# relative import in every module resolves to a file that exists. That is self-describing (the code IS the
# list), it can never go stale, and it catches the failure this exists for: a module lost to .dockerignore
# or a truncated context. A mismatch FAILS THE BUILD, because an image is built once and run everywhere,
# so an incomplete one would ship a blank panel to every container.
RUN python3 - ./js ./app.js <<'PYJS'
import os, re, sys
jsdir, entry = sys.argv[1], sys.argv[2]
files = [entry] + [os.path.join(jsdir, f) for f in sorted(os.listdir(jsdir)) if f.endswith(".js")]
subdirs = [os.path.join(r, f) for r, _d, fs in os.walk(jsdir) for f in fs if f.endswith(".js")]
files = sorted(set(files) | set(subdirs))
spec = re.compile(r"""(?:import|export)[^;'"]*?from\s*["']([^"']+)["']|import\s*\(\s*["']([^"']+)["']""")
missing, edges = [], 0
for f in files:
    src = open(f, encoding="utf-8").read()
    for m in spec.finditer(src):
        target = m.group(1) or m.group(2)
        if not target.startswith("."):          # preact / htm — resolved by the importmap, not on disk
            continue
        edges += 1
        p = os.path.normpath(os.path.join(os.path.dirname(f), target))
        if not os.path.exists(p):
            missing.append("%s -> %s" % (os.path.basename(f), target))
print("SPA: %d modules, %d local imports, all resolved" % (len(files), edges) if not missing
      else "SPA: %d local imports checked" % edges)
if missing:
    sys.exit("INCOMPLETE SPA in the image — unresolved: " + "; ".join(missing[:8]))
PYJS
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh ./swg-panel-server ./swg-sub /usr/local/bin/swg-passwd

ENV SWG_PANEL_WEB=/opt/swg-panel \
    SWG_PANEL_FLEET=/etc/swg-panel/fleet.json \
    SWG_PANEL_HOST=0.0.0.0 \
    SWG_PANEL_PORT=8443 \
    SWG_PANEL_AUTH=/etc/swg-panel/auth \
    SWG_PANEL_TLS_CERT=/etc/swg-panel/tls/fullchain.pem \
    SWG_PANEL_TLS_KEY=/etc/swg-panel/tls/key.pem \
    STATS_DIR=/var/www/wgstats \
    PANEL_USER=admin \
    TLS=selfsigned

EXPOSE 8443
ENTRYPOINT ["/entrypoint.sh"]
