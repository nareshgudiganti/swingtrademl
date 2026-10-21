# TradeMind: briefing pack for a SEBI compliance professional (D0a)

**Date:** 2026-10-21 · **Tracker:** ev16 "D0a Initial SEBI Research Analyst assessment" ·
**Prepared for:** the app's owner to hand to a SEBI compliance professional.

This pack describes facts and lists questions. It is **not legal advice** and draws no conclusion
about what is or is not permitted. Every regulation named below is for the professional to confirm,
including whether it applies and which version is current.

## 1. Summary

TradeMind (website swingtrademl.com) is a privately built web app for swing trading Indian (NSE)
equity shares. Every trading day it analyses a list of stocks and labels each one **TRADE / WATCH /
WAIT / AVOID**, with a suggested entry, target (+8%) and stop (−4%) over at most 15 trading days. Today
all automated trading is **simulated with pretend money ("paper")**. Real money appears in one place
only: the owner's own Zerodha account, which the app reads and comments on for the owner alone. Real
orders from the app are built but **switched off**. A handful of accounts exist: the owner, the
owner's secondary accounts and one tester. Nothing is sold, nobody pays and sign-up is closed. The
owner plans a small, free, invite-only pilot and, later, possibly a paid product. **No outside-facing
feature will be designed until this assessment (D0a) is back**, and no outside user will see the
pilot until a detailed written opinion on its exact design (D0b) is back.

## 2. What the app does today

| Part | What it does | Status |
|---|---|---|
| Market data | Daily NSE prices and related data, through Zerodha Kite Connect and other feeds | Live |
| "v1 bot" | Machine-learning models score stocks; rules turn scores into buy/sell decisions. Its own horizon: about +2% within 5 trading days | Live, **paper only** — places simulated orders in a simulated account |
| "TradeMind Brain" | Decision layer that labels ideas TRADE / WATCH / WAIT / AVOID (+8% target / −4% stop / half sold at +5% / exit within 15 trading days) and labels holdings HOLD / MONITOR / REDUCE / EXIT, with plain-English reasons | Live in **practice mode** since 2026-10-04: records ideas and their outcomes; places **no** orders |
| Trading mode | `TRADING_MODE=paper`; live trading needs a second switch `ALLOW_LIVE_TRADING`, which defaults to off | Paper; live switch off |
| My Holdings | Reads the owner's **real** Zerodha holdings and shows advisory reads (scores, stop-loss warnings) | Live, **owner account only** (`sudeeksha`) |
| Real orders from My Holdings | Owner can buy/sell by hand in their own Zerodha account, with per-order (₹10,000) and per-day (₹25,000) caps | Code on `main`; **switch `ALLOW_REAL_HOLDINGS_ORDERS` off by default**. Not verified on the live server for this pack |
| Telegram alerts | Daily summary, stop-loss and system messages to **one** chat (the owner's) | Live; one chat only |
| Testing book | A separate simulated account where a tester buys/sells by hand | Used by one tester (see §3) |
| Plans manager (Free / Pro) | Can limit what each plan sees | Built; **owner switch off**; no payment system exists in the code |
| Disclaimers | No investor-facing disclaimer or SEBI-related wording was found in the app's screens | Not found |
| Source code | The GitHub repository `nareshgudiganti/swingtrademl` is **public**. It contains the full code, design documents and research results; secrets are kept out of it | Public |

## 3. Who sees what today

| Account | Role | Sees | Can do |
|---|---|---|---|
| `sudeeksha` | Owner (the only one) | Everything, including My Holdings (real account) | Everything; only account allowed real-account access |
| Two other logins (`naresh`, `naresh.gudiganti23`) | Secondary members | Per the design, no owner powers and no My Holdings | — |
| `vijay` | Tester | The shared app, **including the same day's ideas**, while the plans switch is off; never the owner's private areas | Buy/sell by hand in the **testing book (pretend money)** only. 4-week manual usability test from 2026-10-15; no broker link, no payment |
| Public | — | Nothing: sign-up is closed (`ALLOW_SIGNUP` off by default and on the live server) | — |

Role rules come from the design `docs/superpowers/specs/2026-10-16-multi-user-portfolios-design.md`
(§6.5) and are on `main`. Whether every role change has been applied on the live server was not checked
for this pack.

## 4. What is planned (none of it is built for outside users yet)

| # | Planned feature | Who sees it | Money involved? | Automated orders? |
|---|---|---|---|---|
| P1 | **Pilot (D1–D4):** 5–10 invited users, free; research/education view; ideas shown **only after they finish**; honest track record; consent + disclaimer; payments off; no broker link; usage measured; weekly 5-question check-in; ask about willingness to pay | Invited users | No money taken. Users are **asked** if they would pay | No |
| P2 | **Release C — invite + manual paper pilot:** each invited member gets their own pretend-money account (₹10 lakh) and buys/sells by hand. The design shows **today's** ideas (TRADE ideas with levels) to members | Invited members | No | No (manual, pretend money) |
| P3 | **Release D — auto-follow:** the brain's ideas are bought and sold automatically in a member's **pretend-money** account; owner switches it on per account | Invited members | No | Yes, simulated only; no broker |
| P4 | **Release E — alerts per user:** each member can link their own Telegram chat; email sign-in/reset | Invited members | No | No |
| P5 | **Business test:** a waiting list or a priced pre-order survey, designed only after D0a/D0b | Wider public | Possibly (pricing asked; pre-orders not decided) | No |
| P6 | **Paid plans:** Free / Pro switch already built | Paying users | Yes, if ever turned on | Not decided |
| P7 | **Owner's own real money:** brain-driven orders in the owner's Zerodha account after a manual-approval trial | Owner only | Owner's own | Possibly, owner's account only |

Note a gap between documents: the pilot plan (P1) shows ideas only after they finish, while the
release C design (P2) shows the current day's ideas. The owner wants the professional's view before
choosing.

## 5. Questions for the professional

Regulations the owner believes may be relevant (to confirm, with current amendments): SEBI (Research
Analysts) Regulations, 2014 as amended, including the 2024 amendments; SEBI (Investment Advisers)
Regulations, 2013 as amended; SEBI's February 2025 circular "Safer participation of retail investors
in Algorithmic trading"; SEBI's October 2024 circular on association of regulated persons with
certain persons (the "finfluencer" rule) and its January 2025 clarification.

**A. Showing ideas**
1. Does showing TRADE / WATCH / WAIT / AVOID ideas (with entry, target and stop) to invited users,
   free of charge, need Research Analyst registration or another registration?
2. Does it matter whether ideas are shown the same day or **only after they finish** (past results)?
3. Does it change anything if the view is labelled "research / education", or if no target and stop
   are shown?
4. Is there a number of users, or a relationship (friends, family, testers), below which this is
   treated differently? A free pilot is not assumed to be exempt.

**B. Pilot and demand testing**
5. Does a free pilot with consent and disclaimer fall inside or outside the line?
6. Do a waiting list, a "would you pay?" question, or a priced pre-order survey change the answer?
7. Does publishing a track record (paper results) to users or the public raise advertising or
   performance-claim rules?

**C. Automation**
8. Does automatic following of the brain's ideas in a user's **pretend-money** account (release D)
   count as algorithmic trading or as advice?
9. If auto-follow ever touched a real broker account (not planned), what would apply (broker
   approval, algo registration, other)?

**D. Today's set-up**
10. Does the current tester set-up (one tester sees the same day's ideas and trades pretend money)
    already fall inside the line? If so, what should change now?
11. Do the secondary logins (no owner powers, no real-account access) raise any issue?

**E. Owner's own use**
12. Can the owner use the app for their own real Zerodha account, including manual real orders and,
    later, brain-driven orders in that account only? Does the Kite API / algo circular apply?

**F. Money**
13. What changes if any user pays (subscription, Pro plan, one-off), and what registration, fee
    limits or agreements would then apply?
14. Do the plans manager or the pricing question being built already count as an offer?

**G. Records, disclosures, public code**
15. Which disclaimers, risk disclosures, consents and records (ideas, reasons, outcomes, user
    access) should be kept now, even before any outside user?
16. Does a **public** GitHub repository with the full logic, research results and track records
    count as publishing research or recommendations? Should it be made private?
17. Are there data-protection points for storing invited users' emails and usage data?

## 6. What the owner needs back

- A **short written view per question** (yes / no / depends, with the reason and the rule it rests on).
- Which planned features (P1–P7) are **blocked until D0b** (the detailed written opinion on the exact
  pilot design), and which may be designed now.
- Anything in **today's** set-up (§2–3, especially Q10 and Q16) that should change **before** D0b.
- What D0b will need from the owner (documents, screens, draft disclaimers).

Until this view is back: no outside-facing feature is designed, no outside user sees ideas, no money
is taken, and all trading for anyone other than the owner stays pretend money.

**Sources for regulation names (to confirm):**
[RA Regulations listing](https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=3&smid=0) ·
[RA Regulations PDF](https://www.sebi.gov.in/sebi_data/commondocs/RESEARCHANALYSTS-regulations_p.pdf) ·
[RA advertisement code clarification, Oct 2024](https://www.sebi.gov.in/legal/circulars/oct-2024/clarification-with-respect-to-advertisement-code-for-research-analysts-ras-_87945.html) ·
[Retail algo trading circular, Feb 2025](https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html) ·
[Association with certain persons, Oct 2024](https://www.sebi.gov.in/legal/circulars/oct-2024/association-of-persons-regulated-by-the-board-and-their-agents-with-certain-persons_87837.html) ·
[Clarification, Jan 2025](https://www.sebi.gov.in/legal/circulars/jan-2025/details-clarifications-on-provisions-related-to-association-of-persons-regulated-by-the-board-miis-and-their-agents-with-persons-engaged-in-prohibited-activities_91356.html)

**Repo sources for the facts:** `CLAUDE.md`; `docs/architecture/CURRENT-STATE.md`;
`docs/superpowers/specs/2026-10-15-evidence-and-pilot-plan.md` (§5);
`docs/superpowers/specs/2026-10-16-multi-user-portfolios-design.md` (§3, §6.5, §10, §12);
`backend/src/swing_trade_ml/core/config.py`; `services/real_orders.py`; `services/plans.py`; `api/deps.py`.
