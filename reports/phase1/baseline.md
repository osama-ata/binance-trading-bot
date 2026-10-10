<!-- Baseline: code at commit 1148706 (before Phase 1) + a guard skipping orders backtesting.py rejects + a results-neutral per-row speed-up; backtesting 0.6.6. Note: that code charged slippage twice per side (spread = 2 x 2 bps). -->
Walk-forward 2026-04-01 → 2026-10-09, train 30d / test 7d, fee 0.1000%/side, slippage 2.0 bps/side, min train trades 10

| Strategy | Symbol | Bars | Signal TF | OOS return % | Buy & hold % | OOS max DD % | OOS trades | Folds |
|---|---|---|---|---|---|---|---|---|
| ema_pullback | BTCUSDT | 5m | 5m | -1.48 | 3.92 | -1.49 | 15 | 21 |
| vwap_reversion | BTCUSDT | 5m | 5m | -0.09 | 8.12 | -0.09 | 1 | 22 |
| squeeze_breakout | BTCUSDT | 5m | 5m | -3.21 | 8.12 | -3.31 | 68 | 22 |
| opening_range | BTCUSDT | 5m | 5m | -6.60 | 8.12 | -6.60 | 104 | 22 |
| ema_pullback | ETHUSDT | 5m | 5m | -0.98 | 11.78 | -1.09 | 25 | 21 |
| vwap_reversion | ETHUSDT | 5m | 5m | 0.00 | 16.56 | 0.00 | 0 | 22 |
| squeeze_breakout | ETHUSDT | 5m | 5m | -10.18 | 16.56 | -10.26 | 180 | 22 |
| opening_range | ETHUSDT | 5m | 5m | -0.42 | 16.56 | -1.65 | 93 | 22 |
| ema_pullback | BTCUSDT | 15m | 15m | -0.14 | 3.98 | -0.14 | 1 | 21 |
| vwap_reversion | BTCUSDT | 15m | 15m | 0.00 | 7.64 | 0.00 | 0 | 22 |
| squeeze_breakout | BTCUSDT | 15m | 15m | -4.09 | 7.64 | -4.15 | 75 | 22 |
| opening_range | BTCUSDT | 15m | 15m | -4.96 | 7.64 | -5.40 | 92 | 22 |
| ema_pullback | ETHUSDT | 15m | 15m | -0.16 | 11.86 | -0.16 | 1 | 21 |
| vwap_reversion | ETHUSDT | 15m | 15m | 0.00 | 14.50 | 0.00 | 0 | 22 |
| squeeze_breakout | ETHUSDT | 15m | 15m | -5.60 | 14.50 | -5.87 | 94 | 22 |
| opening_range | ETHUSDT | 15m | 15m | -3.71 | 14.50 | -4.45 | 97 | 22 |
