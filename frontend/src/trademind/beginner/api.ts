import { useQuery } from '@tanstack/react-query'

import { BASE_URL, getPreviewPlan, getToken } from '../../api/client'
import type { EventItem, StockBriefData } from './types'

/** Read-only GET. Same headers as client.ts's private authHeaders (which client.ts does not export). */
async function getJson<T>(path: string): Promise<T> {
  const token = getToken()
  const preview = getPreviewPlan()
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(preview ? { 'X-Preview-Plan': preview } : {}),
    },
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* keep statusText */
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export function useStockBrief(symbol: string) {
  return useQuery({
    queryKey: ['beginner', 'stock', symbol],
    queryFn: () => getJson<StockBriefData>(`/beginner/stock/${encodeURIComponent(symbol)}`),
    enabled: symbol.length > 0,
  })
}

export function useUpcomingEvents(scope: 'watchlist' | 'held' | 'all', symbol?: string) {
  const q = symbol ? `?symbol=${encodeURIComponent(symbol)}` : `?scope=${scope}`
  return useQuery({
    queryKey: ['beginner', 'events', scope, symbol ?? null],
    queryFn: () => getJson<EventItem[]>(`/beginner/events${q}`),
  })
}
