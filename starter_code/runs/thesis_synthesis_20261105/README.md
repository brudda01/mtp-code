# R042: thesis evidence synthesis (2026-11-05)

This is a derived results pack, not a new experiment. It made zero model calls
and generated zero markets. Start with [the thesis brief](../../../THESIS_RESULTS.md).

`synthesize.py` uses Python standard-library calculations and matplotlib for
the exportable `background_tradeoff.png` / `.pdf`. It does not import simulator
or API clients. It verifies nine older archive checksums and ZIP CRCs, compares
six sealed reports/audits byte for byte, then recomputes news responses from
all sixteen actual trade logs and rule-return/inventory statistics from eight
raw market paths. The post-hoc price-path-null example retains both wealth marks.

`report.json` preserves all eight news contrasts, four background differences,
all four rule pairs and nested block contrasts, the fixed historical reference,
component costs with missing-usage caveats and incomplete component arms.
`sources.json` records the original input paths and hashes; `start_state.json`
records the baseline Git revision, uncommitted status and 103 unchanged source
files. Source-study manifests retain exact configs, model and prompts/personas.
The new brief does not reinterpret old failed output as HOLD or successful data.

To reproduce in an independent copy of the repository/evidence, retain this
script and `start_state.json`, omit this pack's generated report/figures, then run
`python starter_code/runs/thesis_synthesis_20261105/synthesize.py`.
The script refuses to overwrite an existing report. Exact PDF byte reproduction
is not promised across matplotlib versions/creation timestamps; numerical data
and the input hashes are the reproducibility targets. `checks.json` records the
final numerical/link/provenance checks. `artifact_manifest.json` seals this pack
and the final brief; the diary records the research decision separately.

No source study, simulator, policy, prompt, persona or economic default changed.
The next possible scientific gap is matched endogenous A/B/C replication if a
stable component claim is central. It is not launched or predeclared here.
