"""Train the final LightGBM models on all data up to the last day and save them.

The backtest (backtest.py --with-lightgbm) measures how good the approach is;
this command then fits the same settings on the newest data, so the saved model
can forecast the 28 days after the dataset ends.

From the `ml` folder:
    python -m demand_forecasting.train_final ../data/raw/m5 --store CA_1
Models go to ml/artifacts/<store>/ (not in Git): point.txt, lower.txt, upper.txt,
metadata.json.
"""

import argparse
import sys
import time
from dataclasses import asdict
from pathlib import Path

import lightgbm as lgb
import pandas as pd

from demand_forecasting import m5_data
from demand_forecasting.backtest import ALL_STORES, file_sha256, git_commit
from demand_forecasting.features import add_features
from demand_forecasting.lgbm_model import (
    MODEL_FEATURES,
    ModelSettings,
    save_models,
    train_models,
    training_rows,
)

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "artifacts"


def train_store(raw_dir: Path, store: str, output_dir: Path, settings: ModelSettings) -> Path:
    paths = m5_data.find_files(raw_dir)
    long = m5_data.to_long(
        m5_data.load_sales(paths["sales"], [store]),
        m5_data.load_calendar(paths["calendar"]),
        m5_data.load_prices(paths["prices"], [store]),
    )
    features = add_features(long)
    last_day = features["date"].max()
    train = training_rows(features, last_day, settings.train_days)
    started = time.perf_counter()
    models = train_models(train, settings)
    folder = output_dir / store
    save_models(
        models,
        folder,
        {
            "store": store,
            "models": list(models),
            "features": MODEL_FEATURES,
            "trained_through": last_day.date().isoformat(),
            "train_from": (last_day - pd.Timedelta(days=settings.train_days - 1))
            .date()
            .isoformat(),
            "train_rows": len(train),
            "forecast_horizon_days": 28,
            "settings": asdict(settings),
            "training_seconds": round(time.perf_counter() - started, 1),
            "git_commit": git_commit(),
            "lightgbm": lgb.__version__,
            "data_sha256": {name: file_sha256(path) for name, path in paths.items()},
            "evaluation": "see docs/MODEL_RESULTS.md (rolling-origin backtest)",
        },
    )
    return folder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m demand_forecasting.train_final")
    parser.add_argument("raw_dir", type=Path)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--store", action="append")
    which.add_argument("--all-stores", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    try:
        for store in ALL_STORES if args.all_stores else args.store:
            folder = train_store(args.raw_dir, store, args.output_dir, ModelSettings())
            print(f"{store}: models saved to {folder}")
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
