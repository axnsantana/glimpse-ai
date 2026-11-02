"""Build a PageContext from the live element tree of one client (CAP-1, CAP-2, CAP-7).

The walk starts from this client's layout and reads nothing else, which is what keeps one
user's page out of another user's snapshot (SEC-1). See docs/visibility-policy.md for what
counts as seen.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from types import MappingProxyType
from typing import Any

from nicegui.client import Client
from nicegui.element import Element

from ...config import GlimpseConfig
from ...page import ElementSnapshot, PageContext
from . import _compat, extractors, probe

log = logging.getLogger('glimpse')

META_ATTRIBUTE = '_glimpse_meta'
CONTAINER_CLASSES = frozenset({'Header', 'Footer', 'Splitter', 'ButtonDropdown', 'DropdownButton', 'Fab', 'Log'})
"""These subclass ValueElement, but their value is layout state, not user data."""
DATA_CLASSES = MappingProxyType({'AgGrid': 'table', 'Table': 'table', 'EChart': 'chart', 'Plotly': 'chart',
                                 'Pyplot': 'chart'})


def get_meta(element: Element) -> dict[str, Any]:
    return getattr(element, META_ATTRIBUTE, {})


def _call_if_callable(value: Any) -> Any:
    return value() if callable(value) else value


class Walker:
    def __init__(self, exclude_fields: Collection[Any], visibility: str) -> None:
        self.exclude_fields = exclude_fields
        self.visibility = visibility
        self.elements: list[ElementSnapshot] = []
        self.notes: list[str] = []
        self.withheld = 0
        self.grids: list[tuple[Element, ElementSnapshot]] = []
        self.echarts: list[tuple[Element, ElementSnapshot, str]] = []
        self.plotlies: list[tuple[Element, ElementSnapshot]] = []
        self._hidden_reason = ''

    # Extractors register what needs a browser probe. Only elements on screen are mounted.
    def probe_grid(self, element: Element, snapshot: ElementSnapshot) -> None:
        if not self._hidden_reason:
            self.grids.append((element, snapshot))

    def probe_echart(self, element: Element, snapshot: ElementSnapshot, axis_type: str) -> None:
        if not self._hidden_reason:
            self.echarts.append((element, snapshot, axis_type))

    def probe_plotly(self, element: Element, snapshot: ElementSnapshot) -> None:
        if not self._hidden_reason:
            self.plotlies.append((element, snapshot))

    def walk(self, element: Element, section: str = '') -> None:
        names = _compat.class_names(element)
        if 'GlimpsePanel' in names or names[0] in extractors.SKIPPED:
            return
        meta = get_meta(element)
        if meta.get('excluded') or not _call_if_callable(meta.get('available', True)):
            self.withheld += 1
            return
        if not element.visible or extractors.is_css_hidden(_compat.classes_of(element), _compat.styles_of(element)):
            return

        if 'TabPanels' in names:
            self._switching_children(element, section, 'TabPanel', 'Tab', 'inactive tab')
        elif 'Stepper' in names:
            self._switching_children(element, section, 'Step', 'Step', 'inactive step')
        elif 'Carousel' in names:
            self._switching_children(element, section, 'CarouselSlide', 'Slide', 'inactive slide')
        elif 'Expansion' in names:
            title = str(getattr(element, 'text', '') or '')
            if element.value:
                self._children(element, _join(section, f'Expansion: {title}'))
            else:
                self._hidden(element, section, f'Expansion: {title}', 'collapsed', stub=True)
        elif 'Dialog' in names or 'Menu' in names or 'Popup' in names:
            kind = next(name for name in names if name in ('Dialog', 'Menu', 'Popup'))
            if element.value:
                self._children(element, _join(section, kind))
            else:
                self._hidden(element, section, kind, 'closed', stub=False)
        elif CONTAINER_CLASSES.intersection(names):
            self._children(element, section)
        elif 'Drawer' in names:
            side = str(_compat.props_of(element).get('side') or '').capitalize()
            label = f'{side} drawer'.strip()
            # None means the browser decides by width, and that drawer shows on a desktop.
            if element.value is False:
                self._hidden(element, section, label, 'closed', stub=False)
            else:
                self._children(element, _join(section, label))
        else:
            self._content(element, names, section, meta)

    def _switching_children(self, element: Element, section: str, child_class: str, label: str, reason: str) -> None:
        value = element.value
        active = _compat.props_of(value).get('name') if isinstance(value, Element) else value
        for child in _compat.children_of(element):
            if child_class not in _compat.class_names(child):
                self.walk(child, section)
                continue
            name = _compat.props_of(child).get('name')
            title = f'{label}: {name}'
            if name == active:
                self._children(child, _join(section, title))
            else:
                self._hidden(child, section, title, reason, stub=True)

    def _hidden(self, element: Element, section: str, title: str, reason: str, *, stub: bool) -> None:
        """Content the user cannot see now. A stub says it exists, so that answers can point there."""
        if self.visibility == 'reachable':
            outer = self._hidden_reason
            self._hidden_reason = reason
            start = len(self.elements)
            self._children(element, _join(section, title))
            for snapshot in self.elements[start:]:
                snapshot.hidden_reason = reason
            self._hidden_reason = outer
        elif stub:
            contains = self._contains(element)
            self.elements.append(ElementSnapshot(
                id=f'section-{element.id}', kind='section', label=title, hidden_reason=reason, section=section,
                description=f'Contains {contains}.' if contains else '', dom_id=element.html_id,
            ))

    @staticmethod
    def _contains(element: Element) -> str:
        counts: dict[str, int] = {}
        for child in element.descendants():
            for name in _compat.class_names(child):
                if name in DATA_CLASSES:
                    counts[DATA_CLASSES[name]] = counts.get(DATA_CLASSES[name], 0) + 1
                    break
        return ', '.join(f'{count} {kind}{"s" if count > 1 else ""}' for kind, count in counts.items())

    def _children(self, element: Element, section: str) -> None:
        for child in _compat.children_of(element):
            self.walk(child, section)

    def _content(self, element: Element, names: list[str], section: str, meta: dict[str, Any]) -> None:
        extractor = next((extractors.REGISTRY[name] for name in names if name in extractors.REGISTRY), None)
        snapshot = extractor.function(element, self) if extractor else None
        if snapshot is None and meta:
            snapshot = ElementSnapshot(id=f'section-{element.id}', kind='section', dom_id=element.html_id)
        if snapshot is not None:
            snapshot.section = section
            self._apply_meta(snapshot, meta)
            self.elements.append(snapshot)
        if extractor is None or extractor.descend:
            self._children(element, section)

    def _apply_meta(self, snapshot: ElementSnapshot, meta: dict[str, Any]) -> None:
        if meta.get('id'):
            snapshot.id = str(meta['id'])
        if meta.get('label'):
            snapshot.label = str(meta['label'])
        if meta.get('description'):
            snapshot.description = str(_call_if_callable(meta['description']))
        if meta.get('value') is not None:
            snapshot.extra = _call_if_callable(meta['value'])


def _join(section: str, title: str) -> str:
    return f'{section} > {title}' if section else title


async def capture_page(client: Client, config: GlimpseConfig) -> PageContext:
    """Read this client's page. Walks on the event loop, which is quick as data is only referenced."""
    walker = Walker(config.exclude_fields, config.visibility)
    walker.walk(client.layout)
    page = PageContext(
        url=_compat.page_url(client),
        title=str(client.resolve_title() or ''),
        elements=walker.elements,
        notes=walker.notes,
        visibility=config.visibility,
        developer_context=str(_call_if_callable(config.context) or ''),
    )
    if walker.withheld:
        walker.notes.append(f'{walker.withheld} element(s) on this page are withheld from the assistant by the '
                            'developer. The user may see data you cannot.')
    if config.probe:
        await probe.apply_browser_state(client, walker, config)
    return page
