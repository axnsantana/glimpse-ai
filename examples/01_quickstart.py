"""Quickstart: one line gives your page an assistant that can see it.

Run:    python examples/01_quickstart.py
Then:   click "Ask" in the bottom-right corner.

Change the region, then ask again. The answer follows the screen, even though
no code passes the region or the numbers to the assistant.

Without an API key Glimpse runs in offline demo mode, which answers from simple
rules over the page. Set ANTHROPIC_API_KEY to use a real model (see example 07).
"""

from nicegui import ui

import glimpse

REVENUE = {
    'EMEA': [120, 132, 101, 134, 190, 230],
    'Americas': [220, 182, 191, 234, 290, 330],
    'APAC': [150, 232, 201, 154, 190, 130],
}
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun']


@ui.page('/')
def dashboard() -> None:
    ui.label('Monthly revenue').classes('text-h5')

    def show_region(event) -> None:
        chart.options['series'][0]['data'] = REVENUE[event.value]
        chart.options['series'][0]['name'] = event.value
        chart.update()

    ui.select(list(REVENUE), value='EMEA', label='Region', on_change=show_region)
    chart = ui.echart({
        'title': {'text': 'Revenue (k EUR)'},
        'xAxis': {'type': 'category', 'data': MONTHS},
        'yAxis': {'type': 'value'},
        'series': [{'name': 'EMEA', 'type': 'line', 'data': REVENUE['EMEA']}],
    })

    glimpse.attach(suggestions=['What is on this page?', 'Which month has the highest revenue?'])


ui.run(title='Glimpse quickstart')
