"""Isolation: two users share one server and never share data.

Run:    python examples/10_two_users.py
Open:   http://localhost:8080/?user=ana and http://localhost:8080/?user=ben

NiceGUI runs every user in one Python process, which is where assistants have
leaked data before. Glimpse keeps each snapshot and conversation on the client
connection, so each tab sees only its own page. Ask both tabs for the balance.
"""

from nicegui import ui

import glimpse

ACCOUNTS = {
    'ana': {'name': 'Ana', 'balance': 12450, 'iban': 'PT50 0002 0123'},
    'ben': {'name': 'Ben', 'balance': 310, 'iban': 'DE89 3704 0044'},
}


@ui.page('/')
def account_page(user: str = 'ana') -> None:
    account = ACCOUNTS.get(user, ACCOUNTS['ana'])
    ui.label(f'Account of {account["name"]}').classes('text-h4')
    ui.label(f'Balance: {account["balance"]} EUR')
    ui.label(f'IBAN: {account["iban"]}')
    glimpse.attach(suggestions=['What is the balance?'])


ui.run(title='Glimpse two users')
