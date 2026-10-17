"""The copilot's LangGraph investigation, with scripted models (no network, no cost).

Needs RUN_DB_TESTS=1 except the adapter and question tests.
"""

import json
import os
from collections.abc import Callable
from types import SimpleNamespace

import httpx2
import openai
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app import cli
from app.config import Settings
from app.copilot import graph, service, tools
from app.copilot.model import (
    PROVIDER_URLS,
    CompatibleChatModel,
    ModelReply,
    RequestTooLargeError,
    ScriptedModel,
    ToolCall,
    json_reply,
    tool_reply,
)
from app.main import app
from app.models import AgentRun, AuditEvent, Role, User
from app.policies_service import sync_policies
from app.routes import agents
from tests.conftest import login

needs_db = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="set RUN_DB_TESTS=1 with Postgres running"
)


def route(name: str) -> ModelReply:
    return json_reply({"next": name, "reason": f"need {name}"})


def answer(text: str, citations: list[str]) -> ModelReply:
    return json_reply({"answer": text, "citations": citations, "limitations": "simulated data"})


SUPPLIER_SCRIPT = [
    route("supplier"),
    tool_reply(("supplier_performance", {"supplier_code": "SYN-SUP04"})),
    ModelReply(content="SYN-SUP04 is at risk with overdue order SYN-PO-000901."),
    route("finish"),
]


# --- Without a database ---------------------------------------------------------------


def test_questions_must_be_short_and_not_empty() -> None:
    for question in ["", "   ", "x" * 501]:
        with pytest.raises(ValueError, match="1 to 500 characters"):
            graph.investigate(ScriptedModel([]), None, question)


def fake_client(monkeypatch, model: CompatibleChatModel, replies: list) -> list[dict]:
    """Replace the HTTP client: each call takes the next reply (or raises it)."""
    sent: list[dict] = []

    def create(**request):
        sent.append(request)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    completions = SimpleNamespace(create=create)
    monkeypatch.setattr(
        model, "_client", SimpleNamespace(chat=SimpleNamespace(completions=completions))
    )
    return sent


def response(content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def test_adapter_builds_the_request_and_reads_the_reply(monkeypatch) -> None:
    model = CompatibleChatModel("groq", api_key="gsk-test-not-used", model="test-model")
    broken = SimpleNamespace(
        id="c1", function=SimpleNamespace(name="find_products", arguments='{"query": "rug"')
    )
    sent = fake_client(monkeypatch, model, [response(tool_calls=[broken])])

    reply = model.complete(
        [{"role": "user", "content": "hi"}],
        tools=[{"name": "find_products", "description": "d", "parameters": {}}],
        schema=graph.ROUTE_SCHEMA,
    )

    assert (model.name, sent[0]["model"]) == ("groq:test-model", "test-model")
    assert sent[0]["tools"] == [
        {
            "type": "function",
            "function": {"name": "find_products", "description": "d", "parameters": {}},
        }
    ]
    assert sent[0]["response_format"]["json_schema"]["strict"] is True
    assert reply.tool_calls[0].arguments is None  # unreadable arguments are flagged, not guessed
    assert (reply.prompt_tokens, reply.completion_tokens) == (11, 7)


def test_providers_use_their_own_addresses() -> None:
    groq = CompatibleChatModel("groq", api_key="k", model="m")
    gemini = CompatibleChatModel("gemini", api_key="k", model="m")
    assert str(groq._client.base_url).startswith("https://api.groq.com/openai/v1")
    assert str(gemini._client.base_url).startswith(
        "https://generativelanguage.googleapis.com/v1beta/openai"
    )
    assert sorted(PROVIDER_URLS) == ["gemini", "groq"]  # OpenAI itself is not a provider
    with pytest.raises(ValueError, match="unknown provider"):
        CompatibleChatModel("openai", api_key="k", model="m")


def test_models_without_json_schemas_fall_back_to_json_mode(monkeypatch) -> None:
    model = CompatibleChatModel("groq", api_key="k", model="small-model")
    request = httpx2.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    rejected = openai.BadRequestError(
        "response_format json_schema is not supported",
        response=httpx2.Response(400, request=request),
        body=None,
    )
    sent = fake_client(
        monkeypatch,
        model,
        [rejected, response(content='{"next": "finish", "reason": "ok"}'), response(content="{}")],
    )
    messages = [{"role": "user", "content": "route"}]

    first = model.complete(messages, schema=graph.ROUTE_SCHEMA)
    model.complete(messages, schema=graph.ROUTE_SCHEMA)  # stays in JSON mode, no new rejection

    assert first.content == '{"next": "finish", "reason": "ok"}'
    assert sent[0]["response_format"]["type"] == "json_schema"
    assert [r["response_format"]["type"] for r in sent[1:]] == ["json_object", "json_object"]
    assert '"enum"' in sent[1]["messages"][-1]["content"]  # the schema is written into the prompt
    assert messages == [{"role": "user", "content": "route"}]  # the caller's list is not changed


def test_other_bad_requests_are_not_hidden(monkeypatch) -> None:
    model = CompatibleChatModel("gemini", api_key="k", model="m")
    request = httpx2.Request("POST", "https://example.invalid")
    rejected = openai.BadRequestError(
        "bad tools", response=httpx2.Response(400, request=request), body=None
    )
    fake_client(monkeypatch, model, [rejected])

    with pytest.raises(openai.BadRequestError):
        model.complete([{"role": "user", "content": "x"}], tools=[{"name": "t", "parameters": {}}])


@pytest.mark.parametrize(
    ("provider", "variables"),
    [("groq", "GROQ_API_KEY and GROQ_MODEL"), ("gemini", "GEMINI_API_KEY and GEMINI_MODEL")],
)
def test_the_chosen_provider_needs_its_own_key_and_model(monkeypatch, provider, variables) -> None:
    # A key for the other provider does not count.
    other = "gemini" if provider == "groq" else "groq"
    settings = Settings(llm_provider=provider, **{f"{other}_api_key": "k", f"{other}_model": "m"})
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    with pytest.raises(service.CopilotNotConfiguredError, match=variables):
        service.configured_model()

    complete = Settings(
        llm_provider=provider, **{f"{provider}_api_key": "k", f"{provider}_model": "m1"}
    )
    monkeypatch.setattr(service, "get_settings", lambda: complete)
    assert service.configured_model().name == f"{provider}:m1"


# --- Investigations with a database ------------------------------------------------------


@needs_db
def test_supplier_question_is_answered_with_verified_citations(
    db_engine: Engine, world: dict
) -> None:
    model = ScriptedModel(
        [
            *SUPPLIER_SCRIPT,
            answer(
                "SYN-SUP04 is at risk; SYN-PO-000901 is overdue.",
                ["supplier:SYN-SUP04", "purchase_order:SYN-PO-000901"],
            ),
        ]
    )

    result = graph.investigate(model, db_engine, "Which supplier is unreliable?")

    assert result.status == "completed", result.error
    assert result.answer["grounded"] is True
    assert result.answer["citations"] == ["supplier:SYN-SUP04", "purchase_order:SYN-PO-000901"]
    assert (result.model_calls, result.tool_calls) == (5, 1)
    tool_step = next(step for step in result.trace if step.get("tool"))
    assert (tool_step["node"], tool_step["tool"], tool_step["ok"]) == (
        "supplier",
        "supplier_performance",
        True,
    )
    # The supplier specialist was offered only its own tools, and every prompt carries the rules.
    offered = {spec["name"] for spec in model.requests[1]["tools"]}
    assert offered == {"supplier_performance", "purchase_orders"}
    assert all(
        "You are read-only" in request["messages"][0]["content"] for request in model.requests
    )


@needs_db
def test_invented_citations_are_removed_after_one_retry(db_engine: Engine, world: dict) -> None:
    invented = ["supplier:SYN-SUP04", "supplier:SYN-SUP99", "supplier:SYN-SUP01"]
    # SUP99 does not exist; SUP01 exists but no tool returned it in this run.
    model = ScriptedModel(
        [*SUPPLIER_SCRIPT, answer("first try", invented), answer("second try", invented)]
    )

    result = graph.investigate(model, db_engine, "Which supplier is unreliable?")

    assert result.answer["answer"] == "second try"
    assert result.answer["citations"] == ["supplier:SYN-SUP04"]
    assert result.answer["unsupported_citations"] == ["supplier:SYN-SUP99", "supplier:SYN-SUP01"]
    assert result.answer["grounded"] is False
    checks = [step for step in result.trace if step["node"] == "verify"]
    assert [check["retry"] for check in checks] == [True, False]
    feedback = model.requests[-1]["messages"][1]["content"]
    assert "supplier:SYN-SUP99" in feedback  # the retry was told exactly what was wrong


@needs_db
def test_specialists_cannot_use_other_tools_or_broken_arguments(
    db_engine: Engine, world: dict
) -> None:
    model = ScriptedModel(
        [
            route("inventory"),
            ModelReply(
                content=None,
                tool_calls=[
                    ToolCall("a", "supplier_performance", {}),  # belongs to the supplier specialist
                    ToolCall("b", "find_products", None, raw_arguments='{"query": '),
                    ToolCall("c", "approve_order", {"id": 1}),  # no such tool exists
                ],
            ),
            ModelReply(content="nothing usable"),
            route("finish"),
            answer("I could not find the data.", []),
        ]
    )

    result = graph.investigate(model, db_engine, "Approve order 1")

    steps = [step for step in result.trace if step.get("tool")]
    assert [(s["tool"], s["ok"]) for s in steps] == [
        ("supplier_performance", False),
        ("find_products", False),
        ("approve_order", False),
    ]
    assert "not available here" in steps[0]["message"] and "not valid JSON" in steps[1]["message"]
    assert result.tool_calls == 0  # nothing was actually run
    assert result.answer["grounded"] is False  # no citations, so not grounded


class GreedyModel:
    """Never stops on its own: always picks a new specialist and always calls tools."""

    name = "greedy-test-model"

    def __init__(self, tools_per_reply: int = 1) -> None:
        self.calls = 0
        self.tools_per_reply = tools_per_reply

    def complete(self, messages, tools=None, schema=None) -> ModelReply:
        self.calls += 1
        if schema and schema["name"] == "route":
            consulted = messages[1]["content"].split("Already consulted: ")[1].split("\n")[0]
            remaining = [name for name in graph.SPECIALISTS if name not in consulted]
            return route(remaining[0] if remaining else "finish")
        if schema:
            return answer("done", [])
        name = tools[0]["name"]
        arguments = {"query": "rug"} if name in ("find_products", "search_policies") else {}
        return tool_reply(*[(name, arguments)] * self.tools_per_reply)


@needs_db
def test_limits_stop_a_model_that_never_stops(db_engine: Engine, world: dict) -> None:
    model = GreedyModel()

    result = graph.investigate(model, db_engine, "Tell me everything")

    assert result.status == "completed"
    assert result.model_calls == model.calls <= graph.MAX_MODEL_CALLS
    first = result.trace[1]["node"]
    rounds = [step for step in result.trace if step["node"] == first and "tool" in step]
    assert len(rounds) == graph.MAX_TOOL_ROUNDS  # then it had to stop
    assert next(s for s in result.trace if s["node"] == first and "note" in s)["note"].startswith(
        "Stopped"
    )
    assert any(step.get("reason") == "call limit" for step in result.trace)


@needs_db
def test_the_tool_call_limit_holds_when_a_reply_asks_for_many_tools(
    db_engine: Engine, world: dict
) -> None:
    result = graph.investigate(GreedyModel(tools_per_reply=5), db_engine, "Tell me everything")

    assert result.tool_calls == graph.MAX_TOOL_CALLS
    refused = [s for s in result.trace if s.get("message") == "Tool call limit reached"]
    assert refused


class QuickModel(GreedyModel):
    """Every specialist reports at once, without tools."""

    def complete(self, messages, tools=None, schema=None) -> ModelReply:
        if tools:
            self.calls += 1
            return ModelReply(content="nothing to add")
        return super().complete(messages, tools, schema)


@needs_db
def test_no_extra_call_once_every_specialist_has_reported(db_engine: Engine, world: dict) -> None:
    result = graph.investigate(QuickModel(), db_engine, "Tell me everything")

    # 4 routing calls + 4 notes + 1 answer; no fifth routing call.
    assert result.model_calls == 9
    assert result.trace[-3] == {
        "node": "supervisor",
        "next": "finish",
        "reason": "all specialists consulted",
    }


@needs_db
def test_a_tool_citation_that_names_no_record_is_not_accepted(
    db_engine: Engine, world: dict, monkeypatch
) -> None:
    # Defence in depth: even a citation a tool returned must name a real record.
    original = tools.TOOLS["supplier_performance"]

    def with_bad_citation(session, args, today):
        result = original.function(session, args, today)
        return result.model_copy(update={"citations": [*result.citations, "supplier:SYN-SUP99"]})

    monkeypatch.setitem(
        tools.TOOLS,
        "supplier_performance",
        tools.Tool(original.name, original.description, original.input_model, with_bad_citation),
    )
    model = ScriptedModel(
        [*SUPPLIER_SCRIPT, answer("a", ["supplier:SYN-SUP99"]), answer("b", ["supplier:SYN-SUP99"])]
    )

    result = graph.investigate(model, db_engine, "Which supplier is unreliable?")

    assert result.answer["unsupported_citations"] == ["supplier:SYN-SUP99"]
    assert result.answer["grounded"] is False


@needs_db
def test_a_repeated_specialist_or_unreadable_reply_finishes(db_engine: Engine, world: dict) -> None:
    model = ScriptedModel(
        [
            *SUPPLIER_SCRIPT[:3],
            route("supplier"),  # again: treated as finish
            ModelReply(content="this is not JSON"),  # unreadable answer
        ]
    )

    result = graph.investigate(model, db_engine, "Which supplier is unreliable?")

    assert [s["next"] for s in result.trace if s["node"] == "supervisor"] == ["supplier", "finish"]
    assert result.answer["citations"] == [] and result.answer["grounded"] is False


@needs_db
def test_model_errors_are_recorded_not_raised(db_engine: Engine, world: dict) -> None:
    class Broken:
        name = "broken"

        def complete(self, messages, tools=None, schema=None):
            raise ConnectionError("network down")

    result = graph.investigate(Broken(), db_engine, "Anything")

    assert (result.status, result.answer) == ("failed", None)
    assert result.error == "ConnectionError: network down"


# --- API and CLI -----------------------------------------------------------------------


@pytest.fixture
def analyst_headers(api_client: TestClient, make_user: Callable[..., User]) -> dict[str, str]:
    make_user(Role.ANALYST)
    return login(api_client, "analyst@example.com")


def use_model(model) -> None:
    app.dependency_overrides[agents.chat_model] = lambda: model


@needs_db
def test_investigate_api_stores_the_run_with_its_trace(
    api_client: TestClient, analyst_headers: dict[str, str], db_session: Session, world: dict
) -> None:
    assert api_client.post("/agents/investigate", json={"question": "x"}).status_code == 401
    use_model(
        ScriptedModel([*SUPPLIER_SCRIPT, answer("SYN-SUP04 is at risk.", ["supplier:SYN-SUP04"])])
    )

    response = api_client.post(
        "/agents/investigate",
        json={"question": "Which supplier is unreliable?"},
        headers=analyst_headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["status"], body["model"], body["answer"]["grounded"]) == (
        "completed",
        "scripted-test-model",
        True,
    )
    assert body["trace"][0] == {"node": "supervisor", "next": "supplier", "reason": "need supplier"}
    again = api_client.get(f"/agents/runs/{body['id']}", headers=analyst_headers).json()
    assert again["answer"] == body["answer"]
    assert api_client.get("/agents/runs", headers=analyst_headers).headers["X-Total-Count"] == "1"
    assert api_client.get("/agents/runs/999", headers=analyst_headers).status_code == 404
    event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "agent.investigated")
    ).scalar_one()
    assert event.details["grounded"] is True
    assert (
        api_client.post(
            "/agents/investigate", json={"question": ""}, headers=analyst_headers
        ).status_code
        == 422
    )


@needs_db
def test_hourly_limit_and_missing_configuration(
    api_client: TestClient, analyst_headers: dict[str, str], world: dict, monkeypatch
) -> None:
    monkeypatch.setattr(agents, "get_settings", lambda: Settings(copilot_runs_per_hour=1))
    use_model(ScriptedModel([*SUPPLIER_SCRIPT, answer("ok", ["supplier:SYN-SUP04"])]))
    question = {"question": "Which supplier is unreliable?"}

    assert (
        api_client.post("/agents/investigate", json=question, headers=analyst_headers).status_code
        == 201
    )
    second = api_client.post("/agents/investigate", json=question, headers=analyst_headers)
    assert (second.status_code, second.headers["Retry-After"]) == (429, "3600")

    app.dependency_overrides.pop(agents.chat_model)  # use the real dependency, with no key set
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: Settings(llm_provider="groq", groq_api_key="", groq_model=""),
    )
    response = api_client.post("/agents/investigate", json=question, headers=analyst_headers)
    assert response.status_code == 503
    assert "GROQ_API_KEY" in response.json()["detail"]


@needs_db
def test_investigate_command(
    db_engine: Engine, db_session: Session, world: dict, monkeypatch, capsys
) -> None:
    sync_policies(db_session)
    db_session.commit()
    monkeypatch.setattr(cli, "get_engine", lambda: db_engine)
    monkeypatch.setattr(
        cli,
        "configured_model",
        lambda: ScriptedModel(
            [
                route("decision"),
                tool_reply(("search_policies", {"query": "who approves purchase orders"})),
                ModelReply(content="Managers approve."),
                route("finish"),
                answer(
                    "Only managers or administrators approve.", ["policy:approvals#who-approves"]
                ),
            ]
        ),
    )

    assert cli.main(["investigate", "Who approves purchase orders?"]) == 0
    out = capsys.readouterr().out
    assert "completed, grounded=True" in out and "policy:approvals#who-approves" in out
    run = db_session.execute(select(AgentRun)).scalar_one()
    assert run.created_by_user_id is None and json.dumps(run.trace)

    monkeypatch.setattr(cli, "configured_model", service.configured_model)
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: Settings(llm_provider="groq", groq_api_key="", groq_model=""),
    )
    assert cli.main(["investigate", "x"]) == 1
    assert "not configured" in capsys.readouterr().err


# --- Request size (P5-T4-R3) ----------------------------------------------------------


def test_adapter_turns_a_413_into_request_too_large(monkeypatch) -> None:
    model = CompatibleChatModel("groq", api_key="k", model="m")
    request = httpx2.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    too_large = openai.APIStatusError(
        "Request too large: input tokens per minute",
        response=httpx2.Response(413, request=request),
        body=None,
    )
    fake_client(monkeypatch, model, [too_large])

    with pytest.raises(RequestTooLargeError, match="Request too large"):
        model.complete([{"role": "user", "content": "x"}])


@needs_db
def test_answer_retries_once_with_half_the_evidence(db_engine: Engine, world: dict) -> None:
    model = ScriptedModel(
        [
            *SUPPLIER_SCRIPT,
            RequestTooLargeError("413"),
            answer("SYN-SUP04 is at risk.", ["supplier:SYN-SUP04"]),
        ]
    )

    result = graph.investigate(model, db_engine, "Which supplier is unreliable?")

    assert result.status == "completed" and result.answer["grounded"] is True
    assert {"node": "answer", "retry": "request too large: half the evidence"} in result.trace


@needs_db
def test_a_second_refusal_fails_the_run_cleanly(db_engine: Engine, world: dict) -> None:
    model = ScriptedModel(
        [*SUPPLIER_SCRIPT, RequestTooLargeError("413"), RequestTooLargeError("413")]
    )

    result = graph.investigate(model, db_engine, "Which supplier is unreliable?")

    assert result.status == "failed" and result.error.startswith("RequestTooLargeError")


@needs_db
def test_a_specialist_stops_but_the_run_goes_on(db_engine: Engine, world: dict) -> None:
    model = ScriptedModel(
        [
            route("supplier"),
            tool_reply(("supplier_performance", {"supplier_code": "SYN-SUP04"})),
            RequestTooLargeError("413"),
            route("finish"),
            answer("SYN-SUP04 is at risk.", ["supplier:SYN-SUP04"]),
        ]
    )

    result = graph.investigate(model, db_engine, "Which supplier is unreliable?")

    note = next(
        step["note"] for step in result.trace if step["node"] == "supplier" and "note" in step
    )
    assert note == "Stopped: the provider refused the request as too large."
    assert result.status == "completed" and result.answer["grounded"] is True  # evidence was kept


@needs_db
def test_what_the_model_sees_stays_within_the_size_limits(
    db_engine: Engine, world: dict, monkeypatch
) -> None:
    original = tools.TOOLS["supplier_performance"]

    def huge(session, args, today):
        result = original.function(session, args, today)
        return result.model_copy(update={"data": result.data * 200})  # far over any limit

    monkeypatch.setitem(
        tools.TOOLS,
        "supplier_performance",
        tools.Tool(original.name, original.description, original.input_model, huge),
    )
    model = ScriptedModel([*SUPPLIER_SCRIPT, answer("ok", ["supplier:SYN-SUP04"])])

    result = graph.investigate(model, db_engine, "Which supplier is unreliable?")

    tool_message = model.requests[2]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert len(tool_message["content"]) <= graph.MAX_RESULT_CHARS + len(" ... (truncated)")
    answer_prompt = model.requests[-1]["messages"][1]["content"]
    shown = answer_prompt.split("Tool results:\n", 1)[1]
    assert len(shown) <= graph.MAX_EVIDENCE_CHARS + len(" ... (truncated)")
    assert len(result.evidence[0]["data"]) == 200  # one supplier x 200: the full data is kept
