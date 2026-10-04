import { useQuery } from '@tanstack/react-query'

import { api, getToken } from '../api/client'
import type { MyPlan } from '../api/types'

// What the signed-in person's plan shows. The menu is built from this, but
// it is only a convenience: the backend enforces the same plan on every
// request, so hiding a link here is never the only thing keeping it private.
export function usePlan() {
  const query = useQuery({
    queryKey: ['plan'],
    queryFn: api.myPlan,
    retry: false,
    enabled: !!getToken(),
    staleTime: 60_000,
  })
  const plan: MyPlan | undefined = query.data
  // The whole app: the owner, or anyone while plans are switched off.
  const seesAll = !!plan?.unrestricted
  return {
    plan,
    isLoading: query.isLoading,
    error: query.error,
    seesAll,
    // The real owner, even while previewing a plan.
    canManage: !!plan?.can_manage_plans,
    has: (feature: string) => seesAll || !!plan?.features.includes(feature),
  }
}

export const PLAN_LABELS: Record<string, string> = {
  free: 'Free',
  pro: 'Pro',
  owner: 'Owner',
  all: 'Everything',
}
