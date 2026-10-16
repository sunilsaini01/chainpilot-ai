"""Shared fixtures for PostgreSQL integration tests.

Database tests run only when RUN_DB_TESTS=1. They never touch your development
data: each test run creates its own throwaway database (named
<POSTGRES_DB>_pytest_<random>), migrates it, and drops it at the end.
"""

import os
import uuid
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import security
from app.config import Settings
from app.dependencies import get_db_session
from app.main import app
from app.models import (
    Base,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    Supplier,
    User,
    Warehouse,
)
from app.users_service import create_user

API_DIR = Path(__file__).resolve().parent.parent


def alembic_config(connection) -> Config:
    """Alembic config that migrates over an existing connection (see migrations/env.py)."""
    config = Config(str(API_DIR / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[URL]:
    if os.getenv("RUN_DB_TESTS") != "1":
        pytest.skip("set RUN_DB_TESTS=1 with Postgres running")

    settings = Settings()
    test_db_name = f"{settings.postgres_db}_pytest_{uuid.uuid4().hex[:8]}"
    # CREATE/DROP DATABASE cannot run inside a transaction, hence AUTOCOMMIT.
    admin_engine = create_engine(
        settings.database_url,
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": settings.database_connect_timeout},
    )
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{test_db_name}"'))
    except OperationalError as error:
        # Stop the whole run with one clear message instead of erroring every test.
        pytest.exit(
            f"RUN_DB_TESTS=1 but PostgreSQL at {settings.postgres_host}:{settings.postgres_port} "
            f"is not reachable ({type(error).__name__}). Start it, e.g. `docker compose up -d "
            "postgres`, or unset RUN_DB_TESTS.",
            returncode=1,
        )
    try:
        yield settings.database_url.set(database=test_db_name)
    finally:
        with admin_engine.connect() as connection:
            # FORCE closes any connections a failed test may have left open.
            connection.execute(text(f'DROP DATABASE IF EXISTS "{test_db_name}" WITH (FORCE)'))
        admin_engine.dispose()


@pytest.fixture(scope="session")
def db_engine(test_database_url: URL) -> Iterator[Engine]:
    """Engine for the throwaway database, migrated to the latest revision."""
    engine = create_engine(test_database_url, connect_args={"connect_timeout": 5})
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session for one test. All tables are emptied afterwards so tests stay independent."""
    session = Session(db_engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        with db_engine.begin() as connection:
            connection.execute(
                text(
                    # Every table in the models, so new tables are cleaned automatically.
                    f"TRUNCATE {', '.join(Base.metadata.tables)} RESTART IDENTITY CASCADE"
                )
            )


@pytest.fixture
def product(db_session: Session) -> Product:
    item = Product(
        sku="SKU-001",
        name="Test Widget",
        category="hardware",
        unit_cost=Decimal("2.50"),
        unit_price=Decimal("4.99"),
    )
    db_session.add(item)
    db_session.commit()
    return item


@pytest.fixture
def warehouse(db_session: Session) -> Warehouse:
    site = Warehouse(code="WH-TEST", name="Test Warehouse", city="Testville", capacity_units=1000)
    db_session.add(site)
    db_session.commit()
    return site


# Long enough to pass the password policy; only used in tests.
TEST_PASSWORD = "correct-horse-battery"


@pytest.fixture
def api_client(db_engine: Engine, db_session: Session) -> Iterator[TestClient]:
    """Test client whose requests use the throwaway test database."""

    def test_db_session() -> Iterator[Session]:
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = test_db_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Callable[..., User]:
    """Factory: make_user(Role.ADMIN) creates and commits a user with TEST_PASSWORD.

    Test users get a cheap scrypt cost (N=2^10, p=1) so the suite stays fast. Each
    hash stores its own parameters, so logging in works exactly as in production;
    users created through the API and tests/test_security.py use the real cost.
    """

    def _make_user(role: Role = Role.ANALYST, email: str | None = None) -> User:
        with monkeypatch.context() as patch:
            patch.setattr(security, "SCRYPT_N", 2**10)
            patch.setattr(security, "SCRYPT_P", 1)
            user = create_user(
                db_session,
                email=email or f"{role.value}@example.com",
                full_name=f"Test {role.value.title()}",
                role=role,
                password=TEST_PASSWORD,
            )
        db_session.commit()
        return user

    return _make_user


def login(client: TestClient, email: str, password: str = TEST_PASSWORD) -> dict[str, str]:
    """Log in through the API and return the Authorization header to use."""
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# --- Suppliers and purchase orders (copilot tests) ---------------------------------

# The "today" of the hand-made order history below.
TODAY = date(2026, 10, 17)


def add_order(
    session: Session,
    number: str,
    supplier: Supplier,
    site: Warehouse,
    product: Product,
    ordered: date,
    expected: date,
    received: date | None,
) -> None:
    session.add(
        PurchaseOrder(
            po_number=number,
            supplier_id=supplier.id,
            warehouse_id=site.id,
            status="received" if received else "open",
            ordered_date=ordered,
            expected_date=expected,
            received_date=received,
            lines=[PurchaseOrderLine(product_id=product.id, quantity=10, unit_cost=Decimal(5))],
        )
    )


@pytest.fixture
def world(db_session: Session) -> dict:
    """Four suppliers with hand-made histories, one site, one product; dates near TODAY."""
    suppliers = {
        code: Supplier(
            code=code,
            name=f"Supplier {code[-1]}",
            country="X",
            lead_time_days=7,
            lead_time_std_days=Decimal("1.00"),
        )
        for code in ["SYN-SUP01", "SYN-SUP02", "SYN-SUP03", "SYN-SUP04"]
    }
    site = Warehouse(code="SYN-WH1", name="Site", city="C", capacity_units=10_000)
    db_session.add_all([*suppliers.values(), site])
    db_session.flush()
    rug = Product(
        sku="SYN-0001",
        name="Classic Rug",
        category="kitchen",
        unit_cost=Decimal(5),
        unit_price=Decimal(9),
        supplier_id=suppliers["SYN-SUP01"].id,
    )
    db_session.add(rug)
    db_session.flush()

    number = 0

    def history(code: str, on_time: int, late: int, days_late: int = 3) -> None:
        nonlocal number
        for index in range(on_time + late):
            number += 1
            ordered = TODAY - timedelta(days=60 - index)
            expected = ordered + timedelta(days=7)
            arrived = expected + timedelta(days=days_late if index >= on_time else 0)
            if code == "SYN-SUP01" and index == 0:
                arrived = expected - timedelta(days=2)  # early: on time, 0 days late (not -2)
            add_order(
                db_session,
                f"SYN-PO-{number:06d}",
                suppliers[code],
                site,
                rug,
                ordered,
                expected,
                arrived,
            )

    history("SYN-SUP01", on_time=9, late=1)  # 90% -> good, 0.3 days late on average
    history("SYN-SUP02", on_time=4, late=0)  # 4 orders -> not rated
    history("SYN-SUP03", on_time=6, late=2)  # 75% -> watch
    history("SYN-SUP04", on_time=3, late=2, days_late=10)  # 60% -> at risk
    old = TODAY - timedelta(days=120)  # outside the 90-day window: ignored
    add_order(
        db_session,
        "SYN-PO-000900",
        suppliers["SYN-SUP01"],
        site,
        rug,
        old,
        old + timedelta(7),
        old + timedelta(10),  # received 110 days ago
    )
    add_order(
        db_session,
        "SYN-PO-000901",
        suppliers["SYN-SUP04"],
        site,
        rug,
        TODAY - timedelta(10),
        TODAY - timedelta(3),
        None,
    )  # overdue
    add_order(
        db_session,
        "SYN-PO-000902",
        suppliers["SYN-SUP04"],
        site,
        rug,
        TODAY - timedelta(2),
        TODAY + timedelta(5),
        None,
    )  # not yet due
    db_session.commit()
    return {"suppliers": suppliers, "site": site, "rug": rug}
