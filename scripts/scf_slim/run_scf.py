from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scfopt.config import deep_update, effective_config, list_systems, load_template, load_yaml
from scfopt.doctor import print_report, run_doctor
from scfopt.search import best_record, nearest_bracket_width, propose_next_beta
from scfopt.utils import beta_index, compute_s4, ensure_dir, fit_tail_linear, fmt_beta, initial_anchors, raw_logs, round_beta, running_min_logs, unique_sorted
from scfopt.workflow import evaluate_beta, run, run_full_scf


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lean QE SCF beta friendly-range diagnostic tool")
    parser.add_argument("--config", help="Path to YAML config")
    parser.add_argument("--bench", help="Benchmark YAML mapping system names to templates")
    parser.add_argument("--template", help="Single QE input template")
    parser.add_argument("--system", help="System name")
    parser.add_argument("--outdir", help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Print effective config and anchors without running QE")
    parser.add_argument("--quiet", action="store_true", help="Suppress console log output")
    parser.add_argument("--list-systems", action="store_true", help="List systems from --bench and exit")
    parser.add_argument("--doctor", action="store_true", help="Discover and lightly validate pw.x, MPI, and pseudo paths")
    parser.add_argument("--doctor-json", action="store_true", help="Print doctor report as JSON")
    parser.add_argument("--doctor-no-run-check", action="store_true", help="Skip lightweight pw.x/MPI execution checks")
    parser.add_argument("--pw", help="Explicit pw.x candidate for --doctor")
    parser.add_argument("--mpirun", help="Explicit MPI launcher candidate for --doctor")
    parser.add_argument("--pseudo-dir", help="Explicit pseudopotential directory candidate for --doctor")
    parser.add_argument("--np", type=int, default=1, help="MPI ranks to use in generated qe config")
    parser.add_argument("--search-root", action="append", default=[], help="Extra root to search for QE builds during --doctor")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.doctor:
        cfg = load_yaml(Path(args.config)) if args.config else {}
        report = run_doctor(
            cfg=cfg,
            cwd=Path.cwd(),
            search_roots=[Path(item) for item in args.search_root],
            explicit_pw=args.pw,
            explicit_mpirun=args.mpirun,
            explicit_pseudo_dir=args.pseudo_dir,
            np=args.np,
            run_checks=not args.doctor_no_run_check,
        )
        print_report(report, as_json=args.doctor_json)
        return
    if args.list_systems:
        if not args.bench:
            parser.error("--list-systems requires --bench")
        for system in list_systems(Path(args.bench)):
            print(system)
        return
    if not args.config:
        parser.error("--config is required unless --doctor is used")
    if not args.system:
        parser.error("--system is required unless --doctor is used")
    if not args.outdir:
        parser.error("--outdir is required unless --doctor is used")
    try:
        run(args)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
