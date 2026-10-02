import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { featured, ideas, series, type Action } from '../data'
import { ActionPill, Card, CheckItem, GlowArea, Icon, Ring, Seg, StockLogo, inr, signed, toneClass } from '../ui'

type Filter = 'ALL' | Action

export default function Opportunities() {
  const [filter, setFilter] = useState<Filter>('ALL')
  const [sector, setSector] = useState('All Sectors')
  const [setup, setSetup] = useState('All Setups')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(featured.symbol)

  const count = (a: Action) => ideas.filter((i) => i.action === a).length
  const sectors = ['All Sectors', ...Array.from(new Set(ideas.map((i) => i.sector)))]
  const setups = ['All Setups', ...Array.from(new Set(ideas.map((i) => i.setup)))]

  const rows = useMemo(
    () =>
      ideas.filter(
        (i) =>
          (filter === 'ALL' || i.action === filter) &&
          (sector === 'All Sectors' || i.sector === sector) &&
          (setup === 'All Setups' || i.setup === setup) &&
          (query === '' || `${i.symbol} ${i.name}`.toLowerCase().includes(query.toLowerCase())),
      ),
    [filter, sector, setup, query],
  )

  const pick = ideas.find((i) => i.symbol === selected) ?? featured
  const spark = useMemo(
    () => series(pick.symbol.length * 31 + pick.confidence, 40, pick.price * 0.86, 0.004, 0.025),
    [pick],
  )

  return (
    <div className="tm-page tm-grid">
      <Card glow>
        <div className="tm-toolbar">
          <Seg<Filter>
            active={filter}
            onChange={setFilter}
            options={[
              { id: 'ALL', label: `All (${ideas.length})` },
              { id: 'TRADE', label: `Trade (${count('TRADE')})` },
              { id: 'WATCH', label: `Watch (${count('WATCH')})` },
              { id: 'WAIT', label: `Wait (${count('WAIT')})` },
              { id: 'AVOID', label: `Avoid (${count('AVOID')})` },
            ]}
          />
          <span className="tm-spacer" />
          <select className="tm-select" value={sector} onChange={(e) => setSector(e.target.value)}>
            {sectors.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <select className="tm-select" value={setup} onChange={(e) => setSetup(e.target.value)}>
            {setups.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <span className="tm-flex" style={{ gap: 0, position: 'relative' }}>
            <span style={{ position: 'absolute', left: 8, color: 'var(--tm-faint)', display: 'flex' }}>
              <Icon.Search size={13} />
            </span>
            <input
              className="tm-input"
              style={{ paddingLeft: 26 }}
              placeholder="Search stocks..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </span>
        </div>

        <div className="tm-table-wrap">
          <table className="tm-table">
            <thead>
              <tr>
                <th>Stock</th>
                <th className="tm-right">Price</th>
                <th>Signal</th>
                <th className="tm-right">Confidence</th>
                <th className="tm-right" title="Expected reward for every ₹1 risked">
                  Expected R
                </th>
                <th>Timeframe</th>
                <th>Setup</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((i) => (
                <tr
                  key={i.symbol}
                  className={`tm-clickable ${i.symbol === selected ? 'tm-selected' : ''}`}
                  onClick={() => setSelected(i.symbol)}
                >
                  <td>
                    <span className="tm-mini-dot" style={{ color: i.changePct >= 0 ? 'var(--tm-blue)' : 'var(--tm-red)' }} />
                    <span className="tm-strong">{i.name.toUpperCase()}</span>
                  </td>
                  <td className="tm-right tm-num">
                    {inr(i.price)} <small className={toneClass(i.changePct)}>{signed(i.changePct)}</small>
                  </td>
                  <td>
                    <ActionPill action={i.action} />
                  </td>
                  <td className="tm-right tm-num">{i.confidence}%</td>
                  <td className={`tm-right tm-num ${i.expectedR >= 1 ? 'tm-pos' : 'tm-neg'}`}>+{i.expectedR.toFixed(1)}R</td>
                  <td className="tm-dim">{i.timeframe}</td>
                  <td>{i.setup}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="tm-dim" style={{ textAlign: 'center', padding: '1.5rem' }}>
                    No stocks match these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Selected stock */}
      <Card glow className="tm-feature">
        <StockLogo symbol={pick.symbol} />
        <div>
          <div className="tm-strong" style={{ fontSize: '0.95rem' }}>
            {pick.name.toUpperCase()}
          </div>
          <div className="tm-big tm-num" style={{ fontSize: '1.6rem' }}>
            ₹{inr(pick.price)}{' '}
            <span className={toneClass(pick.changePct)} style={{ fontSize: '1rem' }}>
              {signed(pick.changePct)}
            </span>
          </div>
          <div className="tm-pos" style={{ fontSize: '0.72rem' }}>
            {pick.confidence}% Confidence
          </div>
        </div>
        <div className="tm-flex" style={{ minWidth: 0 }}>
          <Ring
            value={pick.confidence}
            size={84}
            stroke={8}
            center={
              <>
                <span className="tm-ring-value" style={{ fontSize: 20 }}>
                  {pick.confidence}%
                </span>
                <span className="tm-ring-label">Confidence</span>
              </>
            }
          />
          <div style={{ flex: 1, minWidth: 120 }}>
            <GlowArea data={spark} height={70} color={pick.changePct >= 0 ? '#2ee68a' : '#ff4d6a'} />
          </div>
        </div>
        <div>
          <div className="tm-strong" style={{ marginBottom: 2 }}>
            Why TradeMind {pick.action === 'AVOID' ? 'avoids' : 'likes'} this?
          </div>
          {pick.why.map((w) => (
            <CheckItem key={w} tone={pick.action === 'AVOID' ? 'neg' : 'pos'}>
              {w}
            </CheckItem>
          ))}
        </div>
        <Link className="tm-btn" to={`/trademind/stock/${encodeURIComponent(pick.symbol)}`}>
          View Details
        </Link>
      </Card>
    </div>
  )
}
