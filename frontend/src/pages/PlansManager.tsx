import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, setPreviewPlan } from '../api/client'
import type { PlanCatalogue, PlanConfig, PlanKey, PlanLimits } from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatDate } from '../lib/format'
import { PLAN_LABELS, useIsOwner } from '../lib/plan'

// Owner control room: Free and Pro only. Admin APIs require is_superuser — not
// merely "unrestricted" while plans are switched off.

const PLAN_ORDER: PlanKey[] = ['free', 'pro']
const TIER_LABEL: Record<string, string> = { large: 'Large', midcap: 'Mid', smallcap: 'Small' }
type Tab = 'features' | 'limits' | 'users' | 'preview'
type Drafts = Record<PlanKey, PlanConfig>

function OwnerGate({ children }: { children: React.ReactNode }) {
  const { isOwner, username, loading } = useIsOwner()
  if (loading) return <Loading label="Checking owner access…" />
  if (!isOwner) {
    return (
      <div className="card plans-owner-gate">
        <h2 style={{ marginTop: 0 }}>Owner access required</h2>
        <p>
          The Plans screen changes what <strong>Free</strong> and <strong>Pro</strong> users see. Only the
          app owner can open it.
        </p>
        <p className="muted">
          Signing up does <em>not</em> make you the owner. Promote your login once (local):
        </p>
        <pre className="plans-cli">
          cd backend{'\n'}
          .\.venv\Scripts\python.exe -m swing_trade_ml.cli make-owner {username ?? 'YOUR_USERNAME'}
        </pre>
        <p className="muted" style={{ marginBottom: 0 }}>
          Then refresh this page. You are logged in as <strong>{username ?? '…'}</strong>.
        </p>
      </div>
    )
  }
  return <>{children}</>
}

function PlanEditor({ tab, enabled }: { tab: 'features' | 'limits'; enabled: boolean }) {
  const queryClient = useQueryClient()
  const catalogue = useQuery({ queryKey: ['planCatalogue'], queryFn: api.planCatalogue, enabled })
  const plans = useQuery({ queryKey: ['plans'], queryFn: api.plans, enabled })
  const [drafts, setDrafts] = useState<Drafts | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (plans.data) {
      setDrafts(Object.fromEntries(plans.data.map((p) => [p.key, structuredClone(p)])) as Drafts)
    }
  }, [plans.data])

  const dirty = useMemo(
    () =>
      !!drafts &&
      !!plans.data &&
      plans.data.some((p) => JSON.stringify(p) !== JSON.stringify(drafts[p.key])),
    [drafts, plans.data],
  )

  const save = useMutation({
    mutationFn: async () => {
      if (!drafts || !plans.data) return
      for (const original of plans.data) {
        const draft = drafts[original.key]
        if (JSON.stringify(original) !== JSON.stringify(draft)) {
          await api.savePlan(draft.key, { features: draft.features, limits: draft.limits })
        }
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plans'] })
      setSaved(true)
      window.setTimeout(() => setSaved(false), 2500)
    },
  })

  if (!enabled) return null
  if (catalogue.isLoading || plans.isLoading || !drafts) return <Loading />
  if (catalogue.error) return <ErrorBox error={catalogue.error} />
  if (plans.error) return <ErrorBox error={plans.error} />
  const cat = catalogue.data!

  const setFeature = (plan: PlanKey, key: string, on: boolean) =>
    setDrafts((d) => d && { ...d, [plan]: { ...d[plan], features: { ...d[plan].features, [key]: on } } })
  const setLimit = (plan: PlanKey, key: keyof PlanLimits, value: PlanLimits[keyof PlanLimits]) =>
    setDrafts((d) => d && { ...d, [plan]: { ...d[plan], limits: { ...d[plan].limits, [key]: value } } })

  const groups = [...new Set(cat.features.map((f) => f.group))]

  return (
    <>
      <div className="table-wrap plans-table">
        <table>
          <thead>
            <tr>
              <th>{tab === 'features' ? 'Feature' : 'Limit'}</th>
              {PLAN_ORDER.map((k) => (
                <th key={k} className="plans-tier-col">
                  <span className={`plans-tier plans-tier-${k}`}>{PLAN_LABELS[k]}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tab === 'features' &&
              groups.map((group) => (
                <FeatureGroup key={group} group={group} catalogue={cat} drafts={drafts} onChange={setFeature} />
              ))}
            {tab === 'limits' &&
              cat.limits.map((limit) => (
                <tr key={limit.key}>
                  <td>
                    <strong>{limit.label}</strong>
                    <div className="muted" style={{ fontSize: '0.8rem' }}>
                      {limit.description}
                    </div>
                  </td>
                  {PLAN_ORDER.map((plan) => {
                    const value = drafts[plan].limits[limit.key]
                    return (
                      <td key={plan} className="plans-tier-col">
                        {limit.kind === 'int' ? (
                          <input
                            type="number"
                            min={0}
                            value={value as number}
                            onChange={(e) => setLimit(plan, limit.key, Math.max(0, Number(e.target.value)))}
                            aria-label={`${limit.label}, ${PLAN_LABELS[plan]}`}
                          />
                        ) : (
                          <div className="plans-tier-chips">
                            {TIER_LABEL &&
                              (['large', 'midcap', 'smallcap'] as const).map((tier) => (
                                <label key={tier} className="plans-chip">
                                  <input
                                    type="checkbox"
                                    checked={(value as string[]).includes(tier)}
                                    onChange={(e) => {
                                      const tiers = new Set(value as string[])
                                      if (e.target.checked) tiers.add(tier)
                                      else tiers.delete(tier)
                                      setLimit(plan, limit.key, [...tiers])
                                    }}
                                  />
                                  {TIER_LABEL[tier]}
                                </label>
                              ))}
                          </div>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      <div className="row" style={{ marginTop: '1rem', alignItems: 'center', gap: '1rem' }}>
        <button className="primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? 'Saving…' : 'Save changes'}
        </button>
        <button
          type="button"
          disabled={!dirty}
          onClick={() =>
            plans.data &&
            setDrafts(Object.fromEntries(plans.data.map((p) => [p.key, structuredClone(p)])) as Drafts)
          }
        >
          Discard
        </button>
        {saved && <span className="pos">Saved. Live for everyone on that plan.</span>}
        {save.isError && <span className="neg">{(save.error as Error).message}</span>}
      </div>
    </>
  )
}

function FeatureGroup({
  group,
  catalogue,
  drafts,
  onChange,
}: {
  group: string
  catalogue: PlanCatalogue
  drafts: Drafts
  onChange: (plan: PlanKey, key: string, on: boolean) => void
}) {
  const features = catalogue.features.filter((f) => f.group === group)
  return (
    <>
      <tr className="plans-group-row">
        <td colSpan={3}>{group}</td>
      </tr>
      {features.map((f) => (
        <tr key={f.key}>
          <td>
            <strong>{f.label}</strong>
            <div className="muted" style={{ fontSize: '0.8rem' }}>{f.description}</div>
          </td>
          {PLAN_ORDER.map((plan) => (
            <td key={plan} className="plans-tier-col">
              <input
                type="checkbox"
                checked={!!drafts[plan].features[f.key]}
                onChange={(e) => onChange(plan, f.key, e.target.checked)}
                aria-label={`${f.label}, ${PLAN_LABELS[plan]}`}
              />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

function Users({ enabled }: { enabled: boolean }) {
  const users = useQuery({ queryKey: ['adminUsers'], queryFn: api.users, enabled })
  const setPlan = useMutation({
    mutationFn: ({ id, plan }: { id: number; plan: string }) => api.setUserPlan(id, plan),
    onSuccess: () => users.refetch(),
  })

  if (!enabled) return null
  if (users.isLoading) return <Loading />
  if (users.error) return <ErrorBox error={users.error} />
  const list = users.data ?? []
  if (list.length === 0) return <Empty label="No other users yet." />

  return (
    <>
      <div className="table-wrap plans-table">
        <table>
          <thead>
            <tr>
              <th>User</th>
              <th>Last login</th>
              <th>Plan</th>
            </tr>
          </thead>
          <tbody>
            {list.map((u) => (
              <tr key={u.id}>
                <td>
                  <strong>{u.username}</strong>
                  {u.is_owner && <span className="badge badge-on" style={{ marginLeft: 8 }}>Owner</span>}
                </td>
                <td className="muted">{u.last_login_at ? formatDate(u.last_login_at) : '—'}</td>
                <td>
                  {u.is_owner ? (
                    <span className="muted">Owner (all access)</span>
                  ) : (
                    <select
                      value={u.plan}
                      disabled={setPlan.isPending}
                      onChange={(e) => setPlan.mutate({ id: u.id, plan: e.target.value })}
                      aria-label={`Plan for ${u.username}`}
                    >
                      {PLAN_ORDER.map((k) => (
                        <option key={k} value={k}>
                          {PLAN_LABELS[k]}
                        </option>
                      ))}
                    </select>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {setPlan.isError && <p className="neg">{(setPlan.error as Error).message}</p>}
      <p className="note" style={{ marginTop: '1rem' }}>
        New accounts start on <strong>Free</strong>. Assign <strong>Pro</strong> here when someone should get
        TradeMind and full picks.
      </p>
    </>
  )
}

function MasterSwitch({ enabled }: { enabled: boolean }) {
  const queryClient = useQueryClient()
  const current = useQuery({ queryKey: ['planSwitch'], queryFn: api.planSwitch, enabled })
  const flip = useMutation({
    mutationFn: api.setPlanSwitch,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['planSwitch'] })
      queryClient.invalidateQueries({ queryKey: ['plan'] })
    },
  })

  if (!enabled) return null
  if (current.isLoading) return <Loading label="Loading plan switch…" />
  if (current.error) return <ErrorBox error={current.error} />
  const on = !!current.data?.enabled

  return (
    <div className={`banner ${on ? 'banner-ok' : 'banner-info'}`} style={{ marginBottom: '1.25rem' }}>
      <div className="between">
        <div>
          <strong>Plan gating is {on ? 'ON' : 'OFF'}.</strong>{' '}
          {on
            ? 'Only Free / Pro rules apply to everyone except you.'
            : 'Everyone still sees the full app. Turn this on when Free and Pro are ready.'}
        </div>
        <button
          className={on ? '' : 'primary'}
          disabled={flip.isPending}
          onClick={() => {
            const message = on
              ? 'Turn plan gating off? Everyone will see the full app again.'
              : 'Turn plan gating on? Non-owners will only see what their plan allows.'
            if (confirm(message)) flip.mutate(!on)
          }}
        >
          {flip.isPending ? 'Saving…' : on ? 'Turn off' : 'Turn on'}
        </button>
      </div>
      {flip.isError && <div className="neg">{(flip.error as Error).message}</div>}
    </div>
  )
}

function Preview({ enabled }: { enabled: boolean }) {
  if (!enabled) return null
  const start = (plan: PlanKey) => {
    setPreviewPlan(plan)
    window.location.assign('/home')
  }
  return (
    <div className="card">
      <p style={{ marginTop: 0 }}>
        Open the app as a <strong>Free</strong> or <strong>Pro</strong> user (menu, picks, refusals). Your
        account stays owner; use the banner to exit preview.
      </p>
      <div className="row">
        {PLAN_ORDER.map((k) => (
          <button key={k} type="button" className="primary" onClick={() => start(k)}>
            Preview {PLAN_LABELS[k]}
          </button>
        ))}
      </div>
    </div>
  )
}

export default function PlansManager() {
  const { isOwner, loading } = useIsOwner()
  const [tab, setTab] = useState<Tab>('features')
  const TABS: { key: Tab; label: string }[] = [
    { key: 'features', label: 'Features' },
    { key: 'limits', label: 'Limits' },
    { key: 'users', label: 'Users' },
    { key: 'preview', label: 'Preview' },
  ]

  useEffect(() => {
    if (isOwner) setPreviewPlan(null)
  }, [isOwner])

  return (
    <div className="plans-page">
      <OwnerGate>
        <div className="page-head">
          <div>
            <h1 style={{ marginBottom: '0.15rem' }}>Free &amp; Pro plans</h1>
            <p className="muted" style={{ margin: 0, maxWidth: 520 }}>
              Two tiers only. Toggle features and limits, assign users, then turn plan gating on when ready.
            </p>
          </div>
          <div className="plans-tier-legend">
            {PLAN_ORDER.map((k) => (
              <span key={k} className={`plans-tier plans-tier-${k}`}>{PLAN_LABELS[k]}</span>
            ))}
          </div>
        </div>

        {!loading && isOwner && (
          <>
            <MasterSwitch enabled={isOwner} />
            <div className="plans-tabs" role="tablist">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  role="tab"
                  aria-selected={tab === t.key}
                  className={`plans-tab${tab === t.key ? ' active' : ''}`}
                  onClick={() => setTab(t.key)}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="plans-panel">
              {(tab === 'features' || tab === 'limits') && <PlanEditor key={tab} tab={tab} enabled={isOwner} />}
              {tab === 'users' && <Users enabled={isOwner} />}
              {tab === 'preview' && <Preview enabled={isOwner} />}
            </div>
            <p className="note" style={{ marginTop: '1.5rem' }}>
              Always owner-only: Zerodha holdings, capital, safety, strategies, orders, brain console, go-live.
            </p>
          </>
        )}
      </OwnerGate>
    </div>
  )
}
