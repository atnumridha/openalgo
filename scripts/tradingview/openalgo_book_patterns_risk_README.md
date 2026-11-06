# OpenAlgo Book Patterns & Risk

A **new, standalone Pine v6 indicator** for the reviewed Book Pattern Guide rules. It draws its own formation outlines, structural geometry, guide and one frozen Entry/SL/Target reference plan. It contains no strategy orders, broker actions, fills or profitability estimates. The existing combined indicator and the saved OpenAlgoAll study are separate and unchanged.

Add `openalgo_book_patterns_risk.pine` as a **new** indicator. Do not paste it over an existing script. Its guide defaults to **top center**, leaving the existing top-right, bottom-right and bottom-left guides available. The independent Guide position setting offers all nine table positions.

## Defaults and chart behavior

- Standard OHLC candles only. Forming updates show provisional distances; they cannot confirm a pattern, advance a pivot, touch a reference, or age a plan.
- Confirmed annotations on the latest **10 actual chart candles**, counting the current forming candle. Pending geometry, neutral/local observations, and retained full history are independent opt-ins. Full history is bounded, not unlimited.
- Strict 3-left/3-right pivots with three-bar spacing. Recognition time is distinct from the earlier pivot time. An anchor recognized on the breakout candle cannot authorize that same candle retrospectively.
- Prior trend: SMA-seeded EMA20/EMA50, with five-bar fast-average slope and 55 valid bars of warm-up. SMA is optional. ATR14 and RSI14 use Wilder smoothing. MACD12/26 uses SMA-seeded EMAs and a nine-period EMA signal. Invalid OHLC resets indicator warm-up.
- New formation scale is the **preceding completed candle's ATR**, frozen with its event. Stop buffer is max(one tick, 0.05 frozen ATR), rounded outward. Targets round toward entry. A full tick beyond a boundary is required; mere equality is insufficient.
- Risk equity defaults to **0/unset**, risk to **0.25%**, local target/fallback to **3R**, minimum RR to **3R**, and expiry to **50 completed candles**. These settings are independent of the other indicators or any account.
- The guide names up to four relevant qualified alternatives with their Long/Short direction, captured prior trend and actual reason; it preserves both sides of a conflict and counts additional evidence. The selected plan retains its own prior context, and a broader-current-MA conflict is explicit. Period/slope/buffer descriptions use the configured values.
- Once selected, the plan remains frozen until an inclusive stop touch, inclusive target touch, simultaneous/ambiguous touch, or expiry. Later evidence remains an alternative; opposite qualified evidence produces a review warning. Old missed entries are never resurrected after termination.
- Opposing fresh qualified sides give WAIT. Same-side selection uses source rank, more contacts, newest formation end, then lexical pattern ID. Rank order: S/R next-candle trigger, trendline retest, chart shape, candle formation, neutral/local trigger.

All body thresholds, indicator periods, geometry tolerances, pole/cup/handle windows, trigger/retest/failure windows, volume expansion and stop-buffer rules are editable under **Advanced local numerical rules**. All inputs use `display.none`: they remain in Settings without filling the chart title with parameter values.

## Pattern and source semantics

| Family | Confirmation and source distinctions |
| --- | --- |
| Symmetrical, ascending and descending triangles | Known alternating contacts, valid fitted boundaries, strict convergence below75% width. Symmetrical permits either direction; ascending uses B+H measured target. Descending uses labelled R planning target. |
| Bull and bear rectangles | Flat parallel boundaries. Directional breakout arms, then only the next candle may open and close directionally beyond the frozen boundary. Bull stop is original breakout low; bear stop is rectangle resistance. Measured target projects H from B, never the later entry. |
| Bull and bear flags | Opposing parallel corrective channel, ≥3ATR pole over3–15 bars, correction4–20 bars and ≤50% retracement by default. The received correction is revalidated, including complete-channel stop extremes. Bull confirms a boundary close; bear requires the next candle's open/close. A last-window breakout may still get that next-candle confirmation. |
| Falling and rising wedges | Both boundaries slope in the same direction and converge; prior opposite trend; latest opposite structural swing stop. |
| Double/triple tops and bottoms | Separate alternating three/five-swing structures, equal outer levels and ≥1ATR rebounds. Triple bottom uses the higher intervening neckline; triple top the lower. Double uses nearest already-confirmed profitable S/R, otherwise labelled R fallback. |
| Head and shoulders / inverse | Head beyond both shoulders, shoulder tolerance and a projected two-anchor neckline; right-shoulder stop, prior reversal context. |
| Cup and handle | Rounded U uses seven buckets of five-bar-smoothed closes, with three bars near the base; sharp V fails. Default cup40–150 bars, handle3–20, rims within0.5ATR, depth≥2ATR and≤30% rim; handle stays in upper third. Every received pre-break handle candle updates resistance and low, even before a new wick becomes a recognized pivot. The original confirmed anchors remain causal. |
| Rising/falling three methods | Long impulse, three smaller complete-range-contained countertrend candles, fifth continuation close. Stop uses corrective extremes and is checked from the fifth candle onward. The earlier impulse wick cannot invalidate it retrospectively. |
| Tweezers, soldiers/crows | Matched extremes, or three long directional bodies with progressing closes, opens inside prior bodies and small terminal wicks. Source extreme stops. |
| Harami | Smaller contained opposite second body; no invented30% range condition. Bull stop uses second low; bear uses first high. |
| Piercing/dark cloud and morning/evening star | Source midpoint/body relationships. Explicit mode uses previous-close gaps for piercing/cloud and precise middle-body/third-open comparisons for stars. |
| Engulfing | Real body containment with at least one strict edge; optional stricter full-range test. Stop is second-candle extreme. Explicit mode additionally requires confirming open beyond second close. |
| Hammer/hanging man and inverted hammer/shooting star | Dominant wick/small-body morphology and preceding reversal context. Hammer uses latest confirmed swing low or lower pattern low. Inverted hammer uniquely needs the very next open and green close above body top; clearing the upper wick is unnecessary. |
| Marubozu, doji variants, double doji and spinning top | Initially neutral/local observations; later directional outside close plus current directional context for a plan. Neutral/local displays default off. |
| Horizontal support/resistance | Median same-side confirmed-pivot clusters within tolerance and spacing. Photo49 breakout requires the very next directional close beyond the original breakout candle's extreme; original candle opposite-extreme stop. |
| Trendline break/retest | Latest two suitable same-side pivots; line freezes at break. Later range intersection plus directional rejection close within10 bars; stop beyond retest candle's opposite extreme. |

MA/price-MA crosses, MACD signal/zero crosses, RSI recrosses, same-price-pivot RSI/MACD divergence, gaps, direct breakouts, later retests and failed-breakout warnings are context observations. They cannot independently start a plan. Divergence uses the oscillator at each actual price pivot and is published at the second pivot's recognition time. Break/retest/failure observations keep their parent event ID.

**Local conventions are labelled.** The photographs do not define every numerical detector rule, tick buffer, gap interpretation, closed-candle entry convention or R target. Continuous-market mode relaxes only the explicit gap comparisons. A3R planning target passing a3R minimum is not independent market evidence; structural targets are never stretched to pass the minimum.

## Monetary sizing and symbol provenance

Sizing requires an explicitly verified exact `exchange:ticker` ID matching `syminfo.tickerid`, matching actual quote currency, a linear product definition, account currency, positive unit value, quantity step and required FX conversion. Changing the chart symbol invalidates previously entered instrument units. An index remains unsupported even when its ticker matches. `option-premium` additionally requires actual chart metadata `syminfo.type == "option"`; a checkbox alone cannot establish premium provenance. Missing or unsupported data retains price geometry and explains why monetary sizing is unavailable.

Value per price unit is **already per selected underlying/contract/premium unit**. Lot size is presentation only; it is never multiplied into monetary risk again.

```text
budget = equity * riskPercent / 100 - fixedRoundTripCost
lossPerUnit = (abs(entry - stop) + slippagePrice) * unitValue * FX + perUnitCost
quantity = floor(budget / (lossPerUnit * quantityStep)) * quantityStep
lots = quantity / lotSize
```

At least one complete quantity step is required. Affordability, margin and existing portfolio exposure have not been established. Sizing values are planning estimates, not account balances, orders or fills.

## Core API and bounded execution

The production core is literally between `// BOOK ENGINE START` and `// BOOK ENGINE END`. Tests extract and execute this code.

- `BKSettings`, `BKBar`, `BKPivot`, `BKPoint`, `BKSegment`, `BKEvent`, `BKObservation`, `BKLevel`, `BKPlan`, `BKUnits`, `BKState` hold independent typed state.
- `bk_state()` creates state; `bk_step(...)` accepts one actual observed candle, actual close time, confirmation/readiness/live flags, current observation clock and symbol identity. All times passed to the core are UTC seconds.
- `bk_candles`, `bk_shapes`, `bk_revalidate`, `bk_levels`, `bk_levelBreaks` expose the actual production detectors. Optional `bk_shapes(..., family, direction)` selects a single family/side for pending revalidation; the default still detects every family. `bk_evaluate`, `bk_qualify`, `bk_choose`, `bk_advancePlan`, `bk_size` expose actual causal transitions/risk.
- `bk_observe` maintains an observed delivery barrier even on unchanged/forming updates. `bk_unitScope` enforces native ticker and chart-price provenance. `bk_visible` returns complete formations within the actual-chart-index lookback and available drawing budget.

The adapter processes each completed chart index once. It retains640 raw/snapshot candles, at most600 event records,600 context observations, a bounded structural-event identity cache, and the still-needed pending/active state. Seeded EMA/Wilder/MACD values carry forward; pruning never reseeds them. Pivots retain the600-bar relevant window plus predecessor anchors. Active plan references remain separately owned even when their formation leaves the display window. Breakout follow-up parents have a separate age-bounded collection: failed/retest observation windows remain live through their inclusive configured final candle even if dense candle history evicts the display event. A parent is discarded only after both observations are consumed or their respective windows expire.

Shape detection traverses only its latest five eligible pivots; divergence and trendline checks consume the latest two pivots on each side, preserving chronological order and recognition eligibility. Level clustering retains contact extrema, making the all-contact tolerance check constant work while preserving the original median and spacing rules. Pending revalidation constructs only its requested family/side using the frozen scale and current received prefix; cup/flag revalidation, all fresh families and all numerical defaults remain enabled.

Native controls have explicit practical bounds: shape/cup/divergence windows≤500; handle/flag/pole windows≤100; multi-swing outer separation≤250; levels/trend warm-up≤600; indicator/body-average periods≤200; MA slope≤100; pivots2–10; displayed history≤600 candles. OpenAlgo's TypeScript settings permit broader numerical inputs; those broader values are not promised by this native bounded adapter. The maximum500-bar cup plus100-bar handle is tested across the640-bar buffer with its preceding trend preserved.

At most40 complete formations,120 lines and160 labels are admitted, reserving three lines and three labels for the selected plan. Numerical line/label budgets have a native minimum of three. No polylines or boxes are used; candle outlines consume four owned lines each. When a complete formation cannot fit it is omitted as a unit. Only handles created by this indicator are deleted. Last-bar rendering rebuilds this owned worklist, so a forming candle also ages out the oldest latest-ten annotation without advancing engine state.

## Alerts, rollback and native limits

Create a TradingView alert for **Any alert() function call** on this new indicator. It emits one closed-bar message containing fresh confirmed-pattern, selected-plan and reference-touch IDs. Initial history, corrections/settings/symbol recalculation, unavailable updates, late catch-up and first resumed delivery cannot replay historical entries. An alert close must be observed, strictly later than the delivery barrier and no more than the configured freshness window old.

Ordinary Pine `var` state follows realtime rollback. `varip` is used **only** for delivery provenance (`deliveryBarrier`, last received tick and readiness), never for detector/pivot/plan progress. Pine supplies actual `time_close`; wall-clock passage alone cannot advance a cached forming candle. Native Pine does not expose the OpenAlgo connector's connection/calendar/quote metadata. This adapter therefore uses actual realtime arrivals, chart usability and a conservative received-tick interruption barrier; it does not invent connection status or exchange-calendar data. Historical/closed-market displays explicitly say last-session/historical references.

A first native compiler attempt rejected the nonliteral UDT default `1 / 3` (CE10134); the reviewed round1 revision uses the numerically equivalent literal `0.3333333333333333` and checks all UDT defaults. The controller subsequently observed native compilation and rendered guide/patterns/Short references on round1. TradingView then warned that the script was close to the Basic plan total-runtime limit. Round2 reduces measured repeated pivot traversal, cluster contact scans and unrelated pending-family construction. Emulator work counts and timings demonstrate reduced work; a new native run must establish whether the warning is resolved.

Native compilation, rollback, actual alert-server behavior, rendering/coexistence and runtime limits require a separate TradingView acceptance check. **PineTS passing is not native acceptance.** Official references: [execution model](https://www.tradingview.com/pine-script-docs/language/execution-model/), [bar states](https://www.tradingview.com/pine-script-docs/concepts/bar-states/), [limits](https://www.tradingview.com/pine-script-docs/writing/limitations/), [input display](https://www.tradingview.com/pine-script-docs/concepts/inputs/). Native limits include a500ms loop limit per bar and total dataset limits depending on plan; the local3000-bar emulator measurement does not establish a native timing guarantee.

## Verification command

No dependency installation or package change is required in the supplied workspace:

```sh
PATH=/Users/nmandal/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH \
PINETS_MODULE=/private/tmp/tv-combined-validation/node_modules/pinets \
node --test scripts/tradingview/tests/book_patterns_risk.test.cjs
```

The suite bundles the **actual reviewed TypeScript modules** with existing Rolldown at `/Users/nmandal/.codex/worktrees/neo-native/openalgo/frontend/node_modules/rolldown/dist/index.mjs`. `BOOK_REFERENCE` can point to another reviewed module directory; `PINETS_MODULE` can point to the existing PineTS installation. The fixtures are synthetic numerical examples, not evidence of profitability.

Coverage includes every candle family and valid-OHLC near-miss, all shape families, strict causal pivots, complete geometry/timing, source exceptions, gap variants, qualification/selection, every-prefix TS comparison, reviewed cup/flag/reconnect regressions, monetary units, forming behavior, maximum-window pruning, complete drawing budgets, and full-script PineTS parsing. The dated task report records exact commands, counts, hashes and outstanding native acceptance.


### Compact guide and main-chart anchoring (final refinement)

The guide defaults to five compact rows: strategy/side/status, current trend and next condition, Entry/SL/Target, reward/risk plus sizing, and source status. Enable **Full guide** in this study's Settings for the complete context, alternatives, source/local rules and risk explanations. The independent nine-position **Guide position** selection is preserved. Compact values are limited to 64 characters, with full text on hover; this only changes presentation, never detection or frozen prices. OpenAlgo similarly shows a slim summary and an expandable **Details** control.

Every owned Pine line and label explicitly uses `force_overlay=true` with the original UTC time and price anchors. TradingView documents that forced overlays use the main pane's scale regardless of the script scale: [declaration statement scale behavior](https://www.tradingview.com/pine-script-docs/language/declaration-statements/). No independent left/right scale is assigned. Native chart pinning, zoom and compiler acceptance remain separate checks; no price coordinates are shifted to match pixels.

Dotted leader lines join displaced pattern captions to their actual source candle high/low (or structural source point). OpenAlgo uses exact-coordinate source markers in place of repetitive high/low/confirmation words, and packs full main captions against occupied text rectangles; informative structural roles retain their labels. Pine selects source high/low points by role, excluding appended confirmation points, then places captions outside the whole formation OHLC envelope (the greater of four ticks and 0.25 frozen ATR), with at most eight outward collision-lane shifts, without changing formation geometry, event timing or Entry/SL/Target. These owned leaders count against the line budget and are removed with the whole formation; confirmed trend/formation strokes retain their original style.

**Show confirmed context trend lines** defaults on independently of pending, neutral/local and history display. At most one rising support and one falling resistance are drawn from the latest two causally confirmed pivots per side (default 3-left/3-right). They stop at the actual received candle, use real UTC anchors and are labelled **Support trend · context** / **Resistance trend · context**. Up to two line/label slots are reserved after the active-plan slots. These are contextual structural lines, not additional pattern confirmations, entries or alerts. Disabling the setting does not change detection, selected plans or alert delivery.
