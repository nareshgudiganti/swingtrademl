// The new look's Today: answer first, details on tap. Display only — it reads what the classic Today reads and
// changes nothing about picks, decisions, orders, sizing, stops or limits. Top to bottom:
//   1. greeting + one headline sentence
//   2. market status, then three counts (new trades / watch closely / holdings to review; owner: waiting for OK)
//   3. top ideas, one short reason each, ranked (never a chance of profit)
//   4. the bot's paper portfolio (value, invested, cash) and, when there are no trades, why — from the run only
//   5. "Full details": the whole classic Today, unchanged, so nothing it shows is lost
// The experimental-model note appears once, at the foot.

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api } from '../../api/client'
import type { BrainRun } from '../../api/types'
import { formatDateTime } from '../../lib/format'
import { CapFlag, useSymbolCaps } from '../cap'
import { noTradeReason } from '../emptyReasons'
import { ideasFrom, finalWord, useLatestRun } from '../live'
import { QueryNotice } from '../PageState'
import { rankText, scoreRank, SCORE_HINT } from '../scoreText'
import { currentDrawdownPct } from '../live-system'
import { greeting, oneReason, safetySummary, stoppedByRoom, todayHeadline } from '../today/answerRules'
import { holdingsNeedingAttention } from '../today/HoldingsNeedsYou'
import { waitingItems } from '../today/NeedsYou'
import { ideaCounts } from '../today/TodayIdeas'
import { IdeaFigures, PeekCard } from '../stockParts'
import { BrainGate, inr, StockLogo, Tag } from '../ui'
import { MARKET_LABEL, MARKET_PLAIN, MARKET_TONE, wordLabel, wordTagColor } from '../vocab'

/** The new Today shows the top 3 ideas (owner brief: short, answer first); Discover lists every one. */
export const TOP_IDEAS_NEW = 3

export default function TodayNew({ owner = false }: { owner?: boolean }) {
  const today = new Intl.DateTimeFormat('en-IN', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'Asia/Kolkata',
  }).format(new Date())

  return (
    <div className="tm-page tmn-today" data-page="today-new">
      <div className="tmn-hello">
        <h2>{greeting()}</h2>
        <span className="tm-dim">{today}</span>
      </div>
      <BrainGate inline>
        <Answer owner={owner} />
      </BrainGate>
      <p className="tmn-foot">
        Practice mode: everything here is paper trading. The 15-day model is experimental and not yet proven.
      </p>
    </div>
  )
}

function Answer({ owner }: { owner: boolean }) {
  const run = useLatestRun().data!
  const ideas = ideasFrom(run)
  const counts = ideaCounts(run)
  const attention = holdingsNeedingAttention(run)
  const mode = run.banner.mode
  const tone = (mode && MARKET_TONE[mode]) || 'blue'

  return (
    <>
      <p className="tmn-headline" data-testid="today-headline">
        {todayHeadline(mode, counts, attention.length)}
      </p>

      <section className="tmn-card tmn-market" data-tone={tone} aria-label="Market status">
        <div className="tmn-card-head">
          <span className="tmn-card-title">Market status</span>
          <Link className="tm-link" to="/trademind/market">
            View details
          </Link>
        </div>
        <div className="tmn-market-word">
          <Tag tone={tone}>{mode ? MARKET_LABEL[mode] : 'Unknown'}</Tag>
        </div>
        <p className="tm-dim">{(mode && MARKET_PLAIN[mode]) ?? 'The brain did not say what mode the market is in.'}</p>
        {run.banner.headline && <p className="tm-dim tmn-small">{run.banner.headline}</p>}
        <p className="tmn-small tm-faint">From the brain's run on {formatDateTime(run.started_at)}</p>
      </section>

      <div className={`tmn-tiles ${owner ? 'tmn-tiles-4' : ''}`} data-testid="today-tiles">
        <Tile n={counts.TRADE} label="New buys today" to="/trademind/opportunities" tone={counts.TRADE ? 'green' : undefined} />
        <Tile n={counts.WATCH} label="Watch closely" to="/trademind/opportunities" tone={counts.WATCH ? 'amber' : undefined} />
        <Tile n={attention.length} label="Holdings need review" to="/trademind/positions" tone={attention.length ? 'red' : undefined} />
        {owner && <WaitingTile />}
      </div>

      <TopIdeas run={run} />

      <div className="tmn-row-2">
        <PortfolioSummary />
        <RoomNote run={run} ideaCount={ideas.length} tradeCount={counts.TRADE} />
      </div>

      <SafetyLine owner={owner} />
    </>
  )
}

function Tile({ n, label, to, tone }: { n: number | string; label: string; to: string; tone?: 'green' | 'amber' | 'red' }) {
  return (
    <Link to={to} className="tmn-tile" data-tone={tone}>
      <span className="tmn-tile-n">{n}</span>
      <span className="tmn-tile-label">{label}</span>
    </Link>
  )
}

/** Owner only: ideas waiting for the owner's OK (M18 approval stage). The answer is owner-only on the server. */
function WaitingTile() {
  const approvals = useQuery({ queryKey: ['brainApprovals'], queryFn: api.brainApprovals, retry: false })
  const n = approvals.data ? waitingItems(approvals.data, []).approvals.length : approvals.isError ? '—' : '…'
  return <Tile n={n} label="Waiting for your OK" to="/trademind/golive" tone={typeof n === 'number' && n > 0 ? 'amber' : undefined} />
}

function TopIdeas({ run }: { run: BrainRun }) {
  const caps = useSymbolCaps()
  const ideas = ideasFrom(run)
  const top = ideas.slice(0, TOP_IDEAS_NEW)
  const dayScores = ideas.map((d) => d.confidence)
  // Tapping a stock opens a quick look right here (score, rank, price, buy zone, Buy); the full analysis is one tap on.
  const [open, setOpen] = useState<number | null>(null)
  const opened = top.find((d) => d.id === open)

  return (
    <section className="tmn-card" aria-label="Top ideas">
      <div className="tmn-card-head">
        <span className="tmn-card-title">Top ideas</span>
        <Link className="tm-link" to="/trademind/opportunities">
          View all {ideas.length}
        </Link>
      </div>
      {top.length === 0 ? (
        <p className="tm-dim">No ideas in the brain's last run.</p>
      ) : (
        <div className="tmn-ideas" data-testid="top-ideas">
          {top.map((d) => {
            const rank = scoreRank(d.confidence, dayScores)
            return (
              <button
                type="button"
                key={d.id}
                className="tmn-idea"
                aria-expanded={open === d.id}
                onClick={() => setOpen(open === d.id ? null : d.id)}
              >
                <StockLogo symbol={d.symbol} />
                <span className="tmn-idea-main">
                  <span className="tmn-idea-sym">
                    {d.symbol} <CapFlag tier={caps.get(d.symbol.toUpperCase())} />
                  </span>
                  <span className="tmn-idea-why">
                    {oneReason(d)} <span className="tmn-ailink">AI analysis →</span>
                  </span>
                </span>
                <IdeaFigures d={d} />
                <span className="tmn-idea-side">
                  <span className={`tm-tag tm-tag-${wordTagColor(finalWord(d))}`}>{wordLabel(finalWord(d))}</span>
                  {rank && (
                    <span className="tmn-small tm-dim" title={SCORE_HINT}>
                      {rankText(rank)}
                    </span>
                  )}
                </span>
              </button>
            )
          })}
        </div>
      )}
      {opened && <PeekCard decision={opened} run={run} reason={oneReason(opened)} />}
    </section>
  )
}

/** The bot's paper book now: value, how much is invested, how much is cash. No profit figure. */
function PortfolioSummary() {
  const summary = useQuery({ queryKey: ['summary'], queryFn: () => api.summary() })
  const s = summary.data
  const investedPct = s && s.total_value > 0 ? Math.round((s.holdings_value / s.total_value) * 100) : null

  return (
    <section className="tmn-card" aria-label="Portfolio summary">
      <div className="tmn-card-head">
        <span className="tmn-card-title">
          Bot portfolio <Tag tone="blue">Paper</Tag>
        </span>
        <Link className="tm-link" to="/trademind/portfolio">
          View details
        </Link>
      </div>
      <QueryNotice q={summary} what="the portfolio" />
      {s && (
        <>
          <div className="tmn-money">
            <div>
              <div className="tmn-money-n">₹{inr(s.total_value, 0)}</div>
              <div className="tmn-small tm-dim">Total value</div>
            </div>
            <div>
              <div className="tmn-money-n">{investedPct == null ? '—' : `${investedPct}%`}</div>
              <div className="tmn-small tm-dim">Invested</div>
            </div>
            <div>
              <div className="tmn-money-n">{investedPct == null ? '—' : `${100 - investedPct}%`}</div>
              <div className="tmn-small tm-dim">Cash</div>
            </div>
          </div>
          {investedPct != null && (
            <div className="tmn-bar" aria-label={`${investedPct}% invested`}>
              <span style={{ width: `${Math.min(100, Math.max(0, investedPct))}%` }} />
            </div>
          )}
          <p className="tmn-small tm-dim">
            {s.open_positions === 1 ? '1 stock held' : `${s.open_positions} stocks held`}, ₹{inr(s.cash, 0)} cash.
          </p>
        </>
      )}
    </section>
  )
}

/** Why there is no trade today, only from the run: its banner and the stored "no room" lines. Hidden when there
 *  are trade ideas and nothing was stopped for room. */
function RoomNote({ run, ideaCount, tradeCount }: { run: BrainRun; ideaCount: number; tradeCount: number }) {
  const reason = noTradeReason(run.banner, ideaCount, tradeCount)
  const noRoom = stoppedByRoom(ideasFrom(run))
  if (!reason && noRoom === 0) return null
  return (
    <section className="tmn-card tmn-note" aria-label="Why no new trades" data-testid="room-note">
      <div className="tmn-card-head">
        <span className="tmn-card-title">{tradeCount > 0 ? 'Room for new trades' : 'Why no new trades'}</span>
        <Link className="tm-link" to="/trademind/opportunities">
          See every stock
        </Link>
      </div>
      {reason && <p>{reason}</p>}
      {noRoom > 0 && (
        <p className="tm-dim">
          {noRoom === 1 ? '1 stock was' : `${noRoom} stocks were`} stopped by the account&apos;s safety limits (no room
          left).
        </p>
      )}
    </section>
  )
}

/** One line: is the safety net on? Owner: kill switch and the account's fall from its peak against the halt level
 *  (owner-only answers on the server). Everyone else: the rules every trade follows. Links to Portfolio. */
function SafetyLine({ owner }: { owner: boolean }) {
  const limits = useQuery({ queryKey: ['riskLimits'], queryFn: api.riskLimits, enabled: owner })
  const equity = useQuery({ queryKey: ['equityCurve', 400], queryFn: () => api.equityCurve(400), enabled: owner })
  const safety = useQuery({ queryKey: ['safetyState'], queryFn: api.safetyState, enabled: owner, retry: false })
  const s = safetySummary({
    owner,
    paused: safety.data ? !safety.data.new_entries_enabled : null,
    ddPct: equity.data ? currentDrawdownPct(equity.data) : null,
    haltPct: limits.data?.max_drawdown_pct != null ? limits.data.max_drawdown_pct * 100 : null,
  })
  return (
    <Link to="/trademind/portfolio" className="tmn-card tmn-safety" data-tone={s.tone} data-testid="safety-line">
      <span className="tmn-safety-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" />
          <path d="M9 12l2 2 4-4" />
        </svg>
      </span>
      <span className="tmn-grow">{s.text}</span>
      <span className="tm-link">See the rules →</span>
    </Link>
  )
}
