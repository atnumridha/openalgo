# Video strategy guide for OpenAlgo and OpenAlgoAll

Status: execution authorised on 5 November with source-only scope clarification below.
Date: 4 November 2026 (IST).

## User intent and existing choices

The user asks to implement every strategy named in the supplied video on the chart so he can see which setup fits and what action to consider. The previous request explicitly applied chart changes to both local OpenAlgo and the TradingView OpenAlgoAll indicator. Previously approved choices remain: guidance only, a compact collapsible guide, readable labels, only the last ten chart candles' pattern annotations by default, older history opt-in, unconfirmed/pending drawings hidden by default. The existing TradingView Gautam Jha module remains enabled and independently evaluated. This request does not silently add a separate GJ execution engine to OpenAlgo. These new concepts must not alter Auto order eligibility or submit/modify/cancel orders.

## Evidence and limits

The provided local MP4 is 300.163 seconds, 720 × 1280, with video and audio tracks. Sampled the entire visual track at about three-second intervals (100 frames) and reviewed all frames as timestamped contact sheets. Captions and diagrams are readable. The local ffmpeg/ffprobe/Whisper tools are absent; macOS AVFoundation decoded the frames outside the sandbox after sandbox decoding failed. Speech authorization was unavailable, so audio was not independently transcribed. This design is based on the visible examples and captions, not assumed spoken content. Frames remain temporary; no source media is uploaded or added to the repository.

The opening overview names fifteen concepts:

| Concept | Coverage in this clip |
|---|---|
| Fair Value Gap (FVG) | Illustrated approximately 00:18–00:49 |
| Order Block (OB) | Illustrated 00:54–01:23 |
| Liquidity Sweep | Illustrated 01:27–01:46 |
| Break of Structure (BOS) | Illustrated 01:51–02:09 |
| Change of Character (CHoCH) | Illustrated 02:18–02:33 |
| Inverse FVG (IFVG) | Illustrated 02:39–03:00 |
| Breaker Block | Illustrated 03:06–03:18 |
| Optimal Trade Entry (OTE) | Illustrated 03:51–04:09 |
| Keepssy Reversal Model (KRM) | Introduction 04:18–05:00; clip ends before its precise trigger is established |
| Silver Bullet | Named in overview; no complete rule explanation |
| Supply / Demand | Named in overview; no complete rule explanation |
| Support / Resistance | Named in overview; no complete rule explanation |
| Breakout | Named in overview; no complete rule explanation |
| Candle Range Theory (CRT) | Named in overview; no complete rule explanation |
| Power of 3 (PO3) | Named in overview; no complete rule explanation |

Several concepts are components of one setup (for example sweep → CHoCH → FVG), not independent evidence that can be multiplied into a confidence score. The video does not establish success rates, profitability, causal institutional order flow or broker fills. No such claims will be displayed.

A public search did not establish the creator's complete KRM trigger. The chart must not fabricate KRM signals from its name or the illustrated reversal alone. KRM appears in the strategy catalogue with **Rules incomplete** and an explanation. Implementing its detector requires the missing exact definition.

## Approaches

The already approved compact chart-guide approach is retained. Add all fifteen names to one guide/catalogue, reuse causal structure and zone primitives, and distinguish clip-derived definitions from explicitly chosen local variants. The main view shows the current evidence and the next condition, with details available on expansion. One selected setup owns its highlighted levels.

Alternatives considered:

1. Draw every concept, candidate and plan on top of price simultaneously. This conflicts with the user's recent request to reduce clutter.
2. Add separate indicators/scripts for each concept. This duplicates state and uses additional TradingView indicator slots; the account already has script/indicator limits.
3. Extend the existing compact guide and combined indicator (selected approach inherited from the earlier approved chart design). This supports all names and explanations while controlling drawings and preserving the user's defaults.

The incomplete video means the additional six named concepts need explicit operational rules. The following are proposed local variants, not a claim to reproduce the creator's unspecified implementations. KRM stays informational until its exact rules are supplied. User approval must include this distinction.

## Shared deterministic rules (proposed builder choices)

- Use verified completed standard OHLC candles only. A forming bar may move price, but cannot confirm a structure break or trigger a new confirmed annotation. Charts use their selected timeframe; Auto's independent 1m/5m system remains separate.
- Pivots: strict two-left/two-right highs and lows. A pivot becomes usable only after the second right bar closes; never backdate knowledge to the pivot bar. An outside bar qualifying as both extrema is ambiguous and excluded from structure sequencing.
- Pivot retention: maintain alternating confirmed extrema. A consecutive same-type pivot replaces the retained one only if more extreme; otherwise ignore it. Replacement affects future decisions only, never historical emitted records. Ambiguous outside extrema are excluded. The retained pivot's usable time is its own confirmation time, not the displaced pivot's time.
- Trend initialisation: the last two retained highs/lows set HH/HL up or LH/LL down; otherwise bias remains unknown. Once initialised, a closing break in the active bias is BOS and a closing break against it is CHoCH. A CHoCH flips the active bias only after that close, effective from the next bar. Do not reinitialise from the older pairs while waiting for new pivots. Each pivot is consumed at its first closing break; additional breaks require a new usable unconsumed pivot. Reset this state at an unscheduled gap/session boundary. Canonical sequence: H110, L100, H108, L98 initialises down; a later close109 breaks the already-known H108 and emits bullish CHoCH; if a new H112 subsequently becomes confirmed, a later close113 emits bullish BOS. Continuing above108 before H112 is usable emits neither a repeated CHoCH nor a new BOS.
- Tick size must be finite and positive for a priced plan. No invented fallback ticks. Price units always match the displayed instrument.
- Displacement, where required: directional candle body >= the prior completed ATR14, and its close lies in the outer quarter of its full range. ATR uses only candles available before that candle. Wait for warm-up if unavailable.
- Equal-level tolerance: max(two minimum ticks, 0.10 × prior completed ATR14). Require distinct confirmed pivots with at least three bar indices between them. Freeze the cluster and opposing trigger before the sweep.
- Search context: latest 300 verified bars. Pending setup expires after 20 further completed bars, a stop/invalidation crossing, a contrary structure break, or a missing/invalid interval; whichever comes first. Never stitch a pattern across an unscheduled gap. Recognize legitimate scheduled session breaks using the existing session helper; intraday zones do not carry over to a new exchange session. Crypto is continuous.
- A geometric observation can be confirmed while its entry condition is still missing. Distinguish **Confirmed observation** from **Entry condition met**. Showing only confirmed patterns does not make every confirmed observation a trade entry.
- Pre-existing opposing confirmed pivot at setup creation is the structural target, chosen as the nearest valid level beyond both the watched entry and the setup-confirmation close. The level must remain unbroken by price after its own pivot confirmation and through setup creation. Freeze that target once: do not substitute a later pivot after a retest or an unfavourable move. If none exists, the current observation is permanently unpriced and says **Target unavailable — wait for a new setup**; a wholly new setup is required, rather than later promotion of the same event. No invented measured target or mandatory 2R fallback. OTE/CRT/PO3 have the explicit leg/range targets below instead of this structural-pivot target selection. For OTE the creation candle defines the leg extreme; that initial defining touch does not cancel its future retest plan. CRT explicitly rejects a third candle that has already touched its opposite-range target. Display numerical reward/risk only for valid plans; no new blocking risk filter is added.
- Long and Short are exact geometric mirrors. A bought option premium decline is “Premium bearish / avoid new buy”, not an instruction to sell naked options. No conversion between index points and premium points.

## Rules and next-action guidance by concept

Zone lifecycle is separate from the original entry-plan lifecycle. A valid FVG/OB can convert once into a new IFVG/breaker when its far edge is crossed by a completed close within 20 bars of zone creation. A mere wick through the original stop can retire the original entry plan without converting its zone; only a closing failure converts. Price-based invalidation retires the old plan but keeps its frozen zone as conversion evidence until the same 20-bar limit. Time expiry, new exchange session, missing/invalid data or unsupported source destroys conversion eligibility. Converted zones cannot be reused or converted recursively; the derived setup gets a new identity and its own 20-bar pending limit. Creating a derived setup never resurrects the original plan.

All prices/anchors are frozen when confirmed. Every recipe includes confirmedAt, the evidence times, current status, missing conditions, invalidation and any valid plan. The eight illustrated recipes use the clip's visible ideas with the numerical shared choices above.

| Concept | Operational observation / confirmation | Guidance and plan |
|---|---|---|
| FVG | Three consecutive completed bars with bullish low[third] > high[first] (bear mirror). Require displacement in the middle candle plus an established same-direction BOS/CHoCH in the previous five bars, including bar three. That structure break is the local definition of “move confirms”. | Watch the gap midpoint for a later pullback. SL one tick beyond the first candle's wick. Target the frozen valid opposing pivot. Unqualified gaps can be listed as observations but have no entry plan. |
| OB | Last opposite-colour candle within three bars before a displacement candle that causes a confirmed BOS/CHoCH; freeze its full wick zone. An immediately resulting FVG is supporting detail, not a required extra vote. | Watch the opposite candle body's midpoint on a subsequent retest. SL one tick beyond its full wick. Target the frozen opposing pivot. A close through the wrong edge invalidates it. |
| Liquidity Sweep | A completed bar strictly crosses the frozen cluster of at least two equal highs/lows and closes back on the original side. A later completed close through the opposing pivot known before the sweep confirms the reversal sequence. | The sweep alone says “Wait for structure confirmation”. After the break, wait for a new same-direction FVG/OB retest; SL beyond the sweep extreme. Do not enter just because stops may have been swept. |
| BOS | First completed close strictly beyond the last unconsumed confirmed pivot in the established structure direction. A wick is insufficient. | Confirm continuation context; wait for retest of the broken level. Use the last confirmed opposite pivot as invalidation/SL plus one tick. A break without retest says “Wait”. |
| CHoCH | First completed close strictly beyond the last confirmed opposing pivot against the established trend. No EMA gate. | Possible change of direction, not an immediate entry. Wait for a subsequently formed FVG/OB in the new direction and a later retest; SL beyond the reversal extreme. |
| IFVG | Previously confirmed FVG closes fully through its far edge; freeze the former gap as an opposite-direction zone. | Wait for retest from the flipped side. SL one tick beyond the flipped zone's opposite edge. Target the frozen valid opposing pivot. Original FVG is retired; no two simultaneous contradictory plans from the same zone. |
| Breaker Block | A confirmed OB fails on a completed close through its far wick edge. Require a prior sweep within five completed bars before that failure, then a same-direction closing structure break. These are local choices resolving the sketch's sequence. | Watch the failed OB for a later retest from the new side. SL beyond its far edge; structural target. Do not relabel every failed candle as a breaker. |
| OTE | After a confirmed BOS/CHoCH displacement leg, freeze its already confirmed origin pivot and break candle extreme. Long retracement zone is 62%–79% of that leg (Short mirror). Do not move anchors as later bars arrive. | Watch 70.5% as the reference entry; SL one tick beyond the origin pivot. Target the frozen leg extreme. Note any independently confirmed FVG overlap as confluence without a probability score. |
| KRM | Clip introduces a proprietary/name-specific reversal but ends without a reproducible trigger. | **Rules incomplete**. Explain what is missing; draw no KRM entry/SL/target and generate no KRM alert. |
| Silver Bullet — local variant | Same verified sweep → structure shift → new FVG sequence, restricted to 10:00–11:00 America/New_York, Monday–Friday, on 1m or 5m candles. Require both the FVG confirmation and subsequent retest in the window. This is the proposed initial window, not an assertion that other published variants do not exist. Use DST-aware IANA time conversion. | Outside window/timeframe: say so. In-window: FVG midpoint, SL beyond sweep, structural target. On market holidays/closed sessions no source candles means unavailable. Do not imply the NY window has the same effectiveness on BTC or NSE as other markets. |
| Supply/Demand — local variant | A one-to-three-candle base before a displacement causing BOS. Select the immediately preceding maximal run of <=3 bars each with body <=0.5 prior ATR14 and total wick range <=1.5 prior ATR14. Demand wick-to-body zone = minimum base low to maximum base body top; supply mirrors. | First subsequent retest, then a completed directional rejection closing beyond the near edge, confirms the entry condition. SL beyond the far edge. Structural target. A close through the far edge retires the zone. |
| Support/Resistance — local variant | Cluster of >=2 already-confirmed pivot highs/lows within the shared tolerance. Same frozen cluster logic as sweeps. | A touch alone says “Watch”. Directional completed rejection back outside the zone identifies a bounce; SL beyond both the rejecting wick and zone far edge. A closing break waits for a flip retest instead of recommending a bounce. |
| Breakout — local variant | Prior 12-bar range with >=2 distinct confirmed touches on each side within tolerance and height <=4 prior ATR14. First completed close at least one tick outside freezes the breakout. | Wait for a later retest of the broken edge and a directional closing rejection. SL beyond the retest wick; structural target. A close back inside the old range retires the plan as failed breakout. |
| CRT — local variant | Rolling three completed candles on the displayed timeframe: candle 1 defines range; candle 2 strictly sweeps only one edge and closes back inside; candle 3 closes beyond candle 2's opposite extreme while still inside candle 1's opposite edge. Reject two-sided sweeps. | Long/Short reference is candle 3 close, SL beyond the swept extreme, target candle 1's opposite edge. If the target was already touched before confirmation, no entry plan. No fixed HTF/session promise is inferred from the overview. |
| Power of 3 — local variant | Last six completed bars form an accumulation range <=2 prior ATR14. Then one completed bar sweeps only one edge and closes back inside; within the next three bars a displacement close breaks the opposite range edge. Once confirmed, retire/reseed the old range. | Before break: “Wait for distribution confirmation”. After break: watch the broken edge for a retest; SL beyond manipulation wick. Target one frozen accumulation-range height beyond the broken edge. Label it “PO3 · rolling-range variant”; not a claim to infer institutions or reproduce a daily/4H PO3 model. |

## Setup lifecycle and meaning of an action

1. **Watching**: prerequisites/geometry partly present. Unconfirmed chart drawings remain hidden by default, but the guide may state the missing condition.
2. **Confirmed observation / waiting for retest**: all causal observation rules hold, a priced reference may be available, but no entry claim is made yet.
3. **Entry condition met**: a later completed candle touches the reference price/zone and closes in the intended direction on the valid side. This is a reference for review after that close, not a retroactive limit fill. For midpoint recipes, the candle must actually reach the midpoint. Entry marker/reference uses the observed rejection close; show the watched midpoint separately. SL/target geometry must remain valid at that close. For CRT only, the third close is its reference immediately after confirmation.
4. **Invalidated / target reached / expired**: terminal states. Do not fall back to an old candidate as if it were fresh. Cancellation monitoring starts strictly after setup creation, using only subsequent bars. Touching the invalidation or target on a subsequent bar before entry confirmation cancels the plan. The setup-creation candle itself is checked for valid geometry and the recipe-specific already-touched target rules, not replayed as a later exit. The entry-confirmation bar is also checked for stop/target ambiguity. If entry, SL or target ordering within one OHLC bar cannot be determined, mark ambiguous and withhold an entry condition.
5. **Unavailable**: insufficient history, stale/unverified source, unsupported chart type or missing tick metadata. Display the reason.
6. **Rules incomplete**: a named method lacks enough source rules (KRM).

This conservative after-close guidance is deliberate. The video often illustrates limit entries; OHLC cannot prove those historical fills. No broker order is created. The guide never promises that taking a trade is correct or that a setup will profit.

## Display in OpenAlgo

- Add a **Strategy guide** section within the existing chart details area, on by default and collapsible. Keep the current Trade guide (including broker position/protection) independent; do not replace a live trade's protection display with a new research plan.
- A compact default view names the nearest relevant confirmed setup, direction, **Wait / Review Long / Review Short / Invalidated / Unavailable**, its source timeframe, and one short reason/next condition. “Review Long/Short” appears only for a current latest-completed-bar entry condition and valid prices. Older conditions are labelled history, not fresh actions.
- Expanded view lists all 15 named concepts with statuses, unmet conditions, evidence times, and “Clip-derived” or “Local variant”. KRM is plainly incomplete. Different names on the same event are grouped; no duplicated independent-confidence score.
- “Show setup on chart” selects one plan, highlighting its zone, watched entry, SL, target and causal anchors. The current confirmed broker position overlays remain separate and take precedence in the existing Trade guide. Selected guidance is scoped to current symbol/exchange/timeframe.
- Default selection: retain the user's selected currently valid concept; otherwise current valid confirmed Gautam Jha where that module is already available, then newest confirmed entry condition, then newest confirmed observation waiting for a retest. Tie-break by stable catalogue order. Conflicting current Long/Short conditions show **Mixed evidence — wait**, with both available in details. Recency/tie-break order is not a profitability rank. No unrelated nearest-price substitution.
- Reuse current semantic colours and readable font controls; statuses include words, not colour alone. No chart-wide redraw on every millisecond timer. Recompute at verified candle boundaries and use the existing live repaint for price only.

## Display in TradingView OpenAlgoAll

- Extend the existing combined source, not separate scripts. Add a compact strategy-status table, on by default. Full catalogue can be enabled in Inputs; disabled concepts remain visible in catalogue as disabled.
- One selected/automatically chosen valid plan owns new guide drawings. Latest confirmed levels can remain visible after their event falls outside the annotation window, clearly marked historical/last until invalidated.
- Preserve last-ten-chart-candle annotations and existing all-history/pending toggles. A pending setup may be explained as waiting in the status table; its on-chart candidate geometry stays hidden by default.
- Preserve existing EMA, Fib, RSI/MACD, volume and Gautam Jha studies/settings. Keep total Pine plots, request calls and drawings within the plan limits; bounded state and one pass over historical bars. The account's existing saved-script limit remains a deployment limitation: no deleting saved scripts, upgrading, or claiming unsaved code is cloud-saved.
- OpenAlgo and Pine implementations use the same deterministic fixtures and equations. Same OHLC/metadata should produce the same timestamps/states/plans. Different market feeds do not imply matching raw prices.

## Architecture / existing coverage

The live OpenAlgo service uses `/Users/nmandal/.codex/worktrees/neo-native/openalgo`; the TradingView source is in the primary `/Users/nmandal/Documents/AlgoTrading/openalgo` checkout. Recheck before edits, preserve all unrelated changes, and back up exact current files. The live checkout contains concurrent strategy-configuration work; do not replace whole files from an old copy.

Reusable OpenAlgo parts: verified closed-candle source, session-gap helper, existing FVG geometry, confirmed swing/zone primitives, `patternDisplay` recent bounds, chart layer infrastructure, Trade guide and source strategy configuration. Existing archive sweeps/SR flips are related generic observations but do not establish every recipe above. Avoid duplicate drawings and misleading aliasing. Existing option-spread A-01…A-07 configurations are a separate catalogue and stay intact.

New pure strategy-guide engine returns immutable evidence/status/plan records. Rendering layers consume the records; neither calls broker APIs. The Pine port mirrors this state machine with bounded arrays/types. The builder may choose internal names/module splits and tune rendering layout within the existing design system; changing numerical rules requires updating visible rule descriptions and parity tests.

## Verification and completion

- Long/Short mirrored causal tests for all 14 defined recipes; KRM always incomplete until configured.
- Prefix causality: adding future bars cannot rewrite earlier confirmation timestamps or use pivots before they were known. Adding forming/future bars cannot create a confirmed action.
- Boundary tests: strict vs equal touches, ATR warm-up, tick rounding, stale/unverified history, missing intervals, scheduled exchange gaps, invalid prices, two-sided sweeps, expired/consumed levels, midpoint not reached, target already reached, same-bar order ambiguity and terminal-state stability.
- Session tests: America/New_York DST transitions and Silver Bullet half-open window 10:00 inclusive to 11:00 exclusive, weekdays and unsupported intervals.
- Same explicit OHLC fixtures in JS/TS and actual Pine runtime: compare observation time, direction, status, entry reference, stop, target and reasons by stable identifiers. Do not claim parity from copied test implementations.
- UI tests: all names/states, missing-rule explanation, scope reset, latest-only action freshness, mixed-direction wait, one selected plan, keyboard labels, no broker calls and existing ten-candle defaults.
- Build active OpenAlgo frontend; verify live chart controls/drawings without trading actions. Compile updated Pine and inspect 1m/5m/1H standard candles; test mode/selection toggles and no runtime limit error on representative loaded history.
- Report what is implemented vs incomplete, local and live checks, data/source limitations and cloud-save outcome. Do not invent performance statistics or assert trading losses are prevented.

## Approval needed

Approve extending the already chosen compact guide in **both charts**, using the eight clip-derived and six explicitly labelled local variants above, with KRM visible as **Rules incomplete** until its full trigger is available. The incomplete source is the material scope decision; no KRM buy/sell detector should be guessed.

## Builder check

A fresh software-engineer review identified four planning ambiguities. Resolved as builder choices above: explicit pivot replacement/CHoCH bias transitions; target monitoring strictly after creation with OTE's defining extreme exempted; separate zone-conversion evidence from terminal original entry plans; permanently unpriced observations require a new setup instead of inventing a later target. The user-facing decision remains the source-coverage choice in Approval needed. No product code has been changed for this request.

## 5 November scope clarification — “all from the video”

Implement the user-selected all-video catalogue in both charts. The user's reply does not explicitly approve invented substitutes for the named-only methods. Therefore the six previously proposed local-variant rows are retained above as design history but **are not enabled detectors in this delivery**. Along with KRM, they display source-incomplete status and the specific missing definitions. The eight illustrated concepts use their reviewed deterministic implementations, with numerical pivot/displacement choices disclosed as implementation settings. If the creator's complete original explanation can be verified during the source check, add its exact rules and source attribution rather than the unapproved substitutes. This ruling is communicated before implementation and preserves guidance-only scope. No further procedural approval is requested.
