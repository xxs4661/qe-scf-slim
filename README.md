# QE SCF Slim

QE SCF Slim is an evidence-backed diagnostic wrapper for Quantum ESPRESSO `pw.x` SCF calculations. It automates bounded `mixing_beta` probes, terminates clearly unproductive runs, records raw evidence, and reports either a verified recommendation, a clearly labelled probe-only result, or no recommendation.

Version **0.2.0** is a reliability release. It does not claim to find a mathematically optimal beta and does not replace physical convergence testing.

## Reliability model

A beta is no longer accepted merely because one residual once crossed the diagnostic threshold. A feasible probe must reach `task.target_residual_ry`, stop for an accepted reason, retain a stable raw residual tail, remain below the rebound allowance, avoid an upward tail trend, and avoid fatal QE/runtime diagnostics. Tail regression is signed: a positive `decay_rate` means the residual is decreasing.

The recommendation JSON uses explicit states:

| `recommendation_status` | Meaning |
|---|---|
| `verified` | The selected beta passed the optional full SCF verification. |
| `probe_only` | The diagnostic probes produced a candidate, but verification was disabled. |
| `verification_failed` | Probe evidence existed, but full verification failed; `recommended_beta` is `null`. |
| `no_feasible_beta` | No probe met the stability requirements. |
| `runtime_error` | A fatal input, pseudo, launcher, executable, or QE failure stopped the search. |

`best_observed_beta` is the fastest stable sampled point. `probe_recommended_beta` may prefer the center of a robust sampled segment within the configured S4 tolerance. `observed_safe_interval` is emitted only when multiple sufficiently close successful samples support it; search buckets and sampling brackets are never presented as proven safe ranges.

## Automatic preflight

Normal runs validate the beta range, thresholds, canonical namelist order, required QE cards, `pw.x`, launcher configuration, seed availability, and the exact UPF filenames referenced by `ATOMIC_SPECIES`. The result is saved as `preflight.json` before expensive probes begin.

## Template preservation

The defaults no longer silently replace the template's smearing width or mixing scheme:

```yaml
task:
  fixed_degauss: null
  mixing_mode: null
```

Set either value explicitly only when every probe should use that override.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Runtime dependencies are PyYAML, Matplotlib, and psutil. Real probes additionally require Quantum ESPRESSO `pw.x` and the exact UPF files used by the template.

```bash
scf-slim --version
scf-slim --doctor --config scripts/scf_slim/configs/default.yaml
```

## Run

Edit `scripts/scf_slim/configs/default.yaml`, especially `qe.pw`, launcher settings, `qe.env.ESPRESSO_PSEUDO`, `task.beta_range`, the diagnostic target, and `verify.enabled`.

```bash
scf-slim \
  --config scripts/scf_slim/configs/default.yaml \
  --template /path/to/system_scf.in \
  --system MySystem \
  --outdir /path/to/results/MySystem
```

A benchmark mapping can be used instead of `--template`:

```bash
scf-slim \
  --config scripts/scf_slim/configs/default.yaml \
  --bench scripts/scf_slim/configs/benchmark.yaml \
  --system Fe_bcc \
  --outdir /path/to/results/Fe_bcc
```

## Resume and overwrite

A non-empty output directory requires an explicit choice:

```bash
scf-slim ... --outdir /path/to/results --resume
scf-slim ... --outdir /path/to/results --overwrite
```

`--resume` loads completed probes from `summary.csv` and skips them. `run_manifest.json` fingerprints the system, effective configuration, and template, preventing incompatible results from being combined.

## MPI and scheduler launchers

Launcher arguments and `pw.x` arguments are separate:

```yaml
qe:
  mpirun: srun
  np: 32
  launcher_args: ["--cpu-bind=cores"]
  launcher_count_flag: null
  use_launcher_np: true
  pw: /opt/qe/bin/pw.x
  pw_args: ["-nk", "4"]
```

For a site wrapper that already encodes ranks, set `use_launcher_np: false`. Cleanup never sends a process-group signal to the caller; the direct launcher is controlled through its original `Popen` handle and captured descendants are identity-checked before termination.

## Seed reuse

Set `task.seed_from_file: true` and `task.seed_dir` to an existing `<prefix>.save` directory. The tool copies a light seed, uses `startingpot='file'`, and forces `restart_mode='from_scratch'`. It does not misuse QE's `restart` mode for a new diagnostic calculation.

## Outputs

Read these together:

- `preflight.json`: executable, template, and exact pseudo validation;
- `run_manifest.json`: resume-safety fingerprints;
- `summary.csv`: one evidence record per beta;
- `console.log` and `events.jsonl`: search and stop decisions;
- `<system>_recommendation.json`: explicit status and sampled safe segments;
- `jobs/<prefix>/scf.in` and `scf.out`: rendered input and raw QE evidence;
- `plots/`: optional residual plots.

Important CSV columns include `ok`, `S4`, `stop`, `failure_reason`, `final_residual`, `tail_stable`, `tail_rebound_ratio`, `decay_rate`, `osc_hits`, and `neg_rho_max`.

## Testing

The automated suite uses a deterministic fake `pw.x` and exercises the real subprocess, monitor, parser, guards, search, verification, fail-fast, seed, and resume paths without requiring QE:

```bash
python -m compileall -q scripts tests
python -m pytest -q
python -m build
```

Synthetic scenarios cover stable convergence, threshold crossing followed by rebound, fatal QE output, failed full verification, exact pseudo checks, scheduler command construction, safe process cleanup, and resume without repeated probes.

These tests validate workflow behavior, not physical accuracy. Real QE benchmark result datasets are intentionally outside the 0.2.0 release scope.

## Scope

The tool does not replace cutoff, k-point, pseudopotential, structural, occupations, smearing, magnetism, diagonalization, relaxation, or production-threshold validation. If every beta fails, investigate the physical input and runtime environment rather than requesting a finer beta grid.

MIT licensed. See `LICENSE`, `CHANGELOG.md`, and `MIGRATION.md`.
