"""Shared test helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from nicegui import ElementFilter
from nicegui.testing import User

from glimpse import Message, PageContext
from glimpse.adapters.nicegui.panel import GlimpsePanel
from glimpse.session import Turn

ROOT = Path(__file__).parent.parent
EXAMPLES = ROOT / 'examples'


class RecordingEngine:
    """Remembers what it received, and answers with a fixed text."""

    def __init__(self, answer: str = 'Recorded.') -> None:
        self.answer = answer
        self.calls: list[tuple[list[Message], PageContext]] = []

    async def respond(self, messages: list[Message], page: PageContext) -> AsyncIterator[str]:
        self.calls.append((messages, page))
        yield self.answer

    @property
    def last_page(self) -> PageContext:
        return self.calls[-1][1]

    @property
    def last_messages(self) -> list[Message]:
        return self.calls[-1][0]


def panel_of(user: User) -> GlimpsePanel:
    """The panel on the page this user has open."""
    with user:
        panels = list(ElementFilter(kind=GlimpsePanel))
    assert len(panels) == 1, f'expected one panel, found {len(panels)}'
    return panels[0]


async def ask(panel: GlimpsePanel, question: str, timeout: float = 30) -> Turn:
    """Ask as the user would, and wait for the whole answer."""
    task = panel.ask(question)
    assert task is not None
    await asyncio.wait_for(task, timeout)
    # Let NiceGUI's outbox send the last update. On Python below 3.12, asyncio.wait_for can swallow a
    # cancel that lands in the same tick as its event, which delays NiceGUI's shutdown by two seconds.
    await asyncio.sleep(0.01)
    return panel.session.turns[-1]


def element_by_label(page: PageContext, label: str):
    for element in page.elements:
        if element.label == label:
            return element
    raise AssertionError(f'no element labelled {label!r} in {[e.label for e in page.elements]}')
