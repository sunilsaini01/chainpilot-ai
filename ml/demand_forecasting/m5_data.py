"""Loading and checking the Kaggle M5 Forecasting dataset.

The M5 data is Walmart unit sales for 3,049 products in 10 US stores over
1,913 days (2011-01-29 to 2016-04-24), in three files:

- sales_train_validation.csv: one row per product/store, one column per day (d_1 ... d_1913)
- calendar.csv: one row per day: date, Walmart week, events, SNAP food-stamp days
- sell_prices.csv: weekly price per store and product

Download instructions: docs/DATASETS.md. The data is NOT in Git.

Command line (run from the `ml` folder):
    python -m demand_forecasting.m5_data validate ../data/raw/m5
    python -m demand_forecasting.m5_data validate ../data/raw/m5 --store CA_1
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

FILES = {
    "calendar": "calendar.csv",
    "sales": "sales_train_validation.csv",
    "prices": "sell_prices.csv",
}
SALES_ID_COLUMNS = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]
CALENDAR_COLUMNS = [
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
PRICE_COLUMNS = ["store_id", "item_id", "wm_yr_wk", "sell_price"]

# Size of the full official file, used only for an informational note.
FULL_SERIES_COUNT = 30_490
FULL_DAY_COUNT = 1_913
# Above this many series the long table gets very large (full data: ~58M rows), so the
# command-line summary is skipped unless a store filter is given.
MAX_SERIES_FOR_SUMMARY = 5_000


def find_files(raw_dir: Path) -> dict[str, Path]:
    """Return the paths of the three M5 files. Raises FileNotFoundError naming what is missing."""
    paths = {name: Path(raw_dir) / filename for name, filename in FILES.items()}
    missing = [path.name for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"M5 files missing in {raw_dir}: {', '.join(missing)}. "
            "See docs/DATASETS.md for how to download them."
        )
    return paths


def load_calendar(path: Path) -> pd.DataFrame:
    calendar = pd.read_csv(path, parse_dates=["date"])
    # Empty event cells are "no event", not missing data.
    for column in ["event_name_1", "event_type_1", "event_name_2", "event_type_2"]:
        if column in calendar:
            calendar[column] = calendar[column].fillna("")
    return calendar


def load_prices(path: Path, store_ids: list[str] | None = None) -> pd.DataFrame:
    prices = pd.read_csv(path, dtype={"store_id": "category", "item_id": "category"})
    if store_ids:
        prices = prices[prices["store_id"].isin(store_ids)].reset_index(drop=True)
    return prices


def load_sales(path: Path, store_ids: list[str] | None = None) -> pd.DataFrame:
    """Wide sales table. `store_ids` keeps only some stores (the full file melts to ~58M rows)."""
    # Categories store each repeated text value once; melting later then copies small
    # codes instead of millions of strings, which keeps peak memory down.
    sales = pd.read_csv(path, dtype={column: "category" for column in SALES_ID_COLUMNS})
    if store_ids:
        sales = sales[sales["store_id"].isin(store_ids)].reset_index(drop=True)
        # Drop categories for the stores and items that were filtered out.
        for column in SALES_ID_COLUMNS:
            sales[column] = sales[column].cat.remove_unused_categories()
    day_columns = day_columns_of(sales)
    # Daily unit sales fit in int16 (max 32,767), which cuts memory by 4x.
    if day_columns and sales[day_columns].notna().all().all():
        sales[day_columns] = sales[day_columns].astype("int16")
    return sales


def day_columns_of(sales: pd.DataFrame) -> list[str]:
    return [column for column in sales.columns if column.startswith("d_")]


def validate_m5(calendar: pd.DataFrame, sales: pd.DataFrame, prices: pd.DataFrame) -> list[str]:
    """Check the structure and basic sanity of the three tables. Returns a list of problems."""
    problems: list[str] = []

    for name, frame, required in [
        ("calendar", calendar, CALENDAR_COLUMNS),
        ("sales", sales, SALES_ID_COLUMNS),
        ("prices", prices, PRICE_COLUMNS),
    ]:
        missing = [column for column in required if column not in frame.columns]
        if missing:
            problems.append(f"{name}: missing columns {missing}")
    if problems:
        return problems  # the checks below need these columns

    # Sales: day columns must be d_1, d_2, ... with no gaps, counts whole and >= 0.
    day_columns = day_columns_of(sales)
    expected = [f"d_{number}" for number in range(1, len(day_columns) + 1)]
    if not day_columns:
        problems.append("sales: no day columns (d_1, d_2, ...)")
    elif day_columns != expected:
        problems.append("sales: day columns are not consecutive d_1..d_N")
    if sales["id"].duplicated().any():
        problems.append(f"sales: {int(sales['id'].duplicated().sum())} duplicate ids")
    values = sales[day_columns]
    if values.isna().any().any():
        problems.append("sales: missing values in day columns")
    elif (values < 0).any().any():
        problems.append("sales: negative unit sales")
    elif not (values == values.round()).all().all():
        problems.append("sales: unit sales are not whole numbers")

    # Calendar: one row per day, consecutive dates, covering every sales day.
    if calendar["d"].duplicated().any():
        problems.append("calendar: duplicate d values")
    gaps = calendar["date"].sort_values().diff().dropna() != pd.Timedelta(days=1)
    if gaps.any():
        problems.append("calendar: dates are not consecutive days")
    not_in_calendar = set(day_columns) - set(calendar["d"])
    if not_in_calendar:
        problems.append(f"calendar: {len(not_in_calendar)} sales days missing from calendar")

    # Prices: positive, one price per store/item/week, weeks known to the calendar.
    if (prices["sell_price"] <= 0).any():
        problems.append("prices: non-positive sell_price")
    if prices.duplicated(["store_id", "item_id", "wm_yr_wk"]).any():
        problems.append("prices: duplicate store/item/week rows")
    unknown_weeks = set(prices["wm_yr_wk"]) - set(calendar["wm_yr_wk"])
    if unknown_weeks:
        problems.append(f"prices: {len(unknown_weeks)} weeks not in calendar")
    priced = set(zip(prices["store_id"].astype(str), prices["item_id"].astype(str), strict=True))
    series = set(zip(sales["store_id"], sales["item_id"], strict=True))
    never_priced = series - priced
    if never_priced:
        problems.append(f"prices: {len(never_priced)} store/item series have no price at all")

    return problems


def to_long(sales: pd.DataFrame, calendar: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """One row per series and day: sales plus date, price, events and the state's SNAP flag.

    `sell_price` is empty (NaN) in weeks when the product was not on sale in that
    store, which is how M5 marks items not yet launched. Prices are set in advance
    by the retailer, so using them as forecast inputs is not leakage.
    """
    long = sales.melt(
        id_vars=SALES_ID_COLUMNS, value_vars=day_columns_of(sales), var_name="d", value_name="sales"
    )
    long = long.merge(
        calendar[
            [
                "d",
                "date",
                "wm_yr_wk",
                "wday",
                "event_name_1",
                "event_type_1",
                "snap_CA",
                "snap_TX",
                "snap_WI",
            ]
        ],
        on="d",
        how="left",
        validate="many_to_one",
    )
    prices = prices.astype({"store_id": str, "item_id": str})
    long = long.merge(
        prices, on=["store_id", "item_id", "wm_yr_wk"], how="left", validate="many_to_one"
    )
    # Keep only the SNAP flag of the series' own state (CA rows use snap_CA, ...).
    snap_by_state = {"CA": "snap_CA", "TX": "snap_TX", "WI": "snap_WI"}
    long["snap"] = 0
    for state, column in snap_by_state.items():
        in_state = long["state_id"] == state
        long.loc[in_state, "snap"] = long.loc[in_state, column]
    long = long.drop(columns=list(snap_by_state.values()))
    long = compact_long(long)
    return long.sort_values(["id", "date"]).reset_index(drop=True)


# Text columns that repeat on every row: stored once per distinct value as categories.
LONG_CATEGORY_COLUMNS = [*SALES_ID_COLUMNS, "d", "event_name_1", "event_type_1"]
# Small number types: sales fit int16, week ids int32, flags and weekday int8, prices float32.
LONG_NUMBER_TYPES = {
    "sales": "int16",
    "wm_yr_wk": "int32",
    "wday": "int8",
    "snap": "int8",
    "sell_price": "float32",
}


def compact_long(long: pd.DataFrame) -> pd.DataFrame:
    """Shrink the long table's memory.

    Measured on the real data (2026-10-15): one store (CA_1, 5.8M rows) went from
    3,476 MB to 179 MB, and all 10 stores (58.3M rows) fit in 1.8 GB with a 6.4 GB
    peak while building. Without this, all stores would need roughly 35 GB.
    """
    for column in LONG_CATEGORY_COLUMNS:
        long[column] = long[column].astype("category")
    return long.astype(LONG_NUMBER_TYPES)


def summarize(long: pd.DataFrame) -> dict[str, object]:
    """A few facts for a quick look at a loaded subset."""
    return {
        "rows": len(long),
        "series": long["id"].nunique(),
        "stores": sorted(long["store_id"].unique()),
        "first_date": long["date"].min().date().isoformat(),
        "last_date": long["date"].max().date().isoformat(),
        "zero_sales_share": round(float((long["sales"] == 0).mean()), 3),
        "days_without_price_share": round(float(long["sell_price"].isna().mean()), 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m demand_forecasting.m5_data")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Check the M5 files and summarize them")
    validate.add_argument("raw_dir", type=Path)
    validate.add_argument("--store", action="append", help="limit to a store, e.g. CA_1")
    args = parser.parse_args(argv)

    try:
        paths = find_files(args.raw_dir)
    except FileNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    calendar = load_calendar(paths["calendar"])
    sales = load_sales(paths["sales"], args.store)
    prices = load_prices(paths["prices"], args.store)

    problems = validate_m5(calendar, sales, prices)
    if problems:
        for problem in problems:
            print(f"PROBLEM: {problem}", file=sys.stderr)
        return 1

    print(f"OK: {len(sales)} series x {len(day_columns_of(sales))} days")
    if not args.store and (len(sales), len(day_columns_of(sales))) != (
        FULL_SERIES_COUNT,
        FULL_DAY_COUNT,
    ):
        print(f"Note: the official file has {FULL_SERIES_COUNT} series x {FULL_DAY_COUNT} days.")
    if len(sales) > MAX_SERIES_FOR_SUMMARY:
        print("Summary skipped for this many series; add e.g. --store CA_1 to see one.")
        return 0
    for key, value in summarize(to_long(sales, calendar, prices)).items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
