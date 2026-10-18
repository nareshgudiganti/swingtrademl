// Browser tests (qa1) and accessibility checks (qa10). See docs/QUALITY-CHECKS.md.
//
// The app is built once and served by `vite preview`; every /api/v1 call is answered by e2e/support/mockApi.ts,
// so no backend, database or Kite login is ever needed, and nothing can reach production.
import { defineConfig, devices } from '@playwright/test'

const PORT = 4174

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  // The repo is public: keep the plain list output only. No traces, screenshots or videos are saved.
  reporter: 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
    // The PWA service worker would answer requests itself, out of reach of the fake backend.
    serviceWorkers: 'block',
    timezoneId: 'Asia/Kolkata',
    locale: 'en-IN',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    // Same-origin API base, so the fake backend sees every call. Built into its own folder so the
    // normal dist/ is never overwritten.
    command: `npx vite build --outDir dist-e2e --emptyOutDir && npx vite preview --outDir dist-e2e --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    env: { VITE_API_BASE_URL: '/api/v1' },
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
})
