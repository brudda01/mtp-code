# Human-design reference: follow-up access (R032, 2026-11-04)

After the original readout, the authors' **7 July 2021 workshop slides** became
accessible in a university-hosted primary PDF:
[Kopanyi-Peuker, joint work with Weber, Bamberg workshop](https://www.uni-bamberg.de/fileadmin/vwl-macrofinance/Promotionskolleg_Makrooekonomik/Behavioral_Macro_Workshop/Workshop2021/BehMacro_Kopanyi-Peuker.pdf).
Read the extracted 23-page text, especially slides7-9. PDF screenshot retrieval
failed (cache miss); no visual/table interpretation is claimed. These are an
earlier presentation, **not the full methods of the 2024 published version**.
This supplements rather than rewrites the earlier access limitation.

|Design aspect|Author presentation (2021)|This simulator/pilot|
|---|---|---|
|Institution|Six human traders in a call market|Fourteen traders, including finite market maker and two target LLM slots|
|Trading constraints|No short selling or borrowing|Same broad restrictions, plus explicit band/tick/reservation rules|
|Terminal valuation|Known asset buyout at125 points|Continuing shares valued at last auction price; analyst also reports regime benchmark|
|End-time treatment|Short/long and definite/indefinite duration|Same24 recorded rounds; only total count disclosure changes from round1|
|Repetition|Three market rounds per group|One model realization/condition in each of two exogenous scenarios|

This is a useful institutional comparison: a call auction and feasible holdings
are shared, but termination/payoff design and population differ substantially.
It cannot calibrate our numerical price gaps, explain our individual agents'
motives, or establish equivalent human responses. In particular, removing /24
does not implement the authors' stochastic ending treatment. Their reported
similar price dynamics are a reason to keep a null result plausible, not a
target that our pilot must match.

Do not import a fixed buyout or cash-management rule just to imitate a paper:
those would change the economic question and require their own controlled
design. The current task keeps the continuing-stock economy and tests one
information-design detail. External human/market validation remains open.
