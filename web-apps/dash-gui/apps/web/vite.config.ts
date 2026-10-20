import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const resolve = (p: string) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": resolve("./src"),
      "@edumatcher/dash-types": resolve("../../packages/dash-types/src/index.ts"),
    },
  },
  server: {
    port: 8195,
    proxy: {
      "/api": "http://127.0.0.1:5195",
      "/ws": {
        target: "ws://127.0.0.1:5195",
        ws: true,
      },
    },
  },
});
