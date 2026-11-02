"""The context builder: fits one request into the token budget (CTX-1, CTX-4).

Each part has a limit, and the page falls down a ladder of detail until it fits. History
gives way oldest first. Whatever gets cut leaves a visible notice, so the model knows
what it is missing instead of guessing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from .config import GlimpseConfig
from .engine import EngineError, Message
from .page import ContextReport, PageContext, TableData
from .prompt import FENCE_OVERHEAD_TOKENS
from .serialize import LADDER
from .tokens import estimate_tokens, truncate_to_tokens

QUESTION_SHARE = 0.2
CONTEXT_SHARE = 0.15
PAGE_SHARE = 0.7
"""Of what remains after the system prompt, question and developer context."""
TOOL_RESERVE_SHARE = 0.15
"""Of the whole budget, kept free so that tool results can fit."""
MAX_OVERHEAD_SHARE = 0.5
HISTORY_MESSAGE_SHARE = 0.25
ESTIMATE_MARGIN = 0.75
"""Plan to use this share of the budget when tokens are estimated. Measured estimates ran as low as 74% of the real count."""


def check_budget(budget: int, overhead_text: str, count: Callable[[str], int]) -> None:
    """Fail at setup, not on a user's first question, if an engine's fixed text leaves no room for the page."""
    overhead = count(overhead_text) + FENCE_OVERHEAD_TOKENS
    margin = ESTIMATE_MARGIN if count is estimate_tokens else 1.0
    if overhead > budget * margin * MAX_OVERHEAD_SHARE:
        needed = int(overhead / (margin * MAX_OVERHEAD_SHARE)) + 1
        raise ValueError(f'budget={budget} is too small: the system prompt and tools alone take about {overhead} '
                         f'tokens. Use a budget of at least {needed}, or a shorter system prompt.')


def prepare_request(
    page: PageContext,
    history: list[Message],
    question: str,
    config: GlimpseConfig,
    *,
    overhead_text: str = '',
) -> tuple[list[Message], PageContext]:
    """Redact, shape and budget one request. Runs in a worker thread, as tables can be large."""
    count = config.count_tokens
    for element in page.elements:
        if element.table:
            element.table.apply_view()
    if config.redact:
        _redact_page(page, config.redact)
        question = config.redact(question)

    total = int(config.budget * ESTIMATE_MARGIN) if count is estimate_tokens else config.budget
    overhead = count(overhead_text) + FENCE_OVERHEAD_TOKENS
    if overhead > total * MAX_OVERHEAD_SHARE:
        # A system prompt function can grow with the page, which attach() cannot check in advance.
        raise EngineError('This assistant is misconfigured: its system prompt is too large for its token budget.')

    question = truncate_to_tokens(question, int(total * QUESTION_SHARE), count,
                                  '\n[question truncated because it was too long]')
    page.developer_context = truncate_to_tokens(page.developer_context, int(total * CONTEXT_SHARE), count,
                                                '\n[developer context truncated]')
    question_tokens = count(question)
    context_tokens = count(page.developer_context)
    available = total - overhead - question_tokens - context_tokens

    page.rendered, level, truncated = _fit_page(page, int(available * PAGE_SHARE), config)
    page_tokens = count(page.rendered)

    reserve = int(total * TOOL_RESERVE_SHARE)
    kept, dropped, history_tokens = _fit_history(history, max(available - page_tokens - reserve, 0), count)

    page.report = ContextReport(
        budget=config.budget,
        usable=total,
        system_tokens=overhead,
        page_tokens=page_tokens,
        history_tokens=history_tokens,
        question_tokens=question_tokens,
        context_tokens=context_tokens,
        detail_level=level,
        dropped_messages=dropped,
        truncated_page=truncated,
    )
    return [*kept, Message('user', question)], page


def _fit_page(page: PageContext, budget: int, config: GlimpseConfig) -> tuple[str, int, bool]:
    text = ''
    for level, detail in enumerate(LADDER):
        text = config.serializer(page, detail)
        if config.count_tokens(text) <= budget:
            return text, level, False
    notice = '\n[The page is too large to list in full. Some elements are missing from this list.]'
    return truncate_to_tokens(text, budget, config.count_tokens, notice), len(LADDER) - 1, True


def _fit_history(history: list[Message], budget: int, count: Callable[[str], int]) -> tuple[list[Message], int, int]:
    """Keep the newest messages that fit, cutting any single message that is too long."""
    limit = max(int(budget * HISTORY_MESSAGE_SHARE), 200)
    kept: list[Message] = []
    used = 0
    for message in reversed(history):
        content = truncate_to_tokens(message.content, limit, count, '\n[message truncated]')
        tokens = count(content)
        if used + tokens > budget:
            break
        kept.append(replace(message, content=content))
        used += tokens
    kept.reverse()
    while kept and kept[0].role != 'user':
        used -= count(kept.pop(0).content)
    return kept, len(history) - len(kept), used


def _redact_page(page: PageContext, redact: Callable[[str], str]) -> None:
    """Run the hook over every string in the snapshot, so that no engine sees the raw value (SEC-7)."""
    page.title = redact(page.title)
    page.url = redact(page.url)
    page.developer_context = redact(page.developer_context)
    for element in page.elements:
        element.label = redact(element.label)
        element.description = redact(element.description)
        if element.text is not None:
            element.text = redact(element.text)
        element.value = _redact_value(element.value, redact)
        element.extra = _redact_value(element.extra, redact)
        element.state = _redact_value(element.state, redact)
        if element.options is not None:
            element.options = _redact_value(element.options, redact)
        if element.table:
            _redact_table(element.table, redact)
        for series in element.series or ():
            series.name = redact(series.name)
            if series.x is not None:
                series.x = _redact_value(series.x, redact)


def _redact_table(table: TableData, redact: Callable[[str], str]) -> None:
    table.rows = [{key: _redact_value(value, redact) for key, value in row.items()} for row in table.rows]
    table.labels = {key: redact(value) for key, value in table.labels.items()}


def _redact_value(value: Any, redact: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: _redact_value(item, redact) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(item, redact) for item in value]
    return value
