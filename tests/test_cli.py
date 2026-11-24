import json

from dryrun.cli import main

AUTOS, EXPORT = "examples/automations.yaml", "examples/export.json"


def test_text_report_on_examples(capsys):
    assert main([AUTOS, EXPORT, "--as-of", "2026-03-06", "--monthly-limit", "100"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("DRY RUN")
    assert "Tasks that would change: 8 of 12" in out
    assert "legacy-auto-close      disabled, never fires" in out
    assert "within limit" in out


def test_json_report_and_usage_numbers(capsys):
    assert main([AUTOS, EXPORT, "--as-of", "2026-03-06", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["usage"]["total_runs"] == 12 == len(data["runs"])
    assert data["usage"]["noop_runs"] == 1
    assert data["runs_by_automation"]["urgent-escalation"] == 3
    assert data["task_changes"]["T-1006"][1] == {
        "field": "list", "before": "Scheduled Jobs", "after": "Invoicing",
        "automations": ["complete-to-invoicing"]}


def test_strict_fails_on_warning_and_on_limit(capsys):
    assert main([AUTOS, EXPORT, "--strict"]) == 1          # export has one orphan event
    assert main([AUTOS, EXPORT, "--monthly-limit", "10"]) == 0
    assert "OVER LIMIT" in capsys.readouterr().out


def test_limit_from_environment(capsys, monkeypatch):
    monkeypatch.setenv("DRYRUN_MONTHLY_LIMIT", "500")
    assert main([AUTOS, EXPORT]) == 0
    assert "Monthly limit:                   500" in capsys.readouterr().out


def test_events_file_override(tmp_path, capsys):
    events = tmp_path / "events.json"
    events.write_text(json.dumps([{"type": "task_created", "task_id": "T-1009"}]))
    assert main([AUTOS, EXPORT, "--events", str(events), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["usage"]["total_runs"] == 1 and data["usage"]["projected_30_day_runs"] is None


def test_bad_input_exits_2(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("automations:\n  - id: x\n    trigger: {type: nope}\n    actions: []\n")
    assert main([str(bad), EXPORT]) == 2
    assert "unknown trigger type" in capsys.readouterr().err
    assert main([AUTOS, str(tmp_path / "missing.json")]) == 2
