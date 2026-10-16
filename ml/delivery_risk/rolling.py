"""Rolling monthly simulation of the delivery-risk model (P3-T2b plan, see the work log).

At the start T of each month we pretend to deploy the model:
- it may learn only from orders whose outcome was already known (delivered before T);
- it scores the orders purchased during that month;
- an alert flags the riskiest 10%, using a cut-off taken from the scores of the
  orders purchased in the 8 weeks before T (so no information from month M is used).

Two calibration variants are compared:
- "none":          train on all outcomes known before T.
- "recent_platt":  train on outcomes known before T - 56 days, then Platt-calibrate on
                   the outcomes that became known in the last 56 days, so probabilities
                   follow the recent late rate.

From the `ml` folder:
    python -m delivery_risk.rolling ../data/raw/olist --output report.json
"""

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import sklearn

from delivery_risk.evaluation import PlattCalibrator, all_metrics, threshold_metrics
from delivery_risk.models import MODELS, predict
from delivery_risk.olist_data import FILES, build_orders, load_tables
from demand_forecasting.backtest import file_sha256, git_commit

DEVELOPMENT_MONTHS = pd.date_range("2017-07-01", "2018-03-01", freq="MS")  # 9 months
TEST_MONTHS = pd.date_range("2018-04-01", "2018-08-01", freq="MS")  # 5 months, used once
RECENT = pd.Timedelta(days=56)
ALERT_SHARE = 0.10  # flag the riskiest 10% (a fixed review capacity, not tuned)
VARIANTS = ("none", "recent_platt")
SELECTION_TIE = 0.005

Scorer = Callable[[pd.DataFrame], np.ndarray]


def known_before(orders: pd.DataFrame, moment: pd.Timestamp) -> pd.DataFrame:
    """Orders whose outcome (late or not) was known before `moment`."""
    return orders[orders["outcome_known_at"] < moment]


def fit_recent_platt(orders: pd.DataFrame, start: pd.Timestamp, model_name: str):
    """Model trained on outcomes known before start - 56 days, plus a Platt calibrator
    fitted on the outcomes that became known in the 56 days before `start`."""
    model = MODELS[model_name](known_before(orders, start - RECENT))
    recent = orders[
        (orders["outcome_known_at"] >= start - RECENT) & (orders["outcome_known_at"] < start)
    ]
    calibrator = PlattCalibrator().fit(recent["late"], predict(model, recent))
    return model, calibrator


def fit_scorer(orders: pd.DataFrame, start: pd.Timestamp, model_name: str, variant: str) -> Scorer:
    """Train (and maybe calibrate) a model as it could have been at time `start`."""
    if variant == "none":
        model = MODELS[model_name](known_before(orders, start))
        return lambda rows: predict(model, rows)
    if variant == "recent_platt":
        model, calibrator = fit_recent_platt(orders, start, model_name)
        return lambda rows: calibrator.predict(predict(model, rows))
    raise ValueError(f"unknown variant {variant!r}")


def score_month(
    orders: pd.DataFrame, start: pd.Timestamp, model_name: str, variant: str
) -> pd.DataFrame:
    """Scores, alert cut-off and outcomes for the orders purchased in the month from `start`."""
    end = start + pd.offsets.MonthBegin(1)
    month = orders[
        (orders["order_purchase_timestamp"] >= start) & (orders["order_purchase_timestamp"] < end)
    ]
    recent_purchases = orders[
        (orders["order_purchase_timestamp"] >= start - RECENT)
        & (orders["order_purchase_timestamp"] < start)
    ]
    scorer = fit_scorer(orders, start, model_name, variant)
    cutoff = float(np.quantile(scorer(recent_purchases), 1 - ALERT_SHARE))
    return pd.DataFrame(
        {
            "month": start.strftime("%Y-%m"),
            "late": month["late"].to_numpy(),
            "score": scorer(month),
            "cutoff": cutoff,
        }
    )


def summarize(scored: pd.DataFrame) -> dict:
    y, p = scored["late"].to_numpy(), scored["score"].to_numpy()
    metrics = all_metrics(y, p)
    flags = p >= scored["cutoff"].to_numpy()
    alert = threshold_metrics(y, np.where(flags, 1.0, 0.0), 0.5)
    alert.pop("threshold")
    return {**metrics, "alert_rule_top_10pct": alert}


def evaluate(orders: pd.DataFrame, months, model_name: str, variant: str) -> dict:
    scored = pd.concat([score_month(orders, m, model_name, variant) for m in months])
    per_month = {month: summarize(part) for month, part in scored.groupby("month")}
    return {"pooled": summarize(scored), "per_month": per_month}


def mean_over_months(result: dict, metric: str) -> float:
    return float(np.mean([month[metric] for month in result["per_month"].values()]))


def choose(development: dict) -> tuple[str, str]:
    """Pre-registered rule: model by mean PR-AUC (variant "none"), then calibration by mean ECE."""
    pr_auc = {name: mean_over_months(development[name]["none"], "pr_auc") for name in MODELS}
    best = max(pr_auc.values())
    tied = [name for name in MODELS if best - pr_auc[name] <= SELECTION_TIE]
    model = min(tied, key=lambda name: mean_over_months(development[name]["none"], "brier"))
    variant = min(VARIANTS, key=lambda v: mean_over_months(development[model][v], "ece"))
    return model, variant


def run(raw_dir: Path, checkpoint: Path | None = None) -> dict:
    started = time.perf_counter()
    orders, _ = build_orders(load_tables(raw_dir))
    development = {
        name: {variant: evaluate(orders, DEVELOPMENT_MONTHS, name, variant) for variant in VARIANTS}
        for name in MODELS
    }
    model, variant = choose(development)
    summary = {
        name: {
            variant_name: {
                "mean_pr_auc": round(mean_over_months(result, "pr_auc"), 4),
                "mean_brier": round(mean_over_months(result, "brier"), 4),
                "mean_ece": round(mean_over_months(result, "ece"), 4),
            }
            for variant_name, result in variants.items()
        }
        for name, variants in development.items()
    }
    if checkpoint:
        partial = {
            "status": "development finished; test not run yet",
            "development_summary": summary,
            "chosen": {"model": model, "calibration": variant},
        }
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(json.dumps(partial, indent=2) + "\n", encoding="utf-8", newline="\n")

    test = evaluate(orders, TEST_MONTHS, model, variant)
    paths = {name: Path(raw_dir) / file for name, file in FILES.items()}
    return {
        "plan": "docs/CLAUDE_WORK_LOG.md, 'P3-T2b plan' (written before running)",
        "dataset": "Olist Brazilian E-Commerce (public data); not ChainPilot's simulated suppliers",
        "development_months": [m.strftime("%Y-%m") for m in DEVELOPMENT_MONTHS],
        "test_months": [m.strftime("%Y-%m") for m in TEST_MONTHS],
        "development_summary": summary,
        "development": development,
        "chosen": {"model": model, "calibration": variant},
        "alert_rule": (
            f"flag the riskiest {ALERT_SHARE:.0%}; cut-off from the previous 56 days of orders"
        ),
        "test": test,
        "provenance": {
            "git_commit": git_commit(),
            "scikit_learn": sklearn.__version__,
            "lightgbm": lgb.__version__,
            "data_sha256": {name: file_sha256(path) for name, path in paths.items()},
        },
        "runtime_seconds": round(time.perf_counter() - started, 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m delivery_risk.rolling")
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(args.raw_dir, checkpoint=args.output)
    except FileNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(
        f"Development (mean over {len(DEVELOPMENT_MONTHS)} months): "
        f"{json.dumps(result['development_summary'])}"
    )
    print(f"Chosen: {result['chosen']}")
    print(f"Test pooled: {json.dumps(result['test']['pooled'])}")
    if args.output:
        report = json.dumps(result, indent=2) + "\n"
        args.output.write_text(report, encoding="utf-8", newline="\n")
        print(f"Report written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
