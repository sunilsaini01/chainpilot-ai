"""Shared fixtures for PostgreSQL integration tests.

Database tests run only when RUN_DB_TESTS=1. They never touch your development
data: each test run creates its own throwaway database (named
<POSTGRES_DB>_pytest_<random>), migrates it, and drops it at the end.
"""

import os
import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.config import Settings
from app.dependencies import get_db_session
from app.main import app
from app.models import Base, Product, Role, User, Warehouse
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
    admin_engine = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{test_db_name}"'))
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
def make_user(db_session: Session) -> Callable[..., User]:
    """Factory: make_user(Role.ADMIN) creates and commits a user with TEST_PASSWORD."""

    def _make_user(role: Role = Role.ANALYST, email: str | None = None) -> User:
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
