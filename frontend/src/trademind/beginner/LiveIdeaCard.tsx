// IdeaCard with its plan details and rupees at stake read from the backend (/beginner/stock/{symbol}).
// Only a TRADE idea asks for them (at most a handful a day); other words have no buy plan to fill in.
import type { ReactNode } from 'react'

import { useStockBrief } from './api'
import IdeaCard, { effectiveWord, type PlanData } from './IdeaCard'
import type { BeginnerDecision, MoneyAtStakeData } from './types'

export default function LiveIdeaCard({
  decision: d,
  compact,
  actions,
  dayScores,
  tags,
}: {
  decision: BeginnerDecision
  compact?: boolean
  actions?: ReactNode
  dayScores?: readonly (number | null)[]
  tags?: ReactNode
}) {
  const isTrade = d.kind === 'idea' && effectiveWord(d) === 'TRADE'
  // An empty symbol leaves the query switched off.
  const brief = useStockBrief(isTrade ? d.symbol : '')
  const data = brief.data
  // The brief reads the brain's latest nightly run itself; it only counts when it is about this same decision.
  const same = data?.q2_brain.decision?.id === d.id

  let plan: PlanData | undefined
  let money: MoneyAtStakeData | undefined
  if (isTrade) {
    if (brief.isLoading) {
      plan = { available: false, why: 'still loading' }
      money = { available: false, why: 'still loading' }
    } else if (brief.isError || !data) {
      const why = `could not load the plan details (${brief.error instanceof Error ? brief.error.message : 'no reply'})`
      plan = { available: false, why }
      money = { available: false, why }
    } else if (!same) {
      const why = data.q2_brain.why ?? 'the plan details are from a different brain run'
      plan = { available: false, why }
      money = { available: false, why }
    } else {
      plan = data.q3_plan
      money = data.q4_money
    }
  }

  return (
    <IdeaCard
      decision={d}
      plan={plan}
      money={money}
      compact={compact}
      actions={actions}
      dayScores={dayScores}
      tags={tags}
      linkTo={`/trademind/stock/${encodeURIComponent(d.symbol)}`}
    />
  )
}
