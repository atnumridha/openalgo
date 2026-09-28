# Profit lock from INR300: frozen-signal comparison

| Recipe | Costs | Trades | Wins | Win rate | Net P&L (INR) | Worst window drawdown |
|---|---|---:|---:|---:|---:|---:|
| technical-v3 | base | 37 | 12 | 32.43% | -2555.90 | 5.5496% |
| technical-v3 | stress | 37 | 13 | 35.14% | -2019.23 | 4.38% |
| profit-lock-v4 | base | 37 | 12 | 32.43% | -2466.07 | 5.5496% |
| profit-lock-v4 | stress | 37 | 13 | 35.14% | -2019.23 | 4.38% |

Frozen prior ML signals; no refit, threshold search or final holdout replay.
Five independent capital windows, not a continuous account return.
Historical candles ratchet on observed open/close, not unordered highs; they cannot prove live bid depth, latency or fills.
Current Kotak costs reused as the user-approved retrospective research assumption. Stress doubles slippage bps plus 10 and multiplies brokerage by 1.5.
Old v3 exactly reproduces saved entry/exit identities and net P&L. Stops have no hard profit cap; all-in entry/day/drawdown gates are unchanged.
No production DB writes, broker requests or live eligibility promotion.

Profit amounts are gross before charges. The new floor is max(INR100, peak gross minus INR300), armed at INR300. Stop orders cannot guarantee that realized giveback stays within INR300.
