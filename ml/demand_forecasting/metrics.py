"""Forecast accuracy metrics.

M5 sales are mostly zeros, so percentage errors per day (MAPE) are useless:
dividing by an actual of 0 is undefined. These metrics stay well-defined:

- MAE   mean absolute error, in units.                 mean(|f - y|)
- WAPE  total absolute error / total actual units.      sum(|f - y|) / sum(y)
- Bias  total over/under-forecast / total actual.       sum(f - y) / sum(y)
        (+0.10 means forecasting 10% too much overall)
- RMSSE root mean squared scaled error, per series:     sqrt(mean((f - y)^2) / scale)
        scale = mean squared day-to-day change in that series' own history,
        counted from its first sale (as in the M5 competition). RMSSE < 1 means
        better than the in-sample "same as yesterday" forecast. We report the
        plain average over series, and a sales-value-weighted average
        (weights = each series' dollar sales in the 28 days before the origin),
        which counts high-revenue products more. The competition's WRMSSE also
        averaged 11 higher aggregation levels; we do not, so neither number is
        comparable with the Kaggle leaderboard.
"""

import numpy as np
import pandas as pd


def mae(actual: np.ndarray, forecast: np.ndarray) -> float:
    return float(np.mean(np.abs(forecast - actual)))


def wape(actual: np.ndarray, forecast: np.ndarray) -> float:
    """Raises ValueError if there are no actual sales to compare against."""
    total = float(np.sum(actual))
    if total == 0:
        raise ValueError("WAPE is undefined when total actual sales are 0")
    return float(np.sum(np.abs(forecast - actual)) / total)


def bias(actual: np.ndarray, forecast: np.ndarray) -> float:
    total = float(np.sum(actual))
    if total == 0:
        raise ValueError("Bias is undefined when total actual sales are 0")
    return float(np.sum(forecast - actual) / total)


def rmsse_scales(history: pd.DataFrame) -> pd.Series:
    """Per-series RMSSE scale from a history table with columns id, date, sales.

    Days before a product's first sale are ignored (it was not on the shelf yet).
    Series with no change at all (scale 0) cannot be scaled; they get NaN.
    """
    history = history.sort_values(["id", "date"])
    sold_before = history.groupby("id", observed=True)["sales"].cummax() > 0
    selling = history[sold_before]
    squared_changes = selling.groupby("id", observed=True)["sales"].diff() ** 2
    scales = squared_changes.groupby(selling["id"], observed=True).mean()
    return scales.where(scales > 0)


def rmsse_per_series(results: pd.DataFrame, scales: pd.Series) -> pd.Series:
    """RMSSE of each series (index = id). Series without a valid scale are dropped."""
    squared_error = (results["forecast"] - results["actual"]) ** 2
    mse = squared_error.groupby(results["id"], observed=True).mean()
    return np.sqrt(mse / scales.reindex(mse.index)).dropna()


def mean_rmsse(results: pd.DataFrame, scales: pd.Series) -> tuple[float, int]:
    """Average RMSSE over series. `results` has columns id, actual, forecast.

    Returns (mean RMSSE, number of series used). Series without a valid scale are skipped.
    """
    per_series = rmsse_per_series(results, scales)
    return float(per_series.mean()), int(per_series.size)


def sales_value_weights(history: pd.DataFrame, days: int = 28) -> pd.Series:
    """Weight per series for weighted RMSSE: dollar sales in the last `days` of `history`.

    `history` has columns id, date, sales, sell_price and ends at the forecast origin,
    so no future data is used. Products that sold nothing get weight 0. This is the
    weighting the M5 competition used for its bottom level (product x store); the
    competition then also averaged 11 higher aggregation levels, which we do not.
    """
    start = history["date"].max() - pd.Timedelta(days=days)
    recent = history[history["date"] > start]
    value = recent["sales"] * recent["sell_price"].fillna(0)
    return value.groupby(recent["id"].astype(str), observed=True).sum()


def weighted_rmsse(per_series: pd.Series, weights: pd.Series) -> float:
    """Average of per-series RMSSE weighted by sales value. NaN if all weights are 0."""
    aligned = weights.reindex(per_series.index).fillna(0)
    total = float(aligned.sum())
    if total == 0:
        return float("nan")
    return float((per_series * aligned).sum() / total)
