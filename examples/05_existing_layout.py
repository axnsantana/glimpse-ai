"""Existing layouts: Glimpse shares the page with your drawers and your CSS.

Run:    python examples/05_existing_layout.py

This page already has a header, a footer and both drawers, and its global CSS
is deliberately hostile: every element is forced to one font and colour. The
panel sits in a Shadow DOM, so that CSS cannot reach it, and none of the panel's
CSS can reach your page. Opening the panel makes room for it instead of covering
your right drawer. Pass push=False to overlay the page instead.
"""

from nicegui import ui

import glimpse


@ui.page('/')
def page() -> None:
    ui.add_css('* { font-family: "Comic Sans MS", cursive !important; color: darkred !important; }')

    with ui.header().classes('items-center bg-amber-200'):
        ui.label('Host application header')
    with ui.left_drawer(value=True).classes('bg-amber-100'):
        ui.label('Left navigation')
        ui.link('Dashboard', '/')
    with ui.right_drawer(value=True).classes('bg-amber-100'):
        ui.label('Right drawer owned by the host')
        ui.checkbox('Show archived', value=True)
    with ui.footer().classes('bg-amber-200'):
        ui.label('Host application footer')

    ui.label('Team capacity').classes('text-h5')
    ui.echart({
        'xAxis': {'type': 'category', 'data': ['Ana', 'Ben', 'Chi']},
        'yAxis': {'type': 'value'},
        'series': [{'name': 'Hours', 'type': 'bar', 'data': [32, 28, 40]}],
    }).classes('w-full h-64')

    glimpse.attach(suggestions=['Who has the most hours?', 'What does the right drawer contain?'])


ui.run(title='Glimpse in an existing layout')
