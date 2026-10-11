# Phase 1c: 4h Donchian robustness (fixed parameters, no optimiser)

Evaluation 2021-06-01 → 2026-10-09 on 1h bars (history from 2020-01-01 for warm-up), fee 0.10%/side, slippage 2.0 bps/side, params {'signal_tf': '4h', 'max_bars': 100000, 'vol_target': 0.3, 'vol_lookback': 180} + defaults {'stop_atr': 3.0, 'entry_threshold': 0.6, 'exit_threshold': 0.2, 'lookbacks': '24,48,96,192,384'}, risk {'max_position_pct': 1.0} (code 830f7992d589c726).

## Per symbol (base parameters)

| Symbol | Return % | B&H % | Max DD % | Trades | Exposure % | Sharpe | B&H Sharpe |
|---|---|---|---|---|---|---|---|
| BTCUSDT | 62.71 | 125.21 | -28.03 | 53 | 26 | 0.61 | 0.55 |
| ETHUSDT | 100.86 | -5.57 | -22.65 | 47 | 29 | 0.73 | 0.34 |
| SOLUSDT | 75.23 | 252.74 | -30.56 | 55 | 25 | 0.61 | 0.73 |
| BNBUSDT | 137.87 | 104.84 | -31.27 | 52 | 30 | 0.86 | 0.52 |

## Equal-weight portfolio (daily rebalanced)

| Series | CAGR % | Vol % | Sharpe | Max DD % |
|---|---|---|---|---|
| Donchian portfolio (base) | 14.01 | 14.69 | 0.97 | -19.70 |
| Buy & hold basket | 21.14 | 62.55 | 0.62 | -81.24 |

- **DSR 0.96** (deflated over 15 variants), **PBO 0.49** (CSCV, 12870 splits over the 15 portfolio variants).

## Year by year (portfolio)

| Year | Donchian % | B&H basket % |
|---|---|---|
| 2021 (part) | 14.56 | 107.71 |
| 2022 | -9.41 | -74.20 |
| 2023 | 38.30 | 202.38 |
| 2024 | 14.94 | 102.67 |
| 2025 | 14.65 | -4.48 |
| 2026 (part) | 6.75 | -10.89 |

## Parameter sensitivity (portfolio Sharpe; per-symbol Sharpe)

| Variant | Portfolio Sharpe | BTCUSDT | ETHUSDT | SOLUSDT | BNBUSDT |
|---|---|---|---|---|---|
| base | 0.97 | 0.61 | 0.73 | 0.61 | 0.86 |
| stop_atr=1.5 | 0.73 | 0.35 | 0.88 | 0.42 | 0.24 |
| stop_atr=2.25 | 0.96 | 0.60 | 0.94 | 0.57 | 0.54 |
| stop_atr=3.75 | 1.00 | 0.55 | 0.82 | 0.74 | 0.84 |
| stop_atr=4.5 | 0.85 | 1.04 | 0.84 | 0.54 | 0.23 |
| entry_threshold=0.4 | 1.12 | 1.01 | 0.89 | 0.85 | 0.55 |
| entry_threshold=0.5 | 0.97 | 0.61 | 0.73 | 0.61 | 0.86 |
| entry_threshold=0.7 | 0.87 | 0.58 | 0.83 | 0.75 | 0.44 |
| entry_threshold=0.8 | 0.87 | 0.58 | 0.83 | 0.75 | 0.44 |
| exit_threshold=0.0 | 0.86 | 0.50 | 0.58 | 0.72 | 0.74 |
| exit_threshold=0.1 | 0.86 | 0.50 | 0.58 | 0.72 | 0.74 |
| exit_threshold=0.3 | 0.97 | 0.61 | 0.73 | 0.61 | 0.86 |
| exit_threshold=0.4 | 0.93 | 0.80 | 0.57 | 0.59 | 0.69 |
| lookbacks=12,24,48,96,192 | 1.12 | 0.96 | 0.62 | 1.00 | 0.73 |
| lookbacks=48,96,192,384,768 | 0.64 | 0.68 | 0.56 | 0.60 | -0.08 |

## Cost stress (portfolio)

| Costs | Sharpe | CAGR % |
|---|---|---|
| base (0.1% fee, 2.0 bps) | 0.97 | 14.01 |
| slippage 2x | 0.96 | 13.89 |
| slippage 3x | 0.95 | 13.78 |
| fee 0.15% | 0.93 | 13.43 |

## Gate

- [x] DSR > 0.95
- [x] PBO < 0.5
- [x] positive in a majority of years (5/6)
- [x] Sharpe > 0 for every sweep variant
- [x] Sharpe > 0 at 2x slippage

**PASS**
