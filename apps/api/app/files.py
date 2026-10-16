"""Small file helpers shared by the import commands."""

import hashlib
from pathlib import Path


def sha256_of(path: Path) -> str:
    """SHA-256 of a file, read in 1 MB blocks so large files do not fill memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
