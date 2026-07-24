import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/auth": "http://localhost:8000",
      "/extract": "http://localhost:8000",
      "/generate-xml": "http://localhost:8000",
      "/invoices": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/clients": "http://localhost:8000",
      "/corrections": "http://localhost:8000",
      "/preview-masters": "http://localhost:8000",
      "/pre-import-check": "http://localhost:8000",
      "/trial-balance": "http://localhost:8000",
      "/pnl": "http://localhost:8000",
      "/balance-sheet": "http://localhost:8000",
      "/firm-dashboard": "http://localhost:8000",
      "/client-dashboard": "http://localhost:8000",
      "/compliance": "http://localhost:8000",
      "/gstr-reconcile": "http://localhost:8000",
      "/banking": "http://localhost:8000",
      "/ledgers": "http://localhost:8000",
      "/config": "http://localhost:8000",
      "/rules-engine": "http://localhost:8000",
      "/metrics": "http://localhost:8000",
    },
  },
});
