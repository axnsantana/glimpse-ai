"""A carousel and a collapsed expansion, each holding a grid, with no annotations."""

from nicegui import ui

import glimpse

REGIONS = ['EMEA', 'Americas', 'APAC']


@ui.page('/')
def page() -> None:
    ui.label('Team page')
    with ui.carousel(navigation=True).classes('w-[600px] h-72'):
        with ui.carousel_slide('Welcome'):
            ui.label('Welcome to the team page')
        with ui.carousel_slide('Team'):
            ui.aggrid({'columnDefs': [{'field': 'team', 'headerName': 'Team'},
                                      {'field': 'headcount', 'headerName': 'Headcount'}],
                       'rowData': [{'team': 'Ops', 'headcount': 4}, {'team': 'Dev', 'headcount': 17},
                                   {'team': 'Sales', 'headcount': 9}]}).classes('h-48')
    with ui.expansion('Order details', value=False):
        ui.aggrid({'columnDefs': [{'field': 'order', 'headerName': 'Order'},
                                  {'field': 'region', 'headerName': 'Region', 'filter': True},
                                  {'field': 'amount', 'headerName': 'Amount'}],
                   'rowData': [{'order': f'SO-{1000 + i}', 'region': REGIONS[i % 3], 'amount': 100 + i}
                               for i in range(30)]}).classes('h-64')
    glimpse.attach()


ui.run()
