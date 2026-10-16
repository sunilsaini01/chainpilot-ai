"""Day-by-day stock replay for many items at once (numpy arrays: items x days).

Rules (pre-registered in the work log, "P4-T2 plan"):
- Each morning, deliveries due that day arrive.
- Demand is served from stock; demand that cannot be served is lost (no backorders).
- At the end of each review day an order brings the inventory position
  (on hand + on order) up to that review's target level. It arrives `lead time`
  days later, in the morning.
- Each item starts with its first target level on hand and nothing on order.
"""

from dataclasses import dataclass

import numpy as np

REVIEW_DAYS = 7


@dataclass
class ReplayResult:
    """Per item and day (items x days), plus the orders placed."""

    sold: np.ndarray
    lost: np.ndarray
    on_hand: np.ndarray  # end of day, after sales
    units_ordered: np.ndarray  # per item, including orders that arrive after the end
    orders_placed: np.ndarray  # per item


def replay(
    demand: np.ndarray, targets: np.ndarray, lead_times: np.ndarray, review_days: int = REVIEW_DAYS
) -> ReplayResult:
    """Replay one policy.

    demand      items x days, units demanded each day
    targets     items x reviews; column 0 is the starting stock, column k the
                target at the review held at the end of day k * review_days - 1
    lead_times  items x reviews, whole days (column 0 is not used)
    """
    items, days = demand.shape
    reviews = targets.shape[1]
    if lead_times.shape != targets.shape:
        raise ValueError("lead_times must have the same shape as targets")
    if (reviews - 1) * review_days > days:
        raise ValueError("more reviews than the simulated days allow")
    if (lead_times[:, 1:] < 1).any():
        raise ValueError("lead times must be at least 1 day")

    on_hand = targets[:, 0].astype(float).copy()
    arriving = np.zeros((items, days))  # deliveries per morning
    late_orders = np.zeros(items)  # ordered but arriving after the last day
    sold = np.zeros((items, days))
    lost = np.zeros((items, days))
    end_stock = np.zeros((items, days))
    units_ordered = np.zeros(items)
    orders_placed = np.zeros(items, dtype=int)

    for day in range(days):
        on_hand += arriving[:, day]
        sold[:, day] = np.minimum(on_hand, demand[:, day])
        lost[:, day] = demand[:, day] - sold[:, day]
        on_hand -= sold[:, day]
        end_stock[:, day] = on_hand

        review = (day + 1) // review_days
        if (day + 1) % review_days == 0 and 1 <= review < reviews:
            on_order = arriving[:, day + 1 :].sum(axis=1) + late_orders
            quantity = np.maximum(targets[:, review] - (on_hand + on_order), 0)
            arrival = day + lead_times[:, review]
            inside = arrival < days
            arriving[np.flatnonzero(inside), arrival[inside]] += quantity[inside]
            late_orders += np.where(inside, 0, quantity)
            units_ordered += quantity
            orders_placed += quantity > 0

    return ReplayResult(sold, lost, end_stock, units_ordered, orders_placed)


def summarize(result: ReplayResult, demand: np.ndarray, prices: np.ndarray) -> dict:
    """Totals that can be added up across stores (see `rates` for the ratios)."""
    items, days = demand.shape
    weeks = days // REVIEW_DAYS
    weekly_lost = result.lost[:, : weeks * REVIEW_DAYS].reshape(items, weeks, REVIEW_DAYS).sum(2)
    weekly_demand = demand[:, : weeks * REVIEW_DAYS].reshape(items, weeks, REVIEW_DAYS).sum(2)
    return {
        "items": items,
        "days": days,
        "demand_units": float(demand.sum()),
        "sold_units": float(result.sold.sum()),
        "lost_units": float(result.lost.sum()),
        "item_weeks": int(items * weeks),
        "item_weeks_without_lost_sales": int((weekly_lost == 0).sum()),
        "item_weeks_with_demand": int((weekly_demand > 0).sum()),
        "item_weeks_with_demand_and_no_lost_sales": int(
            ((weekly_demand > 0) & (weekly_lost == 0)).sum()
        ),
        "stock_unit_days": float(result.on_hand.sum()),
        "stock_value_days": float((result.on_hand * prices).sum()),
        "units_ordered": float(result.units_ordered.sum()),
        "orders_placed": int(result.orders_placed.sum()),
    }


def add_totals(parts: list[dict]) -> dict:
    """Add up the totals of several stores (days must match)."""
    total = {key: sum(part[key] for part in parts) for key in parts[0] if key != "days"}
    return {**total, "days": parts[0]["days"]}


def rates(total: dict) -> dict:
    """The reported metrics, from the totals."""
    return {
        "fill_rate": round(total["sold_units"] / total["demand_units"], 4),
        "cycle_service_level": round(
            total["item_weeks_without_lost_sales"] / total["item_weeks"], 4
        ),
        "cycle_service_level_weeks_with_demand": round(
            total["item_weeks_with_demand_and_no_lost_sales"] / total["item_weeks_with_demand"],
            4,
        ),
        "average_units_on_hand": round(total["stock_unit_days"] / total["days"], 1),
        "average_stock_value": round(total["stock_value_days"] / total["days"], 1),
        "units_ordered": round(total["units_ordered"], 1),
        "orders_placed": total["orders_placed"],
        "lost_units": round(total["lost_units"], 1),
    }


def baseline_stock_at(fill_rate: float, baseline: list[dict], metric: str) -> float | None:
    """Baseline's stock at the same fill rate, read off its curve by linear interpolation.

    None if the fill rate is outside the range the baseline settings cover (no
    extrapolation).
    """
    points = sorted((point["fill_rate"], point[metric]) for point in baseline)
    fills = [fill for fill, _ in points]
    if not fills[0] <= fill_rate <= fills[-1]:
        return None
    return float(np.interp(fill_rate, fills, [value for _, value in points]))
