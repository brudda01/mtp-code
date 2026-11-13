# Exploratory news pilot

Status: **completed_query_first_delivery**. 8/8 live markets complete.

Qwen `qwen-3.8-27b` at BharatCode; prompt suite `comparable_agents_v2_disclosed_rules`, condition A, memory 5, temperature 0.3, low reasoning effort, output cap 4096. Fourteen equal-resource slots; two specified rule slots replaced by two bundled LLM personas. Twenty rounds, event at 11; two exogenous seeds. Model draws are unseeded. Linked delivery phases are preserved separately.

The completed pilot shows context-dependent order responses: Meera's first-seed positive contrast is mixed in the second seed; Arjun's two HOLD-only frames cannot fund a buy. Combined real-change/news markets have smaller average benchmark gaps in both seeds, but differing pre-event states prevent a clean causal price claim. One combined arm also has 90 accepted Meera buy shares and no fills. These distinctions motivate confirmation rather than a provider switch.

## Same stored state: headline versus silence

Three fresh replies per condition in each actual control-market event frame. Only the uncertain positive dividend forecast changes. These orders never execute. Buy capacity below uses the common conservative market-order reservation, not a guaranteed fill.

| Seed / frame | Stock weight | Market buy cap | Silent signed orders | Announced signed orders | Paired differences |
| --- | ---: | ---: | --- | --- | --- |
| 1441 / Meera | 36.51% | 101 | -10, -10, -10 | +40, +0, +25 | +50, +10, +35 |
| 1441 / Arjun | 99.68% | 0 | +0, +0, +0 | +0, +0, +0 | +0, +0, +0 |
| 2882 / Meera | 49.42% | 85 | +50, +50, +0 | +0, +30, +40 | -50, -20, +40 |
| 2882 / Arjun | 99.92% | 0 | +0, +0, +0 | +0, +0, +0 | +0, +0, +0 |

Constraint context matters: a nearly fully invested account with no buying headroom cannot express a positive-news response by buying. A HOLD does not by itself reveal an unchanged belief. Personas differ on several traits and arrive at different states; cross-frame differences do not isolate personality.

## Market outcomes

Post-event gaps are mean absolute price deviations from the configured stationary-regime benchmark (mean dividend / cash rate), not an externally calibrated true price. The assigned regime is hidden; an uncertain forecast does not give traders an immediately known correct price. Full markets match exogenous innovations and initial resources, but live states already differ before news. Paired price differences therefore do not identify a clean causal headline effect.

| Seed / cell | Live pre-event close | Live post mean | Live post gap | Rule post gap | Live target involvement | Live target submitted / accepted / filled shares after news |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1441 / control | 109.30 | 102.29 | 4.81% | 1.00% | 76.2% | 649 / 649 / 192 |
| 1441 / headline_only | 113.90 | 103.87 | 5.09% | 1.00% | 63.5% | 643 / 643 / 248 |
| 1441 / fundamentals_only | 104.40 | 105.16 | 12.37% | 12.27% | 68.1% | 957 / 937 / 264 |
| 1441 / combined | 102.60 | 108.23 | 9.81% | 12.27% | 26.4% | 224 / 221 / 43 |
| 2882 / control | 98.10 | 90.47 | 9.53% | 6.72% | 73.0% | 714 / 714 / 200 |
| 2882 / headline_only | 100.00 | 100.19 | 0.19% | 6.72% | 46.5% | 382 / 382 / 73 |
| 2882 / fundamentals_only | 101.00 | 101.86 | 15.12% | 17.43% | 78.4% | 672 / 644 / 343 |
| 2882 / combined | 101.80 | 107.72 | 10.23% | 17.43% | 22.6% | 49 / 47 / 47 |

Target involvement counts each market trade once even if both target agents trade with each other. Submitted/accepted/filled quantities instead count target trader legs; they are not the same denominator. Larger order sizes can increase a policy's market influence, so these are comparisons of specified policies rather than intrinsic LLM superiority.

## Conditional passive comparison

Every target account is retained. Values are active-minus-passive returns in percentage points using the same initial wealth denominator. The passive account keeps its initial shares and earns the realized dividends and cash interest on this market's price path. This is not a separate no-trading equilibrium or risk-adjusted alpha. Auction and regime-benchmark terminal marks are both shown.

| Seed / cell | Meera: auction / benchmark | Arjun: auction / benchmark |
| --- | ---: | ---: |
| 1441 / control | +3.03 / +1.82 | -3.69 / -3.56 |
| 1441 / headline_only | +1.15 / +1.40 | -6.52 / -5.65 |
| 1441 / fundamentals_only | -4.24 / -5.04 | -1.80 / -1.52 |
| 1441 / combined | +0.00 / +0.00 | +6.57 / +8.12 |
| 2882 / control | +0.00 / +0.00 | -0.97 / -8.57 |
| 2882 / headline_only | +0.84 / +0.84 | -1.80 / -1.80 |
| 2882 / fundamentals_only | +1.96 / +1.96 | -7.53 / -4.64 |
| 2882 / combined | -1.37 / -3.61 | +2.91 / +7.00 |

## Interpretation boundary

Two short exogenous scenarios and three replies per fixed frame are exploratory evidence. They do not establish stable market dynamics, human realism, herding, generalized profitability, or A/B/C benefits. Earlier incomplete attempts remain in report.json and the raw study tree; they are not spliced into full runs or pooled as additional independent markets. Negative, constrained and unfilled cases are retained.

The A simple / B factual summaries / C reflection comparison remains available and has not been replaced by this A-only pilot. Further confirmation should distinguish news meaning, portfolio headroom, limit execution and policy sizing before expanding model/provider comparisons.

Artifacts: [market paths](market_paths.pdf), [same-state orders and headroom](same_state_news.pdf), [full report](report.json), and [delivery/provenance audit](delivery_audit.json).
