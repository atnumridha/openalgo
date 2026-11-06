# New book patterns, trend and risk indicator

Status: user selected the recommended single-plan pattern-plus-trend approach on 5 November 2026. Proceed with that approach and the reviewed explicit defaults; retain the alternatives as design history.

## Request and preservation

Create a new, separately named indicator from the 55 photographs in `WhatsApp Unknown 2026-11-05 at 6.26.34 PM.zip`. It should recognize the reference patterns on received chart candles, draw their geometry, explain the expected direction and next condition, and provide entry, exit and risk references. Earlier display preferences carry forward: confirmed annotations from the latest ten candles by default, pending observations hidden, with optional complete history.

Deliver a separate TradingView Pine script and a separately selectable OpenAlgo study, provisionally **OpenAlgo Book Patterns & Risk**. Keep OpenAlgoAll, its source, existing pattern engines, settings, and saved TradingView script unchanged. Adding a study registration and host drawing hook does not replace the existing indicator. Do not change trading bots, broker risk limits or order execution. Risk references in this indicator do not place or manage actual orders.

Preservation hashes are recorded in `workspace/book-pattern-risk-guide-2026-11-05/existing-indicator-hashes-before.json`. Verify these protected files again after implementation. The serving OpenAlgo checkout is `/Users/nmandal/.codex/worktrees/neo-native/openalgo`; the primary workspace holds the Pine scripts. Changes must be bounded and must preserve unrelated work in both checkouts.

## Approaches

1. **One combined plan with pattern-specific trend confirmation — recommended.** Detect and draw all supported formations, then select one current qualified Entry/SL/Target reference. Show other matching patterns and reasons for waiting in the guide. Continuation and reversal formations use different trend context. This fits the request for a combined indicator and limits overlapping trade plans.
2. **Independent plan for every confirmed pattern.** Each pattern has its own entry and risk references. This exposes disagreements directly but creates overlapping levels and more chart clutter.

The user selected approach 1: “One plan: pattern + trend confirmation (Recommended)”. Once selected, a plan stays frozen until stop/target reference touch or expiry; newer evidence is shown alongside it and does not replace it automatically. Numerical defaults below remain explicitly identified implementation choices, not quotations from the reference book.

## Reference coverage

Every photograph was visually inspected. Detailed evidence, including uncertain or contradictory text, is retained in the three `reference-*.md` files under the workspace evidence directory. Photo numbers below follow archive order, not page order. General prose, candle anatomy and chapter covers are contextual material rather than separate trading signals.

| Photos | Coverage |
|---|---|
| 01–03 | Psychology, capital preservation, volume, risk/reward, position size and drawdown discussion |
| 04–09 | SMA/EMA and price/MA crosses, 20/50 MA illustration, MACD 12/26/9, MACD signal/zero crosses, RSI 14 and 30/70 recrosses, confirmed RSI/MACD divergence |
| 10–12 | Symmetrical, descending and ascending triangles |
| 13–19 | Bull/bear flags, cup and handle, bull/bear rectangles, falling/rising wedges |
| 20–25 | Inverse/head and shoulders, triple bottoms/tops, double bottoms/tops |
| 26–27 | Direct breakout, breakout/retest and failed-breakout observations |
| 28–30 | Rising/falling three methods, tweezer bottom/top |
| 31–36 | Three black crows/white soldiers, bearish/bullish harami, dark cloud cover, piercing line |
| 37–44 | Evening/morning star, bullish/bearish engulfing, shooting star, hanging man, inverted hammer, hammer |
| 45–46 | Doji and double doji, long-legged/dragonfly/gravestone context, bullish/bearish marubozu and spinning top |
| 47–50 | Candle anatomy; support/resistance construction and role reversal; close-confirmed breakout followed by next-candle extreme breach; gaps |
| 51–52 | Trendlines, breakout followed by retest, trendline support/resistance context |
| 53–55 | Pattern limitations, taxonomy and reference title; no additional mechanical signals |

Doji variants, spinning tops and gaps can be observations without a directional entry. A failed bullish breakout does not automatically authorize a short plan. Require a separately confirmed bearish setup for that plan, and vice versa.

### Source differences that must survive implementation

- Bull rectangle: the text permits a breakout-candle-low stop. Bear rectangle: the text specifies above rectangle resistance. Preserve this asymmetry.
- Bull harami: the text uses the second candle's low for its stop. Bear harami: the example places the stop above the first high.
- Rising/falling three methods: corrective-candle extremes and complete-pattern extremes differ in text and sketches. Use the corrective extremes only when they remain beyond the confirmation entry in the correct direction; otherwise withhold a plan and explain the invalid geometry. Record this conservative conflict resolution.
- Hammer: the printed stop is the swing low. Cup and handle: stop below handle low. Wedges: stop beyond the last appropriate structural extreme.
- Head/shoulders and multi-top/bottom sketches sometimes place stops near the shoulder or breakout candle. Do not silently substitute full-pattern stops for every family. Use the explicitly supported stop where clear; label a conservative structural fallback as a local rule when unclear.
- Photos 24/25 mix multi-swing double top/bottom diagrams with adjacent-candle prose. Implement multi-swing structures separately from tweezer/candle formations; do not collapse them into one detector.
- Photo 49 explicitly requires a close beyond support/resistance and a next-candle breach of the breakout candle's extreme. Photo 51 requires a trendline break followed by retest.
- RSI extremes alone are not entries. The reference warns that overbought/oversold conditions can persist.
- Ignore inconsistent tiny anatomy/diagram labels when they contradict OHLC geometry. Keep uncertain interpretations documented.

## Proposed executable rules for missing definitions

The book leaves pivot selection, tolerances, most target formulas, numerical trend filters and sizing mechanics undefined. The following are configurable implementation choices, not claims that the book specifies them:

- Use standard OHLC candles and actual timestamps. Use only completed, valid candles for confirmation. Forming-candle progress can update with quotes, but cannot create a confirmed signal.
- Use confirmed 3-left/3-right pivots by default, configurable from 2 to 10. A pivot becomes usable only when its right-side candles have closed. Record both the pivot time and the later recognition time; do not backdate signals.
- Normalize shape tolerances using ATR14 and tick size. Default flat/equal-level tolerance: 0.25 ATR. Require two confirmed contacts on each boundary for triangles/wedges/rectangles. Suggested formation span: 12–180 bars. Equal-high/low candle tolerance: max(two ticks, 0.05 ATR).
- Fit boundaries through confirmed alternating swings; require the expected slope, positive width and actual convergence where applicable. A wick crossing a line does not establish a completed breakout.
- Flags require a preceding directional impulse of at least 3 ATR over 3–15 bars, a 4–20 bar corrective channel, and no more than 50% pole retracement. Cup-and-handle requires a rounded U base, comparable rims and a shallower handle in the upper part of the cup; reject sharp V examples. Implement and test the detailed deterministic geometry rather than using the pattern name alone.
- Candle-body thresholds are explicit settings: doji body at most 10% of range; small body at most 30%; long body at least 60%; negligible wick at most 10%. Hammer/inverted-hammer/shooting-star dominant wick must also be at least twice the body, matching clear reference text.
- Offer explicit pattern-specific gap comparisons by default, as enumerated in the appendix. Where the photographs are ambiguous, label that comparison as a local interpretation. A continuous-market variant may relax gaps only when selected, and must be labelled as a local variant. Do not describe every gap choice as an exact book requirement or silently change rules for crypto.
- Default trend context uses EMA20/50, with selectable SMA/EMA. Continuation plans require the appropriate preceding trend and a confirmed directional break. Reversals require the opposite preceding trend plus price confirmation; do not impose a requirement that the slow MA crossover must already have occurred. The guide must state when the broader MA trend still conflicts.
- RSI14, MACD12/26/9 and volume evidence are visible context. They are independently selectable filters rather than a universal requirement that all indicators agree. Volume expansion uses 1.2 times SMA20 when enabled. Missing/unreliable volume is shown as unavailable, never treated as a passing volume filter.
- Divergence pairs the oscillator value with the same confirmed price-pivot bars, with 5–80 bars of separation. Divergence is a setup observation until the required price breakout confirms it.

These defaults need positive and negative fixtures, mirrored directions, boundary cases and prefix-by-prefix checks. Tune them through explicit settings; do not claim they are an optimized or profitable strategy.

## Confirmation, guidance and drawings

Keep detection, confirmation and the plan lifecycle separate. A completed formation is a pattern observation; a qualified entry requires its own trigger.

- Candlestick entries use a later completed candle's close beyond the documented trigger extreme. Where the source explicitly requires the very next candle, expire that trigger after one candle. For examples without a specified deadline, propose a configurable three-candle trigger window.
- Structure breakouts confirm when a completed candle closes beyond their projected boundary. The entry reference is that confirmation close unless the source specifies a later trigger. Do not depict the earlier boundary price as an achieved fill.
- Trendline break/retest waits for a later retest and directional closing rejection within a proposed ten-bar window. Do not treat a touch during the break candle as a later retest.
- Freeze the pattern geometry, stop and target when a plan qualifies. New quotes update distance/progress, not the historical confirmation or initial stop. Never loosen the original stop automatically.
- If the confirmation bar also breaches the proposed stop, withhold the plan because intrabar ordering is unknown. If a later candle crosses both SL and target, show an ambiguous reference-touch result instead of assuming which happened first.
- When bullish and bearish qualified evidence conflicts, display WAIT with both reasons. Do not silently select a direction by array order. Otherwise use deterministic priority: source-complete trigger first, structure plus confirming candle next, then standalone confirmed candle. Show additional matching patterns in the guide.
- Draw confirmed shape boundaries/necklines, relevant swing connectors, breakout/retest markers and the selected plan's Entry/SL/Target lines. Draw neutral candle observations only when enabled. Keep pending geometry and unconfirmed labels off by default.
- Default labels cover confirmations on the latest ten chart candles. Full-history display is optional and bounded. The latest plan levels may remain until invalidation/target/expiry while their old pattern label is hidden. Changing that policy must not reveal old labels by default.
- Refresh explanations on every received candle/quote. Explain the pattern, context, expected direction, exact next condition, invalidation and reason for WAIT. A disconnected/stale source must retain references with an explicit unavailable status and emit no new confirmed alert.
- Offer confirmed-pattern, qualified-plan, stop-reference-touch and target-reference-touch alerts. Alerts wait for completed candles and are deduplicated by symbol, interval, pattern and confirmation time. These are observations, not broker fill confirmations.

## Entry, exits and risk references

Use measured targets where the photographed text clearly defines them: ascending triangle and rectangles use pattern height projected from breakout. For the other families, use a clearly labelled configurable R target, proposed default 3R, or a confirmed relevant support/resistance target where the source calls for it. Display the selected target method. Reject a target on the wrong side of entry.

Propose a minimum reward/risk filter of 3R by default, configurable. A pattern whose supported structural target offers less room still appears as confirmed geometry, with WAIT and the calculated ratio. Never stretch the structural target just to make the ratio pass.

Risk controls are planning inputs in the new indicator only:

- Account equity defaults to zero/unset. Proposed risk percentage defaults to 0.25%; it is configurable. The book's 2% illustration is not applied automatically to this account.
- Calculate risk cash from entered equity and risk percentage, then divide by entry-to-stop distance multiplied by verified value per price unit. Round size down to the supported quantity/lot step. Optional cost/slippage inputs reduce the available risk budget.
- Show monetary sizing only when account currency, quote currency/conversion, point value/contract multiplier and quantity step are known or explicitly entered. Otherwise show the missing input and keep the price-level plan visible.
- Option premium plans use that option's premium, contract multiplier and lot size. Underlying-index levels cannot be used as option-premium entry or stop values. Index charts without a specified tradable product cannot claim broker-ready position size.
- Show estimated risk cash, price risk, target reward and reward/risk. Account balances, existing positions, available margin and realized P&L are not inferred from a chart.
- Fixed structural SL and target are the default exit references. No automatic trailing, scaling out, daily loss lockout or capital-risk change is inferred from the photographs. Existing live-bot protections and account limits remain unchanged.

## Implementation boundaries and verification

Create new Pine and OpenAlgo engine/drawing/guide files with independent settings and storage keys. Suggested Pine filename: `scripts/tradingview/openalgo_book_patterns_risk.pine`. Suggested OpenAlgo study ID: `book-pattern-risk-guide`. Reuse immutable common candle/time types and chart host facilities where useful; do not modify old detector logic or replace the existing Pine script.

Permitted existing-file integration is limited to additive registration/rendering in `NeoMarketChart.tsx`, `chartStudyChoices.ts` and, if needed, `NeoTradingViewWorkspace.tsx` plus their relevant tests. Do not edit protected `ToolkitPanel.tsx`, `ToolkitLayer.ts` or any old engine. Add the new study to the current chart without removing or changing existing selected study IDs; use separate keys for the new study's detailed settings. No global defaults migration is needed. If an unforeseen host change is required, update this explicit integration boundary before making it.

Tests must verify each covered pattern and its invalid examples, the source-specific stop differences, closed-candle timing, prefix invariance, gap mode, volume unavailable behavior, risk-unit conversion/rounding, conflicting signals, ambiguous SL/target candles, label retention, stale-feed behavior and parity between the actual Pine core and the OpenAlgo engine. Pattern coverage must map back to the reference ledger so no photo family is silently omitted.

Verify native TradingView acceptance of the new script and actual OpenAlgo rendering. Test symbol/interval changes, hover during refresh, repeated automatic refresh and large retained history. Save a bounded diff and check preservation hashes. Do not describe synthetic fixture outcomes as profitability or live trading evidence.

Proposed visual retention budgets: at most 40 complete shape drawings, 80 polylines, 160 labels and 120 line objects, reserving capacity for the selected plan. Drop the oldest complete formation when necessary; do not allow partial geometry to survive automatic garbage collection. Delete only drawings owned by the new layer. A full-history switch means retained historical formations within these limits, not an unlimited object count.

### Platform references verified during design

- TradingView documents that real-time bar confirmation occurs on the closing update. Use that distinction for confirmed events and keep pivot recognition time separate from the older pivot bar. [Bar states](https://www.tradingview.com/pine-script-docs/concepts/bar-states/), [repainting](https://www.tradingview.com/pine-script-docs/concepts/repainting/).
- Pine drawing counts are finite, so explicit retention and whole-formation cleanup are required. [Drawing limits](https://www.tradingview.com/pine-script-docs/writing/limitations/).
- The platform's fixed-risk sizing example uses stop distance and contract point value. This indicator must use entered equity and validated instrument units instead of a strategy's simulated equity or an assumed broker balance. [Position sizing example](https://www.tradingview.com/pine-script-docs/faq/strategies/).

## Approval requested

Review the separate-indicator approach, confirmation behavior and explicitly proposed numerical defaults. Implementation begins only after this design is approved or the user explicitly asks to skip the design discussion. The existing indicator remains unchanged meanwhile.

## Executable rules appendix — proposed local definitions

This appendix settles implementation choices identified in the builder check. Numerical definitions below are proposals wherever the photographs do not define them. The source ledgers remain authoritative about what was actually visible.

### Common geometry and timing

1. Ignore invalid, nonfinite, nonpositive OHLC, inconsistent high/low ranges and zero-range candles for directional pattern calculations. Do not repair such a candle into an eligible signal. Keep unavailable inputs visibly unavailable.
1a. Completion adapters may provide validated actual UTC `closeTime` (strictly after bar time), particularly for shortened final-session and daily candles. Otherwise use bar time plus interval. Eligibility is capped by both current time and the fixed successful history `observedAt`; clock passage alone cannot promote cached OHLC. Keep `quoteObservedAt` separate for live-quote freshness; a new history response does not refresh an old quote. Pine uses its actual `time_close`.
2. Use Wilder ATR14 from the preceding completed bar for a newly evaluated formation's scale; freeze that scale with the event. Use at least two ticks for equal-level geometry tolerance even when 0.25 ATR is smaller. Confirmation requires one full tick beyond an anchor; equality alone is not a break.
3. Pivots are strict extrema over their 3+3 window. Adjacent same-side pivots collapse to the more extreme one, with the earlier pivot winning exact ties. Consecutive alternating pivots must be at least three bars apart. Their actual timestamps, indices and recognition times remain available.
4. A formation's boundary anchors must be usable before the breakout candle begins. If a right-side pivot becomes known only on that breakout candle or later, do not retrospectively qualify that earlier break. Subsequent closes may confirm only after the geometry is known. Freeze line anchors at breakout; later pivots cannot change that event's retest line.
5. For two-boundary structures, use the most recent two confirmed highs and two confirmed lows in alternating order, spanning 12–180 bars. Each boundary must contain its two anchor contacts. Reject intervening completed closes outside the fitted boundaries by more than tolerance. Record the complete anchor sequence for drawing.
6. Flat means the two boundary-anchor prices differ by no more than tolerance. Rising/falling means they differ by more than tolerance in the corresponding direction. Converging means positive width that narrows to less than 75% of its width at the first shared boundary time; the breakout must occur before the fitted lines cross. Parallel means end width remains between 75% and 125% of starting width. Exact 75% belongs to parallel, not converging.
7. Stop buffer is max(one tick, 0.05 frozen ATR), rounded outward to a valid tick. This places a breakout-candle-low stop below that low rather than on it. Long stop touch uses low <= stop; short uses high >= stop. Check confirmation-bar invalidation against the buffered stop, not an unbuffered source anchor. Target touches are inclusive.

### Shape contract

Here `B` is the projected breakout boundary at confirmation, `H` is the greatest vertical boundary separation over the formation's anchor interval, and `R` is the entry-to-buffered-stop price distance. Unless a following candle is specified, entry reference is the first completed close at least one tick through B. The R target is a local fallback, not a book-defined measured objective.

| Family | Detection / context | Trigger and stop | Target |
|---|---|---|---|
| Symmetrical triangle | Upper falling, lower rising, converging | Break either line; stop beyond most recent opposite-side swing | 3R local fallback |
| Ascending triangle | Upper flat, lower rising, converging; preceding uptrend | Close above upper; stop beyond latest lower pivot, a documented structural fallback | B + H, explicitly measured |
| Descending triangle | Lower flat, upper falling, converging; preceding downtrend | Close below lower; stop beyond latest upper pivot, structural fallback | 3R local fallback |
| Bull rectangle | Both flat and parallel; preceding uptrend | Green close above upper, then the next candle must open above B and finish green above B; entry at that following close; stop below original breakout-candle low | B + H |
| Bear rectangle | Both flat and parallel; preceding downtrend | Red close below lower, then the next candle must open below B and finish red below B; entry at that following close; stop above rectangle resistance | B - H |
| Bull flag | Upward pole >=3 ATR over 3–15 bars; downward parallel channel 4–20 bars; retrace <=50% pole | Close above flag resistance; stop below flag low | 3R local fallback |
| Bear flag | Downward pole, upward parallel correction with the same bounds | Red close below flag support; following candle must open below B and finish red below B; entry at following close; stop above flag high | 3R local fallback |
| Falling wedge | Both lines fall, upper faster, converging; preceding downtrend | Close above upper; stop below latest lower pivot | 3R local fallback |
| Rising wedge | Both lines rise, lower faster, converging; preceding uptrend | Close below lower; stop above latest upper pivot | 3R local fallback |
| Double bottom / top | L-H-L / H-L-H; equal extremes within tolerance; middle rebound >=1 ATR; 3–80 bars between extrema | Break middle neckline; stop beyond second extreme | Nearest confirmed profitable S/R if available, otherwise 3R |
| Triple bottom / top | L-H-L-H-L / inverse; all three outer extremes within tolerance; each rebound >=1 ATR; 3–80 bar separation | Bottom neckline is higher of intervening highs; top neckline is lower of intervening lows. Stop beyond final extreme, explicitly a conservative local anchor | 3R local fallback |
| Inverse / head-and-shoulders | L-H-L-H-L / inverse. Head beyond both shoulders by >=0.5 ATR; shoulders within 0.5 ATR. Preceding opposite trend | Break projected line through two intervening pivots after right shoulder is known; stop beyond right shoulder | 3R local fallback |
| Cup and handle | Prior uptrend; cup 40–150 bars, handle 3–20 bars; rim difference <=0.5 ATR; depth >=2 ATR and <=30% rim price; handle depth <=1/3 cup depth and confined to upper third | Close above higher rim/handle resistance; stop below handle low | 3R local fallback |

For the cup's rounded-U test, divide the cup into seven equal time buckets and average five-bar-smoothed closes in each. The first three bucket means must descend and the last three ascend; the middle bucket must be the minimum. At least three distinct bars must lie within the bottom 15% of cup depth. These explicit local conditions reject a sharp V. For flags, require the corrective channel widths to satisfy the common parallel test and both boundary slopes to oppose the pole; a flat correction belongs to the rectangle detector. The flag-specific 4–20-bar channel window overrides the common 12–180-bar shape span; confirmed pivot/contact requirements still apply, so the shortest channels may not contain enough usable contacts at the selected pivot length.

### Candlestick contract

All formations use real bodies for containment/engulfing; full-range engulfing can be an optional stricter filter, off by default. Long bodies meet the common 60% range threshold and are at least the preceding 14-bar average body. Small bodies are <=30% of range and smaller than the relevant impulse body's size. Patterns require their stated prior trend; filter equality and missing warm-up do not pass.

Default directional candle confirmation is a later green close >= pattern trigger high + one tick for Long, or a later red close <= pattern trigger low - one tick for Short, within three candles. This later-close policy is a conservative local execution convention. Specific exceptions below take precedence.

| Pattern | Geometry / direction | Trigger anchor and stop anchor |
|---|---|---|
| Rising / falling three methods | Directional long candle, three smaller countertrend candles whose complete high/low ranges lie inside the first candle's range, fifth directional close beyond all three corrective highs/lows and beyond first close | Fifth high/low trigger; stop beyond min/max of three corrective candles. Check this stop for invalidation from the fifth candle onward, after its corrective anchors exist; the earlier impulse wick cannot invalidate it retrospectively |
| Tweezer bottom / top | Red-green with matched lows / green-red with matched highs | Second high/low; stop beyond matched extremes |
| Three white soldiers / black crows | Three same-direction long bodies, progressing closes, each later open inside preceding body, terminal-direction wick <=10% range | Third high/low; stop beyond first candle low/high |
| Bull / bear harami | Large first directional body; smaller opposite body contained inside it | Bull: later green close above second high; stop below second low. Bear: later red close below second low; stop above first high |
| Piercing line / dark cloud cover | Opposite second candle closes beyond first body midpoint but does not fully engulf first body | Second high/low; stop beyond complete two-candle low/high |
| Morning / evening star | First long directional candle, small middle body, opposite third close beyond first midpoint | Third high/low; stop beyond formation extreme |
| Bull / bear engulfing | Opposite second real body contains first body; at least one boundary extends strictly; preceding opposite trend | Second high/low; stop beyond second low/high; prior first extreme is not substituted silently |
| Hammer / hanging man | Small upper body, lower wick >=2 bodies, upper wick <=10% range; prior down/uptrend | Hammer: high trigger, stop below latest confirmed swing low or pattern low if lower. Hanging man: low trigger, stop above pattern high |
| Inverted hammer / shooting star | Small lower body, upper wick >=2 bodies, lower wick <=10%; prior down/uptrend | Inverted hammer exception: very next candle opens above pattern body top and closes green above that body top; stop below pattern low. Shooting star: low trigger, stop above pattern high |
| Bull / bear marubozu | Body >=90% range, each wick <=5%; appropriate directional context | Observation initially; proposed local later-close breakout trigger uses its high/low and opposite extreme stop |
| Doji variants, double doji, spinning top | Doji <=10% body; spinning top <=30% body with both wicks >=30%. Dragonfly upper wick <=10%; gravestone lower <=10%; long-legged both >=30%. Double doji is two adjacent dojis | Neutral observation initially. Proposed local breakout confirmation uses the complete formation high/low, stop beyond its opposite extreme; require directional context before plan qualification |

Default gap policy is **Explicit comparisons**, with a separate **Continuous-market local variant**:

- Piercing line: second open < first close. Dark cloud cover: second open > first close. This uses previous-close gaps, not complete high/low non-overlap.
- Morning star: middle body entirely below first close and third open above middle body top. Evening star: middle body entirely above first close and third open below middle body bottom. These precise star comparisons resolve illustrated-gap ambiguity as local choices.
- Engulfing does not require a gap between the two engulfing bodies. In Explicit comparisons mode, its confirming candle must also open beyond the second candle's close in the expected direction. This interprets the described following-day gap as a local confirmation rule.
- Other patterns have no additional gap prerequisite. Continuous-market mode removes the above gap prerequisites but preserves every body, trend and later-close requirement; show the variant in the guide.

### Support/resistance, trendlines and breakout types

Build horizontal levels from confirmed pivots in the previous 200 bars. Cluster same-side pivot prices within tolerance, require at least two touches separated by three bars, and use the median member price. Each changed cluster is a new version with a new recognition time; freeze the version used by an event.

Photo 49 template: a green close one tick above resistance arms Long; only the very next observed candle can confirm with a green close one tick above that breakout candle's high. Stop is below the original breakout candle's low. The Short mirror requires red candles and low-side closes. The closed later candle is the entry reference, so no intrabar boundary fill is assumed.

Trendline break/retest uses the most recent two same-side confirmed pivots, with at least three bars between them. After a close one tick through the line, freeze it. On a later bar within ten candles, a retest requires its range to intersect line +/- tolerance and a directional candle to close at least one tick back on the breakout side. Stop is beyond that retest candle's opposite extreme. Do not create a plan if the buffered stop has already been breached during confirmation.

A direct/strong breakout is the confirmed breakout observation; its volume expansion is evidence, not proof it will not retest. Returning by a completed close to the old range within three bars marks failed breakout. Breakout/retest and failed-breakout annotations refer to their original event and do not rewrite it.

Where a support/resistance target is selected, use the nearest already confirmed level on the profitable side of entry at qualification time. If absent, use the explicitly labelled 3R fallback. Measured targets project H from B, not from the later entry close. Round targets toward entry and stops away from entry to the instrument tick. R-derived 3R passing a 3R filter is a planning constraint, not separate market evidence; display that distinction.

### Trend and optional filters

Capture preceding context on the bar immediately before formation start. Bull = EMA20 > EMA50 and EMA20 > its value five bars earlier; Bear is the strict mirror. Equal/contradictory comparisons are neutral; fewer than 55 valid prior bars is unavailable. The selected SMA variant replaces both averages consistently. Reversal formations require the opposite prior context plus their own price trigger; they need not wait for a slow MA cross after formation. Continuations require their directional prior context and a confirming close on the appropriate side of current MA20. Neutral formations can qualify a local breakout plan only with current Bull/Bear context in that direction.

Optional RSI filter: Long requires RSI14 >50; Short requires RSI14 <50. Optional MACD filter: Long requires MACD12/26 > its EMA9 signal; Short requires MACD below signal. These are separate toggles; require both only when both are enabled. Each enabled input must be finite. The optional volume filter requires positive confirmation volume >=1.2 times preceding SMA20 volume. Filters default off; show their values and pass/fail/unavailable states. MA crosses, price/MA crosses, MACD signal/zero crosses, RSI30/70 recrosses and confirmed divergence are context observations. They cannot initiate a plan without a price-pattern trigger.

### Single-plan lifecycle

- Pattern recognition, trigger arming, qualification and plan activation have separate IDs/timestamps. A failed/expired pending candidate does not prevent that same completed candle from starting a new pattern.
- Process a new completed candle once: update older plan reference touches; expire old candidates; evaluate candidates whose geometry was already known; detect fresh formations; publish observations and a newly selected plan. Fresh candle formations cannot use their own formation candle as a later confirming candle.
- A qualified plan is selected only from fresh candidates on that candle, after context/filter/risk checks. Eligible candidates on both sides yield WAIT. Same-direction ties use a fixed rank: support/resistance next-candle trigger; trendline retest; chart-shape breakout; candle formation trigger; neutral/local trigger. Then use more confirmed geometry contacts, newest formation end, and lexical pattern ID. This order is independent of array iteration.
- Once active, keep the plan until SL touch, target touch, or 50 completed candles, whichever occurs first. Fifty is a configurable local expiry. If both references touch on one candle, terminate with ambiguous order of touches. These statuses describe price references, not actual fills or P&L.
- Later qualified evidence does not replace the active plan. Show it as an alternative; opposite evidence adds a review warning. There is no automatic position exit or entry action. On termination, select only newly qualified candidates from that current candle; never resurrect an old missed entry automatically.
- Forming updates show provisional distance/progress only. Confirmed touch alerts occur at candle close. Deduplication key includes symbol, interval, event/plan ID, event type and confirmation time so entry and later touch alerts remain distinct.
- Recompute historical observations deterministically on feed correction or identity change, with no historical alert replay. Suppress new live alerts when disconnected, on unsupported synthetic chart types, or with a live quote older than 15 seconds while the market is open. After market close, label results as last-session references; lack of a new quote then is not a failed pattern.

### Risk units

Size is underlying quantity units; show lots separately. With user-entered equity E, risk fraction f, fixed round-trip cost F, price distance D, monetary value per price unit V, required currency conversion X, per-unit cost C and per-unit slippage price S:

`budget = E*f - F`

`loss_per_unit = (D + S)*V*X + C`

`quantity = floor(budget / (loss_per_unit * quantity_step)) * quantity_step`

Require positive finite budget/distance/unit value/conversion/step and at least one complete step. Apply a lot/contract multiplier exactly once, using an explicit product unit definition. Unsupported inverse/nonlinear products retain price levels but have no monetary sizing. Show that affordability/margin and existing portfolio exposure have not been established. Missing equity or conversion does not fabricate a size or suppress valid pattern geometry.

## User-directed chart clarity refinement — 5 November, 22:04 onward

Finish visual correction of this study before the separate 51-strategy extension. The compact guide is the default on both platforms; full explanation and settings remain available through Details / Full guide. Include the actual current trend in the existing compact rows.

Own drawings must use the same UTC and price scale as the candles. Caption leaders are dotted; structural formation/trend strokes stay visually distinct. A candle caption connects to its actual formation high/low point, and is placed outside the complete formation envelope with bounded outward collision spacing. An appended confirmation point must not accidentally become the source candle anchor. Count caption leaders in the existing owned drawing budgets.

Draw current confirmed structural trend context independently of breakout events: at most one rising support line and one falling resistance line from the most recent two usable confirmed pivots of each side, preserving the causal 3-left/3-right recognition and minimum pivot spacing. Project only through the latest received chart candle, never into the future. Label these lines explicitly as context; they do not create a pattern confirmation, plan, alert or order. Offer an independent Show trend lines setting, on by default, and reserve their bounded line/label capacity before ordinary formation drawings. Existing latest-ten/pending/neutral/history policies continue to govern pattern annotations. All old indicator files, settings and selected study IDs remain protected.

Native5m readability correction: keep every retained formation's full main caption and geometry. Use exact-coordinate source markers instead of repetitive generic high/low/confirmation words. Lay out main captions against full occupied text rectangles across bounded available space, outside their formation envelope and with dotted leaders to the unchanged source candle point. This is a display correction only; it does not change detection, latest-ten visibility, plan selection, old study selections or settings.
