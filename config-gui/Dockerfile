# EduMatcher Config Builder — single-container image.
#
# Builds the React frontend and serves it from the Fastify API on one port,
# so a production deployment is a single container listening on $PORT (8080).
#
# The optional "Verify with pm-cverifier" button needs the Python toolchain,
# which is NOT included here; that endpoint returns a friendly 503 in this
# image. Everything else works. See docs/user-guide/27-config-GUI.md.

# ---- build stage -------------------------------------------------------------
FROM node:22-slim AS build
WORKDIR /app

# Install workspace dependencies first (better layer caching).
COPY package.json package-lock.json* tsconfig.base.json ./
COPY packages ./packages
COPY apps ./apps
RUN npm install

# Type-check and build the frontend bundle into apps/web/dist.
RUN npm run build --workspace @edumatcher/web

# Drop dev-only dependencies to shrink the runtime image.
RUN npm prune --omit=dev

# ---- runtime stage -----------------------------------------------------------
FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=8080 \
    STATIC_DIR=/app/apps/web/dist

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/packages ./packages
COPY --from=build /app/apps/server ./apps/server
COPY --from=build /app/apps/web/dist ./apps/web/dist
COPY --from=build /app/package.json /app/tsconfig.base.json ./

EXPOSE 8080
# tsx (a server runtime dependency) runs the TypeScript server directly;
# suitable for this internal tool.
CMD ["npm", "run", "start", "--workspace", "@edumatcher/server"]
