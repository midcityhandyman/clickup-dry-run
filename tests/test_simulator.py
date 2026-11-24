import copy

import pytest

from dryrun.simulator import simulate
from tests.helpers import auto, autos, tasks

BASE = {"id": "T-1", "name": "Sample job", "status": "new", "priority": "normal",
        "list": "Intake", "due_date": "2026-03-06", "custom": {"Estimate": 100}}


def status_event(to, task_id="T-1", at="2026-03-02T09:00:00"):
    return {"type": "status_changed", "task_id": task_id, "at": at, "to": to}


def test_run_changes_task_and_leaves_input_untouched():
    snapshot = tasks(BASE)
    original = copy.deepcopy(snapshot)
    rules = autos(auto("review", {"type": "status_changed", "to": "in review"}, [
        {"type": "add_assignee", "assignee": "Riley Example"},
        {"type": "set_due_date", "days_from_trigger": 2},
    ]))
    result = simulate(rules, snapshot, [status_event("in review")])
    assert snapshot == original                       # nothing mutated in place
    assert len(result.runs) == 1
    assert result.final["T-1"]["assignees"] == ["Riley Example"]
    assert result.final["T-1"]["due_date"] == "2026-03-04"
    diff = {d.field: (d.before, d.after, d.automations) for d in result.task_diffs()["T-1"]}
    assert diff["due_date"] == ("2026-03-06", "2026-03-04", ["review"])
    # the status change came from the event, not an automation, so it is not in the diff
    assert "status" not in diff


def test_conditions_gate_the_run():
    rules = autos(auto("paid", {"type": "status_changed", "to": "complete"},
                       [{"type": "move_to_list", "to": "Invoicing"}],
                       [{"field": "custom.Estimate", "op": "gt", "value": 0}]))
    free = dict(BASE, id="T-2", custom={"Estimate": 0})
    result = simulate(rules, tasks(BASE, free),
                      [status_event("complete"), status_event("complete", "T-2")])
    assert [r.task_id for r in result.runs] == ["T-1"]
    assert list(result.task_diffs()) == ["T-1"]


def test_chained_automations_count_as_extra_runs():
    rules = autos(
        auto("to-invoicing", {"type": "status_changed", "to": "complete"},
             [{"type": "move_to_list", "to": "Invoicing"}]),
        auto("on-arrival", {"type": "moved_to_list", "to": "Invoicing"},
             [{"type": "set_custom_field", "field": "Invoice Status", "value": "draft"},
              {"type": "create_subtask", "name": "Invoice {{task.name}}"}]),
    )
    result = simulate(rules, tasks(BASE), [status_event("complete")])
    assert [(r.automation_id, r.depth, r.caused_by) for r in result.runs] == [
        ("to-invoicing", 0, None), ("on-arrival", 1, "to-invoicing")]
    assert result.final["T-1"]["custom"]["Invoice Status"] == "draft"
    assert result.runs[1].side_effects == ['subtask: "Invoice Sample job"']


def test_noop_run_still_consumes_a_run():
    already = dict(BASE, tags=["escalated"])
    rules = autos(auto("tagger", {"type": "priority_changed", "to": "urgent"},
                       [{"type": "add_tag", "tag": "Escalated"}]))
    event = {"type": "priority_changed", "task_id": "T-1", "to": "urgent"}
    result = simulate(rules, tasks(already), [event])
    assert len(result.runs) == 1 and result.runs[0].noop
    assert result.task_diffs() == {}


def test_ping_pong_loop_is_detected_and_stopped():
    rules = autos(
        auto("ping", {"type": "status_changed", "to": "open"},
             [{"type": "change_status", "to": "blocked"}]),
        auto("pong", {"type": "status_changed", "to": "blocked"},
             [{"type": "change_status", "to": "open"}]),
    )
    result = simulate(rules, tasks(BASE), [status_event("open")])
    assert [r.automation_id for r in result.runs] == ["ping", "pong"]
    assert len(result.warnings) == 1 and "loop on task T-1: ping -> pong -> ping" in result.warnings[0]


def test_max_depth_stops_long_chains():
    steps = ["a", "b", "c", "d"]
    rules = autos(*[
        auto(f"step-{s}", {"type": "status_changed", "to": s},
             [{"type": "change_status", "to": steps[i + 1] if i + 1 < len(steps) else "end"}])
        for i, s in enumerate(steps)
    ])
    result = simulate(rules, tasks(BASE), [status_event("a")], max_depth=2)
    assert [r.automation_id for r in result.runs] == ["step-a", "step-b"]
    assert "max depth 2" in result.warnings[0]


def test_disabled_automation_never_fires():
    rules = autos(auto("off", {"type": "status_changed"}, [{"type": "add_tag", "tag": "x"}],
                       enabled=False))
    result = simulate(rules, tasks(BASE), [status_event("complete")])
    assert result.runs == [] and result.runs_by_automation() == {"off": []}


def test_as_of_fires_due_date_trigger_only_for_matching_open_tasks():
    rules = autos(auto("nudge", {"type": "due_date_arrives"},
                       [{"type": "change_priority", "to": "high"}],
                       [{"field": "status", "op": "not_equals", "value": "complete"}]))
    later = dict(BASE, id="T-2", due_date="2026-03-09")
    done = dict(BASE, id="T-3", status="complete")
    result = simulate(rules, tasks(BASE, later, done), [], as_of="2026-03-06")
    assert [r.task_id for r in result.runs] == ["T-1"]
    assert result.events_replayed == 2  # T-1 and T-3 are both due that day


def test_unknown_task_is_warned_and_skipped():
    rules = autos(auto("any", {"type": "status_changed"}, [{"type": "add_tag", "tag": "x"}]))
    result = simulate(rules, tasks(BASE), [status_event("complete", "T-404")])
    assert result.runs == [] and "T-404" in result.warnings[0]


def test_bad_event_is_rejected():
    with pytest.raises(ValueError, match="unknown or missing type"):
        simulate([], tasks(BASE), [{"type": "exploded", "task_id": "T-1"}])


def test_projection_scales_window_to_thirty_days():
    rules = autos(auto("any", {"type": "status_changed"}, [{"type": "add_tag", "tag": "x"}]))
    events = [status_event("a", at="2026-03-02T09:00:00"),
              status_event("b", at="2026-03-04T09:00:00")]
    result = simulate(rules, tasks(BASE), events)
    assert result.window_days() == 3
    assert result.projected_monthly_runs() == 20  # 2 runs in 3 days


def test_as_of_uses_due_dates_as_they_stand_after_the_replay():
    rules = autos(
        auto("review", {"type": "status_changed", "to": "in review"},
             [{"type": "set_due_date", "days_from_trigger": 2}]),
        auto("nudge", {"type": "due_date_arrives"}, [{"type": "add_tag", "tag": "due"}]),
    )
    events = [status_event("in review")]  # 2026-03-02, so the due date moves to 03-04
    moved_to = simulate(rules, tasks(BASE), events, as_of="2026-03-04")
    assert [r.automation_id for r in moved_to.runs] == ["review", "nudge"]
    stale = simulate(rules, tasks(BASE), events, as_of="2026-03-06")  # the snapshot date
    assert [r.automation_id for r in stale.runs] == ["review"]


def test_status_event_without_from_takes_it_from_the_task():
    rules = autos(auto("reopen", {"type": "status_changed", "from": "new", "to": "open"},
                       [{"type": "add_tag", "tag": "x"}]))
    result = simulate(rules, tasks(BASE), [status_event("open"), status_event("open")])
    assert len(result.runs) == 1  # the second event goes open -> open, so `from: new` fails


def test_custom_field_event_without_field_is_rejected():
    with pytest.raises(ValueError, match="custom_field_changed needs a 'field'"):
        simulate([], tasks(BASE), [{"type": "custom_field_changed", "task_id": "T-1", "to": 1}])
