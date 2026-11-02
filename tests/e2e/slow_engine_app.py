"""A page with a slow engine, for testing streaming and cancellation in a browser."""

import asyncio

from nicegui import ui

import glimpse


async def slow_engine(messages, page):
    try:
        for index in range(200):
            yield f'word{index} '
            await asyncio.sleep(0.05)
    finally:
        cleaned.text = 'engine closed'


@ui.page('/')
def page() -> None:
    global cleaned
    cleaned = ui.label('engine running')
    glimpse.attach(engine=slow_engine, open=True, probe=False)


ui.run()
