---
name: scf
description: Diagnose Quantum ESPRESSO pw.x SCF output, compare multiple logs, or test mixing_beta on an existing input. Use for electronic convergence, interrupted jobs, QE runtime checks, and guarded beta probes.
---

# Diagnose a Quantum ESPRESSO SCF calculation

The checkout entry point is `python3 <skill-dir>/scripts/scf_slim/run_scf.py`.
An installed copy exposes the same commands through `scf-slim`. Write probe
artifacts into the user's workspace.

## Start with the available evidence

1. Given an existing output, run `scf-slim diagnose FILE --json`. Given several
   outputs, use `scf-slim compare FILE... --json` and inspect the individual logs
   that need attention. Both commands accept gzip files.
2. State the reported outcome for the latest invocation. Cite source lines for
   the convergence verdict and last accuracy estimate, retaining its operator
   and Ry units. A completion footer alone leaves the electronic outcome open.
3. Describe a next action supported by the evidence. For example, when the log
   says QE exhausted two iterations, check the iteration budget and threshold.
   For runtime errors, inspect the reported routine and scheduler stderr.
4. Use full calculation and template context before comparing beta values.
   Ordinary SCF, ionic convergence and hybrid outer-loop convergence have
   different criteria. Identify any calculation outside the parser's scope.

## Run a bounded probe

When the user wants live calculation, install the probe extra, check the
environment with `scf-slim probe --doctor`, and inspect the plan first.

~~~sh
scf-slim probe --template input.in --outdir /path/to/workspace/scan --dry-run
scf-slim probe --template input.in --outdir /path/to/workspace/scan
~~~

A search can also use `--config` with a YAML file and `--bench` with a named
`--system`. Inspect the generated inputs, `summary.csv`, individual `scf.out`
files and `<system>_recommendation.json`. Report the tested beta values, cheap
screening target, verification threshold and outcome. Give a recommendation
only as far as the evidence supports it. Cutoff and k-point convergence need
separate tests for the target property.
