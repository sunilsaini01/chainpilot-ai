"""Tests for the LightGBM model, using a small synthetic table in the M5 long format."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from demand_forecasting import train_final
from demand_forecasting.backtest import make_origins, run_backtest, scales_for, score
from demand_forecasting.conformal import ConformalIntervals
from demand_forecasting.features import add_features
from demand_forecasting.lgbm_model import (
    WEEKLY_LAYOUT,
    ModelSettings,
    fit_model,
    load_models,
    make_forecaster,
    predict_rows,
    rows_for_steps,
    save_models,
    training_rows,
)

FIXTURES = Path(__file__).parent / "fixtures" / "m5_tiny"
N_SERIES, N_DAYS = 24, 240
START = pd.Timestamp("2015-01-03")  # a Saturday
ORIGIN = START + pd.Timedelta(days=211)

# Tiny model so the tests run in seconds; behaviour, not accuracy, is tested here.
FAST_PARAMS = {
    "objective": "tweedie",
    "tweedie_variance_power": 1.1,
    "learning_rate": 0.1,
    "num_leaves": 15,
    "min_data_in_leaf": 20,
    "seed": 42,
    "deterministic": True,
    "num_threads": 1,
    "verbose": -1,
}


def fast(weekly: bool = False, rounds: int = 20) -> ModelSettings:
    return ModelSettings(train_days=180, rounds=rounds, weekly_models=weekly, params=FAST_PARAMS)


def synthetic_long(seed: int = 0) -> pd.DataFrame:
    """M5-like long table: weekly pattern, noise, one product not on sale at first."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(START, periods=N_DAYS, freq="D")
    frames = []
    for number in range(N_SERIES):
        level = 1 + number % 5
        weekly = np.tile([1.0, 1.4, 0.8, 0.7, 0.9, 1.1, 1.6], N_DAYS // 7 + 1)[:N_DAYS]
        sales = rng.poisson(level * weekly)
        price = np.full(N_DAYS, 2.0 + number % 3, dtype="float32")
        if number == 0:  # not on sale for the first 100 days
            sales[:100] = 0
            price[:100] = np.nan
        item = f"FOODS_1_{number:03d}"
        frames.append(
            pd.DataFrame(
                {
                    "id": f"{item}_CA_1_validation",
                    "item_id": item,
                    "dept_id": "FOODS_1",
                    "cat_id": "FOODS",
                    "store_id": "CA_1",
                    "state_id": "CA",
                    "d": [f"d_{i + 1}" for i in range(N_DAYS)],
                    "date": dates,
                    "wm_yr_wk": 11501 + np.arange(N_DAYS) // 7,
                    "wday": np.arange(N_DAYS) % 7 + 1,
                    "event_name_1": "",
                    "event_type_1": "",
                    "sales": sales,
                    "sell_price": price,
                    "snap": (dates.day <= 10).astype("int8"),
                }
            )
        )
    long = pd.concat(frames, ignore_index=True)
    for column in [
        "id",
        "item_id",
        "dept_id",
        "cat_id",
        "store_id",
        "state_id",
        "d",
        "event_name_1",
        "event_type_1",
    ]:
        long[column] = long[column].astype("category")
    return long


def history_until(long: pd.DataFrame, origin: pd.Timestamp) -> pd.DataFrame:
    return long[long["date"] <= origin][["id", "date", "sales"]]


@pytest.mark.parametrize("min_lag", [7, 28])
def test_training_rows_never_go_past_the_origin(min_lag: int) -> None:
    features = add_features(synthetic_long(), min_lag=min_lag)

    rows = training_rows(features, ORIGIN, train_days=180, min_lag=min_lag)

    assert rows["date"].max() == ORIGIN
    assert rows["date"].min() > ORIGIN - pd.Timedelta(days=180)
    assert rows[f"lag_{min_lag}"].notna().all()
    assert rows["sell_price"].notna().all()  # days not on sale are left out


@pytest.mark.parametrize("weekly", [False, True])
def test_predictions_do_not_change_when_future_sales_change(weekly: bool) -> None:
    """The strongest leakage check: rewrite every sale after the origin."""
    long = synthetic_long()
    changed = long.copy()
    changed.loc[changed["date"] > ORIGIN, "sales"] += 50

    before = make_forecaster(long, fast(weekly))(history_until(long, ORIGIN), 28)
    after = make_forecaster(changed, fast(weekly))(history_until(long, ORIGIN), 28)

    pd.testing.assert_frame_equal(before, after)


def test_next_weeks_inputs_include_last_week_only_with_a_7_day_lag() -> None:
    """Why the weekly layout exists: the inputs for days 1-7 ahead can use last week's
    sales when the minimum lag is 7, but not when it is 28. (Both models still learn
    from last week as training targets, which is allowed: those days are before the origin.)
    """
    long = synthetic_long()
    changed = long.copy()
    last_week = (changed["date"] > ORIGIN - pd.Timedelta(days=7)) & (changed["date"] <= ORIGIN)
    changed.loc[last_week, "sales"] += 30

    def next_week_inputs(frame: pd.DataFrame, min_lag: int) -> pd.DataFrame:
        features = add_features(frame, min_lag=min_lag)
        rows = rows_for_steps(features, ORIGIN, 1, 7)
        return rows[[c for c in rows.columns if c.startswith(("lag_", "rolling_"))]]

    assert not next_week_inputs(long, 7).equals(next_week_inputs(changed, 7))
    pd.testing.assert_frame_equal(next_week_inputs(long, 28), next_week_inputs(changed, 28))


@pytest.mark.parametrize(("weekly", "horizon"), [(False, 28), (True, 28), (True, 10)])
def test_every_series_and_day_is_forecast_exactly_once(weekly: bool, horizon: int) -> None:
    long = synthetic_long()

    forecast = make_forecaster(long, fast(weekly))(history_until(long, ORIGIN), horizon)

    assert len(forecast) == N_SERIES * horizon
    assert not forecast.duplicated(["id", "date"]).any()
    assert forecast["date"].min() == ORIGIN + pd.Timedelta(days=1)
    assert forecast["date"].max() == ORIGIN + pd.Timedelta(days=horizon)


def test_forecasts_are_non_negative_and_zero_when_not_on_sale() -> None:
    long = synthetic_long()
    delisted = (long["id"] == "FOODS_1_001_CA_1_validation") & (
        long["date"] > ORIGIN + pd.Timedelta(days=9)
    )
    long.loc[delisted, "sell_price"] = np.nan

    forecast = make_forecaster(long, fast(True))(history_until(long, ORIGIN), 28)

    assert (forecast["forecast"] >= 0).all()
    off_sale = forecast[
        (forecast["id"] == "FOODS_1_001_CA_1_validation")
        & (forecast["date"] > ORIGIN + pd.Timedelta(days=9))
    ]
    assert len(off_sale) == 19 and (off_sale["forecast"] == 0).all()


def test_horizon_longer_than_the_feature_lag_is_refused() -> None:
    long = synthetic_long()

    with pytest.raises(ValueError, match="at most 28"):
        make_forecaster(long, fast())(history_until(long, ORIGIN - pd.Timedelta(days=60)), 29)


def test_backtest_with_calibrated_intervals_reports_coverage() -> None:
    long = synthetic_long()
    series = long[["id", "date", "sales"]]
    forecaster = make_forecaster(long, fast(True))
    validation = run_backtest(series, forecaster, [ORIGIN - pd.Timedelta(days=28)], 14)
    intervals = ConformalIntervals.fit(validation, n_bins=4)

    origins = make_origins(series["date"].max(), horizon=14, n_origins=1)
    results = intervals.apply(run_backtest(series, forecaster, origins, 14))
    metrics = score(results, scales_for(series, origins))

    for row in metrics:
        assert 0.5 <= row["interval_coverage_80"] <= 1.0
        assert row["interval_width"] > 0


def test_learns_the_weekly_pattern_better_than_a_flat_guess() -> None:
    long = synthetic_long()

    forecast = make_forecaster(long, fast(rounds=60))(history_until(long, ORIGIN), 28)
    merged = forecast.merge(
        long.assign(id=long["id"].astype(str))[["id", "date", "sales"]], on=["id", "date"]
    )
    model_error = (merged["forecast"] - merged["sales"]).abs().sum()
    flat = merged.groupby("id")["sales"].transform("mean")  # knows the future average!
    flat_error = (flat - merged["sales"]).abs().sum()

    # Beats even a flat forecast that was given the true future average.
    assert model_error < flat_error


def test_saved_models_load_and_predict_the_same(tmp_path: Path) -> None:
    long = synthetic_long()
    models = []
    for bucket in WEEKLY_LAYOUT:
        features = add_features(long, min_lag=bucket.min_lag)
        train = training_rows(features, ORIGIN, 180, bucket.min_lag)
        models.append((bucket, fit_model(train, bucket.min_lag, fast(True))))

    save_models(models, tmp_path, {"store": "CA_1"})
    loaded, metadata = load_models(tmp_path)

    assert metadata["store"] == "CA_1"
    assert [entry["name"] for entry in metadata["models"]] == [
        "steps_1_7",
        "steps_8_14",
        "steps_15_21",
        "steps_22_28",
    ]
    for (bucket, model), (loaded_bucket, loaded_model) in zip(models, loaded, strict=True):
        assert bucket == loaded_bucket
        rows = rows_for_steps(
            add_features(long, min_lag=bucket.min_lag), ORIGIN, bucket.first_step, bucket.last_step
        )
        pd.testing.assert_frame_equal(
            predict_rows(model, rows, bucket.min_lag),
            predict_rows(loaded_model, rows, bucket.min_lag),
        )


def test_train_final_command_on_fixtures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The 21-day fixture has no row with a 28-day lag, so there is nothing to train on:
    # the command must fail with a clear error, not save an empty model.
    monkeypatch.setattr(train_final, "ModelSettings", lambda weekly_models: fast(weekly_models))

    code = train_final.main([str(FIXTURES), "--store", "CA_1", "--output-dir", str(tmp_path)])

    assert code == 1
    assert "no training rows" in capsys.readouterr().err
    assert not (tmp_path / "CA_1").exists()
