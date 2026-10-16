"""Score dispatched orders with the chosen delivery-risk procedure and write a file
the API can import (P3-T3).

Procedure (chosen in P3-T2b, docs/MODEL_RESULTS.md): logistic regression, retrained
at the start of each month on the outcomes known by then, with Platt calibration on
the last 56 days of known outcomes. Each order dispatched in that month is scored
by that month's model, so nothing it uses happened after its dispatch.

What each order gets
    probability     approximate chance of arriving late (it drifts with the monthly
                    late rate, so treat it as approximate)
    day_percentile  its rank among all orders dispatched the same day (0..1)
    tier            high = riskiest 10% of the day (these are the alerts),
                    medium = next 20%, low = the rest
    reasons         the 3 features that pushed its risk up the most, read directly
                    from the logistic regression (contribution in log-odds)

DATA LABEL: Olist public marketplace data, not ChainPilot's simulated suppliers.
Actual outcomes are not in the file: scores are what the system knew at dispatch.

From the `ml` folder:
    python -m delivery_risk.scoring ../data/raw/olist
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from delivery_risk.models import NUMERIC_FEATURES, logistic_inputs
from delivery_risk.olist_data import CATEGORY_FEATURES, FILES, build_orders, load_tables
from delivery_risk.rolling import RECENT, fit_recent_platt, known_before
from demand_forecasting.backtest import file_sha256, git_commit

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "processed" / "delivery_risk"
DATASET_LABEL = "Olist Brazilian E-Commerce (public data); not ChainPilot's simulated suppliers"
SCORING_MONTHS = pd.date_range("2018-04-01", "2018-08-01", freq="MS")
HIGH_SHARE, MEDIUM_SHARE = 0.10, 0.20  # top 10% high (alert), next 20% medium
TOP_REASONS = 3
CSV_COLUMNS = [
    "order_id",
    "purchased_at",
    "dispatched_at",
    "dispatch_date",
    "probability",
    "day_percentile",
    "tier",
    "alert",
    "reasons",
]


def source_feature(output_name: str) -> str:
    """Map a transformed column name (e.g. 'other_categories__customer_state_SP') back to
    the feature it came from ('customer_state')."""
    _, column = output_name.split("__", 1)
    if column in NUMERIC_FEATURES:
        return column
    for feature in CATEGORY_FEATURES:
        if column.startswith(feature + "_"):
            return feature
    raise ValueError(f"cannot map {output_name!r} to a feature")


def contributions(pipeline, rows: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    """Per-feature contribution to each row's log-odds of being late, compared with the
    average reference order: coefficient x (transformed value - reference mean).

    Comparing with the average matters for categories: without it, every order's own
    state would always "contribute", even a perfectly typical one. The reference is the
    model's training data, so no information from after the dispatch is used.
    Property (tested): the contributions of a row add up to
    log-odds(row) - log-odds(average order).
    """
    columns = pipeline.named_steps["columns"]
    coefficients = pipeline.named_steps["model"].coef_[0]
    values = columns.transform(logistic_inputs(rows))
    reference_mean = columns.transform(logistic_inputs(reference)).mean(axis=0)
    names = [source_feature(name) for name in columns.get_feature_names_out()]
    per_column = pd.DataFrame(
        (values - reference_mean) * coefficients, columns=names, index=rows.index
    )
    return per_column.T.groupby(level=0).sum().T  # one-hot columns summed per feature


def explain(
    pipeline, rows: pd.DataFrame, reference: pd.DataFrame, top: int = TOP_REASONS
) -> list[list[dict]]:
    """For each row, the `top` features that raise its risk most above an average order."""
    reasons = []
    for index, row in contributions(pipeline, rows, reference).iterrows():
        strongest = row[row > 0].sort_values(ascending=False).head(top)
        reasons.append(
            [
                {
                    "feature": feature,
                    "value": _plain(rows.at[index, feature]),
                    "effect": round(float(effect), 3),
                }
                for feature, effect in strongest.items()
            ]
        )
    return reasons


def _plain(value):
    """A JSON-friendly version of a feature value."""
    if isinstance(value, (float, np.floating)):
        return None if np.isnan(value) else round(float(value), 3)
    if isinstance(value, (int, np.integer)):
        return int(value)
    return str(value)


def assign_tiers(scores: pd.DataFrame) -> pd.DataFrame:
    """Percentile within each dispatch day, then high / medium / low."""
    percentile = scores.groupby("dispatch_date")["probability"].rank(pct=True, method="max")
    tier = np.where(
        percentile > 1 - HIGH_SHARE,
        "high",
        np.where(percentile > 1 - HIGH_SHARE - MEDIUM_SHARE, "medium", "low"),
    )
    return scores.assign(day_percentile=percentile.round(4), tier=tier, alert=tier == "high")


def score_dispatches(
    orders: pd.DataFrame, months=SCORING_MONTHS
) -> tuple[pd.DataFrame, list[dict]]:
    """Score every order dispatched in the given months. Returns scores and per-month model info."""
    parts, models_info = [], []
    for start in months:
        end = start + pd.offsets.MonthBegin(1)
        dispatched = orders[(orders["dispatched_at"] >= start) & (orders["dispatched_at"] < end)]
        if dispatched.empty:
            continue
        pipeline, calibrator = fit_recent_platt(orders, start, "logistic_regression")
        training = known_before(orders, start - RECENT)  # what the model was trained on
        probability = calibrator.predict(pipeline.predict_proba(logistic_inputs(dispatched))[:, 1])
        parts.append(
            pd.DataFrame(
                {
                    "order_id": dispatched["order_id"].to_numpy(),
                    "purchased_at": dispatched["order_purchase_timestamp"].to_numpy(),
                    "dispatched_at": dispatched["dispatched_at"].to_numpy(),
                    "dispatch_date": dispatched["dispatched_at"].dt.date.to_numpy(),
                    "probability": probability,
                    "reasons": [json.dumps(r) for r in explain(pipeline, dispatched, training)],
                }
            )
        )
        models_info.append(
            {
                "month": start.strftime("%Y-%m"),
                "trained_on_outcomes_before": (start - pd.Timedelta(days=56)).date().isoformat(),
                "calibration": calibrator.to_dict(),
                "orders_scored": len(dispatched),
            }
        )
    scores = assign_tiers(pd.concat(parts, ignore_index=True))
    return scores.sort_values(
        ["dispatch_date", "probability"], ascending=[True, False]
    ), models_info


def write_scores(
    scores: pd.DataFrame, models_info: list[dict], output_root: Path, data_sha256: dict
) -> Path:
    """Write scores.csv and manifest.json into a new folder named after the period."""
    first, last = scores["dispatch_date"].min(), scores["dispatch_date"].max()
    folder = output_root / f"olist_logistic_{first:%Y-%m-%d}_{last:%Y-%m-%d}"
    folder.mkdir(parents=True, exist_ok=True)
    csv_path = folder / "scores.csv"
    out = scores.assign(
        purchased_at=scores["purchased_at"].dt.strftime("%Y-%m-%dT%H:%M:%S"),
        dispatched_at=scores["dispatched_at"].dt.strftime("%Y-%m-%dT%H:%M:%S"),
        dispatch_date=scores["dispatch_date"].astype(str),
        alert=scores["alert"].map({True: "true", False: "false"}),
    )
    out[CSV_COLUMNS].to_csv(csv_path, index=False, float_format="%.6f", lineterminator="\n")
    manifest = {
        "dataset": DATASET_LABEL,
        "model": "logistic_regression + recent Platt (monthly retraining)",
        "period_start": str(first),
        "period_end": str(last),
        "rows": len(scores),
        "tier_rule": "per dispatch day: high = top 10% (alert), medium = next 20%, low = rest",
        "probability_note": "approximate; the monthly late rate swings (see docs/MODEL_RESULTS.md)",
        "monthly_models": models_info,
        "csv_sha256": file_sha256(csv_path),
        "git_commit": git_commit(),
        "data_sha256": data_sha256,
    }
    manifest["run_key"] = hashlib.sha256(manifest["csv_sha256"].encode()).hexdigest()[:16]
    (folder / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return folder


def publish(raw_dir: Path, output_root: Path) -> Path:
    orders, _ = build_orders(load_tables(raw_dir))
    scores, models_info = score_dispatches(orders)
    data_sha256 = {name: file_sha256(Path(raw_dir) / file) for name, file in FILES.items()}
    return write_scores(scores, models_info, output_root, data_sha256)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m delivery_risk.scoring")
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    try:
        folder = publish(args.raw_dir, args.output_root)
    except FileNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    print(
        f"Wrote {manifest['rows']} scored orders ({manifest['period_start']} to "
        f"{manifest['period_end']}) to {folder}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
