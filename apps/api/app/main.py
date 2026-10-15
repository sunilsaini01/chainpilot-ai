"""FastAPI application entry point. Run with: uvicorn app.main:app"""

import logging

from fastapi import FastAPI

from app.config import get_settings
from app.routes import health


def create_app() -> FastAPI:
    """Build the FastAPI app. A function (not just a global) makes tests easy to isolate."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.include_router(health.router)
    return app


app = create_app()
