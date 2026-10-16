"""Inventory replay simulator (P4-T2).

The policy math lives in the API package (`apps/api/app/inventory_policy.py`,
decision D-044) so the API and this simulator use the same formulas. That file
uses only the standard library; this makes it importable from `ml/`.
"""

import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.append(str(API_DIR))
