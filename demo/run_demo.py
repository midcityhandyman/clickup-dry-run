"""Offline demo: replay the fake export through the example automations.

Usage: python demo/run_demo.py           (prints the report)
       python demo/run_demo.py --save    (also writes demo/output.txt)
"""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dryrun.cli import main  # noqa: E402

ARGS = ["examples/automations.yaml", "examples/export.json",
        "--as-of", "2026-03-06", "--monthly-limit", "100"]


def run() -> str:
    import os
    os.chdir(ROOT)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(ARGS)
    header = f"$ python -m dryrun {' '.join(ARGS)}\n\n"
    return header + buffer.getvalue() + f"\nexit code: {code}\n"


if __name__ == "__main__":
    text = run()
    sys.stdout.write(text)
    if "--save" in sys.argv:
        (ROOT / "demo" / "output.txt").write_text(text, encoding="utf-8", newline="\n")
