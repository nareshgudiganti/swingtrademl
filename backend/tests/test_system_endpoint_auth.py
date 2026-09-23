"""Which system endpoints are public.

/health and /ready are liveness and readiness probes — an orchestrator calls
them with no credentials, so they must stay open. /status and /refresh-data
must not: the first is an inventory of the account (portfolio size, job
schedule, broker connection), and the second fires the ingest jobs.
"""

from __future__ import annotations

HEADERS = {"X-API-Key": "test-api-key"}


def test_health_and_ready_stay_public(client):
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/ready").status_code == 200


def test_status_requires_auth(client):
    assert client.get("/api/v1/status").status_code in (401, 403)


def test_refresh_data_requires_auth(client):
    assert client.post("/api/v1/refresh-data").status_code in (401, 403)


def test_status_still_served_with_credentials(client):
    resp = client.get("/api/v1/status", headers=HEADERS)
    assert resp.status_code == 200
    assert "trading_mode" in resp.json()
