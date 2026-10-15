"""Creating and changing products and warehouses (master data).

Functions never commit; API routes commit together with the audit event.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Product, Warehouse


class DuplicateCodeError(Exception):
    """Raised when a SKU or warehouse code is already taken."""


def _json_safe(value: Any) -> Any:
    # Audit details are stored as JSON, which has no Decimal type; "4.99" keeps it exact.
    return str(value) if isinstance(value, Decimal) else value


def apply_changes(entity: Product | Warehouse, updates: dict[str, Any]) -> dict[str, list]:
    """Set the given attributes and return {field: [old, new]} for those that really changed."""
    changes: dict[str, list] = {}
    for field, new_value in updates.items():
        old_value = getattr(entity, field)
        if old_value != new_value:
            changes[field] = [_json_safe(old_value), _json_safe(new_value)]
            setattr(entity, field, new_value)
    return changes


def _add_unique(session: Session, entity: Product | Warehouse, label: str) -> None:
    """Insert inside a savepoint so a duplicate code only undoes this insert."""
    try:
        with session.begin_nested():
            session.add(entity)
    except IntegrityError as error:
        raise DuplicateCodeError(f"{label} already exists") from error


def create_product(
    session: Session, sku: str, name: str, category: str, unit_cost: Decimal, unit_price: Decimal
) -> Product:
    product = Product(
        sku=sku, name=name, category=category, unit_cost=unit_cost, unit_price=unit_price
    )
    _add_unique(session, product, f"A product with SKU {sku}")
    return product


def create_warehouse(
    session: Session, code: str, name: str, city: str, capacity_units: int
) -> Warehouse:
    warehouse = Warehouse(code=code, name=name, city=city, capacity_units=capacity_units)
    _add_unique(session, warehouse, f"A warehouse with code {code}")
    return warehouse
