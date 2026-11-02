"""Read-only tools over one snapshot, so the model can fetch detail on demand (CTX-2).

They only read the snapshot built for this request. Anything the capture left out is
out of reach, and the tools have no way to change the page.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .page import PageContext, Series, TableData
from .summarize import as_number, column_stats, summarize_series

MAX_ROWS = 200
MAX_POINTS = 500


FILTER_OPS = ('equals', 'contains', 'gt', 'gte', 'lt', 'lte')


class ToolInputError(ValueError):
    """Invalid tool arguments. The message goes back to the model."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    function: Callable[[dict[str, Any]], str]

    def __call__(self, arguments: dict[str, Any]) -> str:
        return self.function(self.validate(arguments))

    def validate(self, arguments: Any) -> dict[str, Any]:
        """Check arguments against the schema. Models can send truncated or mistyped input."""
        if not isinstance(arguments, dict):
            raise ToolInputError('Arguments must be a JSON object.')
        properties = self.parameters['properties']
        for name in self.parameters.get('required', ()):
            if name not in arguments:
                raise ToolInputError(f'Missing required argument: {name}')
        cleaned = {}
        for name, value in arguments.items():
            if name not in properties:
                raise ToolInputError(f'Unknown argument: {name}')
            if value is None:
                continue
            expected = properties[name].get('type')
            valid = {
                'string': isinstance(value, str),
                'integer': isinstance(value, int) and not isinstance(value, bool),
                'boolean': isinstance(value, bool),
                'array': isinstance(value, list),
            }.get(expected, True)
            if not valid:
                raise ToolInputError(f'Argument {name} must be of type {expected}.')
            if 'enum' in properties[name] and value not in properties[name]['enum']:
                raise ToolInputError(f'Argument {name} must be one of {properties[name]["enum"]}.')
            cleaned[name] = value
        return cleaned


def page_tools(page: PageContext) -> list[Tool]:
    def table_of(arguments: dict[str, Any]) -> tuple[str, TableData]:
        element = page.element(arguments['element_id'])
        if element is None:
            raise ToolInputError(f'{arguments["element_id"]} is not on this page.')
        if element.table is None:
            raise ToolInputError(f'{element.id} is not a table.')
        element.table.apply_view()
        return element.id, element.table

    def column_of(table: TableData, name: str) -> str:
        for column in table.columns:
            if name in (column, table.label(column)):
                return column
        lowered = name.lower()
        for column in table.columns:
            if lowered in (column.lower(), table.label(column).lower()):
                return column
        raise ToolInputError(f'No column named {name}. Columns: {", ".join(table.columns)}')

    def filtered_rows(table: TableData, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        rows = table.rows
        for condition in arguments.get('filters', ()):
            if not isinstance(condition, dict) or not isinstance(condition.get('column'), str):
                raise ToolInputError('Each filter needs a column, an op and a value.')
            test = _condition_test(condition)
            column = column_of(table, condition['column'])
            rows = [row for row in rows if test(row.get(column))]
        return rows

    def get_rows(arguments: dict[str, Any]) -> str:
        element_id, table = table_of(arguments)
        rows = filtered_rows(table, arguments)
        if 'sort_by' in arguments:
            column = column_of(table, arguments['sort_by'])
            from .page import _sort_key

            rows = sorted(rows, key=lambda row: _sort_key(row.get(column)), reverse=arguments.get('descending', False))
        offset = max(arguments.get('offset', 0), 0)
        limit = min(max(arguments.get('limit', 50), 1), MAX_ROWS)
        shown = rows[offset:offset + limit]
        return json.dumps({
            'element_id': element_id,
            'matching_rows': len(rows),
            'offset': offset,
            'rows': [{column: row.get(column) for column in table.columns} for row in shown],
        }, default=str)

    def aggregate_rows(arguments: dict[str, Any]) -> str:
        element_id, table = table_of(arguments)
        column = column_of(table, arguments['column'])
        operation = arguments['operation']
        rows = filtered_rows(table, arguments)
        if 'group_by' not in arguments:
            return json.dumps({'element_id': element_id, 'column': column, 'operation': operation, 'matching_rows': len(rows),
                               'result': _aggregate(rows, column, operation)}, default=str)
        group_by = column_of(table, arguments['group_by'])
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(str(row.get(group_by)), []).append(row)
        results = {name: _aggregate(rows, column, operation) for name, rows in groups.items()}
        ordered = sorted(results.items(), key=lambda item: as_number(item[1]) or 0, reverse=True)[:MAX_ROWS]
        return json.dumps({'element_id': element_id, 'column': column, 'operation': operation,
                           'group_by': group_by, 'groups': len(results), 'result': dict(ordered)}, default=str)

    def get_series(arguments: dict[str, Any]) -> str:
        element = page.element(arguments['element_id'])
        if element is None:
            raise ToolInputError(f'{arguments["element_id"]} is not on this page.')
        if element.series is None:
            raise ToolInputError(f'{element.id} is not a chart.')
        visible = [series for series in element.series if not series.hidden]
        if 'series' in arguments:
            visible = [series for series in visible if series.name.lower() == arguments['series'].lower()]
            if not visible:
                raise ToolInputError(f'No visible series named {arguments["series"]}.')
        start = max(arguments.get('start', 0), 0)
        count = min(max(arguments.get('count', MAX_POINTS), 1), MAX_POINTS)
        return json.dumps({'element_id': element.id, 'series': [_series_part(series, start, count) for series in visible]},
                          default=str)

    def get_element(arguments: dict[str, Any]) -> str:
        element = page.element(arguments['element_id'])
        if element is None:
            raise ToolInputError(f'{arguments["element_id"]} is not on this page.')
        return json.dumps({
            'id': element.id, 'kind': element.kind, 'label': element.label, 'text': element.text,
            'value': element.value if element.has_value else None, 'options': element.options,
            'state': element.state, 'description': element.description, 'developer_data': element.extra,
            'section': element.section, 'hidden_reason': element.hidden_reason,
        }, default=str)

    element_id = {'type': 'string', 'description': 'The element ID from the page state, for example table-12.'}
    filters = {
        'type': 'array',
        'description': 'Conditions a row must all meet. Text comparisons ignore case.',
        'items': {'type': 'object', 'properties': {
            'column': {'type': 'string'},
            'op': {'type': 'string', 'enum': list(FILTER_OPS)},
            'value': {'type': ['string', 'number']},
        }, 'required': ['column', 'op', 'value']},
    }
    return [
        Tool(
            'get_rows',
            'Read rows of a table as the user currently sees it, after their filters. Can also filter further and sort.',
            {'type': 'object', 'properties': {
                'element_id': element_id,
                'offset': {'type': 'integer', 'description': 'First row to return. Default 0.'},
                'limit': {'type': 'integer', 'description': f'Rows to return. Default 50, at most {MAX_ROWS}.'},
                'filters': filters,
                'sort_by': {'type': 'string', 'description': 'Column to sort by.'},
                'descending': {'type': 'boolean', 'description': 'Sort from high to low.'},
            }, 'required': ['element_id']},
            get_rows,
        ),
        Tool(
            'aggregate_rows',
            'Compute an exact sum, mean, min, max, count or distinct count over a table, optionally per group. '
            'Use this rather than adding up rows yourself.',
            {'type': 'object', 'properties': {
                'element_id': element_id,
                'column': {'type': 'string', 'description': 'Column to aggregate.'},
                'operation': {'type': 'string', 'enum': ['sum', 'mean', 'min', 'max', 'count', 'distinct']},
                'group_by': {'type': 'string', 'description': 'Column to group by. Largest results come first.'},
                'filters': filters,
            }, 'required': ['element_id', 'column', 'operation']},
            aggregate_rows,
        ),
        Tool(
            'get_series',
            'Read raw points of a chart, respecting the zoom and hidden series the user has applied.',
            {'type': 'object', 'properties': {
                'element_id': element_id,
                'series': {'type': 'string', 'description': 'Series name. Default: all visible series.'},
                'start': {'type': 'integer', 'description': 'First point to return. Default 0.'},
                'count': {'type': 'integer', 'description': f'Points to return, at most {MAX_POINTS}.'},
            }, 'required': ['element_id']},
            get_series,
        ),
        Tool(
            'get_element',
            'Read everything captured about one element, without length limits on its text.',
            {'type': 'object', 'properties': {'element_id': element_id}, 'required': ['element_id']},
            get_element,
        ),
    ]


def _condition_test(condition: dict[str, Any]) -> Callable[[Any], bool]:
    """Build a check for one filter. Numbers compare as numbers, and everything else as text."""
    operator, wanted = condition.get('op'), condition.get('value')
    if operator not in FILTER_OPS or wanted is None:
        raise ToolInputError(f'Each filter needs a value and an op, one of {", ".join(FILTER_OPS)}.')
    text = str(wanted).lower()
    number = as_number(wanted)
    if operator == 'contains':
        return lambda value: text in str('' if value is None else value).lower()
    if operator == 'equals':
        return lambda value: (as_number(value) == number) if number is not None and as_number(value) is not None \
            else str('' if value is None else value).lower() == text
    if number is None:
        raise ToolInputError(f'{operator} needs a number.')
    compare = {'gt': float.__gt__, 'gte': float.__ge__, 'lt': float.__lt__, 'lte': float.__le__}[operator]

    def check(value: Any) -> bool:
        actual = as_number(value)
        return actual is not None and compare(actual, number)

    return check


def _aggregate(rows: list[dict[str, Any]], column: str, operation: str) -> Any:
    if operation == 'count':
        return sum(1 for row in rows if row.get(column) not in (None, ''))
    if operation == 'distinct':
        return len({str(row.get(column)) for row in rows if row.get(column) not in (None, '')})
    stats = column_stats(rows, column)
    if stats['type'] != 'number':
        raise ToolInputError(f'Column {column} is not numeric.')
    return stats[operation]


def _series_part(series: Series, start: int, count: int) -> dict[str, Any]:
    part: dict[str, Any] = {
        'name': series.name,
        'total_points': len(series.y),
        'start': start,
        'y': series.y[start:start + count],
        'summary': {key: value for key, value in summarize_series(series.y, series.x, sketch_points=0).items()},
    }
    if series.x is not None:
        part['x'] = series.x[start:start + count]
    return part
