"""Claude, through the official anthropic SDK. Needs the anthropic package, an optional extra."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from ..engine import EngineError, Message
from ..events import EngineEvent, StepStarted, TextMessageContent
from ..tools import Tool
from .direct import RoundResult, ToolCall

log = logging.getLogger('glimpse')

ADAPTIVE_THINKING_PREFIXES = (
    'claude-fable-5', 'claude-mythos-5', 'claude-opus-5', 'claude-sonnet-5', 'claude-haiku-5',
    'claude-opus-4-6', 'claude-opus-4-7', 'claude-opus-4-8', 'claude-sonnet-4-6',
)
SERVER_FALLBACK_MODELS = ('claude-fable-5-1', 'claude-opus-5-5', 'claude-opus-5', 'claude-sonnet-5-5')
FALLBACK_BETA = 'server-side-fallback-2026-07-01'
MAX_JSON_RETRIES = 2


class AnthropicProvider:
    def __init__(self, model: str, *, api_key: str | None, base_url: str | None, max_output_tokens: int,
                 effort: str) -> None:
        try:
            import anthropic
        except ImportError as error:
            raise EngineError('The Anthropic SDK is not installed on the server. '
                              'Run: pip install anthropic') from error
        self.anthropic = anthropic
        self.model = model
        self.first_party = base_url is None
        self.max_output_tokens = max_output_tokens
        self.effort = effort
        arguments: dict[str, Any] = {}
        if api_key:
            arguments['api_key'] = api_key
        if base_url:
            arguments['base_url'] = base_url
        self.client = anthropic.AsyncAnthropic(**arguments)

    def conversation(self, system: str, messages: list[Message], tools: list[Tool]) -> _AnthropicConversation:
        return _AnthropicConversation(self, system, messages, tools)

    async def aclose(self) -> None:
        await self.client.close()


class _AnthropicConversation:
    def __init__(self, provider: AnthropicProvider, system: str, messages: list[Message], tools: list[Tool]) -> None:
        self.provider = provider
        self.system = system
        # Earlier answers go back as text only. Thinking blocks are replayed only inside the
        # tool loop of one question, where the prefix they are bound to does not change. So
        # trimming old history and moving the page state between turns stay legal.
        self.messages: list[dict[str, Any]] = [{'role': m.role, 'content': m.content} for m in messages]
        self.tools = tools
        self._assistant_content: list[Any] = []

    def _parameters(self, use_tools: bool) -> dict[str, Any]:
        provider = self.provider
        parameters: dict[str, Any] = {
            'model': provider.model,
            'max_tokens': provider.max_output_tokens,
            'system': self.system,
            'messages': self.messages,
        }
        if self.tools:
            parameters['tools'] = [self._tool(tool) for tool in self.tools]
            # Once the transcript holds tool calls the tools must stay listed, so the last
            # round switches them off with tool_choice rather than removing them.
            parameters['tool_choice'] = {'type': 'auto' if use_tools else 'none'}
        if provider.model.startswith(ADAPTIVE_THINKING_PREFIXES):
            parameters['thinking'] = {'type': 'adaptive'}
            parameters['output_config'] = {'effort': provider.effort}
        if provider.first_party and provider.model in SERVER_FALLBACK_MODELS:
            parameters['betas'] = [FALLBACK_BETA]
            parameters['fallbacks'] = 'default'
        return parameters

    def _tool(self, tool: Tool) -> dict[str, Any]:
        definition = {'name': tool.name, 'description': tool.description, 'input_schema': tool.parameters}
        # A proxy may reject this field, so only send it to the real API.
        if self.provider.first_party:
            definition['eager_input_streaming'] = True
        return definition

    async def next_round(self, *, use_tools: bool) -> AsyncIterator[EngineEvent | RoundResult]:
        provider = self.provider
        anthropic = provider.anthropic
        parameters = self._parameters(use_tools)
        json_retries = 0
        pause_input = pause_output = 0
        while True:
            try:
                messages_api = provider.client.beta.messages if 'betas' in parameters else provider.client.messages
                async with messages_api.stream(**parameters) as stream:
                    async for event in stream:
                        if event.type == 'text':
                            yield TextMessageContent(event.text)
                        elif event.type == 'content_block_start' and event.content_block.type == 'thinking':
                            yield StepStarted('Thinking')
                    message = await stream.get_final_message()
            except ValueError:
                # JSON the SDK could not parse at all, so there is no tool_use block to answer.
                json_retries += 1
                if json_retries > MAX_JSON_RETRIES:
                    raise EngineError('The model sent an invalid tool call. Please try again.') from None
                continue
            except anthropic.AuthenticationError as error:
                raise EngineError('The model provider rejected the API key configured on the server.') from error
            except anthropic.RateLimitError as error:
                raise EngineError('The model provider is rate limiting this app. Please try again shortly.') from error
            except anthropic.NotFoundError as error:
                log.error('Anthropic rejected model %r: %s', provider.model, error)
                raise EngineError('The model configured on the server was not found.') from error
            except anthropic.APIStatusError as error:
                log.error('Anthropic API error %s: %s', error.status_code, error)
                raise EngineError(f'The model provider returned an error ({error.status_code}).') from error
            except anthropic.APIConnectionError as error:
                log.error('Could not reach Anthropic: %s', error)
                raise EngineError('The server could not reach the model provider.') from error
            except TypeError as error:
                if 'authentication' in str(error).lower() or 'api_key' in str(error).lower():
                    raise EngineError('No API key is configured on the server. Set ANTHROPIC_API_KEY.') from error
                raise

            pause_input += _input_tokens(message.usage)
            pause_output += message.usage.output_tokens or 0
            if message.stop_reason != 'pause_turn':
                break
            self.messages.append({'role': 'assistant', 'content': _echoable(message.content)})
            parameters = self._parameters(use_tools)

        result = RoundResult(stop_reason=message.stop_reason or '', input_tokens=pause_input,
                             output_tokens=pause_output)
        calls = [block for block in message.content if block.type == 'tool_use']
        if message.stop_reason == 'refusal':
            result.notice = 'The model declined to answer this question.'
            yield result
            return
        if message.stop_reason == 'max_tokens':
            # A cut-off tool input can parse as a valid partial object, so it must not run.
            result.notice = 'This answer was cut off because it reached the output limit.'
            yield result
            return
        if calls:
            self._assistant_content = _echoable(message.content)
            result.tool_calls = [ToolCall(block.id, block.name, block.input, json.dumps(block.input, default=str))
                                 for block in calls]
        yield result

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:
        # All results go back in one user message, together with the unchanged assistant turn.
        self.messages.append({'role': 'assistant', 'content': self._assistant_content})
        self.messages.append({'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': call_id, 'content': content, **({'is_error': True} if error else {})}
            for call_id, content, error in results
        ]})


def _echoable(content: list[Any]) -> list[Any]:
    """Drop what the API says not to echo after a mid-output fallback.

    Before the last fallback block only text goes back. Everything after it echoes as is.
    """
    boundary = max((index for index, block in enumerate(content) if block.type == 'fallback'), default=-1)
    return [block for index, block in enumerate(content) if index > boundary or block.type == 'text']


def _input_tokens(usage: Any) -> int:
    """Sum all attempts. With a fallback, top-level usage covers only the attempt that finished."""
    iterations = getattr(usage, 'iterations', None)
    parts = iterations if iterations else [usage]
    total = 0
    for part in parts:
        total += (part.input_tokens or 0) + (getattr(part, 'cache_read_input_tokens', 0) or 0)
        total += getattr(part, 'cache_creation_input_tokens', 0) or 0
    return total
