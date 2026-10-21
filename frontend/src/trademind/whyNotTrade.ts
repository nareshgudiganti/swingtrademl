// "Why not TRADE?" (ux11): the stored reasons the brain did not make an idea a TRADE, in plain words.
//
// Display only. Built ONLY from what the brain stored on the decision (its word, reasons, the
// downgrade and an owner's overrule). Each stored line is matched to the rule that wrote it
// (backend brain/modules/m08_decide/rules.py, m08 engine draft, brain/constitution.py) and given a
// short plain sentence. A stored line that matches no known rule is shown as stored, never
// guessed at. Nothing stored → `whyNotTrade` returns [] and the screen says so.
//
// The raw model score is a ranking, not a chance (see honest.tsx): a "below the buy level" line
// is never shown with its numbers.

export type WhyKind =
  | 'owner_overrule'
  | 'below_buy_level'
  | 'no_clear_signal'
  | 'no_price'
  | 'risk_no_room'
  | 'risk_not_approved'
  | 'results_or_event'
  | 'exchange_watch_list'
  | 'weak_signals'
  | 'similar_cases_lost'
  | 'careful_market_downtrend'
  | 'weak_sector'
  | 'no_setup'
  | 'data_not_reliable'
  | 'buys_paused'
  | 'bad_plan'
  | 'other'

export type WhyItem = {
  kind: WhyKind
  /** The plain sentence shown first. */
  text: string
  /** What the brain stored, for "detail on tap". Null when the stored line would mislead (raw scores). */
  detail: string | null
}

/** The fields of a stored brain decision this needs (a BrainDecision, or one side of /brain/changes). */
export type DecisionLike = {
  word: string
  reasons: string[]
  downgraded_from?: string | null
  downgrade_reason?: string | null
  overruled_word?: string | null
  overrule_reason?: string | null
}

type Rule = { kind: Exclude<WhyKind, 'owner_overrule' | 'other'>; test: RegExp; text: string; showDetail: boolean }

// Order only matters when one line could match two rules: the first match wins.
const RULES: Rule[] = [
  {
    kind: 'risk_no_room',
    test: /risk check said no/i,
    text: "It looked good, but the account's safety limits had no room for it.",
    showDetail: true,
  },
  {
    kind: 'risk_not_approved',
    test: /risk check has not approved|risk gate did not approve|risk gate is not installed/i,
    text: 'The safety check did not approve buying it.',
    showDetail: false,
  },
  {
    kind: 'below_buy_level',
    test: /is below the buy level|needed to pay after costs/i,
    text: 'Its score was not high enough. The brain only buys stocks that rank above its buy level.',
    showDetail: false,
  },
  {
    kind: 'no_clear_signal',
    test: /^No opinion about this stock|signals do not favour buying/i,
    text: 'The brain had no clear signal to buy this stock today.',
    showDetail: false,
  },
  {
    kind: 'no_price',
    test: /^No price data/i,
    text: 'There was no price data for this stock yet.',
    showDetail: false,
  },
  {
    kind: 'exchange_watch_list',
    test: /exchange's watch list/i,
    text: 'The stock exchange has put this stock on its watch list, so the brain stays away.',
    showDetail: true,
  },
  {
    kind: 'results_or_event',
    test: /avoids new trades|results soon|event blackout/i,
    text: 'Company results or a similar event is coming up. The brain does not start new trades around these.',
    showDetail: true,
  },
  {
    kind: 'weak_signals',
    test: /signals are weak or disagree/i,
    text: 'Its signals were weak or pointed in different directions.',
    showDetail: false,
  },
  {
    kind: 'similar_cases_lost',
    test: /similar cases lost money/i,
    text: 'In the past, similar setups lost money on average.',
    showDetail: true,
  },
  {
    kind: 'careful_market_downtrend',
    test: /market is careful and this stock is falling/i,
    text: 'The market is in a careful mood and this stock is not in an up-trend.',
    showDetail: false,
  },
  {
    kind: 'weak_sector',
    test: /sector ranks .* outside the top/i,
    text: 'Its industry group is not one of the strongest right now.',
    showDetail: true,
  },
  {
    kind: 'no_setup',
    test: /no classic setup/i,
    text: 'It did not show a pattern the brain looks for (a dip in an up-trend, or a breakout with heavy buying).',
    showDetail: false,
  },
  {
    kind: 'data_not_reliable',
    test: /data is not reliable today|data quality was not checked/i,
    text: 'The price data was not reliable enough today to act on.',
    showDetail: true,
  },
  {
    kind: 'buys_paused',
    test: /owner paused new buys/i,
    text: 'New buys are paused.',
    showDetail: true,
  },
  {
    kind: 'bad_plan',
    test: /trade plan's prices are not usable/i,
    text: 'The buy, target and stop prices did not line up, so no trade was suggested.',
    showDetail: false,
  },
]

/** One stored line in plain words, or null when no known rule wrote it. */
export function classifyReason(line: string): WhyItem | null {
  const rule = RULES.find((r) => r.test.test(line))
  if (!rule) return null
  return { kind: rule.kind, text: rule.text, detail: rule.showDetail ? line : null }
}

/**
 * Why this idea is not a TRADE, from its stored fields only. [] for a TRADE, for a holding word, and
 * when the brain stored nothing that says why.
 */
export function whyNotTrade(d: DecisionLike): WhyItem[] {
  const word = d.overruled_word ?? d.word
  if (!['WATCH', 'WAIT', 'AVOID'].includes(word)) return []
  const items: WhyItem[] = []
  const seen = new Set<WhyKind>()
  const add = (item: WhyItem) => {
    if (item.kind !== 'other' && seen.has(item.kind)) return
    if (item.kind === 'other' && items.some((i) => i.kind === 'other' && i.text === item.text)) return
    seen.add(item.kind)
    items.push(item)
  }

  if (d.overruled_word) {
    add({
      kind: 'owner_overrule',
      text: `The owner changed this decision to ${d.overruled_word}.`,
      detail: d.overrule_reason?.trim() ? `Reason given: ${d.overrule_reason.trim()}` : 'No reason was given.',
    })
  }
  for (const line of d.reasons) {
    const item = classifyReason(line)
    if (item) add(item)
  }
  // The rule that lowered it last, when no known rule matched it: shown as stored, never guessed at.
  if (d.downgrade_reason && !classifyReason(d.downgrade_reason)) {
    add({ kind: 'other', text: d.downgrade_reason, detail: null })
  }
  // A WAIT/AVOID straight from the draft (never lowered) keeps its reason first.
  const brainOnly = items.filter((i) => i.kind !== 'owner_overrule')
  if (brainOnly.length === 0 && !d.downgraded_from && d.reasons[0] && d.word !== 'TRADE') {
    add({ kind: 'other', text: d.reasons[0], detail: null })
  }
  return items
}

/** A stable key for "did the reason change?": the kinds, and the stored text of unmatched lines. */
export function whyKey(items: WhyItem[]): string {
  return items
    .map((i) => (i.kind === 'other' ? `other:${i.text.replace(/[\d.,%₹+−-]+/g, '#')}` : i.kind))
    .sort()
    .join('|')
}

export const NOTHING_STORED = 'The brain did not store a reason for this decision.'
