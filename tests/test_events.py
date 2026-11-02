"""ENG-7: the internal event vocabulary maps onto AG-UI, with no runtime dependency on it."""

from __future__ import annotations

import pytest

ag_ui = pytest.importorskip('ag_ui.core')

from glimpse import events  # noqa: E402

THREAD = 'thread'
RUN = 'run'

MAPPING = [
    (events.RunStarted('r'), ag_ui.RunStartedEvent, lambda e: {'thread_id': THREAD, 'run_id': e.run_id or RUN}),
    (events.RunFinished('r'), ag_ui.RunFinishedEvent, lambda e: {'thread_id': THREAD, 'run_id': e.run_id or RUN}),
    (events.RunError('oops', 'code'), ag_ui.RunErrorEvent, lambda e: {'message': e.message, 'code': e.code}),
    (events.StepStarted('s'), ag_ui.StepStartedEvent, lambda e: {'step_name': e.step_name}),
    (events.StepFinished('s'), ag_ui.StepFinishedEvent, lambda e: {'step_name': e.step_name}),
    (events.TextMessageStart('m'), ag_ui.TextMessageStartEvent, lambda e: {'message_id': e.message_id}),
    (events.TextMessageContent('d', 'm'), ag_ui.TextMessageContentEvent,
     lambda e: {'message_id': e.message_id, 'delta': e.delta}),
    (events.TextMessageEnd('m'), ag_ui.TextMessageEndEvent, lambda e: {'message_id': e.message_id}),
    (events.ToolCallStart('t', 'n'), ag_ui.ToolCallStartEvent,
     lambda e: {'tool_call_id': e.tool_call_id, 'tool_call_name': e.tool_call_name}),
    (events.ToolCallArgs('t', 'd'), ag_ui.ToolCallArgsEvent, lambda e: {'tool_call_id': e.tool_call_id, 'delta': e.delta}),
    (events.ToolCallEnd('t'), ag_ui.ToolCallEndEvent, lambda e: {'tool_call_id': e.tool_call_id}),
    (events.ToolCallResult('t', 'c'), ag_ui.ToolCallResultEvent,
     lambda e: {'message_id': 'm', 'tool_call_id': e.tool_call_id, 'content': e.content}),
    (events.Custom('n', 1), ag_ui.CustomEvent, lambda e: {'name': e.name, 'value': e.value}),
]


@pytest.mark.parametrize('event, target, fields', MAPPING, ids=[type(item[0]).__name__ for item in MAPPING])
def test_event_maps_onto_ag_ui(event, target, fields):
    converted = target(**fields(event))
    assert converted.type.value == event.type


def test_mapping_covers_every_event():
    declared = {cls for cls in vars(events).values()
                if isinstance(cls, type) and hasattr(cls, 'type') and cls.__module__ == events.__name__}
    assert declared == {type(item[0]) for item in MAPPING}


def test_usage_travels_as_a_custom_event():
    usage = events.Usage(input_tokens=1, output_tokens=2)
    event = events.usage_event(usage)
    assert event.type == 'CUSTOM' and event.name == events.USAGE_EVENT and event.value.total_tokens == 3
