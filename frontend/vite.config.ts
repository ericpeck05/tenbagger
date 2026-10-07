import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// API_PORT and PORT let a second copy run alongside (for example against a scratch database).
const apiPort = process.env.API_PORT ?? "8000";
const port = Number(process.env.PORT ?? 5173);

export default defineConfig({
  plugins: [react()],
  server: {
    port,
    strictPort: true,
    proxy: { "/api": `http://127.0.0.1:${apiPort}` },
  },
});
