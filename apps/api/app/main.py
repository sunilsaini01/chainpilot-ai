"""FastAPI application entry point. Run with: uvicorn app.main:app"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.logging_config import configure_logging
from app.routes import (
    agents,
    approvals,
    audit,
    auth,
    dashboard,
    delivery_risk,
    forecasts,
    health,
    inventory,
    policies,
    products,
    purchasing,
    replenishment,
    users,
    warehouses,
)


def create_app() -> FastAPI:
    """Build the FastAPI app. A function (not just a global) makes tests easy to isolate."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    app = FastAPI(title=settings.app_name, version="0.1.0")
    # The web app (P6) runs on another origin. Only the listed origins may call the
    # API from a browser, and the paging/label headers are made readable to them.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        # The dashboard's login cookie goes with its requests. Safe only because the
        # origins are an explicit list (never "*") and changes need the CSRF token.
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-CSRF-Token"],
        expose_headers=["X-Total-Count", "X-Dataset", "X-Unassessed-Count", "Retry-After"],
    )
    app.include_router(health.router)
    app.include_router(dashboard.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(products.router)
    app.include_router(warehouses.router)
    app.include_router(inventory.router)
    app.include_router(purchasing.router)
    app.include_router(replenishment.router)
    app.include_router(approvals.router)
    app.include_router(policies.router)
    app.include_router(agents.router)
    app.include_router(forecasts.router)
    app.include_router(delivery_risk.router)
    app.include_router(audit.router)
    return app


app = create_app()
