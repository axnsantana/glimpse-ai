"""The assistant panel. Its browser side lives in panel.js, inside a Shadow DOM (UI-3)."""

from __future__ import annotations

from typing import Any

from nicegui.client import Client
from nicegui.element import Element

from ...config import GlimpseConfig
from ...engine import Engine
from ...session import ChatSession, Turn
from .capture import capture_page


class GlimpsePanel(Element, component='panel.js'):
    def __init__(
        self,
        client: Client,
        engine: Engine,
        config: GlimpseConfig,
        *,
        title: str = 'Assistant',
        suggestions: list[str] | tuple[str, ...] = (),
        width: int = 400,
        push: bool = True,
        open: bool = False,
        inspector: bool | str = True,
    ) -> None:
        super().__init__()
        self.props['config'] = {
            'title': title,
            'suggestions': list(suggestions),
            'width': width,
            'push': push,
            'open': open,
            'inspector': bool(inspector),
            'banner': str(getattr(engine, 'banner', '') or ''),
        }
        self.inspector = inspector
        self.session = ChatSession(engine, config, lambda: capture_page(client, self.session.config), self._send_turn)
        self.on('glimpse_send', lambda event: self.ask(str(event.args.get('text', ''))))
        self.on('glimpse_cancel', lambda _: self.session.cancel())
        self.on('glimpse_clear', lambda _: self._clear())
        self.on('glimpse_inspect', lambda event: self._inspect(event.args.get('id')))
        self.on('glimpse_reveal', lambda event: self.reveal(event.args.get('turn'), event.args.get('id')))
        # The stream stops when the client is gone for good, not on a brief reconnect (NFR-2).
        client.on_delete(self.session.cancel)

    def ask(self, question: str) -> Any:
        """Ask a question, as if the user had typed it. Returns the task answering it."""
        return self.session.ask(question)

    def reveal(self, turn_id: Any, element_id: Any) -> None:
        """Bring a source the user clicked on screen, for example by opening its tab. The browser then scrolls to it."""
        turn = next((turn for turn in self.session.turns if turn.id == turn_id), None)
        element = turn.page.element(str(element_id)) if turn and turn.page else None
        if element is not None and element.reveal is not None:
            element.reveal()

    def _send_turn(self, turn: Turn) -> None:
        if not self.is_deleted:
            self.run_method('upsert', turn.view())

    def _clear(self) -> None:
        self.session.reset()
        self.run_method('clear')

    def _inspect(self, turn_id: Any) -> None:
        if not self.inspector:
            return
        turn = next((turn for turn in self.session.turns if turn.id == turn_id), None)
        if turn is None:
            return
        engine = self.session.engine
        full = self.inspector == 'full'
        system = getattr(engine, '_system', None)
        system_prompt = system(turn.page) if full and system and turn.page else ''
        self.run_method('showInspection', turn.inspection(full=full, system_prompt=system_prompt))
