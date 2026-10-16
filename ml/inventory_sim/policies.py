"""Target levels (order-up-to) for each policy at each review (P4-T2 plan).

Every target is computed from information available at the review: sales up to
that day, or a forecast made that day.
"""

import math

import numpy as np
import pandas as pd

# Importable because inventory_sim/__init__.py adds apps/api to the path (D-044).
from app.inventory_policy import order_up_to_level, std_from_interval

LEAD_TIME_DAYS = 7
LEAD_TIME_STD = math.sqrt(2)  # uniform whole days 5..9
REVIEW_DAYS = 7
PROTECTION_DAYS = LEAD_TIME_DAYS + REVIEW_DAYS
BASELINE_BUFFER_DAYS = [0, 3.5, 7, 14]
SERVICE_LEVELS = [0.80, 0.90, 0.95, 0.98]
# std_from_interval is linear in the interval width, so one factor converts all rows.
STD_PER_UNIT_OF_WIDTH = std_from_interval(0, 1)


def baseline_targets(sales_28: np.ndarray, buffer_days: float) -> np.ndarray:
    """Simple reorder rule: the 28-day average times (lead time + review + buffer) days.

    Takes the 28-day sales total (whole units) and divides last, so that an exact
    whole-unit result is not pushed up by float rounding (e.g. 2.0000000001 -> 3).
    Converted to float first: M5 sales are int16, and 1,657 x 28 silently wraps
    around in int16 arithmetic (P4-T2-R1). Whole numbers stay exact in float64.
    """
    return np.ceil(np.asarray(sales_28, dtype=float) * (PROTECTION_DAYS + buffer_days) / 28)


def forecast_inputs(forecast: pd.DataFrame) -> pd.DataFrame:
    """Per item: daily mean and daily std over the protection period.

    `forecast` has one row per item and day for steps 1..14 with forecast, lower
    and upper (80% interval). The daily std is the root mean square of the daily
    stds, so that 14 x std^2 equals the sum of the daily variances.
    """
    steps = forecast.groupby("id", observed=True)["date"].nunique()
    if (steps != PROTECTION_DAYS).any():
        raise ValueError(f"each item needs a forecast for exactly {PROTECTION_DAYS} days")
    daily_std = (forecast["upper"] - forecast["lower"]) * STD_PER_UNIT_OF_WIDTH
    return (
        forecast.assign(variance=daily_std**2)
        .groupby("id", observed=True)
        .agg(daily_mean=("forecast", "mean"), variance=("variance", "mean"))
        .assign(daily_std=lambda frame: np.sqrt(frame["variance"]))[["daily_mean", "daily_std"]]
    )


def formula_targets(inputs: pd.DataFrame, service_level: float) -> pd.Series:
    """ChainPilot policy: `order_up_to_level` from the shared policy module, per item."""
    levels = [
        order_up_to_level(
            mean, std, LEAD_TIME_DAYS, LEAD_TIME_STD, REVIEW_DAYS, service_level
        ).level
        for mean, std in zip(inputs["daily_mean"], inputs["daily_std"], strict=True)
    ]
    return pd.Series(levels, index=inputs.index, dtype=float)
