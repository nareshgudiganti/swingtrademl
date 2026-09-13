import type { CapacitorConfig } from '@capacitor/cli'

// The native shells bundle the built `dist/` output (see api/client.ts's
// BASE_URL) rather than pointing at a dev server, so VITE_API_BASE_URL must
// be a real reachable backend URL — localhost inside the app's WebView means
// the phone itself, not your dev machine — when you run `vite build` for a
// device/emulator install. Set it in frontend/.env.production (gitignored).
const config: CapacitorConfig = {
  appId: 'com.swingtrade.ml',
  appName: 'Swing Trade ML',
  webDir: 'dist',
  // Explicit defaults, spelled out because backend CORS_ORIGINS
  // (.env.example) must match these exactly: https://localhost on Android,
  // capacitor://localhost on iOS.
  server: {
    androidScheme: 'https',
    iosScheme: 'capacitor',
  },
}

export default config
