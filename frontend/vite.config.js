import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev server proxies API/admin calls to Django so session cookies stay same-origin.
// changeOrigin: false keeps the browser's Host header, so Django's CSRF Origin check passes.
const backend = { target: process.env.BACKEND_URL || 'http://127.0.0.1:8001', changeOrigin: false }

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': backend,
      '/admin': backend,
      '/static': backend,
    },
  },
})
