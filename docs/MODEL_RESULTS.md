# Model Results

Every number here comes from an actual run, and the full report is saved in `docs/results/`. Nothing is estimated or copied from elsewhere.

## Demand forecasting: baselines (P2-T2)

**Data:** M5 `sales_train_validation.csv`, all 10 stores, 30,490 product × store series, daily unit sales.
**Method:** rolling-origin backtest with 3 forecast origins, 28 days ahead each, scored on the first 7, 14 and 28 days. Each forecaster sees only sales up to its origin.

| Origin (last known day) | Test window |
|---|---|
| 2016-01-31 | 2016-02-01 to 2016-02-28 |
| 2016-02-28 | 2016-02-29 to 2016-03-27 |
| 2016-03-27 | 2016-03-28 to 2016-04-24 |

**Results** (pooled over all stores and origins; lower is better, bias closest to 0 is best):

| Model | Horizon | MAE (units/day) | WAPE | Bias | RMSSE |
|---|---|---|---|---|---|
| Seasonal naive (same weekday last week) | 7 days | 1.186 | 0.856 | −0.065 | 0.890 |
| Seasonal naive | 14 days | 1.211 | 0.860 | −0.079 | 0.934 |
| Seasonal naive | 28 days | 1.214 | 0.880 | −0.061 | 0.958 |
| **Moving average, last 28 days** | 7 days | **1.020** | **0.736** | −0.030 | **0.675** |
| **Moving average, last 28 days** | 14 days | **1.037** | **0.737** | −0.044 | **0.714** |
| **Moving average, last 28 days** | 28 days | **1.040** | **0.753** | **−0.025** | **0.736** |

WAPE at 28 days, by store (seasonal naive / moving average): CA_1 0.877 / 0.748, CA_2 0.932 / 0.787, CA_3 0.805 / 0.672, CA_4 1.067 / 0.894, TX_1 0.908 / 0.792, TX_2 0.871 / 0.744, TX_3 0.874 / 0.750, WI_1 0.931 / 0.790, WI_2 0.826 / 0.724, WI_3 0.839 / 0.748.

**How to read this**
- **WAPE 0.753:** the absolute daily errors add up to 75% of the units actually sold. That sounds high, but it is normal at the level of one product in one store on one day, where 64% of days have zero sales (store CA_1). Errors shrink a lot when sales are added up (weekly, per category). That is a later reporting choice.
- **The 28-day average beats "same weekday last week"** in every store and at every horizon. One week of history is too noisy for single items; averaging four weeks smooths out chance spikes. The moving average is the benchmark the tree model (P2-T3) must beat.
- **Bias is slightly negative** (−2.5% to −8%): both baselines under-forecast a little. Sales were growing over time, and promotions or events raise demand above recent history.
- **RMSSE < 1** means better than the in-sample "same as yesterday" forecast.

**Caveats (so the numbers are not misused)**
- RMSSE here is the **plain average over series**, not the M5 competition's dollar-weighted, hierarchy-aggregated WRMSSE. These numbers are **not comparable** with the Kaggle leaderboard.
- Ten (origin, series) pairs had no sales change before their origin, so RMSSE cannot be scaled for them; they were left out of RMSSE only (91,460 of 91,470 pairs used).
- The three windows are February to April 2016. Results for other seasons (e.g. December) may differ.

**Provenance** (from `docs/results/p2_baselines.json`)
- Code: commit `0c32413` (clean). The first run used `a5ad708-dirty`; a re-run from a clean checkout of `0c32413` on 2026-10-16 gave identical numbers, and this report is that re-run.
- Python 3.11.9, pandas 3.0.6, numpy 2.4.6. Runtime about 133 s on a 16 GB Windows laptop (first run).
- Data SHA-256: calendar `d12b5914…60f5`, sales `f368e66e…6724`, prices `9da3ad1f…d2ef` (full values in the JSON).

**Reproduce**

```powershell
cd ml
python -m demand_forecasting.backtest ..\data\raw\m5 --all-stores --horizon 28 --origins 3 --output ..\docs\results\p2_baselines.json
```

One value was checked independently: seasonal-naive WAPE for store CA_1, origin 2016-03-27, 28 days, recomputed with plain pandas straight from the CSV files gave 0.8876, and the backtest gives 0.888.

## Demand forecasting: LightGBM (P2-T3)

**Same data, origins and test windows as the baselines above**, and the same run, so all three models are compared on identical rows. One LightGBM model per store per origin, trained on the 730 days up to the origin; Tweedie objective for the point forecast, plus 10th and 90th percentile models for an 80% interval. Settings were fixed before running and **not tuned on these test windows**.

| Model | Horizon | MAE | WAPE | Bias | RMSSE | 80% interval coverage | Interval width |
|---|---|---|---|---|---|---|---|
| Seasonal naive | 7 days | 1.186 | 0.856 | -0.065 | 0.890 | – | – |
| Seasonal naive | 14 days | 1.211 | 0.860 | -0.079 | 0.934 | – | – |
| Seasonal naive | 28 days | 1.214 | 0.880 | -0.061 | 0.958 | – | – |
| Moving average, 28 days | 7 days | 1.020 | 0.736 | -0.030 | 0.675 | – | – |
| Moving average, 28 days | 14 days | 1.037 | 0.737 | -0.044 | 0.714 | – | – |
| Moving average, 28 days | 28 days | 1.040 | 0.753 | -0.025 | 0.736 | – | – |
| LightGBM (Tweedie) | 7 days | 1.044 | 0.753 | -0.035 | 0.684 | 0.873 | 2.99 |
| LightGBM (Tweedie) | 14 days | 1.056 | 0.751 | -0.044 | 0.720 | 0.870 | 3.00 |
| LightGBM (Tweedie) | 28 days | 1.042 | 0.755 | -0.050 | 0.736 | 0.870 | 2.97 |

WAPE at 28 days by store (moving average / LightGBM; ✓ = LightGBM better): CA_1 0.7483 / 0.7477 ✓ (a hair), CA_2 0.787 / 0.773 ✓, CA_3 0.672 / 0.671 ✓, CA_4 0.894 / 0.904, TX_1 0.792 / 0.811, TX_2 0.744 / 0.750, TX_3 0.750 / 0.774, WI_1 0.790 / 0.778 ✓, WI_2 0.724 / 0.718 ✓, WI_3 0.748 / 0.750.

**Honest reading**
- **LightGBM does not beat the 28-day moving average** overall: at 28 days it ties (WAPE 0.755 vs 0.753, RMSSE 0.736 both), and at 7 and 14 days it is slightly worse (WAPE 0.753 vs 0.736). It is better in 5 of 10 stores at 28 days.
- **Likely cause (a design choice, not a bug):** every sales-based feature is at least 28 days old, so that one model can forecast all 28 days without feeding back its own predictions. For the first forecast days, the model therefore works from sales 4 to 8 weeks old, while the moving average uses the last 28 days. The standard remedy is one model per forecast week (lags of at least 7, 14, 21, 28 days), chosen on a separate validation period before these test windows, so the test results stay unbiased. See review item P2-T3-R1.
- **The 80% interval is too wide:** it contains the actual value 87% of the time instead of 80%. The 10th-percentile model is usually 0 on these zero-heavy series, so the interval almost always includes the many zero-sales days. A calibration step (e.g. conformal adjustment on a validation window) would fix this (P2-T3-R2).
- Bias −5%: like the baselines, it slightly under-forecasts.

**Provenance** (`docs/results/p2_lightgbm.json`): code `f5601f9-dirty` (commit f5601f9 plus the uncommitted P2-T3 code, committed right after this run), LightGBM 4.7.0, settings in the JSON, same data checksums as above. Runtime 1,382 s (23 min) for 30 store-origin trainings of 3 models each.

**Reproduce**

```powershell
cd ml
python -m demand_forecasting.backtest ..\data\raw\m5 --all-stores --horizon 28 --origins 3 --with-lightgbm --output ..\docs\results\p2_lightgbm.json
python -m demand_forecasting.train_final ..\data\raw\m5 --store CA_1      # final model -> ml/artifacts/CA_1/
```

The final CA_1 model (trained 2014-04-26 to 2016-04-24, 2,187,494 rows, 40.5 s) was saved and reloaded, and it predicts real feature rows with ordered intervals. Model files are not in Git.

## Demand forecasting: improved model, chosen on a validation period (P2-T3b)

The plan below was written in `docs/CLAUDE_WORK_LOG.md` **before** any of these numbers existed, so the test result could not influence the choice.

1. **Validation period** (all 10 stores), entirely before the test windows: origins 2015-11-08, 2015-12-06, 2016-01-03; windows 2015-11-09 to 2016-01-31.
2. **Candidates** (same fixed settings as P2-T3, point forecasts): LightGBM single model (all sales features ≥ 28 days old) and LightGBM **weekly models** (one model per forecast week, with sales features ≥ 7, 14, 21 and 28 days old). Reference: 28-day moving average.
3. **Selection rule:** lowest mean WAPE over 7/14/28 days on validation (ties within 0.001 broken by RMSSE).
4. **80% intervals:** conformal calibration from each model's validation errors, in 10 bins by forecast size (2,561,160 validation rows), replacing the quantile models of P2-T3.
5. **Test:** the chosen model and the moving average, **once**, on the same test windows as before.

**Validation** (Nov 2015 – Jan 2016):

| Model | Horizon | MAE | WAPE | Bias | RMSSE |
|---|---|---|---|---|---|
| Moving average, 28 days | 7 days | 0.982 | 0.775 | -0.038 | 0.636 |
| Moving average, 28 days | 14 days | 0.984 | 0.782 | -0.031 | 0.665 |
| Moving average, 28 days | 28 days | 1.000 | 0.817 | -0.003 | 0.689 |
| LightGBM, single model | 7 days | 0.998 | 0.787 | -0.007 | 0.646 |
| LightGBM, single model | 14 days | 0.989 | 0.786 | -0.017 | 0.672 |
| LightGBM, single model | 28 days | 0.978 | 0.800 | -0.025 | 0.686 |
| LightGBM, weekly models | 7 days | 0.954 | 0.752 | -0.005 | 0.628 |
| LightGBM, weekly models | 14 days | 0.955 | 0.759 | -0.017 | 0.658 |
| LightGBM, weekly models | 28 days | 0.958 | 0.784 | -0.026 | 0.678 |

Mean WAPE over 7/14/28 days: single 0.7910, weekly 0.7651. **Chosen: weekly models.**

**Test** (Feb – Apr 2016, the same windows as the earlier tables):

| Model | Horizon | MAE | WAPE | Bias | RMSSE | 80% interval coverage | Interval width |
|---|---|---|---|---|---|---|---|
| Moving average, 28 days | 7 days | 1.020 | 0.736 | -0.030 | 0.675 | 0.868 | 2.64 |
| Moving average, 28 days | 14 days | 1.037 | 0.737 | -0.044 | 0.714 | 0.863 | 2.64 |
| Moving average, 28 days | 28 days | 1.040 | 0.753 | -0.025 | 0.736 | 0.861 | 2.64 |
| LightGBM, weekly models | 7 days | 0.996 | 0.718 | -0.010 | 0.665 | 0.809 | 2.71 |
| LightGBM, weekly models | 14 days | 1.020 | 0.725 | -0.023 | 0.705 | 0.804 | 2.72 |
| LightGBM, weekly models | 28 days | 1.022 | 0.740 | -0.038 | 0.728 | 0.799 | 2.68 |

WAPE at 28 days by store (moving average / weekly LightGBM; ✓ = LightGBM better): CA_1 0.7483 / 0.7349 ✓, CA_2 0.7874 / 0.7611 ✓, CA_3 0.6718 / 0.6595 ✓, CA_4 0.8943 / 0.8941 ✓, TX_1 0.7920 / 0.7952, TX_2 0.7444 / 0.7366 ✓, TX_3 0.7503 / 0.7530, WI_1 0.7899 / 0.7662 ✓, WI_2 0.7240 / 0.6999 ✓, WI_3 0.7483 / 0.7295 ✓.

**Reading**
- **The weekly LightGBM beats the 28-day moving average at every horizon**: WAPE 0.718 / 0.725 / 0.740 vs 0.736 / 0.737 / 0.753 at 7 / 14 / 28 days (about 2% lower), RMSSE also lower, better in 8 of 10 stores at 28 days (CA_4 only by a hair, effectively a tie; TX_1 and TX_3 slightly worse). The gain is real but modest; item-level daily demand is very noisy.
- The improvement over the first LightGBM version comes from letting the model for next week use last week's sales (the cause identified in P2-T3).
- **Intervals are now calibrated:** coverage 0.799–0.809 for the weekly model (target 0.80; per store 0.789–0.809), about as wide as the moving average's intervals, which over-cover (0.86). The old quantile intervals covered 0.87.
- **Bias:** closer to 0 than the moving average at 7 and 14 days (−1.0%, −2.3%), slightly further at 28 days (−3.8% vs −2.5%).
- The moving average's test numbers are identical to the earlier runs (a consistency check).
- Same caveats as above: unweighted RMSSE (not comparable with the Kaggle leaderboard); test windows cover February–April only.

**Provenance** (`docs/results/p2_model_selection.json`): commit `0c32413` (clean), LightGBM 4.7.0, same data checksums as above. The results were first produced from `7ead45b-dirty` (93 min); a re-run from a clean checkout of `0c32413` gave identical validation and test metrics, intervals and choice (runtime 114 min, slower because other work ran at the same time), and this report is that re-run. An earlier run of the same plan crashed in the calibration step before showing any numbers (see the work log).

**Reproduce**

```powershell
cd ml
python -m demand_forecasting.model_selection ..\data\raw\m5 --all-stores --output ..\docs\results\p2_model_selection.json
python -m demand_forecasting.train_final ..\data\raw\m5 --all-stores --weekly --selection-report ..\docs\results\p2_model_selection.json
```

## Final check on untouched data: the published forecasts (P2-T4)

The published forecast file (`m5_lightgbm_weekly_2016-04-24`, 853,720 rows) covers 2016-04-25 to 2016-05-22, the 28 days after the training data ends. The M5 download also contains `sales_train_evaluation.csv` with the **real sales of exactly those days**. No training, validation, test or model-choice step ever read it, so this is a genuinely unseen check, done once after everything else was fixed. Result saved in `docs/results/p2_holdout.json`.

| Horizon | WAPE weekly LightGBM | WAPE moving average | Bias LightGBM | Bias moving average | RMSSE LightGBM | RMSSE moving average | Weighted RMSSE LightGBM | Weighted RMSSE moving average | 80% interval coverage |
|---|---|---|---|---|---|---|---|---|---|
| 7 days | **0.711** | 0.747 | -0.061 | +0.021 | **0.670** | 0.682 | **0.758** | 0.816 | 0.806 |
| 14 days | **0.717** | 0.738 | -0.050 | -0.016 | **0.717** | 0.726 | **0.805** | 0.839 | 0.801 |
| 28 days | **0.717** | 0.739 | -0.077 | -0.039 | **0.755** | 0.767 | **0.834** | 0.868 | 0.796 |

- **The improvement holds on unseen data**, slightly larger than in the test windows: WAPE about 3–5% lower than the moving average.
- **Weighted RMSSE** (each series weighted by its dollar sales in the 28 days before the forecast) shows a bigger gap (0.834 vs 0.868 at 28 days): the model helps most on the high-revenue products, which matter most for inventory.
- **Intervals stay calibrated:** 79.6–80.6% coverage for a nominal 80%.
- **Watch-out: bias.** The model under-forecasts by 5–8% here (the moving average by −4% to +2%). For replenishment, under-forecasting means too little stock, so P4 should add a safety-stock buffer (or a bias correction checked on validation data) rather than use the point forecast directly. See review item P2-T4-R1.

Reproduce: `python -m demand_forecasting.holdout ..\data\raw\m5 ..\data\processed\forecasts\m5_lightgbm_weekly_2016-04-24 --output ..\docs\results\p2_holdout.json`
