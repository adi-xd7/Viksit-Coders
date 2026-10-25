import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dev server proxies the API (default http://127.0.0.1:8000; override with RAGNAROK_API).
const api = process.env.RAGNAROK_API ?? "http://127.0.0.1:8000";
const proxied = ["/cases", "/docs", "/trade", "/feed", "/ingest", "/api"];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(proxied.map((p) => [p, { target: api, changeOrigin: true }])),
  },
});
