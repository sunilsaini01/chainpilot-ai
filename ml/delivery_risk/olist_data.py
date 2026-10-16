"""Olist e-commerce data: one row per delivered order, with a "late" label and
features known at dispatch time (when the seller hands the order to the carrier).

Data: Kaggle "Brazilian E-Commerce Public Dataset by Olist" (download guide in
docs/DATASETS.md). It describes a Brazilian marketplace, a different business
from M5 (Walmart). The two are never joined.

Label
    late = 1 if the order reached the customer on a calendar day after the
    estimated delivery date that the customer was promised at purchase.

What the model may use (known at dispatch)
    everything known at purchase (promise, prices, freight, products, locations,
    payment) plus the dispatch facts (handover time; whether the seller missed its
    shipping deadline).

What it must never use (leakage)
    the customer delivery date (it IS the answer), reviews (written after
    delivery), and the final order status.

Command line (from the `ml` folder):
    python -m delivery_risk.olist_data validate ../data/raw/olist
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

FILES = {
    "orders": "olist_orders_dataset.csv",
    "items": "olist_order_items_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
}

# Time-based split by purchase date, fixed before any modelling (see docs/DECISIONS.md).
SPLITS = {
    "train": ("2017-01-01", "2017-12-31"),
    "validation": ("2018-01-01", "2018-03-31"),
    "test": ("2018-04-01", "2018-08-31"),
}
# Only keep orders whose promised date is at least this long before the data ends,
# so that late orders had time to arrive and be recorded (avoids right-censoring).
CENSORING_MARGIN_DAYS = 30

FEATURE_COLUMNS = [
    "promised_days",  # purchase -> promised date
    "handling_days",  # purchase -> carrier handover
    "days_left_at_dispatch",  # carrier handover -> promised date
    "dispatched_after_limit",  # handover after the seller's shipping deadline
    "purchase_weekday",
    "purchase_month",
    "dispatch_weekday",
    "n_items",
    "n_sellers",
    "total_price",
    "total_freight",
    "freight_share",
    "total_weight_kg",
    "max_volume_litres",
    "distance_km",
    "same_state",
    "payment_installments",
    "customer_state",  # category
    "seller_state",  # category
    "product_category",  # category
    "payment_type",  # category
]
CATEGORY_FEATURES = ["customer_state", "seller_state", "product_category", "payment_type"]
# Columns that exist in the raw data but must never become features.
FORBIDDEN_FEATURES = {
    "order_delivered_customer_date",
    "delivered_date",
    "late",
    "delivery_days",
    "order_status",
    "review_score",
    "review_comment_message",
    "review_creation_date",
    "outcome_known_at",
}


def find_files(raw_dir: Path) -> dict[str, Path]:
    paths = {name: Path(raw_dir) / filename for name, filename in FILES.items()}
    missing = [path.name for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"Olist files missing in {raw_dir}: {', '.join(missing)}. "
            "See docs/DATASETS.md for how to download them."
        )
    return paths


def load_tables(raw_dir: Path) -> dict[str, pd.DataFrame]:
    paths = find_files(raw_dir)
    dates = {
        "orders": [
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ],
        "items": ["shipping_limit_date"],
    }
    return {name: pd.read_csv(path, parse_dates=dates.get(name)) for name, path in paths.items()}


def zip_centroids(geolocation: pd.DataFrame) -> pd.DataFrame:
    """Mean latitude/longitude per 5-digit zip prefix (the raw file has many points per prefix).

    Points outside Brazil's bounding box are dropped first; the raw file contains a
    few obviously wrong coordinates.
    """
    inside = geolocation["geolocation_lat"].between(-34, 6) & geolocation[
        "geolocation_lng"
    ].between(-74, -34)
    return (
        geolocation[inside]
        .groupby("geolocation_zip_code_prefix")[["geolocation_lat", "geolocation_lng"]]
        .mean()
    )


def haversine_km(lat1, lng1, lat2, lng2) -> np.ndarray:
    """Great-circle distance in km between arrays of coordinates."""
    lat1, lng1, lat2, lng2 = (
        np.radians(np.asarray(v, dtype=float)) for v in (lat1, lng1, lat2, lng2)
    )
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    )
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def validate_tables(tables: dict[str, pd.DataFrame]) -> list[str]:
    """Structural checks on the raw tables. Returns a list of problems."""
    problems = []
    orders, items = tables["orders"], tables["items"]
    if orders["order_id"].duplicated().any():
        problems.append("orders: duplicate order_id")
    if items.duplicated(["order_id", "order_item_id"]).any():
        problems.append("items: duplicate (order_id, order_item_id)")
    unknown_orders = set(items["order_id"]) - set(orders["order_id"])
    if unknown_orders:
        problems.append(f"items: {len(unknown_orders)} order_ids not in orders")
    for name, key in [
        ("products", "product_id"),
        ("sellers", "seller_id"),
        ("customers", "customer_id"),
    ]:
        if tables[name][key].duplicated().any():
            problems.append(f"{name}: duplicate {key}")
    if (items["price"] < 0).any() or (items["freight_value"] < 0).any():
        problems.append("items: negative price or freight")
    if (
        orders["order_purchase_timestamp"].isna().any()
        or orders["order_estimated_delivery_date"].isna().any()
    ):
        problems.append("orders: missing purchase or estimated delivery date")
    return problems


def build_orders(tables: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, int]]:
    """One row per usable delivered order with label, features and split.

    Returns the table and a dict of how many orders were dropped for which reason.
    """
    orders = tables["orders"].copy()
    dropped: dict[str, int] = {}

    def drop(mask: pd.Series, reason: str) -> None:
        nonlocal orders
        dropped[reason] = int(mask.sum())
        orders = orders[~mask]

    drop(orders["order_status"] != "delivered", "not delivered (outcome unknown)")
    drop(
        orders["order_delivered_customer_date"].isna()
        | orders["order_delivered_carrier_date"].isna(),
        "missing delivery or carrier date",
    )
    drop(
        (orders["order_delivered_carrier_date"] < orders["order_purchase_timestamp"])
        | (orders["order_delivered_customer_date"] < orders["order_delivered_carrier_date"]),
        "inconsistent dates (handover before purchase, or delivery before handover)",
    )
    data_end = tables["orders"]["order_purchase_timestamp"].max()
    drop(
        orders["order_estimated_delivery_date"]
        > data_end - pd.Timedelta(days=CENSORING_MARGIN_DAYS),
        f"promised date within {CENSORING_MARGIN_DAYS} days of the data end "
        "(outcome may be censored)",
    )

    # Split by purchase date; orders outside every split window are dropped.
    purchase_day = orders["order_purchase_timestamp"].dt.normalize()
    orders["split"] = None
    for name, (start, end) in SPLITS.items():
        orders.loc[purchase_day.between(pd.Timestamp(start), pd.Timestamp(end)), "split"] = name
    drop(orders["split"].isna(), "purchased outside the split windows (2016, Sep-Oct 2018)")

    # Label: delivered on a later calendar day than promised.
    orders["late"] = (
        orders["order_delivered_customer_date"].dt.normalize()
        > orders["order_estimated_delivery_date"].dt.normalize()
    ).astype("int8")

    # --- Features known at dispatch ---------------------------------------------
    purchase = orders["order_purchase_timestamp"]
    carrier = orders["order_delivered_carrier_date"]
    promised = orders["order_estimated_delivery_date"]
    orders["promised_days"] = (promised - purchase).dt.total_seconds() / 86400
    orders["handling_days"] = (carrier - purchase).dt.total_seconds() / 86400
    orders["days_left_at_dispatch"] = (promised - carrier).dt.total_seconds() / 86400
    orders["purchase_weekday"] = purchase.dt.weekday
    orders["purchase_month"] = purchase.dt.month
    orders["dispatch_weekday"] = carrier.dt.weekday

    items = tables["items"].merge(tables["products"], on="product_id", how="left")
    items["weight_kg"] = items["product_weight_g"] / 1000
    items["volume_litres"] = (
        items["product_length_cm"] * items["product_height_cm"] * items["product_width_cm"] / 1000
    )
    per_order = items.groupby("order_id").agg(
        n_items=("order_item_id", "size"),
        n_sellers=("seller_id", "nunique"),
        total_price=("price", "sum"),
        total_freight=("freight_value", "sum"),
        # min_count=1: an order whose products all lack a weight stays unknown (NaN),
        # instead of pandas' default of summing nothing to 0 kg.
        total_weight_kg=("weight_kg", lambda weights: weights.sum(min_count=1)),
        max_volume_litres=("volume_litres", "max"),
        shipping_limit=("shipping_limit_date", "max"),
    )
    # The "main" item (highest price) gives the seller and category for the order.
    main = items.sort_values(["order_id", "price"], ascending=[True, False]).drop_duplicates(
        "order_id"
    )
    main = main[["order_id", "seller_id", "product_category_name"]]
    orders = orders.merge(per_order, on="order_id", how="inner").merge(
        main, on="order_id", how="left"
    )
    orders["freight_share"] = orders["total_freight"] / (
        orders["total_price"] + orders["total_freight"]
    )
    # Seller handed over later than its contractual shipping deadline.
    orders["dispatched_after_limit"] = (
        orders["order_delivered_carrier_date"] > orders["shipping_limit"]
    ).astype("int8")

    sellers = tables["sellers"][["seller_id", "seller_zip_code_prefix", "seller_state"]]
    customers = tables["customers"][["customer_id", "customer_zip_code_prefix", "customer_state"]]
    orders = orders.merge(sellers, on="seller_id", how="left").merge(
        customers, on="customer_id", how="left"
    )
    centroids = zip_centroids(tables["geolocation"])
    seller_xy = centroids.reindex(orders["seller_zip_code_prefix"]).to_numpy()
    customer_xy = centroids.reindex(orders["customer_zip_code_prefix"]).to_numpy()
    orders["distance_km"] = haversine_km(
        seller_xy[:, 0], seller_xy[:, 1], customer_xy[:, 0], customer_xy[:, 1]
    )
    orders["same_state"] = (orders["seller_state"] == orders["customer_state"]).astype("int8")

    payments = tables["payments"]
    main_payment = payments.sort_values(
        ["order_id", "payment_value"], ascending=[True, False]
    ).drop_duplicates("order_id")
    orders = orders.merge(
        main_payment[["order_id", "payment_type"]], on="order_id", how="left"
    ).merge(
        payments.groupby("order_id")["payment_installments"].max().rename("payment_installments"),
        on="order_id",
        how="left",
    )
    orders["product_category"] = orders["product_category_name"].fillna("unknown")
    for column in CATEGORY_FEATURES:
        orders[column] = orders[column].fillna("unknown").astype("category")

    # When the outcome (late or not) became known: the delivery time. NOT a feature;
    # rolling.py uses it to decide which orders a model was allowed to learn from.
    orders["outcome_known_at"] = orders["order_delivered_customer_date"]
    # When the order was handed to the carrier: known at dispatch, used to group the
    # day's dispatches for ranking (scoring.py). Not a model feature.
    orders["dispatched_at"] = orders["order_delivered_carrier_date"]
    columns = [
        "order_id",
        "split",
        "order_purchase_timestamp",
        "dispatched_at",
        "outcome_known_at",
        "late",
        *FEATURE_COLUMNS,
    ]
    return orders[columns].sort_values("order_purchase_timestamp").reset_index(drop=True), dropped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m delivery_risk.olist_data")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Check the Olist files and summarize")
    validate.add_argument("raw_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        tables = load_tables(args.raw_dir)
    except FileNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    problems = validate_tables(tables)
    for problem in problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    if problems:
        return 1
    orders, dropped = build_orders(tables)
    print(f"OK: {len(tables['orders'])} raw orders -> {len(orders)} usable delivered orders")
    for reason, count in dropped.items():
        print(f"  dropped {count:>6}: {reason}")
    for name in SPLITS:
        part = orders[orders["split"] == name]
        # The test set's late rate is not printed: it is looked at only once, in evaluation.
        rate = f", late rate {part['late'].mean():.3f}" if name != "test" else ""
        print(f"  {name:<10} {len(part):>6} orders {SPLITS[name][0]}..{SPLITS[name][1]}{rate}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
