import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// The Flask backend serves web/dist at / in production. In development Vite
// serves the source and proxies everything the backend owns.
const backend = "http://127.0.0.1:5000";

export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/thumb": backend,
      "/image": backend,
      "/legacy": backend,
    },
  },
});
