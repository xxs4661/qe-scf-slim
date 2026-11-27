# Two silicon runs with different outcomes

Both logs finish with `JOB DONE.` The two inputs specify the same diamond-Si
primitive cell, 4 × 4 × 4 k-point mesh, PBE pseudopotential, and electronic
convergence threshold of 1e-8 Ry. The only change is `electron_maxstep`.

| Saved stdout | Iteration limit | Reported outcome | Last printed SCF accuracy |
| --- | ---: | --- | ---: |
| [si-converged.out](si-converged.out) | 60 | Converged in 10 iterations | < 4.7e-9 Ry |
| [si-maxstep.out](si-maxstep.out) | 2 | Convergence not achieved after 2 iterations | < 0.01224138 Ry |

From the repository root, inspect the line-numbered evidence or compare the
runs side by side. These commands read the saved output without running QE.

```sh
scf-slim diagnose examples/si-maxstep.out
scf-slim compare examples/si-converged.out examples/si-maxstep.out
```

## Reproduce the pair with pw.x

The files contain the complete stdout from two fresh PWSCF 7.5 calculations
on Apple Silicon using one MPI rank, one OpenMP thread, and one OpenBLAS
thread. The examples exercise electronic convergence. A calculation of material
properties would also need separate tests of k-point sampling and cutoffs.

To rerun, start at the repository root with `pw.x` on your path. The following
commands use a new directory for all inputs, downloads, scratch data and output.
The silicon pseudopotential is the scalar-relativistic PBE ultrasoft entry by
A. Dal Corso in the [Quantum ESPRESSO PS Library table](https://pseudopotentials.quantum-espresso.org/legacy_tables/ps-library/si).

```sh
run_dir=$(mktemp -d)
cp examples/si-*.in "$run_dir/"
cd "$run_dir"
mkdir -p pseudos tmp
pseudo=Si.pbe-n-rrkjus_psl.1.0.0.UPF
curl -fL "https://pseudopotentials.quantum-espresso.org/upf_files/$pseudo" -o "pseudos/$pseudo"
python3 - <<'PY'
import hashlib
from pathlib import Path

pseudo = Path("pseudos/Si.pbe-n-rrkjus_psl.1.0.0.UPF")
if hashlib.sha256(pseudo.read_bytes()).hexdigest() != "669fb75395a9d26973b0ea1ce8223bbcb30d3396c5d48bf5e794d1243c52375a":
    raise SystemExit("Pseudopotential checksum mismatch")
PY
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
pw.x -in si-converged.in > si-converged.out
pw.x -in si-maxstep.in > si-maxstep.out
```

The second calculation intentionally exhausts its two iterations. QE builds and
MPI launchers may return a failure code for this case. Check the electronic
convergence messages in each log. Timings, last digits, and iteration counts can
vary across builds. QE documents how the energy-error estimate relates to
`conv_thr` in the [PWscf input reference](https://www.quantum-espresso.org/Doc/INPUT_PW.html).

For a case with a mixing-dependent outcome, see the [six-layer aluminum slab](al111/README.md).
