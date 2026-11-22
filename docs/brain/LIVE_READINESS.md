# Live trading readiness (Phase 4)

Paper and M18 shadow can run without these. **Real auto orders** need the Phase 0 items below (copied from the old roadmap tracker; the archived original, kept only as history, is [ROADMAP_TRACKER.md](../archive/ROADMAP_TRACKER.md)).

| Item | Owner | Status |
|------|-------|--------|
| Static IP on Kite developer console | You | Open |
| DDPI on Zerodha account | You | Open |
| After-close entry method (AMO vs next-open limit) | Dev + you | Open |
| Broker GTT stops written from worker | Dev | Open |
| Kill-switch / exits drill recorded | You | Open |

M18 **Automatic** stage is separate: stay on **Practice** until [ROADMAP.md](ROADMAP.md) Phase 1 gate and 30 shadow ideas are done.

## Phase 0 checklist (moved from ROADMAP_TRACKER on 2026-11-21)

Copied word for word from the "Phase 0 — Make live trading *possible* (before any real auto order)" section of the
old `docs/ROADMAP_TRACKER.md`. Status marks are as they were on the last tracker update (2026-09-21) and may be stale.

- [x] **Market protection on MARKET / SL-M orders** (S, done and deployed 2026-09-21)
- [ ] **You:** register the droplet's static IP (147.182.176.105) on developers.kite.trade → IP Whitelist. All API orders from other IPs are rejected
- [ ] **You:** activate DDPI on the Zerodha account (₹100 + GST). Without it the bot cannot sell. *2026-09-21: not yet active; waiting for Zerodha's email*
- [ ] **You:** ask Zerodha support to confirm that a self-use algo under 10 orders/second needs no registration or Algo ID (the public reading says so; get it in writing)
- [ ] **Decide and build the after-close entry method** (M): AMO orders vs. next-morning limit orders. Confirm Zerodha's AMO window and rules first *(not verified)*. Live blocker R2
- [ ] Live **stop-loss held at the broker** (GTT) instead of only in our worker (M) — protects you if our server is down
- [ ] Kill-switch and exits-switch **drill on paper**, recorded (S)
- [ ] One paper-mode "fire drill" of a full live day with the broker call stubbed (S)
