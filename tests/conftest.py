from __future__ import annotations

import importlib
from collections.abc import AsyncIterator, Callable
from importlib.metadata import version
from pathlib import Path

import pytest
from nicegui import core
from nicegui.testing import User
from nicegui.testing.user_simulation import user_simulation

from .helpers import EXAMPLES

# NiceGUI 4 tests with httpx2 and 3.19 with httpx. Both have the same API, and each is a dependency of the
# NiceGUI it belongs to, so the one imported here is always installed.
http = importlib.import_module('httpx2' if int(version('nicegui').split('.')[0]) >= 4 else 'httpx')

CREDENTIAL_VARIABLES = (
    'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'OPENAI_API_KEY', 'GLIMPSE_MODEL',
    'GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_GENAI_USE_VERTEXAI', 'GOOGLE_GENAI_USE_ENTERPRISE',
    'GOOGLE_CLOUD_PROJECT', 'GOOGLE_CLOUD_LOCATION', 'GCLOUD_PROJECT', 'ANTHROPIC_VERTEX_PROJECT_ID', 'CLOUD_ML_REGION',
    'GOOGLE_APPLICATION_CREDENTIALS', 'ANTHROPIC_VERTEX_BASE_URL', 'GOOGLE_GEMINI_BASE_URL', 'GOOGLE_VERTEX_BASE_URL',
)


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    """Tests must never reach a real provider, whatever the developer's shell has set. Only -m live may."""
    if request.node.get_closest_marker('live'):
        return
    for variable in CREDENTIAL_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv('HOME', str(tmp_path))


@pytest.fixture(autouse=True)
def no_error_logs(caplog: pytest.LogCaptureFixture, request: pytest.FixtureRequest) -> AsyncIterator[None]:
    """An error logged during a test is a failure, even if every assertion passes."""
    yield
    if request.node.get_closest_marker('allow_error_logs'):
        return
    errors = [record.getMessage() for record in caplog.get_records('call') if record.levelname == 'ERROR']
    assert not errors, f'Unexpected ERROR logs: {errors}'


@pytest.fixture
def open_example() -> Callable:
    """Run an example file exactly as it ships, and return a simulated user for it."""

    def opener(name: str) -> AsyncIterator[User]:
        return user_simulation(main_file=next(EXAMPLES.glob(f'{name}*.py')))

    return opener


def second_user() -> User:
    """Another browser on the same running app."""
    return User(http.AsyncClient(transport=http.ASGITransport(core.app), base_url='http://test'))
