# What the one-auction wealth marks measure

These are accounting checks and exposure consequences, not a strategy-profit
ranking. At zero tax in a uniform-price auction, let q be executed net shares
(buys minus sells), p the clearing price, d the dividend paid afterwards, r the
cash interest rate and M the chosen closing mark. Relative to holding the SAME
opening shares/cash without trading:

`excess wealth = q * ((M - p) + d - r*p)`

Trading swaps cash and shares at p, so at the auction mark(M=p) the immediate
trading gain is zero before income. The remaining difference is dividend versus
cash-interest income on the changed position. A private benchmark mark adds
`q*(benchmark-p)`; it does not turn that benchmark into an executable sale price.

The identity is checked independently against every account under both marks in
all216 base/deeper SAME-ORDER accounting variants. These are reused outcomes,
not216 independent experiments. See wealth_identity_check.json for count/error.
All counterpart excess amounts sum to zero in the specified zero-tax closed
share market. Retain both marks as methods/context; headline execution and
liquidity mechanisms carry the substantive result here. Neither mark establishes
risk-adjusted skill, actual liquidation profits, aggregate welfare or realism.
