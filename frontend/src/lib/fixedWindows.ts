// Fixed look-back and look-ahead windows that are NOT trading rules, so they are not served from
// /config/trading-rules. Each is named here with the place that really fixes it.

/** The two "price move after we sold" columns (price_5d / price_15d after exit): the checkpoints in
 *  backend api/v1/endpoints/portfolio.py (POST_EXIT_CHECKPOINTS). A measurement window of a report, not the plan. */
export const POST_EXIT_DAYS = { short: 5, long: 15 } as const

/** The upcoming-events window the backend words ("Nothing scheduled in the next 15 trading days",
 *  services/beginner_views.py). A look-ahead for company events, not the plan. */
export const EVENTS_LOOKAHEAD_TRADING_DAYS = 15
