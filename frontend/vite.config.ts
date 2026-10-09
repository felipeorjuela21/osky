import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import basicSsl from "@vitejs/plugin-basic-ssl";

// The backend (FastAPI) runs on :8000; the dev server proxies /api to it.
// `npm run dev:lan` serves Osky to phones on the same Wi-Fi over HTTPS
// (mobile browsers only allow the microphone on secure pages). The backend
// stays private: phones only talk to this dev server.
export default defineConfig(({ mode }) => {
  const lan = mode === "lan";
  return {
    plugins: lan ? [react(), basicSsl()] : [react()],
    server: {
      port: lan ? 5175 : 5174,
      host: lan ? true : "localhost",
      proxy: { "/api": "http://127.0.0.1:8000", "/health": "http://127.0.0.1:8000" },
    },
  };
});
