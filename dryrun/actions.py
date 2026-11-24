"""Apply actions to an in-memory task copy. Nothing here talks to a network."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .conditions import get_field, norm


@dataclass
class Change:
    field: str
    before: Any
    after: Any


@dataclass
class Outcome:
    changes: list[Change] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)  # follow-on events


_TEMPLATE = re.compile(r"\{\{\s*task\.([\w. ]+?)\s*\}\}")


def render(text: str, task: dict[str, Any]) -> str:
    """Fill {{task.field}} placeholders, for example {{task.name}}."""
    def repl(match: re.Match[str]) -> str:
        value = get_field(task, match.group(1)) if match.group(1) != "id" else task["id"]
        if isinstance(value, list):
            return ", ".join(map(str, value))
        return "" if value is None else str(value)
    return _TEMPLATE.sub(repl, str(text))


def _set_scalar(task: dict[str, Any], name: str, value: Any, out: Outcome) -> bool:
    before = task.get(name)
    if norm(before) == norm(value):
        return False
    task[name] = value
    out.changes.append(Change(name, before, value))
    return True


def _edit_list(task: dict[str, Any], name: str, item: str, add: bool, out: Outcome) -> bool:
    before = list(task[name])
    present = norm(item) in norm(before)
    if present == add:
        return False
    after = before + [item] if add else [v for v in before if norm(v) != norm(item)]
    task[name] = after
    out.changes.append(Change(name, before, after))
    return True


def apply_action(action: dict[str, Any], task: dict[str, Any], event_date: str | None) -> Outcome:
    """Mutate `task` as the action would and describe what happened."""
    out = Outcome()
    kind = action["type"]
    if kind == "change_status":
        before = task.get("status")
        if _set_scalar(task, "status", action["to"], out):
            out.events.append({"type": "status_changed", "from": before, "to": action["to"]})
    elif kind == "change_priority":
        if _set_scalar(task, "priority", action["to"], out):
            out.events.append({"type": "priority_changed", "to": action["to"]})
    elif kind == "add_tag":
        if _edit_list(task, "tags", action["tag"], True, out):
            out.events.append({"type": "tag_added", "tag": action["tag"]})
    elif kind == "remove_tag":
        _edit_list(task, "tags", action["tag"], False, out)
    elif kind == "add_assignee":
        if _edit_list(task, "assignees", action["assignee"], True, out):
            out.events.append({"type": "assignee_added", "assignee": action["assignee"]})
    elif kind == "remove_assignee":
        _edit_list(task, "assignees", action["assignee"], False, out)
    elif kind == "set_custom_field":
        name, value = action["field"], action["value"]
        before = task["custom"].get(name)
        if norm(before) != norm(value):
            task["custom"][name] = value
            out.changes.append(Change(f"custom.{name}", before, value))
            out.events.append({"type": "custom_field_changed", "field": name, "to": value})
    elif kind == "set_due_date":
        if "date" in action:
            target = str(action["date"])
        elif event_date:
            target = (date.fromisoformat(event_date)
                      + timedelta(days=int(action["days_from_trigger"]))).isoformat()
        else:
            out.side_effects.append("set_due_date skipped: triggering event has no date")
            return out
        _set_scalar(task, "due_date", target, out)
    elif kind == "move_to_list":
        if _set_scalar(task, "list", action["to"], out):
            out.events.append({"type": "moved_to_list", "to": action["to"]})
    elif kind == "add_comment":
        out.side_effects.append(f'comment: "{render(action["text"], task)}"')
    elif kind == "create_subtask":
        out.side_effects.append(f'subtask: "{render(action["name"], task)}"')
    else:  # validated at load time, kept as a guard for direct callers
        raise ValueError(f"unknown action type {kind!r}")
    return out
