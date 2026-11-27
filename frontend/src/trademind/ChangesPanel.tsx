// "What changed since the last scan" for a saved screen or for My Watchlist (#310, slice A). Brain ideas only: which
// stocks came into the screen and which dropped out, one stored reason each. The server builds every sentence from
// stored fields; this panel only lays them out. A Pro feature: a Free account sees one plain line instead.
// Never shown: profit, return, a chance of gain, or how an idea turned out.

import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { usePlan } from '../lib/plan'
import {
  digestIsEmpty,
  NOT_ENOUGH_HISTORY,
  placeText,
  wordMove,
  type DigestRow,
  type ScreenDigest,
} from './savedScreens'

export const LOCKED_TEXT = 'What changed on your saved screens and watchlist is part of the Pro plan.'
export const LOAD_ERROR = 'Could not load what changed. Your saved screen still works without it.'

function Rows({ title, rows, testId }: { title: string; rows: DigestRow[]; testId: string }) {
  if (rows.length === 0) return null
  return (
    <div data-testid={testId}>
      <h4 className="tmn-w2-digest-h">
        {title} <span className="tm-dim tmn-small">({rows.length})</span>
      </h4>
      <ul className="tmn-w2-digest-list">
        {rows.map((r) => {
          const place = placeText(r.rank, r.rank_of)
          const move = wordMove(r)
          return (
            <li key={r.symbol} data-testid="digest-row">
              <b>{r.symbol}</b>
              {move && <span className="tm-dim tmn-small"> · {move}</span>}
              {place && <span className="tm-dim tmn-small"> · {place}</span>}
              <div className="tmn-small">{r.reason}</div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/** The note itself, from an answer already in hand (also what the tests render). */
export function ChangesView({ digest }: { digest: ScreenDigest }) {
  return (
    <>
      {!digest.comparable ? (
        <p className="tmn-small" data-testid="digest-not-enough">
          {NOT_ENOUGH_HISTORY}
          {digest.note && <span className="tm-dim"> {digest.note}</span>}
        </p>
      ) : digestIsEmpty(digest) ? (
        <p className="tm-dim tmn-small" data-testid="digest-none">
          Nothing came in or dropped out since the last scan
          {digest.previous && digest.current ? ` (${digest.previous.day} to ${digest.current.day})` : ''}.
        </p>
      ) : (
        <>
          {digest.current && digest.previous && (
            <p className="tm-dim tmn-small">
              The brain’s run on {digest.current.day} compared with {digest.previous.day}.
            </p>
          )}
          <Rows title="Came in" rows={digest.came_in} testId="digest-came-in" />
          <Rows title="Dropped out" rows={digest.dropped_out} testId="digest-dropped-out" />
          <Rows title="Not compared" rows={digest.not_compared} testId="digest-not-compared" />
        </>
      )}
      <p className="tm-dim tmn-small" data-testid="digest-footer">
        {digest.footer}
      </p>
    </>
  )
}

/** `screenId` null = My Watchlist. */
export default function ChangesPanel({ screenId }: { screenId: number | null }) {
  const { has } = usePlan()
  const allowed = has('screen_digest')
  const q = useQuery({
    queryKey: ['screenDigest', screenId ?? 'watchlist'],
    queryFn: () => (screenId == null ? api.watchlistDigest() : api.screenDigest(screenId)),
    enabled: allowed,
    retry: false,
  })
  return (
    <section className="tmn-card tmn-w2-digest" aria-label="What changed since the last scan" data-testid="changes-panel">
      <h3 className="tmn-w2-digest-title">What changed since the last scan</h3>
      {!allowed ? (
        <p className="tm-dim tmn-small" data-testid="digest-locked">
          {LOCKED_TEXT}
        </p>
      ) : q.isLoading ? (
        <p className="tm-dim tmn-small" data-testid="digest-loading">
          Loading…
        </p>
      ) : q.isError || !q.data ? (
        <p className="tm-dim tmn-small" data-testid="digest-error">
          {LOAD_ERROR}
        </p>
      ) : (
        <ChangesView digest={q.data} />
      )}
    </section>
  )
}
