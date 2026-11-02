"""Read state that only the browser holds: grid filters and sort, chart zoom and legend (CAP-5).

The probe asks the browser for facts, not data. A grid returns row indices, and the server
looks those rows up in its own copy. That keeps messages small, and it means a tampered
browser can only change what its own user's assistant is told about row order.

If the probe fails, the page is still captured from the server, and the context says so. A
silent failure here would produce confident answers about rows the user has filtered out.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from nicegui.client import Client

from ...config import GlimpseConfig
from ...page import ElementSnapshot, Series

log = logging.getLogger('glimpse')

MAX_INDICES = 50_000
"""Keeps the reply under Socket.IO's 1 MB message limit. Past that, the context says rows are partial."""
MAX_SELECTED = 20

_SCRIPT = r'''
const safe = (read) => { try { return read(); } catch (error) { return {error: String(error)}; } };
const out = {grids: {}, echarts: {}, plotlies: {}};
for (const id of %(grids)s) out.grids[id] = safe(() => {
  const api = getElement(id).api;
  const rows = [];
  let total = 0;
  api.forEachNodeAfterFilterAndSort((node) => {
    if (node.group) return;
    total += 1;
    if (rows.length < %(max_indices)d) rows.push(node.sourceRowIndex);
  });
  const paginated = api.paginationIsLastPageFound ? api.getGridOption('pagination') : false;
  return {
    rows, total,
    filter: api.getFilterModel(),
    quick: api.getGridOption('quickFilterText') || '',
    sort: api.getColumnState().filter((c) => c.sort)
      .sort((a, b) => (a.sortIndex || 0) - (b.sortIndex || 0)).map((c) => [c.colId, c.sort]),
    displayed: api.getAllDisplayedColumns().map((c) => c.getColDef().field || c.getColId()),
    selected: api.getSelectedNodes().slice(0, %(max_selected)d).map((n) => n.sourceRowIndex),
    selected_count: api.getSelectedNodes().length,
    page: paginated ? api.paginationGetCurrentPage() + 1 : null,
    page_size: paginated ? api.paginationGetPageSize() : null,
  };
});
for (const id of %(echarts)s) out.echarts[id] = safe(() => {
  const option = getElement(id).chart.getOption();
  const zoom = (option.dataZoom || [])[0];
  return {
    zoom: zoom ? {start: zoom.start, end: zoom.end, startValue: zoom.startValue, endValue: zoom.endValue} : null,
    legend: option.legend && option.legend[0] ? option.legend[0].selected : null,
  };
});
for (const id of %(plotlies)s) out.plotlies[id] = safe(() => {
  const plot = getElement(id).$el;
  const axis = plot.layout.xaxis || {};
  return {range: axis.autorange ? null : axis.range, visible: plot.data.map((t) => t.visible === undefined ? true : t.visible)};
});
return out;
'''


def build_script(grids: list[int], echarts: list[int], plotlies: list[int]) -> str:
    """Build the probe. Only integer element IDs go into the script."""
    return _SCRIPT % {
        'grids': [int(value) for value in grids],
        'echarts': [int(value) for value in echarts],
        'plotlies': [int(value) for value in plotlies],
        'max_indices': MAX_INDICES,
        'max_selected': MAX_SELECTED,
    }


async def apply_browser_state(client: Client, walker: Any, config: GlimpseConfig) -> None:
    if not (walker.grids or walker.echarts or walker.plotlies):
        return
    script = build_script([element.id for element, _ in walker.grids],
                          [element.id for element, _, _ in walker.echarts],
                          [element.id for element, _ in walker.plotlies])
    try:
        result = await client.run_javascript(script, timeout=config.probe_timeout)
    except Exception as error:  # A timeout, or a client that has gone away.
        log.debug('Glimpse browser probe failed: %s', error)
        walker.notes.append(_unavailable_note(walker))
        return
    if not isinstance(result, dict):
        walker.notes.append(_unavailable_note(walker))
        return
    for element, snapshot in walker.grids:
        apply_grid_state(snapshot, _entry(result, 'grids', element.id), walker.notes)
    for element, snapshot, axis_type in walker.echarts:
        apply_echart_state(snapshot, _entry(result, 'echarts', element.id), axis_type, walker.notes)
    for element, snapshot in walker.plotlies:
        apply_plotly_state(snapshot, _entry(result, 'plotlies', element.id), walker.notes)


def _entry(result: dict, group: str, element_id: int) -> dict:
    entries = result.get(group)
    entry = entries.get(str(element_id)) if isinstance(entries, dict) else None
    return entry if isinstance(entry, dict) else {'error': 'missing'}


def _unavailable_note(walker: Any) -> str:
    return ('The browser did not report its current state. Any grid filter or sort, chart zoom, or hidden legend '
            'entry the user applied in the browser is unknown, so tables and charts below may include data the '
            'user has filtered out or hidden. Say so if it matters to the answer.')


def _element_note(snapshot: ElementSnapshot) -> str:
    return (f'{snapshot.id} did not report its browser state, so it may include data the user has filtered out or '
            'hidden.')


def apply_grid_state(snapshot: ElementSnapshot, state: dict, notes: list[str]) -> None:
    table = snapshot.table
    if table is None:
        return
    if 'error' in state or not isinstance(state.get('rows'), list):
        notes.append(_element_note(snapshot))
        return
    source = table.rows
    indices = [index for index in state['rows'] if isinstance(index, int) and 0 <= index < len(source)]
    total = state.get('total') if isinstance(state.get('total'), int) else len(indices)
    table.rows = [source[index] for index in indices]
    table.source_rows = len(source)
    if total > len(indices):
        notes.append(f'{snapshot.id}: the browser reported only the first {len(indices):,} of {total:,} displayed rows, '
                     'so statistics cover those rows only.')
    if state.get('filter'):
        snapshot.state['filter'] = state['filter']
    if state.get('quick'):
        snapshot.state['quick_filter'] = state['quick']
    if state.get('sort'):
        snapshot.state['sorted_by'] = [f'{table.label(str(column))} {direction}' for column, direction in state['sort']
                                       if str(column) in table.columns]
    displayed = state.get('displayed')
    if isinstance(displayed, list) and displayed:
        table.columns = [str(column) for column in displayed if str(column) in table.columns] or table.columns
    if state.get('selected_count'):
        snapshot.state['selected_rows'] = state['selected_count']
        chosen = [source[index] for index in state.get('selected') or []
                  if isinstance(index, int) and 0 <= index < len(source)]
        if chosen and table.columns:
            first = table.columns[0]
            snapshot.state['selected'] = [row.get(first) if isinstance(row, dict) else None for row in chosen]
    if state.get('page') and state.get('page_size'):
        snapshot.state['page'] = state['page']
        snapshot.state['rows_per_page'] = state['page_size']


def apply_echart_state(snapshot: ElementSnapshot, state: dict, axis_type: str, notes: list[str]) -> None:
    if snapshot.series is None:
        return
    if 'error' in state:
        notes.append(_element_note(snapshot))
        return
    legend = state.get('legend')
    if isinstance(legend, dict):
        for series in snapshot.series:
            if legend.get(series.name) is False:
                series.hidden = True
    zoom = state.get('zoom')
    if not isinstance(zoom, dict):
        return
    start, end = zoom.get('start'), zoom.get('end')
    if not (isinstance(start, (int, float)) and isinstance(end, (int, float))) or (start <= 0 and end >= 100):
        return
    snapshot.state['zoom'] = f'{start:g}% to {end:g}% of the axis'
    for series in snapshot.series:
        _zoom_echart_series(series, zoom, axis_type)


def _zoom_echart_series(series: Series, zoom: dict, axis_type: str) -> None:
    count = len(series.y)
    if not count:
        return
    start_value, end_value = zoom.get('startValue'), zoom.get('endValue')
    if axis_type == 'category' and isinstance(start_value, int) and isinstance(end_value, int):
        first, last = start_value, end_value
    elif (axis_type == 'value' and series.x is not None and _all_numbers(series.x)
          and _is_number(start_value) and _is_number(end_value)):
        kept = [index for index, x in enumerate(series.x) if start_value <= x <= end_value]
        if kept:
            first, last = kept[0], kept[-1]
        else:
            first, last = 0, -1
    else:
        # A time axis, or anything else: fall back on the percentage of the axis.
        first = math.floor(zoom['start'] / 100 * (count - 1))
        last = math.ceil(zoom['end'] / 100 * (count - 1))
    _keep(series, first, last)


def _keep(series: Series, first: int, last: int) -> None:
    series.total_points = len(series.y)
    first, last = max(first, 0), min(last, len(series.y) - 1)
    series.y = series.y[first:last + 1]
    if series.x is not None:
        series.x = series.x[first:last + 1]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _all_numbers(values: list[Any]) -> bool:
    return all(_is_number(value) for value in values)


def apply_plotly_state(snapshot: ElementSnapshot, state: dict, notes: list[str]) -> None:
    if snapshot.series is None:
        return
    if 'error' in state:
        notes.append(_element_note(snapshot))
        return
    visible = state.get('visible')
    if isinstance(visible, list):
        for series, flag in zip(snapshot.series, visible, strict=False):
            if flag in (False, 'legendonly'):
                series.hidden = True
    window = state.get('range')
    if not (isinstance(window, list) and len(window) == 2):
        return
    low, high = window
    snapshot.state['zoom'] = f'x axis from {low} to {high}'
    for series in snapshot.series:
        if series.x is None:
            if _is_number(low) and _is_number(high):
                _keep(series, math.ceil(low), math.floor(high))
            continue
        if _all_numbers(series.x) and _is_number(low) and _is_number(high):
            kept = [index for index, x in enumerate(series.x) if low <= x <= high]
        elif _is_number(low) and _is_number(high):
            # Plotly gives category axes a numeric range by position.
            kept = [index for index in range(len(series.x)) if low <= index <= high]
        else:
            kept = [index for index, x in enumerate(series.x) if str(low) <= str(x) <= str(high)]
        if kept:
            _keep(series, kept[0], kept[-1])
        else:
            _keep(series, 0, -1)
