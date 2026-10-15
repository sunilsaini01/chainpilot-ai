"""Tests for the M5 loader and validator, using the tiny synthetic M5-format fixtures."""

import shutil
from pathlib import Path

import pandas as pd
import pytest

from demand_forecasting import m5_data
from demand_forecasting.m5_data import (
    find_files,
    load_calendar,
    load_prices,
    load_sales,
    summarize,
    to_long,
    validate_m5,
)

FIXTURES = Path(__file__).parent / "fixtures" / "m5_tiny"


@pytest.fixture
def tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    paths = find_files(FIXTURES)
    return (
        load_calendar(paths["calendar"]),
        load_sales(paths["sales"]),
        load_prices(paths["prices"]),
    )


def _in_call_order(tables) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """The fixture yields (calendar, sales, prices); to_long takes (sales, calendar, prices)."""
    calendar, sales, prices = tables
    return sales, calendar, prices


def test_fixture_files_are_valid(tables) -> None:
    assert validate_m5(*tables) == []


def test_missing_files_point_to_the_download_guide(tmp_path: Path) -> None:
    shutil.copy(FIXTURES / "calendar.csv", tmp_path)

    with pytest.raises(FileNotFoundError) as error:
        find_files(tmp_path)

    message = str(error.value)
    assert "sales_train_validation.csv" in message and "sell_prices.csv" in message
    assert "docs/DATASETS.md" in message


def test_sales_are_stored_compactly(tables) -> None:
    _, sales, _ = tables

    assert (sales[m5_data.day_columns_of(sales)].dtypes == "int16").all()


def test_to_long_has_one_row_per_series_and_day(tables) -> None:
    calendar, sales, prices = tables

    long = to_long(sales, calendar, prices)

    assert len(long) == 6 * 21
    assert long.groupby("id").size().eq(21).all()
    first = long.iloc[0]
    assert first["date"] == pd.Timestamp("2011-01-29")
    assert first["wm_yr_wk"] == 11101


def test_prices_join_by_store_item_and_week(tables) -> None:
    calendar, sales, prices = tables
    long = to_long(sales, calendar, prices)

    row = long[(long["id"] == "FOODS_1_001_CA_1_validation") & (long["d"] == "d_8")].iloc[0]
    expected = prices[
        (prices["store_id"] == "CA_1")
        & (prices["item_id"] == "FOODS_1_001")
        & (prices["wm_yr_wk"] == 11102)
    ]["sell_price"].iloc[0]
    assert row["sell_price"] == expected


def test_items_not_yet_on_sale_have_no_price_and_no_sales(tables) -> None:
    long = to_long(*_in_call_order(tables))
    hobbies_week_1 = long[(long["cat_id"] == "HOBBIES") & (long["wm_yr_wk"] == 11101)]

    assert len(hobbies_week_1) == 2 * 7
    assert hobbies_week_1["sell_price"].isna().all()
    assert (hobbies_week_1["sales"] == 0).all()


def test_each_series_gets_its_own_states_snap_flag(tables) -> None:
    calendar, sales, prices = tables
    long = to_long(sales, calendar, prices)

    for state, column in [("CA", "snap_CA"), ("TX", "snap_TX")]:
        rows = long[long["state_id"] == state][["d", "snap"]].drop_duplicates()
        expected = calendar.set_index("d")[column]
        assert (rows.set_index("d")["snap"] == expected.loc[rows["d"]]).all()
    assert "snap_CA" not in long.columns


def test_events_are_attached_and_blank_means_no_event(tables) -> None:
    long = to_long(*_in_call_order(tables))

    super_bowl = long[long["date"] == pd.Timestamp("2011-02-06")]
    assert (super_bowl["event_name_1"] == "SuperBowl").all()
    assert (long[long["date"] == pd.Timestamp("2011-02-05")]["event_name_1"] == "").all()


def test_store_filter_keeps_only_that_store() -> None:
    paths = find_files(FIXTURES)

    sales = load_sales(paths["sales"], ["TX_1"])
    prices = load_prices(paths["prices"], ["TX_1"])

    assert set(sales["store_id"]) == {"TX_1"}
    assert set(prices["store_id"].astype(str)) == {"TX_1"}
    assert len(sales) == 3


def test_summary(tables) -> None:
    summary = summarize(to_long(*_in_call_order(tables)))

    assert summary["series"] == 6
    assert summary["first_date"] == "2011-01-29"
    assert summary["last_date"] == "2011-02-18"
    # 2 HOBBIES series x 7 unpriced days out of 126 rows.
    assert summary["days_without_price_share"] == round(14 / 126, 3)


# --- The validator must catch broken data -------------------------------------


def broken(tables, which: str, change) -> list[str]:
    calendar, sales, prices = (frame.copy() for frame in tables)
    frames = {"calendar": calendar, "sales": sales, "prices": prices}
    frames[which] = change(frames[which])
    return validate_m5(frames["calendar"], frames["sales"], frames["prices"])


def _set(frame: pd.DataFrame, column: str, row: int, value) -> pd.DataFrame:
    frame[column] = frame[column].astype("object" if isinstance(value, str) else "float64")
    frame.loc[row, column] = value
    return frame


@pytest.mark.parametrize(
    ("which", "change", "expected"),
    [
        ("sales", lambda f: f.drop(columns=["store_id"]), "missing columns"),
        ("sales", lambda f: f.drop(columns=["d_5"]), "not consecutive"),
        ("sales", lambda f: _set(f, "d_3", 0, -1), "negative"),
        ("sales", lambda f: _set(f, "d_3", 0, 1.5), "whole numbers"),
        ("sales", lambda f: _set(f, "d_3", 0, float("nan")), "missing values"),
        ("sales", lambda f: pd.concat([f, f.iloc[[0]]], ignore_index=True), "duplicate ids"),
        ("calendar", lambda f: f.drop(index=20), "missing from calendar"),
        ("calendar", lambda f: f.drop(index=10).reset_index(drop=True), "not consecutive days"),
        ("prices", lambda f: _set(f, "sell_price", 0, 0.0), "non-positive"),
        ("prices", lambda f: pd.concat([f, f.iloc[[0]]], ignore_index=True), "duplicate"),
        ("prices", lambda f: f[f["item_id"] != "FOODS_1_001"], "no price at all"),
    ],
)
def test_validator_catches_problems(tables, which: str, change, expected: str) -> None:
    problems = broken(tables, which, change)

    assert any(expected in problem for problem in problems), problems


# --- Command line ----------------------------------------------------------------


def test_cli_validate_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert m5_data.main(["validate", str(FIXTURES)]) == 0

    output = capsys.readouterr().out
    assert "OK: 6 series x 21 days" in output
    assert "official file has 30490 series" in output  # the fixture is not the full data
    assert "first_date: 2011-01-29" in output


def test_cli_validate_missing_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert m5_data.main(["validate", str(tmp_path)]) == 1
    assert "docs/DATASETS.md" in capsys.readouterr().err


def test_cli_reports_problems(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for name in ["calendar.csv", "sell_prices.csv"]:
        shutil.copy(FIXTURES / name, tmp_path)
    sales = pd.read_csv(FIXTURES / "sales_train_validation.csv")
    sales.loc[0, "d_2"] = -3
    sales.to_csv(tmp_path / "sales_train_validation.csv", index=False)

    assert m5_data.main(["validate", str(tmp_path)]) == 1
    assert "PROBLEM: sales: negative unit sales" in capsys.readouterr().err
