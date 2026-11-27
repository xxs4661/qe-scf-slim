"""Decide what a user should do next from the evidence in one parsed pw.x log."""

from __future__ import annotations

import math
import re
from typing import Any


def _decision(priority: str, code: str, reason: str, action: str, lines: list[int]) -> dict:
    return {"priority": priority, "code": code, "reason": reason, "next_action": action,
            "evidence_lines": sorted(set(lines))}


def _rebounds(values: list[float]) -> int:
    """Count distinct factor-of-two falls followed by factor-of-two rises."""
    peak = trough = values[0]
    falling = False
    count = 0
    for value in values[1:]:
        if falling:
            trough = min(trough, value)
            if value / 2 >= trough:
                count += 1
                falling = False
                peak = value
        else:
            peak = max(peak, value)
            if value <= peak / 2:
                falling = True
                trough = value
    return count


def _recent_trend(report: dict, accuracy_line: int | None) -> tuple[str, list[dict]]:
    """Compare consecutive printed estimates up to the latest observed iteration."""
    tail = report["history"][-8:]
    steps = report["iterations"]
    iterations = [point["iteration"] for point in tail]
    if (len(tail) < 4 or steps is None or iterations[-1] != steps
            or any(not isinstance(i, int) for i in iterations)
            or any(b != a + 1 for a, b in zip(iterations, iterations[1:]))
            or tail[-1]["line"] != accuracy_line):
        return "", []
    values = [p["residual_ry"] for p in tail]
    if min(values) > 0:
        half = len(values) // 2
        improving = min(values[half:]) < min(values[:half]) / 2
        if (len(values) >= 6 and not improving and values[-1] >= values[0] / 2
                and _rebounds(values) >= 2 and len(report["mixing_betas"]) <= 1):
            return "rebounds", tail
        if improving and values[-1] <= values[0] / 2:
            return "improving", tail
    return "", tail


def _unconverged(report: dict, outcome_line: int, accuracy_line: int | None) -> dict:
    steps = report["iterations"]
    lines = [outcome_line]
    if steps is not None and steps <= 3:
        return _decision("intervene", "short_iteration_budget",
                         f"QE reported electronic nonconvergence after only {steps} iterations.",
                         "Check electron_maxstep in the input and allow enough iterations for the requested conv_thr.", lines)

    trend, tail = _recent_trend(report, accuracy_line)
    lines.extend(p["line"] for p in tail)
    if trend == "rebounds":
        return _decision("intervene", "repeated_rebounds",
                         f"The last {len(tail)} printed SCF estimates show repeated large rebounds and limited net progress before QE stopped.",
                         "If the structure and occupations are appropriate, compare one retry at lower mixing_beta with the same starting conditions and convergence settings.", lines)
    if trend == "improving":
        return _decision("intervene", "improving_at_limit",
                         f"QE stopped before convergence as the last {len(tail)} printed estimates fell overall from {tail[0]['residual_ry']:.4g} to {tail[-1]['residual_ry']:.4g} Ry.",
                         "Check whether the available wall time permits extending electron_maxstep at the same conv_thr.", lines)
    return _decision("intervene", "unconverged",
                     "QE reports that the electronic cycle ended without reaching convergence.",
                     "Review the SCF history, occupations and iteration limit against the input before choosing a retry.", lines)


def _late_warning(report: dict, kind: str) -> bool:
    stat = report["warnings"].get(kind, {})
    iteration = report["iterations"]
    return (stat.get("last_cycle") == report["cycles"] and iteration is not None
            and stat.get("last_iteration") in (iteration, iteration - 1))


def _sizable_negative_rho(text: str) -> tuple[float, float] | None:
    # QE PWscf user guide, troubleshooting 5.0.0.24: values of order 0.1 merit review.
    try:
        up, down = [float(s.lower().replace("d", "e")) for s in text.partition(":")[2].split()[:2]]
    except ValueError:
        return None
    if math.isfinite(up) and math.isfinite(down) and max(abs(up), abs(down)) >= 0.1:
        return up, down
    return None


def assess_intervention(report: dict[str, Any]) -> dict:
    """Return a read-only triage decision about electronic SCF, with absolute source lines."""
    evidence = {event["kind"]: event for event in report["evidence"]}

    def lines(*kinds: str) -> list[int]:
        return [evidence[k]["line"] for k in kinds if k in evidence]

    status = report["status"]
    if status == "unsupported":
        return _decision("review", "unsupported", "The calculation type or supplied output is outside electronic SCF triage.",
                         "Identify the calculation and inspect its completion criteria in the appropriate workflow.", lines("unsupported", "program") or lines("job_done"))
    if status == "failed":
        cause = " ".join(evidence[k]["text"].lower() for k in ("fatal", "error_detail") if k in evidence)
        refs = lines("fatal", "error_detail")
        if "readpp" in cause or "pseudopotential" in cause or ".upf" in cause:
            return _decision("intervene", "pseudopotential_error", "QE reported an error while reading pseudopotential data.",
                             "Check the ATOMIC_SPECIES filenames and their readability in pseudo_dir on the compute node.", refs)
        if re.search(r"out[ _-]of[ _-]memory|oom[-_ ]kill", cause):
            return _decision("intervene", "out_of_memory", "The job reported a memory allocation failure or scheduler OOM kill.",
                             "Check peak memory against the allocation before resubmitting.", refs)
        if "time limit" in cause:
            return _decision("intervene", "time_limit", "The scheduler reports that the job reached a time limit.",
                             "Inspect the checkpoint and wall-time allocation before resuming the job.", refs)
        if "fatal" in evidence:
            return _decision("intervene", "runtime_error", "The job reported a fatal error.",
                             "Inspect the reported error with the launcher or scheduler stderr before retrying.", refs)
        # diagnose marks explicit nonfinite final energy/accuracy as failed.
        nonfinite = [e["line"] for k, e in evidence.items() if k in ("accuracy", "energy")
                     and re.search(r"\b(?:nan|inf(?:inity)?)\b", e["text"], re.I)]
        return _decision("intervene", "nonfinite_result", "The final electronic output contains a nonfinite numerical value.",
                         "Inspect the numerical record and input data before using this result.", nonfinite)
    if status == "incomplete":
        if "stop" in evidence:
            if "time exceeded" in evidence["stop"]["text"].lower():
                return _decision("intervene", "time_limit", "QE reports reaching its configured time limit.",
                                 "Inspect the checkpoint and available wall time before resuming the job.", lines("stop"))
            return _decision("review", "stop_requested", "QE reports a stop request.",
                             "Check whether the stop was intentional and whether the checkpoint is usable.", lines("stop"))
        last = max((e["line"] for e in evidence.values()), default=None)
        if "converged" in evidence:
            return _decision("review", "check_job_state", "The electronic cycle reported convergence but stdout ends before the job-completion footer.",
                             "Check the scheduler exit status and look for the remainder of stdout.", [evidence["converged"]["line"], last])
        if "job_done" in evidence:
            return _decision("review", "missing_scf_outcome", "QE printed its completion footer without a final electronic-convergence message.",
                             "Confirm the calculation type and examine the final electronic cycle.", lines("iteration", "accuracy", "job_done"))
        if report["iterations"] is not None and report["iterations"] >= 12:
            trend, tail = _recent_trend(report, evidence.get("accuracy", {}).get("line"))
            if trend == "rebounds":
                return _decision("review", "monitor_rebounds",
                                 f"This snapshot ends at iteration {report['iterations']} with repeated large rebounds and limited progress over the last {len(tail)} printed estimates.",
                                 "Check the latest stdout and scheduler state to see whether subsequent iterations are making progress.",
                                 [p["line"] for p in tail])
        return _decision("review", "check_job_state", "The supplied stdout has no definitive completed electronic result.",
                         "Check the scheduler state and the end of stdout before deciding whether to resume.", [last] if last else [])
    if status == "unconverged":
        return _unconverged(report, evidence["unconverged"]["line"], evidence.get("accuracy", {}).get("line"))
    if status != "converged":
        raise ValueError(f"Unknown electronic SCF status {status!r}")

    residual, threshold = report["residual_ry"], report["threshold_ry"]
    if residual is not None and threshold is not None and residual > threshold:
        return _decision("review", "threshold_check", "QE reports convergence with a printed accuracy estimate above the printed threshold.",
                         "Check conv_thr, scf_must_converge and the precision of the printed estimate before accepting the result.", lines("threshold", "accuracy", "converged"))
    if ("accuracy" in evidence and residual is None) or ("energy" in evidence and report["energy_ry"] is None):
        return _decision("review", "unreadable_result", "A final numerical record could not be read from the converged output.",
                         "Check the marked energy and SCF accuracy in the original result files.", lines("accuracy", "energy", "converged"))
    if _late_warning(report, "negative_rho"):
        rho = _sizable_negative_rho(evidence["negative_rho"]["text"])
        if rho is not None:
            return _decision("review", "late_negative_rho",
                             f"Late negative rho (up, down) was {rho[0]:.4g}, {rho[1]:.4g} electrons. A channel magnitude of at least 0.1 electrons triggers review.",
                             "Check whether the charge-density cutoff is adequate for these pseudopotentials before using the density.", lines("negative_rho", "converged"))
    if _late_warning(report, "c_bands"):
        return _decision("review", "late_band_warning", "QE reported unconverged eigenvalues in the final two iterations of the converged SCF cycle.",
                         "Check how many bands remained unconverged and whether they affect the observable of interest.", lines("c_bands", "converged"))
    return _decision("none", "converged", "QE reported electronic convergence and completed the run.",
                     "Keep this SCF result.", lines("converged", "job_done"))
