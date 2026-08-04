// Thin fetch wrapper around the FastAPI backend.

import type {
  DetailedPosition,
  EquityPoint,
  Instrument,
  LatestSignal,
  MLModel,
  MessageResponse,
  PortfolioSummary,
  ScanResult,
  Strategy,
  StrategyType,
  SystemStatus,
  Trade,
} from './types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

// The backend guards protected routes with a shared X-API-Key. Storing it in
// localStorage is acceptable for a single-operator dashboard on localhost; it
// must be replaced with the JWT flow (POST /auth/login) before this is exposed
// on any public address.
const API_KEY_STORAGE = 'stml.apiKey'

export function getApiKey(): string {
  return localStorage.getItem(API_KEY_STORAGE) ?? ''
}

export function setApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE, key.trim())
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
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': getApiKey(),
      ...init?.headers,
    },
  })

  if (!response.ok) {
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

export const api = {
  // ------------------------------------------------------------- system --
  status: () => get<SystemStatus>('/status'),
  health: () => get<{ status: string; version: string }>('/health'),

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

  // -------------------------------------------------------- instruments --
  watchlist: () => get<Instrument[]>('/instruments/watchlist'),
  setWatchlist: (symbols: string[]) => put<Instrument[]>('/instruments/watchlist', { symbols }),
  syncInstruments: () => post<MessageResponse>('/instruments/sync'),

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
