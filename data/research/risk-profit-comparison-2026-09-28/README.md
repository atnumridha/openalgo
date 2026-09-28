# Frozen-signal risk and profit comparison

Status: exploratory_comparison_complete. Source start `9494de1aa42864e47fdfb4bef14eec189487dbfd3e01e94c27a8e880e4eccbc3`, end `9494de1aa42864e47fdfb4bef14eec189487dbfd3e01e94c27a8e880e4eccbc3`.

| Variant | Fees | Trades | Wins | Win rate | Net P&L (INR) | Worst window drawdown |
|---|---|---:|---:|---:|---:|---:|
| old-profit-v2 | base | 380 | 157 | 41.32% | -16955.74 | 19.8395% |
| old-profit-v2 | stress | 287 | 111 | 38.68% | -21670.78 | 19.8427% |
| technical-v3 | base | 37 | 12 | 32.43% | -2555.90 | 5.5496% |
| technical-v3 | stress | 37 | 13 | 35.14% | -2019.23 | 4.38% |
| technical-v3-tight-2atr | base | 37 | 12 | 32.43% | -2555.90 | 5.5496% |
| technical-v3-tight-2atr | stress | 37 | 13 | 35.14% | -2019.23 | 4.38% |

These are independent development windows, not a continuous portfolio or evidence of live executable profitability.

The old baseline matches every saved entry/exit identity and net result. All report and input hashes are in `manifest.json`.

## Method and limits

- Same frozen prior ML signals, fixed contracts, holds and cooldown; no refit, threshold or parameter search.
- Five independent capital windows of INR25000; aggregate net is not one continuous account return.
- Full immutable dataset files are hashed and structurally validated; replay and ATR calculations only use listed development sessions. Protected final sessions are not evaluated.
- Historical candles cannot establish executable bid/ask depth, latency, spread or actual fills; these results do not qualify production deployment.
- Base fees reuse the saved user-approved retrospective Kotak cost assumption; stress doubles slippage bps plus 10 and multiplies brokerage by 1.5, as in run_replay.
- ATR overlay is research-only: simple mean of ten true ranges from eleven contiguous preceding option minute bars, reset by session; current-bar high/low/close excluded even at close.
- ATR overlay activates only after observed-open/close gross peak reaches INR600; stop is max(v3 stop, tick-ceiling(observed peak minus 2ATR)). It never widens stops or weakens INR1000-to-INR900 floor.
- An open/close observation already below a newly tightened stop exits at that observation; previously established stops use replay gap/low stop-first handling. No high-before-low ordering is assumed.
- ATR overlay only monkeypatches standalone-process replay functions; it is not a production recipe or configuration option.
- Rejection counts are replay decision events, not a full partition of frozen signals: signals while a position is active are not separately classified.
- Tighter admission and different exits can change subsequent admissions through cash, drawdown and cooldown; comparisons share signals but need not share executed trades.

## Interpretation

The new technical policy remains loss-making in both fee scenarios. Smaller losses coincide with far fewer admitted trades and do not establish a better predictive edge.
Stress can change entry prices, stops, and subsequent drawdown/cooldown admission; a lower aggregate stress loss does not mean higher costs improve the same trades.
The volatility overlay had 0 observations eligible to activate at INR600 gross profit.
It never activated. Identical volatility-variant results provide no comparative evidence about that trail or the advanced INR1000-to-INR900 profit floor. No production promotion is supported.

## Rejection events

- old-profit-v2/base: `{"consecutive_losses_stop": 578, "cooldown": 220, "daily_budget_exhausted": 34, "drawdown_headroom": 933, "entry_gap_filter": 3}`
- old-profit-v2/stress: `{"consecutive_losses_stop": 502, "cooldown": 163, "daily_budget_exhausted": 42, "drawdown_headroom": 1247, "entry_gap_filter": 3}`
- technical-v3/base: `{"consecutive_losses_stop": 6, "cooldown": 20, "entry_gap_filter": 4, "per_trade_risk_exceeded": 2343}`
- technical-v3/stress: `{"consecutive_losses_stop": 7, "cooldown": 18, "entry_gap_filter": 4, "per_trade_risk_exceeded": 2345}`
- technical-v3-tight-2atr/base: `{"consecutive_losses_stop": 6, "cooldown": 20, "entry_gap_filter": 4, "per_trade_risk_exceeded": 2343}`
- technical-v3-tight-2atr/stress: `{"consecutive_losses_stop": 7, "cooldown": 18, "entry_gap_filter": 4, "per_trade_risk_exceeded": 2345}`
