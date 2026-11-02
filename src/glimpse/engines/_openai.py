"""OpenAI, and any OpenAI-compatible endpoint such as Ollama, vLLM or LM Studio (ENG-5).

Needs the openai package, an optional extra. A local model needs nothing but base_url.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from ..engine import EngineError, Message
from ..events import EngineEvent, TextMessageContent
from ..tools import Tool
from .direct import RoundResult, ToolCall

log = logging.getLogger('glimpse')


class OpenAIProvider:
    def __init__(self, model: str, *, api_key: str | None, base_url: str | None, max_output_tokens: int) -> None:
        try:
            import openai
        except ImportError as error:
            raise EngineError('The OpenAI SDK is not installed on the server. '
                              'Run: pip install openai') from error
        self.openai = openai
        self.model = model
        self.custom_endpoint = base_url is not None
        self.max_output_tokens = max_output_tokens
        arguments: dict[str, Any] = {}
        if api_key or base_url:
            arguments['api_key'] = api_key or 'not-needed'
        if base_url:
            arguments['base_url'] = base_url
        try:
            self.client = openai.AsyncOpenAI(**arguments)
        except openai.OpenAIError as error:
            raise EngineError('No API key is configured on the server. Set OPENAI_API_KEY.') from error

    def conversation(self, system: str, messages: list[Message], tools: list[Tool]) -> _OpenAIConversation:
        return _OpenAIConversation(self, system, messages, tools)

    async def aclose(self) -> None:
        await self.client.close()


class _OpenAIConversation:
    def __init__(self, provider: OpenAIProvider, system: str, messages: list[Message], tools: list[Tool]) -> None:
        self.provider = provider
        self.messages: list[dict[str, Any]] = [
            {'role': 'system', 'content': system},
            *({'role': m.role, 'content': m.content} for m in messages),
        ]
        self.tools = [{'type': 'function', 'function': {'name': t.name, 'description': t.description,
                                                        'parameters': t.parameters}} for t in tools]

    def _parameters(self, use_tools: bool) -> dict[str, Any]:
        provider = self.provider
        parameters: dict[str, Any] = {
            'model': provider.model,
            'messages': self.messages,
            'stream': True,
            'stream_options': {'include_usage': True},
        }
        # OpenAI's current models want max_completion_tokens. Most compatible servers still use max_tokens.
        parameters['max_tokens' if provider.custom_endpoint else 'max_completion_tokens'] = provider.max_output_tokens
        if self.tools:
            parameters['tools'] = self.tools
            parameters['tool_choice'] = 'auto' if use_tools else 'none'
        return parameters

    async def next_round(self, *, use_tools: bool) -> AsyncIterator[EngineEvent | RoundResult]:
        provider = self.provider
        openai = provider.openai
        result = RoundResult()
        text = ''
        partial: dict[int, dict[str, str]] = {}
        try:
            stream = await provider.client.chat.completions.create(**self._parameters(use_tools))
            async for chunk in stream:
                if chunk.usage:
                    result.input_tokens = chunk.usage.prompt_tokens or 0
                    result.output_tokens = chunk.usage.completion_tokens or 0
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:
                    result.stop_reason = choice.finish_reason
                delta = choice.delta
                if delta.content:
                    text += delta.content
                    yield TextMessageContent(delta.content)
                for call in delta.tool_calls or ():
                    slot = partial.setdefault(call.index, {'id': '', 'name': '', 'arguments': ''})
                    if call.id:
                        slot['id'] = call.id
                    if call.function and call.function.name:
                        slot['name'] += call.function.name
                    if call.function and call.function.arguments:
                        slot['arguments'] += call.function.arguments
        except openai.AuthenticationError as error:
            raise EngineError('The model provider rejected the API key configured on the server.') from error
        except openai.RateLimitError as error:
            raise EngineError('The model provider is rate limiting this app. Please try again shortly.') from error
        except openai.NotFoundError as error:
            log.error('The endpoint rejected model %r: %s', provider.model, error)
            raise EngineError('The model configured on the server was not found.') from error
        except openai.APIStatusError as error:
            log.error('Model API error %s: %s', error.status_code, error)
            raise EngineError(f'The model provider returned an error ({error.status_code}).') from error
        except openai.APIConnectionError as error:
            log.error('Could not reach the model endpoint: %s', error)
            raise EngineError('The server could not reach the model provider.') from error

        if result.stop_reason == 'length':
            result.notice = 'This answer was cut off because it reached the output limit.'
            yield result
            return
        if result.stop_reason == 'content_filter':
            result.notice = 'The model provider filtered this answer.'
        if partial:
            ordered = [partial[index] for index in sorted(partial)]
            self.messages.append({'role': 'assistant', 'content': text or None, 'tool_calls': [
                {'id': slot['id'], 'type': 'function', 'function': {'name': slot['name'], 'arguments': slot['arguments']}}
                for slot in ordered
            ]})
            result.tool_calls = [ToolCall(slot['id'], slot['name'], _parse(slot['arguments']), slot['arguments'])
                                 for slot in ordered]
        yield result

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:
        for call_id, content, _ in results:
            self.messages.append({'role': 'tool', 'tool_call_id': call_id, 'content': content})


def _parse(arguments: str) -> Any:
    try:
        return json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return None
