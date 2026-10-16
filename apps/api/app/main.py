"""FastAPI application entry point. Run with: uvicorn app.main:app"""

from fastapi import FastAPI

from app.config import get_settings
from app.logging_config import configure_logging
from app.routes import audit, auth, forecasts, health, inventory, products, users, warehouses


def create_app() -> FastAPI:
    """Build the FastAPI app. A function (not just a global) makes tests easy to isolate."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(products.router)
    app.include_router(warehouses.router)
    app.include_router(inventory.router)
    app.include_router(forecasts.router)
    app.include_router(audit.router)
    return app


app = create_app()
