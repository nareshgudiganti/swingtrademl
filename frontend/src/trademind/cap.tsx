import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'

export type CapTier = 'large' | 'midcap' | 'smallcap'

const LABEL: Record<CapTier, string> = {
  large: 'Large',
  midcap: 'Mid',
  smallcap: 'Small',
}

const HINT: Record<CapTier, string> = {
  large: 'Large company — bigger and steadier',
  midcap: 'Mid-sized company',
  smallcap: 'Small company — moves more',
}

/** Same rule as backend strategies/tier.py: the model name says the size. */
export function capTierFromModel(modelName: unknown): CapTier | null {
  if (typeof modelName !== 'string' || modelName === '') return null
  if (modelName.endsWith('_smallcap')) return 'smallcap'
  if (modelName.endsWith('_midcap')) return 'midcap'
  if (modelName === 'swing_classifier') return 'large'
  return null
}

/** Which company-size list each symbol sits on (large / mid / small models). */
export function useSymbolCaps() {
  const strategies = useQuery({
    queryKey: ['strategies'],
    queryFn: api.strategies,
    staleTime: 5 * 60_000,
  })

  const caps = useMemo(() => {
    const map = new Map<string, CapTier>()
    const rank: Record<CapTier, number> = { large: 1, midcap: 2, smallcap: 3 }
    for (const strategy of strategies.data ?? []) {
      const tier = capTierFromModel(strategy.params?.model_name)
      if (!tier) continue
      for (const symbol of strategy.symbols ?? []) {
        const key = symbol.toUpperCase()
        const prev = map.get(key)
        if (!prev || rank[tier] > rank[prev]) map.set(key, tier)
      }
    }
    return map
  }, [strategies.data])

  return caps
}

export function CapFlag({ tier, gap = false }: { tier?: string | null; gap?: boolean }) {
  if (tier !== 'large' && tier !== 'midcap' && tier !== 'smallcap') return null
  return (
    <span className={`tm-cap tm-cap-${tier}`} title={HINT[tier]} style={gap ? { marginLeft: '0.4rem' } : undefined}>
      {LABEL[tier]}
    </span>
  )
}
