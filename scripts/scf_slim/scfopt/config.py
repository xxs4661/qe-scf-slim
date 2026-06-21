from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


BASE_CONFIG: Dict[str, Any] = {
    "preset": "default",
    "qe": {
        "mpirun": None,
        "pw": "pw.x",
        "np": 1,
        "extra_args": [],
        "env": {"OMP_NUM_THREADS": "1"},
    },
    "task": {
        "beta_range": [0.01, 1.00],
        "fixed_degauss": 0.02,
        "target_residual_ry": 1.0e-4,
        "probe_conv_thr_ry": 1.0e-8,
        "final_conv_thr_ry": 1.0e-8,
        "electron_maxstep": 160,
        "episode_timeout_s": 7200,
        "mixing_mode": "local-TF",
        "seed_from_file": False,
        "extra_steps_after_target": 3,
    },
    "search": {
        "strategy": "sequential",
        "beta_decimals": 2,
        "n_anchors": 7,
        "max_evals": 12,
        "min_dist": 0.01,
        "stop_bracket_width": 0.02,
    },
    "presearch": {
        "enabled": False,
        "num_buckets": 2,
        "min_span_for_presearch": 0.30,
        "n_anchors": 7,
    },
    "bucket": {
        "num_buckets": 2,
        "min_span": 0.20,
        "edge_probe_first": False,
        "edge_improve_stop_steps": 0.0,
        "skip_bucket_s4_margin": None,
    },
    "budget": {
        "per_bucket_eval_max": 6,
    },
    "guards": {
        "burnin_steps": 60,
        "adaptive_triggers": True,
        "near_stop_enabled": True,
        "near_graceful_exit": False,
        "near_grace_wait_s": 300,
        "osc_enabled": True,
        "diverge_ratio": 3.5,
        "plateau_patience_steps": 20,
        "neg_rho_guard_enabled": True,
        "neg_rho_abs_tol": 0.02,
        "neg_rho_rel_tol": 0.0,
        "neg_rho_patience": 20,
    },
    "verify": {"enabled": True, "inherit_seed": False, "timeout_s": 7200},
    "output": {"plots": True, "keep_light_seed": True},
    "overrides": {},
    "system_overrides": {},
}


PRESETS: Dict[str, Dict[str, Any]] = {
    "smoke": {
        "task": {"electron_maxstep": 40, "episode_timeout_s": 300, "extra_steps_after_target": 0},
        "search": {"n_anchors": 3, "max_evals": 4, "stop_bracket_width": 0.05},
        "verify": {"enabled": False},
        "output": {"plots": False},
    },
    "default": {},
    "thorough": {
        "search": {"n_anchors": 11, "max_evals": 20, "stop_bracket_width": 0.01},
        "task": {"extra_steps_after_target": 5},
    },
}


def deep_update(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in (update or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value
    return base


def load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fin:
        loaded = yaml.safe_load(fin) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return loaded


def effective_config(user_cfg: Dict[str, Any], system_name: str) -> Dict[str, Any]:
    preset_name = str(user_cfg.get("preset", BASE_CONFIG["preset"]))
    if preset_name not in PRESETS:
        choices = ", ".join(sorted(PRESETS))
        raise ValueError(f"Unknown preset {preset_name!r}; choose one of {choices}")
    cfg = copy.deepcopy(BASE_CONFIG)
    user_base = copy.deepcopy(user_cfg)
    explicit_overrides = user_base.pop("overrides", {}) or {}
    deep_update(cfg, user_base)
    deep_update(cfg, PRESETS[preset_name])
    deep_update(cfg, explicit_overrides)
    override = (cfg.get("system_overrides") or {}).get(system_name, {})
    if override:
        deep_update(cfg, override)
    return cfg


def bench_template_for_system(bench: Dict[str, Any], system_name: str) -> Optional[str]:
    systems = bench.get("systems")
    if isinstance(systems, list):
        for item in systems:
            name = str(item.get("name") or item.get("system") or item.get("id") or "").strip()
            if name == system_name:
                return item.get("template") or item.get("template_path") or item.get("path")
    if isinstance(systems, dict):
        node = systems.get(system_name)
        if isinstance(node, dict):
            return node.get("template") or node.get("template_path") or node.get("path")
        if isinstance(node, str):
            return node
    node = bench.get(system_name)
    if isinstance(node, dict):
        return node.get("template") or node.get("template_path") or node.get("path")
    if isinstance(node, str):
        return node
    return None


def list_systems(bench_path: Path) -> List[str]:
    bench = load_yaml(bench_path)
    systems = bench.get("systems")
    if isinstance(systems, list):
        return [str(item.get("name") or item.get("system") or item.get("id")) for item in systems]
    if isinstance(systems, dict):
        return [str(key) for key in systems]
    return []


def load_template(bench: Optional[str], template: Optional[str], system_name: str) -> Tuple[str, str]:
    if bench:
        bench_path = Path(bench).resolve()
        rel = bench_template_for_system(load_yaml(bench_path), system_name)
        if not rel:
            raise ValueError(f"System {system_name!r} was not found in {bench_path}")
        raw_path = Path(os.path.expandvars(os.path.expanduser(str(rel))))
        template_path = raw_path if raw_path.is_absolute() else (bench_path.parent / raw_path).resolve()
        return template_path.read_text(encoding="utf-8"), str(template_path)
    if template:
        template_path = Path(os.path.expandvars(os.path.expanduser(template))).resolve()
        return template_path.read_text(encoding="utf-8"), str(template_path)
    raise ValueError("Provide either --bench or --template")
