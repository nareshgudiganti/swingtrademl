// Tests run in Node, which has no browser storage. Screens that read the sign-in token (usePlan) need one; an
// empty in-memory store behaves like a signed-out browser, and tests seed what they need into the query cache.
import { setTradingRules } from './trademind/tradingRules'

// What GET /config/trading-rules answers today. The screens take their trading numbers from the server, so the
// tests load the same numbers; the text tests then prove the screens still say exactly what they said before.
setTradingRules({
  research: {
    version: 'hz-rules-v1',
    sha256: 'test',
    horizons: [
      { horizon: 5, target_pct: 0.02, stop_pct: 0.04, half_out_pct: null, max_sessions: 5, research_only: false },
      { horizon: 10, target_pct: 0.06, stop_pct: 0.035, half_out_pct: null, max_sessions: 10, research_only: true },
      { horizon: 15, target_pct: 0.08, stop_pct: 0.04, half_out_pct: 0.05, max_sessions: 15, research_only: true },
    ],
  },
  brain_plan: { target_pct: 0.08, stop_pct: 0.04, half_out_pct: 0.05, max_sessions: 15 },
  risk_limits: { max_drawdown_pct: 0.15 },
  trial: { start: '2026-10-14', min_sessions: 15, sessions_so_far: 0 },
  calendar: { holidays: ['2026-10-20', '2026-11-10', '2026-11-24'] },
})

if (typeof globalThis.localStorage === 'undefined') {
  const store = new Map<string, string>()
  globalThis.localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() {
      return store.size
    },
  } as Storage
}
