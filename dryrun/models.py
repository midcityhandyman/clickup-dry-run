"""Loading and validating automation definitions and task exports."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when an automation file or export is malformed."""


# trigger type -> parameters it may carry (all optional unless listed in REQUIRED)
TRIGGER_PARAMS: dict[str, set[str]] = {
    "task_created": set(),
    "status_changed": {"from", "to"},
    "priority_changed": {"to"},
    "tag_added": {"tag"},
    "assignee_added": {"assignee"},
    "custom_field_changed": {"field", "to"},
    "moved_to_list": {"to"},
    "due_date_arrives": set(),
}
TRIGGER_REQUIRED: dict[str, set[str]] = {"custom_field_changed": {"field"}}

# action type -> (required params, optional params)
ACTION_PARAMS: dict[str, tuple[set[str], set[str]]] = {
    "change_status": ({"to"}, set()),
    "change_priority": ({"to"}, set()),
    "add_tag": ({"tag"}, set()),
    "remove_tag": ({"tag"}, set()),
    "add_assignee": ({"assignee"}, set()),
    "remove_assignee": ({"assignee"}, set()),
    "set_custom_field": ({"field", "value"}, set()),
    "set_due_date": (set(), {"date", "days_from_trigger"}),
    "move_to_list": ({"to"}, set()),
    "add_comment": ({"text"}, set()),
    "create_subtask": ({"name"}, set()),
}

CONDITION_OPS = {
    "equals", "not_equals", "in", "not_in", "contains", "not_contains",
    "is_set", "is_not_set", "gt", "gte", "lt", "lte", "before", "after",
}
OPS_WITHOUT_VALUE = {"is_set", "is_not_set"}
OPS_NEEDING_LIST = {"in", "not_in"}

TASK_FIELDS = ("name", "status", "priority", "assignees", "tags", "list", "due_date")


@dataclass
class Automation:
    id: str
    name: str
    trigger: dict[str, Any]
    conditions: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    match: str = "all"
    enabled: bool = True


def _check_field_name(name: Any, where: str) -> None:
    if not isinstance(name, str) or not (
        name in TASK_FIELDS or (name.startswith("custom.") and len(name) > 7)
    ):
        raise ConfigError(
            f"{where}: unknown field {name!r}; use one of {', '.join(TASK_FIELDS)} or custom.<name>"
        )


def parse_automation(raw: Any, index: int) -> Automation:
    where = f"automation #{index + 1}"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: expected a mapping")
    auto_id = raw.get("id")
    if not isinstance(auto_id, str) or not auto_id:
        raise ConfigError(f"{where}: missing 'id'")
    where = f"automation {auto_id!r}"

    trigger = raw.get("trigger")
    if not isinstance(trigger, dict) or "type" not in trigger:
        raise ConfigError(f"{where}: 'trigger' must be a mapping with a 'type'")
    ttype = trigger["type"]
    if ttype not in TRIGGER_PARAMS:
        raise ConfigError(f"{where}: unknown trigger type {ttype!r}")
    params = set(trigger) - {"type"}
    extra = params - TRIGGER_PARAMS[ttype]
    if extra:
        raise ConfigError(f"{where}: trigger {ttype} does not accept {sorted(extra)}")
    missing = TRIGGER_REQUIRED.get(ttype, set()) - params
    if missing:
        raise ConfigError(f"{where}: trigger {ttype} requires {sorted(missing)}")

    conditions = raw.get("conditions") or []
    if not isinstance(conditions, list):
        raise ConfigError(f"{where}: 'conditions' must be a list")
    for n, cond in enumerate(conditions, 1):
        cwhere = f"{where} condition #{n}"
        if not isinstance(cond, dict):
            raise ConfigError(f"{cwhere}: expected a mapping")
        _check_field_name(cond.get("field"), cwhere)
        op = cond.get("op")
        if op not in CONDITION_OPS:
            raise ConfigError(f"{cwhere}: unknown op {op!r}")
        if op not in OPS_WITHOUT_VALUE and "value" not in cond:
            raise ConfigError(f"{cwhere}: op {op} needs a 'value'")
        if op in OPS_NEEDING_LIST and not isinstance(cond.get("value"), list):
            raise ConfigError(f"{cwhere}: op {op} needs a list 'value'")

    actions = raw.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ConfigError(f"{where}: needs at least one action")
    for n, action in enumerate(actions, 1):
        awhere = f"{where} action #{n}"
        if not isinstance(action, dict) or action.get("type") not in ACTION_PARAMS:
            raise ConfigError(f"{awhere}: unknown or missing action type")
        required, optional = ACTION_PARAMS[action["type"]]
        params = set(action) - {"type"}
        if required - params:
            raise ConfigError(f"{awhere}: {action['type']} requires {sorted(required - params)}")
        if params - required - optional:
            raise ConfigError(
                f"{awhere}: {action['type']} does not accept {sorted(params - required - optional)}"
            )
        if action["type"] == "set_due_date" and len(params) != 1:
            raise ConfigError(f"{awhere}: set_due_date needs exactly one of date, days_from_trigger")

    match = raw.get("match", "all")
    if match not in ("all", "any"):
        raise ConfigError(f"{where}: 'match' must be all or any")

    return Automation(
        id=auto_id,
        name=str(raw.get("name") or auto_id),
        trigger=dict(trigger),
        conditions=[dict(c) for c in conditions],
        actions=[dict(a) for a in actions],
        match=match,
        enabled=bool(raw.get("enabled", True)),
    )


def parse_automations(doc: Any) -> list[Automation]:
    if not isinstance(doc, dict) or not isinstance(doc.get("automations"), list):
        raise ConfigError("automation file must have a top level 'automations' list")
    autos = [parse_automation(raw, i) for i, raw in enumerate(doc["automations"])]
    seen: set[str] = set()
    for auto in autos:
        if auto.id in seen:
            raise ConfigError(f"duplicate automation id {auto.id!r}")
        seen.add(auto.id)
    return autos


def load_automations(path: str | Path) -> list[Automation]:
    with open(path, encoding="utf-8") as handle:
        try:
            doc = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    return parse_automations(doc)


def normalise_task(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw.get("id"):
        raise ConfigError("every task in the export needs an 'id'")
    return {
        "id": str(raw["id"]),
        "name": raw.get("name", ""),
        "status": raw.get("status"),
        "priority": raw.get("priority"),
        "assignees": list(raw.get("assignees") or []),
        "tags": list(raw.get("tags") or []),
        "list": raw.get("list"),
        "due_date": raw.get("due_date"),
        "custom": dict(raw.get("custom") or {}),
    }


def parse_export(doc: Any) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Return (tasks by id, raw events) from an export document."""
    if not isinstance(doc, dict) or not isinstance(doc.get("tasks"), list):
        raise ConfigError("export must be a JSON object with a 'tasks' list")
    tasks: dict[str, dict[str, Any]] = {}
    for raw in doc["tasks"]:
        task = normalise_task(raw)
        if task["id"] in tasks:
            raise ConfigError(f"duplicate task id {task['id']!r} in export")
        tasks[task["id"]] = task
    events = doc.get("events") or []
    if not isinstance(events, list):
        raise ConfigError("'events' in the export must be a list")
    return tasks, events


def load_export(path: str | Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    with open(path, encoding="utf-8") as handle:
        try:
            doc = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path}: invalid JSON: {exc}") from exc
    return parse_export(doc)
