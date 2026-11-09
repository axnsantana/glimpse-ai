"""The direct engine: one model, no agent framework (ENG-3).

Provider SDKs are optional extras, imported only when used (NFR-1). The engine owns the
read-only tool loop and the budget for tool results. Each provider module owns its wire
format and transcript.
"""

from __future__ import annotations

import asyncio
import json
import os
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
DEFAULT_GEMINI_MODEL = 'gemini-flash-latest'
DEFAULT_VERTEX_LOCATION = 'global'
OLLAMA_BASE_URL = 'http://localhost:11434/v1'

PROVIDERS = ('anthropic', 'openai', 'ollama', 'gemini', 'vertex')
NO_MODEL_MESSAGE = ('No model is configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY on the server, '
                    'or pass model= to glimpse.attach().')

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
        if provider in PROVIDERS:
            return provider, name
    if model.startswith('claude'):
        return 'anthropic', model
    if model.startswith('gemini'):
        return 'gemini', model
    return 'openai', model


@dataclass(frozen=True)
class GoogleCloud:
    """Where Vertex AI calls go. Credentials come from Application Default Credentials, not a key."""

    project: str
    location: str


def google_cloud(project: str | None = None, location: str | None = None) -> GoogleCloud:
    """Resolve the Vertex AI project and location from arguments, then from the environment."""
    project = (project or os.environ.get('GOOGLE_CLOUD_PROJECT') or os.environ.get('ANTHROPIC_VERTEX_PROJECT_ID')
               or os.environ.get('GCLOUD_PROJECT'))
    if not project:
        raise EngineError('No Google Cloud project is configured on the server. '
                          'Set GOOGLE_CLOUD_PROJECT, or pass project= to glimpse.attach().')
    location = (location or os.environ.get('GOOGLE_CLOUD_LOCATION') or os.environ.get('CLOUD_ML_REGION')
                or DEFAULT_VERTEX_LOCATION)
    return GoogleCloud(project, location)


GOOGLE_CREDENTIALS_MESSAGE = ('The server has no usable Google Cloud credentials. Run '
                              '"gcloud auth application-default login", or set GOOGLE_APPLICATION_CREDENTIALS.')


def google_auth_error(error: BaseException) -> EngineError | None:
    """A safe message for a missing or broken Google credential, wherever in the chain it was raised."""
    current: BaseException | None = error
    while current is not None:
        module = type(current).__module__
        if module.startswith('google.auth') or 'Could not resolve API token' in str(current):
            return EngineError(GOOGLE_CREDENTIALS_MESSAGE)
        current = current.__cause__ or current.__context__
    return None


def make_provider(
    model: str | None,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    project: str | None = None,
    location: str | None = None,
    max_output_tokens: int = 16000,
    effort: str = 'medium',
) -> Provider:
    """Build the provider client for one answer. Raises EngineError with a message for the end user."""
    if not model:
        raise EngineError(NO_MODEL_MESSAGE)
    name, model_name = parse_model(model)
    if name == 'anthropic' or (name == 'vertex' and model_name.startswith('claude')):
        from ._anthropic import AnthropicProvider

        cloud = google_cloud(project, location) if name == 'vertex' else None
        return AnthropicProvider(model_name, api_key=api_key, base_url=base_url, max_output_tokens=max_output_tokens,
                                 effort=effort, vertex=cloud)
    if name in ('gemini', 'vertex'):
        from ._google import GeminiProvider

        cloud = google_cloud(project, location) if name == 'vertex' else None
        return GeminiProvider(model_name, api_key=api_key, base_url=base_url, max_output_tokens=max_output_tokens,
                              effort=effort, vertex=cloud)
    from ._openai import OpenAIProvider

    base_url = base_url or (OLLAMA_BASE_URL if name == 'ollama' else None)
    api_key = api_key or ('ollama' if name == 'ollama' else None)
    return OpenAIProvider(model_name, api_key=api_key, base_url=base_url, max_output_tokens=max_output_tokens)


def tool_schemas_text(page: PageContext) -> str:
    schemas = [{'name': tool.name, 'description': tool.description, 'parameters': tool.parameters}
               for tool in page.tools]
    return json.dumps(schemas)


class DirectEngine:
    """Answers with a single model, reading more of the page through tools when it needs to.

    :param model: "provider:model", for example "anthropic:claude-opus-5-5", "vertex:claude-opus-5-5",
        "vertex:gemini-flash-latest", "gemini:gemini-flash-latest", "openai:gpt-5" or "ollama:llama3.2"
    :param api_key: a key for the provider, instead of its environment variable. Not used by vertex:
    :param project: the Google Cloud project for vertex: models, instead of GOOGLE_CLOUD_PROJECT
    :param location: the Vertex AI location, instead of GOOGLE_CLOUD_LOCATION. Default "global"
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        system_prompt: str | Callable[[PageContext], str] | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        project: str | None = None,
        location: str | None = None,
        max_output_tokens: int = 16000,
        max_tool_rounds: int = 4,
        effort: str = 'medium',
        provider: Provider | None = None,
    ) -> None:
        self.model = model
        self.system_prompt = system_prompt
        self.api_key = api_key
        self.base_url = base_url
        self.project = project
        self.location = location
        self.max_output_tokens = max_output_tokens
        self.max_tool_rounds = max_tool_rounds
        self.effort = effort
        self._provider = provider

    def system_for(self, page: PageContext) -> str:
        """The system prompt this engine sends for a page."""
        if callable(self.system_prompt):
            return self.system_prompt(page)
        return DEFAULT_SYSTEM_PROMPT if self.system_prompt is None else self.system_prompt

    def overhead_text(self, page: PageContext) -> str:
        """What this engine adds to each request, so the budget can count it."""
        return self.system_for(page) + tool_schemas_text(page)

    def _make_provider(self) -> Provider:
        return make_provider(self.model, api_key=self.api_key, base_url=self.base_url, project=self.project,
                             location=self.location, max_output_tokens=self.max_output_tokens, effort=self.effort)

    async def respond(self, messages: list[Message], page: PageContext) -> AsyncIterator[EngineEvent]:
        # The page goes in the final user message only, so history stays small and the
        # system prompt holds no untrusted text.
        sent = [*messages[:-1], Message('user', user_turn(page, messages[-1].content))]
        async for event in self.run(self.system_for(page), sent, page):
            yield event

    async def run(self, system: str, sent: list[Message], page: PageContext) -> AsyncIterator[EngineEvent]:
        """Answer messages that are already shaped, with the page's tools. The council engine uses this for each role."""
        # One engine serves every session, so each answer gets its own client and closes it.
        provider = self._provider or self._make_provider()
        try:
            async for event in tool_loop(provider, system, sent, page, max_tool_rounds=self.max_tool_rounds,
                                         model=self.model or ''):
                yield event
        finally:
            if self._provider is None:
                await provider.aclose()


async def tool_loop(provider: Provider, system: str, sent: list[Message], page: PageContext, *,
                    max_tool_rounds: int, model: str) -> AsyncIterator[EngineEvent]:
    """Call the model, run the tools it asks for, and repeat, within the round limit and the budget."""
    tools = page.tools
    by_name = {tool.name: tool for tool in tools}
    conversation = provider.conversation(system, sent, tools)

    remaining = page.report.remaining or 0
    input_tokens = output_tokens = 0
    for round_number in range(max_tool_rounds + 1):
        use_tools = round_number < max_tool_rounds and remaining > MIN_TOKENS_FOR_TOOLS
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
            content, is_error = await run_tool(by_name, call)
            content = truncate_to_tokens(content, min(MAX_TOOL_RESULT_TOKENS, max(remaining, 0)), estimate_tokens,
                                         '\n[result truncated to fit the budget]')
            remaining -= estimate_tokens(content)
            outcomes.append((call.id, tool_result_block(content), is_error))
            yield ToolCallEnd(call.id)
            yield ToolCallResult(call.id, content)
            yield tool_call_record(call.name, call.arguments, is_error)
        yield StepStarted('Thinking')
        conversation.add_tool_results(outcomes)
    yield usage_event(Usage(input_tokens=input_tokens, output_tokens=output_tokens, model=model))


def tool_call_record(name: str, arguments: Any, is_error: bool) -> Custom:
    """What the inspector and the source chips show for one tool call (UI-7)."""
    element_id = arguments.get('element_id', '') if isinstance(arguments, dict) else ''
    return Custom('glimpse.tool_call', {'name': name, 'element_id': element_id,
                                        'arguments': json.dumps(arguments, default=str),
                                        'error': 'yes' if is_error else ''})


async def run_tool(tools: dict[str, Tool], call: ToolCall) -> tuple[str, bool]:
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
