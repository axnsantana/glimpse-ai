"""Built-in engines, and the rule that picks one when the developer does not."""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

from ..engine import Engine, as_engine
from .direct import DEFAULT_ANTHROPIC_MODEL, DEFAULT_OPENAI_MODEL, DirectEngine
from .offline import OfflineEngine

__all__ = ['DirectEngine', 'OfflineEngine', 'detect_model', 'resolve_engine']

log = logging.getLogger('glimpse')


def detect_model() -> str | None:
    """Find a model from the environment, or None if no credentials are configured."""
    if model := os.environ.get('GLIMPSE_MODEL'):
        return model
    if os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('ANTHROPIC_AUTH_TOKEN'):
        return f'anthropic:{DEFAULT_ANTHROPIC_MODEL}'
    # An `ant auth login` profile also works with the SDK, with no environment variable set.
    profile = Path.home() / '.config' / 'anthropic'
    if profile.is_dir() and importlib.util.find_spec('anthropic') is not None:
        return f'anthropic:{DEFAULT_ANTHROPIC_MODEL}'
    if os.environ.get('OPENAI_API_KEY'):
        return f'openai:{DEFAULT_OPENAI_MODEL}'
    return None


def resolve_engine(engine: Any = 'auto', *, model: str | None = None, system_prompt: Any = None) -> Engine:
    """Turn the engine argument of attach() into an engine."""
    if engine == 'auto':
        chosen = model or detect_model()
        if chosen is None:
            log.warning('Glimpse found no model credentials, so it is running in offline demo mode. '
                        'Set ANTHROPIC_API_KEY or OPENAI_API_KEY, or pass model=.')
            return OfflineEngine()
        return DirectEngine(chosen, system_prompt=system_prompt)
    if engine == 'direct':
        return DirectEngine(model or detect_model(), system_prompt=system_prompt)
    if engine == 'offline':
        return OfflineEngine()
    if isinstance(engine, str):
        raise ValueError(f"Unknown engine {engine!r}. Use 'auto', 'direct', 'offline', or pass your own.")
    return as_engine(engine)
