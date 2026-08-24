"""Application settings, loaded once from the environment at import time.

Everything the app can be tuned with lives here. Nothing reads `os.environ`
directly anywhere else — that keeps the deployment surface to a single file and
makes the move to a cloud secret manager a config change rather than a code
change.
"""

from __future__ import annotations

from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# repo root — backend/src/swing_trade_ml/core/config.py -> up 4 levels
REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------------------------------------------------------------- core --
    APP_NAME: str = "Swing Trade ML"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "console"
    TIMEZONE: str = "Asia/Kolkata"

    # ----------------------------------------------------------------- api --
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: str = "http://localhost:5173"

    API_KEY: str = "change-me"
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 720

    # Self-registration. Fine to leave on for local development; turn off
    # before this is reachable from anywhere but your own machine — an open
    # signup endpoint on a system that can place real trades is a genuine
    # account-takeover surface, not just a nuisance.
    ALLOW_SIGNUP: bool = True

    # Google "Sign in with Google" — from console.cloud.google.com, an OAuth
    # 2.0 Client ID (type: Web application) with this exact redirect URI added.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URL: str = "http://localhost:8000/api/v1/auth/google/callback"
    # Where the browser lands after a successful Google login, with the JWT
    # appended as a query param for the SPA to pick up.
    FRONTEND_URL: str = "http://localhost:5173"
    # Comma-separated allow-list. Deliberately required (not "empty means
    # allow everyone") — this is a personal trading tool, not a public SaaS,
    # and Google login must never become "any Google account gets a trading
    # bot" just because the button exists.
    GOOGLE_ALLOWED_EMAILS: str = ""

    # ------------------------------------------------------------ database --
    DATABASE_URL: str = (
        "postgresql+psycopg://swingtrade:swingtrade_local_pw@localhost:5432/swing_trade_ml"
    )
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False
    DB_AUTO_MIGRATE: bool = True

    REDIS_URL: str = "redis://localhost:6379/0"

    # ------------------------------------------------------- trading mode --
    TRADING_MODE: Literal["paper", "live"] = "paper"
    ALLOW_LIVE_TRADING: bool = False

    PAPER_STARTING_CAPITAL: float = 1_000_000.0
    PAPER_SLIPPAGE_BPS: float = 5.0
    PAPER_BROKERAGE_PER_ORDER: float = 20.0
    PAPER_TAX_BPS: float = 12.0

    # ------------------------------------------------------------ zerodha --
    KITE_API_KEY: str = ""
    KITE_API_SECRET: str = ""
    KITE_REDIRECT_URL: str = "http://localhost:8000/api/v1/auth/kite/callback"

    # -------------------------------------------------------- market data --
    DEFAULT_WATCHLIST: str = "RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK"
    HISTORICAL_BACKFILL_DAYS: int = 1825
    # Market-context benchmark for relative-strength/regime features. Kite's
    # own tradingsymbol for the index — confirmed live against the instrument
    # dump (segment="INDICES", instrument_type is unhelpfully "EQ" like every
    # equity, so this is matched by exact tradingsymbol, not type/segment).
    BENCHMARK_INDEX_SYMBOL: str = "NIFTY 50"
    LIVE_CANDLE_INTERVAL: str = "15minute"
    LIVE_POLL_SECONDS: int = 60
    MARKET_OPEN_TIME: str = "09:15"
    MARKET_CLOSE_TIME: str = "15:30"

    # ----------------------------------------------------------- strategy --
    SIGNAL_SCAN_CRON_HOUR: int = 15
    SIGNAL_SCAN_CRON_MINUTE: int = 45
    ENABLE_SCHEDULER: bool = True

    # --------------------------------------------------------------- risk --
    MAX_POSITION_PCT: float = 0.10
    MAX_OPEN_POSITIONS: int = 10
    RISK_PER_TRADE_PCT: float = 0.01
    # "risk_based" (default) sizes off distance-to-stop — see
    # calculate_quantity(). "fixed_amount" instead targets a flat rupee spend
    # per position regardless of stop distance, for a deliberately small,
    # capital-light live rollout: at 1 real share per trade, Zerodha's flat
    # per-scrip DP charge on every sell (~₹18-24) plus this app's own
    # per-order cost model dominates a small stock's entire position value,
    # so results would measure fee drag, not the strategy. A small fixed
    # amount (₹5,000-10,000+) keeps costs a sane fraction of position size.
    POSITION_SIZING_MODE: Literal["risk_based", "fixed_amount"] = "risk_based"
    FIXED_POSITION_AMOUNT_INR: float = 10_000.0
    DEFAULT_STOP_LOSS_PCT: float = 0.05
    DEFAULT_TAKE_PROFIT_PCT: float = 0.15
    MAX_PORTFOLIO_DRAWDOWN_PCT: float = 0.20
    # A held position's model confidence has to fall this many percentage
    # points below what it was at entry, AND into the "weakening" zone
    # (below the midpoint of ML_MIN_CONFIDENCE and the strategy's own
    # exit_confidence), before a decay alert fires. Two conditions, not one:
    # a single day's normal probability jitter (e.g. 66% -> 63%) must never
    # trigger this — only a real decline into genuinely weaker territory.
    CONFIDENCE_DECAY_ALERT_PCT: float = 0.15

    # ----------------------------------------------------------------- ml --
    MODEL_ARTIFACT_DIR: str = "./data/models"
    ML_PREDICTION_HORIZON_DAYS: int = 5
    ML_TARGET_RETURN_PCT: float = 0.02
    ML_TRAIN_TEST_SPLIT: float = 0.2
    ML_MIN_CONFIDENCE: float = 0.60
    ML_RANDOM_SEED: int = 42

    # ------------------------------------------------------------- finance --
    # Guard against an oversized statement upload — FastAPI does not cap
    # UploadFile size on its own.
    FINANCE_MAX_UPLOAD_MB: int = 20

    # ----------------------------------------------------------- telegram --
    TELEGRAM_ENABLED: bool = False
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    TELEGRAM_NOTIFY_ON: str = "signal,order,fill,error,daily_summary,system"

    # ------------------------------------------------------------ derived --

    @field_validator("MODEL_ARTIFACT_DIR")
    @classmethod
    def _resolve_artifact_dir(cls, v: str) -> str:
        """Make relative artifact paths absolute against the current working
        directory, not REPO_ROOT.

        REPO_ROOT is computed by walking up from this file's own location,
        which only lands on the actual repo root in the editable/src install
        layout. Inside the Docker image the package is a real wheel under
        site-packages, so that walk lands somewhere under
        /usr/local/lib/python3.x instead — not writable by the non-root
        `appuser` the container runs as, and training crashed outright the
        first time this ran against real data. cwd is correct in both cases:
        it's /app in the container (where the Dockerfile already creates and
        chowns data/models) and `backend/` for a normal local run.
        """
        p = Path(v)
        return str(p if p.is_absolute() else (Path.cwd() / p).resolve())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def watchlist(self) -> list[str]:
        return [s.strip().upper() for s in self.DEFAULT_WATCHLIST.split(",") if s.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def telegram_events(self) -> set[str]:
        return {e.strip().lower() for e in self.TELEGRAM_NOTIFY_ON.split(",") if e.strip()}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def market_open(self) -> time:
        h, m = self.MARKET_OPEN_TIME.split(":")
        return time(int(h), int(m))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def market_close(self) -> time:
        h, m = self.MARKET_CLOSE_TIME.split(":")
        return time(int(h), int(m))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_live_trading(self) -> bool:
        """Real money is only at risk when BOTH latches are open.

        Requiring two independent flags means no single careless edit — or a
        stray env var in a deploy config — can flip a paper system into a live
        one. Every order path in the codebase asks this property, never
        TRADING_MODE directly.
        """
        return self.TRADING_MODE == "live" and self.ALLOW_LIVE_TRADING

    @computed_field  # type: ignore[prop-decorator]
    @property
    def model_dir(self) -> Path:
        p = Path(self.MODEL_ARTIFACT_DIR)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @computed_field  # type: ignore[prop-decorator]
    @property
    def kite_configured(self) -> bool:
        return bool(self.KITE_API_KEY and self.KITE_API_SECRET)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def google_allowed_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.GOOGLE_ALLOWED_EMAILS.split(",") if e.strip()}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def google_oauth_configured(self) -> bool:
        """Both the OAuth app credentials AND at least one allowed email must
        be set — see GOOGLE_ALLOWED_EMAILS above for why the latter is not
        optional."""
        return bool(
            self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET and self.google_allowed_emails
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
