"""The tool loop: the model asks for a tool, we run it, it carries on.

Driven against a scripted `messages.create`, so these assert the loop's own
behaviour rather than a vendor's availability. The properties that matter are
the ones a half-built loop would get wrong quietly: every call answered, a
failing tool reported rather than raised, and a cap that stops a model which
keeps asking forever.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.clients.llm.anthropic_provider import _MAX_TOOL_ROUNDS, AnthropicProvider
from app.clients.llm.base import ChatMessage, ToolOutcome, ToolSchema
from app.core.errors import ProviderError

pytestmark = pytest.mark.anyio

WEATHER = ToolSchema(
    name="get_weather",
    description="Current conditions.",
    input_schema={"type": "object", "properties": {"city": {"type": "string"}}},
)


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_block(name: str, arguments: dict, block_id: str = "tu_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=arguments, id=block_id)


def reply(content: list, stop_reason: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        model="claude-opus-5",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


class ScriptedClient:
    """Stands in for `anthropic.AsyncAnthropic`, returning replies in order."""

    def __init__(self, replies: list[SimpleNamespace]) -> None:
        self._replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create, stream=None)

    async def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        if not self._replies:
            raise AssertionError("the loop asked for more replies than were scripted")
        return self._replies.pop(0)


def provider_with(replies: list[SimpleNamespace]) -> tuple[AnthropicProvider, ScriptedClient]:
    provider = AnthropicProvider("sk-not-a-real-key")
    client = ScriptedClient(replies)
    provider._client = client  # noqa: SLF001 - the seam a fake SDK plugs into
    return provider, client


async def generate(provider, **kwargs):
    return await provider.generate(
        messages=[ChatMessage(role="user", content="What is the weather in Hanoi?")],
        model="claude-opus-5",
        max_tokens=1024,
        **kwargs,
    )


async def test_the_model_calls_a_tool_and_answers_with_what_it_learned():
    provider, client = provider_with(
        [
            reply([tool_block("get_weather", {"city": "Hanoi"})], "tool_use"),
            reply([text_block("It is 22C and clear.")], "end_turn"),
        ]
    )
    ran: list[tuple[str, dict]] = []

    async def execute(name: str, arguments: dict) -> ToolOutcome:
        ran.append((name, arguments))
        return ToolOutcome(text="22C, clear")

    result = await generate(provider, tools=[WEATHER], execute_tool=execute)

    assert ran == [("get_weather", {"city": "Hanoi"})]
    assert "22C and clear" in result.text
    # The result went back as a tool_result on a user turn, which is the only
    # shape the API accepts as an answer to a tool call.
    second = client.requests[1]["messages"]
    assert second[-1]["role"] == "user"
    assert second[-1]["content"][0]["type"] == "tool_result"
    assert second[-1]["content"][0]["content"] == "22C, clear"


async def test_the_tool_schema_is_offered_as_its_owner_wrote_it():
    provider, client = provider_with([reply([text_block("Hello.")], "end_turn")])

    async def execute(name: str, arguments: dict) -> ToolOutcome:
        return ToolOutcome(text="unused")

    await generate(provider, tools=[WEATHER], execute_tool=execute)

    offered = client.requests[0]["tools"]
    assert offered == [
        {
            "name": "get_weather",
            "description": "Current conditions.",
            "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
        }
    ]


async def test_tools_are_not_offered_without_a_way_to_run_them():
    """Offering a tool with no executor would have the model call into nothing."""
    provider, client = provider_with([reply([text_block("Hello.")], "end_turn")])

    await generate(provider, tools=[WEATHER])

    assert "tools" not in client.requests[0]


async def test_a_failing_tool_is_reported_to_the_model_not_raised():
    provider, client = provider_with(
        [
            reply([tool_block("get_weather", {"city": "Atlantis"})], "tool_use"),
            reply([text_block("I could not look that up.")], "end_turn"),
        ]
    )

    async def execute(name: str, arguments: dict) -> ToolOutcome:
        raise ProviderError("'weather' is unreachable.")

    result = await generate(provider, tools=[WEATHER], execute_tool=execute)

    assert "could not look that up" in result.text
    sent = client.requests[1]["messages"][-1]["content"][0]
    assert sent["is_error"] is True
    assert sent["content"] == "'weather' is unreachable."


async def test_every_tool_call_is_answered_even_the_unknown_one():
    """The API rejects a turn that leaves any tool call unanswered."""
    provider, client = provider_with(
        [
            reply(
                [
                    tool_block("get_weather", {"city": "Hanoi"}, "tu_1"),
                    tool_block("launch_missiles", {}, "tu_2"),
                ],
                "tool_use",
            ),
            reply([text_block("Done.")], "end_turn"),
        ]
    )
    ran: list[str] = []

    async def execute(name: str, arguments: dict) -> ToolOutcome:
        ran.append(name)
        return ToolOutcome(text="22C")

    await generate(provider, tools=[WEATHER], execute_tool=execute)

    # The tool that was never offered is refused rather than run.
    assert ran == ["get_weather"]
    answered = client.requests[1]["messages"][-1]["content"]
    assert [block["tool_use_id"] for block in answered] == ["tu_1", "tu_2"]
    assert answered[1]["is_error"] is True


async def test_a_model_that_keeps_calling_tools_is_capped():
    provider, client = provider_with(
        [reply([tool_block("get_weather", {"city": "Hanoi"})], "tool_use")] * 40
    )
    calls = {"n": 0}

    async def execute(name: str, arguments: dict) -> ToolOutcome:
        calls["n"] += 1
        return ToolOutcome(text="22C")

    result = await generate(provider, tools=[WEATHER], execute_tool=execute)

    assert calls["n"] == _MAX_TOOL_ROUNDS
    # It stops rather than looping, and says why the turn ended short.
    assert result.stop_reason == "tool_use"


async def test_narration_before_a_tool_call_survives_into_the_answer():
    """Text from an earlier round would otherwise be dropped for the last one."""
    provider, _ = provider_with(
        [
            reply(
                [text_block("Let me check that."), tool_block("get_weather", {"city": "Hanoi"})],
                "tool_use",
            ),
            reply([text_block("It is 22C.")], "end_turn"),
        ]
    )

    async def execute(name: str, arguments: dict) -> ToolOutcome:
        return ToolOutcome(text="22C")

    result = await generate(provider, tools=[WEATHER], execute_tool=execute)

    assert "Let me check that." in result.text
    assert "It is 22C." in result.text
