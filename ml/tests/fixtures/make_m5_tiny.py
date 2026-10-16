"""Generate the tiny M5-format fixture files in ./m5_tiny/.

SYNTHETIC: these numbers are invented. They only copy the *format* of the
Kaggle M5 files (same file names, columns and conventions), so the loader can be
tested without the real 300 MB dataset. Run from the `ml` folder:

    python tests/fixtures/make_m5_tiny.py
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUTPUT = Path(__file__).parent / "m5_tiny"
N_DAYS = 21  # three Walmart weeks of sales
# Like the real M5 files, the calendar and prices continue after the last sales day,
# so future days can be forecast. One extra week here.
N_CALENDAR_DAYS = 28
START = date(2011, 1, 29)  # the real M5 start date (a Saturday, week 11101)
ITEMS = [
    ("FOODS_1_001", "FOODS_1", "FOODS"),
    ("HOBBIES_1_001", "HOBBIES_1", "HOBBIES"),
    ("HOUSEHOLD_1_001", "HOUSEHOLD_1", "HOUSEHOLD"),
]
STORES = [("CA_1", "CA"), ("TX_1", "TX")]
# M5 numbers weekdays from Saturday = 1.
WEEKDAYS = ["Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def week_id(day_index: int) -> int:
    return 11101 + day_index // 7


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    rng = random.Random(2011)

    with open(OUTPUT / "calendar.csv", "w", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")  # same bytes on every OS
        writer.writerow(
            [
                "date",
                "wm_yr_wk",
                "weekday",
                "wday",
                "month",
                "year",
                "d",
                "event_name_1",
                "event_type_1",
                "event_name_2",
                "event_type_2",
                "snap_CA",
                "snap_TX",
                "snap_WI",
            ]
        )
        for i in range(N_CALENDAR_DAYS):
            day = START + timedelta(days=i)
            event = ("SuperBowl", "Sporting") if day == date(2011, 2, 6) else ("", "")
            writer.writerow(
                [
                    day.isoformat(),
                    week_id(i),
                    WEEKDAYS[i % 7],
                    i % 7 + 1,
                    day.month,
                    day.year,
                    f"d_{i + 1}",
                    *event,
                    "",
                    "",
                    int(day.day <= 10),
                    int(day.day % 2 == 1),
                    int(day.day % 3 == 0),
                ]
            )

    with open(OUTPUT / "sales_train_validation.csv", "w", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")  # same bytes on every OS
        writer.writerow(
            [
                "id",
                "item_id",
                "dept_id",
                "cat_id",
                "store_id",
                "state_id",
                *[f"d_{i + 1}" for i in range(N_DAYS)],
            ]
        )
        for item_id, dept_id, cat_id in ITEMS:
            for store_id, state_id in STORES:
                # HOBBIES only goes on sale in week 2: zero sales and no price before that.
                first_day = 7 if cat_id == "HOBBIES" else 0
                sales = [0 if i < first_day else rng.randint(0, 6) for i in range(N_DAYS)]
                writer.writerow(
                    [
                        f"{item_id}_{store_id}_validation",
                        item_id,
                        dept_id,
                        cat_id,
                        store_id,
                        state_id,
                        *sales,
                    ]
                )

    with open(OUTPUT / "sell_prices.csv", "w", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")  # same bytes on every OS
        writer.writerow(["store_id", "item_id", "wm_yr_wk", "sell_price"])
        for store_id, _ in STORES:
            for item_id, _, cat_id in ITEMS:
                for week in range(N_CALENDAR_DAYS // 7):
                    if cat_id == "HOBBIES" and week == 0:
                        continue  # not on sale yet, as in the real data
                    price = round(rng.uniform(1.0, 9.0), 2)
                    writer.writerow([store_id, item_id, 11101 + week, f"{price:.2f}"])


if __name__ == "__main__":
    main()
