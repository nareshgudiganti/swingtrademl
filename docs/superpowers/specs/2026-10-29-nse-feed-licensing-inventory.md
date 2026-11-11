# Data feed compliance and licensing inventory (production)

**Date:** 2026-10-29 · **Asked by:** owner ("compliance and licensing inventory for every NSE feed used in
production, citing exact source terms. No paid subscription or expanded data collection without approval.")
· **Builds on:** `docs/superpowers/specs/2026-10-29-r0-data-feasibility-report.md` (R0) ·
**Links to:** `docs/compliance/2026-10-21-sebi-d0a-briefing-pack.md` (D0a)

**Status:** desk research only. No code, config, test, protocol or evidence file was changed. Nothing was
bought, no one was contacted, nothing was stopped. Each terms document was fetched once, by hand.

> **This is not legal advice.** It sets out what the code does and what the published terms say, word for
> word. Whether a clause applies to TradeMind, and what follows if it does, is for a lawyer and a SEBI
> compliance professional to decide. Section 7 lists the questions for them.

---

## 0. Summary table

How to read the three use columns:
- **(a) Own research:** the owner looks at the data privately, with no other user involved.
- **(b) Automated decisions:** a program uses the data to decide something (v1 entry filter, brain labels,
  paper orders). Exchanges call this "non-display" use.
- **(c) Shown to other users:** the data, or something worked out from it, appears on a screen or in a
  message for anyone besides the owner. Today that means the tester `vijay`, the two secondary logins, and
  later the invited pilot users.

Labels: **OK** = permitted (quote given) · **OK-if** = permitted with conditions · **NO-without-consent**
= prohibited unless the owner gets written consent or a licence · **UNCLEAR** = the terms do not settle it.

| # | Feed (prod) | Source | (a) Own research | (b) Automated decisions | (c) Shown to other users | What depends on it |
|---|---|---|---|---|---|---|
| N1 | Daily bhavcopy: delivery %, series EQ/BE/BZ | NSE archive file | **NO-without-consent** (scripted collection) | **NO-without-consent** + non-display policy UNCLEAR | **NO-without-consent** | v1 entry filter `avoid.py` (BE/BZ), M12 delivery signal (shadow), M01 freshness |
| N2 | Bulk and block deals | NSE archive file | NO-without-consent | NO-without-consent | NO-without-consent | M12 deal signal (shadow) |
| N3 | FII/DII daily flows | NSE internal JSON API | NO-without-consent | NO-without-consent | NO-without-consent | M10 market mode (can set DEFENSIVE), banner text |
| N4 | Results calendar | NSE internal JSON API | NO-without-consent | NO-without-consent | NO-without-consent | v1 `avoid.py` 3-day results blackout, M13 (ON) → AVOID, holdings health, "upcoming events" screen |
| N5 | Corporate actions | NSE internal JSON API | NO-without-consent | NO-without-consent | NO-without-consent | v1 `avoid.py` 2-day blackout, M12/M13 "price reset", M01, `split_check`, experiments scorer (evidence) |
| N6 | ASM / GSM surveillance lists | NSE internal JSON API | NO-without-consent | NO-without-consent | NO-without-consent | v1 `avoid.py`, M13 restrictions |
| N7 | KEI announcements and shareholding | NSE quote page + internal JSON API | NO-without-consent | n/a (display only) | **NO-without-consent** | Company and news tab only |
| K1 | Daily candles (stocks, NIFTY 50, sector indices, INDIA VIX) | Zerodha Kite Connect | **OK-if** (paid plan, personal use); storing them is **UNCLEAR** | **UNCLEAR** (paper / "mock trading" clause; possible NSE non-display fee) | **NO-without-consent** | Everything: v1 models, all brain modules, charts, paper fills |
| K2 | Live quotes every 60 s | Kite Connect | OK-if | UNCLEAR (same as K1) | **NO-without-consent** | Paper exits, live prices on screens |
| K3 | Instrument list (weekly) | Kite Connect | OK-if | OK-if | Low risk (reference data), UNCLEAR | Symbol → token mapping |
| K4 | Owner's own holdings, positions, trades, margins, orders | Kite Connect | **OK** | OK-if (fully automated orders need exchange approval) | Owner only by design: OK. Showing it to anyone else: not allowed | My Holdings, fill capture, holdings sync |
| K5 | Scripted Kite login (password + TOTP) | kite.zerodha.com web login | **UNCLEAR** | UNCLEAR | n/a | Unattended daily login |
| A1 | Mutual fund NAVs (NAVAll.txt) | AMFI website | **OK-if** (personal, non-commercial); storing the whole file is UNCLEAR | n/a (valuation only) | **NO-without-consent** if shown beyond the account owner | Mutual fund holdings value |
| — | Telegram (outbound only) | api.telegram.org | Not a data source. Messages carry values derived from N/K feeds to the owner's one chat | — | Only the owner today | Alerts |
| — | Google sign-in | Google OAuth | Not a data source (identity only) | — | — | Login |

**Not used in production (checked):** BSE, niftyindices.com, any news/RSS feed, Yahoo or other price sites.
`core/holidays.py` only cites the NSE holiday page in a comment and does not fetch it.

**The three points the owner most needs to see:**
1. **All seven NSE feeds (N1–N7) are collected by a program from NSE's website and internal APIs.** NSE's
   website terms forbid that whatever the purpose, and add nothing that makes an exception for small
   volumes or private use. R0 already flagged this.
2. **Kite Connect's terms forbid using its data in "virtual/mock trading apps"**, and forbid showing it to
   "any third party". Production runs paper trading on Kite prices, and a tester trades a pretend-money book
   on them. This is new; R0 did not look at the Kite terms.
3. **NSE's website terms also forbid using its data for "virtual trading or simulation activities".**
   N1, N4, N5 and N6 feed the v1 entry filter, which decides paper trades.

---

## 1. Every external feed production pulls (from code)

Schedule times are IST, weekdays, from `backend/src/swing_trade_ml/workers/scheduler.py`. Volumes are
worked out from the code. None of them were measured on prod.

### 1.1 NSE feeds: `services/market_feeds.py`, job `job_daily_market_feeds` (`workers/jobs.py:323-350`)

Runs at **08:30** (`scheduler.py:175-180`), **19:20** (`:167-172`) and **22:05** "final" alarm run
(`:188-193`, `jobs.py:373-374`). Every run calls `run_daily_feeds` (`market_feeds.py:343-373`). All
requests send `User-Agent: Mozilla/5.0` (`:54-55`). The code comment says: "NSE serves a bot-blocking page
to clients without a browser-like agent."

| # | URL (file:line) | Data | Volume per day | Stored in | Used by | Shown to users? |
|---|---|---|---|---|---|---|
| N1 | `https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv` (`market_feeds.py:41`, loader `:135-141`) | Every NSE security's close, volume, turnover, trades, **delivery qty / %**, series. Only EQ/BE/BZ kept (`:59`) | 1 new file per day. The 08:30 and 19:20 runs also call `backfill_history_step` (`jobs.py:338`, `market_feeds.py:406-428`): **up to 120 files per run**, until 400 days of history are stored. Once that history is complete, ≈1 file a day | `daily_delivery` | v1 `avoid.py:48-55` (BE/BZ → refuse entry), called from `services/risk.py:645`; brain `reader.delivery_rows` (`brain/reader.py:229`) → **M12** (`m12_stock/module.py:69`, default mode SHADOW `:58`); M01 feed freshness (`brain/connectors.py:36`) | Not shown directly. Feed dates and row counts at `/feeds/status` (`api/v1/endpoints/market_data.py:128-131`). M12 lines ("delivery high") appear on cards only if M12 is switched out of shadow |
| N2 | `https://nsearchives.nseindia.com/content/equities/bulk.csv`, `…/block.csv` (`:42-43`, `:181-187`) | That day's bulk and block deals: client name, side, qty, price | 2 files × 3 runs | `block_deals` | `reader.deal_rows` (`reader.py:250`) → M12 (`m12/module.py:71`, shadow) | Same as N1 |
| N3 | `https://www.nseindia.com/api/fiidiiTradeReact` (`:44`, `:212-220`) | FII and DII buy/sell/net for the latest day | 1 call × 3 runs | `institutional_flows` | `reader.fii_net` (`reader.py:347`) → **M10** market judge (`m10_market/judge.py:92-96,133`): FII selling can turn NORMAL into **DEFENSIVE** | Yes, as words: the banner reason "Foreign investors (FIIs) sold on at least 4 of the last 5 days…" (`judge.py:94`) is shown to everyone who can see the Today banner |
| N4 | `https://www.nseindia.com/api/event-calendar?index=equities&from_date=…&to_date=…` (`:45`, `:267-283`), 21-day window | Board-meeting dates whose purpose mentions results | 1 call × 3 runs | `upcoming_events` (kind `results`) | v1 `avoid.py:57-72` (3-day results blackout); **M13** (`m13_news/module.py:41`, default **ON** `:32`) → AVOID; `holdings_health.py:299-338`; brain `reader.event_rows` (`reader.py:202`) | **Yes:** "upcoming events" endpoint (`api/v1/endpoints/beginner.py:45`, `services/beginner_views.py:140-152,430`); card lines such as "Results on 14 Oct."; refusal reasons |
| N5 | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=…&to_date=…` (`:46-48`) | Ex-dates of splits, bonuses, rights, demergers… (`:227`) | 1 call × 3 runs | `upcoming_events` (kind `corporate_action`) | v1 `avoid.py:74-89` (2-day blackout); M12/M13 "price reset"; M01 (`m01_quality/module.py:45`); `services/split_check.py:65`; experiments scorer (`services/experiments/scorer.py:137,182`) — **evidence** | Yes, same endpoint and cards as N4 |
| N6 | `https://www.nseindia.com/api/reportASM`, `…/api/reportGSM` (`:50-51`, `:306-315`) | NSE surveillance lists with stage | 2 calls × 3 runs | `trading_restrictions` | v1 `avoid.py:32-46`; M13 restrictions (`reader.py:214`) | Yes, as refusal reasons ("The exchange has put X on its extra-watch list…") |

Steady state is roughly 8 requests per run, about **25 NSE requests a day**. While the history backfill is
still filling, it can add up to 240 more files a day.

### 1.2 NSE company filings: `services/company_filings.py`, job `job_company_filings` (`jobs.py:353-370`)

Runs at **19:40** (`scheduler.py:182-187`) for `COMPANY_SYMBOLS = ("KEI",)` (`company_filings.py:32`).

| # | URL (file:line) | Data | Volume | Stored | Used by | Shown? |
|---|---|---|---|---|---|---|
| N7 | `https://www.nseindia.com/get-quotes/equity?symbol=KEI` (cookie fetch, `:34`, `:135`), then `https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=KEI` (`:35`) and `https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol=KEI` (`:36`). Sends a full Chrome User-Agent (`:37-41`) and a Referer (`:136`) | Up to 60 announcements (time, category, summary, PDF link); promoter vs public shareholding by quarter | 3 requests a day | `CompanyAnnouncement` / `CompanyShareholding` tables (`db/models/company.py`) | Nothing in decisions. The module docstring says "Display only" (`:7`) | **Yes:** Company and news tab, `/company/{symbol}` (`api/v1/endpoints/company.py:19-22`), for any logged-in user. Each announcement links to the NSE PDF on nsearchives |

### 1.3 Zerodha Kite Connect: `brokers/kite.py`, `services/ingestion.py`

| # | Call (file:line) | Schedule | Data | Stored | Used by | Shown? |
|---|---|---|---|---|---|---|
| K1 | `kite.historical_data` (`kite.py:565-576`) via `ingestion.backfill_instrument` (`ingestion.py:388`) | `daily_ingest` 15:40 (`scheduler.py:122-127`, `jobs.py:377-440`): watchlist, every strategy's symbol list, NIFTY 50, sector indices and INDIA VIX (`ingestion.py:150-251`) | Daily OHLCV (and intraday where configured) | `candles` (TimescaleDB), permanently | v1 models and signals; **all** brain modules through `DatedReader`; paper fills and P&L; evidence ledgers | **Yes:** charts, stock pages, prices on Today, portfolio values, for every logged-in user, including the tester |
| K2 | `kite.quote` (`kite.py:553-557`) via `ingestion.refresh_quotes` (`ingestion.py:469-509`); `kite.ltp` (`:540-544`) | Every `LIVE_POLL_SECONDS` = 60 s (`config.py:193`) in market hours (`scheduler.py:100-105`) | Live price snapshot | Latest values (and intraday bars) | Paper exit checks (`job_check_exits`), brain intraday holdings check | **Yes,** live prices on screens |
| K3 | `kite.instruments("NSE")` (`kite.py:585-587`; `ingestion.py:66,186`) | Sunday 08:00 (`scheduler.py:237-242`) | Instrument dump (symbol, token, lot, tick) | `instruments` | Symbol mapping | Indirectly |
| K4 | `holdings`, `positions`, `trades`, `margins`, `order_history`, `place_order`, `cancel_order` (`kite.py:388-526`) | 15:48 holdings sync, 15:50 / 19:30 fill capture (`scheduler.py:151-163`), on demand | The owner's own Zerodha account | Real holdings and trades tables | My Holdings (advisory), real-order switch (off by default) | Owner account only (D0a pack §3) |
| K5 | `POST https://kite.zerodha.com/api/login`, `…/api/twofa` (`kite.py:146,172,239`) with stored password + TOTP | 06:10 (`scheduler.py:80-85`) | Session token | `broker_session` | Unattended login | — |

Kite volume: one historical call per symbol per day (the watchlist, strategy lists and about 21 index
entries in `ml/sector_map.py`), plus one batched quote call a minute for about 375 market minutes a day.

### 1.4 Other outbound calls

| # | URL (file:line) | Schedule | Data | Used / shown |
|---|---|---|---|---|
| A1 | `https://www.amfiindia.com/spages/NAVAll.txt` (`services/finance/mutual_funds.py:24`) | 21:30 (`scheduler.py:228-233`, `jobs.py:625`) | Every scheme's latest NAV (one text file, ≈1 request a day) | Values mutual fund holdings that users record. Shown to the logged-in user who owns those holdings (`api/v1/router.py:74`, protected) |
| T | `https://api.telegram.org` (`notifications/telegram.py:27`) | Alerts, `flush_alerts` every 5 min | Outbound only: summaries, stop-loss and feed-problem messages | One chat, the owner's (D0a pack §2) |
| G | `accounts.google.com`, `oauth2.googleapis.com`, `www.googleapis.com/oauth2/v3/userinfo` (`api/v1/endpoints/auth.py:416-418`) | On sign-in | Identity only | Not market data |

---

## 2. What the governing terms say (verbatim)

"Verified" means I fetched the document today (2026-10-29) and read the quoted text myself. "From R0"
means I reused an R0 citation without fetching it again.

### 2.1 NSE website and app Terms of Use (governs N1–N7)

URL: <https://www.nseindia.com/static/nse-terms-of-use>. The page shows **"Updated on: 29/10/2025"**.
Verified.

- Automated collection: **"User is prohibited to conduct any systematic or automated data collection
  activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our
  Website / Mobile Application."**
- Copying, storing, showing: **"User agrees that any information or content or data on the Website / Mobile
  Application shall not be copied, modified, reverse engineer, reproduced, uploaded, transmitted, posted,
  stored (either in hardcopy or in an electronic retrieval system), adapted, altered, translated,
  disseminated, distributed, displayed, performed, broadcasted, published, hyperlinked, sold, marketed,
  licensed, rented, leased or distributed in any form, without prior written permission of NSE."**
- Downloadable files: **"Unless the information or Content is available for download, not to aggregate,
  copy or duplicate in any manner any of the content or information which is available on Website / Mobile
  Application."** The bhavcopy and deal CSVs (N1, N2) are "available for download". That may soften the
  aggregation sentence for those files. It does not touch the automated-collection sentence or the
  "stored … displayed … without prior written permission" sentence. **(UNCLEAR, ask the lawyer.)**
- Simulation: **"User acknowledges, agrees and undertakes that it shall not, in any form and manner, use or
  make the data or Content available on the Website / Mobile Application, for any gaming, virtual trading or
  simulation activities under any circumstances whatsoever."**
- Enforcement: **"Unauthorised use of the data, Content or materials appearing on the Website / Mobile
  Application may violate copyright, trademark and other applicable laws, and could result in NSE taking
  strict actions against such User."**
- Scope of the grant: **"User is granted a non-exclusive, non-transferable, limited right to access the
  Website / Mobile Application and avail the services provided by NSE through the Website / Mobile
  Application."**

### 2.2 NSE Policy for Non-Display Usage of Market Data (March 2026)

URL: <https://nsearchives.nseindia.com//web/mediaattachment/2026-03/Non_Display_Policy_20260323164430.pdf>
(the file name carries the stamp 2026-03-23; the PDF shows no other version number). Verified.

- 1.2: **"Market Data shall mean all the data disseminated by NSE Data & Analytics Limited including but not
  limited to real time data, delayed data, snapshot data, End of Day data pertaining to Capital Market
  Segment, … Indices etc."**
- 1.3: **"Non-Display Usage means use of Market Data as part of automated calculations or algorithms to
  support trading decision making processes … or portfolio valuation, risk management … If Market Data is
  used for deriving any value (Derived Data) for internal analysis, it will also fall under this Policy."**
- 1.4, who it covers: **"Subscriber means the following persons/entities (including Market Participants such
  as financial firms, traders, investment managers, investors, …) who subscribe to the Market Data for non-
  display usage: a) Data Vendors of NSE Data & Analytics Ltd. … b) Clients who subscribe to and receive the
  Market Data from Data Vendors of NSE Data & Analytics Ltd. c) Any other persons … subject to approval by
  NSE Data & Analytics Ltd on a case-to-case basis."**
- 3.1: **"Any Subscribers or any other persons who wish to be granted approval for receiving Market Data for
  Non-Display Usage will be required to enter into an agreement/undertaking with/in favor of NSE Data &
  Analytics Ltd., upon the payment of applicable fees …"**
- 3.5: **"In case the subscriber wishes to redistribute the derived data externally, separate agreement and
  fees shall be applicable."**
- Contact: marketdata@nse.co.in, +91-22-2659 8385.

How this reads for us (UNCLEAR): the policy is written for people who *subscribe to* market data from NSE
D&A or its vendors. For the NSE website feeds (N1–N6), the website terms in 2.1 already settle the
question. For Kite data (K1–K2), the open question is whether Zerodha counts as a "Data Vendor of NSE Data
& Analytics", which would make the owner a "Client" under 1.4(b). Neither document says. The policy shows
no fee figure; R0 found ₹23.9 lakh a year for real-time CM L1 enterprise non-display use (2026 tariff p.4,
from R0).

### 2.3 NSE End of the Day Data tariff (April 2026)

URL: <https://nsearchives.nseindia.com//web/mediaattachment/2026-04/Download_End_of_the_Day_Data_Tariff_20260424120810.pdf>.
Verified.

- Capital Market EOD: **₹1,00,000** (domestic) / USD 5,500 (international).
- Note 1: **"The above-mentioned commercials are per medium of data display. For the sake of clarity,
  website and mobile app are considered two different mediums and charged separately."**
- Note 2: **"Real time market data vendors of NSE are allowed to provide End of Day (EOD) data on their
  proprietary terminal/software without any additional fees for display. However, if EOD / Previous Day EOD
  data is provided to vendor's clients for any type of usage, written consent from NSE Data & Analytics Ltd
  is mandatory."**

Other NSE D&A prices (from R0, not fetched again): EOD Corporate Data ₹5,00,000 a year; Corporate Data over
leased line ₹10,60,000 a year (<https://www.nseindia.com/static/market-data/corporate-data-subscription>);
historical bhavcopy ₹30,000 a year in the April 2025 tariff, missing from the 2026 tariff.

### 2.4 NSE Indices (niftyindices.com) Terms of Use

URL: <https://www.niftyindices.com/terms-of-use> (no date shown). Verified. **No production feed calls this
site.** Index values (NIFTY 50, sector indices, INDIA VIX) reach us only through Kite (K1). The terms are
recorded here because index data is NSE Indices' property, and they would apply if anyone added a feed from
the site:

- **"You may not conduct any systematic or automated data collection activities (including scraping, data
  mining, data extraction and data harvesting) on or in relation to our website without our express written
  consent."**
- **"No material from the Site may be copied, modified, reproduced, republished, uploaded, transmitted,
  posted or distributed in any form without prior written permission from the Company."**

### 2.5 Zerodha Kite Connect Terms and conditions (governs K1–K5)

URL: <https://kite.trade/terms/> (no date or version on the page; it says changes apply "without specific
communication"). Verified.

- Who it is for: **"This may be for personal use, where You, a Client, develops a private interface
  exclusively for customising personal trading and investment experience, or this may be for building a
  trading platform. The development of trading platforms is bound by various norms and regulations
  stipulated by various exchanges and SEBI."**
- Display, derivation and simulation: **"Please note that live market data obtained via Kite Connect cannot
  be displayed to the public at large, and you cannot attempt to reverse engineer, derive the composition or
  underlying information, structure or ideas of the market data. You are not permitted to use the APIs
  and/or live market data for virtual/mock trading apps, trading related games, … Any such redistribution
  or attempt, if found, may result in the immediate termination of your access to Kite Connect."**
- Copies and databases: **"Unless expressly permitted by Zerodha or by the applicable laws, you will not,
  and will not permit your end users or others acting on your behalf to, do the following with content
  returned from the APIs. Scrape, build databases, or otherwise create permanent copies of such content, or
  keep cached copies with the intent of redistributing. Copy, translate, modify, create a derivative work of,
  sell, lease, lend, convey, distribute, publicly display, or sublicense to any third party."**
- Access method: **"You will only access (or attempt to access) an API by the means described in the
  documentation of that API. … Any circumvention of the methods described in the documentation may result
  in the termination of your access to the APIs."**
- Automation: **"The APIs are not meant for placing fully automated trades (without manual intervention). If
  you wish to use the APIs for full automation, you should seek necessary approvals from the exchange."**
- Other users: **"You may use the APIs to build platforms which You may in turn offer to other Clients of
  Zerodha (after obtaining the required exchange approvals)."**
- Credentials: **"Your credentials (such as passwords, API keys and secrets, and Client IDs) are intended to
  be used only by you."**

Kite Connect FAQ, <https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs>
(no date shown). Verified through a page summary, so the wording below may be slightly trimmed:
- Personal (free) plan: "No live market data or historical data." Paid plan: "Kite Connect paid at
  ₹500/month per API key", which includes "Live market data via WebSockets" and "Historical candle data".
- **"Displaying or redistributing Kite Connect API data on external platforms violates exchange data vending
  policies."**

A Zerodha Z-Connect post of April 2025 mentions "₹ 2000 for data". It conflicts with the FAQ's ₹500 (C,
search snippet). The owner can confirm the current price from the Kite developer console bill.

### 2.6 AMFI website Terms of Use (governs A1)

URL: <https://www.amfiindia.com/terms-of-use> (no date shown). Verified.

- **"AMFI grants you a non-exclusive, personal, non-transferable, non-sublicensable, limited and revocable
  right to access, use and display this Site … for your personal and non-commercial use only (the
  "Permitted Uses")."**
- **"No other use of the Site is authorised unless you and we have agreed otherwise in writing."**
- **"You may not publicly perform, publicly display, transmit, publish, participate in the sale or transfer
  of, modify, or create derivative works based on anything available through the Site, in whole or in part.
  You shall not store electronically any significant portion of any part of the Site."**

Context (C): SEBI requires AMCs to publish NAVs on the AMFI site
(<https://www.sebi.gov.in/legal/circulars/feb-2001/disclosure-of-navs-on-amfi-website_18073.html>, not
opened). The terms quoted above still govern how the site is used.

### 2.7 BSE

Not used in production. R0 could not load BSE's website terms. For reference, the BSE tariff
(<https://www.bseindia.com/downloads1/Information_Products_Pricing_Sheet.pdf>, Feb 2025, from R0) separates
"individual use" from "redistribution" prices.

### 2.8 Related regulation (context for the lawyer, not checked in full)

SEBI circular of 4 Feb 2025, "Safer participation of retail investors in Algorithmic trading". It was
extended to 1 Oct 2025 (SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/108), then given a glide path
(…/CIR/2025/132, 30 Sep 2025:
<https://www.sebi.gov.in/legal/circulars/sep-2025/extension-of-timeline-for-implementation-of-sebi-circular-dated-february-04-2025-on-safer-participation-of-retail-investors-in-algorithmic-trading-_96979.html>).
Mark C: dates come from search results, and I did not open the circulars. This matters for M18 "auto" and
for Kite's "fully automated trades" clause. It does not matter for paper trading.

---

## 3. Classification, feed by feed

### N1–N6 (NSE `market_feeds.py`)

- **(a) Own research: NO-without-consent.** The ban is on *how* the data is collected ("systematic or
  automated data collection … scraping … data extraction"), so it applies even if nobody else ever sees
  the result. Storing the data is also listed ("stored … in an electronic retrieval system … without prior
  written permission"). N1 and N2 are downloadable files, which helps a little (2.1, UNCLEAR). N3–N6 call
  NSE's internal `/api/` endpoints behind a browser-like User-Agent, and get no such help.
- **(b) Automated decisions: NO-without-consent.** On top of (a): the "virtual trading or simulation" sentence
  (2.1). These feeds decide paper entries through `avoid.py` and brain labels. NSE's non-display policy
  (2.2) treats "automated calculations … to support trading decision making" and derived data as a licensed
  use. Whether the policy literally covers a website user is UNCLEAR, but 2.1 already settles it.
- **(c) Shown to other users: NO-without-consent.** "displayed … disseminated … without prior written
  permission of NSE" (2.1). Results dates (N4), corporate actions (N5), surveillance reasons (N6) and the FII
  banner reason (N3) all reach the tester and the secondary logins. Derived values shown outside need "separate
  agreement and fees" (2.2 §3.5).

### N7 (NSE company filings)

- **(a) NO-without-consent**, for the same reasons as N1–N6. It also first loads the quote page to collect
  cookies, then calls the internal API with a full Chrome User-Agent.
- **(b)** Not applicable: nothing in decisions reads it.
- **(c) NO-without-consent.** The tab shows NSE content (summaries and shareholding) and links to NSE PDFs to
  any logged-in user. A plain link to a public PDF is lower risk than copying it. Note that the NSE terms
  list "hyperlinked" among the things that need permission. UNCLEAR how strictly NSE applies that word.

### K1–K3 (Kite candles, quotes, instruments)

- **(a) Own research: OK-if.** Permitted as "personal use, where You, a Client, develops a private interface
  exclusively for customising personal trading and investment experience" (2.5), on the paid Connect plan
  (the FAQ says the free plan has "No live market data or historical data"). **Storage is UNCLEAR:** the terms
  ban "build databases, or otherwise create permanent copies of such content" unless "expressly permitted
  by Zerodha". Prod keeps every candle permanently in TimescaleDB. Zerodha offers a historical-data API, but
  I found no written permission to keep a permanent database.
- **(b) Automated decisions: UNCLEAR, with one hard point.** Using your own data to decide your own trades
  is what the personal-use clause describes. **But the terms forbid using "the APIs and/or live market
  data for virtual/mock trading apps."** Production is in paper mode: v1 places simulated orders and the brain
  records practice ideas, all priced from Kite data. An owner-only paper trial before going live may be
  defensible as "customising personal trading". The clause, however, makes no exception for personal use.
  Ask Zerodha in writing (section 5). Separately, whether NSE's non-display fee applies to Kite data is
  UNCLEAR (2.2 §1.4(b)). Fully automated *real* orders (M18 "auto") need exchange approval under 2.5 and the
  SEBI algo framework (2.8). That stage has not been reached and remains the owner's call.
- **(c) Shown to other users: NO-without-consent.** "cannot be displayed to the public at large"; "publicly
  display, or sublicense to any third party"; the FAQ says displaying "on external platforms violates
  exchange data vending policies". Invite-only is not "the public at large", but the "any third party"
  wording still covers it. **The tester's pretend-money book (D0a pack §3) is a virtual trading use running
  on Kite prices and shown to a third party, which is the clearest conflict in this inventory.** Offering
  the app to "other Clients of Zerodha" is possible only "after obtaining the required exchange approvals".
- K3 (instrument list) is reference data. It carries the same terms but is low risk. UNCLEAR.

### K4 (owner's own account)

- **OK** for the owner's own use: reading your own holdings and trades and placing your own orders is the
  core purpose of the API. Real orders are behind a switch that is off by default. Fully automated real
  orders need exchange approval (2.5). Showing this data to any other user would breach "used only by you"
  and the display clauses. The current design keeps it owner-only.

### K5 (scripted login)

- **UNCLEAR.** The code drives Zerodha's web login (`/api/login`, `/api/twofa`) with the stored password and
  TOTP, not the documented redirect flow. The terms say "You will only access … an API by the means
  described in the documentation" and warn that "circumvention" can end access. The memory note
  "Kite auto-login works" covers whether it works technically, not whether it is permitted. Ask Zerodha.

### A1 (AMFI NAVs)

- **(a) OK-if:** "personal and non-commercial use only". **UNCLEAR:** "You shall not store electronically any
  significant portion of any part of the Site". The job fetches the whole NAVAll.txt file daily, and the
  code keeps NAVs for the funds users hold.
- **(c) NO-without-consent** once any user other than the owner sees NAV-based values or the product becomes
  commercial: "publicly display … create derivative works … No other use … unless … agreed otherwise in
  writing."

---

## 4. Licensed alternatives and what to ask (options only; stopping or buying is the owner's call)

Each row lists what breaks or weakens if the feed were stopped. The fallback behaviour comes from the code.
Note one asymmetry: **v1's `avoid.py` fails open** (docstring lines 9-11: "a feed that has not loaded must
not silently veto every trade"). Losing N4, N5 or N6 therefore makes **v1 less cautious**, because results
and surveillance blackouts disappear. The brain treats missing data as caution (CLAUDE.md principle 5).

| Feed | Options (cheapest first) | Published price | What depends on it if stopped |
|---|---|---|---|
| N1 bhavcopy (delivery %, series) | (1) NSE D&A **written consent** for one small daily download; (2) NSE D&A EOD CM data licence; (3) BSE QE/bhavcopy file (does not give NSE delivery %) | (2) ₹1,00,000 a year **per display medium** (verified 2.3); a non-display agreement, price not published; (3) ₹35,000 individual / ₹1,50,000 redistribution (R0) | v1 BE/BZ refusal stops; M12 delivery signal (shadow) goes quiet; M01 reports the feed stale |
| N2 bulk/block | (1) consent; (2) part of NSE EOD / corporate data products (content U → quote) | U | M12 deal signal (shadow) only |
| N3 FII/DII | (1) consent; (2) licensed vendor (U); not in Kite Connect as far as I know (C) | U | M10 loses the FII rule. With fewer than 20 days of data it already skips the rule and says "FII flow data is not available" (`judge.py:140`), so M10 can turn DEFENSIVE less often |
| N4 results calendar | (1) consent; (2) NSE EOD Corporate Data; (3) BSE Financial Results Calendar feed | (2) ₹5,00,000 a year (R0); (3) ₹3,00,000 a year EOD (R0) | v1 3-day results blackout gone (fail-open); M13 can no longer AVOID before results; holdings-health results warning and the "upcoming events" screen go empty |
| N5 corporate actions | (1) consent; (2) NSE EOD Corporate Data; (3) BSE Corporate Action feed; (4) derive from bhavcopy PREVCLOSE (R0 idea, untested; still needs N1 licensed) | (2) ₹5,00,000 (R0); (3) ₹5,00,000 EOD (R0) | v1 2-day blackout gone; M12/M13 "price reset" protection gone (a split can look like a breakdown); M01 and `split_check` lose their check; experiments scorer loses split handling (**evidence**) |
| N6 ASM/GSM | (1) consent; (2) ask NSE D&A whether surveillance lists are in any product (U) | U | v1 surveillance refusal gone (fail-open); M13 restrictions gone |
| N7 KEI filings | (1) consent; (2) NSE EOD Corporate Data (display needs more); (3) BSE corporate data redistribution bundle | (2) ₹5,00,000; display ₹10,60,000 leased (R0); (3) ₹12,00,000 redistribution (R0) | Company and news tab only (display); nothing in decisions |
| K1–K2 display to others | (1) Zerodha written permission / its "mass retail products" arrangement + exchange approval; (2) authorised NSE data vendor with a display licence; (3) NSE D&A EOD display licence for EOD prices | (1) not published; (2) not published; (3) ₹1,00,000 a year per medium (website and app separately) | Charts and prices on screens for the tester and secondary logins; the tester's pretend-money book |
| K1–K2 paper / mock trading | Zerodha written confirmation that an owner-only paper trial is acceptable personal use; otherwise a separately licensed price source for simulations | U | All paper P&L, v1 paper bot, brain practice-mode outcomes, testing book |
| K5 scripted login | Zerodha written confirmation, or the documented manual redirect login each morning | free | Unattended mornings (owner logs in by hand) |
| A1 AMFI | (1) AMFI written permission; (2) per-scheme NAV from the AMC's own site; (3) licensed MF data vendor | U | Mutual fund holding values |

### What the owner would ask for (drafts only; I contacted no one)

**To NSE Data & Analytics (marketdata@nse.co.in, +91-22-2659 8385).** This extends R0 item Q1e.
1. Written consent for an individual's automated, rate-limited daily download of: `sec_bhavdata_full`,
   `bulk.csv`, `block.csv` (archive files); and FII/DII, event calendar, corporate actions, ASM and GSM
   (website JSON). About 25 requests a day, for private use in the individual's own paper/practice trading
   app. If consent is not possible, which licensed product covers each item, at what price.
2. Whether this use (automated decisions in a private paper/practice app) needs a non-display / derived-data
   agreement, and its fee.
3. The price of display rights if results dates, corporate actions, surveillance flags and FII summaries are
   shown to 5–10 invited, non-paying users, and later to paying users.
4. Consent, or the licensed route, for showing announcements and shareholding for one stock (KEI) to those
   users.
5. Whether NSE price data received through a broker's API (Kite Connect) needs an NSE non-display agreement
   when used by the broker's own client for their own decisions.

**To Zerodha (Kite Connect; contact through the developer console or support ticket):**
1. Is an owner-only paper/practice trial, run before trading real money in the same account, allowed under
   the "virtual/mock trading apps" clause?
2. Is keeping a permanent database of historical candles from the historical API allowed, given "build
   databases, or otherwise create permanent copies"?
3. Is showing prices and charts to a handful of invited users (a tester, later a free pilot) allowed? If
   not, what does the platform / "mass retail products" route require (exchange approvals, vendor
   licence)?
4. Is the scripted TOTP login allowed under "the means described in the documentation"?
5. The current data price (₹500 vs ₹2,000 a month).

**To AMFI:** may an individual's app fetch NAVAll.txt once a day and show NAV-based values to the account
owner, and later to other invited users?

---

## 5. What this inventory does **not** recommend

- It does not recommend stopping any production feed. Stopping N4–N6 would make v1 *less* cautious
  (fail-open), so any stop decision should weigh that. It is the owner's call.
- It does not recommend buying anything. The prices above are for comparison only.
- It does not recommend extending `company_filings.py` beyond KEI, or finishing the bhavcopy backfill,
  before consent. Both would be "expanded data collection" under the owner's rule. **Note:**
  `backfill_history_step` already pulls up to 120 old bhavcopy files per run until 400 days are stored. If
  prod's history is not yet complete, that backfill is still running today.

---

## 6. Confidence and gaps

| Item | Status |
|---|---|
| Feed list, URLs, schedules, consumers | Verified from code on branch `change/stock-page-clarity` (working tree, 2026-10-29). Not checked against what prod is actually running (no SSH, no prod calls made) |
| NSE terms, non-display policy, EOD tariff, NSE Indices terms, Kite terms, AMFI terms | Verified today, quoted above |
| Kite FAQ wording | Verified through a page summary; check exact text before quoting externally |
| NSE corporate-data and BSE prices | From R0, not fetched again |
| SEBI algo circular dates | C (search results) |
| Whether M12 is in SHADOW on prod | Code default only (`m12_stock/module.py:58`); prod mode not checked |
| Kite plan actually subscribed | Unknown. Historical data requires the paid plan (FAQ) |

---

## 7. Points for a lawyer / SEBI compliance professional (add to the D0a pack)

The D0a briefing pack (`docs/compliance/2026-10-21-sebi-d0a-briefing-pack.md`) lists the market-data row as
"Daily NSE prices and related data, through Zerodha Kite Connect and other feeds". Suggested additional
questions:

1. **Website terms as a contract:** are NSE's website terms (2.1) binding on a server-side program that never
   "accepts" them? What is the realistic exposure for low-volume automated collection: blocking only, or a
   civil claim?
2. **"Available for download" (2.1):** does it permit scripted download of NSE's archive CSVs (N1, N2), as
   opposed to the internal `/api/` endpoints (N3–N7)?
3. **"Virtual trading or simulation" (NSE 2.1) and "virtual/mock trading apps" (Kite 2.5):** does an
   owner-only paper trial fall under them? Does the tester's pretend-money book? Do the planned pilot
   releases C and D (pretend-money accounts and auto-follow for invited members, D0a §4 P2/P3)?
4. **Non-display policy reach (2.2):** is an individual using a broker's API data for their own decisions a
   "Subscriber" under §1.4(b)?
5. **Derived data shown to users:** are TRADE/WATCH/AVOID labels, the DEFENSIVE banner and "results soon"
   lines "derived data … redistribute[d] externally" (2.2 §3.5) once testers or pilot users see them?
6. **Fully automated orders:** does M18 "auto" in the owner's own account need exchange approval under the
   Kite terms and the SEBI retail-algo framework (2.8)?
7. **Interaction with the research-analyst question in D0a:** if data licences are needed before any outside
   user sees the app, the D0b pilot design should include them.

---

*Sources fetched for this note (one fetch each, saved only in the session scratchpad):* NSE Terms of Use;
NSE Non-Display Policy (Mar 2026); NSE EOD Data Tariff (Apr 2026); niftyindices.com Terms of Use;
kite.trade/terms; Zerodha Kite Connect FAQ; amfiindia.com Terms of Use. Other citations are from R0 or
marked C.
