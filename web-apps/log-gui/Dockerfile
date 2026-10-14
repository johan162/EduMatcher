# pm-log-ui — single-container image.
#
# Builds the React frontend and serves it from the Fastify bridge on one
# port, so a production deployment is a single container listening on
# $PORT (8091). The bridge still needs network access to pm-log-srv's
# LALF-PS ports (5601/5602) and filesystem access to log.db — see
# docker-compose.yml for how those are wired in.
#
# The runtime stage also carries a Python venv with the edumatcher package,
# because the Diagnostics view runs the real pm-log-cli rather than a second
# implementation of its heuristics.
#
# Build with:
# podman build --no-cache -t log-gui:latest -f Dockerfile .

# ---- build stage -------------------------------------------------------------
FROM node:22-trixie-slim AS build
WORKDIR /app

ARG WEB_PORT=8091

COPY package.json package-lock.json* tsconfig.base.json ./
COPY packages ./packages
COPY apps ./apps
RUN npm config set fetch-retries 2 \
 && npm install --global npm@11.19.0 \
 && npm config set fetch-timeout 120000 \
 && if [ -f package-lock.json ]; then npm ci; else npm install; fi \
 && npm cache clean --force

RUN npm run build --workspace @edumatcher/log-web

RUN npm prune --omit=dev

# ---- runtime stage -----------------------------------------------------------
FROM node:22-trixie-slim AS runtime
ARG WEB_PORT=8091

# The Diagnostics view shells out to pm-log-cli rather than reimplementing the
# seven heuristics in TypeScript, so the image needs the Python package too.
# Debian trixie's python3 is 3.13, which is what edumatcher requires.
ARG EDUMATCHER_VERSION=""

WORKDIR /app
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=${WEB_PORT} \
    STATIC_DIR=/app/apps/web/dist \
    LOG_DB_PATH=/app/data/log.db \
    ACK_STORE_PATH=/app/data/log-ui-acks.db \
    PATH=/opt/edumatcher/.venv/bin:$PATH

# .wheel/ holds a locally built wheel when one was placed there (the release
# workflow does), and only .keep otherwise. Its presence selects the source,
# exactly as in deployment/docker/Dockerfile.
COPY .wheel/ /tmp/wheel/
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-venv && \
    rm -rf /var/lib/apt/lists/* && \
    python3 -m venv /opt/edumatcher/.venv && \
    if ls /tmp/wheel/*.whl >/dev/null 2>&1; then \
        echo "Installing local wheel: $(ls /tmp/wheel/*.whl)" && \
        pip install --no-cache-dir /tmp/wheel/*.whl; \
    elif [ -n "${EDUMATCHER_VERSION}" ]; then \
        pip install --no-cache-dir "edumatcher==${EDUMATCHER_VERSION}"; \
    else \
        pip install --no-cache-dir edumatcher; \
    fi && \
    rm -rf /tmp/wheel && \
    pm-log-cli --help >/dev/null

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/packages ./packages
COPY --from=build /app/apps/bridge ./apps/bridge
COPY --from=build /app/apps/web/dist ./apps/web/dist
COPY --from=build /app/package.json /app/tsconfig.base.json ./

VOLUME ["/app/data"]
EXPOSE ${WEB_PORT}
CMD ["npm", "run", "start", "--workspace", "@edumatcher/log-bridge"]
