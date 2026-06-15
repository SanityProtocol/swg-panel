# swg-panel — control-plane (broker + UI) image.
# Self-contained: serves its own TLS + login + the /wgstats board. Nodes reach the
# panel over OUTBOUND HTTPS (no ssh, no inbound) — add them in the Nodes screen.
# Python + openssl + acme.sh (bundled, so the container can issue real TLS certs:
# letsencrypt / cloudflare / cf15 — same options as bare-metal). Nodes run bare-metal
# (install-node.sh) or as the companion swg-node image (see Dockerfile.node).
# Base from AWS ECR Public (mirrors Docker Hub official images) to dodge Docker Hub's
# anonymous pull-rate limit — no account needed. Prebuilt images are also on GHCR (see CI).
FROM public.ecr.aws/docker/library/python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends openssl ca-certificates curl socat \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL https://get.acme.sh | sh -s -- --home /opt/acme.sh --nocron --noprofile \
 && ln -sf /opt/acme.sh/acme.sh /usr/local/bin/acme.sh

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
