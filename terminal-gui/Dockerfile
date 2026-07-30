# pm-terminal — single-container image.
#
# Mirrors log-gui/Dockerfile. One difference today: apps/web does not exist
# yet (Phase 5), so this builds and runs the bridge alone — the container
# serves /api and /ws but no UI. The two commented lines below are the whole
# change needed once the frontend lands; STATIC_DIR is deliberately left unset
# until then, since the bridge only registers the static handler when it is
# set, and pointing it at a missing directory would 500 every page request.
#
# Typically build the image when behind a corporate proxy with:
#
# podman build --no-cache --pull --log-level=debug \
#  --build-arg HTTP_PROXY=http://host.containers.internal:9000 \
#  --build-arg HTTPS_PROXY=http://host.containers.internal:9000 \
#  --build-arg NO_PROXY=localhost,127.0.0.1 \
#  --build-arg NPM_STRICT_SSL=false \
#  -t terminal-gui:latest -f Dockerfile .
#
# When not behind a proxy, build with:
# podman build --no-cache -t terminal-gui:latest -f Dockerfile .

# ---- build stage -------------------------------------------------------------
FROM node:22-slim AS build
WORKDIR /app

# --- Corporate-network support (see log-gui/Dockerfile for precedent) --------
ARG HTTP_PROXY=${HTTP_PROXY:-}
ARG HTTPS_PROXY=${HTTPS_PROXY:-}
ARG NO_PROXY=${NO_PROXY:-}
ARG NPM_REGISTRY=${NPM_REGISTRY:-https://registry.npmjs.org/}
ARG NPM_STRICT_SSL=${NPM_STRICT_SSL:-true}

ENV HTTP_PROXY=${HTTP_PROXY} HTTPS_PROXY=${HTTPS_PROXY} NO_PROXY=${NO_PROXY} \
    http_proxy=${HTTP_PROXY} https_proxy=${HTTPS_PROXY} no_proxy=${NO_PROXY}

COPY package.json package-lock.json* tsconfig.base.json ./
COPY packages ./packages
COPY apps ./apps
RUN npm config set fetch-retries 2 \
 && npm config set fetch-timeout 120000 \
 && if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
 && if [ "$NPM_STRICT_SSL" = "false" ]; then npm config set strict-ssl false; fi \
 && npm install

# Phase 5: uncomment once apps/web exists.
# RUN npm run build --workspace @edumatcher/terminal-web

RUN npm prune --omit=dev

# ---- runtime stage -----------------------------------------------------------
FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=8090 \
    LOG_FAILOVER_DIR=/app/logs
# Phase 5: add STATIC_DIR=/app/apps/web/dist to the ENV block above.

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/packages ./packages
COPY --from=build /app/apps/bridge ./apps/bridge
# Phase 5: COPY --from=build /app/apps/web/dist ./apps/web/dist
COPY --from=build /app/package.json /app/tsconfig.base.json ./

# The bridge holds no durable state of its own (design §3.2 — all history
# stays in pm-stats behind pm-api-gwy). This volume exists only for the LALF
# failover log written when pm-log-srv is unreachable (§17.5).
VOLUME ["/app/logs"]
EXPOSE 8090
CMD ["npm", "run", "start", "--workspace", "@edumatcher/terminal-bridge"]
