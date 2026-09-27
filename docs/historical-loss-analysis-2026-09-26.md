# Why historical Run #2 lost money

This diagnosis applies to the tested Trend and breakout research candidate. It does not establish the performance of other installed Flows.

## Findings from the saved trades and original minute prices

- The run recorded **one win and seven losses** across training and exploratory OOS. All seven recorded losses were expiry-day options and stopped within their entry five-minute bar. The one winner was four calendar days before expiry.
- Losing entry bars had high-to-low ranges of **26.28%–99.59% of opening premium**, compared with a fixed 10% premium stop. This demonstrates a mismatch between the stop and the observed movements in this sample; widening stops has not been tested and is not a proven remedy.
- All three OOS trades were the same `NIFTY30MAR2622450PE` contract on 30 March. The underlying-close signals were at 11:10, 13:50 and 13:55. There is no cooldown, failed-breakout reset or expiry-day exclusion in the current candidate. Re-entry repeats exposure to the same setup.
- With the 20% buffer, initial deployable cash is ₹8,000. A 65-unit lot therefore allows a premium of approximately ₹123.08 per unit before fees. The baseline rejected 157 opportunities as unaffordable. The executed sample is concentrated in cheaper expiry-day contracts; this is a capital/instrument-fit issue as well as a signal issue.
- The signal's alleged second trend confirmation is mathematically redundant. It compares two adjacent 20-close means. Their difference is `(current_close - oldest_previous_close) / 20`. A close above all previous 20 highs necessarily makes that difference positive; a close below all 20 lows makes it negative. Consequently this candidate is effectively a 20-bar range breakout, without independent trend confirmation.
- Fees do not account for most of the OOS loss: the three trades lost **₹1,382.27 before explicit fees but after modeled slippage**, plus **₹29.83 in fees**, giving **₹1,412.10 net loss**.
- Training equity ended at ₹9,077.28 after reaching a ₹11,331.07 peak. This left only **₹12.42** above the 20% drawdown floor. New entries must fit their entire planned risk inside that headroom; this explains why the protection can reject further trades even though total loss from initial capital is only 9.23% and the pause flag has not yet switched on.

## Important correction to interpretation of the five-minute result

The replay explicitly assumes the stop is reached first whenever the same five-minute candle touches both stop and target. This is a conservative modeling convention, not observed event order.

Four recorded losing entry bars touched both thresholds. Inspection of the original one-minute candles found:

| Trade | Minute-data finding |
|---|---|
| 27 Jan, `NIFTY27JAN2625000PE`, entry bar starts 14:05 | Target first at 14:06, before any observed stop touch. The five-minute model records −₹704.21 anyway. |
| 27 Jan, `NIFTY27JAN2625050PE`, entry starts 13:40 | Both thresholds within the 13:40 minute; sequence remains unknown. |
| 27 Jan, `NIFTY27JAN2625150CE`, entry starts 14:55 | Both thresholds within the 14:55 minute; sequence remains unknown. |
| 30 Mar, `NIFTY30MAR2622450PE`, entry starts 13:50 | Stop first at 13:51; target is not touched in that minute. |

The other two OOS losses also touch the stop before the target in the minute data. Thus **the OOS losses remain supported by this finer-resolution check**, while the training loss amount is materially sensitive to candle aggregation. Minute candles still cannot resolve within-minute order, bid/ask spreads, tick rounding or actual fills.

Do not flip one trade to a winner and present a revised portfolio return: changed outcomes alter future equity, sizing, entry admission and later trades. A complete chronological rerun is required. No stored UI result was altered by this diagnostic.

## What needs improvement

1. Separate five-minute signal construction from one-minute execution replay, retaining explicit ambiguity when both thresholds fall within a minute.
2. Define expiry, liquidity and premium/lot affordability rules before a new run; choose a universe that fits ₹10,000 rather than allowing affordability to concentrate entries near expiry.
3. Add a genuinely independent trend/regime condition and a specified re-entry/cooldown rule. Evaluate these as new hypotheses, not as proven profitable fixes.
4. Validate a fixed version on untouched data and forward paper trading after development screening. Keep the 60 reserved sessions sealed while diagnosing and changing the model.

Only eight executed trades across a bounded contract selection are insufficient to estimate a durable trading edge. The prior UI test validated execution of the software workflow; it did not validate profitability or precise real-world fills.

Evidence: `data/research/recent-ui-test-2026-09-26/loss-diagnostics.json`, `run-2.json`, trade exports, the original one-minute Parquet file and `services/research/replay.py`. No trading rules, capital settings or live controls were changed during this analysis.
