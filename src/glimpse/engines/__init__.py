"""Built-in engines, and the rule that picks one when the developer does not."""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

from ..engine import Engine, as_engine
from .adk import AdkEngine, is_adk_agent
from .council import CouncilEngine
from .direct import DEFAULT_ANTHROPIC_MODEL, DEFAULT_GEMINI_MODEL, DEFAULT_OPENAI_MODEL, DirectEngine
from .offline import OfflineEngine

__all__ = ['AdkEngine', 'CouncilEngine', 'DirectEngine', 'OfflineEngine', 'detect_model', 'resolve_engine']

log = logging.getLogger('glimpse')

ENGINE_NAMES = ('auto', 'direct', 'council', 'adk', 'offline')


def _enabled(variable: str) -> bool:
    return os.environ.get(variable, '').strip().lower() in ('1', 'true', 'yes')


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
    # GOOGLE_API_KEY is often set for other Google APIs, so only the Gemini-specific key counts here.
    if os.environ.get('GEMINI_API_KEY'):
        return f'gemini:{DEFAULT_GEMINI_MODEL}'
    # A Google Cloud project alone is common on developer machines, so Vertex AI also needs the
    # opt-in that the Google SDKs use themselves.
    if (_enabled('GOOGLE_GENAI_USE_VERTEXAI') or _enabled('GOOGLE_GENAI_USE_ENTERPRISE')) \
            and os.environ.get('GOOGLE_CLOUD_PROJECT'):
        return f'vertex:{DEFAULT_GEMINI_MODEL}'
    return None


def resolve_engine(
    engine: Any = 'auto',
    *,
    model: str | None = None,
    system_prompt: Any = None,
    project: str | None = None,
    location: str | None = None,
) -> Engine:
    """Turn the engine argument of attach() into an engine."""
    cloud = {'project': project, 'location': location}
    if engine == 'auto':
        chosen = model or detect_model()
        if chosen is None:
            log.warning('Glimpse found no model credentials, so it is running in offline demo mode. '
                        'Set ANTHROPIC_API_KEY or OPENAI_API_KEY, or pass model=.')
            return OfflineEngine()
        return DirectEngine(chosen, system_prompt=system_prompt, **cloud)
    if engine == 'direct':
        return DirectEngine(model or detect_model(), system_prompt=system_prompt, **cloud)
    if engine == 'council':
        return CouncilEngine(model or detect_model(), system_prompt=system_prompt, **cloud)
    if engine == 'adk':
        chosen = model or detect_model()
        if chosen is None:
            raise ValueError("engine='adk' needs a model, for example model='vertex:gemini-flash-latest', "
                             'or pass your ADK agent as engine=.')
        return AdkEngine(model=chosen, system_prompt=system_prompt, **cloud)
    if engine == 'offline':
        return OfflineEngine()
    if isinstance(engine, str):
        raise ValueError(f'Unknown engine {engine!r}. Use one of {", ".join(map(repr, ENGINE_NAMES))}, '
                         'or pass your own.')
    if is_adk_agent(engine):
        return AdkEngine(engine, **cloud)
    return as_engine(engine)
