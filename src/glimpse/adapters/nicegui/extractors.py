"""Read each kind of NiceGUI element into a framework-neutral snapshot, with no annotations (CAP-1, CAP-3)."""

from __future__ import annotations

import base64
import html.parser
import re
import struct
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any

from nicegui.element import Element

from ...page import WITHHELD_VALUE, ElementSnapshot, Series, TableData
from . import _compat

DEFAULT_SENSITIVE = re.compile(
    r'pass\s*(word|wd|phrase|code)|\bpwd\b|\bsecret\b|\b(access|auth|api|refresh|bearer|session)[-_ ]?(token|key)\b'
    r'|^token$|private[-_ ]?key|\bssn\b|social security|credit[-_ ]?card|card[-_ ]?number|\bcvv\b|\bcvc\b',
    re.IGNORECASE,
)
HIDDEN_CLASSES = frozenset({'hidden', 'invisible', 'sr-only', 'opacity-0'})
MAX_STATE_ITEMS = 20


def is_css_hidden(classes: Collection[str], styles: dict[str, str]) -> bool:
    """Detect the usual ways to hide text, which is also how hidden prompt injection works."""
    if HIDDEN_CLASSES.intersection(classes):
        return True
    return _style_hides(styles)


def _style_hides(styles: dict[str, str]) -> bool:
    def number(name: str) -> float | None:
        match = re.match(r'\s*(-?[\d.]+)', styles.get(name, ''))
        return float(match.group(1)) if match else None

    if styles.get('display', '').strip().lower() == 'none':
        return True
    if styles.get('visibility', '').strip().lower() in ('hidden', 'collapse'):
        return True
    return number('opacity') == 0 or number('font-size') == 0


def field_is_excluded(name: str, exclude: Collection[Any]) -> bool:
    if not name:
        return False
    if DEFAULT_SENSITIVE.search(name):
        return True
    for rule in exclude:
        if isinstance(rule, str):
            if rule.casefold() == name.casefold():
                return True
        elif rule.search(name):
            return True
    return False


class _VisibleText(html.parser.HTMLParser):
    """Text of an HTML fragment that a user would see. Skips scripts, comments and hidden nodes."""

    VOID = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.VOID:
            return
        if self.hidden_depth or tag in ('script', 'style', 'template', 'head', 'noscript') or self._hides(attrs):
            self.hidden_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        pass

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.VOID and self.hidden_depth:
            self.hidden_depth -= 1
        if tag in ('p', 'div', 'li', 'tr', 'br', 'h1', 'h2', 'h3', 'h4'):
            self.parts.append(' ')

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)

    @staticmethod
    def _hides(attrs: list[tuple[str, str | None]]) -> bool:
        attributes = dict(attrs)
        if 'hidden' in attributes or attributes.get('aria-hidden') == 'true':
            return True
        if is_css_hidden((attributes.get('class') or '').split(), {}):
            return True
        styles = {}
        for declaration in (attributes.get('style') or '').split(';'):
            if ':' in declaration:
                key, value = declaration.split(':', 1)
                styles[key.strip().lower()] = value.strip()
        return _style_hides(styles)


def visible_text_of_html(markup: str) -> str:
    parser = _VisibleText()
    parser.feed(markup)
    parser.close()
    return re.sub(r'\s+', ' ', ''.join(parser.parts)).strip()


def strip_markdown_comments(markup: str) -> str:
    return re.sub(r'<!--.*?-->', '', markup, flags=re.DOTALL).strip()


@dataclass(frozen=True)
class Extractor:
    function: Callable[[Element, Any], ElementSnapshot | None]
    descend: bool = False
    """Whether to read the children too. Data widgets keep theirs to themselves."""


def label_of(element: Element) -> str:
    """The name a user would give this element: its own label, or a short text right before it."""
    props = _compat.props_of(element)
    for name in ('label', 'aria-label', 'title', 'placeholder'):
        value = props.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def nearby_label(element: Element) -> str:
    previous = _compat.previous_sibling(element)
    if previous is not None and 'TextElement' in _compat.class_names(previous):
        text = str(getattr(previous, 'text', '') or '').strip()
        if 0 < len(text) <= 80:
            return text
    return ''


def _snapshot(element: Element, walker: Any, kind: str, **fields: Any) -> ElementSnapshot:
    return ElementSnapshot(id=f'{kind}-{element.id}', kind=kind, dom_id=element.html_id, **fields)


# Text and simple content.


def text_element(element: Element, walker: Any) -> ElementSnapshot | None:
    text = str(getattr(element, 'text', '') or '').strip()
    return _snapshot(element, walker, 'text', text=text) if text else None


def button(element: Element, walker: Any) -> ElementSnapshot | None:
    text = str(getattr(element, 'text', '') or '').strip()
    return _snapshot(element, walker, 'button', label=text) if text else None


def link(element: Element, walker: Any) -> ElementSnapshot | None:
    # The target is left out: URLs can carry tokens, and models should not be handed them to repeat.
    text = str(getattr(element, 'text', '') or '').strip()
    return _snapshot(element, walker, 'link', label=text) if text else None


def markdown(element: Element, walker: Any) -> ElementSnapshot | None:
    text = strip_markdown_comments(str(getattr(element, 'content', '') or ''))
    return _snapshot(element, walker, 'text', text=visible_text_of_html(text) if '<' in text else text) if text else None


def html_element(element: Element, walker: Any) -> ElementSnapshot | None:
    text = visible_text_of_html(str(getattr(element, 'content', '') or ''))
    return _snapshot(element, walker, 'text', text=text) if text else None


def code(element: Element, walker: Any) -> ElementSnapshot | None:
    content = str(getattr(element, 'content', '') or '')
    return _snapshot(element, walker, 'code', text=content, label=str(getattr(element, 'language', '') or ''))


def mermaid(element: Element, walker: Any) -> ElementSnapshot | None:
    return _snapshot(element, walker, 'diagram', text=str(getattr(element, 'content', '') or ''))


def chat_message(element: Element, walker: Any) -> ElementSnapshot | None:
    props = _compat.props_of(element)
    text = props.get('text')
    text = ' '.join(str(part) for part in text) if isinstance(text, list) else str(text or '')
    return _snapshot(element, walker, 'message', label=str(props.get('name') or ''), text=visible_text_of_html(text))


def tree(element: Element, walker: Any) -> ElementSnapshot | None:
    props = _compat.props_of(element)
    state = {}
    if props.get('selected') is not None:
        state['selected'] = props['selected']
    if props.get('ticked'):
        state['ticked'] = props['ticked']
    if props.get('expanded'):
        state['expanded'] = props['expanded']
    labels = _tree_labels(props.get('nodes') or [], props.get('label-key', 'label'))
    return _snapshot(element, walker, 'tree', text=', '.join(labels[:200]), state=state)


def _tree_labels(nodes: list[dict], key: str) -> list[str]:
    labels: list[str] = []
    for node in nodes:
        labels.append(str(node.get(key, '')))
        labels.extend(_tree_labels(node.get('children') or [], key))
    return labels


def image(element: Element, walker: Any) -> ElementSnapshot | None:
    # The source is left out: it can be a data URL, or a URL with credentials.
    props = _compat.props_of(element)
    return _snapshot(element, walker, 'image', label=str(props.get('alt') or nearby_label(element)), readable=False)


def unreadable(kind: str) -> Callable[[Element, Any], ElementSnapshot | None]:
    def extract(element: Element, walker: Any) -> ElementSnapshot | None:
        return _snapshot(element, walker, kind, label=nearby_label(element), readable=False)

    return extract


# Inputs: applied state, with sensitive values withheld (CAP-2, SEC-5).


def _is_sensitive_input(element: Element, label: str, walker: Any) -> bool:
    props = _compat.props_of(element)
    if props.get('type') == 'password':
        return True
    # A revealed password keeps its toggle icon in the append slot, though its type is now "text".
    if 'append' in element.slots:
        for child in element.slots['append'].children:
            if _compat.props_of(child).get('name') in ('visibility', 'visibility_off'):
                return True
    if str(props.get('autocomplete') or '').lower() in ('current-password', 'new-password', 'cc-number', 'cc-csc'):
        return True
    return field_is_excluded(label, walker.exclude_fields) or field_is_excluded(str(props.get('name') or ''),
                                                                                walker.exclude_fields)


def value_input(element: Element, walker: Any) -> ElementSnapshot | None:
    label = label_of(element) or str(getattr(element, 'text', '') or '').strip() or nearby_label(element)
    snapshot = _snapshot(element, walker, 'input', label=label, has_value=True)
    if _is_sensitive_input(element, label, walker):
        snapshot.value = WITHHELD_VALUE
        return snapshot
    snapshot.value = getattr(element, 'value', None)
    return snapshot


def choice_input(element: Element, walker: Any) -> ElementSnapshot | None:
    snapshot = value_input(element, walker)
    if snapshot is None or snapshot.value == WITHHELD_VALUE:
        return snapshot
    options = getattr(element, 'options', None)
    if isinstance(options, dict):
        value = snapshot.value
        snapshot.value = [options.get(item, item) for item in value] if isinstance(value, list) else options.get(value, value)
        snapshot.options = [str(option) for option in options.values()]
    elif isinstance(options, list):
        snapshot.options = [str(option) for option in options]
    return snapshot


def tabs(element: Element, walker: Any) -> ElementSnapshot | None:
    names = []
    for child in _compat.children_of(element):
        props = _compat.props_of(child)
        names.append(str(props.get('label') or props.get('name') or ''))
    value = getattr(element, 'value', None)
    current = _compat.props_of(value).get('name') if isinstance(value, Element) else value
    return _snapshot(element, walker, 'tabs', label='Tabs', has_value=True, value=current, options=names)


# Tables (CAP-2, CAP-3).


def _drop_fields(
    columns: list[str], labels: dict[str, str], exclude: Collection[Any], state: dict[str, Any],
) -> list[str]:
    kept = [c for c in columns if not (field_is_excluded(c, exclude) or field_is_excluded(labels.get(c, ''), exclude))]
    if len(kept) != len(columns):
        state['withheld_columns'] = len(columns) - len(kept)
    return kept


def table(element: Element, walker: Any) -> ElementSnapshot | None:
    props = _compat.props_of(element)
    visible = props.get('visible-columns')
    names: dict[str, str] = {}
    labels: dict[str, str] = {}
    columns: list[str] = []
    for column in element.columns:
        name = str(column.get('name') or column.get('field') or '')
        field = column.get('field')
        field = field if isinstance(field, str) else name
        if not name or (visible is not None and name not in visible):
            continue
        columns.append(field)
        names[name] = field
        labels[field] = str(column.get('label') or name)
    state: dict[str, Any] = {}
    columns = _drop_fields(columns, labels, walker.exclude_fields, state)
    data = TableData(columns=columns, labels=labels, rows=list(element.rows), source_rows=len(element.rows))

    # ui.table reports its filter and sort to the server, so no probe is needed.
    data.filter_text = str(getattr(element, 'filter', '') or '')
    if data.filter_text:
        state['filter'] = data.filter_text
    pagination = element.pagination or {}
    sort_by = pagination.get('sortBy')
    if sort_by:
        data.sort_by = names.get(sort_by, sort_by) if names.get(sort_by, sort_by) in columns else ''
        data.descending = bool(pagination.get('descending'))
        state['sorted_by'] = f'{labels.get(data.sort_by, sort_by)} {"descending" if data.descending else "ascending"}'
    if pagination.get('rowsPerPage'):
        state['page'] = pagination.get('page', 1)
        state['rows_per_page'] = pagination['rowsPerPage']
    selected = element.selected
    if selected:
        key = element.row_key
        state['selected'] = [row.get(key) for row in selected[:MAX_STATE_ITEMS]] if key in columns else len(selected)
    return _snapshot(element, walker, 'table', label=str(props.get('title') or nearby_label(element)),
                     table=data, state=state)


def _grid_columns(definitions: list[dict], parent: str = '') -> tuple[list[str], dict[str, str], list[str]]:
    columns: list[str] = []
    labels: dict[str, str] = {}
    computed: list[str] = []
    for definition in definitions:
        if 'children' in definition:
            sub_columns, sub_labels, sub_computed = _grid_columns(definition['children'], definition.get('headerName', ''))
            columns += sub_columns
            labels |= sub_labels
            computed += sub_computed
            continue
        field = definition.get('field') or definition.get('colId')
        header = definition.get('headerName') or field
        if not field:
            if header:
                computed.append(str(header))
            continue
        if definition.get('hide'):
            continue
        columns.append(field)
        labels[field] = f'{parent} {header}'.strip() if parent else str(header)
    return columns, labels, computed


def aggrid(element: Element, walker: Any) -> ElementSnapshot | None:
    options = element.options
    rows = options.get('rowData') or []
    definitions = options.get('columnDefs')
    if definitions:
        columns, labels, computed = _grid_columns(definitions)
    else:
        columns = list(rows[0]) if rows and isinstance(rows[0], dict) else []
        labels, computed = {}, []
    state: dict[str, Any] = {}
    columns = _drop_fields(columns, labels, walker.exclude_fields, state)
    if computed:
        state['computed_columns_not_readable'] = computed
    data = TableData(columns=columns, labels=labels, rows=list(rows), source_rows=len(rows),
                     dotted_fields=not options.get('suppressFieldDotNotation'))
    snapshot = _snapshot(element, walker, 'table', label=str(options.get('title') or nearby_label(element)),
                         table=data, state=state)
    walker.probe_grid(element, snapshot)
    return snapshot


# Charts (CAP-3).


def _first(value: Any) -> dict:
    if isinstance(value, list):
        return value[0] if value and isinstance(value[0], dict) else {}
    return value if isinstance(value, dict) else {}


def _plain(value: Any) -> Any:
    """Turn numpy arrays and Plotly's binary encoding into plain lists, with no numpy import."""
    if hasattr(value, 'tolist'):
        return value.tolist()
    if isinstance(value, dict) and 'bdata' in value:
        return _decode_bdata(value)
    if isinstance(value, tuple):
        return list(value)
    return value


_BDATA_FORMATS = {'f8': 'd', 'f4': 'f', 'i4': 'i', 'u4': 'I', 'i2': 'h', 'u2': 'H', 'i1': 'b', 'u1': 'B',
                  'int8': 'b', 'uint8': 'B', 'int16': 'h', 'uint16': 'H', 'int32': 'i', 'uint32': 'I',
                  'float32': 'f', 'float64': 'd'}


def _decode_bdata(value: dict) -> list[Any]:
    code = _BDATA_FORMATS.get(str(value.get('dtype')))
    if code is None:
        return []
    raw = base64.b64decode(value['bdata'])
    return list(struct.unpack(f'<{len(raw) // struct.calcsize(code)}{code}', raw))


def echart(element: Element, walker: Any) -> ElementSnapshot | None:
    options = element.options
    title = _first(options.get('title')).get('text') or nearby_label(element)
    x_axis, y_axis = _first(options.get('xAxis')), _first(options.get('yAxis'))
    horizontal = y_axis.get('type') == 'category' and x_axis.get('type') != 'category'
    category_axis = y_axis if horizontal else x_axis
    categories = category_axis.get('data')
    series_options = options.get('series')
    if isinstance(series_options, dict):
        series_options = [series_options]
    dataset = _first(options.get('dataset')).get('source')
    series = [_echart_series(item, index, categories, dataset, horizontal)
              for index, item in enumerate(series_options or []) if isinstance(item, dict)]
    legend = _first(options.get('legend')).get('selected')
    if isinstance(legend, dict):
        for item in series:
            if legend.get(item.name) is False:
                item.hidden = True
    state: dict[str, Any] = {}
    if x_axis.get('name'):
        state['x_axis'] = x_axis['name']
    if y_axis.get('name'):
        state['y_axis'] = y_axis['name']
    snapshot = _snapshot(element, walker, 'chart', label=str(title or ''), series=series, state=state)
    walker.probe_echart(element, snapshot, str(category_axis.get('type') or ('category' if categories else 'value')))
    return snapshot


def _echart_series(
    options: dict, index: int, categories: list | None, dataset: Any, horizontal: bool,
) -> Series:
    name = str(options.get('name') or f'Series {index + 1}')
    kind = str(options.get('type') or '')
    data = options.get('data')
    if data is None and dataset:
        return _echart_dataset_series(name, kind, options, index, dataset)
    data = _plain(data) or []
    x: list[Any] = []
    y: list[Any] = []
    has_own_x = False
    for position, point in enumerate(data):
        value = point.get('value') if isinstance(point, dict) else point
        if isinstance(point, dict) and point.get('name') is not None:
            x.append(point['name'])
            has_own_x = True
            y.append(value[-1] if isinstance(value, (list, tuple)) else value)
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            first, second = (value[1], value[0]) if horizontal else (value[0], value[1])
            x.append(first)
            has_own_x = True
            y.append(value[-1] if len(value) > 2 else second)
        else:
            x.append(categories[position] if categories and position < len(categories) else position)
            y.append(value)
    known_x = has_own_x or bool(categories)
    return Series(name=name, kind=kind, x=x if known_x else None, y=y)


def _echart_dataset_series(name: str, kind: str, options: dict, index: int, dataset: Any) -> Series:
    """Read a series from ECharts' dataset.source: rows of arrays with a header, or rows of objects."""
    encode = options.get('encode') or {}
    if isinstance(dataset, list) and dataset and isinstance(dataset[0], dict):
        keys = list(dataset[0])
        x_key = encode.get('x', keys[0])
        y_key = encode.get('y', keys[index + 1] if index + 1 < len(keys) else keys[-1])
        return Series(name=name if options.get('name') else str(y_key), kind=kind, x=[row.get(x_key) for row in dataset],
                      y=[row.get(y_key) for row in dataset])
    if isinstance(dataset, list) and dataset and isinstance(dataset[0], (list, tuple)):
        header, *rows = dataset
        x_index = encode.get('x', 0)
        y_index = encode.get('y', index + 1)
        x_index = header.index(x_index) if isinstance(x_index, str) and x_index in header else x_index
        y_index = header.index(y_index) if isinstance(y_index, str) and y_index in header else y_index
        if not isinstance(x_index, int) or not isinstance(y_index, int) or y_index >= len(header):
            return Series(name=name, kind=kind, y=[])
        return Series(name=name if options.get('name') else str(header[y_index]), kind=kind,
                      x=[row[x_index] for row in rows], y=[row[y_index] for row in rows])
    return Series(name=name, kind=kind, y=[])


def plotly(element: Element, walker: Any) -> ElementSnapshot | None:
    figure = element.figure
    figure = figure if isinstance(figure, dict) else figure.to_plotly_json()
    layout = figure.get('layout') or {}
    title = layout.get('title')
    title = title.get('text') if isinstance(title, dict) else title
    series = [_plotly_trace(trace, index) for index, trace in enumerate(figure.get('data') or [])]
    state: dict[str, Any] = {}
    for axis, name in (('xaxis', 'x_axis'), ('yaxis', 'y_axis')):
        axis_title = (layout.get(axis) or {}).get('title')
        axis_title = axis_title.get('text') if isinstance(axis_title, dict) else axis_title
        if axis_title:
            state[name] = axis_title
    snapshot = _snapshot(element, walker, 'chart', label=str(title or nearby_label(element)), series=series, state=state)
    walker.probe_plotly(element, snapshot)
    return snapshot


def _plotly_trace(trace: dict, index: int) -> Series:
    kind = str(trace.get('type') or 'scatter')
    if 'values' in trace:
        x, y = _plain(trace.get('labels')), _plain(trace.get('values'))
    elif 'z' in trace:
        x, y = None, _flatten(_plain(trace.get('z')))
    else:
        x, y = _plain(trace.get('x')), _plain(trace.get('y'))
        if y is None:
            x, y = None, x
    return Series(
        name=str(trace.get('name') or f'Trace {index + 1}'),
        kind=kind,
        x=list(x) if x is not None else None,
        y=list(y) if y is not None else [],
        hidden=trace.get('visible') in (False, 'legendonly'),
    )


def _flatten(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    flat: list[Any] = []
    for item in value:
        flat.extend(_flatten(item) if isinstance(item, list) else [item])
    return flat


def pyplot(element: Element, walker: Any) -> ElementSnapshot | None:
    """Optional support for ui.pyplot: reads line data and titles from the figure's axes."""
    figure = getattr(element, 'fig', None)
    series: list[Series] = []
    titles = []
    for axes in getattr(figure, 'axes', ()):
        if axes.get_title():
            titles.append(axes.get_title())
        for index, line in enumerate(axes.get_lines()):
            name = line.get_label()
            series.append(Series(name=name if not str(name).startswith('_') else f'Line {index + 1}', kind='line',
                                 x=list(map(_scalar, line.get_xdata())), y=list(map(_scalar, line.get_ydata()))))
    return _snapshot(element, walker, 'chart', label=', '.join(titles) or nearby_label(element), series=series,
                     readable=bool(series))


def _scalar(value: Any) -> Any:
    return value.item() if hasattr(value, 'item') else value


# Extractors keyed by class name, so that optional dependencies are never imported.
REGISTRY: dict[str, Extractor] = {
    'AgGrid': Extractor(aggrid),
    'Table': Extractor(table),
    'EChart': Extractor(echart),
    'Plotly': Extractor(plotly),
    'Pyplot': Extractor(pyplot),
    'Mermaid': Extractor(mermaid),
    'Tabs': Extractor(tabs),
    'ChoiceElement': Extractor(choice_input),
    # These inherit from TextElement ahead of ValueElement, but what matters is their state.
    'Checkbox': Extractor(value_input),
    'Switch': Extractor(value_input),
    'Chip': Extractor(text_element, descend=True),
    'ValueElement': Extractor(value_input),
    'Markdown': Extractor(markdown),
    'Html': Extractor(html_element),
    'Code': Extractor(code),
    'ChatMessage': Extractor(chat_message),
    'Tree': Extractor(tree),
    'Button': Extractor(button, descend=True),
    'Link': Extractor(link),
    'Image': Extractor(image),
    'InteractiveImage': Extractor(image),
    'Leaflet': Extractor(unreadable('map')),
    'Scene': Extractor(unreadable('3d scene')),
    'Video': Extractor(unreadable('video')),
    'Audio': Extractor(unreadable('audio')),
    'Highchart': Extractor(unreadable('chart')),
    'Altair': Extractor(unreadable('chart')),
    'AnyWidget': Extractor(unreadable('widget')),
    'Xterm': Extractor(unreadable('terminal')),
    'TextElement': Extractor(text_element, descend=True),
}

SKIPPED = frozenset({
    'Tooltip', 'Timer', 'Keyboard', 'Query', 'Colors', 'DarkMode', 'Fullscreen', 'Icon', 'Spinner', 'Space',
    'Separator', 'Skeleton', 'Notification', 'ContextMenu', 'Teleport', 'Avatar', 'SkipLink', 'PageScroller',
    'Joystick', 'Upload', 'LinearProgress', 'CircularProgress',
})


def register_extractor(element_class: type | str, function: Callable[[Element, Any], ElementSnapshot | None],
                       *, descend: bool = False) -> None:
    """Teach Glimpse to read a widget, for example a custom component of your own."""
    name = element_class if isinstance(element_class, str) else element_class.__name__
    REGISTRY[name] = Extractor(function, descend)
