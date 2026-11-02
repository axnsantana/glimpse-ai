"""Turn model output into a safe document for the panel (SEC-2, SEC-3, SEC-9).

The output never reaches a Markdown or HTML renderer. A small parser turns it into a
tree of blocks, and the panel builds DOM nodes from that tree with textContent only, so
HTML in model output is just text. Images are never rendered. A link gets an href only
if it passes the check here. Every streamed chunk goes through this on the server.

Data can leave through a rendered image with no click at all (EchoLeak, GitLab Duo), or
through a link the user clicks. That is why external links are not clickable by default.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

_INLINE = re.compile(
    r'(?P<image>!\[(?P<alt>[^\]\n]*)\]\((?P<image_url>[^)\s]*)[^)\n]*\))'
    r'|(?P<ref>\[ref:(?P<ref_id>[\w.:-]+)\])'
    r'|(?P<link>\[(?P<link_text>[^\]\n]+)\]\((?P<link_url>[^)\s]*)[^)\n]*\))'
    r'|(?P<code>`(?P<code_text>[^`\n]+)`)'
    r'|(?P<bold>\*\*(?P<bold_text>[^\n]+?)\*\*)'
    r'|(?P<italic>(?<![\w*])\*(?P<italic_text>[^*\n]+?)\*(?![\w*]))'
)
_HEADING = re.compile(r'^(#{1,4})\s+(.*)$')
_BULLET = re.compile(r'^\s*[-*+]\s+(.*)$')
_ORDERED = re.compile(r'^\s*\d+[.)]\s+(.*)$')
_RULE = re.compile(r'^\s*([-*_])(\s*\1){2,}\s*$')
_TABLE_DIVIDER = re.compile(r'^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$')


@dataclass
class SafeDocument:
    blocks: list[dict[str, Any]] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    """Known element IDs the text cited, in order."""
    removed_images: int = 0
    blocked_links: int = 0


def render_safe(
    text: str,
    *,
    known_ids: Collection[str] = (),
    allowed_link_hosts: Collection[str] = (),
) -> SafeDocument:
    """Parse model output into safe blocks. Handles partial text, as it runs on every chunk."""
    document = SafeDocument()
    context = _Context(document, set(known_ids), {host.lower() for host in allowed_link_hosts})
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    index = 0
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            document.blocks.append({'t': 'p', 'c': context.inline(' '.join(paragraph))})
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith('```'):
            flush()
            language = stripped[3:].strip()
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith('```'):
                code.append(lines[index])
                index += 1
            document.blocks.append({'t': 'code', 'lang': language[:30], 'v': '\n'.join(code)})
        elif not stripped:
            flush()
        elif _RULE.match(line):
            flush()
            document.blocks.append({'t': 'hr'})
        elif heading := _HEADING.match(stripped):
            flush()
            document.blocks.append({'t': 'h', 'level': len(heading.group(1)), 'c': context.inline(heading.group(2))})
        elif stripped.startswith('|') and index + 1 < len(lines) and _TABLE_DIVIDER.match(lines[index + 1]):
            flush()
            rows = [_table_cells(line)]
            index += 2
            while index < len(lines) and lines[index].strip().startswith('|'):
                rows.append(_table_cells(lines[index]))
                index += 1
            index -= 1
            document.blocks.append({
                't': 'table',
                'head': [context.inline(cell) for cell in rows[0]],
                'rows': [[context.inline(cell) for cell in row] for row in rows[1:]],
            })
        elif _BULLET.match(line) or _ORDERED.match(line):
            flush()
            ordered = bool(_ORDERED.match(line))
            pattern = _ORDERED if ordered else _BULLET
            items = []
            while index < len(lines) and (item := pattern.match(lines[index])):
                items.append(context.inline(item.group(1)))
                index += 1
            index -= 1
            document.blocks.append({'t': 'ol' if ordered else 'ul', 'items': items})
        elif stripped.startswith('>'):
            flush()
            quote = []
            while index < len(lines) and lines[index].strip().startswith('>'):
                quote.append(lines[index].strip().lstrip('>').strip())
                index += 1
            index -= 1
            document.blocks.append({'t': 'quote', 'c': context.inline(' '.join(quote))})
        else:
            paragraph.append(stripped)
        index += 1
    flush()
    return document


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip('|').split('|')]


@dataclass
class _Context:
    document: SafeDocument
    known_ids: set[str]
    allowed_hosts: set[str]

    def inline(self, text: str) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        position = 0
        for match in _INLINE.finditer(text):
            if match.start() > position:
                nodes.append({'t': 'text', 'v': text[position:match.start()]})
            position = match.end()
            if match.group('image'):
                self.document.removed_images += 1
                alt = match.group('alt').strip()
                nodes.append({'t': 'note', 'v': f'[image removed: {alt}]' if alt else '[image removed]'})
            elif match.group('ref'):
                self._citation(match.group('ref_id'), nodes)
            elif match.group('link'):
                self._link(match.group('link_text'), match.group('link_url'), nodes)
            elif match.group('code'):
                nodes.append({'t': 'code', 'v': match.group('code_text')})
            elif match.group('bold'):
                nodes.append({'t': 'b', 'c': self.inline(match.group('bold_text'))})
            else:
                nodes.append({'t': 'i', 'c': self.inline(match.group('italic_text'))})
        if position < len(text):
            nodes.append({'t': 'text', 'v': text[position:]})
        return nodes

    def _citation(self, element_id: str, nodes: list[dict[str, Any]]) -> None:
        """Only IDs from this snapshot become links to an element. Others are dropped."""
        if element_id not in self.known_ids:
            return
        if element_id not in self.document.citations:
            self.document.citations.append(element_id)
        nodes.append({'t': 'ref', 'id': element_id})

    def _link(self, label: str, url: str, nodes: list[dict[str, Any]]) -> None:
        if is_allowed_url(url, self.allowed_hosts):
            nodes.append({'t': 'a', 'href': url, 'c': self.inline(label)})
            return
        self.document.blocked_links += 1
        host = urlsplit(url).hostname if url.lower().startswith(('http://', 'https://')) else None
        suffix = f' (link to {host} removed)' if host else ' (link removed)'
        nodes.append({'t': 'text', 'v': label})
        nodes.append({'t': 'note', 'v': suffix})


def is_allowed_url(url: str, allowed_hosts: Collection[str] = ()) -> bool:
    """Allow same-site paths and http(s) links to hosts the developer listed. Nothing else."""
    if not url or any(character.isspace() or ord(character) < 32 for character in url):
        return False
    if url.startswith('/') and not url.startswith(('//', '/\\')):
        return True
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme.lower() not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        return False
    return parts.hostname.lower() in {host.lower() for host in allowed_hosts}
