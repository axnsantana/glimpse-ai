"""The NiceGUI adapter. This package and panel.js are the only code that depends on NiceGUI (NFR-6)."""

from .attach import attach
from .extractors import register_extractor
from .panel import GlimpsePanel

__all__ = ['GlimpsePanel', 'attach', 'register_extractor']
