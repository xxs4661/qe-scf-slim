from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


def _log10(x: float, eps: float = 1e-300) -> float:
    return math.log10(max(float(x), eps))


@dataclass
class GuardCfg:
    burnin_steps: int = 60
    episode_timeout_s: float = 7200.0
    target_residual_ry: float = 1e-4
    near_stop_enabled: bool = True
    near_margin_factor: float = 1.0
    near_confirm_tail: int = 3
    near_graceful_exit: bool = False
    near_grace_wait_s: float = 300.0
    adaptive_triggers: bool = True
    diverge_start_after_steps: int = 20
    diverge_start_frac: float = 0.12
    diverge_start_min_steps: int = 10
    diverge_ratio: float = 3.5
    diverge_steps: int = 4
    diverge_rel_L: float = 0.25
    diverge_min_L: int = 20
    plateau_min_lookback: int = 40
    plateau_rel_lookback: float = 0.33
    plateau_max_lookback: int = 100
    plateau_kappa: float = 0.6
    plateau_patience_steps: int = 20
    osc_enabled: bool = True
    osc_W: int = 24
    osc_flip_frac_persist: float = 0.60
    osc_iqr_decades_min: float = 0.06
    osc_slope_max_persist: float = 0.003
    osc_transient_drop_min: float = 0.15
    osc_transient_slope_min: float = 0.004
    osc_grace_steps: int = 15
    osc_grace_frac: float = 0.10
    osc_grace_min_steps: int = 6
    neg_rho_guard_enabled: bool = True
    neg_rho_abs_tol: float = 0.02
    neg_rho_rel_tol: float = 0.0
    neg_rho_patience: int = 20
    neg_rho_unknown_fatal: bool = False


@dataclass
class GuardState:
    last_big_impr_step: int = 0
    s_ref_per_step: Optional[float] = None
    near_confirm_left: int = 0
    near_last_k_for_confirm: int = -1
    env_logs: List[float] = field(default_factory=list)
    osc_transient_hits: int = 0
    osc_last_k: int = -1


RES_RE = re.compile(r"estimated\s+scf\s+accuracy\s*(?:=|<|is)?\s*([0-9.\-+EedD]+)\s*Ry", re.I)
SUCC_RE = re.compile(r"convergence has been achieved", re.I)
ENE_RE = re.compile(r"!\s*total energy\s*=\s*([0-9.\-EeDd+]+)\s*Ry", re.I)
NEG_RHO_LINE = re.compile(r"negative\s+rho\s*\(up,\s*down\)\s*:\s*([0-9.\-+EeDd]+)\s+([0-9.\-+EeDd]+)", re.I)
NEG_RHO_ANY = re.compile(r"negative\s+rho|rho\s+.*negative|negative\s+density", re.I)
NELEC_RE = re.compile(r"(?:number\s+of\s+electrons|nelec)\s*=\s*([0-9.]+)", re.I)


def parse_new_lines(lines: List[str], residuals: List[float]) -> Tuple[int, Optional[float], bool, Optional[Tuple[float, float]], Optional[float]]:
    added = 0
    energy = None
    success = False
    neg_vals = None
    nelec = None
    for line in lines:
        match = RES_RE.search(line)
        if match:
            try:
                residuals.append(float(match.group(1).replace("D", "E").replace("d", "e")))
                added += 1
            except ValueError:
                pass
        match = ENE_RE.search(line)
        if match:
            try:
                energy = float(match.group(1).replace("D", "E").replace("d", "e"))
            except ValueError:
                pass
        if SUCC_RE.search(line):
            success = True
        match = NEG_RHO_LINE.search(line)
        if match:
            try:
                neg_vals = (float(match.group(1).replace("D", "E").replace("d", "e")), float(match.group(2).replace("D", "E").replace("d", "e")))
            except ValueError:
                neg_vals = None
        elif NEG_RHO_ANY.search(line) and neg_vals is None:
            neg_vals = None
        match = NELEC_RE.search(line)
        if match:
            try:
                nelec = float(match.group(1))
            except ValueError:
                pass
    return added, energy, success, neg_vals, nelec


def env_logs(residuals: List[float]) -> List[float]:
    out = []
    best = float("inf")
    for value in residuals:
        if value <= 0:
            continue
        best = min(best, value)
        out.append(_log10(best))
    return out


def raw_logs(residuals: List[float]) -> List[float]:
    return [_log10(value) for value in residuals if value > 0]


def sign_flip_rate(values: List[float], window: int) -> float:
    tail = values[-window - 1:]
    flips = 0
    total = 0
    for i in range(2, len(tail)):
        d1 = tail[i] - tail[i - 1]
        d0 = tail[i - 1] - tail[i - 2]
        if d1 == 0 or d0 == 0:
            continue
        total += 1
        flips += int(d1 * d0 < 0)
    return flips / total if total else 0.0


def iqr(values: List[float]) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    n = len(vals)

    def quantile(q: float) -> float:
        pos = q * (n - 1)
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            return vals[lo]
        weight = pos - lo
        return (1 - weight) * vals[lo] + weight * vals[hi]

    return quantile(0.75) - quantile(0.25)


def guard_evaluate_step(
    residuals: List[float],
    step: int,
    wall_s: float,
    max_steps_budget: int,
    cfg: GuardCfg,
    state: GuardState,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    if wall_s >= cfg.episode_timeout_s:
        return "timeout", {"wall_s": wall_s}

    y_env = env_logs(residuals)
    y_raw = raw_logs(residuals)
    if not y_raw:
        return None, None
    state.env_logs = y_env

    div_start, osc_grace = trigger_steps(cfg, max_steps_budget)
    near = near_target_stop(y_env, step, cfg, state)
    if near:
        return near
    osc = oscillation_stop(y_raw, step, cfg, state, osc_grace)
    if osc:
        return osc
    div = divergence_stop(residuals, step, cfg, div_start)
    if div:
        return div
    return plateau_stop(y_env, step, cfg, state)


def trigger_steps(cfg: GuardCfg, max_steps_budget: int) -> Tuple[int, int]:
    if not cfg.adaptive_triggers:
        return cfg.diverge_start_after_steps, cfg.osc_grace_steps
    div_start = max(cfg.diverge_start_min_steps, min(cfg.diverge_start_after_steps, int(round(cfg.diverge_start_frac * max_steps_budget))))
    osc_grace = max(cfg.osc_grace_min_steps, min(cfg.osc_grace_steps, int(round(cfg.osc_grace_frac * max_steps_budget))))
    return div_start, osc_grace


def near_target_stop(y_env: List[float], step: int, cfg: GuardCfg, state: GuardState) -> Optional[Tuple[str, Dict[str, Any]]]:
    if not cfg.near_stop_enabled or not y_env:
        return None
    target_log = _log10(cfg.target_residual_ry * cfg.near_margin_factor)
    if y_env[-1] > target_log:
        return None
    if cfg.near_confirm_tail <= 0:
        return "near_target_done", {"k": step, "y_last": y_env[-1], "e_last": 10 ** y_env[-1]}
    if state.near_confirm_left <= 0:
        state.near_confirm_left = int(cfg.near_confirm_tail)
        state.near_last_k_for_confirm = step
    elif step > state.near_last_k_for_confirm:
        state.near_confirm_left -= 1
        state.near_last_k_for_confirm = step
        if state.near_confirm_left <= 0:
            return "near_target_done", {"k": step, "y_last": y_env[-1], "e_last": 10 ** y_env[-1]}
    return None


def oscillation_stop(y_raw: List[float], step: int, cfg: GuardCfg, state: GuardState, osc_grace: int) -> Optional[Tuple[str, Dict[str, Any]]]:
    if not cfg.osc_enabled or step < max(osc_grace, min(cfg.burnin_steps, osc_grace)):
        return None
    window = min(cfg.osc_W, len(y_raw) - 1)
    if window < 8:
        return None
    flip = sign_flip_rate(y_raw, window)
    slope = max(0.0, (y_raw[-window - 1] - y_raw[-1]) / float(window))
    spread = iqr(y_raw[-window - 1:])
    if flip >= cfg.osc_flip_frac_persist and spread >= cfg.osc_iqr_decades_min and slope <= cfg.osc_slope_max_persist:
        return "oscillation_persistent", {"flip_rate": flip, "iqr": spread, "slope": slope, "W": window}
    if step > state.osc_last_k and flip >= cfg.osc_flip_frac_persist and (y_raw[-window - 1] - y_raw[-1]) >= cfg.osc_transient_drop_min and slope >= cfg.osc_transient_slope_min:
        state.osc_transient_hits += 1
        state.osc_last_k = step
    return None


def divergence_stop(residuals: List[float], step: int, cfg: GuardCfg, div_start: int) -> Optional[Tuple[str, Dict[str, Any]]]:
    if step < max(cfg.burnin_steps, div_start):
        return None
    lookback = max(cfg.diverge_min_L, int(cfg.diverge_rel_L * max(1, step - cfg.burnin_steps)))
    window = [value for value in residuals[-min(lookback, step):] if value > 0]
    if not window:
        return None
    local_min = min(window)
    bad = sum(1 for value in residuals[-cfg.diverge_steps:] if value > 0 and value >= cfg.diverge_ratio * local_min)
    if bad >= cfg.diverge_steps:
        return "diverge", {"lookback": lookback, "local_min": local_min, "ratio": cfg.diverge_ratio}
    return None


def plateau_stop(y_env: List[float], step: int, cfg: GuardCfg, state: GuardState) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    lookback = max(cfg.plateau_min_lookback, min(cfg.plateau_max_lookback, int(cfg.plateau_rel_lookback * max(1, step - cfg.burnin_steps))))
    if len(y_env) >= min(cfg.burnin_steps, 10) + 20:
        slopes = [(y_env[-w - 1] - y_env[-1]) / w for w in range(5, 41, 5) if len(y_env) >= w + 1]
        slopes.sort()
        if slopes:
            state.s_ref_per_step = max(1e-8, slopes[len(slopes) // 2])
    if len(y_env) < lookback + 1:
        return None, None
    drop = y_env[-lookback - 1] - y_env[-1]
    required = cfg.plateau_kappa * (state.s_ref_per_step or 1e-2) * lookback
    if drop >= max(0.0, required):
        state.last_big_impr_step = step
    elif step - state.last_big_impr_step >= cfg.plateau_patience_steps:
        return "stall", {"lookback": lookback, "drop": drop, "required": required}
    return None, None

