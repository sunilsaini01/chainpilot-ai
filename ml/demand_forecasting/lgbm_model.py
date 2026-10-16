"""LightGBM demand model (point forecasts; intervals come from conformal.py).

One model set per store. Inputs are the leakage-safe features from features.py
plus product, department and category. Tweedie objective, which suits counts
with many zeros. Days without a price (product not on sale) are left out of
training and forecast as 0.

Two layouts:
- single model: every sales feature is >= 28 days old, one model for days 1-28.
- weekly models: four models; the one for days 1-7 may use sales >= 7 days old,
  days 8-14 >= 14 days, days 15-21 >= 21 days, days 22-28 >= 28 days.
  Short-range forecasts then use fresher sales, still without any leakage:
  a model for days up to N ahead only uses sales at least N days old.
"""

import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from demand_forecasting.features import DEFAULT_MIN_LAG, add_features, feature_columns

CATEGORY_FEATURES = ["item_id", "dept_id", "cat_id"]
MAX_HORIZON = DEFAULT_MIN_LAG

# Fixed, simple settings chosen before looking at any test window (no tuning on test data).
POINT_PARAMS = {
    "objective": "tweedie",
    "tweedie_variance_power": 1.1,
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 100,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "seed": 42,
    "deterministic": True,
    "num_threads": 4,
    "verbose": -1,
}


@dataclass(frozen=True)
class Bucket:
    """One model's job: forecast steps first_step..last_step using sales >= min_lag days old."""

    min_lag: int
    first_step: int
    last_step: int


SINGLE_LAYOUT = [Bucket(28, 1, 28)]
WEEKLY_LAYOUT = [Bucket(7, 1, 7), Bucket(14, 8, 14), Bucket(21, 15, 21), Bucket(28, 22, 28)]


@dataclass
class ModelSettings:
    train_days: int = 730  # two years of history per origin keeps training fast
    rounds: int = 300
    weekly_models: bool = False
    params: dict = field(default_factory=lambda: dict(POINT_PARAMS))

    @property
    def layout(self) -> list[Bucket]:
        return WEEKLY_LAYOUT if self.weekly_models else SINGLE_LAYOUT


def model_features(min_lag: int) -> list[str]:
    return [*feature_columns(min_lag), *CATEGORY_FEATURES]


def training_rows(
    features: pd.DataFrame, origin: pd.Timestamp, train_days: int, min_lag: int = DEFAULT_MIN_LAG
) -> pd.DataFrame:
    """Rows usable for training at `origin`: dated up to the origin, inside the training
    window, with a full set of lag features and a price (product on sale)."""
    start = origin - pd.Timedelta(days=train_days)
    rows = features[(features["date"] > start) & (features["date"] <= origin)]
    return rows[rows[f"lag_{min_lag}"].notna() & rows["sell_price"].notna()]


def fit_model(train: pd.DataFrame, min_lag: int, settings: ModelSettings) -> lgb.Booster:
    if train.empty:
        raise ValueError(
            f"no training rows: each series needs more than {min_lag} days of history "
            "(with prices) before the origin"
        )
    data = lgb.Dataset(
        train[model_features(min_lag)],
        label=train["sales"].astype("float32"),
        categorical_feature=CATEGORY_FEATURES,
        free_raw_data=True,
    )
    return lgb.train(settings.params, data, num_boost_round=settings.rounds)


def predict_rows(model: lgb.Booster, rows: pd.DataFrame, min_lag: int) -> pd.DataFrame:
    """Forecast for feature rows: never negative, 0 when the product is not on sale."""
    values = np.clip(model.predict(rows[model_features(min_lag)]), 0, None)
    on_sale = rows["sell_price"].notna().to_numpy()
    return pd.DataFrame(
        {
            "id": rows["id"].astype(str).to_numpy(),
            "date": rows["date"].to_numpy(),
            "forecast": np.where(on_sale, values, 0.0),
        }
    )


def rows_for_steps(
    features: pd.DataFrame, origin: pd.Timestamp, first_step: int, last_step: int
) -> pd.DataFrame:
    return features[
        (features["date"] >= origin + pd.Timedelta(days=first_step))
        & (features["date"] <= origin + pd.Timedelta(days=last_step))
    ]


def make_forecaster(long: pd.DataFrame, settings: ModelSettings):
    """Build a forecaster for backtest.run_backtest from a long M5 table of one store.

    Features are computed once per minimum lag. That is safe because a model for
    steps up to N only reads features whose sales are at least N days old, so its
    test-day features use sales up to the origin only. Calendar and price columns
    are known in advance. Training rows never go past the origin.
    """
    features_for = cache(lambda min_lag: add_features(long, min_lag=min_lag))

    def forecaster(history: pd.DataFrame, horizon: int) -> pd.DataFrame:
        if horizon > MAX_HORIZON:
            raise ValueError(f"horizon must be at most {MAX_HORIZON} days (feature lag)")
        origin = history["date"].max()
        parts = []
        for bucket in settings.layout:
            if bucket.first_step > horizon:
                continue
            features = features_for(bucket.min_lag)
            train = training_rows(features, origin, settings.train_days, bucket.min_lag)
            model = fit_model(train, bucket.min_lag, settings)
            test = rows_for_steps(
                features, origin, bucket.first_step, min(bucket.last_step, horizon)
            )
            parts.append(predict_rows(model, test, bucket.min_lag))
        return pd.concat(parts, ignore_index=True)

    return forecaster


def save_models(
    models: list[tuple[Bucket, lgb.Booster]], folder: Path, metadata: dict
) -> list[Path]:
    """Save each booster in LightGBM's own text format plus a metadata JSON.

    The text format needs no pickle, so loading a model file cannot run arbitrary code.
    """
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    entries = []
    for bucket, model in models:
        name = f"steps_{bucket.first_step}_{bucket.last_step}"
        path = folder / f"{name}.txt"
        model.save_model(str(path))
        written.append(path)
        entries.append({"name": name, **bucket.__dict__})
    meta_path = folder / "metadata.json"
    meta = {**metadata, "models": entries}
    meta_path.write_text(json.dumps(meta, indent=2, default=str) + "\n", encoding="utf-8")
    written.append(meta_path)
    return written


def load_models(folder: Path) -> tuple[list[tuple[Bucket, lgb.Booster]], dict]:
    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    models = [
        (
            Bucket(entry["min_lag"], entry["first_step"], entry["last_step"]),
            lgb.Booster(model_file=str(folder / f"{entry['name']}.txt")),
        )
        for entry in metadata["models"]
    ]
    return models, metadata
