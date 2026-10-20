// The first-time tour (ux5): five short screens for someone new to the app. It opens by itself once per account
// (see tourRules.ts for how "seen" is kept), and the Help button in the top bar opens it again at any time.
// Every word explained here comes from the one glossary (vocab.ts) through <Term>/<WordTag>, and every number
// matches the code: +8% / -4% / half at +5% / 15 trading days (brain/modules/m08_decide/policy.py and
// core/config.py ML_*), practice mode wording (services/brain_golive/stage.py), Paper/Real strips (books.ts).
// The model score is described only as a ranking, never as a chance of winning.

import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode, Ref } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import './tour.css'
import { api, getToken } from '../api/client'
import { Term, WordTag } from './term'
import { HOLDING_WORDS, IDEA_WORDS, MARKET_LABEL, MARKET_MODES } from './vocab'
import { TOUR_STEP_COUNT, backStep, markTourSeen, nextStep, shouldAutoOpen, tourKeyAction, wrapFocus } from './tourRules'

export type TourAudience = {
  /** May open the real Zerodha page (owner console and REAL_ACCOUNT_USERS). Only then is that page named. */
  realAccount: boolean
}

type Step = { title: string; body: (a: TourAudience, go: () => void) => ReactNode }

/** A page to look at: a link that also closes the tour. */
function Go({ to, onGo, children }: { to: string; onGo: () => void; children: ReactNode }) {
  return (
    <Link to={to} className="tm-link" onClick={onGo}>
      {children}
    </Link>
  )
}

export const TOUR_STEPS: Step[] = [
  {
    title: 'What the words mean',
    body: () => (
      <>
        <p>The brain gives every stock one word. Tap any word, here or anywhere in the app, to see what it means.</p>
        <p className="tm-tour-label">For new ideas</p>
        <div className="tm-tour-words">
          {IDEA_WORDS.map((w) => (
            <WordTag key={w} word={w} />
          ))}
        </div>
        <p className="tm-tour-label">For stocks you hold</p>
        <div className="tm-tour-words">
          {HOLDING_WORDS.map((w) => (
            <WordTag key={w} word={w} />
          ))}
        </div>
        <p className="tm-tour-label">
          The <Term k="market_mode">market mode</Term> at the top of Today
        </p>
        <div className="tm-tour-words">
          {MARKET_MODES.map((m) => (
            <Term key={m} k={m}>
              {MARKET_LABEL[m]}
            </Term>
          ))}
        </div>
      </>
    ),
  },
  {
    title: 'Paper money and real money',
    body: (a) => (
      <>
        <p>
          <Term k="paper">Paper</Term> means practice money: nothing is really bought or sold. The bot trades on paper
          only.
        </p>
        {a.realAccount ? (
          <p>
            Your <Term k="real">real</Term> Zerodha account has its own page, My Zerodha (Real), under Portfolio.
            Actions on that page can place real orders.
          </p>
        ) : (
          <p>This account shows paper money only.</p>
        )}
        <p>
          Every money screen has a strip at the top that says Paper or Real. Paper and real figures are never added
          together.
        </p>
      </>
    ),
  },
  {
    title: 'What the brain does, and does not do',
    body: () => (
      <>
        <p>
          Once a day, after the market closes, the brain reads the market, ranks stocks and runs a safety check. The
          safety check can only say no or make a trade smaller.
        </p>
        <p>
          It is in practice mode: its ideas are recorded and scored, and it does not buy or sell anything by itself.
          Moving it on from practice is the owner&rsquo;s decision; nothing switches it on by itself.
        </p>
        <p>
          The <Term k="model_score">model score</Term> only ranks stocks against each other. It is not a chance of
          winning and not a promise of profit. Any trade can lose money.
        </p>
      </>
    ),
  },
  {
    title: 'The plan for every trade',
    body: () => (
      <>
        <ul className="tm-tour-list">
          <li>
            <Term k="target">Target</Term>: sell at 8% above the buy price.
          </li>
          <li>
            <Term k="stop_loss">Stop-loss</Term>: sell at 4% below the buy price, to keep a bad trade small.
          </li>
          <li>
            <Term k="half_out">Sell half</Term> when the stock is up 5%, and keep the rest for the target.
          </li>
          <li>
            <Term k="horizon">Time limit</Term>: out within 15 trading days, about three weeks.
          </li>
        </ul>
        <p>These are the plan&rsquo;s limits, not a forecast. Many trades end at the stop-loss or the time limit.</p>
      </>
    ),
  },
  {
    title: 'Where to look each day',
    body: (a, go) => (
      <>
        <ul className="tm-tour-list">
          <li>
            <Go to="/trademind" onGo={go}>
              Today
            </Go>
            : the market mode, today&rsquo;s ideas and any holdings that need attention.
          </li>
          <li>
            Discover, then{' '}
            <Go to="/trademind/opportunities" onGo={go}>
              Opportunities
            </Go>
            : every idea with its word.
          </li>
          <li>
            Portfolio, then{' '}
            <Go to="/trademind/positions" onGo={go}>
              Bot (Paper)
            </Go>
            : what the bot holds on paper.
          </li>
          {a.realAccount && (
            <li>
              Portfolio, then{' '}
              <Go to="/trademind/holdings" onGo={go}>
                My Zerodha (Real)
              </Go>
              : your real shares.
            </li>
          )}
          <li>
            Insights, then{' '}
            <Go to="/trademind/records" onGo={go}>
              Records
            </Go>{' '}
            for finished trades, or{' '}
            <Go to="/trademind/learn" onGo={go}>
              Learn
            </Go>{' '}
            for every word explained.
          </li>
        </ul>
        <p>You can open this tour again at any time with Help at the top of the screen.</p>
      </>
    ),
  },
]

type ViewProps = {
  step: number
  audience: TourAudience
  id: string
  onNext: () => void
  onBack: () => void
  onClose: () => void
  onKeyDown?: (e: ReactKeyboardEvent<HTMLDivElement>) => void
  dialogRef?: Ref<HTMLDivElement>
}

/** One screen of the tour, without state, so it can be checked without a browser. */
export function TourView({ step, audience, id, onNext, onBack, onClose, onKeyDown, dialogRef }: ViewProps) {
  const s = TOUR_STEPS[step]!
  const last = step === TOUR_STEP_COUNT - 1
  return (
    <div
      ref={dialogRef}
      className="tm-dialog tm-tour"
      role="dialog"
      aria-modal="true"
      aria-labelledby={`${id}-title`}
      data-testid="tour"
      onKeyDown={onKeyDown}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="tm-tour-head">
        <p className="tm-tour-count" aria-live="polite">
          Step {step + 1} of {TOUR_STEP_COUNT}
        </p>
        <button type="button" className="tm-tour-close" aria-label="Close the tour" onClick={onClose}>
          ×
        </button>
      </div>
      <h2 className="tm-tour-title" id={`${id}-title`} tabIndex={-1}>
        {s.title}
      </h2>
      <div className="tm-tour-body">{s.body(audience, onClose)}</div>
      <div className="tm-tour-dots" aria-hidden="true">
        {TOUR_STEPS.map((t, i) => (
          <span key={t.title} className={i === step ? 'on' : ''} />
        ))}
      </div>
      <div className="tm-tour-foot">
        <button type="button" className="tm-btn tm-btn-ghost" onClick={onBack} disabled={step === 0}>
          Back
        </button>
        <button type="button" className="tm-btn" onClick={last ? onClose : onNext}>
          {last ? 'Done' : 'Next'}
        </button>
      </div>
    </div>
  )
}

const FOCUSABLE = 'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])'

/** The Help button for the top bar, plus the tour itself (opened by itself once per account). */
export function Tour({ realAccount }: TourAudience) {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, enabled: !!getToken(), retry: false })
  const username = me.data?.username
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState(0)
  const id = `tm-tour-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const helpRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const returnTo = useRef<HTMLElement | null>(null)

  const show = useCallback(() => {
    returnTo.current = (document.activeElement as HTMLElement | null) ?? null
    setStep(0)
    setOpen(true)
    if (username) markTourSeen(username)
  }, [username])

  // First visit for this account: open once by itself.
  useEffect(() => {
    if (shouldAutoOpen(username)) show()
  }, [username, show])

  const close = useCallback(() => {
    setOpen(false)
    const r = returnTo.current
    const back = r && r !== document.body && r.isConnected ? r : helpRef.current
    back?.focus()
  }, [])

  // Each screen starts at its title, so a screen reader reads it first.
  useEffect(() => {
    if (open) dialogRef.current?.querySelector<HTMLElement>('.tm-tour-title')?.focus()
  }, [open, step])

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Tab') {
      const root = dialogRef.current
      if (!root) return
      const items = [...root.querySelectorAll<HTMLElement>(FOCUSABLE)]
      const active = document.activeElement
      const at = items.indexOf(active as HTMLElement)
      // Focus on something inside that is not in the list (the title, an open word box): the browser moves it to
      // a neighbour that is still inside, so leave it alone.
      if (at === -1 && active && root.contains(active)) return
      const to = wrapFocus(at, items.length, e.shiftKey)
      if (to !== null) {
        e.preventDefault()
        items[to]?.focus()
      }
      return
    }
    const action = tourKeyAction(e.key)
    if (action === 'none') return
    e.preventDefault()
    if (action === 'close') close()
    else if (action === 'next') setStep((s) => nextStep(s))
    else setStep((s) => backStep(s))
  }

  return (
    <>
      <button
        ref={helpRef}
        type="button"
        className="tm-help"
        aria-haspopup="dialog"
        aria-expanded={open}
        title="A short tour of the app"
        onClick={show}
        data-testid="help"
      >
        Help
      </button>
      {open &&
        createPortal(
          <div className="tm tm-tour-layer">
            <div className="tm-dialog-backdrop" onClick={close}>
              <TourView
                step={step}
                audience={{ realAccount }}
                id={id}
                dialogRef={dialogRef}
                onKeyDown={onKeyDown}
                onNext={() => setStep((s) => nextStep(s))}
                onBack={() => setStep((s) => backStep(s))}
                onClose={close}
              />
            </div>
          </div>,
          document.body,
        )}
    </>
  )
}
