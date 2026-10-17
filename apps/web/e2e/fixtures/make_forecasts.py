"""Writes the tiny SYNTHETIC forecast folder the browser tests import (forecasts/).

Not M5 data and not a model's output: flat made-up demand, so the test stack
has stock-out risks and recommendations to approve. The dataset name says so,
and the dashboard shows that name. Same output on every run.
Usage: python apps/web/e2e/fixtures/make_forecasts.py
"""

import csv
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

FOLDER = Path(__file__).parent / "forecasts"
START = date(2016, 4, 25)
HORIZON = 28
STORES = ["CA_1", "CA_2", "TX_1", "WI_1"]  # one per SYN- warehouse (the seed makes 4)
# One item per M5 category the seed's product categories map to; units per day.
ITEMS = {"FOODS_3_001": ("FOODS_3", "FOODS", 30.0), "HOBBIES_1_001": ("HOBBIES_1", "HOBBIES", 12.0),
         "HOUSEHOLD_1_001": ("HOUSEHOLD_1", "HOUSEHOLD", 20.0)}  # fmt: skip
COLUMNS = ["series_id", "item_id", "dept_id", "cat_id", "store_id",
           "forecast_date", "step", "forecast", "lower", "upper"]  # fmt: skip


def main() -> None:
    FOLDER.mkdir(exist_ok=True)
    csv_path = FOLDER / "forecasts.csv"
    rows = 0
    with open(csv_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(COLUMNS)
        for item, (dept, category, level) in ITEMS.items():
            for store in STORES:
                for step in range(1, HORIZON + 1):
                    day = START + timedelta(days=step - 1)
                    writer.writerow([f"{item}_{store}_evaluation", item, dept, category, store,
                                     day.isoformat(), step, level, level * 0.7, level * 1.3])  # fmt: skip
                    rows += 1
    csv_sha256 = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    manifest = {
        "run_key": "e2e-synthetic-" + csv_sha256[:8],
        "dataset": "SYNTHETIC test forecasts for browser tests (not M5, not a model)",
        "model": "flat made-up demand",
        "trained_through": (START - timedelta(days=1)).isoformat(),
        "forecast_start": START.isoformat(),
        "forecast_end": (START + timedelta(days=HORIZON - 1)).isoformat(),
        "horizon_days": HORIZON,
        "series": len(ITEMS) * len(STORES),
        "rows": rows,
        "csv_sha256": csv_sha256,
    }
    (FOLDER / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Wrote {rows} synthetic forecast rows to {FOLDER}")


if __name__ == "__main__":
    main()
