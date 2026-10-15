"""Product and warehouse API tests (RUN_DB_TESTS=1)."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Role, User
from tests.conftest import login

NEW_PRODUCT = {
    "sku": " sku-100 ",
    "name": "Blue Widget",
    "category": "widgets",
    "unit_cost": "2.50",
    "unit_price": "4.99",
}
NEW_WAREHOUSE = {"code": "wh-north", "name": "North DC", "city": "Leeds", "capacity_units": 5000}


@pytest.fixture
def admin_headers(api_client: TestClient, make_user: Callable[..., User]) -> dict[str, str]:
    make_user(Role.ADMIN)
    return login(api_client, "admin@example.com")


@pytest.fixture
def analyst_headers(api_client: TestClient, make_user: Callable[..., User]) -> dict[str, str]:
    make_user(Role.ANALYST)
    return login(api_client, "analyst@example.com")


def test_admin_creates_product_with_normalized_sku_and_exact_prices(
    api_client: TestClient, db_session: Session, admin_headers: dict[str, str]
) -> None:
    response = api_client.post("/products", json=NEW_PRODUCT, headers=admin_headers)

    assert response.status_code == 201
    body = response.json()
    assert body["sku"] == "SKU-100"
    assert body["unit_price"] == "4.99"  # Decimal, sent as an exact string
    event = db_session.execute(select(AuditEvent)).scalars().all()[-1]
    assert (event.action, event.details) == ("product.created", {"sku": "SKU-100"})


def test_duplicate_sku_in_any_case_is_409(
    api_client: TestClient, admin_headers: dict[str, str]
) -> None:
    api_client.post("/products", json=NEW_PRODUCT, headers=admin_headers)

    response = api_client.post(
        "/products", json={**NEW_PRODUCT, "sku": "SKU-100"}, headers=admin_headers
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sku", "bad sku!"),
        ("sku", ""),
        ("unit_cost", "-1.00"),
        ("unit_price", "1.999"),  # more than 2 decimal places
        ("name", ""),
    ],
)
def test_invalid_product_is_422(
    api_client: TestClient, admin_headers: dict[str, str], field: str, value: str
) -> None:
    response = api_client.post(
        "/products", json={**NEW_PRODUCT, field: value}, headers=admin_headers
    )

    assert response.status_code == 422


def test_analyst_can_read_but_not_create_products(
    api_client: TestClient, admin_headers: dict[str, str], analyst_headers: dict[str, str]
) -> None:
    created = api_client.post("/products", json=NEW_PRODUCT, headers=admin_headers).json()

    assert api_client.get("/products", headers=analyst_headers).status_code == 200
    assert api_client.get(f"/products/{created['id']}", headers=analyst_headers).status_code == 200
    assert (
        api_client.post("/products", json=NEW_PRODUCT, headers=analyst_headers).status_code == 403
    )
    patch = api_client.patch(
        f"/products/{created['id']}", json={"name": "x"}, headers=analyst_headers
    )
    assert patch.status_code == 403


def test_reading_products_requires_login(api_client: TestClient) -> None:
    assert api_client.get("/products").status_code == 401


def test_product_search_and_filters(api_client: TestClient, admin_headers: dict[str, str]) -> None:
    for sku, name, category in [
        ("A-1", "Red Mug", "kitchen"),
        ("A-2", "Blue Mug", "kitchen"),
        ("B-1", "Desk Lamp", "office"),
    ]:
        api_client.post(
            "/products",
            json={**NEW_PRODUCT, "sku": sku, "name": name, "category": category},
            headers=admin_headers,
        )
    lamp_id = api_client.get("/products", params={"search": "lamp"}, headers=admin_headers).json()[
        0
    ]["id"]
    api_client.patch(f"/products/{lamp_id}", json={"is_active": False}, headers=admin_headers)

    def skus(**params: str) -> list[str]:
        response = api_client.get("/products", params=params, headers=admin_headers)
        return [product["sku"] for product in response.json()]

    assert skus(search="mug") == ["A-1", "A-2"]
    assert skus(category="office") == ["B-1"]
    assert skus(is_active="false") == ["B-1"]
    assert skus(limit="1", offset="1") == ["A-2"]


def test_patch_product_changes_only_sent_fields_and_audits_them(
    api_client: TestClient, db_session: Session, admin_headers: dict[str, str]
) -> None:
    product = api_client.post("/products", json=NEW_PRODUCT, headers=admin_headers).json()

    response = api_client.patch(
        f"/products/{product['id']}", json={"unit_price": "5.49"}, headers=admin_headers
    )

    assert response.status_code == 200
    assert response.json()["unit_price"] == "5.49"
    assert response.json()["name"] == "Blue Widget"  # untouched
    event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "product.updated")
    ).scalar_one()
    assert event.details == {"changes": {"unit_price": ["4.99", "5.49"]}}


@pytest.mark.parametrize("body", [{"name": None}, {"sku": "NEW-SKU"}])
def test_patch_product_rejects_nulls_and_ignores_sku(
    api_client: TestClient, admin_headers: dict[str, str], body: dict
) -> None:
    product = api_client.post("/products", json=NEW_PRODUCT, headers=admin_headers).json()

    response = api_client.patch(f"/products/{product['id']}", json=body, headers=admin_headers)

    if "name" in body:
        assert response.status_code == 422
    else:
        # Unknown fields are ignored, so the SKU stays as it was.
        assert response.status_code == 200
        assert response.json()["sku"] == "SKU-100"


def test_missing_product_and_warehouse_are_404(
    api_client: TestClient, admin_headers: dict[str, str]
) -> None:
    assert api_client.get("/products/999999", headers=admin_headers).status_code == 404
    assert api_client.get("/warehouses/999999", headers=admin_headers).status_code == 404
    assert (
        api_client.patch("/products/999999", json={"name": "x"}, headers=admin_headers).status_code
        == 404
    )


def test_admin_creates_and_updates_warehouse(
    api_client: TestClient, db_session: Session, admin_headers: dict[str, str]
) -> None:
    created = api_client.post("/warehouses", json=NEW_WAREHOUSE, headers=admin_headers)

    assert created.status_code == 201
    assert created.json()["code"] == "WH-NORTH"
    warehouse_id = created.json()["id"]

    updated = api_client.patch(
        f"/warehouses/{warehouse_id}", json={"capacity_units": 6000}, headers=admin_headers
    )

    assert updated.status_code == 200
    assert updated.json()["capacity_units"] == 6000
    actions = db_session.execute(select(AuditEvent.action).order_by(AuditEvent.id)).scalars().all()
    assert actions[-2:] == ["warehouse.created", "warehouse.updated"]


@pytest.mark.parametrize(
    ("body", "expected_status"),
    [
        ({**NEW_WAREHOUSE, "capacity_units": 0}, 422),
        ({**NEW_WAREHOUSE, "code": "WH NORTH"}, 422),
        (NEW_WAREHOUSE, 409),  # created once in the test, so the second time is a duplicate
    ],
)
def test_warehouse_validation(
    api_client: TestClient, admin_headers: dict[str, str], body: dict, expected_status: int
) -> None:
    api_client.post("/warehouses", json=NEW_WAREHOUSE, headers=admin_headers)

    assert api_client.post("/warehouses", json=body, headers=admin_headers).status_code == (
        expected_status
    )


def test_analyst_can_list_but_not_create_warehouses(
    api_client: TestClient, analyst_headers: dict[str, str]
) -> None:
    assert api_client.get("/warehouses", headers=analyst_headers).status_code == 200
    response = api_client.post("/warehouses", json=NEW_WAREHOUSE, headers=analyst_headers)
    assert response.status_code == 403


def test_search_treats_percent_and_underscore_literally(
    api_client: TestClient, admin_headers: dict[str, str]
) -> None:
    for sku, name in [("P-1", "100% Cotton Tee"), ("P-2", "Plain Tee"), ("P-3", "Mug_Large")]:
        api_client.post(
            "/products", json={**NEW_PRODUCT, "sku": sku, "name": name}, headers=admin_headers
        )

    def names(search: str) -> list[str]:
        response = api_client.get("/products", params={"search": search}, headers=admin_headers)
        return [product["name"] for product in response.json()]

    assert names("100%") == ["100% Cotton Tee"]
    assert names("%") == ["100% Cotton Tee"]  # not "everything"
    assert names("p_a") == []  # as a wildcard "_" would match "Pla" in "Plain Tee"
    assert names("mug_") == ["Mug_Large"]
