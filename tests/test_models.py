import pytest

from dryrun.models import ConfigError, load_automations, load_export, parse_automations, parse_export
from tests.helpers import auto

OK_ACTION = [{"type": "add_tag", "tag": "x"}]


def test_example_files_load():
    automations = load_automations("examples/automations.yaml")
    tasks, events = load_export("examples/export.json")
    assert len(automations) == 8
    assert sum(1 for a in automations if not a.enabled) == 1
    assert len(tasks) == 12 and len(events) == 10


@pytest.mark.parametrize("raw,message", [
    (auto("a", {"type": "teleported"}, OK_ACTION), "unknown trigger type"),
    (auto("a", {"type": "task_created", "to": "x"}, OK_ACTION), "does not accept"),
    (auto("a", {"type": "custom_field_changed"}, OK_ACTION), "requires"),
    (auto("a", {"type": "task_created"}, []), "at least one action"),
    (auto("a", {"type": "task_created"}, [{"type": "launch_rocket"}]), "action type"),
    (auto("a", {"type": "task_created"}, [{"type": "add_tag"}]), "requires"),
    (auto("a", {"type": "task_created"}, [{"type": "set_due_date"}]), "exactly one"),
    (auto("a", {"type": "task_created"}, OK_ACTION,
          [{"field": "colour", "op": "equals", "value": 1}]), "unknown field"),
    (auto("a", {"type": "task_created"}, OK_ACTION,
          [{"field": "status", "op": "resembles", "value": 1}]), "unknown op"),
    (auto("a", {"type": "task_created"}, OK_ACTION,
          [{"field": "status", "op": "in", "value": "new"}]), "needs a list"),
    (auto("a", {"type": "task_created"}, OK_ACTION, match="some"), "all or any"),
])
def test_bad_automations_are_rejected(raw, message):
    with pytest.raises(ConfigError, match=message):
        parse_automations({"automations": [raw]})


def test_duplicate_ids_rejected():
    one = auto("same", {"type": "task_created"}, OK_ACTION)
    with pytest.raises(ConfigError, match="duplicate automation id"):
        parse_automations({"automations": [one, dict(one)]})


def test_export_validation():
    with pytest.raises(ConfigError, match="tasks"):
        parse_export({"items": []})
    with pytest.raises(ConfigError, match="duplicate task id"):
        parse_export({"tasks": [{"id": "T-1"}, {"id": "T-1"}]})
    tasks, events = parse_export({"tasks": [{"id": "T-1"}]})
    assert tasks["T-1"]["tags"] == [] and tasks["T-1"]["custom"] == {} and events == []
