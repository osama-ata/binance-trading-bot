"""Typed settings loaded once from environment variables (.env)."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _list(name: str, default: str) -> list[str]:
    return [s.strip().upper() for s in os.getenv(name, default).split(",") if s.strip()]


@dataclass(frozen=True)
class Settings:
    # VIRTUAL = paper broker on live market data, LIVE = real orders on BINANCE_ENV
    trading_mode: str = os.getenv("TRADING_MODE", "VIRTUAL").strip().upper()
    # prod | testnet | demo  (only used for LIVE orders; market data always comes from prod)
    binance_env: str = os.getenv("BINANCE_ENV", "testnet").strip().lower()
    api_key: str | None = os.getenv("BINANCE_API_KEY") or None
    api_secret: str | None = os.getenv("BINANCE_SECRET") or None
    # Optional Ed25519 private key (path or PEM). Recommended by Binance; used instead of HMAC secret.
    private_key: str | None = os.getenv("BINANCE_PRIVATE_KEY") or None

    symbols: list[str] = field(default_factory=lambda: _list("SYMBOLS", "BTCUSDT,ETHUSDT"))
    interval: str = os.getenv("INTERVAL", "5m").strip()
    strategy: str = os.getenv("STRATEGY", "ema_pullback").strip()
    warmup_bars: int = int(os.getenv("WARMUP_BARS", "500"))

    # Costs (Binance spot default tier: 0.1% maker/taker)
    fee_rate: float = float(os.getenv("FEE_RATE", "0.001"))
    slippage_bps: float = float(os.getenv("SLIPPAGE_BPS", "2"))

    # Risk
    paper_cash: float = float(os.getenv("PAPER_CASH", "10000"))
    risk_per_trade: float = float(os.getenv("RISK_PER_TRADE", "0.005"))
    max_position_pct: float = float(os.getenv("MAX_POSITION_PCT", "0.25"))
    daily_loss_limit: float = float(os.getenv("DAILY_LOSS_LIMIT", "0.02"))
    max_trades_per_day: int = int(os.getenv("MAX_TRADES_PER_DAY", "10"))
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "2"))
    loss_streak_cooldown: int = int(os.getenv("LOSS_STREAK_COOLDOWN", "3"))
    cooldown_bars: int = int(os.getenv("COOLDOWN_BARS", "12"))
    # Time stop in bars; empty = use the strategy's own default
    max_bars_in_trade: int | None = int(os.environ["MAX_BARS_IN_TRADE"]) if os.getenv("MAX_BARS_IN_TRADE") else None

    # Database
    pg_user: str = os.getenv("POSTGRES_USER", "postgres")
    pg_password: str = os.getenv("POSTGRES_PASSWORD", "postgres")
    pg_db: str = os.getenv("POSTGRES_DB", "tradingbot")
    pg_host: str = os.getenv("POSTGRES_HOST", "localhost")
    pg_port: int = int(os.getenv("POSTGRES_PORT", "5432"))

    @property
    def database_url(self) -> str:
        return os.getenv(
            "DATABASE_URL",
            f"postgresql://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_db}",
        )


settings = Settings()
