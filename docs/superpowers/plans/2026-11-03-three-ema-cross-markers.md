# Three EMA X markers

Goal: Correct X display to match the user's video strategy, rather than plotting every9/15 cross.

User requests a specific correction; no new trading behavior is requested. Preserve the approved three-EMA Auto strategy and its1m/5m execution rules.

- [x] Share closed-chart-bar triple alignment event detection with the existing three_ema detector. Backend returns `alignment_crosses` separately from legacy9/15 `crosses`; preserve old response contracts. Chart events use displayed timeframe without claiming full1m/5m Auto eligibility.
- [x] Send OHLC plus interval from EmaLiveLayer; request backend confirmation at candle close. Never derive a triple X from two-average data, forming candles, missing OHLC, old backend responses or noncontiguous evidence.
- [x] Paint existing large green/red X primitive using only backend triple events, at average9/21 price on confirmationbar. Keep legacy9/15 trend/exit calculations unchanged. User phrase allthree means confirmation involves all3, not falsely forcing disjointEMA lines to intersect at one point.
- [x] TDD for9/15-onlycrossabsence, delayedtripleordering/gaps/slopes, closedbarfilter, firstqualifieridentity, asyncstaleness, finalbarclose and revisioncorrections. Validate sharedAuto detector remains unchanged by chart path.
- [x] Review, focusedtests,build,hashpublication,healthverification. No agent-created liveorders or new Auto toggles.

Verified610backend+24subtests,721frontend,tsc/build,independentreview,44signalAuto-parity,healthpass,servedhashmatches. Browserrefresh remainsuser-owned; no testorders.
