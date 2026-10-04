import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, setPreviewPlan } from '../api/client'
import type { PlanCatalogue, PlanConfig, PlanKey, PlanLimits } from '../api/types'
import { ErrorBox, Loading } from '../components/Loading'
import { formatDate } from '../lib/format'
import { PLAN_LABELS } from '../lib/plan'

// The owner's control room for Free / Pro: which features each plan
// gets, its limits, who is on which plan, and a way to see the app through a
// plan's eyes. Only the owner reaches this (the API checks that too).

const PLAN_ORDER: PlanKey[] = ['free', 'pro']
const TIER_LABEL: Record<string, string> = { large: 'Large', midcap: 'Mid', smallcap: 'Small' }
type Tab = 'features' | 'limits' | 'users' | 'preview'
type Drafts = Record<PlanKey, PlanConfig>

function PlanEditor({ tab }: { tab: 'features' | 'limits' }) {
  const queryClient = useQueryClient()
  const catalogue = useQuery({ queryKey: ['planCatalogue'], queryFn: api.planCatalogue })
  const plans = useQuery({ queryKey: ['plans'], queryFn: api.plans })
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
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{tab === 'features' ? 'Feature' : 'Limit'}</th>
              {PLAN_ORDER.map((k) => (
                <th key={k} style={{ textAlign: 'center' }}>
                  {PLAN_LABELS[k]}
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
                      <td key={plan} style={{ textAlign: 'center' }}>
                        {limit.kind === 'int' ? (
                          <input
                            type="number"
                            min={0}
                            value={Number(value ?? 0)}
                            onChange={(e) => setLimit(plan, limit.key, Math.max(0, Number(e.target.value)))}
                            style={{ width: 80 }}
                            aria-label={`${limit.label}, ${PLAN_LABELS[plan]}`}
                          />
                        ) : (
                          <div className="row" style={{ justifyContent: 'center' }}>
                            {cat.cap_tiers.map((tier) => {
                              const tiers = (value as string[]) ?? []
                              return (
                                <label key={tier} style={{ fontSize: '0.8rem' }}>
                                  <input
                                    type="checkbox"
                                    checked={tiers.includes(tier)}
                                    onChange={(e) =>
                                      setLimit(
                                        plan,
                                        limit.key,
                                        e.target.checked ? [...tiers, tier] : tiers.filter((t) => t !== tier),
                                      )
                                    }
                                  />{' '}
                                  {TIER_LABEL[tier] ?? tier}
                                </label>
                              )
                            })}
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

      <div className="row" style={{ marginTop: '1rem' }}>
        <button className="primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? 'Saving…' : 'Save changes'}
        </button>
        <button
          disabled={!dirty || save.isPending}
          onClick={() =>
            plans.data &&
            setDrafts(Object.fromEntries(plans.data.map((p) => [p.key, structuredClone(p)])) as Drafts)
          }
        >
          Undo
        </button>
        {saved && <span className="pos">Saved. It applies to everyone on that plan straight away.</span>}
        {save.isError && <span className="neg">{(save.error as Error).message}</span>}
      </div>

      {tab === 'features' && (
        <p className="note" style={{ marginTop: '1rem' }}>
          Never in any plan, only yours: your Zerodha holdings, Capital, Safety switches, Strategies, placing
          or closing orders, Finance and Settings. With “Picks from every model” off, a plan sees only the
          base model ({cat.base_model}, Large Cap).
        </p>
      )}
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
  return (
    <>
      <tr className="table-group-row">
        <td colSpan={4}>{group}</td>
      </tr>
      {catalogue.features
        .filter((f) => f.group === group)
        .map((f) => (
          <tr key={f.key}>
            <td>
              <strong>{f.label}</strong>
              <div className="muted" style={{ fontSize: '0.8rem' }}>
                {f.description}
              </div>
            </td>
            {PLAN_ORDER.map((plan) => (
              <td key={plan} style={{ textAlign: 'center' }}>
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

function Users() {
  const queryClient = useQueryClient()
  const users = useQuery({ queryKey: ['adminUsers'], queryFn: api.users })
  const setPlan = useMutation({
    mutationFn: ({ id, plan }: { id: number; plan: string }) => api.setUserPlan(id, plan),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['adminUsers'] }),
  })

  if (users.isLoading) return <Loading />
  if (users.error) return <ErrorBox error={users.error} />

  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>User</th>
              <th>Signs in with</th>
              <th>Last seen</th>
              <th>Plan</th>
            </tr>
          </thead>
          <tbody>
            {(users.data ?? []).map((u) => (
              <tr key={u.id}>
                <td>
                  <strong>{u.username}</strong>
                  {u.email && <div className="muted" style={{ fontSize: '0.8rem' }}>{u.email}</div>}
                </td>
                <td>{u.auth_provider === 'google' ? 'Google' : 'Password'}</td>
                <td>{u.last_login_at ? formatDate(u.last_login_at) : 'Never'}</td>
                <td>
                  {u.is_owner ? (
                    <span className="badge badge-on">Owner · sees everything</span>
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
        A change applies the next time that person opens a page. New accounts start on Free. Sign-up is still
        closed: people get in only through the Google allow-list or an account you create.
      </p>
    </>
  )
}

function MasterSwitch() {
  const queryClient = useQueryClient()
  const current = useQuery({ queryKey: ['planSwitch'], queryFn: api.planSwitch })
  const flip = useMutation({
    mutationFn: api.setPlanSwitch,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['planSwitch'] })
      queryClient.invalidateQueries({ queryKey: ['plan'] })
    },
  })

  if (current.isLoading) return <Loading />
  if (current.error) return <ErrorBox error={current.error} />
  const on = !!current.data?.enabled

  return (
    <div className={`banner ${on ? 'banner-ok' : 'banner-info'}`} style={{ marginBottom: '1rem' }}>
      <div className="between">
        <div>
          <strong>Plans are {on ? 'ON' : 'OFF'}.</strong>{' '}
          {on
            ? 'Everyone except you sees only what their plan includes.'
            : 'Everyone who signs in sees the whole app, exactly as before plans. Set things up and preview them first; nothing changes for anyone until you turn this on.'}
        </div>
        <button
          className={on ? '' : 'primary'}
          disabled={flip.isPending}
          onClick={() => {
            const message = on
              ? 'Turn plans off? Everyone who signs in will see the whole app again, as before plans.'
              : 'Turn plans on? Everyone except you will immediately see only what their plan includes.'
            if (confirm(message)) flip.mutate(!on)
          }}
        >
          {flip.isPending ? 'Saving…' : on ? 'Turn plans off' : 'Turn plans on'}
        </button>
      </div>
      {flip.isError && <div className="neg">{(flip.error as Error).message}</div>}
    </div>
  )
}

function Preview() {
  const start = (plan: PlanKey) => {
    setPreviewPlan(plan)
    // A full reload drops every cached owner response, so nothing from
    // your own view can leak into the preview.
    window.location.assign('/home')
  }
  return (
    <>
      <p>See the app exactly as someone on a plan sees it: the same menu, the same picks, the same refusals.</p>
      <div className="row">
        {PLAN_ORDER.map((k) => (
          <button key={k} className="primary" onClick={() => start(k)}>
            View as {PLAN_LABELS[k]}
          </button>
        ))}
      </div>
      <p className="muted" style={{ fontSize: '0.85rem' }}>
        A banner at the top lets you leave the preview at any time.
      </p>
    </>
  )
}

export default function PlansManager() {
  const [tab, setTab] = useState<Tab>('features')
  const TABS: { key: Tab; label: string }[] = [
    { key: 'features', label: 'Features' },
    { key: 'limits', label: 'Limits' },
    { key: 'users', label: 'Users' },
    { key: 'preview', label: 'Preview' },
  ]
  return (
    <>
      <div className="page-head">
        <div>
          <h1 style={{ marginBottom: '0.15rem' }}>Plans</h1>
          <div className="muted" style={{ fontSize: '0.82rem' }}>
            Choose what Free and Pro users can see. No payments yet: you assign plans by hand.
          </div>
        </div>
      </div>
      <MasterSwitch />
      <div className="row" style={{ marginBottom: '1rem' }} role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={tab === t.key ? 'primary' : ''}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {(tab === 'features' || tab === 'limits') && <PlanEditor key={tab} tab={tab} />}
      {tab === 'users' && <Users />}
      {tab === 'preview' && <Preview />}
    </>
  )
}
