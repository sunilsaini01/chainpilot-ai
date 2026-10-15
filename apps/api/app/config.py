"""Application settings loaded from environment variables (or a local .env file)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """All runtime configuration for the API.

    Database connection details are kept as separate fields instead of one
    DATABASE_URL string. A password such as ``p@ss:w/rd#1`` would corrupt a
    hand-built URL; ``URL.create`` escapes each part safely instead.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ChainPilot AI API"
    environment: str = "local"
    # Validated here so a typo fails with a clear settings error instead of
    # crashing inside logging setup.
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_user: str = "chainpilot"
    # SecretStr keeps the password out of logs and reprs.
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "chainpilot"

    # Seconds to wait for Postgres before /ready reports the database as down.
    database_connect_timeout: int = Field(default=3, ge=1, le=60)

    @property
    def database_url(self) -> URL:
        """Build the SQLAlchemy URL from the separate connection fields."""
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value() or None,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    """Return one cached Settings object so the environment is read only once."""
    return Settings()
