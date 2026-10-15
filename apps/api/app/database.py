"""Database engine setup and a simple connectivity check."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine, text

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Create the SQLAlchemy engine lazily.

    Creating it on first use (not at import time) means the API can start and
    serve /health even when Postgres is not running yet.
    """
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,  # drop dead connections after a Postgres restart
        connect_args={"connect_timeout": settings.database_connect_timeout},
    )


def check_database(engine: Engine) -> None:
    """Run ``SELECT 1``. Raises a SQLAlchemy error if the database is unreachable."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
