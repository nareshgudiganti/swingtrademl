# Fundamentals Vendor Decision

Date: 2026-09-13
Decides: which vendor backs the long-term stock picks model's fundamentals features (docs/superpowers/specs/2026-09-12-long-term-stock-picks-design.md §4).

**Research method note:** this evaluation was done via web search and page
fetches (WebSearch/WebFetch tools), not vendor sales calls or trial API
keys. Several vendor sites are JS-rendered and returned only page
metadata to the fetch tool, not full documentation content — where that
happened it is called out explicitly below rather than filled in with a
guess. Nothing in this document states a specific price, rate limit, or
API field name that was not actually found in a fetched page or search
result.

## Candidates evaluated

### Tijori Finance
- NSE/BSE coverage: Yes — an India-specific equity research platform. Per
  its own public description, it sources share price and financial data
  (balance sheet, P&L, cash flow, shareholding) "directly from approved
  data vendors at BSE & NSE," and separately scrapes supplementary
  operational metrics (market share, product/geography/raw-material
  exposure) that aren't part of formal filings.
- Point-in-time correctness: Unknown — no public API documentation exists
  to check against. Can't be assessed without vendor contact.
- Historical depth: Unknown — not published anywhere publicly accessible.
- API shape: **No public self-serve API found.** Tijori is a web
  research product (watchlists, alerts, feeds); nothing in search results
  or their site indicates a documented REST/SDK for programmatic access.
  Any integration would depend on an undisclosed partnership arrangement,
  not a product available today.
- Pricing: Not applicable/found — no public API pricing exists to quote.

### Trendlyne
- NSE/BSE coverage: Yes — an India-specific stock analysis platform with
  over 1,500 screenable fundamental/technical parameters per public
  marketing copy.
- Point-in-time correctness: Unknown — cannot be verified without API docs
  (see below).
- Historical depth: Not found in public sources.
- API shape: **No traditional REST API found.** Search results confirm
  Trendlyne is consumed through its web UI and subscription plans. One
  search result surfaced a very recently advertised "AI MCP plan" (from
  ₹299/mo, described as "market data for your AI") which suggests some
  programmatic/agent-facing access may be emerging, but there is no
  documentation available publicly describing its scope, fields, or
  point-in-time behavior — too immature/undocumented to evaluate as an
  integration target right now.
- Pricing: Retail web subscription plans exist (one source cites a paid
  tier around $10.42/mo), separate from the undocumented AI/MCP plan
  above. No API-specific pricing found.

### Financial Modeling Prep (FMP)
- NSE/BSE coverage: **Not confirmed, and there are real red flags against
  it.** FMP's own pricing-tier descriptions (via search result summaries
  of their docs) describe the Starter plan as covering "US coverage" with
  5 years of historical fundamentals, and the Premium plan as *adding* UK
  and Canada coverage (30 years depth) — India is not named as covered at
  any tier in what could be retrieved. Direct fetches of
  `site.financialmodelingprep.com/pricing-plans` and `/developer/docs`
  both returned HTTP 403 (blocked), so the full plan matrix could not be
  independently confirmed beyond these summaries — but nothing found
  anywhere supports the "global/APAC coverage includes India fundamentals"
  claim some marketing pages imply.
- Point-in-time correctness: Not evaluated — moot given the coverage gap
  above.
- Historical depth: 5 years (Starter) to 30 years (Premium) — but for the
  covered markets (US/UK/Canada), not confirmed for India.
- API shape: Real REST API with an official SDK/docs site — this part of
  the criteria is genuinely met, just apparently not for this market.
- Pricing: Free tier (500MB bandwidth) up to Enterprise (1TB+); exact
  India-relevant tier not identifiable since India isn't named as covered.

### Finnhub
- NSE/BSE coverage: **Claimed but unverified, with signs of weak practical
  support.** Finnhub's marketing describes "global fundamentals" and its
  general exchange list is said to include many world markets, but a
  concrete developer question on Finnhub's own GitHub issue tracker
  ("How to call an API with NSE Data (NSE INDIA)?", issue #363) went
  **unanswered** with no resolution — a real signal that NSE/India support
  is either undocumented or not actually productized, not just an
  isolated complaint. Direct fetches of Finnhub's exchange-list and
  pricing docs pages returned only page titles/meta text (JS-rendered),
  so this could not be independently confirmed either way beyond that
  signal.
- Point-in-time correctness: Finnhub does offer a "financials-as-reported"
  style endpoint concept for some markets per general knowledge of the
  product, but this could not be confirmed for NSE-listed names
  specifically given the coverage question above.
- Historical depth: Not confirmed for India.
- API shape: Real REST API with SDKs (confirmed via their public GitHub
  client libraries) — met in general, unverified for this market.
- Pricing: Has a published pricing page; specific numbers not retrievable
  (JS-rendered, blocked by fetch).

### FinEdge API (finedgeapi.com)
- NSE/BSE coverage: Explicitly claimed — the product's own tagline is
  "FinEdge Financial Data API | NSE & BSE Fundamentals, P&L, Balance
  Sheet & Cash Flow," and it is marketed specifically as an "Indian
  Financial Data API." Of every candidate found, this is the only one
  whose entire positioning is India-fundamentals-as-an-API.
- Point-in-time correctness: **Could not verify.** The documentation page
  (`/financial-data-api-documentation`) is JS-rendered and returned no
  crawlable content beyond the page title via the fetch tool — no
  endpoint list, field list, or restatement-handling policy could be
  read.
- Historical depth: Could not verify — same rendering limitation.
- API shape: Positioned as a real REST API ("via REST API" per search
  summaries), not a scrape target — but this claim comes from third-party
  summaries of the site, not directly confirmed API docs, since the docs
  page itself didn't render.
- Pricing: Could not verify — not found in any retrievable source.

### NSE/BSE official XBRL corporate filings (free fallback)
- NSE/BSE coverage: Unambiguous — this *is* the primary source. Confirmed
  via XBRL.org that all three Indian exchanges (BSE, NSE, and MSE) have
  adopted XBRL for listed-company filings, and SEBI mandates XBRL for
  quarterly financial results, annual financial statements, and BRSR/ESG
  reports. NSE also runs an "Integrated Filing" format (mandatory from Q4
  FY2024-25) consolidating P&L, related-party transactions, audit
  qualifications, and fund-deviation disclosures into one quarterly
  document per company.
- Point-in-time correctness: **The strongest of any candidate, definitionally.**
  Each filing is the figure as disclosed for that specific reporting
  period at the time it was filed — there is no vendor-side restatement
  layer to worry about, because this is the primary regulatory filing
  itself, not a downstream aggregation.
- Historical depth: Multi-year — XBRL filing has been mandated for Indian
  listed companies for well over a decade; NSE's own XBRL information page
  documents this history (page fetch of the details itself failed with a
  network reset during this research, but the mandate's existence and
  duration is independently confirmed via XBRL.org's dated announcement of
  BSE/NSE/MSE adoption).
- API shape: **Not a clean ratios API.** These are structured per-filing
  XBRL documents accessed through NSE's filing platforms (e.g. NEAPS) or
  per-company filing archives — real, official, and non-scraped, but
  requires building an XBRL parser and a per-company/per-period ingestion
  pipeline rather than calling a `GET /ratios` endpoint. This is the
  "heavier to parse" cost the design spec (§4) already anticipated.
- Pricing: Free.

## Decision

**No candidate found today cleanly satisfies all four spec §4 criteria at
once**, and per this document's own instructions, that gets said
explicitly rather than picked around:

- The two India-specific commercial products (Tijori, Trendlyne) have no
  documented, self-serve API today — Tijori's data pipeline is real and
  point-in-time-plausible, but not something this codebase can integrate
  against without a bespoke partnership; Trendlyne's only nascent
  programmatic offering is undocumented.
- The two global commercial APIs (FMP, Finnhub) are real, well-documented
  REST APIs in general, but neither has confirmable evidence of solid
  NSE/BSE coverage — FMP's own tier descriptions omit India entirely, and
  Finnhub has a public, unanswered "how do I even query NSE" question on
  its own issue tracker.
- FinEdge is the one vendor whose entire product is positioned exactly for
  this need (NSE/BSE fundamentals via API), but its documentation is not
  publicly crawlable, so point-in-time correctness — the single criterion
  the spec calls a "red flag, not a detail to skip" if unclear — cannot be
  confirmed from outside. It should not be integrated against on faith.

**Recommendation: use the NSE/BSE official XBRL filings as the Phase-2
data source**, per the design spec's own explicit fallback guidance (§4,
plan Task 1 Step 3): "if... no vendor cleanly satisfies point-in-time
correctness, say so explicitly and recommend the NSE/BSE official-filings
fallback rather than picking a vendor that fails this on a technicality."
That is the situation here — not because every vendor was disqualified on
a technicality, but because none could be *confirmed* to pass, and a
model trained on fundamentals of unconfirmed provenance is worse than
building a slightly heavier ingestion pipeline against data that is
correct by construction.

**Secondary recommendation:** before Task 6 starts building the XBRL
pipeline, spend a short amount of direct vendor contact (not further web
research) with FinEdge specifically — request their actual API docs and
ask their point-in-time/restatement policy directly. If it holds up, it
is a meaningfully lower-effort integration than parsing XBRL filings
directly, and budget is not a constraint per
[[project_ml_accuracy_roadmap]]. This document does not block on that
follow-up; it names the NSE/BSE fallback as the decision to build against
*now* because that path is verifiable today without waiting on a vendor
reply.

## Fields available

From NSE/BSE XBRL filings (quarterly financial results + Integrated
Filing format + annual reports), the following spec §5 fields map
directly to standard filing line items:

- **Revenue/earnings YoY growth**: computable directly — quarterly and
  annual P&L figures are core XBRL financial-results fields, and YoY
  growth is a derived calculation over consecutive filed periods.
- **Debt/equity trend**: computable from balance-sheet XBRL fields
  (borrowings, total equity) across filed periods.
- **Promoter holding change**: covered by shareholding-pattern
  disclosures, which are a separate mandated filing category alongside
  financial results — promoter holding % is explicitly disclosed
  quarterly.
- **ROE trend**: derivable (net profit / shareholders' equity) from the
  same P&L + balance-sheet fields above; not a directly-tagged XBRL field
  itself but a computed ratio, same as the swing model already computes
  derived ratios rather than consuming pre-computed ones (matches
  `ml/features.py`'s existing "ratios and percentages, not raw levels"
  convention).
- **Trailing P/E vs. sector median**: **partial gap.** The "earnings"
  half comes from filings; the "price" half requires joining against this
  codebase's own existing candle data (already available via
  `ml/dataset.py`); "sector median" additionally requires a peer-grouping
  scheme — this codebase does not yet have one (the sector_map.py module
  referenced in the plan's Task 3 sample code does not currently exist in
  this repo; confirmed by search — see Task 3's implementation notes in
  the accompanying commit). Task 6 will need to either build a minimal
  sector-grouping table or drop the "vs. sector median" comparison down to
  a raw trailing P/E feature initially.

## Integration notes for Task 6

- **Source**: NSE's XBRL filing platform (NEAPS) and per-company filing
  archives at nseindia.com, per the confirmed XBRL mandate covering BSE,
  NSE, and MSE. NSE's dedicated XBRL information page is
  `https://www.nseindia.com/static/companies-listing/xbrl-information`
  (a direct fetch during this research hit a network-level error, not a
  content finding — re-check this page directly when Task 6 starts, since
  it likely lists the exact filing-category taxonomy and any bulk-access
  mechanism NSE offers beyond individual filings).
- **Auth method**: None expected — these are public regulatory filings,
  not a metered API. No API key management needed, unlike every
  commercial candidate above.
- **Rate limits**: Not applicable in the API sense, but scraping etiquette
  still applies (reasonable request pacing) since this is NSE's own
  filing infrastructure, not a bulk-data drop.
- **Format**: XBRL (XML-based) documents per filing, tagged per SEBI's
  mandated taxonomy — Task 6 will need an XBRL parser (a mature, existing
  Python library, e.g. `python-xbrl` or `arelle`, rather than a
  hand-rolled XML walker) plus a mapping from XBRL tag names to this
  codebase's `FUNDAMENTALS_FEATURE_COLUMNS` names. The exact tag names
  were not enumerated in this research pass (would require opening an
  actual sample filing, which is Task 6's own first implementation step,
  not this spike's).
- **What Task 6 should NOT do**: integrate against FMP or Finnhub for
  Indian-company fundamentals given the coverage doubts above, and should
  not build against Tijori/Trendlyne/FinEdge without first getting
  written confirmation of point-in-time/restatement behavior directly
  from the vendor (a sales/support conversation, not a public docs page)
  — none of their public documentation was sufficient to clear that bar
  in this research pass.

## Sources

- [Tijori Finance data sourcing (Quora)](https://www.quora.com/From-Where-Tijori-finance-is-getting-all-data-means-which-API-they-are-using)
- [Tijori Finance features page](https://www.tijorifinance.com/features/)
- [Trendlyne subscription plans](https://trendlyne.com/subscription/plans/)
- [Trendlyne review — Strike.money](https://www.strike.money/reviews/trendlyne)
- [Financial Modeling Prep pricing plans](https://site.financialmodelingprep.com/pricing-plans)
- [Financial Modeling Prep developer docs](https://site.financialmodelingprep.com/developer/docs)
- [Finnhub](https://finnhub.io/)
- [Finnhub pricing](https://finnhub.io/pricing)
- [Finnhub GitHub issue #363 — NSE symbol question, unanswered](https://github.com/finnhubio/Finnhub-API/issues/363)
- [FinEdge Financial Data API](https://www.finedgeapi.com/)
- [FinEdge API documentation page](https://www.finedgeapi.com/financial-data-api-documentation)
- [NSE India XBRL filing information](https://www.nseindia.com/static/companies-listing/xbrl-information)
- [XBRL.org — India: BSE, NSE and MSE have adopted XBRL](https://www.xbrl.org/news/india-bse-nse-and-mse-have-adopted-xbrl/)
- [Screener.in third-party scraper (Apify) — confirms no official API](https://apify.com/scrapyx/screener-in-stocks-scraper/api/cli)
