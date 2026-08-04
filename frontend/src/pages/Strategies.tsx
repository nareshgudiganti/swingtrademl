import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatDate } from '../lib/format'

export default function Strategies() {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)

  const strategies = useQuery({ queryKey: ['strategies'], queryFn: api.strategies })
  const types = useQuery({ queryKey: ['strategyTypes'], queryFn: api.strategyTypes })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['strategies'] })

  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      active ? api.deactivateStrategy(id) : api.activateStrategy(id),
    onSuccess: invalidate,
  })

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteStrategy(id),
    onSuccess: invalidate,
  })

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.createStrategy(body),
    onSuccess: () => {
      invalidate()
      setShowForm(false)
    },
  })

  const scan = useMutation({
    mutationFn: api.scanAll,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['signals'] })
      queryClient.invalidateQueries({ queryKey: ['positions'] })
      queryClient.invalidateQueries({ queryKey: ['summary'] })
    },
  })

  if (strategies.isLoading) return <Loading />
  if (strategies.error) return <ErrorBox error={strategies.error} />

  const rows = strategies.data ?? []

  return (
    <>
      <div className="page-head">
        <h1>Strategies</h1>
        <div className="row">
          <button onClick={() => scan.mutate()} disabled={scan.isPending}>
            {scan.isPending ? 'Scanning…' : 'Run scan now'}
          </button>
          <button className="primary" onClick={() => setShowForm((v) => !v)}>
            {showForm ? 'Cancel' : 'New strategy'}
          </button>
        </div>
      </div>

      {scan.data && (
        <div className="banner banner-info">
          Scan complete — {scan.data.instruments_evaluated} instruments evaluated,{' '}
          {scan.data.signals_generated} signals ({scan.data.buys} buys, {scan.data.exits} exits),{' '}
          {scan.data.executed} executed
          {scan.data.errors.length > 0 && `, ${scan.data.errors.length} errors`}.
        </div>
      )}
      {(create.error || toggle.error || remove.error || scan.error) && (
        <ErrorBox error={create.error ?? toggle.error ?? remove.error ?? scan.error} />
      )}

      {showForm && (
        <form
          className="card"
          style={{ marginBottom: '1.5rem' }}
          onSubmit={(event) => {
            event.preventDefault()
            const form = new FormData(event.currentTarget)
            const symbols = String(form.get('symbols') ?? '')
              .split(',')
              .map((s) => s.trim().toUpperCase())
              .filter(Boolean)
            create.mutate({
              name: String(form.get('name')),
              strategy_type: String(form.get('strategy_type')),
              description: String(form.get('description') || ''),
              symbols,
              params: {},
            })
          }}
        >
          <h2>New strategy</h2>
          <div className="grid" style={{ marginBottom: '0.8rem' }}>
            <label>
              <div className="stat-label">Name</div>
              <input name="name" required placeholder="ML Swing — large caps" />
            </label>
            <label>
              <div className="stat-label">Type</div>
              <select name="strategy_type" required>
                {types.data?.map((t) => (
                  <option key={t.strategy_type} value={t.strategy_type}>
                    {t.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <div className="stat-label">Symbols (blank = whole watchlist)</div>
              <input name="symbols" placeholder="INFY, TCS, RELIANCE" />
            </label>
            <label>
              <div className="stat-label">Description</div>
              <input name="description" placeholder="Optional" />
            </label>
          </div>
          <button className="primary" type="submit" disabled={create.isPending}>
            {create.isPending ? 'Creating…' : 'Create'}
          </button>
          <p className="muted" style={{ fontSize: '0.82rem' }}>
            New strategies start inactive. Review the parameters, then activate.
          </p>
        </form>
      )}

      <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
        {!rows.length ? (
          <Empty label="No strategies yet. Create one to start generating signals." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Mode</th>
                <th>Symbols</th>
                <th>Status</th>
                <th>Created</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id}>
                  <td>
                    <strong>{s.name}</strong>
                    {s.description && (
                      <div className="muted" style={{ fontSize: '0.75rem' }}>
                        {s.description}
                      </div>
                    )}
                  </td>
                  <td className="muted">{s.strategy_type}</td>
                  <td>
                    <span className={`badge ${s.mode === 'live' ? 'badge-live' : 'badge-paper'}`}>
                      {s.mode}
                    </span>
                  </td>
                  <td className="muted">
                    {s.symbols.length ? s.symbols.join(', ') : 'watchlist'}
                  </td>
                  <td>
                    <span className={`badge ${s.is_active ? 'badge-on' : 'badge-off'}`}>
                      {s.is_active ? 'active' : 'inactive'}
                    </span>
                  </td>
                  <td className="muted">{formatDate(s.created_at)}</td>
                  <td>
                    <div className="row">
                      <button
                        onClick={() => toggle.mutate({ id: s.id, active: s.is_active })}
                        disabled={toggle.isPending}
                      >
                        {s.is_active ? 'Deactivate' : 'Activate'}
                      </button>
                      {!s.is_active && (
                        <button
                          className="danger"
                          onClick={() => confirm(`Delete "${s.name}"?`) && remove.mutate(s.id)}
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <h2>Available strategy types</h2>
      <div className="grid">
        {types.data?.map((t) => (
          <div className="card" key={t.strategy_type}>
            <div className="stat-label">{t.strategy_type}</div>
            <div style={{ fontWeight: 600, marginBottom: '0.35rem' }}>{t.display_name}</div>
            <p className="muted" style={{ fontSize: '0.82rem', margin: 0 }}>
              {t.description}
            </p>
          </div>
        ))}
      </div>
    </>
  )
}
