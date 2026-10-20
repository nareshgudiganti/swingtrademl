// Admin > Alerts (tracker ux3): which Telegram messages reach the owner's phone, quiet hours and a daily digest.
// Owner only. Everyday messages can be switched off or held back; sells, real-money orders, safety stops, login and
// system problems are always sent at once and are shown here as "Always on" with the reason.
// These settings only decide whether and when a message is sent. They never change what the bot buys or sells.

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, api } from '../../api/client'
import { draftFrom, heldText, isOn, problem, quietText, sameDraft, toggle } from '../alerts'
import type { AlertSettings, AlertSettingsUpdate } from '../alerts'
import { QueryState } from '../PageState'
import { Term } from '../term'
import { Card, PageHead, Tag } from '../ui'

function saveError(err: unknown): string {
  if (err instanceof ApiError && err.status === 422) return err.message
  if (err instanceof ApiError && (err.status === 401 || err.status === 403)) return 'Only the owner can change alerts.'
  return 'Could not save. Check your internet and try again.'
}

export function AlertsForm({ data }: { data: AlertSettings }) {
  const queryClient = useQueryClient()
  const original = draftFrom(data)
  const [draft, setDraft] = useState<AlertSettingsUpdate>(original)
  const [saved, setSaved] = useState(false)
  const save = useMutation({
    mutationFn: (body: AlertSettingsUpdate) => api.saveAlertSettings(body),
    onSuccess: (next) => {
      queryClient.setQueryData(['alert-settings'], next)
      setDraft(draftFrom(next))
      setSaved(true)
    },
  })

  const edit = (next: AlertSettingsUpdate) => {
    setDraft(next)
    setSaved(false)
  }
  const issue = problem(draft)
  const changed = !sameDraft(draft, original)
  const held = heldText(data.held)

  return (
    <>
      <Card
        title="Messages you can switch off"
        sub="Everyday news. Switching one off only stops the phone message; everything still shows in the app."
      >
        <div className="tm-rows" data-testid="alerts-switchable">
          {data.switchable.map((t) => {
            const on = isOn(draft, t.key)
            const id = `alert-${t.key}`
            return (
              <div className="tm-alert-row" key={t.key} data-alert={t.key}>
                <div className="tm-between">
                  <label className="tm-alert-toggle" htmlFor={id}>
                    <input
                      id={id}
                      type="checkbox"
                      checked={on}
                      onChange={(e) => edit(toggle(draft, t.key, e.target.checked))}
                    />
                    <span className="tm-strong">{t.label}</span>
                  </label>
                  <Tag tone={on ? 'green' : 'amber'}>{on ? 'On' : 'Off'}</Tag>
                </div>
                <details className="tm-alert-why">
                  <summary>What is this?</summary>
                  <p className="tm-dim">{t.explain}</p>
                </details>
              </div>
            )
          })}
        </div>
      </Card>

      <Card title="Always on" sub="These can't be switched off or held back, because you may need to act on them.">
        <div className="tm-rows" data-testid="alerts-always-on">
          {data.always_on.map((t) => (
            <div className="tm-alert-row" key={t.key} data-alert={t.key}>
              <div className="tm-between">
                <span className="tm-strong">{t.label}</span>
                <Tag tone="blue">Always on</Tag>
              </div>
              <p className="tm-dim tm-alert-reason">{t.explain}</p>
            </div>
          ))}
        </div>
      </Card>

      <div className="tm-grid tm-cols-2">
        <Card
          title={<Term k="quiet_hours">Quiet hours</Term>}
          sub="Everyday messages wait during this time and are sent together when it ends. India time (IST)."
        >
          <label className="tm-alert-toggle" htmlFor="alert-quiet">
            <input
              id="alert-quiet"
              type="checkbox"
              checked={draft.quiet_enabled}
              onChange={(e) => edit({ ...draft, quiet_enabled: e.target.checked })}
            />
            <span>Use quiet hours</span>
          </label>
          <div className="tm-alert-times">
            <label>
              <span className="tm-dim">From</span>
              <input
                type="time"
                className="tm-input"
                value={draft.quiet_start}
                disabled={!draft.quiet_enabled}
                onChange={(e) => edit({ ...draft, quiet_start: e.target.value })}
              />
            </label>
            <label>
              <span className="tm-dim">To</span>
              <input
                type="time"
                className="tm-input"
                value={draft.quiet_end}
                disabled={!draft.quiet_enabled}
                onChange={(e) => edit({ ...draft, quiet_end: e.target.value })}
              />
            </label>
          </div>
          {draft.quiet_enabled && (
            <p className="tm-dim" style={{ marginBottom: 0 }} data-testid="alerts-quiet-text">
              Quiet from {quietText(draft.quiet_start, draft.quiet_end)}.
            </p>
          )}
        </Card>

        <Card
          title={<Term k="digest">Daily digest</Term>}
          sub="One message a day with the everyday news, instead of one message each time."
        >
          <label className="tm-alert-toggle" htmlFor="alert-digest">
            <input
              id="alert-digest"
              type="checkbox"
              checked={draft.digest_enabled}
              onChange={(e) => edit({ ...draft, digest_enabled: e.target.checked })}
            />
            <span>Send one digest a day</span>
          </label>
          <div className="tm-alert-times">
            <label>
              <span className="tm-dim">At</span>
              <input
                type="time"
                className="tm-input"
                value={draft.digest_time}
                disabled={!draft.digest_enabled}
                onChange={(e) => edit({ ...draft, digest_time: e.target.value })}
              />
            </label>
          </div>
        </Card>
      </div>

      <Card>
        {held && (
          <p className="tm-dim" data-testid="alerts-held">
            {held}
          </p>
        )}
        {issue && (
          <p className="tm-neg" role="alert">
            {issue}
          </p>
        )}
        {save.isError && (
          <p className="tm-neg" role="alert">
            {saveError(save.error)}
          </p>
        )}
        <div className="tm-gl-actions">
          <button
            type="button"
            className="tm-btn"
            disabled={!changed || issue !== null || save.isPending}
            onClick={() => save.mutate(draft)}
          >
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
          {changed && (
            <button type="button" className="tm-btn tm-btn-ghost" onClick={() => edit(original)}>
              Undo changes
            </button>
          )}
          {saved && !changed && (
            <span className="tm-pos" role="status">
              Saved.
            </span>
          )}
        </div>
        <p className="tm-dim" style={{ marginBottom: 0 }}>
          These settings only change which messages reach your phone, and when. They never change what the bot buys or
          sells.
        </p>
      </Card>
    </>
  )
}

export default function Alerts() {
  const q = useQuery({ queryKey: ['alert-settings'], queryFn: api.alertSettings })
  return (
    <div className="tm-page tm-grid">
      <PageHead
        title="Alerts"
        sub="Choose which Telegram messages reach your phone. All times are India time (IST)."
      />
      <QueryState q={q} what="your alert settings">
        {(data) => <AlertsForm data={data} />}
      </QueryState>
    </div>
  )
}
