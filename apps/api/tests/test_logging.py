"""Unit tests for structured (JSON) logging."""

import json
import logging
import sys
from collections.abc import Iterator

import pytest

from app.logging_config import UVICORN_LOGGERS, JsonFormatter, configure_logging


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    """Undo logging changes so these tests don't affect other tests."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    yield
    root.handlers, root.level = saved_handlers, saved_level


def make_record(message: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord("app.test", logging.WARNING, __file__, 1, message, args, None)


def test_json_formatter_outputs_one_parsable_line() -> None:
    line = JsonFormatter().format(make_record("Disk %s at %d%%", "data", 91))

    entry = json.loads(line)
    assert "\n" not in line
    assert entry["level"] == "WARNING"
    assert entry["logger"] == "app.test"
    assert entry["message"] == "Disk data at 91%"
    assert entry["timestamp"].endswith("+00:00")  # always UTC


def test_json_formatter_includes_exception_traceback() -> None:
    try:
        raise ValueError("bad input")
    except ValueError:
        record = logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )

    entry = json.loads(JsonFormatter().format(record))

    assert "ValueError: bad input" in entry["exception"]


def test_configure_logging_routes_uvicorn_logs_through_root() -> None:
    configure_logging("INFO", "json")

    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
    for name in UVICORN_LOGGERS:
        assert logging.getLogger(name).handlers == []
        assert logging.getLogger(name).propagate is True


def test_configure_logging_twice_does_not_duplicate_handlers() -> None:
    configure_logging("INFO", "text")
    configure_logging("DEBUG", "text")

    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG
    assert not isinstance(root.handlers[0].formatter, JsonFormatter)
