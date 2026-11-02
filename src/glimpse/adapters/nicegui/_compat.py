"""Every use of NiceGUI internals lives in this file (NFR-7). See docs/nicegui-internals.md.

The tests run against the pinned minimum version and NiceGUI pre-releases, so a change
here shows up as a test failure, not as an assistant that silently sees less.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from nicegui.element import Element
from nicegui.slot import Slot


def has_slot_context() -> bool:
    """Whether this code runs while a page is being built. ui.context would create a client as a side effect."""
    return bool(Slot.get_stack())


def props_of(element: Element) -> dict[str, Any]:
    return element._props


def classes_of(element: Element) -> list[str]:
    return list(element._classes)


def styles_of(element: Element) -> dict[str, str]:
    return dict(element._style)


def children_of(element: Element) -> Iterator[Element]:
    for slot in element.slots.values():
        yield from slot.children


def previous_sibling(element: Element) -> Element | None:
    parent = element.parent_slot
    if parent is None:
        return None
    children = parent.children
    try:
        index = children.index(element)
    except ValueError:
        return None
    return children[index - 1] if index > 0 else None


def class_names(element: Element) -> list[str]:
    """Class names from most to least specific. Dispatching on names means no optional import is forced."""
    return [cls.__name__ for cls in type(element).__mro__]


def page_url(client: Any) -> str:
    """The path only. Query strings often hold tokens and identifiers."""
    router = getattr(client, 'sub_pages_router', None)
    base = client.page.path
    current = getattr(router, 'current_path', None)
    if current and base != current and '{' in base:
        return base.split('{')[0].rstrip('/') + current
    return current if current and base == '/' else base
