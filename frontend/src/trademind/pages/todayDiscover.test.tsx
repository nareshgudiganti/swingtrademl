// oa12: Today and Discover show every brain idea with the one recommendation card (beginner/IdeaCard.tsx).
// Same ideas and counts as before; every card says "Experimental, unproven"; no score is shown as a % chance
// unless calibrated; nothing claims the model is validated, proven or profitable.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { BrainDecision, BrainRun } from '../../api/types'
import { BANNED_CLAIMS } from '../beginner/cardText'
import { finalWord, ideasFrom } from '../live'
import Home from './Home'
import Opportunities from './Opportunities'

let nextId = 1
const dec = (symbol: string, word: string, confidence: number | null, over: Partial<BrainDecision> = {}): BrainDecision =>
  ({
    id: nextId++, run_id: 'r1', symbol, kind: 'idea', word, reasons: [`${symbol} reason`], entry_low: 100,
    entry_high: 102, target: 108, stop: 96, qty: word === 'TRADE' ? 10 : 0, horizon_days: 15, confidence,
    honest_score: null, evidence_text: null, downgraded_from: null, downgrade_reason: null, overruled_word: null,
    overrule_reason: null, overruled_by: null, overruled_at: null, ...over,
  }) as BrainDecision

const run = {
  run_id: 'r1', kind: 'nightly', as_of: '2026-10-21', live: true, ms: 1, error: null, counts: {}, status: 'done',
  started_at: '2026-10-21T13:20:00Z', banner: { mode: 'NORMAL', headline: null }, book: 'bot', modules: {},
  quality: { overall: null, stale: [] }, sectors: [], situations: [], portfolio: {},
  decisions: [
    dec('AAATRADE', 'TRADE', 0.81, { reasons: ['The model scores this stock 81% against a buy level of 60%.'] }),
    dec('BBBWATCH', 'WATCH', 0.66),
    dec('CCCWAIT', 'WAIT', 0.4),
    dec('DDDAVOID', 'AVOID', 0.2),
    dec('EEECAL', 'WATCH', 0.55, { honest_score: { status: 'measured', honest_chance: 0.12 } }),
    dec('FFFOVER', 'TRADE', 0.7, { overruled_word: 'AVOID', overrule_reason: 'Too risky' }),
    dec('HOLDME', 'HOLD', 0.5, { kind: 'holding' }),
  ],
} as unknown as BrainRun

function render(page: 'today' | 'discover'): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['brainLatest', 'nightly'], run)
  return renderToString(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[page === 'today' ? '/trademind' : '/trademind/opportunities']}>
        {page === 'today' ? <Home /> : <Opportunities />}
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const text = (html: string) =>
  html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/&#x27;|&apos;/g, "'").replace(/\s+/g, ' ')

/** The HTML of each card, split on the card marker. */
const cards = (html: string) => html.split('data-card="idea"').slice(1)
const symbols = (html: string) => [...html.matchAll(/data-card="idea" data-symbol="([^"]+)"/g)].map((m) => m[1])

describe.each(['today', 'discover'] as const)('oa12 card on %s', (page) => {
  const html = render(page)

  it('uses the one card for every idea it lists', () => {
    expect(cards(html).length).toBeGreaterThan(0)
    expect(html).not.toContain('<table')
  })

  it('every card says "Experimental, unproven" and has a model status line', () => {
    for (const c of cards(html)) {
      expect(text(c)).toContain('Experimental, unproven')
      expect(c).toContain('data-part="model-status"')
    }
  })

  it('no wording says validated, proven, profitable or probability', () => {
    expect(text(html)).not.toMatch(BANNED_CLAIMS)
  })

  it('no model score is shown as a %; only the calibrated idea shows a % chance', () => {
    for (const c of cards(html)) {
      const t = text(c)
      if (c.includes('EEECAL')) {
        expect(t).toContain('~12%')
      } else {
        expect(t).not.toMatch(/\d\s*%/)
      }
    }
    expect(text(html)).toContain('The model scores this stock 81 against a buy level of 60.')
    expect(text(html)).toContain('Rank 1 of 6 today by model score')
  })
})

describe('the same ideas as before', () => {
  // The order and selection come from ideasFrom(), unchanged by the card.
  const ordered = ideasFrom(run).map((d) => d.symbol)

  it('Today lists the top five ideas in the brain order', () => {
    expect(symbols(render('today'))).toEqual(ordered.slice(0, 5))
  })

  it('Discover lists every idea, then the featured one, keeps the counts and the paper Buy button', () => {
    const html = render('discover')
    const featured = ideasFrom(run).find((d) => finalWord(d) === 'TRADE')!.symbol
    expect(symbols(html)).toEqual([...ordered, featured])
    const t = text(html)
    expect(t).toContain('All (6)')
    expect(t).toContain('Trade (1)')
    expect(t).toContain('Watch (2)')
    expect(t).toContain('Wait (1)')
    expect(t).toContain('Avoid (2)')
    expect(html.match(/>Buy</g)?.length).toBe(6)
    expect(t).not.toContain('HOLDME')
  })

  it("Discover shows the overruled idea with the owner's word and no buy zone", () => {
    const c = cards(render('discover')).find((x) => x.startsWith(' data-symbol="FFFOVER"'))!
    expect(text(c)).toContain('You overruled the brain to AVOID')
    expect(text(c)).not.toContain('Buy zone')
  })
})
