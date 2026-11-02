from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest
from nicegui import core
from nicegui.testing import User
from nicegui.testing.user_simulation import user_simulation

from .helpers import EXAMPLES

CREDENTIAL_VARIABLES = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'OPENAI_API_KEY', 'GLIMPSE_MODEL')


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
    return User(httpx.AsyncClient(transport=httpx.ASGITransport(core.app), base_url='http://test'))
