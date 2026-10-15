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
from dataclasses import asdict
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from demand_forecasting import m5_data
from demand_forecasting.baselines import BASELINES
from demand_forecasting.lgbm_model import ModelSettings, make_forecaster
from demand_forecasting.metrics import bias, mae, mean_rmsse, rmsse_scales, wape

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


def score(results: pd.DataFrame, scales_by_origin: dict[pd.Timestamp, pd.Series]) -> list[dict]:
    """Metrics for each horizon window (first 7, 14, 28 days), pooled over all origins.

    WAPE and bias are computed from summed errors; RMSSE is averaged over every
    (origin, series) pair, each scaled by its own history up to that origin.
    """
    rows = []
    for window in HORIZON_WINDOWS:
        part = results[results["step"] <= window]
        if part.empty or part["step"].max() < window:
            continue
        actual = part["actual"].to_numpy(dtype=float)
        forecast = part["forecast"].to_numpy(dtype=float)
        rmsse_values, rmsse_counts = [], []
        for origin, by_origin in part.groupby("origin"):
            value, count = mean_rmsse(by_origin, scales_by_origin[origin])
            rmsse_values.append(value * count)
            rmsse_counts.append(count)
        rows.append(
            {
                "horizon_days": window,
                "mae": round(mae(actual, forecast), 4),
                "wape": round(wape(actual, forecast), 4),
                "bias": round(bias(actual, forecast), 4),
                "rmsse": round(sum(rmsse_values) / sum(rmsse_counts), 4),
                "rmsse_series": int(sum(rmsse_counts)),
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


def backtest_stores(
    raw_dir: Path,
    stores: list[str],
    horizon: int,
    n_origins: int,
    lightgbm_settings: ModelSettings | None = None,
) -> dict[str, object]:
    """Run every baseline (and LightGBM, if settings are given) for each store,
    keeping one store in memory at a time."""
    paths = m5_data.find_files(raw_dir)
    calendar = m5_data.load_calendar(paths["calendar"])
    model_names = [*BASELINES, *(["lightgbm"] if lightgbm_settings else [])]
    all_results: dict[str, list[pd.DataFrame]] = {name: [] for name in model_names}
    all_scales: dict[str, dict] = {}
    origins: list[pd.Timestamp] = []
    store_rows = []

    for store in stores:
        sales = m5_data.load_sales(paths["sales"], [store])
        prices = m5_data.load_prices(paths["prices"], [store])
        long = m5_data.to_long(sales, calendar, prices)
        series = long[["id", "date", "sales"]]
        origins = make_origins(series["date"].max(), horizon, n_origins)
        scales = scales_for(series, origins)
        for origin, scale in scales.items():
            all_scales.setdefault(store, {})[origin] = scale
        forecasters = dict(BASELINES)
        if lightgbm_settings:
            forecasters["lightgbm"] = make_forecaster(long, lightgbm_settings)
        for name, forecaster in forecasters.items():
            print(f"  {store}: {name}", file=sys.stderr, flush=True)
            results = run_backtest(series, forecaster, origins, horizon)
            results["store"] = store
            all_results[name].append(results)
            store_rows.append({"store": store, "model": name, "metrics": score(results, scales)})
        del long, series, sales, prices, forecasters

    # Pool all stores: ids are unique across stores, so scales can simply be combined.
    pooled_scales = {
        origin: pd.concat([all_scales[store][origin] for store in stores]) for origin in origins
    }
    overall = [
        {"model": name, "metrics": score(pd.concat(parts, ignore_index=True), pooled_scales)}
        for name, parts in all_results.items()
    ]
    return {
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
            "lightgbm": lgb.__version__,
            "lightgbm_settings": asdict(lightgbm_settings) if lightgbm_settings else None,
            "numpy": np.__version__,
            "data_sha256": {name: file_sha256(path) for name, path in paths.items()},
        },
    }


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
        "--with-lightgbm", action="store_true", help="also backtest the LightGBM model (slow)"
    )
    args = parser.parse_args(argv)

    stores = ALL_STORES if args.all_stores else args.store
    started = time.perf_counter()
    try:
        settings = ModelSettings() if args.with_lightgbm else None
        report = backtest_stores(args.raw_dir, stores, args.horizon, args.origins, settings)
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    report["runtime_seconds"] = round(time.perf_counter() - started, 1)

    print(f"Stores: {', '.join(stores)} | origins: {', '.join(report['origins'])}")
    print(format_table(report))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Report written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
