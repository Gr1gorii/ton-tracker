import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// v0.1 dev server. The API base URL is configured in src/api.ts via the
// VITE_API_BASE env var (defaults to http://localhost:8000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Fail loudly if 5173 is taken instead of drifting to another port —
    // the backend CORS allowlist is pinned to 5173.
    strictPort: true,
  },
});
