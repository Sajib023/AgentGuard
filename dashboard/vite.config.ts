import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API + WS to the AgentGuard core (default :8907).
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/v1": { target: "http://127.0.0.1:8907", ws: true, changeOrigin: true },
    },
  },
  build: { outDir: "dist", target: "es2020" },
});
