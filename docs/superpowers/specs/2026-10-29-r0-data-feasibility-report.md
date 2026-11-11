# R0 — Data feasibility report (desk research, nothing bought)

**Date:** 2026-10-29 · **For:** owner decision on whether to buy any data · **Design it serves:**
`2026-10-29-selection-model-experiments-design.md` (sections 5, 8, 11) · **Status:** research only — no
purchase, no trial, no sign-up, no vendor contacted, no bulk download, no scraper run.

---

## 0. The answer in plain English

1. **Old prices including companies that later disappeared (2014 → 2021): yes, this can be had, and
   cheaply.** NSE keeps one price file per trading day (the "bhavcopy"). Each day's file lists every
   stock that traded that day, so firms that were delisted later are in it automatically. The
   files are free to look at on NSE's site, but NSE's terms forbid collecting them with a program.
   NSE sells a licensed copy. Its April 2025 price list showed **₹30,000 a year** for historical
   bhavcopy. That line is missing from the April 2026 price list, so we need a quote.
2. **Which stocks were in NIFTY 100 / Midcap 150 on each date: partly.** NSE Indices' monthly files
   exist and I checked them myself. NIFTY 100 is covered from April 2013. **NIFTY Midcap 150 first
   shows up somewhere between Feb 2017 and Jan 2018.** Before that the index list was never
   published in these files. After March 2022 the files cover only a few indices, and neither
   NIFTY 100 nor Midcap 150 is among them. So for 2014–2017 a formal large-cap vs mid-cap split
   needs a paid history from NSE Indices, or that part has to be marked NOT TESTABLE.
3. **Company results "as first filed, with the exact time the exchange published them": possible
   from NSE or BSE, not from the cheap vendors.** The exchanges stamp every filing with a
   publication time. Vendors like EODHD, CMIE, ACE and Capitaline do not say whether they keep the
   first-filed numbers or the publication time, so they fail rule L5 until they prove otherwise.
4. **Why KEI's results "stop at Dec 2024":** this is almost certainly not a lag. NSE **switched off
   the old results-filing tool on 1 April 2025** (circular NSE/CML/2025/20). Since then results
   have gone into a new section called "Integrated Filing – Financials". The old feed our code
   reads therefore ends with the last quarter filed the old way, Oct–Dec 2024. The newer results
   exist, but in a different place.
5. **Licensing is the real cost driver, not the data.** NSE's own policy says that using its market
   data, end-of-day files included, "for deriving any value … for internal analysis" counts as
   "non-display usage", which needs a separate agreement and fee (price not published). Showing
   the data in a product later costs more again: ₹1 lakh a year per medium for end-of-day prices,
   and ₹5–10.6 lakh a year for company filings data.
6. **Two existing jobs in the repo collect data from NSE by program every day, not just one.** One
   is `company_filings.py` (KEI). The other, `market_feeds.py`, takes the bhavcopy, FII/DII flows,
   the events calendar, corporate actions and ASM/GSM lists. Both run against NSE's written
   "no automated data collection" clause. That is a real terms risk, and it needs a decision from
   you (section 7.4).

**Cheapest route that meets L1–L5 for research:** ask NSE Data & Analytics for (a) the
historical-bhavcopy licence and (b) written consent, or a quote, for one-time research use of its
corporate-filings history, which carries publication timestamps. Ask NSE Indices for historical
constituents. **Expected cost: about ₹35,000 if NSE grants consent for the filings; about
₹6.5–8 lakh a year (with GST) if it insists on the paid EOD Corporate Data product; ₹15–30 lakh a
year+ for later use inside a product shown to users.** Details are in section 9.

---

## 1. How to read this report

| Mark | Meaning |
|---|---|
| **V** | Verified today on the source's own page or document (link given) |
| **V-mirror** | Verified on an exact copy of the source's document hosted by a third party |
| **C** | Claim — forum post, search snippet, vendor marketing, or general knowledge; not confirmed |
| **U** | Unknown — not stated anywhere I could read; needs a quote or a test |

What I actually fetched, for transparency. Each was a single, by-hand-scale request, nothing in
a loop over dates or stocks:
- 7 public NSE / BSE PDFs (price lists, policy, one circular)
- about 10 HTML pages
- 9 NSE Indices monthly constituent zips, as samples to test the April 2013 → March 2022 claim
  (Apr 2013, Jan 2016, Jan 2017, Jan 2018, Jan 2019, Jan 2020, Mar 2022, Apr 2022, Sep 2026)
- tiny byte-range probes of 4 bhavcopy URL patterns and 4 NSE reference files

Everything is in my scratchpad; nothing went into the repo.

---

## 2. Leakage rules this report checks against (from design section 5)

| Rule | Short meaning | What a source must have |
|---|---|---|
| L1 | Use the publication time, not the quarter | A publication (dissemination) **date and time** for every filing |
| L2 | Usable from the next session if published after 15:30 | Time of day, not just a date |
| L3 | First-filed value; revisions are new rows | Original filings kept; revisions carry their own date |
| L4 | Results date counts only if the board-meeting notice was public | Board-meeting **notices** with their own timestamps |
| L5 | No timestamps → no formal evidence | The source must supply L1–L4 data, or it is "exploration only" |

Prices and index membership do not need time-of-day; for them "point-in-time" means **the data as it
was on that date** (no survivor bias, no back-filled index lists).

---

## 3. Question 1 — Pre-2021 daily prices including later-delisted stocks (target 2014-01 →)

### 3.1 NSE bhavcopy archive (free to view)

| Item | Finding | Mark |
|---|---|---|
| What it is | One file per trading day with every traded security's open/high/low/close/volume | V ([NSE EOD page](https://www.nseindia.com/static/market-data/eod-historical-data-subscription)) |
| Years | Old format answers for 2 Jan 2014: `https://nsearchives.nseindia.com/content/historical/EQUITIES/2014/JAN/cm02JAN2014bhav.csv.zip` (HTTP 206 on a byte-range probe; a HEAD request gets 503, so tools that use HEAD will wrongly think it is missing). Forum posts say the archive goes back to the mid-1990s | V for 2014 / C for earlier |
| Current URL patterns | (a) old format above, used up to mid-2024; (b) `…/products/content/sec_bhavdata_full_DDMMYYYY.csv` (answers for 02-01-2020; the repo already uses this one); (c) UDiFF format since July 2024: `…/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip` (answers for 2026-01-28; **404 for 2014 and 2020**, so the new format is not back-filled) | V (probes) / C (July 2024 switch date, [eod2 README](https://github.com/BennyThadikaran/eod2/blob/main/README.md)) |
| Includes later-delisted names? | **Yes, by construction.** Each daily file lists what traded that day. I did not open a 2014 file to count names; do that in R1 | V (by design) / count U |
| Helper files | `…/content/equities/delisted.csv` (symbol, name, delisting date, type, back to 2002), `…/content/equities/symbolchange.csv` (old → new symbol with dates). Both answer | V (first lines read) |
| Point-in-time | Yes, prices are as traded that day (unadjusted) | V |
| Dissemination timestamp | Not needed for prices (end of day) | — |
| Licence, research | Website terms: **"User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting)"**. Downloading ~1,900 daily files by script breaks this. Manual clicking is allowed, but around 1,900 files is not practical by hand. Also, NSE's non-display policy covers EOD data used "for deriving any value … for internal analysis" | V ([NSE terms](https://www.nseindia.com/static/nse-terms-of-use), [non-display policy, Mar 2026](https://nsearchives.nseindia.com//web/mediaattachment/2026-03/Non_Display_Policy_20260323164430.pdf)) |
| Licence, product | Not covered; needs a display licence (see 3.2) | V |
| Price | Free to view | V |

### 3.2 NSE Data & Analytics — paid EOD / historical data (the licensed copy)

Contact on NSE's page: **marketdata@nse.co.in, +91-22-2659 8385**. All prices are per year and
exclude GST (18%).

| Product | Price | Source | Mark |
|---|---|---|---|
| **End of Day Historical Bhav Copy Data — Capital Market** | **₹30,000 / yr** (USD 500) | ["Other Products" tariff, effective 1 Apr 2025](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Other_Products_Tariff_01042025_.pdf), p.5 | V (2025) — **not listed in the 2026 tariff → quote needed** |
| Historical Trade Data — CM (trade-by-trade, far more than we need) | ₹1,10,000 / yr per site (2026); 2025 sheet had ₹20,000 for "Students / Researchers", 2026 lists ₹22,000 under "Educational Institutions Products" | [Domestic tariff, effective 1 Apr 2026](https://nsearchives.nseindia.com//web/mediaattachment/2026-04/Download_Pricing_file_-_Domestic_clients_20260424122229.pdf), p.8 and p.13 | V — whether an individual qualifies as "researcher" is U |
| End of the Day Data — CM (daily file, ongoing, **for display**) | ₹1,00,000 / yr per site **per medium** (website and mobile app count separately) | [EOD tariff, Apr 2026](https://nsearchives.nseindia.com//web/mediaattachment/2026-04/Download_End_of_the_Day_Data_Tariff_20260424120810.pdf); 2026 tariff p.7 | V |
| Conditions | "if EOD / Previous Day EOD data is provided to vendor's clients for any type of usage, written consent from NSE Data & Analytics Ltd is mandatory" | EOD tariff note 2 | V |
| Coverage of the historical product (start year, delisted, adjustments) | Not stated | — | U → quote |

**Verdict:** this is the cleanest licensed source for Stage 2 prices, and very likely the cheapest.
It includes delisted names. History depth and the 2026 price still need a quote.

### 3.3 EODHD (low-cost fallback for prices)

| Item | Finding | Mark |
|---|---|---|
| Price | All-in-one **$99.99 / month** (or $999.90 / yr); EOD-only "Historian" $19.99 / month; fundamentals-only $59.99 / month (fundamentals-only has no prices, dividends or splits) | V ([pricing](https://eodhd.com/pricing)) |
| Delisted | "Delisted before 2018: **EOD only**; after 2018: EOD, fundamentals, dividends and splits". Symbol-change history is **US only**, so NSE renames are not linked | V ([delisted data page](https://eodhd.com/financial-apis/delisted-stock-companies-data-2)) |
| NSE delisted count | "NSE … 940 entries" in a search snippet of an EODHD page | C |
| Fundamentals depth | "non-US symbols from 2000"; "**Minor companies have the last 6 years and 20 quarters**" | V ([fundamentals docs](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds)) |
| As-first-filed or restated? | Not stated anywhere | U |
| Timestamp | Each report has a `filing_date` (a date, **no time of day**) | V (docs) |
| Licence, research | Personal plans: a "Non-Professional User … solely in a personal capacity" may "store, manipulate, and analyze the data for private, non-commercial purposes" | V ([terms](https://eodhd.com/financial-apis/terms-conditions)) |
| Licence, product | Personal plans forbid "displaying, or granting access"; commercial plans are priced separately | V / price U |

**Verdict:** fine as a **cross-check or fallback for prices** during private research (one month
≈ $100). Its **fundamentals fail L1/L2** (no time of day) and **L3 is unknown**, so under L5 they
are exploration only. Missing pre-2018 corporate-action data for delisted names hurts price
adjustment.

### 3.4 Other Indian vendors

| Vendor | What I found | Delisted | Point-in-time | Timestamp | Price | Mark |
|---|---|---|---|---|---|---|
| **TrueData** | Real-time/EOD vendor; its Python package fetches the day's NSE bhavcopy | U | U | U | not published | C ([pypi](https://pypi.org/project/truedata-ws/4.0.1)) |
| **Global Datafeeds** | Real-time and EOD feed (Amibroker-focused); no history depth stated | U | U | U | not published | C |
| **Accord Fintech — ACE Equity** | Desktop/cloud database: quarterly results (Ind AS), shareholding (promoter / public / institutional), Excel export; sold mostly to institutions | U | likely standardised/restated — U | U | not published; contact info@accordfintech.com | C ([IIMA library](https://library.iima.ac.in/a_to_z_databases.html), [user guide](https://iimidr.ac.in/wp-content/uploads/2025/10/User-Guide-ACE-Equity-Nxt.pdf)) |
| **CMIE Prowess / Prowessdx** | ~50,000 companies, from 1989/1990; annual + quarterly, built from annual reports and exchange feeds; **sold to institutions (academic Prowessdx)**, no individual price seen | U | U | U | not published | C ([Wikipedia](https://en.wikipedia.org/wiki/Centre_for_Monitoring_Indian_Economy), [IIMC library](https://library.iimcal.ac.in/cmie-prowessdx/)) |
| **Capitaline** | Annual + interim results, announcements, share prices. Third-party offers: list price ₹1,50,000 / yr single user; CA-institute rate ₹25,000 / login / yr (AWS TP); older ₹30,000 (Capitaline Plus) | U | U | U | ₹25k–1.5L / yr (third-party) | C ([CFA Society offer PDF](https://cfasocietyindia.org/wp-content/uploads/Media-Uploads-Membership/Member-offers/Member-Offer-Document_for-Society_Capitalin2.pdf), [ICAI](https://www.icai.org/post/16361)) |
| **Trendlyne** | MCP/AI-access plans with financials, shareholding, filings; research tier 400 calls a day; no API price for bulk history | U | U | U | not published for bulk | C ([MCP plans](https://trendlyne.com/subscription/mcp/plans/)) |
| **Zerodha Kite** (our current price source) | Gives our 2021+ candles; delisted instruments are not in the instrument list, so no delisted history | No | prices yes | — | already paid | C (general knowledge) |

**Verdict:** none of these vendors publicly promises **as-first-filed values with publication
time**, so none passes L5 without a written confirmation. They are not cheaper than NSE for prices.

### 3.5 BSE (alternative exchange source)

| Product (BSE Information Products tariff, Feb 2025) | Price / yr (excl. GST) | Mark |
|---|---|---|
| QE File (EOD) — Bhavcopy, individual use | ₹35,000 (redistribution ₹1,50,000) | V ([BSE tariff](https://www.bseindia.com/downloads1/Information_Products_Pricing_Sheet.pdf) p.14) |
| Historical OHLC — Stock | ₹75,000 "per year" (unclear: per year of history or per subscription year) | V / meaning U |
| History depth | BSE says its EOD history runs "since 1990" (search snippet of BSE's page; the page itself blocks bots) | C |
| BSE website terms | Page would not load for me (JS / bot block) | U |

BSE prices are only useful if the Stage 2 universe is built on BSE codes. The design uses NSE
symbols, so BSE is a fallback.

---

## 4. Question 2 — Corporate actions (splits / bonus / dividends) to adjust old prices

| Source | Coverage | Point-in-time | Licence | Price | Mark |
|---|---|---|---|---|---|
| **Derive from the bhavcopy itself**: on an ex-date, NSE's `PREVCLOSE` column is believed to be the *adjusted* previous close, so (yesterday's close ÷ today's PREVCLOSE) gives the adjustment factor | same as bhavcopy, includes delisted | yes | same as bhavcopy | included | **C — must be tested on 5–10 known splits/bonuses in R1** |
| NSE corporate actions page/API (`/api/corporates-corporateActions`, already called by `market_feeds.py`) | ex-date, purpose text ("Bonus 1:1", "Face value split"…); history depth U | yes (ex-date known in advance) | NSE terms (automated collection banned) | free to view | V that the repo calls it / depth U |
| NSE corporate data products (EOD Corporate Data ₹5,00,000 / yr; Corporate Data leased line ₹10,60,000 / yr) — "company fundamentals, corporate announcements, and shareholding pattern" | U | U | licensed | as listed | V price ([corporate data page](https://www.nseindia.com/static/market-data/corporate-data-subscription)) / content U |
| BSE "Corporate Action via Internet" | U | U | licensed | ₹5,00,000 EOD / ₹6,00,000 continuous | V ([BSE tariff](https://www.bseindia.com/downloads1/Information_Products_Pricing_Sheet.pdf) p.11) |
| EODHD splits / dividends | delisted after 2018 only | U | personal use | in $99.99 / month plan | V (delisted page) |

**Verdict:** try the free bhavcopy-derived method first, inside the bhavcopy licence, and check it
against NSE's corporate-actions list for a sample. Nothing extra needs to be bought unless the
check fails.

---

## 5. Question 3 — Historical index membership (NIFTY 100, NIFTY Midcap 150)

### 5.1 NSE Indices monthly constituent files — the claim, tested

URL pattern (V):
`https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_data{Mon}{YYYY}.zip`

| Month sampled | Files inside | NIFTY 100? | Midcap 150? |
|---|---|---|---|
| Apr 2013 | 25 CSVs (`cnx100`, `cnx500`, `cnxmidcap`, `cnxnifty`, sectors…) with date, symbol, weight | **yes** (as CNX 100) | no (index did not exist) |
| Jan 2014, Jan 2018, Jan 2021 | answer (byte-range probe) | — | — |
| Jan 2016 | PDFs: nifty100, niftymidcap50, niftymidcap100, niftysmallcap100 … | yes | **no** |
| Jan 2017 | same set | yes | **no** |
| Jan 2018, Jan 2019, Jan 2020 | PDFs incl. `NIFTY_100` and `NIFTY_Midcap_150` | yes | **yes** |
| Mar 2022 | 41 PDFs incl. NIFTY 100, Midcap 150, NIFTY 500 | yes | yes |
| Apr 2022 | only 4 PDFs: NIFTY 50, Bank, Financial Services, Midcap Select | **no** | **no** |
| Sep 2026 | 7 PDFs: + IT, Next 50, India FPI 150 | **no** | **no** |

**Verdict on the forum claim "Apr 2013 – Mar 2022 for all indices, only F&O indices after":
TRUE, with one nuance.** Midcap 150 is missing until some month between Feb 2017 and Jan 2018. I
did not check the exact first month. Also, the files are **CSV in 2013 and PDF from at least
2016**, so the PDFs need table extraction. Source of the claim:
[TradingQnA thread](https://tradingqna.com/t/where-can-i-find-historical-composition-of-nifty-indices/7163) (C) → now V.

Known trap (C, [MarketCalls](https://www.marketcalls.in/?p=64824)): a change that takes effect on
1–2 April may still show the outgoing stock in the March file. Use the change notices (5.2) for
exact effective dates.

### 5.2 Other free pieces

| Source | What | Mark |
|---|---|---|
| `https://nsearchives.nseindia.com/content/indices/IndexInclExcl.xls` | Inclusion/exclusion dates per index; forum says it stops at **31 Jul 2020**; has a NIFTY 500 sheet from 1998 | V (file answers) / C (content) |
| NSE Indices index-change press releases | Exact effective dates of each rebalance (semi-annual) | C (not opened) |

### 5.3 Licence

NSE Indices terms: **"You may not conduct any systematic or automated data collection activities
… without our express written consent"** and "No material from the Site may be copied …
reproduced … without prior written permission" ([niftyindices terms](https://www.niftyindices.com/terms-of-use), V).
About 110 monthly files plus PDF extraction counts as systematic collection → **written consent, or
a paid history file from NSE Indices, is needed** (price U → quote).

**Effect on the design (6.4):** a formal large/mid split is possible from about 2018 onward using
the free files (with consent). For 2014–2017 the Midcap 150 list is not in these files. Either
buy NSE Indices' back-history (if it exists), or label that slice **NOT TESTABLE**, or treat it as
EXPLORATORY (an approximation such as NIFTY 500 minus NIFTY 100 minus smallcaps would carry survivor
risk of its own).

---

## 6. Questions 4–6 — Company data with publication timestamps

### 6.1 Quarterly results as first filed (S3 inputs 1–5)

| Source | Coverage | As first filed? | Dissemination timestamp | Licence | Price | Mark |
|---|---|---|---|---|---|---|
| **NSE announcements** ("Outcome of Board Meeting — Financial results", PDF) | every listed company, incl. now-delisted; history depth U | **yes** — it is the filing itself; later corrections are new announcements | **yes** — `an_dt` with time of day; the repo already parses it as `%d-%b-%Y %H:%M:%S` | NSE terms ban automated collection | free to view | V (code) / depth U |
| **NSE XBRL results** (old utility up to 31 Mar 2025; "Integrated Filing – Financials" from 1 Apr 2025) | XBRL results start around 2015 under the LODR rules (C); ~2018 circular rolled out NSE's XBRL modules (C) | **yes** (each XBRL file is a submission; revisions are separate submissions) | submission / broadcast date-time shown per filing (C, from a search snippet of NSE's page) | same terms | free to view | V-mirror for the 2025 switch ([NSE/CML/2025/20](https://ca2013.com/wp-content/uploads/2025/04/NSE-Circular_02.04.2025.pdf)) / rest C |
| NSE EOD Corporate Data (SFTP after 8 pm) | "company fundamentals, corporate announcements, and shareholding pattern"; history U | U | U | licensed | **₹5,00,000 / yr** | V price ([corporate data page](https://www.nseindia.com/static/market-data/corporate-data-subscription); 2026 tariff p.7) |
| NSE Corporate Data (leased line, real time) | same, live | U | U | licensed | ₹10,60,000 / yr | V |
| BSE Results feed | all BSE-listed | U | BSE shows "Exchange received / disseminated time" on announcements (C) | licensed | **₹3,00,000 EOD** / ₹5,00,000 continuous | V price (BSE tariff p.11) |
| EODHD fundamentals | non-US from 2000; minor companies 20 quarters only | U | date only | personal use | $59.99–99.99 / month | V / U — **fails L1/L2** |
| CMIE / ACE / Capitaline | long history | U (standardised databases usually restate) | U | institutional | see 3.4 | C — **fails L5 until confirmed** |

**The KEI "lag" — a known cause, not a mystery.** NSE circular **NSE/CML/2025/20 (2 April 2025)**
says that from **1 April 2025** companies file results **only** through "Integrated Filing –
Financial", and that the "Existing XBRL utilities for filing Financial Results" are **discontinued**
(V-mirror; the copy I read is hosted by ca2013.com). KEI's old-feed data ending at the
**December 2024 quarter** is exactly what this switch predicts: the January 2025 filing was the last
one under the old tool. NSE's company menu now has separate "Financial Results" and "Integrated
Filing – Financials" sections (V, NSE page navigation). One company's letter also mentions a BSE
→ NSE integrated-filing sync glitch (C,
[Kesoram letter](https://nsearchives.nseindia.com/corporate/KESORAMIND_22092025142811_KILReply22092029.pdf)).
**Recommended wording change for the code comment:** "the old results feed stopped at the Dec-2024
quarter because NSE moved results to Integrated Filing from 1 Apr 2025". I have **not** edited the
file; this report is the only change.

### 6.2 Shareholding pattern with FII / DII / MF split and filing date (S3 inputs 6–8)

| Source | Split available? | Filing date | Revisions | Price | Mark |
|---|---|---|---|---|---|
| NSE shareholding filings (XBRL per quarter) | The SEBI format (since late 2015) breaks "Public" into institutions: mutual funds, FPIs, banks/insurers, etc. | NSE page lists **submission date, revision date, broadcast date/time**, XBRL link | yes, shown as revision date | free to view | C (search snippet of [NSE SHP page](https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern); format from general knowledge) |
| What the repo uses today (`/api/corporate-share-holdings-master`) | **promoter vs public only**; `submissionDate` is a **date with no time**; the code keeps only the *latest* filing per quarter (`filed >= best[...]`), which **breaks L3** if reused for research | — | overwritten | — | V (read `company_filings.py` lines 98–125) |
| NSE EOD Corporate Data | includes shareholding pattern | U | U | ₹5,00,000 / yr | V / U |
| BSE Shareholding Pattern feed | U | U | U | ₹3,00,000 EOD | V price |
| ACE / Capitaline / Trendlyne | promoter / public / institutional (ACE guide) | U | U | see 3.4 | C |

Note for L2: shareholding filings carry a broadcast **time** on the NSE page (C), but the
`submissionDate` field the repo reads has no time. For formal use, either take the broadcast time
from the announcement stream, or (the safe fallback) treat a date-only filing as usable **from the
next trading day**.

### 6.3 Board-meeting notices (F1, rule L4)

| Item | Finding | Mark |
|---|---|---|
| Rule | SEBI LODR Reg. 29: prior notice of a results board meeting. Notice period was 5 working days for results under the 2015 rules; a May 2024 amendment reportedly made it a uniform **2 working days** and requires the date in the notice | C ([ca2013 Reg 29](https://ca2013.com/lodr-regulation-29/), [MMJC](https://mmjc.in/amendment-to-sebi-lodr-regulations-2/)) |
| NSE source | "Board Meetings" filings section + announcements ("Prior intimation of board meeting", PDF, timestamped); the repo's `market_feeds.py` already calls NSE's `/api/event-calendar` | V (repo) / depth U |
| BSE source | "Financial Results Calendar" feed ₹3,00,000 / yr; Board Meetings in corporate data | V price |
| History depth | Not stated by any source | **U — one manual look at one stock's 2015 announcements answers it** |

**F1 caution:** the event-calendar API shows the *meeting date*. It does not show when the notice
was published, and L4 needs that. Use the timestamped **prior-intimation announcements**, not the
calendar.

---

## 7. Question 7 — Licensing

### 7.1 What the terms say (all V, quoted)

- **NSE website:** "User is prohibited to conduct any systematic or automated data collection
  activities (including scraping, data mining, data extraction and data harvesting) on or in
  relation to our Website / Mobile Application." No exception for research, and no consent route
  written into this clause ([terms](https://www.nseindia.com/static/nse-terms-of-use)).
- **NSE Indices website:** same ban "without our express written consent"; copying or
  reproducing material needs "prior written permission" ([terms](https://www.niftyindices.com/terms-of-use)).
- **NSE non-display policy (Mar 2026):** market data "including … End of Day data". Non-display
  usage includes "automated calculations or algorithms to support trading decision making …
  portfolio valuation, risk management … **If Market Data is used for deriving any value (Derived
  Data) for internal analysis, it will also fall under this Policy.**" Separate agreement and fee for
  "redistribut[ing] the derived data externally" and for "any other purpose"
  ([policy PDF](https://nsearchives.nseindia.com//web/mediaattachment/2026-03/Non_Display_Policy_20260323164430.pdf)).
- **NSE tariffs:** EOD prices for display are charged per medium; EOD data passed to "vendor's
  clients for any type of usage" needs written consent ([EOD tariff](https://nsearchives.nseindia.com//web/mediaattachment/2026-04/Download_End_of_the_Day_Data_Tariff_20260424120810.pdf)).
- **BSE website terms:** could not load (U). BSE's tariff splits "individual use" from
  "redistribution" prices (V).
- **EODHD:** personal plans are for "private, non-commercial purposes", with no displaying or
  sharing (V).

### 7.2 What would cover (a) private research

| Data | Minimum cover |
|---|---|
| Pre-2021 prices | NSE historical bhavcopy licence (₹30k in 2025, quote for 2026), **or** NSE's written consent to download the public archive once. Ask whether a non-display / derived-data agreement is also required for model research (the policy wording suggests yes) |
| Index membership | NSE Indices written consent for the monthly files, or a paid constituent history |
| Company filings with timestamps | NSE written consent for one-time research collection of announcements + XBRL + SHP, **or** NSE EOD Corporate Data (₹5L / yr) if it includes history and timestamps, **or** BSE equivalents (₹3L each for results / SHP / calendar EOD) |

### 7.3 What would cover (b) later use in a product shown to users

| Use | Indicative cost / yr (excl. GST) | Mark |
|---|---|---|
| Showing NSE EOD prices on website + app | ₹1,00,000 × 2 media = ₹2,00,000 | V |
| Showing company filings data | NSE Corporate Data ₹10,60,000; or BSE "Corporate Data (All 3) for redistribution licence on open user website and mobile application" ₹12,00,000 | V |
| Showing **derived** values (scores, signals) to users | "separate agreement and fees" — not published | U → quote |
| Non-display (algorithm) use of real-time data | ₹23.9 lakh / yr (CM L1, enterprise), only if real-time NSE data feeds the algorithm directly | V (2026 tariff p.4); applicability U |

Today's live prices come through Zerodha Kite. Whether Kite's terms cover showing those prices
to other users is a separate question I did not research.

### 7.4 The existing jobs — terms-risk flag (read, not changed)

- `backend/src/swing_trade_ml/services/company_filings.py` runs **every weekday at 19:40 IST**
  (`workers/scheduler.py` line 182). It first loads an NSE quote page to collect cookies, then calls
  NSE's **internal JSON API** (`/api/corporate-announcements`, `/api/corporate-share-holdings-master`)
  with a browser-like User-Agent. It stores the results and **shows them to users** in the Company
  tab. That is (i) systematic automated collection, which NSE's terms prohibit, and (ii) display of
  NSE-sourced data without a display licence. The volume is tiny (one stock), but the clause has no
  size threshold. **Risk: real, low-volume; do not extend to 306 stocks without consent.**
- **Also flagged (wider than asked):** `backend/src/swing_trade_ml/services/market_feeds.py` calls
  `sec_bhavdata_full`, bulk/block deals, `/api/fiidiiTradeReact`, `/api/event-calendar`,
  `/api/corporates-corporateActions`, `/api/reportASM`, `/api/reportGSM` on a schedule. Same clause
  applies.
- Practical consequence: NSE could block the server's IP. That would silently break v1 side feeds,
  and the brain treats missing data as caution, so it would also make the brain more cautious. The
  safest fix is to ask NSE for written consent covering these daily pulls (item Q1e below), or to
  replace them with licensed equivalents. **Your call; nothing changed.**

---

## 8. Per-source summary table

| # | Source | Years | Delisted | Point-in-time | Dissemination timestamp | Research licence | Product licence | Price | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| 1 | NSE bhavcopy archive (free) | 2014 V (earlier C) → today | **yes** | yes | n/a | **terms ban scripts**; consent needed | no | free to view | V |
| 2 | NSE D&A historical bhavcopy | U | yes (by nature) | yes | n/a | licence | separate display fee | ₹30k (2025) → quote | V (2025 tariff) |
| 3 | NSE D&A EOD data (ongoing) | today | — | yes | n/a | licence | ₹1L / medium | ₹1,00,000 | V |
| 4 | EODHD | 30+ yrs prices; fundamentals non-US from 2000 | yes (pre-2018 EOD only) | prices yes; fundamentals U | date only | personal use OK | commercial plan | $99.99 / month | V |
| 5 | NSE Indices monthly files | Apr 2013 → Mar 2022 (Midcap 150 from ≤ Jan 2018) | yes (lists as they were) | yes | n/a | consent needed | consent needed | free to view | V |
| 6 | IndexInclExcl.xls | to Jul 2020 (C) | yes | yes | n/a | consent | consent | free | V exists / C content |
| 7 | NSE announcements (results PDFs, board-meeting notices) | U | yes | **yes, as filed** | **yes, with time** | consent needed | display licence | free to view | V (fields) |
| 8 | NSE XBRL results / SHP | ~2015 → (C); new section from Apr 2025 (V-mirror) | yes | **yes** (submissions + revisions) | submission / broadcast time (C) | consent needed | display licence | free to view | C / V-mirror |
| 9 | NSE EOD Corporate Data | U | U | U | U | licence | add display | ₹5,00,000 | V price |
| 10 | NSE Corporate Data (leased line) | live | — | — | U | licence | licence | ₹10,60,000 | V price |
| 11 | BSE Results / SHP / Calendar / Announcements (EOD) | U | U | U | U | licence | ₹12L redistribution bundle | ₹3L / ₹3L / ₹3L / ₹5L | V price |
| 12 | BSE bhavcopy / historical OHLC | "since 1990" (C) | U | yes | n/a | individual use | ₹1.5L redistribution | ₹35k / ₹75k | V price |
| 13 | CMIE Prowess | 1989/90 → | U | U | U | institutional | U | not published | C |
| 14 | ACE Equity | U | U | U | U | institutional | U | not published | C |
| 15 | Capitaline | U | U | U | U | per login | U | ₹25k–1.5L (3rd party) | C |
| 16 | Trendlyne | U | U | U | U | plan terms | U | not published for bulk | C |
| 17 | TrueData / Global Datafeeds | U | U | U | U | U | U | not published | C |

---

## 9. Recommendation, ranked (cheapest route that satisfies L1–L5)

**Rank 1 — NSE first, consent before money.**
1. **Prices (Stage 2):** NSE D&A historical bhavcopy licence for CM 2014-01 → 2021-07. It includes
   delisted names; renames come from `symbolchange.csv`; corporate-action adjustment is derived
   from the bhavcopy and spot-checked. *Expected ₹30,000 + GST if the 2025 line still applies.*
2. **Company data (S3, F1):** ask NSE for **written consent for one-time, private-research
   collection** of announcements (results outcomes + board-meeting notices, with `an_dt`), XBRL
   results (old utility to Mar 2025 + Integrated Filing after) and XBRL shareholding (with
   submission / revision / broadcast times). This is the only route seen that clearly gives
   **as-first-filed values + publication time (L1–L4)**. If NSE refuses consent and instead offers
   EOD Corporate Data (₹5L / yr), first get written confirmation that it **includes history back to
   2014/2015, publication timestamps and revisions as separate records**. Otherwise it does not
   satisfy L5 and is not worth buying.
3. **Index membership:** ask NSE Indices for consent to use the monthly files (Apr 2013 → Mar
   2022), or a quote for constituent history with effective dates. Accept that **Midcap 150 before
   ~2018 does not exist in these files**.
4. **Non-display question:** in the same email, ask NSE D&A whether model research on licensed EOD
   / corporate data needs a non-display / derived-data agreement, and its price.

**Rank 2 — BSE as fallback for company data** (₹3L results + ₹3L shareholding + ₹3L results
calendar EOD = ₹9L / yr). Only after BSE confirms history depth and timestamps.

**Rank 3 — EODHD for prices only** ($99.99 for one month), as a cross-check or if NSE's bhavcopy
licence is slow or refused. Its fundamentals are **exploration-only** under L5.

**Not recommended for formal evidence:** CMIE, ACE, Capitaline, Trendlyne, TrueData, Global
Datafeeds. None states as-first-filed values or publication time. Use them only if a vendor puts
both in writing.

**If nothing is bought:** Stage 2 = NOT TESTABLE (design 6.3); S3 / F1 run on 2021-08 → 2026-08
only if the existing NSE pulls are covered by consent; otherwise S3 / F1 are exploration-only.

---

## 10. Exact list of quotes / consents to request (owner sends these; I contacted no one)

**Q1 — NSE Data & Analytics (marketdata@nse.co.in, +91-22-2659 8385)**
- a. Price under the **2026** tariff for **End of Day Historical Bhav Copy — Capital Market**,
  2014-01-01 → 2021-07-31 (one-time purchase or annual?). Does it include delisted securities and
  a symbol-change history? Does an individual qualify for the "Students / Researchers" rate?
- b. **EOD Corporate Data** (₹5,00,000 / yr): history depth; does each record carry the
  **exchange dissemination date-time**; are revisions separate records; does it include XBRL
  results values, shareholding categories (MF / FPI / other institutions), board-meeting
  intimations and corporate actions? Price of a one-time historical back-file?
- c. Is a **non-display / derived-data agreement** required for an individual's private model
  research on EOD data? Price?
- d. Alternative: **written consent** for a one-time, rate-limited download of public archive files
  (bhavcopy 2014–2021, corporate announcements and XBRL filings) for private, non-commercial research.
- e. Written consent (or licensed replacement) for the **daily automated pulls already running**
  in `market_feeds.py` and `company_filings.py`, and the price of display rights if TradeMind shows
  this data to users.
- f. For later product use: price of the **derived-data redistribution** agreement (scores shown
  to users).

**Q2 — NSE Indices Ltd (via niftyindices.com contact)**
- a. Written consent to download the monthly "Market Capitalisation and Weightage" files (Apr
  2013 → Mar 2022) for private research.
- b. Quote for **historical constituents with effective dates** for NIFTY 100, NIFTY Midcap 150
  (and NIFTY Midcap 100 / NIFTY 500 for pre-2017 years), 2014 → today.

**Q3 — BSE (fallback, only if Q1b/Q1d fail)**: history depth, timestamps and price of the
Results, Shareholding Pattern, Financial Results Calendar and Announcements EOD feeds as a
**historical back-file**; BSE website terms for automated collection.

**Q4 — EODHD (fallback for prices)**: number of NSE delisted tickers and their start year; any NSE
symbol-change history; whether fundamentals are as-first-reported or restated; commercial-plan
price for later product use.

**Q5 — Optional, only if Q1–Q3 fail on company data**: CMIE (Prowess), Accord (ACE Equity),
Capitaline. Ask the same two questions to each: "Are quarterly figures kept **as first reported**,
with revisions as separate records?" and "Is the **exchange publication date and time** stored per
filing?" Without two yes answers, they cannot be used for formal evidence.

---

## 11. Total cost estimate

All figures per year, excluding 18% GST unless stated. "Quote" = not published.

| Scenario | What is bought | Estimate |
|---|---|---|
| **A. Minimum research (consent granted)** | NSE historical bhavcopy; NSE + NSE Indices consents free; no non-display fee | **≈ ₹30,000 (₹35,400 incl. GST)** |
| **B. Research, NSE sells instead of consenting** | Bhavcopy ₹30k–1.1L + EOD Corporate Data ₹5L + index history (quote, assume ₹0–1L) + non-display / derived (quote) | **≈ ₹5.3–7.1 lakh + quotes → ₹6.3–8.4 lakh incl. GST** |
| **B'. Research via BSE for company data** | Bhavcopy (NSE) ₹30k + BSE results / SHP / calendar ₹9L | **≈ ₹9.3 lakh → ₹11 lakh incl. GST** |
| **C. Prices-only fallback** | EODHD all-in-one, 1–2 months | **$100–200 (≈ ₹8.5k–17k)** |
| **D. Later product use (display to users)** | EOD prices web + app ₹2L + corporate data display ₹10.6–12L + derived-data redistribution (quote) | **≈ ₹13–15 lakh + quote → realistically ₹15–30 lakh / yr incl. GST** |

**Bottom line for the owner:** to stay within the leakage rules, research can probably be done for
**₹35,000 to ₹8 lakh**, depending on whether NSE gives written consent. Plan the larger product
licences (₹15 lakh+ a year) only if the experiments pass. Do not buy CMIE, ACE, Capitaline or
EODHD fundamentals for formal evidence: none of them shows when a number became public.

---

## 12. Open items for step R1 (after the owner chooses and consent / licence exists)

- Count how many of the 177 + 129 stocks and how many delisted names appear in the 2014–2021
  bhavcopies.
- Find the first month Midcap 150 appears (between Feb 2017 and Jan 2018) and extract PDF tables.
- Test the PREVCLOSE-based adjustment on 5–10 known splits and bonuses.
- Check how far back NSE announcements and XBRL results go for 3 stocks (incl. one delisted).
- Confirm the "broadcast date/time" field on NSE SHP and results pages.
- Re-point the KEI results reader to "Integrated Filing – Financials". This is a code change and
  needs your approval.
