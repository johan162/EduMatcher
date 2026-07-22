import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const resolve = (p: string) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": resolve("./src"),
      // Resolve workspace packages directly to their TS source for a fast dev loop.
      "@edumatcher/schema": resolve("../../packages/schema/src/index.ts"),
      "@edumatcher/yaml-codec": resolve("../../packages/yaml-codec/src/index.ts"),
      "@edumatcher/diagnostics": resolve("../../packages/diagnostics/src/index.ts"),
    },
  },
  server: {
    port: 5174,
    proxy: {
      "/api": "http://127.0.0.1:5175",
    },
  },
});
