// Manual test (tr3, owner 2026-10-25): the one place to make a hand-picked practice buy. Idea cards no longer
// carry a Buy button, so a practice buy is never mistaken for a brain pick. Owner or tester only: the menu
// hides it from everyone else and the server refuses anyone else (POST /portfolio/tester/buy).
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/client'
import { CapFlag, useSymbolCaps } from '../cap'
import { Card, inr } from '../ui'

export const MANUAL_TEST_LINE = 'Practice money only. This is your own test, not a brain pick.'

export default function ManualTest() {
  const queryClient = useQueryClient()
  const caps = useSymbolCaps()
  const [symbol, setSymbol] = useState('')
  const [qty, setQty] = useState('1')
  const [debounced, setDebounced] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setDebounced(symbol.trim()), 250)
    return () => clearTimeout(t)
  }, [symbol])
  const search = useQuery({
    queryKey: ['bx-stock-search', debounced],
    queryFn: () => api.instruments(debounced),
    enabled: debounced.length >= 2,
    retry: false,
  })

  const picked = symbol.trim().toUpperCase()
  const tier = caps.get(picked)
  const buy = useMutation({
    mutationFn: () => api.testerPaperBuy({ symbol: picked, quantity: Number(qty), cap_tier: tier ?? 'large' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['testerPositions'] })
      queryClient.invalidateQueries({ queryKey: ['testerSummary'] })
    },
  })

  return (
    <div className="tm-page tm-grid">
      <Card glow title="Manual test" sub="Pick a stock and how many shares, then make a practice buy.">
        <p className="tm-note" data-testid="manual-test-line" style={{ marginTop: 0 }}>
          {MANUAL_TEST_LINE}
        </p>
        <form
          className="tm-flex tm-wrap"
          style={{ gap: '0.5rem', alignItems: 'center' }}
          onSubmit={(e) => {
            e.preventDefault()
            buy.mutate()
          }}
        >
          <input
            className="tm-input"
            list="manual-test-stocks"
            placeholder="Stock, e.g. INFY"
            aria-label="Stock"
            value={symbol}
            onChange={(e) => {
              setSymbol(e.target.value)
              buy.reset()
            }}
          />
          <datalist id="manual-test-stocks">
            {(search.data ?? []).map((s) => (
              <option key={s.tradingsymbol} value={s.tradingsymbol}>
                {s.name ?? s.tradingsymbol}
              </option>
            ))}
          </datalist>
          <CapFlag tier={tier} />
          <input
            className="tm-input"
            type="number"
            min={1}
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            aria-label="Quantity"
            style={{ width: 90 }}
          />
          <button className="tm-btn" type="submit" disabled={!picked || !(Number(qty) > 0) || buy.isPending}>
            {buy.isPending ? 'Buying…' : 'Paper buy'}
          </button>
        </form>
        {buy.isError && <p className="tm-neg">{(buy.error as Error).message}</p>}
        {buy.isSuccess && (
          <p className="tm-pos" style={{ marginTop: '0.6rem' }}>
            Practice buy placed: {buy.data.quantity} × {buy.data.symbol} at about ₹{inr(buy.data.entry_price)}. It is in
            the Testing book, kept apart from the bot&apos;s trades.
          </p>
        )}
      </Card>
    </div>
  )
}
