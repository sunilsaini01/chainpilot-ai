"""Delivery-risk import and API tests (RUN_DB_TESTS=1)."""

import csv
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import cli
from app.delivery_risk_import import CSV_COLUMNS, DeliveryRiskImportError, import_delivery_risk
from app.models import AuditEvent, DeliveryRiskRun, DeliveryRiskScore, Role, User
from tests.conftest import login

DATASET = "Olist Brazilian E-Commerce (public data); not ChainPilot's simulated suppliers"
REASONS = json.dumps([{"feature": "distance_km", "value": 2808.4, "effect": 1.27}])


def score_row(order: str, day: str, probability: float, percentile: float, tier: str) -> list:
    return [
        order,
        f"{day}T08:00:00",
        f"{day}T15:00:00",
        day,
        probability,
        percentile,
        tier,
        "true" if tier == "high" else "false",
        REASONS,
    ]


DEFAULT_ROWS = [
    score_row("a1", "2018-05-02", 0.62, 1.0, "high"),
    score_row("a2", "2018-05-02", 0.20, 0.8, "medium"),
    score_row("a3", "2018-05-02", 0.05, 0.4, "low"),
    score_row("b1", "2018-05-03", 0.50, 1.0, "high"),
    score_row("b2", "2018-05-03", 0.30, 0.9, "high"),
    score_row("b3", "2018-05-03", 0.02, 0.2, "low"),
]


def write_folder(folder: Path, csv_rows: list[list] | None = None, **manifest_changes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    rows = DEFAULT_ROWS if csv_rows is None else csv_rows
    with open(folder / "scores.csv", "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)
    checksum = hashlib.sha256((folder / "scores.csv").read_bytes()).hexdigest()
    manifest = {
        "run_key": checksum[:16],
        "dataset": DATASET,
        "model": "logistic_regression + recent Platt (monthly retraining)",
        "period_start": "2018-05-02",
        "period_end": "2018-05-03",
        "rows": len(rows),
        "csv_sha256": checksum,
        **manifest_changes,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def count(session: Session, model) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def test_import_loads_every_score_with_reasons(db_session: Session, tmp_path: Path) -> None:
    run = import_delivery_risk(db_session, write_folder(tmp_path / "run1"))
    db_session.commit()

    assert (run.row_count, str(run.period_start), str(run.period_end)) == (
        6,
        "2018-05-02",
        "2018-05-03",
    )
    assert count(db_session, DeliveryRiskScore) == 6
    a1 = db_session.execute(
        select(DeliveryRiskScore).where(DeliveryRiskScore.order_id == "a1")
    ).scalar_one()
    assert (a1.tier, a1.alert) == ("high", True)
    assert a1.reasons[0]["feature"] == "distance_km"


def test_same_file_twice_is_refused(db_session: Session, tmp_path: Path) -> None:
    folder = write_folder(tmp_path / "run1")
    import_delivery_risk(db_session, folder)
    db_session.commit()

    with pytest.raises(DeliveryRiskImportError, match="already imported"):
        import_delivery_risk(db_session, folder)


def _changed(index: int, column: int, value) -> list[list]:
    rows = [list(row) for row in DEFAULT_ROWS]
    rows[index][column] = value
    return rows


@pytest.mark.parametrize(
    ("rows", "manifest_changes", "message"),
    [
        (_changed(0, 4, 1.5), {}, "probability"),
        (_changed(0, 5, 0), {}, "day_percentile"),
        (_changed(0, 6, "urgent"), {}, "unknown tier"),
        (_changed(0, 7, "false"), {}, "exactly for the high tier"),  # high tier without alert
        (_changed(1, 7, "true"), {}, "exactly for the high tier"),  # alert on a medium order
        (_changed(0, 3, "2018-05-03"), {}, "inconsistent"),  # day differs from dispatched_at
        (  # a self-consistent order dispatched after the manifest's period
            [*DEFAULT_ROWS, score_row("z1", "2018-05-09", 0.1, 1.0, "high")],
            {},
            "inconsistent",
        ),
        (_changed(0, 8, "not json"), {}, "unreadable"),
        (DEFAULT_ROWS, {"rows": 99}, "manifest says 99 rows"),
        (DEFAULT_ROWS, {"csv_sha256": "0" * 64}, "checksum"),
    ],
)
def test_invalid_files_are_rejected_before_anything_is_written(
    db_session: Session, tmp_path: Path, rows, manifest_changes, message: str
) -> None:
    folder = write_folder(tmp_path / "bad", csv_rows=rows, **manifest_changes)

    with pytest.raises(DeliveryRiskImportError, match=message):
        import_delivery_risk(db_session, folder)
    db_session.rollback()

    assert count(db_session, DeliveryRiskRun) == 0
    assert count(db_session, DeliveryRiskScore) == 0


def test_cli_import_writes_an_audit_event(
    db_engine,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_engine", lambda: db_engine)

    assert cli.main(["import-delivery-risk", str(write_folder(tmp_path / "run1"))]) == 0
    assert "Imported delivery-risk run" in capsys.readouterr().out
    event = db_session.execute(select(AuditEvent)).scalar_one()
    assert (event.action, event.actor_user_id, event.details["rows"]) == (
        "delivery_risk_run.imported",
        None,
        6,
    )


@pytest.fixture
def analyst_headers(api_client: TestClient, make_user: Callable[..., User]) -> dict[str, str]:
    make_user(Role.ANALYST)
    return login(api_client, "analyst@example.com")


@pytest.fixture
def imported(db_session: Session, tmp_path: Path) -> DeliveryRiskRun:
    run = import_delivery_risk(db_session, write_folder(tmp_path / "run1"))
    db_session.commit()
    return run


def test_delivery_risk_needs_login(api_client: TestClient) -> None:
    for path in [
        "/delivery-risk/runs",
        "/delivery-risk/scores",
        "/delivery-risk/alerts?date=2018-05-02",
    ]:
        assert api_client.get(path).status_code == 401


def test_no_run_yet_is_404(api_client: TestClient, analyst_headers: dict[str, str]) -> None:
    assert api_client.get("/delivery-risk/scores", headers=analyst_headers).status_code == 404


def test_scores_are_labelled_filtered_and_riskiest_first(
    api_client: TestClient, analyst_headers: dict[str, str], imported: DeliveryRiskRun
) -> None:
    def get(**params) -> tuple[list[dict], dict]:
        response = api_client.get("/delivery-risk/scores", params=params, headers=analyst_headers)
        assert response.status_code == 200, response.text
        return response.json(), response.headers

    rows, headers = get()
    assert headers["X-Total-Count"] == "6"
    assert "not ChainPilot's simulated suppliers" in headers["X-Dataset"]
    # Newest day first, riskiest first within a day.
    assert [row["order_id"] for row in rows] == ["b1", "b2", "b3", "a1", "a2", "a3"]
    assert rows[0]["reasons"][0]["feature"] == "distance_km"

    assert [r["order_id"] for r in get(dispatch_date="2018-05-02")[0]] == ["a1", "a2", "a3"]
    assert [r["order_id"] for r in get(tier="high")[0]] == ["b1", "b2", "a1"]
    assert [r["order_id"] for r in get(alert="false")[0]] == ["b3", "a2", "a3"]
    assert [r["order_id"] for r in get(order_id="a2")[0]] == ["a2"]


def test_alerts_for_one_day(
    api_client: TestClient, analyst_headers: dict[str, str], imported: DeliveryRiskRun
) -> None:
    response = api_client.get(
        "/delivery-risk/alerts", params={"date": "2018-05-03"}, headers=analyst_headers
    )

    assert response.status_code == 200
    assert [row["order_id"] for row in response.json()] == ["b1", "b2"]
    assert all(row["alert"] and row["tier"] == "high" for row in response.json())
    assert response.headers["X-Total-Count"] == "2"


@pytest.mark.parametrize(
    ("path", "params", "expected_status"),
    [
        ("/delivery-risk/scores", {"tier": "urgent"}, 422),
        ("/delivery-risk/scores", {"run_id": 999_999}, 404),
        ("/delivery-risk/alerts", {}, 422),  # the date is required
        ("/delivery-risk/alerts", {"date": "not-a-date"}, 422),
    ],
)
def test_query_errors(
    api_client: TestClient,
    analyst_headers: dict[str, str],
    imported: DeliveryRiskRun,
    path: str,
    params: dict,
    expected_status: int,
) -> None:
    assert (
        api_client.get(path, params=params, headers=analyst_headers).status_code == expected_status
    )
