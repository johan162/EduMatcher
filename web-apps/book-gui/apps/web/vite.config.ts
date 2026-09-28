import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const resolve = (p: string) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": resolve("./src"),
      "@edumatcher/book-types": resolve("../../packages/book-types/src/index.ts"),
    },
  },
  server: {
    port: 8194,
    proxy: {
      "/api": "http://127.0.0.1:5194",
      "/ws": {
        target: "ws://127.0.0.1:5194",
        ws: true,
      },
    },
  },
});
