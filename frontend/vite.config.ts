import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the backend runs on :8000 (uvicorn); in production nginx serves dist/ and proxies /api and /auth.
const backend = process.env.WWC_BACKEND ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 8080,
    proxy: { "/api": backend, "/auth": backend },
  },
});
