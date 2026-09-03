# EduMatcher Trading Desk UI — single-container image.
#
#


# ---- build stage -------------------------------------------------------------
FROM node:22-slim AS build
WORKDIR /app

# --- Corporate-network support --------
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ARG WEB_PORT=8093
ARG NPM_REGISTRY=https://registry.npmjs.org/
ARG NPM_STRICT_SSL=true

# Export proxy vars so npm (and node's fetch) honour them during the build.
ENV HTTP_PROXY=${HTTP_PROXY} HTTPS_PROXY=${HTTPS_PROXY} NO_PROXY=${NO_PROXY} \
    http_proxy=${HTTP_PROXY} https_proxy=${HTTPS_PROXY} no_proxy=${NO_PROXY}

COPY package.json package-lock.json* tsconfig.base.json ./
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
RUN npm run build --workspace @edumatcher/trader-web

# Drop dev-only dependencies to shrink the runtime image.
RUN npm prune --omit=dev

# ---- runtime stage -----------------------------------------------------------
FROM node:22-slim AS runtime
ARG WEB_PORT=8093

WORKDIR /app
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=${WEB_PORT} \
    STATIC_DIR=/app/apps/web/dist

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/apps/serve ./apps/serve
COPY --from=build /app/apps/web/dist ./apps/web/dist
COPY --from=build /app/package.json /app/tsconfig.base.json ./

EXPOSE ${WEB_PORT}
CMD ["npm", "run", "start", "--workspace", "@edumatcher/trader-serve"]
