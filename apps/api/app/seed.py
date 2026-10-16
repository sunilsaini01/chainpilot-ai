"""Deterministic synthetic demo data: warehouses, products, opening stock,
suppliers and purchase orders.

SYNTHETIC DATA: nothing here describes a real company. Every SKU starts with
"SYN-", every warehouse code with "SYN-WH", every supplier code with "SYN-SUP"
and every purchase order number with "SYN-PO-", so the data is easy to spot.

Two steps keep this testable:
1. `build_plan()` is pure Python: the same seed always gives the same plan.
2. `load_plan()` writes the plan to the database. Opening stock goes through
   `record_movement`, so the stock ledger and capacity rules apply as usual.
"""

import random
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.inventory_service import record_movement
from app.models import (
    MovementReason,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    Supplier,
    Warehouse,
)

SKU_PREFIX = "SYN-"
WAREHOUSE_PREFIX = "SYN-WH"
OPENING_REFERENCE = "SEED-OPENING"

# Bounds from the project spec (section 3).
MIN_PRODUCTS, MAX_PRODUCTS = 100, 500
MIN_WAREHOUSES, MAX_WAREHOUSES = 3, 5

# Opening stock fills at most this share of each warehouse, leaving room for receipts.
MAX_FILL_SHARE = Decimal("0.70")
# Share of product/warehouse pairs that start with stock (the rest start empty).
STOCKED_SHARE = 0.8
# Share of stocked pairs that start nearly empty (1-20 units), so the demo has
# low-stock items for stock-out detection to find.
LOW_STOCK_SHARE = 0.1
LOW_STOCK_MAX_UNITS = 20

CATEGORIES = ["kitchen", "home", "office", "garden", "toys", "sports", "pets", "health"]
ADJECTIVES = ["Classic", "Compact", "Deluxe", "Eco", "Large", "Mini", "Premium", "Smart"]
NOUNS = {
    "kitchen": ["Mug", "Pan", "Kettle", "Knife Set", "Blender"],
    "home": ["Lamp", "Cushion", "Rug", "Clock", "Mirror"],
    "office": ["Notebook", "Desk Tidy", "Stapler", "Monitor Arm", "Chair Mat"],
    "garden": ["Hose", "Planter", "Trowel", "Bird Feeder", "Solar Light"],
    "toys": ["Puzzle", "Building Kit", "Plush Bear", "Kite", "Board Game"],
    "sports": ["Yoga Mat", "Water Bottle", "Dumbbell", "Football", "Skipping Rope"],
    "pets": ["Dog Bed", "Cat Toy", "Food Bowl", "Lead", "Litter Tray"],
    "health": ["First Aid Kit", "Thermometer", "Hand Gel", "Vitamins", "Face Masks"],
}
SITES = [
    ("North DC", "Leeds", 60_000),
    ("South DC", "Southampton", 50_000),
    ("Midlands DC", "Birmingham", 80_000),
    ("Scotland DC", "Glasgow", 40_000),
    ("West DC", "Bristol", 45_000),
]

# Simulated suppliers: (code, name, country, promised lead time in days, its
# standard deviation, average days late). Two are deliberately unreliable
# (SUP04, SUP06) so that supplier-risk checks have something to find.
SUPPLIERS = [
    ("SYN-SUP01", "Simulated Housewares Supplier", "United Kingdom", 4, 0.5, 0.0),
    ("SYN-SUP02", "Simulated General Importer", "Netherlands", 7, 1.0, 0.5),
    ("SYN-SUP03", "Simulated Garden Supplier", "Poland", 10, 2.0, 1.0),
    ("SYN-SUP04", "Simulated Far-East Trader", "China", 21, 4.0, 4.0),
    ("SYN-SUP05", "Simulated Sports Supplier", "Germany", 6, 1.0, 0.0),
    ("SYN-SUP06", "Simulated Toy Maker", "Vietnam", 18, 3.0, 2.5),
]
# Which suppliers can supply each category (one is picked per product).
CATEGORY_SUPPLIERS = {
    "kitchen": ["SYN-SUP01", "SYN-SUP02"],
    "home": ["SYN-SUP01", "SYN-SUP04"],
    "office": ["SYN-SUP02", "SYN-SUP05"],
    "garden": ["SYN-SUP03"],
    "toys": ["SYN-SUP06", "SYN-SUP04"],
    "sports": ["SYN-SUP05", "SYN-SUP04"],
    "pets": ["SYN-SUP02", "SYN-SUP03"],
    "health": ["SYN-SUP01", "SYN-SUP05"],
}
PO_PREFIX = "SYN-PO-"
HISTORY_DAYS = 120  # purchase-order history before the "as of" date
ORDER_GAP_DAYS = (10, 18)  # days between two orders from one supplier to one site
LINES_PER_ORDER = (3, 8)
# The demo's "today". The seed command passes the real date; tests use this
# default so the plan stays the same from day to day.
DEFAULT_AS_OF = date(2026, 10, 16)


@dataclass(frozen=True)
class PlannedWarehouse:
    code: str
    name: str
    city: str
    capacity_units: int


@dataclass(frozen=True)
class PlannedSupplier:
    code: str
    name: str
    country: str
    lead_time_days: int
    lead_time_std_days: Decimal
    average_days_late: float  # only used to simulate the order history


@dataclass(frozen=True)
class PlannedProduct:
    sku: str
    name: str
    category: str
    unit_cost: Decimal
    unit_price: Decimal
    supplier_code: str | None = None
    min_order_qty: int = 1
    pack_size: int = 1


@dataclass(frozen=True)
class PlannedStock:
    sku: str
    warehouse_code: str
    quantity: int


@dataclass(frozen=True)
class PlannedLine:
    sku: str
    quantity: int
    unit_cost: Decimal


@dataclass(frozen=True)
class PlannedPurchaseOrder:
    po_number: str
    supplier_code: str
    warehouse_code: str
    ordered_date: date
    expected_date: date
    received_date: date | None  # None = still open (on order)
    lines: tuple[PlannedLine, ...]


@dataclass(frozen=True)
class SeedPlan:
    seed: int
    warehouses: list[PlannedWarehouse]
    products: list[PlannedProduct]
    opening_stock: list[PlannedStock]
    suppliers: list[PlannedSupplier]
    purchase_orders: list[PlannedPurchaseOrder]
    as_of: date


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_plan(
    seed: int = 42, n_products: int = 200, n_warehouses: int = 4, as_of: date = DEFAULT_AS_OF
) -> SeedPlan:
    """Create the synthetic data plan. Raises ValueError for sizes outside the spec bounds.

    `as_of` is the demo's "today": the order history ends there, and open orders
    are the ones that have not arrived by then.
    """
    if not MIN_PRODUCTS <= n_products <= MAX_PRODUCTS:
        raise ValueError(f"products must be between {MIN_PRODUCTS} and {MAX_PRODUCTS}")
    if not MIN_WAREHOUSES <= n_warehouses <= MAX_WAREHOUSES:
        raise ValueError(f"warehouses must be between {MIN_WAREHOUSES} and {MAX_WAREHOUSES}")

    # One private generator, never the global `random`, so the plan depends only on `seed`.
    rng = random.Random(seed)

    warehouses = [
        PlannedWarehouse(f"{WAREHOUSE_PREFIX}{number}", name, city, capacity)
        for number, (name, city, capacity) in enumerate(SITES[:n_warehouses], start=1)
    ]

    products = []
    for number in range(1, n_products + 1):
        category = rng.choice(CATEGORIES)
        name = f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS[category])}"
        unit_cost = _money(rng.uniform(1.0, 60.0))
        # Retail markup between 30% and 120% over cost.
        unit_price = _money(float(unit_cost) * rng.uniform(1.3, 2.2))
        products.append(
            PlannedProduct(f"{SKU_PREFIX}{number:04d}", name, category, unit_cost, unit_price)
        )

    opening_stock = []
    for warehouse in warehouses:
        budget = int(warehouse.capacity_units * MAX_FILL_SHARE)
        stocked = [product for product in products if rng.random() < STOCKED_SHARE]
        low = [product for product in stocked if rng.random() < LOW_STOCK_SHARE]
        regular = [product for product in stocked if product not in low]

        for product in low:
            quantity = rng.randint(1, LOW_STOCK_MAX_UNITS)
            opening_stock.append(PlannedStock(product.sku, warehouse.code, quantity))
            budget -= quantity

        # Random weights split the remaining budget between the regular products,
        # so the total can never exceed it (each share is rounded down).
        weights = [rng.uniform(0.2, 1.0) for _ in regular]
        total_weight = sum(weights)
        for product, weight in zip(regular, weights, strict=True):
            quantity = int(budget * weight / total_weight)
            if quantity > 0:
                opening_stock.append(PlannedStock(product.sku, warehouse.code, quantity))

    # Suppliers and orders (P4-T3) are drawn after the products and stock, so a
    # given seed still produces the same products and stock as before they existed.
    suppliers = [
        PlannedSupplier(code, name, country, lead, Decimal(str(std)), late)
        for code, name, country, lead, std, late in SUPPLIERS
    ]
    products = [_with_purchasing_rules(product, rng) for product in products]
    purchase_orders = _order_history(rng, suppliers, warehouses, products, as_of)
    return SeedPlan(seed, warehouses, products, opening_stock, suppliers, purchase_orders, as_of)


def _with_purchasing_rules(product: PlannedProduct, rng: random.Random) -> PlannedProduct:
    """Pick a supplier for the product's category, a pack size and a minimum order."""
    pack_size = rng.choice([1, 1, 6, 12])
    return replace(
        product,
        supplier_code=rng.choice(CATEGORY_SUPPLIERS[product.category]),
        pack_size=pack_size,
        min_order_qty=pack_size * rng.choice([1, 2, 4]),  # always whole packs
    )


def _order_history(
    rng: random.Random,
    suppliers: list[PlannedSupplier],
    warehouses: list[PlannedWarehouse],
    products: list[PlannedProduct],
    as_of: date,
) -> list[PlannedPurchaseOrder]:
    """Orders placed over the last HISTORY_DAYS from each supplier to each warehouse.

    The actual lead time is drawn around the promised one plus the supplier's
    average lateness. Orders that arrived by `as_of` are received (their goods
    are part of the opening stock, so no extra stock movements are made); the
    others are still open, and some of those are already overdue.
    """
    orders = []
    for warehouse in warehouses:
        for supplier in suppliers:
            catalogue = [p for p in products if p.supplier_code == supplier.code]
            if not catalogue:
                continue
            ordered = as_of - timedelta(days=HISTORY_DAYS - rng.randint(0, 9))
            while ordered <= as_of:
                actual_days = round(
                    rng.gauss(
                        supplier.lead_time_days + supplier.average_days_late,
                        float(supplier.lead_time_std_days),
                    )
                )
                arrival = ordered + timedelta(days=max(actual_days, 1))
                count = min(rng.randint(*LINES_PER_ORDER), len(catalogue))
                chosen = sorted(rng.sample(catalogue, count), key=lambda p: p.sku)
                lines = tuple(
                    PlannedLine(p.sku, p.min_order_qty * rng.randint(1, 4), p.unit_cost)
                    for p in chosen
                )
                expected = ordered + timedelta(days=supplier.lead_time_days)
                received = arrival if arrival <= as_of else None
                orders.append((ordered, warehouse.code, supplier.code, expected, received, lines))
                ordered += timedelta(days=rng.randint(*ORDER_GAP_DAYS))

    # Numbered in date order, as a purchasing system would.
    orders.sort(key=lambda order: order[:3])
    return [
        PlannedPurchaseOrder(
            f"{PO_PREFIX}{number:06d}", supplier, site, ordered, expected, received, lines
        )
        for number, (ordered, site, supplier, expected, received, lines) in enumerate(
            orders, start=1
        )
    ]


class AlreadySeededError(Exception):
    """Raised when synthetic data is already in the database."""


def already_seeded(session: Session) -> bool:
    count = session.execute(
        select(func.count()).select_from(Product).where(Product.sku.startswith(SKU_PREFIX))
    ).scalar_one()
    return count > 0


def load_plan(session: Session, plan: SeedPlan) -> dict[str, int]:
    """Write the plan in the caller's transaction. Never deletes or overwrites anything.

    Raises AlreadySeededError if synthetic products already exist, so running
    the command twice cannot double the stock.
    """
    if already_seeded(session):
        raise AlreadySeededError("Synthetic data is already loaded (SYN- products exist)")

    supplier_ids = {}
    for planned in plan.suppliers:
        supplier = Supplier(
            code=planned.code,
            name=planned.name,
            country=planned.country,
            lead_time_days=planned.lead_time_days,
            lead_time_std_days=planned.lead_time_std_days,
        )
        session.add(supplier)
        session.flush()
        supplier_ids[planned.code] = supplier.id

    warehouse_ids = {}
    for planned in plan.warehouses:
        warehouse = Warehouse(
            code=planned.code,
            name=planned.name,
            city=planned.city,
            capacity_units=planned.capacity_units,
        )
        session.add(warehouse)
        session.flush()
        warehouse_ids[planned.code] = warehouse.id

    product_ids = {}
    for planned in plan.products:
        product = Product(
            sku=planned.sku,
            name=planned.name,
            category=planned.category,
            unit_cost=planned.unit_cost,
            unit_price=planned.unit_price,
            supplier_id=supplier_ids.get(planned.supplier_code),
            min_order_qty=planned.min_order_qty,
            pack_size=planned.pack_size,
        )
        session.add(product)
        session.flush()
        product_ids[planned.sku] = product.id

    for stock in plan.opening_stock:
        # actor None = system process (see record_movement).
        record_movement(
            session,
            product_ids[stock.sku],
            warehouse_ids[stock.warehouse_code],
            stock.quantity,
            MovementReason.RECEIPT,
            reference=OPENING_REFERENCE,
        )

    # Purchase orders are documents, not stock changes: received ones are already
    # part of the opening stock; open ones arrive later through the receive action.
    for planned in plan.purchase_orders:
        received = planned.received_date is not None
        session.add(
            PurchaseOrder(
                po_number=planned.po_number,
                supplier_id=supplier_ids[planned.supplier_code],
                warehouse_id=warehouse_ids[planned.warehouse_code],
                status=PurchaseOrderStatus.RECEIVED if received else PurchaseOrderStatus.OPEN,
                ordered_date=planned.ordered_date,
                expected_date=planned.expected_date,
                received_date=planned.received_date,
                lines=[
                    PurchaseOrderLine(
                        product_id=product_ids[line.sku],
                        quantity=line.quantity,
                        unit_cost=line.unit_cost,
                    )
                    for line in planned.lines
                ],
            )
        )
    session.flush()

    open_orders = [order for order in plan.purchase_orders if order.received_date is None]
    summary = {
        "warehouses": len(plan.warehouses),
        "products": len(plan.products),
        "opening_movements": len(plan.opening_stock),
        "units": sum(stock.quantity for stock in plan.opening_stock),
        "suppliers": len(plan.suppliers),
        "purchase_orders": len(plan.purchase_orders),
        "open_purchase_orders": len(open_orders),
    }
    record_event(
        session,
        "seed.loaded",
        "seed",
        None,
        actor=None,
        details={"seed": plan.seed, "as_of": plan.as_of.isoformat(), **summary},
    )
    return summary
