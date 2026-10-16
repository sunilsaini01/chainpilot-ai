"""The chat model behind the copilot, behind one small interface.

Providers (decision D-052): Groq and Google Gemini, chosen with LLM_PROVIDER.
Both offer an OpenAI-compatible API, so one adapter serves both; the `openai`
Python package is used only as the HTTP client for that protocol. No request
goes to OpenAI.

Tests use `ScriptedModel`, which replays prepared replies, so the test suite and
CI never call a paid or rate-limited API.

Messages are plain dicts in the Chat Completions format, so the graph code does
not depend on any provider.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import BadRequestError, OpenAI

TIMEOUT_SECONDS = 60
MAX_RETRIES = 2  # the client retries rate limits (common on free tiers) and network errors
PROVIDER_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] | None  # None if the model's arguments were not valid JSON
    raw_arguments: str = ""


@dataclass(frozen=True)
class ModelReply:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def as_message(self) -> dict[str, Any]:
        """The assistant message to append to the conversation."""
        # An empty string rather than None: some compatible APIs reject a null content.
        message: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.raw_arguments or json.dumps(call.arguments or {}),
                    },
                }
                for call in self.tool_calls
            ]
        return message


class ChatModel(Protocol):
    name: str

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> ModelReply:
        """One model call. `tools` enables function calling; `schema` forces JSON output."""


def _parse_arguments(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


class CompatibleChatModel:
    """A Groq or Gemini model through its OpenAI-compatible Chat Completions API.

    Structured output: a strict JSON schema is requested first. Some models on
    these providers only support plain JSON mode; if the provider rejects the
    schema request, this model switches to JSON mode (with the schema written into
    the prompt) for the rest of its life. The graph checks every reply anyway.
    """

    def __init__(self, provider: str, api_key: str, model: str) -> None:
        if provider not in PROVIDER_URLS:
            raise ValueError(f"unknown provider {provider!r}; use one of {sorted(PROVIDER_URLS)}")
        self.name = f"{provider}:{model}"
        self.model = model
        self.strict_json = True
        self._client = OpenAI(
            api_key=api_key,
            base_url=PROVIDER_URLS[provider],
            timeout=TIMEOUT_SECONDS,
            max_retries=MAX_RETRIES,
        )

    def _request(self, messages, tools, schema) -> dict[str, Any]:
        request: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            request["tools"] = [{"type": "function", "function": spec} for spec in tools]
        if schema and self.strict_json:
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema["name"], "schema": schema["schema"], "strict": True},
            }
        elif schema:
            request["response_format"] = {"type": "json_object"}
            request["messages"] = [
                *messages,
                {
                    "role": "system",
                    "content": "Reply with one JSON object that matches this JSON schema: "
                    + json.dumps(schema["schema"]),
                },
            ]
        return request

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> ModelReply:
        try:
            response = self._client.chat.completions.create(
                **self._request(messages, tools, schema)
            )
        except BadRequestError:
            if not (schema and self.strict_json):
                raise
            self.strict_json = False  # this model does not take JSON schemas: use JSON mode
            response = self._client.chat.completions.create(
                **self._request(messages, tools, schema)
            )
        message = response.choices[0].message
        calls = [
            ToolCall(
                id=call.id,
                name=call.function.name,
                arguments=_parse_arguments(call.function.arguments),
                raw_arguments=call.function.arguments or "",
            )
            for call in (message.tool_calls or [])
        ]
        usage = response.usage
        return ModelReply(
            content=message.content,
            tool_calls=calls,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )


class ScriptedModel:
    """Test double: returns the prepared replies in order and records every request."""

    def __init__(self, replies: list[ModelReply], name: str = "scripted-test-model") -> None:
        self.name = name
        self._replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> ModelReply:
        self.requests.append({"messages": messages, "tools": tools, "schema": schema})
        if not self._replies:
            raise AssertionError("the scripted model ran out of replies")
        return self._replies.pop(0)


def json_reply(value: dict[str, Any]) -> ModelReply:
    """A structured-output reply (for scripting tests)."""
    return ModelReply(content=json.dumps(value))


def tool_reply(*calls: tuple[str, dict[str, Any]]) -> ModelReply:
    """A reply that asks for tool calls (for scripting tests)."""
    return ModelReply(
        content=None,
        tool_calls=[ToolCall(f"call_{i}", name, args) for i, (name, args) in enumerate(calls)],
    )
