"""The real anthropic and openai SDKs, against a local server that speaks their wire formats.

No model is called. This checks the requests Glimpse builds and how it reads streams,
including the shapes that are easy to get wrong: thinking blocks, fallbacks, refusals and
tool calls. Run the live eval in tests/test_fidelity.py to test against a real provider.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from glimpse import ChatSession, DirectEngine, ElementSnapshot, GlimpseConfig, PageContext, TableData

pytest.importorskip('anthropic')
pytest.importorskip('openai')


class FakeProvider:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.paths: list[str] = []
        self.responses: list[tuple[int, list[str] | dict]] = []


@pytest.fixture
def provider() -> Iterator[tuple[FakeProvider, str]]:
    fake = FakeProvider()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers['content-length'])))
            fake.requests.append(body)
            fake.paths.append(self.path)
            fake.headers.append({key.lower(): value for key, value in self.headers.items()})
            status, payload = fake.responses.pop(0)
            if isinstance(payload, dict):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('content-type', 'application/json')
                self.send_header('content-length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            data = ''.join(payload).encode()
            self.send_response(status)
            self.send_header('content-type', 'text/event-stream')
            self.send_header('content-length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args) -> None:
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield fake, f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()
    server.server_close()


def sse(event: str, data: dict) -> str:
    return f'event: {event}\ndata: {json.dumps({"type": event, **data})}\n\n'


def anthropic_stream(blocks: list[dict], stop_reason: str = 'end_turn', model: str = 'claude-opus-5-5') -> list[str]:
    """A message stream as the Messages API sends it."""
    events = [sse('message_start', {'message': {
        'id': 'msg_1', 'type': 'message', 'role': 'assistant', 'model': model, 'content': [], 'stop_reason': None,
        'stop_sequence': None, 'usage': {'input_tokens': 50, 'output_tokens': 1},
    }})]
    for index, block in enumerate(blocks):
        if block['type'] == 'text':
            events.append(sse('content_block_start', {'index': index, 'content_block': {'type': 'text', 'text': ''}}))
            events.append(sse('content_block_delta', {'index': index, 'delta': {'type': 'text_delta', 'text': block['text']}}))
        elif block['type'] == 'thinking':
            events.append(sse('content_block_start', {'index': index, 'content_block': {
                'type': 'thinking', 'thinking': '', 'signature': ''}}))
            events.append(sse('content_block_delta', {'index': index, 'delta': {
                'type': 'signature_delta', 'signature': block['signature']}}))
        elif block['type'] == 'tool_use':
            events.append(sse('content_block_start', {'index': index, 'content_block': {
                'type': 'tool_use', 'id': block['id'], 'name': block['name'], 'input': {}}}))
            events.append(sse('content_block_delta', {'index': index, 'delta': {
                'type': 'input_json_delta', 'partial_json': json.dumps(block['input'])}}))
        events.append(sse('content_block_stop', {'index': index}))
    events.append(sse('message_delta', {'delta': {'stop_reason': stop_reason, 'stop_sequence': None},
                                        'usage': {'output_tokens': 7}}))
    events.append(sse('message_stop', {}))
    return events


def page() -> PageContext:
    return PageContext(title='Sales', elements=[ElementSnapshot(
        id='table-1', kind='table', label='Orders',
        table=TableData(columns=['id', 'amount'], rows=[{'id': 1, 'amount': 10}, {'id': 2, 'amount': 20}]),
    )])


async def answer(engine: DirectEngine, question: str = 'What is the total?', page_context: PageContext | None = None):
    async def capture() -> PageContext:
        return page_context or page()

    session = ChatSession(engine, GlimpseConfig(), capture, lambda turn: None)
    await asyncio.wait_for(session.ask(question), 20)
    return session.turns[-1], session


TOOL_CALL = {'type': 'tool_use', 'id': 'toolu_1', 'name': 'aggregate_rows',
             'input': {'element_id': 'table-1', 'column': 'amount', 'operation': 'sum'}}


@pytest.fixture
def anthropic_env(provider, monkeypatch) -> FakeProvider:
    fake, url = provider
    monkeypatch.setenv('ANTHROPIC_BASE_URL', url)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    return fake


async def test_anthropic_full_tool_round_trip(anthropic_env):
    fake = anthropic_env
    fake.responses = [
        (200, anthropic_stream([{'type': 'thinking', 'signature': 'sig1'}, {'type': 'text', 'text': 'Checking. '}, TOOL_CALL],
                               'tool_use')),
        (200, anthropic_stream([{'type': 'text', 'text': 'The total is 30 [ref:table-1].'}])),
    ]
    turn, _session = await answer(DirectEngine('anthropic:claude-opus-5-5'))
    assert turn.status == 'done', turn.error
    assert turn.text == 'Checking. The total is 30 [ref:table-1].'
    assert turn.usage.input_tokens == 100 and turn.usage.output_tokens == 14

    first, second = fake.requests
    headers = fake.headers[0]
    assert headers['authorization'] == 'Bearer test-key' and 'anthropic-version' in headers
    assert first['model'] == 'claude-opus-5-5' and first['stream'] is True
    assert first['thinking'] == {'type': 'adaptive'}
    assert first['output_config'] == {'effort': 'medium'}
    assert 'temperature' not in first
    assert first['fallbacks'] == 'default'
    assert 'server-side-fallback-2026-07-01' in headers['anthropic-beta']
    assert first['tool_choice'] == {'type': 'auto'}
    assert all(tool['eager_input_streaming'] for tool in first['tools'])
    assert {tool['name'] for tool in first['tools']} == {'get_rows', 'aggregate_rows', 'get_series', 'get_element'}
    # Untrusted page data stays out of the system prompt.
    assert '<page_state>\n' not in first['system']
    assert '<page_state>' in first['messages'][-1]['content'] and 'What is the total?' in first['messages'][-1]['content']

    # The assistant turn goes back whole, thinking included, then one user message with all results.
    assistant, results = second['messages'][-2:]
    assert [block['type'] for block in assistant['content']] == ['thinking', 'text', 'tool_use']
    assert assistant['content'][0]['signature'] == 'sig1'
    assert results['role'] == 'user'
    assert results['content'][0]['type'] == 'tool_result' and results['content'][0]['tool_use_id'] == 'toolu_1'
    assert '"result": 30' in results['content'][0]['content']
    assert second['messages'][:-2] == first['messages'], 'the prefix must not change within a turn'


async def test_anthropic_later_questions_send_text_only_history(anthropic_env):
    fake = anthropic_env
    fake.responses = [(200, anthropic_stream([{'type': 'thinking', 'signature': 's'}, {'type': 'text', 'text': 'One.'}])),
                      (200, anthropic_stream([{'type': 'text', 'text': 'Two.'}]))]
    _, session = await answer(DirectEngine('anthropic:claude-opus-5-5'), 'First?')
    await asyncio.wait_for(session.ask('Second?'), 20)
    messages = fake.requests[1]['messages']
    assert messages[0] == {'role': 'user', 'content': 'First?'}, 'the old page state is not sent again'
    assert messages[1] == {'role': 'assistant', 'content': 'One.'}, 'no thinking blocks from earlier turns'
    assert '<page_state>' in messages[2]['content'] and 'Second?' in messages[2]['content']


async def test_anthropic_refusal_is_reported_and_tools_do_not_run(anthropic_env):
    fake = anthropic_env
    fake.responses = [(200, anthropic_stream([TOOL_CALL], 'refusal'))]
    turn, _ = await answer(DirectEngine('anthropic:claude-opus-5-5'))
    assert any('declined' in notice for notice in turn.notices)
    assert len(fake.requests) == 1 and turn.tool_calls == []


async def test_anthropic_cut_off_tool_input_never_runs(anthropic_env):
    fake = anthropic_env
    fake.responses = [(200, anthropic_stream([TOOL_CALL], 'max_tokens'))]
    turn, _ = await answer(DirectEngine('anthropic:claude-opus-5-5'))
    assert any('cut off' in notice for notice in turn.notices)
    assert len(fake.requests) == 1 and turn.tool_calls == []


async def test_anthropic_older_model_gets_no_new_parameters(anthropic_env):
    fake = anthropic_env
    fake.responses = [(200, anthropic_stream([{'type': 'text', 'text': 'Hi'}], model='claude-haiku-4-5'))]
    await answer(DirectEngine('anthropic:claude-haiku-4-5'))
    request = fake.requests[0]
    assert 'thinking' not in request and 'output_config' not in request and 'fallbacks' not in request


async def test_anthropic_proxy_gets_no_first_party_only_fields(provider, monkeypatch):
    fake, url = provider
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake.responses = [(200, anthropic_stream([{'type': 'text', 'text': 'Hi'}]))]
    await answer(DirectEngine('anthropic:claude-opus-5-5', base_url=url))
    request = fake.requests[0]
    assert 'fallbacks' not in request
    assert not any('eager_input_streaming' in tool for tool in request['tools'])


@pytest.mark.parametrize('status, expected', [
    (401, 'rejected the API key'),
    (429, 'rate limiting'),
    (404, 'not found'),
    (400, 'returned an error (400)'),
])
@pytest.mark.allow_error_logs
async def test_anthropic_errors_become_safe_messages(anthropic_env, status, expected):
    fake = anthropic_env
    error = {'type': 'error', 'error': {'type': 'x', 'message': 'internal detail secret'}}
    fake.responses = [(status, error)] * 3
    turn, _ = await answer(DirectEngine('anthropic:claude-opus-5-5'))
    assert turn.status == 'error' and expected in turn.error
    assert 'secret' not in turn.error


def openai_chunk(content=None, tool_calls=None, finish=None, usage=None) -> str:
    delta = {'role': 'assistant'}
    if content is not None:
        delta['content'] = content
    if tool_calls is not None:
        delta['tool_calls'] = tool_calls
    choices = [] if usage else [{'index': 0, 'delta': delta, 'finish_reason': finish}]
    return 'data: ' + json.dumps({'id': 'c', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'm',
                                  'choices': choices, 'usage': usage}) + '\n\n'


OPENAI_TOOL_STREAM = [
    openai_chunk(tool_calls=[{'index': 0, 'id': 'call_1', 'type': 'function', 'function': {
        'name': 'aggregate_rows', 'arguments': '{"element_id": "table-1", '}}]),
    openai_chunk(tool_calls=[{'index': 0, 'function': {'arguments': '"column": "amount", "operation": "sum"}'}}]),
    openai_chunk(finish='tool_calls'),
    openai_chunk(usage={'prompt_tokens': 40, 'completion_tokens': 3, 'total_tokens': 43}),
    'data: [DONE]\n\n',
]
OPENAI_TEXT_STREAM = [
    openai_chunk(content='Total '), openai_chunk(content='is 30.'), openai_chunk(finish='stop'),
    openai_chunk(usage={'prompt_tokens': 50, 'completion_tokens': 4, 'total_tokens': 54}), 'data: [DONE]\n\n',
]


async def test_openai_tool_round_trip_with_the_real_sdk(provider, monkeypatch):
    fake, url = provider
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setenv('OPENAI_BASE_URL', url)
    fake.responses = [(200, OPENAI_TOOL_STREAM), (200, OPENAI_TEXT_STREAM)]
    turn, _ = await answer(DirectEngine('openai:gpt-5'))
    assert turn.status == 'done', turn.error
    assert turn.text == 'Total is 30.'
    assert turn.usage.input_tokens == 90 and turn.usage.output_tokens == 7
    first, second = fake.requests
    assert first['max_completion_tokens'] == 16000 and 'max_tokens' not in first
    assert first['messages'][0]['role'] == 'system'
    assert first['stream'] is True and first['stream_options'] == {'include_usage': True}
    assert first['tools'][0]['type'] == 'function'
    assert second['messages'][-2]['tool_calls'][0]['id'] == 'call_1'
    assert second['messages'][-1]['role'] == 'tool' and '"result": 30' in second['messages'][-1]['content']


async def test_local_model_through_an_openai_compatible_endpoint(provider):
    """ENG-5: a local server works with only a base_url, no key and no special handling."""
    fake, url = provider
    fake.responses = [(200, OPENAI_TEXT_STREAM)]
    turn, _ = await answer(DirectEngine('ollama:llama3.2', base_url=f'{url}/v1'))
    assert turn.status == 'done', turn.error
    assert fake.requests[0]['model'] == 'llama3.2'
    assert fake.requests[0]['max_tokens'] == 16000 and 'max_completion_tokens' not in fake.requests[0]


async def test_openai_invalid_tool_json_goes_back_as_an_error(provider, monkeypatch):
    fake, url = provider
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    bad = [openai_chunk(tool_calls=[{'index': 0, 'id': 'c1', 'type': 'function', 'function': {
        'name': 'get_rows', 'arguments': '{"element_id": '}}]), openai_chunk(finish='tool_calls'), 'data: [DONE]\n\n']
    fake.responses = [(200, bad), (200, OPENAI_TEXT_STREAM)]
    turn, _ = await answer(DirectEngine('openai:gpt-5', base_url=url))
    assert 'INVALID_JSON' in fake.requests[1]['messages'][-1]['content']
    assert turn.status == 'done'


async def test_openai_without_a_key_says_what_to_do():
    turn, _ = await answer(DirectEngine('openai:gpt-5'))
    assert 'OPENAI_API_KEY' in turn.error


async def test_missing_sdk_says_which_extra_to_install(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in ('anthropic', 'openai'):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    turn, _ = await answer(DirectEngine('anthropic:claude-opus-5-5'))
    assert 'pip install anthropic' in turn.error
    turn, _ = await answer(DirectEngine('openai:gpt-5'))
    assert 'pip install openai' in turn.error


# Google Cloud: Claude and Gemini on Vertex AI, and Gemini with an API key.


class FakeGoogleCredentials:
    """Stands in for Application Default Credentials, so no test needs a Google account."""

    token = 'vertex-token'
    expired = False
    valid = True
    quota_project_id = None
    universe_domain = 'googleapis.com'

    def refresh(self, request) -> None:
        pass

    def before_request(self, request, method, url, headers) -> None:
        headers['authorization'] = f'Bearer {self.token}'


@pytest.fixture
def google_credentials(monkeypatch):
    pytest.importorskip('google.auth')
    import google.auth

    monkeypatch.setattr(google.auth, 'default', lambda *args, **kwargs: (FakeGoogleCredentials(), 'adc-project'))


async def test_claude_on_vertex_uses_the_project_region_and_no_api_key(provider, monkeypatch, google_credentials):
    fake, url = provider
    monkeypatch.setenv('ANTHROPIC_VERTEX_BASE_URL', url)
    fake.responses = [
        (200, anthropic_stream([{'type': 'text', 'text': 'Checking. '}, TOOL_CALL], 'tool_use')),
        (200, anthropic_stream([{'type': 'text', 'text': 'The total is 30 [ref:table-1].'}])),
    ]
    turn, _ = await answer(DirectEngine('vertex:claude-opus-5-5', project='my-project', location='us-east5'))
    assert turn.status == 'done', turn.error
    assert turn.text == 'Checking. The total is 30 [ref:table-1].'
    assert fake.paths[0] == '/projects/my-project/locations/us-east5/publishers/anthropic/models/claude-opus-5-5:streamRawPredict'
    assert fake.headers[0]['authorization'] == 'Bearer vertex-token'
    assert 'x-api-key' not in fake.headers[0]
    first = fake.requests[0]
    assert first['thinking'] == {'type': 'adaptive'} and first['output_config'] == {'effort': 'medium'}
    assert all(tool['eager_input_streaming'] for tool in first['tools']), 'Vertex AI supports eager tool streaming'
    assert 'fallbacks' not in first, 'server-side fallback is a first-party API feature only'
    assert 'server-side-fallback' not in fake.headers[0].get('anthropic-beta', '')
    assert fake.requests[1]['messages'][-1]['content'][0]['type'] == 'tool_result'


async def test_vertex_project_and_location_come_from_the_environment(provider, monkeypatch, google_credentials):
    fake, url = provider
    monkeypatch.setenv('ANTHROPIC_VERTEX_BASE_URL', url)
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'env-project')
    fake.responses = [(200, anthropic_stream([{'type': 'text', 'text': 'Hi'}]))]
    turn, _ = await answer(DirectEngine('vertex:claude-sonnet-5-5'))
    assert turn.status == 'done', turn.error
    assert fake.paths[0].startswith('/projects/env-project/locations/global/'), 'the location defaults to global'


async def test_vertex_without_a_project_says_what_to_do():
    turn, _ = await answer(DirectEngine('vertex:claude-opus-5-5'))
    assert turn.status == 'error' and 'GOOGLE_CLOUD_PROJECT' in turn.error


async def test_vertex_without_google_credentials_says_what_to_do(provider, monkeypatch):
    pytest.importorskip('google.auth')
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError

    def no_credentials(*args, **kwargs):
        raise DefaultCredentialsError('Your default credentials were not found. internal detail')

    fake, url = provider
    monkeypatch.setenv('ANTHROPIC_VERTEX_BASE_URL', url)
    monkeypatch.setattr(google.auth, 'default', no_credentials)
    turn, _ = await answer(DirectEngine('vertex:claude-opus-5-5', project='p'))
    assert turn.status == 'error'
    assert 'gcloud auth application-default login' in turn.error and 'internal detail' not in turn.error
    assert fake.requests == []


def gemini_chunk(parts=None, finish=None, usage=None) -> str:
    candidate = {'content': {'role': 'model', 'parts': parts or []}, 'index': 0}
    if finish:
        candidate['finishReason'] = finish
    body = {'candidates': [candidate]}
    if usage:
        body['usageMetadata'] = usage
    return 'data: ' + json.dumps(body) + '\r\n\r\n'


GEMINI_TOOL_STREAM = [
    gemini_chunk([{'text': 'Checking. '}]),
    gemini_chunk([{'functionCall': {'name': 'aggregate_rows', 'args': {
        'element_id': 'table-1', 'column': 'amount', 'operation': 'sum'}}, 'thoughtSignature': 'c2lnbmF0dXJl'}],
        finish='STOP', usage={'promptTokenCount': 60, 'candidatesTokenCount': 4, 'thoughtsTokenCount': 2}),
]
GEMINI_TEXT_STREAM = [
    gemini_chunk([{'text': 'The total is '}]),
    gemini_chunk([{'text': '30 [ref:table-1].'}], finish='STOP',
                 usage={'promptTokenCount': 80, 'candidatesTokenCount': 6}),
]


async def test_gemini_with_an_api_key_round_trip(provider, monkeypatch):
    pytest.importorskip('google.genai')
    fake, url = provider
    monkeypatch.setenv('GOOGLE_GEMINI_BASE_URL', url)
    monkeypatch.setenv('GEMINI_API_KEY', 'gemini-key')
    fake.responses = [(200, GEMINI_TOOL_STREAM), (200, GEMINI_TEXT_STREAM)]
    turn, _ = await answer(DirectEngine('gemini:gemini-flash-latest'))
    assert turn.status == 'done', turn.error
    assert turn.text == 'Checking. The total is 30 [ref:table-1].'
    assert turn.usage.input_tokens == 140 and turn.usage.output_tokens == 12
    assert 'models/gemini-flash-latest:streamGenerateContent' in fake.paths[0]
    assert fake.headers[0]['x-goog-api-key'] == 'gemini-key'

    first, second = fake.requests
    assert '<page_state>\n' not in first['systemInstruction']['parts'][0]['text'], 'no page data in the system prompt'
    assert '<page_state>' in first['contents'][-1]['parts'][0]['text']
    declarations = first['tools'][0]['functionDeclarations']
    assert {item['name'] for item in declarations} == {'get_rows', 'aggregate_rows', 'get_series', 'get_element'}
    assert first['toolConfig']['functionCallingConfig']['mode'] == 'AUTO'
    # The model turn goes back with its thought signature, then the results in one user turn.
    model_turn, results = second['contents'][-2:]
    assert model_turn['role'] == 'model'
    assert any(part.get('thoughtSignature') == 'c2lnbmF0dXJl' for part in model_turn['parts'])
    response = results['parts'][0]['functionResponse']
    assert results['role'] == 'user' and response['name'] == 'aggregate_rows'
    assert '"result": 30' in response['response']['result']
    assert second['contents'][:-2] == first['contents'], 'the prefix must not change within a turn'


async def test_gemini_on_vertex_uses_the_project_and_location(provider, monkeypatch, google_credentials):
    pytest.importorskip('google.genai')
    fake, url = provider
    monkeypatch.setenv('GOOGLE_VERTEX_BASE_URL', url)
    fake.responses = [(200, GEMINI_TEXT_STREAM)]
    turn, _ = await answer(DirectEngine('vertex:gemini-flash-latest', project='my-project', location='europe-west4'))
    assert turn.status == 'done', turn.error
    assert '/projects/my-project/locations/europe-west4/publishers/google/models/gemini-flash-latest' in fake.paths[0]
    assert fake.headers[0]['authorization'] == 'Bearer vertex-token'


async def test_gemini_cut_off_tool_call_never_runs(provider, monkeypatch):
    pytest.importorskip('google.genai')
    fake, url = provider
    monkeypatch.setenv('GOOGLE_GEMINI_BASE_URL', url)
    monkeypatch.setenv('GEMINI_API_KEY', 'k')
    fake.responses = [(200, [gemini_chunk([{'functionCall': {'name': 'get_rows', 'args': {'element_id': 'table-1'}}}],
                                          finish='MAX_TOKENS')])]
    turn, _ = await answer(DirectEngine('gemini:gemini-flash-latest'))
    assert any('cut off' in notice for notice in turn.notices)
    assert len(fake.requests) == 1 and turn.tool_calls == []


@pytest.mark.parametrize('status, expected', [
    (401, 'rejected the credentials'),
    (429, 'rate limiting'),
    (404, 'not found'),
    (400, 'returned an error (400)'),
])
@pytest.mark.allow_error_logs
async def test_gemini_errors_become_safe_messages(provider, monkeypatch, status, expected):
    pytest.importorskip('google.genai')
    fake, url = provider
    monkeypatch.setenv('GOOGLE_GEMINI_BASE_URL', url)
    monkeypatch.setenv('GEMINI_API_KEY', 'k')
    fake.responses = [(status, {'error': {'code': status, 'message': 'internal detail secret', 'status': 'X'}})] * 3
    turn, _ = await answer(DirectEngine('gemini:gemini-flash-latest'))
    assert turn.status == 'error' and expected in turn.error
    assert 'secret' not in turn.error


async def test_gemini_without_a_key_says_what_to_do():
    pytest.importorskip('google.genai')
    turn, _ = await answer(DirectEngine('gemini:gemini-flash-latest'))
    assert 'GEMINI_API_KEY' in turn.error
