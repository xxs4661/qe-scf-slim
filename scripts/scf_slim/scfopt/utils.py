from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def fmt_beta(beta: float, decimals: int) -> str:
    return format(float(beta), f".{int(decimals)}f")


def round_beta(beta: float, decimals: int) -> float:
    return float(round(float(beta), int(decimals)))


def beta_index(beta: float, decimals: int) -> int:
    return int(round(float(beta) * (10 ** int(decimals))))


def unique_sorted(values: Iterable[float], decimals: int) -> List[float]:
    seen = {}
    for value in values:
        rounded = round_beta(value, decimals)
        seen[beta_index(rounded, decimals)] = rounded
    return [seen[key] for key in sorted(seen)]


def initial_anchors(beta_range: Tuple[float, float], n_anchors: int, decimals: int) -> List[float]:
    lo, hi = beta_range
    if n_anchors <= 1:
        return [round_beta((lo + hi) / 2.0, decimals)]
    raw = [lo + i * (hi - lo) / (n_anchors - 1) for i in range(n_anchors)]
    return unique_sorted(raw, decimals)


def raw_logs(residuals: List[float]) -> List[float]:
    return [math.log10(max(value, 1e-300)) for value in residuals if value > 0]


def running_min_logs(residuals: List[float]) -> List[float]:
    out = []
    current = float("inf")
    for value in residuals:
        if value <= 0:
            continue
        current = min(current, value)
        out.append(math.log10(max(current, 1e-300)))
    return out


def compute_s4(residuals: List[float], threshold: float) -> Optional[int]:
    for idx, value in enumerate(residuals, start=1):
        if value > 0 and value <= threshold:
            return idx
    return None


def median_filter_3(values: List[float]) -> List[float]:
    if len(values) <= 2:
        return list(values)
    out = []
    for idx in range(len(values)):
        lo = max(0, idx - 1)
        hi = min(len(values), idx + 2)
        window = values[lo:hi]
        out.append(sorted(window)[len(window) // 2])
    return out


def fit_tail_linear(log_values: List[float], window: int) -> Tuple[float, float, int]:
    if not log_values:
        return 0.0, 0.0, 0
    n = min(max(3, int(window)), len(log_values))
    ys = median_filter_3(log_values[-n:])
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(ys) / n
    ss_xx = sum((x - mx) ** 2 for x in xs)
    if ss_xx <= 0:
        return 0.0, 0.0, n
    slope = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / ss_xx
    intercept = my - slope * mx
    sse = sum((ys[i] - (intercept + slope * xs[i])) ** 2 for i in range(n))
    sst = sum((y - my) ** 2 for y in ys)
    r2 = 1.0 if sst <= 0 else max(0.0, 1.0 - sse / sst)
    return abs(float(slope)), float(r2), n

