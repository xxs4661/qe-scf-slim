"""Rerun the Al(111) comparison in fresh directories with a local copy of pw.x."""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "scripts" / "scf_slim"))
from scfopt.diagnostics import diagnose

PSEUDO = "Al.pbe-n-kjpaw_psl.1.0.0.UPF"
SHA256 = "450c947cbbf30c33a5a77685bbe9a270947816f8a93837c02c749d0ee4e3ab4a"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pw", default="pw.x", help="QE executable, default pw.x on PATH")
    parser.add_argument("--pseudo", required=True, type=Path, help="path to the Al PBE PAW file")
    parser.add_argument("--outdir", required=True, type=Path, help="new directory for the results")
    parser.add_argument("--all-runs", action="store_true", help="also repeat the pair and compare mixing_ndim=8")
    args = parser.parse_args()
    if hashlib.sha256(args.pseudo.read_bytes()).hexdigest() != SHA256:
        parser.error(f"unexpected pseudopotential checksum (expected {SHA256})")
    solver = shutil.which(args.pw)
    if solver is None:
        parser.error(f"cannot find {args.pw}")
    solver = str(Path(solver).absolute())
    args.outdir.mkdir(parents=True, exist_ok=False)
    cases = [("070", 2, 1), ("020", 2, 1)]
    if args.all_runs:
        cases.extend([("020", 2, 2), ("070", 2, 2), ("070", 8, 1), ("020", 8, 1)])
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               VECLIB_MAXIMUM_THREADS="1", JULIA_NUM_THREADS="1")
    mismatches = []
    for beta, ndim, repeat in cases:
        run_dir = args.outdir / f"beta-{beta}-ndim-{ndim}-run-{repeat}"
        run_dir.mkdir()
        source = (HERE / f"beta-{beta}.in").read_text()
        # Keep the original relative paths and give every run an empty scratch directory.
        (run_dir / "pseudos").mkdir()
        shutil.copyfile(args.pseudo, run_dir / "pseudos" / PSEUDO)
        (run_dir / "pw.in").write_text(source.replace("mixing_ndim=2", f"mixing_ndim={ndim}"))
        start = time.monotonic()
        with (run_dir / "pw.out").open("wb") as stdout, (run_dir / "pw.err").open("wb") as stderr:
            result = subprocess.run([solver, "-in", "pw.in"], cwd=run_dir, env=env,
                                    stdout=stdout, stderr=stderr, check=False)
        elapsed = time.monotonic() - start
        with (run_dir / "pw.out").open(encoding="utf-8", errors="replace") as log:
            report = diagnose(log)
        status = report["status"]
        residual = report["residual_ry"]
        accuracy = "unknown" if residual is None else f"{report['residual_operator']} {residual:.6g} Ry"
        print(f"{run_dir.name}: {status}, steps={report['iterations']}, last SCF estimate {accuracy}, "
              f"elapsed={elapsed:.2f}s, process exit={result.returncode}", flush=True)
        # Some QE builds exit nonzero for an explicitly reported iteration limit.
        if (status not in {"converged", "unconverged"} or result.returncode < 0
                or (status == "converged" and result.returncode != 0)):
            print(f"Cannot assess this comparison. Inspect {run_dir}/pw.out and pw.err.", file=sys.stderr)
            return 2
        expected = "unconverged" if (beta, ndim) == ("070", 2) else "converged"
        if status != expected:
            mismatches.append(f"{run_dir.name} reported {status} (expected {expected})")
    if mismatches:
        print("Recorded convergence outcomes differed on this build:")
        for mismatch in mismatches:
            print(f"  {mismatch}")
        return 1
    print("Recorded convergence outcomes reproduced for all requested arms.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except OSError as exc:
        print(f"Cannot run comparison: {exc}", file=sys.stderr)
        sys.exit(2)
