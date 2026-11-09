# Engines

An engine turns the conversation and the page snapshot into an answer. Glimpse captures the page, fits it into the budget and sanitizes the output for every engine, so engines differ only in how they reach an answer.

| Engine | `attach(engine=...)` | Model calls per question | Needs |
|---|---|---|---|
| Direct | `"direct"`, or `"auto"` when credentials are found | 1, plus one per tool round | The provider's SDK |
| Council | `"council"` | 2 to 6, plus tool rounds | The provider's SDK |
| ADK | your ADK agent, or `"adk"` | Whatever your agent does | `google-adk`, Python 3.11 or later |
| Offline demo | `"offline"`, or `"auto"` with no credentials | None | Nothing |
| Your own | a function or an object with `respond()` | Up to you | Up to you |

Every engine works with every model string in [models.md](models.md). The ADK engine is the exception: it builds agents for `vertex:`, `gemini:` and `anthropic:` models, and takes any model your own agent uses.

## Direct

One model answers, reading more of the page through four read-only tools when it needs to. This is the default and the only engine measured on a real model so far.

```python
glimpse.attach(model='vertex:claude-opus-5-5', project='my-project', location='global')
```

## Council

An actor drafts an answer, a critic checks the draft against the page, and a mediator settles the answer if they still disagree. It is the "Actor-Critic-Mediator" engine from the original design.

```python
glimpse.attach(engine='council', model='vertex:claude-opus-5-5', project='my-project')

# Or with more control
glimpse.attach(engine=glimpse.CouncilEngine(
    'vertex:claude-opus-5-5',
    critic_model='vertex:claude-sonnet-5-5',   # a different model often catches different mistakes
    critic_effort='low',
    max_rounds=2,                               # reviews before the mediator decides
    project='my-project',
))
```

For each question:

1. **The actor** drafts an answer, exactly as the direct engine would.
2. **The critic** reviews the draft against the page state. It has the same read-only tools, so it can check totals and filtered values itself. It replies `VERDICT: APPROVE` or `VERDICT: REVISE` with a list of problems.
3. **If the critic wants changes**, the actor revises once per remaining round, and the critic reviews again.
4. **If they still disagree after the last round**, the mediator writes the final answer from the page, the last draft and the critique.

The user sees only the final answer. The panel shows the current step ("Drafting an answer", "Checking the draft against the page"), and "What the assistant saw" lists the tool calls of every role.

**What it costs.** An approved first draft takes two model calls, and a full disagreement with `max_rounds=2` takes five, before tool rounds. Each request also keeps about 3,200 tokens for a draft and a critique, so the council needs a `budget=` of at least about 14,100 tokens. The default 16,000 works. `attach()` tells you if yours is too small.

**What is not known yet.** Spike S3 was meant to show whether the extra calls give better answers, and it has not run. Use the council on pages where a wrong number is costly, and compare it with the direct engine on your own questions before making it the default.

**Streaming.** A draft the critic approves appears in one piece when the review ends, because Glimpse cannot know in advance that it will be approved. The mediator's answer streams.

**Safety.** Drafts and critiques are model output that read untrusted page text. They are fenced as data, like the page state, and the critic is told to report instructions it finds in them. The critic's own text never reaches the user.

## ADK

[Google ADK](https://adk.dev) agents plug in through a thin adapter. Pass your agent as it is:

```python
from google.adk.agents import LlmAgent
from google.adk.models import Gemini

def eur_to_usd(amount_eur: float) -> dict:
    """Convert euros to US dollars."""
    return {'amount_usd': amount_eur * 1.08}

agent = LlmAgent(
    name='sales_analyst',
    model=Gemini(model='gemini-flash-latest',
                 client_kwargs={'vertexai': True, 'project': 'my-project', 'location': 'global'}),
    instruction='Amounts are in thousands of euros.',
    tools=[eur_to_usd],
)
glimpse.attach(engine=agent)
```

Or let Glimpse build a single agent from a model string: `glimpse.attach(engine='adk', model='vertex:gemini-flash-latest', project='my-project')`.

For each question, the adapter:

- **Copies your agent**, so your object is never changed, and adds the four read-only page tools to every `LlmAgent` in it, next to your own tools.
- **Puts Glimpse's rules for page data in front of each instruction.** They say that page text is data, how to cite elements, and to say "not on this page" instead of guessing. Your instruction follows them. Pass `glimpse.AdkEngine(agent, glimpse_rules=False)` to rely on your own.
- **Starts a new in-memory ADK session** holding the conversation so far as text, with the page state in the last message. Glimpse keeps and budgets the history, so one agent serves every user without sharing state.
- **Maps ADK events onto Glimpse events.** Text streams, tool calls show as progress and in the inspector, and token usage is summed. No ADK type reaches the panel.

With a pipeline such as a `SequentialAgent`, every agent's text is shown by default. Pass `answer_from=['writer']` to show only the agents you name, and the others appear as progress ("researcher is working").

**Limits.** Only agent trees built from `sub_agents` get the page tools. ADK 2's graph `Workflow` API has not been tried. Sessions, memory and artifact services you configure on a `Runner` are not used, because Glimpse runs the agent itself. Tools you give your agent are yours to secure: Glimpse sanitizes what the agent writes, not what your tools do.

## Your own

See [models.md](models.md#using-your-own-agent) and [example 06](../examples/06_custom_engine.py). An async generator of strings is enough.

## Which to use

Start with the direct engine. Try the council where answers are checked by hand today, or where a wrong number is costly. Use ADK when you already have an ADK agent, or want its tools, callbacks and multi-agent patterns next to the page. All of them run on Vertex AI.
