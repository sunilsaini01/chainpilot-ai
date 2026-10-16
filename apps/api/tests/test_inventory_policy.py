"""Inventory policy math (no database). Expected values are worked out by hand."""

import math
import random

import pytest

from app.inventory_policy import (
    days_of_cover,
    demand_over,
    inventory_position,
    order_quantity,
    order_up_to_level,
    reorder_point,
    std_from_interval,
    z_for_service_level,
)

# Worked example used below: 10 units/day (std 3), lead time 7 days (std 2),
# weekly review, 95% service level.
DAILY_MEAN, DAILY_STD, LEAD, LEAD_STD, REVIEW, SERVICE = 10, 3, 7, 2, 7, 0.95


def test_inventory_position_adds_open_orders() -> None:
    assert inventory_position(on_hand=40, on_order=60) == 100
    with pytest.raises(ValueError, match="on_order"):
        inventory_position(on_hand=40, on_order=-1)


def test_z_values() -> None:
    assert z_for_service_level(0.5) == 0
    assert z_for_service_level(0.95) == pytest.approx(1.6449, abs=1e-4)
    assert z_for_service_level(0.99) == pytest.approx(2.3263, abs=1e-4)
    for bad in (0.4, 1.0):
        with pytest.raises(ValueError, match="service_level"):
            z_for_service_level(bad)


def test_std_from_an_80_percent_interval() -> None:
    # An 80% normal interval is +-1.2816 standard deviations wide.
    assert std_from_interval(10 - 1.2816, 10 + 1.2816) == pytest.approx(1.0, abs=1e-4)
    assert std_from_interval(5, 5) == 0
    with pytest.raises(ValueError, match="upper"):
        std_from_interval(3, 2)


def test_demand_over_the_protection_period() -> None:
    # 14 days: mean 140; variance 14 x 3^2 + 10^2 x 2^2 = 126 + 400 = 526.
    mean, std = demand_over(LEAD + REVIEW, DAILY_MEAN, DAILY_STD, LEAD_STD)
    assert mean == 140
    assert std == pytest.approx(math.sqrt(526))
    # Without lead-time variability only day-to-day variation is left.
    assert demand_over(14, 10, 3)[1] == pytest.approx(3 * math.sqrt(14))


def test_order_up_to_level_worked_example() -> None:
    target = order_up_to_level(DAILY_MEAN, DAILY_STD, LEAD, LEAD_STD, REVIEW, SERVICE)

    assert target.expected_demand == 140
    assert target.safety_stock == pytest.approx(1.64485 * math.sqrt(526), abs=1e-3)  # 37.72
    assert target.level == 178  # 177.72 rounded up


def test_level_is_rounded_up_never_down() -> None:
    # 140 + 1.2816 x 0.1 x sqrt(14) = 140.48: ordering 140 would undercut the target.
    assert order_up_to_level(10, 0.1, 7, 0, 7, 0.90).level == 141


def test_no_uncertainty_means_no_safety_stock() -> None:
    target = order_up_to_level(10, 0, 7, 0, 7, 0.99)
    assert (target.safety_stock, target.level) == (0, 140)


def test_reorder_point_worked_example() -> None:
    # Lead time only: 70 + 1.645 x sqrt(7 x 9 + 100 x 4) = 70 + 1.645 x 21.52 = 105.39
    rop = reorder_point(DAILY_MEAN, DAILY_STD, LEAD, LEAD_STD, SERVICE)
    assert rop == pytest.approx(70 + 1.64485 * math.sqrt(463), abs=1e-3)


def test_order_up_to_level_reaches_the_service_level_in_simulation() -> None:
    # Independent check of the variance formula: draw random lead times and
    # demand, and count how often the protection period's demand fits in the level.
    rng = random.Random(7)
    target = order_up_to_level(DAILY_MEAN, DAILY_STD, LEAD, LEAD_STD, REVIEW, SERVICE)
    trials, enough = 20_000, 0
    for _ in range(trials):
        days = REVIEW + max(rng.gauss(LEAD, LEAD_STD), 0)
        demand = rng.gauss(DAILY_MEAN * days, DAILY_STD * math.sqrt(days))
        enough += demand <= target.expected_demand + target.safety_stock
    assert enough / trials == pytest.approx(SERVICE, abs=0.006)


@pytest.mark.parametrize(
    ("position", "target", "moq", "pack", "max_units", "expected"),
    [
        (180, 178, 1, 1, None, (0, 0, "not_needed")),
        (178, 178, 1, 1, None, (0, 0, "not_needed")),
        (100, 178, 1, 1, None, (78, 78, "ordered")),
        (100, 178, 1, 12, None, (84, 78, "ordered")),  # 7 packs of 12
        (100, 178, 100, 1, None, (100, 78, "raised_to_moq")),
        (100, 178, 100, 12, None, (108, 78, "raised_to_moq")),  # 100 -> 9 packs
        (100, 178, 1, 12, 50, (48, 78, "limited")),  # room for 4 whole packs
        (100, 178, 60, 12, 50, (0, 78, "blocked")),  # 48 < minimum order 60
        (100, 178, 1, 12, 11, (0, 78, "blocked")),  # not even one pack fits
    ],
)
def test_order_quantity_rules(position, target, moq, pack, max_units, expected) -> None:
    decision = order_quantity(position, target, moq, pack, max_units)
    assert (decision.quantity, decision.shortfall, decision.reason) == expected


def test_order_quantity_rejects_bad_rules() -> None:
    with pytest.raises(ValueError, match="pack_size"):
        order_quantity(0, 10, pack_size=0)
    with pytest.raises(ValueError, match="max_units"):
        order_quantity(0, 10, max_units=-5)


def test_days_of_cover() -> None:
    assert days_of_cover(on_hand=30, daily_mean=10) == 3
    assert days_of_cover(on_hand=30, daily_mean=0) == math.inf
