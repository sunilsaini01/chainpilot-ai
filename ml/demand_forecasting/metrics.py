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
        plain average over series; the competition weighted it by dollar sales.
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


def mean_rmsse(results: pd.DataFrame, scales: pd.Series) -> tuple[float, int]:
    """Average RMSSE over series. `results` has columns id, actual, forecast.

    Returns (mean RMSSE, number of series used). Series without a valid scale are skipped.
    """
    squared_error = (results["forecast"] - results["actual"]) ** 2
    mse = squared_error.groupby(results["id"], observed=True).mean()
    per_series = np.sqrt(mse / scales.reindex(mse.index))
    per_series = per_series.dropna()
    return float(per_series.mean()), int(per_series.size)
