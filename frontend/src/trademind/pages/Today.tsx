// oa5: one Today page = the old Home + Swing Picks. Display only: it reads what the other screens read and changes
// nothing about picks, decisions, orders, sizing, stops or limits. Top to bottom:
//   1. status strip   market mode and banner; for the owner, kill switch, drawdown and trading stage
//   2. needs you      flagged holdings (a slot, see today/HoldingsNeedsYou.tsx); for the owner, approvals and proposals
//   3. today's ideas  horizon selector, idea counts, the top 5 ideas as the one recommendation card
//   4. what changed since yesterday, today's insights
//   5. all of today's picks (id="picks"): everything Swing Picks had; /trademind/dashboard opens Today here
// The feature list it is checked against: docs/superpowers/plans/2026-10-23-oa5-today-feature-list.md.
// The status strip and "needs you" do not wait for a brain run; everything else sits behind BrainGate.

import { useEffect, useState } from 'react'

import { DEFAULT_HORIZON, type HorizonId } from '../horizons'
import { useLatestRun } from '../live'
import { HoldingsNeedsYou } from '../today/HoldingsNeedsYou'
import { NeedsYou } from '../today/NeedsYou'
import { StatusStrip } from '../today/StatusStrip'
import { HowItWorks, SwingPicksList } from '../today/SwingPicks'
import { TodayChanges, TodayIdeas, TodayInsights } from '../today/TodayIdeas'
import { BrainGate } from '../ui'

export default function Today({
  owner = false,
  focus,
  initialHorizon = DEFAULT_HORIZON,
}: {
  /** The owner console: adds the safety picture and what waits for the owner's decision. */
  owner?: boolean
  /** 'picks': opened from /trademind/dashboard, so scroll to the pick list. */
  focus?: 'picks'
  /** Tests only: the window chosen when the page opens (15 days otherwise). */
  initialHorizon?: HorizonId
}) {
  const latest = useLatestRun()
  const [win, setWin] = useState<HorizonId>(initialHorizon)
  const runId = latest.data?.run_id

  useEffect(() => {
    if (focus === 'picks' && runId) document.getElementById('picks')?.scrollIntoView({ block: 'start' })
  }, [focus, runId])

  return (
    <div className="tm-page tm-grid tm-today" data-page="today" data-focus={focus}>
      <StatusStrip owner={owner} />
      <NeedsYou owner={owner} holdings={<HoldingsNeedsYou run={latest.data} />} />
      <BrainGate>
        <TodayFromRun win={win} onWin={setWin} />
      </BrainGate>
    </div>
  )
}

function TodayFromRun({ win, onWin }: { win: HorizonId; onWin: (h: HorizonId) => void }) {
  const run = useLatestRun().data!
  return (
    <>
      <TodayIdeas run={run} win={win} onWin={onWin} />
      <div className="tm-grid tm-cols-2">
        <TodayChanges run={run} />
        <TodayInsights run={run} />
      </div>
      <section id="picks" className="tm-grid tm-today-picks" aria-label="All of today's picks">
        <h2 className="tm-today-h2">All of today&apos;s picks</h2>
        <HowItWorks />
        <SwingPicksList run={run} win={win} onWin={onWin} />
      </section>
    </>
  )
}
