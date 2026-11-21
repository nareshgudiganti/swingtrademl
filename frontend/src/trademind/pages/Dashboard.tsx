// The old Swing Picks page. Since oa5 its parts live in ../today/SwingPicks.tsx and are shown on Today
// (pages/Today.tsx); /trademind/dashboard now opens Today at the pick list. This page is no longer routed and
// stays only until Phase 6 (oa10) removes it, so its tests keep checking the moved parts.

import { useState } from 'react'

import { DEFAULT_HORIZON, type HorizonId } from '../horizons'
import { useLatestRun } from '../live'
import { HowItWorks, SwingPicksHero, SwingPicksList } from '../today/SwingPicks'
import { BrainGate } from '../ui'

// `initialHorizon` exists for tests (the page opens on 15 days otherwise).
export default function Dashboard({ initialHorizon = DEFAULT_HORIZON }: { initialHorizon?: HorizonId } = {}) {
  return (
    <BrainGate>
      <DashboardBody initialHorizon={initialHorizon} />
    </BrainGate>
  )
}

function DashboardBody({ initialHorizon }: { initialHorizon: HorizonId }) {
  const run = useLatestRun().data!
  const [win, setWin] = useState<HorizonId>(initialHorizon)
  return (
    <div className="tm-page tm-grid">
      <div className="tm-dash-top">
        <SwingPicksHero run={run} win={win} onWin={setWin} />
        <HowItWorks />
      </div>
      <SwingPicksList run={run} win={win} onWin={setWin} />
    </div>
  )
}
