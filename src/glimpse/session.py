"""One conversation with the assistant, on one page, for one client.

This object owns all state of a conversation. The adapter keeps it on the client
connection and nothing is module-level, so sessions cannot see each other (SEC-1).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from .builder import prepare_request
from .config import GlimpseConfig
from .engine import Engine, EngineError, Message
from .events import (
    USAGE_EVENT,
    Custom,
    RunError,
    StepFinished,
    StepStarted,
    TextMessageContent,
    ToolCallResult,
    ToolCallStart,
    Usage,
)
from .page import ElementSnapshot, PageContext
from .sanitize import render_safe

log = logging.getLogger('glimpse')

RENDER_INTERVAL = 0.05
_END = object()


@dataclass
class Turn:
    """One question and its answer, as the panel shows it."""

    id: int
    question: str
    status: str = 'reading'
    """reading, thinking, streaming, done, stopped or error."""
    progress: str = 'Reading the page'
    text: str = ''
    blocks: list[dict[str, Any]] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    engine_notices: list[str] = field(default_factory=list)
    """Remarks from the engine, such as an answer that was cut off."""
    error: str = ''
    page: PageContext | None = None
    tool_calls: list[dict[str, str]] = field(default_factory=list)
    usage: Usage | None = None
    question_sent: str = ''
    """The question after redaction and budgeting, which is what the engine and history get."""

    def sources(self) -> list[dict[str, str]]:
        """Elements this answer used: those it cited, then those its tools read (UI-7)."""
        if self.page is None:
            return []
        wanted = [*self.citations, *(call['element_id'] for call in self.tool_calls if call.get('element_id'))]
        sources = []
        for element_id in dict.fromkeys(wanted):
            element = self.page.element(element_id)
            if element is not None:
                sources.append({'id': element.id, 'label': _source_label(element), 'kind': element.kind,
                                'dom': element.dom_id})
        return sources

    def view(self) -> dict[str, Any]:
        """Everything the browser needs to draw this turn. Holds no raw model output."""
        return {
            'id': self.id,
            'question': self.question,
            'status': self.status,
            'progress': self.progress,
            'blocks': self.blocks,
            'sources': self.sources(),
            'notices': self.notices,
            'error': self.error,
            'tokens': self.page.report.used if self.page else None,
            'budget': self.page.report.budget if self.page else None,
        }

    def inspection(self, *, full: bool = False, system_prompt: str = '') -> dict[str, Any]:
        """What the assistant saw for this answer (UI-6)."""
        if self.page is None:
            return {'id': self.id, 'available': False}
        report = self.page.report
        data: dict[str, Any] = {
            'id': self.id,
            'available': True,
            'page': self.page.rendered,
            'notes': self.page.notes,
            'parts': [
                ['Page', report.page_tokens],
                ['History', report.history_tokens],
                ['Question', report.question_tokens],
                ['Developer context', report.context_tokens],
                ['System prompt and tools', report.system_tokens],
            ],
            'tokens': report.used,
            'budget': report.budget,
            'detail_level': report.detail_level,
            'dropped_messages': report.dropped_messages,
            'tool_calls': self.tool_calls,
            'usage': _usage_dict(self.usage),
        }
        if full:
            data['developer_context'] = self.page.developer_context
            data['system_prompt'] = system_prompt
        return data


def _source_label(element: ElementSnapshot) -> str:
    """A name a user can recognize, so that a source is not just called "text"."""
    if element.label:
        return element.label
    text = (element.text or '').strip()
    if text:
        return text if len(text) <= 32 else text[:31].rstrip() + '…'
    return element.kind


def _usage_dict(usage: Usage | None) -> dict[str, Any] | None:
    if usage is None:
        return None
    return {'input': usage.input_tokens, 'output': usage.output_tokens, 'model': usage.model, 'cost': usage.cost,
            'estimated': usage.estimated}


class ChatSession:
    def __init__(
        self,
        engine: Engine,
        config: GlimpseConfig,
        capture: Callable[[], Awaitable[PageContext]],
        on_turn: Callable[[Turn], None],
    ) -> None:
        self.engine = engine
        self.config = config
        self.capture = capture
        self.on_turn = on_turn
        self.turns: list[Turn] = []
        self.history: list[Message] = []
        self.total_tokens = 0
        self.total_cost = 0.0
        self._task: asyncio.Task | None = None
        self._last_render = 0.0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def ask(self, question: str) -> asyncio.Task | None:
        """Start answering. Returns None if an answer is already running or the question is empty."""
        question = question.strip()
        if not question or self.running:
            return None
        turn = Turn(id=len(self.turns) + 1, question=question)
        self.turns.append(turn)
        limit = self._limit_reached()
        if limit:
            turn.status, turn.error, turn.progress = 'error', limit, ''
            self.on_turn(turn)
            return None
        self.on_turn(turn)
        self._task = asyncio.create_task(self._run(turn))
        return self._task

    def cancel(self) -> None:
        """Stop the answer in progress. The engine's iterator is closed."""
        if self.running:
            self._task.cancel()

    def reset(self) -> None:
        """Start a new conversation. Session totals stay, as they guard spending."""
        self.cancel()
        self.turns.clear()
        self.history.clear()

    def _limit_reached(self) -> str:
        config = self.config
        if config.max_session_tokens is not None and self.total_tokens >= config.max_session_tokens:
            return 'This session has reached its usage limit, so the assistant cannot answer more questions.'
        if config.max_session_cost is not None and self.total_cost >= config.max_session_cost:
            return 'This session has reached its spending limit, so the assistant cannot answer more questions.'
        return ''

    async def _run(self, turn: Turn) -> None:
        try:
            await self._answer(turn)
            if turn.status != 'error':
                turn.status = 'done'
        except asyncio.CancelledError:
            turn.status = 'stopped'
        except EngineError as error:
            turn.status, turn.error = 'error', error.user_message
        except TimeoutError:
            turn.status, turn.error = 'error', 'The assistant took too long to answer.'
        except Exception:
            log.exception('Glimpse engine failed')
            turn.status, turn.error = 'error', 'The assistant could not answer. The details are in the server log.'
        turn.progress = ''
        self._render(turn, force=True)
        self._remember(turn)

    async def _answer(self, turn: Turn) -> None:
        page = await self.capture()
        turn.page = page
        overhead = getattr(self.engine, 'overhead_text', None)
        messages, page = await asyncio.to_thread(
            prepare_request, page, list(self.history), turn.question, self.config,
            overhead_text=overhead(page) if overhead else '',
            reserved_tokens=getattr(self.engine, 'reserved_tokens', 0),
        )
        turn.question_sent = messages[-1].content
        turn.status, turn.progress = 'thinking', 'Thinking'
        self._render(turn, force=True)

        usage: Usage | None = None
        async for event in self._stream(turn, messages, page):
            if isinstance(event, str):
                event = TextMessageContent(event)
            if isinstance(event, TextMessageContent):
                turn.text += event.delta
                turn.status, turn.progress = 'streaming', ''
                self._render(turn)
            elif isinstance(event, StepStarted):
                turn.progress = event.step_name
                self._render(turn, force=True)
            elif isinstance(event, StepFinished):
                turn.progress = 'Thinking' if turn.status == 'thinking' else ''
                self._render(turn, force=True)
            elif isinstance(event, ToolCallStart):
                turn.progress = f'Reading more of the page ({event.tool_call_name})'
                self._render(turn, force=True)
            elif isinstance(event, ToolCallResult):
                pass
            elif isinstance(event, RunError):
                turn.status, turn.error = 'error', event.message or 'The assistant could not answer.'
            elif isinstance(event, Custom) and event.name == USAGE_EVENT:
                usage = event.value
            elif isinstance(event, Custom) and event.name == 'glimpse.notice':
                turn.engine_notices.append(str(event.value))
            elif isinstance(event, Custom) and event.name == 'glimpse.tool_call':
                turn.tool_calls.append(event.value)
                self._render(turn, force=True)
        self._report_usage(turn, usage)

    async def _stream(self, turn: Turn, messages: list[Message], page: PageContext) -> AsyncIterator[Any]:
        """Iterate the engine, with heartbeats during silence, a timeout, and a clean close on cancel (NFR-2)."""
        stream = self.engine.respond(messages, page).__aiter__()

        async def read_next() -> Any:
            try:
                return await stream.__anext__()
            except StopAsyncIteration:
                return _END

        started = time.monotonic()
        pending: asyncio.Task | None = None
        try:
            while True:
                pending = asyncio.ensure_future(read_next())
                while True:
                    done, _ = await asyncio.wait({pending}, timeout=self.config.heartbeat)
                    if done:
                        break
                    elapsed = time.monotonic() - started
                    if elapsed > self.config.request_timeout:
                        raise TimeoutError
                    if not turn.text:
                        turn.progress = f'Still working, {int(elapsed)}s so far'
                        self._render(turn, force=True)
                item = pending.result()
                pending = None
                if item is _END:
                    return
                yield item
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                try:
                    await pending
                except (asyncio.CancelledError, Exception):
                    pass
            close = getattr(stream, 'aclose', None)
            if close is not None:
                await close()

    def _render(self, turn: Turn, *, force: bool = False) -> None:
        """Sanitize on the server for every update the browser receives (SEC-3)."""
        now = time.monotonic()
        if not force and now - self._last_render < RENDER_INTERVAL:
            return
        self._last_render = now
        known = {element.id for element in turn.page.elements} if turn.page else set()
        document = render_safe(turn.text, known_ids=known, allowed_link_hosts=self.config.allowed_link_hosts)
        turn.blocks = document.blocks
        turn.citations = document.citations
        notices = list(turn.engine_notices)
        if turn.status == 'stopped':
            notices.append('Stopped.')
        if document.removed_images:
            notices.append(f'{document.removed_images} image(s) in this answer were removed for safety.')
        if document.blocked_links:
            notices.append(f'{document.blocked_links} link(s) in this answer were disabled for safety.')
        turn.notices = notices
        self.on_turn(turn)

    def _remember(self, turn: Turn) -> None:
        question = turn.question_sent or turn.question
        if turn.status == 'done' and turn.text:
            self.history += [Message('user', question), Message('assistant', turn.text)]
        elif turn.status == 'stopped' and turn.text:
            self.history += [Message('user', question), Message('assistant', turn.text + '\n[stopped by the user]')]

    def _report_usage(self, turn: Turn, usage: Usage | None) -> None:
        count = self.config.count_tokens
        if usage is None:
            report = turn.page.report if turn.page else None
            usage = Usage(input_tokens=report.used if report else 0, output_tokens=count(turn.text), estimated=True)
        if self.config.pricing is not None and usage.cost is None:
            usage = replace(usage, cost=self.config.pricing.cost(usage))
        turn.usage = usage
        self.total_tokens += usage.total_tokens
        self.total_cost += usage.cost or 0.0
        if self.config.on_usage is not None:
            try:
                self.config.on_usage(usage)
            except Exception:
                log.exception('Glimpse on_usage hook failed')
