"""Synthetic seed data tests. Plan tests need no database; loading tests need RUN_DB_TESTS=1."""

import os
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app import cli
from app.models import (
    AuditEvent,
    Inventory,
    InventoryMovement,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    Warehouse,
)
from app.seed import (
    CATEGORY_SUPPLIERS,
    HISTORY_DAYS,
    LOW_STOCK_MAX_UNITS,
    MAX_FILL_SHARE,
    OPENING_REFERENCE,
    AlreadySeededError,
    build_plan,
    load_plan,
)

needs_db = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="set RUN_DB_TESTS=1 with Postgres running"
)


# --- The plan (pure Python) ----------------------------------------------------


def test_same_seed_gives_identical_plan() -> None:
    assert build_plan(seed=7) == build_plan(seed=7)


def test_different_seed_gives_different_plan() -> None:
    assert build_plan(seed=7).products != build_plan(seed=8).products


@pytest.mark.parametrize(
    ("products", "warehouses", "message"),
    [(99, 4, "products"), (501, 4, "products"), (200, 2, "warehouses"), (200, 6, "warehouses")],
)
def test_sizes_outside_spec_bounds_are_rejected(
    products: int, warehouses: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_plan(n_products=products, n_warehouses=warehouses)


@pytest.mark.parametrize(("products", "warehouses"), [(100, 3), (500, 5)])
def test_plan_sizes_and_synthetic_labels(products: int, warehouses: int) -> None:
    plan = build_plan(n_products=products, n_warehouses=warehouses)

    assert len(plan.products) == products
    assert len(plan.warehouses) == warehouses
    assert all(product.sku.startswith("SYN-") for product in plan.products)
    assert all(site.code.startswith("SYN-WH") for site in plan.warehouses)
    assert len({product.sku for product in plan.products}) == products  # unique


def test_prices_are_exact_and_above_cost() -> None:
    for product in build_plan().products:
        assert product.unit_cost > 0
        assert product.unit_price > product.unit_cost
        assert product.unit_cost == product.unit_cost.quantize(Decimal("0.01"))
        assert product.unit_price == product.unit_price.quantize(Decimal("0.01"))


def test_opening_stock_fits_within_the_fill_limit_of_each_warehouse() -> None:
    plan = build_plan(n_products=500, n_warehouses=5)
    totals: dict[str, int] = defaultdict(int)
    for stock in plan.opening_stock:
        assert stock.quantity > 0
        totals[stock.warehouse_code] += stock.quantity

    for site in plan.warehouses:
        assert 0 < totals[site.code] <= site.capacity_units * MAX_FILL_SHARE


def test_not_every_product_is_stocked_everywhere() -> None:
    # Some product/warehouse pairs start empty, so stock-outs exist to investigate later.
    plan = build_plan()
    pairs = {(stock.sku, stock.warehouse_code) for stock in plan.opening_stock}

    assert len(pairs) < len(plan.products) * len(plan.warehouses)


# --- Loading into PostgreSQL -----------------------------------------------------


@needs_db
def test_load_writes_plan_through_the_stock_ledger(db_session: Session) -> None:
    plan = build_plan(n_products=100, n_warehouses=3)

    summary = load_plan(db_session, plan)
    db_session.commit()

    def count(model) -> int:
        return db_session.execute(select(func.count()).select_from(model)).scalar_one()

    assert count(Warehouse) == 3
    assert count(Product) == 100
    assert count(InventoryMovement) == len(plan.opening_stock) == summary["opening_movements"]
    # Every opening unit is explained by a ledger entry from the system (no user).
    ledger_total = db_session.execute(
        select(func.sum(InventoryMovement.quantity_change)).where(
            InventoryMovement.reason == "receipt",
            InventoryMovement.reference == OPENING_REFERENCE,
            InventoryMovement.created_by_user_id.is_(None),
        )
    ).scalar_one()
    on_hand_total = db_session.execute(select(func.sum(Inventory.on_hand))).scalar_one()
    assert ledger_total == on_hand_total == summary["units"]
    event = db_session.execute(select(AuditEvent)).scalar_one()
    assert (event.action, event.actor_user_id, event.details["seed"]) == ("seed.loaded", None, 42)


@needs_db
def test_loading_twice_is_refused_and_changes_nothing(db_session: Session) -> None:
    load_plan(db_session, build_plan(n_products=100, n_warehouses=3))
    db_session.commit()

    with pytest.raises(AlreadySeededError):
        load_plan(db_session, build_plan(seed=99, n_products=100, n_warehouses=3))
    db_session.rollback()

    assert db_session.execute(select(func.count()).select_from(Product)).scalar_one() == 100


@needs_db
def test_seed_command(
    monkeypatch: pytest.MonkeyPatch,
    db_engine: Engine,
    db_session: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_engine", lambda: db_engine)

    assert cli.main(["seed", "--products", "100", "--warehouses", "3", "--seed", "5"]) == 0
    assert "Loaded SYNTHETIC data (seed 5): 3 warehouses, 100 products" in capsys.readouterr().out

    assert cli.main(["seed", "--products", "100", "--warehouses", "3"]) == 1
    assert "already loaded" in capsys.readouterr().err
    assert cli.main(["seed", "--products", "50"]) == 1
    assert "between 100 and 500" in capsys.readouterr().err


def test_plan_includes_low_stock_and_well_stocked_items() -> None:
    quantities = [stock.quantity for stock in build_plan().opening_stock]
    low = [quantity for quantity in quantities if quantity <= LOW_STOCK_MAX_UNITS]

    # Roughly 10% of stocked pairs are low (a fixed seed makes this exact and repeatable).
    assert 0.05 * len(quantities) < len(low) < 0.15 * len(quantities)
    assert max(quantities) > 100


# --- Suppliers and purchase orders (P4-T3) ---------------------------------------


def test_products_and_stock_are_unchanged_by_the_purchasing_data() -> None:
    # Values produced by seed 42 before suppliers and orders existed: the purchasing
    # data is drawn afterwards, so old seeds give the same catalogue and stock.
    plan = build_plan(42, 200, 4)
    first = plan.products[0]
    assert (first.sku, first.name, first.unit_cost) == ("SYN-0001", "Classic Rug", Decimal("15.45"))
    assert (len(plan.opening_stock), sum(s.quantity for s in plan.opening_stock)) == (654, 160712)


def test_every_product_has_a_supplier_for_its_category_and_whole_pack_rules() -> None:
    plan = build_plan()
    for product in plan.products:
        assert product.supplier_code in CATEGORY_SUPPLIERS[product.category]
        assert product.min_order_qty >= product.pack_size >= 1
        assert product.min_order_qty % product.pack_size == 0


def test_purchase_orders_are_labelled_numbered_and_consistent() -> None:
    plan = build_plan(n_products=500, n_warehouses=5)
    products = {product.sku: product for product in plan.products}
    leads = {supplier.code: supplier.lead_time_days for supplier in plan.suppliers}

    assert all(supplier.code.startswith("SYN-SUP") for supplier in plan.suppliers)
    numbers = [order.po_number for order in plan.purchase_orders]
    assert numbers == [f"SYN-PO-{n:06d}" for n in range(1, len(numbers) + 1)]
    dates = [order.ordered_date for order in plan.purchase_orders]
    assert dates == sorted(dates)
    for order in plan.purchase_orders:
        assert plan.as_of - timedelta(days=HISTORY_DAYS) <= order.ordered_date <= plan.as_of
        assert order.expected_date == order.ordered_date + timedelta(
            days=leads[order.supplier_code]
        )
        if order.received_date is not None:
            assert order.ordered_date < order.received_date <= plan.as_of
        assert len({line.sku for line in order.lines}) == len(order.lines) > 0
        for line in order.lines:
            product = products[line.sku]
            assert product.supplier_code == order.supplier_code  # ordered from its own supplier
            assert line.quantity % product.min_order_qty == 0
            assert line.unit_cost == product.unit_cost


def test_history_has_open_overdue_orders_and_an_unreliable_supplier() -> None:
    plan = build_plan()
    open_orders = [order for order in plan.purchase_orders if order.received_date is None]
    overdue = [order for order in open_orders if order.expected_date < plan.as_of]

    def late_share(code: str) -> float:
        received = [o for o in plan.purchase_orders if o.supplier_code == code and o.received_date]
        return sum(o.received_date > o.expected_date for o in received) / len(received)

    assert open_orders and overdue
    # SUP04 is simulated as often late, SUP01 as reliable.
    assert late_share("SYN-SUP04") > 0.6 > 0.2 > late_share("SYN-SUP01")


def test_as_of_date_only_shifts_the_order_dates() -> None:
    earlier = build_plan(as_of=date(2026, 1, 1))
    later = build_plan(as_of=date(2026, 1, 11))

    assert earlier.products == later.products
    for a, b in zip(earlier.purchase_orders, later.purchase_orders, strict=True):
        assert b.ordered_date - a.ordered_date == timedelta(days=10)
        assert (a.lines, a.supplier_code) == (b.lines, b.supplier_code)


@needs_db
def test_load_writes_suppliers_and_orders_without_extra_stock_movements(
    db_session: Session,
) -> None:
    plan = build_plan(n_products=100, n_warehouses=3)

    summary = load_plan(db_session, plan)
    db_session.commit()

    def count(model) -> int:
        return db_session.execute(select(func.count()).select_from(model)).scalar_one()

    assert count(Supplier) == summary["suppliers"] == 6
    assert count(PurchaseOrder) == summary["purchase_orders"] == len(plan.purchase_orders)
    assert count(PurchaseOrderLine) == sum(len(order.lines) for order in plan.purchase_orders)
    assert summary["open_purchase_orders"] == sum(
        o.received_date is None for o in plan.purchase_orders
    )
    # Orders are documents: the only stock movements are the opening ones.
    assert count(InventoryMovement) == len(plan.opening_stock)
    linked = db_session.execute(
        select(func.count()).select_from(Product).where(Product.supplier_id.is_not(None))
    ).scalar_one()
    assert linked == 100
    event = db_session.execute(select(AuditEvent)).scalar_one()
    assert event.details["as_of"] == plan.as_of.isoformat()
