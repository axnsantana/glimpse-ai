"""Rules that keep the design honest: they hold across the code, not just on one path."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SOURCE = ROOT / 'src' / 'glimpse'
ADAPTER = SOURCE / 'adapters' / 'nicegui'


def run_python(code: str) -> str:
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120, check=True)
    return result.stdout.strip()


def test_core_does_not_import_nicegui_or_any_provider():
    """NFR-1 and NFR-6: only the adapter touches NiceGUI, and SDKs load only when used."""
    output = run_python(
        'import sys, glimpse\n'
        'print(sorted(m for m in ("nicegui", "anthropic", "openai", "plotly", "numpy", "pandas", "ag_ui") '
        'if m in sys.modules))'
    )
    assert output == '[]'


def test_only_the_adapter_mentions_nicegui():
    offenders = []
    for path in SOURCE.rglob('*.py'):
        if ADAPTER in path.parents:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or '']
                if any(name.split('.')[0] == 'nicegui' for name in names):
                    offenders.append(str(path))
    assert not offenders, offenders


def test_private_nicegui_attributes_only_appear_in_compat():
    """NFR-7: a NiceGUI upgrade should have one place to break."""
    private = ('_props', '_classes', '_style', '_event_listeners', '_deleted')
    offenders = []
    for path in ADAPTER.glob('*.py'):
        if path.name == '_compat.py':
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in private:
                if isinstance(node.value, ast.Name) and node.value.id == 'self' and path.name == 'panel.py':
                    continue  # A subclass setting its own props is NiceGUI's documented way to write a component.
                offenders.append(f'{path.name}:{node.lineno} {node.attr}')
    assert not offenders, offenders


def test_no_conversation_or_page_state_at_module_level():
    """SEC-1: mutable module-level values are how sessions leak into each other."""
    allowed = {'REGISTRY'}  # Maps widget classes to reader functions. Holds code, not user data.
    offenders = []
    for path in SOURCE.rglob('*.py'):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            mutable = isinstance(value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp))
            if isinstance(value, ast.Call) and getattr(value.func, 'id', '') in ('list', 'dict', 'set', 'defaultdict'):
                mutable = True
            for target in targets:
                name = getattr(target, 'id', '')
                if mutable and name not in allowed and name != '__all__' and not name.startswith('_BDATA'):
                    offenders.append(f'{path.relative_to(SOURCE)}:{node.lineno} {name}')
    assert not offenders, offenders


def required_dependencies() -> list[str]:
    match = re.search(r'^dependencies = \[(.*?)\]', (ROOT / 'pyproject.toml').read_text(), re.MULTILINE | re.DOTALL)
    return re.findall(r'"([^"]+)"', match.group(1))


def test_declared_dependencies_stay_near_zero():
    assert [item.split('>')[0] for item in required_dependencies()] == ['nicegui']
    text = (ROOT / 'pyproject.toml').read_text()
    assert 'anthropic = [' in text and 'openai = [' in text, 'providers stay optional extras'


def test_minimum_nicegui_covers_the_advisory_list():
    """SEC-9: 3.19.0 fixes GHSA-m47w-xwfc-82pf, the latest advisories when this was set. See docs/security.md."""
    assert required_dependencies()[0].startswith('nicegui>=3.19.0')


def test_every_example_is_listed_and_has_try_this_docs():
    readme = (ROOT / 'examples' / 'README.md').read_text()
    for path in sorted((ROOT / 'examples').glob('*.py')):
        assert path.name in readme, f'{path.name} is missing from examples/README.md'
        assert ast.get_docstring(ast.parse(path.read_text())), f'{path.name} needs a docstring explaining what to try'


def test_required_docs_exist():
    """NFR-8."""
    for name in ('getting-started', 'models', 'data-flow', 'visibility-policy', 'security', 'known-limits',
                 'versioning', 'nicegui-internals'):
        assert (ROOT / 'docs' / f'{name}.md').is_file(), name
