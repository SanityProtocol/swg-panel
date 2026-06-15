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
# which exits 0 even when its own download fails — silently shipping an image with no acme.sh).
# Download is retried, then `acme.sh --version` VERIFIES it landed so a bad fetch fails the build.
ARG ACME_VERSION=3.1.3
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssl ca-certificates curl socat tar \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL --retry 5 --retry-delay 3 --retry-all-errors \
      "https://github.com/acmesh-official/acme.sh/archive/refs/tags/${ACME_VERSION}.tar.gz" -o /tmp/acme.tar.gz \
 && mkdir -p /tmp/acme && tar -xzf /tmp/acme.tar.gz -C /tmp/acme --strip-components=1 \
 && ( cd /tmp/acme && ./acme.sh --install --home /opt/acme.sh --nocron --noprofile ) \
 && ln -sf /opt/acme.sh/acme.sh /usr/local/bin/acme.sh \
 && /opt/acme.sh/acme.sh --version \
 && rm -rf /tmp/acme /tmp/acme.tar.gz

WORKDIR /opt/swg-panel
COPY swg-panel-server app.css app.js index.html reconcile.js VERSION ./
COPY vendor/ ./vendor/
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh ./swg-panel-server

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
