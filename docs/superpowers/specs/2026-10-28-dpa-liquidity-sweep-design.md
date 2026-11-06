# DPA liquidity sweep strategy

Implement and test the linked Daily Price Action method as a separate Pine v6 strategy for standard NIFTY/SENSEX price charts. Preserve the PK and BB/Chikou scripts. The article is reference material, not operational authorization.

## Source and scope
https://dailypriceaction.com/blog/liquidity-sweep-reversals/ (read 28 October 2026, including its annotated acceptance example).
Use 15-minute entries with completed 1-hour context, 62–79% retracements, a sweep followed by a later confirming close, sweep-extreme stops, external-extreme targets and a minimum 2R filter. Bull and Bear are underlying directional signals. Option premium execution is outside this index backtest.

## Implementation decisions
The article selects structure visually. Automatic mode uses adjustable confirmed symmetric pivots (default 2 left / 2 right) at both timeframes. A bearish impulse is captured at a confirmed lower low with lower highs; bullish is mirrored. Preserve that impulse during its retracement, until a replacement impulse or origin breach. Completed HTF values only, no retroactive labels.
A qualifying local high/low must form after that context became available, and lie inside OTE. The triggering level is the lowest low / highest high after that local swing and before the sweep, matching the source illustration. Require the sweep to close back through the swept level and confirmation on a later candle. Extend the conservative stop if the sweep extreme extends before confirmation. Invalidate if the origin or target is touched before entry or the HTF impulse changes. These mechanical definitions are our explicit choices.
Choose the article's close-entry branch; discretionary FVG retest entry and mean/distribution-channel judgments are not modeled. Default stop buffer is 2 minimum ticks. Model 0.02% commission per fill and one tick adverse slippage; require net modeled reward/risk >= 2. Costs remain editable in TradingView Properties, but the admission filter's cost inputs must match them. One unit and no pyramiding. No day-end flattening: the article holds trades across sessions.

## Approaches
Chosen: automatic confirmed pivots, because the user requested implementation and testing and already uses TradingView. Manual-only anchors would make a general test depend on hand-picked levels. A trend indicator proxy would not implement the source's structure/OTE requirements. Pivot parameters and unmodeled discretion must be visible to the user.

## Presentation and validation
Separate name: DPA Liquidity Sweep | OTE. Bull/Bear entry labels, OTE band, swept and trigger levels, frozen trade stop and target. Table with context, phase, levels, planned R and gross index results. Use actual production Pine in deterministic tests, and compile/run on TradingView with the chart, interval, date coverage, costs and results recorded. Index results do not represent CE/PE profits.
