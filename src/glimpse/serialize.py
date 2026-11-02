"""Turn a snapshot into model input. Any function with this shape can replace the default (CAP-9)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .page import ElementSnapshot, PageContext, Series, TableData
from .summarize import column_stats, format_number, summarize_series


@dataclass(frozen=True)
class Detail:
    """How much of each element to include. The budget picks a level from LADDER."""

    rows: int = 50
    points: int = 120
    text: int = 2000
    cell: int = 200
    manifest_only: bool = False


LADDER = (
    Detail(rows=50, points=120, text=2000, cell=200),
    Detail(rows=25, points=60, text=1000, cell=120),
    Detail(rows=10, points=24, text=400, cell=80),
    Detail(rows=0, points=0, text=160, cell=60),
    Detail(rows=0, points=0, text=80, cell=40, manifest_only=True),
)

Serializer = Callable[[PageContext, Detail], str]


def _clip(text: Any, limit: int) -> str:
    text = str(text).replace('\r', ' ').replace('\n', ' ').strip()
    return text if len(text) <= limit else text[:limit] + '…'


def _format_state(state: dict[str, Any]) -> str:
    return '; '.join(f'{key}: {_clip(json.dumps(value, default=str), 200)}' for key, value in state.items())


def text_serializer(page: PageContext, detail: Detail) -> str:
    """The default format: compact plain text with an element ID on every entry."""
    lines = [f'Page: {_clip(page.title, 200) or "(untitled)"} ({page.url})']
    if page.visibility != 'visible':
        lines.append(f'Visibility policy: {page.visibility}. Entries marked "not visible" are not on screen now.')
    lines.extend(f'Capture note: {_clip(note, 400)}' for note in page.notes)
    if not page.elements:
        lines.append('No readable elements were found on this page.')
    section = None
    for element in page.elements:
        if element.section != section:
            section = element.section
            lines.append(f'\n## {_clip(section, 120)}' if section else '')
        lines.extend(_element_lines(element, detail))
    return '\n'.join(lines)


def _element_lines(element: ElementSnapshot, detail: Detail) -> list[str]:
    head = f'[{element.id}] {element.kind}'
    if element.label:
        head += f' "{_clip(element.label, 160)}"'
    if element.hidden_reason:
        head += f' (not visible: {_clip(element.hidden_reason, 120)})'
    if not element.readable:
        head += ' (no readable data)'
    if element.has_value:
        head += f' = {_clip(_value_text(element.value), detail.text)}'
    if element.text and not detail.manifest_only:
        head += f': {_clip(element.text, detail.text)}'
    lines = [head]
    if element.description:
        lines.append(f'  Description: {_clip(element.description, 1000)}')
    if element.extra is not None:
        lines.append(f'  Developer data: {_clip(_value_text(element.extra), 1000)}')
    if element.options and not detail.manifest_only:
        lines.append(f'  Options: {_clip(", ".join(str(option) for option in element.options[:40]), 400)}')
    if element.state:
        lines.append(f'  Applied state: {_format_state(element.state)}')
    if element.table:
        lines.extend(_table_lines(element.id, element.table, detail))
    if element.series is not None:
        lines.extend(_series_lines(element.id, element.series, detail))
    return lines


def _value_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


def _table_lines(element_id: str, table: TableData, detail: Detail) -> list[str]:
    shown = table.rows[: detail.rows]
    total = len(table.rows)
    source = table.source_rows if table.source_rows is not None else total
    columns = ', '.join(table.label(column) for column in table.columns)
    lines = [f'  Columns: {_clip(columns, 600)}']
    count = f'{total:,} rows' if total == source else f'{total:,} of {source:,} rows after the filter'
    if detail.manifest_only:
        lines.append(f'  {count.capitalize()}. Call get_rows("{element_id}") to read them.')
        return lines
    if len(shown) < total:
        lines.append(f'  Showing {len(shown):,} of {total:,} rows ({count}). This limit is only on what is listed here, '
                     'not on what the user can see, so do not tell the user it is. '
                     f'Call get_rows("{element_id}") or aggregate_rows("{element_id}") for the rest.')
    else:
        lines.append(f'  Showing all {count}.')
    if len(shown) < total:
        lines.append('  Column statistics over all of these rows:')
        for column in table.columns:
            lines.append(f'    {_clip(table.label(column), 80)}: {_stats_text(column_stats(table.rows, column), detail)}')
    if shown:
        lines.append('  | ' + ' | '.join(_clip(table.label(column), detail.cell) for column in table.columns) + ' |')
        for row in shown:
            lines.append('  | ' + ' | '.join(_cell(row.get(column), detail) for column in table.columns) + ' |')
    return lines


def _cell(value: Any, detail: Detail) -> str:
    return _clip('' if value is None else format_number(value), detail.cell).replace('|', '/')


def _stats_text(stats: dict[str, Any], detail: Detail) -> str:
    if stats['type'] == 'number':
        return (f'min {format_number(stats["min"])}, max {format_number(stats["max"])}, '
                f'mean {format_number(round(stats["mean"], 4))}, sum {format_number(stats["sum"])}, '
                f'{stats["count"]:,} values, {stats["missing"]:,} missing')
    top = ', '.join(f'{_clip(name, detail.cell)} ({count:,})' for name, count in stats['top'])
    return f'{stats["distinct"]:,} distinct values, most common: {top}; {stats["missing"]:,} missing'


def _series_lines(element_id: str, series_list: list[Series], detail: Detail) -> list[str]:
    lines: list[str] = []
    hidden = [series.name for series in series_list if series.hidden]
    if hidden:
        lines.append(f'  Hidden by the user: {_clip(", ".join(hidden), 300)}')
    for series in series_list:
        if series.hidden:
            continue
        lines.extend(_one_series_lines(element_id, series, detail))
    return lines


def _one_series_lines(element_id: str, series: Series, detail: Detail) -> list[str]:
    title = f'  Series "{_clip(series.name, 120)}"' + (f' ({series.kind})' if series.kind else '')
    window = ''
    if series.total_points is not None and series.total_points != len(series.y):
        window = f', zoomed to {len(series.y):,} of {series.total_points:,} points'
    if detail.manifest_only:
        return [f'{title}: {len(series.y):,} points{window}. Call get_series("{element_id}") to read them.']
    if len(series.y) <= detail.points:
        pairs = ', '.join(f'{_x(series, index)}={_y(value)}' for index, value in enumerate(series.y))
        return [f'{title}{window}: {pairs}']
    sketch_size = min(detail.points, 24)
    summary = summarize_series(series.y, series.x, sketch_points=sketch_size)
    if not summary.get('numeric'):
        return [f'{title}: {len(series.y):,} points with no numeric values']
    change = summary['change_percent']
    lines = [
        f'{title}: showing a summary of {len(series.y):,} points{window}. '
        f'Call get_series("{element_id}") for raw values.',
        f'    min {_y(summary["min"])} at {_clip(summary["min_at"], 60)}, '
        f'max {_y(summary["max"])} at {_clip(summary["max_at"], 60)}, mean {_y(round(summary["mean"], 4))}, '
        f'first {_y(summary["first"])} at {_clip(summary["first_at"], 60)}, '
        f'last {_y(summary["last"])} at {_clip(summary["last_at"], 60)}, trend {summary["trend"]}'
        + (f', change {change:+.1f}%' if change is not None else ''),
    ]
    if summary.get('sketch'):
        pairs = ', '.join(f'{_clip(x, 40)}={_y(y)}' for x, y in summary['sketch'])
        lines.append(f'    Sampled shape (a sample, not every point): {pairs}')
    return lines


def _x(series: Series, index: int) -> str:
    return _clip(series.x[index], 40) if series.x is not None and index < len(series.x) else str(index)


def _y(value: Any) -> str:
    return 'null' if value is None else _clip(format_number(value), 40)


def json_serializer(page: PageContext, detail: Detail) -> str:
    """An alternative format, as compact JSON. Pass serializer=glimpse.json_serializer to attach()."""
    elements = []
    for element in page.elements:
        item: dict[str, Any] = {'id': element.id, 'kind': element.kind, 'label': element.label}
        for name in ('section', 'description', 'hidden_reason'):
            if getattr(element, name):
                item[name] = getattr(element, name)
        if element.text and not detail.manifest_only:
            item['text'] = _clip(element.text, detail.text)
        if element.has_value:
            item['value'] = element.value
        if element.state:
            item['state'] = element.state
        if element.table:
            rows = element.table.rows[: detail.rows]
            item['table'] = {'columns': element.table.columns, 'rows': rows, 'total_rows': len(element.table.rows),
                             'source_rows': element.table.source_rows}
            if len(rows) < len(element.table.rows):
                item['table']['notice'] = (f'Showing {len(rows):,} of {len(element.table.rows):,} rows. '
                                           f'Call get_rows("{element.id}") for the rest.')
        if element.series is not None:
            item['series'] = [_json_series(series, detail) for series in element.series if not series.hidden]
        elements.append(item)
    return json.dumps({'url': page.url, 'title': page.title, 'notes': page.notes, 'elements': elements}, default=str)


def _json_series(series: Series, detail: Detail) -> dict[str, Any]:
    if len(series.y) <= detail.points:
        return {'name': series.name, 'x': series.x, 'y': series.y}
    return {'name': series.name, 'summary': summarize_series(series.y, series.x, sketch_points=min(detail.points, 24))}
