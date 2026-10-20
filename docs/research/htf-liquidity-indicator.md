# Source-guided liquidity and entry plans

`Liquidity Zones · 1H / 4H / 1D` overlays `/trading`. Its stable indicator ID is
`oa-htf-liquidity`. The default **Source-guided** marking method uses fixed
historical wick lines, and adds an explainable entry plan on 1m–5m candles.
The indicator only reads chart data. It submits no entry, stop or exit orders.

## What the supplied sources establish

Reviewed both supplied Hindi transcripts and selected overview/detail frames
from the local Crypto-Gold-Live and MASTER-CLASS-10 videos. These establish
relative price structure and confirmation sequences; they do not supply a
complete mechanical algorithm for selecting every significant turn.

- [Masterclass copy](https://www.youtube.com/watch?v=Hyr3CeJ-sVk):
  1:15:40–1:18:00 shows a low, bounce, sweep and green response, with stop below
  confirmation. 1:41:40–1:43:00 marks selected historical turns across timeframes.
  1:52:20–1:53:10 shows bullish continuation through a pullback low toward an
  untouched previous high. 1:53:20–1:54:00 rejects that continuation if the upper
  target was already taken. 2:03:20–2:04:40 demonstrates its bearish counterpart.
  2:23:20–2:26:20 reiterates green-high / red-low entry breaks.
- [Live Gold walkthrough](https://www.youtube.com/watch?v=0stizzV7D1Y):
  00:05:50 daily and 00:06:40 hourly historical references; 00:07:30–00:07:55
  retains a touched upper line. The retrospective drawing at 01:02–01:04 shows
  entry 4288.36 and SL 4286.36. At 01:12 its target distance is 29.22, implying
  4317.58. These are Gold example prices, not BTC defaults or verified fills.

The lower-timeframe continuation and higher-timeframe event reversal are
separate setups. A V/W turn or a candle colour alone is not an entry. Source
claims about algorithms, institutional participants or inevitable destinations
are not measured facts supplied by this indicator.

## Automatic selection and explicit app rules

The following are engineering choices where the sources leave discretion:

- A strict historical high/low requires two completed candles on each side,
  adjustable from one to six. Equal plateaus are excluded. Confirmation is
  available only after the right candles close. This is an automatic proxy
  for a selected turn, not the presenter's exact discretionary selection.
- Clean display keeps one latest confirmed turn per enabled 1H, 4H and 1D
  timeframe. Selection uses confirmation time and stable ID, not live-price
  distance. An active or last displayed plan pins its reference in that
  timeframe so the entry context stays visible. No ATR bands in source mode.
- Swept references remain visible, labelled Swept. They can remain targets.
  These are potential liquidity references, not measured resting orders.
- Reversal evaluation retains the latest known high and low for each enabled
  timeframe; these opposing references supply its possible targets even when
  the clean display only shows one. A plan's Target line displays the chosen
  opposing price. Multiple simultaneous candidates prefer newest confirmation,
  then stable reference ID. One candidate per reference per loaded history.
- A trader can override one timeframe with **Selected liquidity price**,
  **Selected level side**, **Selected level timeframe** and **Active from**.
  The chosen time is required; the first chart candle at or after that time
  can use it. No signals are backdated to earlier crossings. Zero price uses
  automatic selection. Settings are saved by the existing chart workspace.

## Setup sequence and risk lines

Use **Entry setup** to choose:

1. **Higher-timeframe sweep reversal** (default): known high swept strictly
   above, first completed red candle, subsequent low break for SHORT; known
   low swept strictly below, first completed green candle, subsequent high
   break for LONG. The sweep candle may itself confirm when it closes with
   the required colour. No close beyond the final entry trigger is required.
   No continuation trend filter applies to this setup.
2. **Trend continuation**: directional prior trend, first confirmed pullback,
   rebound, fresh sweep of that pullback boundary, confirmation and subsequent
   high/low break. The prior trend extreme remains the target and must not have
   been touched after forming, including before entry. App trend definition:
   20 candles (configurable 8–100) before the extreme, signed displacement in
   the trade direction and absolute displacement / close travel at least 0.55.
3. **Off**: liquidity only.

Both use the displayed ordinary 1m–5m candles for entries. A coarser chart
shows a request to switch to 1m or 5m; lower-timeframe entries are not invented
from hourly candles. The default first-qualifying-candle choice, 8-candle watch
expiry (from sweep), one candidate per reference and strict entry crossing
are explicit app policies. The sources do not define these universally.

A plan freezes three labelled, right-edge lines:

- **Entry, blue:** confirmation high for LONG, low for SHORT. A later price
  must move strictly through it; equality does not trigger.
- **SL, red:** beyond the extreme from sweep through confirmation, with an
  adjustable buffer, default one broker tick. This is the app's conservative
  implementation of the demonstrated stop area, not a source-defined buffer.
- **Target, green:** nearest opposing known liquidity beyond Entry for reversal;
  the preserved prior trend extreme for continuation. Prices round to valid
  broker ticks. Missing opposing liquidity shows **NO TARGET** and does not
  trigger. There is no invented 1:3 or ATR-based target.

The compact panel reports waiting, watching entry, triggered, expired,
invalidated, SL reached, target reached, target already taken, data gap or
ambiguous. It shows reference price and **gross** price-based reward/risk.
The plan is not fee-adjusted P&L and is not a broker order or guaranteed fill.
Ended plans keep dotted levels marked ended until another candidate appears;
the panel explicitly says LAST SETUP and shows its event time. Entry, SL and
Target guides span the viewport so the right-edge labels do not cover the
entire line. This horizontal projection does not backdate signal eligibility.
Quote prices remain USD for BTCUSD regardless of the cash P&L preference.

A plan waiting for entry expires after the configured watch. A protective
boundary breach invalidates an untriggered plan. A triggered plan keeps its
original levels until a price boundary is observed. A chart gap cancels active
analysis rather than pretending a missed crossing was observed.

## Causality and OHLC limits

All analysis uses only supplied chart history/replay prefix. Completed HTF
candles come from the chart library `securitySeries` without lookahead, with
separate checks for expected start, end, valid OHLC and continuous native bars.
Crypto periods use UTC. Indian indices use 09:15–15:30 IST, including a
shortened final bucket. Missing candles prevent affected swing confirmations.
Transformed candles require Compute on: Underlying bars.

A candidate needs a level known before its sweep, a completed confirmation and
another candle's price range for entry. Current-bar values can update with the
feed; a forming confirmation is not declared complete early. Historical OHLC
establishes range crossings, not exact tick chronology or fills. An entry and
stop/target in the same candle, or both SL and target in a later candle, show
**AMBIGUOUS** rather than a clean success. Recalculation is deterministic for
identical history/settings. Loading more history or corrected candles can change
which earlier candidates were selected; this is chart analysis, not a durable
execution journal. No exchange orders, fees or win-rate claims are inferred.

## Legacy layers and compatibility

**Legacy · ATR swing zones** preserves the former strict pivot / 0.1 ATR band
approximation, W/M grouping, taken-zone filtering and optional open / previous
wick / body layers. Source mode is now the default for existing instances
without a marking-method setting. **Previous completed period high / low**
remains a liquidity-only source. Detailed view may show legacy context layers;
the default focused view retains the user's one-reference-per-timeframe limit.
The standalone Pine file still contains the earlier previous-period method and
has not been updated to these entry rules.

## Installation and validation

Source: `scripts/chart_indicators/htf_liquidity.js`.
Install only through the repository chart-indicator gate:

```sh
node --test test/chart_indicators/htf_liquidity.test.mjs test/chart_indicators/liquidity_setup.test.mjs
node .claude/skills/chart-indicator/validate.mjs scripts/chart_indicators/htf_liquidity.js --install
```

Tests cover higher-timeframe continuity, sessions, replay, fixed selection,
manual activation, long/short sequences, unclosed confirmation, dojis, equality,
no opposing target, tick rounding, expiry, invalidation, ambiguity, continuation
opposing-target exclusion and frozen plans. Source and prior installed runtime
are backed up under `log/backups/liquidity-20261018-source/`. Indicator-only
updates require a page reload, no frontend build or server restart.
