"""A realistic dashboard: the case Glimpse is built for.

Run:    python examples/02_sales_dashboard.py

It uses every main NiceGUI data element: ui.echart, ui.plotly, ui.aggrid and
ui.table, plus inputs and tabs. Nothing is annotated, and attach() is the only
Glimpse call.

The assistant reads applied state, not just base data. Try this sequence:

1. Ask "What is the highest revenue?"
2. Change the region to Americas and ask again.
3. Open the Orders tab, filter or sort a grid column, and ask "Which order has
   the highest amount?" The grid filter only exists in the browser, and Glimpse
   reads it with a small probe.
4. Drag the zoom slider on the chart, or click a legend entry to hide a series,
   and ask about the trend.
5. Open "What the assistant saw" under an answer to see exactly what was sent.
"""

import random

import plotly.graph_objects as go
from nicegui import ui

import glimpse

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
REGIONS = ['EMEA', 'Americas', 'APAC']
PRODUCTS = ['Atlas', 'Beacon', 'Comet', 'Delta']
CUSTOMERS = ['Acme', 'Globex', 'Initech', 'Umbrella', 'Hooli', 'Stark', 'Wayne', 'Soylent']


def make_orders() -> list[dict]:
    rng = random.Random(7)
    return [
        {
            'order': f'SO-{1000 + i}',
            'month': MONTHS[i % 12],
            'region': REGIONS[i % 3],
            'product': rng.choice(PRODUCTS),
            'customer': rng.choice(CUSTOMERS),
            'amount': rng.randint(50, 900),
            'status': rng.choice(['open', 'shipped', 'shipped', 'returned']),
        }
        for i in range(240)
    ]


ORDERS = make_orders()


def totals(orders: list[dict], key: str, names: list[str]) -> list[int]:
    return [sum(o['amount'] for o in orders if o[key] == name) for name in names]


@ui.page('/')
def dashboard() -> None:
    def selected_orders() -> list[dict]:
        return [o for o in ORDERS if region.value == 'All' or o['region'] == region.value]

    def refresh() -> None:
        orders = selected_orders()
        revenue = totals(orders, 'month', MONTHS)
        trend.options['series'][0]['data'] = revenue
        trend.options['series'][1]['data'] = [round(value * 0.62) for value in revenue]
        trend.update()
        product_chart.update_figure(product_figure(orders))
        grid.options['rowData'] = orders
        grid.update()
        customers.rows = customer_rows(orders)
        customers.update()
        kpi_revenue.text = f'Revenue: {sum(revenue):,} k EUR'
        kpi_orders.text = f'Orders: {len(orders)}'

    def product_figure(orders: list[dict]) -> go.Figure:
        figure = go.Figure(go.Bar(name='Revenue', x=PRODUCTS, y=totals(orders, 'product', PRODUCTS)))
        figure.update_layout(title='Revenue by product', margin={'t': 40, 'b': 30, 'l': 40, 'r': 10})
        return figure

    def customer_rows(orders: list[dict]) -> list[dict]:
        revenue = totals(orders, 'customer', CUSTOMERS)
        return [{'customer': name, 'revenue': value} for name, value in zip(CUSTOMERS, revenue, strict=True)]

    ui.label('Sales dashboard').classes('text-h4')
    with ui.row().classes('items-center gap-6'):
        region = ui.select(['All', *REGIONS], value='All', label='Region', on_change=refresh).classes('w-40')
        kpi_revenue = ui.label().classes('text-h6')
        kpi_orders = ui.label().classes('text-h6')

    with ui.tabs() as tabs:
        overview_tab = ui.tab('Overview')
        orders_tab = ui.tab('Orders')
        customers_tab = ui.tab('Customers')

    with ui.tab_panels(tabs, value=overview_tab).classes('w-full'):
        with ui.tab_panel(overview_tab):
            with ui.row().classes('w-full no-wrap gap-4'):
                trend = ui.echart({
                    'title': {'text': 'Monthly revenue and cost'},
                    'tooltip': {'trigger': 'axis'},
                    'legend': {'top': 28},
                    'grid': {'top': 64},
                    'dataZoom': [{'type': 'slider'}],
                    'xAxis': {'type': 'category', 'data': MONTHS},
                    'yAxis': {'type': 'value', 'name': 'k EUR'},
                    'series': [
                        {'name': 'Revenue', 'type': 'line', 'data': []},
                        {'name': 'Cost', 'type': 'line', 'data': []},
                    ],
                }).classes('w-1/2 h-80')
                product_chart = ui.plotly(product_figure(ORDERS)).classes('w-1/2 h-80')

        with ui.tab_panel(orders_tab):
            ui.label('Orders')
            grid = ui.aggrid({
                'columnDefs': [
                    {'field': 'order', 'headerName': 'Order'},
                    {'field': 'month', 'headerName': 'Month', 'filter': True},
                    {'field': 'region', 'headerName': 'Region', 'filter': True},
                    {'field': 'product', 'headerName': 'Product', 'filter': True},
                    {'field': 'customer', 'headerName': 'Customer', 'filter': True},
                    {'field': 'amount', 'headerName': 'Amount', 'filter': 'agNumberColumnFilter', 'sortable': True},
                    {'field': 'status', 'headerName': 'Status', 'filter': True},
                ],
                'rowData': ORDERS,
                'rowSelection': {'mode': 'multiRow'},
            }).classes('h-96')

        with ui.tab_panel(customers_tab):
            customers = ui.table(
                title='Revenue by customer',
                columns=[
                    {'name': 'customer', 'label': 'Customer', 'field': 'customer', 'sortable': True},
                    {'name': 'revenue', 'label': 'Revenue', 'field': 'revenue', 'sortable': True},
                ],
                rows=[],
                row_key='customer',
                pagination=5,
            )

    refresh()

    glimpse.attach(
        context='All amounts are in thousands of EUR. Returned orders are included in revenue.',
        suggestions=[
            'What is the highest revenue?',
            'What are the current filters?',
            'Which month has the lowest cost?',
        ],
    )


ui.run(title='Glimpse sales dashboard')
