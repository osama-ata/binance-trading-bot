"""Streamlit dashboard: `streamlit run src/dashboard.py`."""
import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import text

import research_cache
from backtester import BacktestConfig, run_backtest, summarize, walk_forward
from config import settings
from data import load_klines
from database import get_engine
from strategies import STRATEGIES, BaseStrategy

st.set_page_config(page_title="Crypto Commander", layout="wide")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
INTERVALS = ["1m", "5m", "15m", "30m", "1h", "4h"]


@st.cache_resource
def db_engine():
    return get_engine()


@st.cache_data(ttl=300, show_spinner=False)
def klines(symbol: str, interval: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    return load_klines(symbol, interval, start, end)


def query(sql: str, **params) -> pd.DataFrame:
    try:
        with db_engine().connect() as conn:
            return pd.read_sql(text(sql), conn, params=params)
    except Exception as e:
        st.error(f"Database error: {e}")
        return pd.DataFrame()


def candles(df: pd.DataFrame, trades: pd.DataFrame | None = None, title: str = "") -> go.Figure:
    fig = go.Figure(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
                                   name="price"))
    if trades is not None and not trades.empty:
        fig.add_scatter(x=trades["entry_time"], y=trades["entry_price"], mode="markers", name="entry",
                        marker=dict(symbol="triangle-up", size=11, color="#2ca02c"))
        fig.add_scatter(x=trades["exit_time"], y=trades["exit_price"], mode="markers", name="exit",
                        marker=dict(symbol="triangle-down", size=11, color="#d62728"))
    fig.update_layout(title=title, xaxis_rangeslider_visible=False, height=520, margin=dict(t=40, b=10))
    return fig


def strategy_params(strategy: str, key: str) -> dict:
    cls = STRATEGIES[strategy]
    params = {}
    defaults = {**BaseStrategy.defaults, **cls.defaults}
    cols = st.columns(4)
    for n, (name, default) in enumerate(defaults.items()):
        col = cols[n % 4]
        if default is None or isinstance(default, (bool, str)):
            text = col.text_input(name, "" if default is None else str(default), key=f"{key}-{name}",
                                  help="empty = None" if default is None or name.endswith("_tf") else None)
            params[name] = None if text.strip().lower() in ("", "none") else text.strip()
        elif isinstance(default, int):
            params[name] = col.number_input(name, value=default, step=1, key=f"{key}-{name}")
        else:
            params[name] = col.number_input(name, value=float(default), format="%.4f", key=f"{key}-{name}")
    return params


tab_live, tab_bt, tab_wf, tab_research = st.tabs(["📈 Live / Paper", "🛠️ Backtest", "🔁 Walk-forward", "🔬 Research"])

# ---------------- Live / paper monitoring ----------------
with tab_live:
    modes = query("SELECT DISTINCT mode FROM equity_snapshots")
    mode_options = modes["mode"].tolist() if not modes.empty else ["VIRTUAL"]
    c1, c2, c3 = st.columns(3)
    mode = c1.selectbox("Mode", mode_options)
    start = c2.date_input("From", dt.date.today() - dt.timedelta(days=7))
    end = c3.date_input("To", dt.date.today())
    end_excl = end + dt.timedelta(days=1)  # include the whole end day

    equity = query(
        "SELECT timestamp, equity FROM equity_snapshots WHERE mode = :m AND timestamp >= :s AND timestamp < :e "
        "ORDER BY timestamp", m=mode, s=start, e=end_excl,
    )
    closed = query(
        "SELECT symbol, strategy, entry_reason, opened_at AS entry_time, entry_price, closed_at AS exit_time, "
        "exit_price, exit_reason, qty, pnl FROM positions WHERE mode = :m AND status = 'CLOSED' "
        "AND closed_at >= :s AND closed_at < :e ORDER BY closed_at", m=mode, s=start, e=end_excl,
    )
    open_pos = query(
        "SELECT symbol, strategy, opened_at, qty, entry_price, stop, target, bars_held, entry_reason "
        "FROM positions WHERE mode = :m AND status = 'OPEN'", m=mode,
    )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Equity", f"{equity['equity'].iloc[-1]:,.2f}" if not equity.empty else "—")
    k2.metric("Realised PnL", f"{closed['pnl'].sum():,.2f}" if not closed.empty else "0.00")
    k3.metric("Trades", len(closed))
    k4.metric("Win rate", f"{(closed['pnl'] > 0).mean() * 100:.0f}%" if not closed.empty else "—")

    if not equity.empty:
        st.plotly_chart(go.Figure(go.Scatter(x=equity["timestamp"], y=equity["equity"], name="equity"))
                        .update_layout(title="Equity", height=300, margin=dict(t=40, b=10)), width="stretch")
    st.subheader("Open positions")
    st.dataframe(open_pos, width="stretch", hide_index=True)

    st.subheader("Chart")
    c1, c2 = st.columns(2)
    sym = c1.selectbox("Symbol", sorted(set(settings.symbols) | set(closed.get("symbol", pd.Series()).unique())))
    tf = c2.selectbox("Timeframe", INTERVALS, index=INTERVALS.index(settings.interval) if settings.interval in INTERVALS else 1)
    try:
        px = klines(sym, tf, start, end)
        sym_trades = closed[closed["symbol"] == sym] if not closed.empty else None
        st.plotly_chart(candles(px, sym_trades, f"{sym} {tf}"), width="stretch")
    except Exception as e:
        st.error(f"Could not load candles: {e}")
    st.subheader("Closed trades")
    st.dataframe(closed, width="stretch", hide_index=True)

# ---------------- Backtest ----------------
with tab_bt:
    c1, c2, c3, c4 = st.columns(4)
    bt_strategy = c1.selectbox("Strategy", list(STRATEGIES), key="bt-strat")
    bt_symbol = c2.selectbox("Symbol", SYMBOLS, key="bt-sym")
    bt_tf = c3.selectbox("Timeframe", INTERVALS, index=2, key="bt-tf")
    bt_start = c4.date_input("Start", dt.date.today() - dt.timedelta(days=90), key="bt-start")
    c1, c2, c3, c4 = st.columns(4)
    bt_end = c1.date_input("End", dt.date.today(), key="bt-end")
    cash = c2.number_input("Initial cash", 1_000, 10_000_000, 10_000, step=1_000)
    fee = c3.number_input("Fee per side", 0.0, 0.01, settings.fee_rate, format="%.5f",
                          help="Binance spot: 0.001 (0.075% = 0.00075 when paying fees in BNB)")
    slip = c4.number_input("Slippage (bps)", 0.0, 50.0, settings.slippage_bps)
    with st.expander("Strategy parameters"):
        params = strategy_params(bt_strategy, "bt")

    if st.button("Run backtest", type="primary"):
        with st.spinner("Loading history from data.binance.vision and simulating…"):
            try:
                df = klines(bt_symbol, bt_tf, bt_start, bt_end)
                stats, _ = run_backtest(df, bt_strategy, params, BacktestConfig(cash, fee, slip))
                m = summarize(stats)
                cols = st.columns(6)
                for n, key in enumerate(["Return [%]", "Buy & Hold [%]", "Max Drawdown [%]", "# Trades",
                                         "Profit Factor", "Avg R"]):
                    cols[n].metric(key, f"{m[key]:.2f}" if isinstance(m[key], float) else m[key])
                cols = st.columns(5)
                for n, key in enumerate(["Win Rate [%]", "Expectancy [%]", "Trades / day", "Exposure [%]", "Sharpe"]):
                    cols[n].metric(key, f"{m[key]:.2f}")
                eq = stats["_equity_curve"]["Equity"]
                st.plotly_chart(go.Figure(go.Scatter(x=eq.index, y=eq, name="equity"))
                                .update_layout(title="Equity", height=300, margin=dict(t=40, b=10)),
                                width="stretch")
                tr = stats["_trades"].rename(columns={"EntryTime": "entry_time", "ExitTime": "exit_time",
                                                      "EntryPrice": "entry_price", "ExitPrice": "exit_price"})
                st.plotly_chart(candles(df.iloc[-3000:], tr[tr["entry_time"] >= df.index[-3000:][0]],
                                        f"{bt_symbol} {bt_tf} (last 3000 bars)"), width="stretch")
                st.dataframe(tr.drop(columns=["Tag"], errors="ignore"), width="stretch")
            except Exception as e:
                st.exception(e)

# ---------------- Walk-forward ----------------
with tab_wf:
    st.caption("Optimise on a rolling training window, then trade the following unseen window with the chosen "
               "parameters. Only out-of-sample results are shown; this is the honest estimate of performance.")
    c1, c2, c3, c4 = st.columns(4)
    wf_strategy = c1.selectbox("Strategy", list(STRATEGIES), key="wf-strat")
    wf_symbol = c2.selectbox("Symbol", SYMBOLS, key="wf-sym")
    wf_tf = c3.selectbox("Timeframe", INTERVALS, index=2, key="wf-tf")
    wf_start = c4.date_input("Start", dt.date.today() - dt.timedelta(days=180), key="wf-start")
    c1, c2, c3, c4 = st.columns(4)
    train_days = c1.number_input("Train days", 7, 365, 30)
    test_days = c2.number_input("Test days", 1, 90, 7)
    min_trades = c3.number_input("Min trades in training", 1, 500, 10)
    maximize = c4.selectbox("Optimise for", ["SQN", "Sharpe Ratio", "Return [%]", "Profit Factor"])
    wf_signal_tf = st.selectbox("Signal timeframe (execution stays on the bar timeframe)",
                                ["strategy default", "bar timeframe", "15min", "1h", "4h"], key="wf-sigtf")
    st.write("Grid:", STRATEGIES[wf_strategy].param_grid)

    if st.button("Run walk-forward", type="primary"):
        with st.spinner("Running walk-forward optimisation…"):
            try:
                df = klines(wf_symbol, wf_tf, wf_start, dt.date.today())
                folds, eq = walk_forward(df, wf_strategy, int(train_days), int(test_days),
                                         cfg=BacktestConfig(10_000, settings.fee_rate, settings.slippage_bps),
                                         min_trades=int(min_trades), maximize=maximize,
                                         params={} if wf_signal_tf == "strategy default" else
                                         {"signal_tf": None if wf_signal_tf == "bar timeframe" else wf_signal_tf})
                if eq.empty:
                    st.warning("Not enough data for a single fold.")
                else:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Out-of-sample return", f"{(eq.iloc[-1] / eq.iloc[0] - 1) * 100:.2f}%")
                    c2.metric("Max drawdown", f"{((eq / eq.cummax()) - 1).min() * 100:.2f}%")
                    c3.metric("OOS trades", int(folds["test_trades"].sum()))
                    st.plotly_chart(go.Figure(go.Scatter(x=eq.index, y=eq)).update_layout(
                        title="Stitched out-of-sample equity", height=300), width="stretch")
                    st.dataframe(folds, width="stretch", hide_index=True)
            except Exception as e:
                st.exception(e)

# ---------------- Research runs ----------------
DSR_GATE, PBO_GATE = 0.95, 0.5

with tab_research:
    st.caption("Every cached walk-forward run (scripts/wf_report.py), from the `research_runs` table. Out-of-sample "
               f"only. The gate to move a strategy towards live trading is DSR > {DSR_GATE} and PBO < {PBO_GATE}. "
               "Backfill older runs with `uv run python scripts/research_db.py`.")
    runs = query("SELECT * FROM research_runs ORDER BY created_at DESC")
    if runs.empty:
        st.info("No research runs in the database yet.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        f_strat = c1.multiselect("Strategy", sorted(runs["strategy"].dropna().unique()))
        f_sym = c2.multiselect("Symbol", sorted(runs["symbol"].dropna().unique()))
        f_code = c3.multiselect("Code fingerprint", list(dict.fromkeys(runs["code"].dropna())),
                                help="Results from different code versions are not comparable one to one")
        only_pass = c4.toggle("Only runs that pass the gate")
        view = runs
        for col, sel in (("strategy", f_strat), ("symbol", f_sym), ("code", f_code)):
            if sel:
                view = view[view[col].isin(sel)]
        view = view.assign(passes=(view["dsr"] > DSR_GATE) & (view["pbo"] < PBO_GATE),
                           variant=view["params"].map(lambda p: ", ".join(f"{k}={v}" for k, v in (p or {}).items()))
                           + view["risk"].map(lambda r: "".join(f" | {k}={v}" for k, v in (r or {}).items())))
        if only_pass:
            view = view[view["passes"]]

        k1, k2, k3 = st.columns(3)
        k1.metric("Runs", len(view))
        k2.metric("Pass the gate", int(view["passes"].sum()))
        k3.metric("Best DSR", f"{view['dsr'].max():.2f}" if view["dsr"].notna().any() else "—")

        plot = view.dropna(subset=["dsr", "pbo"])
        if not plot.empty:
            fig = go.Figure()
            fig.add_shape(type="rect", x0=DSR_GATE, x1=1.0, y0=0, y1=PBO_GATE, fillcolor="rgba(44,160,44,0.12)",
                          line_width=0)
            fig.add_scatter(x=plot["dsr"], y=plot["pbo"], mode="markers",
                            marker=dict(size=9, color=plot["oos_return_pct"], colorscale="RdYlGn", cmid=0,
                                        colorbar=dict(title="OOS %")),
                            text=plot["strategy"] + " " + plot["symbol"] + " " + plot["interval"] + "/"
                            + plot["signal_tf"].fillna("") + "<br>" + plot["variant"],
                            hovertemplate="%{text}<br>DSR %{x:.2f}, PBO %{y:.2f}<extra></extra>")
            fig.update_layout(title="Deflated Sharpe vs PBO (green = passes the gate)", height=380,
                              xaxis=dict(title="DSR", range=[-0.02, 1.02]),
                              yaxis=dict(title="PBO", range=[-0.02, 1.02]), margin=dict(t=40, b=10))
            st.plotly_chart(fig, width="stretch")

        cols = ["created_at", "strategy", "symbol", "interval", "signal_tf", "variant", "start", "end", "train_days",
                "test_days", "oos_return_pct", "buy_hold_pct", "oos_max_dd_pct", "oos_trades", "folds",
                "oos_sharpe_ann", "buy_hold_sharpe_ann", "dsr", "pbo", "passes", "key"]
        st.dataframe(view[cols], width="stretch", hide_index=True)

        key = st.selectbox("Run details", view["key"],
                           format_func=lambda k: " · ".join(str(view.set_index("key").loc[k, c]) for c in
                                                            ("strategy", "symbol", "interval", "signal_tf", "variant")))
        if key:
            run = research_cache.load(key)
            if run is None:
                st.warning("Run files are not on this machine (data/research/ is not in git).")
            else:
                if "equity" in run:
                    eq = run["equity"]
                    st.plotly_chart(go.Figure(go.Scatter(x=eq.index, y=eq)).update_layout(
                        title="Stitched out-of-sample equity", height=300, margin=dict(t=40, b=10)), width="stretch")
                if "folds" in run:
                    st.dataframe(run["folds"], width="stretch", hide_index=True)
