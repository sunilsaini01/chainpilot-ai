"""Calibrated 80% forecast intervals from past errors (split-conformal method).

Idea: run the model on a validation period, look at its real errors
(actual - forecast), and use their 10th and 90th percentiles as the interval
bounds. If the future behaves like the validation period, about 80% of actuals
fall inside, whatever the model is.

Errors are larger for products that sell more, so they are grouped into bins
by forecast size, and each bin gets its own bounds. Example: for forecasts
around 5 units the errors might range from -3 to +4, giving [2, 9]; for
forecasts near 0.1 they might range from -0.1 to +1, giving [0, 1.1].
"""

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

LOWER_PERCENTILE, UPPER_PERCENTILE = 10, 90  # -> an 80% interval
MIN_ROWS_PER_BIN = 100


@dataclass
class ConformalIntervals:
    bin_edges: list[float]  # inner edges between forecast-size bins
    lower_offsets: list[float]  # 10th percentile of (actual - forecast) per bin
    upper_offsets: list[float]  # 90th percentile per bin
    calibration_rows: int

    @classmethod
    def fit(cls, results: pd.DataFrame, n_bins: int = 10) -> "ConformalIntervals":
        """Learn the bounds from validation rows with columns actual and forecast."""
        forecast = results["forecast"].to_numpy(dtype=float)
        error = results["actual"].to_numpy(dtype=float) - forecast
        # Bin edges at forecast quantiles, so each bin holds a similar number of rows.
        # Many forecasts are exactly 0, so several quantiles can be equal; np.unique
        # removes the duplicates.
        edges = np.unique(np.quantile(forecast, np.linspace(0, 1, n_bins + 1)[1:-1]))
        bins = _bin_of(forecast, edges)
        overall = (
            float(np.percentile(error, LOWER_PERCENTILE)),
            float(np.percentile(error, UPPER_PERCENTILE)),
        )
        lower, upper = [], []
        for b in range(len(edges) + 1):
            errors = error[bins == b]
            # A bin with too few rows gives unreliable percentiles: use the overall ones.
            if errors.size < MIN_ROWS_PER_BIN:
                lower.append(overall[0])
                upper.append(overall[1])
            else:
                lower.append(float(np.percentile(errors, LOWER_PERCENTILE)))
                upper.append(float(np.percentile(errors, UPPER_PERCENTILE)))
        return cls(edges.tolist(), lower, upper, len(results))

    def apply(self, forecast: pd.DataFrame) -> pd.DataFrame:
        """Add lower and upper columns: never negative, and always containing the forecast."""
        values = forecast["forecast"].to_numpy(dtype=float)
        bins = _bin_of(values, np.asarray(self.bin_edges))
        lower = values + np.asarray(self.lower_offsets)[bins]
        upper = values + np.asarray(self.upper_offsets)[bins]
        return forecast.assign(
            lower=np.clip(np.minimum(lower, values), 0, None),
            upper=np.maximum(upper, values),
        )

    def to_dict(self) -> dict:
        return asdict(self)


def _bin_of(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Bin number per value. right=True makes a value equal to an edge fall into the
    lower bin, so when the lowest edge is 0 the many exact-zero forecasts share bin 0
    (with right=False bin 0 would be empty and the zeros would join bin 1)."""
    return np.digitize(values, edges, right=True)
