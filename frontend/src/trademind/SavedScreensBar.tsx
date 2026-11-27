// The "Saved screens" menu on Discover (#310, slice A): open, save, update, rename and delete a named set of filters.
// Each person has their own (the server keys them to the signed-in account). Deleting a screen only deletes the
// saved settings: never the watchlist, a trade or an order. Plain words, nothing here changes what the brain decides.

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import {
  describeSpec,
  MAX_NAME,
  sameAsSaved,
  specFromControls,
  type Controls,
  type SavedScreen,
} from './savedScreens'

type Mode = 'idle' | 'save' | 'rename' | 'delete'

export const SCREENS_KEY = ['savedScreens']

export default function SavedScreensBar({
  controls,
  active,
  problems,
  onOpen,
  onClose,
}: {
  controls: Controls
  active: SavedScreen | null
  /** What in the opened screen cannot be applied right now (plain words). */
  problems: string[]
  onOpen: (screen: SavedScreen) => void
  onClose: () => void
}) {
  const client = useQueryClient()
  const list = useQuery({ queryKey: SCREENS_KEY, queryFn: api.mySavedScreens, retry: false })
  const [mode, setMode] = useState<Mode>('idle')
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)

  const screens = list.data?.screens ?? []
  const limit = list.data?.limit ?? null
  const done = () => {
    setMode('idle')
    setError(null)
    return client.invalidateQueries({ queryKey: SCREENS_KEY })
  }
  const fail = (e: unknown) => setError((e as Error).message)

  const create = useMutation({
    mutationFn: (n: string) => api.saveScreen(n, specFromControls(controls)),
    onSuccess: (s) => {
      onOpen(s)
      return done()
    },
    onError: fail,
  })
  const update = useMutation({
    mutationFn: () => api.changeScreen(active!.id, { spec: specFromControls(controls, active!.spec) }),
    onSuccess: (s) => {
      onOpen(s)
      client.invalidateQueries({ queryKey: ['screenDigest'] })
      return done()
    },
    onError: fail,
  })
  const rename = useMutation({
    mutationFn: (n: string) => api.changeScreen(active!.id, { name: n }),
    onSuccess: (s) => {
      onOpen(s)
      return done()
    },
    onError: fail,
  })
  const remove = useMutation({
    mutationFn: () => api.deleteScreen(active!.id),
    onSuccess: () => {
      onClose()
      return done()
    },
    onError: fail,
  })

  const busy = create.isPending || update.isPending || rename.isPending || remove.isPending
  const full = limit != null && screens.length >= limit
  const unchanged = active ? sameAsSaved(active.spec, controls) : false
  const readBack = describeSpec(specFromControls(controls, active?.spec))

  const open = (m: Mode, initial = '') => {
    setError(null)
    setName(initial)
    setMode(m)
  }
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const n = name.trim()
    if (!n) return setError('Give the screen a name.')
    if (mode === 'rename') rename.mutate(n)
    else create.mutate(n)
  }

  return (
    <section className="tmn-w2-screens" aria-label="Saved screens" data-testid="saved-screens">
      <div className="tmn-w2-screens-row">
        <label className="tmn-w2-select tm-dim tmn-small">
          Saved screens
          <select
            value={active ? String(active.id) : ''}
            onChange={(e) => {
              const s = screens.find((x) => String(x.id) === e.target.value)
              if (s) onOpen(s)
              else onClose()
              setMode('idle')
            }}
            data-testid="saved-screens-menu"
            disabled={list.isLoading}
          >
            <option value="">{screens.length === 0 ? 'None saved yet' : 'Choose a screen'}</option>
            {screens.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        {active && (
          <button type="button" className="tmn-w2-pill" disabled={busy || unchanged} onClick={() => update.mutate()} data-testid="screen-update">
            Update “{active.name}”
          </button>
        )}
        <button
          type="button"
          className="tmn-w2-pill"
          disabled={busy || full}
          title={full ? `You can keep up to ${limit} saved screens. Delete one to save another.` : undefined}
          onClick={() => open('save')}
          data-testid="screen-save-new"
        >
          {active ? 'Save as new' : 'Save current filters'}
        </button>
        {active && (
          <>
            <button type="button" className="tmn-w2-pill" disabled={busy} onClick={() => open('rename', active.name)} data-testid="screen-rename">
              Rename
            </button>
            <button type="button" className="tmn-w2-pill" disabled={busy} onClick={() => open('delete')} data-testid="screen-delete">
              Delete
            </button>
          </>
        )}
        {limit != null && (
          <span className="tm-dim tmn-small" data-testid="screens-count">
            {screens.length} of {limit} saved
          </span>
        )}
      </div>

      {(mode === 'save' || mode === 'rename') && (
        <form className="tmn-w2-screens-form" onSubmit={submit} data-testid="screen-form">
          <label className="tmn-small">
            {mode === 'rename' ? 'New name' : 'Name this screen'}
            <input
              type="text"
              value={name}
              maxLength={MAX_NAME}
              onChange={(e) => setName(e.target.value)}
              placeholder="For example: Large companies, BUY"
              data-testid="screen-name"
              autoFocus
            />
          </label>
          {mode === 'save' && (
            <p className="tm-dim tmn-small" data-testid="screen-readback">
              Saving: {readBack}
            </p>
          )}
          <button type="submit" className="tmn-w2-primary" disabled={busy} data-testid="screen-submit">
            {mode === 'rename' ? 'Rename' : 'Save screen'}
          </button>
          <button type="button" className="tmn-w2-pill" onClick={() => setMode('idle')}>
            Cancel
          </button>
        </form>
      )}

      {mode === 'delete' && active && (
        <p className="tmn-small" role="alert" data-testid="screen-confirm-delete">
          Delete “{active.name}”? Only the saved filters go. Your watchlist and your trades are not touched.{' '}
          <button type="button" className="tmn-w2-pill" disabled={busy} onClick={() => remove.mutate()} data-testid="screen-confirm-yes">
            Yes, delete it
          </button>{' '}
          <button type="button" className="tmn-w2-pill" onClick={() => setMode('idle')}>
            Keep it
          </button>
        </p>
      )}

      {error && (
        <p className="tm-neg tmn-small" role="alert" data-testid="screen-error">
          {error}
        </p>
      )}

      {active && (
        <p className="tm-dim tmn-small" data-testid="screen-showing">
          Showing: {describeSpec(active.spec)}
        </p>
      )}
      {problems.map((p) => (
        <p className="tmn-w2-note" key={p} data-testid="screen-problem">
          {p}
        </p>
      ))}
    </section>
  )
}
