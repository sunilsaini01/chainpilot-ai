"""Import a delivery-risk scoring file produced by ml/delivery_risk/scoring.py.

Same approach as forecast_import.py: the folder holds scores.csv and
manifest.json; everything is checked before anything is written; the run and
its rows go in one transaction (PostgreSQL COPY); a file can be imported once.

DATA LABEL: Olist public marketplace orders, not ChainPilot's simulated suppliers.
"""

import csv
import json
import math
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.files import sha256_of
from app.models import DeliveryRiskRun

CSV_COLUMNS = [
    "order_id",
    "purchased_at",
    "dispatched_at",
    "dispatch_date",
    "probability",
    "day_percentile",
    "tier",
    "alert",
    "reasons",
]
MANIFEST_FIELDS = [
    "run_key",
    "dataset",
    "model",
    "period_start",
    "period_end",
    "rows",
    "csv_sha256",
]
TIERS = {"high", "medium", "low"}


class DeliveryRiskImportError(Exception):
    """The scoring folder is missing, inconsistent, or already imported."""


def _parse_row(row: dict, line: int, start: date, end: date) -> tuple:
    try:
        purchased = datetime.fromisoformat(row["purchased_at"])
        dispatched = datetime.fromisoformat(row["dispatched_at"])
        day = date.fromisoformat(row["dispatch_date"])
        probability = float(row["probability"])
        percentile = float(row["day_percentile"])
        reasons = json.loads(row["reasons"])
    except (ValueError, TypeError) as error:
        raise DeliveryRiskImportError(f"line {line}: unreadable value ({error})") from error
    if not (math.isfinite(probability) and 0 <= probability <= 1):
        raise DeliveryRiskImportError(f"line {line}: probability must be between 0 and 1")
    if not (math.isfinite(percentile) and 0 < percentile <= 1):
        raise DeliveryRiskImportError(f"line {line}: day_percentile must be in (0, 1]")
    if row["tier"] not in TIERS or row["alert"] not in ("true", "false"):
        raise DeliveryRiskImportError(f"line {line}: unknown tier or alert value")
    alert = row["alert"] == "true"
    if alert != (row["tier"] == "high"):
        raise DeliveryRiskImportError(f"line {line}: alert must be true exactly for the high tier")
    if dispatched.date() != day or not start <= day <= end or dispatched < purchased:
        raise DeliveryRiskImportError(f"line {line}: dates are inconsistent")
    if not isinstance(reasons, list):
        raise DeliveryRiskImportError(f"line {line}: reasons must be a list")
    return (
        row["order_id"],
        purchased,
        dispatched,
        day,
        probability,
        percentile,
        row["tier"],
        alert,
        json.dumps(reasons),
    )


def import_delivery_risk(session: Session, folder: Path) -> DeliveryRiskRun:
    """Validate and load one scoring folder. Does not commit; the caller does."""
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise DeliveryRiskImportError(f"{folder} has no manifest.json") from error
    missing = [field for field in MANIFEST_FIELDS if field not in manifest]
    if missing:
        raise DeliveryRiskImportError(f"manifest.json is missing {missing}")
    csv_path = folder / "scores.csv"
    if not csv_path.is_file():
        raise DeliveryRiskImportError(f"{folder} has no scores.csv")
    if sha256_of(csv_path) != manifest["csv_sha256"]:
        raise DeliveryRiskImportError("scores.csv does not match the checksum in manifest.json")
    existing = session.execute(
        select(DeliveryRiskRun.id).where(DeliveryRiskRun.run_key == manifest["run_key"])
    ).scalar_one_or_none()
    if existing is not None:
        raise DeliveryRiskImportError(
            f"run {manifest['run_key']} is already imported (id {existing})"
        )

    start = date.fromisoformat(manifest["period_start"])
    end = date.fromisoformat(manifest["period_end"])
    with open(csv_path, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != CSV_COLUMNS:
            raise DeliveryRiskImportError(f"unexpected CSV header {reader.fieldnames}")
        rows = [_parse_row(row, line, start, end) for line, row in enumerate(reader, start=2)]
    if len(rows) != int(manifest["rows"]):
        raise DeliveryRiskImportError(
            f"manifest says {manifest['rows']} rows, file has {len(rows)}"
        )

    run = DeliveryRiskRun(
        run_key=manifest["run_key"],
        name=folder.name,
        dataset=manifest["dataset"],
        model=manifest["model"],
        period_start=start,
        period_end=end,
        row_count=len(rows),
        manifest=manifest,
    )
    session.add(run)
    session.flush()
    columns = ", ".join(["run_id", *CSV_COLUMNS])
    cursor = session.connection().connection.cursor()
    with cursor.copy(f"COPY delivery_risk_scores ({columns}) FROM STDIN") as copy:
        for values in rows:
            copy.write_row((run.id, *values))
    return run
