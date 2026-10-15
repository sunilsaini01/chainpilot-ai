"""Logging setup: one JSON object per line, so CloudWatch and similar tools can search fields."""

import json
import logging
from datetime import UTC, datetime
from typing import Literal

# Uvicorn installs its own text handlers on these loggers. We remove them and let
# records flow to the root logger so request logs use the same format as ours.
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class JsonFormatter(logging.Formatter):
    """Format a log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        # default=str keeps logging from crashing on values json cannot encode.
        return json.dumps(entry, default=str)


def configure_logging(level: str, log_format: Literal["json", "text"]) -> None:
    """Send all logs (ours and uvicorn's) to stdout in the chosen format."""
    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(TEXT_FORMAT))

    root = logging.getLogger()
    root.handlers = [handler]  # replace, so repeated calls don't duplicate lines
    root.setLevel(level)

    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
