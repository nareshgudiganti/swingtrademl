// oa8: the top bar's alerts bell and trading-stage chip. Display only.
//
// The bell lists what the brain really sent the owner (the brain_alerts table, via GET /brain/alerts), newest first.
// Opening it marks them seen in this browser only (bellRules.ts); nothing is written to the server.
// The chip shows the stage exactly as GET /brain/stage reports it: Practice, Approval or Auto.
// Both answers are owner-only on the server. When the server refuses (or the brain is off), that part is simply not
// drawn: no error, no empty box.

import { useEffect, useId, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { BrainAlertRecord, BrainStage } from '../api/types'
import { formatDateTime } from '../lib/format'
import { bellLabel, latestId, readSeen, stageChip, unseenCount, writeSeen } from './bellRules'
import './bell.css'

const KIND_WORD: Record<string, string> = { banner: 'Market mode', trade: 'New idea', holding: 'Your stock' }

function BellIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" />
      <path d="M10 20.5a2.2 2.2 0 0 0 4 0" />
    </svg>
  )
}

type ViewProps = {
  stage: BrainStage | undefined
  alerts: BrainAlertRecord[] | undefined
  seenId: number
  /** Called when the owner opens the bell (marks everything listed as seen). */
  onOpen?: () => void
  /** Tests only: draw the list already open. */
  initiallyOpen?: boolean
}

export function TopBarAlertsView({ stage, alerts, seenId, onOpen, initiallyOpen = false }: ViewProps) {
  const [open, setOpen] = useState(initiallyOpen)
  // What counted as new when the bell was opened, so the "new" marks stay while the list is on screen.
  const [shownSeen, setShownSeen] = useState(seenId)
  const wrap = useRef<HTMLDivElement>(null)
  const panelId = useId()

  useEffect(() => {
    if (!open) return
    const close = (e: Event) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  if (!stage && !alerts) return null
  const unseen = alerts ? unseenCount(alerts, seenId) : 0
  const chip = stage ? stageChip(stage.stage) : null
  const markSeen = open ? shownSeen : seenId

  return (
    <>
      {stage && chip && (
        <span className="tm-stage-chip" data-testid="stage-chip" data-stage={stage.stage} title={stage.plain || chip.explain}>
          <span className="tm-sr-only">Trading stage: </span>
          {chip.label}
        </span>
      )}
      {alerts && (
        <div className="tm-bell" ref={wrap}>
          <button
            type="button"
            className="tm-bell-btn"
            data-testid="alerts-bell"
            aria-label={bellLabel(unseen)}
            title={bellLabel(unseen)}
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => {
              if (!open) {
                setShownSeen(seenId)
                onOpen?.()
              }
              setOpen((o) => !o)
            }}
          >
            <BellIcon />
            {unseen > 0 && (
              <span className="tm-bell-count" aria-hidden="true">
                {unseen > 9 ? '9+' : unseen}
              </span>
            )}
          </button>
          {open && (
            <div className="tm-bell-panel" id={panelId} role="region" aria-label="Recent alerts" data-testid="alerts-panel">
              <div className="tm-bell-head">
                <strong>Recent alerts</strong>
                <span>What the brain told you</span>
                {chip && (
                  <span className="tm-bell-stage" data-testid="bell-stage">
                    {`Trading stage: ${chip.label}`}
                  </span>
                )}
              </div>
              {alerts.length === 0 ? (
                <p className="tm-bell-empty">No alerts yet. The brain sends one when something changes.</p>
              ) : (
                <ul className="tm-bell-list">
                  {alerts.map((a) => {
                    const isNew = a.id > markSeen
                    return (
                      <li key={a.id} data-new={isNew ? 'true' : undefined} className={isNew ? 'tm-bell-new' : ''}>
                        <span className="tm-bell-meta">
                          {KIND_WORD[a.kind] ?? 'Alert'} · {formatDateTime(a.sent_at)}
                          {isNew && <span className="tm-bell-newtag"> · New</span>}
                        </span>
                        <span className="tm-bell-text">{a.text}</span>
                      </li>
                    )
                  })}
                </ul>
              )}
              <Link to="/trademind/alerts" className="tm-bell-foot" onClick={() => setOpen(false)}>
                Choose which alerts you get
              </Link>
            </div>
          )}
        </div>
      )}
    </>
  )
}

/** Owner's top bar: asks the server, shows only what it answered. */
export default function TopBarAlerts() {
  // Same key as the Go-live page, so both always show the same stage. No retries: a refusal just hides the chip.
  const stage = useQuery({ queryKey: ['brainStage'], queryFn: api.brainStage, retry: false })
  const alerts = useQuery({
    queryKey: ['brainAlertsRecent'],
    queryFn: () => api.brainAlerts(20),
    retry: false,
    refetchInterval: 5 * 60_000,
  })
  const [seenId, setSeenId] = useState(() => readSeen())
  const list = alerts.data

  return (
    <TopBarAlertsView
      stage={stage.isError ? undefined : stage.data}
      alerts={alerts.isError ? undefined : list}
      seenId={seenId}
      onOpen={() => {
        if (!list) return
        const newest = latestId(list)
        writeSeen(newest)
        setSeenId((s) => Math.max(s, newest))
      }}
    />
  )
}
