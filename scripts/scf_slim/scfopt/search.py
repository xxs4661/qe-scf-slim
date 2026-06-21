from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .utils import beta_index, round_beta, unique_sorted


def rank_key(record: Dict[str, Any]) -> Tuple[float, float, float, float]:
    if not record.get("ok"):
        return (float("inf"), 0.0, 0.0, float(record["beta"]))
    return (
        float(record["S4"]),
        -float(record.get("R2") or 0.0),
        -float(record.get("b_abs") or 0.0),
        float(record["beta"]),
    )


def best_record(records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    feasible = [record for record in records if record.get("ok")]
    if not feasible:
        return None
    return sorted(feasible, key=rank_key)[0]


def candidate_from_gap(
    left: float,
    right: float,
    decimals: int,
    min_dist: float,
    seen: set[int],
    blocked: set[int] | None = None,
) -> Optional[float]:
    if right - left < 2 * min_dist:
        return None
    blocked = blocked or set()
    raw_candidates = [(left + right) / 2.0, left + (right - left) / 3.0, right - (right - left) / 3.0]
    for value in raw_candidates:
        beta = round_beta(value, decimals)
        if beta <= left + 1e-12 or beta >= right - 1e-12:
            continue
        idx = beta_index(beta, decimals)
        if idx not in seen and idx not in blocked:
            return beta
    return None


def propose_next_beta(
    records: List[Dict[str, Any]],
    beta_range: Tuple[float, float],
    decimals: int,
    min_dist: float,
    blocked_indices: set[int] | None = None,
    prefer_edge_neighbor: bool = False,
) -> Optional[float]:
    lo, hi = beta_range
    evaluated = unique_sorted((float(record["beta"]) for record in records), decimals)
    seen = {beta_index(beta, decimals) for beta in evaluated}
    blocked = blocked_indices or set()
    best = best_record(records)

    if best is not None:
        best_beta = float(best["beta"])
        if prefer_edge_neighbor:
            candidate = edge_neighbor_candidate(best_beta, beta_range, decimals, min_dist, seen, blocked)
            if candidate is not None:
                return candidate
        pts = sorted([lo, *evaluated, hi])
        pos = pts.index(best_beta)
        adjacent_gaps: List[Tuple[float, float]] = []
        if pos > 0:
            adjacent_gaps.append((pts[pos - 1], best_beta))
        if pos < len(pts) - 1:
            adjacent_gaps.append((best_beta, pts[pos + 1]))
        adjacent_gaps.sort(key=lambda pair: pair[1] - pair[0], reverse=True)
        for left, right in adjacent_gaps:
            candidate = candidate_from_gap(left, right, decimals, min_dist, seen, blocked)
            if candidate is not None:
                return candidate

    pts = sorted([lo, *evaluated, hi])
    all_gaps = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    all_gaps.sort(key=lambda pair: pair[1] - pair[0], reverse=True)
    for left, right in all_gaps:
        candidate = candidate_from_gap(left, right, decimals, min_dist, seen, blocked)
        if candidate is not None:
            return candidate
    return None


def edge_neighbor_candidate(
    best_beta: float,
    beta_range: Tuple[float, float],
    decimals: int,
    min_dist: float,
    seen: set[int],
    blocked: set[int],
) -> Optional[float]:
    lo, hi = beta_range
    step = max(float(min_dist), 10 ** (-decimals))
    edge_tol = step / 2.0 + 1e-12
    if abs(best_beta - hi) <= edge_tol:
        for offset in (step, 2 * step, 3 * step):
            beta = round_beta(hi - offset, decimals)
            idx = beta_index(beta, decimals)
            if beta > lo + 1e-12 and idx not in seen and idx not in blocked:
                return beta
    if abs(best_beta - lo) <= edge_tol:
        for offset in (step, 2 * step, 3 * step):
            beta = round_beta(lo + offset, decimals)
            idx = beta_index(beta, decimals)
            if beta < hi - 1e-12 and idx not in seen and idx not in blocked:
                return beta
    return None


def nearest_bracket_width(records: List[Dict[str, Any]], best: Dict[str, Any], beta_range: Tuple[float, float]) -> float:
    lo, hi = beta_range
    pts = sorted([lo, *[float(record["beta"]) for record in records], hi])
    beta = float(best["beta"])
    pos = pts.index(beta)
    left = pts[pos - 1] if pos > 0 else lo
    right = pts[pos + 1] if pos < len(pts) - 1 else hi
    return right - left
