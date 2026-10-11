# TODO — Research-driven improvement backlog

> **Handoff document.** This was written on 2026-10-10 after a deep web search of open-source trading bots, backtesting tools, Binance API changes and the published evidence on intraday crypto strategies. It is meant for the next agent or developer working on this repo.
>
> Every item gives the **problem** (with file:line references to the code as of commit `1148706`), **what to do**, **acceptance criteria** and **sources**. Things that could not be verified are marked **[UNVERIFIED]**.
> State at the time of writing: branch `main`, `uv run pytest -q`: 32 passed.
>
> **Progress log:** Phase 1 = sections 1, 5.1, 5.4, 4.1, 4.2 (DSR/PBO) and the `backtesting>=0.6.6` bump, pushed stage by stage. Stages 1–6 done (all 20 final runs, plus the 5m-exec / 1h-signal comparison, finished on the Mac Studio 2026-10-11). Research runs are cached in `data/research/` and tables are committed in `reports/`. **Gate verdict: FAIL** (see section 1, "Phase 1 results").
>
> **Handoff (2026-10-11): Phase 1 finished on the Mac Studio.** Work continues there (`~/coding/binance-trading-bot`, 20 cores, use `--jobs 16`).
> - The missing `donchian_ensemble` ETHUSDT 15m run and the 5m-exec / 1h-signal comparison (`reports/phase1/final_5m_exec_1h_signals.md`) are done. Neither changes the verdict (still **FAIL**).
> - The Docker stack runs again: the Dockerfile now installs from `uv.lock` (`pip install .` failed with no build backend and no README in the build context). The compose db's host port is `${POSTGRES_PORT:-5432}`; on the Studio, 5432 belongs to another project, so `.env` sets `POSTGRES_PORT=5433`.
> - **Phase 1b (approved 2026-10-11), in progress:** (1) longer history, (2) Donchian on 4h/1d signals with vol-targeted sizing, (3) opening_range on more symbols and longer history, (4) regime and time-of-day filters, (5) a Postgres `research_runs` table plus a dashboard Research tab. See "Phase 1b" under section 1.

---

## 0. Context for whoever picks this up

### What the bot is

A Binance **spot**, **long-only**, intraday bot, Python 3.11, managed with `uv`. The default interval is 5m and the default symbols are BTCUSDT and ETHUSDT.

| File | Role |
|---|---|
| `src/strategies/base.py` | `BaseStrategy`: `indicators(df)`, `entry(row, prev)`, `stop_for`, `target_for`, `exit(row)`. Returns a `Signal(entry, stop, target, reason)`. `prepare()` builds a causal indicator frame. |
| `src/strategies/{ema_pullback,vwap_reversion,squeeze_breakout,opening_range}.py` | The 4 strategies. |
| `src/indicators.py` | Hand-written pandas indicators: ema, sma, rsi, atr, adx, bollinger, keltner, `session_vwap`, `resample_ohlcv`, `higher_tf` (merges a higher timeframe without look-ahead). |
| `src/risk.py` | `position_size` (fixed-fractional, capped by `max_position_pct`), `Position`, `updated_stop` (break-even), `bar_exit` (stop wins if both stop and target are hit in one bar), `RiskManager` (daily loss halt, max trades/day, max open positions, loss-streak cooldown). |
| `src/backtester.py` | backtesting.py `FractionalBacktest` adapter, `run_backtest`, `summarize`, `walk_forward` (rolling grid search maximizing SQN, stitches the out-of-sample equity curves). |
| `src/engine.py` | `TradingEngine`: runs one evaluation per **closed** kline per symbol, fed by the websocket. |
| `src/brokers.py` | `Store` (Postgres persistence), `PaperBroker`, `BinanceBroker` (MARKET entry, then OCO with a LIMIT_MAKER take-profit and a STOP_LOSS). |
| `src/binance_client.py` | Thin wrapper over the official `binance-sdk-spot` (v13.1.0). Symbol filters use `Decimal` rounding. |
| `src/data.py` | Downloads data.binance.vision monthly/daily zips, caches them as parquet under `data/klines/`, and fills the not-yet-archived tail from REST. |
| `src/database.py` | SQLAlchemy models `trades`, `positions`, `equity_snapshots`. |
| `src/main.py` | Entry point. `TRADING_MODE=VIRTUAL\|LIVE`, `BINANCE_ENV=prod\|testnet\|demo`. `CONFIRM_LIVE_PROD=yes` is required for prod. |
| `src/dashboard.py` | Streamlit dashboard. |
| `tests/` | pytest suite on a synthetic OHLCV fixture (`tests/conftest.py`). |

### Strategic conclusion from the research

- **Do not migrate to a framework.**
  - Freqtrade (GPL-3.0) is the best source of ideas.
  - Hummingbot (Apache-2.0) has the closest exit model to ours.
  - NautilusTrader (LGPL-3.0) is the reference for backtest/live parity and reconciliation, but it needs Python ≥3.12 (v1) or ≥3.13 (v2 is still an RC), so it is not usable on 3.11.
  - Jesse (MIT core) sells live trading as a paid closed plugin.
  - Borrow ideas and re-implement them.
- **Licenses (important when copying code):**
  - Copy only from **MIT, Apache-2.0, BSD or Unlicense** sources, keeping attribution: Hummingbot, Jesse core, LEAN, skfolio, arch (NCSA), TA-Lib (BSD-2), talipp (MIT), quantstats (Apache-2.0), Passivbot (Unlicense).
  - Do **not** copy code from **GPL/AGPL** projects: Freqtrade, NostalgiaForInfinity, freqtrade-strategies, OctoBot, Lumibot, backtrader (GPL); backtesting.py, cryptofeed, pypbo (AGPL). Re-implement their ideas instead.
  - **Our runtime dependency `backtesting` is AGPL-3.0.** That is fine for private use. If the bot is ever distributed or offered as a network service, the combined source must be released under AGPL. (Not legal advice.)
  - vectorbt and PyBroker are Apache-2.0 **plus Commons Clause**, which is not OSI-free.
  - mlfinlab is "all rights reserved", so avoid it.

### Suggested execution order

1. **P0-A:** fees: stops, targets, break-even (section 1). This is a definite, measured money-loser.
2. **P0-B:** backtest-validity tests: look-ahead and warm-up (section 4.1).
3. **P0-C:** live engine hardening (section 2) before any real-money run.
4. **P1:** risk-layer upgrades (section 3).
5. **P1:** overfitting statistics on walk-forward (section 4.2–4.4).
6. **P2:** strategy filters and timeframe changes (section 5).
7. **P2:** ops, observability and library hygiene (sections 6–7).

---

## 1. P0-A: the fee hurdle (measured, highest impact)

### Finding

A research agent pulled ~31 days of public Binance klines (about 2026-09-09 → 2026-10-10):

| | BTCUSDT | ETHUSDT |
|---|---|---|
| 5m ATR14, median % of price | **0.11%** (p25 0.07, p75 0.15) | 0.15% |
| 15m median true range | 0.17% | 0.21% |
| 1h median true range | 0.40% | 0.54% |
| 5m true range by hour | peak **13:00–15:00 UTC** (0.21–0.24%), trough 20:00–07:00 UTC (~0.09%) | similar |
| BTC/ETH return correlation | **0.865** at both 5m and 1h | |
| BTC 5m lag-1 autocorrelation | −0.011 (≈ 0) | |

Fees: Binance spot VIP0 charges **0.10% maker and 0.10% taker**, so a round trip is 0.20%. Paying fees in BNB gives 25% off (0.075% per side, needs a BNB balance). Sources: [Binance fee schedule](https://www.binance.com/en/fee/schedule), [secondary summary](https://support.binance.us/en/articles/9843536-binance-us-launches-trading-fee-discount-and-vip-program-with-bnb).

Consequences, which I confirmed against the code:

- `BaseStrategy.stop_for` (`src/strategies/base.py:91`) puts the stop at `stop_atr × ATR(5m)`. At 1.5 × 0.11% ≈ **0.17%**, the stop is smaller than the 0.20% round-trip fee. **Fees ≈ 1.2R per trade.**
- Break-even win rate with an `rr`:1 target: `p > (1 + c) / (rr + 1)`, where c is the cost in R. At rr = 2 and c = 1.2 that means **p > 73%**. At c = 0.25 it would be p > 42%.
- `position_size` (`src/risk.py:9`): risking 0.5% of equity with a 0.17% stop gives a notional of about 290% of equity, which `max_position_pct = 0.25` clips. **Effective risk ≈ 0.04% of equity per trade, while fees ≈ 0.05% of equity per trade.** The configured `RISK_PER_TRADE` is therefore meaningless at these stop distances.
- Break-even moves the stop to the exact entry price: `src/risk.py:39-43` (live and paper) and `src/backtester.py:59` (`trade.sl = trade.entry_price`). A "break-even" exit still **loses the fees on both sides**.
- The literature agrees. 5m BTC technical-rule profits are unstable and fade after costs ([EUR thesis, 3,312 rules](https://thesis.eur.nl/pub/41546/Bakker.pdf)). Daily-rule profits survive because the break-even costs are much higher there ([Hudson & Urquhart, Annals of OR](https://link.springer.com/article/10.1007/s10479-019-03357-1)).
- Maker-only entries **do not lower the fee rate at VIP0** (maker = taker). They only save spread and slippage, and they bring adverse selection.
  - **[UNVERIFIED]** BTC/FDUSD and ETH/FDUSD reportedly have 0% maker fees since 2026-01-29 ([CoinTurk](https://en.coin-turk.com/?p=211215)). Check per symbol with `GET /api/v3/account/commission` before relying on this. FDUSD also had a depeg scare in 2025.

### Tasks

- [x] **1.1 Fee-aware minimum stop distance.** *(done: `min_stop_fee_mult=4.0` in `BaseStrategy.defaults`; strategies take `fee_rate=` in the constructor, set from `settings.fee_rate` in `main.py` and from `BacktestConfig.commission` in the backtest adapter. Rejections are counted in `strategy.rejected`.)* Add a parameter to `BaseStrategy.defaults`, e.g. `min_stop_fee_mult: 4.0`. In `entry_signal` (`src/strategies/base.py:74`), reject the signal when `(entry - stop) / entry < min_stop_fee_mult × 2 × fee_rate`.
  - Plumb `fee_rate` in. Strategies don't know it today. Options: pass it via `prepare()` or a constructor kwarg, or have the backtester and engine set `strategy.fee_rate` from `settings.fee_rate` / `BacktestConfig.commission`.
- [x] **1.2 Minimum target distance.** *(done: `min_target_fee_mult=5.0`; `VwapReversion.min_reward_pct` removed in favour of it.)* Reject the signal when `(target - entry) / entry < min_target_fee_mult × 2 × fee_rate` (default about 5). `VwapReversion` already has `min_reward_pct = 0.004` (`src/strategies/vwap_reversion.py`). Generalize that into the base class.
- [x] **1.3 ATR from a higher timeframe for stops.** *(done: `atr_tf="1h"` default; `prepare()` writes `atr` (stop ATR, from `atr_tf`) and `atr_base` (signal-timeframe ATR). `warmup_bars(bar)` now covers the HTF ATR; subclasses override `indicator_warmup(bar)` instead. `stop_atr` defaults/grids moved to 2.0–3.0 × 1h ATR.)* Add an `atr_tf` param to the base (default `"15m"` or `"1h"`). In `prepare()` compute `ta.higher_tf(df, atr_tf, lambda h: ta.atr(h, n))` and use it in `stop_for`. Keep 5m for entry timing.
  - Re-tune `stop_atr` grids, since the values will be about 2–4× larger in price terms.
  - `warmup_bars` must grow to cover `atr_n` higher-timeframe bars.
- [x] **1.4 Fee-adjusted break-even.** *(done: `risk.breakeven_level(entry, fee, slippage, tick) = entry·(1+f)/((1−f)(1−s)) + tick`; `risk.breakeven_stop()` is used by both `updated_stop` (engine/brokers) and the backtest adapter. If the new stop is already above the bar close, the engine exits at market (reason `breakeven`) instead of placing a stop Binance would reject.)* Change `updated_stop` (`src/risk.py:39`) to move the stop to `entry × (1 + 2 × fee_rate) + one tick`, not `entry`. Apply the same to `src/backtester.py:59`. Keep both in sync; ideally the backtester calls `risk.updated_stop`.
- [x] **1.5 Make sizing honest.** *(done: `summarize()` adds `Effective risk [%]` and `Cap-bound trades [%]`; the engine logs when `MAX_POSITION_PCT` caps a position. Finding: with ≥0.8% stops the 25% notional cap still binds on ~95–100% of trades, so effective risk ≈ 0.28% of equity vs the 0.5% target.)* Once 1.3 lands, check how often the `max_position_pct` cap binds. Either log a warning or add a metric "effective risk % per trade" to `summarize()` (`src/backtester.py:129`).
- [x] **1.6 Report costs in R.** *(done: `Fees [R]` and `Gross Avg R` in `summarize()`.)* In `summarize()`, add `Fees [R]` (mean fee per trade divided by initial risk) and `Gross Avg R` next to the net `Avg R`.
- [x] **1.7 Low-volatility skip filter.** *(done as a generic gate: `min_atr_pct` (default 0 = off) on signal-timeframe ATR%; the target-distance gate (1.2) already covers "expected move below the fee hurdle".)* No entries when 5m ATR% is below a threshold (BTC ~0.08%, tune per symbol), or when the expected move (target distance) is below the fee hurdle. This can live in the base class as a generic gate.
- [ ] **1.8 Optional: BNB fee payment.** *(not done; optional.)* If enabled, set `FEE_RATE=0.00075` and keep a BNB balance. `BinanceBroker._fee_in_quote` (`src/brokers.py:194`) currently *estimates* BNB-paid fees as `qty × price × fee_rate`. Make it exact using the BNB price, or `myTrades`.

**Also fixed while doing this (found during the stage):**
- The backtester charged slippage twice: `spread=2×slippage_bps` per side, while backtesting.py already applies `spread` on every fill. It is now `slippage_bps` per side, matching the PaperBroker.
- `_Adapter.next` could submit an order whose target sat below the spread-adjusted fill price, which makes backtesting.py raise `Long orders require: SL < LIMIT < TP` and kills a whole walk-forward. Such signals are now skipped.
- `scripts/wf_report.py` added: walk-forward for every strategy × symbol × interval, printed as a Markdown table.

**Single-backtest check, BTCUSDT 5m, 2026-04-01 → 2026-10-09, default params (after the change):**

| Strategy | Trades | Win % | Avg R (net) | Gross Avg R | Fees [R] | Effective risk % | Gate rejections |
|---|---|---|---|---|---|---|---|
| ema_pullback | 12 | 25.0 | −0.37 | −0.19 | 0.19 | 0.27 | stop 2 |
| vwap_reversion | 0 | – | – | – | – | – | target 5, stop 1 |
| squeeze_breakout | 124 | 35.5 | −0.24 | −0.07 | 0.17 | 0.31 | stop 36 |
| opening_range | 53 | 39.6 | −0.35 | −0.16 | 0.19 | 0.28 | stop 82 |

Fees fell from ≈1.2R to ≈0.18R per trade, as predicted. But **gross** Avg R is negative for every strategy: the entry signals have no edge even before costs, so the fee fix alone cannot make them profitable.

**Acceptance:**
- New tests show a signal is rejected when the stop is narrower than 4 × round-trip fees.
- A break-even exit has PnL ≥ 0 after fees in both the backtest and the PaperBroker.
- `summarize()` shows the fee and effective-risk metrics.
- Re-run the walk-forward for all 4 strategies and record the before/after in this file. *(done; see "Phase 1 results" below and `reports/phase1/`)*

**Phase 1 results: before/after walk-forward** (2026-04-01 → 2026-10-09, train 30d / test 7d, out-of-sample only; full tables in `reports/phase1/baseline.md`, `after_stage1.md`, `final_bars.md` and `final_5m_exec_1h_signals.md`):

| Strategy · Symbol · Bars | Before Phase 1: OOS % (trades) | After Phase 1: OOS % (trades) | After: DSR / PBO |
|---|---|---|---|
| ema_pullback · BTC · 5m | −1.48 (15) | −1.03 (12) | 0.00 / 0.23 |
| vwap_reversion · BTC · 5m | −0.09 (1) | 0.00 (0) | – / 0.80 |
| squeeze_breakout · BTC · 5m | −3.21 (68) | −5.81 (96) | 0.00 / 0.06 |
| opening_range · BTC · 5m | −6.60 (104) | −2.69 (30) | 0.00 / 0.61 |
| ema_pullback · ETH · 5m | −0.98 (25) | −1.93 (26) | 0.00 / 0.35 |
| squeeze_breakout · ETH · 5m | −10.18 (180) | −12.50 (191) | 0.00 / 0.59 |
| opening_range · ETH · 5m | −0.42 (93) | **+0.96** (44) | 0.45 / 0.25 |
| squeeze_breakout · BTC · 15m | −4.09 (75) | −7.39 (64) | 0.00 / 0.22 |
| opening_range · BTC · 15m | −4.96 (92) | −2.30 (33) | 0.01 / 0.52 |
| squeeze_breakout · ETH · 15m | −5.60 (94) | −5.43 (78) | 0.02 / 0.88 |
| opening_range · ETH · 15m | −3.71 (97) | −1.56 (47) | 0.05 / 0.30 |
| donchian_ensemble · BTC · 5m exec / 1h signals | (new) | +0.24 (16) | 0.05 / 0.69 |
| donchian_ensemble · BTC · 15m exec / 1h signals | (new) | +0.36 (16) | 0.06 / 0.79 |
| donchian_ensemble · ETH · 5m exec / 1h signals | (new) | −0.98 (15) | 0.07 / 0.61 |
| donchian_ensemble · ETH · 15m exec / 1h signals | (new) | −0.94 (15) | 0.06 / 0.54 |

Buy & hold over the same windows was +4% to +35%. Caveats:
- The baseline charged slippage twice (4 bps/side vs 2), so it is slightly pessimistic.
- `vwap_reversion` now never trades: its VWAP targets are too close to clear the fee hurdle.
- The opening-range rows changed for two reasons: the fee gates and the New York session time.

**5m execution with 1h signals** for the other strategies (`final_5m_exec_1h_signals.md`; compare with the 5m/5m rows above):

| Strategy · Symbol | 5m signals: OOS % (trades) | 1h signals: OOS % (trades) | 1h: DSR / PBO |
|---|---|---|---|
| ema_pullback · BTC | −1.03 (12) | 0.00 (0) | – / 0.49 |
| ema_pullback · ETH | −1.93 (26) | −0.07 (2) | 0.00 / 0.49 |
| vwap_reversion · BTC | 0.00 (0) | 0.00 (0) | – / 0.00 |
| vwap_reversion · ETH | 0.00 (0) | 0.00 (0) | – / 0.00 |
| squeeze_breakout · BTC | −5.81 (96) | −1.14 (21) | 0.01 / 0.84 |
| squeeze_breakout · ETH | −12.50 (191) | −0.14 (28) | 0.22 / 0.80 |

Slower signals cut trade counts by 4–7× and most of the fee bleed, but nothing turns positive. The ema_pullback and vwap_reversion rules almost never fire on 1h. squeeze_breakout's PBO above 0.8 means the in-sample parameter choice is mostly noise.

**Gate verdict (Phase 1 → Phase 2): FAIL.** No strategy/symbol/timeframe reaches DSR > 0.95 with PBO < 0.5 (all 20 final runs plus the 6 1h-signal runs). The best is opening_range on ETH 5m: +0.96% OOS, DSR 0.45, PBO 0.25, so promising but not significant. Per the plan, **do not start Phase 2 (live hardening)**. Keep researching: Donchian/trend on slower bars (4h/1d signals), regime filters (5.5), and opening_range on more symbols and longer history.

### Phase 1b: research to find something that passes the gate (same gate: DSR > 0.95 and PBO < 0.5)

- [x] **Stage 1: longer history.** Downloaded and cached (data.binance.vision):
  - 1h BTCUSDT/ETHUSDT 2020-01-01 → 2026-10-09: 59,345 bars each. 15 gaps, all known exchange outages; the longest is 6h (2020-02-19).
  - 5m BTCUSDT/ETHUSDT/SOLUSDT/BNBUSDT 2022-01-01 → 2026-10-09: 501,968 bars each. One gap (2023-03-24 outage, 85 min).
  - `wf_report.py` gained `--risk KEY=VALUE` (RiskManager settings, e.g. `max_position_pct=1.0`; only added to the cache key when set) and a **B&H Sharpe** column: the annualised Sharpe of buy & hold over the same OOS window, the risk-adjusted bar a long-only strategy has to beat.
- [x] **Stage 2: Donchian on 4h / 1d signals with vol-targeted sizing (3.5).** Code fingerprint `7eaad4fa0c8f7174`; tables in `reports/phase1b/donchian_*.md`.
  - **Code:** volatility-targeted sizing (3.5).
    - `BaseStrategy` params `vol_target` (annualised, 0 = off) and `vol_lookback` (signal bars). They add an `rvol` column (`indicators.realized_vol`) and set `Signal.size_frac = vol_target / rvol`.
    - `position_size(..., notional_frac=)` / `RiskManager.size` use that notional instead of stop-distance sizing, still capped by `max_position_pct`. Backtester and live engine both pass it.
    - Tests cover sizing, annualisation, signal fraction, backtest notional, and no look-ahead with vol targeting.
    - Not exposed as an env var yet; live trading stays blocked by the gate.
  - **Setup:** 1h execution bars (not 5m: 4h/1d signals don't need 5m stop checks, and 6.8 years of 5m × 27 combos would take hours), 2020-01-01 → 2026-10-09, train 365d / test 90d, time stop off (`max_bars=100000`), min train trades 5 (4h) / 3 (1d).
    - Lookbacks: 4h uses the default `24,48,96,192,384` (4–64 days); 1d uses `10,20,40,80,160` days.
    - Sizing: "stop" = default 0.5% risk per trade, 25% notional cap; "VT" = `vol_target=0.3` over 30 days of returns, `max_position_pct=1.0`.

    | Variant | Symbol | OOS % | B&H % | Max DD % | Trades | OOS Sharpe | B&H Sharpe | DSR | PBO |
    |---|---|---|---|---|---|---|---|---|---|
    | 4h, stop | BTC | +4.88 | +41.43 | −5.10 | 67 | 0.31 | 0.39 | 0.31 | 0.37 |
    | 4h, stop | ETH | +14.61 | −29.65 | −8.64 | 61 | 0.66 | 0.26 | **0.83** | 0.65 |
    | 4h, VT 30% | BTC | +25.92 | +41.43 | −18.20 | 68 | 0.40 | 0.39 | 0.47 | 0.53 |
    | 4h, VT 30% | ETH | **+63.82** | −29.65 | −26.78 | 63 | 0.68 | 0.26 | **0.88** | 0.88 |
    | 1d, stop | BTC | −1.85 | +11.98 | −2.25 | 21 | −0.35 | 0.30 | 0.04 | 0.43 |
    | 1d, stop | ETH | +0.86 | −54.29 | −2.27 | 23 | 0.17 | 0.09 | 0.23 | 0.20 |
    | 1d, VT 30% | BTC | −19.97 | +11.98 | −21.67 | 21 | −0.36 | 0.30 | 0.05 | 0.48 |
    | 1d, VT 30% | ETH | −10.88 | −54.29 | −26.56 | 23 | −0.14 | 0.09 | 0.05 | 0.14 |

    (OOS windows start ~2021-05 for 4h and ~2022-01 for 1d because of the warm-up, so buy & hold differs.)
  - **Reading:**
    - **4h is the best result of the whole project so far.** On ETH it beat buy & hold on return and Sharpe (0.66–0.68 vs 0.26) with DSR 0.83–0.88, but PBO is 0.65–0.88: which grid point wins in-sample doesn't carry over, so the edge may belong to the family rather than to the tuned parameters. On BTC it roughly matched buy & hold's Sharpe with far less exposure.
    - Vol targeting scales the 4h result up (more exposure) without changing its Sharpe much, as the literature says (3.5).
    - Daily signals fail: only ~21 trades in ~4.7 OOS years, and the 10–160-day lookbacks whipsawed in 2022–2025.
    - **Still FAIL:** nothing reaches DSR > 0.95 with PBO < 0.5. DSR only deflates for the 27-point grid; these 4 variants per symbol are extra trials it doesn't account for.
  - **Next for this family:** cut the grid (the high PBO says the 27 combos are mostly noise) to one or two robust settings and check that the 4h result survives; test 4h on SOL/BNB; and consider a portfolio across symbols rather than per-symbol gates.
- [ ] **Stage 3: opening_range on longer history and more symbols.**
- [ ] **Stage 4: regime and time-of-day filters (5.5, 5.2).**
- [x] **Stage 5: `research_runs` Postgres table and dashboard Research tab.** *(done ahead of stages 2–4 while their runs computed)*
  - `database.ResearchRun` (table `research_runs`, keyed by the cache key): spec, risk and params as JSON, plus the headline numbers (OOS return, B&H, max DD, trades, folds, OOS and B&H Sharpe, DSR, PBO, seconds). NaN is stored as NULL.
  - `research_cache.save` upserts each new run (best effort: 3 s connect timeout, then it logs once and stops trying; `RESEARCH_DB=0` turns it off). The files in `data/research/` stay the source of truth for equity and folds.
  - `scripts/research_db.py` backfills from `data/research/`; 27 existing runs loaded.
  - The dashboard's new **🔬 Research** tab has filters (strategy, symbol, code fingerprint, passes-gate only), a DSR-vs-PBO scatter with the gate region shaded, the run table, and each run's stitched OOS equity and folds.
  - Tests: upsert, NaN to NULL, no duplicates, a database failure never raises; tests never touch the real database (autouse fixture).

---

## 2. P0-C: live engine hardening (`src/engine.py`, `src/brokers.py`, `src/binance_client.py`)

These come from Binance's spot API docs and changelog (`binance/binance-spot-api-docs`), the installed SDK source (`binance-sdk-spot 13.1.0`, `binance-common 4.5.1`), and how Freqtrade, Hummingbot and NautilusTrader handle the same problems.

### 2.1 The user data stream (listenKey is dead)

- **Fact:** `POST/PUT/DELETE /api/v3/userDataStream` and `userDataStream.start/ping/stop` were **retired 2026-02-20 07:00 UTC**. Replacements on the WebSocket API (`wss://ws-api.binance.com/ws-api/v3`):
  - `userDataStream.subscribe`: needs `session.logon`, which needs an **Ed25519** key.
  - `userDataStream.subscribe.signature`: added 2025-08-12, works with any key type, no logon.
  - Each costs weight 2 and returns a `subscriptionId`.
  - Events: `executionReport`, `listStatus`, `outboundAccountPosition`, `balanceUpdate`, `eventStreamTerminated`, `externalLockUpdate`.
  - Sources: [CHANGELOG](https://developers.binance.com/docs/binance-spot-api-docs/CHANGELOG), [user-data-stream requests](https://developers.binance.com/docs/binance-spot-api-docs/websocket-api/user-data-stream-requests), [user-data-stream events](https://developers.binance.com/docs/binance-spot-api-docs/user-data-stream).
- **Current code:** no user stream at all. `BinanceBroker.check_exits` (`src/brokers.py:243`) **polls** `get_order_list_status` and then `get_order` once per closed bar, so fills are only detected up to one bar (5 min) late.
- [ ] Add a user-stream task in `BinanceClient` alongside `stream_closed_klines` (`src/binance_client.py:143`), using the SDK's WebSocket API client. Route `executionReport` and `listStatus` events into the broker.
- [ ] Handle `executionReport` execution types `x`: `NEW`, `TRADE`, `CANCELED`, `EXPIRED`, `REJECTED`, `REPLACED`, `TRADE_PREVENTION`. Also handle the `expiryReason` field (added 2026-05-06).
  - Dedupe by `(orderId, tradeId t)`.
  - Accumulate `l` (last filled qty) and `n`/`N` (commission and its asset). Average price = `Z / z`.
  - `listStatus.L == "ALL_DONE"` means the OCO is finished.
  - Binance documents no ordering guarantee, so code defensively.
- [ ] Keep REST polling only as a fallback. This is Hummingbot's rule: poll every 5 s if the user stream has been silent beyond a threshold, otherwise every 120 s. Reference: [hummingbot exchange_py_base.py](https://github.com/hummingbot/hummingbot/blob/master/hummingbot/connector/exchange_py_base.py).
- [ ] **Switch to Ed25519 keys.** Binance's FAQ now says HMAC keys are deprecated ([api_key_types.md](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/api_key_types.md)); no removal date found **[UNVERIFIED]**.
  - The SDK's auto-reconnect (at 23 h, `AUTO_RECONNECT_INTERVAL_SECONDS = 23*3600`, and on `serverShutdown`) re-runs `session.logon` and re-subscribes the user stream **only if you logged on** (`binance_common/websocket.py` ≈ lines 902–950).
  - With HMAC plus `subscribe.signature` you must re-subscribe in your own reconnect callback.
  - **[UNVERIFIED]** whether `subscribe.signature` streams are restored automatically. Test on Demo Mode by forcing a disconnect.

### 2.2 Order idempotency and unknown order states

- **Fact:** `newClientOrderId` is only unique among *open* orders. "Orders with the same newClientOrderID can be accepted only when the previous one is filled", so **retrying a MARKET order with the same cid can double-buy**.
  - A 5xx or `-1007` (timeout) "does not necessarily mean that your request has failed".
  - Sources: [rest-api.md](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md) (newClientOrderId), [errors.md](https://github.com/binance/binance-spot-api-docs/blob/master/errors.md).
- **SDK facts (verified in the installed source):**
  - `ConfigurationRestAPI` defaults to `timeout=1000` ms and `retries=3`.
  - Retries only apply to GET and DELETE (`binance_common/utils.py:355`, `retriable_methods = ["GET", "DELETE"]`), so a POST is never auto-resent. Good.
  - Our client sets `timeout=5000` (`src/binance_client.py:95,104`).
- **Current code:**
  - `market_buy` (`src/binance_client.py:178`) uses a random `bot-<uuid>` cid, but nothing is persisted before sending.
  - `market_sell` (`:190`) sets **no** cid.
  - `place_exit_oco` (`:200`) sets no `listClientOrderId`, `aboveClientOrderId` or `belowClientOrderId`.
  - `Store.opened` (`src/brokers.py:47`) runs only *after* the buy and the OCO succeed. A crash in between leaves a position the bot has no record of.
- [ ] Raise the trading-client timeout to about 10000 ms, which matches Binance's 10 s backend timeout.
- [ ] Add an **`orders` table** in `src/database.py` with columns: `client_order_id` (unique), `order_list_id`, `exchange_order_id`, `symbol`, `role` (entry/tp/sl/exit), `status` (PENDING_SUBMIT/NEW/PARTIALLY_FILLED/FILLED/CANCELED/EXPIRED/REJECTED/UNKNOWN), `position_id`, timestamps, `executed_qty`, `cum_quote`, `commission`, `commission_asset`.
  - Write the row **before** sending, using deterministic cids such as `{position_id}-entry`, `{position_id}-tp`, `{position_id}-sl`, `{position_id}-exit-{n}`.
  - Freqtrade has the same idea: an `orders` table linked to trades, with stoploss orders tagged `ft_order_side="stoploss"`.
- [ ] On a timeout, `-1007` or 5xx: **do not resend**. Wait for the `executionReport` with `c == cid`, or poll `GET /api/v3/order?origClientOrderId=cid` with backoff for about 30 s. Retry only after several `-2013` "order does not exist" answers.
  - Hummingbot marks an order "lost" after 3 not-found results ([client_order_tracker.py](https://github.com/hummingbot/hummingbot/blob/master/hummingbot/connector/client_order_tracker.py)) and treats a 503 as order id "UNKNOWN" rather than a failure ([binance_exchange.py](https://github.com/hummingbot/hummingbot/blob/master/hummingbot/connector/exchange/binance/binance_exchange.py)).

### 2.3 OCO sizing and protection failures

- **Current code:**
  - `BinanceBroker.open` (`src/brokers.py:201`) already subtracts a base-asset fee from the held quantity. Good.
  - On an OCO failure it immediately `market_sell`s. If *that* raises, the exception propagates, the position is never stored, and the position is **unprotected and untracked**.
- [ ] Retry the OCO once with fresh price checks before flattening. If the flatten fails, persist the position as `UNPROTECTED`, alert, and keep retrying on every bar.
- [ ] Before placing the OCO, check the price rule "LIMIT_MAKER price > last traded price > STOP_LOSS stopPrice". If the price has already moved past the stop or target during the fill, exit at market instead.
- [ ] Use `exchange_filters` for `TRAILING_DELTA` and `PERCENT_PRICE_BY_SIDE` too if trailing stops are adopted (2.5).

### 2.4 Atomic time-stop and discretionary exit (`BinanceBroker.close`, `src/brokers.py:235`)

- **Current code:** `cancel_order_list`, then `market_sell`. If the OCO filled between the two calls, the cancel raises, or the sell fails for insufficient balance. Neither case is handled.
- [ ] Use `POST /api/v3/order/cancelReplace` with:
  - `cancelOrigClientOrderId=<one OCO leg>`
  - `side=SELL`, `type=MARKET`, `quantity=held`
  - `cancelReplaceMode=STOP_ON_FAILURE`
  - Cancelling one leg cancels the whole order list. If the OCO already filled, the cancel fails and **no** sell is sent, so there is no double-sell.
  - Then treat the position as closed by the OCO fill.
  - Source: rest-api.md, "Cancel an Existing Order and Send a New Order".

### 2.5 Break-even / stop moves (`BinanceBroker.move_stop`, `src/brokers.py:264`)

- **Current code:** cancel the OCO, then place a new OCO.
  - The position is unprotected between the two calls.
  - If the second call fails, the exception propagates up to `engine.on_bar`, which only logs it. The position is left **unprotected** with a stale `exit_order_list_id`.
  - There is also no check that the OCO hasn't partially filled or triggered.
- Options:
  - (a) Keep cancel-and-replace, but wrap it: on failure, retry, then market-sell. Throttle moves (Freqtrade's default is 60 s via `stoploss_on_exchange_interval`). Never touch an order that has triggered.
  - (b) Use `cancelReplace` to swap to a single STOP_LOSS at break-even. This is atomic but loses the take-profit leg.
  - (c) Use Binance's native **trailing stop**: `belowType=STOP_LOSS` with `belowTrailingDelta` (in BIPS, must pass the `TRAILING_DELTA` filter) and no `belowStopPrice`, which ratchets up from the high-water mark. Or a trailing take-profit: `aboveType=TAKE_PROFIT` with `aboveStopPrice` as activation and `aboveTrailingDelta`. Sources: [trailing-stop-faq.md](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/trailing-stop-faq.md).
    - This is **not equivalent** to break-even. Model it in the backtester and PaperBroker first.
- Note: `PUT /api/v3/order/amend/keepPriority` can only **reduce quantity**, not change price ([order_amend_keep_priority.md](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/order_amend_keep_priority.md)). It does not help here.
- [ ] Implement (a) now and evaluate (c) behind a flag.

### 2.6 Reconciliation on startup and after every reconnect

- **Current code:** `TradingEngine.warmup` (`src/engine.py:32`) only *logs* positions restored from Postgres (`Store.load_open_positions`). It never checks them against the exchange.
- [ ] Add `BinanceBroker.reconcile()` and call it before streaming starts, after every user-stream reconnect, and every N minutes:
  1. For each OPEN position and order in the database: `GET /api/v3/order` (by `origClientOrderId`), `GET /api/v3/openOrderList`, `GET /api/v3/myTrades?orderId=` (for exact fills and fees).
  2. Compare with `GET /api/v3/account?omitZeroBalances=true` base-asset balances.
  3. Coins held but no live OCO: re-place the OCO, or flatten.
  4. OCO done: close the position in the database with the real fill price and fee.
  5. OCO on the exchange with no database row: adopt it or alert.
  6. Anything still ambiguous: **refuse to trade (fail closed)**.
- Note: orders that were cancelled or expired with no fills get archived after 90 days (`-2026`).
- References:
  - Freqtrade `startup_update_open_orders()` / `handle_onexchange_order()` ([freqtradebot.py](https://github.com/freqtrade/freqtrade/blob/develop/freqtrade/freqtradebot.py), around lines 264–790).
  - NautilusTrader's "fail closed" reconciliation ([reconciliation.md](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/execution/reconciliation.md)).
- [ ] Also fix `check_exits` (`src/brokers.py:243-262`):
  - Use exact fees from `myTrades` or the user stream instead of `cummulativeQuoteQty × fee_rate`.
  - When an OCO was cancelled externally, the position is currently marked closed while the **coins are still held**. Instead, re-protect or alert.

### 2.7 Kline gap-filling after websocket reconnects

- **Facts:** every connection is dropped at 24 h. `serverShutdown` is sent about 10 min before maintenance (added 2026-05-06). Ping every 20 s, pong within 60 s. Limits: 5 incoming msg/s, 1024 streams per connection, 300 connections per 5 min per IP. Klines **missed during a reconnect are lost** ([web-socket-streams.md](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md)).
- **Current code:** `_process_bar` (`src/engine.py:52`) appends `df.loc[t]` and assumes continuity. A gap silently corrupts the indicators.
- [ ] Track `last_closed_open_time` per symbol. On any (re)connect, or when `t != last + bar`, fetch the missing closed klines from REST (`client.get_klines`, data-api.binance.vision) and replay them through the same handler in order, deduped by open time.
- [ ] Add a test that feeds bars with a gap and asserts the frame is backfilled.

### 2.8 Rate limits and clock

- **Rate limits:**
  - `REQUEST_WEIGHT` is 6000/min per **IP**; `ORDERS` and unfilled-order counts are per account.
  - Since 2026-04-02, **successful** order, cancel, cancelReplace and orderList calls cost 0 weight, and `RAW_REQUESTS` is 300k per 5 min.
  - Read the `X-MBX-USED-WEIGHT-1M` and `X-MBX-ORDER-COUNT-*` headers (the SDK exposes them as `response.rate_limits`).
  - On 429/418, honour `Retry-After`. Bans escalate from 2 min to 3 days.
  - Sources: rest-api.md "LIMITS"; CHANGELOG 2026-03-27.
- **Clock:**
  - The SDK signs with raw `time.time()` and has **no server-offset correction** (`binance_common/utils.get_timestamp`).
  - Run chrony/NTP on the host. Check against `GET /api/v3/time` every few minutes and alert if drift exceeds 500 ms.
  - `recvWindow` takes up to 3 decimals (microseconds) since 2025-08-28. Keep it ≤ 5000.
  - On `-1021`, re-sync.
- [ ] Log and alert on weight usage, and add the clock-drift check.

### 2.9 Single instance

- [ ] Take a Postgres advisory lock (`pg_try_advisory_lock`) per (mode, account) at startup so two bot processes can never trade the same account.

### 2.10 Paper and demo testing

- **Binance Demo Mode** is live for the Spot API since 2026-01-29.
  - URLs: `demo-api.binance.com`, `demo-ws-api.binance.com`, `demo-stream.binance.com`. Keys come from demo.binance.com.
  - Filters, features and limits are **the same as live**. Order books are "similar to" live.
  - Balances reset on demand.
  - Sources: [demo-mode/general-info.md](https://github.com/binance/binance-spot-api-docs/blob/master/demo-mode/general-info.md), [demo-mode/CHANGELOG.md](https://github.com/binance/binance-spot-api-docs/blob/master/demo-mode/CHANGELOG.md).
- **Testnet** has prices and books independent of live (often thin), and balances reset monthly.
- `BINANCE_ENV=demo` already exists (`src/binance_client.py` `REST_URLS`).
- [ ] Before real money, run `TRADING_MODE=LIVE BINANCE_ENV=demo` for at least 1–2 weeks and exercise these scenarios:
  - kill the process mid-trade
  - cancel the OCO manually on the website
  - force a websocket disconnect
  - simulate a timeout
- [ ] Ensure the websocket URLs also switch to demo/testnet for the user stream. Market klines can stay on prod data.

### 2.11 Future: atomic entry plus protection (OTOCO / OPOCO)

- **OTOCO** (`POST /api/v3/orderList/otoco`, since 2024-06-11): the working order must be `LIMIT` or `LIMIT_MAKER`, **not MARKET**. The pending OCO is placed only when the working order is fully filled. **[UNVERIFIED]** whether `workingTimeInForce=IOC` is accepted.
- **OPOCO** (`/api/v3/orderList/opoco`, live 2025-12-18; check the `opoAllowed` symbol flag): the pending sell quantity is whatever the buy actually received, **net of commission and LOT_SIZE-adjusted**, which removes the sizing problem. BUY-working / SELL-pending only. Source: [faqs/opo.md](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/opo.md).
- Both have the same catch: a partial fill leaves the remainder working and no exit placed. You need an entry timeout that cancels the list and protects the filled part manually (cf. Freqtrade `unfilledtimeout`, Jesse `should_cancel_entry()`).
- `POST /api/v3/orderList/oco` is the current OCO endpoint; the old `/api/v3/order/oco` is **deprecated**. The SDK's `order_list_oco` already uses the new one.
- [ ] Evaluate OPOCO with a marketable LIMIT entry once 2.1–2.6 are done.

### 2.12 Not needed

- SOR (`/api/v3/sor/order`): it only routes across interchangeable stablecoin books.
- STP: with one position per symbol the bot cannot self-trade. Just parse `TRADE_PREVENTION`.

---

## 3. P1: risk layer (`src/risk.py`)

- [ ] **3.1 A unified exit spec.**
  - Replace the scattered exit settings (`Signal.stop/target`, `strategy.p["max_bars"]`, `breakeven_at_r`) with a `Barriers` dataclass: `stop`, `target`, `max_bars`, `breakeven_r`, `trailing: {activation_r, delta_r} | None`.
  - The backtester (`_Adapter.next`), `TradingEngine._process_bar` and both brokers should consume the same object.
  - This is modeled on Hummingbot's `TripleBarrierConfig` (Apache-2.0, can be copied with notice): [data_types.py](https://github.com/hummingbot/hummingbot/blob/master/hummingbot/strategy_v2/executors/position_executor/data_types.py), [position_executor.py](https://github.com/hummingbot/hummingbot/blob/master/hummingbot/strategy_v2/executors/position_executor/position_executor.py).
  - Hummingbot's trailing stop: activate when PnL% > activation, trigger = PnL − delta, ratchet up only. `new_instance_with_adjusted_volatility()` scales all barriers by a volatility factor.
  - **Caveat:** Hummingbot's stop, time and trailing barriers are client-side. Our exchange-side OCO is safer; keep it.
- [ ] **3.2 Freqtrade-style protections** as composable lock objects (re-implement, GPL). Interface: `Protection.check(closed_trades, now) -> Lock(scope=symbol|global, until) | None`, with lookbacks counted in candles.
  - **StoplossGuard:** `trade_limit` stop-outs within `lookback_period_candles` lock trading for `stop_duration_candles`. Can be per pair.
  - **MaxDrawdown:** `max_allowed_drawdown` over a lookback, on equity.
  - **LowProfitPairs:** lock a symbol whose profit over its last N trades is below `required_profit`.
  - **CooldownPeriod:** per-symbol lock after any exit.
  - Our existing `loss_streak_cooldown` and `daily_loss_limit` become two such protections.
  - Docs: [freqtrade plugins](https://www.freqtrade.io/en/stable/plugins/), [source](https://github.com/freqtrade/freqtrade/tree/develop/freqtrade/plugins/protections).
  - `RiskManager` needs a closed-trade history to support this. Today it only tracks a streak.
- [ ] **3.3 Correlation-aware portfolio heat cap.**
  - BTC/ETH ρ ≈ 0.87 (measured), so two longs are about 1.9× one bet.
  - Add `max_portfolio_risk` (e.g. 0.75% of equity) as the sum of open `qty × (entry − stop)`. Alternatively scale the second position by `1/√(1+ρ)`.
  - `can_open` (`src/risk.py:96`) currently only counts positions.
- [ ] **3.4 Drawdown de-risking.** Halve `risk_per_trade` at −5% from peak equity and pause entries at −10%. This is sensible capital preservation, with weak evidence that it adds return. Equity-curve trading (stop when equity is below its moving average) has weak and mixed evidence, so skip it.
- [ ] **3.5 Volatility-targeted sizing** within the existing caps: scale risk so per-trade notional volatility is constant. It stabilizes risk but does not reliably add return ([Cederburg et al. 2020, JFE](https://www.lehigh.edu/~xuy219/research/COWY.pdf); Harvey et al. 2018).
- [ ] **3.6 Decaying target (ROI table):** Freqtrade-style `minimal_roi = {"0": x, "40": 0.0}` (minutes since entry → required profit), as an optional complement to `max_bars`.
- **Defer:** fractional Kelly (needs hundreds of live trades; cap at 0.25 Kelly if ever used), and riskfolio-lib / skfolio portfolio optimization (overkill for 2 symbols).

---

## 4. P0-B / P1: backtest validity (`src/backtester.py`, `tests/`)

### Facts about the current engine

These were verified in the installed backtesting.py 0.6.5 source.

- When a bar touches both stop and target, **the stop fills first**. `new_order()` inserts stop orders at the front of the queue, so this is pessimistic and consistent with `risk.bar_exit`. Break-even updates re-create the stop order, which also goes to the front.
- A stop or limit *entry* whose stop/target is inside the same bar has its exit deferred to the next bar (issue #119). Market entries are fine.
- `backtesting.lib.random_ohlc_data()` exists for synthetic OHLC.
- `Backtest.optimize(..., return_heatmap=True)` plus `backtesting.lib.plot_heatmaps` give parameter heatmaps.
- **0.6.6** (2026-07-22) fixes Pandas 3.0 array errors and a CAGR bug ([CHANGELOG](https://github.com/kernc/backtesting.py/blob/master/CHANGELOG.md)). Bump `backtesting>=0.6.6` in `pyproject.toml`.

### 4.1 Look-ahead and warm-up tests (P0-B, ~1 day)

- [x] **`tests/test_lookahead.py`:** for each strategy, pick about 200 cut points `t`, including every signal bar and bars in the middle of an unfinished 1h candle. *(done in Phase 1 stage 4: `src/validation.py` `lookahead_check` + `default_cuts`; `tests/test_lookahead.py` runs 200 cuts per strategy and per signal-timeframe variant, plus a test that a planted centred-window leak is caught.)*
  - Assert `strategy.prepare(df.loc[:t]).iloc[-1]` ≈ `strategy.prepare(df).loc[t]` (`np.isclose`, rtol 1e-9; both start at the same first bar, so the recursive EMAs match exactly).
  - Also assert `entry_signal` gives the same result.
  - This catches leaks in `higher_tf`, `session_vwap`, `resample_ohlcv`, the opening-range groupby, and any `shift(-1)`, `bfill` or centered window.
  - Freqtrade's version: [lookahead.py](https://github.com/freqtrade/freqtrade/blob/develop/freqtrade/optimize/analysis/lookahead.py), [docs](https://www.freqtrade.io/en/stable/lookahead-analysis/). It runs truncated backtests ending one candle after each entry or exit and compares the signal and indicator columns with no tolerance.
- [x] **`tests/test_recursive.py`** *(done in Phase 1 stage 4 as `validation.recursive_check`, tested in `tests/test_lookahead.py`; tests marked `slow`, skip with `-m "not slow"`)* (Freqtrade `recursive-analysis`, [docs](https://www.freqtrade.io/en/stable/recursive-analysis/)): compute indicators with N bars of history before an evaluation point (N = 20, 40, 80, 150, 300, 999 …) and report the % difference of the last value against full history.
  - Use it to verify each strategy's `warmup_bars(bar)` is large enough that the live engine (`keep_bars`, `src/engine.py:27`) matches the backtest within e.g. 0.1%.
  - EMA200 on 1h inside `ema_pullback` is the riskiest.

**Stage 4 results.** Run on real data with `uv run python src/validation.py BTCUSDT 5m 2026-06-01` (60 cuts per strategy, 10 evaluation points):

- **No look-ahead** in any strategy (0 mismatches on real data and on the synthetic fixture, including 15min/1h signal timeframes).
- **Two warm-up bugs found and fixed:**
  1. Warm-ups used fixed multiples (`1.5 × atr_n` 1h bars for the stop ATR, `1.5 × htf_slow` for EMA200-on-1h). Wilder ATR needs ≈6.9·n bars and an EMA ≈3.5·(n+1) bars to forget their seed to 0.1%, so the live engine's stop ATR differed from the backtest by ≈5%. New `indicators.ewm_warmup(alpha, tol)` now derives the warm-ups: the base class covers the 1h ATR (1,308 5m bars ≈ 4.5 days), and `ema_pullback` needs 8,305 5m bars ≈ 29 days.
  2. `donchian_ensemble` component states were path-dependent: a component stayed long from a breakout until an exit, however long ago, so live and backtest could disagree indefinitely (50% score difference at the old warm-up). Components now look only at channel events within their own lookback, and the warm-up is 2 × the longest lookback (9,252 5m bars ≈ 32 days).
- **Max indicator difference with the live engine's history** (`warmup_bars + 50`) vs full history, after the fixes: ema_pullback 0.0%, vwap_reversion / squeeze_breakout / opening_range 0.03%, donchian_ensemble 0.0%. With only 300 bars it was 17.6% (vwap/squeeze/orb), and 100% for ema_pullback/donchian.

### 4.2 Overfitting statistics on the walk-forward results (P1)

- [x] **Deflated Sharpe Ratio / Probabilistic Sharpe Ratio.** *(done in Phase 1 stage 5: `src/overfitting.py` `probabilistic_sharpe`, `expected_max_sharpe`, `deflated_sharpe`; own code from the papers, no SciPy needed (stdlib `NormalDist`). `backtester.overfitting_report()` deflates the stitched walk-forward OOS daily returns by the Sharpe variance of the full parameter grid.)*
  - Correct the selected parameter set's Sharpe for the number of grid trials. About 30 lines; formula from Bailey & López de Prado ([SSRN 2460551](https://papers.ssrn.com/abstract=2460551)).
  - Reference code: [esvhd/pypbo](https://github.com/esvhd/pypbo) (**AGPL**, don't copy) and [zoonek/2025-sharpe-ratio](https://github.com/zoonek/2025-sharpe-ratio) (PSR, MinTRL, FDR; license **[UNVERIFIED]**).
  - Write our own implementation.
- [x] **PBO via CSCV.** *(done in Phase 1 stage 5: `overfitting.pbo_cscv` (16 blocks → all 12,870 splits, or a random subset via `max_splits`); the T×N matrix comes from `backtester.grid_returns()`, i.e. daily returns of every grid combination over the full period. Also reports the in-sample vs out-of-sample Sharpe of the in-sample winner.)*
  - Build a T×N matrix of per-period (e.g. daily) returns for every grid combination. `walk_forward` already runs them all inside `bt.optimize`; capture the per-combo equity or returns.
  - Split into S = 16 blocks. For each of the C(S, S/2) in-sample/out-of-sample splits, take the in-sample best combo's out-of-sample rank.
  - PBO = share of splits where that rank is below the median.
  - Other implementations: pypbo, the R package [pbo](https://github.com/mrbcuda/pbo).
- [ ] **Combinatorial Purged Cross-Validation (CPCV).** *(not in Phase 1)* Use [`skfolio.model_selection.CombinatorialPurgedCV`](https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html) (BSD, v1.8.1) purely as an index splitter: `n_folds`, `n_test_folds`, `purged_size`, `embargo_size`, `recombined_paths`. It gives many out-of-sample paths instead of one.
- [ ] **White's Reality Check / Hansen SPA.** *(not in Phase 1)* [`arch.bootstrap.SPA`](https://arch.readthedocs.io/en/latest/multiple-comparison/generated/arch.bootstrap.SPA.html) (NCSA, arch 8.0.0): losses = −per-bar returns of each combo vs a flat or buy-and-hold benchmark. StepM and MCS are also in `arch.bootstrap` **[UNVERIFIED details]**.
- [ ] **Walk-forward diagnostics.** *(partly: the fold table already has the chosen params and train score per fold; heatmaps and stability metrics not done)* Per fold, log the chosen parameters, the train→test SQN degradation and parameter stability. Save heatmaps (`return_heatmap=True`).

### 4.3 Monte Carlo

- [ ] Reshuffling trade order only changes the path (max drawdown, streaks), not the final return. Bootstrap **with replacement** for return dispersion. On 5m data, a block bootstrap of daily returns is better.
- [ ] Report the p5/p95 of CAGR and max drawdown, plus the probability of hitting the daily-loss or max-drawdown limits.

### 4.4 Intrabar realism

- [ ] **Measure first:** count trades whose exit bar had `Low <= SL and High >= TP`. If that's under about 1%, skip the rest of this item.
- [ ] Otherwise, resolve ambiguous bars with 1m, 1s or aggTrades data from data.binance.vision ([binance-public-data](https://github.com/binance/binance-public-data)) and rewrite those exits in `stats._trades`. This is easy because the strategies are long-only with one position at a time. Also re-check break-even moves inside a bar.
  - Freqtrade has `--timeframe-detail` ([docs](https://www.freqtrade.io/en/stable/backtesting/)).
  - NautilusTrader uses a fixed O→H→L→C path or `bar_adaptive_high_low_ordering` ([bar execution](https://nautilustrader.io/docs/latest/concepts/backtesting/bar-execution/)).
- [ ] **Latency sensitivity:** closed klines arrive about 0.1–1 s after the bar closes, so filling at the next bar's open is optimistic. Add a run filling at the worse of next open ± k ticks.
- [ ] **Model the exit legs separately:** the take-profit is a maker fill at its exact limit price; the stop-loss is a taker fill with slippage. PaperBroker already does this (`src/brokers.py:169`). The backtester applies a symmetric `spread`.

### 4.5 Reporting

- [x] **Research persistence** *(added during Phase 1 at the user's request)*.
  - `src/research_cache.py` caches every `scripts/wf_report.py` run in `data/research/<key>/` (spec, summary, per-fold table, OOS equity) plus `data/research/index.csv`. The key covers the full run spec and a fingerprint of the result-affecting code (strategies, indicators, risk, backtester, data loading) and the backtesting/pandas versions. Identical reruns are instant; any code change invalidates automatically. Use `--refresh` to force a recompute.
  - `--out reports/...md` writes the table to a file. Reports under `reports/` are committed, so results survive across machines; `data/` (klines + research cache) stays gitignored and can be copied between machines.

- [ ] Use **quantstats** 0.0.86 (Apache-2.0, maintained) on daily returns resampled from the stitched out-of-sample equity. Optional: ffn 1.4.0 (MIT).
- Skip pyfolio-reloaded and empyrical-reloaded (no release in over a year).

### 4.6 Alternative engines (no action, for reference)

| Engine | License | Note |
|---|---|---|
| vectorbt 1.1.2 | Apache-2.0 + Commons Clause | Fast parameter sweeps, useful for PBO matrices. |
| PyBroker 2.0.1 | Apache-2.0 + Commons Clause | Built-in walk-forward and bootstrap; equities-oriented. |
| NautilusTrader | LGPL-3.0 | Most realistic, but Python ≥3.12/3.13. |
| Freqtrade | GPL-3.0 | Would mean rewriting the bot as a Freqtrade strategy. |
| Jesse 3.2.4 | MIT | Real 1m candles, Monte Carlo, Optuna. |
| backtrader | GPL-3.0 | Stale since 2023. |
| zipline-reloaded, bt | Apache / MIT | Poor fit. |

**Decision:** keep backtesting.py.

---

## 5. P2: strategies (`src/strategies/`)

- [x] **5.1 Make the opening range follow New York time.** *(done in Phase 1 stage 3: `session_open="09:30"` + `session_tz="America/New_York"` converted per local day, so DST is handled; `session_tz="UTC"` keeps a fixed UTC open. Tests cover January (14:30 UTC), July (13:30 UTC) and the UTC override.)*
  - `OpeningRangeBreakout` hard-codes `"session_open": "13:30"` UTC (`src/strategies/opening_range.py:16`). That is the NYSE open only during US daylight time (EDT). In winter (EST) the open is **14:30 UTC**.
  - Fix: compute the open per day with `zoneinfo.ZoneInfo("America/New_York")` at 09:30 local, then convert to UTC. Keep a UTC override option.
  - Evidence (strong, descriptive): 13:00–21:59 UTC carried 50.6% of BTC daily variance in 2022–25, up from 38.4%. The peak shifts with US daylight saving. Weekend volatility is about 0.6× weekdays ([CryptoSlate summary of an MDPI study](https://cryptoslate.com/crypto-never-closes-but-bitcoin-ethereum-xrp-and-solana-now-move-on-wall-street-time/)).
  - **No peer-reviewed crypto opening-range study was found**, so the opening-range edge itself has weak evidence.
- [ ] **5.2 Time-of-day volatility gate:** restrict breakout strategies (squeeze, opening range) to about 13:00–17:00 UTC, when the 5m range is about 2× overnight. Hour-of-day *return* anomalies are **not persistent** (Baur et al., SSRN 3088472; [Quantpedia](https://quantpedia.com/are-there-seasonal-intraday-or-overnight-anomalies-in-bitcoin/); [Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/) reports gross of costs). Use hours as **volatility filters only**.
- [ ] **5.3 Multi-timeframe crash veto for the dip strategies** (`vwap_reversion`, `ema_pullback`), from NostalgiaForInfinity (GPL-3.0, re-implement only):
  - Skip entries when RSI(3) is crashing on several timeframes at once, e.g. `RSI3_5m < 3 and RSI3_15m < 5 and RSI3_1h < 15`.
  - Skip after a large daily move or a big upper wick.
  - Evidence: weak to moderate (practitioner work, popular but survivorship-biased).
  - **Do not port NFI's DCA / "grinding" or its −99% stoploss.**
  - NFI context: 5m bars, 40–80 volume-ranked pairs, 6–12 open trades, deep dip-buys (e.g. EMA26 − EMA12 > 3.4% of price and close < 0.999 × lower BB), a liquidity check on zero-volume candles in the last 288 bars, and a BTC 4h informative timeframe. Repo: [iterativv/NostalgiaForInfinity](https://github.com/iterativv/NostalgiaForInfinity).
- [x] **5.4 Slower signal timeframe.** *(done in Phase 1 stage 2, except vol-targeted sizing, which is 3.5)*
  - Test 15m or 1h signals with 5m execution: run strategies on `resample_ohlcv` output and keep the engine on 5m.
  - Slower trend following has the best net-of-cost crypto evidence: an ensemble of Donchian channels with vol-targeted sizing, net Sharpe > 1.5, but on daily or multi-hour bars ([Zarattini, Pagani & Barbon, SFI RP 25-80](https://ideas.repec.org/p/chf/rpseri/rp2580.html)).
  - Consider adding a Donchian-ensemble trend strategy.
  - **Done:**
    - New `signal_tf` param on every strategy (env `SIGNAL_TF`, dashboard walk-forward selector, `wf_report.py --set signal_tf=1h`). `prepare()` resamples to `signal_tf`, computes indicators there, and forward-fills only *closed* signal bars onto the execution bars via `indicators.align_higher_tf()`. `prev:<col>` columns carry the previous signal bar; `signal_bar` marks the execution bars that close one. Entries and discretionary exits fire only on those bars; stops, targets, break-even and the time stop still run on every execution bar.
    - New `donchian_ensemble` strategy (1h signals by default): 5 Donchian breakout components (24–384 signal bars), long when ≥ `entry_threshold` of them are long, exit when the share falls to `exit_threshold`, wide 3×ATR stop.
    - Timeframe strings are normalised (`15m` → `15min`, `1d` → `1D`); pandas reads `15m` as *months*.
    - Speed-up: strategy rows are converted to dicts once per frame instead of building a pandas Series per bar (tests 9.4 s → 3.2 s; a 6-month 5m walk-forward ≈ 2 min). `scripts/wf_report.py` now runs jobs in parallel processes (`--jobs`).
    - Tests: no look-ahead with `signal_tf` = 15min/1h (cuts inside forming bars), signals only on signal-bar closes, aligned values equal the resampled bar.
  - **Results:** see the Phase 1 results tables in section 1. 1h signals reduce losses but nothing passes the gate.
- [ ] **5.5 Regime routing with simple deterministic measures:** Kaufman Efficiency Ratio, Choppiness Index and realized-volatility percentile on 1h.
  - Run VWAP mean-reversion and EMA pullback only when ER(1h) is low and volatility is mid-range.
  - Run squeeze and opening range only when ER is rising, during 13–16 UTC.
  - Skip when 1h realized vol is below about the 20th percentile (targets can't clear fees) or above about the 95th (crash risk).
  - Fit thresholds on train windows, freeze them, and test on later windows.
  - Evidence: practitioner lore. **hmmlearn is in limited-maintenance mode**, and HMM-on-BTC papers are mostly in-sample. Defer HMMs.
- [ ] **5.6 Universe selection (optional, if more symbols are added).** Freqtrade's pairlist pipeline ([plugins](https://www.freqtrade.io/en/stable/plugins/)):
  - **VolumePairList:** `number_assets`, `sort_key=quoteVolume`, `min_value`, `refresh_period`.
  - **Filters:** AgeFilter (`min_days_listed`); **PrecisionFilter** (drop pairs where tick rounding of the stop exceeds 1%, which matters with tight 5m stops); PriceFilter; **SpreadFilter** (`max_spread_ratio`); VolatilityFilter / RangeStabilityFilter (drop pairs that are too quiet, important given the fee hurdle); DelistFilter.
  - Implement `select_universe()` run hourly.
- [ ] **5.7 A multi-timeframe merge helper:** `higher_tf` already avoids look-ahead. Freqtrade's equivalent (`merge_informative_pair`) shifts the higher-timeframe date by one period and then does an as-of merge. Covered by the test in 4.1; no change unless that test finds a leak.
- [ ] **5.8 Jesse-style partial exits** (MIT): `self.take_profit = [(q/2, p1), (q/2, p2)]` ([docs](https://docs.jesse.trade/docs/strategies/entering-and-exiting)). Optional scale-out support once the exit spec (3.1) exists. On spot this needs multiple OCOs or a TP ladder.

### Evidence summary for intraday crypto edges

- **Intraday time-series momentum (moderate):** BTC's first half-hour return predicts the last half-hour ([Shen, Urquhart & Wang 2022](https://research.birmingham.ac.uk/en/publications/bitcoin-intraday-time-series-momentum/)). Both momentum and reversal appear, depending on jumps, FOMC days and liquidity ([Wen et al. 2022, NAJEF](https://ideas.repec.org/a/eee/ecofin/v62y2022ics1062940822000833.html)). Neither shows profits after 0.2% round trips.
- **2026 "Quarter-Hour Effect" preprint** ([arXiv 2607.09426](https://arxiv.org/abs/2607.09426)): unreviewed, perps, no costs. Treat as hype until replicated.
- **ML/LLM:**
  - FreqAI (GPL) is a framework paper with no out-of-sample profitability evidence ([JOSS](https://joss.theoj.org/papers/10.21105/joss.04864)).
  - The LLM trading "arena" results (2025) were mostly losses, with n = 1.
  - The only defensible later use is a **meta-label classifier** (take or skip a rule signal), validated with purged CV and DSR, once there are more than 500 signals. **Defer.**
- **Freqtrade Edge positioning was removed** (PR #11867, June 2025). Don't replicate it.

---

## 6. P2: ops and observability

- [ ] **API keys:**
  - Ed25519, trade-only (withdrawals off), IP-whitelisted to a static-IP VPS.
  - Mount the PEM as a Docker secret or read-only file, not an environment variable baked into the image.
  - Use separate keys for demo and prod.
  - **[UNVERIFIED]** that keys without an IP restriction lose trade permission after 90 days ([bitsgap blog](https://bitsgap.com/blog/trade-only-api-keys-why-your-bot-cant-withdraw-your-funds)).
- [ ] **Control plane:** a Telegram bot (`python-telegram-bot` 22.x, async) in the same event loop.
  - Allowlist by chat_id, like Freqtrade's `authorized_only` ([telegram.py](https://github.com/freqtrade/freqtrade/blob/develop/freqtrade/rpc/telegram.py)).
  - Commands: `/status`, `/pause` (no new entries), `/resume`, `/flatten <sym>` (with confirmation), `/reconcile`, `/daily`.
  - Handlers send commands to the engine through an `asyncio.Queue` and never call the exchange directly.
  - Alternative: the Streamlit dashboard writes commands to a Postgres `commands` table that the engine polls.
  - Spec reference: Freqtrade [telegram-usage](https://www.freqtrade.io/en/stable/telegram-usage/), [rest-api](https://www.freqtrade.io/en/stable/rest-api/).
- [ ] **Heartbeat / dead-man's switch:** ping healthchecks.io (or similar) only if all of these hold: market stream fresh, user stream fresh, last reconcile OK, clock drift OK. Optionally systemd `sd_notify` WATCHDOG, as in Freqtrade's [worker.py](https://github.com/freqtrade/freqtrade/blob/develop/freqtrade/worker.py).
- [ ] **Prometheus** (`prometheus_client.start_http_server`). Metrics to export:
  - used weight
  - order round-trip latency histogram
  - user-stream lag (event `E` vs local time)
  - reconnect count
  - open positions
  - **seconds a position has been unprotected** (alert if over 5 s)
  - equity and PnL
- [ ] **Docker:** one container per account, `restart: unless-stopped`, the advisory lock from 2.9, and NTP on the host rather than in the container.

---

## 7. P2: libraries and data hygiene

- [x] **ccxt removed.** `src/exchange_wrapper.py` is deleted, nothing imports `ccxt`, and it's gone from `pyproject.toml`. Keep it that way:
  - Running two exchange clients means two state, clock and timeout policies and double rate-limit use.
  - (`ccxt.pro` `watchOrders` for Binance spot does use `userDataStream.subscribe.signature`, but OCO, OTOCO and cancelReplace are only reachable through raw `privatePost…` calls there.)
- [ ] **Keep `binance-sdk-spot`** as the only exchange client. Alternatives checked:
  - `python-binance` 1.0.37 is maintained but there's no reason to switch.
  - `unicorn-binance-websocket-api` 2.16.1 (MIT) is a fallback if the SDK's websocket is flaky.
  - `cryptofeed` (AGPL, Python ≥3.13) is not a fit.
- [x] **Bump `backtesting>=0.6.6`.** *(done in Phase 1 stage 6)*
- [ ] **Indicators:** consider **TA-Lib 0.8.1** (BSD-2; pip wheels for cp311 on macOS, Linux and Windows) for live/backtest parity.
  - `talib.stream` is now a true incremental API: `stream.RSI(history)` returns a handle, `.update(bar)` is O(1), `.peek()` gives the forming bar, and `open_and_fill()` does both. Streamed values are documented as identical to batch values.
  - **Breaking change:** the old `talib.stream.X` functions that returned only the last value are gone. Watch `set_unstable_period` for EMA, RSI and ADX.
  - **First diff its RSI, ATR and ADX against `src/indicators.py`** (Wilder `ewm(alpha=1/n, adjust=False)` seeding may differ).
  - Sources: [README](https://github.com/TA-Lib/ta-lib-python), [CHANGELOG](https://raw.githubusercontent.com/TA-Lib/ta-lib-python/master/CHANGELOG).
  - Alternative: talipp 2.7.0 (MIT, pure-Python incremental).
  - **Avoid pandas-ta:** the twopirllc repo now returns 404, 0.3.14b0 was pulled from PyPI, and only 0.4.71b0 (Python ≥3.12, numba) remains. A fork is pandas-ta-classic (MIT).
  - Avoid `ta` (stale since 2023) and `finta` (archived).
  - **Note:** the current engine recomputes `strategy.prepare(df)` over `keep_bars` rows on every bar (`src/engine.py:63`). That's fine at 5m. Incremental indicators are only needed for much faster intervals.
- [ ] **Data integrity (`src/data.py`):**
  - Verify each downloaded zip against its `.CHECKSUM` file (SHA-256) from data.binance.vision.
  - Add a gap and duplicate check on the loaded 5m index (exchange outages produce missing bars) and log the gaps.
  - `klines_to_df` already handles the microsecond timestamps that spot archive files use since 2025-01-01.
- Optional: DuckDB `read_parquet('data/klines/**/*.parquet')` for ad-hoc research.
- Not needed: tardis.dev (paid tick/L2 data).

---

## 8. Open questions / unverified (check before relying on them)

1. 0% maker fee on BTC/FDUSD and ETH/FDUSD since 2026-01-29. Check with `GET /api/v3/account/commission`.
2. Whether OTOCO accepts `workingTimeInForce=IOC` for a marketable-limit entry.
3. Whether the SDK auto-reconnect re-subscribes `userDataStream.subscribe.signature` without `session.logon`. Test on Demo Mode.
4. The HMAC key deprecation timeline.
5. Whether unrestricted-IP keys expire after 90 days.
6. Whether TA-Lib's Wilder smoothing matches `src/indicators.py` exactly.
7. The license of zoonek/2025-sharpe-ratio.
8. Exact BNB fee-discount terms (taken from secondary sources).
9. Whether Hummingbot resumes executors after a crash, and the pricing of Jesse's live plugin. Both are only relevant if adopting either.

## 9. Project survey snapshot (2026-10-10, from the GitHub/PyPI APIs)

| Project | License | Stars | Latest | Python | Verdict |
|---|---|---|---|---|---|
| Freqtrade | GPL-3.0 | 55.2k | 2026.9 | ≥3.11 (PyPI) / ≥3.12 (repo) | Ideas only |
| Hummingbot | Apache-2.0 | 20.4k | v2.17.0 | ≥3.10 | Copy exit model with attribution |
| NautilusTrader | LGPL-3.0 | 29.8k | v2.0.0rc6 | ≥3.13 (v2) | Design reference |
| QuantConnect LEAN | Apache-2.0 | 21.9k | Docker/CLI | C# | Too heavy |
| Jesse | MIT (core) | 8.6k | 3.2.4 | — | API ideas; live is a paid plugin |
| OctoBot | GPL-3.0 | 6.7k | 3.0.0-beta3 | ≥3.12 | Low fit |
| Superalgos | Apache-2.0 | 5.7k | 1.7.0 | JS | Low fit |
| Passivbot | Unlicense | 2.1k | v8.1.0 | futures grid | Low fit |
| vectorbt | Apache-2.0 + Commons Clause | 9.3k | 1.1.2 | — | Optional research tool |
| barter-rs / hftbacktest | MIT | 2.3k / 4.9k | — | Rust | Reference only |
