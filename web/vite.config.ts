/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the API so the browser talks to one origin (no CORS, no key in the build).
const target = process.env.P2E_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": target, "/health": target } },
  test: { environment: "node", include: ["src/**/*.test.{ts,tsx}"] },
});
