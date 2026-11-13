# Fresh seed-42 equal correction — launched 10 November 2026

Latest user explicitly authorized correction of the replay defect, using
`ANOTHER_GODEL_MACHINES_API_KEY` and unchanged pacing. This is a narrow exception
to older collection-freeze notes, not authorization for additional studies.

- Attempt 1 history: PID 5772 launched at 09:54 IST, delivered 167 decisions across 13 full
  rounds, and halted at round 14 due to a Windows/OneDrive file-lock collision on `summary.json`.
  Attempt 1 is preserved intact in `runs/wealth_s42_equal_fresh_correction_crashed_round14_20261110`.
- Fix applied: `run_wealth_correction.py` upgraded with `safe_write_json` using thread-specific
  temporary files (`.pid.ident.tmp`), a 10-attempt backoff retry loop, and exception shielding
  so file-sync locks never abort agent decisions or the simulation loop.
- Root: `runs/wealth_s42_equal_fresh_correction_20261110`
- One seed-42 equal, 12-LLM, 100-round market, 1,200 fresh decisions; strictly zero replay.
- 110 RPM, four concurrent workers, 200,000 estimated input TPM preserved.
- One-arm ceilings: 1,500 attempts / 24,000,000 reserved tokens (one quarter of
  original four-market ceilings). Same model, prompts, economics and fast-runner
  seed offsets. Global fatal-error stop enabled; returned model/finish checked.
- No automated restarts, continuation roots, other arms or provider probes.
- Launcher: `run_wealth_correction.py`; delivery: `fresh_correction_delivery.py`.
  Original runner, delivery and engine files remain byte-identical.
- Three offline tests pass, including the complete network-blocked 1,200-response
  synthetic run with 2,000 account-round checks, replay rejection, wrong-model
  refusal and overwrite refusal. Synthetic results are not scientific evidence.
- First twelve real responses reported the intended model; zero replay records.
- Standard output/error: `runs/wealth_correction_20261110_stdout.txt` and
  `runs/wealth_correction_20261110_stderr.txt`.

While running, summary `delivered_responses` and usage are current. Its
`completed_rounds` is only finalized on completion; count `kind=round` in the
market ledger for intermediate cleared-round progress. No live source edits.

On success the worker writes `financial_verification.json` (fresh request/persona
association and all account transitions), corrects manifest request counts,
closes its scoped protocol and writes `output_hashes.json`. On failure it records
stopped status and closes without silently resuming. Inspect actual results before
claiming complete or revising scientific conclusions.

The original seed-42 equal hybrid remains invalid as adaptive evidence and must
stay preserved. A successful replacement is a new provider realization after the
audit with a different named credential/date, not retroactive repair. Existing
three fresh markets remain unchanged. The thesis strategy's diagnosis remains
historically true; integrate the replacement separately only after completion and
audit, retaining this provenance caveat.
