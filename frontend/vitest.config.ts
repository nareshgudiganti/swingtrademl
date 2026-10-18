import { defineConfig } from 'vitest/config'

// Kept apart from vite.config.ts so tests do not load the PWA plugin.
export default defineConfig({
  test: {
    environment: 'node',
    setupFiles: ['src/test-setup.ts'],
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx', 'scripts/**/*.test.mjs'],
  },
})
