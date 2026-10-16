"""P4-T2: replay real M5 demand through the inventory policies (plan in the work log).

For each store: forecasts are made at every weekly review from the sales known
that day (moving average, and the weekly LightGBM retrained at each review), the
target levels are computed, and every policy is replayed day by day on the real
sales. The forecast inputs are cached because LightGBM is the slow part.

From the `ml` folder (about 30-60 minutes, mostly LightGBM):
    python -m inventory_sim.experiment ../data/raw/m5 \
        --output ../docs/results/p4_inventory_replay.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from demand_forecasting import m5_data
from demand_forecasting.backtest import file_sha256, git_commit
from demand_forecasting.baselines import moving_average_28
from demand_forecasting.conformal import ConformalIntervals
from demand_forecasting.lgbm_model import ModelSettings, make_forecaster
from inventory_sim.policies import (
    BASELINE_BUFFER_DAYS,
    PROTECTION_DAYS,
    SERVICE_LEVELS,
    baseline_targets,
    forecast_inputs,
    formula_targets,
)
from inventory_sim.replay import add_totals, baseline_stock_at, rates, replay, summarize

REPO_ROOT = Path(__file__).resolve().parents[2]
SELECTION_REPORT = REPO_ROOT / "docs" / "results" / "p2_model_selection.json"
DEFAULT_CACHE = REPO_ROOT / "data" / "processed" / "inventory_sim"
STORES = ["CA_1", "TX_1", "WI_1"]
FIRST_REVIEW = pd.Timestamp("2016-01-31")
REVIEWS = 11  # 2016-01-31 (starting stock) and every 7 days up to 2016-04-10
FIRST_DAY, LAST_DAY = pd.Timestamp("2016-02-01"), pd.Timestamp("2016-04-17")
LEAD_TIME_CHOICES = np.arange(5, 10)  # uniform whole days, mean 7
SEED = 2016
FORECASTERS = ["moving_average_28", "lightgbm_weekly"]


def review_dates() -> list[pd.Timestamp]:
    return [FIRST_REVIEW + pd.Timedelta(days=7 * k) for k in range(REVIEWS)]


def wide(long: pd.DataFrame, column: str, ids: list[str]) -> np.ndarray:
    """items x simulated days for one column of the long table."""
    days = long[(long["date"] >= FIRST_DAY) & (long["date"] <= LAST_DAY)]
    table = days.assign(id=days["id"].astype(str)).pivot(index="id", columns="date", values=column)
    return table.reindex(ids).to_numpy(dtype=float)


def store_inputs(long: pd.DataFrame, intervals: dict[str, ConformalIntervals]) -> pd.DataFrame:
    """Per review and item: 28-day sales and each forecaster's daily mean and std."""
    series = long[["id", "date", "sales"]]
    lightgbm = make_forecaster(long, ModelSettings(weekly_models=True))
    forecasters = {"moving_average_28": moving_average_28, "lightgbm_weekly": lightgbm}
    parts = []
    for review, origin in enumerate(review_dates()):
        history = series[series["date"] <= origin]
        last_28 = history[history["date"] > origin - pd.Timedelta(days=28)]
        frame = last_28.groupby("id", observed=True)["sales"].sum().rename("sales_28").to_frame()
        for name in FORECASTERS:
            started = time.perf_counter()
            forecast = intervals[name].apply(forecasters[name](history, PROTECTION_DAYS))
            inputs = forecast_inputs(forecast)
            frame = frame.join(inputs.add_prefix(f"{name}__"))
            print(
                f"    review {origin.date()} {name}: {time.perf_counter() - started:.0f} s",
                file=sys.stderr,
                flush=True,
            )
        parts.append(frame.assign(review=review))
    inputs = pd.concat(parts).reset_index()
    return inputs.assign(id=inputs["id"].astype(str))


def policy_targets(inputs: pd.DataFrame, ids: list[str]) -> dict[str, np.ndarray]:
    """items x reviews target levels for every policy setting."""
    by_review = [
        inputs[inputs["review"] == review].set_index("id").reindex(ids) for review in range(REVIEWS)
    ]
    targets = {}
    for buffer in BASELINE_BUFFER_DAYS:
        columns = [baseline_targets(frame["sales_28"].to_numpy(), buffer) for frame in by_review]
        targets[f"baseline_buffer_{buffer:g}d"] = np.column_stack(columns)
    for name in FORECASTERS:
        for level in SERVICE_LEVELS:
            columns = []
            for frame in by_review:
                one = frame[[f"{name}__daily_mean", f"{name}__daily_std"]]
                one.columns = ["daily_mean", "daily_std"]
                columns.append(formula_targets(one, level).to_numpy())
            targets[f"formula_{name}_{level:.2f}"] = np.column_stack(columns)
    return targets


def run(raw_dir: Path, cache_dir: Path, reuse: bool) -> dict:
    started = time.perf_counter()
    selection = json.loads(SELECTION_REPORT.read_text(encoding="utf-8"))
    intervals = {name: ConformalIntervals(**selection["conformal"][name]) for name in FORECASTERS}
    paths = m5_data.find_files(raw_dir)
    calendar = m5_data.load_calendar(paths["calendar"])
    cache_dir.mkdir(parents=True, exist_ok=True)

    totals: dict[str, list[dict]] = {}
    by_store: dict[str, dict] = {}
    for store_number, store in enumerate(STORES):
        print(f"  {store}", file=sys.stderr, flush=True)
        prices = m5_data.load_prices(paths["prices"], [store])
        long = m5_data.to_long(m5_data.load_sales(paths["sales"], [store]), calendar, prices)
        cache = cache_dir / f"inputs_{store}.csv"
        if reuse and cache.exists():
            inputs = pd.read_csv(cache, dtype={"id": str})
        else:
            inputs = store_inputs(long, intervals)
            inputs.to_csv(cache, index=False, lineterminator="\n")

        ids = sorted(inputs["id"].unique())
        demand = wide(long, "sales", ids)
        prices_wide = np.nan_to_num(wide(long, "sell_price", ids))
        if np.isnan(demand).any():
            raise ValueError(f"{store}: missing sales in the simulated days")
        rng = np.random.default_rng([SEED, store_number])
        lead_times = rng.choice(LEAD_TIME_CHOICES, size=(len(ids), REVIEWS))

        by_store[store] = {}
        for setting, targets in policy_targets(inputs, ids).items():
            total = summarize(replay(demand, targets, lead_times), demand, prices_wide)
            totals.setdefault(setting, []).append(total)
            by_store[store][setting] = rates(total)["fill_rate"]
        del long

    results = {setting: rates(add_totals(parts)) for setting, parts in totals.items()}
    return {
        "plan": "docs/CLAUDE_WORK_LOG.md, 'P4-T2 plan' (2026-10-16 18:40 UTC)",
        "dataset": "M5 sales as demand (censored by real stock-outs); stores " + ", ".join(STORES),
        "simulated_days": [FIRST_DAY.date().isoformat(), LAST_DAY.date().isoformat()],
        "reviews": [day.date().isoformat() for day in review_dates()],
        "lead_time_days": "uniform 5-9 (mean 7, std 1.41), same draws for every policy",
        "results": results,
        "fill_rate_by_store": by_store,
        "questions": answer_questions(results),
        "provenance": {
            "code": git_commit(),
            "data_sha256": {name: file_sha256(path) for name, path in paths.items()},
            "intervals": "docs/results/p2_model_selection.json (validation period)",
        },
        "runtime_seconds": round(time.perf_counter() - started, 1),
    }


def answer_questions(results: dict) -> dict:
    baseline = [value for key, value in results.items() if key.startswith("baseline")]
    target_95 = results["formula_lightgbm_weekly_0.95"]
    answers = {
        "a_lightgbm_95_cycle_service_level": target_95["cycle_service_level"],
        "a_reaches_at_least_0.93": target_95["cycle_service_level"] >= 0.93,
    }
    for name in FORECASTERS:
        for level in (0.90, 0.95):
            result = results[f"formula_{name}_{level:.2f}"]
            comparison = {"fill_rate": result["fill_rate"]}
            for metric in ("average_units_on_hand", "average_stock_value"):
                base = baseline_stock_at(result["fill_rate"], baseline, metric)
                comparison[metric] = result[metric]
                comparison[f"baseline_{metric}"] = None if base is None else round(base, 1)
                comparison[f"{metric}_vs_baseline"] = (
                    None if base is None else round(result[metric] / base - 1, 4)
                )
            answers[f"{name}_{level:.2f}_at_same_fill_rate"] = comparison
    return answers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m inventory_sim.experiment")
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--reuse", action="store_true", help="reuse cached forecast inputs")
    args = parser.parse_args(argv)
    report = run(args.raw_dir, args.cache_dir, args.reuse)
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report["results"], indent=1))
    print(json.dumps(report["questions"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
