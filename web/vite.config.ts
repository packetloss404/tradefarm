import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Backend target — defaults to local uvicorn. For the split-machine setup
// (dashboard on workstation, backend on a broadcast VM), set
// TRADEFARM_BACKEND=<vm-host>:8000 in web/.env.local or in the shell before
// running. See web/.env.example.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.TRADEFARM_BACKEND || "127.0.0.1:8000";
  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5179,
      strictPort: true,
      proxy: {
        "/api": {
          target: `http://${backend}`,
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/api/, ""),
        },
        // VOD asset streaming — serves the rendered MP4 + thumbnail
        // from out/sessions/<id>/. Same origin as the dashboard, so
        // the <video> element can stream the file directly and the
        // download button gets a clean relative URL.
        "/vod": {
          target: `http://${backend}`,
          changeOrigin: true,
        },
        // Live event stream — must be proxied as a WebSocket. `changeOrigin`
        // rewrites the Origin header to the backend's host so CORS-on-WS (if
        // any) sees a same-origin upgrade.
        "/ws": {
          target: `ws://${backend}`,
          ws: true,
          changeOrigin: true,
        },
      },
    },
  };
});
