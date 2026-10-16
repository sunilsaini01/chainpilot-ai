"""Small helpers shared by the import commands (forecasts, delivery risk).

Both imports check everything before writing, so that a bad file stops with a
clear message instead of a raw database error halfway through the load.
"""

import hashlib
import json
from pathlib import Path

from sqlalchemy import Table


class ImportFileError(Exception):
    """Base class: the import folder is missing, inconsistent, or already imported."""


def sha256_of(path: Path) -> str:
    """SHA-256 of a file, read in 1 MB blocks so large files do not fill memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(folder: Path, required: list[str], error: type[ImportFileError]) -> dict:
    """manifest.json as a dict with all required fields, or `error`."""
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except FileNotFoundError as problem:
        raise error(f"{folder} has no manifest.json") from problem
    except ValueError as problem:  # also catches invalid JSON (JSONDecodeError)
        raise error(f"manifest.json is not valid JSON ({problem})") from problem
    if not isinstance(manifest, dict):
        raise error("manifest.json must be a JSON object")
    missing = [field for field in required if field not in manifest]
    if missing:
        raise error(f"manifest.json is missing {missing}")
    return manifest


def text_limits(table: Table, columns: list[str]) -> dict[str, int]:
    """Maximum lengths of String(n) columns, read from the table so they never drift."""
    return {name: table.c[name].type.length for name in columns}


def check_text(
    values: dict, limits: dict[str, int], where: str, error: type[ImportFileError]
) -> None:
    """Each value must be non-empty text that fits its column."""
    for name, limit in limits.items():
        value = values[name]
        if not isinstance(value, str) or not 1 <= len(value) <= limit:
            raise error(f"{where}: {name} must be text of 1 to {limit} characters")
