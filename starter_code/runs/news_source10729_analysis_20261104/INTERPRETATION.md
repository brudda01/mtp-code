# R035: fresh news responses, actual execution, and the limits of the result

**The new phase completed: one fresh source history and all18 planned matched
single-auction trials.**36 fresh joint-trial choices plus12 source choices used
Qwen; no delivery/parse/output failure. The earlier failed source9623 remains
missing, so the original two-history study is still only half covered.

The main useful result is a clearer chain from information to intended orders,
fills and prices. These stages can tell different stories even in fresh data.

## What changed under the headlines?

Both agents receive the same headline condition in each trial. Within a frame,
opening portfolios, actual history,12 other traders' orders and allocation RNG
are identical. Three fresh reply pairs per condition, no selected resampling.

Meera holds in ALL18 query replies(6 silent/6 positive/6 negative). Arjun's
headline-minus-silent contrasts are:

|Snapshot|Headline|Accepted signed contrasts(3 draws)|Executed signed contrasts|Price contrasts|
|---|---|---|---|---|
|Round2|Positive|+50,0,+50|+20,0,+20|+1.0,0,+1.0|
|Round2|Negative|0,-100,0|0,-10,0|0,0,0|
|Round6|Positive|+155,0,+105|+69,0,+32|+7.6,0,+1.4|
|Round6|Negative|0,0,0|0,0,0|0,0,0|

Shares are buy positive/sell negative; prices in currency units. The two
snapshots come from ONE history, not two independent market replications.
Contexts change in prices, holdings and own past reasoning together; the table
does not isolate a trend, risk or personality interaction.

## Three examples worth explaining in the thesis

**A price null can hide real trading.** Round2, draw2: no headline produces
HOLD and the MM buys10 from four other sellers at99.5. The negative headline
produces Arjun market SELL100, of which10 fill to the same MM at99.5. Total
volume stays10 and price stays99.5, but the seller changes to Arjun. Neither
price change nor aggregate volume alone captures his response. The accepted
100-share sale also greatly exceeds its10-share execution.

**A signed positive response mixes buying and reduced selling.** At round6,
Arjun owns5 shares and has18655.54 cash. All silent and negative replies sell
those5 at market and all5 fill. Positive draw1 instead buys150 at market,
fills64, and avoids that5-share sale: the contrast is+69, not69 buys. Positive
draw3 buys100 with limit89.0, fills27, and avoids5 sold: contrast+32. Positive
draw2 STILL sells5, giving zero contrast. The same positive input thus produces
a large market buy, a full exit, or a limit buy in three fresh requests. This
observed variability is why one selected reply is not reliable evidence of a
stable policy; backend sampling/identity are not fully controlled.

**A zero incremental negative response can be a position boundary.** The
round6 silent policy already sells every remaining share at market. With no
shorting, it cannot reduce stock exposure further. Negative-minus-silent zero
does not distinguish no attention from an already saturated exit policy. This
does not prove the agent would short if allowed; no such experiment was run.

## Opportunity, reasoning and cautious interpretation

At round2 BOTH agents have100 shares,10003.87 cash, and market-buy capacity83.
At round6 Meera still has100 shares,10019.83 cash and capacity93; Arjun has5
shares,18655.54 cash and capacity174. Natural source decisions generated these
states; no cash buffer or position cap was imposed to force responses.

Meera's HOLDs cannot all be blamed on a lack of buying/selling opportunity.
Her recorded explanations explicitly acknowledge forecasts and their uncertain
payments, often choosing to wait for confirmation or avoid realizing a loss.
These are model self-reports, not proof of internal attention, causal loss
aversion or calibrated human realism. The one-auction design cannot test her
stated plan to react after a dividend actually changes. Likewise, differences
from Arjun bundle persona traits and own histories; they are not an isolated
risk/trait experiment. Round2 financial states match, but their prior reasoning
and full profiles still differ.

## What the economic and rule controls establish

Current economic factors1/.8/1.2 reuse the SAME accepted orders and allocation
state, yielding identical auctions but different paid dividends/private wealth
marks. They are54 accounting variants of18 trials, not54 independent responses.
The hidden current payout has not been observed at the order cutoff; a later
economic-learning or persistent-price effect requires sequential data.

F/M target-policy substitutions use the same opening resources and public
observations; their headlines do not change orders/fills. This is a software/
policy negative control because those specified rules ignore text, not evidence
of intrinsic LLM superiority. Both one-auction stay-put marks and every
counterparty outcome are retained. Uniform-auction-mark excess is cashflow/
exposure accounting, not immediate trading skill or liquidation profit.

## Coverage and next decision

48 successful HTTP calls,124808 provider-reported tokens,702164 conservative
reservations; zero new errors/unknown usages/blocked/JSON repairs/reflections.
Including the original R033 failures:50 HTTP,724448 reservations,2 old unknown
usages and1 old blocked request. Source6/6 and phase18/18 complete, original
planned study1/2 histories and18/36 trials. Failed9623 is not retried/replaced.
Its missing cells remain explicit. PID12220 exited; no API job remains.

All36 exact trial messages, source histories/original auctions, rule controls,
54 settlement variants, model/settings/source/output hashes and accounts pass
audit. Original production defaults and selectable A/B/C remain unchanged.
This8192/common-hidden fresh pilot is separate from R034's4096/shown-length
retrospective sample; it adds examples of the mechanism, not numeric replication
of the old effects. No new liquidity grid, provider switch or reflection default.

Keep execution/opportunity as a thesis candidate, with fresh price-versus-fill
and position-boundary examples alongside R034's disclosed robustness check.
Further general claims require prospectively chosen independent histories and
joint sequential feedback; neither a universal headline sign nor human realism
has been validated here. Do not extend generation until a preferred sign appears.
