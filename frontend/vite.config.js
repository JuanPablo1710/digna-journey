import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  envDir: "..",
  server: {
    proxy: {
      "/health": "http://localhost:8000",
      "/catalog": "http://localhost:8000",
      "/channels": "http://localhost:8000",
      "/cases": "http://localhost:8000",
      "/identity": "http://localhost:8000",
      "/auth": "http://localhost:8000",
      "/agent": "http://localhost:8000",
      "/demo": "http://localhost:8000",
      "/resume": "http://localhost:8000",
    },
  },
});

