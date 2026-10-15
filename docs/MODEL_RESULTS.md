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
- Code: `a5ad708-dirty`, i.e. commit a5ad708 plus the uncommitted P2-T2 code, committed right after this run.
- Python 3.11.9, pandas 3.0.6, numpy 2.4.6. Runtime 133 s on a 16 GB Windows laptop.
- Data SHA-256: calendar `d12b5914…60f5`, sales `f368e66e…6724`, prices `9da3ad1f…d2ef` (full values in the JSON).

**Reproduce**

```powershell
cd ml
python -m demand_forecasting.backtest ..\data\raw\m5 --all-stores --horizon 28 --origins 3 --output ..\docs\results\p2_baselines.json
```

One value was checked independently: seasonal-naive WAPE for store CA_1, origin 2016-03-27, 28 days, recomputed with plain pandas straight from the CSV files gave 0.8876, and the backtest gives 0.888.
