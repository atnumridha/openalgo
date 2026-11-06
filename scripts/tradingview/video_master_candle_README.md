# PK rejection rules — corrected reference replay

Pine source: `video_master_candle_strategy.pine`. Chart title: **PK Rejection Rules | Reference S/R**.

The correction follows the user's supplied Marathi transcript and reviewed rejection diagrams. It implements the disclosed entry and stop rules. **It does not recreate the undisclosed automatic S/R or PK/R1/R2 label formulas.** Default S/R inputs are zero, so an unconfigured chart shows WAIT and produces no trades. Supertrend and option-premium ATR stops have been removed.

## Corrected rules

1. A candle sweeps a supplied support/resistance level and closes back on the original side. Its color is unrestricted.
2. The immediately following candle must confirm direction: bullish above support, bearish below resistance.
3. Once that confirmation candle closes, its high plus one tick arms a Bull stop entry, or its low minus one tick arms a Bear stop entry. The order can fill during any of the **next three candles**, including on a wick. No entry can fill on the confirmation candle itself. Unfilled orders are cancelled after the third subsequent candle.
4. Rejection stop modes are separate: **S/R close** exits when a candle closes beyond the frozen setup level; **Sweep extreme** uses a native price stop one tick beyond the actual sweep candle's low/high. The small confirmation-candle technical stop is not substituted for either mode.
5. A supplied PK label candle arms its own high/low entry and uses **its own** opposite extreme for the price stop. No prior-candle or rejection stop is substituted.

Default one-tick high/low buffers and freezing the setup reference are explicit implementation choices. The transcript does not numerically define these. Its two rejection examples are not automatically named R1/R2 here because their exact label-selection rules are not supplied.

## Configure an actual reference

Use a standard **5-minute NIFTY or SENSEX underlying chart**.

- **Manual S/R:** enter a known original support and/or resistance level. A zero value disables that side. A constant level applies throughout the selected replay range, so use it only for the period where that level was valid.
- **Original indicator plots:** add an accessible original indicator to the same chart, select its separate support/resistance plots, and enable only the sources actually selected. The last completed bar's plot value is used as the sweep reference. This requires exposed numeric plots; visual labels or private unplotted calculations cannot be read.
- **Known PK candle:** select its exact chart-bar time and direction. Alternatively, connect a compatible numeric PK direction plot that returns +1 on Bull label candles, −1 on Bear label candles, and 0/na otherwise. These controls replay supplied labels; they do not invent PK detection.

The original creator's [PK S&R Master Setup listing](https://www.tradingview.com/script/PcS6jjhV-PK-S-R-MASTER-SETUP-3-in-1-Combo/) is invite-only. Access and compatible plots have not been established.

## Replay and display

Default range remains **27 October 2026, 09:15–15:30 IST**. Set the dates for another session as needed. No new order is armed at session end; existing positions close at 15:30. Pending state resets on session/date boundaries and missing bars.

Bull / BUY CALL and Bear / BUY PUT are **underlying directional labels**. Native simulated orders trade one chart/index unit. An option-premium chart is rejected: copying index S/R levels into option prices would produce invalid option risk and P&L. A corrected option backtest remains dependent on verified original signals and an explicit cross-instrument execution model.

The transcript does not give a fixed target formula. The optional R target is **disabled by default**. If enabled, it uses planned trigger-to-stop risk; gaps can change actual fill risk. The reel's 1.04R drawing is an example, not a universal target rule. No trailing formula or Master-level sideways recovery is invented.

Properties defaults: ₹100,000 capital, one chart unit, 0.10% commission per side, zero simulated slippage, no pyramiding, calculation on bar close, pending stop orders available from the following bar. These are simulator assumptions, not Kotak charges or executable quotes.

## Historical ambiguity

OHLC data cannot establish whether a price-stop invalidation happened before or after an entry in the same bar. If an entry bar touches its protective price stop, the script suppresses the Bull/Bear signal, immediately flattens any remaining simulated position and increments **Ambiguous entry/stop bars**. The emulator's trade ledger is retained; it is not retrospectively erased. Any nonzero count marks the replay **UNVALIDATED**, and its P&L must not be described as the original indicator's performance. Lower timeframe evidence is needed to resolve such cases.

## Validation and history

The behavioral suite executes the actual Pine core and native simulated orders using synthetic candles. It covers the corrected stops, either sweep color, adjacency, wick triggers, three-bar expiry, frozen risk, known PK candle stops, source WAIT and ambiguous fills. TradingView compilation is a separate check.

The earlier rejected approximation is preserved at `docs/validation/video-master-candle/2026-10-27-approximation.pine`. Its old CE/PE results are **not corrected results** and must not be attributed to this version or the original indicator.

[Sofien Kaabar's article](https://kaabar-sofien.medium.com/the-master-candle-pattern-recognition-in-tradingview-80316988f396) describes a different seven-candle containment/breakout pattern. That pattern has not been added to the PK rejection rules.
