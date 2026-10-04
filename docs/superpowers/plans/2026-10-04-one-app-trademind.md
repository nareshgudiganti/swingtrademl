# One Final App: TradeMind — Inventory and Phases

Owner decision (2026-10-04): "final application I need instead of these many". Production today
shows two apps side by side: the old v1 app (Dashboard, Positions, Strategies, Safety, Settings,
Brain console, Finance…) and the new TradeMind app at `/trademind`, which only views data. Goal:
**one app, TradeMind**, with every function the owner uses, then retire the old screens. The old
version stays as a backup: git tag `v1`, and a "Classic view" link during the changeover.

## Inventory: old screens and their functions, and what TradeMind has

Legend: ✅ TradeMind already has it · 🟡 partly · ❌ missing

| Old screen | What it does (functions) | TradeMind today |
|---|---|---|
| Top bar (App) | Zerodha login, connection badge, refresh data, brain mode badge, active models | 🟡 status only; no login, no refresh |
| Dashboard | Overview: money, today's buy list, market regime, open positions, strategy results, check one stock (`predict`), refresh data | 🟡 Home/Market/Portfolio cover overview + regime; no v1 buy list, no strategy results, no "check a stock" |
| Positions (`/portfolio`) | Open and closed positions, trades, **close a position by hand** | 🟡 Positions/Portfolio show them; **no close button**, no closed-trade list |
| Holdings | Your real Zerodha holdings, **import from Zerodha**, **mark as sold by hand** | ❌ |
| Real report | Real-money trading report, **import tradebook**, **sync real trades** | ❌ |
| Reports | Full trade history | ❌ |
| Scan results | What each daily scan found and why | ❌ (brain ideas yes, v1 scan no) |
| Strategies | List with results; **switch on/off**, create, delete, **scan now** | ❌ |
| Models | Model list, accuracy, predictions; **train**, **activate** | ❌ (System shows active models only) |
| Model lab | Calibration (is "60%" really 60%?) | ❌ |
| Capital | Risk limits, risk events log | ✅ Risk screen |
| Safety | **Stop / resume new trades**, safety log, connection state | 🟡 shows state; **no stop/resume buttons** |
| Brain console | Run brain now, **overrule a decision**, switch modules on/trial/off, alert preview/send, learning proposals, what-if, **go-live: stage switch, approvals (Approve/Reject), brain vs v1 comparison** | 🟡 views, proposals, what-if yes; **no go-live cards, no overrule, no run-now, no module switches, no alerts** |
| Settings | Account, **Zerodha login**, watch list edit, data coverage + **backfill**, **sync instruments**, Telegram status + **test message** | ❌ |
| Finance | Personal money manager: bank statements upload, transactions, categories, loans, mutual funds, recurring bills, daily expenses, insights (1,626 lines) | ❌ |
| Login / sign-up | Shared by both apps | ✅ |

## Phases (each phase ships on its own, small and safe)

1. **Daily essentials, so TradeMind can be home.** Zerodha login + connection, refresh data,
   stop/resume new trades, close a position by hand, brain go-live cards (stage, approvals,
   comparison), overrule, run brain now, module switches, alert preview/send.
2. **Records.** Trade history + closed trades, v1 scan results and buy list, strategy results,
   real holdings (import, mark sold) and the real-money report (tradebook import, sync).
3. **Setup.** Settings (watch list, data coverage/backfill, instruments, Telegram test), model
   accuracy and calibration (read-only), strategies list with on/off.
4. **Personal finance** as its own TradeMind section (largest single piece).
5. **Switch home to TradeMind.** Old screens move behind a small "Classic view" link for a
   couple of weeks, then are removed. Rollback = git tag `v1` / the previous release.

## Open owner decisions

- **Personal finance:** keep it inside the final app (phase 4) or as a separate app?
  Recommendation: keep it, as its own tab.
- **Strategy create/delete and model train/activate:** the v1 freeze (2026-09-28) earmarked these
  for v2 ("do not build into v1"). Recommendation: final app shows strategies and models
  read-only with on/off only; create/delete/train stay out until v2.

## Rules

Plain English, no invented numbers, TradeMind look (`trademind.css`), phone width without
sideways scroll, every action that changes something asks for confirmation, and nothing that
moves money skips the existing safety checks.
