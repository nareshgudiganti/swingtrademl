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
  const isOwner = !!plan?.is_owner
  return {
    plan,
    isLoading: query.isLoading,
    error: query.error,
    isOwner,
    has: (feature: string) => isOwner || !!plan?.features.includes(feature),
  }
}

export const PLAN_LABELS: Record<string, string> = {
  free: 'Free',
  plus: 'Plus',
  pro: 'Pro',
  owner: 'Owner',
}
