"""Settings for one attach() call."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any

from .events import Usage
from .serialize import Serializer, text_serializer
from .tokens import estimate_tokens

MIN_BUDGET = 1000
VISIBILITY_POLICIES = ('visible', 'reachable')


@dataclass(frozen=True)
class Pricing:
    """USD per million tokens. Supplied by the developer, because prices change."""

    input: float = 0.0
    output: float = 0.0

    def cost(self, usage: Usage) -> float:
        return (usage.input_tokens * self.input + usage.output_tokens * self.output) / 1_000_000


@dataclass(frozen=True)
class GlimpseConfig:
    context: str | Callable[[], str] = ''
    budget: int = 16000
    visibility: str = 'visible'
    exclude_fields: Collection[Any] = ()
    redact: Callable[[str], str] | None = None
    serializer: Serializer = text_serializer
    count_tokens: Callable[[str], int] = estimate_tokens
    on_usage: Callable[[Usage], Any] | None = None
    pricing: Pricing | None = None
    max_session_tokens: int | None = None
    max_session_cost: float | None = None
    allowed_link_hosts: Collection[str] = ()
    probe: bool = True
    probe_timeout: float = 1.0
    request_timeout: float = 300.0
    heartbeat: float = 5.0

    def __post_init__(self) -> None:
        if self.budget < MIN_BUDGET:
            raise ValueError(f'budget must be at least {MIN_BUDGET} tokens, got {self.budget}.')
        if self.visibility not in VISIBILITY_POLICIES:
            raise ValueError(f'visibility must be one of {VISIBILITY_POLICIES}, got {self.visibility!r}.')

