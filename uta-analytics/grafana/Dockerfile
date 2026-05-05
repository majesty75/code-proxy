# Custom Grafana image that:
#   1. (Optional) trusts a corporate root CA so plugin downloads work behind
#      MITM-style TLS-inspecting firewalls.
#   2. Pre-installs the ClickHouse datasource at build time so the runtime
#      container never needs to reach grafana.com.
#   3. Falls back to a pre-downloaded plugin .zip if the user can't get
#      grafana.com to work even with the corp CA installed.
#
# Build (with corp CA + online plugin install):
#     # 1. drop your corp root CA here as ./grafana/corp-ca.crt (PEM-encoded)
#     # 2. docker compose build grafana
#
# Build (offline — corp CA + pre-downloaded plugin .zip):
#     # 1. on a connected machine:
#     #      curl -L -o grafana-clickhouse-datasource.zip \
#     #        https://grafana.com/api/plugins/grafana-clickhouse-datasource/versions/latest/download
#     # 2. drop it at ./grafana/plugins/grafana-clickhouse-datasource.zip
#     # 3. docker compose build grafana
#
# Build (no corp network at all):
#     # the offline-zip path works even with no internet — just the local zip.
#
# All inputs are optional; the build steps tolerate any combination.

ARG GRAFANA_VERSION=latest
FROM grafana/grafana-oss:${GRAFANA_VERSION}

USER root

# 1. Trust the corporate CA (if present). Doing this BEFORE plugin install so
#    "grafana cli plugins install" can hit grafana.com through the firewall.
COPY --chown=root:root corp-ca.crt* /tmp/corp-certs/
RUN set -e; \
    if ls /tmp/corp-certs/*.crt >/dev/null 2>&1; then \
      echo "→ Installing corporate CA into system trust store"; \
      mkdir -p /usr/local/share/ca-certificates; \
      for f in /tmp/corp-certs/*.crt; do \
        cp "$f" "/usr/local/share/ca-certificates/$(basename "$f")"; \
      done; \
      update-ca-certificates; \
    else \
      echo "→ No corporate CA at ./grafana/corp-ca.crt — assuming public network"; \
    fi; \
    rm -rf /tmp/corp-certs

# 2. Install the ClickHouse datasource into the BUNDLED plugin path
#    (/usr/share/grafana/data/plugins-bundled). The runtime grafana-data volume
#    masks /var/lib/grafana/plugins, so we deliberately install elsewhere — the
#    bundled path is in the default plugin search list.
COPY --chown=root:root plugins/* /tmp/plugins/
ENV BUNDLED_PLUGINS=/usr/share/grafana/data/plugins-bundled
RUN set -e; \
    PLUGIN="grafana-clickhouse-datasource"; \
    mkdir -p "${BUNDLED_PLUGINS}"; \
    if ls /tmp/plugins/${PLUGIN}*.zip >/dev/null 2>&1; then \
      ZIP=$(ls /tmp/plugins/${PLUGIN}*.zip | head -1); \
      echo "→ Installing ${PLUGIN} from $ZIP (offline)"; \
      grafana cli --pluginsDir "${BUNDLED_PLUGINS}" --pluginUrl "file://${ZIP}" plugins install ${PLUGIN}; \
    else \
      echo "→ Installing ${PLUGIN} from grafana.com"; \
      grafana cli --pluginsDir "${BUNDLED_PLUGINS}" plugins install ${PLUGIN}; \
    fi; \
    rm -rf /tmp/plugins; \
    chown -R grafana:root "${BUNDLED_PLUGINS}"

# 3. Drop back to the unprivileged user the upstream image uses.
USER grafana

# Tell Grafana the plugin is already installed so the entrypoint doesn't try
# to re-download it on every container start (avoids the runtime TLS hit).
ENV GF_INSTALL_PLUGINS=""
