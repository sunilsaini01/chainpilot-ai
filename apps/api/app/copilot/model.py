"""The chat model behind the copilot, behind one small interface.

`OpenAIChatModel` calls OpenAI's Chat Completions API (decision D-049). Tests use
`ScriptedModel`, which replays prepared replies, so the test suite and CI never
call a paid API.

Messages are plain dicts in the Chat Completions format, so the graph code does
not depend on the OpenAI package.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import OpenAI

TIMEOUT_SECONDS = 60
MAX_RETRIES = 2  # the OpenAI client retries rate limits and network errors itself


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
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
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


class OpenAIChatModel:
    def __init__(self, api_key: str, model: str) -> None:
        self.name = model
        self._client = OpenAI(api_key=api_key, timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES)

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> ModelReply:
        request: dict[str, Any] = {"model": self.name, "messages": messages}
        if tools:
            request["tools"] = [{"type": "function", "function": spec} for spec in tools]
        if schema:
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema["name"], "schema": schema["schema"], "strict": True},
            }
        response = self._client.chat.completions.create(**request)
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
