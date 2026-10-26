import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import { Card, inr } from './ui'

const REFRESH = ['summary', 'equityCurve', 'positions', 'riskLimits', 'capitalAdded']

/** Paper money only: adds practice cash and keeps it out of the profit figures. */
export default function AddMoneyCard() {
  const queryClient = useQueryClient()
  const [amount, setAmount] = useState('')
  const added = useQuery({ queryKey: ['capitalAdded'], queryFn: api.capitalAdded })

  const add = useMutation({
    mutationFn: () => api.addCapital(Number(amount)),
    onSuccess: () => {
      setAmount('')
      for (const key of REFRESH) queryClient.invalidateQueries({ queryKey: [key] })
    },
  })

  const value = Number(amount)
  const rows = added.data?.added ?? []

  return (
    <Card
      title="Add practice money"
      sub="Paper account only. Money you add is never counted as profit, so your percentages stay honest."
    >
      <form
        className="tm-flex tm-wrap"
        style={{ gap: '0.5rem', alignItems: 'center' }}
        onSubmit={(e) => {
          e.preventDefault()
          if (confirm(`Add ₹${inr(value, 0)} of practice money to the paper account?`)) add.mutate()
        }}
      >
        <input
          className="tm-input"
          type="number"
          min={1}
          inputMode="numeric"
          placeholder="Amount in ₹, e.g. 4000000"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          aria-label="Amount to add in rupees"
          style={{ width: 220 }}
        />
        <button className="tm-btn" disabled={!(value > 0) || add.isPending}>
          {add.isPending ? 'Adding…' : 'Add money'}
        </button>
      </form>
      {add.isError && <p className="tm-neg">Could not add that money. {(add.error as Error).message}</p>}
      {add.isSuccess && (
        <p className="tm-dim">
          Added ₹{inr(add.data.added, 0)}. The account is now worth ₹{inr(add.data.account_value, 0)}.
        </p>
      )}
      {added.data && (
        <div className="tm-rows" style={{ marginTop: '0.6rem' }}>
          <div className="tm-row">
            <span className="tm-dim">First funding</span>
            <span className="tm-strong">₹{inr(added.data.starting_capital, 0)}</span>
          </div>
          {rows.map((r) => (
            <div key={r.at} className="tm-row">
              <span className="tm-dim">
                Added on {new Date(r.at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}
              </span>
              <span className="tm-strong">₹{inr(r.amount, 0)}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}
