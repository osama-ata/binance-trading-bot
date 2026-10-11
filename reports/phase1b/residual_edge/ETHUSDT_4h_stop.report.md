# Residual Edge Analysis

**Status:** RESIDUAL_FRAGILE
**Decision eligibility:** REVIEW_REQUIRED
**Period:** 2021-05-09 to 2026-10-09 (1980 observations)
**Primary model:** buy_hold

## Primary Model

| Metric | Value |
|---|---:|
| R² | 0.1719 |
| Adjusted R² | 0.1715 |
| Annualized alpha | 2.1750% |
| Alpha HAC t-stat | 1.430 |
| Annualized residual volatility | 3.5675% |
| Residual edge ratio | 0.610 |

## Baseline Loadings

| Baseline | Loading | HAC t-stat | VIF |
|---|---:|---:|---:|
| buy_hold_return | 0.0221 | 5.864 | 1.000 |

## Model Sensitivity

| Model | Role | R² | Annualized alpha | Residual edge ratio | Status |
|---|---|---:|---:|---:|---|
| buy_hold | primary | 0.1719 | 2.1750% | 0.610 | RESIDUAL_FRAGILE |
| sma200_trend | sensitivity | 0.1253 | 2.0088% | 0.548 | RESIDUAL_FRAGILE |
| buy_hold_plus_sma200 | sensitivity | 0.1804 | 2.0538% | 0.579 | RESIDUAL_FRAGILE |

## Evidence Warnings

- **HIGH — ROLLING_ANALYSIS_INCOMPLETE:** Model buy_hold could not estimate 78 rolling windows.
- **HIGH — ROLLING_ANALYSIS_INCOMPLETE:** Model sma200_trend could not estimate 507 rolling windows.
- **HIGH — ROLLING_ANALYSIS_INCOMPLETE:** Model buy_hold_plus_sma200 could not estimate 846 rolling windows.

## Regime Breakdown

### trend_regime

| Regime | N | Evidence | Annualized active return | Active Sharpe |
|---|---:|---|---:|---:|
| bear | 990 | ADEQUATE | 2.0291% | 0.650 |
| bull | 990 | ADEQUATE | 2.3209% | 0.586 |

## Interpretation

- 78 rolling windows could not be estimated.
- This report does not authorize a trade or an automatic exposure change.
- Confirm exploratory findings on untouched out-of-sample or live data.
