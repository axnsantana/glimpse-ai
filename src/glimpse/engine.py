"""The engine contract: messages and a snapshot in, an async stream of events out (ENG-1).

Three shapes count as an engine:

- an object with respond(messages, page) returning an async iterator (the Engine protocol)
- an async generator function taking (messages, page) and yielding str or events (ENG-2)
- a plain function taking (messages, page) and returning str or an iterable of str

A plain function runs in a worker thread, so blocking code cannot freeze the app.

Cancelling a response closes the iterator, so an engine can use try/finally to clean up.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from .events import EngineEvent
from .page import PageContext


@dataclass(frozen=True)
class Message:
    role: Literal['user', 'assistant']
    content: str


class EngineError(Exception):
    """A failure with a message that is safe to show to the end user."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


@runtime_checkable
class Engine(Protocol):
    def respond(self, messages: list[Message], page: PageContext) -> AsyncIterator[EngineEvent | str]: ...


class FunctionEngine:
    """Wraps a function as an engine."""

    def __init__(self, function: Callable[..., Any]) -> None:
        self.function = function
        self.__name__ = getattr(function, '__name__', 'engine')

    async def respond(self, messages: list[Message], page: PageContext) -> AsyncIterator[EngineEvent | str]:
        function = self.function
        if inspect.isasyncgenfunction(function):
            stream = function(messages, page)
            try:
                async for item in stream:
                    yield item
            finally:
                await stream.aclose()
        elif inspect.iscoroutinefunction(function):
            result = await function(messages, page)
            async for item in _items(result):
                yield item
        else:
            result = await asyncio.to_thread(function, messages, page)
            async for item in _items(result):
                yield item


async def _items(result: Any) -> AsyncIterator[EngineEvent | str]:
    if hasattr(result, '__aiter__'):
        async for item in result:
            yield item
    elif isinstance(result, str) or not isinstance(result, Iterable):
        yield result
    else:
        iterator = iter(result)
        done = object()
        while (item := await asyncio.to_thread(next, iterator, done)) is not done:
            yield item


def as_engine(engine: Any) -> Engine:
    """Accept any supported engine shape."""
    if hasattr(engine, 'respond'):
        return engine
    if callable(engine):
        return FunctionEngine(engine)
    raise TypeError(f'{engine!r} is not an engine. Pass an object with respond(), or a function.')
