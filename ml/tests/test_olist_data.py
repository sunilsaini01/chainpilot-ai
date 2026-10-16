"""Tests for the Olist delivery data: label, leakage rules, censoring, split and features."""

import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from delivery_risk import olist_data
from delivery_risk.olist_data import (
    CATEGORY_FEATURES,
    FEATURE_COLUMNS,
    FORBIDDEN_FEATURES,
    build_orders,
    haversine_km,
    load_tables,
    validate_tables,
)

FIXTURES = Path(__file__).parent / "fixtures" / "olist_tiny"


@pytest.fixture
def tables() -> dict[str, pd.DataFrame]:
    return load_tables(FIXTURES)


@pytest.fixture
def orders(tables) -> pd.DataFrame:
    built, _ = build_orders(tables)
    return built.set_index("order_id")


def test_fixture_tables_are_valid(tables) -> None:
    assert validate_tables(tables) == []


def test_only_usable_delivered_orders_are_kept_and_drops_are_counted(tables) -> None:
    built, dropped = build_orders(tables)

    assert sorted(built["order_id"]) == ["o1", "o2", "o3", "o6", "o7"]
    assert dropped["not delivered (outcome unknown)"] == 2  # o4 shipped, o10 processing
    assert dropped["purchased outside the split windows (2016, Sep-Oct 2018)"] == 1  # o8
    assert sum(dropped.values()) + len(built) == len(tables["orders"])


def test_late_label_compares_calendar_days(orders) -> None:
    assert orders.loc["o1", "late"] == 0
    assert orders.loc["o2", "late"] == 1  # two days after the promise
    assert orders.loc["o3", "late"] == 0  # 23:30 on the promised day still counts as on time
    assert orders.loc["o6", "late"] == 1


def test_orders_promised_close_to_the_data_end_are_dropped(tables) -> None:
    # o9 was promised 2018-08-20; the data ends 2018-08-31, inside the 30-day margin.
    built, dropped = build_orders(tables)

    assert "o9" not in set(built["order_id"])
    assert dropped["promised date within 30 days of the data end (outcome may be censored)"] == 1


def test_inconsistent_dates_are_dropped(tables) -> None:
    built, _ = build_orders(tables)

    assert "o5" not in set(built["order_id"])  # handed to the carrier before it was bought


def test_split_is_by_purchase_date(orders) -> None:
    assert orders["split"].to_dict() == {
        "o1": "train",
        "o2": "train",
        "o3": "train",
        "o6": "validation",
        "o7": "test",
    }


def test_no_forbidden_column_is_a_feature() -> None:
    assert not (set(FEATURE_COLUMNS) & FORBIDDEN_FEATURES)
    assert set(CATEGORY_FEATURES) <= set(FEATURE_COLUMNS)


def test_features_do_not_change_when_the_delivery_date_changes(tables) -> None:
    """Leakage check: the customer delivery date may change the label, never a feature."""
    before, _ = build_orders(tables)
    changed = {name: table.copy() for name, table in tables.items()}
    delivered = changed["orders"]["order_delivered_customer_date"]
    changed["orders"]["order_delivered_customer_date"] = delivered + pd.Timedelta(days=9)

    after, _ = build_orders(changed)

    pd.testing.assert_frame_equal(before[FEATURE_COLUMNS], after[FEATURE_COLUMNS])
    assert not before["late"].equals(after["late"])


def test_reviews_cannot_influence_the_data() -> None:
    # The loader does not even read the reviews file (written after delivery).
    assert "reviews" not in olist_data.FILES


def test_timing_features(orders) -> None:
    o2 = orders.loc["o2"]
    assert o2["promised_days"] == pytest.approx(20 + 16 / 24)  # 05-10 08:00 -> 05-31 00:00
    assert o2["handling_days"] == pytest.approx(5 + 2 / 24)  # 05-10 08:00 -> 05-15 10:00
    assert o2["days_left_at_dispatch"] == pytest.approx(15 + 14 / 24)
    assert o2["dispatched_after_limit"] == 1  # limit was 05-12
    assert orders.loc["o1", "dispatched_after_limit"] == 0


def test_multi_item_order_is_summarized_by_its_main_item(orders) -> None:
    o6 = orders.loc["o6"]
    assert (o6["n_items"], o6["n_sellers"]) == (3, 2)
    assert o6["total_price"] == pytest.approx(260.0)
    assert o6["total_freight"] == pytest.approx(40.0)
    assert o6["freight_share"] == pytest.approx(40 / 300)
    assert o6["total_weight_kg"] == pytest.approx(1.5 + 0.5 + 1.5)
    assert o6["seller_state"] == "RJ"  # seller of the most expensive item
    assert o6["product_category"] == "informatica_acessorios"
    assert o6["payment_type"] == "credit_card"  # the largest payment
    assert o6["payment_installments"] == 6


def test_missing_weights_stay_unknown_not_zero(orders) -> None:
    o7 = orders.loc["o7"]
    assert np.isnan(o7["total_weight_kg"])
    assert np.isnan(o7["max_volume_litres"])
    assert o7["product_category"] == "unknown"


def test_distance_uses_zip_centroids_and_ignores_points_outside_brazil(orders) -> None:
    # o1: seller and customer share zip 01001 -> 0 km, even though one point is in Madrid.
    assert orders.loc["o1", "distance_km"] == pytest.approx(0.0, abs=1e-6)
    # o2: Rio (seller) -> Belo Horizonte (customer), about 340 km.
    assert 300 < orders.loc["o2", "distance_km"] < 380
    assert orders.loc["o2", "same_state"] == 0
    assert orders.loc["o1", "same_state"] == 1
    # o7: customer zip has no coordinates -> unknown distance.
    assert np.isnan(orders.loc["o7", "distance_km"])


def test_haversine_known_distance() -> None:
    # Sao Paulo -> Rio de Janeiro is about 360 km.
    assert 340 < float(haversine_km(-23.55, -46.63, -22.90, -43.18)) < 380


def test_validator_catches_problems(tables) -> None:
    broken = {name: table.copy() for name, table in tables.items()}
    broken["orders"] = pd.concat([broken["orders"], broken["orders"].iloc[[0]]])
    broken["items"].loc[0, "price"] = -1

    problems = validate_tables(broken)

    assert any("duplicate order_id" in p for p in problems)
    assert any("negative price" in p for p in problems)


def test_command_line(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert olist_data.main(["validate", str(FIXTURES)]) == 0
    output = capsys.readouterr().out
    assert "10 raw orders -> 5 usable delivered orders" in output
    assert "late rate" not in output.split("test")[-1]  # the test late rate stays hidden

    for path in FIXTURES.iterdir():
        if path.name != "olist_orders_dataset.csv":
            shutil.copy(path, tmp_path)
    assert olist_data.main(["validate", str(tmp_path)]) == 1
    assert "docs/DATASETS.md" in capsys.readouterr().err
