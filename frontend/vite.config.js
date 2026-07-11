import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/clients": "http://localhost:8000",
      "/extract": "http://localhost:8000",
      "/generate-xml": "http://localhost:8000",
      "/invoices": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/auth": "http://localhost:8000",
      "/api": "http://localhost:8000",
      "/preview-masters": "http://localhost:8000",
      "/pre-import-check": "http://localhost:8000",
      "/corrections": "http://localhost:8000",
    },
  },
});
