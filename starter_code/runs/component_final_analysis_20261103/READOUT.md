# News and A/B/C on common recorded histories

Status: **completed_all_scheduled_cases**; 108/108 cases resolved, 107 valid orders and 1 failed/missing. No executions.

A uses raw observations and actual recent outcomes. B adds computed facts. C adds two generated reflections on the same actual A-market past, with its pre-news diary shared across headline variants. Three fresh repetitions per cell were planned; delivered counts are shown below. Four reused actual states, not held-out markets or an endogenous C trajectory. This is not a news-retention or profitability experiment.

Coverage: 36/36 cells have resolved slots; 35/36 have three valid replies. Missing outputs are not HOLD zeros. [Remaining-work inventory](remaining_work.json) records unresolved inputs/budgets; it does not resume the study.

## What this experiment shows

**HOLD can be a response to good news.** In Arjun's seed2882 state, A requests sells of 100/80/0 shares without news and HOLD/HOLD/HOLD after the positive forecast. The mean headline-minus-silent change is +60 signed shares, although no BUY is affordable. Measuring BUY frequency alone would miss this response. These are order intentions, not executed shares.

**There is no uniform component upgrade here.** In Meera's seed2882 state, positive-news contrasts are-50/-30/+40 for A,-20/+20/0 for B and+20/+20/+30 for C. C is more consistent in that particular contrast. In her other state, B's contrasts are+20/+10/+10 and C's+20/+10/0. Negative-news patterns differ too. Baseline no-news decisions also change across modes; larger headline contrasts do not by themselves establish better trading or human realism.

**Constraints are part of the explanation.** Arjun's seed1441 frame produces HOLD in all 27 valid queries, including nine negative-news queries with 192 shares available to sell. Buying limits do not explain every null, and a HOLD does not reveal whether beliefs changed.

**Reflection adds measured cost.** The 24 reflection calls used 59,907 reported tokens, beyond C's decision calls. A used 113,515, B 120,274, and C decisions 130,346 reported tokens. One C decision exhausted 4096 reasoning tokens and returned no order; it stays missing and was never resampled. Sharing each diary across three branches makes these experimental costs, not deployment estimates.

These are exploratory conditional results on four reused states. Keep A as the reference and B/C selectable; test execution, market paths and costs in fresh sequential markets before promoting a more complex agent.

## Stored account states

| Frame | Stock weight | Market-buy capacity | Sell capacity |
| --- | ---: | ---: | ---: |
| Meera / 1441 | 36.51% | 101 | 70 |
| Arjun / 1441 | 99.68% | 0 | 192 |
| Meera / 2882 | 49.42% | 85 | 100 |
| Arjun / 2882 | 99.92% | 0 | 200 |

Signed accepted shares by repetition (missing replies are not HOLD zeros). Positive quantities buy; negative quantities sell. No direction is a correctness oracle.

| Frame / mode | No headline | Positive | Negative | Positive minus silent | Negative minus silent |
| --- | --- | --- | --- | --- | --- |
| Meera / 1441 / A | +0, -10, +0 | +0, +0, +20 | -10, -10, -10 | +0, +10, +20 | -10, +0, -10 |
| Meera / 1441 / B | -10, -10, -10 | +10, +0, +0 | -10, -10, -10 | +20, +10, +10 | +0, +0, +0 |
| Meera / 1441 / C | +0, -10, +0 | +20, +0, +0 | -10, -10, -20 | +20, +10, +0 | -10, +0, -20 |
| Arjun / 1441 / A | +0, +0, +0 | +0, +0, +0 | +0, +0, +0 | +0, +0, +0 | +0, +0, +0 |
| Arjun / 1441 / B | +0, +0, +0 | +0, +0, +0 | +0, +0, +0 | +0, +0, +0 | +0, +0, +0 |
| Arjun / 1441 / C | +0, +0, +0 | +0, +0, +0 | +0, +0, +0 | +0, +0, +0 | +0, +0, +0 |
| Meera / 2882 / A | +50, +50, +0 | +0, +20, +40 | +0, +0, +0 | -50, -30, +40 | -50, -50, +0 |
| Meera / 2882 / B | +50, +0, +0 | +30, +20, +0 | +0, +0, +0 | -20, +20, +0 | -50, +0, +0 |
| Meera / 2882 / C | +0, +0, +0 | +20, +20, +30 | +0, missing, +0 | +20, +20, +30 | +0, missing, +0 |
| Arjun / 2882 / A | -100, -80, +0 | +0, +0, +0 | +0, -100, -100 | +100, +80, +0 | +100, -20, -100 |
| Arjun / 2882 / B | +0, +0, +0 | -50, +0, +0 | -100, +0, -100 | -50, +0, +0 | -100, +0, -100 |
| Arjun / 2882 / C | +0, +0, +0 | +0, +0, +0 | -50, -60, +0 | +0, +0, +0 | -50, -60, +0 |

## Mean headline-minus-silent contrasts

Shares, with available matched-frame repetitions in parentheses. These are descriptive repeated replies, not independent markets or confidence intervals. Missing replies are excluded explicitly, never imputed as zero.

| Frame / mode | Positive minus silent | Negative minus silent |
| --- | ---: | ---: |
| Meera / 1441 / A | +10.00 (n=3) | -6.67 (n=3) |
| Meera / 1441 / B | +13.33 (n=3) | +0.00 (n=3) |
| Meera / 1441 / C | +10.00 (n=3) | -10.00 (n=3) |
| Arjun / 1441 / A | +0.00 (n=3) | +0.00 (n=3) |
| Arjun / 1441 / B | +0.00 (n=3) | +0.00 (n=3) |
| Arjun / 1441 / C | +0.00 (n=3) | +0.00 (n=3) |
| Meera / 2882 / A | -13.33 (n=3) | -33.33 (n=3) |
| Meera / 2882 / B | +0.00 (n=3) | -16.67 (n=3) |
| Meera / 2882 / C | +23.33 (n=3) | +0.00 (n=2) |
| Arjun / 2882 / A | +60.00 (n=3) | -6.67 (n=3) |
| Arjun / 2882 / B | -16.67 (n=3) | -66.67 (n=3) |
| Arjun / 2882 / C | +0.00 (n=3) | -36.67 (n=3) |

Arjun's natural frames cannot fund even one executable buy, while both can sell. That constrains positive-news order responses; persona and headroom are not separately randomized. Reporting accepted orders also does not predict fills. Full requested orders, limits, resource reductions, descriptive variation and missing/failed cases are in report.json and the raw run.

## Cost and interpretation

139 HTTP attempts;424,042 provider-reported tokens plus7 unknown-usage requests. Conservative reservations:1,816,876/4,000,000; request cap264. Full accounting is in report.json.

Reflection and decision costs are separated in report.json. Each two-call C chain is shared across three experimental headline branches; that amortization is not a deployment cost estimate. Model: BharatCode qwen-3.8-27b, decision temperature0.3/reflection0, low effort, cap4096, timeout180; sampling unseeded. Common prompt suite v2, memory5, C reflects at5/10 on actual records.

Three linked phases are preserved: an early503 stop, a later output-cap stop, and an explicit post-failure batch-stop amendment that retains capped replies as missing and attempts the other independent cases. No failed choice was resampled or given a larger budget. First-repeat final-frame C news replies span a delivery-time gap. The model alias has no pinned backend fingerprint. These limitations remain even when every scheduled case is resolved.

Do not infer full-market effects, human realism or general component superiority from this small conditional study. C/B also includes retention of older common-history facts, not only extra reasoning. All cells and directions are retained; further market confirmation needs genuine sequential trajectories and independent scenarios.

[News contrasts](news_contrasts.pdf) | [Full report and audit](report.json)
