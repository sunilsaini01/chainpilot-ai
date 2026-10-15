"""Model features built only from information available at forecast time.

Leakage rule: to forecast up to `min_lag` days ahead from an origin, a feature
for date t may only use sales from t - min_lag or earlier. With the default
min_lag = 28, one model can predict all of the next 28 days directly (no
recursive feeding of its own predictions), because every sales-based feature
is at least 28 days old. Calendar and price features are known in advance.

Example for a row dated 2016-03-29 with min_lag = 28:
    lag_28           = sales on 2016-03-01
    rolling_mean_7   = mean of sales 2016-02-24 .. 2016-03-01 (7 days ending at t - 28)
"""

import pandas as pd

DEFAULT_MIN_LAG = 28
LAG_OFFSETS = (0, 7, 14, 28)  # extra days beyond min_lag: lag_28, lag_35, lag_42, lag_56
ROLLING_WINDOWS = (7, 28, 56)


def add_features(long: pd.DataFrame, min_lag: int = DEFAULT_MIN_LAG) -> pd.DataFrame:
    """Add feature columns to a long M5 table (see m5_data.to_long). Returns a new frame."""
    if min_lag < 1:
        raise ValueError("min_lag must be at least 1")
    frame = long.sort_values(["id", "date"]).reset_index(drop=True)
    by_series = frame.groupby("id", observed=True)["sales"]

    # Sales shifted so that row t sees sales from t - min_lag: the newest value allowed.
    allowed = by_series.shift(min_lag)
    for offset in LAG_OFFSETS:
        lag = min_lag + offset
        frame[f"lag_{lag}"] = by_series.shift(lag).astype("float32")

    allowed_by_series = allowed.groupby(frame["id"], observed=True)
    for window in ROLLING_WINDOWS:
        frame[f"rolling_mean_{window}"] = (
            allowed_by_series.rolling(window, min_periods=1).mean().reset_index(level=0, drop=True)
        ).astype("float32")
    frame["rolling_std_28"] = (
        allowed_by_series.rolling(28, min_periods=2).std().reset_index(level=0, drop=True)
    ).astype("float32")

    # Calendar: known in advance.
    frame["month"] = frame["date"].dt.month.astype("int8")
    frame["day_of_month"] = frame["date"].dt.day.astype("int8")
    frame["is_event"] = (frame["event_name_1"].astype(str) != "").astype("int8")

    # Price: set by the retailer in advance. Change against the previous week's price.
    price = frame["sell_price"]
    previous_week_price = frame.groupby("id", observed=True)["sell_price"].shift(7)
    frame["price_change_week"] = (price / previous_week_price - 1).astype("float32")
    return frame


FEATURE_COLUMNS = [
    *(f"lag_{DEFAULT_MIN_LAG + offset}" for offset in LAG_OFFSETS),
    *(f"rolling_mean_{window}" for window in ROLLING_WINDOWS),
    "rolling_std_28",
    "wday",
    "month",
    "day_of_month",
    "is_event",
    "snap",
    "sell_price",
    "price_change_week",
]
