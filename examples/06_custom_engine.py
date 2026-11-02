"""Custom engines: bring your own agent in a few lines.

Run:    python examples/06_custom_engine.py

Glimpse captures, budgets and sanitizes for every engine. An engine only turns
messages and a page snapshot into a stream. This example shows three forms:

/           A plain async generator of str, the shortest engine.
/protocol   A class implementing the Engine protocol, emitting rich events.
/adapter    A thin adapter around an agent framework. FakeAgent stands in for
            your framework, for example Google ADK or LangGraph.
"""

import asyncio
from collections.abc import AsyncIterator

from nicegui import ui

import glimpse
from glimpse.events import StepFinished, StepStarted, TextMessageContent


# Form 1: an async generator of str.
async def echo_engine(messages: list[glimpse.Message], page: glimpse.PageContext) -> AsyncIterator[str]:
    yield f'You asked: "{messages[-1].content}"\n\n'
    yield f'I can see {len(page.elements)} elements on "{page.title}":\n\n'
    for item in page.manifest():
        yield f'- {item["kind"]}: {item["label"] or "(unlabelled)"} [ref:{item["id"]}]\n'


# Form 2: the Engine protocol, with events for progress and text.
class ChecklistEngine:
    banner = 'ChecklistEngine: a demo of the Engine protocol. No model is called.'

    async def respond(self, messages: list[glimpse.Message], page: glimpse.PageContext) -> AsyncIterator:
        yield StepStarted('Looking for tables')
        await asyncio.sleep(0.4)
        tables = [element for element in page.elements if element.table]
        yield StepFinished('Looking for tables')
        yield TextMessageContent(f'I found {len(tables)} table(s). ')
        for table in tables:
            yield TextMessageContent(f'"{table.label}" has {len(table.table.rows)} rows [ref:{table.id}]. ')


# Form 3: an adapter around an existing agent. This is all the code a framework needs.
class FakeAgent:
    """Stands in for an agent framework with its own streaming API."""

    def __init__(self, instructions: str) -> None:
        self.instructions = instructions

    async def run_stream(self, prompt: str) -> AsyncIterator[dict]:
        for word in f'The agent received {len(prompt)} characters of page state and question.'.split():
            await asyncio.sleep(0.03)
            yield {'kind': 'token', 'text': word + ' '}


class FakeAgentEngine:
    banner = 'FakeAgentEngine: a demo adapter. No model is called.'

    def __init__(self, agent: FakeAgent) -> None:
        self.agent = agent

    async def respond(self, messages: list[glimpse.Message], page: glimpse.PageContext) -> AsyncIterator[str]:
        prompt = page.to_prompt() + '\n\n' + messages[-1].content
        async for event in self.agent.run_stream(prompt):
            if event['kind'] == 'token':
                yield event['text']


def content() -> None:
    ui.label('Inventory').classes('text-h4')
    ui.table(
        title='Stock',
        columns=[
            {'name': 'item', 'label': 'Item', 'field': 'item'},
            {'name': 'count', 'label': 'Count', 'field': 'count'},
        ],
        rows=[{'item': 'Bolts', 'count': 120}, {'item': 'Nuts', 'count': 75}],
    )


@ui.page('/')
def generator_page() -> None:
    content()
    glimpse.attach(engine=echo_engine, suggestions=['What can you see?'])


@ui.page('/protocol')
def protocol_page() -> None:
    content()
    glimpse.attach(engine=ChecklistEngine(), suggestions=['How many tables are there?'])


@ui.page('/adapter')
def adapter_page() -> None:
    content()
    glimpse.attach(engine=FakeAgentEngine(FakeAgent('Answer about the page.')), suggestions=['Summarize the page'])


ui.run(title='Glimpse custom engines')
