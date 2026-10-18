"""The cached risk assessment (P9-T1-R1): same answers, fewer recalculations (RUN_DB_TESTS=1)."""

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app import replenishment_service
from app.inventory_service import record_movement
from app.models import MovementReason, PurchaseOrder, PurchaseOrderLine
from app.purchasing_service import receive_purchase_order
from app.replenishment_service import assess_all, link_demand_profiles
from tests.test_replenishment import scenario  # noqa: F401  (the shared fixture)


@pytest.fixture
def loads(db_session: Session, scenario: dict, monkeypatch: pytest.MonkeyPatch) -> list[int]:  # noqa: F811
    """Linked demo data, and a counter of real recalculations (calls of load_inputs)."""
    link_demand_profiles(db_session)
    db_session.commit()
    calls: list[int] = []
    original = replenishment_service.load_inputs

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(replenishment_service, "load_inputs", counting)
    return calls


def rows(assessments) -> list[dict]:
    return [a.as_dict() for a in assessments]


def test_a_repeated_call_is_served_from_the_cache_with_the_same_answer(
    db_session: Session, loads: list[int]
) -> None:
    _, first, first_unassessed = assess_all(db_session, 0.95)
    _, second, second_unassessed = assess_all(db_session, 0.95)

    assert rows(second) == rows(first) and second_unassessed == first_unassessed
    assert len(loads) == 1
    replenishment_service.clear_assessment_cache()
    _, fresh, _ = assess_all(db_session, 0.95)
    assert rows(fresh) == rows(first)  # the cache changes nothing about the answer
    assert len(loads) == 2


def test_callers_get_their_own_list(db_session: Session, loads: list[int]) -> None:
    for _ in range(3):  # the first call fills the cache, the next ones are served from it
        _, assessments, _ = assess_all(db_session, 0.95)
        assert assessments  # not emptied by an earlier caller
        assessments.clear()


def test_a_stock_movement_makes_it_recalculate(
    db_session: Session,
    scenario: dict,  # noqa: F811
    loads: list[int],
) -> None:
    _, before, _ = assess_all(db_session, 0.95)
    record_movement(
        db_session, scenario["rug"].id, scenario["sites"][0].id, 40, MovementReason.RECEIPT
    )
    db_session.commit()

    _, after, _ = assess_all(db_session, 0.95)

    assert len(loads) == 2
    assert rows(after) != rows(before)


def test_receiving_an_order_makes_it_recalculate(db_session: Session, loads: list[int]) -> None:
    assess_all(db_session, 0.95)
    order = db_session.query(PurchaseOrder).filter_by(po_number="PO-OPEN").one()
    receive_purchase_order(db_session, order.id, date(2026, 10, 18), None)
    db_session.commit()

    assess_all(db_session, 0.95)
    assert len(loads) == 2


def test_a_new_open_order_makes_it_recalculate(
    db_session: Session,
    scenario: dict,  # noqa: F811
    loads: list[int],
) -> None:
    """No stock moves (as when an approved reorder places an order): only the open
    orders change, and with them the stock on order."""
    assess_all(db_session, 0.95)
    db_session.add(
        PurchaseOrder(
            po_number="PO-NEW",
            supplier_id=scenario["rug"].supplier_id,
            warehouse_id=scenario["sites"][0].id,
            status="open",
            ordered_date=date(2026, 10, 18),
            expected_date=date(2026, 10, 25),
            lines=[PurchaseOrderLine(product_id=scenario["rug"].id, quantity=10, unit_cost=5)],
        )
    )
    db_session.commit()

    _, after, _ = assess_all(db_session, 0.95)
    assert len(loads) == 2
    rug_at_wh1 = next(
        a
        for a in after
        if a.inputs.product_id == scenario["rug"].id
        and a.inputs.warehouse_id == scenario["sites"][0].id
    )
    assert rug_at_wh1.inputs.on_order == 10


def test_a_product_edit_makes_it_recalculate(
    db_session: Session,
    scenario: dict,  # noqa: F811
    loads: list[int],
) -> None:
    assess_all(db_session, 0.95)
    scenario["kite"].min_order_qty = 24
    db_session.commit()

    assess_all(db_session, 0.95)
    assert len(loads) == 2


def test_another_service_level_is_its_own_entry(db_session: Session, loads: list[int]) -> None:
    assess_all(db_session, 0.95)
    assess_all(db_session, 0.99)
    assess_all(db_session, 0.95)
    assert len(loads) == 2


def test_entries_expire_after_a_minute(
    db_session: Session, loads: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(replenishment_service.time, "monotonic", lambda: clock[0])
    assess_all(db_session, 0.95)
    clock[0] += replenishment_service.CACHE_SECONDS - 1
    assess_all(db_session, 0.95)
    assert len(loads) == 1
    clock[0] += 2
    assess_all(db_session, 0.95)
    assert len(loads) == 2
