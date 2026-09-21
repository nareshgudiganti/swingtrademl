# Roadmap and tracker: from "ML signals" to "an expert swing trader that runs itself"

Written 2026-09-21. Supersedes the status tables in
`docs/superpowers/research/2026-09-14-quant-gap-roadmap-to-10L.md`, which is a week
old and now wrong about what is built. Reviews the two ChatGPT PDFs (quant-gap
roadmap, platform blueprint) and the two mockups (TradeMind dashboard, end-to-end
workflow) against the code as of commit `ee811b4`.

Update the **Status** column and the checkboxes as work lands. Anything marked
*not verified* was not confirmed against a primary source this session.

---

## 1. The honest answer first

**Is the analysis done?** Yes — on 14 Sep. Both PDFs were compared with the code, and
Stages 1 and 2 of that plan have since been built (below). What was *not* done is a
fresh look at the two mockups, the data sources, and the live-trading rules, which
is what this document adds.

**The uncomfortable fact that shapes everything.** The models have a real but *small*
edge. On the honest walk-forward test (barrier label, +8% before −4% in 15 days),
ROC AUC is 0.556–0.583 (0.5 is a coin flip), and 2 of 15 folds were at or below 0.5.
The earlier ablation showed that adding sector, breadth and VIX features moved
nothing. So:

> More price-pattern features and fancier models will not turn this into an expert.
> A human swing trader who earns well is not out-predicting the price chart. They
> use **information the chart does not contain** (results, institutional buying,
> delivery, positioning, news), they are **very selective**, and they are
> **strict about risk and exits**. The application should copy those three things.

Risk and exits are now largely built. **Information is the gap.** That is the plan.

**No system can promise "nice profits".** What we can do is make each trade have a
better-than-even, *measured* chance, keep losses small, and prove it on paper before
real money grows. Everything below is aimed at that, and every claim gets measured.

---

## 2. Where we are — status against both PDFs and both mockups

Status: DONE · PARTIAL · NOT BUILT. Evidence is from code and commits, not from the
PDFs' own status tables.

### Model and validation
| Item | Status | Evidence / note |
|---|---|---|
| Label matches the trade (+8% before −4%, 15 days) | DONE | `dd1f4c4`; three barrier models trained, running as advisory shadows |
| Walk-forward validation (5 folds, purged) | DONE | `9731251` |
| Confidence calibration report | DONE | `1f69855`, `ml/calibration.py` |
| Lost ablation results recovered | DONE | `docs/.../2026-09-15-ablation-results-recovered.md` |
| Barrier models promoted over the old ones | NOT DECIDED | Waiting for shadow signals to resolve; evidence not yet in |
| Re-run ablation on the barrier label | NOT BUILT | Old null result may not hold |
| Exit model with its own label | NOT BUILT | Exits still read the entry model's probability |
| Hysteresis on exit threshold | NOT BUILT | |
| Drift monitoring (features, outcomes by bucket) | NOT BUILT | Only per-position confidence-decay alerts |
| Champion / challenger | NOT BUILT | Registry supports versioning and rollback |
| Scheduled monthly retrain (challenger only) | NOT BUILT | Retraining is CLI-only |

### Risk and capital
| Item | Status | Evidence / note |
|---|---|---|
| Sector cap, cap-tier budget, cash floor | DONE | `d3a8497`, `services/limits.py` |
| Limits that scale with account size (₹10K → ₹1Cr ladder) | DONE | `services/limits.py`, `GET /risk/limits` |
| Regime → deployable capital (rule table) | DONE | `services/deployable.py` |
| Kill switch, exits switch, risk-event log | DONE | Safety page, `services/system_state.py` |
| Drawdown brake on today's account | DONE | `ba8d107` |
| In-flight buys counted against limits | DONE | `1ebe853` |
| Partial profit booking (half at first target) | DONE | `7d849de` |
| Sell-once latch; exit reason recorded | DONE | `d5cff86` |
| Broker-held stop-loss (Zerodha GTT) | PARTIAL | Columns exist, nothing writes them yet |
| Surveillance-list filter (ASM / GSM / T2T stocks) | NOT BUILT | See risk R9 |
| Correlation cap | NOT BUILT | Sector cap covers most of it |

### Execution and live readiness
| Item | Status | Evidence / note |
|---|---|---|
| Live order path with two-flag latch | DONE | `brokers/kite.py` |
| **Market protection on API market orders** | **DONE 2026-09-21** | Zerodha rejects them without it since 1 Apr 2026. Was a live-trading blocker; see R1 |
| **Entries at the right time (after-close orders)** | **NOT BUILT** | Scan runs 15:45 and sends *regular* orders after the close. Live, those are rejected. Needs the AMO / next-open-with-limit design decided on 14 Sep. **Live blocker R2** |
| Static IP registered with Zerodha for the droplet | UNKNOWN | Owner action; required for every API order |
| DDPI on the Zerodha account | UNKNOWN | Owner action; without it, automated selling is impossible |
| Unattended Kite login | DONE | Working as of 2026-09-18 |
| Assisted-live (approve each order from Telegram) | NOT BUILT | Telegram sends alerts only |
| Order reconciliation | DONE | Scheduled job |

### Reporting and trust
| Item | Status | Evidence / note |
|---|---|---|
| Real Zerodha holdings tracked with model read | DONE | My Holdings |
| Real buy/sell report and P&L after charges | DONE 2026-09-21 | `ee811b4`; history needs a tradebook file import |
| Post-exit tracking | PARTIAL | 21-day watch and "since sold" columns; no Day 1/3/5/7, no benchmark, no early/good/poor label |
| Paper vs real vs auto kept visibly separate | PARTIAL | Holdings vs Portfolio are separate; no single three-way view |

### Data and features (the biggest gap)
| Family | Status |
|---|---|
| Price, trend, momentum, volatility, volume | DONE (53 features) |
| Relative strength vs NIFTY and vs sector, INDIA VIX, breadth | DONE — and *did not help* on the old label |
| Delivery percentage, bulk/block deals, institutional flow | PARTIAL — stored daily since 2026-09-21; not yet model features |
| Results dates, corporate actions, announcements | NOT BUILT |
| Fundamentals (growth, margins, leverage) | NOT BUILT — hardest item, see §4 |
| Futures and options positioning (open interest, PCR) | NOT BUILT |
| Global cues (US futures, crude, dollar-rupee) | NOT BUILT |
| News and events | NOT BUILT — deliberately last |
| Order-book depth / spread | NOT BUILT — cannot be back-filled; start recording |

### The two mockups
| Mockup element | Status |
|---|---|
| Home: one-line daily brief, "what needs attention" | PARTIAL — Dashboard has Needs attention / Worth buying / Recent exits |
| Signal cards with confidence, reason, risk | DONE (plain-English) |
| Capital screen, Safety screen, Model Lab | DONE (built to the design canvas in `.design-src/`) |
| Market-regime gauge on Home | NOT BUILT (regime is used, not shown as a gauge) |
| Portfolio vs NIFTY chart | NOT BUILT |
| Capital allocation donut (Large/Mid/Small/Cash) | PARTIAL — Capital page |
| "Model engine status" panel (data updated → scanned → candidates → risk checked) | NOT BUILT — good trust feature, cheap |
| Exited Recently 7-day timeline | PARTIAL — see post-exit |
| Approvals screen | NOT BUILT (design exists: `.design-src/Approvals.dc.html`) |
| The mockup's "Upgrade to Pro / billing / user support" | OUT OF SCOPE — single-user app; also see R13 |

---

## 3. What an expert swing trader actually does, and where we copy it

| What experts do | Why it makes money | In this app |
|---|---|---|
| **1. Read the market first.** Trade big when the market is healthy, small or not at all when it is not | Most losses come from buying good setups in a bad tape | Regime → deployable % **built**. Add FII/DII flow and global cues to it |
| **2. Follow the strongest sectors** | Money rotates; leaders lead | Sector relative strength is a feature. Add a *sector ranking* that gates candidates |
| **3. Pick stocks with a reason beyond the chart:** improving earnings, institutions accumulating, high delivery on up days, a fresh catalyst | This is the information edge | **Not built. Phase 1** |
| **4. Buy a proper setup** — breakout from a tight base on volume, pullback to a rising average — not just "score > 0.6" | Defined entry = defined stop = small loss | Add a **playbook layer** (§6) that produces candidates; ML then ranks them |
| **5. Avoid landmines:** results tomorrow, ex-dividend/split, surveillance-list stocks, illiquid names | One bad gap undoes ten good trades | Results-date and ASM/GSM/T2T filters. **Phase 1** |
| **6. Risk a fixed small amount per trade** | Survival | **Built** (sizing off distance to stop) |
| **7. Bank part early, trail the rest, cut time-wasters** | Turns a 55% hit rate into profit | **Built** (half at first target, trail, time stop). Exit *model* and hysteresis still missing |
| **8. Keep a journal and review honestly** | Finds what actually works | Post-exit engine + P&L report. Add Day 1/3/5/7, benchmark, early/good/poor label |
| **9. Stay out when unsure** — cash is a position | | **Built** |

**The recommended architecture — "playbooks propose, ML ranks, rules protect":**

```
Market data + information feeds (§4)
   -> Regime + sector ranking            (rules, readable)
   -> Playbook candidates                (breakout / pullback / earnings-drift; rules)
   -> Landmine filter                    (results, corporate action, ASM/GSM, liquidity)
   -> ML score, calibrated               (does this candidate work now?)
   -> Risk + allocator                   (sector cap, cash floor, deployable %, size)
   -> Approval (phase-dependent)         (shadow -> assisted -> auto)
   -> Broker (AMO / limit at open, market protection, stop at broker)
   -> Monitor + exit engine              (partial profit, trail, exit model, hysteresis)
   -> Post-exit review + drift + challenger model
```

Why not pure ML over all ~300 stocks, as today: with an AUC near 0.56 the model
cannot find needles alone. Restricting it to already-sensible setups raises the base
rate it starts from — and it is how the expert works.

---

## 4. Data sources — what to integrate

"Point-in-time safe" = we can know when the fact became public, so a backtest cannot
peek. **Rule: from day one, store every daily snapshot with the date we fetched it.**
That alone makes each new feed point-in-time safe going forward.

Verified this session unless marked.

| # | Source | What we get | Cost | How | Point-in-time | Priority |
|---|---|---|---|---|---|---|
| 1 | **NSE daily bhavcopy + delivery file** | Every stock's price, volume, and *the share of volume taken for delivery* | Free | Static files on NSE's archive site; the stable route, unlike scraping the website | Yes (dated files) | **P1** |
| 2 | **NSE bulk and block deals** | Big buyers and sellers named | Free | NSE reports / archive | Yes | **P1** |
| 3 | **FII / DII daily net buy-sell** | Institutional direction | Free | NSE provisional numbers (unofficial libraries such as `nselib` wrap it; expect breakage) | Yes if stored daily | **P1** |
| 4 | **NSE corporate announcements + XBRL results** | Results dates, results themselves, dividends, splits, board meetings | Free | NSE filings; XBRL arrives within 24 hours of the PDF | Yes (filing timestamp) | **P1** for dates and corporate actions; **P3** for results-as-features |
| 5 | **F&O bhavcopy, participant-wise open interest, option chain** | Positioning: open-interest build-up, put/call ratio | Free | NSE archive | Yes | P2 |
| 6 | **ASM / GSM / T2T surveillance lists** | Stocks with trading restrictions | Free | NSE lists *(not verified this session)* | Yes | **P1** (filter) |
| 7 | **Kite Connect** (already used) | Candles, quotes, orders | ₹500/month for the data plan; free personal plan has no market data | API | Yes | Have |
| 8 | **Global cues:** US index futures, crude, dollar-rupee, US 10-year | Overnight risk-on / risk-off | Free feeds exist; reliability varies *(not verified)* | Daily snapshot | Yes if stored | P2 |
| 9 | **News / announcements text** | Event risk, sentiment | RSS free; scoring by a language model costs API tokens | Fetch, timestamp, score | Only from the day we start recording | **P4, last** |
| 10 | **Order-book depth** (Kite) | Spread, liquidity | Free with the data plan | Record snapshots now | Cannot be back-filled | Start recording in P2 |
| 11 | Paid fundamentals APIs (FinEdge and similar) | Ratios, statements | Paid; coverage and history *not verified* | API | Doubtful | Evaluate only if XBRL parsing proves too costly |
| 12 | Screener.in, Trendlyne, Tickertape, Chartink, TradingView | Great for a human | — | No public API; scraping likely breaches their terms | — | **Avoid for automation.** Use as a *manual cross-check* only |

**Fundamentals — the honest cost.** The 12 Sep vendor study found no credible paid
point-in-time source for Indian equities at retail scale. The free route is parsing
NSE XBRL. Its trap is *restatements*: using today's corrected figures for a past date
makes a backtest look brilliant and the live model useless. Budget weeks; treat as
its own project after Phase 1 shows whether *any* information feature helps.

**NSE website scraping risk.** The website blocks bots and changes without notice.
Prefer the archive files; wrap every fetch so a failure raises a Telegram alert
instead of silently feeding stale data.

---

## 5. The workflow, end to end

### What runs when (IST)
| Time | What happens | Human? |
|---|---|---|
| 06:10 | Auto-login to Zerodha | No (Telegram alert if it fails) |
| 06:30 *(new)* | Fetch overnight global cues, previous-day FII/DII, corporate-action and results calendar | No |
| 08:45 *(new)* | Morning brief on Telegram + Home: market regime, deployable %, today's landmines | Read |
| 09:15–09:30 *(new)* | Place approved limit orders at the open (or AMO orders placed the evening before fill) | Approve, in assisted phase |
| 09:15–15:30 | Prices, stops, exits checked every minute | No |
| 15:40 | Daily candles; bhavcopy + delivery + bulk/block + F&O (available after close) | No |
| 15:45 | Scan: regime → sector → playbooks → landmine filter → ML → risk → proposals | No |
| 15:50 | Save today's real trades (buy/sell report) | No |
| 16:00 | Snapshot and daily summary | Read |
| Evening *(new)* | Proposals wait for approval; AMO placed on approval | Approve |
| Monthly *(new)* | Challenger model trained; drift report | Decide promote / reject |

### Three modes, never blended
Real holdings (monitored) · Paper (virtual money, same pipeline) · Auto live (real
orders). Every screen labels which money it shows.

---

## 6. Phased plan and tracker

Effort: S = a day or two, M = about a week, L = several weeks. "You" = an action only
the account owner can do.

### Phase 0 — Make live trading *possible* (before any real auto order)
- [x] **Market protection on MARKET / SL-M orders** (S, done and deployed 2026-09-21)
- [ ] **You:** register the droplet's static IP (147.182.176.105) on developers.kite.trade → IP Whitelist. All API orders from other IPs are rejected
- [ ] **You:** activate DDPI on the Zerodha account (₹100 + GST). Without it the bot cannot sell. *2026-09-21: not yet active; waiting for Zerodha's email*
- [ ] **You:** ask Zerodha support to confirm that a self-use algo under 10 orders/second needs no registration or Algo ID (the public reading says so; get it in writing)
- [ ] **Decide and build the after-close entry method** (M): AMO orders vs. next-morning limit orders. Confirm Zerodha's AMO window and rules first *(not verified)*. Live blocker R2
- [ ] Live **stop-loss held at the broker** (GTT) instead of only in our worker (M) — protects you if our server is down
- [ ] Kill-switch and exits-switch **drill on paper**, recorded (S)
- [ ] One paper-mode "fire drill" of a full live day with the broker call stubbed (S)

### Phase 1 — Add the information edge (the main lever)
- [x] Daily **snapshot store** for every external feed, dated on fetch (S) — tables `daily_delivery`, `block_deals`, `institutional_flows` (2026-09-21)
- [x] NSE bhavcopy + **delivery %** loader with automatic ~400-day history backfill (2026-09-21)
- [ ] Delivery **features**: delivery ratio, delivery on up-days, 5/20-day trend, fed into the model (M)
- [x] **Bulk / block deals** loader (2026-09-21); history starts from now (NSE publishes only the latest day)
- [ ] Bulk/block **feature**: named accumulation in the last N days (S)
- [x] **FII / DII** daily flows loader (2026-09-21)
- [ ] Feed FII/DII into the regime rule table (S)
- [x] **Results calendar + corporate actions**; entries refused within 3 days of results and 2 days of a split/bonus/rights (2026-09-21, `services/avoid.py`). Split/bonus *price adjustment* of stored candles still to verify
- [x] **ASM / GSM / T2T filter** (2026-09-21) — NSE's ASM and GSM lists fetched each morning, trade-for-trade read from the series column. On day one 5 of the 304 traded stocks were on a watch list
- [ ] **Re-run the feature ablation on the barrier label** with the new families, walk-forward. *Keep only what moves ROC AUC or top-bucket precision by more than noise* (M)
- Exit test: at least one new family improves walk-forward results, or we stop adding data and say so plainly.

### Phase 2 — Playbooks and ranking
- [ ] Playbook candidate generators: base breakout on volume, pullback to a rising average, post-results drift (M each)
- [ ] Sector ranking gate: only candidates from the strongest sectors (S)
- [ ] ML rescoring restricted to candidates; compare against today's "score everything" on the same paper stream (M)
- [ ] Try a **ranking objective** (rank stocks against each other each day) versus the current yes/no classifier (M)
- [ ] Decide promotion of the barrier models over the old ones, on shadow-stream evidence (S)

### Phase 3 — Smarter exits and honest review
- [ ] Hysteresis on the exit threshold (S)
- [ ] **Exit model** with its own label (M)
- [ ] Post-exit **Day 1/3/5/7**, versus NIFTY and sector, with a protected / good / neutral / early / poor label (M)
- [ ] Exit-quality summary on Reports ("we exited early on N%") (S)

### Phase 4 — Keep it healthy
- [ ] Drift monitor: feature shift, outcome by confidence bucket, by regime (M)
- [ ] Monthly scheduled **challenger** training, never auto-promoted (S)
- [ ] Champion vs challenger report on the same forward stream (M)
- [ ] Model artifact **backup** off the droplet (the 2026-09-15 recovery lost three) (S)

### Phase 5 — The screens (mockup parity, plain English)
- [ ] Home: one-sentence daily brief + regime gauge + "3 things need attention" (S)
- [ ] **Model engine status** panel: data updated → scanned → candidates → risk-checked → signals (S)
- [ ] Portfolio vs NIFTY chart (S)
- [ ] Capital allocation donut incl. cash (S)
- [ ] **Approvals** screen and Telegram approve/reject buttons (M) — needed for assisted live
- [ ] Exited Recently 7-day timeline (S, after Phase 3)
- [ ] One "real / paper / auto" switcher with separate totals (S)
- [ ] Data-freshness strip: last time each feed updated (S)

### Phase 6 — Earn the live switch (staged capital)
Gates from the 14 Sep roadmap still apply: ≥150 closed trades, calibration within 10
points on populated buckets, ≥3 walk-forward folds none negative, ≥2 regimes, drawdown
within your rupee limit, model beats the SMA benchmark, exits scored, safety drills
done, ≥30 clean daily logins.
- [ ] Shadow live: exact would-be orders logged, none sent
- [ ] Assisted live at ₹10K–₹25K: you approve each order
- [ ] Ladder up only when the gates hold for a month at each rung (limits already scale by account size)
- [ ] Auto live, behind everything above

### Later, only if earned
- [ ] Fundamentals from NSE XBRL (L)
- [ ] News/event scoring by a language model — as a **filter and explainer**, never the buy/sell decider (L)
- [ ] A second broker API for data redundancy (M)
- [ ] Options-based hedging (out of scope for now)

---

## 7. Alternatives and trade-offs

| Decision | Options | Recommendation | Why |
|---|---|---|---|
| Where the edge comes from | (a) more price features, (b) new information feeds, (c) playbook candidates | **(b) then (c)** | (a) already tested and flat |
| Model shape | Yes/no classifier · daily ranking model · expected-return regression | Keep the classifier now; **try ranking in Phase 2** | Swing trading is choosing the best few of many each day |
| Rules vs learning for regime | Learned model · rule table | **Rule table (built)** | Too few real regime changes in five years to learn |
| Buy vs build market info | Streak, Sensibull, Chartink, Screener (manual tools) · own pipeline | **Own pipeline for anything that feeds trades; the manual tools as cross-checks** | No public APIs; terms restrict scraping; not reproducible |
| Broker | Stay on Zerodha Kite · Angel SmartAPI, Dhan, Upstox, Fyers (free-to-cheap APIs) | **Stay on Kite; consider one as a data backup later** | You already hold real positions there; API data quality and free-history depth vary between brokers *(comparison from web summaries, not verified)* |
| Language models | Decide trades · summarise and filter | **Filter and explain only** | Not reproducible or calibratable; would undo the leakage discipline |
| Going live | Straight to auto · staged | **Staged, with gates** | The only thing that makes the evidence real |
| Hosting | One droplet · managed cloud | Stay, but **add backups and an uptime alert** | A single machine is the weakest link at real money |

---

## 8. Risk register

| # | Risk | Likelihood | Impact | What we do | Status |
|---|---|---|---|---|---|
| R1 | Zerodha rule changes reject our orders (this already happened: market protection, 1 Apr 2026) | High | Trading stops | Fixed. Add a **daily canary**: a tiny validated order dry-run or order-margin check each morning; alert on any API rule error | Fixed; canary open |
| R2 | After-close entries sent as regular orders are rejected | Certain if live | No entries | Phase 0 entry-method decision | Open — blocker |
| R3 | Model edge is small and unstable across regimes | High | Slow bleed after costs | Measured gates, staged capital, kill switch, drawdown brake | Mitigated |
| R4 | Overfitting new features | Medium | False confidence | Walk-forward only; keep a final untouched window; ablate every addition | Process |
| R5 | Look-ahead leakage from new data | Medium | Fake backtests | Dated snapshots; restatement discipline for fundamentals | Process |
| R6 | NSE site or unofficial library breaks | High | Stale features | Archive files; freshness strip; Telegram alert on a missed feed | Open |
| R7 | Kite token killed mid-day (opening the Kite app) | High | Blind hours | Re-login and retry built for orders and quotes | Mitigated |
| R8 | Server or database loss | Low–medium | Lose history, open positions unmanaged | Backups exist per deploy; add off-machine copy and **broker-held stops** | Partial |
| R9 | Stock on a surveillance list (ASM / GSM / T2T) | Medium | Cannot exit freely, higher margin | Filter (Phase 1) | Open |
| R10 | Results or corporate-action gap | Medium | Large single-day loss | Calendar filter; sector and size caps | Open |
| R11 | Small-cap illiquidity and slippage | Medium | Worse fills than the cost model | Liquidity floor; record depth now; cap-tier budget built | Partial |
| R12 | Credentials on the server (password, TOTP seed) | Low | Account takeover | Harden the droplet: SSH keys only, firewall, no password login, rotate secrets | Owner to review |
| R13 | Regulation: your own algo is fine at this scale; **recommending stocks to other people or running money for others is not** | Low now | Serious | Stay single-user; take legal advice before any sharing. The mockup's Pro plans / billing would trigger this | Guardrail |
| R14 | Tax on profits (short-term vs long-term rates) | Certain | Net returns lower | The report shows profit *before tax*; rates change, so confirm with an accountant *(not verified)* | Note |
| R15 | Overnight gaps and circuit limits | Medium | Stop does not protect | Position sizing assumes gaps; broker-held stops do not fully help | Accepted |
| R16 | Over-trusting the UI's confidence number | Medium | Bad decisions | Calibration report shown beside every confidence; "trained, not in use" labelling | Partial |
| R17 | Scope: the finance and mutual-fund modules compete for time | Medium | Slower trading work | Freeze them; trading roadmap first | Decision needed |

---

## 9. Decisions and actions for the owner

1. **Static IP registration and DDPI** — status? (Phase 0; both are a few minutes and gate live trading.)
2. **Which live entry method** — evening AMO order, or a limit order placed at 9:15 after you approve the evening proposal. Recommended: approve in the evening, order at 9:15 with a limit, cancel if the open is beyond it (the 14 Sep decision).
3. ~~Approve Phase 1 data feeds~~ — **approved 2026-09-21** (NSE bhavcopy/delivery, bulk-block, FII/DII built; results/corporate actions and surveillance lists next)
4. ~~Freeze the finance and mutual-fund work~~ — **decided yes, 2026-09-21**. No new finance/mutual-fund features until Phase 1–3 land
5. **Personal money vs the bot:** should the bot ever manage your own hand-picked holdings, or stay read-only there? (Open since the Real Trading tab.)

---

*Planning document. Nothing here is a projection or guarantee of returns. Paper results,
backtests and calibration are evidence about past behaviour, not about future capital.*
