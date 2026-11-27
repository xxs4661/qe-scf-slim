from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scf-slim probe", description="Run a bounded search over mixing_beta for an SCF input.")
    parser.add_argument("--config", help="Optional YAML configuration for the search and QE launcher")
    parser.add_argument("--bench", help="Benchmark YAML mapping system names to templates")
    parser.add_argument("--template", help="Single QE input template")
    parser.add_argument("--system", help="Benchmark system or label (defaults to the template filename stem)")
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


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        import yaml
    except ModuleNotFoundError as exc:
        if exc.name != "yaml":
            raise
        parser.error('live probes require the probe extra: python -m pip install ".[probe]" from the checkout')
    try:
        return execute(args, parser)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Probe failed: {exc}", file=sys.stderr)
        return 2


def execute(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from .config import list_systems, load_yaml
    from .doctor import print_report, run_doctor
    from .workflow import run

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
        return 0
    if args.list_systems:
        if not args.bench:
            parser.error("--list-systems requires --bench")
        for system in list_systems(Path(args.bench)):
            print(system)
        return 0
    if not args.system and args.template:
        args.system = Path(args.template).stem
    if not args.system:
        parser.error("supply --system with --bench, or use --template FILE")
    if args.system in {".", ".."} or any(c in "/\\" or ord(c) < 32 for c in args.system):
        parser.error("--system must be a single filename component")
    if not args.outdir:
        parser.error("--outdir is required unless --doctor is used")
    if bool(args.template) == bool(args.bench):
        parser.error("choose one of --template or --bench")
    result = run(args)
    return int(result.get("recommendation_status") in {"verification_failed", "no_candidate"})
