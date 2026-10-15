"""Alembic environment: connects to PostgreSQL and runs migrations.

Run from apps/api:  alembic upgrade head
"""

from alembic import context

from app.config import get_settings
from app.database import build_engine
from app.logging_config import configure_logging
from app.models import Base

# Used by `alembic revision --autogenerate` to compare models with the database.
target_metadata = Base.metadata


def run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


# Tests pass in their own connection (to a throwaway test database).
# Otherwise (command line or the Docker `migrate` service) use the app settings,
# which builds the URL safely from separate POSTGRES_* variables.
existing_connection = context.config.attributes.get("connection")
if existing_connection is not None:
    run_migrations(existing_connection)
else:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    engine = build_engine(settings)
    with engine.connect() as connection:
        run_migrations(connection)
    engine.dispose()
