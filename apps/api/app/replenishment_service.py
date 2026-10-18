"""Stock-out risks and reorder/transfer recommendations (P4-T4).

DATA LABEL: stock, suppliers and orders are SIMULATED (SYN- seed data). Their
demand is borrowed from the forecast of a linked M5 item and store (a demo
link, decision D-044); the M5 product is not the same product or company.

How one product at one warehouse is assessed (same rule the replay simulator
validated, D-045):
- daily demand mean and std: the linked forecast's next (lead time + 7) days;
  std from the 80% interval (`std_from_interval`), averaged as variances
- position = on hand + on order (open purchase orders)
- reorder point and order-up-to level from `app/inventory_policy.py`
- status: out_of_stock (nothing on hand, demand expected), at_risk (position
  below the reorder point), excess (on hand more than EXCESS_DAYS of demand
  above the target), otherwise ok

Recommendations are proposals only (status "pending"); approving and executing
them is the approval workflow (P7). Transfers come first (stock another site can
spare), then supplier orders for what is still missing, with the supplier's
minimum order and pack size and each warehouse's free space.
"""

import hashlib
import math
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.audit import record_event
from app.inventory_policy import (
    days_of_cover,
    order_quantity,
    order_up_to_level,
    reorder_point,
    std_from_interval,
)
from app.models import (
    Forecast,
    ForecastRun,
    Inventory,
    InventoryMovement,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    Recommendation,
    RecommendationKind,
    RecommendationStatus,
    Supplier,
    User,
    Warehouse,
)
from app.purchasing_service import on_order_quantities
from app.seed import SKU_PREFIX, WAREHOUSE_PREFIX

DATA_LABEL = (
    "SIMULATED stock and suppliers (SYN-); demand borrowed from M5 forecasts "
    "of linked items (demo link, not the same products)"
)
REVIEW_DAYS = 7  # stock is reviewed weekly, as in the replay simulator
DEFAULT_SERVICE_LEVEL = 0.95  # D-045
MAX_FORECAST_DAYS = 28  # the forecasts cover 28 days
EXCESS_DAYS = 60
# Demo choice: which M5 category stands in for each simulated category.
CATEGORY_TO_M5 = {
    "kitchen": "HOUSEHOLD",
    "home": "HOUSEHOLD",
    "garden": "HOUSEHOLD",
    "office": "HOBBIES",
    "toys": "HOBBIES",
    "sports": "HOBBIES",
    "pets": "FOODS",
    "health": "FOODS",
}
STATUS_ORDER = ["out_of_stock", "at_risk", "ok", "excess"]


class NoForecastRunError(Exception):
    """Raised when no forecast run has been imported yet."""


@dataclass(frozen=True)
class ItemInputs:
    """Everything needed to assess one product at one warehouse."""

    product_id: int
    sku: str
    warehouse_id: int
    warehouse_code: str
    supplier_id: int | None
    on_hand: int
    on_order: int
    daily_mean: float
    daily_std: float
    lead_time_days: int
    lead_time_std: float
    min_order_qty: int
    pack_size: int
    demand_profile: str  # e.g. "FOODS_3_090 at CA_1"


@dataclass(frozen=True)
class Assessment:
    inputs: ItemInputs
    status: str
    position: int
    reorder_point: float
    safety_stock: float
    target_level: int
    days_of_cover: float | None  # None = no demand expected
    shortfall: int  # target - position (0 if none)

    def as_dict(self) -> dict:
        values = asdict(self)
        inputs = values.pop("inputs")
        return {
            **inputs,
            **values,
            "reorder_point": round(self.reorder_point, 2),
            "safety_stock": round(self.safety_stock, 2),
            "daily_mean": round(self.inputs.daily_mean, 3),
            "daily_std": round(self.inputs.daily_std, 3),
            "days_of_cover": None if self.days_of_cover is None else round(self.days_of_cover, 1),
        }


def protection_days(lead_time_days: int) -> int:
    """Days an order must cover: lead time + review period.

    Raises ValueError when that is longer than the forecast: such an item cannot
    be assessed honestly (it is counted as unassessed instead).
    """
    days = lead_time_days + REVIEW_DAYS
    if days > MAX_FORECAST_DAYS:
        raise ValueError(f"lead time + review = {days} days, forecasts cover {MAX_FORECAST_DAYS}")
    return days


def daily_demand(rows: list[tuple[int, float, float, float]], days: int) -> tuple[float, float]:
    """Daily mean and std over forecast steps 1..days from (step, forecast, lower, upper) rows.

    The std is the root mean square of the daily stds, so days x std^2 equals the
    sum of the daily variances. Raises ValueError if a step is missing.
    """
    by_step = {step: (forecast, lower, upper) for step, forecast, lower, upper in rows}
    if any(step not in by_step for step in range(1, days + 1)):
        raise ValueError(f"forecast does not cover steps 1 to {days}")
    chosen = [by_step[step] for step in range(1, days + 1)]
    mean = sum(forecast for forecast, _, _ in chosen) / days
    variance = sum(std_from_interval(lower, upper) ** 2 for _, lower, upper in chosen) / days
    return mean, math.sqrt(variance)


def assess(inputs: ItemInputs, service_level: float) -> Assessment:
    """Status, reorder point and target level for one product at one warehouse."""
    position = inputs.on_hand + inputs.on_order
    rop = reorder_point(
        inputs.daily_mean,
        inputs.daily_std,
        inputs.lead_time_days,
        inputs.lead_time_std,
        service_level,
    )
    target = order_up_to_level(
        inputs.daily_mean,
        inputs.daily_std,
        inputs.lead_time_days,
        inputs.lead_time_std,
        REVIEW_DAYS,
        service_level,
    )
    cover = days_of_cover(inputs.on_hand, inputs.daily_mean)
    if inputs.on_hand == 0 and inputs.daily_mean > 0:
        status = "out_of_stock"
    elif position < rop:
        status = "at_risk"
    elif inputs.on_hand > target.level + EXCESS_DAYS * inputs.daily_mean:
        status = "excess"
    else:
        status = "ok"
    return Assessment(
        inputs,
        status,
        position,
        rop,
        target.safety_stock,
        target.level,
        None if math.isinf(cover) else cover,
        max(target.level - position, 0),
    )


def priority(assessment: Assessment) -> tuple:
    """Most urgent first: by status, then fewest days of cover, then SKU and site."""
    cover = assessment.days_of_cover
    return (
        STATUS_ORDER.index(assessment.status),
        math.inf if cover is None else cover,
        assessment.inputs.sku,
        assessment.inputs.warehouse_code,
    )


@dataclass
class Plan:
    """Planned moves: (source, destination, units) transfers and reorders per item."""

    transfers: list[tuple[Assessment, Assessment, int]] = field(default_factory=list)
    reorders: list[tuple[Assessment, int, str]] = field(default_factory=list)
    blocked: list[Assessment] = field(default_factory=list)  # no space or no supplier


def plan_replenishment(assessments: list[Assessment], free_space: dict[int, int]) -> Plan:
    """Transfers first, then supplier orders, most urgent items first.

    A site can give only the units it holds above its own target (so a site that
    is short of the product gives nothing). `free_space` (units per warehouse) is
    shared by everything arriving there and is reduced as plans are made.
    """
    plan = Plan()
    space = dict(free_space)
    incoming: dict[tuple[int, int], int] = defaultdict(int)  # (product, warehouse) -> units
    spare: dict[tuple[int, int], int] = {}
    for item in assessments:
        key = (item.inputs.product_id, item.inputs.warehouse_id)
        # Only stock above the site's own target can be given. A short site never
        # has any: its on hand is below the reorder point, which is below the target.
        spare[key] = max(item.inputs.on_hand - item.target_level, 0)

    ordered = sorted(assessments, key=priority)
    by_product = defaultdict(list)
    for item in ordered:
        by_product[item.inputs.product_id].append(item)

    # 1. Transfers, only for items that are short (below their reorder point or empty).
    for item in ordered:
        if item.status not in ("out_of_stock", "at_risk"):
            continue
        need = item.shortfall
        donors = sorted(
            (other for other in by_product[item.inputs.product_id] if other is not item),
            key=lambda other: -spare[(other.inputs.product_id, other.inputs.warehouse_id)],
        )
        for donor in donors:
            donor_key = (donor.inputs.product_id, donor.inputs.warehouse_id)
            units = min(need, spare[donor_key], space[item.inputs.warehouse_id])
            if units <= 0:
                continue
            plan.transfers.append((donor, item, units))
            spare[donor_key] -= units
            space[item.inputs.warehouse_id] -= units
            incoming[(item.inputs.product_id, item.inputs.warehouse_id)] += units
            need -= units

    # 2. Supplier orders for whatever is still below the target (order-up-to rule).
    for item in ordered:
        position = item.position + incoming[(item.inputs.product_id, item.inputs.warehouse_id)]
        if position >= item.target_level:
            continue
        if item.inputs.supplier_id is None:
            plan.blocked.append(item)
            continue
        decision = order_quantity(
            position,
            item.target_level,
            item.inputs.min_order_qty,
            item.inputs.pack_size,
            max_units=max(space[item.inputs.warehouse_id], 0),
        )
        if decision.quantity == 0:
            plan.blocked.append(item)
            continue
        plan.reorders.append((item, decision.quantity, decision.reason))
        space[item.inputs.warehouse_id] -= decision.quantity
    return plan


# --- Database side ---------------------------------------------------------------


def newest_forecast_run(session: Session) -> ForecastRun:
    run = session.execute(
        select(ForecastRun).order_by(ForecastRun.id.desc()).limit(1)
    ).scalar_one_or_none()
    if run is None:
        raise NoForecastRunError("No forecast run imported yet (see import-forecasts)")
    return run


def link_demand_profiles(session: Session) -> dict[str, int]:
    """Give unlinked SYN- products an M5 item and SYN- warehouses an M5 store.

    Uses the newest forecast run. The item is chosen from the mapped M5 category
    by a SHA-256 of the SKU, so the same SKU always gets the same item. Existing
    links are never changed. Does not commit.
    """
    run = newest_forecast_run(session)
    items_by_category: dict[str, list[str]] = defaultdict(list)
    for item_id, category in session.execute(
        select(Forecast.item_id, Forecast.cat_id).where(Forecast.run_id == run.id).distinct()
    ):
        items_by_category[category].append(item_id)
    stores = sorted(
        session.execute(select(Forecast.store_id).where(Forecast.run_id == run.id).distinct())
        .scalars()
        .all()
    )

    linked_products = 0
    products = session.execute(
        select(Product)
        .where(Product.sku.startswith(SKU_PREFIX), Product.demand_profile_item_id.is_(None))
        .order_by(Product.sku)
    ).scalars()
    for product in products:
        candidates = sorted(items_by_category.get(CATEGORY_TO_M5.get(product.category, ""), []))
        if not candidates:
            continue
        digest = int(hashlib.sha256(product.sku.encode()).hexdigest(), 16)
        product.demand_profile_item_id = candidates[digest % len(candidates)]
        linked_products += 1

    linked_warehouses = 0
    warehouses = session.execute(
        select(Warehouse)
        .where(Warehouse.code.startswith(WAREHOUSE_PREFIX))
        .order_by(Warehouse.code)
    ).scalars()
    for warehouse, store in zip(warehouses, stores, strict=False):
        if warehouse.demand_profile_store_id is None:
            warehouse.demand_profile_store_id = store
            linked_warehouses += 1
    session.flush()
    return {"forecast_run_id": run.id, "products": linked_products, "warehouses": linked_warehouses}


def load_inputs(
    session: Session, run: ForecastRun, warehouse_id: int | None = None
) -> tuple[list[ItemInputs], int]:
    """Inputs for every linked product at every linked warehouse.

    Returns the inputs and how many product/warehouse pairs could not be
    assessed (no demand link, or no forecast for the needed days).
    """
    warehouse_query = select(Warehouse).order_by(Warehouse.code)
    if warehouse_id is not None:
        warehouse_query = warehouse_query.where(Warehouse.id == warehouse_id)
    warehouses = session.execute(warehouse_query).scalars().all()
    rows = session.execute(
        select(Product, Supplier)
        .outerjoin(Supplier, Product.supplier_id == Supplier.id)
        .where(Product.is_active.is_(True))
        .order_by(Product.sku)
    ).all()
    total_pairs = len(warehouses) * len(rows)

    linked_sites = [site for site in warehouses if site.demand_profile_store_id]
    linked_products = [(p, s) for p, s in rows if p.demand_profile_item_id]
    on_hand = {
        (product, site): units
        for product, site, units in session.execute(
            select(Inventory.product_id, Inventory.warehouse_id, Inventory.on_hand)
        )
    }
    on_order = on_order_quantities(session, warehouse_id)
    forecast_rows: dict[tuple[str, str], list] = defaultdict(list)
    if linked_sites and linked_products:
        query = select(
            Forecast.item_id,
            Forecast.store_id,
            Forecast.step,
            Forecast.forecast,
            Forecast.lower,
            Forecast.upper,
        ).where(
            Forecast.run_id == run.id,
            Forecast.step <= MAX_FORECAST_DAYS,
            Forecast.store_id.in_({site.demand_profile_store_id for site in linked_sites}),
            Forecast.item_id.in_(
                {product.demand_profile_item_id for product, _ in linked_products}
            ),
        )
        for item, store, step, forecast, lower, upper in session.execute(query):
            forecast_rows[(item, store)].append((step, forecast, lower, upper))

    inputs = []
    for product, supplier in linked_products:
        lead = supplier.lead_time_days if supplier else 7  # no supplier: cannot reorder anyway
        lead_std = float(supplier.lead_time_std_days) if supplier else 0.0
        for site in linked_sites:
            series = (product.demand_profile_item_id, site.demand_profile_store_id)
            try:
                mean, std = daily_demand(forecast_rows[series], protection_days(lead))
            except ValueError:
                continue  # not assessed: counted below
            inputs.append(
                ItemInputs(
                    product_id=product.id,
                    sku=product.sku,
                    warehouse_id=site.id,
                    warehouse_code=site.code,
                    supplier_id=product.supplier_id,
                    on_hand=on_hand.get((product.id, site.id), 0),
                    on_order=on_order.get((product.id, site.id), 0),
                    daily_mean=mean,
                    daily_std=std,
                    lead_time_days=lead,
                    lead_time_std=lead_std,
                    min_order_qty=product.min_order_qty,
                    pack_size=product.pack_size,
                    demand_profile=f"{series[0]} at {series[1]}",
                )
            )
    return inputs, total_pairs - len(inputs)


# --- Cache (P9-T1-R1) -----------------------------------------------------------------
# The overview, the stock-risk list and the copilot all need the assessment of every
# pair, which takes a few hundred CPU milliseconds. It is kept for a short time and
# reused while its inputs are unchanged, per API process.

CACHE_SECONDS = 60  # safety net: even an unnoticed change shows within a minute
CACHE_ENTRIES = 16  # e.g. a few service levels and warehouse filters
_cache: dict[tuple, tuple[float, list[Assessment], int]] = {}
_cache_lock = threading.Lock()


def data_version(session: Session) -> tuple:
    """A value that changes whenever an input of the assessment changes.

    Counts, not only timestamps: PostgreSQL's now() is a transaction's start time, so
    a slow transaction can commit after a faster one with an older timestamp. Every
    committed stock movement raises the movement count (the ledger is append-only),
    and every new, received or cancelled order changes the open-order numbers.
    Products, warehouses and suppliers change rarely (admin edits, demand links):
    their newest updated_at and row count, plus the cache's 60 s limit.
    """
    open_lines = (
        select(func.count(), func.coalesce(func.sum(PurchaseOrderLine.quantity), 0))
        .join(PurchaseOrder)
        .where(PurchaseOrder.status == PurchaseOrderStatus.OPEN)
    )
    movements = select(func.count()).select_from(InventoryMovement)
    parts = [movements, open_lines]
    for model in (Product, Warehouse, Supplier):
        parts.append(select(func.count(), func.max(model.updated_at)).select_from(model))
    return tuple(tuple(session.execute(part).one()) for part in parts)


def clear_assessment_cache() -> None:
    with _cache_lock:
        _cache.clear()


def assess_all(
    session: Session, service_level: float, warehouse_id: int | None = None
) -> tuple[ForecastRun, list[Assessment], int]:
    """Assess every linked pair, most urgent first. Returns (run, assessments, unassessed).

    Served from the cache while the forecast run and the data version are unchanged
    and the entry is under CACHE_SECONDS old.
    """
    run = newest_forecast_run(session)
    key = (run.id, service_level, warehouse_id, data_version(session))
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None and now - cached[0] < CACHE_SECONDS:
        return run, list(cached[1]), cached[2]  # a copy: callers may reorder their list

    inputs, unassessed = load_inputs(session, run, warehouse_id)
    assessments = sorted((assess(item, service_level) for item in inputs), key=priority)
    with _cache_lock:
        if len(_cache) >= CACHE_ENTRIES:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]))  # the oldest entry
        _cache[key] = (now, assessments, unassessed)
    return run, list(assessments), unassessed


def free_space(session: Session) -> dict[int, int]:
    """Units each warehouse can still take: capacity - on hand - open orders to it."""
    stored = dict(
        session.execute(
            select(Inventory.warehouse_id, func.sum(Inventory.on_hand)).group_by(
                Inventory.warehouse_id
            )
        ).all()
    )
    incoming: dict[int, int] = defaultdict(int)
    for (_, site), units in on_order_quantities(session).items():
        incoming[site] += units
    return {
        site.id: site.capacity_units - int(stored.get(site.id, 0)) - incoming[site.id]
        for site in session.execute(select(Warehouse)).scalars()
    }


def create_recommendations(
    session: Session, service_level: float, actor: User | None
) -> tuple[list[Recommendation], dict[str, int]]:
    """Replace pending recommendations with a fresh set. Does not commit."""
    run, assessments, unassessed = assess_all(session, service_level)
    plan = plan_replenishment(assessments, free_space(session))

    superseded = session.execute(
        update(Recommendation)
        .where(Recommendation.status == RecommendationStatus.PENDING)
        .values(status=RecommendationStatus.SUPERSEDED)
    ).rowcount

    common = {
        "forecast_run_id": run.id,
        "service_level": service_level,
        "created_by_user_id": actor.id if actor else None,
        "status": RecommendationStatus.PENDING,
    }
    created = []
    for donor, item, units in plan.transfers:
        created.append(
            Recommendation(
                kind=RecommendationKind.TRANSFER,
                product_id=item.inputs.product_id,
                warehouse_id=item.inputs.warehouse_id,
                source_warehouse_id=donor.inputs.warehouse_id,
                quantity=units,
                reason="transfer_spare_stock",
                details={"destination": item.as_dict(), "source": donor.as_dict()},
                **common,
            )
        )
    for item, units, reason in plan.reorders:
        created.append(
            Recommendation(
                kind=RecommendationKind.REORDER,
                product_id=item.inputs.product_id,
                warehouse_id=item.inputs.warehouse_id,
                supplier_id=item.inputs.supplier_id,
                quantity=units,
                reason=reason,
                details={"item": item.as_dict()},
                **common,
            )
        )
    session.add_all(created)
    session.flush()

    summary = {
        "assessed": len(assessments),
        "unassessed": unassessed,
        "transfers": len(plan.transfers),
        "reorders": len(plan.reorders),
        "blocked": len(plan.blocked),
        "superseded": superseded,
    }
    record_event(
        session,
        "recommendations.generated",
        "recommendation",
        None,
        actor=actor,
        details={"forecast_run_id": run.id, "service_level": service_level, **summary},
    )
    return created, summary
