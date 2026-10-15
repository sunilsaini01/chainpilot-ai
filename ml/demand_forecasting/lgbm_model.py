"""LightGBM demand model with an 80% forecast interval.

One model per store. Inputs are the leakage-safe features from features.py
(sales-based features are at least 28 days old) plus the product, department
and category. Three boosters are trained per origin:

- point forecast: Tweedie objective, which suits counts with many zeros
- lower bound:   10th percentile (quantile objective)
- upper bound:   90th percentile, so [lower, upper] is an 80% interval

Days when a product has no price were days it was not on sale: they are left out
of training and forecast as 0.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from demand_forecasting.features import DEFAULT_MIN_LAG, FEATURE_COLUMNS, add_features

CATEGORY_FEATURES = ["item_id", "dept_id", "cat_id"]
MODEL_FEATURES = [*FEATURE_COLUMNS, *CATEGORY_FEATURES]

# Fixed, simple settings chosen before looking at the test windows (no tuning on test data).
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
QUANTILE_ALPHAS = {"lower": 0.1, "upper": 0.9}


@dataclass
class ModelSettings:
    train_days: int = 730  # two years of history per origin keeps training fast
    rounds: int = 300
    quantile_rounds: int = 150
    with_interval: bool = True
    params: dict = field(default_factory=lambda: dict(POINT_PARAMS))


def training_rows(features: pd.DataFrame, origin: pd.Timestamp, train_days: int) -> pd.DataFrame:
    """Rows usable for training at `origin`: dated up to the origin, inside the training
    window, with a full set of lag features and a price (product on sale)."""
    start = origin - pd.Timedelta(days=train_days)
    rows = features[(features["date"] > start) & (features["date"] <= origin)]
    return rows[rows[f"lag_{DEFAULT_MIN_LAG}"].notna() & rows["sell_price"].notna()]


def _fit(train: pd.DataFrame, params: dict, rounds: int) -> lgb.Booster:
    data = lgb.Dataset(
        train[MODEL_FEATURES],
        label=train["sales"].astype("float32"),
        categorical_feature=CATEGORY_FEATURES,
        free_raw_data=True,
    )
    return lgb.train(params, data, num_boost_round=rounds)


def train_models(train: pd.DataFrame, settings: ModelSettings) -> dict[str, lgb.Booster]:
    if train.empty:
        raise ValueError(
            "no training rows: each series needs more than "
            f"{DEFAULT_MIN_LAG} days of history (with prices) before the origin"
        )
    models = {"point": _fit(train, settings.params, settings.rounds)}
    if settings.with_interval:
        for name, alpha in QUANTILE_ALPHAS.items():
            params = {**settings.params, "objective": "quantile", "alpha": alpha}
            params.pop("tweedie_variance_power", None)
            models[name] = _fit(train, params, settings.quantile_rounds)
    return models


def predict(models: dict[str, lgb.Booster], rows: pd.DataFrame) -> pd.DataFrame:
    """Forecasts for `rows`: never negative, 0 when the product is not on sale,
    and lower <= forecast <= upper."""
    on_sale = rows["sell_price"].notna().to_numpy()
    out = pd.DataFrame({"id": rows["id"].astype(str).to_numpy(), "date": rows["date"].to_numpy()})
    for name, model in models.items():
        values = np.clip(model.predict(rows[MODEL_FEATURES]), 0, None)
        out[{"point": "forecast"}.get(name, name)] = np.where(on_sale, values, 0.0)
    if "lower" in out and "upper" in out:
        # Separately trained quantile models can cross; keep the interval ordered.
        out["lower"] = np.minimum(out["lower"], out["forecast"])
        out["upper"] = np.maximum(out["upper"], out["forecast"])
    return out


def make_forecaster(long: pd.DataFrame, settings: ModelSettings):
    """Build a forecaster for backtest.run_backtest from a long M5 table of one store.

    Features are computed once. That is safe because every sales-based feature is
    at least DEFAULT_MIN_LAG days old, so for horizons up to DEFAULT_MIN_LAG the
    features of a test day only use sales up to the origin. Calendar and price
    columns are known in advance. Training rows never go past the origin.
    """
    features = add_features(long)

    def forecaster(history: pd.DataFrame, horizon: int) -> pd.DataFrame:
        if horizon > DEFAULT_MIN_LAG:
            raise ValueError(f"horizon must be at most {DEFAULT_MIN_LAG} days (feature lag)")
        origin = history["date"].max()
        models = train_models(training_rows(features, origin, settings.train_days), settings)
        test = features[
            (features["date"] > origin) & (features["date"] <= origin + pd.Timedelta(days=horizon))
        ]
        return predict(models, test)

    return forecaster


def save_models(models: dict[str, lgb.Booster], folder: Path, metadata: dict) -> list[Path]:
    """Save each booster in LightGBM's own text format plus a metadata JSON.

    The text format needs no pickle, so loading a model file cannot run arbitrary code.
    """
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in models.items():
        path = folder / f"{name}.txt"
        model.save_model(str(path))
        written.append(path)
    meta_path = folder / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2, default=str) + "\n", encoding="utf-8")
    written.append(meta_path)
    return written


def load_models(folder: Path) -> tuple[dict[str, lgb.Booster], dict]:
    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    models = {
        name: lgb.Booster(model_file=str(folder / f"{name}.txt")) for name in metadata["models"]
    }
    return models, metadata
