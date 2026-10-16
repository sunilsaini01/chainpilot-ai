"""Rolling-origin backtests: how good would each forecast have been in the past?

For each forecast origin (a cut-off date) the forecaster sees only sales up to
and including that date and predicts the next `horizon` days, which we then
compare with what really happened. Origins are spaced one horizon apart at the
end of the data, so the test windows do not overlap:

    history ......................| test 1 |
    history ...............................| test 2 |
    history ........................................| test 3 |   <- last day of data

Command line (from the `ml` folder):
    python -m demand_forecasting.backtest ../data/raw/m5 --store CA_1
    python -m demand_forecasting.backtest ../data/raw/m5 --all-stores
    python -m demand_forecasting.backtest ../data/raw/m5 --all-stores --output report.json
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from demand_forecasting import m5_data
from demand_forecasting.baselines import BASELINES
from demand_forecasting.conformal import ConformalIntervals
from demand_forecasting.lgbm_model import ModelSettings, make_forecaster
from demand_forecasting.metrics import (
    bias,
    mae,
    rmsse_per_series,
    rmsse_scales,
    sales_value_weights,
    wape,
)

Forecaster = Callable[[pd.DataFrame, int], pd.DataFrame]

# The spec asks for 7-, 14- and 28-day forecasts; we score the first 7, 14 and 28 days.
HORIZON_WINDOWS = (7, 14, 28)
ALL_STORES = ["CA_1", "CA_2", "CA_3", "CA_4", "TX_1", "TX_2", "TX_3", "WI_1", "WI_2", "WI_3"]


def make_origins(last_date: pd.Timestamp, horizon: int, n_origins: int) -> list[pd.Timestamp]:
    """Cut-off dates, oldest first, so the last test window ends on `last_date`."""
    if n_origins < 1 or horizon < 1:
        raise ValueError("horizon and n_origins must be at least 1")
    return [last_date - pd.Timedelta(days=horizon * k) for k in range(n_origins, 0, -1)]


def run_backtest(
    series: pd.DataFrame, forecaster: Forecaster, origins: list[pd.Timestamp], horizon: int
) -> pd.DataFrame:
    """Forecast from every origin. Returns rows of origin, id, date, step, actual, forecast.

    `series` has columns id, date, sales. The forecaster only receives rows up to
    the origin, so it cannot see the answers.
    """
    results = []
    for origin in origins:
        history = series[series["date"] <= origin]
        future = series[
            (series["date"] > origin) & (series["date"] <= origin + pd.Timedelta(days=horizon))
        ]
        if future["date"].nunique() != horizon:
            raise ValueError(f"not enough data after origin {origin.date()} for {horizon} days")

        forecast = forecaster(history, horizon)

        # Guard: the forecast must cover exactly the test days, nothing earlier.
        if forecast["date"].min() <= origin or forecast["date"].max() > future["date"].max():
            raise ValueError("forecast dates are outside the test window")
        merged = (
            future[["id", "date", "sales"]]
            .assign(id=future["id"].astype(str))
            .merge(
                forecast.assign(id=forecast["id"].astype(str)),
                on=["id", "date"],
                how="left",
                validate="one_to_one",
            )
        )
        if merged["forecast"].isna().any():
            raise ValueError("the forecaster did not return a value for every series and day")
        merged["origin"] = origin
        merged["step"] = (merged["date"] - origin).dt.days
        results.append(merged.rename(columns={"sales": "actual"}))
    return pd.concat(results, ignore_index=True)


def score(
    results: pd.DataFrame,
    scales_by_origin: dict[pd.Timestamp, pd.Series],
    weights_by_origin: dict[pd.Timestamp, pd.Series] | None = None,
) -> list[dict]:
    """Metrics for each horizon window (first 7, 14, 28 days), pooled over all origins.

    WAPE and bias are computed from summed errors; RMSSE is averaged over every
    (origin, series) pair, each scaled by its own history up to that origin. With
    `weights_by_origin` (sales value before each origin) a weighted RMSSE is added.
    """
    rows = []
    for window in HORIZON_WINDOWS:
        part = results[results["step"] <= window]
        if part.empty or part["step"].max() < window:
            continue
        actual = part["actual"].to_numpy(dtype=float)
        forecast = part["forecast"].to_numpy(dtype=float)
        rmsse_values, rmsse_counts = [], []
        weighted_sum, weight_total = 0.0, 0.0
        for origin, by_origin in part.groupby("origin"):
            per_series = rmsse_per_series(by_origin, scales_by_origin[origin])
            rmsse_values.append(float(per_series.sum()))
            rmsse_counts.append(int(per_series.size))
            if weights_by_origin is not None:
                weights = weights_by_origin[origin].reindex(per_series.index).fillna(0)
                weighted_sum += float((per_series * weights).sum())
                weight_total += float(weights.sum())
        weighted = (
            {"rmsse_weighted": round(weighted_sum / weight_total, 4)}
            if weights_by_origin is not None and weight_total > 0
            else {}
        )
        rows.append(
            {
                "horizon_days": window,
                "mae": round(mae(actual, forecast), 4),
                "wape": round(wape(actual, forecast), 4),
                "bias": round(bias(actual, forecast), 4),
                "rmsse": round(sum(rmsse_values) / sum(rmsse_counts), 4),
                "rmsse_series": int(sum(rmsse_counts)),
                **weighted,
                "actual_units": int(actual.sum()),
                **interval_metrics(part),
            }
        )
    return rows


def interval_metrics(part: pd.DataFrame) -> dict[str, float]:
    """For models with an 80% interval (columns lower, upper): how often the actual
    falls inside (ideal 0.80), the average width in units, and the average pinball
    loss of the two bounds (lower is better; it rewards narrow but honest intervals)."""
    if "lower" not in part or "upper" not in part:
        return {}
    actual = part["actual"].to_numpy(dtype=float)
    lower = part["lower"].to_numpy(dtype=float)
    upper = part["upper"].to_numpy(dtype=float)
    inside = (actual >= lower) & (actual <= upper)
    return {
        "interval_coverage_80": round(float(inside.mean()), 4),
        "interval_width": round(float(np.mean(upper - lower)), 4),
        "pinball_10_90": round((pinball(actual, lower, 0.1) + pinball(actual, upper, 0.9)) / 2, 4),
    }


def pinball(actual: np.ndarray, quantile_forecast: np.ndarray, q: float) -> float:
    """Quantile (pinball) loss: under-forecasts cost q per unit, over-forecasts 1 - q."""
    error = actual - quantile_forecast
    return float(np.mean(np.maximum(q * error, (q - 1) * error)))


def weights_for(long: pd.DataFrame, origins: list[pd.Timestamp]) -> dict[pd.Timestamp, pd.Series]:
    """Weighted-RMSSE weights per origin: dollar sales in the 28 days up to that origin."""
    columns = ["id", "date", "sales", "sell_price"]
    return {
        origin: sales_value_weights(long.loc[long["date"] <= origin, columns]) for origin in origins
    }


def scales_for(series: pd.DataFrame, origins: list[pd.Timestamp]) -> dict[pd.Timestamp, pd.Series]:
    """RMSSE scales per origin, each from history up to that origin only (no leakage)."""
    scales = {}
    for origin in origins:
        scale = rmsse_scales(series[series["date"] <= origin])
        scale.index = scale.index.astype(str)
        scales[origin] = scale
    return scales


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "describe", "--always", "--dirty"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


Factory = Callable[[pd.DataFrame], Forecaster]  # builds a forecaster from one store's long table


def baseline_factories() -> dict[str, Factory]:
    return {name: (lambda long, fn=fn: fn) for name, fn in BASELINES.items()}


def lightgbm_factory(settings: ModelSettings) -> Factory:
    return lambda long: make_forecaster(long, settings)


def backtest_stores(
    raw_dir: Path,
    stores: list[str],
    horizon: int,
    n_origins: int,
    factories: dict[str, Factory] | None = None,
    end_date: pd.Timestamp | None = None,
    intervals: dict[str, ConformalIntervals] | None = None,
) -> tuple[dict[str, object], dict[str, pd.DataFrame]]:
    """Backtest every model for each store, keeping one store in memory at a time.

    `end_date` moves the last test window earlier (used for the validation period);
    by default it ends on the last day of data. If `intervals` has calibrated bounds
    for a model, they are added to its forecasts and scored too.
    Returns the report and, per model, all result rows (for calibration).
    """
    factories = factories or baseline_factories()
    paths = m5_data.find_files(raw_dir)
    calendar = m5_data.load_calendar(paths["calendar"])
    all_results: dict[str, list[pd.DataFrame]] = {name: [] for name in factories}
    all_scales: dict[str, dict] = {}
    all_weights: dict[str, dict] = {}
    origins: list[pd.Timestamp] = []
    store_rows = []

    for store in stores:
        sales = m5_data.load_sales(paths["sales"], [store])
        prices = m5_data.load_prices(paths["prices"], [store])
        long = m5_data.to_long(sales, calendar, prices)
        series = long[["id", "date", "sales"]]
        origins = make_origins(end_date or series["date"].max(), horizon, n_origins)
        scales = scales_for(series, origins)
        weights = weights_for(long, origins)
        all_weights[store] = weights
        for origin, scale in scales.items():
            all_scales.setdefault(store, {})[origin] = scale
        for name, factory in factories.items():
            print(f"  {store}: {name}", file=sys.stderr, flush=True)
            results = run_backtest(series, factory(long), origins, horizon)
            if intervals and name in intervals:
                results = intervals[name].apply(results)
            results["store"] = store
            all_results[name].append(results)
            store_rows.append(
                {"store": store, "model": name, "metrics": score(results, scales, weights)}
            )
        del long, series, sales, prices

    # Pool all stores: ids are unique across stores, so scales can simply be combined.
    pooled_scales = {
        origin: pd.concat([all_scales[store][origin] for store in stores]) for origin in origins
    }
    pooled_weights = {
        origin: pd.concat([all_weights[store][origin] for store in stores]) for origin in origins
    }
    pooled = {name: pd.concat(parts, ignore_index=True) for name, parts in all_results.items()}
    overall = [
        {"model": name, "metrics": score(results, pooled_scales, pooled_weights)}
        for name, results in pooled.items()
    ]
    report = {
        "dataset": "M5 Forecasting - Accuracy (sales_train_validation.csv)",
        "stores": stores,
        "horizon_days": horizon,
        "origins": [origin.date().isoformat() for origin in origins],
        "test_windows": [
            [
                (origin + pd.Timedelta(days=1)).date().isoformat(),
                (origin + pd.Timedelta(days=horizon)).date().isoformat(),
            ]
            for origin in origins
        ],
        "overall": overall,
        "by_store": store_rows,
        "provenance": {
            "git_commit": git_commit(),
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "lightgbm": lgb.__version__,
            "data_sha256": {name: file_sha256(path) for name, path in paths.items()},
        },
    }
    return report, pooled


def format_table(report: dict[str, object]) -> str:
    header = f"{'model':<20}{'horizon':>8}{'MAE':>9}{'WAPE':>9}{'bias':>9}{'RMSSE':>9}"
    lines = [header + f"{'cover80':>9}{'width':>8}"]
    for entry in report["overall"]:
        for row in entry["metrics"]:
            interval = (
                f"{row['interval_coverage_80']:>9.3f}{row['interval_width']:>8.2f}"
                if "interval_coverage_80" in row
                else ""
            )
            lines.append(
                f"{entry['model']:<20}{row['horizon_days']:>8}{row['mae']:>9.3f}"
                f"{row['wape']:>9.3f}{row['bias']:>+9.3f}{row['rmsse']:>9.3f}{interval}"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m demand_forecasting.backtest")
    parser.add_argument("raw_dir", type=Path)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--store", action="append", help="e.g. CA_1 (repeatable)")
    which.add_argument("--all-stores", action="store_true")
    parser.add_argument("--horizon", type=int, default=28)
    parser.add_argument("--origins", type=int, default=3)
    parser.add_argument("--output", type=Path, help="write the full report as JSON")
    parser.add_argument(
        "--with-lightgbm", action="store_true", help="also backtest both LightGBM layouts (slow)"
    )
    args = parser.parse_args(argv)

    stores = ALL_STORES if args.all_stores else args.store
    started = time.perf_counter()
    try:
        factories = baseline_factories()
        if args.with_lightgbm:
            factories["lightgbm_single"] = lightgbm_factory(ModelSettings())
            factories["lightgbm_weekly"] = lightgbm_factory(ModelSettings(weekly_models=True))
        report, _ = backtest_stores(args.raw_dir, stores, args.horizon, args.origins, factories)
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    report["runtime_seconds"] = round(time.perf_counter() - started, 1)

    print(f"Stores: {', '.join(stores)} | origins: {', '.join(report['origins'])}")
    print(format_table(report))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"Report written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
