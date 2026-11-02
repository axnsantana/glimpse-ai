"""A no-model engine, so that the examples and tests run without an API key.

It answers from simple rules over the snapshot. This is a demo of what capture sees and
not a replacement for a model. The panel shows a banner while it is in use. No page data
leaves the process.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from ..engine import Message
from ..events import EngineEvent, TextMessageContent, TextMessageEnd, TextMessageStart
from ..page import ElementSnapshot, PageContext, Series, TableData
from ..summarize import as_number, column_stats, format_number, summarize_series

STOP_WORDS = frozenset(
    'a an and are at be by can do does for from has have how i in is it me my of on or show tell that the there this '
    'to was what when where which who whose why with you your was were will would could should value data please'.split()
)
HIGH_WORDS = frozenset({'highest', 'largest', 'max', 'maximum', 'most', 'top', 'best', 'biggest', 'peak', 'paid', 'over'})
LOW_WORDS = frozenset({'lowest', 'smallest', 'min', 'minimum', 'least', 'worst', 'bottom'})
MEAN_WORDS = frozenset({'average', 'mean'})
SUM_WORDS = frozenset({'total', 'sum'})
COUNT_WORDS = frozenset({'many', 'count', 'number'})
TREND_WORDS = frozenset({'trend', 'trending', 'rising', 'falling', 'growing', 'going'})
STATE_WORDS = frozenset({'filter', 'filters', 'filtered', 'selected', 'selection', 'tab', 'tabs', 'sorted', 'sort', 'zoom',
                         'zoomed', 'inputs', 'input', 'settings', 'setting', 'current', 'state'})
OVERVIEW_WORDS = frozenset({'see', 'summary', 'summarize', 'summarise', 'overview', 'page', 'screen', 'looking', 'on'})


class OfflineEngine:
    banner = ('Offline demo mode: no model is connected. Answers come from simple rules over the page. '
              'Set ANTHROPIC_API_KEY on the server to use a real model.')

    def __init__(self, delay: float = 0.012) -> None:
        self.delay = delay

    async def respond(self, messages: list[Message], page: PageContext) -> AsyncIterator[EngineEvent]:
        yield TextMessageStart('offline')
        for word in re.findall(r'\S+\s*', answer_question(messages[-1].content, page)):
            await asyncio.sleep(self.delay)
            yield TextMessageContent(word, 'offline')
        yield TextMessageEnd('offline')


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r'[a-z0-9]+', text.lower()) if word not in STOP_WORDS}


def answer_question(question: str, page: PageContext) -> str:
    """Pick the rule that fits the question, and answer only from the snapshot."""
    words = _words(question)
    raw_words = set(re.findall(r'[a-z0-9]+', question.lower()))

    if raw_words & STATE_WORDS and not raw_words & (HIGH_WORDS | LOW_WORDS | MEAN_WORDS | SUM_WORDS):
        return _describe_state(page)
    measure = _measure(raw_words)
    if measure:
        target = _best_numeric_target(words, page)
        if target:
            return _answer_measure(measure, target)
    if found := _keyword_matches(words, page):
        return found
    if not words - OVERVIEW_WORDS or raw_words & {'summarize', 'summarise', 'summary', 'overview'}:
        return _overview(page)
    return (f'That is not on this page, as far as I can tell. I looked for: {", ".join(sorted(words)) or "(nothing)"}. '
            'In offline demo mode I can only match words, so a connected model may do better.')


def _measure(words: set[str]) -> str:
    for name, group in (('trend', TREND_WORDS), ('high', HIGH_WORDS), ('low', LOW_WORDS), ('mean', MEAN_WORDS),
                        ('sum', SUM_WORDS), ('count', COUNT_WORDS)):
        if words & group:
            return name
    return ''


def _overview(page: PageContext) -> str:
    if not page.elements:
        return 'I cannot read anything on this page.'
    lines = [f'This page, "{page.title or page.url}", shows:', '']
    for element in page.elements:
        if element.kind == 'button':
            continue
        lines.append(f'- {_describe(element)} [ref:{element.id}]')
    return '\n'.join(lines)


def _describe(element: ElementSnapshot) -> str:
    name = f'"{element.label}"' if element.label else ''
    if element.hidden_reason:
        return f'{element.kind} {name} (not visible now: {element.hidden_reason})'.replace('  ', ' ')
    if element.table:
        return f'table {name} with {len(element.table.rows):,} rows'.replace('  ', ' ')
    if element.series is not None:
        names = ', '.join(series.name for series in element.series if not series.hidden)
        return f'chart {name} with series {names}'.replace('  ', ' ')
    if element.has_value:
        return f'input {name} set to {element.value}'.replace('  ', ' ')
    if element.text:
        return f'text: {element.text[:120]}'
    return f'{element.kind} {name}'.strip()


def _describe_state(page: PageContext) -> str:
    lines = []
    for element in page.elements:
        if element.hidden_reason:
            continue
        if element.has_value:
            lines.append(f'- {element.label or element.kind} is set to {element.value} [ref:{element.id}]')
        if element.state:
            state = '; '.join(f'{key}: {value}' for key, value in element.state.items())
            lines.append(f'- {element.label or element.kind} has {state} [ref:{element.id}]')
    return 'The page currently has:\n\n' + '\n'.join(lines) if lines else 'I see no inputs or applied state on this page.'


def _best_numeric_target(words: set[str], page: PageContext) -> tuple[ElementSnapshot, str, object] | None:
    """Find the table column or chart series that best matches the question's words."""
    best = None
    best_score = -1
    for element in page.elements:
        if element.hidden_reason:
            continue
        label_score = len(words & _words(element.label))
        if element.table:
            for column in element.table.columns:
                if column_stats(element.table.rows[:2000], column)['type'] != 'number':
                    continue
                score = 2 * len(words & _words(f'{column} {element.table.label(column)}')) + label_score
                if score > best_score:
                    best, best_score = (element, column, element.table), score
        for series in element.series or ():
            if series.hidden:
                continue
            score = 2 * len(words & _words(series.name)) + label_score
            if score > best_score:
                best, best_score = (element, series.name, series), score
    return best


def _answer_measure(measure: str, target: tuple[ElementSnapshot, str, object]) -> str:
    element, name, data = target
    cite = f'[ref:{element.id}]'
    if isinstance(data, TableData):
        return _table_measure(measure, name, data, cite)
    return _series_measure(measure, name, data, cite)


def _series_measure(measure: str, name: str, series: Series, cite: str) -> str:
    summary = summarize_series(series.y, series.x, sketch_points=0)
    if not summary.get('numeric'):
        return f'The series "{name}" has no numeric values {cite}.'
    number = format_number
    if measure == 'high':
        return f'The highest value of "{name}" is {number(summary["max"])}, at {summary["max_at"]} {cite}.'
    if measure == 'low':
        return f'The lowest value of "{name}" is {number(summary["min"])}, at {summary["min_at"]} {cite}.'
    if measure == 'mean':
        return f'The average of "{name}" is {number(round(summary["mean"], 4))} {cite}.'
    if measure == 'sum':
        total = sum(value for value in (as_number(item) for item in series.y) if value is not None)
        return f'The total of "{name}" is {number(total)} {cite}.'
    if measure == 'count':
        return f'"{name}" has {summary["count"]:,} points {cite}.'
    change = summary['change_percent']
    detail = f', from {number(summary["first"])} to {number(summary["last"])}'
    detail += f' ({change:+.1f}%)' if change is not None else ''
    return f'The trend of "{name}" is {summary["trend"]}{detail} {cite}.'


def _table_measure(measure: str, column: str, table: TableData, cite: str) -> str:
    label = table.label(column)
    stats = column_stats(table.rows, column)
    number = format_number
    if measure == 'count':
        return f'The table shows {len(table.rows):,} rows {cite}.'
    if stats['type'] != 'number':
        return f'The column "{label}" is not numeric {cite}.'
    if measure in ('high', 'low'):
        wanted = stats['max'] if measure == 'high' else stats['min']
        word = 'highest' if measure == 'high' else 'lowest'
        row = next((row for row in table.rows if as_number(row.get(column)) == wanted), {})
        named = next((str(row[key]) for key in table.columns if key != column and isinstance(row.get(key), str)), '')
        suffix = f', on the row for {named}' if named else ''
        return f'The {word} {label} is {number(wanted)}{suffix} {cite}.'
    if measure == 'mean':
        return f'The average {label} is {number(round(stats["mean"], 4))} over {stats["count"]:,} rows {cite}.'
    if measure == 'sum':
        return f'The total {label} is {number(stats["sum"])} over {stats["count"]:,} rows {cite}.'
    return f'The "{label}" column goes from {number(stats["min"])} to {number(stats["max"])} {cite}.'


def _keyword_matches(words: set[str], page: PageContext) -> str:
    if not words:
        return ''
    scored = []
    for element in page.elements:
        if element.hidden_reason and not words & _words(element.label):
            continue
        haystack = _words(' '.join(str(part) for part in (element.label, element.text or '', element.description,
                                                          element.value if element.has_value else '') if part))
        score = len(words & haystack)
        if score and element.kind != 'button':
            scored.append((score, element))
    if not scored:
        return ''
    top = max(score for score, _ in scored)
    lines = [_keyword_line(element) for score, element in scored if score == top][:5]
    return '\n'.join(lines)


def _keyword_line(element: ElementSnapshot) -> str:
    extra = f' Note: {element.description}' if element.description else ''
    return f'{_describe(element)[0].upper()}{_describe(element)[1:]} [ref:{element.id}].{extra}'
