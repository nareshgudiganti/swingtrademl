import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api } from '../../api/client'
import type { MLModel, Strategy } from '../../api/types'
import SymbolPicker from '../../components/SymbolPicker'
import { formatDate, formatPercent, modelLabel } from '../../lib/format'
import { Confirm } from '../Confirm'
import { Card, PageHead, Seg, Tabs, Tag } from '../ui'

const TABS = ['Account & alerts', 'Stocks watched', 'Price data', 'Strategies', 'Models'] as const
type TabName = (typeof TABS)[number]

function Problem({ what }: { what: string }) {
  return <p className="tm-neg">Could not load {what}. Try again shortly.</p>
}

// ---------------------------------------------------------------- account --

function AccountTab() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })
  const telegram = useQuery({ queryKey: ['telegram'], queryFn: api.telegramStatus })
  const status = useQuery({ queryKey: ['status'], queryFn: api.status })
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<string | null>(null)

  return (
    <div className="tm-grid tm-cols-2">
      <Card title="Who is logged in">
        {me.isLoading && <p className="tm-dim">Loading…</p>}
        {me.isError && <Problem what="your account" />}
        {me.data && (
          <>
            <div className="tm-strong">{me.data.username}</div>
            <div className="tm-dim">
              {me.data.email ?? 'No email on file'} · signed in with{' '}
              {me.data.auth_provider === 'google' ? 'Google' : 'a password'}
            </div>
          </>
        )}
      </Card>

      <Card title="Zerodha connection">
        {status.isLoading && <p className="tm-dim">Loading…</p>}
        {status.isError && <Problem what="the connection" />}
        {status.data && (
          <>
            <div>
              <Tag tone={status.data.broker_authenticated ? 'green' : 'amber'}>
                {status.data.broker_authenticated ? 'Connected' : 'Not connected'}
              </Tag>
            </div>
            <p className="tm-dim" style={{ marginBottom: 0 }}>
              Logging in to Zerodha is done on the <Link to="/trademind/control">Control page</Link>.
            </p>
          </>
        )}
      </Card>

      <Card title="Telegram alerts" sub="Messages sent to your phone when something needs your attention">
        {telegram.isLoading && <p className="tm-dim">Loading…</p>}
        {telegram.isError && <Problem what="Telegram status" />}
        {telegram.data && (
          <>
            <div className="tm-between" style={{ flexWrap: 'wrap', gap: '0.5rem' }}>
              <Tag tone={telegram.data.ok ? 'green' : 'amber'}>
                {telegram.data.ok ? `On${telegram.data.bot ? ` (@${telegram.data.bot})` : ''}` : 'Off'}
              </Tag>
              <button className="tm-btn" disabled={!telegram.data.ok} onClick={() => setTesting(true)}>
                Send a test message
              </button>
            </div>
            <p className="tm-dim" style={{ marginBottom: 0 }}>
              {telegram.data.ok
                ? 'Sell warnings and other alerts are sent to Telegram. Without this you would only see them by opening the app.'
                : (telegram.data.error ?? 'Telegram is not set up, so alerts only show inside the app.')}
            </p>
            {result && <p className="tm-pos">{result}</p>}
          </>
        )}
      </Card>

      {testing && (
        <Confirm
          title="Send a test message?"
          confirmLabel="Send"
          onConfirm={async () => {
            const r = await api.telegramTest()
            setResult(r.message)
          }}
          onClose={() => setTesting(false)}
        >
          One short test message will be sent to your Telegram. Nothing is bought or sold.
        </Confirm>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- watched --

function WatchTab() {
  const queryClient = useQueryClient()
  const watchlist = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist })
  const [symbols, setSymbols] = useState<string[]>([])
  const seeded = useRef(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (watchlist.data && !seeded.current) {
      setSymbols(watchlist.data.map((i) => i.tradingsymbol))
      seeded.current = true
    }
  }, [watchlist.data])

  const original = (watchlist.data ?? []).map((i) => i.tradingsymbol)
  const changed = symbols.length !== original.length || symbols.some((s) => !original.includes(s))

  return (
    <Card
      title="Stocks watched"
      sub="The stocks the app keeps an eye on. The brain also looks at the stocks from version 1, so it may study more than this list."
    >
      {watchlist.isLoading && <p className="tm-dim">Loading…</p>}
      {watchlist.isError && <Problem what="the list" />}
      {watchlist.data && (
        <>
          <div className="tm-dim" style={{ fontSize: '0.8rem', marginBottom: '0.4rem' }}>
            Search by company name or short code, then press Enter to add. Press the × on a stock to remove it.
          </div>
          <div className="tm-picker">
            <SymbolPicker
              value={symbols}
              onChange={(v) => {
                setSymbols(v)
                setSaved(false)
              }}
              placeholder="Search for a company…"
            />
          </div>
          {symbols.length === 0 && <p className="tm-dim">The list is empty. Add at least one stock to save.</p>}
          <div className="tm-flex" style={{ marginTop: '0.8rem', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
            <button className="tm-btn" disabled={!changed || symbols.length === 0} onClick={() => setSaving(true)}>
              Save the list
            </button>
            {saved && !changed && <span className="tm-pos">Saved.</span>}
          </div>
        </>
      )}
      {saving && (
        <Confirm
          title="Save this list?"
          confirmLabel="Save"
          onConfirm={async () => {
            await api.setWatchlist(symbols)
            await queryClient.invalidateQueries({ queryKey: ['watchlist'] })
            await queryClient.invalidateQueries({ queryKey: ['status'] })
            setSaved(true)
          }}
          onClose={() => setSaving(false)}
        >
          The app will watch these {symbols.length} stock{symbols.length === 1 ? '' : 's'} from now on.
          Stocks you already hold are not sold by this.
        </Confirm>
      )}
    </Card>
  )
}

// ------------------------------------------------------------- price data --

type DataAction = 'backfill' | 'sync' | null

function DataTab() {
  const queryClient = useQueryClient()
  const coverage = useQuery({ queryKey: ['coverage'], queryFn: api.coverage })
  const [action, setAction] = useState<DataAction>(null)
  const [result, setResult] = useState<string | null>(null)

  return (
    <div className="tm-grid">
      <Card title="Price history" sub="The past prices the app learns from. Stocks with fewer than 300 days of history are marked in red.">
        <div className="tm-flex" style={{ gap: '0.5rem', flexWrap: 'wrap' }}>
          <button className="tm-btn" onClick={() => setAction('backfill')}>
            Download missing price history
          </button>
          <button className="tm-btn tm-btn-ghost" onClick={() => setAction('sync')}>
            Update the list of tradable stocks
          </button>
        </div>
        {result && <p className="tm-pos">{result}</p>}
      </Card>

      <Card title="What price history we have">
        {coverage.isLoading && <p className="tm-dim">Loading…</p>}
        {coverage.isError && <Problem what="price history" />}
        {coverage.data && coverage.data.length === 0 && (
          <p className="tm-dim">No price history yet. Update the list of tradable stocks first, then download the history.</p>
        )}
        {coverage.data && coverage.data.length > 0 && (
          <div className="tm-table-wrap">
            <table className="tm-table">
              <thead>
                <tr>
                  <th>Stock</th>
                  <th>Days of prices</th>
                  <th>From</th>
                  <th>To</th>
                </tr>
              </thead>
              <tbody>
                {coverage.data.map((c) => (
                  <tr key={c.symbol}>
                    <td className="tm-strong">{c.symbol}</td>
                    <td className={c.candles < 300 ? 'tm-neg' : ''}>{c.candles.toLocaleString('en-IN')}</td>
                    <td className="tm-dim">{c.from ? formatDate(c.from) : '—'}</td>
                    <td className="tm-dim">{c.to ? formatDate(c.to) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {action === 'backfill' && (
        <Confirm
          title="Download missing price history?"
          confirmLabel="Download"
          onConfirm={async () => {
            const r = await api.backfill({ interval: 'day' })
            setResult(`${r.message}${r.detail ? `. ${r.detail}` : ''}`)
            await queryClient.invalidateQueries({ queryKey: ['coverage'] })
          }}
          onClose={() => setAction(null)}
        >
          The app will fetch past daily prices for the stocks it watches. This can take a few minutes, so keep this window open.
          Nothing is bought or sold.
        </Confirm>
      )}
      {action === 'sync' && (
        <Confirm
          title="Update the list of tradable stocks?"
          confirmLabel="Update"
          onConfirm={async () => {
            const r = await api.syncInstruments()
            setResult(r.message)
            await queryClient.invalidateQueries({ queryKey: ['watchlist'] })
          }}
          onClose={() => setAction(null)}
        >
          The app will ask Zerodha for its current list of stocks. This can take a minute or two. Zerodha must be connected.
          Nothing is bought or sold.
        </Confirm>
      )}
    </div>
  )
}

// ------------------------------------------------------------- strategies --

const STRATEGY_PLAIN: Record<string, string> = {
  ml_swing_main: 'Large companies (model)',
  ml_swing_midcap: 'Mid-size companies (model)',
  ml_swing_smallcap: 'Small companies (model)',
  sma_crossover_benchmark: 'Simple yardstick (moving averages)',
  brain: 'TradeMind brain (practice)',
  real_trading: 'Your own buys',
}

function StrategiesTab() {
  const queryClient = useQueryClient()
  const strategies = useQuery({ queryKey: ['strategies'], queryFn: api.strategies })
  const [target, setTarget] = useState<Strategy | null>(null)

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['strategies'] })
    await queryClient.invalidateQueries({ queryKey: ['strategyPerformance'] })
    // Switching the brain strategy also moves the brain back to practice.
    await queryClient.invalidateQueries({ queryKey: ['brainModules'] })
    await queryClient.invalidateQueries({ queryKey: ['brainLatest'] })
  }

  return (
    <Card
      title="Strategies"
      sub="Each strategy is one way the app finds stocks to buy. You can switch them on or off here."
    >
      {strategies.isLoading && <p className="tm-dim">Loading…</p>}
      {strategies.isError && <Problem what="the strategies" />}
      {strategies.data && strategies.data.length === 0 && <p className="tm-dim">There are no strategies yet.</p>}
      {strategies.data && strategies.data.length > 0 && (
        <div className="tm-table-wrap">
          <table className="tm-table">
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Status</th>
                <th>Money</th>
                <th>Switch</th>
              </tr>
            </thead>
            <tbody>
              {strategies.data.map((s) => (
                <tr key={s.id}>
                  <td className="tm-strong tm-wrap" title={s.name}>
                    {STRATEGY_PLAIN[s.name] ?? s.description ?? s.name}
                  </td>
                  <td>
                    <Tag tone={s.is_active ? 'green' : 'amber'}>{s.is_active ? 'On' : 'Off'}</Tag>
                  </td>
                  <td>
                    <Tag tone={s.mode === 'live' ? 'red' : 'blue'}>{s.mode === 'live' ? 'Real money' : 'Practice'}</Tag>
                  </td>
                  <td>
                    <Seg
                      small
                      options={[
                        { id: 'on', label: 'On' },
                        { id: 'off', label: 'Off' },
                      ]}
                      active={s.is_active ? 'on' : 'off'}
                      onChange={(v) => (v === 'on') !== s.is_active && setTarget(s)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {target && (
        <Confirm
          title={`Switch ${target.is_active ? 'off' : 'on'} “${STRATEGY_PLAIN[target.name] ?? target.name}”?`}
          confirmLabel={target.is_active ? 'Switch off' : 'Switch on'}
          danger={target.is_active}
          onConfirm={async () => {
            await (target.is_active ? api.deactivateStrategy(target.id) : api.activateStrategy(target.id))
            await invalidate()
          }}
          onClose={() => setTarget(null)}
        >
          {target.name === 'real_trading' ? (
            target.is_active ? (
              <>
                The bot will stop tracking and sending alerts about the shares you bought yourself in Zerodha. It never buys
                anything for this one, and your shares are not touched.
              </>
            ) : (
              <>The bot will start tracking and sending alerts about the shares you bought yourself in Zerodha again. It never buys anything for this one.</>
            )
          ) : target.name === 'brain' ? (
            target.is_active ? (
              <>
                The brain will stop recording its ideas. Switching it off also puts the brain back to practice. Stocks it
                already holds keep their stop-loss and target.
              </>
            ) : (
              <>
                The brain will start recording its ideas again. In practice it only records ideas; it buys only through the
                Go-live stage rules.
              </>
            )
          ) : target.is_active ? (
            <>It will stop making new buys. Stocks it already holds keep their stop-loss and target.</>
          ) : (
            <>It will start looking for new stocks to buy again, with {target.mode === 'live' ? 'real money' : 'practice money'}.</>
          )}
        </Confirm>
      )}
    </Card>
  )
}

// ----------------------------------------------------------------- models --

function ModelAccuracy({ model }: { model: MLModel }) {
  const acc = useQuery({ queryKey: ['predAccuracy', model.id], queryFn: () => api.predictionAccuracy(model.id) })
  return (
    <tr>
      <td className="tm-strong tm-wrap" title={`${model.name}:${model.version}`}>
        {modelLabel(`${model.name}:${model.version}`)}
      </td>
      <td>
        {acc.isLoading && <span className="tm-dim">Loading…</span>}
        {acc.isError && <span className="tm-neg">Could not load</span>}
        {acc.data &&
          (acc.data.evaluated_predictions > 0 ? (
            <>
              <span className="tm-strong">{formatPercent(acc.data.accuracy, 0)}</span>{' '}
              <span className="tm-dim">
                ({acc.data.correct} of {acc.data.evaluated_predictions} right)
              </span>
            </>
          ) : (
            <span className="tm-dim">Too new to judge: no predictions have been checked yet.</span>
          ))}
      </td>
      <td className="tm-dim">
        Looks {model.prediction_horizon_days} days ahead, for a rise of {formatPercent(model.target_return_pct, 1)}
      </td>
    </tr>
  )
}

function verdictFor(gap: number | null, meaningful: boolean): { label: string; tone: 'green' | 'amber' | 'blue' | 'violet' } {
  if (!meaningful) return { label: 'Too few to judge', tone: 'violet' }
  if (gap == null) return { label: '—', tone: 'violet' }
  if (gap <= -0.1) return { label: 'Too sure of itself', tone: 'amber' }
  if (gap >= 0.1) return { label: 'Too modest', tone: 'blue' }
  return { label: 'Honest', tone: 'green' }
}

const HORIZONS = [5, 10, 15] as const

function ModelsTab() {
  const status = useQuery({ queryKey: ['status'], queryFn: api.status })
  const models = useQuery({ queryKey: ['models'], queryFn: api.models })
  const [horizon, setHorizon] = useState<number>(5)
  const horizonAcc = useQuery({
    queryKey: ['predAccuracyHorizon', horizon],
    queryFn: () => api.predictionAccuracyAtHorizon(horizon),
  })
  const [source, setSource] = useState<'signals' | 'predictions'>('signals')
  const report = useQuery({ queryKey: ['calibration', source], queryFn: () => api.calibration(source) })

  const active = (models.data ?? []).filter((m) => m.status === 'ACTIVE')
  const activeNames = status.data?.active_models ?? []

  return (
    <div className="tm-grid">
      <Card
        title="Models in use"
        sub="One model per company size. Each studies past prices and gives every stock a chance of rising. Here you can only see them."
      >
        {(status.isLoading || models.isLoading) && <p className="tm-dim">Loading…</p>}
        {(status.isError || models.isError) && <Problem what="the models" />}
        {status.data && models.data && active.length === 0 && (
          <>
            {activeNames.length > 0 ? (
              activeNames.map((m) => (
                <div key={m} className="tm-strong" title={m}>
                  {modelLabel(m)}
                </div>
              ))
            ) : (
              <p className="tm-dim">No model is in use right now.</p>
            )}
          </>
        )}
        {active.length > 0 && (
          <div className="tm-table-wrap">
            <table className="tm-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>How often it was right</th>
                  <th>What it predicts</th>
                </tr>
              </thead>
              <tbody>
                {active.map((m) => (
                  <ModelAccuracy key={m.id} model={m} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="All predictions, judged over a different time span"
        sub="Re-checks every past prediction as if it had been about this many days ahead."
        action={
          <Seg
            small
            options={HORIZONS.map((h) => ({ id: String(h), label: `${h} days` }))}
            active={String(horizon)}
            onChange={(v) => setHorizon(Number(v))}
          />
        }
      >
        {horizonAcc.isLoading && <p className="tm-dim">Loading…</p>}
        {horizonAcc.isError && <Problem what="this check" />}
        {horizonAcc.data &&
          (horizonAcc.data.evaluable > 0 ? (
            <>
              <div className="tm-big" style={{ fontSize: '1.4rem' }}>{formatPercent(horizonAcc.data.accuracy, 0)}</div>
              <div className="tm-stat-label">
                right: {horizonAcc.data.correct} of {horizonAcc.data.evaluable} predictions that could be checked, looking for a rise of{' '}
                {formatPercent(horizonAcc.data.target_return, 1)} within {horizonAcc.data.horizon_days} days
              </div>
            </>
          ) : (
            <p className="tm-dim">Not enough time has passed to check any prediction over {horizon} days.</p>
          ))}
      </Card>

      <Card
        title="Is the model's confidence honest?"
        sub="When the model says about 60%, does it really work out about 60% of the time?"
        action={
          <Seg
            small
            options={[
              { id: 'signals', label: 'Buy ideas' },
              { id: 'predictions', label: 'All predictions' },
            ]}
            active={source}
            onChange={setSource}
          />
        }
      >
        {report.isLoading && <p className="tm-dim">Loading…</p>}
        {report.isError && <Problem what="this check" />}
        {report.data && report.data.buckets.length === 0 && (
          <p className="tm-dim">Nothing has been checked yet. This needs predictions whose outcome is already known.</p>
        )}
        {report.data && report.data.buckets.length > 0 && (
          <>
            <div className="tm-stat-label" style={{ marginBottom: '0.5rem' }}>
              {report.data.total_scored} predictions checked. Bands with fewer than 30 examples are not real evidence.
            </div>
            <div className="tm-table-wrap">
              <table className="tm-table">
                <thead>
                  <tr>
                    <th>When it said</th>
                    <th>It was right</th>
                    <th>Verdict</th>
                  </tr>
                </thead>
                <tbody>
                  {report.data.buckets.map((b) => {
                    const v = verdictFor(b.calibration_gap, b.meaningful)
                    return (
                      <tr key={`${b.lower}-${b.upper}`}>
                        <td>
                          {formatPercent(b.lower, 0)} to {formatPercent(b.upper, 0)}
                        </td>
                        <td>
                          {b.observed_rate != null ? (
                            <>
                              <span className="tm-strong">{formatPercent(b.observed_rate, 0)}</span>{' '}
                              <span className="tm-dim">of the time ({b.wins} of {b.n})</span>
                            </>
                          ) : (
                            '—'
                          )}
                        </td>
                        <td>
                          <Tag tone={v.tone}>{v.label}</Tag>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <p className="tm-dim" style={{ marginBottom: 0 }}>
              “Too sure of itself” means it promised more than it delivered, which is the kind that costs money.
            </p>
          </>
        )}
      </Card>
    </div>
  )
}

// ------------------------------------------------------------------- page --

export default function Setup() {
  const [tab, setTab] = useState<TabName>('Account & alerts')
  return (
    <div className="tm-page tm-grid">
      <PageHead title="Setup" sub="Your account, the stocks watched, the price data, and what is switched on." />
      <Tabs tabs={TABS} active={tab} onChange={setTab} />
      {tab === 'Account & alerts' && <AccountTab />}
      {tab === 'Stocks watched' && <WatchTab />}
      {tab === 'Price data' && <DataTab />}
      {tab === 'Strategies' && <StrategiesTab />}
      {tab === 'Models' && <ModelsTab />}
    </div>
  )
}
