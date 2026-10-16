"""Policy documents: parsing (no database), loading and search (RUN_DB_TESTS=1)."""

import os
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app import cli
from app.models import AuditEvent, DocumentChunk, Role, User
from app.policies_service import (
    DEFAULT_FOLDER,
    MAX_CHUNK_CHARS,
    PolicyError,
    parse_policy,
    search_policies,
    slugify,
    sync_policies,
)
from app.policy_eval import evaluate
from tests.conftest import login

needs_db = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="set RUN_DB_TESTS=1 with Postgres running"
)

EXAMPLE = """# Example policy

> SIMULATED.

## Ordering rules

Orders follow the minimum order quantity.

## Approvals

Managers approve purchase orders.
"""


# --- Parsing ---------------------------------------------------------------------


def test_each_section_is_one_chunk_with_a_slug() -> None:
    title, chunks = parse_policy(EXAMPLE)

    assert title == "Example policy"
    assert [(c.section, c.section_slug) for c in chunks] == [
        ("Overview", "overview"),
        ("Ordering rules", "ordering-rules"),
        ("Approvals", "approvals"),
    ]
    assert chunks[1].content == "Orders follow the minimum order quantity."


def test_long_sections_are_split_at_blank_lines() -> None:
    paragraph = "word " * 200  # about 1,000 characters
    title, chunks = parse_policy(f"# T\n\n## Long\n\n{paragraph}\n\n{paragraph}\n\n{paragraph}\n")

    assert [c.section_slug for c in chunks] == ["long", "long", "long"]
    assert all(len(c.content) <= MAX_CHUNK_CHARS for c in chunks)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("no title\n## A\nx", "must start"),
        ("# T\n## Same name\nx\n## Same  name!\ny", "same name"),
    ],
)
def test_bad_policies_are_rejected(text: str, message: str) -> None:
    with pytest.raises(PolicyError, match=message):
        parse_policy(text)


def test_slugify() -> None:
    assert slugify("When the system cannot plan") == "when-the-system-cannot-plan"
    assert slugify("Space at the receiving site!") == "space-at-the-receiving-site"


def test_shipped_policies_are_labelled_and_parse() -> None:
    files = sorted(DEFAULT_FOLDER.glob("*.md"))
    assert len(files) == 6
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "SIMULATED COMPANY POLICY" in text, path.name
        parse_policy(text)


# --- Loading and search ------------------------------------------------------------


def write(folder: Path, name: str, text: str) -> None:
    folder.mkdir(exist_ok=True)
    (folder / f"{name}.md").write_text(text, encoding="utf-8")


def count(session: Session) -> int:
    return session.execute(select(func.count()).select_from(DocumentChunk)).scalar_one()


@needs_db
def test_sync_adds_skips_updates_and_removes(db_session: Session, tmp_path: Path) -> None:
    folder = tmp_path / "policies"
    write(folder, "example", EXAMPLE)
    write(folder, "other", "# Other\n\n## Only\n\nText.\n")

    first = sync_policies(db_session, folder)
    db_session.commit()
    assert (first["added"], count(db_session)) == (
        ["example", "other"],
        4,
    )  # 3 sections + 1 (no overview text)

    assert sync_policies(db_session, folder)["unchanged"] == ["example", "other"]

    write(
        folder,
        "example",
        EXAMPLE.replace("## Approvals\n\nManagers approve", "## Approvals\n\nAdmins approve"),
    )
    (folder / "other.md").unlink()
    third = sync_policies(db_session, folder)
    db_session.commit()
    assert (third["updated"], third["removed"]) == (["example"], ["other"])
    contents = db_session.execute(select(DocumentChunk.content)).scalars().all()
    assert any("Admins approve" in c for c in contents)
    assert not any("Managers approve" in c for c in contents)
    assert count(db_session) == 3


@needs_db
def test_sync_rejects_bad_folders_and_names(db_session: Session, tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match="no .md policy files"):
        sync_policies(db_session, tmp_path)
    write(tmp_path, "Bad_Name", EXAMPLE)
    with pytest.raises(PolicyError, match="lower-case"):
        sync_policies(db_session, tmp_path)


@needs_db
def test_search_matches_any_word_with_stemming_and_ranks(
    db_session: Session, tmp_path: Path
) -> None:
    write(tmp_path, "example", EXAMPLE)
    sync_policies(db_session, tmp_path)

    # "approval" (singular) finds "approve" and "Approvals" through stemming.
    hits = search_policies(db_session, "Who gives approval for purchase orders?")
    assert hits[0].citation == "policy:example#approvals"
    assert "<b>" in hits[0].snippet
    # Words from two sections: the section with more of them comes first.
    hits = search_policies(db_session, "minimum order quantity and managers")
    assert [hit.section for hit in hits[:2]] == ["Ordering rules", "Approvals"]
    assert hits[0].rank > hits[1].rank


@needs_db
@pytest.mark.parametrize(
    "query", ["zebra giraffe", "the and of", "'; DROP TABLE x; --", "a & b | !c"]
)
def test_unmatched_or_odd_queries_return_nothing_or_safely(
    db_session: Session, tmp_path: Path, query: str
) -> None:
    write(tmp_path, "example", EXAMPLE)
    sync_policies(db_session, tmp_path)

    assert search_policies(db_session, query) == []


@needs_db
@pytest.mark.parametrize("query", ["", "   ", "x" * 201])
def test_empty_or_long_query_is_rejected(db_session: Session, query: str) -> None:
    with pytest.raises(PolicyError, match="1 to 200 characters"):
        search_policies(db_session, query)


@needs_db
def test_load_policies_command_uses_the_shipped_folder(
    db_engine: Engine,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_engine", lambda: db_engine)

    assert cli.main(["load-policies"]) == 0
    assert "Policies: 6 added, 0 updated, 0 unchanged, 0 removed" in capsys.readouterr().out
    assert cli.main(["load-policies"]) == 0
    assert "0 added, 0 updated, 6 unchanged" in capsys.readouterr().out
    event = db_session.execute(select(AuditEvent).order_by(AuditEvent.id)).scalars().first()
    assert event.action == "policies.loaded" and len(event.details["added"]) == 6
    assert cli.main(["load-policies", "does-not-exist"]) == 1


# --- API -------------------------------------------------------------------------


@pytest.fixture
def analyst_headers(api_client: TestClient, make_user: Callable[..., User]) -> dict[str, str]:
    make_user(Role.ANALYST)
    return login(api_client, "analyst@example.com")


@needs_db
def test_policy_api(
    api_client: TestClient, analyst_headers: dict[str, str], db_session: Session
) -> None:
    assert api_client.get("/policies/search?q=x").status_code == 401
    sync_policies(db_session)
    db_session.commit()

    documents = api_client.get("/policies", headers=analyst_headers).json()
    assert [d["document"] for d in documents] == [
        "approvals",
        "data-and-ai-use",
        "receiving",
        "replenishment",
        "stock-transfers",
        "supplier-performance",
    ]
    hits = api_client.get(
        "/policies/search",
        params={"q": "minimum order quantity pack size"},
        headers=analyst_headers,
    ).json()
    assert hits[0]["citation"] == "policy:replenishment#order-quantities"
    assert api_client.get("/policies/search?q=", headers=analyst_headers).status_code == 422
    assert (
        api_client.get("/policies/search?q=x&limit=21", headers=analyst_headers).status_code == 422
    )


@needs_db
def test_retrieval_check_still_finds_every_direct_question(db_session: Session) -> None:
    # Regression guard for the pre-registered check (docs/results/p5_policy_retrieval.json).
    # Paraphrased questions are not asserted: keyword search is known to miss them.
    sync_policies(db_session)

    report = evaluate(db_session)

    assert len(report["questions"]) == 12
    assert report["summary"]["direct_hit_at_3"] == "9/9"
