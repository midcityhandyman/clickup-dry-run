"""Render a simulation Result as plain text or as a JSON-ready dict."""
from __future__ import annotations

from typing import Any

from .simulator import Result


def show(value: Any) -> str:
    if value is None or value == "":
        return "(none)"
    if isinstance(value, list):
        return "[" + ", ".join(map(str, value)) + "]" if value else "(none)"
    return str(value)


def usage(result: Result, monthly_limit: int | None) -> dict[str, Any]:
    projected = result.projected_monthly_runs()
    info: dict[str, Any] = {
        "total_runs": len(result.runs),
        "noop_runs": sum(1 for r in result.runs if r.noop),
        "chained_runs": sum(1 for r in result.runs if r.depth > 0),
        "window_days": result.window_days(),
        "projected_30_day_runs": projected,
        "monthly_limit": monthly_limit,
        "over_limit": bool(monthly_limit is not None and projected is not None
                           and projected > monthly_limit),
    }
    if monthly_limit and projected is not None:
        info["percent_of_limit"] = round(projected / monthly_limit * 100, 1)
    return info


def to_dict(result: Result, monthly_limit: int | None = None) -> dict[str, Any]:
    return {
        "summary": {
            "tasks": len(result.final),
            "events_replayed": result.events_replayed,
            "automations": len(result.automations),
            "automations_disabled": sum(1 for a in result.automations if not a.enabled),
            "tasks_changed": len(result.task_diffs()),
        },
        "usage": usage(result, monthly_limit),
        "runs_by_automation": {k: len(v) for k, v in result.runs_by_automation().items()},
        "runs": [
            {
                "automation": r.automation_id, "task": r.task_id, "event": r.event_id,
                "event_type": r.event_type, "depth": r.depth, "caused_by": r.caused_by,
                "noop": r.noop, "side_effects": r.side_effects,
                "changes": [{"field": c.field, "before": c.before, "after": c.after}
                            for c in r.changes],
            }
            for r in result.runs
        ],
        "task_changes": {
            task_id: [{"field": d.field, "before": d.before, "after": d.after,
                       "automations": d.automations} for d in rows]
            for task_id, rows in result.task_diffs().items()
        },
        "warnings": result.warnings,
    }


def to_text(result: Result, monthly_limit: int | None = None) -> str:
    lines: list[str] = []
    add = lines.append
    disabled = sum(1 for a in result.automations if not a.enabled)
    diffs = result.task_diffs()

    add("DRY RUN: nothing was sent anywhere. All changes below are simulated.")
    add("=" * 68)
    add(f"Tasks in export: {len(result.final)}   Events replayed: {result.events_replayed}"
        f"   Automations: {len(result.automations)} ({disabled} disabled)")
    add("")

    add("Runs by automation")
    grouped = result.runs_by_automation()
    width = max((len(a.id) for a in result.automations), default=10)
    for auto in result.automations:
        runs = grouped[auto.id]
        if not auto.enabled:
            note = "disabled, never fires"
        else:
            note = f"{len(runs)} run{'s' if len(runs) != 1 else ''}"
            noops = sum(1 for r in runs if r.noop)
            chained = sum(1 for r in runs if r.depth > 0)
            extras = [f"{noops} changed nothing"] if noops else []
            extras += [f"{chained} fired by another automation"] if chained else []
            if extras:
                note += " (" + ", ".join(extras) + ")"
        add(f"  {auto.id.ljust(width)}  {note}")
    add("")

    add(f"Tasks that would change: {len(diffs)} of {len(result.final)}")
    for task_id, rows in diffs.items():
        add(f"  {task_id}  {result.final[task_id]['name']}")
        fwidth = max(len(d.field) for d in rows)
        for d in rows:
            add(f"    {d.field.ljust(fwidth)}  {show(d.before)} -> {show(d.after)}"
                f"   [{', '.join(d.automations)}]")
    add("")

    effects = [(r, e) for r in result.runs for e in r.side_effects]
    add(f"Side effects that would be created: {len(effects)}")
    for run, effect in effects:
        add(f"  {run.task_id}  {effect}   [{run.automation_id}]")
    add("")

    add("Run log (in firing order)")
    for n, r in enumerate(result.runs, 1):
        cause = f" <- {r.caused_by}" if r.caused_by else ""
        if r.noop:
            what = "no change"
        elif not r.changes:
            what = f"{len(r.side_effects)} side effect(s) only"
        else:
            what = f"{len(r.changes)} field change(s)"
        add(f"  {n:>3}. {r.automation_id} on {r.task_id} via {r.event_type}{cause}: {what}")
    add("")

    add(f"Warnings: {len(result.warnings)}")
    for warning in result.warnings:
        add(f"  ! {warning}")
    add("")

    use = usage(result, monthly_limit)
    add("Automation usage")
    add(f"  Runs this replay:                {use['total_runs']}")
    add(f"  Runs that change nothing:        {use['noop_runs']}")
    add(f"  Runs fired by other automations: {use['chained_runs']}")
    if use["window_days"]:
        add(f"  Event window:                    {use['window_days']} day(s)")
        add(f"  Projected over 30 days:          {use['projected_30_day_runs']}")
    if monthly_limit:
        if "percent_of_limit" in use:
            verdict = "OVER LIMIT" if use["over_limit"] else "within limit"
            add(f"  Monthly limit:                   {monthly_limit}"
                f" ({use['percent_of_limit']}% used at this rate, {verdict})")
        else:
            add(f"  Monthly limit:                   {monthly_limit} (no dated events, cannot project)")
    return "\n".join(lines) + "\n"
