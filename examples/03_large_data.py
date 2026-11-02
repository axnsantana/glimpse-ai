"""Large data: the page holds 200,000 points, and each request stays small.

Run:    python examples/03_large_data.py

Sending the raw data would cost millions of tokens. Glimpse sends statistics
computed in Python, plus a visible truncation notice such as "Showing 25 of
20,000 rows", and gives the model read-only tools to fetch more on demand.

budget=6000 is deliberately tight here. Open "What the assistant saw" under an
answer and compare the token count with the size of the page.
"""

import math
import random

from nicegui import ui

import glimpse

POINTS = 200_000
ROWS = 20_000


def make_signal() -> list[float]:
    rng = random.Random(3)
    return [round(50 + 0.0002 * i + 10 * math.sin(i / 4000) + rng.gauss(0, 1), 3) for i in range(POINTS)]


def make_events() -> list[dict]:
    rng = random.Random(5)
    return [
        {
            'id': i,
            'sensor': rng.choice(['north', 'south', 'east', 'west']),
            'severity': rng.choice(['info', 'info', 'info', 'warning', 'critical']),
            'reading': round(rng.gauss(50, 12), 2),
        }
        for i in range(ROWS)
    ]


SIGNAL = make_signal()
EVENTS = make_events()


@ui.page('/')
def monitor() -> None:
    ui.label('Sensor monitor').classes('text-h4')
    ui.echart({
        'title': {'text': f'Pressure signal ({POINTS:,} points)'},
        'xAxis': {'type': 'category', 'show': False},
        'yAxis': {'type': 'value', 'scale': True},
        'dataZoom': [{'type': 'inside'}],
        'series': [{'name': 'Pressure', 'type': 'line', 'showSymbol': False, 'sampling': 'lttb', 'data': SIGNAL}],
    }).classes('w-full h-64')
    ui.aggrid({
        'columnDefs': [{'field': name, 'filter': True, 'sortable': True} for name in EVENTS[0]],
        'rowData': EVENTS,
    }).classes('h-96')

    glimpse.attach(
        budget=6000,
        suggestions=['What is the trend of the pressure signal?', 'What is the highest reading?'],
    )


ui.run(title='Glimpse large data')
