# Conditional LLM order influence (R054)

All 216 R043 auctions reconstructed exactly; 432 isolated counterfactual clears. Three existing seeds, eighteen existing paths; no new model calls or adaptive trajectories. Cap10 retains accepted side/limit and caps each target quantity at ten; remove suppresses both target orders while retaining accounts. Other orders, opening state and allocation RNG are fixed.

| Seed | Intervention | Changed prices / 72 | Mean absolute price impact (% previous close) | Volume reduction (%) | Changed target fills at same price |
|---|---|---:|---:|---:|---:|
| 22853 | cap10 | 18/72 | 0.699430 | 17.576 | 13 |
| 22853 | remove | 33/72 | 0.941625 | 29.886 | 14 |
| 23971 | cap10 | 20/72 | 0.524646 | 14.403 | 5 |
| 23971 | remove | 23/72 | 0.925998 | 23.626 | 15 |
| 25087 | cap10 | 11/72 | 0.907597 | 13.987 | 9 |
| 25087 | remove | 18/72 | 1.065402 | 24.094 | 15 |

All individual markets (twelve nested auctions each):

| Seed | Mode | Draw | Intervention | Cap-affected frames | Price changes | Mean absolute impact (%) | Volume reduction (%) |
|---|---|---|---|---:|---:|---:|---:|
| 22853 | A | 1 | cap10 | 6 | 4 | 1.522056 | 25.526 |
| 22853 | A | 1 | remove | 6 | 4 | 1.645227 | 36.036 |
| 22853 | A | 2 | cap10 | 10 | 3 | 0.124793 | 8.439 |
| 22853 | A | 2 | remove | 10 | 7 | 0.342350 | 23.207 |
| 22853 | B | 1 | cap10 | 10 | 2 | 0.839627 | 22.654 |
| 22853 | B | 1 | remove | 10 | 6 | 1.563505 | 38.835 |
| 22853 | B | 2 | cap10 | 5 | 4 | 1.130277 | 23.137 |
| 22853 | B | 2 | remove | 5 | 6 | 1.313416 | 36.471 |
| 22853 | C | 1 | cap10 | 11 | 3 | 0.124793 | 0.000 |
| 22853 | C | 1 | remove | 11 | 6 | 0.249585 | 10.345 |
| 22853 | C | 2 | cap10 | 5 | 2 | 0.455033 | 17.992 |
| 22853 | C | 2 | remove | 5 | 4 | 0.535666 | 25.941 |
| 23971 | A | 1 | cap10 | 8 | 4 | 0.288443 | 12.177 |
| 23971 | A | 1 | remove | 8 | 5 | 0.700425 | 21.402 |
| 23971 | A | 2 | cap10 | 5 | 4 | 0.984554 | 19.310 |
| 23971 | A | 2 | remove | 5 | 5 | 1.479766 | 28.621 |
| 23971 | B | 1 | cap10 | 3 | 3 | 0.434240 | 11.923 |
| 23971 | B | 1 | remove | 3 | 3 | 0.741039 | 18.846 |
| 23971 | B | 2 | cap10 | 3 | 2 | 0.345844 | 15.769 |
| 23971 | B | 2 | remove | 3 | 2 | 0.652643 | 24.231 |
| 23971 | C | 1 | cap10 | 6 | 3 | 0.887992 | 18.705 |
| 23971 | C | 1 | remove | 6 | 4 | 1.377840 | 30.576 |
| 23971 | C | 2 | cap10 | 5 | 4 | 0.206805 | 6.696 |
| 23971 | C | 2 | remove | 5 | 4 | 0.604273 | 16.071 |
| 25087 | A | 1 | cap10 | 4 | 1 | 0.766568 | 17.722 |
| 25087 | A | 1 | remove | 4 | 2 | 0.811251 | 26.266 |
| 25087 | A | 2 | cap10 | 6 | 1 | 0.408654 | 14.103 |
| 25087 | A | 2 | remove | 6 | 1 | 0.408654 | 25.641 |
| 25087 | B | 1 | cap10 | 6 | 3 | 1.304274 | 12.784 |
| 25087 | B | 1 | remove | 6 | 4 | 1.501586 | 24.432 |
| 25087 | B | 2 | cap10 | 5 | 3 | 1.347251 | 13.783 |
| 25087 | B | 2 | remove | 5 | 3 | 1.347251 | 21.114 |
| 25087 | C | 1 | cap10 | 4 | 2 | 0.853863 | 13.580 |
| 25087 | C | 1 | remove | 4 | 5 | 1.317253 | 25.926 |
| 25087 | C | 2 | cap10 | 3 | 1 | 0.764974 | 12.102 |
| 25087 | C | 2 | remove | 3 | 3 | 1.006417 | 21.338 |

The JSON report retains all/affected denominators, signed and benchmark-gap changes, maker inventory and full examples. Lower volume follows mechanically from reducing orders in this maximum-volume auction; the magnitude and price response are the observations. No estimate of persistent caps, agent-count scaling, human behavior or welfare follows.
