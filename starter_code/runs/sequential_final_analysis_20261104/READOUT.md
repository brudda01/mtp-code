# Sequential A/B/C market campaign: linked final analysis

Completed clean live arms: 7/9; finalized attempted arms: 9/9. Original C4103/5209 remain partial22/19, never resampled. R030 targets only untouched A5209,C/A/B6317.

R030 changes only stopping BETWEEN independent markets: a terminal double503 retains a partial/missing path, then a60-second cooldown precedes the next untouched market. Other fatal failures stop the batch. No simulator/config/prompt/economic/cap change or within-market stop amendment. R030 status: completed.

Earlier stops remain visible: C4103 has22 rounds/8 reflections; C5209 has19/6. Meera5209's round20 HOLD was delivered but never cleared; no order/trade/payout/outcome from that round enters financial metrics. The separate R030 A5209 attempt starts at round1 as originally planned. Complete ABC scenarios: [6317].

Coverage: 419 valid delivered decisions across linked blocks, of which 418 belong to completed financial rounds. Other delivered choices(1) are retained as cancelled, not executed feedback. Reflection verification covers 22 completed cycles and 23 HTTP-attempt prompts, so a retry is not counted as another reflection.

First block STOPPED on Meera/C round23 HTTP503 and its one identical-payload retry (also503). A/B are complete24; C ends22 with all eight reflections. Round23 never cleared; Arjun's request was blocked after the provider stop, and round24 was unattempted. These missing outcomes are not HOLD preferences. No rerun, continuation or full-horizon C result.

24 rounds; public forecast plus actual permanent +20% dividend-mean change at round11. Same endowments, rules, personas and exogenous dividend path. A raw/B facts/C reflection start from round1; C reflects on its own real fills and outcomes. New common Qwen8192 profile, not pooled with old4096 probes.

Three preselected exogenous scenarios, one trajectory per mode; at most ONE complete A/B/C scenario because two C arms are partial. This is small exploratory evidence, not replicated C efficacy or human realism. Policies can produce different pre-news prices; the shared event is not an isolated causal headline comparison. B/C first messages match; early divergence before the first diary at6 cannot be attributed to reflection. Execution dates/provider draws differ across phases.

## Main findings to carry forward

Factual summaries have mixed effects across seeds; reflection does not give a uniform improvement in the one complete scenario. More accepted buying need not produce more executed buying. Pre-news stock exposure limits interpretations of later gains. The large late A6317 fall also carries explicit end-of-episode language, warranting a horizon-disclosure control before treating that path difference as a memory benefit. Longer rule-only persistence/MM concerns remain unresolved.

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
| rules/5209 | 24/24 (completed) | 102.80 | 102.50 | 9.86% | 24.4% | 1.31% | 46.7% |
| rules/6317 | 24/24 (completed) | 97.80 | 97.10 | 13.68% | 21.2% | 1.07% | 57.9% |
| A/4103 | 24/24 (completed) | 104.90 | 104.90 | 5.68% | 6.9% | 1.39% | 36.0% |
| B/4103 | 24/24 (completed) | 105.10 | 105.10 | 5.33% | 13.4% | 1.38% | 41.5% |
| C/4103 | 22/24 (provider_error) | 105.90 | 106.80 | 4.37% | 3.2% | 1.40% | 35.5% |
| B/5209 | 24/24 (completed) | 110.50 | 110.50 | 4.12% | 31.4% | 1.50% | 35.2% |
| C/5209 | 19/24 (provider_error) | 114.50 | 115.10 | 1.87% | 6.2% | 1.70% | 31.2% |
| A/5209 | 24/24 (completed) | 112.20 | 111.00 | 3.97% | 5.9% | 1.46% | 40.4% |
| C/6317 | 24/24 (completed) | 104.40 | 104.10 | 6.15% | 2.2% | 1.39% | 40.9% |
| A/6317 | 24/24 (completed) | 104.90 | 104.90 | 7.18% | 38.8% | 1.63% | 34.9% |
| B/6317 | 24/24 (completed) | 104.40 | 104.40 | 5.68% | 3.9% | 1.42% | 39.4% |

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
| B/5209/Meera | pre | 0 / 0 / 0 | +0 |
| B/5209/Meera | post | 120 / 120 / 91 | -21 |
| B/5209/Arjun | pre | 154 / 153 / 93 | +93 |
| B/5209/Arjun | post | 7 / 6 / 1 | +1 |
| C/5209/Meera | pre | 30 / 30 / 30 | -30 |
| C/5209/Meera | post | 100 / 100 / 13 | +13 |
| C/5209/Arjun | pre | 397 / 385 / 94 | +94 |
| C/5209/Arjun | post | 0 / 0 / 0 | +0 |
| A/5209/Meera | pre | 60 / 60 / 3 | +3 |
| A/5209/Meera | post | 20 / 20 / 15 | +15 |
| A/5209/Arjun | pre | 221 / 186 / 93 | +93 |
| A/5209/Arjun | post | 1 / 1 / 1 | +1 |
| C/6317/Meera | pre | 30 / 30 / 16 | -16 |
| C/6317/Meera | post | 5 / 5 / 5 | -5 |
| C/6317/Arjun | pre | 237 / 221 / 98 | +98 |
| C/6317/Arjun | post | 1 / 1 / 1 | +1 |
| A/6317/Meera | pre | 0 / 0 / 0 | +0 |
| A/6317/Meera | post | 80 / 80 / 50 | -30 |
| A/6317/Arjun | pre | 338 / 338 / 97 | +97 |
| A/6317/Arjun | post | 361 / 361 / 88 | -86 |
| B/6317/Meera | pre | 135 / 135 / 15 | +15 |
| B/6317/Meera | post | 10 / 10 / 10 | +10 |
| B/6317/Arjun | pre | 185 / 178 / 98 | +98 |
| B/6317/Arjun | post | 2 / 1 / 1 | +1 |

Quantities here count target trader legs, not union market trades. A request, acceptance and fill are different. Pre/post headroom, all market diagnostics and failures are retained in report.json.

### Concrete execution example: Meera5209, rounds11-15

| Mode / round | Accepted order | Limit | Actual auction price | Shares filled |
| --- | --- | ---: | ---: | ---: |
| B / 11 | buy 40 | 111.0 | 110.5 | 35 |
| B / 12 | hold 0 | None | 111.5 | 0 |
| B / 13 | hold 0 | None | 112.6 | 0 |
| B / 14 | sell 10 | 112.6 | 112.6 | 1 |
| B / 15 | sell 15 | 112.0 | 112.5 | 0 |
| C / 11 | buy 20 | 114.0 | 115.1 | 0 |
| C / 12 | buy 20 | 116.0 | 116.2 | 0 |
| C / 13 | buy 20 | 116.4 | 117.4 | 0 |
| C / 14 | buy 20 | 118.5 | 118.7 | 0 |
| C / 15 | buy 20 | 118.9 | 118.7 | 13 |
| A / 11 | buy 20 | 111.0 | 111.0 | 15 |
| A / 12 | hold 0 | None | 112.0 | 0 |
| A / 13 | hold 0 | None | 113.1 | 0 |
| A / 14 | hold 0 | None | 113.0 | 0 |
| A / 15 | hold 0 | None | 112.9 | 0 |

C requested five20-share buys, but its first four limits were below the realized auction price; only13 shares filled on its fifth bid. Zero fills therefore do not imply zero buying intent or ignored news. B/C market states and quote sizes differ, so this is an execution-mechanism illustration, not an isolated reflection effect.

## Opportunity just before the event

| Mode/seed/agent | Stock weight | Market-buy capacity | Most optimistic band-limit buy capacity | Shares sellable |
| --- | ---: | ---: | ---: | ---: |
| A/4103/llm_012 | 55.67% | 72 | 108 | 109 |
| A/4103/llm_013 | 99.62% | 0 | 0 | 198 |
| B/4103/llm_012 | 51.14% | 79 | 119 | 100 |
| B/4103/llm_013 | 99.43% | 0 | 1 | 198 |
| C/4103/llm_012 | 50.35% | 80 | 120 | 98 |
| C/4103/llm_013 | 96.89% | 5 | 7 | 192 |
| B/5209/llm_012 | 52.39% | 75 | 113 | 100 |
| B/5209/llm_013 | 99.59% | 0 | 0 | 193 |
| C/5209/llm_012 | 37.39% | 97 | 146 | 70 |
| C/5209/llm_013 | 98.66% | 2 | 3 | 194 |
| A/5209/llm_012 | 54.33% | 72 | 108 | 103 |
| A/5209/llm_013 | 99.60% | 0 | 0 | 193 |
| C/6317/llm_012 | 42.85% | 93 | 139 | 84 |
| C/6317/llm_013 | 99.41% | 0 | 1 | 198 |
| A/6317/llm_012 | 51.10% | 79 | 119 | 100 |
| A/6317/llm_013 | 99.30% | 1 | 1 | 197 |
| B/6317/llm_012 | 58.53% | 67 | 101 | 115 |
| B/6317/llm_013 | 99.39% | 1 | 1 | 198 |

Market buys reserve the upper band; the optimistic limit capacity assumes the lowest tick within the band, which need not fill. These are pre-round11 accounts, not unconstrained measures of news attention. Large passive-relative gains can reflect exposure accumulated before the announcement.

## Conditional passive-relative returns

Percentage-point excess over retaining initial shares and receiving the same payments, on this realized price path. Both terminal marks use the same initial wealth denominator. Not a separate no-trading equilibrium, risk-adjusted alpha or liquidation return.

| Mode/seed/agent | Completed rounds | Auction mark | Regime-benchmark mark |
| --- | ---: | ---: | ---: |
| rules/4103/fund_012 | 24/24 | +1.46 | +3.20 |
| rules/4103/mome_013 | 24/24 | -0.57 | -0.66 |
| rules/5209/fund_012 | 24/24 | +2.19 | +3.07 |
| rules/5209/mome_013 | 24/24 | +0.77 | +1.13 |
| rules/6317/fund_012 | 24/24 | +0.83 | +1.74 |
| rules/6317/mome_013 | 24/24 | +0.13 | +0.57 |
| A/4103/llm_012 | 24/24 | -0.27 | -0.01 |
| A/4103/llm_013 | 24/24 | +11.38 | +9.03 |
| B/4103/llm_012 | 24/24 | +0.25 | +0.32 |
| B/4103/llm_013 | 24/24 | +12.59 | +9.28 |
| C/4103/llm_012 | 22/24 | -0.31 | -0.24 |
| C/4103/llm_013 | 22/24 | +10.35 | +8.64 |
| B/5209/llm_012 | 24/24 | +0.55 | +0.75 |
| B/5209/llm_013 | 24/24 | +6.94 | +6.05 |
| C/5209/llm_012 | 19/24 | -1.32 | -1.03 |
| C/5209/llm_013 | 19/24 | +9.36 | +7.71 |
| A/5209/llm_012 | 24/24 | +1.21 | +0.85 |
| A/5209/llm_013 | 24/24 | +7.91 | +6.03 |
| C/6317/llm_012 | 24/24 | -1.48 | -1.42 |
| C/6317/llm_013 | 24/24 | +9.60 | +9.31 |
| A/6317/llm_012 | 24/24 | +1.77 | -0.93 |
| A/6317/llm_013 | 24/24 | +1.73 | +2.72 |
| B/6317/llm_012 | 24/24 | +2.39 | +2.11 |
| B/6317/llm_013 | 24/24 | +10.42 | +9.33 |

## Distribution of passive-relative wealth

Wealth units, auction / regime-benchmark mark. Each row uses its own recorded horizon. In this closed, zero-tax setup, aggregate active-minus-passive wealth sums to zero on each realized path: target gains have offsetting losses elsewhere. These are conditional accounting differences, not welfare, risk-adjusted skill, direct subsidy or an equilibrium no-trading comparison. Target slots are the two replaced F/M agents in rules or the two LLMs in live modes.

| Policy/seed/horizon | Target slots | Market maker | Other traders |
| --- | ---: | ---: | ---: |
| rules/4103/24 | +179.8 / +506.5 | -303.4 / -1065.7 | +123.6 / +559.2 |
| rules/5209/24 | +592.7 / +840.7 | -1188.0 / -1720.0 | +595.4 / +879.4 |
| rules/6317/24 | +192.5 / +462.2 | -549.3 / -1419.3 | +356.8 / +957.1 |
| A/4103/24 | +2220.8 / +1803.2 | -1974.1 / -1311.7 | -246.7 / -491.5 |
| B/4103/24 | +2569.0 / +1919.1 | -2165.2 / -1220.5 | -403.7 / -698.5 |
| C/4103/22 | +2008.8 / +1679.8 | -1613.2 / -1182.7 | -395.6 / -497.1 |
| B/5209/24 | +1497.5 / +1358.8 | -975.8 / -782.0 | -521.8 / -576.9 |
| C/5209/19 | +1606.6 / +1337.1 | -1191.4 / -820.4 | -415.2 / -516.7 |
| A/5209/24 | +1824.3 / +1376.3 | -1202.6 / -726.6 | -621.6 / -649.6 |
| C/6317/24 | +1624.0 / +1577.2 | -1404.7 / -1324.9 | -219.2 / -252.2 |
| A/6317/24 | +701.7 / +359.7 | +717.8 / -1046.2 | -1419.5 / +686.5 |
| B/6317/24 | +2562.1 / +2289.3 | -1782.8 / -1452.8 | -779.4 / -836.6 |

## Full-horizon component contrasts

Each entry uses two clean24-round arms from the same seed; missing/partial pairs stay missing. These are descriptive differences with one unseeded trajectory per policy, not causal efficacy estimates. Negative gap differences mean closer average post-event prices; positive wealth differences mean higher conditional passive excess. Reported-token totals exclude unknown failed-request usage, so token differences are not complete billed-cost differences.

| Seed / contrast | Gap difference (pp) | Meera auction / benchmark excess difference (pp) | Arjun auction / benchmark excess difference (pp) | Reported token difference |
| --- | ---: | ---: | ---: | ---: |
| 4103 / B-A | -0.35 | +0.53 / +0.33 | +1.22 / +0.25 | +9200 |
| 4103 / C-B | missing | missing | missing | missing |
| 5209 / B-A | +0.15 | -0.67 / -0.11 | -0.97 / +0.02 | +20912 |
| 5209 / C-B | missing | missing | missing | missing |
| 6317 / B-A | -1.51 | +0.61 / +3.04 | +8.69 / +6.61 | +6442 |
| 6317 / C-B | +0.48 | -3.87 / -3.53 | -0.82 / -0.03 | +29842 |

## Secondary comparisons over observed rounds

Post-hoc: compare B/C only through the last round completed in BOTH. These service-dependent cutoffs were not the planned24-round horizon; no assumption that missingness is harmless, no replacement terminal result, no pooling of different horizons or causal inference. Raw runs are unchanged; only recorded prices/fills/accounts are evaluated.

| Seed / observed rounds | C-B post gap (pp) | Meera C-B auction / benchmark excess (pp) | Arjun C-B auction / benchmark excess (pp) | Meera B / C post gross fills |
| --- | ---: | ---: | ---: | ---: |
| 4103 / 22 | -1.04 | -0.62 / -0.56 | +0.44 / -0.64 | 38 / 2 |
| 5209 / 19 | -3.74 | -2.14 / -2.07 | +4.85 / +1.67 | 56 / 13 |

## Possible end-of-episode cue: A6317

The actual system prompt says the stock continues and shares do not expire; the user prompt still discloses Round22/24. Meera then sells40 at22 while citing so few rounds left. All40 traded shares at22 have her as seller. Price falls119.2 to111.6. Arjun next requests SELL198 then SELL162 at23/24, citing the momentum break and final round; fills36 then51, with final price102.0. This is a descriptive sequence, not proof that the horizon caused the price fall or that reflection prevented it.

Post-hoc sensitivity ONLY: evaluate all three observed paths at21, before the identified sale. The cutoff was selected after inspecting the tail; it cannot replace the primary24-round endpoint or establish causal component efficacy.

| Mode at21 | Post-event mean gap | Meera auction / benchmark passive excess (pp) | Arjun auction / benchmark passive excess (pp) |
| --- | ---: | ---: | ---: |
| A | 6.51% | +0.72 / +0.76 | +8.43 / +8.82 |
| B | 6.93% | +1.95 / +2.11 | +8.68 / +9.32 |
| C | 7.52% | -1.16 / -1.42 | +8.06 / +9.30 |

Next proposed control: hold the recorded state/persona/rules fixed and vary only episode-end disclosure; retain the existing continuation rule. No prompt change or new API study was made here. Do not generalize one terminal-cued path into a universal A failure or B/C upgrade.


## One qualitative memory caution

The original seed4103's eight C reflection prompts were verified against its own actual last-five outcomes and previous diary. At15 Arjun correctly recalls buying5 at106.8 (round11). At20 it says the earlier5-share recollection was wrong and its only buy was1 at116.1 (round16); both trades actually occurred. The newer verified window covers16-20, while the earlier trade is outside it. This is a post-hoc candidate for conflating a recent window with total history, not an estimated hallucination rate or demonstrated trading harm. Raw diaries, inputs and both actual fills are preserved in report.json and the source run. No prompt change was made during the campaign.

## Before any reflection

| Mode/seed/agent | First requested order |
| --- | --- |
| A/4103/llm_012 | hold 0, limit None |
| A/4103/llm_013 | buy 50, limit 100.2 |
| B/4103/llm_012 | hold 0, limit None |
| B/4103/llm_013 | hold 0, limit None |
| C/4103/llm_012 | hold 0, limit None |
| C/4103/llm_013 | buy 90, limit 110.0 |
| B/5209/llm_012 | hold 0, limit None |
| B/5209/llm_013 | buy 50, limit None |
| C/5209/llm_012 | hold 0, limit None |
| C/5209/llm_013 | hold 0, limit None |
| A/5209/llm_012 | buy 20, limit 100.0 |
| A/5209/llm_013 | buy 98, limit None |
| C/6317/llm_012 | hold 0, limit None |
| C/6317/llm_013 | hold 0, limit None |
| A/6317/llm_012 | hold 0, limit None |
| A/6317/llm_013 | buy 90, limit 100.2 |
| B/6317/llm_012 | hold 0, limit None |
| B/6317/llm_013 | hold 0, limit None |

B/C first messages are identical for each persona. C first reflects after round5; its diary first enters the decision at6. Differences already present at1 cannot be caused by added reflection. Model generation is unseeded; one trajectory per mode does not separate reflection effects from response variability and their subsequent feedback.

## Generation cost

| Mode/seed | Decision attempts / reported tokens | Reflection attempts / reported tokens | Conservative reservations |
| --- | ---: | ---: | ---: |
| A/4103 | 48 / 136981 | 0 / 0 | 776896 |
| B/4103 | 48 / 146181 | 0 / 0 | 803649 |
| C/4103 | 46 / 149551 | 8 / 23291 | 927229 |
| B/5209 | 49 / 152561 | 0 / 0 | 827936 |
| C/5209 | 41 / 127508 | 7 / 16987 | 814630 |
| A/5209 | 48 / 131649 | 0 / 0 | 767883 |
| C/6317 | 48 / 150320 | 8 / 20754 | 950081 |
| A/6317 | 48 / 134790 | 0 / 0 | 785231 |
| B/6317 | 48 / 141232 | 0 / 0 | 797622 |

Finalized-arm usage: {"requests_made": 447, "reserved_tokens": 7451157, "provider_reported_tokens": 1331805, "unknown_usage_requests": 6, "failed_requests": 6, "blocked_requests": 1}. Full raw requests/reflections/failures and config/source manifests remain in each run. Student declared incremental prices zero; daily remaining quota is unverified.

Fatal provider/output/budget failure stops the endogenous path. R030 alone permits a later independent market after a recorded terminal double503 and60s cooldown; other fatal/fallback failures stop that batch. Existing parse-HOLD/old-diary fallback is flagged operationally, not a preference. No failed arm is resampled/spliced. Each metric/wealth mark ends at the listed horizon; partials are not full-horizon results. Preserve all signs/missing arms; no human realism, headline causality or uniform component upgrade is established.

[Seed6317 paths](seed_6317_paths.pdf) | [Full campaign report](report.json) | [Preserved R029 readout](../sequential_next_analysis_20261103/READOUT.md)
