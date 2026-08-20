/// <reference types="vite/client" />

interface Window {
  __AVOCADO_CONFIG__?: {
    apiBaseUrl?: string
  }
}

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
