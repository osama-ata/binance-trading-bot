# Binance Trading Bot

A Binance spot day-trading bot built on **Binance's official Python SDK** (`binance-sdk-spot`). Backtests and live trading run the **same strategy code**, behind a shared risk manager, with a paper broker and a live broker that both persist state to Postgres.

> This is research and engineering tooling, not financial advice. Validate on the paper broker and on Binance Demo or Testnet before risking real funds.

## Features
- **Official Binance SDK.** Market data comes over REST and WebSocket streams. Live orders are market entries followed immediately by an exchange-side **OCO** (LIMIT_MAKER target plus STOP_LOSS), so positions stay protected if the bot dies. `BINANCE_ENV` switches between `prod`, `testnet` and `demo` (Binance Demo Trading: real market, fake funds).
- **Event-driven engine.** It reacts to *closed* candles from the kline websocket, never to partially formed bars.
- **Strategies** (long-only, in `src/strategies/`):
  - `ema_pullback`: pullback in an uptrend, with a higher-timeframe trend filter and ADX
  - `vwap_reversion`: mean reversion to the daily VWAP in a low-ADX range
  - `squeeze_breakout`: Bollinger-inside-Keltner squeeze, then a volume breakout
  - `opening_range`: opening-range breakout around a session open (default 13:30 UTC)
- **Risk management** (`src/risk.py`), the same in backtest and live:
  - Fixed-fraction position sizing from the stop distance, capped by notional
  - Break-even stop and time stop
  - Daily loss kill switch and maximum trades per day
  - Maximum open positions and a cooldown after a losing streak
- **Backtesting.**
  - Bulk history from `data.binance.vision`, cached as Parquet, with the REST API filling the last day.
  - Realistic costs: 0.1% fee per side plus slippage.
  - Fractional crypto sizing.
  - Day-trading metrics: average R, profit factor, expectancy and trades per day.
  - **Walk-forward optimisation** that reports out-of-sample results only.
- **Dashboard** (Streamlit) with three tabs:
  - Live/paper monitoring: equity, open positions, closed trades, and real candles with entry/exit markers
  - Backtester
  - Walk-forward

## Setup
Requires Python 3.11+, [uv](https://docs.astral.sh/uv/) and Docker (for Postgres).

```bash
uv sync
```

```bash
cp .env.example .env
```

```bash
docker compose up -d db
```

Edit `.env`. The defaults run the paper broker on live Binance market data, so no API keys are needed for `TRADING_MODE=VIRTUAL`.

### API keys for LIVE mode
- **Demo trading** (recommended first): log in to Binance → Demo Trading → API Management. Set `BINANCE_ENV=demo`.
- **Testnet**: create keys at https://testnet.binance.vision and set `BINANCE_ENV=testnet`.
- **Production**: set `BINANCE_ENV=prod` *and* `CONFIRM_LIVE_PROD=yes`. The bot refuses to start otherwise. Restrict the key to spot trading with no withdrawals, and allowlist your IP.
- Binance recommends Ed25519 keys. Set `BINANCE_PRIVATE_KEY` to the PEM path instead of `BINANCE_SECRET`.

## Usage
Run the bot:

```bash
uv run python src/main.py
```

Logs go to the console and to `logs/bot.log`. Positions and the paper cash balance survive restarts.

Run the dashboard (http://localhost:8501):

```bash
uv run streamlit run src/dashboard.py
```

Run the tests:

```bash
uv run pytest
```

Or run everything in Docker:

```bash
docker compose up -d
```

## Day-trading notes from the backtests
- **Fees dominate on low timeframes.** On BTCUSDT 5m, a 1.5×ATR stop is roughly 0.3% of price, while a market round trip costs 0.2% in fees plus slippage. That is about 0.7R lost per trade before any edge. Prefer 15m or above, maker (limit) entries, and the BNB fee discount (`FEE_RATE=0.00075`).
- **Judge strategies on walk-forward out-of-sample results**, not on a single optimised backtest. None of the bundled strategies is profitable out of sample on recent BTC data with default settings. They are starting points for research.

## Structure
| File | Purpose |
|---|---|
| `src/main.py` | Entry point: wires config, client, broker, strategy and risk into the engine |
| `src/engine.py` | Websocket-driven loop: one evaluation per closed candle per symbol |
| `src/binance_client.py` | Adapter over the official `binance-sdk-spot` (klines, streams, orders, OCO, exchange filters) |
| `src/brokers.py` | `PaperBroker` (simulated fills) and `BinanceBroker` (real orders), plus DB `Store` |
| `src/strategies/` | `BaseStrategy` interface and strategies |
| `src/indicators.py` | Causal indicators (EMA, RSI, ATR, ADX, Bollinger, Keltner, session VWAP, higher-timeframe join) |
| `src/risk.py` | Position sizing, stop management and circuit breakers |
| `src/backtester.py` | backtesting.py adapter, metrics and walk-forward |
| `src/data.py` | Historical klines from data.binance.vision plus REST, with a Parquet cache in `data/klines/` |
| `src/database.py` | SQLAlchemy models (trades, positions, equity snapshots) and a migration helper |
| `src/dashboard.py` | Streamlit UI |
| `src/config.py` | Typed settings from `.env` |
