# One post-hoc liquidity-depth check

Only the market maker's CURRENT quote_size changes10->20; cash/inventory/spread/skew/cap, other traders' original orders and all old focal replies/history/RNG remain. Both original size10 books reproduce first. Both states accept20-share bids/asks under their actual resources. This is not a regenerated market history, empirical calibration, extra reply sample or selected better default. Chosen after base results; all36 cases included.

|Frame|News|Mean accepted|Filled contrasts: original / deeper|Mean filled: original / deeper|
|---|---|---:|---|---|
|s1441_llm_012|positive|10.00|[0, 0, 10] / [0, 0, 10]|3.33 / 3.33|
|s1441_llm_012|negative|-6.67|[0, 0, 0] / [0, 0, -10]|0.00 / -3.33|
|s1441_llm_013|positive|0.00|[0, 0, 0] / [0, 0, 0]|0.00 / 0.00|
|s1441_llm_013|negative|0.00|[0, 0, 0] / [0, 0, 0]|0.00 / 0.00|
|s2882_llm_012|positive|-13.33|[-2, -10, 12] / [-2, -20, 22]|0.00 / 0.00|
|s2882_llm_012|negative|-33.33|[-2, -12, 0] / [-2, -22, 0]|-4.67 / -8.00|
|s2882_llm_013|positive|60.00|[21, 21, 0] / [31, 31, 0]|14.00 / 20.67|
|s2882_llm_013|negative|-6.67|[21, 0, 0] / [31, 0, 0]|7.00 / 10.33|

All72 base/variant conditional auctions use canonical validation/settlement and finite-MM accounting. Same-order payout/benchmark variants are not extra auctions/replies. Keep accepted-versus-filled and state-specific results; this check cannot establish real-world liquidity or long-run robustness.
