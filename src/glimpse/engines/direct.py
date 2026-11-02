"""The direct engine: one model, no agent framework (ENG-3).

Provider SDKs are optional extras, imported only when used (NFR-1). The engine owns the
read-only tool loop and the budget for tool results. Each provider module owns its wire
format and transcript.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..engine import EngineError, Message
from ..events import Custom, EngineEvent, StepStarted, ToolCallEnd, ToolCallResult, ToolCallStart, Usage, usage_event
from ..page import PageContext
from ..prompt import DEFAULT_SYSTEM_PROMPT, tool_result_block, user_turn
from ..tokens import estimate_tokens, truncate_to_tokens
from ..tools import Tool, ToolInputError

DEFAULT_ANTHROPIC_MODEL = 'claude-opus-5-5'
DEFAULT_OPENAI_MODEL = 'gpt-5'
OLLAMA_BASE_URL = 'http://localhost:11434/v1'

MAX_TOOL_RESULT_TOKENS = 4000
MIN_TOKENS_FOR_TOOLS = 200


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Any
    """Parsed arguments, or None if the model sent JSON that could not be parsed."""
    raw: str = ''


@dataclass
class RoundResult:
    """The end of one model call."""

    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ''
    input_tokens: int = 0
    output_tokens: int = 0
    notice: str = ''


class Conversation(Protocol):
    """One question's exchange with a provider, across tool rounds."""

    def next_round(self, *, use_tools: bool) -> AsyncIterator[EngineEvent | RoundResult]: ...

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None: ...


class Provider(Protocol):
    def conversation(self, system: str, messages: list[Message], tools: list[Tool]) -> Conversation: ...

    async def aclose(self) -> None: ...


def parse_model(model: str) -> tuple[str, str]:
    """Split "provider:model". Without a prefix, the provider is inferred from the name."""
    if ':' in model:
        provider, name = model.split(':', 1)
        if provider in ('anthropic', 'openai', 'ollama'):
            return provider, name
    return ('anthropic' if model.startswith('claude') else 'openai'), model


class DirectEngine:
    """Answers with a single model, reading more of the page through tools when it needs to."""

    def __init__(
        self,
        model: str | None = None,
        *,
        system_prompt: str | Callable[[PageContext], str] | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        max_output_tokens: int = 16000,
        max_tool_rounds: int = 4,
        effort: str = 'medium',
        provider: Provider | None = None,
    ) -> None:
        self.model = model
        self.system_prompt = system_prompt
        self.api_key = api_key
        self.base_url = base_url
        self.max_output_tokens = max_output_tokens
        self.max_tool_rounds = max_tool_rounds
        self.effort = effort
        self._provider = provider

    def _system(self, page: PageContext) -> str:
        if callable(self.system_prompt):
            return self.system_prompt(page)
        return DEFAULT_SYSTEM_PROMPT if self.system_prompt is None else self.system_prompt

    def overhead_text(self, page: PageContext) -> str:
        """What this engine adds to each request, so the budget can count it."""
        schemas = [{'name': tool.name, 'description': tool.description, 'parameters': tool.parameters}
                   for tool in page.tools]
        return self._system(page) + json.dumps(schemas)

    def _make_provider(self) -> Provider:
        if not self.model:
            raise EngineError('No model is configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY on the server, '
                              'or pass model= to glimpse.attach().')
        name, model = parse_model(self.model)
        if name == 'anthropic':
            from ._anthropic import AnthropicProvider

            return AnthropicProvider(model, api_key=self.api_key, base_url=self.base_url,
                                     max_output_tokens=self.max_output_tokens, effort=self.effort)
        from ._openai import OpenAIProvider

        base_url = self.base_url or (OLLAMA_BASE_URL if name == 'ollama' else None)
        api_key = self.api_key or ('ollama' if name == 'ollama' else None)
        return OpenAIProvider(model, api_key=api_key, base_url=base_url, max_output_tokens=self.max_output_tokens)

    async def respond(self, messages: list[Message], page: PageContext) -> AsyncIterator[EngineEvent]:
        # One engine serves every session, so each answer gets its own client and closes it.
        provider = self._provider or self._make_provider()
        try:
            async for event in self._answer(provider, messages, page):
                yield event
        finally:
            if self._provider is None:
                await provider.aclose()

    async def _answer(self, provider: Provider, messages: list[Message], page: PageContext) -> AsyncIterator[EngineEvent]:
        tools = page.tools
        by_name = {tool.name: tool for tool in tools}
        # The page goes in the final user message only, so history stays small and the
        # system prompt holds no untrusted text.
        sent = [*messages[:-1], Message('user', user_turn(page, messages[-1].content))]
        conversation = provider.conversation(self._system(page), sent, tools)

        remaining = page.report.remaining or 0
        input_tokens = output_tokens = 0
        for round_number in range(self.max_tool_rounds + 1):
            use_tools = round_number < self.max_tool_rounds and remaining > MIN_TOKENS_FOR_TOOLS
            result = RoundResult()
            async for event in conversation.next_round(use_tools=use_tools):
                if isinstance(event, RoundResult):
                    result = event
                else:
                    yield event
            input_tokens += result.input_tokens
            output_tokens += result.output_tokens
            if result.notice:
                yield Custom('glimpse.notice', result.notice)
            # Some local models ignore tool_choice. A round without tools is the last round regardless.
            if not result.tool_calls or not use_tools:
                break

            outcomes: list[tuple[str, str, bool]] = []
            for call in result.tool_calls:
                yield ToolCallStart(call.id, call.name)
                content, is_error = await _run_tool(by_name, call)
                content = truncate_to_tokens(content, min(MAX_TOOL_RESULT_TOKENS, max(remaining, 0)), estimate_tokens,
                                             '\n[result truncated to fit the budget]')
                remaining -= estimate_tokens(content)
                outcomes.append((call.id, tool_result_block(content), is_error))
                yield ToolCallEnd(call.id)
                yield ToolCallResult(call.id, content)
                element_id = call.arguments.get('element_id', '') if isinstance(call.arguments, dict) else ''
                yield Custom('glimpse.tool_call', {'name': call.name, 'element_id': element_id,
                                                   'arguments': json.dumps(call.arguments, default=str),
                                                   'error': 'yes' if is_error else ''})
            yield StepStarted('Thinking')
            conversation.add_tool_results(outcomes)
        yield usage_event(Usage(input_tokens=input_tokens, output_tokens=output_tokens,
                                model=self.model or ''))


async def _run_tool(tools: dict[str, Tool], call: ToolCall) -> tuple[str, bool]:
    tool = tools.get(call.name)
    if tool is None:
        return f'Unknown tool: {call.name}', True
    if call.arguments is None:
        return json.dumps({'INVALID_JSON': call.raw}), True
    try:
        # Tables can be large, and this keeps the event loop free.
        return await asyncio.to_thread(tool, call.arguments), False
    except ToolInputError as error:
        return str(error), True
