"""Forecast import and API tests (RUN_DB_TESTS=1)."""

import csv
import hashlib
import json
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import cli, forecast_import
from app.forecast_import import CSV_COLUMNS, ForecastImportError, import_forecasts
from app.models import AuditEvent, Forecast, ForecastRun, Role, User
from tests.conftest import login

START = date(2016, 4, 25)
SERIES = [
    ("FOODS_3_090_CA_1_validation", "FOODS_3_090", "FOODS_3", "FOODS", "CA_1"),
    ("HOBBIES_1_001_CA_1_validation", "HOBBIES_1_001", "HOBBIES_1", "HOBBIES", "CA_1"),
    ("FOODS_3_090_TX_1_validation", "FOODS_3_090", "FOODS_3", "FOODS", "TX_1"),
]
HORIZON = 7
DATASET = "M5 Forecasting - Accuracy (public Walmart data); not the simulated SYN- products"


def write_forecast_folder(
    folder: Path, csv_rows: list[list] | None = None, **manifest_changes
) -> Path:
    """A small valid forecast folder (3 series x 7 days), optionally altered."""
    folder.mkdir(parents=True, exist_ok=True)
    rows = csv_rows
    if rows is None:
        rows = []
        for number, (series_id, item, dept, cat, store) in enumerate(SERIES):
            for step in range(1, HORIZON + 1):
                point = 1.0 + number + step / 10
                rows.append(
                    [
                        series_id,
                        item,
                        dept,
                        cat,
                        store,
                        (START + timedelta(days=step - 1)).isoformat(),
                        step,
                        point,
                        max(point - 1, 0),
                        point + 2,
                    ]
                )
    with open(folder / "forecasts.csv", "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)
    checksum = hashlib.sha256((folder / "forecasts.csv").read_bytes()).hexdigest()
    manifest = {
        "run_key": checksum[:16],
        "dataset": DATASET,
        "model": "lightgbm_weekly",
        "trained_through": "2016-04-24",
        "forecast_start": START.isoformat(),
        "forecast_end": (START + timedelta(days=HORIZON - 1)).isoformat(),
        "horizon_days": HORIZON,
        "series": len(SERIES),
        "rows": len(rows),
        "csv_sha256": checksum,
        **manifest_changes,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def count(session: Session, model) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def test_import_loads_the_run_and_every_row(db_session: Session, tmp_path: Path) -> None:
    run = import_forecasts(db_session, write_forecast_folder(tmp_path / "run1"))
    db_session.commit()

    assert (run.row_count, run.series_count, run.horizon_days) == (21, 3, 7)
    assert run.forecast_start == START and run.forecast_end == date(2016, 5, 1)
    assert count(db_session, Forecast) == 21
    first = db_session.execute(select(Forecast).order_by(Forecast.id).limit(1)).scalar_one()
    assert (first.series_id, first.step, first.forecast_date) == (SERIES[0][0], 1, START)
    assert first.lower <= first.forecast <= first.upper


def test_the_same_file_cannot_be_imported_twice(db_session: Session, tmp_path: Path) -> None:
    folder = write_forecast_folder(tmp_path / "run1")
    import_forecasts(db_session, folder)
    db_session.commit()

    with pytest.raises(ForecastImportError, match="already imported"):
        import_forecasts(db_session, folder)


def _bad_rows(change: Callable[[list], None]) -> list[list]:
    rows = [
        [
            SERIES[0][0],
            "FOODS_3_090",
            "FOODS_3",
            "FOODS",
            "CA_1",
            (START + timedelta(days=s - 1)).isoformat(),
            s,
            2.0,
            1.0,
            3.0,
        ]
        for s in range(1, HORIZON + 1)
    ]
    change(rows)
    return rows


@pytest.mark.parametrize(
    ("rows", "manifest_changes", "message"),
    [
        (_bad_rows(lambda r: r[0].__setitem__(8, 2.5)), {}, "lower <= forecast"),  # lower > point
        (_bad_rows(lambda r: r[0].__setitem__(8, -0.1)), {}, "0 <= lower"),
        (_bad_rows(lambda r: r[2].__setitem__(5, "2016-05-30")), {}, "does not match date"),
        (_bad_rows(lambda r: r[0].__setitem__(7, "nan")), {}, "finite"),
        (_bad_rows(lambda r: r[0].__setitem__(7, "abc")), {}, "unreadable"),
        (_bad_rows(lambda r: None), {"rows": 99}, "manifest says 99 rows"),
        (_bad_rows(lambda r: None), {"csv_sha256": "0" * 64}, "checksum"),
        (_bad_rows(lambda r: r.append(list(r[0]))), {}, "appears twice"),  # same series and day
        (_bad_rows(lambda r: r[0].__setitem__(4, "X" * 17)), {}, "store_id must be text"),
        (_bad_rows(lambda r: r[0].__setitem__(0, "")), {}, "series_id must be text"),
        (_bad_rows(lambda r: None), {"horizon_days": 35}, "horizon_days must be 1 to 28"),
        (_bad_rows(lambda r: None), {"forecast_start": "soon"}, "unreadable value"),
        (_bad_rows(lambda r: None), {"model": "m" * 51}, "model must be text"),
    ],
)
def test_invalid_files_are_rejected_before_anything_is_written(
    db_session: Session, tmp_path: Path, rows, manifest_changes, message: str
) -> None:
    folder = write_forecast_folder(tmp_path / "bad", csv_rows=rows, **manifest_changes)

    with pytest.raises(ForecastImportError, match=message):
        import_forecasts(db_session, folder)
    db_session.rollback()

    assert count(db_session, ForecastRun) == 0
    assert count(db_session, Forecast) == 0


def test_missing_manifest_and_wrong_header_are_rejected(
    db_session: Session, tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ForecastImportError, match="no manifest"):
        import_forecasts(db_session, empty)
    (empty / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ForecastImportError, match="not valid JSON"):
        import_forecasts(db_session, empty)

    folder = write_forecast_folder(tmp_path / "header")
    text = (folder / "forecasts.csv").read_text(encoding="utf-8").replace("upper", "high", 1)
    (folder / "forecasts.csv").write_text(text, encoding="utf-8")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    manifest["csv_sha256"] = hashlib.sha256((folder / "forecasts.csv").read_bytes()).hexdigest()
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ForecastImportError, match="unexpected CSV header"):
        import_forecasts(db_session, folder)


def test_a_database_error_mid_import_leaves_nothing_behind(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The row checks now catch duplicates, so skip them to make COPY itself fail on
    # the unique constraint: the whole import must roll back, including the run row.
    folder = write_forecast_folder(tmp_path / "dup", rows=len(SERIES) * HORIZON + 1)
    original_read_rows = forecast_import._read_rows

    def read_rows_with_a_duplicate(*args) -> list[tuple]:
        rows = original_read_rows(*args)
        return [*rows, rows[0]]

    monkeypatch.setattr(forecast_import, "_read_rows", read_rows_with_a_duplicate)

    with pytest.raises(Exception, match="uq_forecasts_run_series_date"):
        import_forecasts(db_session, folder)
    db_session.rollback()

    assert count(db_session, ForecastRun) == 0


def test_cli_import_writes_an_audit_event(
    db_engine,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_engine", lambda: db_engine)
    folder = write_forecast_folder(tmp_path / "run1")

    assert cli.main(["import-forecasts", str(folder)]) == 0
    assert "Imported forecast run" in capsys.readouterr().out
    event = db_session.execute(select(AuditEvent)).scalar_one()
    assert (event.action, event.actor_user_id, event.details["rows"]) == (
        "forecast_run.imported",
        None,
        21,
    )
    assert cli.main(["import-forecasts", str(folder)]) == 1
    assert "already imported" in capsys.readouterr().err


# --- API ---------------------------------------------------------------------------


@pytest.fixture
def analyst_headers(api_client: TestClient, make_user: Callable[..., User]) -> dict[str, str]:
    make_user(Role.ANALYST)
    return login(api_client, "analyst@example.com")


def test_forecasts_need_login(api_client: TestClient) -> None:
    assert api_client.get("/forecasts").status_code == 401
    assert api_client.get("/forecasts/runs").status_code == 401


def test_no_runs_yet_is_404(api_client: TestClient, analyst_headers: dict[str, str]) -> None:
    response = api_client.get("/forecasts", headers=analyst_headers)

    assert response.status_code == 404


def test_newest_run_is_the_default_and_responses_are_labelled(
    api_client: TestClient, db_session: Session, analyst_headers: dict[str, str], tmp_path: Path
) -> None:
    import_forecasts(db_session, write_forecast_folder(tmp_path / "old"))
    newer_rows = [[SERIES[0][0], *SERIES[0][1:], START.isoformat(), 1, 9.0, 8.0, 10.0]]
    newer = import_forecasts(
        db_session, write_forecast_folder(tmp_path / "new", csv_rows=newer_rows, series=1)
    )
    db_session.commit()

    runs = api_client.get("/forecasts/runs", headers=analyst_headers)
    forecasts = api_client.get("/forecasts", headers=analyst_headers)

    assert [run["name"] for run in runs.json()] == ["new", "old"]
    assert runs.headers["X-Total-Count"] == "2"
    assert forecasts.status_code == 200
    assert [row["run_id"] for row in forecasts.json()] == [newer.id]
    assert "not the simulated SYN- products" in forecasts.headers["X-Dataset"]


def test_filters_paging_and_total_count(
    api_client: TestClient, db_session: Session, analyst_headers: dict[str, str], tmp_path: Path
) -> None:
    run = import_forecasts(db_session, write_forecast_folder(tmp_path / "run1"))
    db_session.commit()

    def get(**params) -> tuple[list[dict], str]:
        response = api_client.get("/forecasts", params=params, headers=analyst_headers)
        assert response.status_code == 200, response.text
        return response.json(), response.headers["X-Total-Count"]

    rows, total = get(store_id="CA_1", limit=5)
    assert total == "14" and len(rows) == 5
    assert all(row["store_id"] == "CA_1" for row in rows)

    rows, total = get(item_id="FOODS_3_090")
    assert total == "14"  # the same item in two stores

    rows, total = get(series_id=SERIES[2][0], date_from="2016-04-27", date_to="2016-04-28")
    assert total == "2"
    assert [row["step"] for row in rows] == [3, 4]
    assert rows[0]["forecast"] <= rows[0]["upper"]

    _, total = get(run_id=run.id)
    assert total == "21"


@pytest.mark.parametrize(
    ("params", "expected_status"),
    [
        ({"run_id": 999_999}, 404),
        ({"date_from": "2016-05-02", "date_to": "2016-05-01"}, 422),
        ({"limit": 1001}, 422),
    ],
)
def test_forecast_query_errors(
    api_client: TestClient,
    db_session: Session,
    analyst_headers: dict[str, str],
    tmp_path: Path,
    params: dict,
    expected_status: int,
) -> None:
    import_forecasts(db_session, write_forecast_folder(tmp_path / "run1"))
    db_session.commit()

    assert api_client.get("/forecasts", params=params, headers=analyst_headers).status_code == (
        expected_status
    )
