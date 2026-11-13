# News and A/B/C on common recorded histories

Status: **provider_error**; 34/108 decisions. All outcomes are queries without executions.

A uses raw observations and actual recent outcomes. B adds computed facts. C adds two generated reflections on the same actual A-market past, with its pre-news diary shared across headline variants. Three fresh repetitions per cell were planned; delivered counts are shown below. Four reused actual states, not held-out markets or an endogenous C trajectory. This is not a news-retention or profitability experiment.

Coverage: 34/36 cells have any response; 0/36 have all three planned repeats. Delivery gaps cannot establish a mode benefit. [Remaining-work inventory](remaining_work.json) records pending inputs and budgets; it does not resume the study.

| Frame | Stock weight | Market-buy capacity | Sell capacity |
| --- | ---: | ---: | ---: |
| s1441_llm_012 | 36.51% | 101 | 70 |
| s1441_llm_013 | 99.68% | 0 | 192 |
| s2882_llm_012 | 49.42% | 85 | 100 |
| s2882_llm_013 | 99.92% | 0 | 200 |

Signed accepted shares by repetition (missing replies are not HOLD zeros). Positive quantities buy; negative quantities sell. No direction is a correctness oracle.

| Frame / mode | No headline | Positive | Negative | Positive minus silent | Negative minus silent |
| --- | --- | --- | --- | --- | --- |
| s1441_llm_012 / A | +0 | +0 | -10 | +0, missing, missing | -10, missing, missing |
| s1441_llm_012 / B | -10 | +10 | -10 | +20, missing, missing | +0, missing, missing |
| s1441_llm_012 / C | +0 | +20 | -10 | +20, missing, missing | -10, missing, missing |
| s1441_llm_013 / A | +0 | +0 | +0 | +0, missing, missing | +0, missing, missing |
| s1441_llm_013 / B | +0 | +0 | +0 | +0, missing, missing | +0, missing, missing |
| s1441_llm_013 / C | +0 | +0 | +0 | +0, missing, missing | +0, missing, missing |
| s2882_llm_012 / A | +50 | +0 | +0 | -50, missing, missing | -50, missing, missing |
| s2882_llm_012 / B | +50 | +30 | +0 | -20, missing, missing | -50, missing, missing |
| s2882_llm_012 / C | +0 | +20 | +0 | +20, missing, missing | +0, missing, missing |
| s2882_llm_013 / A | -100 | +0 | +0 | +100, missing, missing | +100, missing, missing |
| s2882_llm_013 / B | +0 | -50 | -100 | -50, missing, missing | -100, missing, missing |
| s2882_llm_013 / C | +0 | missing | missing | missing, missing, missing | missing, missing, missing |

Arjun's natural frames cannot fund even one executable buy, while both can sell. That constrains positive-news order responses; persona and headroom are not separately randomized. Reporting accepted orders also does not predict fills. Full requested orders, limits, resource reductions, descriptive variation and missing/failed cases are in report.json and the raw run.

## Cost and interpretation

Usage: `{"requests_made": 49, "max_requests": 264, "reserved_tokens": 641213, "max_reserved_tokens": 4000000, "reserved_cost_usd": 0.0, "max_cost_usd": 0.0, "provider_reported_tokens": 135427, "estimated_mock_tokens": 0, "unknown_usage_requests": 7, "failed_requests": 7, "observed_cost_estimate_usd": 0.0, "blocked_requests": 0, "requests_per_minute": 10, "input_tokens_per_minute": 60000, "stop_on_api_error": true, "provider_stopped": true, "reservation_method": "utf8_bytes_plus_256_and_max_output_no_refunds"}`.

Reflection and decision costs are separated in report.json. Each two-call C chain is shared across three experimental headline branches; that amortization is not a deployment cost estimate. Model: BharatCode qwen-3.8-27b, decision temperature0.3/reflection0, low effort, cap4096, timeout180; sampling unseeded. Common prompt suite v2, memory5, C reflects at5/10 on actual records.

Do not infer full-market effects, human realism or general component superiority from this small conditional study. All cells and directions are retained; further market confirmation needs genuine sequential trajectories and independent scenarios.

[News contrasts](news_contrasts.pdf) | [Full report and audit](report.json)
