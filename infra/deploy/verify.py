"""Read-only post-deployment checks, run inside the API container."""

import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.session import engine

with urlopen("http://localhost:8000/api/v1/ready", timeout=5) as response:
    if response.status != 200:
        raise RuntimeError("API is not ready")
with engine.connect() as connection:
    revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    if revision != ScriptDirectory.from_config(Config("alembic.ini")).get_current_head():
        raise RuntimeError("Unexpected database revision")
    invalid = connection.execute(text(
        "SELECT count(*) FROM strategies WHERE strategy_type = 'long_term_value' "
        "AND execution_mode <> 'advisory'"
    )).scalar_one()
    if invalid:
        raise RuntimeError("Long-term advisory migration is incomplete")
directory = Path(settings.MODEL_ARTIFACT_DIR)
heartbeat = float((directory / ".scheduler_heartbeat").read_text())
if heartbeat < float(sys.argv[1]) or time.time() - heartbeat > 180:
    raise RuntimeError("Waiting for a fresh worker heartbeat")
jobs = json.loads((directory / ".scheduler_jobs.json").read_text())
required = {"signal_scan", "check_exits", "reconcile_orders", "heartbeat"}
if not required.issubset({job["id"] for job in jobs}):
    raise RuntimeError("Required scheduler jobs are missing")
print("API, migration, advisory policy, heartbeat, and scheduler verified")
