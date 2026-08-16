# pm-terminal — single-container image.
#
# Mirrors log-gui/Dockerfile: builds the React frontend and serves it from the
# Fastify bridge on one port, so a production deployment is a single container
# listening on $PORT (8090). The bridge still needs network access to
# pm-md-gwy's CALF port (5570) and pm-api-gwy (8080) — see docker-compose.yml
# for how those are wired in.
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
 && if [ -f package-lock.json ]; then npm ci; else npm install; fi \
 && npm cache clean --force

RUN npm run build --workspace @edumatcher/terminal-web

RUN npm prune --omit=dev

# ---- runtime stage -----------------------------------------------------------
FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=8090 \
    STATIC_DIR=/app/apps/web/dist \
    LOG_FAILOVER_DIR=/app/logs

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/packages ./packages
COPY --from=build /app/apps/bridge ./apps/bridge
COPY --from=build /app/apps/web/dist ./apps/web/dist
COPY --from=build /app/package.json /app/tsconfig.base.json ./

# The bridge holds no durable state of its own (design §3.2 — all history
# stays in pm-stats behind pm-api-gwy). This volume exists only for the LALF
# failover log written when pm-log-srv is unreachable (§17.5).
VOLUME ["/app/logs"]
EXPOSE 8090
CMD ["npm", "run", "start", "--workspace", "@edumatcher/terminal-bridge"]
