// The "Company and news" tab (full-analysis page) and its one-line teaser (stock page). Display only: it shows
// what the company itself filed, each block with its source and date, and says "Not available" or "Out of date"
// instead of guessing. It never changes the brain's call and uses no buy or sell words.

import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { CompanyBlock, CompanyView } from '../api/types'

export function useCompany(symbol: string) {
  return useQuery({ queryKey: ['company', symbol], queryFn: () => api.company(symbol), retry: false })
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-10-22" or an ISO time -> "22 Oct 2026" (the date part as given, never shifted by time zone). */
export function shortDate(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}` : ''
}

function Stamp({ block }: { block: CompanyBlock }) {
  if (block.state === 'not_available') return <span className="sp-small">Not available</span>
  return (
    <span className="sp-small" data-state={block.state}>
      {block.source} · as of {shortDate(block.as_of)}
      {block.state === 'out_of_date' && <b className="sp-neg"> · Out of date</b>}
    </span>
  )
}

function Card({ title, block, testid, children }: { title: string; block: CompanyBlock; testid: string; children?: React.ReactNode }) {
  return (
    <section className="sp-card sp-stack" aria-label={title} data-testid={testid} data-state={block.state}>
      <h3 className="sp-h3">{title}</h3>
      {children}
      <Stamp block={block} />
    </section>
  )
}

export function CompanyTab({ symbol }: { symbol: string }) {
  const q = useCompany(symbol)
  if (q.isLoading) return <p className="sp-small">Loading…</p>
  if (q.isError || !q.data) return <p className="sp-small" data-testid="company-error">The company information could not be loaded right now.</p>
  const c: CompanyView = q.data
  const ok = (b: CompanyBlock) => b.state !== 'not_available' && b.text
  return (
    <div className="sp-stack" data-testid="company-tab">
      <section className="sp-card sp-stack" data-testid="company-headline">
        <span className="sp-label">Company check</span>
        <p className="sp-bigtext" style={{ fontSize: 17 }}>
          {c.headline ?? 'There is not enough filed information to summarise this company yet.'}
        </p>
        <p className="sp-small">{c.note}</p>
      </section>

      <div className="sp-grid3">
        <Card title="Where is the price now?" block={c.price_position} testid="company-price">
          <p className="sp-bigtext">{ok(c.price_position) ? c.price_position.text : 'Not available.'}</p>
        </Card>
        <Card title="Who owns the company?" block={c.ownership} testid="company-owners">
          <p className="sp-bigtext">{ok(c.ownership) ? c.ownership.text : 'Not available.'}</p>
        </Card>
        <Card title="How is the business doing?" block={c.results} testid="company-results">
          <p className="sp-bigtext">Not available yet.</p>
          {c.results.why && <p className="sp-small">{c.results.why}</p>}
        </Card>
      </div>

      <Card title="What did the company announce?" block={c.announcements} testid="company-announcements">
        {c.announcements.items.length === 0 ? (
          <p className="sp-bigtext">Not available.</p>
        ) : (
          <ul className="sp-stack" style={{ margin: 0, padding: 0, listStyle: 'none', gap: 10 }}>
            {c.announcements.items.map((a) => (
              <li key={`${a.at}-${a.category}`}>
                <b>{shortDate(a.at)}</b> · {a.category}
                {a.summary && <div className="sp-small">{a.summary}</div>}
                {a.attachment_url && (
                  <a className="sp-small" href={a.attachment_url} target="_blank" rel="noopener noreferrer">
                    Open the filing ›
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="sp-grid3" data-testid="company-soon">
        {c.coming_soon.map((t) => (
          <section key={t} className="sp-card sp-card-flat sp-stack" style={{ borderStyle: 'dashed' }}>
            <span className="sp-label">Coming soon</span>
            <b>{t}</b>
            <span className="sp-small">Needs a paid data source.</span>
          </section>
        ))}
      </div>
    </div>
  )
}

/** One line on the stock page above "Want the full story?", linking to the tab. Silent until there is something to say. */
export function CompanyTeaser({ symbol, to }: { symbol: string; to: string }) {
  const q = useCompany(symbol)
  const line = q.data?.headline
  if (!line) return null
  return (
    <Link className="sp-card sp-card-flat sp-q" to={to} data-testid="company-teaser" style={{ textDecoration: 'none', color: 'inherit' }}>
      <div className="sp-q-icon" style={{ background: 'var(--sp-blue-bg)', color: 'var(--sp-blue-ink)' }}>₹</div>
      <div>
        <div className="sp-label" style={{ fontSize: 12 }}>Company check</div>
        <div className="sp-q-text">{line}</div>
        <div className="sp-small">Open Company and news ›</div>
      </div>
    </Link>
  )
}
