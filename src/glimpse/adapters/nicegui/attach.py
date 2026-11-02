"""attach(): one call that gives a page, or a whole app, its assistant (DEV-1, DEV-3)."""

from __future__ import annotations

import fnmatch
import logging
from collections.abc import Callable, Collection
from typing import Any

from nicegui import app, ui
from nicegui.client import Client

from ...builder import check_budget
from ...config import GlimpseConfig, Pricing
from ...engines import resolve_engine
from ...events import Usage
from ...page import PageContext
from ...serialize import Serializer, text_serializer
from ...tokens import estimate_tokens
from . import _compat
from .panel import GlimpsePanel

log = logging.getLogger('glimpse')


def attach(
    *,
    engine: Any = 'auto',
    model: str | None = None,
    context: str | Callable[[], str] = '',
    system_prompt: Any = None,
    budget: int = 16000,
    visibility: str = 'visible',
    exclude_fields: Collection[Any] = (),
    redact: Callable[[str], str] | None = None,
    serializer: Serializer = text_serializer,
    count_tokens: Callable[[str], int] = estimate_tokens,
    on_usage: Callable[[Usage], Any] | None = None,
    pricing: Pricing | dict[str, float] | None = None,
    max_session_tokens: int | None = None,
    max_session_cost: float | None = None,
    allowed_link_hosts: Collection[str] = (),
    probe: bool = True,
    probe_timeout: float = 1.0,
    request_timeout: float = 300.0,
    title: str = 'Assistant',
    suggestions: Collection[str] = (),
    width: int = 400,
    push: bool = True,
    open: bool = False,
    inspector: bool | str = True,
    skip_paths: Collection[str] = (),
) -> GlimpsePanel | None:
    """Add the assistant panel to this page, or to every page.

    Inside a page function it applies to that page. At module level it applies to every
    page of the app. All arguments are optional, and all data stays on the server unless
    the chosen engine sends it to its model.

    :param engine: "auto" (a model if credentials are found, otherwise the offline demo), "direct", "offline",
        an object with respond(messages, page), or a function (messages, page) yielding text
    :param model: "provider:model", for example "anthropic:claude-opus-5-5", "openai:gpt-5" or "ollama:llama3.2"
    :param context: extra facts for the assistant, or a function returning them. End users can extract this text
    :param system_prompt: replaces the built-in system prompt exactly (a string, or a function of the page)
    :param budget: the most tokens one request may use, estimated unless count_tokens is exact
    :param visibility: "visible" reads what is on screen. "reachable" also reads inactive tabs and collapsed sections
    :param exclude_fields: column or input names to withhold, as strings or compiled regular expressions
    :param redact: runs on every string before it can leave the process
    :param serializer: turns a snapshot into model input
    :param count_tokens: a token counter to use instead of the built-in estimate
    :param on_usage: called with a Usage after each answer
    :param pricing: USD per million tokens, {"input": ..., "output": ...}, to compute cost
    :param max_session_tokens: stop answering once a session has used this many tokens
    :param max_session_cost: stop answering once a session has cost this much, which needs pricing
    :param allowed_link_hosts: hosts that may appear as clickable links in answers
    :param probe: read browser-only state such as grid filters and chart zoom
    :param probe_timeout: seconds to wait for the browser
    :param request_timeout: seconds of silence before an answer is given up on
    :param title: panel title
    :param suggestions: starter questions for an empty conversation
    :param width: panel width in pixels
    :param push: make room for the panel instead of covering the page
    :param open: start with the panel open
    :param inspector: show "What the assistant saw". "full" also shows the system prompt and developer context
    :param skip_paths: glob patterns of pages to leave out when attached at module level
    :return: the panel, or None when attached at module level
    """
    if isinstance(pricing, dict):
        pricing = Pricing(**pricing)
    config = GlimpseConfig(
        context=context, budget=budget, visibility=visibility, exclude_fields=tuple(exclude_fields), redact=redact,
        serializer=serializer, count_tokens=count_tokens, on_usage=on_usage, pricing=pricing,
        max_session_tokens=max_session_tokens, max_session_cost=max_session_cost,
        allowed_link_hosts=tuple(allowed_link_hosts), probe=probe, probe_timeout=probe_timeout,
        request_timeout=request_timeout,
    )
    resolved = resolve_engine(engine, model=model, system_prompt=system_prompt)
    overhead = getattr(resolved, 'overhead_text', None)
    if overhead is not None:
        check_budget(budget, overhead(PageContext()), count_tokens)
    options = {'title': title, 'suggestions': tuple(suggestions), 'width': width, 'push': push, 'open': open,
               'inspector': inspector}

    def add_panel(client: Client) -> GlimpsePanel:
        with client.layout:
            return GlimpsePanel(client, resolved, config, **options)

    if _compat.has_slot_context():
        client = ui.context.client
        _remove_existing(client)
        return add_panel(client)

    def on_connect(client: Client) -> None:
        if any(fnmatch.fnmatch(client.page.path, pattern) for pattern in skip_paths):
            return
        # This also runs on a reconnect, and a page may already have called attach() itself.
        if any(isinstance(element, GlimpsePanel) for element in client.elements.values()):
            return
        add_panel(client)

    app.on_connect(on_connect)
    return None


def _remove_existing(client: Client) -> None:
    for element in list(client.elements.values()):
        if isinstance(element, GlimpsePanel):
            element.delete()
