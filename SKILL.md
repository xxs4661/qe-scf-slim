---
name: scf
description: Identify which Quantum ESPRESSO pw.x SCF jobs need intervention from existing logs, cite the evidence, and recommend a targeted next action.
---

# Triage SCF calculations

Use `scf-slim triage PATH...` for a batch or directory. For a source checkout, run `python3 <skill-dir>/scripts/scf_slim/run_scf.py triage PATH...`. The command reads the logs offline.

1. Report the counts of jobs marked `intervene`, `review` and `none`, and any read errors. Start with the calculations that need intervention.
2. Run `scf-slim diagnose FILE --json` on a flagged job. Report the reason and next action from `intervention`. Cite the original records at `evidence_lines`. Preserve the operator and Ry units for the printed accuracy estimate.
3. Use the scheduler and latest output to clarify a partial job. Check the input and reported failure first when the log cites a missing file, a resource limit or a short iteration budget.
4. If a terminated run shows repeated rebounds with little net progress, check the structure and occupations. A single lower-beta retry with other inputs fixed tests the mixing hypothesis. Compare the two outputs with `scf-slim compare`. A converged run with no flagged issues needs no SCF intervention.

A broad live beta scan consumes allocation. Use it only when requested or when the user has chosen it after seeing the evidence. Install the probe extra, check `scf-slim probe --doctor`, and inspect the budget with `scf-slim probe --template input.in --outdir /path/to/workspace/scan --dry-run`. Write outputs in the workspace. A successful finalist verifies convergence for those inputs; a speedup claim also needs the direct baseline, all trial costs and comparable production outputs.

For reproducible examples, use the silicon and Al(111) jobs in `examples/`. The electronic verdict concerns the final cycle of the latest invocation. Physical cutoff, k-point, ionic and hybrid outer-loop convergence have separate criteria.
