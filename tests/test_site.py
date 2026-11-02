"""The presentation page should not drift away from the project it describes."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
PAGE = (ROOT / 'site' / 'index.html').read_text()


def test_every_image_on_the_page_exists():
    images = re.findall(r'src="(images/[^"]+)"', PAGE)
    assert images
    for image in images:
        assert (ROOT / 'site' / image).is_file(), image


def test_every_repository_link_points_at_a_real_file():
    paths = re.findall(r'github\.com/axnsantana/glimpse-ai/blob/main/([^"#]+)', PAGE)
    assert paths
    for path in paths:
        assert (ROOT / path).is_file(), path


def test_every_example_is_listed():
    for path in (ROOT / 'examples').glob('*.py'):
        assert f'examples/{path.name}' in PAGE, path.name


def test_install_requirements_match_the_project():
    project = (ROOT / 'pyproject.toml').read_text()
    assert re.search(r'nicegui>=3\.19', project) and 'NiceGUI 3.19 or later' in PAGE
    assert 'requires-python = ">=3.10"' in project and 'Python 3.10 or later' in PAGE


def test_the_page_loads_no_tracking_or_unknown_scripts():
    assert not re.findall(r'<script[^>]+src=', PAGE), 'the page has one small inline script and needs nothing else'
    hosts = set(re.findall(r'<link[^>]+href="https://([^/"]+)', PAGE))
    assert hosts <= {'fonts.googleapis.com', 'fonts.gstatic.com'}
