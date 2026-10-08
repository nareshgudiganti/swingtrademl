import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { BrainDecision } from '../../api/types'
import type { Action } from '../types'
import { barsFrom } from '../live-stock'
import { finalWord, stockSituations, useBrainStatus, useLatestRun, useWhy } from '../live'
import { wordClassName, wordTagColor, wordTone } from '../vocab'
import ScoreTrail from '../ScoreTrail'
import { Confirm } from '../Confirm'
import { CapFlag, useSymbolCaps } from '../cap'
import { ActionPill, BrainGate, Candles, Card, CheckItem, Icon, NotConnected, Seg, Tabs, Tag, inr, signed, toneClass } from '../ui'

const TABS = ['Overview', 'Technical', 'Fundamental', 'AI Analysis', 'Similar Cases', 'News', 'Options'] as const
type TabId = (typeof TABS)[number]

const RANGES = ['1M', '3M', '6M', '1Y'] as const
type Range = (typeof RANGES)[number]
const RANGE_DAYS: Record<Range, number> = { '1M': 22, '3M': 66, '6M': 132, '1Y': 252 }

// Most careful first — same order as the brain console. The owner may only
// move a decision toward caution, never toward more risk.
const IDEA_ORDER = ['AVOID', 'WAIT', 'WATCH', 'TRADE']
const HOLDING_ORDER = ['EXIT', 'REDUCE', 'MONITOR', 'HOLD']

const WORD_PLAIN: Record<string, string> = {
  TRADE: 'Buy it',
  WATCH: 'Not yet, keep an eye on it',
  WAIT: 'Wait, nothing to do',
  AVOID: 'Stay away',
  HOLD: 'Keep it, the plan is working',
  MONITOR: 'Keep it, but watch closely',
  REDUCE: 'Sell some',
  EXIT: 'Sell it all',
}

function Overrule({ decision }: { decision: BrainDecision }) {
  const queryClient = useQueryClient()
  const order = decision.kind === 'idea' ? IDEA_ORDER : HOLDING_ORDER
  const options = order.slice(0, order.indexOf(finalWord(decision)))
  const [word, setWord] = useState(options[options.length - 1] ?? '')
  const [asking, setAsking] = useState(false)

  return (
    <div className="tm-overrule">
      {decision.overruled_word && (
        <p className="tm-note tm-overrule-done">
          Changed by {decision.overruled_by ?? 'you'}: {decision.word} → {decision.overruled_word}
          {decision.overrule_reason ? ` — “${decision.overrule_reason}”` : ''}
        </p>
      )}
      {options.length === 0 ? (
        <p className="tm-dim">This is already the most careful word, so there is nothing to change.</p>
      ) : (
        <>
          <div className="tm-stat-label">Disagree? Make it more careful</div>
          <p className="tm-dim tm-overrule-hint">You can only make the brain more careful, never less. You must say why.</p>
          <div className="tm-action-row">
            <select className="tm-input" value={word} onChange={(e) => setWord(e.target.value)} aria-label="New decision">
              {options.map((w) => (
                <option key={w} value={w}>
                  {w} — {WORD_PLAIN[w]}
                </option>
              ))}
            </select>
            <button className="tm-btn" onClick={() => setAsking(true)}>
              Change decision
            </button>
          </div>
        </>
      )}
      {asking && (
        <Confirm
          title={`Change the decision on ${decision.symbol}?`}
          confirmLabel="Change decision"
          reason={{ label: 'Why are you changing it?', placeholder: 'e.g. results are due next week' }}
          onConfirm={async (reason) => {
            await api.brainOverrule(decision.id, word, reason)
            // The chosen word is now the final one; the next valid choice is one step more cautious.
            setWord(order[order.indexOf(word) - 1] ?? '')
            for (const key of ['brainLatest', 'brainWhy', 'brainRuns', 'brainTrack']) {
              queryClient.invalidateQueries({ queryKey: [key] })
            }
          }}
          onClose={() => setAsking(false)}
        >
          The brain said {finalWord(decision)}. You are changing it to {word} ({WORD_PLAIN[word]}).{' '}
          {decision.kind === 'idea'
            ? 'If a buy of this stock is waiting for your OK, or was approved but not placed yet, it will not happen, and the brain’s buy becomes a hold. '
            : 'This changes the brain’s advice on a stock you hold. '}
          Nothing you already own is sold by this change, and it can only ever move toward caution.
        </Confirm>
      )}
    </div>
  )
}

export default function StockDetail() {
  return (
    <BrainGate>
      <StockDetailBody />
    </BrainGate>
  )
}

function StockDetailBody() {
  const { symbol: rawSymbol } = useParams()
  const symbol = (rawSymbol ?? '').toUpperCase()
  const caps = useSymbolCaps()

  const status = useBrainStatus()
  const latest = useLatestRun()
  const run = latest.data
  const fromRun = run?.decisions.find((d) => d.symbol.toUpperCase() === symbol)
  const why = useWhy(status === 'live' && !fromRun && symbol ? symbol : undefined)

  const [tab, setTab] = useState<TabId>('Overview')
  const [range, setRange] = useState<Range>('3M')
  const candlesQ = useQuery({
    queryKey: ['candles', symbol, RANGE_DAYS[range]],
    queryFn: () => api.candles(symbol, RANGE_DAYS[range]),
    enabled: !!symbol,
  })
  const trailQ = useQuery({
    queryKey: ['stock-score-trail', symbol],
    queryFn: () => api.stockScoreTrail(symbol),
    enabled: !!symbol,
    retry: false,
  })
  const bars = useMemo(() => barsFrom(candlesQ.data ?? []), [candlesQ.data])

  const stillLookingUp = !fromRun && why.isLoading
  if (stillLookingUp) {
    return (
      <div className="tm-page">
        <p className="tm-dim">Looking up {symbol}…</p>
      </div>
    )
  }

  const lookupFailed = !fromRun && why.isError
  if (lookupFailed) {
    return (
      <div className="tm-page">
        <Card title="Could not reach the brain">
          <p className="tm-dim">Something went wrong talking to the brain. Try again shortly.</p>
        </Card>
      </div>
    )
  }

  const decision: BrainDecision | undefined = fromRun ?? why.data?.decision ?? undefined
  if (!decision) {
    return (
      <div className="tm-page">
        <Link to="/trademind/opportunities" className="tm-link tm-flex" style={{ gap: 2, marginBottom: '0.8rem' }}>
          <Icon.Back size={14} /> Opportunities
        </Link>
        <Card title={symbol || 'Unknown stock'}>
          <p className="tm-dim">No decision for this stock today.</p>
        </Card>
      </div>
    )
  }

  const situations = stockSituations(run!, symbol)
  const currentPrice = bars.length > 0 ? bars[bars.length - 1]!.c : undefined
  const prevClose = bars.length > 1 ? bars[bars.length - 2]!.c : undefined
  const changePct = currentPrice != null && prevClose != null ? ((currentPrice - prevClose) / prevClose) * 100 : undefined
  const refPrice = currentPrice ?? decision.entry_low ?? undefined
  const targetPct = decision.target != null && refPrice != null ? ((decision.target - refPrice) / refPrice) * 100 : undefined
  const stopPct = decision.stop != null && refPrice != null ? ((decision.stop - refPrice) / refPrice) * 100 : undefined

  const chart =
    candlesQ.isError || (candlesQ.isSuccess && bars.length === 0) ? (
      <NotConnected what="Price chart" reason="No stored price history for this stock yet." />
    ) : (
      <Card
        className="tm-span-2"
        title={<span className="tm-dim" style={{ fontWeight: 500 }}>{symbol} · daily price</span>}
        action={<Seg<Range> small active={range} onChange={setRange} options={RANGES.map((r) => ({ id: r, label: r }))} />}
      >
        {candlesQ.isLoading ? (
          <p className="tm-dim">Loading price history…</p>
        ) : (
          <Candles bars={bars} height={300} target={decision.target ?? undefined} stop={decision.stop ?? undefined} />
        )}
      </Card>
    )

  return (
    <div className="tm-page">
      <div className="tm-flex tm-wrap" style={{ marginBottom: '0.8rem', gap: '0.9rem' }}>
        <Link to="/trademind/opportunities" className="tm-link tm-flex" style={{ gap: 2 }}>
          <Icon.Back size={14} /> Opportunities
        </Link>
        <span className="tm-icon-badge" style={{ borderColor: 'rgba(79,140,255,.6)', color: 'var(--tm-blue)' }}>
          <Icon.Target />
        </span>
        <span style={{ fontSize: '1.25rem', fontWeight: 700 }}>
          {symbol}
          <CapFlag tier={caps.get(symbol)} gap />
        </span>
        {currentPrice != null && (
          <span className="tm-num" style={{ fontSize: '1.15rem', fontWeight: 600 }}>
            ₹{inr(currentPrice)}
          </span>
        )}
        {changePct != null && (
          <span className={`tm-num ${toneClass(changePct)}`} style={{ fontWeight: 600 }}>
            {signed(changePct)}
          </span>
        )}
        {decision.kind === 'idea' ? (
          <ActionPill action={finalWord(decision) as Action} />
        ) : (
          <Tag tone={wordTagColor(finalWord(decision))}>{finalWord(decision)}</Tag>
        )}
        {decision.confidence != null && (
          <span title="A ranking, not a chance — not a probability">
            <Tag tone="violet">{Math.round(decision.confidence * 100)} model score</Tag>
          </span>
        )}
      </div>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === 'Overview' && (
        <div className="tm-grid">
          <div className="tm-grid tm-cols-3">
            {chart}
            <Card glow title="TradeMind Decision">
              {decision.reasons.length > 0 ? (
                decision.reasons.map((r, i) => (
                  <CheckItem key={i} tone={wordTone(finalWord(decision))}>
                    {r}
                  </CheckItem>
                ))
              ) : (
                <p className="tm-dim">No reasons recorded for this decision.</p>
              )}
              {decision.evidence_text && <p className="tm-note" style={{ marginTop: '0.7rem' }}>{decision.evidence_text}</p>}
              <Overrule decision={decision} />
              <div className="tm-grid tm-cols-2" style={{ marginTop: '0.9rem', gap: '0.7rem' }}>
                {decision.entry_low != null && (
                  <div>
                    <div className="tm-stat-label">Buy around</div>
                    <div className="tm-stat-value">
                      ₹{inr(decision.entry_low, 0)}
                      {decision.entry_high != null && decision.entry_high !== decision.entry_low ? `–₹${inr(decision.entry_high, 0)}` : ''}
                    </div>
                  </div>
                )}
                {decision.target != null && (
                  <div>
                    <div className="tm-stat-label">Target</div>
                    <div className="tm-stat-value tm-pos">
                      ₹{inr(decision.target, 0)} {targetPct != null && <small>({signed(targetPct, 0)})</small>}
                    </div>
                  </div>
                )}
                {decision.stop != null && (
                  <div>
                    <div className="tm-stat-label">Stop Loss</div>
                    <div className="tm-stat-value tm-neg">
                      ₹{inr(decision.stop, 0)} {stopPct != null && <small>({signed(stopPct, 0)})</small>}
                    </div>
                  </div>
                )}
                <div>
                  <div className="tm-stat-label">Shares suggested</div>
                  <div className="tm-stat-value">{decision.qty}</div>
                </div>
                <div>
                  <div className="tm-stat-label">Horizon</div>
                  <div className="tm-stat-value" style={{ color: 'var(--tm-violet)' }}>
                    {decision.horizon_days} trading days
                  </div>
                </div>
              </div>
            </Card>
          </div>

          <Card title="Strength score, day by day" sub="How strongly the model liked this stock each day it was checked">
            {trailQ.isLoading ? (
              <p className="tm-dim">Loading…</p>
            ) : !trailQ.data || trailQ.data.score_trail.length === 0 ? (
              <p className="tm-dim">No daily scores saved for this stock yet. The list starts with the next daily check.</p>
            ) : (
              <ScoreTrail
                p={{
                  entry_confidence: null,
                  last_confidence: trailQ.data.last_score,
                  score_trail: trailQ.data.score_trail,
                  score_band: trailQ.data.score_band,
                }}
              />
            )}
          </Card>

          <div className="tm-grid tm-cols-2">
            <Card title="Situations recognised for this stock">
              {situations.length === 0 ? (
                <p className="tm-dim">No recognised situation for this stock right now.</p>
              ) : (
                <div className="tm-rows">
                  {situations.map((s, i) => (
                    <div key={i} className="tm-row" style={{ alignItems: 'flex-start' }}>
                      <span>
                        <div className="tm-strong">
                          {s.label}
                          {s.is_unknown ? ' — never seen before' : ''}
                        </div>
                        {s.evidence.map((e, j) => (
                          <div key={j} className="tm-faint">{e}</div>
                        ))}
                      </span>
                      {s.suggest_defensive && <Tag tone="amber">Suggests caution</Tag>}
                    </div>
                  ))}
                </div>
              )}
            </Card>
            <NotConnected
              what="AI scores"
              reason="Not connected yet — the brain gives one model score and a word, not separate technical, fundamental and sentiment scores."
            />
          </div>
        </div>
      )}

      {tab === 'Technical' && (
        <div className="tm-grid tm-cols-3">
          {chart}
          <NotConnected what="What the chart says" reason="Technical indicators (RSI, MACD, moving averages…) are not connected yet." />
        </div>
      )}

      {tab === 'Fundamental' && (
        <NotConnected what="Fundamentals" reason="Fundamentals are not connected yet — the brain does not read company results." />
      )}

      {tab === 'AI Analysis' && (
        <div className="tm-grid tm-cols-2">
          <Card glow title="Why the brain decided this">
            {decision.reasons.length > 0 ? (
              decision.reasons.map((r, i) => (
                <CheckItem key={i} tone={wordTone(finalWord(decision))}>
                  {r}
                </CheckItem>
              ))
            ) : (
              <p className="tm-dim">No reasons recorded for this decision.</p>
            )}
            {decision.evidence_text && <p className="tm-note" style={{ marginTop: '0.7rem' }}>{decision.evidence_text}</p>}
          </Card>
          <Card title="In plain words">
            <p style={{ marginTop: 0 }}>
              TradeMind {decision.kind === 'idea' ? 'suggests' : 'currently has'}{' '}
              <strong className={wordClassName(finalWord(decision))}>{finalWord(decision)}</strong> for {symbol}
              {decision.confidence != null && (
                <>
                  {' '}
                  with <strong>{Math.round(decision.confidence * 100)} model score</strong>
                </>
              )}
              .
            </p>
            <div style={{ marginTop: '1rem' }}>
              <Link className="tm-btn" to={`/trademind/ai/${encodeURIComponent(symbol)}`}>
                Open full reasoning
              </Link>
            </div>
          </Card>
        </div>
      )}

      {tab === 'Similar Cases' &&
        (decision.evidence_text?.includes('Similar cases') ? (
          <Card glow title="Times this looked the same before" sub="What the brain found in similar past situations">
            <p className="tm-dim">{decision.evidence_text}</p>
          </Card>
        ) : (
          <NotConnected what="Similar cases" reason="The brain hasn't recorded similar-case evidence for this decision." />
        ))}

      {tab === 'News' && (
        <NotConnected what="Recent news" reason="News is not connected yet — the brain does not read news." />
      )}

      {tab === 'Options' && (
        <NotConnected what="Options" reason="Options data is not connected yet — the brain does not read the options chain." />
      )}
    </div>
  )
}
