// The new look's stock page: short, the main things only. Header with Buy, four summary cards, the brain's eight
// steps (so nobody has to click to find them), the plan, the company, three one-line answers, and a way into the
// full-analysis page (StockAnalysis.tsx). Display only: reads the brain's latest run and stored data.

import { Link, useParams } from 'react-router-dom'

import type { BrainDecision, BrainRun } from '../../api/types'
import { formatDateTime } from '../../lib/format'
import { useSymbolCaps } from '../cap'
import { useLatestRun } from '../live'
import { BrainGate } from '../ui'
import {
  BrainFlow,
  CompanyCard,
  FullCta,
  Glance,
  PlanLadder,
  QuickAnswers,
  StockHeader,
  useStockData,
} from '../stockParts'
import StockDetail from './StockDetail'

export const CAP_LABEL: Record<string, string> = { large: 'LARGE', midcap: 'MID', smallcap: 'SMALL' }

export default function StockNew() {
  return (
    <BrainGate>
      <StockNewBody />
    </BrainGate>
  )
}

function StockNewBody() {
  const symbol = (useParams().symbol ?? '').toUpperCase()
  const run = useLatestRun().data!
  const decision = run.decisions.find((d) => d.symbol.toUpperCase() === symbol)
  // Nothing from tonight's run for this stock: the classic page asks the brain on demand and says so.
  if (!decision) return <StockDetail />
  return <StockNewView decision={decision} run={run} />
}

function StockNewView({ decision, run }: { decision: BrainDecision; run: BrainRun }) {
  const caps = useSymbolCaps()
  const data = useStockData(decision, run)
  const analysisTo = `/trademind/stock/${encodeURIComponent(decision.symbol)}/analysis`
  const cap = caps.get(decision.symbol.toUpperCase())

  return (
    <div className="tm-page sp" data-page="stock-new">
      <Link to="/trademind/opportunities" className="sp-back">
        ← Back to Discover
      </Link>
      <StockHeader
        decision={decision}
        last={data.last}
        prev={data.prev}
        change={data.change}
        snapshot={data.snapshot}
        cap={cap ? CAP_LABEL[cap] : undefined}
        analysisTo={analysisTo}
      />
      <Glance
        decision={decision}
        run={run}
        last={data.last}
        prev={data.prev}
        change={data.change}
        trail={data.trail}
        idea={data.idea}
        snapshot={data.snapshot}
        runAt={`Brain’s run on ${formatDateTime(run.started_at)}`}
      />
      <BrainFlow decision={decision} run={run} analysisTo={analysisTo} />
      <div className="sp-split">
        <PlanLadder decision={decision} />
        <CompanyCard brief={data.brief} />
      </div>
      <QuickAnswers brief={data.brief} />
      <FullCta to={analysisTo} />
    </div>
  )
}
