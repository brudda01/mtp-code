# R043: what the quiet A/B/C replication adds

Reviewed on 2026-11-05. All18 markets completed12 sessions, with432 valid
decisions and24 genuine reflections. Three fresh exogenous scenarios, two
unseeded model draws per mode/scenario; not six independent scenario seeds.
No API/output/parse/reflection failures, repairs, retries, unknown usage,
missing slots or cancelled choices. The intended Qwen model/profile was retained.

## A repeatable gap pattern, with important qualifications

These are percentage-point differences in the whole-path mean absolute
price gap from the simulator's private dividend-value benchmark. Each entry
averages the two prespecified model draws within that scenario.

| Scenario | B minus A | C minus B | C minus A |
|---|---:|---:|---:|
| 22853 | -0.5875 | -0.4125 | -1.0000 |
| 23971 | +0.4625 | -1.7500 | -1.2875 |
| 25087 | +7.0125 | -4.2125 | +2.8000 |

C has a smaller average gap than B in all3 scenarios, and in5/6 individual
draw contrasts. The exception is22853/draw2: C-B is+0.1167pp. This is a
bounded repeated policy-level pattern worth reporting. It is not a universal
reflection upgrade, empirical/human-realism validation or an isolated effect of
the reflection text on identical histories. C versus A worsens the average
gap in25087, so the result does not justify choosing the most elaborate mode.
B-A has both signs across draws/scenarios; factual summaries do not consistently
improve this statistic either. No scalar winner or significance test was planned.

## A smaller gap is not the same as higher individual returns

Below are C-B differences in full12-session passive-relative returns, averaged
within scenario. The first value uses the last auction price; the second uses
the private-value mark. Values are percentage points, not percentage changes.

| Scenario | Meera: auction / private | Arjun: auction / private |
|---|---:|---:|
| 22853 | -0.450 / -0.442 | +4.771 / -0.156 |
| 23971 | +0.105 / -0.116 | -2.043 / +0.613 |
| 25087 | -0.341 / -1.304 | +0.128 / +3.056 |

Meera's private-value passive excess is lower with C in all3 scenario averages,
even though the market gap is also smaller. Arjun's direction can depend on
the terminal valuation:22853 looks better at auction prices and slightly worse
at private value;23971 reverses that pattern. Keep both marks and both traders.
These are conditional realized-path accounting comparisons. They are not
risk-adjusted alpha, human realism or aggregate welfare. The report includes
market-maker/other-trader counterpart accounts; closed zero-tax excess sums
cancel under either mark.

## Context has a measurable cost, without a universal cost ratio

Across six equal-length markets per mode, reported totals were A359233,
B394446 and C459390 tokens. C used64944 more than B, or16.4646% in this campaign.
Actual reflections accounted for61342 tokens; the decision-only difference was
3602. All usage was known. One C-B draw cost304 fewer tokens despite reflection;
the other five cost more. These totals concern this exact profile, history
length, population and model. They are not a deployment price or a general
cost multiplier.

## Why this does not isolate a pure reflection effect

B/C first messages matched within each actor/scenario/draw, and no reflection
exists before the end of session5. Nevertheless4/12 first requested order pairs
differed in side/quantity/limit, all for Arjun;8/12 matched. This post-hoc all-case
diagnostic illustrates unseeded model variation before reflection. Later C
diaries then refer to C's own diverged market history. The study compares the
specified policies across matched exogenous scenarios; it does not hold later
states fixed or identify an individual reflection sentence as a causal mechanism.

All456 actual-history requests and24 reflection chains were checked. Independent
cash/wealth reconstruction covered3528 account-rounds, maximum cash error
2.91e-11. These establish accounting/provenance consistency, not behavioural truth.
Short quiet markets do not validate long-run stylized facts, news response or
human biases. Older ambiguous-news/disclosed-horizon cohorts remain separate.

## Completion and preservation

Live generation finished2026-11-05 02:48:37 IST, within648HTTP/9.9M reservation
ceilings:456HTTP,1213069 reported tokens,7266911 conservative reservations.
Both original processes exited. The numerical readout and figures were generated
successfully. Original automatic archiving failed before creating a ZIP because
relative paths were compared with an absolute repository path. A separate
preservation wrapper normalized those paths, leaving the frozen driver,
analysis, original failure and all experiment outputs unchanged. Zero new API,
market or numerical-analysis runs were required. The evidence ZIP and all411
exported hashes/1009 recursive configured-secret checks passed;10 older archives
were unchanged. The failure and repair plan/source are retained in the ZIP.

Read [READOUT.md](READOUT.md) for all12 primary draw contrasts,
[report.json](report.json) for complete paths/holdings/execution/cost/counterparts,
[interpretation_checks.json](interpretation_checks.json) for this summary's
derivations and every first-order pair, and
[component_contrasts.pdf](component_contrasts.pdf) for the inspected exportable
figure. This manual interpretation is a supplemental artifact; the core archive
and its original analysis manifest are unchanged.

No further API stage or default promotion is scheduled. This component result
now sits alongside the execution/news measurement and market-background
trade-off findings; none substitutes for external human/market validation.
