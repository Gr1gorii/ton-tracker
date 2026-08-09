import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API base URL is configured in src/apiBase.ts via the
// VITE_API_BASE env var (defaults to http://localhost:8000).
export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: "tonconnect",
              test: /node_modules[\\/]@tonconnect[\\/]/,
              priority: 10,
            },
          ],
        },
      },
    },
  },
  server: {
    port: 5173,
    // Fail loudly if 5173 is taken instead of drifting to another port —
    // the backend CORS allowlist is pinned to 5173.
    strictPort: true,
  },
});
