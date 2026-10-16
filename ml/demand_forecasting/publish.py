"""Turn the saved models into a forecast file the API can import.

For each store, loads ml/artifacts/<store>/ (from train_final), builds features
for the days after the data ends, predicts with the model for each forecast
week, adds the calibrated 80% interval, and writes

    <output>/forecasts.csv   one row per series and future day
    <output>/manifest.json   what produced it (model, dates, versions, checksums)

DATA LABEL: these are forecasts for the public M5 (Walmart) dataset. They are
not forecasts for the simulated SYN- products in the application database.

From the `ml` folder:
    python -m demand_forecasting.publish ../data/raw/m5 --all-stores
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

from demand_forecasting import m5_data
from demand_forecasting.backtest import ALL_STORES, file_sha256, git_commit
from demand_forecasting.conformal import ConformalIntervals
from demand_forecasting.features import add_features
from demand_forecasting.lgbm_model import load_models, predict_rows, rows_for_steps
from demand_forecasting.train_final import DEFAULT_OUTPUT as DEFAULT_ARTIFACTS

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "processed" / "forecasts"
DATASET_LABEL = "M5 Forecasting - Accuracy (public Walmart data); not the simulated SYN- products"
CSV_COLUMNS = [
    "series_id",
    "item_id",
    "dept_id",
    "cat_id",
    "store_id",
    "forecast_date",
    "step",
    "forecast",
    "lower",
    "upper",
]


def forecast_store(raw_dir: Path, store: str, artifacts_dir: Path) -> tuple[pd.DataFrame, dict]:
    """Forecast every series of one store for the days after its data ends."""
    models, metadata = load_models(artifacts_dir / store)
    if not metadata.get("intervals"):
        raise ValueError(
            f"{store}: model has no calibrated intervals (train with --selection-report)"
        )
    horizon = max(bucket.last_step for bucket, _ in models)

    paths = m5_data.find_files(raw_dir)
    calendar = m5_data.load_calendar(paths["calendar"])
    prices = m5_data.load_prices(paths["prices"], [store])
    long = m5_data.to_long(m5_data.load_sales(paths["sales"], [store]), calendar, prices)
    last_day = long["date"].max()
    if last_day.date().isoformat() != metadata["trained_through"]:
        raise ValueError(
            f"{store}: model trained through {metadata['trained_through']}, "
            f"but the data ends {last_day.date()}"
        )
    extended = m5_data.future_long(long, calendar, prices, horizon)

    parts = []
    for bucket, model in models:
        features = add_features(extended, min_lag=bucket.min_lag)
        rows = rows_for_steps(features, last_day, bucket.first_step, bucket.last_step)
        parts.append(predict_rows(model, rows, bucket.min_lag))
        del features
    forecast = ConformalIntervals(**metadata["intervals"]).apply(
        pd.concat(parts, ignore_index=True)
    )

    series = long[["id", "item_id", "dept_id", "cat_id", "store_id"]].drop_duplicates("id")
    series = series.astype(str).rename(columns={"id": "series_id"})
    forecast = forecast.rename(columns={"id": "series_id", "date": "forecast_date"}).merge(
        series, on="series_id", how="left", validate="many_to_one"
    )
    forecast["step"] = (forecast["forecast_date"] - last_day).dt.days
    forecast["forecast_date"] = forecast["forecast_date"].dt.date.astype(str)
    return forecast[CSV_COLUMNS], metadata


def publish(raw_dir: Path, stores: list[str], artifacts_dir: Path, output_root: Path) -> Path:
    frames, metadata_by_store = [], {}
    for store in stores:
        frame, metadata = forecast_store(raw_dir, store, artifacts_dir)
        frames.append(frame)
        metadata_by_store[store] = metadata
    trained_through = {meta["trained_through"] for meta in metadata_by_store.values()}
    if len(trained_through) != 1:
        raise ValueError(f"stores were trained through different days: {sorted(trained_through)}")
    forecasts = pd.concat(frames, ignore_index=True).sort_values(["series_id", "step"])

    folder = output_root / f"m5_lightgbm_weekly_{trained_through.pop()}"
    folder.mkdir(parents=True, exist_ok=True)
    csv_path = folder / "forecasts.csv"
    forecasts.to_csv(csv_path, index=False, float_format="%.4f", lineterminator="\n")
    any_meta = next(iter(metadata_by_store.values()))
    manifest = {
        "dataset": DATASET_LABEL,
        "model": "lightgbm_weekly",
        "trained_through": any_meta["trained_through"],
        "forecast_start": forecasts["forecast_date"].min(),
        "forecast_end": forecasts["forecast_date"].max(),
        "horizon_days": int(forecasts["step"].max()),
        "stores": stores,
        "series": int(forecasts["series_id"].nunique()),
        "rows": len(forecasts),
        "interval": "80% (split-conformal, calibrated on the validation period)",
        "csv_sha256": file_sha256(csv_path),
        "model_git_commits": sorted({meta["git_commit"] for meta in metadata_by_store.values()}),
        "publish_git_commit": git_commit(),
        "data_sha256": any_meta["data_sha256"],
        "evaluation": "docs/MODEL_RESULTS.md",
    }
    # One key per distinct forecast file: importing the same file twice is refused.
    manifest["run_key"] = hashlib.sha256(manifest["csv_sha256"].encode()).hexdigest()[:16]
    (folder / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return folder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m demand_forecasting.publish")
    parser.add_argument("raw_dir", type=Path)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--store", action="append")
    which.add_argument("--all-stores", action="store_true")
    parser.add_argument("--artifacts-dir", type=Path, default=DEFAULT_ARTIFACTS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)

    try:
        folder = publish(
            args.raw_dir,
            ALL_STORES if args.all_stores else args.store,
            args.artifacts_dir,
            args.output_root,
        )
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    print(
        f"Wrote {manifest['rows']} forecasts for {manifest['series']} series "
        f"({manifest['forecast_start']} to {manifest['forecast_end']}) to {folder}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
