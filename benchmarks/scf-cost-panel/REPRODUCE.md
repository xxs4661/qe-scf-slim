# Reproduce the SCF timing panel

The evidence archive expands directly into the current directory. Use a new empty directory. The seven base inputs, material-specific settings, UPF identifiers and checksums are under `cases/`. Each measured run has `pw.in`, `pw.out`, `pw.err` and `timing.json`. `A` and `B` denote 40 steps at β=0.70 and β=0.20. `E` denotes 80 steps at β=0.70. The data in `results/` are policy replays over these observed runs.

## Check the existing evidence

Verification and accounting need only a standard Python 3.10+ installation. From the extracted directory, point the first command at the original archive.

```sh
python3 pack_evidence.py --verify ../scf-cost-panel.zip
python3 summarize.py --results measured --overheads results/cli-overhead.json --output replay.json
python3 supplement.py --output cost-replay.json
python3 -c 'import json; assert json.load(open("replay.json")) == json.load(open("results/panel-summary.json"))'
python3 -c 'import json; assert json.load(open("cost-replay.json")) == json.load(open("results/cost-details.json"))'
```

The decision engine used for all solver-side diagnoses and CLI timings was `scf-slim 0.4.0`, commit `846f93ab4711752df2c66519844b1add1e68a4b8`. Install this engine to independently check the decisions or repeat the solver runs.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'git+https://github.com/xxs4661/qe-scf-slim.git@846f93ab4711752df2c66519844b1add1e68a4b8'
scf-slim diagnose measured/al111-stress/r1/A/pw.out
scf-slim triage measured/si-short-budget/r1/A/pw.out measured/fe-missing-upf/r1/A/pw.out
```

## Repeat the experiment

The reference machine used Apple M5 (arm64), macOS 26.6.2, Quantum ESPRESSO PWSCF 7.5 through a Julia 1.12.7 JLL launcher, and Python 3.12.14 for the CLI. PW's header reports one MPI process. The runner requests one thread for OpenMP, Julia and the supported math libraries. Each trial starts a fresh process and working directory. The recorded wall clock spans process creation through exit, including launcher startup. Atomic starts and an empty scratch directory prevent electronic state reuse. File-system caches were left enabled. Run serially and wait until QE is idle before timing triage. A native pw.x, a different launcher or a shared cluster will have different absolute times.

```sh
python fetch_pseudos.py
python audit/verify_panel.py --panel . --output physical-audit-replay.json
python audit/verify_incidents.py --panel . --output incident-audit-replay.json
python run_panel.py --pw pw.x --pseudos pseudos --outdir repeat/measured
python measure_triage.py --cli scf-slim --results repeat/measured --output repeat/cli-overhead.json
python summarize.py --results repeat/measured --overheads repeat/cli-overhead.json --output repeat/panel-summary.json
```

The verification scripts check the distributed measurements against raw QE convergence markers and source lines. The first downloads are the public UPFs referenced by each `case.json`. The runner checks their SHA-256 hashes before starting QE. A writeable local scratch filesystem and space for the full panel are required. The terminal policies reuse the same observed solver arms. CLI time includes launching a fresh process, reading the logs and returning the decisions as JSON. Human review time and queue delays are outside the measurement.
