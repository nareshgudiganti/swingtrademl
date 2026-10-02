// SAMPLE DATA for the TradeMind screens. Every screen reads from here through
// useTradeMind(), so wiring the real backend later means replacing the body of
// that hook — no screen has to change. Nothing in this file is a live signal.

// The brain's settled vocabulary (Option A): ideas are TRADE / WATCH / WAIT /
// AVOID — never BUY/SELL.
export type Action = 'TRADE' | 'WATCH' | 'WAIT' | 'AVOID'

export type Point = { t: string; v: number }

export type Idea = {
  symbol: string
  name: string
  sector: string
  price: number
  changePct: number
  action: Action
  confidence: number // 0-100
  expectedR: number // reward per ₹1 risked
  timeframe: string
  setup: string
  target: number
  stop: number
  why: string[]
}

export type CandleBar = { t: string; o: number; h: number; l: number; c: number; vol: number }

// Deterministic pseudo-random so the sample charts look the same on every load.
function rng(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 4294967296
  }
}

export function series(
  seed: number,
  n: number,
  start: number,
  drift: number,
  vol: number,
  label: (i: number) => string = (i) => String(i),
): Point[] {
  const r = rng(seed)
  let v = start
  return Array.from({ length: n }, (_, i) => {
    v = v * (1 + drift + (r() - 0.5) * vol)
    return { t: label(i), v: Math.round(v * 100) / 100 }
  })
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function candles(seed: number, n: number, start: number, end: number): CandleBar[] {
  const r = rng(seed)
  const out: CandleBar[] = []
  let c = start
  const drift = Math.pow(end / start, 1 / n) - 1
  for (let i = 0; i < n; i++) {
    const o = c * (1 + (r() - 0.5) * 0.012)
    // A sideways stretch, then a breakout: the "breakout from a 3-month
    // range" story the screen tells.
    const phase = i < n * 0.7 ? 0 : drift * 3.2
    c = o * (1 + phase + (r() - 0.48) * 0.03)
    const h = Math.max(o, c) * (1 + r() * 0.012)
    const l = Math.min(o, c) * (1 - r() * 0.012)
    const vol = Math.round((0.6 + r() * 0.8 + (i > n * 0.7 ? 0.8 : 0)) * 1_000_000)
    const day = new Date(2026, 3, 1 + Math.round(i * 1.45))
    out.push({ t: `${day.getDate()} ${MONTHS[day.getMonth()]}`, o, h, l, c, vol })
  }
  // Pin the last close to the quoted price.
  const last = out[out.length - 1]!
  // Pin the last day to the quoted price and today's move.
  last.o = end / 1.024
  last.c = end
  last.h = end * 1.004
  last.l = last.o * 0.996
  return out
}

// ------------------------------------------------------------------ market --

export const marketState = {
  mood: 'BULLISH' as 'BULLISH' | 'CAUTION' | 'DEFENSIVE' | 'BEARISH',
  confidence: 82,
  signalsAnalysed: 250,
  headline: 'Most stocks are rising and big investors are buying — a good time to look for new trades.',
}

export const indices = [
  { name: 'NIFTY', value: 24631, changePct: 0.82 },
  { name: 'SENSEX', value: 81402, changePct: 0.76 },
  { name: 'INDIA VIX', value: 13.4, changePct: -2.1, hint: 'The "fear gauge" — lower means calmer markets' },
]

export const regimeHistory = [
  { mood: 'Bullish', color: '#2ee68a', share: 48 },
  { mood: 'Caution', color: '#ffb547', share: 22 },
  { mood: 'Defensive', color: '#ff7a45', share: 18 },
  { mood: 'Bearish', color: '#ff4d6a', share: 12 },
]

export const regimeTimeline = series(11, 60, 22800, 0.0014, 0.018, (i) =>
  i % 10 === 0 ? MONTHS[(3 + Math.floor(i / 10)) % 12]! : '',
).map((p, i) => ({ ...p, mood: i < 14 ? 3 : i < 24 ? 2 : i < 34 ? 1 : 0 }))

export const sectors = [
  { name: 'Auto', changePct: 3.2 },
  { name: 'Banking', changePct: 2.1 },
  { name: 'IT', changePct: 1.8 },
  { name: 'FMCG', changePct: 0.4 },
  { name: 'Pharma', changePct: -0.2 },
  { name: 'Metal', changePct: -0.8 },
  { name: 'Energy', changePct: -1.1 },
  { name: 'Realty', changePct: -1.4 },
]

export const breadth = { advancing: 1842, declining: 856, unchanged: 102 }

export const marketSignals = [
  { label: 'FII buying', hint: 'Foreign investors bought today', value: '+₹1,842 Cr', tone: 'pos' as const },
  { label: 'DII buying', hint: 'Indian funds bought today', value: '+₹1,210 Cr', tone: 'pos' as const },
  { label: 'Put/Call ratio', hint: 'Above 1 = traders expect a rise', value: '1.12', tone: 'neutral' as const },
  { label: 'VIX (lower)', hint: 'Fear gauge falling = calmer market', value: '13.4', tone: 'pos' as const },
  { label: 'Global markets', hint: 'US and Asia overnight', value: 'Positive', tone: 'pos' as const },
  { label: 'Crude oil', hint: 'Brent, $ per barrel', value: '$82.1', tone: 'neutral' as const },
]

export const marketEvents = [
  { date: '06 Oct', title: 'RBI policy decision', impact: 'High' },
  { date: '10 Oct', title: 'TCS quarterly results', impact: 'Medium' },
  { date: '14 Oct', title: 'India inflation (CPI)', impact: 'Medium' },
  { date: '17 Oct', title: 'Reliance quarterly results', impact: 'High' },
]

// ------------------------------------------------------------------- ideas --

type Row = [string, string, string, number, number, Action, number, number, string, string]

const ROWS: Row[] = [
  ['TATAMOTORS', 'Tata Motors', 'Auto', 982.5, 2.4, 'TRADE', 82, 1.8, '2-4 weeks', 'Breakout'],
  ['RELIANCE', 'Reliance', 'Energy', 2874.3, 0.6, 'WATCH', 68, 1.4, '2-6 weeks', 'Pullback'],
  ['HDFCBANK', 'HDFC Bank', 'Banking', 1621.4, 1.1, 'TRADE', 76, 1.6, '2-4 weeks', 'Trend'],
  ['INFY', 'Infosys', 'IT', 1482.2, -0.3, 'WATCH', 62, 1.3, '3-6 weeks', 'Consolidation'],
  ['LT', 'Larsen & Toubro', 'Infra', 3421.0, 1.4, 'TRADE', 74, 1.7, '2-5 weeks', 'Breakout'],
  ['ICICIBANK', 'ICICI Bank', 'Banking', 1243.3, 0.9, 'TRADE', 71, 1.5, '2-4 weeks', 'Pullback'],
  ['BHARTIARTL', 'Bharti Airtel', 'Telecom', 1184.5, 0.4, 'WATCH', 66, 1.4, '3-6 weeks', 'Trend'],
  ['SBIN', 'SBI', 'Banking', 782.1, 1.2, 'TRADE', 69, 1.6, '2-5 weeks', 'Breakout'],
  ['M&M', 'Mahindra & Mahindra', 'Auto', 2915.6, 1.9, 'TRADE', 73, 1.7, '2-4 weeks', 'Trend'],
  ['MARUTI', 'Maruti Suzuki', 'Auto', 12480.0, 0.8, 'TRADE', 70, 1.5, '3-5 weeks', 'Pullback'],
  ['TCS', 'TCS', 'IT', 4120.4, -0.2, 'WATCH', 61, 1.2, '3-6 weeks', 'Consolidation'],
  ['HCLTECH', 'HCL Tech', 'IT', 1688.9, 0.5, 'WATCH', 64, 1.3, '2-6 weeks', 'Trend'],
  ['AXISBANK', 'Axis Bank', 'Banking', 1172.3, 0.7, 'WATCH', 63, 1.3, '2-5 weeks', 'Pullback'],
  ['ITC', 'ITC', 'FMCG', 468.2, 0.2, 'WATCH', 60, 1.2, '3-6 weeks', 'Consolidation'],
  ['HINDUNILVR', 'Hindustan Unilever', 'FMCG', 2512.0, -0.1, 'WATCH', 58, 1.1, '4-6 weeks', 'Consolidation'],
  ['SUNPHARMA', 'Sun Pharma', 'Pharma', 1764.5, -0.4, 'WATCH', 59, 1.2, '3-6 weeks', 'Pullback'],
  ['TITAN', 'Titan', 'Consumer', 3388.0, 0.3, 'WATCH', 57, 1.1, '3-6 weeks', 'Trend'],
  ['ASIANPAINT', 'Asian Paints', 'Consumer', 2896.0, -0.6, 'WAIT', 52, 0.9, '—', 'No clear setup'],
  ['NTPC', 'NTPC', 'Energy', 362.4, -0.9, 'WAIT', 50, 0.9, '—', 'No clear setup'],
  ['WIPRO', 'Wipro', 'IT', 548.3, -0.5, 'WATCH', 56, 1.1, '3-6 weeks', 'Consolidation'],
  ['TATASTEEL', 'Tata Steel', 'Metal', 148.6, -1.6, 'AVOID', 38, 0.6, '—', 'Breakdown'],
  ['ADANIENT', 'Adani Enterprises', 'Metal', 2410.0, -2.2, 'AVOID', 34, 0.5, '—', 'Breakdown'],
  ['DLF', 'DLF', 'Realty', 812.5, -1.9, 'AVOID', 36, 0.6, '—', 'Downtrend'],
  ['ONGC', 'ONGC', 'Energy', 248.7, -1.3, 'AVOID', 40, 0.7, '—', 'Downtrend'],
]

const WHY: Record<string, string[]> = {
  Breakout: [
    'Price broke above its recent ceiling with heavy buying',
    'Its sector is one of the strongest today',
    'Overall market mood supports new buys',
    'Good reward compared with the risk',
  ],
  Pullback: [
    'A strong stock that dipped and is bouncing back',
    'Dip stopped at a level buyers defended before',
    'Its sector is holding up well',
  ],
  Trend: ['Has been rising steadily for weeks', 'Each dip has been bought quickly', 'Sector is steady'],
  Consolidation: ['Moving sideways in a tight range', 'Waiting for a clear move up before acting'],
  'No clear setup': ['No pattern worth acting on right now'],
  Breakdown: ['Fell below a level it held for months', 'Its sector is weak', 'Selling pressure is rising'],
  Downtrend: ['Making lower lows for weeks', 'Its sector is among the weakest'],
}

export const ideas: Idea[] = ROWS.map(([symbol, name, sector, price, ch, action, conf, r, tf, setup]) => {
  const riskPct = 0.07
  return {
    symbol,
    name,
    sector,
    price,
    changePct: ch,
    action,
    confidence: conf,
    expectedR: r,
    timeframe: tf,
    setup,
    target: Math.round(price * (1 + riskPct * Math.max(r, 1)) * 10) / 10,
    stop: Math.round(price * (1 - riskPct) * 10) / 10,
    why: WHY[setup] ?? [],
  }
})

export const featured = ideas[0]!

// Tata Motors gets the hand-tuned numbers from the design.
featured.target = 1140
featured.stop = 912

export const todaysInsights = [
  { text: 'Auto sector showing strength', tone: 'pos' as const },
  { text: 'Reliance at key resistance', tone: 'pos' as const },
  { text: '3 new high-probability setups', tone: 'pos' as const },
  { text: 'Market breadth improving', tone: 'pos' as const },
  { text: 'Keep position size moderate', tone: 'neg' as const },
]

// --------------------------------------------------------- stock analysis --

export const stockScores = [
  { name: 'Technical score', value: 78, verdict: 'Bullish', hint: 'What the price chart says' },
  { name: 'Fundamental score', value: 72, verdict: 'Good', hint: 'How healthy the business is' },
  { name: 'AI sentiment', value: 84, verdict: 'Positive', hint: 'Tone of recent news and reports' },
  { name: 'Overall score', value: 82, verdict: 'High confidence', hint: 'All of the above combined' },
]

export const stockAnalysis = [
  'Breakout from 3-month range',
  'High volume confirmation',
  'Auto sector showing strength',
  'Favorable market regime',
  'Good risk-reward setup',
]

export const technicals = [
  { name: 'Trend (50-day average)', value: 'Above — rising', tone: 'pos' as const, plain: 'Price is above its 50-day average' },
  { name: 'Momentum (RSI 14)', value: '64', tone: 'pos' as const, plain: 'Strong, but not over-heated (70+)' },
  { name: 'MACD', value: 'Bullish cross', tone: 'pos' as const, plain: 'Short-term trend just turned up' },
  { name: 'Volume vs 20-day avg', value: '1.9×', tone: 'pos' as const, plain: 'Almost double the usual buying' },
  { name: 'Distance from 52-week high', value: '−3.1%', tone: 'neutral' as const, plain: 'Close to its yearly best' },
  { name: 'Daily swing (ATR)', value: '₹24.6', tone: 'neutral' as const, plain: 'Typical day moves about 2.5%' },
]

export const fundamentals = [
  { name: 'Sales growth (1y)', value: '+14.2%', tone: 'pos' as const },
  { name: 'Profit growth (1y)', value: '+21.8%', tone: 'pos' as const },
  { name: 'Price / earnings', value: '9.8', tone: 'pos' as const },
  { name: 'Debt / equity', value: '1.1', tone: 'neutral' as const },
  { name: 'Return on equity', value: '18.4%', tone: 'pos' as const },
  { name: 'Promoter holding', value: '46.4%', tone: 'neutral' as const },
]

export const news = [
  { when: '2h ago', title: 'Tata Motors September sales up 12% year on year', tone: 'pos' as const, source: 'Business Standard' },
  { when: '1d ago', title: 'JLR order book stays strong ahead of festive season', tone: 'pos' as const, source: 'Mint' },
  { when: '2d ago', title: 'Auto index hits record high on strong monthly numbers', tone: 'pos' as const, source: 'Economic Times' },
  { when: '4d ago', title: 'Steel prices ease, lowering input costs for carmakers', tone: 'neutral' as const, source: 'Reuters' },
  { when: '6d ago', title: 'Analysts flag EV margin pressure in coming quarters', tone: 'neg' as const, source: 'Moneycontrol' },
]

export const optionsView = {
  maxPain: 960,
  pcr: 1.18,
  callWall: 1000,
  putWall: 940,
  ivRank: 32,
}

// --------------------------------------------------------------- portfolio --

export const portfolio = {
  value: 1248500,
  gain: 137200,
  gainPct: 12.4,
  positions: 8,
  cashPct: 42,
  riskUsedPct: 58,
  maxDrawdownPct: -4.2,
  health: 72,
  equity: series(21, 70, 1080000, 0.0021, 0.016, (i) => (i % 14 === 0 ? MONTHS[(4 + Math.floor(i / 14)) % 12]! : '')),
}

export const allocation = [
  { name: 'Banking', pct: 28, color: '#4f8cff' },
  { name: 'Auto', pct: 18, color: '#2ee68a' },
  { name: 'IT', pct: 15, color: '#8b5cf6' },
  { name: 'FMCG', pct: 12, color: '#e04fd6' },
  { name: 'Energy', pct: 10, color: '#ffb547' },
  { name: 'Others', pct: 17, color: '#33d6ff' },
]

export const holdings = [
  { symbol: 'TATAMOTORS', name: 'Tata Motors', pnlPct: 18.4, qty: 60, avg: 829.9 },
  { symbol: 'RELIANCE', name: 'Reliance', pnlPct: 6.2, qty: 25, avg: 2706.5 },
  { symbol: 'HDFCBANK', name: 'HDFC Bank', pnlPct: 12.1, qty: 40, avg: 1446.4 },
  { symbol: 'INFY', name: 'Infosys', pnlPct: -2.1, qty: 30, avg: 1514.0 },
  { symbol: 'LT', name: 'Larsen & Toubro', pnlPct: 8.6, qty: 12, avg: 3150.1 },
  { symbol: 'ICICIBANK', name: 'ICICI Bank', pnlPct: 4.3, qty: 50, avg: 1192.0 },
  { symbol: 'SBIN', name: 'SBI', pnlPct: -1.2, qty: 80, avg: 791.6 },
  { symbol: 'BHARTIARTL', name: 'Bharti Airtel', pnlPct: 3.4, qty: 35, avg: 1145.5 },
]

export const suggestions = [
  { text: 'Banking is 28% of your money — close to the 25% comfort limit', tone: 'warn' as const },
  { text: 'Infosys is below your buy price; the brain says keep watching, not sell', tone: 'neutral' as const },
  { text: 'You have 42% cash — room for 2 more trades at normal size', tone: 'pos' as const },
]

// -------------------------------------------------------------- positions --

export const position = {
  symbol: 'TATAMOTORS',
  entry: 925.4,
  current: 982.5,
  pnlPct: 6.2,
  sizePct: 5,
  target: 1140,
  stop: 912,
  expectedR: 1.8,
  timeframe: '2-4 weeks',
  enteredOn: '04 Sep 2026',
  daysHeld: 20,
}

export const pathData = (() => {
  const actual = series(41, 22, 925, 0.003, 0.02)
  const labels = ['May', '', '', '', 'Jun', '', '', '', 'Jul', '', '', '', 'Aug', '', '', '', 'Sep', '', '', '', '', 'Oct']
  return Array.from({ length: 34 }, (_, i) => ({
    t: labels[i] ?? '',
    expected: Math.round(925 * Math.pow(1140 / 925, i / 33) * 10) / 10,
    actual: i < actual.length ? actual[i]!.v : null,
    upper: Math.round(925 * Math.pow(1200 / 925, i / 33) * 10) / 10,
    lower: Math.round(925 * Math.pow(980 / 925, i / 33) * 10) / 10,
  }))
})()

export const reevalTriggers = [
  { text: 'Price breaks below ₹940', level: 'Normal' },
  { text: 'Sector momentum weakens', level: 'Watch' },
  { text: 'Market mood changes to Defensive', level: 'High' },
  { text: 'Quarterly results on 24 Oct (big-move day)', level: 'Watch' },
]

export const exitPlan = [
  { step: 'First target', price: '₹1,040 (+5%)', action: 'Sell half, lock in profit' },
  { step: 'Protect the rest', price: 'Move stop to ₹925', action: 'Worst case: break even' },
  { step: 'Final target', price: '₹1,140 (+16%)', action: 'Sell the rest' },
  { step: 'Stop loss', price: '₹912 (−7%)', action: 'Sell everything, no questions' },
  { step: 'Time stop', price: '30 calendar days', action: 'Sell if nothing has happened' },
]

export const openPositions = holdings.slice(0, 6).map((h, i) => ({
  ...h,
  pnlPct: h.symbol === position.symbol ? position.pnlPct : h.pnlPct,
  status: (['On track', 'On track', 'Ahead', 'Behind', 'On track', 'Watch'] as const)[i],
  days: [20, 12, 9, 15, 6, 3][i],
}))

// --------------------------------------------------------------- AI chain --

export const reasoningChain = [
  { title: 'Market state', sub: 'Bullish, improving breadth', detail: 'Most stocks are rising (1,842 up vs 856 down) and big investors are net buyers. The brain allows new trades at normal size.' },
  { title: 'Situation recognition', sub: 'Breakout setup with volume', detail: 'Price closed above the top of its 3-month range on almost double the usual volume — a classic breakout.' },
  { title: 'Evidence analysis', sub: 'Technical + Fundamental + News', detail: 'Chart signals agree (trend, momentum, volume). Profits are growing. Recent news is mostly positive.' },
  { title: 'Similar cases', sub: '14 similar situations (78% success)', detail: 'In 14 past cases that looked like this, 11 reached their target before their stop.' },
  { title: 'ML predictions', sub: '82% probability of upward move', detail: 'The model gives an 82% chance of an up-move within the time window. (Sample figure — real figures will be calibrated.)' },
  { title: 'Risk check', sub: 'Within risk limits, good R:R', detail: 'Adding this keeps total risk at 58% of the limit and Auto at 18% of the portfolio (limit 25%).' },
  { title: 'Decision', sub: 'TRADE — High confidence', detail: 'All checks passed. Suggested size: 4-6% of the portfolio.' },
]

export const keyFactors = [
  { name: 'Technical breakout', impact: 'High' },
  { name: 'Sector strength', impact: 'High' },
  { name: 'Market regime', impact: 'High' },
  { name: 'Fundamental growth', impact: 'Medium' },
  { name: 'Historical success rate', impact: 'High' },
]

export const modelOutputs = [
  { model: 'Trend model', score: 0.84, vote: 'Up' },
  { model: 'Mean-reversion model', score: 0.58, vote: 'Neutral' },
  { model: 'Sentiment model', score: 0.79, vote: 'Up' },
  { model: 'Sector-rotation model', score: 0.81, vote: 'Up' },
  { model: 'Volatility model', score: 0.66, vote: 'Up' },
]

// ------------------------------------------------------------------- risk --

export const riskLimits = [
  { name: 'Total risk used', used: 58, limit: 100, unit: '%', plain: 'How much of your allowed risk is in use' },
  { name: 'Biggest sector (Banking)', used: 28, limit: 25, unit: '%', plain: 'No sector should be more than 25%' },
  { name: 'Open positions', used: 8, limit: 10, unit: '', plain: 'Most trades held at once' },
  { name: 'Drawdown from peak', used: 4.2, limit: 15, unit: '%', plain: 'Trading stops automatically at 15%' },
  { name: 'Loss today', used: 0.4, limit: 2, unit: '%', plain: 'New trades pause after a 2% daily loss' },
]

export const riskChecks = [
  { name: 'Market allows new trades', ok: true },
  { name: 'Data is fresh (today)', ok: true },
  { name: 'Broker connected', ok: true },
  { name: 'Sector limit', ok: false, note: 'Banking over 25% — no new banking trades' },
  { name: 'Daily loss limit', ok: true },
  { name: 'Drawdown halt', ok: true },
]

export const drawdownSeries = series(51, 70, 0, 0, 0).map((_, i) => ({
  t: i % 14 === 0 ? MONTHS[(4 + Math.floor(i / 14)) % 12]! : '',
  v: -Math.abs(Math.round((Math.sin(i / 6) * 2.4 + Math.sin(i / 2.3) * 0.9) * 10) / 10),
}))

// ------------------------------------------------------------- experience --

export const outcomeMix = [
  { name: 'Profitable', pct: 78, color: '#2ee68a' },
  { name: 'Small loss', pct: 14, color: '#33d6ff' },
  { name: 'Large loss', pct: 8, color: '#e04fd6' },
]

export const keyLearnings = [
  'Breakout setups work well in a bullish market',
  'Stop loss is critical in volatile markets',
  'Auto sector shows 72% link with the overall market',
  'Average holding period: 18 trading days',
]

export const similarCases = [
  { date: 'Mar 2023', symbol: 'TATAMOTORS', situation: 'Breakout + Volume', regime: 'Bullish', outcomePct: 16.2, r: 2.1 },
  { date: 'Jan 2023', symbol: 'M&M', situation: 'Breakout + Volume', regime: 'Bullish', outcomePct: 12.4, r: 1.8 },
  { date: 'Oct 2022', symbol: 'TATAMOTORS', situation: 'Consolidation breakout', regime: 'Caution', outcomePct: -4.2, r: -0.6 },
  { date: 'Aug 2022', symbol: 'M&M', situation: 'Breakout + Volume', regime: 'Bullish', outcomePct: 18.6, r: 2.3 },
  { date: 'May 2022', symbol: 'MARUTI', situation: 'Breakout + Volume', regime: 'Bullish', outcomePct: 9.8, r: 1.4 },
  { date: 'Feb 2022', symbol: 'EICHERMOT', situation: 'Breakout + Volume', regime: 'Caution', outcomePct: -3.1, r: -0.5 },
  { date: 'Nov 2021', symbol: 'TATAMOTORS', situation: 'Breakout + Volume', regime: 'Bullish', outcomePct: 21.4, r: 2.9 },
  { date: 'Jul 2021', symbol: 'BAJAJ-AUTO', situation: 'Breakout + Volume', regime: 'Bullish', outcomePct: 7.6, r: 1.1 },
]

export const memoryStats = {
  cases: 14,
  successRate: 78,
  avgGainPct: 9.4,
  avgLossPct: -3.8,
  totalMemories: 2486,
}

// ---------------------------------------------------------------- ML lab --

export const modelPerf = { accuracy: 82, profitFactor: 1.8, annualReturn: 24.3, maxDrawdown: -12.1 }

export const strategyEquity = series(61, 80, 100, 0.0028, 0.03, (i) =>
  i % 16 === 0 ? String(2021 + Math.floor(i / 16)) : '',
).map((p, i) => ({ ...p, bench: Math.round(100 * Math.pow(1.0016, i) * 100) / 100 }))

export const mlModels = [
  { name: 'Trend model', accuracy: 82, status: 'Active' },
  { name: 'Mean reversion', accuracy: 68, status: 'Shadow' },
  { name: 'Sentiment model', accuracy: 71, status: 'Active' },
  { name: 'Sector rotation', accuracy: 74, status: 'Active' },
  { name: 'Volatility model', accuracy: 69, status: 'Shadow' },
]

export const recentPredictions = [
  { symbol: 'TATAMOTORS', prediction: 'UP', confidence: 82, actualPct: 2.4, status: 'Correct' },
  { symbol: 'RELIANCE', prediction: 'UP', confidence: 71, actualPct: 1.8, status: 'Correct' },
  { symbol: 'HDFCBANK', prediction: 'UP', confidence: 76, actualPct: -0.5, status: 'Incorrect' },
  { symbol: 'INFY', prediction: 'DOWN', confidence: 64, actualPct: -1.2, status: 'Correct' },
  { symbol: 'LT', prediction: 'UP', confidence: 74, actualPct: 1.1, status: 'Correct' },
  { symbol: 'SBIN', prediction: 'UP', confidence: 69, actualPct: null, status: 'Pending' },
]

export const featureImportance = [
  { name: 'Price momentum', pct: 24 },
  { name: 'Volume', pct: 18 },
  { name: 'Sector strength', pct: 15 },
  { name: 'Market sentiment', pct: 12 },
  { name: 'Technical indicators', pct: 10 },
  { name: 'Volatility', pct: 8 },
  { name: 'Fundamentals', pct: 7 },
  { name: 'Market breadth', pct: 6 },
]

export const backtests = [
  { strategy: 'Breakout + Volume', trades: 214, winRate: 58, avgR: 1.4, returnPct: 31.2, dd: -9.8 },
  { strategy: 'Pullback in trend', trades: 168, winRate: 61, avgR: 1.2, returnPct: 24.5, dd: -8.1 },
  { strategy: 'Sector rotation', trades: 92, winRate: 54, avgR: 1.6, returnPct: 19.8, dd: -11.4 },
  { strategy: 'Mean reversion', trades: 141, winRate: 63, avgR: 0.8, returnPct: 9.6, dd: -7.2 },
]

// ------------------------------------------------------------------ hook --

/** @deprecated Sample data only — no screen should call this once it's on
 * live data. Use the hooks and mappers in `./live.ts` instead. Removed in
 * Task 5 once the last screen stops importing it. */
export function useTradeMind() {
  // Later: swap for react-query calls against /brain/* — same shape.
  return {
    isDemo: true,
    marketState,
    indices,
    ideas,
    featured,
    portfolio,
  }
}

export function findIdea(symbol: string | undefined): Idea {
  return ideas.find((i) => i.symbol === symbol) ?? featured
}
