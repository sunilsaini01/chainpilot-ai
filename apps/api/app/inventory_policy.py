"""Inventory policy math: safety stock, reorder point, order-up-to level, order size.

Plain, deterministic functions with no database access, so they are easy to test
and can be shared by the API (recommendations) and the ML replay simulator.
Standard library only: the simulator imports this module from `ml/`.

Units and assumptions
- Quantities are product units; times are days; demand is units per day.
- Inventory position = on hand + on order (open purchase orders not yet
  received). Retail sales that cannot be served are lost, not backordered, so
  there is no backorder term.
- Periodic review: stock is checked every `review_days` and an order may be
  placed; it arrives after the supplier lead time. An order must therefore cover
  the "protection period" = lead time + review period.
- Daily demand and lead time are treated as independent and roughly normal. Real
  retail demand is lumpy, so the replay simulator (P4-T2) measures whether the
  target service level is actually reached instead of trusting the formula.
- Service level here is the cycle service level: the chance of not running out
  between two deliveries.
"""

import math
from dataclasses import dataclass
from statistics import NormalDist

STANDARD_NORMAL = NormalDist()


def _require_non_negative(**values: float) -> None:
    for name, value in values.items():
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite number >= 0, got {value}")


def inventory_position(on_hand: int, on_order: int) -> int:
    """Units we have or will have without ordering more: on hand + on order."""
    _require_non_negative(on_hand=on_hand, on_order=on_order)
    return on_hand + on_order


def z_for_service_level(service_level: float) -> float:
    """How many standard deviations of safety stock a service level needs (0.95 -> 1.645)."""
    if not 0.5 <= service_level < 1:
        raise ValueError(f"service_level must be in [0.5, 1), got {service_level}")
    return STANDARD_NORMAL.inv_cdf(service_level)


def std_from_interval(lower: float, upper: float, coverage: float = 0.8) -> float:
    """Daily demand standard deviation implied by a central forecast interval.

    An 80% normal interval spans 2 x 1.2816 standard deviations, so
    std = (upper - lower) / 2.563. Used to turn the forecast table's lower/upper
    columns into the demand uncertainty the safety-stock formula needs.
    """
    _require_non_negative(lower=lower, upper=upper)
    if upper < lower:
        raise ValueError("upper must be >= lower")
    if not 0 < coverage < 1:
        raise ValueError(f"coverage must be between 0 and 1, got {coverage}")
    half_width_in_stds = STANDARD_NORMAL.inv_cdf(0.5 + coverage / 2)
    return (upper - lower) / (2 * half_width_in_stds)


def demand_over(
    days: float, daily_mean: float, daily_std: float, lead_time_std: float = 0.0
) -> tuple[float, float]:
    """Mean and standard deviation of total demand over `days` uncertain days.

    Two sources of uncertainty (textbook formula, independent days):
    - demand varies from day to day:   days x daily_std^2
    - the lead time itself varies:     daily_mean^2 x lead_time_std^2
    """
    _require_non_negative(
        days=days, daily_mean=daily_mean, daily_std=daily_std, lead_time_std=lead_time_std
    )
    variance = days * daily_std**2 + daily_mean**2 * lead_time_std**2
    return days * daily_mean, math.sqrt(variance)


def reorder_point(
    daily_mean: float,
    daily_std: float,
    lead_time_days: float,
    lead_time_std: float,
    service_level: float,
) -> float:
    """Inventory position below which stock may run out before a new order arrives.

    Expected demand during the lead time plus safety stock. Used to flag
    stock-out risk: a position below this is at risk if nothing is ordered now.
    """
    mean, std = demand_over(lead_time_days, daily_mean, daily_std, lead_time_std)
    return mean + z_for_service_level(service_level) * std


@dataclass(frozen=True)
class OrderUpToLevel:
    """Target inventory position after ordering, and how it was built (all in units)."""

    expected_demand: float  # over lead time + review period
    safety_stock: float
    level: int  # expected_demand + safety_stock, rounded up to whole units


def order_up_to_level(
    daily_mean: float,
    daily_std: float,
    lead_time_days: float,
    lead_time_std: float,
    review_days: float,
    service_level: float,
) -> OrderUpToLevel:
    """Periodic-review target: enough for the protection period (lead time + review)."""
    _require_non_negative(review_days=review_days)
    mean, std = demand_over(lead_time_days + review_days, daily_mean, daily_std, lead_time_std)
    safety = z_for_service_level(service_level) * std
    return OrderUpToLevel(mean, safety, math.ceil(mean + safety))


@dataclass(frozen=True)
class OrderDecision:
    """How many units to order and why.

    reason is one of:
      not_needed          position already at or above the target
      ordered             the shortfall, rounded up to whole packs
      raised_to_moq       the shortfall was below the supplier's minimum order
      limited             capped by warehouse space or budget (still >= MOQ)
      blocked             the cap leaves less than the minimum order, so nothing
    """

    quantity: int
    shortfall: int  # target - position, before any supplier rules or caps
    reason: str


def order_quantity(
    position: int,
    target_level: int,
    min_order_qty: int = 1,
    pack_size: int = 1,
    max_units: int | None = None,
) -> OrderDecision:
    """Order the shortfall, respecting the supplier's minimum order and pack size.

    `max_units` is the most we may receive: free warehouse space and/or what the
    budget allows (the caller passes the smaller of the two). Supplier rules come
    first, then the cap is applied, rounding down to whole packs.
    """
    _require_non_negative(position=position, target_level=target_level)
    if min_order_qty < 1 or pack_size < 1:
        raise ValueError("min_order_qty and pack_size must be at least 1")
    if max_units is not None:
        _require_non_negative(max_units=max_units)

    shortfall = target_level - position
    if shortfall <= 0:
        return OrderDecision(0, max(shortfall, 0), "not_needed")

    wanted = max(shortfall, min_order_qty)
    reason = "raised_to_moq" if shortfall < min_order_qty else "ordered"
    quantity = math.ceil(wanted / pack_size) * pack_size

    if max_units is not None and quantity > max_units:
        quantity = (max_units // pack_size) * pack_size
        if quantity < min_order_qty:
            return OrderDecision(0, shortfall, "blocked")
        reason = "limited"
    return OrderDecision(quantity, shortfall, reason)


def days_of_cover(on_hand: int, daily_mean: float) -> float:
    """How many days the stock on hand lasts at the expected demand (inf if no demand)."""
    _require_non_negative(on_hand=on_hand, daily_mean=daily_mean)
    return math.inf if daily_mean == 0 else on_hand / daily_mean
