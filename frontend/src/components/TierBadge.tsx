import type { Tier } from '../lib/tiers'

/** The colored, icon-bearing tier pill shared by every page that labels a
 * row with its cap-tier (Strategies, ML Models) — one definition so it looks
 * identical everywhere instead of three hand-rolled inline styles drifting
 * apart. */
export default function TierBadge({ tier }: { tier: Tier }) {
  return (
    <span
      className="badge"
      style={{
        background: `color-mix(in srgb, ${tier.color} 16%, transparent)`,
        color: tier.color,
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.3rem',
      }}
    >
      <tier.Icon />
      {tier.label}
    </span>
  )
}
