# Getting started

Glimpse adds an assistant in a side panel to a NiceGUI app. It answers questions about what the user sees on the page, including filters, selected tabs and chart zoom, with no annotations in your code.

## Install

Glimpse is not on PyPI yet, so install it from a clone of the repository:

```bash
pip install -e ".[anthropic]"    # .[vertex] for Vertex AI, .[gemini], .[openai] for OpenAI and local models, .[adk]
```

Once it is released, this will be `pip install "glimpse-ai[anthropic]"`.

You import it as `glimpse`. Python 3.10 or later and NiceGUI 3.19 or later are required.

## Add it to a page

Put one call at the end of a page function:

```python
from nicegui import ui
import glimpse

@ui.page('/')
def dashboard():
    ui.echart({...})
    ui.aggrid({...})
    glimpse.attach()

ui.run()
```

Or call it once at module level to cover every page, including `ui.sub_pages` and script mode:

```python
glimpse.attach(skip_paths=['/login'])
```

## Connect a model

Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` on the server, or pass `model=`. See [models.md](models.md). Keep keys in your environment or in a `.env` file that git ignores.

For Vertex AI, use your Google credentials instead of a key, and name the project and location:

```python
glimpse.attach(model='vertex:claude-opus-5-5', project='my-project', location='global')
```

To have answers checked before they are shown, or to use your own Google ADK agent, see [engines.md](engines.md).

With no credentials, Glimpse runs in **offline demo mode**: it answers from simple keyword rules over the page, and the panel shows a banner saying so. This lets you try the examples without a key. It is not a replacement for a model.

## Check what the assistant sees

Under each answer, open **What the assistant saw**. It shows exactly what was sent and how much of the token budget it used. If an answer looks wrong, start here.

## Common options

| Option | What it does |
|---|---|
| `context=` | Facts the screen does not show, as a string or a function. End users can extract this text |
| `exclude_fields=` | Column or input names to withhold, as strings or compiled regular expressions |
| `redact=` | A function run on every string before it can leave the process |
| `budget=` | The most tokens one request may use. The default is 16,000 |
| `visibility=` | `"visible"` (the default) or `"reachable"`. See [visibility-policy.md](visibility-policy.md) |
| `suggestions=` | Starter questions shown in an empty conversation |
| `on_usage=`, `pricing=`, `max_session_tokens=`, `max_session_cost=` | Track and limit spending |
| `system_prompt=` | Replaces the built-in system prompt exactly |
| `push=False` | Overlay the page instead of making room for the panel |

`help(glimpse.adapters.nicegui.attach)` lists them all.

## Annotate only if you want to

```python
glimpse.describe(chart, id='nps', description='Q3 used a new vendor.', value=lambda: {'target': 45})
glimpse.exclude(secret_card)
```

## Next

- The [examples](../examples/README.md) show each feature in a running app
- [security.md](security.md) before you ship to customers
- [known-limits.md](known-limits.md) for what does not work yet
