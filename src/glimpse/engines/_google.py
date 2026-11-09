"""Gemini, through the google-genai SDK, on the Gemini API or on Vertex AI.

Needs the google-genai package, an optional extra that requires Python 3.11 or later. With an
API key it calls the Gemini API. With a Google Cloud project and location it calls Vertex AI,
using Application Default Credentials.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from ..engine import EngineError, Message
from ..events import EngineEvent, StepStarted, TextMessageContent
from ..tools import Tool
from .direct import GoogleCloud, RoundResult, ToolCall, google_auth_error

log = logging.getLogger('glimpse')

FILTERED_REASONS = ('SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST', 'SPII', 'RECITATION', 'IMAGE_SAFETY')


def api_error_message(code: int | None) -> str:
    """The same safe messages the other providers give, by HTTP status."""
    if code in (401, 403):
        return 'The model provider rejected the credentials configured on the server.'
    if code == 429:
        return 'The model provider is rate limiting this app. Please try again shortly.'
    if code == 404:
        return 'The model configured on the server was not found.'
    return f'The model provider returned an error ({code}).'


class GeminiProvider:
    def __init__(self, model: str, *, api_key: str | None, base_url: str | None, max_output_tokens: int,
                 effort: str, vertex: GoogleCloud | None = None) -> None:
        try:
            from google import genai
            from google.genai import types
        except ImportError as error:
            raise EngineError('The Google Gen AI SDK is not installed on the server. '
                              'Run: pip install google-genai (Python 3.11 or later)') from error
        self.types = types
        self.model = model
        self.platform = 'vertex' if vertex else 'gemini'
        self.max_output_tokens = max_output_tokens
        self.effort = effort
        arguments: dict[str, Any] = {}
        if base_url:
            arguments['http_options'] = types.HttpOptions(base_url=base_url)
        if vertex is not None:
            arguments.update(vertexai=True, project=vertex.project, location=vertex.location)
        elif api_key:
            arguments['api_key'] = api_key
        try:
            self.client = genai.Client(**arguments)
        except ValueError as error:
            raise EngineError('No API key is configured on the server. Set GEMINI_API_KEY.') from error
        except Exception as error:
            if (safe := google_auth_error(error)) is not None:
                raise safe from error
            raise

    def conversation(self, system: str, messages: list[Message], tools: list[Tool]) -> _GeminiConversation:
        return _GeminiConversation(self, system, messages, tools)

    async def aclose(self) -> None:
        await self.client.aio.aclose()


class _GeminiConversation:
    def __init__(self, provider: GeminiProvider, system: str, messages: list[Message], tools: list[Tool]) -> None:
        types = provider.types
        self.provider = provider
        self.system = system
        # Earlier answers go back as text only, as with the other providers.
        self.contents: list[Any] = [
            types.Content(role='model' if m.role == 'assistant' else 'user', parts=[types.Part(text=m.content)])
            for m in messages
        ]
        self.tools = [types.Tool(function_declarations=[
            types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.parameters)
            for t in tools
        ])] if tools else []
        self._calls: dict[str, tuple[str, str | None]] = {}
        """Call ID to the tool name, and the ID Gemini gave, if it gave one."""

    def _config(self, use_tools: bool) -> Any:
        types = self.provider.types
        config: dict[str, Any] = {'system_instruction': self.system, 'max_output_tokens': self.provider.max_output_tokens}
        if self.tools:
            # As with Claude, the tools stay listed once used, and the last round turns them off.
            config['tools'] = self.tools
            config['tool_config'] = types.ToolConfig(function_calling_config=types.FunctionCallingConfig(
                mode='AUTO' if use_tools else 'NONE'))
            config['automatic_function_calling'] = types.AutomaticFunctionCallingConfig(disable=True)
        return types.GenerateContentConfig(**config)

    async def next_round(self, *, use_tools: bool) -> AsyncIterator[EngineEvent | RoundResult]:
        from google.genai import errors

        provider = self.provider
        types = provider.types
        result = RoundResult()
        parts: list[Any] = []
        calls: list[Any] = []
        finish = ''
        blocked = ''
        thinking_shown = False
        try:
            stream = await provider.client.aio.models.generate_content_stream(
                model=provider.model, contents=self.contents, config=self._config(use_tools))
            async for chunk in stream:
                if chunk.usage_metadata:
                    usage = chunk.usage_metadata
                    result.input_tokens = usage.prompt_token_count or 0
                    result.output_tokens = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
                if chunk.prompt_feedback and chunk.prompt_feedback.block_reason:
                    blocked = str(chunk.prompt_feedback.block_reason)
                if not chunk.candidates:
                    continue
                candidate = chunk.candidates[0]
                if candidate.finish_reason:
                    finish = getattr(candidate.finish_reason, 'value', str(candidate.finish_reason))
                for part in (candidate.content.parts if candidate.content and candidate.content.parts else ()):
                    # Parts go back exactly as received, because Gemini needs their thought signatures.
                    parts.append(part)
                    if part.thought:
                        if not thinking_shown:
                            thinking_shown = True
                            yield StepStarted('Thinking')
                    elif part.text:
                        yield TextMessageContent(part.text)
                    if part.function_call:
                        calls.append(part.function_call)
        except errors.APIError as error:
            log.error('%s API error %s for model %r: %s', provider.platform, error.code, provider.model, error)
            raise EngineError(api_error_message(error.code)) from error
        except Exception as error:
            if (safe := google_auth_error(error)) is not None:
                raise safe from error
            if type(error).__module__.startswith(('httpx', 'aiohttp')):
                log.error('Could not reach %s: %s', provider.platform, error)
                raise EngineError('The server could not reach the model provider.') from error
            raise

        result.stop_reason = finish
        if blocked:
            result.notice = 'The model declined to answer this question.'
            yield result
            return
        if finish == 'MAX_TOKENS':
            # A cut-off call must not run, as with the other providers.
            result.notice = 'This answer was cut off because it reached the output limit.'
            yield result
            return
        if finish in FILTERED_REASONS:
            result.notice = 'The model provider filtered this answer.'
        if finish == 'MALFORMED_FUNCTION_CALL':
            result.notice = 'The model sent an invalid tool call.'
        if calls and finish != 'MALFORMED_FUNCTION_CALL':
            self.contents.append(types.Content(role='model', parts=parts))
            for index, call in enumerate(calls):
                call_id = call.id or f'call_{len(self.contents)}_{index}'
                self._calls[call_id] = (call.name or '', call.id)
                arguments = dict(call.args) if call.args is not None else {}
                result.tool_calls.append(ToolCall(call_id, call.name or '', arguments,
                                                  json.dumps(arguments, default=str)))
        yield result

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:
        types = self.provider.types
        # All results go back in one user turn, in the order of the calls.
        self.contents.append(types.Content(role='user', parts=[
            types.Part(function_response=types.FunctionResponse(
                id=self._calls.get(call_id, ('', None))[1],
                name=self._calls.get(call_id, ('', None))[0],
                response={'error' if error else 'result': content},
            ))
            for call_id, content, error in results
        ]))
