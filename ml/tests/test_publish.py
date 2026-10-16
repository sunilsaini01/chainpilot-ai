"""Tests for future rows and the forecast file (publish.py), on the tiny M5-format fixtures."""

import json
from pathlib import Path

import pandas as pd
import pytest

from demand_forecasting import m5_data, publish
from demand_forecasting.conformal import ConformalIntervals
from demand_forecasting.features import add_features
from demand_forecasting.lgbm_model import (
    Bucket,
    ModelSettings,
    fit_model,
    save_models,
    training_rows,
)

FIXTURES = Path(__file__).parent / "fixtures" / "m5_tiny"
LAST_SALES_DAY = pd.Timestamp("2011-02-18")
TINY = ModelSettings(
    train_days=30,
    rounds=5,
    params={
        "objective": "tweedie",
        "learning_rate": 0.1,
        "num_leaves": 4,
        "min_data_in_leaf": 2,
        "min_data_in_bin": 1,
        "seed": 1,
        "deterministic": True,
        "num_threads": 1,
        "verbose": -1,
    },
)


def tables(store: str = "CA_1"):
    paths = m5_data.find_files(FIXTURES)
    calendar = m5_data.load_calendar(paths["calendar"])
    prices = m5_data.load_prices(paths["prices"], [store])
    long = m5_data.to_long(m5_data.load_sales(paths["sales"], [store]), calendar, prices)
    return long, calendar, prices


def test_future_rows_have_calendar_and_prices_but_no_sales() -> None:
    long, calendar, prices = tables()

    extended = m5_data.future_long(long, calendar, prices, days=7)

    future = extended[extended["date"] > LAST_SALES_DAY]
    assert len(future) == 3 * 7  # 3 series in CA_1, 7 days
    assert future["sales"].isna().all()
    assert future["sell_price"].notna().all()
    assert (future["date"].max() - LAST_SALES_DAY).days == 7
    # Each series keeps its own state's SNAP flag.
    snap = calendar.set_index("date").loc[future["date"], "snap_CA"].to_numpy()
    assert (future["snap"].to_numpy() == snap).all()
    # Past rows are unchanged.
    past = extended[extended["date"] <= LAST_SALES_DAY].reset_index(drop=True)
    assert past["sales"].tolist() == long.sort_values(["id", "date"])["sales"].tolist()


def test_future_rows_need_calendar_coverage() -> None:
    long, calendar, prices = tables()

    with pytest.raises(ValueError, match="does not cover 8 days"):
        m5_data.future_long(long, calendar, prices, days=8)


def make_artifacts(folder: Path, store: str, with_intervals: bool = True) -> None:
    """A one-week model trained on the fixture, saved like train_final does."""
    long, _, _ = tables(store)
    bucket = Bucket(7, 1, 7)
    features = add_features(long, min_lag=7)
    train = training_rows(features, LAST_SALES_DAY, TINY.train_days, 7)
    model = fit_model(train, 7, TINY)
    intervals = ConformalIntervals([0.5, 2.0], [-0.5, -1.0, -2.0], [1.0, 2.0, 3.0], 100)
    save_models(
        [(bucket, model)],
        folder / store,
        {
            "store": store,
            "trained_through": "2011-02-18",
            "intervals": intervals.to_dict() if with_intervals else None,
            "git_commit": "test",
            "data_sha256": {"sales": "x"},
        },
    )


def test_publish_writes_forecasts_and_manifest(tmp_path: Path) -> None:
    for store in ["CA_1", "TX_1"]:
        make_artifacts(tmp_path / "artifacts", store)

    folder = publish.publish(FIXTURES, ["CA_1", "TX_1"], tmp_path / "artifacts", tmp_path / "out")

    forecasts = pd.read_csv(folder / "forecasts.csv")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert folder.name == "m5_lightgbm_weekly_2011-02-18"
    assert list(forecasts.columns) == publish.CSV_COLUMNS
    assert len(forecasts) == 6 * 7
    assert forecasts["forecast_date"].min() == "2011-02-19"
    assert forecasts["forecast_date"].max() == "2011-02-25"
    assert sorted(forecasts["step"].unique()) == list(range(1, 8))
    assert (forecasts["lower"] <= forecasts["forecast"]).all()
    assert (forecasts["forecast"] <= forecasts["upper"]).all()
    assert (forecasts["lower"] >= 0).all()
    assert manifest["rows"] == 42 and manifest["series"] == 6
    assert manifest["stores"] == ["CA_1", "TX_1"]
    assert "not the simulated SYN- products" in manifest["dataset"]
    assert manifest["csv_sha256"] == publish.file_sha256(folder / "forecasts.csv")
    assert len(manifest["run_key"]) == 16


def test_publish_refuses_models_without_intervals(tmp_path: Path) -> None:
    make_artifacts(tmp_path / "artifacts", "CA_1", with_intervals=False)

    with pytest.raises(ValueError, match="no calibrated intervals"):
        publish.publish(FIXTURES, ["CA_1"], tmp_path / "artifacts", tmp_path / "out")


def test_publish_refuses_models_trained_on_other_data(tmp_path: Path) -> None:
    make_artifacts(tmp_path / "artifacts", "CA_1")
    meta_path = tmp_path / "artifacts" / "CA_1" / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["trained_through"] = "2011-02-11"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    code = publish.main(
        [
            str(FIXTURES),
            "--store",
            "CA_1",
            "--artifacts-dir",
            str(tmp_path / "artifacts"),
            "--output-root",
            str(tmp_path / "out"),
        ]
    )

    assert code == 1


def test_holdout_scores_against_the_evaluation_file(tmp_path: Path) -> None:
    from demand_forecasting import holdout

    make_artifacts(tmp_path / "artifacts", "CA_1")
    folder = publish.publish(FIXTURES, ["CA_1"], tmp_path / "artifacts", tmp_path / "out")
    # A fake evaluation file: the fixture sales plus 7 known future days (all 2 units).
    raw = tmp_path / "raw"
    raw.mkdir()
    sales = pd.read_csv(FIXTURES / "sales_train_validation.csv")
    sales = sales[sales["store_id"] == "CA_1"]
    for day in range(22, 29):
        sales[f"d_{day}"] = 2
    sales["id"] = sales["id"].str.replace("_validation", "_evaluation")
    sales.to_csv(raw / "sales_train_evaluation.csv", index=False)
    for name in ["calendar.csv", "sell_prices.csv"]:  # needed for the weighted RMSSE
        (raw / name).write_bytes((FIXTURES / name).read_bytes())

    result = holdout.holdout_scores(raw, folder)

    assert result["rows"] == 3 * 7
    assert result["actuals"].endswith("d_22..d_28")
    row = result["metrics"][0]
    assert row["horizon_days"] == 7
    forecasts = pd.read_csv(folder / "forecasts.csv")
    expected = (forecasts["forecast"] - 2).abs().sum() / (2 * 21)
    assert row["wape_model"] == pytest.approx(expected, abs=1e-4)

    assert row["rmsse_model"] > 0 and row["rmsse_weighted_model"] > 0
    assert set(row) >= {"rmsse_moving_average_28", "rmsse_weighted_moving_average_28"}


def test_fast_history_scales_match_the_backtest_definition() -> None:
    from demand_forecasting import holdout
    from demand_forecasting.metrics import rmsse_scales

    wide = pd.DataFrame(
        [[0, 0, 2, 4, 2, 0], [3, 3, 3, 3, 3, 3], [0, 0, 0, 0, 0, 0], [1, 5, 0, 0, 2, 2]],
        index=pd.Index(["a", "flat", "never", "b"], name="series_id"),
        columns=[f"d_{i}" for i in range(1, 7)],
    )
    long = wide.reset_index().melt(id_vars="series_id", var_name="d", value_name="sales")
    long["date"] = pd.Timestamp("2016-01-01") + pd.to_timedelta(long["d"].str[2:].astype(int), "D")

    fast = holdout.history_scales(wide)
    reference = rmsse_scales(long.rename(columns={"series_id": "id"}))

    pd.testing.assert_series_equal(
        fast.sort_index(),
        reference.reindex(fast.index).sort_index(),
        check_names=False,
        check_dtype=False,
        rtol=1e-6,
    )
