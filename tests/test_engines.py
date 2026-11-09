"""ENG-1, ENG-2, UI-5, UI-7, DEV-4, DEV-5: the engine contract and what the session does around it."""

from __future__ import annotations

import asyncio
import json

import pytest
from nicegui import ui
from nicegui.testing import User

import glimpse
from glimpse import ChatSession, DirectEngine, EngineError, GlimpseConfig, Message, OfflineEngine, PageContext
from glimpse.engine import as_engine
from glimpse.engines import detect_model, resolve_engine
from glimpse.engines.direct import RoundResult, ToolCall, parse_model
from glimpse.events import RunError, StepStarted, TextMessageContent, ToolCallStart, Usage, usage_event

from .helpers import RecordingEngine, panel_of


async def _until(condition) -> None:
    async def poll() -> None:
        while not condition():  # noqa: ASYNC110
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), 5)


def session_with(engine, page: PageContext | None = None, **config) -> ChatSession:
    async def capture() -> PageContext:
        return page or PageContext(title='T')

    return ChatSession(as_engine(engine), GlimpseConfig(**config), capture, lambda turn: None)


async def run(session: ChatSession, question: str = 'Q'):
    task = session.ask(question)
    if task is not None:
        await asyncio.wait_for(task, 10)
    return session.turns[-1]


async def test_async_generator_of_str():
    async def engine(messages, page):
        yield 'Hello '
        yield 'world'

    turn = await run(session_with(engine))
    assert turn.status == 'done' and turn.text == 'Hello world'


async def test_coroutine_and_plain_functions_also_count_as_engines():
    async def coroutine(messages, page):
        return 'from a coroutine'

    def plain(messages, page):
        return 'from a function'

    def generator(messages, page):
        yield 'from '
        yield 'a generator'

    assert (await run(session_with(coroutine))).text == 'from a coroutine'
    assert (await run(session_with(plain))).text == 'from a function'
    assert (await run(session_with(generator))).text == 'from a generator'


async def test_blocking_engine_does_not_freeze_the_event_loop():
    import threading
    import time

    loop_thread = threading.current_thread()
    seen = {}

    def blocking(messages, page):
        seen['thread'] = threading.current_thread()
        time.sleep(0.3)
        return 'done'

    session = session_with(blocking)
    task = session.ask('Q')
    ticks = 0
    while not task.done():
        await asyncio.sleep(0.02)
        ticks += 1
    assert seen['thread'] is not loop_thread
    assert ticks >= 5, 'the loop kept running while the engine blocked'


async def test_engines_can_mix_events_and_text():
    class Engine:
        async def respond(self, messages, page):
            yield StepStarted('Working')
            yield 'one '
            yield TextMessageContent('two')
            yield usage_event(Usage(input_tokens=10, output_tokens=2, model='m'))

    turn = await run(session_with(Engine()))
    assert turn.text == 'one two'
    assert turn.usage.total_tokens == 12 and not turn.usage.estimated


def test_not_an_engine():
    with pytest.raises(TypeError):
        as_engine(42)
    with pytest.raises(ValueError, match='Unknown engine'):
        resolve_engine('committee')


async def test_cancel_closes_the_engine_and_keeps_the_partial_answer():
    closed = asyncio.Event()

    async def engine(messages, page):
        try:
            yield 'partial '
            await asyncio.sleep(60)
            yield 'never'
        finally:
            closed.set()

    session = session_with(engine)
    task = session.ask('Q')
    await _until(lambda: session.turns[0].text)
    session.cancel()
    await asyncio.wait_for(task, 5)
    turn = session.turns[0]
    assert closed.is_set()
    assert turn.status == 'stopped' and turn.text == 'partial ' and 'Stopped.' in turn.notices
    assert session.history[-1].content.endswith('[stopped by the user]')


async def test_a_second_question_waits_for_the_first():
    gate = asyncio.Event()

    async def engine(messages, page):
        await gate.wait()
        yield 'ok'

    session = session_with(engine)
    first = session.ask('one')
    assert session.ask('two') is None
    assert len(session.turns) == 1
    gate.set()
    await first
    assert session.ask('   ') is None


async def test_errors_never_show_internals_to_the_end_user(caplog):
    async def engine(messages, page):
        raise RuntimeError('db password is hunter2')
        yield ''

    turn = await run(session_with(engine))
    assert turn.status == 'error' and 'hunter2' not in turn.error and 'server log' in turn.error
    assert 'hunter2' in caplog.text
    caplog.clear()


async def test_engine_error_message_reaches_the_user():
    async def engine(messages, page):
        raise EngineError('Fix your key')
        yield ''

    assert (await run(session_with(engine))).error == 'Fix your key'

    async def reports(messages, page):
        yield RunError('Provider is down')

    assert (await run(session_with(reports))).error == 'Provider is down'


async def test_failed_turns_do_not_pollute_history():
    async def engine(messages, page):
        raise EngineError('no')
        yield ''

    session = session_with(engine)
    await run(session)
    assert session.history == []


async def test_history_is_sent_on_the_next_question():
    engine = RecordingEngine('First answer')
    session = session_with(engine)
    await run(session, 'First question')
    await run(session, 'Second question')
    assert [message.content for message in engine.last_messages] == ['First question', 'First answer', 'Second question']


async def test_timeout_gives_up_with_a_message():
    async def engine(messages, page):
        await asyncio.sleep(60)
        yield 'late'

    session = session_with(engine, request_timeout=0.05, heartbeat=0.01)
    turn = await run(session)
    assert turn.status == 'error' and 'too long' in turn.error


async def test_progress_heartbeat_during_silence():
    updates = []

    async def engine(messages, page):
        await asyncio.sleep(0.1)
        yield 'ok'

    async def capture():
        return PageContext()

    session = ChatSession(as_engine(engine), GlimpseConfig(heartbeat=0.02), capture,
                          lambda turn: updates.append(turn.progress))
    await asyncio.wait_for(session.ask('Q'), 5)
    assert any(update.startswith('Still working') for update in updates)
    assert updates[0] == 'Reading the page' and 'Thinking' in updates


async def test_usage_hook_cost_and_session_limits():
    seen = []

    class Engine:
        async def respond(self, messages, page):
            yield 'x'
            yield usage_event(Usage(input_tokens=1_000_000, output_tokens=1_000_000, model='m'))

    session = session_with(Engine(), on_usage=seen.append, pricing=glimpse.Pricing(input=2, output=10),
                           max_session_cost=11)
    turn = await run(session)
    assert seen[0].cost == 12 and turn.usage.cost == 12
    assert session.total_cost == 12
    assert session.ask('again') is None
    assert 'spending limit' in session.turns[-1].error

    tokens = session_with(RecordingEngine('answer ' * 100), max_session_tokens=1)
    await run(tokens)
    await run(tokens)
    assert 'usage limit' in tokens.turns[-1].error
    assert tokens.turns[0].usage.estimated, 'with no report from the engine, usage is estimated and says so'


async def test_a_broken_usage_hook_does_not_break_the_answer(caplog):
    def hook(usage):
        raise ValueError('boom')

    turn = await run(session_with(RecordingEngine(), on_usage=hook))
    assert turn.status == 'done'
    caplog.clear()


# Sources and honesty.


async def test_sources_come_from_citations_and_tool_use():
    page = PageContext(elements=[glimpse.ElementSnapshot(id='chart-1', kind='chart', label='Sales', dom_id='c1')])

    async def engine(messages, page):
        yield 'Up [ref:chart-1], and [ref:made-up].'

    turn = await run(session_with(engine, page))
    assert turn.sources() == [{'id': 'chart-1', 'label': 'Sales', 'kind': 'chart', 'dom': 'c1'}]
    assert 'made-up' not in json.dumps(turn.blocks)


async def test_a_text_source_is_named_by_its_content():
    page = PageContext(elements=[glimpse.ElementSnapshot(id='a', kind='text', text='Revenue: 112,830 k EUR'),
                                 glimpse.ElementSnapshot(id='b', kind='text', text='x' * 100)])

    async def engine(messages, page):
        yield 'See [ref:a] and [ref:b].'

    labels = [source['label'] for source in (await run(session_with(engine, page))).sources()]
    assert labels[0] == 'Revenue: 112,830 k EUR' and labels[1].endswith('…') and len(labels[1]) <= 32


async def test_inspector_shows_exactly_what_was_sent_and_hides_context_by_default():
    page = PageContext(title='T', developer_context='internal note',
                       elements=[glimpse.ElementSnapshot(id='a', kind='text', text='Visible text')])
    turn = await run(session_with(RecordingEngine(), page))
    data = turn.inspection()
    assert 'Visible text' in data['page'] and data['tokens'] == turn.page.report.used
    assert 'developer_context' not in data
    assert turn.inspection(full=True, system_prompt='SP')['developer_context'] == 'internal note'


# The offline engine answers only from the snapshot.


def offline_page() -> PageContext:
    return PageContext(title='Sales', elements=[
        glimpse.ElementSnapshot(id='chart-1', kind='chart', label='Revenue',
                                series=[glimpse.Series(name='Revenue', x=['Jan', 'Feb'], y=[5, 9]),
                                        glimpse.Series(name='Cost', x=['Jan', 'Feb'], y=[100, 1], hidden=True)]),
        glimpse.ElementSnapshot(id='input-1', kind='input', label='Region', has_value=True, value='EMEA'),
    ])


@pytest.mark.parametrize('question, expected', [
    ('What is the highest revenue?', '9'),
    ('What is the lowest revenue?', '5'),
    ('What is the total revenue?', '14'),
    ('What is the trend of revenue?', 'rising'),
    ('What are the current filters?', 'EMEA'),
    ('What is on this page?', 'Revenue'),
    ('What is the price of tea in Lisbon?', 'not on this page'),
])
async def test_offline_engine(question, expected):
    turn = await run(session_with(OfflineEngine(delay=0), offline_page()), question)
    assert expected in turn.text


async def test_offline_engine_ignores_series_the_user_hid():
    turn = await run(session_with(OfflineEngine(delay=0), offline_page()), 'What is the highest value?')
    assert '100' not in turn.text


# Choosing a model.


def test_model_strings():
    assert parse_model('anthropic:claude-opus-5-5') == ('anthropic', 'claude-opus-5-5')
    assert parse_model('ollama:llama3.2:8b') == ('ollama', 'llama3.2:8b')
    assert parse_model('claude-sonnet-5-5') == ('anthropic', 'claude-sonnet-5-5')
    assert parse_model('gpt-5') == ('openai', 'gpt-5')
    assert parse_model('vendor/model:free') == ('openai', 'vendor/model:free')
    assert parse_model('vertex:claude-opus-5-5') == ('vertex', 'claude-opus-5-5')
    assert parse_model('vertex:gemini-flash-latest') == ('vertex', 'gemini-flash-latest')
    assert parse_model('gemini:gemini-flash-latest') == ('gemini', 'gemini-flash-latest')
    assert parse_model('gemini-flash-latest') == ('gemini', 'gemini-flash-latest')


def test_google_cloud_settings_come_from_arguments_then_the_environment(monkeypatch):
    from glimpse.engines.direct import google_cloud

    with pytest.raises(EngineError, match='GOOGLE_CLOUD_PROJECT'):
        google_cloud()
    assert (google_cloud('p').project, google_cloud('p').location) == ('p', 'global')
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'env-project')
    monkeypatch.setenv('CLOUD_ML_REGION', 'us-east5')
    assert (google_cloud().project, google_cloud().location) == ('env-project', 'us-east5')
    monkeypatch.setenv('GOOGLE_CLOUD_LOCATION', 'europe-west4')
    assert google_cloud().location == 'europe-west4', 'the Google variable wins over the Anthropic one'
    assert (google_cloud('arg', 'us-central1').project, google_cloud('arg', 'us-central1').location) == \
        ('arg', 'us-central1')


def test_auto_engine_detection(monkeypatch):
    assert detect_model() is None
    assert isinstance(resolve_engine('auto'), OfflineEngine)
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    assert detect_model() == 'openai:gpt-5'
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'k')
    assert detect_model() == 'anthropic:claude-opus-5-5'
    assert isinstance(resolve_engine('auto'), DirectEngine)
    monkeypatch.setenv('GLIMPSE_MODEL', 'ollama:x')
    assert detect_model() == 'ollama:x'
    assert resolve_engine('auto', model='gpt-5').model == 'gpt-5'


def test_google_detection_needs_a_clear_signal(monkeypatch):
    monkeypatch.setenv('GOOGLE_API_KEY', 'k')
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'p')
    assert detect_model() is None, 'a key or project set for other Google APIs must not send pages to Gemini'
    monkeypatch.setenv('GOOGLE_GENAI_USE_VERTEXAI', 'true')
    assert detect_model() == 'vertex:gemini-flash-latest'
    monkeypatch.setenv('GEMINI_API_KEY', 'k')
    assert detect_model() == 'gemini:gemini-flash-latest'
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'k')
    assert detect_model() == 'anthropic:claude-opus-5-5', 'the default provider does not change'


def test_attach_options_reach_the_direct_engine():
    engine = resolve_engine('auto', model='vertex:claude-opus-5-5', project='p', location='us-east5')
    assert isinstance(engine, DirectEngine) and (engine.project, engine.location) == ('p', 'us-east5')


async def test_direct_engine_without_a_model_says_what_to_do():
    turn = await run(session_with(DirectEngine()))
    assert 'ANTHROPIC_API_KEY' in turn.error


# The direct engine's loop, with a scripted provider.


class ScriptedConversation:
    def __init__(self, rounds, record):
        self.rounds = list(rounds)
        self.record = record

    async def next_round(self, *, use_tools):
        self.record['use_tools'].append(use_tools)
        for item in self.rounds.pop(0):
            yield item

    def add_tool_results(self, results):
        self.record['results'].append(results)


class ScriptedProvider:
    def __init__(self, *rounds):
        self.rounds = rounds
        self.record = {'use_tools': [], 'results': []}

    def conversation(self, system, messages, tools):
        self.record.update(system=system, messages=messages, tools=tools)
        return ScriptedConversation(self.rounds, self.record)


def table_page() -> PageContext:
    return PageContext(elements=[glimpse.ElementSnapshot(
        id='table-1', kind='table', label='Orders',
        table=glimpse.TableData(columns=['id', 'amount'], rows=[{'id': i, 'amount': i * 10} for i in range(500)]),
    )])


async def test_tool_loop_feeds_results_back_and_records_provenance():
    provider = ScriptedProvider(
        [RoundResult(tool_calls=[ToolCall('t1', 'aggregate_rows', {'element_id': 'table-1', 'column': 'amount',
                                                                    'operation': 'sum'})],
                     input_tokens=100, output_tokens=5)],
        [TextMessageContent('The total is 1247500 [ref:table-1].'), RoundResult(input_tokens=120, output_tokens=9)],
    )
    turn = await run(session_with(DirectEngine('m', provider=provider), table_page()))
    assert turn.text.startswith('The total')
    assert turn.usage.input_tokens == 220 and turn.usage.output_tokens == 14
    call_id, content, is_error = provider.record['results'][0][0]
    assert call_id == 't1' and not is_error
    assert '1247500' in content and content.startswith('<tool_result>')
    assert turn.tool_calls[0]['name'] == 'aggregate_rows'
    assert [source['id'] for source in turn.sources()] == ['table-1']
    # The page is in the last message and the system prompt holds no page data (SEC-4).
    assert '<page_state>' in provider.record['messages'][-1].content
    assert '<page_state>\n' not in provider.record['system']


@pytest.mark.parametrize('arguments, expected', [
    (None, 'INVALID_JSON'),
    ({'element_id': 'nope'}, 'not on this page'),
    ({}, 'Missing required'),
    ({'element_id': 'table-1', 'limit': 'many'}, 'must be of type integer'),
    ({'element_id': 'table-1', 'bogus': 1}, 'Unknown argument'),
])
async def test_bad_tool_input_goes_back_to_the_model_as_an_error(arguments, expected):
    provider = ScriptedProvider(
        [RoundResult(tool_calls=[ToolCall('t1', 'get_rows', arguments, 'raw')])],
        [TextMessageContent('Sorry.'), RoundResult()],
    )
    turn = await run(session_with(DirectEngine('m', provider=provider), table_page()))
    _, content, is_error = provider.record['results'][0][0]
    assert is_error and expected in content
    assert turn.status == 'done'


async def test_tool_loop_stops_at_the_round_limit_and_final_round_has_no_tools():
    call = ToolCall('t', 'get_rows', {'element_id': 'table-1'})
    provider = ScriptedProvider(
        [RoundResult(tool_calls=[call])], [RoundResult(tool_calls=[call])], [TextMessageContent('End'), RoundResult()],
    )
    await run(session_with(DirectEngine('m', provider=provider, max_tool_rounds=2), table_page()))
    assert provider.record['use_tools'] == [True, True, False]


async def test_tool_results_cannot_blow_the_budget():
    provider = ScriptedProvider(
        *[[RoundResult(tool_calls=[ToolCall(f't{i}', 'get_rows', {'element_id': 'table-1', 'limit': 200})])]
          for i in range(4)],
        [TextMessageContent('End'), RoundResult()],
    )
    turn = await run(session_with(DirectEngine('m', provider=provider), table_page(), budget=6000))
    assert turn.status == 'done', turn.error
    from glimpse.tokens import estimate_tokens

    results = [result for round_results in provider.record['results'] for result in round_results]
    assert results, 'the test only means something if tools ran'
    tool_tokens = sum(estimate_tokens(result[1]) for result in results)
    # The fences add a few tokens per result.
    assert turn.page.report.used + tool_tokens <= 6000 + 20 * len(results)
    assert provider.record['use_tools'][-1] is False, 'tools switch off once the budget is spent'


async def test_a_model_that_ignores_tool_choice_cannot_keep_the_loop_going():
    call = ToolCall('t', 'get_rows', {'element_id': 'table-1'})
    provider = ScriptedProvider([RoundResult(tool_calls=[call])], [TextMessageContent('Text'), RoundResult(tool_calls=[call])])
    turn = await run(session_with(DirectEngine('m', provider=provider, max_tool_rounds=1), table_page()))
    assert turn.status == 'done' and turn.text == 'Text'
    assert len(provider.record['results']) == 1


async def test_a_budget_too_small_for_the_direct_engine_fails_at_attach(user: User):
    @ui.page('/')
    def page():
        with pytest.raises(ValueError, match='budget=1500 is too small'):
            glimpse.attach(model='openai:gpt-5', budget=1500)
        glimpse.attach(engine=RecordingEngine(), budget=1000)

    await user.open('/')
    assert panel_of(user).session.config.budget == 1000


async def test_tool_events_show_progress():
    updates = []

    async def capture():
        return table_page()

    provider = ScriptedProvider(
        [RoundResult(tool_calls=[ToolCall('t', 'get_rows', {'element_id': 'table-1'})])],
        [TextMessageContent('Done'), RoundResult()],
    )
    session = ChatSession(DirectEngine('m', provider=provider), GlimpseConfig(), capture,
                          lambda turn: updates.append(turn.progress))
    await asyncio.wait_for(session.ask('Q'), 5)
    assert any('get_rows' in update for update in updates)
    assert ToolCallStart.type == 'TOOL_CALL_START'


async def test_engine_notices_reach_the_user():
    provider = ScriptedProvider([TextMessageContent('Partial'), RoundResult(notice='This answer was cut off.')])
    turn = await run(session_with(DirectEngine('m', provider=provider)))
    assert 'This answer was cut off.' in turn.notices


async def test_exact_system_prompt_override():
    provider = ScriptedProvider([RoundResult()])
    await run(session_with(DirectEngine('m', provider=provider, system_prompt='Exactly this.')))
    assert provider.record['system'] == 'Exactly this.'

    provider = ScriptedProvider([RoundResult()])
    await run(session_with(DirectEngine('m', provider=provider, system_prompt=lambda page: f'For {page.title}')))
    assert provider.record['system'] == 'For T'


async def test_attach_passes_model_and_prompt_to_the_direct_engine(user: User):
    @ui.page('/')
    def page():
        glimpse.attach(model='anthropic:claude-sonnet-5-5', system_prompt='Be brief.')

    await user.open('/')
    engine = panel_of(user).session.engine
    assert isinstance(engine, DirectEngine)
    assert engine.model == 'anthropic:claude-sonnet-5-5' and engine.system_prompt == 'Be brief.'


async def test_attach_returns_the_panel_and_replaces_an_earlier_one(user: User):
    panels = []

    @ui.page('/')
    def page():
        panels.append(glimpse.attach(engine=RecordingEngine()))
        panels.append(glimpse.attach(engine=RecordingEngine()))

    await user.open('/')
    assert panel_of(user) is panels[1]


async def test_page_level_attach_wins_over_module_level(user: User):
    module_engine, page_engine = RecordingEngine(), RecordingEngine()
    glimpse.attach(engine=module_engine, probe=False)

    @ui.page('/')
    def page():
        ui.label('Hello')
        glimpse.attach(engine=page_engine, probe=False)

    await user.open('/')
    assert panel_of(user).session.engine is page_engine


async def test_reconnect_does_not_add_a_second_panel(user: User):
    glimpse.attach(engine=RecordingEngine(), probe=False)

    @ui.page('/')
    def page():
        ui.label('Hello')

    client = await user.open('/')
    first = panel_of(user)
    from nicegui import app

    for handler in app._connect_handlers:
        result = handler(client)
        assert result is None or not asyncio.iscoroutine(result)
    assert panel_of(user) is first


async def test_panel_events_drive_the_session(user: User):
    @ui.page('/')
    def page():
        ui.label('Body')
        glimpse.attach(engine=RecordingEngine('Hello'), probe=False, inspector='full', system_prompt='x')

    await user.open('/')
    panel = panel_of(user)

    class Event:
        def __init__(self, args):
            self.args = args

    handlers = {name: listener.handler for name, listener in _listeners(panel).items()}
    handlers['glimpse_send'](Event({'text': 'From the browser'}))
    await asyncio.wait_for(panel.session._task, 5)
    assert panel.session.turns[0].question == 'From the browser'
    handlers['glimpse_inspect'](Event({'id': 1}))
    handlers['glimpse_inspect'](Event({'id': 99}))
    handlers['glimpse_cancel'](Event({}))
    handlers['glimpse_clear'](Event({}))
    assert panel.session.turns == [] and panel.session.history == []


def _listeners(panel) -> dict:
    return {listener.type: listener for listener in panel._event_listeners.values()}


async def test_client_deletion_cancels_a_running_answer(user: User):
    """PA4 streams: a tab that goes away must stop the model call, not leave it running."""
    closed = asyncio.Event()

    async def engine(messages, page):
        try:
            yield 'start'
            await asyncio.sleep(60)
        finally:
            closed.set()

    @ui.page('/')
    def page():
        glimpse.attach(engine=engine, probe=False)

    client = await user.open('/')
    panel = panel_of(user)
    task = panel.ask('Q')
    await _until(lambda: panel.session.turns[0].text)
    client.delete()
    await asyncio.wait_for(task, 5)
    assert closed.is_set()


def test_messages_are_plain_data():
    assert Message('user', 'hi') == Message('user', 'hi')
