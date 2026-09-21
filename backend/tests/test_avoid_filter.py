from datetime import date, timedelta

from sqlalchemy import select

from swing_trade_ml.db.models.feeds import DailyDelivery, TradingRestriction, UpcomingEvent
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.services import avoid, market_feeds, risk

TODAY = date(2026, 9, 21)


def _event(db, symbol, kind, days_ahead, detail="Financial Results"):
    db.add(UpcomingEvent(symbol=symbol, kind=kind, event_date=TODAY + timedelta(days=days_ahead), detail=detail))
    db.flush()


def test_nothing_known_means_nothing_avoided(db_session):
    assert avoid.avoid_reason(db_session, "ABC", TODAY) is None


def test_results_within_three_days_block_entry(db_session):
    _event(db_session, "ABC", "results", 2)

    assert "results" in avoid.avoid_reason(db_session, "ABC", TODAY)


def test_results_far_away_or_already_past_do_not_block(db_session):
    _event(db_session, "FAR", "results", 10)
    _event(db_session, "PAST", "results", -1)

    assert avoid.avoid_reason(db_session, "FAR", TODAY) is None
    assert avoid.avoid_reason(db_session, "PAST", TODAY) is None


def test_a_split_soon_blocks_entry(db_session):
    _event(db_session, "ABC", "corporate_action", 1, "Face Value Split (Sub-Division) - From Rs 10 To Rs 2")

    assert "share price" in avoid.avoid_reason(db_session, "ABC", TODAY)


def test_surveillance_listing_blocks_entry_but_a_stale_list_does_not(db_session):
    db_session.add(TradingRestriction(symbol="ASM1", kind="ASM", stage="Stage I", as_of=TODAY))
    db_session.add(TradingRestriction(symbol="OLD", kind="GSM", stage="VI", as_of=TODAY - timedelta(days=30)))
    db_session.flush()

    assert "watch list" in avoid.avoid_reason(db_session, "ASM1", TODAY)
    assert avoid.avoid_reason(db_session, "OLD", TODAY) is None


def test_trade_for_trade_series_blocks_entry(db_session):
    db_session.add(DailyDelivery(symbol="TFT", series="BE", trade_date=TODAY - timedelta(days=1)))
    db_session.flush()

    assert "delivery-only" in avoid.avoid_reason(db_session, "TFT", TODAY)


def test_check_entry_refuses_a_stock_reporting_results(db_session, monkeypatch):
    instrument = Instrument(instrument_token=880001, tradingsymbol="RESULTSCO", exchange="NSE")
    db_session.add(instrument)
    db_session.flush()
    db_session.add(
        UpcomingEvent(
            symbol="RESULTSCO", kind="results", event_date=date.today(), detail="Financial Results"
        )
    )
    db_session.flush()

    decision = risk.check_entry(
        db_session, "paper", instrument.id, price=100.0, stop_loss=96.0,
        portfolio_value=1_000_000, available_cash=1_000_000,
    )

    assert decision.allowed is False
    assert decision.rule == "AVOID"


PAYLOAD_EVENTS = [
    {"symbol": "AUGMONT", "purpose": "Financial Results", "date": "21-Sep-2026"},
    {"symbol": "AUGMONT", "purpose": "Financial Results/Other business matters", "date": "21-Sep-2026"},
    {"symbol": "FUNDCO", "purpose": "Fund Raising", "date": "22-Sep-2026"},
]
PAYLOAD_ACTIONS = [
    {"symbol": "PNBGILTS", "subject": "Dividend - Rs 2 Per Share", "exDate": "21-Sep-2026"},
    {"symbol": "SPLITCO", "subject": "Face Value Split (Sub-Division) - From Rs 10/- To Rs 2/-",
     "exDate": "24-Sep-2026"},
]


def test_event_parsers_keep_only_results_and_price_resetting_actions():
    assert [e["symbol"] for e in market_feeds.parse_events(PAYLOAD_EVENTS)] == ["AUGMONT", "AUGMONT"]
    assert [a["symbol"] for a in market_feeds.parse_actions(PAYLOAD_ACTIONS)] == ["SPLITCO"]


def test_restriction_parser_reads_both_asm_lists_and_gsm():
    asm = {
        "longterm": {"data": [{"symbol": "A2ZINFRA", "asmSurvIndicator": "Stage I"}]},
        "shortterm": {"data": [{"symbol": "ABH", "asmSurvIndicator": "Stage II"}]},
    }
    gsm = [{"symbol": "AGSTRA", "gsmStage": "LXII"}]

    rows = market_feeds.parse_restrictions(asm, gsm, TODAY)

    assert {(r["symbol"], r["kind"]) for r in rows} == {
        ("A2ZINFRA", "ASM"), ("ABH", "ASM"), ("AGSTRA", "GSM"),
    }


def test_loading_events_twice_stores_each_once(db_session, monkeypatch):
    import json

    def fetch(url):
        return json.dumps(PAYLOAD_EVENTS if "event-calendar" in url else PAYLOAD_ACTIONS).encode()

    monkeypatch.setattr(market_feeds, "fetch", fetch)

    first = market_feeds.load_upcoming_events(db_session, TODAY)
    second = market_feeds.load_upcoming_events(db_session, TODAY)

    assert first == 2  # AUGMONT results (deduplicated) + SPLITCO
    assert second == 0
    assert len(list(db_session.execute(select(UpcomingEvent)).scalars())) == 2
