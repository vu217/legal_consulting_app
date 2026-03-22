import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/** Backend for dev/preview proxy — browser calls same-origin /api → forwarded here. */
const DEFAULT_BACKEND = "http://127.0.0.1:8000";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const proxyTarget = env.VITE_BACKEND_PROXY_TARGET || DEFAULT_BACKEND;

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
    preview: {
      port: 4173,
      proxy: {
        "/api": {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
