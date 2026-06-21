from __future__ import annotations

import os
import re
from typing import Any, Dict


ERROR_PATTERNS = [
    r"out\s+of\s+memory",
    r"segmentation\s+fault",
    r"error\s+in\s+routine",
    r"charge\s+(?:density\s+)?is\s+nan",
    r"diagonalization\s+\(subsp\)\s+failed",
    r"stopped\s+in\s+routine",
    r"stop\s+critical",
    r"EXX:\s+.*\s+error",
    r"exiting\s+.*\.\.\.",
]

_RE_SCFA = re.compile(r"estimated scf accuracy\s*[<|=]\s*([0-9.+\-EeDd]+)\s*Ry", re.I)
_RE_STEPS = re.compile(r"iteration\s*#\s*(\d+)", re.I)
_RE_EN = re.compile(r"total energy\s*=\s*([\-0-9.+EeDd]+)\s*Ry")
_RE_WALL = re.compile(r"PWSCF\s*:\s*cpu\s*[0-9.+EeDd-]+s\s*wall\s*([0-9.+EeDd-]+)s")
_RE_SUCCESS = re.compile(r"convergence has been achieved", re.I)


def _to_float(text: str) -> float:
    return float(text.replace("D", "E").replace("d", "e"))


def parse_scf_output(path: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "success": False,
        "error": False,
        "no_convergence": False,
        "residual": None,
        "steps": None,
        "time": None,
        "energy": None,
    }
    if not os.path.exists(path):
        out["error"] = True
        return out
    try:
        with open(path, "r", errors="ignore") as fin:
            text = fin.read()
    except Exception:
        out["error"] = True
        return out

    out["success"] = bool(_RE_SUCCESS.search(text))
    out["error"] = any(re.search(pattern, text, re.I) for pattern in ERROR_PATTERNS)

    matches = _RE_SCFA.findall(text)
    if matches:
        try:
            out["residual"] = _to_float(matches[-1])
        except ValueError:
            pass

    matches = _RE_STEPS.findall(text)
    if matches:
        try:
            out["steps"] = int(matches[-1])
        except ValueError:
            pass

    matches = _RE_EN.findall(text)
    if matches:
        try:
            out["energy"] = _to_float(matches[-1])
        except ValueError:
            pass

    matches = _RE_WALL.findall(text)
    if matches:
        try:
            out["time"] = _to_float(matches[-1])
        except ValueError:
            pass

    out["no_convergence"] = not out["success"] and not out["error"]
    return out
