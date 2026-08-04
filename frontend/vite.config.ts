import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    // 0.0.0.0 so the dev server is reachable when it runs inside the container
    host: '0.0.0.0',
    port: 5173,
    watch: {
      // Windows bind mounts do not deliver inotify events into Linux
      // containers; polling is the only thing that makes hot reload work there.
      usePolling: true,
      interval: 300,
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
