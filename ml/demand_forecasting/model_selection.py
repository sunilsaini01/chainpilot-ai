"""Choose the forecasting model on a validation period, then test it once.

The plan was fixed before any numbers were seen (docs/CLAUDE_WORK_LOG.md,
"P2-T3b plan"):

1. Validation: 3 origins whose 28-day windows end on VALIDATION_END, the day
   before the test windows start. Candidates: LightGBM single model and
   LightGBM weekly models; reference: 28-day moving average.
2. Selection rule: lowest mean WAPE over the 7-, 14- and 28-day horizons; ties
   within 0.001 are broken by mean RMSSE.
3. Calibrated 80% intervals for each model from its validation errors (conformal.py).
4. Test: the chosen model and the moving average, once, on the usual test windows
   (ending on the last day of data), with their calibrated intervals.

From the `ml` folder (all stores take about an hour):
    python -m demand_forecasting.model_selection ../data/raw/m5 --all-stores \
        --output ../docs/results/p2_model_selection.json
"""

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from demand_forecasting.backtest import (
    ALL_STORES,
    backtest_stores,
    baseline_factories,
    format_table,
    lightgbm_factory,
)
from demand_forecasting.conformal import ConformalIntervals
from demand_forecasting.lgbm_model import ModelSettings

VALIDATION_END = pd.Timestamp("2016-01-31")
HORIZON, N_ORIGINS = 28, 3
REFERENCE = "moving_average_28"
TIE_TOLERANCE = 0.001

CANDIDATES = {
    "lightgbm_single": ModelSettings(weekly_models=False),
    "lightgbm_weekly": ModelSettings(weekly_models=True),
}


def mean_metric(report: dict, model: str, metric: str) -> float:
    rows = next(entry["metrics"] for entry in report["overall"] if entry["model"] == model)
    return sum(row[metric] for row in rows) / len(rows)


def choose(report: dict, candidates: list[str]) -> tuple[str, dict[str, dict[str, float]]]:
    """Apply the selection rule. Returns the winner and the numbers it was based on."""
    scores = {
        name: {
            "mean_wape": mean_metric(report, name, "wape"),
            "mean_rmsse": mean_metric(report, name, "rmsse"),
        }
        for name in candidates
    }
    best_wape = min(score["mean_wape"] for score in scores.values())
    tied = [name for name in candidates if scores[name]["mean_wape"] - best_wape <= TIE_TOLERANCE]
    winner = min(tied, key=lambda name: scores[name]["mean_rmsse"])
    return winner, scores


def run(
    raw_dir: Path,
    stores: list[str],
    candidates: dict[str, ModelSettings],
    checkpoint: Path | None = None,
) -> dict:
    started = time.perf_counter()
    reference = {REFERENCE: baseline_factories()[REFERENCE]}

    # 1. Validation (never touches the test windows).
    factories = {**reference, **{n: lightgbm_factory(s) for n, s in candidates.items()}}
    validation, validation_results = backtest_stores(
        raw_dir, stores, HORIZON, N_ORIGINS, factories, end_date=VALIDATION_END
    )
    # 2. Selection.
    winner, scores = choose(validation, list(candidates))
    if checkpoint:
        # Save the expensive validation step before anything else can fail.
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        partial = {
            "status": "validation finished; test not run yet",
            "validation": validation,
            "validation_scores": scores,
            "chosen": winner,
        }
        checkpoint.write_text(json.dumps(partial, indent=2) + "\n", encoding="utf-8")
    # 3. Calibrated intervals from validation errors.
    intervals = {
        name: ConformalIntervals.fit(validation_results[name]) for name in [REFERENCE, winner]
    }
    # 4. One test run.
    test_factories = {**reference, winner: lightgbm_factory(candidates[winner])}
    test, _ = backtest_stores(
        raw_dir, stores, HORIZON, N_ORIGINS, test_factories, intervals=intervals
    )

    return {
        "plan": "docs/CLAUDE_WORK_LOG.md, 'P2-T3b plan' (written before running)",
        "selection_rule": "lowest mean WAPE over 7/14/28 days on validation; ties within "
        f"{TIE_TOLERANCE} broken by mean RMSSE",
        "candidates": {name: asdict(settings) for name, settings in candidates.items()},
        "validation": validation,
        "validation_scores": scores,
        "chosen": winner,
        "conformal": {name: interval.to_dict() for name, interval in intervals.items()},
        "test": test,
        "runtime_seconds": round(time.perf_counter() - started, 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m demand_forecasting.model_selection")
    parser.add_argument("raw_dir", type=Path)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--store", action="append")
    which.add_argument("--all-stores", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        stores = ALL_STORES if args.all_stores else args.store
        result = run(args.raw_dir, stores, CANDIDATES, checkpoint=args.output)
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Validation origins: {', '.join(result['validation']['origins'])}")
    print(format_table(result["validation"]))
    print(f"\nChosen on validation: {result['chosen']}  {result['validation_scores']}")
    print(f"\nTest origins: {', '.join(result['test']['origins'])}")
    print(format_table(result["test"]))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"Report written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
