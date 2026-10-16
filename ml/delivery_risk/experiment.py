"""Run the pre-registered P3-T2 experiment (plan: docs/CLAUDE_WORK_LOG.md, "P3-T2 plan").

1. Fit logistic regression and LightGBM on the training period (2017).
2. Score both on validation (Jan-Mar 2018); choose by PR-AUC (ties within 0.005:
   lower Brier).
3. Recalibrate the chosen model's scores on validation (Platt scaling) and pick
   the F1-maximising threshold on the calibrated validation scores.
4. Apply model + calibration + threshold once to the test period (Apr-Aug 2018).

From the `ml` folder:
    python -m delivery_risk.experiment ../data/raw/olist --output report.json
"""

import argparse
import json
import platform
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import sklearn

from delivery_risk.evaluation import (
    PlattCalibrator,
    all_metrics,
    best_f1_threshold,
    reliability_table,
)
from delivery_risk.models import LIGHTGBM_PARAMS, LIGHTGBM_ROUNDS, MODELS, predict
from delivery_risk.olist_data import FILES, SPLITS, build_orders, load_tables
from demand_forecasting.backtest import file_sha256, git_commit

SELECTION_TIE = 0.005


def choose(validation_scores: dict[str, dict]) -> str:
    best = max(scores["pr_auc"] for scores in validation_scores.values())
    tied = [n for n, s in validation_scores.items() if best - s["pr_auc"] <= SELECTION_TIE]
    return min(tied, key=lambda name: validation_scores[name]["brier"])


def run(raw_dir: Path, checkpoint: Path | None = None) -> dict:
    started = time.perf_counter()
    orders, dropped = build_orders(load_tables(raw_dir))
    train, validation, test = (orders[orders["split"] == name] for name in SPLITS)

    # 1-2. Fit on train, compare on validation.
    models = {name: fit(train) for name, fit in MODELS.items()}
    validation_scores = {
        name: all_metrics(validation["late"], predict(model, validation))
        for name, model in models.items()
    }
    chosen = choose(validation_scores)
    if checkpoint:
        partial = {
            "status": "validation finished; test not run yet",
            "validation": validation_scores,
            "chosen": chosen,
        }
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(json.dumps(partial, indent=2) + "\n", encoding="utf-8", newline="\n")

    # 3. Calibrate and choose the threshold on validation.
    raw_validation = predict(models[chosen], validation)
    calibrator = PlattCalibrator().fit(validation["late"], raw_validation)
    calibrated_validation = calibrator.predict(raw_validation)
    threshold = best_f1_threshold(validation["late"].to_numpy(), calibrated_validation)

    # 4. One look at the test period.
    raw_test = predict(models[chosen], test)
    calibrated_test = calibrator.predict(raw_test)
    y_test = test["late"].to_numpy()

    paths = {name: Path(raw_dir) / file for name, file in FILES.items()}
    return {
        "plan": "docs/CLAUDE_WORK_LOG.md, 'P3-T2 plan' (written before training)",
        "dataset": "Olist Brazilian E-Commerce (public data); not ChainPilot's simulated suppliers",
        "splits": {
            name: {"from": start, "to": end, "orders": int((orders["split"] == name).sum())}
            for name, (start, end) in SPLITS.items()
        },
        "dropped_orders": dropped,
        "validation": validation_scores,
        "chosen": chosen,
        "calibration": calibrator.to_dict(),
        "validation_calibrated": all_metrics(validation["late"], calibrated_validation, threshold),
        "threshold": round(threshold, 4),
        "test": {
            "calibrated": all_metrics(y_test, calibrated_test, threshold),
            "uncalibrated": all_metrics(y_test, raw_test),
            "reliability_calibrated": reliability_table(y_test, calibrated_test),
            # For transparency only; the choice above was made on validation.
            "pr_auc_by_model": {
                name: round(float(all_metrics(y_test, predict(model, test))["pr_auc"]), 4)
                for name, model in models.items()
            },
        },
        "settings": {
            "lightgbm": LIGHTGBM_PARAMS,
            "lightgbm_rounds": LIGHTGBM_ROUNDS,
            "logistic_regression": "C=1.0, max_iter=2000, median impute, standardise, one-hot",
        },
        "provenance": {
            "git_commit": git_commit(),
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "lightgbm": lgb.__version__,
            "data_sha256": {name: file_sha256(path) for name, path in paths.items()},
        },
        "runtime_seconds": round(time.perf_counter() - started, 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m delivery_risk.experiment")
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(args.raw_dir, checkpoint=args.output)
    except FileNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Validation (choose by PR-AUC): {json.dumps(result['validation'])}")
    print(
        f"Chosen: {result['chosen']} | calibration {result['calibration']} "
        f"| threshold {result['threshold']}"
    )
    print(f"Test (calibrated): {json.dumps(result['test']['calibrated'])}")
    if args.output:
        report = json.dumps(result, indent=2) + "\n"
        args.output.write_text(report, encoding="utf-8", newline="\n")
        print(f"Report written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
