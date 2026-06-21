from __future__ import annotations

import json
import time
from argparse import Namespace
from pathlib import Path
from typing import Any, Dict, List

from .buckets import bucket_order_key, bucket_result, describe_bucket, edge_improvement_stop, plan_buckets, presearch_anchor_count, records_in_bucket, search_strategy
from .config import effective_config, load_template, load_yaml
from .logging_utils import EventLogger
from .output import write_summary
from .plots import plot_residuals
from .qe_runner import QERunner, cleanup_job_root_heavy, cleanup_save_heavy, clone_save_light
from .search import best_record, nearest_bracket_width, propose_next_beta
from .utils import beta_index, compute_s4, ensure_dir, fit_tail_linear, fmt_beta, initial_anchors, raw_logs, round_beta


RUN_ID = f"{int(time.time()) % 100000000:08d}"


def build_runner(cfg: Dict[str, Any]) -> QERunner:
    qe = cfg.get("qe", {})
    env = {str(k): str(v) for k, v in (qe.get("env") or {}).items() if v is not None}
    return QERunner(
        mpirun=qe.get("mpirun"),
        pw=str(qe.get("pw") or "pw.x"),
        np=int(qe.get("np", 1)),
        extra_args=list(qe.get("extra_args") or []),
        env=env,
    )


def prepare_guard_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    task = cfg.get("task", {})
    guards = dict(cfg.get("guards") or {})
    guards["target_residual_ry"] = float(task.get("target_residual_ry", 1e-4))
    guards["near_confirm_tail"] = int(task.get("extra_steps_after_target", 3))
    guards["near_stop_enabled"] = bool(guards.get("near_stop_enabled", True))
    return guards


def evaluate_beta(
    *,
    system_name: str,
    beta: float,
    tag: str,
    template_text: str,
    runner: QERunner,
    cfg: Dict[str, Any],
    out_dir: Path,
    logger: EventLogger,
) -> Dict[str, Any]:
    task = cfg.get("task", {})
    search = cfg.get("search", {})
    decimals = int(search.get("beta_decimals", 2))
    beta = round_beta(beta, decimals)
    prefix = f"{system_name}_{tag}_B{fmt_beta(beta, decimals)}_{int(time.time() * 1000)}".replace(".", "p")

    logger.print(f"[probe] beta={fmt_beta(beta, decimals)} tag={tag}")
    logger.log("probe_start", beta=beta, tag=tag, prefix=prefix)
    res = runner.run(
        template_text,
        outdir=out_dir / "jobs",
        prefix=prefix,
        mixing_beta=beta,
        degauss=task.get("fixed_degauss"),
        conv_thr=float(task.get("probe_conv_thr_ry", task.get("target_residual_ry", 1e-4))),
        electron_maxstep=int(task.get("electron_maxstep", 160)),
        mixing_mode=task.get("mixing_mode", "plain"),
        wf_collect=False,
        disk_io="low",
        startingpot=("file" if task.get("seed_from_file", False) else None),
        guard_cfg_dict=prepare_guard_cfg(cfg),
        episode_timeout_s=float(task.get("episode_timeout_s", 7200)),
        disable_guard=False,
    )
    record = probe_record(beta, tag, res, cfg, out_dir, prefix)
    if cfg.get("output", {}).get("plots", True):
        plots_dir = out_dir / "plots"
        ensure_dir(plots_dir)
        plot_residuals(plots_dir / f"residual_beta_{fmt_beta(beta, decimals)}.png", res["residuals"], f"{system_name} beta={fmt_beta(beta, decimals)}")
    logger.print(f"        stop={record['stop']} steps={record['steps']} S4={record['S4'] if record['S4'] is not None else 'NA'} R2={record['R2'] if record['R2'] is not None else 'NA'}")
    logger.log("probe_end", **record)
    return record


def probe_record(beta: float, tag: str, res: Dict[str, Any], cfg: Dict[str, Any], out_dir: Path, prefix: str) -> Dict[str, Any]:
    task = cfg.get("task", {})
    seed_dir = keep_light_seed(res, cfg, out_dir, prefix)
    s4 = compute_s4(res["residuals"], float(task.get("target_residual_ry", 1e-4)))
    b_abs, r2, fit_n = fit_tail_linear(raw_logs(res["residuals"]), int(task.get("fit_window_L", 12)))
    diagnostics = res.get("diagnostics", {})
    ok = s4 is not None
    return {
        "beta": beta,
        "ok": ok,
        "S4": int(s4) if s4 is not None else None,
        "steps": int(res["steps"]),
        "stop": res["stop_reason"],
        "time_s": float(res["time_s"]),
        "energy": res.get("energy"),
        "b_abs": b_abs if ok else None,
        "R2": r2 if ok else None,
        "fit_n": fit_n,
        "M_after_S4": max(0, int(res["steps"]) - int(s4 or res["steps"])) if ok else 0,
        "seed_dir": str(seed_dir) if seed_dir.exists() else "",
        "stdout_path": res.get("stdout_path"),
        "job_dir": res.get("job_dir"),
        "osc_hits": int(diagnostics.get("osc_transient_hits", 0)),
        "neg_rho_max": float(diagnostics.get("neg_rho_max", 0.0) or 0.0),
        "stage": tag,
    }


def keep_light_seed(res: Dict[str, Any], cfg: Dict[str, Any], out_dir: Path, prefix: str) -> Path:
    seeds_dir = out_dir / "seeds"
    ensure_dir(seeds_dir)
    seed_dir = seeds_dir / f"{prefix}.save"
    if cfg.get("output", {}).get("keep_light_seed", True):
        clone_save_light(Path(res["prefix_save"]), seed_dir)
        cleanup_save_heavy(seed_dir)
    cleanup_save_heavy(Path(res["prefix_save"]))
    cleanup_job_root_heavy(Path(res["job_dir"]))
    return seed_dir


def run_full_scf(
    *,
    system_name: str,
    champion: Dict[str, Any],
    template_text: str,
    runner: QERunner,
    cfg: Dict[str, Any],
    out_dir: Path,
    logger: EventLogger,
) -> Dict[str, Any]:
    task = cfg.get("task", {})
    verify = cfg.get("verify", {})
    decimals = int(cfg.get("search", {}).get("beta_decimals", 2))
    beta = float(champion["beta"])
    prefix = f"{system_name}_FULL_B{fmt_beta(beta, decimals)}_{int(time.time() * 1000)}".replace(".", "p")
    job_dir = out_dir / "jobs" / prefix
    job_dir.mkdir(parents=True, exist_ok=True)

    used_seed = maybe_clone_seed(champion, verify, job_dir, prefix)
    logger.print(f"[full] beta={fmt_beta(beta, decimals)} seed={'yes' if used_seed else 'no'}")
    res = runner.run(
        template_text,
        outdir=out_dir / "jobs",
        prefix=prefix,
        mixing_beta=beta,
        degauss=task.get("fixed_degauss"),
        conv_thr=float(task.get("final_conv_thr_ry", 1e-8)),
        electron_maxstep=int(task.get("electron_maxstep", 160)),
        mixing_mode=task.get("mixing_mode", "plain"),
        wf_collect=False,
        disk_io="low",
        startingpot=("file" if used_seed else None),
        startingwfc=("atomic" if used_seed else None),
        restart_mode=("restart" if used_seed else None),
        guard_cfg_dict={},
        episode_timeout_s=float(verify.get("timeout_s", task.get("episode_timeout_s", 7200))),
        disable_guard=True,
    )
    cleanup_save_heavy(Path(res["prefix_save"]))
    cleanup_job_root_heavy(Path(res["job_dir"]))
    out = full_record(beta, champion, res, used_seed)
    logger.log("full_end", **out)
    return out


def maybe_clone_seed(champion: Dict[str, Any], verify: Dict[str, Any], job_dir: Path, prefix: str) -> bool:
    seed_dir = Path(champion.get("seed_dir") or "")
    if verify.get("inherit_seed", False) and seed_dir.exists():
        clone_save_light(seed_dir, job_dir / f"{prefix}.save")
        return True
    return False


def full_record(beta: float, champion: Dict[str, Any], res: Dict[str, Any], used_seed: bool) -> Dict[str, Any]:
    actual_total = int(res["steps"])
    if used_seed:
        actual_total += int(champion.get("S4") or 0) + int(champion.get("M_after_S4") or 0)
    return {
        "beta": beta,
        "success": bool(res.get("success")),
        "stop": res.get("stop_reason"),
        "steps_only": int(res.get("steps", -1)),
        "actual_total": actual_total,
        "used_seed": used_seed,
        "stdout_path": res.get("stdout_path"),
        "job_dir": res.get("job_dir"),
    }


def run(args: Namespace) -> Dict[str, Any]:
    cfg = effective_config(load_yaml(Path(args.config)), args.system)
    template_text, template_source = load_template(args.bench, args.template, args.system)
    out_dir = Path(args.outdir).resolve()
    task = cfg.get("task", {})
    search = cfg.get("search", {})
    beta_range = tuple(float(x) for x in task.get("beta_range", [0.01, 1.0]))
    decimals = int(search.get("beta_decimals", 2))
    anchor_count = presearch_anchor_count(cfg) if search_strategy(cfg) == "bucket" else int(search.get("n_anchors", 7))
    anchors = initial_anchors(beta_range, anchor_count, decimals)

    if args.dry_run:
        return dry_run_payload(args, cfg, template_source, out_dir, beta_range, anchors)

    logger = EventLogger(out_dir, quiet=args.quiet)
    logger.print(f"run_id={RUN_ID} system={args.system} template={template_source}")
    logger.print(
        f"preset={cfg.get('preset')} strategy={search_strategy(cfg)} "
        f"beta_range=[{fmt_beta(beta_range[0], decimals)}, {fmt_beta(beta_range[1], decimals)}] "
        f"max_evals={search.get('max_evals')}"
    )
    logger.log("run_start", system=args.system, template=template_source, config=str(Path(args.config).resolve()))
    if search_strategy(cfg) == "bucket":
        return execute_bucket_search(args, cfg, template_text, template_source, out_dir, logger, beta_range, anchors)
    return execute_search(args, cfg, template_text, template_source, out_dir, logger, beta_range, anchors)


def dry_run_payload(args: Namespace, cfg: Dict[str, Any], template_source: str, out_dir: Path, beta_range: tuple[float, float], anchors: List[float]) -> Dict[str, Any]:
    payload = {
        "system": args.system,
        "template": template_source,
        "outdir": str(out_dir),
        "preset": cfg.get("preset"),
        "beta_range": list(beta_range),
        "anchors": anchors,
        "max_evals": int(cfg.get("search", {}).get("max_evals", 12)),
        "strategy": search_strategy(cfg),
        "effective_config": cfg,
    }
    print(json.dumps(payload, indent=2))
    return payload


def execute_search(args: Namespace, cfg: Dict[str, Any], template_text: str, template_source: str, out_dir: Path, logger: EventLogger, beta_range: tuple[float, float], anchors: List[float]) -> Dict[str, Any]:
    search = cfg.get("search", {})
    decimals = int(search.get("beta_decimals", 2))
    max_evals = int(search.get("max_evals", 12))
    min_dist = float(search.get("min_dist", 0.01))
    runner = build_runner(cfg)
    records: List[Dict[str, Any]] = []
    seen: set[int] = set()

    for beta in anchors:
        if len(records) >= max_evals:
            break
        run_one_probe(args.system, beta, "ANCHOR", template_text, runner, cfg, out_dir, logger, records, seen, decimals)

    while len(records) < max_evals:
        candidate = propose_next_beta(records, beta_range, decimals, min_dist)
        if candidate is None or beta_index(candidate, decimals) in seen:
            logger.print("[search] no unseen candidate remains")
            break
        run_one_probe(args.system, candidate, "REFINE", template_text, runner, cfg, out_dir, logger, records, seen, decimals)
        best = best_record(records)
        if best is not None:
            width = nearest_bracket_width(records, best, beta_range)
            logger.print(f"[search] current_best beta={fmt_beta(best['beta'], decimals)} S4={best['S4']} bracket_width={width:.4f}")
            if width <= float(search.get("stop_bracket_width", 0.02)):
                logger.print("[search] bracket width reached stop threshold")
                break
    return finish_run(args, cfg, template_text, template_source, runner, out_dir, logger, records)


def execute_bucket_search(args: Namespace, cfg: Dict[str, Any], template_text: str, template_source: str, out_dir: Path, logger: EventLogger, beta_range: tuple[float, float], anchors: List[float]) -> Dict[str, Any]:
    search = cfg.get("search", {})
    decimals = int(search.get("beta_decimals", 2))
    min_dist = float(search.get("min_dist", 0.01))
    max_evals = int(search.get("max_evals", 16))
    stop_width = float(search.get("stop_bracket_width", 0.02))
    bucket_cfg = cfg.get("bucket", {})
    per_bucket_max = int(cfg.get("budget", {}).get("per_bucket_eval_max", 6))
    edge_probe_first = bool(bucket_cfg.get("edge_probe_first", False))
    edge_stop_steps = float(bucket_cfg.get("edge_improve_stop_steps", 0.0) or 0.0)
    skip_s4_margin = bucket_cfg.get("skip_bucket_s4_margin")
    runner = build_runner(cfg)
    records: List[Dict[str, Any]] = []
    seen: set[int] = set()

    logger.print(f"[stage0] presearch anchors={', '.join(fmt_beta(beta, decimals) for beta in anchors)}")
    for beta in anchors:
        if len(records) >= max_evals:
            break
        run_one_probe(args.system, beta, "PRE", template_text, runner, cfg, out_dir, logger, records, seen, decimals)

    buckets = plan_buckets(records, beta_range, cfg, decimals)
    logger.print("[stage1] bucket plan: " + "; ".join(describe_bucket(bucket, decimals) for bucket in buckets))
    logger.log("bucket_plan", buckets=buckets)

    bucket_records_by_id: Dict[int, List[Dict[str, Any]]] = {
        int(bucket["id"]): records_in_bucket(records, bucket, decimals) for bucket in buckets
    }
    ordered_buckets = sorted(buckets, key=lambda bucket: bucket_order_key(bucket, bucket_records_by_id[int(bucket["id"])]))

    for bucket in ordered_buckets:
        bucket_id = int(bucket["id"])
        bucket_dir = out_dir / f"bucket_{bucket_id:02d}"
        bucket_dir.mkdir(parents=True, exist_ok=True)
        bucket_records = bucket_records_by_id[bucket_id]
        write_summary(bucket_dir, bucket_records)
        warm = ", ".join(fmt_beta(record["beta"], decimals) for record in bucket_records) or "none"
        logger.print(f"[bucket {bucket_id:02d}] {describe_bucket(bucket, decimals)} warm={warm}")

        global_best = best_record(records)
        bucket_best = best_record(bucket_records)
        if skip_s4_margin is not None and global_best is not None and bucket_best is not None:
            gap = float(bucket_best["S4"]) - float(global_best["S4"])
            if gap >= float(skip_s4_margin):
                logger.print(
                    f"[bucket {bucket_id:02d}] skipped: bucket_best S4={bucket_best['S4']} "
                    f"is {gap:.1f} steps behind global_best beta={fmt_beta(global_best['beta'], decimals)}"
                )
                logger.log("bucket_skipped", bucket_id=bucket_id, reason="s4_margin", gap=gap)
                continue

        while len(bucket_records) < per_bucket_max and len(records) < max_evals:
            candidate = propose_next_beta(
                bucket_records,
                (float(bucket["L"]), float(bucket["U"])),
                decimals,
                min_dist,
                blocked_indices=seen,
                prefer_edge_neighbor=edge_probe_first,
            )
            if candidate is None:
                logger.print(f"[bucket {bucket_id:02d}] no unseen candidate remains")
                break
            record = run_one_probe(args.system, candidate, f"BUCKET{bucket_id:02d}", template_text, runner, cfg, out_dir, logger, records, seen, decimals)
            bucket_records.append(record)
            bucket_records.sort(key=lambda item: float(item["beta"]))
            write_summary(bucket_dir, bucket_records)
            best = best_record(bucket_records)
            if best is None:
                continue
            width = nearest_bracket_width(bucket_records, best, (float(bucket["L"]), float(bucket["U"])))
            logger.print(f"[bucket {bucket_id:02d}] current_best beta={fmt_beta(best['beta'], decimals)} S4={best['S4']} bracket_width={width:.4f}")
            if edge_improvement_stop(bucket_records, bucket, best, decimals, min_dist, edge_stop_steps):
                logger.print(f"[bucket {bucket_id:02d}] edge-neighbor improvement reached stop threshold")
                break
            if width <= stop_width + 1e-12:
                logger.print(f"[bucket {bucket_id:02d}] bracket width reached stop threshold")
                break

        bucket_records_by_id[bucket_id] = bucket_records
        write_summary(bucket_dir, bucket_records)

    bucket_results = [bucket_result(bucket, bucket_records_by_id[int(bucket["id"])], decimals) for bucket in buckets]
    return finish_run(
        args,
        cfg,
        template_text,
        template_source,
        runner,
        out_dir,
        logger,
        records,
        search_report={"strategy": "bucket", "buckets": bucket_results},
    )


def run_one_probe(system_name: str, beta: float, tag: str, template_text: str, runner: QERunner, cfg: Dict[str, Any], out_dir: Path, logger: EventLogger, records: List[Dict[str, Any]], seen: set[int], decimals: int) -> Dict[str, Any]:
    seen.add(beta_index(beta, decimals))
    record = evaluate_beta(system_name=system_name, beta=beta, tag=tag, template_text=template_text, runner=runner, cfg=cfg, out_dir=out_dir, logger=logger)
    records.append(record)
    write_summary(out_dir, records)
    return record


def finish_run(args: Namespace, cfg: Dict[str, Any], template_text: str, template_source: str, runner: QERunner, out_dir: Path, logger: EventLogger, records: List[Dict[str, Any]], search_report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    summary_csv = write_summary(out_dir, records)
    champion = best_record(records)
    full = None
    if champion and cfg.get("verify", {}).get("enabled", True):
        full = run_full_scf(system_name=args.system, champion=champion, template_text=template_text, runner=runner, cfg=cfg, out_dir=out_dir, logger=logger)
    recommendation = build_recommendation(args, cfg, template_source, champion, full, summary_csv, out_dir, len(records), search_report)
    rec_path = out_dir / f"{args.system}_recommendation.json"
    rec_path.write_text(json.dumps(recommendation, indent=2), encoding="utf-8")
    logger.print(f"[done] recommendation={rec_path}")
    if champion:
        logger.print(f"[done] beta={fmt_beta(champion['beta'], int(cfg.get('search', {}).get('beta_decimals', 2)))} S4={champion['S4']}")
    print(json.dumps(recommendation, indent=2))
    return recommendation


def build_recommendation(args: Namespace, cfg: Dict[str, Any], template_source: str, champion: Dict[str, Any] | None, full: Dict[str, Any] | None, summary_csv: Path, out_dir: Path, n_records: int, search_report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = {
        "system": args.system,
        "template": template_source,
        "recommended_beta": champion.get("beta") if champion else None,
        "target_residual_ry": float(cfg.get("task", {}).get("target_residual_ry", 1e-4)),
        "preset": cfg.get("preset"),
        "strategy": search_strategy(cfg),
        "evaluations": n_records,
        "champion_probe": champion,
        "full_scf": full,
        "summary_csv": str(summary_csv),
        "console_log": str(out_dir / "console.log"),
        "events_jsonl": str(out_dir / "events.jsonl"),
    }
    if search_report is not None:
        payload["search_report"] = search_report
    return payload
