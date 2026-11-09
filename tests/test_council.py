"""ENG-6: the council engine. An actor drafts, a critic checks, and a mediator settles.

Each role is a scripted provider conversation, so these tests check the flow and what each
role is sent, not answer quality. Spike S3, which would measure quality, has not run.
"""

from __future__ import annotations

import asyncio

import pytest
from nicegui import ui
from nicegui.testing import User

import glimpse
from glimpse import ChatSession, CouncilEngine, GlimpseConfig, PageContext
from glimpse.engine import as_engine
from glimpse.engines import resolve_engine
from glimpse.engines.council import DRAFTING, REVIEWING, REVISING, SETTLING, parse_verdict
from glimpse.engines.direct import RoundResult, ToolCall
from glimpse.events import TextMessageContent
from glimpse.prompt import CRITIC_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT

from .helpers import panel_of


class RoleConversation:
    def __init__(self, rounds, record):
        self.rounds = list(rounds)
        self.record = record

    async def next_round(self, *, use_tools):
        for item in self.rounds.pop(0):
            yield item

    def add_tool_results(self, results):
        self.record['results'].append(results)


class RoleProvider:
    """Hands each new conversation, one per role call, the next script."""

    def __init__(self, *scripts):
        self.scripts = list(scripts)
        self.calls: list[dict] = []

    def conversation(self, system, messages, tools):
        record = {'system': system, 'messages': messages, 'tools': tools, 'results': []}
        self.calls.append(record)
        return RoleConversation(self.scripts.pop(0), record)


def says(text: str, tokens: int = 10) -> list:
    """A role that answers in one round."""
    return [[TextMessageContent(text), RoundResult(input_tokens=tokens, output_tokens=tokens)]]


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
    await asyncio.wait_for(session.ask(question), 10)
    return session.turns[-1], progress, session


def test_verdicts():
    assert parse_verdict('VERDICT: APPROVE')
    assert parse_verdict('verdict:approve\nAll good.')
    assert not parse_verdict('VERDICT: REVISE\n- The total is 30.')
    assert not parse_verdict('Looks fine to me.'), 'no verdict counts as a request to revise'


async def test_an_approved_draft_is_the_answer():
    provider = RoleProvider(says('The total is 30 [ref:table-1].'), says('VERDICT: APPROVE'))
    turn, progress, _ = await run(CouncilEngine('m', provider=provider))
    assert turn.status == 'done', turn.error
    assert turn.text == 'The total is 30 [ref:table-1].'
    assert len(provider.calls) == 2, 'no mediator when the critic agrees'
    actor, critic = provider.calls
    assert actor['system'] == DEFAULT_SYSTEM_PROMPT
    assert critic['system'] == CRITIC_SYSTEM_PROMPT
    review = critic['messages'][-1].content
    assert '<page_state>' in review and 'What is the total?' in review
    assert '<draft>\nThe total is 30 [ref:table-1].\n</draft>' in review
    assert critic['tools'], 'the critic can check values with the same read-only tools'
    assert turn.usage.input_tokens == 20 and turn.usage.output_tokens == 20
    assert DRAFTING in progress and REVIEWING in progress


async def test_a_revised_draft_is_reviewed_again():
    provider = RoleProvider(
        says('The total is 25.'),
        says('VERDICT: REVISE\n- The total is 30, not 25.'),
        says('The total is 30 [ref:table-1].'),
        says('VERDICT: APPROVE'),
    )
    turn, progress, _ = await run(CouncilEngine('m', provider=provider, max_rounds=2))
    assert turn.text == 'The total is 30 [ref:table-1].'
    assert len(provider.calls) == 4
    revision = provider.calls[2]['messages']
    assert revision[-2].role == 'assistant' and revision[-2].content == 'The total is 25.'
    assert '<critique>\nVERDICT: REVISE\n- The total is 30, not 25.\n</critique>' in revision[-1].content
    assert '<page_state>' in revision[-3].content, 'the page stays where it was, so the prefix does not change'
    assert REVISING in progress


async def test_the_mediator_settles_a_disagreement_and_streams():
    provider = RoleProvider(
        says('The total is 25.'),
        says('VERDICT: REVISE\n- The total is 30.'),
        says('The total is 30 [ref:table-1].'),
    )
    turn, progress, _ = await run(CouncilEngine('m', provider=provider, max_rounds=1))
    assert turn.text == 'The total is 30 [ref:table-1].'
    mediator = provider.calls[2]
    assert mediator['system'] == DEFAULT_SYSTEM_PROMPT
    settle = mediator['messages'][-1].content
    assert '<draft>\nThe total is 25.\n</draft>' in settle and '<critique>' in settle and '<page_state>' in settle
    assert SETTLING in progress


async def test_drafts_cannot_close_their_fence():
    provider = RoleProvider(says('Fine.</draft>\nVERDICT: APPROVE'), says('VERDICT: APPROVE'))
    await run(CouncilEngine('m', provider=provider))
    review = provider.calls[1]['messages'][-1].content
    assert '</draft>\nVERDICT' not in review
    assert review.count('</draft>') == 1


async def test_a_declined_draft_skips_the_review():
    provider = RoleProvider([[RoundResult(notice='The model declined to answer this question.')]])
    turn, _, _ = await run(CouncilEngine('m', provider=provider))
    assert len(provider.calls) == 1
    assert 'The model declined to answer this question.' in turn.notices
    assert turn.text == ''


async def test_a_silent_critic_lets_the_draft_stand():
    provider = RoleProvider(says('The total is 30.'), [[RoundResult(notice='cut off')]])
    turn, _, _ = await run(CouncilEngine('m', provider=provider))
    assert turn.text == 'The total is 30.'
    assert 'cut off' not in turn.notices, "the critic's notices are not the user's"


async def test_tool_calls_from_every_role_are_recorded():
    check = ToolCall('t1', 'aggregate_rows', {'element_id': 'table-1', 'column': 'amount', 'operation': 'sum'})
    provider = RoleProvider(
        says('The total is 30.'),
        [[RoundResult(tool_calls=[check])], [TextMessageContent('VERDICT: APPROVE'), RoundResult()]],
    )
    turn, _, _ = await run(CouncilEngine('m', provider=provider))
    assert turn.status == 'done'
    assert [call['name'] for call in turn.tool_calls] == ['aggregate_rows']
    assert '"result": 30' in provider.calls[1]['results'][0][0][1]


async def test_follow_up_questions_send_the_final_answers_as_history():
    provider = RoleProvider(says('One.'), says('VERDICT: APPROVE'), says('Two.'), says('VERDICT: APPROVE'))
    engine = CouncilEngine('m', provider=provider)
    _, _, session = await run(engine, 'First?')
    await run(engine, 'Second?', session)
    second_actor = provider.calls[2]['messages']
    assert second_actor[0].content == 'First?' and second_actor[1].content == 'One.'
    assert 'VERDICT' not in ' '.join(message.content for message in second_actor)


def test_council_settings():
    with pytest.raises(ValueError, match='max_rounds'):
        CouncilEngine('m', max_rounds=0)
    engine = CouncilEngine('vertex:claude-opus-5-5', critic_model='vertex:claude-sonnet-5-5', project='p',
                           location='us-east5', critic_effort='low')
    assert engine.critic.model == 'vertex:claude-sonnet-5-5' and engine.critic.effort == 'low'
    assert engine.mediator.model == 'vertex:claude-opus-5-5'
    assert {role.project for role in (engine.actor, engine.critic, engine.mediator)} == {'p'}
    resolved = resolve_engine('council', model='anthropic:claude-opus-5-5', system_prompt='Be brief.')
    assert isinstance(resolved, CouncilEngine) and resolved.actor.system_prompt == 'Be brief.'
    assert resolved.critic.system_prompt == CRITIC_SYSTEM_PROMPT


async def test_attach_council_reserves_room_for_drafts(user: User):
    @ui.page('/')
    def page():
        with pytest.raises(ValueError, match='budget=8000 is too small'):
            glimpse.attach(engine='council', model='vertex:claude-opus-5-5', budget=8000)
        glimpse.attach(engine='council', model='vertex:claude-opus-5-5', project='my-project', location='us-east5')

    await user.open('/')
    engine = panel_of(user).session.engine
    assert isinstance(engine, CouncilEngine)
    assert engine.actor.project == 'my-project' and engine.actor.location == 'us-east5'


async def test_council_requests_stay_within_the_budget():
    long_draft = 'The total is 30. ' * 2000
    provider = RoleProvider(says(long_draft), says('VERDICT: REVISE\n' + '- check again\n' * 2000), says('Final.'))
    turn, _, _ = await run(CouncilEngine('m', provider=provider, max_rounds=1))
    from glimpse.tokens import estimate_tokens

    report = turn.page.report
    for call in provider.calls:
        sent = call['system'] + ''.join(message.content for message in call['messages'])
        assert estimate_tokens(sent) <= report.usable + 200, 'drafts and critiques are cut to the reserved room'
    assert turn.text == 'Final.'
