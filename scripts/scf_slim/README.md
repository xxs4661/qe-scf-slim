# SCF Slim

This directory contains the standalone Python CLI used by the `$scf` skill.
The tool renders QE templates, runs guarded `pw.x` probes, and writes enough
logs to explain why a beta range was chosen.

The search is intentionally simple: coarse anchors first, deterministic bucket
refinement second. Bad probes are stopped early when the residual history points
to divergence, oscillation, a plateau, timeout, or excessive negative rho.

Probe runs are evaluated against `task.target_residual_ry`, a deliberately loose
target used to compare beta values cheaply. After choosing a beta, run your own
full SCF at the convergence threshold required by the actual calculation.

## Layout

- `run_scf.py`: CLI entry point.
- `parser.py`: parser for existing QE `scf.out` files.
- `scfopt/config.py`: YAML config, presets, benchmark/template loading.
- `scfopt/doctor.py`: QE, MPI, and pseudo discovery.
- `scfopt/guards.py`: near-target, divergence, oscillation, plateau, and negative-rho guards.
- `scfopt/workflow.py`: probe/search/final-verification flow.
- `scfopt/qe_input.py`, `scfopt/qe_runner.py`, `scfopt/process_monitor.py`: QE input rendering and process control.
- `scfopt/search.py`, `scfopt/buckets.py`: deterministic beta proposal and bucket summaries.
- `scfopt/output.py`, `scfopt/plots.py`, `scfopt/logging_utils.py`: output helpers.

## Smoke test

This does not run QE:

```bash
cd scf_slim
python3 run_scf.py --doctor --doctor-no-run-check
python3 run_scf.py --config configs/default.yaml --bench configs/benchmark.yaml --system Fe_bcc --outdir /path/to/workspace/out/smoke --dry-run
python3 run_scf.py --bench configs/benchmark.yaml --list-systems
python3 -m py_compile run_scf.py parser.py scfopt/*.py
```

## Environment doctor

Before spending time on beta probes, check the local QE setup:

```bash
python3 run_scf.py --doctor --config configs/default.yaml
```

The doctor looks for `pw.x`, `mpirun`/`mpiexec`/`srun`, and plausible pseudo
directories. It prints a `qe:` YAML snippet you can copy into a config. Its run
checks are lightweight, roughly `pw.x -h`, not an SCF calculation.

## Real run

Edit `configs/default.yaml` first:

- `qe.pw`
- `qe.mpirun` and `qe.np` if using MPI
- `qe.env.ESPRESSO_PSEUDO`
- `task.beta_range`
- `task.target_residual_ry`: cheap residual target used to score beta probes
- `task.probe_conv_thr_ry`: QE `conv_thr` injected into probe inputs
- `task.final_conv_thr_ry`: QE `conv_thr` for the optional final verification
- `preset`: `smoke`, `default`, or `thorough`

Preset values are applied after ordinary config values. Put deliberate
exceptions under `overrides:`.

Then run:

```bash
cd scf_slim
MPLCONFIGDIR=/tmp/mpl-cache python3 run_scf.py \
  --config configs/default.yaml \
  --bench configs/benchmark.yaml \
  --system Fe_bcc \
  --outdir /path/to/workspace/out/Fe_bcc
```

Use `--template /path/to/system_scf.in` instead of `--bench` for a single custom template.

For BaTiO3 initial-beta probing, start from:

```bash
python3 run_scf.py \
  --config configs/batio3_initial_beta.yaml \
  --bench configs/benchmark.yaml \
  --system BaTiO3 \
  --outdir /path/to/workspace/out/BaTiO3_initial
```

That config uses bucket mode with an edge-neighbor check. If the best beta sits
on a bucket boundary, the next probe moves inward before the tool gives up on
the rest of the bucket.

The recommendation is a beta-tuning result, not a production SCF result. Use the
chosen beta in a final standalone QE SCF run with your required `conv_thr` and
fully converged physical settings.
