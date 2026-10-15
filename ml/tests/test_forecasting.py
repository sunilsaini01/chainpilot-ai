"""Tests for metrics, baselines, rolling-origin backtests and leakage-safe features."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from demand_forecasting import backtest
from demand_forecasting.backtest import make_origins, run_backtest, scales_for, score
from demand_forecasting.baselines import moving_average_28, seasonal_naive
from demand_forecasting.features import FEATURE_COLUMNS, add_features
from demand_forecasting.metrics import bias, mae, mean_rmsse, rmsse_scales, wape

FIXTURES = Path(__file__).parent / "fixtures" / "m5_tiny"
START = pd.Timestamp("2016-01-02")  # a Saturday


def make_series(values_by_id: dict[str, list[float]]) -> pd.DataFrame:
    """A small id/date/sales table starting on START."""
    frames = [
        pd.DataFrame(
            {
                "id": series_id,
                "date": pd.date_range(START, periods=len(values), freq="D"),
                "sales": values,
            }
        )
        for series_id, values in values_by_id.items()
    ]
    return pd.concat(frames, ignore_index=True)


# --- Metrics -------------------------------------------------------------------


def test_point_metrics_by_hand() -> None:
    actual = np.array([2.0, 0.0, 4.0])
    forecast = np.array([3.0, 1.0, 2.0])  # errors +1, +1, -2

    assert mae(actual, forecast) == pytest.approx(4 / 3)
    assert wape(actual, forecast) == pytest.approx(4 / 6)
    assert bias(actual, forecast) == pytest.approx(0 / 6)


def test_wape_and_bias_refuse_all_zero_actuals() -> None:
    with pytest.raises(ValueError, match="undefined"):
        wape(np.zeros(3), np.ones(3))
    with pytest.raises(ValueError, match="undefined"):
        bias(np.zeros(3), np.ones(3))


def test_rmsse_scale_ignores_days_before_first_sale() -> None:
    # Not on the shelf for 3 days, then sales 2, 4, 2: changes 2 and -2, mean square 4.
    scales = rmsse_scales(make_series({"a": [0, 0, 0, 2, 4, 2], "flat": [3, 3, 3, 3, 3, 3]}))

    assert scales["a"] == pytest.approx(4.0)
    assert np.isnan(scales["flat"])  # no change at all: cannot be scaled


def test_mean_rmsse_by_hand_and_skips_unscalable_series() -> None:
    results = pd.DataFrame(
        {"id": ["a", "a", "flat"], "actual": [1.0, 3.0, 3.0], "forecast": [3.0, 3.0, 9.0]}
    )
    scales = pd.Series({"a": 4.0, "flat": np.nan})

    value, count = mean_rmsse(results, scales)

    # Series a: mean squared error (4 + 0) / 2 = 2, divided by 4, square root.
    assert value == pytest.approx(np.sqrt(0.5))
    assert count == 1


# --- Baselines -----------------------------------------------------------------


def test_seasonal_naive_repeats_the_last_week() -> None:
    week = [1, 2, 3, 4, 5, 6, 7]
    history = make_series({"a": [0] * 7 + week})

    forecast = seasonal_naive(history, horizon=10)

    assert forecast["forecast"].tolist() == week + week[:3]
    assert forecast["date"].min() == history["date"].max() + pd.Timedelta(days=1)
    # Same weekday as the copied day.
    assert (forecast["date"].dt.dayofweek.tolist()) == [
        (START + pd.Timedelta(days=7 + k % 7)).dayofweek for k in range(10)
    ]


def test_moving_average_uses_last_28_days() -> None:
    history = make_series({"a": [100] * 10 + [2] * 28})

    forecast = moving_average_28(history, horizon=3)

    assert forecast["forecast"].tolist() == [2.0, 2.0, 2.0]


def test_seasonal_naive_needs_a_full_week() -> None:
    with pytest.raises(ValueError, match="last 7 days"):
        seasonal_naive(make_series({"a": [1, 2, 3]}), horizon=7)


# --- Backtest ------------------------------------------------------------------


def test_origins_are_spaced_one_horizon_apart_and_end_at_the_last_date() -> None:
    last = pd.Timestamp("2016-04-24")

    origins = make_origins(last, horizon=28, n_origins=3)

    assert [o.date().isoformat() for o in origins] == ["2016-01-31", "2016-02-28", "2016-03-27"]


def test_forecaster_never_sees_the_test_window() -> None:
    series = make_series({"a": list(range(60)), "b": list(range(60, 120))})
    origins = make_origins(series["date"].max(), horizon=7, n_origins=3)
    seen_until = []

    def spy(history: pd.DataFrame, horizon: int) -> pd.DataFrame:
        seen_until.append(history["date"].max())
        return seasonal_naive(history, horizon)

    run_backtest(series, spy, origins, horizon=7)

    assert seen_until == origins


def test_perfect_forecaster_scores_zero_error() -> None:
    series = make_series({"a": [1, 0, 3, 2, 5, 1, 4] * 8, "b": [2, 2, 0, 1, 3, 0, 1] * 8})
    origins = make_origins(series["date"].max(), horizon=7, n_origins=2)

    def oracle(history: pd.DataFrame, horizon: int) -> pd.DataFrame:
        origin = history["date"].max()
        future = series[
            (series["date"] > origin) & (series["date"] <= origin + pd.Timedelta(days=horizon))
        ]
        return future.rename(columns={"sales": "forecast"})

    results = run_backtest(series, oracle, origins, horizon=7)
    metrics = score(results, scales_for(series, origins))

    assert metrics == [
        {
            "horizon_days": 7,
            "mae": 0.0,
            "wape": 0.0,
            "bias": 0.0,
            "rmsse": 0.0,
            "rmsse_series": 4,
            "actual_units": int(results["actual"].sum()),
        }
    ]


def test_forecast_outside_the_test_window_is_rejected() -> None:
    series = make_series({"a": list(range(30))})
    origins = make_origins(series["date"].max(), horizon=7, n_origins=1)

    def cheater(history: pd.DataFrame, horizon: int) -> pd.DataFrame:
        forecast = seasonal_naive(history, horizon)
        forecast["date"] -= pd.Timedelta(days=1)  # includes the origin day itself
        return forecast

    with pytest.raises(ValueError, match="outside the test window"):
        run_backtest(series, cheater, origins, horizon=7)


def test_rmsse_scale_uses_only_history_up_to_each_origin() -> None:
    # Calm history, then wild jumps only in the test window.
    series = make_series({"a": [2, 4] * 14 + [0, 100] * 7})
    origin = make_origins(series["date"].max(), horizon=14, n_origins=1)[0]

    scale = scales_for(series, [origin])[origin]["a"]

    assert scale == pytest.approx(4.0)  # from the calm part only


def test_scores_for_7_14_28_day_windows() -> None:
    series = make_series({"a": [3, 1, 4, 1, 5, 9, 2] * 12, "b": [1, 1, 2, 3, 5, 8, 1] * 12})
    origins = make_origins(series["date"].max(), horizon=28, n_origins=2)

    results = run_backtest(series, seasonal_naive, origins, horizon=28)
    metrics = score(results, scales_for(series, origins))

    assert [row["horizon_days"] for row in metrics] == [7, 14, 28]
    # A perfectly weekly pattern is predicted exactly by the seasonal naive baseline.
    assert all(row["wape"] == 0.0 for row in metrics)


def test_command_line_on_fixtures(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "report.json"

    code = backtest.main(
        [
            str(FIXTURES),
            "--store",
            "CA_1",
            "--horizon",
            "7",
            "--origins",
            "2",
            "--output",
            str(output),
        ]
    )

    assert code == 0
    printed = capsys.readouterr().out
    assert "seasonal_naive" in printed and "moving_average_28" in printed
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["origins"] == ["2011-02-04", "2011-02-11"]
    assert report["test_windows"][-1] == ["2011-02-12", "2011-02-18"]
    assert set(report["provenance"]["data_sha256"]) == {"calendar", "sales", "prices"}
    assert report["overall"][0]["metrics"][0]["horizon_days"] == 7


def test_command_line_reports_too_many_origins(capsys: pytest.CaptureFixture[str]) -> None:
    code = backtest.main([str(FIXTURES), "--store", "CA_1", "--horizon", "7", "--origins", "3"])

    assert code == 1  # only 21 days: the first origin would have no history
    assert "Error" in capsys.readouterr().err


# --- Features --------------------------------------------------------------------


def feature_frame(values: list[float]) -> pd.DataFrame:
    frame = make_series({"a": values})
    return frame.assign(wday=1, snap=0, event_name_1="", sell_price=np.float32(2.0))


def test_lag_and_rolling_values_by_hand() -> None:
    features = add_features(feature_frame(list(range(100))), min_lag=28)
    row = features.iloc[60]  # sales value 60

    assert row["lag_28"] == 32
    assert row["lag_56"] == 4
    assert row["rolling_mean_7"] == pytest.approx(np.mean(range(26, 33)))


def test_features_never_use_sales_newer_than_min_lag() -> None:
    """Change every sale after t - min_lag: features at t must not move."""
    values = [float(v % 13) for v in range(120)]
    t, min_lag = 100, 28
    changed = values.copy()
    for day in range(t - min_lag + 1, len(values)):
        changed[day] += 1000

    before = add_features(feature_frame(values), min_lag)
    after = add_features(feature_frame(changed), min_lag)

    sales_based = [column for column in FEATURE_COLUMNS if column.startswith(("lag_", "rolling_"))]
    pd.testing.assert_series_equal(before.loc[t, sales_based], after.loc[t, sales_based])


def test_all_feature_columns_exist_and_min_lag_is_checked() -> None:
    features = add_features(feature_frame(list(range(80))))

    assert set(FEATURE_COLUMNS) <= set(features.columns)
    with pytest.raises(ValueError):
        add_features(feature_frame(list(range(10))), min_lag=0)
