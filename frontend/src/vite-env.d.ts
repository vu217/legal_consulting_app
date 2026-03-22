/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  /** Dev/preview proxy target for /api (default http://127.0.0.1:8000) */
  readonly VITE_BACKEND_PROXY_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
