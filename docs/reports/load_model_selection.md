# Load model selection (validation year only)

Validation period 2024-11-01 → 2025-10-31. The test year was not used.

Variants differ only in the GBM target: absolute MW, or the ratio to a level known at issue time.

| model | mae_mw | rmse_mw | bias_mw | pinball_mean_mw | coverage_90 | skill_vs_tso |
|---|---|---|---|---|---|---|
| gbm_ratio_recent24h_temp_only | 1,468 | 2,009 | -195 | 476 | 0.886 | +31.2% |
| gbm_ratio_recent24h | 1,697 | 2,466 | -525 | 553 | 0.886 | +20.4% |
| gbm_absolute | 1,794 | 2,646 | -489 | 603 | 0.878 | +15.9% |
| gbm_ratio_lag_d7 | 1,833 | 2,543 | -467 | 599 | 0.883 | +14.1% |
| tso_official | 2,133 | 2,689 | -12 | — | — | +0.0% |

Selection rule (fixed before running): lowest mean pinball loss; ties broken by MAE.
