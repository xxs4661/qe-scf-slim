# QE SCF Slim

QE SCF Slim is a small diagnostic wrapper for Quantum ESPRESSO `pw.x` SCF runs.
Its main purpose is to cut down the manual trial-and-error around
`mixing_beta`.

In a typical difficult SCF setup, the slow part is not editing one input file.
It is the loop around it: choose a beta, run `pw.x`, watch whether the residual
falls or blows up, stop hopeless runs, record the useful evidence, pick the next
beta, and repeat. QE SCF Slim automates that loop enough to answer the practical
question:

> Which beta values are safe enough to use for this system, on this QE setup,
> with this template?

The tool first checks that the runtime environment is plausible, then runs a
bounded set of guarded probes. Those probes are judged against a deliberately
loose and relatively cheap residual target, so beta values can be compared
without paying for a full production SCF at every trial point. The output is a
usable beta range, a suggested default, and the raw evidence behind the
recommendation.

It does not try to replace physical convergence testing, and it does not claim
that one beta is mathematically best. After the diagnostic run finishes, use
the recommended beta in a separate full SCF calculation with the convergence
thresholds required by your actual study.

## Manual work it replaces

Without this tool, beta tuning usually means doing these steps by hand:

1. Edit `mixing_beta` in a QE input.
2. Launch `pw.x`, sometimes through MPI.
3. Watch the SCF residuals for divergence, oscillation, stalls, timeouts, or
   negative-rho warnings.
4. Kill runs that are obviously going nowhere.
5. Save the final residual, number of steps, stop reason, and output path.
6. Decide which beta to try next.
7. Repeat until a usable range is clear.

QE SCF Slim keeps that workflow explicit, but makes it reproducible. It renders
the input files, monitors the run, stops bad probes early, writes the summaries,
and chooses the next beta from a small deterministic search plan.

## How the workflow works

1. **Doctor check**: find `pw.x`, MPI launchers, and pseudopotential directories
   before starting expensive SCF probes.
2. **Template rendering**: keep your QE template, but inject the beta, output
   directory, convergence threshold, electron max steps, and selected
   `mixing_mode`.
3. **Guarded probes**: run candidate betas while monitoring the live QE output.
   A probe can stop early on timeout, divergence, persistent oscillation,
   plateau, near-target residual, or excessive negative rho. The near-target
   residual is intentionally cheaper than a production SCF threshold.
4. **Coarse search**: start from a small set of broad beta anchors instead of a
   dense grid.
5. **Bucket refinement**: refine only the region that looks useful, then stop
   when the bracket or budget is small enough.
6. **Recommendation**: write a beta range and default beta backed by
   `summary.csv`, `console.log`, `<system>_recommendation.json`, and per-job
   `scf.out` files.

## What it checks

- `pw.x`, MPI launchers, and pseudopotential directories.
- QE SCF templates rendered with different `mixing_beta` values.
- Probe runs that diverge, oscillate, stall, time out, or hit negative-rho
  warnings.
- Coarse beta anchors followed by deterministic bucket refinement.
- Run artifacts: `summary.csv`, `console.log`, residual plots, per-job
  `scf.out`, and `<system>_recommendation.json`.

## What it does not tune

If every beta fails, the next step is usually not a finer beta scan. Check the
structure, pseudopotentials, cutoffs, k-points, occupations, charge/spin setup,
smearing, and runtime/MPI configuration first.

This tool is deliberately focused on SCF beta diagnostics. It does not replace
cutoff convergence, k-point convergence, pseudopotential validation, relax or
vc-relax testing, or a final production-quality SCF input review.

## Probe threshold vs final SCF threshold

QE SCF Slim uses a cheap residual target to compare beta values. By default,
that target is:

```yaml
task:
  target_residual_ry: 1.0e-4
```

Edit `task.target_residual_ry` in `scripts/scf_slim/configs/default.yaml` or in
your copied config to change the threshold used for beta scoring and near-target
early stopping. A smaller value makes beta probes more expensive; a larger value
makes them cheaper but less discriminating.

There are two related settings:

- `task.probe_conv_thr_ry`: the QE `conv_thr` injected into each probe input.
  The default is stricter than `target_residual_ry`; with guards enabled, probes
  can still stop once they have reached the cheaper target and a few confirming
  steps.
- `task.final_conv_thr_ry`: the QE `conv_thr` used only by the tool's optional
  final verification run.

For production data, do not stop at the diagnostic recommendation. Take the
recommended beta, put it in your real QE input, and run a normal SCF calculation
with the `conv_thr`, cutoffs, k-points, occupations, and other settings required
by your accuracy target.

## Repository layout

- `SKILL.md`: Codex skill instructions.
- `agents/openai.yaml`: Codex UI metadata.
- `scripts/scf_slim/run_scf.py`: CLI entry point.
- `scripts/scf_slim/scfopt/`: core diagnostic package.
- `scripts/scf_slim/configs/`: example configs and QE templates.
- `tests/`: smoke and unit tests that do not require a working QE install.

## Requirements

- Python 3.10 or newer.
- PyYAML and Matplotlib.
- Quantum ESPRESSO `pw.x` for real SCF runs.
- MPI launcher such as `mpirun`, `mpiexec`, or `srun` only when your QE setup
  needs it.
- UPF pseudopotentials compatible with your templates.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

For a quick local checkout, installing `scripts/scf_slim/requirements.txt` is
also enough to run the source CLI directly.

## Codex skill use

Place this repository at:

```bash
~/.codex/skills/scf
```

Then ask Codex to use `$scf` when working on QE SCF diagnostics.

## Quick smoke checks

These commands do not run a real SCF calculation:

```bash
cd scripts/scf_slim
python run_scf.py --doctor --doctor-json --doctor-no-run-check --config configs/default.yaml
python run_scf.py --bench configs/benchmark.yaml --list-systems
python run_scf.py --config configs/batio3_initial_beta.yaml --bench configs/benchmark.yaml --system BaTiO3 --outdir /tmp/scf_slim_smoke --dry-run
```

## Running a probe

First update `configs/default.yaml` or a copied config:

- `qe.pw`
- `qe.mpirun` and `qe.np` if using MPI
- `qe.env.ESPRESSO_PSEUDO`
- `task.beta_range`
- `task.target_residual_ry` for the cheap beta-test target
- `preset`

Then run from `scripts/scf_slim`:

```bash
MPLCONFIGDIR=/tmp/mpl-cache python run_scf.py \
  --config configs/default.yaml \
  --bench configs/benchmark.yaml \
  --system Fe_bcc \
  --outdir /tmp/scf_slim_Fe_bcc
```

For a custom QE template:

```bash
python run_scf.py \
  --config configs/default.yaml \
  --template /path/to/system_scf.in \
  --system MySystem \
  --outdir /tmp/scf_slim_MySystem
```

## Reading the output

Do not judge a run from a single number. Read these files together:

- `summary.csv`: beta, success flag, S4, steps, stop reason, oscillation hits,
  negative-rho diagnostics, and paths.
- `console.log`: probe order, bucket/search decisions, and final recommendation.
- `<system>_recommendation.json`: recommendation and search report.
- per-job `scf.out`: raw QE evidence for suspicious runs.

## Tests

Run the standard-library suite:

```bash
python -m unittest discover -s tests
```

Or run the same tests through pytest:

```bash
python -m pytest
```

The tests avoid real QE execution. They cover configuration merging, template
rendering, guard stop decisions, parser behavior, and CLI smoke commands.

## License

MIT License. See `LICENSE`.
