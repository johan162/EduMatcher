# EduMatcher Config Builder — single-container image.
#
# Builds the React frontend and serves it from the Fastify API on one port,
# so a production deployment is a single container listening on $PORT (8080).
#
# The optional "Verify with pm-cverifier" button needs the Python toolchain,
# which is NOT included here; that endpoint returns a friendly 503 in this
# image. Everything else works. See docs/user-guide/030-config-GUI.md.

# Typically build the image when behind a corporate proxy with:
#
# podman build --no-cache --pull --log-level=debug \
#  --build-arg HTTP_PROXY=http://host.containers.internal:9000 \
#  --build-arg HTTPS_PROXY=http://host.containers.internal:9000 \
#  --build-arg NO_PROXY=localhost,127.0.0.1 \
#  --build-arg NPM_STRICT_SSL=false \
#  -t config-gui:latest -f Dockerfile .
#
# When not behind a proxy, build with:
# podman build --no-cache -t config-gui:latest -f Dockerfile .

# Typically run the backend (non-interactive) with:
# podman run --rm -it -p 8092:8092 config-gui:latest
#
# (Press Ctrl-C to stop the container, or use `podman ps` and `podman stop <id>`.)
# 

# ---- build stage -------------------------------------------------------------
FROM node:22-slim AS build
WORKDIR /app

# --- Corporate-network support --------
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ARG WEB_PORT=8092
ARG NPM_REGISTRY=https://registry.npmjs.org/
ARG NPM_STRICT_SSL=true

# Export proxy vars so npm (and node's fetch) honour them during the build.
ENV HTTP_PROXY=${HTTP_PROXY} HTTPS_PROXY=${HTTPS_PROXY} NO_PROXY=${NO_PROXY} \
    http_proxy=${HTTP_PROXY} https_proxy=${HTTPS_PROXY} no_proxy=${NO_PROXY}

# Install workspace dependencies first (better layer caching).
COPY package.json package-lock.json* tsconfig.base.json ./
COPY packages ./packages
COPY apps ./apps
# Fail fast (in ~2 min) instead of hanging indefinitely when the network is
# blocked, and apply any registry / TLS overrides supplied via build args.
RUN npm config set fetch-retries 2 \
 && npm config set fetch-timeout 120000 \
 && if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
 && if [ "$NPM_STRICT_SSL" = "false" ]; then npm config set strict-ssl false; fi \
 && if [ -f package-lock.json ]; then npm ci; else npm install; fi \
 && npm cache clean --force

# Type-check and build the frontend bundle into apps/web/dist.
RUN npm run build --workspace @edumatcher/web

# Drop dev-only dependencies to shrink the runtime image.
RUN npm prune --omit=dev

# ---- runtime stage -----------------------------------------------------------
FROM node:22-slim AS runtime
ARG WEB_PORT=8092

WORKDIR /app
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=${WEB_PORT} \
    STATIC_DIR=/app/apps/web/dist

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/packages ./packages
COPY --from=build /app/apps/server ./apps/server
COPY --from=build /app/apps/web/dist ./apps/web/dist
COPY --from=build /app/package.json /app/tsconfig.base.json ./

EXPOSE ${WEB_PORT}
# tsx (a server runtime dependency) runs the TypeScript server directly;
# suitable for this internal tool.
CMD ["npm", "run", "start", "--workspace", "@edumatcher/server"]
