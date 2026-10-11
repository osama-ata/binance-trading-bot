# Residual Edge Analysis

**Status:** RESIDUAL_FRAGILE
**Decision eligibility:** REVIEW_REQUIRED
**Period:** 2021-05-09 to 2026-10-09 (1980 observations)
**Primary model:** buy_hold

## Primary Model

| Metric | Value |
|---|---:|
| R² | 0.1276 |
| Adjusted R² | 0.1271 |
| Annualized alpha | 3.2923% |
| Alpha HAC t-stat | 0.593 |
| Annualized residual volatility | 11.6730% |
| Residual edge ratio | 0.282 |

## Baseline Loadings

| Baseline | Loading | HAC t-stat | VIF |
|---|---:|---:|---:|
| buy_hold_return | 0.0820 | 5.872 | 1.000 |

## Model Sensitivity

| Model | Role | R² | Annualized alpha | Residual edge ratio | Status |
|---|---|---:|---:|---:|---|
| buy_hold | primary | 0.1276 | 3.2923% | 0.282 | RESIDUAL_FRAGILE |
| sma200_trend | sensitivity | 0.1373 | 3.4671% | 0.299 | RESIDUAL_FRAGILE |
| buy_hold_plus_sma200 | sensitivity | 0.1589 | 3.0645% | 0.267 | RESIDUAL_FRAGILE |

## Evidence Warnings

- **HIGH — ROLLING_ANALYSIS_INCOMPLETE:** Model buy_hold could not estimate 29 rolling windows.
- **HIGH — ROLLING_ANALYSIS_INCOMPLETE:** Model sma200_trend could not estimate 519 rolling windows.
- **HIGH — ROLLING_ANALYSIS_INCOMPLETE:** Model buy_hold_plus_sma200 could not estimate 933 rolling windows.

## Regime Breakdown

### trend_regime

| Regime | N | Evidence | Annualized active return | Active Sharpe |
|---|---:|---|---:|---:|
| bear | 944 | ADEQUATE | 1.0048% | 0.105 |
| bull | 1036 | ADEQUATE | 5.3766% | 0.405 |

## Interpretation

- 29 rolling windows could not be estimated.
- This report does not authorize a trade or an automatic exposure change.
- Confirm exploratory findings on untouched out-of-sample or live data.
