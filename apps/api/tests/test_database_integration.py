"""Integration test against a real PostgreSQL server.

Skipped unless RUN_DB_TESTS=1, because it needs Postgres running
(for example via `docker compose up -d postgres`).
"""

import os

import pytest
from sqlalchemy import text

from app.config import Settings
from app.database import build_engine, check_database

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="set RUN_DB_TESTS=1 with Postgres running"
)


def test_can_query_real_postgres() -> None:
    # Same engine settings as the app (including the connect timeout).
    engine = build_engine(Settings())

    check_database(engine)  # raises if the connection fails

    with engine.connect() as connection:
        version = connection.execute(text("SHOW server_version")).scalar_one()
    assert version.startswith("16")
    engine.dispose()
