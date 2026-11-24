"""Replay events against a task snapshot and record what automations would do.

Two copies of the tasks are kept. `baseline` receives only the replayed events.
`final` receives the events plus every automation action. The difference between
the two is exactly what the automations would change.
"""
from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .actions import Change, apply_action
from .conditions import conditions_pass, norm, trigger_matches
from .models import Automation, TASK_FIELDS, TRIGGER_PARAMS


@dataclass
class Event:
    id: str
    type: str
    task_id: str
    at: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    depth: int = 0
    chain: tuple[tuple[str, str], ...] = ()  # (automation id, task id) that led here
    caused_by: str | None = None

    @property
    def day(self) -> str | None:
        return self.at[:10] if self.at else None


@dataclass
class Run:
    automation_id: str
    task_id: str
    event_id: str
    event_type: str
    depth: int
    caused_by: str | None
    changes: list[Change] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)

    @property
    def noop(self) -> bool:
        return not self.changes and not self.side_effects


@dataclass
class FieldDiff:
    field: str
    before: Any
    after: Any
    automations: list[str]


@dataclass
class Result:
    automations: list[Automation]
    baseline: dict[str, dict[str, Any]]
    final: dict[str, dict[str, Any]]
    runs: list[Run] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    events_replayed: int = 0
    event_days: list[str] = field(default_factory=list)

    def runs_by_automation(self) -> dict[str, list[Run]]:
        grouped: dict[str, list[Run]] = {a.id: [] for a in self.automations}
        for run in self.runs:
            grouped[run.automation_id].append(run)
        return grouped

    def task_diffs(self) -> dict[str, list[FieldDiff]]:
        """Net field changes per task that are attributable to automations."""
        diffs: dict[str, list[FieldDiff]] = {}
        for task_id, after in self.final.items():
            before = self.baseline[task_id]
            names = list(TASK_FIELDS) + [
                f"custom.{k}" for k in sorted(set(before["custom"]) | set(after["custom"]))
            ]
            rows = []
            for name in names:
                old = before["custom"].get(name[7:]) if name.startswith("custom.") else before[name]
                new = after["custom"].get(name[7:]) if name.startswith("custom.") else after[name]
                if old == new:
                    continue
                who: list[str] = []
                for run in self.runs:
                    if run.task_id == task_id and run.automation_id not in who and any(
                        c.field == name for c in run.changes
                    ):
                        who.append(run.automation_id)
                rows.append(FieldDiff(name, old, new, who))
            if rows:
                diffs[task_id] = rows
        return diffs

    def window_days(self) -> int:
        if not self.event_days:
            return 0
        first, last = min(self.event_days), max(self.event_days)
        return (date.fromisoformat(last) - date.fromisoformat(first)).days + 1

    def projected_monthly_runs(self) -> int | None:
        days = self.window_days()
        return round(len(self.runs) / days * 30) if days else None


def parse_events(raw_events: list[dict[str, Any]]) -> list[Event]:
    events = []
    for n, raw in enumerate(raw_events, 1):
        if not isinstance(raw, dict) or raw.get("type") not in TRIGGER_PARAMS:
            raise ValueError(f"event #{n}: unknown or missing type")
        if not raw.get("task_id"):
            raise ValueError(f"event #{n}: missing task_id")
        data = {k: v for k, v in raw.items() if k not in ("id", "type", "task_id", "at")}
        events.append(Event(str(raw.get("id") or f"ev{n}"), raw["type"], str(raw["task_id"]),
                            raw.get("at"), data))
    return sorted(events, key=lambda e: e.at or "")  # stable, undated first


def due_date_events(tasks: dict[str, dict[str, Any]], as_of: str) -> list[Event]:
    """One due_date_arrives event for every task due on `as_of` (YYYY-MM-DD)."""
    date.fromisoformat(as_of)
    return [
        Event(f"due-{task_id}", "due_date_arrives", task_id, f"{as_of}T00:00:00")
        for task_id, task in tasks.items()
        if (task.get("due_date") or "")[:10] == as_of
    ]


def apply_event(task: dict[str, Any], event: Event) -> None:
    """Apply the change an observed event describes to a task copy."""
    data = event.data
    if event.type == "status_changed":
        task["status"] = data.get("to")
    elif event.type == "priority_changed":
        task["priority"] = data.get("to")
    elif event.type == "moved_to_list":
        task["list"] = data.get("to")
    elif event.type == "custom_field_changed":
        task["custom"][data["field"]] = data.get("to")
    elif event.type in ("tag_added", "assignee_added"):
        key, item = ("tags", data.get("tag")) if event.type == "tag_added" else (
            "assignees", data.get("assignee"))
        if item is not None and norm(item) not in norm(task[key]):
            task[key] = task[key] + [item]


class Simulator:
    def __init__(self, automations: list[Automation], tasks: dict[str, dict[str, Any]],
                 max_depth: int = 5) -> None:
        self.automations = automations
        self.max_depth = max_depth
        self.result = Result(automations, copy.deepcopy(tasks), copy.deepcopy(tasks))

    def run(self, events: list[Event]) -> Result:
        res = self.result
        for event in events:
            if event.task_id not in res.final:
                res.warnings.append(
                    f"event {event.id} refers to task {event.task_id}, not in the export; skipped")
                continue
            apply_event(res.baseline[event.task_id], event)
            apply_event(res.final[event.task_id], event)
            res.events_replayed += 1
            if event.day:
                res.event_days.append(event.day)
            queue = deque([event])
            while queue:
                queue.extend(self._dispatch(queue.popleft()))
        return res

    def _dispatch(self, event: Event) -> list[Event]:
        """Fire every automation the event triggers; return follow-on events."""
        res = self.result
        task = res.final[event.task_id]
        follow_on: list[Event] = []
        for auto in self.automations:
            if not auto.enabled or not trigger_matches(auto.trigger, event.type, event.data):
                continue
            if not conditions_pass(auto.conditions, task, auto.match, event.day):
                continue
            if (auto.id, event.task_id) in event.chain:
                path = " -> ".join(a for a, _ in event.chain) + f" -> {auto.id}"
                res.warnings.append(
                    f"loop on task {event.task_id}: {path}; stopped, a live workspace may keep going")
                continue
            if event.depth >= self.max_depth:
                res.warnings.append(
                    f"chain on task {event.task_id} reached max depth {self.max_depth} at"
                    f" {auto.id}; stopped")
                continue
            run = Run(auto.id, event.task_id, event.id, event.type, event.depth, event.caused_by)
            for action in auto.actions:
                outcome = apply_action(action, task, event.day)
                run.changes.extend(outcome.changes)
                run.side_effects.extend(outcome.side_effects)
                for raw in outcome.events:
                    kind = raw.pop("type")
                    follow_on.append(Event(
                        f"{event.id}>{auto.id}.{len(follow_on) + 1}", kind, event.task_id,
                        event.at, raw, event.depth + 1,
                        event.chain + ((auto.id, event.task_id),), auto.id))
            res.runs.append(run)
        return follow_on


def simulate(automations: list[Automation], tasks: dict[str, dict[str, Any]],
             raw_events: list[dict[str, Any]], as_of: str | None = None,
             max_depth: int = 5) -> Result:
    """Convenience entry point used by the CLI, the demo and the tests."""
    events = parse_events(raw_events)
    if as_of:
        events += due_date_events(tasks, as_of)
    return Simulator(automations, tasks, max_depth).run(events)
