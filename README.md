# Glimpse

Add an AI assistant that can see the page to your [NiceGUI](https://nicegui.io) app, in one line.

```python
from nicegui import ui
import glimpse

@ui.page('/')
def dashboard():
    ui.echart({...})
    ui.aggrid({...})
    glimpse.attach()    # That's it

ui.run()
```

Users get a side panel where they can ask about what is on their screen. The assistant reads the live page when they ask, including their filters, sort order, selected tab and chart zoom. You do not annotate anything or pass it any data.

![Glimpse beside a sales dashboard. After the user filters the grid, the assistant reports the 21 orders on screen and the highest amount among them](https://raw.githubusercontent.com/axnsantana/glimpse-ai/main/docs/images/real-model-filtered-grid.png)

> **Status: 0.1, an early MVP.** Capture, the panel and the security defaults are tested in a real browser. With Claude Opus 5.5, it answered all 26 reference questions correctly, in one run on a single dashboard with a simple scorer. That is a good early sign, not a full evaluation. See [known limits](https://github.com/axnsantana/glimpse-ai/blob/main/docs/known-limits.md).

## Install

```bash
pip install "glimpse-ai[anthropic]"
```

Pick the extra for your model: `anthropic`, `vertex` for Google Cloud Vertex AI, `gemini`, `openai` for OpenAI and local models, and `adk` for Google ADK agents. The package is `glimpse-ai`, and you import it as `glimpse`. Python 3.10 or later and NiceGUI 3.19 or later are required. Gemini and ADK need Python 3.11 or later.

## Try it

No API key is needed. Without one, the panel runs in a clearly labelled offline demo mode that answers from simple rules over the page.

```bash
git clone https://github.com/axnsantana/glimpse-ai && cd glimpse-ai
conda env create -f environment.yml && conda activate glimpse
python examples/02_sales_dashboard.py
```

For real answers, set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` on the server, point it at a Google Cloud project for Vertex AI, or run a local model. See [Choosing a model](https://github.com/axnsantana/glimpse-ai/blob/main/docs/models.md).

## Examples

Each one is a small runnable app, and each one runs in the test suite as it ships.

| | Example | Shows |
|---|---|---|
| 01 | [Quickstart](https://github.com/axnsantana/glimpse-ai/blob/main/examples/01_quickstart.py) | One line, and answers that follow the screen |
| 02 | [Sales dashboard](https://github.com/axnsantana/glimpse-ai/blob/main/examples/02_sales_dashboard.py) | `ui.echart`, `ui.plotly`, `ui.aggrid`, `ui.table`, inputs and tabs, with no annotations |
| 03 | [Large data](https://github.com/axnsantana/glimpse-ai/blob/main/examples/03_large_data.py) | 200,000 points inside a 6,000-token budget |
| 04 | [Multi-page apps](https://github.com/axnsantana/glimpse-ai/blob/main/examples/04_multi_page.py) | One call for a whole app, including sub pages |
| 05 | [Existing layouts](https://github.com/axnsantana/glimpse-ai/blob/main/examples/05_existing_layout.py) | Sharing a page with drawers and hostile CSS |
| 06 | [Custom engines](https://github.com/axnsantana/glimpse-ai/blob/main/examples/06_custom_engine.py) | Your own agent, in as little as one async generator |
| 07 | [Choosing a model](https://github.com/axnsantana/glimpse-ai/blob/main/examples/07_choose_your_model.py) | Cloud or local models, prompts, usage and limits |
| 08 | [Privacy and security](https://github.com/axnsantana/glimpse-ai/blob/main/examples/08_privacy_and_security.py) | Secrets stay out, and a compromised model cannot exfiltrate data |
| 09 | [Developer context](https://github.com/axnsantana/glimpse-ai/blob/main/examples/09_developer_context.py) | Adding what the screen cannot show |
| 10 | [Two users](https://github.com/axnsantana/glimpse-ai/blob/main/examples/10_two_users.py) | Sessions that never see each other |
| 11 | [Cloud and agents](https://github.com/axnsantana/glimpse-ai/blob/main/examples/11_cloud_and_agents.py) | Vertex AI with a project and region, the council engine, and your own ADK agent |

## What makes it different

Passing data to a chat function by hand works until users start filtering. Then a hand-wired assistant answers from all the rows while the user looks at a few. Glimpse reads the view the user actually has, on each question.

| | |
|---|---|
| **Sees the applied view** | Grid filters and sort, chart zoom and hidden series, table sort, inputs and tabs |
| **Stays inside a budget** | Large tables and series become statistics computed in Python, plus a visible "Showing 50 of 12,000 rows" and read-only tools to fetch more |
| **Shows its work** | "What the assistant saw" under each answer, and sources that scroll to the element used |
| **Safe by default** | Passwords withheld, hidden text ignored, images and external links in answers disabled, sessions isolated |
| **Your model** | Claude and Gemini, on their APIs or on Vertex AI, OpenAI, local models, a council of models that checks its answers, a Google ADK agent, or your own. No cloud service of ours, and no agent framework required |
| **Small** | NiceGUI is the only required dependency |

![The panel beside a host app with its own drawers and hostile CSS](https://raw.githubusercontent.com/axnsantana/glimpse-ai/main/docs/images/existing-layout.png)

## How it works

```text
Page (NiceGUI) -> Adapter -> PageContext -> Context builder -> Engine -> Model -> Sanitizer -> Panel
```

Everything runs in your NiceGUI process. Read [Data flow](https://github.com/axnsantana/glimpse-ai/blob/main/docs/data-flow.md) to see what goes where.

## Docs

- [Getting started](https://github.com/axnsantana/glimpse-ai/blob/main/docs/getting-started.md)
- [Choosing a model](https://github.com/axnsantana/glimpse-ai/blob/main/docs/models.md)
- [Engines: direct, council, ADK and your own](https://github.com/axnsantana/glimpse-ai/blob/main/docs/engines.md)
- [Data flow](https://github.com/axnsantana/glimpse-ai/blob/main/docs/data-flow.md)
- [Visibility policy](https://github.com/axnsantana/glimpse-ai/blob/main/docs/visibility-policy.md): what counts as "seen"
- [Security and privacy](https://github.com/axnsantana/glimpse-ai/blob/main/docs/security.md)
- [Known limits](https://github.com/axnsantana/glimpse-ai/blob/main/docs/known-limits.md)
- [Releasing](https://github.com/axnsantana/glimpse-ai/blob/main/docs/releasing.md)
- [Versioning](https://github.com/axnsantana/glimpse-ai/blob/main/docs/versioning.md)
- [NiceGUI internals](https://github.com/axnsantana/glimpse-ai/blob/main/docs/nicegui-internals.md)
- [Requirements status](https://github.com/axnsantana/glimpse-ai/blob/main/docs/requirements-status.md): each SRS requirement and its evidence
- [Going public](https://github.com/axnsantana/glimpse-ai/blob/main/docs/going-public.md): the steps to release the code and publish the presentation page in `site/`

## Development

```bash
conda env create -f environment.yml && conda activate glimpse
pytest                # Fast tests, including every example
pytest -m e2e         # Real Chrome against the real examples
ruff check src tests examples
```

`pytest -m live` scores a real model on the reference question set (about $0.35 on Claude Opus 5.5) and checks real requests against the budget with the free token counting endpoint. See [tests/test_fidelity.py](https://github.com/axnsantana/glimpse-ai/blob/main/tests/test_fidelity.py).

## License

[MIT](https://github.com/axnsantana/glimpse-ai/blob/main/LICENSE)
