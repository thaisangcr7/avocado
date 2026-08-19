import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  server: {
    port: 5173,
    // Lets the browser talk to the API on the same origin in development, so
    // there is no CORS preflight on every request and cookies would work the
    // same way locally as behind a shared domain in production.
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
        // Required for the live dictation socket. Without it the proxy
        // forwards HTTP but silently drops the WebSocket upgrade, so
        // `/api/v1/voice/stream` just hangs with no error anywhere.
        ws: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
