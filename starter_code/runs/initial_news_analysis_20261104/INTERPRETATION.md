# R036: sequential news pilot, interpretation and semantic caution

**Read this alongside the numeric READOUT.md. All ten markets completed, but
the bulletin's time wording has an important interpretation problem.** The
results describe responses to the exact delivered bulletin, not a verified
response to a correctly understood permanent-level forecast. No wording was
changed or path rerun after this discovery.

The strongest additions are concrete measurement examples: a response can
redistribute scarce fills between traders without changing their combined
flow; not buying can matter as much as selling; and a price-only or terminal-only
summary can disagree with the behaviour and path. These extend the existing
execution/opportunity thesis candidate. They do not establish human realism.

## What was completed

Root `../20261104_140638_initial_news_ee0f084f`: fresh seeds13111/14227,
twelve rounds, corrected simple agent A, two LLM traders among fourteen slots.
Each seed has quiet, positive real shift silent/visible, and negative real
shift silent/visible. The shift occurs before round1's decisions; its payout
is paid after that auction. True mean changes once from .02 to .024 or .016,
then remains constant with bounded iid payout noise. Initial accounts, prior
reference, personas and twelve background traders match within seed; visible
first inputs differ from silent ones only by the headline. Later feedback is
part of each path. All ten actual rule companions and their negative controls
passed before live calls. No cash injection, saved-reply reuse or hidden new
mean in the silent initial input.

Finished2026-11-04 15:03:43 IST; PID3416 exited. All240 planned choices returned,
all120 live financial rounds cleared.241 HTTP attempts,606498 provider-reported
tokens,3750938 conservative reservations,one unknown-usage attempt,zero blocked
requests. Arjun11 in seed14227/up_silent had one URLError after21.04s; the
already-authorized identical-message extra attempt recovered. No persistent
API/parse/reflection/output failure, JSON repair, missing choice or reflection.
No failure-policy amendment, quota inference, model switch or extra experiment.

Exact BharatCode `qwen-3.8-27b`,8192 output cap/low reasoning/temp.3/180s,
memory5/reflection0,10RPM/60000 byte-estimate input TPM. Provider randomness is
unseeded; backend fingerprint unavailable. Version
`initial_news_A_v1_explicit_prior_reference`; common hidden recording length,
initial dividend honestly labelled as a supplied prior rather than a paid
observation in this episode. Original production defaults and selectable A/B/C
remain unchanged. There is no controlled before/after benefit estimate for
this clarification. Revision0f80f2cfaa6b1059ecbf5c2ded9ffe91640195a6 plus frozen
uncommitted sim/helper sources/configs/prompts are retained in the protocol,
prepared source ZIP and individual manifests. Do not pool with older prompts.

## Frozen primary: first-three-round signed executed flow

Every entry is **visible minus silent**, under the same true regime and seed.
The three numbers are requested / accepted / actually filled signed shares.
Positive means more buying or less selling; quantities summed over repeated
orders are not necessarily distinct shares.

|Seed|Shift|Meera|Arjun|Combined filled|
|---|---|---|---|---:|
|13111|up|+50 / +50 / +13|+13 / +22 / -13|0|
|13111|down|0 / 0 / 0|+10 / +10 / 0|0|
|14227|up|0 / 0 / 0|+53 / +38 / +22|+22|
|14227|down|-150 / -150 / 0|-465 / -465 / -97|-97|

**Allocation can hide a response.** At13111/up round1, the silent path has
Meera HOLD and Arjun's market BUY accepted at83; he fills35. With the headline,
Meera's market BUY50 fills13 and Arjun's market BUY still accepts83 but fills22.
Both auctions close106.1 with volume35. Extra buy intention changes who gets
the available stock. Across the primary window Meera buys13 versus0, while
Arjun buys64 versus77: combined77 in both. This is neither no behavioural
response nor a sell by Arjun. Background first orders and opening states match;
the first auction's submitted target-order difference is Meera's added BUY.

**The downside cases differ.** At13111 both downside paths give Arjun75
early buys, despite accepted totals120 visible versus110 silent; hence no
early filled contrast. At14227 he buys65 in silent and sells32 in visible,
so -97 consists of32 actual sells plus65 avoided buys. It is not97 shares
sold in the visible path. His repeated accepted SELL100/100/80 offers fill
0/20/12; adding offers cannot be reported as280 distinct sales.

Meera's first-three silent BUY50/50/50 at14227 all miss, whereas visible
produces HOLD/HOLD/HOLD: a -150 accepted contrast with zero filled contrast.
Later her silent bids acquire97 shares; the visible path keeps all100 initial
shares and never trades. At12 she has passive excess -9.145%/-8.369% in silent
versus0%/0% in visible (auction/benchmark marks). Zero excess means matching
the holding portfolio, not avoiding the loss on her original stock. A response
need not appear as selling, and early unfilled intentions are not lifetime
exposure. This is an observed joint-path contrast, not an isolated Meera effect.

## Prices, participation and both wealth marks

All values below are percentages except closing price. Gap is the twelve-round
mean absolute deviation from the **private internal** regime benchmark.
Turnover is traded shares /1450 /round. Each slash pair is LLM-population /
matched F/M-replacement companion, with the same total resources and fourteen
slots. Rule visible/silent financial duplicates are deliberate negative controls.

|Seed|Cell|Close|Gap LLM/rules|Turnover LLM/rules|MM volume share LLM/rules|
|---|---|---:|---|---|---|
|13111|quiet|108.9|8.68 / 2.59|1.48 / 1.10|33.46 / 52.60|
|13111|up silent|126.3|4.52 / 8.65|1.74 / 1.14|39.74 / 60.61|
|13111|up visible|129.3|5.35 / 8.65|1.75 / 1.14|39.47 / 60.61|
|13111|down silent|83.7|17.27 / 16.30|1.71 / 1.01|27.52 / 63.64|
|13111|down visible|91.8|21.04 / 16.30|1.81 / 1.01|31.43 / 63.64|
|14227|quiet|116.8|11.88 / 2.92|1.24 / 1.07|46.30 / 54.55|
|14227|up silent|123.9|6.82 / 7.08|1.51 / 1.11|38.02 / 58.03|
|14227|up visible|125.2|6.86 / 7.08|1.51 / 1.11|41.83 / 58.03|
|14227|down silent|78.4|18.82 / 13.73|1.95 / 1.25|20.06 / 50.92|
|14227|down visible|80.3|8.50 / 13.73|1.60 / 1.25|42.65 / 50.92|

In these ten comparisons, the LLM populations have higher turnover and lower
MM volume share, while gap rankings depend on regime. These are two scenarios,
not ten independent policy-effect replications; silent/visible rule duplicates
give six distinct financial reference paths. Order sizing, execution style and
information processing differ between the specified policies. Lower MM share
is not proof of healthy liquidity, greater realism or intrinsic LLM superiority.

Adding the headline changes mean gap by +.833pp/+3.771pp at13111 up/down and
+.042pp/-10.323pp at14227 up/down. The negative14227 path approaches80 much
earlier with the headline, but the negative13111 path remains farther away.
Thus a single attractive path or terminal value does not summarize the study.
Even the two positive paths overshoot120 by the end. Twelve rounds cannot
establish equilibrium convergence or long-run return statistics.

Keep both lifetime conditional passive marks. For example Arjun13111/up has
visible-minus-silent excess +.555pp at auction prices but -.763pp at the private
benchmark: the financial interpretation changes sign with the terminal mark.
All other signs and all counterpart groups remain in READOUT.md/report.json.
Target gains are offset by MM/other traders' passive-relative losses in this
zero-tax closed market; they are not aggregate welfare gains. Passive accounts
hold initial endowments on each realized price/payout path, not an equilibrium
simulation with trading removed. No risk-adjusted-alpha or liquidation claim.

## Important retrospective discovery: level versus growth wording

The exact positive bulletin is:

> A news report forecasts a sustained 20% rise in KGP's dividend per trading session; actual future payments remain uncertain.

Negative replaces "rise" with "fall". "Per trading session" was intended to
describe the dividend's unit, but it can also modify the percentage change.
Arjun14227/down_visible round1 explicitly says **"Dividends shrinking 20% every
session"**. That is a repeated-growth reading, inconsistent with the one-time
permanent mean-level change actually implemented. Several positive explanations
also describe a per-session ramp; those phrases alone are less conclusive.
The complete eight first-round visible-news messages/replies and actual payout
paths are copied directly from source into semantic_examples.json, with source
hashes; this is not a new model sample or reconstructed prompt.

This qualifies interpretation of the strongest -97 example and any economic
belief/price-discovery story. The intended level-change treatment was not
demonstrated to be understood consistently. The data still establish the
recorded actions, fills, allocation mechanism, accounting and responses to
the delivered sentence. Text is evidence of an expressed interpretation,
not access to latent beliefs or proof that wording caused the later path.
There is no controlled old/new wording comparison or misunderstanding-rate
estimate. Earlier studies that used this exact bulletin need the same caution;
do not assume all earlier replies made the same error or erase their evidence.

Separate qualitative consistency leads: Meera14227/down_silent lowers an
unfilled100.1 bid to100.0 at3 while claiming this will obtain a fill; Arjun's
positive14227 explanations call100.2/100.7 the top of the band although the
disclosed20% band is much wider. These are rationale/rule-description mismatches,
not newly scored numeric-probe failures or proof their feasible orders are invalid.
The earlier successful numeric qualification does not guarantee faithful
economic interpretation in every live decision. Do not tune a persona or
switch models to obtain a preferred action.

**Next correction PROPOSED only:** use a clearly stated one-time change in the
expected dividend **level**, remaining at the new level in later sessions with
uncertain realized payments. Avoid naming the hidden implemented mean as known
fact; preserve the forecast's uncertainty. Verify the reading in a small
predeclared semantic control before further market generation; any subsequent
version must apply common rules/wording across selectable A/B/C. No headline,
sim default or existing prompt was edited here; no extra API run is scheduled.
Do not claim a semantic correction improves behaviour before controlled evidence.

## Audit and thesis placement

All source/config/protocol/output hashes, eight initial pair input checks,
241 actual-history request checks, identical retry messages and ten rule
controls pass. Independent reconstruction from fills/tax/interest/dividends
matches3360 account-round balances across twenty complete rule/live markets;
max cash/auction-wealth error2.91e-11. Total shares1450, nonnegative resources,
MM inventory within0..300 and passive counterpart cancellation pass. Four
offline driver plus three offline readout checks pass; unchanged sim sources
remain protected by the prepared snapshot. These are methods assurance.

Use the allocation/exposure examples in the execution/opportunity results,
with all primary zeros and signs. Use the policy/price table as a bounded
market-context result, alongside existing longer background sensitivities.
Keep A/B/C's earlier mixed effects and costs as the separate third thesis
candidate; this A-only study does not replace or confirm them. Treat semantic
ambiguity as an explicit validity limitation and a justified next correction,
not a fourth validated headline result. No human/trait calibration, universal
news effect, herding, long-run realism or superiority claim follows. The initial
event also lacks established pre-event trend history. Do not assume raw A
forgets news once its structured five-round window expires; reasoning can carry it.
