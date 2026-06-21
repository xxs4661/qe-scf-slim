from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .search import best_record, rank_key
from .utils import beta_index, fmt_beta, round_beta


def search_strategy(cfg: Dict[str, Any]) -> str:
    search = cfg.get("search", {})
    presearch = cfg.get("presearch", {})
    if bool(presearch.get("enabled", False)):
        return "bucket"
    return str(search.get("strategy", search.get("mode", "sequential"))).lower()


def presearch_anchor_count(cfg: Dict[str, Any]) -> int:
    presearch = cfg.get("presearch", {})
    search = cfg.get("search", {})
    return int(presearch.get("n_anchors", search.get("n_anchors", 7)))


def records_in_bucket(records: Iterable[Dict[str, Any]], bucket: Dict[str, Any], decimals: int) -> List[Dict[str, Any]]:
    lo = float(bucket["L"])
    hi = float(bucket["U"])
    lower_open = bool(bucket.get("lower_open", False))
    out: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for record in records:
        beta = float(record["beta"])
        if beta < lo - 1e-12 or beta > hi + 1e-12:
            continue
        if lower_open and beta <= lo + 1e-12:
            continue
        idx = beta_index(beta, decimals)
        if idx in seen:
            continue
        seen.add(idx)
        out.append(record)
    return sorted(out, key=lambda item: float(item["beta"]))


def describe_bucket(bucket: Dict[str, Any], decimals: int) -> str:
    left = "(" if bucket.get("lower_open", False) else "["
    return f"B{int(bucket['id']):02d} {left}{fmt_beta(bucket['L'], decimals)}, {fmt_beta(bucket['U'], decimals)}]"


def plan_buckets(
    records: List[Dict[str, Any]],
    beta_range: Tuple[float, float],
    cfg: Dict[str, Any],
    decimals: int,
) -> List[Dict[str, Any]]:
    lo, hi = beta_range
    presearch = cfg.get("presearch", {})
    bucket_cfg = cfg.get("bucket", {})
    num_buckets = int(presearch.get("num_buckets", bucket_cfg.get("num_buckets", 2)))
    min_span_for_presearch = float(presearch.get("min_span_for_presearch", 0.0))
    if num_buckets < 2 or (hi - lo) < min_span_for_presearch:
        return [{"id": 1, "L": lo, "U": hi, "center": round_beta((lo + hi) / 2.0, decimals), "lower_open": False}]

    feasible = sorted([record for record in records if record.get("ok")], key=lambda item: float(item["beta"]))
    champion = best_record(records)
    if not feasible or champion is None:
        split = round_beta((lo + hi) / 2.0, decimals)
        return split_buckets(lo, hi, split, decimals)

    best_beta = float(champion["beta"])
    feasible_betas = [float(record["beta"]) for record in feasible]
    median_beta = feasible_betas[len(feasible_betas) // 2]
    if beta_index(median_beta, decimals) == beta_index(best_beta, decimals) and len(feasible_betas) > 1:
        median_beta = max(feasible_betas, key=lambda beta: (abs(beta - best_beta), -beta))

    low_center, high_center = sorted([best_beta, median_beta])
    split = (low_center + high_center) / 2.0
    min_span = float(bucket_cfg.get("min_span", 0.0))
    if min_span > 0.0 and 2 * min_span <= (hi - lo) + 1e-12:
        split = max(lo + min_span, min(hi - min_span, split))
    else:
        split = max(lo, min(hi, split))
    split = round_beta(split, decimals)
    if split <= lo or split >= hi:
        split = round_beta((lo + hi) / 2.0, decimals)
    return split_buckets(lo, hi, split, decimals, low_center=low_center, high_center=high_center)


def split_buckets(
    lo: float,
    hi: float,
    split: float,
    decimals: int,
    low_center: Optional[float] = None,
    high_center: Optional[float] = None,
) -> List[Dict[str, Any]]:
    split = round_beta(split, decimals)
    low_raw = low_center if low_center is not None else (lo + split) / 2.0
    high_raw = high_center if high_center is not None else (split + hi) / 2.0
    low_center_value = min(max(float(low_raw), lo), split)
    high_center_value = min(max(float(high_raw), split), hi)
    return [
        {
            "id": 1,
            "L": lo,
            "U": split,
            "center": round_beta(low_center_value, decimals),
            "lower_open": False,
        },
        {
            "id": 2,
            "L": split,
            "U": hi,
            "center": round_beta(high_center_value, decimals),
            "lower_open": True,
        },
    ]


def bucket_result(bucket: Dict[str, Any], records: List[Dict[str, Any]], decimals: int) -> Dict[str, Any]:
    champion = best_record(records)
    payload: Dict[str, Any] = {
        "bucket_id": int(bucket["id"]),
        "range": [float(bucket["L"]), float(bucket["U"])],
        "lower_open": bool(bucket.get("lower_open", False)),
        "evaluations": len(records),
        "champion_beta": None,
        "score": None,
        "ok": False,
    }
    if champion is not None:
        payload.update(
            {
                "champion_beta": float(champion["beta"]),
                "score": int(champion["S4"]),
                "ok": True,
                "champion_stop": champion.get("stop"),
                "champion_steps": int(champion.get("steps", 0)),
                "champion_R2": champion.get("R2"),
            }
        )
    failed = [record for record in records if not record.get("ok")]
    payload["failed"] = len(failed)
    payload["label"] = describe_bucket(bucket, decimals)
    return payload


def bucket_order_key(bucket: Dict[str, Any], records: List[Dict[str, Any]]) -> Tuple[float, float]:
    champion = best_record(records)
    if champion is None:
        return (float("inf"), float(bucket["id"]))
    return (rank_key(champion)[0], float(bucket["id"]))


def edge_improvement_stop(
    records: List[Dict[str, Any]],
    bucket: Dict[str, Any],
    best: Dict[str, Any],
    decimals: int,
    min_dist: float,
    min_improvement: float,
) -> bool:
    if min_improvement <= 0 or not best.get("ok"):
        return False
    beta = float(best["beta"])
    lo = float(bucket["L"])
    hi = float(bucket["U"])
    step = max(float(min_dist), 10 ** (-decimals))
    edge_tol = step / 2.0 + 1e-12
    edge_beta: Optional[float] = None
    if abs(beta - (hi - step)) <= edge_tol:
        edge_beta = hi
    elif abs(beta - (lo + step)) <= edge_tol:
        edge_beta = lo
    if edge_beta is None:
        return False
    edge_idx = beta_index(edge_beta, decimals)
    for record in records:
        if beta_index(float(record["beta"]), decimals) != edge_idx or not record.get("ok"):
            continue
        return float(record["S4"]) - float(best["S4"]) >= min_improvement
    return False
