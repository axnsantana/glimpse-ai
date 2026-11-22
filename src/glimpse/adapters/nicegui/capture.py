"""Build a PageContext from the live element tree of one client (CAP-1, CAP-2, CAP-7).

The walk starts from this client's layout and reads nothing else, which is what keeps one
user's page out of another user's snapshot (SEC-1). See docs/visibility-policy.md for what
counts as seen.
"""

from __future__ import annotations

import functools
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


RevealStep = tuple[int, Any]
"""An element ID, and the value that shows what is inside it: a tab, step or slide name, or True for an expansion."""


def get_meta(element: Element) -> dict[str, Any]:
    return getattr(element, META_ATTRIBUTE, {})


def _call_if_callable(value: Any) -> Any:
    return value() if callable(value) else value


class Walker:
    def __init__(self, exclude_fields: Collection[Any], visibility: str, read_inactive_sections: bool = True) -> None:
        self.exclude_fields = exclude_fields
        self.visibility = visibility
        self.read_inactive_sections = read_inactive_sections
        self.elements: list[ElementSnapshot] = []
        self.notes: list[str] = []
        self.withheld = 0
        self.grids: list[tuple[Element, ElementSnapshot]] = []
        self.echarts: list[tuple[Element, ElementSnapshot, str]] = []
        self.plotlies: list[tuple[Element, ElementSnapshot]] = []
        self.reveals: list[tuple[ElementSnapshot, tuple[RevealStep, ...]]] = []
        """Snapshots off screen, with the steps that bring each on screen, outermost first."""
        self._path: list[RevealStep | None] = []
        """The hidden containers around the current element. None is one a source cannot open, such as a dialog."""

    # Extractors register what needs a browser probe. Elements off screen are probed too: a tab the
    # user has opened, or a collapsed expansion, stays mounted in the page with its filters.
    def probe_grid(self, element: Element, snapshot: ElementSnapshot) -> None:
        self.grids.append((element, snapshot))

    def probe_echart(self, element: Element, snapshot: ElementSnapshot, axis_type: str) -> None:
        self.echarts.append((element, snapshot, axis_type))

    def probe_plotly(self, element: Element, snapshot: ElementSnapshot) -> None:
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

        # Tabs, slides and expansions usually fold one view to save room, so their content is part of the page.
        # A later step is often a stage the user has not reached, so steps are read only when "reachable".
        if 'TabPanels' in names:
            self._switching_children(element, section, 'TabPanel', 'Tab', 'inactive tab',
                                     read=self.read_inactive_sections)
        elif 'Stepper' in names:
            self._switching_children(element, section, 'Step', 'Step', 'inactive step')
        elif 'Carousel' in names:
            self._switching_children(element, section, 'CarouselSlide', 'Slide', 'inactive slide',
                                     read=self.read_inactive_sections)
        elif 'Expansion' in names:
            title = str(getattr(element, 'text', '') or '')
            if element.value:
                self._children(element, _join(section, f'Expansion: {title}'))
            else:
                self._hidden(element, section, f'Expansion: {title}', 'collapsed', stub=True,
                             read=self.read_inactive_sections, step=(element.id, True))
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

    def _switching_children(
        self, element: Element, section: str, child_class: str, label: str, reason: str, *, read: bool = False,
    ) -> None:
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
                self._hidden(child, section, title, reason, stub=True, read=read, step=(element.id, name))

    def _hidden(
        self, element: Element, section: str, title: str, reason: str, *, stub: bool, read: bool = False,
        step: RevealStep | None = None,
    ) -> None:
        """Content the user cannot see now. A stub says it exists, so that answers can point there."""
        self._path.append(step)
        if read or self.visibility == 'reachable':
            start = len(self.elements)
            self._children(element, _join(section, title))
            for snapshot in self.elements[start:]:
                # The innermost reason is the one that hides it. Its section names the containers around it.
                snapshot.hidden_reason = snapshot.hidden_reason or reason
        elif stub:
            contains = self._contains(element)
            self._add(ElementSnapshot(
                id=f'section-{element.id}', kind='section', label=title, hidden_reason=reason, section=section,
                description=f'Contains {contains}.' if contains else '', dom_id=element.html_id,
            ))
        self._path.pop()

    def _add(self, snapshot: ElementSnapshot) -> None:
        self.elements.append(snapshot)
        steps = tuple(step for step in self._path if step is not None)
        if self._path and len(steps) == len(self._path):
            self.reveals.append((snapshot, steps))

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
            self._add(snapshot)
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


def reveal(client: Client, steps: tuple[RevealStep, ...]) -> None:
    """Open the tabs and sections around an element, outermost first, as the user would by clicking them."""
    for element_id, value in steps:
        element = client.elements.get(element_id)
        if element is None:
            return
        element.value = value


async def capture_page(client: Client, config: GlimpseConfig) -> PageContext:
    """Read this client's page. Walks on the event loop, which is quick as data is only referenced."""
    walker = Walker(config.exclude_fields, config.visibility, config.read_inactive_sections)
    walker.walk(client.layout)
    for snapshot, steps in walker.reveals:
        snapshot.reveal = functools.partial(reveal, client, steps)
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
