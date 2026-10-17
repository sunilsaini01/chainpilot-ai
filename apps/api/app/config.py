"""Application settings loaded from environment variables (or a local .env file)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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
    # "json" for containers and cloud log search; "text" is easier to read locally.
    log_format: Literal["json", "text"] = "json"

    # 127.0.0.1 rather than "localhost": on Windows "localhost" tries IPv6 (::1)
    # first, but Docker publishes Postgres on IPv4 only, so connections stall.
    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_user: str = "chainpilot"
    # SecretStr keeps the password out of logs and reprs.
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "chainpilot"

    # Seconds to wait for Postgres before /ready reports the database as down.
    database_connect_timeout: int = Field(default=3, ge=1, le=60)

    # How long a login token stays valid (default 8 hours = one working day; max 7 days).
    access_token_ttl_minutes: int = Field(default=480, ge=5, le=7 * 24 * 60)
    # The browser's login cookie is sent only over HTTPS when Secure is set. Default:
    # Secure everywhere except ENVIRONMENT=local (plain http://127.0.0.1).
    session_cookie_secure: bool | None = None

    # AI copilot (P5-T3): Groq or Google Gemini (decision D-052). Only the chosen
    # provider's key and model are needed; without them the copilot answers 503.
    llm_provider: Literal["groq", "gemini"] = "groq"
    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = ""
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = ""
    # Browser origins allowed to call the API (the web app, P6), comma-separated.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Cost control: investigations each user may start per hour.
    copilot_runs_per_hour: int = Field(default=20, ge=1, le=1000)

    @field_validator("cors_origins")
    @classmethod
    def no_wildcard_origin(cls, value: str) -> str:
        # The API allows credentials (the login cookie), so "*" would let any site
        # make logged-in requests. Origins must be listed one by one.
        if "*" in value:
            raise ValueError("CORS_ORIGINS must list origins explicitly; '*' is not allowed")
        return value

    @property
    def cookie_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.environment != "local"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

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
