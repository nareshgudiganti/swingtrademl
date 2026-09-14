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
    description: 'Bigger, steadier companies. Fewer trades, aimed at lower risk.',
    color: '#4f8cff',
    Icon: BuildingIcon,
  },
  {
    match: 'ml_swing_midcap',
    modelName: 'swing_classifier_midcap',
    label: 'Mid Cap',
    description: 'Mid-sized companies. A balance of risk and reward.',
    color: '#a78bfa',
    Icon: ScaleIcon,
  },
  {
    match: 'ml_swing_smallcap',
    modelName: 'swing_classifier_smallcap',
    label: 'Small Cap',
    description: 'Smaller, more volatile companies. Higher risk, higher potential reward.',
    color: '#2dd4bf',
    Icon: SproutIcon,
  },
] as const

export type Tier = (typeof TIERS)[number]

export function tierFor(strategyName: string): Tier | null {
  return TIERS.find((t) => t.match === strategyName) ?? null
}

// Strategies that aren't cap tiers still show up in tables (Holdings rows are
// all `real_trading`, Reports groups by whatever ran). Raw internal names are
// jargon, so give the known ones a plain-English label and fall back to the
// raw name for anything user-created.
const OTHER_STRATEGY_LABELS: Record<string, string> = {
  real_trading: 'Your own holdings',
  sma_crossover: 'Moving-average crossover',
  long_term_value: 'Long-term value',
}

export function strategyLabel(strategyName: string): string {
  return tierFor(strategyName)?.label ?? OTHER_STRATEGY_LABELS[strategyName] ?? strategyName
}
