---
name: scf
description: Diagnose Quantum ESPRESSO SCF setup and identify a usable mixing_beta range with the bundled scf_slim workflow. Use when the user asks about QE/pw.x, MPI or pseudopotential environment checks, SCF convergence trouble, guarded beta probing, negative-rho/divergence/oscillation/plateau behavior, or interpreting scf_slim outputs.
---

# SCF V1.1

Use this skill for first-pass Quantum ESPRESSO SCF diagnostics. Check whether the QE environment and input look healthy before spending runs on `mixing_beta`, then report a usable beta range with the evidence behind it. Make clear that beta probes use a cheap residual target and that the user should run a full SCF afterward at their required accuracy.

## Bundled Tool

The bundled tool lives under:

```bash
<skill-dir>/scripts/scf_slim
```

Run commands from that directory so imports resolve naturally.
Write outputs to the user's workspace or a temp directory; the installed skill
directory may be read-only.

## Workflow

1. Run the environment doctor before expensive SCF probes:

```bash
cd <skill-dir>/scripts/scf_slim
python3 run_scf.py --doctor --config configs/default.yaml
```

Use `--doctor-json` for machine-readable output, `--doctor-no-run-check` when only discovery is desired, and `--pw`, `--mpirun`, `--pseudo-dir`, `--search-root`, or `--np` to add explicit candidates.

2. If doctor reports missing or unrunnable `pw.x`, missing pseudos, or likely MPI/runtime mismatch, fix that first. Do not start beta probing until the environment is plausible.

3. For beta probing, keep the run diagnostic. Start from a broad practical range, let `scf_slim` evaluate its configured coarse anchors and deterministic bucket refinement, and avoid manual fine sweeps such as `0.57, 0.58, 0.59` unless the user explicitly asks for detailed sensitivity.

The cheap beta-test target is `task.target_residual_ry` in the config. `task.probe_conv_thr_ry` is the QE `conv_thr` injected into probe inputs, and `task.final_conv_thr_ry` applies only to the optional final verification run.

4. Run a diagnostic probe:

```bash
python3 run_scf.py \
  --config configs/batio3_initial_beta.yaml \
  --bench configs/benchmark.yaml \
  --system BaTiO3 \
  --outdir /path/to/workspace/out/BaTiO3_initial
```

For a custom system, use `--template /path/to/system_scf.in` instead of `--bench`.

5. Summarize the result as a beta range, a practical default beta, and evidence from `summary.csv` and `console.log`. Remind the user to rerun a full SCF with their production `conv_thr` and physical convergence settings.

## Interpretation Rules

- Treat small differences between nearby beta values as numerical noise unless they are large and repeatable.
- Prefer robust ranges, e.g. `0.50-0.60`, over precise claims like `0.59 is optimal`.
- If all tested beta values fail or behave abnormally, do not recommend a beta. Tell the user this is likely an input, structure, pseudo, occupation, cutoff, k-point, charge, spin, or runtime problem.
- If `negative rho` appears across beta values, prioritize checking structure, pseudo compatibility, `ecutrho`, and atom overlaps.
- If many `c_bands not converged` messages appear, check occupations, smearing, metallicity, diagonalization settings, and `nbnd`.
- If every beta oscillates, check occupations, `mixing_mode`, charge/spin setup, and initial magnetic moments.
- If every beta times out but residuals decrease, the system may simply be large or the threshold too strict.

## Outputs To Inspect

- `summary.csv`: beta, success flag, S4, steps, stop reason, oscillation hits, and output paths.
- `console.log`: probe order, bucket/coarse-search decisions, and final recommendation.
- `<system>_recommendation.json`: recommendation and search report.
- per-job `scf.out`: raw QE evidence for suspicious runs.

## Scope

This skill can:

- discover and lightly validate `pw.x`, MPI launchers, and pseudopotential paths;
- render QE SCF templates with candidate `mixing_beta` values;
- run guarded SCF probes with divergence, oscillation, plateau, timeout, and negative-rho handling;
- identify a usable beta range;
- detect when the problem is probably not beta and should be debugged as an input/environment issue;
- produce concise, evidence-backed recommendations.

This skill should not:

- claim a single exact best beta from a diagnostic run;
- run precision beta sensitivity studies unless the user explicitly asks for them;
- replace full convergence testing for cutoff, k-points, pseudos, occupations, or relax/vc-relax settings.
