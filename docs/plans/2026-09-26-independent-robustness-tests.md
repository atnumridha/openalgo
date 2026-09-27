# Fixed-rule robustness tests — registered before new results

Purpose: challenge the positive Run #3 result, not keep selecting parameters until a positive sample appears. No production rule, capital limit or live state changes.

Frozen rule: `trend_breakout`, lookback20, stop10%, target20%, all other parameters and implementation exactly as Run #3. Freeze its specification and implementation hash in local evidence. These retrospective tests use additional dates; they do not prove future profits.

Data: the first 60 shared observed index/options sessions of each calendar quarter of 2025, selected solely by date and availability. Q1 Jan1–Mar27, Q2 Apr1–Jun27, Q3 Jul1–Sep24, Q4 Oct1–Dec29. Keep the same causal universe construction as Dataset #3: select at09:20, one CE and PE when available, nearest expiry1–7 days, premium20–120, strike within500 points, observed volume >=10 prior-NSE-lot quantities. Official prior-session contract definitions, current daily range audit; explicit historical lot sizes and tick0.05. Never repair missing option prices.

Each quarter is bundled with the same already-reserved final60 sessions (Apr24–Jul21 2026) to use the existing UI workflow and date-use ledger. Those final dates are not evaluated or used to choose rules. Queue one development run per quarter using the same hypothetical current fee schedule extended only in the research draft. New dates become recorded development evidence and cannot later be presented as untouched final data.

In addition, replay each entire60-session quarter without resetting equity at the42/18 split. Repeat that continuous quarter under four fixed scenarios: (1)10bps slippage/₹0 brokerage per order, (2)30bps/₹0, (3)100bps/₹0, (4)30bps/₹20. Preserve all risk rules. Every quarter starts independently at₹10,000; never label the sum an annual compounded account return. Repeat these four scenarios on the already-seen60-session2026 development period to test reset sensitivity, clearly marked in-sample diagnostics.

Statistical diagnostics:10,000 five-session block resamples of daily net P&L, seed20260926, on the240 new sessions; resampling is not new market evidence and does not replay risk-dependent order admission. Report profit concentration and arithmetic P&L without the single largest winner, explicitly not an alternate portfolio replay. Include all quarters, stress failures, ambiguous outcomes and missing-data failures.

Support for robustness requires positive aggregate new-period net P&L, at least3/4 positive quarters, positive aggregate30bps+₹20 scenario, at least40 completed base-scenario trades, no incomplete or ambiguous outcomes and positive5th-percentile block-bootstrap sum. These are screening requirements, not proof of future returns or live-release permission. If requirements fail, stop this batch, preserve final holdout and report the failed claim. No rule changes or search expansion based on results.
