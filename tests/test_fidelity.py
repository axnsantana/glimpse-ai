"""The S0 question set: values, trends, comparisons and filtered state on the reference dashboard.

test_context_holds_the_facts needs no model. For each question it checks that the facts
needed to answer are in what the model would receive, or a tool call away. That tests
capture fidelity on its own (NFR-5), and it is what runs in CI.

test_live_answers scores a real model on the same questions, and test_live_budget_holds checks
real requests against the free token counting endpoint. The scoring spends about $0.35 on Claude
Opus 5.5, so it only runs when asked for. Pass thresholds wait for spike S1, so it reports its score:

    GLIMPSE_EVAL_MODEL=anthropic:claude-opus-5-5 ANTHROPIC_API_KEY=... pytest -m live -s
"""

from __future__ import annotations

import asyncio
import os
import random
import re
from dataclasses import dataclass, replace

import pytest
from nicegui import ElementFilter, ui

import glimpse

from .helpers import EXAMPLES, ask, panel_of

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
REGIONS = ['EMEA', 'Americas', 'APAC']
PRODUCTS = ['Atlas', 'Beacon', 'Comet', 'Delta']
CUSTOMERS = ['Acme', 'Globex', 'Initech', 'Umbrella', 'Hooli', 'Stark', 'Wayne', 'Soylent']


def orders() -> list[dict]:
    """An independent copy of the example's data, so that a capture bug cannot grade itself."""
    rng = random.Random(7)
    return [{
        'order': f'SO-{1000 + i}', 'month': MONTHS[i % 12], 'region': REGIONS[i % 3], 'product': rng.choice(PRODUCTS),
        'customer': rng.choice(CUSTOMERS), 'amount': rng.randint(50, 900),
        'status': rng.choice(['open', 'shipped', 'shipped', 'returned']),
    } for i in range(240)]


def total(rows: list[dict], key: str, name: str) -> int:
    return sum(row['amount'] for row in rows if row[key] == name)


def by_month(rows: list[dict]) -> dict[str, int]:
    return {month: total(rows, 'month', month) for month in MONTHS}


def top(values: dict[str, int]) -> str:
    return max(values, key=values.get)


def low(values: dict[str, int]) -> str:
    return min(values, key=values.get)


ALL = orders()
EMEA = [row for row in ALL if row['region'] == 'EMEA']
AMERICAS = [row for row in ALL if row['region'] == 'Americas']
MONTHLY, EMEA_MONTHLY, AMERICAS_MONTHLY = by_month(ALL), by_month(EMEA), by_month(AMERICAS)
PRODUCT = {name: total(ALL, 'product', name) for name in PRODUCTS}
EMEA_PRODUCT = {name: total(EMEA, 'product', name) for name in PRODUCTS}
CUSTOMER = {name: total(ALL, 'customer', name) for name in CUSTOMERS}


@dataclass(frozen=True)
class Case:
    question: str
    category: str
    facts: tuple[str, ...]
    """Strings the model needs in its context, and that a right answer should contain."""
    region: str = 'All'
    tab: str = 'Overview'


CASES = [
    # Reading values.
    Case('What is the total revenue shown?', 'value', (f'{sum(MONTHLY.values()):,}',)),
    Case('How many orders are shown?', 'value', ('Orders: 240',)),
    Case('What was revenue in March?', 'value', (f'Mar={MONTHLY["Mar"]}',)),
    Case('What was cost in June?', 'value', (f'Jun={round(MONTHLY["Jun"] * 0.62)}',)),
    Case('What is the revenue for product Comet?', 'value', (f'Comet={PRODUCT["Comet"]}',)),
    Case('What is the amount of order SO-1000?', 'value', (str(ALL[0]['amount']),), tab='Orders'),
    Case('What is the revenue of customer Hooli?', 'value', (str(CUSTOMER['Hooli']),), tab='Customers'),
    Case('Which regions can I pick?', 'value', ('EMEA', 'Americas', 'APAC')),
    # Trends and extremes.
    Case('Which month has the highest revenue?', 'trend', (top(MONTHLY), str(MONTHLY[top(MONTHLY)]))),
    Case('Which month has the lowest revenue?', 'trend', (low(MONTHLY), str(MONTHLY[low(MONTHLY)]))),
    Case('Which month has the highest cost?', 'trend', (top(MONTHLY),)),
    Case('Is revenue rising or falling from January to December?', 'trend',
         (f'Jan={MONTHLY["Jan"]}', f'Dec={MONTHLY["Dec"]}')),
    Case('Which product sells the most?', 'trend', (top(PRODUCT), str(PRODUCT[top(PRODUCT)]))),
    Case('Which customer brings in the most revenue?', 'trend', (top(CUSTOMER), str(CUSTOMER[top(CUSTOMER)])),
         tab='Customers'),
    # Comparisons.
    Case('Is revenue higher in February or in August?', 'comparison', (f'Feb={MONTHLY["Feb"]}', f'Aug={MONTHLY["Aug"]}')),
    Case('Which is bigger, Atlas or Delta?', 'comparison', (f'Atlas={PRODUCT["Atlas"]}', f'Delta={PRODUCT["Delta"]}')),
    Case('How does cost compare with revenue in July?', 'comparison',
         (f'Jul={MONTHLY["Jul"]}', f'Jul={round(MONTHLY["Jul"] * 0.62)}')),
    Case('Who brings in more revenue, Acme or Stark?', 'comparison', (str(CUSTOMER['Acme']), str(CUSTOMER['Stark'])),
         tab='Customers'),
    # State after filtering.
    Case('Which region is selected?', 'filtered', ('Region" = EMEA',), region='EMEA'),
    Case('What is the revenue now?', 'filtered', (f'{sum(EMEA_MONTHLY.values()):,}',), region='EMEA'),
    Case('How many orders are shown now?', 'filtered', (f'Orders: {len(EMEA)}',), region='EMEA'),
    Case('Which month is highest for this region?', 'filtered', (top(EMEA_MONTHLY),), region='EMEA'),
    Case('Which product leads in this region?', 'filtered', (top(EMEA_PRODUCT),), region='EMEA'),
    Case('What was revenue in May for this region?', 'filtered', (f'May={AMERICAS_MONTHLY["May"]}',), region='Americas'),
    Case('Which tab am I on?', 'filtered', ('Tabs" = Customers',), tab='Customers'),
    Case('How many orders does the grid show for this region?', 'filtered', (f'of {len(EMEA)} rows',), region='EMEA',
         tab='Orders'),
]


def test_question_set_covers_the_categories_the_spike_asks_for():
    categories = {case.category for case in CASES}
    assert categories == {'value', 'trend', 'comparison', 'filtered'}
    assert 20 <= len(CASES) <= 30


async def _apply(user, case: Case) -> None:
    with user:
        region = next(iter(ElementFilter(kind=ui.select)))
        tabs = next(iter(ElementFilter(kind=ui.tabs)))
    region.set_value(case.region)
    tabs.set_value(case.tab)
    await asyncio.sleep(0)


@pytest.mark.parametrize('case', CASES, ids=lambda case: case.question)
async def test_context_holds_the_facts(case: Case, open_example):
    async with open_example('02') as user:
        await user.open('/')
        panel = panel_of(user)
        panel.session.config = replace(panel.session.config, probe=False)
        await _apply(user, case)
        page = (await ask(panel, case.question)).page
        rendered = page.rendered
        for fact in case.facts:
            assert fact in rendered, f'{fact!r} is missing from the context for: {case.question}'


async def test_grid_filter_in_the_browser_reduces_what_the_model_sees(open_example):
    """The hardest filtered case: state only the browser knows. tests/e2e covers it with a real grid."""
    async with open_example('02') as user:
        await user.open('/')
        panel = panel_of(user)
        await _apply(user, Case('', 'filtered', (), tab='Orders'))

        def reply(_match):
            with user:
                grid = next(iter(ElementFilter(kind=ui.aggrid)))
            kept = [index for index, row in enumerate(ALL) if row['status'] == 'open']
            return {'grids': {str(grid.id): {
                'rows': kept, 'total': len(kept), 'filter': {'status': {'filter': 'open'}}, 'quick': '', 'sort': [],
                'displayed': [], 'selected': [], 'selected_count': 0}}, 'echarts': {}, 'plotlies': {}}

        user.javascript_rules[re.compile(r'[\s\S]*const out = \{grids')] = reply
        page = (await ask(panel, 'What is the highest amount of the open orders?')).page
        grid = next(element for element in page.elements if element.table)
        assert {row['status'] for row in grid.table.rows} == {'open'}
        best = max(row['amount'] for row in ALL if row['status'] == 'open')
        assert f'max {best}' in page.rendered or str(best) in page.rendered


def expected_answers(case: Case) -> list[str]:
    """What a right answer must contain: the value part of each fact, without its label in the context."""
    answers = []
    for fact in case.facts:
        match = re.search(r'of (\d+) rows$', fact)
        value = match.group(1) if match else fact.split('=')[-1].split(': ')[-1]
        answers.append(value.strip().replace(',', ''))
    return answers


def test_expected_answers_are_plain_values():
    assert expected_answers(Case('', 'value', ('Mar=1234', 'Orders: 240', 'Region" = EMEA', '112,830', 'of 80 rows'))) == [
        '1234', '240', 'EMEA', '112830', '80',
    ]


@pytest.mark.live
@pytest.mark.timeout(1500)
async def test_live_answers():
    """Score a real model. Spends money, so it runs only with -m live and GLIMPSE_EVAL_MODEL."""
    from nicegui.testing.user_simulation import user_simulation

    model = os.environ.get('GLIMPSE_EVAL_MODEL')
    if not model:
        pytest.skip('Set GLIMPSE_EVAL_MODEL to run this.')
    passed: dict[str, list[bool]] = {}
    input_tokens = output_tokens = 0
    ratios = []
    cited = 0
    for case in CASES:
        async with user_simulation(main_file=EXAMPLES / '02_sales_dashboard.py') as user:
            await user.open('/')
            panel = panel_of(user)
            panel.session.engine = glimpse.DirectEngine(model)
            panel.session.config = replace(panel.session.config, probe=False)
            await _apply(user, case)
            turn = await ask(panel, case.question, timeout=180)
            text = turn.text.replace(',', '')
            good = turn.status == 'done' and all(answer in text for answer in expected_answers(case))
            passed.setdefault(case.category, []).append(good)
            if turn.usage:
                input_tokens += turn.usage.input_tokens
                output_tokens += turn.usage.output_tokens
                if not turn.tool_calls and turn.usage.input_tokens:
                    ratios.append(turn.page.report.used / turn.usage.input_tokens)
            cited += bool(turn.citations)
            print(f'{"PASS" if good else "FAIL"} [{case.category}] {case.question}  want={expected_answers(case)} '
                  f'tools={[call["name"] for call in turn.tool_calls]} {turn.error}\n     {turn.text[:260]!r}', flush=True)
    for category, results in passed.items():
        print(f'{category}: {sum(results)}/{len(results)}')
    everything = [result for results in passed.values() for result in results]
    print(f'overall: {sum(everything)}/{len(everything)}, answers with a citation: {cited}/{len(CASES)}')
    print(f'tokens: {input_tokens} in, {output_tokens} out')
    if ratios:
        print(f'estimate / actual input tokens: min {min(ratios):.2f}, max {max(ratios):.2f}')


@pytest.mark.live
@pytest.mark.timeout(300)
@pytest.mark.parametrize('budget', [6000, 8000, 16000, 64000])
async def test_live_budget_holds(budget):
    """CTX-1 against the free token counting endpoint: what is really sent fits the budget, whatever the page holds."""
    anthropic = pytest.importorskip('anthropic')
    from glimpse.builder import prepare_request
    from glimpse.prompt import user_turn

    if not (os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('ANTHROPIC_AUTH_TOKEN')):
        pytest.skip('Needs Anthropic credentials. Counting tokens is free.')
    rng = random.Random(budget)
    numbers = [{'order': f'SO-{i}', 'city': rng.choice(['Porto', 'Lyon']), 'amount': rng.randint(50, 900),
                'ratio': round(rng.random(), 4), 'when': f'2026-{i % 12 + 1:02d}-{i % 28 + 1:02d}'} for i in range(3000)]
    long_words = 'Rücksendungsbearbeitungsgebühren Umsatzsteuervoranmeldung Datenschutzgrundverordnung ' * 300
    pages = {
        'numbers': [
            glimpse.ElementSnapshot(id='table-1', kind='table', label='Orders',
                                    table=glimpse.TableData(columns=list(numbers[0]), rows=numbers)),
            glimpse.ElementSnapshot(id='chart-1', kind='chart', series=[glimpse.Series(
                name='S', x=[f'd{i}' for i in range(90)], y=[round(rng.random(), 3) for _ in range(90)])]),
        ],
        'long words': [glimpse.ElementSnapshot(id=f'text-{i}', kind='text', text=long_words) for i in range(4)],
        'cjk': [glimpse.ElementSnapshot(id=f'text-{i}', kind='text', text='今月の売上は前年同月比で増加しました。' * 200)
                for i in range(6)],
    }
    client = anthropic.AsyncAnthropic()
    engine = glimpse.DirectEngine('m')
    tools = [{'name': tool.name, 'description': tool.description, 'input_schema': tool.parameters}
             for tool in glimpse.PageContext().tools]
    worst = 0.0
    for name, elements in pages.items():
        history = [glimpse.Message('user' if i % 2 == 0 else 'assistant',
                                   f'Earlier message {i}. ' + 'The total rose by 12.5%. ' * 60) for i in range(40)]
        page = glimpse.PageContext(title=name, elements=elements, developer_context='Amounts are in EUR. ' * 100)
        messages, page = prepare_request(page, history, 'What is the total?', glimpse.GlimpseConfig(budget=budget),
                                         overhead_text=engine.overhead_text(page))
        sent = [{'role': m.role, 'content': m.content} for m in messages[:-1]]
        sent.append({'role': 'user', 'content': user_turn(page, messages[-1].content)})
        counted = await client.messages.count_tokens(model='claude-opus-5-5', system=glimpse.DEFAULT_SYSTEM_PROMPT,
                                                     tools=tools, messages=sent)
        print(f'budget {budget} {name}: real {counted.input_tokens}, estimated {page.report.used}')
        worst = max(worst, counted.input_tokens / budget)
        assert counted.input_tokens <= budget, name
    await client.close()
    print(f'budget {budget}: worst use {worst:.0%}')
