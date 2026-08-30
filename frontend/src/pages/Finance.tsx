import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import Modal from '../components/Modal'
import Stat from '../components/Stat'
import type { FinanceFilters, FinanceIngestedFile, FinanceLoan } from '../api/types'
import { calculateEmi } from '../lib/loans'
import { formatCurrency, formatDate } from '../lib/format'

const TABS = [
  { key: 'statement', label: 'Statement' },
  { key: 'transactions', label: 'Transactions' },
  { key: 'calculation', label: 'Calculation' },
  { key: 'analysis', label: 'Analysis' },
  { key: 'loans', label: 'Loans' },
] as const
type TabKey = (typeof TABS)[number]['key']

export default function Finance() {
  const [tab, setTab] = useState<TabKey>('statement')
  const [filters, setFilters] = useState<FinanceFilters>({})

  const categoryList = useQuery({ queryKey: ['financeCategoryList'], queryFn: api.financeCategories })
  const monthlyAll = useQuery({ queryKey: ['financeMonthlyAll'], queryFn: () => api.financeMonthlySummary() })

  const showFilterBar = tab === 'transactions' || tab === 'calculation' || tab === 'analysis'

  return (
    <>
      <div className="page-head">
        <h1>Finance</h1>
      </div>

      <div className="tier-tabs">
        {TABS.map((t) => (
          <button key={t.key} className={`tier-tab ${tab === t.key ? 'active' : ''}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {showFilterBar && (
        <FilterBar
          filters={filters}
          onChange={setFilters}
          months={(monthlyAll.data ?? []).map((m) => m.month)}
          categories={categoryList.data ?? []}
        />
      )}

      {tab === 'statement' && <StatementTab />}
      {tab === 'transactions' && <TransactionsTab filters={filters} categoryList={categoryList.data ?? []} />}
      {tab === 'calculation' && <CalculationTab filters={filters} />}
      {tab === 'analysis' && <AnalysisTab filters={filters} />}
      {tab === 'loans' && <LoansTab />}
    </>
  )
}

// ------------------------------------------------------------- filter bar --

function FilterBar({
  filters,
  onChange,
  months,
  categories,
}: {
  filters: FinanceFilters
  onChange: (f: FinanceFilters) => void
  months: string[]
  categories: string[]
}) {
  return (
    <div className="row" style={{ gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
      <select
        value={filters.month ?? ''}
        onChange={(e) => onChange({ ...filters, month: e.target.value || undefined })}
      >
        <option value="">All months</option>
        {months.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
      <select
        value={filters.category ?? ''}
        onChange={(e) => onChange({ ...filters, category: e.target.value || undefined })}
      >
        <option value="">All categories</option>
        {categories.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
      <select
        value={filters.direction ?? ''}
        onChange={(e) => onChange({ ...filters, direction: e.target.value || undefined })}
      >
        <option value="">All directions</option>
        <option value="DEBIT">Debit</option>
        <option value="CREDIT">Credit</option>
      </select>
      {(filters.month || filters.category || filters.direction) && (
        <button onClick={() => onChange({})}>Clear filters</button>
      )}
    </div>
  )
}

// -------------------------------------------------------------- statement --

function StatementTab() {
  const queryClient = useQueryClient()
  const [uploadResult, setUploadResult] = useState<string | null>(null)
  const [showDeleted, setShowDeleted] = useState(false)
  const [permanentTarget, setPermanentTarget] = useState<FinanceIngestedFile | null>(null)

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['financeStatements'] })
    queryClient.invalidateQueries({ queryKey: ['financeDeletedStatements'] })
    queryClient.invalidateQueries({ queryKey: ['financeTransactions'] })
    queryClient.invalidateQueries({ queryKey: ['financeMonthlyAll'] })
    queryClient.invalidateQueries({ queryKey: ['financeCategorySummary'] })
    queryClient.invalidateQueries({ queryKey: ['financeMerchants'] })
    queryClient.invalidateQueries({ queryKey: ['financeInsights'] })
    queryClient.invalidateQueries({ queryKey: ['financeCalculation'] })
    queryClient.invalidateQueries({ queryKey: ['financeCategoryList'] })
  }

  const statements = useQuery({ queryKey: ['financeStatements'], queryFn: api.financeStatements })
  const deletedStatements = useQuery({
    queryKey: ['financeDeletedStatements'],
    queryFn: api.financeDeletedStatements,
    enabled: showDeleted,
  })

  const upload = useMutation({
    mutationFn: ({ file, password }: { file: File; password: string }) =>
      api.uploadFinanceStatement(file, password || undefined),
    onSuccess: (result) => {
      setUploadResult(result.message)
      invalidateAll()
    },
    onError: (error: unknown) => setUploadResult(error instanceof Error ? error.message : String(error)),
  })

  const softDelete = useMutation({
    mutationFn: (id: number) => api.deleteFinanceStatement(id),
    onSuccess: invalidateAll,
  })

  const restore = useMutation({
    mutationFn: (id: number) => api.restoreFinanceStatement(id),
    onSuccess: invalidateAll,
  })

  const permanentDelete = useMutation({
    mutationFn: ({ id, filename }: { id: number; filename: string }) =>
      api.permanentlyDeleteFinanceStatement(id, filename),
    onSuccess: () => {
      setPermanentTarget(null)
      invalidateAll()
    },
  })

  return (
    <>
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

      <h2>Statements</h2>
      <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
        {!statements.data?.length ? (
          <Empty label="No statements uploaded yet." />
        ) : (
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
                    <button onClick={() => softDelete.mutate(s.id)} disabled={softDelete.isPending}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <button onClick={() => setShowDeleted((v) => !v)}>
        {showDeleted ? 'Hide' : 'Show'} recently deleted
      </button>

      {showDeleted && (
        <div className="table-wrap" style={{ marginTop: '0.8rem' }}>
          {deletedStatements.isLoading ? (
            <Loading />
          ) : !deletedStatements.data?.length ? (
            <Empty label="Nothing in Recently Deleted." />
          ) : (
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th className="num">Transactions</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {deletedStatements.data.map((s) => (
                  <tr key={s.id}>
                    <td>{s.file_name}</td>
                    <td className="num">{s.transaction_count}</td>
                    <td>
                      <button onClick={() => restore.mutate(s.id)} disabled={restore.isPending}>
                        Restore
                      </button>{' '}
                      <button onClick={() => setPermanentTarget(s)}>Delete permanently</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {permanentTarget && (
        <PermanentDeleteModal
          statement={permanentTarget}
          onClose={() => setPermanentTarget(null)}
          onConfirm={(filename) => permanentDelete.mutate({ id: permanentTarget.id, filename })}
          pending={permanentDelete.isPending}
          error={permanentDelete.error instanceof Error ? permanentDelete.error.message : null}
        />
      )}
    </>
  )
}

function PermanentDeleteModal({
  statement,
  onClose,
  onConfirm,
  pending,
  error,
}: {
  statement: FinanceIngestedFile
  onClose: () => void
  onConfirm: (filename: string) => void
  pending: boolean
  error: string | null
}) {
  const [typed, setTyped] = useState('')
  const matches = typed === statement.file_name

  return (
    <Modal onClose={onClose}>
      <h2>Delete permanently</h2>
      <p>
        This cannot be undone. Type the file name <strong>{statement.file_name}</strong> to confirm deleting it and
        its {statement.transaction_count} transaction(s) for good.
      </p>
      <input
        value={typed}
        onChange={(e) => setTyped(e.target.value)}
        placeholder={statement.file_name}
        style={{ marginBottom: '0.8rem' }}
      />
      <button disabled={!matches || pending} onClick={() => onConfirm(typed)}>
        {pending ? 'Deleting…' : 'Delete permanently'}
      </button>
      {error && (
        <p className="muted" style={{ fontSize: '0.82rem', marginTop: '0.6rem' }}>
          {error}
        </p>
      )}
    </Modal>
  )
}

// ---------------------------------------------------------- transactions --

function TransactionsTab({ filters, categoryList }: { filters: FinanceFilters; categoryList: string[] }) {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')

  const transactions = useQuery({
    queryKey: ['financeTransactions', filters, search],
    queryFn: () => api.financeTransactions({ ...filters, search: search || undefined }),
  })

  const recategorize = useMutation({
    mutationFn: ({ id, category }: { id: number; category: string }) =>
      api.recategorizeFinanceTransaction(id, category),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['financeTransactions'] }),
  })

  return (
    <>
      <div className="row" style={{ gap: '0.5rem', marginBottom: '0.8rem', flexWrap: 'wrap' }}>
        <input placeholder="Search description…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      {!filters.category && (
        <p className="muted" style={{ fontSize: '0.82rem' }}>
          Internal transfers (sweeps) are hidden by default — filter by category "Internal Transfer" to see them.
        </p>
      )}

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
                  <td>
                    {t.description}
                    {t.is_reference_only && (
                      <span className="muted" style={{ fontSize: '0.72rem', marginLeft: '0.4rem' }}>
                        (reference only — counted from another statement)
                      </span>
                    )}
                  </td>
                  <td className={`num ${t.direction === 'CREDIT' ? 'pos' : ''}`}>{formatCurrency(t.amount)}</td>
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
                      {categoryList
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

// ---------------------------------------------------------- calculation --

function CalculationTab({ filters }: { filters: FinanceFilters }) {
  const calculation = useQuery({
    queryKey: ['financeCalculation', filters],
    queryFn: () => api.financeCalculation(filters),
  })

  if (calculation.isLoading) return <Loading />
  if (calculation.error) return <ErrorBox error={calculation.error} />

  const c = calculation.data!

  return (
    <div className="grid">
      <Stat label="Total debits" value={formatCurrency(c.total_debits)} />
      <Stat label="Total credits" value={formatCurrency(c.total_credits)} tone={c.total_credits > 0 ? 'pos' : 'flat'} />
      <Stat label="Net" value={formatCurrency(c.net)} tone={c.net >= 0 ? 'pos' : 'neg'} />
      <Stat label="Transactions" value={c.transaction_count} />
    </div>
  )
}

// -------------------------------------------------------------- analysis --

function AnalysisTab({ filters }: { filters: FinanceFilters }) {
  const categories = useQuery({
    queryKey: ['financeCategorySummary', filters.month, filters.direction],
    queryFn: () => api.financeCategorySummary({ month: filters.month, direction: filters.direction }),
  })
  const merchants = useQuery({
    queryKey: ['financeMerchants', filters],
    queryFn: () => api.financeMerchants(filters, 15),
  })
  const insights = useQuery({ queryKey: ['financeInsights', filters], queryFn: () => api.financeInsights(filters) })

  if (categories.isLoading) return <Loading />
  if (categories.error) return <ErrorBox error={categories.error} />

  const categoryRows = filters.category
    ? (categories.data ?? []).filter((c) => c.category === filters.category)
    : categories.data ?? []

  return (
    <>
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

      <h2>Spend by category</h2>
      <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
        {!categoryRows.length ? (
          <Empty label="No categorised expenses in this view." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Category</th>
                <th className="num">Total</th>
                <th className="num">Transactions</th>
                <th className="num">Avg</th>
              </tr>
            </thead>
            <tbody>
              {categoryRows.map((c) => (
                <tr key={c.category}>
                  <td>{c.category}</td>
                  <td className="num">{formatCurrency(c.total_expense)}</td>
                  <td className="num">{c.transaction_count}</td>
                  <td className="num">{formatCurrency(c.avg_transaction)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <h2>Top merchants</h2>
      <div className="table-wrap">
        {!merchants.data?.length ? (
          <Empty label="No merchant data in this view." />
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
    </>
  )
}

// ---------------------------------------------------------------- loans --

interface LoanFormState {
  account_number: string
  name: string
  principal: string
  annual_rate: string
  tenure_months: string
  emi: string
  extra_payment: string
  start_date: string
}

const emptyLoanForm: LoanFormState = {
  account_number: '',
  name: '',
  principal: '',
  annual_rate: '',
  tenure_months: '',
  emi: '',
  extra_payment: '0',
  start_date: new Date().toISOString().slice(0, 10),
}

function LoansTab() {
  const queryClient = useQueryClient()
  const [modalOpen, setModalOpen] = useState(false)
  const [editingLoan, setEditingLoan] = useState<FinanceLoan | null>(null)
  const [form, setForm] = useState<LoanFormState>(emptyLoanForm)
  const [emiTouched, setEmiTouched] = useState(false)

  const loans = useQuery({ queryKey: ['financeLoans'], queryFn: api.financeLoans })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['financeLoans'] })

  const create = useMutation({ mutationFn: api.createFinanceLoan, onSuccess: invalidate })
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => api.updateFinanceLoan(id, body),
    onSuccess: invalidate,
  })
  const remove = useMutation({ mutationFn: api.deleteFinanceLoan, onSuccess: invalidate })

  const suggestedEmi = calculateEmi(
    Number(form.principal) || 0,
    Number(form.annual_rate) || 0,
    Number(form.tenure_months) || 0,
  )

  function openCreate() {
    setEditingLoan(null)
    setForm(emptyLoanForm)
    setEmiTouched(false)
    setModalOpen(true)
  }

  function openEdit(loan: FinanceLoan) {
    setEditingLoan(loan)
    setForm({
      account_number: loan.account_number ?? '',
      name: loan.name,
      principal: String(loan.principal),
      annual_rate: String(loan.annual_rate),
      tenure_months: String(loan.tenure_months),
      emi: String(loan.emi),
      extra_payment: String(loan.extra_payment),
      start_date: loan.start_date.slice(0, 10),
    })
    setEmiTouched(true)
    setModalOpen(true)
  }

  function submit() {
    const body = {
      account_number: form.account_number || null,
      name: form.name,
      principal: Number(form.principal),
      annual_rate: Number(form.annual_rate),
      tenure_months: Number(form.tenure_months),
      emi: Number(form.emi) || suggestedEmi,
      extra_payment: Number(form.extra_payment) || 0,
      start_date: form.start_date,
    }
    if (editingLoan) {
      update.mutate({ id: editingLoan.id, body }, { onSuccess: () => setModalOpen(false) })
    } else {
      create.mutate(body, { onSuccess: () => setModalOpen(false) })
    }
  }

  const rows = loans.data ?? []
  const totals = rows.reduce(
    (acc, l) => ({
      principal: acc.principal + l.principal,
      outstanding: acc.outstanding + l.outstanding,
      emi: acc.emi + l.emi,
    }),
    { principal: 0, outstanding: 0, emi: 0 },
  )

  return (
    <>
      <div className="page-head">
        <h2 style={{ margin: 0 }}>Loans</h2>
        <button className="primary" onClick={openCreate}>
          Add loan
        </button>
      </div>

      {!!rows.length && (
        <div className="grid">
          <Stat label="Total principal" value={formatCurrency(totals.principal)} />
          <Stat label="Total outstanding" value={formatCurrency(totals.outstanding)} />
          <Stat label="Total monthly EMI" value={formatCurrency(totals.emi)} />
        </div>
      )}

      <div className="table-wrap">
        {loans.isLoading ? (
          <Loading />
        ) : !rows.length ? (
          <Empty label="No loans yet. Add one to track EMI and payoff progress." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Loan</th>
                <th>Account</th>
                <th className="num">Outstanding</th>
                <th className="num">Principal</th>
                <th className="num">ROI</th>
                <th className="num">EMI</th>
                <th>Est. closure</th>
                <th>Pending</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((loan) => (
                <tr key={loan.id}>
                  <td>
                    <strong>{loan.name}</strong>
                  </td>
                  <td className="muted">{loan.account_number || '—'}</td>
                  <td className="num">{formatCurrency(loan.outstanding)}</td>
                  <td className="num">{formatCurrency(loan.principal)}</td>
                  <td className="num">{loan.annual_rate.toFixed(2)}%</td>
                  <td className="num">{formatCurrency(loan.emi)}</td>
                  <td className="muted">{loan.estimated_close ? formatDate(loan.estimated_close) : '—'}</td>
                  <td className="muted">{loan.pending_label}</td>
                  <td>
                    <button onClick={() => openEdit(loan)}>Edit</button>{' '}
                    <button
                      onClick={() => {
                        if (confirm(`Delete loan "${loan.name}"?`)) remove.mutate(loan.id)
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {modalOpen && (
        <Modal onClose={() => setModalOpen(false)}>
          <h2>{editingLoan ? 'Edit loan' : 'Add loan'}</h2>
          <div className="grid" style={{ marginBottom: '0.8rem' }}>
            <label>
              <div className="stat-label">Loan name</div>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </label>
            <label>
              <div className="stat-label">Account number (optional)</div>
              <input
                value={form.account_number}
                onChange={(e) => setForm({ ...form, account_number: e.target.value })}
              />
            </label>
            <label>
              <div className="stat-label">Principal (₹)</div>
              <input
                type="number"
                min="0"
                value={form.principal}
                onChange={(e) => setForm({ ...form, principal: e.target.value })}
                required
              />
            </label>
            <label>
              <div className="stat-label">Annual interest rate (%)</div>
              <input
                type="number"
                min="0"
                step="0.01"
                value={form.annual_rate}
                onChange={(e) => setForm({ ...form, annual_rate: e.target.value })}
                required
              />
            </label>
            <label>
              <div className="stat-label">Tenure (months)</div>
              <input
                type="number"
                min="1"
                value={form.tenure_months}
                onChange={(e) => setForm({ ...form, tenure_months: e.target.value })}
                required
              />
            </label>
            <label>
              <div className="stat-label">
                EMI (₹) {!emiTouched && suggestedEmi > 0 && <span className="muted">— suggested {formatCurrency(suggestedEmi)}</span>}
              </div>
              <input
                type="number"
                min="0"
                value={form.emi || (suggestedEmi ? suggestedEmi.toFixed(2) : '')}
                onChange={(e) => {
                  setEmiTouched(true)
                  setForm({ ...form, emi: e.target.value })
                }}
              />
            </label>
            <label>
              <div className="stat-label">Extra monthly payment (₹, optional)</div>
              <input
                type="number"
                min="0"
                value={form.extra_payment}
                onChange={(e) => setForm({ ...form, extra_payment: e.target.value })}
              />
            </label>
            <label>
              <div className="stat-label">Start date</div>
              <input
                type="date"
                value={form.start_date}
                onChange={(e) => setForm({ ...form, start_date: e.target.value })}
                required
              />
            </label>
          </div>
          <button className="primary" onClick={submit} disabled={create.isPending || update.isPending}>
            {editingLoan ? 'Save changes' : 'Add loan'}
          </button>
        </Modal>
      )}
    </>
  )
}
