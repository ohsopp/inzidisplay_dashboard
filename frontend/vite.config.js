import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',  // SSH/원격에서 접속 가능 (기본값 127.0.0.1은 로컬만)
    port: 6173,
    proxy: {
      '/socket.io': {
        target: 'http://localhost:6005',
        ws: true,
      },
    },
  },
})
