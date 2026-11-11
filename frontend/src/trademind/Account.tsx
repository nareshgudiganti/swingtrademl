// "Account and plan": who you are, whether you are on Free or Pro, how to upgrade, and how to stop.
// The wording and which buttons show come from lib/billingRules.ts. Money is handled by Razorpay's own
// window (test mode only for now): this page never sees a card number. The server decides who is on Pro.
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, api } from '../api/client'
import type { BillingCheckout, BillingMe, BillingPlans } from '../api/types'
import { PRO_FEATURES_FALLBACK, accountView, billingErrorText, formatDate, proPriceLine } from '../lib/billingRules'
import { Confirm } from './Confirm'
import DeleteAccount from './DeleteAccount'
import { QueryState } from './PageState'

const CHECKOUT_JS = 'https://checkout.razorpay.com/v1/checkout.js'

type RazorpayWindow = Window & {
  Razorpay?: new (opts: Record<string, unknown>) => { open: () => void }
}

function loadCheckoutScript(): Promise<void> {
  const w = window as RazorpayWindow
  if (w.Razorpay) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = CHECKOUT_JS
    s.onload = () => resolve()
    s.onerror = () => reject(new Error('The payment window could not load. Check your connection and try again.'))
    document.body.appendChild(s)
  })
}

function errText(err: unknown): string {
  if (err instanceof ApiError) return billingErrorText(err.status, err.message)
  if (err instanceof Error) return err.message
  return 'Something went wrong. Please try again.'
}

export default function Account() {
  const qc = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })
  const plans = useQuery({ queryKey: ['billing-plans'], queryFn: api.billingPlans, retry: false })
  const billing = useQuery({
    queryKey: ['billing-me'],
    queryFn: api.billingMe,
    retry: false,
    // While a payment is being confirmed, check again every few seconds (the provider tells the server first).
    refetchInterval: (q) => (q.state.data && accountView(q.state.data, plans.data).state === 'confirming' ? 4000 : false),
  })
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmCancel, setConfirmCancel] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const lastCheckout = useRef<string | null>(null)

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['billing-me'] })
    void qc.invalidateQueries({ queryKey: ['my-plan'] })
    void qc.invalidateQueries({ queryKey: ['me'] })
  }

  const upgrade = useMutation({
    mutationFn: api.billingCheckout,
    onMutate: () => {
      setError(null)
      setNotice(null)
    },
    onSuccess: async (info: BillingCheckout) => {
      lastCheckout.current = info.completion_token
      refresh()
      if (info.key_id) {
        try {
          await loadCheckoutScript()
          const Razorpay = (window as RazorpayWindow).Razorpay
          if (!Razorpay) throw new Error('The payment window could not load. Please try again.')
          new Razorpay({
            key: info.key_id,
            subscription_id: info.subscription_id,
            name: 'TradeMind Pro',
            description: 'Monthly plan (test mode)',
            handler: () => {
              setWaiting(true)
              setNotice('Payment sent. We are confirming it now. This page will update by itself.')
              refresh()
            },
            modal: { ondismiss: () => refresh() },
          }).open()
        } catch (err) {
          setError(errText(err))
        }
      } else if (info.completion_token) {
        setNotice('Test mode: the payment is waiting. Press “Complete the test payment” below.')
      }
    },
    onError: (err) => setError(errText(err)),
  })

  const fakePay = useMutation({
    mutationFn: (subscriptionId: string) => api.billingFakePay(subscriptionId),
    onSuccess: () => {
      setNotice('Test payment complete.')
      refresh()
    },
    onError: (err) => setError(errText(err)),
  })

  const cancel = async () => {
    try {
      await api.billingCancel(true)
    } catch (err) {
      throw new Error(errText(err))
    }
    setNotice('Done. You will not be charged again.')
    refresh()
  }

  const paidThrough = formatDate(billing.data?.subscription?.paid_through)

  return (
    <div className="tm-page" data-testid="account-page">
      <div className="tm-page-head">
        <h1>Account and plan</h1>
        <p>Your sign-in details and your plan.</p>
      </div>

      <QueryState q={me} what="your account">
        {(user) => (
          <div className="tm-card" data-testid="account-details">
            <div className="tm-card-head">
              <span className="tm-card-title">You</span>
            </div>
            <p className="tm-strong">{user.email ?? user.username}</p>
            <p className="tm-dim">
              {user.email ? `Sign-in name: ${user.username}. ` : ''}
              {user.auth_provider === 'google' ? 'You sign in with Google.' : 'You sign in with your email and password.'}
            </p>
          </div>
        )}
      </QueryState>

      <QueryState
        q={billing}
        what="your plan"
        errorTitle="We could not load your plan."
        notFound="Plans and billing are not open yet. Everything you can use today is already on your account."
      >
        {(b: BillingMe) => (
          <PlanCard
            billing={b}
            plans={plans.data}
            busy={upgrade.isPending || fakePay.isPending}
            notice={notice}
            error={error}
            onUpgrade={() => upgrade.mutate()}
            onCancel={() => setConfirmCancel(true)}
            pendingToken={lastCheckout.current}
            onFakePay={(token) => fakePay.mutate(token)}
            waiting={waiting}
          />
        )}
      </QueryState>

      {me.data && <DeleteAccount usesPassword={me.data.auth_provider !== 'google'} />}

      {confirmCancel && (
        <Confirm
          title="Stop Pro?"
          confirmLabel="Yes, stop at the end of this period"
          danger
          onConfirm={cancel}
          onClose={() => setConfirmCancel(false)}
        >
          <p>
            You will not be charged again. You keep Pro until the end of the period you already paid for
            {paidThrough ? `, ${paidThrough}` : ''}. After that your account goes back to Free.
          </p>
        </Confirm>
      )}
    </div>
  )
}

function PlanCard({
  billing,
  plans,
  busy,
  notice,
  error,
  onUpgrade,
  onCancel,
  pendingToken,
  onFakePay,
  waiting,
}: {
  billing: BillingMe
  plans: BillingPlans | undefined
  busy: boolean
  notice: string | null
  error: string | null
  onUpgrade: () => void
  onCancel: () => void
  pendingToken: string | null
  onFakePay: (token: string) => void
  waiting: boolean
}) {
  const view = accountView(billing, plans)
  const price = proPriceLine(plans)
  const showUpgrade = view.state === 'free' || view.state === 'ended'
  return (
    <div
      className={`tm-card ${view.state.startsWith('pro') ? 'tm-glow-green' : ''}`}
      data-testid="plan-card"
      data-state={view.state}
    >
      <div className="tm-card-head">
        <span className="tm-card-title">Your plan</span>
        {billing.sandbox && (
          <span className="tm-card-sub" data-testid="test-mode">
            Test mode: no real money
          </span>
        )}
      </div>
      <p className="tm-strong" data-testid="plan-headline">
        {view.headline}
      </p>
      <p className="tm-dim">{view.detail}</p>
      {waiting && view.state === 'confirming' && <p className="tm-dim">Thank you. Confirming…</p>}

      {showUpgrade && (
        <div data-testid="upgrade-card">
          <p className="tm-strong">Pro{price ? `: ${price}` : ''}</p>
          <ul>
            {PRO_FEATURES_FALLBACK.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
          <button type="button" className="tm-btn" disabled={busy || !view.canUpgrade} onClick={onUpgrade}>
            {busy ? 'Please wait…' : 'Upgrade to Pro'}
          </button>
          <p className="tm-dim">You can stop at any time. You keep Pro until the end of the period you paid for.</p>
        </div>
      )}

      {pendingToken && billing.provider === 'fake' && view.state !== 'pro' && (
        <button type="button" className="tm-btn tm-btn-ghost" disabled={busy} onClick={() => onFakePay(pendingToken)}>
          Complete the test payment
        </button>
      )}

      {view.canCancel && (
        <button type="button" className="tm-btn tm-btn-ghost" onClick={onCancel} data-testid="cancel-pro">
          Stop Pro
        </button>
      )}

      {notice && (
        <p className="tm-dim" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="tm-state-error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
