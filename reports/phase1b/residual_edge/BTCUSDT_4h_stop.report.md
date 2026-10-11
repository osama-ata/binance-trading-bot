# Residual Edge Analysis

**Status:** RESIDUAL_FRAGILE
**Decision eligibility:** REVIEW_REQUIRED
**Period:** 2021-05-09 to 2026-10-09 (1980 observations)
**Primary model:** buy_hold

## Primary Model

| Metric | Value |
|---|---:|
| R² | 0.1153 |
| Adjusted R² | 0.1148 |
| Annualized alpha | 0.5319% |
| Alpha HAC t-stat | 0.382 |
| Annualized residual volatility | 2.7937% |
| Residual edge ratio | 0.190 |

## Baseline Loadings

| Baseline | Loading | HAC t-stat | VIF |
|---|---:|---:|---:|
| buy_hold_return | 0.0185 | 5.404 | 1.000 |

## Model Sensitivity

| Model | Role | R² | Annualized alpha | Residual edge ratio | Status |
|---|---|---:|---:|---:|---|
| buy_hold | primary | 0.1153 | 0.5319% | 0.190 | RESIDUAL_FRAGILE |
| sma200_trend | sensitivity | 0.1161 | 0.5828% | 0.209 | RESIDUAL_FRAGILE |
| buy_hold_plus_sma200 | sensitivity | 0.1386 | 0.4852% | 0.176 | RESIDUAL_FRAGILE |

## Evidence Warnings

- **HIGH — ROLLING_ANALYSIS_INCOMPLETE:** Model buy_hold could not estimate 29 rolling windows.
- **HIGH — ROLLING_ANALYSIS_INCOMPLETE:** Model sma200_trend could not estimate 519 rolling windows.
- **HIGH — ROLLING_ANALYSIS_INCOMPLETE:** Model buy_hold_plus_sma200 could not estimate 933 rolling windows.

## Regime Breakdown

### trend_regime

| Regime | N | Evidence | Annualized active return | Active Sharpe |
|---|---:|---|---:|---:|
| bear | 944 | ADEQUATE | 0.0220% | 0.009 |
| bull | 1036 | ADEQUATE | 0.9966% | 0.323 |

## Interpretation

- 29 rolling windows could not be estimated.
- This report does not authorize a trade or an automatic exposure change.
- Confirm exploratory findings on untouched out-of-sample or live data.
