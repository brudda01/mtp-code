# R046 archived-source reproducibility audit

This is offline verification,not a new scientific sample or live-model study.

The final replay results cover8 R039rule markets,16 R041news markets and18
R043component markets:42paths,5144financial rounds,294byte-identical financial
CSV comparisons and712strict recorded-reply consumptions. Socket connections
were blocked;ZERO network attempts occurred. Each request had to match the
saved messages,temperature,output cap,JSON mode,reasoning setting and model.
All original source hashes were checked before execution. The original model
replies were replayed;they were not re-generated or statistically replicated.
Per-replay model logs/summaries retain the ORIGINAL tape's usage metadata.
Those token numbers are not additional provider usage and must not be summed
into live campaign costs. Each regenerated path has a verification marker.

## Files and qualified success

- `replay_report.json`: all study results and original failure/supplement.
- `R039/original_bundle.json` and `R041/original_bundle.json`: passed using their
  prepared source archives in isolated processes.
- `R043/original_bundle.json`: retained import failure before any replay;
  original archive omitted a transitive continuation-helper import.
- `R043/with_archived_dependency.json`: all18 passed after supplying
  `runs/sequential_next_20261103.py` from the sealed R041source snapshot,matching
  the earlier R042hash checkpoint.
- `R043/dependency_supplement.zip`: missing file plus explicit source/hash receipt.
  It does not overwrite any original archive.
- `diagnostics.json`: post-hoc pre/post-reflection gap and all-arm sizing
  diagnostics. These are not new predeclared primary endpoints.
- `audit_source.py` / `replay_worker.py`: exact verification code at execution.
  The current top-level driver additionally accepts a fresh output directory;
  its copy is `audit_cli_source.py`. No simulation-source edit was required.

The separate earlier `../examiner_audit_20261105/setup_failure.json` records
an extractor setup failure:the initial source-only extension guard rejected a
legitimate YAML configuration before replay. That directory was retained;this
v2directory contains the subsequent verification. It is not a failed scientific
case or an omitted provider output.

## Repeat the verification

Use the preserved repository/evidence tree with the original three study
directories. The replay does not need an API key or network. The recorded
Python/library versions are in `environment.json` and `requirements-replay.txt`.
Run from `starter_code` using a NEW output directory:

```text
python -m runs.examiner_audit_20261105 --output runs/examiner_audit_recheck
```

Existing output directories are never overwritten. The driver extracts archived
sources and starts isolated workers;it does not silently import mutable
simulation code from the working tree. In R043it records the missing-dependency
failure,then adds only the explicitly archived companion dependency. Supplying
the old R041source bundle is therefore part of this documented reproduction.

This demonstrates local same-environment reproduction from source snapshots
and saved model outputs. A separate researcher/machine has not performed it.
Fresh provider draws,backend changes,other populations and human/market
generalization are not guaranteed. For an independent-data reflection claim,
read the proposed common-prefix control in the thesis examiner review;no such
new live study has been launched.
