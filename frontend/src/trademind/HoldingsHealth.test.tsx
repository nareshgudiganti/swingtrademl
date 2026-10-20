import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { HoldingsHealth } from '../api/types'
import { HealthCheckView, healthBooks } from './HoldingsHealth'

const base: HoldingsHealth = {
  book: 'bot',
  book_label: 'Bot (Paper)',
  is_real_money: false,
  account_value: 1_000_000,
  account_value_basis: "The bot's account: shares held plus cash left",
  holdings_checked: 2,
  rules: ['At most 25% of the account in one sector', 'Stop-loss 4% below the price paid'],
  results_checked: true,
  notes: [],
  issues: [],
  checked_at: '2026-10-20T10:00:00+05:30',
}

describe('HealthCheckView', () => {
  it('lists each issue in plain words, with the detail behind a tap', () => {
    const html = renderToString(
      <HealthCheckView
        data={{
          ...base,
          issues: [
            { kind: 'no_stop', symbols: ['TCS'], title: 'TCS has no stop-loss.', detail: 'Nothing will sell TCS automatically.' },
            { kind: 'sector_too_big', symbols: ['TCS', 'INFY'], title: 'Too much money is in IT.', detail: 'IT is 31% of this account.' },
          ],
        }}
      />,
    )
    expect(html).toContain('TCS has no stop-loss.')
    expect(html).toContain('Too much money is in IT.')
    expect(html).toContain('<details')
    expect(html).toContain('IT is 31% of this account.')
    expect(html).toContain('2 things to look at')
    expect(html).toContain('Bot (Paper)')
  })

  it('says all clear when nothing breaks a rule, and shows the rules it checked', () => {
    const html = renderToString(<HealthCheckView data={base} />)
    expect(html).toContain('All clear')
    expect(html).toContain('At most 25% of the account in one sector')
  })

  it('an empty book is an empty state, not all clear', () => {
    const html = renderToString(<HealthCheckView data={{ ...base, holdings_checked: 0 }} />)
    expect(html).toContain('data-state="empty"')
    expect(html).not.toContain('All clear')
  })

  it('says when results days could not be checked', () => {
    const html = renderToString(
      <HealthCheckView
        data={{ ...base, results_checked: false, notes: ['The company results calendar has not loaded, so results days were not checked.'] }}
      />,
    )
    expect(html).toContain('results days were not checked')
  })

  it('marks the real book as real money', () => {
    const html = renderToString(<HealthCheckView data={{ ...base, book: 'real', book_label: 'My Zerodha (Real)', is_real_money: true }} />)
    expect(html).toContain('Real money')
  })
})

describe('healthBooks', () => {
  it('shows the real book only to real-account users, and Testing only when it is on', () => {
    expect(healthBooks({ isOwner: true, testingOn: true, realAccount: true })).toEqual(['bot', 'tester', 'real'])
    expect(healthBooks({ isOwner: true, testingOn: false, realAccount: false })).toEqual(['bot'])
    expect(healthBooks({ isOwner: false, testingOn: true, realAccount: false })).toEqual(['bot'])
  })
})
