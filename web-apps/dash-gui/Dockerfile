# EduMatcher Operator Dashboard (pm-dash) — single-container image.
#
# Mirrors book-gui/Dockerfile: builds the React frontend and serves it from
# the Fastify bridge on one port, so a production deployment is a single
# container listening on $PORT (8095). The bridge subscribes to pm-monitor's
# PUB socket (5611) and reads metrics.db read-only — see docker-compose.yml.
# zeromq is a native module; its prebuilt binary for linux-x64/arm64 glibc
# is what makes node:22-slim (no build toolchain) sufficient.
#
# Typically build the image when behind a corporate proxy with:
#
# podman build --no-cache --pull --log-level=debug \
#  --build-arg HTTP_PROXY=http://host.containers.internal:9000 \
#  --build-arg HTTPS_PROXY=http://host.containers.internal:9000 \
#  --build-arg NO_PROXY=localhost,127.0.0.1 \
#  --build-arg NPM_STRICT_SSL=false \
#  -t dash-gui:latest -f Dockerfile .
#
# When not behind a proxy, build with:
# podman build --no-cache -t dash-gui:latest -f Dockerfile .

# ---- build stage -------------------------------------------------------------
FROM node:22-slim AS build
WORKDIR /app

# --- Corporate-network support --------
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ARG WEB_PORT=8095
ARG NPM_REGISTRY=https://registry.npmjs.org/
ARG NPM_STRICT_SSL=true

ENV HTTP_PROXY=${HTTP_PROXY} HTTPS_PROXY=${HTTPS_PROXY} NO_PROXY=${NO_PROXY} \
    http_proxy=${HTTP_PROXY} https_proxy=${HTTPS_PROXY} no_proxy=${NO_PROXY}

COPY package.json package-lock.json* tsconfig.base.json ./
COPY packages ./packages
COPY apps ./apps

# Fail fast (in ~2 min) instead of hanging indefinitely when the network is
# blocked, and apply any registry / TLS overrides supplied via build args.
RUN npm config set fetch-retries 2 \
 && npm install --global npm@11.19.0 \
 && npm config set fetch-timeout 120000 \
 && if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
 && if [ "$NPM_STRICT_SSL" = "false" ]; then npm config set strict-ssl false; fi \
 && if [ -f package-lock.json ]; then npm ci; else npm install; fi \
 && npm cache clean --force

# Type-check and build the frontend bundle into apps/web/dist.
RUN npm run build --workspace @edumatcher/dash-web

# Drop dev-only dependencies to shrink the runtime image.
RUN npm prune --omit=dev

# ---- runtime stage -----------------------------------------------------------
FROM node:22-slim AS runtime
ARG WEB_PORT=8095

WORKDIR /app
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=${WEB_PORT} \
    STATIC_DIR=/app/apps/web/dist \
    LOG_FAILOVER_DIR=/app/logs

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/packages ./packages
COPY --from=build /app/apps/bridge ./apps/bridge
COPY --from=build /app/apps/web/dist ./apps/web/dist
COPY --from=build /app/package.json /app/tsconfig.base.json ./

# The bridge holds no durable state of its own — history is pm-monitor's
# metrics.db, mounted read-only. This volume exists only for the LALF
# failover log written when pm-log-srv is unreachable.
VOLUME ["/app/logs"]
EXPOSE ${WEB_PORT}
CMD ["npm", "run", "start", "--workspace", "@edumatcher/dash-bridge"]
