// Holdings health check (tracker ux7): plain-English warnings about what ONE book holds — too much in one
// stock or sector, a stop-loss further than agreed, a trade past its 15-day plan, a results day coming up.
// Read-only: it never places an order or changes a stop, a size or a limit. Every rule and number comes from
// the server (services/holdings_health.py, which reads services/limits.py and the settings); nothing is
// worked out here. Books are checked one at a time and never added together; the real book is offered only
// to the accounts allowed to see it, and the server refuses it to everyone else as well.

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { HealthBook, HoldingsHealth } from '../api/types'
import { useIsOwner, usePlan } from '../lib/plan'
import { QueryState, PageState } from './PageState'
import { Term } from './term'
import { Card, CheckItem, Tabs, inr } from './ui'

const BOOK_TAB: Record<HealthBook, string> = {
  bot: 'Bot (Paper)',
  tester: 'Testing (Paper)',
  real: 'My Zerodha (Real)',
}

/** Which books this viewer may check. Pure (tested). */
export function healthBooks(opts: { isOwner: boolean; testingOn: boolean; realAccount: boolean }): HealthBook[] {
  const books: HealthBook[] = ['bot']
  if (opts.isOwner && opts.testingOn) books.push('tester')
  if (opts.realAccount) books.push('real')
  return books
}

/** The card body for one book's result. Pure rendering (tested). */
export function HealthCheckView({ data }: { data: HoldingsHealth }) {
  const count = data.issues.length
  return (
    <div className="tm-rows" data-book={data.book}>
      <p className="tm-dim" style={{ margin: 0, fontSize: '0.8rem' }}>
        Checking: <span className="tm-strong">{data.book_label}</span>
        {data.is_real_money ? ' · Real money' : ' · Practice money'} · {data.holdings_checked}{' '}
        {data.holdings_checked === 1 ? 'stock' : 'stocks'} · account ₹{inr(data.account_value, 0)}
      </p>

      {data.holdings_checked === 0 ? (
        <PageState kind="empty" reason="Nothing is held in this book, so there is nothing to check." />
      ) : count === 0 ? (
        <CheckItem tone="pos">All clear — nothing here breaks the rules below.</CheckItem>
      ) : (
        <>
          <p className="tm-strong" style={{ margin: '0.2rem 0' }}>
            {count === 1 ? '1 thing to look at' : `${count} things to look at`}
          </p>
          {data.issues.map((issue) => (
            <CheckItem key={`${issue.kind}:${issue.symbols.join(',')}`} tone="warn">
              <details>
                <summary style={{ cursor: 'pointer' }}>{issue.title}</summary>
                <span className="tm-dim" style={{ display: 'block', marginTop: '0.25rem', fontSize: '0.8rem' }}>
                  {issue.detail}
                </span>
              </details>
            </CheckItem>
          ))}
        </>
      )}

      {data.notes.map((note) => (
        <p key={note} className="tm-dim" style={{ margin: 0, fontSize: '0.75rem' }}>
          {note}
        </p>
      ))}

      <details className="tm-note" style={{ marginTop: '0.3rem' }}>
        <summary>What is checked</summary>
        <ul style={{ margin: '0.3rem 0 0', paddingLeft: '1.1rem', fontSize: '0.8rem' }}>
          {data.rules.map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
        </ul>
        <p className="tm-dim" style={{ margin: '0.3rem 0 0', fontSize: '0.75rem' }}>
          Shares are measured against: {data.account_value_basis}. These are warnings only — nothing is bought, sold
          or changed.
        </p>
      </details>
    </div>
  )
}

export function HoldingsHealthCard() {
  const { canSeeRealAccount } = usePlan()
  const { isOwner } = useIsOwner()
  const broker = useQuery({ queryKey: ['status'], queryFn: api.status })
  const books = healthBooks({
    isOwner,
    testingOn: broker.data?.paper_tester_enabled !== false,
    realAccount: canSeeRealAccount,
  })
  const [picked, setPicked] = useState<HealthBook>('bot')
  const book = books.includes(picked) ? picked : 'bot'
  const health = useQuery({ queryKey: ['holdingsHealth', book], queryFn: () => api.holdingsHealth(book) })

  return (
    <Card
      title="Holdings Health Check"
      sub={
        <>
          Problems with what is held, in plain words: too much in one stock or <Term k="sector">sector</Term>, a{' '}
          <Term k="stop_loss">stop-loss</Term> too far away, a trade past its plan, results day coming up
        </>
      }
    >
      {books.length > 1 && (
        <Tabs
          tabs={books.map((b) => BOOK_TAB[b])}
          active={BOOK_TAB[book]}
          onChange={(label) => setPicked(books.find((b) => BOOK_TAB[b] === label) ?? 'bot')}
        />
      )}
      <QueryState q={health} what="the health check">
        {(data) => <HealthCheckView data={data} />}
      </QueryState>
    </Card>
  )
}
