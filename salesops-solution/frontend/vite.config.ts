import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Serve the SPA under the `/keysight-salesops/` base path so the production
// URL (https://app.solution.zbrain.ai/keysight-salesops/) and the local dev
// URL stay identical. Vite generates asset references relative to this base.
export default defineConfig({
  base: "/keysight-salesops/",
  plugins: [react()],
  server: {
    port: 5173,
    // Bind to all interfaces so Caddy can reach Vite over 127.0.0.1 IPv4.
    host: true,
    // Caddy fronts the dev server on app.solution.zbrain.ai; Vite must accept
    // requests with that Host header.
    allowedHosts: ["app.solution.zbrain.ai", "localhost", "127.0.0.1", ".trycloudflare.com"],
    // HMR over the public hostname works only if we tell Vite where the
    // WebSocket should target.
    hmr: {
      host: "app.solution.zbrain.ai",
      protocol: "wss",
      clientPort: 443,
    },
    proxy: {
      "/api": "http://localhost:8000",
      "/files": "http://localhost:8000",
    },
  },
});
