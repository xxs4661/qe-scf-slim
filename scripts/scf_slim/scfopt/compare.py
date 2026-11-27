"""Summarize existing pw.x logs in input order for people and batch jobs."""

from __future__ import annotations

import argparse
import json
import zlib
from collections import Counter
from typing import Any

from .diagnostics import diagnose
from .log_input import open_log


def add_compare_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "compare",
        help="summarize multiple pw.x outputs side by side",
        description="Show the latest invocation in each output, in the order supplied.",
    )
    parser.add_argument("logs", nargs="+", metavar="FILE", help="pw.x log, .gz log, or - for stdin")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable batch summary")
    parser.add_argument(
        "--check", action="store_true", help="return exit code 1 if any log is not converged"
    )
    parser.set_defaults(handler=run_compare)


def _read_summary(path: str) -> dict[str, Any]:
    try:
        with open_log(path) as lines:
            report = diagnose(lines)
    except (OSError, EOFError, UnicodeError, zlib.error) as exc:
        message = getattr(exc, "strerror", None) or str(exc)
        return {"path": path, "status": "read_error", "error": message}
    fields = (
        "status", "runs", "cycles", "job_done", "iterations", "mixing_beta", "mixing_betas",
        "residual_operator", "residual_ry", "threshold_ry", "energy_ry", "wall_seconds",
    )
    return {"path": path, **{field: report[field] for field in fields}}


def _number(value: float | int | None) -> str:
    if value is None:
        return "—"
    return str(value) if isinstance(value, int) else f"{value:.6g}"


def _table(rows: list[dict[str, Any]], counts: dict[str, int]) -> str:
    header = ("Status", "Last iter", "Last beta", "Est. acc. (Ry)", "conv_thr (Ry)", "Wall (s)", "File")
    cells = []
    for row in rows:
        estimate = "—"
        if row.get("residual_ry") is not None:
            estimate = (row["residual_operator"] or "") + str(row["residual_ry"])
        # Escape newlines and terminal controls in user-supplied names while preserving Unicode.
        path = repr(row["path"])[1:-1]
        if "error" in row:
            path += "  (" + repr(row["error"])[1:-1] + ")"
        cells.append((
            row["status"], _number(row.get("iterations")), _number(row.get("mixing_beta")),
            estimate, _number(row.get("threshold_ry")), _number(row.get("wall_seconds")), path,
        ))

    widths = [max(len(value) for value in col) for col in zip(header, *cells)]
    lines = []
    for row in [header, *cells]:
        numeric = [value.rjust(width) for value, width in zip(row[1:-1], widths[1:-1])]
        lines.append("  ".join([row[0].ljust(widths[0]), *numeric, row[-1]]))
    lines += [
        "",
        ", ".join(f"{count} {status}" for status, count in counts.items()),
        "Iteration, beta and accuracy refer to the last SCF cycle. Wall time covers the latest invocation.",
        "For line-numbered evidence, run scf-slim diagnose FILE.",
    ]
    return "\n".join(lines)


def run_compare(args: argparse.Namespace) -> int:
    rows = []
    used_stdin = False
    for path in args.logs:
        if path == "-" and used_stdin:
            rows.append({"path": path, "status": "read_error", "error": "stdin can be read only once"})
            continue
        if path == "-":
            used_stdin = True
        rows.append(_read_summary(path))

    counts = dict(sorted(Counter(row["status"] for row in rows).items()))
    if args.json:
        print(json.dumps({"schema_version": 1, "counts": counts, "runs": rows}, indent=2, allow_nan=False))
    else:
        print(_table(rows, counts))

    if "read_error" in counts:
        return 2
    return int(args.check and any(status != "converged" for status in counts))
