# #250 Verification: in-app price and paper-order alerts

Baseline commit: `5de3b9c` (main). Test database: `swing_trade_ml_dev1b_test`. Written 2026-11-24 (IST).
Tests and this note only. No alert, order, notification or frozen code was changed. No message was sent anywhere: every test
replaces the notifier with a recorder, or replaces the HTTP client and uses a made-up chat id. The note holds no chat id, token or
personal data.
New tests: `backend/tests/test_verify_250_alerts.py` (22 tests: 18 pass, 4 are strict expected failures that mark gaps).

## In plain English

The question: do the app's alerts fire once, at the right time, with correct numbers and honest labels, reach only the owner,
survive a quiet period, and not vanish when a send fails?

- **Price alerts behave.** A stop-loss or target alert for a holding fires once (not every minute), only when the price is at or beyond
  the level, with the right entry, current price and quantity. It carries no alert type, so the owner cannot switch it off and it is
  never held for quiet hours. The "confidence falling" warning fires once per episode, resets when the score recovers, and can start a
  new episode later.
- **The two flags are different things.** `advisory_alert_sent_at` (a stop, target or time limit was breached) makes the stock read as
  EXIT on screen. `confidence_alert_sent_at` (the model's conviction is fading) is the weaker "needs a look".
- **Paper-order alerts match what was stored.** An exit alert repeats the stored trade's entry, exit, quantity, profit, return and
  holding days; an entry alert repeats the stored order and position. Paper ones say PAPER and never LIVE. A real-money buy alert can
  never be switched off; a paper one can. A refused order is alerted with its own id and reason.
- **Alerts go only to the owner's one chat.** There is one configured chat; no alert is addressed to a user or a book, and the texts
  hold no account or person identifiers. Bot and Testing sells are labelled apart. (Who may see real-book data in the app is #426's
  scope and its tests.)
- **Held alerts are delivered once after the quiet period,** together in one message; a failed delivery keeps them held for the next
  run; sells and anything untagged are never held.
- **A stock sold elsewhere stops alerting** once the holdings sync closes it, and the stock still held keeps its one alert.
- **Four gaps found (none fixed):**
  1. **a6: the exit alert is not plain English.** It prints the internal code `Reason: STOP_LOSS_HIT` (and `TIME_STOP`, `TARGET_HIT`)
     and tells the owner to call `POST /portfolio/positions/<id>/manual-close`.
  2. **b5: an exit alert for a real (My Holdings) position says "PAPER".** The label comes from the bot's mode, not the position's
     mode, so a real-money holding is badged as practice while the bot is on paper.
  3. **e2: a stop-loss alert that failed to send is still marked as sent,** so it is never retried. Today a failed send only writes a
     log line.
  4. **e3: the same for the confidence warning** (the flag is set before the send).

## Findings table

| # | Question | Code (at `5de3b9c`) | Expected | Observed (test) | Result |
|---|---|---|---|---|---|
| a1 | Stop alert: once, right numbers, cannot be held | `services/execution.py:1574-1576` (send, then `advisory_alert_sent_at`); no `kind` so `alert_policy.py:168` `route` always sends | one message with entry, current price, quantity; second sweep silent | one message, numbers match, `("signal", None)`, flag set, no repeat (`test_a1_*`) | Pass |
| a2 | Target alert, and silence inside the band | `execution.py:1544-1546` (stop, then target), `:1574` | alert at or beyond the target only | silent at 102, one alert at 108.50 (`test_a2_*`) | Pass |
| a3 | Which flag surfaces where | `api/v1/endpoints/portfolio.py:291` (`alert_sent` from `confidence_alert_sent_at`), `:301` (`exit_alert_sent` from `advisory_alert_sent_at`); `execution.py:position_action` | stop flag reads EXIT, confidence flag does not | `test_a3_*` (the rule) and `test_a3b_*` (through the real `/portfolio/positions/detailed` endpoint: only-stop-flag holding reads `exit`, only-confidence-flag holding reads `alert`; swapping the two flags would fail it); `test_advisory_exit_alert_visibility.py` (2), `test_confidence_decay.py` (18) | Pass |
| a4 | Confidence alert: once per episode, right numbers | `execution.py:800-829` (pure rule), `:834-886` (flag at `:867`, reset `:878`), `:2093` text | one alert, "80% → 40% (down 40%)", reset on recovery, new episode alerts again | as expected; tagged `holding_warnings` so the owner may mute or hold it (`test_a4_*`) | Pass |
| a5 / a6 | Text: numbers (see a1) and plain wording | `execution.py:2052-2062`, `:1965-1975` (`Reason: {reason}` prints the enum value) | words, no codes, no API path | `Reason: STOP_LOSS_HIT` and `POST /portfolio/positions/67/manual-close` | **GAP** |
| b1 | Exit alert matches the stored trade; says paper | `execution.py:619`, `:1965-1975` | same entry, exit, quantity, P&L, return, days; "PAPER · Bot", no LIVE | all match (`test_b1_*`) | Pass |
| b2 | Entry alert matches the stored order and position | `execution.py:264-268`, `:1943-1953` | same quantity, price, order id, stop; PAPER | all match; kind `paper_buys` (`test_b2_*`) | Pass |
| b3 | Rejected order alerted | `execution.py:1882-1908` | id and reason, cannot be held | id, symbol and reason shown, `("error", None)` (`test_b3_*`; sell-failure path also in `test_money_execution_edges.py`) | Pass |
| b4 | Real buy cannot be muted, paper can | `execution.py:1938-1940`, `alert_policy.py:83` | real: no kind; paper: switchable | as expected (`test_b4_*`; `test_alert_settings.py::test_paper_buys_switchable_real_buys_never`) | Pass |
| b5 | Real holding's alert never says paper | `execution.py:1575` passes `broker.mode`; the other-book branch (`:1581-1587`) passes `position.mode` | LIVE or no PAPER for a live position | badge "PAPER" on a live My Holdings position | **GAP** |
| c1 | Alerts go to one configured chat only | `notifications/telegram.py:85-107` (`_post`) | the one configured chat id | one request, to the configured (made-up) id (`test_c1_*`; no network) | Pass |
| c2 | No person or account data in a text | `execution.py:2052`, messages | none | none found (`test_c2_*`; a weak check: it bans a short word list in one stop alert and cannot prove no identifier ever appears) | Pass |
| c3 | Books labelled | `execution.py:1960-1962` `_badge`, `services/sell_labels.py:26` | "Bot" and "Testing" in the badge | both present (`test_c3_*`) | Pass |
| d1 | Held alert delivered once after quiet hours | `services/alert_settings.py:134-160` (`gate` holds), `:162-208` (`flush`), `alert_policy.py:179` (`due`) | held at night, nothing at 01:30, one message at 07:30, not again; sells never held | as expected (`test_d1_*`; `test_alert_settings.py`, 27 tests, covers digest and settings) | Pass |
| d2 | Failed delivery of held alerts | `alert_settings.py:196-204` (marked sent only after Telegram took it) | stays held, retried | stays held, then sent (`test_d2_*`) | Pass |
| e1 | A failed send is recorded | `notifications/telegram.py:93-107` | a record the owner can see | returns False and writes a log line only (`test_e1_*`) | Pass (log only) |
| e2 | Failed stop alert is retried | `execution.py:1574-1576` | flag stays empty so the next sweep retries | flag is set although the send failed | **GAP** |
| e3 | Failed confidence alert is retried | `execution.py:867-871` | flag stays empty | flag is set before the send | **GAP** |
| f1 | Ghost holding stops alerting | `services/holdings_sync.py:46-100`, `execution.py:check_exits` | closed holding silent, held one keeps its single alert | as expected (`test_f1_*`; `test_real_holdings_orders.py`) | Pass |
| f2 | An empty or failed holdings load never closes everything | `holdings_sync.py` (caller passes the held set) | held stock stays open | stays open (`test_f2_*`) | Pass |
| f3 | Closing a ghost | `execution.py:660` `manual_close_position` | one alert, marked as a manual close | one alert, reason MANUAL, a trade row stored (`test_f3_*`) | Pass |

## Gaps for the owner (one line each, none fixed)

- **a6:** write the exit alert reason in words ("hit your stop-loss") and drop the API path from the message.
- **b5:** label an exit alert for a real (My Holdings) position with the position's own mode, not the bot's.
- **e2 / e3:** set the "alert sent" flag only after the send succeeds (or record the failure and retry). This touches the exit-alert
  path and the alert wiring, so it needs the owner's approval.

## Limits worth knowing (not gaps)

- A failed send leaves only a log line (`telegram.send_failed`); the app stores no failed-send record the owner can see (e1). The held
  outbox does not have this problem (d2).
- The single Telegram chat is the owner's; there is no per-user Telegram alert, so "never reaches another user" holds by construction.
  The in-app flags are read per screen and book (#426 covers who may see the real book).

## How the gap tests work

Each gap is a test that states what the code SHOULD do, marked `xfail(strict=True, raises=AssertionError)`. They fail today for the stated
reason (checked with `--runxfail`). If a gap is fixed the strict marker turns the test red and is then removed on purpose.

## Not covered here

Real brokers, live orders, the real Telegram service, production and the owner's accounts were not touched. The brain's own alert wording
(`brain/alerts`) is covered by `test_brain_alerts*.py` and not re-judged here. The sealed trial was not touched.

Re-run for this note (dev1b): the new file plus `test_alert_policy.py`, `test_alert_settings.py`, `test_confidence_decay.py`,
`test_advisory_exit_alert_visibility.py`, `test_telegram_production_only.py`, `test_money_execution_edges.py` and `test_real_holdings_orders.py`:
**162 passed, 4 xfailed** (the four gaps).
