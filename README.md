# Binance Trading Bot

A Python-based crypto trading bot skeleton featuring a dashboard, backtester, and virtual/live trading modes.

## Features
- **Virtual & Live Modes**: Test safely with virtual paper trading before going live.
- **Dashboard**: Interactive Streamlit dashboard for monitoring and backtesting.
- **Backtester**: Test strategies against historical data using `backtesting.py`.
- **Database**: PostgreSQL integration for logging trades.

## Setup

### Prerequisites
- Python 3.11+
- Docker & Docker Compose (optional, for DB)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repo_url>
   cd binance-trading-bot
   ```

2. **Install Dependencies**
   It is recommended to use a virtual environment.
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```
   *Note: This installs dependencies defined in `pyproject.toml`.*

3. **Environment Variables**
   Create a `.env` file in the root directory.
   **Important**: For local execution, set `POSTGRES_HOST=localhost`.
   ```ini
   TRADING_MODE=VIRTUAL
   BINANCE_API_KEY=your_api_key
   BINANCE_SECRET=your_secret
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=postgres
   POSTGRES_DB=tradingbot
   POSTGRES_HOST=localhost
   ```

4. **Database Setup**
   Start the PostgreSQL database using Docker:
   ```bash
   docker compose up -d db
   ```
   *Note: We only start the `db` service to allow running python scripts locally.*

## Usage

### 1. Run the Trading Bot
The bot will run in the terminal, executing trades in the loop.
```bash
python src/main.py
```
Output should show: `🚀 Starting Engine in VIRTUAL mode`

### 2. Run the Dashboard
Launch the Streamlit dashboard to view trade history and backtest strategies.
```bash
streamlit run src/dashboard.py
```
Access at: `http://localhost:8501`

## Structure
- `src/main.py`: Entry point for the trading bot loop.
- `src/exchange_wrapper.py`: Wrapper around CCXT for Binance interactions.
- `src/dashboard.py`: Streamlit-based user interface.
- `src/backtester.py`: Backtesting logic wrapper.
- `src/database.py`: Database connection and models.
