import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Serve the SPA under the `/keysight-salesops-governance/` base path so the
// production URL (https://app.solution.zbrain.ai/keysight-salesops-governance/)
// and the local dev URL stay identical. Vite generates asset references
// relative to this base.
//
// The dev proxy forwards every /api/* call to the live SalesOps backend on
// port 8000 — that's the single source of truth for governance data. The
// governance dashboard has no backend of its own.
export default defineConfig({
  base: "/keysight-salesops-governance/",
  plugins: [react()],
  server: {
    port: 5175,
    host: true,
    allowedHosts: ["app.solution.zbrain.ai", "localhost", "127.0.0.1", ".trycloudflare.com"],
    hmr: {
      host: "app.solution.zbrain.ai",
      protocol: "wss",
      clientPort: 443,
    },
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
