"""Token estimates. No tokenizer dependency: exact counts vary per model."""

from __future__ import annotations

import math
import re

_PIECES = re.compile(r'(?P<word>[A-Za-z]+)|(?P<digits>[0-9]+)|(?P<newline>\n)|(?P<other>[^\sA-Za-z0-9])')


def estimate_tokens(text: str) -> int:
    """Estimate tokens the way a tokenizer splits text, on the safe side.

    A flat ratio does not work here. English runs near 3.5 bytes per token, but the number
    tables on a dashboard run near 1.5, measured against Anthropic's token counting endpoint.
    Each word, group of digits, symbol and line counts separately. This is still an estimate:
    measured samples range from about 0.75 to 1.4 times the real count, so the context builder
    also keeps a margin. test_live_budget_holds checks real requests against the real endpoint.
    Pass count_tokens= to attach() for exact counts.
    """
    tokens = 0.0
    for match in _PIECES.finditer(text):
        kind = match.lastgroup
        if kind == 'word':
            tokens += 1 + (match.end() - match.start()) / 5
        elif kind == 'digits':
            tokens += 1 + (match.end() - match.start()) / 3
        elif kind == 'newline':
            tokens += 1
        else:
            tokens += 1.1
    return math.ceil(tokens)


def truncate_to_tokens(text: str, budget: int, count=estimate_tokens, notice: str = '\n[truncated to fit the budget]') -> str:
    """Cut text to fit a token budget, leaving a visible notice."""
    if budget <= 0:
        return ''
    if count(text) <= budget:
        return text
    room = budget - count(notice)
    if room <= 0:
        return ''
    cut = text
    while cut and count(cut) > room:
        cut = cut[: max(int(len(cut) * room / count(cut)) - 1, 0)]
    return cut + notice
