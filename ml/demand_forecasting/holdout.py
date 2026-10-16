"""Score a published forecast file against the real sales of the forecast period.

The M5 download includes sales_train_evaluation.csv, which has 28 more days
(d_1914..d_1941 = 2016-04-25..2016-05-22) than the training file. No training,
validation or test step uses it, so it is a final, untouched check of the
published forecasts. The 28-day moving average is scored on the same days.

From the `ml` folder:
    python -m demand_forecasting.holdout ../data/raw/m5 \
        ../data/processed/forecasts/m5_lightgbm_weekly_2016-04-24
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from demand_forecasting.backtest import HORIZON_WINDOWS
from demand_forecasting.metrics import bias, rmsse_per_series, wape, weighted_rmsse

EVALUATION_FILE = "sales_train_evaluation.csv"


def history_scales(history: pd.DataFrame) -> pd.Series:
    """RMSSE scale per series from its known history (rows = series, columns = days):
    mean squared day-to-day change, counted from the first sale (as metrics.rmsse_scales)."""
    values = history.to_numpy(dtype="float32")
    sold = values > 0
    first_sale = np.where(sold.any(axis=1), sold.argmax(axis=1), values.shape[1])
    squared_changes = np.diff(values, axis=1) ** 2
    # The change into day j+1 counts only if day j is on or after the first sale.
    counted = np.arange(values.shape[1] - 1)[None, :] >= first_sale[:, None]
    counts = counted.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        scale = (squared_changes * counted).sum(axis=1) / counts
    scale = pd.Series(scale, index=history.index)
    return scale.where(scale > 0)


def recent_sales_value(recent: pd.DataFrame, raw_dir: Path) -> pd.Series:
    """Weighted-RMSSE weights: dollar sales per series in the given (last 28) known days."""
    calendar = pd.read_csv(raw_dir / "calendar.csv", usecols=["d", "wm_yr_wk"])
    prices = pd.read_csv(raw_dir / "sell_prices.csv")
    long = recent.reset_index().melt(id_vars="series_id", var_name="d", value_name="sales")
    # "FOODS_3_090_CA_1_validation" -> item "FOODS_3_090", store "CA" + "_" + "1".
    parts = long["series_id"].str.rsplit("_", n=3, expand=True)
    long["item_id"] = parts[0]
    long["store_id"] = parts[1] + "_" + parts[2]
    long = long.merge(calendar, on="d").merge(
        prices, on=["store_id", "item_id", "wm_yr_wk"], how="left", validate="many_to_one"
    )
    value = long["sales"] * long["sell_price"].fillna(0)
    return value.groupby(long["series_id"]).sum()


def rmsse_both(part: pd.DataFrame, scales: pd.Series, weights: pd.Series) -> dict[str, float]:
    """Plain and sales-value-weighted mean RMSSE, for the model and the moving average."""
    scores = {}
    for name, column in [("model", "forecast"), ("moving_average_28", "ma28")]:
        results = part[["series_id", "actual", column]].rename(
            columns={"series_id": "id", column: "forecast"}
        )
        per_series = rmsse_per_series(results, scales)
        scores[f"rmsse_{name}"] = round(float(per_series.mean()), 4)
        scores[f"rmsse_weighted_{name}"] = round(weighted_rmsse(per_series, weights), 4)
    return scores


def holdout_scores(raw_dir: Path, forecast_folder: Path) -> dict:
    forecasts = pd.read_csv(forecast_folder / "forecasts.csv")
    manifest = json.loads((forecast_folder / "manifest.json").read_text(encoding="utf-8"))
    evaluation = pd.read_csv(raw_dir / EVALUATION_FILE)
    day_columns = [c for c in evaluation.columns if c.startswith("d_")]
    last_known = int(day_columns[-1][2:]) - int(manifest["horizon_days"])  # e.g. 1913
    # Same series, named "..._evaluation" in this file. Used as the index rather than
    # added as a column, because adding a column to this 1,900-column table is slow.
    sales = evaluation[day_columns].set_axis(
        evaluation["id"].str.replace("_evaluation", "_validation").rename("series_id"), axis=0
    )

    future = [f"d_{last_known + step}" for step in range(1, manifest["horizon_days"] + 1)]
    # Last 28 known days (fewer if the history is shorter), as in baselines.moving_average_28.
    recent = [f"d_{day}" for day in range(max(1, last_known - 27), last_known + 1)]
    actual = (
        sales[future].reset_index().melt(id_vars="series_id", var_name="d", value_name="actual")
    )
    actual["step"] = actual["d"].str[2:].astype(int) - last_known
    moving_average = sales[recent].mean(axis=1).rename("ma28")

    merged = forecasts.merge(
        actual[["series_id", "step", "actual"]], on=["series_id", "step"], validate="one_to_one"
    ).merge(moving_average, left_on="series_id", right_index=True, validate="many_to_one")
    if len(merged) != len(forecasts):
        raise ValueError("not every forecast row has an actual value")
    known = [f"d_{day}" for day in range(1, last_known + 1)]
    scales = history_scales(sales[known])
    weights = recent_sales_value(sales[recent], raw_dir)

    rows = []
    for window in HORIZON_WINDOWS:
        part = merged[merged["step"] <= window]
        actual_units = part["actual"].to_numpy(dtype=float)
        inside = (part["actual"] >= part["lower"]) & (part["actual"] <= part["upper"])
        rows.append(
            {
                "horizon_days": window,
                "wape_model": round(wape(actual_units, part["forecast"].to_numpy(float)), 4),
                "wape_moving_average_28": round(
                    wape(actual_units, part["ma28"].to_numpy(float)), 4
                ),
                "bias_model": round(bias(actual_units, part["forecast"].to_numpy(float)), 4),
                "bias_moving_average_28": round(
                    bias(actual_units, part["ma28"].to_numpy(float)), 4
                ),
                "interval_coverage_80": round(float(np.mean(inside)), 4),
                **rmsse_both(part, scales, weights),
            }
        )
    return {
        "forecast_run": forecast_folder.name,
        "run_key": manifest["run_key"],
        "actuals": f"{EVALUATION_FILE}, d_{last_known + 1}..d_{int(day_columns[-1][2:])}",
        "rows": len(merged),
        "metrics": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m demand_forecasting.holdout")
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("forecast_folder", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = holdout_scores(args.raw_dir, args.forecast_folder)
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    for row in result["metrics"]:
        print(row)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
