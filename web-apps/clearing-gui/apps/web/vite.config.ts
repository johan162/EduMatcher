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
    port: 8196,
    proxy: {
      // The browser talks to its own origin only; /api is forwarded to
      // pm-api-gwy, which owns every clearing read. Same as trader-gui.
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
  build: {
    target: "esnext",
    sourcemap: true,
  },
});
