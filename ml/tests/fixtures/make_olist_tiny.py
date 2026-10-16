"""Generate tiny Olist-format fixture files in ./olist_tiny/.

SYNTHETIC: hand-written orders in the real Olist column format, one per edge case,
so each test's expected result is obvious. Run from the `ml` folder:

    python tests/fixtures/make_olist_tiny.py
"""

import csv
from pathlib import Path

OUTPUT = Path(__file__).parent / "olist_tiny"

# order_id, status, purchase, approved, carrier, delivered, promised, customer
ORDERS = [
    # 1 train, on time
    (
        "o1",
        "delivered",
        "2017-03-01 10:00:00",
        "2017-03-01 11:00:00",
        "2017-03-02 09:00:00",
        "2017-03-08 15:00:00",
        "2017-03-20 00:00:00",
        "c1",
    ),
    # 2 train, late (delivered 2 days after the promised day)
    (
        "o2",
        "delivered",
        "2017-05-10 08:00:00",
        "2017-05-10 09:00:00",
        "2017-05-15 10:00:00",
        "2017-06-02 12:00:00",
        "2017-05-31 00:00:00",
        "c2",
    ),
    # 3 train, delivered late in the evening of the promised day: NOT late
    (
        "o3",
        "delivered",
        "2017-07-01 10:00:00",
        "2017-07-01 10:30:00",
        "2017-07-03 10:00:00",
        "2017-07-20 23:30:00",
        "2017-07-20 00:00:00",
        "c3",
    ),
    # 4 not delivered: outcome unknown, dropped
    (
        "o4",
        "shipped",
        "2017-08-01 10:00:00",
        "2017-08-01 11:00:00",
        "2017-08-02 10:00:00",
        "",
        "2017-08-25 00:00:00",
        "c1",
    ),
    # 5 inconsistent: carrier handover before purchase, dropped
    (
        "o5",
        "delivered",
        "2017-09-05 10:00:00",
        "2017-09-05 11:00:00",
        "2017-09-01 10:00:00",
        "2017-09-10 10:00:00",
        "2017-09-30 00:00:00",
        "c2",
    ),
    # 6 validation, late; two sellers, three items
    (
        "o6",
        "delivered",
        "2018-02-10 12:00:00",
        "2018-02-10 13:00:00",
        "2018-02-16 09:00:00",
        "2018-03-12 10:00:00",
        "2018-03-05 00:00:00",
        "c3",
    ),
    # 7 test, on time; all its products lack a weight; customer zip has no coordinates
    (
        "o7",
        "delivered",
        "2018-05-02 09:00:00",
        "2018-05-02 09:30:00",
        "2018-05-03 10:00:00",
        "2018-05-10 10:00:00",
        "2018-05-25 00:00:00",
        "c4",
    ),
    # 8 purchased in 2016: outside the split windows, dropped
    (
        "o8",
        "delivered",
        "2016-10-04 10:00:00",
        "2016-10-04 11:00:00",
        "2016-10-06 10:00:00",
        "2016-10-20 10:00:00",
        "2016-11-10 00:00:00",
        "c1",
    ),
    # 9 test, promised within 30 days of the data end (2018-08-31): censored, dropped
    (
        "o9",
        "delivered",
        "2018-08-05 10:00:00",
        "2018-08-05 11:00:00",
        "2018-08-06 10:00:00",
        "2018-08-15 10:00:00",
        "2018-08-20 00:00:00",
        "c2",
    ),
    # 10 the newest purchase in the data (defines the data end); not delivered
    ("o10", "processing", "2018-08-31 10:00:00", "", "", "", "2018-09-25 00:00:00", "c3"),
]
# order_id, item number, product, seller, shipping limit, price, freight
ITEMS = [
    ("o1", 1, "p1", "s1", "2017-03-03 10:00:00", 100.0, 20.0),
    ("o2", 1, "p2", "s2", "2017-05-12 10:00:00", 50.0, 25.0),  # handed over after the limit
    ("o3", 1, "p1", "s1", "2017-07-04 10:00:00", 80.0, 10.0),
    ("o4", 1, "p1", "s1", "2017-08-03 10:00:00", 60.0, 10.0),
    ("o5", 1, "p2", "s2", "2017-09-07 10:00:00", 40.0, 10.0),
    ("o6", 1, "p1", "s1", "2018-02-14 10:00:00", 30.0, 5.0),
    ("o6", 2, "p2", "s2", "2018-02-14 10:00:00", 200.0, 30.0),  # the main (most expensive) item
    ("o6", 3, "p1", "s1", "2018-02-14 10:00:00", 30.0, 5.0),
    ("o7", 1, "p3", "s1", "2018-05-04 10:00:00", 70.0, 15.0),
    ("o8", 1, "p1", "s1", "2016-10-07 10:00:00", 90.0, 20.0),
    ("o9", 1, "p1", "s1", "2018-08-07 10:00:00", 55.0, 12.0),
    ("o10", 1, "p1", "s1", "2018-09-02 10:00:00", 45.0, 9.0),
]
PRODUCTS = [  # id, category, weight g, length, height, width
    ("p1", "moveis_decoracao", 1500, 20, 10, 10),
    ("p2", "informatica_acessorios", 500, 30, 5, 20),
    ("p3", "", "", "", "", ""),  # unknown category and size
]
SELLERS = [("s1", "01001", "sao paulo", "SP"), ("s2", "20010", "rio de janeiro", "RJ")]
CUSTOMERS = [  # id, unique id, zip, city, state
    ("c1", "u1", "01001", "sao paulo", "SP"),
    ("c2", "u2", "30110", "belo horizonte", "MG"),
    ("c3", "u3", "20010", "rio de janeiro", "RJ"),
    ("c4", "u4", "99999", "nowhere", "AM"),  # zip prefix not in the geolocation file
]
PAYMENTS = [  # order, sequence, type, installments, value
    ("o1", 1, "credit_card", 3, 120.0),
    ("o2", 1, "boleto", 1, 75.0),
    ("o3", 1, "credit_card", 1, 90.0),
    ("o4", 1, "credit_card", 2, 70.0),
    ("o5", 1, "voucher", 1, 50.0),
    ("o6", 1, "credit_card", 6, 250.0),
    ("o6", 2, "voucher", 1, 50.0),
    ("o7", 1, "debit_card", 1, 85.0),
    ("o8", 1, "credit_card", 1, 110.0),
    ("o9", 1, "boleto", 1, 67.0),
    ("o10", 1, "credit_card", 1, 54.0),
]
GEOLOCATION = [  # zip prefix, lat, lng, city, state (several points per prefix, like the real file)
    ("01001", -23.55, -46.63, "sao paulo", "SP"),
    ("01001", -23.56, -46.64, "sao paulo", "SP"),
    ("01001", 40.0, -3.7, "madrid?", "SP"),  # obviously wrong point outside Brazil: ignored
    ("20010", -22.90, -43.18, "rio de janeiro", "RJ"),
    ("30110", -19.92, -43.94, "belo horizonte", "MG"),
]


def write(name: str, header: list[str], rows: list[tuple]) -> None:
    with open(OUTPUT / name, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file, lineterminator="\n")  # same bytes on every OS
        writer.writerow(header)
        writer.writerows(rows)


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    write(
        "olist_orders_dataset.csv",
        [
            "order_id",
            "order_status",
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
            "customer_id",
        ],
        ORDERS,
    )
    write(
        "olist_order_items_dataset.csv",
        [
            "order_id",
            "order_item_id",
            "product_id",
            "seller_id",
            "shipping_limit_date",
            "price",
            "freight_value",
        ],
        ITEMS,
    )
    write(
        "olist_products_dataset.csv",
        [
            "product_id",
            "product_category_name",
            "product_weight_g",
            "product_length_cm",
            "product_height_cm",
            "product_width_cm",
        ],
        PRODUCTS,
    )
    write(
        "olist_sellers_dataset.csv",
        ["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"],
        SELLERS,
    )
    write(
        "olist_customers_dataset.csv",
        [
            "customer_id",
            "customer_unique_id",
            "customer_zip_code_prefix",
            "customer_city",
            "customer_state",
        ],
        CUSTOMERS,
    )
    write(
        "olist_order_payments_dataset.csv",
        [
            "order_id",
            "payment_sequential",
            "payment_type",
            "payment_installments",
            "payment_value",
        ],
        PAYMENTS,
    )
    write(
        "olist_geolocation_dataset.csv",
        [
            "geolocation_zip_code_prefix",
            "geolocation_lat",
            "geolocation_lng",
            "geolocation_city",
            "geolocation_state",
        ],
        GEOLOCATION,
    )


if __name__ == "__main__":
    main()
