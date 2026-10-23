// The market and prices chip in the top bar, on every TradeMind page: one chip that says whether the market is open
// ("Market closed · opens Mon 26 Oct, 9:15 am") and whether the prices behind the page are fresh or out of date
// ("Prices from today's close"). It used to be two chips side by side, which crowded the bar. Display only.
// The prices wording and the trading-day counting live in pricesAge.ts; the market words come from the server.
// Narrower screens show less: only the market's first words on a laptop, no market part below about 1530px, and the
// short prices text on a phone (see trademind.css).
import { useMarketSession } from './live'
import { istToday, pricesAge } from './pricesAge'

const MARKET_HOURS = 'Indian stock market (NSE) hours, 9:15 am to 3:30 pm on trading days'

export default function PricesBadge() {
  const market = useMarketSession()
  if (!market.data) return null
  const m = market.data
  const age = pricesAge({
    latestCandleDate: m.latest_candle_date ?? null,
    today: m.today ?? istToday(new Date()),
    recentClosedTradingDays: m.recent_closed_trading_days ?? [m.last_closed_trading_day],
  })
  // Out-of-date prices are the warning that matters most, so amber wins; otherwise green while the market is open.
  const tone = age.tone === 'stale' ? 'tm-asof-stale' : m.state === 'open' ? 'tm-asof-open' : ''
  const marketState = m.plain.split(' · ')[0]
  const marketTitle = (m.calendar_warning ?? MARKET_HOURS).replace(/\.$/, '')
  return (
    <span
      className={`tm-asof ${tone}`}
      title={`${m.plain}. ${marketTitle}.\n${age.detail}`}
      aria-label={`${m.plain}. ${age.label}. ${age.detail}`}
      data-testid="prices-badge"
    >
      <span className="tm-asof-market" data-testid="market-part">
        <span className="tm-asof-market-full">{m.plain}</span>
        {/* On a laptop-width screen only the first words ("Market closed"); the full text is in the tooltip. */}
        <span className="tm-asof-market-short" aria-hidden="true">
          {marketState}
        </span>
        <span aria-hidden="true"> · </span>
      </span>
      <span className="tm-asof-long">{age.label}</span>
      <span className="tm-asof-short" aria-hidden="true">
        {age.short}
      </span>
    </span>
  )
}
