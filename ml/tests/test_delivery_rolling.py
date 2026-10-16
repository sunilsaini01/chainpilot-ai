"""Tests for the rolling monthly simulation (delivery_risk/rolling.py), on synthetic orders."""

import numpy as np
import pandas as pd
import pytest

from delivery_risk import rolling
from delivery_risk.olist_data import CATEGORY_FEATURES, FEATURE_COLUMNS, FORBIDDEN_FEATURES


def synthetic_orders(seed: int = 0) -> pd.DataFrame:
    """Orders over 2017-2018; outcomes become known 3-30 days after purchase."""
    rng = np.random.default_rng(seed)
    n = 6_000
    purchase = pd.Timestamp("2017-01-01") + pd.to_timedelta(rng.uniform(0, 600, n), "D")
    frame = pd.DataFrame({column: rng.normal(size=n) for column in FEATURE_COLUMNS})
    for column in CATEGORY_FEATURES:
        frame[column] = pd.Categorical(rng.choice(["A", "B"], n))
    log_odds = -2.5 + 1.2 * frame["days_left_at_dispatch"]
    frame["late"] = (rng.random(n) < 1 / (1 + np.exp(-log_odds))).astype(int)
    frame["order_purchase_timestamp"] = purchase
    frame["outcome_known_at"] = purchase + pd.to_timedelta(rng.uniform(3, 30, n), "D")
    return frame.sort_values("order_purchase_timestamp").reset_index(drop=True)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> list[pd.DataFrame]:
    """Replace the model fitters with ones that record their training data."""
    seen: list[pd.DataFrame] = []
    original = dict(rolling.MODELS)

    def recording(name):
        def fit(train):
            seen.append(train)
            return original[name](train)

        return fit

    monkeypatch.setattr(rolling, "MODELS", {name: recording(name) for name in original})
    return seen


def test_outcome_time_is_never_a_feature() -> None:
    assert "outcome_known_at" in FORBIDDEN_FEATURES
    assert "outcome_known_at" not in FEATURE_COLUMNS


def test_training_only_uses_outcomes_known_before_the_month(spy) -> None:
    orders = synthetic_orders()
    start = pd.Timestamp("2018-01-01")

    rolling.score_month(orders, start, "logistic_regression", "none")

    assert spy[0]["outcome_known_at"].max() < start
    # ...and really does use everything that was known by then.
    assert len(spy[0]) == int((orders["outcome_known_at"] < start).sum())


def test_recent_platt_trains_earlier_and_calibrates_on_the_last_56_days(
    spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    orders = synthetic_orders()
    start = pd.Timestamp("2018-01-01")
    calibration_sets = []
    original_fit = rolling.PlattCalibrator.fit

    def recording_fit(self, y, p):
        calibration_sets.append(len(y))
        return original_fit(self, y, p)

    monkeypatch.setattr(rolling.PlattCalibrator, "fit", recording_fit)

    rolling.score_month(orders, start, "logistic_regression", "recent_platt")

    assert spy[0]["outcome_known_at"].max() < start - rolling.RECENT
    window = (orders["outcome_known_at"] >= start - rolling.RECENT) & (
        orders["outcome_known_at"] < start
    )
    assert calibration_sets == [int(window.sum())]


def test_a_month_scores_only_its_own_purchases_and_the_cutoff_uses_earlier_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orders = synthetic_orders()
    start = pd.Timestamp("2018-01-01")
    scored_rows = []

    def scorer_factory(orders_, start_, model_name, variant):
        def score(rows):
            scored_rows.append(rows["order_purchase_timestamp"])
            return np.linspace(0, 1, len(rows))

        return score

    monkeypatch.setattr(rolling, "fit_scorer", scorer_factory)

    result = rolling.score_month(orders, start, "logistic_regression", "none")

    recent, month = scored_rows
    assert recent.min() >= start - rolling.RECENT and recent.max() < start
    assert month.min() >= start and month.max() < pd.Timestamp("2018-02-01")
    assert len(result) == len(month)
    assert result["cutoff"].iloc[0] == pytest.approx(0.9, abs=0.01)  # 90th percentile of 0..1


def test_development_months_never_reach_the_test_period() -> None:
    assert rolling.DEVELOPMENT_MONTHS.max() + pd.offsets.MonthBegin(1) <= rolling.TEST_MONTHS.min()
    assert list(rolling.TEST_MONTHS.strftime("%Y-%m")) == [
        "2018-04",
        "2018-05",
        "2018-06",
        "2018-07",
        "2018-08",
    ]


def test_alert_rule_flags_about_ten_percent() -> None:
    orders = synthetic_orders()

    result = rolling.evaluate(
        orders, pd.date_range("2018-01-01", "2018-03-01", freq="MS"), "logistic_regression", "none"
    )

    assert 0.05 <= result["pooled"]["alert_rule_top_10pct"]["flagged_share"] <= 0.15
    assert set(result["per_month"]) == {"2018-01", "2018-02", "2018-03"}


def per_month(**metrics_by_month) -> dict:
    return {"per_month": metrics_by_month}


def test_choose_model_by_pr_auc_then_calibration_by_ece() -> None:
    development = {
        "logistic_regression": {
            "none": per_month(m1={"pr_auc": 0.30, "brier": 0.05, "ece": 0.02}),
            "recent_platt": per_month(m1={"pr_auc": 0.30, "brier": 0.05, "ece": 0.01}),
        },
        "lightgbm": {
            "none": per_month(m1={"pr_auc": 0.40, "brier": 0.06, "ece": 0.03}),
            "recent_platt": per_month(m1={"pr_auc": 0.40, "brier": 0.06, "ece": 0.05}),
        },
    }

    assert rolling.choose(development) == ("lightgbm", "none")
