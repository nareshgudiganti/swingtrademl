import { BuildingIcon, ScaleIcon, SproutIcon } from '../components/icons'

// The cap-tier identity shared across every page that groups by strategy:
// Suggestions groups its tabs by this, Strategies colors its Tier column by
// this. One definition so "Mid Cap is violet" means the same thing everywhere
// instead of three pages agreeing on a hex code by convention.
export const TIERS = [
  {
    match: 'ml_swing_main',
    modelName: 'swing_classifier',
    label: 'Large Cap',
    color: '#4f8cff',
    Icon: BuildingIcon,
  },
  {
    match: 'ml_swing_midcap',
    modelName: 'swing_classifier_midcap',
    label: 'Mid Cap',
    color: '#a78bfa',
    Icon: ScaleIcon,
  },
  {
    match: 'ml_swing_smallcap',
    modelName: 'swing_classifier_smallcap',
    label: 'Small Cap',
    color: '#2dd4bf',
    Icon: SproutIcon,
  },
] as const

export type Tier = (typeof TIERS)[number]

export function tierFor(strategyName: string): Tier | null {
  return TIERS.find((t) => t.match === strategyName) ?? null
}
