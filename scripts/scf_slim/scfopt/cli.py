"""Command-line interface for offline log analysis and live beta probes."""

from __future__ import annotations

import argparse
import json
import sys
import zlib

from . import __version__
from .compare import add_compare_parser
from .diagnostics import diagnose
from .log_input import open_log


def run_diagnose(args: argparse.Namespace) -> int:
    try:
        with open_log(args.log) as stream:
            report = diagnose(stream)
    except (OSError, EOFError, UnicodeError, zlib.error) as exc:
        if args.json:
            print(json.dumps({"schema_version": 1, "path": args.log, "status": "read_error", "error": str(exc)}))
        else:
            print(f"Cannot read {args.log}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"schema_version": 1, "path": args.log, **report}, indent=2, allow_nan=False))
    else:
        print(f"{args.log}  [{report['status']}]")
        print(f"PWSCF runs: {report['runs']}    SCF cycles in last run: {report['cycles']}")
        if report['iterations'] is not None:
            print(f"Last SCF iteration: {report['iterations']}")
        if report['residual_ry'] is not None:
            print(f"Last estimated SCF accuracy: {report['residual_operator']} {report['residual_ry']:.8g} Ry")
        if report["threshold_ry"] is not None:
            print(f"Requested SCF threshold: {report['threshold_ry']:.8g} Ry")
        if report['energy_ry'] is not None:
            print(f"Final printed total energy (!): {report['energy_ry']:.12g} Ry")
        if report['mixing_betas']:
            print('Observed mixing beta: ' + ', '.join(f'{beta:g}' for beta in report['mixing_betas']))
        if report['wall_seconds'] is not None:
            print(f"PWSCF wall time: {report['wall_seconds']:g} s")
        if report['evidence']:
            print('\nEvidence (source line)')
            for item in report['evidence']:
                print(f"  {item['line']:>6}  {item['text']}")
        if report['advice']:
            print('\nInterpretation')
            for advice in report['advice']:
                print(f'  {advice}')
    return int(args.check and report['status'] != 'converged')


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Forward the original flag-based CLI and the explicit probe subcommand.
    first = argv[0] if argv else ""
    legacy_flags = first.startswith("-") and first not in {"--version", "--help", "-h"}
    if first == "probe" or legacy_flags:
        from .probe_cli import main as probe_main

        return probe_main(argv[1:] if first == "probe" else argv)

    parser = argparse.ArgumentParser(prog='scf-slim', description='Diagnose Quantum ESPRESSO pw.x output and run guarded SCF probes.')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    commands = parser.add_subparsers(dest='command', required=True, metavar='COMMAND')
    cmd = commands.add_parser('diagnose', help='explain one pw.x log with line-numbered evidence')
    cmd.add_argument('log', metavar='LOG', help='pw.x output, a .gz log, or - for stdin')
    cmd.add_argument('--json', action='store_true', help='emit a JSON report including the iteration history')
    cmd.add_argument('--check', action='store_true', help='exit 1 unless the calculation converged')
    cmd.set_defaults(handler=run_diagnose)
    add_compare_parser(commands)
    commands.add_parser('probe', help='run the live beta search or environment doctor (see probe --help)')
    args = parser.parse_args(argv)
    return args.handler(args)
