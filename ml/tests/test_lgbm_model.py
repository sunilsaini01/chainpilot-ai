"""Tests for the LightGBM model, using a small synthetic table in the M5 long format."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from demand_forecasting import train_final
from demand_forecasting.backtest import make_origins, run_backtest, scales_for, score
from demand_forecasting.features import add_features
from demand_forecasting.lgbm_model import (
    ModelSettings,
    load_models,
    make_forecaster,
    predict,
    save_models,
    train_models,
    training_rows,
)

FIXTURES = Path(__file__).parent / "fixtures" / "m5_tiny"
N_SERIES, N_DAYS = 24, 240
START = pd.Timestamp("2015-01-03")  # a Saturday

# Tiny model so the tests run in seconds; behaviour, not accuracy, is tested here.
FAST = ModelSettings(
    train_days=180,
    rounds=20,
    quantile_rounds=10,
    params={
        "objective": "tweedie",
        "tweedie_variance_power": 1.1,
        "learning_rate": 0.1,
        "num_leaves": 15,
        "min_data_in_leaf": 20,
        "seed": 42,
        "deterministic": True,
        "num_threads": 1,
        "verbose": -1,
    },
)


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


def test_training_rows_never_go_past_the_origin() -> None:
    features = add_features(synthetic_long())
    origin = START + pd.Timedelta(days=200)

    rows = training_rows(features, origin, train_days=180)

    assert rows["date"].max() == origin
    assert rows["date"].min() > origin - pd.Timedelta(days=180)
    assert rows["lag_28"].notna().all()
    assert rows["sell_price"].notna().all()  # days not on sale are left out


def test_predictions_do_not_change_when_future_sales_change() -> None:
    """The strongest leakage check: rewrite every sale after the origin."""
    long = synthetic_long()
    changed = long.copy()
    origin = START + pd.Timedelta(days=211)
    changed.loc[changed["date"] > origin, "sales"] += 50

    history = long[long["date"] <= origin][["id", "date", "sales"]]
    before = make_forecaster(long, FAST)(history, 28)
    after = make_forecaster(changed, FAST)(history, 28)

    pd.testing.assert_frame_equal(before, after)


def test_predictions_are_ordered_non_negative_and_zero_when_not_on_sale() -> None:
    long = synthetic_long()
    long.loc[
        (long["id"] == "FOODS_1_001_CA_1_validation")
        & (long["date"] > START + pd.Timedelta(days=220)),
        "sell_price",
    ] = np.nan
    origin = START + pd.Timedelta(days=211)

    forecast = make_forecaster(long, FAST)(long[long["date"] <= origin], 28)

    assert (forecast[["lower", "forecast", "upper"]] >= 0).all().all()
    assert (forecast["lower"] <= forecast["forecast"]).all()
    assert (forecast["forecast"] <= forecast["upper"]).all()
    delisted = forecast[
        (forecast["id"] == "FOODS_1_001_CA_1_validation")
        & (forecast["date"] > START + pd.Timedelta(days=220))
    ]
    assert len(delisted) > 0 and (delisted[["lower", "forecast", "upper"]] == 0).all().all()


def test_horizon_longer_than_the_feature_lag_is_refused() -> None:
    long = synthetic_long()

    with pytest.raises(ValueError, match="at most 28"):
        make_forecaster(long, FAST)(long[long["date"] <= START + pd.Timedelta(days=150)], 29)


def test_lightgbm_in_a_backtest_reports_interval_metrics() -> None:
    long = synthetic_long()
    origins = make_origins(long["date"].max(), horizon=14, n_origins=2)
    series = long[["id", "date", "sales"]]

    results = run_backtest(series, make_forecaster(long, FAST), origins, horizon=14)
    metrics = score(results, scales_for(series, origins))

    assert [row["horizon_days"] for row in metrics] == [7, 14]
    for row in metrics:
        assert 0 <= row["interval_coverage_80"] <= 1
        assert row["interval_width"] > 0
        assert row["pinball_10_90"] > 0


def test_learns_the_weekly_pattern_better_than_a_flat_guess() -> None:
    long = synthetic_long()
    origin = START + pd.Timedelta(days=211)
    settings = ModelSettings(train_days=180, rounds=60, quantile_rounds=10, params=FAST.params)

    forecast = make_forecaster(long, settings)(long[long["date"] <= origin], 28)
    merged = forecast.merge(
        long.assign(id=long["id"].astype(str))[["id", "date", "sales"]], on=["id", "date"]
    )
    model_error = (merged["forecast"] - merged["sales"]).abs().sum()
    flat = merged.groupby("id")["sales"].transform("mean")  # knows the future average!
    flat_error = (flat - merged["sales"]).abs().sum()

    # Beats even a flat forecast that was given the true future average.
    assert model_error < flat_error


def test_saved_models_load_and_predict_the_same(tmp_path: Path) -> None:
    features = add_features(synthetic_long())
    origin = START + pd.Timedelta(days=211)
    models = train_models(training_rows(features, origin, 180), FAST)
    test = features[features["date"] > origin]

    save_models(models, tmp_path, {"models": list(models), "store": "CA_1"})
    loaded, metadata = load_models(tmp_path)

    assert metadata["store"] == "CA_1"
    pd.testing.assert_frame_equal(predict(models, test), predict(loaded, test))


def test_train_final_command_on_fixtures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The 21-day fixture has no row with a 28-day lag, so there is nothing to train on:
    # the command must fail with a clear error, not save an empty model.
    monkeypatch.setattr(train_final, "ModelSettings", lambda: FAST)

    code = train_final.main([str(FIXTURES), "--store", "CA_1", "--output-dir", str(tmp_path)])

    assert code == 1
    assert "no training rows" in capsys.readouterr().err
    assert not (tmp_path / "CA_1" / "point.txt").exists()
