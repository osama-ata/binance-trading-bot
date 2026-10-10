"""Bot entry point: `python src/main.py` (settings come from .env, see .env.example)."""
import asyncio
import logging
import os
import sys
from pathlib import Path

from binance_client import BinanceClient
from brokers import BinanceBroker, PaperBroker, Store
from config import settings
from database import init_db
from engine import TradingEngine
from risk import RiskManager
from strategies import STRATEGIES

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(LOG_DIR / "bot.log")],
    )
    # The Binance SDK logs every websocket ping/subscribe on the root logger at INFO; keep only its warnings.
    for handler in logging.getLogger().handlers:
        handler.addFilter(lambda r: r.name != "root" or r.levelno >= logging.WARNING)


def build_engine() -> TradingEngine:
    log = logging.getLogger("main")
    live = settings.trading_mode == "LIVE"
    if live and settings.binance_env == "prod" and os.getenv("CONFIRM_LIVE_PROD") != "yes":
        sys.exit("Refusing to trade real money: set CONFIRM_LIVE_PROD=yes together with BINANCE_ENV=prod.")

    client = BinanceClient(
        env=settings.binance_env,
        api_key=settings.api_key if live else None,
        api_secret=settings.api_secret,
        private_key=settings.private_key,
    )
    try:
        factory = init_db()
    except Exception as e:
        sys.exit(f"Database connection failed ({e}). Start it with `docker compose up -d db`.")

    mode = f"LIVE-{settings.binance_env}" if live else "VIRTUAL"
    store = Store(factory, mode)
    if live:
        broker = BinanceBroker(store, client, fee_rate=settings.fee_rate)
    else:
        broker = PaperBroker(store, settings.paper_cash, settings.fee_rate, settings.slippage_bps, client=client)

    overrides = {"max_bars": settings.max_bars_in_trade} if settings.max_bars_in_trade else {}
    if settings.signal_tf:
        overrides["signal_tf"] = None if settings.signal_tf.lower() == "none" else settings.signal_tf
    strategy = STRATEGIES[settings.strategy](fee_rate=settings.fee_rate, **overrides)
    log.info("Starting %s | strategy=%s %s | symbols=%s | interval=%s",
             mode, strategy.name, strategy.p, settings.symbols, settings.interval)
    return TradingEngine(client, broker, strategy, RiskManager.from_settings(settings),
                         settings.symbols, settings.interval, settings.warmup_bars, settings.slippage_bps)


if __name__ == "__main__":
    setup_logging()
    try:
        asyncio.run(build_engine().run())
    except KeyboardInterrupt:
        logging.getLogger("main").info("Bot stopped by user.")
