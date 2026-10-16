"""Import a forecast file produced by the ML pipeline (ml/demand_forecasting/publish.py).

The folder holds forecasts.csv and manifest.json. Everything is checked before
anything is written, and the run and all its rows are inserted in one
transaction, so a failed import leaves nothing behind. The same file (same
run_key) cannot be imported twice.

DATA LABEL: M5 public-dataset forecasts, kept apart from the simulated SYN- products.
"""

import csv
import math
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.files import ImportFileError, check_text, read_manifest, sha256_of, text_limits
from app.models import Forecast, ForecastRun

CSV_COLUMNS = [
    "series_id",
    "item_id",
    "dept_id",
    "cat_id",
    "store_id",
    "forecast_date",
    "step",
    "forecast",
    "lower",
    "upper",
]
MANIFEST_FIELDS = [
    "run_key",
    "dataset",
    "model",
    "trained_through",
    "forecast_start",
    "forecast_end",
    "horizon_days",
    "series",
    "rows",
    "csv_sha256",
]
MAX_HORIZON_DAYS = 28  # matches the step_range check on the forecasts table
RUN_TEXT = text_limits(ForecastRun.__table__, ["run_key", "name", "dataset", "model"])
ROW_TEXT = text_limits(
    Forecast.__table__, ["series_id", "item_id", "dept_id", "cat_id", "store_id"]
)


class ForecastImportError(ImportFileError):
    """The forecast folder is missing, inconsistent, or already imported."""


def _parse_row(row: dict, line: int, start: date, horizon: int) -> tuple:
    """Check one CSV row and return it as values in CSV_COLUMNS order."""
    check_text(row, ROW_TEXT, f"line {line}", ForecastImportError)
    try:
        step = int(row["step"])
        day = date.fromisoformat(row["forecast_date"])
        forecast, lower, upper = (float(row[name]) for name in ("forecast", "lower", "upper"))
    except (ValueError, TypeError) as error:
        raise ForecastImportError(f"line {line}: unreadable value ({error})") from error
    if not all(math.isfinite(value) for value in (forecast, lower, upper)):
        raise ForecastImportError(f"line {line}: forecast values must be finite numbers")
    if not 0 <= lower <= forecast <= upper:
        raise ForecastImportError(f"line {line}: need 0 <= lower <= forecast <= upper")
    if not 1 <= step <= horizon or day != start + timedelta(days=step - 1):
        raise ForecastImportError(f"line {line}: step {step} does not match date {day}")
    return (
        row["series_id"],
        row["item_id"],
        row["dept_id"],
        row["cat_id"],
        row["store_id"],
        day,
        step,
        forecast,
        lower,
        upper,
    )


def _read_rows(csv_path: Path, start: date, horizon: int) -> list[tuple]:
    rows, seen = [], set()
    with open(csv_path, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != CSV_COLUMNS:
            raise ForecastImportError(f"unexpected CSV header {reader.fieldnames}")
        for line, row in enumerate(reader, start=2):
            values = _parse_row(row, line, start, horizon)
            # One forecast per series and day: caught here with a line number,
            # not by the database's unique constraint in the middle of COPY.
            key = (values[0], values[5])
            if key in seen:
                raise ForecastImportError(f"line {line}: {key[0]} on {key[1]} appears twice")
            seen.add(key)
            rows.append(values)
    return rows


def import_forecasts(session: Session, folder: Path) -> ForecastRun:
    """Validate and load one forecast folder. Does not commit; the caller does."""
    manifest = read_manifest(folder, MANIFEST_FIELDS, ForecastImportError)
    check_text({**manifest, "name": folder.name}, RUN_TEXT, "manifest.json", ForecastImportError)
    try:
        trained_through = date.fromisoformat(manifest["trained_through"])
        start = date.fromisoformat(manifest["forecast_start"])
        end = date.fromisoformat(manifest["forecast_end"])
        horizon = int(manifest["horizon_days"])
        series_count = int(manifest["series"])
        expected_rows = int(manifest["rows"])
    except (ValueError, TypeError) as error:
        raise ForecastImportError(f"manifest.json: unreadable value ({error})") from error
    if not 1 <= horizon <= MAX_HORIZON_DAYS:
        raise ForecastImportError(f"manifest.json: horizon_days must be 1 to {MAX_HORIZON_DAYS}")
    csv_path = folder / "forecasts.csv"
    if not csv_path.is_file():
        raise ForecastImportError(f"{folder} has no forecasts.csv")
    if sha256_of(csv_path) != manifest["csv_sha256"]:
        raise ForecastImportError("forecasts.csv does not match the checksum in manifest.json")
    existing = session.execute(
        select(ForecastRun.id).where(ForecastRun.run_key == manifest["run_key"])
    ).scalar_one_or_none()
    if existing is not None:
        raise ForecastImportError(f"run {manifest['run_key']} is already imported (id {existing})")

    rows = _read_rows(csv_path, start, horizon)
    if len(rows) != expected_rows:
        raise ForecastImportError(f"manifest says {manifest['rows']} rows, file has {len(rows)}")

    run = ForecastRun(
        run_key=manifest["run_key"],
        name=folder.name,
        dataset=manifest["dataset"],
        model=manifest["model"],
        trained_through=trained_through,
        forecast_start=start,
        forecast_end=end,
        horizon_days=horizon,
        series_count=series_count,
        row_count=len(rows),
        manifest=manifest,
    )
    session.add(run)
    session.flush()  # gives run.id

    # COPY is PostgreSQL's bulk loader: ~850k rows in seconds instead of minutes.
    # It runs on the session's own connection, so it is part of the same transaction.
    columns = ", ".join(["run_id", *CSV_COLUMNS])
    cursor = session.connection().connection.cursor()
    with cursor.copy(f"COPY forecasts ({columns}) FROM STDIN") as copy:
        for values in rows:
            copy.write_row((run.id, *values))
    return run
