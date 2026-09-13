import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import path from 'node:path'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      // Update on reload rather than autoUpdate: a trading dashboard should
      // never swap its running JS out from under a mid-session user: they
      // get the new version next time they open the app, not mid-click.
      registerType: 'prompt',
      includeAssets: ['favicon-32.png', 'apple-touch-icon.png'],
      manifest: {
        name: 'Swing Trade ML',
        short_name: 'SwingML',
        description: 'Daily buy/hold/sell suggestions and position tracking.',
        theme_color: '#0b1120',
        background_color: '#0b1120',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        icons: [
          { src: '/pwa-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/pwa-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/pwa-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
    }),
  ],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    // 0.0.0.0 so the dev server is reachable when it runs inside the container
    host: '0.0.0.0',
    port: 5173,
    // Vite's dev server rejects requests for any Host header not listed here
    // (DNS-rebinding protection) — the nginx reverse proxy forwards the
    // original Host, so the public domain and droplet IP both need to be
    // allowed alongside the usual local ones.
    allowedHosts: ['localhost', '127.0.0.1', '147.182.176.105', 'swingtrademl.com', 'www.swingtrademl.com'],
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
