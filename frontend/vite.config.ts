import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const backend = process.env.ORBIT_BACKEND_URL ?? "http://127.0.0.1:18700";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/health": { target: backend, changeOrigin: true },
      "/openapi.json": { target: backend, changeOrigin: true },
      "/docs": { target: backend, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    restoreMocks: true,
  },
});