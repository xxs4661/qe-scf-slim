# Migration from 0.1.x to 0.2.0

## Defaults no longer override the template

`task.fixed_degauss` and `task.mixing_mode` now default to `null`. Add explicit values only when all probes should override the QE template.

## Recommendation fields

Use `recommendation_status` before consuming `recommended_beta`:

- `verified`: recommendation passed full SCF verification;
- `probe_only`: candidate comes only from diagnostic probes;
- `verification_failed`, `no_feasible_beta`, or `runtime_error`: `recommended_beta` is null.

For diagnostic inspection, use `probe_recommended_beta`, `best_observed_beta`, `observed_safe_interval`, and `observed_safe_segments`.

## Output directory behavior

A non-empty output directory is rejected by default. Add `--resume` for a compatible existing run or `--overwrite` to start cleanly.

## MPI configuration

Legacy `qe.extra_args` is still accepted as an alias for `qe.pw_args`. New configurations should separate:

```yaml
qe:
  launcher_args: []
  pw_args: []
```

## Seed behavior

Set both `task.seed_from_file: true` and `task.seed_dir: /path/to/prefix.save`. The tool copies a light seed and uses a new `from_scratch` calculation with file density. It no longer treats the new probe as a restart.

## Preflight

Normal runs now validate the exact UPF files referenced by the template. Correct `qe.env.ESPRESSO_PSEUDO` before launching. Use `--skip-preflight` only in externally validated workflows.
