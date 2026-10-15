"""Migration tests: run against a throwaway PostgreSQL database (RUN_DB_TESTS=1)."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect

from app.models import Base
from tests.conftest import alembic_config

CORE_TABLES = {"products", "warehouses", "inventory", "inventory_movements"}


def table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def test_migrations_create_all_core_tables(db_engine: Engine) -> None:
    assert CORE_TABLES <= table_names(db_engine)


def test_models_and_migrations_are_in_sync(db_engine: Engine) -> None:
    # If someone edits app/models.py without writing a migration, this lists the differences.
    with db_engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert differences == []


def test_downgrade_then_upgrade_round_trip(db_engine: Engine) -> None:
    with db_engine.begin() as connection:
        command.downgrade(alembic_config(connection), "base")
    assert table_names(db_engine) == set()

    with db_engine.begin() as connection:
        command.upgrade(alembic_config(connection), "head")
    assert CORE_TABLES <= table_names(db_engine)
