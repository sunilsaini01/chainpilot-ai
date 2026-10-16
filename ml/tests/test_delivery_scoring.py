"""Tests for delivery-risk scoring: explanations, tiers, leakage, and the published file."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from delivery_risk import scoring, tier_check
from delivery_risk.models import fit_logistic, logistic_inputs
from delivery_risk.olist_data import CATEGORY_FEATURES, FEATURE_COLUMNS


def synthetic_orders(seed: int = 0, n: int = 8_000) -> pd.DataFrame:
    """Orders over 2017-2018 with dispatch and outcome times, in the order-table format."""
    rng = np.random.default_rng(seed)
    purchase = pd.Timestamp("2017-01-01") + pd.to_timedelta(rng.uniform(0, 600, n), "D")
    frame = pd.DataFrame({column: rng.normal(size=n) for column in FEATURE_COLUMNS})
    for column in CATEGORY_FEATURES:
        frame[column] = pd.Categorical(rng.choice(["A", "B", "C"], n))
    log_odds = -2.5 + 1.2 * frame["days_left_at_dispatch"] + 0.8 * (frame["customer_state"] == "C")
    frame["late"] = (rng.random(n) < 1 / (1 + np.exp(-log_odds))).astype(int)
    frame["order_id"] = [f"o{i}" for i in range(n)]
    frame["order_purchase_timestamp"] = purchase
    frame["dispatched_at"] = purchase + pd.to_timedelta(rng.uniform(0.1, 5, n), "D")
    frame["outcome_known_at"] = frame["dispatched_at"] + pd.to_timedelta(rng.uniform(2, 25, n), "D")
    return frame.sort_values("order_purchase_timestamp").reset_index(drop=True)


MONTHS = pd.date_range("2018-04-01", "2018-05-01", freq="MS")


def test_contributions_add_up_to_the_log_odds_difference() -> None:
    """The explanation is exact, not an approximation: per row, the feature
    contributions sum to log-odds(row) - log-odds(average training order)."""
    orders = synthetic_orders()
    train = orders.iloc[:5_000]
    pipeline = fit_logistic(train)
    rows = orders.iloc[5_000:5_200]

    total = scoring.contributions(pipeline, rows, train).sum(axis=1).to_numpy()

    probability = pipeline.predict_proba(logistic_inputs(rows))[:, 1]
    columns, model = pipeline.named_steps["columns"], pipeline.named_steps["model"]
    average = (
        model.intercept_[0]
        + columns.transform(logistic_inputs(train)).mean(axis=0) @ model.coef_[0]
    )
    np.testing.assert_allclose(total, np.log(probability / (1 - probability)) - average, atol=1e-8)


def test_reasons_are_the_strongest_positive_contributions() -> None:
    orders = synthetic_orders()
    train = orders.iloc[:5_000]
    pipeline = fit_logistic(train)
    rows = orders.iloc[5_000:5_300]

    reasons = scoring.explain(pipeline, rows, train)

    assert len(reasons) == len(rows)
    for row_reasons in reasons:
        effects = [reason["effect"] for reason in row_reasons]
        assert len(row_reasons) <= 3
        assert all(effect > 0 for effect in effects)
        assert effects == sorted(effects, reverse=True)
        assert {reason["feature"] for reason in row_reasons} <= set(FEATURE_COLUMNS)
    # The feature that really drives risk in this data shows up most often.
    top = pd.Series([r[0]["feature"] for r in reasons if r]).value_counts()
    assert top.index[0] == "days_left_at_dispatch"


def test_source_feature_maps_transformed_names_back() -> None:
    assert scoring.source_feature("numbers__distance_km") == "distance_km"
    assert scoring.source_feature("other_categories__customer_state_SP") == "customer_state"
    assert scoring.source_feature("product_category__product_category_infrequent_sklearn") == (
        "product_category"
    )
    with pytest.raises(ValueError):
        scoring.source_feature("numbers__no_such_feature")


def test_tiers_follow_the_daily_ranking() -> None:
    rng = np.random.default_rng(1)
    scores = pd.DataFrame(
        {
            "dispatch_date": np.repeat(pd.date_range("2018-04-02", periods=3).date, 100),
            "probability": rng.random(300),
        }
    )

    tiered = scoring.assign_tiers(scores)

    for _, day in tiered.groupby("dispatch_date"):
        assert (day["tier"] == "high").sum() == 10
        assert (day["tier"] == "medium").sum() == 20
        assert (
            day.loc[day["tier"] == "high", "probability"].min()
            > day.loc[day["tier"] != "high", "probability"].max()
        )
    assert (tiered["alert"] == (tiered["tier"] == "high")).all()


def test_scores_ignore_outcomes_that_were_not_known_yet() -> None:
    """Leakage check: rewriting every outcome learned after the first scoring month
    starts must not change that month's scores."""
    orders = synthetic_orders()
    changed = orders.copy()
    later = changed["outcome_known_at"] >= MONTHS[0]
    changed.loc[later, "late"] = 1 - changed.loc[later, "late"]

    before, _ = scoring.score_dispatches(orders, MONTHS[:1])
    after, _ = scoring.score_dispatches(changed, MONTHS[:1])

    pd.testing.assert_frame_equal(before, after)


def test_scoring_covers_each_dispatch_month_with_its_own_model() -> None:
    orders = synthetic_orders()

    scores, models_info = scoring.score_dispatches(orders, MONTHS)

    dispatched = orders[
        (orders["dispatched_at"] >= "2018-04-01") & (orders["dispatched_at"] < "2018-06-01")
    ]
    assert len(scores) == len(dispatched)
    assert [info["month"] for info in models_info] == ["2018-04", "2018-05"]
    assert models_info[0]["trained_on_outcomes_before"] == "2018-02-04"  # 56 days before
    assert scores["probability"].between(0, 1).all()
    assert "late" not in scores.columns  # outcomes are never published


def test_published_files(tmp_path: Path) -> None:
    scores, models_info = scoring.score_dispatches(synthetic_orders(), MONTHS)

    folder = scoring.write_scores(scores, models_info, tmp_path, {"orders": "abc"})

    csv = pd.read_csv(folder / "scores.csv")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert list(csv.columns) == scoring.CSV_COLUMNS
    assert manifest["rows"] == len(csv) == len(scores)
    assert manifest["csv_sha256"] == scoring.file_sha256(folder / "scores.csv")
    assert "not ChainPilot's simulated suppliers" in manifest["dataset"]
    assert set(csv["tier"]) <= {"high", "medium", "low"}
    assert set(csv["alert"]) <= {True, False}
    first_reasons = json.loads(csv.loc[0, "reasons"])
    assert isinstance(first_reasons, list) and "effect" in first_reasons[0]
    assert b"\r\n" not in (folder / "scores.csv").read_bytes()


def test_tier_summary_counts_late_orders_per_tier() -> None:
    scored = pd.DataFrame(
        {
            "tier": ["high", "high", "medium", "low", "low", "low", "low", "low"],
            "alert": [True, True, False, False, False, False, False, False],
            "late": [1, 0, 1, 0, 0, 0, 0, 1],
        }
    )

    summary = tier_check.tier_summary(scored)

    assert summary["rows"] == 8 and summary["late_rate"] == 0.375
    assert summary["tiers"]["high"] == {
        "orders": 2,
        "late_rate": 0.5,
        "share_of_late_orders": 0.3333,
    }
    assert summary["tiers"]["low"]["late_rate"] == 0.2
    assert summary["alert"] == {"precision": 0.5, "recall": 0.3333, "flagged_share": 0.25}
