"""Legacy dictionary API for callers of parse_scf_output()."""

from __future__ import annotations

import zlib
from typing import Any

from scfopt.diagnostics import diagnose
from scfopt.log_input import open_log


def parse_scf_output(path: str) -> dict[str, Any]:
    """Return the summary for the last pw.x invocation using the original keys."""
    try:
        with open_log(path) as stream:
            report = diagnose(stream)
    except (OSError, EOFError, UnicodeError, zlib.error):
        return {
            "success": False,
            "error": True,
            "no_convergence": False,
            "residual": None,
            "steps": None,
            "time": None,
            "energy": None,
        }

    success = report["status"] == "converged"
    error = report["status"] == "failed" or any(item["kind"] == "fatal" for item in report["evidence"])
    return {
        "success": success,
        "error": error,
        "no_convergence": not (success or error),
        "residual": report["residual_ry"],
        "steps": report["iterations"],
        "time": report["wall_seconds"],
        "energy": report["energy_ry"],
    }
