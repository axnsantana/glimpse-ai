"""Developer context: add what the screen cannot show.

Run:    python examples/09_developer_context.py

Capture works with no annotations. When you know more than the page shows, add
it as a string with context=, or per element with glimpse.describe():

- description explains an element.
- value adds data a chart does not show, and may be a function read at ask time.
- available can be a function, so an element can come and go while the page runs.

Treat all of this as visible to end users. A determined user can get an assistant
to repeat its context, so never put secrets here.
"""

from nicegui import ui

import glimpse

TARGET_NPS = 45


@ui.page('/')
def survey_page(user: str = 'Ana') -> None:
    ui.label('Customer survey').classes('text-h4')

    chart = ui.echart({
        'title': {'text': 'Net promoter score'},
        'xAxis': {'type': 'category', 'data': ['Q1', 'Q2', 'Q3', 'Q4']},
        'yAxis': {'type': 'value'},
        'series': [{'name': 'NPS', 'type': 'bar', 'data': [31, 38, 42, 47]}],
    })
    glimpse.describe(
        chart,
        id='nps_chart',
        description='NPS from the quarterly survey. Q3 used a new vendor, so Q3 and later are not comparable to Q1 and Q2.',
        value=lambda: {'target': TARGET_NPS},
    )

    show_notes = ui.switch('Share analyst notes with the assistant', value=False)
    notes = ui.label('Analyst notes: the Q4 rise came mostly from one enterprise account.')
    glimpse.describe(notes, id='analyst_notes', available=lambda: show_notes.value)

    glimpse.attach(
        context=lambda: f'Signed-in user: {user}. The company fiscal year starts in January.',
        suggestions=['Is NPS above target?', 'Can I compare Q2 with Q4?', 'What do the analyst notes say?'],
    )


ui.run(title='Glimpse developer context')
