// oa5: one Today page (Home + Swing Picks). What it shows, for whom, and the wording rules: the model score is never
// shown with a % (only the calibrated chance may be), every signal says "Experimental, unproven", and the cards show
// signal, score, entry/exit, risk and explanation.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { ApiError } from '../../api/client'
import type { BrainDecision, BrainRun } from '../../api/types'
import { BANNED_CLAIMS } from '../beginner/cardText'
import { finalWord, ideasFrom } from '../live'
import { ideaCounts } from '../today/TodayIdeas'
import Today from './Today'

let nextId = 1
const dec = (symbol: string, word: string, confidence: number | null, over: Partial<BrainDecision> = {}): BrainDecision =>
  ({
    id: nextId++, run_id: 'r1', symbol, kind: 'idea', word, reasons: [`${symbol} reason`], entry_low: 100,
    entry_high: 102, target: 108, stop: 96, qty: word === 'TRADE' ? 10 : 0, horizon_days: 15, confidence,
    honest_score: null, evidence_text: null, downgraded_from: null, downgrade_reason: null, overruled_word: null,
    overrule_reason: null, overruled_by: null, overruled_at: null, ...over,
  }) as BrainDecision

const run = {
  run_id: 'r1', kind: 'nightly', as_of: '2026-10-22', live: true, ms: 1, error: null, counts: {}, status: 'done',
  started_at: '2026-10-22T13:20:00Z', banner: { mode: 'NORMAL', headline: 'Steady.' }, book: 'bot', modules: {},
  quality: { overall: null, stale: [] }, sectors: [], situations: [], portfolio: {},
  decisions: [
    dec('AAATRADE', 'TRADE', 0.81, { reasons: ['The model scores this stock 81% against a buy level of 60%.'] }),
    dec('BBBWATCH', 'WATCH', 0.66),
    dec('CCCWAIT', 'WAIT', 0.4),
    dec('DDDAVOID', 'AVOID', 0.2),
    dec('EEECAL', 'WATCH', 0.55, { honest_score: { status: 'measured', honest_chance: 0.12 } as BrainDecision['honest_score'] }),
    dec('FFFOVER', 'TRADE', 0.7, { overruled_word: 'AVOID', overrule_reason: 'Too risky' }),
    dec('GGGEXTRA', 'WAIT', 0.3),
    dec('HELDOK', 'HOLD', 0.5, { kind: 'holding' }),
    dec('HELDBAD', 'EXIT', 0.2, { kind: 'holding', reasons: ['Scored 20% and fell below its stop.'] }),
  ],
} as unknown as BrainRun

type Seed = Record<string, unknown>
function render(opts: { owner?: boolean; run?: BrainRun | null; seed?: Seed; errors?: string[]; path?: string } = {}): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (opts.run !== null) client.setQueryData(['brainLatest', 'nightly'], opts.run ?? run)
  client.setQueryData(['plan'], { unrestricted: !!opts.owner, can_manage_plans: !!opts.owner, can_see_real_account: false, features: ['trademind'] })
  for (const [k, v] of Object.entries(opts.seed ?? {})) client.setQueryData(JSON.parse(k), v)
  return renderToString(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[opts.path ?? '/trademind']}>
        <Today owner={opts.owner} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const text = (html: string) =>
  html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/&#x27;|&apos;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/\s+/g, ' ')

/** Each recommendation card's own HTML: from its marker to the start of the next card or the end of the card list. */
function cards(html: string): string[] {
  const list = html.slice(html.indexOf('data-testid="top-ideas"'), html.indexOf('id="picks"'))
  return list.split('data-card="idea"').slice(1)
}
const symbols = (html: string) => [...html.matchAll(/data-card="idea" data-symbol="([^"]+)"/g)].map((m) => m[1])

const OWNER_SEED: Seed = {
  '["safetyState"]': { new_entries_enabled: true, exits_enabled: true, halt_reason: null, halted_at: null, halted_by: null },
  '["brainStage"]': { stage: 'shadow', plain: 'Practice only: the brain records ideas but buys nothing.', finished: 1, needed: 30, ready: false, history: [] },
  '["riskLimits"]': { max_drawdown_pct: 0.15 },
  '["equityCurve",400]': [{ date: '2026-10-22', total_value: 1, cash: 1, holdings_value: 0, day_pnl: 0, drawdown_pct: 0.03, open_positions: 0 }],
  '["brainApprovals"]': [
    { id: 1, symbol: 'WAITOK', decision_day: '2026-10-22', price: 1234.5, stop_loss: 1185, take_profit: 1333, suggested_qty: 3, reason: 'r', status: 'pending', status_plain: 'Waiting', decided_by: null, decided_at: null, decided_note: null, position_id: null, result_note: null, created_at: null, valid_until: null },
    { id: 2, symbol: 'ALREADYDONE', decision_day: '2026-10-21', price: 10, stop_loss: null, take_profit: null, suggested_qty: null, reason: 'r', status: 'approved', status_plain: 'Approved', decided_by: 'owner', decided_at: null, decided_note: null, position_id: null, result_note: null, created_at: null, valid_until: null },
  ],
  '["brainProposals"]': [
    { id: 7, kind: 'buy_level', title: 'Raise the buy level to 65%', evidence: 'e', change: {}, status: 'open', created_at: '2026-10-01', decided_by: null, decided_at: null, decided_note: null },
    { id: 8, kind: 'buy_level', title: 'Sealed during the blind trial', evidence: 'e', change: {}, status: 'open', sealed: true, created_at: '2026-10-15', decided_by: null, decided_at: null, decided_note: null },
    { id: 9, kind: 'buy_level', title: 'Old one', evidence: 'e', change: {}, status: 'dismissed', created_at: '2026-09-01', decided_by: 'owner', decided_at: null, decided_note: null },
  ],
}

describe('Today: top 5 cards with the horizon selector', () => {
  const html = render()

  it('shows the brain\'s first five ideas, in its order, with the one card', () => {
    expect(symbols(html.slice(0, html.indexOf('id="picks"')))).toEqual(ideasFrom(run).map((d) => d.symbol).slice(0, 5))
  })

  it('offers the five horizons on the ideas and on the pick list, 15 days chosen in both', () => {
    expect(html.match(/data-horizon="/g)?.length).toBe(10)
    expect(html.match(/aria-selected="true"[^>]*data-horizon="15d"/g)?.length).toBe(2)
    expect(text(html)).not.toMatch(/\bValidated\b/)
  })

  it('every card shows signal, score, entry/exit, risk, explanation and "Experimental, unproven"', () => {
    const cs = cards(html)
    expect(cs.length).toBe(5)
    for (const c of cs) {
      expect(c).toMatch(/tm-tag/) // the signal word
      for (const part of ['score', 'plan', 'risk', 'reasons', 'model-status']) expect(c).toContain(`data-part="${part}"`)
      expect(text(c)).toContain('Experimental, unproven')
    }
    expect(text(cs[0]!)).toContain('Buy zone')
    expect(text(cs[0]!)).toContain('Stop')
  })

  it('never shows the model score with a %; only the calibrated idea shows a % chance', () => {
    for (const c of cards(html)) {
      if (c.includes('EEECAL')) expect(text(c)).toContain('~12%')
      else expect(text(c)).not.toMatch(/\d\s*%/)
    }
    // The brain's own sentence, in the card and the pick detail, loses its % signs.
    expect(text(html)).toContain('The model scores this stock 81 against a buy level of 60.')
    expect(text(html)).not.toContain('81%')
    expect(text(html)).not.toMatch(BANNED_CLAIMS)
  })

  it('the idea counts are the same counts Home showed (owner overrule wins)', () => {
    const c = ideaCounts(run)
    const homeCounts = { TRADE: 0, WATCH: 0, WAIT: 0, AVOID: 0 } as Record<string, number>
    for (const d of ideasFrom(run)) homeCounts[finalWord(d)] = (homeCounts[finalWord(d)] ?? 0) + 1
    expect(c).toEqual(homeCounts)
    expect(c).toEqual({ TRADE: 1, WATCH: 2, WAIT: 2, AVOID: 2 })
  })

  it('every pick in the list says "Experimental, unproven" too', () => {
    const table = html.slice(html.indexOf('data-feature="pick-table"'))
    const rows = table.split('data-pick="').slice(1)
    expect(rows.length).toBeGreaterThan(0)
    for (const r of rows) expect(text(r.slice(0, r.indexOf('</tr>')))).toContain('Experimental, unproven')
  })

  it('has no real-money figure or button', () => {
    expect(text(html)).not.toMatch(/My Zerodha|real money|real order/i)
  })
})

describe('Today on a horizon with no strategy', () => {
  it('shows that no idea exists for it, never the 15-day cards under its name', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    client.setQueryData(['brainLatest', 'nightly'], run)
    const html = renderToString(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Today initialHorizon="30d" />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(html).not.toContain('data-card="idea"')
    expect(text(html)).toContain('No supported trading strategy for 30 Days')
    expect(html).not.toContain('<table')
  })
})

describe('Today: status strip', () => {
  it('everyone sees the market mode and the banner', () => {
    for (const owner of [true, false]) {
      const t = text(render({ owner, seed: OWNER_SEED }))
      expect(t).toContain('Market Mode')
      expect(t).toContain('Steady.')
    }
  })

  it('the owner sees new buys, drawdown against the halt level, and the stage, each linking to its page', () => {
    const html = render({ owner: true, seed: OWNER_SEED })
    const t = text(html)
    expect(t).toContain('New buys Allowed')
    expect(t).toContain('3.0% below its peak')
    expect(t).toContain('New buys stop at 15%')
    expect(t).toContain('Trading stage Practice')
    for (const to of ['/trademind/control', '/trademind/risk', '/trademind/golive']) expect(html).toContain(`href="${to}"`)
  })

  it('a kill switch that is on says paused, and why', () => {
    const seed = { ...OWNER_SEED, '["safetyState"]': { new_entries_enabled: false, exits_enabled: true, halt_reason: 'Checking a data problem', halted_at: null, halted_by: 'owner' } }
    expect(text(render({ owner: true, seed }))).toContain('Paused by the kill switch Reason: Checking a data problem, by owner.')
  })

  it('a non-owner sees no safety switch, stage or drawdown', () => {
    const t = text(render({ owner: false, seed: OWNER_SEED }))
    for (const w of ['New buys', 'Drawdown', 'Trading stage', 'kill switch']) expect(t).not.toContain(w)
    expect(t).toContain('everything here is paper trading')
  })
})

describe('Today: needs you', () => {
  it('lists the flagged holdings (Paper), not the fine ones, with the % taken off the score', () => {
    const html = render()
    const t = text(html)
    expect(t).toContain('Holdings Needing Attention')
    expect(t).toContain('HELDBAD')
    expect(t).toContain('Scored 20 and fell below its stop.')
    const holdings = html.slice(html.indexOf('data-feature="holdings-attention"'), html.indexOf('data-feature="holdings-attention"') + 2000)
    expect(holdings).not.toContain('HELDOK')
  })

  it('the owner sees the ideas waiting for an OK and the open proposals, and that sealed ones cannot be decided', () => {
    const html = render({ owner: true, seed: OWNER_SEED })
    const t = text(html)
    expect(html).toContain('data-approval="WAITOK"')
    expect(html).not.toContain('data-approval="ALREADYDONE"')
    expect(t).toContain('Paper buy at about ₹1,234.50')
    expect(t).toContain('Raise the buy level to 65')
    expect(t).not.toContain('65%')
    expect(html).not.toContain('data-proposal="9"')
    expect(t).toContain('1 proposal is sealed until the blind trial ends, so it cannot be decided yet.')
    expect(html).toContain('href="/trademind/learn"')
  })

  it('nothing on Today decides anything: no approve, reject or accept button', () => {
    const t = text(render({ owner: true, seed: OWNER_SEED }))
    expect(t).not.toMatch(/\b(Approve|Reject|Accept|Dismiss)\b/)
  })

  it('a non-owner gets no approvals or proposals', () => {
    const html = render({ owner: false, seed: OWNER_SEED })
    expect(html).not.toContain('WAITOK')
    expect(text(html)).not.toContain('Waiting for your decision')
  })
})

describe('Today with no brain run', () => {
  it('still shows the status strip and needs you, and says the brain has not run yet', async () => {
    // retryOnMount off: a server render would otherwise show the failed query as loading again.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, retryOnMount: false } } })
    client.setQueryData(['brainHealth'], { ok: true })
    for (const [k, v] of Object.entries(OWNER_SEED)) client.setQueryData(JSON.parse(k), v)
    // A 404 on the latest run with the brain switched on = "no run yet".
    await client.prefetchQuery({ queryKey: ['brainLatest', 'nightly'], queryFn: () => Promise.reject(new ApiError('none', 404)) })
    const html = renderToString(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Today owner />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(html).toContain('data-testid="status-strip"')
    expect(html).toContain('data-testid="needs-you"')
    expect(html).toContain('data-feature="kill-switch"')
    expect(html).not.toContain('data-card="idea"')
    expect(text(html)).toContain('No run yet')
  })
})

describe('/trademind/dashboard', () => {
  it('opens Today at the pick list', () => {
    const html = renderToString(
      <QueryClientProvider client={(() => { const c = new QueryClient(); c.setQueryData(['brainLatest', 'nightly'], run); return c })()}>
        <MemoryRouter initialEntries={['/trademind/dashboard']}>
          <Today focus="picks" />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(html).toContain('data-focus="picks"')
    expect(html).toContain('id="picks"')
  })
})
