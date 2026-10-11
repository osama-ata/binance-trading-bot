# Residual Edge Analysis

**Status:** RESIDUAL_FRAGILE
**Decision eligibility:** ELIGIBLE
**Period:** 2021-06-02 to 2026-10-09 (1956 observations)
**Primary model:** buy_hold_basket

## Primary Model

| Metric | Value |
|---|---:|
| R² | 0.3189 |
| Adjusted R² | 0.3186 |
| Annualized alpha | 9.0283% |
| Alpha HAC t-stat | 1.667 |
| Annualized residual volatility | 12.1218% |
| Residual edge ratio | 0.745 |

## Baseline Loadings

| Baseline | Loading | HAC t-stat | VIF |
|---|---:|---:|---:|
| buy_hold_basket_return | 0.1326 | 9.641 | 1.000 |

## Model Sensitivity

| Model | Role | R² | Annualized alpha | Residual edge ratio | Status |
|---|---|---:|---:|---:|---|
| buy_hold_basket | primary | 0.3189 | 9.0283% | 0.745 | RESIDUAL_FRAGILE |
| btc_buy_hold | sensitivity | 0.2509 | 10.1342% | 0.797 | RESIDUAL_FRAGILE |

## Evidence Warnings

- None.

## Regime Breakdown

### btc_trend_regime

| Regime | N | Evidence | Annualized active return | Active Sharpe |
|---|---:|---|---:|---:|
| bear | 932 | ADEQUATE | 2.5993% | 0.250 |
| bull | 1024 | ADEQUATE | 14.8797% | 1.102 |

## Interpretation

- Residual evidence does not clear all robustness thresholds.
- Rolling alpha is positive in too few windows.
- This report does not authorize a trade or an automatic exposure change.
- Confirm exploratory findings on untouched out-of-sample or live data.
