"""Tests for calibrated intervals and the model-selection rule."""

import numpy as np
import pandas as pd
import pytest

from demand_forecasting.conformal import ConformalIntervals
from demand_forecasting.model_selection import choose


def noisy_rows(n: int, seed: int) -> pd.DataFrame:
    """Forecasts with errors that grow with the forecast size, like real sales."""
    rng = np.random.default_rng(seed)
    forecast = rng.gamma(1.0, 2.0, n)
    actual = np.clip(forecast + rng.normal(0, 0.5 + forecast, n), 0, None)
    return pd.DataFrame({"forecast": forecast, "actual": actual})


def test_intervals_cover_about_80_percent_of_new_data() -> None:
    intervals = ConformalIntervals.fit(noisy_rows(50_000, seed=1))

    fresh = intervals.apply(noisy_rows(50_000, seed=2))
    inside = (fresh["actual"] >= fresh["lower"]) & (fresh["actual"] <= fresh["upper"])

    assert 0.78 <= inside.mean() <= 0.82


def test_bounds_are_non_negative_contain_the_forecast_and_widen_with_size() -> None:
    intervals = ConformalIntervals.fit(noisy_rows(20_000, seed=3))

    result = intervals.apply(pd.DataFrame({"forecast": [0.05, 8.0]}))

    assert (result["lower"] >= 0).all()
    assert (result["lower"] <= result["forecast"]).all()
    assert (result["forecast"] <= result["upper"]).all()
    widths = (result["upper"] - result["lower"]).tolist()
    assert widths[1] > widths[0]


def test_intervals_survive_a_round_trip_through_plain_data() -> None:
    intervals = ConformalIntervals.fit(noisy_rows(5_000, seed=4))

    copy = ConformalIntervals(**intervals.to_dict())

    rows = noisy_rows(100, seed=5)
    pd.testing.assert_frame_equal(intervals.apply(rows), copy.apply(rows))


def report_with(scores: dict[str, tuple[float, float]]) -> dict:
    """A validation report where each model has the same WAPE/RMSSE at every horizon."""
    return {
        "overall": [
            {
                "model": name,
                "metrics": [
                    {"horizon_days": horizon, "wape": wape, "rmsse": rmsse}
                    for horizon in (7, 14, 28)
                ],
            }
            for name, (wape, rmsse) in scores.items()
        ]
    }


def test_selection_picks_the_lowest_mean_wape() -> None:
    winner, _ = choose(report_with({"a": (0.74, 0.70), "b": (0.72, 0.75)}), ["a", "b"])

    assert winner == "b"


def test_selection_breaks_near_ties_by_rmsse() -> None:
    winner, scores = choose(report_with({"a": (0.7205, 0.70), "b": (0.7200, 0.75)}), ["a", "b"])

    assert winner == "a"  # WAPE within 0.001, so the lower RMSSE wins
    assert scores["b"]["mean_wape"] == pytest.approx(0.72)


def zero_heavy_rows(n: int, seed: int) -> pd.DataFrame:
    """Like M5: most forecasts are exactly 0 (e.g. a moving average of zero sales)."""
    rng = np.random.default_rng(seed)
    forecast = np.where(rng.random(n) < 0.6, 0.0, rng.gamma(1.0, 2.0, n))
    actual = rng.poisson(forecast + 0.05).astype(float)
    return pd.DataFrame({"forecast": forecast, "actual": actual})


def test_many_exact_zero_forecasts_are_handled() -> None:
    # Regression: with right-open bins the zeros left bin 0 empty and fit() crashed.
    intervals = ConformalIntervals.fit(zero_heavy_rows(50_000, seed=6))

    fresh = intervals.apply(zero_heavy_rows(50_000, seed=7))
    inside = (fresh["actual"] >= fresh["lower"]) & (fresh["actual"] <= fresh["upper"])

    assert 0.75 <= inside.mean() <= 0.95  # discrete data: coverage cannot be exactly 80%
    assert (fresh["lower"] >= 0).all()


def test_tiny_bins_fall_back_to_overall_bounds() -> None:
    rows = pd.DataFrame({"forecast": [0.0] * 500 + [5.0] * 5, "actual": [0.0] * 500 + [9.0] * 5})

    intervals = ConformalIntervals.fit(rows)

    # The bin with only 5 rows uses the overall percentiles instead of its own.
    assert intervals.upper_offsets[-1] == pytest.approx(
        float(np.percentile(rows["actual"] - rows["forecast"], 90))
    )
