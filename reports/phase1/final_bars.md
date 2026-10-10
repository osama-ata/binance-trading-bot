<!-- Final Phase 1 run (code fingerprint 1c08844fda07262b), backtesting 0.6.6, walk-forward 2026-04-01 → 2026-10-09,
     train 30d / test 7d, fee 0.1%/side, slippage 2 bps/side, min 10 train trades. 19/20 runs finished; donchian_ensemble ETHUSDT 15m missing.
     Buy & hold differs per strategy because longer warm-ups (ema_pullback, donchian_ensemble) shift the OOS window. -->

| Strategy | Symbol | Bars | Signal TF | OOS return % | Buy & hold % | OOS max DD % | OOS trades | Folds | OOS Sharpe (ann.) | DSR | PBO |
|---|---|---|---|---|---|---|---|---|---|---|---|
| donchian_ensemble | BTCUSDT | 15m | 1h | 0.36 | 20.64 | -3.53 | 16 | 18 | 0.27 | 0.06 | 0.79 |
| ema_pullback | BTCUSDT | 15m | 15m | 0.00 | 11.81 | 0.00 | 0 | 19 | 0.00 | n/a | 0.23 |
| opening_range | BTCUSDT | 15m | 15m | -2.30 | 5.63 | -2.38 | 33 | 22 | -2.12 | 0.01 | 0.52 |
| squeeze_breakout | BTCUSDT | 15m | 15m | -7.39 | 5.63 | -7.39 | 64 | 22 | -4.86 | 0.00 | 0.22 |
| vwap_reversion | BTCUSDT | 15m | 15m | 0.00 | 5.63 | 0.00 | 0 | 22 | 0.00 | n/a | 0.00 |
| ema_pullback | ETHUSDT | 15m | 15m | -0.31 | 22.67 | -0.31 | 1 | 19 | -1.66 | 0.00 | 0.47 |
| opening_range | ETHUSDT | 15m | 15m | -1.56 | 13.38 | -2.95 | 47 | 22 | -1.00 | 0.05 | 0.30 |
| squeeze_breakout | ETHUSDT | 15m | 15m | -5.43 | 13.38 | -5.43 | 78 | 22 | -2.54 | 0.02 | 0.88 |
| vwap_reversion | ETHUSDT | 15m | 15m | 0.00 | 13.38 | 0.00 | 0 | 22 | 0.00 | n/a | 0.79 |
| donchian_ensemble | BTCUSDT | 5m | 1h | 0.24 | 20.55 | -3.59 | 16 | 18 | 0.19 | 0.05 | 0.69 |
| ema_pullback | BTCUSDT | 5m | 5m | -1.03 | 11.79 | -1.59 | 12 | 19 | -2.61 | 0.00 | 0.23 |
| opening_range | BTCUSDT | 5m | 5m | -2.69 | 5.82 | -2.88 | 30 | 22 | -3.65 | 0.00 | 0.61 |
| squeeze_breakout | BTCUSDT | 5m | 5m | -5.81 | 5.82 | -5.95 | 96 | 22 | -4.61 | 0.00 | 0.06 |
| vwap_reversion | BTCUSDT | 5m | 5m | 0.00 | 5.82 | 0.00 | 0 | 22 | 0.00 | n/a | 0.80 |
| donchian_ensemble | ETHUSDT | 5m | 1h | -0.98 | 35.19 | -5.02 | 15 | 18 | -0.56 | 0.07 | 0.61 |
| ema_pullback | ETHUSDT | 5m | 5m | -1.93 | 22.60 | -1.93 | 26 | 19 | -3.41 | 0.00 | 0.35 |
| opening_range | ETHUSDT | 5m | 5m | 0.96 | 13.51 | -1.05 | 44 | 22 | 0.96 | 0.45 | 0.25 |
| squeeze_breakout | ETHUSDT | 5m | 5m | -12.50 | 13.51 | -13.24 | 191 | 22 | -5.25 | 0.00 | 0.59 |
| vwap_reversion | ETHUSDT | 5m | 5m | 0.00 | 13.51 | 0.00 | 0 | 22 | 0.00 | n/a | 0.46 |
