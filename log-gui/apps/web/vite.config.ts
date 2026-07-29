import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const resolve = (p: string) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": resolve("./src"),
      "@edumatcher/log-types": resolve("../../packages/log-types/src/index.ts"),
    },
  },
  server: {
    port: 5178,
    proxy: {
      "/api": "http://127.0.0.1:8091",
      "/ws": {
        target: "ws://127.0.0.1:8091",
        ws: true,
      },
    },
  },
});
