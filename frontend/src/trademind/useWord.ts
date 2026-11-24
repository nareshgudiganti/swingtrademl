// The one decision word a screen shows for an idea (#486): the owner sees the stored word, as Today does; everyone
// else sees the stock-level verdict. See wordFor() in live.ts for the rule and why.
import { usePlan } from '../lib/plan'
import type { BrainDecision } from '../api/types'
import { wordFor } from './live'

/** True for the owner: the screens that show a decision word read it the same way Today does. */
export function useOwner(): boolean {
  return usePlan().canManage
}

export function useWordFor(): (d: BrainDecision) => string {
  const { canManage } = usePlan()
  return (d) => wordFor(d, canManage)
}
