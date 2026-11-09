"""Vertex AI, the council engine, and your own Google ADK agent.

Install what you need, sign in to Google Cloud, and run with your project:

    pip install "anthropic[vertex]" google-genai google-adk
    gcloud auth application-default login
    GOOGLE_CLOUD_PROJECT=my-project python examples/11_cloud_and_agents.py

No API key is used: Vertex AI calls use your Google credentials, and GOOGLE_CLOUD_LOCATION
picks the region (default "global"). GLIMPSE_MODEL picks the model, for example
vertex:claude-sonnet-5-5 or vertex:gemini-flash-latest. An API key still works for the
other providers, for example GLIMPSE_MODEL=anthropic:claude-opus-5-5 with ANTHROPIC_API_KEY.

/           The direct engine on Vertex AI: one model, with the project and region set in attach().
/council    The council engine: an actor drafts, a critic checks the draft against the page,
            and a mediator settles any disagreement. Slower and dearer, and checked.
/adk        Your own ADK agent on Gemini, with a tool of its own next to the page tools Glimpse adds.

Try this: on each page, ask "Which region missed its target, and by how much in USD?".
The ADK agent converts with its own tool. Open "What the assistant saw" to see the tool calls.
Without credentials, the panel says what is missing.
"""

import os

from nicegui import ui

import glimpse

MODEL = os.environ.get('GLIMPSE_MODEL', 'vertex:claude-opus-5-5')
PROJECT = os.environ.get('GOOGLE_CLOUD_PROJECT')  # None lets Glimpse report what is missing
LOCATION = os.environ.get('GOOGLE_CLOUD_LOCATION', 'global')

QUESTION = 'Which region missed its target, and by how much in USD?'


def regional_sales() -> None:
    ui.label('Quarterly sales (EUR thousands)').classes('text-h4')
    ui.table(
        title='Sales against target',
        columns=[
            {'name': 'region', 'label': 'Region', 'field': 'region'},
            {'name': 'target', 'label': 'Target', 'field': 'target'},
            {'name': 'actual', 'label': 'Actual', 'field': 'actual'},
        ],
        rows=[
            {'region': 'EMEA', 'target': 420, 'actual': 455},
            {'region': 'Americas', 'target': 610, 'actual': 572},
            {'region': 'APAC', 'target': 300, 'actual': 318},
        ],
    )
    ui.echart({
        'title': {'text': 'Actual by region'},
        'xAxis': {'type': 'category', 'data': ['EMEA', 'Americas', 'APAC']},
        'yAxis': {'type': 'value'},
        'series': [{'type': 'bar', 'name': 'Actual', 'data': [455, 572, 318]}],
    })


@ui.page('/')
def direct_page() -> None:
    regional_sales()
    glimpse.attach(model=MODEL, project=PROJECT, location=LOCATION, suggestions=[QUESTION])


@ui.page('/council')
def council_page() -> None:
    regional_sales()
    glimpse.attach(engine='council', model=MODEL, project=PROJECT, location=LOCATION,
                   title='Assistant (council)', suggestions=[QUESTION])


def eur_to_usd(amount_eur: float) -> dict:
    """Convert an amount in euros to US dollars at today's rate.

    Args:
        amount_eur: the amount in euros.
    """
    rate = 1.08  # A fixed rate for the example. Your tool would call your own service.
    return {'amount_usd': round(amount_eur * rate, 2), 'rate': rate}


def adk_agent():
    """Your agent, built with ADK as usual. Glimpse adds the page tools and its rules for page data."""
    from google.adk.agents import LlmAgent
    from google.adk.models import Gemini

    model = Gemini(model=MODEL.removeprefix('vertex:') if 'gemini' in MODEL else 'gemini-flash-latest',
                   client_kwargs={'vertexai': True, 'project': PROJECT, 'location': LOCATION})
    return LlmAgent(
        name='sales_analyst',
        model=model,
        instruction='You are a sales analyst. Amounts on the page are in thousands of euros. '
                    'When the user asks for dollars, convert with eur_to_usd.',
        tools=[eur_to_usd],
    )


@ui.page('/adk')
def adk_page() -> None:
    regional_sales()
    try:
        agent = adk_agent()
    except ImportError:
        ui.label('This page needs Google ADK: pip install google-adk (Python 3.11 or later).')
        return
    glimpse.attach(engine=agent, title='Assistant (ADK)', suggestions=[QUESTION])


ui.run(title='Glimpse on Vertex AI')
