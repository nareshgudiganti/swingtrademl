"""brain_route_access — TradeMind GET vs owner console."""

from swing_trade_ml.core.plans import brain_route_access


def test_brain_consumer_gets():
    assert brain_route_access("GET", "/brain/runs/latest") == "trademind"
    assert brain_route_access("GET", "/brain/health") == "trademind"
    assert brain_route_access("GET", "/brain/why/RELIANCE") == "trademind"
    assert brain_route_access("GET", "/brain/runs/abc-123") == "trademind"


def test_brain_owner_only():
    assert brain_route_access("GET", "/brain/modules") == "owner"
    assert brain_route_access("GET", "/brain/runs/abc/trace") == "owner"
    assert brain_route_access("POST", "/brain/runs") == "owner"
    assert brain_route_access("GET", "/brain/stage") == "owner"
