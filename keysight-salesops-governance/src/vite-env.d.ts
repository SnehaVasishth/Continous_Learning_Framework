/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly BASE_URL: string;
  readonly VITE_SALESOPS_API_URL?: string;
  readonly VITE_SALESOPS_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
