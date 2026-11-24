# #251 Verification: notification preferences and delivery failures

Baseline commit: `5de3b9c` (main). Test database: `swing_trade_ml_dev2b_test`. Written 2026-11-24 (IST).
Tests and this note only. No notification, alert, order or frozen code was changed. Nothing was sent anywhere: the Telegram network
call and the HTTP client are replaced by recorders, the email sender is the in-memory log sender or a stub, and every token and chat
id is a made-up placeholder. This note holds no token, chat id, address or personal data.
New tests: `backend/tests/test_verify_251_notifications.py` (21 tests: 17 pass, 4 are strict expected failures that mark gaps). Cited,
not repeated: Developer-1's #250 note (`docs/verification/250-alerts.md` on `test/250-alerts`, where e2/e3 show that a stop-loss or
confidence alert whose send failed is still marked sent) and the existing suites `test_alert_policy.py`, `test_alert_settings.py`,
`test_account_auth_email.py`, `test_brain_alerts_service.py`, `test_telegram_production_only.py`.

## In plain English

The question: are the owner's notification choices stored and respected, can a safety alert never be switched off, and is a failed
delivery never silently lost?

- **Preferences work as designed.** With nothing stored, every alert is on and nothing is held. Each of the six informational types
  (new buy ideas, practice buys, score slipping, end-of-day summary, weekly report, app status) can be switched off, and then it is
  dropped. Quiet hours hold them and send them once, as one message, when quiet hours end. A change is written to the audit log with
  who made it. Only an owner can read or change the settings.
- **Safety alerts cannot be muted.** Sells and stop-losses, real-money orders, safety stops, login problems and system problems are
  never tagged as switchable. The settings API refuses to switch any of them off (422), the router ignores them even if a stored row
  named one, and a scan of the whole app shows the only things tagged as switchable are the six informational types. A paper buy can be
  muted, a real-money buy never can. At 23:00 with quiet hours on, a buy idea is held while a stop-loss goes straight out.
- **A held alert is not lost.** It is marked sent only after Telegram took it; if delivery fails it stays held and is tried again; a
  partly delivered batch marks only what arrived.
- **Four gaps, none fixed (each is a strict expected-failure test):**
  1. **The settings are one shared row, not per user.** Every owner account and the shared key read and overwrite the same settings.
  2. **A refused direct send is not retried and not recorded.** If Telegram answers 429 or 5xx the message is tried once and only a log
     line is written. Held alerts are retried; direct ones (including stop-loss, see #250 e2/e3) are not.
  3. **A server setting can silence a stop-loss.** `TELEGRAM_NOTIFY_ON` filters by event before any safety rule; leaving out `signal`
     silently drops stop-loss alerts. It is an operator setting, not a user preference, but the "can't be muted" promise does not cover it.
  4. **A failed email is invisible to the owner.** A verification or reset email that could not be sent leaves only a log line. The
     person can ask for a resend (rate limited); the owner is not told.

## Findings table

| # | Question | Code (at `5de3b9c`) | Expected | Observed (test) | Result |
|---|---|---|---|---|---|
| p1 | Defaults when nothing is stored | `services/alert_settings.py:40-55` (`_prefs(None)`), `api/v1/endpoints/notifications.py:75` | all on, no quiet hours, no digest, times 22:00 / 07:00 / 18:00 IST | as expected (`test_p1_*`; also `test_alert_settings.py::test_owner_reads_defaults`) | Pass |
| p2 | Empty or missing stored values mute nothing | `alert_settings.py:40-55` | nothing muted | `disabled_kinds=None` loads as nothing muted (`test_p2_*`) | Pass |
| p3 | Each switchable type respects on and off | `notifications/alert_policy.py:168-176` (`route`) | off = drop, on = send, other types unaffected | all six types (`test_p3_*`; `test_alert_policy.py`) | Pass |
| p4 | A safety type cannot be switched off | `alert_policy.py:87-120` (`ALWAYS_ON`), `:192-198` (`validate`) | API 422; router ignores a stored name | all five refused, all sent (`test_p4_*`; `test_alert_settings.py` for `sells`) | Pass |
| p5 | Only the six informational types are ever tagged | every `kind=` on a send call across `src/` | resolves to a switchable key | scan passes; the only pass-through helpers are the notifier, brain alerts, the owner's manual summary and `_buy_alert_kind` (`test_p5_*`) | Pass |
| p5b | Real-money buy cannot be muted, paper can | `services/execution.py:1937-1939` | live: no kind; paper: `paper_buys` | as expected (`test_p5b_*`; #250 b4) | Pass |
| p6 | Sell, fill, exit, error, system templates carry no kind | `notifications/telegram.py:164-298` | untagged = always sent | five templates, kind `None` (`test_p6_*`) | Pass |
| p7 | Quiet hours: held vs sent, then one flush | `telegram.py:52-83`, `alert_settings.py:134-211`, `alert_policy.py:179` | 23:00: idea held, stop-loss sent; 07:01: one message; no repeat | as expected (`test_p7_*`; `test_alert_settings.py`) | Pass |
| p8 | A change is audited with who | `notifications.py:87-102` | one `alerts.settings` row naming the actor | as expected (`test_p8_*`) | Pass |
| p9 | What the screen is given | `alert_settings.py:104-125` (`as_dict`); screen `frontend/src/trademind/pages/Alerts.tsx` | five always-on types with reasons and no switch; plain words | data as expected (`test_p9_*`); the screen is tested in `frontend/src/trademind/alerts.test.tsx` ("shows the safety messages as always on, with the reason, and no switch"), not re-run here | Pass |
| p10 | Who may read or change | `notifications.py:69` (`require_owner`) | member, tester, stranger refused; nothing stored | 403, 403, 401, nothing stored (`test_p10_*`) | Pass |
| p11 | Settings per user | `db/models/alerts.py:20-31` (one row, scope `owner`) | each owner has their own | owner B sees owner A's mute (`test_gap_two_owner_accounts_*`) | **GAP** |
| f1 | A refused direct send | `telegram.py:85-107` (`_post`) | returns False | False, one log line, one attempt (`test_f1_*`; #250 e1) | Pass (log only) |
| f2 | Retried or recorded after a 429 / 5xx | `telegram.py:85-107` | a retry, or a stored record | one attempt, nothing stored (`test_gap_a_refused_direct_send_*`) | **GAP** |
| f3 | Event filter cannot silence a stop-loss | `telegram.py:48-50` (`_should_send`), `core/config.py:357` | stop-loss sent whatever the filter says | not sent when `signal` is left out (`test_gap_a_stop_loss_alert_is_sent_*`) | **GAP** |
| f4 | The default event filter covers every event the app uses | `core/config.py:357, 423` | all six events included | included (`test_f2_*`) | Pass |
| f5 | Held alerts after a failed or partial delivery | `alert_settings.py:196-211` | marked sent only after Telegram took it | first text sent and marked, second stays held, then delivered (`test_f3_*`; `test_alert_settings.py`) | Pass |
| f6 | Unreadable settings never silence an alert | `alert_settings.py:134-159` | send | send (`test_f4_*`; `test_alert_settings.py`) | Pass |
| f7 | Muted vs failed | `telegram.py:52-83` | muted = False, nothing posted | as expected (`test_f5_*`) | Pass |
| f8 | Brain alerts: recorded only when really sent, one per day | `brain/alerts/service.py:114-127` | a failed send is not recorded, so the next run finds it again | cited: `test_brain_alerts_service.py` (6 tests) | Pass |
| f9 | Email failure never breaks the request or leaks existence | `api/v1/endpoints/account_auth.py:101-103`, `services/email/senders.py:50-68` | same 201 answer, no raise | as expected (`test_f6_*`; `test_account_auth_email.py` sender tests) | Pass |
| f10 | Email failure visible to the owner | same | a record the owner can see | none (`test_gap_a_failed_email_*`) | **GAP** |
| f11 | Duplicates and rate limits | notifier posts every message it is given (`telegram.py:52-107`) | repeats stopped at the source | notifier does not dedupe (`test_f7_*`); sources dedupe: per-position flags (#250 a1/a4), brain one-per-day key, email notice once per hour (`test_account_auth_email.py::test_register_notice_is_limited_to_one_per_hour_per_address`), public email routes rate limited (`::test_public_routes_have_rate_limit_dependencies`) | Pass (by design) |
| f12 | Stop-loss send that fails is still marked sent | `services/execution.py:1574-1576` | flag only after a successful send | #250 e2 / e3 | **GAP** (cited, #250) |

## Gaps for the owner (one line each, none fixed)

- **p11:** give each owner their own alert settings (the model already says a per-user scope is planned), or state that the settings
  are deliberately shared by all owner accounts.
- **f2 / f12:** retry a refused direct send, or store it as held, and set the "alert sent" flag only after Telegram took it (needs the
  owner's approval: it touches the exit-alert path).
- **f3:** exempt the safety events from the event filter, or refuse a `TELEGRAM_NOTIFY_ON` that leaves out `signal`, `fill` or `error`.
- **f10:** write a failed email into the audit log or an admin-visible list.

## How the gap tests work

Each gap is a test that states what the code SHOULD do, marked `xfail(strict=True, raises=AssertionError)`. They fail today for the
stated reason (checked with `--runxfail`: owner B sees `['paper_buys']`; one attempt after a 429; nothing posted when `signal` is left
out; no audit row names the failed email). If a gap is fixed the strict marker turns the test red and is then removed on purpose.

## Not covered here

The real Telegram service, real email delivery, production and the owner's accounts were not touched. Per-screen rendering of the alert
bell and the settings page is covered by the frontend tests named above and was not re-run for this note. The brain's alert wording and
the sealed trial were not touched.

Re-run for this note (dev2b): the new file plus `test_alert_policy.py`, `test_alert_settings.py`, `test_account_auth_email.py`,
`test_brain_alerts_service.py` and `test_telegram_production_only.py`: **163 passed, 4 xfailed** (the four gaps).
