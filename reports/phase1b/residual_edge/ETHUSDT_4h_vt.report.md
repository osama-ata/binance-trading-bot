# Residual Edge Analysis

**Status:** RESIDUAL_FRAGILE
**Decision eligibility:** REVIEW_REQUIRED
**Period:** 2021-05-09 to 2026-10-09 (1980 observations)
**Primary model:** buy_hold

## Primary Model

| Metric | Value |
|---|---:|
| R² | 0.1740 |
| Adjusted R² | 0.1736 |
| Annualized alpha | 8.6112% |
| Alpha HAC t-stat | 1.467 |
| Annualized residual volatility | 13.6133% |
| Residual edge ratio | 0.633 |

## Baseline Loadings

| Baseline | Loading | HAC t-stat | VIF |
|---|---:|---:|---:|
| buy_hold_return | 0.0848 | 6.230 | 1.000 |

## Model Sensitivity

| Model | Role | R² | Annualized alpha | Residual edge ratio | Status |
|---|---|---:|---:|---:|---|
| buy_hold | primary | 0.1740 | 8.6112% | 0.633 | RESIDUAL_FRAGILE |
| sma200_trend | sensitivity | 0.1330 | 7.9183% | 0.568 | RESIDUAL_FRAGILE |
| buy_hold_plus_sma200 | sensitivity | 0.1849 | 8.0853% | 0.598 | RESIDUAL_FRAGILE |

## Evidence Warnings

- **HIGH — ROLLING_ANALYSIS_INCOMPLETE:** Model buy_hold could not estimate 77 rolling windows.
- **HIGH — ROLLING_ANALYSIS_INCOMPLETE:** Model sma200_trend could not estimate 506 rolling windows.
- **HIGH — ROLLING_ANALYSIS_INCOMPLETE:** Model buy_hold_plus_sma200 could not estimate 845 rolling windows.

## Regime Breakdown

### trend_regime

| Regime | N | Evidence | Annualized active return | Active Sharpe |
|---|---:|---|---:|---:|
| bear | 990 | ADEQUATE | 8.8697% | 0.779 |
| bull | 990 | ADEQUATE | 8.3527% | 0.538 |

## Interpretation

- 77 rolling windows could not be estimated.
- This report does not authorize a trade or an automatic exposure change.
- Confirm exploratory findings on untouched out-of-sample or live data.
