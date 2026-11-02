"""NFR-9: the failures developers report in similar tools, as named tests (Prior Art, PA4)."""

from __future__ import annotations

import asyncio
import time

from nicegui import ui
from nicegui.testing import User

import glimpse

from .conftest import second_user
from .helpers import RecordingEngine, ask, panel_of


async def test_context_not_arriving_after_navigation(user: User):
    """Grafana Logs Drilldown #2035: no context after navigation, and stale filters."""
    engine = RecordingEngine()
    glimpse.attach(engine=engine, probe=False)

    @ui.page('/a')
    def page_a():
        ui.label('Page A content')

    @ui.page('/b')
    def page_b():
        ui.label('Page B content')

    await user.open('/a')
    await ask(panel_of(user), 'Where am I?')
    assert 'Page A content' in engine.last_page.rendered
    await user.open('/b')
    await ask(panel_of(user), 'Where am I?')
    assert 'Page B content' in engine.last_page.rendered
    assert 'Page A content' not in engine.last_page.rendered


async def test_context_not_arriving_on_early_open(user: User):
    """A question asked at once, before anything on the page has changed, still gets the page."""
    engine = RecordingEngine()

    @ui.page('/')
    def page():
        ui.label('Ready at load')
        glimpse.attach(engine=engine, probe=False)

    await user.open('/')
    await ask(panel_of(user), 'Now')
    assert 'Ready at load' in engine.last_page.rendered


async def test_context_not_arriving_stale_filter(user: User):
    """The filter sent is the one at the moment of asking, every time."""
    engine = RecordingEngine()

    @ui.page('/')
    def page():
        ui.select(['A', 'B'], value='A', label='Filter', on_change=None)
        glimpse.attach(engine=engine, probe=False)

    await user.open('/')
    panel = panel_of(user)
    await ask(panel, 'one')
    assert 'Filter" = A' in engine.last_page.rendered
    with user:
        from nicegui import ElementFilter

        next(iter(ElementFilter(kind=ui.select))).set_value('B')
    await ask(panel, 'two')
    assert 'Filter" = B' in engine.last_page.rendered
    assert 'Filter" = A' not in engine.last_page.rendered


async def test_context_not_arriving_is_said_out_loud_when_the_probe_fails(user: User):
    """If the browser cannot report its state, the model is told so it does not answer with false confidence."""
    engine = RecordingEngine()

    @ui.page('/')
    def page():
        ui.aggrid({'columnDefs': [{'field': 'a'}], 'rowData': [{'a': 1}]})
        glimpse.attach(engine=engine, probe_timeout=0.01)

    await user.open('/')
    await ask(panel_of(user), 'Q')
    page_context = engine.last_page
    assert any('did not report' in note for note in page_context.notes)
    assert 'Capture note: The browser did not report' in page_context.rendered
    assert any(e.table for e in page_context.elements), 'server data is still sent'


async def test_probe_replies_are_validated(user: User):
    """A tampered or stale browser reply cannot crash a capture or add data."""
    from glimpse.adapters.nicegui.probe import apply_echart_state, apply_grid_state, apply_plotly_state

    table = glimpse.ElementSnapshot(id='g', kind='table', table=glimpse.TableData(columns=['a'], rows=[{'a': 1}]))
    notes: list[str] = []
    apply_grid_state(table, {'rows': [0, 99, -1, 'x', None], 'total': 1, 'filter': {}, 'sort': [], 'displayed': ['evil']},
                     notes)
    assert table.table.rows == [{'a': 1}] and table.table.columns == ['a']
    apply_grid_state(table, {'error': 'gone'}, notes)
    assert any('did not report' in note for note in notes)

    chart = glimpse.ElementSnapshot(id='c', kind='chart', series=[glimpse.Series(name='S', y=[1, 2, 3])])
    apply_echart_state(chart, {'zoom': {'start': 'x', 'end': None}, 'legend': 'bad'}, 'category', notes)
    assert chart.series[0].y == [1, 2, 3]
    apply_plotly_state(chart, {'range': 'bad', 'visible': 'bad'}, notes)
    assert chart.series[0].y == [1, 2, 3]


async def test_payload_growth_over_a_long_session(user: User):
    """CopilotKit #1482, assistant-ui #1767: full history on every request until HTTP 413."""
    engine = RecordingEngine('word ' * 300)

    @ui.page('/')
    def page():
        ui.label('Body')
        glimpse.attach(engine=engine, probe=False, budget=3000)

    await user.open('/')
    panel = panel_of(user)
    for turn in range(40):
        await ask(panel, f'Question {turn}')
        assert engine.last_page.report.used <= 3000
    assert engine.last_page.report.dropped_messages > 0


async def test_concurrent_sessions_two_users_at_once(user: User):
    """CopilotKit #2708: two users or tabs raised 'Step is already active'."""
    started = []

    async def engine(messages, page):
        started.append(messages[-1].content)
        await asyncio.sleep(0.05)
        yield f'Answer to {messages[-1].content}'

    @ui.page('/')
    def page(name: str = ''):
        ui.label(f'Data of {name}')
        glimpse.attach(engine=engine, probe=False)

    other = second_user()
    await user.open('/?name=first')
    await other.open('/?name=second')
    one, two = panel_of(user), panel_of(other)
    assert one is not two

    first, second = await asyncio.gather(ask(one, 'Q1'), ask(two, 'Q2'))
    assert first.status == 'done' and second.status == 'done'
    assert first.text == 'Answer to Q1' and second.text == 'Answer to Q2'
    assert 'Data of first' in first.page.rendered and 'Data of second' not in first.page.rendered
    assert 'Data of second' in second.page.rendered and 'Data of first' not in second.page.rendered
    assert sorted(started) == ['Q1', 'Q2']


async def test_concurrent_sessions_two_tabs_of_one_user(user: User):
    """Two tabs share cookies, so anything keyed on the user instead of the connection would collide."""
    engine = RecordingEngine()
    state = {'next': 0}

    @ui.page('/')
    def page():
        state['next'] += 1
        ui.label(f'Tab number {state["next"]}')
        glimpse.attach(engine=engine, probe=False)

    await user.open('/')
    one = panel_of(user)
    other = second_user()
    other.http_client.cookies = user.http_client.cookies
    await other.open('/')
    two = panel_of(other)
    await ask(one, 'From tab one')
    assert 'Tab number 1' in engine.last_page.rendered and two.session.turns == []
    await ask(two, 'From tab two')
    assert 'Tab number 2' in engine.last_page.rendered
    assert [message.content for message in engine.last_messages] == ['From tab two']


async def test_snapshot_does_not_block_the_event_loop(user: User):
    """NFR-4: one user's large table must not freeze the app for everyone."""
    rows = [{'id': i, 'city': f'City {i % 50}', 'amount': i % 1000} for i in range(300_000)]
    engine = RecordingEngine()

    @ui.page('/')
    def page():
        ui.table(columns=[{'name': name, 'label': name, 'field': name} for name in rows[0]], rows=rows,
                 pagination={'rowsPerPage': 10, 'sortBy': 'amount', 'descending': True})
        glimpse.attach(engine=engine, probe=False, redact=lambda text: text.upper())

    await user.open('/')
    panel = panel_of(user)
    task = panel.ask('Q')
    worst = 0.0
    while not task.done():
        before = time.perf_counter()
        await asyncio.sleep(0.005)
        worst = max(worst, time.perf_counter() - before - 0.005)
    assert panel.session.turns[0].status == 'done'
    assert 'Showing 50 of 300,000 rows' in engine.last_page.rendered
    # This is a smoke limit, not a target. Numeric targets wait for spike S1, as the SRS says.
    assert worst < 1.0, f'the event loop stalled for {worst:.3f}s'
