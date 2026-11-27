"""Read pw.x stdout one line at a time. Line numbers refer to the original input."""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


_PROGRAM = re.compile(r"^Program\s+(\S+)\s+v\.", re.I)
_CYCLE = re.compile(r"^Self-consistent Calculation\s*$", re.I)
_ITERATION = re.compile(r"^iteration\s*#\s*(\d{1,12})\b", re.I)
_BETA = re.compile(r"\bbeta\s*=\s*([^\s,]+)", re.I)
_ACCURACY = re.compile(r"^estimated\s+scf\s+accuracy\s*([<=])\s*(\S+)\s+Ry(?:d)?\b", re.I)
_THRESHOLD = re.compile(r"^(?:scf )?convergence threshold\s*=\s*(\S+)", re.I)
_ENERGY = re.compile(r"^!\s*total\s+energy\s*=\s*(\S+)\s+Ry(?:d)?\b", re.I)
_OUTCOME = re.compile(r"^convergence\s+(has been achieved|not achieved)\b(?:\s+(?:in|after)\s+(\d{1,12})\s+iterations?)?", re.I)
_NONFINITE = re.compile(r"^[+-]?(?:nan(?:\(\w+\))?|inf(?:inity)?)$", re.I)
_DONE = re.compile(r"^JOB DONE\.?$", re.I)
_WALL = re.compile(r"^PWSCF\s*:.*?\bCPU\s+(.+?)\s+WALL\b", re.I)
_LEGACY_WALL = re.compile(r"^PWSCF\s*:\s*CPU\s+.+?\s+WALL\s+(.+)$", re.I)
_TIME_PART = re.compile(r"(\d+(?:\.\d*)?)\s*([dhms])", re.I)
_CBANDS = re.compile(r"^c_bands\s*:\s*(?:[1-9]\d*|\*+)\s+eigen(?:values|vectors) not converged\b", re.I)
_NEG_RHO = re.compile(r"^negative rho\s*\(up,\s*down\)\s*:", re.I)
_STOP = re.compile(r"^(Maximum CPU time exceeded|Program stopped by user request|Signal Received, stopping)", re.I)
_ROUTINE = re.compile(r"^(?:Error in routine\b|from\s+\S+\s*:\s*error\s*#)", re.I)
_FATAL = re.compile(r"out[ _-]of[ _-]memory|\boom[-_ ]kill\b|segmentation fault|\bSIGSEGV\b|\bMPI_ABORT\b"
                    r"|slurmstepd:.*\b(?:CANCELLED|TIME LIMIT)\b|charge\s+(?:density\s+)?is NaN"
                    r"|diagonalization\s+\(subsp\) failed|^stopped in routine\b|^stop critical\b", re.I)
_OUT_OF_SCOPE = re.compile(
    r"^(?:(?:End of )?(?:Band Structure Calculation|Non[- ]self[- ]consistent Calculation|"
    r"BFGS Geometry Optimization|(?:Molecular|Damped|Over-damped Langevin) Dynamics Calculation)|"
    r"number of bfgs steps\s*=|bfgs (?:converged|failed)\b|Final scf calculation at the relaxed structure|"
    r"Calculation \(EXX\) stopped|EXX(?:-fraction\s*=|:| self-consistency reached| convergence NOT achieved)|"
    r"calculation\s*=\s*['\"](?:nscf|bands|(?:vc-)?(?:relax|md))['\"])", re.I,
)


def _number(token: str) -> float | None:
    try:
        value = float(token.upper().replace("D", "E"))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _duration(token: str) -> float | None:
    """QE prints durations such as '2m 3.30s' or '1d 4h12m'."""
    if _TIME_PART.sub("", token).strip():
        return None
    parts = _TIME_PART.findall(token)
    scale = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    seconds = sum(float(amount) * scale[unit.lower()] for amount, unit in parts)
    return seconds if parts and math.isfinite(seconds) else None


@dataclass
class _Cycle:
    iteration: int | None = None
    energy: float | None = None
    residual: float | None = None
    operator: str | None = None
    beta: float | None = None
    betas: list[float] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    outcome: str | None = None
    evidence: dict = field(default_factory=dict)
    nonfinite: set[str] = field(default_factory=set)

    def read_value(self, kind: str, token: str) -> float | None:
        if _NONFINITE.fullmatch(token):
            self.nonfinite.add(kind)
        else:
            self.nonfinite.discard(kind)
        return _number(token)


@dataclass
class _Run:
    recognized: bool = False
    cycle: _Cycle = field(default_factory=_Cycle)
    cycles: int = 0
    wall: float | None = None
    threshold: float | None = None
    evidence: dict = field(default_factory=dict)
    warnings: dict = field(default_factory=dict)

    def new_cycle(self) -> None:
        self.cycles += 1
        self.cycle = _Cycle()

    def record_warning(self, event: dict) -> None:
        kind = event["kind"]
        stat = self.warnings.setdefault(kind, {"count": 0, "first_line": event["line"]})
        stat.update(count=stat["count"] + 1, last_line=event["line"],
                    last_iteration=self.cycle.iteration, last_cycle=self.cycles or None)
        self.evidence[kind] = event


def _accuracy_trend(history: list[dict]) -> str | None:
    """Describe numerical changes in the recent printed estimates, without fitting a model."""
    values = [point["residual_ry"] for point in history[-8:]]
    if len(values) < 2:
        return None
    pairs = list(zip(values, values[1:]))
    if all(a > b for a, b in pairs):
        return (f"The last {len(values)} readable SCF estimates decrease from {values[0]:.6g} "
                f"to {values[-1]:.6g} Ry. Check the available wall time before extending the run.")
    if all(a == b for a, b in pairs):
        return f"The last {len(values)} readable SCF estimates are equal at the printed precision ({values[-1]:.6g} Ry)."
    rebounds = sum(a > b < c for a, b, c in zip(values, values[1:], values[2:]))
    if rebounds >= 2:
        return (f"The last {len(values)} readable estimates contain {rebounds} decreases followed by increases. "
                "Check the occupations and band filling. Test a smaller mixing_beta with other inputs fixed.")
    if values[-1] > values[-2]:
        return f"The last readable SCF estimate rose from {values[-2]:.6g} to {values[-1]:.6g} Ry."
    return None


def _warning_advice(run: _Run) -> list[str]:
    advice = []
    for kind, stat in run.warnings.items():
        location = f"{stat['count']} line(s), latest at line {stat['last_line']}"
        if kind == "negative_rho":
            advice.append(f"Negative rho ({location}). Small printed values can arise from Fourier truncation. "
                          "If sizable, test charge-density cutoff convergence (ecutrho) with the same pseudopotentials.")
        elif (stat["last_cycle"] == run.cycles and stat["last_iteration"] is not None
              and run.cycle.iteration is not None and stat["last_iteration"] >= run.cycle.iteration - 1):
            advice.append(f"The c_bands warning ({location}) reaches the final two observed iterations. "
                          "Compare the reported unconverged eigenvalues with the number of bands and check the input if a significant fraction remains.")
        else:
            advice.append(f"The c_bands diagonalization warning occurs on {location}. Early warnings can resolve as SCF proceeds. "
                          "Check whether a significant fraction of eigenvalues remains unconverged in the final iterations.")
    return advice


def _assessment(run: _Run) -> tuple[str, list[str]]:
    evidence = run.evidence
    cycle = run.cycle
    if "unsupported" in evidence:
        return "unsupported", ["Inspect the identified calculation in its own workflow. The reported SCF metrics cover only the last electronic cycle."]
    if not run.recognized:
        return "unsupported", ["Supply pw.x standard output with the program banner or recognizable SCF records."]
    if "fatal" in evidence:
        detail = " ".join(evidence[key]["text"].lower() for key in ("fatal", "error_detail") if key in evidence)
        if "readpp" in detail or "pseudopotential" in detail:
            return "failed", ["Check the UPF filenames in ATOMIC_SPECIES and whether pseudo_dir is readable on the compute node."]
        if re.search(r"out[ _-]of[ _-]memory|oom[-_ ]kill", detail):
            return "failed", ["Check the job's memory limit and measured peak memory in the scheduler log."]
        return "failed", ["Inspect the reported error and its surrounding lines, then check launcher or scheduler stderr for the cause."]
    if "stop" in evidence:
        return "incomplete", ["pw.x reported a time limit or a stop request. Inspect the saved restart data before resubmitting."]
    if cycle.nonfinite:
        names = {"accuracy": "SCF accuracy", "energy": "marked total energy"}
        fields = " and ".join(names[kind] for kind in sorted(cycle.nonfinite))
        return "failed", [f"The final {fields} record contains an explicit NaN or infinity. Inspect the numerical output and input data before using this calculation."]
    if cycle.outcome == "unconverged":
        steps = f" after {cycle.iteration} iterations" if cycle.iteration is not None else ""
        advice = [f"pw.x reports no SCF convergence{steps}. Check electron_maxstep in &ELECTRONS and the requested conv_thr."]
        trend = _accuracy_trend(cycle.history)
        if trend:
            advice.append(trend)
        return "unconverged", advice
    if cycle.outcome == "converged" and "job_done" in evidence:
        return "converged", []
    if cycle.outcome == "converged":
        return "incomplete", ["The electronic cycle converged. Check the end of stdout and the scheduler exit status for job completion."]
    if "job_done" in evidence:
        return "incomplete", ["pw.x printed JOB DONE without a final SCF convergence result. Check the calculation type and any early stop."]
    return "incomplete", ["Check whether the job is still running. If it has exited, inspect scheduler stderr and the end of stdout."]


def diagnose(lines: Iterable[str]) -> dict[str, Any]:
    """Diagnose the latest invocation, retaining the accuracy history of its latest cycle.

    Converged requires both an explicit electronic convergence record and JOB DONE.
    Reported energy is QE's marked (!) energy. 'residual_ry' is the *printed*
    estimated energy error with the operator given by 'residual_operator'.
    """
    run = _Run()
    previous_runs = 0
    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue

        def record(kind: str) -> dict:
            return {"kind": kind, "line": line_no, "text": line}

        program = _PROGRAM.match(line)
        start_cycle = _CYCLE.match(line)
        iteration = _ITERATION.match(line)
        accuracy = _ACCURACY.match(line)
        energy = _ENERGY.match(line)
        outcome = _OUTCOME.match(line)
        threshold = _THRESHOLD.match(line)
        if program or ("job_done" in run.evidence and (start_cycle or iteration or accuracy or energy or outcome or threshold)):
            previous_runs += int(run.recognized)
            run = _Run(recognized=True)
        if program:
            key = "program" if program[1].upper() == "PWSCF" else "unsupported"
            run.evidence[key] = record(key)
            continue

        if threshold:
            run.recognized = True
            run.threshold = _number(threshold[1])
            run.evidence["threshold"] = record("threshold")
            continue
        if _OUT_OF_SCOPE.match(line):
            run.recognized = True
            if "unsupported" not in run.evidence:
                run.evidence["unsupported"] = record("unsupported")
            continue
        if "fatal" in run.evidence and run.evidence["fatal"]["line"] + 1 == line_no and not line.startswith("%"):
            run.evidence["error_detail"] = record("error_detail")
        if _ROUTINE.match(line) or _FATAL.search(line):
            if _ROUTINE.match(line):
                run.recognized = True
            if "fatal" not in run.evidence:
                run.evidence["fatal"] = record("fatal")
            continue
        if _STOP.match(line):
            run.evidence["stop"] = record("stop")
            continue
        if _DONE.fullmatch(line):
            run.evidence["job_done"] = record("job_done")
            continue
        if _CBANDS.match(line):
            run.record_warning(record("c_bands"))
            continue
        if _NEG_RHO.match(line):
            run.record_warning(record("negative_rho"))
            continue
        wall = _LEGACY_WALL.match(line) or _WALL.match(line)
        if wall:
            run.recognized = True
            run.wall = _duration(wall[1])
            run.evidence["wall"] = record("wall")
            continue

        if not (start_cycle or iteration or accuracy or energy or outcome):
            continue
        if start_cycle or accuracy or energy or (outcome and outcome[2]) or (iteration and _BETA.search(line)):
            run.recognized = True
        # A later cycle can be incomplete even when an earlier one converged.
        if start_cycle or not run.cycles or (iteration and (
            run.cycle.outcome or (run.cycle.iteration is not None and int(iteration[1]) < run.cycle.iteration)
        )):
            run.new_cycle()
        cycle = run.cycle
        if start_cycle:
            cycle.evidence["scf_start"] = record("scf_start")
        elif iteration:
            cycle.iteration = int(iteration[1])
            cycle.evidence["iteration"] = record("iteration")
            beta = _BETA.search(line)
            if beta:
                cycle.beta = _number(beta[1])
                if cycle.beta is not None and cycle.beta not in cycle.betas:
                    cycle.betas.append(cycle.beta)
        elif accuracy:
            value = cycle.read_value("accuracy", accuracy[2])
            cycle.residual = value if value is not None and value >= 0 else None
            cycle.operator = accuracy[1]
            cycle.evidence["accuracy"] = record("accuracy")
            if cycle.residual is not None:
                cycle.history.append({"iteration": cycle.iteration, "residual_ry": cycle.residual,
                                      "operator": cycle.operator, "line": line_no})
        elif energy:
            cycle.energy = cycle.read_value("energy", energy[1])
            cycle.evidence["energy"] = record("energy")
        elif outcome:
            cycle.outcome = "unconverged" if outcome[1].lower().startswith("not") else "converged"
            if outcome[2]:
                cycle.iteration = int(outcome[2])
            cycle.evidence["outcome"] = record(cycle.outcome)

    status, advice = _assessment(run)
    cycle = run.cycle
    if (status == "converged" and cycle.residual is not None and run.threshold is not None
            and cycle.residual > run.threshold):
        advice.append("The printed accuracy estimate is above the printed SCF threshold. Check scf_must_converge and the precision of the printed values.")
    if "accuracy" in cycle.evidence and cycle.residual is None and "accuracy" not in cycle.nonfinite:
        advice.append("The last printed SCF accuracy could not be read as a finite, nonnegative value.")
    if "energy" in cycle.evidence and cycle.energy is None and "energy" not in cycle.nonfinite:
        advice.append("The marked total energy could not be read as a finite value. Inspect the original energy record.")
    if len(cycle.betas) > 1:
        advice.append("Multiple printed mixing_beta values occur in the last cycle. Inspect their sequence before comparing runs.")
    advice.extend(_warning_advice(run))
    evidence = sorted([*run.evidence.values(), *cycle.evidence.values()], key=lambda event: event["line"])
    return {
        "status": status, "runs": previous_runs + int(run.recognized), "cycles": run.cycles,
        "job_done": "job_done" in run.evidence, "iterations": cycle.iteration,
        "mixing_beta": cycle.beta, "mixing_betas": cycle.betas,
        "residual_ry": cycle.residual, "residual_operator": cycle.operator,
        "threshold_ry": run.threshold, "energy_ry": cycle.energy, "wall_seconds": run.wall,
        "history": cycle.history, "warnings": run.warnings, "evidence": evidence, "advice": advice,
    }
