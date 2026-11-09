"""ENG-4: Google ADK agents as engines, through a thin adapter.

The real ADK runner runs here. A scripted model stands in for the LLM, so these tests check
what the adapter gives the agent and how it maps ADK events, with no network. One test also
runs ADK's real Gemini model class against a local server that speaks the Gemini wire format.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from nicegui import ui
from nicegui.testing import User

import glimpse
from glimpse import AdkEngine, ChatSession, GlimpseConfig, PageContext
from glimpse.engine import as_engine
from glimpse.engines import resolve_engine
from glimpse.prompt import DEFAULT_SYSTEM_PROMPT

from .helpers import panel_of
from .test_providers import GEMINI_TEXT_STREAM, GEMINI_TOOL_STREAM, provider  # noqa: F401

pytest.importorskip('google.adk')

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types


def text_reply(*chunks: str, prompt_tokens: int = 50, output_tokens: int = 5) -> list[LlmResponse]:
    """What a streaming model sends: partial chunks, then the whole message with usage."""
    partials = [LlmResponse(content=types.Content(role='model', parts=[types.Part(text=chunk)]), partial=True)
                for chunk in chunks]
    final = LlmResponse(content=types.Content(role='model', parts=[types.Part(text=''.join(chunks))]),
                        usage_metadata=types.GenerateContentResponseUsageMetadata(
                            prompt_token_count=prompt_tokens, candidates_token_count=output_tokens))
    return [*partials, final]


def call_reply(name: str, arguments: dict[str, Any]) -> list[LlmResponse]:
    return [LlmResponse(content=types.Content(role='model', parts=[
        types.Part(function_call=types.FunctionCall(id=f'adk-{name}', name=name, args=arguments))]),
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=40, candidates_token_count=3))]


class ScriptedLlm(BaseLlm):
    """Answers each model call with the next script, and keeps every request it got."""

    model: str = 'scripted'
    scripts: list[Any] = []
    requests: list[Any] = []

    async def generate_content_async(self, llm_request, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        script = self.scripts.pop(0)
        if isinstance(script, Exception):
            raise script
        for response in script:
            yield response


def scripted(*scripts) -> ScriptedLlm:
    return ScriptedLlm(scripts=list(scripts), requests=[])


def table_page() -> PageContext:
    return PageContext(title='Sales', elements=[glimpse.ElementSnapshot(
        id='table-1', kind='table', label='Orders',
        table=glimpse.TableData(columns=['id', 'amount'], rows=[{'id': 1, 'amount': 10}, {'id': 2, 'amount': 20}]),
    )])


async def run(engine, question: str = 'What is the total?', session: ChatSession | None = None):
    progress: list[str] = []

    async def capture():
        return table_page()

    session = session or ChatSession(as_engine(engine), GlimpseConfig(), capture,
                                     lambda turn: progress.append(turn.progress))
    await asyncio.wait_for(session.ask(question), 20)
    return session.turns[-1], progress, session


def system_text(request) -> str:
    instruction = request.config.system_instruction
    return instruction if isinstance(instruction, str) else ''.join(part.text or '' for part in instruction.parts)


def declared_tools(request) -> set[str]:
    return {declaration.name for tool in request.config.tools or () for declaration in tool.function_declarations or ()}


def last_user_text(request) -> str:
    return ''.join(part.text or '' for part in request.contents[-1].parts)


def stock_level(item: str) -> dict:
    """The developer's own tool: how many of an item are in stock."""
    return {'item': item, 'count': 3}


async def test_your_agent_gets_the_page_its_tools_and_the_rules():
    model = scripted(text_reply('The total ', 'is 30 [ref:table-1].'))
    agent = LlmAgent(name='analyst', model=model, instruction='You are a terse analyst.', tools=[stock_level])
    turn, _, _ = await run(AdkEngine(agent))
    assert turn.status == 'done', turn.error
    assert turn.text == 'The total is 30 [ref:table-1].', 'partial chunks stream, and the final copy is not repeated'
    assert turn.usage.input_tokens == 50 and turn.usage.output_tokens == 5

    request = model.requests[0]
    system = system_text(request)
    assert system.startswith(DEFAULT_SYSTEM_PROMPT) and 'You are a terse analyst.' in system
    assert '<page_state>\n' not in system, 'page data stays out of the instruction (SEC-4)'
    assert declared_tools(request) == {'stock_level', 'get_rows', 'aggregate_rows', 'get_series', 'get_element'}
    assert '<page_state>' in last_user_text(request) and 'What is the total?' in last_user_text(request)
    assert len(agent.tools) == 1 and agent.instruction == 'You are a terse analyst.', 'your agent is not changed'


async def test_page_tools_run_inside_adk_and_are_recorded():
    model = scripted(call_reply('aggregate_rows', {'element_id': 'table-1', 'column': 'amount', 'operation': 'sum'}),
                     text_reply('The total is 30 [ref:table-1].'))
    turn, progress, _ = await run(AdkEngine(LlmAgent(name='analyst', model=model)))
    assert turn.status == 'done', turn.error
    assert [(call['name'], call['element_id']) for call in turn.tool_calls] == [('aggregate_rows', 'table-1')]
    assert any('aggregate_rows' in step for step in progress)
    response = model.requests[1].contents[-1].parts[0].function_response
    assert response.name == 'aggregate_rows'
    assert response.response['result'].startswith('<tool_result>') and '"result": 30' in response.response['result']
    assert turn.usage.input_tokens == 90


async def test_bad_tool_input_goes_back_to_the_agent_as_an_error():
    model = scripted(call_reply('get_rows', {'element_id': 'nope'}), text_reply('Sorry.'))
    turn, _, _ = await run(AdkEngine(LlmAgent(name='analyst', model=model)))
    response = model.requests[1].contents[-1].parts[0].function_response
    assert 'not on this page' in response.response['error']
    assert turn.status == 'done' and turn.tool_calls[0]['error'] == 'yes'


async def test_history_goes_into_the_adk_session_as_text():
    model = scripted(text_reply('One.'), text_reply('Two.'))
    engine = AdkEngine(LlmAgent(name='analyst', model=model))
    _, _, session = await run(engine, 'First?')
    await run(engine, 'Second?', session)
    contents = model.requests[1].contents
    assert [content.role for content in contents] == ['user', 'model', 'user']
    assert contents[0].parts[0].text == 'First?', 'the old page state is not sent again'
    assert contents[1].parts[0].text == 'One.'
    assert '<page_state>' in contents[2].parts[0].text


async def test_a_pipeline_shows_only_the_agents_you_name():
    researcher_model = scripted(text_reply('Notes: total 30.'))
    writer_model = scripted(text_reply('The total is 30 [ref:table-1].'))
    pipeline = SequentialAgent(name='pipeline', sub_agents=[
        LlmAgent(name='researcher', model=researcher_model, instruction='Collect the facts.'),
        LlmAgent(name='writer', model=writer_model, instruction='Write the answer.'),
    ])
    turn, progress, _ = await run(AdkEngine(pipeline, answer_from=['writer']))
    assert turn.status == 'done', turn.error
    assert turn.text == 'The total is 30 [ref:table-1].'
    assert 'researcher is working' in progress
    for model in (researcher_model, writer_model):
        assert 'get_rows' in declared_tools(model.requests[0]), 'every agent in the tree can read the page'
        assert system_text(model.requests[0]).startswith(DEFAULT_SYSTEM_PROMPT)


async def test_rules_can_be_left_to_your_instruction():
    model = scripted(text_reply('Hi.'))
    await run(AdkEngine(LlmAgent(name='analyst', model=model, instruction='Only mine.'), glimpse_rules=False))
    assert system_text(model.requests[0]) .startswith('Only mine.')


@pytest.mark.allow_error_logs
async def test_model_errors_under_adk_become_safe_messages():
    from google.genai import errors

    failure = errors.ClientError(429, {'error': {'code': 429, 'message': 'internal detail secret', 'status': 'X'}})
    turn, _, _ = await run(AdkEngine(LlmAgent(name='analyst', model=scripted(failure))))
    assert turn.status == 'error' and 'rate limiting' in turn.error and 'secret' not in turn.error


async def test_attach_accepts_an_adk_agent_directly(user: User):
    agent = LlmAgent(name='analyst', model=scripted(text_reply('Hi.')))

    @ui.page('/')
    def page():
        glimpse.attach(engine=agent)

    await user.open('/')
    engine = panel_of(user).session.engine
    assert isinstance(engine, AdkEngine) and engine.agent is agent


def test_built_agents_and_their_models():
    with pytest.raises(ValueError, match='needs an ADK agent'):
        AdkEngine()
    with pytest.raises(ValueError, match='gemini:, vertex: and anthropic:'):
        AdkEngine(model='openai:gpt-5')
    with pytest.raises(TypeError, match='not an ADK agent'):
        AdkEngine(object())
    engine = resolve_engine('adk', model='vertex:gemini-flash-latest', project='my-project', location='europe-west4')
    assert isinstance(engine, AdkEngine)
    agent = engine._base_agent()
    assert agent.model.model == 'gemini-flash-latest'
    assert agent.model.client_kwargs == {'vertexai': True, 'project': 'my-project', 'location': 'europe-west4'}
    claude = AdkEngine(model='vertex:claude-opus-5-5', project='my-project', location='us-east5')._base_agent().model
    assert type(claude).__name__ == 'Claude' and claude.client.region == 'us-east5'
    assert claude.client.project_id == 'my-project'


async def test_a_built_agent_runs_on_real_gemini_wire_format(provider, monkeypatch):  # noqa: F811
    """ADK's own Gemini class, streaming from a local server, through the adapter."""
    fake, url = provider
    monkeypatch.setenv('GOOGLE_GEMINI_BASE_URL', url)
    fake.responses = [(200, GEMINI_TOOL_STREAM), (200, GEMINI_TEXT_STREAM)]
    turn, _, _ = await run(AdkEngine(model='gemini:gemini-flash-latest', api_key='gemini-key'))
    assert turn.status == 'done', turn.error
    assert turn.text.endswith('The total is 30 [ref:table-1].')
    assert [call['name'] for call in turn.tool_calls] == ['aggregate_rows']
    first, second = fake.requests
    assert fake.headers[0]['x-goog-api-key'] == 'gemini-key'
    assert DEFAULT_SYSTEM_PROMPT[:60] in json.dumps(first['systemInstruction'])
    response = second['contents'][-1]['parts'][0]['functionResponse']
    assert response['name'] == 'aggregate_rows' and '"result": 30' in response['response']['result']


async def test_stop_cancels_the_adk_run():
    class SlowLlm(ScriptedLlm):
        async def generate_content_async(self, llm_request, stream: bool = False):
            yield LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Partial')]), partial=True)
            await asyncio.sleep(30)
            yield LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Never')]))

    async def capture():
        return table_page()

    session = ChatSession(as_engine(AdkEngine(LlmAgent(name='analyst', model=SlowLlm()))), GlimpseConfig(), capture,
                          lambda turn: None)
    task = session.ask('Q')
    while not session.turns[-1].text:  # noqa: ASYNC110
        await asyncio.sleep(0.01)
    session.cancel()
    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)
    assert session.turns[-1].status == 'stopped' and session.turns[-1].text == 'Partial'
