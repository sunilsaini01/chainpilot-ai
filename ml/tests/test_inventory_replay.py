"""Tests for the inventory replay simulator (P4-T2). The replay example is traced by hand."""

import numpy as np
import pandas as pd
import pytest
from app.inventory_policy import order_up_to_level

from demand_forecasting.conformal import ConformalIntervals
from inventory_sim import experiment
from inventory_sim.policies import (
    LEAD_TIME_DAYS,
    LEAD_TIME_STD,
    REVIEW_DAYS,
    baseline_targets,
    forecast_inputs,
    formula_targets,
)
from inventory_sim.replay import add_totals, baseline_stock_at, rates, replay, summarize

# One item, 21 days, 2 units a day. Start with 10; reviews at the end of days 6 and 13.
DEMAND = np.full((1, 21), 2.0)
TARGETS = np.array([[10.0, 30.0, 30.0]])
PRICES = np.full((1, 21), 1.5)


def test_replay_worked_example() -> None:
    # Days 0-4 sell the 10 units; days 5-8 lose 2 a day. End of day 6: order 30,
    # arriving on the morning of day 9. End of day 13: 20 on hand -> order 10, arriving
    # day 16. Day 20 ends with 30 - 10 + 10 - 14 = 16 units.
    result = replay(DEMAND, TARGETS, np.array([[0, 3, 3]]))

    assert result.lost[0].tolist() == [0] * 5 + [2] * 4 + [0] * 12
    assert result.sold.sum() == 34
    assert result.on_hand[0, [6, 9, 13, 16, 20]].tolist() == [0, 28, 20, 24, 16]
    assert (result.units_ordered[0], result.orders_placed[0]) == (40, 2)


def test_open_orders_count_in_the_position() -> None:
    # The first order takes 10 days (arrives day 16), so at the second review the
    # position is 0 on hand + 30 on order = the target: nothing more is ordered.
    result = replay(DEMAND, TARGETS, np.array([[0, 10, 3]]))

    assert (result.units_ordered[0], result.orders_placed[0]) == (30, 1)
    assert result.on_hand[0, 16] == 28


def test_orders_arriving_after_the_end_are_counted_but_never_sold() -> None:
    result = replay(DEMAND, TARGETS, np.array([[0, 30, 3]]))

    assert (result.units_ordered[0], result.orders_placed[0]) == (30, 1)
    assert result.sold.sum() == 10  # only the starting stock


def test_replay_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError, match="at least 1 day"):
        replay(DEMAND, TARGETS, np.array([[0, 0, 3]]))
    with pytest.raises(ValueError, match="same shape"):
        replay(DEMAND, TARGETS, np.array([[0, 3]]))
    with pytest.raises(ValueError, match="more reviews"):
        replay(DEMAND[:, :10], TARGETS, np.array([[0, 3, 3]]))


def test_metrics_of_the_worked_example() -> None:
    total = summarize(replay(DEMAND, TARGETS, np.array([[0, 3, 3]])), DEMAND, PRICES)
    metrics = rates(total)

    assert metrics["fill_rate"] == round(34 / 42, 4)
    # Weeks: days 0-6 lost 4, days 7-13 lost 4, days 14-20 lost nothing.
    assert metrics["cycle_service_level"] == round(1 / 3, 4)
    end_stock = [8, 6, 4, 2, 0, 0, 0, 0, 0, 28, 26, 24, 22, 20, 18, 16, 24, 22, 20, 18, 16]
    assert metrics["average_units_on_hand"] == round(sum(end_stock) / 21, 1)
    assert metrics["average_stock_value"] == round(1.5 * sum(end_stock) / 21, 1)
    # Two stores with the same numbers: same rates, doubled counts.
    both = add_totals([total, total])
    assert rates(both)["fill_rate"] == metrics["fill_rate"]
    assert both["demand_units"] == 84 and both["days"] == 21


def test_baseline_stock_is_interpolated_not_extrapolated() -> None:
    curve = [
        {"fill_rate": 0.90, "average_units_on_hand": 100},
        {"fill_rate": 0.80, "average_units_on_hand": 60},
    ]
    assert baseline_stock_at(0.85, curve, "average_units_on_hand") == pytest.approx(80)
    assert baseline_stock_at(0.95, curve, "average_units_on_hand") is None


def test_baseline_targets() -> None:
    # 28 units in 28 days = 1/day: x 14 days = 14; with a 3.5-day buffer 17.5 -> 18.
    assert baseline_targets(np.array([28, 14, 2, 0]), 0).tolist() == [14, 7, 1, 0]
    assert baseline_targets(np.array([28]), 3.5).tolist() == [18]


def _forecast(item: str, values: list[float], lower: list[float], upper: list[float]):
    dates = pd.date_range("2016-02-01", periods=len(values))
    return pd.DataFrame(
        {"id": item, "date": dates, "forecast": values, "lower": lower, "upper": upper}
    )


def test_forecast_inputs_and_formula_targets() -> None:
    width = 2 * 1.2815516  # an 80% interval this wide means a std of 1
    forecast = pd.concat(
        [
            _forecast("a", [1.0] * 14, [0.0] * 14, [width] * 14),
            # std 1 for 7 days and 2 for 7 days -> root mean square sqrt(2.5)
            _forecast("b", [2.0] * 7 + [4.0] * 7, [0.0] * 14, [width] * 7 + [2 * width] * 7),
        ]
    )
    inputs = forecast_inputs(forecast)

    assert inputs.loc["a", "daily_mean"] == 1 and inputs.loc["a", "daily_std"] == pytest.approx(1)
    assert inputs.loc["b", "daily_mean"] == 3
    assert inputs.loc["b", "daily_std"] == pytest.approx(np.sqrt(2.5))
    expected = order_up_to_level(3, np.sqrt(2.5), LEAD_TIME_DAYS, LEAD_TIME_STD, REVIEW_DAYS, 0.95)
    assert formula_targets(inputs, 0.95)["b"] == expected.level

    with pytest.raises(ValueError, match="exactly 14 days"):
        forecast_inputs(forecast.iloc[1:])


def _tiny_long() -> pd.DataFrame:
    dates = pd.date_range("2015-12-01", "2016-04-24")
    rng = np.random.default_rng(0)
    frames = [
        pd.DataFrame({"id": item, "date": dates, "sales": rng.poisson(rate, len(dates))})
        for item, rate in [("x_CA_1", 3.0), ("y_CA_1", 0.5)]
    ]
    long = pd.concat(frames, ignore_index=True)
    return long.assign(id=long["id"].astype("category"))


def test_review_inputs_use_only_sales_known_at_the_review(monkeypatch) -> None:
    # LightGBM is replaced by the moving average to keep the test fast; the point is
    # that the history handed to the forecasters stops at each review day.
    monkeypatch.setattr(
        experiment, "make_forecaster", lambda long, settings: experiment.moving_average_28
    )
    intervals = ConformalIntervals([0.5], [-0.5, -1.0], [1.0, 2.0], 1000)
    intervals = {name: intervals for name in experiment.FORECASTERS}
    long = _tiny_long()
    before = experiment.store_inputs(long, intervals)

    changed = long.copy()
    after_last_review = changed["date"] > experiment.review_dates()[-1]
    changed.loc[after_last_review, "sales"] = 1000
    in_sixth_week = changed["date"] > experiment.review_dates()[5]
    changed_mid = long.copy()
    changed_mid.loc[in_sixth_week, "sales"] = 1000

    pd.testing.assert_frame_equal(before, experiment.store_inputs(changed, intervals))
    mid = experiment.store_inputs(changed_mid, intervals)
    early = before["review"] <= 5
    pd.testing.assert_frame_equal(before[early], mid[early])
    assert not before[~early].equals(mid[~early])  # later reviews do see the new sales


def test_policy_targets_shapes_and_baseline_column() -> None:
    ids = ["x_CA_1", "y_CA_1"]
    rows = []
    for review in range(experiment.REVIEWS):
        for item, sales in zip(ids, [28, 56], strict=True):
            row = {"id": item, "review": review, "sales_28": sales}
            for name in experiment.FORECASTERS:
                row[f"{name}__daily_mean"] = 1.0
                row[f"{name}__daily_std"] = 0.0
            rows.append(row)
    targets = experiment.policy_targets(pd.DataFrame(rows), ids)

    assert len(targets) == 4 + 2 * 4
    assert targets["baseline_buffer_0d"].shape == (2, experiment.REVIEWS)
    assert targets["baseline_buffer_0d"][:, 0].tolist() == [14, 28]
    # No demand uncertainty, but the lead time still varies (std 1.41 days):
    # 14 + 1.645 x 1/day x 1.41 = 16.33 -> 17.
    assert targets["formula_lightgbm_weekly_0.95"][:, 3].tolist() == [17, 17]


def test_a_week_losing_a_single_unit_is_a_missed_cycle() -> None:
    # 1 unit a day; 6 in stock runs out on day 6 (1 unit lost). The order of 8 at the
    # end of day 6 arrives the next morning and covers the second week.
    demand = np.ones((1, 14))
    result = replay(demand, np.array([[6.0, 8.0, 0.0]]), np.array([[0, 1, 1]]))
    metrics = rates(summarize(result, demand, np.ones((1, 14))))

    assert result.lost.sum() == 1
    assert metrics["cycle_service_level"] == 0.5
    assert metrics["cycle_service_level_weeks_with_demand"] == 0.5


def test_baseline_targets_do_not_overflow_small_integer_sales() -> None:
    # M5 sales are int16: 1,657 x 28 = 46,396 does not fit and used to wrap around.
    sales = np.array([1657, 30000], dtype=np.int16)
    assert baseline_targets(sales, 14).tolist() == [1657, 30000]
    assert baseline_targets(sales, 7).tolist() == [1243, 22500]
