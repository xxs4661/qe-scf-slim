# QE SCF Slim

A read-only triage tool for Quantum ESPRESSO `pw.x` electronic self-consistent-field (SCF) calculations. Point it at a directory of job logs. It puts jobs that need intervention first, explains the reason, cites the relevant stdout lines and suggests one next action. Triage uses Python 3.10+ and its standard library. It runs on a login node without launching QE.

[中文快速上手](README.zh-CN.md)

## Start with the logs

~~~sh
git clone https://github.com/xxs4661/qe-scf-slim.git
cd qe-scf-slim
python3 scripts/scf_slim/run_scf.py triage --all examples/
python3 scripts/scf_slim/run_scf.py diagnose examples/al111/beta-070.out
~~~

For a command available anywhere, install the checkout in a virtual environment with `python -m pip install .`. Then run `scf-slim triage path/to/jobs/`.

| Decision | What it means | Example action |
| --- | --- | --- |
| `intervene` | The output records a problem that needs a change before the result can be used. | Check a missing UPF, address a scheduler limit, extend a clearly short iteration budget, or test one change to mixing when the history supports it. |
| `review` | The log needs more context or a numerical check. | Check the scheduler for a truncated job or inspect a band warning that persisted to the final electronic iterations. |
| `none` | QE reports electronic convergence and completion, with no issue flagged by these rules. | Keep the SCF result. Validate the k-point sampling and cutoffs for the property you plan to calculate. |

The decision and the QE outcome are separate fields. A live job can have `status=incomplete` and `priority=review`. A converged job can also merit review. A directory read error is reported separately, and readable files still get their own results.

## Cases you can inspect

| Saved job | What QE recorded | What the tool suggests |
| --- | --- | --- |
| Silicon, standard iteration budget | Converged in 10 iterations | Keep the result. |
| Same silicon, budget of 2 iterations | Printed `JOB DONE.` after reporting electronic nonconvergence | Inspect `electron_maxstep` and the requested threshold. |
| Six-layer Al(111), β=0.70 | Large rebounds near the end of a 40-step budget, no convergence | Check the structure and occupations, then compare one controlled retry at lower β. |
| Same Al(111), β=0.20 | Converged in 22 iterations with the same initial conditions | Keep the result. |

**Changing the mixing history reverses the ordering.** In the same slab with the default eight-vector history, both runs converge, β=0.70 in 18 steps and β=0.20 in 27. The two-vector result supports a targeted retry for that input.

The aluminum comparison holds the structure, pseudopotential, k mesh, smearing, mixing mode and history length (`mixing_ndim=2`) fixed. The decision for each log uses only its own contents. A residual pattern can motivate testing a change. The paired calculation supplies the evidence about sensitivity to that change. Open the [Al(111) inputs, logs, residual plot and repeat measurements](examples/al111/README.md) or the [silicon controls](examples/README.md).

## Cluster and pipeline use

~~~sh
scf-slim triage /scratch/my-jobs
scf-slim triage --check --json /scratch/my-jobs > actions.json
scf-slim diagnose - --json < run/scf.out > details.json
scf-slim compare ref/scf.out retry/scf.out.gz
~~~

- `triage` searches directories recursively for `*.out` and `*.out.gz`. Supply explicit paths for other filenames or `-` for stdin. JSON rows carry the QE `status` and `intervention` with `priority`, `code`, `reason`, `next_action` and `evidence_lines`. Counts include all three priorities and `read_error`. The default text focuses on jobs needing attention. Add `--all` to list healthy jobs too.
- `diagnose` shows one decision, the cited source records, the estimated accuracy in Ry and the printed threshold. Its JSON also contains the final electronic cycle's iteration history.
- `compare` keeps the supplied order and shows numerical outcomes side by side. Compare iterations and times at the same physical settings, threshold and resources.
- A successful read returns **0** by default. With `triage --check`, **1** means at least one job needs intervention **or** review. With `diagnose --check` and `compare --check`, **1** tests the reported electronic outcome and means at least one job did not reach `converged`. Input or read errors return **2**.

### How to interpret a mixing recommendation

The tool considers the final cycle of the latest invocation in an appended log. It gives fatal errors and explicit stops their own actions. The mixing rule examines the last 6–8 consecutive printed estimates at a stable observed beta. It requires at least two falls of a factor of two followed by rebounds of a factor of two. It suppresses this signal if the end value or the best value in the second half improves by more than a factor of two relative to the start or first-half best, respectively. These are screening heuristics. In a snapshot with at least 12 iterations and no final outcome, the same pattern prompts a check of the newest stdout and scheduler state. A single spike, tiny fluctuations, or a rapidly decreasing series does not trigger a mixing retry. The cited records let you inspect that judgment yourself. The rules target ordinary electronic SCF. Recognizable relaxation, MD, hybrid and band-structure runs need their own completion criteria. See the [QE troubleshooting guide](https://www.quantum-espresso.org/Doc/pw_user_guide/node21.html) and [pw.x input reference](https://www.quantum-espresso.org/Doc/INPUT_PW.html).

## What three timing rounds showed

Seven SCF settings across five materials were run from scratch with a frozen v0.4.0 classifier. In each round, terminal triage and a single lower-β retry on nonconvergence completed 7/7 jobs with identical solver calls. Triage added 0.055 s per batch to identify the job, cite the evidence and verify the retry. Running both β settings for every case cost 124.86 s, compared with 90.16 s for triage. The five new settings all converged on their first run. Two separate input-fault controls show when identifying the cause avoids a wrong retry. [Timings, raw logs and reproduction instructions](benchmarks/scf-cost-panel/README.md)

## Optional live beta probes

For most jobs, start with the run you already intended to do and triage its output. A parameter search has a real cost. On the small silicon control, direct QE with β=0.70 took 8 electronic iterations. The v0.3.0 default search used 12 trials and a verification run, totaling 99 iterations to obtain the same printed energy. [Recorded cost comparison](examples/si-search-cost.json)

A controlled retry changes one input with the same starting conditions and target. For a broader search, the existing live runner is available explicitly. Install the extra with `python -m pip install '.[probe]'`. Inspect the plan before spending compute time.

~~~sh
scf-slim probe --doctor
scf-slim probe --template silicon.in --outdir runs/si --dry-run
~~~

The default budget permits up to 12 trials and one verification. The screening target is 1e-4 Ry and the default verification threshold is 1e-8 Ry. Use `--config` to change the budget, launcher and thresholds. Relative template `pseudo_dir` values resolve from the template directory. The config or environment variable `ESPRESSO_PSEUDO` takes precedence. The live search preserves the template's smearing width and mixing mode unless explicitly overridden.

Inspect each rendered input and stdout under `jobs/`, plus `summary.csv` and `<system>_recommendation.json`. The latter records `verified`, `probe_only`, `verification_failed` or `no_candidate`. The last two leave the recommended beta empty. Reusing an output location creates a separate run directory. The original flag-based probe command also works. See the [live runner guide](scripts/scf_slim/README.md) and [default configuration](scripts/scf_slim/configs/default.yaml).

## Development

~~~sh
python -m pip install -e '.[dev,probe]'
python -m pytest
~~~

The test suite reads saved outputs offline. The examples include instructions for rerunning the calculations. [MIT License](LICENSE)
