# QE SCF Slim 0.2.0 Test Report

Date: 2026-07-10

Scope: reliability release excluding real Quantum ESPRESSO benchmark calculations, per project request.

## Automated tests

All 42 collected tests passed in isolated shards:

- Core configuration, guards, manifest, parser, preflight, input rendering, launcher/process control, and scoring: **34 passed**.
- Resume/checkpoint compatibility and probe deduplication: **2 passed**.
- Light seed reuse and QE `from_scratch` semantics: **1 passed**.
- End-to-end fake-`pw.x` workflows: **5 passed**.

Total: **42 passed, 0 failed**.

The end-to-end suite covers verified recommendations, probe-only mode, verification failure revoking a recommendation, target crossing followed by rebound, and fatal runtime fail-fast behavior.

## Build and smoke checks

- `python -m compileall -q scripts tests`: passed.
- Wheel build: passed.
- Source distribution build: passed.
- `scf-slim --version`: returned `qe-scf-slim 0.2.0`.
- Wheel installation into a clean virtual environment and CLI import smoke check: passed.

## Deliberate exclusion

No real Quantum ESPRESSO material benchmark results were generated or claimed. Synthetic tests validate workflow correctness, not physical accuracy or performance on real materials.
