"""The events an engine streams to the panel.

The vocabulary mirrors AG-UI, without depending on it. tests/test_events.py checks
the mapping onto ag-ui-protocol. Engines may also yield plain strings, which count
as text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class Usage:
    """Tokens used to answer one question. Cost needs pricing from the developer."""

    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ''
    cost: float | None = None
    estimated: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class RunStarted:
    type: ClassVar[str] = 'RUN_STARTED'
    run_id: str = ''


@dataclass(frozen=True)
class RunFinished:
    type: ClassVar[str] = 'RUN_FINISHED'
    run_id: str = ''


@dataclass(frozen=True)
class RunError:
    """A failure to show to the end user. Keep message free of internals."""

    type: ClassVar[str] = 'RUN_ERROR'
    message: str = ''
    code: str = ''


@dataclass(frozen=True)
class StepStarted:
    """Progress to show in the panel, for example 'Thinking'."""

    type: ClassVar[str] = 'STEP_STARTED'
    step_name: str = ''


@dataclass(frozen=True)
class StepFinished:
    type: ClassVar[str] = 'STEP_FINISHED'
    step_name: str = ''


@dataclass(frozen=True)
class TextMessageStart:
    type: ClassVar[str] = 'TEXT_MESSAGE_START'
    message_id: str = ''


@dataclass(frozen=True)
class TextMessageContent:
    type: ClassVar[str] = 'TEXT_MESSAGE_CONTENT'
    delta: str = ''
    message_id: str = ''


@dataclass(frozen=True)
class TextMessageEnd:
    type: ClassVar[str] = 'TEXT_MESSAGE_END'
    message_id: str = ''


@dataclass(frozen=True)
class ToolCallStart:
    type: ClassVar[str] = 'TOOL_CALL_START'
    tool_call_id: str = ''
    tool_call_name: str = ''


@dataclass(frozen=True)
class ToolCallArgs:
    type: ClassVar[str] = 'TOOL_CALL_ARGS'
    tool_call_id: str = ''
    delta: str = ''


@dataclass(frozen=True)
class ToolCallEnd:
    type: ClassVar[str] = 'TOOL_CALL_END'
    tool_call_id: str = ''


@dataclass(frozen=True)
class ToolCallResult:
    type: ClassVar[str] = 'TOOL_CALL_RESULT'
    tool_call_id: str = ''
    content: str = ''


@dataclass(frozen=True)
class Custom:
    type: ClassVar[str] = 'CUSTOM'
    name: str = ''
    value: Any = None


USAGE_EVENT = 'glimpse.usage'


def usage_event(usage: Usage) -> Custom:
    """Report token usage. Maps onto AG-UI's CUSTOM event."""
    return Custom(USAGE_EVENT, usage)


EngineEvent = (
    RunStarted | RunFinished | RunError | StepStarted | StepFinished | TextMessageStart | TextMessageContent
    | TextMessageEnd | ToolCallStart | ToolCallArgs | ToolCallEnd | ToolCallResult | Custom
)
