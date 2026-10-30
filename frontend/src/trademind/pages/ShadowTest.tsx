// Shadow Test (owner only, read only): every ranked stock followed for up to 15 trading days, bought or not.
// It answers "do higher-ranked stocks perform better?" and changes no pick, order, size, stop or limit.
// Only FINISHED ideas count in results; a running idea is shown, never counted as a win. Under 30 completed
// ranking days the page says "too early" and nothing more. Figures come from the brain's stored runs and
// our stored daily candles (last close, not live).

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { ShadowFinished, ShadowGroup, ShadowRunning, ShadowTestView } from '../../api/types'
import { useSymbolCaps } from '../cap'
import { shortDate } from '../CompanyTab'
import { BrainGate } from '../ui'
import { SortTh, useSort } from '../sort'
import StockLink from '../StockLink'
import '../stockpage.css'

const pct = (n: number | null | undefined, digits = 1) =>
  n == null ? '—' : `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(digits)}%`
const tone = (n: number | null | undefined) => (n == null ? '' : n >= 0 ? 'sp-pos' : 'sp-neg')
const share = (part: number, whole: number) => (whole ? ` (${Math.round((part / whole) * 100)}%)` : '')

type GroupFilter = 'all' | 'Top 5' | 'Ranks 6-20' | 'Rank 21+'
type BoughtFilter = 'all' | 'yes' | 'no'
const OUTCOME_TEXT = { target: 'Reached +8%', stop: 'Hit −4% stop', timeout: 'Ran out of time (day 15)' } as const

export default function ShadowTest() {
  return (
    <BrainGate>
      <ShadowBody />
    </BrainGate>
  )
}

function ShadowBody() {
  const q = useQuery({ queryKey: ['shadow-test'], queryFn: api.shadowTest, retry: false })
  if (q.isLoading) {
    return (
      <div className="tm-page sp">
        <p className="sp-small">Loading…</p>
      </div>
    )
  }
  if (q.isError || !q.data) {
    return (
      <div className="tm-page sp" data-testid="shadow-error">
        <p className="sp-small">The Shadow Test could not be loaded right now.</p>
      </div>
    )
  }
  return <ShadowView v={q.data} />
}

export function ShadowView({ v }: { v: ShadowTestView }) {
  const [tab, setTab] = useState<'running' | 'finished'>('running')
  const [group, setGroup] = useState<GroupFilter>('all')
  const [bought, setBought] = useState<BoughtFilter>('all')
  const [search, setSearch] = useState('')
  const caps = useSymbolCaps()

  const keep = (r: { symbol: string; group: string; paper_bought: boolean }) =>
    (group === 'all' || r.group === group) &&
    (bought === 'all' || (bought === 'yes') === r.paper_bought) &&
    (!search.trim() || r.symbol.toUpperCase().includes(search.trim().toUpperCase()))
  const running = v.running.filter(keep)
  const finished = v.finished.filter(keep)
  const pctDone = Math.min(100, Math.round((v.verdict.days_done / v.verdict.days_needed) * 100))

  return (
    <div className="tm-page sp" data-page="shadow-test">
      <header className="sp-flow-head" style={{ marginBottom: 0 }}>
        <div>
          <h2 className="sp-h2" style={{ fontSize: 22 }}>
            Do higher-ranked stocks perform better?
          </h2>
          <div className="sp-sub">We follow ranked stocks for up to 15 trading days, bought or skipped.</div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <span className="sp-pill sp-pill-amber" data-testid="shadow-label">
            Tracking only
          </span>
          <span className="sp-pill" data-testid="shadow-paper" title="Everything here is paper trading">
            Paper stage · practice money
          </span>
        </div>
      </header>
      <p className="sp-small" data-testid="shadow-note">
        {v.label} Last close, not live: updated after market close ({shortDate(v.as_of)}).
      </p>

      <section className="sp-card sh-verdict" data-testid="shadow-verdict" data-state={v.verdict.state}>
        <div>
          <span className="sp-label">{v.verdict.state === 'too_early' ? 'Evidence building' : 'Ready to review'}</span>
          <div className="sp-big" style={{ fontSize: 28 }}>
            {v.verdict.headline}
          </div>
          <p>{v.verdict.detail}</p>
        </div>
        <div className="sh-days">
          <div className="sp-between" style={{ fontSize: 14 }}>
            <b>
              {v.verdict.days_done} / {v.verdict.days_needed}
            </b>
            <span>completed ranking days</span>
          </div>
          <div className="sp-meter" role="img" aria-label={`${v.verdict.days_done} of ${v.verdict.days_needed} days`}>
            <i style={{ width: `${pctDone}%`, background: 'var(--sp-green)' }} />
          </div>
          <span className="sp-small">A review checkpoint, not a pass guarantee.</span>
        </div>
      </section>

      <div className="sh-tiles" data-testid="shadow-totals">
        <Tile n={v.totals.running} k="Running" s="Currently being tracked." />
        <Tile n={v.totals.finished} k="Finished" s="Completed tracking (target, stop or day 15)." />
        <Tile
          n={v.totals.target}
          of={v.totals.finished}
          k={`Target reached${share(v.totals.target, v.totals.finished)}`}
          s="Finished ideas that hit +8%."
          tone="up"
        />
        <Tile
          n={v.totals.stop}
          of={v.totals.finished}
          k={`Stop reached${share(v.totals.stop, v.totals.finished)}`}
          s="Finished ideas that hit −4%."
          tone="down"
        />
      </div>

      <GroupsTable groups={v.groups} />

      <section className="sp-card sp-stack" aria-label="Followed stocks">
        <div className="sh-bar">
          <div className="sp-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              className="sp-tab"
              aria-selected={tab === 'running'}
              data-testid="shadow-tab-running"
              onClick={() => setTab('running')}
            >
              Running ({v.running.length})
            </button>
            <button
              type="button"
              role="tab"
              className="sp-tab"
              aria-selected={tab === 'finished'}
              data-testid="shadow-tab-finished"
              onClick={() => setTab('finished')}
            >
              Finished ({v.finished.length})
            </button>
          </div>
          <input
            className="sh-input"
            placeholder="Search stocks…"
            aria-label="Search stocks"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select className="sh-input" aria-label="Rank group" value={group} onChange={(e) => setGroup(e.target.value as GroupFilter)}>
            <option value="all">All ranks</option>
            <option value="Top 5">Top 5</option>
            <option value="Ranks 6-20">Ranks 6-20</option>
            <option value="Rank 21+">Rank 21+</option>
          </select>
          <select className="sh-input" aria-label="Paper bought" value={bought} onChange={(e) => setBought(e.target.value as BoughtFilter)}>
            <option value="all">Paper bought: any</option>
            <option value="yes">Paper bought only</option>
            <option value="no">Not bought only</option>
          </select>
        </div>
        {tab === 'running' ? <RunningTable rows={running} caps={caps} /> : <FinishedTable rows={finished} caps={caps} />}
        <p className="sp-small" data-testid="shadow-open-note">
          Open ideas do not count as completed outcomes.
        </p>
      </section>

      <section className="sp-card" aria-label="How this test works" data-testid="shadow-how">
        <h2 className="sp-h3">How this test works</h2>
        <ol className="sh-how">
          {v.how.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ol>
        <p className="sp-small">
          One active record per stock. Tracking does not change trades. The score is a ranking, not a chance of profit.
        </p>
      </section>
    </div>
  )
}

function Tile({ n, of, k, s, tone: t }: { n: number; of?: number; k: string; s: string; tone?: 'up' | 'down' }) {
  return (
    <div className="sp-card sp-stat">
      <div className={`sp-big ${t === 'up' ? 'sp-pos' : t === 'down' ? 'sp-neg' : ''}`} style={{ fontSize: 32 }}>
        {n}
        {of != null && (
          <span className="sp-small" style={{ fontSize: 16 }}>
            {' '}
            of {of}
          </span>
        )}
      </div>
      <div style={{ fontWeight: 700 }}>{k}</div>
      <div className="sp-small">{s}</div>
    </div>
  )
}

function GroupsTable({ groups }: { groups: ShadowGroup[] }) {
  return (
    <section className="sp-card sp-stack" aria-label="Does rank make a difference?" data-testid="shadow-groups">
      <div>
        <h2 className="sp-h2">Does rank make a difference?</h2>
        <div className="sp-sub">Finished ideas only, grouped by rank when first tracked. Returns are before costs.</div>
      </div>
      <div className="sp-scroll">
        <table className="sh-table">
          <thead>
            <tr>
              <th>Original rank</th>
              <th>Finished</th>
              <th>Target +8%</th>
              <th>Stop −4%</th>
              <th>Average result</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <tr key={g.group}>
                <td>
                  <b>{g.group}</b>
                </td>
                <td>{g.finished}</td>
                <td className="sp-pos">
                  {g.target} / {g.finished}
                  {share(g.target, g.finished)}
                </td>
                <td className="sp-neg">
                  {g.stop} / {g.finished}
                  {share(g.stop, g.finished)}
                </td>
                <td className={tone(g.average_pct)}>
                  <b>{pct(g.average_pct)}</b>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

const CAP_NAME: Record<string, string> = { large: 'LARGE', midcap: 'MID', smallcap: 'SMALL' }

function Stock({ symbol, caps }: { symbol: string; caps: Map<string, string> }) {
  const cap = caps.get(symbol.toUpperCase())
  return (
    <>
      <StockLink symbol={symbol} /> {cap && <span className="sp-cap">{CAP_NAME[cap]}</span>}
    </>
  )
}

function Bought({ yes }: { yes: boolean }) {
  return <span className={`sh-chip ${yes ? 'sh-yes' : ''}`}>{yes ? 'Yes' : 'No'}</span>
}

function RunningTable({ rows: unsorted, caps }: { rows: ShadowRunning[]; caps: Map<string, string> }) {
  const { sorted: rows, sorter } = useSort(unsorted, {
    stock: (r: ShadowRunning) => r.symbol,
    rank: (r: ShadowRunning) => r.rank,
    today: (r: ShadowRunning) => (r.price_not_updated ? null : r.today_pct),
    since: (r: ShadowRunning) => r.since_pct,
    day: (r: ShadowRunning) => r.day,
    bought: (r: ShadowRunning) => (r.paper_bought ? 1 : 0),
  }, { key: null }, { stock: 'asc', rank: 'asc' })
  if (rows.length === 0) {
    return (
      <p className="sp-small" data-testid="shadow-empty">
        Nothing is running for this filter.
      </p>
    )
  }
  return (
    <div className="sp-scroll">
      <table className="sh-table" data-testid="shadow-running">
        <thead>
          <tr>
            <SortTh sorter={sorter} k="stock">Stock</SortTh>
            <SortTh sorter={sorter} k="rank">Original rank</SortTh>
            <SortTh sorter={sorter} k="today">Daily change</SortTh>
            <SortTh sorter={sorter} k="since">Since ranked</SortTh>
            <th style={{ minWidth: 190 }}>Stop-to-target position</th>
            <SortTh sorter={sorter} k="day">Trading days</SortTh>
            <SortTh sorter={sorter} k="bought">Paper bought</SortTh>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol}>
              <td>
                <Stock symbol={r.symbol} caps={caps} />
              </td>
              <td>#{r.rank}</td>
              <td className={tone(r.today_pct)}>
                {r.price_not_updated ? <span className="sp-small">price not updated</span> : pct(r.today_pct)}
              </td>
              <td className={tone(r.since_pct)}>{pct(r.since_pct)}</td>
              <td>
                {r.position == null ? (
                  '—'
                ) : (
                  <div className="sh-rng" role="img" aria-label={`${pct(r.since_pct)} since ranked, between the −4% stop and the +8% target`}>
                    <i className="sh-rng-stop" />
                    <i className="sh-rng-target" />
                    <span className="sh-dot" style={{ left: `${Math.round(r.position * 100)}%` }} />
                    <small className="sh-l1">−4%</small>
                    <small className="sh-l2">0%</small>
                    <small className="sh-l3">+8%</small>
                  </div>
                )}
              </td>
              <td>{r.day} / 15</td>
              <td>
                <Bought yes={r.paper_bought} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function FinishedTable({ rows: unsorted, caps }: { rows: ShadowFinished[]; caps: Map<string, string> }) {
  const { sorted: rows, sorter } = useSort(unsorted, {
    stock: (r: ShadowFinished) => r.symbol,
    rank: (r: ShadowFinished) => r.rank,
    ranked: (r: ShadowFinished) => r.ranked_on,
    ended: (r: ShadowFinished) => r.ended_on,
    outcome: (r: ShadowFinished) => OUTCOME_TEXT[r.outcome],
    result: (r: ShadowFinished) => r.result_pct,
    took: (r: ShadowFinished) => r.days,
    bought: (r: ShadowFinished) => (r.paper_bought ? 1 : 0),
  }, { key: null }, { stock: 'asc', rank: 'asc', outcome: 'asc' })
  if (rows.length === 0) {
    return (
      <p className="sp-small" data-testid="shadow-empty">
        Nothing has finished for this filter.
      </p>
    )
  }
  return (
    <div className="sp-scroll">
      <table className="sh-table" data-testid="shadow-finished">
        <thead>
          <tr>
            <SortTh sorter={sorter} k="stock">Stock</SortTh>
            <SortTh sorter={sorter} k="rank">Original rank</SortTh>
            <SortTh sorter={sorter} k="ranked">Ranked</SortTh>
            <SortTh sorter={sorter} k="ended">Ended</SortTh>
            <SortTh sorter={sorter} k="outcome">Outcome</SortTh>
            <SortTh sorter={sorter} k="result">Result</SortTh>
            <SortTh sorter={sorter} k="took">Took</SortTh>
            <SortTh sorter={sorter} k="bought">Paper bought</SortTh>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.symbol}-${r.ranked_on}`}>
              <td>
                <Stock symbol={r.symbol} caps={caps} />
              </td>
              <td>#{r.rank}</td>
              <td>{shortDate(r.ranked_on)}</td>
              <td>{shortDate(r.ended_on)}</td>
              <td>{OUTCOME_TEXT[r.outcome]}</td>
              <td className={tone(r.result_pct)}>
                <b>{pct(r.result_pct)}</b>
              </td>
              <td>{r.days != null ? `${r.days} days` : '—'}</td>
              <td>
                <Bought yes={r.paper_bought} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
