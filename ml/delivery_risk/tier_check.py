"""Check the published delivery-risk tiers against what actually happened (P3-T3).

The published scores contain no outcomes. This joins them to the real `late` label
afterwards and reports, per tier, how many orders were late. It is a second look
at the Apr-Aug 2018 test months (the first was P3-T2b); the daily top-10% rule was
fixed before this check and is not tuned on it.

From the `ml` folder:
    python -m delivery_risk.tier_check ../data/raw/olist \
        ../data/processed/delivery_risk/olist_logistic_2018-04-02_2018-08-31 \
        --output ../docs/results/p3_delivery_risk_tiers.json
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from delivery_risk.olist_data import build_orders, load_tables
from demand_forecasting.backtest import git_commit

TIERS = ["high", "medium", "low"]


def tier_summary(scored: pd.DataFrame) -> dict:
    """Late rate per tier and the alert's precision/recall.

    `scored` needs the columns tier, alert and late (0/1).
    """
    late_total = scored["late"].sum()
    tiers = {}
    for tier in TIERS:
        rows = scored[scored["tier"] == tier]
        tiers[tier] = {
            "orders": len(rows),
            "late_rate": round(float(rows["late"].mean()), 4),
            "share_of_late_orders": round(float(rows["late"].sum() / late_total), 4),
        }
    alerts = scored[scored["alert"]]
    return {
        "rows": len(scored),
        "late_rate": round(float(scored["late"].mean()), 4),
        "tiers": tiers,
        "alert": {
            "precision": round(float(alerts["late"].mean()), 4),
            "recall": round(float(alerts["late"].sum() / late_total), 4),
            "flagged_share": round(len(alerts) / len(scored), 4),
        },
    }


def check(raw_dir: Path, scores_folder: Path) -> dict:
    scores = pd.read_csv(scores_folder / "scores.csv", usecols=["order_id", "tier", "alert"])
    orders, _ = build_orders(load_tables(raw_dir))
    scored = scores.merge(orders[["order_id", "late"]], on="order_id", how="inner")
    if len(scored) != len(scores):
        raise ValueError(f"{len(scores) - len(scored)} scored orders have no known outcome")
    manifest = json.loads((scores_folder / "manifest.json").read_text(encoding="utf-8"))
    return {
        **tier_summary(scored),
        "note": "Second look at the Apr-Aug 2018 test months (first: P3-T2b). "
        "The daily top-10% rule was fixed before this check and not tuned.",
        "provenance": {"scores_run_key": manifest["run_key"], "code": git_commit()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m delivery_risk.tier_check")
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("scores_folder", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = check(args.raw_dir, args.scores_folder)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
