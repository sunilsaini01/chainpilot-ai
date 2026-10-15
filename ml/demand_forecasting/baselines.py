"""Simple benchmark forecasts. Any real model must beat these to be worth using.

Every forecaster has the same shape:
    forecaster(history, horizon) -> DataFrame with columns id, date, forecast
where `history` has columns id, date, sales and ends on the forecast origin
(the last day we are allowed to know), and `horizon` is the number of days ahead.
"""

import numpy as np
import pandas as pd


def _last_days(history: pd.DataFrame, days: int) -> tuple[pd.Index, np.ndarray, pd.Timestamp]:
    """The last `days` values of every series as a (series x days) array."""
    origin = history["date"].max()
    recent = history[history["date"] > origin - pd.Timedelta(days=days)]
    # Plain strings: pivoting a categorical id could add empty rows for unused categories.
    recent = recent.assign(id=recent["id"].astype(str))
    table = recent.pivot(index="id", columns="date", values="sales")
    if table.shape[1] != days or table.isna().any().any():
        raise ValueError(f"every series needs all of its last {days} days of history")
    return table.index, table.to_numpy(dtype=float), origin


def _to_frame(ids: pd.Index, origin: pd.Timestamp, values: np.ndarray) -> pd.DataFrame:
    """Turn a (series x horizon) array into rows of id, date, forecast."""
    horizon = values.shape[1]
    dates = pd.date_range(origin + pd.Timedelta(days=1), periods=horizon, freq="D")
    return pd.DataFrame(
        {
            "id": np.repeat(np.asarray(ids), horizon),
            "date": np.tile(dates, len(ids)),
            "forecast": values.reshape(-1),
        }
    )


def seasonal_naive(history: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Each future day repeats the same weekday from the last 7 days.

    Example: the origin is a Sunday; next Monday gets last Monday's sales,
    the Monday after that gets the same value again.
    """
    ids, last_week, origin = _last_days(history, 7)
    # Day k ahead (k = 1, 2, ...) has the weekday of column (k - 1) % 7 of the last week.
    columns = [(step - 1) % 7 for step in range(1, horizon + 1)]
    return _to_frame(ids, origin, last_week[:, columns])


def moving_average_28(history: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Every future day gets the series' average daily sales of the last 28 days
    (or of all days, if the history is shorter than that)."""
    ids, last_28, origin = _last_days(history, min(28, history["date"].nunique()))
    level = last_28.mean(axis=1, keepdims=True)
    return _to_frame(ids, origin, np.repeat(level, horizon, axis=1))


BASELINES = {"seasonal_naive": seasonal_naive, "moving_average_28": moving_average_28}
