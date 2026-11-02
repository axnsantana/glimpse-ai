"""What capture reads from each kind of element, with no annotations."""

from __future__ import annotations

import plotly.graph_objects as go
import pytest
from nicegui import ui
from nicegui.testing import User

import glimpse

from .helpers import RecordingEngine, ask, element_by_label, panel_of


async def capture(user: User, path: str = '/', **_) -> glimpse.PageContext:
    await user.open(path)
    panel = panel_of(user)
    return (await ask(panel, 'What is on this page?')).page


def attach(**options) -> RecordingEngine:
    engine = RecordingEngine()
    glimpse.attach(engine=engine, probe=False, **options)
    return engine


async def test_inputs_report_their_current_values(user: User):
    @ui.page('/')
    def page():
        ui.input('Name', value='Ada')
        ui.number('Limit', value=7)
        ui.textarea('Notes', value='Line')
        ui.select({'a': 'Alpha', 'b': 'Beta'}, value='b', label='Mode')
        ui.select(['x', 'y'], value=['x', 'y'], multiple=True, label='Many')
        ui.radio(['r1', 'r2'], value='r2')
        ui.toggle({1: 'One', 2: 'Two'}, value=2)
        ui.checkbox('Agree', value=True)
        ui.switch('Live', value=False)
        ui.label('Threshold')
        ui.slider(min=0, max=10, value=4)
        ui.date(value='2026-01-02')
        attach()

    page_context = await capture(user)
    values = {e.label: e.value for e in page_context.elements if e.has_value}
    assert values['Name'] == 'Ada'
    assert values['Limit'] == 7
    assert values['Notes'] == 'Line'
    assert values['Mode'] == 'Beta', 'the label the user sees, not the internal key'
    assert values['Many'] == ['x', 'y']
    assert values['Agree'] is True
    assert values['Live'] is False
    assert values['Threshold'] == 4, 'an unlabelled slider takes the text right before it'
    unlabelled = [e.value for e in page_context.elements if e.has_value and not e.label]
    assert 'r2' in unlabelled
    assert 'Two' in unlabelled, 'the label the user sees, not the internal key'
    assert element_by_label(page_context, 'Mode').options == ['Alpha', 'Beta']


async def test_text_markdown_and_html_are_read_as_visible_text(user: User):
    @ui.page('/')
    def page():
        ui.label('Plain label')
        ui.markdown('**Bold** words <!-- hidden comment instruction -->')
        ui.html('<div><b>Shown</b><span hidden>secret attr</span>'
                '<span style="display: none">secret style</span>'
                '<span style="opacity:0">secret opacity</span>'
                '<span style="font-size: 0px">secret size</span>'
                '<span class="hidden">secret class</span></div>', sanitize=False)
        ui.code('x = 1', language='python')
        ui.mermaid('graph TD; A-->B')
        attach()

    rendered = (await capture(user)).rendered
    assert 'Plain label' in rendered and 'Bold' in rendered and 'Shown' in rendered
    assert 'x = 1' in rendered and 'A-->B' in rendered
    assert 'secret' not in rendered
    assert 'hidden comment' not in rendered


def test_html_scripts_and_styles_are_not_text():
    from glimpse.adapters.nicegui.extractors import visible_text_of_html

    text = visible_text_of_html('<style>x{}</style><script>bad()</script><p>Good<br>line</p><img src=x>'
                                '<div hidden><p>nested <b>secret</b></p></div>After')
    assert text == 'Goodline After' or text == 'Good line After'
    assert 'bad' not in text and 'secret' not in text


async def test_elements_the_user_cannot_see_are_not_read(user: User):
    @ui.page('/')
    def page():
        ui.label('Seen')
        ui.label('Not visible').set_visibility(False)
        with ui.column().classes('hidden'):
            ui.label('Hidden by class')
        with ui.column().style('display: none'):
            ui.label('Hidden by style')
        with ui.column().classes('sr-only'):
            ui.label('Screen reader only')
        with ui.column() as outer:
            ui.label('Hidden through parent')
        outer.set_visibility(False)
        with ui.dialog():
            ui.label('In a closed dialog')
        with ui.button('Menu'):
            with ui.menu():
                ui.menu_item('In a closed menu')
        with ui.label('Hover me'):
            ui.tooltip('Tooltip text')
        attach()

    rendered = (await capture(user)).rendered
    assert 'Seen' in rendered and 'Hover me' in rendered
    for absent in ('Not visible', 'Hidden by class', 'Hidden by style', 'Screen reader only', 'Hidden through parent',
                   'closed dialog', 'closed menu', 'Tooltip text'):
        assert absent not in rendered, absent


async def test_open_dialog_is_read(user: User):
    @ui.page('/')
    def page():
        dialog = ui.dialog()
        with dialog:
            ui.label('Dialog body')
        dialog.open()
        attach()

    page_context = await capture(user)
    assert 'Dialog body' in page_context.rendered
    assert element_for_text(page_context, 'Dialog body').section == 'Dialog'


def element_for_text(page: glimpse.PageContext, text: str):
    return next(element for element in page.elements if element.text == text)


def tabbed_page() -> None:
    with ui.tabs() as tabs:
        one = ui.tab('One')
        ui.tab('Two')
    with ui.tab_panels(tabs, value=one):
        with ui.tab_panel('One'):
            ui.label('First tab body')
        with ui.tab_panel('Two'):
            ui.label('Second tab body')
            ui.table(columns=[{'name': 'a', 'label': 'A', 'field': 'a'}], rows=[{'a': 'cell'}])
    with ui.expansion('More', value=False):
        ui.label('Collapsed body')
    with ui.expansion('Open part', value=True):
        ui.label('Expanded body')


async def test_visibility_policy_visible_is_the_default(user: User):
    @ui.page('/')
    def page():
        tabbed_page()
        attach()

    page_context = await capture(user)
    rendered = page_context.rendered
    assert 'First tab body' in rendered and 'Expanded body' in rendered
    assert 'Second tab body' not in rendered and 'cell' not in rendered and 'Collapsed body' not in rendered
    stub = element_by_label(page_context, 'Tab: Two')
    assert stub.hidden_reason == 'inactive tab' and 'Contains 1 table' in stub.description
    assert element_by_label(page_context, 'Expansion: More').hidden_reason == 'collapsed'


async def test_visibility_policy_reachable_reads_more_and_marks_it(user: User):
    @ui.page('/')
    def page():
        tabbed_page()
        attach(visibility='reachable')

    page_context = await capture(user)
    rendered = page_context.rendered
    assert 'Second tab body' in rendered and 'cell' in rendered and 'Collapsed body' in rendered
    assert element_for_text(page_context, 'Second tab body').hidden_reason == 'inactive tab'
    assert element_for_text(page_context, 'First tab body').hidden_reason == ''
    assert 'Entries marked "not visible"' in rendered


def test_invalid_settings_fail_at_attach():
    with pytest.raises(ValueError, match='visibility'):
        glimpse.GlimpseConfig(visibility='everything')
    with pytest.raises(ValueError, match='budget'):
        glimpse.GlimpseConfig(budget=10)


async def test_table_reports_filter_sort_selection_and_hidden_columns(user: User):
    @ui.page('/')
    def page():
        table = ui.table(
            title='People',
            columns=[{'name': 'name', 'label': 'Name', 'field': 'name', 'sortable': True},
                     {'name': 'age', 'label': 'Age', 'field': 'age', 'sortable': True},
                     {'name': 'city', 'label': 'City', 'field': 'city'}],
            rows=[{'name': 'Ana', 'age': 30, 'city': 'Porto', 'internal': 'x1'},
                  {'name': 'Ben', 'age': 25, 'city': 'Lyon', 'internal': 'x2'},
                  {'name': 'Abe', 'age': 41, 'city': 'Porto', 'internal': 'x3'}],
            row_key='name', selection='single', pagination={'rowsPerPage': 2, 'sortBy': 'age', 'descending': True},
        )
        table.filter = 'porto'
        table.selected = [table.rows[0]]
        attach()

    page_context = await capture(user)
    table = element_by_label(page_context, 'People')
    assert [row['name'] for row in table.table.rows] == ['Abe', 'Ana'], 'filtered and sorted as on screen'
    assert table.table.source_rows == 3
    assert table.state['filter'] == 'porto'
    assert table.state['sorted_by'] == 'Age descending'
    assert table.state['selected'] == ['Ana']
    assert table.state['rows_per_page'] == 2
    assert all('internal' not in row for row in table.table.rows), 'keys not on screen never reach an engine'
    assert 'x1' not in page_context.rendered


async def test_aggrid_columns_nested_fields_and_groups(user: User):
    @ui.page('/')
    def page():
        ui.aggrid({
            'columnDefs': [
                {'field': 'name', 'headerName': 'Name'},
                {'headerName': 'Contact', 'children': [{'field': 'info.email', 'headerName': 'Email'}]},
                {'field': 'hiddenone', 'hide': True},
                {'headerName': 'Computed', 'valueGetter': 'data.a + 1'},
            ],
            'rowData': [{'name': 'Ana', 'info': {'email': 'a@x.io'}, 'hiddenone': 'nope'}],
        })
        attach()

    page_context = await capture(user)
    table = next(element for element in page_context.elements if element.table)
    assert table.table.columns == ['name', 'info.email']
    assert table.table.rows == [{'name': 'Ana', 'info.email': 'a@x.io'}]
    assert table.state['computed_columns_not_readable'] == ['Computed']
    assert 'nope' not in page_context.rendered


async def test_aggrid_from_pandas(user: User):
    import pandas as pd

    @ui.page('/')
    def page():
        ui.aggrid.from_pandas(pd.DataFrame({'city': ['Porto'], 'population': [230000]}))
        attach()

    table = next(element for element in (await capture(user)).elements if element.table)
    assert table.table.rows == [{'city': 'Porto', 'population': 230000}]


@pytest.mark.parametrize('data, expected_x, expected_y', [
    ([1, 2, 3], ['a', 'b', 'c'], [1, 2, 3]),
    ([{'value': 1}, {'value': 2}, {'value': 3}], ['a', 'b', 'c'], [1, 2, 3]),
    ([['a', 5], ['b', 6]], ['a', 'b'], [5, 6]),
])
async def test_echart_data_forms(user: User, data, expected_x, expected_y):
    @ui.page('/')
    def page():
        ui.echart({'xAxis': {'type': 'category', 'data': ['a', 'b', 'c']}, 'yAxis': {},
                   'series': [{'type': 'line', 'name': 'S', 'data': data}]})
        attach()

    chart = next(element for element in (await capture(user)).elements if element.kind == 'chart')
    assert chart.series[0].x == expected_x
    assert chart.series[0].y == expected_y


async def test_echart_pie_dataset_horizontal_and_preset_legend(user: User):
    @ui.page('/')
    def page():
        ui.echart({'title': {'text': 'Pie'}, 'series': [{'type': 'pie', 'data': [{'name': 'A', 'value': 3}]}]})
        ui.echart({'title': {'text': 'Rows'},
                   'dataset': {'source': [['q', 'x1', 'x2'], ['Q1', 1, 2], ['Q2', 3, 4]]},
                   'xAxis': {'type': 'category'}, 'yAxis': {},
                   'series': [{'type': 'bar'}, {'type': 'bar'}]})
        ui.echart({'title': {'text': 'Objects'},
                   'dataset': {'source': [{'m': 'Jan', 'v': 9}]},
                   'xAxis': {'type': 'category'}, 'yAxis': {},
                   'series': [{'type': 'bar', 'encode': {'x': 'm', 'y': 'v'}}]})
        ui.echart({'title': {'text': 'Sideways'}, 'xAxis': {'type': 'value'},
                   'yAxis': {'type': 'category', 'data': ['p', 'q']},
                   'series': [{'type': 'bar', 'name': 'B', 'data': [7, 8]}]})
        ui.echart({'title': {'text': 'Legend'}, 'legend': {'selected': {'Off': False}},
                   'xAxis': {'type': 'category', 'data': ['a']}, 'yAxis': {},
                   'series': [{'name': 'On', 'type': 'bar', 'data': [1]}, {'name': 'Off', 'type': 'bar', 'data': [2]}]})
        attach()

    page_context = await capture(user)
    assert element_by_label(page_context, 'Pie').series[0].x == ['A']
    rows = element_by_label(page_context, 'Rows').series
    assert [(s.name, s.x, s.y) for s in rows] == [('x1', ['Q1', 'Q2'], [1, 3]), ('x2', ['Q1', 'Q2'], [2, 4])]
    assert element_by_label(page_context, 'Objects').series[0].y == [9]
    assert element_by_label(page_context, 'Sideways').series[0].x == ['p', 'q']
    legend = element_by_label(page_context, 'Legend').series
    assert [s.hidden for s in legend] == [False, True]


async def test_plotly_figure_dict_numpy_and_binary_encoding(user: User):
    import numpy as np

    @ui.page('/')
    def page():
        ui.plotly(go.Figure(go.Scatter(name='NumPy', x=np.array([1.5, 2.5]), y=np.array([3, 4])),
                            layout={'title': {'text': 'Numbers'}, 'xaxis': {'title': {'text': 'Time'}}}))
        ui.plotly({'data': [{'type': 'bar', 'name': 'Plain', 'x': ['a'], 'y': [1]},
                            {'type': 'bar', 'name': 'Off', 'x': ['a'], 'y': [2], 'visible': 'legendonly'}],
                   'layout': {'title': 'Dict figure'}})
        # How Plotly encodes numpy arrays when serializing.
        ui.plotly({'data': [{'type': 'scatter', 'name': 'Binary',
                             'y': {'dtype': 'i2', 'bdata': 'AQACAAMA'}}], 'layout': {'title': 'Encoded'}})
        ui.plotly({'data': [{'type': 'pie', 'labels': ['A', 'B'], 'values': [1, 2]}], 'layout': {'title': 'Pie'}})
        attach()

    page_context = await capture(user)
    numbers = element_by_label(page_context, 'Numbers')
    assert numbers.series[0].x == [1.5, 2.5] and numbers.series[0].y == [3, 4]
    assert numbers.state['x_axis'] == 'Time'
    plain = element_by_label(page_context, 'Dict figure').series
    assert plain[0].y == [1] and plain[1].hidden
    assert element_by_label(page_context, 'Encoded').series[0].y == [1, 2, 3]
    assert element_by_label(page_context, 'Pie').series[0].x == ['A', 'B']


async def test_pyplot_is_read_when_matplotlib_is_used(user: User):
    @ui.page('/')
    def page():
        with ui.pyplot() as figure:
            import matplotlib.pyplot as plt

            plt.plot([1, 2], [3, 4], label='Line A')
            plt.title('Matplotlib chart')
        assert figure
        attach()

    chart = element_by_label(await capture(user), 'Matplotlib chart')
    assert chart.series[0].name == 'Line A' and chart.series[0].y == [3, 4]


async def test_widgets_with_no_readable_data_say_so(user: User):
    @ui.page('/')
    def page():
        ui.label('Site map')
        ui.leaflet()
        ui.image('https://example.test/picture.png?token=abc')
        attach()

    page_context = await capture(user)
    site_map = next(element for element in page_context.elements if element.kind == 'map')
    assert not site_map.readable and site_map.label == 'Site map'
    assert 'no readable data' in page_context.rendered
    assert 'token=abc' not in page_context.rendered, 'image URLs can carry credentials'


async def test_sensitive_inputs_are_withheld_by_default(user: User):
    @ui.page('/')
    def page():
        ui.input('Plain', value='ok')
        ui.input('Hidden type', value='v1', password=True)
        ui.input('Revealed one', value='v2', password=True, password_toggle_button=True)
        ui.input('API key', value='v3')
        ui.input('Credit card', value='v4')
        ui.input('Autocomplete', value='v5').props('autocomplete=current-password')
        ui.input('Custom', value='v6')
        attach(exclude_fields=['custom'])

    page_context = await capture(user)
    values = {e.label: e.value for e in page_context.elements if e.has_value}
    assert values['Plain'] == 'ok'
    for label in ('Hidden type', 'Revealed one', 'API key', 'Credit card', 'Autocomplete', 'Custom'):
        assert values[label] == '[withheld]', label
    for secret in ('v1', 'v2', 'v3', 'v4', 'v5', 'v6'):
        assert f'= {secret}' not in page_context.rendered


async def test_exclude_fields_removes_table_columns_everywhere(user: User):
    import re

    @ui.page('/')
    def page():
        ui.table(columns=[{'name': 'n', 'label': 'Name', 'field': 'n'},
                          {'name': 's', 'label': 'Salary', 'field': 's'},
                          {'name': 'p', 'label': 'Password', 'field': 'p'}],
                 rows=[{'n': 'Ana', 's': 5000, 'p': 'pw1'}])
        ui.aggrid({'columnDefs': [{'field': 'n'}, {'field': 'home_salary'}],
                   'rowData': [{'n': 'Ben', 'home_salary': 6000}]})
        attach(exclude_fields=[re.compile('salary', re.I)], serializer=glimpse.json_serializer)

    page_context = await capture(user)
    tables = [element for element in page_context.elements if element.table]
    assert tables[0].table.columns == ['n'] and tables[1].table.columns == ['n']
    assert tables[0].state['withheld_columns'] == 2
    for secret in ('5000', '6000', 'pw1'):
        assert secret not in page_context.rendered, 'also when a custom serializer dumps whole rows'
    assert page_context.rendered.startswith('{'), 'the serializer is swappable'


async def test_describe_and_exclude(user: User):
    @ui.page('/')
    def page():
        glimpse.describe(ui.label('KPI'), id='kpi', description='Net of refunds', value={'target': 5})
        with ui.card() as card:
            ui.label('Plain card text')
        glimpse.describe(card, description='A card about refunds')
        with ui.card() as secret:
            ui.label('Top secret')
        glimpse.exclude(secret)
        attach()

    page_context = await capture(user)
    kpi = page_context.element('kpi')
    assert kpi.description == 'Net of refunds' and kpi.extra == {'target': 5}
    assert 'A card about refunds' in page_context.rendered and 'Plain card text' in page_context.rendered
    assert 'Top secret' not in page_context.rendered
    assert any('withheld' in note for note in page_context.notes)


async def test_custom_extractor_teaches_glimpse_a_new_widget(user: User):
    class Gauge(ui.element):
        def __init__(self, reading: int) -> None:
            super().__init__('div')
            self.reading = reading

    def read_gauge(element, walker):
        return glimpse.ElementSnapshot(id=f'gauge-{element.id}', kind='gauge', label='Gauge', has_value=True,
                                       value=element.reading)

    glimpse.register_extractor(Gauge, read_gauge)

    @ui.page('/')
    def page():
        Gauge(73)
        attach()

    assert element_by_label(await capture(user), 'Gauge').value == 73


async def test_refreshable_content_is_read_live(user: User):
    state = {'count': 1}

    @ui.page('/')
    def page():
        @ui.refreshable
        def counter():
            ui.label(f'Count is {state["count"]}')

        counter()
        glimpse.describe(ui.button('Bump', on_click=lambda: (state.update(count=2), counter.refresh())), id='bump')
        attach()

    await user.open('/')
    panel = panel_of(user)
    assert 'Count is 1' in (await ask(panel, 'What is on this page?')).page.rendered
    user.find('Bump').click()
    assert 'Count is 2' in (await ask(panel, 'What is on this page?')).page.rendered


async def test_snapshot_is_built_when_the_user_asks_not_before(user: User):
    """CAP-4: the snapshot reflects the moment of asking, so changes since then are not missed."""
    calls = []

    @ui.page('/')
    def page():
        label = ui.label('Before')
        ui.button('Change', on_click=lambda: label.set_text('After'))
        attach()
        calls.append(label)

    await user.open('/')
    panel = panel_of(user)
    assert panel.session.turns == []
    user.find('Change').click()
    assert 'After' in (await ask(panel, 'Now?')).page.rendered


async def test_every_nicegui_class_is_dispatched_on_purpose():
    """A NiceGUI upgrade can add a ValueElement subclass that is not an input. This makes that visible."""
    import inspect

    from nicegui.element import Element
    from nicegui.elements.mixins.value_element import ValueElement

    from glimpse.adapters.nicegui.capture import CONTAINER_CLASSES
    from glimpse.adapters.nicegui.extractors import REGISTRY, SKIPPED

    switching = {'TabPanels', 'Stepper', 'Carousel', 'Expansion', 'Dialog', 'Menu', 'Drawer', 'LeftDrawer',
                 'RightDrawer', 'Tabs'}
    real_inputs = {
        'Checkbox', 'CodeMirror', 'ColorInput', 'ColorPicker', 'Date', 'DateInput', 'Editor', 'Input', 'InputChips',
        'Knob', 'Number', 'Pagination', 'Radio', 'Range', 'Rating', 'Select', 'Slider', 'Switch', 'Textarea', 'Time',
        'TimeInput', 'Toggle', 'ChoiceElement', 'Codemirror', 'Chip', 'Popup',
    }
    unknown = set()
    for name in dir(ui):
        cls = getattr(ui, name)
        if inspect.isclass(cls) and issubclass(cls, ValueElement):
            known = cls.__name__ in switching | real_inputs | CONTAINER_CLASSES | SKIPPED | set(REGISTRY)
            if not known:
                unknown.add(cls.__name__)
    assert not unknown, f'decide how to read these ValueElement classes: {unknown}'
    assert issubclass(ui.element, Element)
