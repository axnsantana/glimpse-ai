"""Glimpse adds an AI assistant that can see the page to your NiceGUI app, in one line.

    import glimpse

    @ui.page('/')
    def dashboard():
        ui.echart(...)
        glimpse.attach()
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .config import GlimpseConfig, Pricing
from .engine import Engine, EngineError, Message
from .engines import AdkEngine, CouncilEngine, DirectEngine, OfflineEngine
from .events import Usage
from .page import ElementSnapshot, PageContext, Series, TableData
from .prompt import DEFAULT_SYSTEM_PROMPT
from .serialize import Detail, json_serializer, text_serializer
from .session import ChatSession, Turn
from .tools import Tool

__version__ = '0.1.0'

__all__ = [
    'DEFAULT_SYSTEM_PROMPT',
    'AdkEngine',
    'ChatSession',
    'CouncilEngine',
    'Detail',
    'DirectEngine',
    'ElementSnapshot',
    'Engine',
    'EngineError',
    'GlimpseConfig',
    'Message',
    'OfflineEngine',
    'PageContext',
    'Pricing',
    'Series',
    'TableData',
    'Tool',
    'Turn',
    'Usage',
    'attach',
    'describe',
    'exclude',
    'json_serializer',
    'register_extractor',
    'text_serializer',
]


if TYPE_CHECKING:
    # Editors see the real signatures. At runtime NiceGUI loads on first use, so the core stays framework-neutral.
    from .adapters.nicegui import attach, register_extractor
else:

    def attach(**options: Any) -> Any:
        """Add the assistant to this page, or at module level to every page.

        See glimpse.adapters.nicegui.attach for all options.
        """
        from .adapters.nicegui import attach as nicegui_attach

        return nicegui_attach(**options)

    def register_extractor(element_class: Any, function: Callable[..., Any], *, descend: bool = False) -> None:
        """Teach Glimpse to read a widget it does not know."""
        from .adapters.nicegui import register_extractor as nicegui_register

        nicegui_register(element_class, function, descend=descend)


def describe(
    element: Any,
    *,
    id: str | None = None,
    label: str | None = None,
    description: str | Callable[[], str] | None = None,
    value: Any = None,
    available: bool | Callable[[], bool] = True,
) -> Any:
    """Add what the screen cannot show to one element. All of this is extractable by end users (SEC-6).

    :param id: a stable name for answers to cite
    :param label: overrides the name Glimpse found
    :param description: explains the element, as text or a function returning text
    :param value: extra data, or a function read at ask time
    :param available: False withholds the element. A function lets it come and go
    :return: the element
    """
    meta = dict(getattr(element, '_glimpse_meta', {}))
    meta.update({'id': id, 'label': label, 'description': description, 'value': value, 'available': available})
    element._glimpse_meta = meta
    return element


def exclude(element: Any) -> Any:
    """Withhold an element and everything inside it from the assistant (SEC-5)."""
    meta = dict(getattr(element, '_glimpse_meta', {}))
    meta['excluded'] = True
    element._glimpse_meta = meta
    return element
