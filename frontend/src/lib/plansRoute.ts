// Which screen draws the Plans manager (tracker oa3).
//  - 'trademind': the owner, with the brain on, at /trademind/plans: TradeMind draws it under Admin > Plans.
//  - 'classic':   every other way in (/plans, the brain off, the status unreadable, anyone not the owner): the
//                 classic light shell, exactly as before. The page's own owner check answers a non-owner.
//  - 'wait':      the owner at /trademind/plans while the account status is still loading (avoids a flash).
//  - null:        not a Plans path.
export type PlansShell = 'trademind' | 'classic' | 'wait' | null

export function plansShell(
  path: string,
  who: { isOwner: boolean; brainEnabled: boolean | undefined; statusFailed: boolean },
): PlansShell {
  if (path === '/plans' || path.startsWith('/plans/')) return 'classic'
  if (path !== '/trademind/plans') return null
  if (!who.isOwner) return 'classic'
  if (who.brainEnabled === undefined && !who.statusFailed) return 'wait'
  return who.brainEnabled ? 'trademind' : 'classic'
}
