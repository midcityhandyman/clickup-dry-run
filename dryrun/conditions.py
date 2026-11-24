"""Trigger matching and condition evaluation. Pure functions, no state."""
from __future__ import annotations

from datetime import date
from typing import Any


def norm(value: Any) -> Any:
    """Case and whitespace insensitive form used for every comparison."""
    if isinstance(value, str):
        return value.strip().casefold()
    if isinstance(value, list):
        return [norm(v) for v in value]
    if isinstance(value, date):  # YAML reads an unquoted 2026-03-06 as a date
        return value.isoformat()
    return value


def get_field(task: dict[str, Any], name: str) -> Any:
    if name.startswith("custom."):
        return task.get("custom", {}).get(name[len("custom."):])
    return task.get(name)


def _is_set(actual: Any) -> bool:
    return actual not in (None, "", [])


def _equals(actual: Any, expected: Any) -> bool:
    if isinstance(actual, list):
        other = expected if isinstance(expected, list) else [expected]
        return sorted(map(str, actual)) == sorted(map(str, other))
    return actual == expected


def _in(actual: Any, expected: list[Any]) -> bool:
    if isinstance(actual, list):
        return any(item in expected for item in actual)
    return actual in expected


def _contains(actual: Any, expected: Any) -> bool:
    if isinstance(actual, list):
        return expected in actual
    if isinstance(actual, str):
        return str(expected) in actual
    return False


def _compare(actual: Any, expected: Any) -> int | None:
    """Return -1, 0 or 1, or None when the values cannot be ordered."""
    if not _is_set(actual) or expected is None or isinstance(actual, list):
        return None
    try:
        left, right = float(actual), float(expected)
    except (TypeError, ValueError):
        left, right = str(actual), str(expected)  # ISO dates order as strings
    return (left > right) - (left < right)


def evaluate(cond: dict[str, Any], task: dict[str, Any], today: str | None = None) -> bool:
    """Evaluate one condition. The value 'today' resolves to the event date."""
    actual = norm(get_field(task, cond["field"]))
    expected = cond.get("value")
    if expected == "today" and today:
        expected = today
    expected = norm(expected)
    op = cond["op"]
    if op == "is_set":
        return _is_set(actual)
    if op == "is_not_set":
        return not _is_set(actual)
    if op == "equals":
        return _equals(actual, expected)
    if op == "not_equals":
        return not _equals(actual, expected)
    if op == "in":
        return _in(actual, expected)
    if op == "not_in":
        return not _in(actual, expected)
    if op == "contains":
        return _contains(actual, expected)
    if op == "not_contains":
        return not _contains(actual, expected)
    order = _compare(actual, expected)
    if order is None:
        return False
    return {
        "gt": order > 0, "after": order > 0,
        "gte": order >= 0,
        "lt": order < 0, "before": order < 0,
        "lte": order <= 0,
    }[op]


def conditions_pass(
    conditions: list[dict[str, Any]], task: dict[str, Any], match: str = "all",
    today: str | None = None,
) -> bool:
    if not conditions:
        return True
    results = (evaluate(c, task, today) for c in conditions)
    return any(results) if match == "any" else all(results)


def trigger_matches(trigger: dict[str, Any], event_type: str, data: dict[str, Any]) -> bool:
    """A trigger matches when the type is equal and every given parameter agrees.

    A parameter may be a single value or a list of accepted values.
    """
    if trigger["type"] != event_type:
        return False
    for key, wanted in trigger.items():
        if key == "type" or wanted is None:
            continue
        actual = norm(data.get(key))
        accepted = norm(wanted if isinstance(wanted, list) else [wanted])
        if actual not in accepted:
            return False
    return True
