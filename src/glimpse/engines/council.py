"""The council engine: an actor drafts, a critic checks, and a mediator settles (ENG-6).

Each question takes several model calls, so answers cost more and take longer, in exchange for
an answer that was checked against the page before the user sees it:

1. The actor drafts an answer, with the page and its tools, exactly as the direct engine would.
2. The critic reviews the draft against the page, using the same tools, and approves it or lists problems.
3. If it lists problems, the actor revises once per remaining round, and the critic reviews again.
4. If the critic still disagrees after the last round, the mediator writes the final answer.

Only the final answer reaches the user. An approved draft appears in one piece, while the
mediator's answer streams. The panel shows which step is running.

It works with every provider the direct engine supports, including Vertex AI, and needs no
agent framework. Spike S3 has not measured whether the extra calls pay off, so treat it as an
option to try on hard pages, not as the default.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field

from ..engine import Message
from ..events import USAGE_EVENT, Custom, EngineEvent, StepStarted, TextMessageContent, Usage, usage_event
from ..page import PageContext
from ..prompt import CRITIC_SYSTEM_PROMPT, critic_turn, mediator_turn, revision_turn, user_turn
from ..tokens import estimate_tokens, truncate_to_tokens
from .direct import DirectEngine, Provider

log = logging.getLogger('glimpse')

COUNCIL_TEXT_TOKENS = 1500
"""The most of a draft or a critique that is passed on to the next role."""

DRAFTING = 'Drafting an answer'
REVIEWING = 'Checking the draft against the page'
REVISING = 'Revising the answer'
SETTLING = 'Settling the final answer'

_VERDICT = re.compile(r'VERDICT:\s*(APPROVE|REVISE)', re.IGNORECASE)


def parse_verdict(critique: str) -> bool:
    """True if the critic approved. A review that gives no verdict counts as a request to revise."""
    match = _VERDICT.search(critique)
    return bool(match) and match.group(1).upper() == 'APPROVE'


@dataclass
class _Said:
    """What one role answered, after its events have been passed on."""

    text: str
    notices: list[str] = field(default_factory=list)
    streamed: bool = False
    """True if the text already reached the user as it was written."""


@dataclass
class _Totals:
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, usage: Usage) -> None:
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens


class CouncilEngine:
    """Answers through an actor, a critic and a mediator.

    :param model: the actor's model, as for DirectEngine, for example "vertex:claude-opus-5-5"
    :param critic_model: the critic's model. Default: the actor's model
    :param mediator_model: the mediator's model. Default: the actor's model
    :param max_rounds: reviews before the mediator decides. 1 means draft, review, then mediate if needed
    :param system_prompt: replaces the built-in prompt for the actor and the mediator. The critic keeps its own
    :param critic_effort: the critic's effort. Default: the same as effort
    """

    reserved_tokens = 2 * COUNCIL_TEXT_TOKENS + 200
    """Room each request keeps for a draft and a critique, on top of the page and history."""

    def __init__(
        self,
        model: str | None = None,
        *,
        critic_model: str | None = None,
        mediator_model: str | None = None,
        max_rounds: int = 2,
        system_prompt: str | Callable[[PageContext], str] | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        project: str | None = None,
        location: str | None = None,
        max_output_tokens: int = 16000,
        max_tool_rounds: int = 4,
        effort: str = 'medium',
        critic_effort: str | None = None,
        provider: Provider | None = None,
    ) -> None:
        if max_rounds < 1:
            raise ValueError(f'max_rounds must be at least 1, got {max_rounds}.')
        self.model = model
        self.max_rounds = max_rounds
        common = {'api_key': api_key, 'base_url': base_url, 'project': project, 'location': location,
                  'max_output_tokens': max_output_tokens, 'max_tool_rounds': max_tool_rounds, 'provider': provider}
        self.actor = DirectEngine(model, system_prompt=system_prompt, effort=effort, **common)
        self.critic = DirectEngine(critic_model or model, system_prompt=CRITIC_SYSTEM_PROMPT,
                                   effort=critic_effort or effort, **common)
        self.mediator = DirectEngine(mediator_model or model, system_prompt=system_prompt, effort=effort, **common)

    @property
    def system_prompt(self) -> str | Callable[[PageContext], str] | None:
        return self.actor.system_prompt

    def overhead_text(self, page: PageContext) -> str:
        """The largest fixed text of any role. reserved_tokens covers the draft and critique."""
        return max((role.overhead_text(page) for role in (self.actor, self.critic, self.mediator)), key=len)

    async def respond(self, messages: list[Message], page: PageContext) -> AsyncIterator[EngineEvent]:
        history, question = messages[:-1], messages[-1].content
        totals = _Totals()
        actor_sent = [*history, Message('user', user_turn(page, question))]

        draft = _Said('')
        async for item in self._role(self.actor, actor_sent, page, DRAFTING, totals):
            if isinstance(item, _Said):
                draft = item
            else:
                yield item
        final = draft

        # An empty draft means the actor declined or was cut off, and its notice says so.
        for round_number in range(1, self.max_rounds + 1 if draft.text.strip() else 1):
            review = _Said('')
            critic_sent = [*history, Message('user', critic_turn(page, question, _shorten(draft.text)))]
            async for item in self._role(self.critic, critic_sent, page, REVIEWING, totals):
                if isinstance(item, _Said):
                    review = item
                else:
                    yield item
            if not review.text.strip():
                log.info('The council critic gave no review, so the draft stands. %s', review.notices)
                break
            if parse_verdict(review.text):
                break
            critique = _shorten(review.text)

            if round_number == self.max_rounds:
                settled = _Said('')
                mediator_sent = [*history, Message('user', mediator_turn(page, question, _shorten(draft.text), critique))]
                async for item in self._role(self.mediator, mediator_sent, page, SETTLING, totals, stream=True):
                    if isinstance(item, _Said):
                        settled = item
                    else:
                        yield item
                if settled.text.strip():
                    final = settled
                break

            revised = _Said('')
            revision_sent = [*actor_sent, Message('assistant', _shorten(draft.text)), Message('user', revision_turn(critique))]
            async for item in self._role(self.actor, revision_sent, page, REVISING, totals):
                if isinstance(item, _Said):
                    revised = item
                else:
                    yield item
            if revised.text.strip():
                draft = final = revised

        if final.text and not final.streamed:
            yield TextMessageContent(final.text)
        for notice in final.notices:
            yield Custom('glimpse.notice', notice)
        yield usage_event(Usage(input_tokens=totals.input_tokens, output_tokens=totals.output_tokens,
                                model=self.model or ''))

    async def _role(self, role: DirectEngine, sent: list[Message], page: PageContext, step: str, totals: _Totals,
                    *, stream: bool = False) -> AsyncIterator[EngineEvent | _Said]:
        """Run one role, pass on its progress and tool events, and end with what it said."""
        yield StepStarted(step)
        parts: list[str] = []
        notices: list[str] = []
        async with aclosing(role.run(role.system_for(page), sent, page)) as events:
            async for event in events:
                if isinstance(event, TextMessageContent):
                    parts.append(event.delta)
                    if stream:
                        yield event
                elif isinstance(event, StepStarted):
                    yield StepStarted(step)
                elif isinstance(event, Custom) and event.name == USAGE_EVENT:
                    totals.add(event.value)
                elif isinstance(event, Custom) and event.name == 'glimpse.notice':
                    notices.append(str(event.value))
                else:
                    yield event
        yield _Said(''.join(parts), notices, streamed=stream and bool(parts))


def _shorten(text: str) -> str:
    return truncate_to_tokens(text, COUNCIL_TEXT_TOKENS, estimate_tokens, '\n[cut to fit the budget]')
