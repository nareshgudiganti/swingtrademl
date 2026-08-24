import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { api } from '../api/client'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import Stat from '../components/Stat'
import { formatCompact, formatCurrency, formatDate } from '../lib/format'

const ACCENT = '#4f8cff'

export default function Finance() {
  const queryClient = useQueryClient()
  const [uploadResult, setUploadResult] = useState<string | null>(null)
  const [filters, setFilters] = useState<{ month: string; category: string; direction: string; search: string }>({
    month: '',
    category: '',
    direction: '',
    search: '',
  })

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['financeStatements'] })
    queryClient.invalidateQueries({ queryKey: ['financeTransactions'] })
    queryClient.invalidateQueries({ queryKey: ['financeMonthly'] })
    queryClient.invalidateQueries({ queryKey: ['financeCategories'] })
    queryClient.invalidateQueries({ queryKey: ['financeMerchants'] })
    queryClient.invalidateQueries({ queryKey: ['financeInsights'] })
    queryClient.invalidateQueries({ queryKey: ['financeCategoryList'] })
  }

  const statements = useQuery({ queryKey: ['financeStatements'], queryFn: api.financeStatements })
  const monthly = useQuery({ queryKey: ['financeMonthly'], queryFn: api.financeMonthlySummary })
  const categories = useQuery({ queryKey: ['financeCategories'], queryFn: api.financeCategorySummary })
  const merchants = useQuery({ queryKey: ['financeMerchants'], queryFn: () => api.financeMerchants(10) })
  const insights = useQuery({ queryKey: ['financeInsights'], queryFn: api.financeInsights })
  const categoryList = useQuery({ queryKey: ['financeCategoryList'], queryFn: api.financeCategories })
  const transactions = useQuery({
    queryKey: ['financeTransactions', filters],
    queryFn: () =>
      api.financeTransactions({
        month: filters.month || undefined,
        category: filters.category || undefined,
        direction: filters.direction || undefined,
        search: filters.search || undefined,
      }),
  })

  const upload = useMutation({
    mutationFn: ({ file, password }: { file: File; password: string }) =>
      api.uploadFinanceStatement(file, password || undefined),
    onSuccess: (result) => {
      setUploadResult(result.message)
      invalidateAll()
    },
    onError: (error: unknown) => {
      setUploadResult(error instanceof Error ? error.message : String(error))
    },
  })

  const recategorize = useMutation({
    mutationFn: ({ id, category }: { id: number; category: string }) =>
      api.recategorizeFinanceTransaction(id, category),
    onSuccess: invalidateAll,
  })

  const deleteStatement = useMutation({
    mutationFn: (id: number) => api.deleteFinanceStatement(id),
    onSuccess: invalidateAll,
  })

  if (monthly.isLoading) return <Loading />
  if (monthly.error) return <ErrorBox error={monthly.error} />

  const monthlyRows = monthly.data ?? []
  const categoryRows = categories.data ?? []
  const currentMonth = monthlyRows[monthlyRows.length - 1]
  const avgMonthly = monthlyRows.length
    ? monthlyRows.reduce((sum, m) => sum + m.total_expense, 0) / monthlyRows.length
    : 0
  const topCategory = categoryRows[0]
  const uncategorised = categoryRows.find((c) => c.category === 'Uncategorised')

  return (
    <>
      <div className="page-head">
        <h1>Finance</h1>
      </div>

      <form
        className="card"
        style={{ marginBottom: '1.5rem' }}
        onSubmit={(event) => {
          event.preventDefault()
          const form = event.currentTarget
          const data = new FormData(form)
          const file = data.get('file') as File | null
          const password = String(data.get('password') || '')
          if (!file || file.size === 0) return
          upload.mutate({ file, password })
          form.reset()
        }}
      >
        <h2>Upload statement</h2>
        <div className="grid" style={{ marginBottom: '0.8rem' }}>
          <label>
            <div className="stat-label">Statement file (PhonePe PDF, ICICI PDF, or CSV)</div>
            <input type="file" name="file" accept=".pdf,.csv" required />
          </label>
          <label>
            <div className="stat-label">PDF password (if protected)</div>
            <input type="password" name="password" placeholder="Optional" />
          </label>
        </div>
        <button className="primary" type="submit" disabled={upload.isPending}>
          {upload.isPending ? 'Uploading…' : 'Upload'}
        </button>
        {uploadResult && (
          <p className="muted" style={{ fontSize: '0.82rem', marginTop: '0.6rem' }}>
            {uploadResult}
          </p>
        )}
      </form>

      {!!statements.data?.length && (
        <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Source</th>
                <th className="num">Transactions</th>
                <th>Imported</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {statements.data.map((s) => (
                <tr key={s.id}>
                  <td>{s.file_name}</td>
                  <td className="muted">{s.source_type}</td>
                  <td className="num">{s.transaction_count}</td>
                  <td className="muted">{formatDate(s.created_at)}</td>
                  <td>
                    <button
                      onClick={() => {
                        if (confirm(`Delete "${s.file_name}" and its transactions?`)) {
                          deleteStatement.mutate(s.id)
                        }
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid">
        <Stat
          label="This month's spend"
          value={currentMonth ? formatCurrency(currentMonth.total_expense) : '—'}
          sub={currentMonth ? `${currentMonth.transaction_count} transactions` : 'No data yet'}
        />
        <Stat label="Average monthly spend" value={formatCurrency(avgMonthly)} />
        <Stat
          label="Top category"
          value={topCategory ? topCategory.category : '—'}
          sub={topCategory ? formatCurrency(topCategory.total_expense) : undefined}
        />
        <Stat
          label="Uncategorised"
          value={uncategorised ? formatCurrency(uncategorised.total_expense) : formatCurrency(0)}
          sub={uncategorised ? `${uncategorised.transaction_count} transactions` : 'All categorised'}
          tone={uncategorised && uncategorised.total_expense > 0 ? 'neg' : 'flat'}
        />
      </div>

      {!!insights.data?.length && (
        <div className="card" style={{ marginBottom: '1.5rem' }}>
          <h2>Insights</h2>
          <ul style={{ margin: 0, paddingLeft: '1.2rem' }}>
            {insights.data.map((line, i) => (
              <li key={i} style={{ marginBottom: '0.3rem' }}>
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}

      <h2>Monthly spend</h2>
      <div className="card" style={{ height: 260, marginBottom: '1.5rem' }}>
        {!monthlyRows.length ? (
          <Empty label="No expense transactions yet — upload a statement above." />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={monthlyRows} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid stroke="#263352" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="month" stroke="#8b9bb4" fontSize={11} tickMargin={8} />
              <YAxis
                stroke="#8b9bb4"
                fontSize={11}
                width={70}
                tickFormatter={(v: number) => formatCompact(v)}
              />
              <Tooltip
                contentStyle={{ background: '#131c31', border: '1px solid #263352', borderRadius: 10 }}
                formatter={(v: number) => formatCurrency(v)}
              />
              <Bar dataKey="total_expense" fill={ACCENT} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <h2>Spend by category</h2>
      <div className="card" style={{ height: Math.max(260, categoryRows.length * 32), marginBottom: '1.5rem' }}>
        {!categoryRows.length ? (
          <Empty label="No categorised expenses yet." />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={categoryRows}
              layout="vertical"
              margin={{ top: 8, right: 24, bottom: 0, left: 8 }}
            >
              <CartesianGrid stroke="#263352" strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" stroke="#8b9bb4" fontSize={11} tickFormatter={(v: number) => formatCompact(v)} />
              <YAxis
                type="category"
                dataKey="category"
                stroke="#8b9bb4"
                fontSize={11}
                width={160}
              />
              <Tooltip
                contentStyle={{ background: '#131c31', border: '1px solid #263352', borderRadius: 10 }}
                formatter={(v: number) => formatCurrency(v)}
              />
              <Bar dataKey="total_expense" fill={ACCENT} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <h2>Top merchants</h2>
      <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
        {!merchants.data?.length ? (
          <Empty label="No merchant data yet." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Merchant / description</th>
                <th className="num">Total spend</th>
                <th className="num">Transactions</th>
              </tr>
            </thead>
            <tbody>
              {merchants.data.map((m, i) => (
                <tr key={i}>
                  <td>{m.description}</td>
                  <td className="num">{formatCurrency(m.total_expense)}</td>
                  <td className="num">{m.transaction_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <h2>Transactions</h2>
      <div className="row" style={{ gap: '0.5rem', marginBottom: '0.8rem', flexWrap: 'wrap' }}>
        <select value={filters.month} onChange={(e) => setFilters((f) => ({ ...f, month: e.target.value }))}>
          <option value="">All months</option>
          {monthlyRows.map((m) => (
            <option key={m.month} value={m.month}>
              {m.month}
            </option>
          ))}
        </select>
        <select
          value={filters.category}
          onChange={(e) => setFilters((f) => ({ ...f, category: e.target.value }))}
        >
          <option value="">All categories</option>
          {(categoryList.data ?? []).map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          value={filters.direction}
          onChange={(e) => setFilters((f) => ({ ...f, direction: e.target.value }))}
        >
          <option value="">All directions</option>
          <option value="DEBIT">Debit</option>
          <option value="CREDIT">Credit</option>
        </select>
        <input
          placeholder="Search description…"
          value={filters.search}
          onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))}
        />
      </div>

      <div className="table-wrap">
        {transactions.isLoading ? (
          <Loading />
        ) : !transactions.data?.length ? (
          <Empty label="No transactions match these filters." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Description</th>
                <th className="num">Amount</th>
                <th>Direction</th>
                <th>Category</th>
              </tr>
            </thead>
            <tbody>
              {transactions.data.map((t) => (
                <tr key={t.id}>
                  <td className="muted">{formatDate(t.txn_date)}</td>
                  <td>{t.description}</td>
                  <td className={`num ${t.direction === 'CREDIT' ? 'pos' : ''}`}>
                    {formatCurrency(t.amount)}
                  </td>
                  <td>
                    <span className={`badge ${t.direction === 'CREDIT' ? 'badge-buy' : 'badge-sell'}`}>
                      {t.direction}
                    </span>
                  </td>
                  <td>
                    <select
                      value={t.category}
                      onChange={(e) => recategorize.mutate({ id: t.id, category: e.target.value })}
                    >
                      <option value={t.category}>{t.category}</option>
                      {(categoryList.data ?? [])
                        .filter((c) => c !== t.category)
                        .map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                    </select>
                    {t.is_manual_override && (
                      <span className="muted" style={{ fontSize: '0.72rem', marginLeft: '0.4rem' }}>
                        edited
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
