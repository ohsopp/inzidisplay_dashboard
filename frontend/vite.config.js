import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// SIMPAC react_dashboard/vite.config.js 와 동형 — Inzi Gunicorn 기본 포트 6005
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendPort = env.VITE_BACKEND_PORT || '6005'

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: 6173,
      proxy: {
        '/api': {
          target: `http://127.0.0.1:${backendPort}`,
          changeOrigin: true,
        },
        '/socket.io': {
          target: `http://127.0.0.1:${backendPort}`,
          ws: true,
        },
      },
    },
  }
})
