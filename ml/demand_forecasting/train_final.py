"""Train the final LightGBM models on all data up to the last day and save them.

The backtests measure how good the approach is; this command fits the chosen
layout on the newest data, so the saved models can forecast the 28 days after
the dataset ends. If a model-selection report is given, its calibrated interval
bounds are stored too, so the API can return 80% intervals.

From the `ml` folder:
    python -m demand_forecasting.train_final ../data/raw/m5 --store CA_1 --weekly \
        --selection-report ../docs/results/p2_model_selection.json
Models go to ml/artifacts/<store>/ (not in Git).
"""

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import lightgbm as lgb
import pandas as pd

from demand_forecasting import m5_data
from demand_forecasting.backtest import ALL_STORES, file_sha256, git_commit
from demand_forecasting.features import add_features
from demand_forecasting.lgbm_model import ModelSettings, fit_model, save_models, training_rows

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "artifacts"


def train_store(
    raw_dir: Path,
    store: str,
    output_dir: Path,
    settings: ModelSettings,
    intervals: dict | None = None,
) -> Path:
    paths = m5_data.find_files(raw_dir)
    long = m5_data.to_long(
        m5_data.load_sales(paths["sales"], [store]),
        m5_data.load_calendar(paths["calendar"]),
        m5_data.load_prices(paths["prices"], [store]),
    )
    last_day = long["date"].max()
    started = time.perf_counter()
    models = []
    train_rows = {}
    for bucket in settings.layout:
        features = add_features(long, min_lag=bucket.min_lag)
        train = training_rows(features, last_day, settings.train_days, bucket.min_lag)
        models.append((bucket, fit_model(train, bucket.min_lag, settings)))
        train_rows[f"steps_{bucket.first_step}_{bucket.last_step}"] = len(train)
        del features, train
    folder = output_dir / store
    save_models(
        models,
        folder,
        {
            "store": store,
            "trained_through": last_day.date().isoformat(),
            "train_from": (last_day - pd.Timedelta(days=settings.train_days - 1))
            .date()
            .isoformat(),
            "train_rows": train_rows,
            "forecast_horizon_days": 28,
            "settings": asdict(settings),
            "intervals": intervals,
            "training_seconds": round(time.perf_counter() - started, 1),
            "git_commit": git_commit(),
            "lightgbm": lgb.__version__,
            "data_sha256": {name: file_sha256(path) for name, path in paths.items()},
            "evaluation": "see docs/MODEL_RESULTS.md",
        },
    )
    return folder


def intervals_from_report(report_path: Path, model_name: str) -> dict:
    """The calibrated 80% interval bounds for `model_name` from a model-selection report."""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return report["conformal"][model_name]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m demand_forecasting.train_final")
    parser.add_argument("raw_dir", type=Path)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--store", action="append")
    which.add_argument("--all-stores", action="store_true")
    parser.add_argument("--weekly", action="store_true", help="one model per forecast week")
    parser.add_argument("--selection-report", type=Path, help="add calibrated interval bounds")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    settings = ModelSettings(weekly_models=args.weekly)
    model_name = "lightgbm_weekly" if args.weekly else "lightgbm_single"
    try:
        intervals = (
            intervals_from_report(args.selection_report, model_name)
            if args.selection_report
            else None
        )
        for store in ALL_STORES if args.all_stores else args.store:
            folder = train_store(args.raw_dir, store, args.output_dir, settings, intervals)
            print(f"{store}: models saved to {folder}")
    except (FileNotFoundError, ValueError, KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
