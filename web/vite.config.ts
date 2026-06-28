import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Proxy API to the backend so the SPA can use same-origin /v0 paths in dev.
    proxy: {
      '/v0': 'http://127.0.0.1:8009',
      '/health': 'http://127.0.0.1:8009',
    },
  },
})
