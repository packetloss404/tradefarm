import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Tauri's dev server reads STREAM_BACKEND_URL at build time and proxies /api
// + /ws there so the browser-side fetcher just calls relative paths. Default
// is the local FastAPI backend; override via env when streaming from a
// different machine (the Tauri shell also reads a settings file at runtime
// — see src/settings.ts — but that path applies to packaged builds, not the
// vite dev proxy).
const BACKEND = process.env.STREAM_BACKEND_URL ?? "http://127.0.0.1:8000";
const WS_BACKEND = BACKEND.replace(/^http/, "ws");

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Vite is launched by `tauri dev` which expects this fixed dev URL.
  server: {
    port: 5180,
    strictPort: true,
    host: "127.0.0.1",
    proxy: {
      "/api": { target: BACKEND, rewrite: (p) => p.replace(/^\/api/, ""), changeOrigin: true },
      "/ws": { target: WS_BACKEND, ws: true, changeOrigin: true },
    },
  },
  // Tauri's bundled assets need a relative base.
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
  },
  envPrefix: ["VITE_", "TAURI_"],
});
