# R051 scientific review (2026-11-07)

All 16 paths were inspected. Removing the inventory skew lowers return ACF1
and increases market-maker boundary time in each of the four fresh seeds,
under both homogeneous and heterogeneous backgrounds. The larger ACF1 decline
under heterogeneity occurs in all four scenarios. These are four paired
scenarios, not eight or sixteen independent replications.

Heterogeneity is not a universal improvement: it increases the whole-path
valuation gap at the original skew in all four seeds; results without skew
split two improved and two worsened. The adverse seed 29671 heterogeneous path
ends at 217.5 against the private 100 benchmark. Its final 200 sessions have
54.866% mean gap despite return ACF1 of 0.0022. Near-zero return dependence alone
therefore does not establish realistic price formation. All four fundamentalist
accounts hold zero shares from session 450 onward. This is consistent with
constrained corrective selling, but the cause is not isolated experimentally.
The post-hoc trace is preserved in adverse_case.json; all other paths and signs
remain in report.json and all_paths.png/pdf.

The intervention jointly varies three fundamentalist thresholds and four
momentum windows. Mean parameter values are preserved, but realized trading
intensity is not held fixed. The short payout window, one asset, no shorting,
cash injections, batch auction and uncalibrated time scale remain limitations.
Neither candidate becomes the default. There is no fresh LLM or human data.

Independent account arithmetic covers 134,400 account-rounds. A local replay
from the frozen source archive reproduced 16 paths and 112 financial CSVs
byte for byte with network access blocked. This verifies local deterministic
reproduction, not independent-machine reproducibility or additional scientific
scenarios. The main interpretation and R050 feedback findings are integrated
in thesis/FEEDBACK_AND_BACKGROUND_REVIEW.md and draft Sections 5.5-5.6.
