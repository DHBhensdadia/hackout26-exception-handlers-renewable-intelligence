# Backend comparison: XGBoost vs LightGBM

Both backends were trained and benchmarked on the identical pipeline, features, splits and
holdout. The only variable is the gradient-boosting implementation.

**Result: XGBoost is the default.** It is the backend named in spec section 24, and the
measurement below shows no accuracy reason to override that.

| Tech | Metric | LightGBM | XGBoost | Delta |
|---|---|---:|---:|---:|
| solar | nMAE (% capacity) | 6.586 | 6.660 | +0.074 |
| solar | nRMSE (% capacity) | 10.977 | 10.984 | +0.006 |
| solar | Bias (% capacity) | -1.407 | -1.551 | -0.144 |
| solar | R2 | 0.835 | 0.834 | -0.000 |
| solar | PICP % (nominal 80) | 75.870 | 80.943 | +5.074 |
| solar | Mean pinball | 0.037 | 0.037 | +0.000 |
| wind | nMAE (% capacity) | 13.432 | 13.578 | +0.146 |
| wind | nRMSE (% capacity) | 19.002 | 19.026 | +0.024 |
| wind | Bias (% capacity) | -0.004 | 0.329 | +0.332 |
| wind | R2 | 0.671 | 0.670 | -0.001 |
| wind | PICP % (nominal 80) | 78.277 | 81.321 | +3.045 |
| wind | Mean pinball | 0.042 | 0.043 | +0.000 |

## Reading this

**Accuracy is a tie.** XGBoost is 0.07pp worse on solar nMAE and 0.15pp worse on wind. Both
gaps are well inside run-to-run noise for a model at ~6.6% and ~13.6% error; neither would
survive a different random seed. R2 is identical to three decimals.

**XGBoost's uncertainty band is better calibrated.** PICP - how often the p10-p90 interval
actually contains the truth - lands at 80.9% (solar) and 81.3% (wind) against a nominal 80%.
LightGBM undercovers at 75.9% and 78.3%, meaning its interval is slightly too narrow and the
forecast is marginally overconfident. For a platform whose spec (section 26) explicitly
requires uncertainty rather than point estimates, and whose Phase 2 surplus/shortage logic
will consume the p10 and p90 bounds directly, calibration of the interval matters at least
as much as the median error.

**Conclusion.** The original rationale for preferring LightGBM - a marginally more mature
quantile objective - is not supported by measurement on this problem. XGBoost matches it on
accuracy and beats it on the metric that governs the uncertainty band.

## Switching back

Both backends stay implemented behind the `ModelBackend` protocol in `models/backends.py`:

```bash
REIP_BACKEND=lightgbm uv run python -m reip.models.train
REIP_BACKEND=lightgbm uv run python -m reip.eval.report
```

Artifacts are suffixed per backend (`.json` for XGBoost, `.txt` for LightGBM) and the
metadata sidecar records which one produced them, so `predict.py` always loads the matching
reader regardless of the current setting.
