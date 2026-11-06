# Market screener integration design

Date: 31 October 2026, Asia/Kolkata.
Status: approved direction on 31 October 2026: separate screener page plus chart candlestick-pattern setup. Implement inline in the existing running checkout.

## Intent and existing constraints

The user asked us to inspect Tradomate's screener and apply useful features to OpenAlgo. Earlier instructions require the existing OpenAlgo appearance, a full-size chart, fast calculations, all supported symbol classes, CE/PE premium semantics, crypto LONG/SHORT labels, closed-bar signals and exact gross 1:2 chart plans. Scope remains analytical chart signals and research; connecting filters to order placement is excluded.

The running checkout is `/Users/nmandal/.codex/worktrees/neo-native/openalgo`; preserve unrelated work. The application uses React, TanStack Query, existing UI primitives, a Flask backend, owner-scoped SQLite watchlists and Historify history. The chart study engines and contract/session metadata already exist. There is no screener route or shared custom-rule builder in the inspected application. The existing native replay job validates NIFTY option datasets only; it is not a general universe backtester. A scanner architecture document exists, but does not establish a running market-wide scanner.

## Approaches

1. **Dedicated Screener page, recommended proposal.** A full-width discovery workspace at `/screener` with a link to the current chart. This fits the user's requirement to preserve chart space and allows a readable result table. It requires a rule evaluator, data-coverage service, saved-screen persistence and navigation support.
2. **Panel inside the chart.** Smaller initial integration and immediate chart selection, but limited room for rules/results and conflicts with the repeated request to keep the chart visible. Not recommended.
3. **Complete research platform.** Adds screener, generic historical validation, universe backtesting, news, fundamentals, sectors and seasonality together. This requires additional verified datasets/providers and a larger general-purpose research engine. Recommended as later stages rather than an implied one-step clone.

The scope-choice question has been presented to the user. Approach 1 is our recommendation, not a choice already made by the user. Approval of this design would select Approach 1 and the first-release scope below. If the user chooses another approach, revise this document before implementation.

## Reference evidence and access limits

The public screener showed 70 screens grouped into technical, candle, news, price-action, reversal, volume and fundamental categories. We inspected a public EMA preset's visible condition tree and result table. It offers previous-bar comparisons, nested logical choices, universe/exchange/sector controls, result search/sorting, column customization, export, saving and alerts. Some actions require sign-in; the column editor displayed a sign-in requirement, and historical validation/backtest actions were disabled. No login, account creation or paid feature access was attempted. [Public screener](https://tradomate.one/screener/), [public EMA example](https://tradomate.one/screener/screen/ema-crossover).

Official documentation confirms editable rule creation, natural-language assistance, personal universes and saved screens. Our first release uses an explicit rule builder; unconstrained natural-language strategy generation is a later feature. [Screener guide](https://tradomate.one/docs/quick-start-screener/).

Their validation guide distinguishes analysis of today's matching stocks from a market-wide historical scan and shows per-symbol occurrences and trade/return analysis. [Validation guide](https://tradomate.one/docs/quick-start-stocks-validation/).

The backtest guide describes history-wide occurrences, holding-period comparisons and result visualizations. These are separate from our existing NIFTY-only replay. [Backtest guide](https://tradomate.one/docs/quick-start-screener-backtesting/).

Their alert guide covers saved-screen matches and watchlist/company conditions, with settings and trigger history. Our initial adaptation uses in-app alerts and the user's existing sound preferences. External delivery remains a separate opt-in feature. [Alert guide](https://tradomate.one/docs/quick-start-alerts/).

News, financial statements, corporate events, sector fundamentals and seasonality are adjacent features, requiring their own source coverage. The vendor states it uses delayed exchange data and a fundamentals vendor. We will use our own authorized data sources. [Feature overview](https://tradomate.one/features/).

## First-release behavior

### Discovery and screens

Add a lazy-loaded Screener page within the application's existing authenticated navigation. Reuse current typography, controls, colors and spacing. No new visual theme, third-party branding or cloned marketing assets. A compact header contains universe, timeframe, data timestamp, refresh/cancel and saved-screen selection. The page holds presets, an expandable rule builder and a result table. It never occupies space inside the chart.

Provide our own clearly documented presets for direction/rank, EMA and MACD crossings, RSI threshold/recovery, band breakout/re-entry, relative volume, prior-day range breaks, support/resistance proximity and the existing supported candlestick patterns. Each preset exposes its exact periods, thresholds and closed-bar basis. Do not describe our existing EMA setup as identical to a reference preset with different periods. Avoid claiming institutional positioning from price/volume alone.

User screens can be saved, renamed, duplicated and deleted, with confirmation for deletion. Conditions can be enabled/disabled, edited, copied, removed and combined with ALL/ANY groups. Initial depth is at most 3 and at most 24 leaf conditions. Periods are bounded to 1–500; node kinds/operators and numeric inputs are validated on both sides. No executable expressions or arbitrary code evaluation.

First-release fields: OHLC, volume, previous completed candle, price change, EMA/SMA, RSI, MACD components, Bollinger levels, ATR, relative volume, prior-session high/low, confirmed support/resistance and existing candlestick patterns. First-release conditions all use the selected timeframe; mixing timeframes inside a rule is deferred. Prior-session values are explicitly daily context. Thresholds, comparisons and cross-above/cross-below rules have precise previous/current closed-bar definitions. A disabled or unknown field cannot silently pass.

### Universes and data truth

Initial universe choices are existing owner watchlists, downloaded symbols and an official NIFTY50 list with displayed coverage. Default to downloaded data; if the catalog is empty, show the existing watchlists and a useful data-coverage/loading action rather than fake matches. Users can include exact CE/PE contracts and supported crypto instruments in a watchlist. A broad NIFTY500/all-market picker must not imply that history is present; introduce it only with verified membership and an explicit coverage model. Sector filtering remains unavailable until reliable symbol-to-sector metadata is connected.

Each result identifies symbol, exchange, timeframe, source, observed time, last completed candle and data state. The scan uses stored Historify or previously verified cached history first. Public Delta histories support selected crypto symbols. Missing bars are missing, never forward-filled into apparent signals. Index volume or unavailable derivative metadata remains unavailable; rules depending on it cannot match.

Provide a data-coverage view and a user-triggered load/refresh for missing broker history. Do not launch a silent 500-symbol historical polling loop. Bound broker work using the configured broker's existing rate limits and at most two concurrent requests. Cancel stale screen/universe jobs and coalesce identical per-owner instrument/timeframe requests. Loading happens outside chart rendering and shows covered/pending/failed counts. The first-release scan is explicitly a snapshot of the data available, not a guaranteed continuous whole-market feed.

A signal is confirmed only from the source's own request observation and instrument session. Reuse the causal/tick/session conventions already verified for the chart. Daily date stamps and partial final-session candles need the existing handling. Crypto is continuous; commodity/currency instruments retain their sessions. Owner, app mode, rule revision, symbol/exchange, timeframe and source observation scope cache entries. Missing/stale data cannot produce new alert events.

### Results and chart handoff

Results show symbol/exchange, last completed candle price, colored signed change and percent, RSI, relative volume, direction, matching-rule explanation and source time. Session change compares that price to the preceding verified Daily close; crypto uses the UTC Daily boundary. A separate bar-change field compares adjacent completed bars. If the relevant baseline is missing, show unavailable rather than a zero change. These are snapshot values; live quote updates must carry their separate timestamp and must not change a confirmed filter result. Optional columns add other computed values; unsupported fields show unavailable. Provide stable sorting, search, configurable columns, CSV export and add-to-watchlist. Use bounded/paginated rendering and pause refreshing when the page is hidden.

A match is an analytical observation, not an executed fill. A saved screen has explicit intent: observe (the default), bullish, or bearish. Presets declare their intent and show it in the editor. A neutral volume-only rule or mixed ANY group stays MATCH unless the user explicitly assigns an intent; the evaluator does not infer an investment direction from Boolean logic. Directional columns label this as the screen's setup intent. For own-price bullish/bearish presets, use LONG setup/SHORT setup on crypto, bullish/bearish setup on other non-options, and BUY/AVOID on the selected bought option premium. No separate hidden indicator overrides the selected rules. Ranking means a disclosed sort metric (for example session percent change or relative volume), not an invented composite quality score. Option premiums display BUY/AVOID for the selected CE or PE; crypto uses LONG/SHORT. Clicking Open chart passes the exact symbol, exchange and timeframe into `/trading` through a validated URL target. The current workspace lacks this URL initialization and needs a targeted addition, including back/forward navigation. It must not briefly load NIFTY in place of the requested instrument or lose the selected strike.

Keep entry/SL/target calculations in the existing chart planner, including external-fill entry and exact gross 1:2 geometry. The scanner does not fabricate an entry, cash fee estimate or contract lot size. Open chart retains the existing full-size workspace.

### Saved screens and alerts

Persist saved definitions in an owner-scoped database, independent of browser cache. Include schema version and rule revision. Reuse watchlist ownership and session/CSRF conventions. No screen is public/shared by default.

Alerts are explicitly armed in the UI, with sound testing using the existing sound settings. Our first-release lifecycle choice is to monitor only the selected saved screen while its Screener page is visible. The UI states this before arming. Switching screens, opening the chart, hiding the tab, closing the page or losing source freshness pauses monitoring; it does not imply whole-app/background surveillance. Saved preferences do not automatically resume sounding after reload. Resuming first records a fresh match baseline without sounding historical matches.

Arming authorizes bounded automatic data refresh for this view at completed-candle boundaries, in addition to watching independently updated stored data. The existing owner/broker cache coalesces requests, and broker rate limits still apply. For this browser-only first release, broker-backed automatic monitoring is capped at25 selected instruments; larger universes remain available for explicit snapshot scans/coverage checks, or must be narrowed before arming. Display the next refresh, pending coverage and pause reason. No hidden data downloads or server daemon are created. This bounded monitoring/data acquisition policy is our proposal, not an existing user-approved behavior. Emit once when a fresh instrument first enters the matching set; rearm after a verified non-match. Deduplicate by owner/screen revision/instrument/closed-candle time. A failed/stale observation is unknown, not an exit that rearms an alert. Save trigger history with the data observation time. Browser sound works while the app is open and permitted to play audio; background server/email/WhatsApp delivery is not part of this release. Editing a rule resets its match baseline without replaying old events as new alerts. Restart/reconnect shows the current baseline without sounding for old matches.

## Later research stages and data dependencies

A second stage can add per-symbol historical occurrence validation and then universe backtesting. Evaluate each historical prefix causally, enter at a subsequent observable price, model gaps and same-bar ambiguity conservatively, separate gross2R from fees, and show sample counts, source coverage, drawdown and trade logs. Current list membership creates survivorship bias unless point-in-time membership is available and must be labelled. Never relabel the NIFTY option replay engine as a generic crypto/equity portfolio backtester.

News sentiment, fundamentals, events, sector peers, deal/holding information, long-history seasonality and free-form AI need separate provider/model decisions. No invented PE ratios, news sentiment, sector data or occurrence win rates. These are not first-release placeholders with fabricated numbers.

## Acceptance and testing

- Unit-test each comparison, crossing, ALL/ANY group, disabled condition and missing-data state; use prefix tests to prevent future-data leakage.
- Check all supported symbol classes and seven timeframes, including CE/PE mapping, FX precision, midnight Daily transport and 24/7 crypto.
- Test persistence ownership/CSRF, invalid/deep rule payloads, mode changes, reload, duplication, deletion and cancelled/replaced jobs.
- Verify chart handoff exact identity/timeframe, browser history and isolation from automated trading controls.
- Test alert enter/rearm/deduplication, stale/error observations, reconnect baselines and multiple matching symbols.
- Test coverage reporting and broker request coalescing/cancellation/rate limits. Compare supported indicator numerics with the existing chart implementation instead of introducing a second drifting formula set.
- Run focused suites, source review, complete chart regressions, type checks, build and service/asset health verification before release. Measure scanning separately from chart rendering and network time; no zero-lag claim.
- Existing local browser access was blocked in the preceding work; do not bypass that security restriction. If it remains unavailable, report the visual-interaction verification limit explicitly.

## Implementation boundaries and builder decisions

Use the existing app, dependencies and running checkout. Reuse UI primitives, shared market-data feeds and stored history. Our implementation choice is a dedicated browser Web Worker for pure rule/indicator evaluation, importing the same extracted TypeScript math as the chart. The Flask layer supplies authenticated coverage/history batches and persisted definitions/events; it does not introduce independent Python approximations of indicator formulas. A single worker per open screener caches one selected timeframe, processes bounded batches and discards replies for cancelled revisions. Stored snapshots produce results without a new market subscription. Broker fills run in bounded background work; they cannot occupy the execution/protection worker or hold a long page request open. Exact filenames/module extraction, table paging strategy, index placement under Tools versus the primary navigation, and internal service organization are left to the builder, preserving the stated behavior. Extract indicator math as needed so chart and screener share tested implementations; no independently approximated RSI/MACD logic. Do not install Redis or start a separate scanner daemon without a further deployment decision.

Implementation completed under the accepted scope below. See `docs/validation/2026-10-31-market-screener.md` for delivered behavior, verification evidence and remaining provider/visual limits.

## Builder review resolution

A read-only builder review asked about alert monitoring lifetime/fresh-data authority and how Boolean conditions determine direction. Both are now settled as explicit proposed product choices above: selected visible-screen monitoring with a bounded refresh budget; and saved directional intent with neutral MATCH as the default. These do not require the user to choose internal architecture. The integration scope was subsequently approved as recorded below.

## Accepted scope and execution

The user selected “separate screener page + chart candlestick pattern setup”. This authorizes the recommended first-release integration and a chart pattern-family selector, shared with screener pattern rules and chart handoff. Reuse/extend causal candle recognition, risk geometry and evidence identity; expose only implemented pattern families. The implementer will proceed inline without another execution-method permission round, preserve unrelated changes and make no commits or pushes. Additional data-provider research stages remain outside this release.
