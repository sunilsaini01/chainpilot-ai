"""Running and storing copilot investigations (used by the API and the CLI)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.config import get_settings
from app.copilot.graph import InvestigationResult, investigate
from app.copilot.model import ChatModel, CompatibleChatModel
from app.models import AgentRun, User


class CopilotNotConfiguredError(Exception):
    """The chosen provider's key or model name is missing."""


def configured_model() -> ChatModel:
    """The model of the provider named by LLM_PROVIDER. The key is never logged or returned."""
    settings = get_settings()
    provider = settings.llm_provider
    key = getattr(settings, f"{provider}_api_key").get_secret_value()
    model = getattr(settings, f"{provider}_model")
    if not key or not model:
        prefix = provider.upper()
        raise CopilotNotConfiguredError(
            f"The AI copilot is not configured: set {prefix}_API_KEY and {prefix}_MODEL "
            f"(LLM_PROVIDER={provider})"
        )
    return CompatibleChatModel(provider=provider, api_key=key, model=model)


def runs_in_last_hour(session: Session, user_id: int) -> int:
    since = datetime.now(UTC) - timedelta(hours=1)
    return session.execute(
        select(func.count())
        .select_from(AgentRun)
        .where(AgentRun.created_by_user_id == user_id, AgentRun.created_at >= since)
    ).scalar_one()


def run_and_save(session: Session, model: ChatModel, question: str, actor: User | None) -> AgentRun:
    """Investigate, store the run with its trace, and audit it. Does not commit.

    The tools use the same database as `session`, each in its own read-only
    transaction.
    """
    result: InvestigationResult = investigate(model, session.get_bind(), question)
    run = AgentRun(
        question=question.strip(),
        status=result.status,
        answer=result.answer,
        trace=result.trace,
        model=model.name,
        model_calls=result.model_calls,
        tool_calls=result.tool_calls,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        duration_ms=result.duration_ms,
        error=result.error,
        created_by_user_id=actor.id if actor else None,
    )
    session.add(run)
    session.flush()
    record_event(
        session,
        "agent.investigated",
        "agent_run",
        run.id,
        actor=actor,
        details={
            "status": run.status,
            "grounded": bool(run.answer and run.answer.get("grounded")),
            "model_calls": run.model_calls,
            "tool_calls": run.tool_calls,
            "tokens": run.prompt_tokens + run.completion_tokens,
        },
    )
    return run
