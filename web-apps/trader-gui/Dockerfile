# pm-trading-ui — single-container image.
#
# Mirrors terminal-gui/Dockerfile: builds the React frontend and serves it
# from the zero-dependency Node static server (apps/serve/serve.ts) on one
# port, so a production deployment is a single container listening on $PORT
# (8093). The server proxies /api/* (REST + WebSocket upgrades) to
# pm-api-gwy — see docker-compose.yml for how that's wired in.
#
# Typically build the image when behind a corporate proxy with:
#
# podman build --no-cache --pull --log-level=debug \
#  --build-arg HTTP_PROXY=http://host.containers.internal:9000 \
#  --build-arg HTTPS_PROXY=http://host.containers.internal:9000 \
#  --build-arg NO_PROXY=localhost,127.0.0.1 \
#  --build-arg NPM_STRICT_SSL=false \
#  -t trader-gui:latest -f Dockerfile .
#
# When not behind a proxy, build with:
# podman build --no-cache -t trader-gui:latest -f Dockerfile .

# ---- build stage -------------------------------------------------------------
FROM node:22-slim AS build
WORKDIR /app

# --- Corporate-network support (see terminal-gui/Dockerfile for precedent) ---
ARG HTTP_PROXY=${HTTP_PROXY:-}
ARG HTTPS_PROXY=${HTTPS_PROXY:-}
ARG NO_PROXY=${NO_PROXY:-}
ARG NPM_REGISTRY=${NPM_REGISTRY:-https://registry.npmjs.org/}
ARG NPM_STRICT_SSL=${NPM_STRICT_SSL:-true}

ENV HTTP_PROXY=${HTTP_PROXY} HTTPS_PROXY=${HTTPS_PROXY} NO_PROXY=${NO_PROXY} \
    http_proxy=${HTTP_PROXY} https_proxy=${HTTPS_PROXY} no_proxy=${NO_PROXY}

COPY package.json package-lock.json* tsconfig.base.json ./
COPY apps ./apps
RUN npm config set fetch-retries 2 \
 && npm config set fetch-timeout 120000 \
 && if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
 && if [ "$NPM_STRICT_SSL" = "false" ]; then npm config set strict-ssl false; fi \
 && if [ -f package-lock.json ]; then npm ci; else npm install; fi \
 && npm cache clean --force

RUN npm run build --workspace @edumatcher/trader-web

RUN npm prune --omit=dev

# ---- runtime stage -----------------------------------------------------------
FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=8093 \
    STATIC_DIR=/app/apps/web/dist

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/apps/serve ./apps/serve
COPY --from=build /app/apps/web/dist ./apps/web/dist
COPY --from=build /app/package.json /app/tsconfig.base.json ./

EXPOSE 8093
CMD ["npm", "run", "start", "--workspace", "@edumatcher/trader-serve"]
