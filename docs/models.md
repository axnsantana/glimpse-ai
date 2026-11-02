# Choosing a model

You choose the model, and Glimpse does not depend on any cloud service of its own. Model calls always run on your server, so API keys never reach the browser.

## Model strings

| `model=` | Provider | Install | Credentials |
|---|---|---|---|
| `anthropic:claude-opus-5-5` | Anthropic | `glimpse-ai[anthropic]` | `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` or an `ant auth login` profile |
| `openai:gpt-5` | OpenAI | `glimpse-ai[openai]` | `OPENAI_API_KEY` |
| `ollama:llama3.2` | A local Ollama server | `glimpse-ai[openai]` | None |

Any other OpenAI-compatible server (vLLM, LM Studio, a gateway) works with no special handling:

```python
glimpse.attach(engine=glimpse.DirectEngine('openai:my-model', base_url='http://localhost:8000/v1'))
```

## How the model is picked

With the default `engine="auto"`, Glimpse uses the first of these that applies:

1. The `model=` argument
2. The `GLIMPSE_MODEL` environment variable
3. `anthropic:claude-opus-5-5`, if Anthropic credentials are found
4. `openai:gpt-5`, if `OPENAI_API_KEY` is set
5. The offline demo engine, with a banner in the panel and a warning in the server log

Pass `engine="direct"` if you would rather see an error than fall back to the demo.

## What Glimpse sends to Claude

For current Claude models the direct engine turns on adaptive thinking and sets `effort` (default `medium`, which you can change with `DirectEngine(effort=...)`). For Fable 5.1, Opus 5.5, Opus 5 and Sonnet 5.5 on the first-party API, it also enables server-side refusal fallback, so a declined request can retry on another model. It handles refusals and cut-off answers by telling the user, and it never runs a tool call from a cut-off response.

A custom `base_url` is treated as a proxy, so first-party-only fields are left out.

## Cost

Prices change, so Glimpse has no price table. Supply your own:

```python
glimpse.attach(
    pricing={'input': 4.00, 'output': 20.00},   # USD per million tokens
    on_usage=lambda usage: log(usage.total_tokens, usage.cost),
    max_session_cost=0.50,
)
```

`max_session_tokens` and `max_session_cost` apply per session, and a session is one page load. Use `on_usage` to build an app-wide budget.

`budget=` limits **input** per request. Glimpse has no tokenizer dependency, so it estimates tokens from words, digits and symbols, and plans to use 75% of the budget to allow for error. On the real requests we measured, the estimate was 0.97 to 1.12 times Claude's count, and on deliberately awkward text it ranged from about 0.75 to 1.4. Pass `count_tokens=` for your own counts, which also turns off the margin.

The default prompt and tools take about 2,100 estimated tokens, so the direct engine needs a budget of at least about 5,600. `attach()` tells you if yours is too small. Each tool round is a separate request and is billed separately, so a two-round answer costs more than the budget of one request suggests.

## Using your own agent

See [example 06](../examples/06_custom_engine.py). An engine can be an async generator of strings:

```python
async def my_engine(messages, page):
    yield await my_agent.run(page.to_prompt() + '\n\n' + messages[-1].content)

glimpse.attach(engine=my_engine)
```

`page.to_prompt()` gives you the fenced, budgeted page state, and `page.tools` gives you the read-only tools as plain Python callables with JSON schemas. One engine object serves every session, so keep no conversation state on it.
