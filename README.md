# QE SCF Slim

Read Quantum ESPRESSO `pw.x` output and decide which self-consistent-field (SCF)
calculations need attention. `scf-slim diagnose` gives a verdict with source
line numbers. `scf-slim compare` turns a batch of logs into a table or JSON for
a job pipeline. If a calculation genuinely needs a different mixing factor,
`scf-slim probe` can test candidates against the same input.

[中文快速上手](README.zh-CN.md)

## Try it on two real calculations

The repository includes stdout from two silicon runs with identical inputs
except for the electronic iteration limit. Both printed `JOB DONE.`

~~~sh
git clone https://github.com/xxs4661/qe-scf-slim.git
cd qe-scf-slim
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
scf-slim compare examples/si-*.out
scf-slim diagnose examples/si-maxstep.out
~~~

| File | Verdict | Last SCF iteration | Last printed SCF accuracy |
| --- | --- | ---: | ---: |
| `si-converged.out` | converged | 10 | < 4.7e-9 Ry |
| `si-maxstep.out` | unconverged | 2 | < 0.01224138 Ry |

The second input allowed just two iterations. Inspecting the cited convergence
message and the iteration budget is a better first step here than starting a
mixing-factor sweep. The inputs, outputs, pseudopotential checksum, and commands
to reproduce both runs are in the [example directory](examples/README.md).

## Use it on a cluster

The offline commands require Python 3.10+ and use its standard library.
They work on a login node without QE, MPI, pseudopotentials, or network access.
An uninstalled checkout works too, using `python3 scripts/scf_slim/run_scf.py`
in place of `scf-slim`.

~~~sh
scf-slim diagnose scratch/Fe/scf.out.gz
scf-slim compare runs/*/scf.out
scf-slim diagnose - --json < scratch/Fe/scf.out > fe-diagnosis.json
scf-slim compare --check --json runs/*/scf.out > batch.json
~~~

By default, a readable log produces a report and exit code **0**, including for
failed calculations. With `--check`, **1** means at least one calculation needs
attention. **2** means the command line or an input file could not be read.
Batch JSON keeps the result for each file in argument order with aggregate
counts. Individual JSON includes the last electronic cycle's accuracy history,
units in field names, numbered evidence, and interpretation.

| Verdict | Evidence |
| --- | --- |
| `converged` | The latest electronic cycle reports convergence and the invocation prints its completion footer. |
| `unconverged` | QE explicitly reports that electronic convergence was not achieved. |
| `incomplete` | A recognized calculation is still open, stopped early, or lacks definitive final output. |
| `failed` | A recognized run reports a fatal error or a nonfinite final electronic energy or accuracy estimate. |
| `unsupported` | The log is unrecognized or identifies a calculation outside the supported SCF scope. |

For appended outputs the newest invocation wins. The comparison uses each
run's final electronic cycle and the wall time printed for that invocation.
Compare iteration counts across runs with the same structure, thresholds and
physics. QE's estimated SCF accuracy is an estimate of the energy error in Ry.
Electronic convergence alone does not establish convergence of the k-point mesh
or basis cutoff. The tool targets ordinary electronic SCF runs. Identifiable
bands, NSCF, relaxation, MD and hybrid outer-loop outputs get an unsupported
verdict. Very short fragments can omit the markers needed to identify a mode.
See the [QE input reference](https://www.quantum-espresso.org/Doc/INPUT_PW.html)
and [QE troubleshooting guide](https://www.quantum-espresso.org/Doc/pw_user_guide/node21.html).

## Probe mixing beta on your own input

Install the live extras and point the tool at a usable SCF template. A dry run
prints the effective configuration, candidates and budget before launching QE.

~~~sh
python -m pip install '.[probe]'
scf-slim probe --doctor
scf-slim probe --template silicon.in --outdir runs/si --dry-run
scf-slim probe --template silicon.in --outdir runs/si
~~~

The default setup runs `pw.x` on one rank. Relative `pseudo_dir` values are
resolved from the template's directory. An explicit `ESPRESSO_PSEUDO` in the
config or environment takes precedence. Probes preserve the template's smearing
width and mixing mode by default. Use `--config` to change the launcher, probe
budget, guard thresholds or verification settings. Start with
[default.yaml](scripts/scf_slim/configs/default.yaml) or see the
[benchmark and configuration guide](scripts/scf_slim/README.md).
The original flag-based `scf-slim --config ...` invocation is also supported.

Each probe writes its rendered input and stdout under `jobs/`. Reusing an
output directory keeps earlier evidence and puts the new run in a unique
`run-*` subdirectory. The JSON field `outdir` gives the actual location. Read
`summary.csv` alongside `<system>_recommendation.json`. The default search
uses a cheap target of 1e-4 Ry to screen candidates, then checks the selected
beta in a fresh SCF at 1e-8 Ry. The recommendation records whether verification
succeeded (`verified`), was disabled (`probe_only`), or failed
(`verification_failed`). A search without a qualifying probe records
`no_candidate`. The latter two outcomes leave `recommended_beta` empty and
return exit code 1. Review the full SCF log before using a beta in production.

## Development

~~~sh
python -m pip install -e '.[dev,probe]'
python -m pytest
~~~

The test suite runs offline against saved QE outputs. To repeat the calculations
themselves, use the [silicon example](examples/README.md). Licensed under
the [MIT License](LICENSE).
