"""Statistics computed in Python, so that the model narrates numbers it did not have to add up."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from typing import Any


def as_number(value: Any) -> float | None:
    """Return a finite number, or None for anything else, including booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def format_number(value: Any) -> str:
    number = as_number(value)
    if number is None:
        return str(value)
    return str(int(number)) if number == int(number) and abs(number) < 1e15 else f'{number:.10g}'


def column_stats(rows: Iterable[dict[str, Any]], column: str) -> dict[str, Any]:
    """Describe one column: numeric statistics, or the most common values."""
    numbers: list[float] = []
    others: Counter[str] = Counter()
    missing = 0
    for row in rows:
        value = row.get(column)
        number = as_number(value)
        if number is not None:
            numbers.append(number)
        elif value is None or value == '':
            missing += 1
        else:
            others[str(value)] += 1
    if numbers and len(numbers) >= sum(others.values()):
        return {'type': 'number', 'count': len(numbers), 'missing': missing + sum(others.values()),
                'min': min(numbers), 'max': max(numbers), 'mean': sum(numbers) / len(numbers), 'sum': sum(numbers)}
    return {'type': 'text', 'count': sum(others.values()), 'missing': missing + len(numbers),
            'distinct': len(others), 'top': others.most_common(5)}


def summarize_series(y: list[Any], x: list[Any] | None = None, *, sketch_points: int = 12) -> dict[str, Any]:
    """Describe a series by its shape, extremes and trend, plus a small extrema-preserving sketch."""
    points = [(index, number) for index, value in enumerate(y) if (number := as_number(value)) is not None]
    if not points:
        return {'count': len(y), 'numeric': 0}

    def x_at(index: int) -> Any:
        return x[index] if x is not None and index < len(x) else index

    values = [number for _, number in points]
    low_index, low = min(points, key=lambda point: point[1])
    high_index, high = max(points, key=lambda point: point[1])
    first, last = values[0], values[-1]
    summary: dict[str, Any] = {
        'count': len(y),
        'numeric': len(values),
        'min': low,
        'min_at': x_at(low_index),
        'max': high,
        'max_at': x_at(high_index),
        'mean': sum(values) / len(values),
        'first': first,
        'first_at': x_at(points[0][0]),
        'last': last,
        'last_at': x_at(points[-1][0]),
        'change_percent': (last - first) / abs(first) * 100 if first else None,
        'trend': _trend(values),
    }
    if sketch_points > 0:
        summary['sketch'] = [(x_at(index), number) for index, number in _sketch(points, sketch_points)]
    return summary


def _trend(values: list[float]) -> str:
    """Name the direction from a least-squares fit, relative to the range of the data."""
    count = len(values)
    if count < 2:
        return 'flat'
    mean_x = (count - 1) / 2
    mean_y = sum(values) / count
    numerator = sum((index - mean_x) * (value - mean_y) for index, value in enumerate(values))
    denominator = sum((index - mean_x) ** 2 for index in range(count))
    spread = max(values) - min(values)
    if not denominator or not spread:
        return 'flat'
    fitted_change = numerator / denominator * (count - 1)
    if abs(fitted_change) < 0.1 * spread:
        return 'flat'
    return 'rising' if fitted_change > 0 else 'falling'


def _sketch(points: list[tuple[int, float]], limit: int) -> list[tuple[int, float]]:
    """Keep the low and high of each bucket, so that peaks survive downsampling."""
    if len(points) <= limit:
        return points
    buckets = max(limit // 2, 1)
    size = len(points) / buckets
    kept: list[tuple[int, float]] = []
    for bucket in range(buckets):
        part = points[int(bucket * size):int((bucket + 1) * size)]
        if not part:
            continue
        low, high = min(part, key=lambda p: p[1]), max(part, key=lambda p: p[1])
        kept.extend(sorted({low, high}))
    return kept
