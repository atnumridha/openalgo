# Strategy and rule review — 28 September 2026

## What was verified

The running account has seven armed **Sandbox** strategies, all with live opt-in off. Every strategy completed scheduled checks at 09:38 and 09:47 IST. There were no managed runs when inspected. Bollinger reached entry admission at **09:35 and 09:40**, and the saved governor rejection reported `minimum_reward_risk = 1.126016260162601626016260163`. Thus “nothing started” includes both legitimate no-signal checks and concrete rejected entry attempts.

Both saved risk accounts allocate **₹10,000**, with `equity-1pct-v2`. This intentionally computes an all-in cap of **₹100 per trade / ₹300 per day** at that equity. At ₹25,000 it computes **₹250 / ₹750**, not a flat ₹300 / ₹2,000. The approved hardening plan deliberately preserved saved allocations and adopted percentage limits, one managed position, and a stop after three consecutive net losses. Monitoring does not change them.

This is a code and current-evidence review, not a new profitability or accuracy backtest. No order was forced and no live permission was enabled.

## Findings

### P1 — Current stop geometry is generally incompatible with the newer budget

`services/strategy_module/scalping.py::protect_leg` uses 10 option-premium points for Opening Box and `min(₹800 / quantity, 20% of premium)` for the other profiles. The technical profit recipe preserves that distance; it deliberately does not shrink a technical stop to fit the account.

For an illustrative 65-unit lot at a ₹200 premium, the shared recipe produces:

| Candidate | Stop distance | Gross planned loss | Current ₹10k all-in cap |
|---|---:|---:|---:|
| Common scalp distance | ₹12.30 per unit | ₹799.50 | ₹100 |
| Opening Box | ₹10 per unit | ₹650 | ₹100 |

Costs increase the required budget further. Box cannot fit the policy’s absolute ₹300 maximum whenever the lot has more than 30 units, even if capital increases. Normal ATM/ITM premiums usually put the other profiles near the ₹800 distance ceiling. That explains why valid technical signals can still produce no entry.

**Correction:** define a genuine, versioned stop from executable option-market structure and evaluate feasible whole-lot candidates before claiming an executable setup. Reject candidates that cannot fit the budget. Do not create artificially tight stops or relax the risk cap merely to obtain trades. Requalify any changed entry/exit recipe on independent data.

**Regression needed:** real lot sizes, realistic premiums/spreads/costs and each profile must yield an explicit affordable or unaffordable result consistent with the same admission calculation.

### P1 — Runner milestone and reward-to-risk admission disagree

`services/risk/cash_exit.py::_geometry` explicitly makes ₹900 a **reporting milestone**, while `services/risk/profit_exit.py::evaluate_profit` removes the fixed take-profit so the position can run. `portfolio_governor.py::_collect_facts` nevertheless treats that milestone as a fixed premium target. With the sample above, its rounded 13.85-point milestone divided by a 12.30-point stop gives **1.12601626016R**, exactly the observed Bollinger rejection.

Worse, EMA9/15, MACD200, EMA5 and Regime50/200 can substitute the old underlying-index 2R geometry, despite the actual exit basis being option premium. SMA, Bollinger and Box retain the premium calculation. Equivalent option-risk recipes therefore reach different admission conclusions depending on profile metadata.

**Correction:** define one explicit admission contract for the versioned runner recipe. Separate a milestone from an executable target, use the actual exit instrument consistently, and retain the independent all-in cash-loss gate. Do not simply bypass the governor or assert the runner guarantees 3R.

**Regression needed:** identical premium stop/cost/runner geometry must receive the same admission verdict across all seven profiles; legacy recipes must retain their historical rules.

### P2 — An unrelated owner’s run can block session risk facts

`services/strategy_module/portfolio_governor.py::_session_history` traverses global active run IDs. It checks missing broker and invalid/prior-session start time **before** loading the strategy and checking its owner. An old or malformed same-mode run belonging to another owner can make the current owner’s risk facts unavailable.

This is independent of the observed Bollinger rejection and was found through code inspection, not a production incident for this account.

**Correction:** establish owner scope before validating account-specific run evidence. Add an Alice/Bob test where Bob’s prior-session or malformed run cannot block Alice’s otherwise clean entry facts.

### P2 — A transient waiting message concealed earlier rejected entries

The previous list label showed armed/waiting after a later no-signal check, so the earlier governor refusal was not visible without reading logs. The new Automation Review screen preserves the latest failed execution and risk-rejection evidence separately from the current state. It also captures closed-bar input/indicator snapshots, freshness, conditions, raw retained events, orders and fills.

This observability issue is addressed in this change. The trading-rule findings above are documented for correction, not silently changed during a monitoring rollout.

## Intentional restrictions that reduce trades

- EMA50/200 requires a **fresh crossover**, prior-day trend confirmation and a low-volatility daily regime. Existing alignment alone does not trigger.
- MACD200 combines a crossover on the required side of zero, EMA200, a recently confirmed pivot retest and at least 604 completed five-minute bars.
- EMA9/15 requires NIFTY candle structure, normalized slopes and same-bar Bank Nifty confirmation. The normalized slope is an explicit approximation; visual chart angles are not invariant to chart scaling.
- EMA5 uses asynchronous alerts and a subsequent one-minute break; simultaneous directions, gaps and session changes suppress a trigger.
- Opening Box considers only the **first** breakout close between 09:31–09:45. A weak first breakout consumes that day’s opportunity. Waiting after this window is not evidence of a stopped scheduler.
- SMA5/34 is a sign-change rule, while Bollinger is an outside-band reversal hypothesis. Neither is evidence of a proven trading edge.
- Signals older than 55 seconds are refused. Only completed candles are eligible. Data/quote/contract/cost/risk/qualification checks can still refuse a valid pattern.

More signals would require changing the hypothesis and testing it again; a no-trade morning does not establish a defect or justify weakening confirmation rules.

## Recommended sequence

1. Reconcile stop geometry and runner admission into one versioned, internally consistent execution contract.
2. Confirm intended saved allocation explicitly through the existing account controls; do not confuse allocated capital with broker buying power.
3. Fix owner scoping in session history and add the boundary regression.
4. Test eligible and blocked candidates for all seven profiles under current costs and whole lots; then compare untouched out-of-sample data and forward sandbox results.
5. Keep live entry gated until the same final configuration completes its qualification and explicit release process.
