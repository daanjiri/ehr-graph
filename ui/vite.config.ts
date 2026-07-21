import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    // 127.0.0.1 explícito: en Windows `localhost` puede resolver a ::1 y
    // acabar en otro servicio que publique el mismo puerto por IPv6.
    proxy: { "/api": "http://127.0.0.1:8010" },
  },
});
