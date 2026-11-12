import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const resolve = (p: string) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": resolve("./src"),
    },
  },
  server: {
    port: 8193,
    proxy: {
      // Optional own pm-api-gwy instance for the admin feed, matching
      // API_ADMIN_MONITOR_TARGET in pm-trading-ui-serve. Listed first: the
      // first matching context wins.
      ...(process.env.API_ADMIN_MONITOR_TARGET
        ? {
            "/api/v1/ws/admin/monitor": {
              target: process.env.API_ADMIN_MONITOR_TARGET,
              changeOrigin: true,
              ws: true,
            },
          }
        : {}),
      // Forward REST and WebSocket calls to pm-api-gwy during development,
      // avoiding browser CORS restrictions.
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
        ws: true, // proxy WebSocket upgrades (/api/v1/ws/private, /ws/market-data, /ws/admin/monitor)
      },
    },
  },
  build: {
    target: "esnext",
    sourcemap: true,
  },
  define: {
    // Expose package version to the app
    __APP_VERSION__: JSON.stringify(process.env.npm_package_version ?? "0.0.0"),
  },
});
