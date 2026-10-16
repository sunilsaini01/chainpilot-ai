"""Tests for the late-delivery metrics, calibration and models (synthetic data)."""

import numpy as np
import pandas as pd
import pytest

from delivery_risk.evaluation import (
    PlattCalibrator,
    all_metrics,
    best_f1_threshold,
    expected_calibration_error,
    threshold_metrics,
)
from delivery_risk.experiment import choose
from delivery_risk.models import MODELS, predict
from delivery_risk.olist_data import CATEGORY_FEATURES, FEATURE_COLUMNS


def synthetic_orders(n: int, seed: int) -> pd.DataFrame:
    """Orders where lateness really depends on the days left at dispatch and distance."""
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({column: rng.normal(size=n) for column in FEATURE_COLUMNS})
    frame["days_left_at_dispatch"] = rng.uniform(-5, 30, n)
    frame["distance_km"] = rng.uniform(0, 3000, n)
    frame.loc[rng.random(n) < 0.05, "distance_km"] = np.nan  # some unknown distances
    for column in CATEGORY_FEATURES:
        frame[column] = pd.Categorical(
            rng.choice(["A", "B", "C"], n), categories=["A", "B", "C", "D"]
        )
    log_odds = (
        -1.0 - 0.25 * frame["days_left_at_dispatch"] + 0.0008 * frame["distance_km"].fillna(1500)
    )
    frame["late"] = (rng.random(n) < 1 / (1 + np.exp(-log_odds))).astype(int)
    return frame


# --- Metrics -------------------------------------------------------------------


def test_expected_calibration_error_by_hand() -> None:
    y = np.array([0, 0, 1, 1])
    p = np.array([0.15, 0.15, 0.85, 0.85])  # bins 0.1-0.2 and 0.8-0.9

    # Bin 1: |0 - 0.15| ; bin 8: |1 - 0.85| ; each half the orders.
    assert expected_calibration_error(y, p) == pytest.approx(0.5 * 0.15 + 0.5 * 0.15)


def test_perfectly_calibrated_scores_have_tiny_ece() -> None:
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, 200_000)
    y = (rng.random(p.size) < p).astype(int)

    assert expected_calibration_error(y, p) < 0.01


def test_threshold_metrics_by_hand() -> None:
    y = np.array([1, 1, 0, 0, 0])
    p = np.array([0.9, 0.2, 0.8, 0.1, 0.1])

    result = threshold_metrics(y, p, 0.5)  # flags orders 1 and 3

    assert result == {
        "threshold": 0.5,
        "flagged_share": 0.4,
        "precision": 0.5,
        "recall": 0.5,
        "f1": 0.5,
    }


def test_best_f1_threshold_separates_a_clean_case() -> None:
    y = np.array([0, 0, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.3, 0.7, 0.9])

    threshold = best_f1_threshold(y, p)

    assert threshold == pytest.approx(0.7)
    assert threshold_metrics(y, p, threshold)["f1"] == 1.0


def test_random_scores_have_pr_auc_near_the_late_rate() -> None:
    rng = np.random.default_rng(1)
    y = (rng.random(100_000) < 0.1).astype(int)

    metrics = all_metrics(y, rng.random(y.size))

    assert abs(metrics["pr_auc"] - 0.1) < 0.01
    assert abs(metrics["roc_auc"] - 0.5) < 0.01


def test_platt_scaling_fixes_overconfident_scores() -> None:
    rng = np.random.default_rng(2)
    true_p = rng.uniform(0.01, 0.3, 50_000)
    y = (rng.random(true_p.size) < true_p).astype(int)
    overconfident = np.clip(true_p * 2.5, 0, 0.99)  # same ranking, wrong probabilities

    calibrated = PlattCalibrator().fit(y, overconfident).predict(overconfident)

    assert (
        expected_calibration_error(y, calibrated) < expected_calibration_error(y, overconfident) / 3
    )
    assert np.all(np.diff(calibrated[np.argsort(overconfident)]) >= -1e-12)  # ranking kept
    assert set(PlattCalibrator().fit(y, overconfident).to_dict()) == {"slope", "intercept"}


# --- Models ----------------------------------------------------------------------


@pytest.mark.parametrize("name", list(MODELS))
def test_models_learn_a_real_pattern(name: str) -> None:
    train, test = synthetic_orders(6_000, seed=3), synthetic_orders(3_000, seed=4)

    model = MODELS[name](train)
    scores = predict(model, test)

    assert scores.shape == (len(test),)
    assert ((scores >= 0) & (scores <= 1)).all()
    assert all_metrics(test["late"], scores)["pr_auc"] > 2 * test["late"].mean()


@pytest.mark.parametrize("name", list(MODELS))
def test_models_handle_unseen_categories_and_missing_values(name: str) -> None:
    model = MODELS[name](synthetic_orders(3_000, seed=5))
    rows = synthetic_orders(50, seed=6)
    for column in CATEGORY_FEATURES:  # "D" never appears in the training data
        rows[column] = pd.Categorical(["D"] * len(rows), categories=["A", "B", "C", "D"])
    rows["total_weight_kg"] = np.nan

    scores = predict(model, rows)

    assert np.isfinite(scores).all()


@pytest.mark.parametrize("name", list(MODELS))
def test_only_feature_columns_influence_predictions(name: str) -> None:
    model = MODELS[name](synthetic_orders(3_000, seed=7))
    rows = synthetic_orders(200, seed=8)
    with_extra = rows.assign(order_delivered_customer_date="2018-01-01", late=1 - rows["late"])

    np.testing.assert_allclose(predict(model, rows), predict(model, with_extra))


# --- Selection rule ------------------------------------------------------------------


def test_choose_highest_pr_auc_and_break_ties_by_brier() -> None:
    assert (
        choose({"a": {"pr_auc": 0.40, "brier": 0.05}, "b": {"pr_auc": 0.45, "brier": 0.09}}) == "b"
    )
    assert (
        choose({"a": {"pr_auc": 0.452, "brier": 0.05}, "b": {"pr_auc": 0.455, "brier": 0.09}})
        == "a"
    )
