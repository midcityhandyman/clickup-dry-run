"""Command line entry point: python -m dryrun AUTOMATIONS EXPORT [options]."""
from __future__ import annotations

import argparse
import json
import os
import sys

from .models import ConfigError, load_automations, load_export
from .report import to_dict, to_text, usage
from .simulator import simulate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dryrun",
        description="Simulate ClickUp-style automations against an exported task JSON."
                    " Nothing is ever written to a workspace.",
    )
    parser.add_argument("automations", help="YAML file with trigger, conditions, actions")
    parser.add_argument("export", help="JSON export with tasks and, optionally, events")
    parser.add_argument("--events", help="JSON file with an events list; overrides the export's")
    parser.add_argument("--as-of", metavar="YYYY-MM-DD",
                        help="also fire due_date_arrives for tasks due on this date")
    parser.add_argument("--monthly-limit", type=int, default=None,
                        help="plan run allowance to compare against"
                             " (default: DRYRUN_MONTHLY_LIMIT)")
    parser.add_argument("--max-depth", type=int, default=5,
                        help="how many automations may chain off one event (default 5)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 on any warning or when the projection is over the limit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    limit = args.monthly_limit
    try:
        if limit is None and os.environ.get("DRYRUN_MONTHLY_LIMIT"):
            limit = int(os.environ["DRYRUN_MONTHLY_LIMIT"])
        automations = load_automations(args.automations)
        tasks, raw_events = load_export(args.export)
        if args.events:
            with open(args.events, encoding="utf-8") as handle:
                loaded = json.load(handle)
            raw_events = loaded["events"] if isinstance(loaded, dict) else loaded
        result = simulate(automations, tasks, raw_events, args.as_of, args.max_depth)
    except (ConfigError, ValueError, KeyError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(to_dict(result, limit), indent=2))
    else:
        sys.stdout.write(to_text(result, limit))
    if args.strict and (result.warnings or usage(result, limit)["over_limit"]):
        return 1
    return 0
