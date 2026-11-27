"""Build a prioritized intervention report from existing pw.x output."""

from __future__ import annotations

import argparse
import json
import os
import stat
import zlib
from pathlib import Path
from typing import Any

from .diagnostics import diagnose
from .log_input import open_log


# Read errors appear with the files needing attention, ahead of healthy runs.
_PRIORITIES = ("intervene", "review", "read_error", "none")


def add_triage_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "triage", help="find jobs that need intervention and explain why",
        description="Prioritize actions using existing pw.x logs. Directory inputs are scanned "
                    "recursively for *.out and *.out.gz, without following nested directory symlinks.",
    )
    parser.add_argument("paths", metavar="PATH", nargs="+", help="a log, directory, or - for stdin")
    parser.add_argument("--all", action="store_true", help="also list healthy runs in the text report")
    parser.add_argument("--json", action="store_true", help="emit all decisions as JSON")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 for intervene or review, 2 for input/read errors, otherwise 0")
    parser.set_defaults(handler=run_triage)


def _read_error(path: str, error: BaseException | str) -> dict[str, Any]:
    return {"path": path, "status": "read_error", "error": getattr(error, "strerror", None) or str(error)}


def _scan_directory(root: str, rows: list[dict[str, Any]]) -> list[str]:
    paths = []
    errors_before = len(rows)

    def onerror(exc: OSError) -> None:
        rows.append(_read_error(exc.filename or root, exc))

    for dirname, subdirs, names in os.walk(root, onerror=onerror, followlinks=False):
        subdirs.sort()
        for name in sorted(names):
            if name.lower().endswith((".out", ".out.gz")):
                paths.append(os.path.join(dirname, name))
    if not paths and len(rows) == errors_before:
        rows.append(_read_error(root, "no *.out or *.out.gz files found"))
    return paths


def _row_priority(row: dict[str, Any]) -> str:
    return "read_error" if row["status"] == "read_error" else row["intervention"]["priority"]


def _read_run(path: str) -> dict[str, Any]:
    with open_log(path) as stream:
        report = diagnose(stream)
    return {"path": path, "status": report["status"], "intervention": report["intervention"]}


def _collect(inputs: list[str]) -> list[dict[str, Any]]:
    rows = []
    seen_files = set()
    stdin_used = False
    for arg in inputs:
        try:
            if arg == "-":
                if not stdin_used:
                    stdin_used = True
                    rows.append(_read_run("-"))
                continue
            paths = _scan_directory(arg, rows) if Path(arg).is_dir() else [arg]
        except (OSError, EOFError, UnicodeError, zlib.error) as exc:
            rows.append(_read_error(arg, exc))
            continue
        for path in paths:
            try:
                info = os.stat(path)
                if not stat.S_ISREG(info.st_mode):
                    rows.append(_read_error(path, "expected a regular log file"))
                    continue
                key = (info.st_dev, info.st_ino) if info.st_ino else os.path.realpath(path)
                if key not in seen_files:
                    seen_files.add(key)
                    rows.append(_read_run(path))
            except (OSError, EOFError, UnicodeError, zlib.error) as exc:
                rows.append(_read_error(path, exc))
    return sorted(rows, key=lambda row: _PRIORITIES.index(_row_priority(row)))


def _print_summary(rows: list[dict[str, Any]], counts: dict[str, int], show_all: bool) -> None:
    print("  ".join(f"{priority}: {count}" for priority, count in counts.items()))
    for row in rows:
        priority = _row_priority(row)
        if priority == "none" and not show_all:
            continue
        # repr escapes terminal control characters in user-provided filenames.
        path = repr(row["path"])[1:-1]
        if priority == "read_error":
            print(f"\n[read_error] {path}  {repr(row['error'])[1:-1]}")
            continue
        print(f"\n[{priority}] {path}  ({row['status']})")
        decision = row["intervention"]
        if priority != "none":
            print(f"  {decision['reason']}")
            if decision["evidence_lines"]:
                print("  Source lines: " + ", ".join(str(line) for line in decision["evidence_lines"]))
            print(f"  Next: {decision['next_action']}")


def run_triage(args: argparse.Namespace) -> int:
    rows = _collect(args.paths)
    counts = dict.fromkeys(_PRIORITIES, 0)
    for row in rows:
        counts[_row_priority(row)] += 1
    if args.json:
        print(json.dumps({"schema_version": 1, "counts": counts, "runs": rows}, indent=2, allow_nan=False))
    else:
        _print_summary(rows, counts, args.all)
    if counts["read_error"]:
        return 2
    return int(args.check and bool(counts["intervene"] or counts["review"]))
