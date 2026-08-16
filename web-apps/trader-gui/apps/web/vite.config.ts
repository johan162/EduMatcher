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
    port: 5173,
    proxy: {
      // Forward REST and WebSocket calls to pm-api-gwy during development,
      // avoiding browser CORS restrictions.
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
        ws: true, // proxy WebSocket upgrades (/events, /market-data, /admin/monitor)
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
