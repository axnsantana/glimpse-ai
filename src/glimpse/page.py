"""PageContext: the framework-neutral snapshot of one page at one moment."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tools import Tool

WITHHELD_VALUE = '[withheld]'
"""Stands in for the value of a password or other sensitive input."""


@dataclass
class Series:
    """One series of a chart, after any zoom in the browser is applied."""

    name: str
    y: list[Any]
    x: list[Any] | None = None
    kind: str = ''
    hidden: bool = False
    total_points: int | None = None
    """Points before zoom, when the zoom shows only some of them."""


@dataclass
class TableData:
    """A table as the user sees it. Call apply_view() once to filter and sort rows."""

    columns: list[str]
    rows: list[dict[str, Any]]
    labels: dict[str, str] = field(default_factory=dict)
    source_rows: int | None = None
    """Rows before any filter. Defaults to len(rows)."""
    filter_text: str = ''
    sort_by: str = ''
    descending: bool = False
    dotted_fields: bool = False
    """Whether a column such as "a.b" reads a nested value, as AG Grid does."""
    view_applied: bool = False

    def apply_view(self) -> None:
        """Keep only the columns on screen, then apply filter_text and sort_by as the browser does.

        Rows are often dicts with more keys than the table displays. Projecting them here
        means that fields the user cannot see, or that were excluded, never reach an engine.
        This can be slow on large tables, so it runs outside the event loop.
        """
        if self.view_applied:
            return
        self.view_applied = True
        if self.source_rows is None:
            self.source_rows = len(self.rows)
        self.rows = [
            {column: _read_field(row, column, self.dotted_fields) for column in self.columns}
            for row in self.rows
        ]
        if self.filter_text:
            needle = self.filter_text.lower()
            self.rows = [
                row for row in self.rows
                if any(needle in str(row.get(column, '')).lower() for column in self.columns)
            ]
        if self.sort_by:
            self.rows = sorted(self.rows, key=lambda row: _sort_key(row.get(self.sort_by)), reverse=self.descending)

    def label(self, column: str) -> str:
        return self.labels.get(column) or column


def _read_field(row: Any, column: str, dotted: bool) -> Any:
    if not isinstance(row, dict):
        return None
    if column in row or not dotted:
        return row.get(column)
    value: Any = row
    for part in column.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _sort_key(value: Any) -> tuple[int, float, str]:
    if isinstance(value, bool) or value is None:
        return (2, 0, str(value))
    if isinstance(value, (int, float)) and not math.isnan(value):
        return (0, float(value), '')
    return (1, 0, str(value).lower())


@dataclass
class ElementSnapshot:
    """One element on the page. The id is stable for the element's lifetime and is what answers cite."""

    id: str
    kind: str
    label: str = ''
    description: str = ''
    text: str | None = None
    value: Any = None
    has_value: bool = False
    options: list[Any] | None = None
    state: dict[str, Any] = field(default_factory=dict)
    table: TableData | None = None
    series: list[Series] | None = None
    extra: Any = None
    """Data added with glimpse.describe(value=...)."""
    section: str = ''
    """Where the element sits, for example "Tab: Orders"."""
    readable: bool = True
    """False for widgets whose data cannot be read, such as a 3D scene."""
    hidden_reason: str = ''
    """Why the user cannot see this now. Only set for stubs and reachable content."""
    dom_id: str = ''
    """The browser element to scroll to when an answer cites this element."""


@dataclass
class ContextReport:
    """What went into a request. The panel's inspector shows it."""

    budget: int = 0
    usable: int = 0
    """The budget, less the safety margin kept when tokens are only estimated."""
    system_tokens: int = 0
    page_tokens: int = 0
    history_tokens: int = 0
    question_tokens: int = 0
    context_tokens: int = 0
    detail_level: int = 0
    dropped_messages: int = 0
    truncated_page: bool = False

    @property
    def used(self) -> int:
        return (self.system_tokens + self.page_tokens + self.history_tokens + self.question_tokens
                + self.context_tokens)

    @property
    def remaining(self) -> int:
        return max((self.usable or self.budget) - self.used, 0)


@dataclass
class PageContext:
    """The snapshot handed to an engine, together with its budgeted text form."""

    url: str = ''
    title: str = ''
    elements: list[ElementSnapshot] = field(default_factory=list)
    developer_context: str = ''
    notes: list[str] = field(default_factory=list)
    """Limits of this capture, such as a browser probe that timed out. Always sent to the model."""
    visibility: str = 'visible'
    captured_at: float = field(default_factory=time.time)
    rendered: str = ''
    """The page as text, already fitted to the budget. Filled in before the engine runs."""
    report: ContextReport = field(default_factory=ContextReport)

    def element(self, element_id: str) -> ElementSnapshot | None:
        for element in self.elements:
            if element.id == element_id:
                return element
        return None

    def manifest(self) -> list[dict[str, Any]]:
        """A compact list of what is on the page."""
        return [
            {'id': element.id, 'kind': element.kind, 'label': element.label, 'section': element.section,
             'hidden_reason': element.hidden_reason}
            for element in self.elements
        ]

    def to_prompt(self) -> str:
        """The developer context and page state, fenced for use in a model prompt."""
        from .prompt import page_block

        return page_block(self)

    @property
    def tools(self) -> list[Tool]:
        """Read-only tools that fetch more of this snapshot on demand."""
        from .tools import page_tools

        return page_tools(self)
