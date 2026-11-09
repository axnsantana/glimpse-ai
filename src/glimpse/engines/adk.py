"""Google ADK agents as Glimpse engines, through a thin adapter (ENG-4).

Pass your own agent, or let Glimpse build a single LlmAgent from a model string:

    glimpse.attach(engine=my_adk_agent)                          # your agent, tools and callbacks
    glimpse.attach(engine=glimpse.AdkEngine(model='vertex:gemini-flash-latest', project='my-project'))

For each question the adapter clones the agent, adds the page's read-only tools and the
Glimpse rules for untrusted page data to every LlmAgent in it, and runs it in a new in-memory
ADK session filled with the conversation so far. Glimpse keeps the history and budgets it, so
nothing about a session is kept between questions and the engine stays safe to share (SEC-1).

ADK is an optional extra, imported only when this engine answers (NFR-1). It needs Python 3.11
or later. No ADK type reaches the panel: the adapter maps ADK events onto Glimpse events.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from typing import Any

from ..engine import EngineError, Message
from ..events import EngineEvent, StepStarted, TextMessageContent, ToolCallEnd, ToolCallResult, ToolCallStart, Usage, usage_event
from ..page import PageContext
from ..prompt import DEFAULT_SYSTEM_PROMPT, tool_result_block, user_turn
from ..tokens import estimate_tokens, truncate_to_tokens
from ..tools import Tool, ToolInputError
from .direct import MAX_TOOL_RESULT_TOKENS, google_auth_error, google_cloud, parse_model, tool_call_record, tool_schemas_text

log = logging.getLogger('glimpse')

APP_NAME = 'glimpse'
USER_ID = 'glimpse-user'
AGENT_NAME = 'glimpse_assistant'
INSTALL_MESSAGE = 'Google ADK is not installed on the server. Run: pip install google-adk (Python 3.11 or later)'


def is_adk_agent(value: Any) -> bool:
    """True for an ADK agent, checked without importing ADK."""
    return any(cls.__module__.startswith('google.adk.') and cls.__name__ == 'BaseAgent' for cls in type(value).__mro__)


class AdkEngine:
    """Runs a Google ADK agent for each question, with the page's tools.

    :param agent: your ADK agent, any BaseAgent. Leave it out to have Glimpse build one LlmAgent from model
    :param model: for a built agent, "vertex:gemini-flash-latest", "vertex:claude-opus-5-5",
        "gemini:gemini-flash-latest" or "anthropic:claude-opus-5-5"
    :param system_prompt: the built agent's instruction. Default: Glimpse's own prompt
    :param project: the Google Cloud project for vertex: models, instead of GOOGLE_CLOUD_PROJECT
    :param location: the Vertex AI location, instead of GOOGLE_CLOUD_LOCATION. Default "global"
    :param api_key: a key for gemini: or anthropic: models, instead of their environment variables
    :param glimpse_rules: add Glimpse's rules for page data in front of the instruction of every LlmAgent
        in your agent. Your instruction is kept after them. Built agents always have them
    :param answer_from: names of the agents whose text is the answer. Others show as progress only.
        Default: every agent's text is shown
    :param max_output_tokens: for a built agent
    """

    def __init__(
        self,
        agent: Any = None,
        *,
        model: str | None = None,
        system_prompt: str | Callable[[PageContext], str] | None = None,
        project: str | None = None,
        location: str | None = None,
        api_key: str | None = None,
        glimpse_rules: bool = True,
        answer_from: tuple[str, ...] | list[str] | None = None,
        max_output_tokens: int = 16000,
    ) -> None:
        if agent is None and model is None:
            raise ValueError('AdkEngine needs an ADK agent, or a model to build one from.')
        if agent is not None and not is_adk_agent(agent):
            raise TypeError(f'{agent!r} is not an ADK agent. Pass a google.adk agent, or use model=.')
        if agent is None:
            provider, _ = parse_model(model)
            if provider not in ('gemini', 'vertex', 'anthropic'):
                raise ValueError(f'AdkEngine builds agents for gemini:, vertex: and anthropic: models, not {model!r}. '
                                 'For other providers, pass your own ADK agent, for example with LiteLlm.')
        self.agent = agent
        self.model = model
        self.system_prompt = system_prompt
        self.project = project
        self.location = location
        self.api_key = api_key
        self.glimpse_rules = glimpse_rules
        self.answer_from = tuple(answer_from) if answer_from else None
        self.max_output_tokens = max_output_tokens
        self._built: Any = None
        """The agent built from model, kept so that its model client is reused. It holds no session data."""

    def _instruction(self, page: PageContext) -> str:
        if callable(self.system_prompt):
            return self.system_prompt(page)
        return DEFAULT_SYSTEM_PROMPT if self.system_prompt is None else self.system_prompt

    def overhead_text(self, page: PageContext) -> str:
        """The instruction and tools Glimpse adds, so the budget can count them."""
        if self.agent is None:
            text = self._instruction(page)
        else:
            own = getattr(self.agent, 'instruction', '')
            text = (DEFAULT_SYSTEM_PROMPT if self.glimpse_rules else '') + (own if isinstance(own, str) else '')
        return text + tool_schemas_text(page)

    def _base_agent(self) -> Any:
        if self.agent is not None:
            return self.agent
        if self._built is None:
            from google.adk.agents import LlmAgent

            self._built = LlmAgent(name=AGENT_NAME, model=self._adk_model(),
                                   description='Answers questions about the page the user is looking at.')
        return self._built

    def _adk_model(self) -> Any:
        provider, name = parse_model(self.model)
        if provider == 'vertex' and name.startswith('claude'):
            import anthropic
            from google.adk.models.anthropic_llm import Claude

            cloud = google_cloud(self.project, self.location)
            client = anthropic.AsyncAnthropicVertex(project_id=cloud.project, region=cloud.location)
            return Claude(model=name, client=client, max_tokens=self.max_output_tokens)
        if provider == 'anthropic':
            import anthropic
            from google.adk.models.anthropic_llm import AnthropicLlm

            client = anthropic.AsyncAnthropic(**({'api_key': self.api_key} if self.api_key else {}))
            return AnthropicLlm(model=name, client=client, max_tokens=self.max_output_tokens)
        from google.adk.models import Gemini

        if provider == 'vertex':
            cloud = google_cloud(self.project, self.location)
            return Gemini(model=name, client_kwargs={'vertexai': True, 'project': cloud.project,
                                                     'location': cloud.location})
        return Gemini(model=name, client_kwargs={'api_key': self.api_key} if self.api_key else None)

    def _agent_for(self, page: PageContext, tools: list[Any]) -> Any:
        """A copy of the agent tree with the page's tools, so the original is never changed."""
        from google.adk.agents import LlmAgent

        base = self._base_agent()
        if self.agent is None:
            instruction = self._instruction(page)

            def built_instruction(_context: Any) -> str:
                # A provider function also stops ADK from reading braces in the prompt as state keys.
                return instruction

            return base.clone(update={'tools': [*base.tools, *tools], 'instruction': built_instruction})

        def with_page(agent: Any) -> Any:
            update: dict[str, Any] = {'sub_agents': [with_page(sub) for sub in agent.sub_agents]}
            if isinstance(agent, LlmAgent):
                update['tools'] = [*agent.tools, *tools]
                if self.glimpse_rules:
                    update['instruction'] = _with_rules(agent.instruction)
            return agent.clone(update=update)

        return with_page(base)

    async def respond(self, messages: list[Message], page: PageContext) -> AsyncIterator[EngineEvent]:
        try:
            from google.adk.agents import RunConfig
            from google.adk.agents.run_config import StreamingMode
            from google.adk.events import Event
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService
            from google.genai import types
        except ImportError as error:
            raise EngineError(INSTALL_MESSAGE) from error

        budget = _ToolBudget(page.report.remaining or 0)
        page_tools = [_adk_tool(tool, budget) for tool in page.tools]
        agent = self._agent_for(page, page_tools)
        sessions = InMemorySessionService()
        session = await sessions.create_session(app_name=APP_NAME, user_id=USER_ID)
        # Earlier turns go in as text only, like the other engines. The page goes in the last message.
        for number, message in enumerate(messages[:-1]):
            role = 'user' if message.role == 'user' else 'model'
            await sessions.append_event(session, Event(
                invocation_id=f'history-{number // 2}', author='user' if role == 'user' else agent.name,
                content=types.Content(role=role, parts=[types.Part(text=message.content)])))
        question = types.Content(role='user', parts=[types.Part(text=user_turn(page, messages[-1].content))])

        runner = Runner(agent=agent, app_name=APP_NAME, session_service=sessions)
        mapper = _EventMapper(self.answer_from, self.model or getattr(agent, 'name', 'adk'))
        try:
            stream = runner.run_async(user_id=USER_ID, session_id=session.id, new_message=question,
                                      run_config=RunConfig(streaming_mode=StreamingMode.SSE))
            async with aclosing(stream) as events:
                async for event in events:
                    for item in mapper.map(event):
                        yield item
        except EngineError:
            raise
        except Exception as error:
            safe = _safe_error(error)
            if safe is None:
                raise
            raise safe from error
        finally:
            await runner.close()
        yield mapper.usage()


def _with_rules(instruction: Any) -> Any:
    if not callable(instruction):
        return f'{DEFAULT_SYSTEM_PROMPT}\n\n{instruction}' if instruction else DEFAULT_SYSTEM_PROMPT

    async def combined(context: Any) -> str:
        own = instruction(context)
        if inspect.isawaitable(own):
            own = await own
        return f'{DEFAULT_SYSTEM_PROMPT}\n\n{own}'

    return combined


class _ToolBudget:
    """What is left of one request's budget for tool results, shared by every tool call in it."""

    def __init__(self, remaining: int) -> None:
        self.remaining = remaining

    def fit(self, content: str) -> str:
        content = truncate_to_tokens(content, min(MAX_TOOL_RESULT_TOKENS, max(self.remaining, 0)), estimate_tokens,
                                     '\n[result truncated to fit the budget]')
        self.remaining -= estimate_tokens(content)
        return content


def _adk_tool(tool: Tool, budget: _ToolBudget) -> Any:
    """Wrap one read-only page tool as an ADK tool, with the same checks as the direct engine."""
    from google.adk.tools.base_tool import BaseTool
    from google.genai import types

    class PageTool(BaseTool):
        def _get_declaration(self) -> types.FunctionDeclaration:
            return types.FunctionDeclaration(name=tool.name, description=tool.description,
                                             parameters_json_schema=tool.parameters)

        async def run_async(self, *, args: dict[str, Any], tool_context: Any) -> dict[str, Any]:
            try:
                content, error = await asyncio.to_thread(tool, args), False
            except ToolInputError as problem:
                content, error = str(problem), True
            return {'error' if error else 'result': tool_result_block(budget.fit(content))}

    return PageTool(name=tool.name, description=tool.description)


class _EventMapper:
    """Turns ADK events into Glimpse events, so no ADK type reaches the panel."""

    def __init__(self, answer_from: tuple[str, ...] | None, model: str) -> None:
        self.answer_from = answer_from
        self.model = model
        self.input_tokens = 0
        self.output_tokens = 0
        self.streamed: set[str] = set()
        """Authors whose current reply already arrived in partial chunks."""
        self.calls: dict[str, tuple[str, Any]] = {}
        self.last_author = ''
        self.text_author: str | None = None

    def map(self, event: Any) -> list[EngineEvent]:
        out: list[EngineEvent] = []
        if event.error_code:
            log.error('ADK agent %r reported %s: %s', event.author, event.error_code, event.error_message)
            raise EngineError(_event_error_message(str(event.error_code), event.error_message or ''))
        author = event.author or ''
        shown = self.answer_from is None or author in self.answer_from
        if author and author != self.last_author and author != 'user':
            self.last_author = author
            if not shown:
                out.append(StepStarted(f'{author} is working'))
        if not event.partial and event.usage_metadata:
            usage = event.usage_metadata
            self.input_tokens += usage.prompt_token_count or 0
            self.output_tokens += (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
        parts = event.content.parts if event.content and event.content.parts else []
        text = ''.join(part.text for part in parts if part.text and not part.thought)
        if any(part.thought for part in parts):
            out.append(StepStarted('Thinking'))
        if text and shown:
            if event.partial:
                self.streamed.add(author)
                out.append(TextMessageContent(self._separated(author, text)))
            elif author not in self.streamed:
                out.append(TextMessageContent(self._separated(author, text)))
        if not event.partial:
            self.streamed.discard(author)
            for call in event.get_function_calls():
                self.calls[call.id or call.name] = (call.name, call.args)
                out.append(ToolCallStart(call.id or call.name, call.name))
            for response in event.get_function_responses():
                call_id = response.id or response.name
                name, arguments = self.calls.get(call_id, (response.name, {}))
                result = response.response or {}
                content = result.get('result', result.get('error', '')) if isinstance(result, dict) else str(result)
                content = content if isinstance(content, str) else json.dumps(content, default=str)
                out += [ToolCallEnd(call_id), ToolCallResult(call_id, content),
                        tool_call_record(name, arguments, isinstance(result, dict) and 'error' in result)]
                out.append(StepStarted('Thinking'))
        return out

    def _separated(self, author: str, text: str) -> str:
        """Text from a second agent starts on a new paragraph."""
        if self.text_author is not None and author != self.text_author:
            text = '\n\n' + text
        self.text_author = author
        return text

    def usage(self) -> EngineEvent:
        return usage_event(Usage(input_tokens=self.input_tokens, output_tokens=self.output_tokens, model=self.model))


def _event_error_message(code: str, message: str) -> str:
    """ADK reports a failed model call as an event with a status name or number, and the message."""
    from ._google import api_error_message

    statuses = {'UNAUTHENTICATED': 401, 'PERMISSION_DENIED': 403, 'NOT_FOUND': 404, 'RESOURCE_EXHAUSTED': 429}
    if code.isdigit():
        return api_error_message(int(code))
    if code in statuses:
        return api_error_message(statuses[code])
    leading = message.split(' ', 1)[0]
    if leading.isdigit():
        return api_error_message(int(leading))
    return 'The agent could not answer. The details are in the server log.'


def _safe_error(error: Exception) -> EngineError | None:
    """A message for the end user, from the errors the model SDKs under ADK raise."""
    if (safe := google_auth_error(error)) is not None:
        return safe
    code = getattr(error, 'code', None) or getattr(error, 'status_code', None)
    if isinstance(code, int):
        from ._google import api_error_message

        log.error('The ADK agent failed with status %s: %s', code, error)
        return EngineError(api_error_message(code))
    return None
