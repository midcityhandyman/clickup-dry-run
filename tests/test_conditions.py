import pytest

from dryrun.conditions import conditions_pass, evaluate, trigger_matches
from dryrun.models import normalise_task

TASK = normalise_task({
    "id": "T-1", "name": "Sample job: fix gate", "status": "In Progress", "priority": "high",
    "assignees": ["Alex Sample"], "tags": ["triage", "outdoor"], "list": "Scheduled Jobs",
    "due_date": "2026-03-06", "custom": {"Estimate": 250, "Region": "North"},
})


@pytest.mark.parametrize("cond,expected", [
    ({"field": "status", "op": "equals", "value": "in progress"}, True),   # case insensitive
    ({"field": "status", "op": "not_equals", "value": "complete"}, True),
    ({"field": "priority", "op": "in", "value": ["urgent", "high"]}, True),
    ({"field": "priority", "op": "not_in", "value": ["urgent", "high"]}, False),
    ({"field": "tags", "op": "contains", "value": "Outdoor"}, True),
    ({"field": "tags", "op": "not_contains", "value": "indoor"}, True),
    ({"field": "tags", "op": "in", "value": ["indoor", "triage"]}, True),
    ({"field": "tags", "op": "equals", "value": ["outdoor", "triage"]}, True),
    ({"field": "name", "op": "contains", "value": "gate"}, True),
    ({"field": "custom.Estimate", "op": "gt", "value": 100}, True),
    ({"field": "custom.Estimate", "op": "lte", "value": 100}, False),
    ({"field": "custom.Region", "op": "equals", "value": "north"}, True),
    ({"field": "custom.Missing", "op": "is_not_set"}, True),
    ({"field": "custom.Missing", "op": "gt", "value": 1}, False),
    ({"field": "assignees", "op": "is_set"}, True),
    ({"field": "due_date", "op": "before", "value": "2026-03-10"}, True),
    ({"field": "due_date", "op": "after", "value": "2026-03-10"}, False),
])
def test_evaluate(cond, expected):
    assert evaluate(cond, TASK) is expected


def test_today_resolves_to_event_date():
    cond = {"field": "due_date", "op": "lte", "value": "today"}
    assert evaluate(cond, TASK, today="2026-03-06") is True
    assert evaluate(cond, TASK, today="2026-03-05") is False


def test_match_all_versus_any():
    conds = [{"field": "priority", "op": "equals", "value": "low"},
             {"field": "list", "op": "equals", "value": "Scheduled Jobs"}]
    assert conditions_pass(conds, TASK, "all") is False
    assert conditions_pass(conds, TASK, "any") is True
    assert conditions_pass([], TASK) is True


def test_trigger_matching():
    trig = {"type": "status_changed", "to": ["In Review", "complete"], "from": "in progress"}
    assert trigger_matches(trig, "status_changed", {"from": "In Progress", "to": "complete"})
    assert not trigger_matches(trig, "status_changed", {"from": "new", "to": "complete"})
    assert not trigger_matches(trig, "priority_changed", {"to": "complete"})
    assert trigger_matches({"type": "status_changed"}, "status_changed", {"to": "anything"})


def test_unquoted_yaml_dates_compare_as_iso_strings():
    import yaml
    conds = yaml.safe_load("""
- {field: due_date, op: equals, value: 2026-03-06}
- {field: due_date, op: in, value: [2026-03-06]}
- {field: due_date, op: before, value: 2026-03-07}
""")
    assert all(not isinstance(c["value"], str) for c in conds[::2])  # really parsed as dates
    assert conditions_pass(conds, TASK, "all") is True
