# Fresh sequential market gate

Completed clean live arms: 2/9. This pass targets only seed4103 A/B/C. Other two seeds stay unrun.

First block STOPPED on Meera/C round23 HTTP503 and its one identical-payload retry (also503). A/B are complete24; C ends22 with all eight reflections. Round23 never cleared; Arjun's request was blocked after the provider stop, and round24 was unattempted. These missing outcomes are not HOLD preferences. No rerun, continuation or full-horizon C result.

24 rounds; public forecast plus actual permanent +20% dividend-mean change at round11. Same endowments, rules, personas and exogenous dividend path. A raw/B facts/C reflection start from round1; C reflects on its own real fills and outcomes. New common Qwen8192 profile, not pooled with old4096 probes.

This first seed is exploratory, not replicated market evidence. Policies can produce different pre-news prices; the shared event is not an isolated causal headline comparison. B/C initial messages are checked identical: C has no diary until after round5, so earlier divergence cannot be attributed to reflection.

## Longer rule-only background context (600 quiet rounds)

| Seed | Mean benchmark gap | Return ACF1 | Absolute-return ACF1 | Turnover/round | MM volume share |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4103 | 5.84% | 0.220 | 0.015 | 1.41% | 42.3% |
| 5209 | 5.30% | 0.157 | -0.043 | 1.31% | 44.1% |
| 6317 | 6.20% | 0.251 | 0.030 | 1.24% | 47.0% |

Fresh seeds retain return dependence and substantial MM participation. These are descriptive, uncalibrated background results, not validation of financial stylized facts. No baseline was tuned/selected after these outcomes.

## Finalized markets with the same event

| Policy/seed | Financial rounds | Pre-news price | Event price | Post mean gap | Target union trade share | Turnover/round | MM volume share |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rules/4103 | 24/24 (completed) | 95.50 | 94.70 | 15.01% | 22.8% | 1.12% | 56.0% |
| A/4103 | 24/24 (completed) | 104.90 | 104.90 | 5.68% | 6.9% | 1.39% | 36.0% |
| B/4103 | 24/24 (completed) | 105.10 | 105.10 | 5.33% | 13.4% | 1.38% | 41.5% |
| C/4103 | 22/24 (provider_error) | 105.90 | 106.80 | 4.37% | 3.2% | 1.40% | 35.5% |

Target union trade share counts a target-to-target trade once. It is not the share of trader legs. Equal resources do not equalize policy order sizes; these are specified-policy comparisons, not intrinsic LLM superiority.

## Actual orders and fills

| Mode/seed/agent | Period | Requested / accepted / executed shares | Net executed shares |
| --- | --- | ---: | ---: |
| A/4103/Meera | pre | 265 / 265 / 9 | +9 |
| A/4103/Meera | post | 75 / 75 / 20 | -20 |
| A/4103/Arjun | pre | 318 / 299 / 98 | +98 |
| A/4103/Arjun | post | 2 / 2 / 0 | +0 |
| B/4103/Meera | pre | 210 / 210 / 0 | +0 |
| B/4103/Meera | post | 135 / 135 / 38 | -2 |
| B/4103/Arjun | pre | 227 / 212 / 98 | +98 |
| B/4103/Arjun | post | 1 / 1 / 1 | +1 |
| C/4103/Meera | pre | 26 / 26 / 18 | -2 |
| C/4103/Meera | post | 2 / 2 / 2 | -2 |
| C/4103/Arjun | pre | 311 / 298 / 92 | +92 |
| C/4103/Arjun | post | 6 / 6 / 6 | +6 |

Quantities here count target trader legs, not union market trades. A request, acceptance and fill are different. Pre/post headroom, all market diagnostics and failures are retained in report.json.

## Opportunity just before the event

| Mode/seed/agent | Stock weight | Market-buy capacity | Most optimistic band-limit buy capacity | Shares sellable |
| --- | ---: | ---: | ---: | ---: |
| A/4103/llm_012 | 55.67% | 72 | 108 | 109 |
| A/4103/llm_013 | 99.62% | 0 | 0 | 198 |
| B/4103/llm_012 | 51.14% | 79 | 119 | 100 |
| B/4103/llm_013 | 99.43% | 0 | 1 | 198 |
| C/4103/llm_012 | 50.35% | 80 | 120 | 98 |
| C/4103/llm_013 | 96.89% | 5 | 7 | 192 |

Market buys reserve the upper band; the optimistic limit capacity assumes the lowest tick within the band, which need not fill. These are pre-round11 accounts, not unconstrained measures of news attention. Large passive-relative gains can reflect exposure accumulated before the announcement.

## Conditional passive-relative returns

Percentage-point excess over retaining initial shares and receiving the same payments, on this realized price path. Both terminal marks use the same initial wealth denominator. Not a separate no-trading equilibrium, risk-adjusted alpha or liquidation return.

| Mode/seed/agent | Completed rounds | Auction mark | Regime-benchmark mark |
| --- | ---: | ---: | ---: |
| rules/4103/fund_012 | 24/24 | +1.46 | +3.20 |
| rules/4103/mome_013 | 24/24 | -0.57 | -0.66 |
| A/4103/llm_012 | 24/24 | -0.27 | -0.01 |
| A/4103/llm_013 | 24/24 | +11.38 | +9.03 |
| B/4103/llm_012 | 24/24 | +0.25 | +0.32 |
| B/4103/llm_013 | 24/24 | +12.59 | +9.28 |
| C/4103/llm_012 | 22/24 | -0.31 | -0.24 |
| C/4103/llm_013 | 22/24 | +10.35 | +8.64 |

## One qualitative memory caution

All eight C reflection prompts were verified against its own actual last-five outcomes and previous diary. At15 Arjun correctly recalls buying5 at106.8 (round11). At20 it says the earlier5-share recollection was wrong and its only buy was1 at116.1 (round16); both trades actually occurred. The newer verified window covers16-20, while the earlier trade is outside it. This is a post-hoc candidate for conflating a recent window with total history, not an estimated hallucination rate or demonstrated trading harm. Raw diaries, inputs and both actual fills are preserved in report.json and the source run. No prompt change was made during the campaign.

## Before any reflection

| Mode/seed/agent | First requested order |
| --- | --- |
| A/4103/llm_012 | hold 0, limit None |
| A/4103/llm_013 | buy 50, limit 100.2 |
| B/4103/llm_012 | hold 0, limit None |
| B/4103/llm_013 | hold 0, limit None |
| C/4103/llm_012 | hold 0, limit None |
| C/4103/llm_013 | buy 90, limit 110.0 |

B/C first messages are identical for each persona. C first reflects after round5; its diary first enters the decision at6. Differences already present at1 cannot be caused by added reflection. Model generation is unseeded; one trajectory per mode does not separate reflection effects from response variability and their subsequent feedback.

## Generation cost

| Mode/seed | Decision attempts / reported tokens | Reflection attempts / reported tokens | Conservative reservations |
| --- | ---: | ---: | ---: |
| A/4103 | 48 / 136981 | 0 / 0 | 776896 |
| B/4103 | 48 / 146181 | 0 / 0 | 803649 |
| C/4103 | 46 / 149551 | 8 / 23291 | 927229 |

Finalized-arm usage: {"requests_made": 150, "reserved_tokens": 2507774, "provider_reported_tokens": 456004, "unknown_usage_requests": 2, "failed_requests": 2, "blocked_requests": 1}. Full raw requests/reflections/failures and config/source manifests remain in each run. Student declared incremental prices zero; daily remaining quota is unverified.

Fatal provider/output/budget failure stops the block. Existing parse-HOLD/old-diary fallback is operationally flagged, not a model preference. No failed arm is resampled or spliced. Every arm's metrics and wealth marks end at its own listed financial horizon; a partial arm is not a comparable full-horizon result. Report all signs and missing/partial arms; do not infer human realism, headline causality or a uniform reflection upgrade from the first gate.

[Market and portfolio paths](first_gate_paths.pdf) | [Full report](report.json)
