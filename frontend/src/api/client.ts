// Thin fetch wrapper around the FastAPI backend.

import type {
  CurrentUser,
  DetailedPosition,
  EquityPoint,
  Instrument,
  LatestSignal,
  MLModel,
  MessageResponse,
  PortfolioSummary,
  Prediction,
  PredictionRun,
  ScanResult,
  Strategy,
  StrategyType,
  SystemStatus,
  Trade,
} from './types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

// The dashboard authenticates as a real user: POST /auth/login or /auth/signup
// returns a JWT, which is what every subsequent request carries as a bearer
// token. (The backend also accepts a shared X-API-Key as an alternative, but
// that path exists for scripts/automation — the dashboard never uses it.)
const TOKEN_STORAGE = 'stml.token'

export function getToken(): string {
  return localStorage.getItem(TOKEN_STORAGE) ?? ''
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE, token.trim())
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_STORAGE)
}

/**
 * Google sign-in redirects the whole browser back to this app's own URL with
 * `?token=...` attached (see the backend's /auth/google/callback). Called
 * once on startup, before anything renders, so a fresh Google login is picked
 * up and the token never lingers visibly in the address bar.
 */
export function captureTokenFromRedirect(): boolean {
  const url = new URL(window.location.href)
  const token = url.searchParams.get('token')
  if (!token) return false

  setToken(token)
  url.searchParams.delete('token')
  window.history.replaceState({}, '', url.toString())
  return true
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  })

  if (!response.ok) {
    // A 401 on an authenticated request means the token expired or was
    // revoked — drop it so the app falls back to the login screen instead of
    // looping on the same failing request.
    if (response.status === 401 && token) {
      clearToken()
    }

    // FastAPI returns {detail: ...}; fall back to the status line when the
    // body is empty or not JSON (a proxy error page, for instance).
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* keep statusText */
    }
    throw new ApiError(detail, response.status)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

const get = <T>(path: string) => request<T>(path)
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined })
const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'PUT', body: JSON.stringify(body) })
const del = <T>(path: string) => request<T>(path, { method: 'DELETE' })

/** Full-page navigation, not a fetch: Google's consent screen must be a real
 * browser redirect, and the backend replies with one too. */
export function googleLoginUrl(): string {
  return `${BASE_URL}/auth/google/login`
}

export const api = {
  // ------------------------------------------------------------- system --
  status: () => get<SystemStatus>('/status'),
  health: () => get<{ status: string; version: string }>('/health'),

  // -------------------------------------------------------------- auth --
  login: (username: string, password: string) =>
    post<{ access_token: string }>('/auth/login', { username, password }),
  signup: (username: string, password: string, email?: string) =>
    post<{ access_token: string }>('/auth/signup', { username, password, email }),
  me: () => get<CurrentUser>('/auth/me'),

  // ---------------------------------------------------------- portfolio --
  summary: (mode?: string) =>
    get<PortfolioSummary>(`/portfolio/summary${mode ? `?mode=${mode}` : ''}`),
  positions: () => get<DetailedPosition[]>('/portfolio/positions/detailed'),
  closePosition: (id: number, reason = 'MANUAL') =>
    post<MessageResponse>(`/portfolio/positions/${id}/close`, { reason }),
  trades: (limit = 100) => get<Trade[]>(`/portfolio/trades?limit=${limit}`),
  equityCurve: (days = 180) => get<EquityPoint[]>(`/portfolio/equity-curve?days=${days}`),
  snapshot: () => post<MessageResponse>('/portfolio/snapshot'),

  // ------------------------------------------------------------ signals --
  latestSignals: (limit = 20) => get<LatestSignal[]>(`/signals/latest?limit=${limit}`),

  // --------------------------------------------------------- strategies --
  strategies: () => get<Strategy[]>('/strategies'),
  strategyTypes: () => get<StrategyType[]>('/strategies/types'),
  createStrategy: (body: Partial<Strategy>) => post<Strategy>('/strategies', body),
  updateStrategy: (id: number, body: Partial<Strategy>) =>
    patch<Strategy>(`/strategies/${id}`, body),
  deleteStrategy: (id: number) => del<MessageResponse>(`/strategies/${id}`),
  activateStrategy: (id: number) => post<Strategy>(`/strategies/${id}/activate`),
  deactivateStrategy: (id: number) => post<Strategy>(`/strategies/${id}/deactivate`),
  scanAll: () => post<ScanResult>('/strategies/scan-all'),

  // ---------------------------------------------------------------- ml --
  models: () => get<MLModel[]>('/ml/models'),
  activateModel: (id: number) => post<MLModel>(`/ml/models/${id}/activate`),
  train: (body: Record<string, unknown>) => post<MessageResponse>('/ml/train', body),
  predictionAccuracy: () =>
    get<{ evaluated_predictions: number; correct: number; accuracy: number }>(
      '/ml/predictions/accuracy',
    ),
  // Scores the whole watchlist now, ranked by probability — the "what should
  // I focus on" view. persist=true also feeds the accuracy metric above.
  predict: (persist = true) => post<PredictionRun[]>(`/ml/predict?persist=${persist}`),
  // The history behind the accuracy stat: every prediction the bot has ever
  // made, symbol-resolved, with the outcome once its horizon has elapsed.
  predictions: (limit = 100) => get<Prediction[]>(`/ml/predictions?limit=${limit}`),

  // -------------------------------------------------------- instruments --
  watchlist: () => get<Instrument[]>('/instruments/watchlist'),
  setWatchlist: (symbols: string[]) => put<Instrument[]>('/instruments/watchlist', { symbols }),
  syncInstruments: () => post<MessageResponse>('/instruments/sync'),
  instruments: (search: string, limit = 8) =>
    get<Instrument[]>(`/instruments?search=${encodeURIComponent(search)}&limit=${limit}`),

  // -------------------------------------------------------- market data --
  backfill: (body: Record<string, unknown>) => post<MessageResponse>('/market-data/backfill', body),
  coverage: () =>
    get<{ symbol: string; candles: number; from: string | null; to: string | null }[]>(
      '/market-data/coverage',
    ),

  // ------------------------------------------------------ notifications --
  telegramStatus: () =>
    get<{ ok: boolean; bot: string | null; error: string | null }>('/notifications/telegram/status'),
  telegramTest: () => post<MessageResponse>('/notifications/telegram/test'),
}
