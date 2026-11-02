"""Multi-page apps: call attach() once, before the pages.

Run:    python examples/04_multi_page.py

Called at module level, attach() covers every page of the app, including
ui.sub_pages inside a single page, with no per-page code. Each page gets its own
assistant session. skip_paths leaves out pages such as a login form.
"""

from nicegui import ui

import glimpse

glimpse.attach(
    skip_paths=['/login'],
    suggestions=['What is on this page?'],
)


def navigation() -> None:
    with ui.row():
        ui.link('Home', '/')
        ui.link('Reports', '/reports')
        ui.link('Portal', '/portal')
        ui.link('Login', '/login')


@ui.page('/')
def home() -> None:
    navigation()
    ui.label('Welcome back').classes('text-h4')
    ui.label('Open tickets: 12')


@ui.page('/reports')
def reports() -> None:
    navigation()
    ui.label('Reports').classes('text-h4')
    ui.table(
        columns=[
            {'name': 'report', 'label': 'Report', 'field': 'report'},
            {'name': 'pages', 'label': 'Pages', 'field': 'pages'},
        ],
        rows=[{'report': 'Q1 review', 'pages': 14}, {'report': 'Q2 review', 'pages': 21}],
    )


@ui.page('/login')
def login() -> None:
    navigation()
    ui.input('Email')
    ui.input('Password', password=True)
    ui.button('Sign in')


def portal_billing() -> None:
    ui.label('Billing').classes('text-h5')
    ui.label('Current plan: Team, 40 seats')


def portal_people() -> None:
    ui.label('People').classes('text-h5')
    ui.label('Active members: 37')


@ui.page('/portal')
@ui.page('/portal/{_:path}')
def portal() -> None:
    navigation()
    with ui.row():
        ui.link('Billing', '/portal')
        ui.link('People', '/portal/people')
    ui.sub_pages({'/': portal_billing, '/people': portal_people}, root_path='/portal')


ui.run(title='Glimpse multi-page')
