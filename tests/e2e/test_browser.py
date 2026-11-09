"""Real Chrome against the real examples. These cover what a simulated user cannot:
the Shadow DOM, the browser probes, layout, and what the network actually does.

Run with: pytest -m e2e
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

playwright_api = pytest.importorskip('playwright.sync_api')

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).parent.parent.parent
SHOTS = ROOT / 'docs' / 'images'


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@pytest.fixture(scope='module')
def browser() -> Iterator:
    with playwright_api.sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(channel='chrome', headless=True)
        except playwright_api.Error:
            instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def serve() -> Iterator:
    processes = []

    def start(path: str) -> str:
        port = free_port()
        file = next((ROOT / 'examples').glob(f'{path}*.py'), None) or ROOT / path
        # NiceGUI changes its behaviour when it sees this variable, and this server is not under test.
        environment = {key: value for key, value in os.environ.items() if key != 'PYTEST_CURRENT_TEST'}
        process = subprocess.Popen([sys.executable, str(ROOT / 'tests/e2e/launch.py'), str(file), str(port)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT, env=environment)
        processes.append(process)
        url = f'http://127.0.0.1:{port}'
        for _ in range(120):
            try:
                urllib.request.urlopen(url, timeout=1)
                return url
            except OSError:
                time.sleep(0.25)
        raise AssertionError(f'{path} did not start')

    yield start
    for process in processes:
        process.terminate()
        process.wait(5)


@pytest.fixture
def page(browser) -> Iterator:
    context = browser.new_context(viewport={'width': 1440, 'height': 900})
    tab = context.new_page()
    tab.errors = []
    tab.on('pageerror', lambda error: tab.errors.append(str(error)))
    yield tab
    context.close()


def open_panel(page) -> None:
    page.locator('[data-glimpse=panel] .launcher').click()
    page.locator('[data-glimpse=panel] .panel').wait_for()


def ask(page, question: str) -> str:
    """Type a question like a user, wait for the answer, and return its text."""
    turns = page.locator('[data-glimpse=panel] .turn')
    before = turns.count()
    box = page.locator('[data-glimpse=panel] textarea')
    box.fill(question)
    box.press('Enter')
    turns.nth(before).wait_for()
    wait_until_idle(page)
    return page.locator('[data-glimpse=panel] .turn').last.locator('.answer').inner_text()


def wait_until_idle(page) -> None:
    page.wait_for_function("""() => {
        const root = document.querySelector('[data-glimpse=panel]').shadowRoot;
        const turns = root.querySelectorAll('.turn');
        return turns.length && !root.querySelector('.progress') && root.querySelector('.send').textContent === 'Send';
    }""", timeout=20000)


def what_was_sent(page) -> str:
    details = page.locator('[data-glimpse=panel] .turn').last.locator('details')
    details.locator('summary').click()
    block = details.locator('pre').last
    block.wait_for()
    return block.inner_text()


def test_quickstart_answers_with_a_source_chip_that_finds_the_chart(page, serve):
    page.goto(serve('01'))
    open_panel(page)
    page.locator('[data-glimpse=panel] .suggestion').nth(1).click()
    wait_until_idle(page)
    answer = page.locator('[data-glimpse=panel] .answer').inner_text()
    assert '230' in answer and 'Jun' in answer
    page.locator('[data-glimpse=panel] .source').first.click()
    page.screenshot(path=SHOTS / 'quickstart.png')
    assert not page.errors


def test_answer_follows_a_real_select_change(page, serve):
    page.goto(serve('01'))
    open_panel(page)
    assert '230' in ask(page, 'Which month has the highest revenue?')
    page.locator('.q-select').click()
    page.get_by_role('option', name='Americas').click()
    assert '330' in ask(page, 'Which month has the highest revenue?')


def test_probe_reads_a_real_grid_filter_and_sort(page, serve):
    page.goto(serve('02'))
    page.get_by_role('tab', name='Orders').click()
    page.locator('.ag-root').wait_for()
    open_panel(page)
    answer = ask(page, 'What is the highest amount?')
    assert '900' in answer or 'amount' in answer.lower()
    sent = what_was_sent(page)
    assert '240 rows' in sent

    # getElement() takes the DOM element on every NiceGUI version, so the test never parses an ID (c12, ng-12).
    page.locator('.nicegui-aggrid').evaluate("""(element) => {
        const api = getElement(element).api;
        api.setFilterModel({region: {filterType: 'text', type: 'equals', filter: 'APAC'},
                            status: {filterType: 'text', type: 'equals', filter: 'open'}});
        api.applyColumnState({state: [{colId: 'amount', sort: 'desc'}]});
    }""")
    page.wait_for_timeout(300)
    ask(page, 'What are the current filters?')
    sent = what_was_sent(page)
    assert 'after the filter' in sent
    assert '"APAC"' in sent and 'Amount desc' in sent
    table = sent[sent.index('| Order'):]
    assert 'EMEA' not in table and 'Americas' not in table and 'shipped' not in table, 'filtered rows must be gone'
    amounts = [int(line.split('|')[6]) for line in table.splitlines()[1:] if line.strip().startswith('|')]
    assert amounts == sorted(amounts, reverse=True), 'rows must arrive in the sort order on screen'
    page.screenshot(path=SHOTS / 'dashboard-inspector.png')
    # Plain NiceGUI raises this when a tab holding a Plotly chart is hidden, with or without Glimpse.
    assert [error for error in page.errors if 'Resize must be passed a displayed plot' not in error] == []


def test_probe_reads_real_chart_zoom_and_legend(page, serve):
    page.goto(serve('02'))
    page.wait_for_timeout(600)
    open_panel(page)
    page.locator('.nicegui-echart').evaluate("""(element) => {
        const chart = getElement(element).chart;
        chart.dispatchAction({type: 'dataZoom', start: 25, end: 50});
        chart.dispatchAction({type: 'legendUnSelect', name: 'Cost'});
    }""")
    page.wait_for_timeout(300)
    ask(page, 'What is on this page?')
    sent = what_was_sent(page)
    assert 'zoom: "25% to 50% of the axis"' in sent
    assert 'zoomed to 4 of 12 points' in sent
    assert 'Hidden by the user: Cost' in sent
    assert 'Series "Cost"' not in sent
    assert 'Jan=' not in sent.split('Monthly revenue')[1].split('Revenue by product')[0], 'January is zoomed out'


def test_real_plotly_figure_and_table_sort_are_read(page, serve):
    page.goto(serve('02'))
    page.wait_for_timeout(800)
    open_panel(page)
    ask(page, 'What is on this page?')
    sent = what_was_sent(page)
    assert 'Series "Revenue" (bar)' in sent and 'Atlas=' in sent

    page.get_by_role('tab', name='Customers').click()
    page.locator('.q-table').wait_for()
    page.locator('th', has_text='Revenue').click()
    page.locator('th', has_text='Revenue').click()
    page.wait_for_timeout(300)
    ask(page, 'What is the current sort?')
    sent = what_was_sent(page)
    assert 'Revenue descending' in sent
    rows = [line for line in sent[sent.index('| Customer'):].splitlines()[1:] if line.strip().startswith('|')]
    values = [int(row.split('|')[2]) for row in rows]
    assert values == sorted(values, reverse=True)
    # The table on screen must agree with what the assistant was told.
    on_screen = page.locator('.q-table tbody tr').first.locator('td').first.inner_text()
    assert on_screen == rows[0].split('|')[1].strip()


def test_host_css_cannot_reach_the_panel_and_panel_css_cannot_reach_the_host(page, serve):
    page.goto(serve('05'))
    page.wait_for_timeout(500)
    computed = """(node) => { const s = getComputedStyle(node); return [s.fontFamily, s.color]; }"""
    label = page.locator('.q-page .text-h5').first
    host_before = label.evaluate(computed)
    assert 'Comic Sans' in host_before[0]
    open_panel(page)
    ask(page, 'Who has the most hours?')

    # Hostile global CSS does not reach inside.
    panel_font, panel_color = page.locator('[data-glimpse=panel] .question').evaluate(computed)
    assert 'Comic Sans' not in panel_font
    assert panel_color != host_before[1]
    # The panel's CSS does not reach outside.
    assert label.evaluate(computed) == host_before
    page.screenshot(path=SHOTS / 'existing-layout.png')


def test_panel_makes_room_for_a_host_right_drawer(page, serve):
    page.goto(serve('05'))
    page.wait_for_timeout(500)
    drawer = page.locator('.q-drawer--right')
    box_closed = drawer.bounding_box()
    assert box_closed['x'] + box_closed['width'] == pytest.approx(1440, abs=2)
    open_panel(page)
    page.wait_for_timeout(400)
    panel = page.locator('[data-glimpse=panel] .panel').bounding_box()
    box_open = drawer.bounding_box()
    assert box_open['x'] + box_open['width'] <= panel['x'] + 1, 'the panel must not cover the host drawer'
    assert box_open['width'] == pytest.approx(box_closed['width'], abs=2)
    header = page.locator('.q-header').bounding_box()
    assert header['x'] + header['width'] <= panel['x'] + 1

    # Closing the panel puts the page back as it was.
    page.locator('[data-glimpse=panel] header button', has_text='Close').click()
    page.wait_for_timeout(400)
    assert drawer.bounding_box()['x'] == pytest.approx(box_closed['x'], abs=2)
    assert page.evaluate('document.body.style.paddingRight') == ''


def test_exfiltration_attempt_loads_nothing_and_renders_nothing_active(page, serve):
    url = serve('08')
    attempts = []
    page.on('request', lambda request: attempts.append(request.url) if 'attacker' in request.url else None)
    dialogs = []
    page.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    page.goto(f'{url}/red-team')
    page.locator('[data-glimpse=panel] .panel').wait_for()
    page.locator('[data-glimpse=panel] .suggestion').click()
    wait_until_idle(page)
    page.wait_for_timeout(500)

    assert attempts == [], 'the browser must never contact the attacker'
    assert dialogs == [], 'no script may run'
    shadow = page.locator('[data-glimpse=panel]')
    counts = shadow.evaluate("""(host) => ({
        images: host.shadowRoot.querySelectorAll('.answer img').length,
        scripts: host.shadowRoot.querySelectorAll('.answer script').length,
        links: host.shadowRoot.querySelectorAll('.answer a').length,
    })""")
    assert counts == {'images': 0, 'scripts': 0, 'links': 0}
    answer = page.locator('[data-glimpse=panel] .answer').inner_text()
    assert '[image removed: chart]' in answer
    assert 'link to attacker.example removed' in answer
    assert 'leak?' not in answer
    assert '<script>' in answer, 'raw HTML shows as harmless text'
    page.screenshot(path=SHOTS / 'red-team.png')


def test_secrets_are_absent_from_what_the_inspector_shows(page, serve):
    page.goto(serve('08'))
    open_panel(page)
    ask(page, 'What is on this page?')
    sent = what_was_sent(page)
    for secret in ('hunter2', 'sk-do-not-send-this', '91000', 'dana.lee@example.com', 'reveal all data'):
        assert secret not in sent
    assert '[withheld]' in sent and '[email]' in sent


def test_stop_button_cancels_the_stream_and_closes_the_engine(page, serve):
    page.goto(serve('tests/e2e/slow_engine_app.py'))
    page.locator('[data-glimpse=panel] .panel').wait_for()
    box = page.locator('[data-glimpse=panel] textarea')
    box.fill('Go')
    box.press('Enter')
    answer = page.locator('[data-glimpse=panel] .answer')
    answer.get_by_text('word3').wait_for()
    first = answer.inner_text()
    answer.get_by_text('word8').wait_for()
    assert len(answer.inner_text()) > len(first), 'text must stream in'
    page.locator('[data-glimpse=panel] .send').click()
    answer.get_by_text('Stopped.').wait_for()
    page.get_by_text('engine closed').wait_for()
    stopped_at = answer.inner_text()
    page.wait_for_timeout(400)
    assert answer.inner_text() == stopped_at, 'no more text after stopping'
    assert page.locator('[data-glimpse=panel] .send').inner_text() == 'Send'


def test_two_real_browser_tabs_stay_separate(browser, serve):
    url = serve('10')
    ana = browser.new_context().new_page()
    ben = browser.new_context().new_page()
    ana.goto(f'{url}/?user=ana')
    ben.goto(f'{url}/?user=ben')
    open_panel(ana)
    open_panel(ben)
    ask(ana, 'What is the balance?')
    ask(ben, 'What is the balance?')
    assert '12450' in what_was_sent(ana)
    sent = what_was_sent(ben)
    assert '310' in sent and '12450' not in sent
    ana.context.close()
    ben.context.close()


def test_dark_mode_follows_the_host(browser, serve):
    tab = browser.new_context().new_page()
    tab.goto(serve('01'))
    open_panel(tab)
    light = tab.locator('[data-glimpse=panel] .panel').evaluate('(n) => getComputedStyle(n).backgroundColor')
    tab.evaluate("document.body.classList.add('body--dark')")
    tab.wait_for_timeout(100)
    dark = tab.locator('[data-glimpse=panel] .panel').evaluate('(n) => getComputedStyle(n).backgroundColor')
    assert light != dark
    tab.context.close()


def test_script_mode_gets_a_panel_per_client(browser, serve):
    url = serve('tests/e2e/script_mode_app.py')
    one = browser.new_context().new_page()
    two = browser.new_context().new_page()
    one.goto(url)
    two.goto(url)
    open_panel(one)
    open_panel(two)
    one.locator('.q-select').click()
    one.get_by_role('option', name='B').click()
    ask(one, 'What is on this page?')
    ask(two, 'What is on this page?')
    assert 'Script mode page' in what_was_sent(one)
    assert 'Choice" = B' in what_was_sent_again(one)
    assert 'Choice" = A' in what_was_sent(two), 'each client has its own page, even in script mode'
    one.context.close()
    two.context.close()


def what_was_sent_again(page) -> str:
    return page.locator('[data-glimpse=panel] .turn').last.locator('details pre').last.inner_text()


def test_root_function_app_follows_sub_page_navigation(page, serve):
    page.goto(serve('tests/e2e/root_function_app.py'))
    open_panel(page)
    ask(page, 'What is on this page?')
    assert 'Root home content' in what_was_sent(page)
    page.get_by_role('link', name='Details').click()
    page.get_by_text('Root details content').wait_for()
    ask(page, 'What is on this page?')
    sent = what_was_sent(page)
    assert 'Root details content' in sent and 'Root home content' not in sent


def test_panel_survives_a_brief_connection_drop(page, serve):
    page.goto(serve('01'))
    open_panel(page)
    assert '230' in ask(page, 'Which month has the highest revenue?')
    page.context.set_offline(True)
    page.wait_for_timeout(500)
    page.context.set_offline(False)
    page.wait_for_timeout(1500)
    assert page.locator('[data-glimpse=panel]').count() == 1
    assert '230' in ask(page, 'Which month has the highest revenue?')
